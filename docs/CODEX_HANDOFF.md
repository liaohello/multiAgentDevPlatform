# 交给执行 Agent 的完整提示词

以下正文可直接交给能够访问 Windows 项目的一个 Agent。用户已确认本地网页先行，要求实施完整闭环并把结果带回原聊天审阅。本文件是本次实施任务入口；详细验收见执行计划。

---

你负责在本地实施 agentProj 的第一版 Web 工作台，并交付可运行结果、真实/模拟分开的证据和审阅报告。

工作目录：`C:\Users\Administrator\Desktop\tool\agentProj`。

## 目标与执行范围

用户已经接受先用本地网页打通完整闭环。请连续完成执行计划 E0–E7：

`浏览器输入 Goal → Windows Sol 规划 → Windows Python 冻结任务并检查预算/权限 → WSL Codex/DeepSeek 执行 → 收集测试与 Git/代码快照证据 → Sol 逐项验收 → Python 完成、修复或暂停 → 网页展示结果、Token 与证据`。

本次同时交付确定性的模拟失败/重规划/修复场景、预算停止、重复请求、取消和恢复验证，以及最小 Wiki/Markdown 导入、Skill 会话选择、Quick Prompt 优化、Goal Review、手动全链复盘和 Token Audit。

## 读取与依据

先读根目录 `AGENTS.md`、`MEMORY.md`、`WIKI.md`，再读：

1. `docs/design/IMPLEMENTATION_PLAN.md`：本次实施范围、E0–E7、A01–A15 验收和完成判定。
2. `docs/design/WORKBENCH_DESIGN.md`：整体架构与控制边界。
3. `docs/design/DATA_CONTRACTS.md`、`docs/design/BUDGET_AND_USAGE.md`、`docs/design/DECISIONS_AND_OPEN_QUESTIONS.md`。
4. 按阶段补读 `SKILL_MANAGEMENT.md`、`FOUR_SKILLS_DESIGN.md`、`OPS_CAPABILITY_DESIGN.md`。
5. 需要来源时读 `docs/references/GITHUB_PROJECT_RESEARCH_2026-10-15.md` 和其 JSON 清单，不默认加载归档 ZIP、原始页面噪声或整个技能库。
6. 交付时按 `docs/EXECUTION_REPORT_TEMPLATE.md` 填写报告。

用户当前任务和执行计划决定本轮范围，历史文档中的“待讨论”“尚未授权开发”等旧交付描述不应阻止这次明确的实施任务；它们也不表示所有其他推荐已被用户逐项确认。发生实质冲突时说明事实，常规可逆实现选择自行决定并记录。

## 可直接采用的实现默认

React + TypeScript + Vite；Windows Python + FastAPI；SQLite 单一状态源和文件证据；HTTP 命令 + SSE；每个工作目录一个写入 Worker；Windows 和 WSL 分别通过 Codex App Server 接入。

复用同一份用户选定源码并验证 Windows/WSL 路径映射。真实演示使用项目内隔离的临时工作目录，避免让演示 Worker 修改工作台自身代码。默认关闭复核预留，用户配置时从总预算内划分。

桌面壳、多写入并发、SSH/CI、第三方插件批量安装、完整 Profile 编辑、Deep Optimize 和高级文件工具不属于本次首版范围。确有现有代码或兼容性理由时可调整可逆细节，在报告记录原因和影响。

## 执行要求

先检查实际目录、代码、用户修改、Git 边界和 Windows/WSL 工具。依赖安装到项目环境并锁定版本，保留已有资料，不修改全局模型配置或登录状态。Git 不存在时用文件清单/哈希定位改动即可。

核验实际 CLI/协议能力，模型 ID 与推理档位从有效运行时配置获取。DeepSeek 依官方 Responses 接入方案验证；不能静默换成其他执行模型后宣称通过原方案。公开文档不等于本机运行结果。

真实调用使用现有合法认证和用户已设置的测试额度/预算。缺失时尽早集中说明具体输入需求，并继续独立的代码、界面、模拟与测试；不能自行把历史示例额度或测试上限当成用户批准预算，也不要反复要求确认常规实现细节。

Windows Python 是唯一跨轮调度器，所有启动、重试、恢复共用状态/权限/预算门禁。执行额度达到 100% 后禁止下一执行轮；当前轮按冻结策略收尾或中断。复核不能借整理任务继续实现，重启不能清空停止锁。

保留 Goal/计划/验收版本、代码快照与 Decision→Run→Result→Review 的因果关系。执行证据由程序收集/核验；模型 PASS 不能单独把 Goal 标完成，缺失、错配或迟到的证据不能放行。

Agent 原始推理与凭据不进入普通日志、项目数据库、Wiki 或报告；持久事件按允许字段构建。Skill 配置、提供和可观察调用分别记录；跨目录正文只在明确授权后读取。

每阶段完成后继续下一个阶段，直至约定交付完成。出现环境缺口时完成不依赖该缺口的工作；可修复的实现和测试问题继续处理。无法继续的外部条件要给出具体失败/未执行证据和最小解除方法。

## 验收与结果真实性

按 `IMPLEMENTATION_PLAN.md` 的 A01–A15 逐项验收，保存命令、工作目录、退出码与证据。用真实浏览器检查主要操作、流式展示和刷新重连。预算和异常场景可模拟；Windows/WSL 真接入、真实 Goal 闭环和原生会话/取消行为需要真实验证。

真实闭环由工作台统一启动，不能用手工执行两个 CLI 的结果拼装成“产品已跑通”。模拟模式在 UI、事件和报告显式标记，不与真实计量混用。

完整满足必验项且真实闭环通过才为 `COMPLETE`；因必要外部依赖无法验证而可交付其他成果为 `PARTIAL_BLOCKED`；代码未完成或仍有失败项为 `INCOMPLETE`。未跑检查写 NOT_RUN，有外部阻碍写 BLOCKED，测试失败写 FAIL，均不能替换成 PASS。

## 必须交付

1. 可运行的后端与前端，锁定依赖，README 写清安装、开发/构建后启动、配置、测试、停止及网页地址；区分真实模式和模拟模式。
2. `docs/reports/ENVIRONMENT_REPORT.md`：环境/版本/能力与证据，不含秘密。
3. `docs/reports/MVP_EXECUTION_REPORT.md`：按模板填写，供原聊天审阅。
4. `docs/reports/MVP_EXECUTION_RESULT.json`：完成状态、模式、A01–A15 状态、证据、阻碍和剩余工作。
5. `docs/reports/evidence/` 或明确索引的本地证据文件：测试输出、浏览器截图/录屏、示例 Goal、冻结版本、代码快照、执行与审阅关系。
6. 更新 MEMORY、WIKI、JSON 索引与实际实现状态，保留原始资料和历史模拟示例。用 commit 或文件清单/哈希标明验收对应的代码状态。

最终向用户简要报告完成状态、如何启动、网页地址、真实闭环结果、两份报告路径和需用户处理的具体项。用户会把该报告带回原聊天，由另一个 Agent 根据证据审阅。
