# agentProj Wiki 索引

更新：2026-10-15。模型先读 [MEMORY.md](MEMORY.md)，再根据任务查阅本页列出的专题。下表的摘要用于路由，详细要求以对应设计和决策文件为准。机器索引：[INDEX.json](docs/wiki/INDEX.json)。

> 当前项目已包含可运行实现（第一版本地 Web 工作台，状态 PARTIAL_BLOCKED）。启动方式见 [README.md](README.md)；实现结果与验收见 [MVP 执行报告](docs/reports/MVP_EXECUTION_REPORT.md)。

> 最新独立阶段审查为 **CHANGES_REQUIRED**，发现 7 类需修复问题；原 PARTIAL_BLOCKED 是执行方历史交付标签，当前验收范围见[阶段评估](docs/reports/STAGE_REVIEW_2026-10-15.md)。

## 按任务定位

| 当前任务 / 关键词 | 首选文件 | 需要时补读 |
| --- | --- | --- |
| 阶段评估、执行结果审阅、可靠性缺陷、下一轮修复 | [独立阶段评估](docs/reports/STAGE_REVIEW_2026-10-15.md) | [定向反例与代码哈希](docs/reports/evidence/stage-review/verification.json)；[原执行报告](docs/reports/MVP_EXECUTION_REPORT.md) |
| 前端重设计、PPT 布局、会话 Dashboard、执行时间线与异常恢复 | [整体设计的用户界面章节](docs/design/WORKBENCH_DESIGN.md) | [决策 R20](docs/design/DECISIONS_AND_OPEN_QUESTIONS.md)；[用量与预算](docs/design/BUDGET_AND_USAGE.md)；[实际接口](backend/app/api.py) |
| 运行工作台、安装/启动/测试/停止、两种模式 | [README](README.md) | [执行报告](docs/reports/MVP_EXECUTION_REPORT.md)；[环境报告](docs/reports/ENVIRONMENT_REPORT.md) |
| 实现结果、验收证据、真实/模拟结论、阻碍与解除 | [MVP 执行报告](docs/reports/MVP_EXECUTION_REPORT.md)；[机器摘要](docs/reports/MVP_EXECUTION_RESULT.json) | [验收证据目录](docs/reports/evidence/)；[环境报告](docs/reports/ENVIRONMENT_REPORT.md) |
| 下一步解除 WSL 阻碍、复测真实闭环 | [执行报告 §8](docs/reports/MVP_EXECUTION_REPORT.md) | [环境报告](docs/reports/ENVIRONMENT_REPORT.md)；README 真实模式章节 |
| 开始实施、执行提示词、交给另一个 Agent | [完整执行提示词](docs/CODEX_HANDOFF.md) | [E0–E7 执行计划](docs/design/IMPLEMENTATION_PLAN.md) |
| 执行结果、反馈原聊天、A01–A15 验收 | [反馈报告模板](docs/EXECUTION_REPORT_TEMPLATE.md) | [执行计划](docs/design/IMPLEMENTATION_PLAN.md)；[交接资料核验](docs/maintenance/HANDOFF_VALIDATION_2026-10-15.md) |
| 完整项目设计、综合方案、技术栈、架构取舍 | [整体设计审阅稿](docs/design/WORKBENCH_DESIGN.md) | [GitHub 调研](docs/references/GITHUB_PROJECT_RESEARCH_2026-10-15.md)；[审阅议题](docs/design/DESIGN_REVIEW.md) |
| 参考仓库、实际代码、固定版本、来源纠正 | [GitHub 参考调研](docs/references/GITHUB_PROJECT_RESEARCH_2026-10-15.md) | [源码与版本清单](docs/references/github-research-2026-10-15.json) |
| 与用户讨论、方案采纳、优先决定哪些问题 | [设计审阅清单](docs/design/DESIGN_REVIEW.md) | [决策与待确认事项](docs/design/DECISIONS_AND_OPEN_QUESTIONS.md) |
| 整体架构、Sol / DeepSeek / Python 分工、会话隔离、输出与记忆 | [工作台整体设计](docs/design/WORKBENCH_DESIGN.md) | [已明确要求与未定事项](docs/design/DECISIONS_AND_OPEN_QUESTIONS.md) |
| Skill Manager、Registry、Profile、单轮调用、发现范围 | [Skill 管理设计](docs/design/SKILL_MANAGEMENT.md) | [候选来源](docs/references/SKILL_CANDIDATES.md) |
| Prompt 优化、Goal 验收、双 Agent 复盘、Token Audit | [四种 Skill 设计](docs/design/FOUR_SKILLS_DESIGN.md) | [数据约定](docs/design/DATA_CONTRACTS.md)；需要核对措辞时读[原讨论](docs/conversations/2026-10-15-four-skills.md) |
| Token、预算 100%、收尾、复核预留、恢复 | [用量与预算](docs/design/BUDGET_AND_USAGE.md) | [数据约定](docs/design/DATA_CONTRACTS.md) |
| Ops、文件工具、Adapter、Trace、Handoffs、SSH | [Ops 能力扩展](docs/design/OPS_CAPABILITY_DESIGN.md) | [数据约定](docs/design/DATA_CONTRACTS.md) |
| Goal / Plan / Session / Decision / Run / Evidence、事件、JSON | [数据与事件约定](docs/design/DATA_CONTRACTS.md) | [模拟示例](docs/examples/goal.example.json)；[决策链](docs/examples/decision-trace.example.json) |
| 要求冲突、什么已确认、什么仍是建议 | [决策与待确认事项](docs/design/DECISIONS_AND_OPEN_QUESTIONS.md) | 相关专题；必要时核对来源 |
| 先做什么、里程碑、验收、模拟链重放 | [实施计划](docs/design/IMPLEMENTATION_PLAN.md) | [数据约定](docs/design/DATA_CONTRACTS.md)；[本地交接说明](docs/CODEX_HANDOFF.md) |
| 第三方 Skill 选型、仓库、来源与许可证核验 | [Skill 候选清单](docs/references/SKILL_CANDIDATES.md) | [Skill 管理设计](docs/design/SKILL_MANAGEMENT.md) |
| 原文说了什么、信息从哪里来、为什么合并文件 | [本地化讨论](docs/conversations/2026-10-15-four-skills.md)；[来源与状态](docs/SOURCES_AND_STATUS.md) | [原始文本](docs/sources/2026-10-15-four-skills.original.txt)；[整理记录](docs/maintenance/ORGANIZATION_2026-10-15.md) |

## 阅读路径

首次了解：`MEMORY.md → WORKBENCH_DESIGN.md → DECISIONS_AND_OPEN_QUESTIONS.md`。

实施某项：`MEMORY.md → 本页对应专题 → DATA_CONTRACTS.md → IMPLEMENTATION_PLAN.md`。只加载与当前任务直接相关的文件，缺少上下文再沿链接补读。

追溯讨论：`对应设计 → 本地化对话 → 原始文本`；更早资料从备份 ZIP 读取。历史对话中的推荐、外部核验断言和示例不自动成为当前事实。

## 文档关系与维护

`AGENTS.md` 负责读取约定，`MEMORY.md` 保存短摘要，Wiki 负责定位，`docs/design/` 按主题保存完整设计，`docs/conversations/` 与 `docs/sources/` 提供来源。摘要和索引只保留导航所需信息。

新增思考先保留来源，再合并进对应主题；有实质修订时更新决策与日期，同步本页和 JSON 索引。不要为同一主题再创建第二份“最终版”。归档文件不参与默认检索。
