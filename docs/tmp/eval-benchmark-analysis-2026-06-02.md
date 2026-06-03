# ActPlane Eval: Candidate Benchmarks Analysis

Date: 2026-06-02

Which existing benchmarks can ActPlane directly use or adapt, and what
does ActPlane uniquely add to each?

---

## 1. Three Candidate Benchmarks

### 1.1 OctoBench — Instruction Following in Coding Agents

**Paper:** Ding et al., arXiv:2601.10343, Jan 2026. PDF: `octobench.pdf`.
**Repo:** `github.com/MiniMax-AI/mini-vela`

| Dimension | Details |
|---|---|
| Scale | 34 environments, 217 tasks, 7,098 checklist items |
| Agent scaffolds | Claude Code, Kilo, Droid |
| Execution | Real execution in Docker, full trajectory logging |
| Instructions from | CLAUDE.md, config files, system prompts, skills, memory, tool schemas |
| Measurement | Binary checklist items scored by 3-judge LLM panel |
| Metrics | CSR (per-check compliance ~80%), ISR (end-to-end all-checks ~10-28%) |
| Key finding | **Scissors gap**: high per-check compliance does NOT translate to end-to-end success |

**Why it fits ActPlane:**

OctoBench tests exactly what ActPlane addresses: agents fail to
simultaneously satisfy multiple heterogeneous instructions from repo
config files during real coding tasks. The "scissors gap" (CSR 80% vs
ISR 10-28%) is ActPlane's value proposition — runtime enforcement can
catch the 20% per-rule misses before they compound.

OctoBench includes Claude Code as a scaffold. ActPlane integrates with
Claude Code. The instructions come from CLAUDE.md and similar files —
the same sources ActPlane's corpus is drawn from.

**How to use it:**

```
Condition A: OctoBench as-is (no enforcement)
  → Baseline CSR and ISR already published (Table 2)

Condition B: OctoBench + ActPlane enforcement + feedback
  → Run same tasks with ActPlane DSL rules derived from OctoBench's
    instruction sources
  → Measure: does ISR improve? Does CSR improve?
  → Key comparison: ISR_B − ISR_A = ActPlane's contribution to
    end-to-end compliance
```

**Challenges:**
- Need to translate OctoBench's checklist items into ActPlane DSL rules.
  Not all checklist items are OS-level enforceable (some are semantic:
  "code should be readable"). Only OS-observable items can be enforced.
- OctoBench's Docker environments may need modification for eBPF
  (privileged containers or shared kernel).
- Scoring is LLM-as-Judge on trajectories, not deterministic. ActPlane
  adds a deterministic enforcement signal but the overall score still
  needs LLM judgment.

**Verdict: BEST FIT for instruction-following evaluation.** Can directly
show that ActPlane improves the scissors gap on an established benchmark.

---

### 1.2 AGENTIF — Instruction Following in Agentic Scenarios

**Paper:** Qi et al. (Tsinghua), arXiv:2505.16944, May 2025. PDF: `agentif.pdf`.
**Repo:** `github.com/THU-KEG/AgentIF`

| Dimension | Details |
|---|---|
| Scale | 50 real-world agentic apps, 707 instructions, 8,415 constraints |
| Instructions | From industrial agents (Cursor, Manus) + open-source agent system prompts |
| Constraint types | Formatting, Semantic, **Tool** (10-27% compliance — lowest) |
| Presentation types | Vanilla, Conditional, Example |
| Measurement | Code-based + LLM-based + Hybrid evaluation |
| Metrics | CSR (per-constraint) and ISR (per-instruction, all constraints) |
| Key finding | Tool constraints are hardest (10-27%); compliance drops sharply from simple (87%) to realistic (58%) scenarios |

**Why it fits ActPlane:**

AGENTIF's "tool constraints" category directly maps to ActPlane's
enforcement scope: "use correct parameter types for function calls",
"restrict tool usage to a predefined set", "avoid internet access".
The 10-27% compliance rate on tool constraints is the strongest
published motivation for tool-level enforcement.

**How to use it:**

```
Condition A: AGENTIF as-is
  → Baseline CSR already published (Table 2: tool constraints 10-27%)

Condition B: AGENTIF tasks + ActPlane enforcement on tool constraints
  → For each tool constraint, write an ActPlane DSL rule
  → Measure: does tool-constraint CSR improve?
```

**Challenges:**
- AGENTIF tasks are single-turn function calls, not multi-step coding in
  repos. Less realistic than OctoBench for coding agents.
