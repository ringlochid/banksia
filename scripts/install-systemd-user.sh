#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_DIR="${OMS_CONFIG_DIR:-$CONFIG_HOME/oh-my-subagents}"
DATA_DIR="${OMS_DATA_DIR:-$DATA_HOME/oh-my-subagents}"
VENV_DIR="${OMS_VENV_DIR:-$DATA_DIR/venv}"
PYTHON_BIN="${OMS_PYTHON_BIN:-python3}"
CONFIG_PATH="${OMS_CONFIG:-$CONFIG_DIR/config.toml}"
WORKSPACE_PATH="${OMS_WORKSPACE:-$PWD}"
INSTALL_MODE="source"
WHEEL_PATH=""
NO_DEPS=0
API_PORT=""
EXTRA_SPEC=""
FORCE_INIT=0
NO_START=0

usage() {
  cat <<'EOF'
Usage: scripts/install-systemd-user.sh [options]

Installs Oh My Subagents into a dedicated user venv, runs the shipped noninteractive
initializer, then delegates service ownership to `oms service install`.

Options:
  --editable       Install from the repo in editable mode
  --wheel PATH     Install an already-built Oh My Subagents wheel
  --no-deps        Do not resolve dependencies (for an offline prepared venv)
  --postgres       Install the postgres extra
  --workspace PATH Persist this existing directory as the default workspace
  --port PORT      Persist this local API port during initialization
  --force-init     Re-write the generated config.toml during oms init
  --no-start       Install the service but do not start it now
  -h, --help       Show this help

Environment overrides:
  OMS_CONFIG_DIR, OMS_DATA_DIR, OMS_VENV_DIR,
  OMS_CONFIG, OMS_WORKSPACE, OMS_PYTHON_BIN
EOF
}

while (($# > 0)); do
  case "$1" in
    --editable)
      INSTALL_MODE="editable"
      ;;
    --wheel)
      shift
      [[ $# -gt 0 ]] || { echo "--wheel requires a path" >&2; exit 1; }
      WHEEL_PATH="$1"
      ;;
    --no-deps)
      NO_DEPS=1
      ;;
    --postgres)
      EXTRA_SPEC="[postgres]"
      ;;
    --workspace)
      shift
      [[ $# -gt 0 ]] || { echo "--workspace requires a path" >&2; exit 1; }
      WORKSPACE_PATH="$1"
      ;;
    --port)
      shift
      [[ $# -gt 0 ]] || { echo "--port requires a value" >&2; exit 1; }
      API_PORT="$1"
      ;;
    --force-init)
      FORCE_INIT=1
      ;;
    --no-start)
      NO_START=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$(uname -s)" != Linux* ]]; then
  echo "This convenience wrapper is Linux-only. Install Oh My Subagents, then run 'oms init' and 'oms service install' on this host." >&2
  exit 1
fi
if [[ ! -d "$WORKSPACE_PATH" ]]; then
  echo "Workspace directory not found: $WORKSPACE_PATH" >&2
  exit 1
fi

mkdir -p "$CONFIG_DIR" "$DATA_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

INSTALL_TARGET="$REPO_ROOT"
if [[ -n "$WHEEL_PATH" ]]; then
  if [[ "$INSTALL_MODE" == "editable" ]]; then
    echo "--editable and --wheel cannot be used together" >&2
    exit 1
  fi
  [[ -f "$WHEEL_PATH" ]] || { echo "Wheel not found: $WHEEL_PATH" >&2; exit 1; }
  INSTALL_TARGET="$(cd "$(dirname "$WHEEL_PATH")" && pwd)/$(basename "$WHEEL_PATH")"
fi
INSTALL_SPEC="$INSTALL_TARGET$EXTRA_SPEC"
PIP_ARGS=(install)
if (( NO_DEPS )); then
  PIP_ARGS+=(--no-deps)
fi
if [[ "$INSTALL_MODE" == "editable" ]]; then
  PIP_ARGS+=(-e)
fi
"$VENV_DIR/bin/python" -m pip "${PIP_ARGS[@]}" "$INSTALL_SPEC"

INIT_ARGS=(
  init
  --non-interactive
  --config "$CONFIG_PATH"
  --data-dir "$DATA_DIR"
  --workspace "$WORKSPACE_PATH"
)
if [[ -n "$API_PORT" ]]; then
  INIT_ARGS+=(--port "$API_PORT")
fi
if (( FORCE_INIT )); then
  INIT_ARGS+=(--force)
fi
"$VENV_DIR/bin/oms" "${INIT_ARGS[@]}"

SERVICE_INSTALL_ARGS=(
  service install
  --config "$CONFIG_PATH"
)
if (( NO_START )); then
  SERVICE_INSTALL_ARGS+=(--no-start)
fi
"$VENV_DIR/bin/oms" "${SERVICE_INSTALL_ARGS[@]}"

echo "Installed Oh My Subagents and reconciled its per-user background service."
echo "  config: $CONFIG_PATH"
echo "  data:   $DATA_DIR"
echo "  venv:   $VENV_DIR"
if (( NO_START )); then
  echo "Start it with: $VENV_DIR/bin/oms service start --config $CONFIG_PATH"
else
  echo "Check it with: $VENV_DIR/bin/oms service status --config $CONFIG_PATH"
fi
