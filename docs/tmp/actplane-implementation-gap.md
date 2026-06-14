# ActPlane Implementation Gap

This snapshot compares the current repository implementation against the design
claims in the paper and against the minimum shape needed for open-source and
industrial use.

## Executive Summary

ActPlane is close to a usable single-agent, flat-policy harness. The DSL,
compiler, eBPF loader, label propagation core, basic BPF-LSM enforcement,
semantic feedback file, Codex hook, and MCP auto-attach path are present.

The largest remaining gap is productized multi-agent policy domains. ActPlane
now has a runtime process-tree boundary for a single engine instance: only a
seeded root pid, normally the repo agent launched by `actplane run`, `watch`, or
MCP auto-attach, and its fork descendants participate in rule matching and label
propagation. This prevents an unseeded process from being affected by broad
rules such as unconditional exec denies. Runtime-appended rules and updates now
carry a kernel-enforced `domain_id`, and file, endpoint, current-domain process,
provenance, session, and exit-gate state are separated for the global domain and
the process's current runtime domain. Local labels no longer satisfy global
rules, and sibling domains no longer collide through same-numbered local file
labels. A minimal live child-domain control path now exists through the Rust
loader API (`ChildDomainSpec`, `DomainHandle::bind_child_domain`) and the MCP
`bind_child_domain` tool for already-started subagent root pids. Current
`domains:` in YAML are still compile-time policy selection and inheritance.
MCP now has an append-only DSL delta path, runtime metadata merge, JSONL audit
records for reload/bind/append/launch outcomes, and a minimal child-domain
launcher that starts the child stopped, binds its domain, optionally installs a
local policy, then resumes it. The MCP launcher now keeps a local child
registry, persists child metadata under `.actplane/children/`, reloads that
registry on MCP restart, exposes status/listing, bounded stdout/stderr log
reads, and process-group termination for launched subagents. The remaining
product gaps are CLI lifecycle and delta workflows, subagent restart and MCP
protocol e2e coverage, and
complete inherited
ancestor-domain process/gate namespaces.

The second largest gap is hook and flow precision. Enforcement covers exec
identity, file open/create/truncate through open flags, IPv4 connect, process
fork/exec/exit, unlink/rename in tracepoint mode, and stdio pseudo-channels.
It does not yet provide full fd-level file read/write flow, recv ingress,
hostname/network name resolution, or LSM blocking for unlink/rename/truncate.

For a paper-quality system, the domains/delta story and hook coverage need to be
tightened. For industrial use, ActPlane also needs policy review, structured
audit logs, safe rollout modes, and clearer templates around common policies.

## What Is Implemented

### CLI and Project Integration

Implemented:

- `actplane init`, `setup`, `check`, `doctor`, `domains`, `compile`, `run`,
  `watch`, `feedback-hook`, and `mcp`.
- Policy discovery from `actplane.yaml` and `.actplane/policy.yaml`.
- Inline `--rule` support for one-off policies.
- Auto-elevation through passwordless sudo for commands that load eBPF.
- `actplane run` starts the target stopped, loads the engine, seeds the root pid,
  writes hook state, then resumes the target.
- `actplane watch` attaches to the parent agent/shell pid, preserving that pid
  across passwordless sudo elevation, and seeds it as the protected process-tree
  root.
- Codex hook integration forwards new feedback file content into the next model
  turn.
- MCP auto-attach can load the engine around the parent agent, expose policy
  and feedback resources, hot-reload trusted admin policy, and bind an
  already-started subagent pid into a child runtime domain.

Relevant code:

- `collector/src/main.rs`
- `collector/src/runtime.rs`
- `collector/src/hook.rs`
- `collector/src/setup.rs`
- `collector/src/mcp.rs`

### DSL and Compiler

Implemented:

- `source` declarations for `exec`, `file`, and `endpoint`.
- `notify`, `block`, and `kill` clause effects.
- `exec`, `open`, `read`, `write`, `unlink`, `connect`, and `recv` syntax.
- Optional single argv-token predicates for exec rules.
- Boolean label expressions with `and`, `or`, and `not`, lowered by DNF.
- `unless target`, `unless lineage-includes exec`, and `unless after ...`.
- `after exec ... exits N`.
- `since` invalidators for staleness-aware gates.
- `declassify` and `endorse` transforms.
- Fixed-size `#[repr(C)]` config blob matching `bpf/taint.h`.
- Rule metadata for semantic feedback.

Relevant code:

- `collector/src/dsl/ast.rs`
- `collector/src/dsl/parse.rs`
- `collector/src/dsl/lower.rs`
- `collector/src/dsl/mod.rs`
- `bpf/taint.h`

### eBPF Engine

Implemented:

- Writable `ts_updates`, `ts_rules`, and `ts_counts` maps.
- Runtime repo/session boundary through `cap_task`: only seeded pids and their
  fork descendants are active policy subjects for rule matching, label updates,
  file/endpoint flow, and stdio pseudo-channel flow.
- Domain-scoped runtime appended rules and updates: BPF stamps appended entries
  with the requested target domain id and checks that id during rule/update
  scans. Domain `0` remains the inherited/global admin policy domain.
- Domain-keyed file and endpoint object labels: labels written to shared files
  or endpoints by one runtime domain are not read back as same-numbered local
  labels by a sibling domain. File provenance keys carry the same domain bucket.
- Domain-scoped dynamic process state for the global domain and the process's
  current runtime domain. Rule evaluation reads global and current-domain labels
  separately, so a label introduced by a local source cannot satisfy a global
  rule with the same bit number.
- Domain-scoped process provenance, session gates, and exit-qualified gates for
  the same global/current-domain execution path.
- Domain binding resets a pid's inherited process labels to the target domain's
  initial state, so a newly bound child cannot accidentally interpret labels
  copied from its previous domain.
- Process label state, file label state, endpoint label state, root/session gate
  state, exit-qualified gates, and compact provenance maps.
- Fork inheritance.
- Exec label updates, transforms, gates, and argv token matching in the
  post-exec path.
- File open based read/write propagation.
- Numeric IPv4 connect matching and endpoint label flow.
- Staleness via per-session epoch counters.
- BPF-LSM block mode when `bpf` LSM is active.
- Tracepoint mode for notify/kill style observation.
- User ring buffer based whole-policy hot reload.
- Low-level append-delta path with a mask-based capability admission core.
- Map-fd backed runtime domain control handle: `ChildDomainSpec`,
  `DomainHandle::bind_child_domain`, and `Loader::bind_child_domain` create a
  child `cap_state`, seed clean per-domain process state, preserve the parent
  process-tree root, and activate the child pid only after the domain state is
  written.
- Policy feature gates for verifier-heavy path matching and sink classes.
  The Rust and C loaders set the enabled feature set before BPF verification,
  and runtime reload/append rejects unsupported features instead of silently
  accepting rules that cannot execute in the loaded object.

Relevant code:

- `bpf/process.bpf.c`
- `bpf/taint_engine.bpf.h`
- `bpf/capability.bpf.h`
- `bpf/src/lib.rs`
- `bpf/src/capability.rs`

### Feedback

Implemented:

- Kernel emits only `TAINT_VIOLATION` events.
- Userspace maps `rule_id` to rule name, reason, effect, and operation.
- Feedback payloads include the ActPlane prefix, target operation, reason,
  action taken, retry guidance, and a small machine-readable JSON tag.
- Provenance is surfaced for the first matched required label when available.
- Structured violation events are appended to `events.jsonl` alongside the
  text feedback file. Each event records pid/ppid/comm, target, rule id,
  action, effect, matched label, rule metadata when available, and first-label
  provenance.

Relevant code:

- `collector/src/report.rs`
- `collector/src/feedback.rs`
- `collector/src/audit.rs`

## Major Gaps

### P0: Full Policy Domains Are Not Yet Productized Runtime Isolation

Current state:

- `actplane run` starts one stopped target process, loads one engine, seeds that
  target pid, and resumes it. `watch` and MCP auto-attach similarly seed the
  parent agent/shell pid. This makes the repo/session process tree the default
  runtime isolation unit for the current engine.
- The eBPF hot path now ignores unseeded pids before rule matching or label
  propagation. Fork inheritance uses the parent's TGID so policies still follow
  children spawned by non-main threads.
- The kernel ABI includes `domain_id` on `taint_rule` and `taint_update`.
  Whole-policy loads use domain `0`. Runtime append requests are stamped by BPF
  with the target `cap_state` id, and matching walks the `cap_state.parent`
  chain so child domains inherit parent-local rules.
- File labels, endpoint labels, and file provenance are keyed by the active
  runtime domain, so sibling domains can reuse the same local label bit without
  contaminating each other through shared files.
- Dynamic process labels, process provenance, root/session gates, and
  exit-qualified gates are keyed by domain for domain `0` and the process's
  current runtime domain. This closes the important collision where a local
  source's process label bit could satisfy an inherited global rule.
- `Loader::bind_state` resets the bound pid's process label state. This closes
  the common subagent creation case where fork copied parent-domain labels before
  the child was rebound into its local domain.
- `ChildDomainSpec` and `DomainHandle::bind_child_domain` provide a supported
  Rust loader API for creating a child runtime domain below an existing parent
  domain and binding an already-started pid into it. The helper validates
  monotonic authority, target, label, gate, and scope constraints before it
  writes the child domain state.
- MCP auto-attach exposes a minimal `bind_child_domain` tool that binds an
  already-started subagent root pid under the auto-attached repo agent. The
  default child domain can bind self-scoped rules but does not receive
  label-creation authority.
- MCP auto-attach also exposes `append_policy_delta`, which compiles an
  append-only DSL fragment against the target domain's existing label map,
  submits it through the kernel-admitted append path, and merges rule metadata
  so later kernel violations report the appended rule's reason.
- MCP control operations write JSONL audit records for accepted/rejected
  `reload_policy`, `bind_child_domain`, and `append_policy_delta` calls. The
  audit log is created alongside the run feedback file and can be configured
  through `feedback.audit`.
- MCP auto-attach exposes `launch_child_domain`, which starts a subagent command
  stopped, binds it to a child runtime domain, optionally appends local policy,
  resumes it only after setup succeeds, detaches stdout/stderr from MCP stdio,
  and reaps the process in a background waiter. Launched children are recorded
  in a local registry, stdout/stderr are written under `.actplane/children/`,
  and MCP exposes `list_child_domains`, `read_child_domain_logs`, and
  `terminate_child_domain` for status, bounded log collection, and process-group
  termination. The registry is persisted as per-child `meta.json` records and
  reloaded when the MCP server starts. Termination checks Linux process start
  time before signaling so a stale registry entry does not kill a reused pid.
- The C loader's `--seed-pid/--seed-label` path seeds both label state and the
  capability maps required by the runtime boundary.
- YAML `domains:` select a set of locked/default rules at compile time.
- `disable` can remove inherited default rules but not locked rules.
- `actplane check`, `compile`, and `domains` show the selected domain.
- The selected domain is flattened into one ordinary DSL policy before loading.

Missing:

- No in-kernel effective-policy mask per process tree.
- Domain state propagation is implemented for domain `0` and the current bound
  runtime domain. Full ancestor-domain process labels, lineage gates, session
  gates, and invalidator propagation for arbitrary inherited parent domains is
  still missing. Parent-domain rules can be inherited, but label-bearing parent
  domain workflows are not fully represented below the current domain.
