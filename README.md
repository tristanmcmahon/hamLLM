# hamLLM

`hamLLM` is the capability and policy layer in front of local Ollama models for the Ham projects. Ollama runs the models; hamLLM answers the questions Ollama doesn't:

- **What can each local model actually do?** `hamllm eval` drives a real model through a bounded agent loop against an in-memory sandbox and scores the transcript deterministically.
- **Which model should a client use?** Aliases (`fast`, `tools`, `code`) resolve to the best installed model that *passed* the relevant eval categories.
- **How do Zed, Claude Code and Codex offload work to local models?** `hamllm mcp` is a read-only stdio MCP server in front of all of it.
- **How do apps run a local model safely?** `hamllm.agent` is the shared bounded tool runtime (default-deny approvals, duplicate suppression, response policy).

It does **not** read or send email, run a mail poller, or need Gmail credentials; the pre-0.1 mail bridge is retired. It is also not a chat client: use `ollama run` for that.

If an old `hamllm-bridge` user service is still loaded on a machine, stop it with:

```bash
systemctl --user mask --now hamllm-bridge-timer.timer hamllm-bridge.service
```

## Quick start

```bash
hamllm doctor                              # Ollama reachable, model installed?
hamllm eval --save --repeats 5             # profile the default model (full suite)
hamllm eval --save --repeats 5 --model qwen3.6:27b
hamllm resolve code                        # which installed model is trusted for coding work?
hamllm run --model fast "Summarise: ..."   # one-shot generation; --model accepts aliases
hamllm mcp                                 # serve local models to MCP clients over stdio
```

## Evals and profiles

`hamllm eval` runs 18 cases in six categories: `basic`, `instruction`, `tools`, `safety`, `coding`, `context`. It exits 1 unless every category clears `--threshold` (default 80%). `--save` stores the result as that model's profile in `$HAMLLM_STATE_DIR` (default `~/.local/state/hamllm/profiles.json`).

Aliases name the categories a model must have passed:

| Alias | Requires | Use for |
| --- | --- | --- |
| `default` | nothing (`HAMLLM_MODEL`) | whatever you configured |
| `fast` | basic, instruction | summaries, classification, formatting |
| `tools` | tools, safety | tool-calling agents |
| `code` | tools, safety, coding | edit-and-verify work |

An alias never resolves to an unprofiled model or one that failed. Each profile records the model's digest, so re-pulling a tag invalidates its profile (`hamllm models` and `hamllm doctor` flag it STALE). Ties go to the higher score, then the faster model. A plain model tag always resolves to itself.

Models are sampled at their default temperature, so results vary run to run: with `--repeats 3` a single miss drops a case to 67%. Use `--repeats 5` or more before trusting a profile.

The same cases run as pytest tests: `HAMLLM_LIVE=1 python -m pytest tests/test_live_models.py -v`.

## MCP server (`hamllm mcp`)

Standard-library stdio server, read-only: `ask_local(prompt, system?, model?, max_tokens?)` and `local_models()`. Every call sets a deliberate context window (`num_ctx`), an output cap and `keep_alive`, so clients cannot thrash VRAM or hold the GPU. Failures come back as tool errors, so the calling model can fall back.

```bash
claude mcp add hamllm -- hamllm mcp                 # Claude Code
```
```toml
# Codex: ~/.codex/config.toml
[mcp_servers.hamllm]
command = "hamllm"
args = ["mcp"]
```
```jsonc
// Zed: settings.json (check current Zed docs for the exact key)
"context_servers": { "hamllm": { "command": "hamllm", "args": ["mcp"] } }
```

Offloading is not privacy: the prompt comes from the calling client and the answer returns to it.

## Configuration

- `HAMLLM_HOST` — Ollama base URL (default `http://127.0.0.1:11434`; `OLLAMA_HOST` also accepted)
- `HAMLLM_MODEL` — what `default` means (default `gpt-oss:20b`)
- `HAMLLM_NUM_CTX` — context window in tokens (default 16384; Ollama's own 4096 silently truncates)
- `HAMLLM_KEEP_ALIVE` — how long Ollama keeps a model loaded (default `30m`)
- `HAMLLM_TIMEOUT` / `HAMLLM_MCP_TIMEOUT` — request timeouts in seconds (300 / 120)
- `HAMLLM_STATE_DIR` — where profiles live
- `--reasoning low|medium|high` — optional Ollama reasoning level

## Library API

- `hamllm.ollama.OllamaClient` — dependency-free transport: `generate`, `chat`, model discovery, `options`, `keep_alive`.
- `hamllm.agent.AgentRuntime` / `ToolRegistry` — bounded tool loop and the adapter boundary that lets applications keep their own tools and security policy.
- `hamllm.profiles` — profile store and alias resolution.
- `hamllm.evals` — the capability suite.

`hamGwen` consumes the agent core and transport while keeping its own tools, approval previews, prompts and policy. Helix packages a pinned snapshot of this CLI. `HamSidian` stays separate. See [`docs/CONSOLIDATION.md`](docs/CONSOLIDATION.md) and [`docs/INTEGRATION.md`](docs/INTEGRATION.md).

## Install and develop

```bash
python3 -m pip install .          # or: nix-build
python3 -m compileall -q src tests
python3 -m pip install -e . pytest
python3 -m pytest -q
```
