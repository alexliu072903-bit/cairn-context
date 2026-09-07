#!/bin/bash

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYNC_SCRIPT="$REPO_DIR/scripts/sync.sh"
REMOTE_URL=""

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Automatic scheduling currently supports macOS only." >&2
  exit 1
fi

case "$REPO_DIR/" in
  "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*)
    echo "Refusing to install from a macOS protected directory: $REPO_DIR" >&2
    echo "Move the repository to a path such as $HOME/cairn and try again." >&2
    exit 1
    ;;
esac

if ! git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a Git repository: $REPO_DIR" >&2
  exit 1
fi

BRANCH="$(git -C "$REPO_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [ -z "$BRANCH" ]; then
  echo "Detached HEAD is not supported." >&2
  exit 1
fi

if ! REMOTE_URL="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null)"; then
  echo "Missing origin remote. Add a private remote and push the initial branch first." >&2
  exit 1
fi

if ! git -C "$REPO_DIR" ls-remote --exit-code origin "refs/heads/$BRANCH" >/dev/null 2>&1; then
  echo "The origin branch is unavailable. Push '$BRANCH' before enabling autosync." >&2
  exit 1
fi

if command -v gh >/dev/null 2>&1; then
  case "$REMOTE_URL" in
    https://github.com/*|git@github.com:*)
      REPO_SLUG="${REMOTE_URL#https://github.com/}"
      REPO_SLUG="${REPO_SLUG#git@github.com:}"
      REPO_SLUG="${REPO_SLUG%.git}"
      VISIBILITY="$(gh repo view "$REPO_SLUG" --json visibility --jq .visibility 2>/dev/null || true)"
      if [ "$VISIBILITY" = "PUBLIC" ]; then
        echo "Refusing to autosync personal context to a public GitHub repository: $REPO_SLUG" >&2
        exit 1
      fi
      ;;
  esac
fi

REPO_ID="$(printf '%s' "$REPO_DIR" | cksum | awk '{print $1}')"
PLIST_LABEL="ai.cairn.autosync.$REPO_ID"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LAUNCH_DOMAIN="gui/$(id -u)"
SERVICE_TARGET="$LAUNCH_DOMAIN/$PLIST_LABEL"

chmod +x "$SYNC_SCRIPT"
mkdir -p "$HOME/Library/LaunchAgents" "$REPO_DIR/.cairn"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SYNC_SCRIPT</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO_DIR</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$REPO_DIR/.cairn/sync.log</string>
  <key>StandardErrorPath</key>
  <string>$REPO_DIR/.cairn/sync.log</string>
</dict>
</plist>
EOF

launchctl bootout "$SERVICE_TARGET" 2>/dev/null || true
if ! launchctl bootstrap "$LAUNCH_DOMAIN" "$PLIST_PATH"; then
  echo "LaunchAgent installation failed. Plist: $PLIST_PATH" >&2
  exit 1
fi

if ! launchctl kickstart -k "$SERVICE_TARGET"; then
  launchctl bootout "$SERVICE_TARGET" 2>/dev/null || true
  echo "LaunchAgent failed to start. Log: $REPO_DIR/.cairn/sync.log" >&2
  exit 1
fi

echo "Autosync enabled every 30 minutes."
echo "Repository: $REPO_DIR"
echo "Remote: $REMOTE_URL"
echo "Log: $REPO_DIR/.cairn/sync.log"
