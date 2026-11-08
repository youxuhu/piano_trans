#!/usr/bin/env bash
# Run the official Transkun CLI in its isolated environment. Transkun 2.0.1
# imports pkg_resources; install setuptools<81 in that environment first.
set -euo pipefail
CONDA_BIN="${CONDA_EXE:-$(command -v conda || true)}"
if [ -z "$CONDA_BIN" ]; then CONDA_BIN="$HOME/miniconda3/bin/conda"; fi
exec "$CONDA_BIN" run --no-capture-output -n lingpu-transkun python -m transkun.transcribe "$@"
