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
carry a kernel-enforced `domain_id`, and file, endpoint, process provenance,
session, and exit-gate state are separated across the active domain chain:
global domain `0`, the process's current runtime domain, and inherited ancestor
runtime domains. Local labels no longer satisfy global rules, inherited
parent-domain rules can observe their own dynamic labels and gates in
descendants, and sibling domains no longer collide through same-numbered local
file labels. The kernel now maintains a `cap_policy` mask per runtime domain,
so a process tree's effective policy is the union of explicitly bound rule
indices along its domain chain rather than an implicit scan of every rule in
the global table. A minimal live child-domain control path now exists through
the Rust loader API (`ChildDomainSpec`, `DomainHandle::bind_child_domain`) and
the MCP `bind_child_domain` tool for already-started subagent root pids.
Current `domains:` in YAML are still compile-time policy selection and
inheritance.
MCP now has an append-only DSL delta path, runtime metadata merge, JSONL audit
records for reload/bind/append/launch outcomes, and a minimal child-domain
launcher that starts the child stopped, binds its domain, optionally installs a
local policy, then resumes it. The MCP launcher now keeps a local child
registry, persists child metadata under `.actplane/children/`, reloads that
registry on MCP restart, exposes status/listing, bounded stdout/stderr log
reads, and process-group termination for launched subagents. CLI now also has a
local control surface for already-running MCP auto-attached and `watch` engines
through `.actplane/control.json`: it can check status, hot-reload trusted
policy, bind an existing child pid, append a domain-local DSL delta, launch a
stopped child with an optional pre-resume delta, list child domains, read child
logs, and terminate or restart launched child process groups. Restart uses a
fresh runtime domain by default so stale dynamic labels from the old child
domain do not carry into the replacement. A background supervisor now
periodically reconciles child records and relaunches children marked with
`restart_policy=on_exit` into a fresh domain after an unexpected exit, with a
persisted restart count, restart limit, restart backoff, explicit
restart-limit blocked status, and a JSONL audit event when automatic relaunch is
exhausted. After an MCP server restart, still-running registry records are
adopted under polling-based supervision and can be relaunched when they later
exit, with the limitation that exit code/signal precision is unavailable for
adopted processes. Basic runtime audit context, stable process identity for
audit actors, parser-backed lowered-clause source provenance, machine-readable
backend support reports, and a project-configured append-delta approval
admission gate are now present. Basic
domain-local runtime declassification is now admitted by the kernel when the
submitting domain has `AUTH_DECLASSIFY` and label authority for the cleared
bits, which covers the paper's core "clear labels within an authoring domain"
mechanism without letting a child clear inherited higher-authority labels. Basic
multi-client local-control socket stress is covered, and the live watch/control
and MCP/control e2es now exercise concurrent control clients against loaded
engines. Violation events now use per-lowered-rule metadata, so a multi-clause
policy reports the exact matched clause operation, kernel operation, effect, and
target metadata instead of a rule-level summary. The kernel also falls back from
process provenance to file/endpoint object provenance when a sink matches a
stored object label before that label has been copied into the process. The
remaining evaluation gap is promoting these privileged stress paths into
CI/nightly and scaling them beyond the current smoke-test volume.

The second largest gap is hook and flow precision. Enforcement covers exec
identity, file open/create/truncate through open flags, IPv4 connect, process
fork/exec/exit, unlink/rename/truncate in BPF-LSM and tracepoint modes, and
stdio pseudo-channels.
Tracepoint mode now attributes connected IPv4 receive and unconnected UDP
`recvfrom`/`recvmsg` source addresses, but it does not yet provide IPv6,
hostname/network name resolution, batch UDP syscall coverage, or coverage for
shared memory. File-backed mmap is covered at mapping creation for read/exec
mappings and shared writable mappings, with the same conservative
write-at-map-time precision tradeoff as other eager flows. BPF-LSM
`file_mprotect` covers later file-backed mprotect permission changes
pre-operation. Tracepoint mode keeps a bounded fallback for the eight most
recent exact-start file-backed mappings per pid, which propagates mprotect
read/exec source reads and shared-writable `mprotect`/`mremap` flows after
successful syscalls but is not a complete VMA shadow index. Tracepoint mode also
models pathname and abstract-name `AF_UNIX` sockets as file-like IPC objects
after bind/connect/accept or address-bearing datagram sendto/sendmsg, including
fork inheritance and subsequent read/write or send/recv flow. Tracepoint mode also
tracks received SCM_RIGHTS fds after successful `recvmsg`, scanning the first
two ancillary control messages, accepting up to eight fds per SCM_RIGHTS
message, and reusing known fd object identity when the sent fd was already
modeled.

The hook attach surface is now policy-budgeted rather than globally eager.
Process lifecycle, exec identity, and the runtime control tick are always
attached for domain isolation and runtime control. File and endpoint hooks are
attached only when the initial policy or selected hook profile reserves those
features. Advanced file-flow hooks, including mmap/mprotect fallback,
SCM_RIGHTS, Unix-socket IPC, pipe/socketpair, sendfile, copy_file_range, and
splice, are off by default and require `ACTPLANE_ENABLE_ADVANCED_HOOKS=1` or
`ACTPLANE_HOOK_PROFILE=full`. Runtime deltas cannot widen the attached hook set
after load. A delta that adds file flow is therefore rejected unless the engine
was started with a file-flow budget or the full hook profile. A delta that adds
`block` on exec, file, or connect is similarly rejected unless the corresponding
LSM hook budget was reserved at load time. The full profile reserves hook and
flow features, but it does not unconditionally enable file sink rule matching or
verifier-expensive path matcher extensions such as contains/suffix. Those rule
matching features still need to appear in the initial policy if later deltas
require them. MCP auto-attach, watch, and child-run reserve file-flow hooks
because those product surfaces can install child-domain file-source deltas after
the initial policy load. Standalone loader users can request the same budget
with `ACTPLANE_RESERVE_FILE_FLOW=1`. Ordinary file-flow, `notify`, and `kill`
policies now use tracepoint file hooks by default. BPF-LSM file hooks such as
`file_permission`, `file_open`, and path mutation hooks are reserved for
`block open/write` policies or the explicit full hook profile.

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
- Stopped-start launch paths now wait until the wrapper process is actually in
  the kernel stopped state before installing domain state and sending
  `SIGCONT`. This avoids the race where a fast no-delta launch could receive
  `SIGCONT` before it executed `kill -STOP $$`.
- `actplane watch` attaches to the parent agent/shell pid, preserving that pid
  across passwordless sudo elevation, and seeds it as the protected process-tree
  root. It exposes the same repo-local control socket as MCP auto-attach, with
  the elevated control process bound as a submitter in the attached parent
  domain.
- Codex hook integration forwards new feedback file content into the next model
  turn.
- MCP auto-attach can load the engine around the parent agent, expose policy
  and feedback resources, hot-reload trusted admin policy, and bind an
  already-started subagent pid into a child runtime domain.
- `actplane control ...` can talk to an already-running MCP auto-attached or
  `watch` engine through a repo-local Unix socket state file and operate the
  same reload, bind, append, launch, list, log-read, terminate, restart, and
  reconcile paths.

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
- In-kernel effective-policy masks: `cap_policy` records the rule indices bound
  to each runtime domain. Rule evaluation first checks the active domain's mask
  or an inherited ancestor/global mask before evaluating the rule body.
