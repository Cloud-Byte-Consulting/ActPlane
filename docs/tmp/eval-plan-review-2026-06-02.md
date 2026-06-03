# ActPlane Evaluation Plan — For Review

Date: 2026-06-02. Pre-experiment. Requesting review.

## Paper Abstract Claims (main.tex)

> "ActPlane **improves policy compliance by XX%** over existing enforcement
> mechanisms and **end-to-end task completion by XX pp**, with **<X µs**
> per-syscall overhead."

Three numbers to prove:
- C1: compliance improvement (XX%)
- C2: task completion improvement (XX pp)
- C3: overhead (<X µs)

## Proposed Evaluation

### Exp 1: Instruction Compliance (OctoBench) → supports C1

**Benchmark:** OctoBench (Ding et al., arXiv:2601.10343)
- 217 tasks, 34 Docker environments, 7,098 checklist items
- Scaffolds: Claude Code, Kilo, Droid
- Published baselines: CSR ~80%, ISR 10-28%

**Method:**
- Condition A: OctoBench as-is (published baseline)
- Condition B: OctoBench + ActPlane enforcement + semantic feedback
- Translate OS-enforceable checklist items (~30-40%) into ActPlane DSL rules
- Run agent in OctoBench Docker with ActPlane (--privileged)
- Score with OctoBench's evaluation (3-judge LLM panel)

**Metric:** ΔCSR and ΔISR on enforceable items

**Expected:** ActPlane catches the 20% per-rule misses, improving ISR

### Exp 2: Safety Enforcement (OpenAgentSafety) → supports C1

**Benchmark:** OpenAgentSafety (Vijayvargiya et al., ICLR 2026)
- 361 tasks, OpenHands Docker sandbox, real bash/file/browser
- Published baselines: 49-73% unsafe (7 models)
- Deterministic evaluator.py per task

**Method:**
- Condition A: OA-Safety as-is (published baseline)
- Condition B: OA-Safety + ActPlane enforcement + feedback
- Derive ActPlane rules from safety checkpoints
  (e.g., "don't hardcode secrets" → IFC rule on SECRET label)
- Run on OS-level-relevant tasks (~50-60% of 361)

**Metric:** Δunsafe rate on enforceable task subset

**Expected:** ActPlane prevents OS-level unsafe actions (file delete,
secret leak, dangerous exec)

### Exp 3: End-to-End Task Completion (Terminal-Bench) → supports C2

**Benchmark:** Terminal-Bench (89 CLI tasks in Docker)

**Method:**
- Condition B1: No ActPlane (baseline)
- Condition B2: ActPlane enforcement + bare EPERM (no feedback)
- Condition B3: ActPlane enforcement + semantic feedback

**Metric:** Task completion rate (test script pass/fail)

**Expected:**
- B3 > B1 (ActPlane improves task completion via guardrails)
- B3 > B2 (semantic feedback enables recovery, bare EPERM doesn't)
- B3 - B2 = feedback contribution (the load-bearing claim)

### Exp 4: Overhead → supports C3

**Method:** Standard microbenchmark + macrobenchmark
- Per-syscall latency (fork/exec/open/write/connect) × rule counts (1/10/32/100)
- Agent trace replay end-to-end overhead
- Memory consumption

**Metric:** p50/p99 latency, overhead %

**Expected:** <X µs at p99 with 32 rules

## Questions for Reviewer

1. **Does this plan fully support the paper's abstract claims?**
   - C1 ("improves policy compliance by XX%"): Exp 1 (OctoBench) + Exp 2 (OA-Safety)
   - C2 ("end-to-end task completion by XX pp"): Exp 3 (Terminal-Bench)
   - C3 ("<X µs overhead"): Exp 4

2. **Is OctoBench the right benchmark for C1?**
   - The abstract says "607 policies from the empirical study" but OctoBench
     uses its own checklist items, not our 607 directives.
   - Should we also run on our own corpus (607 directives × real repos)?
   - Or is OctoBench sufficient as a third-party validation?

3. **Is the compliance claim supported?**
   - OctoBench measures instruction following (checklist compliance), not
     "policy compliance" in the paper's sense (directive-derived enforcement).
   - The abstract says "improves policy compliance over existing enforcement
     mechanisms" — this implies a comparison against tool-layer and other
     enforcement systems, not just "with vs without ActPlane."
   - Do we need the 7-system comparison from eval.md to support this claim?

4. **Is the threat model aligned?**
   - Paper: "cooperative-but-forgetful" agents that need behavioral policies
   - OctoBench: tests whether agents follow heterogeneous instructions
     during coding tasks — natural forgetfulness, not adversarial
   - OA-Safety: tests safety under benign+adversarial intent — includes
     adversarial scenarios not in our threat model
   - Is this misalignment a problem?

5. **What about the "607 policies" claim?**
   - Abstract says "evaluate on 607 policies from the empirical study"
   - Current plan doesn't directly use our 607 corpus directives
   - OctoBench has its own instruction set; OA-Safety has its own tasks
   - Do we need an experiment that directly uses our 607 directives?

6. **Scale and statistical rigor?**
   - OctoBench: 217 tasks × 2 conditions. Is this enough?
   - OA-Safety: ~200 enforceable tasks × 2 conditions. Is this enough?
   - How many runs per condition for statistical significance?
   - What statistical tests? Bootstrap CI? McNemar?

7. **Practical concerns?**
   - OctoBench uses LiteLLM proxy + scaffold scripts. How does ActPlane
     integrate without breaking the observation harness?
   - OA-Safety uses OpenHands framework. Does ActPlane need to be
     integrated into OpenHands, or can it wrap the entire process?
   - Both need --privileged Docker for eBPF. Any kernel compatibility issues?

8. **What's missing?**
   - No experiment directly measures "natural forgetfulness rate" on our
     607 corpus directives (McMillan et al. measured CLAUDE.md compliance
     decay, but on a different instruction type)
   - No multi-model comparison (OctoBench tested 8 models, we should test ≥2)
   - No comparison with tool-layer systems (AgentSpec, Progent) on the
     same benchmark — currently only ActPlane vs no-ActPlane
