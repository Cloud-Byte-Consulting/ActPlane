#!/usr/bin/env python3
"""Run the RQ1 evaluation end to end.

Paper-facing entrypoint:

    python3 docs/eval_scripts/run_eval.py --config full

The script validates the corpus, runs the selected systems in Docker COW,
judges trajectories, and prints the final Decision Compliance Rate table.
"""

from __future__ import annotations

import argparse
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
CORPUS_ROOT = ROOT / "docs" / "corpus-test"
OUT_BASE = ROOT / "docs" / "eval_runs"

IMAGE = "actplane-rq1-agent-sdk:latest"
AGENT_MAX_STEPS = 5
LLAMA_API_KEY_ENV = "LLAMA_API_KEY"
LLAMA_START_TIMEOUT = 360.0
LLAMA_JUDGE_DIR = "trajectory_judges_llama_cpp_guardrail_response"
LLAMA_JUDGE_WORKERS = 3
LLAMA_JUDGE_MAX_TOKENS = 16384
LLAMA_JUDGE_TIMEOUT = 1800.0

REMOTE_GLM_API_KEY_ENV = "GLM_API_KEY"
REMOTE_GLM_MODEL_NAME = "glm-4.7-flash"
REMOTE_GLM_AGENT_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
REMOTE_GLM_JUDGE_BASE_URL = "https://api.z.ai/api/paas/v4"
REMOTE_GLM_JUDGE_DIR = "trajectory_judges_glm_4_7_flash_guardrail_response"
REMOTE_GLM_JUDGE_WORKERS = 1
REMOTE_GLM_JUDGE_TIMEOUT = 180.0

REMOTE_DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
REMOTE_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
REMOTE_DEEPSEEK_DEFAULT_MODEL_NAME = "deepseek-v4-pro"
REMOTE_DEEPSEEK_JUDGE_WORKERS = 1
REMOTE_DEEPSEEK_JUDGE_TIMEOUT = 300.0


@dataclass(frozen=True)
class EvalConfig:
    systems: tuple[str, ...]
    out_name: str


CONFIGS = {
    "prompt-filter": EvalConfig(("prompt-filter",), "prompt-filter"),
    "baseline": EvalConfig(("prompt-filter", "tool-regex"), "baseline"),
    "actplane": EvalConfig(("actplane", "actplane-opaque"), "actplane"),
    "full": EvalConfig(("prompt-filter", "tool-regex", "actplane", "actplane-opaque"), "full"),
}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_env_file(env: dict[str, str], path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in env:
            env[key] = value


def safe_judge_dir(prefix: str, model_name: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in model_name.lower()).strip("_")
    return f"trajectory_judges_{prefix}_{safe}_guardrail_response"


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
    if returncode != 0:
        print(f"{name} failed with rc={returncode}. See {rel(log_path)}.", file=sys.stderr)
        if stdout.strip():
            print(stdout[-4000:], file=sys.stderr)
    return result


def module_cmd(module: str, args: list[str]) -> list[str]:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
        f"from {module} import cli_main; "
        "raise SystemExit(cli_main(sys.argv[1:]))"
    )
    return [sys.executable, "-c", code, *args]


def manifest_trace_files(statement_dir: Path) -> list[Path]:
    manifest_path = statement_dir / "statement.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing statement manifest: {rel(manifest_path)}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    trace_names = manifest.get("trace_files")
    if not isinstance(trace_names, list) or not trace_names:
        raise ValueError(f"statement manifest has no trace_files: {rel(manifest_path)}")

    traces: list[Path] = []
    for name in trace_names:
        if not isinstance(name, str) or "/" in name or name.startswith("."):
            raise ValueError(f"invalid trace file in {rel(manifest_path)}: {name!r}")
        trace = statement_dir / name
        if not trace.exists():
            raise FileNotFoundError(f"manifest trace not found: {rel(trace)}")
        traces.append(trace)
    return traces


def trace_jobs(limit: int | None) -> list[tuple[Path, Path, tuple[str, str, str]]]:
    jobs: list[tuple[Path, Path, tuple[str, str, str]]] = []
    for rule in sorted(CORPUS_ROOT.glob("*/*/rule.yaml")):
        statement_dir = rule.parent
        repo = statement_dir.parent.name.replace("__", "/")
        statement_id = statement_dir.name
        for trace in manifest_trace_files(statement_dir):
            jobs.append((statement_dir, trace, (repo, statement_id, trace.name)))
    return jobs[:limit] if limit is not None else jobs


