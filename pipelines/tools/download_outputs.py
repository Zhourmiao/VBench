#!/usr/bin/env python3
"""Download completed I2V videos from existing research result records."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args()


def load_cases(results_root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for result_file in sorted(results_root.glob("case-*/research_results.jsonl")):
        records = []
        for line in result_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        if not records:
            continue
        attempts = []
        seen_prompt_ids = set()
        for record in reversed(records):
            prompt_id = record.get("prompt_id")
            if prompt_id and prompt_id not in seen_prompt_ids:
                attempts.append({"prompt_id": prompt_id, "node": record.get("node")})
                seen_prompt_ids.add(prompt_id)
        cases.append({
            "case_dir": result_file.parent.name,
            "records": records,
            "attempts": attempts,
        })
    return cases


def find_media_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("filename"), str) and value["filename"].lower().endswith(".mp4"):
            return value
        for child in value.values():
            found = find_media_item(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_media_item(child)
            if found:
                return found
    return None


def query_result(node: str, prompt_id: str, timeout: float) -> dict[str, Any]:
    errors = []
    for endpoint in (f"{node}/api/jobs/{prompt_id}", f"{node}/history/{prompt_id}"):
        try:
            response = requests.get(endpoint, timeout=60)
            response.raise_for_status()
            body = response.json()
            if endpoint.endswith(f"/history/{prompt_id}") and prompt_id in body:
                body = body[prompt_id]
            return body
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError("; ".join(errors))


def download_case(case: dict[str, Any], output_dir: Path, timeout: float) -> dict[str, Any]:
    case_dir = case["case_dir"]
    records = case["records"]
    result: dict[str, Any] = {
        "case_dir": case_dir,
        "prompt": records[-1].get("prompt"),
        "status": "not_found",
    }

    for attempt in case["attempts"]:
        prompt_id = attempt["prompt_id"]
        node = attempt.get("node")
        if not node:
            continue
        try:
            remote = query_result(node, prompt_id, timeout)
            media = find_media_item(remote.get("outputs", remote))
            execution_status = remote.get("execution_status", {}).get("status_str")
            if not media or execution_status not in {None, "success"}:
                continue
            params = {
                "filename": media["filename"],
                "subfolder": media.get("subfolder", ""),
                "type": media.get("type", "output"),
            }
            response = requests.get(f"{node}/view", params=params, timeout=timeout)
            response.raise_for_status()
            case_output_dir = output_dir / case_dir
            case_output_dir.mkdir(parents=True, exist_ok=True)
            output_path = case_output_dir / f"{case_dir}.mp4"
            output_path.write_bytes(response.content)
            result.update({
                "status": "downloaded",
                "node": node,
                "prompt_id": prompt_id,
                "remote_filename": media["filename"],
                "remote_subfolder": media.get("subfolder", ""),
                "local_video": str(output_path),
                "bytes": len(response.content),
            })
            return result
        except Exception as exc:
            result["last_error"] = str(exc)
    return result


def main() -> None:
    args = parse_args()
    if args.concurrency < 1:
        raise ValueError("--concurrency 必须大于等于 1")
    cases = load_cases(args.results_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(download_case, case, args.output_dir, args.timeout) for case in cases]
        for future in as_completed(futures):
            item = future.result()
            results.append(item)
            print(f"[{item['case_dir']}] {item['status']}")
    results.sort(key=lambda item: item["case_dir"])
    manifest = args.output_dir / "download_manifest.json"
    manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    downloaded = sum(item["status"] == "downloaded" for item in results)
    print(f"已下载 {downloaded}/{len(results)} 个视频")
    print(f"清单已保存到 {manifest}")


if __name__ == "__main__":
    main()
