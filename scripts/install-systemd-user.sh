#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${AUTOCLAW_SERVICE_NAME:-autoclaw}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_DIR="${AUTOCLAW_CONFIG_DIR:-$CONFIG_HOME/autoclaw}"
DATA_DIR="${AUTOCLAW_DATA_DIR:-$DATA_HOME/autoclaw}"
VENV_DIR="${AUTOCLAW_VENV_DIR:-$DATA_DIR/venv}"
PYTHON_BIN="${AUTOCLAW_PYTHON_BIN:-python3}"
CONFIG_PATH="${AUTOCLAW_CONFIG:-$CONFIG_DIR/config.toml}"
ENV_FILE_PATH="$(dirname "$CONFIG_PATH")/autoclaw.env"
UNIT_DIR="$CONFIG_HOME/systemd/user"
UNIT_PATH="$UNIT_DIR/$SERVICE_NAME.service"
SYSTEMCTL_BIN="${AUTOCLAW_SYSTEMCTL_BIN:-systemctl}"
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

Installs AutoClaw into a dedicated user venv, initializes config/data,
renders a user systemd unit, and enables the service.

Options:
  --editable       Install from the repo in editable mode
  --wheel PATH     Install an already-built AutoClaw wheel
  --no-deps        Do not resolve dependencies (for an offline prepared venv)
  --postgres       Install the postgres extra
  --port PORT      Persist this local API port during initialization
  --force-init     Re-write the generated config.toml during autoclaw init
  --no-start       Install/enable the unit but do not start it now
  -h, --help       Show this help

Environment overrides:
  AUTOCLAW_CONFIG_DIR, AUTOCLAW_DATA_DIR, AUTOCLAW_VENV_DIR,
  AUTOCLAW_CONFIG, AUTOCLAW_SERVICE_NAME,
  AUTOCLAW_SYSTEMCTL_BIN, AUTOCLAW_PYTHON_BIN
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

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$UNIT_DIR"
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
"$VENV_DIR/bin/pip" "${PIP_ARGS[@]}" "$INSTALL_SPEC"

INIT_ARGS=(init --non-interactive --config "$CONFIG_PATH" --data-dir "$DATA_DIR")
if [[ -n "$API_PORT" ]]; then
  INIT_ARGS+=(--port "$API_PORT")
fi
if (( FORCE_INIT )); then
  INIT_ARGS+=(--force)
fi
"$VENV_DIR/bin/autoclaw" "${INIT_ARGS[@]}"

SERVICE_INSTALL_ARGS=(
  service install
  --name "$SERVICE_NAME"
  --config "$CONFIG_PATH"
  --unit-dir "$UNIT_DIR"
)
if [[ -n "$API_PORT" ]]; then
  SERVICE_INSTALL_ARGS+=(--port "$API_PORT")
fi
if (( NO_START )); then
  SERVICE_INSTALL_ARGS+=(--no-start)
fi
AUTOCLAW_SYSTEMCTL_BIN="$SYSTEMCTL_BIN" \
  "$VENV_DIR/bin/autoclaw" "${SERVICE_INSTALL_ARGS[@]}"

echo "Installed $SERVICE_NAME.service"
echo "  unit:   $UNIT_PATH"
echo "  config: $CONFIG_PATH"
echo "  data:   $DATA_DIR"
echo "  venv:   $VENV_DIR"
if (( NO_START )); then
  echo "Service was not started. Start it with: systemctl --user start $SERVICE_NAME.service"
else
  echo "Check status with: systemctl --user status $SERVICE_NAME.service --no-pager"
fi
echo "To keep the user service running after logout, enable linger separately if desired:"
echo "  sudo loginctl enable-linger $USER"
