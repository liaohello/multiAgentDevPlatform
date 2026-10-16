"""Runtime configuration. All values can be overridden with AGENTPROJ_* env vars.

No credentials are read or stored here. Codex authentication stays in the
runtime's own native store (~/.codex or the WSL home), managed by the user.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


class Settings:
    def __init__(self) -> None:
        self.project_root: Path = PROJECT_ROOT
        self.data_dir = Path(_env("AGENTPROJ_DATA_DIR", str(PROJECT_ROOT / ".agentproj")))
        self.db_path = Path(_env("AGENTPROJ_DB", str(self.data_dir / "state.sqlite")))
        self.goals_dir = self.data_dir / "goals"
        self.imports_dir = self.data_dir / "imports"
        self.wiki_dir = self.data_dir / "wiki"
        self.skills_dir = self.data_dir / "skills"
        self.evidence_dir = self.data_dir / "evidence"
        self.demo_workspace = self.data_dir / "demo-workspace"
        self.ui_dist = PROJECT_ROOT / "ui" / "dist"

        self.host = _env("AGENTPROJ_HOST", "127.0.0.1")
        self.port = int(_env("AGENTPROJ_PORT", "8787"))

        # Local auth: token is generated at startup unless the user pins one.
        self.pinned_token = _env("AGENTPROJ_TOKEN")
        self.token: str | None = None  # set by main at startup

        # Codex binary for the Windows Sol adapter.
        self.codex_bin = _env("AGENTPROJ_CODEX_BIN") or self._detect_codex_bin()

        # WSL side. Distro empty -> auto detect via `wsl -l -q`.
        self.wsl_distro = _env("AGENTPROJ_WSL_DISTRO")
        self.wsl_codex_cmd = _env("AGENTPROJ_WSL_CODEX_CMD", "codex")

        # Timeouts / bounds.
        self.turn_timeout_sec = int(_env("AGENTPROJ_TURN_TIMEOUT", "1800"))
        self.max_auto_rounds = int(_env("AGENTPROJ_MAX_AUTO_ROUNDS", "8"))
        self.evidence_command_timeout_sec = int(_env("AGENTPROJ_EVIDENCE_TIMEOUT", "600"))

        # Output caps (bytes) for persisted evidence text.
        self.max_evidence_output_bytes = int(_env("AGENTPROJ_MAX_EVIDENCE_BYTES", str(256 * 1024)))
        self.max_persisted_message_bytes = int(_env("AGENTPROJ_MAX_MESSAGE_BYTES", str(48 * 1024)))

    @staticmethod
    def _detect_codex_bin() -> str:
        """Prefer the native codex.exe used by the desktop app; fallback to `codex` wrapper."""
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin",
        ]
        for base in candidates:
            if base.is_dir():
                for child in sorted(base.iterdir(), reverse=True):
                    exe = child / "codex.exe"
                    if exe.is_file():
                        return str(exe)
        return "codex"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.goals_dir,
            self.imports_dir,
            self.wiki_dir,
            self.skills_dir,
            self.evidence_dir,
            self.demo_workspace,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def windows_to_wsl_path(self, windows_path: str) -> str | None:
        """Standard drive mapping C:\\x -> /mnt/c/x. Marked unverified until probed in WSL."""
        p = str(windows_path).strip()
        if len(p) >= 2 and p[1] == ":":
            drive = p[0].lower()
            rest = p[2:].replace("\\", "/")
            if not rest.startswith("/"):
                rest = "/" + rest
            return f"/mnt/{drive}{rest}"
        return None

    def to_stored_path(self, full: Path) -> str:
        """Store paths relative to the project root when possible, else absolute."""
        try:
            return str(Path(full).relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            return str(Path(full)).replace("\\", "/")

    def resolve_stored_path(self, stored: str) -> Path:
        p = Path(stored)
        return p if p.is_absolute() else self.project_root / stored


settings = Settings()
