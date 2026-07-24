from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import httpx
import pytest
import yaml
from click import Group
from click.testing import CliRunner, Result

import banksia.interfaces.cli.commands.task as task_command_module
from banksia.interfaces.cli import build_parser
from banksia.interfaces.cli import main as cli_main
from banksia.interfaces.cli.commands.task import TaskStartCliError


def test_workflow_cli_imports_draft_and_exports_normalized_published_truth(
    tmp_path: Path,
) -> None:
    runner, parser, config_path = _initialized_cli(tmp_path)
    workflow_path = tmp_path / "cli-workflow.yml"
    workflow_path.write_text(
        """
kind: workflow
id: cli-authoring
description: CLI draft import proof.
lead: {id: lead}
""".lstrip(),
        encoding="utf-8",
    )
    imported = _invoke_import(runner, parser, config_path, workflow_path)
    assert imported.exit_code == 0, imported.output
    imported_payload = json.loads(imported.output)
    assert imported_payload["is_created"] is True
    assert imported_payload["draft"]["workflow_id"] == "cli-authoring"
    assert imported_payload["undo_receipt"] is None

    workflow_path.write_text(
        workflow_path.read_text(encoding="utf-8").replace(
            "CLI draft import proof.",
            "CLI updated draft import proof.",
        ),
        encoding="utf-8",
    )
    missing_etag = _invoke_import(runner, parser, config_path, workflow_path)
    assert missing_etag.exit_code == 1
    assert "current ETag is required" in str(missing_etag.exception)

    updated = _invoke_import(
        runner,
        parser,
        config_path,
        workflow_path,
        expected_etag=imported_payload["draft"]["etag"],
    )
    assert updated.exit_code == 0, updated.output
    updated_payload = json.loads(updated.output)
    assert updated_payload["is_created"] is False
    assert updated_payload["undo_receipt"].startswith("workflow-undo.")

    exported = runner.invoke(
        parser,
        [
            "workflow",
            "export",
            "reviewed-delivery",
            "--config",
            str(config_path),
            "--format",
            "yaml",
        ],
    )
    assert exported.exit_code == 0, exported.output
    exported_payload = yaml.safe_load(exported.output)
    assert exported_payload["id"] == "reviewed-delivery"
    assert exported_payload["kind"] == "workflow"


