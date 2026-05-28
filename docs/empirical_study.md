# Empirical Studies of Agent Instruction Files: A Survey for ActPlane

This document surveys five empirical studies (2025--2026) that characterize how
developers configure AI coding agents through instruction files (CLAUDE.md,
AGENTS.md, copilot-instructions.md, etc.).  It is intended as a reference for
writing the Background and Related Work sections of the ActPlane paper.

---

## 1. On the Use of Agentic Coding Manifests (Chatlatanagulchai et al., 2025)

**Full citation.**
Worawalan Chatlatanagulchai, Kundjanasith Thonglek, Brittany Reid, Yutaro
Kashiwa, Pattara Leelaprute, Arnon Rungsawang, Bundit Manaskasemsak, and
Hajimu Iida.  "On the Use of Agentic Coding Manifests: An Empirical Study of
Claude Code."  In *Proc. 26th International Conference on Product-Focused
Software Process Improvement (PROFES 2025)*, LNCS 16361, Springer, 2025.
arXiv:2509.14744.

### Methodology

- Collected **253 CLAUDE.md** files from **242 GitHub repositories** via the
  GitHub API, filtering for repos with >= 20 commits after CLAUDE.md
  introduction (collection window: 2025-02-24 to 2025-06-16).
- Two-phase content analysis:
  1. Extracted all H1/H2 section titles; three LLMs (Claude, Gemini, ChatGPT)
     generated candidate labels; authors curated to 20 labels.
  2. Two inspectors independently labeled each file (multi-label); 1,228
     assignments with 113 disagreements resolved by a third inspector.
     Final scheme: **15 content categories**.
