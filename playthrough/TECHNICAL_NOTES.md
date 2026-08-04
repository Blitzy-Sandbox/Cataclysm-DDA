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

**The platform is out of support, and the tooling says so out loud.** This is
Ubuntu 25.10, which reached end of life on 2026-07-09, and `env.sh` prints a
named warning to that effect on every run because ImageMagick, ffmpeg and the
Xorg/Xvfb stack all parse untrusted-shaped input in this pipeline. It is
recorded rather than suppressed; `PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1`
turns it into a hard failure for anyone who wants that.

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
excludes it; and `git status --porcelain playthrough/` is empty, with
`playthrough/tooling/__pycache__/` the only ignored entry in the tree. Across
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
