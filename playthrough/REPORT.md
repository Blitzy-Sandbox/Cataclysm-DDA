# Playthrough report

Three sections, in the order the requirement fixes them. Every figure below was
read out of the artifacts in this tree; nothing is quoted from memory, and where
a claim rests on a command, the command is shown.

## A) Screen Recording and Animation

### The save lives in the repository, and it is committed

The game was launched from the repository root as
`./cataclysm-tiles --userdir ./playthrough/userdir/`, so the engine wrote its
save inside the working tree. `--userdir` is normalised but not absolutised
\[src/path_info.cpp:105\] and the save directory is derived as
`user_dir + "save/"` \[src/path_info.cpp:144\], which is why the launch
directory matters as much as the flag.

Getting it *tracked* took one change to `.gitignore`, and it was not optional.
Cataclysm-DDA names per-character save files `#<base64-of-name>.sav`, and
`.gitignore` carries `\#*` at line 131, an unanchored `*.log` at line 31 and
`debug.log` at line 79. Without a negation, `git add` skips those files and
exits successfully — the failure is silent. A terminal negation block was
appended, and it is the **last** matching pattern, which is what makes it
effective:

```console
$ git check-ignore -v --no-index -- \
    "playthrough/userdir/graveyard/2026-08-10T04-04-38/#T2RldHRlIFZhY2hvbg==.sav"
.gitignore:275:!/playthrough/**	playthrough/userdir/graveyard/…/#T2RldHRlIFZhY2hvbg==.sav
```

The committer identity is set in this repository only:

```console
$ git config --local --get user.name && git config --local --get user.email
Blitzy Agent
agent@blitzy.com
```

**Two commits bracket the session, as required — one after the survivor was
created, one after it closed.** Both name the same survivor and the second
descends from the first:

| Checkpoint | Commit | Records |
| --- | --- | --- |
| `creation` | `57ee8afc3498ff12973cae284c16e1ae700bf089` | Barrows / Odette Vachon, 199 frames, 199 rows |
| `final` | `7b7673677eb70a7466cb5618152590daa3209ed4` | Barrows / Odette Vachon, 305 frames, 305 rows |

The `creation` checkpoint is taken after the first autosave rather than at the
instant the creator closed, and the reason is the engine's: no character file
exists at creation, because the `#<base64>.sav` is written when the game next
saves, and the autosave needs both 50 turns and five real minutes. A checkpoint
taken any earlier would have had no save in it, which is the thing that commit
exists to publish.

**The survivor's save is in the graveyard, and that is where a death puts it.**
`cleanup_at_end()` \[src/do_turn.cpp:111-207\] runs `move_save_to_graveyard()`
\[src/game_io.cpp:247-275\], which *renames* every `save/<World>/#<b64>.*` file
into `graveyard/<timestamp>/`. Then, the dead survivor having been the world's
only character, `WORLD_END` decides the world's fate: it is committed as
`"reset"` — the engine's own default \[src/options.cpp:2836-2841\] — so
`delete_world(name, false)` \[src/worldfactory.cpp:2458-2496\] cleared
everything `isForbidden()` \[:2449-2456\] does not spare. `save/Barrows/`
therefore holds `mods.json`, `world_timestamp.json` and `worldoptions.json`,
and the character's files are all tracked at
`playthrough/userdir/graveyard/2026-08-10T04-04-38/`.

### The capture system, and the frame count

One screenshot per keystroke, and the relation is structural rather than
intended. `session.py` owns a single monotonic frame counter and performs the
whole step — focus the window by class, send exactly one key with
`xdotool key --window --clearmodifiers`, let the frame settle, capture exactly
one PNG through `capture.sh`, read the sidebar clock, append exactly one
manifest row. Because one function increments the counter and uses it for both
the filename and the row, an orphan frame or an orphan row cannot be produced by
any ordering.

`capture.sh` photographs the **X root window** rather than the game window: the
game occupies 1920×1072 inside a 1920×1080 root, so capturing the root yields a
true-resolution PNG with no rescaling step to soften the text the OCR depends
on.

