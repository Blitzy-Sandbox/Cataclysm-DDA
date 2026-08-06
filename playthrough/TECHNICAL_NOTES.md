# Technical notes

The engineering record for the playthrough capture. Everything that is a
decision about the machinery, a measurement taken from this checkout, or an
observation about how the pipeline behaves belongs here — and nowhere else.

`playthrough/dossier.md` is Delphine Ouellette's own account of herself,
written before the first keystroke, and it is hers entirely: no point
accounting, no option values, no source citations, no notes about how any of
it was arranged. She would not write a page like that and does not think
about herself in those terms. Keeping the two apart is what makes the
in-character record worth reading as a record rather than as a commentary,
so the mechanical half of the character lives on this page instead.

Every value below was read out of this checkout at the stated location. Where
a number is quoted, it is the shipped value in this tree and not a value
remembered from another version.

## Read this before any count on this page

**Two blocks of this page describe capture sets that no longer exist, and each
says so at its own heading — a long way below the content it retracts.** A
runtime QA pass pointed out that a reader who starts at the top meets those
numbers first and the disclaimer last, so the pointer belongs here:

* **[The session was re-recorded, and this section supersedes every count
  above](#the-session-was-re-recorded-and-this-section-supersedes-every-count-above).**
  Everything ABOVE that heading is the **first, 560-frame session**, which was
  rejected at code review and retired. Every "560" on this page, and the
  frame-by-frame narrative of the abandoned first creation run at *The
  interrupted capture at frame 177* — including its `real_ts` and luminance
  figures, which do not match the frame 177 in the tree today — belongs to
  that retired set.
* **[Runtime QA remediation of the earlier 395-frame capture
  set](#runtime-qa-remediation-of-the-earlier-395-frame-capture-set).**
  Every frame number and every "out of 395" count in that section belongs to a
  second retired set. It is kept because the engine behaviours it pins down and
  the tooling it produced are still in force.

`playthrough/frames/` holds **419 frames** — one per keystroke of the session
that shipped — with 419 manifest rows and 419 telemetry rows. Any count on this
page that is not 419 is describing a retired set; the sections that do describe
the shipped record are *Post-capture verification of `playthrough/frames/`* and
everything from *The session was re-recorded* onward.

---

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
(2028-06) also pass. Moving the capture and render workload to any of them
removes the condition entirely; nothing in the pipeline depends on 25.10.

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

**It is deliberately NOT a trust bypass**, and the distinction is worth
recording rather than leaving to be rediscovered. A variable in
`PLAYTHROUGH_TRUST_BYPASS_VARS` means *a check that establishes the evidence
was relaxed, so a reading might be wrong* — `PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X`,
for instance, means another local account could have injected keystrokes, which
falsifies the record directly, and `capture.sh` refuses production capture
while any bypass is active. An end-of-life platform makes no reading wrong: it
raises the risk that a parser has an unfixed defect, which needs hostile input
to matter, and the only images this pipeline decodes are the PNGs it captured
itself on a host that opens no network connection. Putting it in that registry
would refuse every recorded session on the only available host while adding
nothing the summary does not already carry.

`PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM` is retired and *answered* rather than
ignored: `=1` is now the default and says so, and `=0` no longer weakens
anything and says that, because an operator who set a variable believing it
configured something has to be told it did not.

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
`NAME: MshockXottoplus` in [gfx/MShockXotto+/tileset.txt]. The close-range
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
frame reads `Place: golf course servic…` [playthrough/frames/frame_00403.png],
and the scenario's own `allowed_locs` list runs to twenty-five locations —
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
the environment summary, and travels with the session's contract. The waiver
is deliberately not a member of `PLAYTHROUGH_TRUST_BYPASS_VARS`: it relaxes
nothing about tool trust, path confinement or artifact verification.

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

## The commit identity, and why nothing here configures it

Code review found repository-local `user.name` and `user.email` empty and
asked for "the required local identity through the platform-approved
mechanism". Those are two different things on this host, and the difference is
worth writing down because the obvious reading of that sentence is the one
thing that must not be done.

**The platform-approved mechanism is the ambient identity, not a repository
setting.** Every commit on this branch is required to be authored and committed
as `Blitzy Agent <agent@blitzy.com>`, and the platform supplies exactly that
through git's own configuration outside this checkout. Measured, read-only:

    $ git var GIT_AUTHOR_IDENT
    Blitzy Agent <agent@blitzy.com> 1785867294 +0000
    $ git var GIT_COMMITTER_IDENT
    Blitzy Agent <agent@blitzy.com> 1785867294 +0000

So the identity was never missing. What was missing was a *repository-local
copy* of it — and writing that copy is forbidden here, because a script that
sets `user.name` and `user.email` can set them to anything, and a host whose
whole rule is "one fixed identity" cannot distinguish a helpful copy from an
override. Every commit in this history already carries the right name, which is
the property the review was actually after.

`playthrough/tooling/commit_artifacts.sh` therefore **asserts** the identity
and never writes one. `git var GIT_AUTHOR_IDENT` is the right question to ask
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

### Three rows narrated an effect their own capture contradicts

Frames 292, 293 and 364 record keystrokes that were genuinely pressed and
genuinely photographed, with clock readings that are independently reproducible
— and notes that say the wait was interrupted and that look mode was entered. It
was not. In each case a `(Case Sensitive)` modal was already on the screen and
swallowed the key: frame 292 is byte-identical to 291, 293 to 292, and 364 to
363, and look mode demonstrably replaces the whole sidebar column, which those
frames still show. The keys, the frames and the clocks are all sound; the
human-authored *effect* clause on three rows out of 419 is not.

This is the defect class the observed-effect guard exists for, and the guard
already handles it: it compares each capture with the one before it, before the
row is appended, and appends `; nothing on the screen changed` when not one
pixel differs. It simply post-dates these captures. So the guard was run over
the record retroactively, with the same measurement on the same evidence, by a
new `session.py annotate` subcommand.

**What the measurement found, over all 419 frames:** eight captures are
byte-identical to their predecessor —

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

All eight now carry the marker, not only the three QA named. The marker states
what was **measured** and nothing else, it is true of all eight captures, and
leaving five of them unmarked would have made its presence depend on a human
judgement about which narration overstates itself — which is the very thing the
guard replaces. The five were already honest (a space that types is not a key
that was ignored, and frame 41 is admitted at frames 42 and 64); they are now
also *complete*.

**What was and was not touched.** The append is to the `action` field only. No
commentary, no clock, no timestamp, no filename and no frame changed — verified
field by field against the previous commit: exactly eight rows differ, and in
every one of them the only differing key is `action`. The telemetry sidecar's
`action` was extended in step, because every integrity check compares the two,
and the counts stayed 419 / 419 / 419. The marker is appended, never
substituted: `manifest.extend_action()` and `session.extend_observation_action()`
both refuse text that does not begin with what was already recorded, refuse a
change to any other field, re-validate the whole record through the writer's own
gate afterwards, and write atomically.

**The pass is deliberately limited to what it can honestly measure.** It
classifies with no sidebar crop, so the only verdict it can reach is
`unchanged` — the whole-screen one. The `outside-map` verdict needs the sidebar
geometry of the session that took the frame, a measurement these captures never
had, and a row whose narration is accurate must not be rewritten on a
measurement taken long after the keystroke. Without `--apply` the command only
reports, which is how this was read before anything was written.

**One tooling defect surfaced by that pass, and fixed.** Ten of the 418 pairs
came back UNMEASURABLE, all for the same reason: ImageMagick prints an FX result
with six significant digits, so a count of 1,027,832 changed pixels arrived as
`1.02783e+06`, which is not a count. Every pair differing by a million pixels or
more was therefore unmeasurable — which is exactly what a scene transition is,
so the verdict was silently unavailable for the most visually significant steps
of any session. `measure_difference()` now passes `-precision 16`, and all 419
frames measure: `EXAMINED=419, MARKED=8, UNMEASURED=` (empty).

**The whole derived chain was regenerated**, because `timeline.json` embeds the
manifest's digest and each frame's action text, and three further documents
embed the timeline's digest. The film itself did not change and could not have:
no frame, duration, clamp, transition flag or cue window differs. Measured
after regeneration:

| artifact | result |
| --- | --- |
| `playthrough/timeline.json` | only the manifest digest and the 8 action strings differ; 419 frames, 2 transitions, 204 reconciled, `231.000 + 2.000 = 233.000 s`, 215 date-confirmed |
| `build/transitions/*.png` | 24 files, all **byte-identical** to before |
| `build/concat.txt` | **byte-identical** (`5e7741e8c1…`) |
| `playthrough/cata-play.mp4` | **byte-identical** (`5e1344bac9…`), 8,051,910 B |
| `playthrough/transcript.srt` / `.md` | both **byte-identical** (`a67fcce909…`, `c924d91f1d…`) |
| `playthrough/cata-play-cc.mp4` | **byte-identical** (`da957b72ee…`), h264 1920×1080 + `mov_text` `eng`, 419 cues in and out |
| the three generation manifests | now name the current timeline `5fa42ff7b1…` |

A byte-identical film from a corrected record is the strongest available
statement that the correction was to the prose and to nothing else.

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
winner (`ocr_clock.py`, `_measure_phase`; on one host the computed and
the drawn phase differed by 14 pixels). A measured phase is immune to
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
