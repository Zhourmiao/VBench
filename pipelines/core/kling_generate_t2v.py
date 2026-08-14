#!/usr/bin/env python3
"""Generate Kling T2V videos and save them in the VBench run format.

Input cases are the JSON array produced by build_t2v_cases.py.
For each successful case this script writes:
  generation/<case_id>/<case_id>.mp4
  generation/<case_id>/case.json
  generation/<case_id>/generation.json
and appends one record to generation/manifest.jsonl.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://api-beijing.klingai.com"
TURBO_MODEL = "kling-3.0-turbo"
TERMINAL_STATUSES = {"succeed", "failed"}


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_jwt(access_key: str, secret_key: str) -> str:
    issued_at = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": access_key, "exp": issued_at + 1800, "nbf": issued_at - 5}
    encoded_header = base64url(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = base64url(json.dumps(payload, separators=(",", ":")).encode())
    unsigned = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret_key.encode(), unsigned, hashlib.sha256).digest()
    return f"{unsigned.decode()}.{base64url(signature)}"


class KlingAPIError(RuntimeError):
    pass


class KlingClient:
    def __init__(
        self,
        api_key: str = "",
        access_key: str = "",
        secret_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
    ):
        if not api_key and not (access_key and secret_key):
            raise ValueError(
                "需要 KLING_API_KEY，或同时设置 KLING_ACCESS_KEY 和 KLING_SECRET_KEY"
            )
        self.api_key = api_key
        self.access_key = access_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        token = self.api_key or create_jwt(self.access_key, self.secret_key)
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise KlingAPIError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise KlingAPIError(f"网络错误: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise KlingAPIError("Kling 返回了无效 JSON") from exc

        if result.get("code", 0) != 0:
            raise KlingAPIError(
                f"Kling error {result.get('code')}: "
                f"{result.get('message') or 'request rejected'}"
            )
        return result

    def create(self, prompt: str, model: str, options: dict[str, Any]) -> str:
        if model == TURBO_MODEL:
            response = self.request(
                "POST",
                "/text-to-video/kling-3.0-turbo",
                {"prompt": prompt, **options},
            )
            data = response.get("data") or {}
            if isinstance(data, list):
                data = data[0] if data else {}
            task_id = (
                response.get("task_id")
                or data.get("task_id")
                or data.get("id")
                or data.get("task", {}).get("task_id")
            )
        elif model == "kling-v3-omni":
            response = self.request(
                "POST", "/v1/videos/omni-video", {"prompt": prompt, **options}
            )
            task_id = response.get("data", {}).get("task_id")
        else:
            response = self.request(
                "POST",
                "/v1/videos/text2video",
                {"prompt": prompt, **options},
            )
            task_id = response.get("data", {}).get("task_id")

        if not task_id:
            raise KlingAPIError(f"响应中没有 task_id: {response}")
        return task_id

    def get_task(self, task_id: str, model: str) -> dict[str, Any]:
        if model == TURBO_MODEL:
            response = self.request("GET", f"/v1/videos/text2video/{task_id}")
            data = response.get("data")
            if isinstance(data, list):
                return data[0] if data else {}
            return data or response
        if model == "kling-v3-omni":
            response = self.request("GET", f"/v1/videos/omni-video/{task_id}")
        else:
            response = self.request("GET", f"/v1/videos/text2video/{task_id}")
        return response.get("data", {})

    def wait(self, task_id: str, model: str, poll_interval: int, timeout: int) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.get_task(task_id, model)
            status = str(task.get("task_status", "")).lower()
            print(f"task={task_id} status={status or 'unknown'}", file=sys.stderr)
            if status in TERMINAL_STATUSES:
                if status == "failed":
                    raise KlingAPIError(
                        f"生成失败: {task.get('task_status_msg', task)}"
                    )
                return task
            time.sleep(poll_interval)
        raise TimeoutError(f"等待任务超过 {timeout} 秒: {task_id}")


def download_video(url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        partial.replace(output)
    except urllib.error.URLError as exc:
        raise KlingAPIError(f"视频下载失败: {exc.reason}") from exc


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"cases 必须是 JSON 数组: {path}")
    cases = []
    for index, item in enumerate(raw, 1):
        case = dict(item)
        case.setdefault("case_id", f"t2v-{index:04d}")
        prompt = case.get("prompt_eval_en") or case.get("prompt") or case.get("prompt_input")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"案例缺少 prompt: {case.get('case_id')}")
        case["prompt_eval_en"] = prompt.strip()
        cases.append(case)
    return cases


def video_url_from_task(task: dict[str, Any]) -> str:
    videos = task.get("task_result", {}).get("videos", [])
    if not videos or not videos[0].get("url"):
        raise KlingAPIError(f"任务成功但没有返回视频 URL: {task}")
    return str(videos[0]["url"])


def build_options(args: argparse.Namespace) -> dict[str, Any]:
    if args.model == TURBO_MODEL:
        settings: dict[str, Any] = {
            "aspect_ratio": args.aspect_ratio,
            "resolution": "720p",
            "duration": args.duration,
        }
        if args.sound is not None:
            settings["sound"] = args.sound
        options: dict[str, Any] = {"settings": settings, "options": {}}
    else:
        options = {
            "model_name": args.model,
            "duration": str(args.duration),
            "aspect_ratio": args.aspect_ratio,
            "mode": args.mode,
        }
        if args.sound is not None:
            options["sound"] = args.sound
    if args.negative_prompt:
        options["negative_prompt"] = args.negative_prompt
    return options


def process_case(
    client: KlingClient,
    case: dict[str, Any],
    args: argparse.Namespace,
    output_root: Path,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    case_dir = output_root / case_id
    video_path = case_dir / f"{case_id}.mp4"
    metadata_path = case_dir / "generation.json"

    if video_path.is_file() and video_path.stat().st_size > 0 and not args.force:
        record = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        record["status"] = "skipped_existing"
        return record

    started_at = time.time()
    options = build_options(args)
    record: dict[str, Any] = {
        **case,
        "provider": "kling",
        "mode": "t2v",
        "model": args.model,
        "status": "submitted",
        "started_at": started_at,
        "output_video": str(video_path),
    }

    try:
        task_id = args.task_id if args.task_id else client.create(
            case["prompt_eval_en"], args.model, options
        )
        record["task_id"] = task_id
        task = client.wait(task_id, args.model, args.poll_interval, args.timeout)
        video_url = video_url_from_task(task)
        record["video_url"] = video_url
        download_video(video_url, video_path)
        record["status"] = "success"
        record["finished_at"] = time.time()
        record["case_json"] = str(case_dir / "case.json")
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "case.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        metadata_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return record
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        record["finished_at"] = time.time()
        case_dir.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases", type=Path)
    source.add_argument("--prompt")
    parser.add_argument("--case-id", default="t2v-0001")
    parser.add_argument("--sample-index", type=int, default=0)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--model", default=os.getenv("KLING_MODEL", TURBO_MODEL))
    parser.add_argument("--mode", choices=("std", "pro"), default="std")
    parser.add_argument("--duration", type=int, choices=range(3, 16), default=5)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16", "1:1"), default="16:9")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--sound", choices=("on", "off"))
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--base-url", default=os.getenv("KLING_BASE_URL", DEFAULT_BASE_URL))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.poll_interval < 1 or args.timeout < 1:
        raise ValueError("poll interval 和 timeout 必须大于 0")
    if args.task_id and args.cases:
        raise ValueError("--task-id 只能与单个 --prompt/--case-id 一起使用，不能与 --cases 同时使用")

    if args.cases:
        cases = load_cases(args.cases.resolve())
    else:
        cases = [{
            "case_id": args.case_id,
            "prompt_eval_en": args.prompt,
            "sample_index": args.sample_index,
        }]

    client = KlingClient(
        api_key=os.getenv("KLING_API_KEY", ""),
        access_key=os.getenv("KLING_ACCESS_KEY", ""),
        secret_key=os.getenv("KLING_SECRET_KEY", ""),
        base_url=args.base_url,
    )
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.jsonl"
    success = 0
    failed = 0

    with manifest_path.open("a", encoding="utf-8") as manifest:
        for case in cases:
            print(f"processing case={case['case_id']}", file=sys.stderr)
            record = process_case(client, case, args, output_root)
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()
            if record["status"] in {"success", "skipped_existing"}:
                success += 1
            else:
                failed += 1

    print(f"completed success={success} failed={failed}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KlingAPIError, TimeoutError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
