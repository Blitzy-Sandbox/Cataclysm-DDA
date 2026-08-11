# playthrough/ — the capture and cinematography subsystem

One survivor, one continuous session, one screenshot per keystroke, and a film
whose pacing is the in-game clock rather than a frame rate.

Everything in this directory is either **evidence** — the captures, the record,
the save the engine wrote, the films, the transcripts — or the **tooling** that
produced it. Nothing here changes the game. **The Cataclysm-DDA engine is the
*host* of this feature, not its subject:** the shipped binary is invoked, the
sidebar clock is read, and the rendered pixels are photographed, all through
interfaces the engine already had. No game behaviour, balance, content or
presentation is altered, and **no tracked file** under `src/`, `tests/`,
`data/` or `gfx/` is modified by any of it. One untracked thing outside this
directory does get written, and it is named rather than glossed: the required
tileset is *installed* into `gfx/MShockXotto+`, which `.gitignore:52` excludes,
so it is artwork on the host rather than source in the repository (section 3).

`gfx/` is the one exception and it is stated rather than glossed: the required
MSXotto+ artwork is **installed into `gfx/`** by `launch_game.sh`, which
hydrates it from a pre-placed pack whose provenance is verified against the
tracked anchor before it is used. That directory is git-ignored
(`.gitignore:52`, with four negations), so the installation produces **no
tracked change** — which is why it is invisible in a diff and why saying "no
`gfx/` path is touched" was wrong in a way nothing would have caught. Nothing
under `gfx/` is *authored* here; a pack is installed there, and the artwork
every frame is rendered in is therefore the one substantive input git does not
carry, which is exactly why the anchor exists.

## The four documents, and which one to read

| Page | Audience | Holds |
| --- | --- | --- |
| `REPORT.md` | anyone arriving for the first time | the deliverable account, in the three mandated sections: the recording and animation, the character creation, and the session itself |
| `README.md` (this page) | operator | the artifact inventory, the prerequisites, how to re-run each stage, the environment contract, the commit lifecycle, the contracts the gates check |
| `TECHNICAL_NOTES.md` | engineer | the measurements, the pitfalls, the divergences, and the chronological log of how the record was produced and reviewed |
| `dossier.md`, `transcript.md` | reader | the survivor's own voice, and nothing about machinery |
| `REPORT.md` | reviewer | the mandated three-section account of the recording, the character and the session — every figure measured, and every requirement that is not fully met named in the section it belongs to |

This page is a reference; `TECHNICAL_NOTES.md` is a log. Where a fact here has
an evidence trail longer than a sentence, this page states the fact and names
the section of that page which measured it, rather than reproducing the
working. There is no in-character voice anywhere on this page, and no
engineering narrative either — both live elsewhere on purpose.

**Provenance convention.** A figure stated plainly was measured in this
checkout with the command shown. A figure marked **(plan)** comes from the
Agent Action Plan and was *not* reproduced here. Where a plan figure and a
measurement disagree, both appear and the disagreement is named.
`TECHNICAL_NOTES.md` uses the same convention.

It is a discipline, not a guarantee, and it is written that way deliberately:
a measurement is only true of the tree it was taken in, and this page has been
found publishing stale ones — a commit count, a test count and an acceptance
result that had all moved on. So counts here name the commit or the date they
were taken at, a reader is entitled to re-run the command beside them, and
where this page and `TECHNICAL_NOTES.md` disagree about a number the later
measurement date wins. Unless a figure says otherwise, the measurements below
were taken at **`5f902536e8`** on **2026-08-10**.

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
33
```

(That count moves with every commit this feature adds; 32 is what it read at
`5f902536e8`. The number that matters is not its value but that every one of
them is under `playthrough/` or one of the two ignore files — section 8
measures that.)

`f38c2fbae3` is the branch base — the last upstream commit before any of this
work — and the acceptance gate names it as the point the change surface is
measured from. That last count is whatever it was **when this line was
written**: every later commit on this branch moves it, so a reader running the
command today should expect a larger number. The two commands above it are
stable, and those two are the ones `test_readme.py` asserts — a figure that
drifts by design is quoted here and deliberately left unasserted, rather than
asserted and left to rot. The root `README.md` is therefore an **upstream-synced** file:
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

The shipped session: **307 captures**, **300.500 s** of film, **twelve**
transitions. Read `REPORT.md` for the deliverable account, `transcript.md` for
the survivor's own, and `TECHNICAL_NOTES.md` for how it was produced and
reviewed.

---

## 2. What is in this directory

| Path | What it is | Written by |
| --- | --- | --- |
| `tooling/` | the authored pipeline — 9 shell entry points, 10 Python modules, 21 `test_*.py` suites, `requirements.txt`, `requirements.lock`, `tileset_provenance.json`, `environment/Dockerfile`. Kept out of the game's source tree on purpose | authored |
| `frames/frame_NNNNN.png` | exactly one 1920×1080 capture per keystroke — 307 of them, contiguous from `frame_00001`, none decimated, sampled or deduplicated | `capture.sh` |
| `manifest.jsonl` | one row per capture, six fields: `frame`, `file`, `real_ts`, `ingame_clock`, `action`, `commentary` | `session.py` |
| `amendments.jsonl` | corrections to the record, **appended** rather than applied in place, so the original reading survives beside the correction | operator, via `session.py annotate --amend` and review |
| `timeline.json` | the computed durations and transition flags — **the single source of truth** for both the film and the captions | `timeline.py` |
| `build/` | intermediates and telemetry: `concat.txt`, `transitions/`, `observations.jsonl`, `frame_dates.jsonl`, `frame_digests.jsonl`, `transitions.json`, `movie.json`, `transcript.json`, `acknowledgments.jsonl` | the stage that owns each |
| `build/evidence_anchor.jsonl` | the hash-chained, append-only seal over every evidence artifact — each row carries the artifact's sha256, its byte count and **git's own blob name**, plus the previous row's chain hash. The chain's head is published as a `Playthrough-Evidence-Anchor:` trailer on every checkpoint, which is what puts it beyond the reach of anyone editing the working tree | `commit_artifacts.sh`, at each checkpoint |
| `cata-play.mp4` | the film: `h264`, 1920×1080, no audio stream | `render_movie.py` |
| `cata-play-cc.mp4` | the same film with a selectable `mov_text` caption track tagged `language=eng` | `embed_captions.sh` |
| `transcript.srt` | the caption cue file — 307 cues | `make_srt.py` |
| `transcript.md` | the timestamped, in-character record — 307 entries, cumulative video time | `make_srt.py` |
| `dossier.md` | the survivor's first-person backstory, written and committed **before** the first gameplay frame | authored |
| `userdir/` | the engine's own tree: `save/<World>/`, `config/`, `achievements/`, `templates/`, `cache/`. Committed. The **save** is the engine's alone and is never edited; the **config** is engine-created and then patched in place by `seed_options.py` (see below) | the game, plus `seed_options.py` for `config/options.json` |
| `TECHNICAL_NOTES.md` | the engineering log — measurements, pitfalls, divergences | authored |
| `REPORT.md` | the deliverable account, in exactly three sections: *A) Screen Recording and Animation*, *B) Character Creation*, *C) Playing the Game* | authored |
| `acceptance-report.txt` | the gate's own passing verdict set over the tree it measured — committed so a verdict outlives the terminal it was printed at | `verify_artifacts.sh` |
| `README.md` | this page | authored |

Two properties of that set are easy to lose and are therefore stated rather
than left to be inferred.

**Frame-directory purity is an integrity constraint, not a preference.**
`frames/` holds exactly one PNG per keystroke and nothing else. Derived
imagery — the materialised transition pictures — goes to `build/transitions/`,
never here, because the acceptance gate asserts

```console
$ ls -1 playthrough/frames/frame_*.png | wc -l
307
$ wc -l < playthrough/manifest.jsonl
307
```

and mixing derived images into `frames/` would destroy that identity while
every other count still tallied.

**Everything is committed**, including every frame and both films:

```console
$ git ls-files playthrough | wc -l
662
$ git ls-files playthrough/frames | wc -l
307
$ git ls-files playthrough/userdir | wc -l
149
$ git ls-files playthrough/userdir/save | wc -l
134
```

`userdir/save` holds the whole **live** world, and that is the engine's doing
rather than a choice: the survivor slept through the night, woke to her alarm
and left through the in-game Save & Quit, so the world was kept. Those 134
files are one world, `Fairport Harbor` — `master.gsav`, `dimension_data.gsav`,
ten `o.N.N` overmap segments, 95 map chunks under `maps/`, five memory-map
files under `#<base64>.mm1/`, the fourteen `#<base64>.seen.N.N` visibility
files, and the survivor's own `#T2RldHRlIFZhY2hvbg==.sav` beside its `.log`,
`.pt`, `.ano.json` and `.zones.json` companions. The remaining fifteen tracked
userdir files are seven in `cache/`, six in `config/`, one character template
and one achievement. Section 9 has the whole sequence.

There is **no** `userdir/graveyard`, and its absence is evidence rather than an
omission: the engine creates one only by `move_save_to_graveyard()` on death.
An earlier recording of this feature did end in death and did carry eleven
graveyard files; this one ends the way AAP requirement R11 names first, so the
save stayed where a living survivor's save lives.

The `git ls-files playthrough` total moves with every commit that adds a
tooling file or a suite, so `test_readme.py` asserts the two that are
properties of the **recording** — the captures and the save files — by running
the commands above and comparing their output with what is quoted here, and it
quotes the total without asserting it.

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

