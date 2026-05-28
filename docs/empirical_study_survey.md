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

**Data collection.** 253 CLAUDE.md files from 242 GitHub repositories,
collected via GitHub API (case-insensitive search for files named
`Claude.md`). Collection window: 2025-02-24 to 2025-06-16. Filtering
criterion: repositories must have at least 20 commits after introducing
their CLAUDE.md file.

**Label creation (Phase 1).** Extracted all H1/H2 section headings from
the 253 files. Prompted three LLMs (Claude, Gemini, ChatGPT) to generate
candidate labels from the headings. One author selected and consolidated
labels; two authors reviewed. Started with 80 candidate labels,
consolidated to 20, finalized at **15 content categories**.

**Label assignment (Phase 2).** Two inspectors (paper authors, not
external annotators) independently assigned labels to each file.
**Unit of analysis: whole file** (multi-label per file). Total: 1,228
label assignments across 253 files. 113 disagreement instances (~9.2%
conflict rate). Resolution: "a third inspector joined the discussion and
collaborated with the initial two to reach a consensus on the final
labels."

**Inter-rater reliability: no formal metric reported.** No Cohen's kappa,
no Krippendorff's alpha, no percent-agreement statistic. The only
quantitative information is the 113/1,228 disagreement count.

**Methodological gaps.** LLM-assisted label creation without validation
of LLM suggestions; informal consensus resolution; labeling at file
granularity (not section or instruction level); no external annotators.

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

**Data collection.** 2,303 agent context files from 1,925 repositories
across three tools: Claude Code (922 CLAUDE.md), OpenAI Codex (694
AGENTS.md), GitHub Copilot (687 copilot-instructions.md). Filtered from
8,370 repos with at least 5 GitHub stars (AIDev dataset).

**Label creation.** Same two-stage approach as Paper 1, expanded to 16
categories. Phase 1 used Claude Opus 4.1, Gemini 2.5 Pro, and GPT-5 to
generate candidate labels from section headings. Authors curated to 16
final categories (added "Debugging" vs. Paper 1's 15).

**Manual labeling.** 332 Claude Code files manually labeled by three
inspectors with "programming experience ranging from 4 to 17 years."
**How the 332-file subset was selected is not documented in the paper**
(no mention of random or stratified sampling). Two inspectors independently
assigned labels to each file. Total: 2,227 label assignments before
resolution. 438 instances of disagreement (**80.3% raw agreement rate**).
Resolution: third inspector consensus. **No Cohen's kappa or formal
reliability metric reported.**

**Automated classification.** GPT-5 used as a multi-label binary
classifier on the full 2,303 files. Prompt contained "(i) the full context
file content and (ii) a concise description and representative examples for
each category." **The exact prompt is not disclosed in the paper** (stated
to be in the replication package). Validated against the 332 manually
labeled files as ground truth.

GPT-5 per-category F1: Testing 0.94, Architecture 0.93, Build & Run 0.92,
System Overview 0.89, Implementation Details 0.89, Development Process 0.83,
Configuration & Environment 0.75, Security 0.74, DevOps 0.72, Performance
0.71, Debugging 0.71, Documentation 0.57, UI/UX 0.56, Maintenance 0.56,
AI Integration 0.48, Project Management 0.42. **Micro-average F1: 0.79.**

**Maintenance analysis.** Commit history: 5,655 (Claude) + 2,767 (Codex) +
2,237 (Copilot) commits analyzed. Readability: Flesch Reading Ease (FRE).

**Methodological gaps.** No formal reliability metric beyond raw agreement;
332-file sample selection undocumented; GPT-5 prompt not disclosed in paper;
per-category F1 varies from 0.42 to 0.94 (weakest categories are exactly
those most relevant to behavioral contracts: AI Integration 0.48, Project
Management 0.42); unit of analysis is file-level.

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

**Data collection.** Searched GitHub for repos containing CLAUDE.md files
(Aug 28--30, 2025). From 4,724 results, filtered to top-100 most popular
repos (>=100 stars, English, non-tutorial/non-awesome-list). Retrieved 328
CLAUDE.md files (including referenced memory-bank files; 45 detected).

**Section extraction.** Automated markdown parsing extracted 2,492 level-2
section titles. For 36 files without level-2 sections, level-1 headings
were used instead. **Unit of analysis: section title** (not full section
content, not individual instructions).

