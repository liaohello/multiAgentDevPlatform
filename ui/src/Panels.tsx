import { useEffect, useState } from "react";
import { api, cls, fmtTime } from "./api";

/* ------------------------------------------------------------- Skills */
export function SkillsPanel({ bundle, setError }: { bundle: any; setError: (s: string) => void }) {
  const [skills, setSkills] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [runId, setRunId] = useState("");
  const [usage, setUsage] = useState<any[]>([]);

  const load = async () => {
    try {
      setSkills(await api.get("/api/skills"));
      if (bundle) {
        const all = await api.get(`/api/sessions?workspace_id=${bundle.goal.workspace_id}`);
        setSessions(all);
        const sel: Record<string, string[]> = {};
        for (const s of all) {
          const mine = await api.get(`/api/sessions/${s.id}/skills`);
          sel[s.id] = mine.map((m: any) => m.skill_id);
        }
        setSelected(sel);
      }
    } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [bundle?.goal?.id]);

  const toggleAllowed = async (id: string, allowed: boolean) => {
    try { await api.post(`/api/skills/${id}/allowed`, { allowed }); await load(); }
    catch (e: any) { setError(e.message); }
  };
  const saveSelection = async (sid: string, ids: string[]) => {
    try { await api.post(`/api/sessions/${sid}/skills`, { skill_ids: ids }); await load(); }
    catch (e: any) { setError(e.message); }
  };
  const loadUsage = async () => {
    if (!runId) return;
    try { setUsage(await api.get(`/api/runs/${runId}/skills`)); } catch (e: any) { setError(e.message); }
  };

  return (
    <div className="panel">
      <section>
        <h3>Skill Registry（配置 ≠ 实际调用）</h3>
        <table className="mini wide">
          <thead><tr><th>ID</th><th>名称</th><th>版本</th><th>来源</th><th>哈希</th><th>项目允许</th></tr></thead>
          <tbody>
            {skills.map((s) => (
              <tr key={s.id}>
                <td className="mono">{s.id}</td><td>{s.name}</td>
                <td className="mono">{s.version.slice(0, 18)}</td>
                <td>{s.source}</td>
                <td className="mono muted">{s.content_hash?.slice(0, 16)}</td>
                <td>
                  <input type="checkbox" checked={s.allowed} onChange={(e) => toggleAllowed(s.id, e.target.checked)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {bundle && (
        <section>
          <h3>会话选择（保存配置不启动模型；运行冻结版本）</h3>
          {sessions.map((s) => (
            <div key={s.id} className="session-row">
              <div>
                <span className={cls("badge", s.role === "sol" ? "role-sol" : "role-worker")}>{s.role}</span>
                <span className="mono">{s.id}</span>
                <span className="muted"> model={s.model || "-"} · effort={s.reasoning_effort || "-"} · thread={s.native_thread_id?.slice(0, 12) || "（未建）"}</span>
              </div>
              <div className="skills-checks">
                {skills.filter((k) => k.allowed).map((k) => (
                  <label key={k.id} className="chk">
                    <input
                      type="checkbox"
                      checked={(selected[s.id] || []).includes(k.id)}
                      onChange={(e) => {
                        const cur = new Set(selected[s.id] || []);
                        e.target.checked ? cur.add(k.id) : cur.delete(k.id);
                        setSelected({ ...selected, [s.id]: [...cur] });
                      }}
                    />
                    {k.id}
                  </label>
                ))}
                <button onClick={() => saveSelection(s.id, selected[s.id] || [])}>保存该会话配置</button>
              </div>
            </div>
          ))}
        </section>
      )}

      <section>
        <h3>某次 Run 的 Skill 观测状态</h3>
        <div className="row">
          <input placeholder="run_id" value={runId} onChange={(e) => setRunId(e.target.value)} />
          <button onClick={loadUsage}>查询</button>
        </div>
        <table className="mini">
          <thead><tr><th>skill</th><th>状态</th><th>备注</th><th>时间</th></tr></thead>
          <tbody>
            {usage.map((u) => (
              <tr key={u.id}><td>{u.skill_id}</td><td className="mono">{u.state}</td><td className="muted">{u.note}</td><td className="muted">{fmtTime(u.ts)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

/* --------------------------------------------------------------- Wiki */
export function WikiPanel({ bundle, workspaces, setError }: { bundle: any; workspaces: any[]; setError: (s: string) => void }) {
  const [wsId, setWsId] = useState<string>("");
  const [entries, setEntries] = useState<any[]>([]);
  const [importPath, setImportPath] = useState("");
  const [body, setBody] = useState<string>("");
  const [readPath, setReadPath] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => { if (bundle && !wsId) setWsId(bundle.goal.workspace_id); }, [bundle, wsId]);
  const load = async (id: string) => {
    if (!id) return;
    try { setEntries(await api.get(`/api/wiki?workspace_id=${id}`)); } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { load(wsId); /* eslint-disable-next-line */ }, [wsId]);

  const doImport = async () => {
    try {
      const r = await api.post("/api/wiki/import", { workspace_id: wsId, source_path: importPath, note: "UI 导入" });
      setNotice(`已导入：${r.title}（hash ${r.content_hash.slice(0, 18)}…，scope=${r.scope}）`);
      await load(wsId);
    } catch (e: any) { setError(`导入失败：${e.message}`); }
  };
  const doScan = async () => {
    try {
      const r = await api.post("/api/wiki/scan", { workspace_id: wsId, subdir: "." });
      setNotice(`已扫描：${r.scanned}（新增/更新 ${r.entries_created_or_updated} 条）`);
      await load(wsId);
    } catch (e: any) { setError(`扫描失败：${e.message}`); }
  };
  const openBody = async (id: string) => {
    try {
      const r = await api.get(`/api/wiki/entries/${id}/body?workspace_id=${wsId}`);
      setBody(r.body);
    } catch (e: any) { setError(`正文读取被拒绝：${e.message}`); }
  };
  const tryReadPath = async () => {
    try {
      const r = await api.post("/api/wiki/read-path", { workspace_id: wsId, rel_path: readPath });
      setBody(r.body);
    } catch (e: any) { setError(`路径读取被拒绝：${e.message}`); }
  };

  return (
    <div className="panel">
      <section>
        <h3>工作目录 Wiki（标题/摘要/标签/来源索引）</h3>
        <div className="row">
          <select value={wsId} onChange={(e) => setWsId(e.target.value)}>
            <option value="">（选择工作目录）</option>
            {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <button onClick={doScan}>扫描该目录文档（元数据）</button>
        </div>
        <div className="row">
          <input placeholder="导入 Markdown/TXT 的绝对路径" value={importPath} onChange={(e) => setImportPath(e.target.value)} style={{ flex: 1 }} />
          <button onClick={doImport}>显式导入</button>
        </div>
        {notice && <div className="alert info">{notice}</div>}
        <table className="mini wide">
          <thead><tr><th>标题</th><th>摘要</th><th>标签</th><th>来源</th><th>scope</th><th></th></tr></thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>{e.title}</td><td className="muted">{e.summary?.slice(0, 80)}</td>
                <td>{(e.tags || []).join(", ")}</td>
                <td className="mono muted" style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }}>{e.source}</td>
                <td><span className="badge">{e.scope}</span></td>
                <td><button onClick={() => openBody(e.id)}>读正文</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section>
        <h3>受控路径读取（越界/跨目录会被拒绝并记录事件）</h3>
        <div className="row">
          <input placeholder="相对工作目录的路径，如 README.md；越界示例：../../x" value={readPath} onChange={(e) => setReadPath(e.target.value)} style={{ flex: 1 }} />
          <button onClick={tryReadPath}>读取</button>
        </div>
      </section>
      {body && <pre className="md">{body.slice(0, 20000)}</pre>}
    </div>
  );
}

/* ------------------------------------------------------------ Reports */
export function ReportsPanel({ bundle, setError }: { bundle: any; setError: (s: string) => void }) {
  const [reports, setReports] = useState<any[]>([]);
  const [current, setCurrent] = useState<any | null>(null);
  const [text, setText] = useState("帮我做一个 normalize_tags 函数，逗号分隔去空白去重");

  const load = async () => {
    if (!bundle) return;
    try { setReports(await api.get(`/api/workflows/reports?goal_id=${bundle.goal.id}`)); } catch (e: any) { setError(e.message); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [bundle?.goal?.id]);

  const run = async (kind: string, url: string, body: any) => {
    try {
      const idem = `${kind}-${crypto.randomUUID()}`;
      const resp = await api.post(url, body, idem);
      setCurrent({ kind, markdown: resp.markdown, json: JSON.stringify(resp.report, null, 1) });
      await load();
    } catch (e: any) { setError(`${kind} 失败：${e.message}`); }
  };

  const open = async (id: string) => {
    try {
      const r = await api.get(`/api/workflows/reports/${id}`);
      setCurrent({ kind: r.kind, markdown: r.report_md, json: JSON.stringify(r.report, null, 1) });
    } catch (e: any) { setError(e.message); }
  };

  if (!bundle) return <div className="panel"><p className="muted">先选择一个 Goal。</p></div>;

  return (
    <div className="panel">
      <section>
        <h3>四种轻量工作流（读取同一事件/证据，分析计入预算）</h3>
        <div className="row wrap">
          <input value={text} onChange={(e) => setText(e.target.value)} style={{ flex: 1 }} />
          <button onClick={() => run("prompt-optimizer", `/api/goals/${bundle.goal.id}/optimize`, { text })}>Quick Prompt 优化</button>
          <button onClick={() => run("postmortem", `/api/goals/${bundle.goal.id}/postmortem`, {})}>全链复盘</button>
          <button onClick={() => run("token-audit", `/api/goals/${bundle.goal.id}/token-audit`, {})}>Token Audit</button>
          <span className="muted">（Goal Review 已在闭环中生成，见 Goal 页签）</span>
        </div>
      </section>
      <section>
        <h3>历史报告</h3>
        <ul className="report-list">
          {reports.map((r) => (
            <li key={r.id} onClick={() => open(r.id)}>
              <span className="badge">{r.kind}</span>
              <span className={cls("badge", `mode-${r.mode}`)}>{r.mode}</span>
              <span className="muted">{fmtTime(r.created_at)}</span>
            </li>
          ))}
          {!reports.length && <li className="muted">暂无报告。</li>}
        </ul>
      </section>
      {current && (
        <section>
          <h3>报告：{current.kind}</h3>
          <details open><summary>Markdown</summary><pre className="md">{current.markdown}</pre></details>
          <details><summary>结构化 JSON</summary><pre className="md">{current.json}</pre></details>
        </section>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Env */
export function EnvPanel() {
  const [env, setEnv] = useState<any | null>(null);
  const [models, setModels] = useState<any | null>(null);
  const [err, setErr] = useState("");

  const load = async () => {
    try { setEnv(await api.get("/api/env/adapters")); }
    catch (e: any) { setErr(e.message); }
  };
  useEffect(() => { load(); }, []);

  return (
    <div className="panel">
      <section>
        <h3>Adapter 能力（Windows Sol / WSL Worker）</h3>
        <button onClick={load}>重新探测</button>
        {err && <div className="alert error">{err}</div>}
        {env && (
          <table className="mini wide">
            <thead><tr><th>角色</th><th>状态</th><th>详情</th></tr></thead>
            <tbody>
              <tr><td>Windows Sol</td>
                <td className={env.windows_sol.status === "PASS" ? "ok" : "bad"}>{env.windows_sol.status}</td>
                <td className="muted">{env.windows_sol.detail}</td></tr>
              <tr><td>WSL Worker</td>
                <td className={env.wsl_worker.status === "PASS" ? "ok" : "bad"}>{env.wsl_worker.status}</td>
                <td className="muted">{env.wsl_worker.detail}</td></tr>
            </tbody>
          </table>
        )}
      </section>
      <section>
        <h3>运行时模型（从 Codex app-server 查询）</h3>
        <button onClick={async () => { try { setModels(await api.get("/api/models")); } catch (e: any) { setErr(e.message); } }}>
          查询模型列表
        </button>
        {models && (
          <div className="muted">
            来源：{models.source} {models.error ? `（${models.error}）` : ""}
            <ul>{models.models.map((m: any) => <li key={m.id} className="mono">{m.id} — {m.display} · 档位 {m.efforts.join("/")}</li>)}</ul>
          </div>
        )}
      </section>
      <section>
        <h3>会话配置调整（切强度保留历史）</h3>
        <SessionConfigForm />
      </section>
    </div>
  );
}

function SessionConfigForm() {
  const [sessionId, setSessionId] = useState("");
  const [effort, setEffort] = useState("medium");
  const [model, setModel] = useState("");
  const [msg, setMsg] = useState("");
  return (
    <div className="row wrap">
      <input placeholder="session_id" value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
      <input placeholder="model（可空）" value={model} onChange={(e) => setModel(e.target.value)} />
      <select value={effort} onChange={(e) => setEffort(e.target.value)}>
        {["low", "medium", "high", "xhigh", "max"].map((x) => <option key={x}>{x}</option>)}
      </select>
      <button onClick={async () => {
        try {
          const r = await api.post(`/api/sessions/${sessionId}/config`, { model: model || null, reasoning_effort: effort });
          setMsg(`已更新：model=${r.model || "-"} effort=${r.reasoning_effort}（下一轮生效，历史保留）`);
        } catch (e: any) { setMsg(`失败：${e.message}`); }
      }}>更新会话配置</button>
      {msg && <span className="muted">{msg}</span>}
    </div>
  );
}
