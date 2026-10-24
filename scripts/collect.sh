#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# -eq 1 ]] || die "Usage: collect.sh RUN"
export MPLBACKEND=Agg
"$PYTHON" -m mcflow aggregate "$1"
exec "$PYTHON" -m mcflow plot "$1"
