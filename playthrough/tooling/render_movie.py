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

So the COMMITTED list keeps the documented, portable, reviewable form
-- single-quoted and repository-root-relative, which is the only form
that means the same thing in every checkout -- and the encode is driven
by a transient list whose entries are that same sequence made absolute.
The transient list is DERIVED FROM THE BYTES THAT WERE WRITTEN, so what
the encoder consumed is provably the committed sequence: every duration
line is copied verbatim and every file line is the committed relative
path with the render root prefixed.  Because those entries are
absolute, the transient list's own location is irrelevant to how they
resolve -- which is why it is put OUTSIDE the working tree and removed
in a finally block.  Nothing this module writes into playthrough/ is
ever anything but the two committed artifacts, so a crashed run cannot
leave a scratch file behind for commit_artifacts.sh to stage.

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
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from typing import (Any, Dict, List, NamedTuple, Optional, Sequence,
                    Tuple)

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
    from timeline import (CEIL, EPSILON, FLOOR, TimelineError,
                          approved_root, default_timeline_path,
                          read_timeline, round_seconds, timeline_total,
                          validate_timeline)
except ImportError:
    # Imported from somewhere other than this directory: put the
    # tooling directory on the path and try once more.  A second
    # failure is a genuinely broken checkout and is allowed to raise.
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from timeline import (CEIL, EPSILON, FLOOR, TimelineError,
                          approved_root, default_timeline_path,
                          read_timeline, round_seconds, timeline_total,
                          validate_timeline)

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
# anything, so asking for one is reported.  It is not refused -- an
# operator on a different ffmpeg may legitimately need room -- but it
# is never granted quietly.
TOLERANCE_ADVISORY = 0.25

# ---------------------------------------------------------------------
# The concat list's shape.  Spelled as constants because the writer and
# the reader of these bytes are both in this file and must not drift,
# and because the transient encode list is derived by re-reading them.
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
    """Report something an operator must see but that is not fatal."""
    print("render_movie.py: %s" % message, file=sys.stderr)


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
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise RenderError(
            "%s is not a regular file: %s" % (label, resolved))
    if suffix is not None and not resolved.lower().endswith(suffix):
        raise RenderError(
            "%s must name a %s file, got %s.  The container format is "
            "chosen by extension, and the caption track embed_captions."
            "sh adds later is an MP4 feature."
            % (label, suffix, resolved))
    return resolved


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

    The committed list carries this form and only this form.  A result
    that climbs out of the base or stays absolute is refused rather than
    written, because an entry ffmpeg would resolve against the wrong
    directory is exactly the defect this spelling exists to avoid.  A
    single quote is refused too: the concat script format has no way to
    escape one inside a single-quoted entry, so a path containing one
    could not be expressed at all and must not be silently mangled into
    something that parses as a different file.
    """
    relative = os.path.relpath(absolute, base)
    if os.path.isabs(relative) or relative.split(os.sep)[0] == os.pardir:
        raise RenderError(
            "%s is not inside %s, so it cannot be written as a "
            "repository-relative concat entry (relpath gave %s)"
            % (absolute, base, relative))
    entry = relative.replace(os.sep, CONCAT_SEPARATOR)
    if CONCAT_FILE_SUFFIX in entry:
        raise RenderError(
            "%s contains a single quote, which the concat script "
            "format cannot express inside a quoted entry: %s"
            % (absolute, entry))
    return entry


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
    return candidate


# ---------------------------------------------------------------------
# Durations.  The concat list is the one place the timeline's numbers
# become text, so the formatting is exact and the transition split is
# arithmetic rather than an approximation.
# ---------------------------------------------------------------------

# Microsecond resolution in the list.  The timeline itself is written at
# millisecond resolution, but a transition second divided twelve ways is
# not expressible in milliseconds, and rounding it there would leave the
# group short or long by up to 4 ms EVERY TIME the ceiling engages --
# which the container would then disagree with the captions about, once
# per transition, cumulatively.
DURATION_DECIMALS = 6
MICROSECONDS = 10 ** DURATION_DECIMALS


def format_duration(seconds: float) -> str:
    """Return `seconds` as a concat duration value.

    Fixed at microsecond resolution and then stripped of trailing
    fractional zeros, so 0.25 stays "0.25", 10.0 stays "10.0" and a
    twelfth of a second becomes "0.083333" -- the documented shape, and
    deterministic, which is what makes a re-run byte-identical.

    The stripping is confined to the fractional part on purpose: a naive
    rstrip("0") over the whole string turns "100.000000" into "1".
    """
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
    whole, _, fraction = format(
        number, ".%df" % DURATION_DECIMALS).partition(".")
    return whole + "." + (fraction.rstrip("0") or "0")


def transition_durations(
    seconds: float,
    count: Optional[int] = None,
) -> List[float]:
    """Split a transition's seconds across its frames, EXACTLY.

    The timeline charges exactly `seconds` of video time per transition
    and the container has to agree, so the split is done in whole
    microseconds and the remainder is distributed one microsecond at a
    time across the leading frames rather than dropped.  Twelve frames
    over one second therefore come out as four at 0.083334 s and eight
    at 0.083333 s, which sums to 1.000000 s and not to 0.999996 s.

    That difference looks negligible and is not: a group that falls 4 us
    short would drift the picture away from the cues by that much every
    time the ceiling engages, in the same direction, for the rest of the
    film.
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
    total = int(round(number * MICROSECONDS))
    base, remainder = divmod(total, frames)
    if base <= 0:
        raise RenderError(
            "a transition of %r s cannot be split across %d frames at "
            "microsecond resolution" % (seconds, frames))
    shares = [base + 1] * remainder + [base] * (frames - remainder)
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
) -> Plan:
    """Resolve and check every input before a byte is written.

    THE WHOLE OF THE INPUT CONTRACT IS ASSERTED HERE, so that a defect
    stops the run while the previous concat list and the previous movie
    are still intact and still consistent with each other.  In order:
    the document satisfies its own invariant; the transition length is
    the one that can be materialised; every entry's frame index,
    duration and flag are well formed; every capture named exists and
    lies inside playthrough/frames/; every flagged entry's group is
    exactly on disk; and the total the entries imply is the total the
    document declares.

    A MISSING FRAME ABORTS AND IS NEVER SKIPPED.  Skipping one would
    preserve every appearance of success -- the encode would run, the
    container would be produced -- while breaking the
    one-frame-per-keystroke invariant and shifting every caption after
    it by that frame's window.
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

    # The sibling's own validator, run for the document form exactly as
    # make_srt.py runs it.  It holds the clamp bounds, the
    # strictly-greater transition rule, the contiguity of the cue
    # windows and the invariant sum(durations) + sum(transitions) ==
    # total == final cue end.  A film encoded from a document that fails
    # its own invariant would be paced by numbers the captions do not
    # share, and the two would look consistent while disagreeing.
    if isinstance(document, dict):
        problems = validate_timeline(document)
        if problems:
            raise RenderError(
                "the timeline does not satisfy its own invariants, so "
                "the film it paces would not match the captions "
                "make_srt.py writes from the same document (%d "
                "problem(s)): %s"
                % (len(problems), "; ".join(problems)))

    base = render_root(root)
    captures = _captures_dir(root)
    transitions: Optional[str] = None
    shares = transition_durations(seconds)

    planned: List[ConcatEntry] = []
    durations: List[float] = []
    flags: List[bool] = []
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
            planned.append(ConcatEntry(
                path, _relative_entry(path, base), share,
                KIND_TRANSITION, index, ordinal))
        groups += 1

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
# The concat list.  Two forms of the same sequence: the committed one,
# repository-root-relative so that it means the same thing in every
# checkout, and the transient one the encoder is actually handed, made
# absolute because ffmpeg would otherwise resolve every entry against
# the list's own directory.  See the module docstring for the
# measurement that forced the split.
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
    """
    if not plan.entries:
        raise RenderError("there are no entries to write")
    lines: List[str] = []
    for entry in plan.entries:
        lines.append(
            CONCAT_FILE_PREFIX + entry.relative + CONCAT_FILE_SUFFIX)
        lines.append(
            CONCAT_DURATION_PREFIX + format_duration(entry.duration))
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


