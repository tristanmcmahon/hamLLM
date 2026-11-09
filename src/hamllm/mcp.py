"""Minimal stdio MCP server: lets Zed, Claude Code and Codex offload work to local models.

Newline-delimited JSON-RPC 2.0 on stdin/stdout, standard library only. stdout is
reserved for protocol messages; diagnostics go to stderr. The tools are read-only:
no filesystem, no shell, no network beyond the configured Ollama host.

Offloading does not make content private: the prompt comes from the calling
client and the answer returns to it.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from . import __version__, config, profiles
from .ollama import OllamaCancelled, OllamaClient, OllamaError

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
CHARS_PER_TOKEN = 4  # rough; used only to reject prompts that clearly overflow the window
DEFAULT_MAX_TOKENS = 1024
MAX_TOKENS_CEILING = 4096
REQUEST_CANCELLED = -32800

INSTRUCTIONS = (
    "Local-model offload on the user's own hardware. Use ask_local for bulk, low-stakes "
    "work (summaries, commit messages, classification, log triage). Do not use it for "
    "hard reasoning, and verify its output before relying on it."
)

DEFAULT_SYSTEM = (
    "You are a local worker model called by another AI agent. Reply with only the requested "
    "output: no preamble, no alternatives or options unless asked, no closing remarks. If the "
    "task is ambiguous, pick the most reasonable interpretation and answer it."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "ask_local",
        "description": (
            "Run one prompt on a local model and return its text. Best for cheap, "
            "low-stakes tasks; output is unverified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The task, with all context inline."},
                "system": {"type": "string", "description": "Optional system prompt."},
                "model": {
                    "type": "string",
                    "description": "Model tag or alias (default, fast, tools, code). Default: default.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": f"Output cap (default {DEFAULT_MAX_TOKENS}, max {MAX_TOKENS_CEILING}).",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "local_models",
        "description": "List installed local models, their eval results, and what each alias resolves to.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class Server:
    def __init__(
        self,
        client: OllamaClient,
        *,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
        usage_log: Path | None = None,
        load_profiles: Callable[[], dict[str, dict[str, Any]]] = profiles.load,
    ) -> None:
        self.client = client
        self.num_ctx = num_ctx if num_ctx is not None else config.num_ctx()
        self.keep_alive = keep_alive if keep_alive is not None else config.mcp_keep_alive()
        self.usage_log = usage_log
        self.load_profiles = load_profiles

    def handle(
        self,
        message: Any,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any] | None:
        """Return the response for one message, or None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "invalid request")
        msg_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(msg_id, -32600, "invalid request")
        if "id" not in message:
            return None
        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            return _error(msg_id, -32602, "params must be an object")
        params = params or {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
            return _ok(msg_id, {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "hamllm", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        if method == "ping":
            return _ok(msg_id, {})
        if method == "tools/list":
            return _ok(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            return self._call_tool(msg_id, params, cancelled=cancelled)
        return _error(msg_id, -32601, f"method not found: {method}")

    def _call_tool(
        self,
        msg_id: Any,
        params: dict[str, Any],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in {tool["name"] for tool in TOOLS}:
            return _error(msg_id, -32602, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return _error(msg_id, -32602, "arguments must be an object")
        try:
            text = (
                self.ask_local(arguments, cancelled=cancelled)
                if name == "ask_local"
                else self.local_models()
            )
        except OllamaCancelled:
            return _error(msg_id, REQUEST_CANCELLED, "request cancelled")
        except (OllamaError, profiles.ResolutionError, ValueError) as exc:
            return _ok(msg_id, _text(str(exc), is_error=True))
        return _ok(msg_id, _text(text))

    def _record_usage(
        self,
        *,
        model: str,
        started: float,
        prompt_chars: int,
        response_chars: int,
        max_tokens: int,
        status: str,
    ) -> None:
        if self.usage_log is None:
            return
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "latency_seconds": round(time.monotonic() - started, 3),
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "max_tokens": max_tokens,
            "status": status,
        }
        try:
            self.usage_log.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.usage_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError as exc:
            print(f"hamllm mcp: could not append usage log: {exc}", file=sys.stderr)

    def ask_local(
        self,
        arguments: dict[str, Any],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        system = arguments.get("system")
        if system is not None and not isinstance(system, str):
            raise ValueError("system must be a string")
        system = system or DEFAULT_SYSTEM
        requested = arguments.get("model") or profiles.DEFAULT_ALIAS
        if not isinstance(requested, str):
            raise ValueError("model must be a string")
        max_tokens = arguments.get("max_tokens", DEFAULT_MAX_TOKENS)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        max_tokens = min(max_tokens, MAX_TOKENS_CEILING)

        installed = self.client.installed()
        saved = self.load_profiles()
        model = profiles.resolve(requested, list(installed), saved, digests=installed)
        explicit_tag = requested not in {profiles.DEFAULT_ALIAS, *profiles.ALIASES}
        if explicit_tag and model != config.default_model():
            profile = saved.get(model)
            if profile is None:
                raise profiles.ResolutionError(
                    f"{model} is installed but has never been profiled, so it is not offered over MCP; "
                    f"run `hamllm eval --save --model {model}` first"
                )
            if profiles.is_stale(profile, installed.get(model)):
                raise profiles.ResolutionError(
                    f"{model}'s profile is stale because its weights changed; re-run "
                    f"`hamllm eval --save --model {model}`"
                )
            if profiles.is_outdated(profile):
                raise profiles.ResolutionError(
                    f"{model}'s profile was produced by an older eval suite; re-run "
                    f"`hamllm eval --save --model {model}`"
                )
            if profile.get("ready") is not True:
                raise profiles.ResolutionError(
                    f"{model} did not pass its saved capability eval and is not offered by explicit tag over MCP"
                )

        estimated = (len(prompt) + len(system) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
        if estimated + max_tokens > self.num_ctx:
            raise ValueError(
                f"prompt is about {estimated} tokens plus up to {max_tokens} output tokens, "
                f"but the local window is {self.num_ctx}; send less, request less output, or summarise first."
            )

        started = time.monotonic()
        status = "error"
        response = ""
        try:
            response = self.client.generate(
                model,
                prompt,
                system,
                options={"num_ctx": self.num_ctx, "num_predict": max_tokens},
                keep_alive=self.keep_alive,
                cancelled=cancelled,
            )
            if not response.strip():
                raise ValueError(
                    f"{model} returned no text; its {max_tokens}-token budget may have been spent "
                    "on reasoning. Retry with a larger max_tokens or a different model."
                )
            status = "ok"
            return f"{response.strip()}\n\n[local model: {model}]"
        except OllamaCancelled:
            status = "cancelled"
            raise
        finally:
            self._record_usage(
                model=model,
                started=started,
                prompt_chars=len(prompt) + len(system),
                response_chars=len(response),
                max_tokens=max_tokens,
                status=status,
            )

    def local_models(self) -> str:
        """A compact summary: this lands in a cloud model's context, so every token counts."""
        digests = self.client.installed()
        installed = sorted(digests)
        saved = self.load_profiles()
        lines = []
        for alias in (profiles.DEFAULT_ALIAS, *profiles.ALIASES):
            try:
                lines.append(f"{alias} -> {profiles.resolve(alias, installed, saved, digests=digests)}")
            except profiles.ResolutionError:
                lines.append(f"{alias} -> unavailable (no profiled model qualifies)")
        profiled = [m for m in installed if m in saved]
        profiled.sort(
            key=lambda m: (
                profiles.is_stale(saved[m], digests[m]) or profiles.is_outdated(saved[m]),
                not saved[m].get("ready"),
                saved[m].get("median_seconds") or 1e9,
                m,
            )
        )
        for model in profiled:
            profile = saved[model]
            state = (
                "STALE"
                if profiles.is_stale(profile, digests[model])
                else "OUTDATED"
                if profiles.is_outdated(profile)
                else "ready"
                if profile.get("ready")
                else "not ready"
            )
            rates = " ".join(f"{c} {round(r * 100)}" for c, r in (profile.get("categories") or {}).items())
            median = profile.get("median_seconds")
            lines.append(f"{model}: {state}; {rates}; median {median}s" if median else f"{model}: {state}; {rates}")
        unprofiled = [m for m in installed if m not in saved]
        if unprofiled:
            lines.append("not profiled (not offered): " + ", ".join(unprofiled))
        return "\n".join(lines)


def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _text(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _request_key(request_id: Any) -> str:
    return json.dumps(request_id, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def serve(server: Server, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Serve JSON-RPC while serialising GPU work and remaining responsive to cancellation."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    work: queue.Queue[tuple[dict[str, Any], threading.Event, str] | None] = queue.Queue()
    pending: dict[str, threading.Event] = {}
    pending_lock = threading.Lock()
    output_lock = threading.Lock()

    def write(response: dict[str, Any] | None) -> None:
        if response is None:
            return
        with output_lock:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()

    def worker() -> None:
        while True:
            item = work.get()
            if item is None:
                work.task_done()
                return
            message, cancelled_event, key = item
            try:
                if cancelled_event.is_set():
                    response = _error(message.get("id"), REQUEST_CANCELLED, "request cancelled")
                else:
                    response = server.handle(message, cancelled=cancelled_event.is_set)
            except Exception as exc:
                print(f"hamllm mcp: internal error: {exc!r}", file=sys.stderr)
                response = _error(message.get("id"), -32603, "internal error")
            finally:
                with pending_lock:
                    pending.pop(key, None)
            write(response)
            work.task_done()

    worker_thread = threading.Thread(target=worker, name="hamllm-mcp-worker", daemon=True)
    worker_thread.start()

    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            write(_error(None, -32700, "parse error"))
            continue

        if isinstance(message, dict) and message.get("method") == "notifications/cancelled":
            params = message.get("params")
            request_id = params.get("requestId") if isinstance(params, dict) else None
            key = _request_key(request_id)
            with pending_lock:
                event = pending.get(key)
            if event is not None:
                event.set()
            continue

        if (
            isinstance(message, dict)
            and message.get("jsonrpc") == "2.0"
            and message.get("method") == "tools/call"
            and "id" in message
        ):
            key = _request_key(message.get("id"))
            event = threading.Event()
            with pending_lock:
                if key in pending:
                    write(_error(message.get("id"), -32600, "duplicate request id"))
                    continue
                pending[key] = event
            work.put((message, event, key))
            continue

        try:
            response = server.handle(message)
        except Exception as exc:
            print(f"hamllm mcp: internal error: {exc!r}", file=sys.stderr)
            msg_id = message.get("id") if isinstance(message, dict) else None
            response = _error(msg_id, -32603, "internal error")
        write(response)

    work.join()
    work.put(None)
    work.join()
    worker_thread.join()
    return 0
