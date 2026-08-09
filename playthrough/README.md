# playthrough/ — the capture and cinematography subsystem

One survivor, one continuous session, one screenshot per keystroke, and a film
whose pacing is the in-game clock rather than a frame rate.

Everything in this directory is either **evidence** — the captures, the record,
the save the engine wrote, the films, the transcripts — or the **tooling** that
produced it. Nothing here changes the game. **The Cataclysm-DDA engine is the
*host* of this feature, not its subject:** the shipped binary is invoked, the
sidebar clock is read, and the rendered pixels are photographed, all through
interfaces the engine already had. No game behaviour, balance, content or
presentation is altered, and no file under `src/`, `tests/`, `data/` or `gfx/`
is touched by any of it.

## The three documents, and which one to read

| Page | Audience | Holds |
| --- | --- | --- |
| `README.md` (this page) | operator | the artifact inventory, the prerequisites, how to re-run each stage, the environment contract, the commit lifecycle, the contracts the gates check |
| `TECHNICAL_NOTES.md` | engineer | the measurements, the pitfalls, the divergences, and the chronological log of how the record was produced and reviewed |
| `dossier.md`, `transcript.md` | reader | the survivor's own voice, and nothing about machinery |

This page is a reference; `TECHNICAL_NOTES.md` is a log. Where a fact here has
an evidence trail longer than a sentence, this page states the fact and names
the section of that page which measured it, rather than reproducing the
working. There is no in-character voice anywhere on this page, and no
engineering narrative either — both live elsewhere on purpose.

**Provenance convention, applied without exception below.** A figure stated
plainly was measured in this checkout with the command shown. A figure marked
**(plan)** comes from the Agent Action Plan and was *not* reproduced here.
Where a plan figure and a measurement disagree, both appear and the
disagreement is named. This is the same convention `TECHNICAL_NOTES.md` uses,
so the two pages cannot quietly diverge about where a number came from.

---

## Why this page exists here, and not in the root `README.md`

A feature normally documents itself in the top-level readme. This one
deliberately does not, and the reason is recorded rather than left implicit.

This checkout is a **fork**, and the commit this feature branched from is
literally a merge from upstream:

```console
$ git log -1 --pretty='%h %s' f38c2fbae3
f38c2fbae3 Merge branch 'CleverRaven:master' into master
$ git merge-base --is-ancestor f38c2fbae3 HEAD && echo "branch base"
branch base
$ git rev-list --count f38c2fbae3..HEAD
30
```

`f38c2fbae3` is the branch base — the last upstream commit before any of this
work — and the acceptance gate names it as the point the change surface is
measured from. The root `README.md` is therefore an **upstream-synced** file:
editing it would create a permanent merge-conflict surface on every subsequent
sync, for a document whose audience is players of the game rather than
operators of this pipeline. Putting the feature's documentation here achieves
the documentation goal with no upstream friction, and the root `README.md`
stays byte-identical to upstream's.

---

## 1. What the subsystem does

A pipeline that plays the already-shipped **SDL tiles** build in character
under a headless X server, captures **exactly one screenshot per keystroke**,
derives each frame's on-screen duration from the **in-game clock delta** that
keystroke produced, renders those frames into an MP4 whose pacing is therefore
**diegetic** — video time tracks game time — writes a timestamped first-person
transcript, embeds it as a **selectable** closed-caption track, and commits
every artifact into git.

Nothing is sped up, slowed down, sampled or dropped. The only two departures
from a literal one-second-of-video-per-second-of-game-time mapping are the
floor and the ceiling in section 6, and the only imagery in the film that was
not photographed off the screen is the one-second transition unit the ceiling
inserts.

The shipped session: **326 captures**, **219.500 s** of film, **one**
transition. Read `transcript.md` for the account of it and
`TECHNICAL_NOTES.md` for how it was produced and reviewed.

---

## 2. What is in this directory

| Path | What it is | Written by |
| --- | --- | --- |
| `tooling/` | the authored pipeline — 9 shell entry points, 10 Python modules, 20 `test_*.py` suites, `requirements.txt`, `requirements.lock`, `tileset_provenance.json`, `environment/Dockerfile`. Kept out of the game's source tree on purpose | authored |
| `frames/frame_NNNNN.png` | exactly one 1920×1080 capture per keystroke — 326 of them, contiguous from `frame_00001`, none decimated, sampled or deduplicated | `capture.sh` |
| `manifest.jsonl` | one row per capture, six fields: `frame`, `file`, `real_ts`, `ingame_clock`, `action`, `commentary` | `session.py` |
| `amendments.jsonl` | corrections to the record, **appended** rather than applied in place, so the original reading survives beside the correction | operator, via `session.py annotate --amend` and review |
| `timeline.json` | the computed durations and transition flags — **the single source of truth** for both the film and the captions | `timeline.py` |
| `build/` | intermediates and telemetry: `concat.txt`, `transitions/`, `observations.jsonl`, `frame_dates.jsonl`, `frame_digests.jsonl`, `transitions.json`, `movie.json`, `transcript.json` | the stage that owns each |
| `cata-play.mp4` | the film: `h264`, 1920×1080, no audio stream | `render_movie.py` |
| `cata-play-cc.mp4` | the same film with a selectable `mov_text` caption track tagged `language=eng` | `embed_captions.sh` |
| `transcript.srt` | the caption cue file — 326 cues | `make_srt.py` |
| `transcript.md` | the timestamped, in-character record — 326 entries, cumulative video time | `make_srt.py` |
| `dossier.md` | the survivor's first-person backstory, written and committed **before** the first gameplay frame | authored |
| `userdir/` | the engine's own tree: `save/<World>/`, `config/`, `achievements/`, `templates/`, `cache/`. Committed, never hand-edited | the game |
| `TECHNICAL_NOTES.md` | the engineering log — measurements, pitfalls, divergences | authored |
| `README.md` | this page | authored |

Two properties of that set are easy to lose and are therefore stated rather
than left to be inferred.

**Frame-directory purity is an integrity constraint, not a preference.**
`frames/` holds exactly one PNG per keystroke and nothing else. Derived
imagery — the materialised transition pictures — goes to `build/transitions/`,
never here, because the acceptance gate asserts

```console
$ ls -1 playthrough/frames/frame_*.png | wc -l
326
$ wc -l < playthrough/manifest.jsonl
326
```

and mixing derived images into `frames/` would destroy that identity while
every other count still tallied.

**Everything is committed**, including every frame and both films:

```console
$ git ls-files playthrough | wc -l
509
$ git ls-files playthrough/frames | wc -l
326
$ git ls-files playthrough/userdir/save | wc -l
99
```

When repository size and completeness conflict, completeness wins, and the
mitigation is engineering rather than omission.

---

## 3. Prerequisites

### The tiles binary is never tracked, so a fresh checkout has none

This is the first thing that stops a new operator, and it is not a defect.
Three separate statements are all true of `./cataclysm-tiles`, and confusing
them wastes an afternoon:

```console
$ git check-ignore -v cataclysm-tiles
.gitignore:75:*cataclysm-tiles   cataclysm-tiles
$ git ls-files --error-unmatch cataclysm-tiles
error: pathspec 'cataclysm-tiles' did not match any file(s) known to git
Did you forget to 'git add'?
```

It is **git-ignored** [.gitignore:75] and **tracked in no commit**, so `git
clone` alone never produces one and the pipeline must build it —
`launch_game.sh build` exists for exactly this, and `launch_game.sh all`
calls it. A **warmed** worktree that has already built one does have it, which
is why "the binary is present" and "a clone has no binary" are both true
statements about different trees rather than a contradiction.

Verify whichever binary you end up with by asking it what it is:

