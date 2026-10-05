from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import __version__, config, profiles
from .config import DEFAULT_MODEL  # noqa: F401  (re-exported for callers)
from .ollama import DEFAULT_HOST, OllamaClient, OllamaError

MCP_TIMEOUT_SECONDS = 120.0


def _client(args: argparse.Namespace) -> OllamaClient:
    return OllamaClient(args.host, args.timeout)


def _options(args: argparse.Namespace) -> dict[str, int]:
    return {"num_ctx": args.num_ctx}


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
    client = _client(args)
    model = profiles.resolve(args.model, client.models(), profiles.load())
    response = client.generate(
        model,
        prompt,
        args.system,
        think=args.reasoning,
        options=_options(args),
        keep_alive=config.keep_alive(),
    )
    if args.json:
        print(json.dumps({"model": model, "response": response}))
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


def resolve_model(args: argparse.Namespace) -> int:
    model = profiles.resolve(args.name, _client(args).models(), profiles.load(), threshold=args.threshold)
    print(model)
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


def evaluate(args: argparse.Namespace) -> int:
    from . import evals

    client = _client(args)
    installed = client.models()
    if args.model not in installed:
        raise ValueError(f"model {args.model!r} is not installed; run `hamllm models`")
    cases = [c for c in evals.CASES if not args.category or c.category in args.category]
    if not cases:
        raise ValueError(f"no cases match; categories: {', '.join(evals.CATEGORIES)}")
    if args.save and args.category:
        raise ValueError("--save needs the full suite; drop --category")
    out = sys.stderr if args.json else sys.stdout
    options = _options(args)

    def show(summary: evals.CaseSummary) -> None:
        passed = sum(r.passed for r in summary.runs)
        state = "PASS" if summary.pass_rate >= args.threshold else "FAIL"
        print(
            f"{state}  {summary.case.category}/{summary.case.name}  "
            f"{passed}/{len(summary.runs)}  {summary.median_seconds:.1f}s",
            file=out,
        )
        for run in summary.runs:
            if not run.passed:
                print(f"      {run.reason}", file=out)

    summaries = evals.run_suite(
        client, args.model, cases=cases, repeats=args.repeats,
        reasoning=args.reasoning, options=options, on_result=show,
    )
    result = evals.report(args.model, summaries, args.threshold, options=options)
    if args.save:
        print(f"profile saved to {profiles.save_report(result)}", file=out)
    if args.json:
        print(json.dumps(result))
    else:
        for category, rate in result["categories"].items():
            print(f"{category:12} {rate:.0%}")
        print("READY" if result["ready"] else "NOT READY", f"({args.model}, threshold {args.threshold:.0%})")
    return 0 if result["ready"] else 1


def mcp_server(args: argparse.Namespace) -> int:
    from .mcp import Server, serve

    return serve(Server(_client(args), num_ctx=args.num_ctx))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hamllm",
        description="Capability profiles, evals and an MCP front door for local Ollama models",
    )
    parser.add_argument("--version", action="version", version=f"hamLLM {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--host",
        default=(
            os.environ.get("HAMLLM_HOST")
            or os.environ.get("OLLAMA_HOST")
            or DEFAULT_HOST
        ),
    )
    common.add_argument("--model", default=config.default_model())
    common.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("HAMLLM_TIMEOUT", "300")),
    )
    common.add_argument(
        "--num-ctx",
        type=int,
        default=config.num_ctx(),
        help="context window in tokens (env HAMLLM_NUM_CTX)",
    )
    common.add_argument(
        "--reasoning",
        choices=("low", "medium", "high"),
        default=None,
        help="optional Ollama reasoning level",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run", parents=[common], help="run one prompt (--model accepts an alias)"
    )
    run.add_argument("prompt", nargs="*")
    run.add_argument("--system")
    run.add_argument("--json", action="store_true")
    run.set_defaults(handler=run_once)

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

    probe = commands.add_parser(
        "eval", parents=[common], help="test whether the model can field real requests"
    )
    probe.add_argument("--repeats", type=int, default=1, help="runs per case")
    probe.add_argument("--threshold", type=float, default=profiles.DEFAULT_THRESHOLD, help="min pass rate per category")
    probe.add_argument("--category", action="append", help="limit to a category (repeatable)")
    probe.add_argument("--save", action="store_true", help="store the result as this model's capability profile")
    probe.add_argument("--json", action="store_true")
    probe.set_defaults(handler=evaluate)

    resolve = commands.add_parser(
        "resolve", parents=[common], help="print the installed model an alias resolves to"
    )
    resolve.add_argument("name", help="tag or alias: " + ", ".join([profiles.DEFAULT_ALIAS, *profiles.ALIASES]))
    resolve.add_argument("--threshold", type=float, default=profiles.DEFAULT_THRESHOLD)
    resolve.set_defaults(handler=resolve_model)

    serve = commands.add_parser(
        "mcp", parents=[common], help="serve local models to MCP clients over stdio"
    )
    serve.set_defaults(
        handler=mcp_server,
        timeout=float(os.environ.get("HAMLLM_MCP_TIMEOUT", MCP_TIMEOUT_SECONDS)),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OllamaError, ValueError) as exc:
        parser.error(str(exc))
    return 2