- Domain-keyed file and endpoint object labels: labels written to shared files
  or endpoints by one runtime domain are not read back as same-numbered local
  labels by a sibling domain. File provenance keys carry the same domain bucket.
- Domain-scoped dynamic process state for the active domain chain. Rule
  evaluation reads labels from the matched rule's own domain, so a label
  introduced by a local source cannot satisfy a global or parent-domain rule
  with the same bit number.
- Domain-scoped process provenance, session gates, and exit-qualified gates for
  the same active-domain-chain execution path.
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
- Userspace maps `rule_id` to one lowered kernel rule's name, reason, effect,
  declared clause operation, matched kernel operation, target kind, target
  pattern, and optional target argument.
- Feedback payloads include the ActPlane prefix, target operation, reason,
  action taken, retry guidance, and a small machine-readable JSON tag.
- Provenance is surfaced for one matched required label when available. For
  stored file and endpoint labels, the kernel falls back to object provenance if
  the process label provenance has not yet been populated. Structured events
  now enumerate every matched label in `matched_label_details`, including each
  label's name, mask, provenance status, and a single-hop causal-chain entry
  when the kernel reported an origin for that label.
- Structured violation events are appended to `events.jsonl` alongside the
  text feedback file. Each event records pid/ppid/comm, target, rule id,
  action, effect, matched label mask, per-label matched details, rule metadata
  when available, and reported single-hop provenance. Rule metadata now
  includes lowered-clause operation/effect/target fields plus source ref,
  source line span, parser-backed lowered-clause source index, exact
  lowered-clause line span and text, source/clause hashes, and locked/default
  binding mode when those fields are known.

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
- The kernel also maintains `cap_policy`, a runtime-domain policy mask over the
  128 rule-table slots. Initial load, whole-policy reload, and append-only
  deltas bind rule indices into that mask. Rule evaluation skips a rule unless
  its `domain_id` is present in the process tree's current domain chain and the
  rule index is explicitly active in that domain's mask.
- File labels, endpoint labels, and file provenance are keyed by the active
  runtime domain, so sibling domains can reuse the same local label bit without
  contaminating each other through shared files.
- Dynamic process labels, process provenance, root/session gates, and
  exit-qualified gates are keyed by domain for domain `0` and the process's
  current runtime domain. This closes the important collision where a local
  source's process label bit could satisfy an inherited global rule.
- Exec updates, file read/write flow, connect flow, fork inheritance, exit-gate
  completion, and rule evaluation now walk the active domain chain. A child
  domain therefore inherits parent-domain rules without collapsing label state:
  parent-domain source labels, lineage gates, session gates, invalidators, and
  file labels remain in the parent namespace and are still visible to that
  parent's inherited rules when a descendant process acts.
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
- Launched child records now carry an explicit `restart_policy`. During
  `reconcile_child_domains`, a child marked `on_exit` that has exited and has
  not already been replaced is relaunched with the recorded command, local
  policy, and scope in a fresh runtime domain. The old record is persisted with
  `replacement_child_id`, and the replacement records `restarted_from`.
- Restart metadata is bounded and persisted: each child record stores
  `restart_count`, `restart_limit`, `restart_backoff_ms`, and
  `last_exit_unix_ms`. A replacement increments the lineage restart count,
  inherits the limit/backoff, and the supervisor stops relaunching after the
  limit is reached. Exhausted records now expose
  `restart_blocked_reason="restart limit reached"` and
  `restart_alerted_unix_ms`, and reconciliation writes a one-time
  `restart_child_domain` audit record with `status="blocked"`.
- MCP auto-attach and `watch` control start a background supervisor alongside
  the repo-local control socket. The supervisor periodically runs the same
  reconciliation path, so long-lived children marked `restart_policy=on_exit`
  can recover without an explicit `reconcile_child_domains` call.
- When an MCP server restarts, persisted child records that still match their
  pid start time are adopted with `supervision.mode="adopted_polling"` and
  `adopted_unix_ms`. This makes recovery explicit: the new server cannot regain
  a kernel wait handle or exact exit code for an already-running non-child
  process, but it can poll identity, mark later exits with unknown code/signal,
  and relaunch `on_exit` records through the same supervisor path. Adoption
  writes an `adopt_child_domain` JSONL audit record.
- CLI `child-run` provides the same stopped-start, child-domain bind, optional
  append-only delta attach, resume, wait, and cleanup sequence for standalone
  child commands. It accepts `--delta FILE` and `--delta-text DSL`, installs
  those fragments before the child is resumed, and records feedback/audit/events
  through the same runtime metadata path.
- CLI `control` provides a cross-process control client for an already-running
  MCP auto-attached or `watch` engine. The engine-owning process writes
  `.actplane/control.json` with a Unix socket path and process identity, and the
  CLI rejects stale state before sending a JSON control request. Supported
  operations are `status`,
  `reload-policy`, `bind-child`, `append-delta`, `launch-child`,
  `list-children`, `read-logs`, `terminate-child`, `restart-child`, and
  `reconcile-children`.
- A non-privileged local-control stress test now runs 16 concurrent clients with
  128 total requests against the same Unix control socket, covering the
  per-connection handler thread path without requiring a live eBPF engine.
- The MCP or watch control process is bound as a submitter in the attached
  parent domain. Runtime append requests use the control process pid for the
  kernel ring-buffer anti-spoofing check, while audit and child-domain parentage
  still refer to the attached parent agent pid.
- Repo-local supervisor operations through `actplane control`, such as launch,
  terminate, restart, reconcile, and trusted reload, are treated as a local
  admin path guarded by the repo-local control socket/state file. If the peer
  process is already bound into this engine, it must be in the trusted parent
  domain; a bound child/sibling-domain process is rejected. An unbound local
  CLI peer is allowed so operators can manage a watch engine that is attached
  to a different agent pid.
- A privileged watch/control product e2e now runs two top-level watch engines
  with distinct attached agent pids and repo roots, launches one child domain in
  each engine with a different local policy delta, and verifies that each
  feedback file contains only its own child-domain rule and reason.
- A privileged MCP protocol e2e now runs two MCP auto-attached engines with
  distinct attached agent pids and repo roots, launches one child domain in each
  engine through JSON-RPC with a different local policy delta, and verifies that
  feedback rule names and reasons remain engine-local.
- MCP- and watch-launched children drop from the sudo/root control process back
  to `SUDO_UID`/`SUDO_GID` before exec, matching the safer `actplane run` and
  `child-run` behavior. Child stdout/stderr log files are chowned back to that
  user when created under sudo, while `.actplane/children` registry directories
  and `meta.json` records remain root-owned and non-group/world-writable so
  restart/reconcile does not trust user-editable policy metadata. In non-root
  capability-based deployments, persisted child registry replay is disabled
  rather than trusted, because a same-UID agent could otherwise edit the
  registry before MCP restart.
- The C loader's `--seed-pid/--seed-label` path seeds both label state and the
  capability maps required by the runtime boundary.
- YAML `domains:` select a set of locked/default rules at compile time.
- `disable` can remove inherited default rules but not locked rules.
- `actplane check`, `compile`, and `domains` show the selected domain.
- The selected domain is flattened into one ordinary DSL policy before loading.

Missing:

- MCP lifecycle recovery is polling-based for children that outlive an MCP
  server restart. It intentionally does not claim exact wait-handle recovery or
  precise exit status for adopted processes.
- Concurrent top-level isolation is covered on the watch/control and MCP
  protocol product paths, but not yet as a CI-grade matrix across all runtime
  entrypoints.

