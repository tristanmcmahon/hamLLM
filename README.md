# hamLLM

`hamLLM` is the shared local-AI substrate for the Ham projects: a small local-only Ollama CLI plus reusable transport and bounded agent-runtime primitives.

It does **not** read or send email, run a mail poller, or require Gmail credentials. The pre-0.1 mail bridge is retired.

If an old `hamllm-bridge` user service is still loaded on a machine, stop it with:

```bash
systemctl --user mask --now hamllm-bridge-timer.timer hamllm-bridge.service
```

## CLI

```bash
hamllm doctor
hamllm models
hamllm run "Explain this shell error"
hamllm chat
```

The default model is `gpt-oss:20b`. Choose any installed Ollama tag with `--model` or `HAMLLM_MODEL`:

```bash
hamllm run --model qwen3.6:27b "Review this plan"
HAMLLM_MODEL=gpt-oss:20b hamllm chat
```

Configuration:

- `HAMLLM_HOST` — Ollama base URL (default `http://127.0.0.1:11434`; `OLLAMA_HOST` is also accepted)
- `HAMLLM_MODEL` — default installed model tag
- `HAMLLM_TIMEOUT` — request timeout in seconds
- `--reasoning low|medium|high` — optional Ollama reasoning level for `run` and `chat`

`run` accepts a prompt on standard input and supports `--json`. `models` and `doctor` support `--json`. Interactive chat understands `/clear`, `/model NAME`, and `/exit`.

## Shared runtime API

- `hamllm.ollama.OllamaClient` — dependency-free local Ollama transport, model discovery, version checks, generate/chat calls.
- `hamllm.agent.AgentRuntime` — bounded tool loop with duplicate-call suppression, default-deny approvals, state-change cache invalidation, budget-aware synthesis, and injectable deterministic response policy.
- `hamllm.agent.ToolRegistry` — adapter boundary that lets applications retain their own tools and security policy.

`hamGwen` consumes the shared agent core while keeping Gwen-specific tools, approval previews, prompts, destructive-response policy, and behavioural evals. `HamSidian` remains separate because its semantic reviewer has its own read-only-source and deterministic-verification boundary.

See [`docs/CONSOLIDATION.md`](docs/CONSOLIDATION.md) for the repository ownership model.

## Install

```bash
python3 -m pip install .
```

Or build with Nix:

```bash
nix-build
```

## Development

```bash
python3 -m compileall -q src tests
python3 -m pip install -e . pytest
python3 -m pytest -q
hamllm --help
```
