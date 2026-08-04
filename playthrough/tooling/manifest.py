#!/usr/bin/env python3
"""Append-only JSON Lines writer for playthrough/manifest.jsonl.

One JSON object per line, one line per captured frame, one captured
frame per keystroke.  The manifest is the record that the session
happened: every row ties one keystroke to the PNG it produced, to the
wall-clock instant of that capture, to the sidebar clock as it was
actually read from that PNG, and to the survivor's own reason for
acting.  That record is evidence, and evidence is not rewritten, so this
module only ever appends.

SCHEMA -- exactly six keys, in this order, on every row:

    frame         int       monotonic index from 1, supplied by the
                            caller; this module never generates it
    file          str       "playthrough/frames/frame_%05d.png" from
                            the index, matching what capture.sh wrote
    real_ts       str       UTC wall-clock instant of the capture, one
                            fixed sortable form on every row; supplied
                            by the caller, never defaulted here
    ingame_clock  str|None  the sidebar clock AS READ, or JSON null --
                            the ONLY nullable field in the schema
    action        str       the single keystroke plus enough plain
                            description to be unambiguous
    commentary    str       the survivor's first-person reason for it

Nothing else is permitted, and a row carrying an unexpected key or
missing a required one is refused rather than written.  Durations,
transition flags and caption cue windows belong to
playthrough/timeline.json, the single source of truth for timing;
recording them here as well would create the second source of truth the
pipeline exists to avoid.  Engineering and diagnostic observations
belong to playthrough/TECHNICAL_NOTES.md.

``ingame_clock`` IS THE HONESTY FIELD.  ``display::time_string()``
(src/display.cpp:207-218) returns an exact time only when the survivor
has a watch; otherwise one of the coarse phrases from
``display::time_approx()`` (src/display.cpp:159-185), otherwise "???".
Under the seeded 24_HOUR=24h option an exact reading is fixed-width
"%02d:%02d:%02d" (src/calendar.cpp:638-663), which is what makes it
legible at all.  When the clock could not be read the value is None and
serialises as JSON null.  It is never interpolated, never carried
forward from the previous row and never guessed; reconciling an
unreadable or non-monotonic reading is timeline.py's job, downstream and
visibly flagged.  This module records what was seen.

THE WRITE CONTRACT.  A row is not reported as appended until it has been
written, flushed AND forced to the device; a failure anywhere on that
path raises ManifestError rather than being downgraded to a warning,
because the frame-count identity is checked against this file.
``real_ts`` is mandatory and taking it is deliberately the caller's act:
this module will not stamp "now" on the caller's behalf, because the
instant a row is appended is not the instant the frame was captured, and
quietly recording one as the other is fabricated evidence.
:func:`append_row` documents the fields it takes and what it guarantees.

THE COMMAND LINE IS READ-ONLY on purpose -- appending is available to
importers only, so session.py keeps sole ownership of the frame counter
and no shell caller can slip a row in beside it:

    python3 playthrough/tooling/manifest.py verify --require-frames
    python3 playthrough/tooling/manifest.py count

The command line is read-only on purpose: appending is available to
importers only, so that session.py keeps sole ownership of the frame
counter and no shell caller can slip a row in beside it.

Where the record may live is not negotiable.  Every path this module
opens -- for reading as well as for appending -- must resolve inside
the playthrough/ directory derived from this module's OWN location,
with no symlinked component, and is opened with O_NOFOLLOW.
PLAYTHROUGH_MANIFEST, PLAYTHROUGH_FRAMES_DIR and a --manifest argument
are honoured within that tree and refused outside it: a record that an
environment variable could redirect to /etc/passwd, to a device node
or to somebody else's checkout would not be evidence of anything.  The
append itself is serialised with an exclusive fcntl advisory lock that
is MANDATORY -- a lock that cannot be taken refuses the write rather
than proceeding unserialised -- so two writers that both come through
this module cannot interleave a row, and a failed append's rollback
cannot remove bytes the other put there.  Being advisory, it says
nothing about a reader that does not take it, which is why the readers
refuse an unparseable line instead of trusting the lock.

Standard library only -- nothing here needs
playthrough/tooling/requirements.txt.  fcntl makes this POSIX-only,
which matches the pipeline's Linux/X11 scope.  Paths follow
playthrough/tooling/env.sh, the single definition of the artifact
layout, whose PLAYTHROUGH_MANIFEST, PLAYTHROUGH_FRAMES_DIR and
PLAYTHROUGH_FRAME_FORMAT exports are honoured when they are set.
"""

import argparse
import datetime
import errno
import fcntl
import json
import os
import re
import sys


# The schema, in the order rows are written.  Exactly these six keys,
# on every row, always.  The tuple is the authority: the writer, the
# reader and the verifier all derive their expectations from it.
FIELDS = (
    "frame",
    "file",
    "real_ts",
    "ingame_clock",
    "action",
    "commentary",
)

# One capture per keystroke, indexed from 1.  The five-digit
# zero-padded field is what keeps a lexical sort of the frames
# identical to a numeric one, which is what makes the ffmpeg concat
# list trivially correct -- so an index that would widen the field is
# a real defect and is refused, not silently formatted.
MIN_FRAME_INDEX = 1
MAX_FRAME_INDEX = 99999

# The frame path recorded in the `file` field: repository-relative, so
# the manifest stays valid in any checkout, and built from one format
# shared with env.sh's PLAYTHROUGH_FRAME_FORMAT so that the capturer,
# this writer and the concat list agree byte for byte.
FRAMES_REL_DIR = "playthrough/frames"
FRAME_NAME_FORMAT = "frame_%05d.png"
FRAME_FILE_FORMAT = FRAMES_REL_DIR + "/" + FRAME_NAME_FORMAT

# The one name this module reads or appends to, defined once and used by
# both default_manifest_path() and the target validator below.  The
# record of a session lives at exactly <approved root>/manifest.jsonl
# and nowhere else: see _validated_manifest_target() for why the exact
# path, and not merely containment, is what is required.
MANIFEST_NAME = "manifest.jsonl"

# real_ts: the wall-clock instant of the capture, in UTC, to the
# millisecond, in one fixed form on every row so that the column sorts
# lexically as well as chronologically.  Production metadata only --
# video pacing comes from the in-game clock, never from here.
REAL_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
REAL_TS_SUFFIX = "Z"
REAL_TS_EXAMPLE = "2026-05-14T09:12:03.481Z"

# An exact reading under the seeded 24_HOUR=24h option: fixed-width
# "%02d:%02d:%02d" (src/calendar.cpp:649).
CLOCK_24H_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

# The RANGE half of that contract, which the shape alone does not carry.
# to_string_time_of_day formats the three fields from a time of day, so
# "24:00:00", "23:60:00" and "99:99:99" are all fixed-width and
# clock-shaped while saying something no clock in this game can show.
# ocr_clock.py enforces exactly these bounds on the reading side and
# DECLINES such a value rather than repairing it into a plausible time;
# the same numbers live here so that the writer cannot label a reading
# 'exact' that its sibling would have refused to emit at all.
CLOCK_MAX_HOUR = 23
CLOCK_MAX_MINUTE = 59
CLOCK_MAX_SECOND = 59

# Bounds on the free-text fields, both about what happens to these
# strings AFTER this file: `action` and `commentary` are copied into
# playthrough/transcript.md and become the SRT cue text.
#
# MAX_FIELD_LENGTH is a refusal and is set far above anything a person
# writes, so it catches machine output and runaway loops without ever
# arguing with legitimate prose.  CUE_ADVISORY_LENGTH is only an
# advisory, and its value comes from the other end of the pipeline: a
# cue occupies its frame's on-screen window, timeline.py caps that
# window at 10 s, and a few hundred characters is what a reader gets
# through in that time.
MAX_FIELD_LENGTH = 2000
CUE_ADVISORY_LENGTH = 400

# The two other shapes to_string_time_of_day can emit: "military"
# "%02d%02d.%02d" (src/calendar.cpp:646) and the 12h default
# "%d:%02d:%02d%sAM/PM" with variable padding (src/calendar.cpp:
# 657-661).  seed_options.py selects 24h precisely because these are
# hostile to a fixed-width read, so a reading in either shape is
# genuine but off-contract and is reported rather than refused.
CLOCK_MILITARY_RE = re.compile(r"^\d{4}\.\d{2}$")
CLOCK_12H_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2} ?[AP]M$")

# The coarse phrases display::time_approx() can return, verbatim and
# in source order (src/display.cpp:159-185), plus the value
# display::time_string() falls back to when the sky is not visible
# (src/display.cpp:216).  A reading that is one of these is a genuine
# observation of the frame, not a failure.
COARSE_TIME_PHRASES = (
    "Around midnight",
    "Around dawn",
    "Around dusk",
    "Dead of night",
    "Night",
    "Early morning",
    "Morning",
    "Around noon",
    "Afternoon",
    "Early evening",
    "Evening",
)
UNKNOWN_TIME_TEXT = "???"

