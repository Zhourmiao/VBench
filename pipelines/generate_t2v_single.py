#!/usr/bin/env python3
"""Submit one prompt-only LTX-2.3 T2V workflow to ComfyUI."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from t2v_common import DEFAULT_NODES, download_output, poll_job, submit_workflow, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--prompt")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--nodes", nargs="+", default=DEFAULT_NODES)
    parser.add_argument("--prompt-node", default="267:266")
    parser.add_argument("--prompt-input-key", default="value")
    parser.add_argument("--negative-prompt-node", default="267:247")
    parser.add_argument("--negative-prompt-input-key", default="text")
    parser.add_argument("--seed-nodes", nargs="*", default=["267:216", "267:237"])
    parser.add_argument("--seed-input-key", default="noise_seed")
    parser.add_argument("--width-node", default="267:257")
    parser.add_argument("--width-input-key", default="value")
    parser.add_argument("--height-node", default="267:258")
    parser.add_argument("--height-input-key", default="value")
    parser.add_argument("--fps-nodes", nargs="*", default=["267:260"])
    parser.add_argument("--fps-input-key", default="value")
    parser.add_argument("--duration-node", default="267:225")
    parser.add_argument("--duration-input-key", default="value")
    parser.add_argument("--duration-scale", type=float, default=1.0)
    parser.add_argument("--duration-offset", type=float, default=0.0)
    parser.add_argument("--bypass-nodes", nargs="*", default=[])
    parser.add_argument("--negative-prompt")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--duration", type=int)
    parser.add_argument("--output-name", default="output.mp4")
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    return parser.parse_args()


def node_inputs(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
    if node_id not in workflow or not isinstance(workflow[node_id], dict):
        raise KeyError(f"workflow 中不存在节点 {node_id}")
    return workflow[node_id].setdefault("inputs", {})


def set_workflow_inputs(workflow: dict[str, Any], args: argparse.Namespace) -> None:
    if not args.prompt:
        raise ValueError("必须通过 --prompt 或 --case 提供 prompt")
    node_inputs(workflow, args.prompt_node)[args.prompt_input_key] = args.prompt
    if args.negative_prompt is not None:
        node_inputs(workflow, args.negative_prompt_node)[args.negative_prompt_input_key] = args.negative_prompt
    if args.seed is not None:
        for node_id in args.seed_nodes:
            node_inputs(workflow, node_id)[args.seed_input_key] = args.seed
    if args.width is not None:
        node_inputs(workflow, args.width_node)[args.width_input_key] = args.width
    if args.height is not None:
        node_inputs(workflow, args.height_node)[args.height_input_key] = args.height
    if args.fps is not None:
        for node_id in args.fps_nodes:
            inputs = node_inputs(workflow, node_id)
            if args.fps_input_key in inputs:
                inputs[args.fps_input_key] = args.fps
    if args.duration is not None:
        node_inputs(workflow, args.duration_node)[args.duration_input_key] = int(
            args.duration * args.duration_scale + args.duration_offset
        )
    for node_id in args.bypass_nodes:
        node_inputs(workflow, node_id)["bypass"] = True


def effective_parameters(workflow: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    def values(node_ids: list[str], key: str) -> dict[str, Any]:
        return {node_id: node_inputs(workflow, node_id).get(key) for node_id in node_ids}

    return {
        "prompt": node_inputs(workflow, args.prompt_node).get(args.prompt_input_key),
        "negative_prompt": node_inputs(workflow, args.negative_prompt_node).get(args.negative_prompt_input_key),
        "seed": values(args.seed_nodes, args.seed_input_key),
        "width": node_inputs(workflow, args.width_node).get(args.width_input_key),
        "height": node_inputs(workflow, args.height_node).get(args.height_input_key),
        "fps": values(args.fps_nodes, args.fps_input_key),
        "duration": node_inputs(workflow, args.duration_node).get(args.duration_input_key),
        "duration_scale": args.duration_scale,
        "duration_offset": args.duration_offset,
        "bypass_nodes": list(args.bypass_nodes),
    }


def load_case(args: argparse.Namespace) -> dict[str, Any]:
    if args.case is None:
        return {}
    case = json.loads(args.case.read_text(encoding="utf-8"))
    args.prompt = args.prompt or case.get("prompt_input")
    args.seed = args.seed if args.seed is not None else case.get("seed")
    args.width = args.width if args.width is not None else case.get("width")
    args.height = args.height if args.height is not None else case.get("height")
    args.fps = args.fps if args.fps is not None else case.get("fps")
    args.duration = args.duration if args.duration is not None else case.get("duration")
    return case


def main() -> int:
    args = parse_args()
    case = load_case(args)
    if not args.template.is_file():
        raise FileNotFoundError(args.template)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    workflow = json.loads(args.template.read_text(encoding="utf-8"))
    set_workflow_inputs(workflow, args)
    write_json(args.output_dir / "workflow.json", workflow)
    if case:
        write_json(args.output_dir / "case.json", case)

    node = args.nodes[0]
    started_wall = datetime.now(timezone.utc)
    started_mono = time.monotonic()
    record: dict[str, Any] = {
        **case,
        "node": node,
        "prompt": args.prompt,
        "seed": args.seed,
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "duration": args.duration,
        "template": str(args.template),
        "started_at": started_wall.isoformat(),
        "effective_parameters": effective_parameters(workflow, args),
    }
    try:
        prompt_id = submit_workflow(node, workflow)
        record["prompt_id"] = prompt_id
        result = poll_job(node, prompt_id, args.poll_interval, args.timeout)
        record.update(
            {
                "status": result.get("status"),
                "status_source": result.get("status_source"),
                "raw_result": result,
            }
        )
        if result.get("status") == "success":
            output_path = args.output_dir / args.output_name
            record["local_video"] = download_output(node, result, output_path)
    except Exception as exc:
        record.update({"status": "client_error", "error": str(exc)})
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["elapsed_sec"] = round(time.monotonic() - started_mono, 2)
    with (args.output_dir / "research_results.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record.get("status") == "success" and record.get("local_video") else 1


if __name__ == "__main__":
    raise SystemExit(main())
