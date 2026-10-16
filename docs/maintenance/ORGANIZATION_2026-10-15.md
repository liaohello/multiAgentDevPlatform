# 2026-10-15 项目整理记录

任务：合并相同内容，保存现有设计为项目记忆，本地化新对话，并为模型建立 Wiki 索引。未扩展到应用实现。

## 去重与备份

整理前共 29 个文件；内层 `agentProj/` 的 12 个文件与外层对应文件 SHA-256 完全相同。已逐项确认后移除这套重复副本。17 份独立原文件完整保存在 [2026-10-15-originals.zip](../archive/2026-10-15-originals.zip)，ZIP 内每个文件均与原 SHA-256 校验一致。

备份不含重复的内层目录，不属于日常模型阅读材料。原文件清单、大小、哈希、重复映射、迁移路径及 ZIP 哈希保存在 [organization-2026-10-15.json](organization-2026-10-15.json)。

## 内容归并

| 原位置 / 内容 | 当前位置 / 处理 |
| --- | --- |
| `agentProj/` 下重复资料 | 合并至外层正式资料；重复文件移除 |
| 旧 `PROJECT_MEMORY.md` | 架构与会话保留在 [工作台设计](../design/WORKBENCH_DESIGN.md)，Skill 管理、全链复盘和预算完整内容分别并入专题 |
| `OPS_CAPABILITY_DESIGN_20261015.md` | [Ops 专题](../design/OPS_CAPABILITY_DESIGN.md)，修正当前位置与落盘状态 |
| 原日期目录中的数据、决策、实施文档 | 迁至 `docs/design/`，补充本轮四种 Skill 设计及当前资料状态 |
| `SKILL_CANDIDATES.md` | [候选来源](../references/SKILL_CANDIDATES.md)，合并新对话中的来源线索 |
| 原示例 JSON | 迁至 `docs/examples/`，保留模拟标记和原始字节 |
| 原交接正文、来源说明、JSON 记忆索引 | 更新为当前路径、实际 Windows 写入状态和按需阅读方式；原版仍在 ZIP |
| 旧两个 README、复制安装脚本、旧 manifest / SHA 清单 | 只存于原文件 ZIP；当前入口为根目录 `README.md` |
| 用户本轮粘贴文本 | 保存原文到 `docs/sources/`，生成可读对话到 `docs/conversations/` |

## 本次新增的本地约定

根目录 `AGENTS.md` 引导模型读取 `MEMORY.md` 和 `WIKI.md`，再按主题访问设计；JSON 索引保存路径、摘要、标签与来源。这是为本次整理建立的文件组织方式，不是新增的工作台运行时功能。

设计以“整体架构—专题设计—来源证据”分层。摘要只保留核心约束和导航，同主题详细内容维护在一个专题中；历史原文用于追溯，不被写成当前已验证事实。

## 验证范围

核验原始文件备份、重复哈希、Markdown 本地链接、JSON 可解析性、索引路径与文档覆盖、附件副本一致性、示例未被改写、重复活动文件及旧路径/旧落盘状态残留。验证结果见 [VALIDATION_2026-10-15.md](VALIDATION_2026-10-15.md)。未执行应用测试或第三方兼容性验证。