- No formal inter-rater agreement coefficient (Cohen's kappa) reported.

### Key findings

| Category | Prevalence |
|---|---|
| Build and Run | 77.1% |
| Implementation Details | 71.9% |
| Architecture | 64.8% |
| Testing | 60.5% |
| System Overview | 48.2% |
| Development Process | 37.2% |
| Configuration & Environment | 26.5% |
| Maintenance | 19.8% |
| AI Integration | 15.4% |
| Documentation & References | 13.8% |
| Performance | 12.7% |
| Project Management | 11.1% |
| DevOps | 9.5% |
| Security | 8.7% |
| UI/UX | 8.3% |

- Structural properties: median 1 H1, 5 H2, 9 H3 headings; deep nesting
  (H4+) is rare.
- **No analysis of behavioral constraints, "do not" rules, or safety
  instructions.**  The 15-label taxonomy is purely thematic (what *topic* a
  section covers), not functional (whether the instruction *enables* or
  *restricts*).

### Limitations

- Claude-only; no cross-tool comparison.
- No assessment of manifest quality or agent-performance impact.
- No longitudinal / evolution analysis.
- Subjective labeling without formal reliability coefficients.

---

## 2. Agent READMEs (Chatlatanagulchai, Chen et al., 2025)

**Full citation.**
Worawalan Chatlatanagulchai, Hao Li, Yutaro Kashiwa, Brittany Reid,
Kundjanasith Thonglek, Pattara Leelaprute, Arnon Rungsawang, Bundit
Manaskasemsak, Bram Adams, Ahmed E. Hassan, and Hajimu Iida.  "Agent READMEs:
An Empirical Study of Context Files for Agentic Coding."  arXiv:2511.12884,
November 2025.

### Methodology

- **2,303 agent context files** from **1,925 repositories** across three tools:
  - Claude Code: 922 CLAUDE.md
  - OpenAI Codex: 694 AGENTS.md
  - GitHub Copilot: 687 copilot-instructions.md
- Sourced from 8,370 repos with >= 5 stars (AIDev dataset).
- Manual labeling of a 332-file Claude Code subset (80.3% initial agreement;
  disagreements resolved by third inspector).  **16 content categories.**
- Automated classification of the full corpus using GPT-5 (micro-avg
  F1 = 0.79; strongest on Testing 0.94, Architecture 0.93, Build&Run 0.92;
  weakest on Project Management 0.42, AI Integration 0.48).
- Maintenance analysis via commit history (5,655 + 2,767 + 2,237 commits).
- Readability: Flesch Reading Ease (FRE).

### Key findings

**RQ1 -- Characteristics:**
- Median length: Claude 485 words, Copilot 535, Codex 335.
- FRE: Claude 16.6 ("very difficult"), Copilot 26.6, Codex 39.6.
- Shallow hierarchy: median 1 H1, 6--7 H2, 11--12 H3.

**RQ2 -- Maintenance:**
- 59--67% of files modified in multiple commits.
- Median commit interval: Claude/Codex ~1 day, Copilot ~3 days.
- Append-dominated: median 57 words added, <15 deleted per commit.

**RQ3 -- Content (16 categories):**

| Category | Prevalence |
|---|---|
| Testing | 75.0% |
| Implementation Details | 69.9% |
| Architecture | 67.7% |
| Development Process | 63.3% |
| Build and Run | 62.3% |
| System Overview | 59.0% |
| Maintenance | 43.7% |
| Configuration & Environment | 38.0% |
| Documentation | 26.8% |
| AI Integration | 24.4% |
| Debugging | 24.4% |
| DevOps | 18.1% |
| Performance | **14.5%** |
| Security | **14.5%** |
| UI/UX | 8.7% |
| Project Management | 5.4% |

**Critical gap:** Non-functional requirements (Security 14.5%, Performance
14.5%) are drastically underrepresented relative to functional categories.
The authors conclude that developers "provide few guardrails to ensure that
agent-written code is secure or performant."

**On behavioral constraints specifically:**  The paper notes examples of
prohibitive instructions ("Do NOT use data- attributes", "NEVER CANCEL test
processes") but does *not* separately quantify what fraction of instructions
are prohibitive/restrictive vs. enabling.  There is **no analysis of
compliance or enforcement**.

### Limitations

- Manual labeling on only 332 of 2,303 files.
- GPT-5 classifier performance varies by category.
- Open-source bias (>= 5 stars); may not represent corporate usage.
- No temporal evolution analysis.
- No compliance / violation measurement.

---

## 3. Decoding the Configuration of AI Coding Agents (Santos et al., 2025)

**Full citation.**
Helio Victor F. Santos, Vitor Costa, Joao Eduardo Montandon, and Marco Tulio
Valente.  "Decoding the Configuration of AI Coding Agents: Insights from Claude
Code Projects."  In *1st International Workshop on Agentic Engineering (AGENT
2026)*, co-located with ICSE 2026, pp. 63--67.  arXiv:2511.09268.

### Methodology

- Searched GitHub for repos with CLAUDE.md files (Aug 28--30, 2025); from 4,724
  results, filtered to top-100 most popular repos (>= 100 stars, English,
  non-tutorial).
- Retrieved **328 CLAUDE.md files** (including referenced memory-bank files).
- Extracted **2,492 level-2 section titles**; one author grouped them into
  semantic categories, two others verified.
- Applied **FP-Max** algorithm (min support 0.15) for maximal frequent itemset
  mining to find co-occurrence patterns.

### Key findings

**RQ1 -- Concerns and practices:**

| Concern | Prevalence |
|---|---|
| Software Architecture | 72.6% |
| Development Guidelines | 44.8% |
| Project Overview | 39.0% |
| Testing Guidelines | 35.4% |
| Testing Commands | 33.2% |
| Dependencies | 30.8% |
| General Project Guidelines | 25.6% |
| Integration/Usage Guidelines | 18.0% |
| Configuration | 17.4% |

**RQ2 -- Code examples and links:** Development Guidelines sections most
often include code examples (17.7%); links are rare; only 2 files used
diagrams (Mermaid).

**RQ3 -- Co-occurrence patterns (top 5):**

| Pattern | Support |
|---|---|
| Architecture + Dependencies + Project Overview | 21.6% |
| Architecture + General Guidelines | 20.1% |
| Architecture + Dev Guidelines + Project Overview | 19.8% |
| Architecture + Dev Guidelines + Testing | 18.9% |
| Architecture + Integration | 17.7% |

Architecture appears in all top-5 patterns.

**On behavioral constraints:** The study focuses on SE concerns (architecture,
testing, development practices).  It does **not** address safety, security, or
behavioral restrictions.  No compliance/enforcement analysis.

### Limitations

- Single-author classification (reviewed by two others).
- Claude-only; no cross-tool comparison.
- Rapidly evolving field may outdate findings.

---

## 4. On the Impact of AGENTS.md Files on Efficiency (Lulla et al., 2026)

**Full citation.**
Jai Lal Lulla, Seyedmoein Mohsenimofidi, Matthias Galster, Jie M. Zhang,
Sebastian Baltes, and Christoph Treude.  "On the Impact of AGENTS.md Files on
the Efficiency of AI Coding Agents."  In *Journal Ahead Workshop (JAWs) 2026*,
co-located with ICSE 2026, ACM.  arXiv:2601.20404.

### Methodology

- Used **OpenAI Codex** (gpt-5.2-codex model) on **10 repositories**,
  **124 pull requests** (merged, <= 100 LoC changed, <= 5 files).
- Paired experiment: each PR task executed with and without AGENTS.md in
  isolated Docker containers.
- Metrics: wall-clock runtime (seconds), token consumption (input, cached
  input, output).
- Statistical test: Wilcoxon signed-rank (p < 0.05).
- AGENTS.md files were filtered to contain coding conventions, architecture,
  and project description (based on prior taxonomy).

### Key findings

| Metric | Without AGENTS.md | With AGENTS.md | Change |
|---|---|---|---|
| Median runtime | 98.57 s | 70.34 s | -28.64% |
| Mean runtime | 162.94 s | 129.91 s | -20.27% |
| Median output tokens | 2,925 | 2,440 | -16.58% |
| Mean output tokens | 5,745 | 4,591 | -20.08% |
| Mean input tokens | 353,010 | 318,652 | -9.73% |

- Task completion behavior remained comparable across conditions.
- AGENTS.md primarily benefits high-cost outlier runs (median input/cached
  tokens showed minimal change).

**On compliance/violation:** Explicitly **not measured**.  A manual sanity
check of 50 random samples verified non-trivial output, but no correctness
or compliance evaluation was performed.

### Limitations

- Only 10 repos, 124 PRs.
- Single agent tool (Codex); may not generalize.
- Small PRs only (<= 100 LoC).
- No semantic correctness evaluation.
- Excluded repos with multiple AGENTS.md files.

---

## 5. Dive into Claude Code (Liu et al., 2026)

**Full citation.**
Jiacheng Liu, Xiaohan Zhao, Xinyi Shang, and Zhiqiang Shen.  "Dive into
Claude Code: The Design Space of Today's and Future AI Agent Systems."
arXiv:2604.14228, April 2026.  Code: github.com/VILA-Lab/Dive-into-Claude-Code.

### Methodology

- Reverse-engineered Claude Code v2.1.88 TypeScript source (publicly
  available on npm).
- Mapped architecture into **7 functional components** and traced **5 core
  values** through **13 design principles** to implementation choices.
- Compared against OpenClaw (open-source multi-channel agent gateway) across
  6 dimensions.

### Key findings

**Architecture:**
- 98.4% of the codebase is operational infrastructure; only 1.6% is AI
  decision logic.
- Core loop: `while(true) { call model -> run tools -> repeat }`.
- Seven components: User, Interfaces, Agent Loop, Permission System, Tools
  (54 built-in + MCP), State & Persistence, Execution Environment.

**Permission system -- 7 modes:**
1. plan (approval required)
2. default (standard interactive)
3. acceptEdits (auto-approve certain ops)
4. auto (ML-based classifier, feature-gated)
5. dontAsk (no prompts, deny rules enforced)
6. bypassPermissions (minimal prompting, safety-critical checks preserved)
7. bubble (internal subagent escalation)

- Users approve **93% of permission prompts** -- approval fatigue undermines
  interactive confirmation as sole safety mechanism.
- Seven independent defense-in-depth layers: tool pre-filtering, deny-first
  rule evaluation, permission mode constraints, auto-mode ML classifier,
  shell sandboxing, session-scoped permissions, hook-based interception.

**Context management -- 5-layer pipeline:**
Budget Reduction -> Snip -> Microcompact -> Context Collapse -> Auto-Compact.

**CLAUDE.md processing:** Lazy-loaded via a 4-level hierarchy (managed
settings > directory-specific > project-root CLAUDE.md > auto-memory).
Instructions are treated as **context**, not as **policy** -- violations rely
on the model respecting instructions; unlike the permission system, there are
no hard deny/allow gates for CLAUDE.md directives.

**Five core values:** Human Decision Authority, Safety/Security/Privacy,
Reliable Execution, Capability Amplification, Contextual Adaptability.

**On OS-level enforcement:** Shell sandboxing restricts filesystem/network
access independent of the application-level permission model, but the paper
reports **no taint tracking, information-flow control, or syscall-level
enforcement**.

### Limitations

- Static analysis of one version (v2.1.88); architecture may evolve.
- No runtime experiments or user studies.
- No access to Anthropic's server-side system prompt or model weights.
- Observability-evaluation gap: silent failures may mask problems.
- Context compaction trades interpretability for efficiency.

---

## 6. Synthesis

### 6.1 What these studies collectively tell us about agent instruction files

The five studies converge on a consistent picture:

1. **Agent instruction files are ubiquitous and actively maintained.**
   Chatlatanagulchai et al. (2025b) find 59--67% are modified in multiple
   commits, typically every 1--3 days, with append-dominated evolution.

2. **Content is overwhelmingly functional.**  Across all studies, the top
   categories are Build/Run (62--77%), Implementation Details (70--72%),
   Architecture (65--73%), and Testing (35--75%).  These are *enabling*
   instructions that tell the agent what the project is and how to work in it.

3. **Non-functional requirements are rare.**  Security appears in only 8.7--14.5%
   of files; Performance in 12.7--14.5%.  These numbers are consistent across
   the Chatlatanagulchai (2025a) and Chatlatanagulchai et al. (2025b) corpora.

4. **Files are hard to read.**  FRE scores of 16.6--39.6 place them in the
   "difficult" to "very difficult" range (Chatlatanagulchai et al. 2025b).

5. **Architecture is the backbone.**  Santos et al. find Architecture in all
   top-5 co-occurrence patterns and 72.6% of files.

6. **Instruction files improve efficiency.**  Lulla et al. show a 28.64%
   median runtime reduction and 16.58% output token reduction when AGENTS.md
   is present, with comparable task completion.

### 6.2 "Behavioral contracts" vs. coding style

**No study explicitly separates behavioral contracts (restrictions, prohibitions,
invariants) from coding-style guidance.**  The taxonomies used by all three
corpus studies (Chatlatanagulchai 2025a: 15 categories; Chatlatanagulchai
2025b: 16 categories; Santos 2025: 9 categories) classify by *topic* (e.g.,
"Architecture", "Testing", "Security"), not by *speech act* (e.g., "must do X",
"must not do Y", "if X then Y").

Chatlatanagulchai et al. (2025b) note examples of prohibitive instructions
("Do NOT use data- attributes", "NEVER CANCEL") but do not quantify their
prevalence.  From the reported data we can observe that:

- **Security** (8.7--14.5%) is the closest proxy for behavioral contracts, but
  most security content is coding guidance ("workspace isolation", "permission
  systems"), not behavioral restrictions on the agent itself.
- **AI Integration** (15.4--24.4%) includes "role" definitions and behavioral
  framing, but the studies do not break this down further.
- **Development Process** (37.2--63.3%) includes commit-message and PR rules,
  which are quasi-contractual, but again no sub-classification.

**Bottom line:** The fraction of instructions that constitute enforceable
behavioral contracts (as opposed to coding style or project context) is
unknown from the existing literature.  This is a gap ActPlane's corpus study
can fill.

### 6.3 Compliance and violation measurement

**No study measures whether agents actually comply with instructions.**

- Chatlatanagulchai (2025a) explicitly states this as future work.
- Chatlatanagulchai et al. (2025b) analyzes only what developers write, not
  what agents do.
- Santos et al. (2025) does not discuss compliance.
- Lulla et al. (2026) measures efficiency (runtime, tokens) but not
  correctness or compliance.  Their sanity check verifies non-trivial output,
  not adherence to AGENTS.md instructions.
- Liu et al. (2026) documents the *mechanism* (permission system, deny rules)
  but provides no empirical violation rate data beyond the 93% approval rate
  statistic (which measures user behavior, not agent compliance).

**This is the central gap.**  All five studies assume instructions are followed
or do not ask the question.  None provides empirical evidence on violation
frequency, violation types, or whether enforcement matters.

### 6.4 Implications for ActPlane's corpus study methodology

ActPlane's corpus study can build directly on these findings while addressing
their gaps:

| Aspect | Existing studies | ActPlane opportunity |
|---|---|---|
| **Taxonomy axis** | Topic-based (what the instruction is *about*) | Speech-act-based (what the instruction *demands*: enable, restrict, gate, transform) |
| **Enforcement** | None measured | Kernel-level enforcement with violation logs |
| **Compliance data** | None | Empirical violation rates from eBPF telemetry |
| **Scope** | Userspace instructions (context for the model) | Syscall-boundary enforcement (holds for any tool/subprocess) |
| **Expressiveness** | Free-text natural language | Compiled DSL with labeled information-flow semantics |
| **What counts as "security"** | Vague ("workspace isolation") | Precise: label propagation, mask matching, lineage gates |

The existing studies establish that:
- Developers *want* behavioral constraints (they write prohibitive rules).
- Developers *rarely specify* non-functional constraints (security 8.7--14.5%).
- There is *no enforcement* today (CLAUDE.md is context, not policy -- Liu
  et al. 2026).
- Efficiency improves with better context (Lulla et al. 2026).

ActPlane can argue that the low prevalence of security/behavioral instructions
may partly reflect the *lack of enforcement infrastructure*: why write
constraints you cannot enforce?  The labeled information-flow model provides
the missing enforcement layer.

### 6.5 What ActPlane's corpus study asks that these studies do NOT answer

1. **What fraction of real-world agent instructions are enforceable behavioral
   contracts?**  None of the five studies classifies instructions by
   enforceability or by speech act (prohibition vs. obligation vs. preference).

2. **Do agents violate instructions, and how often?**  No study provides
   empirical violation rates.

3. **Can natural-language instructions be compiled to a formal policy?**  The
   existing studies treat instruction files as opaque text.  ActPlane's DSL
   demonstrates that a meaningful subset can be lowered to labeled
   information-flow rules.

4. **Does enforcement change agent behavior or developer practice?**  Lulla
   et al. measure efficiency without enforcement; no study measures the
   effect of *hard* enforcement (kill/deny at syscall boundary) on agent
   correctness, safety, or developer trust.

5. **What is the relationship between instruction-file content and actual
   syscall-level behavior?**  The existing studies analyze text; ActPlane
   can correlate text-level instructions with kernel-observed behavior.

6. **What information-flow properties do developers implicitly specify?**  The
   label/source/sink/propagation model in ActPlane can express constraints
   (e.g., "data read from secrets must not be written to network") that no
   existing taxonomy captures, even when developers write them in natural
   language.

---

## References

1. W. Chatlatanagulchai, K. Thonglek, B. Reid, Y. Kashiwa, P. Leelaprute,
   A. Rungsawang, B. Manaskasemsak, and H. Iida.  "On the Use of Agentic
   Coding Manifests: An Empirical Study of Claude Code."  PROFES 2025, LNCS
   16361, Springer, 2025.  arXiv:2509.14744.

2. W. Chatlatanagulchai, H. Li, Y. Kashiwa, B. Reid, K. Thonglek,
   P. Leelaprute, A. Rungsawang, B. Manaskasemsak, B. Adams, A. E. Hassan,
   and H. Iida.  "Agent READMEs: An Empirical Study of Context Files for
   Agentic Coding."  arXiv:2511.12884, November 2025.

3. H. V. F. Santos, V. Costa, J. E. Montandon, and M. T. Valente.
   "Decoding the Configuration of AI Coding Agents: Insights from Claude Code
   Projects."  AGENT 2026 (ICSE), pp. 63--67.  arXiv:2511.09268.

4. J. L. Lulla, S. Mohsenimofidi, M. Galster, J. M. Zhang, S. Baltes, and
   C. Treude.  "On the Impact of AGENTS.md Files on the Efficiency of AI
   Coding Agents."  JAWs 2026 (ICSE), ACM.  arXiv:2601.20404.

5. J. Liu, X. Zhao, X. Shang, and Z. Shen.  "Dive into Claude Code: The
   Design Space of Today's and Future AI Agent Systems."  arXiv:2604.14228,
   April 2026.
