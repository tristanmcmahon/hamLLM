from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import __version__
from .ollama import OllamaClient, OllamaError

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gpt-oss:20b"


def _client(args: argparse.Namespace) -> OllamaClient:
    return OllamaClient(args.host, args.timeout)


def _prompt(words: list[str]) -> str:
    if words:
        return " ".join(words)
    if sys.stdin.isatty():
        raise ValueError("provide a prompt or pipe one on standard input")
    prompt = sys.stdin.read()
    if not prompt.strip():
        raise ValueError("the prompt is empty")
    return prompt


def run_once(args: argparse.Namespace) -> int:
    prompt = _prompt(args.prompt)
    response = _client(args).generate(args.model, prompt, args.system)
    if args.json:
        print(json.dumps({"model": args.model, "response": response}))
    else:
        print(response)
    return 0


def list_models(args: argparse.Namespace) -> int:
    models = _client(args).models()
    if args.json:
        print(json.dumps({"models": models}))
    elif models:
        print("\n".join(models))
    else:
        print("No Ollama models are installed.")
    return 0


def doctor(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        version = client.version()
        models = client.models()
    except OllamaError as exc:
        payload = {
            "healthy": False,
            "host": args.host,
            "model": args.model,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(payload))
        else:
            print(f"FAIL  {exc}")
        return 1

    healthy = args.model in models
    payload = {
        "healthy": healthy,
        "host": args.host,
        "ollama_version": version,
        "model": args.model,
        "model_installed": healthy,
        "models": models,
    }
    if args.json:
        print(json.dumps(payload))
    else:
        print(f"PASS  Ollama {version} at {args.host}")
        state = "PASS" if healthy else "FAIL"
        detail = "installed" if healthy else "not installed"
        print(f"{state}  {args.model}: {detail}")
    return 0 if healthy else 1


def chat(args: argparse.Namespace) -> int:
    client = _client(args)
    messages: list[dict[str, str]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    model = args.model
    print(f"hamLLM {__version__} — {model} ({args.host})")
    print("/clear resets context; /model NAME switches model; /exit quits.")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in {"/exit", "/quit"}:
            return 0
        if line == "/clear":
            messages = [item for item in messages if item["role"] == "system"]
            print("Context cleared.")
            continue
        if line.startswith("/model "):
            candidate = line.removeprefix("/model ").strip()
            if not candidate:
                print("Model name is empty.", file=sys.stderr)
                continue
            model = candidate
            messages = [item for item in messages if item["role"] == "system"]
            print(f"Using {model}; context cleared.")
            continue
        messages.append({"role": "user", "content": line})
        try:
            response = client.chat(model, messages)
        except OllamaError:
            messages.pop()
            raise
        messages.append({"role": "assistant", "content": response})
        print(f"{model}> {response}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hamllm", description="Run and inspect local Ollama models"
    )
    parser.add_argument("--version", action="version", version=f"hamLLM {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--host", default=os.environ.get("HAMLLM_HOST", DEFAULT_HOST)
    )
    common.add_argument(
        "--model", default=os.environ.get("HAMLLM_MODEL", DEFAULT_MODEL)
    )
    common.add_argument(
        "--timeout",
        type=float,
        default=os.environ.get("HAMLLM_TIMEOUT", "300"),
    )

    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", parents=[common], help="run one prompt")
    run.add_argument("prompt", nargs="*")
    run.add_argument("--system")
    run.add_argument("--json", action="store_true")
    run.set_defaults(handler=run_once)

    interactive = commands.add_parser(
        "chat", parents=[common], help="start an interactive local chat"
    )
    interactive.add_argument("--system")
    interactive.set_defaults(handler=chat)

    models = commands.add_parser(
        "models", parents=[common], help="list installed Ollama models"
    )
    models.add_argument("--json", action="store_true")
    models.set_defaults(handler=list_models)

    check = commands.add_parser(
        "doctor", parents=[common], help="check Ollama and the selected model"
    )
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        return args.handler(args)
    except (OllamaError, ValueError) as exc:
        parser.error(str(exc))
    return 2
