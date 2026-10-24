#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

[[ $# -ge 1 ]] || die "Usage: preflight.sh RUN [--slurm] [--plots]"
run=$1
shift
checks=()
for option in "$@"; do
    case "$option" in
        --slurm) require_command sbatch; require_command squeue; require_command sacct ;;
        --plots) checks+=(--plots) ;;
        *) die "Unknown option: $option" ;;
    esac
done
exec "$PYTHON" "$SCRIPT_DIR/run_info.py" preflight "$run" "${checks[@]}"