**Probe before you claim the tree is ready — do not assume this command
works.** In a fresh clone it fails, because there is no binary to ask:

```console
$ ./cataclysm-tiles --version
bash: ./cataclysm-tiles: No such file or directory
$ playthrough/tooling/launch_game.sh build      # then ask again
```

Once a binary exists, verify whichever one you ended up with by asking it what
it is:

```console
$ ./cataclysm-tiles --version
Cataclysm Dark Days Ahead: <the short commit YOUR tree was built from>

+tiles, +sound

data dir: data/
user dir: ./
```

**The commit line is deliberately not a literal here.** It used to carry a
hard-coded hash, which read as a measurement of this tree and was not one: the
binary built from this checkout reports its own `HEAD`, so a fixed hash in a
document that outlives one commit is wrong for every tree except the one it was
copied from. Compare it against `git rev-parse --short=10 HEAD`.

They agree on a tree that has not been committed to since the build, and
disagreeing does **not** by itself mean the binary is stale: this subsystem
commits to `playthrough/` regularly, and a commit that touches nothing the
engine is built from cannot change a single rendered pixel. What actually
matters is whether the ENGINE has moved, so ask that instead:

```console
$ git diff --name-only \
      "$(./cataclysm-tiles --version | head -1 | awk '{print $NF}')"..HEAD \
      -- src Makefile CMakeLists.txt data gfx
```

Empty output means the binary describes HEAD's engine and is fine to capture
with, whatever the two hashes read. Any path listed means the binary predates
code or content that the record would otherwise be photographed against, and
it must be rebuilt before anything is captured. Note that the gates enforce
only the `+tiles` property, not this one -- it is a judgment about whether the
film shows the tree the record describes, which is why it is stated here as an
operator check rather than asserted as a measurement.

That **`+tiles`** string is the direct, self-reported proof this is the SDL
tiles build and not the curses one. The rule is about the *binary*, not about
which artwork pack is selected. The hash on the first line names whichever
commit that particular build came from, so it differs between builds and
between worktrees; `+tiles` is the line that carries the claim, and it is the
line `test_readme.py` holds this block to.

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
  **(plan)**. Measured here the ceiling is CPU rather than memory, and the
  figures have to be read from the **cgroup** rather than from `/proc`,
  because `/proc` is not namespaced and reports the whole machine. Read at
  `/sys/fs/cgroup/$(cut -d: -f3 /proc/self/cgroup)/` on **2026-08-10**:
  `cpu.max` is `400000 100000`, i.e. **4 CPUs**; `memory.max` is
  `137438953472`, i.e. **128 GiB**; `memory.swap.max` is **`0`**, so this
  scope gets no swap at all. `/proc` meanwhile shows the host's
  `MemTotal: 4029526764 kB` (3.75 TiB) and `SwapTotal: 6291452 kB`, and
  `nproc` reports **4** against `nproc --all`'s **128** — the only two
  numbers on this host that agree with the cgroup. Either way `-j3` is safe
  and `-j128` is not: the limit is the four CPUs, not the memory the plan
  worried about.
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
this host. Note also that a venv built from the system interpreter would be
3.13, not the 3.12 the pins contract for, so it could not install the lock at
all — `numpy` and `Pillow` ship per-interpreter binary wheels.

**Provision it from packages the archive key already trusts, and do not
bootstrap pip off the network.** This page used to recommend
`python3 -m venv --without-pip` followed by fetching `get-pip.py`, and that
advice contradicted the whole point of the file it was helping to install: a
script downloaded and executed with the caller's privileges, with no pin and no
signature, is precisely the unverified trust anchor `requirements.lock` exists
to eliminate for everything downstream of it. Installing a hash-pinned closure
*through* an unverified installer establishes nothing.

The supported routes, in order of preference:

1. **Use the container.** `playthrough/tooling/supported_env.sh` drives an image
   that already carries the interpreter and the pinned closure, which is also
   the sanctioned path when the host release is out of support.
2. **Install the distribution's own `python3-venv` and `python3-pip` for a 3.12
   interpreter** with `apt-get`, so the artifacts come from a repository apt
   already verifies, and create the environment with pip present from the
   start.
3. **If a 3.12 interpreter genuinely has to be built** — this archive carries no
   `python3.12` package — build it from the release tarball whose published
   **sha256 you verify before extracting**, and record the digest you checked
   beside the command. That is what was done for `/opt/python3.12` on this host.

Whichever route, install with the lock rather than the declaration:
`pip install --require-hashes --only-binary :all: --no-deps -r
playthrough/tooling/requirements.lock`. The pipeline resolves its own
interpreter and reports which one:

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
* **Launch fully detached, and launch it through `launch_game.sh`.** A
  foreground long-running child can have its whole process group signalled when
  an outer call times out, which kills the game mid-session, so the launch uses
  `setsid nohup ... </dev/null & disown` — the strongest detachment a shell can
  perform.

  ```bash
  playthrough/tooling/launch_game.sh launch     # detached
  playthrough/tooling/launch_game.sh guard      # foreground, owns the instance
  ```

  **There is deliberately no raw command to copy here any more.** This page used
  to print the bare `setsid nohup ./cataclysm-tiles ... >/tmp/cata.log` line,
  and pasting it skips everything that makes a launch safe and clone-scoped:
  the log goes to a **predictable, world-writable path** that another local
  account can pre-create as a symlink — the redirection then truncates and
  overwrites whatever it points at, with this process's privileges — while the
  launcher writes to a verified 0700 runtime root instead. It also bypasses the
  X cookie (so the display has no access control and any local account can read
  the screen being captured and inject keystrokes), the per-checkout launch lock
  (so two runs can drive one save), the geometry and tileset assertions, and the
  `CLONE_INDEX` offsets that keep parallel checkouts off each other's display.
  None of that is visible in the failure mode: the game starts and the frames
  look fine.

  `launch_game.sh guard` is the variant that stays in the foreground and owns
  the instance for its whole lifetime, for callers that need something to hold
  the process.
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
  across the whole 307-frame population they are all at the **bottom**, rows
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

`tooling/environment/Dockerfile` declares the **tooling** half of a capture
environment on a Linux release that is **in support** — the X server and window
manager, `xdotool`, ImageMagick, ffmpeg, tesseract, the engine's SDL2 runtime
and fonts, `g++-14` for rebuilding the engine in the same place that captures
it, and a sha256-pinned CPython 3.12 with `requirements.lock` installed into
`/opt/playthrough-venv`. It is **not** self-sufficient for a recording, and the
gap is named in *The required artwork is the one input nothing can hand you*
below: the image ships **no artwork**, because `gfx/` is untracked, so the
required tileset has to be present in the mounted checkout before the engine is
launched. `tooling/supported_env.sh` drives the image:

```console
$ playthrough/tooling/supported_env.sh build        # build the image
$ playthrough/tooling/supported_env.sh inventory    # what it actually contains
$ playthrough/tooling/supported_env.sh preflight    # prove the path end to end
$ playthrough/tooling/supported_env.sh run playthrough/tooling/run_pipeline.sh --no-commit
$ playthrough/tooling/supported_env.sh shell        # a shell inside it
```

#### Recording a session inside it — the hosted-session lifecycle

`run` starts a container, runs one command and takes it away again, which is
right for a render and useless for a **recording**: the X server, the window
manager and the engine all live inside the container, and a session is some
hundreds of keystrokes each delivered by its own command. Every one of them has
to reach the **same** container, so recording uses `up`, a series of `exec`s, and
`down`.

```console
$ playthrough/tooling/supported_env.sh up                     # start the session
$ playthrough/tooling/supported_env.sh exec playthrough/tooling/launch_game.sh headless
$ playthrough/tooling/supported_env.sh exec playthrough/tooling/launch_game.sh launch
$ playthrough/tooling/supported_env.sh exec bash -c 'source playthrough/tooling/env.sh \
      >/dev/null; "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/seed_options.py'
$ playthrough/tooling/supported_env.sh exec playthrough/tooling/launch_game.sh stop
$ playthrough/tooling/supported_env.sh exec playthrough/tooling/launch_game.sh launch
$ playthrough/tooling/supported_env.sh exec bash -c 'source playthrough/tooling/env.sh \
      >/dev/null; "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py step \
      --key Return --action "open the menu" --commentary "why the survivor did it" \
      --observed "what the last frame showed" --expect changed'
  # ... one exec per keystroke, then the in-game Save & Quit ...
$ playthrough/tooling/supported_env.sh exec playthrough/tooling/commit_artifacts.sh final
$ playthrough/tooling/supported_env.sh down                   # end the session
```

**Why the Python steps are wrapped in `bash -c 'source … env.sh; …'` and the
shell steps are not.** `exec` deliberately forwards almost nothing — `HOME`,
`TMPDIR` and the cleared bypass names — so that what a hosted command sees is
the container's contract and not the host's shell. Every `*.sh` stage sources
`env.sh` itself, so it establishes `DISPLAY`, `XAUTHORITY` and the rest on the
way in. A bare `python` child does not, and the symptom is specific rather than
vague: Xvfb here runs with a MIT-MAGIC-COOKIE, so without `XAUTHORITY` the
first thing that tries to reach the display fails outright.

