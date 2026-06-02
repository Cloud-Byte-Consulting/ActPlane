# ActPlane Collector

The userspace half of ActPlane: a **project-policy runner + taint-DSL compiler +
reporting shim**. File policies are YAML (`actplane.yaml` or `.actplane/policy.yaml`)
with an embedded `policy: |` DSL block; raw DSL is only accepted through `--rule`
for one-off command-line use. The collector lowers the DSL to the kernel ABI
(`struct taint_config`), runs the embedded eBPF program, and prints each
`TAINT_VIOLATION` the kernel emits with its policy reason. The kernel does all
taint propagation and matching.
Each clause starts with an action verb: `notify`, `block`, or `kill`.
For harness enforcement, `block` denies through BPF LSM when available, while
`kill` makes the action fail by terminating the violating task. If BPF LSM is
not active, tracepoint mode does not support `block`; use `notify` for reporting
or `kill` for harness termination. `actplane run` always prepares
`.actplane/last-violation.txt` and exports the hook environment.

## Build & test

```bash
cargo build --release        # produces target/release/actplane
cargo test                   # DSL compiler unit tests (E1–E13, corpus, ABI)
test/policy-corpus.sh        # YAML policy corpus + release compile microbench
```

## Usage

```bash
sudo -E ./target/release/actplane run -- codex --cd /work
sudo -E ./target/release/actplane --policy ../policies/readonly.yaml run -- claude -p "review"
./target/release/actplane compile --out cfg.bin
./target/release/actplane feedback-hook
```

See [`../docs/rule-language.md`](../docs/rule-language.md) for the policy grammar and 13
worked examples.

## Source layout

- `src/main.rs` — CLI driver. Discovers/loads `actplane.yaml`, calls
  `dsl::compile_str`, dispatches `run` / `watch` / `compile` / setup commands,
  and reports each violation with its reason via `report()`.
- `src/runtime.rs` — loads the embedded eBPF engine through the
  `ebpf-ifc-engine` crate, seeds the `COMMAND` label for `run` targets (or
  `AGENT` for backward compatibility), prepares `.actplane/last-violation.txt`,
  and manages watch/MCP auto-attach lifetimes.
- `src/config.rs` — loads legacy `policy: |` files and domain-based
  `rules:`/`domains:` policy files, then resolves the effective DSL source.
- `src/feedback.rs`, `src/report.rs`, `src/hook.rs`, `src/mcp.rs` — format
  kernel matches into corrective feedback and expose that feedback to agent
  hooks or MCP clients.
- `src/dsl/` — the compiler:
  - `ast.rs` — `Policy` / `Source` / `Rule` / `Clause` / `Expr` / `Cond` / `Xform`.
  - `parse.rs` — hand-rolled lexer + recursive-descent parser for the DSL.
  - `lower.rs` — `#[repr(C)]` mirrors of the kernel structs (`CUpdate`, `CRule`,
    `CConfig`) and
    `compile(Policy) -> Compiled { bytes, reasons, meta, labels }`:
    bit allocation, DNF expansion of label expressions (`dnf()`), and glob lowering
    (`lower_exec` / `lower_path` / `lower_ipv4`, mapping `**`/`*` to EXACT / PREFIX /
    SUFFIX / ANY match kinds and IPs to net+mask).
  - `mod.rs` — `compile_str()` entry point + the test suite.
- `test/policies/` — YAML policy corpus; each file has a `policy: |` block that is
  parsed through the same YAML shape users write.

## ABI contract

`lower.rs`'s `#[repr(C)]` structs are **byte-identical** to the C structs in
`bpf/taint.h`. The compiled blob is serialized with `std::slice::from_raw_parts`
and loaded straight into the eBPF policy maps by `bpf/src/lib.rs`. Any change to
`taint.h` must be mirrored here (and vice versa); the `fixed-size` test guards
the total `CConfig` size against drift.
