# ActPlane Thesis Evolution — Discussion Log

> 本文记录 ActPlane 论文核心 thesis 的演化过程，从最初的 "push to OS" 到 cross-layer
> linkage 的 insight。每一层都保留，因为它展示了为什么浅层 framing 不够。

---

## 第一层："Push enforcement to OS layer"（出发点）

最初的 argument：

- Agent 被 NL 指令（CLAUDE.md / AGENTS.md）管着，但 prompt-level 约束是概率性的。
- Tool-layer guard（AgentSpec, Progent）可以被 bash/subprocess/SDK 绕过。
- 因此 enforcement 应该在 OS 层——syscall/LSM 边界，agent 无论怎么走都要过。

**为什么不够**：CamQuery (CCS 2018) 已经在内核做了 labeled IFC + cross-channel +
enforce。光说 "push to OS" 等于说 "CamQuery was right, we reimplemented it on eBPF"。
这是 motivation，不是 contribution。

---

## 第二层："Cooperative threat model changes what enforcement means"

传统 IFC/MAC 的 subject 是 adversary，设计哲学是：

- 目标是 soundness（绝不漏掉攻击）
- 拦住就赢了，subject 困惑无所谓
- Silent `-EPERM` 是正确行为
- 评估指标：violation caught, false negative rate

但 agent 是 cooperative-but-forgetful。这不是同一个优化问题：

- 目标是 **task completion through correct paths**（不是拦截本身）
- 拦住但 agent 卡死 = 系统失败，不是系统成功
- Feedback 不是锦上添花，是 **load-bearing component**
- 评估指标变成：recovery rate, task completion, repeated violations

**Insight**：CamQuery 的机制搬过来不够——CamQuery 优化的是 "prevent the bad thing"，
agent harness 优化的是 "enable the correct path despite the agent's tendency to forget"。

---

## 第三层："Provenance-aware remediation — what only the kernel can say"

这一层回答：为什么 feedback 必须跟 OS-level IFC 绑定，而不能在任意层加上去？

考虑一个 violation："agent 尝试 `curl api.github.com`，被拦了"。

- **Tool-layer guard** 只能说："你不被允许 curl"。它只看到了当前这一步操作。
- **OS-level IFC** 能说："你 30 秒前读了 `.env` 文件，获得了 `SECRET` label，而
  `SECRET` label 的进程不允许连外网。你可以：(1) 先跑 `redactor` 工具去除敏感数据
  （declassify path），(2) 把网络操作交给一个没有 `SECRET` label 的子任务。"

这个 remediation 包含三种只有内核 provenance 才知道的信息：
1. **为什么被拦** — 不是因为 curl 本身被禁，而是因为你携带了 SECRET taint
2. **taint 从哪来** — 你读了 `.env`，这是 source
3. **怎样合法地完成任务** — declassify/gate path 存在，kernel 知道它

**Insight**：kernel provenance state 是产生有效 remediation 的唯一来源。这是
OS-level IFC + feedback 不是 trivial 组合的原因。

---

## 第四层："Action vs Behavior gap"（探索，有局限）

Agent 指令文件里的约束大部分在 **behavior level**：

- "never expose secrets" = 不是禁止 connect，是禁止 "读过 secret 之后 connect"
- "test before commit" = 不是禁止 commit，是禁止 "没跑测试的 commit"

Enforcement 需要把分散的 action 聚合成 behavior，这需要执行历史。Label 是执行历史
的压缩表示。

**局限**：这个 framing 不完全准确——不是所有现有系统都在 action level：
- SELinux 有 type transition（有限的状态机式 behavior）
- Tetragon 有 followChildren（fork/exec 谱系的 boolean flag）
- CamQuery 有完整的跨通道 label 传播（full behavior-level）

所以不能说 "所有人都在 action level，只有我们在 behavior level"。

---

## 第五层："Cross-layer linkage"（当前最佳 framing）

核心 insight 不是 "在哪一层做 enforcement"，而是 **层与层之间有没有连通**。

现状——三层各自孤立：

```
Intent layer    (CLAUDE.md: "不要泄露 secret")     <-- 孤立
     |  X 断开
Tool layer      (AgentSpec: 检查 tool call)         <-- 孤立
     |  X 断开
OS layer        (seccomp/Landlock: 检查 syscall)    <-- 孤立
```

- Tool-layer guard 拦了一个 tool call，但 agent 用 subprocess 绕过去了它看不见
- OS enforcer 拦了一个 syscall，但只能返回 `Permission denied`，agent 不知道为什么
- Agent 写了 behavioral constraint，既没连到 tool-layer 也没连到 OS-layer

ARMO 博客 (armosec.io/blog/ebpf-based-ai-agent-enforcement/) 的观察：
> "eBPF sees *that* something happened, not *why*."

CamQuery 在 OS 层内做了横向连通（cross-object labels）+ 向下连通（policy -> kernel）。
但没有**向上连通**（kernel violation -> agent feedback）。

AgentSpec 在 tool 层做了横向检查 + 向上连通（corrective feedback）。
但没有**向下连通**（看不见 tool API 之下的操作）。

ActPlane 提供三个方向的连通：

```
Intent layer    (policy DSL: behavioral constraint)
     |  v 向下：DSL 编译成内核规则
OS layer        (eBPF: label propagation + enforcement)
     |  <-> 横向：跨 process/file/network 的 label 传播
     |  ^ 向上：violation -> 带 provenance 的 behavioral feedback -> agent context
Intent layer    (agent 理解 feedback, 换路重试)
```

Label propagation 在这个 framing 里的角色：不是 "OS 层的 feature"，而是**连通的中间
表示**——label 把分散的 OS action 聚合成 behavioral state，让内核能代表 intent 层做
判断，也让 feedback 能用 behavioral 语言解释 OS-level 的事件。

---

## Contribution statement（基于 cross-layer framing）

> Agent behavioral constraints span from intent through tools to OS syscalls,
> but existing enforcement mechanisms operate within a single layer. ActPlane
> closes the loop across layers: it compiles intent-level constraints into
> OS-level enforcement via labeled information flow, and translates OS-level
> violations back into intent-level feedback the agent can act on.

这比 "push to OS" 深的地方：它不是说 "OS 层更好"，而是说**问题本质上是跨层的，
需要一个跨层的机制**。OS 层是 enforcement 的必要位置（因为 action 最终在那里
发生），但光有 OS enforcement 没用——还需要向上的 feedback 路径才能让 cooperative
agent 受益。

---

## Open questions

1. "Cross-layer" 是不是最好的术语？系统领域有没有更 established 的说法？
   - End-to-end argument (Saltzer, Reed, Clark 1984) 有相关精神
   - Cross-layer optimization 在网络领域有先例
   - 但 "cross-layer enforcement" 在 security 领域不是标准术语
2. Paper 标题要不要改？"OS-Enforced Agent Harnesses" 是否还合适？
   - 主流 "harness" 指 orchestration，不是 enforcement（见 harness_define.md）
   - 可能需要 qualify：enforcement harness / safety harness
3. Evaluation 的核心 hypothesis 是否要调整为 cross-layer 的验证？
   - C3 vs C4 验证的是 feedback（向上连通）的价值
   - E1 验证的是 OS-level 不可绕过性（向下连通的必要性）
   - 需要一个实验验证 cross-object label propagation（横向连通）的必要性
4. Abstract 的结构如何基于 cross-layer framing 重写？
   - 见本文第五层的骨架