- No CLI subagent launcher or lifecycle manager that provides the same stopped
  start, domain bind, optional policy attach, and resume workflow as MCP.
- MCP lifecycle management still lacks a restart operation and supervisor-grade
  reconciliation. Persisted records survive MCP server restarts, but ActPlane
  does not yet relaunch failed subagents or recover a wait handle for an already
  running process.
- No live test yet for two concurrently running top-level agents that each
  append different local policies through the collector or MCP product surface.

Why this matters:

The process-tree boundary is enough to stop one engine from interfering with
unrelated host processes, which is required for open-source usability. The
`domain_id` path prevents a low-level appended local rule from changing a
sibling domain's active policy. Domain-keyed object labels avoid the common
collision where one domain's bit 0 taints a shared file and another domain
interprets that bit as its own label. Domain-keyed current/global process state
also prevents local source labels from tripping global inherited rules. It is
still not the paper's full layered-domain model because userspace can now create
a minimal child domain, but it cannot yet create, audit, and update child-domain
policy as a complete supported workflow, and arbitrary inherited
ancestor-domain process/gate state is not fully propagated.

Minimum fix:

- Promote the MCP child-domain workflow into a matching CLI workflow, and add
  explicit restart/reconcile handling for long-lived subagents.
- Extend domain-scoped process/gate propagation beyond domain `0` and the
  current runtime domain, or constrain the product model so inherited
  parent-domain policies do not rely on dynamic parent-domain labels/gates.
- Keep root/admin rules globally inherited and immutable, and reserve
  whole-policy reload for trusted admin contexts.
- Add product-level live tests for two sibling agents with conflicting local
  rules and metadata-backed feedback.

### P0: Runtime Delta Plumbing Exists, But Is Not Productized

Current state:

- `bpf/capability.bpf.h` defines `cap_state`, `cap_task`, and user-ring-buffer
  delta requests.
- `bpf/src/lib.rs` exposes `submit_delta`, `append_policy_delta`,
  `ChildDomainSpec`, `DomainHandle::bind_child_domain`, and
  `Loader::bind_child_domain`.
- The BPF side rejects label deletion in appended updates and checks coarse
  authority masks.
- Appended rules and updates are kernel-stamped with the target domain id before
  insertion, so a caller cannot submit a supposedly local delta as domain `0`.
- Runtime reload/append is feature-gated by the BPF object that was verified at
  load time. If a new delta requires path `contains`, path suffix, open/write
  sink rules, or connect support that was not enabled for the object, userspace
  returns an error and the BPF admission path also rejects it.
- MCP exposes `reload_policy`, which replaces the whole policy table,
  `bind_child_domain`, which binds an existing subagent pid to a child runtime
  domain, and `append_policy_delta`, which submits a DSL fragment through
  `ReloadHandle::append_policy_delta_with_rule_id_base`. It also exposes
  `launch_child_domain`, which wraps stopped start, bind, optional append, and
  resume into one lifecycle operation.
- Runtime policy metadata is now mutable in the MCP auto-attach path.
  Whole-policy reload replaces the global metadata table, and append-only
  deltas extend it with a rule-id base that matches the kernel-stamped appended
  entries.
- Runtime delta compilation preserves a per-domain label-bit dictionary, so
  split deltas in the same runtime domain do not silently remap an existing
  label name to a different bit.
- Feedback lookup is rule-context based: appended local rules carry their own
  label-name map, which avoids misnaming same-numbered labels reused by a
  sibling domain.
- Accepted/rejected MCP reload, child-domain bind, and append-delta operations
  are appended to a structured JSONL audit log. Records include event type,
  status, actor pid, target/child domain ids where applicable, rule-id base and
  rule count for accepted deltas, deterministic policy hash, and rejection
  error text.

Missing:

- No CLI command submits append-only DSL deltas.
- No project YAML mapping from domains to kernel `cap_state`.
- Audit records are useful but still minimal. They do not yet include a stable
  user/session identity, source-line spans, policy/rule source text, or
  supervisor approval metadata.