**Classification.** Verbatim from paper: "These sections were then manually
analyzed by one of the authors, who grouped them into semantically related
categories according to the software engineering concerns and practices they
refer to...Next, a meeting was held with two other authors, who inspected
the proposed classification and confirmed it." That is: **single coder,
two meeting-based verifiers. No named coding methodology** (no open coding,
no thematic analysis, no card sorting). No quantitative inter-rater
reliability metric of any kind.

**Co-occurrence analysis.** Applied FP-Max algorithm (min support 0.15) for
maximal frequent itemset mining on the category assignments.

**Methodological gaps.** Single-coder classification is the weakest design
among the five studies. The "verification" is qualitative confirmation in a
meeting, not independent coding. Classification operates on section titles
only, not section content, so instructions within sections are invisible.

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

**Agent.** OpenAI Codex (gpt-5.2-codex model). Verbatim: Codex was
"selected because it is specifically designed for software engineering
tasks." Not Claude Code.

**Dataset.** 10 repositories (randomly sampled from 26 qualifying repos),
124 pull requests (up to 15 merged PRs per repo). PR inclusion criteria:
<=100 LoC changes, <=5 modified files, merged status, created after
AGENTS.md introduction, code-only changes. AGENTS.md files were
pre-existing in the repositories, not created by the researchers.

**Experimental design.** Paired within-task comparison: each PR task
executed once with and once without AGENTS.md present, in isolated Docker
containers with identical repo snapshots. Independent variable: presence of
AGENTS.md. Dependent variables: wall-clock runtime (seconds), token
consumption (input, cached input, output).

**Statistical test.** Wilcoxon signed-rank test (p < 0.05).

**Sanity check.** Verbatim: "we randomly sampled 50 PR tasks and inspected
the corresponding agent outputs, comparing them against the human-written
merged pull requests, to confirm that they resulted in non-empty,
non-trivial code changes consistent with the intended task, rather than
aborted runs or random edits." This verifies outputs were non-trivial,
**not** that AGENTS.md instructions were followed.

**What was explicitly not measured.** Verbatim: "A comprehensive evaluation
of the output quality, e.g., the semantic correctness or the functional
equivalence to the merged PR, is beyond the scope of this paper." And:
"whether agent-produced changes are correct, maintainable, or aligned with
developer intent" remains unmeasured.

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

**This is a design-space analysis, not an empirical study.** The paper
reverse-engineered the publicly available TypeScript source code of Claude
Code v2.1.88 (obtained from an external GitHub mirror / npm). Verbatim:
"Our analysis is grounded primarily in the source code, supplemented by
official Anthropic documentation and selected community analysis."

**Scope.** Mapped the architecture into 7 functional components and traced
5 core values through 13 design principles to implementation choices.
Compared against OpenClaw (open-source multi-channel agent gateway) across
6 dimensions.

**No original empirical data.** No benchmarks, no user studies, no
experiments. All statistics cited in the paper are sourced from Anthropic's
internal data:
- "93% approval rate": Verbatim -- "Anthropic's auto-mode analysis found
  that users approve approximately 93% of permission prompts." Citation
  points to Anthropic's own documentation, not an independent measurement.
- "132 engineers" survey: Also Anthropic's internal data.
- "20% to 40%" auto-approve trajectory: Also cited from Anthropic
  longitudinal data.

**Methodological gaps.** Static analysis of one version only (v2.1.88);
no runtime experiments; no access to Anthropic's server-side system prompt
or model weights; all quantitative claims are Anthropic's, not
independently verified.

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

- Liu et al. cite Anthropic's internal data that users approve **93% of
  permission prompts** (not independently measured). This suggests
  approval fatigue undermines interactive confirmation as a safety mechanism.
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

