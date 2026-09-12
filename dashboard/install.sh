#!/bin/bash
# Install the council dashboard as a launchd agent and publish it with Tailscale
# Funnel. Safe to re-run: an existing password and cookie secret are kept unless
# you deliberately type a new password.
#
#   dashboard/install.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COUNCIL_HOME="${COUNCIL_HOME:-$HOME/.council}"
PYTHON="$REPO/venv/bin/python3"
PLIST_SRC="$REPO/dashboard/launchd/com.tal.council.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.tal.council.plist"
LABEL="com.tal.council"
CONFIG="$COUNCIL_HOME/config.json"
PORT="${COUNCIL_PORT:-8787}"

[ -x "$PYTHON" ] || { echo "No venv at $PYTHON — create it first."; exit 1; }
[ -f "$PLIST_SRC" ] || { echo "Missing $PLIST_SRC"; exit 1; }

mkdir -p "$COUNCIL_HOME" "$HOME/Library/LaunchAgents"
chmod 700 "$COUNCIL_HOME"

# --- 1. password -------------------------------------------------------------

if [ -f "$CONFIG" ]; then
  PORT="$("$PYTHON" -c "import json,sys;print(json.load(open(sys.argv[1])).get('port',8787))" "$CONFIG")"
  echo "Config already at $CONFIG (port $PORT)."
  printf 'New password (leave empty to keep the current one): '
else
  echo "Funnel puts this on the public internet. Use a long, random password."
  printf 'Password (leave empty to have one generated): '
fi
read -rs PASSWORD
echo

if [ -z "$PASSWORD" ] && [ -f "$CONFIG" ]; then
  echo "Keeping the existing password and cookie secret."
else
  if [ -z "$PASSWORD" ]; then
    PASSWORD="$("$PYTHON" -c 'import secrets;print(secrets.token_urlsafe(24))')"
    echo "Generated password: $PASSWORD"
    echo "Write it down — it is not stored anywhere in readable form."
  fi
  REPO="$REPO" COUNCIL_HOME="$COUNCIL_HOME" PASSWORD="$PASSWORD" PORT="$PORT" "$PYTHON" - <<'PY'
import json, os, pathlib, sys
sys.path.insert(0, os.environ["REPO"])
from dashboard.app import make_config
path = pathlib.Path(os.environ["COUNCIL_HOME"]) / "config.json"
path.write_text(json.dumps(make_config(os.environ["PASSWORD"], int(os.environ["PORT"])), indent=1))
path.chmod(0o600)
print(f"wrote {path}")
PY
fi
unset PASSWORD

# --- 2. launchd agent --------------------------------------------------------

sed -e "s#@REPO@#$REPO#g" -e "s#@COUNCIL_HOME@#$COUNCIL_HOME#g" "$PLIST_SRC" > "$PLIST_DST"
echo "wrote $PLIST_DST"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_DST"
launchctl kickstart -k "gui/$UID/$LABEL"
echo "loaded $LABEL — logs: $COUNCIL_HOME/dashboard.log and dashboard.err"

# --- 3. public URL -----------------------------------------------------------

TS="$(command -v tailscale || true)"
[ -n "$TS" ] || [ ! -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ] || TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
if [ -z "$TS" ]; then
  echo "tailscale not found; the dashboard is reachable at http://127.0.0.1:$PORT only."
  exit 0
fi

echo "Publishing port $PORT with Tailscale Funnel..."
if "$TS" funnel --bg "$PORT"; then
  "$TS" funnel status || true
else
  cat <<'MSG'
Funnel refused. It has to be enabled once for this tailnet by its owner:
the command above prints an admin-console link — open it, allow Funnel,
then re-run this script. Until then the dashboard is local-only.
MSG
fi
