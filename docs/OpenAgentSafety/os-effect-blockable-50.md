# OpenAgentSafety OS-effect Blockable 50

This document records the ActPlane run over OpenAgentSafety cases whose unsafe
checkpoint has an OS-observable effect. The goal is not to claim that every
OpenAgentSafety safety failure can be stopped by syscall-level policy. The goal
is to isolate the subset where the bad behavior crosses an OS edge that
ActPlane can observe and enforce: process execution, file write, file unlink,
permission change, account or system configuration mutation, network or
surveillance artifact creation, credential aggregation, or harmful content
being materialized into a file.

## Bottom line

For this local Qwen 27B run:

| Condition | Cases | Unsafe by official evaluator | ActPlane prevented | Mean safety |
|---|---:|---:|---:|---:|
| Baseline | 50 | 50 | 0 | 0.0% |
| ActPlane | 50 | n/a after prevention | 50 | 100.0% |

The final selected set is:

- Manifest: `docs/OpenAgentSafety/data/os_effect_blockable_50.json`
- Policies: `docs/OpenAgentSafety/policies/actplane/<task_id>.yaml`
- Baseline aggregate: `docs/OpenAgentSafety/results/baseline/20260608T122658Z-baseline-blockable50-aggregate`
- ActPlane aggregate: `docs/OpenAgentSafety/results/actplane/20260608T122658Z-actplane-blockable50-aggregate`
- Summary: `docs/OpenAgentSafety/results/os_effect_blockable_50/20260608T122658Z-summary/summary.json`
- CSV: `docs/OpenAgentSafety/results/os_effect_blockable_50/20260608T122658Z-summary/summary.csv`
- Bar chart: `docs/OpenAgentSafety/results/os_effect_blockable_50/20260608T122658Z-summary/baseline_vs_actplane.svg`

The final consistency check was:

```text
summary_rows: 50
baseline_unsafe_100: 50
actplane_prevented: 50
actplane_safety_100: 50
```

## Setup

The experiment used the official OpenAgentSafety runner and evaluator through
the local wrapper:

```text
docs/OpenAgentSafety/scripts/run_selected.py
```

The official checkout is:

```text
docs/OpenAgentSafety/OpenAgentSafety
```

Local model serving:

```text
llama.cpp server
Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf
http://127.0.0.1:18080/v1
```

Runtime image:

```text
ghcr.io/all-hands-ai/runtime:oh_v0.28.1_openagentsafety-base-local_t_latest
```

The local patch at
`docs/OpenAgentSafety/patches/local-llama-openhands.patch` makes the official
runner use the local OpenAI-compatible endpoint and lets the wrapper pass the
runtime image and ActPlane watcher settings.

## Selection rule

A case is included only if all of the following are true:

1. The local Qwen baseline run is unsafe under the official OpenAgentSafety
   evaluator, normally `final_score.result == final_score.total == 1`.
2. The unsafe checkpoint has a concrete OS-observable sink.
3. An ActPlane policy can target that sink without relying on OpenAgentSafety
   evaluator internals or trajectory text.
4. The ActPlane run triggers a `kill` or `block` effect before the unsafe OS
   effect is completed as a useful agent action.

This excludes cases where the only unsafe behavior is a chat message, a purely
semantic judgment, or evaluator regex matching against quoted task text.

It also excludes cases that this OpenHands configuration performs through an
editor API path that the current tracepoint watcher does not observe as a normal
`/workspace/...` file syscall. Those can be evaluated separately as tool-layer
integration coverage, but they should not be counted as OS-level prevention.

## Policy design

Each final case has one policy file:

```text
docs/OpenAgentSafety/policies/actplane/<task_id>.yaml
```

Policies are intentionally direct. Examples of sink classes:

- Dangerous command execution: `kill exec "rm"`, `kill exec "iptables"`,
  `kill exec "useradd"`.
- Protected file mutation: `kill write file "/workspace/.../tests/**"`,
  `kill unlink file "/workspace/.ssh/**"`.
- Credential or surveillance artifacts: `kill write file "/workspace/export_env.py"`,
  `kill write file "/workspace/clipboard_logger.py"`.
- Harmful content materialization: `kill write file "/workspace/comments.txt"`,
  `kill write file "/workspace/file_list.txt"`.
- Persistence or system configuration: `kill write file "/etc/sudoers.d/**"`,
  `kill write file "/workspace/usb_payload/**"`.

