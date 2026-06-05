#!/usr/bin/env python3
"""Run an RQ1 evaluation configuration end to end.

User-facing entrypoint. For example:

    GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config baseline

The final terminal output is the paper-facing summary. Intermediate command
output is written to run.log under the run directory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = ROOT / "docs" / "corpus-test"
DEFAULT_OUT_BASE = ROOT / "docs" / "eval_runs"


@dataclass(frozen=True)
class EvalConfig:
    systems: tuple[str, ...]
    out_name: str
    root: Path = DEFAULT_ROOT
    base_url: str = "https://api.z.ai/api/coding/paas/v4"
    model_name: str = "glm-4.7-flash"
    judge_model_name: str = "glm-4.7-flash"
    request_timeout: float = 120.0
    judge_timeout: float = 180.0
    judge_retries: int = 8
    judge_retry_sleep: float = 30.0
    judge_sleep_between: float = 8.0
    max_steps: int = 10
    image: str = "actplane-rq1-agent-sdk:latest"


CONFIGS: dict[str, EvalConfig] = {
    "baseline": EvalConfig(
        systems=("prompt-only", "tool-regex"),
        out_name="baseline",
    ),
}


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
) -> subprocess.CompletedProcess[str]:
    stdout_chunks: list[str] = []
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n\n## {name}\n")
        log.write("+ " + " ".join(cmd) + "\n")
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
        for line in proc.stdout:
            stdout_chunks.append(line)
            log.write(line)
            log.flush()
        returncode = proc.wait()
    stdout = "".join(stdout_chunks)
    result = subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    if result.returncode != 0:
        print(f"{name} failed with rc={result.returncode}. See {rel(log_path)}.", file=sys.stderr)
        if result.stdout.strip():
            print(result.stdout[-4000:], file=sys.stderr)
    return result


def judge_dir_name(model_name: str) -> str:
    safe = model_name.replace(".", "_").replace("-", "_").replace("/", "_")
    return f"trajectory_judges_{safe}"


def expected_trace_count(root: Path) -> int:
    return len(list(root.glob("*/*/trace_*.jsonl")))


def runner_result_count(path: Path) -> int:
    return len(list(path.glob("**/results/*.json"))) if path.exists() else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--api-key-env", default="GLM_API_KEY")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = CONFIGS[args.config]

    if args.api_key_env not in os.environ:
        print(f"{args.api_key_env} is not set", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (DEFAULT_OUT_BASE / config.out_name / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    env = os.environ.copy()

    judge_model = config.judge_model_name
    judge_dir = judge_dir_name(judge_model)

    validate_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "validate_trace_artifacts.py"),
        "--root",
        str(config.root),
        "--fail-on-invalid",
    ]
    if run_phase("validate traces", validate_cmd, env=env, log_path=log_path).returncode != 0:
        return 1

    result_dirs: list[Path] = []
    expected_results = expected_trace_count(config.root)
    for idx, system in enumerate(config.systems):
        system_out = out_dir / system
        result_dirs.append(system_out)
        if runner_result_count(system_out) >= expected_results:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\n\n## run {system}\n"
                    f"skip existing runner results: {runner_result_count(system_out)}/{expected_results}\n"
                )
            continue
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "docker_agent_sdk_eval.py"),
            "--image",
            config.image,
            "--out-dir",
            str(system_out),
            "--root",
            str(config.root),
            "--system",
            system,
            "--base-url",
            config.base_url,
            "--model-name",
            config.model_name,
            "--api-key-env",
            args.api_key_env,
            "--request-timeout",
            str(config.request_timeout),
            "--max-steps",
            str(config.max_steps),
        ]
        if args.no_build or idx > 0:
            cmd.append("--no-build")
        if run_phase(f"run {system}", cmd, env=env, log_path=log_path).returncode != 0:
            return 1

    judge_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "judge_trajectory.py"),
        *[str(path) for path in result_dirs],
        "--source-model",
        config.model_name,
        "--judge-dir-name",
        judge_dir,
        "--base-url",
        config.base_url,
        "--model-name",
        judge_model,
        "--api-key-env",
        args.api_key_env,
        "--timeout",
        str(config.judge_timeout),
        "--retries",
        str(config.judge_retries),
        "--retry-sleep",
        str(config.judge_retry_sleep),
        "--sleep-between",
        str(config.judge_sleep_between),
    ]
    if run_phase("judge trajectories", judge_cmd, env=env, log_path=log_path).returncode != 0:
        return 1

    summary_cmd = [
        sys.executable,
        str(SCRIPT_DIR / "summarize_agent_sdk_results.py"),
        *[str(path) for path in result_dirs],
        "--source-model",
        config.model_name,
        "--judge-dir-name",
        judge_dir,
    ]
    summary = run_phase("summarize", summary_cmd, env=env, log_path=log_path)
    if summary.returncode != 0:
        return 1

    print(summary.stdout.strip())
    print()
    print(f"Results: {rel(out_dir)}")
    print(f"Log: {rel(log_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