# The classifications classify_ingame_clock() can return.  They exist
# so that timeline.py and verify_artifacts.sh can reason about a
# reading without re-deriving these regular expressions.
CLOCK_NULL = "null"
CLOCK_EXACT = "exact"
CLOCK_NONSTANDARD = "nonstandard"
CLOCK_COARSE = "coarse"
CLOCK_UNKNOWN = "unknown"
CLOCK_UNRECOGNISED = "unrecognised"

# Out-of-character vocabulary.  `commentary` is part of the
# in-character record, so this list mirrors the substring grep the
# transcript gate applies downstream -- deliberately including its
# bluntness, so that a warning here predicts a failure there.  It is
# advisory only: a hit is reported, never rewritten.
META_VOCABULARY = (
    "frame", "screenshot", "capture", "ocr", "ffmpeg", "moviepy",
    "manifest", "timeline", "keystroke", "xdotool", "pipeline",
    "tileset", "sidebar", "commit", "option",
)

# Markers saying a field was never filled in.  Unlike META_VOCABULARY
# beside it these are REFUSALS, not advisories: a row is the
# authoritative record of what one keystroke did and why, and every
# structural check -- the six-field schema, the 1..n identity, the
# frame-set equality -- passes straight over a field reading
# "placeholder".
PLACEHOLDER_WORDS = (
    "placeholder", "todo", "fixme", "tbd", "xxx", "wip",
)

# Phrases whose presence in an `action` says the field does not describe
# the keystroke: an action that defers to a note elsewhere is not a
# record of what was pressed, it is a promise that the record is
# somewhere else.
UNRECORDED_ACTION_PHRASES = (
    "see note", "see technical_notes", "unknown key", "unknown action",
    "not recorded", "see below", "see above",
)

_SENTINEL_WORD_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(PLACEHOLDER_WORDS), re.IGNORECASE)


class ManifestError(Exception):
    """A row was refused, or a manifest on disk is malformed.

    Raised in place of writing, so that a bad row never reaches the
    file: a manifest that is wrong is worse than a session that stops,
    because the count identity between the frames directory and this
    file is what proves one capture per keystroke.
    """


# Keys of the warnings already emitted in this process, so that an
# advisory about a standing condition is reported once instead of once
# per row.  Mutated only through _warn_once().
_WARNED = set()


def _warn(message):
    """Report a non-fatal problem on stderr and carry on.

    The prefix matches playthrough_warn() in
    playthrough/tooling/env.sh, so that every stage of the pipeline
    reports in one recognisable form in the session log.
    """
    print("playthrough: WARNING: manifest.py: %s" % message,
          file=sys.stderr, flush=True)


def _warn_once(key, message):
    """Warn about `key` the first time it is seen in this process."""
    if key in _WARNED:
        return
    _WARNED.add(key)
    _warn(message)


def _module_dir():
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _playthrough_dir():
    """Return the absolute playthrough/ directory.

    Derived from this module's own location rather than from the
    working directory, so a helper is correct even when it is invoked
    from somewhere other than the repository root.
    """
    return os.path.dirname(_module_dir())


def repo_root():
    """Return the repository root, from this module's own location.

    playthrough/tooling -> playthrough -> the checkout.  Derived rather
    than read from the environment for the same reason approved_root()
    is: a path a variable could move is not a path anything may be
    reported relative to.
    """
    return os.path.realpath(os.path.dirname(_playthrough_dir()))


def relative_to_repo(path):
    """Return `path` spelled relative to the repository root.

    THE ONLY FORM A MACHINE SUMMARY REPORTS.  An absolute path discloses
    the checkout's location on the host -- and these summaries are
    written into logs that are kept, quoted into reports and read by
    people who have no business knowing where somebody else's clone
    lives.  Every artifact this pipeline touches is inside the checkout,
    so the relative form is complete as well as smaller: it is what a
    reader would type.

    A path that genuinely lies outside the checkout is returned as its
    basename with a marker rather than as a traversal, because "../.."
    still discloses depth and an outside path is a fault to notice, not
    a location to publish.
    """
    if path is None:
        return ""
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    text = str(path)
    if not text:
        return ""
    base = repo_root()
    resolved = os.path.realpath(os.path.abspath(text))
    if resolved == base:
        return "."
    if resolved.startswith(base + os.sep):
        return os.path.relpath(resolved, base)
    return "<outside the checkout>/" + os.path.basename(resolved)


def approved_root(root=None):
    """Return the only directory tree this module may read or write.

    Derived from this module's own location and NEVER from the
    environment.  That is the whole point: PLAYTHROUGH_MANIFEST, a
    --manifest argument and a caller's typo are all untrusted input,
    and a record of what was captured is not evidence if any of them
    can move it somewhere else on the host.  playthrough/ is the root
    because every artifact of this pipeline lives beneath it.

    `root` exists so that a test can point exactly the same rules at a
    temporary directory it owns, which is the only supported way to
    relocate the tree -- it is an explicit argument at the call site,
    not something an environment variable can reach.
    """
    if root is None:
        return os.path.realpath(_playthrough_dir())
    if isinstance(root, os.PathLike):
        root = os.fspath(root)
    if not isinstance(root, str):
        raise ManifestError(
            "the approved root must be a string path, got %s"
            % type(root).__name__)
    if not root.strip():
        raise ManifestError("the approved root must not be empty")
    if "\x00" in root:
        raise ManifestError(
            "the approved root must not contain a NUL byte")
    resolved = os.path.realpath(root)
    if not os.path.isdir(resolved):
        raise ManifestError("no approved root at %s" % resolved)
    return resolved


def _within(path, root):
    """Return True when `path` is `root` itself or lies beneath it."""
    return path == root or path.startswith(root + os.sep)


def _assert_within_root(resolved, label, root=None):
    """Refuse a path that does not resolve inside the approved root.

    The FULLY RESOLVED form is what is tested, so `../` sequences and
    a symlink pointing out of the tree are both caught: /etc/passwd,
    /dev/anything and a sibling checkout are refused rather than
    written.  This is the check that makes it safe to accept a path
    from the environment or the command line at all.

    Returns the approved root, so a caller can pass it straight to
    _assert_no_symlink() without deriving it twice.
    """
    approved = approved_root(root)
    canonical = os.path.realpath(resolved)
    if not _within(canonical, approved):
        raise ManifestError(
            "%s must stay inside %s, but %s resolves to %s"
            % (label, approved, resolved, canonical))
    return approved


def _assert_no_symlink(resolved, root, label):
    """Refuse `resolved` if it or a component below `root` is a link.

    Containment alone is not enough.  A link INSIDE the tree still
    points somewhere else inside the tree, so one planted link could
    redirect every appended row into another artifact -- the frames
    directory, the timeline, the movie -- and the append would look
    entirely successful.  The final component is checked first because
    that is the case that is well defined however the path was
    spelled; the walk then covers every directory between the root and
    the file.
    """
    if os.path.islink(resolved):
        raise ManifestError(
            "%s is a symbolic link: %s.  This module writes files, it "
            "does not follow links to them." % (label, resolved))
    if not _within(resolved, root):
        # The path reaches the tree through a symlinked ancestor ABOVE
        # the root -- a checkout under a linked directory, say.
        # _assert_within_root() has already proved the destination is
        # inside the tree, and components above the root are not this
        # module's business, so there is nothing further to walk.
        return
    current = root
    for part in os.path.relpath(resolved, root).split(os.sep):
        if part in ("", os.curdir):
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ManifestError(
                "%s has a symlinked component at %s; a link there "
                "could redirect the record inside %s"
                % (label, current, root))


def _open_nofollow(path, flags, mode=0o600):
    """Open `path` without following it if it is a symlink.

    O_NOFOLLOW makes the kernel refuse the final component when it is
    a link, which closes the window between the check above and this
    open: a link planted in between fails the syscall instead of being
    followed.  The mode matters only when the file is created, and it
    is private because a manifest row records what the survivor's
    screen showed; git records only the executable bit, so nothing
    about the committed artifact changes.
    """
    try:
        return os.open(path, flags, mode)
    except OSError as err:
        if err.errno in (errno.ELOOP, errno.EMLINK):
            raise ManifestError(
                "the manifest path is a symbolic link: %s.  Refusing "
                "to follow it." % path) from err
        raise ManifestError(
            "could not open the manifest %s: %s" % (path, err)) from err


def default_manifest_path():
    """Return the manifest this pipeline writes and reads.

    Honours PLAYTHROUGH_MANIFEST from playthrough/tooling/env.sh when
    it is set, because that file is the single definition of the
    artifact layout, and otherwise falls back to
    <repository>/playthrough/manifest.jsonl derived from this module's
    location -- so the module is still correct when nothing has been
    sourced, as when it is imported by an ad-hoc test.
    """
    from_env = os.environ.get("PLAYTHROUGH_MANIFEST")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), MANIFEST_NAME)


