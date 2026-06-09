# Failure-Conditioned Policy Revision Experiment

## Claim Under Test

The paper draft has the placeholder claim:

> Agents can learn from failure: single Agent translation pass detects 71.9%, revision fixes it to xx%.

The defensible version supported by this artifact is narrower:

> On the 28 ActPlane false negatives from the fixed RQ1 run, one failure-conditioned policy revision pass recovered 26 cases, a strict lower bound of 92.9%. All 26 complete reruns produced visible ActPlane interventions.

This should be reported as an FN-slice repair experiment, not as a replacement
for the main full-corpus Decision Compliance Rate. The experiment does not
measure whether the relaxed policies introduce new false positives on benign
traces.

## Experimental Design

The design follows the shape expected for a systems or ML conference artifact:

1. Fixed baseline artifact.
   The FN set is extracted from the existing 190-trace RQ1 run, not selected by
   hand after revision.

2. Fixed input to the reviser.
   For each false negative, the reviser receives the original policy, the trace
   snapshot, fixture snapshot, runner facts, ActPlane feedback fields, and the
   trajectory judge's FN rationale.

3. No in-place corpus mutation.
   Revised policies are written under a separate override root:

   `docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/policies`

4. FN-only rerun.
   The rerun uses the paper entrypoint with an explicit trace list:

   `docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/fn_trace_list.json`

5. Conservative reporting.
   Cases without complete runner JSON are counted against the recovery rate,
   even when stderr shows ActPlane attached and delivered feedback.

6. Clean kernel state check.
   A post-run `bpftool` check found no ActPlane or taint-related BPF programs,
   links, or pins remaining. System BPF programs unrelated to ActPlane were not
   removed.

## Baseline And Revision Artifacts

Baseline selected runner list:

`docs/eval_runs/full/deepseek_rq1_20260607T193612Z_v4_pro/selected_runner_results.txt`

Baseline judge directory:

`trajectory_judges_deepseek_deepseek_v4_pro_guardrail_response`

Extracted FN cases:

- 28 ActPlane FN traces.
- 14 unique `repo + statement_id` policy groups.

Revision model:

- llama.cpp OpenAI-compatible server.
- Model ID: `Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M`.

Revision outputs:

- `manifest.json`: case list, policy paths, compile status, and rationale.
- `prompts/`: exact prompts given to the translation agent.
- `responses/`: raw and parsed model responses.
- `policies/`: revised `rule.yaml` files.
- `compile_logs/`: `actplane check` output.

## Procedure

Policy revision command:

```bash
python3 -u docs/eval_scripts/revise_rq1_fn_policies.py \
  --out-dir docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped
```

Deterministic supplement command:

```bash
python3 docs/eval_scripts/supplement_rq1_fn_policies.py \
  --revision-dir docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped
```

FN-only rerun command:

```bash
ACTPLANE_RULE_OVERRIDE_ROOT=/home/yunwei37/workspace/ActPlane/docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/policies \
python3 docs/eval_scripts/run_eval.py \
  --config actplane-only \
  --trace-list docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/fn_trace_list.json \
  --out-dir docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/rerun_actplane_only_v2
```

## Result

Current verified state:

| Quantity | Count |
|---|---:|
| Baseline ActPlane FN traces | 28 |
| Revised policy groups | 14 |
| Revised policies passing `actplane check` | 14 |
| Latest unique rerun keys | 28 |
| Complete runner results | 26 |
| Complete results with `setup_fired=true` | 26 |
| Complete results with visible setup intervention | 26 |
| Incomplete runner results | 2 |

Strict lower-bound recovery:

```text
26 / 28 = 92.9%
```

Conditional intervention rate among complete reruns:

```text
26 / 26 = 100.0%
```

## Incomplete Cases

The two incomplete cases are both from `ruvnet/ruflo#29`:

- `trace_opaque_fixture_violation.jsonl`
- `trace_script_visible_violation.jsonl`

Latest failure mode:

```text
actplane run failed (rc=137)
ActPlane: running pid ... under COMMAND label 0x1; feedback ...
```

Interpretation:

The revised policy catches these traces with a direct `kill exec "bash"` style
clause. That is a real ActPlane intervention, but it can kill the monitored
inner runner before `agent_sdk_eval.py` prints the JSON sentinel. The paper
entrypoint then treats the case as incomplete rather than scorable. Counting
both as failures gives the strict 92.9% lower bound above.

## Why This Is Acceptable Evidence

The experiment is useful because it tests a concrete repair loop on the exact
known misses from the fixed RQ1 run. The repair input is auditable, the revised
policies are stored separately, and the rerun scope is explicit.

The result should be presented carefully:

- Valid claim: failure-conditioned revision recovers at least 92.9% of the
  original ActPlane FN slice.
- Valid claim: every complete rerun showed visible ActPlane intervention.
- Invalid claim from this artifact alone: full-corpus DCR improves to 92.9%.
- Invalid claim from this artifact alone: false positives are unchanged.

## Recommended Paper Wording

Use language like:

> To test whether policy failures are repairable, we took the 28 ActPlane false
> negatives from the fixed RQ1 run and gave a local translation agent each
> failing trace, the original DSL rule, and the judge's feedback. The revised
> policies compiled for all 14 affected statements. Rerunning only the original
> FN traces, 26 of 28 produced complete runner results with visible ActPlane
> interventions, a strict recovery lower bound of 92.9%. The remaining two cases
> triggered ActPlane but killed the runner before it emitted the result sentinel,
> so we count them as unrecovered. This is an FN-slice repair study rather than a
> full DCR rerun, so it does not measure the false-positive cost of the relaxed
> rules.

## Next Step For A Full Paper Claim

For a stronger OSDI or NeurIPS claim, run the revised policies on the full
190-trace corpus with the same source model and judge. That would allow reporting
both the recovered FN rate and the false-positive cost introduced by revision.
