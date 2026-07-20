from __future__ import annotations

import ast
from pathlib import Path

from .models import AuditSettings, ModuleRecord, PublicNamingFinding

WEAK_PUBLIC_VERBS = ("handle", "process", "run", "do", "apply", "check")
FACT_SHAPED_PREFIXES = ("is_", "has_", "should_", "can_")


def collect_public_naming_findings(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> tuple[PublicNamingFinding, ...]:
    findings: list[PublicNamingFinding] = []
    for module in modules:
        if not _should_scan_module(module, settings):
            continue
        findings.extend(
            finding
            for finding in _module_public_naming_findings(module)
            if (finding.path, finding.name) not in settings.approved_public_naming_exceptions
        )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (finding.path.as_posix(), finding.line, finding.name),
        )
    )


def _module_public_naming_findings(module: ModuleRecord) -> list[PublicNamingFinding]:
    findings: list[PublicNamingFinding] = []
    for node in module.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            findings.extend(_function_naming_findings(module.path, node, "function"))
            continue
        if isinstance(node, ast.ClassDef):
            findings.extend(_class_public_naming_findings(module.path, node))
            continue
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        boolean_name = _public_boolean_name(node)
        if boolean_name is None or boolean_name.startswith(FACT_SHAPED_PREFIXES):
            continue
        findings.append(
            PublicNamingFinding(
                path=module.path,
                line=node.lineno,
                name=boolean_name,
                kind="boolean",
                reason="public_boolean_not_fact_shaped",
            )
        )
    return findings


def _class_public_naming_findings(path: Path, node: ast.ClassDef) -> list[PublicNamingFinding]:
    findings: list[PublicNamingFinding] = []
    for child in node.body:
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            field_name = _public_boolean_name(child)
            if field_name is not None and not field_name.startswith(FACT_SHAPED_PREFIXES):
                findings.append(
                    PublicNamingFinding(
                        path=path,
                        line=child.lineno,
                        name=field_name,
                        kind="field",
                        reason="public_boolean_not_fact_shaped",
                    )
                )
            continue
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if child.name.startswith("_") and child.name != "__init__":
            continue
        kind = "method" if child.name != "__init__" else "constructor"
        findings.extend(_function_naming_findings(path, child, kind))
    return findings


def _function_naming_findings(
    path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    kind: str,
) -> list[PublicNamingFinding]:
    findings: list[PublicNamingFinding] = []
    if node.name != "__init__" and _starts_with_weak_public_verb(node.name):
        findings.append(
            PublicNamingFinding(
                path=path,
                line=node.lineno,
                name=node.name,
                kind=kind,
                reason="weak_public_verb",
            )
        )
    findings.extend(_boolean_parameter_findings(path, node, kind))
    return findings


def _starts_with_weak_public_verb(name: str) -> bool:
    first_token = name.split("_", maxsplit=1)[0]
    return first_token in WEAK_PUBLIC_VERBS


def _boolean_parameter_findings(
    path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    kind: str,
) -> list[PublicNamingFinding]:
    findings: list[PublicNamingFinding] = []
    positional_arguments = list(node.args.posonlyargs) + list(node.args.args)
    positional_defaults = [None] * (len(positional_arguments) - len(node.args.defaults)) + list(
        node.args.defaults
    )
    for argument, default in zip(positional_arguments, positional_defaults, strict=False):
        finding = _parameter_boolean_finding(path, argument, default, kind)
        if finding is not None:
            findings.append(finding)
    for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=False):
        finding = _parameter_boolean_finding(path, argument, default, kind)
        if finding is not None:
            findings.append(finding)
    return findings


def _parameter_boolean_finding(
    path: Path,
    argument: ast.arg,
    default: ast.expr | None,
    kind: str,
) -> PublicNamingFinding | None:
    if argument.arg in {"self", "cls"} or argument.arg.startswith("_"):
        return None
    annotation = argument.annotation
    if annotation is not None and _annotation_is_boolean(annotation):
        if argument.arg.startswith(FACT_SHAPED_PREFIXES):
            return None
        return PublicNamingFinding(
            path=path,
            line=argument.lineno,
            name=argument.arg,
            kind=f"{kind}-parameter",
            reason="public_boolean_not_fact_shaped",
        )
    if default is None or not _expression_is_boolean(default):
        return None
    if argument.arg.startswith(FACT_SHAPED_PREFIXES):
        return None
    return PublicNamingFinding(
        path=path,
        line=argument.lineno,
        name=argument.arg,
        kind=f"{kind}-parameter",
        reason="public_boolean_not_fact_shaped",
    )


def _should_scan_module(module: ModuleRecord, settings: AuditSettings) -> bool:
    if module.path in settings.public_naming_extra_modules:
        return True
    return any(module.path.is_relative_to(root) for root in settings.public_naming_scan_roots)


def _public_boolean_name(node: ast.Assign | ast.AnnAssign) -> str | None:
    value: ast.expr | None
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        name = node.targets[0].id
        value = node.value
    else:
        if not isinstance(node.target, ast.Name):
            return None
        name = node.target.id
        value = node.value
        if _annotation_is_boolean(node.annotation):
            return name if not name.startswith("_") else None
    if name.startswith("_") or name == "__all__":
        return None
    return name if _expression_is_boolean(value) else None


def _annotation_is_boolean(annotation: ast.expr) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "bool"
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == "bool"
    if isinstance(annotation, ast.Constant):
        return annotation.value is bool
    if _annotation_is_none(annotation):
        return False
    if isinstance(annotation, ast.Subscript):
        base = annotation.value
        if isinstance(base, ast.Name) and base.id in {"Optional", "Literal"}:
            slice_value = annotation.slice
            if base.id == "Optional":
                return _annotation_is_boolean(slice_value)
            if isinstance(slice_value, ast.Tuple):
                return all(
                    isinstance(element, ast.Constant) and isinstance(element.value, bool)
                    for element in slice_value.elts
                )
        return False
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left_is_boolean = _annotation_is_boolean(annotation.left)
        right_is_boolean = _annotation_is_boolean(annotation.right)
        left_is_none = _annotation_is_none(annotation.left)
        right_is_none = _annotation_is_none(annotation.right)
        return (
            (left_is_boolean and right_is_boolean)
            or (left_is_boolean and right_is_none)
            or (right_is_boolean and left_is_none)
        )
    return False


def _annotation_is_none(annotation: ast.expr) -> bool:
    return (isinstance(annotation, ast.Constant) and annotation.value is None) or (
        isinstance(annotation, ast.Name) and annotation.id == "None"
    )


def _expression_is_boolean(value: ast.expr | None) -> bool:
    if value is None:
        return False
    if isinstance(value, ast.Constant):
        return isinstance(value.value, bool)
    if isinstance(value, ast.Call):
        return isinstance(value.func, ast.Name) and value.func.id == "bool"
    if isinstance(value, ast.Compare):
        return True
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not):
        return True
    if isinstance(value, ast.BoolOp):
        return all(_expression_is_boolean(operand) for operand in value.values)
    return False
