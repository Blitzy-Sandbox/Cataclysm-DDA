#!/usr/bin/env python3
"""Write playthrough/build/concat.txt and encode playthrough/cata-play.mp4.

The renderer.  It turns playthrough/timeline.json plus the captured PNGs
plus the transition PNGs make_transitions.py materialised into ONE MP4 in
ONE encoder pass, with a per-image duration on every entry so that the
film's pacing is diegetic: video time tracks game time.

WHY ONE PASS IS POSSIBLE AT ALL
Because the transitions are materialised as IMAGES rather than spliced
in as separate video segments, the whole movie is a single concat
demuxer list of image entries.  There is no segment cutting, no mixed
demuxer list, and no codec or parameter mismatch to reconcile -- a
transition is simply twelve more image entries carrying their own
duration lines.  The timeline arithmetic stays trivially consistent
with the container for the same reason.

WHAT IS READ AND WHAT IS WRITTEN
Read: playthrough/timeline.json, the captures under playthrough/frames/
and the derived frames under playthrough/build/transitions/.  Written:
playthrough/build/concat.txt and playthrough/cata-play.mp4, and nothing
else.  playthrough/frames/ is never written to -- it holds exactly one
PNG per keystroke and that identity is what the whole
one-frame-per-keystroke gate rests on.

THE TIMELINE IS THE SINGLE SOURCE OF TRUTH
Every duration comes from playthrough/timeline.json and none is
computed here.  make_srt.py walks the same document for its cue
windows, so the picture and the captions are paced by the same numbers
by construction rather than by coincidence.  This module's job is to
make the CONTAINER agree with those numbers too, and then to prove it
did by measuring the finished file and printing the comparison.

*** THE REPEATED FINAL file ENTRY IS NOT OPTIONAL ***
The last entry's duration line does not take effect unless its file
line is repeated once more afterwards with no duration of its own.
That is the canonical concat demuxer idiom for variable per-image
durations, and omitting it truncates the container while every other
count still matches -- which is the single easiest way to ruin the film
silently, because every caption past the shortfall then points beyond
the end of the video.  Measured on this host with -bf 0 on a 134.000 s
timeline: 134.040 s with the repeated entry, 133.800 s without it.  So
the file line count must be exactly the duration line count PLUS ONE,
and :func:`concat_counts` asserts that on the bytes that were written.

*** -bf 0 IS LOAD-BEARING, NOT A TUNING CHOICE ***
libx264's default B-frame reorder delay leaves the final DTS behind the
final PTS, and the mov muxer derives the track duration from the DTS
timeline.  Under -fps_mode vfr, where the PTS deltas are wildly
uneven, that loses the trailing frames' durations outright.  Measured
on this host, ffmpeg 7.1.1: an 11.250 s three-image timeline whose PTS
came out perfectly (0, 0.24, 1.24, 11.24) reported a container duration
of 1.520 s, and a realistic 134.000 s timeline with two transition
groups reported 129.800 s -- 4.2 s short, silently.  Setting
-video_track_timescale does not help; -bf 0 fixes it exactly (11.280 s
and 134.040 s).  A slideshow of static captures gains essentially
nothing from B-frames, and their reorder delay is precisely what
corrupts the timing, so they are switched off.  Without this the
mandated container-versus-timeline comparison could not be satisfied at
all.

*** A CONCAT ENTRY RESOLVES AGAINST THE LIST'S OWN DIRECTORY ***
ffmpeg joins a relative concat entry onto the directory of the LIST
FILE, not onto the process working directory.  Reproduced on this host:
a list at pt/build/concat.txt holding "file 'pt/frames/a.png'", run
with the root as the working directory, fails with

    Impossible to open 'pt/build/pt/frames/a.png'

Piping the list is no escape -- with the list on standard input the
base becomes "fd:" and the entries come out as 'fd:pt/frames/a.png' --
and the demuxer exposes no base-directory option (ffmpeg -h
demuxer=concat offers only safe, auto_convert and
segment_time_metadata).

So the entries are spelled relative to THE LIST FILE'S OWN DIRECTORY,
which is the base the demuxer actually resolves against: `../frames/...`
for a capture and `transitions/...` for a transition frame.  That form
means the same thing in every checkout AND is the form ffmpeg can
resolve, so there is one list rather than two and THE COMMITTED LIST IS
THE FILE THE ENCODER IS HANDED.  Anyone who checks the repository out
can re-run the encode from the committed artifact and get the same film.

The list is verified before it is used rather than trusted: every entry
is resolved back from the bytes on disk and the sequence must equal the
plan's paths plus the repeated final entry.  A short write, a corrupted
entry, or one pointing outside playthrough/frames/ or
playthrough/build/transitions/ stops the encode.  Nothing this module
writes into playthrough/ is ever anything but the two committed
artifacts, so a crashed run cannot leave a scratch file behind for
commit_artifacts.sh to stage.

FAIL LOUDLY, NEVER SILENTLY
A missing frame, a duration outside the clamp, a flagged entry whose
twelve transition frames are not on disk, a malformed timeline, a
truncated container: each aborts with the numbers in the message.  A
missing frame is never skipped -- skipping preserves the appearance of
success while breaking the one-frame-per-keystroke invariant and
shifting every caption after it.

NO DECIMATION, NO FABRICATION, NO BURNED-IN TEXT
Every captured frame appears in the list exactly once, at full
resolution.  Nothing is sampled, deduplicated, downscaled or
recompressed to save space or time, and no frame is duplicated to pad a
duration -- the duration line does that.  The film contains only the
captures and the declared transition imagery, in timeline order.  No
filter graph is ever built: the captions are muxed as a SELECTABLE
mov_text track by embed_captions.sh, and burning them into pixels is
forbidden.  There is no audio input, so the container carries no audio
stream.

USE
    python3 -B playthrough/tooling/render_movie.py
    python3 -B playthrough/tooling/render_movie.py --concat-only
    python3 -B playthrough/tooling/render_movie.py --timeline PATH

    import render_movie
    plan = render_movie.plan_render(document)
    text = render_movie.format_concat_list(plan)

Re-running is idempotent: the same timeline and the same frames produce
a byte-identical concat list and a fresh encode of it.

Standard library only, plus the sibling timeline and make_transitions
modules.  Nothing here needs playthrough/tooling/requirements.txt: this
module orchestrates ffmpeg and touches no pixels, so the film can be
re-encoded and re-measured in any checkout that has ffmpeg.
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from decimal import Decimal
from typing import (Any, Dict, List, Mapping, NamedTuple, Optional,
                    Sequence, Tuple)

# Set BEFORE the sibling imports below, which are the only imports here
# that can write into the repository working tree.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1, but this module is documented as runnable
# on its own, and a standalone invocation without that environment would
# compile the siblings to playthrough/tooling/__pycache__/ -- which
# .gitignore's terminal `!/playthrough/**` negation then makes
# COMMITTABLE.  A stray .pyc in a committed evidence tree is an artifact
# nobody authored.  The flag must precede the imports it protects,
# because the interpreter consults it at compile time; every documented
# command also passes -B.
sys.dont_write_bytecode = True

try:
    # The clamp constants, the arithmetic tolerance, the millisecond
    # rounding, the invariant total, the hardened reader, the
    # containment root, the artifact layout and the document validator
    # all live in the sibling module.  Importing them is what keeps the
    # numbers this film is paced by from existing twice and drifting
    # apart.
    from timeline import (CEIL, EPSILON, FLOOR, GENERATION_VERSION,
                          ArtifactLock, TimelineError, approved_root,
                          assert_timeline_document,
                          clear_generation_journal,
                          default_timeline_path, file_digest,
                          fsync_directory,
                          generation_journal_problems, read_timeline,
                          round_seconds, timeline_total,
                          write_generation_journal)
except ImportError:
    # Imported from somewhere other than this directory: put the
    # tooling directory on the path and try once more.  A second
    # failure is a genuinely broken checkout and is allowed to raise.
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from timeline import (CEIL, EPSILON, FLOOR, GENERATION_VERSION,
                          ArtifactLock, TimelineError, approved_root,
                          assert_timeline_document,
                          clear_generation_journal,
                          default_timeline_path, file_digest,
                          fsync_directory,
                          generation_journal_problems, read_timeline,
                          round_seconds, timeline_total,
                          write_generation_journal)

try:
    # The transition naming, the group size, the capture-path validator
    # and the frame geometry come from the module that WROTE the
    # transition frames, so the renderer cannot hold a different
    # opinion about what they are called or how many there are.  That
    # module's own third-party imports are soft, so this costs nothing
    # when moviepy, numpy and Pillow are absent -- as they are wherever
    # only a re-encode is wanted.
    import make_transitions
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    import make_transitions


# ---------------------------------------------------------------------
# The encode.  Every value here is a decision with a reason, and the
# reasons are recorded beside them because a flag nobody can justify is
# a flag somebody will eventually "clean up".
# ---------------------------------------------------------------------

# The demuxer, and relative-or-absolute entries permitted.  Safe mode
# rejects an absolute entry outright -- measured: "Unsafe file name
# '/.../frames/a.png'" -- and the encode list is absolute by
# construction (see the module docstring), so this is required rather
# than merely convenient.
CONCAT_FORMAT = "concat"
CONCAT_SAFE = "0"

# Variable frame rate.  This is what makes ffmpeg honour the per-image
# duration lines instead of resampling them onto a constant grid, and
# it is therefore the flag the whole diegetic-pacing requirement rests
# on.
#
# NOTHING MAY SET AN OUTPUT FRAME RATE ALONGSIDE IT.  ffmpeg refuses
# the combination outright -- "One of -r/-fpsmax was specified together
# a non-CFR -vsync/-fps_mode.  This is contradictory." and exit 234 --
# so an output frame rate added "for safety" does not degrade the film,
# it prevents the film.  There is deliberately no way to reach one from
# this module's command line.
FPS_MODE = "vfr"

# See "-bf 0 IS LOAD-BEARING" in the module docstring.  Zero B-frames
# means DTS equals PTS, which is the only way the mov muxer can write a
# track duration that matches the timeline.
BFRAMES = "0"

# Broad player compatibility; a research finding rather than a
# preference.  4:2:0 8-bit is what every hardware decoder accepts.
PIXEL_FORMAT = "yuv420p"

# The codec the acceptance gate names: ffprobe must report h264.
VIDEO_CODEC = "libx264"

# Constant-quality rather than a bitrate target, because the film is a
# slideshow of text-heavy screenshots whose bitrate demand varies
# enormously between a menu and a lit street.
CRF = "20"

# The moov atom at the front, so the container starts playing without
# reading to the end of a file that is mostly PNG-derived keyframes.
MOVFLAGS = "+faststart"

# Overwrite without asking.  Re-running the renderer is a normal thing
# to do and must not block on a prompt in a pipeline.
OVERWRITE = "-y"

# Only errors on stderr.  The per-frame progress chatter would bury the
# one line that matters when something is wrong.
LOGLEVEL = "error"

# ffprobe's machine-readable form.  JSON is parsed rather than scraped,
# so a field that is absent is absent rather than mistaken for the next
# one along.
PROBE_FORMAT = "json"

# Wall-clock ceilings for the two children this module runs.  A hung
# tool is a fault to REPORT: without a limit, one unresolvable entry in
# the concat list leaves ffmpeg waiting forever and the pipeline -- one
# sequential script -- stops with no diagnosis at all.
#
# The two limits are asymmetric for a structural reason rather than a
# measured one: the encode is a full libx264 pass over every entry in
# the concat list at 1920x1080, so its cost grows with the length of the
# session, while the probe reads container metadata and decodes nothing,
# so its cost is independent of the film.  Neither value is a
# performance budget.  Both are outer bounds, far enough above anything
# this pipeline can produce that reaching one means the child is stuck
# rather than slow -- which is why no figure from a particular session
# is written here: it would go stale the moment the capture set is
# replaced, and the bound does not depend on it.  The film's real
# duration is measured after the encode and compared against
# timeline.json, which is where that number belongs.
ENCODE_TIMEOUT = 3600.0
PROBE_TIMEOUT = 120.0

# The stream facts the gate asserts.
CODEC_NAME_H264 = "h264"
CODEC_TYPE_VIDEO = "video"
CODEC_TYPE_AUDIO = "audio"

# A container smaller than this is a header and nothing else.  A single
# 1920x1080 keyframe of real screen content measures tens of kilobytes,
# and the smallest film this pipeline can produce is one frame, so four
# kilobytes is comfortably below anything legitimate and comfortably
# above an empty or truncated write.
MIN_OUTPUT_BYTES = 4096

# ---------------------------------------------------------------------
# THE ENCODER TOLERANCE, DERIVED FROM MEASUREMENT RATHER THAN CHOSEN
#
# The container duration cannot equal the timeline total exactly, and
# the reason is arithmetic rather than sloppiness.  A concat list of
# images is demuxed through image2, whose default frame rate gives the
# input a 1/25 s timebase, so each entry's cumulative presentation time
# is rounded once onto that grid -- deviation at most half a step, and
# NOT cumulative, because the running sum is what gets rounded and not
# each addend.  The repeated final entry then contributes its own
# default 1/25 = 0.04 s packet on the end.  So
#
#     container - timeline_total  is in  [+0.02, +0.06]
#
# deterministically, whatever the length of the film.  Measured on this
# host: 11.250 -> 11.280 (+0.03), 134.000 -> 134.040 (+0.04), and a
# 396-entry 570.500 s stress list -> 570.560 (+0.06), whose worst
# per-entry deviation from the exact cumulative sum was +0.020 s.
#
# The failure this comparison exists to catch is much larger and has
# the opposite sign.  Dropping the repeated final entry loses the last
# entry's whole duration, and the smallest duration the timeline can
# carry is the floor, so the shortfall is at least
# FLOOR - 0.06 = 0.19 s.  Measured: 134.000 -> 133.800.
#
# 0.12 s therefore sits between the two: twice the largest honest
# quantisation and comfortably inside the smallest possible truncation.
# It is a tolerance on the ENCODER, not on the arithmetic; EPSILON is
# what the arithmetic is held to.
# ---------------------------------------------------------------------
DURATION_TOLERANCE = 0.12

# A tolerance wider than this blunts the gate past the point of meaning
# anything, so asking for one is reported.  An operator on a different
# ffmpeg may legitimately need a little more room than the measured
# 0.12 s, so it is not refused here -- but it is never granted quietly.
TOLERANCE_ADVISORY = 0.25

# AND THIS IS WHERE IT STOPS BEING A TOLERANCE.  Past this the check no
# longer distinguishes an encoder's rounding from a container that lost
# an entry, and the duration comparison is the ONLY gate that can catch
# a truncated film: the frame count still matches, every capture is
# present, and only the length is wrong.  A caller that could pass
# --tolerance 3600 could therefore publish a film whose captions run off
# the end of it while every check reported success.
#
# One second is deliberately far wider than any real encoder rounding --
# the measured worst case on this host is 0.12 s -- and still narrower
# than the 0.25 s FLOOR of a single frame's on-screen time, so a film
# missing even one frame's worth of duration cannot hide beneath it.
TOLERANCE_CEILING = 1.0

# ---------------------------------------------------------------------
# The concat list's shape.  Spelled as constants because the writer and
# the reader of these bytes are both in this file and must not drift,
# and because the committed list is verified by re-reading them.
# ---------------------------------------------------------------------
CONCAT_FILE_PREFIX = "file '"
CONCAT_FILE_SUFFIX = "'"
CONCAT_DURATION_PREFIX = "duration "

# The list is written with LF endings and a single trailing newline,
# whatever the platform, because it is a committed text artifact and a
# diff of it should show a changed frame rather than a changed line
# ending.
CONCAT_NEWLINE = "\n"

# The separator inside a concat entry.  Always a forward slash, even
# though os.sep would be one here anyway: the list is committed, and a
# committed artifact should not record which platform wrote it.
CONCAT_SEPARATOR = "/"

# What an entry in the plan is.  A capture is one keystroke's evidence;
# a transition frame is declared, derived imagery that make_transitions
# composed.  Keeping them distinguishable is what lets the summary
# report both counts, and what lets the group arithmetic be asserted
# separately from the capture arithmetic.
KIND_CAPTURE = "capture"
KIND_TRANSITION = "transition"

# An ordinal only a transition frame has.  A capture is not part of a
# group, and -1 says so without pretending it is the zeroth member of
# one.
NO_ORDINAL = -1

# ---------------------------------------------------------------------
# The artifact layout.  env.sh is the single definition of it; these are
# the two variables that name what this module writes, plus the prefix
# it resolves its two tools through.
# ---------------------------------------------------------------------
ENV_CONCAT_LIST = "PLAYTHROUGH_CONCAT_LIST"
ENV_MOVIE = "PLAYTHROUGH_MOVIE"
TOOL_ENV_PREFIX = "PLAYTHROUGH_BIN_"

# Where the two artifacts land when nothing nominates them, relative to
# the playthrough directory.  Joined from literal components, never
# concatenated from anything a caller supplied.  The `build` component
# names the ONLY directory this module ever creates: make_transitions.py
# owns build/transitions/, this module owns build/concat.txt, and
# creating that parent is the whole of its directory management.
CONCAT_REL_PARTS = ("build", "concat.txt")
MOVIE_REL_PARTS = ("cata-play.mp4",)

# The same two paths spelled for a human, so a refusal names them the
# way the AAP and playthrough/README.md do.
CONCAT_REL_DESC = "playthrough/" + "/".join(CONCAT_REL_PARTS)
MOVIE_REL_DESC = "playthrough/" + "/".join(MOVIE_REL_PARTS)

# The container extension.  Required, because -movflags +faststart and
# the mov_text caption track embed_captions.sh adds later are both MP4
# facts: a different extension would select a different muxer and the
# caption stage would then fail on a file this stage called a success.
MOVIE_SUFFIX = ".mp4"

# The two tools, named once.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Exit statuses.  run_pipeline.sh reads nothing else, so a wrong status
# is a whole stage that appears to have worked.
EXIT_OK = 0
EXIT_FAILED = 1

# ---------------------------------------------------------------------
# THE TRUST GATE
#
# The film is a COMMITTED artifact, so it is evidence in exactly the
# sense a kept frame is -- and a security review found that the
# end-of-life platform waiver did not force the diagnostic state, leaving
# capture and mux "eligible as trusted production evidence despite
# known-unpatched parser/X risks".  It is a registered trust bypass now,
# capture.sh and launch_game.sh refuse under it, embed_captions.sh
# refuses the mux under it, and this module refuses the encode.
#
# THE ANSWER COMES FROM env.sh, NOT FROM A VARIABLE.  Reading an exported
# PLAYTHROUGH_TRUST_STATE would be a control a caller defeats by
# exporting the word "trusted", and recomputing the state here would put
# a second, drifting implementation of it in the tree.  So the decision
# is delegated to the one file that owns it, in a subshell, per render --
# a few tens of milliseconds against an encode measured in minutes.
#
# AND IT APPLIES WHERE EVIDENCE CAN BE PUBLISHED.  A render into a tree
# git does not track cannot be committed and is not evidence -- that is
# every test in this suite, which renders into a temporary root -- so the
# gate runs when the destination root IS a git working tree.  The same
# verified discriminator env.sh uses for its platform source, and for the
# same reason: it is a property of the tree rather than a claim a caller
# makes about itself.
ENV_SCRIPT_REL_PARTS = ("playthrough", "tooling", "env.sh")
TRUST_CONTEXT = "the film render"
TRUST_TIMEOUT = 60
# Sourced, then asked BOTH questions, in embed_captions.sh's own order:
# is this platform still receiving security fixes, and is any check
# relaxed?  Both are required and neither implies the other -- an
# unwaived end-of-life host is "trusted" until something calls the
# platform check, and a waived one is in support of nothing.  The path
# arrives as $1 so nothing is interpolated into the program text, and
# stdout is discarded because env.sh's summary is not this module's
# business; only the status and stderr are.
TRUST_PROGRAM = (
    'set +e\n'
    '. "$1" >/dev/null 2>&1 || exit 97\n'
    'playthrough_check_platform || exit 96\n'
    'playthrough_assert_trusted "$2" || exit 98\n'
    'exit 0\n'
)
TRUST_EXIT_UNSOURCEABLE = 97
TRUST_EXIT_PLATFORM = 96


class RenderError(Exception):
    """The film cannot be rendered honestly from these inputs.

    Raised in place of encoding something that would be wrong: a
    missing frame, a duration the timeline should never have produced,
    a flagged entry with no transition frames on disk, a path that
    resolves outside the tree, or a container whose length does not
    match the numbers the captions were written from.  A wrong film is
    worse than no film, because it looks like a right one.
    """


def _warn(message: str) -> None:
    """Report something an operator must see but that is not fatal.

    The level is stated, and the prefix matches playthrough_warn() in
    playthrough/tooling/env.sh and every sibling module, so an advisory
    cannot be read as the fatal error it sits next to in the log.
    """
    print("playthrough: WARNING: render_movie.py: %s" % message,
          file=sys.stderr)


class ConcatEntry(NamedTuple):
    """One image entry of the concat list.

    `path` is absolute and has already been proved to lie inside the
    directory its `kind` belongs to.  `relative` is the same file
    spelled relative to the render root with forward slashes, which is
    the form the committed list carries.  `duration` is the seconds this
    image occupies on screen -- read from the timeline for a capture,
    and the group's share of the transition second for a transition
    frame.  `frame` is the capture index the entry is or follows, and
    `ordinal` places a transition frame within its group.
    """

    path: str
    relative: str
    duration: float
    kind: str
    frame: int
    ordinal: int


class Plan(NamedTuple):
    """Everything the encode needs, resolved and checked.

    Built before a byte is written, so a defect in the timeline or a
    missing file stops the run while the previous artifacts are still
    intact.  `expected_total` is sum(durations) + sum(transitions)
    computed from the entries; `declared_total` is what the document
    says the same quantity is, or None for a bare array.  They are
    compared rather than assumed equal.
    """

    entries: List[ConcatEntry]
    capture_count: int
    group_count: int
    transition_seconds: float
    expected_total: float
    declared_total: Optional[float]
    width: int
    height: int


class Probe(NamedTuple):
    """What ffprobe measured about the finished container."""

    duration: Optional[float]
    video_streams: int
    audio_streams: int
    codec_name: Optional[str]
    width: Optional[int]
    height: Optional[int]
    size: int
    # The number of coded pictures, preferring the demuxed packet count
    # and falling back to the header's nb_frames, which is the weaker
    # source and is frequently absent under VFR.  None when neither
    # could be taken -- a count that could not be measured is reported
    # as absent rather than guessed at.
    frames: Optional[int] = None
    # The file these measurements were taken FROM, which during a render
    # is the staging sibling and not the published movie.  It travels with
    # the measurements so the generation manifest hashes the same bytes
    # that were verified: the publish step renames them rather than
    # rewriting them, so the digest holds either side of the switch.
    path: str = ""


# ---------------------------------------------------------------------
# Paths.  Every one is either joined from module-level literal
# components onto a directory that has already been validated, or
# arrives from the timeline, the environment or the command line and is
# resolved and PROVED to be inside the tree it belongs to before it is
# opened or written into the list.  That is what keeps this module clear
# of the unvalidated-path-join pattern the repository's CodeQL python leg
# gates on [.github/workflows/codeql-analysis.yml:35].
# ---------------------------------------------------------------------

def _join(base: str, parts: Sequence[str]) -> str:
    """Join literal path components onto a base directory."""
    return os.path.normpath(os.path.join(base, *parts))


def _module_dir() -> str:
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _approved_root(root: Optional[str] = None) -> str:
    """Return the only tree this module may read from or write into.

    Delegated to timeline.approved_root() rather than reimplemented, so
    the renderer, the caption generator and the transition composer
    cannot end up with three opinions about where an artifact may live.
    It resolves to playthrough/ from the module's own location and NEVER
    from the environment; `root` is a call site's argument so that a
    test can hold the same rules against a directory it owns.
    """
    try:
        return approved_root(root)
    except TimelineError as err:
        raise RenderError(str(err)) from err


def _publishable_root(root: Optional[str] = None) -> Optional[str]:
    """Return the repository root when a render there could be committed.

    ``None`` when it could not -- when the tree is not a git working
    tree, which is what a temporary render root is.  The distinction is
    the whole basis of the trust gate: an artifact that cannot be
    committed cannot become evidence, and the pipeline's integrity claim
    is about committed artifacts (R1, R3).
    """
    base = os.path.dirname(_approved_root(root))
    return base if os.path.exists(os.path.join(base, ".git")) else None


def assert_trusted_render(root: Optional[str] = None) -> Optional[str]:
    """Refuse the encode while the trust state is diagnostic.

    Returns the repository root the gate ran against, or ``None`` when it
    did not apply.  Raises :class:`RenderError` when the state is
    diagnostic, and ALSO when the answer cannot be obtained at all: a
    gate that cannot run stops the run, because "I could not ask" and
    "the answer was no" leave the same film unattested.

    The reason is env.sh's own, quoted verbatim, so an operator reads the
    same sentence here that capture.sh and embed_captions.sh print.
    """
    base = _publishable_root(root)
    if base is None:
        return None
    script = os.path.join(base, *ENV_SCRIPT_REL_PARTS)
    if not os.path.isfile(script):
        raise RenderError(
            "there is no %s, so the trust state this film would be "
            "encoded under cannot be established.  The check is not "
            "skipped: a film produced while a security check was "
            "relaxed is not evidence, and this render would be "
            "committed" % "/".join(ENV_SCRIPT_REL_PARTS))
    try:
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", TRUST_PROGRAM,
             "bash", script, TRUST_CONTEXT],
            cwd=base, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=TRUST_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as err:
        raise RenderError(
            "the trust state could not be established (%s), so the "
            "encode is refused rather than run without it" % err) from err
    if result.returncode == 0:
        return base
    detail = result.stderr.decode("utf-8", "replace").strip()
    if result.returncode == TRUST_EXIT_UNSOURCEABLE:
        raise RenderError(
            "%s could not be sourced, so the trust state this film "
            "would be encoded under is unknown and the encode is "
            "refused.  %s" % (script, detail or "No output."))
    if result.returncode == TRUST_EXIT_PLATFORM:
        raise RenderError(
            "REFUSING to encode the film on this platform.  %s"
            % (detail or "No output."))
    raise RenderError(
        "REFUSING to encode the film while the trust state is "
        "diagnostic.  %s" % (detail or "No output."))


def render_root(root: Optional[str] = None) -> str:
    """Return the directory a concat entry is spelled relative to.

    The parent of the approved root -- the repository root in a real
    checkout -- because that is exactly what the timeline's own
    "playthrough/frames/frame_00001.png" is relative to, and what
    make_transitions._validated_image_path() resolves such a value
    against.  Deriving it from the approved root rather than from
    $PLAYTHROUGH_REPO_ROOT keeps one answer to "relative to what"
    instead of two that could disagree.

    This is also the working directory ffmpeg is given, so that the
    committed list means the same thing to a reader and to the encoder.
    """
    return os.path.dirname(_approved_root(root))


def _resolved(path: str) -> str:
    """Return `path` absolute and fully symlink-resolved."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def _within(path: str, directory: str) -> bool:
    """Return True when `path` is `directory` or lies beneath it.

    Both sides are expected to be fully resolved already, so neither a
    `..` segment nor a symlink can smuggle a path past the test.
    """
    return path == directory or path.startswith(directory + os.sep)


