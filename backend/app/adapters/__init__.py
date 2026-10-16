"""Adapter interfaces shared by real (Codex app-server) and fake/simulation roles."""
from .base import (  # noqa: F401
    AdapterUnavailable,
    AgentAdapterSession,
    FakeScriptContext,
    TurnCallbacks,
    TurnOutcome,
)