- Instructions come from system prompts, not repo config files. Different
  instruction delivery mechanism from ActPlane's target.
- No execution environment — agents generate responses, don't actually
  execute commands. Would need to add real execution for ActPlane.

**Verdict: BEST for motivation data.** The 10-27% tool constraint
compliance is the strongest single number to cite. But the benchmark
itself is harder to adapt for ActPlane's OS-level enforcement because
it lacks real execution environments.

---

### 1.3 AgentDojo — Security Against Prompt Injection

**Paper:** Debenedetti et al. (ETH Zurich), NeurIPS 2024. PDF: `agentdojo.pdf`.
**Repo:** `github.com/ethz-splab/agentdojo`

| Dimension | Details |
|---|---|
| Scale | 97 user tasks, 629 security test cases, 4 environments |
| Environments | Workspace (email/calendar/drive), Slack, Banking, Travel |
| Threat model | Indirect prompt injection via tool returns |
| Agent | Tool-calling LLM agent |
| Measurement | Deterministic utility function + security function per task |
| Metrics | Utility (task completion) and Security (attack blocked) |
| Key finding | Best models solve <66% of tasks even without attacks; ASR ~25% with attacks |

**Why it fits ActPlane:**

AgentDojo tests security (prompt injection defense), not compliance.
But it has two properties that make it useful:

1. **Joint utility + security measurement.** AgentDojo measures both
   whether the agent completes the task AND whether attacks succeed.
   This is the right framework for ActPlane: enforcement should block
   attacks without hurting utility.

2. **Progent already ran on it.** Progent (tool-layer enforcement) reduced
   ASR from 39.9% to 1.0% on AgentDojo. If ActPlane runs on the same
   benchmark, we get a direct head-to-head: ActPlane (OS-level) vs
   Progent (tool-level) on identical tasks.

3. **Extensible framework.** AgentDojo supports adding new defenses via
   a simple agent interface. ActPlane could be plugged in as a defense
   layer.

**How to use it:**

```
Condition A: AgentDojo no defense
  → Baseline: Utility ~66%, ASR ~40% (published)

Condition B: AgentDojo + Progent
  → Published: Utility ~76%, ASR ~1% (Progent paper)

Condition C: AgentDojo + ActPlane
  → New: Utility ?%, ASR ?%
  → Compare B vs C: does OS-level enforcement match or beat tool-level?
```

**Challenges:**
- AgentDojo's environments (email, banking, travel) are NOT coding
  environments. ActPlane is designed for coding agents.
- The tools are simulated Python functions, not real OS operations.
  ActPlane's eBPF enforcement doesn't apply to simulated tools.
- To use ActPlane on AgentDojo, the tool implementations would need to
  make real system calls (file I/O, network), which they currently don't.

**Verdict: BEST for security comparison with Progent.** Gives a direct
head-to-head on an established security benchmark. But requires
significant adaptation because AgentDojo's environments don't use
real OS operations.

---

## 2. Comparison Table

| | OctoBench | AGENTIF | AgentDojo |
|---|---|---|---|
| **What it tests** | Instruction following in coding | Instruction following in agentic apps | Security against prompt injection |
| **Agent type** | Claude Code / Kilo / Droid | Generic LLM (single-turn) | Tool-calling LLM |
| **Environment** | Real repo in Docker | No execution env | Simulated stateful env |
| **Instructions from** | CLAUDE.md, config files | System prompts | N/A (tasks, not instructions) |
| **Real execution** | ✅ Yes | ❌ No | Simulated |
| **OS-level operations** | ✅ bash, git, file I/O | ❌ | ❌ |
| **Existing baseline** | ✅ CSR 80%, ISR 10-28% | ✅ Tool CSR 10-27% | ✅ Utility 66%, ASR 40% |
| **Progent comparison** | ❌ | ❌ | ✅ Progent: ASR 40%→1% |
| **Adaptation effort** | Medium (translate checklist → DSL) | High (add execution env) | High (real OS operations) |
| **ActPlane's unique value** | Improves ISR via enforcement | Improves tool constraint CSR | OS-level defense vs tool-level |

---

## 3. Recommended Eval Plan

### Primary benchmark: OctoBench (instruction compliance)

OctoBench is the best fit because:
1. Same agent (Claude Code), same instruction sources (CLAUDE.md)
2. Real execution in Docker environments
3. Published baseline numbers (ISR, CSR)
4. The scissors gap (CSR 80% → ISR 10-28%) is ActPlane's exact value prop
5. Checklist-based evaluation enables fine-grained analysis

