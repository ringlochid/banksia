from __future__ import annotations

import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import banksia.runtime.task_start as task_start_module
import banksia.runtime.workspace.git_exclusion as git_exclusion_module
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.providers import ProviderKind
from banksia.runtime.contracts import TaskStartRequest
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.task_start import start_task
from banksia.runtime.workspace.git_exclusion import prepare_workspace_git_exclusion
from tests.helpers.workflow_runtime import initialized_workflow_database


def test_main_worktree_root_gets_one_anchored_local_exclusion(tmp_path: Path) -> None:
    repository = _initialize_repository(tmp_path / "repository")

    first = prepare_workspace_git_exclusion(repository)
    second = prepare_workspace_git_exclusion(repository)

    exclude = _git_path(repository, "info/exclude")
    assert first == second == exclude
    assert exclude.read_text(encoding="utf-8").splitlines().count("/.banksia/") == 1
    assert not (repository / ".gitignore").exists()
    assert _is_ignored(repository, ".banksia/probe")


def test_nested_workspace_exclusion_does_not_hide_a_sibling(tmp_path: Path) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    workspace = repository / "projects" / "selected"
    sibling = repository / "projects" / "sibling"
    workspace.mkdir(parents=True)
    sibling.mkdir()

    prepare_workspace_git_exclusion(workspace)

    exclude = _git_path(repository, "info/exclude")
    assert "/projects/selected/.banksia/" in exclude.read_text(encoding="utf-8").splitlines()
    assert _is_ignored(repository, "projects/selected/.banksia/probe")
    assert not _is_ignored(repository, "projects/sibling/.banksia/probe")
    assert not (workspace / ".gitignore").exists()


def test_linked_worktree_uses_the_git_reported_exclude_path(tmp_path: Path) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    linked = tmp_path / "linked"
    _run_git(repository, "worktree", "add", "--quiet", str(linked))
    workspace = linked / "workspace"
    workspace.mkdir()

    reported = _git_path(workspace, "info/exclude")
    root_actual = prepare_workspace_git_exclusion(linked)
    actual = prepare_workspace_git_exclusion(workspace)

    assert root_actual == actual == reported
    assert {"/.banksia/", "/workspace/.banksia/"} <= set(
        reported.read_text(encoding="utf-8").splitlines()
    )
    assert _is_ignored(linked, ".banksia/probe")
    assert _is_ignored(linked, "workspace/.banksia/probe")
    assert not _is_ignored(linked, "other/.banksia/probe")


def test_nested_workspace_git_pattern_escapes_literal_metacharacters(
    tmp_path: Path,
) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    workspace = repository / "selected [one]*"
    workspace.mkdir()

    prepare_workspace_git_exclusion(workspace)

    assert _is_ignored(repository, "selected [one]*/.banksia/probe")
    assert not _is_ignored(repository, "selected one/.banksia/probe")


def test_tracked_banksia_content_is_rejected_before_exclude_mutation(
    tmp_path: Path,
) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    workspace = repository / "workspace"
    tracked = workspace / ".banksia" / "tracked.txt"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("user content", encoding="utf-8")
    _run_git(repository, "add", "workspace/.banksia/tracked.txt")
    _run_git(repository, "commit", "--quiet", "-m", "track Banksia path")
    exclude = _git_path(repository, "info/exclude")
    before = exclude.read_bytes()

    with pytest.raises(RuntimeOperationError, match="tracked content"):
        prepare_workspace_git_exclusion(workspace)

    assert exclude.read_bytes() == before
    assert tracked.read_text(encoding="utf-8") == "user content"


def test_non_git_workspace_has_no_git_or_banksia_side_effect(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert prepare_workspace_git_exclusion(workspace) is None

    assert tuple(workspace.iterdir()) == ()


def test_missing_git_is_harmless_for_a_non_git_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def missing_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_exclusion_module.subprocess, "run", missing_git)

    assert prepare_workspace_git_exclusion(workspace) is None
    assert tuple(workspace.iterdir()) == ()


