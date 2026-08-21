from __future__ import annotations

import hashlib
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath

EXPECTED_DISTRIBUTION_NAME = "oh-my-subagents"
EXPECTED_DISTRIBUTION_VERSION = "0.3.0"
LEGACY_COMMAND_NOTICE = "The 'banksia' command is deprecated; use 'oms'."
STARTER_WORKFLOW_IDS = (
    "decision-through-competing-prototypes",
    "deep-research-and-decision-brief",
    "experiment-and-replication-program",
    "idea-to-validated-demo",
    "incident-investigation-and-recovery",
    "migration-and-modernisation",
    "production-feature-delivery",
    "security-audit-and-hardening",
)
STARTER_WORKFLOW_FILENAMES = tuple(f"{workflow_id}.yaml" for workflow_id in STARTER_WORKFLOW_IDS)
ADVANCED_REFERENCE_WORKFLOW_IDS = (
    "advanced-cross-layer-delivery",
    "advanced-reviewed-code-change",
    "advanced-technical-decision",
)
STARTER_RESOURCE_PREFIX = "oh_my_subagents/workflows/resources/starter_workflows/"
REQUIRED_PACKAGE_MEMBERS = (
    "oh_my_subagents/config.py",
    "oh_my_subagents/main.py",
    "oh_my_subagents/interfaces/web_console/assets/index.html",
    "oh_my_subagents/interfaces/web_console/assets/assets/oms-mark.svg",
    *(f"{STARTER_RESOURCE_PREFIX}{filename}" for filename in STARTER_WORKFLOW_FILENAMES),
    "oh_my_subagents/platform/managed_services/resources/systemd/oh-my-subagents.service",
    "oh_my_subagents/runtime/prompt/assets/shared/core.txt",
    "oh_my_subagents/runtime/prompt/assets/behaviors/contributor.txt",
    "banksia/__init__.py",
    "banksia/__main__.py",
)
FORBIDDEN_MEMBER_FRAGMENTS = (
    ".env",
    "callback",
    "prompt-request.json",
    "prompt.md",
    "session_key",
    "autoclaw",
)


def select_one_artifact(dist_dir: Path, pattern: str) -> Path:
    artifacts = sorted(dist_dir.glob(pattern))
    if len(artifacts) != 1:
        raise AssertionError(
            f"expected exactly one {pattern} artifact in {dist_dir}, found {len(artifacts)}"
        )
    return artifacts[0].resolve()


def verify_artifact_names(*, wheel_path: Path, sdist_path: Path) -> None:
    expected_wheel_prefix = f"oh_my_subagents-{EXPECTED_DISTRIBUTION_VERSION}-"
    if not wheel_path.name.startswith(expected_wheel_prefix):
        raise AssertionError(
            f"wheel has unexpected name or version: {wheel_path.name}; "
            f"expected prefix {expected_wheel_prefix}"
        )
    expected_sdist_name = f"oh_my_subagents-{EXPECTED_DISTRIBUTION_VERSION}.tar.gz"
    if sdist_path.name != expected_sdist_name:
        raise AssertionError(
            f"source distribution has unexpected name or version: {sdist_path.name}; "
            f"expected {expected_sdist_name}"
        )