```console
$ ls playthrough/frames/frame_*.png | wc -l
305
$ wc -l < playthrough/manifest.jsonl
305
```

**305 captures, 305 rows, 305 caption cues, 305 transcript entries.** Every
capture is 1920×1080 and every one is tracked.

**One disclosed deviation, stated rather than smoothed.** The terminal `Y`
answering the main menu's "Really quit?" did what it was asked and the
application exited, so the capture taken immediately afterwards was genuinely
black (`mean=0 stddev=0`). `capture.sh` refused it and withdrew it to the
runtime directory. The luminance guard was not weakened and no frame was
fabricated, which is why the set is a consistent 305/305 rather than 306 with a
black image in it. The keystroke's own journal, written before delivery, records
it in full; it is reproduced in `playthrough/TECHNICAL_NOTES.md`.

### On-screen duration is in-game time, with a floor, a ceiling and a transition

Each frame stays on screen for as long as the action it recorded took **in the
game**, measured by differencing the sidebar clock between consecutive frames.
No turn count is modelled and no conversion constant is invented — the clock is
the only source of pacing. `24_HOUR` is seeded to `24h` so the clock renders as
fixed-width `"%02d:%02d:%02d"` \[src/calendar.cpp:638-662\], which is what makes
differencing reliable.

The mapping is `duration = min(max(raw_delta, 0.25), 10.0)`:

* **Floor 0.25 s.** Menu navigation and character creation consume no game time.
  Those frames fall to the floor; not one was dropped, merged or optimised away,
  which is why the timeline has exactly 305 entries for 305 keystrokes.
* **Ceiling 10.0 s.** Three entries exceeded it, and each gets a **cinematic
  transition** inserted after it — a 0.4 s fade to black, a 0.2 s card reading
  "…time passes…" set in the game's own `data/font/Terminus.ttf`, and a 0.4 s
  fade in, composed with MoviePy and materialised as twelve PNGs.

| Frame | Clock | Raw delta | On screen | Transition |
| --- | --- | ---: | ---: | --- |
| 195 | `08:00:12` | 10 794 s | 10.00 s | yes |
| 198 | `11:00:06` | 21 601 s | 10.00 s | yes |
| 210 | `17:00:11` | 47 s | 10.00 s | yes |

Those first two are the three-hour and six-hour waits she spent in cover. The
transition seconds are charged to the caption cursor as well as to the film, so
cue windows cannot drift from frame windows:

```
219.750 s of captures + 3.000 s of transitions = 222.750 s
```

and the final cue closes at `00:03:42,750`, which is that same total.

### The assembled film

**`playthrough/cata-play.mp4`**, one `libx264` pass over an ffmpeg
concat-demuxer list built from the timeline, at `-fps_mode vfr`. The list
repeats its final `file` entry — 342 file lines against 341 duration lines —
without which the container duration truncates.

```console
$ ffprobe -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height,pix_fmt,nb_frames \
    -show_entries format=duration,size -of default=nw=1 playthrough/cata-play.mp4
codec_name=h264
width=1920
height=1080
pix_fmt=yuv420p
nb_frames=342
duration=222.800000
size=9189760
```

342 encoded frames is 305 captures + 36 transition images + the repeated final
entry. The container's 222.800 s sits 0.050 s from the timeline's 222.750 s,
inside the render's own 0.12 s tolerance. There is no audio stream: the session
was muted (`SOUND_ENABLED=false`, `SDL_AUDIODRIVER=dummy`) and nothing was
narrated.

**The pixels are real, and that is asserted rather than assumed.** A frame
extracted from the finished film 60 seconds in:

```console
$ ffmpeg -v error -ss 60 -i playthrough/cata-play.mp4 -frames:v 1 -y probe.png
$ convert probe.png -colorspace Gray \
    -format "mean=%[fx:mean] std=%[fx:standard_deviation]" info:
mean=0.16773 std=0.206294
```

