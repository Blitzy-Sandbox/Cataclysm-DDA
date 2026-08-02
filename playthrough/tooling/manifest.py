#!/usr/bin/env python3
"""Append-only JSON Lines writer for playthrough/manifest.jsonl.

One JSON object per line, one line per captured frame, one captured
frame per keystroke.  The manifest is the record that the session
happened: every row ties one keystroke to the PNG it produced, to the
wall-clock instant of that capture, to the sidebar clock as it was
actually read from that PNG, and to the survivor's own reason for
acting.  That record is evidence, and evidence is not rewritten, so
this module only ever appends.

Schema -- exactly six keys, in this order, on every row:

    frame         int       monotonic index from 1, supplied by the
                            caller; this module never generates it
    file          str       "playthrough/frames/frame_%05d.png" from
                            the index, matching what capture.sh wrote
    real_ts       str       UTC wall-clock instant of the capture, one
                            fixed sortable form on every row
    ingame_clock  str|None  the sidebar clock AS READ, or JSON null
    action        str       the single keystroke plus enough plain
                            description to be unambiguous
    commentary    str       the survivor's first-person reason for it

Nothing else is permitted.  Durations, transition flags and caption
cue windows belong to playthrough/timeline.json, which is the single
source of truth for timing; recording them here as well would create
the second source of truth the pipeline exists to avoid.  Engineering
and diagnostic observations belong to playthrough/TECHNICAL_NOTES.md.
A row carrying an unexpected key, or missing a required one, is
refused rather than written.

`ingame_clock` is the honesty field.  display::time_string()
(src/display.cpp:207-219) returns an exact time only when the survivor
has a watch; otherwise one of the coarse phrases from
display::time_approx() (src/display.cpp:159-185), otherwise "???".
Under the seeded 24_HOUR=24h option an exact reading is fixed-width
"%02d:%02d:%02d" (src/calendar.cpp:638-663), which is what makes it
legible at all.  When the clock could not be read the value is None
and serialises as JSON null.  It is never interpolated, never carried
forward from the previous row and never guessed; reconciling an
unreadable or non-monotonic reading is timeline.py's job, downstream
and visibly flagged.  This module records what was seen.

Typical use, from session.py, which owns the frame counter::

    import manifest

    index = ...                     # session.py's counter, not ours
    path = manifest.default_manifest_path()
    manifest.append_row(
        path, index, manifest.frame_file(index),
        manifest.utc_timestamp(), "08:15:32", "l  (look around)",
        "I want the street in front of me read properly before I "
        "put a boot on it.")

Verification, from verify_artifacts.sh::

    python3 playthrough/tooling/manifest.py verify --require-frames
    python3 playthrough/tooling/manifest.py count

The command line is read-only on purpose: appending is available to
importers only, so that session.py keeps sole ownership of the frame
counter and no shell caller can slip a row in beside it.

Standard library only -- nothing here needs
playthrough/tooling/requirements.txt.  Paths follow
playthrough/tooling/env.sh, the single definition of the artifact
layout, whose PLAYTHROUGH_MANIFEST, PLAYTHROUGH_FRAMES_DIR and
PLAYTHROUGH_FRAME_FORMAT exports are honoured when they are set.
"""

import argparse
import datetime
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
    return os.path.join(_playthrough_dir(), "manifest.jsonl")


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


def _validated_manifest_path(value):
    """Return an absolute manifest path that is safe to append to.

    The parent directory must already exist.  Creating it here would
    let a mistyped path quietly grow a second manifest somewhere else
    in the tree, and directory creation is playthrough_mkdirs()' job
    in playthrough/tooling/env.sh, not this module's.
    """
    resolved = _validated_path(value, "manifest path")
    parent = os.path.dirname(resolved)
    if not os.path.isdir(parent):
        raise ManifestError(
            "the directory for the manifest does not exist: %s"
            % parent)
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ManifestError(
            "the manifest path is not a regular file: %s" % resolved)
    return resolved


def _validated_directory(value, label):
    """Return `value` as an absolute directory that exists."""
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


def classify_ingame_clock(value):
    """Describe a clock reading without altering it.

    Returns CLOCK_NULL for None, CLOCK_EXACT for the contracted
    fixed-width 24h form, CLOCK_NONSTANDARD for a genuine clock in the
    military or 12h shape, CLOCK_COARSE for one of the phrases a
    survivor without a watch sees, CLOCK_UNKNOWN for "???", and
    CLOCK_UNRECOGNISED for anything else -- which is information, not
    grounds for discarding the reading.
    """
    if value is None:
        return CLOCK_NULL
    if not isinstance(value, str):
        raise ManifestError(
            "a clock reading is a string or None, got %s"
            % type(value).__name__)
    text = value.strip()
    if CLOCK_24H_RE.match(text):
        return CLOCK_EXACT
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
    if kind == CLOCK_UNRECOGNISED:
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


