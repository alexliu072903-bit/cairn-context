#!/bin/bash

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
IDENTITY=""
PROJECT=""
REPOSITORY=""
# 每个目标是一个 skills 目录；Codex 目标额外安装 agents/openai.yaml。
TARGETS=()

usage() {
  cat >&2 <<'USAGE'
Usage: install.sh --identity "Your Name" --project project-id --repository /path/to/cairn [targets]

Targets (repeat or combine; default is --codex for backward compatibility):
  --codex              install the Skill to ~/.codex/skills
  --claude-code        install the Skill to ~/.claude/skills
  --skills-dir PATH    install the Skill to any other skills directory
USAGE
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
    --codex)
      TARGETS+=("codex:${CODEX_SKILLS_ROOT:-${CAIRN_SKILLS_ROOT:-$HOME/.codex/skills}}")
      shift
      ;;
    --claude-code)
      TARGETS+=("generic:${CLAUDE_SKILLS_ROOT:-$HOME/.claude/skills}")
      shift
      ;;
    --skills-dir)
      [ -n "${2:-}" ] || { usage; exit 1; }
      TARGETS+=("generic:${2/#\~/$HOME}")
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
CAIRN_CONFIG_ROOT="${CAIRN_CONFIG_ROOT:-$HOME/.cairn}"
CONFIG_TARGET="$CAIRN_CONFIG_ROOT/config.json"

if [ "${#TARGETS[@]}" -eq 0 ]; then
  TARGETS+=("codex:${CAIRN_SKILLS_ROOT:-$HOME/.codex/skills}")
fi

if [ -e "$REPOSITORY" ] && [ -n "$(find "$REPOSITORY" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  echo "Refusing to overwrite non-empty repository: $REPOSITORY" >&2
  exit 1
fi

# 先检查所有目标，任何一个已存在就整体拒绝，避免装到一半。
for target in "${TARGETS[@]}"; do
  if [ -e "${target#*:}/cairn-context" ]; then
    echo "Refusing to overwrite existing Skill: ${target#*:}/cairn-context" >&2
    exit 1
  fi
done

mkdir -p "$REPOSITORY" "$CAIRN_CONFIG_ROOT"
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

for target in "${TARGETS[@]}"; do
  kind="${target%%:*}"
  skill_target="${target#*:}/cairn-context"
  mkdir -p "$skill_target"
  cp "$SOURCE_DIR/SKILL.md" "$skill_target/SKILL.md"
  if [ "$kind" = "codex" ]; then
    mkdir -p "$skill_target/agents"
    cp "$SOURCE_DIR/agents/openai.yaml" "$skill_target/agents/openai.yaml"
  fi
done

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
for target in "${TARGETS[@]}"; do
  echo "Installed Skill: ${target#*:}/cairn-context"
done
echo "Configured: $CONFIG_TARGET"
