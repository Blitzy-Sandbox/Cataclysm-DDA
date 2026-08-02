#!/usr/bin/env python3
"""Turn playthrough/manifest.jsonl into playthrough/timeline.json.

This module owns every number the film is paced by, and it is the ONLY
place those numbers are computed.  playthrough/timeline.json is the
single source of truth: make_transitions.py, render_movie.py and
make_srt.py all read it rather than re-deriving durations of their own.
That is not tidiness, it is the fix for a measured defect -- a probe
render without a shared timeline produced a 10.52 s container against
an 11.75 s subtitle stream, because a caption generator that walks
frame durations without charging the inserted transition seconds is
correct at the start of the film and increasingly wrong by the end.
With one artifact the drift is not unlikely, it is arithmetically
impossible.

THE MODEL
    duration[i] = min(max(clock[i + 1] - clock[i], 0.25), 10.0)

The in-game clock is READ and DIFFERENCED.  Turns are not modelled,
moves are not modelled and no conversion constant appears anywhere in
this file -- community documentation puts roughly a hundred moves at
about one second of game time, and the whole point of differencing the
sidebar clock is to sidestep that ambiguity instead of encoding it.
The 0.25 s floor and the 10.0 s ceiling are the only two deviations
from a literal one-second-of-video-per-second-of-game-time mapping.

Zero-delta frames are load-bearing and are kept at the floor.  Menu
navigation and character creation consume no game time; those frames
fall to 0.25 s.  They are never merged, dropped or optimised away,
because one keystroke produced one capture and that relation has to
survive into the movie.

TRANSITIONS ARE CHARGED TO VIDEO TIME, NOT GAME TIME
A raw delta above the ceiling sets transition_after, and the cue
cursor advances by TRANSITION seconds after that frame's window and
before the next frame's window opens.  That single detail is why the
cue following a transition starts at 00:00:17,250 and not at
00:00:16,250 on the reference sequence.  A raw delta of exactly 10.0 s
is NOT a transition: the comparison is strictly greater.

THE INVARIANT, asserted by validate_timeline() and carried in the
artifact so a reader can check it without running anything:

    sum(durations) + sum(transitions) == total == final cue end

WHY THE CLOCK PARSE IS RELIABLE
to_string_time_of_day (src/calendar.cpp:638-663) has three branches:
"military" gives "%02d%02d.%02d", "24h" gives "%02d:%02d:%02d", and
the 12h default gives "%d:%02d:%02d%sAM"/"%sPM" with padding removed
as necessary.  Only the 24h branch is fixed width, which is exactly
why seed_options.py sets 24_HOUR=24h -- the default is "12h"
(src/options.cpp:1868-1877).  Anything that does not match
CLOCK_RE is refused rather than guessed at.

NEVER FABRICATE
display::time_string (src/display.cpp:207-218) returns an exact clock
only when the survivor has a watch; otherwise one of the coarse
phrases from display::time_approx (src/display.cpp:159-186), or "???"
when the sky is not visible.  A reading that is absent, coarse,
unknown, in another format or moving backwards is RECONCILED against
the last trusted reading and FLAGGED in the artifact -- never
smoothed, never interpolated, never invented.  Every such frame
carries reconciled=true and a reconciled_reason, so a reader can see
which clocks were reconciled instead of having to trust that none
were.  The manifest keeps the reading verbatim; this module keeps the
audit trail.

The six-field manifest schema carries no date line, so the day counter
here is inferred from the clock alone under the rollover rule
documented at MAX_WRAP_ADVANCE.  display::date_string
(src/display.cpp:193-205) is what a human cross-checks against; it is
deliberately not a manifest field, because adding one would create the
second source of truth this pipeline exists to avoid.

USE
    python3 playthrough/tooling/timeline.py
    python3 playthrough/tooling/timeline.py --stdout
    python3 playthrough/tooling/timeline.py --verify

    import timeline
    doc = timeline.build_timeline(rows)
    cue = timeline.format_srt_timecode(doc["frames"][0]["cue_start"])

The mathematics is exposed as pure functions -- parse, absolutise,
delta, clamp, flag, cue walk, formatter -- separately from every
filesystem call, so test_timeline.py can assert all of it without
touching the disk.  format_srt_timecode lives here rather than in
make_srt.py so that there is exactly one implementation of the
timecode and exactly one module to import.

Standard library only, plus the sibling manifest module: nothing here
needs playthrough/tooling/requirements.txt, so the timeline can be
recomputed and audited in any checkout.
"""

import argparse
import json
import math
import os
import re
import sys

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    # The six-field schema, the manifest reader and the clock
    # classifier live in the sibling module; sharing them is what keeps
    # the coarse-phrase list from existing twice.
    import manifest
except ImportError:
    # Imported from somewhere other than this directory: put the
    # tooling directory on the path and try once more.  A second
    # failure is a genuinely broken checkout and is allowed to raise.
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    import manifest


# The three constants the requirements fix.  They are values, not
# tunables: a floor of a quarter second keeps a zero-delta frame
# visible, a ceiling of ten seconds keeps a night's sleep watchable,
# and one second of video buys the fade-out, the card and the fade-in
# that make_transitions.py materialises when the ceiling engages.
FLOOR = 0.25
CEIL = 10.0
TRANSITION = 1.0

# Clock arithmetic.  A Cataclysm day is twenty-four hours: the
# sidebar reading is hour_of_day, minute_of_hour and
# to_seconds(time_past_midnight) % 60 (src/calendar.cpp:640-642).
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
SECONDS_PER_HOUR = SECONDS_PER_MINUTE * MINUTES_PER_HOUR
SECONDS_PER_DAY = SECONDS_PER_HOUR * HOURS_PER_DAY

# The contracted reading, and the only shape that is parsed: the
# fixed-width 24h form (src/calendar.cpp:649).  Deliberately anchored
# at both ends -- a match on a substring of a longer string would be a
# guess about which part of it was the clock.
CLOCK_RE = re.compile(r"^[0-9]{2}:[0-9]{2}:[0-9]{2}$")

# How far a wrap may imply the clock advanced before it is treated as
# a reading that moved backwards rather than as a crossing of
# midnight.  A wrap of 23:59:58 -> 00:00:04 implies six seconds; a
# night's sleep of 22:10:00 -> 06:30:00 implies eight and a third
# hours; both are ordinary play.  A reading of 08:00:00 followed by
# 07:59:00 would imply an advance of 23 h 59 m from one keystroke,
# which no single action produces -- that is a misread going
# backwards, and it is refused and flagged instead of being inflated
# into a phantom day.  The bound is therefore set as permissively as
# it can be while still catching that class: nothing legitimate is
# lost below it, because no keystroke advances the clock by more than
# 23 hours.  It is a rollover-plausibility bound and nothing else --
# in particular it is NOT a game-time conversion factor, of which
# this module has none.
MAX_WRAP_ADVANCE = 23 * SECONDS_PER_HOUR

