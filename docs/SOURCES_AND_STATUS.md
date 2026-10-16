# 来源范围与实际状态

更新日期：2026-10-15（America/Los_Angeles）。项目路径：`C:\Users\Administrator\Desktop\tool\agentProj`。

## 来源及可信边界

| 来源 | 保留位置 | 说明 |
| --- | --- | --- |
| 原项目讨论记忆包 | [原文件备份 ZIP](archive/2026-10-15-originals.zip) | 17 份独立原文件，包含历史摘要、建议、模拟示例及打包资料 |
| 既有 Ops 设计记录 | [Ops 设计](design/OPS_CAPABILITY_DESIGN.md)；原版在 ZIP | 保留设计判断，第三方来源/版本/性能未在本任务核验 |
| 本轮用户粘贴的四种 Skill 讨论 | [原始文本](sources/2026-10-15-four-skills.original.txt) | 从用户附件逐字节复制；完整保留原文本和页面噪声 |
| 四种 Skill 讨论可读版 | [本地化 Markdown](conversations/2026-10-15-four-skills.md) | 清理图卡残片、CSS，依据可见标签重建流程图；正文观点保留为历史讨论 |
| 本次整理决策与阅读约定 | [整理记录](maintenance/ORGANIZATION_2026-10-15.md)；[AGENTS.md](../AGENTS.md) | 去重、归档、主题拆分、项目记忆和 Wiki 路由 |
| 本轮 GitHub 与官方文档调研 | [调研报告](references/GITHUB_PROJECT_RESEARCH_2026-10-15.md)；[固定版本清单](references/github-research-2026-10-15.json) | 16 个仓库的元数据/版本线索，30 份固定版本文件及官方文档；非运行验证 |
| 综合设计与待讨论问题 | [整体方案](design/WORKBENCH_DESIGN.md)；[审阅清单](design/DESIGN_REVIEW.md) | 推荐架构与实施顺序，未自动升级为用户已采纳决定 |
| 用户确认与开发交接 | [执行计划](design/IMPLEMENTATION_PLAN.md)；[完整提示词](CODEX_HANDOFF.md)；[报告模板](EXECUTION_REPORT_TEMPLATE.md) | 用户确认本地网页先行，由用户交给另一个 Agent 执行；本聊天未启动应用开发 |
| 外部 Agent 的实现交付 | [执行报告](reports/MVP_EXECUTION_REPORT.md)；[机器摘要](reports/MVP_EXECUTION_RESULT.json) | 已有 Web 原型、模拟闭环和真实 Sol 证据，自报 PARTIAL_BLOCKED |
| 本聊天阶段性独立评估 | [阶段报告](reports/STAGE_REVIEW_2026-10-15.md)；[反例数据](reports/evidence/stage-review/verification.json) | 原测试/构建通过，定向反例揭示核心缺陷；CHANGES_REQUIRED，未在本轮修改业务源码 |

早期记忆包曾注明来源包括 Personal Context / 历史上下文检索。本任务没有重新检索这些历史，也未取得完整原始聊天。R01–R16 延续为既有基线，不能当作本轮逐字确认。新附件中的“我核对了仓库”等陈述属于原讨论，本次仅归档，未重新验证其结论。

## 本次实际完成

- 已直接读取和写入上述 Windows 项目目录，合并 12 份完全相同的重复文件，保留一套主题设计。
- 原项目的 29 个文件已建立逐文件 SHA-256 清单；17 份独立原文件进入去重 ZIP，归档内容逐项校验。
- 用户附件原文已保存，可读 Markdown 已生成；四种 Skill 的新增设计并入专题文档。
- 已建立 `AGENTS.md → MEMORY.md → WIKI.md → 对应设计` 的本地阅读路径及 JSON 索引。
- 已将旧安装脚本、打包入口和旧校验清单归档；它们描述的是历史包，不能用来校验当前重组目录。

## 尚未实施或核验

早期整理/研究时尚无应用实现；现已有外部 Agent 交付的 Web 原型与部分真实证据。独立评估确认原测试和构建可复现，也发现需修复的状态、计量、目录范围、Skill 和 WSL 接入问题。完整真实 Sol→WSL DeepSeek→Sol 链仍未通过，原生 Skill 隔离与 WSL 取消/恢复尚需验证。`docs/examples/` 仍是历史模拟数据，不能作为真实执行证据。

项目记忆由本地文件持久保存；本次没有写入模型账户级全局记忆。后续在本目录工作的模型应按 `AGENTS.md` 阅读；其他运行环境需支持该约定，或明确提供入口文件。

## 后续维护

设计变更写入对应专题和决策表，实际实现/验证再更新状态并附证据。原始来源保持可追溯；新增独立对话使用新的日期或主题文件。文件迁移、备份哈希和重复对应关系见 [整理清单](maintenance/organization-2026-10-15.json)。

本轮调研与综合设计的文档核验结果见 [RESEARCH_VALIDATION_2026-10-15.md](maintenance/RESEARCH_VALIDATION_2026-10-15.md)；此前整理报告保留其当时的检查数量。

早期交接新增/更新 E0–E7 和 A01–A15，将真实闭环、模拟场景、未执行和外部阻塞分开；交接资料校验见 [HANDOFF_VALIDATION_2026-10-15.md](maintenance/HANDOFF_VALIDATION_2026-10-15.md)。执行报告后来已生成，阶段评估另行保留，不覆盖原执行结果。