def load_result(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def is_complete_runner_result(data: dict) -> bool:
    if data.get("scorable") is False:
        return False
    if not isinstance(data.get("trace_records_snapshot"), list):
        return False
    if not isinstance(data.get("fixture_files_snapshot"), dict):
        return False
    output = str(data.get("agent_output") or "")
    if output.startswith("(setup error:"):
        return False
    incomplete_markers = [
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
    return not any(marker in output for marker in incomplete_markers)


def result_trace_key(data: dict) -> tuple[str, str, str]:
    return (
        str(data.get("repo") or ""),
        str(data.get("statement_id") or ""),
        str(data.get("trace_file") or data.get("trace") or ""),
    )


def complete_runner_keys(system_dir: Path, *, system: str, model_name: str) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    if not system_dir.exists():
        return keys
    for path in system_dir.glob("**/results/*.json"):
        data = load_result(path)
        if not data:
            continue
        if data.get("system") == system and data.get("model") == model_name and is_complete_runner_result(data):
            keys.add(result_trace_key(data))
    return keys


def select_runner_files(
    system_dirs: list[Path],
    *,
    systems: tuple[str, ...],
    expected: set[tuple[str, str, str]],
    model_name: str,
) -> list[Path]:
    latest: dict[tuple[str, str, str, str], tuple[Path, float]] = {}
    for system_dir in system_dirs:
        if not system_dir.exists():
            continue
        for path in system_dir.glob("**/results/*.json"):
            data = load_result(path)
            if not data:
                continue
            system = str(data.get("system") or "")
            trace_key = result_trace_key(data)
            if system not in systems or trace_key not in expected:
                continue
            if data.get("model") != model_name or not is_complete_runner_result(data):
                continue
            key = (system, *trace_key)
            previous = latest.get(key)
            mtime = path.stat().st_mtime
            if previous is None or mtime > previous[1]:
                latest[key] = (path, mtime)
    return [path for path, _mtime in sorted(latest.values(), key=lambda item: str(item[0]))]


def write_result_list(out_dir: Path, result_files: list[Path]) -> Path:
    path = out_dir / "selected_runner_results.txt"
    path.write_text("".join(f"{rel(result)}\n" for result in result_files), encoding="utf-8")
    return path


def docker_eval_cmd(
    *,
    system: str,
    out_dir: Path,
    agent_base_url: str,
    model_name: str,
    api_key_env: str,
    limit: int | None,
    statement_dir: Path | None = None,
    trace: Path | None = None,
) -> list[str]:
    args = [
        "--image",
        IMAGE,
        "--no-build",
        "--out-dir",
        str(out_dir),
        "--system",
        system,
        "--base-url",
        agent_base_url,
        "--model-name",
        model_name,
        "--api-key-env",
        api_key_env,
        "--request-timeout",
        "120",
        "--max-steps",
        str(AGENT_MAX_STEPS),
        "--root",
        str(CORPUS_ROOT),
    ]
    if statement_dir is not None:
        args.extend(["--statement-dir", str(statement_dir)])
    if trace is not None:
        args.extend(["--trace", str(trace)])
    if limit is not None and statement_dir is None and trace is None:
        args.extend(["--limit", str(limit)])
    return module_cmd("docker_agent_sdk_eval", args)


def run_systems(
    *,
    config: EvalConfig,
    out_dir: Path,
    jobs: list[tuple[Path, Path, tuple[str, str, str]]],
    agent_base_url: str,
    model_name: str,
    api_key_env: str,
    limit: int | None,
    env: dict[str, str],
    log_path: Path,
) -> list[Path] | None:
    job_by_key = {key: (statement_dir, trace) for statement_dir, trace, key in jobs}
    expected = set(job_by_key)
    scope_statement_dir: Path | None = None
    scope_trace: Path | None = None
    if len(jobs) == 1:
        scope_statement_dir, scope_trace, _key = jobs[0]
    else:
        statement_dirs = {statement_dir for statement_dir, _trace, _key in jobs}
        if len(statement_dirs) == 1:
            candidate_statement_dir = next(iter(statement_dirs))
            requested = {trace.resolve() for _statement_dir, trace, _key in jobs}
            manifest = {trace.resolve() for trace in manifest_trace_files(candidate_statement_dir)}
            if requested == manifest:
                scope_statement_dir = candidate_statement_dir

    system_dirs: list[Path] = []
    for system in config.systems:
        system_out = out_dir / system
        system_dirs.append(system_out)
        complete = complete_runner_keys(system_out, system=system, model_name=model_name)
        complete_expected = complete & expected
        missing = sorted(expected - complete_expected)
        if not missing:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\n\n## run {system}\n"
                    f"skip existing runner results: {len(complete_expected)}/{len(expected)}\n"
                )
            continue

        if not complete_expected:
            cmd = docker_eval_cmd(
                system=system,
                out_dir=system_out,
                agent_base_url=agent_base_url,
                model_name=model_name,
                api_key_env=api_key_env,
                limit=limit,
                statement_dir=scope_statement_dir,
                trace=scope_trace,
            )
            if run_phase(f"run {system}", cmd, env=env, log_path=log_path).returncode != 0:
                return None
        else:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\n\n## run {system}\n"
                    f"resume missing runner results: {len(missing)}/{len(expected)}\n"
                )
            for key in missing:
                statement_dir, trace = job_by_key[key]
                cmd = docker_eval_cmd(
                    system=system,
                    out_dir=system_out,
                    agent_base_url=agent_base_url,
                    model_name=model_name,
                    api_key_env=api_key_env,
                    limit=None,
                    statement_dir=statement_dir,
                    trace=trace,
                )
                phase = f"run {system} {key[0]}#{key[1]} {key[2]}"
                if run_phase(phase, cmd, env=env, log_path=log_path).returncode != 0:
                    return None

    result_files = select_runner_files(
        system_dirs,
        systems=config.systems,
        expected=expected,
        model_name=model_name,
    )
    expected_count = len(expected) * len(config.systems)
    if len(result_files) < expected_count:
        print(f"Only found {len(result_files)}/{expected_count} complete runner files.", file=sys.stderr)
        return None
    return result_files


