#!/usr/bin/env bash
set -Eeuo pipefail

# Append one sample per prompt to an existing T2V run.
# Usage:
#   bash scripts/append_t2v_cases.sh runs/<run_id>

RUN_DIR_INPUT="${1:?用法: $0 <run_dir>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$RUN_DIR_INPUT" ]]; then
  echo "run 目录不存在：$RUN_DIR_INPUT" >&2
  exit 1
fi

RUN_DIR="$(cd "$RUN_DIR_INPUT" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$REPO_ROOT"

"$PYTHON_BIN" -u pipelines/build_t2v_cases.py \
  --output-dir "$RUN_DIR/cases" \
  --append \
  --samples-per-prompt 1 \
  --input-language en

echo "cases 追加完成：$RUN_DIR/cases/cases.json"
