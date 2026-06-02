# ActPlane Performance Evaluation Notes

Date: 2026-06-02

This document records the full performance run executed on the current machine,
plus an optimization analysis based on the observed overhead. It covers both
per-syscall microbenchmarks and macro/end-to-end workloads.

## Executive Summary

The current ActPlane tracepoint-mode overhead is acceptable for mixed real
workloads but visible on syscall-dense open/write paths.

- Microbench AP-100 overhead:
  - `open`: +4.56 us p50, +4.95 us p99.
  - `connect`: +1.36 us p50, +1.52 us p99.
  - `write`: +0.72 us p50, +1.18 us p99. The percentage is large because the
    baseline write path is only 0.326 us p50.
  - `fork`: noisy; p50 +2.68 us at AP-100, p99 lower than baseline in this run.
  - `exec`: +27.85 us p50, +37.64 us p99 at AP-100.
- Macro overhead:
  - `stress-ng --open`: +25.7% at AP-32, +39.5% at AP-100.
  - `stress-ng --mixed`: +0.2% at AP-32, +1.7% at AP-100.
  - cold `cargo build --release` of the collector: no meaningful wall-clock
    overhead in this run (-0.5% AP-32, +0.1% AP-100).

The largest optimization opportunity is to separate **subject/capability labels**
such as `COMMAND`/`AGENT` from **data-flow labels** such as `SECRET`/`UNTRUST`.
Today `COMMAND` propagates on every write, so write-heavy workloads pay file map
updates and provenance copies even when the policy only needs `COMMAND` as a
process-scoped guard. A compiler-provided `flow_mask` could avoid that without
weakening secret/untrusted-data IFC.

## Environment

Result directories:

- Micro: `docs/corpus-test/perf/results/2026-06-02T080107Z`
- Macro: `docs/corpus-test/perf/results/macro-2026-06-02T081334Z`

Machine:

- CPU: Intel Core Ultra 9 285K, 24 cores, 1 socket.
- Kernel: Linux 6.15.11-061511-generic.
- CPU governor: `performance`.
- Microbench CPU pinning: CPU 2.
- ActPlane: `collector/target/release/actplane`, version 0.1.5.
- stress-ng: 0.17.06.
- Git revision: `cce6540fb2e0485ae546f3b5f60b4d2e5d8fa89c`, dirty tree.

Important limitation:

`/sys/kernel/security/lsm` is:

```text
lockdown,capability,landlock,yama,apparmor,ima,evm
```

There is no `bpf` LSM in the active list. These results are therefore
tracepoint-mode / harness-mode overhead results, not final BPF-LSM pre-operation
enforcement results. For the paper, rerun on a kernel booted with `bpf` in the
active LSM list.

`perf` was not usable on this kernel because the matching `linux-tools` package
is missing:

```text
perf not found for kernel 6.15.11-061511
```

The run therefore uses raw latency samples, `/usr/bin/time -v`, and stress-ng
metrics, but no hardware/perf counter table.

## Methodology

### Microbenchmarks

Command:

```bash
python3 docs/corpus-test/perf/run_perf.py \
  --build-actplane \
  --configs baseline,ap-1,ap-10,ap-32,ap-100 \
  --ops open,write,connect,fork,exec \
  --repeats 7 \
  --cpu 2 \
  --raw-samples
```

The benchmark generated no-hit policies for AP-1/AP-10/AP-32/AP-100. This
isolates steady-state policy scanning and label propagation from violation
reporting cost. Raw samples were saved under the result directory; the full
result directory is about 193 MB.

Measured operations:

- `open`: `open(path, O_RDONLY|O_CLOEXEC)`.
- `write`: `write(fd, 4096B)` to an already-open temp file.
- `connect`: UDP `connect(127.0.0.1:9)`.
- `fork`: `fork()` plus parent `waitpid()`.
- `exec`: `fork()` plus child `execve("/bin/true")` plus parent `waitpid()`.

### Macro / End-to-End Workloads

Command:

```bash
python3 docs/corpus-test/perf/run_macro.py \
  --configs baseline,ap-32,ap-100 \
  --workloads stressng-open,stressng-fork,stressng-exec,stressng-hdd,stressng-mixed,collector-release-build \
  --repeats 3 \
  --timeout-s 3600
```

Workloads:

- `stressng-open`: 4 open workers, 400k open/close bogo ops.
- `stressng-fork`: 4 fork workers, 50k fork bogo ops.
- `stressng-exec`: 4 exec workers, 10k exec bogo ops.
- `stressng-hdd`: 4 hdd workers, 12k hdd bogo ops, 128 MB per worker.
- `stressng-mixed`: open/fork/exec/hdd/cpu combined fixed-op workload.
- `collector-release-build`: cold `cargo build --release` of the ActPlane
  collector, with a distinct `CARGO_TARGET_DIR` for every config/repeat.

The macro result directory is about 3.1 GB because cold Cargo build artifacts
are preserved for auditability.

## Micro Results

Median across 7 repeats. Times are microseconds.

| op | config | p50 | p99 | p999 | p50 overhead | p99 overhead |
|---|---:|---:|---:|---:|---:|---:|
| open | baseline | 8.875 | 10.186 | 11.332 | +0.0% | +0.0% |
| open | ap-1 | 9.510 | 10.919 | 12.492 | +7.2% | +7.2% |
| open | ap-10 | 9.906 | 11.478 | 13.075 | +11.6% | +12.7% |
| open | ap-32 | 11.190 | 12.815 | 14.164 | +26.1% | +25.8% |
| open | ap-100 | 13.436 | 15.136 | 17.025 | +51.4% | +48.6% |
| write | baseline | 0.326 | 0.377 | 0.522 | +0.0% | +0.0% |
| write | ap-1 | 1.036 | 1.551 | 1.963 | +217.8% | +311.4% |
| write | ap-10 | 0.779 | 1.569 | 1.935 | +139.0% | +316.2% |
| write | ap-32 | 0.717 | 1.558 | 1.868 | +119.9% | +313.3% |
| write | ap-100 | 1.045 | 1.556 | 1.987 | +220.6% | +312.7% |
| connect | baseline | 1.991 | 2.533 | 4.286 | +0.0% | +0.0% |
| connect | ap-1 | 1.949 | 2.477 | 4.324 | -2.1% | -2.2% |
| connect | ap-10 | 2.333 | 2.930 | 4.623 | +17.2% | +15.7% |
| connect | ap-32 | 2.708 | 3.313 | 5.012 | +36.0% | +30.8% |
| connect | ap-100 | 3.346 | 4.052 | 5.884 | +68.1% | +60.0% |
| fork | baseline | 68.448 | 287.459 | 607.328 | +0.0% | +0.0% |
| fork | ap-1 | 71.287 | 180.149 | 463.404 | +4.1% | -37.3% |
| fork | ap-10 | 70.014 | 251.041 | 510.199 | +2.3% | -12.7% |
| fork | ap-32 | 65.387 | 148.256 | 197.400 | -4.5% | -48.4% |
| fork | ap-100 | 71.131 | 168.339 | 293.444 | +3.9% | -41.4% |
| exec | baseline | 297.240 | 477.555 | 580.070 | +0.0% | +0.0% |
| exec | ap-1 | 318.096 | 526.911 | 662.283 | +7.0% | +10.3% |
| exec | ap-10 | 314.936 | 501.422 | 571.980 | +6.0% | +5.0% |
| exec | ap-32 | 313.867 | 482.113 | 575.159 | +5.6% | +1.0% |
| exec | ap-100 | 325.093 | 515.193 | 630.119 | +9.4% | +7.9% |

Observations:

- `open` and `connect` scale with rule count, as expected from per-event
  no-hit rule/update scans.
- `write` has small absolute overhead but very large relative overhead because
  the baseline is sub-microsecond. This path is likely dominated by label-flow
  and provenance map work, not only rule matching.
- `fork` tail numbers are noisy and should not be over-interpreted. p50 overhead
  is small. The negative p99 overhead means scheduler variance dominated the
  tail in this run.
- `exec` p50 overhead stays under 10% even at AP-100.

## Macro Results

Median across 3 repeats. Elapsed time is seconds.

