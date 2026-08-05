#!/usr/bin/env bash
set -Eeuo pipefail

# Unified offline evaluation entrypoint for T2V and I2V runs.
# Usage: bash scripts/run_evaluation.sh <run_dir> [--resume]

RUN_DIR="${1:?用法: $0 <run_dir> [--resume]}"
RESUME_FLAG="${2:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$RUN_DIR" ]]; then
  echo "run 目录不存在：$RUN_DIR" >&2
  exit 1
fi

CONFIG_PATH=""
for candidate in "$RUN_DIR/config/run.yaml" "$RUN_DIR/config/run.json"; do
  if [[ -f "$candidate" ]]; then
    CONFIG_PATH="$candidate"
    break
  fi
done
if [[ -z "$CONFIG_PATH" ]]; then
  echo "缺少 run 配置：$RUN_DIR/config/run.yaml 或 run.json" >&2
  exit 1
fi

cd "$REPO_ROOT"
source "$REPO_ROOT/scripts/vbench_env.sh"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x /opt/conda/bin/python ]]; then
  PYTHON_BIN=/opt/conda/bin/python
else
  PYTHON_BIN=python3
fi

BENCHMARK="$($PYTHON_BIN - "$CONFIG_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.suffix.lower() == ".json":
    config = json.loads(path.read_text(encoding="utf-8"))
else:
    import yaml
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
print(config.get("benchmark", ""))
PY
)"

case "$BENCHMARK" in
  vbench2)
    export TORCH_HOME="$VBENCH2_TORCH_HOME"
    echo "[1/4] 生成 T2V generation manifest"
    "$PYTHON_BIN" -u pipelines/build_generation_manifest.py \
      --run-dir "$RUN_DIR" --benchmark vbench2 --hash --force
    echo "[2/4] 整理 T2V 视频"
    "$PYTHON_BIN" -u pipelines/prepare_videos.py \
      --cases "$RUN_DIR/cases/cases.json" \
      --generated-root "$RUN_DIR/generation" \
      --video-root "$RUN_DIR/videos/prepared"
    ;;
  vbench_i2v)
    export TORCH_HOME="$VBENCH_TORCH_HOME"
    echo "[1/4] 生成 I2V generation manifest"
    "$PYTHON_BIN" -u pipelines/build_generation_manifest.py \
      --run-dir "$RUN_DIR" --benchmark vbench_i2v --hash --force
    echo "[2/4] I2V 使用配置中的公共视频目录和输入图片目录"
    ;;
  *)
    echo "不支持的 benchmark：$BENCHMARK（应为 vbench2 或 vbench_i2v）" >&2
    exit 1
    ;;
esac

echo "[3/4] 检查模型、权重和 Python 依赖"
"$PYTHON_BIN" -u pipelines/check_models.py --run-dir "$RUN_DIR"

echo "[4/4] 启动统一评测调度器"
if [[ "$RESUME_FLAG" == "--resume" ]]; then
  "$PYTHON_BIN" -u pipelines/run_evaluation.py --run-dir "$RUN_DIR" --resume
else
  "$PYTHON_BIN" -u pipelines/run_evaluation.py --run-dir "$RUN_DIR"
fi

echo "评测流程完成：$RUN_DIR/evaluation"