Why this matters:

The process-tree boundary is enough to stop one engine from interfering with
unrelated host processes, which is required for open-source usability. The
`domain_id` path prevents a low-level appended local rule from changing a
sibling domain's active policy. Domain-keyed object labels avoid the common
collision where one domain's bit 0 taints a shared file and another domain
interprets that bit as its own label. Domain-keyed process state across the
active domain chain also prevents local source labels from tripping global or
parent inherited rules while still letting those inherited rules observe labels
and gates created in their own domain. Userspace can now create and operate
child domains through MCP and the CLI control socket, including manual restart,
registry reconcile, and background relaunch for `on_exit` children. The core
MCP JSON-RPC workflow is now covered, with explicit adopted-polling recovery
across MCP server restarts. A declarative YAML-to-runtime-domain mapping would
be a convenience layer, not a requirement for the current repo-scoped MVP. The
remaining domain product gap is richer review/template UX and stronger
activation-time provenance.

Minimum fix:

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
- The BPF side admits label deletion in appended updates only when the caller
  has `AUTH_DECLASSIFY` and label authority for every deleted bit.
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
- CLI `child-run --delta FILE` and `child-run --delta-text DSL` submit
  append-only DSL deltas into the newly launched child domain before the child
  is resumed. They also accept `--approved-by`, `--approval-ref`, and
  `--generated-by` metadata for projects that require approved runtime deltas.
- CLI `control append-delta --target-id DOMAIN --delta FILE` and
  `--delta-text DSL` submit append-only DSL deltas into a domain owned by an
  already-running MCP auto-attached or `watch` engine. `control launch-child
  --delta FILE` uses the same append path before resuming the launched child
  and accepts the same approval metadata.
- CLI `delta add --target-id DOMAIN --delta FILE` is the stable high-level
  alias for the same repo-local append path. It preserves the existing
  `control append-delta` behavior, including optional `--approved-by`,
  `--approval-ref`, and `--generated-by` audit metadata, and defaults to the
  attached parent domain when no target id is provided by the control server.
- `actplane.yaml` can now configure
  `runtime.approval.append_delta.required=true`. When enabled, append-only
  runtime policy changes are rejected before compilation/kernel admission
  unless they carry non-empty `approved_by`, any configured required
  `approval_ref` and `generated_by`, and an `approved_by` value present in the
  optional `allowed_approvers` allowlist. This covers direct append-delta
  requests and child launch/restart policy attachments. Restart/reconcile
  persists and reuses the original child policy approval metadata from the
  protected child registry. Hot reload now refreshes this approval gate from
  the reloaded `actplane.yaml`, so runtime admission follows the active project
  config rather than the startup config.
- Runtime policy metadata is now mutable in the MCP auto-attach and `watch`
  control paths. Whole-policy reload replaces the global metadata table, and
  append-only deltas extend it with a rule-id base that matches the
  kernel-stamped appended entries.
- Runtime delta compilation preserves a per-domain label-bit dictionary, so
  split deltas in the same runtime domain do not silently remap an existing
  label name to a different bit.
- Runtime policy deltas append new table entries rather than mutating existing
  entries, but appended updates can now delete labels. The kernel admission
  path and Rust submitter require `AUTH_DECLASSIFY` and verify that every
  deleted bit is inside the caller domain's `label_mask`. Because appended
  updates are stamped with the target runtime domain id, an author can clear
  labels in its own authoring domain or child domain without clearing inherited
  parent/global labels. Ordinary bind-only child domains do not receive
  `AUTH_DECLASSIFY` by default.
- Local-control append requests use Unix peer credentials as the runtime caller
  pid. The control process has only delegated-submit authority (`AUTH_DELEGATE`)
  for this path, so BPF still checks the peer process's domain authority and
  label mask before admitting a delta. Parent-only supervisor operations such as
  reload, bind, launch, log read, terminate, restart, and reconcile are trusted
  local-admin operations: a peer already bound into this engine must be in the
  parent runtime domain, while an unbound local CLI peer is allowed through the
  repo-local control socket.
- Runtime append now confirms kernel admission by reading back the BPF
  `ts_counts` slot after each appended update/rule. If the kernel rejects a
  request or the append table is full, userspace returns an error and does not
  extend rule metadata or write an accepted audit record. The submit path is
  serialized per `ReloadHandle`, prechecks capacity and authority for the whole
  delta before submitting any entry, and restores the previous counts and target
  domain policy mask if an unexpected mid-append failure occurs.
- Feedback lookup is rule-context based: appended local rules carry their own
  label-name map, which avoids misnaming same-numbered labels reused by a
  sibling domain.
- Accepted/rejected MCP reload, child-domain bind, and append-delta operations
  are appended to a structured JSONL audit log. Records include event type,
  status, actor pid, target/child domain ids where applicable, rule-id base and
  rule count for accepted deltas, deterministic policy hash, rejection error
  text, submitter pid, attached parent pid/domain, audit context id, stable
  `/proc`-backed process identities for actor/caller/submitter/engine parent,
  and audit writer euid/egid. Local-control peer identity is captured when
  `SO_PEERCRED` is read, before runtime audit writes the record, so caller
  identity is not resampled after request handling. Reload and append-delta audit records also include
  per-rule provenance with rule id, name, effect, ops, reason, source ref,
  lowered clause operation, matched kernel operation, target kind, target
  pattern, optional target argument, source start/end lines, parser clause
  source index, exact lowered clause start/end lines, source and clause hashes,
  source and clause text, and locked/default binding mode when the rule came
  from a YAML domain.
  Locked inherited/admin rules are also marked `immutable=true` in audit and
  violation-event metadata.
  Append-delta requests can carry optional `policy_ref`, `approved_by`,
  `approval_ref`, and `generated_by` fields through MCP,
  `actplane control append-delta`, `actplane control launch-child`,
  `actplane child-run`, or `actplane delta add`, and those fields are written
  both as flat fields and as an `approval_chain` object in the JSONL audit
  record. When `runtime.approval.append_delta.required=true`, the
  `approval_chain` is marked `enforced=true` with an accepted/rejected decision,
  missing fields, allowlist context, and rejection reason. It also records
  `admission_model=static_metadata_allowlist`, `external_verified=false`, and
  `signature=null` so downstream tools do not mistake the local gate for an
  external ticket-system or signature verifier.
- Structured violation events now carry the matched runtime domain id, session
  root pid, exact matched kernel operation, declared effect, full matched
  required-label mask, and per-lowered-rule clause/target metadata. Human
  feedback uses the kernel-provided matched operation instead of the first
  operation listed in rule metadata.
- The standalone C and Rust loader NDJSON paths use the same
  `timestamp_ns` provenance field, emit `provenance: null` when no provenance is
  available, and escape string fields before printing.

Missing:

- Audit records are useful but still incomplete. They now include runtime
  context fields, stable process identities, source/clause-level rule
  provenance, and enforced append-delta approval state, but the approval gate
  is a static project-configured metadata admission check rather than a
  cryptographic signature or external ticket-system verification, and
  whole-policy reload remains trusted-admin functionality.
- `reload_policy` is powerful: it can replace the whole active table and should
  be treated as trusted-admin functionality, not ordinary agent
  self-restriction.
- Feature-gated reload means a running object cannot be expanded to new
  verifier-heavy matcher classes or sink classes without restart. This is safe,
  because it rejects unsupported deltas, but it is not yet a smooth product
  experience.

Minimum fix:

