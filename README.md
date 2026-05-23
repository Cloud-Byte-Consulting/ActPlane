# ActPlane: OS-Enforced Agent Harnesses

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

ActPlane is an **OS-level harness for AI agents**: it enforces behavioral rules on
an agent's *whole* execution — across any tool, subprocess, or direct syscall —
from the kernel via eBPF, and reports each violation with a human-readable reason
(the corrective-feedback payload).

The motivation: agent constraints today live in prompts (`CLAUDE.md` / `AGENTS.md`),
which are only *probabilistic* — a long-context agent forgets or routes around
them, often non-maliciously. Tool-layer guards (AgentSpec, MCP gateways) only see
the tool API and are bypassed the moment the agent shells out or links an SDK.
ActPlane sits **below the tool layer**: every `exec` / file / network operation is
a syscall, so a rule like *"nothing descended from `codex`, however many hops, may
run `git` or read `secrets.env`"* holds no matter how the agent gets there.

Rules are **information-flow / provenance** rules, not static allow-lists. Taint
labels propagate along fork/exec edges and, as data flow, along file read/write
and network edges, so confidentiality / integrity invariants follow *derived* data
across processes and files. See [`docs/taint-dsl.md`](docs/taint-dsl.md) for the
rule language and 12 worked examples, [`docs/actplane-research-plan.md`](docs/actplane-research-plan.md)
for the framing, and [`docs/related_work.md`](docs/related_work.md) for positioning.

## How it works

```
policy.dsl ──▶ collector (Rust compiler) ──▶ struct taint_config ──▶ eBPF kernel engine
   (rules)        parse + lower to kernel ABI     (rodata blob)        propagate taint,
                                                                       match rules,
   violations ◀────────── NDJSON (TAINT_VIOLATION + reason) ◀───────── emit on match only
```

- **Kernel** (`bpf/`): hooks `fork / exec / exit / open / unlink / rename / connect`,
  keeps a per-node taint label set (process / file / endpoint), propagates it,
  evaluates the compiled rules, and emits **only** `TAINT_VIOLATION` events through
  a single `emit_violation()` function.
- **Collector** (`collector/`): a Rust DSL compiler that lowers a `.dsl` policy to
  the kernel config (`struct taint_config`), runs the embedded loader, and prints
  each violation with its policy reason.

## Build

```bash
make            # builds bpf/ (eBPF programs) then collector/ (Rust)
make test       # bpf C unit tests + collector Rust unit tests
sudo bash test/e2e_examples.sh   # live enforcement of all 12 examples (E1–E12)
```

Requires clang/llvm, libelf, zlib, a recent kernel (5.8+; developed on 6.15), and
a Rust toolchain. `make install` installs the system dependencies (Ubuntu/Debian).

## Run

```bash
# write a policy (full grammar in docs/taint-dsl.md)
cat > codex.dsl <<'EOF'
source AGENT = exec "**/codex"
rule no-git:
  deny exec "**/git" if AGENT
  reason "Codex must not invoke git; use the review workflow."
EOF

sudo ./collector/target/release/actplane codex.dsl      # compile + enforce
# compile only:  ./collector/target/release/actplane codex.dsl --out policy.bin
```

`actplane` compiles the policy, loads the embedded eBPF enforcer, and prints:

```
🚫 BLOCKED: process 'git' (pid 4213, ppid 4210) — /usr/bin/git
   reason: Codex must not invoke git; use the review workflow.
```

## Layout

- `bpf/` — eBPF taint engine (`taint.h` ABI + matchers, `taint_engine.bpf.h` state +
  `te_*` helpers, `process.bpf.c` hooks) and loader (`process.c`); plus the retained
  capture programs (`sslsniff`, `stdiocap`, `browsertrace`). See [`bpf/README.md`](bpf/README.md).
- `collector/` — `src/dsl/` (DSL parser + lowering compiler), `src/main.rs` (driver),
  `src/binary_extractor.rs` (embeds/extracts the eBPF loader). See [`collector/README.md`](collector/README.md).
- `docs/` — research plan, the taint-DSL spec, related work, and reference PDFs.

## Status

The DSL compiler and the kernel matching predicates are unit-tested (`make test`),
the full kernel engine compiles and is accepted by the eBPF verifier, and **all 12
DSL examples (E1–E12) enforce live on a real kernel** (6.15) — verified by
`test/e2e_examples.sh`, which loads each example's policy, fires a trigger, and
checks both the violation and the suppression of the allowed case (latest run:
11/11, E8 folded into E1). The corrective-feedback *loop* (currently a
reason-printing report) and an agent evaluation are the remaining items. This is a
research prototype.
