"""Environment-driven settings shared by every front-end (CLI, MCP server)."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "gpt-oss:20b"
# Ollama's own default window is 4096 tokens and it silently drops the oldest
# context beyond that, so hamLLM sets one deliberately.
DEFAULT_NUM_CTX = 16384
DEFAULT_KEEP_ALIVE = "30m"


def default_model() -> str:
    return os.environ.get("HAMLLM_MODEL") or DEFAULT_MODEL


def num_ctx() -> int:
    return int(os.environ.get("HAMLLM_NUM_CTX") or DEFAULT_NUM_CTX)


def keep_alive() -> str:
    return os.environ.get("HAMLLM_KEEP_ALIVE") or DEFAULT_KEEP_ALIVE


def state_dir() -> Path:
    explicit = os.environ.get("HAMLLM_STATE_DIR")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "hamllm"
