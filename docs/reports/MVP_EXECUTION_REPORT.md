# MVP 执行报告（MVP_EXECUTION_REPORT）

填写日期：2026-10-15（America/Los_Angeles）。执行 Agent：WorkBuddy 本地会话（可访问 Windows 项目目录与工具链）。
依据：[CODEX_HANDOFF.md](../CODEX_HANDOFF.md) 执行提示词、[IMPLEMENTATION_PLAN.md](../design/IMPLEMENTATION_PLAN.md) E0–E7 与 A01–A15、[EXECUTION_REPORT_TEMPLATE.md](../EXECUTION_REPORT_TEMPLATE.md) 报告模板。

## 1. 结果概况

- **完成状态：PARTIAL_BLOCKED**。
  - 可运行后端与前端、锁定依赖、启动/停止/测试脚本、模拟闭环与全部异常场景验证、真实 Windows Sol 接入（含真实规划、会话隔离、续接、切强度、原生中断）均已交付并留有证据。
  - **真实闭环未通过**：链路中「WSL Codex/DeepSeek 执行」一段因本执行环境的程序黑名单阻止 `wsl.exe`（WinError 5 / PROGRAM BLOCKED BY SECURITY POLICY）而无法运行，属必要外部依赖阻碍；按要求不用模拟替代 A02/A04 的真实验证。
- 执行日期/时区：2026-10-15，America/Los_Angeles。
- 本次实现范围：E0–E7 全部阶段（含四种轻量工作流、Skill/Wiki 最小实现、预算门禁、证据采集、SSE、浏览器页面）。
- 未实现/未验证范围：WSL/DeepSeek 真实执行（环境阻碍）；Skill 在原生运行时层面的严格隔离（保留限制说明，不宣称完成）；桌面壳、多 Worker、SSH/CI 等本在首版范围之外。
- 代码版本定位：本项目**不是 Git 仓库**（`git status` 报 `not a git repository`），按计划使用文件清单/哈希定位验收对象：`docs/reports/evidence/code_manifest.sha256.txt`（57 个文件：backend/app、backend/tests、backend/scripts、ui/src、scripts、依赖清单与构建产物哈希）。
- 模式运行情况：**两种模式均已实际运行**。真实模式运行了 Windows Sol 真实回合（规划、隔离/续接实验、中断实验）；模拟模式完成完整闭环（失败→重规划→修复→完成）与预算/取消场景。
- 真实 Windows Sol → WSL DeepSeek → Sol 闭环：**BLOCKED**（Sol 段真实通过，WSL 段环境阻碍；证据见 §5）。

## 2. 启动与复现

### 生产式启动（已实测）

```
目录:    <项目根> C:\Users\Administrator\Desktop\tool\agentProj
命令:    scripts\start_workbench.bat
效果:    自动构建前端（如需）→ 启动后端（前台窗口）→ 打开浏览器
网页:    http://127.0.0.1:8787   （页面自动注入本次会话令牌）
停止:    关闭窗口 / Ctrl+C；或 scripts\stop_workbench.bat（按 runtime.json 的 pid 只终止本应用进程）
```

实测记录（证据 `evidence/a01_start_stop/` 与 §4 A01 行）：

- 服务就绪：`GET /api/health` → `{"status":"ok","version":"1.0.0",...}`；
- 停止脚本输出：`stopping pid 22060 ...` → `成功: 已终止 PID 22060`，随后连接被拒绝，说明服务已正常退出；
- 说明：本执行会话处于带进程回收策略的沙箱中，`start /min` 形式的后台子进程会在父任务结束时被回收，因此交付脚本改为**前台运行模式**（对最终用户等价且更稳健）；沙箱内的后台任务方式（工具托管）同样验证通过。

### 依赖安装与构建

```
后端:  backend\.venv （由托管 Python 3.13.14 创建；依赖固定于 backend\requirements.txt，
       全量锁定 backend\requirements.lock.txt。注意：本机 pip 默认镜像（清华）不可用，
       脚本以 -i https://pypi.org/simple 安装）
前端:  ui\package-lock.json 锁定；npm install 69 packages；npm run build 成功
       （tsc 全过，产物 ui/dist：index.html 0.47kB / css 7.01kB / js 254.99kB，证据 evidence/tests/ui_build_output.txt）
```

### 测试与停止

