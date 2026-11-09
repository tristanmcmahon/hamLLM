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

## Install

```bash
scripts/install.sh --dry-run        # see exactly what it would do
scripts/install.sh                  # launcher + MCP registration for installed Zed, Claude Code and Codex
scripts/install.sh --zed            # only register Zed (also works before Zed is installed)
scripts/install.sh --profile-all    # ...and profile every installed text model (minutes per model)
scripts/install.sh --instructions   # ...and add an "offload to ask_local" rule to ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md
scripts/install.sh --uninstall      # remove all registrations, instruction blocks and the shared launcher
scripts/install.sh --uninstall --zed # remove only Zed; keep the shared launcher for other clients
```

It needs only Python 3.11+: no pip, no sudo (works on NixOS). It writes a `hamllm` launcher to `~/.local/bin` that runs this checkout, resolving `python3` from the runtime PATH rather than embedding a garbage-collectable Nix-store interpreter path, so `git pull` is the upgrade. The MCP server is registered with `HAMLLM_MODEL=code` (override with `HAMLLM_MCP_MODEL`), so it uses whichever installed model best passed the `code` evals; profile your models first or `ask_local` falls back to the `HAMLLM_MODEL` default. `HAMLLM_HOST` is passed through when set.

When Zed is on PATH or its settings already exist, install updates only `context_servers.hamllm` in `${XDG_CONFIG_HOME:-~/.config}/zed/settings.json`. It preserves JSONC comments, trailing commas, other settings and other MCP servers, and makes a timestamped `settings.json.hamllm-backup-*` before each change. `--uninstall` removes only the hamLLM entry; `--zed` targets Zed explicitly. The Zed command is `hamllm` so the launcher remains valid after Nix store garbage collection. Make sure `~/.local/bin` (or your `--prefix`/`PREFIX` bin directory) is on Zed's PATH; restart Zed after installation.

## Quick start

```bash
hamllm doctor                              # Ollama reachable, model installed?
hamllm eval --save --repeats 5             # profile the default model (full suite)
hamllm eval --save --repeats 5 --model qwen3.6:27b
hamllm eval --save --all --repeats 3       # every text-generation model, then a comparison table
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

An alias never resolves to an unprofiled model or one that failed its required categories. Each profile records the model's digest, so re-pulling a tag invalidates its profile (`hamllm models` and `hamllm doctor` flag it STALE). Ties go to the stronger evidence-weighted score, then latency measured only across the categories that alias requires. A plain model tag still resolves directly in the CLI; over MCP, a non-default explicit tag must have a current, fully ready profile.

Models are sampled at their default temperature, so results vary run to run: with `--repeats 3` a single miss drops a case to 67%. Use `--repeats 5` or more before trusting a profile.

The same cases run as pytest tests: `HAMLLM_LIVE=1 python -m pytest tests/test_live_models.py -v`.

## MCP server (`hamllm mcp`)

Standard-library stdio server, read-only: `ask_local(prompt, system?, model?, max_tokens?)` and `local_models()`. GPU work is serialized through one worker so concurrent clients cannot pile generations onto the same GPU, while the protocol loop remains responsive to MCP cancellation. Cancellable generations use Ollama's streaming HTTP response internally only so disconnect/cancel can stop wasted work; the MCP tool still returns one completed result.

Every call sets a deliberate context window, reserves room for the requested output cap, and uses an MCP-specific keep-alive (default 5m). Failures come back as tool errors so the calling model can fall back. Prompts that would overflow input + output context are rejected, aliases require current qualifying profiles, and a non-default explicit tag must have a current fully-ready profile. The configured default remains an explicit operator escape hatch.

Set `HAMLLM_USAGE_LOG=/path/to/usage.jsonl` to record opt-in performance metadata (timestamp, model, latency, character counts, output cap and status). Prompts, system text and generated answers are never logged.

The installer uses the stable checkout launcher path for Claude Code and Codex, and the PATH-resolved `hamllm` command for Zed. For manual registration, use a stable absolute launcher path if the client cannot find `hamllm` on PATH. To point at a non-default Ollama, add `HAMLLM_HOST`.

```bash
# Claude Code: --scope user makes it available in every project
claude mcp add --scope user hamllm -- hamllm mcp
claude mcp add --env HAMLLM_HOST=http://helix:11434 --scope user hamllm -- hamllm mcp   # remote Ollama
```
```bash
# Codex
codex mcp add hamllm -- hamllm mcp
```
```toml
# ...or by hand in ~/.codex/config.toml
[mcp_servers.hamllm]
command = "hamllm"
args = ["mcp"]
```
```jsonc
// Zed: settings.json (or Settings -> AI -> MCP Servers -> Add Local Server)
"context_servers": {
  "hamllm": { "command": "hamllm", "args": ["mcp"], "env": { "HAMLLM_MODEL": "code" } }
}
```

The flat Zed `context_servers` form matches [Zed's MCP documentation](https://zed.dev/docs/ai/mcp). It was verified working on Helix with Zed on 2026-11-09; after changing registration, restart the agent/editor session and check Settings → AI → MCP Servers for a green “Server is active” indicator. Claude Code's per-tool timeout is far longer than the server's 120s cap, so slow models time out inside hamLLM first and return a clean tool error.

Offloading is not privacy: the prompt comes from the calling client and the answer returns to it.

## Configuration

- `HAMLLM_HOST` — Ollama base URL (default `http://127.0.0.1:11434`; `OLLAMA_HOST` also accepted)
- `HAMLLM_MODEL` — what `default` means (default `gpt-oss:20b`)
- `HAMLLM_NUM_CTX` — context window in tokens (default 16384; Ollama's own 4096 silently truncates)
- `HAMLLM_KEEP_ALIVE` — general CLI keep-alive (default `30m`)
- `HAMLLM_MCP_KEEP_ALIVE` — MCP keep-alive (default `5m`; falls back to explicit `HAMLLM_KEEP_ALIVE`)
- `HAMLLM_TIMEOUT` / `HAMLLM_MCP_TIMEOUT` — request timeouts in seconds (300 / 120)
- `HAMLLM_USAGE_LOG` — optional JSONL path for prompt-free MCP usage/latency metadata
- `HAMLLM_STATE_DIR` — where profiles live
- `--reasoning low|medium|high` — optional Ollama reasoning level

## Library API

- `hamllm.ollama.OllamaClient` — dependency-free transport: `generate`, `chat`, model discovery, `options`, `keep_alive`.
- `hamllm.agent.AgentRuntime` / `ToolRegistry` — bounded tool loop and adapter boundary. Every declared tool must be explicitly classified as observational, mutating or executing; unclassified or multiply-classified schemas fail closed.
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
