# ActPlane: OS-Enforce AI Agent Harnesses with eBPF

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

ActPlane is an **OS-level harness for AI agents**. It lets you or AI agents write behavioral
contracts for your agent in YAML, and enforces them deterministically at the OS
level via eBPF, across every process, file access, and network connection, no
matter how the agent gets there with scripts or commands. When a contract is violated, ActPlane blocks the action and feeds the reason back to the agent so it self-corrects.

Prompt constraints are probabilistic. ActPlane is deterministic.

## Quickstart

Install with one command. The eBPF program ships prebuilt (CO-RE, architecture
independent), so there is **no clang/llvm/libbpf to install** — just a Rust
toolchain:

```bash
cargo install actplane
```

Write a policy and run an agent (or any command) under enforcement:

```bash
actplane init                                  # write a starter actplane.yaml
actplane check                                 # validate rules (no privileges)

sudo -E actplane run claude -p "review this repo"
```

When the agent violates a rule, ActPlane kills the action and tells it why:

```
🚫 KILLED: process 'git' (pid 4213, ppid 4210) — /usr/bin/git
   effect: kill
   reason: no git under the agent; use the review workflow
```

The agent receives this reason through its hook integration, understands the
constraint, and takes a different path to complete the task.

**Requirements:** Linux kernel 5.8+ with BTF (`/sys/kernel/btf/vmlinux`). `run`
and `watch` load the eBPF enforcer, so they need root (or `CAP_BPF` +
`CAP_SYS_ADMIN`); ActPlane drops the target command back to your user. With
BPF-LSM enabled, rules can `block` before the action commits; otherwise they
`audit` (report) or `kill`.

## Why an OS-level harness?

Agent constraints today come in three forms. Each solves a real problem but
leaves a gap that the next layer down needs to cover.

| Approach | What it does | What it can't cover |
|----------|-------------|---------------------|
| **Prompt constraints** (`CLAUDE.md`, `AGENTS.md`) | Tell the agent what to do and not do | Probabilistic: long-context agents forget or route around them, often non-maliciously |
| **Tool-layer guards** (MCP gateways, AgentSpec) | Intercept and authorize at the tool API | Bypassed the moment the agent shells out, links an SDK, or spawns a subprocess |
| **Sandboxes** (containers, VMs, E2B, Daytona) | Isolate the entire execution environment | All-or-nothing: can't express "file A must only be accessed via script A" or "run tests before committing" |

ActPlane sits below all three, at the OS level. Every `exec`, file open, and
network connect goes through the kernel, so a rule like *"nothing descended from
`codex`, however many hops, may run `git` or modify files outside `/work`"*
holds regardless of which tool path the agent takes.

The key differences:

- **OS-level coverage**: enforcement happens at the kernel, not the tool API. Bash, Python subprocess, direct SDK calls, all covered.
- **Call-chain granularity**: rules follow process lineage, not just single operations. "Codex's entire subprocess tree cannot touch git" is one rule.
- **Corrective feedback, not just blocking**: violations feed a human-readable reason back to the agent, so it can retry a different way. This is what makes it a harness, not a sandbox.
- **Agent-maintained rules**: the rule language is designed so agents can write, validate (`actplane check`), and evolve their own contracts.

## Harness, not just a sandbox

A sandbox draws an isolation boundary: everything inside is allowed, everything
outside is denied. That works for untrusted code, but agents need something
richer.

- **Data-flow constraints**: a sandbox only guards the boundary. A harness can express "data read from A must never flow to B", across arbitrary fork/exec chains.
- **Causal ordering**: a sandbox cannot express "run tests before committing". A harness can, via `since` clauses and gate invalidation.
- **Corrective feedback**: a sandbox returns EPERM and the agent is stuck. A harness returns a human-readable reason, so the agent retries a different way.
- **Agent-authored rules**: a sandbox is imposed externally. A harness is collaborative: the agent writes, validates (`actplane check`), and evolves its own contracts.

