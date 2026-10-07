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
scripts/install.sh                  # launcher + MCP registration for Claude Code and Codex (whichever are on PATH)
scripts/install.sh --profile-all    # ...and profile every installed text model (minutes per model)
scripts/install.sh --zed            # ...and add the server to Zed's settings.json (comments preserved, backup made)
scripts/install.sh --instructions   # ...and add an "offload to ask_local" rule to ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md
scripts/install.sh --uninstall      # remove the launcher, registrations and instruction blocks
```

It needs only Python 3.11+: no pip, no sudo (works on NixOS). It writes a `hamllm` launcher to `~/.local/bin` that runs this checkout, so `git pull` is the upgrade. The MCP server is registered with `HAMLLM_MODEL=code`, so it uses whichever installed model best passed the `code` evals; profile your models first or `ask_local` falls back to the `HAMLLM_MODEL` default. Without `--zed` it prints the Zed snippet and leaves Zed alone. `--zed` runs `scripts/zed_config.py`, which edits Zed's JSONC `settings.json` in place: it keeps your comments and formatting, makes a timestamped backup first, shows the change with `--dry-run`, and refuses to write if it can't parse the file. Run it directly for finer control (`--legacy` for older Zed's nested form, `--remove` to take the entry out, `--settings PATH` or `$ZED_SETTINGS` for a non-default file).

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

An alias never resolves to an unprofiled model or one that failed. Each profile records the model's digest, so re-pulling a tag invalidates its profile (`hamllm models` and `hamllm doctor` flag it STALE). Ties go to the higher score, then the faster model. A plain model tag always resolves to itself.

Models are sampled at their default temperature, so results vary run to run: with `--repeats 3` a single miss drops a case to 67%. Use `--repeats 5` or more before trusting a profile.

The same cases run as pytest tests: `HAMLLM_LIVE=1 python -m pytest tests/test_live_models.py -v`.

## MCP server (`hamllm mcp`)

Standard-library stdio server, read-only: `ask_local(prompt, system?, model?, max_tokens?)` and `local_models()`. Every call sets a deliberate context window (`num_ctx`), an output cap and `keep_alive`, so clients cannot thrash VRAM or hold the GPU. Failures come back as tool errors, so the calling model can fall back. Two guards bound what a calling client can make the GPU do: prompts that clearly overflow the context window are rejected rather than silently truncated, and only the default model or a profiled model can be loaded (an installed-but-unprofiled tag is refused).

Use an absolute path to `hamllm` (for example `./result/bin/hamllm` after `nix-build`) if it is not on the PATH of the client that launches it. To point at a non-default Ollama, add `HAMLLM_HOST`.

```bash
# Claude Code: --scope user makes it available in every project
claude mcp add --scope user hamllm -- hamllm mcp
claude mcp add --scope user --env HAMLLM_HOST=http://helix:11434 hamllm -- hamllm mcp   # remote Ollama
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
// Zed: scripts/zed_config.py (or install.sh --zed) adds this for you; by hand in settings.json
// (or Settings -> AI -> MCP Servers -> Add Local Server)
"context_servers": {
  "hamllm": { "command": "hamllm", "args": ["mcp"], "env": {} }
}
```

Claude Code, Codex and Zed docs were checked on 2026-10-06 (Zed's via search summaries, since its docs site was unreachable from the sandbox). If Zed does not load the server, older versions used a nested form: `"command": { "path": "hamllm", "args": ["mcp"] }`. Claude Code's per-tool timeout is far longer than the server's 120s cap, so slow models time out inside hamLLM first and return a clean tool error.

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
