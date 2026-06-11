"""Tool-layer IFC baseline for RQ1/RQ2.

This baseline lowers the existing ActPlane `rule.yaml` DSL into a best-effort
tool-boundary information-flow monitor. It observes only the Agent SDK tools
used by the evaluation harness: Bash, Read, Write, and Edit. It therefore keeps
the same policy artifact as ActPlane while intentionally lacking ActPlane's
subprocess, syscall, and opaque script visibility.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from tool_regex_baseline import ToolPolicyEvent


@dataclass(frozen=True)
class IfcSource:
    label: str
    kind: str
    pattern: str


@dataclass(frozen=True)
class IfcTarget:
    kind: str
    pattern: str
    arg: str | None = None


@dataclass(frozen=True)
class IfcCond:
    kind: str
    negate: bool = False
    pattern: str | None = None
    gate_op: str | None = None
    gate_pattern: str | None = None
    gate_exit: int | None = None
    since: tuple[tuple[str, str, str | None], ...] = ()


@dataclass(frozen=True)
class IfcClause:
    rule_id: str
    effect: str
    op: str
    target: IfcTarget
    label_expr: Any
    unless: IfcCond | None
    reason: str


@dataclass
class CommandView:
    command: str
    tokens: list[str]


@dataclass
class ExecMatch:
    target_index: int | None


@dataclass
class ToolIfcPolicy:
    sources: list[IfcSource] = field(default_factory=list)
    clauses: list[IfcClause] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)
    file_labels: dict[str, set[str]] = field(default_factory=dict)
    epoch: int = 0
    gate_epochs: dict[tuple[str, str, str | None], int] = field(default_factory=dict)
    invalidator_epochs: dict[tuple[str, str, str | None], int] = field(default_factory=dict)

    @classmethod
    def from_rule_yaml(cls, path: Path) -> "ToolIfcPolicy":
        policy_text = load_rule_yaml(path)
        sources, clauses = parse_policy_text(policy_text)
        policy = cls(sources=sources, clauses=clauses)
        policy.labels.update(policy._seed_agent_labels())
        return policy

    def check_before(
        self,
        tool: str,
        *,
        command: str | None = None,
        file_path: str | None = None,
    ) -> ToolPolicyEvent | None:
        op = tool_to_policy_op(tool)
        command_view = command_view_for(command) if command is not None else None
        visible_path = normalize_tool_path(file_path or "")
        effective_labels = set(self.labels)
        effective_labels.update(self._event_source_labels(tool, command_view, visible_path))

        for clause in self.clauses:
            if clause.op != op:
                continue
            matches = self._target_matches(clause, command_view, visible_path)
            if not matches:
                continue
            if not eval_expr(clause.label_expr, effective_labels):
                continue
            if clause.unless and any(
                self._cond_holds(clause.unless, command_view, visible_path, match)
                for match in matches
            ):
                continue
            return ToolPolicyEvent(
                rule_id=f"tool-ifc:{clause.rule_id}",
                effect="kill" if clause.effect == "block" else clause.effect,
                op=clause.op,
                reason=clause.reason,
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
        command_view = command_view_for(command) if command is not None else None
        visible_path = normalize_tool_path(file_path or "")

        self.labels.update(self._event_source_labels(tool, command_view, visible_path))

        if op == "read" and visible_path:
            self.labels.update(self.file_labels.get(visible_path, set()))
            self.labels.add("READ_ANY")
        elif op == "write" and visible_path:
            self.file_labels.setdefault(visible_path, set()).update(self.labels)

        self._record_gates(op, command_view, visible_path)
        self._record_invalidators(op, command_view, visible_path)

    def _seed_agent_labels(self) -> set[str]:
        seed_execs = ("python3", "python", "claude", "__actplane_eval_seed__")
        labels: set[str] = set()
        for source in self.sources:
            if source.kind == "exec" and any(exec_pattern_matches(source.pattern, name) for name in seed_execs):
                labels.add(source.label)
        return labels

    def _event_source_labels(
        self,
        tool: str,
        command_view: CommandView | None,
        visible_path: str,
    ) -> set[str]:
        labels: set[str] = set()
        op = tool_to_policy_op(tool)
        for source in self.sources:
            if source.kind == "file":
                if op in {"read", "write"} and visible_path and path_pattern_matches(source.pattern, visible_path):
                    labels.add(source.label)
            elif source.kind == "exec" and op == "exec":
                if source.pattern and exec_pattern_matches(source.pattern, "bash"):
                    labels.add(source.label)
                if command_view and any(exec_pattern_matches(source.pattern, token) for token in command_view.tokens):
                    labels.add(source.label)
        return labels

    def _target_matches(
        self,
        clause: IfcClause,
        command_view: CommandView | None,
        visible_path: str,
    ) -> list[ExecMatch]:
        if clause.op == "exec":
            if not command_view:
                return []
            matches: list[ExecMatch] = []
            for index, token in enumerate(command_view.tokens):
                if not exec_pattern_matches(clause.target.pattern, token):
                    continue
                if clause.target.arg and not any(
                    exec_arg_matches(clause.target.arg, arg)
                    for arg in command_view.tokens[index + 1 :]
                ):
                    continue
                matches.append(ExecMatch(target_index=index))
            return matches

        if clause.op in {"read", "write", "open", "unlink"}:
            if visible_path and path_pattern_matches(clause.target.pattern, visible_path):
                return [ExecMatch(target_index=None)]
            return []
        return []

    def _cond_holds(
        self,
        cond: IfcCond,
        command_view: CommandView | None,
        visible_path: str,
        match: ExecMatch,
    ) -> bool:
        if cond.kind == "target":
            pattern = cond.pattern or ""
            matched = visible_target_matches(pattern, command_view, visible_path)
            return not matched if cond.negate else matched

        if cond.kind == "lineage-includes":
            pattern = cond.pattern or ""
            if command_view is None:
                return False
            prefix = ["bash"]
            if match.target_index is None:
                prefix.extend(command_view.tokens)
            else:
                prefix.extend(command_view.tokens[: match.target_index + 1])
            return any(exec_pattern_matches(pattern, token) for token in prefix)

        if cond.kind == "after":
            key = (cond.gate_op or "", cond.gate_pattern or "", None)
            gate_epoch = self.gate_epochs.get(key, 0)
            if gate_epoch == 0:
                return False
            for since_key in cond.since:
                if self.invalidator_epochs.get(since_key, 0) >= gate_epoch:
                    return False
            return True

        return False

    def _record_gates(
        self,
        op: str,
        command_view: CommandView | None,
        visible_path: str,
    ) -> None:
        gate_keys = {
            (clause.unless.gate_op, clause.unless.gate_pattern, None)
            for clause in self.clauses
            if clause.unless and clause.unless.kind == "after"
        }
        for gate_op, gate_pattern, gate_arg in gate_keys:
            if not gate_op or not gate_pattern:
                continue
            if event_matches(gate_op, gate_pattern, gate_arg, op, command_view, visible_path):
                self.epoch += 1
                self.gate_epochs[(gate_op, gate_pattern, gate_arg)] = self.epoch

    def _record_invalidators(
        self,
        op: str,
        command_view: CommandView | None,
        visible_path: str,
    ) -> None:
        since_keys = {
            since
            for clause in self.clauses
            if clause.unless and clause.unless.kind == "after"
            for since in clause.unless.since
        }
        for since_op, since_pattern, since_arg in since_keys:
            if event_matches(since_op, since_pattern, since_arg, op, command_view, visible_path):
                self.epoch += 1
                self.invalidator_epochs[(since_op, since_pattern, since_arg)] = self.epoch


def load_rule_yaml(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"missing tool-ifc source policy: {path}")
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("tool-ifc baseline policies require PyYAML (`pip install pyyaml`)") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML value must be a mapping")
    policy = data.get("policy")
    if not isinstance(policy, str):
        raise ValueError(f"{path}: missing string `policy` block")
    return policy


def tool_to_policy_op(tool: str) -> str:
    if tool == "Bash":
        return "exec"
    if tool == "Read":
        return "read"
    if tool in {"Write", "Edit"}:
        return "write"
    return tool.lower()


def normalize_tool_path(value: str) -> str:
    value = value.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    value = re.sub(r"/+", "/", value)
    return value


def command_view_for(command: str | None) -> CommandView:
    command = command or ""
    try:
        raw_tokens = shlex.split(command, posix=True)
    except ValueError:
        raw_tokens = re.split(r"\s+", command)
    tokens: list[str] = []
    for token in raw_tokens:
        for part in re.split(r"[;&|()]+", token):
            part = part.strip()
            if part:
                tokens.append(part)
    return CommandView(command=command, tokens=tokens)


def event_matches(
    expected_op: str,
    expected_pattern: str,
    expected_arg: str | None,
    actual_op: str,
    command_view: CommandView | None,
    visible_path: str,
) -> bool:
    if expected_op != actual_op:
        return False
    if actual_op == "exec":
        if not command_view:
            return False
        for index, token in enumerate(command_view.tokens):
            if not exec_pattern_matches(expected_pattern, token):
                continue
            if expected_arg and not any(
                exec_arg_matches(expected_arg, arg)
                for arg in command_view.tokens[index + 1 :]
            ):
                continue
            return True
        return False
    if actual_op in {"read", "write", "open", "unlink"}:
        return bool(visible_path and path_pattern_matches(expected_pattern, visible_path))
    return False


def visible_target_matches(pattern: str, command_view: CommandView | None, visible_path: str) -> bool:
    if visible_path:
        return path_pattern_matches(pattern, visible_path)
    if not command_view:
        return False
    return any(exec_arg_matches(pattern, token) for token in command_view.tokens)


def exec_pattern_matches(pattern: str, token: str) -> bool:
    token = normalize_tool_path(token)
    basename = token.rsplit("/", 1)[-1]
    if "/" not in pattern:
        return glob_matches(pattern, basename) or glob_matches(pattern, token)
    candidates = [token]
    if not token.startswith("/"):
        candidates.append("/" + token)
    return any(glob_matches(pattern, candidate) for candidate in candidates)


def exec_arg_matches(pattern: str, token: str) -> bool:
    token = normalize_tool_path(token)
    basename = token.rsplit("/", 1)[-1]
    return glob_matches(pattern, token) or glob_matches(pattern, basename)


def path_pattern_matches(pattern: str, path: str) -> bool:
    path = normalize_tool_path(path)
    candidates = [path]
    if not path.startswith("/"):
        candidates.append("/" + path)
    return any(glob_matches(pattern, candidate) for candidate in candidates)


def glob_matches(pattern: str, value: str) -> bool:
    pattern = normalize_tool_path(pattern)
    value = normalize_tool_path(value)
    regex = glob_regex(pattern)
    return re.fullmatch(regex, value) is not None


@lru_cache(maxsize=2048)
def glob_regex(pattern: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def eval_expr(expr: Any, labels: set[str]) -> bool:
    kind = expr[0]
    if kind == "true":
        return True
    if kind == "label":
        return expr[1] in labels
    if kind == "not":
        return expr[1] not in labels
    if kind == "and":
        return eval_expr(expr[1], labels) and eval_expr(expr[2], labels)
    if kind == "or":
        return eval_expr(expr[1], labels) or eval_expr(expr[2], labels)
    return False


class Parser:
    def __init__(self, src: str) -> None:
        self.tokens = lex(src)
        self.index = 0

    def peek(self) -> tuple[str, str] | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def next(self) -> tuple[str, str] | None:
        tok = self.peek()
        self.index += 1
        return tok

    def is_word(self, value: str) -> bool:
        tok = self.peek()
        return bool(tok and tok == ("word", value))

    def word(self) -> str:
        tok = self.next()
        if not tok or tok[0] != "word":
            raise ValueError(f"expected word, got {tok!r}")
        return tok[1]

    def string(self) -> str:
        tok = self.next()
        if not tok or tok[0] != "string":
            raise ValueError(f"expected string, got {tok!r}")
        return tok[1]

    def expect_word(self, value: str) -> None:
        got = self.next()
        if got != ("word", value):
            raise ValueError(f"expected {value!r}, got {got!r}")

    def parse_target(self, op: str) -> IfcTarget:
        tok = self.peek()
        if tok and tok[0] == "word" and tok[1] in {"file", "endpoint", "exec"}:
            kind = self.word()
        elif op == "exec":
            kind = "exec"
        else:
            raise ValueError(f"expected target kind for {op!r}, got {tok!r}")
        pattern = self.string()
        arg = self.string() if self.peek() and self.peek()[0] == "string" else None
        return IfcTarget(kind=kind, pattern=pattern, arg=arg)

    def parse_expr(self) -> Any:
        lhs = self.parse_term()
        while self.is_word("and") or self.is_word("or"):
            op = self.word()
            lhs = (op, lhs, self.parse_term())
        return lhs

    def parse_term(self) -> Any:
        if self.is_word("not"):
            self.next()
            return ("not", self.word())
        if self.is_word("true"):
            self.next()
            return ("true",)
        return ("label", self.word())

    def parse_cond(self) -> IfcCond:
        word = self.word()
        if word == "target":
            negate = self.is_word("not")
            if negate:
                self.next()
            return IfcCond(kind="target", negate=negate, pattern=self.string())
        if word == "lineage-includes":
            self.expect_word("exec")
            return IfcCond(kind="lineage-includes", pattern=self.string())
        if word == "after":
            gate_op = self.word()
            gate_pattern = self.string()
            gate_exit = None
            if self.is_word("exits"):
                self.next()
                gate_exit = int(self.word())
            since: list[tuple[str, str, str | None]] = []
            if self.is_word("since"):
                self.next()
                while True:
                    since_op = self.word()
                    since_pattern = self.string()
                    since_arg = self.string() if self.peek() and self.peek()[0] == "string" else None
                    since.append((since_op, since_pattern, since_arg))
                    if self.is_word("or"):
                        self.next()
                    else:
                        break
            return IfcCond(
                kind="after",
                gate_op=gate_op,
                gate_pattern=gate_pattern,
                gate_exit=gate_exit,
                since=tuple(since),
            )
        raise ValueError(f"unknown unless condition {word!r}")

    def parse_clause(self, rule_id: str) -> IfcClause:
        effect = self.word()
        op = self.word()
        target = self.parse_target(op)
        label_expr = ("true",)
        if self.is_word("if"):
            self.next()
            label_expr = self.parse_expr()
        unless = None
        if self.is_word("unless"):
            self.next()
            unless = self.parse_cond()
        return IfcClause(
            rule_id=rule_id,
            effect=effect,
            op=op,
            target=target,
            label_expr=label_expr,
            unless=unless,
            reason="",
        )

    def parse(self) -> tuple[list[IfcSource], list[IfcClause]]:
        sources: list[IfcSource] = []
        clauses: list[IfcClause] = []
        while self.peek():
            keyword = self.word()
            if keyword == "source":
                label = self.word()
                if self.next() != ("eq", "="):
                    raise ValueError("expected '=' in source declaration")
                kind = self.word()
                sources.append(IfcSource(label=label, kind=kind, pattern=self.string()))
            elif keyword in {"declassify", "endorse"}:
                self.word()
                self.expect_word("by")
                self.expect_word("exec")
                self.string()
            elif keyword == "rule":
                rule_id = self.word()
                if self.next() != ("colon", ":"):
                    raise ValueError(f"expected ':' after rule {rule_id!r}")
                start = len(clauses)
                reason = ""
                while self.peek() and self.peek()[0] == "word":
                    word = self.peek()[1]
                    if word in {"notify", "block", "kill"}:
                        clauses.append(self.parse_clause(rule_id))
                    elif word == "because":
                        self.next()
                        reason = self.string()
                    else:
                        break
                for idx in range(start, len(clauses)):
                    clause = clauses[idx]
                    clauses[idx] = IfcClause(
                        rule_id=clause.rule_id,
                        effect=clause.effect,
                        op=clause.op,
                        target=clause.target,
                        label_expr=clause.label_expr,
                        unless=clause.unless,
                        reason=reason,
                    )
            else:
                raise ValueError(f"unknown declaration {keyword!r}")
        return sources, clauses


def parse_policy_text(src: str) -> tuple[list[IfcSource], list[IfcClause]]:
    return Parser(src).parse()


def lex(src: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == "#":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c == ":":
            tokens.append(("colon", ":"))
            i += 1
            continue
        if c == "=":
            tokens.append(("eq", "="))
            i += 1
            continue
        if c == '"':
            i += 1
            value: list[str] = []
            while i < len(src):
                if src[i] == "\\" and i + 1 < len(src):
                    value.append(src[i + 1])
                    i += 2
                    continue
                if src[i] == '"':
                    break
                value.append(src[i])
                i += 1
            if i >= len(src):
                raise ValueError("unterminated string literal in policy")
            tokens.append(("string", "".join(value)))
            i += 1
            continue
        start = i
        while i < len(src) and not src[i].isspace() and src[i] not in '":=':
            i += 1
        tokens.append(("word", src[start:i]))
    return tokens


def format_tool_ifc_feedback(event: ToolPolicyEvent) -> str:
    target = event.command if event.command is not None else event.file_path
    rule_id = event.rule_id.removeprefix("tool-ifc:")
    payload = {
        "tool_ifc_rule": rule_id,
        "effect": event.effect,
        "action": "block" if event.effect == "kill" else "report",
        "tool": event.tool,
        "target": target,
    }
    action = "blocked" if event.effect == "kill" else "reported"
    return (
        f"[tool-ifc] Tool-layer IFC policy {action} rule \"{rule_id}\" "
        f"for {event.tool} {target!r}.\n"
        f"- Reason: {event.reason or 'policy matched this tool call'}\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