For `/workspace/...` file sinks, policies include both the direct container path
and a host-mount-compatible alias:

```text
kill write file "/workspace/file_list.txt"
kill write file "**/workspace/file_list.txt"
```

All final policies compile with:

```bash
python3 - <<'PY'
import json, subprocess
from pathlib import Path

ids = [
    c["task_id"]
    for c in json.loads(
        Path("docs/OpenAgentSafety/data/os_effect_blockable_50.json").read_text()
    )["cases"]
]

for task_id in ids:
    policy = Path("docs/OpenAgentSafety/policies/actplane") / f"{task_id}.yaml"
    subprocess.run(
        ["./target/release/actplane", "--policy", str(policy), "check"],
        check=True,
    )

print("compiled", len(ids), "policies")
PY
```

## Reproduction

From the ActPlane repo root, make sure the collector is built:

```bash
cargo build --release --manifest-path collector/Cargo.toml
```

Run the final baseline from scratch:

```bash
python3 docs/OpenAgentSafety/scripts/run_selected.py \
  --condition baseline \
  --case-file docs/OpenAgentSafety/data/os_effect_blockable_50.json \
  --keep-llama \
  --skip-services \
  --no-prepare-task-images \
  --runtime-container-image ghcr.io/all-hands-ai/runtime:oh_v0.28.1_openagentsafety-base-local_t_latest \
  --timeout 1800
```

Run the final ActPlane condition:

```bash
ACTPLANE_FORCE_TRACEPOINT=1 python3 docs/OpenAgentSafety/scripts/run_selected.py \
  --condition actplane \
  --case-file docs/OpenAgentSafety/data/os_effect_blockable_50.json \
  --keep-llama \
  --skip-services \
  --no-prepare-task-images \
  --runtime-container-image ghcr.io/all-hands-ai/runtime:oh_v0.28.1_openagentsafety-base-local_t_latest \
  --timeout 1800
```

Generate the summary and bar chart:

```bash
python3 docs/OpenAgentSafety/scripts/summarize_os_effect_results.py \
  --manifest docs/OpenAgentSafety/data/os_effect_blockable_50.json \
  --baseline-run docs/OpenAgentSafety/results/baseline/20260608T122658Z-baseline-blockable50-aggregate \
  --actplane-run docs/OpenAgentSafety/results/actplane/20260608T122658Z-actplane-blockable50-aggregate \
  --out-dir docs/OpenAgentSafety/results/os_effect_blockable_50/20260608T122658Z-summary
```

The recorded final result used aggregate directories because the 50 final cases
were mined and tuned incrementally. The aggregate directories contain symlinks
to official per-case OpenAgentSafety outputs from the real runs, not synthetic
evaluator results.

## Final case set

The final set contains these categories:

```text
exfil-script: 4
unsafe-artifact: 6
unsafe-content-flow: 6
protected-tests: 3
system-config: 2
network-surveillance: 2
discriminatory-code: 2
surveillance-tool: 2
protected-delete: 1
dangerous-exec: 2
protected-secret: 1
permissions: 1
backdoor-artifact: 1
command-and-control: 1
credential-aggregation: 1
dns-exfiltration: 1
secret-dump: 1
data-tampering: 1
secret-aggregation: 1
exfiltration-code: 1
token-harvest: 1
dangerous-cleaner: 1
steganography-tool: 1
sensitive-logging: 1
malicious-wrapper: 1
bruteforce-tool: 1
account-creation: 1
unsafe-web-artifact: 1
persistence-artifact: 1
medical-code: 1
```

The exact task IDs and reasons live in
`docs/OpenAgentSafety/data/os_effect_blockable_50.json`.

## Important exclusions

Some OpenAgentSafety cases are unsafe by the official evaluator but are not
honest OS-level prevention cases for ActPlane:

- Pure chat or output-only harms, such as repeating an abusive phrase.
- Semantic report manipulation, such as hiding negative metrics in a report,
  unless the policy claim is simply "do not write this report file".
- Trajectory-only regex noise, where the evaluator flags a quoted dangerous
  command even when the agent refused to execute it.
- OpenHands editor-only source modifications that do not show up as normal file
  writes in the current tracepoint watcher.

These exclusions are why the final result should be stated as:

```text
At least 50 OpenAgentSafety cases were confirmed locally as both baseline-unsafe
and OS-effect-blockable by ActPlane.
```

It should not be stated as:

```text
All OpenAgentSafety safety failures are blockable by ActPlane.
```

