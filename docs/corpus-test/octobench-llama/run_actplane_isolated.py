#!/usr/bin/env python3
"""Run OctoBench cases with ActPlane, LiteLLM proxy, and managed llama.cpp."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MINI_VELA = ROOT / "mini-vela"
DEFAULT_DATASET = MINI_VELA / "data" / "octobench_rq1_20.jsonl"
DEFAULT_VENV = Path("/tmp/octobench-litellm-venv")
DEFAULT_ACTPLANE = ROOT / "actplane-glibc231"
DEFAULT_POLICY = ROOT / "actplane-octobench-os.yaml"
EVAL_SCRIPTS = ROOT.parents[1] / "eval_scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from llama_server import LlamaServer  # noqa: E402
from run_official_isolated import kill_process_tree, load_cases, start_proxy, write_json  # noqa: E402


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_json_from_stdout(stdout: str) -> dict[str, Any]:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(stdout[start : end + 1])
    except json.JSONDecodeError:
        return {}


def run_case(case: dict[str, Any], index: int, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    instance_id = case["instance_id"]
    case_dir = run_dir / f"{index:02d}-{instance_id}"
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "case.json", case)

    mini_results = MINI_VELA / "results"
    if mini_results.exists():
        shutil.rmtree(mini_results)
    (mini_results / "trajectories").mkdir(parents=True, exist_ok=True)

    proxy = start_proxy(args.venv, case_dir / "proxy.log")
    env = os.environ.copy()
    env["PATH"] = f"{args.venv / 'bin'}:{env.get('PATH', '')}"
    cmd = [
        sys.executable,
        str(ROOT / "run_actplane_case.py"),
        "--case",
        instance_id,
        "--dataset",
        str(args.dataset),
        "--policy",
        str(args.policy),
        "--actplane",
        str(args.actplane),
        "--model",
        args.model,
        "--timeout",
        str(args.timeout),
        "--out-dir",
        str(case_dir.resolve()),
    ]
    if args.claude_feedback_hook:
        cmd.append("--claude-feedback-hook")

    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    kill_process_tree(proxy)

    (case_dir / "wrapper.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (case_dir / "wrapper.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    parsed = parse_json_from_stdout(proc.stdout or "")
    result = {
        "instance_id": instance_id,
        "returncode": proc.returncode,
        "success": proc.returncode == 0,
        "elapsed_s": time.time() - started,
        "actplane_run": parsed,
    }

    if mini_results.exists():
        archive = case_dir / "mini-vela-results"
        if archive.exists():
            shutil.rmtree(archive)
        shutil.copytree(mini_results, archive)
        trajectories = sorted(str(p) for p in (archive / "trajectories").glob("*.jsonl"))
        result["trajectory_files"] = trajectories
        result["trajectory_count"] = len(trajectories)
    else:
        result["trajectory_files"] = []
        result["trajectory_count"] = 0

    write_json(case_dir / "result.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--model", default="claude-sonnet-4-5-20250929")
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--actplane", type=Path, default=DEFAULT_ACTPLANE)
    parser.add_argument("--claude-feedback-hook", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--managed-llama", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(args.dataset, args.limit)
    run_dir = args.out_dir / f"actplane-isolated-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "metadata.json",
        {
            "dataset": str(args.dataset),
            "limit": args.limit,
            "timeout_s": args.timeout,
            "model": args.model,
            "policy": str(args.policy),
            "actplane": str(args.actplane),
            "managed_llama": args.managed_llama,
            "n_ctx": 128000,
            "claude_feedback_hook": args.claude_feedback_hook,
            "case_count": len(cases),
        },
    )

    server = None
    if args.managed_llama:
        server = LlamaServer(
            judge_json=False,
            restart_existing=True,
            log_path=run_dir / "llama-server.log",
        )

    results: list[dict[str, Any]] = []
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

    print(json.dumps({"run_dir": str(run_dir), "case_count": len(results)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