```console
$ supported_env.sh exec sh -c 'echo "[$DISPLAY][$XAUTHORITY]"; xdotool search --class cataclysm-tiles'
[][]
Error: Can't open display: (null)
$ supported_env.sh exec bash -c 'source playthrough/tooling/env.sh >/dev/null; \
      echo "[$DISPLAY][$XAUTHORITY]"; xdotool search --class cataclysm-tiles'
[:99][/tmp/xdg/playthrough/Xauthority]
4194313
```

Sourcing `env.sh` first is therefore not a stylistic flourish; it is the only
form in which a Python step can deliver a keystroke at all.

**In order, and why each step is where it is:**

1. **`up`** starts the container detached with this checkout mounted, and prints
   `SESSION_CONTAINER` and `SESSION_NAME`. Nothing is running inside it yet.
2. **`exec launch_game.sh headless`** brings up Xvfb at 1920×1080×24 and openbox
   *inside* the container and verifies the display. They outlive the `exec`, which
   is the whole reason `up` exists.
3. **`exec launch_game.sh launch`** starts the engine for **calibration**: a
   fresh userdir opens on a language prompt rather than the main menu, and the
   window is created at the compiled-in 640×384 until the game has written
   screen-derived values into `options.json`. Nothing captured here is evidence.
4. **`exec … seed_options.py`** patches that generated `options.json` in
   place — 24-hour clock, sound off, the required tileset, the terminal geometry —
   and the world's `CHARACTER_POINT_POOLS` when a character is about to be
   created, so the creator opens on a points pool. There is no subcommand: the
   bare invocation patches, and `--verify-only` re-reads without writing.
   `--dry-run` and `--explain` are the other two read-only forms.
5. **`exec launch_game.sh stop`, then `launch` again**, so the seeded values take
   effect. `stop` terminates a **calibration** instance and saves nothing — and it
   refuses outright once a recorded session is in progress, which is exactly the
   guard that keeps it from being used to kill a session that has captures. From
   this second launch onward the frames are evidence.
6. **One `exec session.py step` per keystroke.** The loop is observe → decide in
   character → act → capture → log, and the tool enforces it: each step carries
   `--observed` (your reading of the previous capture), an `--expect`, and the
   action and commentary that become the transcript. A step whose observed effect
   contradicts what was declared halts the session rather than pressing on.
7. **The ending happens inside the game** — sleep, wake, then `S` and `Y` at
   *Save and quit?* — so the last delivered key lands on a capturable main menu.
8. **`exec commit_artifacts.sh …`** takes the checkpoints from inside the
   container, where the identity is forwarded in from the host.
9. **`down`** stops and removes the container, and **refuses** while the engine is
   still running: taking it down mid-session would end a recorded session outside
   the game's own ending. `down --abandon 'why'` is the explicit way to end one
   anyway, and the reason is required rather than optional.

**`session`** reports the state at any point, and reads nothing but labels:

```console
$ playthrough/tooling/supported_env.sh session
SESSION_NAME=playthrough-session-<checkout digest>-<clone>
SESSION_CHECKOUT=<checkout digest>
SESSION_CLONE=0
SESSION_CONTAINER=<id, empty when none>
SESSION_UP=yes|no
SESSION_DISPLAY=serving|down
SESSION_ENGINE=none|<pid>
```

**A session is identified by labels, never by name.** The container carries the
checkout's path digest and `CLONE_INDEX` (validated as an integer 0–99) as Docker
labels, the match is selected by exact label rather than by a name pattern, and
the match is then *inspected* for its image, its bind mount and its user before it
is used. More than one match, or a foreign one, is refused rather than adopted —
which matters concretely on a host running several clones: a sibling's container
must never be exec'd into, and a stale one must never be mistaken for this one's.

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
way in and will not forward one. Regenerating the *derived* artifacts inside the
image reproduces the committed films, timeline, transcript and cue file byte for
byte — that is a render, which needs the record and not the artwork. A
**recording** additionally needs the pack, and that is the next section.

The acceptance gate is the one stage that is safe to run anywhere, because it
reads committed evidence and writes nothing. It treats a **capture-time**
bypass as a failure — evidence produced under a relaxed check is not evidence —
and this one as a warning, in its own words: it "says something about the host
doing the reading rather than about the session that was recorded".

### The required artwork is the one input nothing can hand you

`gfx/` is git-ignored [.gitignore:52], so the MSXotto+ pack the film is rendered
in is the single input that neither the repository nor the image carries.
`tooling/tileset_provenance.json` is the tracked statement of exactly which
bytes it must be — **22 files, 5 260 542 bytes,
`tree_sha256=7d853c21de2e9281…`**, composed from upstream
`I-am-Erk/CDDA-Tilesets` at **`6e864adbd2c5d0e68f8517b34e3c7d58eb22747d`** — and
`launch_game.sh` verifies the installed tree against it on **every** launch,
with no bypass for the required tileset. A pack that does not match cannot be
recorded under; that refusal is the design and not a bug.

**Provisioning it, exactly.** Seven steps, run from the repository root with
network access. Every one of them is required, and the three that are easy to
skip are called out underneath.

```console
$ git clone --filter=blob:none --sparse --no-checkout \
      https://github.com/I-am-Erk/CDDA-Tilesets.git /tmp/cdda-tilesets
$ git -C /tmp/cdda-tilesets sparse-checkout set gfx/MShockXotto+
$ git -C /tmp/cdda-tilesets fetch --depth 1 origin \
      6e864adbd2c5d0e68f8517b34e3c7d58eb22747d
$ git -C /tmp/cdda-tilesets checkout \
      6e864adbd2c5d0e68f8517b34e3c7d58eb22747d
$ git -C /tmp/cdda-tilesets rev-parse HEAD    # 6e864adbd2c5d0e68f…
$ make SDL3=0 RELEASE=1 TILES=1 SOUND=1 ASTYLE=0 LINTJSON=0 \
      COMPILER=g++-14 tools/format/json_formatter.cgi
$ /opt/gfxtools-venv/bin/python tools/gfx_tools/compose.py \
      --feedback CONCISE --format-json --loglevel INFO \
      /tmp/cdda-tilesets/gfx/MShockXotto+ gfx/MShockXotto+
$ for f in fallback.png layering.json tileset.txt; do \
      cp -- "/tmp/cdda-tilesets/gfx/MShockXotto+/$f" "gfx/MShockXotto+/$f"; \
  done
$ ( cd gfx/MShockXotto+ && find . -type f \! -name SHA256SUMS \
      -exec sha256sum {} + | LC_ALL=C sort -k2 > SHA256SUMS )
$ playthrough/tooling/tileset_provenance.py verify \
      --directory gfx/MShockXotto+
```

**The commit is FETCHED AND CHECKED OUT, not merely asserted.** An earlier
version of this recipe cloned `--depth 1` and then printed `rev-parse HEAD` with
a comment saying which commit it "must be" — which pins nothing: a shallow clone
takes the branch tip, so the same commands run a week later compose a different
pack and the launch gate refuses with no hint as to why. `--no-checkout` plus a
`fetch --depth 1 origin <sha>` and a `checkout <sha>` lands exactly on the
pinned tree.

**`compose.py` does not emit three of the files, and they are copied
verbatim.** `fallback.png` (316 141 B), `layering.json` (8 126 B) and
`tileset.txt` (961 B) come straight from the upstream directory; the composer
writes the seventeen sprite atlases and `tile_config.json`, which is eighteen,
and the in-pack `SHA256SUMS` is generated over the resulting twenty-one. Omit
the copy and the tree is three files short of the anchor. Measured against the
pinned upstream checkout: all three match the anchor's digests byte for byte
(`e82e2e775517…`, `b7c9bbe894aa…`, `e57dad8057a7…`).

**`json_formatter.cgi` must be built first.** With it, `tile_config.json` is
**625 336 bytes** — the anchor's own figure. Without it `compose.py` logs
`Python built-in formatter was used` and leaves the `json.dump(indent=2)` output
in place, which is **1 036 187 bytes** for the same data: re-serialising the
composed index that way on this host produces exactly that size, so the
difference is the formatter and nothing else.

**`compose.py` needs `pyvips`, which is deliberately outside the pinned
closure.** It is not in `requirements.lock` and not in the image, because it is
a repository tool with its own dependency rather than part of this pipeline's
runtime; `/opt/gfxtools-venv` carries it (pyvips 3.1.1, libvips 8.16.1) and the
recipe above calls that interpreter explicitly.

**Measured on this host: the procedure reproduces the anchor exactly.**

```console
$ playthrough/tooling/tileset_provenance.py verify --directory gfx/MShockXotto+
  TILESET_PROVENANCE=verified
  TILESET_PROVENANCE_TREE_SHA256=7d853c21de2e9281258d144409f104f58b14e8ece5dfdf…
  TILESET_PROVENANCE_FILES=22
  TILESET_PROVENANCE_UPSTREAM_COMMIT=6e864adbd2c5d0e68f8517b34e3c7d58eb22747d
```

All 22 installed files are byte-identical to the anchor, and so are all 22 of
the freshly composed pack cached at `/opt/cdda-gfx-cache/MShockXotto+` — nothing
differs, in either direction. So a re-recording needs no preserved copy of the
artwork and no re-anchor: the pack is derivable from the inputs recorded above,
which is the property that makes the film's declared pixels reproducible.

**`tileset_provenance.py generate` exists and is not part of this recipe.** It
rewrites `tileset_provenance.json` over whatever pack is on disk. That is a
legitimate act when the artwork legitimately changed, and a destructive one
otherwise: it replaces the tracked statement of what the shipped film's pixels
are with a statement about a different pack. It must be a recorded decision
taken in its own commit, and it is never the way to turn a failing launch gate
green — the point of the anchor is that a pack which does not match the film
cannot be recorded under.

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

