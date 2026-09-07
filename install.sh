#!/bin/bash

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
IDENTITY=""
PROJECT=""
REPOSITORY=""

usage() {
  echo 'Usage: install.sh --identity "Your Name" --project project-id --repository /path/to/cairn'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --identity)
      IDENTITY="${2:-}"
      shift 2
      ;;
    --project)
      PROJECT="${2:-}"
      shift 2
      ;;
    --repository)
      REPOSITORY="${2:-}"
      shift 2
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done

if [ -z "$IDENTITY" ] || [ -z "$PROJECT" ] || [ -z "$REPOSITORY" ]; then
  usage
  exit 1
fi

case "$PROJECT" in
  *[!a-z0-9-]*|'')
    echo 'Project id must contain only lowercase letters, digits, and hyphens.' >&2
    exit 1
    ;;
esac

REPOSITORY="${REPOSITORY/#\~/$HOME}"
CAIRN_SKILLS_ROOT="${CAIRN_SKILLS_ROOT:-$HOME/.codex/skills}"
CAIRN_CONFIG_ROOT="${CAIRN_CONFIG_ROOT:-$HOME/.cairn}"
SKILL_TARGET="$CAIRN_SKILLS_ROOT/cairn-context"
CONFIG_TARGET="$CAIRN_CONFIG_ROOT/config.json"

if [ -e "$REPOSITORY" ] && [ -n "$(find "$REPOSITORY" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  echo "Refusing to overwrite non-empty repository: $REPOSITORY" >&2
  exit 1
fi

if [ -e "$SKILL_TARGET" ]; then
  echo "Refusing to overwrite existing Skill: $SKILL_TARGET" >&2
  exit 1
fi

mkdir -p "$REPOSITORY" "$CAIRN_CONFIG_ROOT" "$CAIRN_SKILLS_ROOT"
cp -R "$SOURCE_DIR/template/." "$REPOSITORY/"
mv "$REPOSITORY/projects/__PROJECT__" "$REPOSITORY/projects/$PROJECT"

TODAY="$(date +%F)"
python3 - "$REPOSITORY/projects/$PROJECT/README.md" "$REPOSITORY/projects/$PROJECT/state.md" "$PROJECT" "$IDENTITY" "$TODAY" <<'PY'
from pathlib import Path
import sys

readme, state, project, identity, today = sys.argv[1:]
replacements = {
    "__PROJECT__": project,
    "__IDENTITY__": identity,
    "__DATE__": today,
}
for name in (readme, state):
    path = Path(name)
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
PY

mkdir -p "$SKILL_TARGET/agents"
cp "$SOURCE_DIR/SKILL.md" "$SKILL_TARGET/SKILL.md"
cp "$SOURCE_DIR/agents/openai.yaml" "$SKILL_TARGET/agents/openai.yaml"

python3 - "$CONFIG_TARGET" "$REPOSITORY" "$IDENTITY" "$PROJECT" <<'PY'
import json
import sys

target, repository, identity, project = sys.argv[1:]
with open(target, "w", encoding="utf-8") as handle:
    json.dump(
        {"repository": repository, "identity": identity, "default_project": project},
        handle,
        ensure_ascii=False,
        indent=2,
    )
    handle.write("\n")
PY

echo "Created Cairn repository: $REPOSITORY"
echo "Installed Skill: $SKILL_TARGET"
echo "Configured: $CONFIG_TARGET"
