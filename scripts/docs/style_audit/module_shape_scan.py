from __future__ import annotations

import ast

from .models import AuditSettings, ModuleRecord, ModuleShapeFinding


def collect_module_shape_findings(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> tuple[ModuleShapeFinding, ...]:
    findings: list[ModuleShapeFinding] = []
    for module in modules:
        if not _should_scan_module(module, settings):
            continue
        findings.extend(_module_shape_findings(module))
    return tuple(
        sorted(
            findings,
            key=lambda finding: (finding.path.as_posix(), finding.line, finding.name),
        )
    )


def _module_shape_findings(module: ModuleRecord) -> list[ModuleShapeFinding]:
    findings: list[ModuleShapeFinding] = []
    first_function_seen = False
    private_helper_seen = False
    public_functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    for node in module.tree.body:
        if _is_docstring_node(node) or _is_future_import(node) or _is_type_checking_block(node):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if _is_export_assignment(node):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first_function_seen = True
            if node.name.startswith("_"):
                private_helper_seen = True
                continue
            if private_helper_seen:
                findings.append(
                    ModuleShapeFinding(
                        path=module.path,
                        line=node.lineno,
                        name=node.name,
                        reason="public_after_private_helper",
                    )
                )
            public_functions.append(node)
            continue
        if first_function_seen and _is_top_level_declaration(node):
            findings.append(
                ModuleShapeFinding(
                    path=module.path,
                    line=node.lineno,
                    name=_node_display_name(node),
                    reason="declaration_after_function_block",
                )
            )

    findings.extend(_public_helper_order_findings(module, public_functions))
    return findings


def _public_helper_order_findings(
    module: ModuleRecord,
    public_functions: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[ModuleShapeFinding]:
    findings: list[ModuleShapeFinding] = []
    earlier_public_names: list[str] = []
    for function in public_functions:
        referenced_names = _referenced_outer_names(function)
        if any(name in referenced_names for name in earlier_public_names):
            findings.append(
                ModuleShapeFinding(
                    path=module.path,
                    line=function.lineno,
                    name=function.name,
                    reason="public_after_shared_helper",
                )
            )
        earlier_public_names.append(function.name)
    return findings


def _referenced_outer_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    bound_names = _bound_local_names(function)
    referenced_names: set[str] = set()
    nodes_to_scan = [*function.args.defaults, *function.args.kw_defaults, *function.body]
    for node in nodes_to_scan:
        if node is None:
            continue
        for child in _iter_nodes_without_nested_scopes(node):
            if not isinstance(child, ast.Name) or not isinstance(child.ctx, ast.Load):
                continue
            if child.id in bound_names:
                continue
            referenced_names.add(child.id)
    return referenced_names


def _bound_local_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    bound_names = {
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
    }
    if function.args.vararg is not None:
        bound_names.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        bound_names.add(function.args.kwarg.arg)

    for node in _iter_nodes_without_nested_scopes(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for target in _assignment_targets(node):
                bound_names.update(_target_names(target))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            bound_names.update(_target_names(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    bound_names.update(_target_names(item.optional_vars))
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            bound_names.add(node.name)
    return bound_names


def _assignment_targets(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    return (node.target,)


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_target_names(element))
        return names
    return set()


def _iter_nodes_without_nested_scopes(node: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    stack = [node]
    while stack:
        current = stack.pop()
        nodes.append(current)
        children = list(ast.iter_child_nodes(current))
        for child in reversed(children):
            if child is not node and isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
            ):
                continue
            stack.append(child)
    return nodes


def _should_scan_module(module: ModuleRecord, settings: AuditSettings) -> bool:
    if module.path in settings.module_shape_excluded_modules or "tests" in module.path.parts:
        return False
    return any(module.path.is_relative_to(root) for root in settings.module_shape_scan_roots)


def _is_docstring_node(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_export_assignment(node: ast.stmt) -> bool:
    if isinstance(node, ast.Assign):
        return (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
        )
    return (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "__all__"
    )


def _is_future_import(node: ast.stmt) -> bool:
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _is_type_checking_block(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
        and all(isinstance(child, (ast.Import, ast.ImportFrom)) for child in node.body)
    )


def _is_top_level_declaration(node: ast.stmt) -> bool:
    return isinstance(node, (ast.Assign, ast.AnnAssign, ast.ClassDef, ast.TypeAlias))


def _node_display_name(node: ast.stmt) -> str:
    if isinstance(node, ast.ClassDef):
        return node.name
    if isinstance(node, ast.TypeAlias):
        return ast.unparse(node.name)
    if isinstance(node, ast.Assign):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
        return ast.unparse(node.targets[0])
    if isinstance(node, ast.AnnAssign):
        return ast.unparse(node.target)
    return ast.unparse(node)
