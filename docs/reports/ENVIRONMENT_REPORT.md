# 环境与能力报告（ENVIRONMENT_REPORT）

日期：2026-10-15（本机时区 America/Los_Angeles）。执行 Agent：本地 WorkBuddy 会话（Windows 沙箱环境）。
本报告只记录不含秘密的事实；不包含任何令牌、凭据或原始推理内容。状态口径：PASS / FAIL / BLOCKED / NOT_RUN。

## 1. 主机与工具链

| 项目 | 实测值 | 状态 | 证据 |
| --- | --- | --- | --- |
| 操作系统 | Windows 10 Enterprise（OS 内部版本 10.0.19045），主机名已脱敏 | PASS | `systeminfo` 输出（见 evidence/e0/） |
| 工作目录 | `C:\Users\Administrator\Desktop\tool\agentProj` | PASS | 目录列表 |
| 磁盘空间 | C: 可用约 102 GB | PASS | `df -h` 输出 |
| Git | git 2.55.0.windows.3 可用；**项目目录当前不是 Git 仓库** | PASS（Git 本身） | `git status` 报 `not a git repository`；按计划用文件清单/哈希定位代码状态 |
| Python（托管） | 3.13.14（`...\.workbuddy\binaries\python\versions\3.13.12\python.exe`，路径目录名与版号不同属正常） | PASS | `python --version` |
| Python（系统） | 3.14.3（`C:\Python314\python.exe`） | PASS | `where python` |
| pip | pip 26.1.2 可用 | PASS | `pip --version` |
| Node（托管） | v22.22.2 | PASS | `node --version` |
| Node（系统） | v24.14.1（`C:\Program Files\nodejs`） | PASS | `where node` |
| npm | 10.9.7；registry 连通（`npm ping` PONG 929ms） | PASS | `npm ping` 输出 |
| curl | 8.13.0 | PASS | `curl --version` |

## 2. Windows Codex（Sol 角色）

