# IFC / Provenance Evaluation Survey for ActPlane

Date: 2026-06-02

This note summarizes how nearby IFC, dynamic taint, whole-system provenance, and agent-IFC papers evaluate performance and security. It is based on local papers in `docs/reference/` and is intended to guide ActPlane's evaluation section.

## Short answer

Classic IFC/provenance systems do not usually use `stress-ng` as the main performance evidence. They normally use:

1. syscall or primitive-level microbenchmarks,
2. real system macrobenchmarks such as Linux kernel build, PostMark/file-server workloads, web/cache services, or domain applications,
3. effectiveness workloads such as malware, DARPA TC attack traces, or agent benchmark tasks,
4. storage, memory, CPU, throughput, and query latency when the system has a graph/query component.

For ActPlane, `stress-ng` is useful as a synthetic stress test, but it should be an appendix or stress-case panel. The main RQ2 performance figure should combine syscall overhead with real end-to-end workloads.

## What Prior IFC / Provenance Papers Do

| Paper | Main evaluation style | Performance workloads | Security / utility workloads | Takeaway for ActPlane |
| --- | --- | --- | --- | --- |
| TaintDroid, OSDI 2010 | Runtime taint tracking on Android | Java microbenchmark, IPC benchmark, phone UI macrobenchmarks | Third-party app privacy-leak study | Mix micro cost with user-visible app workflows; report confidence intervals and repeated trials. |
| Hi-Fi, ACSAC 2012 | Whole-system provenance via LSM | syscall microbenchmark, Linux kernel build, PostMark | Simulated malware behaviors and worm lifecycle | Use syscall micro plus kernel build and PostMark-style filesystem macro. |
| LPM, USENIX Security 2015 | Linux provenance modules and provenance-based access control | LMbench, kernel compile, PostMark, BLAST, iperf | PB-DLP provenance queries | Add graph/query cost and network throughput when relevant. |
| CamFlow, SoCC 2017 | Practical whole-system provenance capture | LMbench, kernel unpack/build, PostMark, Apache, Redis, memcache, PHP, pybench | Selective provenance capture and data-volume reduction | This is the closest performance template: LMbench plus standard system and cloud macrobenchmarks. |
| CamQuery, CCS 2018 | Runtime queries over live provenance | LMbench, kernel unpack/build, PostMark, query stacking | In-kernel and userspace provenance queries | Show overhead decomposition: capture baseline, policy/query cost, and scaling with active policies. |
| SLEUTH, USENIX Security 2017 | Real-time attack reconstruction from audit/provenance graphs | Runtime and memory for processing audit streams | DARPA TC red-team data, benign false-alarm data | For detection-style claims, use real attack traces and report memory, throughput, false positives. |
| UNICORN, NDSS 2020 | Streaming provenance anomaly detection | CPU, memory, graph edge processing rate under kernel compilation | StreamSpot, DARPA TC, simulated APT supply-chain data | For graph analytics, show whether processing keeps up with event arrival rate. |
| CaMeL / FIDES / AgentSpec | Agent-layer IFC or runtime enforcement | token/latency overhead or rule-check milliseconds | AgentDojo, prompt-injection attacks, task utility | For ActPlane's agent setting, include agent task completion and violation prevention, not only OS benchmarks. |

## Common Pattern

The common structure is:

1. **Microbenchmarks:** LMbench or custom syscall loops for `open`, `read`, `write`, `stat`, `fork`, `exec`, `connect`, IPC. These answer "what does one mediated edge cost?"
2. **Macrobenchmarks:** Linux/kernel build, archive unpack, PostMark/file-server workload, web server, Redis/memcache, database/scientific workload. These answer "does a real workload slow down?"
3. **Policy/query scaling:** number of active policies, number of queries, graph size, event rate, rule complexity. This answers "does the design scale?"
4. **Security/IFC effectiveness:** attack traces, malware simulations, privacy leaks, prompt-injection tasks, or real corpus-derived rules. These answer "does the mechanism catch or prevent the claimed class?"
5. **System resource cost:** CPU, memory, storage/log volume, event throughput, tail latency, dropped events. This is especially important for provenance systems.

## Where `stress-ng` Fits

`stress-ng` is not a microbenchmark in the strict sense because it runs synthetic workloads over many kernel subsystems. But it is also not a representative application macrobenchmark like kernel build, PostMark, Redis, or an agent trace replay.

Best classification:

- **Synthetic stress benchmark:** useful for robustness, worst-case syscall/event pressure, and regression testing.
- **Not enough as main macrobenchmark:** it does not represent an application-level outcome users care about.
- **Good appendix or secondary panel:** include it to show ActPlane does not collapse under pressure, but do not make it the only macro result.

## Recommended ActPlane Evaluation Shape

### RQ1: Expressiveness / Need

Use the corpus-derived policy taxonomy already in the repo:

- fraction of agent rules requiring OS-level descendants, file propagation, network propagation, or syscall-level enforcement,
- examples that tool-layer guards cannot reliably enforce,
- rule-language coverage over the corpus.

This should be a corpus/effectiveness figure, not a performance figure.

### RQ2: Performance

One figure can work, but it should be a composite figure with two data classes:

1. **Micro data:** syscall p50/p95/p99 overhead versus rule count and label state.
   - Suggested operations: `exec`, `open/read/write`, `connect`, `fork`.
   - Suggested configurations: baseline, monitor no-rules, 1 rule, 10 rules, 100 rules, match vs non-match.

2. **End-to-end macro data:** normalized elapsed time or throughput for real workloads.
   - Required: build workload, e.g. Linux kernel build or at least full ActPlane `make` plus collector `cargo test`.
   - Required: filesystem/server workload, e.g. PostMark, filebench, fio small-file profile, or a reproducible substitute.
   - Strongly recommended: service workload, e.g. NGINX/Apache, Redis, memcache, or a local HTTP benchmark.
   - ActPlane-specific: agent trace replay using corpus-derived rules and real tool chains.

`stress-ng` can be a third, smaller stress panel or appendix table.

### RQ3: Policy Effectiveness / Feedback

Use end-to-end agent scenarios:

- forbidden git branch/worktree style actions,
- network exfiltration after reading sensitive files,
- subprocess and direct syscall bypass attempts,
- file-derived taint propagation to later tools,
- corrective-feedback payload quality and recovery.

Metrics:

- blocked violations,
- bypass success rate,
- false positive rate on benign traces,
- recovery rate after feedback,
- user-visible failure mode.

### RQ4: Scalability / Robustness

Use rule count, label count, process count, file-label-map pressure, and event rate:

- event throughput under increasing rule count,
- memory/map occupancy,
- lost-event count if any output path is used,
- tail latency under stress.

This is where `stress-ng` is useful.

## Recommended Main RQ2 Figure

If the paper wants "one figure per RQ", RQ2 should be a two-panel figure:

- **Panel A: syscall tail overhead.** X-axis = rule count or workload operation; Y-axis = p99 latency overhead. This is the micro view.
- **Panel B: real workload overhead.** X-axis = workload; Y-axis = normalized runtime or throughput. Include build, file/server workload, and agent trace replay. This is the macro view.

The two main data sets should therefore be:

1. syscall microbenchmarks,
2. real end-to-end application workloads.

Do not choose `stress-ng` as one of the two main data sets. Keep it as stress evidence.

## Concrete Benchmark Set for ActPlane

Minimal OSDI-style set:

- `syscall_microbench`: custom syscall latency, p50/p95/p99, enough repetitions.
- build macro: `make`, `make test`, `cargo build --release`, and ideally Linux kernel build if time allows.
- file macro: PostMark, filebench, or fio small-file workload.
- service macro: Redis or NGINX with a local load generator.
- agent macro: replay a corpus-derived sequence that exercises exec, file, network, and violation feedback.
- stress: `stress-ng` syscall/file/process/network stressors as a robustness appendix.

For paper-quality reporting:

- bare-metal machine or pinned VM configuration,
- CPU governor and kernel version recorded,
- warmup runs removed,
- repeated trials with confidence intervals,
- p95/p99 tails for syscall paths,
- raw data and scripts in the artifact,
- baseline includes ActPlane unloaded and ActPlane loaded with empty policy, so enforcement cost is separated from policy cost.

## Local Sources Checked

- `docs/reference/taintdroid.pdf`
- `docs/reference/hifi.pdf`
- `docs/reference/lpm-trustworthy-provenance.pdf`
- `docs/reference/camflow.pdf`
- `docs/reference/camquery-runtime-provenance.pdf`
- `docs/reference/sleuth.pdf`
- `docs/reference/unicorn.pdf`
- `docs/reference/camel.pdf`
- `docs/reference/fides.pdf`
- `docs/reference/agentspec.pdf`
- `docs/reference/papers.md`