- `reload_policy` is powerful: it can replace the whole active table and should
  be treated as trusted-admin functionality, not ordinary agent
  self-restriction.
- Feature-gated reload means a running object cannot be expanded to new
  verifier-heavy matcher classes or sink classes without restart. This is safe,
  because it rejects unsupported deltas, but it is not yet a smooth product
  experience.

Minimum fix:

- Add an explicit `actplane delta add` CLI API for the same append path.
- Extend audit records with stable actor/session identity, policy/rule source
  provenance, and supervisor approval metadata.
- Add end-to-end MCP tests that bind a child domain, append a local delta, and
  verify feedback metadata for the appended rule.
- Surface feature-gate rejections as actionable feedback, and either restart
  with a richer feature set or provide prebuilt BPF variants for common policy
  classes.
- Reserve whole-policy reload for trusted supervisor/admin contexts.

### P0: Hook Coverage Is Incomplete For Security Claims

Current state:

- BPF-LSM programs are registered for `bprm_check_security`, `file_open`,
  `file_permission`, `file_truncate`, `path_truncate`, `path_unlink`,
  `path_rename`, and `socket_connect`.
- The active implementations are `bprm_check_security`, `file_open`, and
  `socket_connect`.
- `file_permission`, `file_truncate`, `path_truncate`, `path_unlink`, and
  `path_rename` are stubs.
- Tracepoints observe open/openat/openat2/creat/truncate, unlink, rename,
  connect, fork, exec, exit, and stdio read/write.

Missing:

- `block unlink` and `block rename` are not implemented in LSM.
- `block truncate` through truncate-specific LSM hooks is not implemented.
- `recv` is parsed and lowered but no live receive hook enforces it.
- Hostname endpoint globs do not work in-kernel. Connect matching is numeric
  IPv4 only.
- IPv6 is not covered.
- Exec argv-token rules cannot be blocked pre-exec because argv slots are only
  available after exec. This is documented, but the BPF-LSM active path needs
  a live regression test to ensure argv-sensitive `kill`/`notify` still fires
  through the post-exec tracepoint path.

Minimum fix:

- Wire `path_unlink`, `path_rename`, and truncate LSM hooks to
  `te_handle_file`.
- Add a clear backend matrix in `actplane check`: which rules are pre-op
  blockable, post-op killable, notify-only, or unsupported on this host.
- Add receive-side hooks or remove `recv` from the supported surface until it is
  implemented.
- Add userspace DNS/SNI/IP expansion for host policies, or restrict the DSL docs
  to numeric IPv4 for enforcement claims.

### P0/P1: File Flow Is Mostly Open-Time, Not Full fd-Level IFC

Current state:

- File labels are applied and propagated when a file is opened with read/write
  flags.
- LSM mode uses `(dev, inode)` identity when available.
- Tracepoint mode falls back to path hashing.
- `read` and `write` tracepoints currently model only stdio pseudo-files
  (`stdio:stdin`, `stdio:stdout`, `stdio:stderr`).

Missing:

- No fd-to-file map for ordinary file descriptors.
- If a process opens an output file, later reads a secret, then writes to the
  already-open output fd, the current engine can miss the file-label flow.
- If a process opens a file for read but never reads from it, the current engine
  may over-taint at open time.
- `mmap`, `sendfile`, pipes, Unix sockets, and shared memory are not modeled.
- There is no precise per-gate file consumption set for staleness. The current
  session-level epoch model is useful but can over- or under-approximate
  freshness in complex multi-file workflows.

Minimum fix:

- Track `pid,fd -> file_id` at open/close/dup.
- Apply read flow at actual read-like operations and write flow at actual
  write-like operations.
- Cover close, dup/dup2/dup3, pipe, and common zero-copy paths at least enough
  to avoid silent bypasses in agent workloads.
