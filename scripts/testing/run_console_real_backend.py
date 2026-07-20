from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import FrameType

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SOURCE_ROOT = REPO_ROOT / "apps" / "api" / "src"


def main() -> int:
    args = _parse_args()
    runtime_root = Path(tempfile.mkdtemp(prefix="autoclaw-console-real-backend-"))
    config_path = runtime_root / "config" / "autoclaw.toml"
    data_dir = runtime_root / "data"
    environment = _build_environment()
    server: subprocess.Popen[str] | None = None

    try:
        _initialize_runtime(
            config_path=config_path,
            data_dir=data_dir,
            environment=environment,
            port=args.port,
        )
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "autoclaw",
                "serve",
                "--config",
                str(config_path),
            ],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
        )
        _install_signal_forwarding(server)
        return server.wait()
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        shutil.rmtree(runtime_root, ignore_errors=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a disposable shipped AutoClaw backend for the console browser smoke."
    )
    parser.add_argument("--port", type=int, default=18126)
    return parser.parse_args()


def _build_environment() -> dict[str, str]:
    environment = os.environ.copy()
    current_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(API_SOURCE_ROOT)
        if not current_pythonpath
        else os.pathsep.join((str(API_SOURCE_ROOT), current_pythonpath))
    )
    environment["AUTOCLAW_ENV"] = "production"
    return environment


def _initialize_runtime(
    *,
    config_path: Path,
    data_dir: Path,
    environment: dict[str, str],
    port: int,
) -> None:
    _run_cli(
        "init",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "WARNING",
        "--json",
        environment=environment,
    )
    _run_cli(
        "providers",
        "configure",
        "openclaw",
        "--config",
        str(config_path),
        "--gateway-url",
        "ws://127.0.0.1:9",
        "--gateway-profile",
        "real-browser-smoke",
        "--json",
        environment=environment,
    )


def _run_cli(*arguments: str, environment: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "autoclaw", *arguments],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        text=True,
        stdout=subprocess.DEVNULL,
    )


def _install_signal_forwarding(server: subprocess.Popen[str]) -> None:
    def forward_signal(signum: int, _frame: FrameType | None) -> None:
        if server.poll() is None:
            server.send_signal(signum)

    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)


if __name__ == "__main__":
    raise SystemExit(main())