# Millisecond resolution, which is all SubRip can express.  Anything
# finer in the artifact would be false precision and would invite a
# cue end that disagrees with a cue start by a rounding step.
DECIMALS = 3

# The schema version of playthrough/timeline.json.  Written into the
# artifact so a future reader knows which shape it is holding.
TIMELINE_VERSION = 1

# Why a clock was reconciled instead of read.  Short, stable, greppable
# codes: they end up in the committed artifact, so they are part of its
# contract.
RECONCILED_MISSING = "clock-missing"
RECONCILED_COARSE = "clock-coarse"
RECONCILED_UNKNOWN = "clock-unknown"
RECONCILED_NONSTANDARD = "clock-nonstandard-format"
RECONCILED_UNPARSEABLE = "clock-unparseable"
RECONCILED_BACKWARDS = "clock-not-monotonic"

# manifest.classify_ingame_clock() describes a reading; this maps its
# answer onto the reason recorded here.  CLOCK_EXACT is absent on
# purpose: an exact reading is parsed, not reconciled.
_REASON_BY_KIND = {
    manifest.CLOCK_NULL: RECONCILED_MISSING,
    manifest.CLOCK_COARSE: RECONCILED_COARSE,
    manifest.CLOCK_UNKNOWN: RECONCILED_UNKNOWN,
    manifest.CLOCK_NONSTANDARD: RECONCILED_NONSTANDARD,
    manifest.CLOCK_UNRECOGNISED: RECONCILED_UNPARSEABLE,
}

# The keys of one entry in the frames array, in the order they are
# written.  Sibling validators rely on frame, file, raw_delta,
# duration, transition_after, cue_start, cue_end, action, commentary
# and reconciled by name, so the tuple is the authority for what this
# module emits and validate_timeline() checks against it.
ENTRY_FIELDS = (
    "frame",
    "file",
    "real_ts",
    "ingame_clock",
    "clock_kind",
    "clock_seconds",
    "reconciled",
    "reconciled_reason",
    "raw_delta",
    "duration",
    "transition_after",
    "cue_start",
    "cue_end",
    "action",
    "commentary",
)

# The top-level keys, in the order they are written.  The constants
# travel with the data so the clamp can be verified from the artifact
# alone, and the totals travel with it so the invariant can be checked
# without recomputing anything.
DOCUMENT_FIELDS = (
    "version",
    "floor",
    "ceil",
    "transition",
    "frame_count",
    "transition_count",
    "reconciled_count",
    "total_duration",
    "total_transition",
    "total",
    "final_cue_end",
    "frames",
)


class TimelineError(Exception):
    """The manifest cannot be turned into an honest timeline.

    Raised in place of writing a timeline that would be wrong, because
    a wrong timeline is worse than no timeline: it would pace the film
    and the captions from the same bad numbers and look consistent
    while doing it.
    """


@dataclass(frozen=True)
class ClockReading:
    """One frame's clock, absolutised and audited.

    `seconds` is the absolutised reading -- day * 86400 plus the time
    of day -- and is monotonically non-decreasing across a session by
    construction.  `reconciled` is true when `seconds` was carried
    from a neighbour rather than read from this frame, in which case
    `reason` says why; `text` is the reading exactly as the manifest
    recorded it, and `kind` is manifest.classify_ingame_clock()'s
    description of it.  Frozen because a reading is evidence.
    """

    seconds: int
    reconciled: bool
    reason: Optional[str]
    kind: str
    text: Optional[str]


def _warn(message: str) -> None:
    """Report a non-fatal problem on stderr and carry on.

    The prefix matches playthrough_warn() in
    playthrough/tooling/env.sh and manifest.py's own reporting, so
    every stage of the pipeline is recognisable in one session log.
    """
    print("playthrough: WARNING: timeline.py: %s" % message,
          file=sys.stderr, flush=True)


# ---------------------------------------------------------------------
# Pure arithmetic.  Nothing below this line until the IO section
# touches the filesystem, the environment or the clock of the machine
# it runs on: the same inputs always produce the same outputs, which is
# what makes the whole feature testable.
# ---------------------------------------------------------------------


def round_seconds(value: float) -> float:
    """Return `value` at the artifact's millisecond resolution.

    Every duration and cue time in playthrough/timeline.json goes
    through here, so the file cannot carry a number finer than a
    subtitle cue can express.  A negative zero is normalised to zero,
    because "-0.0" in a committed JSON file is noise that would show up
    in a diff.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TimelineError(
            "a duration must be a number, got %s"
            % type(value).__name__)
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise TimelineError(
            "a duration must be finite, got %r" % value)
    rounded = round(number, DECIMALS)
    if rounded == 0.0:
        # Collapses both 0.0 and -0.0 onto one representation.
        return 0.0
    return rounded


def parse_time_of_day(value: Any) -> Optional[int]:
    """Return seconds since midnight for a contracted reading.

    Accepts only the fixed-width 24h form the session is configured to
    render (src/calendar.cpp:649) and returns None for everything else
    -- an absent reading, a coarse phrase, "???", a military or 12h
    clock, OCR debris, or a syntactically valid reading whose fields
    are out of range such as "24:00:00" or "08:75:00".  Returning None
    is how this module refuses to guess: the caller reconciles and
    flags, it never invents.

    Surrounding whitespace is ignored, which is a transcription
    detail rather than a reading, and matches how
    manifest.classify_ingame_clock() describes the same value.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not CLOCK_RE.match(text):
        return None
    hours = int(text[0:2])
    minutes = int(text[3:5])
    seconds = int(text[6:8])
    if hours >= HOURS_PER_DAY:
        return None
    if minutes >= MINUTES_PER_HOUR or seconds >= SECONDS_PER_MINUTE:
        return None
    return (hours * SECONDS_PER_HOUR +
            minutes * SECONDS_PER_MINUTE +
            seconds)


# Short alias.  The pipeline talks about "parsing the clock", and a
# caller that reaches for the obvious name should find it.
parse_clock = parse_time_of_day


