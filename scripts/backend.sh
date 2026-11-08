#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
CONDA_BIN="${CONDA_EXE:-$(command -v conda || true)}"
if [ -z "$CONDA_BIN" ]; then CONDA_BIN="$HOME/miniconda3/bin/conda"; fi
exec "$CONDA_BIN" run --no-capture-output -n lingpu python -m uvicorn main:app --host 127.0.0.1 --port 8000