def inspect_wheel(wheel_path: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(wheel_path) as archive:
        members = tuple(sorted(archive.namelist()))
        verify_wheel_identity(archive, members)
    verify_package_members(members)
    verify_forbidden_members(members)
    return members


def verify_wheel_identity(
    archive: zipfile.ZipFile,
    members: tuple[str, ...],
) -> None:
    metadata_member = select_member_with_suffix(members, ".dist-info/METADATA")
    entry_points_member = select_member_with_suffix(members, ".dist-info/entry_points.txt")
    metadata = archive.read(metadata_member).decode("utf-8")
    entry_points = archive.read(entry_points_member).decode("utf-8")
    verify_core_metadata(metadata, source="wheel")
    if "oms = oh_my_subagents.interfaces.cli.main:main" not in entry_points:
        raise AssertionError("wheel does not expose the canonical OMS console entry point")
    if "banksia = oh_my_subagents.interfaces.cli.main:legacy_main" not in entry_points:
        raise AssertionError("wheel does not expose the Oh My Subagents compatibility entry point")
    if "autoclaw" in entry_points.casefold():
        raise AssertionError("wheel retained the removed legacy console entry point")


def select_member_with_suffix(members: tuple[str, ...], suffix: str) -> str:
    matches = [member for member in members if member.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one wheel member ending in {suffix}: {matches}")
    return matches[0]


def inspect_sdist(sdist_path: Path) -> tuple[str, ...]:
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        raw_members = tuple(sorted(member.name for member in archive.getmembers()))
        metadata_member = select_sdist_metadata_member(raw_members)
        metadata_file = archive.extractfile(metadata_member)
        if metadata_file is None:
            raise AssertionError(f"could not read source metadata member: {metadata_member}")
        verify_core_metadata(metadata_file.read().decode("utf-8"), source="source distribution")
    members = tuple(remove_sdist_root(member) for member in raw_members)
    required = (*REQUIRED_PACKAGE_MEMBERS, "LICENSE", "README.md", "pyproject.toml")
    verify_required_suffixes(members, required)
    verify_starter_workflow_members(members)
    verify_console_asset_members(members)
    verify_legacy_bridge_members(members)
    verify_forbidden_members(members)
    return raw_members


def select_sdist_metadata_member(members: tuple[str, ...]) -> str:
    matches = [
        member
        for member in members
        if len(PurePosixPath(member).parts) == 2 and PurePosixPath(member).name == "PKG-INFO"
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one top-level source PKG-INFO member: {matches}")
    return matches[0]


def verify_core_metadata(metadata: str, *, source: str) -> None:
    parsed = Parser().parsestr(metadata, headersonly=True)
    if parsed["Name"] != EXPECTED_DISTRIBUTION_NAME:
        raise AssertionError(
            f"{source} has unexpected distribution name: {parsed['Name']!r}; "
            f"expected {EXPECTED_DISTRIBUTION_NAME!r}"
        )
    if parsed["Version"] != EXPECTED_DISTRIBUTION_VERSION:
        raise AssertionError(
            f"{source} has unexpected version: {parsed['Version']!r}; "
            f"expected {EXPECTED_DISTRIBUTION_VERSION!r}"
        )


def verify_package_members(members: tuple[str, ...]) -> None:
    verify_required_suffixes(members, REQUIRED_PACKAGE_MEMBERS)
    verify_starter_workflow_members(members)
    verify_console_asset_members(members)
    if any(member.startswith("src/oh_my_subagents/") for member in members):
        raise AssertionError("wheel retained a source-tree package prefix")


def verify_starter_workflow_members(members: tuple[str, ...]) -> None:
    actual = tuple(
        sorted(
            member.split(STARTER_RESOURCE_PREFIX, maxsplit=1)[1]
            for member in members
            if STARTER_RESOURCE_PREFIX in member and member.endswith(".yaml")
        )
    )
    if actual != STARTER_WORKFLOW_FILENAMES:
        raise AssertionError(
            f"distribution Starter Workflow resources do not match the exact catalog: {actual}"
        )


def verify_required_suffixes(members: tuple[str, ...], required: tuple[str, ...]) -> None:
    missing = [
        suffix for suffix in required if not any(member.endswith(suffix) for member in members)
    ]
    if missing:
        raise AssertionError(f"distribution is missing required members: {missing}")


def verify_console_asset_members(members: tuple[str, ...]) -> None:
    console_assets = tuple(
        member for member in members if "oh_my_subagents/interfaces/web_console/assets/" in member
    )
    for suffix in (".js", ".css"):
        if not any(member.endswith(suffix) for member in console_assets):
            raise AssertionError(f"distribution is missing a built Console {suffix} asset")


def verify_legacy_bridge_members(members: tuple[str, ...]) -> None:
    normalized_members = tuple(
        member.removeprefix("src/")
        for member in members
        if member.startswith(("banksia/", "src/banksia/"))
    )
    legacy_members = tuple(sorted(normalized_members))
    if legacy_members != ("banksia/__init__.py", "banksia/__main__.py"):
        raise AssertionError(
            f"distribution has an unexpected Banksia compatibility surface: {legacy_members}"
        )


def verify_forbidden_members(members: tuple[str, ...]) -> None:
    for member in members:
        normalized = member.casefold().replace("-", "_")
        if any(fragment in normalized for fragment in FORBIDDEN_MEMBER_FRAGMENTS):
            raise AssertionError(f"distribution retained forbidden member: {member}")
        parts = PurePosixPath(member).parts
        if "__pycache__" in parts or member.endswith((".pyc", ".pyo")):
            raise AssertionError(f"distribution retained Python cache state: {member}")


def remove_sdist_root(member: str) -> str:
    parts = PurePosixPath(member).parts
    return PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else member


def artifact_result(path: Path, members: tuple[str, ...]) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "member_count": len(members),
    }
