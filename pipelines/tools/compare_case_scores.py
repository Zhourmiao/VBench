#!/usr/bin/env python3
"""Compare per-case VBench scores between two model runs.

The script compares cases with the same benchmark identity in ``case.json``.
It reads VBench ``*_eval_results.json`` files and writes the cases where model
A scores higher than model B, together with a self-contained HTML report.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import shutil
from urllib.parse import unquote
from pathlib import Path
from typing import Any


SCORE_KEYS = (
    "video_results",
    "score",
    "value",
    "all_results",
    "video_sim",
    "cur_sim",
    "cur_success_frame_rate",
    "success_frame_rate",
    "cor_num_per_video",
)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：{path}（第 {exc.lineno} 行）") from exc


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, (list, tuple)):
        numbers = [finite_float(item) for item in value]
        numbers = [number for number in numbers if number is not None]
        return sum(numbers) / len(numbers) if numbers else None
    if isinstance(value, dict):
        for key in SCORE_KEYS:
            if key in value:
                score = finite_float(value[key])
                if score is not None:
                    return score
    return None


def case_fingerprint(case: dict[str, Any]) -> str:
    raw = json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


CASE_IDENTITY_FIELDS = (
    "case_id",
    "dimension",
    "prompt_input",
    "prompt_eval_en",
    "prompt_display",
    "prompt_text",
    "file_stem",
    "sample_index",
    "seed",
    "image",
)


def case_identity_fingerprint(case: dict[str, Any]) -> str:
    """Fingerprint the benchmark identity, excluding output/render settings."""
    identity = {key: case.get(key) for key in CASE_IDENTITY_FIELDS if key in case}
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def find_case_files(run_dir: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.rglob("case.json")):
        data = load_json(path)
        if not isinstance(data, dict) or not data.get("case_id"):
            continue
        case_id = str(data["case_id"])
        entry = {
            "case_id": case_id,
            "fingerprint": case_fingerprint(data),
            "identity_fingerprint": case_identity_fingerprint(data),
            "case": data,
            "case_path": str(path.resolve()),
        }
        # Prefer a generation/case.json over an unrelated copied metadata file.
        cases.setdefault(case_id, entry)
        if "generation" in str(path.parent):
            cases[case_id] = entry
    return cases


def score_from_detail(detail: dict[str, Any]) -> float | None:
    for key in SCORE_KEYS:
        score = finite_float(detail.get(key))
        if score is not None:
            return score
    return None


def iter_score_details(value: Any) -> list[dict[str, Any]]:
    """Find per-video dictionaries even when a result has extra nesting."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("video_path"), str):
            found.append(value)
        for child in value.values():
            found.extend(iter_score_details(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(iter_score_details(child))
    return found


def normalize_text(value: str) -> str:
    return " ".join(unquote(value).strip().split())


def build_video_lookup(cases: dict[str, dict[str, Any]]) -> dict[tuple[str, int], str]:
    """Map evaluator filenames (prompt-0.mp4) back to generated case IDs."""
    lookup: dict[tuple[str, int], str] = {}
    for case_id, entry in cases.items():
        case = entry["case"]
        sample_index = case.get("sample_index")
        if not isinstance(sample_index, int):
            continue
        for field in ("prompt_eval_en", "prompt_input", "prompt_display", "file_stem"):
            value = case.get(field)
            if isinstance(value, str) and value.strip():
                lookup[(normalize_text(value), sample_index)] = case_id
    return lookup


def case_id_from_video_path(
    video_path: str, known_ids: set[str], video_lookup: dict[tuple[str, int], str]
) -> str | None:
    name = Path(video_path).stem
    if name in known_ids:
        return name
    match = re.match(r"^(.*)-(\d+)$", name)
    if match:
        prompt, sample_index = match.groups()
        found = video_lookup.get((normalize_text(prompt), int(sample_index)))
        if found is not None:
            return found
    # Handles paths such as .../t2v-0001-0.mp4 and names with URL escaping.
    candidates = sorted(known_ids, key=len, reverse=True)
    for case_id in candidates:
        if re.search(rf"(?:^|[-_/]){re.escape(case_id)}(?:[-_/]|$)", video_path):
            return case_id
    return None


def read_scores(
    run_dir: Path,
    cases: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = {}
    known_ids = set(cases)
    video_lookup = build_video_lookup(cases)
    seen_video_details = 0
    recognized_scores = 0
    skipped_invalid_scores = 0
    evaluation_dir = run_dir / "evaluation"
    files = sorted(evaluation_dir.glob("**/*_eval_results.json"))
    if not files:
        raise FileNotFoundError(f"没有找到逐样例评测结果：{evaluation_dir}/**/*_eval_results.json")

    for path in files:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        for dimension, result in data.items():
            for detail in iter_score_details(result):
                seen_video_details += 1
                case_id = case_id_from_video_path(detail["video_path"], known_ids, video_lookup)
                score = score_from_detail(detail)
                if score is not None and score < 0:
                    skipped_invalid_scores += 1
                    continue
                if case_id is None or score is None:
                    continue
                recognized_scores += 1
                key = (case_id, str(dimension))
                if key in scores and abs(scores[key] - score) > 1e-12:
                    raise ValueError(f"同一 case/维度出现多个分数：{path} -> {key}")
                scores[key] = score
    if not scores:
        print(
            f"警告：{run_dir} 找到 {len(files)} 个评测文件，"
            f"发现 {seen_video_details} 条逐视频记录，但没有解析出可用分数；"
            f"跳过无效分数 {skipped_invalid_scores} 条。"
        )
    elif recognized_scores < seen_video_details:
        print(
            f"提示：{run_dir} 发现 {seen_video_details} 条逐视频记录，"
            f"成功解析 {recognized_scores} 条分数，跳过无效分数 {skipped_invalid_scores} 条。"
        )
    return scores


def build_rows(
    a_cases: dict[str, dict[str, Any]],
    b_cases: dict[str, dict[str, Any]],
    a_scores: dict[tuple[str, str], float],
    b_scores: dict[tuple[str, str], float],
    min_relative_difference: float,
    score_scale: str = "auto",
    strict_case_json: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    stats = {"same_case": 0, "matched_scores": 0, "a_wins": 0}
    for case_id in sorted(set(a_cases) & set(b_cases)):
        fingerprint_key = "fingerprint" if strict_case_json else "identity_fingerprint"
        if a_cases[case_id][fingerprint_key] != b_cases[case_id][fingerprint_key]:
            continue
        stats["same_case"] += 1
        dimensions = sorted(
            {dimension for cid, dimension in a_scores if cid == case_id}
            & {dimension for cid, dimension in b_scores if cid == case_id}
        )
        for dimension in dimensions:
            a_score = a_scores[(case_id, dimension)]
            b_score = b_scores[(case_id, dimension)]
            diff = a_score - b_score
            if score_scale == "auto":
                scale = 100.0 if max(a_score, b_score) > 1.5 else 1.0
            else:
                scale = float(score_scale)
            relative_diff = diff / scale
            stats["matched_scores"] += 1
            if relative_diff <= min_relative_difference:
                continue
            case = a_cases[case_id]["case"]
            rows.append({
                "case_id": case_id,
                "dimension": dimension,
                "model_a_score": a_score,
                "model_b_score": b_score,
                "difference": diff,
                "relative_difference": relative_diff,
                "score_scale": scale,
                "prompt": case.get("prompt_eval_en") or case.get("prompt_input") or case.get("prompt_text", ""),
                "case_json": a_cases[case_id]["case_path"],
            })
            stats["a_wins"] += 1
    rows.sort(key=lambda row: row["difference"], reverse=True)
    return rows, stats


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value.strip("._") or "item"


def find_case_video(run_dir: Path, case_id: str) -> Path | None:
    exact = sorted(run_dir.rglob(f"{case_id}.mp4"))
    if exact:
        return exact[0]
    for directory in sorted(run_dir.rglob(case_id)):
        if directory.is_dir():
            videos = sorted(directory.glob("*.mp4"))
            if videos:
                return videos[0]
    return None


def collect_visual_videos(
    output_dir: Path,
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    video_dir = output_dir / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        stem = f"{safe_filename(row['case_id'])}__{safe_filename(row['dimension'])}"
        for key, model_name, run_dir in (
            ("model_a_video", args.model_a_name, args.model_a_run),
            ("model_b_video", args.model_b_name, args.model_b_run),
        ):
            source = find_case_video(run_dir.resolve(), row["case_id"])
            if source is None:
                row[key] = None
                continue
            target = video_dir / f"{stem}__{safe_filename(model_name)}.mp4"
            shutil.copy2(source, target)
            row[key] = str(target.relative_to(output_dir))


def write_outputs(output_dir: Path, rows: list[dict[str, Any]], stats: dict[str, int], args: argparse.Namespace) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    collect_visual_videos(output_dir, rows, args)
    payload = {
        "model_a": args.model_a_name,
        "model_b": args.model_b_name,
        "min_relative_difference": args.min_relative_difference,
        "score_scale": args.score_scale,
        "stats": stats,
        "winners": rows,
    }
    (output_dir / "comparison.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as file:
        fields = [
            "case_id", "dimension", "model_a_score", "model_b_score", "difference",
            "relative_difference", "score_scale", "prompt", "case_json",
            "model_a_video", "model_b_video",
        ]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    chart_rows = rows
    chart_data = json.dumps(chart_rows, ensure_ascii=False).replace("</", "<\\/")
    title = f"{args.model_a_name} > {args.model_b_name}"
    labels = json.dumps({"a": args.model_a_name, "b": args.model_b_name}, ensure_ascii=False)
    page = f'''<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1100px;margin:28px auto;padding:0 18px;color:#202124}}
h1{{font-size:22px;font-weight:600}} .meta{{color:#666;margin-bottom:22px}}
.row{{display:grid;grid-template-columns:minmax(180px,2fr) 90px 90px minmax(220px,3fr);gap:12px;align-items:center;border-bottom:1px solid #eee;padding:10px 0}}
.label{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}} .case{{font-weight:600}} .prompt{{font-size:12px;color:#666;margin-top:3px}}
.bars{{position:relative;height:28px;background:#f3f4f6;border-radius:5px;overflow:hidden}} .bar{{height:50%;min-width:2px}}
.a{{background:#2563eb}} .b{{background:#f59e0b}} .num{{font-variant-numeric:tabular-nums;text-align:right}} .diff{{color:#15803d;font-weight:600}}
.head{{font-size:12px;color:#666;border-bottom:2px solid #ddd;padding-bottom:7px}} @media(max-width:700px){{.row{{grid-template-columns:1fr 70px 70px;gap:8px}}.bars{{grid-column:1/-1}}.head{{display:none}}}}
.video-row{{border-top:1px solid #ddd;margin-top:24px;padding-top:16px}} .video-row h3{{font-size:16px;margin:0 0 5px}} .video-row h3 span{{color:#15803d;font-size:13px}} .video-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:10px}} .video-label{{font-weight:600;margin-bottom:5px}} video{{width:100%;max-height:360px;background:#111;border-radius:6px}} @media(max-width:700px){{.video-grid{{grid-template-columns:1fr}}}}
</style>
<h1>{html.escape(title)}</h1>
<div class="meta">仅显示相同样例且 A 高于 B 超过满分 10% 的结果；共 {len(rows)} 条，分数图最多显示 {min(len(rows), args.max_chart_rows)} 条，视频对比显示全部结果。</div>
<div class="row head"><div>样例 / 维度</div><div>A</div><div>B</div><div>分数对比（同一刻度）</div></div>
<div id="chart"></div>
<script>
const rows={chart_data}; const names={labels}; const chart=document.getElementById('chart');
const chartRows=rows.slice(0,{args.max_chart_rows});
const max=Math.max(1,...chartRows.flatMap(r=>[r.model_a_score,r.model_b_score]));
const videoList=document.createElement('div');
for(const r of chartRows){{const item=document.createElement('div'); item.className='row';
item.innerHTML='<div class="label"><div class="case">'+escapeHtml(r.case_id)+' · '+escapeHtml(r.dimension)+'</div><div class="prompt">'+escapeHtml(r.prompt||'')+'</div></div>'+ 
'<div class="num">'+r.model_a_score.toFixed(4)+'</div><div class="num">'+r.model_b_score.toFixed(4)+'</div>'+ 
'<div class="bars" title="'+escapeHtml(names.a)+' vs '+escapeHtml(names.b)+'"><div class="bar a" style="width:'+100*r.model_a_score/max+'%"></div><div class="bar b" style="width:'+100*r.model_b_score/max+'%"></div></div>';
chart.appendChild(item);
const videoItem=document.createElement('section'); videoItem.className='video-row';
videoItem.innerHTML='<h3>'+escapeHtml(r.case_id)+' · '+escapeHtml(r.dimension)+' <span>差值 +'+r.difference.toFixed(4)+'（'+(100*r.relative_difference).toFixed(1)+'%）</span></h3>'+
'<div class="prompt">'+escapeHtml(r.prompt||'')+'</div><div class="video-grid">'+
(r.model_a_video?'<div><div class="video-label">'+escapeHtml(names.a)+'</div><video controls preload="metadata" src="'+encodeURI(r.model_a_video)+'"></video></div>':'')+
(r.model_b_video?'<div><div class="video-label">'+escapeHtml(names.b)+'</div><video controls preload="metadata" src="'+encodeURI(r.model_b_video)+'"></video></div>':'')+
'</div>';
videoList.appendChild(videoItem)}}
chart.appendChild(videoList);
function escapeHtml(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
</script>
'''
    (output_dir / "comparison.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-a-run", required=True, type=Path)
    parser.add_argument("--model-b-run", required=True, type=Path)
    parser.add_argument("--model-a-name", default="Model A")
    parser.add_argument("--model-b-name", default="Model B")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录；不指定时自动使用 runs/compare_result/<A>_win_<B>",
    )
    parser.add_argument(
        "--min-relative-difference",
        type=float,
        default=0.1,
        help="按满分比例筛选差异；默认 0.1，即满分 1 时差异 >0.1，满分 100 时差异 >10",
    )
    parser.add_argument(
        "--score-scale",
        choices=("auto", "1", "100"),
        default="auto",
        help="分数满分；auto 按当前维度数值自动判断",
    )
    parser.add_argument(
        "--strict-case-json",
        action="store_true",
        help="要求两个 case.json 全部字段完全一致；默认忽略 duration/fps/分辨率等生成参数",
    )
    parser.add_argument("--max-chart-rows", type=int, default=100)
    args = parser.parse_args()
    if args.min_relative_difference < 0 or args.max_chart_rows <= 0:
        parser.error("--min-relative-difference 不能为负数，--max-chart-rows 必须大于 0")
    if args.output_dir is None:
        args.output_dir = Path("runs/compare_result") / (
            f"{safe_filename(args.model_a_name)}_win_{safe_filename(args.model_b_name)}"
        )
    a_cases = find_case_files(args.model_a_run.resolve())
    b_cases = find_case_files(args.model_b_run.resolve())
    known_ids = set(a_cases) | set(b_cases)
    a_scores = read_scores(args.model_a_run.resolve(), a_cases)
    b_scores = read_scores(args.model_b_run.resolve(), b_cases)
    print(f"已解析分数：{args.model_a_name}={len(a_scores)}，{args.model_b_name}={len(b_scores)}")
    rows, stats = build_rows(
        a_cases,
        b_cases,
        a_scores,
        b_scores,
        args.min_relative_difference,
        args.score_scale,
        args.strict_case_json,
    )
    write_outputs(args.output_dir.resolve(), rows, stats, args)
    print(json.dumps({**stats, "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
