#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

[[ $# -ge 1 ]] || die "Usage: submit.sh RUN [--submit] [--pending] [--collect]"
run=$1
shift
submit=0
collect=0
selection=()
for option in "$@"; do
    case "$option" in
        --submit) submit=1 ;;
        --pending) selection=(--pending) ;;
        --collect) collect=1 ;;
        *) die "Unknown option: $option" ;;
    esac
done

concurrency=${MC_CONCURRENCY:-4}
memory=${MC_MEMORY_MB:-256}
walltime=${MC_WALLTIME:-00:10:00}
positive_integer MC_CONCURRENCY "$concurrency"
positive_integer MC_MEMORY_MB "$memory"
[[ $walltime =~ ^[0-9]{2,3}:[0-5][0-9]:[0-5][0-9]$ ]] || die "MC_WALLTIME must be HH:MM:SS"
checks=()
(( collect == 0 )) || checks+=(--plots)
(( submit == 0 )) || checks+=(--slurm)
bash "$SCRIPT_DIR/preflight.sh" "$run" "${checks[@]}"
plan=$("$PYTHON" "$SCRIPT_DIR/run_info.py" plan "$run" "${selection[@]}")
mapfile -t values <<< "$plan"
run=${values[0]}
manifest=${values[1]}
indices=${values[2]}

site=()
[[ -z ${MC_ACCOUNT:-} ]] || site+=("--account=$MC_ACCOUNT")
[[ -z ${MC_PARTITION:-} ]] || site+=("--partition=$MC_PARTITION")
[[ -z ${MC_QOS:-} ]] || site+=("--qos=$MC_QOS")
array=(sbatch --parsable "${site[@]}" "--array=$indices%$concurrency"
       "--time=$walltime" "--mem=${memory}M" "--output=$run/logs/%A_%a.out"
       "--error=$run/logs/%A_%a.err" "$REPO_DIR/slurm/monte_carlo.sbatch" "$run" "$PYTHON" "$manifest")
collector=(sbatch --parsable "${site[@]}" "--output=$run/logs/collect-%j.out"
           "--error=$run/logs/collect-%j.err")
printf 'Array command:\n'
print_command "${array[@]}"
if (( collect )); then
    printf 'Collector command (ARRAY_JOB_ID is replaced after submission):\n'
    print_command "${collector[@]}" --dependency=afterok:ARRAY_JOB_ID \
        "$REPO_DIR/slurm/collect.sbatch" "$run" "$PYTHON" "$manifest"
fi
if (( submit == 0 )); then
    printf 'Dry run only. Add --submit to contact the scheduler.\n'
    exit 0
fi

lock="$run/.submission.lock"
mkdir -- "$lock" || die "Submission lock exists; investigate before retrying: $lock"
trap 'rmdir -- "$lock"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
raw=$("${array[@]}") || die "Array submission failed or outcome is unknown. Inspect Slurm before retrying."
job=${raw%%;*}
[[ $job =~ ^[0-9]+$ ]] || die "Unexpected sbatch response: $raw. Inspect Slurm; do not blindly retry."
printf 'ARRAY_JOB_ID=%s\n' "$job"
"$PYTHON" "$SCRIPT_DIR/run_info.py" receipt "$run" --job-id "$job" --indices "$indices"
if (( collect )); then
    raw=$("${collector[@]}" "--dependency=afterok:$job" \
        "$REPO_DIR/slurm/collect.sbatch" "$run" "$PYTHON" "$manifest") || \
        die "Array $job was submitted, but collector submission failed. The array has NOT been cancelled."
    collector_job=${raw%%;*}
    [[ $collector_job =~ ^[0-9]+$ ]] || die "Unexpected collector response: $raw. Array $job still exists."
    printf 'COLLECTOR_JOB_ID=%s\n' "$collector_job"
    "$PYTHON" "$SCRIPT_DIR/run_info.py" receipt "$run" --job-id "$job" \
        --indices "$indices" --collector "$collector_job"
fi
