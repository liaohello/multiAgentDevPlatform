# 四种 Goal 生命周期 Skill 设计

更新：2026-10-15。合并原项目记忆第 5.3 / 6 节与[本轮讨论](../conversations/2026-10-15-four-skills.md)。以下是讨论规格，未创建可安装 Skill、执行器或运行实例。Quick / Deep、证据收集器和统一封装均属建议。

## 1. 四种能力与共同边界

| Skill ID | 输入与输出 | 调用时机 | 权限 |
| --- | --- | --- | --- |
| `prompt-optimizer` | 原始需求、约束 → 可执行目标、边界、验收、优化前后差异 | 用户请求或重大 Goal 的可选准备步骤 | 不擅自改变原目标、不改 Goal 状态 |
| `goal-review` | 冻结 Goal、版本、代码快照、测试/Git 证据 → 逐项验收及结论建议 | Worker 提交有效阶段结果后，受预算约束 | 不直接执行测试或将 Goal 标为完成 |
| `goal-collaboration-postmortem` | 选定会话或完整 Goal 因果链 → 规划、返工、反馈利用与效率分析 | 用户请求、手动触发；重大失败可由调度器按已配置策略触发 | 不自行启动新执行轮、不改 Goal 状态 |
| `token-audit` | Python 已采集用量、预算事件、协作记录 → 高消耗原因与改进假设 | 用户请求、异常分析；异常自动触发需配置 | 不计量、不放行预算、不自动重试 |

Windows Python 根据明确事件、权限和预算安排调用。四种 Skill 不自动互相调用形成额外 Agent 循环；统一复用已有持久化事件与证据，不各自扫描和保存一份历史。Skill 可以替换，状态源和控制权仍在调度器。

历史的 Session Postmortem / Goal Execution Postmortem / Goal Postmortem 统一归入 `goal-collaboration-postmortem`；前者也是其单会话分析范围。

## 2. Prompt Optimizer：两种成本模式

| 模式 | 适用情形 | 输出 |
| --- | --- | --- |
| Quick Optimize | 日常需求、小 Goal | 一次分析，输出任务契约、优化 Prompt、与原文差异 |
| Deep Optimize | 重大 Goal 或多次执行失败 | 多候选 Prompt、代表性用例评估、失败分析与对照结果 |

