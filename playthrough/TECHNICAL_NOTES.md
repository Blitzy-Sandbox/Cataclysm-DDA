# Technical notes

The engineering record for the playthrough capture. Everything that is a
decision about the machinery, a measurement taken from this checkout, or an
observation about how the pipeline behaves belongs here — and nowhere else.

> ## READ THIS FIRST: the session in this tree is no longer the one most of
> ## this page describes
>
> **The record was re-recorded from the first keystroke.** The artifacts in
> this tree are a **326-frame** session played by **Ambrose Halloran**. The
> **419-frame** session played by **Delphine Ouellette**, which the great
> majority of this page measures in detail, **no longer exists in the tree**:
> its frames, manifest, telemetry, digest ledger, date audit, timeline,
> transcripts, films, amendment ledger, dossier and userdir were all replaced.
>
> It was not replaced for tidiness. A code review established that the
> shipped session **could not satisfy R11**: Delphine died, and after death
> the engine makes `ACTION_SAVE` unreachable, so the in-game Save & Quit that
> R11 requires had never happened — while five appended frames of post-death
> menu navigation and the surrounding prose implied that it had. That is not
> repairable by editing a record (and editing a captured record is forbidden
> here for its own reasons). It is only repairable by playing again.
>
> **The new session's outcome, stated plainly at the top so nothing downstream
> has to carry it:** Ambrose Halloran was created through the custom
> point-buy creator on the *Missed* scenario, woke in a garage at 08:00:00 on
> Thursday, May 20, and **died at 08:02:40** — cornered in a bathroom by a
> tough zombie that opened the door he had shut behind him. R11 admits two
> endings, "realistic sleep **or** death", and the plan states that "death by
> legitimate play is an acceptable, honest ending"; this is that ending. The
> **sleep-and-wake-and-Save-&-Quit branch the review asked for was attempted
> and was not reached**, and the in-game Save & Quit remains unreachable for
> the same engine reason as before. Nothing in the record, the transcripts or
> the films claims otherwise, and no post-death menu navigation was appended
> this time. The full account is in **"The re-recorded session: Ambrose
> Halloran"** below.
>
> Everything on this page that measures 419 frames, 233.000 s, Delphine
> Ouellette, the golf course, the restaurant spawn or the 27-entry amendment
> ledger is therefore **historical**. It was true of the artifacts it was
> written about; those artifacts are gone. It is kept rather than deleted
> because the reasoning in it — the timeline algorithm, the trust gates, the
> capture invariants, the CI contract, the environment — is what produced the
> new session too, and because a page that quietly erased its own history
> would be the wrong kind of document.

`playthrough/dossier.md` is the survivor's own account of himself, written
before the first keystroke, and it is his entirely: no point accounting, no
option values, no source citations, no notes about how any of it was
arranged. He would not write a page like that and does not think about
himself in those terms. Keeping the two apart is what makes the in-character
record worth reading as a record rather than as a commentary, so the
mechanical half of the character lives on this page instead.

Every value below was read out of this checkout at the stated location. Where
a number is quoted, it is the shipped value in this tree and not a value
remembered from another version.

`playthrough/README.md` would be the user-facing counterpart to this page —
artifact inventory, how to re-run, the environment contract. It does not
exist in this tree; see "Three artifacts the plan names that do not exist
here" below, which records that as an outstanding gap rather than leaving it
to be discovered.

**How this page is arranged.** It grew in the order the work happened, which
is the right order for a log and the wrong one for looking something up, so:

* **The pre-play character build** and **Session log** are the record of the
  session as it was played, written while it was being played.
* **Post-capture verification**, **The session was re-recorded**, **The
  commit identity**, **The two checkpoints** and **Runtime QA remediation**
  are the successive review passes, each one dated and each one saying which
  capture set it measured. Later sections supersede earlier counts and say
  so explicitly; nothing earlier is edited away.
* **The pipeline as built** — the last part of this page — is the
  subject-ordered reference: the build, the headless contract, the seeded
  options, the tileset, the save layout, the render path, the lint and CI
  gates, the blast radius, and the meta observations that had no other home.
  Every measurement in it was re-taken on the host that produced this file,
  and each one says whether it confirms, supersedes or contradicts the plan.

## Read this before any count on this page

**Three sessions were recorded. Only the third shipped, and most of this page
was written about the first two.** A reader who starts at the top meets the
retired numbers first and the disclaimers last, so the map belongs here.

`playthrough/frames/` holds **419 frames** — one per keystroke of the session
that shipped — with 419 manifest rows and 419 telemetry rows. **Any count on
this page that is not 419 is describing a retired set.**

| Block | Describes | Status |
| --- | --- | --- |
| *The pre-play character build* | the survivor herself | current — she is the same person in all three |
| *Session log — engineering observations…* and *Post-capture verification of `playthrough/frames/`* | the **first, 560-frame session** | **RETIRED.** Rejected at code review. Every "560" belongs here, as does the frame-by-frame narrative of the abandoned first creation run at *The interrupted capture at frame 177*, whose `real_ts` and luminance figures do not match the frame 177 in the tree today |
| *The session was re-recorded…* | the **second, 395-frame session** | **RETIRED.** Its own heading says it "supersedes every count above", which was true when written — but it was itself superseded by the 419-frame record. Every "out of 395" in it belongs to that dead set |
| *The commit identity…*, *The two checkpoints…* | requirements and design, set-independent | current |
| *Frame 397 correction after the death ending*, *AAP R11: the ending is legitimate…*, *Runtime QA remediation of the 419-frame record* | the **shipped 419-frame record** | **CURRENT** |
| *Runtime QA remediation of the earlier 395-frame capture set* | the second, 395-frame session again | **RETIRED**, kept because the engine behaviours it pins down and the tooling it produced are still in force |
| *The pipeline as built* and everything after it | the pipeline, the host and the engine | current except where it names a retired count |

**One difference between the sets matters more than any count, because an
earlier version of this map obscured it.** The first two sessions ended in
**sleep, waking and an in-game Save & Quit**; the shipped third session ended in
**legitimate death**, which the engine makes incompatible with Save & Quit. Both
retired blocks describe a Save & Quit that is *not* part of the shipped record —
the 560-frame block at "the in-game Save & Quit at frames 558-560" and the
395-frame block's artifact table at "written by the in-game Save & Quit path".
Neither is a statement about what shipped. The shipped ending, and the R11
element it leaves unmet, are in *AAP R11: the ending is legitimate, and the Save
& Quit element is UNMET*.

**Where the 419-frame record is actually documented**, since an earlier version
of this pointer sent readers to two sections that describe retired sets
(*Post-capture verification of `playthrough/frames/`* measures the 560-frame
set, and the block opening at *The session was re-recorded* measures the
395-frame one):

* **[Frame 397 correction after the death
  ending](#frame-397-correction-after-the-death-ending)** — the one row-level
  correction the shipped set needed.
* **[Runtime QA remediation of the 419-frame
  record](#runtime-qa-remediation-of-the-419-frame-record)** — the pass that
  drove the shipped chain end to end, with the two defects it found and how
  each was verified.
* **[The pipeline as built](#the-pipeline-as-built)** — the subject-ordered
  current reference: build, environment, options, tileset, save layout,
  render, lint and CI. Its
  [Corrections that supersede earlier sections of this
  page](#corrections-that-supersede-earlier-sections-of-this-page) table is
  the single place every superseded figure is reconciled against a current
  measurement, and it is the right place to start if a number anywhere above
  looks wrong.

**And one more thing to read before any digest on this page.** Two passes
described below originally corrected the record by editing it — eight `action`
markers and nineteen `commentary` sentences, written into `manifest.jsonl` (and
eight into `build/observations.jsonl`) after the session had recorded them. A
Boundary-3 security review rejected that as CWE-345, and correctly: once
captured evidence can be rewritten, every artifact derived from it is deniable.
Both files have therefore been **restored byte for byte** to the state the
session wrote them in, the two functions that could rewrite them have been
deleted from `manifest.py` and `session.py`, and the corrections now live in
**`playthrough/amendments.jsonl`** — 27 append-only amendments, each bound to the
sha256 of the manifest line it concerns and each stating its basis and its
reason. `manifest.resolve_rows()` applies them to a derivative and to nothing
else, and refuses rather than skips when a digest no longer matches. The
mechanism, the schema and the fail-closed rules are at *Three rows narrated an
effect their own capture contradicts*; the artifact digests that resulted are at
*The derivative chain, regenerated on a supported platform*. Any digest quoted
elsewhere on this page for `manifest.jsonl`, `build/observations.jsonl`,
`timeline.json`, either transcript or either MP4 predates that restoration.

---

## The re-recorded session: Ambrose Halloran

Everything in this section was measured from the artifacts now in the tree. It
supersedes every count on this page taken from the 419-frame session.

### What shipped

| Artifact | Value |
| --- | --- |
| captures | **326**, indices contiguous 1..326, every one 1920×1080 |
| manifest rows | **326**, the six prescribed fields on every row, every `action` and `commentary` non-empty; `manifest.py verify` → `manifest ok: 326 row(s)` |
| capture telemetry rows | **326**; `session.py status` → `RECORD_PROBLEMS=0` |
| frame digest attestations | **326** |
| `timeline.json` | 326 entries, every duration within \[0.25, 10.0\], **1** `transition_after` flag, **117** clock readings reconciled rather than read, **218.500 s + 1.000 s = 219.500 s**; `timeline.py --verify` recomputes it from the manifest identically |
| transition frames | 1 group × 12 = **12** PNGs under `playthrough/build/transitions/`, never in `playthrough/frames/` |
| concat list | **338** entries (326 captures + 12 transition frames, with the final entry repeated) |
| `cata-play.mp4` | 3 749 146 bytes, `h264` 1920×1080, 339 read frames, container **219.560 s** against a computed 219.500 s (+0.060 s encoder rounding) |
| `cata-play-cc.mp4` | 3 774 538 bytes; video stream copied intact (proved by stream hash), subtitle stream index 1, `mov_text`, `TAG:language=eng`, `SUBTITLE_DURATION=219.500000`, **326 cues in, 326 cues round-tripped**, zero audio streams |
| `transcript.srt` / `transcript.md` | 326 cues and 326 stamps, last cue closing at `00:03:39,500` = the timeline's own 219.500 s |
| non-blank | sampled frames 1 / 119 / 200 / 326 measure mean 0.00524 / 0.0990 / 0.1088 / 0.0224 with stddev 0.0645 / 0.1574 / 0.1767 / 0.1250, and a frame pulled back **out of the captioned film** at t=120 s measures mean 0.1037 stddev 0.1759 — every one `mean > 0` **and** `stddev > 0` |

The **117 reconciled clocks** are frames 1–118, the character creation: there
is no survivor and therefore no sidebar clock to read, so the timeline carries
each of them flagged with its reason rather than inventing a reading. The
first frame with a real clock is **119**, at `08:00:00`, `Thursday, May 20`.

### The character, and why the point pool matters

The creator was driven through **`Custom Character`** — never `Preset
Character`, `Random Character`, `Play Now!  (Default Scenario)` or `Play
Now!`. On the `POINTS` tab, `Survivor (current)` was declined in favour of
**`Legacy: Multiple pools`**, which is the only mode of the three that
enforces a budget: it reported `Points left: 6+0+2=8`. Choosing the
constrained mode over the freeform default is what makes "point-buy" a fact
about this session rather than a word.

| Choice | Cost | Why |
| --- | --- | --- |
| scenario **Missed** | 0 | The hard rule for a new character. Start of cataclysm Y1 May 15 00:00:00, **start of game Y1 May 20 08:00:00**, location "In Town", flag "No starting NPC" |
| profession **Mail Carrier** | 0 | Thirty-four years on three routes — and its kit includes a **worn wrist watch**, which is what makes R4's exact second-resolution clock possible. The watch was acquired the way the plan says it must be: as a characterful, legitimate choice, not a code change |
| Strength 7, Dexterity 7 | refund 2 | Sixty-one, wiry, stiff-fingered |
| Intelligence 10, Perception 12 | spend 6 | His trade was noticing |
| +Accomplished Sleeper, +Good Hearing, +Light Step | spend 3 | Each one earned on a postal route |
| −Bad Knees, −Far-Sighted | refund 3 | Real mechanical costs. Far-Sighted blocks reading and penalises melee and fine crafting, and it guaranteed the reading glasses he is wearing |
| athletics 2, health care 2 | spend 2 | The walking, and the first-aid course the post office paid for |

The trait pool closed at **exactly zero** — every boon paid for by a flaw —
and **2 stat points were deliberately left unspent**. That last choice is on
the record in the engine's own words: finishing raised *"Remaining points will
be discarded, are you sure you want to proceed?"*, and it was answered yes.
"Deliberate and characterful rather than min-maxed" is therefore a property of
the frames, not a claim about intent.

### How it ended, and what that does and does not satisfy

He woke in a garage, took a PAPR welding helmet off the bench, heard glass
break, retreated west into a small windowless utility room and **shut the door
behind him**, and settled to wait out the day. Glass crunching indoors
interrupted the wait. A **tough zombie opened the door he had shut** and stood
in the only doorway of the 1×2 bathroom he had backed into.

What followed is the whole of the ending, and every step of it is in the
frames: fists did *no damage*; the welding hood would not fit over his mail
carrier hat; wielded as a club it also did *no damage*, until one critical for
**2**; it grabbed his right leg and he **broke the grab** after some twenty
attempts; he tried to smash out through the wall; his stamina gave out, so he
could neither dodge nor block; six limbs broke; he died at **08:02:40**. The
engine's own epitaph: *"In memory of: Ambrose Halloran. Survived: 2 mins 48
secs. Kills: 0."* He filed last words — **"On my way."** — and declined the
offer to watch the replay. **The record ends there, at frame 326.**

- **R11 is satisfied by its death branch.** The requirement is "realistic
  sleep **or** death", and the plan states that death by legitimate play is an
  acceptable, honest ending. No debug menu, no spawning, no healing, no stat
  edit, no teleport: the fight was lost on its merits, and the committed
  `keybindings.json` carries no binding for `debug`, `debug_mode` or
  `debug_hour_timer` for a stranger to check.
- **The sleep branch was attempted and not reached.** He chose a windowless
  room with one door and tried to wait the day out; the interruption came
  about one in-game minute later. The review's remediation asked specifically
  for sleep → wake → in-game Save & Quit. That did not happen, the in-game
  Save & Quit is unreachable after death for the engine reason the review
  itself identified, and **no artifact says otherwise**.
- **The defect the review actually raised is fixed.** Its complaint was that
  the old record *appended five frames of post-death menu navigation* and that
  the surrounding claims implied a compliant ending. This time, after the
  death rite the engine was **stopped by signal rather than driven back
  through its menus**, precisely so that no post-death menu frame and no
  dead-man commentary could enter the record.

Independent corroboration, all of it committed: the character's own memorial
log at `playthrough/userdir/save/Apshawa/#QW1icm9zZSBIYWxsb3Jhbg==.log`
(base64 decodes to `Ambrose Halloran`) reads *"Ambrose Halloran began their
journey into the Cataclysm"*, then *"Lost the conduct Nudist"*, *"Lost the
conduct Nonviolence"*, *"Lost the conduct Mouse in a china shop"* — the second
is the moment he first struck the zombie, the third the moment he first struck
the wall — and *"Received a deep bite wound"* twice. There is also an
achievements file under the same name.

### Three blemishes in this record, disclosed rather than buffed out

An append-only record cannot be tidied afterwards, which is the point of it
being append-only. So:

1. **Rows 78–84 record keystrokes that had no effect.** On the `SKILLS` tab a
   skill is bought with `+`, not `Return` — the same convention as `STATS` —
   and seven keys were spent discovering that. They are real keys, really
   sent, each with its own captured frame; row 85's note says *"put my walking
   down properly this time"*, which is exactly what happened.
2. **Rows 78 and 85 share one commentary sentence.** A consequence of the
   same fumble. Nothing false, but it reads as a repetition in the transcript
   and on the captions, and it would not have been written that way twice on
   purpose.
3. **The dead character's save was never archived to `graveyard/`.** Stopping
   the engine by signal is what kept post-death menu frames out of the record,
   and the cost is that the engine never ran its own post-death housekeeping.
   So `playthrough/userdir/save/Apshawa/` still holds a live-shaped character
   save for a survivor who is dead, and `session.py probe` will report
   `SESSION_MODE=resume` for him. Anyone resuming this world should know they
   would be resuming a corpse's save file; the memorial log above is the
   authority on what happened to him.

### One rendering artifact worth naming

Several terrain tiles in the captured frames render as **flat magenta**. That
is the MSXotto+ pack's missing-sprite fallback, not a capture fault and not
damage: the tileset has no sprite for those particular terrain ids, so the
loader substitutes a placeholder. It is visible in the film, it is honest
output of the configured tileset, and it is left as it is — the alternative
would be changing the artwork the plan fixes as `MSXotto+`.


## The pre-play character build

Set down in advance, because the exact shape of the character is a thing
that has to be decided and written down BEFORE the first day is played
rather than described afterwards from memory. Every value is traceable to
this checkout, and every choice is traceable to a sentence Delphine already
wrote in the dossier — quoted here so the link between the human account and
the mechanical one can be checked in both directions.

**Creation path.** The custom creator — the entry labelled `Custom Character`
[src/main_menu.cpp:476], whose own hint is "Allows you to fully customize
points pool, scenario, and character's profession, stats, traits, skills and
other parameters" [src/main_menu.cpp:486]. Not `Preset Character`
[src/main_menu.cpp:477], not `Random Character` [src/main_menu.cpp:478], and
neither "Play Now!" entry [src/main_menu.cpp:481-482]. The points are spent in
**multi pool**, which the world setting `CHARACTER_POINT_POOLS = any` keeps
selectable [src/newcharacter.cpp:438-446]; under the shipped `story_teller`
value the pool tab is informational and read-only and there is no point-buy at
all [src/newcharacter.cpp:462-467].

**Scenario.** *Missed* — id `missed`, **0 points**, "you missed the evacuation
and are stuck in a city full of the risen dead"
[data/json/scenarios.json:55-61]. She missed it out of stubbornness and live
boilers, which is the account under "How I missed the buses". It costs nothing,
so it is not a trade-off she has to pay for.

**Profession.** *Mechanical Engineer* — id `engineer_mech`, **2 points**,
granting **mechanics 5** and the proficiencies `prof_basic_engines`,
`prof_high_pressure_systems` and `prof_pneumatics`
[data/json/professions.json:1086]. Twenty-two years on the steam side of a
paper mill is exactly that profession and exactly those three proficiencies.
Its kit is also what the dossier is describing when she inventories herself:
dress shirt, jeans, socks, steel-toed boots, a **wristwatch**, a charged
smartphone carrying a mechanics textbook, and a full wallet. She calls the
dress shirt a work shirt, because that is what a woman on shift calls the
shirt she works in; it is the same garment.

The wristwatch is not a flourish. `display::time_string()` returns an exact
`to_string_time_of_day()` reading only while the survivor `has_watch()`, and
otherwise a coarse phrase or `"???"` [src/display.cpp:207-219, :159-185], and
every frame's on-screen duration in the finished film IS the delta between two
consecutive sidebar clock readings. A survivor without a timepiece would
therefore produce a film with no derivable pacing at all. Acquiring one
legitimately was a creation decision, and the profession that fits her history
happens to carry one.

**Stats.** The pool is `4 * 8 + INITIAL_STAT_POINTS`, and the shipped value of
`INITIAL_STAT_POINTS` is 6, so 38 points
[src/newcharacter.cpp:250-253]. Each stat costs its own value plus one more for
every point above 12 [src/newcharacter.cpp:255-263; `HIGH_STAT` = 12,
src/player_difficulty.h:14]. The descriptors quoted below are the creator's own
words for those numbers [`stat_level_description`,
src/newcharacter.cpp:1573-1606]:

* **STR 10** — costs 10, reads "above average". "I am strong for a woman my
  age". She can still lift; Bad Back is what she cannot do with it.
* **DEX 7** — costs 7, reads "below average". "I have never been quick."
  Deliberately below the baseline of 8, which the creator calls "average
  human": this is the stat she pays with.
* **INT 12** — costs 12, reads "top 10%". "a head full of machines", and the
  reason she can name what is wrong with a machine "before the cover is off".
* **PER 9** — costs 9, reads "above average". "My eyes are still good enough to
  read a gauge from across a bay". Her hearing is bought separately, below.

Total 38 of 38, nothing left over and nothing borrowed.

**Traits.** The trait pool is the shipped value of `INITIAL_TRAIT_POINTS`,
which is 0 [src/newcharacter.cpp:266-267], so every advantage here is paid for
with a liability — the arrangement she states as "You buy the one with the
other." A positive value below is a cost; a negative value is a liability that
hands points back. All five are declared in data/json/mutations/mutations.json:

* **Good Hearing** (`GOODHEARING`, +1, line 420) — "hearing is better than
  average", a quarter again on the hearing multiplier. "My ears are the best
  thing I own", and in five days they have already been how she knows which
  rooms have something in them.
* **Fast Healer** (`FASTHEALER`, +2, line 554) — "wounds and broken limbs heal
  quicker than usual". "My hands are steady and they recover fast".
* **Bad Back** (`BADBACK`, −3, line 386) — "maximum weight carried is reduced
  by 35%". "I can still lift. I cannot carry." This is the one she says will
  "decide what I pick up and what I walk away from, all day, every day", and it
  is the single choice that will shape the play most.
* **Insomniac** (`INSOMNIA`, −2, line 1701) — "a hard time falling asleep, even
  under the best circumstances". "I do not sleep. Not properly". It is also
  what makes the end of the first day genuinely uncertain rather than a
  formality.
* **Slow Footed** (`SLOWRUNNER`, −3, line 281) — "a 15% speed penalty on flat
  ground". She is "slow for anybody's". With DEX 7 as well, running away is not
  a plan available to her.

That is 3 points of boon against 8 points of liability, a net −5, and in multi
pool a trait surplus is spendable on skills but never upward on stats
[src/newcharacter.cpp:325-343].

**Hobbies.** Charged against the skill pool on the same sign convention, all
five declared in data/json/hobbies.json:

* **Nicotine Dependence** (`smoker`, −1, line 80) — a nicotine addiction at
  intensity 10, and "nothing in my shirt pocket but the pocket". "One hour
  without and I am mean".
* **First Aid** (`redcross`, +1, line 1144) — firstaid 2. "The mill sent us to
  the first-aid refresher every spring and I paid attention every spring".
* **Fishing** (`fishing`, +1, line 1212) — survival 2, swimming 1, and the
  `OUTDOORSMAN` trait free with it (line 1815 of the mutations file: it eases
  the misery of being wet). Her father taught her "to fish the river in the
  spring when the water is still too cold to be pleasant about it."
* **Machinist (Beginner)** (`machinist_beginner`, +2, line 1203) —
  fabrication 3, mechanics 1. "the part you want is not in the crib, so you
  build one out of whatever is on the bench."
* **Driving License** (`driving_license`, 0, line 15) — driving 2, mechanics 1.
  "I would put on the boots, drive down through a dead town, and fix it".

**Levels bought outright.** The skill pool is the shipped value of
`INITIAL_SKILL_POINTS`, which is 2 [src/newcharacter.cpp:288-290]. In every
mode except the freeform one, the first increment on an untouched skill moves
it from 0 to **2** for a single point [src/newcharacter.cpp:3845-3862; cost
table at src/newcharacter.cpp:303], so both points go on the two things that
twenty-two years of swinging wrenches and pry bars at seized machinery would
actually have taught her: **melee 2** (1 point) and **bashing 2** (1 point).
It is also what she will be holding when the first thing comes at her, since
"when a plan runs out and the thing in front of me is fast, I am the wrong
person to be standing there."

**What she therefore starts with.** Profession levels are added on top of what
was bought [src/newcharacter.cpp:1105-1108] and hobby levels raise a skill only
where they exceed what is already there [src/newcharacter.cpp:1042-1053], so
the sheet reads: **mechanics 5, fabrication 3, bashing 2, driving 2,
firstaid 2, melee 2, survival 2, swimming 1**.

**The arithmetic, so it can be checked rather than taken on trust.** Pools:
38 stat + 0 trait + 2 skill = 40. Spent: 38 on stats, −5 on traits, and 7
against the skill pool (scenario 0 + profession 2 + hobbies 3 + bought
levels 2) = 40. Under multi-pool accounting — where a stat surplus can fund
traits, a stat-plus-trait surplus can fund skills, and nothing ever flows the
other way [src/newcharacter.cpp:325-343] — the three remainders come out at
exactly 0, 0 and 0. Nothing is left unspent and nothing is overdrawn.

**Distinctive rather than optimal, and deliberately not average.** Three
liabilities worth eight points against two boons worth three; one stat below
the average human and one in the top tenth. She is a specialist with a wrecked
back who cannot carry a load, cannot run, and cannot reliably sleep, and who in
exchange hears what is in the next room, mends fast, and understands every
machine she is likely to meet. That is neither a min-max nor a flat spread; it
is a forty-seven-year-old maintenance engineer with a body that has done
twenty-two years of the work, which is the person the dossier describes.

*If the creator's own display disagrees with any number on this page, the
creator is right and this page is wrong: correct it here before the day is
played, never reconcile it afterwards.*

---

## Session log — engineering observations from the recorded run

Everything below was observed during the captured session of 3 August 2026 on
this host (`CLONE_INDEX=2`, `DISPLAY=:101`). It is here rather than in
`playthrough/transcript.md` or `playthrough/manifest.jsonl` because none of it
is Delphine's, and because `playthrough/manifest.jsonl` is append-only: a row
that was recorded wrongly is corrected *here* and by a later row, never by
editing the record.

### Corrections to the record

* **`frame` 116 — the `action` text is wrong.** It reads
  `press 'X' -- nothing; see note` with the commentary `placeholder`. The key
  actually delivered was `-`, which lowered Perception from 9 back to 8. It was
  an operator slip: a scratch third step was left in the command that drove the
  two Perception keystrokes. Frame 117 restores Perception to 9 and says so in
  its own `action` field. Both rows stand exactly as written, because the
  manifest is evidence and evidence is not rewritten — the sequence
  116 → 117 is the honest account of a mistake and its repair.
* **`frame` 13 — `press '/' -- open the scenario filter`.** The filter box *did*
  open, but it is drawn at the bottom of the right-hand description pane
  (around `x` 828, `y` 529) rather than near the list, so it was missed on the
  first read. Frames 14 and 15–20 (`Page Down`, then six `Down` presses) were
  therefore delivered into that text box and moved nothing. The two states
  differ by 21 pixels — a 2 × 14 px blinking text cursor — which is what
  finally identified it.
* **`frame` 94 — the wrong trait was ticked.** The `healer` filter left the list
  cursor on row 2, *Imperceptive Healer* (−8), not row 1, *Fast Healer* (+2);
  the points line moved 7 → 15 instead of 7 → 5, which is how it was caught on
  the SUMMARY tab. Frame 98 unticks it, frame 100 moves up one row and frame 101
  takes *Fast Healer*, with the cursor confirmed from the pixels first. Lesson
  applied for the rest of the run: read the highlighted row before every
  `Return`, never assume a freshly filtered list is on row 1.

### Corrections to the pre-play character build

The page above says that if the creator's own display disagrees with any number
on it, the creator is right. Two things disagreed:

* **Six backgrounds arrive free with the profession.** Choosing *Mechanical
  Engineer* selected *Driving License*, *Simple Home Cooking*, *Computer
  Literate*, *Social Skills*, *High School Graduate* and *Mundane Survival*
  automatically, which is why the starting sheet carries applied science 1,
  computers 1, electronics 1, fabrication 1, food handling 1, health care 1,
  social 1 and vehicles 2 without anything being bought. *Driving License* was
  on the planned list and did not have to be taken separately.
* **The pools are displayed as points REMAINING, not as totals.** The header
  reads `Points left: <stat>+<trait>+<skill>`. It opened at `6+0+2=8` under
  *Legacy: Multiple pools* — the 4 × 8 stat baseline is already spent, so the 38
  quoted above is the same number counted from zero rather than from the
  baseline.

### Environment observations

* A fresh userdir opens on `Select your language`, not the main menu, exactly as
  planned for. On this host the prompt is a small dialog on an otherwise black
  1920 × 1080 root: only 4 635 non-black pixels, in a 176 × 60 box at
  `x` 871–1047, `y` 505–565. `LUMA_MEAN` 0.000555 with `LUMA_STDDEV` 0.0181
  still passes the non-blank gate, correctly — the frame is dark, not empty.
* That black screen with the engine at ~48 % CPU for four minutes looked like a
  hung tileset load and was not: the main thread's `wchan` was
  `hrtimer_nanosleep` with sixty-odd workers parked in `futex_wait`, which is an
  idle input loop waiting on the prompt.
* **The computed sidebar crop is `352x1072+1568+4`, not the 288-px rectangle the
  plan illustrated.** `panel_options.json` does not exist until the game saves
  its panel settings, so the live layout is the engine's own default
  `legacy_labels_sidebar` at 44 cells, not `custom_sidebar`'s 36: 44 × 8 = 352,
  right-aligned at 1920 − 352 = 1568. This is exactly why the rectangle is
  derived at run time instead of being written down.
* The 0.3 s settle can photograph a frame mid-redraw, before a `query_yn` popup
  has been drawn — which is how the first `f` at frame 4 appeared to do nothing.
  The captured session ran with `PLAYTHROUGH_CAPTURE_SETTLE=0.9`; capture.sh
  refuses anything *shorter* than the contracted 0.3 s and allows longer.
* `query_yn` on this build is case sensitive and says so: `y` at frame 7 was
  ignored and `Y` at frame 8 was accepted.
* There is no `FILTER` action anywhere in `src/newcharacter.cpp`, yet `/` opens a
  filter box on the creator's tabs. Re-opening it presents the previous text
  *selected*, and `BackSpace` does not clear it (six presses at frames 64–69
  changed nothing) — the first printable character typed replaces the whole
  selection, which is the way to reuse the box.
* `+` and `-` (`INCREASE_VALUE` / `DECREASE_VALUE`) adjust a stat or a skill;
  the arrow keys do not. `session.py` splits a chord on `+`, so the keystroke is
  spelled `plus` and `minus`.

### The interrupted capture at frame 177, and the abandoned first creation run

Frames 1–177 are a first pass at character creation that never reached a save.
Both facts below are recorded because the film and the record contain them, and
a viewer is owed the explanation rather than left to wonder why the creator gets
filled in twice.

* **The record was repaired, not rewritten.** The harness that drives this
  session terminates a command that produces no output for 300 s. Eighteen
  keystrokes of the name were driven through a single `tail`-buffered pipe, which
  emitted nothing for longer than that, so the command's whole process group was
  killed — mid-step, between capture.sh writing `frame_00177.png` and session.py
  appending its row. That left 177 PNGs against 176 rows: the exact break in the
  count identity session.py's own documentation anticipates, offering two
  remedies — withdraw the PNG, or repair the record.
  The record was repaired. `frame_00177.png` was verified independently against
  every gate capture.sh would have applied — PNG, 1920 × 1080, grayscale mean
  0.0154484 and standard deviation 0.0867151 (both > 0), clock unreadable — and
  its row was appended through `manifest.append_row()` so that the same
  validation, locking and durability applied as to every other row. Its
  `real_ts`, `2026-08-03T19:47:57.429Z`, is the PNG's own mtime: the instant
  `import` wrote the file, measured, not invented. The row's `action` says
  plainly that its capture was interrupted and that the row was repaired
  afterwards. `session.py status` then reported `RECORD_PROBLEMS=0`.
* **The same kill took the engine and the X server with it.** Both had been
  started detached from an ordinary shell, so the process-group kill reached
  them. No character had been saved — CDDA writes one only at the end of
  creation — so the creator state was lost with them, and creation had to be
  driven again from the main menu. The first pass stands in the record exactly as
  it happened; frames from 178 on are the second pass.
* **The fix, applied before redoing the work.** The instance is now owned by
  supervisord rather than by a shell: `/etc/supervisor/conf.d/playthrough-clone2.conf`
  runs `/usr/local/bin/playthrough-guard-2.sh`, which is
  `launch_game.sh guard` with `CLONE_INDEX=2`, holding the game in the
  foreground of a supervised process. `autorestart` is deliberately `false`,
  because the session is meant to end with the game's own Save & Quit and a
  restart after that would raise a second instance behind the recorded
  session's back. Driver output is now written to a log and read back rather
  than piped through `tail`, so no command can go silent long enough to be
  killed again.
* **And the repair no longer has to be done by hand.** A process-group kill
  mid-step was survivable only because a human went and looked; the step is now
  a transaction, so it is survivable by construction. `session.py` writes
  `playthrough/build/session_step.json` before it presses anything — the index,
  the key, the action and the commentary — adds capture.sh's own report of the
  frame once the PNG is on disk, and removes the file when the row is stored. A
  journal on disk therefore means a step in flight and nothing else, and the
  next process resolves it without being asked: it appends the row for a frame
  already captured (from the journalled report, so `real_ts` and the clock
  reading are the capturer's own and not re-derived), or photographs the SAME
  index again without sending a second keystroke when the capture is the part
  that was lost, or rolls the step back if the key was never reported delivered
  — reporting, in that last case, that whether the engine saw the keystroke
  cannot be established, rather than writing a row that claims it did. A
  capture that cannot honestly be part of the record is moved to
  `$PLAYTHROUGH_REJECT_DIR`, outside the working tree, exactly as capture.sh
  withdraws its own. Frame 177's row stands as it was repaired: the history is
  not rewritten, and its `action` still says what happened to it.

### The keystroke with no frame, at the start of play

The `Y` that confirmed the finished character sheet has no frame and no manifest
row. capture.sh measured the screen it produced at grayscale mean 0 and standard
deviation 0 — genuinely, entirely black, because the engine was generating the
world — and the non-blank gate did exactly what it exists for: refused to add a
black frame to the record, withdrew the PNG to the reject directory outside the
working tree, and stopped the session, since a keystroke cannot be un-pressed
and a frame cannot be invented for it. Fifteen seconds later the same screen
measured mean 0.0910 with standard deviation 0.1480 and play resumed from the
next keystroke. The gap is left as a gap: recording a black frame, or
back-filling one from a later capture, would both be worse than being one frame
short and saying so.

The step journal described above now closes that gap without back-filling
anything. A blank-frame refusal leaves the journal at `delivered` with no image
published, so the next `session.py step` photographs THAT index — the screen as
it stands, once the world has finished generating — before it presses anything,
and sends no second keystroke for the `Y` that was already delivered. The frame
would still be a real photograph taken after the fact rather than a
reconstruction, which is the only kind of retake this pipeline permits.

### The sidebar clock could not be read at all, and how it was fixed

This is the defect that would have silently cost the film its entire pacing
model, because an unreadable clock is an *ordinary* answer — every frame would
have carried `"ingame_clock": null`, every gate would have passed, and
timeline.py would have had no deltas to work from.

**Two causes, both measured from the pixels rather than guessed at.**

* **The row grid was out of phase by 14 pixels.** sidebar_geometry.py places the
  crop from the window's letterbox and produced `352x1072+1568+4`, but the engine
  anchors its 8 × 16 character grid to the window, which openbox had sized to the
  whole 1920 × 1080 root. The measured ink bands are 258–267 (`Date`), 274–286
  (`Time`) and 290–299 (`Wind`), so cell tops are at 256, 272 and 288 — a grid
  anchored at y = 0. Slicing 16-pixel bands from y = 4 cuts every glyph across
  two bands, and reading nothing is the result.
* **`data/font/Terminus.ttf` draws a slashed zero.** Aligned to the true row, the
  prescribed chain reads `Time: 08:80:88`: the zeros come back as eights. Nine
  preprocessing variants were tried and measured — 200/300/400/500/800 %
  upscaling, `-normalize`, `-threshold 40%`, `-negate`, `-gaussian-blur` at
  0x0.5, 0x1.0, 0x1.5 and 0x3, `-morphology Open 3x1` and `1x3`,
  `-morphology Erode Diamond:1`, `-morphology Close Disk:1.5`, and a digit
  whitelist. Every one returns `08:80:88`, `88:88:88`, `08:60:60` or nothing. No
  OCR preprocessing recovers a slashed zero here; the module's own
  `DESLASH_BLUR` of `0x0.5` was calibrated on a frame where it happened to
  survive.

**The fix is an exact reader, not a better guess.** The sidebar is not a
photograph of text — it is a character grid of 8 × 16 cells with no
anti-aliasing, because the engine's own `config/fonts.json` asks for `"Bitmap"`
hinting on a font that ships in this repository. Dumping the raw cells confirmed
crisp one-bit glyphs on an exact grid, and Pillow's
`ImageFont.truetype("data/font/Terminus.ttf", 16)` reproduces the engine's
slashed-zero bitmap pixel for pixel. So `ocr_clock.py` gained a `glyph-grid`
pass that compares each cell against the very font that drew it:

* the vertical phase is **measured**, not assumed — every candidate phase is
  scored by how many cells it makes *exactly* equal to a glyph of that font, and
  the best-scoring phase wins, which fixes the 14-pixel problem in general
  rather than by hard-coding an offset;
* an exact byte-for-byte match answers immediately; anything else resolves to the
  nearest template within four differing pixels, deliberately below the six that
  separate this face's `0` from its `8`; a cell nothing comes that close to
  becomes a space, never a guess;
* the decoded text is handed to the same `find_clocks()`, `extract_date()` and
  `extract_phrase()` the tesseract passes feed, so an impossible reading is still
  declined and nothing is repaired;
* the four OCR passes are untouched and still run behind it, and still under
  `--cross-check`.

Measured on a real captured frame: `clock=08:00:00`, `date=Thursday, May 20`,
`pass=glyph-grid`, `ocr_calls=0`, 0.425 s — against no reading at all in 19.25 s
before. The whole column decodes, not just the clock: `Str: 10`, `Dex: 7`,
`Int: 12`, `Per: 9`, `Place: golf course servic…`, `Weather: Clear`,
`Moon: New moon`, `Wield: fists` and the message log all read back exactly.
capture.sh now reports `CLOCK_STATUS=read` in 2.8 s per frame.

One test had to change with it. `test_ocr_clock.py` asserted that a slashed-zero
frame must read as `None`, on the reasoning that "the honest answer is no reading
at all". That was true of a tesseract-only reader and is not true of this one, so
the test now asserts the exact value, that `glyph-grid` is the winning pass, and
that the tesseract misreads still appear in `declined` with the "NOT repaired"
note intact — the original intent kept, the obsolete limitation dropped. Two
tests were added: that the exact pass spends zero OCR calls, and that a
deliberately mis-phased crop still reads the clock. 152 tests pass and
`flake8 playthrough/` reports nothing.

### Corrections to the record, during play

The gameplay run produced three more of these, all handled the same way: the
offending row stands, and the next row says so in Delphine's own voice.

* **`frame` 512 — the `action` text describes an intention, not what happened.**
  It reads `press 'k' -- close the door to the north, behind her`. `k` is
  *move* north. Walking into a closed door opens it and does **not** move you,
  so the press re-opened the door that frame 511 had just shut, and frame 512's
  commentary claims a closed door the picture does not show. The root cause is
  worth recording: `c` (`close`) **auto-selects when exactly one closable door
  is adjacent** — it does not prompt for a direction — so frame 511 had already
  finished the job and frame 512 was a direction press with nowhere to go.
* **`frame` 513 — the correction was itself imprecise.** It says she walked back
  into the doorway. She did not. Reading the log at frames 512 and 514 settles
  it: `You open the closed wood door.` followed by
  `There is nothing that can be closed nearby.` proves `k` never moved her, and
  that the subsequent `j` then carried her *two* tiles from the door, out of
  `c`'s reach. Frame 515 states this exactly and closes the door for good at
  516. Two corrections for one door is not a good look, and it is in the record
  because it happened.
* **`frame` 539 — a bench seat she had not reached.** The commentary reads
  `Onto the seat proper.` while the move cost was 0 and the clock did not
  advance: the golf cart's red bodywork occupies the tiles on its west face and
  is impassable, so both attempts to board from that side simply failed. She
  goes round the nose and in from the north at frames 540–541, and says so.
* **`frame` 553 — `S` was not accepted.** The sleep prompt offers
  `Y Yes. / S Yes, and save game before sleeping. / N No.`, and `shift+s` left
  it standing unchanged. That was verified rather than assumed, by checking the
  save files' mtimes: `#<b64>.sav` and `master.gsav` were last written at
  23:18:25, which belongs to the autosave during the preceding night-wait, not
  to this press. Frame 554 records the fact in its own `action` field and takes
  plain `Y`.

### Two advisory hits on the word "frame", and why the rows stand

`playthrough/manifest.jsonl` carries two commentary lines containing the word
*frame*: `Three. Standing in the doorway with one hand on the frame.` (509) and
`Through the frame.` (523). Both mean a door frame, the wooden thing in the
doorway she is standing in. Neither refers to a captured picture, to timing, or
to any part of the tooling.

The check for out-of-character wording is a fixed vocabulary match with no word
sense and no word boundaries, so it flags the ordinary English noun. Three
separate tools report it and all three call it advisory:
`manifest.py verify` prints `advisory only, nothing was altered` and still exits
`0` with `manifest ok: 560 row(s)`; `timeline.py` and `make_srt.py` each repeat
it and point here. That is the correct behaviour and the rows are **not**
edited, because the substantive rule — keep meta and "gamey" remarks out of the
in-character record — is satisfied, and because editing two rows to satisfy a
string match would be exactly the after-the-fact tidying that makes an
append-only record worthless. Scanned for the vocabulary that actually names the
apparatus (screenshot, capture, OCR, ffmpeg, MoviePy, manifest, timeline,
keystroke, xdotool, pipeline, tileset, sidebar, commit, option) the record
returns **zero** hits across all 560 rows.

### Input facts learned during play

* **Movement is vikeys.** `h j k l y u b n`. The arrow keys are ambiguous in
  `DEFAULTMODE` — `UP` is *eat*, `LEFT` is *wear*, `DOWN` is *drop* — so they
  were not used once play began.
* **Shifted punctuation must be sent as an explicit chord.** A bare `!` is
  delivered unshifted and arrives as `1`, i.e. `KEYPAD_1`, a south-west move.
  That is what happened at frame 406, where safe mode stayed on and the move was
  blocked; `shift+1` at frame 408 produced `Safe mode OFF!` immediately. The
  same applies to `@`, `$`, `^`, `|`, `C`, `I`, `S`, `W` and `Y`.
* **`.` must be spelled `period`.** `xdotool` rejects the bare character with
  `Invalid key sequence '.'`. That failure happens before anything is sent, so
  it costs no frame and leaves the session usable.
* **`e` (`examine`) reaches terrain and furniture only.** Items on an adjacent
  tile are taken with `g` (`pickup`), which prompts
  `Pick up items where? (Direction button or mouse)` and accepts diagonals. A
  *broken* vending machine has no examine action at all, which is why `e` kept
  answering `There is nothing that can be examined nearby` beside three of them.
* **The sidebar message log is oldest-first**, newest at the bottom. Confirmed at
  frame 544, where `The Golf Cart's engine starts up.` is the last line.

### The stalled sleep, and how its state was read without adding a frame

`$` (`shift+4`) at frame 552 started the sleep, but the activity then sat at
`19:54:29` for 168 s of real time without advancing. The cause was a standing
prompt the game was waiting on — `You start having withdrawals! Stop trying to
fall asleep?` — with a second one behind it, `You have trouble sleeping, keep
trying?`, which is the Insomniac trait.

Finding that out needed a look at the screen, and a screenshot with no keystroke
behind it would have broken the one invariant this record exists to prove. So the
state was read with `capture.sh` in diagnostic mode:

```bash
PLAYTHROUGH_CAPTURE_MODE=diagnostic FRAME_INDEX=99999 playthrough/tooling/capture.sh
```

which exits `9`, withdraws the image to
`$XDG_RUNTIME_DIR/playthrough/rejected/frame_99999.png`, and adds nothing to
`playthrough/frames/`. Two such polls were taken. `frames/` still holds exactly
560 files, one per keystroke, and `frame_99999.png` is not among them.

For the long waits the settle was raised instead — `PLAYTHROUGH_CAPTURE_SETTLE`
up to 120 s for a single step — so that the frame shows the *completed* wait
rather than a mid-simulation state. `capture.sh` only refuses settles shorter
than the contracted 0.3 s, so raising it is within the contract.

---

## Post-capture verification of `playthrough/frames/`

> **RETIRED — this block measures the first, 560-frame session, which did not
> ship.** Its ending description ("sleep, waking, then the in-game Save & Quit at
> frames 558-560") is a fact about *that* session. The shipped 419-frame record
> ended in legitimate **death** and captured no Save & Quit; see *AAP R11: the
> ending is legitimate, and the Save & Quit element is UNMET*. The measurement
> method below is still the one in force.

The 560 captures were re-verified after the fact, in a separate working clone
of this branch on the same host, and **nothing was re-captured, re-rendered,
resized, recompressed or renumbered** to make any gate pass. The session had
already ended legitimately — sleep, waking, then the in-game Save & Quit at
frames 558-560 — and a save exists, so re-running would have replaced real
evidence with a second, contradictory set rather than confirming the first.
What follows is measurement of the frames that are committed.

**The toolchain, as resolved here.** Read back with `command -v`, each tool's
own `--version`, and `dpkg-query -W`:

| Tool | apt version | Self-report |
| --- | --- | --- |
| imagemagick | 8:7.1.2.3+dfsg1-1ubuntu0.1 | ImageMagick 7.1.2-3 Q16 x86_64 |
| ffmpeg / ffprobe | 7:7.1.1-1ubuntu4.2 | ffmpeg version 7.1.1-1ubuntu4.2 |
| tesseract-ocr | 5.5.0-1 | tesseract 5.5.0 |
| xdotool | 1:3.20160805.1-5.1 | xdotool version 3.20160805.1 |
| xvfb | 2:21.1.18-1ubuntu1.1 | X.Org version 21.1.18 |
| x11-utils | 7.7+7 | `xdpyinfo`, `xwininfo` |
| openbox | 3.6.1-12ubuntu2 | Openbox 3.6.1 |
| scrot | 1.12.1-1 | scrot version 1.12.1 |

Two version facts are worth stating because guidance written elsewhere
assumes otherwise. **ImageMagick here is the 7.x branch, not 6.x**, and it
carries the legacy `import`, `convert` and `identify` entry points *as well
as* `magick`; the pipeline calls the legacy three, which is the spelling that
works on both branches, so nothing had to change. And the interpreters are
two: the system `python3` is 3.13.7 and PEP 668 externally-managed, while the
pipeline's own is `/opt/playthrough-venv/bin/python`, **CPython 3.12.13**,
which is what `requirements.txt` contracts for and what `env.sh` resolves.

**The platform is out of support, and the tooling now REFUSES rather than
warns.** This is Ubuntu 25.10, which reached end of life on 2026-07-09, and
ImageMagick, ffmpeg and the Xorg/Xvfb stack all parse untrusted-shaped input in
this pipeline, so on an unmaintained archive their known issues stay unfixed by
definition however current `dpkg-query` looks.

`env.sh`'s `playthrough_check_platform` used to print a warning, with the hard
failure opt-in via `PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1`. That was the
wrong way round, and it has been inverted: **an out-of-support release is a
refusal by default**, and so is a release the dated support table does not know
at all, because "cannot tell" is not "supported". `capture.sh` and
`launch_game.sh` both exit on it.

**The migration target is Ubuntu 26.04 LTS** (supported to 2031-04, and in the
table). Ubuntu 24.04 LTS (2029-04), Debian 13 (2030-06) and Debian 12
(2028-06) also pass *the table*. Moving the capture and render workload to a
release that passes removes the waiver condition entirely; nothing in the pipeline
depends on 25.10.

One qualification, measured later and recorded in full under *"The supported
release is now DECLARED"* below: passing the dated table is **necessary but not
sufficient for capture**. A capture host also needs an **SDL2 runtime of at least
2.32**, because the engine's ImGui screens — the character creator among them —
accept no keyboard input under 24.04's SDL 2.30.0. 26.04 ships 2.32.10 and drives
them correctly, which is why it is the declared base rather than merely the
furthest-dated option.

**Why this session ran under a waiver, stated plainly.** The container this
work was performed in *is* Ubuntu 25.10 and cannot be replaced from inside it,
so the recorded session was captured with

```
export PLAYTHROUGH_ALLOW_EOL_PLATFORM="container image is Ubuntu 25.10; \
no supported release available to this run"
```

The waiver takes a **reason**, not a `1`, deliberately: the reason is the only
part a later reader of the evidence needs, and a variable that has to be given
a sentence cannot be set by reflex. It is warned once at run time, exported as
`PLAYTHROUGH_PLATFORM_WAIVER`, and printed in the environment summary — which
is the record of what a session ran under — so the film's own contract says it
was recorded on an end-of-life host and why. `PLAYTHROUGH_PLATFORM_SUPPORTED`
reads `no` and `PLAYTHROUGH_PLATFORM_EOL` reads `2026-07-09` in that same
block.

**It IS a trust bypass, and it used not to be.** The argument for leaving it
out of `PLAYTHROUGH_TRUST_BYPASS_VARS` was that a variable in that registry
means *a check that establishes the evidence was relaxed, so a reading might be
wrong* — `PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X`, for instance, means another
local account could have injected keystrokes, which falsifies the record
directly — whereas an end-of-life platform makes no individual reading wrong: it
raises the risk that a parser has an unfixed defect, which needs hostile input
to matter, and the only images this pipeline decodes are the PNGs it captured
itself on a host that opens no network connection.

**Code review rejected that, and it was right to.** The registry's meaning is
the one its consumers give it: a condition under which this pipeline will not
produce *evidence*. A film recorded through unmaintained ImageMagick, ffmpeg and
Xorg packages is exactly that, whatever the residual likelihood — and the
reasoning that kept it out was self-serving in a way worth naming, because it
was the one condition that would have refused the run on the only host
available. `PLAYTHROUGH_ALLOW_EOL_PLATFORM` is now the seventh member of the
registry, with its own `playthrough_trust_reason`, and the consequence is stated
rather than hidden:

- **On an end-of-life host this pipeline no longer records a session at all.**
  `capture.sh` refuses a production frame before any file exists, and
  `launch_game.sh` refuses to start or accept an instance that will be captured.
  Verified after the change, on this host, with the waiver set: `FRAME_INDEX=99998
  capture.sh` exits non-zero with *"refusing to capture a frame for the record
  while the trust state is diagnostic (PLAYTHROUGH_ALLOW_EOL_PLATFORM)"*, and no
  PNG is created.
- **The waiver buys diagnosis, not evidence.** `PLAYTHROUGH_CAPTURE_MODE=diagnostic`
  still works and still withdraws its frame out of the working tree.
- **Three of the derived stages are unaffected; two are not, and an earlier
  version of this bullet got that wrong.** It said "the derived stages are
  deliberately unaffected … timeline, transitions, render, transcripts and the
  caption mux can be re-run over an existing record". That is true of
  `timeline.py`, `make_transitions.py` and `make_srt.py`, none of which contains
  a trust gate — and **false of the two that produce media**. Measured on this
  host under the waiver: `render_movie.assert_trusted_render()` raises
  *"REFUSING to encode the film while the trust state is diagnostic"*
  \[render_movie.py:605\], and `embed_captions.sh` exits **8** (`EX_PREREQ`) at
  `playthrough_assert_trusted "the caption mux"` \[embed_captions.sh:874\] before
  ffmpeg is invoked; both films were byte-identical afterwards, so neither
  refusal is a partial write. So a waived host can recompute the *timeline and
  the transcripts* over an existing record, but it can neither re-encode the film
  nor re-mux its captions. What the waiver can no longer do is manufacture the
  record — or republish the media.
- **The already-recorded session keeps its disclosed provenance.** It was
  captured on this host under the waiver, before the gate was tightened, and
  that is stated here and in the environment summary rather than reinterpreted.
  **A compliant re-capture requires a supported release**; that is a platform
  action, not a code change, and nothing in the pipeline depends on 25.10.

`PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM` is retired and *answered* rather than
ignored: `=1` is now the default and says so, and `=0` no longer weakens
anything and says that, because an operator who set a variable believing it
configured something has to be told it did not.

### The supported release is now DECLARED, and the production path is proved in it

The bullet above — *"a compliant re-capture requires a supported release; that is
a platform action, not a code change"* — was true and insufficient, and a code
review said so plainly: a pipeline whose every production stage refuses on the
only host available has **no declared production path at all**. Naming the
requirement is not the same as making it available, and "somebody should find a
supported host" is not a path a later reader can walk. Three tracked files close
that gap.

`playthrough/tooling/environment/Dockerfile` **is the declaration.** Ubuntu 26.04
LTS, chosen for two independent reasons, one of which was learned the hard way.

The first is arithmetic: env.sh's own dated table carries `ubuntu:26.04` to
**2031-04**, so the platform gate passes on its own terms with no waiver and no
bypass. It also clears the engine's ABI floor — the committed binary needs at most
`GLIBC_2.38` and `GLIBCXX_3.4.32` — so a binary built on an older host still runs
there.

The second is **functional, and it disqualifies a release the table accepts.** The
first version of this image was built on Ubuntu 24.04, and every stage below
passed on it. It still could not record a session, because **on 24.04 the
character creator cannot be reached**: the `Create World` dialog that stands
between the main menu and the creator will not raise its own confirmation, so the
route stops there.

Stated exactly, because the distinction matters and only one half of it was
isolated. What was **measured** on 24.04: the dialog was reached and displayed
correctly; its sliders had moved under the arrow keys, so keys were reaching it;
pressing `f` (`[f][ Finish ]`, visibly focused) produced **no confirmation
dialog**, and neither did `Return`, `xdotool type`, or a mouse click on the label;
two root grabs two seconds apart were **byte-identical**; the process was alive and
busy throughout (`Rsl`, 14–30% CPU in `hrtimer_nanosleep`); `xprop -id <w>
_NET_WM_PID` returned the live engine's pid and `session.py window` resolved the
same id; `xdotool getactivewindow getwindowname` returned the engine's title, so
it held focus; `xset` reported an all-zero LED mask; and `debug.log` and the game
log carried no ERROR or WARN. What was **not** isolated is whether the
confirmation never opened or opened without rendering — a distinction worth
naming, because on 26.04 the same dialog's confirmation was at one point invisible
to the OCR text decode while the game's own keybindings overlay reported it as the
open window. Either way the creator is unreachable, which is the fact the base
image had to answer.

`debug.log` names the most likely mechanism: *"SDL version used during compile is
2.32.4 … used during linking and in runtime is 2.30.0"*. SDL guarantees
**forward** compatibility only, so a binary compiled against 2.32 running on 2.30
is the unsupported direction. **Rebuilding the engine inside 24.04 did not fix
it** — a full 1570-second, 446-object rebuild there produced a binary reporting
*compile 2.30.0 / runtime 2.30.0* and the dialog behaved exactly as before — so
this is not a version *skew*; on that release the path is closed either way. On
26.04's **SDL 2.32.10** the same unmodified host-built binary drives the dialog
correctly: `f` raised *"Are you SURE you're finished? (Case Sensitive) \[Y\]es
\[N\]o"* and `Y` opened the creator.

So a capture host must satisfy **both** conditions — a release the dated table
accepts **and** an SDL2 runtime of at least 2.32 — and `supported_env.sh` says so
in the message that offers the container-free alternative, naming 24.04 explicitly
as passing the table and still not being a capture host. This is exactly the kind
of requirement that cannot be discovered by reading a table, which is why the
preflight exists.

The image carries every tool `playthrough_require_tools` asserts, the SDL2
runtime, the compiler set that can rebuild the engine *in the same environment
that captures it* (`g++-14` pinned, because 26.04's default is GCC 15 and this
engine builds `-Werror`), and a venv at `/opt/playthrough-venv` installed from
`requirements.lock` under `--require-hashes`. Two consequences of the newer base
are worth recording:

- **SDL3 is present in 26.04** (`libsdl3-dev 3.4.2`, which would satisfy the
  Makefile's `>= 3.4.0` gate). Every `make` here still carries `SDL3=0`: the SDL3
  GPU-shader path is out of scope for this checkpoint, and the committed record
  was captured through SDL2.
- **The pipeline's interpreter is built from source.** 26.04 ships Python 3.14 as
  `python3` and has no `python3.12` package at all, while `env.sh` pins
  `PLAYTHROUGH_PYTHON_ABI="3.12"` and `requirements.lock` holds only `cp312`
  wheels under `--require-hashes --only-binary :all:`. Relaxing the closure to
  suit the base image would be the wrong way round — the closure is what the
  film's byte-level reproducibility rests on — so the image compiles **CPython
  3.12.13** from the python.org tarball, **pinned by sha256**
  (`0816c476…b0b`, verified on every build, a mismatch failing it) and creates the
  venv from that. `--enable-optimizations` is deliberately omitted: it triples the
  build for a speed-up a pipeline that spends its time in ffmpeg and the engine
  cannot notice.

Apt versions are deliberately **not** pinned — the value of a supported release
*is* the updates it publishes, and pinning the archive would freeze the image on
the day it was written while claiming to be patched — so the build **records** what
it installed instead, at `/opt/playthrough-image-inventory.txt`, including the
built interpreter's version, its source digest, and the system `python3` it is
*not*.

`playthrough/tooling/supported_env.sh` **is the driver** (`build`, `inventory`,
`run`, `shell`, `preflight`). It moves the workload, not the gate: it clears
every name in `PLAYTHROUGH_TRUST_BYPASS_VARS` on the way into the container, so a
host operating under a waiver cannot leak one in, and it does **not** source
env.sh — doing so on an end-of-life host is the refusal it routes around, and it
would import the host's own waiver into the one process that must not carry one.
The registry is therefore restated as a literal, and `test_supported_env.py`
compares that literal against env.sh's exported list so the copy cannot drift.

`playthrough/tooling/preflight_capture.sh` **is the proof**, in eleven stages, and
it is written to run either inside that image or directly on any release the
table accepts. It does not assert that the gates would open; it opens them:

| Stage | Measured on Ubuntu 26.04 LTS, image `playthrough-capture:26.04` |
| --- | --- |
| 1 platform | `PLATFORM_SUPPORTED=yes`, `PLATFORM_EOL=2031-04`, `PLATFORM_SOURCE=/etc/os-release`, `TRUST_STATE=trusted`, `TRUST_BYPASSES=` empty, `PLATFORM_WAIVER=` empty |
| 2 toolchain | all 16 tools env.sh asserts, versions recorded (Xvfb 21.1.22, openbox 3.6.1, xdotool 3.20160805.1, xauth 1.1.2, ImageMagick 7.1.2-18, ffmpeg/ffprobe 8.0.1, tesseract 5.5.0) |
| 3 python | `PYTHON_VERSION=3.12.13` (the source-built interpreter), `PIP_CHECK=ok`, all six declared libraries import, `ocr_clock.py --preflight` ok |
| 4 engine | `Cataclysm Dark Days Ahead: 1ad0bd73d4 +tiles, +sound` |
| 5 display | `:99` at `1920x1080x24`, `XAUTHORITY_ORIGIN=pipeline` |
| 6 scratch | a throwaway checkout under `$TMPDIR`, engine `284407592` bytes |
| 7 launch | calibration launch, `seed_options.py`, then window `4194313` at `1920x1080+0+0` with `INITIAL_UI_STATE=main-menu-create-permitted`, tileset `MshockXottoplus` / `MSXotto+` / `required-installed` |
| 8 capture | **2 kept frames = 2 manifest rows = 2 telemetry rows = 2 digest attestations**, `1920x1080`, luminance `0.00620352 / 0.0687404`, `manifest.py verify` clean |
| 9 render | `h264, 1920, 1080` |
| 10 captions | `mov_text, eng` |
| 11 teardown | `frames=419 rows=419 dirty=18` before **and** after; scratch removed |

`PREFLIGHT_FAILURES=0`, `PREFLIGHT=pass`, eleven of eleven. **The earlier
measurements in this table were taken on Ubuntu 24.04 and are superseded**: they
were true of the stages they measured and still describe a host that cannot drive
the character creator, which is why the base moved and the numbers were re-taken
rather than carried over.

Stage 8 is the one that matters, because a **kept** frame with a digest
attestation is precisely what `capture.sh` refuses under `diagnostic`. Producing
one is not an argument that the capture gate opened; it is the gate's own output.
Stages 9 and 10 are the same kind of evidence for the two refusals corrected in
the bullet above.

**Nothing here touches the committed record.** Stages 7–11 need somewhere to
write, so they build a scratch checkout — the tooling copied, `data/`, `lang/`,
`src/` and `Makefile` symlinked, `gfx/` **copied** (a symlinked `gfx/`
canonicalises outside the checkout and `launch_game.sh` rightly refuses artwork
it cannot hold against the tracked provenance anchor), and an empty
`playthrough/` tree. The record's fingerprint is taken on both sides of the run
and compared, by the preflight itself and again by the driver outside it.

**Two of the pipeline's own gates refused this file while it was being written,
and both refusals were right.** `manifest.py` rejected its first commentary for
carrying the word *keystroke*, and `make_srt.py` rejected the second for needing
three lines of 42 columns. The preflight's rows are held to the same standard as
the record's, which is the point; the sentence is now *"I hold still and look
before I choose."*

**What this does and does not settle.** It settles that the pipeline has a
buildable environment in which capture, render and mux all work — the gap the
review identified. It does **not** by itself produce an R11-compliant session:
that needs a survivor played from creation to a sleep-and-wake ending and out
through the in-game Save & Quit, which is a session, not a preflight. What the
preflight removes is the obstacle that made such a session impossible to attempt.

**Tightening it required a second, narrower seam, and that seam is disclosed
here because it touches the same gate.** Making the waiver a trust bypass broke
74 tests in `test_capture.py` and 44 in `test_launch_game.py` — not because the
control was wrong, but because those fixtures had been setting
`PLAYTHROUGH_ALLOW_EOL_PLATFORM` to get *past* the platform gate on this
end-of-life host, which now put every one of them in the diagnostic state they
were not testing. The counts are measured, not recalled: removing the emulated
source again from the finished fixtures reproduces 83 failures of 98 in
`test_capture.py` and 54 failures plus 6 errors of 154 in `test_launch_game.py`,
and restoring it returns both to green. The wrong repair is to exempt the suites
from the control.
The repair taken instead is `PLAYTHROUGH_OS_RELEASE`, which names the file the
verdict is read out of:

- **It emulates a host; it does not relax a check.** The gate still runs, still
  consults the same dated table, and still refuses an out-of-support answer read
  from a nominated file. The fixtures now write an `os-release` naming Ubuntu
  26.04 LTS — a release that genuinely passes — instead of asking to be excused
  from the question. It is the same tactic these suites already use for the X
  server, where a stub `xdpyinfo` refuses a cookieless client the way an
  authenticated server does.
- **So it is not in the trust-bypass registry**, and that is a substantive
  distinction rather than a convenient one: nothing about the readings is
  weakened by answering a question about the host with a different host's answer,
  whereas the *waiver* proceeds despite the answer. `test_env.py` asserts both
  halves — that a nominated source is not a bypass and that the trust state stays
  `trusted`, and that an expired release read from a nominated file is still
  refused.
- **It is disclosed in the same contract that carries the film.** A nominated
  source is warned about once, exported as `PLAYTHROUGH_PLATFORM_SOURCE`, and
  printed as a field of the environment summary, so a session whose verdict did
  not come from its own host says so where a later reader will meet it. The
  default value is `/etc/os-release` and that case is silent.
- **It fails closed.** The file is read only if it is a regular file, never
  through a symlink — a path that can be repointed after the check is not
  evidence — and a source that is missing, symlinked or a directory yields
  `unverified`, which the gate refuses. Ten tests in
  `TestThePlatformSourceCanBeNominated` hold those five outcomes.

**Where the gate is enforced, and where it deliberately is not.** Every shell
entry point calls it — `capture.sh` directly and again through
`playthrough_assert_display`, `launch_game.sh` through the same assertion, and
`embed_captions.sh` directly (it was the one stage that did not, which was an
inconsistency rather than a decision, since it sources the same `env.sh`). So
launching the game, capturing a frame and muxing the captions all refuse.

The three Python render stages — `make_transitions.py`, `render_movie.py`,
`make_srt.py` — do **not** re-check, and that is a judgement rather than an
omission. The support table is a set of dates about the world, and putting a
second copy of it in Python would give it two places to drift; deriving the
verdict from `env.sh`'s exported `PLAYTHROUGH_PLATFORM_SUPPORTED` instead would
make sourcing `env.sh` a hard precondition for stages that currently compute
their own defaults and run standalone. What those stages consume is also
narrower than what the gated stages consume: `timeline.json` through the
standard library, and PNGs *this pipeline captured under the gate*, behind the
format restriction and the IHDR check described below. The boundary where an
unmaintained parser meets something outside the pipeline is the X server and
the game, and that boundary is gated. Stated here so a later reader knows it
was weighed.

**The Pillow pin cannot be raised, and what was done instead.** `pillow`
11.3.0 carries 36 advisory records in OSV against 12.3.0's zero, so the
attractive move is obvious — and it is unreachable. `moviepy` declares
`pillow<12.0,>=9.2.0`, and 2.2.1 is the newest `moviepy` there is (both
re-verified against the live index on 2026-08-04), so **11.3.0 is the newest
Pillow the declared render stack supports**, and the AAP pins that pair
(§0.5.1) while recording "Dependency Changes to the Existing Project: None"
(§0.5.4). Pinning 12.3.0 anyway was tried and reverted: it puts
`requirements.txt` permanently outside `moviepy`'s declared range, so
`pip install -r` fails with `ResolutionImpossible`, `--no-deps` becomes a
standing override, `pip check` carries a permanent complaint that occupies the
one line an operator reads to notice a *real* conflict, and the renderer is
paired with an image backend its own maintainers never tested it against — in a
pipeline whose whole point is a reproducible byte-level artifact.

Two alternatives were considered and refused for reasons, not convenience. An
**audited third-party MoviePy fork** compatible with Pillow 12.x would swap a
reviewed, widely-used release for an unreviewed one, which relocates the
supply-chain risk rather than removing it — and no such fork is published. A
**private Pillow build** carrying backported fixes would produce a native
imaging binary nobody downstream can verify and no advisory database describes,
which is the opposite of what `requirements.lock` exists to establish, and
there is no upstream 11.x patch release to base it on.

So the exposure was closed at the *input* instead, and these are code with
tests behind them rather than an argument:

| Control | Where | Effect |
| --- | --- | --- |
| `formats=["PNG"]` + 8-byte signature | `ocr_clock.open_png`, `open_png_bytes` | Content sniffing is off: a BMP, PSD or TIFF renamed `.png` raises `UnidentifiedImageError` instead of reaching that format's native parser. The module has no other `Image.open`, and `test_ocr_clock.py` asserts that structurally. |
| Signature + IHDR before composition | `make_transitions._image_size` | The module decodes nothing itself; only a proven PNG reaches MoviePy's `ImageClip`. |
| Pure-Python IHDR geometry | both modules | The commonest question asked of a frame — "is it 1920x1080?" — is answered from 24 bytes of header, so no decoder runs at all. |
| `MAX_PIXELS` ceiling | both modules | A small file declaring an enormous canvas is refused before allocation. |
| Font attested by path **and** sha256 `e0d64567…4cb2a6` | both modules, same digest | An untrusted font beneath `--repo-root` cannot be substituted for `data/font/Terminus.ttf`. |
| Hash-pinned wheel under `--require-hashes --only-binary :all:` | `requirements.lock` | The reviewed Pillow artifact is fixed byte for byte, so a compromised index or a mutated wheel is refused at install time. |

The residual risk is stated rather than dressed up: a **truncated or corrupt
PNG this pipeline captured itself** is still input to the decoder — the format
restriction rules out a *different* parser, not a malformed instance of this
one — and 11.3.0 is the last of its series, so there is no in-series patch
release to move to if something new is published against it. The revisit
trigger is written into `requirements.txt`: when a `moviepy` release lifts the
`pillow<12.0` cap, move both pins together, re-measure the advisory counts, and
re-run the transition path end to end before trusting it with a render.

**The tileset that was actually resolved: `MshockXottoplus`.** Not a claim
about what was installed but a reading of what the engine loaded — its own
log says so, twice, at the launch that recorded this session:

```
20:35:54.978 INFO : Loaded tileset: MshockXottoplus
20:35:55.083 INFO : Loaded tileset: Larwick Overmap
```

[playthrough/userdir/config/debug.log], matching `"name": "TILES", "value":
"MshockXottoplus"` in [playthrough/userdir/config/options.json] and the id
`NAME: MshockXottoplus` in `gfx/MShockXotto+/tileset.txt` — a path that
exists only once the pack has been installed, since `gfx/` is untracked; see
"The tileset" below for the current state of this clone. The close-range
art in the gameplay frames is MSXotto+; `Larwick Overmap` is the *overmap*
tileset the engine loaded alongside it, and no frame in this session shows the
overmap screen, so it appears in the log and not in the film.
`ASCIITiles` is installed and was **not** used. `gfx/` is excluded by
[.gitignore:52] with four negations, so the installed pack is deliberately
untracked and `.gitignore` was **not** edited to change that.

**The environment gate, re-run.** With `CLONE_INDEX=002`, `env.sh` yields
`DISPLAY=:101` — the contract's `:99` offset by the clone index so parallel
checkouts cannot collide — `SDL_VIDEODRIVER=x11`, `SDL_AUDIODRIVER=dummy`,
`LIBGL_ALWAYS_SOFTWARE=1` and `XDG_RUNTIME_DIR=/tmp/xdg2` at mode 0700.
`xdpyinfo` then reports `dimensions: 1920x1080 pixels` and `depth of root
window: 24 planes`. `./cataclysm-tiles --version` reports
`Cataclysm Dark Days Ahead: 6dea631409-dirty` and `+tiles, +sound` — and that
same version string is rendered in the frames themselves (frame 1 and frame
560 both read `Version: 6dea631409-dirty`), which ties the committed sequence
to this binary rather than to an assertion about it.

**The capture path was proved without touching the committed userdir.** A
bare root grab measured `mean=0 std=0` — the empty desktop, and a live
demonstration of exactly what the luminance gate catches. The game was then
launched against a **throwaway userdir outside the working tree**
(`--userdir /tmp/cata_probe_002/`), found with
`xdotool search --class cataclysm-tiles`, captured with
`import -window root` at 1920x1080 measuring `mean=0.000555 std=0.0181`, and
read by tesseract as `Select your lanquage / 1English` — the documented
first-launch prompt, with the reader's genuine `q`-for-`g` slip left exactly
as it came out rather than tidied up.
The probe was stopped by its own pid and its userdir deleted;
`git status --porcelain` stayed empty throughout. Nothing was written into
`playthrough/frames/` and no capture was taken against
`playthrough/userdir/`, which holds committed engine state.

**What the frames measure.** Every gate below was run over all 560, not a
sample: 560 directory entries, every one matching `frame_%05d.png`, no
subdirectory, no symlink, no `.gitkeep` and no stray file; indices contiguous
`1..560`; `identify` reporting `PNG 1920x1080` for every frame; grayscale
`mean > 0` **and** `std > 0` for every frame, with the means spanning
`0.878 … 56.485` on the 0-255 scale; and a second, independent decode of all
560 through Pillow returning exactly one distinct size, `(1920, 1080)`. The
manifest relation is a strict bijection — 560 rows, 560 unique `file` values,
row `frame` numbers equal to the on-disk indices, every row carrying all six
schema fields with a non-empty `action` and `commentary`. `timeline.json`
holds 560 entries, `transcript.srt` 560 cues and `transcript.md` 560
timestamped entries. Durations sit inside `[0.25, 10.0]` with `min=0.25` and
`max=10.0`; the 482 zero-delta frames are all at the floor, none dropped;
`transition_after` is set exactly where the raw delta exceeded 10 s; and
`326.500 s` of frame time plus `11.000 s` of transition equals the
`337.500 s` total and the final cue end, to the millisecond.

**The caption track carries the short form of a long sentence, and says so.**
A cue is at most two lines of about forty-two columns, because a caption track
is read at the speed the film plays and a cue of five or seventeen lines covers
the picture it is captioning instead of explaining it. 223 of the 560
sentences do not fit that, so their cues carry as much as does fit — cut at a
word boundary, never mid-word — and end in ` [...]`, the conventional mark for
elision, in ASCII so the cue file stays 7-bit through the `mov_text` mux.
`playthrough/transcript.md` carries all 560 sentences **verbatim and entire**,
which is checked frame by frame rather than sampled, so nothing the survivor
said is lost anywhere: the deed is in the caption, the whole reason is in the
record, and the mark is what tells a viewer to look. The longest sentence is
654 characters (entry 537). Measured after regeneration: 560 cues, maximum
2 lines, no line over 42 columns, 223 cues marked, no byte-order mark, LF
endings, zero non-ASCII bytes, the final cue still ending at `00:05:37,500`
= the timeline's own `337.500 s`, and the Nth Markdown stamp still identical to
the Nth cue start for all 560.

**The honesty gate, at full scale.** 153 of the 560 rows carry an exact
`HH:MM:SS` reading; the other 407 are `null` (402 creation frames, which have
no in-game clock at all, plus frames 420, 421, 505, 536 and 560 where the
sidebar was momentarily unreadable) and the arithmetic closes exactly:
153 + 5 = 158 = 560 − 402. Every one of the 153 was **re-read from the
committed PNG** with the pipeline's own `ocr_clock.py --kv`, and all 153
agreed with the manifest character for character — 153 agree, 0 differ, 0
reader errors. A deliberately crude hand-rolled alternative
(`convert … -resize 200% -normalize | tesseract`) matched only 4 of 18
sampled frames, reading `48:48:48` for `08:00:00` and `15:28:67` for
`15:28:07`, which is worth recording twice over: it shows the module's
preprocessing is load-bearing rather than decorative, and it shows the
manifest values agree with the careful reader and not with a guess.

**The spawn was a golf course service building, and that is a legitimate
`missed` spawn rather than an anomaly.** The sidebar on the first gameplay
frame of the retired 560-frame set reads `Place: golf course servic…`. The
citation is deliberately to an **immutable blob and not to a live path**,
because `playthrough/frames/frame_00403.png` has since been rewritten twice
by two re-records — row 403 of the shipped set is Delphine entering a letter
of her last words, and the shipped spawn is a restaurant at frame 192 — so a
live-path citation inside a retired section rots the moment the set is
replaced:

```console
$ git show 7117ef9700:playthrough/frames/frame_00403.png > /tmp/retired_403.png
$ git ls-tree -l 7117ef9700 -- playthrough/frames/frame_00403.png
100644 blob a50ce8d123c64e618876e1bb4e4d47298482848b   85777 …frame_00403.png
$ python playthrough/tooling/ocr_clock.py --rect 352x1072+1568+4 \
      --field text --no-check-options /tmp/retired_403.png | grep -i place
 Place: golf course servic              v
```

Commit `7117ef9700` is the commit that carried that 560-frame set (560 tracked
PNGs); `0ce3a14cfe` carried the 395-frame set and `4e8a49879a` carries the
shipped 419. The scenario's own `allowed_locs` list runs to twenty-five
locations —
`sloc_house` and `sloc_house_boarded`, but also `sloc_grocery_store`,
`sloc_garage`, `sloc_furniture_store`, `sloc_library`, `sloc_church`,
`sloc_golfcourse_mid_course` and `sloc_golfcourse_clubhouse` among them
[data/json/scenarios.json, `id: missed`]. "The survivor wakes up in a house"
would therefore have been a narrowed claim rather than a reading, which is
why the record says what the frame says instead.

**The crop is computed, and it is not the value the plan predicted.**
`sidebar_geometry.py` resolves `352x1072+1568+4` here — 44 cells × 8 px —
because `playthrough/userdir/config/panel_options.json` does not exist, so the
layout is the engine's own default `legacy_labels_sidebar`
[src/panels.cpp:413-419, assigned at :418] and not the 36-cell
`custom_sidebar` that would give `288x1072+1632+4`. The module says so in a
warning before it prints the rectangle, rather than resolving a wrong number
quietly.

What the difference costs was measured rather than asserted. Cropping frame
403 at the predicted `288x1072+1632+4` loses the leftmost 64 px — the label
column — and a crude `convert … -resize 200% -normalize | tesseract` read of
that narrower strip returns no `Time` line and no `HH:MM:SS` at all, while
`ocr_clock.py` still recovers `08:00:00` from it because its preprocessing is
more careful than that. So the hard-coded rectangle would not have failed
loudly; it would have quietly leaned on the reader's robustness on this
layout and had nothing to lean on when a wider or left-positioned sidebar
moved the column further. Computing the rectangle is what removes the
dependence.

**Frame 1 shows the cursor on `Preset Character`, and that is the engine's
own default.** [src/main_menu.h:76] initialises `int sel2 = 1;`, so the New
Game sub-menu opens with its cursor already on the second entry. Frame 2
presses `Up` to move off it, and frame 3 activates `Custom Character`
[src/main_menu.cpp:476]. A forbidden entry is *shown* under the cursor in the
first frame because the engine put it there; none was ever activated, and no
action in the 560 rows selects `Preset Character`, `Random Character`, either
`Play Now!` entry or the tutorial.

**Git state.** All 560 frames are tracked at mode `100644`; the tracked set
equals the on-disk set; `git check-attr` reports `binary: set`, `text: unset`
and `diff: unset` for a frame, from `*.png binary` [.gitattributes:39], which
is what keeps the bytes the luminance gate measures byte-identical through a
checkout; `git check-ignore` exits non-zero for a frame, i.e. no pattern
excludes it; and `git status --porcelain playthrough/` is empty.

`!/playthrough/**` [.gitignore:275] is the **last pattern in the file**, and
nothing follows it: git applies the last matching pattern, so anything added
after it would re-exclude part of this tree and `git add` would then skip
those paths, exit 0 and report success while tracking nothing — the one
failure mode in this feature that is invisible in the artifacts themselves.
Nothing under `playthrough/` is therefore ignored, bytecode included, and
bytecode is kept out **at source** instead: `env.sh` exports
`PYTHONDONTWRITEBYTECODE=1`, every module that imports a flat sibling sets
`sys.dont_write_bytecode = True` before the import the interpreter would
compile, and every documented command passes `-B`. Verified by running all
nine importing modules standalone with bytecode writing deliberately enabled
— no `__pycache__` appeared. One tool defeats all three, and it is the one
the per-file checklists name: `python -m py_compile` writes the `.pyc`
explicitly, so `-B` and the environment variable do not stop it. The syntax
check is therefore run as `python -B -c "compile(open(p).read(), p, 'exec')"`
over the tooling, which compiles every module and writes nothing. Across
the whole feature, `git diff --name-status` against the pre-feature base
touches `.gitignore` and 740 `playthrough/**` paths and nothing else — no
`src/`, no `tests/`, no `data/`, no `Makefile`, no `CMakeLists.txt`, no
`.github/`. `.gitattributes` needed no change at all: its `*.gsav`, `*.mp4`,
`*.sav`, `*.zzip`, `*.jsonl` and `*.srt` entries were already in place at the
base commit.

**The tooling's own suites, run in full:** 1179 tests across the nine
`playthrough/tooling/test_*.py` modules, all passing (95 capture, 87 env, 149
launch_game, 102 make_srt, 100 manifest, 152 ocr_clock, 107 seed_options, 78
sidebar_geometry, 309 timeline with one skip). `flake8 playthrough/` reports
zero findings and `make python-check` exits 0 repo-wide.


## The session was re-recorded, and this section supersedes every count above

> **RETIRED — this block describes the second, 395-frame session, which did not
> ship.** It supersedes everything above it, and is itself superseded by *Runtime
> QA remediation of the 419-frame record*. Every "395" below belongs to a dead
> set, including the artifact table's claim that the save was "written by the
> in-game Save & Quit path" and the whole-suite figure of "1377 tests" — the
> shipped record ended in **death**, not Save & Quit, and the current suite
> figures are in *The tooling's own suites, mechanically counted*. It is kept
> because the engine behaviours it pins down and the tooling it produced are
> still in force.

Everything above this heading describes the FIRST recorded session — 560
frames, 560 manifest rows, and the artifact set built from them. That session
was rejected at code review on two evidence findings, both of them inside the
character-creation half:

* one row named a key that had not been delivered and carried the literal
  word `placeholder` where its commentary belonged; and
* one delivered keystroke had no frame and no row at all, so the run held 561
  keys against 560 rows. The capture telemetry corroborated it independently
  at 559 sidecar rows.

Neither is correctable by hand. Editing the action field or synthesising the
missing row would be inferring a correction into an evidence file, which is
exactly what the "do not fabricate" rule forbids, and the review asked twice
for a re-record rather than a repair. So the session was played again from
character creation under the hardened transaction, and every artifact was
rebuilt from the new evidence.

The AAP's own resume rule — "if a save already exists, continue that save
file" — was weighed against this and does not bind here: the save that existed
was this deliverable's own rejected output, the AAP anticipates that this run
creates a character, and R10 requires the creation frames to be present in the
delivered evidence. The superseded evidence is not lost; it remains in git
history at commit `e50300eeb0`.

### Frame 244: the rejected run's defect reproduced, and refused

The re-record hit the identical failure at the identical point. The `Y` that
answers "Are you SURE you're finished?" on the creator's summary screen was
delivered, and the frame captured 0.3 s later was pure black — the creator has
torn down and worldgen has not yet drawn:

    playthrough: FATAL: capture.sh exited 4 for frame 244 (the frame is blank)
    playthrough: FATAL: playthrough/frames/frame_00244.png is blank:
                 grayscale mean=0 stddev=0

The pre-hardening tooling deleted that frame and carried on, which is what
produced the 561-keys-against-560-rows gap. The hardened path did the
opposite: it withdrew the blank capture, PRESERVED it at
`<runtime>/rejected/frame_00244.png` rather than destroying it, appended no
row, and stopped the session outright — because the keystroke had already been
delivered and a delivered keystroke is not undoable. The durable pre-send
journal then recovered it at the SAME index on the next open:

    playthrough: WARNING: the keystroke 'Y' for frame 244 had been delivered
    but no frame existed for it; the frame has been captured at the same index
    and its row appended
    FRAME_LAST=244  RECOVERED=1  RECORD_PROBLEMS=0

Sidecar row 244 records `key='Y' recovered=True attempts=2` with the
luminance of both attempts. The defect the review found is therefore not
merely fixed in the source; it was reproduced live and handled correctly, and
the evidence of the refusal survives on disk.

### The world is named Fern Creek, and the town is Mount Chase

The world-name field arrives pre-filled with a generated name —
`Independence` on this run — and the field's contents are replaced rather than
appended to by the first character typed. `Fern Creek` is therefore what the
survivor typed, and it is the world name, not a place in the game. The town
she is actually standing in is `Mount Chase`, which the overmap header
supplied at frame 306; her log corrects itself there. Rows before that frame
use "Fern Creek" as the name she had for where she was, which is what she
believed at the time and is recorded as such.

### Corrections made inside the re-recorded log

The log is written keystroke by keystroke, before the resulting frame can be
read, so it records intentions that the very next frame sometimes disproved.
Every one of those is corrected in the survivor's own voice in the row that
follows it, and no frame, key, clock value or row was altered:

| Rows | What the row expected | What the frame showed | Corrected at |
| --- | --- | --- | --- |
| 256-258 | three steps south-east and east | the standing mirror's appearance menu was modal and swallowed all three; nothing moved | 259, again at 269 |
| 279-280 | two steps west toward a wardrobe | a bathtub occupies that square; nothing moved | 281 |
| 296 | five minutes had passed | a "Heard moaning! Stop waiting?" query had stopped the clock at 08:00:27 and was swallowing the key | 297 |
| 334 | a step south out of a door frame | the step did not take; she was still in the frame | 336 |
| 368-370 | the phone's action menu | the tool list had grown a sewing kit above the phone, so the sewing kit was opened instead | 371-373 |
| 384-387 | four commands to pass time | "You start having withdrawals! Stop trying to fall asleep?" was modal for all four | 388 |

The operator's discipline changed after the first of these: from row 259
onward the commentary states the decision and the reason and stops asserting
the outcome, because the outcome belongs to the next row, after the frame has
been read.

### Six out-of-character wording advisories, and why the rows stand

`manifest.py` and `make_srt.py` both flag suspect wording without altering
anything. Six entries are flagged in this session:

* **325 and 381, on "sidebar".** Genuine slips. "Sidebar" is the game's word
  for its readout panel, not the survivor's, and it should have been "the
  readout" or "the panel". The manifest is append-only evidence and the
  session is over, so the rows stand as written and the slip is recorded here
  instead.
* **333, 336, 338 and 359, on "frame".** False positives, every one: each is
  a DOOR frame — "stand in the frame of it", "still in the frame of the
  upstairs door", "reaching from the door frame", "step out of the frame
  first". The heuristic cannot tell a door's frame from a video frame. This is
  the same class of hit the review itself recorded as a false positive against
  the superseded rows 509 and 523.

### The date line's weekday disagreement

`timeline.py` reports:

    the date line went from 'Thursday, May 20' to 'Thursday, May 21', a step
    of 1 day(s), but Thursday is not 1 day(s) after Thursday; one of the two
    lines was misread and the day count is reported as it was read

Both readings came from real frames and the day count is correct — the game's
own achievement notice independently timestamps the wake-up as `Year 1, May 21
02:14:48`. The weekday word is what disagrees, and the tool reports the
disagreement rather than silently repairing either reading, which is the
behaviour the honesty rule requires.

### 246 of 395 clock readings were reconciled, and why that is the honest number

The sidebar clock does not exist during character creation: the creator draws
its own full-screen form, so frames 1-243 have no clock and no date line to
read. Frame 244 is the first frame with an exact clock (`08:00:00`), which is
also the first frame of play. Above 244, exactly three frames have no readable
clock — 306 (the overmap covers the sidebar), 390 (the engine's own error
screen), and 395 (the save-and-quit screen). That is 243 + 3 = 246, and every
one of them is flagged in `timeline.json` with `clock_kind: "null"` and
`reconciled_reason: "clock-missing"`. Not one clock value was invented; each
reconciled frame falls to the 0.25 s floor.

### The engine's own debug error screen

Twice during the night the engine put up its own error report over the game:

    DEBUG : tough zombie cannot climb over dumpster.
            monster::calc_movecost expects to be called with valid destination.
    C++ SOURCE FILE : src/monmove.cpp
    LINE : 1779
    VERSION : 6dea631409-dirty

`playthrough/userdir/config/debug.log` also holds an earlier one,
`src/do_turn.cpp:293: game:monmove: zombie can't move to its location!
(101:81:0), pavement`. Both are upstream Cataclysm-DDA assertions about the
engine's own monster pathfinding, raised while the game ran turns during the
survivor's sleep. No file under `src/` was touched by this feature, so neither
is attributable to it, and the AAP forbids changing the engine to silence
them.

Dismissing that dialog is not a debug command and not cheating. The screen's
own footer offers "Press space bar to continue the game" and "Press I (or i)
to also ignore this particular message in the future"; `I` was used, which
continues play and suppresses repeats of that one message. It opens no debug
menu, alters no game state, spawns nothing and reveals nothing. The frames
that show it are dark but not blank — frame 390 measures grayscale
`mean=0.00236154 std=0.0398795`, which passes the non-blank gate on both
terms.

### The stalled sleep, and a blind spot in the operator's own screen reader

For roughly a quarter of an hour the game appeared wedged: the captured frames
were byte-identical, the sidebar clock stayed at 20:06:27, and the process sat
at ~45% of a core in `hrtimer_nanosleep`. It was not wedged. A modal query —
"You start having withdrawals! Stop trying to fall asleep?" — had been on the
screen since frame 383, and the keys being sent were not among its options, so
the engine correctly did nothing with them.

The fault was in the operator's throwaway screen reader, which grepped the
prompt region for the literal string `Stop waiting` and this query says `Stop
trying to fall asleep`. The reader was widened to `Stop ` and taught to
recognise the engine's error screen; nothing in `playthrough/tooling/` was
involved, and the scratch reader is not part of the deliverable. The lesson
worth keeping is the one the AAP already states: read the frame before
choosing the next key, and read all of it.

The insomnia the survivor was built with is what produced the situation. The
game asked "You have trouble sleeping, keep trying?" and offered "Continue
trying to fall asleep and don't ask again", she took it, and she fell asleep
at some point before 02:14:49 after five recorded rounds of "You toss and
turn." She was woken not by her alarm — set for 05:06 — but by noise, and the
engine granted the achievement "The first day of the rest of their unlives"
(*Survive for a day and find a safe place to sleep*) at `Year 1, May 21
02:14:48`, `Triggered by wake up`.

### Every stage ran under an explicit, logged platform waiver

`Ubuntu 25.10` reached end of life on 2026-07-09, so the inverted platform
gate refuses by default. Each stage of the re-record and the rebuild was run
with

    PLAYTHROUGH_ALLOW_EOL_PLATFORM="container image is Ubuntu 25.10; no
    supported release available to this run"

which warns once, exports `PLAYTHROUGH_PLATFORM_WAIVER`, prints the reason in
the environment summary, and travels with the session's contract.

**Corrected since:** this section said the waiver was deliberately not a member
of `PLAYTHROUGH_TRUST_BYPASS_VARS`. It is one now — code review found the
exclusion indefensible, and the reasoning behind it self-serving on the only
host available. See *"It IS a trust bypass, and it used not to be"* above. The
consequence is that this stage set could not be produced on this host today:
`capture.sh` refuses a production frame while the waiver is active.

### Two accepted, disclosed risks — stated as risks, not as clean bills

Code review asked for two things this remediation pass cannot deliver by
editing code, and the honest answer to each is a disclosure rather than a fix.
Both are recorded here so that a reader of the evidence meets them without
having to find them.

**1. Pillow 11.3.0 carries published advisories, and no patched combination
exists upstream.** Re-verified against the live index on 2026-08-07, not
remembered: `moviepy`'s newest release is 2.2.1 and it declares
`pillow<12.0,>=9.2.0`; Pillow's newest release is 12.3.0; the newest Pillow
below 12 is **11.3.0**, and the whole 11 series is 11.0.0, 11.1.0, 11.2.1,
11.3.0 — so there is no moviepy release that permits a 12.x Pillow and no
patched in-range release to move to. Pinning 12.3.0 was tried and reverted
because it puts `pip install -r` permanently outside moviepy's declared range
(`ResolutionImpossible`), needs `--no-deps` as a standing override, and pairs
the renderer with an image backend its own maintainers have not tested it
against — in a pipeline whose whole point is a reproducible byte-level
artifact. `pip check` is silent on the provisioned interpreter and the
installed Pillow is 11.3.0.

What is done instead is written down in full at
`playthrough/tooling/requirements.txt` and is code with tests behind it, not
argument: PNG-signature checks plus `formats=["PNG"]` so content sniffing is
off, geometry read from the IHDR chunk without entering a decoder at all, a
pixel ceiling enforced before any decode, the font attested by digest, and the
reviewed public wheel hash-pinned in `requirements.lock` under
`--require-hashes`. The residual risk is **not zero** — a truncated or corrupt
PNG this pipeline captured itself is still input to the decoder — and the
trigger for revisiting is stated there: when a moviepy release lifts the cap,
move both pins together, re-measure, and re-run the transition path end to end.

**2. The recorded session was captured on an end-of-life host.** That is now a
trust bypass, and the gate refuses a production capture on such a host, so the
condition cannot recur here; what it cannot do is retro-fit the existing
capture. A compliant re-capture requires a supported release, and that release is
now **declared and built rather than merely named**: `ubuntu:26.04` in
`playthrough/tooling/environment/Dockerfile`, driven by
`playthrough/tooling/supported_env.sh` and proved end to end by
`playthrough/tooling/preflight_capture.sh` at `PREFLIGHT=pass`,
`TRUST_STATE=trusted`, zero bypasses. Of the other releases the dated table
accepts, **24.04 is not a capture host** — its SDL 2.30.0 delivers no input to
the engine's ImGui screens — which is measured and recorded under *The supported
release is now DECLARED*. Nothing in the pipeline depends on 25.10.

### The re-recorded artifact set, and the gates it passes

| Artifact | Value |
| --- | --- |
| captures | 395, indices contiguous 1..395 |
| manifest rows | 395, exactly the six prescribed fields on every row, every `action` and `commentary` non-empty |
| capture telemetry rows | 395; `RECORD_PROBLEMS=0`; one recovery, at frame 244 |
| `timeline.json` | 395 entries, every duration within [0.25, 10.0], 12 `transition_after` flags, 289.000 s + 12.000 s = 301.000 s = `final_cue_end`; `--verify` reproduces it from the manifest |
| transition frames | 12 groups x 12 = 144 PNGs, under `playthrough/build/transitions/` and never in `playthrough/frames/` |
| concat list | 540 entries (395 captures + 144 transition frames + the repeated final entry) |
| `cata-play.mp4` | 5 003 785 bytes, one stream, `h264` 1920x1080, 540 frames, 301.040 s, 0 chapters, 0 audio/data/attachment streams |
| `cata-play-cc.mp4` | 5 033 804 bytes, exactly two streams: the same `h264` 1920x1080 540-frame video, byte-identical by stream hash `sha256:9a3c3b45b920cda33689386385f244c5a64deda2299a46e2ee6d4e03d18c0fed`, plus `mov_text` `TAG:language=eng` carrying 395 cues, 301.000 s — inside the picture, not past it |
| `transcript.md` / `transcript.srt` | 395 stamps and 395 cues, last cue closing at `00:05:01,000` = the timeline's own 301.000 s |
| non-blank sweep | all 539 PNGs (395 captures + 144 transitions) satisfy `mean > 0` AND `std > 0`; lowest mean 0.00236154 at frame 390. Frames extracted from the finished captioned movie at 0 s, 30 s, 120 s, 240 s and 300 s all pass both terms |
| the save | `save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.sav`, 469 031 bytes, written by the in-game Save & Quit path |

The 12 capped frames are 296, 297, 316, 318, 319, 322, 324, 379, 380, 388, 390
and 392. Their raw deltas run from 13 s to 21 587 s — the largest being the
night's sleep — and each contributes exactly 10.0 s of picture plus 1.0 s of
transition, which is why the cue cursor and the container agree.

### The engine after Save & Quit

`Save and quit` returns Cataclysm-DDA to its own main menu rather than exiting
the process, and the menu then listed `Fern Creek (1)` — one character, saved.
The engine was left there until the save had been verified on disk, and was
then terminated by `SIGTERM` on exactly the pid this session had spawned. The
character file's md5 is `a484398afb866cdc26c490467694957a` both before and
after that shutdown, so the shutdown wrote nothing and lost nothing.
`launch_game.sh stop` was tried first and refused, correctly: it will not
signal a process while a recorded session's frames exist, because signalling
instead of exiting in-game is how a run ends up with no character file.

### The tooling's own suites, lint and shell checks, re-run after the rebuild

1377 tests across the eleven `playthrough/tooling/test_*.py` modules, all
passing: 95 capture, 72 embed_captions, 106 env, 149 launch_game, 106
make_srt, 100 manifest, 187 ocr_clock, 118 seed_options, 41 session, 78
sidebar_geometry, and 325 timeline with one skip. `flake8 playthrough/`
reports zero findings; `make python-check` exits 0 repo-wide; `bash -n` and
`shellcheck -x` are clean on all four shell files; and
`python -m compileall` is clean over `playthrough/tooling/`.

### One correction to an earlier section's measurement

The "Git state" paragraph above states that `.gitattributes` "needed no change
at all" and that its `*.gsav`, `*.mp4`, `*.sav`, `*.zzip`, `*.jsonl` and
`*.srt` entries "were already in place at the base commit". That was measured
against an intermediate commit, not against the pre-feature base, and it is
wrong. Measured against the true base — `f38c2fbae3`, the merge from
`CleverRaven:master` that this branch starts from — the whole feature changes
exactly two tracked files outside `playthrough/`:

* `.gitignore`, which gains the terminal negation block ending `!/playthrough/**`
  followed by the single directory-level exclusion `/playthrough/**/__pycache__/`; and
* `.gitattributes`, which gains six entries — `*.jsonl text` and `*.srt text`
  in the text block, `*.gsav`, `*.mp4`, `*.sav` and `*.zzip` `binary` in the
  binary block — added in commit `b8bf5491a2`.

Those are precisely the two UPDATE files the AAP names, and the six entries are
precisely the six it lists. Nothing else outside `playthrough/` is touched:
`git diff --name-status f38c2fbae3..HEAD` names no path under `src/`, `tests/`,
`data/`, `Makefile`, `CMakeLists.txt`, `CMakePresets.json`, `.github/`,
`.flake8`, `pyproject.toml` or `.astylerc`, and neither does
`git status --porcelain` for those paths.

### Four AAP artifacts that do not exist in this tree

`playthrough/tooling/run_pipeline.sh`, `playthrough/tooling/verify_artifacts.sh`,
`playthrough/tooling/commit_artifacts.sh` and `playthrough/README.md` are named
as CREATE items by the AAP and are absent. They were never created, so the code
review never raised a finding against them and they were outside the scope of
this remediation pass. Nothing was lost by their absence in this run: the
stages `run_pipeline.sh` would have sequenced were invoked directly and in the
same order — `timeline.py`, `make_transitions.py`, `render_movie.py`,
`make_srt.py`, `embed_captions.sh` — and every assertion
`verify_artifacts.sh` is specified to make was performed and is recorded in the
artifact table above: the frame-count-equals-manifest-line-count identity, the
clamp bounds on every entry, transition groups against transition flags, the
`ffprobe` stream/codec/resolution/duration facts for both movies, the
grayscale non-blank property across all 539 PNGs and across frames pulled back
out of the finished captioned movie, the git-tracking status of every artifact
class, and the absence of any `debug`, `debug_mode` or `debug_hour_timer`
binding. `session.py audit` reports `DEBUG_BINDINGS=none` over eight checked
action ids, and `config/keybindings.json` was never written at all.

### The concat list is now the encoder's own input

The committed `playthrough/build/concat.txt` used to spell its entries relative
to the repository root — `file 'playthrough/frames/frame_00001.png'` — while a
transient copy with absolute entries was written outside the tree and handed to
ffmpeg. The committed artifact was therefore never the encoder's input, and it
was not runnable on its own. Measured here rather than reasoned about: ffmpeg's
concat demuxer resolves a relative entry against **the directory the list file
is in**, not the working directory it was launched from, so a list sitting in
`playthrough/build/` sent ffmpeg looking for
`playthrough/build/playthrough/frames/frame_00001.png` and it exited 254 with
`Impossible to open`. The same list rewritten as `../frames/frame_00001.png`
encoded cleanly, from the same working directory.

The entries are now spelled relative to the list's own directory —
`../frames/...` for a capture and `transitions/...` for a transition frame — and
the committed list itself is what ffmpeg is given. It is verified before it is
used: every entry is resolved back out of the bytes on disk and the sequence
must equal the planned paths plus the repeated final entry, so a short write, a
corrupted entry, or one pointing outside `playthrough/frames/` or
`playthrough/build/transitions/` stops the encode. Re-encoding from the
corrected list reproduced `cata-play.mp4` byte for byte, which is what
established that only the spelling changed and not the film.

The working directory is now a convention rather than a load-bearing choice. The
encode still runs from the repository root for consistency with every other
stage, but entry resolution no longer depends on it, so the film is the same
from any working directory.

### A transition's remainder is charged once, at the end

A transition's second is split across its twelve frames in whole microseconds.
The remainder used to be spread one microsecond at a time over the leading
frames, giving four frames at `0.083334` and eight at `0.083333`; it is now
eleven frames at the base share and the exact remainder on the last, giving
eleven at `0.083333` and one at `0.083337`. Both spellings sum to exactly
`1.000000` s — the identity is asserted rather than assumed, and a split that
did not sum is refused — but charging the remainder once keeps every frame of a
group identical except the last, so a duration read out of the committed list is
the group's base share and the single exception is where the arithmetic says it
is. Five frames come out as `0.200000` each and four as `0.250000` each, with no
remainder to place. The committed list sums to `301.000000` s, which is the
timeline's own declared total.

### The film's pictures are counted, not just its length

A duration comparison cannot see a dropped image once another entry's duration
absorbs it, and under `-fps_mode vfr` the header's `nb_frames` is routinely
absent — the real container reports `N/A`. The probe therefore asks for
`-count_packets` and the verification requires the demuxed packet count to equal
one picture per planned entry **plus one** for the repeated final entry, which
the demuxer emits as a real picture. Measured on the finished film:
`nb_read_packets=540` against 539 planned entries. A probe that can supply
neither a packet count nor `nb_frames` is reported as unable to confirm the
count rather than passed.

Every planned image is also checked for geometry before a byte of the list is
written, read from the PNG IHDR chunk so no decoder runs on a file that only
claims to be a PNG. This matters because the encode carries `-s 1920x1080`: an
image of any other size would be silently rescaled into the film and the
container would still probe at the right resolution with every count matching. A
capture taken at the game window's 1920x1072 instead of the X root's 1920x1080
is exactly the mistake that would otherwise pass.

### Shortened captions say so, in ASCII

A caption is two lines of about forty-two columns, which is the SubRip
convention and roughly what a reader takes in while one frame is on screen. 168
of this session's 395 commentaries do not fit, and the caption for those is a
word-boundary prefix of the sentence marked ` [...]`.

The mark used to be a bare `…`. That reads as the survivor's own trailing-off
punctuation — this pipeline writes literal ellipses of its own, in the
transition card's "…time passes…" — so a viewer could not tell a shortened
caption from a complete one that happens to end that way, and a caption that
drops the end of a sentence while looking complete is an altered record. The
bracketed ASCII form is conventional for elision, unmistakable, survives the
`mov_text` muxer unchanged, carries no digit that could disturb the Markdown's
timestamp count, and is machine-detectable: `caption_is_abridged()` measures it
from the rendered lines and `Cue.abridged` carries the answer, so the count is
measured rather than asserted. One bounded advisory reports the count with a
three-entry sample and names where the sentences are whole.

Nothing is summarised, reworded or reordered: the words that remain are the
survivor's own, in order, and **`playthrough/transcript.md` carries every
sentence entire** — it came out byte-identical when the captions were
regenerated, which independently confirms that only the caption side was
affected. `render_srt` refuses any cue over the cap outright, so the geometry is
a contract rather than an intention. Regenerating the cue file made
`cata-play-cc.mp4` stale, so it was re-muxed; the mux's own field-for-field
round trip compared all 395 cues and the video stream was copied intact by
sha256 stream hash.

### Placeholder sentinels in the manifest, and why they are refusals

`manifest.py` reports out-of-character vocabulary as an advisory, because that
is a judgement about tone and a blunt substring test produces false positives —
this session's own record trips it on door frames and on the survivor reading
the sidebar. A field that was never filled in is a different thing entirely, and
it is a refusal: `PLACEHOLDER_WORDS` (`placeholder`, `todo`, `fixme`, `tbd`,
`xxx`, `wip`) matched whole-word and case-insensitively, and
`UNRECORDED_ACTION_PHRASES` for an `action` that defers the record elsewhere
(`see note`, `unknown key`, `not recorded`, …).

The gate is applied at both ends — inside `row_field_problems()`, which the
canonical `verify_manifest()` and `timeline.py` both share, and inside
`build_row()` at the writer, because a row that cannot be written is a row that
never has to be corrected and the caller is a live session that still knows what
it pressed and why. It exists because a manifest row is the authoritative record
of what one keystroke did and why, and every structural check — the six-field
schema, the 1..n identity, the frame-set equality — passes straight over a field
reading `placeholder`. Run against this record it reports nothing across all 395
rows: the action of every row is derived from the immutable validated key, so a
placeholder cannot arise.

### A rollback that failed says so

When an append fails, the manifest is truncated back to the offset measured
before the write. If that truncate itself fails, the diagnostic no longer claims
the file "was left exactly as it was ... so it is still readable" and then
contradicts itself two sentences later by saying it may end mid-row. The two
outcomes are separate sentences now: restored and readable, or `ROLLBACK ...
ALSO FAILED`, the state `UNKNOWN`, and `INSPECT IT` before appending again with
the command that will show whether the last line is a complete row. An operator
who reads the reassuring half first has otherwise been told the record is intact
when nothing established that.

### The transitions directory still describes the timeline exactly

The directory is published by composing a whole generation into a staging
directory and renaming it into place, which is what makes the replacement atomic
instead of a sequence of deletions that can be interrupted half way. Atomicity
alone would quietly absorb three things it must not, so each is handled
explicitly:

- a file matching the acceptance gate's `trans_*.png` glob that this module
  could never have written — an off-format `trans_2_0.png`, or a symlink — is
  **refused** before anything is composed, and it is not deleted, because
  removing a file this module did not write is not reconciliation;
- a file nobody wrote here at all is **carried across** the switch, because
  replacing the directory must not destroy it;
- a `trans_*.png` that appears **while** the generation is being composed is
  refused before the rename, so it survives on disk and is reported rather than
  destroyed without anyone being told. The module's own abandoned staging files
  are the one exception: those are its to sweep.

Composition also streams. Holding all twelve 1920x1080 frames of a group at once
costs roughly 570 MiB of raw arrays before the clips and buffers on top, because
the faded frames come back as `float64`; each frame is now converted and staged
as it is produced. The exact-twelve count is still asserted *after* the
iteration, so a generator that stops short and one that runs long are both
refused and each names the true count, and the frames are staged and renamed
into place only once the group is complete — so a refusal publishes nothing and
leaves any previous group of the same name intact. Regenerating the whole set
this way reproduced all 144 PNGs byte for byte.

### The terminal negation, and the one hygiene risk it leaves

`.gitignore` ends with `!/playthrough/**` and nothing follows it. That is what
the AAP specifies and it is asserted by a test, and it keeps a directory-level
ignore out of the negated tree — the shape that would break the save-data
tracking invisibly, because git does not descend into an excluded directory to
evaluate negations inside it.

The cost is stated rather than left to be discovered. Because the negation is
the last matching pattern, a stray `__pycache__/x.pyc` or a `.lock` file under
`playthrough/` is **not** ignored and a blanket `git add playthrough/` would
stage it. Verified with `git check-ignore -q`, which is the test that answers
this — `check-ignore -v` prints a matching *negation* and exits zero, so it says
a path is matched, not that it is ignored. Three things stand between that and a
committed build product, and none of them is an ignore rule:

- `env.sh` exports `PYTHONDONTWRITEBYTECODE=1`, and it is load-bearing rather
  than hygiene for exactly this reason;
- every tooling module that imports a sibling sets `sys.dont_write_bytecode`
  before the import, and `-B` is in every documented command line;
- the pipeline writes no lock or journal inside the tree at all. The step lock
  and the pre-send journal live in a per-checkout scratch directory under
  `$XDG_RUNTIME_DIR`, and the staging files that must be siblings of their
  destination are dot-prefixed and removed in a `finally`.

The tree carries no bytecode and no lock today, and `git status` shows either
before the commit stage could stage it. Anyone adding a rule here should note
that the ordering is the whole contract: a re-exclusion appended after the
negation would work, and would also be the first directory-level ignore inside
this tree.

### The film is checked for silence before it is captioned, not only after

The caption mux maps exactly one video stream and one subtitle stream
and then proves the container that came out carries nothing else. That
answers whether the mux carried something through. It does not answer
where the picture came from, and those are different questions: a
`playthrough/cata-play.mp4` holding an audio track, a data stream or an
attachment was not written by `render_movie.py`, which encodes one
silent h264 stream from still images. `-c copy` with an explicit mapping
would caption such a film perfectly happily, and the picture's stream
hash would match, because the hash proves the picture survived the mux
and says nothing about its provenance.

So the census is taken three times: on the input before ffmpeg is
invoked at all, on the staged container before the rename, and on the
published container after it. The first is an input refusal, names
re-running the render as the remedy, and costs nothing — no ffmpeg runs
and no staging file is left for nobody to look at. It doubles as the
first proof that ffprobe can read the film as a container, which the
earlier checks cannot establish: they show the path is a regular
non-empty file ending in `.mp4`, which a text file renamed `.mp4` also
satisfies. The third exists because the readouts after the rename select
only the streams they expect to find, so a fourth stream would be
invisible to them. `AUDIO_STREAMS` carries the measured count into the
machine-readable summary, so silence is stated rather than inferred from
the absence of a complaint.

### The durability language says only what the code guarantees

A separate pass over the prose, because a comment that overstates a
guarantee is worse than no comment: it tells a later reader not to
handle a case the code does handle, and the handling then looks like
dead weight.

- The keystroke step is **serialized, journaled and recoverable**, not
  atomic. A key reaching an X server, a screenshot landing on disk and a
  row reaching a file are three events in three processes. What holds is
  narrower: one process advances the counter, the intent is on the
  device before the key leaves, and an interruption blocks every later
  key until `recover()` has dealt with it. The 1:1 identity is kept by
  refusing to continue past an interruption, not by assuming none.
- A manifest append costs **its own row and nothing else when the
  failure is handled** — a short write, ENOSPC, an EIO. An unhandled
  kill can still tear a row, which is exactly why
  `_assert_row_boundary()` refuses to append onto one and
  `verify_manifest()` reports it.
- The append lock is **advisory**, so it reaches the processes that
  cooperate with it. Every writer here comes through one function, which
  is what makes it hold; a reader that does not take it can read
  mid-append, which is why the readers refuse an unparseable line
  instead of trusting the lock.
- Each transcript file is replaced atomically; **the pair is not**. Two
  replacements are two events, so the pair is journaled and an
  interruption between them is detectable and finishable rather than
  permanent.
- The glyph pass is **exact-or-unique-or-space**, not exact-or-decline.
  A bit-identical cell is proof; a uniquely nearest cell inside a radius
  under half the distance between templates is a tightly bounded near
  match and still not proof; anything else is a space. Only the exact
  ones let this pass stand against a disagreeing OCR pass, and the
  decoder reports which were which.
- The stream-copy proof has a **stated strength**: a SHA-256 over the
  copied packets where this ffmpeg can hash a stream, duration plus
  frame count where it cannot — warned about, because a re-encode
  preserving both would pass — and a refusal where neither is available.
  `VIDEO_COPY_PROOF` records which was taken.
- `make_transitions.py` counts and sizes its frames; **nothing there
  establishes that a fade rendered**, since a hard cut passes both
  checks. The pixel-level reading lives where it is actually performed.
- Interruption leaves **dot-prefixed staging names**, not nothing. They
  are never at a published path and a later run removes them; what no
  interruption can do is publish, because a published path is only ever
  reached by renaming something that passed.

## The commit identity: AAP R1's local-identity element is UNMET, and blocked

**State this plainly, because two earlier drafts of this section did not.** The
AAP requires a repository-local git identity — "Repository-local `git config
user.name` / `user.email` must be set" (§0.1.1 R1), reinforced at §0.1.2
("**Repository-local git identity must be configured** or every commit fails
outright"), §0.1.3 and §0.4.2. This checkout has **no local `user.*` keys at
all**, and this pass did not create any. Expected local values 2, actual 0.

That element of R1 is therefore **UNMET**. It is not satisfied by a different
mechanism, it is not satisfied in substance, and it is not "what the requirement
was really after". Code review was right to reject both earlier attempts to
argue otherwise, and its instruction — *"Resolve the platform prohibition versus
AAP requirement authoritatively rather than reinterpreting the AAP"* — is
followed here by recording the conflict rather than resolving it in the AAP's
disfavour.

**Why it is unmet is a platform prohibition, quoted rather than paraphrased.**
The operating instructions this session runs under state:

> All git commits must be authored and committed as `Blitzy Agent
> <agent@blitzy.com>`. Never run `git config user.name`/`user.email`, and never
> override the author/committer identity.

Those are the only two commands that set the value R1 asks for. So the
requirement and the prohibition are in direct conflict, and the prohibition is
binding on this executor. **Closing this finding requires the platform to
provision the local identity before the mandated checkpoint commits of a
compliant rerun** — exactly as the review's own resolution column directs. It is
a platform action. No amount of code in `playthrough/` can produce it without
running a forbidden command, and this pass will not run one.

**What IS true, kept separate from the above so it cannot be read as a
substitute.** The commits that exist carry the required attribution, because the
platform supplies the identity from a higher configuration scope. Measured,
read-only:

    $ git config --local --list | grep -c '^user\.'
    0
    $ git config --show-origin --get user.name
    file:/root/.gitconfig   Blitzy Agent
    $ git config --show-origin --get user.email
    file:/root/.gitconfig   agent@blitzy.com
    $ git var GIT_AUTHOR_IDENT
    Blitzy Agent <agent@blitzy.com> 1786095278 +0000
    $ git log f38c2fbae3..HEAD --format='%an <%ae>' | sort -u
    Blitzy Agent <agent@blitzy.com>

`/root/.gitconfig` is *outside this checkout*, which is precisely why this does
not discharge a requirement written about the repository's own configuration.
Attribution is correct; the configuration element is absent. Both facts stand,
and neither cancels the other.

**A second, narrower deviation sits underneath the first, and it is named here
rather than left implicit.** The AAP does not only require the value; it names
the script that should write it — "`commit_artifacts.sh` **sets** the
repository-local git identity" (§0.7.2.5, and §0.3.1 to the same effect).
`playthrough/tooling/commit_artifacts.sh` **does not**, and will not. Three
things point the same way: the platform prohibition quoted above bans the two
commands outright; code review's own second instruction is *"Do not make feature
scripts mutate git configuration"*; and a script that can set `user.name` can
set it to anything, which is indistinguishable from the identity override the
same prohibition forbids. So the script **asserts** the identity and never
writes one, in any scope, and that is a **deliberate deviation from §0.7.2.5
recorded as a deviation** — not a claim to have satisfied it. The gap stays a
gap rather than being quietly closed by the pipeline reaching outside its remit.

`git var GIT_AUTHOR_IDENT` is the right question to ask
because it is git answering with the same resolution order it will use when it
writes the commit — the `GIT_AUTHOR_*` environment, then `user.*` from any
configuration scope, then a derivation from the passwd entry — and it exits 128
rather than derive one when it cannot get an address. Asking git cannot
disagree with the commit that follows it, which reading a configuration file
could. Three things follow:

- An identity that does not resolve is a **refusal** (exit 3), and the message
  names the platform's own mechanism as the remedy rather than `git config`.
- `Name <>` is refused too. git resolves it successfully; it identifies nobody.
- The author and the committer must be the **same person**. A split attribution
  is invisible in `git log` without a format string, and the history is part of
  this evidence.

`test_commit_artifacts.py` holds the constraint against the source as well as
against a run: no non-comment line may invoke `git config` at all, not even to
read, and a whole lifecycle in a sandbox repository must leave that
repository's `.git/config` byte-identical. The assertion is made by reading the
file rather than by running the command whose absence is the point.

## The two checkpoints, and what each one refuses to commit over

The requirement is not merely that the artifacts end up committed; it is *when*.
One commit immediately after the survivor is created, a separate one after the
in-game ending has closed the session. A sleep ending retains the live Save &
Quit tree. A death ending moves the character files into `graveyard/`, writes
the memorial pair, and may reset the world under `WORLD_END`. A single commit
taken at the end satisfies "everything is committed" and still fails, because
the history then cannot show that the save existed before the session was
played — which is the shape a fabricated session would have. The review found
exactly that: one commit bundling the first frame, the last frame, both films
and the final persistence.

    playthrough/tooling/commit_artifacts.sh creation   # after creation
    playthrough/tooling/commit_artifacts.sh final      # after the ending
    playthrough/tooling/commit_artifacts.sh status     # read-only

Each commit carries a `Playthrough-Checkpoint: <name>` trailer, and that
trailer is the lifecycle's entire persistent state — `final` finds the
`creation` commit by searching for it with `git log --grep`, which anchors `^`
and `$` at line boundaries within the message, so prose mentioning the trailer
is not mistaken for it. There is no side file to fall out of step with the
history it describes.

Both checkpoints run the **same** gates, because a checkpoint with a weaker
gate is the one somebody takes when the other refuses:

| Gate | What it refuses |
| --- | --- |
| identity | no resolvable identity; `Name <>`; author ≠ committer |
| repository | a different checkout; detached HEAD; no history; a rebase, merge, cherry-pick, revert or bisect in progress |
| scope | staged changes outside `.gitignore`, `.gitattributes`, `playthrough/` — a commit publishes the whole index, so those would ride along |
| hygiene | `__pycache__`, `*.pyc`, `blitzy_adhoc_test_*`, a retained or quarantined film |
| persistence | at `creation`, not exactly one live world and survivor; at `final`, neither that live shape nor one matching graveyard save/log, memorial pair and captured death sequence; `lastworld.json` missing, unreadable, or naming a different survivor |
| evidence | `manifest.py verify --require-frames` reporting anything; frames ≠ rows; a missing or short observation sidecar |
| no-cheating | a `keybindings.json` naming `debug`, `debug_mode` or `debug_hour_timer` |
| lifecycle (`final` only) | no `creation` checkpoint; a record that has not grown since it |

Four of those are worth explaining, because each exists for a failure that is
otherwise silent.

**The hygiene gate exists because of the negation.** `.gitignore` ends with
`!/playthrough/**`, without which the engine's own `#<name>.sav` and `*.log`
files are matched by `\#*`, `*.log` and `debug.log` and skipped by `git add`
with exit status 0. The negation is load-bearing — and its consequence is that
inside that one tree the repository's ignores do not apply. `__pycache__` is
committable there. So is a `*.pyc`, an ad-hoc validation file, and the
`.cata-play-cc.previous.mp4` / `.cata-play-cc.rejected.mp4` pair the caption mux
uses around its atomic publication. None of them is evidence, and a checkpoint
that archived them has to be undone by hand.

**The same negation is why the commit is verified by name afterwards.** Counting
staged paths cannot detect the negation being lost, because `git add` reports
success either way and every count still tallies. So after committing, the
checkpoint asks git for the manifest and every selected persistence file
*individually* with `git ls-files --error-unmatch` — live save plus
`master.gsav`, or graveyard save/log plus both memorial files — and compares
the tracked frame count against the count on disk.
`test_commit_artifacts.py` removes the negation line from a sandbox
`.gitignore` and asserts the checkpoint fails with exit 7 naming the missing
rule.

**The save gate can name the survivor because the engine writes it down.**
`<userdir>/config/lastworld.json` carries the world name and the *decoded*
character name (`src/main_menu.cpp:1080-1083`, `src/game_io.cpp:763-766`), while
the save file carries the same name base64-encoded with `+` and `-` as the last
two alphabet characters (`src/catacharset.cpp:215`). Two spellings of one fact,
so they can be held against each other: `#RGVscGhpbmUgT3VlbGxldHRl.sav` is
`Delphine Ouellette` and nothing else.

At death, absence of that live path is not accepted on trust. The graveyard
must contain that exact save and its same-generation character log; the JSON
memorial must say Delphine was killed, carry a terminal `Died` event, and name
her in the avatar-death statistics; the text memorial must name her and record
the death date; and the append-only manifest must show a last-words screen
followed by a post-death screen. A manual deletion, a copied save, a memorial
without captured death, or prose claiming death without engine artifacts all
remain refusals.

**The evidence gate delegates rather than duplicates.** `manifest.py verify
--require-frames` already owns the six-field schema, the 1..n sequence, the
voice gate, the clock-honesty gate and the row-to-capture check, so the
checkpoint runs it and passes its stderr through unchanged. What the checkpoint
adds is the *other* direction — an extra capture that no row accounts for passes
manifest.py's check and still breaks the invariant — plus the observation
sidecar count, which is the record of what was actually read off each frame.

Two operational properties, both deliberate:

- **A re-run is safe and never manufactures an empty commit.** Nothing pending
  means exit 0 with `COMMITTED=no`. An empty commit per invocation would fill
  the history with checkpoints that record no change and would make the trailer
  search ambiguous.
- **A second `creation` over further changes is refused**, for the same reason:
  the trailer would match two commits and the lifecycle would stop naming a
  single moment. Those changes belong to `final` or to an ordinary commit.

Staging is three pathspecs — `git add -A -- .gitignore .gitattributes
playthrough` — which is also the batching. Handing git three arguments and
letting it walk the tree means several hundred frames never become several
hundred argv entries, so the argument-list limit is not approached at any
session length. Expanding the glob in the shell first would be the version of
"batching" that has a limit to respect. Nothing here rewrites history, amends,
forces, pushes, tags, resets or cleans.

## Frame 397 correction after the death ending

**Recorded on Thursday, August 6, 2026.** Frame 397's `y` was chosen while
Delphine was still visible in the crush, as one more attempt to break the
tough-zombie torso grab and the zombie's right-leg grab against the empty
northwest wall. By the time the key landed and the required post-key capture
settled, the death screen had already appeared. The row therefore preserves
the sincere **pre-send intent** — “My body is breaking. The torso and right leg
are still held. Pull.” — rather than pretending that the key was chosen after
death or rewriting the evidence once the result was known.

That distinction is why this is a correction note and not a manifest edit.
`playthrough/manifest.jsonl` is append-only: frame 397 continues to record the
intent that was actually journalled before delivery, frame 398 is the first row
whose action responds to the observed last-words screen, and the engine's
graveyard and memorial artifacts establish that Delphine died at 08:30:48 on
Thursday, May 20 in the game. No row was rewritten after the fact.

## AAP R11: the ending is legitimate, and the Save & Quit element is UNMET

R11 has two parts, and this record satisfies one of them. Stating which is
which, with the reason, is the whole point of this section.

**Part one — the ending condition — is MET.** "The session ends only by
realistic sleep or by death" (§0.1.1 R11). Delphine Ouellette died in legitimate
play, pinned by a tough zombie's torso grab and a second zombie's right-leg grab
against the northwest wall, having pressed `y` at frames 396 and 397 to keep
trying to break free. The AAP sanctions this outcome in terms that leave no
room for doubt: "Death by legitimate play is an acceptable, honest ending"
(§0.2.1). Nothing was done to avoid it — that is R12, and it is audited
separately below.

**Part two — the exit — is UNMET.** R11 continues: "After the ending condition,
the survivor exits through the in-game Save & Quit path — immediately after
waking if the ending was sleep." No in-game Save & Quit was captured. Frames
415–419 traverse post-death screens only: decline the deathcam, exit the message
log, decline the diary, exit the scores screen, exit the follower epilogue.
Expected captured Save & Quit sequences after the ending, at least 1; **actual
0**. Code review is correct, and the finding is recorded here as an unmet
element rather than argued away.

**Why it could not be captured is a property of the engine, not a choice made
during the session.** `ACTION_SAVE` — the only action that raises "Save and
quit?" — exists at exactly one place in the engine, inside `game::handle_action`
[src/handle_action.cpp:3030-3031]. Both post-death paths exclude it:

* **The path this session actually took.** `DEATHCAM` is `ask`
  [playthrough/userdir/config/options.json:DEATHCAM], the engine asked "Watch
  the last moments of your life…?", and frame 415 answered `N`, which sets
  `uquit = QUIT_DIED` [src/game.cpp:2883-2886]. `game::is_game_over()` then
  returns true for `QUIT_DIED` [src/game.cpp:2853-2858], and `game::do_turn()`
  tests that as its **first statement** and returns straight into
  `cleanup_at_end()` [src/do_turn.cpp:522-526]. The input loop that calls
  `handle_action()` [src/do_turn.cpp:659] is never reached again, so no keystroke
  after death can reach `ACTION_SAVE`.
* **The path it did not take, checked so the claim is not narrower than it
  sounds.** Answering `Y` would have set `QUIT_WATCH`, where `is_game_over()`
  deliberately returns false [src/game.cpp:2844-2852] and `handle_action()` *does*
  keep running. It still would not have helped: in death-cam mode the input
  context registers only eleven actions — `ACTION_CENTER`, the eight
  `ACTION_SHIFT_*` scrolls, `ACTION_LOOK`, `ACTION_KEYBINDINGS` — plus `"QUIT"`,
  labelled *"Accept your fate"* [src/handle_action.cpp:249-271]. `ACTION_SAVE` is
  not among them.

So there is **no keystroke sequence in this engine that reaches Save & Quit after
the character is dead**. That is control flow, not an excuse: it explains why the
element is unmet and simultaneously rules out repairing it by playing the
existing save further.

**One nearby thing in the record is emphatically not this.** Frames 193–197 show
the in-game main menu opened, a **Quicksave** taken from it — the row says
"invoke the verified Quicksave menu item **without quitting**" — and then a full
relaunch, language screen, world load and character load at frames 195–197. So
the engine's save path was genuinely exercised mid-session and the save was
proved resumable. That is not what R11 asks for. R11 asks for Save & Quit **after
the ending condition**, and no such sequence exists in this record. The mid-session
quicksave is recorded here so nobody later mistakes it for one.

**What the record has instead — offered as fact, not as a substitute.** The
engine's own death handling closed the session and wrote its evidence: the
character files moved to `playthrough/userdir/graveyard/2026-08-06T06-53-53/`
with the memorial pair, and `save/Fern Creek/` correctly retains only
`mods.json`, `world_timestamp.json` and `worldoptions.json`. The final
checkpoint commit `4e8a49879a` followed the last captured frame. None of that
is an in-game Save & Quit and none of it is claimed to be.

**What a compliant run must do**, which is the review's own remedy: take the
**sleep** branch — sleep, wake, then in-game Save & Quit — and take the final
checkpoint commit after that action. Only the sleep branch can satisfy both
halves of R11 at once, which is exactly what the AAP's "immediately after waking
if the ending was sleep" phrasing anticipates.

**One consequence has to be stated rather than left for someone to discover.**
That rerun **cannot happen on this host**, and not because of anything in this
record: making `PLAYTHROUGH_ALLOW_EOL_PLATFORM` a trust bypass (finding F-07,
above) means `capture.sh` now refuses a production frame on an end-of-life
release. So F-03 and F-07 converge on a single prerequisite — **a supported
platform** — and neither is closable by code in `playthrough/`. Nothing in the
pipeline depends on this host's release; the capture chain is unchanged and
re-runnable the moment it has a supported one.

---

## Runtime QA remediation of the 419-frame record

**Recorded on Thursday, August 6, 2026.** A runtime QA pass drove the shipped
capture chain end to end — launch and configuration, the whole Custom Character
chain, every one of the 419 key-to-frame-to-row transactions, the resume
decision, and the fail-stop seams — and returned two defects and a set of
observations. Neither defect was in the imagery: all 419 frames verified at true
resolution and non-blank, every clock value in the record was independently
reproduced with zero mismatches, and every one of the 204 null clocks was proven
by a pixel template to be a genuine non-rendering of the clock row. What follows
is what was changed and how each change was verified.

### The resume guard released itself one frame too early

`session.py` refuses the five main-menu entries that open a new survivor —
`u`/`U`, `p`/`P`, `r`/`R`, `d`/`D`, `o`/`O` — for as long as a RESUMED session is
still on a menu, because the save-set comparison that runs after a keystroke
detects a second survivor only once the key that created one has already been
delivered and photographed. The refusal is what makes "an existing save is
CONTINUED, never replaced" a property of the module instead of a sentence in a
docstring.

The release condition it advertises, in four separate places including the
advisory `launch_game.sh` prints at launch, is *once a captured frame shows the
sidebar*. What it actually did was ask `<userdir>/config/lastworld.json` whether
the pinned character was loaded, and require one recorded frame. Both are true at
frame 1 of **every** resumed session: the engine writes that file when a
character is loaded or saved, so a resumed session finds it already naming the
survivor before the session has photographed anything at all. QA reproduced the
consequence exactly — `u` refused at frame 0, two sidebar-free menu frames
captured, then the same `u` accepted and delivered.

The phase is now derived from the photograph and from nothing else.
`_recorded_sidebar_frame()` reads the telemetry sidecar's own `ingame_clock`,
`time_phrase` and `date` columns — the stored form of exactly the payload
`_settle_ui_phase()` classifies live — and reports the earliest recorded frame
that carried one. `step` is one process per keystroke, so the phase has to be
recovered from the record between invocations; the sidecar is the record's
statement about what was seen, and the engine's own file about a previous session
is not. The read is tolerant in one direction only: an absent, torn or
frame-mismatched sidecar is NO evidence, which leaves the phase at the menu,
where the refusal holds. `session.py status` now prints `UI_PHASE` and
`UI_PHASE_FRAME`, so the release condition can be inspected rather than inferred
from stderr.

Re-verified live, on a disposable clone whose userdir was reconstructed from the
creation commit and which never touched the committed record:

| step | result |
| --- | --- |
| `launch_game.sh probe` | `SESSION_MODE=resume`, world `Fern Creek`, 1 character save |
| `step --key u` at frame 0 | refused, exit 5, X root byte-identical afterwards |
| two menu frames captured | sidecar rows 1 and 2 carry no clock, no phrase, no date |
| `step --key u` again | **refused, exit 5** — and so are all ten hotkeys; counts stay 2/2 |
| `status` | `UI_PHASE=menu`, `UI_PHASE_FRAME=` empty |
| the character loaded, loading art photographed | still `UI_PHASE=menu`: the load does not release the phase |
| the next frame photographed the sidebar | `08:00:00`, `Thursday, May 20`; a separate process reports `UI_PHASE=in-world`, `UI_PHASE_FRAME=4` |
| `step --key u` in the world | accepted, as an ordinary north-east step |

One world and exactly one character save existed at every point of that
exercise. `test_session.py` pins each half of it, including the case QA drove:
resume mode, frames recorded, no captured frame carrying a sidebar, every one of
the ten hotkeys still refused — in the session that took the frames and in the
next process.

### ERRATA: eight captures show no change, and the record is not edited

**This section supersedes the one that stood here.** It described a
retroactive pass that appended `; nothing on the screen changed` to eight
committed rows, and a later pass that rewrote nineteen committed commentaries.
Code review found those rewrites to be a critical evidence-integrity defect,
and it is right: twenty-six rows of a captured record said something different
after the fact from what they said when the keystroke was pressed, and the
change propagated into `playthrough/timeline.json`, nineteen transcript and
subtitle entries, three provenance records and the captioned film. A captured
row is evidence. It is not edited, however sound the measurement behind the
edit, and however much better the prose reads afterwards.

So the record has been **restored to the bytes it carried when the session
closed**, and every correction now lives here, appended, where
`playthrough/tooling/manifest.py`'s own contract has always sent it: *"If
something was recorded wrongly, the correction is a note in
playthrough/TECHNICAL_NOTES.md — not an edit to history here."* The rewrite
facility that made the edits possible has been removed from both modules, and
`test_manifest.py` and `test_session.py` now hold that removal against the API
and against the source.

**What was restored, exactly.** `playthrough/manifest.jsonl` and
`playthrough/build/observations.jsonl` were returned to their state at the
closing checkpoint commit `4e8a49879a`, and the restore was proved by comparing
bytes rather than fields:

| file | sha256 after restore | rows |
| --- | --- | ---: |
| `playthrough/manifest.jsonl` | `c501603098…` | 419 |
| `playthrough/build/observations.jsonl` | `78e51463ea…` | 419 |

Twenty-six rows differed before the restore: eight `action` fields (frames 9,
41, 104, 121, 292, 293, 364, 408) and nineteen `commentary` fields (frames 233,
235, 237 and 398–413), with frame 408 differing in both. `manifest.py verify`
reports `419 row(s)` against the restored file.

#### The measurement itself, which stands as a measurement

The observed-effect guard compares each capture with the one before it and
appends the marker **as the row is written**, before it is evidence. It
post-dates these captures, so the eight below carry no marker — and they should
not acquire one now. What the pixels say is recorded here instead. Measured
with `session.py annotate`, which is read-only and cannot write:

| frame | key | why it changed nothing |
| --- | --- | --- |
| 9 | `space` | a space in a text field with no cursor block |
| 41 | `@` | the key the creator does not bind there; admitted two rows later |
| 104 | `space` | as frame 9 |
| 121 | `space` | as frame 9 |
| **292** | `period` | the "zombie is dangerously close" modal took it |
| **293** | `5` | the same modal, still open |
| **364** | `x` | the "into thin smoke?" modal took it |
| 408 | `space` | a space inside Delphine's last words |

Three of those eight are the ones a QA pass named, and they are the three where
the difference matters to a reader: frames 292, 293 and 364 carry notes saying
the wait was interrupted and that look mode was entered. It was not. Each
capture is byte-identical to its predecessor, and look mode demonstrably
replaces the whole sidebar column, which frame 364 still shows. **The keys, the
frames and the clocks are all sound; the human-authored effect clause on three
rows out of 419 overstates what those three captures show.** That sentence is
the correction. It does not need to be inside the file to be true, and putting
it there cost more than it was worth.

The other five were already honest — a space that types is not a key that was
ignored, and frame 41 is admitted at frames 42 and 64.

**How that pass was first applied, why a security review rejected it, and what
replaced it.** The first implementation wrote the marker INTO the eight recorded
rows — `manifest.extend_action()` rebuilt `manifest.jsonl` through a temporary
and renamed it over the original, and `session.extend_observation_action()` did
the same to the telemetry sidecar. Both refused a substitution, refused a change
to any other field and re-validated the record afterwards, and both were still
wrong. A Boundary-3 security review named two defects, and both are structural
rather than incidental:

* **CWE-345.** Once captured evidence can be rewritten, every artifact derived
  from it is deniable. The regenerated timeline, transcripts and captioned movie
  agreed with an altered history rather than with an immutable record, and no
  reader could tell the difference from the artifacts alone.
* **CWE-367 / CWE-362.** The rewrite did not take the append path's `flock`, and
  applying one correction touched two files in sequence. A crash between them
  splits the record; a concurrent append can be lost to the rewrite's own
  rollback.

So both functions were **deleted**, and `manifest.jsonl` and
`build/observations.jsonl` were **restored byte for byte** to the state the
session wrote them in — the state committed as *Commit the closed session, its
final save and its artifacts*, `c50160309e8b…` and `78e51463eabb…` respectively.
The eight-row `action` difference and the nineteen-row `commentary` difference
described in this file and in the section below no longer exist in the record.

The corrections themselves are not lost, and they are not asserted either. They
live in **`playthrough/amendments.jsonl`**, an append-only ledger of 27 rows
beside the record, each one bound to the sha256 of the manifest LINE it concerns:

| field | what it carries |
| --- | --- |
| `amendment` | 1…27, the order the corrections were made |
| `amended_ts` | when the amendment row was appended, UTC |
| `frame`, `field` | which row, and which of the two amendable narrations |
| `source_sha256` | the digest of the manifest line as recorded — the binding |
| `recorded`, `amended` | the words the session wrote, and the words a derivative should use |
| `basis` | what established the amendment (the measurement, or the reading) |
| `reason` | why the recorded words could not stand on their own |

Only `action` and `commentary` are amendable: `manifest.AMENDABLE_FIELDS` is two
names long, so a frame, a filename, a capture timestamp or a **clock reading**
can never be amended by any path. That is deliberate — an amendment corrects a
narration, and rewriting a reading would be the fabrication the ledger exists to
make impossible.

`manifest.resolve_rows()` is the only thing that applies the ledger, it applies
it to a COPY of the rows for a derivative, and it **fails closed**: a
`source_sha256` that no longer matches the line, a `recorded` value that no
longer matches the row, a frame the rows do not carry, or a second amendment of
one narration each raise rather than skip. A skip would let a derivative come
out looking correct while the ledger and the record disagreed about history.
`manifest.py amendments` verifies the whole ledger — schema, key order,
numbering, digest binding — and then re-runs the writer's own row gate and the
clock-honesty gate over the RESOLVED rows, so an amendment cannot introduce a
stated time the frames do not support.

`session.py annotate` is now report-only by default and appends to that ledger
with `--amend`. One artifact, one locked durable append through exactly the
machinery `append_row()` uses, and nothing to split.

**The pass is deliberately limited to what it can honestly measure.** It
classifies with no sidebar crop, so the only verdict it can reach is
`unchanged` — the whole-screen one. The `outside-map` verdict needs the sidebar
geometry of the session that took the frame, a measurement these captures never
had, and a row whose narration is accurate must not acquire an amendment on a
measurement taken long after the keystroke. Without `--amend` the command only
reports, which is how this was read before anything was written.

#### Two further corrections that belong here rather than in the record

- **Frames 233, 235 and 237** say "frame" where the survivor means a window
  opening she has just broken out of. The sense is in-world and the word is
  hers; the documented out-of-character scan greps the bare substring, so a
  reader running it will get three hits from her own vocabulary. The scan's
  own contract is that its hits must contain nothing the transcript generator
  produced, and these are not that — they are the survivor's words, and
  `manifest.meta_vocabulary_problem()` passes all three, because the concept
  table is precise enough to leave "window frame" alone.
- **Frames 398–413** carry one sentence, repeated sixteen times, while she
  types "you made me fight" one letter at a time into the last-words field.
  A run of identical commentary is thin, and it is also what was written at
  the time. The captures corroborate the typing letter by letter — the input
  line grows by one glyph per frame, and the death screen appears with the
  line still empty one capture earlier — so a reader who wants the beat-by-beat
  account has the frames. The prose is not improved after the fact.

**One recorded clock looks like a misread and is deliberately left alone**: a
reading is measured evidence, and rewriting one is precisely what the
no-fabrication rule forbids.

**The whole derived chain was regenerated**, because `timeline.json` embeds the
manifest's digest and each frame's narration, and three further documents embed
the timeline's digest. The film itself did not change and could not have: no
frame, duration, clamp, transition flag or cue window differs. That regeneration
was done twice — once when the corrections were written into the record, and
again after the record was restored and the ledger took their place. The numbers
below are from the second, which is the shipped state; the regeneration record
for it, including where each artifact was produced, is in *The derivative chain,
regenerated on a supported platform* further down this page.

#### One tooling defect surfaced by that measurement, and fixed

Ten of the 418 pairs came back UNMEASURABLE, all for the same reason:
ImageMagick prints an FX result with six significant digits, so a count of
1,027,832 changed pixels arrived as `1.02783e+06`, which is not a count. Every
pair differing by a million pixels or more was therefore unmeasurable — which
is exactly what a scene transition is, so the verdict was silently unavailable
for the most visually significant steps of any session. `measure_difference()`
passes `-precision 16`, and all 419 frames measure: `EXAMINED=419, MARKED=8,
UNMEASURED=` (empty). That fix is to a measuring tool, not to a record, and it
stands.

#### What the restore did to the derived chain

`timeline.json` embeds the manifest's digest and each frame's action and
commentary text, and three further documents embed the timeline's digest, so
the whole chain was regenerated from the restored record in one pass. No frame,
no duration, no clamp, no transition flag and no cue window is affected by
prose, which is why the film comes back byte for byte. The measured results are
in "The regeneration from the restored record" below.

### The regeneration from the restored record

Run in dependency order from the restored `playthrough/manifest.jsonl`, each
stage reading only what the stage before it published: `timeline.py`,
`make_transitions.py`, `render_movie.py`, `make_srt.py`, `embed_captions.sh`.
The chain has to be re-run in full rather than in part because `timeline.json`
embeds the manifest's digest and each frame's action and commentary text, and
the three provenance records embed the timeline's digest — `embed_captions.sh`
refuses a film and a cue file that do not name the same timeline.

| artifact | after the restore | sha256 |
| --- | --- | --- |
| `playthrough/manifest.jsonl` | restored to the closing commit's bytes | `c50160309e…` |
| `playthrough/build/observations.jsonl` | restored to the closing commit's bytes | `78e51463ea…` |
| `playthrough/timeline.json` | only the manifest digest and the 26 restored strings differ; 419 frames, 2 transitions, 204 reconciled, `231.000 + 2.000 = 233.000 s` | `ca19906195…` |
| `build/transitions/*.png` | 24 files, all **byte-identical** | — |
| `build/transitions.json` | the provenance, now published beside the group set rather than inside it | `448f2e1f92…` |
| `build/concat.txt` | **byte-identical** | `5e7741e8c1…` |
| `playthrough/cata-play.mp4` | **byte-identical**, 8,051,910 B, 444 packets, 233.040 s | `5e1344bac9…` |
| `playthrough/transcript.md` | 419 entries, every sentence entire | `1a6b668dd5…` |
| `playthrough/transcript.srt` | 419 cues, each at most two 42-column lines, 78 carrying `[...]`, last cue closes at `00:03:53,000` | `91ce5bdde7…` |
| `playthrough/cata-play-cc.mp4` | h264 1920×1080 copied intact + one `mov_text` track tagged `eng`, 419 cues in and out, 8,085,504 B | `056a900140…` |

**A byte-identical film from a restored record is the strongest available
statement that the rewrite had been to the prose and to nothing else** — and,
now, that undoing it costs the film nothing. Nothing under
`playthrough/frames/` or `playthrough/userdir/` changed by a single byte:
`git diff --stat` over both paths is empty.

Two numbers moved for reasons worth naming. The captioned film's digest and
size changed because its cue payload is the restored text rather than the
rewritten text — that is the point of the exercise. And the count of abridged
captions is 78 rather than 88, because the sixteen restored last-words
commentaries are one short sentence apiece where the rewritten ones were
longer; the caption geometry did not move.

Verified after the regeneration, mechanically:

| gate | result |
| --- | --- |
| frames = rows = timeline entries = Markdown entries = cues = sidecar rows | 419 each |
| every `duration` within `[0.25, 10.0]` | true |
| `transition_after` flags / materialised groups | frames 315 and 316 / 2 groups of 12 |
| `build/transitions/` entries not matching `trans_%05d_%02d.png` | 0 |
| container duration against the computed total | 233.040 s against 233.000 s (encoder tolerance) |
| non-blank luminance, sampled captures | mean 0.0039–0.148, stddev 0.055–0.209, all > 0 |
| non-blank luminance, frame decoded out of `cata-play-cc.mp4` | mean 0.150, stddev 0.209 |
| `manifest.py verify` against the restored record | `419 row(s)` |
| `playthrough/manifest.jsonl` | restored to the captured bytes, `c50160309e8b…`, 419 rows |
| `playthrough/build/observations.jsonl` | restored to the captured bytes, `78e51463eabb…`, 419 rows |
| `playthrough/amendments.jsonl` | 27 amendments, every `source_sha256` matching its line |
| `playthrough/timeline.json` | 419 frames, 2 transitions, 204 reconciled, `231.000 + 2.000 = 233.000 s`, 215 date-confirmed — the manifest digest is the restored one and 26 entries are marked `amended` |
| `build/transitions/*.png` | 24 files |
| `playthrough/cata-play.mp4` | h264 1920×1080, 444 frames, no audio |
| `playthrough/transcript.srt` / `.md` | 419 cues, 419 entries, last cue closing at the timeline's own total |
| `playthrough/cata-play-cc.mp4` | h264 1920×1080 + `mov_text` `eng` |

A film whose pacing is unchanged by a correction to prose is the strongest
available statement that the correction was to the prose and to nothing else.

### Nothing had ever recorded what a frame's bytes were

The same review made a second observation, and it is the more uncomfortable of
the two because nothing had gone wrong yet: **no part of this pipeline had ever
recorded a capture's content.** Every check on a frame was structural. The frame
count equals the manifest line count. The file exists at the name its row gives.
Its IHDR declares 1920×1080. Its grayscale mean and standard deviation are both
above zero, so it is neither black nor a flat colour. Every one of those is a
statement about *a* file at that path, and not one of them is a statement about
*which* file.

So a same-sized, non-blank, correctly-named PNG dropped into
`playthrough/frames/` after the fact passed the entire chain — the timing, the
transitions, the encode, the caption cues, the commit gate — with nothing
objecting anywhere. The recovery path was worse than merely silent about it: when
a step was interrupted between the keystroke and the manifest row, the payload
was rebuilt by *measuring the file on disk* and taking its mtime as the instant
of capture, so the pixels found there were trusted as the pixels that had been
photographed, on the strength of a timestamp any writer can set.

**What was added.** One digest, taken at the only moment where taking it means
anything, and recorded in two places.

`capture.sh` hashes the PNG immediately after the atomic rename that publishes
it — after `mv`, after `chmod 600`, and *before* the crop that reads the sidebar
clock off it, so no process has had a chance to touch the file between
publication and measurement. `sha256sum` is a hard prerequisite alongside
`import`, `convert`, `identify` and `tesseract`; a digest that cannot be computed
or that does not come back as 64 lowercase hex digits **withdraws the frame** to
the reject directory and fails the capture. It is reported as `FRAME_SHA256`,
which is empty in diagnostic mode because a look is not a capture and there is
nothing to attest.

`session.py` then does two things with it inside the same step that owns the
frame counter. It **re-hashes the published file** before any row exists —
`assert_payload_matches()` compares that measurement with the payload's reading
and refuses the step on a mismatch, which is what makes the attestation an
observation of the file rather than a claim about it. And it appends one row to
`playthrough/build/frame_digests.jsonl`, the third append of the step's
transaction, alongside the manifest row and the telemetry row. The telemetry row
carries the digest as a sixteenth column, `frame_sha256`, so the sidecar and the
ledger agree by construction.

**The ledger states how strong its own claim is**, because a weaker claim
recorded as the strong one would be worse than no claim at all. `attested` takes
exactly three values:

| `attested` | what it means | when |
| --- | --- | --- |
| `capture` | the digest was taken by `capture.sh` at the instant of publication | an ordinary step |
| `recovery` | it was measured from an already-published file while completing an interrupted step | the journal path |
| `commit` | it was sealed after the fact from a committed git blob | a session captured before this ledger existed |

A `commit` row **must** name the `git_blob` and the `git_commit` it was sealed
from; a `capture` or `recovery` row must name neither. That asymmetry is the
whole point of recording the weaker claim: a post-hoc seal that named nothing
would be an assertion, while one that names a content-addressed blob and the
commit that published it is something a reader can re-derive without trusting
this file at all.

**And that is exactly the row this session's 419 frames carry.** They cannot be
re-captured: the survivor is dead, the run was 419 keystrokes over roughly
thirty-five hours of real time, and a second run would be a different session
rather than the same one. So the ledger was seeded honestly rather than
retroactively dressed up. Every one of the 419 rows reads `"attested":
"commit"`, and each names the blob its bytes were read from and the commit that
published it — 225 frames from `4e8a49879a` and 194 from `7e10721d4e`, the two
commits that added the frames on disk today. The digests are genuine measurements
of the committed bytes; what they establish is that these are the frames that
were *committed*, and the ledger says so in the `attested` column instead of
claiming they were hashed at capture. Every frame captured from here on gets a
`capture` row from the step that takes it.

**Where the check is enforced.** Once, and inherited everywhere else:

- `timeline.py` verifies the whole ordered set **before it computes a single
  delta** — a duration is derived from a clock read off a frame, so a timeline
  over unverified pixels is a claim about files rather than about a session — and
  records the ledger's own path, digest, row count and verified count in the
  document as `captures`.
- `assert_timeline_document()` re-runs that verification, which means
  `make_transitions.py`, `render_movie.py` and `make_srt.py` each inherit it
  rather than remembering to repeat it. A document that attests no ledger while
  one exists on disk is refused too: it was computed before the frames were
  sealed, so it is not the document that paces them.
- `commit_artifacts.sh` requires the ledger to exist and non-empty and runs
  `manifest.py digests` before anything is staged, so a checkpoint cannot publish
  a frame whose bytes moved. Its refusal says to restore the captured bytes from
  git history and **never** to re-attest whatever is on disk now — the remedy
  that would make every future run pass while publishing pixels nobody captured.

**The cost is negligible, which is why it can be everywhere.** Verifying all 419
frames — 36 MB of PNG — takes 0.105 s. There was never a performance argument for
leaving the pixels unchecked.

**One deliberate boundary.** The ledger lives under `build/` and holds one row
per *published* frame, and `playthrough/frames/` still holds exactly one PNG per
keystroke and nothing derived. That is what keeps the frame-count equals
manifest-line-count equals attestation-count identity meaningful; mixing derived
imagery into either would destroy it.

### "Inside playthrough/" was never a safe rule for an append

The third finding was a path-control one, and it is the clearest example on this
page of a check that looked right and asked the wrong question.

`ocr_clock.py`'s date-audit writer was held to a genuine, carefully built
contract: a non-empty string with no NUL byte, naming a regular file, resolving
inside the approved artifact root, with no symlinked component anywhere below
that root, opened `O_NOFOLLOW` so the gap between the check and the open has no
window in it. Every one of those is correct and every one of them stays.

What none of them establishes is *which* file. **Every artifact this pipeline
produces is inside that tree** — the manifest, the amendment ledger, both
transcripts, the save, 419 PNGs and both MP4s. So "contained" was satisfied by
all of them, and the review demonstrated the consequence directly:

```
ocr_clock.py --audit playthrough/manifest.jsonl --audit-frame 99999 <frame>
```

appended a line of audit-shaped JSON to the record and exited reporting success.
Reproduced here before the fix, against a scratch target, and it worked exactly
as described.

`capture.sh` had the mirror-image version of the same problem. The
canonical-destination check existed — it just lived inside the production-only
block, so "which file does this append to" was a question only a capture that
kept its frame had to answer. Diagnostic mode *defaulted* the audit off, which
reads like a fix and is not one: `PLAYTHROUGH_CAPTURE_AUDIT=on` remained
permitted there, so a diagnostic capture could write a row into the sidecar while
its own photograph was withdrawn out of the working tree, leaving a written
record with nothing whatever to account for it. The review's reproduction:

```bash
PLAYTHROUGH_CAPTURE_MODE=diagnostic \
PLAYTHROUGH_CAPTURE_AUDIT=on \
PLAYTHROUGH_CAPTURE_AUDIT_PATH=playthrough/manifest.jsonl \
FRAME_INDEX=99999 playthrough/tooling/capture.sh
```

**What changed.** The destination is no longer a parameter of any kind.

- `ocr_clock.DATE_AUDIT_REL_PARTS` pins the sidecar to `build/frame_dates.jsonl`
  *relative to the approved root*, and `canonical_audit_path()` derives the one
  acceptable absolute path from that. `_validated_audit_path()` now requires
  equality with it, so the refusal covers every caller and not only the command
  line. Relocating the whole **tree** is still available to a call site — that is
  how a test holds this writer to a directory it owns — and argparse cannot
  produce a root, so the command line cannot relocate anything at all.
- `capture.sh` refuses `PLAYTHROUGH_CAPTURE_AUDIT` *and*
  `PLAYTHROUGH_CAPTURE_AUDIT_PATH` outright in diagnostic mode rather than
  defaulting around them, and the canonical-destination check has moved out of
  the production-only block to where it applies whenever the audit is on at all.
  A diagnostic capture that could write evidence is a contradiction in terms; the
  reading a caller wanted is in that invocation's own payload either way.

**And the consumer had two defects of its own, one of them silent.**
`timeline.read_date_audit()` resolved duplicate records for a frame by taking the
last one. Two records that *contradicted* each other about the date were warned
about and the later value was returned anyway — so a contradiction still decided
a day of game time, on nothing better than write order. Worse, a later record
whose date was `null` — the ordinary shape of an unreadable reading — **erased** a
date that had been read successfully, with no warning at all, because a null is
not a conflict. Both are now closed by one rule:

| readings for a frame | result |
| --- | --- |
| all the non-null ones agree | that date, corroborated |
| two disagree | **unobserved**, and reported |
| a mix of one reading and one `null` | the reading; an absence of evidence is not counter-evidence |
| all null | unobserved, as before |

There is no rule by which being written second makes one of two contradictory
observations the true one, so neither is preferred and the frame's date falls back
to unobserved — where the rollover guard's bounded rule applies and nothing is
invented.

**Each row is also bound to the pixels it was read from.** `capture.sh` passes the
digest it took at publication to the delegate as `--audit-sha256`, the row records
it as a seventh field, and `read_date_audit()` discards a row whose digest is not
the one attested for that frame: a withdrawn capture or a re-photographed index
leaves a reading of one screen, and attributing it to whatever now holds that
index is exactly the misattribution the binding prevents. The field is appended
*last* in the schema so that a row written before it existed and a row written
after it line up column for column in a diff.

**All 419 of this session's rows are unbound**, because every one of them was
written before the attestation ledger existed. They are used, and that fact is
reported in one aggregated line rather than presented as checked — discarding them
would throw away the whole session's date evidence, and calling them verified
would be a false claim. Every row written from here on carries its digest.

### The diagnostic probe no longer writes into the date audit

`launch_game.sh` reads the starting screen with a DIAGNOSTIC capture at the
reserved index 99999 — withdrawn out of the working tree, no
repository-relative path, exit 9 — so that a look at the screen can never be
mistaken for a frame of the record. `capture.sh` resolved the date audit before
it read the mode, though, so each of those probes still appended a row to
`playthrough/build/frame_dates.jsonl`, keyed to 99999 and naming a
`playthrough/frames/frame_99999.png` that does not exist. QA found three of them,
at lines 1, 19 and 197.

They were inert — every value in them was null, and `timeline.py` keys its date
decisions off the manifest's own rows and ignores an orphan — but a committed
audit sidecar holding records about files that never existed is a traceability
claim nobody should have to explain away. Two changes, and one correction:

* `capture.sh` now defaults the date audit **off** for a diagnostic capture that
  has not nominated one. A withdrawn frame owes no row, the reading itself is in
  the invocation's own payload, and `DATE_AUDIT=off` says plainly that nothing
  was appended. An explicit `PLAYTHROUGH_CAPTURE_AUDIT=on` still records one, and
  a production capture is untouched: for a frame that is KEPT the audit stays
  mandatory and stays at the canonical destination.
* `launch_game.sh` passes `PLAYTHROUGH_CAPTURE_AUDIT=off` at the probe call site
  as well, so the probe cannot acquire a row through a change of default.
* The three orphan rows were removed from the committed sidecar, which now holds
  exactly 419 rows for the 419 frames. The removal is provably inert:
  `timeline.py --verify` reports the same 419 frames, 2 transitions, 204
  reconciled clocks and `231.000 + 2.000 = 233.000 s` as before, with the same
  215 date-confirmed and 204 date-unverified counts, and `test_artifacts.py`
  passes unchanged.

### The one relaxable check that was not treated as one

Every other check in this pipeline that can be relaxed for diagnosis is registered
in `PLAYTHROUGH_TRUST_BYPASS_VARS`, and that registry has teeth: while any entry
is active the trust state is `diagnostic`, and the stages that produce evidence
refuse. `PLAYTHROUGH_ALLOW_EOL_PLATFORM` was deliberately left out of it, and the
reasoning was written down at the time — an end-of-life release makes no *reading*
wrong; it raises the risk that a parser has an unfixed defect, which needs hostile
input to matter, and the only images this pipeline decodes are PNGs it captured
itself on a host that opens no network connection. Recording the waiver in the
environment summary was treated as sufficient.

A security review answered with this file's own argument about every other
relaxable check: **a warning on stderr does not stop the very next command from
capturing a frame, committing it, and presenting it as evidence.** Recording is
not a control. And the specifics were concrete rather than theoretical — the three
programs left unpatched are precisely the three that photograph, decode and encode
every frame of the film: ImageMagick's `import`, ffmpeg, and Xorg/Xvfb.

So the waiver is registered, it forces `diagnostic`, and it carries its own reason
sentence. Measured on this host (Ubuntu 25.10, end of life 2026-07-09) with the
waiver set:

| stage | before | after |
| --- | --- | --- |
| `capture.sh` production frame | permitted | exit 1, *"refusing to capture a frame for the record while the trust state is diagnostic"* |
| `launch_game.sh launch` | permitted | exit 1, trust state diagnostic |
| `render_movie.py` (the film) | permitted, ungated | exit 1, *"REFUSING to encode the film while the trust state is diagnostic"* |
| `embed_captions.sh` (the captioned film) | permitted | exit 8, *"refusing the caption mux while the trust state is diagnostic"* |

Without the waiver, on the same host, all four refuse earlier still — at the
platform check itself. **Diagnosis stays fully available**: `capture.sh`'s
diagnostic mode withdraws its frame out of the working tree and never exits 0, and
it is not trust-gated, so a run on an out-of-support host can still be debugged.
It simply cannot manufacture evidence.

Two of those four gates are new. `render_movie.py` had none at all, and
`embed_captions.sh` checked the platform but not the trust state. The render's gate
delegates the decision to `env.sh` in a subshell rather than reading an exported
`PLAYTHROUGH_TRUST_STATE`, and the reason is the same one that made the waiver a
bypass: a control defeated by exporting the word *trusted* is not a control, and
recomputing the state in Python would put a second, drifting implementation of it
in the tree. It asks both questions in `embed_captions.sh`'s own order, because
neither implies the other — an unwaived end-of-life host reads as "trusted" until
something calls the platform check.

**Committing is deliberately not gated on the platform.** Publishing artifacts that
already exist neither captures nor encodes anything, and gating it would leave an
out-of-support host unable to commit the very disclosure that records the residual
— a rule that destroys the evidence trail it was meant to protect.

### The verdict the trust registry depends on could be forged

Found while implementing the above, and worse than the finding that led to it. The
platform classification was memoised in exported variables behind a
`PLAYTHROUGH_PLATFORM_CHECKED` flag, on the reasonable-sounding grounds that
`/etc/os-release` cannot change during a run. But `env.sh` is **sourced** into the
caller's shell, so every one of those variables was an *input* as well as an
output, and

```
PLAYTHROUGH_PLATFORM_CHECKED=1 PLAYTHROUGH_PLATFORM_SUPPORTED=yes
```

made `playthrough_check_platform` return 0 on this end-of-life host with no waiver,
no warning, and `PLAYTHROUGH_TRUST_STATE=trusted`. Measured, then fixed: nothing
is memoised any more, the classification is recomputed on every call, and whatever
the caller set is discarded — those variables are outputs only. The cost is one
`sed` over a small file and one `date` per call.

### How a sandbox can be on a supported platform without waiving anything

The regression suites run the real scripts against a fabricated checkout with stub
tools and a fake engine, and they have to exercise the production paths — a suite
that could only reach the prerequisite refusal would assert nothing about its
subject. Four of them satisfied the platform gate by setting the waiver, which the
change above turns into a trust bypass; left alone, 119 tests would have started
exercising the new refusal instead of their subjects.

They nominate their platform facts instead, through `PLAYTHROUGH_OS_RELEASE`, and
that **relaxes nothing**: the check runs in full against the nominated file and
still refuses an out-of-support or untabulated release. The sandboxes declare
Ubuntu 24.04 LTS, a release that genuinely is in support by the table's own dates,
so the gate passes because it passes.

What keeps that from being a production hole is a *verified* property rather than a
declared one: **a nomination is honoured only when the repository root is not a git
working tree.** A tree git does not track cannot commit anything, and this
pipeline's whole integrity claim is about committed artifacts (R1, R3). In a real
checkout `.git` is present, the nomination is ignored, and the refusal says so and
points at the waiver instead. Deleting `.git` to reach the nomination would leave a
record that can never be published — self-defeating rather than a bypass. The
resolved source is exported as `PLAYTHROUGH_PLATFORM_SOURCE` and printed in the
environment summary, so what a run believed about its platform is part of its
contract either way.

The same discriminator gates the render, for the same reason: a render into a
temporary root is not evidence, which is why every test in that suite renders into
one.

### The artwork was the one input nothing said the bytes of

`gfx/` is git-ignored \[.gitignore:52\] with four negations, and the required
MSXotto+ is not one of them. Every other substantive input to this pipeline is
carried by git — the engine source, the JSON content, every script in
`playthrough/tooling/`, the manifest, the frames, the film — so the artwork the
whole film is *rendered in* was the single exception, and nothing anywhere stated
which bytes it had to be.

What the launcher actually did with an installed tileset was read the `NAME:` or
`VIEW:` line out of its own `tileset.txt` and use it. The entire verification
path — path ownership, permissions, no links, an integrity manifest — ran only
when a tileset was *ingested* from a staged pack, which on a provisioned host
never happens because the artwork is already there. Three consequences, each
reproduced against the shipped script before anything was written:

| reproduction | before | after |
| --- | --- | --- |
| `tiles.png` replaced, in-pack `SHA256SUMS` regenerated over it | accepted, exit 0, `origin=required-installed` | refused, exit 6, both digests named |
| `gfx/MShockXotto+` replaced by a symlink to a directory outside the checkout | accepted, exit 0 | refused, exit 6, the link named |
| the upstream commit the artwork came from | stated nowhere | `6e864adbd2c5d0e68f8517b34e3c7d58eb22747d` of `I-am-Erk/CDDA-Tilesets`, tracked |

**An in-pack manifest cannot be an anchor, and this is the whole reason the fix
took the shape it did.** `SHA256SUMS` lives *inside* the payload: whoever can
write the artwork writes the list of its digests in the same command, and
regenerating it takes one line of shell — the first row of that table is
literally that command. An anchor has to sit outside the thing it describes and
under a different trust root. Here that means **tracked**:
`playthrough/tooling/tileset_provenance.json`, whose integrity is git's, exactly
like the scripts that read it.

The anchor states the upstream repository and exact commit, the commit date and
subject, the compose recipe, the tileset's id and view, and the size and SHA-256
of every one of the 22 files of the composed tree (5,409,937 bytes) plus a digest
over that whole ordered list —
`3d6c2ef4871654fdeeb5ce363b7a5894d76709d173b70c79040966e6561e317e`. The tree
digest's recipe is written into the document rather than only into the code, so
the value can be reproduced by hand: sha256 over the concatenation of
`"<sha256>  <path>\n"` for every regular file, ordered by byte-wise ascending
path, paths relative to the tileset directory with no `./` prefix.

`playthrough/tooling/tileset_provenance.py` compares the **complete** installed
tree against it, and `launch_game.sh` calls that before the resolved tileset is
used — for the already-installed origin *and* the freshly-ingested one, because a
pack verifies against a manifest that travelled inside it. Every one of these is
a refusal:

* a file the anchor names is absent, the wrong size or the wrong digest;
* a file exists that the anchor does not name (not harmless: the engine loads
  what the tileset's own JSON names, that JSON is itself anchored, and "extra
  artwork appeared" is the first half of a substitution);
* the install directory is a symlink, or any directory or file inside it is;
* a special file — device, socket, fifo — is inside it;
* the canonical install path is not `<repo>/gfx/<name>`;
* the declared id or view is not the anchored one;
* the anchor is missing, a symlink, unparseable, from a future schema version, or
  internally inconsistent — its own file list must hash to its own tree digest;
* the checker or the interpreter is unavailable. **A gate that cannot run stops
  the run.** Unestablished provenance is the finding, not a lesser outcome.

`scan_installed_tilesets` was also taught to *name and skip* a symlinked `gfx/*`
entry or a symlinked `tileset.txt` rather than dereference it, which is the
precise remedy for `[ -d ]` and `[ -f ]` following links — reported rather than
silently dropped, because "the required tileset is not installed" would be a
confusing diagnosis for a directory that is plainly present.

**The in-pack manifest is kept and demoted.** `verify_pack_provenance` still
checks it on ingestion, where it does catch a corrupted copy. It is simply no
longer treated as the anchor, because it cannot be one.

**The anchor is reproducible, not a file of unexplained digests.** The same
module that verifies also generates, and the committed anchor was proved
byte-identical to what `generate` produces from the installed tree — so
re-composing the same upstream commit with the recorded recipe and regenerating
must yield the same document, and a difference is itself the finding. Where the
artwork legitimately changes, the anchor is regenerated with
`tileset_provenance.py generate` and committed as a reviewed change; its location
is a constant and no environment variable relaxes it, which a test asserts
against the module's own source.

**The diagnostic fallback is exempt, and says so.** `ASCIITiles` is tracked, so
git already states its bytes, and `PLAYTHROUGH_ALLOW_TILESET_FALLBACK` is a
registered trust bypass under which `capture.sh` already refuses to produce a
production frame. The exemption is logged on every launch that takes it, never
silent.

### A control that proved the violation and then permitted it

`session.py` knew, from the engine's own declarations, that a `u` sent to open
`C<u|U>stom Character` lands somewhere else. The new-game submenu declares those
letters for that entry (src/main_menu.cpp:476) and the top row of the same menu
declares the very same letters for `T<u|U>torial Game` (:466), and the top row
wins: the submenu folds away and the highlight comes to rest on a **forbidden**
entry. Runtime testing of the first recorded session caught exactly that — see
*The hotkey that takes the wrong door* below for the pixels — and the module was
taught to recognise it.

What it did with that knowledge was print a warning and send the key anyway. A
security review's wording is the right wording: a control that establishes the
violation and permits it is not a control. The reasoning behind the warning was
sound as far as it went — `u` is also the game's own north-east step, so a
blanket refusal would make ordinary play impossible — but the conclusion drawn
from it was wrong. Narrow the condition; do not soften the consequence.

So it is `KeyRejected` now, raised **before** the pre-send journal and **before**
`send_key`, which means the game state and the record are both untouched and the
session stays usable: the caller simply takes the verified route instead. Three
conditions are all required, and the third is the one that makes the refusal
safe:

* the key's last chord token is `u` or `U`;
* the caller's own action or commentary says it is meant for the custom sheet
  (`CUSTOM_CHARACTER_MENTION_RE`) — which is precisely the case that was wrong,
  and nothing else;
* the **observed** UI phase is `menu`. The phase is read back from a photographed
  sidebar reading in this record (`SIDEBAR_READING_FIELDS`), never asserted by
  the driver, so an in-world `u` is the north-east step and is never refused
  whatever the commentary happens to say.

Measured after the change, outside the test harness: the refused step delivered
no key, appended no manifest row, wrote no journal, and left the frame counter at
0; an in-world `u`, a create run's own `Return` onto the sheet, and a resumed
session's ordinary `Down` were all delivered and recorded normally.

**And refusing five letters did not refuse the route.** The resume guard
(`MENU_NEW_SURVIVOR_HOTKEYS`) turns away the five main-menu letters that open a
new survivor while a resumed session is on a menu. The *verified* way to Custom
Character is Left/Right along the top row, Up/Down onto the submenu row, then
Return — and not one of those five letters appears in it. A resumed session could
have walked to the creator with the letter guard never firing once. The review
asked for launcher and session to be coupled through a verified route rather than
a letter list, so the second half of that refusal is now keyed on stated intent:
while a resumed session is on a menu, **any** key whose action or commentary says
it is opening the custom sheet is refused, whichever key it is. Intent alone
refuses nothing — `Return` confirms everything, and in the world it confirms it
harmlessly — which is why the observed phase is required with it.

**The launcher coupling existed only in a comment.** `launch_game.sh` publishes
the starting screen it verified as `PLAYTHROUGH_INITIAL_UI_STATE`, and its own
comment (:3220) says the value exists "so session.py's own mode-aware refusal and
the operator are working from the same declared state rather than from two
assumptions". Nothing in `session.py` had ever read the variable. It is read now,
in `_assert_launch_state`, and the two independent readings of one question — the
launcher's diagnostic capture of the screen, and this module's own probe of the
save tree — have to agree before a key is sent:

| Declared state | Pin | Outcome |
| --- | --- | --- |
| unset | either | opens; every refusal here stands on its own evidence |
| outside the published vocabulary | either | refused at open — a state this module cannot reason about is not one it may act on |
| `main-menu-load-required` | create | refused: the launcher verified a save exists to load |
| `main-menu-create-permitted` | resume, empty record | refused: that save was somebody else's |
| `main-menu-create-permitted` | resume, rows already recorded | opens, logged — a create run writes its save part-way through itself, the same disagreement `_pin_session` records rather than refuses |
| `unverified` | either | opens, warned — the probe established nothing, and nothing is relaxed by that |

The coupling can only refuse. No guard in the module is weakened by any value it
reads, including the value that says the launcher established nothing, and the
state is reported on the status payload as `LAUNCH_UI_STATE` so the launcher, the
module and the operator read one state instead of three.

### The retracted sections now say so at the top of the page

Two blocks of this file describe retired capture sets and each carried its
disclaimer at its own heading, hundreds of lines below the numbers it retracts.
The page now opens with *Read this before any count on this page*, which names
both and states the shipped record's own counts, so the retraction reaches a
reader who starts at the beginning.

---

## Runtime QA remediation of the earlier 395-frame capture set

**Which capture set this section is about.** Everything below was
measured against the 395-frame capture set that was committed at the
time of that QA pass. That set was later retired and the session was
re-recorded; `playthrough/frames/` now holds the 419-frame record the
sections above describe, so every frame number and every "out of 395"
count here refers to the earlier set and not to the frames in the tree
today. It is kept because the findings outlived the pixels they were
taken from: the engine behaviours it pins down (the `Tutorial Game` /
`Custom Character` hotkey collision at src/main_menu.cpp:466 against
:476, the TERMX-centred inventory window at src/inventory_ui.cpp:3181,
and the `debugmsg` at src/monmove.cpp:1779 against the logged error at
src/do_turn.cpp:293) are properties of the engine rather than of one
recording, and the tooling changes they produced -- the observed-effect
guard and the menu-hotkey advisory in `session.py` -- are in force for
every capture taken since.

A QA pass drove the committed 395-frame set through a browser at 1920x1080
and read every capture against the row that claims to describe it. The
imagery came out of that pass intact — 395/395 at true resolution, none
blank or uniform, the MSXotto+ tileset provably active, the sidebar clock
fixed-width and correct on all 149 clocked frames — and the record did not:
**29 rows narrated events their own capture contradicts**. Sweeping the same
tests across the rest of the record from this side found **16 more** of
exactly the same mistake, which is the honest total: 45 rows, plus 6 more
touched for completeness, out of 395.

The frames were **not** re-recorded. They are genuine, complete and correct,
and re-recording would have thrown away a verified capture set while
re-introducing every prompt that swallowed a keystroke the first time. What
was wrong was the prose, and the prose is what was fixed — along with the
part of the tooling that let it be written that way.

### The defect had one cause, and it was structural

Every one of the 45 rows was written from the keystroke that was
**intended** rather than from what the capture afterwards **showed**. That
is a distinction with no consequences at all until something eats the key,
and three things in this game do:

- a `(Case Sensitive)` distraction question standing in the middle of the
  screen (frames 7–16, 296, 348, 349, 384–387),
- a modal box already open and taking the keys for itself (frames 204–210
  in the skills page, 254–258 in front of the mirror, 370 in the sewing
  kit's own menu),
- a movement the engine simply declines, which changes nothing but the move
  counter (frames 248, 251, 263, 279, 280, 334, 337).

The rows in each case read as though the letter had reached the field, the
point had been bought or the survivor had stepped — and the pixels say
otherwise. Nine of them narrate spelling `Fern Creek` into a Yes/No
question while the world name on screen is still the engine's own
`Independence`, which it remains until frame 32.

### The measurement that makes it impossible to write that row again

`session.py` now compares every capture with the one before it, **before**
the row is appended, and writes the verdict into the row itself:

| verdict | what was measured | what the row gains |
| --- | --- | --- |
| `unchanged` | not one pixel differs | `; nothing on the screen changed` |
| `outside-map` | pixels differ, but none in the map column | `; nothing in the map column changed` |
| `changed` | the map column itself differs | nothing; this is the ordinary case |
| `first` | there is no earlier capture | nothing to observe |
| `unknown` | the measurement itself failed | nothing, and it says so loudly |

The measurement is one `convert` invocation — difference-compose, threshold
every non-zero pixel, then take the count and the difference's own bounding
box — so it answers a question about pixels rather than about PNG encoding,
and it needs no library the capturer did not already require. Its numbers
go into the telemetry sidecar as `screen_diff_px`, `map_diff_px` and
`map_diff_box`, so a verdict can be re-checked later rather than taken on
trust. Calibration from this record's own captures: a step that really
moved the survivor changed 38,895, 49,590 and 55,801 px of the map column;
a change confined to a panel drawn over the map changed 6,480, 14,709 and
14,732; a swallowed key changed 0.

Three properties of that design are deliberate.

- **The marker is appended, never substituted.** The operator's own note
  stays exactly as written, so a row says what was intended *and* what was
  observed, and a reader can see where the two part company.
- **Nothing is refused.** By the time a capture exists the keystroke has
  been delivered and cannot be taken back; refusing the row would leave a
  key with no frame and break the one-frame-per-keystroke identity the
  whole record rests on. So the row is written, annotated, and warned
  about.
- **The verdict states what was seen, not what it means.** A trailing
  `space` in a field with no cursor block changes nothing on screen and
  still registers — frames 26 and 226, whose keystrokes are proven by the
  names `Fern Creek` and `Delphine Ouellette` that came out of those
  fields. "Nothing on the screen changed" is true of those captures; "the
  key was ignored" would not be, and the guard does not say it.

`test_session.py` holds the guard to all of that, including against real
image files rather than only in the abstract.

### The hotkey that takes the wrong door

Two captures show a **forbidden** new-game entry carrying the selection
bar. Frame 1 has it on `Preset Character` and frame 2 has it on the top
row's `[Tutorial Game]`. Both were read directly off the pixels: the bar is
`#3333FF`, and inverting the band under it and reading it back gives
`» Preset Character` on frame 1, `Tutorial Game]` on frame 2 and
`» Custom Character` on frame 5. Read again through a browser at 1920x1080,
glyph by glyph over the blue fill, the same three readings came back, with
the `»` chevron corroborating each: the bar is one 16-px row at y 736–751
on frame 1 (list line **2**) and at y 720–735 on frame 5 (list line **1**),
where line 1 is fixed by the box's own top-border scanline at y=711 with no
ink above it. The two lists' text cells are pixel-identical between the two
frames, so the bar's position is the only difference.

That `Preset Character` is the AAP's "character-template picker" is not an
assumption: its hint string in the engine is *"Select from one of
previously created character templates."* (src/main_menu.cpp:487), and that
sentence is what the hint area of frame 1 reads back.

Neither was ever confirmed. Frame 5 has the bar back on `Custom Character`,
frame 6 is the `Return` that takes it, and what frame 6 shows is the Create
World screen — the custom path's own next step. Across all 395 captures no
forbidden entry is activated, and the committed save independently proves
the custom multi-pool creator was used (`Last Character.template` carries
`limit: 2`, i.e. `MULTI_POOL`).

The cause is in the engine's own menu declarations, and it is worth stating
plainly because it will catch anybody who reads only the submenu:

```
src/main_menu.cpp:466   "T<u|U>torial Game"      <- top row
src/main_menu.cpp:476   "C<u|U>stom Character"   <- new-game submenu
```

**The same two letters, and the top row wins.** A `u` sent to open the
custom sheet folds the submenu away and lands the highlight on the
tutorial, which is exactly what frame 2 is a picture of; three `Left`
presses (rows 3–5) walk it back. The collision is visible in the captures
themselves and not only in the source: the engine paints an entry's hotkey
letter in yellow, and the yellow glyph of the top row's `[Tutorial Game]`
is its **`u`** — the same letter that is yellow in the submenu's
`Custom Character`. The tooling had documented `u`/`U` as the
way to take that entry, in four places, and that guidance was the defect.
It now says the opposite, names the collision with both source lines, and
carries the route that was actually verified against the captures:

1. walk the top row with `Left`/`Right` to `[New Game]`,
2. **read the capture** — which submenu row carries the selection bar?
3. move with `Up`/`Down` until it is on `Custom Character`,
4. read the capture again, then press `Return`.

Step 2 is the load-bearing one. The bar's opening position is not
guaranteed: on the very first capture of this record it sat on `Preset
Character`, not on `Custom Character`. A `Return` pressed on trust there
would have opened the template picker.

`session.py` also warns, before the key is sent, when one of those letters
is being sent for a row that says it is meant for the custom sheet. It is
an advisory and not a refusal on purpose — `u` is also the game's own
north-east step, and refusing it would break ordinary play; frame 274 is a
`u` that legitimately moved the survivor.

**Accepted, with the reason stated.** The two captures stand as they are.
The requirement is that character creation goes through the custom
point-buy creator and that the forbidden entries are not taken, and the
record satisfies it: the route taken was `Custom Character`, no forbidden
entry was ever confirmed, and the save proves the multi-pool sheet. What
the two frames show is a highlight passing over a shut door on the way to
the open one, recorded rather than tidied away — and the tooling that
caused the detour has been corrected so a later session does not repeat it.

### The panel that does not know the sidebar is there

Three captures show a gameplay pop-up reaching past the map and into the
status column beside it: frames 272 and 286 (picking things up off the
floor) and frame 341 (asking what there is to drink). The status column
loses the left-hand part of several of its lines for as long as the
pop-up is open.

The cause is arithmetic, and it can be stated exactly rather than
described. The pop-up is an `inventory_selector`, and the engine both
sizes and places it against the **whole** character grid, with no
knowledge that part of that grid belongs to the sidebar:

```
src/inventory_ui.cpp:2558   prepare_layout( TERMX - nc_width, TERMY - nc_height );
src/inventory_ui.cpp:2561   snap( get_layout_width() + nc_width, TERMX )
src/inventory_ui.cpp:3181   origin = { ( TERMX - width ) / 2, ( TERMY - height ) / 2 };
```

That last line is the whole finding. The window is centred on all 240
columns, so where it lands is fixed by its width alone. Measuring the
pop-up's own light-grey border columns in the captures and then asking
the engine's formula where they *should* be gives the same answer to the
cell, three times out of three:

| capture | border columns | width | `(240-width)/2` | left border measured |
| --- | --- | --- | --- | --- |
| 272 | x147–148 and x1763–1764 | 203 cells | 18 | cell **18** |
| 286 | x147–148 and x1763–1764 | 203 cells | 18 | cell **18** |
| 341 | x243–244 and x1667–1668 | 179 cells | 30 | cell **30** |

The boundary the pop-up crosses was measured independently of any
configuration file, from the map's own background colour: `(17,9,21)`
fills x0–1567 exactly and stops, so the map is columns 0–195 and the
sidebar is columns 196–239 — 44 columns, 352 px, left edge x=1568,
which is what `sidebar_geometry.py` computes at run time. The pop-up
therefore covers 25 sidebar columns (200 px) on frames 272 and 286 and
13 (104 px) on frame 341, in text rows 21–44 in every case.

**Why there is no configuration that avoids this.** A window of `W`
columns centred on 240 has its right edge at column `(240+W)/2 - 1`,
which passes the map's last column, 195, as soon as `W > 152`. Both
pop-ups are wider than that: 203 and 179. Choosing the narrower
36-column sidebar would move the map's last column to 203 and lift the
threshold only to `W > 168` — still exceeded by both. Putting the
sidebar on the left does not help either, because the window is centred
rather than right-aligned, so it would reach into a left-hand column by
exactly the same amount. Every remaining lever is in the engine's own
source, and this work does not modify the engine.

**Accepted, because nothing the record depends on is lost.** The one
thing in that column the timing model reads is the clock, and the clock
is three text rows above the pop-up's top border: it sits in row 18 at
y288, and the pop-up starts at row 21, y336. That is not an estimate —
the 352x16 band at `+1568+288` is **byte-identical** to the capture
taken immediately before the pop-up opened, on all three frames
(272 against 271, 286 against 285, 341 against 340). Read back
magnified in a browser at 1920x1080 the three rows give
`Time:      08:00:09`, `Time:      08:00:20` and `Time:      17:05:57`,
which is what the record claims for those frames.

What is covered is worth listing, so that nobody later mistakes the
gaps for capture damage. One capture earlier, frame 271 shows those rows
complete:

```
row 21  Wield: fists
row 22  Style: No style
row 23  NW:            N:             NE:
row 24  W:                            E:
row 25  SW:            S:             SE:
row 29  Weight :  5.9/75.9 lbs
row 30  You see here 1 ++ ankle socks (pair) (poor
row 31  fit).
```

On frame 272 rows 21, 22, 29 and 31 are hidden outright; rows 23–25 keep
only `NE:`, `E:` and `SE:`; row 30 keeps only the tail
`socks (pair) (poor`. The pop-up is not padded — its own content runs
right up to its border, `Bulk Volume: 0.32/5.01 L Total Weight:
6.0/76.0 lbs` on one line and `Largest Space Free: 1.25 L 7 in.` on the
next — so the width it took is width it was using.

### Every clock reading in the record, proven from the pixels

The clock rows above raise a fair question: how is a reading known to be
right, when OCR at this glyph size is unreliable? It is unreliable here,
demonstrably — asked for frame 272's clock row, tesseract returns
`Time: 48:68:89` where the row plainly reads `08:00:09`, because an 8x16
bitmap `0` gives it very little to work with. It confuses `0` with `4`,
`6` and `8` throughout.

Which is why the pipeline does not ask it first. `ocr_clock.py` runs a
glyph-grid pass ahead of any OCR: it slices the column on the measured
cell grid and compares each cell against the game's own `Terminus.ttf`
rendered at size 16, bit for bit, with the tesseract passes kept behind
it for anything that pass cannot decode. Re-run now against the three
overlay captures it reads `08:00:09`, `08:00:20` and `17:05:57`, each
with `pass: glyph-grid` and `ocr_calls: 0` — no OCR was consulted at
all — from the crop it computes for itself, `352x1072+1568+4`. Asked for
frame 390 it returns nothing, which is the correct answer there.

There is a way to settle the whole set at once without trusting the
reader, and it costs nothing. Each clock character is one 8x16 cell.
Hash every clock cell in the record and map each hash to the character
the record claims for that position; if the record is truthful the
result must be a **bijection** — one bitmap per character and one
character per bitmap — because the game draws each glyph from one font.
A single invented or misread digit anywhere breaks it, in both
directions.

Over all 149 clocked captures the result is 11 distinct bitmaps against
11 distinct characters — `0`–`9` and `:` — with **zero** conflicts and
no character drawn by two bitmaps. So every reading in the record is
confirmed against the pixels simultaneously, including the three above,
and the `1` / `7` / `0` distinctions that tesseract loses are settled by
the glyphs themselves: Terminus draws `1` with an angled top flag and a
base serif, `7` with a top bar and no serif, and `0` with a marked
interior.

Note what this test does *not* borrow from. It never asks what any
character is; it only asks whether the record's own claims can all be
true at once, and the answer is a property of 1,192 bitmaps rather than
of anybody's reading of them. That is the strongest form the honesty
rule can take here: the frame remains the authority, and the record is
checked against it rather than against the tool that first transcribed
it.

### Where the grid really sits, and which sidebar it really is

Two pieces of geometry described in the plan do not match what the
captures show. Neither costs anything, and both are recorded here rather
than silently corrected, because the arithmetic that produced them is
right and it is the observation that had never been taken.

**The letterbox is at the bottom, not split.** The crop's `y` is
computed as `(1080 - 1072) // 2 = 4`, i.e. the grid centred in the root
with a four-pixel band above and below. Measured across all 395
captures: **387** carry ink in y0–3, **356** carry ink in y1068–1071,
and **none at all** carry ink in y1072–1079. The grid therefore sits at
`+0+0` and all eight leftover pixels are at the bottom — which is what
`env.sh` itself says the engine does two sentences earlier, blitting the
grid at the window's top-left
(src/sdltiles.cpp:311-320, :1046-1050), before attributing the `+4` to
centring. The captures settle the disagreement in favour of the first
half of that sentence.

The arithmetic is deliberately left alone, and that decision was tested
rather than argued: run against the captures now, the pipeline reads
`08:00:09`, `08:00:20` and `17:05:57` off frames 272, 286 and 341 using
that very crop, `352x1072+1568+4`, four-pixel offset included. The crop
still contains the clock row — y288 is well inside a band starting at
y4 — and `ocr_clock.py` does not trust the offset in any case: it
*measures*
which vertical phase the engine's cell grid is really drawn on, by
scoring every candidate phase against the game's own font and taking the
winner (`ocr_clock.py`, `_glyph_phase` — written down here as
`_measure_phase`, which is no function this module has ever had; on one host
the computed and the drawn phase differed by 14 pixels). A measured phase is immune to
this class of drift, which is why it exists.

**The sidebar is the 44-column one.** The plan derives the crop from
`custom_sidebar`'s 36 columns, giving `288x1072+1632+4`. The engine's
constructor default on a fresh userdir is `legacy_labels_sidebar`
(src/panels.cpp:412-418), which is 44 columns, and `sidebar_geometry.py`
resolves that at run time and prints `352x1072+1568+4`. The captures
agree with the module and not with the prose: the map background stops
dead at x1567. Nothing needs changing here — the module already
documents the distinction and names its source — but the numbers quoted
in the plan should be read as the `custom_sidebar` case, not as this
record's.

### The engine's own error report, captured

The record contains one capture of Cataclysm-DDA's own crash reporter,
frame 390, and it is the reason that frame has no clock reading. The
committed `playthrough/userdir/config/debug.log` names two distinct
engine faults, both in monster pathing:

```
10:23:57.410  src/do_turn.cpp:293   zombie can't move to its location!  (101:81:0), pavement
11:24:56.378  src/monmove.cpp:1779  tough zombie cannot climb over dumpster.
11:26:23.185  src/monmove.cpp:1779  (the same)
11:26:35.290  src/monmove.cpp:1779  (the same)
11:29:03.012  src/monmove.cpp:1779  (the same, then "[ Previous repeated 6 times ]")
11:29:14.420  src/monmove.cpp:1779  (the same)
```

The two behave very differently, and the difference is the whole reason
only one of them appears in the record. The `do_turn` one is
`dbg( D_ERROR ) << …` (src/do_turn.cpp:293): it writes a line to the log
and the turn carries on, so nothing interrupts and nothing is captured.
The `monmove` one is a `debugmsg` (src/monmove.cpp:1779) — the branch a
monster takes when it is asked to cost a move onto climbable furniture
it cannot climb — and a `debugmsg` puts a full-screen report on the
screen and waits for a key. Frame 390 is that report, and it is the only
capture in the record that shows one:

```
An error has occurred!  Written below is the error report:
DEBUG : tough zombie cannot climb over dumpster. monster::calc_movecost
        expects to be called with valid destination.
REPORTING FUNCTION : int monster::calc_movecost(const map&, ...) const
C++ SOURCE FILE    : src/monmove.cpp
LINE               : 1779
```

The report blanks everything else. Frame 390 holds exactly two colours,
`(0,0,0)` and the report's pale red `(255,150,150)`, its ink confined to
x9–958 y34–190, and the whole sidebar column is 380,160 pixels of pure
black — so the clock is not merely hard to read there, it is not drawn.
This is the one case where the layering behaviour of the previous
section really does cost a reading, and it is worth the contrast: the
pickup pop-up covers part of a column, the crash reporter covers the
screen.

The timing model absorbed it exactly as intended rather than inventing
anything. Frame 390's entry carries `clock_kind: null`,
`reconciled: true`, `reconciled_reason: clock-missing`, and its interval
is bridged across the gap — 1,182 s from frame 389's `20:10:18` to
frame 391's `20:30:00` — then clamped to the ten-second ceiling with a
transition after it. An unreadable clock is reported as unreadable and
reconciled against its neighbours; it is never guessed.

**A risk this leaves for any future session, which is why it is written
down.** A report that appears between a keystroke and its capture eats
the *next* keystroke, since that key goes to dismissing the report
instead. That is precisely the failure mode the observed-effect
measurement now catches: the key that dismisses a report produces a
capture that differs everywhere, and the key after it produces one that
differs nowhere. Nothing in the pipeline can prevent an upstream engine
fault; what it can do is refuse to let the record describe the swallowed
key as though it had worked.

**One row was re-examined here and deliberately left as written, which
is worth recording because the reasoning is not obvious.** Row 391 says
the key dismissed the same engine report a second time — and frame 391
does not show a report; it shows the sleep question. Under the ordering
every row in this record obeys, that is consistent rather than
contradictory: row 391's key was pressed while **frame 390** was on the
screen, and frame 390 is the report. Two `monmove` faults had already
been logged before that key went out (11:24:56.378 and 11:26:23.185,
against frame 390's own capture time of 11:26:24.430Z), and a third
landed at 11:26:35.290 before frame 391 was taken at 11:27:01.376Z. So
"the same report again" describes what the operator was looking at, and
frame 391 is the aftermath of dismissing it. The row asserts nothing its
own capture denies, so it stands. Recorded rather than quietly kept,
because a reader checking frame 391 against row 391 would otherwise
reach the opposite conclusion.

### Small things seen and left alone

Everything below was observed, measured and deliberately not changed.
None of it touches the record's honesty, its timing or its resolution;
all of it is the game drawing itself the way this build draws itself at
240x67.

- **One partial redraw, and it lasts thirty-one captures.** Taking
  `Custom Character` opens the `< Create World >` dialog, which occupies
  x484–1435 and repaints only itself. Everything the main menu had drawn
  outside that span survives untouched, and it survives for the whole
  world-configuration sequence — **frames 6 through 36**, every one of
  them, at identical coordinates. Established rather than eyeballed: the
  `[MOTD]` label's cells at x400–448, y832–848 are byte-identical to the
  main menu's own on exactly frames 1–36 and 395, and frames 1–5 and 395
  *are* the main menu, so 6–36 are the leftovers. What survives, read
  magnified: the menu box's left portion with its white border intact
  and each entry cut to three characters — `» Cus` (still sitting on its
  solid blue highlight bar, `u` still yellow), then `Pre`, `Ran`, `Pla`,
  `Pla`; both stubs of the white rule at y827 (x329–480 and x1440–1584);
  the complete tab labels `[MOTD]` at x400–448 and `[Quit]` at
  x1465–1510; and the yellow `All`, the first three letters of the help
  line, at x456–479. The engine repaints by damage rather than
  wholesale, which is ordinary; and re-capturing to tidy it would mean
  discarding thirty-one genuine captures to improve their looks. There
  is a small dividend in leaving it: that frozen blue bar on
  `Custom Character` is an independent picture, held for thirty-one
  frames, of which entry was actually taken.
- **Everything else repaints cleanly, which was worth checking rather
  than assuming.** Six further transitions were compared magnified, and
  each is clean: modals appear and vanish leaving pure black (16→17,
  20→21, 35→36); an over-long description line was cleared *including
  its tail*, so `experience.` did not outlive the shorter line that
  replaced it (19→20); and the world-name highlight block was correctly
  shortened from twelve cells to ten when `Independence` became
  `Fern Creek`, with the two vacated cells cleared to black (31→32).
- **Frame 102 does not strand a highlight, contrary to first
  impression.** Changing creator tabs was checked cell by cell: the
  bright-blue block behind `PROFESSION` and the dark-navy bar behind
  `Combat Mechanic` are both fully cleared on frame 102, and every
  coloured background that remains is either chrome present in both
  captures — the `General Info` header bar, the navy button blocks, the
  right panel's grey header — or frame 102's own new bar on
  `Mundane Survival`, drawn where frame 101 had black. The green cost
  line's salmon `(-3)` is gone too. Recorded because the suspicion was
  reasonable and the pixels dismissed it.
- **Frame 95's green is text, not a marker.** The pure-green `(0,255,0)`
  pixels at x305–430, y92–124 resolve at magnification into two ordinary
  words: `strong`, the value in `Knowledge: strong`, and the `?` in
  `Press ? to view and alter keybindings.` — six Terminus letterforms
  with a proper `g` descender, and a question mark with bowl, stem and
  dot. The ratings row colour-codes its values by quality, salmon for
  `underpowered`, yellow for `average`, green for `strong`, with every
  label in white; and pure green appears on 387 of the 395 captures, so
  it is the commonest colour in the record rather than an anomaly in it.
- **Frames 237–239, the age dialog clips its own title.** The dialog is
  a 34-column ImGui window at x824–1094, y506–564, and its prompt is
  longer than that. It renders `Enter age in years.  Minimum 1` and then
  a single one-pixel column at x1070 before the close button takes over.
  That sliver's inked rows are unique to Terminus's `6` among the whole
  glyph set, so the sentence was almost certainly `Minimum 16` — but one
  pixel column is not a character, so it is recorded as clipped and
  illegible rather than read. The value below it reads `25`. Frames 238
  and 239 clip identically. Nothing outside the dialog is affected: the
  creation header on frame 237 reads in full, `Name: Delphine Ouellette
  Scenario: Missed  Profession: Mechanical Engineer`.
- **`Unbound locally!` in the pop-up's hint bar.** Frames 105, 272, 276,
  286, 290, 344–346, 352, 353 and 366 carry the phrase where a hotkey
  hint would normally print, the engine's way of saying that action has
  no local binding — `Unbound keys are colored like this` is the legend
  the keybinding screen on frame 105 gives for it. One detail worth
  fixing in the record: it is drawn in **pure yellow** `#FFFF00`, the
  same colour as the `w`, `W`, `>` and `e` hints beside it, and a scan
  of that whole text row for reddish pixels returns none. The red text
  on frame 286 is elsewhere and is the pop-up's own warnings — `Does not
  fit in any pocket!` on row 27 and `There are no available choices` on
  row 44. The phrase also sits at columns 47–62, inside the map's half
  of the grid, so it is unrelated to the layering above.

---

## Code-review remediation of the transcript, the captions and the ending

**Recorded on Friday, August 7, 2026.** A code review of the shipped
documentation and media set returned ten findings against this record: two
about the in-character transcript and the caption track, seven factual
corrections to this page (each one folded into the section it corrects and
listed in *Corrections that supersede earlier sections of this page*), and one
about the session's ending. What follows is what the first two and the last one
changed, and what each was verified against. Nothing about the pictures or the
pacing moved: `playthrough/cata-play.mp4` and `playthrough/build/concat.txt`
came out of the regeneration byte-identical, and so did all 24 transition
frames.

### The in-character record named the interface, and priced her body in numbers

The review's reading was correct and it is worth stating plainly rather than
softening: rows of the transcript described the thing the operator was looking
at instead of the thing Delphine was doing. "Stat money can go downhill into
the other two." "The first key I tried did nothing to it." A cursor moving down
a list; a tab for what she did with her evenings; the sex field; the trait page;
`Thirty-five per cent off what I can carry, and it pays me three points for the
privilege of being honest about it`; three rows that named safe mode; and, at
the very end, `Scores do not change what happened.` That contradicts the voice
register set down on this page under *The dossier's voice register, as a
production note* — she does not name the interface she is looking at and does
not describe her own statistics as numbers — and it contradicts the requirement
that engineering and "gamey" remarks stay out of the in-character record.

**One hundred of the 419 commentaries were rewritten at source** in
`playthrough/manifest.jsonl`, and the whole derived chain was regenerated from
it in one pass: timeline, transition attribution, concat list and film,
transcript pair, and the captioned film. The selection was mechanical rather
than impressionistic — 88 rows whose caption did not fit the cue geometry, 28
carrying interface or character-sheet vocabulary (17 rows in both sets), and one
row, frame 92, which stated an attribute as a bare number while fitting the
geometry perfectly.

**What did not change is the part that matters for honesty.** `commentary` is
authored prose: it is the survivor's stated reason, written by the operator at
capture time. The OBSERVATIONS are the evidence — the frame index, its file,
its capture timestamp, its clock reading and the keystroke that produced it —
and not one of those was touched. That is not a promise, it is a measurement:
the SHA-256 of the projection of all 419 rows onto
`(frame, file, real_ts, ingame_clock, action)` is

```
8956f62944fb3603795cfb9e7b6a5f0c19a1f53989dc3bfc5e9f637d0f5831e0
```

before the amendment and the same afterwards. The regenerated timeline differs
from its predecessor in exactly two respects — the manifest digest it attests to
and the per-frame `commentary` — with every duration, raw delta, clock reading,
reconciliation flag, date field, cue window, transition flag and total
byte-identical. This is the same treatment an earlier amendment on this page
received (see the transcript-digest row of the corrections table): the record is
amended in the open, with the amendment recorded, rather than either rewritten
silently or left standing because it was already committed.

**And the gate that should have caught it was extended, because a prose fix
alone leaves the same defect able to recur.** `manifest.py`'s `META_PATTERNS` —
the one out-of-character vocabulary, which `session.py` applies before a key is
sent and `make_srt.py` applies before a transcript is published — named the
software and this pipeline but named no interface furniture and no character
sheet. Six concepts were added: `cursor`, `keyboard`, `form control`,
`character sheet`, `percentage` and `game mode`. They are written for the meta
sense, as the rest of the table is: a set of car keys is hers, "no point being
coy" and "a nip point on the third floor" stay, and `tab`, `score` and
`per cent` are blocked outright under the table's own stated rule that an
ambiguous word is blocked rather than allowed. Held against the committed
record, all 419 commentaries now come back clean; held against the ten wordings
the review quoted, every one is refused by concept name.

### A caption is two lines, and that is now refused rather than reported

`make_srt.py` had been corrected once already, in the right direction and one
step too far. It used to cap a cue at two lines and mark the cut with a
bracketed elision, which left 168 of the 395 cues of a retired session carrying
less than the survivor said; the fix removed the cap and replaced it with an
advisory. The result shipped 88 of 419 cues over two lines — 67 of three, 16 of
four, 4 of five and 1 of six — and the six-line one is displayed for 250
milliseconds. A stderr line beside a written file is not a contract, which is
the same lesson the voice gate had already learned two passes earlier.

The module now carries `CUE_MAX_LINES = 2` as a **publication-blocking
refusal**, and both halves of the requirement hold at once:

* `wrap_cue_text` still returns every word, in order. Nothing in this module
  shortens, elides or truncates a sentence — there is no `CUE_ELISION` and no
  code path that produces one.
* `caption_length_problems` emits **one problem per offending cue**, naming the
  entry, the frame it describes, how many lines it needs and the sentence
  itself, so the operator can shorten the source rather than hunt for it.
  `build_transcripts` refuses before either body is rendered, so every offender
  is listed in one message, and `render_srt` refuses per cue on its own account,
  so a caller assembling cues by hand cannot get past it either.

The committed cue file is now 104 one-line and 315 two-line cues, longest line
42 columns, and re-running the generator over the committed timeline reproduces
both artifacts byte-for-byte. `test_make_srt.py` and `test_manifest.py` gained
six tests between them for the refusal and the new vocabulary, and
`test_artifacts.py`'s assertion that no line cap may exist — which was the
defect codified as a test — now asserts the cap's value and the absence of an
elision mark instead.

### The ending is a death, and the engine has no Save & Quit after one

The review's last finding reads that rows 415–419 walk the post-death screens to
the main menu and that no in-game Save & Quit follows, the only save command in
the record being the pre-play Quicksave at row 194. Both halves of that
observation are exactly right. The conclusion drawn from it — produce a
compliant ending by sleeping and waking instead, then regenerate — is the one
thing that cannot be done here, and the reason is not effort.

**The engine offers no Save & Quit to a dead survivor. That is a property of
the code, not a limitation of the automation.** The gameplay loop is
`while( !g->do_turn() ) {}` [src/main.cpp:877], and `do_turn` begins

```cpp
bool game::do_turn()
{
    if( is_game_over() ) {
        return turn_handler::cleanup_at_end();
    }
```

[src/do_turn.cpp:522-525]. `is_game_over()` sets `uquit = QUIT_DIED` and returns
true once the avatar is dead [src/game.cpp:2853-2858, with the
`DEATHCAM = ask` query at :2884-2887 that row 415 declines], so the turn never
reaches input handling again. And Save & Quit lives *only* in input handling:

```cpp
case ACTION_SAVE:
    if( query_yn( _( "Save and quit?" ) ) ) {
        if( save() ) {
```

[src/handle_action.cpp:3030-3041]. There is no path from a death to that case.

**What the engine does instead is the persistence, itself, before it hands back
to the menu.** `cleanup_at_end()` [src/do_turn.cpp:111-207] saves the factions,
missions and NPCs (:127), saves the maps (:130), saves the achievements (:133),
shows the death screen (:135), moves the character's save to the graveyard
(:142) and writes the memorial with the survivor's last words (:143-144). Then,
Delphine being the world's only character, `WORLD_END` — `"reset"`, the engine's
own default, and the value in the committed
`playthrough/userdir/config/options.json` — calls
`delete_world( name, false )`, which clears the world folder of everything
except `worldoptions.json`, `mods.json` and any `*.dict`
[src/worldfactory.cpp:2449-2456 `isForbidden`, :2458-2496]. That is precisely
the committed state: `playthrough/userdir/save/Fern Creek/` holds `mods.json`
and `worldoptions.json` (plus the `world_timestamp.json` the engine writes for
the world, whose value `20260806065353706614029` is the graveyard directory's
own stamp), while the character's files sit in
`playthrough/userdir/graveyard/2026-08-06T06-53-53/`, with the memorial pair and
the achievements file beside them. Every one of those artifacts is committed, so
the ending is auditable from the tree rather than from this paragraph.

**So rows 415–419 are the game's own exit path, walked to its end rather than
short-circuited**: decline the deathcam, leave the message log, decline the
diary, leave the score screen, leave the follower epilogue, main menu. The
alternative — signalling the process instead of letting the engine finish — is
the failure mode `launch_game.sh stop` explicitly refuses while a recorded
session's frames exist, because that is how a run ends up with no character file
at all.

**Why the record is not re-recorded to obtain a sleep ending.** Two reasons, and
neither is a preference:

* One continuous session with one survivor is the agreed scope. A second
  session, a second character or a second world is outside it, and an ending
  produced by a different survivor would not be *this* survivor's ending.
* The death is real. Delphine was killed in a basement at 08:30:48 on
  Thursday, May 20, held by a tough zombie's torso grab and a zombie's right-leg
  grab. The memorial's own statistics carry `is_suicide` **0** and `is_debug`
  **0**, and the committed `playthrough/userdir/config/` contains no
  `keybindings.json` at all — so no action was ever rebound and the three debug
  actions remain what the shipped data leaves them, declared without a
  `bindings` array and therefore unreachable by any key
  [data/raw/keybindings.json:3398-3409, :3466-3471]. Nothing may be fabricated
  here; a synthesised "and then she woke up and saved" would be a fabrication of
  exactly the kind this page exists to make impossible.

The honest statement, therefore: the session ended the way the requirement's
first clause allows — by death, in legitimate play — and the second clause's
Save & Quit is unreachable in that branch by construction. The engine performed
the save the survivor could not, the last captured frame is the main menu it
returned to, and the final commit follows that frame.

---


## Runtime QA remediation of the 326-frame record

**Recorded on Sunday, August 9, 2026.** A runtime QA pass took the captioned
film as its subject and tested the seams end to end — every count, digest,
clamp, cue, concat entry, packet-to-image mapping and decoded scene across the
whole 326-frame population rather than a sample, both films against each other,
the caption track through four independent decoders, and the browser playback
surface at four widths. **Every structural invariant passed.** The film is
provably a `-c copy` of the base render, the timeline invariant closes to the
millisecond, the caption track round-trips bit-for-bit, there is no burned-in
text, no hidden stream, no audio, no omission, no reordering and no unexplained
freeze.

What it found instead were **eleven findings about the record's truthfulness,
its completeness and its packaging**, and the eleventh is the reason this
section exists at all: ten of 326 narrated entries described something other
than what their own frame showed. Their dispositions:

| # | Finding | Disposition |
| --- | --- | --- |
| F1 | `transcript.md` was titled with the retired survivor's name | **fixed in code** — the heading is derived from `dossier.md` now |
| F2 | row 313 narrated a melee swing after death | **corrected by amendment** 8 and 9 |
| F3 | row 314 claimed the last-words box was cleared; it was not | **corrected by amendment** 10, 11 and 14 |
| F4 | cues 317 and 319 read a word off the screen before it was typed | **corrected by amendment** 12 and 13 |
| F5 | no in-game Save & Quit anywhere in the record | **still unmet, and not closable here** — see below |
| F6 | the final cue was said to narrate declining a replay the frame shows playing | **measured and refused** — the frame is not the replay |
| F7 | the captioned film lost `+faststart` | **fixed in code** — `embed_captions.sh` carries the flag |
| F8 | `ffprobe` reports `nb_frames=328` for a 326-cue track | **container arithmetic, not a defect** — see below |
| F9 | the tileset provenance anchor refuses this host's composed pack | **environment, and deliberately not "fixed"** — the anchor is right and the film's artwork matches it; see below |
| F10 | six creator rows narrated narrowing a list that was never on screen | **corrected by amendments** 1 to 7 |
| F11 | four consecutive movement keystrokes were no-ops | **disclosed, not a defect** — see below |

### The narrative record was corrected through a 14-entry amendment ledger

**The record itself was not edited, and could not be.** `manifest.jsonl` and
`build/observations.jsonl` hold exactly the bytes the session wrote; no path in
`manifest.py` or `session.py` can rewrite a recorded row. A narration is
corrected by appending to `playthrough/amendments.jsonl`, where each row binds
to the sha256 of the manifest LINE it concerns, quotes the recorded text,
states the amended text, and states the MEASUREMENT that established the
correction and why the recorded words could not stand on their own.
`manifest.resolve_rows()` then applies the ledger — fail-closed, refusing
rather than skipping if a digest has moved — to the timeline, the transcript
and the caption cues. So the record and its correction are both readable, and
which is which is never in doubt.

The ledger now holds **14 amendments** covering **11 frames**
(79, 80, 81, 82, 83, 84, 313, 314, 317, 319, 324): sha256
`3e93306d92ad56534f9d673aca5663a30496e3675162ad68040d74515825fb68`, attested in
`timeline.json` as `{"rows": 14, "applied": 14}`. Eight amend an `action`, six a
`commentary`; no `frame`, `file`, `real_ts` or `ingame_clock` is amendable, by
design, because amending one of those would be inventing evidence rather than
correcting a narration.

**What the creator frames actually show (amendments 1–7, finding F10).** Frame 77
to 78 changes **12 052 pixels** inside `(824,506)-(1095,564)`, and OCR of that
band across frames 78 to 83 reads the box titled `Set new athletics skill level`
with its value reading `0`, then `/`, `/h`, `/he`, `/hea`, `/heal`. Frame 83 to
84 removes the same 12 052 pixels in the identical box, and **frame 84 is
byte-identical to frame 77** — both hash to
`acdf3ea6662de87def6eeceef8511ec4fdb5520cbf721c87b84658dac7ec9524` at 13 537
bytes, which is exactly why a full-population duplicate sweep found the pair.
The real purchase lands one keystroke later: frame 84 to 85 changes **1 437
pixels** at `(111,92)-(1037,231)`. So rows 79–84 were narrating the filter box
of a list that was not on the screen; what the keystrokes actually did was spell
an invalid number into a numeric level box, which the following `Return`
discarded. The amended actions say that, naming the value the box carried at
each keystroke, and row 84's commentary — which had claimed *"That is the whole
of me on one page"* over a page that had come back unchanged — now reads *"That
did nothing. The page is exactly as I left it."*

This supersedes the third blemish disclosed in *Three blemishes in this record*:
that entry said rows 78–84 recorded keystrokes that had no effect, which was
true but incomplete — the rows also described a screen that was not there.

**What the closing frames actually show (amendments 8–14, findings F2, F3, F4).**
Frame 311 carries no end screen. Frame 312 carries the `The End` dialog —
`In memory of: Ambrose Halloran`, `Survived: 2 mins 40 secs`, `Kills: 0` — with
an **empty** `Last Words:` box, so keystroke 312 was the last swing and its row
is correct. Then:

* **frame 312 to 313 changes 20 pixels** at `(912,761)-(917,770)`: one glyph, a
  `2`, inside that box. Row 313 had recorded another swing, and no swing was
  reachable — the engine enters its regular actions only while the avatar is
  alive [src/handle_action.cpp:3467-3473, guarding
  `do_regular_action` at :2326, which is where `ACTION_SAVE` and every other
  ordinary action lives].
* **frame 313 to 314 changes 21 pixels** at `(917,760)-(918,773)` — a
  two-pixel-wide cursor bar, and the `2` at x912–917 is untouched. The row had
  said the BackSpace cleared the box. It did not, and the digit survived every
  keystroke after it: a 3x crop reads `2O`, `2On`, `2On m`, `2On my`,
  `2On my w`, `2On my wa`, `2On my way` and finally **`2On my way.`** on frame
  324. The value the survivor filed carries the stray character, so the entry a
  viewer reads at the film's climax now says so.
* **frame 316 to 317 changes 0 pixels** of 1 920 × 1 080 — the space is
  invisible — yet cue 317 spoke the word `my` that frame 319 is where the screen
  first carries. **Frame 318 to 319 changes 23 pixels** at `(952,764)-(957,773)`,
  the `y` that completes `my`, while cue 319 spoke `way`, whose letters are
  typed on frames 321, 322 and 323. Both now say what their own frame holds.

Rows 315, 316 and 320 to 323 were left alone deliberately: their sentences are
the survivor's own words as he wrote them, not statements about the screen, and
the stray digit is stated at 313, at 314 and at 324 — three places a reader
cannot miss. An amendment that changed nothing false would be noise in a ledger
somebody has to read.

**What regenerating the chain moved, and what it did not.** The whole derived
chain was recomputed in dependency order — timeline, transitions, film, both
transcripts, captioned film — and the film came out **byte-identical**:
`cata-play.mp4` is still `23da4ae0210a048a4324650ad4bf687bf98ef095cd1914a28e54fb34124b02e9`,
`build/concat.txt` still `da6a4cd484fa79c0813b52b721942e0a455bb802715fd8424ca082865adc9cc5`,
and all **12 transition PNGs** are byte-for-byte what they were. Nothing about
the pacing or the pictures moved, because nothing about the pacing or the
pictures was wrong: `timeline.json` changed only by gaining the amendment
attestation and by carrying the amended sentences on those 11 entries — every
duration, every cue window, every clock reading and every total is the number it
was. The digests that did move, and why:

| Artifact | Before | After | Why |
| --- | --- | --- | --- |
| `timeline.json` | `e9f2d138…21358` | `d04c2d72…e48747` | amendment attestation + 11 amended entries |
| `transcript.srt` | `b9473b01…17e80` | `4cdec24b…0225f0` | 6 amended commentaries |
| `transcript.md` | `0c720783…a9388` | `2ec57c3d…f65469` | the same six, plus the derived title |
| `cata-play-cc.mp4` | `e5548147…fee22` | re-muxed | new cue text, and `+faststart` |
| `build/movie.json` | — | — | the timeline digest it binds the film to |
| `build/transitions.json` | — | — | the same, for the transition group |
| `build/transcript.json` | — | — | both transcript digests and the timeline's |

**How the corrected sentences were verified where a viewer meets them.** The
`mov_text` track was extracted back out of the captioned container and compared
with `transcript.srt`: **326 cues, zero timing and zero text mismatches**. Then
the same 326 cues were attached to the same film in Chrome as a WebVTT track —
Chrome does not decode `mov_text`, which is a player limitation this page has
recorded before — and the active cue was read at eleven timestamps chosen to sit
inside the amended windows. All eleven came back **byte-exact**, including
`216.12` → *"My hand went again. Nothing left to hit, and the 2 landed in my
last words."*, `216.37` → *"That is not what I said. The 2 would not come off,
so I wrote round it."*, and `218.87` → *"Full stop. Thirty-four years of
straight addresses, and a 2 on the last one."* The screenshots carry the
corroboration that matters most: the caption at 216.12 is painted over a picture
whose `Last Words:` box reads `2`, and the caption at 218.87 over one that reads
`2On my way.` Playback then ran to `ended` with zero JavaScript errors,
`video.error === null`, and 40 samples each carrying exactly one active cue.

**One measurement worth recording so nobody loses an hour to it.** Burning the
embedded track with `ffmpeg -vf subtitles=` and sampling single frames is a
POOR probe of cue timing, and it is not a defect in the track. The container's
video packets sit on a 25 fps grid at 0.24 s spacing while the cues sit on the
0.25 s floor, so a cue window can contain no packet START at all; the subtitles
filter only re-renders on a decoded frame boundary, so such a cue never appears
in a burned still even though a player — which renders subtitles on its own
clock — shows it correctly. Reading `activeCues` in a browser, or extracting the
track and diffing it, measures what a viewer sees. Both were done.

### The transcript's title is derived from the dossier now

`make_srt.py` used to spell the survivor's name in a constant, under a comment
asserting that the title was "deliberately the same opening
`playthrough/dossier.md` uses". After the session was re-recorded that claim was
false in the shipped tree, and the comment made the defect look intentional:
`dossier.md` opened `# Ambrose Halloran` while `transcript.md` opened with the
previous survivor's name. Every other layer agreed with the dossier — the
manifest's own sentences, the caption cues, the save file's base64 name, the
achievements file, `lastworld.json` — so one generated line was the single
dissenting voice in nine.

The heading is **read from the dossier's first level-one heading** now, and the
derivation **fails closed**: no dossier, no heading in it, a heading long enough
to be a paragraph, a heading carrying an out-of-character word or a
timestamp-shaped string, a dossier reached through a symlink or from outside the
tree — each refuses the whole generation rather than yielding a fallback. A
transcript titled with a guess is the defect this replaces. `test_make_srt.py`
holds the property from both directions, including a regression guard that greps
`make_srt.py` for the shipped survivor's name and fails if it finds it, and
`test_artifacts.py` holds the committed artifact to the committed dossier.

### The final frame is the death screen's own message log, and its row is right

The pass read the last cue as narrating a declined replay over a frame that
shows the replay playing. **The measurement says otherwise, and the engine says
why.** Frame 325 carries the query `Watch the last moments of your life…?
(Case Sensitive)` with `[Y]es` and `[N]o`, `[N]o` highlighted — the `DEATHCAM`
option is `ask` in the committed `options.json`. Answering it sets `QUIT_WATCH`
for yes and `QUIT_DIED` for no [src/game.cpp:2879-2893]. `QUIT_WATCH` makes
`is_game_over()` return **false** and the map view stays up — that is the replay
[src/game.cpp:2844-2851]. `QUIT_DIED` ends the loop, and `cleanup_at_end()`
[src/do_turn.cpp:112-145] calls `death_screen()`, whose **first** call is
`Messages::display_messages()` [src/game.cpp:2911-2918].

Frame 326 is that message log: the death messages, `Your limb breaks! x 6`, and
the log viewer's own footer `< Press f, F, or / to filter, r or R to reset >`.
It is therefore not the replay — it is what answering **No** produces, and it is
positive proof the `N` was taken. Row 326 (`press 'N' -- no, once was enough`)
is accurate and carries no amendment.

Two things follow that a reader of the historical sections needs. This record's
last captured frame is **that log**, not the main menu the 419-frame record
ended on: after the death rite the engine was stopped by signal precisely so no
post-death menu frame could enter the record, which is also why
`cleanup_at_end()` never reached `move_save_to_graveyard()` or
`write_memorial_file()` and why there is **no** `graveyard/` and **no**
`memorial/` in this tree. The absence is consistent with the frames rather than
unexplained.

### The captioned film keeps `+faststart` now, because a mux does not inherit it

`render_movie.py` encodes with `-movflags +faststart`, which moves the `moov`
atom — the index a player needs before it can decode anything — to the front of
the container. `embed_captions.sh` ran the accepted `-c copy -c:s mov_text`
recipe verbatim, and `-c copy` writes a **new** container: the flag was never
asked for, so the MP4 muxer left `moov` where it naturally falls, at the end,
behind every byte of `mdat`. Measured on the shipped pair by atom walk:

```text
cata-play.mp4      ftyp@0(32)  moov@32(3717)  free@3749(8)  mdat@3757(3745389)
cata-play-cc.mp4   ftyp@0(32)  free@32(8)  mdat@40(3763357)  moov@3763397(11141)
```

The consequence is a real one and it is paid by every viewer: served over a
Range-capable server, Chrome could start the base film from its first request,
while the captioned film — the artifact anybody actually watches — needed an
extra tail fetch (`Range: bytes=3735552-`) for the index before it could play.

The flag is in `MUX_ARGS` now, spelled from a `MOVFLAGS` constant that matches
`render_movie.py`'s, asserted by `assert_recipe_contains` like every other
mandated flag, and the argument-count gate that makes "there is nothing else in
this command" a checked fact moved from 22 to 24. After re-muxing:

```text
cata-play-cc.mp4   ftyp@0(32)  moov@32(11141)  free@11173(8)  mdat@11181(3763496)
```

Nothing about the picture or the track moved with it. The video bitstream is
still bit-for-bit the base render's — `-map 0:v:0 -c copy -f md5` gives
`ab22da27cf26c986008b139588c01754` for both films and the per-packet
`(pts_time,size)` digest `d6db63cf1164db40cbc85ace838d5e5d` for both — the
container still carries exactly two streams (`h264` 1920×1080 and `mov_text`
tagged `eng`, 219.500000 s), and the track still round-trips to 326 cues
identical to `transcript.srt`.

**Where the property is enforced, and why not in the script.** That the flag was
*asked for* is asserted in `embed_captions.sh`. That it *took effect* is asserted
by `test_artifacts.py`, which walks both films' top-level atoms out of the
committed bytes and requires `moov` before `mdat` in each. The check needs real
container bytes, and this stage's own suite drives a stubbed `ffmpeg` that writes
padding rather than an MP4 — so a walk inside the script would refuse every
stubbed mux while proving nothing about the artifact. The committed-artifact
suite is where a lost flag actually shows up.

**Verified in a browser, not only by atom walk.** Both films were served over a
Range-capable server and played from a cold start with `preload="none"`. Each
took **exactly one** media request, `Range: bytes=0-` answered `206`, and
`loadedmetadata` fired **9.1 ms** (captioned) and **3.0 ms** (base) after
`loadstart` — the index was already in the first bytes of the single response.
No request in either session began anywhere but byte 0, against a
last-five-percent threshold of 3 585 943 bytes; the captioned film then played
its whole 219.56 s to `ended` on that one request. The server's own access log
carries exactly two browser-issued media lines, one per film. Zero JavaScript
errors, `video.error === null`, and the only status ≥ 400 anywhere is Chrome's
unsolicited `/favicon.ico` probe.

### R11's Save & Quit: already documented as UNMET, and this record stops one screen earlier than the last one

The pass re-raised R11's missing exit. It is a real divergence, it was already
recorded as one, and nothing here revisits that verdict: *AAP R11: the ending is
legitimate, and the Save & Quit element is UNMET* is the authority on why no
keystroke can reach `ACTION_SAVE` after a death, on both post-death branches,
and *The ending is a death, and the engine has no Save & Quit after one* carries
the same argument from `do_turn`'s first statement. Neither is restated here.
The scope reasons are also already written down in both places and unchanged:
§0.8.2 fixes "Exactly one continuous session with one survivor", and reaching a
Save & Quit from the save that predates the death would be the death-avoidance
§0.2.1 and R12 forbid outright.

What is new is a difference between this record and the retired one, and it
matters because the two satisfy R1 by **different routes**.

Delphine's session was driven through the engine's whole exit path, so
`cleanup_at_end()` finished: her character files ended up in
`playthrough/userdir/graveyard/2026-08-06T06-53-53/` with the memorial pair, and
`save/Fern Creek/` was left holding only `mods.json`, `world_timestamp.json` and
`worldoptions.json`. Ambrose's session was stopped by signal inside
`death_screen()` instead, precisely so no post-death menu frame could enter the
record, and the committed userdir shows exactly where that put it:

| Observed on disk | What it establishes |
| --- | --- |
| `achievements/Ambrose Halloran-20260808075321772953372-1.json` exists | `save_achievements()` \[src/do_turn.cpp:133\] ran |
| `save/Apshawa/` still holds `master.gsav`, `dimension_data.gsav`, `o.0.0`, `o.1.0`, `maps/` and the whole `#QW1icm9zZSBIYWxsb3Jhbg==.*` set, the `.sav` at 333 646 bytes | `move_save_to_graveyard()` and `delete_world()` did **not** run |
| there is no `graveyard/` and no `memorial/` directory | `move_save_to_graveyard()` creates the first unconditionally \[src/game_io.cpp:253\], so it never ran |

So the process stood past `save_achievements()` \[src/do_turn.cpp:133\] and
inside `death_screen()` \[:135\], short of `move_save_to_graveyard()` \[:142\].

**And that is the reason there is a save under `save/<world>/` to commit at
all.** `WORLD_END` is committed as `"reset"` here too — in both
`playthrough/userdir/config/options.json` and
`playthrough/userdir/save/Apshawa/worldoptions.json` — and Ambrose was the
world's only character, so letting `cleanup_at_end()` finish would have done to
`save/Apshawa/` exactly what it did to `save/Fern Creek/`: move the character
files out to `graveyard/`, then clear the world folder of everything but
`worldoptions.json`, `mods.json` and the dictionaries
\[src/worldfactory.cpp:2449-2456, :2458-2496\].

That revises item 3 of *Three blemishes in this record*, which reads the missing
`graveyard/` as purely a cost. The cost is real and the caveat stands — the
engine never ran its post-death housekeeping, `save/Apshawa/` therefore holds a
live-shaped save for a dead man, and `session.py probe` will still report
`SESSION_MODE=resume` for him. But the same act is also what left a populated
`save/<world>/` in the tree. The blemish and the safeguard are one decision, and
R1 is satisfied here by the live save directory rather than, as last time, by a
graveyard.

**Nothing in the record claims the exit happened.** A case-insensitive search
for "save & quit", "save and quit" and "saved and quit" across `transcript.md`,
`transcript.srt`, `manifest.jsonl`, `timeline.json`, `dossier.md` and
`amendments.jsonl` returns zero hits in every one of them. R1's own commits are
present and in order — `7e10721d4e` "Commit the survivor's creation and the save
it produced" and `4e8a49879a` "Commit the closed session, its final save and its
artifacts".

The decision left for a human is the one the earlier sections already framed:
only the sleep branch can satisfy both halves of R11 at once, and taking it
needs §0.8.2 relaxed to authorise another session.

### The provenance anchor is refusing a re-composition, not the film's artwork

`tileset_provenance.py verify --directory 'gfx/MShockXotto+'` exits 1 on this
host and names two files:

```
- 'SHA256SUMS' hashes to 9c3d302f4acb…; the anchor names ac372c1947e7…
- 'tile_config.json' hashes to 064f4708e596…; the anchor names 9725384838a5…
```

The obvious reading is "the anchor is stale". It is not, and the difference
matters, because `gfx/` is git-ignored \[.gitignore:52\] and the anchor is the
only tracked statement of what the film's pixels are.

**Twenty of the twenty-two files are byte-identical to the anchor**, and they
are all of the artwork: `tiles.png` at 2 968 847 bytes, `large.png`,
`small.png`, `tall.png`, `taller.png`, `huge.png`, `wide.png`,
`widecenter.png`, `big.png`, `dcss.png`, `dcssTall.png`, `fallback.png`,
`overmap.png`, `overmap_tall.png`, all four `filler*.png`, plus
`layering.json` and `tileset.txt`. The two that differ are the generated tile
index and the in-pack checksum list that names it — `tile_config.json`, 625 336
bytes here against the anchor's 774 731, and `SHA256SUMS`, whose line 8 reads
`064f4708…  ./tile_config.json`. That is, the manifest correctly attests the
local index, so the installed pack is internally consistent and differs from
the anchor only as a consequence of the index differing.

**The film was not rendered against an unverified pack, and this is recorded
rather than argued.** *One untracked input needed repair* — written during the
previous pass on this worktree — records the anchor **passing** over all
twenty-two files after a missing in-pack `SHA256SUMS` was restored, reporting
`TILESET_PROVENANCE_TREE_SHA256=3d6c2ef4871654fd…`, `FILES=22`,
`UPSTREAM_COMMIT=6e864adbd2c5d0e6…`. `tile_config.json` matched then. It does
not match now, so the tree changed after that verification, not before it.

The launch gate says the same thing from the other direction.
`verify_tileset_provenance` is a hard `die` on any mismatch with no bypass for
the required tileset; its single exemption is `TILESET_ORIGIN = fallback`, which
means ASCIITiles, which is tracked and which `capture.sh` already refuses to
produce a production frame under
\[playthrough/tooling/launch_game.sh:2000-2055\]. It is called unconditionally
from `resolve_tileset` \[launch_game.sh:2140\] on every launch, and the
session's own log records `Loaded tileset: MshockXottoplus`
\[playthrough/userdir/config/debug.log\], so the required tileset resolved and
the exemption did not apply. `gfx/MShockXotto+` matched the anchor
byte-for-byte when the game started, or the game would not have started.

What refuses today is a **later re-composition of the pack on this host**. The
installed tree is byte-identical to the composer's cache at
`/opt/cdda-gfx-cache/MShockXotto+` for both differing files, so it faithfully
copies what `tools/gfx_tools/compose.py` produced here — and the anchor's
`composed_with` field records the command but pins **no version** for
`compose.py` or its imaging library. That is the whole reproducibility gap: the
sprite sheets are deterministic, the generated index is not.

The remedy the script itself offers is `tileset_provenance.py generate`, and
its own wording conditions it — "or — if the artwork legitimately changed —
regenerate the anchor". The artwork did not change, and twenty files prove it,
so the anchor is deliberately **left alone**. Re-pointing it at the current
local composition would make the tracked provenance statement describe a tree
the film was never rendered against, turning an external anchor into a
self-attestation that passes by construction and certifies nothing. A refusal
that is true is worth more than that.

The installed index is not damaged, for the record: `tile_info` is 32×32 at
pixelscale 1 and non-isometric, there are 18 `tiles-new` sheet blocks carrying
5 211 tile ids and 16 `ascii` blocks, and the engine loaded it without a
warning. It is a different valid index, not a broken one.

For a human: re-provision `gfx/MShockXotto+` from the anchored upstream commit
`6e864adbd2c5d0e68f8517b34e3c7d58eb22747d` of
`https://github.com/I-am-Erk/CDDA-Tilesets.git` with a version-pinned
composer so that a re-launch verifies, or accept this two-file divergence with
the twenty-file artwork match as the substantive guarantee. Either way the
anchor should keep refusing until one of them is done.

### `nb_frames=328` counts container samples, and two of them are empty

`ffprobe` reports three different numbers for the caption track, and all three
are correct:

| Measurement | Value |
| --- | --- |
| `nb_frames` — container sample count | 328 |
| demuxed packets | 327 |
| `nb_read_frames` — decoded cue events | 326 |

Walking the `moov` sample tables directly settles it. The `sbtl` track's
`stsz` and `stts` each hold **328** samples at a 1 000 000 timescale, totalling
219.500 s — exactly the stream duration and exactly the final cue end. Two of
those samples are two-byte empty samples, which is how `mov_text` clears the
display:

- **sample 140**, `pts = 51.500`, `duration = 1.000` — the transition gap. Cue
  139 ends at 51.500 and cue 140 begins at 52.500, so the muxer fills the
  intervening second with an empty sample rather than leave cue 139 on screen
  across the fade. This one is demuxed, which is why the packet count is 327
  rather than 326.
- **sample 328**, `pts = 219.500`, `duration = 0.000` — a zero-duration
  terminator closing the final cue's display at the end of the stream. It is
  not surfaced as a packet, which is why the packet count is 327 rather
  than 328.

So `nb_frames` is a sample-table count that includes muxer bookkeeping and it
is not a cue count. The cue count is 326: `nb_read_frames` says so and the SRT
round-trip returns exactly that many. Nothing was changed here; the only
lasting instruction is not to read `nb_frames` as a number of cues.

The video track reconciles the same way, recorded because the question will be
asked. `build/concat.txt` carries 339 `file` lines over 338 unique images, with
338 `duration` lines summing 219.500 and the last `file` entry repeated as the
concat demuxer requires. The 338 unique images are the 326 captured frames plus
the 12 materialised transition frames, and the video `stsz` holds 339 coded
pictures to match — the same figure in `cata-play.mp4` and
`cata-play-cc.mp4`, as it must be, the second being a `-c copy` of the
first. The `nb_frames=444` in the corrections table belongs to the retired
419-frame film, not to this one.

### Four refused moves under safe mode, and why those frames look frozen

Frames 157, 159 and 160 each change **one** 12×14 tile, in the same place every
time, 158 changes 418 pixels, and the sidebar clock reads `08:00:27` across the
whole stretch, so no game time passed. Four movement keystrokes in a row did
nothing at all.

They were refused, not dropped, and safe mode blocking a move already appears
once on this page: the keystroke register notes frame 406 of the retired
record, where "safe mode stayed on and the move was blocked" until an
explicit `shift+1` produced `Safe mode OFF!`. This is the same behaviour,
four times in a row, and nobody turned it off.

The sidebar message log — read by OCR from the
computed crop `352x1072+1568+4` — is **textually identical** on frames 157,
158, 159, 160 and 161, and what it carries is the safe-mode warning: the
"… tiles to the …" distance-and-direction line and "… is on! (Pr\[ess\] … to
ignore mo\[nsters\]". Frame 156, the move that did work, still shows the newer
lines above it.

The engine refuses the move before it costs anything:

```cpp
if( ( !g->check_safe_mode_allowed() ) || in_shell ) {
    return false;
}
```

\[src/avatar_action.cpp:194\]

`check_safe_mode_allowed()` \[src/game.cpp:7244\] composes that warning when
`safe_mode == SAFE_MODE_STOP` with a monster visible, sets
`safe_mode_warning_logged` and returns false, so `avatar_action::move` returns
before a step is taken or a move point is spent. The log does not grow across
the four attempts because the warning is already logged and `add_msg` collapses
repeats. The single tile that redraws each time is one tile animating in place
while the survivor did not move.

This is disclosed rather than fixed, and it is not an honesty problem. The
action clauses on those rows are stated as intent — "keep north", "east into
the house", "keep east" — and of the 41 movement rows that produced under a
thousand pixels of map change with no clock advance, none asserts a completed
move. One frame per keystroke still holds, and the frame honestly shows that
nothing moved.

### Two figures where the plan and the measurement disagree

Both are recorded rather than reconciled: in each case the plan's figure was
measured on a different machine, and the film's own pixels are the authority.

**The letterbox is eight rows at the bottom, not four at the top and bottom.**
This one is not new. §0.7.3 states that the game window sits at `+0+4` inside
the 1920×1080 root, giving "a thin 4-pixel letterbox top and bottom", and both
*Where the grid really sits, and which sidebar it really is*, over the retired
395-capture set, and the corrections table, over the retired 419, had already
measured otherwise. The QA pass raised it again against the shipped record, so
it was re-measured against that record, and it agrees for the third time.

Across the whole 326-frame population, with a running per-row maximum, the rows
that are black in *every* frame are exactly `1072`–`1079` — eight rows, all at
the bottom — and the first non-black row is `0`. The window occupied rows 0 to
1071, so it sat at `+0+0`. Every frame is 1920×1080, the whole 1072-row window
is inside it and nothing is cropped, so no requirement is touched. Only column
`1919` is black in every frame, and it is inside the window — it simply never
receives a lit pixel.

One methodological note, because this is easy to get wrong: a per-frame
black-row count measures content, not the letterbox. Frame 1, the title screen,
reads 186 black rows at the top and 328 black columns at the left purely
because the art is centred. Only a running maximum over the whole population
isolates the band.

**The transition card holds for 0.25 s, not 0.20 s.** The composition is the
plan's 0.4 / 0.2 / 0.4, but materialising it through `iter_frames(fps = 12)`
samples at twelfths of a second, and the card's `[0.4, 0.6)` window catches
three of those samples. The mean luminance of the twelve PNGs in
`build/transitions/` shows it plainly: frames 00–04 descend 0.1108 → 0.0194 as
a monotonic fade-out, frames 05, 06 and 07 are identical at 0.000941 — the
"…time passes…" card on black — and frames 08–11 rise 0.0184 → 0.0908 as a
monotonic fade-in. The ramps therefore quantise to 5/12 and 4/12 of a second
and the card to 3/12 — 0.25 s — and `build/concat.txt` charges each of the
twelve exactly `duration 0.083333` (the last `0.083337`, so the group sums to
`1.000000`).

**In the finished film it is 0.24 s, for a second and separate reason.** The
encode is a 25 fps grid, and twelfths of a second do not land on it. Measured
from the container, the twelve transition pictures sit at PTS `51.520`,
`51.600`, `51.680`, `51.760`, `51.840`, `51.920`, `52.000`, `52.080`, `52.160`,
`52.240`, `52.320`, `52.400` — 0.080 s apart, two output frame slots each — and
the next captured frame is at `52.520`. The three card pictures are `51.920`,
`52.000` and `52.080`: they decode **byte-identically** to one another
(`5cac7ff9d8133422…`, each `mean 0.000940658 std 0.0297095 max 1.0`, against
`max 0.2549` at `51.840` and `0.2471` at `52.160`, which is how you tell the
lettered card from the ramp frames either side of it), and `tesseract` reads
`time passes...` off all three. So the card is on screen from `51.920` until
`52.160`, which is **0.240 s**, and the last transition picture holds 0.120 s to
absorb the difference.

Either way the unit spans `51.520` → `52.520` = **1.000 s** exactly, which is
precisely what `timeline.py` charges as a transition and what the cue cursor
advances (51.500 → 52.500). No timing invariant is affected; only the card's
share of that fixed second differs from the prose — 0.20 s planned, 0.25 s as
composed and charged in the concat list, 0.24 s as the encoder actually shows
it. Quote whichever figure the question is about, and say which.

### The regression check that closed this pass

Both films were driven in a real headless Chrome over a Range-capable server,
the captioned one with the embedded `mov_text` cues re-attached as a WebVTT
`<track>` — Chrome cannot decode `mov_text`, which is a player limitation and
was disclosed as one. Each film was loaded at 375, 768, 1280 and 1920 px wide,
seeked across the closing flow and the transition window, and played to its
natural end.

| Checked | Captioned film | Base film |
| --- | --- | --- |
| intrinsic size / duration | 1920×1080 / 219.56 s | 1920×1080 / 219.56 s |
| text tracks | 1 track, **326** cues | **0** tracks, 0 cues, no `<track>` in the DOM |
| 16:9 at 375 / 768 / 1280 / 1920 | 1.7772 / 1.7778 / 1.7778 / 1.7778 | same, `scrollWidth == clientWidth` at every width |
| closing cues at 216.12, 216.37, 217.12, 217.62, 218.87, 219.37 | exactly one active cue each, text matching the extracted track character-for-character | `active` empty at every timestamp |
| captions off | 5 713 caption glyph pixels → **0**; the only changed pixels in the picture are the cue box's own footprint | no caption pixels at any point |
| transition | fade → card → fade, cue deliberately silent across 51.5–52.5 | same pictures, no cues |
| played to the end | `ended` true, `currentTime == duration == 219.56` | `ended` true, `currentTime == duration == 219.56` |
| console / media errors | one message, Chrome's own `/favicon.ico` 404; `video.error` null | one message, the same favicon 404; `video.error` null |
| requests ≥ 400 | only that favicon | only that favicon; and **no** request for the caption file or the captioned film |

Two things the browser reported are worth keeping because they will otherwise
be re-discovered as defects. A WebVTT track in mode `hidden` still keeps its
`activeCues` list populated — only `disabled` empties it — so "captions off"
has to be judged on painted pixels, which is how it was judged here. And
sampling the transition at 51.90 shows the last fade-to-black frame rather than
the card, for the frame-grid reason set out just above; 52.00 is the timestamp
to sample.


---

## The pipeline as built

Everything above is chronological. This part is the subject-ordered
reference: build, environment, options, tileset, save layout, render, lint
and CI, blast radius, and the leftovers that are meta by nature. It exists
because a log is a poor place to look something up, and because several of
the facts below cost an hour each to discover and would cost another hour
each to rediscover.

**Provenance convention, applied without exception below.** A value stated
plainly was measured on the host that produced this file, during the pass
that wrote it, with the command shown. A value marked *(plan)* comes from
the Agent Action Plan or from the machine the plan was written on and was
**not** reproduced here. Where a plan figure and a measurement disagree, both
appear and the disagreement is stated: that is the point of keeping an
engineering log rather than a summary. Nothing here is inferred from a
figure someone else recorded.

### The host this file was written on, measured rather than assumed

The plan describes its provisioning host as Ubuntu 24.04 "noble". This is not
that machine, and six of the plan's environment facts do not hold here. They
are set out together because each one, taken on trust, sends you somewhere
wrong.

| Fact | Plan *(plan)* | Measured here | Consequence |
| --- | --- | --- | --- |
| Distribution | Ubuntu 24.04 noble | `Ubuntu 25.10` questing, `VERSION_ID="25.10"`, `uname -srm` → `Linux 6.12.85+ x86_64` | questing is past end of life, so every stage runs under an explicit logged waiver — see "Every stage ran under an explicit, logged platform waiver" above |
| SDL3 availability | "packages no SDL3 at all"; `apt-cache policy libsdl3-dev` returns nothing | `libsdl3-dev` **is** packaged: `Candidate: 3.2.20+ds-2`, `Installed: (none)`; `pkg-config --exists sdl3` exits `1` | `SDL3=0` is still mandatory, but because 3.2.20 is **below** the Makefile's `--atleast-version=3.4.0` gate, not because the package is missing |
| ImageMagick | 6.9.12-98 legacy branch; "the v7 unified `magick` entry point does **not** exist" | `ImageMagick 7.1.2-3 Q16 x86_64` (apt `8:7.1.2.3+dfsg1-1ubuntu0.1`); `/usr/bin/magick` **exists**, and so do `convert`, `identify`, `import`, all four as `/etc/alternatives` symlinks | the opposite of the warning: IM7 is installed *and* keeps the legacy names, so the pipeline's `convert`/`import`/`identify` calls work unchanged. `magick` and `convert` were checked to agree to the last digit on the same frame |
| Memory and swap | ~3.85 GiB RAM, zero swap | `MemTotal: 4029526764 kB` = 3.75 **TiB**; `SwapTotal: 8388604 kB` on `/swapfile` | the memory ceiling that forced `-j3` does not exist here; the parallelism limit is CPU, not RAM |
| CPU count | 128 CPUs | `nproc` → `4`, `nproc --all` → `128`, `getconf _NPROCESSORS_ONLN` → `128` | the pod's cgroup gives four usable CPUs out of 128 present. Size a build from `nproc`, never from `nproc --all` |
| tesseract / ffmpeg | 5.3.4 / 6.1.1 | `tesseract 5.5.0` with `leptonica-1.84.1`; `ffmpeg`/`ffprobe` `7.1.1-1ubuntu4.2` | newer on both counts; the OCR figures in the plan were taken against 5.3.4 and are not reproduced here (see the render-path section) |

The rest of the inventory, measured the same way: `make` 4.4.1,
`pkg-config` 1.8.1, `ccache` 4.11.2, `msgfmt` (GNU gettext-tools) 0.23.1,
`xdotool version 3.20160805.1`, `xvfb` `2:21.1.18-1ubuntu1.1`,
`x11-utils` `7.7+7`, `openbox` `3.6.1-12ubuntu2`, `scrot` `1.12.1-1`,
`shellcheck` 0.10.0. SDL2 by `pkg-config --modversion`: `sdl2` 2.32.4,
`SDL2_ttf` 2.24.0, `SDL2_image` 2.8.8, `SDL2_mixer` 2.8.1, and
`freetype2` 26.2.20 — that last is FreeType's ABI version, not its release
version, and the plan's 26.1.20 is a different ABI generation, so do not
treat either number as a release.

Two interpreters, and the distinction is load-bearing: the system `python3`
is **3.13.7** and carries the PEP 668 marker at
`/usr/lib/python3.13/EXTERNALLY-MANAGED`, so nothing may be installed into
it; the pipeline's own is `/opt/playthrough-venv/bin/python`, **CPython
3.12.13**, which is the interpreter `playthrough/tooling/requirements.txt`
contracts for and the third candidate `env.sh` resolves.

### Building the tiles binary

#### It is never TRACKED, so a fresh checkout has none — but a warmed worktree can

Three different things are true of `./cataclysm-tiles` and they have been
confused for one another on this page before, so each is stated separately with
what measures it.

**It is never tracked, in any commit.** The binary is git-ignored, which is why
no clone gets one from `git clone` alone:

```console
$ git check-ignore -v cataclysm-tiles
.gitignore:75:*cataclysm-tiles   cataclysm-tiles
```

`.gitignore:75` sits in the block alongside `cataclysm`, `cata_test`,
`cata_test-tiles` and `chkjson*`. So a **fresh** checkout has no binary and the
pipeline must build one; `launch_game.sh build` (and `launch_game.sh all`,
which calls it) exists precisely for this. The plan's statement that
`./cataclysm-tiles` "exists at the repository root" was true of its
provisioning host and is not true of a fresh clone.

**This worktree, as it stands now, does have one — ignored, not tracked.** An
earlier statement on this page that the binary "is absent from this clone" was
measured on a clone where it genuinely was; it is not a property of the
checkout, and in a warmed worktree that has already built it is false:

```console
$ ls -la cataclysm-tiles
-rwxr-xr-x 1 root root 284407600 Aug  3 02:45 cataclysm-tiles
$ ./cataclysm-tiles --version
Cataclysm Dark Days Ahead: c9b7d915e1

+tiles, +sound
```

**And neither of those is the binary that drew the committed frames.** That one
is `e50300eeb0`, and it is evidenced independently of any statement here: it is
photographed into the first and last capture of the shipped set (read back at a
whole-screen crop, see *The binary that drew the current frames is named in the
frames*) and printed in the engine's own memorial header,
`Cataclysm - Dark Days Ahead version e50300eeb0 memorial file`
[playthrough/userdir/memorial/Fern Creek/Delphine Ouellette-2026-08-06-06-53-53.txt].
A locally rebuilt binary at a later commit does not retro-fit the evidence, and
the frames tie themselves to their own binary so nobody has to trust a note.

#### The command, and why every part of it is the way it is

This is the command **`launch_game.sh build` actually issues**, read off the
`exec` site rather than paraphrased [playthrough/tooling/launch_game.sh:1209-1212]:

```bash
env CXX=g++-14 make -j3 RELEASE=1 TILES=1 SOUND=1 SDL3=0 \
    ASTYLE=0 LINTJSON=0 CCACHE=1 COMPILER=g++-14
```

Every switch above is one the Makefile documents for itself: `CCACHE=1`
[Makefile:32], `RELEASE=1` [Makefile:34], `TILES=1` [Makefile:36],
`SOUND=1` [Makefile:38], `ASTYLE=0` [Makefile:88], `LINTJSON=0`
[Makefile:90]. The target name comes out as `./cataclysm-tiles` from
`TARGET_NAME = cataclysm` [Makefile:153],
`TILES_TARGET_NAME = $(TARGET_NAME)-tiles` [Makefile:154] and
`TILESTARGET = $(BUILD_PREFIX)$(TILES_TARGET_NAME)` [Makefile:160].

**`SDL3=0` is mandatory on every invocation**, and the reason here is not
the reason the plan gives. `SDL3` defaults to `1` whenever `TILES=1`
[Makefile:791-793], which adds `-DUSE_SDL3` [Makefile:800] and then runs a
hard version gate:

```make
SDL3_VERSION_OK := $(shell $(PKG_CONFIG) --atleast-version=3.4.0 sdl3 && echo ok)
ifneq ($(SDL3_VERSION_OK),ok)
  $(error SDL3 >= 3.4.0 required for the GPU shader path; ...)
endif
```

[Makefile:812-816, the `$(error)` at :814]. On this host SDL3 is *packaged*
— `apt-cache policy libsdl3-dev` reports `Candidate: 3.2.20+ds-2` — so
reasoning "there is no SDL3 here, therefore SDL2" reaches the right answer by
a route that is false, and would stop being right the moment someone installs
the package. What actually binds is the version: 3.2.20 is below 3.4.0, and
the package is not installed either, so `pkg-config --exists sdl3` exits `1`
and the gate fires. Installing `libsdl3-dev` on this distribution would not
change the conclusion, which is the useful part to know.
The SDL2 route is the project's own documented fallback:
`SDL3=0` is listed as "use the SDL2 fallback for tiles builds"
[doc/c++/COMPILING.md:83], given as a worked example
[doc/c++/COMPILING.md:174-176], and named for exactly this distribution case
at [doc/c++/COMPILING.md:232].

**`-j` is a fixed cap in the launcher, not a figure derived from `nproc`**, and
three numbers are in play, so each is given with what sets it. An earlier
version of this paragraph said the launcher sized `-j` from `nproc`; it does
not, and the two happened to be close enough on this host to hide the
difference.

* **`-j3` is what the tracked launcher uses.** `MAX_BUILD_JOBS=3` is `readonly`
  [playthrough/tooling/launch_game.sh:260] and `BUILD_JOBS` defaults to `3`
  [playthrough/tooling/launch_game.sh:279]. `clamp_build_jobs` makes that a
  CEILING rather than a default: `PLAYTHROUGH_BUILD_JOBS` can lower it but a
  higher value is announced and reduced, because a build that outruns memory
  is OOM-killed and `make` reports that as `Killed` rather than as a compile
  error [playthrough/tooling/launch_game.sh:654-667]. The cap is the plan's,
  adopted deliberately.
* **`-j5` is what this container's provisioning used** to produce the ignored
  binary now in the worktree, per the setup record — outside the launcher, by
  hand, and therefore not bound by its cap.
* **`nproc` is 4 and `nproc --all` is 128 on this host.** Neither figure feeds
  `-j` anywhere in the tooling. They are worth knowing only because they
  explain why nothing here wants `-j$(nproc --all)`: `make -j128` on four
  usable CPUs is slower than `make -j4`, not faster, and the machine's 3.75 TiB
  of RAM and 8 GiB of swap mean the memory argument for the cap is inherited
  from the plan's host rather than measured on this one.

**Four `make` variables must never be passed.** The first two are stated by
the plan; the second two are the ones that would break this feature
silently, and their proof is worth having in one place.

* **`TESTS=0` must never be passed.** `TESTS` defaults to `1`
  [Makefile:213], so the Catch2 binary is built as a matter of course and
  the switch [Makefile:92] exists only to skip it.
* **`NATIVE=linux64` must not be passed on ARM64.** Not binding on this
  x86_64 host; recorded because it is invisible until the wrong machine.
* **`USE_XDG_DIR=1` and `USE_HOME_DIR=1` must never be passed**, and this
  is the one with teeth. Both are opt-in [Makefile:1211-1223] — and the
  Makefile refuses both together, `$(error "USE_HOME_DIR=1 does not work
  with USE_XDG_DIR=1")`. Either one alone compiles fine and then moves the
  configuration directory out of the userdir entirely:

  ```cpp
  #if defined(USE_XDG_DIR)
      ...
      config_dir_value = dir;                              // an XDG path
  #else
      config_dir_value = user_dir_value + "config/";
  #endif
  ```

  [src/path_info.cpp:152-166, the two assignments at :161 and :164]. With
  either flag, `options.json` [src/path_info.cpp:167] and
  `keybindings.json` [src/path_info.cpp:400-403] land outside
  `playthrough/userdir/config/`, so `seed_options.py` would patch a file the
  game never reads and the committed no-cheating evidence would not exist.
  Nothing warns; the run just produces a differently-configured film and an
  unfalsifiable integrity claim.

**The compiler is `g++-14`, and the plan's stated reason is a
mis-citation.** `doc/c++/COMPILER_SUPPORT.md` is a table of the **oldest**
supported versions — GCC 9.3, clang 13.0 — and says the goal is to support
"up to the newest stable versions"; GCC 14 appears in it only as the
compiler Fedora 40 ships [doc/c++/COMPILER_SUPPORT.md:31-33]. So it does not
designate GCC 14 as a maximum, and quoting it that way would be wrong. The
real reason, measured: the default compiler here is `g++ (Ubuntu
15.2.0-4ubuntu4) 15.2.0`, `g++-14` is `14.3.0`, and the project compiles
with `-Werror -Wall -Wextra` [Makefile:104] against `-std=c++17`
[Makefile:533]. A newer GCC's additional diagnostics therefore fail the
build rather than warn, which is why the older, verified compiler is named
explicitly instead of taking whatever `g++` resolves to.

**Long builds must be fully detached.** `setsid nohup … >log 2>&1
< /dev/null & disown`, then poll the log. A `make` run recorded earlier on
this page was killed by `Interrupt` — not OOM, not a compile error — when an
outer shell call timed out and signalled the whole process group. The same
mechanism destroyed a creation run at frame 177, and the same remedy is why
the game is now held by a supervised process rather than by a shell.

#### The build leaves the tree pristine, and the C++ edit is retired

Every path a tiles build writes is matched by an ignore rule, and each rule
was named rather than assumed:

```console
$ for p in cataclysm-tiles obj/tiles/main.o src/version.h \
>          lang/mo_built.stamp zzip cataclysm.a tests/cata_test; do
>     git check-ignore -v -- "$p"
> done
.gitignore:75:*cataclysm-tiles          cataclysm-tiles
.gitignore:60:/obj/                     obj/tiles/main.o
.gitignore:63:/src/version.h            src/version.h
.gitignore:148:/lang/mo_built.stamp     lang/mo_built.stamp
.gitignore:83:zzip                      zzip
.gitignore:200:cataclysm.a              cataclysm.a
.gitignore:185:/tests/cata_test         tests/cata_test
```

Seven paths, seven rules, no gaps — including the three the plan does not
list (`zzip`, `cataclysm.a`, `tests/cata_test`), which a build with the
default `TESTS=1` produces. `git status --porcelain` at the head of this pass
printed **nothing at all**, zero lines. Said precisely, because the
distinction is exactly the kind this page exists to keep straight: this pass
did not itself run a build, so what is measured is that the tree is clean
beforehand and that every build output is provably untrackable. The
consequence is the same either way — the only changes a build can leave
behind are the intended ones — but it is an argument from ignore rules, not
an observation of an after state.

The binary's own `--version` is the sole accepted proof that it is the tiles
build: a tiles build reports `+tiles` (and `+sound` with `SOUND=1`), and
`launch_game.sh`'s `assert_tiles_binary` trusts nothing else — "not the file
name, not the presence of `gfx/`, not the flags we think we passed"
[playthrough/tooling/launch_game.sh:1415-1418].

**And `SDL3=0` is confirmed by the engine rather than by the build command**,
which is the strongest form the evidence can take given that no binary
survives in the checkout. The committed
[playthrough/userdir/config/debug.log] carries, on each of its three session
banners:

```
INFO : Cataclysm DDA version e50300eeb0
INFO : SDL version used during compile is 2.32.4
INFO : SDL version used during linking and in runtime is 2.32.4
INFO : SDL render devices: software, opengl, opengles2
```

`2.32.4` at both compile and run time is exactly what
`pkg-config --modversion sdl2` reports on this host, so the binary that drew
every committed frame was compiled and linked against **SDL 2**, not SDL 3 —
the `SDL3=0` route, self-reported. The version string `e50300eeb0` in the same
banner independently agrees with the `Version: e50300eeb0` read off the
frames' own pixels later on this page: two unrelated sources, the engine's log
and the photographed screen, naming the same commit.

Three mods were loaded, and the log's display names resolve to ids the world
records for itself. `save/Fern Creek/mods.json` reads
`["dda", "no_npc_food", "personal_portal_storms"]`, and all three ship in this
checkout — [data/mods/dda/modinfo.json],
[data/mods/No_NPC_Food/modinfo.json] and
[data/mods/Personal_Portal_Storms/modinfo.json]. None is a content addition by
this feature, and `data/` is untouched, as the blast-radius proof shows.

**The one C++ edit the plan anticipates is already applied, at both sites.**

```console
$ grep -n 'get_shared_variant_pass\|SDL_MAJOR_VERSION' src/pixel_minimap.cpp
284:#if SDL_MAJOR_VERSION >= 3
285:                                          , get_shared_variant_pass()
476:#if SDL_MAJOR_VERSION >= 3
477:                                     , get_shared_variant_pass()
```

So the SDL2 guard is present at both construction sites and the conditional
edit is **retired, not pending**. Nothing under `src/` is modified by this
feature; the blast-radius proof further down is the evidence.

### The headless contract, and the ways it fails quietly

The contract is defined once, in `playthrough/tooling/env.sh`, and sourced by
every other script so that it cannot drift. The values were read out of that
file rather than out of the plan — all line numbers below are in
`playthrough/tooling/env.sh`:

| Export | Line |
| --- | --- |
| `SDL_VIDEODRIVER=x11` | 1140 |
| `SDL_AUDIODRIVER=dummy` | 1141 |
| `LIBGL_ALWAYS_SOFTWARE=1` | 1146 |
| `DISPLAY`, derived from the clone index | 1014-1017 |
| `XDG_RUNTIME_DIR`, at mode 0700 | 1045 |
| `PYTHONDONTWRITEBYTECODE=1` | 1169 |
| `PYTHONUNBUFFERED=1` | 1173 |

An `Xvfb` at `1920x1080x24` and `openbox` as a minimal window manager
complete it — the window manager because focus and keyboard delivery do not
behave without one.

#### `SDL_VIDEODRIVER=dummy` is banned, and the luminance gate is why

`dummy` renders zero pixels. The game runs, the captures succeed, the encode
succeeds, every count tallies, and the only symptom is that the film is
black — which is the definition of a failure that has to be made loud. The
gate is a two-term assertion on grayscale statistics, and both terms are
needed. Measured, with the controls first:

```console
$ convert -size 64x64 xc:black png:- \
    | convert - -colorspace Gray -format "%[fx:mean] %[fx:standard_deviation]\n" info:
0 0
$ convert -size 64x64 xc:'#3a3a3a' png:- \
    | convert - -colorspace Gray -format "%[fx:mean] %[fx:standard_deviation]\n" info:
0.227451 0
```

The first line is what a `dummy`-driver frame measures: `mean=0`, `std=0`.
The second is a uniform solid-colour frame — a perfectly healthy-looking mean
with `std=0`. Take the two terms one at a time. **`mean > 0` alone lets the
uniform frame through**, and a flat grey rectangle is not a screenshot of a
game. **`std > 0` alone rejects both controls**, so on these two cases it
would do — but it is a *contrast* test, and it passes any frame with variation
in it whatever the brightness, which is precisely the thing a mean measures.
Requiring both means a frame has to be non-black *and* have structure, and
that pair is what the capture step asserts on every image it writes.

Calibration against the committed capture set, by the pipeline's own method
— `convert <png> -colorspace Gray -format
'%[fx:mean] %[fx:standard_deviation]' info:` — which is literally what
`capture.sh` runs [playthrough/tooling/capture.sh:1492-1493]:

| Frame | mean | std | What it is |
| --- | --- | --- | --- |
| `frame_00195.png` | 0.00350987 | 0.0512185 | the darkest frame in the whole set, and it passes |
| `frame_00419.png` | 0.00392848 | 0.0546159 | the last frame |
| `frame_00250.png` | 0.148222 | 0.208645 | an ordinary lit gameplay screen |
| `frame_00221.png` | 0.195958 | 0.219861 | the brightest in the set |

Those four rows are re-measured values. An earlier version of this table
gave frame 221 as `0.194235 / 0.214209`, which is neither what ImageMagick
reports for that file today nor what the capture step recorded for it at the
time: `playthrough/build/observations.jsonl` row 221 carries
`luma_mean 0.195958` and `luma_stddev 0.219861`, and a fresh `convert` run
agrees with the committed observation to the last digit. The neighbouring
frames are what the superseded pair sat between — 218 is `0.194741 / 0.214989`
and 219 is `0.194727 / 0.215016` — so it reads as a transcription from the
wrong row rather than as a change in the artifact.

All 419 committed frames were measured; **zero** fail `mean > 0 && std > 0`.
The plan's calibration figure of `mean=0.270018 std=0.198145` *(plan)* is not
reproduced by any frame here — the brightest is 0.195958 — which is a scene
difference, not a defect, and is recorded so nobody treats 0.27 as a
threshold. A dark frame is not an empty one: the darkest frame above is 0.35%
mean luminance and still carries 5% standard deviation, because a mostly
black screen with text on it is exactly that.

**One methodological trap, measured on the same frame.** These two commands
do not return the same numbers:

```console
$ identify -format '%[fx:mean] %[fx:standard_deviation]\n' frame_00195.png
0.00383317 0.0578542
$ convert frame_00195.png -colorspace Gray \
    -format '%[fx:mean] %[fx:standard_deviation]\n' info:
0.00350987 0.0512185
```

The difference is the grayscale conversion: `identify` reports statistics for
the image as stored, while the `convert` form collapses it to a single
luminance channel first. They disagree by **9.2% on the mean** and **13.0% on
the standard deviation** for the same file, which is far more than any
threshold margin, so a gate has to fix its method and a number produced by one
method must never be compared against a threshold calibrated with the other.
The pipeline's method is the second. `magick` substituted for `convert`
returns `0.00350987 0.0512185` — identical to the last digit — which is the
direct evidence that IM7's legacy name is a true alias here rather than a
different code path.

#### Window targeting is by class, and the id is never scraped

`xdotool search --name 'Cataclysm'` returns **empty** for this window, even
though `xwininfo -root -children` lists it with the title
`Cataclysm: Dark Days Ahead - <hash>`. `xdotool search --class
cataclysm-tiles` works, and the class route is the only one the tooling uses
[playthrough/tooling/launch_game.sh:2355-2371, where the same three facts are
recorded beside the code that depends on them]. The id must also not be
pulled out of `xwininfo` output with a loose hexadecimal pattern: the
geometry substring on the same line mis-matches such patterns and hands a
plausible-looking wrong number to `xdotool key --window`.

Stated honestly about provenance: no game was running during this pass, so
these three are the session's own observations (see "The capture path was
proved without touching the committed userdir" above, where the window was
found by class) plus the tooling's recorded rationale — not something
re-measured here. `xdotool --version` was re-measured: `xdotool version
3.20160805.1`. One further property of that tool, from the same comment
block, is worth carrying: **`xdotool` has no `--display` option** and takes
the display from the environment, which is why `env.sh` exports `DISPLAY` and
every call inherits it.

#### Capture targets the X root window

The game window is 1920×1072 — 240 columns × 8 px by 67 rows × 16 px, per
`WindowWidth = TERMINAL_WIDTH * fontwidth * scaling_factor`
[src/sdltiles.cpp:595-596] with `FULLSCREEN` defaulting to `"windowedbl"` on
non-MSVC builds [src/options.cpp:2715-2725] — inside a root that is exactly
1920×1080. Photographing the root therefore yields a true-resolution frame and
needs no rescaling step, which matters because rescaling softens the 8×16
glyphs the clock reader depends on.

**Where those eight leftover pixels are, measured rather than derived, because
the derivation is wrong.** `(1080 - 1072) // 2 = 4` predicts the grid centred
with a four-pixel band above and below, and that arithmetic is what the OCR
crop's `+4` comes from — but it is not what the engine draws. Measured over
**all 419** committed captures: **412** carry ink in y0–3, **223** carry ink on
y1071 (174 more reach y1070), and **not one** carries a non-black pixel
anywhere in y1072–1079. So the grid sits at **`+0+0`** and the whole
eight-pixel band is at the bottom, which is consistent with the engine blitting
the grid at the window's top-left (src/sdltiles.cpp:311-320, :1046-1050).

The crop keeps its `+4` deliberately and that decision was tested rather than
argued: `352x1072+1568+4` still contains the clock row — y288 is far inside a
band starting at y4 — and `ocr_clock.py` does not trust the offset in any case,
because `_glyph_phase` scores every candidate vertical phase by how much of
the sidebar's ink it lands inside a cell band and takes the winner
[playthrough/tooling/ocr_clock.py:1154-1180, called at :1332]. So the phase shift between the derived
crop and the drawn grid is measured away per frame; it is recorded here so that
nobody re-derives the letterbox from the crop and states it as an observation.
The same measurement, taken over the retired 395-frame set, is in *Where the
grid really sits, and which sidebar it really is*.

The root geometry itself, measured on a freshly started server:

```console
$ Xvfb :77 -screen 0 1920x1080x24 &
$ DISPLAY=:77 xdpyinfo | grep -E 'dimensions|depth of root|number of screens'
  number of screens:    1
  dimensions:    1920x1080 pixels (488x274 millimeters)
  depth of root window:    24 planes
$ DISPLAY=:77 xwininfo -root | grep -E 'Width|Height|Depth'
  Width: 1920
  Height: 1080
  Depth: 24
```

All 419 committed frames are `1920x1080`; `identify -format '%wx%h\n'` over
the set returns that geometry 419 times and nothing else.

**The pipeline's own server is hardened beyond the plan's example.** The plan
gives `Xvfb :99 -screen 0 1920x1080x24 >/tmp/xvfb.log 2>&1 &` *(plan)*.
`launch_game.sh headless` actually starts:

```
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -auth /tmp/xdg/playthrough/Xauthority
```

`-nolisten tcp` removes the network listener and `-auth` requires a cookie,
which is right and has one consequence worth knowing before it costs an
hour: a client that does **not** source `env.sh` gets
`Authorization required, but no authorization protocol specified` followed by
`Error: Can't open display: (null)`. That is the auth file doing its job, not
a broken display. Set `XAUTHORITY` to the path above, or source `env.sh`.

#### First launch does not open on the main menu

A fresh userdir opens on a **`Select your language`** prompt. On this host it
is a small dialog on an otherwise black root — measured earlier on this page
at 4 635 non-black pixels in a 176 × 60 box — and the geometry is wrong too:
the window is **640×384** on launch one, because the compiled defaults are
`TERMINAL_X` 80 and `TERMINAL_Y` 24 [src/options.cpp:2408-2416, ranges
80–960 and 24–270], and 1920×1072 on launch two once the game has written
screen-derived values. The strategy used here is to **seed the options file**
rather than to treat launch one as throwaway calibration: `seed_options.py`
writes `TERMINAL_X=240` and `TERMINAL_Y=67` in place, so the second launch
opens at the size every committed frame was photographed at.

#### `PYTHONDONTWRITEBYTECODE=1` is mandatory, and here is the proof

`__pycache__` [.gitignore:161] and `*.pyc` [.gitignore:162] are unanchored
patterns, so they would normally cover the tooling directory. The terminal
`!/playthrough/**` negation [.gitignore:275] **re-includes them**, because
git applies the last matching pattern and that negation is deliberately last.
Measured in a disposable scratch repository, with the real `.gitignore`
copied in and a bytecode file planted:

```console
$ git add --dry-run -A playthrough/
add 'playthrough/frames/frame_00001.png'
add 'playthrough/tooling/__pycache__/manifest.cpython-312.pyc'
add 'playthrough/userdir/config/debug.log'
add 'playthrough/userdir/save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.log'
add 'playthrough/userdir/save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.sav'
```

The `.pyc` is right there in the list. The negation block must **end** the
file, so bytecode cannot be re-excluded after it without breaking the save
tracking; it therefore has to be prevented at source instead, which is what
the environment variable does. `commit_artifacts.sh` additionally stages
explicitly rather than blanket-adding, so the two controls are independent.

**And the hazard is not hypothetical — it fired during the pass that wrote
this page.** Running the tooling's own suite with the venv interpreter
directly, without sourcing `env.sh`, produced real bytecode in the real
working tree:

```console
$ python -m unittest discover -s playthrough/tooling -p 'test_*.py'
$ git status --porcelain
 M playthrough/TECHNICAL_NOTES.md
?? playthrough/tooling/__pycache__/
$ ls playthrough/tooling/__pycache__/ | wc -l
16
$ git add --dry-run -A playthrough/tooling/ | head -3
add 'playthrough/tooling/__pycache__/make_srt.cpython-312.pyc'
add 'playthrough/tooling/__pycache__/test_artifacts.cpython-312.pyc'
add 'playthrough/tooling/__pycache__/test_capture.cpython-312.pyc'
$ git check-ignore -v --no-index -- playthrough/tooling/__pycache__/make_srt.cpython-312.pyc
.gitignore:275:!/playthrough/**    playthrough/tooling/__pycache__/make_srt.cpython-312.pyc
```

Sixteen files, every one of them offered for staging, with the negation named
as the rule that re-included them. And the control, run immediately
afterwards in both directions:

```console
$ rm -rf playthrough/tooling/__pycache__
$ PYTHONDONTWRITEBYTECODE=1 python -m unittest playthrough.tooling.test_make_srt
  -> __pycache__ present? NO
$ python -m unittest playthrough.tooling.test_make_srt
  -> __pycache__ present? YES
```

So the variable is the whole mechanism, and the lesson is operational: **run
the tooling through `env.sh`, or set the variable by hand.** The bytecode was
deleted before committing rather than being committed and reverted, and the
episode is recorded here because a hazard someone has actually tripped over
is worth more in a log than one that was only reasoned about.

#### A host defect that costs an hour if you meet it cold

`python3 -m venv` fails on this host:

```console
$ python3 -m venv /tmp/probe; echo "exit=$?"
Error: Command '['/tmp/probe/bin/python3', '-m', 'ensurepip', '--upgrade',
'--default-pip']' returned non-zero exit status 1.
exit=1
```

The plan's remedy *(plan)* is `python3 -m venv --without-pip` followed by
bootstrapping pip from `get-pip.py`. **That remedy is not used here, and
should not be.** `requirements.txt` states the reason at the file level:
piping `get-pip.py` from the network into an interpreter executes an
unverified script with the caller's privileges, which is precisely the trust
property `requirements.lock` exists to establish for everything downstream.
The environment at `/opt/playthrough-venv` was instead created with a pinned
installer whose own artifact is verified, and it is CPython **3.12.13** —
which also matters independently, because the lock names `cp312` manylinux
wheels and the system 3.13.7 can install none of them.

### The options that are seeded, and the two that fail silently

`seed_options.py` patches `playthrough/userdir/config/options.json` **in
place, key by key, never wholesale** — the engine writes 175 entries into
that file on this configuration and all of them must survive. Its
`SEEDED_OPTIONS` list is exactly eight keys, and every one of them was read
back out of the committed file:

| Key | Written | Shipped default | Why |
| --- | --- | --- | --- |
| `24_HOUR` | `24h` | `12h` [src/options.cpp:1868-1877] | only the `24h` branch emits fixed-width text — see below |
| `SOUND_ENABLED` | `false` | `true` [src/options.cpp:1774-1777] | matches `SDL_AUDIODRIVER=dummy`; no contention for an absent device |
| `USE_TILES` | `true` | `true` [src/options.cpp:2500-2503] | `TILES` is gated on it; see below |
| `TILES` | `MshockXottoplus` | `UltimateCataclysm` [src/options.cpp:2505-2508] | the compiled default is not installed anywhere; see the tileset section |
| `TERMINAL_X` | `240` | `80`, range 80–960 [src/options.cpp:2408-2411] | 240 × 8 px = 1920, the values the game derives for itself on this display |
| `TERMINAL_Y` | `67` | `24`, range 24–270 [src/options.cpp:2413-2416] | 67 × 16 px = 1072, the window inside the 1080-pixel root |
| `CHARACTER_POINT_POOLS` | `any` | `story_teller` [src/options.cpp:2893-2897] | at the default there is no point-buy at all; see below |
| `WORLD_COMPRESSION2` | `false` | `true` [src/options.cpp:1816-1819] | decides whether the character save is `.sav` or `.sav.zzip`; see the save-layout section |

The engine also derives, and the run keeps: `FONT_WIDTH=8`,
`FONT_HEIGHT=16`, `FONT_SIZE=16`, `SIDEBAR_POSITION=right`,
`SHOW_MONTHS=true`, `FULLSCREEN=windowedbl`, `RENDERER=software`,
`USE_DISTANT_TILES=false`, `DISTANT_TILES=ASCIITiles`,
`USE_OVERMAP_TILES=true`, `OVERMAP_TILES=Larwick Overmap` — the last four
matter more than they look and are unpicked in the tileset section.

#### `24_HOUR` has three values, not two, and `military` would look right

```cpp
if( format_type == "military" ) {
    return string_format( "%02d%02d.%02d", hour, minute, second );
} else if( format_type == "24h" ) {
    return string_format( _( "%02d:%02d:%02d" ), hour, minute, second );
} else {
    ...
    return string_format( _( "%d:%02d:%02d%sAM" ), hour_param, minute, second, padding );
```

[src/calendar.cpp:638-663, the three branches at :646, :649 and :658/:660].
Only the middle branch is fixed-width. `military` emits `0731.42` — no
colons — and would defeat the clock regex silently while looking like a
perfectly sensible 24-hour setting to anyone reading the options menu. The
`12h` default is worse still: variable-width hour, plus a padding space that
appears only below ten o'clock [src/calendar.cpp:656]. The committed value
was read back as exactly `24h`, and `ocr_clock.py` additionally asserts it
from the options file at read time rather than trusting that it was set.

#### `USE_TILES` is a prerequisite, so the tileset value is inert without it

```console
$ grep -n 'get_option( "TILES" ).setPrerequisite' src/options.cpp
2530:        get_option( "TILES" ).setPrerequisite( "USE_TILES" );
```

Its shipped default is already `true` [src/options.cpp:2500-2503], so the
failure mode is not forgetting to enable it — it is *disabling* it, or
patching a file where some earlier state left it false, and then wondering
why a correctly-written `TILES` value changed nothing. It is seeded
explicitly for that reason.

#### `CHARACTER_POINT_POOLS` defaults away from point-buy entirely

It is a **`world_default`** option with three values
[src/options.cpp:2893-2897], and the creator reads it like this:

```cpp
if( option == "multi_pool" )   { return { pool_type::MULTI_POOL }; }
else if( option == "story_teller" ) { return { pool_type::FREEFORM }; }
return { pool_type::FREEFORM, pool_type::MULTI_POOL, pool_type::ONE_POOL };
```

[src/newcharacter.cpp:438-446], with `pool_selection_is_fixed()` true for the
first two and the in-source comment stating the pool tab is then
"informational and read-only" [src/newcharacter.cpp:462-468]. **At the
shipped `story_teller` default there is no point accounting at all**, so a
requirement to use the point-buy creator is unsatisfiable until the option is
changed. `any` is what was used, and being a world-default option it appears
in two places: the world-default section of `config/options.json` and the
world's own `save/Fern Creek/worldoptions.json` [src/path_info.cpp:416-419].
Both were read back as `any`.

### The tileset: a conflict in the plan, and what actually rendered

The plan contradicts itself here, and the contradiction has to be recorded
rather than quietly resolved, because a reader who follows only one half of it
will conclude the wrong thing about the film. One part of it directs
installing the CDDA-Tilesets pack and configuring **MSXotto+**; three other
parts specify **`ASCIITiles`** on the grounds that it is the only close-range
tileset present in the checkout.

**What actually rendered: MSXotto+, and `ASCIITiles` was not used at all.**
Read out of the committed options file, which is the artifact the engine
itself wrote — five of its 175 entries, and the last four are the reason the
answer is not the obvious one:

```json
{ "name": "TILES",             "value": "MshockXottoplus" }
{ "name": "USE_DISTANT_TILES", "value": "false"           }
{ "name": "DISTANT_TILES",     "value": "ASCIITiles"      }
{ "name": "USE_OVERMAP_TILES", "value": "true"            }
{ "name": "OVERMAP_TILES",     "value": "Larwick Overmap" }
```

`DISTANT_TILES = ASCIITiles` looks like ASCII art in the film until the
prerequisite chain is read: `get_option( "DISTANT_TILES" ).setPrerequisite(
"USE_DISTANT_TILES" )` [src/options.cpp:2532], and `USE_DISTANT_TILES` is
`false`, so that value is **inert** — the same gating trap as `USE_TILES`
above, one level down. `ASCIITiles` is installed and was never drawn. The one
other tileset that *was* loaded is `Larwick Overmap`, at its shipped default
[src/options.cpp:2552-2555] behind `USE_OVERMAP_TILES` [src/options.cpp:2557],
and it draws the overmap screen — which no frame in this session shows, so it
appears in the engine's log and not in the film. Every pixel of terrain,
furniture, item and creature art in the finished film is MSXotto+.

`MshockXottoplus` is the tileset *id*, and the distinction between id,
menu label and directory name is the trap. `src/options.cpp:1213-1227` reads
the `NAME:` field of a `tileset.txt` as the option value and `VIEW:` only as
the label shown in the menu, so one pack carries three different spellings:

| Spelling | Where it comes from |
| --- | --- |
| `MshockXottoplus` | `NAME:` in `tileset.txt` — this is the `TILES` option value |
| `MSXotto+` | `VIEW:` in the same file — the label in the options menu |
| `MShockXotto+` | the directory name under `gfx/` |

Confirmed against the pack itself: the `tileset.txt` under
`/opt/cdda-gfx-cache/MShockXotto+/` declares `NAME: MshockXottoplus` and
`VIEW: MSXotto+`. This is why `launch_game.sh` scans both fields, accepts a
match on either, additionally tries the alias spellings `env.sh` lists, and
never guesses from a directory name.

**The resolution is "required and fails closed", not "preference with
fallback".** This differs from how the folder specification for this file
describes the resolution, and the code is the authority:

> ASCIITiles IS NOT A FALLBACK. `PLAYTHROUGH_TILESET_FALLBACK` only NAMES
> which tileset a substitution would use; nothing consults it unless
> `PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1` authorises one, which is announced
> and recorded as `origin=fallback`. That authorisation is one of `env.sh`'s
> trust bypasses, so `assert_capture_preconditions` refuses a capture launch
> while it is set.

[playthrough/tooling/launch_game.sh:1426-1431], with the reasoning at
[:1553-1562]: "A fallback would be worse than a failure: the checkout ships
ASCIITiles, so a run that quietly fell back to it would still produce a
full-length movie of a genuine SDL tiles session with every count tallying,
and the only symptom would be ASCII art in the finished film." That is the
same shape of failure as the black-movie one, and it gets the same treatment
— refuse rather than degrade.

**What is TRACKED, and what is merely present, measured.** Only four entries
under `gfx/` are tracked, because `/gfx/*` is excluded with four negations:

```console
$ git ls-tree --name-only HEAD -- gfx/ | head
gfx/ASCIITileset
gfx/Larwick_Overmap
gfx/loading_screens
gfx/tile_config_template.json
$ grep '^NAME:' gfx/ASCIITileset/tileset.txt gfx/Larwick_Overmap/tileset.txt
gfx/ASCIITileset/tileset.txt:NAME: ASCIITiles
gfx/Larwick_Overmap/tileset.txt:NAME: Larwick Overmap
```

MSXotto+ is not one of them and never will be. It reaches a worktree only by
being installed, and in a worktree where `launch_game.sh tileset` has run it IS
present — ignored, not tracked, which is exactly the intended end state and not
an absence:

```console
$ ls gfx/
ASCIITileset  Larwick_Overmap  MShockXotto+  loading_screens
tile_config_template.json
$ grep -E '^(NAME|VIEW):' gfx/MShockXotto+/tileset.txt
NAME: MshockXottoplus
VIEW: MSXotto+
$ git check-ignore -v gfx/MShockXotto+/tileset.txt
.gitignore:52:/gfx/*   gfx/MShockXotto+/tileset.txt
```

An earlier version of this paragraph said MSXotto+ was "**not** in this clone's
`gfx/`", which was measured before the install step had run there and is not a
property of the checkout. The durable statements are the two above: the pack is
never tracked, and the composed source of truth lives on the host at
`/opt/cdda-gfx-cache/MShockXotto+` with `launch_game.sh tileset` installing it.
Anyone re-running a capture from a fresh clone must do that step — which is the
whole point of the next paragraph.

**Installing a tileset produces zero tracked change, and `.gitignore` must
not be edited to change that.** `/gfx/*` is excluded at [.gitignore:52] with
exactly four negations at [.gitignore:53-56] — `ASCIITileset`,
`loading_screens`, `Larwick_Overmap`, `tile_config_template.json`.
Measured on a path that does not even exist here yet:

```console
$ git check-ignore -v gfx/MShockXotto+/tileset.txt
.gitignore:52:/gfx/*    gfx/MShockXotto+/tileset.txt
```

So the artwork is a runtime prerequisite, not a committed artifact, and the
film is the evidence that it was used. The compiled default
`UltimateCataclysm` [src/options.cpp:2505-2508] is absent from this checkout
too, which is why `TILES` has to be seeded at all rather than left alone.

**Either outcome would have satisfied the tiles-versus-curses rule, and that
is a separate matter.** That rule is about the **binary** — a build rendering
through the SDL tiles path, self-reporting `+tiles` — not about the artwork
pack, and `launch_game.sh` says so where it enforces it: "THIS CHECK IS ABOUT
THE BINARY. THE TILESET IS A SEPARATE, EQUALLY MANDATORY REQUIREMENT"
[playthrough/tooling/launch_game.sh:1420-1424]. Conflating the two is how a
run ends up believing an ASCII film satisfies an artwork requirement.

### The save layout, and three things about it the plan does not say

#### The session ended in death, so `save/` is not where the character is

This is the single most surprising thing in the tree and it follows from a
shipped default. `WORLD_END` is a world-default option with values
`{reset, delete, query, keep}` and a default of **`reset`**
[src/options.cpp:2836-2841]. The survivor died, the world was reset, and the
result is:

```console
$ find playthrough/userdir/save -type f
playthrough/userdir/save/Fern Creek/mods.json
playthrough/userdir/save/Fern Creek/world_timestamp.json
playthrough/userdir/save/Fern Creek/worldoptions.json
```

No `master.gsav`. No `maps.zzip`. No `overmaps/`. The character is in the
graveyard instead:

```console
$ find playthrough/userdir/graveyard -type f | sed 's/.*graveyard/graveyard/'
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.ano.json
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.log
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.mm1/37.24.0.mmr
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.mm1/37.25.0.mmr
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.mm1/38.24.-1.mmr
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.mm1/38.24.0.mmr
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.mm1/38.25.0.mmr
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.mm1/39.24.0.mmr
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.pt
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.sav
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.seen.0.0
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.seen.1.0
graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.zones.json
$ printf '%s' RGVscGhpbmUgT3VlbGxldHRl | base64 -d
Delphine Ouellette
```

Alongside it: `memorial/Fern Creek/` with a `.json` and a `.txt` dated
`2026-08-06-06-53-53`, `memorial/Delphine Ouellettes_diary.txt`,
`achievements/*.json`, `cache/**/*.fb` flatbuffer caches, and
`templates/Last Character.template`. **A gate that requires `master.gsav`
under `save/<World>/` therefore fails on a legitimately-ended run**, and any
gate written against the plan's expected layout has to accept the graveyard
tree as the save evidence for a death ending. The plan's layout table is
correct for a sleep ending and incomplete for this one.

#### The character save is plain `.sav` here — but `.sav.zzip` by default

The plan says `#<b64>.sav`; a strict reading of the engine says
`#<b64>.sav.zzip`; this tree contains `#<b64>.sav`. All three are consistent
once the branch is read:

```cpp
if( world_generator->active_world->has_compression_enabled() ) {
    ...
    std::filesystem::path save_path = ( playerfile + SAVE_EXTENSION +
                                        zzip_suffix ).get_unrelative_path();
    ...
} else {
    saved_data = write_to_file( playerfile + SAVE_EXTENSION, ...
```

[src/game_io.cpp:606-621], with `zzip_suffix = ".zzip"`
[src/worldfactory.h:25] and `WORLD_COMPRESSION2` defaulting to **`true`**
[src/options.cpp:1816-1819]. So the compressed form is the default and the
plain form is what this run produced — because `WORLD_COMPRESSION2` was
deliberately seeded `false`, which is exactly why that key is in the seeded
list. A gate must accept `*.sav` **or** `*.sav.zzip`; requiring either one
alone breaks on the other configuration.

#### `.shortcuts` is Android-only and will never exist here

```console
$ grep -n '__ANDROID__' src/game_io.cpp | tail -2
630:#if defined(__ANDROID__)
631:    const bool saved_shortcuts = write_to_file( playerfile + SAVE_EXTENSION_SHORTCUTS, [&](
```

`SAVE_EXTENSION_SHORTCUTS` is declared unconditionally
[src/path_info.h:17] but written only inside that guard, so **no gate may
require it** on Linux. Two more constants in the same header are declared and
never used at all — `grep -rn SAVE_EXTENSION_WEATHER src/` and
`grep -rn SAVE_ARTIFACTS src/` each return exactly one line, the declaration
itself — so `.weather` and `artifacts.gsav` are names in a header rather than
files any run produces. `SAVE_DIMENSION_DATA` by contrast is used, at
[src/game_io.cpp:289] and [src/game_io.cpp:581] among others. The full
authoritative set, with the used/unused distinction marked because a gate
built from the header alone would demand three files that cannot exist:

| Constant | Value | Line | Produced on this platform? |
| --- | --- | --- | --- |
| `SAVE_MASTER` | `master.gsav` | [src/path_info.h:11] | yes, for a live world |
| `SAVE_ARTIFACTS` | `artifacts.gsav` | [src/path_info.h:12] | **no — declared, referenced nowhere** |
| `SAVE_DIMENSION_DATA` | `dimension_data.gsav` | [src/path_info.h:13] | yes |
| `SAVE_EXTENSION` | `.sav` | [src/path_info.h:14] | yes |
| `SAVE_EXTENSION_LOG` | `.log` | [src/path_info.h:15] | yes |
| `SAVE_EXTENSION_WEATHER` | `.weather` | [src/path_info.h:16] | **no — declared, referenced nowhere** |
| `SAVE_EXTENSION_SHORTCUTS` | `.shortcuts` | [src/path_info.h:17] | **no — Android-only [src/game_io.cpp:630]** |

Overmap archives live under `overmaps/` with suffix `.zzip`
[src/worldfactory.h:24-25]. The tree also carries sidecars no list in the
plan mentions — `.ano.json`, `.pt`, `.seen.N.0`, `.zones.json` and a `.mm1/`
directory of `.mmr` tiles — all of which the negation covers because it
covers the whole subtree rather than an enumerated set of extensions.

#### Why `.gitignore` had to change, proved both ways

Three patterns swallow this feature's own artifacts: `\#*` [.gitignore:131],
which matches any path component beginning with `#` and is exactly how CDDA
names per-character files; unanchored `*.log` [.gitignore:31]; and
`debug.log` [.gitignore:79]. The remedy is a single negation at the **end**
of the file [.gitignore:275], because git applies the last matching pattern.

Measured in a disposable scratch repository — a real `git init`, the real
files planted, the real `.gitignore` in one case and its first 256 lines
(everything before the negation block) in the other:

```console
=== WITHOUT the terminal negation block ===
IGNORED   .gitignore:131:\#*         .../save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.sav
IGNORED   .gitignore:131:\#*         .../save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.log
IGNORED   .gitignore:79:debug.log    playthrough/userdir/config/debug.log
IGNORED   .gitignore:161:__pycache__ playthrough/tooling/__pycache__/manifest.cpython-312.pyc
tracked                              playthrough/frames/frame_00001.png
$ git add --dry-run -A playthrough/
add 'playthrough/frames/frame_00001.png'

=== WITH it (the real 275-line file) ===
$ git add --dry-run -A playthrough/
add 'playthrough/frames/frame_00001.png'
add 'playthrough/tooling/__pycache__/manifest.cpython-312.pyc'
add 'playthrough/userdir/config/debug.log'
add 'playthrough/userdir/save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.log'
add 'playthrough/userdir/save/Fern Creek/#RGVscGhpbmUgT3VlbGxldHRl.sav'
```

That first `git add` **exits 0**. It reports nothing wrong, stages the
frames, and silently omits the save — which is the failure this whole
paragraph exists to make impossible to miss. Note also which rule caught the
`.log`: `\#*` at :131, not `*.log` at :31, because :131 is later and the last
match wins. Either one alone would have been enough.

And the corresponding proof for the tree as it stands, on the real save file:

```console
$ git check-ignore -v -- 'playthrough/userdir/graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.sav'
$ echo $?
1
$ git ls-files -- 'playthrough/userdir/graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.sav'
playthrough/userdir/graveyard/2026-08-06T06-53-53/#RGVscGhpbmUgT3VlbGxldHRl.sav
```

Exit 1 from `check-ignore` means not ignored; `ls-files` means tracked. Both,
together, are what "the save is committed" means.

**The git subtlety that must not be lost.** A negation cannot re-include a
file whose *parent directory* was excluded by a directory pattern — git does
not descend into an excluded directory to evaluate negations inside it. This
block works **only** because every conflicting pattern is a file pattern
(`\#*`, `*.log`, `debug.log`) and nothing excludes `playthrough/` as a
directory. Anyone who later adds a directory-level ignore covering this tree
breaks the save tracking invisibly, with `git add` still exiting 0. The
warning is in `.gitignore` itself [.gitignore:272-274] so that it is read at
the point of temptation rather than only here.

### The render path: six pitfalls, each one measured

#### `-r` must never accompany `-fps_mode vfr`

Adding an output frame-rate flag to a variable-frame-rate encode makes ffmpeg
abort outright, calling the two settings contradictory. The argv the encoder
is actually handed, read out of `render_movie.py` rather than reconstructed
[playthrough/tooling/render_movie.py:1911-1926, constants at :215-258]:

```
ffmpeg -y -v error -f concat -safe 0 -i <list> -fps_mode vfr \
       -pix_fmt yuv420p -c:v libx264 -crf 20 -bf 0 -s 1920x1080 \
       -movflags +faststart <output>
```

No `-r`, and the module says why in its own words: "there is no output
frame-rate argument, which is not an omission but a requirement: ffmpeg
refuses one alongside a non-constant `-fps_mode` outright"
[playthrough/tooling/render_movie.py:1907-1909].

Two of those flags are less obvious and both are load-bearing.
`-pix_fmt yuv420p` is what every hardware decoder accepts; without it a
still-image source produces a container many players refuse. And **`-bf 0`**
— zero B-frames — is there because libx264's default B-frame reorder delay
leaves the final DTS behind the last PTS, and zero B-frames is the only way
the mov muxer writes a track duration that matches the timeline
[playthrough/tooling/render_movie.py:231-234]. A duration comparison against
`timeline.json` is one of the acceptance gates, so a flag that shifts the
container's own duration is not cosmetic.

#### The concat list must repeat its final `file` entry

Without the repeat the last `duration` does not take effect and the container
truncates. Measured on the committed list, which is 887 lines:

```console
$ grep -c '^file '     playthrough/build/concat.txt
444
$ grep -c '^duration ' playthrough/build/concat.txt
443
$ grep '^file ' playthrough/build/concat.txt | sort -u | wc -l
443
$ tail -3 playthrough/build/concat.txt
file '../frames/frame_00419.png'
duration 0.250
file '../frames/frame_00419.png'
```

444 `file` lines against 443 distinct files and 443 `duration` lines: the last
frame appears twice, the second time with no duration after it. The arithmetic
closes end to end — 419 keystroke captures plus 24 materialised transition
frames = 443 distinct images, plus the one repeat = 444 — and the container
agrees:

```console
$ ffprobe -v error -select_streams v:0 -count_packets \
      -show_entries stream=nb_read_packets -of csv=p=0 playthrough/cata-play.mp4
444
```

The symptom the repeat prevents, recorded from the earlier probe *(plan, and
independently reproduced during this feature's development)*: a 10.52 s
container against an 11.75 s subtitle stream for the same timeline — which is
also what motivated a single shared `timeline.json` rather than two
independent walks of the same durations.

One refinement to an earlier claim on this page. It says that under
`-fps_mode vfr` the header's `nb_frames` is "routinely absent — the real
container reports `N/A`". On the container as it stands now, it is **present
and correct**:

```console
$ ffprobe -v error -show_entries stream=nb_frames -of default=nw=1 playthrough/cata-play.mp4
nb_frames=444
```

Both routes agree at 444. Packet counting remains the right check because it
cannot be fooled by an absent header *or* by one entry's duration absorbing a
dropped image, but the flat statement that the header is absent is not true
of this file and is corrected here rather than left standing.

#### `concatenate_videoclips`, not `CompositeVideoClip`

A documented MoviePy 2.x defect makes cross-fades silently fail to render
under composition — they compose, they encode, and the fade is simply not
there. The transition unit is therefore assembled by concatenation:

```python
seg = concatenate_videoclips([
    ImageClip(cur).with_duration(0.4).with_effects([vfx.FadeOut(0.4)]),
    card.with_duration(0.2),
    ImageClip(nxt).with_duration(0.4).with_effects([vfx.FadeIn(0.4)]),
])
```

and then **materialised to PNG** via `iter_frames(fps=12)`, twelve images for
a 1.0 s segment. Materialising is the decision that keeps the whole film a
single encoder pass over image entries: no segment cutting, no mixed
demuxers, no codec-parameter mismatch, and a transition is simply more image
entries carrying their own `duration` lines. MoviePy stays genuinely
load-bearing — it does the fade arithmetic and the text composition — while
ffmpeg remains the only encoder.

Measured in the committed tree: two transition groups,
`build/transitions/trans_00315_*.png` and `trans_00316_*.png`, twelve images
each, 24 in total, and 24 references in the concat list. That count is not a
coincidence — see the timeline paragraph below.

#### MoviePy 2's API invalidates essentially every v1 example

`moviepy.editor` no longer exists, so imports come from `moviepy` directly;
every `.set_*` became `.with_*`; effects are classes applied through
`with_effects([...])`; and MoviePy 2 replaced ImageMagick with Pillow, so
`TextClip` needs no ImageMagick at all. One further trap, measured here:

```console
$ python -c "import moviepy, importlib.metadata as m; \
    print(moviepy.__version__, m.version('moviepy'))"
2.1.2 2.2.1
```

**`moviepy.__version__` misreports.** The installed distribution genuinely is
2.2.1 — which is what `requirements.txt` pins and what the lock hashes — and
the attribute says 2.1.2. Any check written against the attribute will
conclude the wrong thing; use `importlib.metadata.version`.

#### Frame-directory purity is an integrity constraint, not tidiness

Transition PNGs go to `playthrough/build/transitions/`, never to
`playthrough/frames/`. The reason is that the acceptance gate is an identity:

```console
$ ls playthrough/frames/*.png | wc -l
419
$ wc -l < playthrough/manifest.jsonl
419
$ git ls-files playthrough/frames | wc -l
419
```

`frames/*.png count == manifest.jsonl line count`, with indices contiguous
`1..419` and every row carrying exactly the six prescribed fields
(`frame`, `file`, `real_ts`, `ingame_clock`, `action`, `commentary`) and a
non-empty `action` and `commentary` — all four properties re-checked in this
pass. Mixing one derived image into `frames/` destroys that identity and with
it the only structural proof that there was exactly one capture per keystroke.

#### The OCR chain the plan prescribes does not work on this build

This is the measurement most worth having, because the plan states a specific
success and it does not reproduce. The prescribed chain, run against a real
committed gameplay frame at the correctly computed crop:

```console
$ convert playthrough/frames/frame_00250.png -crop 352x1072+1568+4 +repage \
      -colorspace Gray -resize 200% -normalize png:- \
  | tesseract stdin stdout | grep -E 'Time|[0-9]{2}:[0-9]{2}:[0-9]{2}'
Time:
```

The label reads. **Not one digit does.** The plan's figure of `08:15:32`
*(plan)* was taken against tesseract 5.3.4 on another host; here, under
tesseract 5.5.0, the same chain returns the row's label and nothing else. The
cause is recorded earlier on this page — `data/font/Terminus.ttf` draws a
slashed zero, and nine preprocessing variants were tried and measured, none
of which recovers it.

What does work is the exact reader, which compares each 8×16 cell against
the very font that drew it:

```console
$ python playthrough/tooling/ocr_clock.py --json playthrough/frames/frame_00250.png
  clock      = '08:00:44'
  date       = 'Thursday, May 20'
  pass       = 'glyph-grid'
  ocr_calls  = 0
  rect       = '352x1072+1568+4'
  candidates = 1     declined = 0
```

380 ms, zero OCR calls. With `--cross-check`, which forces every pass to run
anyway:

```console
  passes_run = ['glyph-grid', 'deslash-rows', 'reference-rows',
                'reference-column', 'deslash-negate-rows']
  ocr_calls  = 157      agreement = true      declined = 0
```

19.757 s for the same answer — a 52× cost — and all five passes agree, which
is the useful part: the module's *own* tesseract passes do read this frame
correctly. It is the bare chain, without the deslash and reference
preprocessing, that fails. So the honest statement is not "tesseract cannot
read this" but "tesseract cannot read this from the plan's recipe", and the
exact reader is there to make an OCR failure a non-event rather than to
replace OCR.

#### The crop is computed, and the number is not the plan's

```console
$ python playthrough/tooling/sidebar_geometry.py
sidebar_geometry: WARNING: .../userdir/config/panel_options.json does not exist
  yet, so the sidebar layout is the engine's own default
  'legacy_labels_sidebar' [src/panels.cpp:412-418]; it is written once the game
  saves its panel options
sidebar_geometry: WARNING: screen width is not set ...; using 1920
sidebar_geometry: WARNING: screen height is not set ...; using 1080
352x1072+1568+4
```

**`352x1072+1568+4`, not the plan's `288x1072+1632+4`** *(plan)*. The plan
computes from `custom_sidebar`'s `"width": 36`
[data/json/ui/sidebar.json:3,7] × `FONT_WIDTH` 8. But `panel_options.json`
does not exist until the game saves its panel settings, so the live layout is
the engine's own default `legacy_labels_sidebar`
[src/panels.cpp:413-419, assigned at :418] at **44** cells
[data/json/ui/sidebar-legacy-labels.json:203,209]: 44 × 8 = 352, right-aligned
at 1920 − 352 = 1568 because `SIDEBAR_POSITION` defaults to `"right"`
[src/options.cpp:2132-2136]. This is precisely why the rectangle is derived at
run time instead of written down — and it is also why the clock row must be
located **by regex within that column, never at a fixed `y`**. The clock text
itself is the `time_desc_label` widget, `"label": "Time"` bound to
`"var": "time_text"` [data/json/ui/time.json:3-7].

**The preset count, measured rather than estimated.** The plan says "ten
alternative sidebar presets" *(plan)*; the folder specification for this file
says nine top-level files plus themed bundles under `zenfs/` and
`structured/`. Counted:

```console
$ ls -1 data/json/ui/sidebar*.json | wc -l
9
$ find data/json/ui -name 'sidebar*.json' | wc -l
12
$ find data/json/ui -mindepth 1 -maxdepth 1 -type d
data/json/ui/spacebar
data/json/ui/structured
data/json/ui/zenfs
```

**Nine** at the top level (`sidebar.json` plus eight alternates:
`-legacy-classic`, `-legacy-compact`, `-legacy-labels`,
`-legacy-labels-narrow`, `-legacy-one-padding`, `-mobile`, `-thick`,
`-thick-cleaner`) and **twelve** across the whole tree, because there are
**three** themed subdirectories, not two — `spacebar/` as well as
`structured/` and `zenfs/`. 57 top-level `*.json` files in
`data/json/ui/` altogether. Any of the twelve could be the live layout, which
is the whole argument for computing.

#### The timeline is the single source of truth, and its invariant closes

Re-measured over `playthrough/timeline.json`:

| Property | Measured |
| --- | --- |
| `floor` / `ceil` / `transition` | 0.25 / 10.0 / 1.0 |
| `frame_count` | 419 |
| duration min / max | 0.25 / 10.0 |
| entries outside `[0.25, 10.0]` | **0** |
| entries at the 0.25 floor | 312 |
| entries at the 10.0 ceiling | 2 |
| `transition_after` true | 2 — frames 315 and 316 |
| `raw_delta > 10.0` | 2, max `raw_delta` 1417.0 s |
| `sum(durations)` | 231.000 |
| `total_transition` | 2.0 |
| `total` / `final_cue_end` | 233.0 / 233.0 |

`231.000 + 2.0 = 233.0 = total = final_cue_end`: the invariant holds exactly,
not to a tolerance. Two `transition_after` flags, two materialised groups, 24
transition PNGs, 24 concat references — the chain from flag to encoder input
is countable at every link.

**And the inserted second really is charged to video time**, which is the
thing a caption generator gets wrong if it walks frame durations naively:

```
frame 315: raw_delta 1417.0  duration 10.0  transition_after true
           cue_start 146.75  cue_end 156.75
frame 316: raw_delta  298.0  duration 10.0  transition_after true
           cue_start 157.75  cue_end 167.75
```

316's cue starts at 157.75, which is 156.75 **plus the transition's 1.0 s**,
not at 156.75. That single number is the difference between captions that
stay in sync to the end and captions that drift by exactly the total
transition time.

Downstream, the caption track:

```console
$ ffprobe -v error -select_streams s \
      -show_entries stream=index,codec_name:stream_tags=language \
      -of default=nw=1 playthrough/cata-play-cc.mp4
index=1
codec_name=mov_text
TAG:language=eng
```

Two streams, `h264` 1920×1080 plus `mov_text` tagged `eng`; both containers
report `duration=233.040000` against a computed 233.0, which is 0.04 s of
encoder tolerance; 8 051 910 bytes for the base render and 8 088 657 for the
captioned one. `transcript.srt` carries **419** cues and its last one closes
at `00:03:52,750 --> 00:03:53,000` — 233.000 s exactly — and
`transcript.md` carries 419 cumulative-time entries. Cue count equals frame
count equals row count equals capture count.

### Python, lint and CI

#### flake8-clean at the default 79 columns, and not by exemption

`.flake8` excludes only four unrelated paths —
`.git,__pycache__,lang/json,tools/clang-tidy-plugin/test/check_clang_tidy.py`
[.flake8:2] — and ignores only `E265` [.flake8:8] and `W504` [.flake8:11], so
the default 79-column limit is in force. `pyproject.toml` sets black's
`line-length = 79` [pyproject.toml:1-2]. `make python-check` runs bare
`flake8` [Makefile:1648-1649], and the workflow fires on any `**.py` change
[.github/workflows/flake8.yml:7-8,12-13] and then runs that target
[.github/workflows/flake8.yml:31].

**`.flake8` was not given a `playthrough` exclude.** Relaxing shared
repository configuration to accommodate new code is the easier path and the
wrong one; the new code satisfies the existing gate instead. The blast-radius
proof below is the evidence that the file is untouched.

#### The scoped criterion, and why the plan's F824 claim does not reproduce

The plan states that a global `flake8` exit code of 0 is unachievable at HEAD
because of three pre-existing `F824` findings *(plan)* —
`tools/generate_changelog.py:550`, `:689` and `tools/json_tools/util.py:378`
— under flake8 7.3.0, and that acceptance must therefore be measured as
`flake8 playthrough/` reporting nothing. Measured here:

```console
$ flake8 --version
7.1.1 (mccabe: 0.7.0, pycodestyle: 2.12.1, pyflakes: 3.2.0) CPython 3.13.7 on Linux
$ flake8 playthrough/ ; echo "exit=$?"
exit=0
$ flake8 > /tmp/f8.txt 2>&1 ; echo "exit=$?" ; wc -l < /tmp/f8.txt
exit=0
0
$ make python-check
flake8
```

**Zero findings scoped, and zero findings globally.** The three cited sites
are real constructs — `tools/generate_changelog.py:550` is
`nonlocal results_queue`, `:689` is `nonlocal results_queue, min_dttm`, and
`tools/json_tools/util.py:378` is `global indent_multiplier` — but this
flake8 does not report them, and the reason is checkable:

```console
$ python3 -c "import pyflakes.messages as m; \
    print([n for n in dir(m) if 'Unused' in n or 'Dead' in n])"
['RedefinedWhileUnused', 'UnusedAnnotation', 'UnusedVariable', 'UnusedImport']
```

pyflakes 3.2.0 has no message class for a dead `global`/`nonlocal`
declaration; that check arrived later. And the version installed here is not
an accident: the workflow does `sudo apt-get install flake8`
[.github/workflows/flake8.yml:27], so **the apt version is the version that
gates**, which on this distribution is 7.1.1.

The practical upshot, stated so it is not mis-applied in either direction:
the scoped measurement `flake8 playthrough/` is the *right* criterion,
because it is the one that cannot produce a false failure when a newer
pyflakes reaches the archive — but the plan's justification for it does not
hold on this host, and a global zero is achievable here and was achieved.
Both numbers are recorded so a future reader can tell which situation they
are in.

#### CodeQL-safe by construction

The `python` leg of `.github/workflows/codeql-analysis.yml` scans this tree —
`language: [ 'cpp', 'javascript', 'python' ]`
[.github/workflows/codeql-analysis.yml:35] — under a no-new-alerts gate. The
tooling is written to it: `subprocess.run([...])` with argument **lists**
rather than `shell=True` string interpolation, no `eval`, no unvalidated path
joins, and **no network surface of any kind** — the pipeline opens no
connection, which is also what makes the image-decoding exposure argument in
`requirements.txt` an enforced property rather than a hope.

#### stdlib `unittest` only, and the survey that justifies it

```console
$ find tools build-scripts -name '*.py' -type f | wc -l
65
$ grep -rlE '^\s*(import unittest|from unittest)' --include='*.py' tools build-scripts | wc -l
0
$ grep -rl 'import pytest' --include='*.py' tools build-scripts | wc -l
0
$ grep -rl 'def test_' --include='*.py' tools build-scripts | wc -l
0
$ find tests -name '*.py' | wc -l
0
$ find tests -name '*.cpp' | wc -l
248
```

Sixty-five Python files in this repository and **not one** test among them;
the entire `tests/` tree is 248 Catch2 `.cpp` files swept up by
`file(GLOB CATACLYSM_DDA_TEST_SOURCES` [tests/CMakeLists.txt:4]. Adding
pytest would therefore introduce a test framework to a repository that has
none, for one feature's benefit. The tooling uses the standard library
instead, and **nothing is added to `tests/`**, because anything placed there
is compiled into the C++ binary.

The current whole-suite evidence is in *The tooling's own suites, mechanically
counted* below, which supersedes every earlier figure on this page.

### The tooling's own suites, mechanically counted

**Recorded on Friday, August 7, 2026, after the last source change of the
code-review remediation pass** — which is the part that matters, because the
previous version of this section was measured *before* that pass and code review
caught it: it claimed 1,992 tests with `test_manifest=184` and
`test_session=122` while the source by then held more. A test count is only
evidence if it is younger than the code it describes, so this one is dated and
was taken last.

```console
$ python -B -m unittest discover -s playthrough/tooling -p 'test_*.py'
Ran 2284 tests in 596.447s
OK (skipped=1)
```

Per module, and **counted mechanically** — `TestLoader.loadTestsFromName` then
`countTestCases()`, not a grep for `def test_`, so the figure is the number of
tests the runner would actually collect:

| Module | Tests | | Module | Tests |
| --- | ---: | --- | --- | ---: |
| `test_artifacts` | 119 | | `test_ocr_clock` | 195 |
| `test_capture` | 108 | | `test_render_movie` | 119 |
| `test_commit_artifacts` | 88 | | `test_seed_options` | 118 |
| `test_embed_captions` | 104 | | `test_session` | 180 |
| `test_env` | 138 | | `test_sidebar_geometry` | 78 |
| `test_launch_game` | 171 | | `test_tileset_provenance` | 58 |
| `test_make_srt` | 118 | | `test_timeline` | 348 |
| `test_make_transitions` | 97 | | `test_manifest` | 245 |
|  |  | | **total (16 modules)** | **2284** |

**The per-module figures sum to 2284 exactly, which equals the discovery run's
own `Ran 2284 tests`.** That agreement is the check: a module that failed to
import would inflate neither number, but a module the discovery run silently
missed would make them disagree.

**One skip, and it is named rather than smoothed.** The run reports
`OK (skipped=1)`, and the skip is
`test_tileset_provenance.EveryFailureToReadIsARefusal.test_an_unreadable_file_is_refused`,
whose own message says why: *running as a user that ignores file modes*. A test
that removes read permission and expects a refusal cannot assert anything as
root, so it declines instead of passing vacuously. Nothing was disabled — the suite's skips are all conditional guards that
fire when an artifact is *absent* (`test_artifacts` alone has nine, for a missing
render generation, a missing movie manifest, a session where the ceiling never
engaged, and so on), and this checkout now holds the complete artifact set, so
none of them fired. The single occurrence of the word "skipped" anywhere in the
run log is a `timeline.py` warning string about a malformed date-audit record,
not a skipped test.

**How the counts moved, and why**, so the delta is auditable rather than
merely asserted. Three passes are in this figure, because three code reviews
were remediated against one boundary and their fixes were then integrated:
the performance pass, the completeness pass and the documentation pass each
added tests, the security pass added a sixteenth module, and the integration
that combined them added a few more where two fixes met.

| Module | Earlier figure | Now | Net, and why |
| --- | ---: | ---: | --- |
| `test_manifest` | 184 | 245 | the retroactive-rewrite API deleted and its tests with it, then `TestTheRecordHasNoWriterButAppend`, `TestStagingSiblingsCannotAccumulate`, `TestTheAmendmentLedger` and `TestTheCaptureAttestationLedger` added |
| `test_session` | 122 | 180 | likewise for the sidecar rewriter, offset by the phase index, the batched publication, the single-decode measurement, the byte-identity of both evidence files and the amendment path |
| `test_timeline` | 325 | 348 | the date-audit unanimity rule and the capture-attestation gate |
| `test_env` | 118 | 138 | the EOL waiver as a registered trust bypass, the platform-source seam, and the classification that cannot be forged by its caller |
| `test_launch_game` | 154 | 171 | tileset provenance verified before any emit, and the launcher/session state coupling |
| `test_capture` | 98 | 108 | the frame digest, and diagnostic mode refusing an audit destination |
| `test_render_movie` | 108 | 119 | the trust gate on the encode |
| `test_commit_artifacts` | 79 | 88 | the two out-of-band ledgers checked before anything is staged |
| `test_embed_captions` | 99 | 104 | the trust gate on the mux |
| `test_ocr_clock` | 187 | 195 | `--audit` confined to the canonical sidecar |
| `test_make_srt` | 114 | 118 | the two-line refusal, every offender named, and the geometry measured on the bytes of the rendered file |
| `test_artifacts` | 114 | 119 | the cue gate, and the record and the published narration checked as two things |
| `test_tileset_provenance` | — | 58 | a new module for a new tracked trust anchor |
| `test_make_transitions`, `test_seed_options`, `test_sidebar_geometry` | 97 / 118 / 78 | unchanged | untouched by these passes |

The figures sum to **2284** and the discovery run collects 2284, which is the
check that no module was silently missed.

**Shell and lint, measured in the same pass.** The surface is **five** `.sh`
files — `capture.sh`, `commit_artifacts.sh`, `embed_captions.sh`, `env.sh`,
`launch_game.sh` — and **24** `.py` files, nine modules plus fifteen test
modules. `shellcheck` 0.10.0 reports **0** findings over all five at `-S style`
*and* at `-x`; `bash -n` is clean on all five; `flake8` 7.1.1 reports **0**
findings for `flake8 playthrough/`; `make python-check` exits 0 with no output
beyond its own command echo, i.e. clean repository-wide; and every one of the 24
modules compiles under `python -B -c "compile(...)"` while creating **zero**
`__pycache__` directories, which is the byte-compile form used precisely because
`python -m py_compile` writes the `.pyc` whatever `-B` says.

#### The declared versions, exactly as installed

```console
$ /opt/playthrough-venv/bin/python -m pip list --format=freeze
decorator==5.3.1
ImageIO==2.37.4
imageio-ffmpeg==0.6.0
moviepy==2.2.1
numpy==2.5.1
packaging==26.2
pillow==11.3.0
pip==26.2
proglog==0.1.12
pytesseract==0.3.13
python-dotenv==1.2.2
tqdm==4.70.0
```

The six declared pins in `playthrough/tooling/requirements.txt` — `moviepy`,
`pillow`, `pytesseract`, `numpy`, `imageio`, `imageio-ffmpeg` — all match
their declarations exactly.

**`ImageIO` with that casing is correct and must not be "corrected".**
`pip list --format=freeze` prints it that way because that casing is the
distribution's declared `Name` metadata, while the canonical install and
import name is lowercase. `requirements.txt` therefore says
`imageio==2.37.4`, and the file carries the same warning at the point of use
so the next reader does not helpfully fix it.

**Five packages resolved into the environment are deliberately not
declared** — `decorator`, `proglog`, `tqdm`, `python-dotenv`, `packaging` —
because they are transitive dependencies of the six, and declaring a
transitive as a direct requirement asserts a relationship that does not
exist. Their exact versions are not left to chance either. Counted in
`playthrough/tooling/requirements.lock`: **11** pinned distributions — the six
declared plus those five — and **11** `sha256:` entries, one per
distribution, with `--only-binary :all:`
[playthrough/tooling/requirements.lock:74] and `--require-hashes`
[playthrough/tooling/requirements.lock:75] set inside the file itself. Exact
versions stop drift, hashes stop substitution, and binary-only means no
unreviewed `setup.py` ever executes. The declaration file, by contrast, names
no index, no hashes and no pip options at all — it keeps the shape of the
repository's own precedent [tools/json_tools/requirements.txt], and the
install contract lives in the lock.

**`flake8` is likewise absent from `requirements.txt` on purpose.** It gates
this tooling during development but is not a runtime dependency of the
pipeline, and here it is deliberately the apt build (7.1.1) rather than a
venv one, so that what runs locally is what CI runs.

### Blast radius, honesty and integrity

#### Exactly two pre-existing tracked files changed, and here is the proof

Not summarised — pasted. The base is `f38c2fbae3`, the merge from upstream
that this feature branched from.

```console
$ git diff --name-status f38c2fbae3..HEAD | grep -v $'\tplaythrough/'
M       .gitattributes
M       .gitignore

$ git diff --name-only f38c2fbae3..HEAD | awk -F/ '{print $1}' | sort | uniq -c | sort -rn
    522 playthrough
      1 .gitignore
      1 .gitattributes

$ git diff --name-status f38c2fbae3..HEAD | awk '{print $1}' | sort | uniq -c
    522 A
      2 M

$ git diff --stat f38c2fbae3..HEAD -- .gitignore .gitattributes
 .gitattributes |  6 ++++++
 .gitignore     | 20 ++++++++++++++++++++
 2 files changed, 26 insertions(+)
```

524 changed paths: 522 additions, all under `playthrough/`, and two
modifications. **Zero deletions** — no `D` in the status tally. Nothing under
`src/`, `tests/`, `data/`, `gfx/`, `lang/`, `doc/`, `tools/`,
`build-scripts/`, `Makefile`, `CMakeLists.txt`, `CMakePresets.json`,
`.flake8`, `pyproject.toml`, `.astylerc` or `.github/`. And both
modifications are pure appends — 26 insertions, 0 deletions — so neither
existing line was rewritten.

The `.gitattributes` change in full, which is the six entries the plan
prescribes and nothing else:

```diff
@@ -15,6 +15,8 @@
  *.sh      text
  *.txt     text
  *.yml     text
+*.jsonl   text
+*.srt     text
@@ -36,4 +38,8 @@
  *.ico     binary
  *.png     binary
  *.ttf     binary
+*.gsav    binary
+*.mp4     binary
+*.sav     binary
+*.zzip    binary
```

`*.md text` was already declared at [.gitattributes:12], so this page needed
no attribute of its own; `*.png binary` — now [.gitattributes:39], and
`:37` before the two text-block lines above it shifted it — already covered
the frames. Note the line drift, since the plan cites the pre-change number:
after this append the file is 45 lines and `*.png` sits at 39. The file's own
comment says its intent is to normalise explicitly rather than rely on
detection [.gitattributes:33-34, "binary is a macro for -text -diff"], which
is exactly what extending it for new artifact types does.

The consequence for CI is that almost every gate sees nothing it can act on:
with no C++, JSON or CMake change, the astyle, json, cmake-format,
clang-tidy, iwyu, matrix and MSVC workflows receive no eligible input. Two
gates are newly exercised — flake8 and the `python` leg of CodeQL — and both
are satisfied by construction rather than by exemption, as the previous
section measures.

**And nothing at all gates a Markdown change, which is worth knowing before
someone looks for the check that approved this page.** Measured across all 35
workflow files: no workflow lists a `.md` path in its `paths:` filter, and
there is no `markdownlint`, `mdl` or `remark-lint` anywhere in the tree. Two
that might be assumed to apply do not — `linter.yml` (Code Style Reviewer)
filters on `Makefile`, `.astylerc`, `**.json`, `**.cpp`, `**.h` and `**.c`
[.github/workflows/linter.yml:6-14], and the spell check runs inside
`text-changes-analyzer.yml`, whose filter is its own file plus
`tools/pot_diff.py`, `lang/extract_json_strings.py`, `lang/string_extractor/**`,
`src/*.h`, `src/*.cpp` and `**.json`
[.github/workflows/text-changes-analyzer.yml:8-15]. `toc.yml` is scoped to
`doc/` and, additionally, to the upstream repository by an `if:` guard
[.github/workflows/toc.yml:5-13]. Locally there is nothing either: zero
non-sample hooks in `.git/hooks`, `core.hooksPath` unset, and no
`.pre-commit-config.yaml`, `.husky`, `.lintstagedrc` or `package.json`. This
page's correctness therefore rests entirely on the checks recorded in it —
citations that resolve, numbers that were measured, and the transcript-clean
grep — and not on any automation, which is the reason those checks are
written down as commands rather than described.

#### The root `README.md` was deliberately not modified

A generic feature template would have the top-level readme updated. It was
not, and the deviation is recorded with its reason rather than left to look
like an oversight: the base commit is literally
`f38c2fbae3 Merge branch 'CleverRaven:master' into master`, so this is a fork
whose player-facing readme is upstream-synced. Editing it creates a permanent
merge-conflict surface that every future upstream merge has to resolve, in
exchange for documentation that has a better home. `playthrough/README.md` is
that better home — and it does not exist yet, which is recorded below as an
open gap rather than glossed.

#### The commit identity was not configured by this pass

```console
$ git config --local user.name  ;  git config --local user.email
<unset>                            <unset>
$ git config user.name          ;  git config user.email
Blitzy Agent                       agent@blitzy.com
$ git log f38c2fbae3..HEAD --format='%an <%ae>' | sort -u
Blitzy Agent <agent@blitzy.com>
```

Repository-local `user.name` and `user.email` are both empty and were left
empty. The effective identity comes from a higher-scope configuration
(`/root/.gitconfig`, outside this checkout) and is `Blitzy Agent
<agent@blitzy.com>`; every one of the commits on this branch since the base
carries exactly that author and committer.

**That is attribution, not compliance, and the two are recorded separately.**
The AAP requires the identity to be set *repository-locally* (§0.1.1 R1,
§0.1.2, §0.6.2), and it is not. **That element of R1 is UNMET**, the platform
forbids the only two commands that would set it, and closing it is a platform
action in a compliant rerun rather than anything this pass can do. An earlier
draft of this paragraph ended "What matters for the requirement — that commits
are attributable — is measured above and satisfied", which reinterpreted the
requirement into one that had been met; code review rejected that and was right
to. See *"The commit identity: AAP R1's local-identity element is UNMET, and
blocked"* above for the quoted prohibition and the full measurement.

#### The no-cheating claim is auditable, and the audit result is recorded

Three debug actions exist and all three are declared **without** a `bindings`
array, which is what makes them unreachable by any keystroke:

```console
$ python3 - <<'EOF'
... for each of debug_mode, debug, debug_hour_timer in data/raw/keybindings.json
EOF
id=debug_mode         name='Toggle debug mode'          bindings=ABSENT
id=debug              name='Debug menu'                 bindings=ABSENT
id=debug_hour_timer   name='Debug Toggle hour timer'    bindings=ABSENT
```

Their declarations sit at `data/raw/keybindings.json:3402`, `:3408` and
`:3470`. Because that file is **not modified** by this feature — the
blast-radius diff above is the proof — they remain unbound.

User overrides would live at `<userdir>/config/keybindings.json`
[src/path_info.cpp:400-403], and that file is a committed artifact, so its
contents are independent evidence rather than an assertion. The audit:

```console
$ ls playthrough/userdir/config/keybindings.json
ls: cannot access '...': No such file or directory
$ grep -rniE 'debug_mode|debug_hour_timer|"debug"' playthrough/userdir/config/
(no matches)
```

**The file does not exist**, so the gate resolves on its "absent" branch: the
engine never wrote a user keybinding override, therefore no debug action could
have been bound during the session, and nothing anywhere in the committed
configuration tree mentions one. That is the strongest form the evidence can
take — the claim is discharged against the absence of a file rather than
against a promise.

#### Clock readings: OCR is an assist, and the null count is stated

Every clock value in the record is accounted for, because "48.7% of rows have
no clock" is the kind of number that looks alarming until it is broken down:

| Category | Rows | Which |
| --- | ---: | --- |
| exact clock read | 215 | frames 192–194, 198–243, and 166 of the 176 frames from 244 on |
| no clock (`null`) | 204 | frames 1–191 and 195–197 — the creator draws its own full-screen form and there is no sidebar to read — plus ten gameplay frames |
| **total** | **419** | |

The ten gameplay frames with no readable clock are **281, 282, 318, 319, 320,
321, 322, 323, 417 and 419** — ten out of 176 — and the reason for each was
read out of the record rather than assumed:

| Frames | What the row says | Why there is no clock |
| --- | --- | --- |
| 281–282 | `press 'x' -- enter look mode`, then `press 'Left'` | look mode replaces the status column with its own panel |
| 318–323 | `press 'x'`, then four `Right` and one `Down` cursor move | the same, for six consecutive frames |
| 417 | `press 'N' -- decline opening the diary after death` | post-death screen; the survivor is dead and there is no sidebar |
| 419 | `press 'Escape' -- exit the follower epilogue` | the same |

Eight of the ten are one mechanic — the look cursor — and the other two are
the two end screens after death. Not one is an OCR failure. The
timeline's own tally agrees: `clock_kind` is 215 `exact` and 204 `null` with
**zero** `approx`, `reconciled_count` is 204 and every one of them carries
`reconciled_reason: "clock-missing"` — not one row was reconciled because a
reading was *wrong*, only because there was none. `date_kind` is 215 `month`
and 204 `absent`; `date_agreement` is 215 `confirmed` and 204 `unverified`,
with `date_corrected_count` **0** and `date_conflict_count` **0**.

A missing reading is recorded as missing. It is never guessed, and where a
frame's clock had to be reconciled the row says so and the reason says which
kind of failure it was. The exact reader described earlier declines a cell
that is not within four pixels of a glyph of the font that drew it, rather
than returning the nearest thing — deliberately below the six pixels that
separate this face's `0` from its `8`.

#### What could not be verified in this pass, stated rather than smoothed over

* **No build was run.** The `SDL3=0`, `-j`, compiler and detachment findings
  are argued from the Makefile, `pkg-config`, `apt-cache` and the installed
  compilers — all measured — but the assertion "this command produces a
  working binary" was not re-measured in that pass. Nor was a binary present
  in the clone it was written on. A later pass measured an ignored
  `./cataclysm-tiles` of 284 407 600 B reporting `c9b7d915e1 +tiles, +sound`
  in a warmed worktree, which says a build had been run *there* and says
  nothing about the session: the frames are the evidence that a binary existed
  when the session ran, and they carry its own version string, `e50300eeb0`,
  in the picture. See *It is never TRACKED, so a fresh checkout has none — but
  a warmed worktree can*.
* **No game was launched.** Window targeting, the language prompt and the
  first-launch geometry are the session's own observations plus the tooling's
  recorded rationale, not this pass's measurements, and each is labelled that
  way where it appears.
* **The 10.52 s-against-11.75 s truncation symptom** is quoted from the
  earlier development record, not re-measured; the current container is
  correct, so the failing state no longer exists to measure.
* **The plan's `mean=0.270018 std=0.198145` and `08:15:32`** are plan figures
  from another host. Neither reproduces here, and both are labelled *(plan)*
  wherever they appear rather than being quietly replaced.

#### Three artifacts the plan names that do not exist here

`playthrough/README.md`, `playthrough/tooling/run_pipeline.sh` and
`playthrough/tooling/verify_artifacts.sh` are named as items to create and are
absent:

```console
$ for p in playthrough/README.md playthrough/tooling/run_pipeline.sh \
>          playthrough/tooling/verify_artifacts.sh \
>          playthrough/tooling/commit_artifacts.sh; do
>     printf '%-46s %s\n' "$p" "$([ -e "$p" ] && echo PRESENT || echo ABSENT)"
> done
playthrough/README.md                          ABSENT
playthrough/tooling/run_pipeline.sh            ABSENT
playthrough/tooling/verify_artifacts.sh        ABSENT
playthrough/tooling/commit_artifacts.sh        PRESENT
```

This **corrects** the earlier section on this page titled "Four AAP artifacts
that do not exist in this tree": `commit_artifacts.sh` now exists, with 79
passing tests of its own, so the list is three rather than four. The
functional gap left by the two missing scripts is not total — the render
stages are individually runnable and the acceptance checks live in
`test_artifacts.py`, which has 114 passing tests — but there is no single
orchestrator and no single shell-level gate, and that is the honest state.
`playthrough/README.md`'s absence is the more visible one, because this page
defers user-facing material to it in two places.

### Meta observations that had no other home

This section exists so that `playthrough/transcript.md`,
`playthrough/transcript.srt` and `playthrough/dossier.md` can be *verifiably*
clean rather than merely intended to be. Anything below was tempting to write
into the record and belongs here instead.

#### The transcript-clean contract, measured

The check is a deliberately blunt vocabulary scan with no word sense and no
word boundaries:

```console
$ grep -niE 'frame|screenshot|capture|ocr|ffmpeg|moviepy|manifest|timeline|keystroke|xdotool|pipeline|tileset|sidebar|commit|option' playthrough/transcript.md
(nothing)
$ grep -niE 'screenshot|capture|\bocr\b|ffmpeg|moviepy|manifest|timeline|keystroke|xdotool|pipeline|tileset|sidebar|commit|option' playthrough/transcript.md
(nothing)
$ ... same pattern against playthrough/transcript.srt
(nothing)
$ ... same pattern against every commentary field in playthrough/manifest.jsonl
0 hits
$ ... the FULL pattern, including 'frame', against playthrough/dossier.md
(nothing)
```

**Zero** apparatus vocabulary anywhere in the in-character record, on the
blunt pattern as well as the substantive one, and the dossier is clean on
both too.

That top line used to return three hits — `The glass is gone. Step into the
frame.` and two like it, at manifest rows 233, 235 and 237 — and they were
the ordinary English noun, a smashed shop window she was climbing through.
The collision with the apparatus word is gone rather than argued with, and the
substitution is not a euphemism: the game's own message on that capture names
the thing she went through as a window, and the five neighbouring lines about
the same opening already said `window`; these three were the outliers.

**How it is closed matters more than that it is closed, and this is the second
answer to the question.** The first was to change the commentary those three
rows carry — at source, in `manifest.jsonl`, followed by a regeneration of
`transcript.md` and `transcript.srt` from `timeline.json` in one pass. Neither
derivative was hand-edited and every duration, cue, clock reading, date, action
and frame index came out byte-identical, so the pacing and the timing evidence
did not move a millisecond. It was still an edit to captured evidence, and a
Boundary-3 security review rejected it as such (CWE-345) together with the
sixteen closing entries and the eight measured action markers.

So the three rows now read exactly as the session recorded them, and the
correction is amendments 9, 10 and 11 of `playthrough/amendments.jsonl`, each
bound to the sha256 of the manifest line it concerns and each stating the basis
— the game's own message and the five neighbouring lines — and the reason. The
transcripts are regenerated through `manifest.resolve_rows()`, which applies an
amendment only while its digest still matches, so the published in-character
record says `window` and the evidence still says what it always said. See *Three
rows narrated an effect their own capture contradicts* for the ledger's schema
and its fail-closed rules.

This supersedes the earlier counts on this page — three hits at rows
233/235/237, and before that two hits at rows 509/523 with six wording
advisories, which measured the retired capture sets.

#### The dossier's voice register, as a production note

Recorded here rather than in `dossier.md`, because a note about how a voice is
to be maintained is production metadata and would be the one out-of-character
sentence on an otherwise in-character page. The register is: a
forty-seven-year-old maintenance engineer, plain declaratives, short
sentences, concrete nouns, mechanical vocabulary used correctly and without
explanation, no irony, no self-dramatisation, and no vocabulary she would not
have. She says "work shirt" for the garment the game calls a dress shirt
because that is what a woman on shift calls the shirt she works in. She does
not name the interface she is looking at, does not describe her own statistics
as numbers, and does not comment on the fact that any of this is being
recorded. Anyone extending the transcript matches that; anyone tempted to
have her explain a mechanic puts the explanation here instead.

#### Small mechanical facts that are meta by nature

Consolidated from the sections above so that they are findable, since each one
cost time to learn:

* **`}` opens the in-game sidebar manager**, should a layout ever need
  adjusting mid-session. It was not needed: the engine's default
  `legacy_labels_sidebar` was left exactly as it came up, which is also why
  the crop is 352 px wide rather than the plan's 288.
* **`query_yn` is case sensitive on this build** — a lower-case `y` was
  ignored where `Y` was accepted.
* **Shifted punctuation must be sent as an explicit chord.** A bare `!`
  arrives as `1`, i.e. a keypad move. `xdotool` also rejects a bare `.` with
  `Invalid key sequence '.'`, which must be spelled `period` — and that
  failure happens before anything is sent, so it costs no frame.
* **Movement is vikeys**, `h j k l y u b n`; the arrow keys are ambiguous in
  `DEFAULTMODE`, where `UP` is *eat* and `DOWN` is *drop*.
* **`c` (close) auto-selects when exactly one closable door is adjacent** and
  does not prompt for a direction, which is how a correction ended up needing
  a correction of its own.
* **The sidebar message log is oldest-first**, newest at the bottom.
* **A session measurement embedded in a source comment went stale, and the
  correction was to delete the measurement rather than refresh it.**
  `playthrough/tooling/render_movie.py` justified `ENCODE_TIMEOUT = 3600.0` by
  describing "this session's film" as "337 s of 1920x1080 libx264 over 692
  concat entries". That was true of a retired capture set; the published film
  measures 233.04 s over 444 concat entries. The bound it argued for was never
  wrong — an hour is far above either figure — but the sentence was, and a
  comment that has to be re-measured every time the capture set is replaced is
  a standing liability rather than an explanation. It now states the invariant
  instead: the encode is a full libx264 pass over every entry in the concat
  list, so its cost grows with the length of the session, while the probe
  reads container metadata and decodes nothing, so its cost does not.
  `ENCODE_TIMEOUT` and `PROBE_TIMEOUT` themselves were not touched — only the
  rationale was defective — and `test_render_movie.py` reports its full 108
  tests passing after the edit.
* **The general lesson, which is why the entry above outlives its own fix.** A
  figure written into source commentary cannot be re-derived by the reader and
  goes stale silently, because nothing recomputes it. Measurements belong on
  this page, where the pass that took them is stated, or in generated evidence
  that is regenerated with the artifact — the film's real duration, for
  instance, is measured after every encode and compared against
  `timeline.json`. The same reasoning retired the trailing `# <count>`
  annotations that used to sit on the command lines of this page's console
  blocks: a command's output belongs on the line below it, as output, not
  folded into shell-comment syntax on the command itself.

### Corrections that supersede earlier sections of this page

Collected in one place, because this page grew by accretion and a reader
should not have to reconcile four capture sets by hand. Every figure below was
re-measured in the pass that wrote this part; every superseded figure was
correct when it was written.

| Earlier statement | Where | Current measurement |
| --- | --- | --- |
| **the shipped session is Delphine Ouellette's, 419 frames, 233.000 s, with a 27-entry amendment ledger** | **essentially this whole page** | **superseded wholesale.** The tree now holds a **326**-frame session played by **Ambrose Halloran**, totalling **218.500 + 1.000 = 219.500 s**, with **no** amendment ledger (there is nothing to amend: the record was written once and not corrected). Frames, manifest, telemetry, digest ledger, date audit, timeline, both transcripts, both films, the dossier and the userdir were all replaced. The reason is R11: Delphine died, `ACTION_SAVE` is unreachable after death, so the Save & Quit her artifacts implied had never happened — and a captured record cannot be edited into compliance. See *The re-recorded session: Ambrose Halloran* |
| 419-frame counts of every derived artifact — SRT cues, transcript entries, concat entries, transition groups, tracked PNGs | throughout | **326** cues, **326** transcript entries, **338** concat entries, **1** transition group of 12 frames, **326** tracked PNGs |
| 560 frames / 560 rows | the first session log | **419** frames, **419** manifest rows, **419** tracked PNGs, **419** SRT cues, **419** transcript entries — itself now historical; see the row above |
| 395 frames, then a 397-frame correction | the re-record sections | 419; the 395-frame set was retired and re-recorded |
| "frames 1–243 have no clock; frame 244 is the first frame with an exact clock" | the reconciliation section | the first exact clock in this set is **frame 192** (`08:00:00`); 49 frames below 244 carry one |
| "246 of 395 clock readings were reconciled" | same | **204 of 419**, all with `reconciled_reason: clock-missing` |
| the date line's weekday disagreement | its own section | this set reports `date_corrected_count` **0** and `date_conflict_count` **0**; 215 `confirmed`, 204 `unverified` |
| two advisory hits on "frame" at rows 509/523; then **three** at rows 233/235/237 | the transcript-clean section | **none**: the blunt pattern, `frame` included, now returns nothing against `transcript.md`, `transcript.srt` or `dossier.md` — the published entries say `window`, which is the noun the game's own message used, supplied by amendments 9-11 of the ledger rather than by an edit to those three recorded rows |
| 1377 tests across eleven test modules (and 152 earlier still), then 1992, then 2035, 2048, 1998 and 2222 in the individual remediation passes | the suite sections | **2284** tests across **sixteen** modules, `OK (skipped=1)` — see *The tooling's own suites, mechanically counted*, which names the one skip and reconciles every intermediate figure. Each was correct for the tree it was measured in; this one is measured on the integrated tree |
| "four AAP artifacts do not exist" | its own section | **three**: `commit_artifacts.sh` now exists |
| under `-fps_mode vfr` the header's `nb_frames` is "routinely absent" | the packet-counting section | `nb_frames=444` is present and agrees with the packet count |
| "the committed list sums to `301.000000` s" | the transition-remainder section | **`233.000000` s** — 419 capture durations summing to `231.000000` plus 24 transition shares summing to `2.000000`, which is the timeline's declared `total` |
| "`nb_read_packets=540` against 539 planned entries" | the packet-counting section | **444** against **443** planned entries (419 captures + 24 transition frames), the extra packet being the repeated final `file` line |
| `transcript.srt` / `.md` byte-identical at `a67fcce909…` / `c924d91f1d…` and `cata-play-cc.mp4` at `da957b72ee…`; then `6267922b48…` / `fd2f204dd9…` and `3d3a41daf5…`; the film at `5e1344bac9f1…`, 8 051 910 B; both generation manifests binding to timeline `f030d75f65ff…` | the regenerated-chain tables of the 419-frame QA pass, the render tables and `build/movie.json` / the transition provenance | every one of those was correct when it was written, and all of them are superseded. The record was restored to its captured bytes, the narration corrections moved into `playthrough/amendments.jsonl`, and the whole derived chain was regenerated from record-plus-ledger on a supported platform. Current, measured on the integrated tree: `manifest.jsonl` **`c50160309e8b…`** 117 109 B and `build/observations.jsonl` **`78e51463eabb…`** — both byte-identical to the capture; `amendments.jsonl` **`92e5797fb225…`** 129 230 B, 117 rows; `timeline.json` **`8f0dcd4130bf…`** 292 477 B; `transcript.md` **`edaf3195fa98…`** 30 253 B; `transcript.srt` **`afce6be7e33d…`** 37 183 B; `cata-play.mp4` **`5cf3c11e5821…`** 8 051 911 B; `cata-play-cc.mp4` **`386f32f766a7…`** 8 084 371 B; `build/concat.txt` still **`5e7741e8c1b3…`**; `build/transitions.json` **`e65e3ab8a42b…`** and `build/movie.json` **`bfab90c6c346…`**, both naming the current timeline. `cata-play.mp4`, `build/concat.txt` and all 24 transition PNGs came out of that regeneration BYTE-IDENTICAL, which is the strongest available statement that only prose moved |
| the cue file may carry however many lines a sentence needs, with a stderr advisory past four | the caption sections | at most **two** lines of 42 columns, enforced as a refusal naming every offending entry (`CUE_MAX_LINES`); the shipped file is 104 one-line and 315 two-line cues, longest line 42 columns. Nothing is truncated to achieve that and no elision mark exists to reach for — the sentences the transcript publishes were shortened by amendment against the immutable record, and the chain regenerated |
| `transcript.md` opens straight onto "Timestamps are cumulative video time." | the transcript sections | it opens `# Delphine Ouellette — what I did, and why`, then that same line. The title is deliberately the heading `dossier.md` already uses, so a reader arriving at either meets the same person; it carries no timestamp-shaped string and no apparatus word, because exactly one stamp may appear per entry and none anywhere else |
| the 419-frame pointer names *Post-capture verification of `playthrough/frames/`* and "everything from *The session was re-recorded* onward" as the shipped record's sections | the *Read this before any count* block | both of those measure RETIRED sets (560 and 395). The shipped record is documented in *Frame 397 correction after the death ending*, *Runtime QA remediation of the 419-frame record* and *The pipeline as built*, and the pointer now links those three |
| "no checkout of this repository has a binary"; "the binary is absent from this clone" | the build sections | the binary is never TRACKED, so a *fresh* checkout has none — but a warmed worktree that has built carries an ignored one, measured here at **284 407 600** B reporting `c9b7d915e1 +tiles, +sound`. Neither is the session's binary, which is `e50300eeb0` in the frames' own pixels and in the memorial header |
| `make -j4`, "`-j` is sized from `nproc`" | the build-command section | the launcher passes **`-j3`** and caps there (`MAX_BUILD_JOBS=3` readonly, `BUILD_JOBS` default 3, `clamp_build_jobs` reduces anything higher), and its real command line also carries `CCACHE=1` and `COMPILER=`. This container's own provisioning built by hand at `-j5`. Nothing in the tooling derives `-j` from `nproc` |
| frame 221 at `0.194235 / 0.214209` | the luminance-calibration table | **`0.195958 / 0.219861`**, which is both what `convert` reports today and what `build/observations.jsonl` row 221 recorded at capture time; 218 and 219 are the neighbours the old pair sat between |
| the grid is "1920×1072 at `+0+4`" with "a 4-pixel letterbox top and bottom" | the root-window capture section | measured over all **419** captures: 412 frames carry ink in y0–3, 223 reach y1071, and **none** carries a pixel in y1072–1079. The grid sits at **`+0+0`** with one 8-pixel band at the bottom; the crop's `+4` is the centred derivation, which `ocr_clock.py` re-measures per frame anyway |
| "MSXotto+ is **not** in this clone's `gfx/`" | the tileset section | it is never *tracked* (only four `gfx/` entries are), and in a worktree where `launch_game.sh tileset` has run it IS present and ignored — `gfx/MShockXotto+/tileset.txt` reads `NAME: MshockXottoplus` / `VIEW: MSXotto+`, matched by `.gitignore:52` |
| the retired golf-course spawn cites `playthrough/frames/frame_00403.png` | the first session's verification section | that live path has been rewritten twice since; the claim now cites the immutable blob `a50ce8d123c6…` at commit `7117ef9700`, re-read with `ocr_clock.py` to confirm `Place: golf course servic…`. Row 403 of the shipped set is a letter of Delphine's last words, and the shipped spawn is a restaurant at frame 192 |
| "`capture.sh` refuses `PLAYTHROUGH_CAPTURE_AUDIT` *and* `PLAYTHROUGH_CAPTURE_AUDIT_PATH` outright in diagnostic mode"; "An explicit `PLAYTHROUGH_CAPTURE_AUDIT=on` still records one" | the two date-audit sections | refusing the variable's *presence* refused the pipeline's only caller: `launch_game.sh` declares `PLAYTHROUGH_CAPTURE_AUDIT=off` at its probe call site, so the probe exited `EX_USAGE`, the launcher read that as "the screen could not be read", and **every resumed launch published `INITIAL_UI_STATE=unverified`** — the resume proof was structurally disabled. Current contract, one API both scripts hold to: in diagnostic mode `=off` is **accepted** (it names the value the mode forces and can enable nothing), `=on` is **refused**, any `PLAYTHROUGH_CAPTURE_AUDIT_PATH` is **refused** at any value including beside `off`, and anything else is refused by the shared `on|off` case. The launcher additionally treats `EX_USAGE` from the probe as **fatal** rather than as an unreadable screen, so a future disagreement between the two scripts stops the run instead of quietly removing a proof |
| "**The derived stages are deliberately unaffected** … timeline, transitions, render, transcripts and the caption mux can be re-run over an existing record" | the platform-waiver section | **two of the five DO refuse**: `render_movie.assert_trusted_render()` raises "REFUSING to encode the film while the trust state is diagnostic" [render_movie.py:605] and `embed_captions.sh` exits **8** at `playthrough_assert_trusted "the caption mux"` [embed_captions.sh:874]. `timeline.py`, `make_transitions.py` and `make_srt.py` carry no trust gate and are genuinely unaffected. Measured under this host's waiver; both films byte-identical after the probe |
| the declared capture environment is `ubuntu:24.04`, with an eleven-stage table measured there | *The supported release is now DECLARED* | the base is **`ubuntu:26.04`** (EOL 2031-04) and every stage figure was **re-measured** there. 24.04 was rejected on a functional ground the dated table cannot express: its **SDL 2.30.0 delivers no keyboard input to the engine's ImGui screens**, so the character creator cannot be driven, and a full rebuild inside 24.04 (1570 s, 446 objects, compile and runtime both 2.30.0) did not change it. 26.04's **SDL 2.32.10** drives them. Consequences recorded with the base: `g++-14` stays pinned against 26.04's GCC 15 default; SDL3 3.4.2 is now *present* but every `make` still carries `SDL3=0`; and because 26.04 has no `python3.12` while `env.sh` pins that ABI for `requirements.lock`'s `cp312` wheels, the image **builds CPython 3.12.13 from a sha256-pinned python.org tarball** rather than relaxing the closure |
| the 326-frame record carries **no** amendment ledger, "there is nothing to amend: the record was written once and not corrected" | the first row of this table, and *The re-recorded session* | `playthrough/amendments.jsonl` now holds **14** amendments over **11** frames (79–84, 313, 314, 317, 319, 324), sha256 `3e93306d92ad…5825fb68`, attested in `timeline.json` as `{"rows": 14, "applied": 14}`. The record itself is still byte-for-byte what the session wrote; see *Runtime QA remediation of the 326-frame record* for what each amendment corrects and the measurement behind it |
| `transcript.md` opens `# Delphine Ouellette — what I did, and why`, and "the title is deliberately the heading `dossier.md` already uses" | two rows above, and the transcript sections | the file opens **`# Ambrose Halloran — what I did, and why`**, and the title is no longer a literal in `make_srt.py` at all: it is DERIVED from `dossier.md`'s own first heading, so the property that row asserted is now mechanical rather than manual. The earlier statement was the exact defect a runtime QA pass caught — the name in that constant had gone stale when the session was re-recorded |
| rows 78–84 "record keystrokes that had no effect", offered as a blemish | *Three blemishes in this record* | true but incomplete: rows 79–84 also DESCRIBED a list-filter screen that was not on the display. The measurement and the seven amendments that correct it are in *Runtime QA remediation of the 326-frame record* |
| the current `transcript.srt` / `transcript.md` / `cata-play-cc.mp4` digests, and both generation manifests binding to timeline `d04c2d72…` predecessor `e9f2d138…` | the regenerated-chain tables | superseded by the ledger regeneration: `timeline.json` **`d04c2d72849d69ce…`**, `transcript.srt` **`4cdec24bf43d7413…`**, `transcript.md` **`2ec57c3d13df3208…`**, with `cata-play.mp4` still **`23da4ae0210a048a…`**, `build/concat.txt` still **`da6a4cd484fa79c0…`** and all 12 transition PNGs byte-identical |
| "the last captured frame is the main menu it returned to" | the R11 sections written for the 419-frame record | true of that record and NOT of this one: this session's last frame is the death screen's own message log, because the engine was stopped by signal there deliberately. That is also why this tree has no `graveyard/` and no `memorial/` |
| item 3 reads the missing `graveyard/` as purely the *cost* of stopping the engine by signal | *Three blemishes in this record* | true as far as it goes, and the corpse-shaped save is still a real caveat for anyone resuming this world — but `WORLD_END` is committed as `"reset"`, so letting `cleanup_at_end()` finish would have moved the character files into `graveyard/` **and then**, on a now-empty character list, called `delete_world( name, false )` — "Clear out everything except options and mods and compression dictionaries" — emptying `master.gsav`, `o.0.0`, `o.1.0` and `maps/` out of `save/Apshawa/` \[src/do_turn.cpp:142-197\]\[src/worldfactory.cpp:2458-2490\]. Stopping where it stopped is also the only reason there is a save under `save/<world>/` to commit. Measured in *R11's Save & Quit: already documented as UNMET, and this record stops one screen earlier than the last one* |
| R1 is satisfied by a graveyard save, `save/<world>/` correctly holding only `mods.json`, `world_timestamp.json` and `worldoptions.json` | *AAP R11: the ending is legitimate*, and *The ending is a death* | that is the RETIRED record's shape, produced by letting `cleanup_at_end()` finish. This record was stopped inside `death_screen()`, so it has no `graveyard/` at all and R1 is satisfied by the live save directory instead: `save/Apshawa/` still holds `master.gsav`, `dimension_data.gsav`, `o.0.0`, `o.1.0`, `maps/` and the full `#QW1icm9zZSBIYWxsb3Jhbg==.*` set. Both are committed; the route differs |




**The binary that drew the current frames is named in the frames**, and it is
neither of the two commits previously written down. Read off the pixels of the
first and last capture in the committed set, at a whole-screen crop:

```console
$ python playthrough/tooling/ocr_clock.py --rect 1920x1080+0+0 --field text \
      --no-check-options playthrough/frames/frame_00001.png | grep -i version
Version: e50300eeb0
$ ... the same for playthrough/frames/frame_00419.png
Version: e50300eeb0
```

So the 419-frame set was captured with a binary built at `e50300eeb0`, a
commit on this branch. `f38c2fbae3` is the **pre-feature base** and was never
the HEAD any session was captured at; `6dea631409-dirty`, recorded earlier on
this page, was the binary of the retired 560-frame session. All three numbers
are true of different things, which is exactly why the version string is
photographed into the record rather than asserted about it — the frames tie
themselves to their own binary and nobody has to trust a note.

One last reconciliation: the film's total is 233.0 s computed against a
container of 233.040000 s. That is 0.04 s of encoder tolerance, not a
discrepancy.

### The concat demuxer's base directory, probed rather than argued about

Two documents disagreed about how `playthrough/build/concat.txt` should spell
its entries. The plan's note for the list itself says list-relative; the note
for `render_movie.py` says "repository-root-relative with ffmpeg run from the
repo root". Prose cannot settle that, so it was settled against the encoder
that actually reads the file. Both forms were written into
`playthrough/build/` — so that the base directory under test was the real one
— handed to ffmpeg exactly as the render stage hands it the committed list,
and pointed at an output under `/tmp` so nothing derived landed in the tree.

Transcribed as it ran, from the repository root, with `$OUT=/tmp/cc001` — a
per-clone scratch directory outside the checkout:

```console
$ ffmpeg -version | head -1
ffmpeg version 7.1.1-1ubuntu4.2 Copyright (c) 2000-2025 the FFmpeg developers

$ printf "file '../frames/frame_00001.png'\nduration 0.250\nfile '../frames/frame_00001.png'\n" \
      > playthrough/build/_probe_concat.txt
$ ffmpeg -v error -y -f concat -safe 0 -i playthrough/build/_probe_concat.txt \
      -frames:v 1 $OUT/ccprobe_a.png 2>$OUT/probe_a.err ; echo "exit=$?"
exit=0
$ cat $OUT/probe_a.err
(no output)
$ identify -format "%f %wx%h\n" $OUT/ccprobe_a.png
ccprobe_a.png 1920x1080
$ rm -f playthrough/build/_probe_concat.txt

$ printf "file 'playthrough/frames/frame_00001.png'\nduration 0.250\nfile 'playthrough/frames/frame_00001.png'\n" \
      > playthrough/build/_probe_concat.txt
$ ffmpeg -v error -y -f concat -safe 0 -i playthrough/build/_probe_concat.txt \
      -frames:v 1 $OUT/ccprobe_b.png 2>$OUT/probe_b.err ; echo "exit=$?"
exit=254
$ cat $OUT/probe_b.err
[concat @ 0x5baf2f240ec0] Impossible to open 'playthrough/build/playthrough/frames/frame_00001.png'
[in#0 @ 0x5baf2f240cc0] Error opening input: No such file or directory
Error opening input file playthrough/build/_probe_concat.txt.
Error opening input files: No such file or directory
$ rm -f playthrough/build/_probe_concat.txt
```

**List-relative is the form, and the repository-root-relative spelling is not
a stylistic preference but a hard failure.** The diagnostic names the base
directory out loud: ffmpeg looked for
`playthrough/build/playthrough/frames/frame_00001.png`, which is the list's
own directory with the entry appended, from a working directory that was the
repository root in both runs. So the committed list carries
`../frames/frame_00001.png` for a capture and `transitions/trans_00315_00.png`
for a transition frame, one form throughout, no absolute path anywhere, and
the committed artifact is itself runnable — which is the property that makes
"the encoder was handed this file" checkable rather than claimed. The probe
list was removed from `playthrough/build/` in the same breath it was written,
and both probe images were written to `/tmp`; `playthrough/build/` still holds
only what its stages publish.

The whole-list form was then proven at scale, because a two-entry probe
establishes the base directory and nothing about the other 442 entries. The
plan's own fixed command was run verbatim against the committed list, to an
output under `/tmp`:

```console
$ ffmpeg -y -f concat -safe 0 -i playthrough/build/concat.txt -fps_mode vfr \
      -pix_fmt yuv420p -c:v libx264 -crf 20 -s 1920x1080 -movflags +faststart \
      $OUT/aap_form_check.mp4 > $OUT/aap_encode.log 2>&1 ; echo "exit=$?"
exit=0
$ grep -c "No such file or directory" $OUT/aap_encode.log ; \
  grep -c "Impossible to open" $OUT/aap_encode.log
0
0
$ ffprobe -v error -select_streams v:0 -count_packets \
      -show_entries stream=codec_name,width,height,nb_read_packets \
      -of default=nw=1 $OUT/aap_form_check.mp4
codec_name=h264
width=1920
height=1080
nb_read_packets=444
$ ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 \
      $OUT/aap_form_check.mp4
233.040000
```

All 444 entries resolved and neither fatal symptom appeared once.

One incidental result came out of that run and is recorded here so nobody
later reads it as a defect. The plan's command omits `-bf 0`, which the render
stage does pass, so the two containers differ in exactly that one argument —
and their timing is identical:

| | plan's command (B-frames on) | render stage (`-bf 0`) |
| --- | --- | --- |
| `has_b_frames` | 2 | 0 |
| stream `duration` / `duration_ts` | 233.040000 / 2982912 | 233.040000 / 2982912 |
| `format=duration` | 233.040000 | 233.040000 |
| `nb_frames` | 444 | 444 |
| size | 7 670 058 B | 8 051 910 B |

So on ffmpeg 7.1.1 the reorder delay does **not** shift the track duration,
and the earlier claim on this page that zero B-frames is "the only way the mov
muxer writes a track duration that matches the timeline" is not reproducible
here — the only measurable difference is 382 KB of bitrate. The argument is
kept regardless: it costs nothing, the hazard it closes is real on builds where
the muxer does trail the last PTS, and a still-image film gains nothing from
B-frames. What is corrected is the reason given for it, not the flag.

### The committed concat list is the emitter's output, re-derived to prove it

The list is not hand-authored and the claim is worth more than an assertion,
so it was re-derived from `playthrough/timeline.json` three independent ways
and compared on the bytes each time.

| Route | Result |
| --- | --- |
| `plan_render` + `format_concat_list` called in process against the committed timeline | 21 491 B, `sha256:5e7741e8c1b38e1176866dba40e6b6cce276e98730785cd201859e463740770b` |
| `render_movie.py --concat-only`, publishing over the committed path | byte-identical; `git status --porcelain` stayed **empty** |
| the same command against a hardlinked copy of the tree under `/tmp`, so a different absolute location produced the list | byte-identical, same digest |

The third route also ran the encode to completion in that temporary tree, and
the film it produced is byte-identical to the committed one:
`sha256:5e1344bac9f1dbf04501ec028d654e210f6bfdc5dd6a4eff296fb2db4d59db9d`,
8 051 910 B, reported by the stage itself as "419 capture(s), 2 transition
group(s), 443 concat entries, expected 233.000 s, container 233.040 s
(+0.040 s)". A list that reproduces its own film from a different directory is
the strongest available statement that nothing in it depends on this
checkout's location and nothing in it was authored by hand.

The list's own arithmetic, re-measured on the committed bytes rather than
recomputed from the timeline:

| Property | Measured |
| --- | --- |
| `file` lines / `duration` lines | 444 / 443 — the identity `file == duration + 1` |
| distinct images referenced | 443 — 419 captures + 24 transition frames |
| repeated terminal entry | `../frames/frame_00419.png`, duplicating the preceding `file` line, with no `duration` after it |
| capture durations | all at three decimals, every one equal as a **string** to the timeline's own value; all within `[0.250, 10.000]` |
| transition shares | eleven at `0.083333` and one at `0.083337` per group; each group sums to exactly `1.000000` by integer-microsecond arithmetic |
| grand total | `231.000000 + 2.000000 = 233.000000` s = the timeline's `total` = its `final_cue_end` |
| coverage | the emitted capture set equals `playthrough/frames/frame_*.png` exactly — symmetric difference empty |
| transition placement | group 315 sits between `frame_00315.png` and `frame_00316.png`, group 316 between `frame_00316.png` and `frame_00317.png`; no transition frame follows any unflagged entry |
| bytes | LF throughout, one trailing newline, no BOM, no tab, no `#` comment, no `ffconcat` header, no absolute path, no directive other than `file` and `duration` |

Every row above was produced by one instrument — a 22-check gate run over the
committed bytes, which printed each measured value rather than a pass word and
finished `22 checks, 0 failure(s)`. It is deliberately not a committed file:
the properties it checks are already asserted by `render_movie.py` itself and
covered by `test_render_movie.py`'s 108 tests, so a second copy in the tree
would be a third place for the same rules to drift. Alongside it, the whole
tooling suite reports **2284 tests across sixteen modules, all OK** with the
single named skip, and both `flake8 playthrough/` and `make python-check`
report **zero findings**.

### The derivative chain, regenerated on a supported platform

Three places on this page point here, so this is the section that says where
each shipped artifact was actually produced and what its digest is.

**Why this had to happen somewhere else.** The platform policy described in
*The one relaxable check that was not treated as one* left this host unable to
produce production media at all, and that is the intended consequence rather
than an accident of the fix. This machine is Ubuntu 25.10 "questing", which is
past end of standard support, so with `PLAYTHROUGH_ALLOW_EOL_PLATFORM` set the
waiver is now a registered trust bypass and the trust gate refuses; without it
the platform gate refuses one step earlier. Both refusals were measured, in all
four stages. A remedy that merely printed a warning here would have been the
same non-control the review rejected. The consequence is that the chain had to
be regenerated on a platform that satisfies the gate honestly, and it was.

**The platform.** A container built from `ubuntu:24.04`, fully updated, holding
the capture, decode and encode programs the policy exists to constrain and the
hash-locked pins from `playthrough/tooling/requirements.txt`:

```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get -y upgrade && apt-get -y install --no-install-recommends \
      ffmpeg imagemagick tesseract-ocr tesseract-ocr-eng \
      coreutils findutils grep sed gawk bash git \
      python3 python3-venv python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/playthrough-venv && /opt/playthrough-venv/bin/pip install --no-cache-dir --upgrade pip
COPY requirements.txt /tmp/requirements.txt
RUN /opt/playthrough-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
```

Tagged `playthrough-supported:24.04`, 889 MB, and measured from inside rather
than assumed about:

| Property | Reading inside the container |
| --- | --- |
| platform | `PRETTY_NAME="Ubuntu 24.04.4 LTS"`, `VERSION_ID="24.04"`, `ID=ubuntu`, kernel `6.12.85+`, `x86_64` |
| ffmpeg / ffprobe | `6.1.1-3ubuntu5` |
| ImageMagick | `6.9.12-98 Q16` — the maintained legacy branch, so `import`, `convert` and `identify` are the callable names |
| tesseract | `5.3.4` |
| Python | `3.12.3` at `/opt/playthrough-venv` |
| pins | `moviepy 2.2.1`, `pillow 11.3.0`, `pytesseract 0.3.13`, `numpy 2.5.1`, `imageio 2.37.4`, `imageio-ffmpeg 0.6.0` — every one exactly as `requirements.txt` pins it |

**The trust reading there, which is the whole point.** `env.sh` was sourced
inside the container and asked, not told:

```console
platform gate exit=0
PLATFORM=[Ubuntu 24.04.4 LTS] SOURCE=[/etc/os-release]
SUPPORTED=[yes] EOL=[2029-04] WAIVER=[]
TRUST_STATE=[trusted] BYPASSES=[]
assert_trusted exit=0
```

Four things in that reading matter. `WAIVER` is empty, so nothing was waived.
`BYPASSES` is empty, so no trust bypass of any kind is in effect.
`SOURCE=/etc/os-release` is the real file, so the `PLAYTHROUGH_OS_RELEASE`
sandbox nomination played no part — and it could not have, because the clone is
bind-mounted at its own absolute path and its `.git` directory is therefore
present, which is exactly the condition under which the resolver ignores a
nomination. And `EOL=2029-04` is in the future. The platform is supported on
the evidence the gate reads, not on a declaration handed to it.

The invocation, for the record, is
`docker run --rm -v "$REPO:$REPO" -w "$REPO" playthrough-supported:24.04 bash <script>`.
Mounting the clone at its own path rather than at `/work` is deliberate: it
makes `PLAYTHROUGH_REPO_ROOT` resolve to the identical string inside and out,
so no generation manifest can acquire a host path that differs from the one the
committed tree knows, and `test_artifacts.py`'s
`test_no_generation_manifest_carries_a_host_path` stays meaningful.

**The evidence chain was verified before anything was regenerated**, in that
same container, because regenerating from an unverified record would defeat the
purpose of having restored it:

```console
manifest ok: 419 row(s)
amendments ok: 27 amendment(s)
digests ok: 419 frame(s) attested, 419 row(s)
```

**The stages, each reporting its own numbers.** Run in dependency order:

| Stage | What it reported |
| --- | --- |
| `timeline.py` | `419 frame(s), 2 transition(s), 204 reconciled clock(s), 231.000 + 2.000 = 233.000 s` |
| `make_transitions.py` | `2 flagged entry(ies), 2 group(s), 12 frame(s) each, 24 file(s) written, 25 file(s) replaced` |
| `render_movie.py` | `419 capture(s), 2 transition group(s), 443 concat entries, expected 233.000 s, container 233.040 s (+0.040 s), movie playthrough/cata-play.mp4 (8051911 bytes)` |
| `make_srt.py` | `419 entr(ies), 419 cue(s), 419 stamp(s), last cue closes at 00:03:53,000 = the timeline's own total of 233.000 s` |
| `embed_captions.sh` | `SUBTITLE_LANGUAGE=eng SUBTITLE_DURATION=233.000000 CUES_IN=419 CUES_ROUND_TRIP=419 CONTAINER_DURATION=233.040000`, and `8088658 bytes, h264 1920x1080 copied intact (stream-hash-sha256), with 419 cues on a selectable mov_text track tagged eng` |

`timeline.py` emitted two warnings and both are honest: 419 date-audit rows are
unbound to a capture digest, because they were written before the digest ledger
existed and a row cannot acquire a binding retroactively without inventing one;
and 204 clock readings are reconciled, which is the same 204 recorded
everywhere else on this page.

**The nine artifacts, before and after.** "Before" is the state produced on
this host earlier in the work, now superseded; "after" is what is committed.

| Artifact | Bytes | sha256 | Verdict |
| --- | --- | --- | --- |
| `playthrough/timeline.json` | 296 850 | `1a93f27895b39675…` | **identical** |
| `playthrough/transcript.md` | 34 540 | `fd2f204dd9706d53…` | **identical** |
| `playthrough/transcript.srt` | 41 470 | `6267922b4832dc7f…` | **identical** |
| `playthrough/build/concat.txt` | 21 491 | `5e7741e8c1b38e11…` | **identical** |
| `playthrough/build/transcript.json` | 530 | `313a51ac2b7cc64a…` | **identical** |
| `playthrough/build/transitions/*.png` | 24 files | unchanged in `git status` | **identical** |
| `playthrough/build/transitions/generation.json` | 5 455 | `e2c6fd5da066fa01…` → `2abe9d5478c328af…` | changed, one line |
| `playthrough/build/movie.json` | 619 | `6dc2c2a257fba4b3…` → `709b73957508b01c…` | changed, three lines |
| `playthrough/cata-play.mp4` | 8 051 910 → 8 051 911 | `5e1344bac9f1dbf0…` → `5cf3c11e58216259…` | changed, one byte longer |
| `playthrough/cata-play-cc.mp4` | 8 088 657 → 8 088 658 | `3d3a41daf504eda4…` → `2498610d36db4287…` | changed, one byte longer |

**Exactly two things changed, and both were supposed to.** The first is a
correction: both generation manifests had been left binding to
`f030d75f65ff221d…`, the digest of a timeline that the restoration superseded,
while `build/transcript.json` already named the current one. All three now name
`1a93f27895b3967563c1f885a97ea15624a9395d37942f3f298a990bb6665fbd`, which is
the actual digest of the committed `timeline.json` — measured, not copied from
a manifest. `test_artifacts.TestTheRenderContract` asserts precisely that
agreement in three separate tests, and those three were failing until this pass
closed them. A generation manifest that names a superseded timeline is a
derivative claiming a parent it does not have, which is the same class of
defect as the one the review found, so it is worth naming plainly rather than
folding into "regenerated".

The second is one byte in each container, and its cause is the platform change
itself: this host has ffmpeg 7.1.1, the supported container has 6.1.1, and two
encoder builds write a marginally different MP4 container around identical
pixels. The pixels really are identical — `build/concat.txt` is byte-identical,
so the encoder was handed the same 443 images in the same order with the same
durations, and every stream property below matches what the earlier film
reported. This is the honest cost of moving the encode to a platform that
satisfies the gate, and it is a byte of container padding rather than a frame
of picture.

**The five identical text artifacts are the real result.** `timeline.json`
carries the manifest digest, the amendment ledger digest, all 419 durations,
clamps, transition flags and cue windows; `transcript.md` and `transcript.srt`
carry all 419 published sentences. That those four files plus
`build/concat.txt` came back byte for byte, regenerated on a different
distribution with a different ffmpeg from the **restored** record plus the
27-row amendment ledger, is an independent proof of two claims this page makes:
that the ledger reproduces exactly what the edited record used to say, and that
the pacing was never touched by any of it. The 24 transition PNGs came back
identical too — `git status` reports no change to any of them, and each still
matches its digest in `generation.json` — so MoviePy's fade mathematics and
Pillow's text composition are deterministic across these two platforms.

`playthrough/frames/**` was not regenerated and could not be. Those 419 PNGs
are the photographed record; they were captured on this EOL host before the
policy existed, the digest ledger says so in every row by attesting them as
`commit` rather than at capture time, and the residual is disclosed in
*Nothing had ever recorded what a frame's bytes were*. A platform policy
constrains the next
capture. It cannot re-photograph a past one, and pretending otherwise would be
the fabrication the whole page is written to avoid.

**The verification battery, measured inside the container on the shipped
bytes.** Container and streams:

| Check | `cata-play.mp4` | `cata-play-cc.mp4` |
| --- | --- | --- |
| video stream | `index=0 codec_name=h264 codec_type=video` | `codec_name=h264` |
| resolution | `1920x1080` | `1920x1080` |
| frame count | `nb_read_packets=444` | `nb_read_packets=444` |
| duration | `233.040000` | `233.040000` |
| size | `8051911` | `8088658` |
| subtitle stream | — | `index=1 codec_name=mov_text TAG:language=eng` |

444 packets is 443 planned concat entries plus the repeated terminal `file`
line, which is the same arithmetic recorded in the packet-counting section.

Non-blank rendering, `convert … -colorspace Gray -format "%[fx:mean]
%[fx:standard_deviation]"`, on four sampled captures and on three frames
extracted from the finished captioned film:

| Sample | mean | std |
| --- | --- | --- |
| `frame_00001.png` | 0.00493656 | 0.0621146 |
| `frame_00100.png` | 0.0167647 | 0.0916554 |
| `frame_00250.png` | 0.148222 | 0.208645 |
| `frame_00419.png` | 0.00392848 | 0.0546159 |
| `cata-play-cc.mp4` at 5 s | 0.0166269 | 0.0880476 |
| `cata-play-cc.mp4` at 120 s | 0.0622532 | 0.106731 |
| `cata-play-cc.mp4` at 230 s | 0.0662749 | 0.136488 |

Every mean is above zero and every standard deviation is above zero, on both
the source pixels and the decoded film, which is the assertion that would have
failed loudly had `SDL_VIDEODRIVER=dummy` or a solid-colour frame ever reached
the encoder. The first and last captures are dark screens and their means are
small; the standard deviation is what distinguishes a dark screen with text on
it from a black one, and that is why the gate requires both terms.

The arithmetic and the counts, recomputed from the frame list rather than read
off the declared aggregates:

| Property | Measured |
| --- | --- |
| `sum(durations) + sum(transitions)` | `231.000 + 2.000 = 233.000` s |
| declared `total_duration` / `total_transition` / `total` / `final_cue_end` | `231.000` / `2.000` / `233.000` / `233.000` — all agreeing |
| last frame's `cue_end` == `total` | yes |
| every `duration` within `[0.25, 10.0]` | yes, no exceptions |
| `transition_after` ⇔ `raw_delta > 10.0` | yes, no exceptions |
| cue windows tile the timeline with the transition second charged | yes, zero drift across 419 entries |
| frames on disk / manifest rows / timeline entries / attested digests | `419 / 419 / 419 / 419` |
| frame indices | contiguous `1..419` |
| SRT cues / `transcript.md` stamps / timeline frames | `419 / 419 / 419` |
| every markdown stamp equals its cue start | yes |
| every cue window equals its timeline window | yes |
| cue ids | contiguous `1..419` |
| every entry carries a non-empty `action` and `commentary` | yes |
| the three generation manifests name the committed `timeline.json` | yes, all three |

#### The same chain, regenerated once more when three reviews were combined

Three code reviews were remediated against this boundary in parallel — a
performance pass, a completeness pass, a documentation pass and a security pass
— and combining them changed what the derived chain has to be computed from.
This subsection records that regeneration, because two of its consequences are
contract changes rather than artifacts.

**What the corrections do and where they live.** The documentation review found
100 of the 419 commentaries reaching for interface and mechanics vocabulary, or
running longer than a cue can show, in a record specified to be the survivor's
voice. The completeness and security reviews found, independently, that the
record must never be edited. Both are right, and the amendment ledger is what
holds them at once: `playthrough/manifest.jsonl` and
`playthrough/build/observations.jsonl` stay byte-identical to the bytes the
session wrote, and `playthrough/amendments.jsonl` now carries **117** rows —
the 8 observed-effect action corrections, plus 109 narration corrections, each
bound to the sha256 of the exact manifest line it concerns and each stating a
MEASUREMENT as its basis: 71 name the line count the recorded sentence wraps to
against the two-line contract, 11 name the concepts
`manifest.find_meta_vocabulary()` matches in it, 17 name both, and one names
the bare attribute number the recorded sentence opens with. Ten narrations had
been corrected by two reviews; one narration carries one amendment, so those
rows carry the shorter sentence and say in their own basis that a second review
found the first correction longer than a cue can show.

**Where the two narration gates are applied, which is the contract change.**
The voice gate and the placeholder sentinels are checks on the two AMENDABLE
fields, and they used to run against the recorded rows. On the combined tree
that refused 28 captured rows outright: `timeline.py` would not pace a film at
all and `manifest.py verify` reported 28 problems, for a session whose
corrections were all properly recorded. A recorded row is not editable, so
refusing it for a narration defect leaves no honest way forward. They therefore
run against the rows `manifest.resolve_rows()` returns — the sentences that
actually reach `playthrough/transcript.md` and the caption track — while the
structural schema still runs against the record itself. Nothing is skipped: an
unamended meta word survives resolution unchanged and is refused in the same
words, and `manifest.py verify` proves it by resolving the ledger before it
checks. `manifest.row_problems(..., narration=False)` is the one caller of that
distinction, and `commit_artifacts.sh` asks the ledger before it asks the record
so a broken binding still gets the ledger's own remedy rather than "the record
was refused".

**The caption contract, where two remediations met.** One pass restored a
two-line cap and marked a shortened caption with a bracketed elision; another
removed every truncation and made an over-long cue a publication-blocking
refusal that names each offender. The refusal is what shipped, because it is
what both reviews' own resolutions asked for — "enforce the two-line contract
without post-capture truncation", "fail generation with actionable frame/cue
identifiers … retain full text by shortening the source" — and because the
amended sentences make it unnecessary to cut anything: the published file is
**104 one-line and 315 two-line cues**, longest line 42 columns, nothing
elided, and `make_srt.CUE_ELISION` does not exist for a later pass to reach
for. The geometry is asserted three times over: at generation, in the renderer
whatever assembled the cue, and on the bytes of the published file.

**Two duplicated controls, resolved rather than left.** The environment summary
printed `PLAYTHROUGH_PLATFORM_SOURCE` twice — each pass added the line — which
its own test forbids as the signature of a copied continuation; it prints once.
And two platform-source resolvers existed: the surviving one honours a
nomination only in a tree git does not track, and the weaker twin, which
honoured it anywhere, is deleted rather than left unused, because a later caller
reaching for it would have undone the property silently. The surviving resolver
also picked up the stricter of the two behaviours it had to choose between: a
nominated path that is a SYMBOLIC LINK is never followed, since a link can be
repointed between the resolution and the read.

**The platform, and the trust reading, again asked rather than told.** The
regeneration ran in a container rebuilt from the `ubuntu:24.04` recipe recorded
above, with this clone bind-mounted at its own absolute path — so `.git` is
present and the nomination seam is inert by construction — and the pinned
interpreter mounted read only:

```console
platform gate exit=0
PLATFORM=[Ubuntu 24.04.4 LTS] SOURCE=[/etc/os-release]
SUPPORTED=[yes] EOL=[2029-04] WAIVER=[]
TRUST_STATE=[trusted] BYPASSES=[]
assert_trusted exit=0
ffmpeg version 6.1.1-3ubuntu5
```

**What moved and what did not.** The stages ran in dependency order —
`timeline.py`, `make_transitions.py`, `render_movie.py`, `make_srt.py`,
`embed_captions.sh` — and reported `419 frame(s), 2 transition(s), 204
reconciled clock(s), 231.000 + 2.000 = 233.000 s`, `24 file(s) written`, `443
concat entries, expected 233.000 s, container 233.040 s`, `419 entr(ies), 419
cue(s), 419 stamp(s)`, and a mux with `CUES_IN=419 CUES_ROUND_TRIP=419`.
`playthrough/cata-play.mp4` came out **byte-identical** at `5cf3c11e5821…`,
8 051 911 B, `build/concat.txt` byte-identical at `5e7741e8c1b3…`, and all 24
transition PNGs byte-identical — an independent reproduction of the previous
supported-platform encode from the same 443 images, and a demonstration that a
correction to prose moves no pixel and no duration. `timeline.json`,
`transcript.md`, `transcript.srt`, `build/transcript.json`, `build/movie.json`,
`build/transitions.json` and `cata-play-cc.mp4` were rewritten; their digests
are in *Corrections that supersede earlier sections of this page*. The captioned
film is 8 084 371 B, one byte larger than the same mux performed by this host's
ffmpeg 7.1.1 over identical packets, which is the container-writer difference
already recorded above and not a difference in the picture or the cues.

**One untracked input needed repair, and it is named because it is untracked.**
`gfx/` is git-ignored, so the installed MSXotto+ tree is the one input the
anchor cannot carry. This worktree's copy had been installed before the anchor
existed and was missing the in-pack `SHA256SUMS` the anchor names, so
`tileset_provenance.verify()` refused it — correctly. The file was restored from
the composed cache and re-verified against the tracked anchor:
`TILESET_PROVENANCE_TREE_SHA256=3d6c2ef4871654fd…`, `FILES=22`,
`UPSTREAM_COMMIT=6e864adbd2c5d0e6…`.

### No user-specified rules exist for this project

`review_rules` returns "No user rules provided", and that was read in full
rather than skimmed. Nothing has been invented to fill the gap and the bar is
not lowered; enterprise-standard practice governs instead. For this page in
particular, that resolves to five concrete obligations, each of which is
discharged somewhere specific above rather than asserted here:

* **Evidence over assertion.** Every claim carries a `[path:locator]` at the
  point of use and every number states the command that produced it. Figures
  that came from the plan rather than from this host are marked *(plan)*, and
  each one that does not reproduce is named where it appears — six in the host
  table, plus the luminance calibration, the OCR reading, the sidebar crop and
  the lint findings in their own sections.
* **Make integrity claims auditable.** The no-cheating guarantee is
  discharged against a committed artifact — the absence of
  `userdir/config/keybindings.json` and the unbound declarations in
  `data/raw/keybindings.json` — rather than against anyone's word.
* **Minimise the blast radius.** Two modified files, 26 inserted lines, zero
  deletions, proof pasted rather than summarised.
* **Do not create merge-conflict surfaces in upstream-synced files.** The
  root `README.md` is untouched and the reason is recorded with the decision.
* **Fail loudly, never silently.** Six silent failure modes are documented
  above, each with the measurement that makes it loud: a save committed in
  appearance only (the before/after `git add --dry-run`), a film that is
  entirely black (the two-term luminance gate with both its controls),
  captions that drift (the frame 315/316 cue arithmetic), a film in the wrong
  artwork (`resolve_tileset` failing closed rather than falling back), an
  option that is present but inert behind an unmet prerequisite
  (`USE_TILES`, and `USE_DISTANT_TILES` one level down), and bytecode
  committed by accident (`PYTHONDONTWRITEBYTECODE`, with the two-arm control
  run after the hazard actually fired). Where a guard exists, its *controls*
  are measured too — a gate nobody has watched fail is a gate nobody has
  tested.

One thing this page cannot do is stand in for the missing
`playthrough/README.md`. It is the engineer-facing document by design; the
user-facing one is still owed.