**What ActPlane adds:** Runtime enforcement that catches per-rule misses
(the 20% that makes CSR 80% but ISR 28%), improving end-to-end
compliance.

### Secondary benchmark: AgentDojo subset (security)

A subset of AgentDojo tasks where tool calls involve real OS operations
(or can be adapted to). This gives a Progent head-to-head and shows
ActPlane works for security, not just compliance.

**What ActPlane adds:** OS-level enforcement that Progent's tool-layer
cannot provide (bypass-free via kernel hooks).

### Motivation data (cited, not run):

| Source | Number to cite | In paper where |
|---|---|---|
| McMillan et al. | CLAUDE.md compliance decays −5.6% per step | §1 motivation |
| AGENTIF | Tool constraint compliance = 10-27% (lowest) | §1 motivation |
| OA-Safety | Agents unsafe 49-73% on OS-level tools | §1 motivation |
| ODCV-Bench | 0-56% misalignment under task pressure | §1 motivation |
| Guardrails BG | Negative constraints are the only beneficial rule type | §1 + §Design |
| Lulla et al. | AGENTS.md improves efficiency 20-28% | §Related work |

### Supplementary: Terminal-Bench (end-to-end task completion)

Keep the existing RQ5 design (89 tasks, 3 conditions). This provides
the "task completion" number for the abstract claim.

---

## 4. What ActPlane Uniquely Contributes to Each Benchmark

**No existing benchmark tests runtime enforcement of behavioral policies.**

| Benchmark | What it measures | What ActPlane adds (new) |
|---|---|---|
| OctoBench | Do agents follow instructions? | Does enforcement MAKE them follow instructions? |
| AGENTIF | How well do agents follow tool constraints? | Can OS-level enforcement improve the worst category? |
| AgentDojo | Can agents resist prompt injection? | Does OS-level enforcement outperform tool-level? |
| McMillan | Does compliance decay within sessions? | Does enforcement prevent the decay? |

The common thread: **everyone measures the problem; ActPlane measures the
solution.** This is the paper's unique eval contribution — the first
measurement of whether runtime enforcement improves agent instruction
compliance.

---

## 5. Practical Next Steps (Priority Order)

1. **Get OctoBench running locally.** Clone `github.com/MiniMax-AI/mini-vela`,
   run the Docker environments, reproduce baseline numbers on a few tasks.

2. **Map OctoBench checklist items to ActPlane rules.** For each environment,
   identify which checklist items are OS-enforceable. Write DSL rules.

3. **Run OctoBench + ActPlane.** Compare ISR and CSR with and without
   enforcement.

4. **Terminal-Bench (existing RQ5).** Run with 3 conditions (no AP, bare
   EPERM, full feedback). This is already designed.

5. **AgentDojo subset (stretch goal).** If time allows, adapt a subset of
   AgentDojo tasks for OS-level enforcement and compare with Progent.

---

## References

- Ding et al. "OctoBench: Benchmarking Scaffold-Aware Instruction Following
  in Repository-Grounded Agentic Coding." arXiv:2601.10343, Jan 2026.
- Qi et al. "AGENTIF: Benchmarking Instruction Following of Large Language
  Models in Agentic Scenarios." arXiv:2505.16944, May 2025.
- Debenedetti et al. "AgentDojo: A Dynamic Environment to Evaluate Prompt
  Injection Attacks and Defenses for LLM Agents." NeurIPS 2024.
  arXiv:2406.13352.
- Zhang et al. "Agent Security Bench (ASB): Formalizing and Benchmarking
  Attacks and Defenses in LLM-based Agents." ICLR 2025. arXiv:2410.02644.
- McMillan. "Instruction Adherence in Coding Agent Configuration Files."
  arXiv:2605.10039, May 2025.
- Qi et al. "AGENTIF." arXiv:2505.16944, May 2025.
- Zhang et al. "Guardrails Beat Guidance." arXiv:2604.11088, May 2026.
- Lulla et al. "On the Impact of AGENTS.md Files on the Efficiency of AI
  Coding Agents." ICSE JAWs 2026.
- Vijayvargiya et al. "OpenAgentSafety." ICLR 2026. arXiv:2507.06134.
- Li et al. "ODCV-Bench." arXiv:2512.20798.
- Shi et al. "Progent: Securing AI Agents with Privilege Control."
  arXiv:2504.11703.
- Wang et al. "AgentSpec: Customizable Runtime Enforcement for Safe and
  Reliable LLM Agents." ICSE 2026.