def test_missing_git_fails_closed_for_a_detectable_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    (repository / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    workspace = repository / "workspace"
    workspace.mkdir()

    def missing_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_exclusion_module.subprocess, "run", missing_git)

    with pytest.raises(RuntimeOperationError, match="Git is required"):
        prepare_workspace_git_exclusion(workspace)

    assert not (workspace / ".banksia").exists()


def test_missing_git_continues_past_an_inner_junk_marker_to_parent_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    (repository / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    workspace = repository / "nested" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".git").write_text("not a worktree marker\n", encoding="utf-8")

    def missing_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_exclusion_module.subprocess, "run", missing_git)

    with pytest.raises(RuntimeOperationError, match="Git is required"):
        prepare_workspace_git_exclusion(workspace)


def test_missing_git_fails_closed_without_reading_an_oversized_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").write_bytes(b"x" * 8_192)

    def missing_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_exclusion_module.subprocess, "run", missing_git)

    with pytest.raises(RuntimeOperationError, match="Git is required"):
        prepare_workspace_git_exclusion(workspace)


def test_git_exclusion_rejects_nonregular_opened_descriptor(tmp_path: Path) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    exclude = _git_path(repository, "info/exclude")
    exclude.unlink()
    os.mkfifo(exclude)

    with pytest.raises(RuntimeOperationError, match="not a regular file"):
        prepare_workspace_git_exclusion(repository)


def test_git_exclusion_rejects_path_substitution_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    exclude = _git_path(repository, "info/exclude")
    outside = tmp_path / "outside"
    outside.write_text("outside\n", encoding="utf-8")
    real_flock = git_exclusion_module.fcntl.flock
    did_substitute = False

    def substitute_after_lock(descriptor: int, operation: int) -> None:
        nonlocal did_substitute
        real_flock(descriptor, operation)
        if operation == git_exclusion_module.fcntl.LOCK_EX and not did_substitute:
            did_substitute = True
            exclude.unlink()
            exclude.symlink_to(outside)

    monkeypatch.setattr(git_exclusion_module.fcntl, "flock", substitute_after_lock)

    with pytest.raises(RuntimeOperationError, match="changed while"):
        prepare_workspace_git_exclusion(repository)

    assert exclude.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_concurrent_nested_workspace_exclusions_lock_before_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _initialize_repository(tmp_path / "repository")
    first_workspace = repository / "projects" / "first"
    second_workspace = repository / "projects" / "second"
    first_workspace.mkdir(parents=True)
    second_workspace.mkdir()
    first_read_entered = threading.Event()
    release_first_read = threading.Event()
    second_lock_attempted = threading.Event()
    second_read_entered = threading.Event()
    count_lock = threading.Lock()
    lock_attempt_count = 0
    first_reader_thread_id: int | None = None
    has_blocked_first_read = False
    real_flock = git_exclusion_module.fcntl.flock
    real_lseek = git_exclusion_module.os.lseek

    def observed_flock(descriptor: int, operation: int) -> None:
        nonlocal lock_attempt_count
        if operation == git_exclusion_module.fcntl.LOCK_EX:
            with count_lock:
                lock_attempt_count += 1
                if lock_attempt_count == 2:
                    second_lock_attempted.set()
        real_flock(descriptor, operation)

    def observed_lseek(descriptor: int, position: int, how: int) -> int:
        nonlocal first_reader_thread_id, has_blocked_first_read
        if position != 0 or how != os.SEEK_SET:
            return real_lseek(descriptor, position, how)
        thread_id = threading.get_ident()
        should_block = False
        with count_lock:
            if first_reader_thread_id is None:
                first_reader_thread_id = thread_id
            if thread_id == first_reader_thread_id and not has_blocked_first_read:
                has_blocked_first_read = True
                should_block = True
            elif thread_id != first_reader_thread_id:
                second_read_entered.set()
        if should_block:
            first_read_entered.set()
            assert release_first_read.wait(timeout=2)
        return real_lseek(descriptor, position, how)

    monkeypatch.setattr(git_exclusion_module.fcntl, "flock", observed_flock)
    monkeypatch.setattr(git_exclusion_module.os, "lseek", observed_lseek)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(prepare_workspace_git_exclusion, first_workspace)
        second = None
        try:
            assert first_read_entered.wait(timeout=2)
            second = executor.submit(prepare_workspace_git_exclusion, second_workspace)
            assert second_lock_attempted.wait(timeout=2)
            assert not second_read_entered.is_set()
        finally:
            release_first_read.set()
        first.result(timeout=2)
        assert second is not None
        second.result(timeout=2)

    assert second_read_entered.is_set()
    lines = _git_path(repository, "info/exclude").read_text(encoding="utf-8").splitlines()
    assert "/projects/first/.banksia/" in lines
    assert "/projects/second/.banksia/" in lines