def clock_kind(value: Any) -> str:
    """Describe a reading using the manifest's own classification.

    Delegated rather than reimplemented so that the eleven coarse
    phrases from display::time_approx (src/display.cpp:159-186) are
    listed in exactly one file.  A value the classifier refuses -- a
    number, a list -- is reported as unrecognised here rather than
    raising, because this module's job is to survive a bad manifest
    loudly, not to stop on it.
    """
    try:
        return manifest.classify_ingame_clock(value)
    except manifest.ManifestError:
        return manifest.CLOCK_UNRECOGNISED


def reason_for_reading(value: Any) -> Optional[str]:
    """Return why a reading is unusable, or None if it parses.

    The reason codes are part of the artifact's contract, so this is
    the one place they are chosen.
    """
    if parse_time_of_day(value) is not None:
        return None
    return _REASON_BY_KIND.get(clock_kind(value), RECONCILED_UNPARSEABLE)


def _next_absolute(
    time_of_day: int,
    day: int,
    previous_time_of_day: Optional[int],
    previous_absolute: Optional[int],
) -> Tuple[int, int, bool]:
    """Absolutise one parsed reading against the session so far.

    Returns the absolute value, the day counter to carry forward, and
    whether the reading was trusted.  Three cases, in the order they
    are decided:

    * no trusted reading yet -- this one anchors the session at day 0;
    * the clock did not go backwards -- same day, straightforward;
    * the clock went backwards -- a crossing of midnight if the
      implied advance is plausible (see MAX_WRAP_ADVANCE), in which
      case the day counter increments and the delta comes out POSITIVE,
      and otherwise a reading that is refused, leaving the caller to
      carry the previous absolute forward and flag it.
    """
    if previous_time_of_day is None:
        return day * SECONDS_PER_DAY + time_of_day, day, True
    if time_of_day >= previous_time_of_day:
        return day * SECONDS_PER_DAY + time_of_day, day, True
    advance = SECONDS_PER_DAY - previous_time_of_day + time_of_day
    if advance <= MAX_WRAP_ADVANCE:
        return (day + 1) * SECONDS_PER_DAY + time_of_day, day + 1, True
    anchor = 0 if previous_absolute is None else previous_absolute
    return anchor, day, False


def absolutise_clocks(readings: Sequence[Any]) -> List[ClockReading]:
    """Absolutise a session's readings, monotonic forward only.

    Walks the readings once, carrying a day counter that increments on
    every crossing of midnight, so that 23:59:58 -> 00:00:04 yields a
    POSITIVE six-second step rather than a negative one.  A reading
    that cannot be parsed, or that would move time backwards without
    being explicable as a crossing of midnight, is reconciled against
    the last trusted reading and flagged; the day counter and the
    trusted time of day stay anchored to that last good reading, so a
    single misread frame cannot corrupt the delta of the frame after
    it.

    Readings before the first trusted one -- the language prompt, the
    main menu, character creation, all of which are captured before a
    world exists and therefore have no clock at all -- are anchored
    FORWARD to the first trusted reading rather than to zero.  They
    then differ by nothing and land on the floor, which is what the
    requirements ask for: menu frames are kept at 0.25 s, not inflated
    into a phantom advance by the first real reading of the session.
    Every one of them is still flagged reconciled, so the anchoring is
    visible in the artifact rather than implied.

    The returned list is always the same length as `readings`.  No
    entry is dropped, merged or reordered.
    """
    day = 0
    previous_time_of_day: Optional[int] = None
    previous_absolute: Optional[int] = None
    out: List[ClockReading] = []
    for value in readings:
        kind = clock_kind(value)
        time_of_day = parse_time_of_day(value)
        if time_of_day is None:
            trusted = False
            seconds = (0 if previous_absolute is None
                       else previous_absolute)
            reason = _REASON_BY_KIND.get(kind, RECONCILED_UNPARSEABLE)
        else:
            seconds, day, trusted = _next_absolute(
                time_of_day, day, previous_time_of_day,
                previous_absolute)
            reason = None if trusted else RECONCILED_BACKWARDS
        if previous_absolute is not None and seconds < previous_absolute:
            # Unreachable through the branches above; kept because a
            # negative delta would be a silent lie about game time,
            # and this is the one place it can be made impossible.
            seconds = previous_absolute
            trusted = False
            reason = RECONCILED_BACKWARDS
        if trusted:
            previous_time_of_day = time_of_day
        previous_absolute = seconds
        out.append(ClockReading(
            seconds=seconds, reconciled=not trusted, reason=reason,
            kind=kind, text=value if isinstance(value, str) else None))
    return _anchor_leading_readings(out)


# US spelling, for a caller that reaches for it.
absolutize_clocks = absolutise_clocks


def _anchor_leading_readings(
    readings: Sequence[ClockReading],
) -> List[ClockReading]:
    """Anchor a leading run of unreadable clocks to the first reading.

    Menu and character-creation frames precede the first clock the
    session can show, so leaving them at zero would charge the whole
    of the first real reading to the last menu frame as a phantom
    advance.  Pulling them forward to the first trusted value gives
    them a zero delta and the 0.25 s floor instead, which is the
    documented treatment for frames that consume no game time.  They
    keep their reconciled flag and their reason, so nothing is
    concealed; and if no reading in the whole session was ever
    trusted, there is nothing to anchor to and the list is returned
    untouched.
    """
    first_trusted = None
    for index, reading in enumerate(readings):
        if not reading.reconciled:
            first_trusted = index
            break
    if first_trusted is None or first_trusted == 0:
        # Either there is no trusted reading at all, or the very first
        # reading is already trusted: nothing precedes it.
        return list(readings)
    anchor = readings[first_trusted].seconds
    adjusted = list(readings)
    for index in range(first_trusted):
        adjusted[index] = ClockReading(
            seconds=anchor,
            reconciled=True,
            reason=readings[index].reason,
            kind=readings[index].kind,
            text=readings[index].text)
    return adjusted


def raw_deltas(absolutes: Sequence[int]) -> List[float]:
    """Return the unclamped in-game seconds each frame is on screen.

    raw[i] is the clock advance between frame i and frame i + 1; the
    final frame has no successor and is therefore 0.0, which the floor
    turns into 0.25 s of video.  A negative delta cannot occur --
    absolutise_clocks() guarantees a non-decreasing sequence -- and is
    refused loudly here rather than propagated, because it would mean
    the guard upstream had broken.
    """
    values = list(absolutes)
    deltas: List[float] = []
    for index in range(len(values) - 1):
        delta = float(values[index + 1] - values[index])
        if delta < 0.0:
            raise TimelineError(
                "the absolutised clock moved backwards between frame "
                "%d and frame %d (%r -> %r); game time only ever runs "
                "forward"
                % (index + 1, index + 2, values[index],
                   values[index + 1]))
        deltas.append(delta)
    if values:
        deltas.append(0.0)
    return deltas