- Add end-to-end MCP tests that bind a child domain, append a local delta, and
  verify feedback metadata for the appended rule.
- Decide whether stronger deployments need signed approval tokens or external
  ticket verification beyond the current static allowlist admission gate.
- Surface feature-gate rejections as actionable feedback, and either restart
  with a richer feature set or provide prebuilt BPF variants for common policy
  classes.
- Reserve whole-policy reload for trusted supervisor/admin contexts.

### P0: Hook Coverage Is Incomplete For Security Claims

Current state:

- BPF-LSM programs are registered for `bprm_check_security`, `file_open`,
  `file_permission`, `file_truncate`, `mmap_file`, `path_truncate`,
  `path_unlink`, `path_rename`, `socket_connect`, and `socket_recvmsg`.
- The active implementations are `bprm_check_security`, `file_open`,
  `file_permission`, `file_truncate`, `mmap_file`, `path_truncate`,
  `path_unlink`, `path_rename`, `socket_connect`, and `socket_recvmsg`.
- `path_unlink`, `path_rename`, and truncate-specific LSM hooks now route to
  the same file write rule path as open/write handling, so `block write` rules
  can deny unlink, rename, and truncate before the operation commits.
- `file_permission` and `file_truncate` use a verifier-compatible basename plus
  inode-backed file identity path. They can contribute fd-level object flow and
  broad/basename target matching, but full absolute-path fd precision still
  requires a pid/fd-to-file map.
- `mmap_file` handles file-backed mappings in BPF-LSM mode. Read or executable
  mappings absorb file labels into the process. Shared writable mappings push
  process labels to the mapped file at map creation time.
- `socket_recvmsg` handles connected IPv4 receive in BPF-LSM mode. It can block
  `recv endpoint` rules before the receive completes and can propagate endpoint
  labels or endpoint-source labels into the receiving process.
- Tracepoint mode records successful numeric IPv4 `connect(fd, ...)` calls as a
  `pid,fd -> peer IP` mapping. Successful `read`/`recvfrom`/`recvmsg` on that
  fd reports `notify/kill recv endpoint` rules after the receive and propagates
  endpoint labels or endpoint-source labels into the receiver.
- Tracepoint mode also parses successful unconnected IPv4 `recvfrom(...,
  sockaddr *)` and `recvmsg(..., msghdr.msg_name)` source addresses after the
  kernel writes the source sockaddr, so UDP receive can report `notify/kill recv
  endpoint` rules and propagate endpoint-source labels into the receiver.
  Successful `sendto(..., sockaddr *)` and `sendmsg(..., msghdr.msg_name)` with
  no connected peer map are parsed after send completion for numeric IPv4
  connect/egress updates and reports.
- `actplane check` prints a backend support matrix per rule clause and emits
  static warnings for BPF-LSM-only `block`, argv-sensitive `block exec`, and
  hostname/IPv6 endpoint patterns that cannot match the kernel's numeric IPv4
  enforcement. `actplane check --json` emits the same facts as schema
  `actplane.check.v1`, including host LSM state, source support, per-clause
  support status, support reason, limitations, compiled rule metadata,
  environment override fields such as `ACTPLANE_FORCE_TRACEPOINT`, structured
  warning codes, and JSON-formatted load/compile errors for CI and
  policy-review tools.
- The Rust/aya loader and the C skeleton loader now use the same load-time hook
  budget. Core domain hooks (`sched_process_fork`, `sched_process_exec`,
  `sched_process_exit`) and the runtime control drain tick are always attached.
  File hooks attach only when the policy budget includes file flow, write-path
  hooks attach only when a write source or sink is present, and endpoint hooks
  attach only for connect or recv policies. Exec block hooks attach only for
  executable-identity `block exec` clauses. Argv-token `block exec` clauses are
  unsupported as pre-exec blocks and do not by themselves reserve the
  `bprm_check_security` hook.
- BPF-LSM file hooks are no longer loaded merely because a policy needs
  ordinary file-flow observation. The default path for file sources, file
  transforms, `notify`, and `kill` file rules is tracepoint-based. LSM
  `file_permission`, `file_open`, path mutation, mmap, and mprotect hooks are
  reserved for `block open/write` policy budgets or for the explicit full hook
  profile.
- Advanced tracepoint file-flow hooks are implemented but not default-on:
  mmap/mprotect/mremap/munmap fallback, pipe/pipe2, socketpair, Unix bind,
  connect, accept, SCM_RIGHTS through recvmsg, sendfile64, copy_file_range, and
  splice require `ACTPLANE_ENABLE_ADVANCED_HOOKS=1` or
  `ACTPLANE_HOOK_PROFILE=full`. Full profile also reserves file-flow, network,
  and block hook feature bits so trusted runtime deltas can add common file
  sources and network rules later without silently lacking hooks. File sink rule
  matching and verifier-expensive path contains/suffix matcher bits are still
  reserved only when the initial policy uses them. MCP/watch/child-run reserve
  file-flow hooks explicitly for later child-domain file-source deltas without
  enabling the wider advanced hook set.

Missing:

- Hostname endpoint globs do not work in-kernel. Connect matching is numeric
  IPv4 only, and recv matching has the same numeric IPv4 limitation.
- IPv6 is not covered.
- Batch UDP syscalls such as `recvmmsg`/`sendmmsg` are not modeled separately
  yet.
- Exec argv-token rules cannot be blocked pre-exec because argv slots are only
  available after exec. The LSM path now clears argv scratch before evaluating
  pre-exec block rules, so mixed policies cannot accidentally match a stale
  argv token from an earlier post-exec tracepoint. Focused live tests now cover
  argv-sensitive `notify` and `kill` through the post-exec tracepoint path.

Minimum fix:

- Add userspace DNS/SNI/IP expansion for host policies, or restrict the DSL docs
  to numeric IPv4 for enforcement claims.

### P0/P1: File Flow Has LSM fd Coverage But Not Full Cross-Backend IFC

Current state:

- File labels are applied and propagated when a file is opened with read/write
  flags.
- LSM mode uses `(dev, inode)` identity when available.
- In BPF-LSM mode, `file_permission` provides fd-level propagation when the
  engine is started with a block-file budget or the explicit full hook profile.
  It is no longer part of the default file-flow budget because it is
  verifier-expensive on larger policies, and tracepoints cover ordinary
  `notify`/`kill` file-flow observation by default.
- A live regression now covers the previous open-before-taint miss: a process
  opens an output fd, later reads a secret, writes to that already-open fd, and
  a second process reading the output inherits the secret label.
- Tracepoint mode tracks a `pid,fd -> file_id` map for ordinary file
  descriptors opened through open/openat/openat2 or creat. On successful opens,
  it uses the returned fd to recover inode/dev identity when possible and falls
  back to path hashing only when no fdtable object is available.
- `read` and `write` tracepoints now apply ordinary fd flow after successful
  nonzero I/O. They fall back to stdio pseudo-files
  (`stdio:stdin`, `stdio:stdout`, `stdio:stderr`) when the fd is not in the map.
- Tracepoint mode models fd reuse through open overwrite, `close`, and
  `dup`/`dup2`/`dup3`/`fcntl(F_DUPFD*)` map copies.
- Tracepoint mode copies low-numbered tracked fd mappings on fork, so inherited
  pipe and file descriptors remain visible to child processes after the parent
  closes or reuses its own descriptor.
- Tracepoint mode models anonymous pipes created through `pipe`/`pipe2` as
  transient IFC file objects. Ordinary read/write flow through those pipe fds
  propagates labels.