def default_frames_dir():
    """Return the directory holding one PNG per keystroke.

    Honours PLAYTHROUGH_FRAMES_DIR for the same reason
    default_manifest_path() honours PLAYTHROUGH_MANIFEST.  Derived
    transition images live under playthrough/build/transitions/ and
    never here: the count identity between this directory and the
    manifest is only meaningful while the directory stays pure.
    """
    from_env = os.environ.get("PLAYTHROUGH_FRAMES_DIR")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), "frames")


def _validated_path(value, label):
    """Return `value` as an absolute file path, or raise.

    Every filesystem entry point in this module runs through here, so
    that no unvalidated path is ever handed to open() or os.path.join:
    the value must be a non-empty string or os.PathLike, must not
    carry a NUL byte, and must not name a directory.
    """
    if value is None:
        raise ManifestError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise ManifestError("%s must not be empty" % label)
    if "\x00" in value:
        raise ManifestError("%s must not contain a NUL byte" % label)
    resolved = os.path.abspath(value)
    if os.path.isdir(resolved):
        raise ManifestError(
            "%s names a directory, not a file: %s" % (label, resolved))
    return resolved


def _validated_manifest_target(value, root=None):
    """Return an absolute manifest path this module may touch.

    The shared half of reading and appending, so neither entry point
    can be the lenient one.  Four conditions must hold:

    1. the path resolves inside the approved root (playthrough/,
       derived from this module's location) -- so /etc/passwd, a device
       node and a sibling checkout are refused rather than opened;
    2. it is not reached through a symlinked component, and is not
       itself a link;
    3. it is the EXACT canonical manifest -- ``<approved
       root>/manifest.jsonl`` -- and not merely some path inside the
       tree;
    4. it does not name anything other than a regular file.

    CONDITION 3 IS THE ONE WORTH EXPLAINING.  Containment alone is not
    enough, because everything this pipeline produces lives inside
    playthrough/: with only conditions 1 and 2, a
    ``PLAYTHROUGH_MANIFEST`` or ``--manifest`` naming
    ``playthrough/timeline.json``, or a frame, or the movie, would be
    accepted and APPENDED TO -- JSON Lines rows would be written onto
    the end of another artifact, every write would report success, and
    the artifact would be silently corrupted while the manifest that was
    supposed to record the session did not exist at all.  The record of
    a captured session has exactly one place to live, so that is what
    is required, compared after resolution so a checkout reached through
    a symlinked ancestor still matches.

    The ONLY way to work at another location is the explicit
    call-site-only `root` argument, which relocates the whole approved
    tree for a caller that owns it -- a test in a temporary directory.
    Neither the environment nor the command line can reach it, and even
    then the file must still be named manifest.jsonl directly under that
    root, so the rule being exercised is the production rule rather than
    a weaker one.
    """
    resolved = _validated_path(value, "manifest path")
    approved = _assert_within_root(resolved, "the manifest path", root)
    _assert_no_symlink(resolved, approved, "the manifest path")
    canonical = os.path.join(approved, MANIFEST_NAME)
    if os.path.realpath(resolved) != canonical:
        raise ManifestError(
            "the manifest is %s and nothing else, but %s was given.  "
            "A record of a captured session is not written anywhere "
            "else in the tree: appending rows onto another artifact "
            "would corrupt it and would report success."
            % (canonical, resolved))
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ManifestError(
            "the manifest path is not a regular file: %s" % resolved)
    return resolved


def _validated_manifest_path(value, root=None):
    """Return an absolute manifest path that is safe to append to.

    The parent directory must already exist.  Creating it here would
    let a mistyped path quietly grow a second manifest somewhere else
    in the tree, and directory creation is playthrough_mkdirs()' job
    in playthrough/tooling/env.sh, not this module's.
    """
    resolved = _validated_manifest_target(value, root)
    parent = os.path.dirname(resolved)
    if not os.path.isdir(parent):
        raise ManifestError(
            "the directory for the manifest does not exist: %s"
            % parent)
    return resolved


def _validated_directory(value, label, root=None):
    """Return `value` as an absolute directory that exists.

    Held to the approved root as well, because the directory this
    resolves to is the one counted against the manifest: a frames
    directory pointed somewhere else -- by PLAYTHROUGH_FRAMES_DIR, a
    --frames-dir argument or a symlink -- would make the
    one-frame-per-row identity a statement about the wrong pixels.
    """
    if value is None:
        raise ManifestError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise ManifestError("%s must not be empty" % label)
    if "\x00" in value:
        raise ManifestError("%s must not contain a NUL byte" % label)
    resolved = os.path.abspath(value)
    approved = _assert_within_root(resolved, "the %s" % label, root)
    _assert_no_symlink(resolved, approved, "the %s" % label)
    if not os.path.isdir(resolved):
        raise ManifestError("no %s at %s" % (label, resolved))
    return resolved


def _validated_frame(frame):
    """Return the caller's frame index, or raise.

    The index is supplied by session.py, which owns the counter for
    the whole session; this module validates it and never generates,
    increments or repairs it.
    """
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise ManifestError(
            "frame must be an int supplied by the caller, got %s"
            % type(frame).__name__)
    if frame < MIN_FRAME_INDEX:
        raise ManifestError(
            "frame must be >= %d, got %d" % (MIN_FRAME_INDEX, frame))
    if frame > MAX_FRAME_INDEX:
        raise ManifestError(
            "frame %d exceeds %d, which would widen the %s field and "
            "stop a lexical sort of the frames matching a numeric one"
            % (frame, MAX_FRAME_INDEX, FRAME_NAME_FORMAT))
    return frame


def frame_file(frame):
    """Return the repository-relative capture path for `frame`.

    The one place the `file` field's value comes from, so the capturer
    and the manifest cannot disagree about a filename.
    """
    return FRAME_FILE_FORMAT % _validated_frame(frame)


def _check_frame_format_contract():
    """Warn once if env.sh's frame format has drifted from ours.

    env.sh defines PLAYTHROUGH_FRAME_FORMAT so that the capturer, this
    writer and the concat list agree byte for byte.  A drift there
    would break the count identity silently, which is exactly the
    class of failure this pipeline refuses to have.
    """
    from_env = os.environ.get("PLAYTHROUGH_FRAME_FORMAT")
    if from_env and from_env != FRAME_NAME_FORMAT:
        _warn_once(
            "frame-format",
            "PLAYTHROUGH_FRAME_FORMAT is %r but this writer records "
            "%r; the capturer and the manifest have to agree byte "
            "for byte" % (from_env, FRAME_NAME_FORMAT))


def _reject_line_breaks(value, label):
    """Raise if `value` spans more than one line.

    A row is one JSON object on one line.  json.dumps would escape an
    embedded newline rather than break the file, but a multi-line
    keystroke description or clock reading is not a thing that was
    observed, so it is refused at the door.
    """
    if "\n" in value or "\r" in value:
        raise ManifestError(
            "%s must be a single line: one row is one JSON object on "
            "one line" % label)


def _reject_control_characters(value, label):
    """Raise if `value` carries a control character.

    The line-break check above catches the two controls that would
    change this file's shape; this catches the rest, and it exists
    because the manifest is not the end of the road for these strings.
    `action` and `commentary` are copied into playthrough/transcript.md
    and into the SRT cue text, and JSON is perfectly happy to carry a
    NUL as "\\u0000" through both -- so a value that survives the
    manifest intact can still corrupt a caption file, a terminal that
    prints it, or the ffmpeg mux that reads it.

    There is no legitimate source for one either: these fields are a
    keystroke and a sentence a person wrote, neither of which contains
    a NUL, a backspace or an escape.  A value that does is a program
    error or pasted machine output, and both are worth stopping at the
    door rather than embedding in the evidence.
    """
    for char in value:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            raise ManifestError(
                "%s carries the control character U+%04X, which is not "
                "something a keystroke or a sentence contains: these "
                "strings are copied verbatim into "
                "playthrough/transcript.md and the SRT cue text, so a "
                "control character here corrupts a later artifact "
                "rather than this one.  Record the reading or the "
                "reason in plain text" % (label, code))


def _reject_runaway_length(value, label):
    """Raise if `value` is far longer than anything observed can be.

    A generous ceiling rather than a style rule: 2000 characters is
    already several paragraphs, and one keystroke's description or one
    survivor's reason is a sentence.  A value this long is a stuck loop
    or a pasted log, and it would land in an SRT cue that no player
    could read and that no frame is on screen long enough to show.

    Deliberately far above anything a person writes, so it can never
    refuse legitimate prose -- the readability advisory below is what
    speaks to length that is merely long.
    """
    if len(value) > MAX_FIELD_LENGTH:
        raise ManifestError(
            "%s is %d characters, and the limit is %d.  A row describes "
            "ONE keystroke and the reason for it; a value this long is "
            "machine output or a runaway loop, and it becomes an SRT "
            "cue no frame is on screen long enough to display"
            % (label, len(value), MAX_FIELD_LENGTH))