```console
$ ./cataclysm-tiles --version
Cataclysm Dark Days Ahead: 421659a9cf

+tiles, +sound

data dir: data/
user dir: ./
```

That **`+tiles`** string is the direct, self-reported proof this is the SDL
tiles build and not the curses one. The rule is about the *binary*, not about
which artwork pack is selected.

### The build command, and the switches that must and must not appear

```bash
CXX=g++-14 CCACHE=1 make -j3 RELEASE=1 TILES=1 SOUND=1 SDL3=0 \
    ASTYLE=0 LINTJSON=0
```

Every switch is one the Makefile documents for itself: `RELEASE=1`
[Makefile:34], `TILES=1` [Makefile:36], `SOUND=1` [Makefile:38], `ASTYLE=0`
[Makefile:88], `LINTJSON=0` [Makefile:90], `CCACHE=1` [Makefile:32]. The
output name follows from `TARGET_NAME = cataclysm` [Makefile:153],
`TILES_TARGET_NAME = $(TARGET_NAME)-tiles` [Makefile:154] and
`TILESTARGET = $(BUILD_PREFIX)$(TILES_TARGET_NAME)` [Makefile:160], which is
why it lands at `./cataclysm-tiles` in the repository root.

Four constraints on that command line:

* **`SDL3=0` on every single invocation.** `SDL3` defaults to `1` whenever
  `TILES=1` [Makefile:791-793], which adds `-DUSE_SDL3` [Makefile:800] and
  then runs a hard version gate — `--atleast-version=3.4.0 sdl3`, with
  `$(error SDL3 >= 3.4.0 required for the GPU shader path…)`
  [Makefile:812-814]. The AAP's reason for this is that the distribution
  packages no SDL3 at all **(plan)**; measured here, it does package one and
  the package is simply too old, so the requirement stands for a different
  reason:

  ```console
  $ apt-cache policy libsdl3-dev | head -3
  libsdl3-dev:
    Installed: (none)
    Candidate: 3.2.20+ds-2
  $ pkg-config --exists sdl3; echo "exit=$?"
  exit=1
  ```

  The SDL2 fallback this selects is the one the project's own build
  documentation anticipates [doc/c++/COMPILING.md:232].
* **`-j3`, not `-j$(nproc)`** — and never `-j$(nproc --all)`. The AAP caps
  parallelism for memory: 128 CPUs against ~3.85 GiB RAM with zero swap
  **(plan)**. Measured here the ceiling is CPU rather than memory —
  `nproc` reports **4** while `nproc --all` reports **128**, because the
  cgroup grants four of the machine's cores, and `/proc/meminfo` shows
  `SwapTotal: 6291452 kB`. Either way `-j3` is safe and `-j128` is not.
* **Never pass `TESTS=0`.**
* **Never pass `USE_XDG_DIR=1` or `USE_HOME_DIR=1`.** Both are opt-in
  [Makefile:1211-1222], and either one moves the configuration directory out
  of the userdir — `config_dir_value = user_dir_value + "config/"` is the
  `#else` arm of a `#if defined(USE_XDG_DIR)` [src/path_info.cpp:152-166]. A
  binary built with either switch silently breaks `seed_options.py`, which
  patches `playthrough/userdir/config/options.json`, and breaks the committed
  keybindings evidence section 11 relies on. On ARM64, also never pass
  `NATIVE=linux64`.

### System packages

`ffmpeg`, `imagemagick`, `tesseract-ocr`, `xdotool`, `xvfb`, `x11-utils`,
`openbox`, `scrot`. Two version facts matter operationally, and one of them
contradicts the plan:

* **ImageMagick.** The AAP records the 6.x legacy branch, on which the v7
  unified `magick` entry point does not exist, and instructs the tooling to
  call `import`, `convert` and `identify` directly **(plan)**. Measured here
  it is **ImageMagick 7.1.2-3 Q16**, `/usr/bin/magick` **does** exist, and so
  do `convert`, `import` and `identify` — IM7 is installed *and* keeps the
  legacy names, so the pipeline's calls work unchanged. `magick` and
  `convert` were checked against the same frame and agree to the last digit:
  both report `0.10383 0.172987`. The instruction to call the legacy names is
  still the right one, because it is the only spelling that works on both
  branches.
* **The rest, measured:** `ffmpeg`/`ffprobe` 7.1.1, `tesseract` 5.5.0 with
  leptonica-1.84.1, `xdotool` 3.20160805.1, `openbox` 3.6.1, `scrot` 1.12.1,
  `x11-utils` 7.7+7, `xvfb` 21.1.18. The AAP's 6.1.1 / 5.3.4 **(plan)** were
  taken on another host; any figure in the plan that was calibrated against
  those versions should be re-measured rather than trusted.

### Python

Declared in **`tooling/requirements.txt`** — deliberately outside the game's
source tree, and following the shape of the repository's only other
requirements file, `tools/json_tools/requirements.txt`, whose single line is a
spec, two spaces, and an inline comment naming its consumer
[tools/json_tools/requirements.txt:1]. Six exact `==` pins:

```console
$ grep -vE '^\s*(#|$)' playthrough/tooling/requirements.txt
moviepy==2.2.1  # fade/card/fade transition unit: make_transitions.py
pillow==11.3.0  # PNG inspection, title card, MoviePy 2 image backend
pytesseract==0.3.13  # sidebar clock OCR wrapper: ocr_clock.py
numpy==2.5.1  # frame luminance statistics and MoviePy arrays
imageio==2.37.4  # frame and video IO used by MoviePy
imageio-ffmpeg==0.6.0  # encoder bridge for MoviePy and imageio
```

The pins are exact rather than floating lower bounds because this pipeline
produces a byte-level media artifact **and its own acceptance evidence**: a
floating bound would let a future release change the film while every gate
still reported green. `imageio-ffmpeg` is the sixth entry and the one the
requirement did not name; the file says so inline rather than letting it look
like an accident.

`tooling/requirements.lock` is the stronger path — the same closure with
`--require-hashes` and `--only-binary :all:` — and it is what the production
environment installs.

The interpreter is **CPython 3.12**. Two host facts to know before creating an
environment by hand:

```console
$ python3 -V
Python 3.13.7
$ ls /usr/lib/python3.13/EXTERNALLY-MANAGED
/usr/lib/python3.13/EXTERNALLY-MANAGED
$ python3 -m venv /tmp/probe; echo "exit=$?"
Error: Command '['/tmp/probe/bin/python3', '-m', 'ensurepip', '--upgrade',
'--default-pip']' returned non-zero exit status 1.
exit=1
```

The system interpreter is 3.13 and carries the PEP 668 marker, so nothing may
be installed into it; and `python3 -m venv` fails at the `ensurepip` step on
this host. The working sequence is `python3 -m venv --without-pip` followed by
bootstrapping pip from `get-pip.py` — and note that a venv built from the
system interpreter would be 3.13, not the 3.12 the pins contract for. The
pipeline resolves its own interpreter instead, and reports which one:

```console
$ bash playthrough/tooling/env.sh | grep PLAYTHROUGH_PYTHON
  PLAYTHROUGH_PYTHON         /opt/playthrough-venv/bin/python
  PLAYTHROUGH_PYTHON_VERSION 3.12.13
  PLAYTHROUGH_PYTHON_ABI     3.12
```

---

## 4. The environment contract

Defined **once**, in `tooling/env.sh`, and sourced by every other script so
that no two stages can drift over the display, the video driver or a path.
Source it — executing it instead prints the resolved contract and exports
nothing, which is how the block below was produced:

```console
$ bash playthrough/tooling/env.sh
playthrough environment contract
  DISPLAY                    :99
  SDL_VIDEODRIVER            x11
  SDL_AUDIODRIVER            dummy
  LIBGL_ALWAYS_SOFTWARE      1
  XDG_RUNTIME_DIR            /tmp/xdg
  XAUTHORITY                 <runtime>/Xauthority
  PYTHONDONTWRITEBYTECODE    1
  IMAGEIO_FFMPEG_EXE         /usr/bin/ffmpeg
  [... eight lines elided ...]
  PLAYTHROUGH_SCREEN         1920x1080x24
  PLAYTHROUGH_WINDOW_CLASS   cataclysm-tiles
  PLAYTHROUGH_TILESET        MshockXottoplus
  PLAYTHROUGH_SIDEBAR_LAYOUT legacy_labels_sidebar
  PLAYTHROUGH_SIDEBAR_CELLS  44
  [... the artifact paths, then ...]
  PLAYTHROUGH_USERDIR_ARG    ./playthrough/userdir/
```

Run it with no arguments to see the whole thing; the elisions above are only
for length.

The display surface is `Xvfb :99 -screen 0 1920x1080x24` with **openbox** as a
minimal window manager, so focus and keyboard delivery behave. `XDG_RUNTIME_DIR`
is mode 0700. `launch_game.sh headless` brings both up and verifies them; it
starts Xvfb with `-auth` and a fresh 128-bit `MIT-MAGIC-COOKIE-1` and then
asserts that a client without the cookie is refused
[playthrough/tooling/env.sh:49-54], so the screen being captured is not
readable — and keystrokes are not injectable — by any other local account.

### Seven things about that contract which are load-bearing

* **`SDL_VIDEODRIVER=dummy` is banned everywhere, including as any script's
  default.** It renders zero pixels, and the failure is silent in the worst
  possible way: the game runs, the captures succeed, the encode succeeds, every
  count tallies, and the only symptom is that nothing is visible. `x11` under
  Xvfb is the single correct value, and the luminance gate in section 11 is the
  second line of defence.
* **`PYTHONDONTWRITEBYTECODE=1` is mandatory, not hygiene.** `__pycache__`
  [.gitignore:161] and `*.pyc` [.gitignore:162] are both unanchored, so they
  would normally cover this tree — but the terminal `!/playthrough/**`
  [.gitignore:275] is the *last* matching pattern and therefore
  **re-includes** `playthrough/tooling/__pycache__/*.pyc`. Because the negation
  must stay last (section 8), bytecode is prevented at source rather than
  re-excluded. Every documented Python command here also carries `-B`.
* **Launch fully detached.** A foreground long-running child can have its whole
  process group signalled when an outer call times out, which kills the game
  mid-session:

  ```bash
  setsid nohup ./cataclysm-tiles --userdir ./playthrough/userdir/ \
      >/tmp/cata.log 2>&1 < /dev/null & disown
  ```

  `launch_game.sh launch` does this. `launch_game.sh guard` is the variant that
  stays in the foreground and owns the instance for its whole lifetime, for
  callers that need something to hold the process.
* **Window targeting is class-based.** Resolve the window with
  `xdotool search --class cataclysm-tiles`, then `windowfocus`, then
  `key --window <id>` — the class route is the only one the tooling uses, and
  the three facts behind that choice are recorded beside the code that depends
  on them [playthrough/tooling/launch_game.sh:2513]. As observed during the
  session: `xdotool search --name 'Cataclysm'` returns **empty** for this
  window even though `xwininfo -root -children` lists it with its title, and
  the id must not be scraped out of `xwininfo` with a loose hexadecimal
  pattern, because the geometry substring on the same line mis-matches such a
  pattern and hands back a plausible-looking wrong number. `session.py window`
  is the supported way to ask.
* **Capture targets the X root window, not the game window.** The game window
  is 1920×1072 inside a 1920×1080 root, so photographing the root yields a
  true-resolution frame and needs no rescale that would soften the text the
  clock reader depends on. The eight leftover rows are a letterbox; measured
  across the whole 326-frame population they are all at the **bottom**, rows
  1072–1079, with the grid at `+0+0` — the AAP's "four pixels top and bottom"
  **(plan)** does not reproduce. Nothing is cropped either way; see
  *Two figures where the plan and the measurement disagree* in
  `TECHNICAL_NOTES.md` for the running-maximum method that isolates the band.
* **ImageMagick is called by its legacy names** — `import`, `convert`,
  `identify` — because that spelling works on both the 6.x and 7.x branches.
  See section 3 for what is actually installed here.
* **A fresh userdir does not open on the main menu.** As recorded during the
  session, the first screen is a `Select your language` prompt, and the window
  is created at 640×384 on launch one — the compiled-in `TERMINAL_X` 80 by
  `TERMINAL_Y` 24 [src/options.cpp:2408-2416] at the 8×16 cell — becoming
  1920×1072 on launch two once the game has written screen-derived values into
  `options.json`. `seed_options.py` writes `TERMINAL_X=240` and
  `TERMINAL_Y=67` in place so the geometry is right from the start rather than
  treating launch one as throwaway calibration; the language prompt still has
  to be dismissed before anything else can be navigated.

### The declared production environment

`tooling/environment/Dockerfile` declares a complete, capture-capable image on
a Linux release that is **in support**, and `tooling/supported_env.sh` drives
it:

```console
$ playthrough/tooling/supported_env.sh build        # build the image
$ playthrough/tooling/supported_env.sh inventory    # what it actually contains
$ playthrough/tooling/supported_env.sh preflight    # prove the path end to end
$ playthrough/tooling/supported_env.sh run playthrough/tooling/run_pipeline.sh --no-commit
$ playthrough/tooling/supported_env.sh shell        # a shell inside it
```

It exists because a session must not be **recorded** on an end-of-life
release: ImageMagick, ffmpeg and the Xorg stack all parse untrusted-shaped
input, and an out-of-support archive publishes no fixes for them. `env.sh`
dates the platform and says so plainly — measured on this host, with no waiver
set:

```console
$ bash playthrough/tooling/env.sh | grep -E 'PLATFORM|TRUST'
  PLAYTHROUGH_PLATFORM       Ubuntu 25.10
  PLAYTHROUGH_PLATFORM_SOURCE /etc/os-release
  PLAYTHROUGH_PLATFORM_SUPPORTED no
  PLAYTHROUGH_PLATFORM_EOL   2026-07-09
  PLAYTHROUGH_PLATFORM_WAIVER <none>
  PLAYTHROUGH_TRUST_STATE    trusted
  PLAYTHROUGH_TRUST_BYPASSES <none>
  PLAYTHROUGH_TRUST_UNVERIFIED <none>
```

`PLAYTHROUGH_ALLOW_EOL_PLATFORM` is the documented escape hatch, and it is a
**registered trust bypass rather than a "make it work" flag**: setting it moves
`PLAYTHROUGH_TRUST_STATE` from `trusted` to `diagnostic` and names itself in
`PLAYTHROUGH_TRUST_BYPASSES`, so the relaxation is recorded in the environment
every downstream stage reads. The container is the supported path rather than a
way around that, and `supported_env.sh` clears every registered bypass on the
way in and will not forward one. Regenerating the artifacts inside the image
reproduces the committed films, timeline, transcript and cue file byte for byte.

The acceptance gate is the one stage that is safe to run anywhere, because it
reads committed evidence and writes nothing. It treats a **capture-time**
bypass as a failure — evidence produced under a relaxed check is not evidence —
and this one as a warning, in its own words: it "says something about the host
doing the reading rather than about the session that was recorded".

---

## 5. Re-running the pipeline

### Every command runs from the repository root, and that is a source-level requirement

