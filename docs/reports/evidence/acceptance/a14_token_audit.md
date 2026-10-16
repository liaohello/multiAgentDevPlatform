# Token Audit：A07 预算停止验证

- Goal: `goal_275e60318bf4`（mode=simulation）
- 累计用量：10200 tokens；预留：0；门禁：OPEN

## 诊断发现

- [fact] 预算使用率 51.0%（10200/20000），门禁 OPEN。
- [fact] 精确度分布：{"simulated": 10200}（simulated 为模拟计量，不混入真实统计）。
- [inference] 单步最大增量 2800 tokens；如显著高于中位数，可检查该轮上下文与工具输出体积。
- [inference] 1 个 Run 结果为 failed，返工会推高总成本；对应证据已关联。
- [suggestion] 待验证建议：若连续失败集中于同类错误，可考虑在计划阶段增加针对性验收用例（需后续对照验证，不宣称必然收益）。

## 计量边界

Token Audit 只读取 Python 已采集的用量事件，不负责计量、不放行预算、不自动重试。
真实/估算/未知分别记录；模拟量以 exactness=simulated 单独标记，不与真实口径混用。