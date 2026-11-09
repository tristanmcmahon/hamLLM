"""Environment-driven settings shared by every front-end (CLI, MCP server)."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "gpt-oss:20b"
# Ollama's own default window is 4096 tokens and it silently drops the oldest
# context beyond that, so hamLLM sets one deliberately.
DEFAULT_NUM_CTX = 16384
DEFAULT_KEEP_ALIVE = "30m"
DEFAULT_MCP_KEEP_ALIVE = "5m"


def default_model() -> str:
    return os.environ.get("HAMLLM_MODEL") or DEFAULT_MODEL


def num_ctx() -> int:
    raw = os.environ.get("HAMLLM_NUM_CTX")
    try:
        value = int(raw) if raw is not None and raw != "" else DEFAULT_NUM_CTX
    except ValueError as exc:
        raise ValueError("HAMLLM_NUM_CTX must be a positive integer") from exc
    if value <= 0:
        raise ValueError("HAMLLM_NUM_CTX must be a positive integer")
    return value


def keep_alive() -> str:
    return os.environ.get("HAMLLM_KEEP_ALIVE") or DEFAULT_KEEP_ALIVE


def mcp_keep_alive() -> str:
    return (
        os.environ.get("HAMLLM_MCP_KEEP_ALIVE")
        or os.environ.get("HAMLLM_KEEP_ALIVE")
        or DEFAULT_MCP_KEEP_ALIVE
    )


def usage_log_path() -> Path | None:
    value = os.environ.get("HAMLLM_USAGE_LOG")
    return Path(value).expanduser() if value else None


def state_dir() -> Path:
    explicit = os.environ.get("HAMLLM_STATE_DIR")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "hamllm"
