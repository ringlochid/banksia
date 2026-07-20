from __future__ import annotations

import ast
from pathlib import Path

from .models import AuditSettings, FunctionSizeViolation, ModuleRecord
from .module_loader import count_non_comment_lines


def collect_file_line_violations(
    modules: list[ModuleRecord],
    settings: AuditSettings,
) -> tuple[tuple[Path, int], ...]:
    return tuple(
        sorted(
            (
                (module.path, len(module.lines))
                for module in modules
                if len(module.lines) > settings.file_split_review_threshold
            ),
            key=lambda item: (-item[1], item[0].as_posix()),
        )
    )


def collect_function_size_violations(
    modules: list[ModuleRecord],
    function_size_threshold: int,
) -> tuple[FunctionSizeViolation, ...]:
    violations: list[FunctionSizeViolation] = []
    for module in modules:
        for node in ast.walk(module.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end_line = node.end_lineno or node.lineno
            non_comment_lines = count_non_comment_lines(module.lines, node.lineno, end_line)
            if non_comment_lines <= function_size_threshold:
                continue
            violations.append(
                FunctionSizeViolation(
                    path=module.path,
                    name=node.name,
                    line=node.lineno,
                    non_comment_lines=non_comment_lines,
                )
            )
    return tuple(
        sorted(
            violations,
            key=lambda violation: (
                -violation.non_comment_lines,
                violation.path.as_posix(),
                violation.line,
                violation.name,
            ),
        )
    )
