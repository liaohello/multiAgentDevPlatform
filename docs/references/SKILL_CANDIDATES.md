# Skill 候选来源与核验记录

这些是讨论中的候选，不是安装结果。最初整理记忆时未联网核验；2026-10-15 后续调研已核对四种工作流的部分来源，见下方更新及[完整调研](GITHUB_PROJECT_RESEARCH_2026-10-15.md)。其他候选仍未逐项复核，没有安装或执行第三方 Skill。

## 1. 与最小方案直接相关的候选

| 名称 | 原讨论提及的仓库标识 | 期望能力 | 本次状态 |
| --- | --- | --- | --- |
| unslop | `maxgoff/unslop`；另出现 `MohamedAbdallah-14/unslop` | 减少 AI 冗余代码与无必要防御 | 两个来源可能不同，不能混为一项；待核验 |
| minimalist | `alirezarezvani/claude-skills` | YAGNI、复用、控制依赖与复杂度 | 具体目录与同名 Skill 存在性待核验 |
| codebase-design | `mattpocock/skills` | 模块边界、接口与浅包装问题 | 文件路径、内容和许可证待核验 |
| agentic-architecture | `Lightbridge-KS/agent-stuff` | Agent 循环、工具、记忆、生命周期 | 文件路径、兼容性待核验 |
| code-simplifier | `caarlos0/dotfiles` | 限定当前 Diff、保持行为的简化 | 具体文件与约束待核验 |
| Skill 安装工具 | `vercel-labs/skills` | 查找和安装指定 Skill | 实际版本、参数与下载/执行行为待核验 |

这里的仓库标识按历史讨论保留，不代表其内容真实存在、符合描述或当前适合安装。为避免复制未经核验的命令，本资料不把原 `npx skills add` 命令作为可直接执行步骤。

## 2. 其他讨论过的候选

| 名称 / 仓库标识 | 讨论用途 | 处理意见 |
| --- | --- | --- |
| linus-guidelines | 控制复杂度与特殊情况的评审视角 | 未有可靠文件路径；不代表 Linus 本人背书 |
| codebase-architecture | 目录、契约、依赖边界 | 精确来源未确定 |
| architecture-patterns | Clean / Hexagonal / DDD 等 | 不应因此强制上复杂架构 |
| adr-skill | 重大架构决策记录 | 只在需要时采用 |
| deep-codebase-analysis | 已有项目结构、调用链与错误处理分析 | 精确来源未确定 |
| `obra/superpowers` | brainstorming、planning、TDD、review | 工作流较强，简单任务不强制整套 |
| `imadnan4/architect-skills` | 一组架构类 Skill | 内容与成熟度未在本次验证 |
| `cheriftj/c4-model-skill` | C4 架构图 | 原图卡与其他条目混用，不作为安装依据 |

四种专用工作流的参考标识已合并到下表。来源包括既有历史摘要与[本轮外部讨论](../conversations/2026-10-15-four-skills.md)，未在本次打开仓库。名称或仓库标识可能指项目、目录或单个 Skill，不能据此直接推定安装地址。

| 讨论中的来源标识 | 参考用途 | 接入前重点核验 |
| --- | --- | --- |
| `getsentry/prompt-optimizer` | 任务契约、候选 Prompt、对照评估 | 实际仓库/文件、许可证、评估依赖和成本 |
| `openai/define-goal` / define-goal | 明确 Goal 和完成条件 | 具体仓库及目录；不能默认提供持久计划或执行记录 |
| `giannimassi/agent-retro` | 单会话错误与过程分析 | 原讨论称只支持 Claude Code 本地 JSONL，此说法本次未复核；需重新设计跨 Agent 关联 |
| Bitwarden retrospecting | 多来源证据与复盘方法 | 准确来源、Skill 路径和支持格式尚不明确 |
| `tomzx/verify-pr` / 同处 validate-pr | 验收项到实现/运行证据、目标正确性 | 仓库与文件关系、GitHub/Worktree/Playwright 等依赖、执行权限；不能直接作为只读 Review 接入 |
| `bm629/token-optimization` | 上下文、工具输出、缓存和模型配置成本诊断 | 具体文件和运行环境；不能替代实时计量或预算控制 |

以上能力描述是原讨论的待核验线索，不是本任务的兼容性结论。四种自定义工作流的正式职责见 [四种 Skill 设计](../design/FOUR_SKILLS_DESIGN.md)，Ops 类候选另见 [Ops 设计](../design/OPS_CAPABILITY_DESIGN.md)。

### 2026-10-15 实际定位更新

| 旧标识 | 已核对实际位置 | 公开文件结论 |
| --- | --- | --- |
| `getsentry/prompt-optimizer` | `getsentry/skills` → `skills/prompt-optimizer/SKILL.md` | 任务契约、上下文引用与评估候选 |
| `tomzx/verify-pr` | `tomzx/agents` → `skills/verify-pr/SKILL.md` | 逐项证据映射，亦包含构建/运行等执行操作 |
| `bm629/token-optimization` | `bm629/agent-skills` → `skills/token-optimization/SKILL.md` | 完成任务总成本诊断，不是计量/预算执行器 |
| `giannimassi/agent-retro` | 仓库根 `SKILL.md` | 明确要求 Claude Code 本地 JSONL；跨 Agent 适配需自行实现 |

固定 commit、文件哈希与读取范围见[调研清单](github-research-2026-10-15.json)。以上更新替代相应“具体文件待定位”状态，不表示已通过本机兼容性实验；旧表用于保留历史名称。

## 3. 导入一个 Skill 时需要记录什么

1. 确认仓库、作者、具体目录及真正的 `SKILL.md`，先读内容再选择。
2. 固定 commit 和文件哈希；保留许可证、依赖和支持环境。
3. 区分纯指令与带脚本/外部工具的 Skill；核对网络、文件、凭据和命令需求。
4. 先导入到 Registry，经项目允许和会话选择后再提供给运行时。
5. 用一个小任务验证触发、输出与对代码的影响；不要一次全局安装一套。
6. 记录安装、提供、观察到的调用、相关 Run 和结果；未知项不伪造。

导入/安装本身不是执行授权；Skill 脚本也不能获得超出该 Run 的权限。后续若实际采用某第三方 Skill，应补上真实 URL、commit、文件路径、核验日期与结论。
