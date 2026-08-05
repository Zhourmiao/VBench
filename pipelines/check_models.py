#!/usr/bin/env python3
"""Check local VBench model files and Python dependencies without downloading anything."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


T2V_PROFILES: dict[str, list[dict[str, Any]]] = {
    "llava": [
        {"name": "LLaVA-Video-7B-Qwen2", "kind": "dir", "path": "lmms-lab/LLaVA-Video-7B-Qwen2"},
        {"name": "SigLIP vision tower HF cache", "kind": "glob", "path": "hub/models--google--siglip-so400m-patch14-384/snapshots/*/config.json"},
        {"name": "llava Python package", "kind": "module", "module": "llava"},
    ],
    "qwen": [
        {"name": "Qwen2.5-7B-Instruct", "kind": "dir", "path": "Qwen/Qwen2.5-7B-Instruct"},
        {"name": "transformers Python package", "kind": "module", "module": "transformers"},
    ],
    "arcface": [
        {"name": "ArcFace checkpoint", "kind": "file", "path": "arcface/resnet18_110.pth", "min_bytes": 1024},
        {"name": "RetinaFace checkpoint", "kind": "file", "path": "torch/checkpoints/retinaface_resnet50_2020-07-20-f168fae3c.zip", "min_bytes": 1024},
        {"name": "retinaface Python package", "kind": "module", "module": "retinaface"},
    ],
    "multi_view": [
        {"name": "CoTracker2 checkpoint", "kind": "file", "path": "torch/hub/checkpoints/cotracker2.pth", "min_bytes": 1024},
        {"name": "RAFT checkpoint", "kind": "file", "path": "raft_model/models/raft-things.pth", "min_bytes": 1024},
        {"name": "torch Python package", "kind": "module", "module": "torch"},
    ],
}

I2V_PROFILES: dict[str, list[dict[str, Any]]] = {
    "dino": [
        {"name": "DINO repository", "kind": "dir", "path": "dino_model/facebookresearch_dino_main"},
        {"name": "DINO ViT-B/16 checkpoint", "kind": "file", "path": "dino_model/dino_vitbase16_pretrain.pth", "min_bytes": 1024},
    ],
    "dreamsim": [
        {"name": "DreamSim checkpoints", "kind": "dir_nonempty", "path": "dreamsim_ckpts"},
        {"name": "torch Python package", "kind": "module", "module": "torch"},
    ],
    "clip_b": [
        {"name": "CLIP ViT-B/32 checkpoint", "kind": "file", "path": "clip_model/ViT-B-32.pt", "min_bytes": 1024},
    ],
    "clip_l_aesthetic": [
        {"name": "CLIP ViT-L/14 checkpoint", "kind": "file", "path": "clip_model/ViT-L-14.pt", "min_bytes": 1024},
        {"name": "aesthetic predictor", "kind": "dir_nonempty", "path": "aesthetic_model/emb_reader"},
    ],
    "musiq": [
        {"name": "MUSIQ-SPAQ checkpoint", "kind": "file", "path": "pyiqa_model/musiq_spaq_ckpt-358bb6af.pth", "min_bytes": 1024},
        {"name": "pyiqa Python package", "kind": "module", "module": "pyiqa"},
        {"name": "timm Python package", "kind": "module", "module": "timm"},
    ],
    "amt": [
        {"name": "AMT-S checkpoint", "kind": "file", "path": "amt_model/amt-s.pth", "min_bytes": 1024},
        {"name": "AMT config", "kind": "repo_file", "path": "source/vbench/third_party/amt/cfgs/AMT-S.yaml"},
    ],
    "raft": [
        {"name": "RAFT checkpoint", "kind": "file", "path": "raft_model/models/raft-things.pth", "min_bytes": 1024},
        {"name": "torch Python package", "kind": "module", "module": "torch"},
    ],
}


T2V_DIMENSIONS = {
    "Motion_Rationality": ("llava",),
    "Mechanics": ("llava",),
    "Human_Clothes": ("llava",),
    "Composition": ("llava",),
    "Dynamic_Spatial_Relationship": ("llava",),
    "Dynamic_Attribute": ("llava",),
    "Thermotics": ("llava",),
    "Material": ("llava",),
    "Motion_Order_Understanding": ("llava", "qwen"),
    "Human_Interaction": ("llava", "qwen"),
    "Complex_Landscape": ("llava", "qwen"),
    "Complex_Plot": ("llava", "qwen"),
    "Human_Identity": ("arcface",),
    "Multi-View_Consistency": ("multi_view",),
    "Camera_Motion": ("multi_view",),
    "Instance_Preservation": (),
    # These dimensions reuse the original VBench video-only implementations.
    "subject_consistency": ("dino",),
    "background_consistency": ("clip_b",),
    "aesthetic_quality": ("clip_l_aesthetic",),
    "imaging_quality": ("musiq",),
    "temporal_flickering": (),
    "motion_smoothness": ("amt",),
    "dynamic_degree": ("raft",),
}

VIDEO_ONLY_DIMENSIONS = {
    "subject_consistency",
    "background_consistency",
    "aesthetic_quality",
    "imaging_quality",
    "temporal_flickering",
    "motion_smoothness",
    "dynamic_degree",
}

I2V_DIMENSIONS = {
    "i2v_subject": ("dino",),
    "subject_consistency": ("dino",),
    "i2v_background": ("dreamsim",),
    "background_consistency": ("clip_b",),
    "aesthetic_quality": ("clip_l_aesthetic",),
    "imaging_quality": ("musiq",),
    "motion_smoothness": ("amt",),
    "dynamic_degree": ("raft",),
    "camera_motion": ("multi_view",),
    "temporal_flickering": (),
}


def load_config(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "config" / "run.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("读取 run.yaml 需要 PyYAML，或请使用 --benchmark 和 --dimensions") from exc
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def check_item(item: dict[str, Any], root: Path, repo_root: Path) -> dict[str, Any]:
    kind = item["kind"]
    if kind == "module":
        found = importlib.util.find_spec(item["module"]) is not None
        path = item["module"]
        detail = "importable" if found else "module_not_found"
    else:
        base = repo_root if kind == "repo_file" else root
        path = base / item["path"]
        if kind == "glob":
            matches = sorted(base.glob(item["path"]))
            found = any(match.is_file() and match.stat().st_size > 0 for match in matches)
            detail = f"{len(matches)} matches"
        elif kind == "dir_nonempty":
            found = path.is_dir() and any(path.iterdir())
            detail = "nonempty" if found else "empty_or_missing"
        elif kind == "dir":
            found = path.is_dir() and any(path.iterdir())
            detail = "nonempty" if found else "empty_or_missing"
        else:
            min_bytes = int(item.get("min_bytes", 1))
            found = path.is_file() and path.stat().st_size >= min_bytes
            detail = f"{path.stat().st_size} bytes" if path.is_file() else "missing"
        path = str(path)
    return {"name": item["name"], "path": path, "status": "ok" if found else "missing", "detail": detail}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="读取 config/run.yaml 的 run 目录")
    parser.add_argument("--benchmark", choices=("vbench2", "vbench_i2v"))
    parser.add_argument("--dimensions", nargs="+", help="只检查指定维度；默认读取 run.yaml")
    parser.add_argument("--t2v-cache", type=Path, help="覆盖 T2V 缓存目录")
    parser.add_argument("--i2v-cache", type=Path, help="覆盖 I2V 缓存目录")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.run_dir and not args.benchmark:
        parser.error("请提供 --run-dir 或 --benchmark")

    run_dir = args.run_dir.resolve() if args.run_dir else Path.cwd()
    config = load_config(run_dir) if args.run_dir else {}
    benchmark = args.benchmark or config.get("benchmark")
    if benchmark not in ("vbench2", "vbench_i2v"):
        raise ValueError("benchmark 必须是 vbench2 或 vbench_i2v")
    dimensions = list(args.dimensions or config.get("dimensions") or [])
    if benchmark == "vbench2":
        dimensions.extend(
            dimension for dimension in config.get("video_only_dimensions", VIDEO_ONLY_DIMENSIONS)
            if dimension not in dimensions
        )
    if not dimensions:
        raise ValueError("请通过 --dimensions 指定要检查的维度")
    profiles = T2V_DIMENSIONS if benchmark == "vbench2" else I2V_DIMENSIONS
    unknown = [dimension for dimension in dimensions if dimension not in profiles]
    if unknown:
        raise ValueError(f"没有模型检查配置的维度: {', '.join(unknown)}")

    cache = (args.t2v_cache if benchmark == "vbench2" else args.i2v_cache)
    if cache is None:
        env_name = "VBENCH2_CACHE_DIR" if benchmark == "vbench2" else "VBENCH_CACHE_DIR"
        cache = Path(os.environ.get(env_name, "/root/.cache/vbench2" if benchmark == "vbench2" else "/root/.cache/vbench"))
    cache = cache.expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if benchmark == "vbench2":
        # The T2V model loader resolves this HF model from HF_HOME's cache.
        hf_home = Path(os.environ.get("HF_HOME", str(cache / "huggingface"))).expanduser()
        if not hf_home.is_absolute():
            hf_home = cache / hf_home
        root = cache
    else:
        hf_home = None
        root = cache

    records = []
    for dimension in dimensions:
        # Video-only dimensions are implemented by the original VBench
        # package and store their weights under the I2V/VBench cache root,
        # even when they are dispatched from a T2V run.
        if benchmark == "vbench2" and dimension in VIDEO_ONLY_DIMENSIONS:
            dimension_profiles = I2V_PROFILES
            dimension_root = Path(os.environ.get("VBENCH_CACHE_DIR", str(cache.parent / "vbench"))).expanduser().resolve()
        else:
            dimension_profiles = T2V_PROFILES if benchmark == "vbench2" else I2V_PROFILES
            dimension_root = root
        for profile_name in profiles[dimension]:
            for item in dimension_profiles[profile_name]:
                # SigLIP is stored in the Hugging Face cache, not beside VBench files.
                item_root = hf_home if item["kind"] == "glob" and hf_home else dimension_root
                records.append({"dimension": dimension, "profile": profile_name, **check_item(item, item_root, repo_root)})

    missing = [record for record in records if record["status"] != "ok"]
    report = {
        "report_version": 1,
        "run_id": run_dir.name if args.run_dir else None,
        "benchmark": benchmark,
        "dimensions": dimensions,
        "cache_dir": str(cache),
        "offline": os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checks": len(records),
        "passed_checks": len(records) - len(missing),
        "missing_checks": len(missing),
        "checks": records,
    }
    report_path = (args.report or run_dir / "evaluation" / "model_preflight_report.json").resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"模型预检查：通过 {report['passed_checks']}/{report['total_checks']}，缺失 {report['missing_checks']}")
    print(f"缓存目录：{cache}")
    print(f"报告：{report_path}")
    for record in missing:
        print(f"缺失：[{record['dimension']}] {record['name']} -> {record['path']}")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
