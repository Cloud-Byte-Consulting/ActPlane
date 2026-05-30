# Agent Translation Prompt (for RQ1 + RQ2)

This prompt is used to dispatch subagents that translate natural-language
directives from the empirical corpus into ActPlane DSL rules.

## How to use

Spawn one subagent per repo (or batch of repos). Pass the repo directory
names as the task list. Each subagent reads the source material, writes
DSL rules, and validates them with `actplane check`.

```
Agent({
  prompt: <this prompt> + "\n\n## Your assigned repos\n\n" + repo_list,
  description: "Translate directives for {repo_names}"
})
```

---

## Prompt

You are translating natural-language agent directives into ActPlane DSL
rules. ActPlane is an eBPF policy engine that observes and enforces
information-flow policies on AI agents at the kernel level.

### Your task

For each assigned repo, read the directives and translate them into
ActPlane DSL rules.

### Input files (per repo)

Given a repo named `{REPO}` (e.g., `chenhg5__cc-connect`):

1. **Directives to translate**:
   `/home/yunwei37/workspace/ActPlane/docs/corpus/{REPO}/agent_rules.yaml`
   — each entry has `statement_id`, `text`, `enforceability`, `topic`,
   and a `rule:` field set to `null`. You fill the `rule:` field.

2. **Project instruction file**:
   `/home/yunwei37/workspace/ActPlane/docs/corpus/{REPO}/CLAUDE.md` or
   `AGENTS.md` — read this for project context (build system, test
   commands, directory conventions).

3. **Project metadata**:
   `/home/yunwei37/workspace/ActPlane/docs/corpus/{REPO}/meta.json`
   — repo name, language, description.

4. **Actual source code** (for path patterns):
   `/home/yunwei37/workspace/ActPlane/docs/corpus-evaluated/{REPO}/repo/`
   — shallow clone of the repo. Browse the directory structure to write
   accurate path patterns. Use `find ... -type f | head -50` or
   `ls -R | head -100` to understand the layout. Do NOT read every file
   — just enough to know directory structure and key file names.

**Important**: you write to `docs/corpus/{REPO}/agent_rules.yaml`
(not corpus-evaluated). The human reviewer will later copy and correct
your output into `docs/corpus-evaluated/{REPO}/agent_rules.yaml`.

5. **DSL reference**:
   `/home/yunwei37/workspace/ActPlane/docs/rule-language.md`
   — read Section 2 (grammar) and Section 3 (worked examples) for the
   full syntax. Read this ONCE at the start, not per-repo.

### DSL quick reference

```
source LABEL = exec|file|endpoint PATTERN

rule rule-name:
    notify|block|kill OP TARGET [ARGS...] [if EXPR] [unless COND]
    because "reason string"

OP     = exec | read | write | open | unlink | connect | recv
TARGET = [file|endpoint] PATTERN
COND   = target [not] PATTERN
       | lineage-includes exec PATTERN
       | after exec PATTERN [since EVENT_PAT (or EVENT_PAT)*]
EVENT_PAT = write|read|exec PATTERN
EXPR   = LABEL [and|or [not] LABEL]*
```

Basename matching: `exec "git"` matches `/usr/bin/git` (no `**/`
needed for exec targets). Path patterns use `**` for globbing:
`file "src/**/*.py"`.

Effects: `notify` (observe + tell agent), `block` (prevent operation),
`kill` (terminate process).

### Translation rules

1. **Read the directive text carefully.** Understand what behavior it
   constrains.

2. **Determine if it's translatable.** A directive is translatable if
   its core constraint can be expressed as:
   - A per-event match (deny a specific exec/read/write/connect), OR
   - A cross-event flow (track labels across operations), OR
   - A temporal gate (require action X before action Y)

   A directive is NOT translatable if it requires:
   - Content inspection ("code must follow style X")
   - External system interaction ("upload to service X")
   - Semantic understanding ("write clear commit messages")