def _validated_text(value, label):
    """Return a required, single-line, non-blank string field."""
    if value is None:
        raise ManifestError(
            "%s is required and must not be None" % label)
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a string, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise ManifestError(
            "%s must not be empty: every row documents a real "
            "keystroke and a real reason for it" % label)
    _reject_line_breaks(value, label)
    _reject_control_characters(value, label)
    _reject_runaway_length(value, label)
    return value


def _validated_file(value, frame):
    """Return the frame path, which must be the canonical one.

    Equality with frame_file() is the guard that keeps one row tied to
    one keystroke capture: a row can never point at a derived
    transition image, at a rescaled copy, or at another row's PNG.
    """
    if not isinstance(value, str):
        raise ManifestError(
            "file must be a string, got %s" % type(value).__name__)
    _reject_line_breaks(value, "file")
    expected = FRAME_FILE_FORMAT % frame
    if value != expected:
        raise ManifestError(
            "file must be %r for frame %d, got %r: one row documents "
            "one keystroke capture, never a derived image"
            % (expected, frame, value))
    _check_frame_format_contract()
    return value


def is_possible_clock(value):
    """True when `value` is a time an in-game clock could display.

    SHAPE AND RANGE, because the shape alone admits "24:00:00".  Named
    to match ocr_clock.py's helper of the same name, which applies the
    identical rule when it decides whether an OCR reading may be
    believed, so the two modules cannot drift into disagreeing about
    what a credible clock looks like.

    This is a question, not a repair: a caller that gets False records
    the value it was given, verbatim, and says so.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not CLOCK_24H_RE.match(text):
        return False
    hour, minute, second = (int(part) for part in text.split(":"))
    return (hour <= CLOCK_MAX_HOUR and
            minute <= CLOCK_MAX_MINUTE and
            second <= CLOCK_MAX_SECOND)


def classify_ingame_clock(value):
    """Describe a clock reading without altering it.

    Returns CLOCK_NULL for None, CLOCK_EXACT for the contracted
    fixed-width 24h form, CLOCK_NONSTANDARD for a genuine clock in the
    military or 12h shape, CLOCK_COARSE for one of the phrases a
    survivor without a watch sees, CLOCK_UNKNOWN for "???", and
    CLOCK_UNRECOGNISED for anything else -- which is information, not
    grounds for discarding the reading.

    A fixed-width value that is out of range -- "24:00:00",
    "23:60:00" -- is CLOCK_UNRECOGNISED rather than CLOCK_EXACT.  The
    label is the point: 'exact' is what timeline.py, verify_artifacts.sh
    and the report read as "a clock that can be believed", and a
    self-contradictory row (`"ingame_clock": "24:00:00", "clock_kind":
    "exact"`) misdescribes the evidence even when nothing downstream
    trusts the label.  The reading itself is still recorded exactly as
    it was given; only the description of it is honest.
    """
    if value is None:
        return CLOCK_NULL
    if not isinstance(value, str):
        raise ManifestError(
            "a clock reading is a string or None, got %s"
            % type(value).__name__)
    text = value.strip()
    if CLOCK_24H_RE.match(text):
        if is_possible_clock(text):
            return CLOCK_EXACT
        return CLOCK_UNRECOGNISED
    if CLOCK_MILITARY_RE.match(text) or CLOCK_12H_RE.match(text):
        return CLOCK_NONSTANDARD
    if text in COARSE_TIME_PHRASES:
        return CLOCK_COARSE
    if text == UNKNOWN_TIME_TEXT:
        return CLOCK_UNKNOWN
    return CLOCK_UNRECOGNISED


def _validated_ingame_clock(value):
    """Return the clock reading exactly as it was read, or None.

    None is a success, not a defect: it is how a clock that could not
    be read is recorded, and it serialises as JSON null.  No default
    is ever substituted, no neighbouring row is ever consulted, and an
    unrecognised reading is kept verbatim with a warning rather than
    refused -- refusing it would pressure the caller into inventing a
    value, which is the one thing that must never happen here.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(
            "ingame_clock must be a string or None, got %s"
            % type(value).__name__)
    if not value.strip():
        raise ManifestError(
            "ingame_clock must not be blank: pass None when the clock "
            "could not be read, which records JSON null")
    _reject_line_breaks(value, "ingame_clock")
    kind = classify_ingame_clock(value)
    if kind == CLOCK_UNRECOGNISED and CLOCK_24H_RE.match(value.strip()):
        # Clock-shaped but impossible.  Called out separately because
        # the cause is different and so is the remedy: ocr_clock.py
        # declines such a value outright, so one that reaches this
        # writer came from a hand transcription of the frame and the
        # frame is what should be re-read.
        _warn(
            "ingame_clock %r is fixed-width but states a time no "
            "in-game clock can show (hour <= %d, minute and second "
            "<= %d); recorded verbatim and NOT repaired into a "
            "plausible time, and left for timeline.py to reconcile.  "
            "ocr_clock.py declines such a reading, so re-read the "
            "frame rather than trusting this value"
            % (value, CLOCK_MAX_HOUR, CLOCK_MAX_SECOND))
    elif kind == CLOCK_UNRECOGNISED:
        _warn(
            "ingame_clock %r matches no known form; recorded verbatim "
            "and left for timeline.py to reconcile" % value)
    elif kind == CLOCK_NONSTANDARD:
        _warn_once(
            "clock-format",
            "ingame_clock %r is a clock but not the fixed-width 24h "
            "form; seed_options.py sets 24_HOUR=24h so that every "
            "reading is fixed width" % value)
    return value


def find_meta_vocabulary(text):
    """Return the out-of-character words in `text`, sorted.

    Mirrors the substring grep the transcript gate applies downstream,
    bluntness included, so that a warning here predicts a failure
    there.  Purely advisory: callers report, they never rewrite.
    """
    if not isinstance(text, str):
        return []
    lowered = text.lower()
    return sorted({word for word in META_VOCABULARY
                   if word in lowered})


def find_placeholder_words(text):
    """Return the placeholder markers in `text`, sorted.

    Whole-word and case-insensitive, so ordinary prose is not caught.
    Unlike :func:`find_meta_vocabulary` this is NOT advisory: a hit
    means the field was never filled in, and the callers below treat it
    as a defect in the record rather than a note about its tone.
    """
    if not isinstance(text, str):
        return []
    return sorted({match.group(0).lower()
                   for match in _SENTINEL_WORD_RE.finditer(text)})


def find_unrecorded_action_phrases(text):
    """Return the phrases saying an `action` records no keystroke.

    Case-insensitive substring matching, because these are phrases
    rather than words.  An action that defers to a note elsewhere, or
    names an unknown key, is not a record of what was pressed.
    """
    if not isinstance(text, str):
        return []
    lowered = text.lower()
    return sorted({phrase for phrase in UNRECORDED_ACTION_PHRASES
                   if phrase in lowered})


def sentinel_problems(action, commentary, label):
    """Report every way these two fields fail to be a record.

    `label` prefixes each message -- "row 116" from the reader,
    "action" from the writer -- so the same rule reads correctly
    wherever it is applied.  Pure: nothing is read, repaired or
    rewritten.

    An empty list means both fields say something.  It does NOT mean
    either is TRUE: no code can check an action against the pixels of
    the frame it describes, which is why a field admitting it does not
    describe the keystroke has to be refused here.
    """
    problems = []
    for name, value in (("action", action),
                        ("commentary", commentary)):
        hits = find_placeholder_words(value)
        if hits:
            problems.append(
                "%s %s carries the placeholder marker(s) %s: %r.  A "
                "manifest row is the authoritative record of what one "
                "keystroke did and why; a field marked as not yet "
                "filled in is not a record of anything, and every "
                "structural check would still pass over it.  Write "
                "what was actually pressed and the survivor's actual "
                "reason, from contemporaneous evidence -- never "
                "invented"
                % (label, name, ", ".join(repr(one) for one in hits),
                   value))
    deferrals = find_unrecorded_action_phrases(action)
    if deferrals:
        problems.append(
            "%s action defers the record elsewhere (%s): %r.  This is "
            "the one field nothing downstream can check against the "
            "pixels, so an action that says it does not describe the "
            "keystroke is refused here.  "
            "playthrough/TECHNICAL_NOTES.md is where the ENGINEERING "
            "account of a mistake goes; the row itself still has to "
            "say what was pressed"
            % (label, ", ".join(repr(one) for one in deferrals),
               action))
    return problems


