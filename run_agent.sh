#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
PYTHON="$ROOT/.venv/bin/python"

mkdir -p "$LOG_DIR"

{
  echo
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
  cd "$ROOT" || exit 1

  if [[ ! -x "$PYTHON" ]]; then
    echo "Python venv missing. Run: zsh prepare_mac.sh"
    exit 0
  fi

  if [[ ! -f "$ROOT/.env" ]]; then
    echo ".env missing. Run: zsh prepare_mac.sh"
    exit 0
  fi

  if ! /usr/bin/curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama is not available at http://127.0.0.1:11434"
    exit 0
  fi

  "$PYTHON" - <<'PY'
from dotenv import dotenv_values
values = dotenv_values(".env")
required = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN"]
missing = [name for name in required if not values.get(name)]
if missing:
    print("Waiting for Reddit credentials:", ", ".join(missing))
    raise SystemExit(2)
PY

  if [[ $? -eq 2 ]]; then
    exit 0
  fi

  "$PYTHON" agent.py
} >> "$LOG_DIR/agent.log" 2>&1
