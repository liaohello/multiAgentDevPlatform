"""Deterministic simulation director.

Only the external model runtime is simulated. File edits, command execution,
evidence collection, budget accounting, persistence and state transitions are
the real implementations. All simulated usage is exactness='simulated'.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .adapters.base import FakeScriptContext
from .adapters.fake import FakeTurnContext
from .ids import now_iso
from .prompts import kind_of

DEMO_STUB = '''"""normalize_tags: 按逗号拆分、去首尾空白、忽略空项、去重并保留顺序。"""


def normalize_tags(text: str) -> list[str]:
    raise NotImplementedError("TODO: implement normalize_tags")
'''

DEMO_TESTS = '''"""normalize_tags 的标准库测试（unittest）。运行：python -m pytest -q 或 python -m unittest"""
import unittest

from normalize_tags import normalize_tags


class NormalizeTagsTest(unittest.TestCase):
    def test_basic_split(self):
        self.assertEqual(normalize_tags("a, b, c"), ["a", "b", "c"])

    def test_strip_whitespace(self):
        self.assertEqual(normalize_tags(" a , b "), ["a", "b"])

    def test_drop_empty(self):
        self.assertEqual(normalize_tags("a,,b,"), ["a", "b"])

    def test_dedupe_keep_order(self):
        self.assertEqual(normalize_tags("b,a,b,a"), ["b", "a"])


if __name__ == "__main__":
    unittest.main()
'''

DEMO_README = """# Demo 任务工作目录

由 agentProj 工作台创建的隔离演示目录。任务：实现 `normalize_tags(text)`：

1. 按逗号拆分
2. 去除每项首尾空白
3. 忽略空项
4. 去重并保留首次出现顺序