def _validated_path_value(value: Any, label: str) -> str:
    """Return `value` as an absolute, resolved path, or raise.

    Shape only: a non-empty string or os.PathLike with no NUL byte.
    Where it is allowed to point is a separate question asked
    separately, because a well-formed path aimed somewhere it may not go
    needs a different diagnostic from a malformed one.
    """
    if value is None:
        raise RenderError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise RenderError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise RenderError("%s must not be empty" % label)
    if "\x00" in value:
        raise RenderError("%s must not contain a NUL byte" % label)
    return _resolved(value)


def _validated_output(
    value: Any,
    label: str,
    suffix: Optional[str] = None,
    root: Optional[str] = None,
) -> str:
    """Return an absolute path this module is allowed to write.

    Four rules, each closing a different way a write could land
    somewhere it must not.  The path must resolve inside the approved
    root, because both products are committed artifacts of this session
    and an artifact written outside the tree is one nobody can audit.
    It must NOT resolve inside playthrough/frames/: that directory holds
    exactly one PNG per keystroke and nothing else, and a stray file
    there would break the frame-count equals manifest-line-count
    identity the one-frame-per-keystroke gate rests on.  It must not
    already be something other than a regular file, so a directory, a
    FIFO or a device node is refused rather than written to.  And when a
    suffix is required it must carry it, because the container format is
    selected by extension.
    """
    resolved = _validated_path_value(value, label)
    approved = _approved_root(root)
    if not _within(resolved, approved):
        raise RenderError(
            "%s must stay inside %s, but %s resolves to %s.  Both "
            "products of this stage are committed artifacts of the "
            "session and belong in the working tree with everything "
            "else." % (label, approved, value, resolved))
    captures = _captures_dir(root)
    if _within(resolved, captures):
        raise RenderError(
            "%s resolves to %s, which is inside the capture directory "
            "%s.  Refused: that directory holds exactly one PNG per "
            "keystroke and nothing else, and anything else there would "
            "break the frame-count equals manifest-line-count identity "
            "the one-frame-per-keystroke gate rests on."
            % (label, resolved, captures))
    if os.path.islink(resolved):
        raise RenderError(
            "%s is a symbolic link: %s.  This module publishes by "
            "renaming a verified file into place, so a link here would "
            "be replaced rather than followed -- and a link is not "
            "something this pipeline ever writes."
            % (label, resolved))
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise RenderError(
            "%s is not a regular file: %s" % (label, resolved))
    if suffix is not None and not resolved.lower().endswith(suffix):
        raise RenderError(
            "%s must name a %s file, got %s.  The container format is "
            "chosen by extension, and the caption track embed_captions."
            "sh adds later is an MP4 feature."
            % (label, suffix, resolved))
    _assert_canonical_destination(resolved, label, root)
    return resolved