```
测试:  scripts\run_tests.bat  →  15 passed, 1 warning in 50.74s
       （证据 docs/reports/evidence/tests/pytest_output.txt；完整 15 项覆盖见 §4）
停止:  scripts\stop_workbench.bat （或关闭启动窗口）
```

### 真实/模拟模式选择方式

- 界面「新建 Goal」→ 模式下拉：`simulation`（默认，确定性模拟，场景可选 demo/budget/cancel）或 `real`（真实 Sol；可填模型与推理档位）。
- 真实模式前置：Windows 已登录 Codex（本机为 ChatGPT 账号，实测就绪）；WSL 段需发行版内 Codex 可用（本环境不可达，界面「环境与能力」页显式显示 BLOCKED 原因）。
- 所有模拟记录 `exactness=simulated`、真实记录 `exactness=reported`，在同一 Goal 内不混用。

### 需要用户提供/处理的配置

| 项 | 说明 |
| --- | --- |
| WSL 发行版内的 Codex + DeepSeek 配置 | 按 DeepSeek 官方 Codex 接入说明配置 provider；工作台不读取凭据内容 |
| 解除 `wsl.exe` 黑名单 | Security Center → Command Security → Program Blacklist 移除 `wsl.exe`（或换到无此限制的环境运行） |
| 真实预算额度（可选） | 本次未设定预算上限；如需限额，在创建 Goal 时填写 budget_tokens |

## 3. 环境与实际接入

详见 [ENVIRONMENT_REPORT.md](ENVIRONMENT_REPORT.md)。摘要：

| 项 | 实测结果 | 依据 |
| --- | --- | --- |
| Windows 10 Enterprise 19045 / Git 2.55 / Python 3.13.14 / Node 22.22.2 | 就绪 | 实测 |
| Codex 原生 exe 0.162.0-alpha.17.2（桌面版同款）+ npm 包装器 0.153.4 | 就绪，默认用原生 | 实测 |
| app-server 协议（JSONL/stdio）：initialize、thread/start、thread/resume、turn/start、turn/interrupt、model/list、thread/turns/list 等 | **实测通过**（含真实回合与中断） | 实测 + 生成的 JSON Schema（devtools/protocol-schema-native） |
| 认证 | `Logged in using ChatGPT`（未输出任何凭据内容） | 实测 |
| 模型与档位 | gpt-6.1-sol / gpt-6-sol / gpt-5.6-sol / gpt-6-luna / gpt-5.6-luna 等 7 个；low…max/ultra | `model/list` 实测 |
| WSL 发行版 / WSL 内 Codex / DeepSeek | **BLOCKED**：`wsl.exe` 被程序黑名单阻止（[WinError 5]） | 实测错误原文（evidence/e0/wsl_blocked.evidence.txt） |

## 4. 逐项验收（A01–A15）

测试统计：**15 passed / 0 failed / 0 skipped**（`pytest`）。真实回合统计见 §5 末。