Not a convention — three engine behaviours make the repository root the only
working directory that works:

* `--userdir` is normalised but **not absolutised**:
  `user_dir_value = as_norm_dir( dir );` [src/path_info.cpp:105], reached from
  `PATH_INFO::init_user_dir( params[0] )` [src/main.cpp:416-426]. So
  `--userdir ./playthrough/userdir/` resolves against the process working
  directory.
* With an empty `--basepath`, `datadir_value = "data/"`
  [src/path_info.cpp:128-132], and `gfxdir_value` and `langdir_value` are
  likewise prefix-relative [src/path_info.cpp:134-137].
* Therefore the repository root is simultaneously the only directory under
  which **this checkout's** `data/`, `gfx/` and `lang/mo/` resolve *and* the
  only one under which the userdir lands **inside the working tree** where git
  can track it. Any other choice breaks both halves at once — and it breaks
  them quietly, by loading someone else's data or writing the save somewhere
  that is never committed.

`env.sh` refuses to define a contract if it is sourced from anywhere else.

### How to invoke a Python module

The shell entry points are executable and run directly. **The Python modules
are deliberately not marked executable, and must be run through the
interpreter `env.sh` resolved** — their `#!/usr/bin/env python3` shebang would
otherwise select the system 3.13, which is PEP 668 marked and carries none of
the pinned packages. Source the contract once, then use `$PLAYTHROUGH_PYTHON`
with `-B`, which is exactly what the sequencer does
[playthrough/tooling/run_pipeline.sh:1046]:

```console
$ . playthrough/tooling/env.sh
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/sidebar_geometry.py
352x1072+1568+4
```

Every `$ …/tooling/*.py` command below is shorthand for that form.

### Capturing a session

```console
$ playthrough/tooling/launch_game.sh all      # build, headless, tileset, probe, launch
$ playthrough/tooling/launch_game.sh help     # the subcommands, individually runnable
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py probe   # create vs resume
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py audit   # no debug binding
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py step …  # ONE key, ONE frame
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py status  # counter + record
```

`session.py` is the **sole owner of the frame counter**, which is what makes
the one-frame-per-keystroke invariant structural rather than merely intended:
one function focuses the window, sends exactly one key, lets the frame settle,
captures exactly one PNG through `capture.sh`, reads the clock through
`ocr_clock.py`, and appends exactly one `manifest.jsonl` row through
`manifest.py`. Because the counter is incremented in one place and used for
both the filename and the row, no ordering of operations can produce an orphan
frame or an orphan row. `capture.sh` takes its index from `session.py` through
`FRAME_INDEX` and never derives one itself.

The loop is **observe → decide in character → act → capture → log**. Keys are
never blind-spammed: every iteration reads the captured frame before choosing
the next keystroke.

### The resume-versus-create branch

