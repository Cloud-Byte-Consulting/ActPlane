#!/usr/bin/env python3
"""Run the RQ1 Agent SDK eval inside Docker with a full host-root COW view."""

from __future__ import annotations

import argparse
import os
import site
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGE = "actplane-rq1-agent-sdk:latest"
CONTAINER_HOST_ROOT = Path("/host-root")
CONTAINER_MERGED_ROOT = Path("/workspace/host-root")


def under_root(path: Path) -> Path:
    resolved = path.resolve()
    root = ROOT.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    raise ValueError(f"path is outside workspace: {path}")


def container_path(path: Path) -> str:
    return str(under_root(path))


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def host_pythonpath() -> str:
    entries: list[str] = []
    user_site = site.getusersitepackages()
    if isinstance(user_site, str) and user_site:
        entries.append(user_site)
    existing = os.environ.get("PYTHONPATH")
    if existing:
        entries.extend(p for p in existing.split(os.pathsep) if p)
    seen: set[str] = set()
    unique: list[str] = []
    for entry in entries:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return os.pathsep.join(unique)


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


def container_module_cmd(module: str) -> list[str]:
    script_dir = ROOT / "docs" / "eval_scripts"
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(script_dir)!r}); "
        f"from {module} import cli_main; "
        "raise SystemExit(cli_main(sys.argv[1:]))"
    )
    return ["python3", "-c", code]


def make_agent_args(args: argparse.Namespace) -> list[str]:
    agent_args = [
        *container_module_cmd("agent_sdk_eval"),
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
        f"HOST_ROOT={CONTAINER_HOST_ROOT}",
        "-e",
        f"MERGED_ROOT={CONTAINER_MERGED_ROOT}",
        "-e",
        f"HOST_WORKSPACE={ROOT.resolve()}",
        "-e",
        f"MERGED_WORKSPACE={ROOT.resolve()}",
        "-e",
        "EXPORT_DIR=/out",
        "-e",
        f"HOST_UID={os.getuid()}",
        "-e",
        f"HOST_GID={os.getgid()}",
        "-e",
        f"{args.api_key_env}",
        "-e",
        f"PATH={os.environ.get('PATH', '')}",
        "-e",
        f"HOST_HOME={Path.home()}",
        "-e",
        f"HOST_PYTHONPATH={host_pythonpath()}",
        "-v",
        f"/:{CONTAINER_HOST_ROOT}:ro,rslave",
        "-v",
        f"{out_dir.resolve()}:/out:rw",
    ]
    docker_args.extend([args.image, *make_agent_args(args)])
    rc = run(docker_args)
    print(f"docker eval output: {out_dir}")
    return rc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.no_build:
        rc = build_image(args.image)
        if rc != 0:
            return rc
    if args.api_key_env not in os.environ:
        print(f"warning: {args.api_key_env} is not set in host environment")
    return docker_run(args)


if __name__ == "__main__":
    raise SystemExit(
        "docker_agent_sdk_eval.py is an internal helper. "
        "Use docs/eval_scripts/run_eval.py as the only eval entrypoint."
    )
