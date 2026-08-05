#!/usr/bin/env python3
"""Run an existing VBench video-only dimension without an input image."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))


VIDEO_ONLY_DIMENSIONS = {
    "subject_consistency",
    "background_consistency",
    "aesthetic_quality",
    "imaging_quality",
    "temporal_flickering",
    "motion_smoothness",
    "dynamic_degree",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos-path", required=True, type=Path)
    parser.add_argument("--output-path", required=True, type=Path)
    parser.add_argument("--dimension", required=True, choices=sorted(VIDEO_ONLY_DIMENSIONS))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--read-frame", action="store_true")
    args = parser.parse_args()

    if not args.videos_path.is_dir():
        raise FileNotFoundError(f"视频目录不存在: {args.videos_path}")
    video_count = sum(
        1
        for path in args.videos_path.rglob("*")
        if path.is_file() and path.suffix.lower() == ".mp4"
    )
    if video_count == 0:
        raise FileNotFoundError(f"视频目录中没有 MP4 文件: {args.videos_path}")
    print(f"视频-only 评测输入：{video_count} 个 MP4 文件（递归扫描）")

    from vbench import VBench

    args.output_path.mkdir(parents=True, exist_ok=True)
    evaluator = VBench(
        device=args.device,
        full_info_dir=str(ROOT / "source/vbench/VBench_full_info.json"),
        output_path=str(args.output_path),
    )
    evaluator.evaluate(
        videos_path=str(args.videos_path),
        name=args.dimension,
        dimension_list=[args.dimension],
        local=args.local,
        read_frame=args.read_frame,
        mode="custom_input",
    )


if __name__ == "__main__":
    main()