async def test_task_start_prepares_git_exclusion_before_task_tree(
    tmp_path: Path,
) -> None:
    workspace = _initialize_repository(tmp_path / "repository")

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            response = await start_task(
                TaskStartRequest(
                    workflow="reviewed-delivery",
                    prompt="Verify the Git admission bridge.",
                    workspace=workspace,
                ),
                session=session,
                dependencies=DispatchOpeningDependencies.create(
                    settings=Settings(
                        controller_workspace=workspace,
                        runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
                        codex=CodexSettings(enabled=True),
                    ),
                    available_adapter_kinds={ProviderKind.CODEX},
                    post_commit_publisher=CapturedRuntimeEffectPublisher(),
                ),
            )

    assert (workspace / ".banksia" / response.task_id / "manifest.md").is_file()
    assert _is_ignored(workspace, f".banksia/{response.task_id}/manifest.md")
    assert not (workspace / ".gitignore").exists()


async def test_task_start_rejects_workspace_identity_substitution_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original_workspace = tmp_path / "workspace-before-swap"
    real_prepare = task_start_module.prepare_workspace_git_exclusion

    def substitute_after_git_check(selected_workspace: Path) -> Path | None:
        result = real_prepare(selected_workspace)
        selected_workspace.rename(original_workspace)
        selected_workspace.mkdir()
        return result

    monkeypatch.setattr(
        task_start_module,
        "prepare_workspace_git_exclusion",
        substitute_after_git_check,
    )

    async with initialized_workflow_database(tmp_path) as session_factory:
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="changed identity"):
                await start_task(
                    TaskStartRequest(
                        workflow="reviewed-delivery",
                        prompt="Reject a substituted workspace.",
                        workspace=workspace,
                    ),
                    session=session,
                    dependencies=DispatchOpeningDependencies.create(
                        settings=Settings(
                            controller_workspace=workspace,
                            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
                            codex=CodexSettings(enabled=True),
                        ),
                        available_adapter_kinds={ProviderKind.CODEX},
                        post_commit_publisher=CapturedRuntimeEffectPublisher(),
                    ),
                )

    assert not (workspace / ".banksia").exists()
    assert not (original_workspace / ".banksia").exists()


def _initialize_repository(path: Path) -> Path:
    path.mkdir()
    _run_git(path, "init", "--quiet")
    _run_git(path, "config", "user.email", "banksia-tests@example.invalid")
    _run_git(path, "config", "user.name", "Banksia tests")
    seed = path / "seed.txt"
    seed.write_text("seed", encoding="utf-8")
    _run_git(path, "add", "seed.txt")
    _run_git(path, "commit", "--quiet", "-m", "seed")
    return path


def _git_path(workspace: Path, suffix: str) -> Path:
    output = _run_git(
        workspace,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        suffix,
    )
    return Path(output.strip())


def _is_ignored(repository: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ("git", "-C", str(repository), "check-ignore", "--quiet", "--", relative_path),
        check=False,
    )
    return result.returncode == 0


def _run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
