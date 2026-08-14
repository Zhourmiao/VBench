#!/usr/bin/env python3
"""Run MiniMax H3 T2V cases through an already running ComfyUI server.

This is a thin H3-specific launcher around generate_t2v_batch.py.  It detects
the H3 subgraph node in an API-format workflow and keeps the existing VBench
case/output/retry/resume format.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--workflow", required=True, type=Path, help="ComfyUI API-format workflow JSON")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--nodes", nargs="+", required=True)
    parser.add_argument("--prompt-field", default="prompt_eval_en")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=24, help="记录到 case 元数据；H3 工作流通常固定为 24fps")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument("--negative-prompt")
    return parser.parse_args()


def find_h3_node(workflow: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for node_id, node in workflow.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        # The exported H3 subgraph exposes these controls.  Accept a few
        # prompt key variants because ComfyUI revisions may rename it.
        if "noise_seed" in inputs and "value_1" in inputs and any(
            key in inputs for key in ("prompt", "text", "prompt_text")
        ):
            candidates.append((node_id, inputs))
    if len(candidates) != 1:
        found = ", ".join(node_id for node_id, _ in candidates) or "无"
        raise ValueError(
            "无法唯一识别 MiniMax H3 节点；请确认使用 API 格式 workflow。"
            f" 候选节点: {found}"
        )
    return candidates[0]


def main() -> int:
    args = parse_args()
    workflow_path = args.workflow.resolve()
    if not workflow_path.is_file():
        raise FileNotFoundError(workflow_path)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict) or "nodes" in workflow:
        raise ValueError(
            "--workflow 必须是 ComfyUI API 格式 JSON；请在 ComfyUI 中使用 Save (API Format) 导出。"
        )
    node_id, inputs = find_h3_node(workflow)
    prompt_key = next(key for key in ("prompt", "text", "prompt_text") if key in inputs)
    print(f"识别 MiniMax H3 节点: {node_id}; prompt 输入: {prompt_key}")

    repo_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        str(repo_root / "pipelines/core/generate_t2v_batch.py"),
        "--cases", str(args.cases.resolve()),
        "--template", str(workflow_path),
        "--output-dir", str(args.output_dir.resolve()),
        "--nodes", *args.nodes,
        "--prompt-field", args.prompt_field,
        "--prompt-node", node_id,
        "--prompt-input-key", prompt_key,
        "--seed-nodes", node_id,
        "--seed-input-key", "noise_seed",
        "--width-node", node_id,
        "--width-input-key", "width",
        "--height-node", node_id,
        "--height-input-key", "height",
        "--duration-node", node_id,
        "--duration-input-key", "value_1",
        "--fps-nodes",
        "--duration", str(args.duration),
        "--width", str(args.width),
        "--height", str(args.height),
        "--fps", str(args.fps),
        "--concurrency", str(args.concurrency),
        "--retries", str(args.retries),
        "--retry-delay", str(args.retry_delay),
    ]
    if args.resume:
        command.append("--resume")
    if args.negative_prompt is not None:
        command.extend(["--negative-prompt", args.negative_prompt])
    return subprocess.call(command, cwd=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