7. **Interactive confirmation degenerates to rubber-stamping.** Liu et al.
   cite Anthropic's internal data showing that users approve 93% of
   permission prompts in Claude Code (the statistic is Anthropic's, not an
   independent measurement by Liu et al.). This means the primary
   interactive enforcement mechanism provides negligible filtering in
   practice. Combined with the finding that CLAUDE.md is treated as context
   rather than policy (Liu et al.: "violations rely on the model respecting
   instructions; there are no hard deny/allow gates for CLAUDE.md
   directives"), these data points establish that today's harnesses have no
   effective behavioral enforcement: prompt-level compliance is
   probabilistic, and interactive confirmation is near-universally approved.

8. **Efficiency gains are documented; correctness enforcement is not.**
   Lulla et al. measured that instruction files reduce runtime by 29%, but
   explicitly did not measure compliance: "no correctness or compliance
   evaluation was performed." This gap between demonstrated efficiency
   benefits and unmeasured correctness guarantees is the central motivation
   for OS-level enforcement.

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

The following table illustrates how the same enforcement-relevant speech act
("must not X unless Y") scatters across different topic categories in the
existing taxonomies, making behavioral contracts invisible to topic-based
analysis:

| Real instruction | Topic category (prior studies) | ActPlane category |
|---|---|---|
| "run tests before committing" | Testing | Temporal ordering (E5) |
| "never commit secrets" | Security | Data flow (E1/E7) |
| "never push to main directly" | Development Process | VCS gate (E5/E11) |
| "must use the gh-create-pr skill" | AI Integration | Lineage mediation (E3) |

All four are cross-object contracts requiring state tracking, but they appear
in four different topic categories in the existing taxonomies. ActPlane's
speech-act-based classification groups them by enforcement requirement rather
than by topic.

**Bottom line:** The fraction of instructions that constitute enforceable
behavioral contracts (as opposed to coding style or project context) is
unknown from the existing literature.

**ActPlane's corpus study addresses this gap.** From 144 popular projects (228
instruction files, 39,803 lines), we extracted 3,762 candidate imperative
statements via keyword matching and classified them by category regex into
ActPlane-relevant categories (mapped to DSL constructs E1--E12). Preliminary
findings (all numbers are upper bounds from automated extraction; manual
coding with Cohen's kappa has not yet been completed):

- **101/144 (70%) of projects** contain at least one keyword-and-category
  match. This is an **upper bound**: the category regex admits noise
  (build instructions, commit-message formatting rules), so the true
  prevalence of enforceable behavioral contracts is lower and will be
  determined by manual D1--D7 coding. The distribution of candidates per
  repo (from corpus-analysis.md) is:

  | Candidates per repo | Repos | Cumulative |
  |---|---|---|
  | 0 | 43 | 43 (30%) |
  | 1--2 | 19 | 62 (43%) |
  | 3--5 | 26 | 88 (61%) |
  | 6+ | 56 | 144 (100%) |

  The distribution is bimodal: 30% of projects have zero candidates, while
  39% have six or more. This suggests behavioral contracts are concentrated
  in projects that actively govern agent behavior rather than spread thinly.

- The top categories by repo count are: VCS commit/push gates (63 repos),
  test-before-commit (51 repos), secrets/credentials (40 repos), approval
  gates (23 repos), and mandatory mediation (20 repos).
- These contracts span three patterns that require cross-object state
  tracking: **data flow** (secrets: 40 repos), **temporal ordering**
  (test-before-commit: 51 repos), and **lineage mediation** (mandatory
  tool routing: 20 repos). We use the term "cross-object" rather than
  "information flow" for temporal and lineage patterns, since they track
  execution ordering and process ancestry rather than data propagation
  (Section 6.2.1 below).
- Keyword matching has known **recall limitations**: contracts stated as
  positive imperatives ("always run tests first") and long-sentence
  narratives (e.g., untrusted-input policies) are under-counted. The
  untrusted-input category registered only 1 repo by keyword but manual
  inspection found additional instances (see corpus-analysis.md Section 6).

**Methodological caveats.** The DSL constructs E1--E12 were designed from
an initial examination of instruction files, so the correspondence between
corpus categories and DSL constructs is by construction, not by independent
validation. The finding is that the *prevalence* of these patterns is high,
not that the DSL is independently validated by the corpus. A precision
estimate (manual labeling of a random sample of the 529 candidates) and
inter-rater reliability (Cohen's kappa on the D1--D7 coding) are required
before these numbers can be cited as final results. See
`docs/tmp/corpus-analysis.md` for full methodology, per-category breakdown,
signal-cleanliness annotations, and representative quotes.

#### 6.2.1 Why temporal and lineage patterns require cross-object tracking

A reviewer may object that "run tests before committing" is a workflow
ordering constraint, not an information-flow property. We include it because
enforcement requires the same mechanism: the enforcer must maintain state
(a temporal gate) across multiple OS operations in the agent's process tree
and check that state at a later enforcement point. Per-event matching cannot
express "commit only if a test process executed earlier in this session."
The labeled IFC framework encodes this as an `after` gate: the `TESTED`
label is set when a test binary executes, and the commit rule checks for
its presence. The mechanism is label propagation and checking; the
*semantics* differ (data provenance vs. temporal ordering vs. process
ancestry), but the *enforcement substrate* is the same. We use "cross-object
contracts" as the umbrella term in the paper to avoid over-claiming that all
patterns are information flow in the strict DIFC sense.

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
  but provides no empirical violation rate data beyond citing Anthropic's
  93% approval rate statistic (which measures user behavior, not agent
  compliance, and is not independently verified).

**This is the central gap.** All five studies assume instructions are followed
or do not ask the question. None provides empirical evidence on violation
frequency, violation types, or whether enforcement matters. Three quotes from
the prior authors themselves underscore the gap:

> Chatlatanagulchai et al. (2025b): developers "provide few guardrails to
> ensure that agent-written code is secure or performant."

> Liu et al. (2026): CLAUDE.md instructions are treated as "context, not as
> policy ... violations rely on the model respecting instructions; there are
> no hard deny/allow gates for CLAUDE.md directives."

> Lulla et al. (2026): "no correctness or compliance evaluation was
> performed."

These statements, from the authors of the three largest empirical studies of
agent instruction files, collectively establish that behavioral enforcement
for coding agents is an unaddressed problem.

### 6.4 Relationship to existing studies

ActPlane's corpus study differs from the five surveyed studies along six
dimensions:

| Aspect | Existing studies | ActPlane corpus study |
|---|---|---|
| **Taxonomy axis** | Topic-based (what the instruction is *about*) | Speech-act-based (what the instruction *demands*: restrict, gate, flow) |
| **Enforcement** | None measured | Kernel-level enforcement with violation logs |
| **Compliance data** | None | Empirical violation rates from eBPF telemetry |
| **Scope** | Userspace instructions (context for the model) | Syscall-boundary enforcement (holds for any tool/subprocess) |
| **Expressiveness** | Free-text natural language | Compiled DSL with labeled information-flow semantics |
| **What counts as "security"** | Vague ("workspace isolation") | Precise: label propagation, mask matching, lineage gates |

The existing studies establish that developers write prohibitive rules, that
instruction files are ubiquitous (59--67% modified in multiple commits), and
that there is no enforcement mechanism (CLAUDE.md is context, not policy;
Liu et al. 2026). The low prevalence of security/behavioral instructions in
their taxonomies (8.7--14.5%) may partly reflect the topic-based
classification, which scatters behavioral contracts across Build, Testing,
and Development Process categories rather than grouping them by
enforceability. Whether the availability of enforcement infrastructure
would change what developers write is an open question that this study
does not answer.

### 6.5 Questions the existing studies do not answer

1. **What fraction of real-world agent instructions are enforceable behavioral
   contracts?** None of the five studies classifies instructions by
   enforceability or speech act. ActPlane's corpus study finds
   behavioral-contract candidates in 70% of projects (101/144, upper bound
   from keyword+regex extraction; not yet validated by manual coding).

2. **Do agents violate instructions, and how often?** No study provides
   empirical violation rates. ActPlane's evaluation (Section 6) measures
   this under four feedback conditions.

3. **Can natural-language instructions be compiled to a formal policy?**
   ActPlane's DSL demonstrates that a meaningful subset of cross-object
   contracts (spanning data-flow, temporal-ordering, and lineage-mediation
   patterns) can be lowered to label-propagation rules.

4. **Does enforcement change agent behavior?** Lulla et al. measure
   efficiency without enforcement. ActPlane's C3-vs-C4 experiment isolates
   the effect of kernel-level enforcement with corrective feedback on agent
   recovery rate.

5. **What cross-object contract patterns do developers implicitly specify?**
   The corpus study identifies three recurring patterns: data flow (secrets,
   40 repos), temporal ordering (test-before-commit, 51 repos), and lineage
   mediation (mandatory tool routing, 20 repos). All three require
   cross-object state tracking and cut across the existing topic-based
   taxonomies.

---

## 7. Methodology Comparison Across Studies

The following table compares the empirical methodology of all five prior
studies and ActPlane's corpus analysis along key dimensions. This is intended
as a reference for positioning ActPlane's methodology in the paper.

### 7.1 Methodology comparison table

| Dimension | Chatlatanagulchai (2025a) | Chatlatanagulchai et al. (2025b) | Santos et al. (2025) | Lulla et al. (2026) | Liu et al. (2026) | **ActPlane** |
|---|---|---|---|---|---|---|
| **Venue** | PROFES (SE) | arXiv (SE) | AGENT/ICSE (SE) | JAWs/ICSE (SE) | arXiv (systems) | OSDI/ATC (systems) |
| **Corpus size** | 253 files / 242 repos | 2,303 files / 1,925 repos | 328 files / 100 repos | 10 repos / 124 PRs | 1 system (Claude Code) | 228 files / 144 repos |
| **Sampling** | GitHub API, >=20 commits after CLAUDE.md | AIDev dataset, >=5 stars | GitHub search, top-100 by stars | 10 curated repos | Single system reverse-eng. | GitHub search, top by stars, excl. doc-only |
| **Classification method** | LLM-generated labels, 2 inspectors manual | 332 manual (selection method undocumented) + GPT-5 auto (F1=0.79, prompt not disclosed in paper) | 1 author classified, 2 verified in meeting; no named coding methodology | N/A (efficiency, not content) | Source code reading; all statistics cited from Anthropic internal data | Keyword+regex (automated) |
| **Inter-rater reliability** | No kappa; 113/1228 disagreements (3rd resolves) | No kappa; 80.3% raw agreement only | **None** (single coder + qualitative meeting verification) | N/A | N/A | **Not yet done** |
| **Classification granularity** | File-level (15 topic categories) | File-level (16 topic categories) | Section-title-level (9 concerns) | N/A | Component-level | **Line-level** (D1-D7 dimensions) |
| **Precision/recall reported?** | No | LLM F1 per category (0.42-0.94) | No | N/A | N/A | **Not yet done** |
| **Compliance measured?** | No | No | No | No (efficiency only) | No (mechanism only) | Planned (C1-C4 experiment) |
| **Taxonomy axis** | Topic (what it's about) | Topic (what it's about) | SE concern (what it's about) | N/A | Architecture | **Speech act** (what it demands) |
| **Behavioral contracts distinguished?** | No | No (noted examples, not quantified) | No | No | No | **Yes** (D1: style vs contract) |

### 7.2 Key observations

**No study reports Cohen's kappa.** All three corpus studies (Chatlatanagulchai
2025a, 2025b; Santos 2025) resolve disagreements by consensus (third inspector
or reviewer) rather than reporting a reliability coefficient. ActPlane's
planned D1-D7 coding with kappa would be an improvement over the field
baseline, but the field baseline itself does not require kappa.

**Automated classification is standard.** Chatlatanagulchai et al. (2025b) use
GPT-5 to classify 2,303 files after manually labeling only 332 (14%). The
reported F1 ranges from 0.42 (Project Management) to 0.94 (Testing). This
sets a precedent: LLM-based classification with manual spot-check is accepted
at SE venues. ActPlane's keyword+regex approach is less sophisticated but
operates at line-level rather than file-level granularity.

**Sample sizes vary widely.** Lulla et al. use only 10 repos / 124 PRs and
are published at ICSE. Santos et al. use 100 repos. ActPlane's 144 repos is
in the upper range for this literature.

**File-level vs line-level.** All prior studies classify at file level or
section-title level ("this file contains Architecture content"). ActPlane's
corpus analysis classifies at line level ("this specific sentence is a
behavioral contract about secrets"). This is a finer granularity but requires
higher precision to be credible, since individual lines are noisier than
file-level topic classifications.

### 7.3 Implications for ActPlane's paper

1. **Kappa is not required by the field.** No prior study in this space
   reports kappa. Including it would be an improvement, not a requirement.
   For an OSDI systems paper (where the corpus is motivation, not the
   contribution), kappa is a nice-to-have.

2. **LLM-based classification is an accepted methodology.** Using an LLM
   (Claude, GPT) to classify line-level candidates, with a manual
   spot-check sample for precision estimation, would be at least as
   rigorous as Chatlatanagulchai et al. (2025b) and more rigorous than
   Santos et al. (2025).

3. **The minimum viable methodology for OSDI motivation** is:
   (a) automated extraction (already done: keyword+regex),
   (b) manual precision spot-check on a random sample of 50-100 candidates,
   (c) representative quotes from real files (already done),
   (d) honest upper-bound/lower-bound framing (already done).
   This exceeds what CamQuery, Capsicum, or pledge did for motivation.

4. **The recommended methodology for a stronger contribution** is:
   (a) LLM classification of all candidates (category + confidence),
   (b) manual coding of a stratified sample (50-100) by two annotators,
   (c) Cohen's kappa on the sample,
   (d) precision and recall estimates.
   This would match or exceed the rigor of Chatlatanagulchai et al. (2025b)
   and make the corpus study defensible as a standalone contribution at an
   SE venue if needed.

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
