#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -z "${CODESPACE_NAME:-}" ]]; then
  echo 'This launcher requires GitHub Codespaces. For local use, run npm run dev.' >&2
  exit 1
fi
shorts_port="${AUTO_SHORTS_PORT:-8787}"
if [[ ! "$shorts_port" =~ ^[0-9]{4,5}$ ]] || (( shorts_port < 1024 || shorts_port > 65535 )); then
  echo 'AUTO_SHORTS_PORT must be a port between 1024 and 65535.' >&2
  exit 1
fi
shorts_host="${CODESPACE_NAME}-${shorts_port}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
export AUTO_SHORTS_HOSTS="$shorts_host"
export AUTO_SHORTS_ORIGINS="https://$shorts_host"
export AUTO_SHORTS_SECURE_COOKIE=1
if [[ ! -f .venv/bin/python || ! -f dist/index.html ]]; then
  echo 'Setup is incomplete. Run bash scripts/codespaces-setup.sh first.' >&2
  exit 1
fi
if ! curl --fail --silent --max-time 2 "http://127.0.0.1:$shorts_port/api/config" >/dev/null; then
  mkdir -p data
  nohup .venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port "$shorts_port" \
    >data/codespaces-server.log 2>&1 </dev/null &
  shorts_pid=$!
  for ((attempt=0; attempt<60; attempt++)); do
    if curl --fail --silent --max-time 2 "http://127.0.0.1:$shorts_port/api/config" >/dev/null; then
      break
    fi
    if ! kill -0 "$shorts_pid" 2>/dev/null; then
      tail -30 data/codespaces-server.log >&2
      exit 1
    fi
    sleep 1
  done
  curl --fail --silent --max-time 2 "http://127.0.0.1:$shorts_port/api/config" >/dev/null
fi
echo "Auto Shorts Studio: https://$shorts_host"
echo "Open port $shorts_port from the Codespaces Ports tab. Keep its visibility Private."