def test_workflow_cli_stdin_never_guesses_format() -> None:
    result = CliRunner().invoke(
        build_parser(),
        ["workflow", "import", "--file", "-"],
        input='{"kind":"workflow"}',
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert "stdin import requires --format" in str(result.exception)


def test_task_start_cli_machine_mode_posts_strict_json_and_prints_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, parser, config_path = _initialized_cli(tmp_path)
    captured: list[tuple[str, str, dict[str, Any]]] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def request(
            self,
            method: str,
            path: str,
            **kwargs: Any,
        ) -> httpx.Response:
            captured.append((method, path, kwargs))
            return httpx.Response(
                200,
                request=httpx.Request(method, f"http://127.0.0.1{path}"),
                json={
                    "receipt_id": "receipt.task-start",
                    "status": "accepted",
                    "task_id": "t_01234567",
                    "workflow_id": "reviewed-delivery",
                    "workflow_revision": 1,
                    "workspace": str(tmp_path),
                    "manifest": ".banksia/t_01234567/manifest.md",
                },
            )

    monkeypatch.setattr(task_command_module.httpx, "AsyncClient", FakeAsyncClient)
    machine = runner.invoke(
        parser,
        [
            "task",
            "start",
            "--config",
            str(config_path),
            "--json",
            json.dumps(
                {
                    "workflow": "reviewed-delivery",
                    "prompt": "Complete the requested work.",
                    "workspace": str(tmp_path),
                }
            ),
        ],
    )

    assert machine.exit_code == 0, machine.output
    payload = json.loads(machine.output)
    assert payload["status"] == "accepted"
    assert payload["task_id"] == "t_01234567"
    assert captured[0][0:2] == ("POST", "/tasks")
    assert captured[0][2]["json"] == {
        "workflow": "reviewed-delivery",
        "prompt": "Complete the requested work.",
        "workspace": str(tmp_path),
        "files": [],
    }


async def test_task_start_cli_interactive_mode_uses_workflow_choice_and_editor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InteractiveInput:
        @staticmethod
        def isatty() -> bool:
            return True

    class CatalogClient:
        async def request(
            self,
            method: str,
            path: str,
            **kwargs: Any,
        ) -> httpx.Response:
            assert (method, path, kwargs) == ("GET", "/workflows", {})
            return httpx.Response(
                200,
                request=httpx.Request(method, f"http://127.0.0.1{path}"),
                json={
                    "items": [
                        {
                            "workflow_id": "reviewed-delivery",
                            "description": "Review and refine a bounded delivery.",
                            "published_revision_no": 1,
                            "provenance": "starter_seed",
                        }
                    ]
                },
            )

    choices: list[tuple[str, tuple[str, ...]]] = []

    def choose(
        label: str,
        *,
        type: Any,
        show_choices: bool,
    ) -> str:
        assert show_choices is True
        choices.append((label, tuple(type.choices)))
        return "reviewed-delivery"

    monkeypatch.setattr(task_command_module.sys, "stdin", InteractiveInput())
    monkeypatch.setattr(task_command_module.click, "prompt", choose)
    editor_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def edit(*args: object, **kwargs: object) -> str:
        editor_calls.append((args, kwargs))
        return "Complete  this request.\r\nPreserve detail.\r"

    monkeypatch.setattr(task_command_module.click, "edit", edit)

    request = await task_command_module.prompt_for_task_start_request(
        CatalogClient(),  # type: ignore[arg-type]
        invocation_cwd=tmp_path,
    )

    assert choices == [("Workflow", ("reviewed-delivery",))]
    assert editor_calls == [(("",), {"require_save": True, "extension": ".md"})]
    assert request.model_dump(mode="json") == {
        "workflow": "reviewed-delivery",
        "prompt": "Complete  this request.\nPreserve detail.\n",
        "workspace": str(tmp_path),
        "files": [],
    }


@pytest.mark.parametrize("editor_result", [None, "", " \r\n "])
async def test_task_start_cli_interactive_abort_or_blank_never_builds_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    editor_result: str | None,
) -> None:
    class InteractiveInput:
        @staticmethod
        def isatty() -> bool:
            return True

    class CatalogClient:
        async def request(
            self,
            method: str,
            path: str,
            **kwargs: Any,
        ) -> httpx.Response:
            del kwargs
            return httpx.Response(
                200,
                request=httpx.Request(method, f"http://127.0.0.1{path}"),
                json={
                    "items": [
                        {
                            "workflow_id": "reviewed-delivery",
                            "description": "Review and refine a bounded delivery.",
                            "published_revision_no": 1,
                            "provenance": "starter_seed",
                        }
                    ]
                },
            )

    monkeypatch.setattr(task_command_module.sys, "stdin", InteractiveInput())
    monkeypatch.setattr(
        task_command_module.click, "prompt", lambda *args, **kwargs: "reviewed-delivery"
    )
    monkeypatch.setattr(task_command_module.click, "edit", lambda *args, **kwargs: editor_result)

    with pytest.raises(click.Abort):
        await task_command_module.prompt_for_task_start_request(
            CatalogClient(),  # type: ignore[arg-type]
            invocation_cwd=tmp_path,
        )


