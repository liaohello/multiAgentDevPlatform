import { useEffect, useMemo, useRef } from "react";
import { cls, fmtTime } from "./api";

const EVENT_CN: Record<string, string> = {
  "goal.created": "创建 Goal", "goal.planned": "计划已冻结", "goal.plan_revised": "计划已修订",
  "goal.activated": "开始执行", "goal.paused": "Goal 暂停", "goal.resumed": "Goal 恢复",
  "goal.completed": "Goal 完成", "goal.cancelled": "Goal 取消",
  "run.queued": "Run 入队", "run.starting": "Run 启动", "run.started": "Run 运行中",
  "run.completed": "Run 完成", "run.failed": "Run 失败", "run.interrupted": "Run 中断",
  "run.recovered": "重启恢复", "run.command": "命令执行", "run.file_change": "文件变更",
  "evidence.collected": "证据已采集", "review.created": "验收生成", "review.applied": "验收已应用",
  "decision.created": "决策", "budget.usage_recorded": "用量记录", "budget.closed": "预算门禁关闭",
  "budget.resumed": "预算恢复", "budget.warning": "预算预警", "budget.usage_reset_observed": "用量重置观察",
  "skill.provided": "Skill 已提供", "skill.session_selected": "Skill 会话选择", "skill.registry_updated": "Skill 注册表",
  "wiki.imported": "Wiki 导入", "wiki.body_read": "Wiki 正文读取", "wiki.denied": "Wiki 拒绝",
  "workflow.completed": "工作流报告", "system.recovered": "系统恢复", "system.note": "系统备注",
  "session.created": "会话创建", "session.updated": "会话配置更新", "workspace.created": "工作目录注册",
};

export function StreamPanel({ transient, events, goalId, bundle }: {
  transient: any[]; events: any[]; goalId: string | null; bundle: any;
}) {
  const solBox = useRef<HTMLDivElement>(null);
  const workerBox = useRef<HTMLDivElement>(null);

  const goalTransient = useMemo(
    () => transient.filter((t) => !goalId || t.goal_id === goalId),
    [transient, goalId]
  );
  const solText = useMemo(() => goalTransient.filter((t) => t.role === "sol").map((t) => t.text).join(""), [goalTransient]);
  const workerText = useMemo(() => goalTransient.filter((t) => t.role === "worker").map((t) => t.text).join(""), [goalTransient]);

  const goalEvents = useMemo(
    () => events.filter((e) => !goalId || e.goal_id === goalId).slice(-80).reverse(),
    [events, goalId]
  );

  useEffect(() => { solBox.current?.scrollTo({ top: solBox.current.scrollHeight }); }, [solText]);
  useEffect(() => { workerBox.current?.scrollTo({ top: workerBox.current.scrollHeight }); }, [workerText]);

  return (
    <div className="panel stream-panel">
      <section>
        <h3>实时流（SSE 游标恢复 · 刷新不重发任务）</h3>
        <div className="lane-grid">
          <div>
            <div className="lane-title">Sol（Windows 规划/验收）</div>
            <div className="lane" ref={solBox}>{solText || <span className="muted">等待输出…</span>}</div>
          </div>
          <div>
            <div className="lane-title">Worker（执行）</div>
            <div className="lane" ref={workerBox}>{workerText || <span className="muted">等待输出…</span>}</div>
          </div>
        </div>
      </section>

      {bundle?.usage_series?.length > 0 && (
        <section>
          <h3>Token 曲线（按事件累计）</h3>
          <TokenChart series={bundle.usage_series} budget={bundle.usage.budget_tokens} />
        </section>
      )}

      <section>
        <h3>事件时间线（最近 {goalEvents.length}）</h3>
        <ul className="event-list">
          {goalEvents.map((e) => (
            <li key={e.seq}>
              <span className="muted">#{e.seq}</span>
              <span className={cls("badge", "ev")}>{EVENT_CN[e.type] || e.type}</span>
              <span className="muted mono">{e.run_id ? e.run_id.slice(0, 10) : ""}</span>
              <span className="muted">{fmtTime(e.ts)}</span>
              <span className="ev-payload">{payloadBrief(e)}</span>
            </li>
          ))}
          {!goalEvents.length && <li className="muted">（该 Goal 暂无事件；切换 Goal 后此处按 goal_id 过滤）</li>}
        </ul>
      </section>
    </div>
  );
}

function payloadBrief(e: any): string {
  const p = e.payload || {};
  if (e.type === "run.command") return `${p.command} → exit ${p.exit_code}`;
  if (e.type === "run.completed") return `result=${p.result_status} tests=${JSON.stringify((p.tests || []).map((t: any) => t.exit_code))}`;
  if (e.type === "review.created") return `overall=${p.overall} next=${p.next_action}`;
  if (e.type === "budget.usage_recorded") return `+${p.tokens} (${p.exactness})`;
  if (e.type === "budget.closed") return p.reason;
  if (e.type === "evidence.collected") return `测试 ${(p.tests || []).length} 项，变更 ${p.changed_files} 个文件`;
  if (e.type === "run.file_change" || e.type === "run.recovered") return JSON.stringify(p).slice(0, 120);
  return "";
}

export function TokenChart({ series, budget }: { series: any[]; budget: number | null }) {
  const w = 520, h = 160, pad = 34;
  const points = series.map((s, i) => ({ x: i, y: s.cumulative, tokens: s.total_tokens, ts: s.ts, run: s.run_id }));
  const maxY = Math.max(budget || 0, ...points.map((p) => p.y), 1) * 1.05;
  const n = Math.max(points.length - 1, 1);
  const sx = (i: number) => pad + (i / n) * (w - pad * 2);
  const sy = (v: number) => h - pad - (v / maxY) * (h - pad * 2);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");
  const budgetY = budget ? sy(budget) : null;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="chart" role="img" aria-label="token 累计曲线">
      <rect x={0} y={0} width={w} height={h} fill="var(--chart-bg)" rx={8} />
      {budgetY !== null && (
        <>
          <line x1={pad} x2={w - pad} y1={budgetY} y2={budgetY} stroke="#d64545" strokeDasharray="5 4" strokeWidth={1.4} />
          <text x={w - pad} y={budgetY - 5} textAnchor="end" fontSize={10} fill="#d64545">预算 {budget}</text>
        </>
      )}
      <path d={path} fill="none" stroke="#3b82f6" strokeWidth={1.8} />
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={sx(i)} cy={sy(p.y)} r={3} fill="#3b82f6" />
          <title>{`+${p.tokens} → 累计 ${p.y}\n${p.ts}\n${p.run || ""}`}</title>
        </g>
      ))}
      <text x={pad} y={h - 8} fontSize={10} fill="var(--muted)">每点=一次用量事件（累计）</text>
      <text x={w - pad} y={h - 8} textAnchor="end" fontSize={10} fill="var(--muted)">max {Math.round(maxY)}</text>
    </svg>
  );
}
