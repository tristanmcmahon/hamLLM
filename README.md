# hamLLM

`hamLLM` is the shared local-AI substrate for Tristan's Ham projects: local Ollama transport, common runtime primitives, and bounded integrations that should not be reimplemented independently in every application.

The repository began as a minimal Gmail → Ollama bridge. That bridge remains available, but it is now one integration rather than the definition of the project.

## Current surface

- `hamllm` with no arguments — preserves the original mail-bridge behaviour.
- `hamllm bridge` — runs the mail bridge explicitly.
- `hamllm chat --model MODEL [PROMPT...]` — direct local Ollama chat, one-shot or interactive.
- `hamllm.ollama.OllamaClient` — dependency-free `/api/generate` and `/api/chat` transport for local consumers.
- `hamllm.ollama.call_ollama` — compatibility wrapper for the original bridge.
- `hamllm.agent.AgentRuntime` — reusable bounded tool loop with default-deny approvals, duplicate-call suppression, budget-aware synthesis, and injectable deterministic response policy.
- `hamllm.agent.ToolRegistry` — adapter boundary that lets applications retain their own tool implementations and security policy.

The Python package lives under `src/hamllm/` and requires only the standard library at runtime.

## Consolidation role

`hamLLM` owns reusable local-model plumbing. It does **not** own application policy.

- **hamGwen** currently remains authoritative for Gwen's tool implementations, approval previews, prompts, destructive-response policy, and behavioural evals. Its generic agent-loop mechanics are migrating into `hamLLM` in parity-tested slices; the Gwen name can then survive as a persona/compatibility entry point rather than a separate runtime.
- **HamSidian** remains a separate vault application with its own strict source/derived-vault security boundary. It may consume a stable `hamLLM` reviewer interface later, but consolidation must not weaken its current local-only contract.
- **hamSteam**, **hamCintosh**, and **hamKeyDist** remain separate domain tools.
- **nixos-helix** owns Helix machine configuration and service lifecycle, not application behaviour.
- **hamBridge** is retired; bridge functionality belongs here.

See [`docs/CONSOLIDATION.md`](docs/CONSOLIDATION.md) for the ownership map and migration rules.

## Usage

The old service contract is intentionally preserved:

```bash
hamllm
```

Equivalent explicit form:

```bash
hamllm bridge
```

Direct local chat:

```bash
hamllm chat --model gwen "Summarise this repository"
hamllm chat --model gwen
```

Ollama defaults to `http://127.0.0.1:11434`. Override it with `OLLAMA_HOST`, `HAM_OLLAMA_HOST`, or `--host` for the chat command. The legacy bridge continues to accept its existing `HAM_OLLAMA_URL` endpoint.

## Development

```bash
python -m pytest -q
python -m compileall -q src tests
```

The consolidation rule is simple: common local-AI mechanics move inward to `hamLLM`; domain knowledge and safety policy stay with the Ham that actually owns the job.
