# playthrough/ — the capture and cinematography subsystem

One survivor, one continuous session, one screenshot per keystroke, and a film
whose pacing is the in-game clock rather than a frame rate.

Everything in this directory is either **evidence** (the captures, the record,
the save the engine wrote, the films, the transcript) or the **tooling** that
produced it. Nothing here changes the game: the engine is started, keyed and
photographed through interfaces it already had, and no file under `src/`,
`tests/` or `data/` is touched by any of it.

This page is the operator-facing one. `TECHNICAL_NOTES.md` is the
engineer-facing counterpart and holds the measurements, the pitfalls and the
divergences; `transcript.md` and `dossier.md` are the survivor's own voice and
deliberately contain none of that.

---

## What is here

| Path | What it is |
| --- | --- |
| `dossier.md` | The survivor's first-person backstory, written and committed **before** the first gameplay frame |
| `frames/frame_NNNNN.png` | Exactly one 1920×1080 capture per keystroke — 326 of them, none decimated, sampled or deduplicated |
| `manifest.jsonl` | One row per capture: `frame`, `file`, `real_ts`, `ingame_clock`, `action`, `commentary` |
| `amendments.jsonl` | Corrections to the record, appended rather than applied in place, so the original reading survives |
| `timeline.json` | The computed durations and transition flags — **the single source of truth** for both the film and the captions |
| `cata-play.mp4` | The film: h264, 1920×1080, no audio stream |
| `cata-play-cc.mp4` | The same film with a selectable `mov_text` caption track tagged `language=eng` |
| `transcript.md` | The timestamped, in-character record |
| `transcript.srt` | The same cues as a subtitle file |
| `build/` | Intermediates: the concat list, the materialised transition frames, the attestation ledger |
| `userdir/` | The engine's own tree — the save, the world, the configuration. Written by the game, committed here, never hand-edited |
| `tooling/` | The pipeline, its environment definition, and sixteen-plus regression suites |
| `TECHNICAL_NOTES.md` | Engineering and meta observations, kept out of the in-character record |

Two facts about this set are worth stating because they are easy to lose:

* **The frames directory holds exactly one PNG per keystroke.** Derived imagery
  — the transition frames — goes to `build/transitions/`, never here, because
  the frame count equalling the record's row count is an acceptance check and
  mixing derived images in would destroy it.
* **Everything is committed**, including every frame and both films. When
  repository size and completeness conflict, completeness wins.

---

## How the pacing works

Each frame is on screen for as long as the action took **in game**. The
duration is the difference between consecutive sidebar clock readings, not a
modelled turn count, with two bounds:

* a floor of **0.25 s**, because menu navigation and character creation consume
  no game time and those frames are kept rather than dropped or merged;
* a ceiling of **10 s**, and where the raw delta exceeded it a fade-out, a
  "…time passes…" card in the game's own Terminus face and a fade-in are
  inserted — sleeping through the night is the archetypal case.

For this session that comes to a declared total of **219.5 s** across 326
captures with one transition. The inserted seconds are charged to the caption
cursor as well as the film, which is why the cue file and the container agree;
they are generated from the same `timeline.json` in one pass, so they cannot
drift apart.

---

## Re-running the pipeline

The post-session stages are sequenced by `tooling/run_pipeline.sh`. Run it from
the repository root.

```console
$ playthrough/tooling/run_pipeline.sh --help          # the full contract
$ playthrough/tooling/run_pipeline.sh --no-commit     # rebuild and gate, commit nothing
$ playthrough/tooling/run_pipeline.sh --from render   # retry a late stage
$ playthrough/tooling/run_pipeline.sh --only srt       # one stage
```

The stages, in the only order they can run in:

