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

from llama_server import LlamaServer


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = ROOT / "docs" / "corpus-test"
DEFAULT_OUT_BASE = ROOT / "docs" / "eval_runs"
LLAMA_JUDGE_DIR = "trajectory_judges_llama_cpp_octobench"
LLAMA_JUDGE_MAX_TOKENS = 16384
LLAMA_JUDGE_TIMEOUT = 1800.0
LLAMA_START_TIMEOUT = 360.0


@dataclass(frozen=True)
class EvalConfig:
    systems: tuple[str, ...]
    out_name: str
    root: Path = DEFAULT_ROOT
    agent_base_url: str = "https://api.z.ai/api/coding/paas/v4"
    judge_base_url: str = "https://api.z.ai/api/paas/v4"
    model_name: str = "glm-4.7-flash"
    judge_model_name: str = "glm-4.7-flash"
    judge_thinking: str = "disabled"
    request_timeout: float = 120.0
    judge_timeout: float = 180.0
    judge_retries: int = 8
    judge_retry_sleep: float = 30.0
    judge_retry_sleep_max: float = 60.0
    judge_rate_limit_cooldown: float = 300.0
    judge_sleep_between: float = 120.0
    judge_batch_size: int = 4
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


def module_cmd(module: str, args: list[str]) -> list[str]:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
        f"from {module} import cli_main; "
        "raise SystemExit(cli_main(sys.argv[1:]))"
    )
    return [sys.executable, "-c", code, *args]


def judge_dir_name(model_name: str) -> str:
    safe = model_name.replace(".", "_").replace("-", "_").replace("/", "_")
    return f"trajectory_judges_{safe}"


def write_result_list(out_dir: Path, result_files: list[Path]) -> Path:
    path = out_dir / "selected_runner_results.txt"
    path.write_text(
        "".join(f"{rel(result)}\n" for result in result_files),
        encoding="utf-8",
    )
    return path


def input_list_paths(paths: list[Path]) -> list[Path]:
    normalized: list[Path] = []
    for path in paths:
        candidate = path if path.is_absolute() else ROOT / path
        if not candidate.exists():
            raise FileNotFoundError(f"input list not found: {path}")
        normalized.append(candidate)
    return normalized


def trace_specs(root: Path, limit: int | None = None) -> list[tuple[str, str, str]]:
    return [key for _, _, key in trace_jobs(root, limit)]


def manifest_trace_files(statement_dir: Path) -> list[Path]:
    manifest_path = statement_dir / "statement.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing statement manifest: {rel(manifest_path)}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid statement manifest: {rel(manifest_path)}: {exc}") from exc
    trace_names = manifest.get("trace_files")
    if not isinstance(trace_names, list) or not trace_names:
        raise ValueError(f"statement manifest has no trace_files list: {rel(manifest_path)}")
    traces: list[Path] = []
    for name in trace_names:
        if not isinstance(name, str) or "/" in name or name.startswith("."):
            raise ValueError(f"invalid trace file name in {rel(manifest_path)}: {name!r}")
        trace = statement_dir / name
        if not trace.exists():
            raise FileNotFoundError(f"manifest trace not found: {rel(trace)}")
        traces.append(trace)
    return traces


def trace_jobs(
    root: Path,
    limit: int | None = None,
) -> list[tuple[Path, Path, tuple[str, str, str]]]:
    jobs: list[tuple[Path, Path, tuple[str, str, str]]] = []
    for rule in sorted(root.glob("*/*/rule.yaml")):
        statement_dir = rule.parent
        repo = statement_dir.parent.name.replace("__", "/")
        statement_id = statement_dir.name
        for trace in manifest_trace_files(statement_dir):
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


