#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CONDA_BIN="${CONDA_EXE:-$(command -v conda || true)}"
if [ -z "$CONDA_BIN" ]; then CONDA_BIN="$HOME/miniconda3/bin/conda"; fi
"$CONDA_BIN" create -n lingpu python=3.11 -y
"$CONDA_BIN" run --no-capture-output -n lingpu python -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
"$CONDA_BIN" run --no-capture-output -n lingpu python -m pip install -r backend/requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cu128
"$CONDA_BIN" run --no-capture-output -n lingpu python backend/scripts/download_models.py
if ! command -v npm >/dev/null 2>&1; then
  if [ -f "$HOME/.nvm/nvm.sh" ]; then source "$HOME/.nvm/nvm.sh"; fi
fi
(cd frontend && npm ci)