- Tracepoint mode models `socketpair(AF_UNIX, ...)` fds as transient IPC
  objects. Ordinary read/write plus `sendto`/`recvfrom` and `sendmsg`/`recvmsg`
  flow through those socket fds propagates labels.
- Tracepoint mode models pathname and abstract-name `AF_UNIX` sockets as stable
  file-like IPC objects. Pathname sockets are displayed as `unix:<path>`.
  Abstract sockets are displayed as `unix:@abstract` and keyed by a hash of the
  raw abstract name bytes, so distinct abstract sockets do not share labels.
  Successful `bind` and `connect` attach the object to the socket fd,
  `accept`/`accept4` copy the listening fd's object to the accepted fd, fork
  copies the low-numbered fd mapping, and ordinary read/write plus
  send/recv-style socket I/O propagates labels through the object. Unconnected
  datagram `sendto(..., sockaddr_un)` and `sendmsg(..., msghdr.msg_name)` write
  the sender's labels to the addressed Unix socket object after a successful
  send.
- Tracepoint mode tracks received SCM_RIGHTS fds on successful `recvmsg`. It
  scans the first two ancillary control messages, accepts up to eight fds per
  SCM_RIGHTS message, and first tries to reuse the sender-side `struct file *`
  object identity stored for already-modeled fds, which preserves transient
  pipe/socketpair/Unix-socket objects. If no prior model exists, it falls back
  to the received fd's inode/dev identity.
- Tracepoint mode propagates labels across successful
  `sendfile64(out_fd, in_fd, ...)` when both file descriptors are tracked.
- Tracepoint mode propagates labels across successful
  `copy_file_range(in_fd, ..., out_fd, ...)` when both file descriptors are
  tracked.
- Tracepoint mode propagates labels across successful
  `splice(in_fd, ..., out_fd, ...)` when both file descriptors are tracked,
  including file-to-pipe and pipe-to-file copies.
- File-backed mmap is modeled in both BPF-LSM and tracepoint modes at mapping
  creation: `PROT_READ`/`PROT_EXEC` mappings absorb file labels, and
  `MAP_SHARED | PROT_WRITE` mappings propagate the process labels to the file.
  This closes the common shared-mmap write path that does not issue a later
  `write(2)`.
- BPF-LSM `file_mprotect` now models later permission changes for file-backed
  VMAs before the operation commits, using the VMA's real backing file and
  shared/private status.
- Tracepoint mode records the eight most recent exact-start file-backed
  mappings per pid, deletes exact-start `munmap` entries, propagates read/exec
  source labels on successful exact-start `mprotect`, and propagates
  shared-writable file flow on successful exact-start `mprotect` or `mremap`.
  If a mapping uses an fd that was opened before the process was bound into the
  engine, tracepoint mmap exit recovers the fd's current `struct file` through
  the fdtable and stores basename plus inode/dev identity for the bounded mmap
  shadow entry.

Missing:

- If a process opens a file for read but never reads from it, the current engine
  may over-taint at open time.
- Tracepoint `mprotect`/`mremap` tracking is intentionally bounded. It tracks
  the eight most recent exact-start file-backed mappings per pid, uses basename
  matching when it has to recover a pre-opened fd from the current fdtable, and
  does not handle subrange permission changes or more than eight recent
  mappings per pid.
- SCM_RIGHTS parsing is bounded to the first two ancillary control messages and
  up to eight fds per SCM_RIGHTS message. Larger chains or batches are not yet
  modeled.
- Shared memory is not modeled.
- Unix socket coverage is tracepoint flow coverage. It is not BPF-LSM
  pre-operation `block` coverage.
- Tracepoint path-only operations still fall back to path hashing, so relative
  paths and rename/link aliasing remain less precise when no fdtable object is
  available.
- There is no precise per-gate file consumption set for staleness. The current
  session-level epoch model is useful but can over- or under-approximate
  freshness in complex multi-file workflows.

Minimum fix:

- Cover remaining IPC and memory-mapped paths at least enough to avoid silent
  bypasses in agent workloads.
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
- Extend `check --json` into a richer `check --explain` or `plan` command that
  prints the concrete OS-level interpretation of each rule.
- Add a policy review artifact that can be committed or attached to CI.

### P1: Audit And Feedback Need Structured State

Current state:

- Feedback is appended to a text file and forwarded by hooks.
- Ring-buffer events are decoded in-process.
- A small JSON tag is appended inside the human feedback payload.
- Structured violation events are appended as JSONL using schema
  `actplane.violation.v1`. They include `matched_label_details`, which expands
  the kernel `matched_labels` mask into one object per label with label name,
  mask, provenance status, a reported origin when available, and
  `causal_chain_complete=false` to avoid overstating single-hop provenance as a
  full causal graph.
- Rule source metadata and per-lowered-rule clause metadata are carried into
  violation events when available, so an event can identify the YAML rule entry
  or inline DSL rule plus the lowered clause operation/effect/target that
  generated the matched kernel rule. The same records now include the parser
  clause source index, exact lowered-clause source line span, clause text, and
  clause hash when source metadata is available.
- `actplane check --json` emits a stable host/backend support matrix with
  per-source and per-clause support status, support reason, limitations, and
  warning codes. It also reports policy load/compile failures as
  `actplane.check.v1` JSON and accounts for `ACTPLANE_FORCE_TRACEPOINT` when
  reporting BPF-LSM block support.
- Runtime audit records include stable actor/caller/submitter process
  identities built from pid plus `/proc` start time, uid/gid, comm, and exe
  where available. Local-control caller identity is snapshotted at peer-credential
  capture time. Append-delta audit records include an explicit
  `approval_chain` object for approved-by, approval-ref, and generated-by
  provenance. When `runtime.approval.append_delta.required=true`, the same
  object records an enforced admission decision with missing-field and allowlist
  details.
- Kernel provenance lookup covers both process labels and stored file/endpoint
  object labels. This matters for pre-flow sink events such as an `open` rule
  matching a label stored on the file object before that label is copied into
  the reader process.

Missing:

- Policy/rule provenance still lacks stronger activation-time state transitions
  and external proof of approval beyond the static project allowlist gate.
- Events enumerate every matched label, but kernel provenance still reports one
  matched label origin per violation, not every matched label's origin and not a
  complete multi-hop chain. Stored file/endpoint object labels now have a
  fallback provenance lookup for the reported origin.

Minimum fix:

- Add richer causal provenance fields and, if needed for deployments, signed or
  externally verified approval tokens.
- Keep human feedback as a formatted view over the structured event.

### P1: Evaluation Coverage Is Not Yet CI-Grade

Verified in this snapshot:

- `cargo test --locked -p actplane --tests`: 81 unit tests passed, 1 ignored,
  plus 17 CLI UX tests passed, 2 default MCP JSON-RPC e2e tests passed with 7
  privileged MCP tests ignored, and 2 privileged watch/control e2e tests
  ignored.
- `sudo -E cargo test --locked -p actplane --test mcp_protocol -- --ignored
  --nocapture --test-threads=1`: 7 privileged MCP e2e tests passed, including
  the concurrent two-engine child-domain delta isolation test through JSON-RPC,
  the `restart_policy=on_exit` background supervisor relaunch test, and the MCP
  restart adopted-polling recovery test. It also covers enforced append-delta
  approval admission, hot-reloaded approval-gate changes, and 128 concurrent
  repo-local `control status` requests against a live MCP auto-attached engine.
