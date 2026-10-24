#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# -ge 1 && $# -le 2 ]] || die "Usage: run_local.sh RUN [WORKERS]"
workers=${2:-1}
positive_integer WORKERS "$workers"
bash "$SCRIPT_DIR/preflight.sh" "$1" --plots
"$PYTHON" -m mcflow run "$1" --workers "$workers"
exec bash "$SCRIPT_DIR/collect.sh" "$1"
