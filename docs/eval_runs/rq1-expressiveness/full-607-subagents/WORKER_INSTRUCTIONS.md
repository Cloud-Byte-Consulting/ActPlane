# RQ1 Full-607 Batch Worker Instructions

You are translating one batch of OS-enforceable corpus directives into
ActPlane policies.

Do not edit `docs/papers/`.
Do not run `git branch` or `git worktree`.
Write only inside your assigned batch directory:

```text
docs/eval_runs/rq1-expressiveness/full-607-subagents/batches/batchXX/
```

## Inputs

Your assigned `batch.jsonl` has one directive per line. Each record includes:

```text
uid, repo, repo_dir, statement_id, directive, enforceability, nl_tokens
```

Use project context from:

```text
docs/corpus/{repo_dir}/AGENTS.md
docs/corpus/{repo_dir}/CLAUDE.md
docs/corpus-evaluated/{repo_dir}/repo/
docs/rule-language.md
```

## Output Files

Create:

```text
results.jsonl
summary.json
summary.md
policies/{safe_uid}.yaml
bins/{safe_uid}.bin
compile_logs/{safe_uid}.stderr
compile_logs/{safe_uid}.stdout
```

`results.jsonl` must contain exactly one JSON object per input directive.
Required fields:

```text
uid
repo
repo_dir
statement_id
enforceability
status                  # compiled | failed
final_reason            # compiled or a short failure category
attempts
retry_count
nl_tokens
dsl_tokens
dsl_chars
binary_size
compression_ratio_dsl_over_nl
policy_path
binary_path
policy_yaml
attempt_records
```

## Policy Format

Every generated policy must be complete YAML:

```yaml
version: 1
policy: |
  source AGENT = exec "**"

  rule short-name:
    notify exec "git" "commit" if AGENT
    because "short corrective feedback"
```

Use compact policies. Translate the strongest syscall-observable part of the
directive. Partial translation is acceptable when the directive contains
non-OS-observable text; keep the translated policy focused and put the
unobservable remainder in the `because` text if needed.

Common constructs:

```text
notify|block|kill exec "cmd" "arg" if AGENT
notify|block|kill write file "path/**" if AGENT
notify|block|kill connect endpoint "*" if AGENT
unless lineage-includes exec "tool"
unless after exec "tool" since write "path/**"
unless target "allowed/path/**"
```

Effect choice:

```text
notify: soft guidance, "should", checklist reminder
block: hard "must", "do not", "not allowed"
kill: catastrophic or explicitly forbidden execution
```

## Compile Loop

For each directive:

1. Write a candidate policy to `policies/{safe_uid}.attemptN.yaml`.
2. Compile:

```bash
target/release/actplane --policy policies/{safe_uid}.attemptN.yaml compile --out bins/{safe_uid}.attemptN.bin
```

3. If it fails, revise and retry up to 3 attempts.
4. On success, copy/write the final policy to `policies/{safe_uid}.yaml` and
   final binary to `bins/{safe_uid}.bin`.

Token counting:

```python
import re
len(re.findall(r"\w+|[^\w\s]", text))
```

`binary_size` is the final `.bin` file size in bytes.

## Final Response

Do not paste all policies in chat. Report only:

```text
batch path
input count
compiled count
failed count
retry count
paths written
```