- `sudo -E cargo test --locked -p actplane --test mcp_protocol
  mcp_append_delta_requires_configured_approval_privileged -- --ignored
  --nocapture --test-threads=1`: passed. The test verifies that
  `runtime.approval.append_delta.required=true` rejects missing approval
  metadata before admission, writes a rejected audit record, and accepts a delta
  with the configured allowlisted approver plus required metadata.
- `sudo -E cargo test --locked -p actplane --test mcp_protocol
  mcp_reload_updates_append_delta_approval_gate_privileged -- --ignored
  --nocapture --test-threads=1`: passed. The test starts with approval disabled,
  accepts a delta without approval, hot-reloads an `actplane.yaml` that requires
  approval, and verifies that the next unapproved append is rejected.
- `sudo -E cargo test --locked -p actplane --test watch_control -- --ignored
  --nocapture --test-threads=1`: 2 privileged watch/control e2e tests passed,
  including the concurrent two-engine child-domain delta isolation test.
- `ACTPLANE_REBUILD_BPF=1 cargo test --locked -p ebpf-ifc-engine --lib
  object_is_aligned_elf`: passed and refreshed `bpf/prebuilt/process.bpf.o`.
- `cargo test --locked -p ebpf-ifc-engine --lib`: 14 tests passed, 43 live eBPF
  tests ignored. The added non-live tests cover the
  minimal/default attach budget, rejection of file deltas when the engine was
  not started with a file-flow hook budget, rejection of block deltas when the
  matching LSM hook budget was not reserved, argv-token `block exec` not
  reserving the pre-exec bprm hook, ordinary file-flow not reserving LSM file
  hooks by default, and the 128-rule `cap_policy` mask boundary bits.
- `sudo -E cargo test --locked -p ebpf-ifc-engine --lib
  append_policy_delta_admits_domain_local_declassify_smoke -- --ignored
  --nocapture --test-threads=1`: passed. The test first verifies that a
  runtime `declassify` delta is rejected without `AUTH_DECLASSIFY`, verifies a
  delegated submit where the control process has `AUTH_DELEGATE` but BPF checks
  the child actor's domain authority, then appends a file source and exec rule
  into a runtime domain, observes the violation before declassification,
  verifies the new violation event fields (`op`, `domain_id`, `session_root`,
  and `matched_labels`), appends a domain-local runtime `declassify` update
  admitted by `AUTH_DECLASSIFY`, then verifies the same flow no longer matches
  the local rule.
- `sudo -E cargo test --locked -p ebpf-ifc-engine --lib
  object_label_open_violation_reports_file_provenance_smoke -- --ignored
  --nocapture --test-threads=1`: passed. The test has one process read a source
  label and write a shared file, then a second process triggers an `open` sink
  on that shared file before the file label is copied into the reader process.
  The emitted violation includes the file object's provenance pointing back to
  the original source read.
- `sudo -E cargo test --locked -p ebpf-ifc-engine --lib
  exec_argv_notify_matches_token_smoke -- --ignored --nocapture
  --test-threads=1`: passed. The wrong argv token did not report, and the
  matching token produced a post-exec notify event.
- `sudo -E cargo test --locked -p ebpf-ifc-engine --lib
  exec_argv_kill_terminates_post_exec_smoke -- --ignored --nocapture
  --test-threads=1`: passed. The matching argv token killed the task from the
  post-exec tracepoint path and reported `killed=true`, `blocked=false`.
- `cargo fmt --all --check`: passed.
- `cargo test --locked -p ebpf-ifc-engine --bins`: passed for the standalone
  Rust loader binary after the NDJSON escaping/schema fix.
- `git diff --check`: passed.
- `make -B -C bpf process`: passed.
- `make -C bpf test`: 35 matcher/arg/mask tests passed.
- `sudo -E bash script/e2e_examples.sh`: 12 live enforcement examples passed.
  The script now builds the workspace release binary at `target/release/actplane`
  rather than using a stale legacy `collector/target` binary, and it waits for
  `ActPlane: ready` before resuming each stopped trigger process.
- `sudo -E cargo test --locked -p ebpf-ifc-engine --lib -- --ignored
  --nocapture --test-threads=1`: 41 privileged live eBPF tests passed after the
  hook-budget tightening. LSM-specific fd/mmap/mprotect tests explicitly use the
  full hook profile, while ordinary file-flow tracepoint tests cover the default
  narrower hook budget.
- Focused privileged root/domain smokes run after the hook-budget change passed:
  `unseeded_processes_do_not_match_global_policy`, plus the `domain` filter
  covering `append_policy_delta_scopes_to_target_domain_and_descendants_smoke`,
  `domain_handle_binds_subagent_child_domain_smoke`,
  `ancestor_domain_dynamic_labels_apply_in_child_smoke`,
  `sibling_domain_file_labels_do_not_collide_smoke`,
  `binding_domain_resets_inherited_process_labels_smoke`, and
  `local_domain_process_labels_do_not_satisfy_global_rules_smoke`.
- After adding `cap_policy`, `lsm_fd_write_after_late_read_propagates_file_label_smoke`
  passed with BPF-LSM active, which verifies that initial global rules are bound
  into the effective-policy mask and still fire through the ordinary loader.
- The privileged `reload_policy_latency_smoke` also passed on the current
  object after adding `cap_policy`, with p50 submit-to-drain latency around 27
  microseconds and p50 reload-to-observed exec violation around 121
  microseconds in this run.
- A privileged BPF-LSM path hook smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  lsm_path_write_hooks_block_unlink_rename_and_truncate_smoke --ignored
  --nocapture`) passed: exact `block write` rules denied unlink, truncate, and
  rename pre-operation with `EPERM`, preserved the original files, and emitted
  blocked violation events for each protected path.
- A privileged BPF-LSM fd-flow smoke with the full hook profile
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  lsm_fd_write_after_late_read_propagates_file_label_smoke --ignored
  --nocapture`) passed: an unlabeled process opened an output fd, then read a
  secret, wrote to the already-open output fd, and a second process reading that
  output inherited the secret label and triggered the expected exec violation.
- A privileged BPF-LSM mmap smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  lsm_mmap_shared_write_after_late_read_propagates_file_label_smoke --ignored \
  --nocapture`) passed: an unlabeled process opened and sized an output file,
  then read a secret, wrote the output through `MAP_SHARED` mmap without a later
  `write(2)`, and a second process reading that output inherited the secret
  label and triggered the expected exec violation.
- A privileged BPF-LSM mprotect smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  lsm_mprotect_shared_write_after_late_read_propagates_file_label_smoke \
  --ignored --nocapture`) passed: an unlabeled process mapped an output file
  read-only, read a secret, changed the mapping to shared writable with
  `mprotect`, modified the file through the mapping, and a later reader
  inherited the secret label.
- A privileged BPF-LSM mprotect read-upgrade smoke
  (`lsm_mprotect_read_upgrade_source_taints_subject_smoke --ignored
  --nocapture`) passed: a stopped subject opened the source before engine
  attachment, then after binding mapped it `PROT_NONE`, upgraded it to
  `PROT_READ`, read from the mapping, and inherited the source label before
  exec.
- A privileged forced-tracepoint fd-flow smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_fd_write_after_late_read_propagates_file_label_smoke --ignored
  --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: the same
  open-before-taint ordinary-fd write flow propagated through the tracepoint
  `pid,fd -> file_id` fallback.