| ID | 状态 | 检查方式与实际结果 | 证据类型 | 证据路径（项目内相对路径） |
| --- | --- | --- | --- | --- |
| A01 | PASS | 按 README 脚本启动（健康检查 200、页面可达）→ 停止脚本按 pid 正常终止；`npm run build` 与后端启动退出码 0 | 命令 + 浏览器 | evidence/a01_start_stop_log.txt；evidence/tests/ui_build_output.txt；evidence/browser/a01_dashboard.png |
| A02 | **BLOCKED** | Windows Sol：真实握手 + 真实回合（"PONG"）成功，用量快照 14557 tokens；`/api/env/adapters` 显示 PASS。WSL DeepSeek：探测返回 BLOCKED（wsl.exe 环境策略），无法验证 | 真实 | evidence/e0/live_sol_minimal_turn.txt；evidence/acceptance/server_acceptance.json（A02_adapters） |
| A03 | PASS | 真实实验：新线程 B 对暗号回答 UNKNOWN（隔离）；新进程续接线程 A 回答 ALPHA-7（续接稳定）；切 medium 档位后同线程仍答 ALPHA-7（历史保留）。线程/回合号齐全 | 真实 | evidence/e0/a03_session_isolation_resume_effort.json |
| A04 | **BLOCKED** | 由产品（HTTP→控制器→适配器）发起真实 Goal：真实 Sol 规划成功（7 条验收标准、3 个任务，用量 15925 tokens 入账，exactness=reported）；启动执行后 Worker 适配器返回 ADAPTER_BLOCKED（wsl.exe [WinError 5]），Run FAILED、Goal PAUSED，链路与因果完整。完整真实闭环未通过 | 真实 | evidence/a04/real_goal_attempt.json |
| A05 | PASS | 确定性模拟：Run1 测试失败（pytest exit 1，真实子进程执行）→ Review FAIL citing 证据 → 计划 v2 → Run2 修复 → pytest exit 0 → Review PASS → COMPLETED；全部记录 mode=simulation | 模拟（含真实证据采集） | evidence/tests/pytest_output.txt（test_full_simulation_loop…）；evidence/browser/a04_completed.png |
| A06 | PASS | ①快照漂移：审阅后工作目录变化 → Python 拒绝完成（applied_action=blocked_snapshot_drift，Goal 保持 READY）；②PASS 未引用本轮证据 → 降级 UNKNOWN 且不完成 | 模拟 | pytest 用例 test_evidence_and_review.py（两个用例） |
| A07 | PASS | 预算 5000：plan 1800 + run1 3500 = 5300 ≥ 5000 → 门禁 CLOSED（usage_settlement），自动验收被拒（review_admission 记录）→ 后续 start/resume 均 409；**重启后门禁仍 CLOSED**（新进程重读数据库）；`budget/resume`（注明批准+额度调至 20000）→ review → run2 → COMPLETED | 模拟 + 重启验证 | server_acceptance.json（A07_budget）；pytest test_budget.py::test_budget_100_percent… |
| A08 | PASS | 同 thread 相同累计快照仅记一次（去重键，重复不扣量）；增量=差值；累计下降→记录 reset 观察且 exactness=unknown，不按 0 扣减；产品内 by_exactness 分开（真实 reported=15925 / 模拟 simulated） | 模拟（机制）+ 真实（分口径） | pytest test_budget.py::test_usage_dedupe…；server_acceptance.json（A02/A07 usage） |
| A09 | PASS | 同幂等键重复 start → 同 run_id、runs 计数=1；工作目录已有运行中的 Run → 第二次 start 409（"active run…"）；崩溃恢复：遗留 RUNNING → INTERRUPTED（error_class=PROCESS_RESTART）且不自动重发 | 模拟 + HTTP | server_acceptance.json（A09_idempotency）；pytest test_run_lifecycle.py |
| A10 | PASS | ①产品取消：长任务 Run 经 stop_requested → INTERRUPTED，只影响该 Run；②真实原生取消：turn/interrupt 后真实回合返回 interrupted（duration≈5.0s） | 模拟 + 真实 | pytest test_run_lifecycle.py::test_single_writer_slot_and_cancel；evidence/e0/a10_native_interrupt.txt |
| A11 | PASS | 真实浏览器：Goal 完成（runs=2）后刷新页面，前后 runs=2 且状态一致（无新 Run）、SSE 游标恢复显示历史事件 | 浏览器 | evidence/browser/browser_verify_result.json（steps.A11）；a06_after_refresh.png |
| A12 | PASS | Registry/项目允许/会话选择/运行冻结分别记录；两个会话可见集合不同；重复运行观测状态为 configured+provided，**没有** invoked_observed/loaded_observed（不冒充调用）。**限制**：原生运行时的严格 Skill 隔离未验证，详见 §7 | 模拟 + HTTP | pytest test_skills_wiki.py；evidence/browser/a07_skills.png |
| A13 | PASS | 显式导入记录来源+哈希+scope；正文读取限工作目录；跨工作目录读取与越界路径均被拒绝并留 wiki.denied 事件（先拒绝后读取） | 模拟 + HTTP | pytest test_skills_wiki.py::test_wiki_import…；evidence/browser/a08_wiki.png |
| A14 | PASS | Quick 优化输出原文/优化稿/差异；Goal Review 在闭环内产出；全链复盘输出 Decision→Run→Review 因果链与效率指标（返工 1/2、首次未通过、单位里程碑 10200 tokens）；Token Audit 输出事实/推断/建议并声明不计量不放行 | 模拟（确定性） | evidence/acceptance/a14_postmortem.md、a14_token_audit.md、a14_optimize.md；pytest test_workflows.py |
| A15 | PASS | 无令牌 401、错令牌 401、跨源 Origin 403、本机 Origin 200；持久数据扫描无 reasoning/凭据字段（reasoning 事件在白名单层面被丢弃）；仅监听回环 | 模拟 + HTTP | server_acceptance.json（A15_boundary）；pytest test_auth_and_privacy.py |

