# Skill 管理设计

更新：2026-10-15。来源：原项目整体记忆第 5 节；原版保存在备份 ZIP。此处维护 Registry、Profile、会话作用域和调用观测，四种工作流的任务规格见 [四种 Skill 设计](FOUR_SKILLS_DESIGN.md)。

## 1. 安装、启用、调用与评估

Skill 是现有 Agent 的轻量配置层，不另造一套 Agent 框架。

| 动作 | 含义 |
| --- | --- |
| 导入 / 安装 | 将来源明确的 Skill 版本保存到 Registry |
| 项目允许 | 当前工作目录允许使用哪些条目 |
| 会话启用 | 当前 Sol / DeepSeek 会话后续轮次可使用哪些条目 |
| 单轮调用 | 本轮显式选择一个 Skill，不改变会话默认设置 |
| 实际读取 / 执行 | 在后端有可观察证据时记录；不能与“已启用”等同 |
| 效果评估 | 对照运行证据分析收益、额外成本与适用性 |

建议三层：统一 Skill Registry → 工作目录允许列表 → 会话选择。Profile 作为初始化配置快照，修改 Profile 不悄悄改变既有会话；Goal 中固定 Skill 内容版本，新增版本在明确的后续运行边界生效。

前端建议：输入框旁 `Skills` 入口；`/skills` 查看；`/skill` 选择；`/skill codebase-design` 单轮调用。保存勾选不启动模型，下一轮生效。单轮 Skill 不能跳过项目允许列表；会话启用与真实调用在界面上分别展示。

## 2. 初始 Skill 组合与阶段分配

| 阶段 | Sol | DeepSeek |
| --- | --- | --- |
| 需求整理 | 可选 Prompt Optimizer | 不需要启动 |
| 架构讨论 | `codebase-design`；按需 `agentic-architecture` | 不需要启动 |
| 实现 | 下达目标与检查证据 | `minimalist` 或 `unslop`，先选其一 |
| 实现后简化 | 审阅结果 | Diff 值得整理时调用 `code-simplifier` |
| 验收 | Goal Review | 提供执行与测试证据 |
| 复盘 | Goal Postmortem / Token Audit | 或由用户指定的分析会话执行 |

以上是建议组合，不是全部默认开启。复盘分析者可按用户选择为指定 Windows Sol 会话、指定 WSL DeepSeek 会话或二者；所有选择受数据作用域约束。

初期 Profile 候选：Architecture、Agent Architecture、Minimal Coding、Code Cleanup、Goal Audit；允许空配置。自动 Goal 按阶段使用已批准配置，不让模型每轮先阅读整个技能库来挑选。

## 3. Registry 与运行时隔离

Registry 条目建议保存：仓库、Skill 相对路径、固定 commit、内容哈希、许可证、依赖、适配 Agent、审核状态和脚本能力。不能只按同名 `unslop` 识别来源。

注册仓库不要直接等同于 Agent 自动发现目录。调度器为 Windows 与 WSL 分别准备可访问的运行路径；避免共享进程的全局扫描配置污染其他会话。运行时隔离方案应先做小实验验证，再决定独立进程还是后端原生作用域。

**2026-10-15 调研更新：**已通过[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)和固定版本协议类型核对 `skills/list`、`forceReload`、按 cwd 的额外根目录、进程级根目录与变更通知。它们的存在已有公开依据；本机版本是否支持、同 cwd 多会话的严格隔离和禁用边界仍未实际验证。推荐独立运行时配置的具体方案见[整体设计](WORKBENCH_DESIGN.md)。

两个重要限制：

- 关闭 Skill 能移除后续可用性与显式加载，但无法让保留历史的模型忘记先前读过的规则；若需要严格去除历史影响，应提供明确的新上下文策略。
- Skill 发现隔离不是文件系统权限隔离。Registry、脚本、网络和凭据的真实权限由运行环境与调度器处理，不能依赖一段提示词宣称实现。

## 4. 与其他专题的关系

四种 Goal 生命周期工作流统一按 [四种 Skill 设计](FOUR_SKILLS_DESIGN.md) 命名；历史的 Goal Postmortem / Session Postmortem 是 `goal-collaboration-postmortem` 的范围或旧称。运行记录与 SkillUsage 见 [数据约定](DATA_CONTRACTS.md)，第三方来源见 [候选清单](../references/SKILL_CANDIDATES.md)。不因来源被写入索引就安装或启用。