Sandboxes answer "can this process access this resource?" A harness answers a
broader set of questions: not just security ("secret data must not reach the
network") but also software engineering discipline ("run tests before
committing", "don't mix data from independent tasks in one commit", "use the
migration tool to access prod.db"). These are workflow constraints, not access
control, and they are exactly the kind of rules agents need to operate
autonomously in real codebases.

A harness also subsumes sandboxing when you need it. When an agent spawns a
sub-agent or runs an untrusted command, you can write a rule that confines the
entire subtree to read-only, no-network, or a specific directory. This is
especially important when agents cross vendor boundaries: Codex calling Claude
Code, or the other way around. Framework-level guards from different vendors
don't compose, but OS-level rules follow process lineage regardless of which
runtime is underneath.

## How rules work

Rules are **labeled information-flow contracts**, not static allow-lists.
Labels propagate along fork/exec edges and file read/write edges, so
constraints follow derived data across processes and files.

```yaml
# actplane.yaml
version: 1
policy: |
  label AGENT

  rule no-git-branch:
    deny exec "**/git" @arg "branch"   if AGENT
    deny exec "**/git" @arg "worktree" if AGENT
    effect kill
    reason "This workspace forbids creating git branches or worktrees."
    remediation "Use other git commands, or ask the user to manage branches"
```

The agent can run `git commit`, `git status`, `git push`, but the moment
anything in its process tree tries `git branch` or `git worktree`, the kernel
kills it and feeds the reason back so the agent self-corrects.

See [`docs/rule-language.md`](docs/rule-language.md) for the full rule language and
worked examples.

## Agent integration

ActPlane feeds violation reasons back to agents via their hook systems.

**Claude Code** (`.claude/settings.local.json`):

```json
{
  "hooks": {
    "PostToolUse": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "/path/to/actplane feedback-hook" }] }],
    "PostToolUseFailure": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "/path/to/actplane feedback-hook" }] }]
  }
}
```

**Codex** (`.codex/hooks.json`):

```json
{
  "hooks": {
    "PostToolUse": [{ "matcher": ".*", "hooks": [{ "type": "command", "command": "/path/to/actplane feedback-hook" }] }]
  }
}
```

The adapter forwards new violations as hook context. The kernel remains the sole
authority for enforcement. See [`script/CLAUDE.snippet.md`](script/CLAUDE.snippet.md)
for the agent instruction snippet.

## How it works

```
actplane.yaml ─▶ collector (Rust) ─▶ .rodata config ─▶ eBPF kernel engine
 policy: |        parse + lower DSL    (set_global)      propagate labels,
                                                          match rules,
 violations ◀──── ring buffer (in-process, via aya) ◀─── emit on match only
```

- **Kernel** (`bpf/`): hooks `fork / exec / exit / open / unlink / rename / connect`,
  keeps a per-node label set (process / file / endpoint), propagates labels,
  evaluates compiled rules, emits only violation events.
- **Collector** (`actplane`): discovers `actplane.yaml`, compiles the DSL to the
  kernel config, and loads the prebuilt eBPF object in-process via
  [`actplane-bpf`](bpf/) (aya) — no libbpf/clang at runtime — seeds the target
  process lineage, and reports violations with policy reasons.

## Build from source

`cargo install actplane` is all most users need. To hack on ActPlane:

```bash
git clone --recurse-submodules https://github.com/eunomia-bpf/ActPlane
cd ActPlane/collector && cargo build --release   # uses the prebuilt eBPF object
```

Editing the kernel eBPF (`bpf/*.bpf.c`) requires the BPF toolchain
(clang/llvm, libelf, zlib) and the `libbpf`/`bpftool` submodules. Rebuild and
refresh the committed object with:

```bash
ACTPLANE_REBUILD_BPF=1 cargo build -p actplane-bpf   # regenerates bpf/prebuilt/process.bpf.o
```

Run the tests:

```bash
make test                          # bpf C unit tests + collector Rust unit tests
sudo bash script/e2e_examples.sh   # live E1–E12 enforcement
```
