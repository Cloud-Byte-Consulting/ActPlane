# Enforceability Annotation Review

## Summary

Reviewed 8 `statements.yaml` files from the 64-repository corpus, mixing small, medium, and large instruction files:

| File | Statements | Directives | Description/null | Enforceability distribution |
|---|---:|---:|---:|---|
| `browser-use__browser-harness` | 5 | 3 | 2 | 2 intent, 1 per-event |
| `ag-ui-protocol__ag-ui` | 7 | 7 | 0 | 6 intent, 1 per-event |
| `google__adk-python` | 10 | 8 | 2 | 7 intent, 1 per-event |
| `InsForge__InsForge` | 17 | 11 | 6 | 1 intent, 6 linter, 4 per-event |
| `charmbracelet__crush` | 43 | 27 | 16 | 1 intent, 18 linter, 7 per-event, 1 cross-object |
| `openai__openai-agents-python` | 50 | 34 | 16 | 5 intent, 16 linter, 2 per-event, 11 cross-object |
| `openai__codex` | 85 | 76 | 9 | 4 intent, 58 linter, 6 per-event, 8 cross-object |
| `openclaw__openclaw` | 147 | 131 | 16 | 23 intent, 44 linter, 45 per-event, 19 cross-object |

Overall quality is good for clear file-path/command constraints, style rules, and coordinated multi-file update rules. Most questionable cases are concentrated in a few recurring patterns rather than broad misunderstanding of the taxonomy.

## Correct Classifications

- `browser-use__browser-harness`, id 4: "An agent operating the harness only edits inside `agent-workspace/`" is correctly `behavior_per_event`. A write/open-for-write outside the allowed paths is detectable from one file operation.

- `ag-ui-protocol__ag-ui`, id 1: "When running tasks ... prefer running the task through `nx` ... instead of using the underlying tooling directly" is correctly `behavior_per_event`. The relevant shell command can be matched against `nx` vs direct tool invocations.

- `charmbracelet__crush`, ids 24-37: import grouping, gofumpt formatting, Go naming, comment punctuation, JSON tag naming, and commit-message shape are correctly `behavior_linter`. Each requires inspecting source or message text, not just observing the write/commit event.

- `openai__openai-agents-python`, id 26: "Adding new tool/output/approval item types requires coordinated updates across..." is correctly `behavior_cross_object`. Detecting noncompliance requires comparing a semantic change in one location against required edits in several other files.

- `openai__codex`, ids 17, 20, 21: "if config/dependencies change, regenerate/check schema or lockfiles" are correctly `behavior_cross_object`. These depend on prior file changes and later generated/check commands or paired file modifications.

- `openclaw__openclaw`, id 52: "Build before push when build output, packaging, lazy/module boundaries, dynamic imports, or published surfaces can change" is correctly `behavior_cross_object`. It depends on the changed surface plus ordering before a later push.

## Questionable Classifications

- `InsForge__InsForge`, id 6: "Before writing or editing any InsForge integration code, you MUST call the `fetch-docs` MCP tool..." is labeled `intent`. If MCP/tool calls are considered observable operations, this should be `behavior_cross_object`: it requires tracking a prior `fetch-docs` call before later file modifications. The same pattern appears in `ag-ui-protocol__ag-ui` ids 2-7, `google__adk-python` ids 2-6, `openai__openai-agents-python` ids 4-6 and 18, and several OpenClaw skill-routing rules. If the taxonomy intentionally excludes agent tool-call observation, the coding guide should say that explicitly; otherwise these look systematically underclassified as `intent`.

> **Author response:** Agent tool calls ARE observable operations. MCP tool calls are system-level events (they produce network/IPC traffic). "MUST call fetch-docs before writing code" is `behavior_cross_object` (ordering constraint). Pure tool-routing preferences ("use nx_workspace tool first") without ordering constraints are `behavior_per_event`. This is a systematic undercount that needs correction across AI Integration directives.

- `openai__openai-agents-python`, id 30: the full development workflow is labeled `behavior_per_event`, but it is a compound directive containing cross-object rules: run verification before completion, build docs when docs change, add/update tests alongside code, and invoke a summary step after substantial code work. By Step 5, this should be `behavior_cross_object`, or split into smaller statements.

- `openai__codex`, id 25: "When running Rust commands ... never try to kill them using the PID" is labeled `intent`. The violation is observable as a later kill operation against a previously started Rust command process, so this is at least system-level. Because the target process identity depends on earlier command state, `behavior_cross_object` is the better label.

- `openai__codex`, id 5: "Never add or modify any code related to `CODEX_SANDBOX_NETWORK_DISABLED_ENV_VAR` or `CODEX_SANDBOX_ENV_VAR`" is labeled `behavior_per_event`. The violation is not derivable from the file path alone; it requires inspecting modified code for specific identifiers or related logic. Suggested label: `behavior_linter`.

> **Author response:** Agree partially. The env var names are concrete strings that can be grep-matched in written file content, so this is `behavior_per_event` if we match the write target (files containing those strings). But "code related to" is broader than just the string — it includes surrounding logic. Keeping as `behavior_per_event` since the concrete strings are the primary enforcement signal; the "related" part is judgment.

