#!/bin/bash
set -euo pipefail

LABEL=com.user.herdr-lark-bridge
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || true)"
[ -n "$UV" ] || UV=/opt/homebrew/bin/uv
[ -x "$UV" ] || { echo "uv not found" >&2; exit 1; }

CREDS="$HOME/.config/herdr-lark/credentials.env"
[ -f "$CREDS" ] || { echo "missing $CREDS (LARK_APP_ID, LARK_APP_SECRET)" >&2; exit 1; }
chmod 600 "$CREDS"

mkdir -p "$HOME/Library/Logs/herdr-lark" "$HOME/Library/LaunchAgents"
(cd "$REPO" && "$UV" sync --quiet)

DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
TMP="$(mktemp)"
sed -e "s|@UV@|$UV|g" -e "s|@REPO@|$REPO|g" -e "s|@HOME@|$HOME|g" \
  "$REPO/launchd/$LABEL.plist" > "$TMP"
plutil -lint "$TMP" >/dev/null

if [ "${1:-}" = "--dry-run" ]; then
  cat "$TMP"
  rm -f "$TMP"
  exit 0
fi

mv "$TMP" "$DEST"
DOMAIN="gui/$(id -u)"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST"
launchctl kickstart -k "$DOMAIN/$LABEL"
echo "installed $DEST; logs in ~/Library/Logs/herdr-lark/"
