# agentProj：Ops 能力扩展设计记录

记录日期：2026-10-15（America/Los_Angeles）  
项目：Windows Sol + WSL DeepSeek 开发工作台  
当前文件：`docs/design/OPS_CAPABILITY_DESIGN.md`  
状态：讨论方案记录，尚未实施或验收。

本文整理用户提供的 Ops 集成想法，作为原项目记忆的增补。保留方案中的适配判断与优先级；插件版本、平台兼容性、性能及接口说法均未在本次联网复核，也未安装任何插件。

**2026-10-15 后续调研更新：**上句描述最初归档状态。现已公开核对 dsh-ops、Hermes Operations 和 opencode-ops 的来源与部分文件，未安装、运行或验证性能。最新依据见 [GitHub 调研](../references/GITHUB_PROJECT_RESEARCH_2026-10-15.md)，集成方式见 [整体设计审阅稿](WORKBENCH_DESIGN.md)；以下未被更新的兼容性问题仍保留为待验证。

## 1. 核心决定与设计方向

**Windows Python 保持唯一 Agent 调度中心。Ops 只扩展操作能力，不接管 Agent 生命周期、自动轮次、权限、预算或恢复控制权。**

采用“借鉴设计、按需适配”的路线，避免直接安装并启用全部同名 `ops` 插件，也不引入第三套 Agent 调度框架。

优先研究两个方向：

- `ops-workflow`：任务状态、计划、参考资料和交付成果的组织方式。
- Hermes `operations`：Agent 交接、调用链、活动、模型流量与指标的可视化。

`dsh-ops` 先作为文件工具性能优化候选；`opencode-ops` 的 SSH、终端和看板设计留待后续远程工程扩展阶段参考。

## 2. 四类候选的适配结论

下表是本次保留的**设计判断**，不是经过本机验证的兼容性结论。

| 候选 | 讨论中的来源 | 适配判断 | 推荐复用内容 | 接入限制 |
| --- | --- | --- | --- | --- |
| `ops-workflow` | `OdinMB/ops-workflow` | 高 | state、backlog、references、artifacts、plans | 不接入其自主任务循环 |
| `dsh-ops` | `T-Auto/dsh-ops` | 有条件 | 搜索输出压缩、批量文件操作、工具结果大小控制 | 先核验宿主与平台，再做独立评测 |
| `opencode-ops` | npm 元数据定位到 `asychin/opencode-ops` | 中 | 多 SSH 会话、终端、GitHub Actions、Web Dashboard | 已读包版本对应 README；不引入 OpenCode 运行时 |
| Hermes `operations` | `c-pompa/operations-hermes-desktop-plugin` → `plugins/operations` | 很高 | Handoffs、Trace、Flow、Activity、Notifications | 已核对目录与后端；参考观测设计，不直接接入其专用后端 |

### 2.1 宿主与模型必须分开判断

当前执行端的讨论基线为：

`WSL Ubuntu → Codex CLI → DeepSeek 模型`

`dsh-ops` 面向的宿主是 DeepSeek Harness（DSH）。使用相同模型，不意味着运行时插件接口兼容；不能因为 Codex 使用 DeepSeek 模型，就推断 DSH 插件可直接装进 WSL Codex。

2026-10-15 已核对其公开 README：`0.3.0` 面向 Windows x64 与 DSH `0.2.0-rc.2`，不是 WSL Codex 即装插件。本机未运行；部署前仍需核对实际版本。其来源中的 FastCtx 可单独作为 MCP 文件工具候选，但应固定发布版评测，不使用正在重建的主分支替代发布实现。

同样，Hermes Operations 的指标数据库、看板和桌面运行时依赖，也需在实际研究时核对版本与边界。

## 3. 分别借鉴什么

### 3.1 ops-workflow：任务与资料组织

参考以下职责划分：