def _assert_canonical_destination(
    resolved: str,
    label: str,
    root: Optional[str] = None,
) -> None:
    """Refuse anything but this stage's two exact destinations.

    CONTAINMENT IS NOT ENOUGH, and this is the gap it leaves.  Every
    artifact this pipeline produces lives under playthrough/, so a rule
    that only says "inside the approved root, and not in frames/" still
    accepts playthrough/manifest.jsonl, playthrough/timeline.json,
    playthrough/transcript.srt and anything under playthrough/userdir/.
    A --output or a $PLAYTHROUGH_MOVIE naming one of those would have an
    h264 stream written over the session's own evidence -- the manifest
    that every count is derived from, the timeline that both this module
    and make_srt.py read as the single source of truth, or the save the
    engine wrote.  The write would report success and the loss would
    surface, much later, as some unrelated stage failing to parse a file.

    So the destinations are ENUMERATED rather than merely bounded: this
    module writes playthrough/build/concat.txt and
    playthrough/cata-play.mp4, and nothing else, ever.  The comparison
    is on the resolved path so a checkout reached through a symlinked
    ancestor still matches, and the permitted set is built from the same
    REL_PARTS constants the defaults are built from, so the two cannot
    drift apart.

    $PLAYTHROUGH_MOVIE and $PLAYTHROUGH_CONCAT_LIST therefore no longer
    relocate these artifacts.  That is the intended loss: they are
    committed evidence with one place to live, and env.sh exports them
    so that every stage AGREES about where that place is -- not so that
    it can be moved.
    """
    approved = _approved_root(root)
    permitted = {
        _resolved(_join(approved, CONCAT_REL_PARTS)): CONCAT_REL_DESC,
        _resolved(_join(approved, MOVIE_REL_PARTS)): MOVIE_REL_DESC,
    }
    if _resolved(resolved) in permitted:
        return
    raise RenderError(
        "%s resolves to %s, which is not one of this stage's two "
        "destinations.  It writes %s and %s and nothing else: every "
        "other path under playthrough/ is either a session's evidence "
        "(the manifest, the timeline, the transcript, the save) or a "
        "capture, and an h264 stream written over any of them would "
        "report success and destroy the record."
        % (label, resolved, CONCAT_REL_DESC, MOVIE_REL_DESC))


def _captures_dir(root: Optional[str] = None) -> str:
    """Return the capture directory, through its own owner.

    make_transitions.frames_dir() honours $PLAYTHROUGH_FRAMES_DIR and
    proves the result is inside the approved root; borrowing it keeps
    the renderer and the transition composer reading the same
    directory, which matters because both resolve timeline paths
    against it.
    """
    try:
        return make_transitions.frames_dir(root)
    except make_transitions.TransitionError as err:
        raise RenderError(str(err)) from err


def _transitions_dir(root: Optional[str] = None) -> str:
    """Return the derived-frame directory, through its own owner."""
    try:
        return make_transitions.default_transitions_dir(root)
    except make_transitions.TransitionError as err:
        raise RenderError(str(err)) from err


def default_concat_path(root: Optional[str] = None) -> str:
    """Return the concat list this module writes.

    $PLAYTHROUGH_CONCAT_LIST from playthrough/tooling/env.sh wins,
    because env.sh is the single definition of the artifact layout and a
    clone-indexed run must not write over another clone's list.
    Otherwise playthrough/build/concat.txt, joined from literal
    components onto the approved root so the module is still correct
    when nothing has been sourced.
    """
    from_env = os.environ.get(ENV_CONCAT_LIST)
    if from_env and from_env.strip():
        return _validated_output(
            from_env, "$" + ENV_CONCAT_LIST, root=root)
    return _validated_output(
        _join(_approved_root(root), CONCAT_REL_PARTS),
        "the concat list", root=root)


def default_movie_path(root: Optional[str] = None) -> str:
    """Return the movie this module encodes.

    $PLAYTHROUGH_MOVIE from playthrough/tooling/env.sh wins, for the
    same reason; otherwise playthrough/cata-play.mp4.
    """
    from_env = os.environ.get(ENV_MOVIE)
    if from_env and from_env.strip():
        return _validated_output(
            from_env, "$" + ENV_MOVIE, MOVIE_SUFFIX, root)
    return _validated_output(
        _join(_approved_root(root), MOVIE_REL_PARTS),
        "the movie", MOVIE_SUFFIX, root)


def _relative_entry(absolute: str, base: str) -> str:
    """Return `absolute` as a concat entry relative to `base`.

    `base` IS THE DIRECTORY THE LIST FILE ITSELF SITS IN, because that
    is the directory ffmpeg's concat demuxer resolves a relative entry
    against -- not the working directory the encoder is launched from.
    Measured: a list in playthrough/build/ carrying
    `playthrough/frames/frame_00001.png` makes ffmpeg open
    `playthrough/build/playthrough/frames/frame_00001.png` and fail with
    "Impossible to open".  So the committed list carries `../frames/...`
    for a capture and `transitions/...` for a transition frame, and the
    committed list is therefore the file the encoder is handed.

    An entry may climb out of `base` -- `../frames/` is the normal
    spelling for a capture -- so climbing is not what is checked here.
    Containment is established before this function is reached:
    validated_capture_path() proves a capture lies inside
    playthrough/frames/, _assert_group() proves a transition frame lies
    inside playthrough/build/transitions/, and _absolute_entry() proves
    it again on the way back. An ABSOLUTE result is still refused,
    because it would make the committed list depend on this checkout's
    location.  A single quote is refused too: the concat script format
    has no way to escape one inside a single-quoted entry, so a path
    containing one could not be expressed at all and must not be
    silently mangled into something that parses as a different file.
    """
    relative = os.path.relpath(absolute, base)
    if os.path.isabs(relative):
        raise RenderError(
            "%s cannot be spelled relative to the concat list's own "
            "directory %s (relpath gave the absolute %s), so it cannot "
            "be written as a list-relative concat entry"
            % (absolute, base, relative))
    entry = relative.replace(os.sep, CONCAT_SEPARATOR)
    if CONCAT_FILE_SUFFIX in entry:
        raise RenderError(
            "%s contains a single quote, which the concat script "
            "format cannot express inside a quoted entry: %s"
            % (absolute, entry))
    return entry


def _assert_entry_size(path: str, width: int, height: int) -> None:
    """Refuse an image that is not the size the film is cut at.

    THE ENCODER WOULD OTHERWISE HIDE THIS.  The command carries
    `-s WIDTHxHEIGHT`, so an image of any other size is silently
    RESCALED into the film rather than rejected: a capture taken at the
    game window's 1920x1072 instead of the X root's 1920x1080, or a
    transition frame composed against a different geometry, would be
    stretched and the container would still probe at the right
    resolution with every count matching.

    Read from the IHDR chunk, so no decoder runs on a file that only
    claims to be a PNG -- see make_transitions._image_size() for why
    that matters with Pillow pinned below 12.
    """
    try:
        actual = make_transitions._image_size(path)
    except make_transitions.TransitionError as err:
        raise RenderError(
            "%s cannot go into the film: %s" % (path, err)) from err
    if actual != (width, height):
        raise RenderError(
            "%s is %dx%d, not the %dx%d the film is cut at.  The "
            "encoder's -s flag would rescale it silently, so it is "
            "refused before the concat list is written."
            % (path, actual[0], actual[1], width, height))


def _absolute_entry(
    relative: str,
    base: str,
    allowed: Sequence[str],
) -> str:
    """Return a committed entry made absolute for the encoder.

    The value arrives from bytes this module wrote and read back, which
    is to say from the filesystem, so it is treated as untrusted all the
    same: it must be relative, free of a NUL byte and of a quote, and
    the joined result must resolve inside one of the directories the
    film is allowed to draw imagery from.  Nothing else can reach the
    encoder's input list.
    """
    if not relative or "\x00" in relative:
        raise RenderError(
            "a concat entry must be non-empty and free of NUL bytes")
    if CONCAT_FILE_SUFFIX in relative:
        raise RenderError(
            "a concat entry must not contain a single quote: %s"
            % relative)
    if os.path.isabs(relative) or relative.startswith(CONCAT_SEPARATOR):
        raise RenderError(
            "the committed concat list must hold relative entries, got "
            "%s" % relative)
    joined = _join(base, relative.split(CONCAT_SEPARATOR))
    resolved = _resolved(joined)
    if not any(_within(resolved, directory) for directory in allowed):
        raise RenderError(
            "the concat entry %s resolves to %s, which is outside %s.  "
            "A frame in the film has to be a frame of this session or "
            "a transition this pipeline composed."
            % (relative, resolved, " and ".join(allowed)))
    if not os.path.isfile(resolved):
        raise RenderError(
            "the concat entry %s names %s, which is not there"
            % (relative, resolved))
    return joined


# ---------------------------------------------------------------------
# The toolchain.  Two binaries, resolved the way ocr_clock.py resolves
# its own: env.sh's already-checked $PLAYTHROUGH_BIN_<NAME> is preferred
# so that this module and the shell stages run the same file, and PATH
# is searched only when nothing nominated one.
# ---------------------------------------------------------------------

def _tool_env_var(name: str) -> str:
    """Return env.sh's exported variable name for a tool."""
    safe = "".join(
        char if char.isalnum() else "_" for char in name)
    return TOOL_ENV_PREFIX + safe.upper()


def verified_tool(name: str) -> str:
    """Return an absolute, executable path for the tool called `name`.

    :raises RenderError: when the tool is absent or is not executable.
        The message names the package, because "FileNotFoundError:
        'ffmpeg'" tells an operator nothing about what to install.
    """
    from_env = os.environ.get(_tool_env_var(name), "").strip()
    if from_env and os.path.isabs(from_env):
        candidate: Optional[str] = from_env
        origin = "$%s" % _tool_env_var(name)
    else:
        candidate = shutil.which(name)
        origin = "PATH"
    if not candidate:
        raise RenderError(
            "%s was not found on %s.  The render toolchain is listed "
            "in playthrough/tooling/requirements.txt; on this host both "
            "%s and %s come from the ffmpeg package."
            % (name, origin, FFMPEG, FFPROBE))
    real = os.path.realpath(candidate)
    if not os.path.isfile(real) or not os.access(real, os.X_OK):
        raise RenderError(
            "%s from %s is not an executable file: %s"
            % (name, origin, candidate))
    _assert_trustworthy_tool(real, name, origin)
    # The RESOLVED path is returned, not the name that reached it.  What
    # gets executed is then the file that was actually inspected, rather
    # than a name that could resolve differently a moment later.
    return real