**`env.sh` does not enforce this, and it is worth being exact about why.** This
page used to claim it "refuses to define a contract if it is sourced from
anywhere else", which is false and easy to disprove: sourcing it with the shell
sitting in `/tmp` succeeds and resolves `PLAYTHROUGH_REPO_ROOT` correctly,
because it derives the checkout from `BASH_SOURCE` — its own location — rather
than from the working directory. That design is deliberate and it is the more
useful one: every absolute path it exports is then correct no matter where a
caller happens to be, so no sibling script has to guess. What it *does* refuse
is a location that is not a Cataclysm-DDA checkout at all (no `data/`, no
`src/path_info.cpp`).

So the working directory is a requirement of **the engine and the git-tracking
of the save**, enforced by the scripts that launch and commit rather than by the
contract file. `run_pipeline.sh` and the other entry points `cd` to the
repository root themselves before doing anything, which is what makes the
requirement hold in practice; if you drive a module by hand, `cd` there first.

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

**Every step also proves there is room for the frame before the key is sent.**
A session is deliberately unbounded and every capture is kept at full
resolution, so `frames/` only ever grows — and a disk that fills *between* the
keystroke and the photograph is the worst shape that failure can take: the key
has been acted on and cannot be un-pressed, the capture is truncated or absent,
and a keystroke with no frame breaks the identity the whole record rests on for
a reason no later stage can repair. So `step` refuses first, with the session
left exactly where it was:

```console
playthrough: FATAL: there is not room to record frame 1: 1024 byte(s) free where
<frames> lives, against a reserve of 20971520 and therefore 20970496 byte(s)
short.  The reserve is 64 keystroke(s) of headroom over a 65536-byte floor, plus
16777216 for the sidecars, the journal and the save the engine rewrites.  THE KEY
HAS NOT BEEN SENT, so nothing is lost: free space and press it again.  [...]
$ echo $?
6
```

(Measured with the disk measurement substituted, in a sandbox tree, which is why
the reserve falls to its floor and the path is elided — the message is otherwise
the one the code emits.)

The reserve is **self-calibrating and costs two syscalls**: the size of the
previous capture (one `stat` of one derived filename — never a listing of the
directory, which would be O(captures) *per keystroke*) times 64 keystrokes of
headroom, plus a 16 MiB floor for the sidecars, the journal and the save the
engine rewrites. Because it is that cheap it is taken on **every** key rather
than occasionally. `PLAYTHROUGH_CAPTURE_RESERVE` names a different reserve
exactly, for a host whose figures are unusual; there is deliberately no value
that switches the check off, and a value that is set but unreadable is refused
rather than defaulted. A `statvfs` that cannot be read is reported once and the
step proceeds — that is a fact about the host, and the capturer refuses a frame
it could not write on its own account.

### The resume-versus-create branch

The rule is *if a save already exists, continue that save file*, so a
pre-flight probe of `playthrough/userdir/save/*/` runs before any character
creation:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/session.py probe
PLAYTHROUGH_SESSION_MODE=resume
PLAYTHROUGH_SAVE_DIR=playthrough/userdir/save
PLAYTHROUGH_SAVE_WORLD=Fairport Harbor
PLAYTHROUGH_SAVE_WORLD_COUNT=1
PLAYTHROUGH_SAVE_RESUMABLE_COUNT=1
PLAYTHROUGH_SAVE_CHAR_COUNT=1
PLAYTHROUGH_SAVE_CHAR_FORMS=.sav
PLAYTHROUGH_SCENARIO=missed
```

`launch_game.sh probe` reports the same decision from the shell side. On a clean
tree it resolves to **create**; on a tree carrying a live save it resolves to
**resume**. The reading above is this checkout's, and it says **resume** — the
recorded session ended through Save & Quit, so Odette Vachon's world is still
there and the rule *if a save already exists, continue that save file* now
points at her. Anyone re-running the pipeline over this tree continues her day;
producing a different survivor would mean retiring this evidence first, which
is what the two retirement commits in this history did to the recording before
it.

**There is a third answer, and it is a refusal.** If the append-only record
shows the survivor beginning their last words while a live character save is
still sitting in the world, the probe refuses rather than answering either way,
and names the frame, the survivor and the three ways forward. That state is what
a process ended *inside* the death screen leaves behind: CDDA writes the
character file during play and only moves it to the graveyard in
`cleanup_at_end()`, which runs after that screen — so the save on disk reads as
a perfectly ordinary living character, and resuming it would put a dead
survivor back into play with nothing in the save to show it. Resumability is
therefore decided from the record and the engine's cleanup products, never from
the shape of the save.

**Why the probe answers `resume` in this checkout.** The recorded session ended
the way R11 names first: the survivor slept, woke, and left through the in-game
Save & Quit. `cleanup_at_end()` therefore never took the death path, so
`move_save_to_graveyard()` never ran, `WORLD_END` never cleared anything, and
`playthrough/userdir/save/Fairport Harbor/` still holds one living character
beside its world. One world, one resumable character, and the reading above says
so in all three counts.

That is the interesting half of the refusal described just before it. The two
states are told apart not by the save — which looks identical in both — but by
the **record**: a session that stopped inside the death screen leaves a
live-shaped save with a record that shows the survivor's last words, and a
session that closed properly leaves a live-shaped save with a record that ends
on a main menu. Only the second is resumable, and only reading the record can
tell you which one you have.

The creator is entered through the
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
$ playthrough/tooling/run_pipeline.sh --no-commit     # stages and gate, no commit
$ playthrough/tooling/run_pipeline.sh --from render   # retry a late stage
$ playthrough/tooling/run_pipeline.sh --only srt      # one stage
$ playthrough/tooling/run_pipeline.sh --rebuild       # ignore the run receipt
```

**Two preconditions decide whether the full run can complete, and neither is a
property of the artifacts.** They are listed here rather than discovered at
stage 7, because the sequencer refuses on both *before* the first stage runs and
an operator reading a refusal should already know why:

* **The Python closure has to be the reviewed one.** The plan is refused unless
  all six declared libraries are installed at their declared versions in a
  CPython 3.12 interpreter, importable, with the declaration and the lock in
  agreement — and the refusal names each property that failed. Exact pins exist
  so a later release cannot quietly change the rendered film while every other
  gate still passes, which an unmeasured closure would allow.
* **The trust state has to be `trusted` for any plan that WRITES.** Five of the
  nine stages derive a delivered artifact; a plan containing any of them is
  refused outright while a trust bypass or the platform waiver is in force,
  because the earlier stages would otherwise rewrite the timeline, the
  transition frames and both transcripts before the render's own refusal
  arrived. A plan that only reads and publishes is always permitted — the
  measuring, committing, attesting and publishing stages derive nothing, so
  `--only verify` and `--from verify` are both exempt — and that exemption is
  the important half: measuring a tree and publishing what is already in it are
  what you need most when the host is imperfect.

**And a full run cannot reach its checkpoint on this checkout today**, which is
a fact about the record rather than about the tooling. `commit` takes the `media`
checkpoint, and `media` is about a session whose save has already been published:
it needs a `final` checkpoint for the survivor this userdir has loaded, reached
from that survivor's own `creation`. The newest creation here names a *superseded*
survivor, so the preflight refuses before stage 1 and no stage runs. Until the
session is re-recorded to a genuine ending, `--no-commit` is the invocation that
completes — it runs every stage up to and including the pre-commit gate — and the
lifecycle below is what has to be repaired first.

| # | Stage | Runs | Produces |
| --- | --- | --- | --- |
| 1 | `timeline` | `timeline.py` | `timeline.json` |
| 2 | `transitions` | `make_transitions.py` | `build/transitions/*.png` |
| 3 | `render` | `render_movie.py` | `cata-play.mp4` |
| 4 | `srt` | `make_srt.py` | `transcript.srt` + `transcript.md` |
| 5 | `captions` | `embed_captions.sh` | `cata-play-cc.mp4` |
| 6 | `verify` | `verify_artifacts.sh --phase pre-commit` | a verdict |
| 7 | `commit` | `commit_artifacts.sh media` | a checkpoint |
| 8 | `attest` | `verify_artifacts.sh --phase post-commit --report-to <outside the checkout>` | a report |
| 9 | `publish` | `commit_artifacts.sh attest` | a checkpoint |

**The gate runs twice, and that is deliberate.** Most of its checks are
properties of the *artifacts* and can be answered the moment a render finishes.
A minority are properties of the *history* — is the save tracked, is every
artifact class committed, is the tree clean, does **this** recording have a
checkpoint pair of its own — and a commit is what makes those true. So the
functional half guards the commit and the history half reports what the commit
published. `--no-commit` drops the checkpoint, the attestation **and** the
publication, since with nothing committed the second has nothing to read and the
third nothing to publish.

**The second run is the short one, and the totals are read from the gate rather
than repeated here.** `run_pipeline.sh --help` prints how many checks the gate
declares for each phase and how many are deferred to the history, taken from the
gate's own per-group table at the moment it prints. This page used to write those
numbers down and they went stale; ask the tool:

```console
$ playthrough/tooling/run_pipeline.sh --help | grep -E 'checks before|history:'
```