Both terms matter. A `mean` of 0 is the signature of `SDL_VIDEODRIVER=dummy`,
which renders nothing while every count still tallies; a `std` of 0 would catch
a uniform solid frame that a mean check alone would pass. The acceptance gate
makes the same assertion over **all 305** committed captures and over four
sampled points in each film.

### The transcript

**`playthrough/transcript.md`** — 305 entries, each opening with its cumulative
video timestamp and carrying Odette's own first-person account of why she did
what she did. It is titled `# Odette Vachon — what I did, and why`, deliberately
the same heading her dossier uses, so a reader arriving at either meets the same
person. Its stamps are the cue starts, and it is held to the same
no-engineering-language standard the caption file is.

### The caption track is selectable, not burned in

**`playthrough/cata-play-cc.mp4`**, muxed with
`-c copy -c:s mov_text -metadata:s:s:0 language=eng`:

```console
$ ffprobe -v error -show_entries stream=index,codec_type,codec_name \
    -of csv=p=0 playthrough/cata-play-cc.mp4
0,h264,video
1,mov_text,subtitle
$ ffprobe -v error -select_streams s \
    -show_entries stream=codec_name:stream_tags=language \
    -of default=nw=1 playthrough/cata-play-cc.mp4
codec_name=mov_text
TAG:language=eng
```

Two streams: the picture, and a player-toggleable English subtitle track. That
it is genuinely soft is measured rather than argued — comparing frames from the
captioned and base films at four times gives **0 differing pixels**, so no
caption is painted into the picture. The cue file
`playthrough/transcript.srt` holds 305 cues, contiguous from 1, 206 of one line
and 99 of two, longest line 42 columns. Nothing is truncated to fit: a caption
that needs a third line is refused and the source sentence shortened instead.

### The Python libraries, declared outside the game source

**`playthrough/tooling/requirements.txt`** — a folder that contains no game
source and sits nowhere near `src/`:

```
moviepy==2.2.1          # fade/card/fade transition unit: make_transitions.py
pillow==11.3.0          # PNG inspection, title card, MoviePy 2 image backend
pytesseract==0.3.13     # sidebar clock OCR wrapper: ocr_clock.py
numpy==2.5.1            # frame luminance statistics and MoviePy arrays
imageio==2.37.4         # frame and video IO used by MoviePy
imageio-ffmpeg==0.6.0   # encoder bridge for MoviePy and imageio
```

Installed and verified at exactly those versions:

```console
$ python -c "from importlib.metadata import version; ..."
  moviepy          2.2.1
  pillow           11.3.0
  pytesseract      0.3.13
  numpy            2.5.1
  imageio          2.37.4
  imageio-ffmpeg   0.6.0
```

The five named libraries are pinned exactly; `imageio-ffmpeg` is the sixth and
its comment says why it is there, so the file stays honest about a package the
requirement did not name. Exact `==` pins rather than floating bounds because
this pipeline produces a byte-level media artifact *and its own acceptance
evidence*, and a floating bound would let a future release change the film while
every gate still reported green.

### Everything is committed

| Artifact class | Where the shipped bytes were committed |
| --- | --- |
| the save (world options, graveyard save, memorial) | `7b7673677e` — the `final` checkpoint |
| the captures, all 305 | `57ee8afc34` (1–199) and `7b7673677e` (200–305) |
| `manifest.jsonl`, `amendments.jsonl` | `7b7673677e` |
| `timeline.json`, `transcript.md`, `transcript.srt` | `ebbafd6f39` |
| `cata-play.mp4`, `cata-play-cc.mp4` | `ebbafd6f39` |
| the 36 transition images, `build/concat.txt` | `ebbafd6f39` |
| `tooling/requirements.txt` | `a6e405fe33` |
| `dossier.md` | first tracked at `1ad704df3b` |
| `acceptance-report.txt` | `fc3735b12a` |

The dossier's ordering is provable from the graph rather than asserted: its
introducing commit `1ad704df3b` is a **strict ancestor** of the first capture's
`7117ef9700`, so it existed before the first gameplay frame and one commit
cannot stand for both.

