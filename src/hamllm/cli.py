from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Sequence

from . import bridge
from .ollama import DEFAULT_HOST, OllamaClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hamllm",
        description="Local Ollama runtime and bounded integration layer.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("bridge", help="Run the legacy Gmail task bridge.")

    chat = subparsers.add_parser("chat", help="Chat directly with a local Ollama model.")
    chat.add_argument(
        "--model",
        default=os.environ.get("HAM_MODEL", "gwen"),
        help="Ollama model name (default: HAM_MODEL or gwen).",
    )
    chat.add_argument(
        "--host",
        default=os.environ.get("OLLAMA_HOST") or os.environ.get("HAM_OLLAMA_HOST") or DEFAULT_HOST,
        help="Ollama host URL.",
    )
    chat.add_argument("--timeout", type=float, default=300.0, help="Request timeout in seconds.")
    chat.add_argument(
        "--reasoning",
        choices=("low", "medium", "high"),
        default=None,
        help="Optional Ollama reasoning level.",
    )
    chat.add_argument("prompt", nargs="*", help="One-shot prompt. Omit for interactive chat.")
    return parser


def _message_content(response: dict[str, Any]) -> str:
    message = response.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama response did not contain a message")
    content = message.get("content", "")
    return content if isinstance(content, str) else str(content)


def _run_chat(args: argparse.Namespace) -> int:
    client = OllamaClient(host=args.host, timeout=args.timeout)
    messages: list[dict[str, Any]] = []

    if args.prompt:
        prompt = " ".join(args.prompt)
        messages.append({"role": "user", "content": prompt})
        response = client.chat(args.model, messages, think=args.reasoning)
        answer = _message_content(response)
        if answer:
            print(answer)
        return 0

    while True:
        try:
            prompt = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not prompt:
            continue
        if prompt in {"/bye", "/exit", "/quit"}:
            return 0

        messages.append({"role": "user", "content": prompt})
        response = client.chat(args.model, messages, think=args.reasoning)
        assistant_message = {
            "role": "assistant",
            "content": _message_content(response),
        }
        messages.append(assistant_message)
        if assistant_message["content"]:
            print(assistant_message["content"])


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Preserve the original service contract: bare `hamllm` still runs the mail bridge.
    if not args_list:
        return bridge.main([])

    parser = build_parser()
    args = parser.parse_args(args_list)

    if args.command == "bridge":
        return bridge.main([])
    if args.command == "chat":
        return _run_chat(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
