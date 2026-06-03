#!/usr/bin/env python3
"""Probe one real OctoBench Claude Code container via LiteLLM -> llama.cpp."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CONFLICTS_URL = (
    "https://huggingface.co/datasets/MiniMaxAI/OctoBench/resolve/main/"
    "conflicts.jsonl"
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_first_claudecode_case() -> dict[str, Any]:
    with urllib.request.urlopen(CONFLICTS_URL, timeout=30) as resp:
        for raw in resp:
            if not raw.strip():
                continue
            case = json.loads(raw)
            if case.get("scaffold", {}).get("name") == "claudecode":
                return case
    raise RuntimeError("no claudecode case found")


def wait_http(url: str, timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def start_litellm(config: Path, port: int, log_path: Path) -> subprocess.Popen:
    cmd = [
        "litellm",
        "--config",
        str(config),
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
    ]
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    if not wait_http(f"http://127.0.0.1:{port}/health/liveliness", timeout_s=90):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise RuntimeError(f"LiteLLM did not become healthy on port {port}")
    return proc


def stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def run_container(case: dict[str, Any], port: int, timeout_s: int) -> dict[str, Any]:
    image = case["image"]
    workspace = case.get("workspace_abs_path", "/workspace")
    query = case.get("user_query", [""])[0]
    system_prompt = case.get("system_prompt", "")

    settings = json.dumps(
        {
            "env": {
                "ANTHROPIC_BASE_URL": f"http://host.docker.internal:{port}",
            },
            "permissions": {
                "allow": [
                    "Bash(*)",
                    "Write(*)",
                    "Edit(*)",
                    "Read(*)",
                    "Glob(*)",
                    "Grep(*)",
                    "LS(*)",
                    "TodoRead(*)",
                    "TodoWrite(*)",
                ]
            },
        },
        ensure_ascii=True,
    )

    setup = "mkdir -p ~/.claude && printf %s " + shlex.quote(settings)
    setup += " > ~/.claude/settings.json"
    claude_parts = [
        "claude",
        "--model",
        "claude-sonnet-4-5-20250929",
        "--dangerously-skip-permissions",
        "-p",
        query,
    ]
    if system_prompt:
        claude_parts.extend(["--system-prompt", system_prompt])
    command = setup + " && " + shell_join(claude_parts)
    container_name = f"octobench-llama-probe-{int(time.time())}"

    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-e",
        f"ANTHROPIC_BASE_URL=http://host.docker.internal:{port}",
        "-e",
        "ANTHROPIC_API_KEY=fake-key",
        "-e",
        "IS_SANDBOX=1",
        "-w",
        workspace,
        image,
        "bash",
        "-lc",
        command,
    ]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "command": cmd,
            "returncode": None,
            "elapsed_s": time.time() - started,
            "stdout": stdout,
            "stderr": stderr,
            "timeout": True,
            "timeout_s": timeout_s,
        }
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "elapsed_s": time.time() - started,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=14000)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "litellm_config.local.yaml",
    )
    args = parser.parse_args()

    case = read_first_claudecode_case()
    run_dir = args.out_dir / f"claudecode-probe-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "case.json").write_text(
        json.dumps(case, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    proxy_log = run_dir / "litellm.log"
    proxy = start_litellm(args.config, args.port, proxy_log)
    try:
        result = run_container(case, args.port, args.timeout)
    finally:
        stop_process(proxy)

    report = {
        "kind": "claudecode_litellm_llama_probe",
        "case": {
            "instance_id": case.get("instance_id"),
            "image": case.get("image"),
            "workspace_abs_path": case.get("workspace_abs_path"),
            "scaffold": case.get("scaffold"),
        },
        "litellm_port": args.port,
        "result": result,
        "proxy_log": str(proxy_log),
    }
    out = run_dir / "probe.json"
    out.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "returncode": result["returncode"]}, indent=2))
    return 0 if result["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
