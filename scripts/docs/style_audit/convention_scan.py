from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from .models import ImportPlacementFinding, ModuleRecord, TodoCommentFinding, WildcardImportFinding

TODO_COMMENT_PATTERN = re.compile(r"#\s*(TODO|FIXME|XXX)\b(?P<body>.*)", re.IGNORECASE)
TODO_REQUIREMENT_PATTERN = re.compile(
    r"(@[A-Za-z0-9_/-]+|#[0-9]+|\b(issue|phase|wp|work[- ]package|owner|remove|until|after)\b)",
    re.IGNORECASE,
)


def collect_import_placement_findings(
    modules: list[ModuleRecord],
) -> list[ImportPlacementFinding]:
    findings: list[ImportPlacementFinding] = []
    for module in modules:
        saw_non_import = False
        for node in module.tree.body:
            if _is_docstring_node(node) or _is_future_import(node):
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if saw_non_import:
                    findings.append(
                        ImportPlacementFinding(
                            path=module.path,
                            line=node.lineno,
                            statement=ast.unparse(node),
                        )
                    )
                continue
            if _is_export_assignment(node):
                continue
            saw_non_import = True
    return sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.line))


def collect_wildcard_import_findings(modules: list[ModuleRecord]) -> list[WildcardImportFinding]:
    findings: list[WildcardImportFinding] = []
    for module in modules:
        if module.path.name == "__init__.py":
            continue
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not any(alias.name == "*" for alias in node.names):
                continue
            findings.append(
                WildcardImportFinding(
                    path=module.path,
                    line=node.lineno,
                    source=_format_import_from_source(node),
                )
            )
    return sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.line))


def collect_todo_comment_findings(modules: list[ModuleRecord]) -> list[TodoCommentFinding]:
    findings: list[TodoCommentFinding] = []
    for module in modules:
        source = "\n".join(module.lines)
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            match = TODO_COMMENT_PATTERN.match(token.string)
            if match is None:
                continue
            body = match.group("body")
            if TODO_REQUIREMENT_PATTERN.search(body):
                continue
            findings.append(
                TodoCommentFinding(
                    path=module.path,
                    line=token.start[0],
                    text=token.string.strip(),
                )
            )
    return sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.line))


def collect_relative_import_depth_findings(
    modules: list[ModuleRecord],
) -> tuple[ImportPlacementFinding, ...]:
    findings: list[ImportPlacementFinding] = []
    for module in modules:
        if _is_test_module(module.path):
            continue
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level < 3:
                continue
            findings.append(
                ImportPlacementFinding(
                    path=module.path,
                    line=node.lineno,
                    statement=_format_import_from_statement(node),
                )
            )
    return tuple(sorted(findings, key=lambda finding: (finding.path.as_posix(), finding.line)))


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


def _format_import_from_source(node: ast.ImportFrom) -> str:
    module_name = node.module or ""
    return f"{'.' * node.level}{module_name}" or "<unknown>"


def _format_import_from_statement(node: ast.ImportFrom) -> str:
    imported_names = ", ".join(alias.name for alias in node.names)
    return f"from {_format_import_from_source(node)} import {imported_names}"


def _is_test_module(path: Path) -> bool:
    return "tests" in path.parts
