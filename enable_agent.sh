#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.spanishcue.reddit-agent.plist"
LABEL="com.spanishcue.reddit-agent"

cd "$ROOT"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing .venv. Run: zsh prepare_mac.sh"
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo "Missing .env. Run: zsh prepare_mac.sh"
  exit 1
fi

"$PYTHON" - <<'PY'
from dotenv import dotenv_values
values = dotenv_values(".env")
required = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REFRESH_TOKEN"]
missing = [name for name in required if not values.get(name)]
if missing:
    print("Cannot enable yet. Missing:", ", ".join(missing))
    raise SystemExit(1)
print("Reddit credentials are present.")
print("DRY_RUN =", values.get("DRY_RUN", "true"))
PY

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
chmod +x "$ROOT/run_agent.sh"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$ROOT/run_agent.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$ROOT</string>

  <key>RunAtLoad</key>
  <true/>

  <key>StartInterval</key>
  <integer>3600</integer>

  <key>StandardOutPath</key>
  <string>$ROOT/logs/launchd.out.log</string>

  <key>StandardErrorPath</key>
  <string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "gui/$UID/$LABEL"

echo
echo "Agent scheduled every 60 minutes."
echo "DRY_RUN remains controlled by .env."
echo "Status: zsh status_agent.sh"