保留原始需求与采用理由，不把优化改写成替用户更换目标。它不是每条 Sol 消息的默认前置步骤。任务契约明确完成条件，但计划版本、执行记录与状态持久化由调度器负责。已核对的实际来源是 [getsentry/skills 中的 prompt-optimizer](https://github.com/getsentry/skills/blob/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/prompt-optimizer/SKILL.md)，并非独立的 `getsentry/prompt-optimizer` 仓库；define-goal 的具体来源仍待核验。

## 3. Goal Review：执行验证与验收判断分工

| 组件 | 职责 |
| --- | --- |
| Python Evidence Collector（建议组件） | 在明确授权下执行/收集测试、退出码、构建、Git 状态、代码快照和证据 |
| Sol Goal Review | 对照冻结标准逐项引用实现及运行证据，给出验收建议 |
| Python 调度器 | 验证 Goal/计划/验收版本、快照、证据关联与状态门禁，最终应用状态转换 |

建议结论使用 `PASS / FAIL / BLOCKED / UNKNOWN`。`FAIL` 表示有证据不满足标准；`BLOCKED` 表示已知外部依赖或环境使验证无法完成；`UNKNOWN` 表示证据缺失或不足。BLOCKED 和 UNKNOWN 均不计作通过。Sol 的 PASS 单独不能触发完成，测试全通过也不等于所有用户目标达成。

重大 Goal 可增加“目标正确性”核对：当前规格是否真正对应用户要解决的问题。若发现规格需要改变，记录建议并产生经过确认的新版本，不覆盖冻结标准来制造通过。

已核对 [tomzx/agents 中的 verify-pr](https://github.com/tomzx/agents/blob/698f806de04d92574121473898aba72223789efb/skills/verify-pr/SKILL.md)。其构建、运行、录制和文件操作能力不能直接赋给本项目 Review Skill。实际验证由受控执行器承担，Review 只分析可见证据。

## 4. Goal Collaboration Postmortem：完整协作链

**既有记忆保留要求：**默认的完整复盘对象是当前 Goal 关联的 Windows Sol 规划/验收会话与 WSL DeepSeek 执行会话之间的完整行动链，分析结果与规划之间的联系，而非两个独立错误列表。

分析链：原始 Goal / 总体计划 → Sol 任务与可见理由 → DeepSeek 实际行动、结果和测试 → Sol 验收与重规划 → 对总体计划的影响。

| 维度 | 核心问题 |
| --- | --- |
| 计划一致性 | 行动是否仍服务原 Goal？改计划有没有证据？ |
| 规划质量 | 拆分、依赖、约束和验收条件是否充分？ |
| 执行质量 | 是否理解任务？实现与测试是否有效？ |
| 协作效率 | 是否利用前轮反馈？是否重复同类失败修复？ |
| 成本效率 | 时间、Token 与重试带来了哪些可验证进展？ |

支持选择单个 Sol 会话、单个 DeepSeek 会话或 Goal 全链；范围不完整时明确覆盖限制。每条问题结论引用决策、Run、证据与变更；缺失证据不能自动归责。替代方案只能写有依据的改进假设，不能宣称未经测试的方法必然更快。

建议指标：返工轮次 / 总执行轮次、首次验收通过率、同类错误复现次数、阶段实际与计划耗时偏差、累计 Token / 已通过里程碑数量。分母为零时不计算；混用提供商计量口径、重复计数或任务难度不同会影响解释。必要的失败探索不自动归类为浪费。

建议产物：

- `GOAL_POSTMORTEM.md`：人工阅读的全过程分析。
- `DECISION_TRACE.json`：计划、决策、Run、结果和证据之间的关联。
- `EFFICIENCY_REPORT.json`：指标、口径、缺失项和趋势数据。

前端建议展示阶段与轮次时间线、决策/执行关系、Token 与验收进展、可展开的问题证据。Skill 与消耗可以关联，但不能因此认定所有消耗都由该 Skill 造成；真正比较收益需要后续设计相似任务的对照。

补充约定：缺少中间输出时，不能精确还原未记录的内部错误尝试。保留最小事实链：

`Decision → Task / Run → 状态与错误摘要 → 测试证据 → Review → 下一 Decision`

需要命令级诊断时读取明确保存的必要错误证据；未记录过程统一标为 UNKNOWN。复盘分析者和被分析的会话范围分别配置，不从单会话材料声称覆盖整个 Goal。

## 5. Token Audit：使用已有计量的分析工作流

读取每轮和累计用量、上下文大小、工具输出、重试、等待与验收进展，分析是否存在重复加载、冗长结果、缓存未利用或不合适的模型配置。优化对象是完成整个 Goal 的总成本，而非孤立的一次调用。

区分可见事实、基于证据的推断和待验证改进建议。Skill 选择与用量相关不等于因果。实际用量、估算、价格口径与预算停止由 Python 负责，详见 [用量与预算](BUDGET_AND_USAGE.md)。

## 6. 统一接口与证据关系

建议统一封装如下，专有字段在各工作流中扩展；这是接口草案，不代表版本已经冻结：

```json
{
  "schema_version": "1.0",
  "skill_id": "goal-review",
  "goal_id": "goal-001",
  "session_ids": ["sol-001", "deepseek-001"],
  "input_refs": [],
  "findings": [],
  "evidence_refs": [],
  "uncertainties": []
}
```

示例 ID 和空数组均非真实记录。Review 扩展逐项标准、Goal/验收/计划版本、代码快照与建议结论；Postmortem 扩展范围、因果边、指标及缺失项；Token Audit 扩展用量口径和诊断；Optimizer 扩展原文、候选与差异。具体字段、ID、证据保存和 schema 版本见 [数据约定](DATA_CONTRACTS.md)。

## 7. 实施顺序与模拟验收

先统一事件和证据，再接入轻量 Prompt Optimizer / Goal Review，随后完善全链 Postmortem，最后加入 Token Audit。基础用量采集与预算门禁需要早于 Token Audit，不能等诊断 Skill 完成才开始记录。

用一条模拟 Goal 重放：Sol 下发 → DeepSeek 失败 → Sol 根据证据重规划 → DeepSeek 修复 → Sol 验收 → Postmortem → Token Audit。应能关联计划版本、任务、错误摘要、证据、审阅及每轮成本，展示缺失项，并验证重启后关系仍可恢复。模拟结果必须标注为模拟，不能替代真实执行闭环验收。

具体阶段见 [实施计划](IMPLEMENTATION_PLAN.md)，第三方候选仅作[来源线索](../references/SKILL_CANDIDATES.md)。

## 8. 本轮公开来源核验

2026-10-15 已核对四种工作流对应文件，范围及固定版本见 [GitHub 调研](../references/GITHUB_PROJECT_RESEARCH_2026-10-15.md)。其中 agent-retro 明确要求 Claude Code JSONL，不能直接覆盖本项目双端协作；token-optimization 的实际位置为 bm629/agent-skills 仓库。仅核验方法和文档，没有安装或运行这些 Skill。最新整体集成建议在 [工作台设计审阅稿](WORKBENCH_DESIGN.md)，尚待用户讨论采纳。