| workload | config | elapsed | overhead | user | sys | stress ops |
|---|---:|---:|---:|---:|---:|---:|
| collector-release-build | baseline | 15.330 | +0.0% | 147.93 | 10.03 | 0 |
| collector-release-build | ap-32 | 15.250 | -0.5% | 147.31 | 10.17 | 0 |
| collector-release-build | ap-100 | 15.350 | +0.1% | 146.43 | 10.07 | 0 |
| stressng-exec | baseline | 3.180 | +0.0% | 18.33 | 33.60 | 16384 |
| stressng-exec | ap-32 | 3.200 | +0.6% | 18.57 | 34.80 | 16384 |
| stressng-exec | ap-100 | 3.180 | +0.0% | 18.71 | 35.62 | 16384 |
| stressng-fork | baseline | 4.650 | +0.0% | 7.91 | 10.49 | 50000 |
| stressng-fork | ap-32 | 4.740 | +1.9% | 8.03 | 10.61 | 50000 |
| stressng-fork | ap-100 | 4.990 | +7.3% | 8.06 | 11.33 | 50000 |
| stressng-hdd | baseline | 0.370 | +0.0% | 0.34 | 0.45 | 12000 |
| stressng-hdd | ap-32 | 0.380 | +2.7% | 0.38 | 0.45 | 12000 |
| stressng-hdd | ap-100 | 0.380 | +2.7% | 0.34 | 0.46 | 12000 |
| stressng-mixed | baseline | 13.220 | +0.0% | 63.38 | 26.60 | 334192 |
| stressng-mixed | ap-32 | 13.250 | +0.2% | 63.74 | 28.67 | 334192 |
| stressng-mixed | ap-100 | 13.450 | +1.7% | 63.91 | 31.32 | 334192 |
| stressng-open | baseline | 3.040 | +0.0% | 0.35 | 9.85 | 400000 |
| stressng-open | ap-32 | 3.820 | +25.7% | 0.36 | 12.49 | 400000 |
| stressng-open | ap-100 | 4.240 | +39.5% | 0.35 | 14.79 | 400000 |

Observations:

- `stressng-open` is the worst macro case. It matches the micro result: open is
  rule-count-sensitive and system-time-heavy.
- `stressng-mixed` is low overhead despite including open/fork/exec/hdd/cpu:
  AP-100 adds 0.23 s median elapsed on a 13.22 s baseline.
- The real cold Cargo build is effectively unchanged. It is CPU-heavy and
  parallel; ActPlane's per-syscall overhead is amortized.
- stress-ng reported that `/proc/sys/kernel/sched_autogroup_enabled` is 1. For
  final paper runs, record this value and consider disabling it if the platform
  policy allows.

## Does This Meet OSDI-Style Expectations?

This is a credible artifact run for internal analysis, but not yet final-paper
quality. It has several good properties:

- Raw per-iteration micro samples are preserved.
- Repeated runs are aggregated by median.
- p50/p99/p999 are reported.
- CPU governor and environment metadata are recorded.
- stress-ng fixed-op workloads are used, not only wall-clock toy scripts.
- A real cold build workload is included.

Remaining gaps before an OSDI submission:

1. **Enable BPF LSM and rerun.** Current results are tracepoint-mode because
   `bpf` is absent from active LSMs.
2. **Install matching `perf` tools.** Add `perf stat` counters for cycles,
   instructions, context switches, migrations, page faults, and possibly
   BPF-related counters where available.
3. **Randomize macro run order.** The current macro runner runs baseline then
   AP-32 then AP-100 for each workload. The cold Cargo target is isolated per
   run, but page cache, temperature, and background load can still bias ordered
   runs.
4. **Increase macro repeats to 5 or 7.** Three repeats are enough for a first
   signal, not enough for a final systems paper table.
5. **Report confidence intervals.** Use bootstrap CIs over repeats and raw
   micro samples.
6. **Add violation/reporting latency separately.** The no-hit policy isolates
   steady-state overhead. Reporting cost should be measured as a distinct path:
   ring buffer event, userspace formatting, feedback file write, and hook read.
7. **Add one agent-session trace replay macro.** The stress-ng and cargo build
   workloads are strong OS/application macrobenchmarks. For the paper's agent
   framing, add deterministic replay of recorded agent traces under baseline vs
   AP-32/AP-100.

## Optimization Analysis

### 1. Separate Subject Labels From Data-Flow Labels

Current behavior: the runner seeds `COMMAND` on the root process. Because labels
are unified, `COMMAND` is included in `te_labels(pid)` and then propagated to
files in `te_write_flow`. That means every write by the agent can update `ts_file`
and provenance maps even when `COMMAND` is only used as a subject guard.

Relevant path:

- `bpf/taint_engine.bpf.h`: `te_write_flow` collects write updates, reads
  `te_labels(pid)`, updates `ts_file`, and copies provenance when `pl != 0`.
- `bpf/process.bpf.c`: `trace_write` feeds fd writes through channel handling.

Optimization:

- Add a compiler/kernel `flow_mask` or per-label class.
- Process-only labels (`COMMAND`, `AGENT`, capability markers) stay on process
  lineage but do not flow into files/endpoints by default.
- Data labels (`SECRET`, `UNTRUST`, downloaded content labels) still flow.

Expected impact:

- Large reduction on `write` and `stressng-hdd`.
- Less map churn and provenance copy work.
- Clearer DSL semantics: capability/context labels are not the same as
  information-origin labels.

Risk:

- Some policies may intentionally rely on "files written by the agent" carrying
  `COMMAND`. If that is needed, expose it explicitly, e.g. `source FLOW_AGENT =
  exec "..."` or `flow source`.

### 2. Partition Rules and Updates by Operation

Current behavior:

- `te_collect_updates` scans `ts_updates` via `bpf_loop(te_count(1), ...)`.
- `te_check_labels` scans `ts_rules` via `bpf_loop(te_count(0), ...)`.

Every event pays for a scan over the full active table, even if most rules are
for another operation.

Optimization:

- Lower rules into per-op contiguous ranges or separate maps/counts:
  `rules_exec`, `rules_open`, `rules_write`, `rules_connect`.
- Do the same for updates/sources/gates/invalidators.
- In the kernel, dispatch directly to the relevant range.

Expected impact:

- Reduces AP-100 open/connect slope.
- Helps real policies where only a few operations are used.

Risk:

- ABI change across `collector/src/dsl/lower.rs`, `bpf/taint.h`, and
  `bpf/src/lib.rs`.

### 3. Add an Early No-Policy Fast Path Per Operation

Current behavior:

- File handlers resolve paths and file IDs before knowing whether a given op has
  any relevant rules, updates, or invalidators.

Optimization:

- Compile bitsets like `has_rules_by_op`, `has_updates_by_op`,
  `needs_file_flow`, `needs_endpoint_flow`, `needs_provenance`.
- Return early before path resolution when the operation cannot affect policy
  state or trigger a rule.

Expected impact:

- Very useful for sparse real policies.
- Less useful for the AP-100 no-hit benchmark because it deliberately includes
  all operation classes.

### 4. Make Provenance Collection Lazy or Match-Scoped

Current behavior:

- Provenance maps are updated during propagation so feedback can explain the
  origin of a later violation.

Optimization:

- Add a mode or mask for labels that need provenance.
- For labels that are only capability guards, skip provenance entirely.
- Consider recording compact origin IDs instead of copying full targets on every
  propagation edge.

Expected impact:

- Reduces write/read propagation overhead.
- Reduces map pressure in long-running agent sessions.

Risk:

- Feedback quality can degrade if provenance is skipped for labels that later
  trigger user-facing violations.

### 5. Review `cap_drain_current` Placement

Current behavior:

- `cap_drain_current()` is called inside `te_handle_event`.
- There is also a `getpid` tracepoint drain tick.

Optimization:

- Measure whether every-event draining is necessary for hot reload/capability
  responsiveness.
- If not, drain on explicit tick, bounded interval, or pending flag only.

Expected impact:

- Small but broad overhead reduction across open/write/connect.

Risk:

- Reload/capability propagation latency may increase. This needs a correctness
  test for MCP/hot reload behavior.

### 6. Path Matching / Path Resolution Caches

Current behavior:

- File path matching requires path string resolution and per-rule string match.

Optimization ideas:

- For exact file rules, lower to path hash map entries where safe.
- Cache `(file_id -> last resolved path hash / labels)` for repeated writes.
- Keep glob/prefix rules in the existing string matcher.

Expected impact:

- Helps `open` and `stressng-open`.

Risk:

- Rename/hardlink semantics are subtle. The current inode-aware design should
  not regress into path-only false negatives.

## Recommended Next Experiments

1. Implement `flow_mask` / subject-label split first. It likely gives the best
   write-heavy improvement with the cleanest semantic story.
2. Rerun the full micro suite and macro suite after that change.
3. Then implement per-op rule/update partitioning and rerun AP-32/AP-100.
4. Enable BPF LSM and rerun the final paper table.
5. Add violation-path latency:

   ```text
   triggering syscall -> ringbuf emit -> userspace report -> feedback file fsync/read
   ```

6. Add deterministic agent trace replay macro workloads from `docs/corpus-test`
   so the evaluation includes an agent-shaped end-to-end path, not only
   stress-ng and build workloads.

## Bottom Line

For realistic mixed or build workloads, the current overhead looks deployable in
tracepoint mode: AP-100 adds 1.7% to stress-ng mixed and ~0% to a cold collector
release build. For syscall-dense open/write stress, overhead is measurable and
points to concrete kernel/compiler optimizations. The first optimization to
prioritize is label class separation so `COMMAND` does not flow through every
file write unless a policy explicitly asks for that behavior.
