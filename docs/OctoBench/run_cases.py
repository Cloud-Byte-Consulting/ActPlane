#!/usr/bin/env python3
"""Run OctoBench cases under baseline, tool-regex, or ActPlane conditions.

The baseline condition calls upstream mini-vela's benchmark_runner.py directly.
The enforcement conditions keep upstream mini-vela unchanged, reuse its scaffold
builders, and change only where the case-specific policy is enforced.
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
DEFAULT_DATASET = ROOT / "data" / "selected_cases.jsonl"
DEFAULT_VENV = Path("/tmp/octobench-litellm-venv")
DEFAULT_ACTPLANE = ROOT.parents[1] / "target" / "release" / "actplane"
DEFAULT_POLICY_ROOT = ROOT / "policies"
DEFAULT_LITELLM_CONFIG = ROOT / "configs" / "litellm_llama_cpp.yaml"
TOOL_REGEX_HOOK = ROOT / "tool_regex_hook.py"
ACTPLANE_FEEDBACK_HOOK = ROOT / "actplane_feedback_hook.py"
INSTANCE_ID_FILE = Path("/tmp/current_instance_id.txt")
CONDITIONS = ("baseline", "tool-regex", "actplane", "actplane-feedback")

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


def stop_process_tree_with_signal(proc: subprocess.Popen, sig: int, grace_s: int = 10) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        return

    deadline = time.time() + grace_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.5)
    kill_process_tree(proc, grace_s=2)


def run_proxy_main(config_path: Path, port: int) -> None:
    proxy_dir = MINI_VELA / "proxy"
    sys.path.insert(0, str(proxy_dir))
    os.chdir(proxy_dir)

    import litellm  # noqa: PLC0415
    from trajectory_logger import trajectory_logger_instance  # noqa: PLC0415

    litellm.callbacks.append(trajectory_logger_instance)

    print("=" * 60)
    print("[run_cases proxy] registered upstream TrajectoryLogger callback")
    print(f"[run_cases proxy] trajectory dir: {trajectory_logger_instance.output_dir}")
    print(f"[run_cases proxy] config: {config_path}")
    print(f"[run_cases proxy] port: {port}")
    print("=" * 60)

    sys.argv = [
        "litellm",
        "--config",
        str(config_path),
        "--port",
        str(port),
    ]

    from litellm.proxy.proxy_cli import run_server  # noqa: PLC0415

    run_server()


def start_proxy(venv: Path, log_path: Path, config_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{venv / 'bin'}:{env.get('PATH', '')}"
    proc = subprocess.Popen(
        [str(venv / "bin" / "python"), str(ROOT / "run_cases.py"), "__proxy__", str(config_path), "4000"],
        cwd=ROOT,
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


def start_actplane_watch(actplane: Path, policy_path: Path, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(actplane), "--policy", str(policy_path), "watch"],
        cwd=ROOT.parents[1],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )

    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"ActPlane watch exited early; see {log_path}")
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            text = ""
        if "ActPlane: watching with feedback file" in text:
            return proc
        time.sleep(0.5)
    stop_process_tree_with_signal(proc, signal.SIGINT)
    raise RuntimeError(f"ActPlane watch did not become ready; see {log_path}")


def reset_mini_vela_results(instance_id: str) -> Path:
    mini_results = MINI_VELA / "results"
    run_results = mini_results / "run_results.json"
    if run_results.exists():
        run_results.unlink()

    trajectory = mini_results / "trajectories" / f"{instance_id}.jsonl"
    if trajectory.exists():
        trajectory.unlink()

    (mini_results / "trajectories").mkdir(parents=True, exist_ok=True)
    return mini_results


def archive_mini_vela_results(mini_results: Path, case_dir: Path, instance_id: str) -> list[str]:
    if not mini_results.exists():
        return []

    archive = case_dir / "mini-vela-results"
    if archive.exists():
        shutil.rmtree(archive)
    (archive / "trajectories").mkdir(parents=True, exist_ok=True)

    run_results = mini_results / "run_results.json"
    if run_results.exists():
        shutil.copy2(run_results, archive / "run_results.json")

    trajectory = mini_results / "trajectories" / f"{instance_id}.jsonl"
    if trajectory.exists():
        shutil.copy2(trajectory, archive / "trajectories" / trajectory.name)

    return sorted(str(path) for path in (archive / "trajectories").glob(f"{instance_id}.jsonl"))


def parse_official_case_result(instance_id: str) -> dict[str, Any] | None:
    result_path = MINI_VELA / "results" / "run_results.json"
    if not result_path.exists():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    for item in payload:
        if isinstance(item, dict) and item.get("instance_id") == instance_id:
            return item
    return None


def case_policy_path(policy_root: Path, condition: str, instance_id: str) -> Path:
    if condition == "tool-regex":
        return policy_root / "tool-regex" / f"{instance_id}.json"
    if condition in {"actplane", "actplane-feedback"}:
        return policy_root / condition / f"{instance_id}.yaml"
    raise ValueError(f"condition has no policy file: {condition}")


def tool_regex_hook_setup_script() -> str:
    hook_settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "python3 /tmp/tool_regex_hook.py "
                                "--policy /tmp/tool-regex-policy.json "
                                "--events /tmp/tool-regex-events.jsonl"
                            ),
                        }
                    ],
                }
            ],
        }
    }
    payload = json.dumps(hook_settings, ensure_ascii=False)
    return "mkdir -p ~/.claude && printf %s " + shlex.quote(payload) + " > ~/.claude/settings.local.json"


def actplane_feedback_hook_setup_script() -> str:
    hook_settings = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /tmp/actplane_feedback_hook.py",
                        }
                    ],
                }
            ],
            "PostToolUseFailure": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 /tmp/actplane_feedback_hook.py",
                        }
                    ],
                }
            ],
        }
    }
    payload = json.dumps(hook_settings, ensure_ascii=False)
    return "mkdir -p ~/.claude && printf %s " + shlex.quote(payload) + " > ~/.claude/settings.local.json"


def build_plain_container_command(
    case: dict[str, Any],
    proxy_url: str,
    model: str,
) -> tuple[str, list[str], dict[str, str]]:
    scaffold_name = case.get("scaffold", {}).get("name", "claudecode")
    scaffold = get_scaffold(scaffold_name)
    setup_script = scaffold.get_setup_script(proxy_url, model=model)
    task_commands = scaffold.build_commands(
        case["user_query"],
        case.get("system_prompt", ""),
        model=model,
    )

    commands = [setup_script] + task_commands
    return " && ".join(commands), task_commands, scaffold.get_docker_env(proxy_url, model=model)


def build_tool_regex_container_command(
    case: dict[str, Any],
    proxy_url: str,
    model: str,
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
    if scaffold_name == "claudecode":
        commands.append(tool_regex_hook_setup_script())
    commands.extend(task_commands)
    return " && ".join(commands), task_commands, scaffold.get_docker_env(proxy_url, model=model)


def build_actplane_feedback_container_command(
    case: dict[str, Any],
    proxy_url: str,
    model: str,
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
    if scaffold_name == "claudecode":
        commands.append(actplane_feedback_hook_setup_script())
    commands.extend(task_commands)

    env_vars = scaffold.get_docker_env(proxy_url, model=model)
    env_vars["ACTPLANE_FEEDBACK_FILE"] = "/tmp/actplane-feedback/last-violation.txt"
    env_vars["ACTPLANE_HOOK_STATE"] = "/tmp/actplane-feedback-hook.state.json"
    return " && ".join(commands), task_commands, env_vars


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
    official_result = parse_official_case_result(instance_id)
    official_success = official_result.get("success") if official_result else None
    return {
        "instance_id": instance_id,
        "condition": args.condition,
        "returncode": proc.returncode,
        "process_success": proc.returncode == 0,
        "official_success": official_success,
        "official_result": official_result,
        "success": proc.returncode == 0 and official_success is True,
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
    policy_path = case_policy_path(args.policy_root, args.condition, instance_id)
    INSTANCE_ID_FILE.write_text(instance_id, encoding="utf-8")

    if args.condition == "actplane-feedback":
        full_command, task_commands, env_vars = build_actplane_feedback_container_command(
            case=case,
            proxy_url=proxy_url,
            model=args.model,
        )
    else:
        full_command, task_commands, env_vars = build_plain_container_command(
            case=case,
            proxy_url=proxy_url,
            model=args.model,
        )

    container_name = f"octobench-{args.condition}-{instance_id[:36]}-{int(time.time())}"
    feedback_dir = ROOT.parents[1] / ".actplane"
    if args.condition == "actplane-feedback":
        feedback_dir.mkdir(parents=True, exist_ok=True)
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
        "--name",
        container_name,
        "--add-host=host.docker.internal:host-gateway",
    ]
    if args.condition == "actplane-feedback":
        docker_cmd.extend(
            [
                "-v",
                f"{ACTPLANE_FEEDBACK_HOOK}:/tmp/actplane_feedback_hook.py:ro",
                "-v",
                f"{feedback_dir}:/tmp/actplane-feedback:ro",
            ]
        )
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
            "policy": str(policy_path),
            "actplane": str(args.actplane),
            "actplane_mode": "host-watch",
            "feedback_hook": str(ACTPLANE_FEEDBACK_HOOK)
            if args.condition == "actplane-feedback"
            else None,
            "task_commands": task_commands,
            "docker_command": docker_cmd,
            "trajectory_session_id": instance_id,
        },
    )

    started = time.time()
    watch = start_actplane_watch(args.actplane, policy_path, case_dir / "actplane-watch.log")
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
        }
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
    finally:
        stop_process_tree_with_signal(watch, signal.SIGINT)

    (case_dir / "stdout.txt").write_text(stdout or "", encoding="utf-8")
    (case_dir / "stderr.txt").write_text(stderr or "", encoding="utf-8")
    return result


def run_tool_regex_case(
    case: dict[str, Any],
    args: argparse.Namespace,
    case_dir: Path,
) -> dict[str, Any]:
    instance_id = case["instance_id"]
    scaffold_name = case.get("scaffold", {}).get("name", "claudecode")
    proxy_url = "http://host.docker.internal:4000"
    policy_path = case_policy_path(args.policy_root, "tool-regex", instance_id)
    events_file = case_dir / "tool_regex_events.jsonl"
    events_file.touch()
    INSTANCE_ID_FILE.write_text(instance_id, encoding="utf-8")

    full_command, task_commands, env_vars = build_tool_regex_container_command(
        case=case,
        proxy_url=proxy_url,
        model=args.model,
    )

    container_name = f"octobench-tool-regex-{instance_id[:36]}-{int(time.time())}"
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
        "--name",
        container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{TOOL_REGEX_HOOK}:/tmp/tool_regex_hook.py:ro",
        "-v",
        f"{policy_path}:/tmp/tool-regex-policy.json:ro",
        "-v",
        f"{events_file}:/tmp/tool-regex-events.jsonl",
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
            "policy": str(policy_path),
            "hook": str(TOOL_REGEX_HOOK),
            "events_file": str(events_file),
            "task_commands": task_commands,
            "docker_command": docker_cmd,
            "trajectory_session_id": instance_id,
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

    mini_results = reset_mini_vela_results(instance_id)
    proxy = start_proxy(args.venv, case_dir / "proxy.log", args.litellm_config)
    try:
        if args.condition == "baseline":
            result = run_baseline_case(case, args, case_dir)
        elif args.condition == "tool-regex":
            result = run_tool_regex_case(case, args, case_dir)
        else:
            result = run_actplane_case(case, args, case_dir)
    finally:
        kill_process_tree(proxy)

    trajectories = archive_mini_vela_results(mini_results, case_dir, instance_id)
    result["trajectory_files"] = trajectories
    result["trajectory_count"] = len(trajectories)
    result["scorable"] = len(trajectories) == 1
    if not result["scorable"]:
        result["success"] = False
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
    parser.add_argument("--policy-root", type=Path, default=DEFAULT_POLICY_ROOT)
    parser.add_argument("--actplane", type=Path, default=DEFAULT_ACTPLANE)
    parser.add_argument("--litellm-config", type=Path, default=DEFAULT_LITELLM_CONFIG)
    parser.add_argument("--managed-llama", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    return parser.parse_args()


def normalize_and_validate_args(args: argparse.Namespace) -> None:
    args.dataset = args.dataset.resolve()
    args.venv = args.venv.resolve()
    args.policy_root = args.policy_root.resolve()
    args.actplane = args.actplane.resolve()
    args.litellm_config = args.litellm_config.resolve()
    args.out_dir = args.out_dir.resolve()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    if not (args.venv / "bin" / "python").exists():
        raise SystemExit(f"venv python not found: {args.venv / 'bin' / 'python'}")
    if not args.litellm_config.exists():
        raise SystemExit(f"LiteLLM config not found: {args.litellm_config}")
    if args.condition in {"tool-regex", "actplane", "actplane-feedback"} and not args.policy_root.exists():
        raise SystemExit(f"policy root not found: {args.policy_root}")
    if args.condition == "tool-regex" and not TOOL_REGEX_HOOK.exists():
        raise SystemExit(f"tool-regex hook not found: {TOOL_REGEX_HOOK}")
    if args.condition == "actplane-feedback" and not ACTPLANE_FEEDBACK_HOOK.exists():
        raise SystemExit(f"ActPlane feedback hook not found: {ACTPLANE_FEEDBACK_HOOK}")
    if args.condition in {"actplane", "actplane-feedback"}:
        if not args.actplane.exists():
            raise SystemExit(f"actplane binary not found: {args.actplane}")


def main() -> int:
    args = parse_args()
    normalize_and_validate_args(args)
    cases = load_cases(args.dataset, args.limit, args.case)
    for case in cases:
        if args.condition in {"tool-regex", "actplane", "actplane-feedback"}:
            policy_path = case_policy_path(args.policy_root, args.condition, case["instance_id"])
            if not policy_path.exists():
                raise SystemExit(f"policy not found for {case['instance_id']}: {policy_path}")

    run_dir = args.out_dir / args.condition / f"{args.condition}-isolated-{utc_stamp()}"
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
            "policy_root": str(args.policy_root) if args.condition != "baseline" else None,
            "actplane": str(args.actplane)
            if args.condition in {"actplane", "actplane-feedback"}
            else None,
            "litellm_config": str(args.litellm_config),
            "managed_llama": args.managed_llama,
            "n_ctx": 128000,
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
    if len(sys.argv) >= 2 and sys.argv[1] == "__proxy__":
        if len(sys.argv) != 4:
            raise SystemExit("usage: run_cases.py __proxy__ <litellm-config> <port>")
        run_proxy_main(Path(sys.argv[2]).resolve(), int(sys.argv[3]))
        raise SystemExit(0)
    raise SystemExit(main())