def _validated_commentary(value):
    """Return the survivor's own words, with an advisory if needed."""
    text = _validated_text(value, "commentary")
    if len(text) > CUE_ADVISORY_LENGTH:
        # Advisory, not a refusal: this is about a caption being
        # readable, and where that line falls is a judgement the writer
        # of the sentence gets to make.  The number comes from the other
        # end of the pipeline -- a cue occupies its frame's on-screen
        # window, which timeline.py caps at 10 s, and a comfortable
        # reading rate over 10 s is a few hundred characters.
        _warn(
            "commentary is %d characters, which is more than a reader "
            "can take in while its frame is on screen (a frame's window "
            "is at most 10 s, and this becomes one SRT cue): %r -- "
            "recorded as given, but consider saying it in a sentence"
            % (len(text), text[:80] + "..."))
    hits = find_meta_vocabulary(text)
    if hits:
        _warn(
            "commentary carries out-of-character wording (%s): %r -- "
            "the in-character record stays in the survivor's voice, "
            "and engineering observations belong in "
            "playthrough/TECHNICAL_NOTES.md"
            % (", ".join(hits), text))
    return text


def _format_moment(moment):
    """Render an aware datetime in the fixed real_ts form."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ManifestError(
            "real_ts must carry a timezone so the column is sortable "
            "across hosts; use utc_timestamp()")
    in_utc = moment.astimezone(datetime.timezone.utc)
    return "%s.%03d%s" % (in_utc.strftime(REAL_TS_FORMAT),
                          in_utc.microsecond // 1000,
                          REAL_TS_SUFFIX)


def utc_timestamp(moment=None):
    """Return `moment` in the manifest's fixed real_ts form.

    UTC, millisecond precision, "Z"-suffixed -- for example
    "2026-05-14T09:12:03.481Z".  One form on every row, so the column
    sorts lexically as well as chronologically.  Called with no
    argument it stamps the current instant, which is what session.py
    does at the moment it captures a frame.
    """
    if moment is None:
        moment = datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(moment, datetime.datetime):
        raise ManifestError(
            "utc_timestamp takes a datetime or None, got %s"
            % type(moment).__name__)
    return _format_moment(moment)


def canonical_real_ts(value):
    """Normalise a supplied real_ts to the one fixed form.

    Accepts the canonical string itself, which round-trips byte for
    byte; any other timezone-aware ISO-8601 string, including the
    "Z"-suffixed output of `date -u +%Y-%m-%dT%H:%M:%S.%3NZ`; or an
    aware datetime.  A value with no timezone is refused rather than
    assumed to be UTC, because a timestamp with no zone is not
    sortable across hosts and guessing one would be an invention.

    None IS REFUSED.  `ingame_clock` is the only nullable field in this
    schema, and it is nullable precisely so that an unreadable clock
    can be reported as unread.  real_ts is the opposite kind of value:
    it is a fact the caller holds and this module does not.  Stamping
    "now" for a caller who passed nothing would silently record the
    instant the ROW WAS APPENDED as though it were the instant the
    FRAME WAS CAPTURED -- two different times, separated by the settle,
    the screenshot, the crop and the OCR pass -- and it would do so
    most convincingly on the rows where the caller had simply forgotten
    to measure.  That is fabricated evidence, which HR6 forbids
    outright.  So the timestamp must be passed in, and taking it stays
    a deliberate caller action: utc_timestamp() called at the capture.
    """
    if value is None:
        raise ManifestError(
            "real_ts is required and must not be None; it records when "
            "the capture actually happened, which this module cannot "
            "know and will not invent.  ingame_clock is the only "
            "nullable field.  Call utc_timestamp() at the moment the "
            "frame is captured and pass the result, or pass the "
            "capture's own timestamp (the canonical form is %s)"
            % REAL_TS_EXAMPLE)
    if isinstance(value, datetime.datetime):
        return _format_moment(value)
    if not isinstance(value, str):
        raise ManifestError(
            "real_ts must be an ISO-8601 string or an aware datetime, "
            "got %s" % type(value).__name__)
    text = value.strip()
    if not text:
        raise ManifestError(
            "real_ts must not be empty; it records when the capture "
            "actually happened")
    candidate = text
    if candidate[-1:] in ("Z", "z"):
        # datetime.fromisoformat only accepts a "Z" suffix on Python
        # 3.11 and newer.  Rewriting it to an explicit offset keeps
        # this module correct on every interpreter the repository's
        # tooling may be run under.
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except ValueError as err:
        raise ManifestError(
            "real_ts %r is not ISO-8601 (%s); the canonical form is "
            "%s" % (value, err, REAL_TS_EXAMPLE)) from err
    return _format_moment(parsed)


def _ordered_row(row):
    """Return `row` as a dict of exactly FIELDS, in declared order.

    Refuses a row that is missing a required key or carries an
    unexpected one -- and says which, because a silent extra key is
    how a second source of truth for timing would get in.  A mapping
    whose insertion order differs is reordered rather than refused:
    the schema fixes the order on disk, which this controls.
    """
    if not isinstance(row, dict):
        raise ManifestError(
            "a row must be a dict of the six manifest fields, got %s"
            % type(row).__name__)
    missing = [name for name in FIELDS if name not in row]
    extra = [name for name in row if name not in FIELDS]
    if missing or extra:
        raise ManifestError(
            "a row carries exactly these keys, in this order: %s.  "
            "Missing: %s.  Unexpected: %s.  Durations, transition "
            "flags and cue windows belong to "
            "playthrough/timeline.json; diagnostics belong to "
            "playthrough/TECHNICAL_NOTES.md"
            % (", ".join(FIELDS), missing or "none", extra or "none"))
    return {name: row[name] for name in FIELDS}


def build_row(frame, file, real_ts, ingame_clock, action, commentary):
    """Validate one row and return it, without touching the disk.

    Every field is checked here, so a caller can validate before it
    commits to writing, and so append_row() has exactly one validation
    path.

    `ingame_clock` may be None; NOTHING ELSE MAY BE, and that is
    enforced rather than merely documented.  In particular `real_ts` is
    mandatory: see canonical_real_ts() for why a defaulted timestamp
    would be fabricated evidence rather than a convenience.
    """
    index = _validated_frame(frame)
    row = {
        "frame": index,
        "file": _validated_file(file, index),
        "real_ts": canonical_real_ts(real_ts),
        "ingame_clock": _validated_ingame_clock(ingame_clock),
        "action": _validated_text(action, "action"),
        "commentary": _validated_commentary(commentary),
    }
    # REFUSED AT THE WRITER TOO, not only by the reader.  A row that
    # cannot be written is a row that never has to be corrected, and
    # the caller is a live session that still knows what it pressed and
    # why.
    problems = sentinel_problems(
        row["action"], row["commentary"], "frame %d" % index)
    if problems:
        raise ManifestError("  ".join(problems))
    return _ordered_row(row)


def encode_row(row):
    """Return the exact line this module writes for `row`.

    One self-contained JSON object, keys in the declared order,
    non-ASCII written as itself rather than escaped -- the convention
    the repository's own tooling follows -- and terminated by a single
    LF.  No indentation, no wrapping array, no trailing comma.
    """
    ordered = _ordered_row(row)
    return json.dumps(ordered, ensure_ascii=False) + "\n"


def _fsync(descriptor, path, frame, require_durable):
    """Force a written row to the device, or fail loudly.

    A crash mid-session must not lose the row for a frame that already
    exists on disk, which is the whole reason this call is here.  So a
    refusal is NOT tolerated by default.  flush() has handed the bytes
    to the operating system by this point, but "the kernel has them" is
    not the same claim as "they survive a power loss", and reporting
    success for the weaker claim would mean the manifest -- the
    session's evidence, and the file the frame-count identity is
    checked against -- could silently be missing rows for frames that
    exist.  A row this module cannot prove it stored is therefore
    raised as ManifestError rather than warned about and passed over.

    Reduced durability remains available, but only as an explicit
    caller decision: `require_durable=False` restores the warn-once
    behaviour for a caller who genuinely accepts it, such as a scratch
    manifest on a filesystem that cannot fsync at all.  The default is
    the safe one, and the opt-in has to be typed out.

    THIS STEP DELIBERATELY DOES NOT ROLL THE ROW BACK, unlike the write
    itself.  By the time it runs the line is complete and valid JSON on
    disk; what is in doubt is only whether it survives a power loss.
    Truncating it away would turn an uncertainty into a certain loss --
    deleting the record of a frame that exists -- so the row stays and
    the uncertainty is reported for what it is.
    """
    try:
        os.fsync(descriptor)
    except OSError as err:
        if require_durable:
            raise ManifestError(
                "could not force frame %s's row to the device (%s).  "
                "The line was written to %s and handed to the "
                "operating system, but its DURABILITY IS UNPROVEN, so "
                "the row may not survive a crash -- and the manifest "
                "is the session's evidence.  Re-read the file to "
                "establish what it now contains rather than assuming "
                "either outcome.  Pass require_durable=False only if "
                "reduced durability is genuinely acceptable here"
                % (frame, err, path)) from err
        _warn_once(
            "fsync",
            "could not fsync the manifest (%s); rows are flushed but "
            "not forced to the device -- the caller explicitly "
            "approved this reduced durability" % err)


def _roll_back(descriptor, committed, path, frame, cause):
    """Undo a failed append and return the error to raise.

    The caller writes `raise _roll_back(...)`, so that the rollback and
    the failure are one statement and neither can be forgotten.

    THIS IS WHAT KEEPS A HANDLED FAILURE FROM COSTING MORE THAN ITS OWN
    ROW, and it is the opposite of rewriting history rather than an
    exception to it.  The only bytes it can remove are the ones the
    append that just failed had started to write: `committed` was read
    from the file BEFORE that write, under the same lock, so truncating
    to it restores the file to exactly the state every already-recorded
    row left it in.  No recorded row is altered, no row is dropped, and
    the failure is still raised.

    It covers the failures this process lives to handle -- a short
    write, ENOSPC, an EIO -- and nothing else.  A process killed
    outright never reaches it; see _assert_row_boundary(), which is what
    refuses the torn row it leaves behind.

    Without it a write that stops half way -- ENOSPC on a long session
    is the realistic case, because one PNG per keystroke fills a disk
    long before a session ends -- leaves a partial line with no newline,
    and a partial line is not JSON.  The manifest then cannot be read
    at all: timeline.py, the render, the captions and every acceptance
    gate that counts rows are blocked behind a file only a human hand
    edit can repair.  An append-only evidence record exists precisely so
    that a resource failure costs the failing row and nothing else.

    A truncate that itself fails is reported alongside the original
    cause rather than hidden behind it: the operator then knows the file
    needs inspecting, which is strictly better than being told only
    about the disk.

    THE OUTCOME IS REPORTED, NOT ASSUMED.  The restoration claim is made
    only when the truncate actually succeeded.  A message that says the
    file was left exactly as it was AND that it may end mid-row
    contradicts itself, and an operator reading the reassuring half
    first has been told the record is intact when nothing established
    that.  So the two cases are separate sentences: restored and
    readable, or integrity UNKNOWN and inspection mandatory.
    """
    try:
        os.ftruncate(descriptor, committed)
    except OSError as err:
        outcome = (
            "  The ROLLBACK TO %d bytes ALSO FAILED (%s), so the state "
            "of the file is UNKNOWN: it may still end mid-row.  Nothing "
            "here established that the record is intact, so INSPECT IT "
            "before appending again -- run 'python "
            "playthrough/tooling/manifest.py verify' to see whether the "
            "last line is a complete row." % (committed, err))
    else:
        outcome = (
            "  The file was left exactly as it was before this row (%d "
            "bytes), so it is still readable and the frame this row "
            "describes is the one to re-record." % (committed,))
    return ManifestError(
        "could not append frame %s's row to %s (%s); the manifest is "
        "the session's evidence, so a write this module cannot complete "
        "is reported rather than passed over.%s"
        % (frame, path, cause, outcome))


def _assert_row_boundary(descriptor, committed, path, frame):
    """Refuse to append onto a line that was never finished.

    _roll_back() removes a torn row whenever this process survives to
    run it, which covers the failure that motivated it.  It cannot cover
    a process that is killed outright -- SIGKILL, a power loss, an OOM
    kill -- part way through the write, and then the file ends mid-row
    with no newline.  Appending after that would join two half-rows into
    one line that is neither, quietly turning a recoverable tear into a
    corrupt record that reads as a single malformed row.

    So the boundary is checked before every append, at the cost of one
    byte read: a non-empty manifest must end with the LF that terminated
    its last complete row.  It is refused rather than repaired, because
    the missing piece is a row about a frame that exists, and deciding
    what it said is not this module's business -- verify_manifest()
    reports which line is malformed, the frame it describes is still on
    disk, and the correction is the operator's to make deliberately.
    """
    if committed <= 0:
        return
    try:
        tail = os.pread(descriptor, 1, committed - 1)
    except OSError as err:
        raise ManifestError(
            "could not read the last byte of the manifest %s (%s), so "
            "frame %s's row was not appended: a row must never be "
            "joined onto an unfinished one, and that cannot be ruled "
            "out without this check" % (path, err, frame)) from err
    if tail != b"\n":
        raise ManifestError(
            "%s ends mid-row -- its last %d bytes are not terminated by "
            "a newline -- so frame %s's row was NOT appended onto it.  "
            "A manifest ends with a complete row or it ends with a tear "
            "from a process that was killed mid-write, and appending "
            "would fuse the two into one line that is neither.  Run "
            "'python playthrough/tooling/manifest.py verify' to see the "
            "line, and repair the record deliberately: the frame that "
            "row describes is still in playthrough/frames/"
            % (path, committed, frame))


def _append_whole_row(descriptor, payload, committed, path, frame):
    """Write one encoded row, entirely or not at all.

    One `os.write` of the complete line, unbuffered, on a descriptor
    opened O_APPEND and held under the exclusive lock: there is no
    userspace buffer that could flush a fragment later, and the kernel
    places the bytes at the end of the file whatever another writer is
    doing.  A refusal and a short write are handled identically --
    rolled back to `committed` -- because a row that is 90% written is
    exactly as unreadable as one that raised.

    A short write is looped rather than assumed away only after the
    rollback question is settled: os.write may legitimately return
    fewer bytes, so the remainder is written until it is all there, and
    a step that makes no progress is treated as a failure rather than
    spun on.
    """
    total = len(payload)
    written = 0
    while written < total:
        try:
            count = os.write(descriptor, payload[written:])
        except OSError as err:
            raise _roll_back(
                descriptor, committed, path, frame, err) from err
        if count <= 0:
            raise _roll_back(
                descriptor, committed, path, frame,
                "the write stopped after %d of %d bytes and made no "
                "further progress" % (written, total))
        written += count


def _lock_exclusively(descriptor, path):
    """Take an exclusive advisory lock over the open manifest.

    Two writers appending at the same instant is not hypothetical: the
    capture loop runs unattended, and a second stage or a re-run can
    overlap it.  O_APPEND keeps each write at the end of the file, but
    the lock is what makes "measure the end, write, fsync, and on
    failure truncate back" one indivisible step AS SEEN BY ANOTHER
    PROCESS THAT ALSO TAKES IT -- so two rows cannot interleave and a
    rollback cannot remove bytes another writer put there after this one
    measured the end.

    THE LOCK IS ADVISORY, so that guarantee reaches exactly as far as
    the processes that cooperate with it.  Every writer in this pipeline
    goes through this function, which is what makes it hold here; a
    READER that does not take the lock is unaffected by it and can read
    the file mid-append.  That is why the readers do not rely on the
    lock: verify_manifest() refuses a line it cannot parse, and
    timeline.py refuses the document rather than working around it.

    THE LOCK IS MANDATORY AND THIS FAILS CLOSED.  It used to warn and
    carry on, which was wrong for one specific and unrecoverable
    reason: the append that follows measures the end of the file and,
    on failure, truncates BACK to that offset.  Without the lock those
    two operations are not one step, so a concurrent writer's COMPLETE
    row -- somebody else's evidence -- can be appended between the
    measurement and the truncation and then destroyed by this process's
    rollback.  A step that cannot be serialised is therefore refused
    before anything is measured, which costs a session that stops and
    can be resumed instead of a record that lost a row nobody will
    notice is gone.

    The lock is released when the descriptor closes, which the caller's
    `finally` guarantees on every path including an exception.

    :raises ManifestError: when the lock cannot be taken.  Nothing has
        been measured, written or truncated at that point.
    """
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as err:
        raise ManifestError(
            "could not take an exclusive lock on the manifest %s (%s), "
            "so nothing was written.  The append measures the end of "
            "the file and truncates back to it if it fails; without "
            "the lock those are two operations, and a concurrent "
            "writer's complete row could be appended in between and "
            "then removed by this process's rollback.  A row of "
            "captured evidence is not something to risk on a "
            "filesystem that will not serialise writers -- run one "
            "session at a time on a filesystem that supports flock"
            % (path, err)) from err


def append_row(manifest_path, frame, file, real_ts, ingame_clock,
               action, commentary, require_durable=True, root=None):
    """Validate one row and append it to the manifest.

    The only writer in this module, and the only writer of this file.
    Returns the row exactly as written, so the caller can log or
    assert on it.  Raises ManifestError and writes nothing at all if
    any field is wrong -- there is no partial row.

    A row is not reported as appended until it has been written,
    flushed AND forced to the device.  Every failure up to and including
    the fsync -- the open, the lock, the boundary check, the write, the
    fsync -- raises ManifestError; none is downgraded to a warning,
    because a caller that is told the row was recorded will not go back
    and check.  `require_durable=False` is the one documented exception,
    and it weakens only the fsync step: see _fsync().

    The CLOSE is the one step after that, and it is warned rather than
    raised, deliberately: by then the row is on the device, so raising
    would tell the caller the row was not recorded when it was.  It is
    still reported once.

    `manifest_path` is explicit rather than defaulted so that a test,
    a dry run and the real session cannot be confused for one another;
    default_manifest_path() supplies the pipeline's own value.  It is
    validated against the approved root before anything is opened, so
    a path outside playthrough/ -- or one reached through a symlink --
    is refused rather than appended to.  `root` relocates that approved
    tree for a test that owns a temporary directory; see
    approved_root().

    What this does NOT do is police the index sequence, deliberately.
    Checking that an index follows the last one written would mean
    reading the whole file on every append -- quadratic over a session,
    and a writer that behaves differently depending on what is already
    on disk.  Instead a repeated or skipped index is recorded honestly
    and reported loudly afterwards by verify_manifest(), which is also
    what the acceptance gate runs.  The counter stays session.py's.
    """
    path = _validated_manifest_path(manifest_path, root)
    row = build_row(frame, file, real_ts, ingame_clock, action,
                    commentary)
    line = encode_row(row)
    # Append mode, one line, then closed.  The file is never opened
    # for writing any other way: not truncated, not seeked, not
    # re-sorted, not deduplicated, not compacted, not retro-edited.
    # If something was recorded wrongly the correction is a note in
    # playthrough/TECHNICAL_NOTES.md, not an edit to this history.
    # newline="\n" pins LF whatever the platform, which is what the
    # `*.jsonl text` attribute expects of the committed file.
    #
    # The descriptor is opened with O_NOFOLLOW rather than by name, so
    # a symlink planted between the validation above and this line is
    # refused by the kernel instead of followed, and the whole append
    # is serialised against other writers by the lock below.
    #
    # A HANDLED WRITE FAILURE COSTS ITS OWN ROW AND NOTHING ELSE.  The
    # row is written by os.write directly, not through a buffered
    # stream: a stream can flush a fragment of a line when the disk
    # fills, and a fragment is not JSON, which makes the whole manifest
    # unreadable and blocks every stage that counts its rows.  It is one
    # call for the whole line whenever the kernel takes the whole line,
    # and _append_whole_row() loops for the remainder when it does not,
    # because os.write is allowed to return short.
    # The end of the file is measured first, under the lock, so a write
    # that cannot complete is truncated straight back to it -- see
    # _append_whole_row() and _roll_back().  Nothing else in this module
    # ever seeks or truncates, and a rollback can only ever remove bytes
    # the failing append itself had begun to write.
    #
    # That is as far as the guarantee goes, and it is deliberately not
    # called atomic: an UNHANDLED interruption -- SIGKILL, an OOM kill,
    # the power going -- can stop the write with no chance to undo it,
    # and the file then ends mid-row.  _assert_row_boundary() below
    # refuses to append onto that, and verify_manifest() reports it, so
    # the tear is caught rather than assumed away.
    #
    # Every step is guarded so that an OSError from any of them becomes
    # a ManifestError: the caller already catches that for every
    # validation failure, and a write or durability failure deserves
    # the same visibility rather than surfacing as a different
    # exception type from a different layer.  The ManifestError raised
    # by _fsync() is not an OSError, so it passes through untouched.
    # O_RDWR rather than O_WRONLY for exactly one reason: the boundary
    # check below reads the file's last byte, and pread needs a readable
    # descriptor.  It buys no other freedom -- O_APPEND still forces
    # every write to the end of the file, the reads are positional and
    # never move the write offset, and this remains the only descriptor
    # in the module that can write at all.
    payload = line.encode("utf-8")
    descriptor = _open_nofollow(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW)
    try:
        _lock_exclusively(descriptor, path)
        try:
            committed = os.lseek(descriptor, 0, os.SEEK_END)
        except OSError as err:
            raise ManifestError(
                "could not measure the end of the manifest %s (%s), so "
                "frame %s's row was not written: without that offset a "
                "failed append could not be undone, and a half-written "
                "row would make the whole record unreadable"
                % (path, err, row["frame"])) from err
        _assert_row_boundary(descriptor, committed, path, row["frame"])
        _append_whole_row(
            descriptor, payload, committed, path, row["frame"])
        _fsync(descriptor, path, row["frame"], require_durable)
    finally:
        # Closing releases the lock as well.  A close that fails cannot
        # hide a row this function claimed to have stored -- the write
        # and the fsync above both already raise, and the fsync ran
        # first -- so it is not promoted to a failure that would
        # contradict a row already on disk.  It is still reported once,
        # because a descriptor the operating system would not close is a
        # fact about the host and not something to swallow.
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "close",
                "could not close the manifest %s after appending (%s); "
                "the row itself was written and forced to the device "
                "before this point, so the record is intact" %
                (path, err))
    return row


def append_record(manifest_path, row, require_durable=True, root=None):
    """Append a row supplied as a mapping of the six fields.

    A convenience for a caller that already holds a dict; it shares
    append_row()'s validation exactly -- including the path checks, the
    lock and the durability guarantee -- so neither entry point can be
    the lenient one.
    """
    ordered = _ordered_row(row)
    return append_row(
        manifest_path,
        ordered["frame"],
        ordered["file"],
        ordered["real_ts"],
        ordered["ingame_clock"],
        ordered["action"],
        ordered["commentary"],
        require_durable=require_durable,
        root=root,
    )


def _decode_line(raw, number, path):
    """Parse one manifest line, or raise with its line number."""
    text = raw.rstrip("\n")
    if text.endswith("\r"):
        raise ManifestError(
            "%s line %d ends CRLF; the manifest is LF only"
            % (path, number))
    if not text.strip():
        raise ManifestError(
            "%s line %d is blank; every line is exactly one row"
            % (path, number))
    try:
        row = json.loads(text)
    except ValueError as err:
        raise ManifestError(
            "%s line %d is not JSON: %s" % (path, number, err)) from err
    if not isinstance(row, dict):
        raise ManifestError(
            "%s line %d is not a JSON object; the manifest is JSON "
            "Lines, not a wrapping array" % (path, number))
    return row


def read_rows(manifest_path=None, root=None):
    """Return every row on disk, in file order.  Read-only.

    Opened for reading only, and the returned dicts are copies, so no
    caller of this module can rewrite the record through it.  Key
    order is preserved as it appears on disk, which is what lets
    verify_manifest() check the declared order of the file itself.

    The path is held to the same approved-root, no-symlink and
    O_NOFOLLOW rules as the append path.  Reading is not harmless: a
    redirected read would report somebody else's file as this
    session's record, and every count and duration downstream would be
    computed from it.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_manifest_target(manifest_path, root)
    if not os.path.isfile(path):
        raise ManifestError("no manifest at %s" % path)
    rows = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        handle = os.fdopen(descriptor, "r", encoding="utf-8", newline="")
    except OSError as err:
        os.close(descriptor)
        raise ManifestError(
            "could not read the manifest %s: %s" % (path, err)) from err
    with handle:
        for number, raw in enumerate(handle, start=1):
            rows.append(_decode_line(raw, number, path))
    return rows


