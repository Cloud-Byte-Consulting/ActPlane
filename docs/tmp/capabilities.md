# Minimal Runtime Delta Admission

This is the dynamic-policy part of `ebpf-ifc-engine`. It should stay generic
and small.

## Core Idea

User space may request a policy change. The kernel decides whether it becomes
effective.

```text
request delta
check authority mask
check domain relation
check scope only narrows
apply OR/narrow
```

The kernel does not parse YAML, understand layers, or know agent roles.

## Kernel State

Runtime state is keyed by a small domain id. The current low-level ABI still
uses `target_id`; in the security model that id is a domain id.

```c
struct cap_state {
    u32 parent;
    u32 scope_id;
    u64 labels;
    u64 authority_mask;
    u64 target_mask;     // self/child domain authority
    u64 restrict_mask;
    u64 gate_mask;
    u64 label_mask;
};
```

Task binding is separate:

```text
cap_task[pid] -> domain id
cap_state[domain id] -> effective state
```

## Request

The user-to-kernel request is fixed-size and contains no DSL:

```c
struct cap_delta_request {
    pid_t caller_pid;
    u32 target_id;       // domain id
    u32 new_scope_id;
    u64 required_mask;
    u64 add_restrict_mask;
    u64 add_label_mask;
    u64 add_gate_mask;
};
```

The active implementation uses:

- `cap_req`: `BPF_MAP_TYPE_USER_RINGBUF`
- `cap_task`: pid to domain id
- `cap_state`: domain id to effective state
- `cap_stats`: accept/reject/drain/drop counters

Rust mirrors this as `CapState`, `DeltaRequest`, `Loader::bind_state()`, and
`Loader::submit_delta()`.

## Admission

The BPF path is intentionally mechanical:

```text
caller = cap_task[caller_pid]
src = cap_state[caller]
dst = cap_state[target_id]

1. caller_pid must be the draining task
2. domain must be self or direct child, according to src.target_mask
3. required delta bits must fit src.authority_mask
4. add_label_mask must fit src.label_mask
5. new_scope_id must be unset or narrower than dst.scope_id
6. accepted updates only OR bits or replace scope with a narrower scope
```

The kernel derives required authority from the request body:

```text
add_restrict_mask != 0 -> AUTH_ADD_RESTRICTION
add_label_mask    != 0 -> AUTH_ADD_LABEL
add_gate_mask     != 0 -> AUTH_REQUIRE_GATE
new_scope_id      != 0 -> AUTH_NARROW_SCOPE
```

Then it applies:

```c
dst.restrict_mask |= req.add_restrict_mask;
dst.labels        |= req.add_label_mask;
dst.gate_mask     |= req.add_gate_mask;
if (req.new_scope_id)
    dst.scope_id = req.new_scope_id;
```

There is no operation to clear labels, remove restrictions, remove gates, widen
scope, or modify unrelated domains.

## Why This Is Enough

Higher layers can still expose names such as `session`, `build`, or `review`.
Those names lower to domain ids and deltas before reaching the kernel.

So the reusable engine only needs:

```text
object + label + event + rule + delta + authority
```

Everything agent-specific belongs above the engine.