The checks asked at both moments are the cheap ones it would be wrong to answer
once — the measuring environment, and the version-control facts that have to hold
before and after. No artifact is re-measured after a commit that did not touch
it, and the attestation on a published record takes seconds where a `post-commit`
that ran the whole audit took about ninety.

Three orderings are non-negotiable, and the sequencer checks them against the
plan it resolved rather than against the flags you typed: **`commit` requires
`verify` earlier in the same invocation**, **`attest` requires `commit`**, and
**`publish` requires `attest`**. Ask for any of them on its own and it refuses,
naming the invocation that would have worked. The last one is what closes the
sequence: the publication commits the report the attestation measured, so without
the attestation in the same invocation it would either find nothing to publish or
commit a report an earlier run left behind — a measurement of a different tree
under this one's name.

#### Three things are settled before stage 1 runs

Every stage above is expensive and an hour of encoding cannot be given back, so
three questions whose answers already exist are asked first. Each of them used
to be discovered after the expensive work.

**Would the checkpoint be taken at all?** The checkpoint this sequencer takes is
`media`, which commits a render — and a render is about a session whose save has
already been published, so it needs a `final` checkpoint for the survivor this
userdir has loaded, reached from that survivor's own `creation`. That is a fact
about the history before anything is rendered. When it fails, the checkpoint
refuses at stage 7, with the timeline, the transitions, the encode, the
transcripts, the caption mux and the whole functional gate already spent. The
sequencer asks `commit_artifacts.sh status`, which answers read-only with one
triple per checkpoint an automated caller takes — `FINAL_*` for the session's
save, `MEDIA_*` for the render — and refuses with **exit 4** before stage 1,
naming `--no-commit` as the way to run the render half deliberately:

```console
$ playthrough/tooling/run_pipeline.sh --from verify
PIPELINE_LIFECYCLE=no-creation-for-this-survivor
playthrough: FATAL: the 'media' checkpoint CANNOT be taken over this tree
(no-creation-for-this-survivor), and its reason is above.  [...] no stage is run
$ echo $?
4
```

**It reads the triple for the checkpoint it takes, and the key names are derived
from that checkpoint rather than written down.** Reading `FINAL_*` while taking
`media` would answer "eligible" for a session whose save had not been committed
yet, and then spend the whole render to be refused at stage 7 by the one
assertion the preflight had not asked about — which is the exact failure a
preflight exists to prevent.

The lifecycle rule itself stays in `commit_artifacts.sh`; the sequencer reads
three KEY=value lines and keeps no copy of it. An answer it cannot read is
reported (`PIPELINE_LIFECYCLE=unread`) and the run proceeds — silence is not
evidence of ineligibility, and the checkpoint stage remains the authority.

**Is there room?** Every artifact is full resolution and nothing is ever
dropped to make a generation fit, so running out of space part way through does
not produce a smaller film — it produces a torn one. The reserve is *measured*,
never predicted, and reported in full:

| Term | What it is | When it applies |
| --- | --- | --- |
| rewrite | the bytes the planned producing stages will write over, measured per stage from its own declared outputs | always |
| staging | one more copy of the film, which the caption mux writes beside it before relocating within it | only when `captions` is planned |
| history | the objects the checkpoint writes — an upper bound, since git writes an object only for what changed and these are already-compressed formats | only when `commit` is planned |
| margin | 256 MiB, because the engine's userdir, git's index and the encoder's temporary state all move during a run | always |

It is checked **before the first stage** and **again immediately before the
checkpoint**, because the producing stages spend the disk in between; the two
report under `PIPELINE_CAPACITY` and `PIPELINE_CAPACITY_CHECKPOINT` so neither
overwrites the other. Too little room is **exit 5**, refused before anything is
written, with every figure and the shortfall named. A measurement that cannot
be *taken* — no `df`, no `du`, an unreadable filesystem — is reported as
`unmeasured` and does **not** block the run: that is a fact about the host
rather than evidence the disk is full, and every stage checks its own
preconditions anyway.

One such reading, kept as a sample of the *shape* rather than as a standing
fact — the free figure is whatever the filesystem had at that moment, and it
moves constantly:

```text
playthrough: room to work: 25580575252480 byte(s) free (24395537 MiB) against a
276021248-byte reserve (263 MiB: 3833856 rewrite + 3751936 staging + 0 history +
268435456 margin)
```

`df -B1 /tmp` on **2026-08-10** reported 25 819 133 108 224 bytes free on the
same filesystem, so the sample above is a few hours older than this page; the
reserve is the part that is derived rather than sampled, and it is recomputed on
every run from the artifacts actually present.

**Is any of it already done?** A run receipt records, per producing stage, the
identity of the inputs it was made from and the digest of what it produced. A
stage is skipped only when **both** still hold:

```text
playthrough: stage 1/3 srt: ALREADY DONE -- this run's inputs are the ones it was
produced from and its output is unchanged, so it is skipped.  Pass --rebuild to
run it anyway.
PIPELINE_STAGE_SRT=fresh
PIPELINE_FRESH=srt
```

The receipt is **content-addressed and never time-stamped**. A modification
time can move without the content moving and stay still while the content
changes, so no mtime and no bare size appears in it. What does: the format
number, `HEAD`, a digest of git's own view of the *input* paths (`frames/`, the
record, the amendment ledger, the userdir — which covers the index and the
working tree together), the capture count, and the digests of the record, the
amendment ledger, the capture ledger, `requirements.txt`, the interpreter path,
the trust state and **every stage script**. Change any one of them and nothing
is fresh.

It lives at `${PLAYTHROUGH_RUN_DIR}/receipt-<checkout digest>` — inside the
mode-0700 runtime directory, **never in the working tree**, so it is not an
artifact and cannot be committed, and two clones cannot read each other's. The
name carries a digest of this checkout, the same scoping the lock uses.

What is never skipped: `verify`, `commit` and `attest`, because each asks about
a moment rather than producing a thing; the stage `--only` names, because an
operator asking for one stage means it; anything at all under `--rebuild`; and
every stage after the first one that does work, since its inputs have just
moved. That last rule is also what makes it sound to leave the *intermediate*
artifacts out of the fingerprint — the encoder reads the timeline and the
transition images, which are outputs of earlier stages, and folding them in
would mean nothing could ever be fresh after stage 1. Because freshness
collapses at the first stage that does anything, a chain of skips is a chain in
which nothing in the middle moved.

The outputs are hashed only *after* the input fingerprint has matched, so a
film is read to avoid re-encoding it and never the other way round.

#### The caption mux bounds itself by the film it is given

`embed_captions.sh` keeps `-c copy` and `+faststart` — the pixels are never
re-encoded and the moov atom is moved to the front so the film starts playing
before it has finished downloading — but that relocation rewrites the whole
container, so its cost is the film's size rather than a constant. A fixed
watchdog would therefore kill a legitimately long film as though it were stuck.
Three things replace it:

* **The ceiling is derived**, and the derivation is printed: a 300-second base,
  plus one second per mebibyte for each of the two passes (the stream copy and
  the relocation), plus one second per ten seconds of film. On this record that
  is `328s -- derived from 3749146 byte(s) over 2 pass(es) at 1048576 B/s plus
  219s of film at 1s per 10s, on a 300s base`.
  `PLAYTHROUGH_CAPTION_TIMEOUT` overrides it *exactly*, and the ceiling is
  enforced with `timeout --kill-after`, so a child that ignores `SIGTERM` does
  not outlive the ceiling it was given.
* **The watchdog is progress-aware.** It watches the staging file's size **and
  its modification time** — both, because `+faststart` rewrites in place and the
  size does not move while the largest piece of work happens — and only
  terminates when progress genuinely stalls. `PLAYTHROUGH_CAPTION_STALL` sets
  that stall window (120 seconds by default). The three outcomes are reported
  differently: finished, stalled, and expired at the ceiling.
* **Space is reserved before anything is written.** The mux stages its output
  beside the film and then relocates within it, so the reserve is the input
  film's bytes, plus any already-published captioned film it will replace, plus
  a 64 MiB margin — refused up front with every figure named. An unreadable
  `df` warns and proceeds.

### The gate on its own

```console
$ playthrough/tooling/verify_artifacts.sh                        # every check
$ playthrough/tooling/verify_artifacts.sh --phase pre-commit     # before a commit
$ playthrough/tooling/verify_artifacts.sh --phase post-commit    # about the history
$ playthrough/tooling/verify_artifacts.sh --samples all          # every capture's pixels
$ playthrough/tooling/verify_artifacts.sh --report-to /tmp/report.txt
```

**It writes nothing into the tree it measures**, and that is a property rather
than a habit: with no `--report-to` it reports to stdout and stderr and nowhere
else, and a destination *inside* the working tree is refused by name. Every
verdict prints what it **observed** beside what it expected, so a passing report
reads as evidence rather than as a tally.

All three counts are declared in the script and asserted against the verdicts
actually emitted, so no phase can return a short report unnoticed — each is
summed from its own per-group table
[playthrough/tooling/verify_artifacts.sh:777-832], with the group-by-group
derivation in the comment immediately above them. The numbers themselves are not
repeated on this page; `run_pipeline.sh --help` reads them out of that table at
the moment it prints.

`post-commit` is the **history** phase, not a second full audit: it asks the
questions only a commit can make true, plus the environment it measures them with
and the version-control facts that have to hold at both moments. The artifact
groups are absent because the commit did not touch the artifacts — `--phase all`
is how they are re-measured deliberately. On this record the three phases take
about **36 s**, **22 s** and **7 s**.