def count_rows(manifest_path=None, root=None):
    """Return the number of rows on disk.  Read-only.

    The count that must equal the number of PNGs in the frames
    directory -- one keystroke, one capture, one row.
    """
    return len(read_rows(manifest_path, root))


def last_recorded_frame(manifest_path=None, root=None):
    """Return the last frame index recorded, or 0 if there is none.

    An observation for the resume branch, not a generator: session.py
    owns the frame counter and this module never increments anything.
    A manifest that does not exist yet answers 0, which is how a fresh
    session is distinguished from a resumed one.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_manifest_target(manifest_path, root)
    if not os.path.isfile(path):
        return 0
    rows = read_rows(path, root)
    if not rows:
        return 0
    last = rows[-1].get("frame")
    if isinstance(last, bool) or not isinstance(last, int):
        raise ManifestError(
            "the last row of %s carries a non-integer frame: %r"
            % (path, last))
    return last


def _shape_problems(path):
    """Report defects in the file's byte shape.  Read-only.

    Opened through the same O_NOFOLLOW descriptor discipline as every
    other read here, so the bytes checked are the bytes of the file
    that was validated and not of something a link points at.
    """
    problems = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        handle = os.fdopen(descriptor, "rb")
    except OSError as err:
        os.close(descriptor)
        raise ManifestError(
            "could not read the manifest %s: %s" % (path, err)) from err
    with handle:
        data = handle.read()
    if not data:
        return ["%s is empty" % path]
    if not data.endswith(b"\n"):
        problems.append("%s does not end with a newline" % path)
    if data.endswith(b"\n\n"):
        problems.append("%s ends with a blank line" % path)
    if b"\r" in data:
        problems.append(
            "%s contains a carriage return; the manifest is LF only"
            % path)
    return problems


def row_field_problems(row, number):
    """Report every schema defect in ONE row.  Read-only.

    PUBLIC AND AUTHORITATIVE.  This function -- not a paraphrase of it
    -- is what decides whether a single manifest row is well formed.
    timeline.py gates its whole computation on these rows, and a
    second, weaker copy of these checks living there would mean the
    pipeline had two disagreeing definitions of a valid row, with the
    looser one deciding what gets rendered.  The schema is defined
    here, next to the writer that enforces it, so the reader and the
    writer cannot drift apart.

    THE PAIR, AND WHY IT IS A PAIR.  This function and
    sequence_problems() below are the two halves of the schema: one row
    in isolation, and the 1..n identity across rows.  row_problems() is
    the CANONICAL GATE that applies both to a whole manifest, and it is
    what every other stage calls; these two exist separately so that a
    caller holding one row -- the writer, on its way to appending it --
    can check exactly what it holds without inventing its own rules.
    Nothing outside this module should need to call them directly.

    `number` is the 1-based line number, used only in the messages.
    Nothing is modified, and a returned empty list means this row
    satisfies the six-field schema.
    """
    problems = []
    if list(row) != list(FIELDS):
        return [
            "row %d carries keys %s; expected exactly %s in that "
            "order" % (number, list(row), list(FIELDS))]
    frame = row["frame"]
    if isinstance(frame, bool) or not isinstance(frame, int):
        problems.append(
            "row %d frame is not an integer: %r" % (number, frame))
    elif frame < MIN_FRAME_INDEX or frame > MAX_FRAME_INDEX:
        problems.append(
            "row %d frame is out of range: %d" % (number, frame))
    elif row["file"] != FRAME_FILE_FORMAT % frame:
        problems.append(
            "row %d file is %r; expected %r"
            % (number, row["file"], FRAME_FILE_FORMAT % frame))
    for name in ("real_ts", "action", "commentary"):
        value = row[name]
        if not isinstance(value, str) or not value.strip():
            problems.append(
                "row %d %s is empty or not a string: %r"
                % (number, name, value))
    real_ts = row["real_ts"]
    if isinstance(real_ts, str) and real_ts.strip():
        try:
            canonical_real_ts(real_ts)
        except ManifestError as err:
            problems.append(
                "row %d real_ts is malformed: %s" % (number, err))
    clock = row["ingame_clock"]
    if clock is not None:
        if not isinstance(clock, str) or not clock.strip():
            problems.append(
                "row %d ingame_clock is neither a reading nor null: "
                "%r" % (number, clock))
    hits = find_meta_vocabulary(row["commentary"])
    if hits:
        # Advisory, never a problem: the match is a blunt substring
        # test and a false positive must not fail the gate.
        _warn_once(
            "commentary-meta",
            "row %d commentary carries out-of-character wording (%s); "
            "advisory only, nothing was altered"
            % (number, ", ".join(hits)))
    # A HARD PROBLEM, unlike the advisory above.  See the PLACEHOLDER
    # sentinels beside META_VOCABULARY for why the two are treated
    # differently: a field marked as not yet filled in is not a record
    # of anything, and every other check here passes straight over it.
    problems.extend(sentinel_problems(
        row["action"], row["commentary"], "row %d" % number))
    return problems


def sequence_problems(rows):
    """Report gaps, repeats and reorderings.  Read-only.

    PUBLIC AND AUTHORITATIVE, for the same reason as row_problems():
    the 1..n identity is what makes one keystroke, one frame and one row
    the same statement, and it is checked here so that every stage
    checks it the same way.
    """
    problems = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            # Already reported as a malformed row; skipping it here
            # keeps every later position honest, because renumbering
            # around it would blame the wrong row for the gap.
            continue
        frame = row.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            continue
        if frame != position:
            problems.append(
                "row %d records frame %d; the indices run 1..n with "
                "no gap, no repeat and no reordering"
                % (position, frame))
    return problems


def row_problems(rows, allow_index_gaps=False):
    """Report every schema defect in a sequence of rows.  Pure.

    THE canonical in-memory gate for manifest rows: it applies
    row_field_problems() to every row and sequence_problems() across
    them, which are the only implementations of those rules anywhere in
    the pipeline.  What it holds a manifest to is exactly the six
    declared fields in
    the declared order, an integer index inside the recorded range
    whose `file` is the capture path this module formats from that
    index, a real_ts in the one fixed sortable form, non-empty text
    where text is required, and an `ingame_clock` that is either a
    reading or JSON null.

    Both consumers hold their rows to THIS function.
    verify_manifest() applies it to the file on disk, and timeline.py
    applies it to the rows it is about to pace a film from -- before it
    writes a timeline AND before it attests to one already written --
    so the same defect is reported in the same words wherever it is
    found.  A second, laxer copy of these rules is precisely how a
    manifest error becomes a timeline that quietly filled it in: one
    such copy existed and accepted a row whose `file` named a
    different capture than its `frame`, and a real_ts that was not a
    timestamp at all.

    `allow_index_gaps` suppresses only the 1..n sequence check -- the
    single problem an operator may knowingly accept, and the only one
    this function will ever stay quiet about.  Every other defect is
    reported unconditionally, and verify_manifest() never passes the
    flag, so `manifest.py verify` reports a gap whatever anybody else
    chose to tolerate.

    Nothing is read from disk, nothing is repaired and nothing is
    rewritten -- the caller decides what a problem means, which for
    this pipeline means refusing to build evidence on top of it.
    """
    problems = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(
                "row %d is a %s, not an object"
                % (position, type(row).__name__))
            continue
        problems.extend(row_field_problems(row, position))
    if not allow_index_gaps:
        problems.extend(sequence_problems(rows))
    return problems


def _frame_problems(rows, frames_dir, root=None):
    """Report rows whose capture is missing on disk.  Read-only."""
    problems = []
    directory = _validated_directory(
        frames_dir, "frames directory", root)
    for row in rows:
        frame = row.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            continue
        # The basename is rebuilt from this module's own format rather
        # than joined from the row's text, so nothing unvalidated ever
        # reaches the filesystem.
        candidate = os.path.join(directory, FRAME_NAME_FORMAT % frame)
        if not os.path.isfile(candidate):
            problems.append(
                "no capture on disk for frame %d: %s"
                % (frame, candidate))
    return problems


def verify_manifest(manifest_path=None, frames_dir=None,
                    require_frames=False, root=None):
    """Return a list of problems with the manifest.  Read-only.

    An empty list means the file satisfies the schema, the byte shape
    and the one-row-per-frame invariant.  The schema half is
    row_problems(), the shared gate timeline.py holds its rows to as
    well, so this function adds the checks that need the FILE -- its
    byte shape, and with `require_frames` the existence of the capture
    each row names -- rather than restating the row rules.  Nothing is
    repaired, reordered or rewritten: a problem is reported so that a
    human can decide, which for this file means a note in
    playthrough/TECHNICAL_NOTES.md rather than an edit here.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_manifest_target(manifest_path, root)
    if not os.path.isfile(path):
        return ["no manifest at %s" % path]
    try:
        rows = read_rows(path, root)
    except ManifestError as err:
        return [str(err)]
    problems = _shape_problems(path)
    problems.extend(row_problems(rows))
    if require_frames:
        if frames_dir is None:
            frames_dir = default_frames_dir()
        problems.extend(_frame_problems(rows, frames_dir, root))
    _check_frame_format_contract()
    return problems


