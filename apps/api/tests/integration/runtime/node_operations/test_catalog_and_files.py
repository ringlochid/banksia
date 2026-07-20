from __future__ import annotations

import os
from pathlib import Path

import autoclaw.runtime.task_root.file_access as file_access_module
import pytest
from autoclaw.definitions.contracts import DefinitionKind
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts import TaskRootPaths
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations import (
    NODE_OPERATION_CATALOG,
    AddChildRequest,
    UpdateChildRequest,
    get_node_operation_descriptor,
    list_node_operation_descriptors_for_kind,
)
from autoclaw.runtime.task_root.file_access import (
    list_logical_directory,
    read_logical_text_file,
)
from autoclaw.runtime.task_root.logical_paths import normalize_logical_task_path
from autoclaw.runtime.work_plan import SetWorkPlanRequest
from pydantic import ValidationError
from pytest import MonkeyPatch

EXPECTED_OPERATION_NAMES = (
    "get_current_context",
    "list_files",
    "read_file",
    "set_work_plan",
    "record_checkpoint",
    "return_boundary",
    "open_human_request",
    "start_command_run",
    "search_definitions",
    "get_definition",
    "assign_child",
    "add_child",
    "update_child",
    "remove_child",
    "release_green",
    "release_blocked",
)


def test_catalog_has_one_exact_role_narrowed_sixteen_operation_surface() -> None:
    assert tuple(descriptor.name.value for descriptor in NODE_OPERATION_CATALOG) == (
        EXPECTED_OPERATION_NAMES
    )
    assert len(list_node_operation_descriptors_for_kind(NodeKind.WORKER)) == 8
    assert len(list_node_operation_descriptors_for_kind(NodeKind.PARENT)) == 15
    assert len(list_node_operation_descriptors_for_kind(NodeKind.ROOT)) == 16
    for descriptor in NODE_OPERATION_CATALOG:
        request_properties = descriptor.request_model.model_json_schema().get("properties", {})
        assert "task_id" not in request_properties
        assert "dispatch_id" not in request_properties
        assert descriptor.request_model.model_config.get("extra") == "forbid"


def test_catalog_preserves_terminal_and_structural_operation_teaching() -> None:
    for operation_name in (
        "return_boundary",
        "open_human_request",
        "start_command_run",
    ):
        description = get_node_operation_descriptor(operation_name).description.lower()
        assert "after success" in description
        assert "stop the current outer response" in description
        assert "no further tool calls or prose" in description

    for operation_name in ("add_child", "update_child", "remove_child"):
        description = get_node_operation_descriptor(operation_name).description.lower()
        assert "reread current context" in description
        assert "regenerated manifest" in description

    assert "parent/root" in get_node_operation_descriptor("assign_child").description
    assert "root-only" in get_node_operation_descriptor("release_blocked").description


def test_structural_child_contract_requires_and_preserves_policy_identity() -> None:
    with pytest.raises(ValidationError, match="policy"):
        AddChildRequest.model_validate(
            {
                "expected_structural_revision_id": "flow-revision.01",
                "payload": {
                    "child": {
                        "node_key": "new-worker",
                        "role": "role.target",
                        "description": "Missing mandatory policy.",
                    }
                },
            }
        )

    with pytest.raises(ValidationError, match="cannot clear the node policy"):
        UpdateChildRequest.model_validate(
            {
                "expected_structural_revision_id": "flow-revision.01",
                "payload": {
                    "child_node_key": "worker",
                    "patch": {"policy": None},
                },
            }
        )


def test_definition_lookup_schemas_accept_only_role_and_policy_kinds() -> None:
    for operation_name in ("search_definitions", "get_definition"):
        request_model = get_node_operation_descriptor(operation_name).request_model
        kind_schema = request_model.model_json_schema()["properties"]["kind"]

        assert kind_schema["enum"] == ["role", "policy"]
        assert (
            request_model.model_validate(
                {
                    "kind": "role",
                    **({"key": "role.example"} if operation_name == "get_definition" else {}),
                }
            ).model_dump()["kind"]
            == DefinitionKind.ROLE
        )
        assert (
            request_model.model_validate(
                {
                    "kind": "policy",
                    **({"key": "policy.example"} if operation_name == "get_definition" else {}),
                }
            ).model_dump()["kind"]
            == DefinitionKind.POLICY
        )
        with pytest.raises(ValidationError, match="Input should be"):
            request_model.model_validate(
                {
                    "kind": "workflow",
                    **({"key": "workflow.example"} if operation_name == "get_definition" else {}),
                }
            )


def test_work_plan_contract_rejects_duplicate_and_multiple_active_steps() -> None:
    with pytest.raises(ValueError, match="distinct"):
        SetWorkPlanRequest.model_validate(
            {
                "steps": [
                    {"step": "Inspect", "status": "pending"},
                    {"step": "inspect", "status": "completed"},
                ]
            }
        )
    with pytest.raises(ValueError, match="at most one"):
        SetWorkPlanRequest.model_validate(
            {
                "steps": [
                    {"step": "Inspect", "status": "in_progress"},
                    {"step": "Patch", "status": "in_progress"},
                ]
            }
        )


