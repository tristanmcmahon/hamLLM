"""Minimal stdio MCP server: lets Zed, Claude Code and Codex offload work to local models.

Newline-delimited JSON-RPC 2.0 on stdin/stdout, standard library only. stdout is
reserved for protocol messages; diagnostics go to stderr. The tools are read-only:
no filesystem, no shell, no network beyond the configured Ollama host.

Offloading does not make content private: the prompt comes from the calling
client and the answer returns to it.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from . import __version__, config, profiles
from .ollama import OllamaClient, OllamaError

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_MAX_TOKENS = 1024
MAX_TOKENS_CEILING = 4096

INSTRUCTIONS = (
    "Local-model offload on the user's own hardware. Use ask_local for bulk, low-stakes "
    "work (summaries, commit messages, classification, log triage). Do not use it for "
    "hard reasoning, and verify its output before relying on it."
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
        load_profiles: Callable[[], dict[str, dict[str, Any]]] = profiles.load,
    ) -> None:
        self.client = client
        self.num_ctx = num_ctx if num_ctx is not None else config.num_ctx()
        self.keep_alive = keep_alive if keep_alive is not None else config.keep_alive()
        self.load_profiles = load_profiles

    # -- protocol -----------------------------------------------------------

    def handle(self, message: Any) -> dict[str, Any] | None:
        """Return the response for one message, or None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "invalid request")
        msg_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(msg_id, -32600, "invalid request")
        if "id" not in message:
            return None  # notification (e.g. notifications/initialized)
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
            return self._call_tool(msg_id, params)
        return _error(msg_id, -32601, f"method not found: {method}")

    def _call_tool(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in {tool["name"] for tool in TOOLS}:
            return _error(msg_id, -32602, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return _error(msg_id, -32602, "arguments must be an object")
        try:
            text = self.ask_local(arguments) if name == "ask_local" else self.local_models()
        except (OllamaError, profiles.ResolutionError, ValueError) as exc:
            return _ok(msg_id, _text(str(exc), is_error=True))
        return _ok(msg_id, _text(text))

    # -- tools --------------------------------------------------------------

    def ask_local(self, arguments: dict[str, Any]) -> str:
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        system = arguments.get("system")
        if system is not None and not isinstance(system, str):
            raise ValueError("system must be a string")
        requested = arguments.get("model") or profiles.DEFAULT_ALIAS
        if not isinstance(requested, str):
            raise ValueError("model must be a string")
        max_tokens = arguments.get("max_tokens", DEFAULT_MAX_TOKENS)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        max_tokens = min(max_tokens, MAX_TOKENS_CEILING)

        installed = self.client.installed()
        model = profiles.resolve(requested, list(installed), self.load_profiles(), digests=installed)
        response = self.client.generate(
            model,
            prompt,
            system,
            options={"num_ctx": self.num_ctx, "num_predict": max_tokens},
            keep_alive=self.keep_alive,
        )
        if not response.strip():
            raise ValueError(
                f"{model} returned no text; its {max_tokens}-token budget may have been spent "
                "on reasoning. Retry with a larger max_tokens or a different model."
            )
        return f"{response.strip()}\n\n[local model: {model}]"

    def local_models(self) -> str:
        digests = self.client.installed()
        installed = sorted(digests)
        saved = self.load_profiles()
        aliases: dict[str, Any] = {}
        for alias in (profiles.DEFAULT_ALIAS, *profiles.ALIASES):
            try:
                aliases[alias] = profiles.resolve(alias, installed, saved, digests=digests)
            except profiles.ResolutionError as exc:
                aliases[alias] = {"unavailable": str(exc)}
        return json.dumps(
            {
                "installed": installed,
                "aliases": aliases,
                "profiles": {
                    m: {**saved[m], "stale": profiles.is_stale(saved[m], digests[m])}
                    for m in installed
                    if m in saved
                },
            },
            indent=2,
        )


def _ok(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _text(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def serve(server: Server, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = _error(None, -32700, "parse error")
        else:
            try:
                response = server.handle(message)
            except Exception as exc:  # never let one bad request kill the server
                print(f"hamllm mcp: internal error: {exc!r}", file=sys.stderr)
                msg_id = message.get("id") if isinstance(message, dict) else None
                response = _error(msg_id, -32603, "internal error")
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0
