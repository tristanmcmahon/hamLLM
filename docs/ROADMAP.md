# Ham roadmap and hygiene plan

Evidence date: 2026-10-09. Scope: every repository under `tristanmcmahon` (19). Ownership and invariants live in [`CONSOLIDATION.md`](CONSOLIDATION.md); this file is the sequenced work and the evidence behind it, and it should change more often than that one.

Method, so the numbers can be re-checked: shallow clones of every repo with full history for the default branches; branch state from `git` and GitHub's PR history; CI state from the latest default-branch run; a pattern scan of working trees for committed secrets (private keys, common token formats, quoted long secrets; not a history scan). Nothing was deleted or changed outside this repository.

## Snapshot

| Group | Repos | State |
| --- | --- | --- |
| Local AI | `hamLLM` (anchor), `hamGwen` (consumer), `HamSidian` (separate), `hamBridge` (retired) | Healthy. Gwen and Helix still pin an old hamLLM |
| Helix workstation | `nixos-helix`, `hamCade`, `hamSteam`, `nixos-config` (superseded) | Healthy; `nixos-helix` has its own finished roadmap |
| NAS | `hamOlogy`, `hamFence`, `hamKeyDist` | Healthy and actively changing |
| MiSTer | `tfpga`, `MrKeeper`, `tristerFAVs` | Working scripts plus one design-only repo |
| Shell and desktop | `modern-bash`, `hamCintosh` | Healthy; `hamCintosh` has no CI |
| Other | `hamWorld`, two personal documentation repos | Out of scope for the AI plan |

Good news first. The latest default-branch CI run passed in every repo I could query (hamLLM, hamFence, hamOlogy, hamGwen, hamSteam, hamCade, hamSidian, tfpga; `nixos-helix` and `modern-bash` were not queried). The secret scan found nothing. Ownership boundaries are written down in `CONSOLIDATION.md` and in the guidance files of the repos that have one; code was not audited against them.

## Findings

1. **Stranded work.** Two hamLLM commits (a Zed settings editor and an installer doctor fix, about 700 lines with tests) were pushed to a PR branch after the PR merged, so they never reached `master`. A plain "delete merged branches" sweep would have destroyed them. They are now on the `claude/repos-cleanup-dev-plan-43obhe` branch with their tests passing.
2. **Pin drift.** `hamGwen`'s submodule and `nixos-helix`'s vendored copy both sit at hamLLM `4f2f931`, 19 commits behind `master`. Verified 2026-10-09: Gwen's 52 unit tests pass against both the pin and `master`. Its live evals were not run, and Helix's snapshot needs Nix to validate. The `modern-bash` and `hamCade` snapshots in `nixos-helix` and the `modern-bash` submodule in `hamCintosh` are current.
3. **The compatibility rule had no test.** "`hamllm.agent` and `hamllm.ollama` import paths must keep working" was only a sentence. `tests/test_consumer_contract.py` now pins the exact keyword arguments Gwen passes and fails if one is removed, renamed or made required.
4. **Branch sprawl.** 121 non-default remote branches across ten repos. 108 are safe to delete (ancestors of the default branch, content already present, or the exact tip of a merged PR; every such PR targeted the default branch). One holds the stranded work from finding 1 and is deleted only once that work is on `master`. Six never had a merged PR (closed unmerged, merged then rolled back, or no PR at all) and are tagged `archive/<name>` before deletion so nothing is lost. Six are deliberate keeps (two named checkpoints, a backup, two branches behind open PRs, and this cleanup branch). A second review corrected the first count: one branch counted as merged had its PR merged and then rolled back, so it moved to the tagged group. The list with tip SHAs for restoring is kept privately because most of the repos are private.
5. **Two PRs untouched since 2026-09-18** (`hamCintosh` backup pruning, `hamSidian` macOS workflow), both still open.
6. **Convention drift.**
   - Default branch: `master` in four repos (hamFence, hamOlogy, hamCade, hamGwen), `main` elsewhere.
   - Agent guidance: `AGENTS.md` in three repos, `CLAUDE.md` in two, neither in most of the rest.
   - CI: none in hamKeyDist, hamCintosh, hamWorld, MrKeeper. The first, second and fourth already have shell tests; hamWorld has none.
   - `.gitignore` missing in tfpga, hamKeyDist, hamWorld, MrKeeper; no README in hamWorld.
   - No LICENSE in any code repo, including the two public ones (hamLLM, nixos-helix), which means all rights reserved by default.
7. **Retired repos still listed.** `hamBridge` says itself it can be archived; `nixos-config` is the 2025 stock install config that `nixos-helix` replaced.
8. **Naming.** `tfpga` holds SMB ROM bind mounts, and `MrKeeper`'s default integration expects those scripts' paths. Neither name or README says so.

## Plan

