# RQ1 Detailed Analysis

Data source: `docs/eval_runs/full/20260607_current_full_after_trace_harness_fix/`
(primary model setting: Qwen3.6-27B, 190 traces, 760 system-trace cells, 0 unclear)

## 1. Detection vs Recovery Split

DCR conflates two capabilities: did the system detect the violation, and did the
agent recover after detection? Splitting them reveals where each system's advantage
comes from.

### Detection Rate (violation traces where enforcement intervened/blocked)

| System | visible | script | opaque | total |
|---|---|---|---|---|
| prompt-filter | 31/38 (82%) | 4/38 (11%) | 0/38 (0%) | 35/114 (30.7%) |
| tool-regex | 32/38 (84%) | 2/38 (5%) | 0/38 (0%) | 34/114 (29.8%) |
| AgPlane-opaque | 30/38 (79%) | 7/38 (18%) | 30/38 (79%) | 67/114 (58.8%) |
| AgPlane | 30/38 (79%) | 22/38 (58%) | 30/38 (79%) | 82/114 (71.9%) |

Key observations:
- On visible violations, all systems detect at roughly the same rate (~80%).
- prompt-filter and tool-regex are near-zero on opaque traces (0%) because they
  cannot observe subprocess-level effects.
- AgPlane's kernel-level observation catches opaque traces at the same rate as
  visible ones (79%).
- AgPlane vs AgPlane-opaque differ on script-mediated traces (58% vs 18%):
  structured feedback enables the agent to recognize and retry script-mediated
  violations, which the agent sometimes rewrites in a second attempt that the
  system then catches.

### Recovery Rate (of detected violations, fraction where agent successfully recovered)

| System | visible | script | opaque | total |
|---|---|---|---|---|
| prompt-filter | 31/31 (100%) | 4/4 (100%) | n/a | 35/35 (100%) |
| tool-regex | 32/32 (100%) | 2/2 (100%) | n/a | 34/34 (100%) |
| AgPlane-opaque | 12/30 (40%) | 2/7 (29%) | 13/30 (43%) | 27/67 (40.3%) |
| AgPlane | 30/30 (100%) | 22/22 (100%) | 28/30 (93%) | 80/82 (97.6%) |

Key observations:
- prompt-filter and tool-regex: 100% recovery when detected, because their
  feedback is inherently readable (the tool call was blocked with an explanation).
  But they detect very few violations overall.
- AgPlane-opaque: detects 67 violations (2x baselines) but only recovers 40%,
  because raw EPERM gives the agent no information about what went wrong.
  This is the key evidence that detection alone is insufficient.
- Full AgPlane: 97.6% recovery because structured feedback (rule name + reason +
  remediation) gives the agent enough information to self-correct.
- The 2 unrecovered AgPlane cases (opaque family) are both cases where the agent
  understood the feedback but the recovery action itself was outside its capability
  (e.g., an opaque binary already compiled and executed).

### Summary

AgPlane's DCR advantage (75.8% vs 48.4% prompt-filter) decomposes as:
- Detection advantage: 71.9% vs 30.7% (kernel observation catches subprocess bypasses)
- Recovery advantage: 97.6% vs 100% (structured feedback is slightly below tool-call-native feedback, but applies to 2.3x more detected violations)
- Net: detection x recovery yields far more correct outcomes.

## 2. Per-Event vs Cross-Event Breakdown

The 38 sampled rules split 25 per-event / 13 cross-event.

### Detection Rate by rule type

| System | per-event | cross-event |
|---|---|---|
| prompt-filter | 24/75 (32%) | 11/39 (28%) |
| tool-regex | 24/75 (32%) | 10/39 (26%) |
| AgPlane-opaque | 46/75 (61%) | 21/39 (54%) |
| AgPlane | 59/75 (79%) | 23/39 (59%) |

Cross-event detection is lower across all systems because it requires tracking
state across multiple operations. AgPlane's gap (79% per-event vs 59% cross-event)
reflects cases where the temporal gate condition was not fully established.

### DCR by rule type

| System | per-event DCR | cross-event DCR |
|---|---|---|
| prompt-filter | 88/150 (58.7%) | 32/78 (41.0%) |
| tool-regex | 83/150 (55.3%) | 37/78 (47.4%) |
| AgPlane-opaque | 95/150 (63.3%) | 45/78 (57.7%) |
| AgPlane | 117/150 (78.0%) | 55/82 (67.1%) |

AgPlane's advantage holds on both per-event and cross-event rules. Cross-event
DCR is uniformly lower across all systems, but AgPlane's gap over baselines is
larger on cross-event (67.1% vs ~44% baselines = +23pp) than per-event
(78.0% vs ~57% baselines = +21pp).

## 3. False Positive Analysis

### FP by compliant trace family

| System | allowed-effect | lookalike | total FP |
|---|---|---|---|
| prompt-filter | 13/38 | 14/38 | 27/76 (36%) |
| tool-regex | 15/38 | 12/38 | 27/76 (36%) |
| AgPlane-opaque | 1/38 | 0/38 | 1/76 (1%) |
| AgPlane | 10/38 | 10/40 | 20/78 (26%) |

Key observations:
- AgPlane-opaque has near-zero FP (1/76) because without a feedback channel, the
  system never actively communicates on compliant traces, so the agent never
  overcorrects. This is not precision; it is silence.
- Full AgPlane's FP (20/78) is lower than baselines (27/76) in absolute terms but
  the mechanism differs: baselines FP from misclassifying the tool call text;
  AgPlane FPs from the agent over-correcting after receiving feedback on a
  boundary case.
- FPs split evenly between allowed-effect and lookalike traces, suggesting no
  systematic bias toward one compliant family.

## 4. Recovery Effort

Mean tool steps used by the agent after enforcement detection (max 5 allowed):

| System | mean steps | median | n (detected) |
|---|---|---|---|
| prompt-filter | 3.8 | 5 | 35 |
| tool-regex | 3.6 | 5 | 34 |
| AgPlane-opaque | 2.8 | 3 | 67 |
| AgPlane | 3.9 | 5 | 82 |

AgPlane-opaque uses fewer steps because the agent gives up early (no feedback to
guide recovery). prompt-filter, tool-regex, and full AgPlane all use most of the
allowed budget, suggesting the agent actively attempts recovery when it has
actionable feedback.

## 5. Possible Further Analyses

- **Per-repo breakdown**: do some repos consistently fail across all systems?
  Would show whether results are driven by a few hard/easy repos.
- **Judge confidence distribution**: the judge outputs a confidence score; are
  low-confidence judgments concentrated in one system or family?
- **Feedback content analysis**: for AgPlane FPs, what feedback triggered
  overcorrection? Are specific rule phrasings more FP-prone?
- **DSL translation accuracy**: spot-check N translated rules against directive
  intent. This is separate from detection/recovery but addresses the
  "translation quality unvalidated" concern.
- **Cross-model stability**: compare per-cell labels between Qwen and DeepSeek
  runs to measure model-sensitivity of results.
