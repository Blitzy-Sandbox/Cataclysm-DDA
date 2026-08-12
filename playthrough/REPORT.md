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
    'playthrough/userdir/save/Fairport Harbor/#T2RldHRlIFZhY2hvbg==.sav'
.gitignore:275:!/playthrough/**	playthrough/userdir/save/Fairport Harbor/#T2Rl….sav
```

**The committer identity, stated as it actually is.** Every commit in this
history is authored and committed by `Blitzy Agent <agent@blitzy.com>`, and that
identity resolves from a scope **broader than this checkout** — the repository
records none of its own:

```console
$ git config --local --get user.name
$ git var GIT_AUTHOR_IDENT
Blitzy Agent <agent@blitzy.com> 1786418652 +0000
$ git log -6 --format='%an <%ae>' | sort -u
Blitzy Agent <agent@blitzy.com>
```

The plan asks for a repository-local identity (§0.3.1, §0.10.2). The execution
environment this record was produced in fixes the committer identity itself and
prohibits creating that pair. **Its directive, quoted word for word rather than
paraphrased, because a paraphrase is not an exception:**

> All git commits must be authored and committed as
> `Blitzy Agent <agent@blitzy.com>`. Never run `git config
> user.name`/`user.email`, and never override the author/committer identity.

Setting a repository-local pair means running one of the two commands that
sentence forbids, so satisfying the plan here would have been a violation rather
than a compliance. **The two instructions cannot both be obeyed**, which makes this
a requirement-level conflict for a human to settle and not something any run of
the gate can close. What is delivered instead is the property the local identity
was wanted *for*: the identity **resolves**, and it **agrees with every commit in
the history**. Both are asserted by the acceptance gate rather than claimed here,
and the gate quotes the same directive verbatim in its own divergence — the
constant it quotes from is `IDENTITY_DIRECTIVE` in `verify_artifacts.sh`, so the
wording in the gate and the wording here cannot drift apart silently. This
divergence is recorded in full in `TECHNICAL_NOTES.md`.

**And the gate now calls it a divergence rather than a pass.** It previously
reported this check as `PASS` with the caveat in its prose — the sentence was
truthful and the verdict was not, and a reader or a script that took the verdict
at face value was told this element of R1 was met. A review named exactly that:
the report *"records missing local identity as PASS"*. The gate has a third
verdict class for it now, and this is what a real run prints:

```console
DIVERGENCE  git has an identity to commit these artifacts under, and the
            history agrees with it
      observed: … It is NOT repository-local: 'git config --local --get
                user.name' answers nothing here
      the plan requires: a repository-local pair … per §0.3.1 and §0.10.2
      why it stands: the execution environment … PROHIBITS running 'git config
                user.name' or 'user.email' at any scope …
SUMMARY  … checks passed with 1 DIVERGENCE(S) from the plan …  Nothing FAILED,
         but the run does not claim full compliance
VERIFY_DIVERGENCES=1
VERIFY=pass-with-divergence
```

A divergence is neither a pass nor a failure. It counts toward the declared check
inventory, so it cannot be lost by being reclassified; it does **not** change the
exit status, because a non-zero exit for an environment-imposed and permanent
divergence would block every future checkpoint for good; and the summary sentence
stops claiming full compliance for the run as a whole. `VERIFY=pass-with-divergence`
is a token a caller that only understands pass and fail treats as neither, which
is the correct default for something it has no rule for.

**The session is bracketed by commits, as required — one after the survivor was
created, one after it closed.** Both name the same survivor and the second
descends from the first. Two further checkpoints carry what only exists after
the session is over:

| Checkpoint | Commit | Records |
| --- | --- | --- |
| `creation` | `800ab8e11f8852175e17f96dcc4f68fc5d58d4a4` | Fairport Harbor / Odette Vachon, 171 frames, 171 rows |
| `final` | `555b12b88d90a038681a26bd4286b4254e4a86ad` | Fairport Harbor / Odette Vachon, 307 frames, 307 rows |
| `media` | `b0038360c77a7bb22cbfc47270ea584ad98046d9` | the film, both transcripts, the timeline |
| `attest` | *(the commit that adds this document)* | `acceptance-report.txt` and this report |

The `attest` row carries no hash on purpose: a document cannot contain the id of
the commit that introduces it. `git log --grep '^Playthrough-Checkpoint: attest'`
is where to read it, and the acceptance report committed beside this one names
the tree it measured in its own `VERIFY_MEASURED_COMMIT` line — the commit
immediately before it, which is the last one whose contents it could honestly
have read.

The gate's own verdicts are committed rather than left in a terminal.
`playthrough/acceptance-report.txt` is the **post-commit** half — the properties
only a commit can make true — and declares **37 checks**. The **pre-commit** half,
which measures the artifacts themselves, declares **119**. **134 in all**, and the
counts are summed from the derivation table beside `GROUP_CHECKS_ALL` in
`verify_artifacts.sh` rather than written by hand, so the gate refuses its own
report if the number of checks it printed is not the number it declared.

**The committed acceptance report is the authority on the run-specific verdict,
not this paragraph.** A code review made the point that mattered: a document that
recites pass counts drifts away from the gate that produces them, and a recited
count that has gone stale reads as compliance. So the totals above are the
*declared* ones, which are structural, and the passes, failures, divergences and
informational notes for the run this document was published beside are in
`playthrough/acceptance-report.txt`, measured over the commit it names in its own
`VERIFY_MEASURED_COMMIT` line. Two verdicts in it are **divergences** rather than
passes, and both are stated in full below: the git identity is not
repository-local (next paragraph) and the checkpoints taken before the
evidence-anchor mechanism existed publish no chain head of their own
(*The security controls this record rests on*).

The `creation` checkpoint is taken after the first autosave rather than at the
instant the creator closed, and the reason is the engine's: no character file
exists at creation, because the `#<base64>.sav` is written when the game next
saves, and the autosave needs both 50 turns and five real minutes. A checkpoint
taken any earlier would have had no save in it, which is the thing that commit
exists to publish.

**The survivor's save is in `save/`, where a living survivor's save belongs.**
She slept, woke and left through the in-game Save & Quit, so `cleanup_at_end()`
never took the death path: `move_save_to_graveyard()` did not run, `WORLD_END`
cleared nothing, and there is no `graveyard/` and no `memorial/` in this tree at
all. Their absence is positive evidence about which of R11's two endings was
taken. `playthrough/userdir/save/Fairport Harbor/` holds 134 tracked files —
`master.gsav`, `dimension_data.gsav`, ten `o.N.N` overmap segments, 95 map
chunks, the fourteen `.seen.N.N` visibility files, five memory-map files, and
the character's own `#T2RldHRlIFZhY2hvbg==.sav` beside its `.log`, `.pt`,
`.ano.json` and `.zones.json` companions.

### The capture system, and the frame count

One screenshot per keystroke, and the relation is structural rather than
promised. `session.py` is the sole owner of the frame counter: one function
focuses the window by class, sends exactly one key with
`xdotool key --window`, lets the frame settle, captures exactly one PNG with
`import -window root`, reads the clock, and appends exactly one manifest row.
Because the counter is incremented in one place and used for both the filename
and the row, an orphan frame or an orphan row cannot be produced by any ordering
of operations.

Capture targets the **X root window** deliberately: the game window is
1920×1072 inside a 1920×1080 root, so photographing the root yields a
true-resolution frame with a four-pixel letterbox and needs no rescaling step
that would soften the text the clock is read from.

**307 keystrokes, 307 frames, 307 rows:**

```console
$ ls -1 playthrough/frames/frame_*.png | wc -l
307
$ wc -l < playthrough/manifest.jsonl
307
```

The captures are contiguous `frame_00001.png` … `frame_00307.png`, every row
names its own capture canonically, and `frames/` holds nothing else. Derived
imagery — the materialised transition pictures — goes to `build/transitions/`,
never there, precisely so that the count above is an identity that a mixed-in
file would break.

Every capture is also hashed into `build/frame_digests.jsonl` just after the row
that recorded it: 307 attestations, each at or after its row and within 32.8 s
of it, so a capture that was swapped afterwards would not match its own digest.

### On-screen duration is in-game time, with a floor, a ceiling and a transition

Each frame is shown for the in-game time its keystroke consumed. The source is
the **sidebar clock**, differenced between consecutive frames — no turn count is
modelled and no conversion constant is invented. `24_HOUR` is seeded to `24h`
so the clock renders as fixed-width `%02d:%02d:%02d` \[src/calendar.cpp:638-662\],
which is what makes the reading deterministic.

`duration = min(max(raw_delta, 0.25), 10.0)`, and a raw delta over the ceiling
additionally flags a cinematic transition. Measured over the shipped timeline:

* every duration lies in `[0.25, 10.0]`, and every one *is* exactly
  `clamp(raw_delta, 0.25, 10.0)`;
* **230** frames had a raw delta below the floor — menu keystrokes and steps
  inside a single second — and every one is held at **0.25 s**. None was
  dropped, merged or optimised away;
* the ceiling engaged **12** times, at frames 170, 279, 283, 284, 285, 286, 296,
  298, 299, 303, 304 and 305, whose raw deltas of 172, 337, 2167, 830, 2401,
  36 869, 313, 7200, 7458, 1542, 3000 and 9858 seconds were each held at 10.0 s.

Each of those twelve is followed by a **fade to black, a "…time passes…" card
set in the game's own Terminus face, and a fade in** — 0.4 s, 0.2 s, 0.4 s,
materialised as 12 PNGs at 12 fps, 144 pictures in all. The card is really
rendered: extracted from the finished film and read back by OCR it says
`time passes..`.

**The invariant:** `sum(durations) + sum(transitions) == total == final cue end`.

```console
$ python3 -c "import json; d=json.load(open('playthrough/timeline.json')); \
print(d['total_duration'], d['total_transition'], d['total'], d['final_cue_end'])"
288.5 12.0 300.5 300.5
$ grep -E -- '-->' playthrough/transcript.srt | tail -1
00:05:00,250 --> 00:05:00,500
```

288.5 + 12.0 = 300.5, and the last cue closes at 300.500 s. Walking the cue
cursor again from zero reproduces every window and charges each transition's
inserted second before the next cue begins, which is what stops the caption
track drifting: cues that ignored it would be right at the start and
increasingly wrong by the end.

`timeline.json` is the **single source of truth** — the renderer and the caption
generator both read it, in one pass — and it attests the amendment ledger it was
computed from by sha256, so amending a row after the fact invalidates the
timeline instead of silently disagreeing with it.

### The assembled film

`playthrough/cata-play.mp4`, one `libx264` pass over an ffmpeg concat list of
451 image entries at `-fps_mode vfr -pix_fmt yuv420p`.

```console
$ ffprobe -v error -show_entries stream=codec_name,width,height,pix_fmt,nb_frames \
      -show_entries format=duration -of default=nw=1 playthrough/cata-play.mp4
codec_name=h264
width=1920
height=1080
pix_fmt=yuv420p
nb_frames=452
duration=300.560000
```

h264, 1920×1080, 452 encoded frames, 300.560 s against the timeline's 300.500 s
— one frame at the tail, from the concat demuxer's repeated final entry, which
is the idiom that stops the container truncating the last duration. 20 047 349
bytes.

**It is not blank, and that is measured rather than assumed.** A run left on
`SDL_VIDEODRIVER=dummy` renders zero pixels: the game runs, the captures
succeed, the encode succeeds, every count tallies, and the only symptom is that
nothing is visible. So the grayscale statistics of **all 307** captures were
swept, and frames extracted from both films at eight timestamps with them:

```console
$ identify -format "%f %[fx:mean] %[fx:standard_deviation]\n" 'playthrough/frames/*.png'
frame_00001.png 0.00553587 0.0702471
…
frame_00307.png 0.00399184 0.0589014
```

Every capture has `mean > 0` **and** `stddev > 0` — the mean rules out black, the
standard deviation rules out a uniform solid colour that a mean check alone would
pass. The dimmest is frame 307, the main menu, at mean 0.003992 / stddev
0.058901; the brightest is frame 267 at 0.257112 / 0.238058.

### The transcript

`playthrough/transcript.md` carries one entry per action — 307 of them — each
with its cumulative video timestamp and first-person commentary saying why the
survivor did it. It is generated from `timeline.json` in the same pass as the
caption file, so the two cannot disagree about when anything happened.

**Two shortfalls were found by review, and both are corrected in the record
rather than explained in this document.** An earlier version of this section
claimed that no entry was a single word. That was false, and the count is worth
stating plainly: **44 of the 307 commentaries were one word** — forty-two of them
a single character transcribed while spelling a search term during character
creation (*"M."*, *"I."*, *"S."*), plus *"Next."* at frame 93 and *"Five."* at
frame 144. A letter is not a reason, and R7 asks for the reason. Separately,
**frames 225 and 226 repeated frame 224's sentence** — *"South. Off the tarmac,
over the kerb, into the green."* — across three identical paces.

Both were corrected the only way this record permits: **the manifest is
append-only, so nothing was edited.** 46 amendments were appended to
`playthrough/amendments.jsonl` (ids 157–202), each one binding itself to the
sha256 of the manifest line it corrects, quoting the recorded sentence verbatim,
and stating its basis and its reason. Frame 224 was left exactly as recorded — it
is the origin sentence, not the defect — and 225 and 226 were given their own
motive. The whole chain was then regenerated from the amended record, so the
timeline, the caption file, the readable transcript and the captioned film all
derive from it. **Both the raw record and the ledger are committed**, which is
what makes the correction auditable rather than invisible: a reader can see what
was written, what it was changed to, and why.

What the gate reports over the corrected record, verbatim:

```text
PASS  no entry is only the key that produced it
      observed: 307 entr(ies) measured against the effective narration: the
      record with playthrough/amendments.jsonl applied: each closes as a
      sentence, each carries at least one word beyond its own keystroke, and
      no commentary is a single word.  This is the falsifiable half of the
      requirement; that what the entry adds is a REASON is not machine-decidable
      and is not claimed here
```

No entry repeats a sentence used within the previous three, so the repeat
warning the gate used to print is no longer emitted at all. The gate also names
the five thinnest entries so a reader can judge the half no program can — now
*"Marksmanship. No."* (frame 120), *"Rifles. No."* (121), *"Two more."* (267),
*"A. Boating."* (47) and *"Show me."* (48). Three words can be a complete reason
and thirty can be padding; that judgement is the reader's, and this document does
not claim it.

### The caption track is selectable, not burned in

```console
$ ffprobe -v error -select_streams s -show_entries \
      stream=index,codec_name:stream_tags=language -of default=nw=1 \
      playthrough/cata-play-cc.mp4
index=1
codec_name=mov_text
TAG:language=eng
```

`mov_text` is the soft subtitle codec inside MP4, muxed with `-c copy -c:s
mov_text -metadata:s:s:0 language=eng`, so a player offers it as a track to turn
on and off. **That it is not burned in is provable, not merely intended:** the
video stream of the captioned film is byte-identical to the uncaptioned one.

```console
$ ffmpeg -v error -i playthrough/cata-play.mp4    -map 0:v -f md5 -
MD5=4c38e03830e7d4a278f237276b9dae46
$ ffmpeg -v error -i playthrough/cata-play-cc.mp4 -map 0:v -f md5 -
MD5=4c38e03830e7d4a278f237276b9dae46
```

307 cues for 307 frames, numbered 1..307, each occupying its own frame's window,
none overlapping, with exactly twelve gaps of exactly 1.0 s — the twelve
transitions. Extracting the embedded track back out decodes to 307 cues whose
timings match within 50 ms and whose text is identical for every one. No cue
exceeds two lines of 42 columns.

### The Python libraries, declared outside the game source

`playthrough/tooling/requirements.txt` — **not** under `src/`, which is the
separation the requirement asks for. Six exact pins:

| Package | Version | What it does here |
| --- | --- | --- |
| `moviepy` | 2.2.1 | composes the transition unit: the fades and the title card |
| `pillow` | 11.3.0 | PNG inspection, and MoviePy 2's image backend |
| `pytesseract` | 0.3.13 | the sidebar clock read |
| `numpy` | 2.5.1 | per-frame pixel statistics behind the luminance gate |
| `imageio` | 2.37.4 | frame and video IO under MoviePy |
| `imageio-ffmpeg` | 0.6.0 | the encoder bridge the two above require |

The sixth is not named in the requirement and is declared anyway, with an inline
comment saying exactly why, because a requirements file that hides a real
dependency is worse than one that explains an extra line.

### Everything is committed

```console
$ git ls-files playthrough | wc -l
665
$ git ls-files playthrough/frames | wc -l
307
$ git ls-files playthrough/userdir | wc -l
149
$ git ls-files playthrough/userdir/save | wc -l
134
$ git ls-files playthrough/cata-play.mp4 playthrough/cata-play-cc.mp4 \
      playthrough/transcript.srt playthrough/transcript.md \
      playthrough/manifest.jsonl playthrough/timeline.json \
      playthrough/tooling/requirements.txt
playthrough/cata-play-cc.mp4
playthrough/cata-play.mp4
playthrough/manifest.jsonl
playthrough/timeline.json
playthrough/tooling/requirements.txt
playthrough/transcript.md
playthrough/transcript.srt
```

Every artifact class the requirement names — the save, every frame, both films,
both transcripts and the requirements file — is tracked. `git status
--porcelain -- playthrough/` is empty. No frame was decimated, sampled,
deduplicated or downscaled to save space: where repository size and completeness
conflicted, completeness won.

### The security controls this record rests on

A review found this report *"omits security controls"* — and the omission
mattered for a specific reason. Everything above is a count or a digest, and a
count reads identically whether or not anything was defending it. A reader could
not tell a run with these controls from a run without them, which is the same
failure mode as a report that gets shorter: indistinguishable from a complete one
to anyone who does not already know the number.

So the controls are named here, and — more importantly — they are **inventoried by
the gate itself**. `check_security_controls` holds a table of `label|file|marker`
rows and asserts each control is still present in the file that implements it,
printing the list into `acceptance-report.txt` as observed evidence. A control
that is removed or renamed now **fails a check** instead of quietly disappearing
from the prose. The marker is a function name, never a phrase, so rewording a
comment cannot satisfy it and refactoring cannot silently void it.

| What it defends | Control | Where |
| --- | --- | --- |
| The push credential | the git config carrying the token is owner-only, asserted before any commit | `commit_artifacts.sh` |
| The commit itself | no hook runs on a mutating git command; the published tree is bound to the validated index | `commit_artifacts.sh` |
| What gets staged | per-path provenance — owner, regular file, single link, same device; and a secret and credential scan over every path | `commit_artifacts.sh` |
| The runtime root | a group- or world-writable non-sticky ancestor is refused, and a trusted anchor is chosen ahead of any `/tmp` fallback | `env.sh` |
| Every artifact | created owner-only; foreign writability anywhere under `playthrough/` is refused | `env.sh` |
| Child processes | the inherited environment is sanitised — 31 named variables refused — before anything runs | `env.sh` |
| Concurrent runs | one checkout-wide mutation lock, shared for producers and exclusive for the verifier and committer | `env.sh` |
| The display | the X server is identified by process identity, socket and cookie digest, not by a pid; a fresh cookie per server generation | `env.sh` |
| Values from outside | a bounded printable record-token grammar, and control-byte escaping on every diagnostic | `env.sh` |
| The evidence | the ledgers are hash-chained and each row carries the git blob name of what it seals | `manifest.py` |
| The journal | writes are verified and durability failures propagate rather than being swallowed | `session.py` |
| The payload | a chosen value cannot forge a `KEY=value` record or a log line | `session.py` |
| The decoders | the bytes are read through one `O_NOFOLLOW` descriptor, validated by `fstat` on that descriptor and decoded from memory, so no pathname reaches a native decoder; the decode runs under CPU limits with core dumps forbidden | `ocr_clock.py`, `make_transitions.py` |
| The transcript | the survivor name is held to a conservative grammar rather than escaped after the fact | `make_srt.py` |
| The container | identified by image id and a build-inputs digest, never by a mutable tag | `supported_env.sh` |

**Two of these were tightened by the review that produced this revision**, and
saying so is the point of keeping the list. The X server is no longer signalled by
number: `env.sh` pins a **pidfd** through the pipeline's own interpreter
(`os.pidfd_open` then `signal.pidfd_send_signal`) and validates the process's
identity *after* the handle is pinned, so a pid recycled between the check and the
signal can no longer be signalled by mistake — and where pidfd is unavailable the
helper reports and sends nothing rather than falling back. And the staging scan
now reads **every byte of every path**: it streams each file in overlapping chunks
instead of examining a 256 KiB window, and a file containing NUL bytes is scanned
under a printable-ASCII constraint rather than skipped, so the row above that says
"over every path" is now measurably true — 665 paths and 112,890,194 bytes in
3.9 s on this host.

**Four remain documented divergences from the guidance that prompted them**,
recorded with their reasons rather than quietly dropped: apt inputs are not
snapshotted, because the value of an in-support release *is* its updates, and the
build records its inventory and binds it to the image identity instead; engine
files are classified by position and refused by property rather than by an
explicit filename schema; the evidence ledger is hash-chained, git-anchored and
published in a commit trailer rather than signed, because no key management exists
here and a private key committed to the tree it signs proves nothing; and the
repository-local git identity is reported as a divergence rather than created, for
the reason given at the top of this report.

**And one residual is named by the gate rather than by this paragraph.** The
evidence anchor's head is published as a commit trailer, but the mechanism was
built after the session's own checkpoints were taken, so those checkpoints carry
no head of their own. A review found the gate accepting any newest trailer as
though it covered them, which is exactly the reading that made a retrospective
seal look like a contemporaneous one. The gate now asks the question **per
required checkpoint** and reports what it finds:

```text
DIVERGENCE  the evidence anchor's head is published in the history
      observed: … declares Playthrough-Evidence-Anchor: 468793a63e813a78, which
                is the head the anchor ends on, but 5 required checkpoint(s)
                publish no head of their own: 800ab8e11f (creation)
                7e10721d4e (creation) 555b12b88d (final) 4e8a49879a (final)
                b0038360c7 (media)
```

What would close it is a re-recorded session whose checkpoints are taken through
the hardened committer from the first commit onward. What cannot close it here is
publishing the head to an external transparency service: this feature introduces
no network surface of any kind, by plan (§0.8.2), and inventing one to satisfy an
attestation would be a larger deviation than the one it fixed.

## B) Character Creation

### Who she is

**Odette Vachon.** Fifty-two years old, 175 cm, a commercial fisher out of
Gloucester, Massachusetts — thirty-one seasons on the water, the last nine of
them on a boat of her own. Her grandfather came down from Rivière-du-Loup and
put three sons on fishing boats because it was the only trade he had to give
them; her father was the middle one, she was his only child, and there was no
son to hand it to.

Her account of herself is `playthrough/dossier.md`, written in her own voice
before the first keystroke and committed before the first captured frame. She is
blunt about her own limits in it:

> I am not brave. I want that written down plainly, because I have watched brave
> people get killed on the water and I have never once envied them. What I am is
> patient and stubborn and very hard to hurry.

Her reason for moving is one person: **Camille**, her twenty-six-year-old
daughter, who teaches fourth grade in Salem, thirty-one miles down the coast.

> I am not going to write down what I think has happened to her, because I have
> spent my whole working life around men who talked themselves into believing
> things about people who were overdue, and it never once brought anybody home.
> I am going to go and look.

**The before-play ordering is provable rather than asserted.** The commit that
put the current `dossier.md` bytes in the tree, `8eb61fb1db`, is a strict
ancestor of the one that put the current first capture there, `800ab8e11f` —
checked for *these* blobs rather than for whichever generation first used the
paths.

### How she was built

Through the main-menu door labelled **`Custom Character`** on the **Missed**
scenario, with the **Legacy Multiple pools** point allocation — the tab that
gives stats, traits and skills separate pools and lets stat points be spent down
into the other two. `Random Character`, `Play Now! (Default Scenario)`,
`Play Now!` and the template picker were never entered; `session.py --help`
prints that permitted-door list, so the constraint lives in the tool and not
only in prose.

The build, read out of the committed save rather than recalled:

| | |
| --- | --- |
| Profession | `fisher` |
| Strength | **10** |
| Dexterity | 8 |
| Intelligence | **7** |
| Perception | **10** |
| Traits | `TOUGH`, `PACKMULE`, `STRONGSTOMACH`, `BADBACK`, `HEAVYSLEEPER`, `ADDICTIVE` |
| Skills | survival 5, swimming 3, fabrication 1, mechanics 1, first aid 1, dodge 1, driving 1, cooking 1, tailoring 1 |

### Why this combination and not another

**Every line of it is in the dossier first, and the dossier was written before
the creator was opened.** The mechanics are the fiction, translated:

* *"I am strong, which is thirty-one years of hauling traps and not a gift"* →
  **STR 10**. *"My eyes are the best thing I own; I can see a change in the water
  at half a mile"* → **PER 10**. *"I can carry more than I look like I can"* →
  `PACKMULE`. *"I have been thrown against a gunwale in a February swell and gone
  back to work the same afternoon"* → `TOUGH`. *"A stomach that has never once
  betrayed me, which sounds like a joke until you have eaten what was
  available"* → `STRONGSTOMACH`.
* *"My back is going, and has been for six years"* → `BADBACK`. *"I sleep like
  the dead … I have never in my life woken up to a noise"* → `HEAVYSLEEPER`.
  *"Anything that comes out of a book comes slowly"* → **INT 7**. *"An addictive
  streak that runs straight down my mother's side of the family"* →
  `ADDICTIVE`.

**It is neither min-maxed nor average, and the trade-offs are real ones that
were paid during play.** Three of the four flaws cost her something in the
recorded session and are visible in the frames: `ADDICTIVE` put her into
nicotine withdrawal in the afternoon, twice interrupting a wait she needed;
`HEAVYSLEEPER` is why sleeping at all took two attempts and several prompts; and
`BADBACK` is the reason a fifty-two-year-old with a bad back left heavy things
where they lay instead of hauling them. `INT 7` is a real cost too — anything
learned from a book comes slowly for her, which is why the day's plan leaned on
what she already knew.

**The most deliberate choice is a negative one: she has no weapon skill of any
kind.** No melee, no bashing, no cutting, no stabbing, no marksmanship. A
survivor built to fight would have spent points there; hers went into survival 5
and swimming 3 — the competences of somebody who has spent her life outdoors on
water and none of it in a fight. That single omission determined how the whole
session had to be played, and it is why the day is a day of avoidance,
provisioning and reconnaissance rather than of combat.

**The wristwatch is the one mechanically load-bearing piece of the fiction.** The
dossier names *"the wristwatch my father wore until nineteen ninety-one, which
keeps time to the second and which I have not taken off since the day he died"*
— and the `fisher` profession grants a wristwatch unconditionally. That matters
beyond character: `display::time_string()` returns an exact clock **only when**
`u.has_watch()` \[src/display.cpp:207-219\], otherwise a coarse phrase like
"Around dawn". Every second-resolution duration in the film exists because she is
carrying her father's watch.

## C) Playing the Game

### From spawn to the end, in her own words

She came to on the floor of a golf course service building at **08:00:00 on
Thursday, May 20**, which is the clock on frame 164 and the first exact reading
in the record. The *Missed* scenario is exactly what it says: she slept through
it.

**She looked before she moved.** The first thing she did was answer a query box
and then open the surroundings list — 8 items, **0 monsters**, 44 kinds of
terrain and furniture. The monster tab being empty while the log read *"From the
northwest you hear gargling"* told her the thing making that noise was behind a
wall, which is the only reason she was willing to stay. The terrain tab told her
something worse: of 44 kinds in the room, **not one was a sink, a toilet, or
water of any description**.

**She took what a fifty-two-year-old fisher with a bad back would take, and
nothing else.** A golf bag off a rack — 45 litres of capacity for 1900 grams,
which for somebody who cannot lift with a twist is the best trade in the
building — and she put it on rather than carrying it. Her load went from 13.8 to
18.0 lbs. She left the golf clubs. She looked in the till and the counter and
found nothing, and moved on rather than searching furniture that had already
told her it was empty.

**She secured the building before she explored it**, and later closed the wood
door behind her when she came back in, which took the room to *very dark* and
was worth it.

**The best thing she did all day was reason her way to water without finding
any.** There was no water in the building and none in the open ground. But she
was standing on a golf course, and a golf course has a water hazard — she
surveyed the open ground and read 59 kinds of terrain over four pages, and among
them were **nine willow trees**. Willows grow where the water table is high. She
then opened the overmap and walked the cursor square by square, reading the
header each time — *golf course parking lot*, *golf course*, *forest trail* —
until one of them read **`swamp south from West Rutland`**. She put a note on the
chart, typing **W-A-T-E-R** one letter per keystroke, and it is in the committed
save. She never walked to it: it was late, she had no light, and the point of
knowing where water is is to still be alive when you go for it.

**She fed herself with her own skills rather than with luck.** She foraged a
patch of underbrush — *"You found: handful of young leaves (fresh)! x 2"* — and a
second patch that gave her nothing, which is the honest yield. Eighteen calories
a handful. It is not a meal; it is the difference between an empty stomach and
not.

**She examined the cars without touching them.** A dented hatchback, engine
marked faulty, two 20-litre tanks holding 10.794 litres of petrol each, a
battery draining at 28 of 3000, a broken window, and the siphon greyed out. She
read all of that off the vehicle screen and walked away. There was nothing there
she could use today.

**She spent the afternoon indoors doing nothing, deliberately.** With no weapon
skill, no light, and a swamp two squares away that she could not reach before
dark, the correct move was to sit down and let the day pass — so she set the
wait for *till night* and sat in the dark building for **ten and a quarter
hours**. Nicotine withdrawal interrupted her twice and she ignored it both
times. That single wait is the 36 869-second delta at frame 286, the largest in
the record.

At **19:54:29** she was *Very thirsty* with Focus 8. She ate both handfuls of
leaves. Then she slept — and slept badly, because she is a heavy sleeper: the
first attempt stalled twice on prompts, she woke at **00:04:18** on Friday to an
achievement popup (*"Survive for a day and find a safe place to sleep"*), set the
alarm for four more hours, and went back down.

### How it ended

Her own alarm clock woke her at **04:04:18 on Friday, May 21** — *"From your
position you hear beep-beep-beep! / You wake up."* She was **Dehydrated, Hungry
and Chilly**, her body weight had come down from Overweight to Normal, and her
stats had dropped with the dehydration to Str 9 / Dex 7 / Int 6 / Per 9.

Then she left the way the requirement asks: **immediately after waking, through
the in-game Save & Quit.** Frame 306 delivers `S`, which raises *Save and quit?
(Case Sensitive)*; frame 307 delivers `Y`, and the engine returns to the main
menu with the process still alive and `» Fairport Harbor (1)` listed under
`[Load]`. The last delivered keystroke is therefore a real capture rather than a
lost one.

The committed save agrees with the pixels independently of any OCR: its own
counters read `"turn": 5285058` against `"game_start": 5212800` — 72 258 seconds,
20 h 04 m 18 s from an 08:00:00 start — which is exactly **04:04:18**.

**She lived.** One day, no water found, but she knows where it is.

### No debug commands, no cheats, and nothing avoided by using them

**No debug menu, no debug mode, no spawning, no stat editing, no teleport, no
map reveal, and no reloading** — not at any point, and not to avoid anything.
This is checkable from committed files rather than taken on trust:

* `data/raw/keybindings.json` declares `debug`, `debug_mode` and
  `debug_hour_timer` **without a `bindings` array** \[:3398-3409, :3466-3471\],
  so they are unbound as shipped and unreachable by any keystroke.
* **`playthrough/userdir/config/keybindings.json` does not exist.** The engine
  writes that file only when a binding is changed, so its absence is the
  evidence that the shipped bindings — in which every debug action is unbound —
  are the ones that were played.
* **The engine's own log is committed, and it records no debug activity.** It is
  at `playthrough/userdir/config/debug.log` — the engine writes it beside the
  configuration, not at the top of the userdir, and an earlier version of this
  report cited the wrong path. A case-insensitive search of it for `debug`
  matches **nothing at all**, across the whole 1 634 bytes of it.
* The committed character save carries `"debug_mode": false`.
* **What the word does appear as, stated so the claim above is not read wider
  than it is:** `DEBUG_DIFFICULTIES` is an ordinary world option and is written
  into `playthrough/userdir/config/options.json` and
  `save/Fairport Harbor/external_options.json` by the engine, as it is for every
  world; the character save carries the `debug_mode` key quoted above; and
  `uistate.json` carries the engine's own interface state. So the claim being
  made here is **not** that the string never occurs under the userdir — it is
  that **no debug action was ever activated**, which is what the unbound
  keybindings, the absent `keybindings.json`, the `false` flag and the silent
  engine log say between them.

**Death was never close enough to resist, and that is the honest way to put
it.** The survivor met no monster at any point in the recorded day. She heard
one — the gargling to the northwest, on the far side of a wall — and every
decision after that was made to keep it that way: she stayed in the building,
closed the door behind her, surveyed with the item and monster lists rather than
by walking into rooms, and never once moved toward open ground she could not see
into. A character with no weapon skill of any kind does not survive a fight, so
she did not have one. That is not caution as a substitute for play; it is the
only play the build permits, and it is the reason the session reached a bed
rather than a graveyard.
