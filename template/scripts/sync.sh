#!/bin/bash

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$REPO_DIR/.cairn"
LOG_PATH="$STATE_DIR/sync.log"
LOCK_DIR="$STATE_DIR/sync.lock"

mkdir -p "$STATE_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG_PATH"
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

cd "$REPO_DIR" || exit 1

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "Not a Git repository; sync stopped"
  exit 1
fi

BRANCH="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [ -z "$BRANCH" ]; then
  log "Detached HEAD; sync stopped"
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  log "Missing origin remote; sync stopped"
  exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  git add -A
  if ! git diff --cached --quiet; then
    if ! git commit -m "auto-sync: $(date '+%Y-%m-%d %H:%M')" >> "$LOG_PATH" 2>&1; then
      log "Commit failed; sync stopped"
      exit 1
    fi
  fi
fi

attempt=1
while [ "$attempt" -le 3 ]; do
  if ! git fetch origin "$BRANCH" >> "$LOG_PATH" 2>&1; then
    log "Fetch failed ($attempt/3)"
    attempt=$((attempt + 1))
    continue
  fi

  if ! git rebase "origin/$BRANCH" >> "$LOG_PATH" 2>&1; then
    git rebase --abort >> "$LOG_PATH" 2>&1 || true
    log "Rebase conflict; aborted with local commits preserved"
    exit 1
  fi

  if git diff --quiet "origin/$BRANCH..HEAD"; then
    exit 0
  fi

  if git push origin "HEAD:$BRANCH" >> "$LOG_PATH" 2>&1; then
    exit 0
  fi

  log "Push rejected after remote update ($attempt/3); retrying"
  attempt=$((attempt + 1))
done

log "Sync failed after 3 attempts; local commits preserved"
exit 1
