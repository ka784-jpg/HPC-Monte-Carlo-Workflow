#!/usr/bin/env bash
#SBATCH --job-name=mcflow-collect
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --kill-on-invalid-dep=yes
#SBATCH --output=mcflow-collect-%j.out
#SBATCH --error=mcflow-collect-%j.err

set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: sbatch --dependency=afterok:JOB collect.sbatch RUN PYTHON MANIFEST_SHA256" >&2
    exit 2
fi
run=$1
python=$2
manifest=$3
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg

"$python" -c 'import sys; from mcflow.manifest import load_manifest; from mcflow.storage import digest, WorkflowError
if digest(load_manifest(sys.argv[1])) != sys.argv[2]:
    raise WorkflowError("Queued collector manifest mismatch")' "$run" "$manifest"
"$python" -m mcflow aggregate "$run"
exec "$python" -m mcflow plot "$run"