Each phase is small PRs that keep CI green. "Done when" is the check, not the intention.

### Phase 0: close the loops (owner decisions, minutes each)

- Merge the hamLLM cleanup branch (rescued work, CI lint, contract test, these docs). Done when: CI green on `master`, then delete `claude/fervent-bardeen-iqmlz0`.
- Delete the 108 merged branches, tag-then-delete the 6 unmerged ones, and delete the stranded-work branch once its content is on `master` (a script that checks each branch is still at the reviewed commit does this). Then turn on "Automatically delete head branches" in every repo so this does not regrow. Done when: each repo lists only its default branch, named checkpoints and open-PR branches.
- Merge `hamCintosh` #2 and `hamSidian` #46 (decided 2026-10-10). Both were mergeable and up to date; hamSidian's CI is green and hamCintosh's regression test passes locally, though hamCintosh has no CI.
- Archive `hamBridge` and `nixos-config` (repository settings; a README pointer already exists for the first).

### Phase 1: pins (this week)

- Bump Gwen's submodule to hamLLM `master`, run `make test` and then `make eval` against the real model on Helix. Done when: both pass and the PR notes the evals.
- Refresh `nixos-helix`'s hamLLM snapshot with its `scripts/vendor-sync.sh`, then `./scripts/dev-shell.sh --run './scripts/check.sh'` and, because the snapshot ships the MCP server, `hamllm doctor` on Helix after activation. Done when: `vendor/sources.json` names current `master`.
- Make drift visible: a scheduled workflow in `hamGwen` and `nixos-helix` that opens an issue when the pinned hamLLM commit is more than N commits behind. Done when: it fires on a deliberately stale pin.
- Rule: a branch that has had a PR merged is finished. New work goes on a new branch (this is how finding 1 happened).

### Phase 2: baseline conventions (two weeks)

- Pick one agent-guidance file per repo (suggest `AGENTS.md` as the real file with a one-line `CLAUDE.md` pointer so both tools read it) and add it to the code repos without one, starting with `hamGwen`, `hamSteam`, `hamSidian`.
- Add CI to hamKeyDist, hamCintosh and MrKeeper (syntax check plus the tests they already have; `tfpga`'s workflow is the template) and to hamWorld (syntax check only, it has no tests). Add shellcheck wherever it is already clean.
- Add `.gitignore` and a README where missing.
- Standardise the default branch on `main` (GitHub redirects the old name; check any script or doc that names `master`).
- Decide licences for the two public repos.

### Phase 3: hamLLM, driven by evidence

Taken from `CLAUDE.md` open items, in order of how much each unblocks:

1. Confirm Zed loads the server using `scripts/install.sh --zed` (the one client never verified).
2. Offload usage log (time, model, latency, counts; never prompts) so there is data on whether clients call `ask_local` unprompted. Do not build more offload features until this says they matter.
3. If it does: roll out the opt-in `CLAUDE.md`/`AGENTS.md` offload rule, then deterministic hooks (`prepare-commit-msg` via `hamllm run --model fast`).
4. Re-profile the `helix-*` and `gwen` wrapper models with exact `:latest` tags at 5+ repeats.
5. Only if needed: harder evals (when several models tie at 100%), streaming, then `hamllm acp`.

### Phase 4: MiSTer tooling (decision, low urgency)

Recommended: leave the repos split, rename `tfpga` to say what it is, and cross-link the READMEs so the dependency between `MrKeeper` and the bind-mount scripts is written down. An earlier PR adding MrKeeper to `tfpga` was closed unmerged and MrKeeper lives in its own repo, so the split looks deliberate and merging again would reverse it. Revisit only when `tristerFAVs` gets code.

### Not proposed

No cross-cutting changes to `hamOlogy`, `hamFence`, `hamCade`, `hamSteam`, `HamSidian`: each defines its own scope in its docs and its CI is green. `nixos-helix`'s own roadmap (`docs/roadmap.md` there) is complete apart from two items it records as deliberately skipped.

## Decisions for the owner

1. ~~Delete the merged branches~~ (decided 2026-10-10: yes; reversible from the recorded SHAs and the `archive/` tags).
2. ~~The unmerged branches~~ (decided: tag then delete).
3. ~~The two open PRs~~ (decided: merge both).
4. Archive `hamBridge` and `nixos-config`.
5. `main` everywhere, and `AGENTS.md` plus a `CLAUDE.md` pointer?
6. Licence for the public repos, or deliberately none.
7. MiSTer: split and cross-link (recommended) or merge.

## Keeping it tidy

A monthly pass is enough: branches older than 30 days with no PR, PRs older than 14 days, pinned hamLLM distance, any repo whose latest default-branch CI is red. It is cheap to automate as a scheduled job once Phase 0 has removed the backlog; before that it would only report the backlog.
