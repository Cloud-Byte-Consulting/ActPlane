# Official Score Improvement Attempts

Date: 2026-06-04

## Question

Can we keep the official OctoBench score path and tune policy/feedback so that
ActPlane gets a clearly higher `avg_reward`?

## Trace-Level Finding

The main bottleneck is not ActPlane blocking. Low-scoring trajectories often end
while the model is still exploring files, before any `Write`/`Edit` or test run.

For `md-course-builder-code-style`, fixed-policy `actplane-feedback` repeats had
large variance:

```text
0.559, 0.588, 0.971
```

Under the same policy, the difference between low and high scores was mostly
whether the local model entered implementation. The low-score traces had only
`Glob`/`Grep`/`Read`; the high single run reached `Write`.

## Tool-Regex Clarification

The `tool-regex` condition did not win because its hook blocked actions. In the
three-case run, every `tool_regex_events.jsonl` file was empty.

So the higher `tool-regex` aggregate in that run reflects a better model
trajectory sample, not successful regex blocking.

## Tried: Append-System Guidance

Condition:

```text
actplane-feedback-guided
```

Change:

```text
claude ... --append-system-prompt "<benchmark completion guidance>"
```

Course-builder result:

```text
reward = 0.588
ActPlane events = 0
```

Trace:

- no `TodoWrite`
- no `Task`
- no `Write`/`Edit`
- ended after `Glob`/`Grep`/`Read`

Conclusion: appending guidance did not fix the local model's tendency to stop in
exploration.

## Tried: User-Prompt Prefix Guidance

Condition:

```text
actplane-feedback-task-guided
```

Change:

The same completion guidance was prepended to the user query. The guidance is
present in both raw and converted trajectories.

Course-builder result:

```text
reward = 0.588
ActPlane events = 0
```

Trace:

- guidance was present
- model still used only `Glob`/`Grep`/`Read`
- no `TodoWrite`
- no `Write`/`Edit`

Conclusion: making the guidance user-visible also did not reliably improve
official score.

## Why This Did Not Improve

The local Qwen3 27B GGUF backend is the dominant bottleneck for official
OctoBench score in these cases. It often produces plausible exploration tool
calls but does not reliably continue to implementation and tests.

ActPlane feedback can reduce harmful hard-kill regressions and provide OS-level
evidence, but it does not make the model more capable at completing a full
software-engineering task.

## Practical Next Steps

The most likely ways to improve official score are:

1. Use a stronger tool-use coding model for the scaffold.
2. Run more repeats and report mean/variance instead of single-run wins.
3. Choose an ActPlane-oriented subset with shorter implementation burden and
   clear OS-observable constraints.
4. Add the separate OS-effect reward extension rather than relying only on
   official trajectory reward.

Prompt/scaffold guidance alone is not enough in the current local-model setup.