| 项目 | 实测值 | 状态 | 证据 |
| --- | --- | --- | --- |
| Codex CLI（npm 包装器） | `codex-cli 0.153.4`（`C:\Program Files\nodejs\node_global\codex`，node 包装脚本） | PASS | `codex --version` |
| Codex 原生可执行文件 | `0.162.0-alpha.17.2`，位于 `C:\Users\Administrator\AppData\Local\OpenAI\Codex\bin\9614f1d9b40d9c4f\codex.exe`（桌面应用同款，config `CODEX_CLI_PATH` 指向） | PASS | `codex.exe --version` |
| 登录/认证 | `codex login status` → `Logged in using ChatGPT`；app-server `account/updated` 事件返回 `authMode=chatgpt, planType=plus`。未读取、未输出任何凭据内容 | PASS | 探针输出（见 §4） |
| App Server 可用性 | `codex app-server --listen stdio://` 可启动；`generate-json-schema` 可导出协议 schema（两种版本合计 105 个客户端方法） | PASS | protocol-schema / protocol-schema-native（devtools） |
| 原生握手（最小试验） | `initialize` → 返回 userAgent/codexHome/platform；`model/list` → 7 个模型；`thread/start` → 返回 threadId `01a14114-…`；期间收到 `thread/started`、`mcpServer/startupStatus/updated` 等原生通知 | PASS | `.agentproj/devtools/probe_appserver.py` 输出 |
| 可用模型（含推理档位） | `gpt-6.1-sol`、`gpt-6-astra`、`gpt-6-sol`、`gpt-6-luna`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`；档位覆盖 low/medium/high/xhigh/max（部分含 ultra） | PASS | `model/list` 结果 |
| 当前默认配置 | `config.toml`：model=`gpt-5.6-luna`，reasoning=low，1M 上下文。项目工作台不改动该全局配置；运行时经 app-server 参数覆盖模型 | 事实记录 | `~/.codex/config.toml` |
| 项目目录信任 | 工作目录不在 config.toml 的 trusted 列表；本次不改动全局配置。真实执行使用项目内演示工作目录，必要时通过 app-server 参数或运行环境处理 | 事实记录 | config.toml |

## 3. WSL 与 DeepSeek（Worker 角色）

| 项目 | 实测值 | 状态 | 证据 |
| --- | --- | --- | --- |
| `wsl.exe` 调用 | 被当前执行环境的**程序黑名单（安全策略）阻止**：`PROGRAM BLOCKED BY SECURITY POLICY: wsl.exe (C:\WINDOWS\system32\wsl.exe)`；沙箱提示需由用户在 Security Center → Command Security → Program Blacklist 移除后才能放行 | **BLOCKED** | e0 证据文件（命令与原文错误） |
| WSL 发行版清单/版本 | 无法查询（依赖 wsl.exe） | NOT_RUN | — |
| WSL 内 Codex 版本 | 无法查询。旁证：`~/.codex/bin/wsl/` 下存在为 WSL 注入的 Linux 版 `codex` 与 `codex-code-mode-host` 二进制（桌面应用注入物，非本机 WSL 实际安装证据） | BLOCKED | 目录列表 |
| Windows↔WSL 路径映射 | 无法实测。方案预置映射函数 `C:\…` → `/mnt/c/…`（标准映射，标注为未验证） | BLOCKED | — |
| WSL DeepSeek 接入 | Windows 侧 config.toml 未配置 DeepSeek provider；既定路线为「WSL 内 Codex + DeepSeek」，依赖 wsl.exe → BLOCKED。**不静默更换执行模型** | **BLOCKED** | — |
| DeepSeek Harness（dsh） | 另发现 `dsh 0.1.5-rc.3`（DeepSeek Harness profile 启动器）存在于本机 PATH，按设计仅记录，不用于替代既定 WSL 路线 | 事实记录 | `dsh --version` |

**影响与最小解除方法：** 真实闭环中「WSL Codex/DeepSeek 执行」一段在本环境无法运行，属外部环境阻碍。用户在本机（不受该黑名单限制）按 README 启动工作台并确保 Remove "wsl.exe" from the blacklist（或直接在有 WSL 的终端验证）后，Worker Adapter 即可按同一代码路径执行。见 `MVP_EXECUTION_REPORT.md` §8。

## 4. 协议核验（基于原生 exe 生成的 JSON Schema）

- 客户端方法（105 个）含本项目所需全部核心方法：`initialize`、`thread/start`、`thread/resume`、`turn/start`、`turn/interrupt`、`model/list`、`skills/list`、`account/read`、`thread/read`、`thread/turns/list` 等。
- 服务端通知（81 个）含：`thread/started`、`turn/started`、`turn/completed`、`item/started`、`item/completed`、`item/agentMessage/delta`、`item/commandExecution/outputDelta`、`item/fileChange/patchUpdated`、`thread/tokenUsage/updated`、`item/reasoning/*`（**过滤项，不落盘**）等。
- `turn/start` 支持参数含：`threadId`、`input[]`（text/image/…）、`model`、`effort`、`cwd`、`outputSchema`（可约束最终助手消息为 JSON）、`approvalPolicy`、`sandboxPolicy`。
- 传输：`stdio://`（默认），JSONL（每行一条 JSON-RPC 消息），实测握手成功。
- 生成物路径：`.agentproj/devtools/protocol-schema/`（npm 包装器 0.153.4）与 `.agentproj/devtools/protocol-schema-native/`（原生 0.162.0-alpha）。工作台默认使用原生 exe（可用环境变量覆盖）。

## 5. 结论（最终版）

- Windows Sol 侧：**真实接入可用（PASS）**，认证就绪、模型与推理档位按运行时查询获取；工作台以其作为规划/验收角色。真实证据：`docs/reports/evidence/e0/live_sol_minimal_turn.txt`（真实回合 PONG，用量快照 14557 tokens）、`docs/reports/evidence/e0/a03_session_isolation_resume_effort.json`（隔离/续接/切强度）、`docs/reports/evidence/e0/a10_native_interrupt.txt`（原生中断）。
- WSL DeepSeek 侧：**BLOCKED**（外部环境黑名单，WinError 5）。代码按可替换 Adapter 实现并保留独立开发与模拟验证；不替换模型冒充通过。真实 Goal 的证据：`docs/reports/evidence/a04/real_goal_attempt.json`（真实规划成功、worker 段 ADAPTER_BLOCKED）。
- 浏览器与产物验证：`docs/reports/evidence/browser/`（10 张截图 + `browser_verify_result.json`）；代码状态：`docs/reports/evidence/code_manifest.sha256.txt`（57 个文件哈希；项目非 Git 仓库）。
- 测试：15 passed（`docs/reports/evidence/tests/pytest_output.txt`）。
- 完整结论、差异与解除方法见 `MVP_EXECUTION_REPORT.md` 与 `MVP_EXECUTION_RESULT.json`。