| 概念 | 在本项目中的用途 |
| --- | --- |
| state | Goal、阶段和运行的当前状态 |
| backlog | 尚未进入执行轮次的任务与问题 |
| references | 计划和决定所依据的资料与证据索引 |
| artifacts | 代码变更、报告与其他交付成果 |
| plans | 总体计划及版本变化 |

讨论中建议放在每个工作目录的 `.agent-workspace/`。这是运行数据目录的候选命名，应与原项目已有目录方案统一；不要再建立一套并行状态源。

Python 调度器仍负责状态转换、执行准入和自动轮次。文件组织方式不承担自主调度职责。

### 3.2 dsh-ops：文件工具效率

重点研究：

- 对文件搜索结果进行紧凑表达，同时保持完整性与来源可追溯。
- 批量文件处理，减少重复调用和重复读取。
- 控制单次工具输出大小，明确截断与后续读取方式。
- 减少命令错误循环和没有必要的 Token 消耗。

原讨论提及 Rust 工具和受控 Shell；这些是候选实现方式，不代表本项目必须迁移到 Rust 或替换所有现有工具。

仓库宣称的 Token 降低属于外部自测结果。本项目不得在未评测时沿用其收益数字或据此宣称优化成功。

### 3.3 opencode-ops：终端与远程操作交互

可借鉴多 SSH 会话、终端状态、任务看板、GitHub Actions 与 Web Dashboard 的交互组织。

当前不引入 OpenCode 作为第三个 Agent 运行时。npm 元数据已将包名关联到 `asychin/opencode-ops`，并已读取对应 gitHead 的 README；包版本/源码关联见调研清单，仍未验证本机接入。

### 3.4 Hermes operations：观测与协作分析

参考以下页面和交互概念：

| 概念 | 在 agentProj 中的对应内容 |
| --- | --- |
| Handoffs | Sol 与 DeepSeek 的任务交付和反馈 |
| Trace | Decision、Run、Result、Review 与证据链 |
| Flow | 跨会话调用关系、模型请求与结果流向 |
| Activity | 命令、测试、状态变化与耗时 |
| Notifications | 失败、暂停、预算预警、等待审阅 |

关注模型请求耗时、失败比例、等待时间和跨会话关系。复用这些观测设计，不默认引入 Hermes 的数据库和完整运行时。

## 4. Skills 与 Ops Tools 的分工

| 类型 | 职责 | 示例 |
| --- | --- | --- |
| Skills | 指导 Agent 如何完成任务 | `codebase-design`、`unslop`、`goal-collaboration-postmortem` |
| Ops Tools | 执行具体操作或查询系统事实 | 文件搜索、Git、进程监控、SSH、用量与调用链查询 |
| Python 调度器 | 控制任务是否允许执行、如何启动与结束 | 生命周期、权限、预算、暂停、恢复 |

`SKILL.md` 不能替代原生工具的接口适配。不能把所有插件直接放进 `.agents/skills/`，就认为它们已具备可执行能力。

Ops Capability Layer 是一组职责清楚的适配接口，不要求再建独立服务、插件商店或新框架。优先复用已有 Python、CLI 或 MCP 能力。

## 5. 推荐架构与 Adapter 边界

| 层 | 组件与职责 |
| --- | --- |
| Windows 前端 | 独立会话、Skills、Goal、工具与扩展、监控、Token 曲线 |
| Windows Python Orchestrator | 唯一 Agent 生命周期控制器；权限、预算与执行准入 |
| Agent Layer | Windows Sol、WSL Codex/DeepSeek、各自 Session Skills |
| Ops Capability Layer | File、Workflow、Git/Terminal、Trace/Metrics 等 Adapter |
| 当前工作目录持久记忆 | Session、Goal、Run、Decision、Evidence、Usage |

Adapter 接收明确操作、参数和作用域，调用支持的原生程序、CLI、MCP 或其他接口，再返回结果和必要的事件。它不自行创建新 Goal、不自动续轮、不修改预算、不授予自身权限。