The rule is *if a save already exists, continue that save file*, so a
pre-flight probe of `playthrough/userdir/save/*/` runs before any character
creation:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py probe
```

`launch_game.sh probe` reports the same decision from the shell side. This
checkout now carries a save, so the probe resolves to **resume**; on a clean
tree it resolves to **create**, and the creator is entered through the
main-menu door labelled `Custom Character` — the template picker
(`Preset Character`), `Random Character`, `Play Now!  (Default Scenario)` and
`Play Now!` are all forbidden. `session.py --help` prints that permitted-door
list and the scenario, so the constraint lives in the tool rather than only in
prose.

### The post-session stages

`tooling/run_pipeline.sh` sequences them. It holds none of their logic — each
stage is independently runnable — and it takes no positional arguments.

```console
$ playthrough/tooling/run_pipeline.sh --help          # the full contract
$ playthrough/tooling/run_pipeline.sh --no-commit     # rebuild and gate, commit nothing
$ playthrough/tooling/run_pipeline.sh --from render   # retry a late stage
$ playthrough/tooling/run_pipeline.sh --only srt      # one stage
```

| # | Stage | Runs | Produces |
| --- | --- | --- | --- |
| 1 | `timeline` | `timeline.py` | `timeline.json` |
| 2 | `transitions` | `make_transitions.py` | `build/transitions/*.png` |
| 3 | `render` | `render_movie.py` | `cata-play.mp4` |
| 4 | `srt` | `make_srt.py` | `transcript.srt` + `transcript.md` |
| 5 | `captions` | `embed_captions.sh` | `cata-play-cc.mp4` |
| 6 | `verify` | `verify_artifacts.sh --phase pre-commit` | a verdict |
| 7 | `commit` | `commit_artifacts.sh final` | a checkpoint |
| 8 | `attest` | `verify_artifacts.sh --phase post-commit` | a verdict |

**The gate runs twice, and that is deliberate.** Most of its checks are
properties of the *artifacts* and can be answered the moment a render finishes.
Twelve are properties of the *history* — is the save tracked, is every artifact
class committed, is the tree clean — and a commit is what makes those true. So
the functional half guards the commit and the history half reports what the
commit published. `--no-commit` drops the checkpoint **and** the attestation,
since with nothing committed the second has nothing to read.

Two orderings are non-negotiable, and the sequencer checks them against the
plan it resolved rather than against the flags you typed: **`commit` requires
`verify` earlier in the same invocation**, and **`attest` requires `commit`**.
Ask for either on its own and it refuses, naming the invocation that would have
worked.

### The gate on its own

```console
$ playthrough/tooling/verify_artifacts.sh                       # all 111 checks
$ playthrough/tooling/verify_artifacts.sh --phase pre-commit     # the 99 functional ones
$ playthrough/tooling/verify_artifacts.sh --phase post-commit    # all 111, after a commit
```

It writes nothing, and every verdict prints what it **observed** beside what it
expected, so a passing report reads as evidence rather than as a tally. The
counts are declared in the script — `EXPECTED_CHECKS_ALL=111`
[playthrough/tooling/verify_artifacts.sh:572] and
`EXPECTED_CHECKS_PRE_COMMIT=99` [:573] — and asserted against the verdicts
actually emitted, so neither phase can return a short report unnoticed.

### The commit lifecycle

Three ordered checkpoints, each refusing to run out of turn:

```console
$ playthrough/tooling/commit_artifacts.sh dossier    # before the first frame
$ playthrough/tooling/commit_artifacts.sh creation   # after character creation
  # ... play the session ...
$ playthrough/tooling/commit_artifacts.sh final      # after the session ends
$ playthrough/tooling/commit_artifacts.sh status     # read-only, takes no lock
```

The dossier is committed **alone and first** because "written before the first
gameplay frame" is a statement about ancestry between two commits, and one
commit cannot precede itself — so `creation` refuses until the dossier is
tracked. `final` anchors to the `creation` checkpoint of **the same survivor**
and refuses across a survivor change, which a row count cannot detect, since a
record re-recorded from scratch has "grown" too.

Each checkpoint stages `playthrough/` by artifact class in bounded batches —
never a blanket `add`, never `-A`, never `-f`, never a shell glob — and carries
a `Playthrough-Checkpoint: <name>` trailer, which is the lifecycle's entire
persistent state. There is no side file to fall out of step with the history.

`.gitignore` and `.gitattributes` are **checked** here and committed elsewhere:
the terminal negation is verified both in the working tree and as HEAD carries
it, because a negation that was never committed loses the save data on the next
clone.

The committer records the identity git already resolves in **this repository's**
configuration (`git config --local`, never `--global`, never `--system`, never
overwriting a pair the repository already carries). That is least privilege
rather than tidiness: the container mounts the checkout, sets its own `HOME`
and forwards no `GIT_*`, so an identity living only in a home directory does
not exist in there. It never invents one — a missing identity is a refusal —
and it never rewrites history and never pushes.

---

## 6. The duration model

Each frame is on screen for as long as its keystroke took **in game**. The
duration is the difference between consecutive sidebar clock readings.
**No turn count is modelled and no conversion constant exists anywhere in the
pipeline.** The engine's own accounting is in moves, and community
documentation puts roughly 100 moves at about a second of game time **(plan)** —
a figure this pipeline never needs, because differencing the clock sidesteps the
question rather than inventing a factor.

Two bounds, and one insertion:

* **Floor 0.25 s.** Menu navigation and character creation consume no game
  time. Those frames fall to the floor; they are **not** merged, dropped or
  "optimised away".
* **Ceiling 10 s.** A raw delta above the ceiling is held at it.
* **A 1.0 s cinematic unit** is inserted wherever the raw delta exceeded the
  ceiling: a fade-out, a "…time passes…" card set in the game's own Terminus
  face [data/font/Terminus.ttf], and a fade-in. Sleeping through the night is
  the archetypal case.

```text
dur[i]   = min(max(raw[i], 0.25), 10.0)
trans[i] = raw[i] > 10.0                 # strictly greater
```

The transition is composed as 0.4 s fade-out / 0.2 s card / 0.4 s fade-in and
materialised to PNG at 12 fps, which quantises the ramps to 5/12 and 4/12 of a
second and the card to 3/12 — so the card is charged **0.25 s**, not the 0.20 s
the composition names **(plan)**, and the encoder shows it for 0.24 s on its
25 fps grid. The unit spans exactly 1.000 s either way, which is what
`timeline.py` charges and what the cue cursor advances. Quote whichever figure
the question is about and say which; the arithmetic is in
*Two figures where the plan and the measurement disagree* in
`TECHNICAL_NOTES.md`.

Cue windows walk a video cursor: frame `i` occupies `[t, t + dur[i])`, then
`t += dur[i]`, and if `trans[i]` then `t += 1.0` **before** the next cue
begins. Charging the inserted second to *video* time is what stops the caption
track drifting — cues that ignored it would be correct at the start and
increasingly wrong by the end.

**The invariant:** `sum(durations) + sum(transitions) == total == final cue
end`. Measured on the shipped record:

```console
$ python3 -c "import json; d=json.load(open('playthrough/timeline.json')); \
print(d['total_duration'], d['total_transition'], d['total'], d['final_cue_end'])"
218.5 1.0 219.5 219.5
$ grep -E -- '-->' playthrough/transcript.srt | tail -1
00:03:39,250 --> 00:03:39,500
```

218.5 + 1.0 = 219.5, and the last cue closes at 219.500 s. The ceiling engaged
exactly once, at frame 139, where a raw delta of 13.0 s was held at 10.0 s —
which is why there is one transition group of twelve pictures.

`timeline.json` is the **single source of truth**: the renderer and the caption
generator both read it, in one pass, so the cue windows and the frame windows
are the same numbers by construction rather than by coincidence.

### Reading the clock at all requires a watch, in the fiction

`display::time_string()` returns an exact time **only when `u.has_watch()`**;
otherwise it returns a coarse phrase from `display::time_approx()` — "Around
dawn", "Dead of night" and so on [src/display.cpp:159-186] — or `"???"` when
the sky is not visible [src/display.cpp:207-218]. Second-resolution deltas, the
entire basis of the duration model, are impossible without one.

Acquiring a time-telling device is therefore a **characterful and entirely
legitimate** creation-and-scavenging decision, and never a code change. When
the clock genuinely cannot be read — no watch, underground, or an OCR failure —
the value is recorded as unreadable and reconciled against the previous frame,
never invented. On the shipped record that is **209 exact readings and 117
unreadable**, and the 117 say so in the telemetry rather than carrying a guess.

### Why `24_HOUR` must be `24h`

`to_string_time_of_day()` has three branches [src/calendar.cpp:638-663]:

| `24_HOUR` | Format | Suitable |
| --- | --- | --- |
| `military` | `"%02d%02d.%02d"` [:646] | no — no colons for the regex to find |
| `24h` | `"%02d:%02d:%02d"` [:649] | **yes — fixed width** |
| `12h` (the default) | `"%d:%02d:%02d%sAM"` / `…%sPM"` [:658, :660] | no — variable-width hour, and padding removed conditionally |

Only the `24h` branch is fixed width, which is what makes the OCR regex
`[0-9]{2}:[0-9]{2}:[0-9]{2}` deterministic. The compiled default is `"12h"`
[src/options.cpp:1868-1877], so `seed_options.py` changes it — along with
`SOUND_ENABLED` to `false` (default `true` [src/options.cpp:1774-1777]), to
match `SDL_AUDIODRIVER=dummy`, and the terminal dimensions. The patch is
applied **in place, key by key**, never as a wholesale file replacement,
because the engine writes many other keys into that file that must survive.

---

## 7. The OCR crop is computed, never hard-coded

The crop is

```text
(sidebar_width_cells × FONT_WIDTH) x (TERMINAL_Y × FONT_HEIGHT) + x_offset + y_offset
```

right-aligned because `SIDEBAR_POSITION` defaults to `"right"`
[src/options.cpp:2132-2136], with the font and terminal dimensions read from
the options file. `sidebar_geometry.py` resolves it at run time and says so:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/sidebar_geometry.py
sidebar_geometry: WARNING: .../playthrough/userdir/config/panel_options.json
does not exist yet, so the sidebar layout is the engine's own default
'legacy_labels_sidebar' [src/panels.cpp:412-418]; it is written once the game
saves its panel options
352x1072+1568+4
```

**`352x1072+1568+4`** — and `build/observations.jsonl` records exactly that,
with `clock_rect_from = computed`, for all 326 captures.

**This is where a hard-coded rectangle would have been wrong, and the
disagreement is worth understanding rather than papering over.** The AAP
derives `288x1072+1632+4` from `custom_sidebar`'s width of 36
[data/json/ui/sidebar.json] **(plan)** — arithmetic which reproduces exactly,
`36 × 8 = 288` and `1920 − 288 = 1632`. But `custom_sidebar` is not the
engine's default. `panel_manager::panel_manager()` sets
`current_layout_id = "legacy_labels_sidebar"` on every non-Android build
[src/panels.cpp:413-419], that layout is **44** cells wide
[data/json/ui/sidebar-legacy-labels.json], and `panel_options.json` does not
exist in a fresh userdir, so the constructor default is what is in force:
`44 × 8 = 352` and `1920 − 352 = 1568`. The captures agree with the module and
not with the prose; `TECHNICAL_NOTES.md` has the pixel-level confirmation in
*Where the grid really sits, and which sidebar it really is*.

The measured spread is the general argument for computing it. **Nine**
`sidebar*.json` presets ship in `data/json/ui/` — the default plus eight
alternates — and their declared widths run from **32 to 66 cells**:

```console
$ ls -1 data/json/ui/sidebar*.json | wc -l
9
$ ls -d data/json/ui/*/
data/json/ui/spacebar/  data/json/ui/structured/  data/json/ui/zenfs/
```

Three further themed bundles carry sidebars of their own, `spacebar/` among
them. (The AAP's "ten alternative presets" is an estimate **(plan)**; nine
files is the measurement, and the three bundle directories are one more than
the two the specification names.) A hard-coded rectangle would silently crop
the wrong column the moment the layout changed — and the row is located by
**regex within that column, never at a fixed `y`**, for the same reason. The
clock text itself is rendered by the `time_desc_label` widget bound to
`time_text` [data/json/ui/time.json:3, :7].

The read pipeline has the shape the AAP prescribes:

```bash
convert "$FRAME" -crop "$RECT" +repage -colorspace Gray -resize 200% \
    -normalize png:- | tesseract stdin stdout | grep -Eo '[0-9]{2}:[0-9]{2}:[0-9]{2}'