`--samples N` chooses how many captures have their **current** pixels decoded
for the luminance gate; the default is a bounded spread of 64 that always
includes the first and the last, and `--samples all` decodes every one. The
bounded default does not weaken the no-omission claim, because two
**whole-population** witnesses are unconditional and neither is a sample:
`capture.sh` recorded a non-blank reading for *every* frame at capture time and
the gate reads all of them back out of `build/observations.jsonl`, and the
digest sweep re-hashes *every* capture against the ledger. What the bounded
default gives up is only the re-decoding of a frame whose capture-time reading
and whose digest both already say it is not blank.

### The commit lifecycle

Six ordered checkpoints, each refusing to run out of turn:

```console
$ playthrough/tooling/commit_artifacts.sh integration # the rules, before any artifact
$ playthrough/tooling/commit_artifacts.sh dossier     # before the first frame
$ playthrough/tooling/commit_artifacts.sh creation    # after character creation
  # ... play the session ...
$ playthrough/tooling/commit_artifacts.sh final       # after the session ends
$ playthrough/tooling/commit_artifacts.sh media       # the film, transcripts, timeline
$ playthrough/tooling/commit_artifacts.sh attest      # the acceptance report + REPORT.md
$ playthrough/tooling/commit_artifacts.sh status      # read-only, takes no lock
```

**Why the last three are three and not one.** A single closing checkpoint used
to carry the record, the film and the reports, and it demanded
`playthrough/REPORT.md` before it would run — an unsatisfiable ordering, because
that report cites the commits carrying the film and the acceptance evidence, so
the document had to name commits that did not exist yet. Split, each commit is
about one thing and cites only what already precedes it: `final` closes the
session and needs no report at all; `media` commits what a render produced and
requires `final` to be in the history for this survivor; `attest` publishes the
acceptance report the gate wrote outside the tree, and is the only checkpoint
that requires `REPORT.md`. `run_pipeline.sh` takes `media` as its `commit` stage
and `attest` as its `publish` stage; the first four are taken by hand.

`integration` goes first because it commits the two rules everything after it
depends on — the terminal negation in `.gitignore` and the six attribute rows —
and a negation that was never committed loses the save data on the next clone.
It is the **only** checkpoint that stages a path outside `playthrough/`, it
stages exactly those two by name, and when HEAD already carries them as the
working tree has them it says so and commits nothing rather than manufacturing
an empty commit.

The dossier is committed **alone and first among the artifacts** because
"written before the first gameplay frame" is a statement about ancestry between
two commits, and one commit cannot precede itself — so `creation` refuses until
the dossier is tracked. `dossier` itself refuses once play has begun at all: a
capture on disk, a tracked capture, a manifest row, an observation or a frame
digest is each enough to stop it, so the claim cannot be made retroactively by
committing the dossier late. `final` anchors to the `creation` checkpoint of
**the same survivor** and refuses across a survivor change, which a row count
cannot detect, since a record re-recorded from scratch has "grown" too. The
dossier-precedes-captures ordering is read from the commit that introduced the
bytes **now at HEAD**, not from the oldest commit that ever touched those
paths, so a retired generation's history cannot satisfy it for a later one.

**Staging is an allowlist, and that inversion is load-bearing.** Every path
under `playthrough/` is enumerated and classified before anything is staged, and
a path that belongs to no class is a **refusal** rather than an admission:
authored tooling by exact filename, the engine's own userdir by POSITION in its
tree (so a new file shape a future engine writes is still recorded, while a
stray one beside them is not), and every generated artifact against its declared
schema — `frames/frame_NNNNN.png`, `build/transitions/trans_NNNNN_NN.png`, the
named build intermediates, the film, the transcripts, the record.

Three of the classes used to be whole directories: `git add --
playthrough/tooling`, `-- playthrough/userdir` and `-- playthrough/build` staged
whatever those trees happened to contain, and the only thing between an accident
and a commit was a **denylist** of the shapes somebody had already been bitten
by — bytecode, an ad-hoc test file, a quarantined film, the X authority cookie, a
pid. A denylist answers "is this one of the bad things I know about"; a
checkpoint has to answer "is this evidence". The terminal `!/playthrough/**`
negation makes that worse rather than better, because "it would have been
ignored" is not a fallback that exists inside this tree.

A path git **ignores** is refused too, and for a reason that only appears once
paths are named explicitly: a directory pathspec skips an ignored file in
silence, while an explicit one is a hard error — so the ignore sweep runs ahead
of any `git add`, and the operator gets the precise diagnosis rather than git's.

Beyond that: never a blanket `add`, never `-A`, never `-f`, never a shell glob;
every checkpoint reads its own staged set back and refuses on anything outside
its declared scope, comparing NUL-delimited pathnames end to end so that a
pathname containing a newline cannot slip through the refusal. All carry a
`Playthrough-Checkpoint: <name>` trailer, which is the lifecycle's entire
persistent state. There is no side file to fall out of step with the history.

`.gitignore` and `.gitattributes` are **checked** at every checkpoint and
**committed** by `integration`: the terminal negation is verified both in the
working tree and as HEAD carries it, because a negation that was never committed
loses the save data on the next clone.

`status` also answers, read-only and without taking the lock, whether the two
checkpoints an automated caller takes *would* be taken. There is one triple per
checkpoint, because they assert different things and a caller must read the one
for the checkpoint it takes:

* **`FINAL_ELIGIBLE` / `FINAL_ANCHOR` / `FINAL_REASON`** — whether the session's
  save could be committed. The anchor is the `creation` checkpoint `final` would
  anchor to, which may be an older commit than the newest one; the reason is one
  stable token (`no-survivor-loaded`, `no-record`, `no-creation-checkpoint`,
  `no-creation-for-this-survivor`, `anchor-carries-no-record`,
  `record-has-not-grown`).
* **`MEDIA_ELIGIBLE` / `MEDIA_ANCHOR` / `MEDIA_REASON`** — whether the render
  could be committed, which additionally requires a `final` for **this** survivor
  to be in the history. The anchor is that `final` commit; the reason is
  `no-final-published`, or whichever `FINAL_REASON` token explains why no anchor
  could be resolved at all.

Both are computed with the same predicates the refusals enforce, so the report
cannot drift from what it predicts. `run_pipeline.sh` reads the `MEDIA_*` triple
before its first stage, because `media` is the checkpoint it takes.

How the staging scales matters on a long session, because the captures are the
one class whose size is the session's length:

* the paths are **streamed** as NUL-delimited records into a pathspec file in
  the runtime directory — never accumulated in a shell array, so a hundred
  thousand captures cost a hundred thousand `[ -e ]` tests and no memory;
* each class is then staged with **one** `git add --pathspec-from-file=<file>
  --pathspec-file-nul`, which is one index read and one index write however long
  the session was. Batching argv worked, but it paid a full index rewrite per
  batch, and the index is the size of the repository rather than the size of the
  batch;
* on git older than 2.25, which has no `--pathspec-from-file`, the same file is
  replayed in `STAGE_BATCH_SIZE` chunks through a bounded argument list. The
  capability is *probed* (an empty pathspec list, which a capable git accepts and
  an older one refuses with "unknown option") rather than inferred from a version
  string;
* a path that is neither on disk nor tracked is filtered out first, because a
  pathspec matching nothing is a fatal `git add` error — and an optional
  artifact nobody has written yet must not fell a checkpoint;
* the booleans are git's own exit statuses (`git diff --cached --quiet`, and one
  line of `git add --dry-run`), not captured lists measured for emptiness;
