#!/usr/bin/env python3
"""Run an external LTX-2.3 I2V workflow experiment without changing MOG.

The script uploads an image, edits a copied ComfyUI workflow, submits it to a
selected ComfyUI node, polls the job, downloads the output, and records the
experiment parameters in JSONL.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_NODES = [
    "http://110.126.0.52:8181",
    "http://110.126.0.52:8182",
    "http://110.126.0.52:8183",
    "http://110.126.0.52:8184",
]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = REPO_ROOT / "workflows/comfyui/i2v/Opt3_balanced_i2v075_lora060.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--nodes", nargs="+", default=DEFAULT_NODES)
    parser.add_argument("--sampler")
    parser.add_argument("--cfg", type=float)
    parser.add_argument("--lora-strength", type=float)
    parser.add_argument("--image-strength-1", type=float)
    parser.add_argument("--image-strength-2", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--duration", type=int)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    return parser.parse_args()


def set_inputs(workflow: dict[str, Any], args: argparse.Namespace, image_name: str) -> None:
    workflow["269"]["inputs"]["image"] = image_name
    workflow["320:319"]["inputs"]["value"] = args.prompt
    if args.sampler is not None:
        workflow["320:280"]["inputs"]["sampler_name"] = args.sampler
        workflow["320:291"]["inputs"]["sampler_name"] = args.sampler
    if args.cfg is not None:
        workflow["320:282"]["inputs"]["cfg"] = args.cfg
        workflow["320:314"]["inputs"]["cfg"] = args.cfg
    if args.lora_strength is not None:
        workflow["320:285"]["inputs"]["strength_model"] = args.lora_strength
    if args.image_strength_1 is not None:
        workflow["320:288"]["inputs"]["strength"] = args.image_strength_1
    if args.image_strength_2 is not None:
        workflow["320:296"]["inputs"]["strength"] = args.image_strength_2
    if args.seed is not None:
        workflow["320:276"]["inputs"]["noise_seed"] = args.seed
        workflow["320:277"]["inputs"]["noise_seed"] = args.seed
    if args.height is not None:
        workflow["320:299"]["inputs"]["value"] = args.height
    if args.fps is not None:
        workflow["320:300"]["inputs"]["value"] = args.fps
    if args.duration is not None:
        workflow["320:301"]["inputs"]["value"] = args.duration
    if args.width is not None:
        workflow["320:312"]["inputs"]["value"] = args.width


def effective_parameters(workflow: dict[str, Any]) -> dict[str, Any]:
    inputs = lambda node, name: workflow[node]["inputs"][name]
    return {
        "sampler": inputs("320:280", "sampler_name"),
        "sampler_2": inputs("320:291", "sampler_name"),
        "cfg": inputs("320:282", "cfg"),
        "cfg_2": inputs("320:314", "cfg"),
        "lora_strength": inputs("320:285", "strength_model"),
        "image_strength_1": inputs("320:288", "strength"),
        "image_strength_2": inputs("320:296", "strength"),
        "seed_1": inputs("320:276", "noise_seed"),
        "seed_2": inputs("320:277", "noise_seed"),
        "width": inputs("320:312", "value"),
        "height": inputs("320:299", "value"),
        "fps": inputs("320:300", "value"),
        "duration": inputs("320:301", "value"),
    }


def upload_image(node: str, image_path: Path) -> str:
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with image_path.open("rb") as image_file:
        response = requests.post(
            f"{node}/upload/image",
            files={"image": (image_path.name, image_file, content_type)},
            timeout=60,
        )
    response.raise_for_status()
    return response.json()["name"]


def submit_workflow(node: str, workflow: dict[str, Any]) -> str:
    response = requests.post(f"{node}/api/prompt", json={"prompt": workflow}, timeout=600)
    response.raise_for_status()
    body = response.json()
    if "prompt_id" not in body:
        raise RuntimeError(f"ComfyUI 返回中没有 prompt_id: {body}")
    return body["prompt_id"]


def normalize_history_result(prompt_id: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    status_info = entry.get("status", {})
    if not isinstance(status_info, dict):
        status_info = {}
    status_str = status_info.get("status_str")
    outputs = entry.get("outputs", {})
    if status_str in {"error", "cancelled"}:
        return {
            "status": status_str,
            "outputs": outputs,
            "raw_history": entry,
            "status_source": "history",
        }
    if status_info.get("completed") or status_str in {"success", "completed"}:
        return {
            "status": "success",
            "outputs": outputs,
            "raw_history": entry,
            "status_source": "history",
        }
    return None


def poll_history(node: str, prompt_id: str) -> dict[str, Any] | None:
    response = requests.get(f"{node}/history/{prompt_id}", timeout=15)
    response.raise_for_status()
    body = response.json()
    entry = body.get(prompt_id) if isinstance(body, dict) else None
    if not isinstance(entry, dict):
        return None
    return normalize_history_result(prompt_id, entry)


def poll_job(node: str, prompt_id: str, poll_interval: float, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    use_history = False
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not use_history:
            try:
                response = requests.get(f"{node}/api/jobs/{prompt_id}", timeout=15)
                response.raise_for_status()
                result = response.json()
                if result.get("status") == "completed":
                    result["status"] = "success"
                result["status_source"] = "api_jobs"
                if result.get("status") in {"success", "error", "cancelled", "completed_no_output"}:
                    return result
            except requests.RequestException as exc:
                use_history = True
                last_error = exc

        if use_history:
            try:
                result = poll_history(node, prompt_id)
                if result is not None:
                    return result
            except requests.RequestException as exc:
                last_error = exc
        time.sleep(poll_interval)
    detail = f"；最后错误: {last_error}" if last_error else ""
    raise TimeoutError(f"任务 {prompt_id} 超过 {timeout} 秒仍未完成{detail}")


def find_media_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("filename"), str):
            return value
        for child in value.values():
            found = find_media_item(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_media_item(child)
            if found:
                return found
    return None


def download_output(node: str, result: dict[str, Any], output_path: Path) -> str:
    media = find_media_item(result.get("outputs", {}))
    if media is None:
        raise RuntimeError(f"任务成功但没有找到媒体输出: {result}")
    filename = media["filename"]
    params = {"filename": filename}
    if media.get("subfolder"):
        params["subfolder"] = media["subfolder"]
    response = requests.get(f"{node}/view", params=params, timeout=600)
    response.raise_for_status()
    partial_path = output_path.with_name(output_path.name + ".part")
    partial_path.write_bytes(response.content)
    if partial_path.stat().st_size == 0:
        partial_path.unlink()
        raise RuntimeError(f"下载媒体输出为空: {output_path}")
    partial_path.replace(output_path)
    return str(output_path)


def main() -> int:
    args = parse_args()
    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    if not args.template.is_file():
        raise FileNotFoundError(args.template)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    workflow = json.loads(args.template.read_text(encoding="utf-8"))
    node = args.nodes[0]
    started_at = time.time()
    record: dict[str, Any] = {
        "node": node,
        "input_image": str(args.image),
        "prompt": args.prompt,
        "sampler": args.sampler,
        "cfg": args.cfg,
        "lora_strength": args.lora_strength,
        "image_strength_1": args.image_strength_1,
        "image_strength_2": args.image_strength_2,
        "seed": args.seed,
        "width": args.width,
        "height": args.height,
        "duration": args.duration,
        "fps": args.fps,
    }

    try:
        image_name = upload_image(node, args.image)
        set_inputs(workflow, args, image_name)
        record["effective_parameters"] = effective_parameters(workflow)
        prompt_id = submit_workflow(node, workflow)
        record["prompt_id"] = prompt_id
        result = poll_job(node, prompt_id, args.poll_interval, args.timeout)
        record.update({"status": result.get("status"), "raw_result": result})
        if result.get("status") == "success":
            output_path = args.output_dir / f"{prompt_id}.mp4"
            record["local_video"] = download_output(node, result, output_path)
    except Exception as exc:
        record.update({"status": "client_error", "error": str(exc)})
    record["elapsed_sec"] = round(time.time() - started_at, 2)
    with (args.output_dir / "research_results.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record.get("status") == "success" and record.get("local_video") else 1


if __name__ == "__main__":
    raise SystemExit(main())
