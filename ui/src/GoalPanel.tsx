import { useState } from "react";
import { api, cls, fmtTime, shortId } from "./api";

async function post(name: string, url: string, body?: any, setError?: (e: string) => void, setNotice?: (s: string) => void) {
  try {
    // header values must be ASCII: use a UUID-only idempotency key
    const idem = `ui-${crypto.randomUUID()}`;
    const resp = await api.post(url, body, idem);
    setNotice?.(`${name} 已受理${resp?.duplicate ? "（重复请求，返回已有执行）" : ""}`);
    return resp;
  } catch (e: any) {
    setError?.(`${name} 失败：${e.message}`);
    return null;
  }
}

export function GoalPanel({ bundle, setError, setNotice, refresh }: {
  bundle: any; setError: (s: string) => void; setNotice: (s: string) => void; refresh: () => void;
}) {
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const [evidenceContent, setEvidenceContent] = useState<Record<string, string>>({});
  const [budgetNote, setBudgetNote] = useState("");
  const [budgetNew, setBudgetNew] = useState("");

  if (!bundle) return <div className="panel"><p className="muted">左侧创建一个 Goal，或点击已有 Goal 查看闭环。</p></div>;

  const g = bundle.goal;
  const usage = bundle.usage;

  const act = async (name: string, url: string, body?: any) => {
    const resp = await post(name, url, body, setError, setNotice);
    if (resp) refresh();
  };

  const toggleEvidence = async (ev: any) => {
    if (expandedEvidence === ev.id) { setExpandedEvidence(null); return; }
    setExpandedEvidence(ev.id);
    if (!evidenceContent[ev.id]) {
      try {
        const data = await api.get(`/api/evidence/${ev.id}/content`);
        setEvidenceContent((prev) => ({ ...prev, [ev.id]: data.content + (data.truncated ? "\n…（已截断）" : "") }));
      } catch (e: any) {
        setEvidenceContent((prev) => ({ ...prev, [ev.id]: `读取失败：${e.message}` }));
      }
    }
  };

  const activeRun = (bundle.runs || []).find((r: any) => ["QUEUED", "STARTING", "RUNNING", "STOP_REQUESTED"].includes(r.status));

  return (
    <div className="panel goal-panel">
      <div className="panel-head">
        <div>
          <h2>{g.title}</h2>
          <div className="meta-line">
            <span className={cls("badge", `mode-${g.mode}`)}>{g.mode}</span>
            <span className={cls("badge", `status-${g.status}`)}>{g.status}</span>
            <span className="muted">stage: {g.stage || "-"}</span>
            <span className="muted">goal v{g.goal_version} · plan v{g.plan_version} · accept v{g.acceptance_version}</span>
          </div>
          <pre className="request">{g.original_request}</pre>
          {g.completion_note && <div className="note">结论：{g.completion_note}</div>}
        </div>
        <div className="actions">
          <button onClick={() => act("规划", `/api/goals/${g.id}/plan`)}>Sol 规划</button>
          <button disabled={!!activeRun} onClick={() => act("开始执行", `/api/goals/${g.id}/start`)}>开始执行</button>
          <button onClick={() => act("审阅", `/api/goals/${g.id}/review`)}>Sol 审阅</button>
          <button onClick={() => act("暂停", `/api/goals/${g.id}/pause`, { note: "" })}>暂停</button>
          <button onClick={() => act("恢复", `/api/goals/${g.id}/resume`, { note: "用户恢复" })}>恢复</button>
          {activeRun && <button className="danger" onClick={() => act("取消运行", `/api/runs/${activeRun.id}/cancel`, { note: "用户取消" })}>取消当前 Run</button>}
          <button className="danger" onClick={() => act("取消 Goal", `/api/goals/${g.id}/cancel`, { note: "用户取消" })}>取消 Goal</button>
        </div>
      </div>

      <section>
        <h3>预算与用量 <span className={cls("badge", `gate-${usage.gate}`)}>gate {usage.gate}</span>
          <span className={cls("badge", `level-${usage.level}`)}>{usage.level}</span></h3>
        <div className="usage-line">
          已用 {usage.used_tokens} / {usage.budget_tokens ?? "未配置上限"} tokens
          · 预留 {usage.reserved_tokens}
          · 口径 {JSON.stringify(usage.by_exactness)}
        </div>
        {usage.gate === "CLOSED" && (
          <div className="closed-box">
            <div>预算门禁已关闭：{usage.gate_row?.closed_reason}</div>
            <div className="row">
              <input placeholder="恢复说明（必填）" value={budgetNote} onChange={(e) => setBudgetNote(e.target.value)} />
              <input placeholder="新预算 tokens（可选）" value={budgetNew} onChange={(e) => setBudgetNew(e.target.value)} />
              <button onClick={() => act("预算恢复", `/api/goals/${g.id}/budget/resume`, {
                note: budgetNote || "用户恢复", budget_tokens: budgetNew ? Number(budgetNew) : null,
              })}>批准恢复</button>
            </div>
          </div>
        )}
      </section>

      <section>
        <h3>冻结计划（v{bundle.plan?.version ?? "-"}）</h3>
        {bundle.plan ? <pre className="md">{bundle.plan.content_md}</pre> : <p className="muted">尚未规划。</p>}
        {bundle.plans?.length > 1 && (
          <details><summary>计划版本历史（{bundle.plans.length}）</summary>
            <ul>{bundle.plans.map((p: any) => <li key={p.id}>v{p.version} · {p.change_reason} · {fmtTime(p.created_at)}</li>)}</ul>
          </details>
        )}
      </section>

      <section>
        <h3>验收标准（冻结）</h3>
        <ul className="criteria">
          {bundle.criteria.map((c: any) => (
            <li key={c.id}><b>{c.criterion_key}</b> {c.text} {c.required ? <span className="badge req">必需</span> : <span className="badge">可选</span>}</li>
          ))}
          {!bundle.criteria.length && <li className="muted">规划后冻结。</li>}
        </ul>
      </section>

      <section>
        <h3>Runs（{bundle.runs.length}）</h3>
        {bundle.runs.map((r: any) => (
          <div key={r.id} className="run-card">
            <div className="run-head">
              <span className={cls("badge", `run-${r.status}`)}>{r.status}</span>
              <span className="muted">{shortId(r.id)} · {r.is_auto ? "自动" : "手动"} · {fmtTime(r.started_at)}</span>
              {r.result && <span className={cls("badge", `res-${r.result.status}`)}>结果 {r.result.status}</span>}
              {r.error_class && <span className="badge err">{r.error_class}</span>}
            </div>
            {r.result?.tests?.length > 0 && (
              <table className="mini">
                <thead><tr><th>验证命令</th><th>退出码</th><th>摘要</th></tr></thead>
                <tbody>
                  {r.result.tests.map((t: any, i: number) => (
                    <tr key={i}>
                      <td className="mono">{(t.command || []).join(" ") || t.skipped_reason}</td>
                      <td className={t.exit_code === 0 ? "ok" : "bad"}>{t.exit_code ?? "-"}</td>
                      <td className="muted">{t.summary_line || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {r.result?.changes?.length > 0 && (
              <div className="muted">变更：{r.result.changes.map((c: any) => `${c.path}(${c.change})`).join(", ")}</div>
            )}
            {r.result?.summary?.note && <div className="muted">备注：{r.result.summary.note}</div>}
            <div className="evidence-list">
              {r.evidence.map((ev: any) => (
                <span key={ev.id} className="evidence-chip" onClick={() => toggleEvidence(ev)}>
                  {ev.kind}:{ev.rel_path.split("/").pop()}
                </span>
              ))}
            </div>
            {r.evidence.some((ev: any) => ev.id === expandedEvidence) && (
              <pre className="evidence-body">{evidenceContent[expandedEvidence!] || "加载中…"}</pre>
            )}
            {r.native_thread_id && <div className="muted mono">thread: {r.native_thread_id}</div>}
          </div>
        ))}
        {!bundle.runs.length && <p className="muted">尚无执行。</p>}
      </section>

      <section>
        <h3>验收记录（{bundle.reviews.length}）</h3>
        {bundle.reviews.map((rv: any) => (
          <div key={rv.id} className="review-card">
            <div className="run-head">
              <span className={cls("badge", `overall-${rv.overall}`)}>{rv.overall}</span>
              <span className="muted">{shortId(rv.id)} · plan v{rv.plan_version} · {rv.mode}</span>
              <span className="badge">{rv.applied ? `已应用：${rv.applied_action}` : "未应用"}</span>
            </div>
            <table className="mini">
              <thead><tr><th>标准</th><th>判定</th><th>证据</th><th>理由</th></tr></thead>
              <tbody>
                {rv.verdicts.map((v: any, i: number) => (
                  <tr key={i}>
                    <td>{v.criterion_id}</td>
                    <td className={cls(v.status === "PASS" ? "ok" : v.status === "FAIL" ? "bad" : "warn")}>{v.status}</td>
                    <td className="mono muted">{(v.evidence_ids || []).map(shortId).join(", ")}</td>
                    <td>{v.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rv.note && <div className="muted">note: {rv.note}</div>}
          </div>
        ))}
        {!bundle.reviews.length && <p className="muted">尚无验收。</p>}
      </section>

      <section>
        <h3>Decision 链</h3>
        <ul className="decisions">
          {bundle.decisions.map((d: any) => (
            <li key={d.id}>
              <span className="mono">{shortId(d.id)}</span> {d.kind} → {d.next_action}
              {d.reason?.reason ? <span className="muted">（{d.reason.reason}）</span> : null}
              <span className="muted"> {fmtTime(d.created_at)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
