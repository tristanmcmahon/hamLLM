# Integrating local models with Claude, Codex and Zed

Status: design notes. Nothing here is implemented except `hamllm eval`.
Zed, ACP, Codex and Claude Code details below are from memory and move quickly: check each against current docs before building.

## Step zero: find out what the local model can do

`hamllm eval` (CLI) and `tests/test_live_models.py` (pytest) run a real model through `AgentRuntime` against an in-memory sandbox and score the transcript deterministically.

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

### B. `hamllm mcp`: one stdio MCP server, three clients (recommended next)
Zed (`context_servers`), Claude Code (`claude mcp add`) and Codex (`mcp_servers` in its config) all speak MCP, so one dependency-free stdio server serves them all.

Proposed tools, read-only by default:

- `ask_local(prompt, system?, model?)`: single generation for cheap work such as summaries, commit messages, classification and log triage.
- `local_models()`: installed models plus the latest eval verdict per category.
- Later, opt-in: `local_agent(task)` running `AgentRuntime` with read-only tools only, exposed only if `tools` and `safety` pass.

Claude or Codex can then offload bulk, low-stakes work to the local model and spend their own tokens on the hard parts.

**Privacy caveat:** B does not make anything private. The prompt arrives from a cloud model and the answer returns to it. Privacy-sensitive routing has to be decided by the user or the client, never by the cloud model's choice to call the tool. Say this in the tool description.

### C. `hamllm acp`: local agent inside Zed's agent panel
Zed hosts external agents over the Agent Client Protocol (Claude Code and Codex via adapters). A `hamllm acp` agent would put `AgentRuntime` in that same panel, mapping ACP permission requests onto the `approver` callback, so the local model gets the default-deny approval flow. This is the right home for Gwen-style tools but needs streaming (below) and a larger build. Do it only if B shows people actually want the local agent in-editor.

### D. Eval-gated routing
Persist `hamllm eval --json` per model. `local_models()` and any router use it: delegate a category only if that model passed it recently. This stops the failure mode of trusting a model that cannot call tools.

## Prerequisites in hamLLM before B/C

1. **Context control.** `OllamaClient.chat/generate` cannot pass `options` (`num_ctx`, `temperature`). Add an optional `options` argument; keep `AgentRuntime._chat` unchanged for Gwen's fake clients until Gwen opts in. Needed to make the `context` category meaningful and evals deterministic (`temperature: 0`).
2. **Streaming.** All calls are `stream: false`; ACP and editor UIs want incremental output.
3. **Approver errors.** An approver that raises currently aborts the whole turn; decide whether that should be a denial.
4. **Boundaries.** B stays loopback/stdio, no mutating tools, no network beyond the configured Ollama host (Invariant 4 in `CONSOLIDATION.md`: boundaries only tighten).

## Suggested order

1. Run `hamllm eval --repeats 3` on each model Helix serves; record the baselines.
2. Add the `options` passthrough.
3. Build `hamllm mcp` with `ask_local` and `local_models`; register it in Zed, Claude Code and Codex.
4. Revisit C once there is real usage.
