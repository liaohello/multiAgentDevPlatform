# 执行结果报告模板

执行 Agent 将本模板填写为 `docs/reports/MVP_EXECUTION_REPORT.md`。本模板本身不是执行记录，未填写项不能当作已通过。对应验收见 [执行计划](design/IMPLEMENTATION_PLAN.md)，执行要求见 [交接提示词](CODEX_HANDOFF.md)。

## 1. 结果概况

- 完成状态：COMPLETE / PARTIAL_BLOCKED / INCOMPLETE。
- 执行日期、时区与负责 Agent。
- 本次实现范围、未实现范围。
- 代码版本：commit，或文件清单/哈希的位置；注明用户原有修改。
- 真实模式、模拟模式各自是否运行。
- 真实 Windows Sol → WSL DeepSeek → Sol 闭环：PASS / FAIL / BLOCKED / NOT_RUN。

## 2. 启动与复现

列出实际验证过的依赖安装、配置、开发启动、构建后启动、测试、停止命令，分别注明执行目录、所需环境变量名称、网页地址和健康检查。给出真实模式/模拟模式选择方式。不要附凭据内容。

说明复现需要哪些由用户提供的配置，以及是否已启动长期服务、如何识别和停止本应用进程。

## 3. 环境与实际接入

列出 Windows/WSL 发行版、Python/Node、Codex 版本、路径映射、Provider/模型 ID、实际能力及认证是否就绪。每项注明实测或仅文档依据，链接 `ENVIRONMENT_REPORT.md`。

## 4. 逐项验收

为 A01–A15 各填写一行，状态使用 PASS / FAIL / BLOCKED / NOT_RUN；每行必须有检查方式、证据类型和证据路径。

| ID | 状态 | 检查方式与实际结果 | 证据类型（真实/模拟/浏览器） | 证据路径 |
| --- | --- | --- | --- | --- |
| A01–A15 | 分别填写，不合并为一行 | 命令或浏览器操作、退出码与关键事实 | 明确类型 | 可访问的本地文件 |

测试报告写明通过、失败、跳过和未执行数量。仅记录真实运行的命令与结果，不能预填成功。

## 5. 一个真实 Goal 的完整证据

提供 Goal ID、用户输入、模型与 Session/Thread、计划/验收版本、Decision、Run、Result、Review、代码快照和 Evidence 的关联；记录每次状态变化和其来源。

给出执行命令、测试退出码、变更摘要、逐项验收，以及 Python 最终如何应用状态。真实用量来源、是否估算/缺失、预算停止或恢复分别说明。未跑真实链时直接记录阻碍，不用模拟结果填此节。

## 6. 模拟与异常验证

记录固定失败→重规划→修复场景，以及预算 100%、重复启动、用量重复/迟到、版本错配、刷新重连和恢复的验证。示例 ID 和计量标记为模拟。

## 7. 实现与设计差异

逐项列出实际选择、与计划的差异、原因、影响和验证；区分用户确认决定、实现默认与需要继续讨论的事项。尤其记录 Provider、Skill 隔离、数据库路径和取消策略的实际限制。

## 8. 剩余问题与解除方法

每项包含现象、复现步骤、已知原因/未知部分、影响、已尝试的方法、所需用户输入或环境变化及建议后续动作。说明为何这些问题不应被计作 COMPLETE。

## 9. 给原聊天的简短摘要

用简短文字列出完成状态、启动方式、真实链结果、通过/失败/未执行验收项、主要差异与待处理项，附报告和机器结果路径，便于用户直接带回审阅。

## 10. 机器摘要约定

另外生成 `docs/reports/MVP_EXECUTION_RESULT.json`，至少包含：

- `schema_version`：字符串 `1.0`；`completion_status`：上述三种状态之一。
- `code_revision_ref`、`report_path`、`environment_report_path`、`launch_instructions_ref`。
- `real_loop_status`、`simulation_loop_status`，采用 PASS/FAIL/BLOCKED/NOT_RUN。
- `acceptance`：A01–A15 每项的 `id`、`status`、`mode`、`evidence_refs`、`note`。
- `tests`：实际命令、工作目录、退出码与输出引用，另列跳过/未运行项。
- `demo_goal_refs`、`design_deviations`、`blockers`、`remaining_work`。

使用项目内相对路径或明确注明的本地证据位置，不写凭据或原始推理。机器摘要与 Markdown 的状态一致；真实链未通过不得写 COMPLETE。