def clamp_duration(raw: float) -> float:
    """Clamp one raw delta into the on-screen duration.

    The floor keeps a zero-delta frame visible; the ceiling keeps a
    night's sleep watchable.  Nothing else is applied, and no frame is
    ever removed by this function -- a zero delta returns the floor,
    it does not return zero.
    """
    return min(max(round_seconds(raw), FLOOR), CEIL)


def clamp_durations(raws: Sequence[float]) -> List[float]:
    """Clamp every raw delta, one duration per frame, in order."""
    return [clamp_duration(raw) for raw in raws]


# The requirements call this operation "the clamp"; a caller that
# reaches for that word should find it.
clamp = clamp_duration


def is_transition(raw: float) -> bool:
    """Return whether a raw delta earns a cinematic transition.

    STRICTLY greater than the ceiling: a raw delta of exactly 10.0 s
    is shown at its full length with no transition after it.
    """
    return round_seconds(raw) > CEIL


def transition_flags(raws: Sequence[float]) -> List[bool]:
    """Return the transition flag for every frame, in order."""
    return [is_transition(raw) for raw in raws]


def cue_windows(
    durations: Sequence[float],
    flags: Sequence[bool],
) -> Tuple[List[Tuple[float, float]], float]:
    """Walk the video cursor and return every cue window and the total.

    Frame i occupies [cue_start, cue_end); the cursor then advances by
    that frame's duration, and by TRANSITION as well when the frame is
    flagged -- charged to VIDEO time, before the next frame's window
    opens.  That is what keeps the captions on the picture once
    transitions have been inserted, and it is why the cue after the
    first transition of the reference sequence starts at 17.25 s
    rather than 16.25 s.

    The returned total is the cursor's final value, which equals the
    last cue end whenever the last frame is unflagged -- and it always
    is, because the last frame's raw delta is 0.0 by construction.
    """
    if len(durations) != len(flags):
        raise TimelineError(
            "%d duration(s) against %d transition flag(s); every "
            "frame has exactly one of each"
            % (len(durations), len(flags)))
    cursor = 0.0
    windows: List[Tuple[float, float]] = []
    for duration, flagged in zip(durations, flags):
        start = round_seconds(cursor)
        end = round_seconds(start + round_seconds(duration))
        windows.append((start, end))
        cursor = end
        if flagged:
            cursor = round_seconds(cursor + TRANSITION)
    return windows, round_seconds(cursor)


def timeline_total(
    durations: Sequence[float],
    flags: Sequence[bool],
) -> float:
    """Return sum(durations) + sum(transitions) for a timeline.

    The invariant's left-hand side, computed independently of the cue
    walk so that the two can be compared rather than assumed equal.
    """
    total = math.fsum(round_seconds(value) for value in durations)
    total += TRANSITION * sum(1 for flagged in flags if flagged)
    return round_seconds(total)


def format_srt_timecode(seconds: float) -> str:
    """Return `seconds` as a SubRip timecode, "HH:MM:SS,mmm".

    A COMMA before the milliseconds: this is SubRip, not WebVTT, and a
    full stop there produces a file some players silently ignore.
    Hours are zero-padded to two digits even when there are none, so
    every cue in playthrough/transcript.srt has the same width; a film
    longer than a hundred hours widens the field rather than
    truncating, which SubRip tolerates.

    Milliseconds are rounded half-up so that the same input always
    gives the same timecode -- 3661.5 s is 01:01:01,500 exactly.  The
    values this pipeline produces are whole multiples of a quarter
    second and so are never near a rounding boundary, but a formatter
    that rounded a shade differently on a different platform would put
    the captions and the container out of step, which is precisely the
    failure the shared timeline exists to prevent.

    Negative time has no meaning in a caption file and is refused
    rather than wrapped.
    """
    if not isinstance(seconds, (int, float)) or isinstance(seconds,
                                                           bool):
        raise TimelineError(
            "a timecode needs a number of seconds, got %s"
            % type(seconds).__name__)
    value = float(seconds)
    if math.isnan(value) or math.isinf(value):
        raise TimelineError(
            "a timecode needs a finite number of seconds, got %r"
            % seconds)
    if value < 0.0:
        raise TimelineError(
            "a timecode cannot be negative, got %r" % seconds)
    total_ms = int(math.floor(value * 1000.0 + 0.5))
    hours, remainder = divmod(total_ms, SECONDS_PER_HOUR * 1000)
    minutes, remainder = divmod(remainder, SECONDS_PER_MINUTE * 1000)
    whole, milliseconds = divmod(remainder, 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, whole,
                                    milliseconds)


# ---------------------------------------------------------------------
# The artifact.  Still pure: build_timeline() takes rows and returns a
# dictionary, so the whole computation can be exercised without a
# manifest on disk and without writing anything.
# ---------------------------------------------------------------------


