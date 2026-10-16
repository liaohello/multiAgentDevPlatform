# 数据对象与交接约定草案

本文是接口设计起点，不是已部署协议。示例位于 [docs/examples](../examples/goal.example.json)；全部为模拟值。实际实现应保持最少字段，以满足关联、恢复、计数与证据审阅。更新：2026-10-15，已合并四种 Skill 讨论的接口建议。

本轮[整体设计审阅稿](WORKBENCH_DESIGN.md)建议 SQLite 单一状态源、Windows Python 单写入、同事务提交状态与事件，并将新协议版本统一为字符串 `"1.0"`。这些是待审阅方案，尚未冻结接口；下列旧字段及模拟示例继续作为来源草案保留。

## 1. 主要对象

| 对象 | 必要关系与用途 |
| --- | --- |
| Workspace | 当前工作目录、Windows/WSL 路径映射、授权作用域 |
| Session | workspace、角色、运行环境、后端 thread、模型与推理强度、Skill 配置版本 |
| Goal | 原始需求、目标版本、验收标准版本、计划版本、关联会话、预算策略、当前状态 |
| PlanRevision | Goal、版本、里程碑、依赖、变更原因、发起决定、冻结时间 |
| Decision | Goal、Session、计划版本、可见指令/理由、所依据的结果与证据、下一步动作 |
| Run | Goal、执行 Session、发起 Decision、冻结任务、运行配置、开始/结束、状态、结果 |
| Result | Run、完成/失败/暂停事实、变更、测试、证据引用；不自授验收通过 |
| Evidence | 工作目录内相对路径、类型、来源 Run/Decision、采集时间、必要的哈希/版本 |
| SkillRevision | 来源仓库和目录、commit、内容哈希、许可证、审核与依赖 |
| SkillUsage | Run/轮次、配置版本、期望调用、可观察到的加载/调用证据 |
| UsageEvent | 会话/Goal/调用 ID、提供商、模型、Token/费用口径、精确度与来源 |
| Authorization | 授权范围、用途、创建来源、有效期或撤销状态 |

业务上的一轮可能包含多个模型调用与工具操作；不要让 `run_id` 同时承担 thread、轮次和 API 调用三个含义。可使用 `turn_id` / `model_call_id` 细分，同时让事件总能归属 Goal。

## 2. 决策关联

最小链路：Goal + PlanRevision → Sol Decision → Worker Run → Result → Sol ReviewDecision。

ReviewDecision 引用前一结果与证据，内容可以是继续、重试、重规划、完成或暂停的建议。调度器验证数据、权限与预算后再执行状态变化。

`decision_id` 和 `run_id` 不足以说明因果时增加明确的 `based_on_result_ids`、`caused_by_decision_id`。不要只按时间相邻猜测“这次修复回应了哪次失败”。

## 3. 事件与证据保存

建议追加式事件至少包含：`schema_version`、`event_id`、`timestamp`（含时区）、`workspace_id`、`goal_id`、`session_id`、`run_id`、`type`、`caused_by`、`payload`。不适用的关系可为空，但不能伪造。

事件候选：

- 会话创建、模型/强度调整、显式导入、授权变更。
- 计划创建与修订、指令下达、执行启动/暂停/结束。
- 工具调用、命令结果、测试结论、证据登记。
- Skill 配置生效、运行时提供、可观察加载/调用。
- 用量结算、预算预警、门禁关闭、恢复批准。
- 验收与复盘产物生成。

结构化事件保留事实和必要输出；大文件放证据目录并索引。事件不要混入隐藏推理、凭据或无必要的整段中间自然语言输出。

证据关联实际 Git commit/工作树状态、测试命令、退出码、报告时间；工作树 Diff 应保存快照或哈希，避免后续变化使报告失去对应关系。结果不能仅凭“测试通过”自然语言判断。

## 4. 建议的项目内目录

以下是未来工作台运行数据示意，**本次没有创建实际运行数据**：