| # | Stage | Runs |
| --- | --- | --- |
| 1 | `timeline` | `timeline.py` → `timeline.json` |
| 2 | `transitions` | `make_transitions.py` → `build/transitions/*.png` |
| 3 | `render` | `render_movie.py` → `cata-play.mp4` |
| 4 | `srt` | `make_srt.py` → `transcript.srt` + `transcript.md` |
| 5 | `captions` | `embed_captions.sh` → `cata-play-cc.mp4` |
| 6 | `verify` | `verify_artifacts.sh --phase pre-commit` |
| 7 | `commit` | `commit_artifacts.sh final` |
| 8 | `attest` | `verify_artifacts.sh --phase post-commit` |

**The gate runs twice, and that is deliberate.** Most of its checks are about
the artifacts and can be answered the moment a render finishes. Twelve are about
the history — is the save tracked, is every artifact class committed, is the tree
clean, do the checkpoint trailers name one survivor — and a commit is what makes
those true. So the functional half guards the commit and the history half reports
what the commit published. `--no-commit` drops the checkpoint **and** the
attestation, since with nothing committed the second has nothing to read.

Two rules the sequencer enforces on its own behalf: `commit` will not run unless
`verify` runs ahead of it in the same invocation, and `attest` will not run
without `commit`. Asking for either alone is refused.

The stages are individually runnable too — the sequencer holds none of their
logic, only their order.

---

## Re-running the gate on its own

```console
$ playthrough/tooling/verify_artifacts.sh                      # all 111 checks
$ playthrough/tooling/verify_artifacts.sh --phase pre-commit    # the 99 functional ones
$ playthrough/tooling/verify_artifacts.sh --phase post-commit   # all 111, after a commit
```

It writes nothing. Every verdict prints what it **observed** beside what it
expected, so a passing report is readable as evidence rather than as a tally.
Two of its checks exist specifically to catch failures that are otherwise
silent: a grayscale luminance assertion (`mean > 0` **and** `std > 0`) on
sampled frames and on frames pulled back out of the finished film, which is what
turns a regression to `SDL_VIDEODRIVER=dummy` from an invisible black movie into
a hard failure; and a `git check-ignore` reading of the save and the captures,
because `git add` skips an ignored path and exits 0.

---

## The commit lifecycle

Three ordered checkpoints, each refusing to run out of turn:

```console
$ playthrough/tooling/commit_artifacts.sh dossier    # before the first frame
$ playthrough/tooling/commit_artifacts.sh creation   # after character creation
  # ... play the session ...
$ playthrough/tooling/commit_artifacts.sh final      # after the in-game Save and Quit
$ playthrough/tooling/commit_artifacts.sh status     # read-only, takes no lock
```

The dossier is committed **alone and first** because "written before the first
gameplay frame" is a statement about ancestry between two commits, and one commit
cannot precede itself — so `creation` refuses until the dossier is tracked.
`final` anchors to the `creation` checkpoint of **the same survivor**; a row
count cannot tell two survivors apart, since a record re-recorded from scratch
has "grown" too.

Each checkpoint stages `playthrough/` by artifact class in bounded batches —
never a blanket `add`, never `-A`, never `-f`, never a shell glob — and carries a
`Playthrough-Checkpoint: <name>` trailer, which is the lifecycle's entire
persistent state. There is no side file to fall out of step with the history.

`.gitignore` and `.gitattributes` are **checked** here and committed elsewhere:
the terminal `!/playthrough/**` negation is what stops git silently skipping the
engine's own `#<name>.sav` and `*.log` files, and it is verified both in the
working tree and as HEAD carries it, because a negation that was never committed
loses the save data on the next clone.

The committer records the identity git already resolved into **this
repository's** configuration (`git config --local`, never `--global`, never
`--system`, never overwriting a pair the repository already carries). That is not
tidiness: the container below mounts the checkout, sets its own `HOME` and
forwards no `GIT_*`, so an identity living only in a home directory does not
exist in there. It never invents one — a missing identity is a refusal.

---

## The environment contract

Every stage sources `tooling/env.sh`, which is the single definition of the
headless contract and the artifact layout. Nothing redefines either.

