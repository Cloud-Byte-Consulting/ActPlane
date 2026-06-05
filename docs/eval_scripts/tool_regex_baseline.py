"""Tool-layer raw-regex baseline for RQ1.

The baseline consumes explicit per-case policy files:

    docs/corpus-test/<repo>/<statement_id>/baselines/tool-regex.yaml

It does not read or lower ActPlane's `rule.yaml`. This keeps the baseline
policy artifact visible and auditable. Patterns are Python regular expressions
matched directly against the Agent SDK tool input string; there is no shell
tokenization or command parsing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
                regex_matches(pattern, normalized_tool_path(file_path))
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
                if regex_matches(source.pattern, normalized_tool_path(file_path)):
                    self.labels.add(source.label)
            if op == "write":
                for rule in self.rules:
                    if any(
                        regex_matches(pattern, normalized_tool_path(file_path))
                        for pattern in rule.since_writes
                    ):
                        rule.since_seen = True
                        rule.after_satisfied = False
        elif op == "exec" and command:
            for source in self.sources:
                if source.kind != "exec":
                    continue
                if source.op and source.op != op:
                    continue
                if regex_matches(source.pattern, command):
                    self.labels.add(source.label)
            for rule in self.rules:
                if rule.after_exec and regex_matches(rule.after_exec, command):
                    rule.after_satisfied = True

    def _target_matches(
        self,
        rule: ToolRule,
        *,
        command: str | None,
        file_path: str | None,
    ) -> bool:
        if rule.op == "exec":
            if not command or not regex_matches(rule.pattern, command):
                return False
            return not rule.arg_pattern or regex_matches(rule.arg_pattern, command)
        if rule.op in {"read", "write", "unlink"}:
            return bool(file_path and regex_matches(rule.pattern, normalized_tool_path(file_path)))
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
    unless_pattern = unless.get("pattern", unless.get("target"))
    if isinstance(unless_pattern, list):
        unless_targets = [str(v) for v in unless_pattern]
    elif unless_pattern is not None:
        unless_targets = [str(unless_pattern)]
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
        pattern=str(item.get("pattern", item.get("target"))),
        tool=str(item["tool"]) if item.get("tool") is not None else None,
        arg_pattern=(
            str(item.get("arg_pattern", item.get("arg")))
            if item.get("arg_pattern", item.get("arg")) is not None
            else None
        ),
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


def regex_matches(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value, flags=re.IGNORECASE | re.MULTILINE) is not None
    except re.error as exc:
        raise ValueError(f"invalid tool-regex pattern {pattern!r}: {exc}") from exc


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