验证：`python -m pytest -q`（或 `python -m unittest`）。
"""

BUGGY_IMPL = '''"""normalize_tags: 按逗号拆分、去首尾空白、忽略空项、去重并保留顺序。"""


def normalize_tags(text: str) -> list[str]:
    # 第一版实现（有缺陷：未去空白、未去重、未忽略空项）
    return text.split(",")
'''

FIXED_IMPL = '''"""normalize_tags: 按逗号拆分、去首尾空白、忽略空项、去重并保留顺序。"""


def normalize_tags(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in text.split(","):
        tag = part.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result
'''


def seed_demo_workspace(workspace_dir: str | Path) -> None:
    """Idempotent seed: only writes files that do not exist yet."""
    root = Path(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "README.md": DEMO_README,
        "normalize_tags.py": DEMO_STUB,
        "test_normalize_tags.py": DEMO_TESTS,
    }
    for name, content in files.items():
        target = root / name
        if not target.exists():
            target.write_text(content, encoding="utf-8")


class SimulationDirector:
    """Builds fake handlers that react to the *real* state in the database."""

    def __init__(self, controller) -> None:
        self.controller = controller

    # ------------------------------------------------------------- dispatch
    def sol_handler(self, goal_id: str):
        def handler(ctx: FakeTurnContext) -> str:
            kind = kind_of(ctx.prompt) or "plan"
            if kind == "plan":
                return self._sol_plan(ctx, goal_id)
            if kind == "review":
                return self._sol_review(ctx, goal_id)
            return "{}"
        return handler

    def worker_handler(self, goal_id: str):
        def handler(ctx: FakeTurnContext) -> str:
            scenario = self._scenario(goal_id)
            if scenario == "cancel":
                return self._worker_long(ctx, goal_id)
            return self._worker_implement(ctx, goal_id)
        return handler

    # ---------------------------------------------------------------- shared
    def _scenario(self, goal_id: str) -> str:
        goal = self.controller.get_goal_row(goal_id)
        policy = json.loads(goal["budget_policy"] or "{}") if goal else {}
        return policy.get("scenario", "demo")

    def _sol_plan(self, ctx: FakeTurnContext, goal_id: str) -> str:
        goal = self.controller.get_goal_row(goal_id)
        plan_version = int(goal["plan_version"] or 0)
        ctx.emit_delta("message", f"分析目标：{goal['title']}…\n")
        ctx.sleep(0.4)
        ctx.emit_delta("message", "拆解验收标准：行为正确性 / 测试通过 / 无第三方依赖。\n")
        ctx.sleep(0.4)
        plan = {
            "summary": "实现 normalize_tags 并以其标准库测试验证。",
            "acceptance": [
                {"key": "C1", "text": "normalize_tags 按逗号拆分、去首尾空白、忽略空项、去重并保留顺序", "required": True},
                {"key": "C2", "text": "标准库测试全部通过（python -m pytest -q 退出码 0）", "required": True},
                {"key": "C3", "text": "不引入第三方依赖", "required": True},
            ],
            "steps": [
                "在演示工作目录实现 normalize_tags",
                "运行标准库测试",
                "根据测试结果修复直至全部通过",
            ],
            "tasks": [
                {
                    "title": "实现 normalize_tags",
                    "instructions": "在工作目录的 normalize_tags.py 中实现规范函数；运行 python -m pytest -q；如实报告结果。",
                    "deliverable": "normalize_tags.py",
                    "verify_commands": [["{python}", "-m", "pytest", "-q"]],
                }
            ],
            "notes": f"计划版本 v{plan_version + 1}（模拟生成）。",
        }
        ctx.report_usage({"input_tokens": 1500, "output_tokens": 300, "total_tokens": 1800})
        return json.dumps(plan, ensure_ascii=False)

    def _sol_review(self, ctx: FakeTurnContext, goal_id: str) -> str:
        run = self.controller.latest_finished_run(goal_id)
        evidence = self.controller.list_run_evidence(run["id"]) if run else []
        result = self.controller.get_run_result(run["id"]) if run else None
        tests = (result or {}).get("tests", [])
        exit_codes = [t.get("exit_code") for t in tests if t.get("exit_code") is not None]
        tests_ok = bool(exit_codes) and all(code == 0 for code in exit_codes)

        # C3 checked for real: no third-party imports in normalize_tags.py
        impl_path = Path(self.controller.workspace_path_for_goal(goal_id)) / "normalize_tags.py"
        no_third_party = True
        try:
            content = impl_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    module = stripped.split()[1].split(".")[0]
                    if module not in ("__future__", "unittest", "typing", "re", "sys", "os"):
                        no_third_party = False
        except OSError:
            no_third_party = False

        verify_ev = [e["id"] for e in evidence if e["kind"] == "command"]
        snap_ev = [e["id"] for e in evidence if e["kind"] == "snapshot"]
        verdicts = [
            {
                "criterion_id": "C1",
                "status": "PASS" if tests_ok else "FAIL",
                "evidence_ids": verify_ev[:1],
                "reason": "标准库测试全部通过，行为符合规格。" if tests_ok else "测试未通过：实现未满足全部行为要求。",
            },
            {
                "criterion_id": "C2",
                "status": "PASS" if tests_ok else "FAIL",
                "evidence_ids": verify_ev[:1],
                "reason": "pytest 退出码 0。" if tests_ok else "pytest 退出码非 0。",
            },
            {
                "criterion_id": "C3",
                "status": "PASS" if no_third_party else "FAIL",
                "evidence_ids": snap_ev[:1],
                "reason": "实现仅使用标准库。" if no_third_party else "检测到非标准库导入。",
            },
        ]
        all_pass = all(v["status"] == "PASS" for v in verdicts)
        ctx.emit_delta("message", "逐项核对证据…\n")
        ctx.sleep(0.3)
        for v in verdicts:
            ctx.emit_delta("message", f"  {v['criterion_id']}: {v['status']}\n")
        if all_pass:
            payload = {"verdicts": verdicts, "overall": "PASS", "next_action": "complete", "note": "全部必需项有证据通过。"}
        else:
            payload = {
                "verdicts": verdicts,
                "overall": "FAIL",
                "next_action": "fix",
                "next_task": {
                    "title": "修复 normalize_tags 实现",
                    "instructions": "按规格修复：去首尾空白、忽略空项、去重并保留顺序；再次运行 python -m pytest -q。",
                    "deliverable": "normalize_tags.py",
                    "verify_commands": [["{python}", "-m", "pytest", "-q"]],
                },
                "note": "测试失败，需最小范围修复。",
            }
        ctx.report_usage({"input_tokens": 600, "output_tokens": 100, "total_tokens": 700})
        return json.dumps(payload, ensure_ascii=False)

    def _worker_implement(self, ctx: FakeTurnContext, goal_id: str) -> str:
        goal = self.controller.get_goal_row(goal_id)
        plan_version = int(goal["plan_version"] or 1)
        ctx.emit_delta("message", f"读取任务与现有实现（计划 v{plan_version}）…\n")
        ctx.sleep(0.3)
        if plan_version >= 2:
            ctx.write_file("normalize_tags.py", FIXED_IMPL)
            ctx.emit_delta("message", "已按修复要求更新 normalize_tags.py。\n")
        else:
            ctx.write_file("normalize_tags.py", BUGGY_IMPL)
            ctx.emit_delta("message", "已写入第一版实现。\n")
        ctx.emit_event("run.file_change", {"status": "completed", "changes": [{"path": "normalize_tags.py", "kind": "update"}]})
        ctx.sleep(0.3)
        ctx.emit_delta("message", "运行验证命令：python -m pytest -q\n")
        cmd = ctx.run_command([sys.executable, "-m", "pytest", "-q"])
        tail = (cmd["stdout"] + cmd["stderr"])[-1200:]
        ctx.emit_delta("command", f"[exit {cmd['exit_code']}] pytest -q\n{tail}\n")
        ok = cmd["exit_code"] == 0
        ctx.report_usage({"input_tokens": 3000, "output_tokens": 500, "total_tokens": 3500})
        message = {
            "status": "completed" if ok else "failed",
            "summary": "实现完成，测试通过。" if ok else "实现完成，但测试未通过。",
            "files_changed": ["normalize_tags.py"],
            "tests_run": [{"command": "python -m pytest -q", "exit_code": cmd["exit_code"]}],
            "notes": "" if ok else "实现仍有缺陷，需要修复。",
        }
        return json.dumps(message, ensure_ascii=False)

    def _worker_long(self, ctx: FakeTurnContext, goal_id: str) -> str:
        ctx.emit_delta("message", "开始长任务（用于取消语义验证）…\n")
        for i in range(60):
            if ctx.stop_requested():
                ctx.emit_delta("message", "收到中断请求，停止执行。\n")
                ctx.report_usage({"input_tokens": 200, "output_tokens": 20, "total_tokens": 220})
                return json.dumps(
                    {"status": "failed", "summary": "被中断", "files_changed": [], "tests_run": [], "notes": "interrupted"},
                    ensure_ascii=False,
                )
            ctx.sleep(0.5)
            ctx.emit_delta("message", f"step {i + 1}/60…\n")
        ctx.report_usage({"input_tokens": 3000, "output_tokens": 500, "total_tokens": 3500})
        return json.dumps(
            {"status": "completed", "summary": "长任务完成", "files_changed": [], "tests_run": [], "notes": ""},
            ensure_ascii=False,
        )