- A privileged forced-tracepoint mmap smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_mmap_shared_write_after_late_read_propagates_file_label_smoke \
  --ignored --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: the same
  open-before-taint file flow propagated when the writer modified the output
  through a shared mmap rather than through `write(2)`.
- A privileged forced-tracepoint mmap multi-mapping smoke
  (`tracepoint_mmap_exact_start_tracks_multiple_mappings_smoke --ignored
  --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: a process mapped
  `src_a`, then mapped `src_b`, and a later `mprotect(PROT_READ)` on `src_a`
  still found the older exact-start mapping instead of losing it to the newer
  mapping.
- Privileged forced-tracepoint mprotect and mremap smokes
  (`tracepoint_mprotect_shared_write_after_late_read_propagates_file_label_smoke`
  and `tracepoint_mremap_shared_write_after_late_read_propagates_file_label_smoke
  --ignored --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: the bounded
  mmap tracker propagated shared-writable file flow when a mapping became
  writable through `mprotect`, and when a writable mapping was moved through
  `mremap`.
- A privileged forced-tracepoint mprotect read-upgrade smoke
  (`tracepoint_mprotect_read_upgrade_source_taints_subject_smoke --ignored
  --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: a pre-opened source fd
  was recovered through the fdtable on mmap exit, and the later
  `mprotect(PROT_READ)` source label reached the subject before exec.
- A privileged forced-tracepoint fcntl-dup smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_fcntl_dup_fd_flow_smoke --ignored --nocapture`) passed with
  `ACTPLANE_FORCE_TRACEPOINT`: a file label flowed through an fd duplicated by
  `fcntl(F_DUPFD)` and then into a process that read through the duplicate.
- A privileged forced-tracepoint sendfile smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_sendfile_fd_flow_smoke --ignored --nocapture`) passed with
  `ACTPLANE_FORCE_TRACEPOINT`: a writer opened the output before the secret,
  then copied the secret to the output with `sendfile64`, and a later reader
  inherited the secret label from that output.
- A privileged forced-tracepoint copy-file-range smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_copy_file_range_fd_flow_smoke --ignored --nocapture`) passed with
  `ACTPLANE_FORCE_TRACEPOINT`: the same open-before-taint file-to-file flow
  propagated through `copy_file_range`.
- A privileged forced-tracepoint pipe fork smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_pipe_fork_fd_flow_smoke --ignored --nocapture`) passed with
  `ACTPLANE_FORCE_TRACEPOINT`: a parent created a pipe, forked a child, read a
  secret only after the fork, wrote to the pipe, and the child inherited the
  secret label only by reading from the pipe before its exec.
- A privileged forced-tracepoint socketpair fork smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_socketpair_fork_fd_flow_smoke --ignored --nocapture`) passed with
  `ACTPLANE_FORCE_TRACEPOINT`: a parent created an `AF_UNIX` socketpair, forked
  a child, read a secret only after the fork, sent one byte through the socket,
  and the child inherited the secret label through `socket.recv()` before exec.
- A privileged forced-tracepoint pathname Unix socket smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_unix_path_socket_fork_fd_flow_smoke --ignored --nocapture`) passed
  with `ACTPLANE_FORCE_TRACEPOINT`: a parent bound and listened on a pathname
  `AF_UNIX` socket, forked a child that accepted the connection, read a secret
  only after the fork in the parent, sent one byte through a connected client
  socket, and the child inherited the secret label through the accepted socket
  before exec.
- A privileged forced-tracepoint abstract Unix socket smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_unix_abstract_socket_fork_fd_flow_smoke --ignored --nocapture`)
  passed with `ACTPLANE_FORCE_TRACEPOINT`: the same post-fork secret transfer
  propagated through a Linux abstract-namespace `AF_UNIX` socket whose object id
  is keyed by the raw abstract name bytes rather than a filesystem pathname.
- Privileged forced-tracepoint Unix datagram smokes
  (`tracepoint_unix_dgram_sendto_path_flow_smoke` and
  `tracepoint_unix_dgram_sendmsg_abstract_flow_smoke --ignored --nocapture`)
  passed with `ACTPLANE_FORCE_TRACEPOINT`: a parent bound a pathname or abstract
  `AF_UNIX` datagram socket, forked a child receiver, read a secret only after
  the fork, and sent one datagram from an unconnected client via `sendto` or
  `sendmsg`. The child inherited the secret label through the bound datagram
  socket object before exec.
- Privileged forced-tracepoint SCM_RIGHTS smokes
  (`tracepoint_scm_rights_received_fd_flow_smoke`,
  `tracepoint_scm_rights_fifth_fd_flow_smoke`, and
  `tracepoint_scm_rights_socketpair_fd_identity_smoke --ignored --nocapture`)
  passed with `ACTPLANE_FORCE_TRACEPOINT`: a child writing through a received
  ordinary file fd propagated labels to the written file, the fifth fd in an
  SCM_RIGHTS batch propagated labels after receive, and a child receiving a
  post-fork socketpair endpoint reused the already-modeled transient socket
  object before inheriting the secret label through a later read.
- A privileged forced-tracepoint connected IPv4 recv smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_recv_endpoint_source_taints_reader_smoke --ignored --nocapture`)
  passed with `ACTPLANE_FORCE_TRACEPOINT`: a TCP client connected to loopback,
  received data, inherited the endpoint-source label through the tracepoint
  `pid,fd -> peer IP` mapping, and triggered the expected exec violation.
- A privileged forced-tracepoint unconnected UDP `recvfrom` smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_udp_recvfrom_endpoint_source_taints_reader_smoke --ignored \
  --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: a UDP receiver bound to
  loopback received one datagram, inherited the endpoint-source label from the
  post-receive source sockaddr, and triggered the expected exec violation.
- A privileged forced-tracepoint unconnected UDP `recvmsg` smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_udp_recvmsg_endpoint_source_taints_reader_smoke --ignored \
  --nocapture`) passed with `ACTPLANE_FORCE_TRACEPOINT`: a UDP receiver bound to
  loopback received one datagram through `socket.recvmsg()`, inherited the
  endpoint-source label from `msghdr.msg_name`, and triggered the expected exec
  violation.
- A privileged forced-tracepoint splice smoke
  (`sudo -E ./target/debug/deps/ebpf_ifc_engine-... \
  tracepoint_splice_fd_flow_smoke --ignored --nocapture`) passed with
  `ACTPLANE_FORCE_TRACEPOINT`: a secret file was copied to an output through
  `splice(file -> pipe)` and `splice(pipe -> file)`, and a later reader inherited
  the secret label from that output.
- Privileged BPF-LSM recv smokes passed:
  `lsm_recv_endpoint_source_taints_reader_smoke` verified connected loopback TCP
  receive propagates endpoint-source labels into the receiving process before a
  later exec, and `lsm_recv_endpoint_block_smoke` verified `block recv endpoint`
  returns `EPERM` and emits a blocked violation event.
- A privileged CLI smoke for `child-run --delta` launched a stopped child
  domain, appended a source+rule delta before resume, and produced feedback,
  audit, and structured violation events for the child-local rule.
- Privileged CLI control smokes against a running MCP auto-attached engine
  passed: `control status` connected through `.actplane/control.json`,
  `control launch-child` created a child domain that could be listed and logged,
  and `control launch-child --delta` appended a child-local source+rule delta
  before resume and produced the expected feedback/provenance.