def test_logical_file_access_is_bounded_sorted_and_contained(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    paths.outputs_path.mkdir(parents=True)
    paths.tmp_path.mkdir(parents=True)
    paths.runtime_path.mkdir(parents=True)
    (paths.workspace_path / "z.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (paths.workspace_path / "a.txt").write_text("alpha\n", encoding="utf-8")

    directory, entries = list_logical_directory(paths, "workspace")
    assert directory == "workspace"
    assert [entry[0] for entry in entries] == ["a.txt", "z.txt"]
    assert read_logical_text_file(
        paths,
        "workspace/z.txt",
        start_line=2,
        max_lines=1,
    ) == ("workspace/z.txt", "two\n", 1, True, 3)

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (paths.workspace_path / "escape").symlink_to(outside)
    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(paths, "workspace/escape", start_line=1, max_lines=10)
    assert exc_info.value.code == OperationFailureCode.PATH_ESCAPE


def test_logical_root_listing_is_sorted_and_honors_the_entry_limit(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)

    directory, entries = list_logical_directory(paths, ".")

    assert directory == "."
    assert [entry[0] for entry in entries] == ["_runtime", "outputs", "tmp", "workspace"]
    with pytest.raises(RuntimeOperationError) as exc_info:
        list_logical_directory(paths, ".", entry_limit=3)
    assert exc_info.value.code == OperationFailureCode.DIRECTORY_LIMIT_EXCEEDED


def test_directory_limit_reads_only_one_entry_past_the_ceiling(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    scanner = _CountingScandir(total_entries=100)
    supported_fd = set(os.supports_fd)

    def counting_scandir(_directory_fd: int) -> _CountingScandir:
        return scanner

    monkeypatch.setattr(file_access_module.os, "scandir", counting_scandir)
    monkeypatch.setattr(
        file_access_module.os,
        "supports_fd",
        supported_fd | {counting_scandir},
    )

    with pytest.raises(RuntimeOperationError) as exc_info:
        list_logical_directory(paths, "workspace", entry_limit=2)

    assert exc_info.value.code == OperationFailureCode.DIRECTORY_LIMIT_EXCEEDED
    assert scanner.entries_read == 3


def test_directory_listing_does_not_follow_an_escaping_symlink(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (paths.workspace_path / "escape").symlink_to(outside, target_is_directory=True)

    _, entries = list_logical_directory(paths, "workspace")

    assert entries == (("escape", "workspace/escape", "symlink", None),)
    with pytest.raises(RuntimeOperationError) as exc_info:
        list_logical_directory(paths, "workspace/escape")
    assert exc_info.value.code == OperationFailureCode.PATH_ESCAPE


def test_file_read_accepts_a_contained_symlink_to_a_regular_file(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    (paths.workspace_path / "target.txt").write_text("contained\n", encoding="utf-8")
    (paths.workspace_path / "link.txt").symlink_to("target.txt")

    result = read_logical_text_file(
        paths,
        "workspace/link.txt",
        start_line=1,
        max_lines=10,
    )

    assert result == ("workspace/link.txt", "contained\n", 1, False, None)


def test_controller_owned_root_symlink_cannot_escape_task_root(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path / "task-root")
    paths.task_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    paths.outputs_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "outputs/secret.txt",
            start_line=1,
            max_lines=10,
        )

    assert exc_info.value.code == OperationFailureCode.PATH_ESCAPE


def test_external_workspace_binding_remains_a_valid_logical_root(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path / "task-root").model_copy(
        update={"workspace_path": tmp_path / "external-workspace"}
    )
    paths.workspace_path.mkdir()
    (paths.workspace_path / "read.txt").write_text("external\n", encoding="utf-8")

    result = read_logical_text_file(
        paths,
        "workspace/read.txt",
        start_line=1,
        max_lines=10,
    )

    assert result == ("workspace/read.txt", "external\n", 1, False, None)


def test_file_read_rejects_a_file_larger_than_the_byte_limit(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    (paths.workspace_path / "large.txt").write_bytes(b"12345")

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "workspace/large.txt",
            start_line=1,
            max_lines=10,
            byte_limit=4,
        )

    assert exc_info.value.code == OperationFailureCode.FILE_READ_LIMIT_EXCEEDED


def test_file_read_stays_bounded_when_the_file_grows_after_fstat(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    target = paths.workspace_path / "growing.txt"
    target.write_bytes(b"1234")
    real_fstat = os.fstat
    has_grown = False

    def grow_after_fstat(file_descriptor: int) -> os.stat_result:
        nonlocal has_grown
        metadata = real_fstat(file_descriptor)
        if not has_grown:
            with target.open("ab") as stream:
                stream.write(b"5")
            has_grown = True
        return metadata

    monkeypatch.setattr(file_access_module.os, "fstat", grow_after_fstat)

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "workspace/growing.txt",
            start_line=1,
            max_lines=10,
            byte_limit=4,
        )

    assert has_grown is True
    assert exc_info.value.code == OperationFailureCode.FILE_READ_LIMIT_EXCEEDED


def test_file_read_rejects_non_utf8_content(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    (paths.workspace_path / "binary.dat").write_bytes(b"\xff\xfe")

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "workspace/binary.dat",
            start_line=1,
            max_lines=10,
        )

    assert exc_info.value.code == OperationFailureCode.BINARY_FILE


def test_file_read_rejects_a_non_regular_target(tmp_path: Path) -> None:
    paths = _task_root_paths(tmp_path)
    (paths.workspace_path / "directory").mkdir(parents=True)

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "workspace/directory",
            start_line=1,
            max_lines=10,
        )

    assert exc_info.value.code == OperationFailureCode.NOT_A_FILE


def test_file_read_rejects_a_final_component_symlink_swap(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    target = paths.workspace_path / "raced.txt"
    target.write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    real_open = os.open
    supported_dir_fd = set(os.supports_dir_fd)
    has_swapped = False

    def swap_before_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal has_swapped
        if path == target.name and dir_fd is not None and not has_swapped:
            target.unlink()
            target.symlink_to(outside)
            has_swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(file_access_module.os, "open", swap_before_open)
    monkeypatch.setattr(
        file_access_module.os,
        "supports_dir_fd",
        supported_dir_fd | {swap_before_open},
    )

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(paths, "workspace/raced.txt", start_line=1, max_lines=10)

    assert has_swapped is True
    assert exc_info.value.code == OperationFailureCode.PATH_ESCAPE


def test_file_read_rejects_an_intermediate_component_symlink_swap(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _task_root_paths(tmp_path)
    safe_directory = paths.workspace_path / "safe"
    safe_directory.mkdir(parents=True)
    (safe_directory / "read.txt").write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "read.txt").write_text("secret", encoding="utf-8")
    moved_directory = paths.workspace_path / "safe-before-race"
    real_open = os.open
    supported_dir_fd = set(os.supports_dir_fd)
    has_swapped = False

    def swap_before_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal has_swapped
        if path == safe_directory.name and dir_fd is not None and not has_swapped:
            safe_directory.rename(moved_directory)
            safe_directory.symlink_to(outside, target_is_directory=True)
            has_swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(file_access_module.os, "open", swap_before_open)
    monkeypatch.setattr(
        file_access_module.os,
        "supports_dir_fd",
        supported_dir_fd | {swap_before_open},
    )

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "workspace/safe/read.txt",
            start_line=1,
            max_lines=10,
        )

    assert has_swapped is True
    assert exc_info.value.code == OperationFailureCode.PATH_ESCAPE


def test_file_access_fails_closed_without_descriptor_relative_support(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _task_root_paths(tmp_path)
    paths.workspace_path.mkdir(parents=True)
    (paths.workspace_path / "read.txt").write_text("safe", encoding="utf-8")
    monkeypatch.setattr(file_access_module.os, "O_NOFOLLOW", 0)

    with pytest.raises(RuntimeOperationError) as exc_info:
        read_logical_text_file(
            paths,
            "workspace/read.txt",
            start_line=1,
            max_lines=10,
        )

    assert exc_info.value.code == OperationFailureCode.INVALID_TASK_ROOT


@pytest.mark.parametrize(
    "value",
    ("", "/tmp/x", "../x", "workspace/../x", "C:/x", "\\\\server\\x", "workspace\\x"),
)
def test_logical_path_rejects_nonportable_or_traversing_values(value: str) -> None:
    with pytest.raises(RuntimeOperationError):
        normalize_logical_task_path(value)


def _task_root_paths(task_root: Path) -> TaskRootPaths:
    return TaskRootPaths(
        task_root=task_root,
        workspace_path=task_root / "workspace",
        outputs_path=task_root / "outputs",
        artifacts_path=task_root / "outputs" / "artifacts",
        tmp_path=task_root / "tmp",
        transfers_path=task_root / "tmp" / "transfers",
        localized_path=task_root / "tmp" / "transfers" / "localized",
        runtime_path=task_root / "_runtime",
        criteria_path=task_root / "_runtime" / "criteria",
        attempts_path=task_root / "_runtime" / "attempts",
        dispatch_path=task_root / "_runtime" / "dispatch",
    )


class _CountingScandir:
    def __init__(self, *, total_entries: int) -> None:
        self._total_entries = total_entries
        self.entries_read = 0

    def __enter__(self) -> _CountingScandir:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def __iter__(self) -> _CountingScandir:
        return self

    def __next__(self) -> object:
        if self.entries_read >= self._total_entries:
            raise StopIteration
        self.entries_read += 1
        return object()