def _validated_commentary(value):
    """Return the survivor's own words, with an advisory if needed."""
    text = _validated_text(value, "commentary")
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
    "Z"-suffixed output of `date -u +%Y-%m-%dT%H:%M:%S.%3NZ`; an aware
    datetime; or None to stamp the current instant.  A value with no
    timezone is refused rather than assumed to be UTC, because a
    timestamp with no zone is not sortable across hosts and guessing
    one would be an invention.
    """
    if value is None:
        return utc_timestamp()
    if isinstance(value, datetime.datetime):
        return _format_moment(value)
    if not isinstance(value, str):
        raise ManifestError(
            "real_ts must be an ISO-8601 string, a datetime or None, "
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
    path.  `ingame_clock` may be None; nothing else may be.
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


def _fsync(handle):
    """Force a written row to the device, tolerating a refusal.

    A crash mid-session must not lose the row for a frame that already
    exists on disk.  flush() has handed the bytes to the operating
    system by this point, so a filesystem that refuses fsync is
    reported once rather than allowed to end the session.
    """
    try:
        os.fsync(handle.fileno())
    except OSError as err:
        _warn_once(
            "fsync",
            "could not fsync the manifest (%s); rows are flushed but "
            "not forced to the device" % err)


def append_row(manifest_path, frame, file, real_ts, ingame_clock,
               action, commentary):
    """Validate one row and append it to the manifest.

    The only writer in this module, and the only writer of this file.
    Returns the row exactly as written, so the caller can log or
    assert on it.  Raises ManifestError and writes nothing at all if
    any field is wrong -- there is no partial row.

    `manifest_path` is explicit rather than defaulted so that a test,
    a dry run and the real session cannot be confused for one another;
    default_manifest_path() supplies the pipeline's own value.

    What this does NOT do is police the index sequence, deliberately.
    Checking that an index follows the last one written would mean
    reading the whole file on every append -- quadratic over a session,
    and a writer that behaves differently depending on what is already
    on disk.  Instead a repeated or skipped index is recorded honestly
    and reported loudly afterwards by verify_manifest(), which is also
    what the acceptance gate runs.  The counter stays session.py's.
    """
    path = _validated_manifest_path(manifest_path)
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
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        _fsync(handle)
    return row


def append_record(manifest_path, row):
    """Append a row supplied as a mapping of the six fields.

    A convenience for a caller that already holds a dict; it shares
    append_row()'s validation exactly, so neither entry point can be
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


def read_rows(manifest_path=None):
    """Return every row on disk, in file order.  Read-only.

    Opened for reading only, and the returned dicts are copies, so no
    caller of this module can rewrite the record through it.  Key
    order is preserved as it appears on disk, which is what lets
    verify_manifest() check the declared order of the file itself.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_path(manifest_path, "manifest path")
    if not os.path.isfile(path):
        raise ManifestError("no manifest at %s" % path)
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for number, raw in enumerate(handle, start=1):
            rows.append(_decode_line(raw, number, path))
    return rows


def count_rows(manifest_path=None):
    """Return the number of rows on disk.  Read-only.

    The count that must equal the number of PNGs in the frames
    directory -- one keystroke, one capture, one row.
    """
    return len(read_rows(manifest_path))


def last_recorded_frame(manifest_path=None):
    """Return the last frame index recorded, or 0 if there is none.

    An observation for the resume branch, not a generator: session.py
    owns the frame counter and this module never increments anything.
    A manifest that does not exist yet answers 0, which is how a fresh
    session is distinguished from a resumed one.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_path(manifest_path, "manifest path")
    if not os.path.isfile(path):
        return 0
    rows = read_rows(path)
    if not rows:
        return 0
    last = rows[-1].get("frame")
    if isinstance(last, bool) or not isinstance(last, int):
        raise ManifestError(
            "the last row of %s carries a non-integer frame: %r"
            % (path, last))
    return last


def _shape_problems(path):
    """Report defects in the file's byte shape.  Read-only."""
    problems = []
    with open(path, "rb") as handle:
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


def _row_problems(row, number):
    """Report every schema defect in one row.  Read-only."""
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
    return problems


def _sequence_problems(rows):
    """Report gaps, repeats and reorderings.  Read-only."""
    problems = []
    for position, row in enumerate(rows, start=1):
        frame = row.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            continue
        if frame != position:
            problems.append(
                "row %d records frame %d; the indices run 1..n with "
                "no gap, no repeat and no reordering"
                % (position, frame))
    return problems


def _frame_problems(rows, frames_dir):
    """Report rows whose capture is missing on disk.  Read-only."""
    problems = []
    directory = _validated_directory(frames_dir, "frames directory")
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
                    require_frames=False):
    """Return a list of problems with the manifest.  Read-only.

    An empty list means the file satisfies the schema, the byte shape
    and the one-row-per-frame invariant.  With `require_frames` the
    capture named by each row must also exist.  Nothing is repaired,
    reordered or rewritten: a problem is reported so that a human can
    decide, which for this file means a note in
    playthrough/TECHNICAL_NOTES.md rather than an edit here.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_path(manifest_path, "manifest path")
    if not os.path.isfile(path):
        return ["no manifest at %s" % path]
    try:
        rows = read_rows(path)
    except ManifestError as err:
        return [str(err)]
    problems = _shape_problems(path)
    for number, row in enumerate(rows, start=1):
        problems.extend(_row_problems(row, number))
    problems.extend(_sequence_problems(rows))
    if require_frames:
        if frames_dir is None:
            frames_dir = default_frames_dir()
        problems.extend(_frame_problems(rows, frames_dir))
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
              "or <repository>/playthrough/manifest.jsonl"))
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


def main(argv=None):
    """Run the read-only command line and return an exit status."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "count":
            print(count_rows(args.manifest))
            return 0
        problems = verify_manifest(
            args.manifest,
            frames_dir=args.frames_dir,
            require_frames=args.require_frames)
        total = count_rows(args.manifest) if not problems else 0
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
