#!/usr/bin/env python3
"""Run OctoBench cases under baseline or ActPlane conditions.

The baseline condition calls upstream mini-vela's benchmark_runner.py directly.
The ActPlane conditions keep upstream mini-vela unchanged, reuse its scaffold
builders, and wrap only the generated task command with ActPlane.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
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
EVAL_SCRIPTS = ROOT.parent / "eval_scripts"
DEFAULT_DATASET = ROOT / "data" / "actplane_selected3.jsonl"
DEFAULT_VENV = Path("/tmp/octobench-litellm-venv")
DEFAULT_ACTPLANE = ROOT.parents[1] / "collector" / "target" / "release" / "actplane"
DEFAULT_POLICY = ROOT / "policies" / "actplane-octobench-tuned-v2.yaml"
INSTANCE_ID_FILE = Path("/tmp/current_instance_id.txt")
CONDITIONS = ("baseline", "actplane", "actplane-feedback")

sys.path.insert(0, str(EVAL_SCRIPTS))
sys.path.insert(0, str(MINI_VELA))

from llama_server import LlamaServer  # noqa: E402
from scaffolds import DEFAULT_MODEL, get_scaffold  # noqa: E402


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cases(dataset: Path, limit: int | None, case_ids: list[str]) -> list[dict[str, Any]]:
    all_cases: list[dict[str, Any]] = []
    with dataset.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                all_cases.append(json.loads(line))

    if case_ids:
        by_id = {case["instance_id"]: case for case in all_cases}
        missing = [case_id for case_id in case_ids if case_id not in by_id]
        if missing:
            raise SystemExit(f"case not found in {dataset}: {', '.join(missing)}")
        selected = [by_id[case_id] for case_id in case_ids]
    else:
        selected = all_cases

    return selected[:limit] if limit is not None else selected


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


def reset_mini_vela_results() -> Path:
    mini_results = MINI_VELA / "results"
    if mini_results.exists():
        shutil.rmtree(mini_results)
    (mini_results / "trajectories").mkdir(parents=True, exist_ok=True)
    return mini_results


def archive_mini_vela_results(mini_results: Path, case_dir: Path) -> list[str]:
    if not mini_results.exists():
        return []

    archive = case_dir / "mini-vela-results"
    if archive.exists():
        shutil.rmtree(archive)
    shutil.copytree(mini_results, archive)
    return sorted(str(path) for path in (archive / "trajectories").glob("*.jsonl"))


def claude_feedback_hook_script() -> str:
    hook_settings = {
        "hooks": {
            "PostToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "actplane feedback-hook"}]}
            ],
            "PostToolUseFailure": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "actplane feedback-hook"}]}
            ],
        }
    }
    payload = json.dumps(hook_settings, ensure_ascii=False)
    return "mkdir -p ~/.claude && printf %s " + shlex.quote(payload) + " > ~/.claude/settings.local.json"


def build_actplane_container_command(
    case: dict[str, Any],
    proxy_url: str,
    model: str,
    policy_in_container: str,
    actplane_in_container: str,
    enable_feedback_hook: bool,
) -> tuple[str, list[str], dict[str, str]]:
    scaffold_name = case.get("scaffold", {}).get("name", "claudecode")
    scaffold = get_scaffold(scaffold_name)
    setup_script = scaffold.get_setup_script(proxy_url, model=model)
    task_commands = scaffold.build_commands(
        case["user_query"],
        case.get("system_prompt", ""),
        model=model,
    )

    commands = [setup_script]
    if enable_feedback_hook and scaffold_name == "claudecode":
        commands.append(claude_feedback_hook_script())

    actplane_prefix = (
        f"{shlex.quote(actplane_in_container)} "
        f"--policy {shlex.quote(policy_in_container)} "
        f"--run-as-root run"
    )
    for task_command in task_commands:
        commands.append(f"{actplane_prefix} bash -c {shlex.quote(task_command)}")

    return " && ".join(commands), task_commands, scaffold.get_docker_env(proxy_url, model=model)


def run_baseline_case(
    case: dict[str, Any],
    args: argparse.Namespace,
    case_dir: Path,
) -> dict[str, Any]:
    instance_id = case["instance_id"]
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
    write_json(case_dir / "command.json", {"cmd": cmd, "cwd": str(MINI_VELA)})

    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=MINI_VELA,
        env={**os.environ, "PATH": f"{args.venv / 'bin'}:{os.environ.get('PATH', '')}"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (case_dir / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (case_dir / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    return {
        "instance_id": instance_id,
        "condition": args.condition,
        "returncode": proc.returncode,
        "success": proc.returncode == 0,
        "elapsed_s": time.time() - started,
    }


def run_actplane_case(
    case: dict[str, Any],
    args: argparse.Namespace,
    case_dir: Path,
) -> dict[str, Any]:
    instance_id = case["instance_id"]
    scaffold_name = case.get("scaffold", {}).get("name", "claudecode")
    proxy_url = "http://host.docker.internal:4000"
    enable_feedback_hook = args.condition == "actplane-feedback"
    INSTANCE_ID_FILE.write_text(instance_id, encoding="utf-8")

    full_command, task_commands, env_vars = build_actplane_container_command(
        case=case,
        proxy_url=proxy_url,
        model=args.model,
        policy_in_container="/tmp/actplane-policy.yaml",
        actplane_in_container="/usr/local/bin/actplane",
        enable_feedback_hook=enable_feedback_hook,
    )

    container_name = f"octobench-{args.condition}-{instance_id[:36]}-{int(time.time())}"
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--name",
        container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{args.actplane}:/usr/local/bin/actplane:ro",
        "-v",
        f"{args.policy}:/tmp/actplane-policy.yaml:ro",
        "-v",
        "/sys/kernel/tracing:/sys/kernel/tracing",
        "-v",
        "/sys/kernel/debug:/sys/kernel/debug",
        "-v",
        "/sys/fs/bpf:/sys/fs/bpf",
    ]
    for key, value in env_vars.items():
        docker_cmd.extend(["-e", f"{key}={value}"])
    docker_cmd.extend(
        [
            "-w",
            case.get("workspace_abs_path", "/app"),
            case["image"],
            "bash",
            "-c",
            full_command,
        ]
    )

    write_json(
        case_dir / "command.json",
        {
            "condition": args.condition,
            "container_name": container_name,
            "scaffold": scaffold_name,
            "model": args.model,
            "image": case["image"],
            "workspace_abs_path": case.get("workspace_abs_path"),
            "proxy_url": proxy_url,
            "policy": str(args.policy),
            "actplane": str(args.actplane),
            "task_commands": task_commands,
            "docker_command": docker_cmd,
            "trajectory_session_id": instance_id,
            "feedback_hook": enable_feedback_hook,
        },
    )

    started = time.time()
    try:
        proc = subprocess.run(
            docker_cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=None if args.timeout == 0 else args.timeout,
        )
        result = {
            "instance_id": instance_id,
            "condition": args.condition,
            "returncode": proc.returncode,
            "success": proc.returncode == 0,
            "timeout": False,
            "elapsed_s": time.time() - started,
            "feedback_hook": enable_feedback_hook,
        }
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = {
            "instance_id": instance_id,
            "condition": args.condition,
            "returncode": None,
            "success": False,
            "timeout": True,
            "timeout_s": args.timeout,
            "elapsed_s": time.time() - started,
            "feedback_hook": enable_feedback_hook,
        }
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""

    (case_dir / "stdout.txt").write_text(stdout or "", encoding="utf-8")
    (case_dir / "stderr.txt").write_text(stderr or "", encoding="utf-8")
    return result


def run_case(case: dict[str, Any], index: int, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    instance_id = case["instance_id"]
    case_dir = run_dir / f"{index:02d}-{instance_id}"
    case_dir.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "case.json", case)

    mini_results = reset_mini_vela_results()
    proxy = start_proxy(args.venv, case_dir / "proxy.log")
    try:
        if args.condition == "baseline":
            result = run_baseline_case(case, args, case_dir)
        else:
            result = run_actplane_case(case, args, case_dir)
    finally:
        kill_process_tree(proxy)

    trajectories = archive_mini_vela_results(mini_results, case_dir)
    result["trajectory_files"] = trajectories
    result["trajectory_count"] = len(trajectories)
    write_json(case_dir / "result.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=CONDITIONS, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", action="append", default=[], help="Run only this instance_id. Can be repeated.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--actplane", type=Path, default=DEFAULT_ACTPLANE)
    parser.add_argument("--managed-llama", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    return parser.parse_args()


def normalize_and_validate_args(args: argparse.Namespace) -> None:
    args.dataset = args.dataset.resolve()
    args.venv = args.venv.resolve()
    args.policy = args.policy.resolve()
    args.actplane = args.actplane.resolve()
    args.out_dir = args.out_dir.resolve()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    if not (args.venv / "bin" / "python").exists():
        raise SystemExit(f"venv python not found: {args.venv / 'bin' / 'python'}")
    if args.condition != "baseline":
        if not args.policy.exists():
            raise SystemExit(f"policy not found: {args.policy}")
        if not args.actplane.exists():
            raise SystemExit(f"actplane binary not found: {args.actplane}")


def main() -> int:
    args = parse_args()
    normalize_and_validate_args(args)
    cases = load_cases(args.dataset, args.limit, args.case)
    feedback_hook = args.condition == "actplane-feedback"

    run_dir = args.out_dir / f"{args.condition}-isolated-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "metadata.json",
        {
            "condition": args.condition,
            "dataset": str(args.dataset),
            "case_ids": args.case,
            "limit": args.limit,
            "timeout_s": args.timeout,
            "model": args.model,
            "venv": str(args.venv),
            "policy": str(args.policy) if args.condition != "baseline" else None,
            "actplane": str(args.actplane) if args.condition != "baseline" else None,
            "managed_llama": args.managed_llama,
            "n_ctx": 128000,
            "feedback_hook": feedback_hook,
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
            print(f"[{index + 1}/{len(cases)}] {args.condition} {case['instance_id']}", flush=True)
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