3. **If translatable, write the DSL rule.** Use the project context
   (CLAUDE.md, repo structure) to write accurate patterns:
   - Use actual binary names from the project (e.g., `pytest` vs `jest`
     vs `go` based on the project language)
   - Use actual directory paths from the repo structure
   - Choose the appropriate effect:
     - `notify` for reminders/guidance ("run tests before commit")
     - `block` for hard constraints ("don't write to generated files")
     - `kill` for critical constraints ("don't push to main")

4. **Partial translation is better than null.** If a directive has
   multiple constraints and only some are expressible, translate what
   you CAN and put the rest in the `because` string as a reminder.
   For example, a 7-step checklist where 2 steps are expressible as
   rules → write those 2 as rules, list the other 5 in `because`.
   Only leave `rule:` as null when **nothing** in the directive maps
   to a syscall-level event (pure content inspection, pure semantic
   reasoning).

5. **Write a `because` string** that is useful to the agent — explain
   what happened and what to do instead. Include any untranslatable
   parts of the directive as a checklist reminder.

### Examples

Directive: "Run tests before committing: `go test ./...`"
(Go project, enforceability: cross_event)

```yaml
rule: |
  source AGENT = exec "claude"
  rule tests-before-commit:
    block exec "git" "commit"
      if AGENT unless after exec "go" "test" since write "**/*.go"
    because "Source files changed since last test run. Run `go test ./...`, then commit."
```

Directive: "Never modify vendor/ files"
(enforceability: per_event)

```yaml
rule: |
  source AGENT = exec "claude"
  rule no-vendor-writes:
    block write file "vendor/**" if AGENT
    because "Vendor files are managed by the package manager, not edited directly."
```

Directive: "Adding a new platform: 1. Create platform/X/X.go 2. Implement
core.Platform interface 3. Register in init() 4. Add build tag 5. Update
ALL_PLATFORMS in Makefile 6. Add config example 7. Add unit tests"
(enforceability: cross_event, partial — steps 5-7 are expressible)

```yaml
rule: |
  source AGENT = exec "claude"
  source PLATFORM_CHANGED = file "platform/**/*.go"
  rule platform-checklist:
    notify exec "git" "commit"
      if PLATFORM_CHANGED unless after exec "go" "test" since write "platform/**"
    because "New platform files changed. Run tests, and also verify: update ALL_PLATFORMS in Makefile, add config example in config.example.toml, add build tag in cmd/cc-connect/."
```

Directive: "Keep Rust and TS wire renames aligned"
(enforceability: cross_event, pure content inspection — nothing maps to syscalls)

```yaml
rule: null
```

### Validation

After filling all rules for a repo, write a temporary policy file and
validate:

```bash
# For each non-null rule, create a temp policy and check it
cat > /tmp/test_policy.yaml << 'PEOF'
version: 1
policy: |
  <paste the rule here>
PEOF

/home/yunwei37/workspace/ActPlane/collector/target/release/actplane check --policy /tmp/test_policy.yaml
```

If `actplane check` reports errors, fix the rule. Warnings about
BPF-LSM not being active are expected and can be ignored — they just
mean `block` rules will behave as `notify` without BPF-LSM.

Note: `actplane check` only validates syntax, not semantic correctness.
A syntactically valid rule may still be semantically wrong (e.g., wrong
path pattern). Use your judgment for semantic correctness based on the
project context.

### Output

For each entry in `agent_rules.yaml`, update the `rule:` field in place:
- If translatable: set `rule:` to the DSL rule string (multi-line, using
  YAML `|` block scalar)
- If not translatable: leave `rule:` as `null`

Do NOT modify `statement_id`, `text`, `enforceability`, or `topic` fields.

### Important

- Each rule must include a `source` declaration for any labels it uses.
  A rule like `block exec "git" "commit" if AGENT` needs
  `source AGENT = exec "claude"` (or appropriate binary) declared before it.
- Multiple directives from the same repo may share the same `source`
  declarations. When validating, combine all rules from one repo into
  a single policy to check for conflicts.
- Prefer `notify` over `block` unless the directive clearly demands
  prevention ("never", "do not", "must not").
- Prefer `block` over `kill` unless the directive is about a
  catastrophic action.
