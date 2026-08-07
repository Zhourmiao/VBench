#!/usr/bin/env python3
"""Select I2V metadata entries that contain a required set of dimensions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


# DEFAULT_DIMENSIONS = (
#     "i2v_background",
#     "background_consistency",
#     "aesthetic_quality",
#     "imaging_quality",
#     "temporal_flickering",
# )
DEFAULT_DIMENSIONS = (
            "i2v_subject",
            "subject_consistency",
            "motion_smoothness",
            "dynamic_degree",
            "aesthetic_quality",
            "imaging_quality",
            "temporal_flickering"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "benchmarks/vbench_i2v/metadata/vbench2_i2v_full_info.json"
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks/vbench_i2v/metadata/15_full_info.json"


def load_metadata(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"metadata 必须是对象数组: {path}")
    return value


def select_metadata(
    metadata: list[dict[str, Any]],
    dimensions: tuple[str, ...],
    count: int,
) -> list[dict[str, Any]]:
    required = set(dimensions)
    selected = [
        item for item in metadata
        if required.issubset(set(item.get("dimension", [])))
    ]
    if len(selected) < count:
        raise ValueError(
            f"符合全部维度 {list(dimensions)} 的数据只有 {len(selected)} 条，无法筛选 {count} 条"
        )
    return selected[:count]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument(
        "--dimensions",
        nargs="+",
        default=list(DEFAULT_DIMENSIONS),
        help="要求每条 metadata 同时包含的维度列表",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise ValueError("--count 必须大于 0")
    dimensions = tuple(args.dimensions)
    if not dimensions:
        raise ValueError("至少需要一个维度")

    metadata = load_metadata(args.input.resolve())
    selected = select_metadata(metadata, dimensions, args.count)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已从 {len(metadata)} 条 metadata 中筛选 {len(selected)} 条")
    print(f"维度：{', '.join(dimensions)}")
    print(f"输出：{args.output.resolve()}")


if __name__ == "__main__":
    main()
