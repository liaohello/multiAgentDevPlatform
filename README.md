# agentProj 本地 Web 工作台（第一版实现）

本地 AI 开发工作台：浏览器输入 Goal → Windows Sol 规划 → Windows Python 冻结任务并准入 → WSL Codex/DeepSeek 执行 → 证据采集 → Sol 验收 → 完成/修复/暂停 → 网页展示结果、Token 与证据。

本版本（2026-10-15）已交付可运行实现（E0–E7）。设计资料仍保留在 `docs/design/`；模型阅读约定见 [AGENTS.md](AGENTS.md)，项目记忆见 [MEMORY.md](MEMORY.md)，资料索引见 [WIKI.md](WIKI.md)。

> 交付状态：**PARTIAL_BLOCKED**。真实 Windows Sol 接入与真实规划已验证通过；WSL 内置 Codex/DeepSeek 执行段因本机执行环境把 `wsl.exe` 列入程序黑名单而无法在本环境验证（代码已实现并在界面/报告中准确显示 BLOCKED）。完整链路已用确定性模拟模式端到端验证。详见 [执行报告](docs/reports/MVP_EXECUTION_REPORT.md)。

## 1. 目录结构

| 位置 | 内容 |
| --- | --- |
| `backend/` | FastAPI 后端（Windows Python 唯一调度中心：状态、预算、证据、适配器、工作流） |
| `backend/app/` | 应用代码（Controller / Budget / Evidence / Adapters / Wiki / Skills / Workflows / API） |
| `backend/tests/` | pytest 测试套件（15 项，覆盖闭环、预算、幂等、恢复、边界） |
| `backend/scripts/` | dev 验证脚本（真实 Sol 最小试验、会话隔离试验、真实 Goal 尝试、验收采集） |
| `ui/` | React + TypeScript + Vite 前端（构建后由后端伺服，无需常驻 dev server） |
| `scripts/` | 启动 / 停止 / 开发 / 测试 批处理脚本 |
| `.agentproj/` | 运行数据：`state.sqlite`、Goals/证据文件、`runtime.json`（含本次会话令牌与 pid） |
| `docs/reports/` | 环境报告、执行报告、机器摘要与全部验收证据 |

## 2. 安装与启动

前置：Windows 10/11、Python 3.13+、Node.js 18+（仅构建前端需要）。首次运行需联网安装依赖。

**生产式启动（推荐）**

```bat
scripts\start_workbench.bat
```

该脚本会：① 若无 `ui/dist` 则自动 `npm install + npm run build`；② 若无 `backend\.venv` 则创建虚拟环境并 `pip install -r backend\requirements.txt`（即用 `-i https://pypi.org/simple`，本机 pip 镜像曾不可用）；③ 启动后端并打开浏览器。

- 网页地址：`http://127.0.0.1:8787`（页面自动注入本次会话令牌）。
- 停止服务：关闭该窗口或 Ctrl+C；也可运行 `scripts\stop_workbench.bat`（按 `runtime.json` 中 pid 只停止本应用进程）。

**开发模式（前后端分离热更新）**

```bat
scripts\dev_backend.bat   :: 后端 http://127.0.0.1:8787（--reload）
scripts\dev_ui.bat        :: 前端 http://127.0.0.1:5173（/api 代理到 8787）
```

**测试**

```bat
scripts\run_tests.bat     :: 等价于 backend\.venv\Scripts\python.exe -m pytest -q
```

当前结果：`15 passed`。

**依赖锁定**：`backend/requirements.txt`（直接依赖固定版本）+ `backend/requirements.lock.txt`（pip freeze 全量）；前端 `ui/package-lock.json`。

## 3. 使用方式（浏览器）

1. 左侧「新建 Goal」：填写标题与原始需求；选择模式：
   - `simulation`（确定性模拟，无需任何模型账户）：场景可选 失败→重规划→修复→完成 / 预算停止 / 长任务取消；
   - `real`（真实模式）：Windows Sol 真实规划与验收；执行角色为 WSL 内 Codex（DeepSeek）。可填 Sol 模型与推理档位（留空用运行时默认）。
   - 可选择「隔离演示目录（自动创建）」或已注册的工作目录；预算留空=不设上限。
2. 依次使用按钮：**Sol 规划 → 开始执行 → （自动）验收**；也可手动 审阅/暂停/恢复/取消。
3. 右侧实时流（Sol / Worker 双泳道）、Token 曲线、事件时间线；SSE 按游标恢复，刷新页面不会重发任务。
4. 页签：`Skills`（注册表允许、会话选择、Run 冻结与观测状态）、`Wiki`（元数据索引、显式导入、受控正文读取）、`复盘与审计`（Quick Prompt 优化 / 全链复盘 / Token Audit）、`环境与能力`（Windows/WSL 适配器探测、运行时模型列表、会话配置调整）。

## 4. 关键行为（与设计对应）

- **单一调度中心**：所有启动、重试、恢复都经过同一准入：目标状态 + 预算门禁 + 工作目录单写入槽 + 幂等键。
- **预算 100% 停止**：达到阈值即持久关闭门禁，阻止下一执行轮与自动验收；重启不清锁；恢复需 `budget/resume` 显式批准（可调额度）并留痕。
- **验收不越权**：Sol 只输出逐项建议（PASS/FAIL/BLOCKED/UNKNOWN）；Python 校验版本、证据归属与工作目录快照一致性后才应用状态；快照漂移会阻止完成。
- **证据由程序采集**：验证命令白名单执行、退出码与输出落盘、文件快照与变更清单；Worker 自述仅为候选信息。
- **事件过滤**：白名单事件类型入库；推理项与凭据不进入日志/数据库/界面。
- **本地访问边界**：仅监听回环；每次启动生成会话令牌（页内注入，`.agentproj/runtime.json` 可查）；跨源 Origin 拒绝。
- **两种模式严格分开**：模拟用量 `exactness=simulated`，真实用量 `reported`，同一 Goal 不混用；界面与报告显式标注。

## 5. 配置

环境变量（均可选）：`AGENTPROJ_PORT`、`AGENTPROJ_CODEX_BIN`（默认自动探测桌面版原生 codex.exe）、`AGENTPROJ_WSL_DISTRO`、`AGENTPROJ_WSL_CODEX_CMD`、`AGENTPROJ_TURN_TIMEOUT`、`AGENTPROJ_MAX_AUTO_ROUNDS`、`AGENTPROJ_DATA_DIR`、`AGENTPROJ_TOKEN`（固定令牌，便于集成）。

真实模式前置：Windows 需已登录 Codex（本机实测 ChatGPT 账号）；WSL 段需在发行版内安装并登录 Codex（DeepSeek Provider 按官方 Codex 接入配置），且 `wsl.exe` 可被后端进程调用。

## 6. 相关文档

- 环境与能力：[docs/reports/ENVIRONMENT_REPORT.md](docs/reports/ENVIRONMENT_REPORT.md)
- 执行报告（供原聊天审阅）：[docs/reports/MVP_EXECUTION_REPORT.md](docs/reports/MVP_EXECUTION_REPORT.md)
- 机器摘要：[docs/reports/MVP_EXECUTION_RESULT.json](docs/reports/MVP_EXECUTION_RESULT.json)
- 验收证据索引：[docs/reports/evidence/](docs/reports/evidence/)（含浏览器截图、真实调用输出、代码清单哈希）
- 设计与实施计划：[docs/design/IMPLEMENTATION_PLAN.md](docs/design/IMPLEMENTATION_PLAN.md)、[docs/CODEX_HANDOFF.md](docs/CODEX_HANDOFF.md)
