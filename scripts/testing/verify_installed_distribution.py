from __future__ import annotations

import argparse
import json
import sysconfig
from pathlib import Path

from .installed_distribution.artifacts import (
    artifact_result,
    inspect_sdist,
    inspect_wheel,
    select_one_artifact,
    verify_artifact_names,
)
from .installed_distribution.processes import (
    assert_optional_file_unchanged,
    create_offline_venv,
    install_wheel,
    read_optional_file,
    validate_external_workspace,
)
from .installed_distribution.runtime import verify_installed_runtime
from .installed_distribution.user_service import verify_user_service_installer


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify built Banksia artifacts and the isolated user-service installer."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--artifacts-only", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()

    dist_dir = args.dist_dir.resolve()
    wheel_path = select_one_artifact(dist_dir, "*.whl")
    sdist_path = select_one_artifact(dist_dir, "*.tar.gz")
    verify_artifact_names(wheel_path=wheel_path, sdist_path=sdist_path)

    wheel_members = inspect_wheel(wheel_path)
    sdist_members = inspect_sdist(sdist_path)
    artifact_payload = {
        "wheel": artifact_result(wheel_path, wheel_members),
        "sdist": artifact_result(sdist_path, sdist_members),
    }
    if args.artifacts_only:
        print(json.dumps({"ok": True, **artifact_payload}, indent=2, sort_keys=True))
        return 0
    if args.workspace is None:
        parser.error("--workspace is required unless --artifacts-only is used")

    workspace = args.workspace.resolve()
    repo_root = args.repo_root.resolve()
    validate_external_workspace(workspace=workspace, repo_root=repo_root)
    git_exclude_path = repo_root / ".git" / "info" / "exclude"
    git_exclude_before = read_optional_file(git_exclude_path)
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        dependency_site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
        installed_venv = workspace / "installed-venv"
        create_offline_venv(installed_venv, dependency_site_packages)
        install_wheel(installed_venv, wheel_path, workspace)
        installed_smoke = verify_installed_runtime(
            installed_venv,
            workspace,
            repo_root,
        )
        installer_smoke = verify_user_service_installer(
            wheel_path=wheel_path,
            workspace=workspace,
            repo_root=repo_root,
            dependency_site_packages=dependency_site_packages,
        )
    finally:
        assert_optional_file_unchanged(git_exclude_path, before=git_exclude_before)

    print(
        json.dumps(
            {
                "ok": True,
                **artifact_payload,
                "installed": installed_smoke,
                "installer": installer_smoke,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
