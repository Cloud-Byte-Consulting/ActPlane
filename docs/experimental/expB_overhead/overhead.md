# Exp-B 真实负载稳态开销 (audit, attach-once watch, N=12)

ActPlane 经 `watch` 一次性挂载(taint 引擎 + 规则循环在每个 syscall 上运行);对比同一真实负载挂载前后的墙钟。

| workload | bare p50/p99 (s) | +ActPlane p50/p99 (s) | median 开销 |
|---|---|---|---|
| cc-compile | 1.040 / 1.050 | 1.020 / 1.040 | -1.9% |
| git-loop | 6.270 / 6.390 | 6.350 / 6.800 | +1.3% |
| find-grep | 1.490 / 1.560 | 1.510 / 1.550 | +1.3% |
