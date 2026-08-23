# hamLLM

Minimal Gmail → Ollama mail bridge.

The Python package lives under `src/hamllm/` and exposes the `hamllm` command via `hamllm.bridge:main`.

## Repository layout

- `src/hamllm/` — bridge, Gmail, Ollama, and state handling
- `scripts/` — helper scripts
- `tests/` — automated tests
- `default.nix` — Nix packaging entry point

This repository currently uses `master` as its default branch.
