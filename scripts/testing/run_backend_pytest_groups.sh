#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
BACKEND_ROOT="$REPO_ROOT"
BACKEND_SRC_ROOT="$BACKEND_ROOT/src"
PYTEST_BIN="${PYTEST_BIN:-pytest}"
PYTHONPATH="${PYTHONPATH:-$BACKEND_SRC_ROOT}"

export PYTHONPATH

print_usage() {
  cat <<'EOF'
Usage:
  run_backend_pytest_groups.sh list
  run_backend_pytest_groups.sh integration
  run_backend_pytest_groups.sh integration-local
  run_backend_pytest_groups.sh e2e-bounded
  run_backend_pytest_groups.sh e2e-reviewed
  run_backend_pytest_groups.sh e2e-staged
  run_backend_pytest_groups.sh e2e-all
EOF
}

describe_group() {
  label="$1"
  shift
  printf '%s:' "$label"
  for path in "$@"; do
    printf ' %s' "$path"
  done
  printf '\n'
}

run_group() {
  label="$1"
  shift
  printf '\n== %s ==\n' "$label"
  "$PYTEST_BIN" "$@" -q
}

list_suite() {
  suite="$1"
  printf '\n[%s]\n' "$suite"
  case "$suite" in
    integration|integration-local)
      describe_group \
        "workflow-and-runtime-schema" \
        tests/integration/runtime_schema_contract \
        tests/integration/test_readyz_real_db.py \
        tests/integration/test_startup_schema_guard.py \
        tests/integration/test_db_reset_db.py
      describe_group "bootstrap" tests/integration/bootstrap
      describe_group "operator" tests/integration/operator
      describe_group "runtime" tests/integration/runtime
      describe_group "mcp" tests/integration/mcp
      describe_group "public-surfaces" tests/integration/public_surfaces
      describe_group "workflow-authoring" tests/integration/workflows
      ;;
    e2e-bounded)
      describe_group \
        "workflow-bounded" \
        tests/e2e/workflows/test_published_workflow_start.py
      ;;
    e2e-reviewed)
      describe_group \
        "workflow-reviewed" \
        tests/e2e/workflows/test_recursive_wave_result.py
      ;;
    e2e-staged)
      describe_group \
        "workflow-staged" \
        tests/e2e/workflows/test_wait_watchdog_recovery.py
      ;;
    e2e-all)
      list_suite e2e-bounded
      list_suite e2e-reviewed
      list_suite e2e-staged
      ;;
    *)
      print_usage >&2
      exit 1
      ;;
  esac
}

run_integration_groups() {
  run_group \
    "workflow-and-runtime-schema" \
    tests/integration/runtime_schema_contract \
    tests/integration/test_readyz_real_db.py \
    tests/integration/test_startup_schema_guard.py \
    tests/integration/test_db_reset_db.py
  run_group "bootstrap" tests/integration/bootstrap
  run_group "operator" tests/integration/operator
  run_group "runtime" tests/integration/runtime
  run_group "mcp" tests/integration/mcp
  run_group "public-surfaces" tests/integration/public_surfaces
  run_group "workflow-authoring" tests/integration/workflows
}

run_e2e_suite() {
  suite="$1"
  case "$suite" in
    e2e-bounded)
      run_group \
        "workflow-bounded" \
        tests/e2e/workflows/test_published_workflow_start.py
      ;;
    e2e-reviewed)
      run_group \
        "workflow-reviewed" \
        tests/e2e/workflows/test_recursive_wave_result.py
      ;;
    e2e-staged)
      run_group \
        "workflow-staged" \
        tests/e2e/workflows/test_wait_watchdog_recovery.py
      ;;
    e2e-all)
      run_e2e_suite e2e-bounded
      run_e2e_suite e2e-reviewed
      run_e2e_suite e2e-staged
      ;;
    *)
      print_usage >&2
      exit 1
      ;;
  esac
}

main() {
  if [ "$#" -ne 1 ]; then
    print_usage >&2
    exit 1
  fi

  cd "$BACKEND_ROOT"

  case "$1" in
    list)
      list_suite integration
      list_suite e2e-all
      ;;
    integration|integration-local)
      run_integration_groups
      ;;
    e2e-bounded|e2e-reviewed|e2e-staged|e2e-all)
      run_e2e_suite "$1"
      ;;
    *)
      print_usage >&2
      exit 1
      ;;
  esac
}

main "$@"