def is_complete_runner_result(data: dict) -> bool:
    if data.get("scorable") is False:
        return False
    output = str(data.get("agent_output") or "")
    if output.startswith("(setup error:"):
        return False
    external_or_runner_errors = [
        "RateLimitError",
        "Error code: 429",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "Tool Edit not found",
        "Tool Bash not found",
        "Tool Read not found",
        "Tool Write not found",
        "Tool update_plan not found",
        "not found in agent",
    ]
    return not any(marker in output for marker in external_or_runner_errors)


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
        if not is_complete_runner_result(data):
            continue
        repo = str(data.get("repo") or "")
        statement_id = str(data.get("statement_id") or "")
        trace_file = str(data.get("trace_file") or data.get("trace") or "")
        if repo and statement_id and trace_file:
            keys.add((repo, statement_id, trace_file))
    return keys


def selected_runner_files(
    paths: list[Path],
    *,
    systems: tuple[str, ...],
    expected: set[tuple[str, str, str]],
    model_name: str,
) -> list[Path]:
    latest: dict[tuple[str, str, str, str], tuple[Path, float]] = {}
    system_set = set(systems)
    for root in paths:
        if not root.exists():
            continue
        for result in root.glob("**/results/*.json"):
            data = load_json_result(result)
            if not data:
                continue
            system = str(data.get("system") or "")
            if system not in system_set or data.get("model") != model_name:
                continue
            if not is_complete_runner_result(data):
                continue
            trace_key = (
                str(data.get("repo") or ""),
                str(data.get("statement_id") or ""),
                str(data.get("trace_file") or data.get("trace") or ""),
            )
            if trace_key not in expected:
                continue
            key = (system, *trace_key)
            mtime = result.stat().st_mtime
            previous = latest.get(key)
            if previous is None or mtime > previous[1]:
                latest[key] = (result, mtime)
    return [path for path, _ in sorted(latest.values(), key=lambda item: str(item[0]))]


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
    cmd = module_cmd("docker_agent_sdk_eval", [
        "--image",
        config.image,
        "--out-dir",
        str(system_out),
        "--system",
        system,
        "--base-url",
        config.agent_base_url,
        "--model-name",
        config.model_name,
        "--api-key-env",
        args.api_key_env,
        "--request-timeout",
        str(config.request_timeout),
        "--max-steps",
        str(args.max_steps if args.max_steps is not None else config.max_steps),
    ])
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
        "--judge-backend",
        choices=("remote", "llama"),
        default="remote",
        help="Judge backend. 'llama' starts local llama.cpp inside run_eval.py.",
    )
    parser.add_argument(
        "--judge-input-list",
        type=Path,
        action="append",
        default=[],
        help="Judge and summarize existing runner results from this newline-delimited list.",
    )
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
    parser.add_argument(
        "--judge-workers",
        type=int,
        help="Run LLM judge requests in parallel. Default: 1 for remote, 3 for llama.cpp.",
    )
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        help="Override judge max_tokens. Defaults to 16384 for llama.cpp and unset for remote.",
    )
    parser.add_argument(
        "--judge-sleep-between",
        type=float,
        help="Override seconds to wait between judge request submissions.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = CONFIGS[args.config]
    judge_only = bool(args.judge_input_list)
    judge_workers = args.judge_workers
    if judge_workers is None:
        judge_workers = 3 if args.judge_backend == "llama" else 1

    if (not judge_only or args.judge_backend == "remote") and args.api_key_env not in os.environ:
        print(f"{args.api_key_env} is not set", file=sys.stderr)
        return 2
    if args.workers < 1:
        print("--workers must be >= 1", file=sys.stderr)
        return 2
    if args.max_steps is not None and args.max_steps < 0:
        print("--max-steps must be >= 0", file=sys.stderr)
        return 2
    if judge_workers < 1:
        print("--judge-workers must be >= 1", file=sys.stderr)
        return 2
    if args.judge_max_tokens is not None and args.judge_max_tokens < 1:
        print("--judge-max-tokens must be >= 1", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (DEFAULT_OUT_BASE / config.out_name / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    env = os.environ.copy()

    judge_model = config.judge_model_name
    judge_dir = judge_dir_name(judge_model)
    judge_base_url = config.judge_base_url
    judge_thinking = config.judge_thinking
    judge_timeout = config.judge_timeout
    judge_batch_size = config.judge_batch_size
    judge_max_tokens = args.judge_max_tokens
    judge_sleep_between = (
        args.judge_sleep_between
        if args.judge_sleep_between is not None
        else (0.0 if judge_workers > 1 else config.judge_sleep_between)
    )

    if judge_only:
        try:
            result_lists = input_list_paths(args.judge_input_list)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n\n## runner phase\n")
            log.write("skip runner phase: --judge-input-list was provided\n")
            for path in result_lists:
                log.write(f"input-list: {rel(path)}\n")
    else:
        validate_cmd = module_cmd("validate_trace_artifacts", [
            "--root",
            str(config.root),
            "--fail-on-invalid",
        ])
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

        result_files = selected_runner_files(
            result_dirs,
            systems=config.systems,
            expected=expected,
            model_name=config.model_name,
        )
        expected_runner_files = expected_results * len(config.systems)
        if len(result_files) < expected_runner_files:
            print(
                f"Only found {len(result_files)}/{expected_runner_files} runner files "
                f"for selected traces.",
                file=sys.stderr,
            )
            return 1

        result_lists = [write_result_list(out_dir, result_files)]

    llama_server: LlamaServer | None = None
    if args.judge_backend == "llama":
        llama_server = LlamaServer(
            judge_json=True,
            restart_existing=True,
            log_path=out_dir / "llama-judge-server.log",
        )
        judge_model = llama_server.model_name()
        judge_dir = LLAMA_JUDGE_DIR
        judge_base_url = f"{llama_server.base_url}/v1"
        judge_thinking = "default"
        judge_timeout = LLAMA_JUDGE_TIMEOUT
        judge_batch_size = 1
        if judge_max_tokens is None:
            judge_max_tokens = LLAMA_JUDGE_MAX_TOKENS
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n\n## managed llama.cpp judge\n")
            log.write("+ " + " ".join(llama_server.command()) + "\n")
            log.write(f"judge-workers: {judge_workers}\n")
            log.write(f"judge-max-tokens: {judge_max_tokens}\n")
            log.write(f"judge-dir-name: {judge_dir}\n")

    judge_cmd = module_cmd("judge_trajectory", [
        "--source-model",
        config.model_name,
        "--judge-dir-name",
        judge_dir,
        "--base-url",
        judge_base_url,
        "--model-name",
        judge_model,
        "--thinking",
        judge_thinking,
        "--api-key-env",
        args.api_key_env,
        "--timeout",
        str(judge_timeout),
        "--retries",
        str(config.judge_retries),
        "--retry-sleep",
        str(config.judge_retry_sleep),
        "--retry-sleep-max",
        str(config.judge_retry_sleep_max),
        "--rate-limit-cooldown",
        str(config.judge_rate_limit_cooldown),
        "--sleep-between",
        str(judge_sleep_between),
        "--workers",
        str(judge_workers),
        "--batch-size",
        str(judge_batch_size),
    ])
    for result_list in result_lists:
        judge_cmd.extend(["--input-list", str(result_list)])
    if judge_max_tokens is not None:
        judge_cmd.extend(["--max-tokens", str(judge_max_tokens)])
    try:
        if llama_server is not None:
            llama_server.start(timeout=LLAMA_START_TIMEOUT)
        if run_phase("judge trajectories", judge_cmd, env=env, log_path=log_path).returncode != 0:
            return 1
    finally:
        if llama_server is not None:
            llama_server.stop()

    summary_cmd = module_cmd("summarize_agent_sdk_results", [
        "--source-model",
        config.model_name,
        "--judge-dir-name",
        judge_dir,
    ])
    for result_list in result_lists:
        summary_cmd.extend(["--input-list", str(result_list)])
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
