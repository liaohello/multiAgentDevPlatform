/**
 * agentProj 浏览器验收脚本（dev 工具，不随应用部署）。
 *
 * 前置：
 *   - 工作台已启动（默认 http://127.0.0.1:8787）
 *   - 可用 Chromium/Chrome 可执行文件（默认取 ~/.agent-browser 下的 chrome，可用 CHROME_PATH 覆盖）
 *   - playwright-core（NODE_PATH 指向安装位置）
 *
 * 运行：
 *   NODE_PATH=<node workspace>/node_modules node scripts/browser_verify.mjs [--url http://127.0.0.1:8787] [--out docs/reports/evidence/browser]
 *
 * 产出：多张截图 + browser_verify_result.json（A01/A05/A11 等证据）
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch (e) {
  const alt = process.env.PLAYWRIGHT_CORE_PATH;
  if (alt) ({ chromium } = require(alt));
  else {
    console.error("无法加载 playwright-core：请设置 NODE_PATH 或 PLAYWRIGHT_CORE_PATH");
    process.exit(2);
  }
}

const args = process.argv.slice(2);
function flag(name, def) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : def;
}
const URL = flag("--url", "http://127.0.0.1:8787");
const OUT = flag("--out", "docs/reports/evidence/browser");

const candidates = [
  process.env.CHROME_PATH,
  (() => {
    const base = path.join(os.homedir(), ".agent-browser", "browsers");
    if (!fs.existsSync(base)) return null;
    const dir = fs.readdirSync(base).find((d) => d.startsWith("chrome-"));
    return dir ? path.join(base, dir, "chrome.exe") : null;
  })(),
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
].filter(Boolean);
const CHROME = candidates.find((p) => fs.existsSync(p));
if (!CHROME) {
  console.error("未找到 Chrome/Chromium 可执行文件；请设置 CHROME_PATH");
  process.exit(2);
}

fs.mkdirSync(OUT, { recursive: true });
const result = { url: URL, chrome: CHROME, steps: [], screenshots: [], ok: true };
const shot = async (page, name) => {
  const file = path.join(OUT, name);
  await page.screenshot({ path: file, fullPage: false });
  result.screenshots.push(file);
  console.log(`  [shot] ${file}`);
};

async function api(page, pathname) {
  return page.evaluate(async (p) => {
    const token = document.querySelector('meta[name="agentproj-token"]')?.content || "";
    const r = await fetch(p, { headers: { "X-AgentProj-Token": token } });
    return await r.json();
  }, pathname);
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e)));

try {
  // ---- A01: page loads, service healthy ---------------------------------
  console.log("[A01] 打开工作台页面");
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(2500);
  const title = await page.title();
  const body = await page.locator("body").innerText();
  result.steps.push({ id: "A01", title, hasBrand: body.includes("agentProj 工作台"), hasTokenOK: body.includes("会话令牌已注入") });
  if (!body.includes("agentProj 工作台")) result.ok = false;
  await shot(page, "a01_dashboard.png");

  // ---- create a new goal through the UI ---------------------------------
  console.log("[A02] 通过 UI 创建并运行一个新 Goal");
  const goalTitle = `浏览器验收 ${new Date().toISOString().slice(11, 19)}`;
  await page.locator("aside input").first().fill(goalTitle);
  await page.getByRole("button", { name: "创建 Goal" }).click();
  await page.waitForTimeout(1500);
  const listText = await page.locator("aside.goal-list, aside").first().innerText();
  result.steps.push({ id: "UI-create", goalTitle, listed: listText.includes(goalTitle) });
  await shot(page, "a02_goal_created.png");

  // plan + start via UI buttons
  await page.getByRole("button", { name: "Sol 规划" }).click();
  await page.waitForTimeout(2500);
  await shot(page, "a03_planned.png");
  await page.getByRole("button", { name: "开始执行" }).click();

  // wait for completion (poll API through the page)
  let status = "", bundle = null;
  const goalId = await page.evaluate(() => {
    const el = document.querySelector(".goal-item.active");
    return el ? true : false;
  });
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(1500);
    const h2 = await page.locator(".goal-panel h2").first().innerText().catch(() => "");
    const bodyNow = await page.locator(".goal-panel").first().innerText().catch(() => "");
    if (bodyNow.includes("COMPLETED")) { status = "COMPLETED"; break; }
  }
  result.steps.push({ id: "UI-run", finalStatusOnPage: status || "TIMEOUT" });
  if (status !== "COMPLETED") result.ok = false;
  await shot(page, "a04_completed.png");

  // evidence expand: click the first evidence chip
  const chip = page.locator(".evidence-chip").first();
  if (await chip.count()) {
    await chip.click();
    await page.waitForTimeout(800);
    await shot(page, "a05_evidence_expanded.png");
  }

  // ---- A11: refresh does not restart runs -------------------------------
  console.log("[A11] 刷新页面：Run 计数不变、内容恢复");
  const before = await api(page, `/api/goals?limit=50`).then(() =>
    page.evaluate(async () => {
      const token = document.querySelector('meta[name="agentproj-token"]')?.content || "";
      const r = await fetch("/api/goals", { headers: { "X-AgentProj-Token": token } });
      const goals = await r.json();
      const g = goals[0];
      const rb = await fetch(`/api/goals/${g.id}`, { headers: { "X-AgentProj-Token": token } });
      const bundle = await rb.json();
      return { goalId: g.id, runs: bundle.runs.length, status: bundle.goal.status };
    })
  );
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  const after = await page.evaluate(async () => {
    const token = document.querySelector('meta[name="agentproj-token"]')?.content || "";
    const r = await fetch("/api/goals", { headers: { "X-AgentProj-Token": token } });
    const goals = await r.json();
    const g = goals[0];
    const rb = await fetch(`/api/goals/${g.id}`, { headers: { "X-AgentProj-Token": token } });
    const bundle = await rb.json();
    return { goalId: g.id, runs: bundle.runs.length, status: bundle.goal.status };
  });
  result.steps.push({ id: "A11", before, after, noExtraRuns: before.runs === after.runs });
  if (before.runs !== after.runs) result.ok = false;
  await shot(page, "a06_after_refresh.png");

  // ---- other panels ------------------------------------------------------
  console.log("[panels] 各页签截图");
  for (const [tabName, file] of [["Skills", "a07_skills.png"], ["Wiki", "a08_wiki.png"], ["复盘与审计", "a09_reports.png"], ["环境与能力", "a10_env.png"]]) {
    await page.getByRole("button", { name: tabName }).click();
    await page.waitForTimeout(1200);
    await shot(page, file);
  }

  result.pageErrors = pageErrors;
} finally {
  await browser.close();
}

fs.writeFileSync(path.join(OUT, "browser_verify_result.json"), JSON.stringify(result, null, 1), "utf-8");
console.log("RESULT:", JSON.stringify({ ok: result.ok, steps: result.steps, pageErrors: result.pageErrors }, null, 1));
process.exit(result.ok ? 0 : 1);