本轮整体方案建议 `.agentproj/` 作为统一运行目录，SQLite 由 Windows Python 单写入；原 `.agent-workspace/` 和 `workspace-data/` 保留为历史候选名称，不并行建立状态源。命名仍待审阅。

| Ops 能力 | 初期实现建议 | 优先级 |
| --- | --- | --- |
| File Ops | Python、ripgrep；收益明确后再评估 Rust 工具 | 高 |
| Workflow Ops | Python 状态转换与本地持久化；SQLite 为候选 | 高 |
| Trace Ops | 复用已有 Agent 生命周期和工具事件 | 高 |
| Token Metrics | 适配实际可获得的 Codex 用量事件与预算计算 | 高 |
| Git Ops | 受控 Git CLI | 高 |
| SSH Ops | 独立 SSH Adapter | 后期 |
| CI/CD Ops | 按需使用 GitHub Actions API | 后期 |

接口应围绕实际所需操作设计，避免为了未来可替换性抽象所有工具。SQLite、事件字段和具体用量接口仍应结合现有代码与真实版本确定。

## 6. 前端配置与后端权限

在 Skill Manager 旁增加“工具与扩展”页面，按工作目录显示：

- File Ops：搜索、读取与受控批量操作。
- Trace & Metrics：调用链、Token、状态与耗时。
- Workflow Ops：计划、任务、运行与验收。
- Git / Terminal Ops：代码变更和命令结果。
- SSH / CI Ops：后期按需接入。

权限作用域建议保持三层：工作目录允许列表、会话启用设置、单个 Goal 的临时授权。界面选择先保存配置，不直接启动模型或命令。

前端关闭高权限能力时，后端必须撤销相应入口的后续调用权限；排队操作重新准入。已开始的操作按预定策略收尾或取消，不能假装已经撤回完成的副作用。

如果 Agent 还可通过其他 Shell 或工具执行同类操作，必须明确这些入口的实际限制；只关闭一个 Adapter，不应宣称完成了整个环境的权限隔离。

不照搬 `sshpass`、root SSH 和关闭主机密钥验证等配置。原讨论称相关第三方示例出现过这些做法，本次未核验示例来源；本项目可独立明确不采用这类默认设置。

## 7. 与 Goal Postmortem 的衔接

复用已有 Goal、Session、Decision、Run、Evidence、Usage 关联，不为 Ops 另建一套无法对齐的 ID。

以下仅为交互示意，非真实执行记录：

| 顺序 | 节点 | 可见内容 |
| --- | --- | --- |
| 1 | Sol Decision #31 | 依据 Plan v2 下发接口修改任务 |
| 2 | DeepSeek Run #52 | 完成实现，测试 8/10，未达验收要求 |
| 3 | Sol Review #32 | 根据失败证据要求最小范围修复 |
| 4 | DeepSeek Run #53 | 修复后测试 10/10；仍需逐项核对 Goal 标准 |

每个节点可展开指令、最终/暂停报告、测试证据、Git 变化、Token、耗时和前后决策关系。测试全部通过不自动等同于整个 Goal 完成。

复盘对照原始总体计划，解释哪些行动推进验收、哪些造成返工，区分等待、规划、执行和修复成本。缺少证据时标记未知，不仅凭时间相邻推断因果。

## 8. 输出、记忆与模型调用成本

维持原约定：WSL 大量中间文本不全量进入 Sol 上下文。普通程序提取生命周期事件、Token 信息，以及暂停或结束时的结构化报告；必要命令和测试证据保存在本地并通过引用提供。

不保存或提取私有思维链。输出压缩只减少冗余展示，不丢失可定位的执行事实；发生截断时记录范围与补取入口。

Activity Summary 一类自动调用模型生成文字的监控功能，默认关闭。日常看板优先由程序对已有事件聚合，不为了展示活动而额外调用 Sol。

用户主动触发摘要或复盘时，才按普通模型调用记录用量，并接受同一预算门禁；不得将“监控”或“复盘”标签当作无限额度。

