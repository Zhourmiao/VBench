#!/usr/bin/env python3
"""Build a reproducible generation manifest from cases and local video files."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_cases(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"cases.json 必须是 JSON 数组: {path}")
    return value


def sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_video(source_root: Path, case: dict[str, Any], benchmark: str) -> Path | None:
    case_id = str(case["case_id"])
    if benchmark == "vbench2":
        candidates = [
            source_root / case_id / f"{case_id}.mp4",
            source_root / case_id / "video.mp4",
        ]
    else:
        output_case_id = case_id.replace("i2v-", "case-", 1)
        candidates = [
            source_root / case_id / f"{case_id}.mp4",
            source_root / output_case_id / f"{output_case_id}.mp4",
            source_root / case_id / "video.mp4",
            source_root / output_case_id / "video.mp4",
        ]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    # Supports ComfyUI/API outputs whose filename is not controlled by us.
    for folder in (source_root / case_id, source_root / case_id.replace("i2v-", "case-", 1)):
        if folder.is_dir():
            matches = sorted(path for path in folder.rglob("*.mp4") if path.stat().st_size > 0)
            if matches:
                return matches[0]
    return None


def load_sidecar(video: Path) -> dict[str, Any]:
    sidecar = video.parent / "generation.json"
    if not sidecar.is_file():
        return {}
    value = json.loads(sidecar.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def manifest_video_path(video: Path | None, run_dir: Path) -> str | None:
    if video is None:
        return None
    try:
        return str(video.relative_to(run_dir))
    except ValueError:
        return str(video)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--source-root", type=Path, help="原始视频目录；默认 run_dir/generation")
    parser.add_argument("--benchmark", choices=("vbench2", "vbench_i2v"), default="vbench2")
    parser.add_argument("--hash", action="store_true", help="计算视频 SHA-256；大文件会增加扫描时间")
    parser.add_argument("--force", action="store_true", help="覆盖已有 manifest.jsonl")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    cases_path = (args.cases or run_dir / "cases" / "cases.json").resolve()
    source_root = (args.source_root or run_dir / "generation").resolve()
    output = run_dir / "generation" / "manifest.jsonl"
    if output.exists() and not args.force:
        raise FileExistsError(f"manifest 已存在，使用 --force 覆盖: {output}")

    cases = load_cases(cases_path)
    created_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    for case in cases:
        video = find_video(source_root, case, args.benchmark)
        sidecar = load_sidecar(video) if video else {}
        record: dict[str, Any] = {
            "manifest_version": 1,
            "run_id": run_dir.name,
            "case_id": case.get("case_id"),
            "benchmark": args.benchmark,
            "mode": "i2v" if args.benchmark == "vbench_i2v" else "t2v",
            "prompt": case.get("prompt_eval_en") or case.get("prompt_text") or case.get("prompt"),
            "dimension": case.get("dimension", []),
            "sample_index": case.get("sample_index"),
            "status": "success" if video else "missing",
            "video": manifest_video_path(video, run_dir),
            "created_at": created_at,
            "case": case,
        }
        if video:
            record["size_bytes"] = video.stat().st_size
            if args.hash:
                record["sha256"] = sha256(video)
        record["generation"] = sidecar
        records.append(record)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {
        "manifest_version": 1,
        "run_id": run_dir.name,
        "benchmark": args.benchmark,
        "created_at": created_at,
        "total": len(records),
        "success": sum(record["status"] == "success" for record in records),
        "missing": sum(record["status"] == "missing" for record in records),
        "path": str(output),
    }
    (run_dir / "generation" / "manifest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Manifest 已生成：{summary['success']}/{summary['total']} 成功，缺失 {summary['missing']} 个")
    print(f"清单：{output}")
    if summary["missing"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
