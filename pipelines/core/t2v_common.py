#!/usr/bin/env python3
"""Shared helpers for the VBench-2.0 T2V generation pipeline."""

from __future__ import annotations

import json
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


def submit_workflow(node: str, workflow: dict[str, Any]) -> str:
    response = requests.post(f"{node}/api/prompt", json={"prompt": workflow}, timeout=600)
    response.raise_for_status()
    body = response.json()
    if "prompt_id" not in body:
        raise RuntimeError(f"ComfyUI 返回中没有 prompt_id: {body}")
    return body["prompt_id"]


def normalize_history_result(entry: dict[str, Any]) -> dict[str, Any] | None:
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
    return normalize_history_result(entry)


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
                if isinstance(result, dict) and isinstance(result.get(prompt_id), dict):
                    history_result = normalize_history_result(result[prompt_id])
                    if history_result is not None:
                        return history_result
                    time.sleep(poll_interval)
                    continue
                if result.get("status") == "completed":
                    result["status"] = "success"
                result["status_source"] = "api_jobs"
                if result.get("status") in {"success", "error", "cancelled", "completed_no_output"}:
                    return result
            except (requests.RequestException, ValueError) as exc:
                use_history = True
                last_error = exc

        if use_history:
            try:
                result = poll_history(node, prompt_id)
                if result is not None:
                    return result
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
        time.sleep(poll_interval)
    suffix = f"；最后一次错误：{last_error}" if last_error else ""
    raise TimeoutError(f"任务 {prompt_id} 超过 {timeout} 秒仍未完成{suffix}")


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
    media = find_media_item(result.get("outputs", result))
    if media is None:
        raise RuntimeError(f"任务成功但没有找到媒体输出: {result}")
    params = {"filename": media["filename"]}
    if media.get("subfolder"):
        params["subfolder"] = media["subfolder"]
    if media.get("type"):
        params["type"] = media["type"]
    response = requests.get(f"{node}/view", params=params, timeout=600)
    response.raise_for_status()
    partial_path = output_path.with_name(output_path.name + ".part")
    partial_path.write_bytes(response.content)
    if partial_path.stat().st_size == 0:
        partial_path.unlink()
        raise RuntimeError(f"下载媒体输出为空: {output_path}")
    partial_path.replace(output_path)
    return str(output_path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
