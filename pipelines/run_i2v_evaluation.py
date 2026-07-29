#!/usr/bin/env python3
"""Adapter for the VBench-i2v Python evaluation API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The wrapper is launched as a file from ``pipelines/``. Add the canonical
# source roots explicitly so it does not depend on the caller's PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "source/VBench"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--videos-path", required=True, type=Path)
    parser.add_argument("--full-info", required=True, type=Path)
    parser.add_argument("--output-path", required=True, type=Path)
    parser.add_argument("--dimension", required=True)
    parser.add_argument("--resolution", default="16-9")
    parser.add_argument("--custom-image-folder", type=Path)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use locally prepared I2V checkpoints and repositories.",
    )
    args = parser.parse_args()
    from vbench2_beta_i2v import VBenchI2V

    args.output_path.mkdir(parents=True, exist_ok=True)
    evaluator = VBenchI2V(args.device, str(args.full_info), str(args.output_path))
    evaluator.evaluate(
        videos_path=str(args.videos_path), name=args.dimension,
        dimension_list=[args.dimension],
        custom_image_folder=str(args.custom_image_folder) if args.custom_image_folder else None,
        resolution=args.resolution,
        local=args.local,
        mode="custom_input" if args.custom_image_folder else "vbench_standard",
    )


if __name__ == "__main__":
    main()
