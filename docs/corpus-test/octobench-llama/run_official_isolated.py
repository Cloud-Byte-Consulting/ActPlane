#!/usr/bin/env python3
"""Run OctoBench cases with upstream mini-vela, isolated one case at a time."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MINI_VELA = ROOT / "mini-vela"
EVAL_SCRIPTS = ROOT.parents[1] / "eval_scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from llama_server import LlamaServer  # noqa: E402

DEFAULT_DATASET = MINI_VELA / "data" / "octobench_first10.jsonl"
DEFAULT_VENV = Path("/tmp/octobench-litellm-venv")
DEFAULT_LLAMA_CMD = [
    "/home/yunwei37/workspace/llama.cpp-latest/build/bin/llama-server",
    "-m",
    "/home/yunwei37/.cache/huggingface/hub/models--DevQuasar--Qwen.Qwen3.6-27B-GGUF/snapshots/b19fa7e8538a1a5f66452eb3b3167e026177be1d/Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf",
    "--host",
    "127.0.0.1",
    "--port",
    "18080",
    "--device",
    "CUDA0",
    "--fit",
    "off",
    "-ngl",
    "all",
    "-c",
    "128000",
    "--no-webui",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_cases(dataset: Path, limit: int | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with dataset.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            cases.append(json.loads(line))
            if limit is not None and len(cases) >= limit:
                break
    return cases


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wait_url(url: str, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except Exception:
            time.sleep(2)
    return False


def kill_process_tree(proc: subprocess.Popen, grace_s: int = 10) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + grace_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.5)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=10)


def existing_llama_pids() -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "llama-server.*--port 18080"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    pids: list[int] = []
    own_pid = os.getpid()
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != own_pid:
            pids.append(pid)
    return pids


def existing_llama_supervisor_pids() -> list[int]:
    result = subprocess.run(
        ["pgrep", "-af", "docs/eval_scripts/llama_server.py start"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    pids: list[int] = []
    own_pid = os.getpid()
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != own_pid:
            pids.append(pid)
    return pids


def restart_llama(log_path: Path) -> None:
    for pid in existing_llama_supervisor_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(1)
    for pid in existing_llama_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + 30
    while time.time() < deadline:
        live = []
        for pid in existing_llama_pids():
            try:
                os.kill(pid, 0)
                live.append(pid)
            except ProcessLookupError:
                pass
        if not live:
            break
        time.sleep(1)
    for pid in existing_llama_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for pid in existing_llama_supervisor_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    subprocess.Popen(
        DEFAULT_LLAMA_CMD,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    if not wait_url("http://127.0.0.1:18080/health", timeout_s=360):
        raise RuntimeError(f"llama-server did not become healthy; see {log_path}")


def start_proxy(venv: Path, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{venv / 'bin'}:{env.get('PATH', '')}"
    proc = subprocess.Popen(
        [str(venv / "bin" / "python"), "proxy/start_proxy.py"],
        cwd=MINI_VELA,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    if not wait_url("http://127.0.0.1:4000/health/liveliness", timeout_s=120):
        kill_process_tree(proc)
        raise RuntimeError(f"proxy did not become live; see {log_path}")
    return proc


def run_case(case: dict[str, Any], index: int, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    instance_id = case["instance_id"]
    case_dir = run_dir / f"{index:02d}-{instance_id}"
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "case.json", case)

    if args.restart_llama:
        restart_llama(case_dir / "llama-server.log")

    mini_results = MINI_VELA / "results"
    if mini_results.exists():
        shutil.rmtree(mini_results)
    (mini_results / "trajectories").mkdir(parents=True, exist_ok=True)

    proxy = start_proxy(args.venv, case_dir / "proxy.log")
    env = os.environ.copy()
    env["PATH"] = f"{args.venv / 'bin'}:{env.get('PATH', '')}"
    cmd = [
        str(args.venv / "bin" / "python"),
        "benchmark_runner.py",
        "--dataset",
        str(args.dataset),
        "--model",
        args.model,
        "--case",
        instance_id,
        "--timeout",
        str(args.timeout),
        "--skip-proxy-check",
    ]
    write_json(case_dir / "runner-command.json", {"cmd": cmd, "cwd": str(MINI_VELA)})
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=MINI_VELA,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = {
            "instance_id": instance_id,
            "returncode": proc.returncode,
            "success": proc.returncode == 0,
            "elapsed_s": time.time() - started,
        }
        (case_dir / "runner.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (case_dir / "runner.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    finally:
        kill_process_tree(proxy)

    if mini_results.exists():
        archive = case_dir / "mini-vela-results"
        if archive.exists():
            shutil.rmtree(archive)
        shutil.copytree(mini_results, archive)

    write_json(case_dir / "result.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--model", default="claude-sonnet-4-5-20250929")
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--restart-llama", action="store_true")
    parser.add_argument(
        "--managed-llama",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start one local llama.cpp server before the run and stop it afterwards.",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.managed_llama and args.restart_llama:
        raise SystemExit("--managed-llama and --restart-llama are mutually exclusive")
    cases = load_cases(args.dataset, args.limit)
    run_dir = args.out_dir / f"baseline-isolated-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "metadata.json",
        {
            "dataset": str(args.dataset),
            "limit": args.limit,
            "timeout_s": args.timeout,
            "model": args.model,
            "restart_llama": args.restart_llama,
            "managed_llama": args.managed_llama,
            "n_ctx": 128000,
            "case_count": len(cases),
        },
    )

    results = []
    server = None
    if args.managed_llama:
        server = LlamaServer(
            judge_json=False,
            restart_existing=True,
            log_path=run_dir / "llama-server.log",
        )
    try:
        if server:
            server.start(timeout=360)
        for index, case in enumerate(cases):
            print(f"[{index + 1}/{len(cases)}] {case['instance_id']}", flush=True)
            result = run_case(case, index, args, run_dir)
            results.append(result)
            write_json(run_dir / "summary.json", {"results": results})
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        if server:
            server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
