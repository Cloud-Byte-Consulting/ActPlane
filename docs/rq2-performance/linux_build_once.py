#!/usr/bin/env python3
"""Build a Linux kernel target in a fresh out-of-tree directory."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path


def run_checked(cmd: list[str], cwd: Path, timeout: int) -> None:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    print(proc.stdout, end="")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=24)
    parser.add_argument("--target", default="vmlinux")
    parser.add_argument("--config", default="defconfig")
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    source = args.source.resolve()
    build_dir = args.build_dir.resolve()

    if not (source / "Makefile").exists():
        raise SystemExit(f"not a Linux source tree: {source}")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    start = time.perf_counter()
    run_checked(["make", "-C", str(source), f"O={build_dir}", args.config], source, args.timeout_s)
    config_done = time.perf_counter()
    run_checked(
        [
            "make",
            "-C",
            str(source),
            f"O={build_dir}",
            f"-j{args.jobs}",
            args.target,
        ],
        source,
        args.timeout_s,
    )
    end = time.perf_counter()
    print(
        json.dumps(
            {
                "benchmark": "linux_build",
                "source": str(source),
                "build_dir": str(build_dir),
                "config": args.config,
                "target": args.target,
                "jobs": args.jobs,
                "config_s": config_done - start,
                "build_s": end - config_done,
                "elapsed_s": end - start,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