def _assert_trustworthy_tool(real: str, name: str, origin: str) -> None:
    """Refuse an encoder that somebody else could have replaced.

    `os.access(X_OK)` says only "this is executable" -- it says nothing
    about WHO can rewrite it.  This module runs whatever
    $PLAYTHROUGH_BIN_FFMPEG names, and every frame of the committed film
    passes through it, so an ffmpeg in a world-writable directory, or one
    owned by another unprivileged account, is a binary any local process
    can swap for its own before the render.  The film would then be
    produced by something nobody inspected, and it would look exactly
    like a successful run.

    Three properties, checked on the RESOLVED path and on every ancestor
    directory of it:

      * the file is a regular file, not a device or a socket;
      * it is owned by root or by this uid -- nobody else's to rewrite;
      * neither it nor any directory on the way to it is group- or
        world-writable, because write access to a directory is the right
        to replace what is in it.

    Ancestors matter as much as the file: /usr/bin/ffmpeg owned by root
    is no protection at all if /usr/bin is world-writable.  This mirrors
    playthrough_verify_executable() in playthrough/tooling/env.sh, which
    walks the same chain for the shell half of the pipeline.
    """
    try:
        info = os.lstat(real)
    except OSError as err:
        raise RenderError(
            "%s from %s could not be inspected: %s"
            % (name, origin, err)) from err
    if not stat.S_ISREG(info.st_mode):
        raise RenderError(
            "%s from %s is not a regular file: %s"
            % (name, origin, real))
    trusted = (0, os.getuid())
    if info.st_uid not in trusted:
        raise RenderError(
            "%s resolves to %s, which is owned by uid %d -- neither "
            "root nor this account (uid %d).  Every frame of the film "
            "passes through this binary, so one that another account "
            "owns is refused rather than executed."
            % (name, real, info.st_uid, os.getuid()))
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RenderError(
            "%s resolves to %s, which is group- or world-writable "
            "(mode %04o).  A binary anybody can rewrite is refused."
            % (name, real, info.st_mode & 0o7777))
    directory = os.path.dirname(real)
    while True:
        try:
            entry = os.lstat(directory)
        except OSError as err:
            raise RenderError(
                "the directory %s on the way to %s could not be "
                "inspected: %s" % (directory, name, err)) from err
        if entry.st_uid not in trusted:
            raise RenderError(
                "%s is reached through %s, which is owned by uid %d -- "
                "neither root nor this account.  Write access to a "
                "directory is the right to replace what is in it, so "
                "the tool is refused."
                % (name, directory, entry.st_uid))
        if entry.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            # The sticky bit makes a shared directory safe for FILES
            # nobody else owns, but the binary's own ownership is already
            # proved above, so a sticky /tmp-like ancestor is acceptable
            # only when it is sticky.
            if not entry.st_mode & stat.S_ISVTX:
                raise RenderError(
                    "%s is reached through %s, which is group- or "
                    "world-writable (mode %04o) and not sticky.  "
                    "Anybody able to write that directory can replace "
                    "the binary in it."
                    % (name, directory, entry.st_mode & 0o7777))
        parent = os.path.dirname(directory)
        if parent == directory:
            return
        directory = parent


# ---------------------------------------------------------------------
# Durations.  The concat list is the one place the timeline's numbers
# become text, so the formatting is exact and the transition split is
# arithmetic rather than an approximation.
# ---------------------------------------------------------------------

# Microsecond resolution for a transition share.  The timeline itself is
# written at millisecond resolution, but a transition second divided
# twelve ways is not expressible in milliseconds, and rounding it there
# would leave the group short or long by up to 4 ms EVERY TIME the ceiling
# engages -- which the container would then disagree with the captions
# about, once per transition, cumulatively.
DURATION_DECIMALS = 6
MICROSECONDS = 10 ** DURATION_DECIMALS

# ---------------------------------------------------------------------
# TWO WIDTHS, AND WHY THE LIST NO LONGER STRIPS ZEROS
#
# THE DEFECT.  Every duration used to be written at microsecond precision
# and then stripped of trailing fractional zeros, so a captured frame's
# 0.25 s came out as "0.25", 1 s as "1.0" and the ceiling as "10.0".  The
# arithmetic was right -- ffmpeg parses "0.25" and 0.250 identically -- but
# the committed concat list is EVIDENCE, and as evidence it disagreed with
# every other artifact describing the same numbers: timeline.json writes
# durations at three decimals, verify_artifacts.sh reads the clamp bounds
# as 0.250 and 10.000, and the report quotes them that way.  A reader
# comparing the list against the timeline had to know that "10.0" and
# 10.000 were the same value and that "0.083333" was a different KIND of
# number from either.
#
# So the two kinds are now written at the width each is computed at, and
# neither is stripped:
#
#   * A CAPTURED FRAME's duration comes from timeline.py, which clamps and
#     rounds to milliseconds.  Three decimals is exactly that resolution:
#     "0.250", "1.000", "10.000".
#   * A TRANSITION SHARE is a twelfth of a second computed in whole
#     microseconds, with the remainder charged to the last frame.  Six
#     decimals is exactly that resolution: "0.083333" eleven times and
#     "0.083337" once.
#
# The width therefore SAYS which kind of duration a line carries, and a
# re-run stays byte-identical because both formats are fixed.
# ---------------------------------------------------------------------

# The resolution timeline.py rounds a clamped duration to.  Restated here
# rather than imported for the same reason timeline.py restates its own
# field names: the constant is part of this module's output format.
CAPTURE_DECIMALS = 3


def format_duration(seconds: float) -> str:
    """Return `seconds` as a concat duration at microsecond width.

    The width used for a TRANSITION SHARE, which is computed in whole
    microseconds: a twelfth of a second is "0.083333" and the remainder
    frame "0.083337".  Fixed width, never stripped, so a re-run is
    byte-identical and the number in the list is the number that was
    computed.

    :func:`format_capture_duration` is the other half; see the note above
    for why the two widths differ and what the difference says.
    """
    return _format_seconds(seconds, DURATION_DECIMALS)


def format_capture_duration(seconds: float) -> str:
    """Return `seconds` as a concat duration at millisecond width.

    The width used for a CAPTURED FRAME, whose duration timeline.py has
    already clamped and rounded to milliseconds: the floor is "0.250" and
    the ceiling "10.000", which is how timeline.json, the acceptance gate
    and the report all spell them.
    """
    return _format_seconds(seconds, CAPTURE_DECIMALS)


def _format_seconds(seconds: Any, decimals: int) -> str:
    """Return a validated, fixed-width decimal for a concat duration."""
    try:
        number = float(seconds)
    except (TypeError, ValueError) as err:
        raise RenderError(
            "a duration must be a number, got %r" % (seconds,)) from err
    if math.isnan(number) or math.isinf(number):
        raise RenderError("a duration must be finite, got %r" % seconds)
    if number < 0.0:
        raise RenderError(
            "a duration must not be negative, got %r" % seconds)
    return format(number, ".%df" % decimals)


def format_entry_duration(entry: "ConcatEntry") -> str:
    """Return the duration line's value for one planned entry.

    THE ONE PLACE THE WIDTH IS CHOSEN, keyed off the entry's own kind, so
    a capture cannot be written at a share's width or the other way round.
    """
    if entry.kind == KIND_TRANSITION:
        return format_duration(entry.duration)
    if entry.kind != KIND_CAPTURE:
        raise RenderError(
            "a concat entry is either a %r or a %r, got %r"
            % (KIND_CAPTURE, KIND_TRANSITION, entry.kind))
    return format_capture_duration(entry.duration)


def transition_durations(
    seconds: float,
    count: Optional[int] = None,
) -> List[float]:
    """Split a transition's seconds across its frames, EXACTLY.

    The timeline charges exactly `seconds` of video time per transition
    and the container has to agree, so the split is done in whole
    microseconds and the remainder is never dropped.  `frames - 1`
    frames take an equal base share and THE LAST ONE TAKES THE EXACT
    REMAINDER, so twelve frames over one second come out as eleven at
    0.083333 s and one at 0.083337 s, summing to 1.000000 s and not to
    0.999996 s.

    That difference looks negligible and is not: a group that falls 4 us
    short would drift the picture away from the cues by that much every
    time the ceiling engages, in the same direction, for the rest of the
    film.

    The remainder is charged ONCE, at the END, rather than spread over
    the leading frames.  Both spellings sum correctly, but this one
    keeps every frame of a group identical except the last, so a
    duration read out of the committed list is the group's base share
    and the one exception is where the arithmetic says it is.
    """
    frames = make_transitions.FRAMES_PER_GROUP if count is None else count
    if not isinstance(frames, int) or isinstance(frames, bool):
        raise RenderError(
            "a transition group size must be an integer, got %s"
            % type(frames).__name__)
    if frames <= 0:
        raise RenderError(
            "a transition group must hold at least one frame, got %d"
            % frames)
    try:
        number = float(seconds)
    except (TypeError, ValueError) as err:
        raise RenderError(
            "a transition length must be a number, got %r"
            % (seconds,)) from err
    if math.isnan(number) or math.isinf(number) or number <= 0.0:
        raise RenderError(
            "a transition length must be finite and positive, got %r"
            % (seconds,))
    total = int(round(Decimal(str(number)) * MICROSECONDS))
    base = total // frames
    if base <= 0:
        raise RenderError(
            "a transition of %r s cannot be split across %d frames at "
            "microsecond resolution" % (seconds, frames))
    # frames - 1 equal base slices, and the exact remainder last.
    shares = [base] * (frames - 1) + [total - base * (frames - 1)]
    # The whole point of doing this in integers: the identity holds
    # exactly, so it can be asserted rather than approximated.
    if sum(shares) != total:
        raise RenderError(
            "the transition split does not sum to %d us: %r"
            % (total, shares))
    return [share / MICROSECONDS for share in shares]


# ---------------------------------------------------------------------
# Reading the timeline.  Four of its eighteen entry fields are used, and
# each is checked rather than trusted: a stale or hand-edited document
# is the one input that could pace a whole film wrongly while looking
# entirely plausible.
# ---------------------------------------------------------------------

def _entry_frame_index(entry: Dict[str, Any], position: int) -> int:
    """Return an entry's capture index, checked against the name width.

    The index names the transition group on disk through a five-digit
    field, so a value that will not fit in one is refused here where the
    message can say which entry it was.
    """
    value = entry.get(make_transitions.KEY_FRAME)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RenderError(
            "timeline entry %d has no integer '%s', got %r"
            % (position, make_transitions.KEY_FRAME, value))
    lowest = make_transitions.MIN_FRAME_INDEX
    highest = make_transitions.MAX_FRAME_INDEX
    if value < lowest or value > highest:
        raise RenderError(
            "timeline entry %d has '%s' %d, outside the %d..%d the "
            "five-digit frame field can express"
            % (position, make_transitions.KEY_FRAME, value,
               lowest, highest))
    return value


def _entry_duration(entry: Dict[str, Any], position: int) -> float:
    """Return an entry's clamped duration, checked against the clamp.

    A value outside [FLOOR, CEIL] means timeline.py did not produce this
    document, or something edited it afterwards.  Either way the film's
    pacing and the caption cues no longer come from the same rule, so it
    is refused rather than encoded.  EPSILON absorbs the representation
    of a decimal boundary in binary floating point and nothing more.
    """
    value = entry.get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RenderError(
            "timeline entry %d has no numeric 'duration', got %r"
            % (position, value))
    try:
        duration = round_seconds(value)
    except TimelineError as err:
        raise RenderError(
            "timeline entry %d has an unusable 'duration': %s"
            % (position, err)) from err
    if duration < FLOOR - EPSILON or duration > CEIL + EPSILON:
        raise RenderError(
            "timeline entry %d has duration %r, outside the clamp "
            "[%s, %s] every entry is guaranteed to satisfy.  "
            "timeline.py applies min(max(raw, %s), %s), so this "
            "document was not produced by it or was edited afterwards."
            % (position, duration, FLOOR, CEIL, FLOOR, CEIL))
    return duration


def _entry_flag(entry: Dict[str, Any], position: int) -> bool:
    """Return whether a transition is owed after this entry."""
    value = entry.get(make_transitions.KEY_TRANSITION_AFTER)
    if not isinstance(value, bool):
        raise RenderError(
            "timeline entry %d has no boolean '%s', got %r"
            % (position, make_transitions.KEY_TRANSITION_AFTER, value))
    return value


def group_paths(
    frame: int,
    directory: str,
    root: Optional[str] = None,
) -> List[str]:
    """Return the twelve transition frames that follow `frame`.

    The stem and the group size come from make_transitions, which wrote
    them, so the renderer cannot look for a name the composer does not
    produce.  The prefix is put through that module's own output-prefix
    validator, so the paths are proved to lie inside the transitions
    directory before any of them is opened.
    """
    stem = _join(
        directory,
        (make_transitions.TRANSITION_STEM_FORMAT % frame,))
    try:
        prefix = make_transitions.validated_output_prefix(stem, root)
        return make_transitions.group_frame_paths(prefix)
    except make_transitions.TransitionError as err:
        raise RenderError(str(err)) from err


def _assert_group(
    frame: int,
    paths: Sequence[str],
    present: Sequence[str],
    position: int,
) -> None:
    """Refuse a flagged entry whose group is not exactly on disk.

    EXACTLY the twelve expected frames, no fewer and no more.  Too few
    means make_transitions.py was not run, or was run against a
    different timeline, and the container would then be short of imagery
    for a second it has already charged to video time.  Too many means
    something else is writing into that directory under this module's
    naming, and a stray frame would be silently encoded into the film.
    """
    expected = [os.path.basename(path) for path in paths]
    missing = [name for name, path in zip(expected, paths)
               if not os.path.isfile(path)]
    if missing:
        raise RenderError(
            "timeline entry %d (frame %d) carries '%s' but %d of its %d "
            "transition frames are not on disk: %s.  Run "
            "make_transitions.py against THIS timeline first -- the "
            "timeline has already charged %s s of video time to that "
            "group, so the film would be short of imagery for it."
            % (position, frame,
               make_transitions.KEY_TRANSITION_AFTER, len(missing),
               len(expected), ", ".join(missing),
               make_transitions.EXPECTED_TRANSITION))
    extra = sorted(set(present) - set(expected))
    if extra:
        raise RenderError(
            "the transition group for frame %d holds %d frame(s) beyond "
            "the %d this module encodes: %s.  Exactly %d is the group "
            "size make_transitions.py writes, and anything else in that "
            "directory under the same name would end up in the film "
            "unaccounted for."
            % (frame, len(extra), len(expected), ", ".join(extra),
               make_transitions.FRAMES_PER_GROUP))


