#!/usr/bin/env python3
"""Batch launcher for the external LTX-2.3 I2V research runner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


DEFAULT_NODES = [
    "http://110.126.0.52:8181",
    "http://110.126.0.52:8182",
    "http://110.126.0.52:8183",
    "http://110.126.0.52:8184",
]
REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/batch"))
    parser.add_argument("--nodes", nargs="+", default=DEFAULT_NODES)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--prompt-field", default="prompt_text", help="从 case JSON 读取 prompt 的字段名")
    parser.add_argument("--resume", action="store_true", help="跳过输出目录中已经生成的非空视频")
    parser.add_argument("--retries", type=int, default=0, help="每个失败 case 的额外重试次数")
    parser.add_argument("--retry-delay", type=float, default=5.0, help="重试前等待秒数")
    return parser.parse_args()


def resolve_image_path(raw_path: str, cases_path: Path) -> Path:
    image_path = Path(raw_path)
    if image_path.is_absolute() and image_path.is_file():
        return image_path
    candidates = [
        Path.cwd() / image_path,
        cases_path.parent / image_path,
        cases_path.parent / "images" / image_path.name,
        REPO_ROOT / image_path,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"找不到案例图片 {raw_path!r}；已检查 cases.json 所在目录、其 images/ 子目录和仓库根目录"
    )


def append_case_argument(command: list[str], case: dict[str, Any], key: str, flag: str) -> None:
    value = case.get(key)
    if value is not None:
        command.extend([flag, str(value)])


def run_one(case: dict[str, Any], index: int, node: str, args: argparse.Namespace) -> dict[str, Any]:
    case_output = args.output_dir / f"case-{index:04d}"
    image_path = None
    try:
        image_path = resolve_image_path(case["image"], args.cases)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "tools/generate_i2v_single.py"),
            "--template",
            str(args.template),
            "--nodes",
            node,
            "--image",
            str(image_path),
            "--prompt",
            str(case.get(args.prompt_field, "")),
            "--output-dir",
            str(case_output),
        ]
        for key, flag in (
            ("sampler", "--sampler"),
            ("cfg", "--cfg"),
            ("lora_strength", "--lora-strength"),
            ("image_strength_1", "--image-strength-1"),
            ("image_strength_2", "--image-strength-2"),
            ("seed", "--seed"),
            ("width", "--width"),
            ("height", "--height"),
            ("duration", "--duration"),
            ("fps", "--fps"),
        ):
            append_case_argument(command, case, key, flag)
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
    result = {
        "case_index": index,
        "case_id": case.get("case_id", f"case-{index:04d}"),
        "node": node,
        "image": str(image_path) if image_path else case.get("image"),
        "prompt_field": args.prompt_field,
        "prompt": case.get(args.prompt_field),
        "output_dir": str(case_output),
        "returncode": returncode,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
    }
    return result


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


def output_is_complete(index: int, args: argparse.Namespace) -> bool:
    case_output = args.output_dir / f"case-{index:04d}"
    return any(path.is_file() and path.stat().st_size > 0 for path in case_output.glob("*.mp4"))


def write_batch_results(path: Path, results: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(sorted(results, key=lambda item: item["case_index"]), ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
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
    if not isinstance(cases, list):
        raise ValueError("cases 文件必须是 JSON 数组")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, Any]]] = []
    for index, case in enumerate(cases, start=1):
        if args.resume and output_is_complete(index, args):
            results.append(
                {
                    "case_index": index,
                    "case_id": case.get("case_id", f"case-{index:04d}"),
                    "status": "skipped",
                    "output_dir": str(args.output_dir / f"case-{index:04d}"),
                    "reason": "已有非空视频文件",
                }
            )
            print(f"[{index}] skipped 已存在视频 case={case.get('case_id', f'case-{index:04d}')}")
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
    print(f"结果已保存到 {batch_results_path}")


if __name__ == "__main__":
    main()
