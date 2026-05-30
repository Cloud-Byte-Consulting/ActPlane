# ARMO: eBPF-Based AI Agent Enforcement (Blog Series)

- **Source**: ARMO blog
- **Date**: March–May 2026

## Post 1: eBPF for AI Agent Enforcement — What Kernel-Level Security Catches (and What It Misses)

- **URL**: https://www.armosec.io/blog/ebpf-based-ai-agent-enforcement/

### Key argument: the semantic gap

Pure kernel-level enforcement (eBPF/LSM) catches low-level violations (file access,
network egress) but cannot reason about higher-level semantics (tool-call intent,
prompt injection, task boundaries). A complete agent enforcement stack needs both:
- Kernel layer: unbypassable syscall-level enforcement (eBPF)
- Application layer: semantic understanding of agent actions

---

## Post 2: AI Agent Sandboxing — Progressive Enforcement Guide

- **URL**: https://www.armosec.io/blog/ai-agent-sandboxing-progressive-enforcement-guide/

### Core problem: Policy Paralysis

Teams cannot write effective policies upfront because agent behavior is emergent and
non-deterministic. Two identical deployments produce different runtime behavior based
on user prompts. The result: overly restrictive policies that break production,
permissive policies with gaps, or no policies at all.

### Progressive enforcement framework (4 stages)

1. **Discovery** ("Flying Blind") — detect all AI workloads, build an AI Bill of
   Materials (AI-BOM) showing models, RAG sources, connected tools.

2. **Observation** ("See Everything, Enforce Nothing") — deploy in visibility-only mode.
   Record tools invoked, APIs called, network destinations, processes spawned, file
   access. Build "Application Profile DNA" representing actual runtime behavior over
   days/weeks.

3. **Selective Enforcement** ("Trust but Verify") — promote observed behaviors into
   enforcement policies. Start with highest-risk agents. Active blocking for
   high-confidence agents, alert-only for others.

4. **Full Least Privilege** ("Enforced by Evidence") — all agents operate within
   behavioral boundaries. Deviations blocked in real-time. Continuous observation as
   models and prompts evolve.

Key shift: **from predictive policy-writing to evidence-based constraints** derived
from observed runtime behavior. "Instead of declaring what an agent should do in a
config file, you let the agent tell you what it does through observed behavior."

### Isolation vs behavioral sandboxing

- **Isolation sandboxing** (containers, gVisor, microVMs) controls *where* agents run.
- **Behavioral sandboxing** controls *what* agents do.
- "An agent in the most isolated microVM can still exfiltrate data through legitimate
  API calls if prompt-injected." Isolation is necessary but insufficient.

### Four enforcement dimensions

1. API and tool access — restrict to observed endpoints
2. Network destinations — limit outbound connections
3. Process/syscall constraints — especially for code-generation agents
4. File and data access — restrict to observed filesystem paths

### Why traditional tools fall short

- **Kubernetes NetworkPolicies**: control traffic between pods, not runtime behavior
- **OPA/Gatekeeper**: admission-time rules on configs, not runtime adaptation
- **Agent Sandbox CRD**: infrastructure isolation, not behavioral control

### 30-day implementation roadmap

- Days 1–7: inventory all AI workloads
- Days 8–14: observation mode; build behavioral profiles for highest-risk agents
- Days 15–21: promote observed behaviors into enforcement (alert-only)
- Days 22–30: expand enforcement; establish per-agent policies; monitor drift

### Technical: eBPF overhead

- 1–2.5% CPU, 1% memory overhead
- Zero application code changes, no sidecars
- Same sensor for observation and enforcement

---

## Relevance to ActPlane

### What ActPlane already does well

ActPlane partially bridges the semantic gap through labeled IFC — labels carry semantic
meaning (SECRET, AGENT, REVIEWED) that elevates raw syscall events to policy-relevant
categories. The corrective-feedback mechanism further bridges the gap by translating
kernel-detected violations into model-readable explanations.

### Ideas worth borrowing

1. **Progressive enforcement as a first-class workflow.** ActPlane already has `notify`
   / `block` / `kill` per-rule effects, so the infrastructure exists — but there's no
   guided "observe first, then promote to enforcement" workflow. An `actplane observe`
   mode that profiles agent behavior and suggests rules would address the policy
   paralysis problem directly.

2. **Policy paralysis framing.** ARMO names the core UX problem: users don't know what
   policy to write because agent behavior is emergent. This is a strong motivation for
   ActPlane's "agents can generate their own policies" angle — if the agent itself (or
   a supervisor agent) can write DSL rules after observation, it solves policy paralysis
   without requiring the human to understand the behavior upfront.

3. **Behavioral drift as ongoing concern.** ARMO emphasizes that policies must evolve
   as models and prompts change. ActPlane's `since` staleness mechanism is already a
   form of drift-awareness (invalidate gates when state changes), but explicit
   policy-lifecycle support (version, diff, auto-update) is missing.

4. **Per-agent profiles.** Different agents need different policies. ActPlane's DSL
   already supports this via `source AGENT = exec "codex"` scoping, but the idea of
   automatically building per-agent "Application Profile DNA" from observation data
   and generating per-agent DSL policies is not yet articulated.
