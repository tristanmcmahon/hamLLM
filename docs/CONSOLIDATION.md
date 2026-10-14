# Ham consolidation

The goal is fewer duplicated runtimes without turning unrelated applications into one monolith.

## Ownership map

| Repository | Decision | Durable responsibility |
| --- | --- | --- |
| `hamLLM` | **Anchor / expand** | Capability evals and profiles for local models, alias resolution, MCP front door, shared transport, bounded agent-runtime primitives |
| `hamGwen` | **Thin compatibility/persona layer** | Gwen tools, approval previews, prompts, policy and behavioural evals over `hamLLM` |
| `hamBridge` | **Retire** | Tombstone only; the old mail bridge is not retained |
| `HamSidian` | **Keep separate** | Read-only-source Obsidian analysis, local semantic review, derived-vault publication and safety contract |
| `hamSteam` | **Keep separate** | Steam-library ranking, capacity policy, placement and supported-client actions |
| `hamCintosh` | **Keep separate** | Conservative Apple Silicon user-environment bootstrap |
| `hamKeyDist` | **Keep separate** | Home-LAN SSH public-key distribution and removal |
| `nixos-helix` | **Keep separate infrastructure** | Helix NixOS configuration, mounts, packages, services/timers and machine integration |
| `hamCade` | **Keep separate** | Arcade/MAME application policy, curation, saves and state; `nixos-helix` owns host integration and only vendors its `dependencies.nix` |
| `hamOlogy` | **Keep separate** | Operating toolkit for the NAS's Docker media and infrastructure stack |
| `hamFence` | **Keep separate** | NAS networking, TLS, private ingress and DNS policy (container lifecycle stays with `hamOlogy`, SSH keys with `hamKeyDist`) |
| `modern-bash` | **Keep separate** | Portable Bash environment; consumed by `hamCintosh` (submodule) and `nixos-helix` (snapshot) |
| `tfpga`, `MrKeeper`, `tristerFAVs` | **Keep separate, document the link** | MiSTer tooling: SMB ROM bind mounts; cron-backed maintenance that calls the bind-mount script; a design-only favourites generator |
| `hamWorld` | **Keep separate** | Single-script RimWorld mod bootstrapper; unrelated to the AI stack |
| `nixos-config` | **Retire** | 2025 stock NixOS install config, superseded by `nixos-helix`; archive |

## Invariants

1. Domain policy stays with the domain application.
2. Helix machine lifecycle belongs in `nixos-helix`, not application repositories.
3. Local-model mechanics converge in `hamLLM`.
4. Security boundaries may only become stricter during migration.
5. A retired responsibility is removed or tombstoned rather than kept alive as compatibility baggage.
6. Existing application behaviour is migrated only when parity tests prove the shared replacement.

## Completed local-AI slices

### Local-only transport and CLI

`hamLLM` owns dependency-free Ollama transport plus `run`, `models`, `doctor`, `eval`, `resolve` and `mcp`. The interactive `chat` command was removed in 0.2.0 as a duplicate of `ollama run`. The historical Gmail/OAuth/mail-poller implementation is removed rather than preserved as a second integration path.

### Capability layer (0.2.0)

`hamllm eval --save` records per-category pass rates per model; aliases (`fast`, `tools`, `code`) resolve only to installed models that passed; `hamllm mcp` exposes read-only `ask_local` and `local_models` to Zed, Claude Code and Codex with a fixed context window, output cap and keep-alive. `hamllm.agent` and `hamllm.ollama` keep their import paths for Gwen's pinned submodule.

### Bounded agent core

`hamLLM.agent.AgentRuntime` owns model-independent orchestration:

- bounded tool rounds;
- duplicate observation/mutation/execution suppression;
- default-deny approval handling;
- state-change cache invalidation;
- deterministic response-policy rewriting;
- evidence-aware final synthesis when the tool budget is exhausted.

### Gwen adapter

Gwen consumes the shared agent core and Ollama transport through a pinned
`hamLLM` submodule. Gwen continues to own its concrete workspace/Git/process/service
tools, approval previews, destructive-command response policy, prompts and evals.

### Helix package adapter

`nixos-helix` packages a provenance-labelled hamLLM source snapshot for its
development profile. It does not own hamLLM behaviour. The editor clients use
Helix's loopback Ollama service directly; hamLLM does not proxy their traffic.
The running model list and GPU use must be checked on Helix after activation.

## Next possible slice

Reusable tool implementations may move into `hamLLM` only where they can be parameterised without weakening Gwen's boundaries. Application-specific tools remain with Gwen.

HamSidian is not a mandatory consumer: its OpenClaw reviewer and source-vault protections are a distinct security boundary and should remain separate unless a later migration produces a clear safety or maintenance benefit.

## Where the plan lives

The sequenced work for all of these repositories, with the evidence behind it, is in [`ROADMAP.md`](ROADMAP.md). This file stays the ownership map and the invariants; the roadmap changes more often.
