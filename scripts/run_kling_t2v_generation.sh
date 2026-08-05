#!/usr/bin/env bash
set -Eeuo pipefail

# Generate missing Kling T2V videos from an existing cases.json.
# Usage:
#   export KLING_API_KEY="..."
#   bash scripts/run_kling_t2v_generation.sh runs/<run_id>

RUN_DIR_INPUT="${1:?用法: $0 <run_dir>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$RUN_DIR_INPUT" ]]; then
  echo "run 目录不存在：$RUN_DIR_INPUT" >&2
  exit 1
fi

RUN_DIR="$(cd "$RUN_DIR_INPUT" && pwd)"

if [[ ! -f "$RUN_DIR/cases/cases.json" ]]; then
  echo "找不到 cases 文件：$RUN_DIR/cases/cases.json" >&2
  exit 1
fi

if [[ -z "${KLING_API_KEY:-}" && ( -z "${KLING_ACCESS_KEY:-}" || -z "${KLING_SECRET_KEY:-}" ) ]]; then
  echo "请先设置 KLING_API_KEY，或同时设置 KLING_ACCESS_KEY 和 KLING_SECRET_KEY" >&2
  exit 1
fi

cd "$REPO_ROOT"
mkdir -p "$RUN_DIR/generation"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -u pipelines/kling_generate_t2v.py \
  --cases "$RUN_DIR/cases/cases.json" \
  --output-root "$RUN_DIR/generation" \
  --model "${KLING_MODEL:-kling-3.0-turbo}" \
  --duration "${KLING_DURATION:-5}" \
  --aspect-ratio "${KLING_ASPECT_RATIO:-16:9}" \
  --poll-interval "${KLING_POLL_INTERVAL:-10}" \
  --timeout "${KLING_TIMEOUT:-900}" \
  2>&1 | tee "$RUN_DIR/generation/kling_generation.log"

echo "Kling 生成完成：$RUN_DIR/generation"
