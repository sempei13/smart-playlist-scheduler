#!/bin/bash
# Double-click this file in Finder to install Smart Playlist Scheduler.
# It sets the app to start automatically when you log in, then opens it in your browser.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.smartplaylistscheduler"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/SmartPlaylistScheduler"
PORT=8765

echo "Installing Smart Playlist Scheduler from: $APP_DIR"
echo

# --- find a working Python 3 ---
PY=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3 isn't installed yet."
  echo "macOS will offer to install the Command Line Developer Tools (which include Python)."
  echo "Click Install, wait for it to finish, then double-click Install.command again."
  echo "(Alternatively, install Python from https://www.python.org/downloads/macos/)"
  xcode-select --install 2>/dev/null || true
  read -r -p "Press Return to close..." _
  exit 1
fi
echo "Using Python: $PY ($("$PY" --version 2>&1))"

# --- create the login item (LaunchAgent) ---
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$APP_DIR/app/server.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>SPS_PORT</key><string>$PORT</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/output.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/error.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$PLIST"

# wait for it to come up
for _ in $(seq 1 20); do
  if curl -s -o /dev/null "http://localhost:$PORT/api/state"; then break; fi
  sleep 0.5
done

echo
echo "Done! Smart Playlist Scheduler is running and will start automatically when you log in."
echo "Open it any time at:  http://localhost:$PORT  (or double-click 'Open Scheduler.command')"
echo
echo "Note: keep this folder where it is. If you move it, double-click Install.command again."
open "http://localhost:$PORT"