```

The `-resize 200% -normalize` step is what makes 8×16 terminal glyphs legible
to tesseract at all. **The production reader is `ocr_clock.py`, not that
one-liner, and the difference is measurable rather than stylistic** — run
against a real capture on this host, the one-liner returns nothing while the
module returns the reading the record holds:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/ocr_clock.py \
      playthrough/frames/frame_00163.png
08:00:27
```

The module measures which vertical phase the engine's cell grid is really drawn
on instead of trusting the computed offset, which is why it is immune to a
class of drift the one-liner is not. Use the module. It is also allowed to
fail: it returns a clock string or nothing, and never a guess.

---

## 8. Repository integration — the only two pre-existing files that change

```console
$ git diff --name-status f38c2fbae3..HEAD -- . ':(exclude)playthrough'
M       .gitattributes
M       .gitignore
$ git diff --shortstat f38c2fbae3..HEAD -- .gitignore .gitattributes
 2 files changed, 26 insertions(+)
```

Two files, both additive appends, 26 inserted lines, zero deletions.

### `.gitignore` — a terminal negation block

The block ends at `!/playthrough/**` [.gitignore:275], which is the **last
line of the file**, and that position is the whole contract: **git applies the
last matching pattern**, so a negation placed earlier would simply be
re-overridden by the patterns below it.

Three patterns would otherwise swallow the engine's own output, and each was
confirmed live. Note that `git check-ignore` consults the *index* by default,
so a path that is already tracked reports "not ignored" no matter what the
rules say — `--no-index` is required to see the rules themselves:

```console
$ git check-ignore -v --no-index -- \
    'playthrough/userdir/save/Apshawa/#QW1icm9zZSBIYWxsb3Jhbg==.sav'
.gitignore:275:!/playthrough/**  playthrough/userdir/save/Apshawa/#QW1i….sav
```

Run against a control copy of `.gitignore` truncated just above the block, the
same paths are excluded, and by these patterns:

| Path | Pattern that excludes it without the negation |
| --- | --- |
| `userdir/save/<World>/#<b64>.sav` | `\#*` [.gitignore:131] |
| `userdir/save/<World>/#<b64>.log` | `\#*` [.gitignore:131] |
| `userdir/config/debug.log` | `debug.log` [.gitignore:79] |
| any other `*.log` under this tree | `*.log`, unanchored [.gitignore:31] |
| `tooling/__pycache__/*.pyc` | `__pycache__` [.gitignore:161] |

The `#` prefix is not decoration: CDDA names per-character save files
`#<base64-of-character-name>` plus an extension, so `\#*` matches every one of
them. **Without the negation, `git add` silently skips the save and exits 0** —
the run would look complete while nothing was tracked. That is the failure mode
the whole block exists to prevent.

### The git subtlety that must never be lost

**A negation cannot re-include a file whose *parent directory* was excluded by
a directory pattern.** Git does not descend into an excluded directory to
evaluate negations inside it. This block works only because every conflicting
pattern is a **file** pattern and nothing excludes `playthrough/` as a
directory.

**Anyone who later adds a directory-level ignore covering this tree — a bare
`playthrough/`, or anything equivalent — silently breaks the save-data
tracking.** It is the single most dangerous edit a future maintainer could make
here, and it fails without a message. The comment block above the negation says
so in the file itself [.gitignore:272-274]. The cost the ordering leaves — a
stray file under this tree is not ignored — is analysed in *The terminal
negation, and the one hygiene risk it leaves* in `TECHNICAL_NOTES.md`; the
three things standing between that and a committed build product are listed
there, and none of them is an ignore rule.

### `.gitattributes` — six entries

```console
$ git diff f38c2fbae3..HEAD -- .gitattributes | grep '^+[^+]'
+*.jsonl   text
+*.srt     text
+*.gsav    binary
+*.mp4     binary
+*.sav     binary
+*.zzip    binary
```

`*.jsonl` and `*.srt` join the text block [.gitattributes:7-19]; `*.gsav`,
`*.mp4`, `*.sav` and `*.zzip` join the binary block [.gitattributes:33-44].
`*.png` was already there [.gitattributes:39], which covers the frames, and
`*.md`, `*.txt` and `*.json` already covered the narrative and data artifacts.
The file's own stated rationale is to normalise explicitly rather than rely on
detection [.gitattributes:5-6], so extending it for new artifact types is the
treatment it prescribes for itself.

### What does not change

Nothing else. No file under `src/`, `tests/`, `data/` or `gfx/`; not
`Makefile`, `CMakeLists.txt`, `CMakePresets.json`, `.flake8`, `pyproject.toml`,
`.astylerc`, or anything under `.github/`; and **not the root `README.md`**.

In particular the one C++ edit the specification anticipated — the SDL2
`get_shared_variant_pass` guard in the pixel minimap — is **already applied at
both construction sites** [src/pixel_minimap.cpp:283-287,
src/pixel_minimap.cpp:475-479], so no engine change is required and none was
made. The acceptance gate checks the whole surface rather than trusting this
paragraph:

```text
PASS  the change surface is only the two ignore files and playthrough/
      observed: 511 changed path(s) since f38c2fbae3, all of them under
      playthrough/ or one of: .gitignore .gitattributes
```

---

## 9. The save layout

The engine defines and owns this format; the pipeline's only responsibility is
to make sure the files end up tracked. Nothing here is a schema this feature
designed, and there is no migration to run.

| Contract | Source |
| --- | --- |
| `--userdir <path>` → `PATH_INFO::init_user_dir( params[0] ); PATH_INFO::set_standard_filenames();` | [src/main.cpp:416-426] |
| `savedir = user_dir + "save/"` | [src/path_info.cpp:144] |
| `config_dir = user_dir + "config/"`, with `options.json` | [src/path_info.cpp:164-168] |
| user keybinding overrides at `<userdir>/config/keybindings.json` | [src/path_info.cpp:400-403] |
| the per-world options file is named `worldoptions.json` | [src/path_info.cpp:416-419] |
| `memorial/` and `achievements/` are siblings under the userdir | [src/path_info.cpp:147, :149] |

File names and extensions, authoritative from [src/path_info.h:11-17]:
`master.gsav` (:11), `artifacts.gsav` (:12), `dimension_data.gsav` (:13),
`.sav` (:14), `.log` (:15), `.weather` (:16), `.shortcuts` (:17). Compressed
overmap archives live under `overmaps/` with the suffix `.zzip`
[src/worldfactory.h:24-25].

### Three things a gate written from the plan's wording alone would get wrong

**1. The character save may be `#<b64>.sav.zzip` rather than `#<b64>.sav`, and
which one you get is a world option.** `save_player_data()` branches on
`world_generator->active_world->has_compression_enabled()`
[src/game_io.cpp:606]: with compression on it writes
`playerfile + SAVE_EXTENSION + zzip_suffix` [src/game_io.cpp:609-610], and with
it off the plain `playerfile + SAVE_EXTENSION` [src/game_io.cpp:621].
`WORLD_COMPRESSION2` defaults to **`true`** [src/options.cpp:1816-1819], so the
compressed form is the out-of-the-box default and **a gate must accept either**.

This session took the other branch deliberately, for a plainer and more
auditable committed save, and the committed options file is the evidence:

```console
$ python3 -c "import json; print([e for e in \
json.load(open('playthrough/userdir/config/options.json')) \
if e['name']=='WORLD_COMPRESSION2'])"
[{'name': 'WORLD_COMPRESSION2', ..., 'value': 'false'}]
$ ls playthrough/userdir/save/Apshawa/ | grep -E '^#.*\.sav'
#QW1icm9zZSBIYWxsb3Jhbg==.sav
```

