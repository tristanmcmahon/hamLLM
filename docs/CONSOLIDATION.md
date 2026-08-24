# Ham consolidation

This document defines the repository ownership model for the current Ham family. The goal is fewer duplicated runtimes without turning unrelated applications into one monolith.

## Rule

A Ham survives as a repository when it owns a durable domain job. Reusable local-AI transport/runtime mechanics belong in `hamLLM`. Helix machine configuration and service lifecycle belong in `nixos-helix`.

## Ownership map

| Repository | Decision | Durable responsibility |
| --- | --- | --- |
| `hamLLM` | **Anchor / expand** | Shared local Ollama transport, runtime primitives, common bounded integration surfaces |
| `hamGwen` | **Migrate, then compatibility/archive** | Today: Gwen agent/tool runtime. End state: Gwen persona/config/evals on top of `hamLLM`, with no duplicated core runtime |
| `hamBridge` | **Retire** | No independent responsibility; bridge functionality lives in `hamLLM` |
| `HamSidian` | **Keep separate** | Read-only-source Obsidian analysis, derived-vault publication, semantic-navigation policy and safety contract |
| `hamSteam` | **Keep separate** | Steam-library ranking, capacity policy, placement and supported-client actions |
| `hamCintosh` | **Keep separate** | Conservative Apple Silicon user-environment bootstrap |
| `hamKeyDist` | **Keep separate** | Home-LAN SSH public-key distribution and removal |
| `nixos-helix` | **Keep separate infrastructure** | Helix NixOS configuration, mounts, packages, user services/timers and machine integration |

Non-Ham domain tools such as `tfpga` remain outside this consolidation unless they independently duplicate one of these responsibilities.

## Invariants

1. **Domain policy stays with the domain application.** `hamLLM` must not learn Steam ranking policy, Obsidian publication rules, SSH topology, or macOS bootstrap policy.
2. **Machine lifecycle stays in NixOS.** If a Ham supplies a steady-state program on Helix, `nixos-helix` owns the declarative user service/timer that runs it.
3. **Local-model mechanics converge.** Ollama HTTP handling, common chat/generate transport, reusable agent-loop primitives, and shared model/runtime inspection should not be independently reimplemented.
4. **Security boundaries may only become stricter during migration.** Gwen's approval gates and HamSidian's source-vault protections are migration requirements, not optional cleanup targets.
5. **Compatibility beats flag day.** Existing commands stay available until parity tests prove their replacement.
6. **A tombstone is better than a zombie.** Once a repository has no independent responsibility, its README should point to the surviving owner and it should stop accepting new implementation work.

## Gwen migration sequence

Gwen contains the largest body of reusable local-agent work, so it moves in slices.

### 1. Transport and CLI foundation — this branch

- replace `hamLLM`'s one-off `requests` Ollama call with a standard-library transport;
- support both `/api/generate` and `/api/chat`;
- preserve bare `hamllm` as the legacy bridge invocation;
- add explicit `hamllm bridge` and direct `hamllm chat` surfaces;
- put CI around the package before moving richer code.

### 2. Agent core

Move Gwen's model-independent conversation/tool loop into `hamLLM` without changing its behavioural contract:

- bounded tool rounds;
- duplicate-call suppression;
- tool-result evidence rules;
- deterministic final-response policy;
- clear exhausted-budget reporting.

Gwen's existing behavioural evals are the acceptance tests.

### 3. Tool registry and approvals

Move reusable workspace/Git/process/service tooling behind explicit registries. Preserve:

- default-deny mutation behaviour;
- human approval previews;
- exact-path Git staging/commit boundaries;
- destructive-action resistance;
- no arbitrary shell surface.

Application-specific tools remain with their owning application unless proven generic.

### 4. Gwen compatibility surface

Once parity is demonstrated:

- keep the `gwen` model/persona/config name;
- provide a compatibility command for existing Gwen workflows;
- stop adding runtime code to the standalone `hamGwen` repository;
- archive/tombstone `hamGwen` only after its live eval suite passes against `hamLLM`.

### 5. Consumers

Only after the shared interface is stable should consumers opt in. HamSidian in particular must retain its local-only, read-only-source reviewer contract; moving its reviewer plumbing is not required merely to declare consolidation complete.

## Completion criteria

The local-AI consolidation is complete when:

- `hamBridge` contains only a retirement pointer;
- `hamGwen` contains no unique agent/runtime implementation, only compatibility/persona material or an archive pointer;
- Gwen behavioural evals pass against the `hamLLM` implementation;
- `HamSidian`, `hamSteam`, `hamCintosh`, and `hamKeyDist` remain independently understandable from their own READMEs;
- `nixos-helix` remains the only owner of Helix service lifecycle configuration.
