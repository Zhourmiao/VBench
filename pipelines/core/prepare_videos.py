#!/usr/bin/env python3
"""Validate and arrange generated T2V videos for VBench evaluation modes."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--generated-root", required=True, type=Path)
    parser.add_argument("--video-root", required=True, type=Path)
    parser.add_argument(
        "--quality-info",
        type=Path,
        help="包含 vbench_quality_dimensions 的 prompt metadata；启用后额外生成 quality 目录",
    )
    parser.add_argument(
        "--quality-video-root",
        type=Path,
        help="VBench 1.0 video-only 视频目录；需要与 --quality-info 一起使用",
    )
    parser.add_argument("--copy", action="store_true", help="复制视频；默认使用硬链接，跨磁盘时自动回退复制")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if bool(args.quality_info) != bool(args.quality_video_root):
        raise ValueError("--quality-info 和 --quality-video-root 必须同时提供")
    quality_by_prompt: dict[str, list[str]] = {}
    if args.quality_info:
        quality_items = json.loads(args.quality_info.read_text(encoding="utf-8"))
        if not isinstance(quality_items, list):
            raise ValueError(f"quality metadata 必须是 JSON 数组: {args.quality_info}")
        for item in quality_items:
            prompt = item.get("prompt_en")
            dimensions = item.get("vbench_quality_dimensions")
            if not isinstance(prompt, str) or not isinstance(dimensions, list) or not all(
                isinstance(dimension, str) and dimension for dimension in dimensions
            ):
                raise ValueError(f"quality metadata 缺少有效 prompt_en/vbench_quality_dimensions: {item}")
            quality_by_prompt[prompt] = dimensions

    missing: list[dict] = []
    prepared: list[dict] = []
    for case in cases:
        case_id = case["case_id"]
        source = args.generated_root / case_id / f"{case_id}.mp4"
        dimension = case["dimension"][0]
        filename = f"{case['prompt_eval_en'][:180]}-{case['sample_index']}.mp4"
        if not source.is_file() or source.stat().st_size == 0:
            missing.append({"case_id": case_id, "source": str(source)})
            continue

        targets = [(args.video_root, dimension)]
        if args.quality_info:
            try:
                quality_dimensions = quality_by_prompt[case["prompt_eval_en"]]
            except KeyError as exc:
                raise ValueError(
                    f"cases 中的 prompt 不在 quality metadata 中: {case['prompt_eval_en']}"
                ) from exc
            targets.extend((args.quality_video_root, item) for item in quality_dimensions)

        for root, target_dimension in targets:
            target = root / target_dimension / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.unlink()
            if args.copy:
                shutil.copy2(source, target)
            else:
                try:
                    target.hardlink_to(source)
                except OSError:
                    shutil.copy2(source, target)
            prepared.append({"case_id": case_id, "source": str(source), "target": str(target)})
    report = {
        "prepared": prepared,
        "missing": missing,
        "total": len(cases),
        "total_cases": len(cases),
        "prepared_cases": len({item["case_id"] for item in prepared}),
        "total_prepared_files": len(prepared),
        "quality_info": str(args.quality_info) if args.quality_info else None,
    }
    report_path = args.report or args.video_root.parent / "prepare_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    prepared_cases = len({item["case_id"] for item in prepared})
    print(
        f"已整理 {prepared_cases}/{len(cases)} 个 case，生成 {len(prepared)} 个评测文件；"
        f"缺失 {len(missing)} 个 case"
    )
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