def _row_index(row: Dict[str, Any], position: int) -> int:
    """Return a row's frame index, or its position if it has none.

    session.py owns the counter and every real row carries it; a row
    that does not is numbered by where it sits, which is what an index
    means.  A present index has to be a genuine positive integer,
    because a string or a float there would put the frames array out of
    step with the frames directory.
    """
    if "frame" not in row:
        return position
    value = row["frame"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimelineError(
            "row %d records a %s as its frame index; the index is an "
            "integer from 1" % (position, type(value).__name__))
    if value < 1:
        raise TimelineError(
            "row %d records frame %d; the indices run from 1"
            % (position, value))
    return value


def _row_text(row: Dict[str, Any], key: str) -> str:
    """Return a carried-through text field, defaulting to empty.

    action and commentary belong to the in-character record and are
    copied VERBATIM: this module never edits, summarises, translates or
    annotates them, and never injects engineering language into the
    survivor's voice.  A row that omits one carries an empty string
    rather than an invented sentence.
    """
    value = row.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TimelineError(
            "%s must be text, got %s" % (key, type(value).__name__))
    return value


def _row_file(row: Dict[str, Any], index: int) -> str:
    """Return the capture path for a row.

    Rebuilt from the index when the row omits it, using the manifest's
    own format so the renderer's concat list and the manifest cannot
    disagree about a filename.
    """
    value = row.get("file")
    if value is None:
        return manifest.FRAME_FILE_FORMAT % index
    if not isinstance(value, str):
        raise TimelineError(
            "file must be text, got %s" % type(value).__name__)
    return value


def _entry(
    row: Dict[str, Any],
    position: int,
    reading: ClockReading,
    raw: float,
    duration: float,
    flagged: bool,
    window: Tuple[float, float],
) -> Dict[str, Any]:
    """Assemble one entry of the frames array, keys in fixed order."""
    index = _row_index(row, position)
    real_ts = row.get("real_ts")
    if real_ts is not None and not isinstance(real_ts, str):
        raise TimelineError(
            "real_ts must be text or absent, got %s"
            % type(real_ts).__name__)
    entry = {
        "frame": index,
        "file": _row_file(row, index),
        "real_ts": real_ts,
        # The reading exactly as the manifest recorded it, including
        # JSON null when the clock could not be read.  Never repaired.
        "ingame_clock": reading.text,
        "clock_kind": reading.kind,
        "clock_seconds": reading.seconds,
        "reconciled": reading.reconciled,
        "reconciled_reason": reading.reason,
        "raw_delta": round_seconds(raw),
        "duration": round_seconds(duration),
        "transition_after": bool(flagged),
        "cue_start": round_seconds(window[0]),
        "cue_end": round_seconds(window[1]),
        "action": _row_text(row, "action"),
        "commentary": _row_text(row, "commentary"),
    }
    return {name: entry[name] for name in ENTRY_FIELDS}


def build_timeline(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute the whole timeline from manifest rows.  Pure.

    Takes the rows of playthrough/manifest.jsonl -- or any sequence of
    mappings shaped like them -- and returns the document that
    playthrough/timeline.json holds: one entry per row in the same
    order, plus the totals and the constants they were computed under.
    Nothing is dropped, merged, reordered or decimated, so the length
    of the frames array is always the number of rows given.

    Strictness is split deliberately.  This function refuses only what
    would make the arithmetic wrong -- a non-integer frame index, a
    non-text action -- and tolerates a row that omits a presentational
    field, so the mathematics can be exercised from a two-key test row.
    The stricter shape check that every real row carries all six
    manifest fields belongs to manifest.verify_manifest() and to
    main(), which runs before writing.
    """
    materialised = [_as_row(row, position)
                    for position, row in enumerate(rows, start=1)]
    readings = absolutise_clocks(
        [row.get("ingame_clock") for row in materialised])
    deltas = raw_deltas([reading.seconds for reading in readings])
    durations = clamp_durations(deltas)
    flags = transition_flags(deltas)
    windows, cursor_total = cue_windows(durations, flags)
    entries = [
        _entry(row, position, readings[position - 1],
               deltas[position - 1], durations[position - 1],
               flags[position - 1], windows[position - 1])
        for position, row in enumerate(materialised, start=1)
    ]
    total_duration = round_seconds(math.fsum(durations))
    transition_count = sum(1 for flagged in flags if flagged)
    total_transition = round_seconds(TRANSITION * transition_count)
    document = {
        "version": TIMELINE_VERSION,
        # The clamp travels with the data, so a reader can verify every
        # duration against the constants it was produced under without
        # opening this file.
        "floor": FLOOR,
        "ceil": CEIL,
        "transition": TRANSITION,
        "frame_count": len(entries),
        "transition_count": transition_count,
        "reconciled_count": sum(1 for entry in entries
                                if entry["reconciled"]),
        "total_duration": total_duration,
        "total_transition": total_transition,
        # The invariant, in the artifact: total is the cursor's final
        # value, and final_cue_end is the last window's end.  They are
        # computed by different routes on purpose, so that a reader
        # comparing them is checking something rather than reading the
        # same number twice.
        "total": round_seconds(cursor_total),
        "final_cue_end": (round_seconds(windows[-1][1])
                          if windows else 0.0),
        "frames": entries,
    }
    return {name: document[name] for name in DOCUMENT_FIELDS}


# Naming alias, for a caller that thinks of this as a computation
# rather than a build step.
compute_timeline = build_timeline


def _as_row(row: Any, position: int) -> Dict[str, Any]:
    """Return one input row as a mapping, or raise."""
    if not isinstance(row, dict):
        raise TimelineError(
            "row %d is a %s; a manifest row is a JSON object of the "
            "fields %s" % (position, type(row).__name__,
                           ", ".join(manifest.FIELDS)))
    return row


# ---------------------------------------------------------------------
# Verification.  Every property the acceptance gate checks is asserted
# here as well, so the pipeline fails on its own arithmetic before the
# renderer or the caption muxer ever sees it.
# ---------------------------------------------------------------------

# Comparison tolerance.  Every number this module emits is a whole
# multiple of a quarter second and therefore exact in binary floating
# point, so these comparisons hold exactly on real output; the
# tolerance is here so that a caller feeding fractional durations gets
# a real answer instead of a rounding artefact.
EPSILON = 1e-9


def _close(left: float, right: float) -> bool:
    """Return whether two second counts agree to the millisecond."""
    return abs(float(left) - float(right)) <= EPSILON


def _entry_problems(
    entry: Any,
    position: int,
    allow_index_gaps: bool,
) -> List[str]:
    """Report every defect in one entry of the frames array."""
    if not isinstance(entry, dict):
        return ["entry %d is a %s, not an object"
                % (position, type(entry).__name__)]
    missing = [name for name in ENTRY_FIELDS if name not in entry]
    if missing:
        return ["entry %d is missing %s"
                % (position, ", ".join(missing))]
    problems = []
    index = entry["frame"]
    if isinstance(index, bool) or not isinstance(index, int):
        problems.append(
            "entry %d records a %s as its frame index"
            % (position, type(index).__name__))
    elif index != position and not allow_index_gaps:
        problems.append(
            "entry %d records frame %d; the indices run 1..n with no "
            "gap, no repeat and no reordering" % (position, index))
    duration = entry["duration"]
    raw = entry["raw_delta"]
    for name in ("raw_delta", "duration", "cue_start", "cue_end"):
        value = entry[name]
        if isinstance(value, bool) or not isinstance(
                value, (int, float)):
            problems.append(
                "entry %d %s is not a number: %r"
                % (position, name, value))
            return problems
    if raw < -EPSILON:
        problems.append(
            "entry %d raw_delta is negative (%r); game time only ever "
            "runs forward" % (position, raw))
    if duration < FLOOR - EPSILON or duration > CEIL + EPSILON:
        problems.append(
            "entry %d duration %r is outside the clamp [%s, %s]"
            % (position, duration, FLOOR, CEIL))
    expected_flag = raw > CEIL
    if bool(entry["transition_after"]) != expected_flag:
        problems.append(
            "entry %d transition_after is %r for a raw delta of %r; "
            "the flag is set when and only when the delta exceeds %s"
            % (position, entry["transition_after"], raw, CEIL))
    expected_duration = clamp_duration(raw)
    if not _close(duration, expected_duration):
        problems.append(
            "entry %d duration %r does not clamp its raw delta %r, "
            "which gives %r" % (position, duration, raw,
                                expected_duration))
    if not _close(entry["cue_end"], entry["cue_start"] + duration):
        problems.append(
            "entry %d cue window [%r, %r) is not %r long"
            % (position, entry["cue_start"], entry["cue_end"],
               duration))
    reconciled = entry["reconciled"]
    if not isinstance(reconciled, bool):
        problems.append(
            "entry %d reconciled is %r, which is not a boolean"
            % (position, reconciled))
    elif reconciled and not entry["reconciled_reason"]:
        problems.append(
            "entry %d is reconciled but records no reason; a "
            "reconciled clock is flagged with why, never silently"
            % position)
    elif not reconciled and entry["reconciled_reason"]:
        problems.append(
            "entry %d records the reason %r but is not flagged "
            "reconciled" % (position, entry["reconciled_reason"]))
    return problems


def validate_timeline(
    document: Any,
    allow_index_gaps: bool = False,
) -> List[str]:
    """Return every problem with a timeline document.  Pure.

    An empty list means the document satisfies all of it: the clamp
    bounds on every frame, the strictly-greater transition rule, the
    contiguity of the cue windows, the transition second charged to
    video time between them, a non-decreasing absolutised clock, a
    reason recorded for every reconciled reading, and the invariant

        sum(durations) + sum(transitions) == total == final cue end

    Nothing is repaired.  A problem is reported so that the pipeline
    stops before pacing a film and its captions from numbers that do
    not agree.
    """
    if not isinstance(document, dict):
        return ["the timeline is a %s, not an object with a frames "
                "array" % type(document).__name__]
    missing = [name for name in DOCUMENT_FIELDS
               if name not in document]
    if missing:
        return ["the timeline is missing %s" % ", ".join(missing)]
    frames = document["frames"]
    if not isinstance(frames, list):
        return ["frames is a %s, not an array"
                % type(frames).__name__]
    problems = []
    for name, expected in (("floor", FLOOR), ("ceil", CEIL),
                           ("transition", TRANSITION)):
        if not _close(document[name], expected):
            problems.append(
                "the timeline was written under %s=%r but this module "
                "uses %r; the constants are fixed, not tunable"
                % (name, document[name], expected))
    if document["frame_count"] != len(frames):
        problems.append(
            "frame_count is %r for %d entr(ies)"
            % (document["frame_count"], len(frames)))
    for position, entry in enumerate(frames, start=1):
        problems.extend(
            _entry_problems(entry, position, allow_index_gaps))
    if problems:
        # The cross-entry checks below index into fields the per-entry
        # checks have just shown to be unsound, so they would only
        # produce noise on top of a real answer.
        return problems
    problems.extend(_sequence_problems(frames))
    problems.extend(_total_problems(document, frames))
    return problems


def _sequence_problems(frames: Sequence[Dict[str, Any]]) -> List[str]:
    """Report defects that only show up across entries."""
    problems = []
    if frames and not _close(frames[0]["cue_start"], 0.0):
        problems.append(
            "the first cue starts at %r; a timeline starts at zero"
            % frames[0]["cue_start"])
    for position in range(len(frames) - 1):
        here = frames[position]
        nxt = frames[position + 1]
        gap = TRANSITION if here["transition_after"] else 0.0
        expected = here["cue_end"] + gap
        if not _close(nxt["cue_start"], expected):
            problems.append(
                "entry %d starts at %r; entry %d ends at %r and is "
                "followed by %rs of transition, so it should start at "
                "%r" % (position + 2, nxt["cue_start"], position + 1,
                        here["cue_end"], gap, expected))
        if nxt["clock_seconds"] < here["clock_seconds"]:
            problems.append(
                "the absolutised clock falls from %r to %r between "
                "entry %d and entry %d"
                % (here["clock_seconds"], nxt["clock_seconds"],
                   position + 1, position + 2))
    if frames and frames[-1]["transition_after"]:
        problems.append(
            "the last entry is flagged for a transition; the final "
            "frame has no successor, so its raw delta is zero and "
            "nothing follows it to transition into")
    if frames and not _close(frames[-1]["raw_delta"], 0.0):
        problems.append(
            "the last entry records a raw delta of %r; the final "
            "frame has no successor to difference against"
            % frames[-1]["raw_delta"])
    return problems


def _total_problems(
    document: Dict[str, Any],
    frames: Sequence[Dict[str, Any]],
) -> List[str]:
    """Report defects in the totals, including THE INVARIANT."""
    problems = []
    durations = math.fsum(entry["duration"] for entry in frames)
    flagged = sum(1 for entry in frames if entry["transition_after"])
    reconciled = sum(1 for entry in frames if entry["reconciled"])
    if not _close(document["total_duration"], durations):
        problems.append(
            "total_duration is %r but the frames sum to %r"
            % (document["total_duration"], round_seconds(durations)))
    if document["transition_count"] != flagged:
        problems.append(
            "transition_count is %r but %d entr(ies) are flagged"
            % (document["transition_count"], flagged))
    if document["reconciled_count"] != reconciled:
        problems.append(
            "reconciled_count is %r but %d entr(ies) are flagged"
            % (document["reconciled_count"], reconciled))
    if not _close(document["total_transition"],
                  TRANSITION * flagged):
        problems.append(
            "total_transition is %r for %d transition(s) of %rs"
            % (document["total_transition"], flagged, TRANSITION))
    grand = document["total_duration"] + document["total_transition"]
    if not _close(document["total"], grand):
        problems.append(
            "total is %r but %r of frames plus %r of transitions is "
            "%r" % (document["total"], document["total_duration"],
                    document["total_transition"],
                    round_seconds(grand)))
    end = frames[-1]["cue_end"] if frames else 0.0
    if not _close(document["final_cue_end"], end):
        problems.append(
            "final_cue_end is %r but the last cue ends at %r"
            % (document["final_cue_end"], end))
    if not _close(document["total"], document["final_cue_end"]):
        problems.append(
            "total is %r but the final cue ends at %r; the captions "
            "and the container would not agree"
            % (document["total"], document["final_cue_end"]))
    return problems


# ---------------------------------------------------------------------
# Filesystem.  Every path taken from the environment or the command
# line is validated before it reaches open(), and nothing here uses a
# shell, so the new tooling adds no alert to the repository's CodeQL
# gate.  There is no network surface of any kind.
# ---------------------------------------------------------------------


def _module_dir() -> str:
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _playthrough_dir() -> str:
    """Return the absolute playthrough/ directory.

    Derived from this module's own location rather than from the
    working directory, exactly as manifest.py derives it, so a helper
    is correct even when it is invoked from somewhere else.
    """
    return os.path.dirname(_module_dir())


def _validated_path(value: Any, label: str) -> str:
    """Return `value` as an absolute file path, or raise.

    Every filesystem entry point in this module runs through here, so
    no unvalidated path is ever handed to open(): the value must be a
    non-empty string or os.PathLike, must not carry a NUL byte, and
    must not name a directory.
    """
    if value is None:
        raise TimelineError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise TimelineError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise TimelineError("%s must not be empty" % label)
    if "\x00" in value:
        raise TimelineError(
            "%s must not contain a NUL byte" % label)
    resolved = os.path.abspath(value)
    if os.path.isdir(resolved):
        raise TimelineError(
            "%s names a directory, not a file: %s" % (label, resolved))
    return resolved


def default_timeline_path() -> str:
    """Return the timeline this pipeline writes and reads.

    Honours PLAYTHROUGH_TIMELINE from playthrough/tooling/env.sh, which
    is the single definition of the artifact layout, and otherwise
    falls back to <repository>/playthrough/timeline.json derived from
    this module's location -- so the module is still correct when
    nothing has been sourced, as when it is imported by a test.
    """
    from_env = os.environ.get("PLAYTHROUGH_TIMELINE")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), "timeline.json")


def load_manifest_rows(
    manifest_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the manifest's rows, in file order.  Read-only.

    Delegates to manifest.read_rows(), which reports a malformed line
    by path and line number, and re-raises its complaint as a
    TimelineError so that a caller of this module has one exception
    type to catch.
    """
    try:
        return manifest.read_rows(manifest_path)
    except manifest.ManifestError as err:
        raise TimelineError(str(err)) from err


def encode_timeline(document: Dict[str, Any]) -> str:
    """Return the exact text playthrough/timeline.json holds.

    Two-space indentation, because the artifact is committed and a
    reviewer should be able to read a diff of it; keys in the order
    this module declares rather than sorted, so the shape of an entry
    matches the order it is documented in; non-ASCII written as itself,
    the convention the repository's own tooling follows; NaN and
    Infinity refused outright rather than emitted as the non-standard
    tokens Python would otherwise produce; and exactly one trailing
    newline.

    Nothing here varies from run to run -- no timestamp, no host name,
    no absolute path, no set iteration -- so recomputing the timeline
    from the same manifest produces a byte-identical file, which is
    what makes the committed artifact diffable and its regeneration
    checkable.
    """
    try:
        text = json.dumps(document, ensure_ascii=False, indent=2,
                          allow_nan=False, sort_keys=False)
    except ValueError as err:
        raise TimelineError(
            "the timeline is not representable as standard JSON: %s"
            % err) from err
    return text + "\n"


def write_timeline(
    timeline_path: Optional[str],
    document: Dict[str, Any],
    allow_index_gaps: bool = False,
) -> str:
    """Validate a timeline and write it.  Returns the path written.

    The document is verified before a byte is written, because a
    timeline that fails its own invariant must not reach the disk where
    the renderer and the caption generator would both trust it.
    newline="\\n" pins LF whatever the platform, which is what the
    committed artifact's `*.json text` attribute expects.
    """
    if timeline_path is None:
        timeline_path = default_timeline_path()
    path = _validated_path(timeline_path, "timeline path")
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise TimelineError(
            "the directory for the timeline does not exist: %s"
            % parent)
    problems = validate_timeline(document, allow_index_gaps)
    if problems:
        raise TimelineError(
            "refusing to write a timeline that fails its own checks: "
            "%s" % "; ".join(problems))
    text = encode_timeline(document)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def read_timeline(timeline_path: Optional[str] = None) -> Any:
    """Return the timeline document on disk.  Read-only."""
    if timeline_path is None:
        timeline_path = default_timeline_path()
    path = _validated_path(timeline_path, "timeline path")
    if not os.path.isfile(path):
        raise TimelineError("no timeline at %s" % path)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        return json.loads(text)
    except ValueError as err:
        raise TimelineError(
            "%s is not JSON: %s" % (path, err)) from err


def manifest_row_problems(
    rows: Sequence[Any],
    allow_index_gaps: bool = False,
) -> List[str]:
    """Report rows that are not a complete manifest row.  Pure.

    The strict shape gate build_timeline() deliberately does not
    apply: exactly the six declared fields, in the declared order, an
    integer index running 1..n, and text where text is required.  Run
    before writing, so a manifest that lost a field cannot become a
    timeline that quietly filled it in.
    """
    problems = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(
                "row %d is a %s, not an object"
                % (position, type(row).__name__))
            continue
        if list(row) != list(manifest.FIELDS):
            problems.append(
                "row %d carries keys %s; expected exactly %s in that "
                "order" % (position, list(row),
                           list(manifest.FIELDS)))
            continue
        index = row["frame"]
        if isinstance(index, bool) or not isinstance(index, int):
            problems.append(
                "row %d frame is not an integer: %r"
                % (position, index))
        elif index != position and not allow_index_gaps:
            problems.append(
                "row %d records frame %r; the indices run 1..n with "
                "no gap, no repeat and no reordering"
                % (position, index))
        for name in ("file", "action", "commentary"):
            if not isinstance(row[name], str) or not row[name].strip():
                problems.append(
                    "row %d %s is empty or not a string: %r"
                    % (position, name, row[name]))
        clock = row["ingame_clock"]
        if clock is not None and (not isinstance(clock, str) or
                                  not clock.strip()):
            # A clock that is neither a reading nor JSON null is a
            # malformed row, not an unreadable clock: reconciling it
            # would hide a defect that belongs in the open.
            problems.append(
                "row %d ingame_clock is neither a reading nor null: %r"
                % (position, clock))
    return problems


# ---------------------------------------------------------------------
# Command line.  A bare invocation does the pipeline's job -- read the
# manifest, compute the timeline, check it, write it -- so
# run_pipeline.sh needs no arguments to get the right behaviour, and
# every deviation from it has to be asked for explicitly.
# ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(
        prog="timeline.py",
        description=(
            "Compute playthrough/timeline.json from "
            "playthrough/manifest.jsonl.  Each frame is on screen for "
            "the in-game time its keystroke consumed, floored at "
            "%ss, capped at %ss, with %ss of video charged for the "
            "transition after a capped frame.  The result is the "
            "single source of truth the renderer and the caption "
            "generator both read." % (FLOOR, CEIL, TRANSITION)))
    parser.add_argument(
        "--manifest", default=None, metavar="PATH",
        help=("the manifest to read; defaults to PLAYTHROUGH_MANIFEST "
              "or <repository>/playthrough/manifest.jsonl"))
    parser.add_argument(
        "-o", "--output", default=None, metavar="PATH",
        help=("the timeline to write; defaults to "
              "PLAYTHROUGH_TIMELINE or "
              "<repository>/playthrough/timeline.json"))
    parser.add_argument(
        "--stdout", action="store_true",
        help=("print the timeline instead of writing it, leaving the "
              "committed artifact untouched"))
    parser.add_argument(
        "--verify", action="store_true",
        help=("check the timeline already on disk: it must pass every "
              "invariant AND be byte-identical to a fresh computation "
              "from the manifest, which is what proves it describes "
              "this session and no other"))
    parser.add_argument(
        "--allow-index-gaps", action="store_true",
        help=("proceed when the frame indices are not 1..n; the gap "
              "is still reported, because one keystroke makes exactly "
              "one frame and one row"))
    parser.add_argument(
        "--allow-empty", action="store_true",
        help="proceed when the manifest has no rows at all")
    parser.add_argument(
        "--ignore-manifest-problems", action="store_true",
        help=("compute a timeline even though the manifest failed its "
              "own schema check; every problem is still reported"))
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress the summary line on success")
    return parser


def _report(problems: Sequence[str]) -> None:
    """Print every problem on stderr, one per line."""
    for problem in problems:
        print("timeline.py: %s" % problem, file=sys.stderr)


def _summarise(document: Dict[str, Any], destination: str) -> str:
    """Return the one-line summary printed on success."""
    return ("timeline ok: %d frame(s), %d transition(s), %d "
            "reconciled clock(s), %s + %s = %s s -> %s"
            % (document["frame_count"], document["transition_count"],
               document["reconciled_count"],
               format(document["total_duration"], ".3f"),
               format(document["total_transition"], ".3f"),
               format(document["total"], ".3f"), destination))


def _load_rows(args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Read the manifest and gate it, or raise TimelineError.

    The gate is manifest_row_problems(), which works on the rows
    already in memory and covers everything a correct timeline
    depends on.  manifest.verify_manifest() additionally checks the
    file's byte shape -- LF endings, one trailing newline -- and is run
    by verify_artifacts.sh; reproducing it here would report every
    schema defect twice and read the file a second time to do it.
    """
    rows = load_manifest_rows(args.manifest)
    if not rows and not args.allow_empty:
        raise TimelineError(
            "the manifest has no rows; there is no session to pace.  "
            "Pass --allow-empty if an empty timeline really is what "
            "is wanted")
    problems = manifest_row_problems(rows, args.allow_index_gaps)
    if problems:
        _report(problems)
        if not args.ignore_manifest_problems:
            raise TimelineError(
                "%d problem(s) in the manifest; refusing to pace a "
                "film from it.  Pass --ignore-manifest-problems to "
                "compute a timeline anyway" % len(problems))
        _warn("computing a timeline from a manifest with %d reported "
              "problem(s), because --ignore-manifest-problems was "
              "given" % len(problems))
    return rows


def _warn_reconciliation(document: Dict[str, Any]) -> None:
    """Report reconciled clocks loudly: they changed the pacing.

    A reconciled reading is flagged in the artifact whether or not
    anybody reads the log, but a frame paced from a carried-forward
    clock is exactly the kind of thing an operator should be told
    about while the session is still fresh.
    """
    total = document["frame_count"]
    flagged = document["reconciled_count"]
    if not flagged:
        return
    if total and flagged == total:
        _warn("not one clock reading in this session could be parsed, "
              "so every frame falls to the %ss floor; the sidebar "
              "shows an exact time only while the survivor carries a "
              "watch (src/display.cpp:207-218)" % FLOOR)
        return
    _warn("%d of %d clock reading(s) were reconciled rather than read; "
          "every one is flagged in the timeline with its reason"
          % (flagged, total))


def _verify(args: argparse.Namespace) -> int:
    """Check the timeline on disk against the manifest.  Read-only."""
    destination = args.output or default_timeline_path()
    path = _validated_path(destination, "timeline path")
    stored = read_timeline(path)
    problems = validate_timeline(stored, args.allow_index_gaps)
    rows = load_manifest_rows(args.manifest)
    fresh = build_timeline(rows)
    if not problems:
        problems.extend(
            _drift_problems(stored, fresh, path, args.manifest))
    if problems:
        _report(problems)
        print("timeline.py: %d problem(s) found" % len(problems),
              file=sys.stderr)
        return 1
    if not args.quiet:
        print(_summarise(fresh, path))
    return 0


def _drift_problems(
    stored: Any,
    fresh: Dict[str, Any],
    path: str,
    manifest_path: Optional[str],
) -> List[str]:
    """Report a timeline that no longer matches its manifest.

    Byte comparison rather than a field-by-field one: the encoder is
    deterministic, so identical bytes are exactly the claim worth
    making -- this file was computed from this manifest by this code.
    """
    if encode_timeline(stored) == encode_timeline(fresh):
        return []
    where = manifest_path or manifest.default_manifest_path()
    problems = [
        "%s does not match a fresh computation from %s; regenerate it "
        "with `python3 playthrough/tooling/timeline.py`"
        % (path, where)]
    stored_frames = stored.get("frames") if isinstance(
        stored, dict) else None
    if isinstance(stored_frames, list) and len(
            stored_frames) != fresh["frame_count"]:
        problems.append(
            "the stored timeline has %d entr(ies) against %d row(s) "
            "in the manifest"
            % (len(stored_frames), fresh["frame_count"]))
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command line and return an exit status."""
    args = build_parser().parse_args(argv)
    try:
        if args.verify:
            return _verify(args)
        rows = _load_rows(args)
        document = build_timeline(rows)
        problems = validate_timeline(document, args.allow_index_gaps)
        if problems:
            _report(problems)
            print("timeline.py: %d problem(s) found" % len(problems),
                  file=sys.stderr)
            return 1
        if args.stdout:
            sys.stdout.write(encode_timeline(document))
            destination = "-"
        else:
            destination = write_timeline(
                args.output, document, args.allow_index_gaps)
        _warn_reconciliation(document)
        if not args.quiet and not args.stdout:
            print(_summarise(document, destination))
    except TimelineError as err:
        print("timeline.py: %s" % err, file=sys.stderr)
        return 1
    except OSError as err:
        print("timeline.py: %s" % err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