- Decide whether open-time over-taint remains an acceptable conservative mode
  for v1, and document it if so.

### P1: Policy Generation, Review, And Templates Are Not Implemented

Current state:

- `actplane init` writes a starter policy.
- `actplane check` validates and summarizes rules.
- The repository contains evaluation-time policy corpora and generated policies.

Missing:

- No built-in generator from `AGENTS.md`, `CLAUDE.md`, project config, and the
  current task.
- No template library for common policies such as no protected-branch push,
  tests before commit, no secret egress, no writes outside workspace, or
  no dependency update unless requested.
- No review workflow that shows the natural-language source, generated DSL,
  concrete paths/commands/endpoints, and expected effect.
- No dry-run/observe-first rollout helper that recommends which rules are safe
  to promote from notify to block/kill.

Minimum fix:

- Add a template catalog with parameterized policies.
- Add a `check --explain` or `plan` command that prints the concrete OS-level
  interpretation of each rule.
- Add a policy review artifact that can be committed or attached to CI.

### P1: Audit And Feedback Need Structured State

Current state:

- Feedback is appended to a text file and forwarded by hooks.
- Ring-buffer events are decoded in-process.
- A small JSON tag is appended inside the human feedback payload.
- Structured violation events are appended as JSONL using schema
  `actplane.violation.v1`.

Missing:

- No stable policy/rule provenance: source text, generator, approver, hash,
  domain, and activation time.
- Structured records include the backend action, including unsupported block
  requests, but they do not yet include a host support matrix or exact backend
  support reason.
- Multi-clause rules report the first metadata operation in feedback, not
  necessarily the exact matched clause's source operation.
- Provenance reports one required label origin, not the full causal chain or all
  matched labels.

Minimum fix:

- Add policy hash, rule hash, domain/session id, exact matched op/effect,
  support status, and richer provenance fields.
- Keep human feedback as a formatted view over the structured event.

### P1: Evaluation Coverage Is Not Yet CI-Grade

Verified in this snapshot:

- `cargo test --locked -p actplane --tests`: 62 unit tests passed, 1 ignored,
  plus 4 CLI UX tests passed.
- `cargo test --locked -p ebpf-ifc-engine --lib`: 8 tests passed, 8 live eBPF
  tests ignored.
- `make -C bpf test`: 35 matcher/arg/mask tests passed.
- Live BPF-LSM smoke tests, run with passwordless sudo:
  `unseeded_processes_do_not_match_global_policy`,
  `append_policy_delta_admits_self_rule_smoke`,
  `append_policy_delta_scopes_to_target_domain_and_descendants_smoke`,
  `domain_handle_binds_subagent_child_domain_smoke`,
  `sibling_domain_file_labels_do_not_collide_smoke`,
  `binding_domain_resets_inherited_process_labels_smoke`, and
  `local_domain_process_labels_do_not_satisfy_global_rules_smoke` passed.
- `cargo fmt --check` passed.

Not verified here:

- Live tracepoint-only behavior.
- E2E example suite with `sudo`.
- End-to-end cross-agent/domain non-interference through the full MCP protocol.
  The Rust loader API path is covered by
  `domain_handle_binds_subagent_child_domain_smoke`, and MCP append metadata is
  covered by unit tests rather than a live protocol test. MCP stopped-launch
  mechanics are unit-tested, but the full bind/append/resume protocol path is
  not yet covered by an MCP e2e test.
- Runtime reload latency smoke in the latest feature-gated object.
- LSM support matrix for argv-sensitive exec rules, unlink/rename/truncate,
  and fd-level file flow.

Minimum fix:

- Keep the refreshed `Cargo.lock` and make `--locked` builds part of CI.
- Add a privileged CI or nightly job with BPF-LSM active.
- Add a tracepoint-only matrix using `ACTPLANE_FORCE_TRACEPOINT` or an
  equivalent loader knob.
