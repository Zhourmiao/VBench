#!/usr/bin/env python3
"""Run dataset-specific VBench evaluation from one self-contained run directory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("读取 YAML 配置需要 PyYAML；也可以使用 run.json") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"配置必须是对象: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_command(command: list[str], cwd: Path, log_path: Path) -> dict[str, Any]:
    """Run a child process while teeing its output to terminal and log."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write("$ " + " ".join(command) + "\n")
        handle.flush()
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        output_lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            handle.write(line)
            output_lines.append(line)
            if len(output_lines) > 200:
                output_lines.pop(0)
        returncode = process.wait()
        output = "".join(output_lines)
        handle.write(f"[returncode={returncode}]\n\n")
    return {
        "command": command,
        "returncode": returncode,
        "status": "success" if returncode == 0 else "error",
        "output_tail": output[-4000:],
    }


def load_partial(path: Path, resume: bool) -> list[dict[str, Any]]:
    if not resume or not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def save_partial(path: Path, results: list[dict[str, Any]]) -> None:
    write_json(path, results)


def run_vbench2(run_dir: Path, config: dict[str, Any], log_path: Path, resume: bool) -> list[dict[str, Any]]:
    videos_root = (run_dir / config["videos_root"]).resolve()
    full_info = (run_dir / config["full_info"]).resolve()
    output_root = (run_dir / config.get("evaluation_root", "evaluation")).resolve()
    partial_path = output_root / "dispatch_results.partial.json"
    results = load_partial(partial_path, resume)
    completed_dimensions = {item["dimension"] for item in results if item.get("returncode") == 0}
    for dimension in config["dimensions"]:
        if dimension in completed_dimensions:
            print(f"跳过已完成指标（resume）：{dimension}")
            continue
        command = [
            sys.executable, "-u", str(ROOT / "source/VBench-2.0/evaluate.py"),
            "--videos_path", str(videos_root / dimension),
            "--full_json_dir", str(full_info),
            "--output_path", str(output_root / dimension),
            "--dimension", dimension,
            "--mode", config.get("mode", "vbench_standard"),
        ]
        if config.get("load_ckpt_from_local") is not None:
            command += ["--load_ckpt_from_local", str(config["load_ckpt_from_local"])]
        if config.get("read_frame") is not None:
            command += ["--read_frame", str(config["read_frame"])]
        if config.get("skip_missing_videos", False):
            command.append("--skip_missing_videos")
        result = run_command(command, ROOT / "source/VBench-2.0", log_path)
        results.append({"dimension": dimension, **result})
        save_partial(partial_path, results)
        if result["returncode"] != 0 and config.get("stop_on_error", True):
            break
    return results


def run_i2v(run_dir: Path, config: dict[str, Any], log_path: Path, resume: bool) -> list[dict[str, Any]]:
    videos_path = (run_dir / config["videos_path"]).resolve()
    output_root = (run_dir / config.get("evaluation_root", "evaluation")).resolve()
    raw_info = Path(config["full_info"])
    full_info = raw_info if raw_info.is_absolute() else (ROOT / raw_info).resolve()
    wrapper = ROOT / "pipelines/run_i2v_evaluation.py"
    partial_path = output_root / "dispatch_results.partial.json"
    results = load_partial(partial_path, resume)
    completed_dimensions = {item["dimension"] for item in results if item.get("returncode") == 0}
    for dimension in config["dimensions"]:
        if dimension in completed_dimensions:
            print(f"跳过已完成指标（resume）：{dimension}")
            continue
        command = [
            sys.executable, "-u", str(wrapper),
            "--videos-path", str(videos_path),
            "--full-info", str(full_info),
            "--output-path", str(output_root / dimension),
            "--dimension", dimension,
            "--resolution", config.get("resolution", "16-9"),
        ]
        if config.get("custom_image_folder"):
            command += ["--custom-image-folder", str((run_dir / config["custom_image_folder"]).resolve())]
        if config.get("load_ckpt_from_local", False):
            command.append("--local")
        result = run_command(command, ROOT, log_path)
        results.append({"dimension": dimension, **result})
        save_partial(partial_path, results)
        if result["returncode"] != 0:
            break
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--resume", action="store_true", help="跳过 dispatch_results.partial.json 中已成功的指标")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    config_path = args.config
    if config_path is None:
        for candidate in (run_dir / "config/run.yaml", run_dir / "config/run.json"):
            if candidate.is_file():
                config_path = candidate
                break
    if config_path is None:
        raise FileNotFoundError(f"run 目录中没有 config/run.yaml 或 config/run.json: {run_dir}")
    config = load_config(config_path)
    resume = args.resume or bool(config.get("resume", False))
    log_path = run_dir / "evaluation/evaluation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if config.get("benchmark") == "vbench2":
        results = run_vbench2(run_dir, config, log_path, resume)
    elif config.get("benchmark") == "vbench_i2v":
        results = run_i2v(run_dir, config, log_path, resume)
    else:
        raise ValueError("benchmark 必须是 vbench2 或 vbench_i2v")
    write_json(run_dir / "evaluation/dispatch_results.json", results)
    if any(item["returncode"] != 0 for item in results):
        raise SystemExit(1)
    print(f"评测完成，结果目录：{run_dir / 'evaluation'}")


if __name__ == "__main__":
    main()
