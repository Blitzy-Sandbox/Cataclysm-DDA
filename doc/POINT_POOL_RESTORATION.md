# Point Pool Character Creation — Restoration

This document records the restoration of the Cataclysm: Dark Days Ahead (CDDA)
point-buy (a.k.a. *point-pool*) character-creation system. In point-buy mode the
player spends a finite budget of points across scenario, profession, background,
stats, traits, and skills, sees the running point balance while building the
character, and is prevented from finalizing an over-allocated survivor.

The system was removed in commit `e8b832bd1d` ("Completely remove legacy point
pools from character creation", #85528, 2026-02-25), with a follow-on hint edit in
commit `f2c5d14dde` ("remove mention of points pool in the hint", 2026-03-13).

Because the character creator was subsequently rewritten from the ncurses backend
to a Dear ImGui implementation in commit `1ae6881bb0` ("Imgui character creator",
2026-04-13) — which landed *after* the removal — a literal `git revert` is not
possible: the ncurses edit sites (`set_points`, `draw_points`, `pools_to_string`,
the `tab_manager` "POINTS" tab) no longer exist, and reverse-applying the removal
patch fails ("patch does not apply"). The feature is therefore being restored
*functionally* into the current Dear ImGui creator rather than by reverting the
patch — a staged effort spanning multiple checkpoints rather than a single
mechanical revert.

**Checkpoint status.** As of this checkpoint the serialized-contract foundation
is in place while the remaining in-creator work is planned but not yet present.
Using the Section B traceability numbering below: rows 1-2 (the `ONE_POOL` and
`MULTI_POOL` enum modes), row 3 (the `CHARACTER_POINT_POOLS` world option), and
row 18 (the New Game points-pool hint) are **implemented**; rows 4-17 — the
pool-aware points-left and points-summary helpers, `skill_increment_cost()`, the
`CHARCREATOR_POINTS` tab with the tab-count bump (7→8), the option read and pool
seed in `avatar::create()`, the top-bar and per-tab point accounting, the
per-selection cost/affordability feedback on the scenario/profession/background/
stats/traits/skills tabs, and the `ONE_POOL`/`MULTI_POOL` finalize guards,
together with the point-pool tests — are **pending** and are planned to land in
later checkpoints inside the ImGui creator. Sections A and B therefore describe
the full intended restoration; the decision log records each choice as it is
made, ahead of the code that implements it.

The restoration preserves the `pool_type` integer serialization contract:
`pool_type` is persisted to disk as the integer `"limit"` in character templates,
so the original integer mapping (`FREEFORM=0, ONE_POOL=1, MULTI_POOL=2,
TRANSFER=3`) is pinned to keep existing templates — including `TRANSFER`-based
character-transfer templates — loading unchanged.

Per the project's user-specified **Explainability** rule, every non-trivial
implementation decision and its rationale live in this document (the tables
below) rather than in code comments — covering both the foundation already
landed and the creator restoration still planned, so each decision is recorded
as it is made rather than after the fact. Section A is the decision log; Section
B is the bidirectional traceability matrix mapping every removed construct to its
restoration target, with 100% coverage (each row is traceable in both directions:
removed ⇄ restored).

## Section A — Decision Log

| Decision | Alternatives Considered | Rationale | Residual Risk |
|---|---|---|---|
| Functional re-implementation into the ImGui creator | `git revert`/cherry-pick of `e8b832bd1d` | Reverse-apply verified to fail ("patch does not apply") because the ncurses creator was replaced by ImGui in `1ae6881bb0` | Must re-derive UI wiring by hand; mitigated by the traceability matrix |
| Reuse the surviving point-math engine (`src/newcharacter.cpp` ~L249-341) | Re-add the removed `skill_points_left`/`pools_to_string` verbatim | Avoids duplicated/diverging math; the engine is already validated and used by `randomize()` | Restored helper signatures differ from the originals; logged here |
| Restore pool selection as a dedicated `CHARCREATOR_POINTS` tab (count 7→8) | Top-bar selector; option-only with no selection UI | 1:1 fidelity to the removed "POINTS" tab; consistent with the tabbed builder | Ripples through tab-indexed arrays/dispatch; enumerated and contained |
| Preserve enum integer values `FREEFORM=0, ONE_POOL=1, MULTI_POOL=2, TRANSFER=3` | Renumber sequentially | Keeps the template `"limit"` serialization and `TRANSFER` transfer templates working | None if pinned; guarded by a template round-trip test |
| Persistent points readout in the top bar | Per-tab header only (as in ncurses) | The ImGui top bar is always visible across tabs | Minor UX difference from the ncurses layout; acceptable |
| Keep `FREEFORM`/`story_teller` as the default | Default to `multi_pool` | Matches the removed option's default; least behavior change for current players | None |
| Add point-pool tests to `tests/new_character_test.cpp` (and/or a dedicated file) | A separate new test file only | Co-locates with existing character-generation tests | The file grows; acceptable |
| Add `#include "player_difficulty.h"` to `character_creator_ui.h` | Rely on the existing opaque `enum class pool_type;` in `avatar.h` | In-class initializer `pool_type::FREEFORM` needs the complete enum definition | None; standard include hygiene |
| Finalize the point-pool test seam as a dedicated `tests/char_creation_points_test.cpp` using test-local (mirrored) cost formulas, resolving the open choice left by the seeded testing row above | Expose the production point-math helpers (`point_pool_total`/`points_used_total`/`multi_pool`) as public API for tests; extend only `tests/new_character_test.cpp` | A dedicated file isolates point-pool coverage without widening the engine's internal-linkage surface, and mirrored formulas keep the test independent of private helpers | Formula drift: test-local formulas can diverge from production math if costs change; mitigated by also asserting through reachable engine entry points and reviewing test and engine together on any cost change |
| Reuse the existing character-creator input actions for pool selection and leave `data/raw/keybindings.json` unchanged (no discrete pool-select action) | Add a new discrete pool-select action with its own key binding | The existing tab-navigation and confirm actions already cover choosing a mode on the pool tab, honoring the no-new-keybinding constraint (AAP §0.3) | Action-contract/discoverability: without a dedicated binding the control is reachable only via generic navigation; mitigated by an on-tab label and the New Game hint that advertises the points pool |
| Persist named character templates with the live `cc_uistate.pool` value rather than a hard-coded `FREEFORM` | Always serialize `FREEFORM`; serialize only the local `avatar::create()` pool variable | `save_template()` already writes the passed `pool` as the integer `"limit"`, so sourcing it from the selected pool makes saved templates round-trip to the mode the player actually built under | Stale static state / wrong round-trip: because `cc_uistate` is static, a stale `pool` could be serialized; mitigated by the state-lifecycle decision below and a template round-trip test |
| On template load, the template's stored `"limit"` wins over the world `CHARACTER_POINT_POOLS` option (the template-defined pool is authoritative) | Fixed world option wins; reject the template; prompt the player to choose | A template already encodes the pool the character was built under, so honoring it preserves backward compatibility with existing saved templates, including `TRANSFER` | Backward-compatibility: a `"limit"` that conflicts with a fixed `multi_pool`/`story_teller` world still loads as stored; acceptable because a template is an explicit prior choice, with invalid values handled by the decision below |
| Implement per-selection cost/earn feedback on the stats and traits tabs, not merely an aggregate points context | Show only the aggregate points context on stats/traits and omit per-adjustment cost text | AAP §0.5.4 requires per-selection cost/affordability feedback across scenario/profession/background/stats/traits/skills, so stats and traits must show the point delta of each adjustment | Incomplete affordability feedback: omitting per-adjustment deltas would leave stats/traits inconsistent with the other tabs; tracked here so the later creator diff implements it on both tabs |
| Explicitly initialize/reset `cc_uistate.pool` on every entry into the creator and on each generation path (CUSTOM/RANDOM/NOW/FULL_RANDOM/TEMPLATE) | Rely on the static instance retaining its value between invocations | `cc_uistate` is a file-scope `static`, so its fields survive across creator sessions; seeding `pool` per entry prevents a prior character's mode from leaking into a new one | Cross-session leakage: an unreset static `pool` could silently apply the previous run's mode; mitigated by seeding it from the option (or template) at the start of `avatar::create()` |
| Normalize an out-of-range integer `"limit"` read from a template to a safe default (`FREEFORM`) rather than trusting an unchecked cast | Keep the raw `static_cast<pool_type>`; hard-reject and refuse to load the template | The current load path casts the integer directly, so a corrupt or future `"limit"` would yield an invalid enum value; clamping to a known mode keeps such templates loadable and safe | Corrupt-template / invalid-enum: normalizing hides the malformed value, but the alternative (an undefined enum) is worse, and valid legacy values 0/1/2/3 are unaffected |
| Apply the `ONE_POOL`/`MULTI_POOL` over-allocation guard on every path that can set `finished_character_creator`, not on a single button | Guard only the primary confirm action | Two sites set `finished_character_creator = true` (both under `NEXT_TAB` at the Summary tab, in the named- and unnamed-character branches), so a single-site guard could be bypassed by the other | Bypass: an unguarded completion path would let an over-allocated character finalize; mitigated by centralizing the check so both branches share it |
| When `CHARACTER_POINT_POOLS` fixes the mode (`multi_pool` or `story_teller`), present the `CHARCREATOR_POINTS` tab as informational with selection disabled rather than hiding it | Hide the tab entirely for fixed worlds; always allow free selection regardless of the option | A visible but read-only tab preserves a consistent tab layout and still shows the active mode while honoring the world's fixed choice | UI consistency: a sometimes-present tab, or an editable control that silently ignores input, would confuse players; a visible disabled control communicates the fixed mode clearly |
| Render the points-remaining balance in an always-visible location independent of the collapsible "General Info" header (outside the `CollapsingHeader` body or in the persistent header), not inside `draw_top_bar()` alone | Add the balance only to `draw_top_bar()`, as the seeded persistent-readout row above plans | `draw_top_bar()` is invoked only while the "General Info" `CollapsingHeader` is expanded (`src/newcharacter.cpp` L2744-2751), so a balance placed there disappears when the header is collapsed, violating AAP §0.5.4's always-visible requirement | Requirement loss: without this the balance is hidden whenever the header is collapsed; mitigated by drawing it outside the collapsible body so it persists across tabs and collapse states |

## Section B — Bidirectional Traceability Matrix

| # | Removed construct (from `e8b832bd1d` / `f2c5d14dde`) | Original location | Restoration target | Target file : locator |
|---|---|---|---|---|
| 1 | `pool_type::ONE_POOL` | player_difficulty.h | Re-add enumerator `ONE_POOL` (=1) | `src/player_difficulty.h` : `enum class pool_type` |
| 2 | `pool_type::MULTI_POOL` | player_difficulty.h | Re-add enumerator `MULTI_POOL` (=2) | `src/player_difficulty.h` : `enum class pool_type` |
| 3 | `CHARACTER_POINT_POOLS` option | options.cpp | Re-register world-default option | `src/options.cpp` : `add_options_world_default()` |
| 4 | `skill_points_left(avatar, pool_type)` | newcharacter.cpp | Restore pool-aware points-left helper | `src/newcharacter.cpp` (helper) |
| 5 | `pools_to_string` MULTI_POOL/ONE_POOL branches | newcharacter.cpp | Restore points-summary string helper | `src/newcharacter.cpp` (helper) |
| 6 | `set_points()` "POINTS" tab function | newcharacter.cpp | Pool-selection tab draw (ImGui) | `src/newcharacter.cpp` + `CHARCREATOR_POINTS` |
| 7 | "POINTS" entry in `character_tabs` | newcharacter.cpp (`avatar::create`) | `CHARCREATOR_POINTS` tab + count 7→8 | `src/character_creator_ui.h` : enum + `CHARACTER_CREATOR_TAB_COUNT` |
| 8 | `CHARACTER_POINT_POOLS` read + `pool=MULTI_POOL` | newcharacter.cpp (`avatar::create`) | Restore option read + pool seed | `src/newcharacter.cpp` (~L763) |
| 9 | `draw_points` `netPointCost` param + (±N) display | newcharacter.cpp | Points display in top bar + per-tab | `src/newcharacter.cpp` (~L2801 + per-tab draws) |
| 10 | `skill_increment_cost()` | newcharacter.cpp | Restore helper | `src/newcharacter.cpp` (helper) |
| 11 | `set_profession` "Profession X costs/earns N" | newcharacter.cpp | Cost text in profession draw | `src/newcharacter.cpp` (~L2930) |
| 12 | `set_hobbies` "Background X costs/earns N" | newcharacter.cpp | Cost text in background draw | `src/newcharacter.cpp` (~L2961) |
| 13 | `set_scenario` "Scenario costs/earns N" | newcharacter.cpp | Cost text in scenario draw | `src/newcharacter.cpp` (~L2909) |
| 14 | `set_skills` "Upgrading X by Y costs N" hint | newcharacter.cpp | Upgrade-cost hint in skills draw | `src/newcharacter.cpp` (~L3026) |
| 15 | `set_stats`/`set_traits` `pools_to_string` usage | newcharacter.cpp | Points context in stats/traits draws | `src/newcharacter.cpp` (~L2995 / L3005) |
| 16 | `set_description` `ONE_POOL` over-allocation popup | newcharacter.cpp | Finalize guard (ONE_POOL) | `src/newcharacter.cpp` (~L3419-3430) |
| 17 | `set_description` `MULTI_POOL` stat/trait/skill popups | newcharacter.cpp | Finalize guard (MULTI_POOL) | `src/newcharacter.cpp` (~L3419-3430) |
| 18 | "points pool" New Game hint | main_menu.cpp | Restore hint phrase | `src/main_menu.cpp` (L486) |
