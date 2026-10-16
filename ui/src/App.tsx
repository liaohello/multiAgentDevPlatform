import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, streamUrl, cls, shortId, TOKEN } from "./api";
import { GoalPanel } from "./GoalPanel";
import { StreamPanel } from "./StreamPanel";
import { SkillsPanel, WikiPanel, ReportsPanel, EnvPanel } from "./Panels";

type Tab = "goal" | "skills" | "wiki" | "reports" | "env";

export default function App() {
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [goals, setGoals] = useState<any[]>([]);
  const [goalId, setGoalId] = useState<string | null>(null);
  const [bundle, setBundle] = useState<any | null>(null);
  const [tab, setTab] = useState<Tab>("goal");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [transient, setTransient] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const reloadTimer = useRef<number | null>(null);

  const refreshLists = useCallback(async () => {
    const [ws, gs] = await Promise.all([api.get("/api/workspaces"), api.get("/api/goals")]);
    setWorkspaces(ws);
    setGoals(gs);
  }, []);

  const refreshBundle = useCallback(async (id: string | null) => {
    if (!id) { setBundle(null); return; }
    try {
      setBundle(await api.get(`/api/goals/${id}`));
    } catch (e: any) { setError(e.message); }
  }, []);

  useEffect(() => { refreshLists().catch((e) => setError(e.message)); }, [refreshLists]);
  useEffect(() => { refreshBundle(goalId); }, [goalId, refreshBundle]);

  // ---- SSE with cursor-based resume --------------------------------------
  useEffect(() => {
    let cursor = 0, tseq = 0, aborted = false;
    const controller = new AbortController();
    async function loop() {
      while (!aborted) {
        try {
          const resp = await fetch(streamUrl(cursor, tseq), { signal: controller.signal });
          if (!resp.ok || !resp.body) throw new Error(`stream ${resp.status}`);
          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let buf = "";
          while (!aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            let idx: number;
            while ((idx = buf.indexOf("\n\n")) >= 0) {
              const chunk = buf.slice(0, idx);
              buf = buf.slice(idx + 2);
              const dataLine = chunk.split("\n").find((l) => l.startsWith("data: "));
              if (!dataLine) continue;
              let payload: any;
              try { payload = JSON.parse(dataLine.slice(6)); } catch { continue; }
              for (const ev of payload.events || []) cursor = Math.max(cursor, ev.seq);
              for (const tr of payload.transient || []) tseq = Math.max(tseq, tr.tseq);
              if (payload.events?.length) {
                setEvents((prev) => [...prev, ...payload.events].slice(-400));
                const types = payload.events.map((e: any) => e.type);
                if (types.some((t: string) => ["run.completed", "run.failed", "run.interrupted", "review.applied", "goal.completed", "goal.planned", "goal.plan_revised", "budget.closed", "budget.resumed", "evidence.collected"].includes(t))) {
                  if (reloadTimer.current) window.clearTimeout(reloadTimer.current);
                  reloadTimer.current = window.setTimeout(() => {
                    refreshBundle(goalId);
                    refreshLists();
                  }, 400);
                }
              }
              if (payload.transient?.length) {
                setTransient((prev) => [...prev, ...payload.transient].slice(-600));
              }
            }
          }
        } catch (e) { /* reconnect below */ }
        if (!aborted) await new Promise((r) => setTimeout(r, 1200));
      }
    }
    loop();
    return () => { aborted = true; controller.abort(); };
  }, [goalId, refreshBundle, refreshLists]);

  // ---- goal creation ------------------------------------------------------
  const [form, setForm] = useState({
    title: "实现 normalize_tags",
    request: "实现 normalize_tags(text)：按逗号拆分、去首尾空白、忽略空项、去重并保留顺序。",
    mode: "simulation",
    scenario: "demo",
    workspaceMode: "demo",
    workspaceId: "",
    budget: "",
    autoAdvance: true,
    model: "",
    effort: "low",
  });

  const createGoal = useCallback(async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const body: any = {
        title: form.title,
        request: form.request,
        mode: form.mode,
        scenario: form.mode === "simulation" ? form.scenario : "demo",
        workspace_mode: form.workspaceMode,
        workspace_id: form.workspaceMode === "existing" ? form.workspaceId : null,
        budget_tokens: form.budget ? Number(form.budget) : null,
        auto_advance: form.autoAdvance,
        sol_model: form.model || null,
        sol_effort: form.effort || null,
      };
      const resp = await api.post("/api/goals", body);
      setNotice(`已创建 Goal ${resp.goal.id}`);
      await refreshLists();
      setGoalId(resp.goal.id);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }, [form, refreshLists]);

  const workspaceOptions = useMemo(
    () => workspaces.map((w: any) => ({ id: w.id, label: `${w.name}（${w.windows_path}）` })),
    [workspaces]
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">agentProj 工作台 <span className="muted">本地闭环</span></div>
        <div className="topbar-right">
          <span className={cls("conn", TOKEN ? "ok" : "bad")}>{TOKEN ? "会话令牌已注入" : "缺少令牌"}</span>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <section>
            <h3>新建 Goal</h3>
            <label>标题<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label>原始需求<textarea rows={3} value={form.request} onChange={(e) => setForm({ ...form, request: e.target.value })} /></label>
            <div className="row">
              <label>模式
                <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
                  <option value="simulation">simulation（确定性模拟）</option>
                  <option value="real">real（真实 Sol / WSL Worker）</option>
                </select>
              </label>
              {form.mode === "simulation" && (
                <label>场景
                  <select value={form.scenario} onChange={(e) => setForm({ ...form, scenario: e.target.value })}>
                    <option value="demo">失败→重规划→修复→完成</option>
                    <option value="budget">预算 100% 停止</option>
                    <option value="cancel">长任务（取消验证）</option>
                  </select>
                </label>
              )}
            </div>
            <div className="row">
              <label>工作目录
                <select value={form.workspaceMode} onChange={(e) => setForm({ ...form, workspaceMode: e.target.value })}>
                  <option value="demo">隔离演示目录（自动创建）</option>
                  <option value="existing">已有工作目录</option>
                </select>
              </label>
            </div>
            {form.workspaceMode === "existing" && (
              <label>选择目录
                <select value={form.workspaceId} onChange={(e) => setForm({ ...form, workspaceId: e.target.value })}>
                  <option value="">（选择）</option>
                  {workspaceOptions.map((w) => <option key={w.id} value={w.id}>{w.label}</option>)}
                </select>
              </label>
            )}
            <div className="row">
              <label>预算(tokens)<input placeholder="留空=不设上限" value={form.budget} onChange={(e) => setForm({ ...form, budget: e.target.value })} /></label>
              <label>自动推进
                <input type="checkbox" checked={form.autoAdvance} onChange={(e) => setForm({ ...form, autoAdvance: e.target.checked })} />
              </label>
            </div>
            {form.mode === "real" && (
              <div className="row">
                <label>Sol 模型<input placeholder="如 gpt-5.6-luna" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></label>
                <label>推理档位
                  <select value={form.effort} onChange={(e) => setForm({ ...form, effort: e.target.value })}>
                    {["low", "medium", "high", "xhigh", "max"].map((x) => <option key={x}>{x}</option>)}
                  </select>
                </label>
              </div>
            )}
            <button disabled={busy} onClick={createGoal}>创建 Goal</button>
          </section>

          <section>
            <h3>Goals</h3>
            <ul className="goal-list">
              {goals.map((g) => (
                <li key={g.id} className={cls("goal-item", g.id === goalId && "active")} onClick={() => setGoalId(g.id)}>
                  <div className="goal-title">{g.title}</div>
                  <div className="goal-meta">
                    <span className={cls("badge", `mode-${g.mode}`)}>{g.mode}</span>
                    <span className={cls("badge", `status-${g.status}`)}>{g.status}</span>
                    <span className="muted">{g.stage || ""}</span>
                  </div>
                </li>
              ))}
              {!goals.length && <li className="muted">暂无 Goal</li>}
            </ul>
          </section>
        </aside>

        <main className="main">
          <nav className="tabs">
            {([["goal", "Goal 闭环"], ["skills", "Skills"], ["wiki", "Wiki"], ["reports", "复盘与审计"], ["env", "环境与能力"]] as [Tab, string][]).map(([k, label]) => (
              <button key={k} className={cls("tab", tab === k && "active")} onClick={() => setTab(k)}>{label}</button>
            ))}
          </nav>

          {error && <div className="alert error" onClick={() => setError(null)}>错误：{error}（点击关闭）</div>}
          {notice && <div className="alert info" onClick={() => setNotice(null)}>{notice}</div>}

          {tab === "goal" && (
            <div className="goal-grid">
              <GoalPanel
                bundle={bundle}
                setError={setError}
                setNotice={setNotice}
                refresh={() => { refreshBundle(goalId); refreshLists(); }}
              />
              <StreamPanel transient={transient} events={events} goalId={goalId} bundle={bundle} />
            </div>
          )}
          {tab === "skills" && <SkillsPanel bundle={bundle} setError={setError} />}
          {tab === "wiki" && <WikiPanel bundle={bundle} workspaces={workspaces} setError={setError} />}
          {tab === "reports" && <ReportsPanel bundle={bundle} setError={setError} />}
          {tab === "env" && <EnvPanel />}
        </main>
      </div>
    </div>
  );
}