The same option is why the overmaps are plain `o.0.0` / `o.1.0` files and the
map data is a `maps/` **directory**, rather than `maps.zzip` and
`overmaps/*.zzip`. Both layouts are legitimate; the artifacts in this tree are
the uncompressed one.

**2. `.shortcuts` is Android-only and will never exist on a Linux host.** It is
written inside `#if defined(__ANDROID__)` [src/game_io.cpp:630-635] and only
contributes to the return value inside the same guard [:638-640]. **No gate may
require it.** `.weather` is likewise declared [src/path_info.h:16] but is not
produced here.

**3. The world writes more than the specification enumerates.** Alongside the
files above, this save carries `external_options.json`, `mods.json`,
`uistate.json`, `world_timestamp.json`, `zones.json`, and per-character
sidecars — `.ano.json`, `.pt`, `.seen.0.0`, `.seen.1.0`, `.zones.json`, a
`.mm1/` map-memory directory and a `…_diary.json`. They are committed because
they are what the engine wrote; a gate that enumerated an exact expected set
would fail on the next engine that adds one.

---

## 10. Python, lint and CI

Two CI legs see new eligible inputs, and both are satisfied by construction
rather than by exemption. Because no C++, JSON or CMake file changes, the
astyle, JSON, cmake-format, clang-tidy, IWYU, matrix and MSVC workflows receive
nothing they can act on.

Worth knowing before editing this page: **a documentation-only change under this
tree triggers no workflow at all.** Not one workflow in `.github/workflows/`
carries a path filter that matches a `.md` file — checked across all of them —
so the style reviewer, the TOC generator and the spell checker never see it. The
spell check in particular runs from `text-changes-analyzer.yml`, whose filters
are the workflow itself, `tools/pot_diff.py`, `lang/extract_json_strings.py`,
`lang/string_extractor/**`, `src/*.h`, `src/*.cpp` and `**.json`
[.github/workflows/text-changes-analyzer.yml:4-16]. So prose here is reviewed by
people, not by a gate, and the dictionary at
`tools/spell_checker/dictionary.txt` — which carries `playthroughs` at line
5351, the plural only — is not consulted for it either way.

**flake8, at the DEFAULT 79 columns.** `.flake8` excludes only
`.git,__pycache__,lang/json,tools/clang-tidy-plugin/test/check_clang_tidy.py`
[.flake8:2] and ignores only `E265, W504` [.flake8:3-11], so the default
line-length limit is in force; `pyproject.toml` sets black's `line-length = 79`
to match [pyproject.toml:2]; `make python-check` runs bare `flake8`
[Makefile:1648-1649]; and the workflow fires on any `**.py` change
[.github/workflows/flake8.yml:7-13] and runs that target
[.github/workflows/flake8.yml:31]. **`.flake8` is deliberately NOT given a
`playthrough` exclude** — the new code satisfies the existing gate rather than
relaxing it, because modifying shared repository configuration to accommodate
new code is the wrong trade.

### How the lint gate must be measured — this part matters

**The acceptance criterion is `flake8 playthrough/` reporting zero findings,
NOT a global exit code of 0.** HEAD already carries pre-existing `F824`
findings under `tools/` when evaluated with flake8 7.3.0, which is newer than
the version CI installs from apt, so a global zero is not achievable and
asserting it would produce a false failure. Measured here:

```console
$ flake8 playthrough/; echo "exit=$?"
exit=0
$ flake8; echo "exit=$?"
./tools/generate_changelog.py:550:13: F824 `nonlocal results_queue` is unused: …
./tools/generate_changelog.py:689:13: F824 `nonlocal results_queue` is unused: …
./tools/generate_changelog.py:689:13: F824 `nonlocal min_dttm` is unused: …
./tools/json_tools/util.py:378:9: F824 `global indent_multiplier` is unused: …
exit=1
```

That is **four findings across three sites** — line 689 yields two of them.
(The specification names the three locations **(plan)**; four is the finding
count measured here.) None is under `playthrough/`, none was introduced by this
feature, and fixing them is explicitly out of scope. Anyone who "repairs" a red
global exit code by editing those files, or by adding an exclude, has changed
the wrong thing.

**CodeQL-safe.** The `python` leg of the code-scanning workflow
[.github/workflows/codeql-analysis.yml:35] scans this tree under a no-new-alerts
gate, so the tooling uses `subprocess.run([...])` argument **lists** and never
`shell=True` string interpolation, no `eval`, no unvalidated path joins, and
**no network surface of any kind**.

### The tests

Standard-library `unittest`, no new framework, discovered from this directory —
one suite per script plus `test_artifacts.py` over the artifact set, 20 in all,
run against the real scripts rather than against restatements of them, and
writing only inside their own sandboxes. It takes about fifteen minutes:

```console
$ . playthrough/tooling/env.sh
$ "$PLAYTHROUGH_PYTHON" -B -m unittest discover \
      -s playthrough/tooling -p 'test_*.py'
[...]
Ran 2507 tests in 879.849s

FAILED (errors=1, skipped=5)
```

A single suite runs against this host's artwork rather than against the record,
and it is the one error above. **It is environment-dependent, and it must not be
"fixed".** On a host whose `gfx/` pack has been re-composed since the session was
recorded, `test_tileset_provenance` refuses and names the two files that differ
— `tile_config.json` and the in-pack `SHA256SUMS` that indexes it. `gfx/` is
untracked [.gitignore:52], so `tooling/tileset_provenance.json` is the **only
tracked statement of what the film's pixels are**: the anchor is right, the
artwork the film was rendered against matched it, and regenerating the anchor to
turn a test green would destroy the evidence. The full account is in *The
provenance anchor is refusing a re-composition, not the film's artwork* in
`TECHNICAL_NOTES.md`. Every other suite passes, and the deterministic core can
be run on its own in seconds:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/test_timeline.py
[...]
Ran 361 tests in 2.594s

