#!/usr/bin/env python3
"""Build VBench-2.0 T2V cases and a reduced standard-evaluation metadata file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_DIMENSIONS = [
    "Human_Anatomy",
    "Human_Identity",
    "Composition",
    "Human_Interaction",
    "Dynamic_Spatial_Relationship",
    "Complex_Landscape",
    "Mechanics",
    "Motion_Order_Understanding",
    "Motion_Rationality",
    "Multi-View_Consistency",
    "Complex_Plot",
]
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_ROOT = REPO_ROOT / "benchmarks/vbench2_t2v"


def nonempty_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_info(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [{"prompt_en": key, **value} for key, value in raw.items()]
    raise ValueError(f"不支持的 full_info 格式: {path}")


def load_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"benchmark manifest 必须是 JSON 对象: {path}")
    supported = raw.get("supported_dimensions")
    if not isinstance(supported, list) or not all(isinstance(item, str) for item in supported):
        raise ValueError(f"manifest 缺少有效的 supported_dimensions: {path}")
    return raw


def build_cases(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prompt_root = args.prompt_root.resolve()
    chinese_root = args.chinese_root.resolve()
    info = load_info(args.full_info.resolve())
    dimensions = args.dimensions or DEFAULT_DIMENSIONS
    cases: list[dict[str, Any]] = []
    eval_items: list[dict[str, Any]] = []
    case_number = 1

    for dimension in dimensions:
        selected = nonempty_lines(args.selected_root / f"{dimension}.txt")
        all_chinese = nonempty_lines(chinese_root / f"{dimension}.txt")
        all_english = nonempty_lines(prompt_root / f"{dimension}.txt")
        if len(all_chinese) != len(all_english):
            raise ValueError(f"{dimension}: 中英文 prompt 数量不一致")
        count = args.diversity_samples_per_prompt if dimension == "Diversity" else args.samples_per_prompt
        seen: set[str] = set()
        for display_prompt in selected:
            if display_prompt not in all_chinese:
                raise ValueError(f"{dimension}: selected prompt 不在官方中文 prompt 中: {display_prompt}")
            index = all_chinese.index(display_prompt)
            prompt_en = all_english[index]
            if prompt_en in seen:
                raise ValueError(f"{dimension}: prompt 重复: {prompt_en}")
            seen.add(prompt_en)
            info_item = next(
                (item for item in info if item.get("prompt_en") == prompt_en and dimension in item.get("dimension", [])),
                None,
            )
            if info_item is None:
                raise ValueError(f"找不到 full_info 对应英文 prompt: {prompt_en}")
            video_paths: list[str] = []
            for sample_index in range(count):
                seed = args.seed_base + case_number
                case_id = f"t2v-{case_number:04d}"
                case = {
                    "case_id": case_id,
                    "dimension": [dimension],
                    "prompt_input": args.input_language == "en" and prompt_en or display_prompt,
                    "prompt_eval_en": prompt_en,
                    "prompt_display": display_prompt,
                    "sample_index": sample_index,
                    "seed": seed,
                    "duration": args.duration,
                    "fps": args.fps,
                    "num_frames": args.num_frames or args.duration * args.fps,
                    "width": args.width,
                    "height": args.height,
                }
                cases.append(case)
                filename = f"{prompt_en[:180]}-{sample_index}.mp4"
                video_paths.append(str(Path(args.video_root) / dimension / filename))
                case_number += 1
            eval_item = dict(info_item)
            eval_item["video_list"] = video_paths
            eval_items.append(eval_item)
    return cases, eval_items


def case_key(case: dict[str, Any]) -> tuple[str, str, int]:
    dimensions = case.get("dimension")
    prompt = case.get("prompt_eval_en")
    sample_index = case.get("sample_index")
    if not isinstance(dimensions, list) or not dimensions or not isinstance(dimensions[0], str):
        raise ValueError(f"case 缺少有效 dimension: {case}")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError(f"case 缺少有效 prompt_eval_en: {case}")
    if not isinstance(sample_index, int):
        raise ValueError(f"case 缺少有效 sample_index: {case}")
    return dimensions[0], prompt, sample_index


def merge_cases_for_append(
    existing_path: Path,
    generated_cases: list[dict[str, Any]],
    seed_base: int,
) -> tuple[list[dict[str, Any]], int]:
    """Preserve existing case IDs and append only new dimension/prompt/sample keys."""
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    if not isinstance(existing, list):
        raise ValueError(f"已有 cases.json 必须是数组: {existing_path}")

    by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    max_case_number = 0
    for case in existing:
        key = case_key(case)
        if key in by_key:
            raise ValueError(f"已有 cases.json 存在重复 case: {key}")
        by_key[key] = case
        match = re.fullmatch(r"t2v-(\d+)", str(case.get("case_id", "")))
        if match:
            max_case_number = max(max_case_number, int(match.group(1)))

    merged = list(existing)
    added = 0
    for case in generated_cases:
        key = case_key(case)
        if key in by_key:
            continue
        max_case_number += 1
        new_case = dict(case)
        new_case["case_id"] = f"t2v-{max_case_number:04d}"
        new_case["seed"] = seed_base + max_case_number
        merged.append(new_case)
        by_key[key] = new_case
        added += 1
    return merged, added


def update_run_config_dimensions(config_path: Path, dimensions: list[str]) -> None:
    """Update only the top-level dimensions list of an existing YAML config."""
    if not config_path.exists():
        return
    lines = config_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "dimensions:":
            continue
        end = index + 1
        while end < len(lines) and re.match(r"^\s+-\s+", lines[end]):
            end += 1
        replacement = ["dimensions:", *[f"  - {dimension}" for dimension in dimensions]]
        lines[index:end] = replacement
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return


def write_run_config(output_dir: Path, dimensions: list[str]) -> Path:
    """Create the minimal T2V dispatcher config once per run."""
    run_dir = output_dir.resolve().parent
    config_path = run_dir / "config" / "run.yaml"
    if config_path.exists():
        return config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"run_id: {run_dir.name}",
        "benchmark: vbench2",
        "dataset: vbench2_t2v",
        "workflow: configurable_comfyui_t2v",
        "videos_root: videos/prepared",
        "full_info: cases/selected_full_info.json",
        "evaluation_root: evaluation",
        "dimensions:",
    ]
    lines.extend(f"  - {dimension}" for dimension in dimensions)
    lines.extend([
        "video_only_dimensions:",
        "  - subject_consistency",
        "  - background_consistency",
        "  - aesthetic_quality",
        "  - imaging_quality",
        "  - temporal_flickering",
        "  - motion_smoothness",
        "  - dynamic_degree",
        "video_only_videos_path: videos/prepared",
        "mode: vbench_standard",
        "load_ckpt_from_local: true",
        "read_frame: false",
        "stop_on_error: false",
        "",
    ])
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def parse_args() -> argparse.Namespace:
    benchmark_root = DEFAULT_BENCHMARK_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-root", type=Path, default=benchmark_root / "prompts/selected_7x5")
    parser.add_argument("--prompt-root", type=Path, default=benchmark_root / "prompts/prompt")
    parser.add_argument("--chinese-root", type=Path, default=benchmark_root / "prompts/prompt_ch/VBench2_ch_prompt")
    parser.add_argument("--full-info", type=Path, default=benchmark_root / "full_info.json")
    parser.add_argument("--manifest", type=Path, default=benchmark_root / "manifest.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--append",
        action="store_true",
        help="保留已有 cases 的 case_id，只追加新的维度/prompt/sample",
    )
    parser.add_argument("--video-root", type=Path, default=Path("videos"))
    parser.add_argument("--dimensions", nargs="+")
    parser.add_argument("--all-dimensions", action="store_true", help="使用 manifest 中的全部官方维度")
    parser.add_argument("--samples-per-prompt", type=int)
    parser.add_argument("--diversity-samples-per-prompt", type=int)
    parser.add_argument("--seed-base", type=int, default=2100000)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--num-frames", type=int)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--input-language", choices=["zh", "en"], default="zh")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.selected_root = args.selected_root.resolve()
    args.prompt_root = args.prompt_root.resolve()
    args.chinese_root = args.chinese_root.resolve()
    args.full_info = args.full_info.resolve()
    args.manifest = args.manifest.resolve()
    manifest = load_manifest(args.manifest)
    supported_dimensions = manifest["supported_dimensions"]
    if args.all_dimensions:
        if args.dimensions:
            raise ValueError("--all-dimensions 不能与 --dimensions 同时使用")
        args.dimensions = supported_dimensions
        args.selected_root = args.chinese_root
    selected_dimensions = args.dimensions or DEFAULT_DIMENSIONS
    unknown_dimensions = sorted(set(selected_dimensions) - set(supported_dimensions))
    if unknown_dimensions:
        raise ValueError(f"维度不在 benchmark manifest 中: {unknown_dimensions}")
    args.dimensions = selected_dimensions
    if args.samples_per_prompt is None:
        args.samples_per_prompt = int(manifest.get("samples_per_prompt", 3))
    if args.diversity_samples_per_prompt is None:
        args.diversity_samples_per_prompt = int(manifest.get("diversity_samples_per_prompt", 20))
    if args.samples_per_prompt < 1:
        raise ValueError("--samples-per-prompt 必须大于 0")
    if args.diversity_samples_per_prompt < 1:
        raise ValueError("--diversity-samples-per-prompt 必须大于 0")
    if args.duration <= 0 or args.fps <= 0 or args.width <= 0 or args.height <= 0:
        raise ValueError("视频参数必须为正数")
    cases, eval_items = build_cases(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = args.output_dir / "cases.json"
    if args.append:
        if not cases_path.is_file():
            raise FileNotFoundError(f"--append 要求已有 cases.json: {cases_path}")
        cases, added = merge_cases_for_append(cases_path, cases, args.seed_base)
    else:
        added = len(cases)
    cases_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "selected_full_info.json").write_text(json.dumps(eval_items, ensure_ascii=False, indent=2), encoding="utf-8")
    config_path = write_run_config(args.output_dir, args.dimensions)
    if args.append:
        update_run_config_dimensions(config_path, args.dimensions)
        print(f"已保留 {len(cases) - added} 个旧 cases，追加 {added} 个新 cases")
    else:
        print(f"已生成 {len(cases)} 个 cases、{len(eval_items)} 个 prompt metadata")
    print(f"运行配置：{config_path}")


if __name__ == "__main__":
    main()