`ebbafd6f39`'s subject names only a tooling fix although it also carries the
render; the cause and the reason no history was rewritten to tidy it are
disclosed in `playthrough/TECHNICAL_NOTES.md`.

**The whole artifact set was measured by its own gate**, and the passing
measurement is committed beside the artifacts it judges at
`playthrough/acceptance-report.txt`: **117 of 117 declared checks passed**, no
failures — 117 being its whole declared inventory at that moment; the gate has
since grown to 120 properties and a receipt describes the run that took it. Its
scope includes every claim above — the frame-to-row identity, the clamp bounds,
the transition count, the container facts, the luminance floor on all 305
captures, the caption stream, the dependency closure, and that nothing under
`playthrough/` is left uncommitted.

## B) Character Creation

She was built through the main menu's **`Custom Character`** entry — the
point-buy creator — on the **Missed** scenario. `Random Character`,
`Play Now! (Default Scenario)`, `Play Now!` and the template picker were never
selected; the first keystroke of the session, frame 1, is recorded as *"move the
New Game selection up off Preset Character and onto Custom Character"*.

### Her own account of herself

Written before the first keystroke and committed before the first gameplay
frame, in full at `playthrough/dossier.md`. It opens:

> Fifty-two years old. Thirty-one seasons on the water out of Gloucester, the
> last nine of them on my own boat.

Odette Vachon, 52, of Gloucester, Massachusetts. Thirty-one seasons hauling out
of that harbour, the last nine on the *Marie-Ange*, which was hers. She is
walking down the coast toward Salem because her daughter Camille is somewhere at
the end of it, and that is the whole of her plan. She sleeps like a stone
because she spent thirty-one years bunked over a running diesel, and out here
that is going to cost her. She missed the evacuation.

### What she is made of

**Profession: Fisher. World: Barrows.** Base stats **Str 10 / Dex 8 / Int 7 /
Per 10** — strong hands and good eyes, an unremarkable head for anything
written down.

Traits, in the order the memorial lists them:

| For her | Against her |
| --- | --- |
| **Strong Stomach** | **Addictive Personality** |
| **Tough** | **Heavy Sleeper** |
| | **Bad Back** |

Skills, read back from the engine's own memorial file. Two were bought in the
creator; the rest came with the profession:

| Skill | Level | Source |
| --- | ---: | --- |
| survival | 5 | Fisher |
| athletics | 2 | Fisher |
| vehicles | 2 | Fisher |
| **mechanics** | **2** | **bought, 0 → 2** |
| **fabrication** | **2** | **bought, 0 → 2** |
| applied science, computers, electronics, food handling, health care, social | 1 each | Fisher |

**Four points were deliberately left unspent.** The creator asks about it, and
the record shows the question being answered: *"Remaining points will be
discarded, are you sure you want to proceed?"* → `Y`.

### Why this combination and not another

It is neither min-maxed nor flat. **Not one point went into a combat skill** —
her melee, dodging, bashing and cutting all read 0 — and that is a real
decision with a real price, which the session then charged her in full. What she
can do is keep herself alive outdoors and put broken things back together:
survival 5 is the highest number on her sheet, and the two skills she bought
turn her into someone who can work on an engine and build what she needs.

The flaws are not decoration. **Heavy Sleeper** is the one that killed her: she
lay down in cover at the end of the day and did not hear what was coming.
**Bad Back** caps what she can carry away from anywhere. **Addictive
Personality** is a bill that arrives later. Against them, **Tough** and **Strong
Stomach** are exactly the two boons a fifty-two-year-old deckhand would have
earned — she can take a beating and she can eat what is in front of her.

One item in the Fisher's kit turned out to be load-bearing for the whole film: a
**`wristwatch`**. Cataclysm-DDA only prints an exact clock while the survivor
carries something that tells the time \[src/display.cpp:207-219\]; without one
the sidebar shows a phrase like "Around dawn" and there is nothing to difference.
Her father's watch is the reason every duration in the film is a real number of
seconds. It was chosen in character and it happens to be the pipeline's
precondition.

