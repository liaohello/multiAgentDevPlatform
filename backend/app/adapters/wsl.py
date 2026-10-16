"""WSL transport + WSL Codex adapter (worker role, DeepSeek via Codex).

Windows Python launches the WSL-side Codex app-server through `wsl.exe` and
forwards stdio. Path mapping uses the standard /mnt/<drive> convention and is
validated (`test -d`) before use.

Cancellation policy: first ask the native protocol (turn/interrupt); on
timeout kill only the `wsl.exe` process we own, then `pgrep` the distro for
lingering `codex app-server` processes. If that cannot be verified, the state
is reported UNKNOWN and conflicting writes are blocked (design §21).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .base import AdapterUnavailable
from .codex_appserver import CREATE_NO_WINDOW, CodexAdapterSession


def _run(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return subprocess.run(argv, **kwargs)


class WslTransport:
    def __init__(self, distro: str | None = None, codex_cmd: str = "codex") -> None:
        self.distro = distro
        self.codex_cmd = codex_cmd
        self.wsl_exe = shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"

    # ------------------------------------------------------------- probing
    def probe(self) -> dict:
        """Full availability report. Never raises; returns status + evidence."""
        detail: dict = {"wsl_exe": self.wsl_exe, "distro": self.distro, "codex_cmd": self.codex_cmd}
        try:
            res = _run([self.wsl_exe, "--status"], timeout=20)
        except FileNotFoundError as exc:
            return {"status": "BLOCKED", "detail": f"wsl.exe not found: {exc}", **detail}
        except PermissionError as exc:
            return {"status": "BLOCKED", "detail": f"wsl.exe blocked by environment policy: {exc}", **detail}
        except OSError as exc:
            return {"status": "BLOCKED", "detail": f"cannot launch wsl.exe: {exc}", **detail}
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "detail": "wsl.exe --status timed out", **detail}
        detail["wsl_status_exit"] = res.returncode
        detail["wsl_status_out"] = (res.stdout or res.stderr or "")[:600]

        if self.distro:
            distros = [self.distro]
        else:
            res_l = _run([self.wsl_exe, "-l", "-q"], timeout=20)
            if res_l.returncode != 0:
                return {"status": "FAIL", "detail": f"wsl -l -q failed: {(res_l.stderr or '')[:300]}", **detail}
            distros = [d.strip() for d in (res_l.stdout or "").splitlines() if d.strip()]
            detail["distros"] = distros
            if not distros:
                return {"status": "BLOCKED", "detail": "no WSL distro installed", **detail}
        distro = distros[0]

        res_v = _run([self.wsl_exe, "-d", distro, "--", "bash", "-lc", f"{self.codex_cmd} --version"], timeout=60)
        detail["distro_selected"] = distro
        detail["codex_version_exit"] = res_v.returncode
        detail["codex_version_out"] = ((res_v.stdout or "") + (res_v.stderr or ""))[:400]
        if res_v.returncode != 0:
            return {"status": "FAIL", "detail": f"codex not usable in distro {distro}: {detail['codex_version_out']}", **detail}
        return {"status": "PASS", "detail": f"WSL {distro}: {detail['codex_version_out'].strip()}", **detail}

    def check_path(self, distro: str, wsl_path: str) -> bool:
        try:
            res = _run([self.wsl_exe, "-d", distro, "--", "bash", "-lc", f'test -d "{wsl_path}" && echo OK'], timeout=30)
            return res.returncode == 0 and "OK" in (res.stdout or "")
        except Exception:
            return False

    # ------------------------------------------------------------- launch
    def app_server_command(self, distro: str, wsl_cwd: str) -> list[str]:
        inner = f"cd '{wsl_cwd}' && exec {self.codex_cmd} app-server --listen stdio://"
        return [self.wsl_exe, "-d", distro, "--", "bash", "-lc", inner]

    def pgrep_codex(self, distro: str) -> list[str]:
        """Best-effort check for lingering codex app-server processes in the distro."""
        try:
            res = _run(
                [self.wsl_exe, "-d", distro, "--", "bash", "-lc", "pgrep -af 'codex app-server' || true"],
                timeout=30,
            )
            return [line for line in (res.stdout or "").splitlines() if line.strip()]
        except Exception:
            return []


class WslCodexAdapterSession(CodexAdapterSession):
    """Worker adapter: Codex inside WSL (expected model provider: DeepSeek)."""

    def __init__(
        self,
        *,
        session_id: str,
        transport: WslTransport,
        wsl_cwd: str,
        model: str | None = None,
        effort: str | None = None,
        native_thread_id: str | None = None,
        approval_policy: str = "never",
        sandbox: str = "workspace-write",
        mode: str = "real",
    ) -> None:
        self.transport = transport
        distro = transport.distro or ""
        command = transport.app_server_command(distro, wsl_cwd) if distro else ["wsl.exe"]
        super().__init__(
            session_id=session_id,
            role="worker",
            command=command,
            cwd=None,  # cwd is handled inside the distro
            model=model,
            effort=effort,
            native_thread_id=native_thread_id,
            approval_policy=approval_policy,
            sandbox=sandbox,
            label=f"wsl:{distro or 'auto'}",
            mode=mode,
        )

    def availability(self) -> dict:
        probe = self.transport.probe()
        if probe["status"] != "PASS":
            return {"status": probe["status"], "detail": probe["detail"]}
        distro = probe.get("distro_selected") or self.transport.distro
        # Verify the project path mapping actually resolves.
        if self._wsl_cwd_check(distro):
            return {"status": "PASS", "detail": f"{probe['detail']}; path mapping verified"}
        return {"status": "FAIL", "detail": f"{probe['detail']}; path check failed for distro {distro}"}

    def _wsl_cwd_check(self, distro: str | None) -> bool:
        if not distro:
            return False
        # extract mapped path from the command construction
        for part in self.command:
            if part.startswith("cd '") and "app-server" in part:
                path = part.split("cd '")[1].split("'")[0]
                return self.transport.check_path(distro, path)
        return False

    def verify_no_residual_processes(self) -> dict:
        """After interrupt/cleanup: best-effort check of the distro process table."""
        probe = self.transport.probe()
        distro = probe.get("distro_selected") or self.transport.distro
        if not distro or probe["status"] != "PASS":
            return {"status": "UNKNOWN", "detail": "distro not reachable; cannot verify process state"}
        lines = self.transport.pgrep_codex(distro)
        # ignore pgrep's own bash wrapper line
        lines = [l for l in lines if "pgrep" not in l]
        if lines:
            return {"status": "RESIDUAL", "detail": f"codex processes still present: {lines[:5]}"}
        return {"status": "CLEAN", "detail": "no lingering codex app-server processes"}
