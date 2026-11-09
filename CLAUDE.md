# hamLLM: notes for future sessions

## What this repo is
The capability and policy layer in front of local Ollama models for the Ham projects. Ollama runs the models. hamLLM answers: what can each model actually do (evals), which model should a client use (profiles and aliases), how do Zed, Claude Code and Codex offload work to local models (MCP server), and how do apps run a local model safely (bounded agent runtime). It is not a chat client (use `ollama run`) and has no mail/Gmail code (the old bridge is retired).

Owner's stance: early work, free to re-architect, but `hamllm.agent` and `hamllm.ollama` import paths must keep working because hamGwen consumes them through a pinned submodule and nixos-helix packages a snapshot. Boundaries may only get stricter (see `docs/CONSOLIDATION.md`).

## Layout
- `src/hamllm/ollama.py`: stdlib transport (`generate`, `chat`, `installed()` -> tag:digest, `models()`, `capabilities()`; `options` and `keep_alive` only sent when set)
- `src/hamllm/agent.py`: `AgentRuntime` bounded tool loop. Tool schemas must be explicitly classified observational/mutating/executing with no overlap; unclassified schemas fail closed. Approvals default-deny, duplicate suppression and response policy remain bounded, with one retry on Ollama HTTP 500 "error parsing tool call"
- `src/hamllm/evals.py`: 18 cases in 6 categories (basic, instruction, tools, safety, coding, context) run against an in-memory `Sandbox`; deterministic checks, never exec model code
- `src/hamllm/profiles.py`: validated per-model eval profiles (digest-bound, with trial counts), aliases `fast`/`tools`/`code`, evidence-weighted ranking (Wilson lower bound, then latency from only the alias-relevant categories)
- `src/hamllm/mcp.py`: stdio MCP server, read-only tools `ask_local` and `local_models`; one serialized GPU worker, cancellation-aware Ollama streaming transport, 5m MCP keep-alive, optional prompt-free usage metadata
- `scripts/install.sh` (tested by `tests/test_install.py` with stub clients and Zed settings in a temp HOME): launcher at `~/.local/bin/hamllm` that runs this checkout (no pip, for NixOS), MCP registration with `HAMLLM_MODEL=code`, opt-in `--profile`/`--profile-all`/`--instructions`, `--dry-run`, `--uninstall`, and `--zed`. `src/hamllm/zed_settings.py` surgically updates JSONC `context_servers.hamllm`, backs up before changes, preserves unrelated settings and uses the PATH-resolved launcher
- `src/hamllm/config.py`: env settings (`HAMLLM_HOST/MODEL/NUM_CTX/KEEP_ALIVE/MCP_KEEP_ALIVE/TIMEOUT/MCP_TIMEOUT/USAGE_LOG/STATE_DIR`)
- `src/hamllm/cli.py`: `run`, `models`, `doctor`, `eval` (`--save`, `--all`, `--repeats`), `resolve`, `mcp`
- Profiles live in `~/.local/state/hamllm/profiles.json`

## Commands
`python3 -m pytest -q` (88+ tests, no Ollama needed; live tests need `HAMLLM_LIVE=1`), `ruff check --select F,E9,B,SIM src tests`, `hamllm eval --save --repeats 5 --model TAG`, `hamllm resolve code`. On NixOS there is no pip: use `PYTHONPATH=$PWD/src python3 -m hamllm ...` or `nix-build`. Model names must match exactly (`helix-gemma:latest`, not `helix-gemma`).

## Decisions and why
- Default context is 16k (`HAMLLM_NUM_CTX`) because Ollama's own 4k window silently truncates.
- MCP server reserves output space inside the context window, rejects stale/failed non-default explicit tags, and serializes GPU work. The configured default is the operator escape hatch. It is read-only. Offloading is NOT privacy: the prompt comes from the calling client and the answer returns to it.
- Aliases never resolve to an unprofiled model or one that failed the required categories. A changed digest voids a profile. Speed tie-breaking uses only latency from the categories the alias actually requires.
- argparse shares `parents=[common]` actions across subparsers: never use `set_defaults(timeout=...)` on one subcommand (it leaked mcp's 120s into every command). Timeouts resolve per command: 300s, MCP 120s.
- MCP tool output lands in a cloud model's context, so keep it small: `local_models` is a ~400-token text summary (was ~4k tokens of JSON), and `ask_local` defaults to a terse worker system prompt (the first real call returned a menu of options for a one-line ask).
- Claude Code's `claude mcp add --env` is variadic and swallows the server name as a KEY=VALUE: put another option (`--scope user`) after `--env`, before the name. Test stubs for external CLIs must mimic such parsing (a permissive stub hid this bug); the installer exits non-zero if any client registration fails.
- Eval checks must judge behaviour, not wording. Most early failures were brittle checks (unicode spacing, summaries quoting an injected attack, asking before writing is valid). Normalise text, judge claims per sentence, ignore hedged ones. Check real transcripts before blaming a model.
- Evals run at default temperature; 3 repeats is coarse, use 5+ before trusting a profile.

## Findings on the owner's Helix models (2026-10, 5 repeats)
`gemma4:12b` and `qwen3.6:27b` 100% everywhere (gemma4 1-8s per case, qwen 5-90s). `gpt-oss:20b` 80% coding (one bad fix, one malformed tool-call 500). `deepseek-r1:8b` not ready (prose tool use, false success claims). `gemma3:12b` no tool support. `qwen2.5-coder:14b` emits tool calls as plain JSON text. helix-*/gwen wrappers were READY at 3 repeats and need re-profiling.

## Offload to Claude/Codex/Zed
Registration snippets are in the README. The installer configures Zed's `context_servers` flat form in user settings. Zed loading hamLLM was verified on the owner's Helix workstation on 2026-11-09, and Claude Code user-scope registration was verified connected the same day. Ways offload can happen: (1) the model chooses to call `ask_local`, helped by a `CLAUDE.md`/`AGENTS.md` rule such as "use `ask_local` first for summaries, commit messages, classification, log triage"; (2) deterministic hooks that bypass the cloud model (git `prepare-commit-msg` calling `hamllm run --model fast`, log summarisers); (3) a routing gateway in front of the clients, deliberately NOT recommended (judging "easy" silently degrades results; small models struggle with big agent prompts).

## Open items
- Verified: the MCP server speaks the protocol correctly against the owner's real Ollama (2026-10-06); Claude Code and Codex registration work; Zed loaded the hamLLM MCP server on Helix on 2026-11-09; Claude Code reported the user-scoped hamLLM server Connected on 2026-11-09. Whether clients call `ask_local` unprompted is still unverified.
- Built in 0.2.1: optional prompt-free usage log (`HAMLLM_USAGE_LOG`), cancellation-aware streaming transport for MCP requests, shorter MCP-specific keep-alive, strict tool classification, semantic profile validation and alias-relevant latency ranking.
- Not built: incremental MCP result streaming to the client, `hamllm acp` (local agent in Zed's panel), CI lint step
- Bump Gwen's and Helix's pinned copies and run Gwen's tests (unverified; fields were added with defaults)
- Harder evals only if several models still score 100% and need ranking
