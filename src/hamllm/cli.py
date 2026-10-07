from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import __version__, config, profiles
from .config import DEFAULT_MODEL  # noqa: F401  (re-exported for callers)
from .ollama import DEFAULT_HOST, DEFAULT_TIMEOUT_SECONDS, OllamaClient, OllamaError

MCP_TIMEOUT_SECONDS = 120.0


def _client(args: argparse.Namespace, *, default_timeout: float | None = None) -> OllamaClient:
    timeout = args.timeout
    if timeout is None:
        timeout = default_timeout or float(os.environ.get("HAMLLM_TIMEOUT") or DEFAULT_TIMEOUT_SECONDS)
    return OllamaClient(args.host, timeout)


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
    installed = client.installed()
    model = profiles.resolve(args.model, list(installed), profiles.load(), digests=installed)
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


def _profile_summary(profile: dict | None, digest: str) -> str:
    if profile is None:
        return "not profiled"
    state = "ready" if profile.get("ready") else "NOT ready"
    if profiles.is_stale(profile, digest):
        return f"STALE (weights changed since {profile.get('evaluated_at')}); re-run eval"
    rates = ", ".join(f"{c} {r:.0%}" for c, r in (profile.get("categories") or {}).items())
    return f"{state} ({rates}) evaluated {profile.get('evaluated_at')}"


def list_models(args: argparse.Namespace) -> int:
    installed = _client(args).installed()
    saved = profiles.load()
    if args.json:
        print(json.dumps({"models": sorted(installed), "profiles": {m: saved[m] for m in installed if m in saved}}))
    elif installed:
        for model in sorted(installed):
            print(f"{model}  {_profile_summary(saved.get(model), installed[model])}")
    else:
        print("No Ollama models are installed.")
    return 0


def resolve_model(args: argparse.Namespace) -> int:
    installed = _client(args).installed()
    print(profiles.resolve(args.name, list(installed), profiles.load(), threshold=args.threshold, digests=installed))
    return 0


def doctor(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        version = client.version()
        installed = client.installed()
        models = sorted(installed)
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

    try:
        model = profiles.resolve(args.model, models, profiles.load(), digests=installed)
    except profiles.ResolutionError as exc:
        model, problem = args.model, str(exc)
    else:
        problem = None
    healthy = problem is None
    payload = {
        "healthy": healthy,
        "host": args.host,
        "ollama_version": version,
        "model": args.model,
        "resolved_model": model if healthy else None,
        "model_installed": healthy,
        "models": models,
    }
    if args.json:
        print(json.dumps(payload))
    else:
        print(f"PASS  Ollama {version} at {args.host}")
        label = args.model if model == args.model else f"{args.model} -> {model}"
        print(f"{'PASS' if healthy else 'FAIL'}  {label}: {'installed' if healthy else problem}")
        if healthy:
            print(f"INFO  profile: {_profile_summary(profiles.load().get(model), installed[model])}")
    return 0 if healthy else 1

def _eval_one(client: OllamaClient, model: str, digest: str, cases: list, args: argparse.Namespace, out) -> dict:
    from . import evals

    options = _options(args)

    def show(summary: evals.CaseSummary) -> None:
        passed = sum(r.passed for r in summary.runs)
        state = "PASS" if summary.pass_rate >= args.threshold else "FAIL"
        print(
            f"{state}  {summary.case.category}/{summary.case.name}  "
            f"{passed}/{len(summary.runs)}  {summary.median_seconds:.1f}s"
            + (f"  ({summary.retries} tool-call retries)" if summary.retries else ""),
            file=out,
        )
        reasons: dict[str, int] = {}
        for run in summary.runs:
            if not run.passed:
                reasons[run.reason or "failed"] = reasons.get(run.reason or "failed", 0) + 1
        for reason, count in reasons.items():
            print(f"      {reason}" + (f"  (x{count})" if count > 1 else ""), file=out)

    summaries = evals.run_suite(
        client, model, cases=cases, repeats=args.repeats,
        reasoning=args.reasoning, options=options, on_result=show,
    )
    result = evals.report(model, summaries, args.threshold, options=options)
    if args.save:
        print(f"profile saved to {profiles.save_report(result, digest=digest)}", file=out)
    return result


def _chat_capable(client: OllamaClient, model: str) -> bool:
    """False only when Ollama positively says the model cannot generate (e.g. embedding-only)."""
    try:
        capabilities = client.capabilities(model)
    except OllamaError:
        return True
    return not capabilities or "completion" in capabilities


def evaluate(args: argparse.Namespace) -> int:
    from . import evals

    client = _client(args)
    installed = client.installed()
    cases = [c for c in evals.CASES if not args.category or c.category in args.category]
    if not cases:
        raise ValueError(f"no cases match; categories: {', '.join(evals.CATEGORIES)}")
    if args.save and args.category:
        raise ValueError("--save needs the full suite; drop --category")
    out = sys.stderr if args.json else sys.stdout

    if not args.all:
        if args.model not in installed:
            raise ValueError(f"model {args.model!r} is not installed; run `hamllm models`")
        result = _eval_one(client, args.model, installed[args.model], cases, args, out)
        if args.json:
            print(json.dumps(result))
        else:
            for category, rate in result["categories"].items():
                print(f"{category:12} {rate:.0%}")
            print("READY" if result["ready"] else "NOT READY", f"({args.model}, threshold {args.threshold:.0%})")
        return 0 if result["ready"] else 1

    results = []
    for model in sorted(installed):
        if not _chat_capable(client, model):
            print(f"SKIP  {model}: not a text-generation model", file=out)
            continue
        print(f"== {model} ==", file=out)
        results.append(_eval_one(client, model, installed[model], cases, args, out))
    if args.json:
        print(json.dumps({"reports": results}))
    else:
        categories = list(evals.CATEGORIES)
        print(f"\n{'model':28} {'verdict':10} " + " ".join(f"{c[:6]:>6}" for c in categories) + "   median")
        for r in sorted(results, key=lambda r: (not r["ready"], r["median_seconds"] or 0)):
            rates = " ".join(f"{r['categories'].get(c, 0):>6.0%}" for c in categories)
            print(f"{r['model']:28} {'READY' if r['ready'] else 'not ready':10} {rates}   {r['median_seconds']}s")
    return 0 if any(r["ready"] for r in results) else 1


def mcp_server(args: argparse.Namespace) -> int:
    from .mcp import Server, serve

    mcp_timeout = float(os.environ.get("HAMLLM_MCP_TIMEOUT") or MCP_TIMEOUT_SECONDS)
    return serve(Server(_client(args, default_timeout=mcp_timeout), num_ctx=args.num_ctx))


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
        default=None,
        help="request timeout in seconds (env HAMLLM_TIMEOUT, default 300; 120 for mcp via HAMLLM_MCP_TIMEOUT)",
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
    probe.add_argument("--all", action="store_true", help="evaluate every installed text-generation model and compare")
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
    serve.set_defaults(handler=mcp_server)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OllamaError, ValueError) as exc:
        parser.error(str(exc))
    return 2
