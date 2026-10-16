"""Prompt builders for real Sol/Worker turns.

Every prompt starts with a machine marker `[[AGENTPROJ_KIND:...]]` so the
deterministic simulation director can dispatch without inspecting prose.
The marker is harmless for real models (kept out of the reasoning path).
"""
from __future__ import annotations

import json
import re

KIND_RE = re.compile(r"\[\[AGENTPROJ_KIND:(\w+)\]\]")


def kind_of(prompt: str) -> str | None:
    m = KIND_RE.search(prompt)
    return m.group(1) if m else None


def _strictify(schema):
    """OpenAI strict structured outputs: every object needs additionalProperties=false and all keys required."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            schema["additionalProperties"] = False
            if "properties" in schema:
                schema["required"] = list(schema["properties"].keys())
        for value in list(schema.values()):
            _strictify(value)
    elif isinstance(schema, list):
        for value in schema:
            _strictify(value)
    return schema


PLAN_OUTPUT_SCHEMA = _strictify(
    {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "acceptance": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "text": {"type": "string"},
                        "required": {"type": "boolean"},
                    },
                },
            },
            "steps": {"type": "array", "items": {"type": "string"}},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "instructions": {"type": "string"},
                        "deliverable": {"type": "string"},
                        "verify_commands": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                    },
                },
            },
            "notes": {"type": "string"},
        },
    }
)

REVIEW_OUTPUT_SCHEMA = _strictify(
    {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["PASS", "FAIL", "BLOCKED", "UNKNOWN"]},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                },
            },
            "overall": {"type": "string", "enum": ["PASS", "FAIL", "BLOCKED", "UNKNOWN"]},
            "next_action": {"type": "string", "enum": ["complete", "fix", "replan", "request_user"]},
            "next_task": {
                "type": ["object", "null"],
                "properties": {
                    "title": {"type": "string"},
                    "instructions": {"type": "string"},
                    "deliverable": {"type": "string"},
                    "verify_commands": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                },
            },
            "note": {"type": "string"},
        },
    }
)

WORKER_RESULT_FORMAT = """最终回复必须只包含一个 JSON 对象（不要使用 markdown 代码块），格式如下：
{
  "status": "completed | failed",
  "summary": "做了什么、结果如何（简短）",
  "files_changed": ["相对路径"],
  "tests_run": [{"command": "命令字符串", "exit_code": 0}],
  "notes": "遗留问题或不确定项（可空字符串）"
}"""


def build_plan_prompt(goal: dict, workspace: dict, *, prior_plan_md: str | None = None, failure_note: str | None = None) -> str:
    parts = [
        "[[AGENTPROJ_KIND:plan]]",
        "你是 Sol（规划与验收角色，运行在 Windows）。请为下面的目标制定实施计划。",
        "",
        f"目标标题：{goal['title']}",
        f"用户原始需求：\n{goal['original_request']}",
        "",
        f"工作目录（Windows）：{workspace.get('windows_path')}",
        f"工作目录（WSL 映射）：{workspace.get('wsl_path') or '未配置'}",
        "",
        "要求：",
        "1. 给出可逐项核验的验收标准（acceptance），每项包含 key（C1、C2…）、文本、是否必需。",
        "2. 给出任务列表（tasks），每个任务有明确指令、交付物与验证命令（verify_commands，argv 数组形式，例如 [\"python\", \"-m\", \"pytest\", \"-q\"]）。",
        "3. 执行者为 WSL 内的编码代理，只在本工作目录内修改文件。",
        "4. 只输出符合给定 JSON schema 的 JSON。",
    ]
    if prior_plan_md:
        parts += ["", "上一版计划（供修订参考）：", prior_plan_md[:4000]]
    if failure_note:
        parts += ["", "修订原因（来自上一轮验收证据）：", failure_note[:2000]]
    return "\n".join(parts)


def build_worker_prompt(goal: dict, task: dict, criteria: list[dict], workspace: dict, *, round_note: str | None = None) -> str:
    crit_lines = "\n".join(f"- {c['criterion_key']}: {c['text']}" for c in criteria)
    verify = task.get("verify_commands") or [["python", "-m", "pytest", "-q"]]
    verify_text = "\n".join("  " + " ".join(argv) for argv in verify)
    parts = [
        "[[AGENTPROJ_KIND:worker]]",
        "你是执行者（WSL 内的编码代理）。请完成下面的任务，并在工作目录内自行运行测试验证。",
        "",
        f"目标：{goal['title']}",
        f"工作目录：{workspace.get('wsl_path') or workspace.get('windows_path')}",
        "",
        f"本轮任务：{task.get('title')}",
        f"任务说明：\n{task.get('instructions')}",
        f"交付物：{task.get('deliverable') or '（未指定）'}",
        "",
        "验收标准（供参考，不需要你逐项声明）：",
        crit_lines,
        "",
        "必须运行以下验证命令并记录退出码：",
        verify_text,
        "",
        "约束：",
        "- 只修改本工作目录内的文件；不要修改 .agentproj/ 下的任何内容。",
        "- 不要引入第三方依赖（除任务明确规定）。",
        "- 如果测试失败，如实报告，不要伪造通过。",
        "",
        WORKER_RESULT_FORMAT,
    ]
    if round_note:
        parts += ["", "上一轮反馈（本轮需针对性修复）：", round_note[:2000]]
    return "\n".join(parts)


def build_review_prompt(
    goal: dict,
    criteria: list[dict],
    plan_md: str,
    result: dict,
    evidence_pack: list[dict],
    snapshot_ref: str,
    *,
    versions: dict,
) -> str:
    crit_lines = "\n".join(
        f"- criterion_id={c['criterion_key']} ({'必需' if c['required'] else '可选'}): {c['text']}" for c in criteria
    )
    ev_lines = "\n".join(
        f"- evidence_id={e['id']} kind={e['kind']} path={e['rel_path']} meta={json.dumps(e.get('meta', {}), ensure_ascii=False)[:300]}"
        for e in evidence_pack
    )
    return "\n".join(
        [
            "[[AGENTPROJ_KIND:review]]",
            "你是 Sol（验收角色）。请对照冻结的验收标准，逐项审阅下面的执行证据，给出验收判定与下一步建议。",
            "",
            f"目标：{goal['title']}",
            f"版本：goal_version={versions.get('goal_version')} plan_version={versions.get('plan_version')} acceptance_version={versions.get('acceptance_version')}",
            f"代码快照引用：{snapshot_ref}",
            "",
            "验收标准：",
            crit_lines,
            "",
            "计划（摘要）：",
            plan_md[:3000],
            "",
            "执行结果（执行者报告，仅作候选信息）：",
            json.dumps(result, ensure_ascii=False)[:3000],
            "",
            "程序采集的证据（判定必须引用这些 evidence_id；没有证据支持的项不能判 PASS）：",
            ev_lines or "（无证据）",
            "",
            "判定规则：",
            "- PASS：有证据满足标准；FAIL：有证据表明不满足；BLOCKED：已知外部依赖阻断验证；UNKNOWN：证据缺失。",
            "- 测试通过不等于所有用户目标达成；执行者的自述不能单独构成 PASS。",
            "- next_action：complete（全部必需项通过）/ fix（范围明确的修复）/ replan（需调整计划）/ request_user（需要用户决定）。",
            "- 若 next_action 为 fix，请在 next_task 中给出修复任务（含验证命令）。",
            "只输出符合给定 JSON schema 的 JSON。",
        ]
    )


def build_optimize_prompt(original: str) -> str:
    return "\n".join(
        [
            "[[AGENTPROJ_KIND:optimize]]",
            "你是 Prompt Optimizer（Quick 模式）。请把下面的原始需求整理为可执行的任务契约，并给出优化后的 Prompt。",
            "要求：不改变用户原意；输出包含 '优化后的 Prompt' 与 '与原文的差异说明' 两部分纯文本。",
            "",
            "原始需求：",
            original,
        ]
    )


def build_postmortem_prompt(facts_json: str) -> str:
    return "\n".join(
        [
            "[[AGENTPROJ_KIND:postmortem]]",
            "你是 Goal Collaboration Postmortem 分析者。请基于下面由程序汇总的真实事实，分析该 Goal 的规划、执行、反馈、重规划与成本因果链。",
            "缺失的数据必须标注 UNKNOWN，不得编造。输出 Markdown。",
            "",
            "事实数据（JSON）：",
            facts_json[:12000],
        ]
    )


def build_token_audit_prompt(facts_json: str) -> str:
    return "\n".join(
        [
            "[[AGENTPROJ_KIND:token_audit]]",
            "你是 Token Audit 分析者。请基于程序已采集的用量事实，诊断高消耗原因与改进假设。",
            "你不负责计量、不放行预算；区分事实、推断和待验证建议。输出 Markdown。",
            "",
            "用量事实（JSON）：",
            facts_json[:12000],
        ]
    )
