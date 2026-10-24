#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

[[ $# -ge 1 ]] || die "Usage: sleeper.sh RUN [--job-id ID] [--interval SECONDS] [--timeout SECONDS]"
run=$1
shift
job=
interval=60
timeout=86400
while (( $# )); do
    [[ $# -ge 2 ]] || die "Missing value for $1"
    case "$1" in
        --job-id) job=$2 ;;
        --interval) interval=$2 ;;
        --timeout) timeout=$2 ;;
        *) die "Unknown option: $1" ;;
    esac
    shift 2
done
positive_integer interval "$interval"
positive_integer timeout "$timeout"
if [[ -n $job ]]; then
    [[ $job =~ ^[0-9]+$ ]] || die "Job ID must be numeric"
    require_command squeue
    require_command sacct
fi
trap 'echo "Monitor interrupted; no jobs were cancelled." >&2; exit 130' INT
trap 'echo "Monitor terminated; no jobs were cancelled." >&2; exit 143' TERM
start=$SECONDS
while true; do
    printf '[%s] ' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    ready=0
    if "$PYTHON" "$SCRIPT_DIR/run_info.py" status "$run"; then
        ready=1
    else
        code=$?
        [[ $code -eq 3 ]] || exit "$code"
    fi
    if [[ -n $job ]]; then
        queue=$(squeue --noheader "--jobs=$job" --format=%T) || die "squeue failed; not treating this as completion"
        if [[ -n $queue ]]; then
            printf 'Array %s still in queue: %s\n' "$job" "$queue"
            ready=0
        else
            records=$(sacct --noheader --parsable2 "--jobs=$job" --format=JobID%80,State%40,ExitCode) || \
                die "sacct failed; accounting must be checked before completion"
            if "$PYTHON" "$SCRIPT_DIR/run_info.py" accounting "$run" --job-id "$job" <<< "$records"; then
                :
            else
                code=$?
                [[ $code -eq 3 ]] || exit "$code"
                ready=0
            fi
        fi
    fi
    if (( ready )); then
        printf 'All task outputs are complete and validated. No jobs were submitted by this monitor.\n'
        exit 0
    fi
    remaining=$((timeout - (SECONDS - start)))
    if (( remaining <= 0 )); then
        echo "Monitor timed out; unfinished work is not success. No jobs were cancelled." >&2
        exit 124
    fi
    delay=$interval
    (( delay <= remaining )) || delay=$remaining
    sleep "$delay"
done
