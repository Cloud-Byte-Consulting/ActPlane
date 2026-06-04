"""Tool-layer regex baseline for RQ1.

The baseline consumes explicit per-case policy files:

    docs/corpus-test/<repo>/<statement_id>/baselines/tool-regex.yaml

It does not read or lower ActPlane's `rule.yaml`. This keeps the baseline
policy artifact visible and auditable.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolSource:
    label: str
    kind: str
    pattern: str
    op: str | None = None


@dataclass
class ToolRule:
    rule_id: str
    effect: str
    op: str
    pattern: str
    label_expr: str
    tool: str | None = None
    arg_pattern: str | None = None
    unless_targets: list[str] = field(default_factory=list)
    after_exec: str | None = None
    since_writes: list[str] = field(default_factory=list)
    reason: str = ""
    since_seen: bool = False
    after_satisfied: bool = False


@dataclass
class ToolPolicyEvent:
    rule_id: str
    effect: str
    op: str
    reason: str
    tool: str
    command: str | None = None
    file_path: str | None = None


@dataclass
class ToolRegexPolicy:
    sources: list[ToolSource] = field(default_factory=list)
    rules: list[ToolRule] = field(default_factory=list)
    labels: set[str] = field(default_factory=lambda: {"AGENT"})

    @classmethod
    def from_policy_file(cls, path: Path) -> "ToolRegexPolicy":
        data = load_policy_yaml(path)
        sources = [
            ToolSource(
                label=str(item["label"]),
                kind=str(item.get("kind", "file")),
                pattern=str(item["pattern"]),
                op=str(item["op"]) if item.get("op") is not None else None,
            )
            for item in data.get("sources", [])
        ]
        rules = [parse_policy_rule(item) for item in data.get("rules", [])]
        return cls(sources=sources, rules=rules)

    def check_before(
        self,
        tool: str,
        *,
        command: str | None = None,
        file_path: str | None = None,
    ) -> ToolPolicyEvent | None:
        op = tool_to_policy_op(tool)
        for rule in self.rules:
            if rule.op != op:
                continue
            if rule.tool and rule.tool != tool:
                continue
            if not self._target_matches(rule, command=command, file_path=file_path):
                continue
            if not eval_label_expr(rule.label_expr, self.labels):
                continue
            if file_path and any(
                match_file_pattern(pattern, file_path)
                for pattern in rule.unless_targets
            ):
                continue
            if rule.after_exec:
                if not rule.since_seen:
                    continue
                if rule.after_satisfied:
                    continue
            return ToolPolicyEvent(
                rule_id=rule.rule_id,
                effect=rule.effect,
                op=rule.op,
                reason=rule.reason,
                tool=tool,
                command=command,
                file_path=file_path,
            )
        return None

    def record_after(
        self,
        tool: str,
        *,
        command: str | None = None,
        file_path: str | None = None,
    ) -> None:
        op = tool_to_policy_op(tool)
        if op in {"read", "write"} and file_path:
            for source in self.sources:
                if source.kind != "file":
                    continue
                if source.op and source.op != op:
                    continue
                if match_file_pattern(source.pattern, file_path):
                    self.labels.add(source.label)
            if op == "write":
                for rule in self.rules:
                    if any(match_file_pattern(pattern, file_path) for pattern in rule.since_writes):
                        rule.since_seen = True
                        rule.after_satisfied = False
        elif op == "exec" and command:
            for source in self.sources:
                if source.kind != "exec":
                    continue
                if source.op and source.op != op:
                    continue
                if command_matches_exec(command, source.pattern, None):
                    self.labels.add(source.label)
            for rule in self.rules:
                if rule.after_exec and command_matches_exec(command, rule.after_exec, None):
                    rule.after_satisfied = True

    def _target_matches(
        self,
        rule: ToolRule,
        *,
        command: str | None,
        file_path: str | None,
    ) -> bool:
        if rule.op == "exec":
            return bool(command and command_matches_exec(command, rule.pattern, rule.arg_pattern))
        if rule.op in {"read", "write", "unlink"}:
            return bool(file_path and match_file_pattern(rule.pattern, file_path))
        return False


def load_policy_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing tool-regex baseline policy: {path}")
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("tool-regex baseline policies require PyYAML (`pip install pyyaml`)") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML value must be a mapping")
    return data


def parse_policy_rule(item: dict[str, Any]) -> ToolRule:
    unless = item.get("unless") if isinstance(item.get("unless"), dict) else {}
    unless_target = unless.get("target")
    if isinstance(unless_target, list):
        unless_targets = [str(v) for v in unless_target]
    elif unless_target is not None:
        unless_targets = [str(unless_target)]
    else:
        unless_targets = []

    since_write = unless.get("since_write", [])
    if isinstance(since_write, str):
        since_writes = [since_write]
    elif isinstance(since_write, list):
        since_writes = [str(v) for v in since_write]
    else:
        since_writes = []

    return ToolRule(
        rule_id=str(item["id"]),
        effect=str(item.get("effect", "notify")),
        op=str(item["op"]),
        pattern=str(item["target"]),
        tool=str(item["tool"]) if item.get("tool") is not None else None,
        arg_pattern=str(item["arg"]) if item.get("arg") is not None else None,
        label_expr=str(item.get("if", "AGENT")),
        unless_targets=unless_targets,
        after_exec=str(unless["after_exec"]) if unless.get("after_exec") is not None else None,
        since_writes=since_writes,
        reason=str(item.get("reason", "")),
    )


def tool_to_policy_op(tool: str) -> str:
    if tool == "Bash":
        return "exec"
    if tool == "Read":
        return "read"
    if tool in {"Write", "Edit"}:
        return "write"
    return tool.lower()


def normalize_tool_path(value: str) -> str:
    if not value:
        return value
    value = value.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def match_glob(pattern: str, value: str) -> bool:
    value = normalize_tool_path(value)
    candidates = {value}
    if value.startswith("/"):
        candidates.add(value[1:])
    else:
        candidates.add(f"/{value}")
    if "/" in value:
        candidates.add(Path(value).name)

    patterns = {pattern}
    if pattern.startswith("**/"):
        patterns.add(pattern[3:])
    if pattern.startswith("/"):
        patterns.add(pattern[1:])

    for pat in patterns:
        for candidate in candidates:
            if fnmatch.fnmatchcase(candidate, pat):
                return True
    return False


def match_file_pattern(pattern: str, file_path: str) -> bool:
    return match_glob(pattern, file_path)


def shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def is_shell_separator(token: str) -> bool:
    return token in {"&&", "||", ";", "|", "(", ")"}


def command_matches_exec(command: str, prog_pattern: str, arg_pattern: str | None) -> bool:
    tokens = shell_tokens(command)
    for idx, token in enumerate(tokens):
        if is_shell_separator(token):
            continue
        basename = Path(token).name
        if not (match_glob(prog_pattern, token) or match_glob(prog_pattern, basename)):
            continue
        if not arg_pattern:
            return True
        for later in tokens[idx + 1:]:
            if is_shell_separator(later):
                break
            if match_glob(arg_pattern, later) or match_glob(arg_pattern, Path(later).name):
                return True
    return False


def eval_label_expr(expr: str, labels: set[str]) -> bool:
    expr = expr.strip()
    if not expr:
        return True

    def replace_label(match: re.Match[str]) -> str:
        word = match.group(0)
        if word in {"and", "or", "not", "True", "False"}:
            return word
        return str(word in labels)

    py_expr = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", replace_label, expr)
    if re.search(r"[^()\sA-Za-z0-9_.]", py_expr):
        return False
    try:
        return bool(eval(py_expr, {"__builtins__": {}}, {}))
    except Exception:
        return False


def format_tool_policy_feedback(event: ToolPolicyEvent) -> str:
    target = event.command if event.command is not None else event.file_path
    payload = {
        "tool_rule": event.rule_id,
        "effect": event.effect,
        "action": "block" if event.effect == "kill" else "report",
        "tool": event.tool,
        "target": target,
    }
    action = "blocked" if event.effect == "kill" else "reported"
    return (
        f"[tool-regex] Tool-layer policy {action} rule \"{event.rule_id}\" "
        f"for {event.tool} {target!r}.\n"
        f"- Reason: {event.reason or 'policy matched this tool call'}\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
