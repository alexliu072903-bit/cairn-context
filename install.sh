#!/bin/bash
# 保持原有命令行不变；实际逻辑在 install.py，便于测试且不依赖 bash 的平台差异。
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to install Cairn." >&2
  exit 1
fi

exec python3 "$(cd "$(dirname "$0")" && pwd)/install.py" install "$@"