## C) Playing the Game

### From spawn to the end, in her own words

I came to in a candy shop at **08:00:00**, Thursday, May 20, with the rod in my
hands and nineteen of them near enough to matter. Whoever wrote the
sign over that counter thought people would be buying sweets forever.

The alarm was telling me what I could already see, so I turned it off — it was
freezing me in the doorway every time something new came round a corner, and
standing still in a shop full of them is not a plan. I found the back door on
the west side, opened it, stepped out into the alley, and shut it behind me. A
door you close is worth more than a door you run through.

Then I did the thing that keeps you alive and looks like nothing: I waited.
Three hours first, then six. There were twenty of them between me and anywhere,
and I have never once won a fight I could have walked away from. Something
groaned close enough that I had to decide whether to stay put, and I stayed.
Groaning is not the same as coming.

I came out at **17:00** and I was in trouble — the kind you can measure:
very thirsty, weaker in every way that counts, slower than I woke up. I went back
inside, shut the door again, and set the alarm for dawn. If I could get a night
behind me I could go looking for water in the morning with my eyes working.

I never got to sleep. Something tried to bite me and missed. Two dogs had come
up on me in the last of the light — dogs, not the slow ones — and behind them a
file of the others was coming through the shop.

I went out the back and I fought them in the doorway, because a doorway is the
only place someone who cannot fight has a chance: they come one at a time or
they do not come. One of the dogs got my right arm and held on. I broke the grab
and I hit it, and I hit it again, and the second time it went down. I killed a
dog with a fishing rod. It cost me a promise I had made myself about not doing
that.

Then I walked. North past the wall, west along the brick, past the front of a
home-improvement place — of every building on that street, the one I would have
picked, if I had had a minute. I did not have a minute. The number behind me kept
climbing — twenty, then twenty-six, then twenty-eight — and the second dog was
the only one of them fast enough to stay with me, so I turned round and I took
it on.

That is where it ended. My right arm went, then both of them, then my head. I
lost the rod somewhere and finished with my hands. I could not get a breath
under the weight of it, and I could not get out of the way any more, and then I
could not do anything at all. **17:02:55**, in a subway station in central
Smithfield. Nine hours and two minutes.

They asked me for last words. There was only ever one name for them.

**"Camille."**

### The record of it

The account above is the account the frames support. Every clock reading in it
came off the sidebar of a captured frame: `08:00:00` at frame 158, the alarm
switched off at frame 186, the six-hour wait beginning at frame 198 with the
clock reading `11:00:06`, `17:00:11` at frame 210 as she came out of cover,
`17:02:55` at frame 291 as she began her last words. The engine's own memorial
file records the ending independently: *"She died on Year 1, May 20 17:02:55.
She was killed in a subway station in central Smithfield"*, one kill — a zombie
dog — and 0 of 110 hit points in all six limbs.

The ending is a **death**, which is one of the two endings the session was
permitted, and the engine's whole ending path was then run to completion and
captured screen by screen: the last-words prompt typed one letter at a time
(frames 291–299), the deathcam declined, the post-death message log, the diary
prompt declined, the scores window, the follower epilogue, and out through the
main menu's own quit (frames 300–305). That is what left the graveyard save and
the memorial pair on disk, and what closed the world.

**No debug or cheat command was used at any point in this session** — no debug
menu, no debug mode, no spawning, no stat editing, no teleport, no god mode, no
map reveal. **Death was resisted by legitimate play alone**, and it was not
avoided by any other means: no save was reloaded, nothing was undone, and the
outcome was neither steered toward nor away from. The claim is checkable rather
than asserted. The engine ships `debug_mode`, `debug` and `debug_hour_timer`
with no `bindings` array at all \[data/raw/keybindings.json\], so they are
unreachable by any keystroke unless deliberately bound — and there is **no**
`playthrough/userdir/config/keybindings.json` in this tree. The engine writes
that file only when a binding is changed, so its absence is the evidence that
the shipped bindings, in which every debug action is unbound, are the ones that
were played.