- Promote the ignored reload and append-delta smoke tests into a documented
  privileged test target.
- Add regression cases for open-before-taint, unlink/rename block, argv exec
  kill, and product-level sibling-domain isolation.

### P2: Documentation Drift

Current drift:

- `README.md` describes the high-level product well, but still uses legacy
  `policy: |` examples while `actplane init` now emits `rules:`/`domains:`.
- `bpf/README.md` describes an illustrative API that is not the actual API and
  lists old size limits.
- `docs/rule-language.md` has the most accurate current limitations paragraph,
  but it is not reflected consistently in README or paper text.
- The paper presents layered policy domains as a completed product surface,
  while the current implementation has the in-kernel rule/update scoping core,
  global/current-domain label and gate state, and compile-time YAML domain
  selection, plus a minimal live child-domain bind API and MCP append-only DSL
  deltas with in-memory metadata merge, JSONL audit records, and an MCP
  stopped-start child-domain launcher with persisted metadata, status, bounded
  log reads, and process-group termination. It still lacks CLI delta/lifecycle
  workflows, richer audit provenance, subagent restart/reconcile operations, and complete
  inherited ancestor-domain label/gate propagation.

Minimum fix:

- Make one status matrix the source of truth and link it from README, paper
  appendix, and rule-language docs.
- Separate "implemented", "experimental", and "paper design" surfaces.
- Update examples to consistently use either legacy flat policy or the new
  domain schema, depending on the target audience.

## Priority Roadmap

### P0: Make Claims Safe

1. Decide the domain claim:
   - If v1 is single-session flat policy, say so and weaken the paper/product
     language around layered runtime domains.
   - If v1 needs full multi-agent isolation, finish the child-domain workflow,
     richer audit provenance, CLI delta/lifecycle paths, MCP e2e tests, and
     inherited ancestor-domain propagation before making that claim.
2. Fix the enforcement support matrix:
   - LSM path hooks for unlink/rename/truncate.
   - Confirm argv-sensitive kill/notify behavior when BPF-LSM is active.
   - Warn on unsupported effects in `actplane check`.
3. Add fd-level file flow for ordinary file descriptors or document open-time
   flow as a conservative approximation with known misses.
4. Keep whole-policy reload restricted to trusted contexts.

### P1: Make It Useful For Real Users

1. Extend structured JSONL audit logs with stable actor/session identity and
   policy/rule provenance.
2. Add templates and `check --explain`.
3. Add agent-facing CLI delta and child-launch APIs that share the same audit
   path as MCP.
4. Add privileged CI/e2e coverage for BPF-LSM and tracepoint modes.
5. Add safe rollout modes: observe-only, warn, block selected rules, fail closed
   for high-severity rules.

### P2: Clean Up Surface Area

1. Update README and `bpf/README.md`.
2. Make examples consistently use `COMMAND`/`AGENT` labels.
3. Remove or mark unsupported DSL surfaces such as `recv` until the hooks exist.
4. Add a small support matrix table to the paper appendix.

## Bottom Line

For a local single-agent harness with flat policies, ActPlane now has the
minimum necessary isolation shape: the engine is active only for the seeded
repo/session process tree. For the paper's strongest design claim, the kernel
has real domain-scoping primitives for appended local policy, object labels, and
current/global process labels, plus a minimal supported child-domain bind API.
MCP can launch stopped child-domain processes, append scoped DSL deltas with
in-memory metadata merge, keep a live child registry, expose bounded log reads,
terminate child process groups, persist child metadata, reload the registry on
MCP restart, and write JSONL audit records. The missing pieces
remain CLI delta/lifecycle surfaces, richer audit provenance, subagent restart
and reconciliation, full inherited ancestor-domain process/gate
propagation, inherited immutable admin policy metadata, and full MCP protocol
e2e coverage. For
industrial use, the next hard requirements are fd-precise file flow, complete
hook support for security effects, policy review, and rollout workflow.