OK
```

(Elapsed times vary by host; the counts do not.)

pytest is deliberately absent: the repository has no Python test framework and
no Python tests across its existing scripts, and adding one would be a
gratuitous new dependency. **Nothing is added to `tests/`**, which globs
`tests/*.cpp` into the Catch2 binary — a `.py` file placed there would be swept
into the C++ test build.

---

## 11. The hard rules, and the gates that check them

Seven constraints govern the session. They are **requirement-level constraints
originating in the prompt that specified this work — not `review_rules` rules**.
That distinction is worth keeping: **no user-specified rules exist for this
project**. `review_rules` returns "No user rules provided", read in full rather
than skimmed. Nothing has been invented to fill the gap and the bar is not
lowered; enterprise-standard practice governs instead, and section 12 plus the
final section name where each obligation is discharged.

1. **Play the tiles binary; never accept the curses build.** The rule concerns
   the *binary*, not the artwork pack — a build linked against SDL and
   rendering through the tiles path satisfies it. `--version` reporting
   `+tiles` is the proof (section 3).
2. **Roleplay a real human being for the entire session**, every decision in
   character.
3. **Keep meta and "gamey" remarks out of the in-character record.** They
   belong in `TECHNICAL_NOTES.md`. This is the reason that page exists at all.
4. **The character must be unique, and if a save already exists, resume it**
   rather than replacing it (section 5).
5. **Commit everything** — the save data, every screenshot, the movie, the
   transcript, and the requirements file.
6. **Never fabricate.** Every screenshot, clock reading and caption must
   correspond to a frame that was actually captured and actually observed. OCR
   is an assist; the reading of the frame is authoritative; an unreadable value
   is reported unreadable and reconciled against the previous frame, never
   guessed — and the record says which readings those were.
7. **Absolutely no cheating, for any reason**, explicitly including avoiding
   death. Also binding: **never blind-spam keys** — the loop is observe →
   decide in character → act → capture → log.

### The acceptance gate

`tooling/verify_artifacts.sh` is the executable form of all of it. On the
shipped record:

```console
$ playthrough/tooling/verify_artifacts.sh --phase post-commit
[...]
SUMMARY  111 of 111 checks passed (111 of 111 declared for the 'post-commit'
phase), 11 informational note(s); the committed artifacts are what they claim
to be.
VERIFY_CAPTURES=326
VERIFY_ROWS=326
VERIFY_TIMELINE_TOTAL=219.500
VERIFY_TRANSITIONS=1
VERIFY=pass
```

What it asserts, by section: the `frames == manifest rows` identity and
contiguous indices from `00001`; the clamp bounds on every timeline entry, the
transition flag against the materialised group count, and the
`durations + transitions == total == final cue end` invariant; the container's
codec, resolution and inputs; the caption track and both transcripts against
the timeline; the non-blank luminance of the captures **and** of frames pulled
back out of the finished film; the version-control facts; the no-cheating
property; the binary, the required artwork and repository hygiene; and finally
its own completeness, against a per-phase declared count so a short report
cannot pass unnoticed.

Two of those checks exist specifically to convert a *silent* failure into a
loud one, and both have controls:

* **Non-blank luminance.**
  `convert <png> -colorspace Gray -format "%[fx:mean] %[fx:standard_deviation]" info:`
  must yield `mean > 0` **and** `std > 0`. Measured controls: a pure black
  frame gives `mean=0 std=0`, which is the signature of
  `SDL_VIDEODRIVER=dummy`; a **uniform solid colour** frame gives
  `mean=0.501961 std=0` — which a mean-only check would pass, and which is
  exactly why the second term is there. A real capture measures, for example,
  `0.10383 0.172987`, and a frame extracted from `cata-play-cc.mp4` at
  t = 60 s measures `mean=0.103281 std=0.1758` at 1920×1080. (The gate also
  prints the specification's calibration reading, `mean=0.270018
  std=0.198145` **(plan)**, labelled as provenance only.)
* **`git check-ignore` on the save and the captures**, because `git add` skips
  an ignored path and exits 0 (section 8).

The film's own properties, independently:

```console
$ ffprobe -v error -select_streams s -show_entries \
      stream=index,codec_name:stream_tags=language \
      -of default=nw=1 playthrough/cata-play-cc.mp4
index=1
codec_name=mov_text
TAG:language=eng
```

A `mov_text` track tagged `eng` is a **selectable** caption track — the
captured pixels are never obscured — and `cata-play.mp4` carries `h264` at
1920×1080 with no audio stream at all.

### R12 is machine-auditable, not merely asserted

The no-cheating guarantee is discharged against committed artifacts rather than
against anyone's word. `debug_mode`, `debug` ("Debug menu") and
`debug_hour_timer` are all declared **without a `bindings` array**
[data/raw/keybindings.json:3398-3403, :3404-3409, :3466-3471], so they are
unbound by default and unreachable by any keystroke unless deliberately bound.
The contrast is the very next entry, where
`DEBUG_DIALOGUE_DL_CONDITIONAL` does carry one
[data/raw/keybindings.json:3410-3418].

Because a user override would have to live at
`<userdir>/config/keybindings.json` [src/path_info.cpp:400-403], and because
the engine only writes that file when a binding is changed, its **absence** from
the committed tree is itself the evidence:

```console
$ ls -1 playthrough/userdir/config/
base_colors.json
debug.log
fonts.json
imgui_style.json
lastworld.json
options.json
```

No `keybindings.json`. The gate asserts that, and `session.py audit` checks it
before play as well.

---

## 12. What is out of scope

Stated plainly, so the boundary is not re-litigated:

* **No change to game behaviour, balance, content or presentation.** `src/`,
  `tests/`, `data/` and `gfx/` are untouched, and so is every build and CI
  file (section 8).
* **No frame decimation, sampling, deduplication, downscaling or lossy
  recompression.** One frame per keystroke, all committed. Completeness
  outranks repository size and the mitigation is engineering, not omission.
* **No debug or cheat capability of any kind** — no debug menu, no debug mode,
  no spawning, stat editing, teleport, map reveal or god mode, including as a
  death-avoidance measure (section 11).
* **No burned-in captions**, and no `-vf subtitles=` or `ass=` filter. The
  caption track stays selectable.
* **No audio.** `SOUND_ENABLED=false` and `SDL_AUDIODRIVER=dummy`; the films
  carry no audio stream, no music and no narration.
* **No publishing** — no upload, stream, hosting or external distribution — and
  **no network service, listening port or telemetry** is introduced anywhere.
* **No additional sessions, characters or worlds.** One continuous session,
  one survivor.
* **No transcript localisation.** The caption track is English only, tagged
  `language=eng`.
* **No general-purpose headless UI test framework.** This is a one-shot
  cinematography harness for a single narrated session, not a replacement for
  the manual validation the project documents for interactive UI.
* **No Figma assets and no design system**, because none were provided and
  there is nothing here to design: the only interface involved is the game's
  own pre-existing SDL renderer, whose backend is fixed at compile time, and it
  is photographed exactly as it already renders. The single visual decision the
  feature does make — the transition card's typeface — resolves to the game's
  own `data/font/Terminus.ttf` rather than to an introduced font.
* **No new test framework**, and nothing added to `tests/` (section 10).
* **No Windows, macOS, Android or Emscripten capture path.** The pipeline
  targets the Linux/X11 headless environment described in section 4.
* **No refactoring of the repository's existing Python**, and no fixing of its
  pre-existing `F824` findings (section 10).
* **No SDL3 build path**, since the available SDL3 is below the Makefile's gate
  (section 3), and **no curses build**.

---

## Where to read next

* `TECHNICAL_NOTES.md` — the engineering log: every measurement with the
  command that produced it, every pitfall, and every place a plan figure did
  not reproduce. Start at its own front matter, which maps the page and says
  which capture set each block describes.
* `dossier.md` — the survivor, in his own words, written before the first
  keystroke.
* `transcript.md` — the session, timestamped in cumulative video time.
* **The stages' own `--help`.** All ten Python modules take `--help`, and so do
  `capture.sh`, `commit_artifacts.sh`, `embed_captions.sh`, `launch_game.sh`,
  `run_pipeline.sh`, `supported_env.sh` and `verify_artifacts.sh`. `env.sh`
  ignores arguments and prints the resolved contract instead; and
  `preflight_capture.sh` has no help text — it runs, and its file header is the
  documentation. Those texts are the authority for flags, tunables and exit
  codes; this page is the authority for order, layout and intent.

Enterprise-standard practice governs this work in the absence of any
user-specified rules, and the six obligations that follow from it are each
discharged somewhere specific rather than asserted here: **conform to the host
project's conventions** rather than bending them (the 79-column lint contract
is satisfied, not excluded — section 10 — and the requirements file follows the
repository's own precedent — section 3); **minimise the blast radius** (two
files, 26 inserted lines, zero deletions, machine-checked — section 8); **do
not create merge-conflict surfaces in upstream-synced files** (the root
`README.md` deviation, with its reason, at the top of this page); **evidence
over assertion** (`[path:locator]` citations and executed commands throughout,
with plan figures marked **(plan)**); **make integrity claims auditable** (R12
discharged against committed artifacts — section 11); and **least privilege
over the repository** (repository-local git identity only, no history
rewriting, no force-push, no global configuration change — section 5).