```
DISPLAY=:99                    SDL_VIDEODRIVER=x11     (never dummy)
SDL_AUDIODRIVER=dummy          LIBGL_ALWAYS_SOFTWARE=1
XDG_RUNTIME_DIR=/tmp/xdg       (mode 0700)
```

`SDL_VIDEODRIVER=dummy` is banned everywhere, including as any script's default,
because it renders zero pixels: the game runs, the captures succeed, the encode
succeeds, every count tallies, and the only symptom is that nothing is visible.

Capture targets the **X root window**, not the game window: the window is
1920×1072 inside a 1920×1080 root, so photographing the root gives a
true-resolution frame with a four-pixel letterbox and needs no rescale that
would soften the text the clock reader depends on.

### The declared production environment

`tooling/environment/Dockerfile` defines a complete, capture-capable image on a
Linux release that is **in support**, and `tooling/supported_env.sh` drives it:

```console
$ playthrough/tooling/supported_env.sh build        # build the image
$ playthrough/tooling/supported_env.sh inventory    # what it actually contains
$ playthrough/tooling/supported_env.sh preflight    # prove the path end to end
$ playthrough/tooling/supported_env.sh run playthrough/tooling/run_pipeline.sh --no-commit
$ playthrough/tooling/supported_env.sh shell        # a shell inside it
```

This exists because `env.sh` refuses to record a session on an end-of-life
release — ImageMagick, ffmpeg and the Xorg stack all parse untrusted-shaped
input, and an out-of-support archive publishes no fixes for them. The escape
hatch, `PLAYTHROUGH_ALLOW_EOL_PLATFORM`, is a registered trust bypass that moves
the trust state to `diagnostic`, and under `diagnostic` the capture and render
stages refuse on their own account. The container is the supported path rather
than a way around the refusal, and the driver will not forward a trust bypass
into it.

The image carries its own inventory, measured at build time rather than claimed,
so what a given build contains is a fact it holds.

### Python

The interpreter is CPython **3.12**, holding exactly the closure in
`tooling/requirements.lock`, installed with `--require-hashes` and
`--only-binary :all:`. `tooling/requirements.txt` is the readable declaration —
`moviepy`, `pillow`, `pytesseract`, `numpy`, `imageio`, plus `imageio-ffmpeg` as
the encoder bridge, with a comment saying exactly why a sixth package the
requirement did not name appears in it. The pins are exact because this pipeline
produces a byte-level media artifact *and its own acceptance evidence*: a
floating lower bound would let a future release silently change the film while
every gate still reported green.

Regenerating the artifacts inside the container reproduces the committed films,
timeline, transcript and cue file **byte for byte**.

---

## The tests

Standard-library `unittest`, no new framework, discovered from this directory:

```console
$ python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'
```

Each script has its own suite; the ones covering the post-session tooling are
`test_run_pipeline.py`, `test_verify_artifacts.py`, `test_commit_artifacts.py`
and `test_artifacts.py`. They run against the real scripts rather than
restatements of them, and they write only inside their own sandboxes.

The new Python satisfies the repository's existing lint contract — `flake8` under
the repository's own `.flake8` at 79 columns — rather than being added to its
exclude list. The gate checks that too, and the check is not skippable: a gate
that passed quietly when its linter was missing would certify unlinted code as
linted.

---

## What this subsystem will not do

No debug menu, no debug mode, no spawning, no stat editing, no teleport, no god
mode, no map reveal — for any reason, including avoiding death. Those actions
ship unbound, they were never bound, and because the engine only writes
`userdir/config/keybindings.json` when a binding is changed, that file's absence
from a committed tree is itself the evidence. The gate asserts it.

Nothing here is fabricated. Every clock reading, caption and screenshot
corresponds to a frame that was actually captured. OCR is an assist; the reading
of the frame is authoritative; an unreadable value is recorded as unreadable and
reconciled against the previous frame rather than guessed, and the record says
which readings those were.