def _group_members(directory: str, frame: int) -> List[str]:
    """Return every file already named for `frame`'s group.

    Read from the directory listing rather than probed name by name, so
    a thirteenth frame nobody expected is seen instead of ignored.
    """
    stem = make_transitions.TRANSITION_STEM_FORMAT % frame
    try:
        names = os.listdir(directory)
    except OSError as err:
        raise RenderError(
            "could not read the transitions directory %s: %s"
            % (directory, err)) from err
    return sorted(
        name for name in names
        if name.startswith(stem + "_") and
        make_transitions.TRANSITION_NAME_RE.match(name))


def _declared(document: Any, key: str) -> Optional[float]:
    """Return a numeric top-level field of the document, or None."""
    if not isinstance(document, dict):
        return None
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def plan_render(
    document: Any,
    root: Optional[str] = None,
    timeline_path: Optional[str] = None,
) -> Plan:
    """Resolve and check every input before a byte is written.

    THE WHOLE OF THE INPUT CONTRACT IS ASSERTED HERE, so that a defect
    stops the run while the previous concat list and the previous movie
    are still intact and still consistent with each other.  In order:
    the document satisfies its own invariant; the transition length is
    the one that can be materialised; every entry's frame index,
    duration and flag are well formed; every capture named exists and
    lies inside playthrough/frames/; every flagged entry's group is
    exactly on disk AND is attributed by its own generation manifest to
    THIS timeline; and the total the entries imply is the total the
    document declares.

    A MISSING FRAME ABORTS AND IS NEVER SKIPPED.  Skipping one would
    preserve every appearance of success -- the encode would run, the
    container would be produced -- while breaking the
    one-frame-per-keystroke invariant and shifting every caption after
    it by that frame's window.

    :param timeline_path: the document's own path, needed to hold the
        transition groups' provenance against it.  When it is not given
        the default timeline is assumed, which is what a direct call
        without an explicit document path means.
    """
    try:
        entries = make_transitions.timeline_entries(document)
        seconds = make_transitions.transition_seconds(document)
        width, height = make_transitions.expected_size()
    except make_transitions.TransitionError as err:
        raise RenderError(str(err)) from err
    if not entries:
        raise RenderError(
            "the timeline has no frames, so there is no film to "
            "render.  One keystroke produces one capture and one "
            "timeline entry; a document with none is not a record of a "
            "session.")

    # THE CANONICAL GATE, AND IT IS NO LONGER CONDITIONAL.  This used to
    # read `if isinstance(document, dict)` -- which meant a bare ARRAY of
    # entries skipped it silently, and a bare array was exactly what
    # make_transitions.timeline_entries() used to accept.  So a
    # hand-written list of durations could pace the whole film with no
    # clamp bounds checked, no totals to check the entries against, no
    # constants proving what the clamp was applied under, and no
    # provenance naming the evidence any of it came from.
    #
    # assert_timeline_document() requires all three: an object, zero
    # validate_timeline() problems, and a manifest attestation that
    # matches the manifest on disk.  The last one is what catches a stale
    # timeline left beside a re-recorded session -- the one failure no
    # internal invariant can see, because a stale document is perfectly
    # self-consistent.
    try:
        assert_timeline_document(document, root, label="timeline")
    except TimelineError as err:
        raise RenderError(
            "the timeline cannot be rendered from: %s.  The film it "
            "paces would not match the captions make_srt.py writes from "
            "the same document, and the two would look consistent while "
            "disagreeing." % err) from err

    # The entries are spelled relative to the LIST's own directory,
    # because that is what ffmpeg resolves them against.  See
    # _relative_entry().
    base = os.path.dirname(default_concat_path(root))
    captures = _captures_dir(root)
    transitions: Optional[str] = None
    shares = transition_durations(seconds)

    planned: List[ConcatEntry] = []
    durations: List[float] = []
    flags: List[bool] = []
    flagged_frames: List[int] = []
    groups = 0
    for position, entry in enumerate(entries, start=1):
        index = _entry_frame_index(entry, position)
        duration = _entry_duration(entry, position)
        flagged = _entry_flag(entry, position)
        try:
            capture = make_transitions.validated_capture_path(
                entry.get(make_transitions.KEY_FILE),
                "the '%s' of timeline entry %d"
                % (make_transitions.KEY_FILE, position),
                root, captures)
        except make_transitions.TransitionError as err:
            raise RenderError(
                "%s.  A capture the session took is missing, so the "
                "film cannot honestly include it and is refused rather "
                "than rendered without it." % err) from err
        _assert_entry_size(capture, width, height)
        planned.append(ConcatEntry(
            capture, _relative_entry(capture, base), duration,
            KIND_CAPTURE, index, NO_ORDINAL))
        durations.append(duration)
        flags.append(flagged)
        if not flagged:
            continue
        if transitions is None:
            transitions = _transitions_dir(root)
        paths = group_paths(index, transitions, root)
        _assert_group(index, paths,
                      _group_members(transitions, index), position)
        for ordinal, (path, share) in enumerate(zip(paths, shares)):
            _assert_entry_size(path, width, height)
            planned.append(ConcatEntry(
                path, _relative_entry(path, base), share,
                KIND_TRANSITION, index, ordinal))
        flagged_frames.append(index)
        groups += 1

    # THE PROVENANCE OF THE GROUP SET, CHECKED GLOBALLY AND ONLY ONCE.
    # _assert_group() above proves each flagged index has exactly its
    # twelve files at the right geometry, and a name and a size are not
    # evidence: the same twelve names exist in every session that flags
    # frame 42.  This holds the whole directory to the provenance record
    # make_transitions.py publishes BESIDE it, at
    # playthrough/build/transitions.json -- which binds the groups to a
    # timeline by that document's digest, to the captures they were faded
    # between, and to their own bytes -- and holds the group INDEX SET to
    # the flags in THIS document, so a stale group for an index the
    # recomputed timeline no longer flags is refused instead of being
    # invisible here and counted by verify_artifacts.sh.
    #
    # The record moved out of the directory because that directory admits
    # `trans_*.png` and nothing else, and the two halves are held
    # together by the generation journal rather than by sharing one
    # rename -- so a group set whose record does not describe it is a
    # REFUSAL here, which is what makes the split safe.
    #
    # Skipped only when the timeline flags nothing at all, in which case
    # there is no group set to attribute; _assert_group() is likewise never
    # reached, and the directory may legitimately not exist.
    if flagged_frames:
        source = (default_timeline_path() if timeline_path is None
                  else timeline_path)
        problems = make_transitions.generation_manifest_problems(
            transitions or _transitions_dir(root), source, flagged_frames)
        if problems:
            raise RenderError(
                "the transition frames cannot be attributed to this "
                "timeline: %s" % "  ".join(problems))

    # The expected total, computed two ways from the same entries so
    # that the comparison below is checking something rather than
    # reading one number twice.  The first walks the durations and adds
    # the transition length once per group; the second is timeline.py's
    # own function for the left-hand side of the invariant.
    expected = round_seconds(math.fsum(durations) + seconds * groups)
    crosscheck = timeline_total(durations, flags)
    if abs(expected - crosscheck) > EPSILON:
        raise RenderError(
            "the expected total is %r by this module's arithmetic and "
            "%r by timeline.timeline_total(); the two must agree or the "
            "container has no single length to be checked against"
            % (expected, crosscheck))

    declared = _declared(document, "total")
    if declared is not None and abs(declared - expected) > EPSILON:
        raise RenderError(
            "the timeline declares a total of %r s but its %d entries "
            "and %d transition group(s) imply %r s.  The document is "
            "internally inconsistent or was edited after it was "
            "computed; recompute it with timeline.py rather than "
            "encoding from it."
            % (declared, len(durations), groups, expected))
    _assert_counts(document, len(durations), groups)

    return Plan(
        entries=planned,
        capture_count=len(durations),
        group_count=groups,
        transition_seconds=seconds,
        expected_total=expected,
        declared_total=declared,
        width=width,
        height=height,
    )


def _assert_counts(
    document: Any,
    captures: int,
    groups: int,
) -> None:
    """Refuse a document whose own header contradicts its frames.

    frame_count and transition_count are written by timeline.py from the
    same entries this module just walked, so a disagreement means the
    document on disk is not the document those counts describe -- the
    signature of a stale artifact, which is the one input that would
    otherwise render a plausible film of the wrong session.
    """
    if not isinstance(document, dict):
        return
    for key, actual in (("frame_count", captures),
                        ("transition_count", groups)):
        value = document.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise RenderError(
                "the timeline's '%s' must be an integer, got %r"
                % (key, value))
        if value != actual:
            raise RenderError(
                "the timeline declares '%s' %d but its frames array "
                "yields %d.  The document is stale or was edited; "
                "recompute it with timeline.py."
                % (key, value, actual))


# ---------------------------------------------------------------------
# The concat list.  ONE form of the sequence, spelled relative to the
# list file's own directory because that is the base ffmpeg's concat
# demuxer resolves entries against.  The committed list is therefore the
# file the encoder is handed.  See the module docstring for the
# measurement behind that spelling.
# ---------------------------------------------------------------------

def format_concat_list(plan: Plan) -> str:
    """Return the committed concat list, exactly as it is written.

    In frame order: a `file` line and its `duration` line per entry,
    with each flagged capture followed immediately by its twelve
    transition frames, each carrying its own share of the transition
    second.  Then -- and this is the part that must never be tidied away
    -- the final `file` line ONCE MORE with no duration after it, so
    that the last entry's duration takes effect and the container
    reaches the length the captions were written for.  Whatever ends up
    last in the sequence is what gets repeated, whether that is a
    capture or the twelfth frame of a group.

    A capture's duration is written at millisecond width and a transition
    share's at microsecond width, each being the resolution it was
    computed at; see the note above :func:`format_duration`.
    """
    if not plan.entries:
        raise RenderError("there are no entries to write")
    lines: List[str] = []
    for entry in plan.entries:
        lines.append(
            CONCAT_FILE_PREFIX + entry.relative + CONCAT_FILE_SUFFIX)
        lines.append(
            CONCAT_DURATION_PREFIX + format_entry_duration(entry))
    # *** THE REPEATED FINAL ENTRY.  NOT OPTIONAL.  See the module
    # docstring: without it the last duration line does not take
    # effect, the container comes up short, and every caption past the
    # shortfall points beyond the end of the film -- silently, because
    # every other count still matches.
    lines.append(
        CONCAT_FILE_PREFIX + plan.entries[-1].relative +
        CONCAT_FILE_SUFFIX)
    return CONCAT_NEWLINE.join(lines) + CONCAT_NEWLINE


def concat_counts(text: str) -> Tuple[int, int]:
    """Return (file lines, duration lines) and check the relation.

    The structural half of the truncation gate, and the deterministic
    half: the file line count must be exactly the duration line count
    plus one, because every entry contributes both and the final entry
    contributes one extra file line.  This catches a dropped repeated
    entry on the bytes themselves, without needing an encoder to notice
    it, which matters because the container symptom is a length nobody
    would question in isolation.
    """
    files = 0
    durations = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(CONCAT_FILE_PREFIX):
            files += 1
        elif line.startswith(CONCAT_DURATION_PREFIX):
            durations += 1
        else:
            raise RenderError(
                "concat list line %d is neither a '%s' nor a '%s' "
                "entry: %r" % (number, CONCAT_FILE_PREFIX.strip(),
                               CONCAT_DURATION_PREFIX.strip(), line))
    if files != durations + 1:
        raise RenderError(
            "the concat list has %d file line(s) and %d duration "
            "line(s); it must have exactly one more file line than "
            "duration lines, because the final file line is repeated "
            "with no duration.  Without that repeat the last image's "
            "duration does not take effect and the container truncates."
            % (files, durations))
    return files, durations


def resolved_committed_entries(
    committed: str,
    base: str,
    allowed: Sequence[str],
) -> List[str]:
    """Resolve every `file` entry of the committed list, in order.

    Each entry is re-read from the bytes that were written and resolved
    against `base` -- the list's own directory, which is what ffmpeg
    resolves it against -- and proved to name a real file inside one of
    the `allowed` directories.  Returns the absolute paths in list
    order.

    Reading them back from the bytes rather than from the plan is
    deliberate: a short or corrupted write is caught here, because the
    readback would then not reproduce the plan's sequence.
    """
    resolved: List[str] = []
    seen = False
    for number, line in enumerate(committed.splitlines(), start=1):
        if line.startswith(CONCAT_FILE_PREFIX):
            if not line.endswith(CONCAT_FILE_SUFFIX):
                raise RenderError(
                    "concat list line %d is not a closed quoted entry: "
                    "%r" % (number, line))
            head = len(CONCAT_FILE_PREFIX)
            tail = len(line) - len(CONCAT_FILE_SUFFIX)
            resolved.append(
                _absolute_entry(line[head:tail], base, allowed))
            seen = True
        elif line.startswith(CONCAT_DURATION_PREFIX):
            seen = True
        else:
            raise RenderError(
                "concat list line %d is neither a file nor a duration "
                "entry: %r" % (number, line))
    if not seen:
        raise RenderError("the concat list is empty")
    return resolved


