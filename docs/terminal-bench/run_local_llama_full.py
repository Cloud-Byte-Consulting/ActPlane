#!/usr/bin/env python3
"""Run Terminal-Bench with local llama.cpp/Qwen, cleaning Docker after each task.

This intentionally runs tasks one at a time. Terminal-Bench's built-in
`--cleanup` is enabled, and this wrapper also removes Docker images created
during each task plus prunes build cache, so a full run is less likely to fill
the disk.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = "terminal-bench-core==0.1.1"
DEFAULT_DATASET_PATH = Path(
    "/home/yunwei37/.cache/terminal-bench/terminal-bench-core/0.1.1"
)
DEFAULT_OUTPUT = Path("/tmp/tbench-local-llama")
DEFAULT_LLAMA_SERVER = Path(
    "/home/yunwei37/workspace/llama.cpp-latest/build/bin/llama-server"
)
DEFAULT_MODEL = Path(
    "/home/yunwei37/.cache/huggingface/hub/models--DevQuasar--Qwen.Qwen3.6-27B-GGUF/"
    "snapshots/b19fa7e8538a1a5f66452eb3b3167e026177be1d/"
    "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf"
)
DEFAULT_MODEL_NAME = "openai/Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def run_quiet(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def docker_image_ids() -> set[str]:
    result = run_quiet(["docker", "image", "ls", "-q", "--no-trunc"])
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def docker_container_ids() -> set[str]:
    result = run_quiet(["docker", "ps", "-aq", "--no-trunc"])
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def cleanup_docker(
    new_images: set[str], new_containers: set[str], prune_build_cache: bool
) -> dict[str, Any]:
    cleanup: dict[str, Any] = {
        "new_containers": sorted(new_containers),
        "removed_containers": [],
        "container_remove_errors": [],
        "new_images": sorted(new_images),
        "removed_images": [],
        "image_remove_errors": [],
        "builder_prune": None,
    }
    for container_id in sorted(new_containers):
        result = run_quiet(["docker", "rm", "-f", container_id])
        if result.returncode == 0:
            cleanup["removed_containers"].append(container_id)
        else:
            cleanup["container_remove_errors"].append(
                {"container": container_id, "output": result.stdout[-2000:]}
            )

    for image_id in sorted(new_images):
        result = run_quiet(["docker", "image", "rm", "-f", image_id])
        if result.returncode == 0:
            cleanup["removed_images"].append(image_id)
        else:
            cleanup["image_remove_errors"].append(
                {"image": image_id, "output": result.stdout[-2000:]}
            )

    if prune_build_cache:
        result = run_quiet(["docker", "builder", "prune", "-af"])
        cleanup["builder_prune"] = {
            "returncode": result.returncode,
            "output_tail": result.stdout[-4000:],
        }
    return cleanup


def healthy(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url}/health", timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def stop_process_tree(proc: subprocess.Popen[str], grace_s: float = 10) -> None:
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


def start_llama(args: argparse.Namespace, run_dir: Path) -> subprocess.Popen[str] | None:
    base_url = f"http://{args.host}:{args.port}"
    if healthy(base_url):
        print(f"llama-server already healthy at {base_url}; reusing it")
        return None

    if not args.llama_server.exists():
        raise FileNotFoundError(f"llama-server not found: {args.llama_server}")
    if not args.model_path.exists():
        raise FileNotFoundError(f"model not found: {args.model_path}")

    log_path = run_dir / "llama-server.log"
    log_file = log_path.open("w", encoding="utf-8")
    cmd = [
        str(args.llama_server),
        "-m",
        str(args.model_path),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--device",
        args.device,
        "--fit",
        "off",
        "-ngl",
        args.gpu_layers,
        "-c",
        str(args.ctx_size),
        "-np",
        "1",
        "--reasoning",
        "off",
        "--reasoning-format",
        "none",
        "--no-webui",
    ]
    print("starting llama-server:", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=os.setsid,
    )
    deadline = time.time() + args.llama_start_timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited; see {log_path}")
        if healthy(base_url):
            print(f"llama-server healthy at {base_url}; log: {log_path}")
            return proc
        time.sleep(1)
    stop_process_tree(proc)
    raise TimeoutError(f"llama-server did not become healthy; see {log_path}")


def list_tasks(dataset_path: Path) -> list[str]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset path not found: {dataset_path}")
    return sorted(p.parent.name for p in dataset_path.rglob("task.yaml"))


def run_task(args: argparse.Namespace, run_dir: Path, task_id: str) -> dict[str, Any]:
    task_run_id = f"{args.run_id}__{safe_name(task_id)}"
    log_path = run_dir / "logs" / f"{safe_name(task_id)}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    before_containers = docker_container_ids()
    before_images = docker_image_ids()

    cmd = [
        "uvx",
        "--from",
        "terminal-bench",
        "tb",
        "run",
        "--dataset",
        args.dataset,
        "--agent",
        args.agent,
        "--model",
        args.model_name,
        "-k",
        f"api_base=http://{args.host}:{args.port}/v1",
        "--task-id",
        task_id,
        "--n-concurrent",
        "1",
        "--output-path",
        str(run_dir / "task-runs"),
        "--run-id",
        task_run_id,
    ]
    if args.agent_timeout_sec is not None:
        cmd.extend(["--global-agent-timeout-sec", str(args.agent_timeout_sec)])
    if args.test_timeout_sec is not None:
        cmd.extend(["--global-test-timeout-sec", str(args.test_timeout_sec)])

    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "dummy")

    print(f"\n=== {task_id} ===")
    print(" ".join(cmd))
    started = time.time()
    timed_out = False
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            preexec_fn=os.setsid,
        )
        assert proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        while proc.poll() is None:
            if (
                args.task_hard_timeout_sec is not None
                and time.time() - started > args.task_hard_timeout_sec
            ):
                timed_out = True
                print(f"hard timeout after {args.task_hard_timeout_sec}s: {task_id}")
                stop_process_tree(proc)
                break
            for key, _ in selector.select(timeout=1):
                line = key.fileobj.readline()
                if not line:
                    continue
                log.write(line)
                log.flush()
                if "Results Summary" in line or "Accuracy:" in line or "Error " in line:
                    print(line.rstrip(), flush=True)
        for line in proc.stdout:
            log.write(line)
            log.flush()
            if "Results Summary" in line or "Accuracy:" in line or "Error " in line:
                print(line.rstrip(), flush=True)
        returncode = proc.wait()
    ended = time.time()

    after_containers = docker_container_ids()
    after_images = docker_image_ids()
    cleanup = cleanup_docker(
        after_images - before_images,
        after_containers - before_containers,
        args.prune_build_cache,
    )

    result_path = run_dir / "task-runs" / task_run_id / "results.json"
    parsed: dict[str, Any] | None = None
    if result_path.exists():
        parsed = json.loads(result_path.read_text())

    return {
        "task_id": task_id,
        "run_id": task_run_id,
        "returncode": returncode,
        "timed_out": timed_out,
        "seconds": ended - started,
        "log_path": str(log_path),
        "results_path": str(result_path),
        "results": parsed,
        "docker_cleanup": cleanup,
    }


def summarize(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    per_task: list[dict[str, Any]] = []
    resolved = 0
    unresolved = 0
    errored = 0
    for task in task_results:
        parsed = task.get("results")
        if not parsed:
            errored += 1
            per_task.append(
                {
                    "task_id": task["task_id"],
                    "status": "harness_error",
                    "returncode": task["returncode"],
                    "timed_out": task.get("timed_out", False),
                    "seconds": task["seconds"],
                    "log_path": task["log_path"],
                }
            )
            continue
        item = parsed["results"][0]
        is_resolved = bool(item.get("is_resolved"))
        resolved += int(is_resolved)
        unresolved += int(not is_resolved)
        per_task.append(
            {
                "task_id": task["task_id"],
                "status": "resolved" if is_resolved else "unresolved",
                "failure_mode": item.get("failure_mode"),
                "seconds": task["seconds"],
                "input_tokens": item.get("total_input_tokens"),
                "output_tokens": item.get("total_output_tokens"),
                "run_id": task["run_id"],
                "results_path": task["results_path"],
                "log_path": task["log_path"],
            }
        )
    total = resolved + unresolved + errored
    return {
        "total_tasks": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "harness_errors": errored,
        "accuracy": resolved / total if total else 0.0,
        "per_task": per_task,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", default=f"local-llama-qwen27b-{utc_stamp()}")
    parser.add_argument("--task-id", action="append", help="Run only this task; repeatable")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-at", help="Skip tasks before this task id")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep existing task_results.json and skip task ids already recorded.",
    )
    parser.add_argument("--agent", default="terminus")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--agent-timeout-sec",
        type=float,
        default=None,
        help="Forwarded Terminal-Bench agent timeout; <=0 or omitted disables wrapper override.",
    )
    parser.add_argument(
        "--test-timeout-sec",
        type=float,
        default=None,
        help="Forwarded Terminal-Bench test timeout; <=0 or omitted disables wrapper override.",
    )
    parser.add_argument(
        "--task-hard-timeout-sec",
        type=float,
        default=None,
        help="Wrapper wall-clock cap per task; <=0 or omitted disables it.",
    )
    parser.add_argument("--llama-server", type=Path, default=DEFAULT_LLAMA_SERVER)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--device", default="CUDA0")
    parser.add_argument("--gpu-layers", default="all")
    parser.add_argument("--ctx-size", type=int, default=65536)
    parser.add_argument("--llama-start-timeout", type=float, default=240)
    parser.add_argument("--no-prune-build-cache", dest="prune_build_cache", action="store_false")
    parser.add_argument("--keep-llama", action="store_true", help="Do not stop a server started by this script")
    args = parser.parse_args()
    for timeout_attr in (
        "agent_timeout_sec",
        "test_timeout_sec",
        "task_hard_timeout_sec",
    ):
        value = getattr(args, timeout_attr)
        if value is not None and value <= 0:
            setattr(args, timeout_attr, None)

    run_dir = args.output_path / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": args.run_id,
        "dataset": args.dataset,
        "dataset_path": str(args.dataset_path),
        "agent": args.agent,
        "model_name": args.model_name,
        "api_base": f"http://{args.host}:{args.port}/v1",
        "ctx_size": args.ctx_size,
        "created_at": utc_stamp(),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    tasks = args.task_id or list_tasks(args.dataset_path)
    if args.start_at:
        if args.start_at not in tasks:
            raise ValueError(f"--start-at task not in selected task list: {args.start_at}")
        tasks = tasks[tasks.index(args.start_at) :]
    if args.limit is not None:
        tasks = tasks[: args.limit]

    task_results_path = run_dir / "task_results.json"
    task_results: list[dict[str, Any]] = []
    if args.resume and task_results_path.exists():
        task_results = json.loads(task_results_path.read_text(encoding="utf-8"))
        completed = {item["task_id"] for item in task_results}
        tasks = [task_id for task_id in tasks if task_id not in completed]
        print(f"resume: loaded {len(completed)} completed tasks")

    (run_dir / "tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"selected {len(tasks)} tasks; output: {run_dir}")

    llama_proc = start_llama(args, run_dir)
    try:
        for task_id in tasks:
            task_result = run_task(args, run_dir, task_id)
            task_results.append(task_result)
            task_results_path.write_text(
                json.dumps(task_results, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summary = summarize(task_results)
            (run_dir / "aggregate_results.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                "progress: "
                f"{len(task_results)}/{len(tasks)} tasks, "
                f"resolved={summary['resolved']}, "
                f"unresolved={summary['unresolved']}, "
                f"errors={summary['harness_errors']}, "
                f"accuracy={summary['accuracy']:.2%}"
            )
    finally:
        if llama_proc is not None and not args.keep_llama:
            stop_process_tree(llama_proc)

    summary = summarize(task_results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
