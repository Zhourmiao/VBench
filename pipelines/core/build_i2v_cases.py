#!/usr/bin/env python3
"""Build I2V generation cases from prompts, metadata, and input images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPTS = REPO_ROOT / "benchmarks/vbench_i2v/prompts/all_unique_prompts.txt"
DEFAULT_FULL_INFO = REPO_ROOT / "benchmarks/vbench_i2v/metadata/vbench2_i2v_full_info.json"
DEFAULT_IMAGE_ROOT = REPO_ROOT / "benchmarks/vbench_i2v/images/16-9"


def load_prompts(path: Path) -> list[str]:
    prompts = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not prompts:
        raise ValueError(f"prompt 文件为空: {path}")
    duplicates = sorted({prompt for prompt in prompts if prompts.count(prompt) > 1})
    if duplicates:
        raise ValueError(f"prompt 文件包含重复项: {duplicates[:3]}")
    return prompts


def load_metadata(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"full-info 必须是 JSON 数组: {path}")
    metadata: dict[str, dict[str, Any]] = {}
    for item in raw:
        prompt = item.get("prompt_en") if isinstance(item, dict) else None
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"full-info 存在缺少 prompt_en 的条目: {item}")
        if prompt in metadata:
            raise ValueError(f"full-info 存在重复 prompt_en: {prompt}")
        metadata[prompt] = item
    return metadata


def image_reference(image_path: Path) -> str:
    try:
        return str(image_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(image_path.resolve())


def build_cases(
    prompts_path: Path,
    full_info_path: Path,
    image_root: Path,
    duration: int,
    fps: int,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    prompts = load_prompts(prompts_path)
    metadata = load_metadata(full_info_path)
    cases: list[dict[str, Any]] = []
    missing_metadata: list[str] = []
    missing_images: list[str] = []

    for index, prompt in enumerate(prompts, start=1):
        item = metadata.get(prompt)
        if item is None:
            missing_metadata.append(prompt)
            continue
        image_name = item.get("image_name")
        if not isinstance(image_name, str) or not image_name:
            raise ValueError(f"metadata 缺少 image_name: {prompt}")
        image_path = image_root / image_name
        if not image_path.is_file():
            missing_images.append(str(image_path))
            continue
        cases.append(
            {
                "case_id": f"i2v-{index:04d}",
                "file_stem": Path(image_name).stem,
                "dimension": item.get("dimension", []),
                "image": image_reference(image_path),
                "prompt_text": prompt,
                "duration": duration,
                "fps": fps,
                "width": width,
                "height": height,
            }
        )

    if missing_metadata:
        raise ValueError(f"以下 prompt 在 full-info 中不存在: {missing_metadata[:5]}")
    if missing_images:
        raise FileNotFoundError(f"以下输入图片不存在: {missing_images[:5]}")
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--full-info", type=Path, default=DEFAULT_FULL_INFO)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for value, name in (
        (args.duration, "duration"),
        (args.fps, "fps"),
        (args.width, "width"),
        (args.height, "height"),
    ):
        if value <= 0:
            raise ValueError(f"{name} 必须大于 0")

    cases = build_cases(
        args.prompts.resolve(),
        args.full_info.resolve(),
        args.image_root.resolve(),
        args.duration,
        args.fps,
        args.width,
        args.height,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成 {len(cases)} 个 I2V cases: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
