# ActPlane: Deterministic OS-Level Rules for AI Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Define what your agent can and cannot do in a YAML file. eBPF enforces it on every syscall, no matter how the agent gets there.**

Prompt-level constraints (`CLAUDE.md`, `AGENTS.md`) are probabilistic: a long-context agent forgets or routes around them. Tool-layer guards only see the tool API and are bypassed when the agent shells out or links an SDK directly. ActPlane sits below the tool layer at the kernel: every `exec`, file open, and network connect is a syscall, so a rule like "nothing descended from `codex` may run `git` or modify files outside `/work`" holds regardless of how the agent reaches that operation.

When a rule is violated, ActPlane can **block** (BPF-LSM pre-operation denial), **kill** (terminate the violating task), or **audit** (report only), and feeds a human-readable reason back to the agent so it can self-correct.

> **Status:** Research prototype. The DSL compiler and kernel matching predicates are unit-tested. See [Status](#status) for current gaps.

## Quickstart

```bash
make                     # build eBPF programs + Rust collector
A=./collector/target/release/actplane

$A init                  # write a starter actplane.yaml
$A check                 # validate rules (no privileges needed)
sudo -E $A run -- bash -lc 'git branch x'   # enforce around any command
```

`check` summarizes every rule and warns about anything that won't enforce:

```
✓ ./actplane.yaml: 3 rule(s) compile.
  1. no-git-branch    — deny exec    → kill (create branches/worktrees on the host…)
  2. no-secret-exfil  — deny connect → kill (data derived from local secrets must not leave…)
  3. test-before-commit — deny exec  → kill (run the tests before committing)
✓ no warnings.
```

When enforcement triggers:

```
🚫 KILLED: process 'git' (pid 4213, ppid 4210) — /usr/bin/git
   effect: kill
   reason: Codex must not invoke git; use the review workflow.
```

## How it works

```
actplane.yaml ─▶ collector (Rust) ─▶ struct taint_config ─▶ eBPF kernel engine
 policy: |        parse + lower DSL      (rodata blob)       propagate labels,
                                                              match rules,
 violations ◀──── NDJSON (TAINT_VIOLATION + reason) ◀─────── emit on match only
```

Rules are **labeled information-flow contracts**, not static allowlists. Labels propagate along fork/exec edges and file read/write edges, so constraints follow derived data across processes and files. See [`docs/taint-dsl.md`](docs/taint-dsl.md) for the rule language and 12 worked examples.

## Agent integration

ActPlane feeds violation reasons back to the agent via hooks so it can self-correct.

**Claude Code** (`.claude/settings.local.json`):

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "*",
      "hooks": [{ "type": "command", "command": "/path/to/actplane feedback-hook" }]
    }],
    "PostToolUseFailure": [{
      "matcher": "*",
      "hooks": [{ "type": "command", "command": "/path/to/actplane feedback-hook" }]
    }]
  }
}
```

**Codex** (`.codex/hooks.json`):

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": ".*",
      "hooks": [{ "type": "command", "command": "/path/to/actplane feedback-hook", "statusMessage": "Checking ActPlane feedback" }]
    }]
  }
}
```

Launch the agent through ActPlane so enforcement is active:

```bash
sudo -E actplane run -- codex --cd "$PWD"
sudo -E actplane run -- claude -p "review this repo"
```

## Build

```bash
make            # builds bpf/ (eBPF programs) then collector/ (Rust)
make test       # bpf C unit tests + collector Rust unit tests
```

Requires clang/llvm, libelf, zlib, a recent kernel (5.8+; developed on 6.15), and
a Rust toolchain. `make install` installs the system dependencies (Ubuntu/Debian).

## Layout

- `bpf/` — eBPF taint engine and hooks. See [`bpf/README.md`](bpf/README.md).
- `collector/` — DSL parser, compiler, and runner. See [`collector/README.md`](collector/README.md).
- `script/` — e2e examples and agent instruction snippets.
- `docs/` — the taint-DSL spec, related work, and research plan.

## Status

The DSL compiler and kernel matching predicates are unit-tested (`make test`).
BPF-LSM hooks cover exec, file access/mutation, and IPv4 connect blocking, with
tracepoint violation reporting and `effect kill` termination when BPF-LSM is not
available. Remaining gaps: full `@arg` pre-exec blocking, hostname/SNI network
policy, inode-first file identity, and a clean live e2e suite.

This is a research prototype.