def verify_committed_list(
    committed: str,
    base: str,
    allowed: Sequence[str],
    plan: Plan,
) -> List[str]:
    """Prove the committed list is the sequence the plan resolved.

    The list handed to the encoder is the one committed to the
    repository, so it is verified rather than trusted: every entry is
    resolved from its own bytes and the resulting sequence must equal
    the plan's paths PLUS THE REPEATED FINAL ENTRY, which is what makes
    the last image's duration take effect.  A mismatch means the bytes
    on disk are not the film that was planned, and the encode is refused
    rather than producing a container nobody can reproduce.
    """
    resolved = resolved_committed_entries(committed, base, allowed)
    expected = [entry.path for entry in plan.entries]
    if expected:
        expected = expected + [expected[-1]]
    if resolved != expected:
        raise RenderError(
            "the committed concat list at %s does not resolve to the "
            "planned sequence: it names %d file entries and the plan "
            "resolved %d (the last one repeated so its duration is "
            "honoured).  Refusing to encode a sequence that is not the "
            "one on disk."
            % (_join(base, (CONCAT_REL_PARTS[-1],)),
               len(resolved), len(expected)))
    return resolved


def _sync_directory(parent: str) -> None:
    """Force a rename in `parent` to the device, tolerating refusal.

    os.replace() is atomic with respect to a reader, but the directory
    entry it creates is not durable until the directory itself is
    synced.  A filesystem that refuses is reported rather than allowed
    to end the run: the data itself is already fsynced.
    """
    try:
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as err:
        _warn("could not open %s to sync the rename (%s)"
              % (parent, err))
        return
    try:
        os.fsync(descriptor)
    except OSError as err:
        _warn("could not sync %s after the rename (%s)" % (parent, err))
    finally:
        os.close(descriptor)


def write_text(path: str, text: str) -> str:
    """Write `text` to `path` atomically.  Returns the path written.

    UTF-8 with newline="\\n", so the artifact has LF endings whatever
    the platform and never a byte-order mark -- a mark in front of the
    first `file` line would stop the demuxer recognising it.

    THE REPLACEMENT IS ATOMIC.  Opening the destination "w" truncates it
    first, so an interruption between the truncation and the last byte
    would leave half a concat list where a complete one had been, which
    is worse than a stale one because the stale one at least describes a
    film that was actually encoded.  So the text goes to a temporary
    file in the SAME directory, is flushed and fsynced, and is then
    moved into place with os.replace(), which either fully succeeds or
    leaves the previous file untouched.
    """
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise RenderError(
            "the directory for %s does not exist: %s" % (path, parent))
    descriptor, temporary = tempfile.mkstemp(
        dir=parent, prefix=".concat-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8",
                       newline=CONCAT_NEWLINE) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates at 0600; the concat list is a committed
        # artifact read by ffmpeg and by people, so it carries the
        # ordinary mode a plain open() would have produced.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except OSError:
        # The destination is untouched at this point, so removing the
        # temporary file restores the directory exactly as it was.  A
        # failure to remove it is REPORTED and then set aside, because
        # the exception on its way out describes the real fault and
        # replacing it with a cleanup complaint would hide the cause.
        try:
            os.unlink(temporary)
        except OSError as cleanup:
            _warn("could not remove the temporary file %s (%s)"
                  % (temporary, cleanup))
        raise
    _sync_directory(parent)
    return path


def concat_target(
    path: Optional[str] = None,
    root: Optional[str] = None,
) -> str:
    """Resolve the concat list's destination and ensure its directory.

    This module owns build/concat.txt and creating its directory is the
    whole of its directory management -- build/transitions/ belongs to
    make_transitions.py.
    """
    target = (default_concat_path(root) if path is None
              else _validated_output(path, "the concat list", root=root))
    parent = os.path.dirname(target)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as err:
        raise RenderError(
            "could not create the build directory %s: %s"
            % (parent, err)) from err
    return target


def _assert_list_on_disk(path: str, text: str) -> str:
    """Read a written list back and prove it is the intended bytes."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            written = handle.read()
    except OSError as err:
        raise RenderError(
            "could not read back the concat list %s: %s"
            % (path, err)) from err
    if written != text:
        raise RenderError(
            "the concat list on disk is not what was written to %s (%d "
            "bytes intended, %d bytes read back)"
            % (path, len(text), len(written)))
    concat_counts(written)
    return written


def stage_concat_list(
    plan: Plan,
    path: Optional[str] = None,
    root: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Stage the concat list beside its target.  Returns three strings.

    ``(target, staging, text)`` -- where the list will be published, where
    it is now, and the bytes it carries.

    STAGED IN THE TARGET'S OWN DIRECTORY, WHICH IS LOAD-BEARING.  Every
    `file` entry is spelled relative to the LIST's directory, because that
    is what ffmpeg's concat demuxer resolves it against.  Staging it
    anywhere else -- a temporary directory, the scratch area -- would make
    those entries resolve somewhere else or not at all, so the encoder
    would have to be handed a different list from the one committed, which
    is precisely the defect this module already fixed once.  Staged here,
    the bytes handed to ffmpeg and the bytes published are the SAME BYTES,
    moved by a rename rather than rewritten.

    The bytes are read back and the structural
    file-equals-duration-plus-one relation is asserted on what is actually
    on disk rather than on the string in memory.  A concat list is the
    instruction sheet for the encode; verifying it costs microseconds and
    catches a full disk.
    """
    target = concat_target(path, root)
    text = format_concat_list(plan)
    concat_counts(text)
    staging = staging_path(target)
    write_text(staging, text)
    try:
        _assert_list_on_disk(staging, text)
    except BaseException:
        try:
            os.unlink(staging)
        except OSError as cleanup:  # pragma: no cover - defensive
            _warn("could not remove the staged concat list %s (%s)"
                  % (staging, cleanup))
        raise
    return target, staging, text


def publish_concat_list(staging: str, target: str) -> str:
    """Rename a staged concat list onto its canonical path."""
    try:
        os.replace(staging, target)
    except OSError as err:
        raise RenderError(
            "could not publish the concat list as %s: %s.  The previous "
            "list is untouched." % (target, err)) from err
    _sync_directory(os.path.dirname(target))
    return target


def write_concat_list(
    plan: Plan,
    path: Optional[str] = None,
    root: Optional[str] = None,
) -> Tuple[str, str]:
    """Write and publish the concat list.  Returns (path, text written).

    THE CONCAT-ONLY PATH.  ``--concat-only`` exists so an operator can
    inspect the instruction sheet without spending an encode, and in that
    mode there is no movie for the list to be consistent with, so
    publishing it on its own is the whole of the job.

    The full render does NOT come through here: it stages the list, encodes
    from the staged bytes, and publishes the list and the movie together as
    one generation.  See :func:`stage_concat_list` and
    :func:`publish_generation` for why.
    """
    target, staging, text = stage_concat_list(plan, path, root)
    try:
        publish_concat_list(staging, target)
    except BaseException:
        try:
            os.unlink(staging)
        except OSError:  # pragma: no cover - defensive
            pass
        raise
    return target, _assert_list_on_disk(target, text)


# ---------------------------------------------------------------------
# The encode.  One pass, one process, one argument list.
# ---------------------------------------------------------------------

def encode_command(
    ffmpeg: str,
    list_path: str,
    output: str,
    width: int,
    height: int,
) -> List[str]:
    """Return the ffmpeg argument list, built rather than interpolated.

    A LIST, never a string and never a shell.  That is the repository's
    CodeQL python leg gate
    [.github/workflows/codeql-analysis.yml:35] and it also means a path
    containing a space, a quote or a semicolon cannot change what runs.

    There is no filter argument here and there is no way to add one:
    the captions are muxed as a SELECTABLE mov_text track by
    embed_captions.sh, and burning them into the picture is forbidden.
    There is no audio input either, so the container carries no audio
    stream -- nothing needs suppressing, because nothing is offered.
    And there is no output frame-rate argument, which is not an omission
    but a requirement: ffmpeg refuses one alongside a non-constant
    -fps_mode outright.
    """
    return [
        ffmpeg,
        OVERWRITE,
        "-v", LOGLEVEL,
        "-f", CONCAT_FORMAT,
        "-safe", CONCAT_SAFE,
        "-i", list_path,
        "-fps_mode", FPS_MODE,
        "-pix_fmt", PIXEL_FORMAT,
        "-c:v", VIDEO_CODEC,
        "-crf", CRF,
        "-bf", BFRAMES,
        "-s", "%dx%d" % (width, height),
        "-movflags", MOVFLAGS,
        output,
    ]


def _run(
    command: Sequence[str],
    cwd: str,
    label: str,
    timeout: float = ENCODE_TIMEOUT,
) -> str:
    """Run a tool under a hard time limit and return its stdout.

    Standard input is /dev/null because ffmpeg reads the terminal for
    interactive commands and will otherwise consume whatever the parent
    was reading -- observed on this host swallowing the remainder of a
    shell script and printing its own "Enter command:" prompt.  Standard
    error is captured and SURFACED on failure rather than swallowed: the
    one line that says which frame could not be opened is the whole
    diagnostic.

    EVERY CHILD IS BOUNDED AND EVERY CHILD IS REAPED.  Without a
    timeout, one malformed entry in the concat list is enough for ffmpeg
    to sit forever on an input it cannot resolve, and the whole pipeline
    -- which is a single sequential script -- stops with no diagnosis and
    no process to inspect.  A hung tool is a fault to REPORT, not a
    reason to wait indefinitely.

    Termination is deterministic rather than best-effort: the child is
    started in its OWN process group, so the timeout kills the group and
    not merely the direct child, and then the group is waited on.  ffmpeg
    spawns no helpers today, so this is belt as well as braces -- but the
    alternative, an orphan holding the staging file open while the
    pipeline moves on, is exactly the kind of failure that surfaces as
    something else entirely three stages later.

    :param timeout: wall-clock seconds.  The caller chooses, because an
        encode of a long film and a metadata probe are not the same
        order of magnitude.
    """
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as err:
        raise RenderError(
            "could not run %s: %s" % (label, err)) from err
    try:
        out, errors = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_group(process, label)
        out, errors = process.communicate()
        detail = (errors or "").strip()
        raise RenderError(
            "%s did not finish within %.0fs and was killed.%s  A tool "
            "that hangs is reported rather than waited on: the pipeline "
            "is one sequential script, so an unbounded child stops "
            "everything with no diagnosis."
            % (label, timeout,
               ("  Its last words: " + detail) if detail else ""))
    if process.returncode != 0:
        detail = (errors or "").strip()
        raise RenderError(
            "%s exited %d.%s"
            % (label, process.returncode,
               ("  It said: " + detail) if detail else ""))
    return out or ""


def _terminate_group(
    process: "subprocess.Popen[str]",
    label: str,
) -> None:
    """Kill a timed-out child's whole process group, then reap it.

    SIGKILL rather than SIGTERM: this is already the timeout path, so
    the tool has had its chance to finish, and a handler that ignores
    SIGTERM would leave exactly the orphan this exists to prevent.  The
    group id is the child's pid because it was started with
    start_new_session=True.
    """
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError) as err:
        # It exited between the timeout and the signal, or the platform
        # refused the group; killing the child directly still reaps it.
        _warn("could not kill the %s process group (%s)" % (label, err))
        try:
            process.kill()
        except OSError:  # pragma: no cover - already gone
            pass


# ---------------------------------------------------------------------
# Publication
#
# WHY THE MOVIE IS NOT ENCODED ONTO ITS OWN PATH.  `ffmpeg -y` truncates
# its output the moment it opens it, and the verification -- the ffprobe
# duration comparison that is the ONLY check able to catch a truncated
# film -- ran afterwards, against that same path.  So every failure mode
# the check exists to detect had already destroyed the previous good
# movie by the time it was detected: a short container, a missing
# repeated final entry, an encoder killed half way, a full disk.  The run
# reported the problem and exited non-zero, and playthrough/cata-play.mp4
# was left holding a film nobody had verified, in place of one that had
# been.  It is a committed artifact, so the loss reached the repository.
#
# So the encode now goes to a unique staging sibling, the staging file is
# probed and verified there, and only a file that passed every check is
# renamed onto the canonical path -- atomically, so a reader sees either
# the previous movie or the new one and never a partial encode.  A
# failure removes the staging file and leaves the published movie exactly
# as it was.
#
# The staging file is a SIBLING because os.replace() is only atomic
# within one filesystem, and it keeps the .mp4 suffix because ffmpeg
# selects the muxer from the extension.
# ---------------------------------------------------------------------

# The artifact this module publishes, for timeline.ArtifactLock.  The
# lock lives in the pipeline's scratch directory OUTSIDE the tree,
# because .gitignore's terminal `!/playthrough/**` would otherwise
# re-include a lock file as though it were evidence.
LOCK_NAME = "movie"

STAGING_PREFIX = "."
STAGING_INFIX = ".part-"


def staging_path(output: str) -> str:
    """Return a unique staging sibling for `output`.

    Unique per process and per attempt, so two runs cannot write the same
    staging file even in the moment before one of them takes the lock.
    """
    directory, name = os.path.split(output)
    stem, suffix = os.path.splitext(name)
    return os.path.join(
        directory,
        "%s%s%s%d-%d%s" % (STAGING_PREFIX, stem, STAGING_INFIX,
                           os.getpid(), time.time_ns(), suffix))


def is_staging_name(name: str) -> bool:
    """True for a staging file this module may have left behind."""
    return name.startswith(STAGING_PREFIX) and STAGING_INFIX in name


def clear_stale_staging(output: str) -> List[str]:
    """Remove staging files a killed run left beside `output`.

    Called with the lock held, so nothing being removed here can belong
    to a live run.  It matters because .gitignore re-includes everything
    under playthrough/: a staging file that outlived its process would
    otherwise be staged for commit as though it were the film.
    """
    directory = os.path.dirname(output)
    stem = os.path.splitext(os.path.basename(output))[0]
    removed: List[str] = []
    try:
        names = sorted(os.listdir(directory))
    except OSError as err:
        _warn("could not read %s to clear stale staging files (%s)"
              % (directory, err))
        return removed
    for name in names:
        if not is_staging_name(name):
            continue
        if not name.startswith(STAGING_PREFIX + stem + STAGING_INFIX):
            continue
        candidate = os.path.join(directory, name)
        if os.path.islink(candidate) or not os.path.isfile(candidate):
            continue
        try:
            os.unlink(candidate)
        except OSError as err:
            _warn("could not remove the stale staging file %s (%s)"
                  % (candidate, err))
            continue
        removed.append(candidate)
    return removed


