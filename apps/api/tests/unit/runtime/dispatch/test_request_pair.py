from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.dispatch.request_pair import publish_dispatch_request_pair


def test_request_pair_publishes_complete_immutable_bytes_and_logical_refs(
    tmp_path: Path,
) -> None:
    paths = task_root_paths(tmp_path / "task")

    refs = publish_dispatch_request_pair(
        paths=paths,
        dispatch_id="dispatch.alpha-1",
        instructions_bytes=b"# Instructions\n\nStay bounded.\n",
        input_bytes=b"# Input\n\nExact committed snapshot.\n",
    )

    dispatch_directory = paths.dispatch_path / "dispatch.alpha-1"
    assert refs.instructions_logical_path == ("_runtime/dispatch/dispatch.alpha-1/instructions.md")
    assert refs.input_logical_path == "_runtime/dispatch/dispatch.alpha-1/input.md"
    assert {path.name for path in dispatch_directory.iterdir()} == {
        "instructions.md",
        "input.md",
    }
    assert (dispatch_directory / "instructions.md").read_bytes() == (
        b"# Instructions\n\nStay bounded.\n"
    )
    assert (dispatch_directory / "input.md").read_bytes() == (
        b"# Input\n\nExact committed snapshot.\n"
    )
    assert stat.S_ISREG((dispatch_directory / "instructions.md").stat().st_mode)
    assert stat.S_ISREG((dispatch_directory / "input.md").stat().st_mode)


def test_request_pair_never_overwrites_an_existing_dispatch_directory(
    tmp_path: Path,
) -> None:
    paths = task_root_paths(tmp_path / "task")
    original_instructions = b"original instructions"
    original_input = b"original input"
    publish_dispatch_request_pair(
        paths=paths,
        dispatch_id="dispatch.immutable",
        instructions_bytes=original_instructions,
        input_bytes=original_input,
    )

    with pytest.raises(FileExistsError, match="dispatch request directory already exists"):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id="dispatch.immutable",
            instructions_bytes=b"replacement instructions",
            input_bytes=b"replacement input",
        )

    dispatch_directory = paths.dispatch_path / "dispatch.immutable"
    assert (dispatch_directory / "instructions.md").read_bytes() == original_instructions
    assert (dispatch_directory / "input.md").read_bytes() == original_input


def test_request_pair_preserves_a_directory_created_by_a_competing_publisher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = task_root_paths(tmp_path / "task")
    final_directory = paths.dispatch_path / "dispatch.race"
    original_mkdir = os.mkdir

    def lose_directory_claim(path: Path, mode: int = 0o777) -> None:
        if Path(path) == final_directory:
            original_mkdir(path, mode)
            (final_directory / "winner").write_text("preserve me", encoding="utf-8")
            raise FileExistsError(path)
        original_mkdir(path, mode)

    monkeypatch.setattr(os, "mkdir", lose_directory_claim)

    with pytest.raises(FileExistsError):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id="dispatch.race",
            instructions_bytes=b"losing instructions",
            input_bytes=b"losing input",
        )

    assert (final_directory / "winner").read_text(encoding="utf-8") == "preserve me"


def test_request_pair_removes_only_its_staging_directory_on_known_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = task_root_paths(tmp_path / "task")
    paths.dispatch_path.mkdir(parents=True)
    unrelated = paths.dispatch_path / ".unrelated-stage"
    unrelated.mkdir()

    original_rename = os.rename
    rename_count = 0

    def fail_second_rename(source: Path, destination: Path) -> None:
        nonlocal rename_count
        rename_count += 1
        if rename_count == 2:
            raise OSError("injected rename failure")
        original_rename(source, destination)

    monkeypatch.setattr(os, "rename", fail_second_rename)

    with pytest.raises(OSError, match="injected rename failure"):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id="dispatch.failure",
            instructions_bytes=b"instructions",
            input_bytes=b"input",
        )

    assert unrelated.is_dir()
    assert not (paths.dispatch_path / "dispatch.failure").exists()
    assert tuple(paths.dispatch_path.iterdir()) == (unrelated,)


@pytest.mark.parametrize(
    "dispatch_id",
    (
        "",
        ".",
        "..",
        "../escape",
        "nested/dispatch",
        "nested\\dispatch",
        "/absolute",
        "é" * 128,
    ),
)
def test_request_pair_rejects_unsafe_dispatch_identity(
    tmp_path: Path,
    dispatch_id: str,
) -> None:
    paths = task_root_paths(tmp_path / "task")

    with pytest.raises(ValueError, match="dispatch_id"):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id=dispatch_id,
            instructions_bytes=b"instructions",
            input_bytes=b"input",
        )


def test_request_pair_rejects_dispatch_root_outside_task_root(tmp_path: Path) -> None:
    paths = task_root_paths(tmp_path / "task").model_copy(
        update={"dispatch_path": tmp_path / "external-dispatch"}
    )

    with pytest.raises(ValueError, match="canonical task runtime root"):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id="dispatch.escape",
            instructions_bytes=b"instructions",
            input_bytes=b"input",
        )


def test_request_pair_rejects_relative_task_runtime_paths() -> None:
    paths = task_root_paths(Path("relative-task"))

    with pytest.raises(ValueError, match="must be absolute"):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id="dispatch.relative",
            instructions_bytes=b"instructions",
            input_bytes=b"input",
        )


def test_request_pair_rejects_symlinked_dispatch_root_escape(tmp_path: Path) -> None:
    paths = task_root_paths(tmp_path / "task")
    paths.runtime_path.mkdir(parents=True)
    external_dispatch_root = tmp_path / "external-dispatch"
    external_dispatch_root.mkdir()
    paths.dispatch_path.symlink_to(external_dispatch_root, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes the task root"):
        publish_dispatch_request_pair(
            paths=paths,
            dispatch_id="dispatch.symlink",
            instructions_bytes=b"instructions",
            input_bytes=b"input",
        )

    assert tuple(external_dispatch_root.iterdir()) == ()


def task_root_paths(task_root: Path) -> TaskRootPaths:
    runtime_path = task_root / "_runtime"
    outputs_path = task_root / "outputs"
    transfers_path = task_root / "tmp" / "transfers"
    return TaskRootPaths(
        task_root=task_root,
        workspace_path=task_root / "workspace",
        outputs_path=outputs_path,
        artifacts_path=outputs_path / "artifacts",
        tmp_path=task_root / "tmp",
        transfers_path=transfers_path,
        localized_path=transfers_path / "localized",
        runtime_path=runtime_path,
        criteria_path=runtime_path / "criteria",
        attempts_path=runtime_path / "attempts",
        dispatch_path=runtime_path / "dispatch",
    )
