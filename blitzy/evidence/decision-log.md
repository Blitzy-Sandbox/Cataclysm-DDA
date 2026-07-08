# Decision Log

This Decision Log is the single source of truth for every *why* in this engagement.  It satisfies the user's sole explicit rule — **Explainability** — which requires that every non-trivial decision, and every deviation from the obvious interpretation of the requirements, be documented with rationale in a Markdown decision-log table, that such rationale never be embedded in code comments, and that this log be authoritative.  It mirrors the Agent Action Plan (AAP) §0.10 verbatim, so reviewers have one canonical record of intent.  The user's directive to "follow the steps detailed in the environment guide except…" produced three explicit overrides — decisions 1, 2, and 3 below — each reconciled here against the environment guide's defaults.

## Rules Compliance

- **Decision log present.**  The table below records all non-trivial decisions and every deviation from a literal reading of the environment guide.
- **No rationale in code comments.**  The only script authored for this engagement, the root `record-ui.sh`, reproduces the guide's operational logic and contains no "why" prose; all reasoning lives here instead.
- **Traceability matrix not applicable.**  The Explainability rule mandates a bidirectional source→target matrix only for migrations or refactors; this engagement performs neither, so no such matrix is produced (itself recorded as decision 13 below).
- **Single source of truth.**  This file mirrors AAP §0.10 verbatim, so reviewers have one authoritative "why" document rather than rationale scattered across commits or comments.

## Decision Log

| # | What was decided | Alternatives considered | Why chosen | Risks |
|---|------------------|-------------------------|------------|-------|
| 1 | Play **~60 in-game seconds** from spawn | Guide's "at most 10 in-game seconds" | Explicit user override ("a full one minute in game time") outranks the guide default | Longer exposure in a dangerous lone city start; mitigated by cautious, deliberate actions |
| 2 | Build a **survival-optimized custom** survivor that still has a coherent persona | Guide's unique/non-min-maxed survivor; "Play Now!"/random | User override ("optimized for surviving and thriving"); persona retained so the journal deliverable stays grounded | Tension with the guide's anti-min-max intent — documented and accepted |
| 3 | **Add and commit** all evidence to git as `agent@blitzy.com` | Leave evidence uncommitted (guide is silent on git) | Explicit user requirement (both screenshots and video committed) | Large media in git history; acceptable — no LFS filter configured, files commit as blobs |
| 4 | Select the in-game **"Missed"** scenario | Any other scenario | Explicit user directive; scenario confirmed in data [data/json/scenarios.json:L57] | None; a valid, high-danger start that motivates the optimized build |
| 5 | Store evidence under **`blitzy/evidence/`**; `record-ui.sh` at repo root | Repo root; a new top-level `evidence/`; `data/screenshots/` | `blitzy/` is already tracked; `*.mp4`/`*.png`/`*.md` are not gitignored; keeps engagement evidence separate from game assets | None material |
| 6 | Build via the **SDL2 fallback (`SDL3=0`)** | SDL3 default path | `libsdl3-dev` has no candidate on Ubuntu 24.04 and the Makefile enforces an SDL3 ≥ 3.4.0 floor [Makefile:L792-L793] | None; the SDL2 path is fully supported |
| 7 | **Verify, not re-apply**, the SDL2 guard in `pixel_minimap.cpp` | Re-apply the guide's patch | Guards are already merged at [src/pixel_minimap.cpp:L284,L476]; editing would be redundant and would dirty the tree | None; a no-op confirmed by inspection |
| 8 | **Configure git identity** before committing | Commit with default/unset identity | Git `user.name`/`user.email` are unset; a commit would otherwise fail | None |
| 9 | **Verify BOTH** `cata-ui.mp4` and `cata-play.mp4` non-blank | Verify only the UI-gate clip (guide's literal requirement) | A blank play clip would not be credible evidence that "the game is functioning" | Minor extra effort; negligible |
| 10 | Capture the **spawn clock `T0`** and **Save & Quit clock (~`T0`+60s)** as readable frames | Rely on wall-clock timing | Provides objective proof the ~60-second in-game gate was honored | None |
| 11 | Use the guide's **8-part report structure**; no user template | Invent a bespoke structure | No template was provided; the guide already prescribes the required report sections | None |
| 12 | Keep **existing repo docs REFERENCE-only** (`README`, `doc/**`, `doxygen_doc/**`) | Update them to mention the run | User requested evidence, not upstream doc edits; keeps the change surface minimal | None |
| 13 | Produce **no bidirectional traceability matrix** | Author a source→target traceability matrix | The Explainability rule requires such a matrix only for migrations or refactors, and this engagement performs neither | None |

---

*This log mirrors AAP §0.10 verbatim and is the authoritative record of every decision and deviation in this engagement.*
