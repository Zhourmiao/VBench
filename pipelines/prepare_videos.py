#!/usr/bin/env python3
"""Validate and arrange generated T2V videos for VBench-2.0 standard mode."""

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
    parser.add_argument("--copy", action="store_true", help="复制视频；默认使用硬链接，跨磁盘时自动回退复制")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    missing: list[dict] = []
    prepared: list[dict] = []
    for case in cases:
        case_id = case["case_id"]
        source = args.generated_root / case_id / f"{case_id}.mp4"
        dimension = case["dimension"][0]
        filename = f"{case['prompt_eval_en'][:180]}-{case['sample_index']}.mp4"
        target = args.video_root / dimension / filename
        if not source.is_file() or source.stat().st_size == 0:
            missing.append({"case_id": case_id, "source": str(source), "target": str(target)})
            continue
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
    report = {"prepared": prepared, "missing": missing, "total": len(cases)}
    report_path = args.report or args.video_root.parent / "prepare_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已整理 {len(prepared)}/{len(cases)} 个视频；缺失 {len(missing)} 个")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
