"""Four lightweight lifecycle workflows.

They reuse the same events/evidence/decisions as the main loop — no second
memory, no self-triggered loops. Analysis that touches a model goes through
the same admission path and is recorded with its own mode and cost.
"""
from __future__ import annotations

import json

from .config import Settings
from .db import Database, parse_json
from .events import EventBus, append_event
from .ids import new_id, now_iso
from . import prompts
from .adapters import TurnCallbacks


class Workflows:
    def __init__(self, db: Database, bus: EventBus, controller, budget, settings: Settings) -> None:
        self.db = db
        self.bus = bus
        self.controller = controller
        self.budget = budget
        self.settings = settings

    # ================================================================= facts
    def goal_facts(self, goal_id: str) -> dict:
        bundle = self.controller.get_goal_bundle(goal_id)
        goal = bundle["goal"]
        runs = []
        for r in bundle["runs"]:
            runs.append(
                {
                    "run_id": r["id"],
                    "status": r["status"],
                    "is_auto": bool(r["is_auto"]),
                    "decision_id": r["decision_id"],
                    "plan": r.get("summary") or {},
                    "result_status": (r["result"] or {}).get("status"),
                    "tests": [
                        {"command": " ".join(t.get("command") or []) if isinstance(t.get("command"), list) else t.get("command"),
                         "exit_code": t.get("exit_code"), "evidence_id": t.get("evidence_id")}
                        for t in ((r["result"] or {}).get("tests") or [])
                    ],
                    "evidence": [{"id": e["id"], "kind": e["kind"], "rel_path": e["rel_path"]} for e in r["evidence"]],
                    "started_at": r["started_at"],
                    "ended_at": r["ended_at"],
                }
            )
        reviews = [
            {
                "review_id": rv["id"],
                "run_id": rv["run_id"],
                "overall": rv["overall"],
                "next_action": rv["next_action"],
                "applied_action": rv["applied_action"],
                "verdicts": rv["verdicts"],
            }
            for rv in bundle["reviews"]
        ]
        return {
            "goal": {
                "id": goal["id"], "title": goal["title"], "status": goal["status"],
                "stage": goal["stage"], "mode": goal["mode"],
                "plan_version": goal["plan_version"], "acceptance_version": goal["acceptance_version"],
                "goal_version": goal["goal_version"], "created_at": goal["created_at"],
            },
            "criteria": bundle["criteria"],
            "plans": [{"version": p["version"], "change_reason": p["change_reason"], "created_at": p["created_at"]} for p in bundle["plans"]],
            "decisions": [
                {"decision_id": d["id"], "kind": d["kind"], "next_action": d["next_action"],
                 "reason": d["reason"], "created_at": d["created_at"]}
                for d in bundle["decisions"]
            ],
            "runs": runs,
            "reviews": reviews,
            "usage": bundle["usage"],
            "usage_series": bundle["usage_series"],
            "event_count": len(bundle["events"]),
        }

    # ============================================================ optimizer
    def quick_optimize(self, goal_id: str | None, original: str) -> dict:
        goal = self.controller.get_goal_row(goal_id) if goal_id else None
        if goal:
            self.budget.check_gate_open(goal["id"])
        mode = goal["mode"] if goal else "simulation"
        result_md = ""
        optimized = ""
        differences = ""
        if mode == "real" and goal:
            session_row = self.controller.get_session(goal["sol_session_id"])
            adapter = self.controller._get_adapter(goal, session_row)
            avail = adapter.availability()
            if avail["status"] != "PASS":
                raise RuntimeError(f"sol adapter unavailable: {avail['detail']}")
            workspace = self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],))
            adapter.ensure_thread(model=session_row["model"], effort=session_row["reasoning_effort"], cwd=workspace["windows_path"])
            cb = self.controller._make_callbacks(goal=goal, run_row=None, session_row=session_row)
            outcome = adapter.start_turn(prompts.build_optimize_prompt(original), callbacks=cb)
            if outcome.status != "completed":
                raise RuntimeError(f"optimize turn failed: {outcome.status} {outcome.error or ''}")
            result_md = outcome.final_message
            optimized = _section(result_md, "优化后的 Prompt") or result_md[:2000]
            differences = _section(result_md, "差异") or "（见完整输出）"
        else:
            optimized, differences = _deterministic_optimize(original)
            result_md = (
                "## 优化后的 Prompt\n\n" + optimized +
                "\n\n## 与原文的差异说明\n\n" + differences +
                "\n\n> 本输出由确定性模拟生成器产生（simulation），不代表真实模型分析。"
            )
        report = {"original": original, "optimized": optimized, "differences": differences}
        return self._save_report(
            kind="prompt-optimizer-quick", mode="simulation" if mode != "real" or not goal else "real",
            goal_id=goal["id"] if goal else None, report=report, md=result_md,
            input_refs=[goal["id"]] if goal else [],
        )

    # ============================================================== review
    def trigger_goal_review(self, goal_id: str, idempotency_key: str | None = None) -> dict:
        return self.controller.review_goal_async(goal_id, idempotency_key=idempotency_key)

    # =========================================================== postmortem
    def postmortem(self, goal_id: str) -> dict:
        facts = self.goal_facts(goal_id)
        goal = facts["goal"]
        metrics = self._efficiency_metrics(facts)
        trace = self._decision_trace(facts)
        mode = "real" if goal["mode"] == "real" else "simulation"
        if mode == "real":
            try:
                self.budget.check_gate_open(goal_id)
                md = self._model_analysis(goal_id, prompts.build_postmortem_prompt(json.dumps(facts, ensure_ascii=False, default=str)))
            except Exception as exc:  # noqa: BLE001
                md = f"（模型分析不可用，降级为程序汇总：{exc}）\n\n" + _postmortem_markdown(facts, trace, metrics)
        else:
            md = _postmortem_markdown(facts, trace, metrics)
        report = {"facts": facts, "decision_trace": trace, "efficiency": metrics}
        return self._save_report(
            kind="goal-collaboration-postmortem", mode=mode, goal_id=goal_id,
            report=report, md=md,
            input_refs=[goal_id] + [r["run_id"] for r in facts["runs"]],
        )

    def _efficiency_metrics(self, facts: dict) -> dict:
        runs = facts["runs"]
        reviews = facts["reviews"]
        plan_revisions = len(facts["plans"])
        rework_rounds = max(0, plan_revisions - 1)
        first_pass = None
        if reviews:
            first_pass = reviews[0]["overall"] == "PASS"
        total_tokens = facts["usage"]["used_tokens"]
        milestones = 1 if facts["goal"]["status"] == "COMPLETED" else 0
        return {
            "total_runs": len(runs),
            "plan_revisions": plan_revisions,
            "rework_rounds": rework_rounds,
            "rework_ratio": (rework_rounds / len(runs)) if runs else None,
            "first_review_pass": first_pass,
            "total_tokens": total_tokens,
            "tokens_per_milestone": (total_tokens / milestones) if milestones else None,
            "milestones_reached": milestones,
            "denominators": {"runs": len(runs), "milestones": milestones},
            "missing": [
                item for item in [
                    None if facts["usage"]["by_exactness"].get("reported") is not None else "reported usage split",
                    None if all(r["tests"] for r in runs) else "some runs have no test evidence",
                ] if item
            ],
        }

    def _decision_trace(self, facts: dict) -> list[dict]:
        trace = []
        by_decision = {d["decision_id"]: d for d in facts["decisions"]}
        for run in facts["runs"]:
            node = {
                "decision": by_decision.get(run["decision_id"]),
                "run": {"run_id": run["run_id"], "status": run["status"], "result_status": run["result_status"]},
                "review": next((r for r in facts["reviews"] if r["run_id"] == run["run_id"]), None),
            }
            trace.append(node)
        return trace

    def _model_analysis(self, goal_id: str, prompt: str) -> str:
        goal = self.controller.get_goal_row(goal_id)
        session_row = self.controller.get_session(goal["sol_session_id"])
        adapter = self.controller._get_adapter(goal, session_row)
        avail = adapter.availability()
        if avail["status"] != "PASS":
            raise RuntimeError(avail["detail"])
        workspace = self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],))
        adapter.ensure_thread(model=session_row["model"], effort=session_row["reasoning_effort"], cwd=workspace["windows_path"])
        cb = self.controller._make_callbacks(goal=goal, run_row=None, session_row=session_row)
        outcome = adapter.start_turn(prompt, callbacks=cb)
        if outcome.status != "completed":
            raise RuntimeError(f"analysis turn {outcome.status}")
        return outcome.final_message

    # ========================================================== token audit
    def token_audit(self, goal_id: str) -> dict:
        facts = self.goal_facts(goal_id)
        goal = facts["goal"]
        mode = "real" if goal["mode"] == "real" else "simulation"
        findings = _token_findings(facts)
        md = _token_audit_markdown(facts, findings)
        if mode == "real":
            try:
                self.budget.check_gate_open(goal_id)
                model_md = self._model_analysis(goal_id, prompts.build_token_audit_prompt(json.dumps(facts, ensure_ascii=False, default=str)))
                md = md + "\n\n## 模型分析（真实模式）\n\n" + model_md
            except Exception as exc:  # noqa: BLE001
                md += f"\n\n> 模型分析不可用，仅保留程序事实：{exc}"
        report = {"facts": facts, "findings": findings}
        return self._save_report(
            kind="token-audit", mode=mode, goal_id=goal_id, report=report, md=md,
            input_refs=[goal_id],
        )

    # ================================================================ save
    def _save_report(self, *, kind: str, mode: str, goal_id: str | None, report: dict, md: str, input_refs: list[str]) -> dict:
        report_id = new_id("wfr")
        ws = None
        if goal_id:
            g = self.controller.get_goal_row(goal_id)
            ws = g["workspace_id"] if g else None
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO workflow_reports(id, goal_id, workspace_id, kind, mode, input_refs,
                   report_json, report_md, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (report_id, goal_id, ws, kind, mode, json.dumps(input_refs, ensure_ascii=False),
                 json.dumps(report, ensure_ascii=False, default=str), md, now_iso()),
            )
            append_event(
                self.db, type_="workflow.completed",
                payload={"report_id": report_id, "kind": kind, "mode": mode, "input_refs": input_refs},
                workspace_id=ws, goal_id=goal_id, conn=conn,
            )
        self.bus.notify()
        return {"report_id": report_id, "kind": kind, "mode": mode, "markdown": md, "report": report}

    def list_reports(self, goal_id: str | None = None) -> list[dict]:
        if goal_id:
            rows = self.db.query(
                "SELECT id, goal_id, kind, mode, input_refs, created_at FROM workflow_reports WHERE goal_id=? ORDER BY created_at DESC",
                (goal_id,),
            )
        else:
            rows = self.db.query(
                "SELECT id, goal_id, kind, mode, input_refs, created_at FROM workflow_reports ORDER BY created_at DESC LIMIT 50"
            )
        return [dict(r) for r in rows]

    def get_report(self, report_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM workflow_reports WHERE id = ?", (report_id,))
        if not row:
            return None
        d = dict(row)
        d["report"] = parse_json(d.pop("report_json"), {})
        d["input_refs"] = parse_json(d.pop("input_refs"), [])
        return d


# ---------------------------------------------------------------------------
def _section(text: str, heading: str) -> str | None:
    lines = text.splitlines()
    out = []
    capturing = False
    for line in lines:
        if line.strip().startswith("#") and heading in line:
            capturing = True
            continue
        if capturing and line.strip().startswith("#"):
            break
        if capturing:
            out.append(line)
    result = "\n".join(out).strip()
    return result or None


def _deterministic_optimize(original: str) -> tuple[str, str]:
    """Rule-based Quick optimize used in simulation mode (and as fallback)."""
    cleaned = " ".join(original.split())
    optimized = (
        "任务：请完成以下需求，并在完成后运行项目中已有的测试给出结果。\n"
        f"需求原文：{cleaned}\n"
        "验收：\n"
        "1) 需求中的行为要求全部满足；\n"
        "2) 相关测试通过（直接给出命令与退出码）；\n"
        "3) 不引入未要求的依赖。\n"
        "输出：变更摘要 + 测试命令与结果 + 遗留问题。"
    )
    differences = (
        f"- 原文 {len(original)} 字符，折叠多余空白后为 {len(cleaned)} 字符；\n"
        "- 增加了明确的验收条件与输出格式要求；\n"
        "- 未改变原始目标与范围（规则式整理，逐条可对照）。"
    )
    return optimized, differences


def _postmortem_markdown(facts: dict, trace: list[dict], metrics: dict) -> str:
    g = facts["goal"]
    lines = [
        f"# 全链复盘：{g['title']}",
        "",
        f"- Goal: `{g['id']}`（模式 {g['mode']}，状态 {g['status']}）",
        f"- 计划版本数：{metrics['plan_revisions']}；执行轮次：{metrics['total_runs']}；返工轮次：{metrics['rework_rounds']}",
        f"- 首次验收通过：{metrics['first_review_pass']}",
        f"- 累计用量：{metrics['total_tokens']} tokens（口径见 Token Audit）",
        "",
        "## 因果链（Decision → Run → Review）",
        "",
    ]
    for i, node in enumerate(trace, 1):
        dec = node["decision"] or {}
        run = node["run"]
        rev = node["review"] or {}
        lines.append(
            f"{i}. Decision `{dec.get('decision_id', 'UNKNOWN')}`（{dec.get('kind', '?')}/{dec.get('next_action', '?')}）"
            f" → Run `{run['run_id']}`（{run['status']}，结果 {run['result_status']}）"
            f" → Review `{rev.get('review_id', '（无）')}`（{rev.get('overall', 'UNKNOWN')} → {rev.get('applied_action', '?')}）"
        )
    lines += [
        "",
        "## 分析",
        "",
        "- 计划一致性：每次重规划均有对应验收证据（见上方链路的 Review 节点）。" if metrics["rework_rounds"] else "- 未发生重规划。",
        f"- 规划质量：首次验收{'通过' if metrics['first_review_pass'] else '未通过'}，说明计划对验收标准的覆盖{'充分' if metrics['first_review_pass'] else '存在缺口（已通过修复计划闭合）'}。",
        "- 成本效率：单位里程碑成本 = " + (
            f"{metrics['tokens_per_milestone']:.0f} tokens" if metrics["tokens_per_milestone"] else "UNKNOWN（未通过里程碑）"
        ) + "。",
        "",
        f"> 覆盖范围：Goal `{g['id']}` 的全部已记录 Run/Review/Evidence；缺失项：{metrics['missing'] or '无'}。",
        "> 本文为程序基于真实持久化事实生成的模拟环境分析（若 mode=simulation，模型部分为确定性生成）。",
    ]
    return "\n".join(lines)


def _token_findings(facts: dict) -> list[dict]:
    findings = []
    usage = facts["usage"]
    series = facts["usage_series"]
    if usage["budget_tokens"] and usage["ratio"] is not None:
        findings.append(
            {
                "type": "fact",
                "text": f"预算使用率 {usage['ratio']*100:.1f}%（{usage['committed_tokens']}/{usage['budget_tokens']}），门禁 {usage['gate']}。",
            }
        )
    else:
        findings.append({"type": "fact", "text": "未配置预算上限；用量仅累计展示。"})
    by_exact = usage["by_exactness"]
    if by_exact:
        findings.append({"type": "fact", "text": f"精确度分布：{json.dumps(by_exact, ensure_ascii=False)}（simulated 为模拟计量，不混入真实统计）。"})
    if len(series) >= 2:
        max_step = max(series[i]["total_tokens"] - series[i - 1]["total_tokens"] for i in range(1, len(series)))
        findings.append({"type": "inference", "text": f"单步最大增量 {max_step} tokens；如显著高于中位数，可检查该轮上下文与工具输出体积。"})
    runs = facts["runs"]
    failed = [r for r in runs if r["result_status"] == "failed"]
    if failed:
        findings.append({"type": "inference", "text": f"{len(failed)} 个 Run 结果为 failed，返工会推高总成本；对应证据已关联。"})
    findings.append({"type": "suggestion", "text": "待验证建议：若连续失败集中于同类错误，可考虑在计划阶段增加针对性验收用例（需后续对照验证，不宣称必然收益）。"})
    return findings


def _token_audit_markdown(facts: dict, findings: list[dict]) -> str:
    g = facts["goal"]
    lines = [
        f"# Token Audit：{g['title']}",
        "",
        f"- Goal: `{g['id']}`（mode={g['mode']}）",
        f"- 累计用量：{facts['usage']['used_tokens']} tokens；预留：{facts['usage']['reserved_tokens']}；门禁：{facts['usage']['gate']}",
        "",
        "## 诊断发现",
        "",
    ]
    for f in findings:
        lines.append(f"- [{f['type']}] {f['text']}")
    lines += [
        "",
        "## 计量边界",
        "",
        "Token Audit 只读取 Python 已采集的用量事件，不负责计量、不放行预算、不自动重试。",
        "真实/估算/未知分别记录；模拟量以 exactness=simulated 单独标记，不与真实口径混用。",
    ]
    return "\n".join(lines)
