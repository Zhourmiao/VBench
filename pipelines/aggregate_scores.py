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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    evaluation_root = args.run_dir.resolve() / "evaluation"
    scores: dict[str, float] = {}
    for path in sorted(evaluation_root.glob("**/*_eval_results.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for dimension, value in data.items():
                score = scalar(value)
                if score is not None:
                    scores[dimension] = score

    groups = {
        "creativity": ["Composition", "Diversity"],
        "commonsense": ["Instance Preservation", "Motion Rationality"],
        "controllability": ["Camera Motion", "Complex Landscape", "Complex Plot", "Dynamic Attribute", "Dynamic Spatial Relationship", "Human Interaction", "Motion Order Understanding"],
        "human_fidelity": ["Human Anatomy", "Human Clothes", "Human Identity"],
        "physics": ["Material", "Mechanics", "Multi-View Consistency", "Thermotics"],
    }
    mean = lambda values: sum(values) / len(values) if values else None
    group_scores = {name: mean([scores[key] for key in keys if key in scores]) for name, keys in groups.items()}
    complete = [value for value in group_scores.values() if value is not None]
    report = {
        "dimension_scores": scores,
        "available_dimension_mean": mean(list(scores.values())),
        "dimension_count": len(scores),
        "group_scores": group_scores,
        "official_vbench2_mean": mean(complete) if len(complete) == len(groups) else None,
    }
    output = args.run_dir.resolve() / "summary/dimension_scores.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
