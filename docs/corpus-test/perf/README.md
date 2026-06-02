# ActPlane Performance Benchmarks

This directory contains the RQ2 performance harness. It is intentionally separate
from the RQ1 corpus statement directories so benchmark inputs, generated
policies, raw samples, and summaries do not change the compliance dataset.

## What It Measures

`syscall_microbench.c` measures per-operation latency for:

- `open`: `open(path, O_RDONLY|O_CLOEXEC)`, with `close` outside the timed region
- `write`: `write(fd, 4096B)` to an already-open temp file
- `connect`: UDP `connect(127.0.0.1:9)` on an already-created socket
- `fork`: `fork()` plus parent `waitpid()`
- `exec`: `fork()` plus child `execve("/bin/true")` plus parent `waitpid()`

The `fork` and `exec` measurements include scheduler and wait overhead. The
paper should report them exactly that way; ActPlane overhead is the paired
difference against the same benchmark without ActPlane.

`run_perf.py` builds the C benchmark, generates no-hit ActPlane policies for
`AP-1`, `AP-10`, `AP-32`, and `AP-100`, runs repeated trials, and writes raw
run records plus aggregate CSV/JSON files.

`run_macro.py` runs macro/end-to-end workloads with the same no-hit policy
families: fixed-op `stress-ng` workloads plus real repository build/test
commands wrapped with `/usr/bin/time -v`.

## Recommended Paper Run

Run this on an otherwise idle machine, pin to an isolated CPU, keep the CPU
governor fixed, and preserve raw results:

```bash
python3 docs/corpus-test/perf/run_perf.py \
  --build-actplane \
  --configs baseline,ap-1,ap-10,ap-32,ap-100 \
  --ops open,write,connect,fork,exec \
  --repeats 7 \
  --cpu 2 \
  --raw-samples
```

For a quick local sanity check without eBPF privileges:

```bash
python3 docs/corpus-test/perf/run_perf.py --smoke --baseline-only
```

For macro workloads:

```bash
python3 docs/corpus-test/perf/run_macro.py \
  --configs baseline,ap-32,ap-100 \
  --workloads stressng-open,stressng-fork,stressng-exec,stressng-hdd,stressng-mixed,collector-release-build \
  --repeats 3
```

## Output

Each run creates `docs/corpus-test/perf/results/<timestamp>/` with:

- `metadata.json`: hardware, kernel, git revision, active LSMs, command line
- `policies/*.yaml`: exact generated policies used for AP configurations
- `runs.jsonl`: one record per config/op/repeat
- `runs.csv`: flattened per-run statistics
- `aggregate.csv` and `aggregate.json`: median statistics across repeats and
  overhead relative to the median baseline for the same operation
- `raw/*.csv`: optional per-iteration samples when `--raw-samples` is used
- `logs/*.stdout` / `logs/*.stderr`: command output for auditability

## OSDI-Style Reporting Notes

- Report machine, kernel, LSM state, CPU governor, CPU pinning, and ActPlane git
  revision from `metadata.json`.
- Report median across repeated trials, not a single run.
- Include p50, p99, and p999 per-operation latency. Keep raw samples for artifact
  review and bootstrap confidence intervals.
- Use no-hit policies for the primary overhead table. That isolates steady-state
  rule-scanning and label propagation from ring-buffer/reporting cost.
- Treat violation/reporting latency as a separate experiment if needed; it
  exercises a different path (ring buffer + userspace feedback formatting).
