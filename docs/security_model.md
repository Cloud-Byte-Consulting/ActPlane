# Security Model

ActPlane's reusable engine has two layers:

```text
IFC core:       object + label + event + rule
Runtime policy: domain + binding + delta + authority
```

Agent, subagent, MCP, hooks, prompts, and workspaces are integrations above this
model. They are not part of the engine security model.

## Core Entities

An IFC rule is pure system policy:

```text
rule = condition + effect + reason
```

A domain is the runtime policy boundary for a process tree:

```text
pid -> domain
domain -> effective policy
event(pid) checks only pid's domain
```

Files, sockets, and stdio are not domains. They are IFC objects that carry
labels and participate in flow rules.

A binding attaches a rule to a domain:

```text
binding = domain + rule
```

All bindings are mandatory and monotonic: once a rule is bound to a domain, it
cannot be removed or disabled by the domain or its children.

## Two Logical YAMLs

It is useful to keep two logical files, even if a CLI later allows them in one
physical YAML.

Rule catalog:

```yaml
version: 1

rules:
  no-git-branch:
    ifc: |
      rule no-git-branch:
        kill exec "git" "branch"
        because "do not create git branches"

  no-network:
    ifc: |
      rule no-network:
        block connect any
        because "network is disabled by default"

  readonly:
    ifc: |
      rule readonly:
        block write file any
        because "this domain is read-only"
```

Domain policy:

```yaml
version: 1

domains:
  session:
    bind:
      - no-git-branch
      - no-network
```

The same rule can be bound by different domains:

```yaml
domains:
  review:
    parent: session
    bind:
      - readonly

  build:
    parent: session
    bind:
      - readonly
```

## Effective Policy

For a domain `D`:

```text
policy(D) = policy(parent(D)) + local(D)
```

The security invariant is monotonic tightening:

```text
policy(child) >= policy(parent)
```

Here `>=` means "at least as restrictive". A child domain inherits all parent
rules and may only add more rules. It cannot remove, disable, or weaken any
inherited rule.

## Child Updates

A child domain may update its own domain policy if its authority allows it.

Allowed updates:

```text
add local bindings
add labels
add gates
narrow scope
create child domains with no more authority than delegated
```

Rejected updates:

```text
remove inherited bindings
modify parent domain state
modify sibling domain state
widen scope
remove labels or gates
increase delegated authority
mutate an existing rule definition
```

## Examples

### 1. Child Adds a Rule for Its Own Children

Child domain:

```yaml
domains:
  review:
    parent: session
    bind:
      - readonly
```

Grandchild domain:

```yaml
domains:
  review-helper:
    parent: review
```

Result:

```text
review-helper inherits no-git-branch, no-network from session
review-helper inherits readonly from review
review-helper cannot remove any of these rules
```

### 2. Runtime Rule Addition

Rules can be added at runtime if they are submitted as compiled policy deltas.
The kernel should not parse YAML or DSL in the admission path.

CLI shape:

```bash
actplane rule compile rules/no-curl.yaml --out no-curl.ir
actplane domain bind review --rule-ir no-curl.ir
```

Semantics:

```text
userspace compiles rule DSL -> rule IR
userspace submits add-rule delta
kernel checks authority
kernel installs rule into review's effective policy
```

A domain can also bind an existing catalog rule at runtime:

```bash
actplane domain bind review --rule no-network
```

This is allowed only if the caller has authority to update `review`.

## Runtime Delta Admission

User space does not directly mutate effective policy state. It submits deltas.

Useful delta classes:

```text
create_domain
bind_rule
add_rule_ir
add_label
add_gate
narrow_scope
```

A delta contains only precompiled IDs and masks:

```text
caller_pid
domain_id
required_mask
add_label_mask
add_restrict_mask
add_gate_mask
new_scope_id
bind_rule_ids
```

The kernel admits a delta only if:

```text
caller_pid is bound to a domain
caller may affect the target domain
caller has the required authority bits
scope only narrows
labels/gates/restrictions only add
new bindings do not weaken inherited policy
```

Accepted deltas are merged into the domain's already-computed effective state.
The syscall fast path should not walk the domain tree.

## Rule Identity

Runtime-added rules should be content-addressed or versioned:

```text
rule_id = hash(compiled_rule_ir)
```

This prevents a child from changing the meaning of an inherited rule by
reusing its name with different contents.

Names such as `no-network` are user-facing aliases. Kernel admission should use
stable IDs or hashes.

## Current Implementation Mapping

The current low-level ABI still uses `target_id` in some structs. In this model,
that id is a domain id:

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

Implemented today:

```text
rule catalog in policy YAML
domain bindings in policy YAML
default_domain / --domain selection
actplane domains effective-policy view
actplane check/compile selected-domain summary
starter actplane.yaml generated in domain schema
binding resolution at compile time
valid and invalid domain policy corpus tests
CLI UX tests for domain selection/errors
user ringbuf request path
domain-like state map
pid-to-domain-like binding
mask-based authority checks
monotonic labels/restrictions/gates/scope update
```

Still needed to fully implement this model:

```text
domain naming in low-level BPF ABI
stable rule IDs / content hashes
runtime domain binding table
delta admission for bind
runtime add-rule IR maps
dynamic child-domain creation
```
