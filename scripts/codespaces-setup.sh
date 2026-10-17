#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
sudo apt-get update
sudo apt-get install -y ffmpeg fonts-noto-cjk
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npm run build
.venv/bin/python scripts/doctor.py
