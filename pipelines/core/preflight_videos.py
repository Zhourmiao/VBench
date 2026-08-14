#!/usr/bin/env python3
"""Run non-destructive preflight checks for a VBench run directory."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_video(path: Path) -> dict[str, Any]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("视频预检查需要 opencv-python") from exc

    capture = cv2.VideoCapture(str(path))
    try:
        opened = bool(capture.isOpened())
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps > 0 else 0.0
        first_frame_ok = False
        if opened:
            first_frame_ok, _ = capture.read()
        return {
            "path": str(path),
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else 0,
            "opened": opened,
            "first_frame_readable": bool(first_frame_ok),
            "frame_count": frame_count,
            "fps": round(fps, 4),
            "width": width,
            "height": height,
            "duration_seconds": round(duration, 4),
        }
    finally:
        capture.release()


def check_video(info: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not info["exists"]:
        return ["file_missing"]
    if info["size_bytes"] <= 0:
        errors.append("file_empty")
    if not info["opened"] or not info["first_frame_readable"]:
        errors.append("video_unreadable")
    if info["frame_count"] < 2:
        errors.append("too_few_frames")
    for field in ("width", "height"):
        value = expected.get(field)
        if value and info[field] != value:
            errors.append(f"{field}_mismatch:{info[field]}!={value}")
    expected_fps = expected.get("fps")
    if expected_fps and info["fps"] and abs(info["fps"] - expected_fps) > 0.5:
        errors.append(f"fps_mismatch:{info['fps']}!={expected_fps}")
    expected_duration = expected.get("duration")
    if expected_duration and info["duration_seconds"]:
        if abs(info["duration_seconds"] - expected_duration) > max(0.5, expected_duration * 0.15):
            errors.append(f"duration_mismatch:{info['duration_seconds']}!={expected_duration}")
    return errors


def t2v_checks(run_dir: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for case in cases:
        case_id = case["case_id"]
        path = run_dir / "generation" / case_id / f"{case_id}.mp4"
        info = probe_video(path)
        errors = check_video(info, case)
        result.append({"case_id": case_id, "video": info, "errors": errors})
    return result


def i2v_checks(run_dir: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared_root = run_dir / "videos" / "prepared"
    image_root = run_dir / "cases" / "images"
    result = []
    for case in cases:
        prompt = str(
            case.get("prompt_eval_en")
            or case.get("prompt_text")
            or case.get("prompt")
            or case.get("file_stem")
            or ""
        ).strip()
        video_candidates = sorted(prepared_root.glob(f"{prompt}-*.mp4")) if prompt else []
        image = image_root / f"{prompt}.jpg" if prompt else image_root / "missing.jpg"
        videos = []
        for path in video_candidates:
            info = probe_video(path)
            videos.append({"video": info, "errors": check_video(info, case)})
        errors = []
        if not video_candidates:
            errors.append("prepared_video_missing")
        if not image.is_file() or image.stat().st_size == 0:
            errors.append("custom_image_missing")
        result.append({
            "case_id": case.get("case_id"),
            "prompt": prompt,
            "image": {"path": str(image), "exists": image.is_file()},
            "videos": videos,
            "errors": errors,
        })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--stage", choices=("generation", "prepared"), default="generation")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    config_path = run_dir / "config" / "run.yaml"
    config = {}
    if config_path.is_file():
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except ImportError:
            print("提示：未安装 PyYAML，将按 cases.json 进行检查", file=sys.stderr)
    cases_path = run_dir / "cases" / "cases.json"
    if not cases_path.is_file():
        raise FileNotFoundError(f"缺少案例文件: {cases_path}")
    cases = load_json(cases_path)
    if not isinstance(cases, list):
        raise ValueError(f"cases.json 必须是 JSON 数组: {cases_path}")

    benchmark = config.get("benchmark", "vbench2")
    if benchmark == "vbench2" and args.stage == "generation":
        records = t2v_checks(run_dir, cases)
    elif benchmark == "vbench_i2v" and args.stage == "prepared":
        records = i2v_checks(run_dir, cases)
    else:
        raise ValueError(
            f"当前检查组合不支持: benchmark={benchmark}, stage={args.stage}；"
            "T2V 使用 generation，I2V 使用 prepared"
        )

    bad = [item for item in records if item.get("errors") or any(v.get("errors") for v in item.get("videos", []))]
    report = {
        "run_id": config.get("run_id", run_dir.name),
        "benchmark": benchmark,
        "stage": args.stage,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(records),
        "passed_cases": len(records) - len(bad),
        "failed_cases": len(bad),
        "records": records,
    }
    report_path = (args.report or run_dir / "videos" / f"preflight_{args.stage}_report.json").resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"预检查完成：通过 {report['passed_cases']}/{report['total_cases']}，失败 {report['failed_cases']}")
    print(f"报告：{report_path}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