def publish(staging: str, output: str) -> str:
    """Rename a verified staging file onto the canonical path.

    The file's own bytes are fsynced first, then the rename is made, then
    the directory entry is synced -- so a crash leaves either the old
    movie or the whole new one, never a name pointing at nothing.
    """
    try:
        descriptor = os.open(staging, os.O_RDONLY)
    except OSError as err:
        raise RenderError(
            "could not open the verified encode %s to flush it: %s"
            % (staging, err)) from err
    try:
        os.fsync(descriptor)
    except OSError as err:
        raise RenderError(
            "could not flush the verified encode %s: %s"
            % (staging, err)) from err
    finally:
        os.close(descriptor)
    # The staging file was created by ffmpeg under this process's umask;
    # the movie is a committed artifact read by players and by people, so
    # it carries the ordinary mode a plain open() would have produced.
    try:
        os.chmod(staging, 0o644)
        os.replace(staging, output)
    except OSError as err:
        raise RenderError(
            "could not publish the verified encode as %s: %s.  The "
            "previous movie is untouched." % (output, err)) from err
    fsync_directory(os.path.dirname(output))
    return output


def encode(
    plan: Plan,
    list_text: str,
    output: str,
    root: Optional[str] = None,
    list_path: Optional[str] = None,
) -> str:
    """Encode the film in one pass.  Returns the output path.

    THE LIST THE ENCODER IS HANDED IS THE BYTES THAT GET COMMITTED.  Its
    entries are spelled relative to its own directory, which is what
    ffmpeg's concat demuxer resolves them against, so it needs no second
    form to be runnable.  That matters beyond tidiness: while a transient
    absolute copy was handed to ffmpeg instead, the artifact committed as
    the film's input was never the input, and re-running the encode from
    the committed list failed outright.

    `list_path` is the file to hand ffmpeg, and the full render passes the
    STAGED list -- which sits in the published list's own directory, so
    every entry resolves identically and the bytes are moved into place by
    a rename afterwards rather than rewritten.  That is what lets the
    encode happen BEFORE the list is published without the encoder and the
    repository ever seeing different instructions.  It defaults to the
    published path for the concat-only and direct-call cases.

    The list is verified before it is used either way: every entry is
    re-read from the bytes on disk and resolved back to the planned
    absolute path, so a short or corrupted write, or an entry pointing
    outside the two approved directories, stops the encode instead of
    pacing a film from it.
    """
    allowed = [_captures_dir(root)]
    if plan.group_count:
        allowed.append(_transitions_dir(root))
    concat = list_path if list_path else default_concat_path(root)
    verify_committed_list(list_text, os.path.dirname(concat),
                          allowed, plan)
    ffmpeg = verified_tool(FFMPEG)
    # Run from the render root for consistency with every other stage.
    # The working directory no longer bears on how an entry resolves --
    # the demuxer resolves each one against the LIST's directory -- so
    # this is a convention rather than a load-bearing choice, and the
    # film is the same from any working directory.
    _run(encode_command(ffmpeg, concat, output,
                        plan.width, plan.height),
         render_root(root), "the ffmpeg encode")
    if not os.path.isfile(output):
        raise RenderError(
            "ffmpeg reported success but %s is not there" % output)
    return output


# ---------------------------------------------------------------------
# THE GENERATION: the concat list and the movie, published together
#
# THE DEFECT.  The list was written and published BEFORE the lock was
# taken and before a byte was encoded, and the movie was published after.
# Two consequences, both silent:
#
#   * A FAILED OR INTERRUPTED ENCODE left a NEW concat list beside an OLD
#     movie.  Each file was internally valid, the list described a film
#     that was never made, and nothing on disk recorded that they
#     disagreed -- so `ffprobe` on the movie and a read of the list gave
#     two different answers about the same session and both looked
#     authoritative.
#   * The list was published OUTSIDE the lock, so two runs could
#     interleave: one publishing its list while the other encoded from it.
#
# So the whole publication is now one generation.  The lock is taken
# first, the list is staged in its own target directory (which is what
# makes the encoder's bytes and the committed bytes the same bytes), the
# encode runs from the staged list, the container is verified, and only
# then are the list and the movie switched in -- with a durable journal
# naming both and the digest each is about to carry, so an interruption
# during the switch is detectable and finishable rather than permanent.
#
# build/movie.json is the committed half: it binds the movie to the
# timeline it was paced from, by that document's own digest, and to the
# list it was encoded from.  embed_captions.sh holds it against
# build/transcript.json to refuse a caption track from another session.
# ---------------------------------------------------------------------

BUILD_DIR_NAME = "build"
GENERATION_MANIFEST_NAME = "movie.json"


def generation_manifest_path(root: Optional[str] = None) -> str:
    """Return playthrough/build/movie.json.

    Joined onto the APPROVED root -- playthrough/ -- exactly as
    CONCAT_REL_PARTS is, because the manifest lives beside the concat list
    it describes.  render_root() is the parent of that and is what a
    concat ENTRY is spelled relative to; the two are one directory apart
    and confusing them puts the manifest outside the committed tree.
    """
    return _join(_approved_root(root),
                 (BUILD_DIR_NAME, GENERATION_MANIFEST_NAME))


def build_generation_manifest(
    plan: Plan,
    timeline_path: str,
    list_path: str,
    list_text: str,
    movie_path: str,
    probe: "Probe",
) -> Dict[str, Any]:
    """Return the provenance record for one published film.

    Deterministic: no timestamp, no host name, no absolute path.  The
    movie's digest is read from the STAGED file, whose bytes the publish
    step moves rather than rewrites.
    """
    return {
        "version": GENERATION_VERSION,
        "stage": LOCK_NAME,
        "timeline": {
            "path": relative_to_repo(timeline_path),
            "sha256": file_digest(timeline_path),
        },
        "concat_list": {
            "path": relative_to_repo(list_path),
            "sha256": hashlib.sha256(
                list_text.encode("utf-8")).hexdigest(),
            "bytes": len(list_text.encode("utf-8")),
        },
        "movie": {
            "path": relative_to_repo(movie_path),
            "sha256": file_digest(probe.path),
            "bytes": os.path.getsize(probe.path),
        },
        "expected_total": plan.expected_total,
        "capture_count": plan.capture_count,
        "group_count": plan.group_count,
        "width": plan.width,
        "height": plan.height,
    }


