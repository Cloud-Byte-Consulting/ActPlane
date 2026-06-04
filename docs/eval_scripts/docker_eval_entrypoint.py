#!/usr/bin/env python3
"""Container entrypoint for RQ1 eval runs.

The host workspace is mounted read-only. This entrypoint mounts an overlayfs
inside the container and runs the requested command in the merged workspace.
Only files created in the overlay upperdir are exported to the writable output
mount, so the host checkout and corpus repos are not modified.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).resolve()


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True)


def export_overlay_results(upper: Path, export_dir: Path) -> list[str]:
    exported: list[str] = []
    corpus_root = upper / "docs" / "corpus-test"
    if not corpus_root.exists():
        return exported

    for result_dir in sorted(corpus_root.glob("**/results")):
        for src in sorted(p for p in result_dir.rglob("*") if p.is_file()):
            rel = src.relative_to(upper)
            dst = export_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            exported.append(str(rel))
    return exported


def ensure_tracefs() -> bool:
    tracing = Path("/sys/kernel/tracing")
    if (tracing / "events").exists():
        return False
    tracing.mkdir(parents=True, exist_ok=True)
    proc = run(["mount", "-t", "tracefs", "tracefs", str(tracing)])
    return proc.returncode == 0


def chown_tree(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
    except OSError:
        pass
    for child in path.rglob("*"):
        try:
            os.chown(child, uid, gid)
        except OSError:
            pass


def main() -> int:
    lower = env_path("HOST_WORKSPACE", "/host/ActPlane")
    merged = env_path("MERGED_WORKSPACE", "/workspace/ActPlane")
    export_dir = env_path("EXPORT_DIR", "/out")
    overlay_root = env_path("OVERLAY_ROOT", "/tmp/actplane-workspace-overlay")
    overlay_store = env_path("OVERLAY_STORE", "/mnt/actplane-overlay-store")
    upper = overlay_root / "upper"
    work = overlay_root / "work"

    if not lower.exists():
        print(f"missing HOST_WORKSPACE lowerdir: {lower}", file=sys.stderr)
        return 2
    if not sys.argv[1:]:
        print("usage: actplane-docker-eval <command> [args...]", file=sys.stderr)
        return 2

    overlay_store.mkdir(parents=True, exist_ok=True)
    merged.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    store_mounted = False
    store_proc = run(["mount", "-t", "tmpfs", "tmpfs", str(overlay_store)])
    if store_proc.returncode == 0:
        store_mounted = True
        overlay_root = overlay_store / "workspace"
        upper = overlay_root / "upper"
        work = overlay_root / "work"
    upper.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    mount_cmd = [
        "mount",
        "-t",
        "overlay",
        "overlay",
        "-o",
        f"lowerdir={lower},upperdir={upper},workdir={work}",
        str(merged),
    ]
    mounted = False
    started = time.time()
    rc = 1
    tracefs_mounted = False
    try:
        tracefs_mounted = ensure_tracefs()
        proc = run(mount_cmd)
        if proc.returncode != 0:
            print(
                "failed to mount overlayfs; run docker with --privileged",
                file=sys.stderr,
            )
            return proc.returncode or 1
        mounted = True

        rc = run(sys.argv[1:], cwd=merged).returncode
        return rc
    finally:
        exported = export_overlay_results(upper, export_dir)
        manifest = {
            "host_workspace": str(lower),
            "merged_workspace": str(merged),
            "overlay_upper": str(upper),
            "elapsed_s": round(time.time() - started, 3),
            "command": sys.argv[1:],
            "returncode": rc,
            "exported_files": exported,
        }
        (export_dir / "docker_eval_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        host_uid = os.environ.get("HOST_UID")
        host_gid = os.environ.get("HOST_GID")
        if host_uid is not None and host_gid is not None:
            chown_tree(export_dir, int(host_uid), int(host_gid))
        if mounted:
            subprocess.run(["umount", "-l", str(merged)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if tracefs_mounted:
            subprocess.run(["umount", "-l", "/sys/kernel/tracing"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if store_mounted:
            subprocess.run(["umount", "-l", str(overlay_store)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
