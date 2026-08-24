# Ham consolidation

The goal is fewer duplicated runtimes without turning unrelated applications into one monolith.

## Ownership map

| Repository | Decision | Durable responsibility |
| --- | --- | --- |
| `hamLLM` | **Anchor / expand** | Local Ollama CLI, shared transport, bounded agent-runtime primitives |
| `hamGwen` | **Thin compatibility/persona layer** | Gwen tools, approval previews, prompts, policy and behavioural evals over `hamLLM` |
| `hamBridge` | **Retire** | Tombstone only; the old mail bridge is not retained |
| `HamSidian` | **Keep separate** | Read-only-source Obsidian analysis, local semantic review, derived-vault publication and safety contract |
| `hamSteam` | **Keep separate** | Steam-library ranking, capacity policy, placement and supported-client actions |
| `hamCintosh` | **Keep separate** | Conservative Apple Silicon user-environment bootstrap |
| `hamKeyDist` | **Keep separate** | Home-LAN SSH public-key distribution and removal |
| `nixos-helix` | **Keep separate infrastructure** | Helix NixOS configuration, mounts, packages, services/timers and machine integration |

## Invariants

1. Domain policy stays with the domain application.
2. Helix machine lifecycle belongs in `nixos-helix`, not application repositories.
3. Local-model mechanics converge in `hamLLM`.
4. Security boundaries may only become stricter during migration.
5. A retired responsibility is removed or tombstoned rather than kept alive as compatibility baggage.
6. Existing application behaviour is migrated only when parity tests prove the shared replacement.

## Completed local-AI slices

### Local-only transport and CLI

`hamLLM` owns dependency-free Ollama transport plus `run`, `chat`, `models`, and `doctor`. The historical Gmail/OAuth/mail-poller implementation is removed rather than preserved as a second integration path.

### Bounded agent core

`hamLLM.agent.AgentRuntime` owns model-independent orchestration:

- bounded tool rounds;
- duplicate observation/mutation/execution suppression;
- default-deny approval handling;
- state-change cache invalidation;
- deterministic response-policy rewriting;
- evidence-aware final synthesis when the tool budget is exhausted.

### Gwen adapter

Gwen consumes the shared core through a pinned `hamLLM` submodule. Gwen continues to own its concrete workspace/Git/process/service tools, approval previews, destructive-command response policy, prompts and evals.

## Next possible slice

Reusable tool implementations may move into `hamLLM` only where they can be parameterised without weakening Gwen's boundaries. Application-specific tools remain with Gwen.

HamSidian is not a mandatory consumer: its OpenClaw reviewer and source-vault protections are a distinct security boundary and should remain separate unless a later migration produces a clear safety or maintenance benefit.
