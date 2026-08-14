#!/usr/bin/env python3
"""Batch launcher for the VBench-2.0 prompt-only T2V runner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from t2v_common import DEFAULT_NODES, write_json


REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_FIELDS = (
    "template", "nodes", "concurrency", "prompt_node", "prompt_input_key",
    "negative_prompt_node", "negative_prompt_input_key", "seed_nodes", "seed_input_key",
    "width_node", "width_input_key", "height_node", "height_input_key",
    "fps_nodes", "fps_input_key", "duration_node", "duration_input_key",
    "duration_scale", "duration_offset", "bypass_nodes", "negative_prompt",
    "seed", "width", "height", "fps", "duration", "prompt_field",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--generation-config", type=Path, help="工作流配置 YAML/JSON")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--nodes", nargs="+", default=DEFAULT_NODES)
    parser.add_argument("--concurrency", type=int, default=1)
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
    parser.add_argument("--seed", type=int, help="覆盖所有 case 的 seed")
    parser.add_argument("--width", type=int, help="覆盖所有 case 的宽度")
    parser.add_argument("--height", type=int, help="覆盖所有 case 的高度")
    parser.add_argument("--fps", type=int, help="覆盖所有 case 的 FPS")
    parser.add_argument("--duration", type=int, help="覆盖所有 case 的视频时长（秒）")
    parser.add_argument("--prompt-field", default="prompt_input", help="从 case JSON 读取 prompt 的字段名")
    parser.add_argument("--resume", action="store_true", help="跳过输出目录中已经生成的非空视频")
    parser.add_argument("--retries", type=int, default=0, help="每个失败 case 的额外重试次数")
    parser.add_argument("--retry-delay", type=float, default=5.0, help="重试前等待秒数")
    return parser.parse_args()


def load_generation_config(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("读取工作流 YAML 配置需要 PyYAML") from exc
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"工作流配置必须是对象: {path}")
    return value


def apply_generation_config(args: argparse.Namespace) -> argparse.Namespace:
    if not args.generation_config:
        if args.template is None:
            raise ValueError("必须提供 --template 或 --generation-config")
        return args
    config_path = args.generation_config.resolve()
    config = load_generation_config(config_path)
    explicit = set(sys.argv[1:])
    for field in CONFIG_FIELDS:
        option = "--" + field.replace("_", "-")
        if field in config and option not in explicit:
            setattr(args, field, config[field])
    if args.template is None:
        raise ValueError(f"配置中缺少 template: {config_path}")
    args.template = Path(args.template)
    if not args.template.is_absolute():
        args.template = (REPO_ROOT / args.template).resolve()
    return args


def run_one(case: dict[str, Any], index: int, node: str, args: argparse.Namespace) -> dict[str, Any]:
    case_id = case.get("case_id", f"t2v-{index:04d}")
    case_output = args.output_dir / case_id
    started_at = datetime.now(timezone.utc)
    started_mono = time.monotonic()
    try:
        case = dict(case)
        if args.duration is not None:
            if args.duration <= 0:
                raise ValueError("--duration 必须大于 0")
            case["duration"] = args.duration
        for field in ("seed", "width", "height", "fps"):
            value = getattr(args, field)
            if value is not None:
                if value <= 0:
                    raise ValueError(f"--{field} 必须大于 0")
                case[field] = value
        case_output.mkdir(parents=True, exist_ok=True)
        case_path = case_output / "case.json"
        write_json(case_path, case)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools/generate_t2v_single.py"),
            "--case", str(case_path),
            "--template", str(args.template),
            "--nodes", node,
            "--output-dir", str(case_output),
            "--output-name", f"{case_id}.mp4",
            "--prompt", str(case.get(args.prompt_field, "")),
            "--prompt-node", args.prompt_node,
            "--prompt-input-key", args.prompt_input_key,
            "--negative-prompt-node", args.negative_prompt_node,
            "--negative-prompt-input-key", args.negative_prompt_input_key,
            "--width-node", args.width_node,
            "--width-input-key", args.width_input_key,
            "--height-node", args.height_node,
            "--height-input-key", args.height_input_key,
            "--duration-node", args.duration_node,
            "--duration-input-key", args.duration_input_key,
            "--duration-scale", str(args.duration_scale),
            "--duration-offset", str(args.duration_offset),
            "--seed-input-key", args.seed_input_key,
            "--fps-input-key", args.fps_input_key,
        ]
        for flag, values in [("--seed-nodes", args.seed_nodes), ("--fps-nodes", args.fps_nodes), ("--bypass-nodes", args.bypass_nodes)]:
            if values:
                command.extend([flag, *values])
        if args.negative_prompt is not None:
            command.extend(["--negative-prompt", args.negative_prompt])
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
        returncode = completed.returncode
        status = "success" if returncode == 0 else "error"
        stdout = completed.stdout[-2000:]
        stderr = completed.stderr[-2000:]
    except Exception as exc:
        returncode = 1
        status = "error"
        stdout = ""
        stderr = str(exc)
    return {
        "case_index": index,
        "case_id": case_id,
        "node": node,
        "prompt_field": args.prompt_field,
        "prompt": case.get(args.prompt_field),
        "prompt_eval_en": case.get("prompt_eval_en"),
        "seed": case.get("seed"),
        "output_dir": str(case_output),
        "returncode": returncode,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.monotonic() - started_mono, 2),
    }


def run_one_with_retries(case: dict[str, Any], index: int, node: str, args: argparse.Namespace) -> dict[str, Any]:
    attempts = args.retries + 1
    result: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        result = run_one(case, index, node, args)
        result["attempt"] = attempt
        if result["status"] == "success" or attempt == attempts:
            return result
        if args.retry_delay:
            time.sleep(args.retry_delay)
    return result


def output_is_complete(case: dict[str, Any], index: int, args: argparse.Namespace) -> bool:
    case_id = case.get("case_id", f"t2v-{index:04d}")
    output_path = args.output_dir / case_id / f"{case_id}.mp4"
    return output_path.is_file() and output_path.stat().st_size > 0


def write_batch_results(path: Path, results: list[dict[str, Any]]) -> None:
    write_json(path, sorted(results, key=lambda item: item["case_index"]))


def main() -> None:
    batch_started_at = datetime.now(timezone.utc)
    args = apply_generation_config(parse_args())
    if args.concurrency < 1:
        raise ValueError("--concurrency 必须大于等于 1")
    if args.retries < 0:
        raise ValueError("--retries 必须大于等于 0")
    if args.retry_delay < 0:
        raise ValueError("--retry-delay 必须大于等于 0")
    if not args.nodes:
        raise ValueError("至少需要一个 ComfyUI 节点")
    args.cases = args.cases.resolve()
    args.template = args.template.resolve()
    args.output_dir = args.output_dir.resolve()
    if not args.cases.is_file():
        raise FileNotFoundError(args.cases)
    if not args.template.is_file():
        raise FileNotFoundError(args.template)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases 文件必须是非空 JSON 数组")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, Any]]] = []
    for index, case in enumerate(cases, start=1):
        if args.resume and output_is_complete(case, index, args):
            case_id = case.get("case_id", f"t2v-{index:04d}")
            results.append(
                {
                    "case_index": index,
                    "case_id": case_id,
                    "status": "skipped",
                    "output_dir": str(args.output_dir / case_id),
                    "reason": "已有非空视频文件",
                }
            )
            print(f"[{index}] skipped 已存在视频 case={case_id}")
        else:
            pending.append((index, case))

    batch_results_path = args.output_dir / "batch_results.json"
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(run_one_with_retries, case, index, args.nodes[(index - 1) % len(args.nodes)], args): index
            for index, case in pending
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{result['case_index']}] {result['status']} node={result['node']}")
            write_batch_results(batch_results_path, results)
    write_batch_results(batch_results_path, results)
    write_json(
        args.output_dir / "batch_timing.json",
        {
            "started_at": batch_started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_sec": round(time.time() - batch_started_at.timestamp(), 2),
            "case_count": len(cases),
            "success_count": sum(item["status"] in {"success", "skipped"} for item in results),
            "skipped_count": sum(item["status"] == "skipped" for item in results),
            "error_count": sum(item["status"] == "error" for item in results),
        },
    )
    print(f"结果已保存到 {args.output_dir / 'batch_results.json'}")


if __name__ == "__main__":
    main()
