#!/usr/bin/env python3
"""Run an RQ1 evaluation configuration end to end.

User-facing entrypoint. For example:

    GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config full

The final terminal output is the paper-facing summary. Intermediate command
output is written to run.log under the run directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
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
    "actplane": EvalConfig(
        systems=("actplane", "actplane-opaque"),
        out_name="actplane",
    ),
    "full": EvalConfig(
        systems=("prompt-only", "tool-regex", "actplane", "actplane-opaque"),
        out_name="full",
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


def trace_specs(root: Path, limit: int | None = None) -> list[tuple[str, str, str]]:
    return [key for _, _, key in trace_jobs(root, limit)]


def trace_jobs(
    root: Path,
    limit: int | None = None,
) -> list[tuple[Path, Path, tuple[str, str, str]]]:
    jobs: list[tuple[Path, Path, tuple[str, str, str]]] = []
    for rule in sorted(root.glob("*/*/rule.yaml")):
        statement_dir = rule.parent
        repo = statement_dir.parent.name.replace("__", "/")
        statement_id = statement_dir.name
        for trace in sorted(statement_dir.glob("trace_*.jsonl")):
            key = (repo, statement_id, trace.name)
            jobs.append((statement_dir, trace, key))
    if limit is not None:
        jobs = jobs[:limit]
    return jobs


def load_json_result(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def runner_keys(path: Path, *, system: str, model_name: str) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    if not path.exists():
        return keys
    for result in path.glob("**/results/*.json"):
        data = load_json_result(result)
        if not data:
            continue
        if data.get("system") != system or data.get("model") != model_name:
            continue
        repo = str(data.get("repo") or "")
        statement_id = str(data.get("statement_id") or "")
        trace_file = str(data.get("trace_file") or data.get("trace") or "")
        if repo and statement_id and trace_file:
            keys.add((repo, statement_id, trace_file))
    return keys


def docker_eval_cmd(
    *,
    config: EvalConfig,
    args: argparse.Namespace,
    system: str,
    system_out: Path,
    no_build: bool,
    statement_dir: Path | None = None,
    trace: Path | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "docker_agent_sdk_eval.py"),
        "--image",
        config.image,
        "--out-dir",
        str(system_out),
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
        str(args.max_steps if args.max_steps is not None else config.max_steps),
    ]
    if statement_dir is not None and trace is not None:
        cmd.extend(["--statement-dir", str(statement_dir), "--trace", str(trace)])
    else:
        cmd.extend(["--root", str(config.root)])
        if args.limit is not None:
            cmd.extend(["--limit", str(args.limit)])
    if no_build:
        cmd.append("--no-build")
    return cmd


def run_parallel_system(
    *,
    config: EvalConfig,
    args: argparse.Namespace,
    system: str,
    system_out: Path,
    expected: set[tuple[str, str, str]],
    env: dict[str, str],
    log_path: Path,
) -> int:
    complete = runner_keys(system_out, system=system, model_name=config.model_name)
    pending = [
        (statement_dir, trace, key)
        for statement_dir, trace, key in trace_jobs(config.root, args.limit)
        if key in expected and key not in complete
    ]
    if not pending:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"\n\n## run {system}\n"
                f"skip existing runner results: {len(complete & expected)}/{len(expected)}\n"
            )
        return 0

    def run_one(job: tuple[Path, Path, tuple[str, str, str]]) -> tuple[tuple[str, str, str], int, str]:
        statement_dir, trace, key = job
        cmd = docker_eval_cmd(
            config=config,
            args=args,
            system=system,
            system_out=system_out,
            no_build=True,
            statement_dir=statement_dir,
            trace=trace,
        )
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return key, proc.returncode, proc.stdout

    failures = 0
    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            f"\n\n## run {system}\n"
            f"parallel workers: {args.workers}; pending traces: {len(pending)}/{len(expected)}\n"
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one, job) for job in pending]
        for future in concurrent.futures.as_completed(futures):
            key, returncode, stdout = future.result()
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n### {system} {key[0]}/{key[1]} {key[2]}\n")
                log.write(stdout)
            if returncode != 0:
                failures += 1
                print(
                    f"run {system} failed for {key[0]}/{key[1]} {key[2]} "
                    f"with rc={returncode}. See {rel(log_path)}.",
                    file=sys.stderr,
                )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--api-key-env", default="GLM_API_KEY")
    parser.add_argument(
        "--limit",
        type=int,
        help="Run only the first N trace-conditioned scenarios for sanity checks.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Run trace-level Docker jobs in parallel. Default: 1.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        help="Override the per-scenario agent tool-step budget.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = CONFIGS[args.config]

    if args.api_key_env not in os.environ:
        print(f"{args.api_key_env} is not set", file=sys.stderr)
        return 2
    if args.workers < 1:
        print("--workers must be >= 1", file=sys.stderr)
        return 2
    if args.max_steps is not None and args.max_steps < 0:
        print("--max-steps must be >= 0", file=sys.stderr)
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

    if args.workers > 1 and not args.no_build:
        build_cmd = [
            "docker",
            "build",
            "-f",
            str(SCRIPT_DIR / "Dockerfile.agent-sdk"),
            "-t",
            config.image,
            str(SCRIPT_DIR),
        ]
        if run_phase("build docker image", build_cmd, env=env, log_path=log_path).returncode != 0:
            return 1

    result_dirs: list[Path] = []
    expected = set(trace_specs(config.root, args.limit))
    expected_results = len(expected)
    if expected_results == 0:
        print("No trace scenarios found.", file=sys.stderr)
        return 1
    for idx, system in enumerate(config.systems):
        system_out = out_dir / system
        result_dirs.append(system_out)
        complete = runner_keys(system_out, system=system, model_name=config.model_name)
        complete_expected = len(complete & expected)
        if complete_expected >= expected_results:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\n\n## run {system}\n"
                    f"skip existing runner results: {complete_expected}/{expected_results}\n"
                )
            continue
        if args.workers > 1:
            rc = run_parallel_system(
                config=config,
                args=args,
                system=system,
                system_out=system_out,
                expected=expected,
                env=env,
                log_path=log_path,
            )
            if rc != 0:
                return rc
            continue
        cmd = docker_eval_cmd(
            config=config,
            args=args,
            system=system,
            system_out=system_out,
            no_build=args.no_build or idx > 0,
        )
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
