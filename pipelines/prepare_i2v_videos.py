#!/usr/bin/env python3
"""Prepare ComfyUI I2V batch outputs for VBench-i2v evaluation."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", required=True, type=Path)
    parser.add_argument("--batch-results", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--image-output", required=True, type=Path)
    args = parser.parse_args()

    batch_root = args.batch_root.resolve()
    batch_results = (args.batch_results or batch_root / "batch_results.json").resolve()
    output_root = args.output_root.resolve()
    image_root = args.image_root.resolve()
    image_output = args.image_output.resolve()

    records = json.loads(batch_results.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"batch_results 必须是 JSON 数组: {batch_results}")

    output_root.mkdir(parents=True, exist_ok=True)
    image_output.mkdir(parents=True, exist_ok=True)

    prepared = []
    missing = []
    used_names: dict[str, int] = {}

    for record in records:
        if record.get("status") != "success":
            continue

        case_id = record.get("case_id")
        prompt = str(record.get("prompt", "")).strip()
        if not case_id or not prompt:
            missing.append({"case_id": case_id, "reason": "missing case_id or prompt"})
            continue

        # batch_results uses IDs such as ``i2v-0001``, while the ComfyUI
        # output directories are named ``case-0001``.
        output_case_id = case_id.replace("i2v-", "case-", 1)
        case_dir = batch_root / output_case_id
        video_candidates = sorted(case_dir.glob("*.mp4"))
        if not video_candidates:
            missing.append({"case_id": case_id, "reason": "mp4 not found"})
            continue
        source_video = video_candidates[0]

        occurrence = used_names.get(prompt, 0)
        used_names[prompt] = occurrence + 1
        target_video = output_root / f"{prompt}-{occurrence}.mp4"
        shutil.copy2(source_video, target_video)

        raw_image = Path(str(record.get("image", "")))
        image_candidates = [raw_image, image_root / raw_image.name]
        source_image = next((path for path in image_candidates if path.is_file()), None)
        if source_image is None:
            missing.append({"case_id": case_id, "reason": f"image not found: {raw_image.name}"})
            continue

        # One source image may be reused by several I2V prompts, for example
        # the same image with "camera static" or "camera pans left".  The
        # evaluator resolves images by the video prompt stem, so create an
        # alias using the exact prompt name.
        target_image = image_output / f"{prompt}.jpg"
        shutil.copy2(source_image, target_image)
        prepared.append({
            "case_id": case_id,
            "prompt": prompt,
            "video": str(target_video),
            "image": str(target_image),
        })

    report = {
        "prepared": prepared,
        "missing": missing,
        "prepared_count": len(prepared),
        "missing_count": len(missing),
    }
    report_path = output_root.parent.parent / "i2v_prepare_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已整理 {len(prepared)} 个 I2V 视频；缺失 {len(missing)} 个")
    print(f"视频目录：{output_root}")
    print(f"图片目录：{image_output}")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    main()
