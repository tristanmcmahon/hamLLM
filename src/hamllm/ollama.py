from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 300.0


class OllamaError(RuntimeError):
    """A local Ollama request failed or returned an invalid response."""


@dataclass(frozen=True)
class OllamaClient:
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        host = self.host.strip().rstrip("/")
        parsed = urllib.parse.urlparse(host)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Ollama host must be an http(s) URL")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        object.__setattr__(self, "host", host)

    @classmethod
    def from_environment(cls) -> "OllamaClient":
        host = (
            os.environ.get("HAMLLM_HOST")
            or os.environ.get("OLLAMA_HOST")
            or DEFAULT_HOST
        )
        timeout = float(os.environ.get("HAMLLM_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        return cls(host=host, timeout=timeout)

    def _request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        method = "GET"
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        request = urllib.request.Request(
            f"{self.host}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise OllamaError(f"Ollama returned HTTP {exc.code}{suffix}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise OllamaError(f"Cannot reach Ollama at {self.host}: {reason}") from exc

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaError("Ollama returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise OllamaError("Ollama returned an unexpected response")
        if result.get("error"):
            raise OllamaError(f"Ollama error: {result['error']}")
        return result

    def version(self) -> str:
        version = self._request("/api/version").get("version")
        if not isinstance(version, str) or not version:
            raise OllamaError("Ollama did not report a version")
        return version

    def models(self) -> list[str]:
        entries = self._request("/api/tags").get("models")
        if not isinstance(entries, list):
            raise OllamaError("Ollama did not return a model list")
        names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
        return sorted(name for name in names if isinstance(name, str) and name)

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        *,
        think: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if think is not None:
            payload["think"] = think
        response = self._request("/api/generate", payload).get("response")
        if not isinstance(response, str):
            raise OllamaError("Ollama returned no generated response")
        return response

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        think: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        return self._request("/api/chat", payload)

    def chat_content(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        think: str | None = None,
    ) -> str:
        response = self.chat(model, messages, think=think).get("message")
        if not isinstance(response, dict) or not isinstance(
            response.get("content"), str
        ):
            raise OllamaError("Ollama returned no chat response")
        return response["content"]
