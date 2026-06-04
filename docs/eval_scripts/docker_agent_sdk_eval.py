#!/usr/bin/env python3
"""Run the RQ1 Agent SDK eval inside Docker with an overlay workspace."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGE = "actplane-rq1-agent-sdk:latest"
CONTAINER_WORKSPACE = Path("/workspace/ActPlane")
CONTAINER_HOST_WORKSPACE = Path("/host/ActPlane")


def under_root(path: Path) -> Path:
    resolved = path.resolve()
    root = ROOT.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    raise ValueError(f"path is outside workspace: {path}")


def container_path(path: Path) -> str:
    resolved = under_root(path)
    rel = resolved.relative_to(ROOT.resolve())
    return str(CONTAINER_WORKSPACE / rel)


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def build_image(image: str) -> int:
    return run([
        "docker",
        "build",
        "-f",
        str(SCRIPT_DIR / "Dockerfile.agent-sdk"),
        "-t",
        image,
        str(SCRIPT_DIR),
    ])


def make_agent_args(args: argparse.Namespace) -> list[str]:
    agent_args = [
        "python3",
        str(CONTAINER_WORKSPACE / "docs" / "eval_scripts" / "agent_sdk_eval.py"),
        "--system",
        args.system,
        "--base-url",
        args.base_url,
        "--model-name",
        args.model_name,
        "--api-key-env",
        args.api_key_env,
        "--request-timeout",
        str(args.request_timeout),
        "--max-steps",
        str(args.max_steps),
    ]
    if args.thinking != "default":
        agent_args.extend(["--thinking", args.thinking])
    if args.limit is not None:
        agent_args.extend(["--limit", str(args.limit)])
    if args.statement_dir:
        agent_args.extend(["--statement-dir", container_path(args.statement_dir)])
    else:
        agent_args.extend(["--root", container_path(args.root)])
    if args.trace:
        agent_args.extend(["--trace", container_path(args.trace)])
    return agent_args


def docker_run(args: argparse.Namespace) -> int:
    out_dir = args.out_dir
    if out_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = ROOT / "docs" / "eval_runs" / "docker-agent-sdk" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    docker_args = [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--pid",
        "host",
        "--network",
        "host",
        "-e",
        f"HOST_WORKSPACE={CONTAINER_HOST_WORKSPACE}",
        "-e",
        f"MERGED_WORKSPACE={CONTAINER_WORKSPACE}",
        "-e",
        "EXPORT_DIR=/out",
        "-e",
        f"HOST_UID={os.getuid()}",
        "-e",
        f"HOST_GID={os.getgid()}",
        "-e",
        f"{args.api_key_env}",
        "-v",
        f"{ROOT.resolve()}:{CONTAINER_HOST_WORKSPACE}:ro",
        "-v",
        f"{out_dir.resolve()}:/out:rw",
        args.image,
        *make_agent_args(args),
    ]
    rc = run(docker_args)
    print(f"docker eval output: {out_dir}")
    return rc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT / "docs" / "corpus-test")
    parser.add_argument("--statement-dir", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--system",
        choices=["prompt-only", "tool-regex", "actplane", "actplane-opaque"],
        default="prompt-only",
    )
    parser.add_argument("--base-url", default="https://api.z.ai/api/coding/paas/v4")
    parser.add_argument("--model-name", default="glm-4.7")
    parser.add_argument("--api-key-env", default="GLM_API_KEY")
    parser.add_argument("--thinking", choices=["default", "enabled", "disabled"], default="default")
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--max-steps", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.no_build:
        rc = build_image(args.image)
        if rc != 0:
            return rc
    if args.api_key_env not in os.environ:
        print(f"warning: {args.api_key_env} is not set in host environment")
    return docker_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
