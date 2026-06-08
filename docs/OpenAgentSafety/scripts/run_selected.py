#!/usr/bin/env python3
"""Run selected OpenAgentSafety smoke cases with local llama.cpp/Qwen.

The script is intentionally small. It delegates task execution and scoring to
the official OpenAgentSafety `evaluation/run_eval.py`, and optionally wraps each
case with host-side ActPlane watch for OS-evidence collection.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
OFFICIAL = ROOT / "OpenAgentSafety"
DEFAULT_CONFIG = ROOT / "configs" / "openhands_local_llama_config.toml"
DEFAULT_PATCH = ROOT / "patches" / "local-llama-openhands.patch"
DEFAULT_ACTPLANE = REPO_ROOT / "target" / "release" / "actplane"
DEFAULT_OUTPUT = ROOT / "results"
EVAL_SCRIPTS = REPO_ROOT / "docs" / "eval_scripts"
CONDITIONS = ("baseline", "actplane")
LOCAL_MODEL = "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf"
OFFICIAL_BASE_IMAGE = "ghcr.io/theagentcompany/task-base-image:1.0.0"
OFFICIAL_TASK_IMAGE = "ghcr.io/theagentcompany/{task_id}-image:{version}"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def task_dependencies(task_path: Path) -> list[str]:
    deps_path = task_path / "utils" / "dependencies.yml"
    if not deps_path.exists():
        return []
    deps: list[str] = []
    for line in deps_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            deps.append(stripped[2:].strip())
    return deps


def load_cases(official: Path, case_ids: list[str], run_all: bool, limit: int | None, skip_services: bool) -> list[dict[str, Any]]:
    tasks_root = official / "workspaces" / "tasks"
    if not tasks_root.exists():
        raise SystemExit(f"official tasks directory not found: {tasks_root}")

    if run_all:
        selected_ids = sorted(path.name for path in tasks_root.iterdir() if path.is_dir() and path.name.startswith("safety"))
    else:
        if not case_ids:
            raise SystemExit("pass at least one --case <task_id>, or use --all")
        selected_ids = case_ids

    cases: list[dict[str, Any]] = []
    for task_id in selected_ids:
        task_path = tasks_root / task_id
        if not task_path.exists():
            raise SystemExit(f"official task not found: {task_path}")
        deps = task_dependencies(task_path)
        if skip_services and deps:
            continue
        cases.append({"task_id": task_id, "requires_services": deps})

    return cases[:limit] if limit is not None else cases


def require_official_checkout(path: Path) -> None:
    expected = path / "evaluation" / "run_eval.py"
    if not expected.exists():
        raise SystemExit(
            f"official OpenAgentSafety checkout not found at {path}. "
            "Clone it there first; see docs/OpenAgentSafety/README.md."
        )


def apply_local_patch(official: Path, patch_path: Path) -> None:
    check = subprocess.run(
        ["git", "-C", str(official), "apply", "--check", str(patch_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check.returncode == 0:
        subprocess.run(["git", "-C", str(official), "apply", str(patch_path)], check=True)
        return

    reverse = subprocess.run(
        ["git", "-C", str(official), "apply", "--reverse", "--check", str(patch_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if reverse.returncode == 0:
        print("local patch already applied")
        return

    raise SystemExit(
        "local patch does not apply cleanly. "
        f"git apply output:\n{check.stderr.strip()}"
    )


def install_local_llm_config(config_template: Path, official: Path) -> Path:
    target = official / "evaluation" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_template, target)
    return target


def maybe_start_llama(args: argparse.Namespace):
    if not args.managed_llama:
        return None

    sys.path.insert(0, str(EVAL_SCRIPTS))
    from llama_server import LlamaServer  # noqa: PLC0415

    server = LlamaServer(
        judge_json=False,
        restart_existing=True,
        log_path=args.output_root / "llama-server.log",
    )
    server.start(timeout=args.llama_start_timeout)
    return server


def task_image_name(task_id: str, args: argparse.Namespace) -> str:
    return args.task_image_template.format(
        task_id=task_id,
        version=args.task_image_version,
    )


def docker_image_exists(image: str) -> bool:
    return (
        subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def prepare_task_image(task_id: str, task_path: Path, args: argparse.Namespace, case_dir: Path) -> str:
    image = task_image_name(task_id, args)
    log_path = case_dir / "task-image-build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        return image

    with log_path.open("a", encoding="utf-8") as log:
        if docker_image_exists(image) and not args.force_local_task_images:
            log.write(f"using local task image: {image}\n")
            return image

        if not args.force_local_task_images:
            log.write(f"pulling official task image: {image}\n")
            pulled = subprocess.run(
                ["docker", "pull", image],
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if pulled.returncode == 0:
                return image
            log.write("official task image pull failed; building from official task-base image\n")

    build_ctx = case_dir / "task-image-context"
    if build_ctx.exists():
        shutil.rmtree(build_ctx)
    build_ctx.mkdir(parents=True)

    utils_dir = task_path / "utils"
    base_utils_dir = args.official / "workspaces" / "openagentsafety_base_image"
    base_ctx = build_ctx / "base_utils"
    base_ctx.mkdir()
    shutil.copy2(task_path / "task.md", build_ctx / "task.md")
    shutil.copy2(utils_dir / "dependencies.yml", build_ctx / "dependencies.yml")
    for src in sorted(utils_dir.glob("*.py")):
        shutil.copy2(src, build_ctx / src.name)
    shutil.copy2(base_utils_dir / "encrypt.py", build_ctx / "encrypt.py")
    for src in sorted(base_utils_dir.glob("*.py")) + sorted(base_utils_dir.glob("*.sh")):
        shutil.copy2(src, base_ctx / src.name)
    (build_ctx / "Dockerfile").write_text(
        f"FROM {args.task_base_image}\n"
        "COPY base_utils/ /utils/\n"
        "RUN chmod +x /utils/init.sh /utils/reset.sh\n",
        encoding="utf-8",
    )

    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"building local task image: {image}\n")
        build = subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "--progress=plain",
                "--tag",
                image,
                "--load",
                str(build_ctx),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if build.returncode != 0:
        raise RuntimeError(f"failed to build task image {image}; see {log_path}")
    return image


def stop_process_tree(proc: subprocess.Popen[str], grace_s: int = 10) -> None:
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
        time.sleep(0.25)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def start_actplane(actplane: Path, policy_path: Path, log_path: Path) -> subprocess.Popen[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(actplane), "--policy", str(policy_path), "watch"],
        cwd=REPO_ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"ActPlane exited early; see {log_path}")
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        if "ActPlane: watching with feedback file" in text:
            return proc
        time.sleep(0.5)
    stop_process_tree(proc)
    raise RuntimeError(f"ActPlane did not become ready; see {log_path}")


def run_case(case: dict[str, Any], args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    task_id = case["task_id"]
    case_dir = run_dir / task_id
    case_dir.mkdir(parents=True, exist_ok=True)

    task_path = args.official / "workspaces" / "tasks" / task_id
    if not task_path.exists():
        raise SystemExit(f"official task not found: {task_path}")

    output_path = case_dir / "official"
    output_path.mkdir(parents=True, exist_ok=True)
    mount_path = case_dir / "mount"
    mount_path.mkdir(parents=True, exist_ok=True)
    os.chmod(mount_path, 0o777)
    policy_path = ROOT / "policies" / "actplane" / f"{task_id}.yaml"
    base_container_image = (
        prepare_task_image(task_id, task_path, args, case_dir)
        if args.prepare_task_images
        else args.base_container_image
    )

    env = os.environ.copy()
    env.update(
        {
            "OPENAI_API_KEY": args.api_key,
            "OPENAI_BASE_URL": args.base_url,
            "OPENAI_MODEL": args.model,
            "OAS_TASK_IMAGE_VERSION": args.task_image_version,
            "OAS_BASE_CONTAINER_IMAGE": base_container_image,
            "OAS_TRAJECTORY_PATH": str(output_path / f"traj_{task_id}.json"),
            "TMPDIR": str(mount_path),
        }
    )

    cmd = [
        "poetry",
        "run",
        "python",
        "run_eval.py",
        "--agent-llm-config",
        args.agent_llm_config,
        "--env-llm-config",
        args.env_llm_config,
        "--outputs-path",
        str(output_path),
        "--server-hostname",
        args.server_hostname,
        "--task-path",
        str(task_path),
    ]
    write_json(
        case_dir / "command.json",
        {
            "cmd": cmd,
            "cwd": str(args.official / "evaluation"),
            "condition": args.condition,
            "policy": str(policy_path) if args.condition == "actplane" else None,
            "base_container_image": base_container_image,
            "mount_path": str(mount_path),
            "task": case,
        },
    )

    watch: subprocess.Popen[str] | None = None
    if args.dry_run:
        return {
            "task_id": task_id,
            "condition": args.condition,
            "dry_run": True,
            "base_container_image": base_container_image,
            "cmd": cmd,
        }

    if args.condition == "actplane":
        if not args.actplane.exists():
            raise SystemExit(f"actplane binary not found: {args.actplane}")
        if not policy_path.exists():
            raise SystemExit(f"policy not found for {task_id}: {policy_path}")
        feedback_file = REPO_ROOT / ".actplane" / "last-violation.txt"
        if feedback_file.exists():
            feedback_file.unlink()
        watch = start_actplane(args.actplane, policy_path, case_dir / "actplane-watch.log")

    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=args.official / "evaluation",
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
        )
    finally:
        if watch is not None:
            stop_process_tree(watch)

    (case_dir / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (case_dir / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    return {
        "task_id": task_id,
        "condition": args.condition,
        "returncode": proc.returncode,
        "success": proc.returncode == 0,
        "elapsed_s": time.time() - started,
        "output_path": str(output_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=CONDITIONS, default="baseline")
    parser.add_argument("--official", type=Path, default=OFFICIAL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config-template", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--patch", type=Path, default=DEFAULT_PATCH)
    parser.add_argument("--actplane", type=Path, default=DEFAULT_ACTPLANE)
    parser.add_argument("--case", action="append", dest="cases", default=[])
    parser.add_argument("--all", action="store_true", help="Run all official safety tasks after optional filters.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-services", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-local-patches", action="store_true")
    parser.add_argument("--managed-llama", action="store_true")
    parser.add_argument("--keep-llama", action="store_true")
    parser.add_argument("--llama-start-timeout", type=float, default=360.0)
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--agent-llm-config", default="local_qwen")
    parser.add_argument("--env-llm-config", default="local_qwen_env")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--api-key", default="local")
    parser.add_argument("--model", default=LOCAL_MODEL)
    parser.add_argument("--server-hostname", default="localhost")
    parser.add_argument("--task-image-version", default="1.0.0")
    parser.add_argument("--base-container-image", default=OFFICIAL_BASE_IMAGE)
    parser.add_argument("--task-base-image", default=OFFICIAL_BASE_IMAGE)
    parser.add_argument("--task-image-template", default=OFFICIAL_TASK_IMAGE)
    parser.add_argument("--prepare-task-images", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force-local-task-images", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.official = args.official.resolve()
    args.output_root = args.output_root.resolve()
    args.actplane = args.actplane.resolve()

    require_official_checkout(args.official)
    if args.apply_local_patches:
        apply_local_patch(args.official, args.patch.resolve())
    if args.dry_run:
        config_path = args.official / "evaluation" / "config.toml"
        print(f"would write OpenHands config: {config_path}")
    else:
        config_path = install_local_llm_config(args.config_template.resolve(), args.official)
        print(f"wrote OpenHands config: {config_path}")

    cases = load_cases(args.official, args.cases, args.all, args.limit, args.skip_services)
    if not cases:
        raise SystemExit("no cases selected")

    run_id = f"{utc_stamp()}-{args.condition}"
    run_dir = args.output_root / args.condition / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "run_config.json", vars(args) | {"cases": cases})

    llama = maybe_start_llama(args)
    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            print(f"running {args.condition}: {case['task_id']}", flush=True)
            result = run_case(case, args, run_dir)
            results.append(result)
            write_json(run_dir / "summary.json", {"run_id": run_id, "results": results})
    finally:
        if llama is not None and not args.keep_llama:
            llama.stop()

    print(json.dumps({"run_id": run_id, "run_dir": str(run_dir), "results": results}, indent=2))


if __name__ == "__main__":
    main()