def _build_parser():
    """Return the read-only command line parser."""
    parser = argparse.ArgumentParser(
        prog="manifest.py",
        description=(
            "Inspect playthrough/manifest.jsonl.  Appending is "
            "available to importers only, so that session.py keeps "
            "sole ownership of the frame counter."))
    parser.add_argument(
        "--manifest", default=None, metavar="PATH",
        help=("the manifest to read; defaults to PLAYTHROUGH_MANIFEST "
              "or <repository>/playthrough/manifest.jsonl.  It must "
              "resolve to exactly that file: the record of a session "
              "has one location, and any other path -- including "
              "another artifact inside playthrough/ -- is refused"))
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify",
        help=("check the six-field schema, the byte shape and the "
              "1..n frame sequence"))
    verify.add_argument(
        "--frames-dir", default=None, metavar="DIR",
        help=("the captures to check against; defaults to "
              "PLAYTHROUGH_FRAMES_DIR or "
              "<repository>/playthrough/frames"))
    verify.add_argument(
        "--require-frames", action="store_true",
        help="also require the capture named by every row to exist")
    commands.add_parser(
        "count", help="print the number of rows on stdout")
    return parser


def main(argv=None, root=None):
    """Run the read-only command line and return an exit status.

    `root` is call-site only, exactly as it is on every function above:
    it relocates the approved tree for a caller that owns a temporary
    directory, and neither the environment nor the command line can
    reach it.  The rules a relocated run is held to are the production
    rules, unchanged.
    """
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "count":
            print(count_rows(args.manifest, root))
            return 0
        problems = verify_manifest(
            args.manifest,
            frames_dir=args.frames_dir,
            require_frames=args.require_frames,
            root=root)
        total = count_rows(args.manifest, root) if not problems else 0
    except ManifestError as err:
        print("manifest.py: %s" % err, file=sys.stderr)
        return 1
    for problem in problems:
        print("manifest.py: %s" % problem, file=sys.stderr)
    if problems:
        print("manifest.py: %d problem(s) found" % len(problems),
              file=sys.stderr)
        return 1
    print("manifest ok: %d row(s)" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
