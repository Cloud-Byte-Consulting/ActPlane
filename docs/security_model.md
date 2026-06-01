# Security Model

ActPlane's reusable engine should be described as:

```text
IFC core: object + label + event + rule
Runtime policy: domain + delta + authority
```

Agent, subagent, MCP, hooks, prompts, and workspaces are integrations above this
model. They are not part of the engine security model.

## Domain

A domain is the runtime policy boundary for a process tree.

```text
pid -> domain
domain -> effective policy
event(pid) checks only pid's domain
```

If a rule is added to domain `review`, it affects processes bound to `review`.
It does not affect unrelated domains.

Files, sockets, and stdio are not domains. They are IFC objects that carry
labels and participate in flow rules.

## Rules

A rule has:

```text
condition
effect
reason
lock mode
```

Effects are normal IFC effects:

```text
notify
block
kill
```

Lock mode is the layered-policy part:

```text
locked    -> child domain cannot disable this rule
unlocked  -> child domain may disable this rule for itself
```

This means parent domains can publish default block/kill policies without making
all of them mandatory.

## Child Updates

A child domain may update its own policy if its authority allows it.

Allowed updates:

```text
add stricter rules
add labels
add gates
narrow scope
disable unlocked parent rules
create child domains with no more authority than delegated
```

Rejected updates:

```text
disable locked parent rules
modify parent domain state
modify sibling domain state
remove inherited locked rules
widen scope
remove labels or gates
increase delegated authority
```

The important distinction:

```text
locked parent policy    = security invariant
unlocked parent policy  = default policy
```

Only locked policy participates in the non-bypass security invariant.

## Invariant

For any child domain:

```text
locked_policy(child) >= locked_policy(parent)
```

Here `>=` means "at least as restrictive", not "more privileges".

Unlocked rules are different:

```text
unlocked_policy(parent)
```

is a default template. The child may keep it or disable it.

## Runtime Delta Admission

User space does not directly mutate effective policy state. It submits a delta:

```text
caller_pid
domain_id
required_mask
add_label_mask
add_restrict_mask
add_gate_mask
new_scope_id
disable_unlocked_rule_ids
```

The kernel admits the delta only if:

```text
caller_pid is bound to a domain
caller may affect the target domain
caller has the required authority bits
scope only narrows
labels/gates/restrictions only add
disabled rules are unlocked
locked parent rules remain effective
```

Accepted deltas are merged into the domain's already-computed effective state.
The syscall fast path should not walk a domain tree.

## Example

Parent policy:

```yaml
rules:
  - name: no-git-branch
    locked: true
    ifc: |
      rule no-git-branch:
        kill exec "git" "branch"
        because "do not create git branches"

  - name: no-network
    locked: false
    ifc: |
      rule no-network:
        kill connect any
        because "network is disabled by default"
```

Child domain:

```yaml
domain:
  id: review
  parent: session
  disable:
    - no-network
```

Result:

```text
no-git-branch remains enforced
no-network is disabled only for review
session and sibling domains are unchanged
```

If the child tries:

```yaml
disable:
  - no-git-branch
```

the kernel rejects the delta because `no-git-branch` is locked.

## Current Implementation Mapping

The current low-level ABI still uses `target_id` in some structs. In the security
model, that id is a domain id:

```text
cap_task[pid] -> domain id
cap_state[domain id] -> effective domain state
```

Current implemented fields:

```text
parent
scope_id
labels
authority_mask
target_mask
restrict_mask
gate_mask
label_mask
```

Still needed to fully implement this model:

```text
rule lock metadata
domain disabled-rule set
delta admission for disabling unlocked rules
dynamic child-domain creation
tests for locked versus unlocked parent rules
```
