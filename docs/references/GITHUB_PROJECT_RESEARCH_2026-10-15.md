# GitHub 参考项目调研

检索日期：2026-10-15（America/Los_Angeles）。范围：现有全部设计主题，包括 Windows/WSL 工作台、Agent 接入、Goal、Skill、Wiki、预算、Ops 和复盘。调研结论用于[整体设计审阅稿](../design/WORKBENCH_DESIGN.md)，不代表组件已安装、已在本机运行或已获用户采纳。

## 1. 方法与证据等级

通过公开 GitHub 页面、仓库 API、固定 commit 的原始文件及官方产品文档核验。记录了 16 个仓库的元数据/版本线索，读取 30 份固定版本文件；读取深度不相同，具体见 [机器清单](github-research-2026-10-15.json)。没有运行下载脚本、安装 Skill、调用付费模型或进行性能评测。

下面“已核对”表示实际读到文档或实现，不表示通过本机兼容性实验。没有依据 Star 数给成熟度打分；维护日期仅是本次快照。引用文件链接固定到本次读取的 commit，后续升级需重新核验。

## 2. 优先参考的项目

| 项目 | 核对内容 | 在本项目中借鉴什么 | 边界与取舍 |
| --- | --- | --- | --- |
| [openai/codex](https://github.com/openai/codex) | App Server 官方文档、Thread/Turn/Skills/Usage 协议类型 | 优先使用结构化接入，保存本地 Session 与原生 Thread 映射 | 原生协议版本需固定；不从 TUI 文本推断验收 |
| [lulu-sk/CodexFlow](https://github.com/lulu-sk/CodexFlow) | Windows/WSL 工具、会话关系代码与工作台说明 | 项目/会话组织、路径映射、历史与 Git 交互 | 借鉴界面和路径处理；它的 Electron/PTY 主进程不作为本项目调度中心 |
| [pingdotgg/t3code](https://github.com/pingdotgg/t3code) | Codex Adapter 与 Token 聚合代码 | 将原生事件统一为产品事件；累计计量与单轮计量分开 | 不搬入其完整 TypeScript/Effect 调度与全部 Provider 抽象 |
| [nashory/agx](https://github.com/nashory/agx) | 架构文档、Windows 与工作副本说明 | 单一运行时拥有状态、生命周期、恢复；前端只发命令 | 其终端活动状态不能代替 Goal 验收；不引入 Go 守护程序和 tmux 控制层 |
| [OdinMB/ops-workflow](https://github.com/OdinMB/ops-workflow) | scaffold 与 tidy 指令 | 索引、计划、参考资料、交付成果分工；孤立/失效链接检查 | 不采用其自主发现任务和执行循环；目录层次按实际规模建立 |
| [c-pompa/operations-hermes-desktop-plugin](https://github.com/c-pompa/operations-hermes-desktop-plugin) | 插件目录记录、页面文档、后端接口 | Handoffs、Trace、Flow、Activity 的相互跳转 | 仅参考页面和关联方法；独立仓库未发现明确 LICENSE，不直接复制代码；不接入其自动修复和调度动作 |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | Observation 数据模型与 LICENSE | 父子调用关系、耗时、用量细分和计量来源 | 初期只借鉴数据表达，不部署完整服务；核心与 EE 许可有不同边界 |
| [r0x0r/pywebview](https://github.com/r0x0r/pywebview) | 架构与 Windows 安装文档 | Python 后端配轻量桌面窗口的候选路线 | 先以本地 Web 完成闭环；桌面化前验证 WebView2、输入法、文件选择和 SSE |

## 3. 四种工作流的实际来源

旧资料中的几个名称并非独立仓库，直接访问会得到 404；本次已定位为仓库内的 Skill 文件。

| 工作流 | 实际来源 | 已核对的可借鉴内容 | 本项目处理 |
| --- | --- | --- | --- |
| Prompt Optimizer | [getsentry/skills 的 prompt-optimizer](https://github.com/getsentry/skills/blob/f57ada2d0b640406ea7e25b11d636c530e77c58b/skills/prompt-optimizer/SKILL.md) | 先定义任务契约，再列上下文引用和评估候选 | 自定义 Quick / Deep 两档，避免每次消息都完整评估 |
| Goal Review | [tomzx/agents 的 verify-pr](https://github.com/tomzx/agents/blob/698f806de04d92574121473898aba72223789efb/skills/verify-pr/SKILL.md) | 验收项到代码/运行证据的覆盖映射 | 借鉴方法；执行、安装依赖、录制和外部评论能力留在受控执行器 |
| Collaboration Postmortem | [giannimassi/agent-retro](https://github.com/giannimassi/agent-retro/blob/b09bc15e05ea6d757eaa11756ba1ccfd351385dd/SKILL.md) | 会话过程、摩擦、工具输出与成本分析 | 原文件明确面向 Claude Code JSONL；本项目自行设计 Goal 跨会话因果链 |
| Token Audit | [bm629/agent-skills 的 token-optimization](https://github.com/bm629/agent-skills/blob/6f1504cfc0e39fed36f6d7405907231d6474c01d/skills/token-optimization/SKILL.md) | 以完成任务的总成本为目标，分层诊断上下文与工具结果 | 作为分析方法，实际计量和准入由 Python 负责 |

本次没有加载这些远程 Skill 来约束本轮工作，也未执行其中脚本或外部写入操作。其他历史候选如 unslop 的不同来源、Bitwarden retrospecting、define-goal 的具体位置仍需逐项核验，不因本次调研而全部视为已确认。

## 4. Ops 候选的新结论

### dsh-ops 与 FastCtx

[dsh-ops 当前说明](https://github.com/T-Auto/dsh-ops)明确区分 DSH 宿主及 Windows x64 目标；源码许可为 MIT 与 vendored FastCtx 的 Apache-2.0 组合，附带载荷还有各自声明。它不适合作为 WSL Codex 的即装插件。

其引用的 [FastCtx v0.2.6](https://github.com/yc-duan/fastctx/blob/22b40ea324a186a921dfe38c205e3ffacdf6546d/README.md)直接提供 MCP 文件/搜索/命令工具，比搬用整个 DSH 插件更值得做对照实验。但是 [FastCtx 主分支](https://github.com/yc-duan/fastctx)正在重建为多机器 World，不能把主分支与已发布工具版本混同。

建议第一版继续使用 Python + ripgrep + Git；发现可测的输出或调用瓶颈后，再固定发布版本进行对照。搜索完整性、读取范围和截断补取都要计入评测，不能照搬第三方宣传的节省百分比。

### Hermes Operations 的准确位置

通过 [Hermes 插件目录](https://github.com/NousResearch/hermes-agent/blob/b4dcb5c08b6d5808dd5b7fa2b931722ff8b0f97b/plugin-catalog/operations.yaml)定位到了独立 Operations 仓库，目录指向的版本与本次检查的 commit 一致。

它使用 Hermes 的指标库、看板和 Profile，既有观测页面，也有创建/启动任务等操作。由此推导：本项目应重建针对 Goal 因果链的视图，复用自己的事件 ID 和 Python 命令入口，而非嵌入整套插件后再尝试约束它。

### opencode-ops 的准确位置

npm 元数据将 `opencode-ops` 指向 [asychin/opencode-ops](https://github.com/asychin/opencode-ops)，版本线索为 1.2.0，包声明 MIT；已读对应 gitHead 的 README。可参考 SSH 会话和终端状态组织，后期按需实现独立 Adapter，不引入 OpenCode 运行时。

## 5. 直接影响架构的官方核验

1. [Codex App Server](https://learn.chatgpt.com/docs/app-server)提供 Thread/Turn、Skill 发现和用量通知，适合作为自建工作台的结构化接入。会话级 Skill 隔离仍需实验：按 cwd 列表或进程级额外根目录不自动等于独立会话权限。
2. [OpenAI 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)当前只支持 Responses 作为自定义 Provider 的 wire API。[DeepSeek 的 Codex 文档](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)已经给出 Responses 配置与模型目录，因此保留原 WSL Codex + DeepSeek 路线有文档依据，不需要先假定必须加协议代理。工具调用、用量、取消和续接仍未在本机验证。
3. DeepSeek 示例包含展示原始推理和把凭据写入配置的设置。本项目只借鉴 Provider 接入；不照搬原始推理展示，凭据用原生认证或运行时受控注入，不能进入项目记忆与普通事件。
4. [SQLite WAL 文档](https://sqlite.org/wal.html)说明其同主机共享内存前提。由此选择 Windows Python 独占写本地数据库，WSL 只发送结果；不让两端共享写 SQLite 文件。
5. [FastAPI 的流式响应](https://fastapi.tiangolo.com/advanced/custom-response/)足以承载第一版事件流；[微软 WSL 文件系统说明](https://learn.microsoft.com/en-us/windows/wsl/filesystems)支持将路径归属和跨文件系统性能作为明确设计选择。

## 6. 推荐复用层次

直接依赖：经过版本验证的官方 Codex CLI/App Server、常规 Python/前端库；可选 pywebview。设计借鉴：CodexFlow、T3 Code、AGX、ops-workflow、Operations、Langfuse 及四种工作流来源。性能实验候选：固定发布版 FastCtx。后期交互参考：opencode-ops。

优先自行实现的部分是本项目独有的 Goal 版本冻结、Sol↔DeepSeek 因果关系、预算停止与恢复门禁，以及基于证据的 Goal 完成判定。这些不能从终端工作台的“进程结束”状态直接获得。

## 7. 版本与许可记录的用法

完整 commit、文件 SHA-256、读取范围与官方链接在 [JSON 清单](github-research-2026-10-15.json)。GitHub 未识别出许可证不等于仓库没有任何许可条款；本次对 dsh-ops、Langfuse 进一步读了实际 LICENSE。Operations 未发现明确授权文件，因此建议仅作设计参考。后续真要复制代码或打包依赖，再检查被采用的具体文件及其附带声明。