- `InsForge__InsForge`, id 17: "Use Tailwind CSS 3.4 (do not upgrade to v4). Lock these dependencies in `package.json`" is labeled `behavior_per_event`. The lock/version requirement is a file-content constraint on `package.json`, so `behavior_linter` fits better, even though some upgrade commands might also be interceptable per event.

> **Author response:** This is `behavior_per_event`. "Do not upgrade" = block the upgrade command (npm install tailwindcss@4). The version check in package.json is a secondary signal. The primary enforcement is intercepting the upgrade action.

- `openai__openai-agents-python`, id 36: "Type hints must pass `make typecheck`" is labeled `behavior_per_event`. A single command invocation is not enough unless exit status and changed-code context are modeled as part of the same event. If interpreted as "ensure typecheck passes before readiness," it should be `behavior_cross_object`; if interpreted as a source conformance property, it is closer to `behavior_linter` or an external linter-backed check.

- `openclaw__openclaw`, id 125: "Never commit real phone numbers, videos, credentials, live config" is labeled `behavior_per_event`. Blocking `git commit` alone cannot distinguish compliant from noncompliant commits; enforcement requires scanning staged/committed content. Suggested label: `behavior_linter` under Step 2, or `behavior_cross_object` if the model treats "commit" as requiring accumulated staged-file state.

> **Author response:** This is `behavior_per_event`. "Never commit credentials" = block writes to files matching secret patterns (`.env`, `credentials.json`, etc.) or block git commit when staged files include secret-pattern matches. ActPlane does exactly this with `source SECRET = file "**/.env"` + `deny exec git @arg commit if SECRET`. The file path pattern IS the enforcement signal, not content inspection.

- `openai__codex`, ids 28-30: "resist adding code to `codex-core`" and "consider whether..." are labeled `intent`. That is defensible because the wording is soft and partly deliberative, but the underlying file-write surface is concrete. These should probably be low-confidence edge cases, or split into an intent statement ("consider whether...") plus a system-level constraint if the annotator intends "do not add to `codex-core` without justification."

## Systematic Patterns

- **MCP/skill/tool usage is treated inconsistently.** Direct command wrappers such as `nx` are `behavior_per_event`, while explicit MCP/skill calls are often `intent`. The taxonomy needs a policy for whether agent-level tool invocations count as observable operations. If they do, many AI Integration directives should move from `intent` to `behavior_per_event` or `behavior_cross_object`.

> **Author response:** Agreed. Agent tool calls ARE observable (MCP produces IPC/network events). Pure routing preferences ("use this tool") = `behavior_per_event`. Ordering constraints ("call fetch-docs BEFORE writing code") = `behavior_cross_object`. This is a systematic undercount in AI Integration directives that needs correction. Will add a coding-guide rule and re-audit.

- **Long workflow blocks are sometimes over-compressed.** Multi-step numbered lists often contain several independent constraints with different enforceability levels. When kept as one statement, Step 5 usually pushes them to `behavior_cross_object`, but some are labeled `behavior_per_event`. Splitting these would improve both annotation precision and downstream statistics.

- **Content-sensitive prohibitions are sometimes labeled per-event.** Rules about not committing secrets, not modifying code related to a symbol, dependency version pins, PR body fields, and generated text formats generally require content inspection. These should default to `behavior_linter` unless the prohibited object is fully identified by a command/path pattern.

> **Author response:** Disagree with the general principle. "Never commit secrets" IS per-event because secrets are identified by file path patterns (`.env`, `credentials.json`, `id_rsa`), not content inspection. This is exactly what ActPlane's labeled IFC does: `source SECRET = file "**/.env"` + `deny exec git @arg commit if SECRET`. Dependency version pins ("don't upgrade tailwind") are also per-event (block the upgrade command). Only cases where the prohibited content has no path/command signal (like "no promotional language in CHANGELOG") are truly behavior_linter.

- **Command catalogs vs. commands-to-run are ambiguous.** Some sections listing build/test commands are treated as directives, while similar "utilities/tips" sections are descriptions with `null` enforceability. The directive test says imperatives count, so bullets like "Use `examples/`", "Review `Makefile`", or "Consult `tests/README.md`" may need rechecking if the corpus is meant to capture all imperative advice.

- **Subjective qualifiers need confidence downgrades or splitting.** Phrases like "when feasible", "prefer", "resist", "when appropriate", and "larger behavior/product/security" often combine a concrete observable action with a judgment-heavy condition. Many current labels are plausible, but these should often be medium/low confidence unless the condition is mapped to concrete paths or events.

## Overall Assessment

The annotations are broadly reliable for the easy cases and capture the main enforceability distinctions well. I would not expect a wholesale relabeling to be necessary. The main risk is systematic undercounting of enforceable AI-integration/tool-routing directives as `intent`, plus undercounting cross-object requirements when multi-step workflow lists are left unsplit.

Recommended cleanup before final analysis:

1. Add a coding-guide rule for MCP/skill/tool-call directives.
2. Re-audit compound workflow statements labeled `behavior_per_event`.
3. Re-audit per-event labels where the forbidden/required property is only visible after inspecting file, commit, PR, or output content.
4. Mark soft subjective directives as lower confidence or split the deliberative part from the observable constraint.
