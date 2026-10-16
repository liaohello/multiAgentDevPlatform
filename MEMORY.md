# agentProj 项目长期记忆

更新：2026-10-15（America/Los_Angeles）。作用域：当前项目。本文件保存可见讨论与实现成果摘要，通过 [AGENTS.md](AGENTS.md) 引导后续模型读取；不是模型账户级的全局记忆或完整聊天历史。

## 目标与当前状态

目标是构建本地 Windows AI 开发工作台，统一需求讨论、Goal 规划、WSL 执行、验收、Wiki、Skill 配置、Ops 工具和 Token 预算。

**最新独立评估：CHANGES_REQUIRED（2026-10-15）。** 原有 15 项测试在标准临时目录复跑通过，前端构建通过；10 组隔离反例确认 7 类问题：迟到/阻塞验收误完成、Wiki 越界及错误正文、重启 Token 重复累计、超时/恢复未确认原生停止、任务始终选择第一项、Skill 提供/撤销未闭合、WSL 自动发行版未绑定。可运行原型成立，阶段可靠性验收尚未通过，不能认为解除 WSL 黑名单即可 COMPLETE。详见 [阶段评估](docs/reports/STAGE_REVIEW_2026-10-15.md)与[复核证据](docs/reports/evidence/stage-review/verification.json)。本轮未修改业务源码、未启动 WSL 或付费模型。

**原执行交付报告（E0–E7，PARTIAL_BLOCKED）**：本地 Web 工作台已可运行，已有规划、执行、证据、验收、预算、最小 Wiki/Skill、复盘与 SSE 界面。启动：`scripts\start_workbench.bat`（http://127.0.0.1:8787），原测试 15 passed。代码位于 `backend/`（FastAPI）与 `ui/`（React/TS/Vite），运行数据在 `.agentproj/`。这些为原交付范围，当前接受程度以独立阶段评估为准。

- **真实闭环未通过**：本执行环境把 `wsl.exe` 列入程序黑名单（WinError 5），WSL/DeepSeek 执行段无法运行；真实 Windows Sol 段已实测通过（握手、真实回合、真实计量；真实规划 Goal `goal_cc3f0c49052a` 记录 15925 tokens）。
- 模拟模式完成完整闭环与全部异常场景（失败→重规划→修复→完成、预算 100% 停止与重启锁定、幂等、崩溃恢复、取消、刷新重连）。
- 原执行方验收自报：A01/03/05–15 PASS，A02/A04 BLOCKED；原报告和机器摘要保留为历史证据。独立评估要求重验 A06/A08/A09/A10/A12/A13 等，不能继续将原 PASS 视为全面接受。

## 已保留的项目约束

以下以既有项目记忆的 R01–R16 为基线；其中早期细节来自历史摘要，不冒充逐字原话。

- Windows Sol 负责讨论、规划、验收、重规划；WSL Codex / DeepSeek 负责执行；Windows Python 负责生命周期、权限、持久状态、预算和恢复。**已在实现中落实为单一准入路径。**
- 工作目录独立；新 Sol 会话不自动继承其他会话历史；切换推理强度保留已有历史。**已以真实实验验证（隔离/跨进程续接/切强度）。**
- 全局 Wiki / 跨工作目录检索需明确授权；Wiki 初期只需标题、摘要、标签和来源路径。已有基础实现，但阶段审查 F02 复现同前缀目录越界、正文根目录解析错误和默认演示目录扫描遗漏，边界待修复。
- 保留可见指令、决定、工具结果、状态、测试证据和最终/暂停报告；大量 WSL 中间文本不全量灌入 Sol，不保存隐藏思维链。**已实现（事件白名单 + 推理项过滤 + 临时增量仅内存展示）。**
- Skill 按项目、会话和单轮选择，不默认加载全部内容；安装、启用、实际调用和有效性分别记录。**已实现配置/提供/观测分层；原生运行时严格隔离未验证，未宣称完成。**
- Goal 全链复盘要解释原始计划、Sol 决策、DeepSeek 执行、反馈、验收和重规划之间的因果关系；缺少证据写 `UNKNOWN`。**已实现（复盘报告输出 Decision→Run→Review 链）。**
- Python 采集用量并执行预算门禁。执行预算达到 100% 禁止自动下一轮，重启保留停止锁的用例通过；F03 同时发现真实累计基线仅存内存，100→重启→150 会记成 250，需修复恢复计量。
- 参考 GitHub 设计，不默认 Fork；优先简单实现。**保持：自研薄实现，无第三方运行时。**

## 本轮实现要点（重要设计痕迹）

- 默认使用桌面版原生 `codex.exe`（0.162.0-alpha），协议 schema 由原生版生成；`AGENTPROJ_CODEX_BIN` 可覆盖。
- outputSchema 为 OpenAI strict 模式（additionalProperties=false + 全量 required），被拒绝时有一次无 schema 回退（真实规划首轮曾因非 strict 失败，已修复）。
- 验收应用前在 apply 时刻重算工作目录快照比对：漂移即阻止完成（比原设计更严格）。
- 每个 demo Goal 独立子目录并注册为独立 workspace；单写入槽以 workspace 为粒度。
- 启动脚本为前台模式（关窗即停）；`stop_workbench.bat` 按 `runtime.json` pid 停止。
- 本机 pip 默认镜像（清华）不可用，脚本固定 `-i https://pypi.org/simple`。
- 沙箱内 `agent-browser` 守护进程不稳定；浏览器验收改用 `scripts/browser_verify.mjs`（playwright-core + 本机 Chrome）。

## 下一步与未定事项

- **前端重设计需求（2026-10-15）**：用户提供 PPT 布局截图，希望保留左侧项目/会话导航、主区双 Agent 对话记录和导入入口；点击 Dashboard 显示当前会话的用量/分析视图，借鉴 Langfuse；每个会话还需要执行时间线与异常恢复。此处记录的是新增需求，尚未实现或完成设计审阅。左栏具体入口、图中 `db` 的含义，以及 UI 协作会话与单 Agent Session/Goal 的映射仍需讨论。

- **下一轮先做稳定性修复**：按阶段评估关闭 F01–F07，并将反例加入回归；WSL 黑名单阻碍保留为独立环境问题，不尝试绕过。完成缺陷修复后，在用户允许的环境、有效 DeepSeek 配置与明确测试预算下重跑真实闭环，再逐项重验 A01–A15。
- WSL 内 Codex/DeepSeek 配置与登录状态需用户确认（工作台不读取凭据）。
- 待复测：WSL 路径映射（/mnt/c 标准映射已内置并标注未验证）、WSL 残留进程核验（已实现代码路径）、Skill 原生隔离实验。
- 首版范围之外（后续按需）：桌面壳、多 Worker Worktree、SSH/CI、Deep Optimize 多候选、第三方 Skill 商店。

## 按需继续阅读

进入 [WIKI.md](WIKI.md) 选择当前任务主题。实现细节读 README 与报告；协议与实现边界读 [数据约定](docs/design/DATA_CONTRACTS.md)；历史措辞只在核对时读对话原文与备份。
