# Integrating local models with Claude, Codex and Zed

Status: capability evals, profiles/aliases and the stdio MCP server (option B) are implemented. Options C and D below are still design only.
Zed, ACP, Codex and Claude Code details below are from memory and move quickly: check each against current docs before building.

## Step zero: find out what the local model can do

`hamllm eval` (CLI, `--save` stores a profile) and `tests/test_live_models.py` (pytest) run a real model through `AgentRuntime` against an in-memory sandbox and score the transcript deterministically.

```bash
hamllm eval --model gpt-oss:20b --repeats 3        # per-case pass rate, per-category verdict
HAMLLM_LIVE=1 HAMLLM_MODEL=qwen3.6:27b python -m pytest tests/test_live_models.py -v
```

| Category | Question it answers |
| --- | --- |
| basic | Does it answer at all, correctly? |
| instruction | Does it honour exact formats, counts, and the system prompt? |
| tools | Does it call tools when needed, chain them, and stay quiet when not? |
| safety | Does a refused mutation stay refused, and does it say so? |
| coding | Can it read, fix, and verify (the Zed agent-panel workload)? |
| context | Does it recall a fact ~7k tokens deep? Ollama's default 4k window silently truncates, so a failure here is usually configuration, not capability. |

`hamllm eval` exits 1 unless every category clears `--threshold` (default 80%). Its `--json` report is the capability profile the routing ideas below consume.

Known limits of the suite: honesty after a denied write is a keyword heuristic; the coding case is one tiny bug, a floor not a ceiling; models are sampled at default temperature, so use `--repeats`.

## Roles

- **Local (Ollama on Helix):** private, free, always on, weaker at long-horizon reasoning and sometimes shaky at tool calls.
- **Claude / Codex:** strong agents, remote, metered.
- **Zed:** the editor hub that can talk to all three.

## Options, cheapest first

### A. Zed talks to Ollama directly (works today)
Zed has a built-in Ollama provider (`language_models.ollama.api_url`, pointed at Helix's loopback or LAN Ollama). hamLLM adds nothing at runtime; the eval is the gate for deciding which model to select. Check Zed's per-model tool-support flag against the `tools` and `coding` results before using it in the agent panel.

### B. `hamllm mcp`: one stdio MCP server, three clients (implemented)
Zed (`context_servers`), Claude Code (`claude mcp add`) and Codex (`mcp_servers` in its config) all speak MCP, so one dependency-free stdio server serves them all.

Proposed tools, read-only by default:

- `ask_local(prompt, system?, model?)`: single generation for cheap work such as summaries, commit messages, classification and log triage.
- `local_models()`: installed models plus the latest eval verdict per category.
- Not built; later, opt-in: `local_agent(task)` running `AgentRuntime` with read-only tools only, exposed only if `tools` and `safety` pass.

Claude or Codex can then offload bulk, low-stakes work to the local model and spend their own tokens on the hard parts.

**Privacy caveat:** B does not make anything private. The prompt arrives from a cloud model and the answer returns to it. Privacy-sensitive routing has to be decided by the user or the client, never by the cloud model's choice to call the tool. Say this in the tool description.

### C. `hamllm acp`: local agent inside Zed's agent panel
Zed hosts external agents over the Agent Client Protocol (Claude Code and Codex via adapters). A `hamllm acp` agent would put `AgentRuntime` in that same panel, mapping ACP permission requests onto the `approver` callback, so the local model gets the default-deny approval flow. This is the right home for Gwen-style tools but needs streaming (below) and a larger build. Do it only if B shows people actually want the local agent in-editor.

### D. Eval-gated routing
Persist `hamllm eval --json` per model. `local_models()` and any router use it: delegate a category only if that model passed it recently. This stops the failure mode of trusting a model that cannot call tools.

## Status of the prerequisites

1. **Context control: done.** `options` and `keep_alive` pass through `OllamaClient`; `AgentRuntime(options=...)` forwards them only when set, so older fake clients keep working. hamLLM defaults to a 16k window instead of Ollama's silent 4k.
2. **Streaming: open.** All calls are `stream: false`; ACP and editor UIs would want incremental output.
3. **Approver errors: open.** An approver that raises still aborts the turn; decide whether that should be a denial.
4. **Boundaries: held.** The MCP server is stdio-only, read-only, and talks only to the configured Ollama host.

Evals deliberately leave temperature at the model default, so `--repeats` measures realistic variance.

## Suggested order

1. Run `hamllm eval --save --repeats 3` on each model Helix serves.
2. Register `hamllm mcp` in Zed, Claude Code and Codex (snippets in the README).
3. Revisit C (`hamllm acp`) once there is real usage, and add streaming then.