def encode_list_text(
    committed: str,
    base: str,
    allowed: Sequence[str],
) -> str:
    """Return the list the ENCODER is handed, derived from the committed
    bytes.

    Every `duration` line is copied verbatim and every `file` line is
    the committed relative entry with `base` prefixed, so the sequence
    ffmpeg consumes is provably the sequence that was committed -- same
    order, same count, same durations, and each path the same file.  The
    absolute spelling is what makes the entries independent of the
    directory the list happens to sit in, which is the whole reason this
    second form exists (see the module docstring).

    Deriving it from the bytes rather than from the plan is deliberate:
    it means a short or corrupted write is caught here, because the
    derivation would then not reproduce the plan's line count.
    """
    lines: List[str] = []
    for number, line in enumerate(committed.splitlines(), start=1):
        if line.startswith(CONCAT_FILE_PREFIX):
            if not line.endswith(CONCAT_FILE_SUFFIX):
                raise RenderError(
                    "concat list line %d is not a closed quoted entry: "
                    "%r" % (number, line))
            head = len(CONCAT_FILE_PREFIX)
            tail = len(line) - len(CONCAT_FILE_SUFFIX)
            relative = line[head:tail]
            lines.append(
                CONCAT_FILE_PREFIX +
                _absolute_entry(relative, base, allowed) +
                CONCAT_FILE_SUFFIX)
        elif line.startswith(CONCAT_DURATION_PREFIX):
            lines.append(line)
        else:
            raise RenderError(
                "concat list line %d is neither a file nor a duration "
                "entry: %r" % (number, line))
    if not lines:
        raise RenderError("the concat list is empty")
    return CONCAT_NEWLINE.join(lines) + CONCAT_NEWLINE


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


