#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "docs" / "eval_scripts"))

from judge_trajectory import default_output_path  # noqa: E402
from llama_server import LlamaServer  # noqa: E402
from run_eval import (  # noqa: E402
    LLAMA_API_KEY_ENV,
    LLAMA_JUDGE_MAX_TOKENS,
    LLAMA_START_TIMEOUT,
    docker_eval_cmd,
    module_cmd,
    select_runner_files,
)


SYSTEMS = ("prompt-filter", "tool-regex", "actplane-opaque", "actplane")
JUDGE_DIR = "trajectory_judges_llama_cpp_guardrail_response"
MODEL_NAME = "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run_phase(
    name: str,
    cmd: list[str],
    *,
    env: dict[str, str],
    log_path: Path,
    attempts: int = 2,
    timeout: float | None = None,
) -> int:
    for attempt in range(1, attempts + 1):
        label = name if attempt == 1 else f"{name} retry {attempt}/{attempts}"
        print(f"## {label}", flush=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n\n## {label}\n+ {' '.join(map(str, cmd))}\n")
            log.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert proc.stdout is not None
            tail: list[str] = []
            started = time.time()
            while True:
                line = proc.stdout.readline()
                if line:
                    log.write(line)
                    log.flush()
                    tail.append(line)
                    tail = tail[-80:]
                if proc.poll() is not None:
                    rest = proc.stdout.read()
                    if rest:
                        log.write(rest)
                        log.flush()
                        tail.extend(rest.splitlines(True))
                    break
                if timeout is not None and time.time() - started > timeout:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)
                    break
                time.sleep(0.1)
            rc = proc.returncode
        if rc == 0:
            return 0
        print(f"{label} failed rc={rc}", flush=True)
        if attempt < attempts and rc in (137, 139):
            continue
        print("".join(tail)[-6000:], flush=True)
        return rc if rc is not None else 124
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--name", default="one_trace_tuning")
    args = parser.parse_args()

    trace = args.trace
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "docs" / "tmp" / "rq1" / f"{args.name}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "run.log"
    expected = {(trace.parent.parent.name.replace("__", "/"), trace.parent.name, trace.name)}
    env = os.environ.copy()
    env[LLAMA_API_KEY_ENV] = env.get(LLAMA_API_KEY_ENV) or "local"

    if not hasattr(LlamaServer, "model_name"):
        LlamaServer.model_name = lambda self: self.model_path.name.removesuffix(".gguf")

    agent = LlamaServer(judge_json=False, restart_existing=True, log_path=out / "llama-agent-server.log")
    try:
        agent.start(timeout=LLAMA_START_TIMEOUT)
        model = agent.model_name()
        print("agent model:", model, flush=True)
        for system in SYSTEMS:
            cmd = docker_eval_cmd(
                system=system,
                out_dir=out / system,
                agent_base_url=f"{agent.base_url}/v1",
                model_name=model,
                api_key_env=LLAMA_API_KEY_ENV,
                limit=None,
                statement_dir=trace.parent,
                trace=trace,
            )
            rc = run_phase(f"run {system}", cmd, env=env, log_path=log_path, attempts=3)
            if rc != 0:
                raise SystemExit(f"runner failed {system} rc={rc}")
    finally:
        agent.stop()

    result_files = select_runner_files(
        [out / s for s in SYSTEMS],
        systems=SYSTEMS,
        expected=expected,
        model_name=MODEL_NAME,
    )
    result_list = out / "selected_runner_results.txt"
    result_list.write_text("".join(rel(p) + "\n" for p in result_files), encoding="utf-8")
    print(f"runner results selected: {len(result_files)} / 4", flush=True)
    if len(result_files) != 4:
        return 1

    judge = LlamaServer(judge_json=True, restart_existing=True, log_path=out / "llama-judge-server.log")
    try:
        judge.start(timeout=LLAMA_START_TIMEOUT)
        judge_model = judge.model_name()
        print("judge model:", judge_model, flush=True)
        for idx, path in enumerate(result_files, 1):
            path = path if path.is_absolute() else ROOT / path
            if default_output_path(path, JUDGE_DIR).exists():
                continue
            one = out / "judge_one_input.txt"
            one.write_text(str(path) + "\n", encoding="utf-8")
            cmd = module_cmd(
                "judge_trajectory",
                [
                    "--judge-dir-name",
                    JUDGE_DIR,
                    "--base-url",
                    f"{judge.base_url}/v1",
                    "--model-name",
                    judge_model,
                    "--api-key-env",
                    LLAMA_API_KEY_ENV,
                    "--timeout",
                    "300",
                    "--retries",
                    "1",
                    "--retry-sleep",
                    "10",
                    "--retry-sleep-max",
                    "20",
                    "--workers",
                    "1",
                    "--max-tokens",
                    str(LLAMA_JUDGE_MAX_TOKENS),
                    "--input-list",
                    str(one),
                ],
            )
            rc = run_phase(f"judge {idx}/4", cmd, env=env, log_path=log_path, timeout=420)
            if rc != 0:
                raise SystemExit(f"judge failed rc={rc}")
    finally:
        judge.stop()

    cmd = module_cmd(
        "summarize_agent_sdk_results",
        ["--judge-dir-name", JUDGE_DIR, "--input-list", str(result_list)],
    )
    rc = run_phase("summarize", cmd, env=env, log_path=log_path, attempts=1)
    print("one-trace run:", rel(out), flush=True)
    print(log_path.read_text(encoding="utf-8")[-5000:], flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
