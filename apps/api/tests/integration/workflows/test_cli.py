from __future__ import annotations

import json
from pathlib import Path

import yaml
from banksia.interfaces.cli import build_parser
from click import Group
from click.testing import CliRunner, Result


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


def test_task_compose_cli_starts_current_workflow_in_human_and_json_modes(
    tmp_path: Path,
) -> None:
    runner, parser, config_path = _initialized_cli(tmp_path)
    task_compose_path = tmp_path / "task-compose.yaml"
    task_compose_path.write_text(
        """
task:
  key: cli-workflow-start
  title: CLI Workflow start
  summary: Exercise the bounded Task Compose bridge.
workflow:
  key: reviewed-delivery
""".lstrip(),
        encoding="utf-8",
    )

    human = runner.invoke(
        parser,
        [
            "task-compose",
            "start",
            "--config",
            str(config_path),
            "--file",
            str(task_compose_path),
        ],
    )
    machine = runner.invoke(
        parser,
        [
            "task-compose",
            "start",
            "--config",
            str(config_path),
            "--file",
            str(task_compose_path),
            "--json",
        ],
    )

    assert human.exit_code == 0, human.output
    assert "started task: task_cli-workflow-start_" in human.output
    assert "flow status: running" in human.output
    assert machine.exit_code == 0, machine.output
    payload = json.loads(machine.output)
    assert payload["task_id"].startswith("task_cli-workflow-start_")
    assert payload["flow_status"] == "running"


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
