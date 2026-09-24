#!/bin/zsh

ROOT="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.spanishcue.reddit-agent"

echo "=== launchd ==="
if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  echo "loaded"
else
  echo "not loaded"
fi

echo
echo "=== local status ==="
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  cd "$ROOT"
  "$ROOT/.venv/bin/python" agent.py --status
else
  echo "Python venv missing."
fi

echo
echo "=== recent log ==="
if [[ -f "$ROOT/logs/agent.log" ]]; then
  tail -n 40 "$ROOT/logs/agent.log"
else
  echo "No agent log yet."
fi
