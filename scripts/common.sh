#!/usr/bin/env bash
# Shared setup for the user-facing wrappers; batch files are deliberately self-contained.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON=${PYTHON:-python3}

die() { printf '%s\n' "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"; }
positive_integer() { [[ $2 =~ ^[1-9][0-9]*$ ]] || die "$1 must be a positive integer"; }
print_command() { printf '%q ' "$@"; printf '\n'; }

require_command "$PYTHON"
PYTHON=$("$PYTHON" -c 'import sys; print(sys.executable)')
