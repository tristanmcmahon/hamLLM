from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 300.0


def normalize_host(value: str | None) -> str:
    host = (value or DEFAULT_HOST).strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


def _request_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach Ollama at {url}: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Ollama returned a non-object response")
    return data


@dataclass(frozen=True)
class OllamaClient:
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", normalize_host(self.host))

    @classmethod
    def from_environment(cls, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> "OllamaClient":
        host = os.environ.get("OLLAMA_HOST") or os.environ.get("HAM_OLLAMA_HOST") or DEFAULT_HOST
        return cls(host=host, timeout=timeout)

    def generate(self, model: str, prompt: str, *, think: str | None = None) -> str:
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if think is not None:
            payload["think"] = think
        data = _request_json(f"{self.host}/api/generate", payload, timeout=self.timeout)
        response = data.get("response")
        return response if isinstance(response, str) else ""

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        think: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        return _request_json(f"{self.host}/api/chat", payload, timeout=self.timeout)


def call_ollama(url: str, model: str, prompt: str) -> str:
    """Compatibility wrapper for the original mail bridge."""
    data = _request_json(
        url,
        {"model": model, "prompt": prompt, "stream": False},
        timeout=90.0,
    )
    response = data.get("response")
    return response if isinstance(response, str) else json.dumps(data)
