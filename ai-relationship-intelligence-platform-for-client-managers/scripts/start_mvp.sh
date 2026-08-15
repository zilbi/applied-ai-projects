#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Preparing database..."
python3 scripts/init_db.py
python3 scripts/seed_demo_data.py

run_in_terminal() {
  local command="$1"
  osascript \
    -e 'on run argv' \
    -e 'tell application "Terminal"' \
    -e 'do script item 1 of argv' \
    -e 'activate' \
    -e 'end tell' \
    -e 'end run' \
    "cd \"$ROOT_DIR\" && $command"
}

if command -v osascript >/dev/null 2>&1; then
  run_in_terminal "python3 main_api.py"
  run_in_terminal "python3 main_bot.py"
  echo "Started API and bot in separate Terminal windows."
else
  echo "Run these commands in separate terminals:"
  echo "cd '$ROOT_DIR' && python3 main_api.py"
  echo "cd '$ROOT_DIR' && python3 main_bot.py"
fi