def build_image(env: dict[str, str], log_path: Path) -> int:
    cmd = [
        "docker",
        "build",
        "-f",
        str(SCRIPT_DIR / "Dockerfile.agent-sdk"),
        "-t",
        IMAGE,
        str(SCRIPT_DIR),
    ]
    return run_phase("build docker image", cmd, env=env, log_path=log_path).returncode


def validate_traces(env: dict[str, str], log_path: Path) -> int:
    cmd = module_cmd("validate_trace_artifacts", ["--root", str(CORPUS_ROOT), "--fail-on-invalid"])
    return run_phase("validate traces", cmd, env=env, log_path=log_path).returncode


def judge_and_summarize(
    *,
    result_list: Path,
    judge_base_url: str,
    judge_model: str,
    judge_dir: str,
    judge_timeout: float,
    judge_workers: int,
    judge_max_tokens: int | None,
    api_key_env: str,
    env: dict[str, str],
    log_path: Path,
) -> int:
    judge_cmd = module_cmd("judge_trajectory", [
        "--judge-dir-name",
        judge_dir,
        "--base-url",
        judge_base_url,
        "--model-name",
        judge_model,
        "--api-key-env",
        api_key_env,
        "--timeout",
        str(judge_timeout),
        "--retries",
        "8",
        "--retry-sleep",
        "30",
        "--retry-sleep-max",
        "60",
        "--workers",
        str(judge_workers),
        "--input-list",
        str(result_list),
    ])
    if judge_max_tokens is not None:
        judge_cmd.extend(["--max-tokens", str(judge_max_tokens)])
    if run_phase("judge trajectories", judge_cmd, env=env, log_path=log_path).returncode != 0:
        return 1

    summary_cmd = module_cmd("summarize_agent_sdk_results", [
        "--judge-dir-name",
        judge_dir,
        "--input-list",
        str(result_list),
    ])
    summary = run_phase("summarize", summary_cmd, env=env, log_path=log_path)
    if summary.returncode != 0:
        return 1
    print(summary.stdout.strip())
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--limit", type=int, help="Smoke-test limit. Omit for the full corpus.")
    parser.add_argument("--statement-dir", type=Path, help="Run only one statement directory for trace tuning.")
    parser.add_argument("--trace", type=Path, help="Run only one trace file for trace tuning.")
    parser.add_argument("--remote-glm", action="store_true", help="Use remote GLM instead of local llama.cpp.")
    parser.add_argument(
        "--remote-deepseek",
        action="store_true",
        help="Use DeepSeek's OpenAI-compatible API instead of local llama.cpp.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = CONFIGS[args.config]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (OUT_BASE / config.out_name / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    env = os.environ.copy()
    load_env_file(env, ROOT / ".env")

    if args.remote_glm and args.remote_deepseek:
        print("--remote-glm and --remote-deepseek are mutually exclusive", file=sys.stderr)
        return 2

    if args.trace and not args.statement_dir:
        args.statement_dir = args.trace.parent
    if args.statement_dir:
        if args.trace:
            trace = args.trace
            if not trace.is_absolute() and trace.parent == Path("."):
                trace = args.statement_dir / trace
            traces = [trace]
        else:
            traces = manifest_trace_files(args.statement_dir)
        jobs = [
            (
                args.statement_dir,
                trace,
                (
                    args.statement_dir.parent.name.replace("__", "/"),
                    args.statement_dir.name,
                    trace.name,
                ),
            )
            for trace in traces
        ]
    else:
        jobs = trace_jobs(args.limit)
    expected = {key for _statement_dir, _trace, key in jobs}
    if not expected:
        print("No trace scenarios found.", file=sys.stderr)
        return 1

    if validate_traces(env, log_path) != 0 or build_image(env, log_path) != 0:
        return 1

    if args.remote_deepseek:
        if REMOTE_DEEPSEEK_API_KEY_ENV not in env:
            print(f"{REMOTE_DEEPSEEK_API_KEY_ENV} is not set", file=sys.stderr)
            return 2
        deepseek_base_url = env.get("DEEPSEEK_BASE_URL") or REMOTE_DEEPSEEK_DEFAULT_BASE_URL
        deepseek_model = env.get("DEEPSEEK_MODEL") or REMOTE_DEEPSEEK_DEFAULT_MODEL_NAME
        result_files = run_systems(
            config=config,
            out_dir=out_dir,
            jobs=jobs,
            agent_base_url=deepseek_base_url,
            model_name=deepseek_model,
            api_key_env=REMOTE_DEEPSEEK_API_KEY_ENV,
            limit=args.limit,
            env=env,
            log_path=log_path,
        )
        if result_files is None:
            return 1
        result_list = write_result_list(out_dir, result_files)
        rc = judge_and_summarize(
            result_list=result_list,
            judge_base_url=deepseek_base_url,
            judge_model=deepseek_model,
            judge_dir=safe_judge_dir("deepseek", deepseek_model),
            judge_timeout=REMOTE_DEEPSEEK_JUDGE_TIMEOUT,
            judge_workers=REMOTE_DEEPSEEK_JUDGE_WORKERS,
            judge_max_tokens=None,
            api_key_env=REMOTE_DEEPSEEK_API_KEY_ENV,
            env=env,
            log_path=log_path,
        )
    elif args.remote_glm:
        if REMOTE_GLM_API_KEY_ENV not in env:
            print(f"{REMOTE_GLM_API_KEY_ENV} is not set", file=sys.stderr)
            return 2
        result_files = run_systems(
            config=config,
            out_dir=out_dir,
            jobs=jobs,
            agent_base_url=REMOTE_GLM_AGENT_BASE_URL,
            model_name=REMOTE_GLM_MODEL_NAME,
            api_key_env=REMOTE_GLM_API_KEY_ENV,
            limit=args.limit,
            env=env,
            log_path=log_path,
        )
        if result_files is None:
            return 1
        result_list = write_result_list(out_dir, result_files)
        rc = judge_and_summarize(
            result_list=result_list,
            judge_base_url=REMOTE_GLM_JUDGE_BASE_URL,
            judge_model=REMOTE_GLM_MODEL_NAME,
            judge_dir=REMOTE_GLM_JUDGE_DIR,
            judge_timeout=REMOTE_GLM_JUDGE_TIMEOUT,
            judge_workers=REMOTE_GLM_JUDGE_WORKERS,
            judge_max_tokens=None,
            api_key_env=REMOTE_GLM_API_KEY_ENV,
            env=env,
            log_path=log_path,
        )
    else:
        agent_server = LlamaServer(judge_json=False, restart_existing=True, log_path=out_dir / "llama-agent-server.log")
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n\n## managed llama.cpp agent\n")
            log.write("+ " + " ".join(agent_server.command()) + "\n")
        try:
            agent_server.start(timeout=LLAMA_START_TIMEOUT)
            source_model = agent_server.model_name()
            result_files = run_systems(
                config=config,
                out_dir=out_dir,
                jobs=jobs,
                agent_base_url=f"{agent_server.base_url}/v1",
                model_name=source_model,
                api_key_env=LLAMA_API_KEY_ENV,
                limit=args.limit,
                env=env,
                log_path=log_path,
            )
            if result_files is None:
                return 1
            result_list = write_result_list(out_dir, result_files)
        finally:
            agent_server.stop()

        judge_server = LlamaServer(judge_json=True, restart_existing=True, log_path=out_dir / "llama-judge-server.log")
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n\n## managed llama.cpp judge\n")
            log.write("+ " + " ".join(judge_server.command()) + "\n")
        try:
            judge_server.start(timeout=LLAMA_START_TIMEOUT)
            rc = judge_and_summarize(
                result_list=result_list,
                judge_base_url=f"{judge_server.base_url}/v1",
                judge_model=judge_server.model_name(),
                judge_dir=LLAMA_JUDGE_DIR,
                judge_timeout=LLAMA_JUDGE_TIMEOUT,
                judge_workers=LLAMA_JUDGE_WORKERS,
                judge_max_tokens=LLAMA_JUDGE_MAX_TOKENS,
                api_key_env=LLAMA_API_KEY_ENV,
                env=env,
                log_path=log_path,
            )
        finally:
            judge_server.stop()

    if rc != 0:
        return rc
    print()
    print(f"Results: {rel(out_dir)}")
    print(f"Log: {rel(log_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
