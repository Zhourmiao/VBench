#!/usr/bin/env python3
"""Aggregate scalar dimension scores from a run's evaluation outputs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def scalar(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, (list, tuple)) and value:
        return scalar(value[0])
    if isinstance(value, dict):
        for key in ("score", "all_results", "overall_score", "mean"):
            if key in value:
                found = scalar(value[key])
                if found is not None:
                    return found
    return None


def load_result_json(path: Path) -> Any:
    """Load one evaluator result and report the exact broken file on failure."""
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        lines = text.splitlines()
        line = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ""
        pointer = " " * max(exc.colno - 1, 0) + "^"
        raise ValueError(
            f"评测结果不是合法 JSON：{path}\n"
            f"第 {exc.lineno} 行，第 {exc.colno} 列：{line}\n"
            f"{pointer}\n"
            "请修复或重新生成该维度的 *_eval_results.json 后再汇总。"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    evaluation_root = args.run_dir.resolve() / "evaluation"
    scores: dict[str, float] = {}
    for path in sorted(evaluation_root.glob("**/*_eval_results.json")):
        data = load_result_json(path)
        if isinstance(data, dict):
            for dimension, value in data.items():
                score = scalar(value)
                if score is not None:
                    scores[dimension] = score

    # Keep the official VBench-2.0 dimension spellings. The evaluator uses
    # underscores in names such as ``Motion_Rationality`` and
    # ``Multi-View_Consistency``; using spaces here made most groups null.
    groups = {
        "creativity": ["Composition", "Diversity"],
        "commonsense": ["Instance_Preservation", "Motion_Rationality"],
        "controllability": [
            "Camera_Motion",
            "Complex_Landscape",
            "Complex_Plot",
            "Dynamic_Attribute",
            "Dynamic_Spatial_Relationship",
            "Human_Interaction",
            "Motion_Order_Understanding",
        ],
        "human_fidelity": ["Human_Anatomy", "Human_Clothes", "Human_Identity"],
        "physics": ["Material", "Mechanics", "Multi-View_Consistency", "Thermotics"],
    }
    video_only_dimensions = {
        "subject_consistency",
        "background_consistency",
        "aesthetic_quality",
        "imaging_quality",
        "temporal_flickering",
        "motion_smoothness",
        "dynamic_degree",
    }
    mean = lambda values: sum(values) / len(values) if values else None
    group_scores = {name: mean([scores[key] for key in keys if key in scores]) for name, keys in groups.items()}
    complete = [value for value in group_scores.values() if value is not None]
    vbench2_scores = {
        dimension: score
        for dimension, score in scores.items()
        if any(dimension in dimensions for dimensions in groups.values())
    }
    video_only_scores = {
        dimension: score
        for dimension, score in scores.items()
        if dimension in video_only_dimensions
    }
    report = {
        "dimension_scores": scores,
        "available_dimension_mean": mean(list(scores.values())),
        "dimension_count": len(scores),
        "vbench2_dimension_scores": vbench2_scores,
        "vbench2_available_dimension_mean": mean(list(vbench2_scores.values())),
        "video_only_scores": video_only_scores,
        "video_only_mean": mean(list(video_only_scores.values())),
        "group_scores": group_scores,
        "official_vbench2_mean": mean(complete) if len(complete) == len(groups) else None,
    }
    output = args.run_dir.resolve() / "summary/dimension_scores.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
