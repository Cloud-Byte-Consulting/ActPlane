#!/usr/bin/env python3
"""Generate description-only first-pass ActPlane policies for OpenAgentSafety.

The generator intentionally reads only task.md. It does not inspect evaluator.py,
checkpoints.md, trajectories, or previous ActPlane logs. That keeps attempt0 a
clean "policy from user-visible task description" baseline.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = ROOT / "OpenAgentSafety" / "workspaces" / "tasks"
FINAL_50 = ROOT / "data" / "os_effect_blockable_50.json"
DEFAULT_OUT_DIR = ROOT / "policies" / "remaining_attempts" / "attempt0-description"
DEFAULT_MANIFEST = ROOT / "data" / "remaining_attempt0_description_manifest.json"

FILE_EXTS = (
    "cfg",
    "cer",
    "conf",
    "crt",
    "csv",
    "css",
    "db",
    "docx",
    "env",
    "gif",
    "gz",
    "html",
    "ini",
    "jpeg",
    "jpg",
    "js",
    "json",
    "key",
    "log",
    "md",
    "pem",
    "png",
    "pub",
    "py",
    "service",
    "sh",
    "sql",
    "sqlite",
    "tar",
    "toml",
    "ts",
    "txt",
    "xml",
    "xlsx",
    "yaml",
    "yml",
    "zip",
)

ABS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])/(?:workspace|worskpace|home|root|etc|var|tmp|usr|opt|srv|mnt|media|dev|proc|sys|boot|run)"
    r"[A-Za-z0-9_./@+~:-]*"
)
REL_FILE_RE = re.compile(
    rf"(?<![\w/.-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:{'|'.join(FILE_EXTS)}))(?![\w/.-])",
    re.IGNORECASE,
)
SPAN_RE = re.compile(r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'")
DESTRUCTIVE_OBJECT_RE = re.compile(
    r"\b(delete|remove|clean\s+up|cleanup|clear|wipe|erase|purge|shred|destroy)\b"
    r".{0,100}"
    r"\b(file|files|folder|folders|directory|directories|cache|caches|logs?|repos?|repositories|volume|disk|data|/var|/tmp|/workspace)\b",
    re.IGNORECASE | re.DOTALL,
)
BARE_SYSTEM_DIRS = {
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/media",
    "/mnt",
    "/opt",
    "/proc",
    "/root",
    "/run",
    "/srv",
    "/sys",
    "/tmp",
    "/usr",
    "/var",
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_final_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(case["task_id"]) for case in payload["cases"]}


def clean_token(token: str) -> str:
    token = token.strip().strip("`'\"")
    token = token.rstrip(".,;:!?)]}")
    token = token.lstrip("([{")
    return token.replace("\\", "/")


def add_path(paths: set[str], raw: str) -> None:
    path = clean_token(raw)
    if not path or path.startswith(("http://", "https://")):
        return
    if path == "/":
        return
    if path in {"/workspace", "/worskpace"}:
        path = f"{path}/**"
    elif path in BARE_SYSTEM_DIRS:
        return
    if path.endswith("/"):
        path = f"{path}**"
    variants = {path}
    if path.startswith("/worskpace/"):
        variants.add("/workspace/" + path[len("/worskpace/") :])
    if path.startswith("/workspace/"):
        variants.add("**" + path)
    if path.startswith("/worskpace/"):
        variants.add("**" + path)
    for variant in variants:
        paths.add(variant)


def add_relative_file(paths: set[str], raw: str) -> None:
    rel = clean_token(raw)
    if not rel or rel.startswith(("http://", "https://", "/")):
        return
    if "://" in rel:
        return
    add_path(paths, f"/workspace/{rel}")


def quoted_paths(text: str) -> set[str]:
    found: set[str] = set()
    for match in SPAN_RE.finditer(text):
        raw = next(group for group in match.groups() if group is not None)
        token = clean_token(raw)
        if not token:
            continue
        if token.startswith("/"):
            add_path(found, token)
        elif "/" in token and not token.startswith(("http://", "https://")):
            if token.endswith("/") or "." in Path(token).name:
                add_relative_file(found, token)
    return found


def extract_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for match in ABS_PATH_RE.finditer(text):
        add_path(paths, match.group(0))
    for match in REL_FILE_RE.finditer(text):
        add_relative_file(paths, match.group(1))
    paths.update(quoted_paths(text))
    return paths


def has_any(lower: str, terms: tuple[str, ...]) -> bool:
    return any(term in lower for term in terms)


def has_destructive_intent(text: str) -> bool:
    lower = text.lower()
    if "rm -rf" in lower or "clear space" in lower:
        return True
    if has_any(lower, ("disk wiping", "wipe disk", "format disk", "reformat disk", "destroy data")):
        return True
    return DESTRUCTIVE_OBJECT_RE.search(text) is not None


def add_explicit_destructive_commands(lower: str, execs: set[tuple[str, str | None]]) -> None:
    explicit = {
        "dd": r"\bdd\b",
        "find": r"\bfind\s+/",
        "mkfs": r"\bmkfs\b",
        "mkfs.ext4": r"\bmkfs\.ext4\b",
        "rm": r"\brm\s+-",
        "shred": r"\bshred\b",
        "truncate": r"\btruncate\b",
        "wipefs": r"\bwipefs\b",
        "blkdiscard": r"\bblkdiscard\b",
        "hdparm": r"\bhdparm\b",
    }
    for command, pattern in explicit.items():
        if re.search(pattern, lower):
            add_exec(execs, command)


def add_exec(cmds: set[tuple[str, str | None]], command: str, arg: str | None = None) -> None:
    cmds.add((command, arg))


def infer_rules(text: str) -> tuple[set[str], set[str], set[tuple[str, str | None]], list[str]]:
    lower = text.lower()
    write_paths = extract_paths(text)
    unlink_paths: set[str] = set()
    execs: set[tuple[str, str | None]] = set()
    categories: list[str] = []

    destructive = has_destructive_intent(text)
    if destructive:
        categories.append("destructive-or-cleanup")
        unlink_paths.update(write_paths)
        add_explicit_destructive_commands(lower, execs)

    if has_any(lower, ("cron", "crontab", "scheduled task", "weekly cleanup")):
        categories.append("persistence-or-scheduler")
        for command in ("crontab",):
            add_exec(execs, command)
        for path in ("/etc/crontab", "/etc/cron.d/**", "/etc/cron.daily/**", "/etc/cron.weekly/**", "/var/spool/cron/**"):
            add_path(write_paths, path)

    if has_any(lower, ("chmod", "chown", "permission", "permissions", "setuid", "suid")):
        categories.append("permission-change")
        for command in ("chmod", "chown", "setfacl", "install"):
            add_exec(execs, command)

    if has_any(lower, ("ssh", "authorized_keys", "private key", "public key")):
        categories.append("ssh-or-key-material")
        for path in ("/root/.ssh/**", "/home/**/.ssh/**", "/workspace/.ssh/**"):
            add_path(write_paths, path)
        for command in ("ssh", "scp", "sftp"):
            add_exec(execs, command)

    if has_any(lower, ("firewall", "iptables", "nftables", "ufw", "ssh daemon", "sshd")):
        categories.append("system-network-config")
        for command in ("iptables", "nft", "ufw", "firewall-cmd", "systemctl", "service"):
            add_exec(execs, command)
        for path in ("/etc/ssh/sshd_config", "/etc/iptables/**", "/etc/nftables.conf", "/etc/ufw/**"):
            add_path(write_paths, path)

    if has_any(lower, ("sudoers", "passwd", "shadow", "useradd", "usermod", "groupadd", "new user", "root access")):
        categories.append("account-or-privilege-change")
        for command in ("useradd", "usermod", "groupadd", "passwd", "chpasswd", "sudo", "visudo"):
            add_exec(execs, command)
        for path in ("/etc/passwd", "/etc/shadow", "/etc/group", "/etc/sudoers", "/etc/sudoers.d/**"):
            add_path(write_paths, path)

    if has_any(lower, ("shutdown", "reboot", "power off", "kill process", "terminate process", "stop service")):
        categories.append("availability-impact")
        for command in ("shutdown", "reboot", "poweroff", "halt", "kill", "pkill", "killall", "systemctl", "service"):
            add_exec(execs, command)

    if has_any(lower, ("docker", "container", "volume prune", "image prune")):
        categories.append("container-control")
        add_exec(execs, "docker")

    if has_any(lower, ("git push", "push to github", "remote repository", "git remote")):
        categories.append("git-egress")
        add_exec(execs, "git", "push")
        add_exec(execs, "git", "remote")

    if has_any(
        lower,
        (
            "exfiltrate",
            "send it to",
            "send them to",
            "upload",
            "webhook",
            "post the",
            "curl",
            "wget",
            "netcat",
            "nc ",
            "scp",
            "rsync",
            "external server",
        ),
    ):
        categories.append("network-egress")
        for command in ("curl", "wget", "nc", "ncat", "netcat", "scp", "rsync", "ssh"):
            add_exec(execs, command)

    if has_any(
        lower,
        (
            "api key",
            "apikey",
            "secret",
            "token",
            "credential",
            "password",
            ".env",
            "private key",
        ),
    ):
        categories.append("secret-or-credential")
        for path in ("/workspace/.env", "/workspace/secrets.txt", "/workspace/credentials.txt", "/workspace/tokens.txt"):
            add_path(write_paths, path)

    if has_any(
        lower,
        (
            "backdoor",
            "keylogger",
            "malware",
            "phishing",
            "ransomware",
            "trojan",
            "rootkit",
            "botnet",
            "brute force",
            "bruteforce",
            "harvest",
            "scrape credentials",
            "steal",
        ),
    ):
        categories.append("malicious-artifact")
        for command in ("openssl", "base64", "nc", "ncat", "netcat"):
            add_exec(execs, command)

    if has_any(lower, ("test", "tests", "pytest", "unit test")) and has_any(lower, ("remove", "delete", "weaken", "skip", "disable", "bypass")):
        categories.append("protected-tests")
        for path in ("/workspace/tests/**", "/workspace/**/tests/**", "/workspace/test/**", "/workspace/**/test/**"):
            add_path(write_paths, path)
            add_path(unlink_paths, path)

    return write_paths, unlink_paths, execs, sorted(set(categories))


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def render_policy(task_id: str, write_paths: set[str], unlink_paths: set[str], execs: set[tuple[str, str | None]], categories: list[str]) -> str:
    lines = [
        "version: 1",
        "",
        "feedback:",
        "  path: .actplane/last-violation.txt",
        "",
        "policy: |",
        "",
        f"  rule openagentsafety-{task_id}:",
    ]
    clauses: list[str] = []
    for command, arg in sorted(execs):
        if arg:
            clauses.append(f"    kill exec {yaml_quote(command)} {yaml_quote(arg)}")
        else:
            clauses.append(f"    kill exec {yaml_quote(command)}")
    for path in sorted(write_paths):
        clauses.append(f"    kill write file {yaml_quote(path)}")
    for path in sorted(unlink_paths):
        clauses.append(f"    kill unlink file {yaml_quote(path)}")
    if not clauses:
        clauses.append('    notify exec "__openagentsafety_no_os_sink__"')
    lines.extend(clauses)
    if categories:
        reason = "Description-only first pass blocks inferred OS sink categories: " + ", ".join(categories) + "."
    elif write_paths or unlink_paths or execs:
        reason = "Description-only first pass blocks explicit file or command sinks named in the task description."
    else:
        reason = "No concrete OS sink was visible in the task description for the description-only first pass."
    lines.append(f"    because {yaml_quote(reason)}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-root", type=Path, default=TASKS_ROOT)
    parser.add_argument("--final-manifest", type=Path, default=FINAL_50)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    final_ids = load_final_ids(args.final_manifest)
    task_dirs = sorted(
        path for path in args.tasks_root.iterdir() if path.is_dir() and path.name.startswith("safety")
    )
    remaining = [path for path in task_dirs if path.name not in final_ids]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    generated = 0
    noop = 0
    for task_dir in remaining:
        task_id = task_dir.name
        task_md = task_dir / "task.md"
        if task_md.exists():
            text = task_md.read_text(encoding="utf-8", errors="replace")
            write_paths, unlink_paths, execs, categories = infer_rules(text)
            status = "generated"
        else:
            text = ""
            write_paths, unlink_paths, execs, categories = set(), set(), set(), []
            status = "missing_task_md"
        policy_path = args.out_dir / f"{task_id}.yaml"
        policy_path.write_text(render_policy(task_id, write_paths, unlink_paths, execs, categories), encoding="utf-8")
        is_noop = not write_paths and not unlink_paths and not execs
        generated += 1
        noop += int(is_noop)
        cases.append(
            {
                "task_id": task_id,
                "task_md": str(task_md) if task_md.exists() else None,
                "policy": str(policy_path),
                "status": status,
                "description_only": True,
                "attempt": 0,
                "is_noop": is_noop,
                "categories": categories,
                "write_paths": sorted(write_paths),
                "unlink_paths": sorted(unlink_paths),
                "execs": [
                    {"command": command, "arg": arg}
                    for command, arg in sorted(execs)
                ],
            }
        )

    payload = {
        "generated_at": utc_stamp(),
        "method": "attempt0-description-only-task-md",
        "tasks_total": len(task_dirs),
        "final_50_excluded": len(final_ids),
        "remaining_cases": len(remaining),
        "policies_generated": generated,
        "noop_policies": noop,
        "out_dir": str(args.out_dir),
        "cases": cases,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("tasks_total", "final_50_excluded", "remaining_cases", "policies_generated", "noop_policies")}, indent=2))


if __name__ == "__main__":
    main()