def write_generation_manifest(
    record: Mapping[str, Any],
    root: Optional[str] = None,
) -> str:
    """Write build/movie.json atomically.  Returns the path."""
    target = generation_manifest_path(root)
    parent = os.path.dirname(target)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as err:
        raise RenderError(
            "could not create %s for the generation manifest: %s"
            % (parent, err)) from err
    text = json.dumps(dict(record), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        dir=parent, prefix=".movie-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8",
                       newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:  # pragma: no cover - defensive
            pass
        raise
    _sync_directory(parent)
    return target


def publish_generation(
    plan: Plan,
    timeline_path: str,
    list_target: str,
    list_staging: str,
    list_text: str,
    movie_target: str,
    probe: "Probe",
    root: Optional[str] = None,
) -> Dict[str, Any]:
    """Switch in the concat list and the movie as one generation.

    Returns the manifest record that was written.  Called with the lock
    held and only after the container has been verified, so nothing here
    can fail for a reason that should have stopped the run.

    The journal goes down FIRST, durably, naming both targets and both
    digests.  Between the two renames the tree is momentarily half
    switched, and the journal is what makes that state readable instead of
    permanent: the next run reports exactly which file should hold what,
    and this stage -- deterministic for a given timeline -- finishes it by
    publishing again.
    """
    record = build_generation_manifest(
        plan, timeline_path, list_target, list_text, movie_target, probe)
    for problem in generation_journal_problems(LOCK_NAME, root):
        _warn("a previous render publication was interrupted: %s.  This "
              "run republishes both files from the same timeline, which "
              "repairs it" % problem)
    write_generation_journal(LOCK_NAME, {
        "version": GENERATION_VERSION,
        "stage": LOCK_NAME,
        "timeline": os.path.abspath(timeline_path),
        "targets": [
            {"path": os.path.abspath(list_target),
             "sha256": record["concat_list"]["sha256"]},
            {"path": os.path.abspath(movie_target),
             "sha256": record["movie"]["sha256"]},
        ],
    }, root)
    publish_concat_list(list_staging, list_target)
    publish(probe.path, movie_target)
    _assert_generation_published(record, list_target, movie_target)
    write_generation_manifest(record, root)
    clear_generation_journal(LOCK_NAME, root)
    return record


def _assert_generation_published(
    record: Mapping[str, Any],
    list_target: str,
    movie_target: str,
) -> None:
    """Prove both published files carry the digests just journalled.

    Re-read from disk rather than assumed, and checked BEFORE the journal
    is cleared, so a publication that cannot be verified leaves the
    journal in place for the next run to report.
    """
    for path, declared in ((list_target, record["concat_list"]["sha256"]),
                           (movie_target, record["movie"]["sha256"])):
        try:
            found = file_digest(path)
        except (TimelineError, OSError) as err:
            raise RenderError(
                "%s was published and cannot be re-read to verify it: "
                "%s.  The generation journal is left in place."
                % (path, err)) from err
        if found != declared:
            raise RenderError(
                "%s carries %s after publication and the generation was "
                "%s.  The generation journal is left in place so the "
                "next run reports the mixed state rather than accepting "
                "it." % (path, found[:16], declared[:16]))


# ---------------------------------------------------------------------
# Verification.  EVIDENCE OVER ASSERTION: the module measures the file
# it just produced and prints the measurement next to the number it was
# supposed to be, instead of reporting "ok".  A container that came up
# short is the one failure mode with no visible symptom -- every count
# still matches, the frames are all there, and only the length is wrong
# -- so the comparison is mandatory rather than optional.
# ---------------------------------------------------------------------

def probe_command(ffprobe: str, path: str) -> List[str]:
    """Return the ffprobe argument list.

    One invocation for everything: the container's duration and every
    stream's type, codec and geometry.  Asking once means the numbers
    that get compared all describe the same file at the same moment.

    `-count_packets` is what makes the image count checkable.  Under
    `-fps_mode vfr` the header's `nb_frames` is routinely absent, so
    without it a film that dropped or duplicated an image entry passes
    the codec, geometry and duration checks with nothing objecting.
    Counting packets demuxes the stream, which costs a pass over the
    file and is worth it for the one check that compares the picture
    count against the plan.
    """
    return [
        ffprobe,
        "-v", LOGLEVEL,
        "-count_packets",
        "-show_format",
        "-show_streams",
        "-of", PROBE_FORMAT,
        path,
    ]


def _number(value: Any) -> Optional[float]:
    """Return `value` as a finite float, or None.

    ffprobe writes "N/A" for a field it could not determine, and a
    missing duration must stay missing rather than becoming a zero that
    would then compare against the timeline as a catastrophic shortfall
    and hide the real cause.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _integer(value: Any) -> Optional[int]:
    """Return `value` as an int, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def probe_output(path: str, root: Optional[str] = None) -> Probe:
    """Measure the finished container with ffprobe.

    :raises RenderError: when the file is absent, trivially small, or
        ffprobe cannot parse it -- each of which is a failed encode that
        reported success.
    """
    if not os.path.isfile(path):
        raise RenderError("there is no movie at %s" % path)
    try:
        size = os.path.getsize(path)
    except OSError as err:
        raise RenderError(
            "could not size %s: %s" % (path, err)) from err
    if size < MIN_OUTPUT_BYTES:
        raise RenderError(
            "%s is %d byte(s), which is a container header and not a "
            "film; the smallest legitimate render is one 1920x1080 "
            "keyframe of real screen content and measures tens of "
            "kilobytes" % (path, size))
    ffprobe = verified_tool(FFPROBE)
    output = _run(probe_command(ffprobe, path),
                  render_root(root), "ffprobe", PROBE_TIMEOUT)
    try:
        parsed = json.loads(output)
    except ValueError as err:
        raise RenderError(
            "ffprobe did not return JSON for %s: %s" % (path, err)) from err
    if not isinstance(parsed, dict):
        raise RenderError(
            "ffprobe returned %s rather than an object for %s"
            % (type(parsed).__name__, path))
    container = parsed.get("format")
    container = container if isinstance(container, dict) else {}
    streams = parsed.get("streams")
    streams = streams if isinstance(streams, list) else []
    video = [stream for stream in streams
             if isinstance(stream, dict)
             if stream.get("codec_type") == CODEC_TYPE_VIDEO]
    audio = [stream for stream in streams
             if isinstance(stream, dict)
             if stream.get("codec_type") == CODEC_TYPE_AUDIO]
    first = video[0] if video else {}
    # The demuxed packet count is the stronger source and is preferred;
    # the header's nb_frames is a weaker fallback and is frequently
    # absent under VFR.  Neither available leaves the count None, which
    # verify_problems() reports as unmeasurable rather than passing.
    counted = _integer(first.get("nb_read_packets")) if video else None
    if counted is None and video:
        counted = _integer(first.get("nb_frames"))
    return Probe(
        duration=_number(container.get("duration")),
        video_streams=len(video),
        audio_streams=len(audio),
        codec_name=first.get("codec_name") if video else None,
        width=_integer(first.get("width")) if video else None,
        height=_integer(first.get("height")) if video else None,
        size=size,
        frames=counted,
        path=path,
    )


def verify_problems(
    plan: Plan,
    probe: Probe,
    tolerance: float = DURATION_TOLERANCE,
) -> List[str]:
    """Return every way the container disagrees with the plan.

    An empty list means: exactly one video stream, h264, at the
    resolution the captures were taken at, no audio stream at all, and a
    duration within `tolerance` of sum(durations) + sum(transitions).

    The duration comparison is the one that earns its keep.  It catches
    a dropped repeated final entry, a transition group whose emitted
    durations did not sum to the second the timeline charged, and a
    stale timeline.json -- three different defects, all silent, all
    caught by one subtraction.

    The PICTURE COUNT is checked beside it, because duration alone
    cannot see a dropped image that another entry's duration absorbed.
    The expected count is one per planned entry PLUS ONE for the
    repeated final entry, which the demuxer emits as a real picture.
    """
    problems: List[str] = []
    if probe.video_streams != 1:
        problems.append(
            "the container has %d video stream(s); a film assembled "
            "from one image sequence has exactly one"
            % probe.video_streams)
    if probe.audio_streams:
        problems.append(
            "the container has %d audio stream(s); there is no audio "
            "input, no music and no narration, so there must be none"
            % probe.audio_streams)
    if probe.video_streams:
        if probe.codec_name != CODEC_NAME_H264:
            problems.append(
                "the video codec is %r, not %r"
                % (probe.codec_name, CODEC_NAME_H264))
        if (probe.width, probe.height) != (plan.width, plan.height):
            problems.append(
                "the video is %sx%s, not the %dx%d the captures were "
                "taken at.  The X root is photographed, not the game "
                "window, so a smaller frame means something rescaled "
                "the film."
                % (probe.width, probe.height, plan.width, plan.height))
    if probe.duration is None:
        problems.append(
            "ffprobe could not determine the container duration, so it "
            "cannot be compared with the %.3f s the timeline computes"
            % plan.expected_total)
        return problems
    # One picture per planned entry, plus the repeated final entry.
    expected_frames = len(plan.entries) + 1 if plan.entries else 0
    if probe.frames is None:
        problems.append(
            "ffprobe reported neither a demuxed packet count nor "
            "nb_frames for the video stream, so the %d picture(s) the "
            "plan implies could not be confirmed.  Under -fps_mode vfr "
            "the header count is often absent, which is why the probe "
            "asks for -count_packets; a probe that returns neither "
            "cannot rule out a dropped or duplicated image"
            % expected_frames)
    elif probe.frames != expected_frames:
        problems.append(
            "the video stream carries %d picture(s) but the plan "
            "implies %d (%d entries plus the repeated final entry).  A "
            "count that disagrees means an image was dropped or "
            "duplicated, which no duration check can see once another "
            "entry's duration absorbs it"
            % (probe.frames, expected_frames, len(plan.entries)))
    drift = probe.duration - plan.expected_total
    if abs(drift) > tolerance:
        problems.append(
            "the container is %.3f s but the timeline computes %.3f s "
            "(%+.3f s, tolerance %.3f s). A container SHORTER than the "
            "timeline is the signature of a missing repeated final "
            "entry in the concat list, and every caption past the "
            "shortfall then points beyond the end of the film."
            % (probe.duration, plan.expected_total, drift, tolerance))
    return problems


def relative_to_repo(path: str) -> str:
    """Express a path relative to the checkout, for reporting.

    The summary is a machine-readable line that lands in run logs and in
    the report, and an absolute path there discloses the filesystem
    layout of the host -- the home directory, the operator's name, the
    build root -- to every reader of an artifact that says nothing about
    them otherwise.  Repository-relative is exactly the information the
    reader needs and none of the information they do not.

    A path outside the checkout is reduced to its basename behind a
    marker, so the line stays honest about the file being elsewhere
    without naming where.
    """
    try:
        checkout = os.path.dirname(_approved_root())
    except RenderError:  # pragma: no cover - defensive
        return os.path.basename(path)
    resolved = os.path.abspath(path)
    if resolved == checkout:
        return "."
    prefix = checkout + os.sep
    if resolved.startswith(prefix):
        return resolved[len(prefix):].replace(os.sep, "/")
    return "<outside the checkout>/%s" % os.path.basename(resolved)


def summary_line(
    plan: Plan,
    list_path: str,
    output: Optional[str] = None,
    probe: Optional[Probe] = None,
) -> str:
    """Return the one line run_pipeline.sh's operator reads.

    Both durations appear in it, side by side, whether or not they
    agreed: a summary that only prints a number when it is happy with it
    is a summary nobody can check.
    """
    parts = [
        "%d capture(s)" % plan.capture_count,
        "%d transition group(s)" % plan.group_count,
        "%d concat entr%s" % (len(plan.entries),
                              "y" if len(plan.entries) == 1 else "ies"),
        "expected %.3f s" % plan.expected_total,
    ]
    if probe is not None and probe.duration is not None:
        parts.append("container %.3f s (%+.3f s)"
                     % (probe.duration,
                        probe.duration - plan.expected_total))
    elif probe is not None:
        parts.append("container duration unavailable")
    parts.append("list %s" % relative_to_repo(list_path))
    if output is not None and probe is not None:
        parts.append("movie %s (%d bytes)"
                     % (relative_to_repo(output), probe.size))
    elif output is not None:
        parts.append("movie %s" % relative_to_repo(output))
    return "render_movie.py: " + ", ".join(parts)


# ---------------------------------------------------------------------
# The command line.  Nothing here can select a filter, a burned-in
# subtitle, an output frame rate or a resolution: those are properties
# of the requirement, not of a run, and an operator who could change
# them from the command line could produce a film that passes this
# module's own gates and fails the requirement.
# ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(
        prog="render_movie.py",
        description=(
            "Write playthrough/build/concat.txt from "
            "playthrough/timeline.json and encode "
            "playthrough/cata-play.mp4 from it in a single libx264 "
            "pass, giving every image the duration the timeline says "
            "it occupies so that video time tracks game time.  The "
            "finished container is then measured and its length "
            "printed next to the length the timeline computes."))
    parser.add_argument(
        "--timeline", default=None, metavar="PATH",
        help=("the timeline to read; defaults to PLAYTHROUGH_TIMELINE "
              "or <repository>/playthrough/timeline.json"))
    parser.add_argument(
        "--concat-list", default=None, metavar="PATH",
        help=("the concat list to write; defaults to "
              "PLAYTHROUGH_CONCAT_LIST or "
              "<repository>/playthrough/build/concat.txt"))
    parser.add_argument(
        "--output", default=None, metavar="PATH",
        help=("the movie to encode; defaults to PLAYTHROUGH_MOVIE or "
              "<repository>/playthrough/cata-play.mp4"))
    parser.add_argument(
        "--concat-only", action="store_true",
        help=("check every input and write the concat list, then stop "
              "without encoding; useful for inspecting the list, and "
              "it still runs the whole input contract"))
    parser.add_argument(
        "--tolerance", default=None, type=float, metavar="SECONDS",
        help=("how far the container may differ from the timeline "
              "total; defaults to %.2f s, which is twice the largest "
              "honest quantisation and well inside the smallest "
              "possible truncation.  Capped at %.2f s: past that the "
              "check stops being able to catch a truncated film, and it "
              "is the only check that can"
              % (DURATION_TOLERANCE, TOLERANCE_CEILING)))
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress the summary line on success")
    return parser


def _report(problems: Sequence[str]) -> None:
    """Print every problem on stderr, one per line."""
    for problem in problems:
        print("render_movie.py: %s" % problem, file=sys.stderr)


def _tolerance(value: Optional[float]) -> float:
    """Return the tolerance to hold the container to, checked."""
    if value is None:
        return DURATION_TOLERANCE
    number = float(value)
    if math.isnan(number) or math.isinf(number) or number < 0.0:
        raise RenderError(
            "--tolerance must be a finite, non-negative number of "
            "seconds, got %r" % (value,))
    if number > TOLERANCE_CEILING:
        raise RenderError(
            "--tolerance %.3f s is past the %.2f s ceiling and is "
            "REFUSED.  The duration comparison is the only check that "
            "can catch a truncated container -- every count still "
            "matches, every frame is present, and only the length is "
            "wrong -- so a tolerance wide enough to swallow a missing "
            "repeated final entry disables the one gate that would have "
            "noticed, and every caption past the shortfall then points "
            "beyond the end of the film.  The measured drift is printed "
            "in the summary either way, so a real disagreement can be "
            "read off a failing run without widening the gate."
            % (number, TOLERANCE_CEILING))
    if number > TOLERANCE_ADVISORY:
        _warn(
            "--tolerance %.3f s is wider than the %.2f s at which the "
            "comparison stops distinguishing an honest quantisation "
            "from a truncated container; the measured numbers are "
            "printed either way"
            % (number, TOLERANCE_ADVISORY))
    return number


def main(
    argv: Optional[Sequence[str]] = None,
    root: Optional[str] = None,
) -> int:
    """Run the command line and return an exit status.

    Zero only when every input checked out, the concat list was written
    and verified on disk, and -- unless --concat-only was given -- the
    encode succeeded and the finished container matched the timeline.  A
    run_pipeline.sh stage reads nothing but this status, so a status
    that is wrong is a whole stage that appears to have worked.

    `root` is a call site's argument and nothing else: argparse never
    produces it and no environment variable reaches it.  It exists so
    that a test can hold the REAL command line against a directory it
    owns instead of writing into the committed artifact tree, which is
    the captured evidence of a session and is not a fixture.
    """
    args = build_parser().parse_args(argv)
    try:
        tolerance = _tolerance(args.tolerance)
        # Both destinations are settled BEFORE the timeline is read and
        # long before anything is encoded.  An unusable --output is a
        # typo, and a typo should cost an operator a second rather than
        # the walk over every frame of a session and then an encode.
        output = (default_movie_path(root) if args.output is None
                  else _validated_output(args.output, "--output",
                                         MOVIE_SUFFIX, root))
        list_target = (default_concat_path(root)
                       if args.concat_list is None
                       else _validated_output(
                           args.concat_list, "--concat-list", root=root))
        source = (default_timeline_path() if args.timeline is None
                  else args.timeline)
        # ONE read, through the sibling's own hardened reader, so the
        # document this module encodes is the document make_srt.py
        # captions: held to the same containment and no-symlink rules
        # and opened with O_NOFOLLOW.
        document = read_timeline(source, root)
        if args.concat_only:
            # NO ENCODE, SO NO GENERATION.  --concat-only exists to let an
            # operator read the instruction sheet without spending a
            # render, and there is no movie for the list to be consistent
            # with -- so the list is published on its own, and it is the
            # ONE path that does that.
            plan = plan_render(document, root, source)
            list_path, _ = write_concat_list(plan, list_target, root)
            if not args.quiet:
                print(summary_line(plan, list_path))
            return EXIT_OK
        # PLAN, STAGE, ENCODE, VERIFY, THEN PUBLISH BOTH -- in that order
        # and ALL of it under the lock.  The list used to be published
        # before the lock was taken and before a byte was encoded, so a
        # failed encode left a new list beside an old movie: two valid
        # files describing different sessions, with nothing on disk saying
        # so.  Now the list is staged in its own target directory, the
        # encode runs from those exact bytes, the container is measured
        # while it is still a staging sibling, and the list and the film
        # are switched in together under a journal.
        # THE TRUST GATE, before the lock and before a byte is
        # encoded.  A film produced while a security check was relaxed
        # is not evidence, and this one would be committed.  It applies
        # only where the destination tree can publish -- a render into a
        # temporary root is not evidence and is not gated.
        assert_trusted_render(root)
        with ArtifactLock(LOCK_NAME, root):
            plan = plan_render(document, root, source)
            for stale in clear_stale_staging(output):
                _warn("removed a staging file a previous run left "
                      "behind: %s" % relative_to_repo(stale))
            for stale in clear_stale_staging(list_target):
                _warn("removed a staged concat list a previous run left "
                      "behind: %s" % relative_to_repo(stale))
            list_path, list_staging, list_text = stage_concat_list(
                plan, list_target, root)
            staging = staging_path(output)
            published = False
            try:
                encode(plan, list_text, staging, root, list_staging)
                probe = probe_output(staging, root)
                problems = verify_problems(plan, probe, tolerance)
                # The summary is printed BEFORE the verdict on purpose:
                # the numbers an operator needs in order to understand a
                # failure are the same numbers that describe a success.
                if not args.quiet or problems:
                    print(summary_line(plan, list_path, output, probe))
                if problems:
                    _report(problems)
                    print("render_movie.py: %d problem(s) found -- "
                          "NEITHER the concat list nor the encode was "
                          "published, so %s and %s are both whatever "
                          "they were before this run"
                          % (len(problems), relative_to_repo(list_path),
                             relative_to_repo(output)), file=sys.stderr)
                    return EXIT_FAILED
                publish_generation(
                    plan, source, list_path, list_staging, list_text,
                    output, probe, root)
                published = True
            finally:
                # A run that did not publish takes BOTH staged files with
                # it, so the tree is exactly as it was.  A run that did
                # published them by rename, so neither path is there.
                for leftover in ((staging, list_staging)
                                 if not published else ()):
                    if not os.path.exists(leftover):
                        continue
                    try:
                        os.unlink(leftover)
                    except OSError as err:  # pragma: no cover
                        _warn("could not remove the staging file %s (%s)"
                              % (leftover, err))
    except RenderError as err:
        print("render_movie.py: %s" % err, file=sys.stderr)
        return EXIT_FAILED
    except TimelineError as err:
        print("render_movie.py: %s" % err, file=sys.stderr)
        return EXIT_FAILED
    except make_transitions.TransitionError as err:
        print("render_movie.py: %s" % err, file=sys.stderr)
        return EXIT_FAILED
    except OSError as err:
        print("render_movie.py: %s" % err, file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
