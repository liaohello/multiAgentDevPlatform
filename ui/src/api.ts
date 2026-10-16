const meta = document.querySelector('meta[name="agentproj-token"]') as HTMLMetaElement | null;
export const TOKEN = meta?.content && meta.content !== "__AGENTPROJ_TOKEN__" ? meta.content : "";

async function req<T = any>(method: string, url: string, body?: any, idem?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (TOKEN) headers["X-AgentProj-Token"] = TOKEN;
  if (idem) headers["Idempotency-Key"] = idem;
  const resp = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await resp.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!resp.ok) {
    const detail = data?.detail || data?.raw || resp.statusText;
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail)) as any;
    err.status = resp.status;
    throw err;
  }
  return data as T;
}

export const api = {
  get: <T = any>(url: string) => req<T>("GET", url),
  post: <T = any>(url: string, body?: any, idem?: string) => req<T>("POST", url, body, idem),
};

export function streamUrl(cursor: number, tseq: number): string {
  return `/api/stream?cursor=${cursor}&tseq=${tseq}&token=${encodeURIComponent(TOKEN)}`;
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 14) : "-";
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch { return iso; }
}

export function cls(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
