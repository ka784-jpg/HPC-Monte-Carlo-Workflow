#!/usr/bin/env bash
#SBATCH --job-name=mcflow-sample
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=256M
#SBATCH --time=00:10:00
#SBATCH --signal=B:TERM@60
#SBATCH --output=mcflow-%A_%a.out
#SBATCH --error=mcflow-%A_%a.err

set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: sbatch --array=... monte_carlo.sbatch RUN PYTHON MANIFEST_SHA256" >&2
    exit 2
fi
run=$1
python=$2
manifest=$3
: "${SLURM_ARRAY_TASK_ID:?This script requires a Slurm job array}"

export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
# exec makes the checkpoint-aware worker the batch process receiving Slurm's signal.
exec "$python" -m mcflow task "$run" \
    --task-id "$SLURM_ARRAY_TASK_ID" --expect-manifest "$manifest" \
    --min-free-mb "${MC_MIN_FREE_MB:-64}"
