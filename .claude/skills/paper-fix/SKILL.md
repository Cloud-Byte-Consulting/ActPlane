---
name: paper-fix
description: Fix academic writing antipatterns in a LaTeX paper section. Applies sentence-level rewrites for prose quality.
when_to_use: Fix paper writing, rewrite sentences, improve academic prose, fix LaTeX section writing
argument-hint: [section-file-path]
allowed-tools: Read Edit Bash(grep *)
---

# Fix Academic Paper Writing

Fix academic writing antipatterns in the LaTeX file at `$ARGUMENTS`. If no argument is given, ask which section to fix.

## Process

1. Read the entire file
2. Identify all antipatterns (see checklist below)
3. For each issue, show the original and proposed rewrite to the user
4. Apply fixes using the Edit tool after user confirmation
5. Preserve all technical content and design decisions; only improve prose

## Critical rules

- **NEVER delete design decisions or technical content.** Compression means better prose, not less information.
- **NEVER change the meaning** of a sentence. If unsure, ask.
- **NEVER remove a scope-bearing hedge** (`suggest ... on the selected subset`, `in our setting`, `up to`): it protects the claim from outrunning its evidence (/paper-logic A4/A5). Only collapse stacked hedges down to one.
- **Always diff-check** after multiple edits to ensure no content was lost.
- **No em-dashes** (`---`) in paper text. Table `---` for N/A is fine.
- **No semicolons** joining independent clauses. Use periods, conjunctions, or causal connectors.
- **Why before what**: every design decision states its motivation first.
- **Example before abstraction**: show a concrete case, then generalize.

## Fix priority (apply in this order)

### Priority 1: Logic and clarity
- Missing motivation for design decisions (add "why" before "what")
- Vague referents ("this", "it" with unclear antecedent)
- Dangling modifiers
- Incorrect or misleading claims

### Priority 2: Sentence structure
- Semicolons joining independent clauses -> rewrite with connectors
- Note-like short declarative sentences -> merge with causal connectors
- Weak "There is/It is" openings -> concrete subjects
- Passive voice where actor matters -> active voice
- Nominalizations -> verb forms

### Priority 3: Word choice
- "in order to" -> "to"
- "utilize" -> "use"
- "due to the fact that" -> "because"
- "is able to" -> "can"
- Other verbose phrases (see /paper-review for full list)

### Priority 4: Punctuation
- Colons before non-lists -> restructure
- Em-dashes -> commas, parentheses, or restructured sentences

## Rewrite patterns

### Semicolons -> flowing prose
When replacing semicolons, don't just swap punctuation. Rewrite the sentence to flow:

Before: `Labels propagate at fork; the child inherits the parent mask.`
After: `Labels propagate at fork, so the child inherits the parent mask.`

Choose the connector based on the logical relationship:
- **Cause/effect**: "because", "since", "so", "therefore"
- **Addition**: ", and"
- **Contrast**: ", but", "however," (new sentence), "although"
- **Elaboration**: restructure as a relative clause or appositive

### Note-like -> academic prose
Before: `The DSL has three components. Sources identify objects. Targets are operations. Effects decide outcomes.`
After: `Each rule in the DSL encodes three components: a source identifies which objects the rule applies to, a target names the operation being constrained, and an effect determines whether the engine blocks, kills, or notifies.`

### Missing why
Before: `Labels are monotonic.`
After: `To ensure no history is lost across the session, labels are monotonic.`

### Vague referent
Before: `The engine checks labels and propagates them. This improves safety.`
After: `The engine checks and propagates labels. This monotonic tracking improves safety.`

## Output

After all fixes, provide a summary:
- Number of sentences changed
- Categories of changes made
- Any sentences you flagged but did NOT change (and why)