@pytest.mark.parametrize(
    ("source_kind", "source_text"),
    [
        ("inline", '{"workflow":"reviewed-delivery","workflow":"duplicate","prompt":"x"}'),
        ("inline", '{"workflow":"reviewed-delivery","prompt":"x","value":NaN}'),
        ("file", '{"workflow":'),
        ("stdin", "[]"),
        ("malformed_at", ""),
    ],
)
def test_task_start_machine_json_failures_use_one_stable_error_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
    source_text: str,
) -> None:
    if source_kind == "file":
        source_path = tmp_path / "request.json"
        source_path.write_text(source_text, encoding="utf-8")
        source = f"@{source_path}"
    elif source_kind == "stdin":
        monkeypatch.setattr(
            task_command_module.sys,
            "stdin",
            type("Input", (), {"read": lambda self: source_text})(),
        )
        source = "-"
    elif source_kind == "malformed_at":
        source = "@"
    else:
        source = source_text

    with pytest.raises(TaskStartCliError) as failure:
        task_command_module.parse_task_start_json_request(
            source,
            invocation_cwd=tmp_path,
        )

    assert failure.value.kind == "task_start_json_invalid"
    assert failure.value.hint == (
        "Provide one strict JSON object inline, as @file, or on stdin with '-'."
    )


@pytest.mark.parametrize(
    ("payload", "field_path"),
    [
        ({"workflow": "reviewed-delivery", "prompt": 7}, "prompt"),
        (
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "files": [{"path": 7}],
            },
            "files.0.path",
        ),
        (
            {
                "workflow": "reviewed-delivery",
                "prompt": "Do the work.",
                "files": [{"path": "brief.md", "description": 7}],
            },
            "files.0.description",
        ),
    ],
)
def test_task_start_machine_json_wrong_types_use_typed_request_failure(
    tmp_path: Path,
    payload: dict[str, object],
    field_path: str,
) -> None:
    with pytest.raises(TaskStartCliError) as failure:
        task_command_module.parse_task_start_json_request(
            json.dumps(payload),
            invocation_cwd=tmp_path,
        )

    assert failure.value.kind == "task_start_request_invalid"
    assert str(failure.value).startswith(f"{field_path}: ")
    assert failure.value.hint == "Correct the named TaskStartRequest field and retry."


def test_task_start_machine_json_failure_uses_public_json_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _runner, _parser, config_path = _initialized_cli(tmp_path)

    exit_code = cli_main(
        [
            "task",
            "start",
            "--config",
            str(config_path),
            "--json",
            '{"workflow":"reviewed-delivery","workflow":"duplicate","prompt":"x"}',
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "ok": False,
        "error": {
            "kind": "task_start_json_invalid",
            "message": "Task-start JSON could not be read: duplicate JSON key: workflow",
            "hint": "Provide one strict JSON object inline, as @file, or on stdin with '-'.",
            "details": {},
        },
    }


def test_task_start_machine_json_null_workspace_resolves_to_invocation_cwd(
    tmp_path: Path,
) -> None:
    request = task_command_module.parse_task_start_json_request(
        '{"workflow":"reviewed-delivery","prompt":"Exact prompt.","workspace":null}',
        invocation_cwd=tmp_path,
    )

    assert request.workspace == tmp_path.resolve()


def _initialized_cli(tmp_path: Path) -> tuple[CliRunner, Group, Path]:
    runner = CliRunner()
    parser = build_parser()
    config_path = tmp_path / "config.toml"
    initialized = runner.invoke(
        parser,
        [
            "init",
            "--config",
            str(config_path),
            "--data-dir",
            str(tmp_path / "data"),
            "--force",
            "--non-interactive",
            "--json",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    return runner, parser, config_path


def _invoke_import(
    runner: CliRunner,
    parser: Group,
    config_path: Path,
    workflow_path: Path,
    *,
    expected_etag: str | None = None,
) -> Result:
    arguments = [
        "workflow",
        "import",
        "--config",
        str(config_path),
        "--file",
        str(workflow_path),
        "--json",
    ]
    if expected_etag is not None:
        arguments.extend(("--etag", expected_etag))
    return runner.invoke(parser, arguments)