| 路径 | 内容 |
| --- | --- |
| `workspace-data/sessions/` | 会话元数据、显式导入与可见历史 |
| `workspace-data/goals/<goal-id>/goal.json` | Goal 与当前版本引用 |
| `workspace-data/goals/<goal-id>/plans/` | 不覆盖的计划版本 |
| `workspace-data/goals/<goal-id>/events.jsonl` | 追加的可见行动事实 |
| `workspace-data/goals/<goal-id>/runs/<run-id>/` | 冻结任务、结果与证据 |
| `workspace-data/goals/<goal-id>/reviews/` | 验收与复盘产物 |
| `workspace-data/wiki/index.json` | 标题、摘要、标签与原位置 |
| `workspace-data/skill-config/` | 项目和会话的 Skill 配置版本 |

路径是建议，可复用已有存储。最小版本不要求事件总线、微服务、向量数据库或双写所有数据。若数据库为事实源，文件导出应有清楚版本，避免两个来源各自更新。

## 5. 状态与预算门禁

Goal 生命周期与预算状态应分开表达。比如 Goal 为 `PAUSED`，预算门禁为 `CLOSED`，而已启动 Run 仍可能在收尾。不要用一个 `running=true` 兼任所有状态。

建议预算门禁：`OPEN` → `CLOSED`（达到阈值）→ 用户明确恢复后 `OPEN`。70%/90% 是展示等级，不一定要创建独立后端状态。

所有启动入口使用同一个准入逻辑：检查权限与 Goal 状态 → 汇总已结算用量与未结算预留 → 原子准入 → 记录 Run → 启动进程。手工重试、自动重试和模型请求不能各写一套放行逻辑。

无足够实时用量时，记录估算/未知；当前调用结束后用真实值结算，去重并释放对应预留。不能把累计快照当增量重复相加。可恢复状态应持久化，重启后不默认清除预算锁。

## 6. 结构化输出约定

验收建议逐项输出 `criterion_id`、`status`（PASS/FAIL/BLOCKED/UNKNOWN）、`evidence_ids`、`reason`，并记录 Goal/计划/验收标准的版本及代码快照。已知依赖阻碍验证用 BLOCKED；证据不足用 UNKNOWN。二者都不能视为通过，模型输出状态不直接授权执行。

复盘 JSON 同时保存指标数值、分母、口径、覆盖范围、缺失项与证据。没有通过里程碑时，单位里程碑 Token 为 `null` 并解释原因。推断与事实分开，避免不可验证的“效率评分”。

SkillUsage 的观测状态建议为 `configured`、`provided`、`loaded_observed`、`invoked_observed`；无法观测时保留 `unknown`，不要根据文本风格推断真实调用。

## 7. 四种 Skill 共用的封装与冻结信息

[四种 Skill 设计](FOUR_SKILLS_DESIGN.md) 建议共用 `schema_version`、`skill_id`、`goal_id`、`session_ids`、`input_refs`、`findings`、`evidence_refs`、`uncertainties`；在其上增加专有字段，不另建互不关联的历史源。

Review 至少关联 `goal_version`、`acceptance_version`、`plan_version`、`run_id`、`result_id` 与代码快照引用；状态转换前由 Python 检查这些对象和证据属于同一验收对象。Skill 输出不能依赖“最新文件”这种会随工作树变化的隐含指针。

`task_id` 可标识冻结任务，`run_id` 标识一次执行；重试可关联同一任务但必须拥有新的 Run。错误记录只保存可见错误类型、摘要、来源和必要证据，不补写未记录的尝试。

统一封装示例使用字符串版本 `"1.0"`，旧对象示例使用数字 `1`。二者都是历史草案，尚无可用解析器或冻结版本；实施时需明确各 schema 的版本语义和类型，不能假设已可互换。

## 8. 目录与状态源的统一

本资料库的 `docs/wiki/INDEX.json` 是设计文档索引，不是未来运行时的 `workspace-data/wiki/index.json`。Ops 讨论中的 `.agent-workspace/` 和本文的 `workspace-data/` 是候选目录命名；实施时选定或复用一套，不能同时建立独立可写状态源。

四种 Skill、Ops Trace 和前端都复用同一 Goal / Session / Decision / Run / Evidence / Usage 关联。SQLite、文件或其他存储的选取仍未定，先用最小协议和模拟链验证可追溯性，再决定持久化实现。