- Privileged CLI control restart/reconcile smokes passed: `control
  restart-child --terminate-existing` terminated the old process group and
  launched the same command in a fresh runtime domain, `control
  reconcile-children` reported the old domain as terminated and the replacement
  as running, restart audit records were written, and a policy-preserving
  restart reproduced the child-local feedback in the replacement domain.
- A privileged `watch` control e2e
  (`cargo test --locked -p actplane --test watch_control -- --ignored
  --nocapture`) passed: `actplane watch` wrote
  `.actplane/control.json`, `control status` reached the running watch engine,
  32 concurrent `control status` requests succeeded against the same loaded
  engine, `control launch-child` launched a child domain, `control read-logs`
  observed child stdout, `control terminate-child` stopped it, graceful watch
  shutdown removed the control state, and bounded log reads worked through the
  root-owned child registry. The same e2e now also verifies the
  negative boundary for the trusted local-admin model: a process already bound
  into a launched child domain runs `actplane control launch-child`, receives a
  nonzero rejection that names the non-parent runtime domain, and no nested
  child domain is created.
- A second privileged `watch` control e2e passed with two concurrent watch
  engines attached to different agent pids and repo roots. Each engine launched
  a child domain with a different local file-source delta, and the feedback
  assertions verified that rule names and reasons did not cross from one engine
  into the other.
- MCP protocol coverage now includes default stdio JSON-RPC e2e tests for
  `initialize`, `tools/list`, `resources/list`, `resources/read`, and
  `tools/call list_child_domains`, plus a repeated-request protocol-loop stress
  that sends 96 sequential `tools/list`, `resources/list`, and
  `list_child_domains` requests. A privileged ignored MCP JSON-RPC e2e test
  also passed locally for `tools/call launch_child_domain` with a child-local
  source+rule delta, `read_child_domain_logs`, `terminate_child_domain`,
  `restart_child_domain`, and `reconcile_child_domains`. It verifies kernel
  feedback and provenance through the MCP protocol path, the no-delta
  stopped-start launcher path, bounded child log reads, process-group
  termination, fresh-domain restart metadata through `restarted_from`, and
  append-delta audit records with source-level rule provenance plus
  approval/generator metadata.
- A second privileged MCP protocol e2e passed with two concurrent MCP
  auto-attached engines attached to different agent pids and repo roots. Each
  engine launched a child domain with a different local file-source delta
  through `tools/call launch_child_domain`, and the feedback assertions verified
  that rule names and reasons did not cross from one engine into the other.
- A privileged MCP local-control stress e2e passed: one MCP auto-attached
  engine wrote `.actplane/control.json`, and 16 concurrent clients issued 128
  total `control status` requests through the repo-local Unix socket.
- A third privileged MCP protocol e2e passed for background supervisor recovery:
  `tools/call launch_child_domain` launched a long-lived child with
  `restart_policy=on_exit`, `restart_limit=1`, and `restart_backoff_ms=100`.
  The test killed its process group outside ActPlane, and the background
  supervisor relaunched the recorded command in a fresh child domain without an
  explicit reconcile call while persisting `replacement_child_id` on the old
  record and `restarted_from`, `restart_count=1`, and the inherited
  restart-limit metadata on the replacement. The test then killed the
  replacement, verified `restart_blocked_reason="restart limit reached"` and
  `restart_alerted_unix_ms` on the exhausted record, and checked the JSONL audit
  log for a `restart_child_domain` event with `status="blocked"`.
- A fourth privileged MCP protocol e2e passed for MCP restart recovery:
  one MCP server launched a long-lived `restart_policy=on_exit` child, then the
  server was killed while the child process group stayed alive. A new MCP server
  in the same repo loaded the persisted registry, exposed the child with
  `supervision.mode="adopted_polling"` and `adopted_unix_ms`, wrote an
  `adopt_child_domain` audit event, and relaunched the adopted child into a
  fresh domain after the test killed its process group.
- `cargo fmt --check` passed.

Not verified here:

- Higher-volume multi-client MCP protocol stress.

Minimum fix:

- Keep the refreshed `Cargo.lock` and make `--locked` builds part of CI.
- Add a privileged CI or nightly job with BPF-LSM active.
- Extend the tracepoint-only matrix beyond fd flow using
  `ACTPLANE_FORCE_TRACEPOINT` or an equivalent loader knob.
- Promote the ignored privileged smoke tests into a documented CI/nightly target.
- Add higher-volume product-level sibling-domain stress across MCP clients.

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
  active-domain-chain label and gate state, and compile-time YAML domain
  selection, plus a minimal live child-domain bind API and MCP append-only DSL
  deltas with in-memory metadata merge, JSONL audit records, and an MCP
  stopped-start child-domain launcher with persisted metadata, status, bounded
  log reads, and process-group termination, plus CLI `child-run` for standalone
  child-domain launches and CLI `control` for already-running MCP
  auto-attached engines, including manual child restart and registry reconcile.
  It still lacks higher-concurrency control-plane stress coverage.

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
   - If v1 needs full multi-agent isolation, finish remaining admin-policy
     inheritance before making that claim.
2. Fix the enforcement support matrix:
   - Keep argv-sensitive `block exec` documented and warned as unsupported.
   - Keep `check --json` as the stable backend matrix surface and add richer
     human explanations where useful.
3. Cover remaining file-flow bypasses: tracepoint mmap subrange and
   beyond-eight-mapping precision, SCM_RIGHTS batches beyond the bounded parser,
   shared memory, and rename/link alias precision.
4. Keep whole-policy reload restricted to trusted contexts.

### P1: Make It Useful For Real Users

1. Add templates and a richer `check --explain` or `plan` command.
2. Extend templates, review, and supervisor-grade recovery semantics for
   long-lived subagents.
3. Decide whether deployments need signed approval tokens or external
   ticket-system verification on top of the static approval allowlist gate.
4. Add privileged CI/e2e coverage for BPF-LSM and tracepoint modes.
5. Add safe rollout modes: observe-only, warn, block selected rules, fail closed
   for high-severity rules.

### P2: Clean Up Surface Area

1. Update README and `bpf/README.md`.
2. Make examples consistently use `COMMAND`/`AGENT` labels.
3. Mark recv's current support boundary: BPF-LSM and tracepoint connected IPv4
   are covered, tracepoint unconnected UDP `recvfrom`/`recvmsg` is covered
   post-receive, while batch UDP syscalls, IPv6, and hostname policies are not.
4. Add a small support matrix table to the paper appendix.

## Bottom Line

For a local single-agent harness with flat policies, ActPlane now has the
minimum necessary isolation shape: the engine is active only for the seeded
repo/session process tree. For the paper's strongest design claim, the kernel
has real domain-scoping primitives for appended local policy, object labels, and
active-domain-chain process labels, plus a minimal supported child-domain bind API.
MCP can launch stopped child-domain processes, append scoped DSL deltas with
in-memory metadata merge, keep a live child registry, expose bounded log reads,
terminate child process groups, persist child metadata, reload the registry on
MCP restart, and write JSONL audit records. CLI `child-run` can perform the
same stopped launch, child-domain bind, pre-resume delta attach, and wait flow
for one standalone child command, and CLI `control` can operate already-running
MCP auto-attached or `watch` engines through a repo-local socket, including
manual restart/reconcile for launched child domains. The missing piece remains
promotion of privileged high-volume MCP/watch control stress into CI/nightly
coverage. For industrial use, the next hard requirements are fd-precise file
flow, complete hook support for security
effects, policy review, and rollout workflow.
