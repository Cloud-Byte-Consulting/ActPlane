#!/usr/bin/env python3
"""Run one OctoBench case with ActPlane wrapped around the scaffold command.

This does not modify mini-vela. It imports mini-vela's scaffold definitions,
uses their setup script and task command builder, then adds the ActPlane wrapper
needed by docs/eval_benchmarks.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MINI_VELA = ROOT / "mini-vela"
DEFAULT_DATASET = MINI_VELA / "data" / "octobench_first10.jsonl"
DEFAULT_POLICY = ROOT / "actplane-octobench-os.yaml"
DEFAULT_ACTPLANE = Path("/home/yunwei37/workspace/ActPlane/collector/target/release/actplane")
INSTANCE_ID_FILE = Path("/tmp/current_instance_id.txt")

sys.path.insert(0, str(MINI_VELA))
from scaffolds import DEFAULT_MODEL, get_scaffold  # noqa: E402


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_case(dataset: Path, instance_id: str) -> dict[str, Any]:
    with dataset.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            case = json.loads(line)
            if case.get("instance_id") == instance_id:
                return case
    raise SystemExit(f"case not found in {dataset}: {instance_id}")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def build_container_command(
    case: dict[str, Any],
    proxy_url: str,
    model: str,
    policy_in_container: str,
    actplane_in_container: str,
    enable_claude_hook: bool,
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
    if enable_claude_hook and scaffold_name == "claudecode":
        commands.append(claude_feedback_hook_script())

    actplane_prefix = (
        f"{shlex.quote(actplane_in_container)} "
        f"--policy {shlex.quote(policy_in_container)} "
        f"--run-as-root run"
    )
    for task_command in task_commands:
        commands.append(f"{actplane_prefix} bash -c {shlex.quote(task_command)}")

    return " && ".join(commands), task_commands, scaffold.get_docker_env(proxy_url, model=model)


def run_case(args: argparse.Namespace) -> int:
    case = load_case(args.dataset, args.case)
    scaffold_name = case.get("scaffold", {}).get("name", "claudecode")
    proxy_url = f"http://host.docker.internal:{args.proxy_port}"
    run_dir = args.out_dir.resolve() / f"actplane-{args.case}-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    case_id_for_trajectory = f"actplane-{args.case}"
    INSTANCE_ID_FILE.write_text(case_id_for_trajectory, encoding="utf-8")

    full_command, task_commands, env_vars = build_container_command(
        case=case,
        proxy_url=proxy_url,
        model=args.model,
        policy_in_container="/tmp/actplane-policy.yaml",
        actplane_in_container="/usr/local/bin/actplane",
        enable_claude_hook=args.claude_feedback_hook,
    )

    container_name = f"octobench-actplane-{args.case[:36]}-{int(time.time())}"
    subprocess.run(["docker", "rm", "-f", container_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--name",
        container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{args.actplane.resolve()}:/usr/local/bin/actplane:ro",
        "-v",
        f"{args.policy.resolve()}:/tmp/actplane-policy.yaml:ro",
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

    write_json(run_dir / "case.json", case)
    write_json(
        run_dir / "command.json",
        {
            "container_name": container_name,
            "scaffold": scaffold_name,
            "model": args.model,
            "image": case["image"],
            "workspace_abs_path": case.get("workspace_abs_path"),
            "proxy_url": proxy_url,
            "policy": str(args.policy.resolve()),
            "actplane": str(args.actplane.resolve()),
            "task_commands": task_commands,
            "docker_command": docker_cmd,
            "trajectory_session_id": case_id_for_trajectory,
            "claude_feedback_hook": args.claude_feedback_hook,
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
            "returncode": proc.returncode,
            "success": proc.returncode == 0,
            "timeout": False,
            "elapsed_s": time.time() - started,
        }
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = {
            "returncode": None,
            "success": False,
            "timeout": True,
            "timeout_s": args.timeout,
            "elapsed_s": time.time() - started,
        }
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""

    (run_dir / "stdout.txt").write_text(stdout or "", encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr or "", encoding="utf-8")
    write_json(run_dir / "result.json", result)
    print(json.dumps({"run_dir": str(run_dir), **result}, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--actplane", type=Path, default=DEFAULT_ACTPLANE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--proxy-port", type=int, default=4000)
    parser.add_argument("--timeout", type=int, default=3600, help="0 disables this wrapper timeout")
    parser.add_argument("--claude-feedback-hook", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results")
    return parser.parse_args()


def normalize_paths(args: argparse.Namespace) -> None:
    args.dataset = args.dataset.resolve()
    args.policy = args.policy.resolve()
    args.actplane = args.actplane.resolve()
    args.out_dir = args.out_dir.resolve()


if __name__ == "__main__":
    parsed_args = parse_args()
    normalize_paths(parsed_args)
    raise SystemExit(run_case(parsed_args))
