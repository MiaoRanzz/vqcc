#!/bin/bash
set -euo pipefail
umask 077
VQCC_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VQCC_CONDA_BIN="${VQCC_CONDA_BIN:-/root/miniconda3/bin/conda}"
if [[ ! -x "$VQCC_CONDA_BIN" ]]; then
  VQCC_CONDA_BIN="$(command -v conda)"
fi
VQCC_CONDA_ENV="${VQCC_CONDA_ENV:-vqcc}"
VQCC_ENV_PREFIX="$($VQCC_CONDA_BIN env list | awk -v env="$VQCC_CONDA_ENV" '$1 == env {print $NF; exit}')"
if [[ -z "$VQCC_ENV_PREFIX" || ! -x "$VQCC_ENV_PREFIX/bin/python" ]]; then
  echo "Required Conda environment $VQCC_CONDA_ENV is absent; refusing to use base." >&2
  exit 2
fi
export VQCC_ENV_PREFIX VQCC_CONDA_ENV VQCC_CONDA_BIN
cd -- "$VQCC_PROJECT_ROOT"
exec "$VQCC_CONDA_BIN" run --no-capture-output -n "$VQCC_CONDA_ENV" "$VQCC_ENV_PREFIX/bin/python" automation/runner.py "$@"