* every human-facing list is **bounded and honest about it**: `status` prints the
  exact total and at most twenty lines ("would stage 12,043 path(s); the first
  20 are:"), and a refusal names at most eight paths followed by "(and N more)"
  — a sample is never presented as the whole.

`.gitignore` and `.gitattributes` are **checked** here and committed elsewhere:
the terminal negation is verified both in the working tree and as HEAD carries
it, because a negation that was never committed loses the save data on the next
clone.

**The committer reports the identity and never writes it.** It resolves the
identity git will actually use — `git var GIT_AUTHOR_IDENT`, the value a commit
would carry — and says which scope it came from. A repository-local pair that
**equals** that identity is confirmed and left untouched; one that **disagrees**
is a **refusal**, because a local pair contradicting the committer is a
repository configured to attribute the next commit to somebody else, and the
tool's job is to say so rather than to overwrite it. It writes no git
configuration in any scope, invents no identity — a missing one is a refusal —
never rewrites history and never pushes.

It used to persist the identity with `git config --local` before every
checkpoint. That was removed: the value it wrote was whatever the **host** had
already resolved, so it bought persistence rather than correctness, and the
acceptance gate then read it back and reported it as a property of the
repository. Where a container needs the host's identity — it mounts the checkout,
sets its own `HOME` and forwards no `GIT_*` — `supported_env.sh` forwards
`GIT_AUTHOR_*` and `GIT_COMMITTER_*` into the environment instead, and forwards
nothing when git cannot answer.

**What this branch carries, and the divergence from R1's wording.** There is no
repository-local pair here — `git config --local user.email` exits non-zero — and
the identity resolves from the host's configuration, which is why every commit is
authored and committed as `Blitzy Agent <agent@blitzy.com>`
(`git log -1 --format='%an <%ae> %cn <%ce>'`). The execution environment forbids
running `git config user.name` or `git config user.email` at all, so the
repository-local pair the AAP describes (§0.3.1, §0.10.2) cannot be written by
these passes. The gate therefore asserts the property that is both checkable and
load-bearing: an identity RESOLVES, and it AGREES with the newest commit touching
`playthrough/`. The requirement's substance — commits that carry a real,
attributable identity — holds; its mechanism does not.

**And the gate says so in its verdict, not only in its prose.** This check used
to report `PASS` with the explanation attached — a truthful sentence under an
untruthful verdict, which told any script reading the verdict that this element of
R1 was met. It is now a third verdict class: `DIVERGENCE`, which prints what the
plan requires, what was delivered instead and why it stands. A divergence counts
toward the declared check inventory, so it cannot be lost by reclassification; it
leaves the exit status alone, because failing the run for a permanent
environment-imposed divergence would block every future checkpoint for good; and
it changes the closing verdict to `VERIFY=pass-with-divergence` and the summary
sentence to one that explicitly does not claim full compliance. `attest` publishes
that verdict — `pass-with-divergence` is on its allow-list beside `pass`
deliberately, because if only `pass` were publishable the honest report could
never be committed and the dishonest one would be mandatory. `fail` is still
unpublishable. The divergence is set out in `TECHNICAL_NOTES.md` under *Closed:
the identity is asserted to RESOLVE and to match the history*.

### The knobs, and what each one is for

Every one of these has a working default, and every one that takes a number is
validated before it reaches any arithmetic — a value that is *set but
unreadable* is refused rather than quietly defaulted, because defaulting it
hides an operator's mistake behind a run that looks fine.

| Variable | Default | What it changes |
| --- | --- | --- |
| `PLAYTHROUGH_CAPTURE_RESERVE` | derived: previous capture × 64 + 16 MiB | the free space `session.py step` insists on before sending a key. No value switches the check off. |
| `PLAYTHROUGH_CAPTION_TIMEOUT` | derived from the film's size and duration | the ceiling on the caption mux, honoured exactly when set |
| `PLAYTHROUGH_CAPTION_STALL` | 120 s | how long the caption mux may make no progress before it is stopped |
| `PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT` | 60 s | how long the sequencer waits for another run over **this** checkout |
| `PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT` | 120 s | the same, for a checkpoint |
| `PLAYTHROUGH_RUNTIME_DIR` | `${XDG_RUNTIME_DIR}/playthrough` | where the locks, logs and the run receipt live. Whatever is nominated goes through the same 0700-and-not-a-symlink verification as the default. |
| `CLONE_INDEX` | 0 | shifts the display and the runtime directory so parallel clones do not collide |
| `PLAYTHROUGH_ALLOW_EOL_PLATFORM` | unset | a **registered trust bypass**, not a "make it work" flag (section 4) |

And two command-line switches worth knowing for the same reason:
`verify_artifacts.sh --samples all` decodes every capture's pixels rather than
the bounded default spread, and `run_pipeline.sh --rebuild` ignores the run
receipt and re-runs every planned stage.

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
288.5 12.0 300.5 300.5
$ grep -E -- '-->' playthrough/transcript.srt | tail -1
00:05:00,250 --> 00:05:00,500
```

288.5 + 12.0 = 300.5, and the last cue closes at 300.500 s. The ceiling engaged
twelve times — at frames 170, 279, 283, 284, 285, 286, 296, 298, 299, 303, 304
and 305, whose raw deltas of 172, 337, 2167, 830, 2401, 36 869, 313, 7200,
7458, 1542, 3000 and 9858 seconds were each held at 10.0 s — which is why there
are twelve transition groups of twelve pictures, 144 images altogether. The
largest, 36 869 s at frame 286, is the ten-and-a-quarter-hour wait the survivor
sat out indoors before dark; the 7200 s and 7458 s pair at frames 298 and 299
are the night itself, slept in two attempts.

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
never invented. On the shipped record that is **145 exact readings and 160
unreadable**, and each of the 160 says so in the telemetry — `clock_status`
reads `unreadable` on those rows — rather than carrying a guess.

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
with `clock_rect_from = computed`, for all 307 captures.

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
one-liner, and the difference is measurable rather than stylistic.** Run against
this session's own captures, the module returns the reading the record holds:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/ocr_clock.py \
      playthrough/frames/frame_00164.png
08:00:00
```

The one-liner, on the same four captures, returns something that **matches the
regex and is wrong**:

| Capture | The one-liner | `ocr_clock.py`, and the record |
| --- | --- | --- |
| `frame_00164.png` | `48:40:48` | `08:00:00` |
| `frame_00200.png` | `48:43:18` | `08:03:18` |
| `frame_00267.png` | `48:84:14` | `08:04:14` |
| `frame_00306.png` | `84:04:18` | `04:04:18` |

This is the failure mode worth naming, because it is worse than returning
nothing: `48:40:48` is a well-formed `HH:MM:SS` that `grep -Eo` accepts, so a
pipeline built on the one-liner would not fail — it would record a fabricated
time and carry it into every duration derived from it. The module measures which
vertical phase the engine's cell grid is really drawn on instead of trusting the
computed offset, which is the drift the readings above are made of. Use the
module. It is also allowed to fail: it returns a clock string or nothing, and
never a guess.

---

## 8. Repository integration — the only two pre-existing files that change

```console
$ git diff --name-status f38c2fbae3..HEAD -- . ':(exclude)playthrough'
M       .gitattributes
M       .gitignore
$ git diff --shortstat f38c2fbae3..HEAD -- .gitignore .gitattributes
 2 files changed, 44 insertions(+)
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
    'playthrough/userdir/save/Fairport Harbor/#T2RldHRlIFZhY2hvbg==.sav'
.gitignore:275:!/playthrough/**  playthrough/userdir/save/Fairport Harbor/#T2Rl….sav
```

That is the survivor's own character file, and its name begins with `#` because
CDDA base64-encodes the character name — so this is exactly the path `\#*` would
have swallowed, and the negation is the only reason it is tracked.

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

### `.gitattributes` — six type rows and one waiver

```console
$ git diff f38c2fbae3..HEAD -- .gitattributes | grep '^+[^+#]'
+*.jsonl   text
+*.srt     text
+*.gsav    binary
+*.mp4     binary
+*.sav     binary
+*.zzip    binary
+playthrough/userdir/** -whitespace
```

`*.jsonl` and `*.srt` join the text block [.gitattributes:7-19]; `*.gsav`,
`*.mp4`, `*.sav` and `*.zzip` join the binary block [.gitattributes:33-44].
`*.png` was already there [.gitattributes:39], which covers the frames, and
`*.md`, `*.txt` and `*.json` already covered the narrative and data artifacts.
The file's own stated rationale is to normalise explicitly rather than rely on
detection [.gitattributes:5-6], so extending it for new artifact types is the
treatment it prescribes for itself.

**The seventh row is a whitespace waiver, and it is deliberately narrow.**
Everything under `playthrough/userdir/` is written by the **engine** and is
committed byte for byte because it is what the session produced. Two of those
files end with a blank line — the debug log, and the survivor's memorial diary —
so `git diff --check` reports `new blank line at EOF` against them. The bytes are
evidence: a memorial rewritten to please a whitespace linter is no longer the
memorial the game wrote. `-whitespace` suppresses the report while changing
nothing, and it leaves the `text`/eol handling above in force.

Its scope is the engine's tree **alone** — every authored file here, the tooling,
the transcripts and the reports, is still checked — and because git applies the
**last** matching pattern, a directory-scoped row placed after the suffix rows is
exactly the shape that could silently override them. So the committer asks git
rather than reading the file: it holds one witness path per row through
`git check-attr`, including one on each side of this waiver's boundary, and it
asks the same of HEAD's own copy of the rules. `git diff --check` over
`playthrough/` is clean, with no engine byte edited.

### What does not change

Nothing else. No tracked file under `src/`, `tests/`, `data/` or `gfx/`; not
`Makefile`, `CMakeLists.txt`, `CMakePresets.json`, `.flake8`, `pyproject.toml`,
`.astylerc`, or anything under `.github/`; and **not the root `README.md`**.
`gfx/` gets the untracked tileset installed into it at provisioning time
(section 4), which is host state and never enters the index — the gate's own
change-surface check below is what proves the distinction rather than this
sentence.

In particular the one C++ edit the specification anticipated — the SDL2
`get_shared_variant_pass` guard in the pixel minimap — is **already applied at
both construction sites** [src/pixel_minimap.cpp:283-287,
src/pixel_minimap.cpp:475-479], so no engine change is required and none was
made. The acceptance gate checks the whole surface rather than trusting this
paragraph:

```text
PASS  the change surface is only the two ignore files and playthrough/
      observed: 513 changed path(s) since f38c2fbae3, all of them under
      playthrough/ or one of: .gitignore .gitattributes
```

The path count grows whenever a file is added under this tree — it was 513 when
this line was written — but the property the verdict is about does not: every
changed path is either under `playthrough/` or one of those two files.

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
$ ls 'playthrough/userdir/save/Fairport Harbor/' | grep -E '^#.*\.sav$'
#T2RldHRlIFZhY2hvbg==.sav
```

The same option is why the overmaps were written as plain `o.0.0` … `o.2.2`
files and the map data as a `maps/` **directory**, rather than `maps.zzip` and
`overmaps/*.zzip`. Both layouts are legitimate; this session took the
uncompressed one.

Those world files are in the working tree and tracked, because this session
ended through Save & Quit rather than in death: ten overmap segments, 95 map
chunks, `master.gsav`, `dimension_data.gsav`, `uistate.json`, `zones.json` and
the character's own files, 134 tracked paths in all. `git ls-files
'playthrough/userdir/save/Fairport Harbor/'` is the way to look at them, and
`git ls-tree -r 800ab8e11f -- 'playthrough/userdir/save/'` shows the same world
as it stood at the `creation` checkpoint, before the day was played.

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

**Two legs get new inputs to act on. Rather more than two still run.** Those
are different claims and an earlier version of this section made the wrong one,
so both are stated. The only new *eligible input* this feature creates is
Python, so `flake8.yml` — filtered to `**.py`
[.github/workflows/flake8.yml:7-13] — and the `python` leg of
`codeql-analysis.yml` [.github/workflows/codeql-analysis.yml:35] are the two
gates with something of this feature's to examine, and both are satisfied by
construction rather than by exemption.

But **a workflow that declares no `paths:` filter matches every change**, which
is GitHub's rule and not a detail. Classified mechanically over all 35 files,
**twelve** workflows trigger on a push or pull request and declare no path
filter whatsoever, so they run on any commit here, prose included:
`astyle.yml` and `json.yml` (both bare `on: pull_request`), `clang-tidy.yml`,
`codeql-analysis.yml`, `iwyu.yml`, `matrix.yml`, `CBA.yml`, `pr-validator.yml`,
and the four `pull_request_target` housekeepers `check-branch-name.yml`,
`labeler.yml`, `label-first-time-contributor.yml` and `request-review.yml`. A
thirteenth, `msvc-full-features.yml`, filters by `paths-ignore`, and that list
— `android/`, `build-data/osx/`, `doc/`, `doxygen_doc/`, `gfx/`, `lang/`,
`lgtm/`, `tools/` except `tools/format/`, `utilities/` — never mentions
`playthrough/`, `.gitignore` or `.gitattributes`, so it matches too. Those
workflows **run**, and then, with no C++, JSON or CMake change to act on, they
pass: "receives nothing it can act on" is true of the *work*, not of the
trigger. What genuinely does not start is the path-filtered set —
`linter.yml`, `cmake-format.yml`, `toc.yml`, `text-changes-analyzer.yml`,
`release.yml`, `weekly-changelog.yml`, `format_emscripten.yml`,
`detect-translation-file-changes.yml` and
`assign_mission_target_needs_om_special.yml` — each filtering on paths this
feature never touches.

The consequence for prose specifically: **no workflow filters *for* Markdown**,
so nothing is triggered *by* a `.md` file, and there is no `markdownlint`, `mdl`
or `remark-lint` anywhere in the tree — but a documentation-only commit pushed
to `master` still starts the filterless workflows above, so "no gate reads this
page" is the accurate claim rather than "nothing runs". The spell check in
particular runs from `text-changes-analyzer.yml`, whose filters are the workflow
itself, `tools/pot_diff.py`, `lang/extract_json_strings.py`,
`lang/string_extractor/**`, `src/*.h`, `src/*.cpp` and `**.json`
[.github/workflows/text-changes-analyzer.yml:4-16], so it never sees prose here
and the dictionary at `tools/spell_checker/dictionary.txt` — which carries
`playthroughs` at line 5351, the plural only — is not consulted either way. This
page's correctness therefore rests on the commands written beside its numbers,
which is why they are written down. Measured across all **35** workflow files in
`.github/workflows/` at `5f902536e8`.

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
one suite per script, `test_artifacts.py` over the artifact set and
`test_readme.py` over this page's own commands, 21 in all,
run against the real scripts rather than against restatements of them, and
writing only inside their own sandboxes. It takes about twenty-two minutes. Run
here on **2026-08-10**, on a host with the tileset installed:

```console
$ . playthrough/tooling/env.sh
$ "$PLAYTHROUGH_PYTHON" -B -m unittest discover \
      -s playthrough/tooling -p 'test_*.py'
[...]
Ran 3017 tests in 1427.759s

OK (skipped=1)
```

**One skip, and it is named rather than smoothed.** It is
`test_tileset_provenance.EveryFailureToReadIsARefusal.test_an_unreadable_file_is_refused`,
whose own message says why: *running as a user that ignores file modes*. A test
that removes read permission and expects a refusal cannot assert anything as
root, so it declines instead of passing vacuously.

The suite that measures this host's artwork rather than the record —
`test_tileset_provenance`, over the pack installed at `gfx/MShockXotto+` — passes
here because the pack and the tracked anchor describe the same 22 files
(`TILESET_PROVENANCE=verified`, tree digest `7d853c21de2e…`). `gfx/` is untracked
[.gitignore:52], so `tooling/tileset_provenance.json` is the **only tracked
statement of what the film's pixels are**, and it is what `launch_game.sh
tileset`, the acceptance gate and that suite all reach their verdict through
rather than each re-implementing the walk. On a host whose pack differs from the
anchor the suite refuses and names the files, which is the point of it; the
account of one such divergence, and of what it took to close it honestly, is in
*The provenance anchor is refusing a re-composition, not the film's artwork* in
`TECHNICAL_NOTES.md`. The deterministic core can be run on its own in seconds:

```console
$ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/test_timeline.py
[...]
Ran 374 tests in 2.370s

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

`tooling/verify_artifacts.sh` is the executable form of all of it. A run that
passes ends like this — the shape, not a transcript of the current tree:

```console
$ playthrough/tooling/verify_artifacts.sh
[...]
SUMMARY  <declared> of <declared> checks passed (<declared> declared for the
'all' phase), N informational note(s); the committed artifacts are what they
claim to be.
VERIFY_CAPTURES=<captures>
VERIFY_ROWS=<the same number>
VERIFY_TIMELINE_TOTAL=<seconds>
VERIFY_TRANSITIONS=<transition groups>
VERIFY_MEASURED_COMMIT=HEAD <short hash>
VERIFY=pass
```

**The totals are the gate's own declaration and are not written down here.**
It declares a per-group table and sums it, and `run_pipeline.sh --help` READS
that table at the moment it prints. This page used to quote the numbers instead
— they said `117` while the gate declared `120` — so the one place to ask is the
gate:

```console
$ playthrough/tooling/run_pipeline.sh --help | grep -E 'checks before|history:'
```

**The gate writes nothing into the tree it measures.** By default it reports to
stdout and stderr and no further; `--report-to PATH` names a destination, and a
path inside the working tree is **refused**, in its own words: a report written
there would dirty a file the run had just certified as committed. It used to
publish `playthrough/acceptance-report.txt` itself on a passing run and delete
it on a failing one — so a full-phase run taken after the final commit left the
tree dirty in the one file it had just certified, and a run over a
work-in-progress checkout removed the committed receipt. Publication now belongs
to the `attest` checkpoint, which reads the report at the scratch path and
refuses one that failed, one produced by a phase that measured no history, or one
naming a commit other than `HEAD`.

**`VERIFY_MEASURED_COMMIT` is what makes the report about a tree.** It reads
`HEAD <short hash>` over a clean tree and `HEAD <short hash> plus N uncommitted
path(s) under playthrough` otherwise, so a measurement taken mid-edit says so and
the publication step refuses it automatically.

**Two conditions fail by design on a checkout whose session is still being
worked on**, and both are facts about the checkout rather than defects in the
gate: "nothing under `playthrough/` is left uncommitted", for the ordinary
reason, and the ending and history checks, until a recording has been committed.
The identity check is not one of them any more — it asks whether an identity
RESOLVES and whether it AGREES with the newest commit touching `playthrough/`,
both of which hold here, and reports the fact that the pair is not
repository-local as a `DIVERGENCE` rather than as either a pass or a failure.

**One check is about the defences rather than the artifacts.** `check_security
_controls` inventories every security control this tooling relies on — the
credential containment gate, the hook-void on mutating git commands, the
commit-tree binding, staging provenance and the secret scan, the path-ancestry
trust walk, the writable-path refusal, the environment sanitiser, the mutation
lock, the X process-identity record and cookie rotation, the record-token grammar
and control escaping, the hash-chained evidence ledgers, the journal durability
propagation, the decode provenance and resource limits, the survivor-name grammar
and the container image identity — by asserting each is still present in the file
that implements it, and prints their names into the report. It exists because a
review found the report *omitting* them: a count reads the same whether or not
anything was defending it, so a removed control would otherwise vanish from the
evidence silently instead of failing a check.

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

* **No change to game behaviour, balance, content or presentation.** No
  tracked file under `src/`, `tests/`, `data/` or `gfx/` is modified, and
  neither is any build or CI file (section 8). The one exception is untracked
  and deliberate: the required tileset is installed into `gfx/MShockXotto+`,
  which `.gitignore:52` excludes, so no tracked `gfx/` source changes and the
  artwork never enters the index.
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

* `REPORT.md` — the deliverable report the specification asks for, in exactly
  three sections and no more: the recording and animation with its evidence,
  the character, and the session as the frames record it. It is also where any
  requirement this record does not fully meet is stated in full, in the section
  it belongs to.
* `TECHNICAL_NOTES.md` — the engineering log: every measurement with the
  command that produced it, every pitfall, and every place a plan figure did
  not reproduce. Start at its own front matter, which maps the page and says
  which capture set each block describes.
* `dossier.md` — the survivor, in her own words, written before the first
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
over the repository** (no history rewriting, no force-push, no global
configuration written, and the committer confined to a repository-local
identity when it writes one at all — section 5, which also records what this
branch's commits actually resolved their identity from).
