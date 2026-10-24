#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 ]] || { echo "Usage: retry.sh RUN [--submit] [--collect]" >&2; exit 2; }
run=$1
shift
# This reuses task IDs and seeds; the operator must first confirm old jobs have stopped.
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/submit.sh" "$run" --pending "$@"
