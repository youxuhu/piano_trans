#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
if ! command -v npm >/dev/null 2>&1; then
  if [ -f "$HOME/.nvm/nvm.sh" ]; then source "$HOME/.nvm/nvm.sh"; fi
fi
exec npm run dev -- --host 127.0.0.1