## 5. 一个真实 Goal 的完整证据

**Goal：`goal_cc3f0c49052a`（mode=real，「真实闭环演示：实现 normalize_tags」）**

- 启动方式：产品自身（脚本 `backend/scripts/live_real_goal.py` 走与浏览器相同的 HTTP API；浏览器路径在同一界面的「真实模式」入口）。
- 真实 Sol 规划：新线程 `01a14141-e3fc-…`（app-server 原生），`goal.planned` 事件；产出 7 条验收标准（C1–C7）、3 个任务（含验证命令），冻结为 plan v1；
- **真实计量**：UsageEvent exactness=reported，累计 15925 tokens（provider=openai，来自 thread/tokenUsage/updated 快照增量）；
- 执行段：Run `run_388e47d5ec35` → Worker 适配器（WSL）`availability()=BLOCKED` → Run FAILED（error_class=ADAPTER_BLOCKED），Goal PAUSED，completion_note 逐字记录阻碍；
- 因果链：goal.created → session.resumed(sol) → error(protocol) → system.note → run.queued → run.starting → run.failed（完整事件在 evidence/a04 的 bundle 中）；
- 状态应用：全部由 Python 控制器完成（先准入后启动，失败后不自动重试并暂停）；
- **真实闭环结论：BLOCKED**（Sol 段真实通过；WSL 执行段无法在本环境运行；验收段因无执行结果未发生——不以模拟结果填充本节）。

**真实回合统计（全部为最小额度实验）**：共约 10 个真实回合（2×PONG 验证、4×A03 会话实验、1×中断实验、1×A04 规划、另有 1 个探测回合与 1 次被中断回合）。留档实测：PONG 回合 14557 tokens/次；A04 规划 15925 tokens（唯一进入产品计量记录的回合）；中断回合未产生用量报告（记 unknown，非 0）。未设置预算上限，未使用任何未经批准的数字；未输出凭据内容。

## 6. 模拟与异常验证

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| 失败→重规划→修复→验收（确定性） | Run1 result=failed（真实 pytest exit 1）→ Review FAIL→replan → plan v2 → Run2 result=completed（pytest exit 0）→ Review PASS→completed；全程 mode=simulation、exactness=simulated | evidence/tests/pytest_output.txt；evidence/browser/a04_completed.png |
| 预算 100% | gate CLOSED（持久）、Review 准入被拒、start/resume 409、重启后仍 CLOSED、显式恢复+调额后完成 | server_acceptance.json A07；pytest test_budget.py |
| 重复启动 | 同幂等键 second=duplicate、runs=1；运行中重复启动 409 | server_acceptance.json A09 |
| 用量重复/迟到/重置 | 重复快照不扣量；增量提取；重置观察记 unknown | pytest test_usage_dedupe… |
| 版本/快照不一致 | 快照漂移阻止完成；无证据 PASS 降级 | pytest test_evidence_and_review.py |
| 刷新重连 | 浏览器实测 runs 不变、显示恢复 | browser_verify_result.json A11 |
| 取消 | stop_requested→INTERRUPTED；原生中断 interrupted | pytest + a10_native_interrupt.txt |
| 崩溃恢复 | RUNNING→INTERRUPTED、不自动重发、预算锁保留 | pytest test_crash_recovery… |

## 7. 实现与设计差异

