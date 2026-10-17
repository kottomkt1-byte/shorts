#!/usr/bin/env bash
set -euo pipefail
mkdir -p "${AUTO_SHORTS_DATA:-/data}"
if [[ "$(id -u)" == 0 ]]; then
  chown shorts:shorts "${AUTO_SHORTS_DATA:-/data}"
  exec gosu shorts python scripts/serve.py
fi
exec python scripts/serve.py