def write_concat_list(
    plan: Plan,
    path: Optional[str] = None,
    root: Optional[str] = None,
) -> Tuple[str, str]:
    """Write the committed concat list.  Returns (path, text written).

    The parent build directory is created if it is not there, because
    this module owns build/concat.txt and creating its directory is the
    whole of its directory management -- build/transitions/ belongs to
    make_transitions.py.

    The bytes are read back after the write and compared with what was
    intended, and the structural file-equals-duration-plus-one relation
    is asserted on the bytes that are actually on disk rather than on
    the string in memory.  A concat list is the instruction sheet for
    the encode; verifying the instruction sheet costs microseconds and
    catches a full disk.
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
    text = format_concat_list(plan)
    concat_counts(text)
    write_text(target, text)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            written = handle.read()
    except OSError as err:
        raise RenderError(
            "could not read back the concat list %s: %s"
            % (target, err)) from err
    if written != text:
        raise RenderError(
            "the concat list on disk is not what was written to %s (%d "
            "bytes intended, %d bytes read back)"
            % (target, len(text), len(written)))
    concat_counts(written)
    return target, written


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


def _run(command: Sequence[str], cwd: str, label: str) -> str:
    """Run a tool and return its standard output, or raise.

    Standard input is /dev/null because ffmpeg reads the terminal for
    interactive commands and will otherwise consume whatever the parent
    was reading -- observed on this host swallowing the remainder of a
    shell script and printing its own "Enter command:" prompt.  Standard
    error is captured and SURFACED on failure rather than swallowed: the
    one line that says which frame could not be opened is the whole
    diagnostic.
    """
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
    except OSError as err:
        raise RenderError(
            "could not run %s: %s" % (label, err)) from err
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        raise RenderError(
            "%s exited %d.%s"
            % (label, completed.returncode,
               ("  It said: " + detail) if detail else ""))
    return completed.stdout or ""


def encode(
    plan: Plan,
    list_text: str,
    output: str,
    root: Optional[str] = None,
) -> str:
    """Encode the film in one pass.  Returns the output path.

    The committed list's bytes are turned into the absolute-entry form
    the demuxer can actually resolve, that form is written to a
    transient file, and ffmpeg is run from the render root with it.

    THE TRANSIENT LIST LIVES OUTSIDE THE WORKING TREE.  Its entries are
    absolute, so where the file sits has no bearing on how they resolve,
    and putting it in the system temporary directory means a run killed
    between the write and the unlink cannot leave a scratch file inside
    playthrough/ for commit_artifacts.sh to stage.  The two committed
    artifacts remain the only things this module writes into the tree.
    """
    base = render_root(root)
    allowed = [_captures_dir(root)]
    if plan.group_count:
        allowed.append(_transitions_dir(root))
    encode_text = encode_list_text(list_text, base, allowed)
    if concat_counts(encode_text) != concat_counts(list_text):
        raise RenderError(
            "the encoder's list does not have the same shape as the "
            "committed list; refusing to encode a sequence that is not "
            "the one on disk")
    ffmpeg = verified_tool(FFMPEG)
    descriptor, transient = tempfile.mkstemp(
        prefix="render_movie-concat-", suffix=".txt")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8",
                       newline=CONCAT_NEWLINE) as handle:
            handle.write(encode_text)
            handle.flush()
            os.fsync(handle.fileno())
        _run(encode_command(ffmpeg, transient, output,
                            plan.width, plan.height),
             base, "the ffmpeg encode")
    finally:
        try:
            os.unlink(transient)
        except OSError as err:
            _warn("could not remove the transient encode list %s (%s)"
                  % (transient, err))
    if not os.path.isfile(output):
        raise RenderError(
            "ffmpeg reported success but %s is not there" % output)
    return output


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
    """
    return [
        ffprobe,
        "-v", LOGLEVEL,
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
                  render_root(root), "ffprobe")
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
    return Probe(
        duration=_number(container.get("duration")),
        video_streams=len(video),
        audio_streams=len(audio),
        codec_name=first.get("codec_name") if video else None,
        width=_integer(first.get("width")) if video else None,
        height=_integer(first.get("height")) if video else None,
        size=size,
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
    parts.append("list %s" % list_path)
    if output is not None and probe is not None:
        parts.append("movie %s (%d bytes)" % (output, probe.size))
    elif output is not None:
        parts.append("movie %s" % output)
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
              "possible truncation" % DURATION_TOLERANCE))
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
        plan = plan_render(document, root)
        list_path, list_text = write_concat_list(
            plan, list_target, root)
        if args.concat_only:
            if not args.quiet:
                print(summary_line(plan, list_path))
            return EXIT_OK
        encode(plan, list_text, output, root)
        probe = probe_output(output, root)
        problems = verify_problems(plan, probe, tolerance)
        # The summary is printed BEFORE the verdict on purpose: the
        # numbers an operator needs in order to understand a failure are
        # the same numbers that describe a success.
        if not args.quiet or problems:
            print(summary_line(plan, list_path, output, probe))
        if problems:
            _report(problems)
            print("render_movie.py: %d problem(s) found"
                  % len(problems), file=sys.stderr)
            return EXIT_FAILED
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