执行预算达到 100% 后禁止自动下一轮；当前轮按预设策略完成或安全中断。Ops 不得重启执行循环或绕过暂停状态。

## 9. 接入阶段

| 阶段 | 实施范围 | 目标与验收 |
| --- | --- | --- |
| Ops V0.1 | 借鉴 ops-workflow 与 Hermes Trace，复用 Python 与现有事件 | 打通任务、状态、交接和调试；不引入新的自主循环 |
| Ops V0.2 | 独立评测 dsh-ops 或等价的优化文件工具 | 在相同环境验证 Token、耗时、错误率和结果完整性 |
| Ops V0.3 | 按工作目录、会话和 Goal 配置 Ops Adapter | 后端真实执行允许列表与撤销；配置不影响无关会话 |
| Ops V0.4 | 按实际需求增加 SSH、GitHub Actions | 扩展远程工程操作，同时保留原调度与预算边界 |

V0.1 即需保留最基本的后端权限与作用域检查。V0.3 是配置与扩展机制完善，不意味着前两阶段允许任意操作。

## 10. 文件工具对照评测方案

固定相同仓库快照、相同搜索/读取/批量任务和相同模型配置，对比默认工具与候选优化工具。双方都使用可行且合理的调用方式，不故意制造低效基线。

| 指标 | 记录要求 |
| --- | --- |
| 正确性与完整性 | 是否遗漏文件或匹配项；结果能否定位原文件和位置 |
| 输入/输出 Token | 区分实际计量、估算；统一统计边界和去重规则 |
| 工具输出体积 | 字节/字符与进入模型的 Token 分开记录 |
| 耗时 | 工具耗时、模型等待与端到端耗时分开 |
| 错误与重试 | 非零退出、参数错误、重复读取、补取次数 |
| 环境与依赖 | 平台、工具版本、额外宿主和维护成本 |

不得通过少返回必要结果来宣称节省 Token。缓存状态、模型请求与任务难度会影响结果，应记录比较条件并对必要任务重复测量。

若 dsh-ops 本身不支持当前 WSL/Codex 环境，可先研究其设计或评测兼容的等价工具，不能将其他宿主上的成绩直接归给本项目。

是否引入的依据是完整性保持、实际收益与维护成本，而非仓库宣传数字。具体收益门槛在评测前确定，不在看到结果后调整标准。

## 11. 待核验事项

本轮已完成准确来源与部分文件的公开核对；下列清单中运行能力、许可采用范围和兼容性实验尚未完成。Hermes Operations 未发现明确独立 LICENSE，当前只参考设计，自行实现界面与后端。

1. 四类项目的准确仓库、许可证、维护状态与具体版本。
2. dsh-ops 的当前支持平台、DSH 版本要求和可独立复用的部分。
3. opencode-ops 的 npm 来源、真实源码和运行时依赖。
4. Hermes Operations 的准确插件位置、数据模型、指标接口与运行时依赖。
5. 当前 Codex 的生命周期、工具与用量事件能提供哪些字段。
6. 项目已有目录、事件 ID 和持久化结构，避免重复状态源。
7. Adapter 关闭、正在运行的操作、排队调用与 Goal 暂停的具体处理。
8. 真实基线下文件工具的完整性、Token 与耗时差异。

## 12. 本记录的交付范围

本次只将上述想法整理为 Markdown。未安装插件、未引入第三运行时、未执行性能评测、未实施 Adapter，也未把外部兼容性说法提升为已验证事实。

2026-10-15 整理时已直接保存于 Windows 项目目录。原版已保留在备份 ZIP；本次只更正路径、落盘状态和统一工作流名称。相关设计见 [四种 Skill](FOUR_SKILLS_DESIGN.md)、[Skill 管理](SKILL_MANAGEMENT.md)、[用量与预算](BUDGET_AND_USAGE.md)和[数据约定](DATA_CONTRACTS.md)。
