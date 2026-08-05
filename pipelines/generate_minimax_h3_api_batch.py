#!/usr/bin/env python3
"""Generate VBench T2VA cases through a local MiniMax H3 HTTP API.

The API is synchronous and returns an MP4 body from ``/v1/videos/sync``.
Outputs follow the existing VBench generation layout:
  <output-dir>/<case_id>/<case_id>.mp4
  <output-dir>/<case_id>/case.json
  <output-dir>/<case_id>/research_results.jsonl
  <output-dir>/batch_results.json
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:9098")
    parser.add_argument("--prompt-field", default="prompt_eval_en")
    parser.add_argument("--duration", type=int, help="覆盖 cases 中的时长，单位秒")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--num-inference-steps", type=int, default=50)
    parser.add_argument("--flow-shift", type=float, default=12.0)
    parser.add_argument("--audio-flow-shift", type=float, default=3.0)
    parser.add_argument("--seed", type=int, help="覆盖所有 case 的 seed")
    parser.add_argument("--task", default="t2va")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    return parser.parse_args()


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"cases 必须是非空 JSON 数组: {path}")
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个 case 不是 JSON 对象")
        case = dict(item)
        case.setdefault("case_id", f"t2v-{index:04d}")
        cases.append(case)
    return cases


def effective_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    value = dict(case)
    if args.duration is not None:
        value["duration"] = args.duration
    for field in ("width", "height"):
        override = getattr(args, field)
        if override is not None:
            value[field] = override
    value["fps"] = args.fps
    if args.seed is not None:
        value["seed"] = args.seed
    for field in ("duration", "width", "height", "fps", "seed"):
        if field not in value or value[field] is None:
            raise ValueError(f"case {value['case_id']} 缺少参数: {field}")
        if int(value[field]) <= 0:
            raise ValueError(f"case {value['case_id']} 参数必须大于 0: {field}")
    return value


def post_video(base_url: str, case: dict[str, Any], args: argparse.Namespace, output: Path) -> dict[str, Any]:
    prompt = case.get(args.prompt_field)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"case {case['case_id']} 缺少有效 prompt 字段: {args.prompt_field}")
    duration = int(case["duration"])
    fields = {
        "prompt": prompt,
        "width": str(case["width"]),
        "height": str(case["height"]),
        "fps": str(case["fps"]),
        "num_inference_steps": str(args.num_inference_steps),
        "flow_shift": str(args.flow_shift),
        "seed": str(case["seed"]),
        "extra_params": json.dumps(
            {
                "task": args.task,
                "duration": duration,
                "audio_flow_shift": args.audio_flow_shift,
            },
            separators=(",", ":"),
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    started = time.monotonic()
    with requests.post(
        f"{base_url.rstrip('/')}/v1/videos/sync",
        data=fields,
        stream=True,
        timeout=(30, args.timeout),
    ) as response:
        if response.status_code >= 400:
            detail = response.text[:2000]
            raise RuntimeError(f"MiniMax API HTTP {response.status_code}: {detail}")
        content_type = response.headers.get("content-type", "")
        if "video" not in content_type and "octet-stream" not in content_type:
            preview = response.text[:1000]
            raise RuntimeError(f"API 返回的不是视频，content-type={content_type}: {preview}")
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    if not partial.is_file() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError("API 返回空视频")
    partial.replace(output)
    return {
        "content_type": content_type,
        "content_length": output.stat().st_size,
        "elapsed_sec": round(time.monotonic() - started, 2),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.retries < 0 or args.timeout <= 0:
        raise ValueError("--retries 必须非负，--timeout 必须大于 0")
    cases = load_cases(args.cases.resolve())
    output_root = args.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc).isoformat()

    for index, raw_case in enumerate(cases, 1):
        case = effective_case(raw_case, args)
        case_id = str(case["case_id"])
        case_dir = output_root / case_id
        video_path = case_dir / f"{case_id}.mp4"
        record: dict[str, Any] = {
            **case,
            "provider": "minimax_h3_local_api",
            "mode": args.task,
            "api_url": f"{args.base_url.rstrip('/')}/v1/videos/sync",
            "status": "pending",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        if args.resume and video_path.is_file() and video_path.stat().st_size > 0:
            record["status"] = "skipped"
            record["reason"] = "已有非空视频"
            results.append(record)
            print(f"[{index}/{len(cases)}] skipped {case_id}")
            continue

        write_json(case_dir / "case.json", case)
        attempts = args.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                record["attempt"] = attempt
                api_result = post_video(args.base_url, case, args, video_path)
                record.update(api_result)
                record["status"] = "success"
                break
            except Exception as exc:
                record["status"] = "error"
                record["error"] = str(exc)
                if attempt < attempts:
                    time.sleep(args.retry_delay)
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        results.append(record)
        with (case_dir / "research_results.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{index}/{len(cases)}] {record['status']} {case_id}")
        write_json(output_root / "batch_results.json", results)

    write_json(
        output_root / "batch_timing.json",
        {
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "case_count": len(cases),
            "success_count": sum(item["status"] in {"success", "skipped"} for item in results),
            "error_count": sum(item["status"] == "error" for item in results),
        },
    )
    return 0 if all(item["status"] in {"success", "skipped"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