| # | 实际选择 | 原因 | 影响与验证 |
| --- | --- | --- | --- |
| 1 | 启动脚本采用前台运行（关窗即停），而非 `start /min` 后台隐藏 | 沙箱会回收游离子进程；前台模式在用户环境同样稳健且行为可预期 | 已实测启动/停止；stop 脚本按 pid 兜底 |
| 2 | 默认使用桌面版原生 `codex.exe` 0.162.0-alpha 而非 npm 包装器 0.153.4；协议 schema 按原生版生成 | 桌面登录态与真实运行时一致；原生版协议为包装器超集 | 真实回合实测通过；`AGENTPROJ_CODEX_BIN` 可覆盖 |
| 3 | outputSchema 启用 OpenAI strict 模式（additionalProperties=false、全量 required），并对拒绝 schema 的运行时提供**一次**无 schema 回退 | 实测严格模式为必需，否则真实 API 拒绝（首轮规划曾因此失败，已修复并有事件留痕） | 真实规划已通过（§5） |
| 4 | Skill **原生运行时隔离未验证**，仅实现 Registry/允许/会话选择/Run 冻结/观测状态；UI 与报告不宣称隔离完成 | 设计允许"无法严格隔离时保留阻塞或明确限制"；本环境无法做 WSL 侧验证 | 观测状态严格区分 configured/provided/unknown |
| 5 | Review 应用前在 apply 时刻重算工作目录快照比对（比设计更严格） | 防"审阅期间被修改"的完成 | 有专门用例 |
| 6 | 演示工作目录：每个 demo Goal 独立子目录并注册为独立 workspace（单写入槽以 workspace 为粒度） | 避免演示互相污染 | 与"一个工作目录一个写入 Worker"一致 |
| 7 | 工作流在模拟模式下为确定性实现（规则式），真实模式才调用模型分析；Token Audit 以程序事实为主 | 不为看板隐式调用模型；分析计入预算的前提是真实调用 | A14 证据 |
| 8 | E2 的顺序/同步测试模式（AGENTPROJ_SYNC_MODE） | 使测试确定性；不影响正常异步运行 | 仅测试使用 |
| 9 | 真实管理约定：中断后无用量报告记 unknown；WSL 残留进程核验（pgrep）已实现但依赖 WSL 未能实测 | 环境阻碍 | §8 |

用户确认决定 / 实现默认的区分沿用执行计划：本报告 §7.1–9 均为实现默认或兼容性调整，未改写任何用户逐字决定。

## 8. 剩余问题与解除方法

1. **WSL/DeepSeek 真实执行不可用（主阻碍）**
   现象：`wsl.exe` 启动即被程序黑名单拒绝（WinError 5），Worker 探测返回 BLOCKED。
   影响：真实闭环未通过（A02 半、A04 未过）；Skill 原生隔离与 WSL 路径映射同样无法实测。
   已尝试：直接调用、Python subprocess、服务内探测——均为同一策略拒绝；按沙箱规则不再绕过。
   解除：用户在 Security Center → Command Security → Program Blacklist 移除 `wsl.exe`（或到无限制环境运行），然后按 README 创建 `real` Goal 重跑 `backend/scripts/live_real_goal.py` 即可。
2. **WSL 内 Codex/DeepSeek 配置与登录状态未知**（未读取凭据）。解除：用户确认发行版内 `codex` 可用且已按 DeepSeek 官方文档配置 provider。
3. **本机 pip 镜像不可用**（清华源无响应）。已规避：脚本与文档固定官方 PyPI。
4. **agent-browser CLI 守护进程在沙箱中不稳定**，已改用 playwright-core + 本机 Chrome 的自控脚本（`scripts/browser_verify.mjs`，可复跑）。
5. **Skill 原生隔离、WSL 残留进程核验**：随第 1 项解除后复测。
6. 以上问题使整体只能为 PARTIAL_BLOCKED：真实闭环未通过时不得报 COMPLETE；同时不把模拟 PASS 记为真实结果。

## 9. 给原聊天的简短摘要

- 完成状态：**PARTIAL_BLOCKED**（工程可运行、模拟闭环与异常场景全过、真实 Sol 段实测通过；WSL 段被本机安全策略阻止）。
- 启动：`scripts\start_workbench.bat` → `http://127.0.0.1:8787`；停止 `scripts\stop_workbench.bat`；测试 `scripts\run_tests.bat`（15 passed）。
- 真实链结果：真实 Sol 规划 + 计量（15925 tokens）成功；WSL DeepSeek 执行 BLOCKED（wsl.exe 黑名单）→ 真实闭环未通过，证据完整可复核。
- 验收：A01/03/05/06/07/08/09/10/11/12/13/14/15 = PASS；A02 = BLOCKED（Windows 半通过）；A04 = BLOCKED（真实规划完成、执行段受阻）。
- 主要差异：见 §7（启动模式、原生 exe、strict schema、Skill 隔离未验证等）。待处理项：解除 wsl.exe 限制后重跑真实闭环（具体步骤见 §8）。
- 报告与机器结果：`docs/reports/MVP_EXECUTION_REPORT.md`、`docs/reports/MVP_EXECUTION_RESULT.json`、`docs/reports/ENVIRONMENT_REPORT.md`、`docs/reports/evidence/`。
