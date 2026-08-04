#!/usr/bin/env python3
"""Turn playthrough/manifest.jsonl into playthrough/timeline.json.

This module owns every number the film is paced by and is the ONLY place
those numbers are computed.  playthrough/timeline.json is the single
source of truth: make_transitions.py, render_movie.py and make_srt.py
all read it rather than deriving durations of their own, which is what
makes cue drift arithmetically impossible rather than merely unlikely.

THE MODEL
    duration[i] = min(max(clock[i + 1] - clock[i], 0.25), 10.0)

The in-game clock is READ and DIFFERENCED.  Turns are not modelled,
moves are not modelled, and no conversion constant appears anywhere in
this file: differencing the sidebar clock is precisely how the
turns-to-seconds ambiguity is sidestepped rather than encoded.  The
0.25 s floor and the 10.0 s ceiling are the only two deviations from a
literal one-second-of-video-per-second-of-game-time mapping.

Zero-delta frames are load-bearing and are kept at the floor.  Menu
navigation and character creation consume no game time; those frames
fall to 0.25 s and are never merged, dropped or optimised away, because
one keystroke produced one capture and that relation has to survive into
the movie.

TRANSITIONS ARE CHARGED TO VIDEO TIME, NOT GAME TIME
A raw delta above the ceiling sets transition_after, and the cue cursor
advances by TRANSITION seconds after that frame's window and before the
next frame's window opens -- so the cue following a transition starts
that much later than the preceding window closed, and every cue after it
carries the same offset.  A raw delta of exactly 10.0 s is NOT a
transition: the comparison is strictly greater.

THE INVARIANT, asserted by validate_timeline() and carried in the
artifact so a reader can check it without running anything:

    sum(durations) + sum(transitions) == total == final cue end

WHY THE CLOCK PARSE IS RELIABLE
to_string_time_of_day (src/calendar.cpp:638-663) has three branches:
"military" gives "%02d%02d.%02d", "24h" gives "%02d:%02d:%02d", and the
12h default gives a variable-width AM/PM form.  Only the 24h branch is
fixed-width AND colon-delimited, which is why seed_options.py sets
24_HOUR=24h -- the shipped default is "12h"
(src/options.cpp:1868-1877).  "military" is fixed width too but
colon-free (0815.32), so CLOCK_RE rejects it just as firmly as the 12h
form.  Anything that does not match CLOCK_RE is refused, never guessed
at.

NEVER FABRICATE -- AND LEAVE AN AUDIT TRAIL
display::time_string (src/display.cpp:207-218) returns an exact clock
only when the survivor has a watch; otherwise one of the coarse phrases
from display::time_approx (src/display.cpp:159-186), or "???" when the
sky is not visible.  A reading that is absent, coarse, unknown, in
another format or moving backwards is RECONCILED against the last
trusted reading and FLAGGED -- never smoothed, interpolated or
invented.  Every such frame carries reconciled=true and a
reconciled_reason, so a reader can SEE which clocks were reconciled
instead of having to trust that none were.  The manifest keeps the
reading verbatim; this module keeps the audit trail.

THE DAY COMES FROM THE DATE LINE, THE TIME OF DAY FROM THE CLOCK
A clock alone cannot answer two questions this module has to answer.
Given 08:00:00 followed by 07:59:00 it cannot tell a crossing of
midnight from a misread going backwards -- both are consistent with
the pixels -- and given 08:00:00 followed by 08:00:00 it cannot tell a
frame that consumed no time from one that consumed a full day, because
the time of day came back the same.  Inferring a day counter from the
clock alone therefore invents a day in the first case and loses one in
the second.

So the sidebar DATE line is read as well.  capture.sh reports it per
frame and session.py records it in
playthrough/build/observations.jsonl -- the telemetry sidecar, NOT the
manifest, whose schema is exactly six fields and does not change -- and
this module uses it as the authority for the DAY while
the clock remains the authority for the time of day.  That is the
engine's own division: display::date_string (src/display.cpp:194-205)
renders the day and display::time_string (src/display.cpp:207-218)
renders the time within it.

Concretely, with date evidence in hand:
  * the clock going backwards while the date is unchanged is REFUSED
    as a misread, not inflated into a phantom day;
  * the clock going backwards while the date advanced is a confirmed
    crossing of midnight and yields a positive delta;
  * the clock NOT going backwards while the date advanced has the
    missing whole days ADDED, so a night's sleep of exactly 24 hours
    is 86400 seconds and not 0.
Without date evidence the older clock-only rule at MAX_WRAP_ADVANCE
still applies, but every decision made that way is recorded as
UNVERIFIED in the artifact rather than presented as established, and
--require-date turns the absence of evidence into a hard failure for a
run that must not accept one.

USE
    python3 playthrough/tooling/timeline.py
    python3 playthrough/tooling/timeline.py --stdout
    python3 playthrough/tooling/timeline.py --verify
    python3 playthrough/tooling/timeline.py --require-date

    import timeline
    doc = timeline.build_timeline(rows)
    cue = timeline.format_srt_timecode(doc["frames"][0]["cue_start"])
THE DAY COUNTER RUNS ON CAPTURED EVIDENCE, NOT ON INFERENCE
A clock that goes backwards is either a crossing of midnight or a
misread digit, and FROM THE CLOCK ALONE THE TWO ARE
INDISTINGUISHABLE: 08:00:00 followed by 06:00:00 is a 22-hour day if
you assume a rollover and a bad reading if you do not, and assuming the
rollover invents 22 hours of game time that nobody played -- which then
paces 22 hours of film and captions to match, undetectably, because the
artifact would be internally consistent.

So WHERE A DATE WAS CAPTURED the day advances only when the sidebar's
own date line (display::date_string, src/display.cpp:193-205) is
observed to have CHANGED across the pair.  That evidence is not a
manifest field -- the six-field schema is fixed, and a seventh would
create the second source of truth this pipeline exists to avoid -- so it
comes from the per-frame audit sidecar ocr_clock.py writes as it reads
each frame, playthrough/build/frame_dates.jsonl.  A captured date is
then the ONLY authority for the day counter and no arithmetic test
overrules it, because no bound on the implied advance is defensible
against real evidence.  A single sleep
keystroke asks the engine for up to a full day -- try_sleep_dur is
24_hours (src/handle_action.cpp:1464), narrowed to 3-9 h only when the
survivor sets an alarm -- so an evidenced crossing of midnight implying
23 h 59 m is ordinary play, not a misread.  A rollover's implied advance
is under a day by construction, which is exactly the range one keystroke
can produce.  A frame with NO date evidence is UNKNOWN, never
"unchanged": a missing record means nothing was observed, and treating
that as proof the day did not turn would be the same invention in the
other direction.  Such a frame falls to the bounded clock-only rule
above -- a wrap within MAX_WRAP_ADVANCE is believed, anything larger is
reconciled -- and the decision it produces is recorded as unverified,
never as confirmed.

USE
    python3 -B playthrough/tooling/timeline.py
    python3 -B playthrough/tooling/timeline.py --stdout
    python3 -B playthrough/tooling/timeline.py --verify

The mathematics is exposed as pure functions -- parse, absolutise,
delta, clamp, flag, cue walk, formatter -- separately from every
filesystem call, so test_timeline.py can assert all of it without
touching the disk.  format_srt_timecode lives here rather than in
make_srt.py so there is exactly one implementation of the timecode.

--verify ATTESTS, IT DOES NOT MERELY SELF-CHECK
Both command line paths read their rows through one gate --
manifest.row_problems(), the same canonical row validation a write
passes -- so the manifest is held to it BEFORE the stored artifact is
compared against a fresh computation from it.  Without that, a
timeline built from a manifest whose rows are malformed matches itself
byte for byte and would be reported as proof: the defect sits on both
sides of the comparison, so the comparison cannot see it.  The
byte-identity check answers "was this file computed from this
manifest"; the gate answers "is this manifest a record of a session at
all".  --verify has to answer both to mean anything.

Where the timeline may live is not negotiable, and how it lands is
not either.  Every path this module opens -- for reading as well as
for writing -- must resolve inside the playthrough/ directory derived
from this module's OWN location, with no symlinked component, and the
read is opened with O_NOFOLLOW; PLAYTHROUGH_TIMELINE and a -o argument
are honoured within that tree and refused outside it.  The write is
atomic: a private temporary file in the same directory is fsynced and
then os.replace()d over the artifact, so a reader sees the whole old
document or the whole new one, never half of one.  Both matter for the
same reason -- render_movie.py and make_srt.py consume THIS file and
must agree, so a redirected or truncated timeline would silently
desynchronise the movie from its captions.

Standard library only, plus the sibling manifest module: nothing here
needs playthrough/tooling/requirements.txt, so the timeline can be
recomputed and audited in any checkout.
"""

import argparse
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time

from dataclasses import dataclass
from typing import (Any, Dict, Iterable, List, Mapping, NamedTuple,
                    Optional, Sequence, Tuple)

# Set BEFORE the sibling import below, which is the only import here
# that can write into the repository working tree.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1, but this module is documented as runnable
# on its own, and a standalone `python3 playthrough/tooling/timeline.py`
# without that environment would compile the sibling to
# playthrough/tooling/__pycache__/ -- which .gitignore's terminal
# `!/playthrough/**` negation then makes COMMITTABLE.  A stray .pyc in a
# committed evidence tree is an artifact nobody authored.  The flag must
# precede the import it protects, because the interpreter consults it at
# compile time; every documented command also passes -B.
sys.dont_write_bytecode = True

try:
    # The six-field schema, the manifest reader, the row validators and
    # the clock classifier live in the sibling module; sharing them is
    # what keeps the coarse-phrase list from existing twice.
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

# There is deliberately NO plausibility bound on the advance an
# evidenced rollover implies, and the absence is the fix for a defect
# rather than an omission.
#
# The original rule was arithmetic alone: any backwards clock whose
# implied advance came in under 23 hours was accepted as a crossing of
# midnight, so 08:00:00 -> 06:00:00 (implying 22 hours) passed
# unreconciled and invented most of a day.  Date evidence replaced that
# rule -- see THE DAY COUNTER RUNS ON EVIDENCE in the module docstring
# -- but the 23-hour bound was kept on as a second opinion, justified by
# the claim that no single keystroke could advance the clock that far.
# That claim is false: `time_duration try_sleep_dur = 24_hours`
# (src/handle_action.cpp:1464) means one sleep keystroke asks for a full
# day, narrowed to 3-9 h only when the survivor sets an alarm.  So the
# bound could reject a real, date-evidenced night's sleep and
# reconcile away time that was genuinely played, which is the same
# category of lie in the other direction.
#
# Nor is any looser bound worth writing: a wrap computes
# SECONDS_PER_DAY - previous + current with current < previous, so its
# implied advance is already strictly under one day -- precisely the
# range one keystroke can produce.  A bound at a day would never fire.
# The day counter therefore rests on the captured date line alone, and
# RECONCILED_BACKWARDS survives as the defensive guard against a
# negative delta reaching the artifact (see absolutise_clocks).

# ---------------------------------------------------------------------
# THE SIDEBAR DATE LINE
#
# display::date_string (src/display.cpp:194-205) renders one of two
# forms, and both are parsed here:
#
#   "<Weekday>, <Month> <day>"  when the year is 364 days and
#                               SHOW_MONTHS is on, which is the default
#                               (src/options.cpp:1878-1880) and
#                               therefore the form in play;
#   "<Season>, day <N>"         otherwise.
#
# The month form is EXACTLY invertible to a day of the year, because
# month_and_day (src/calendar.cpp) is a pure function of it: the twelve
# months come in four groups of three, each group covering 91 days, and
# within a group the first month has 31 days and the other two have 30.
# Inverting it gives a day-of-year in 0..363, so two month-form
# readings yield an exact day count.
#
# The season form yields a day count only within one season, because
# season length is an option and the season order cannot be assumed
# from one reading; across a season boundary the day count is reported
# as UNKNOWN rather than guessed.  Two IDENTICAL readings of either
# form always mean zero days, which is the case that matters most --
# it is what refuses a backwards clock.
# ---------------------------------------------------------------------
DAYS_PER_YEAR = 364
DAYS_PER_MONTH_GROUP = 91

# How many whole days ONE keystroke may be believed to have advanced
# the calendar.  It is a plausibility bound on the DATE reading, the
# exact counterpart of MAX_WRAP_ADVANCE on the clock reading, and it is
# emphatically NOT a game-time conversion factor -- this module has
# none.
#
# It exists because a date line is OCR output like any other, and a
# single misread character turns evidence into a large lie in either
# direction: "Jan" read as "Jun" jumps five months forward, and a day
# number misread downward looks like a year wrap once the modulo has
# had it.  Neither is distinguishable from the truth by arithmetic, so
# a step beyond this bound is refused and flagged rather than believed.
#
# A week is as permissive as the bound can be while still catching that
# class.  Nothing legitimate is lost below it: the session is one
# continuous sitting that ends in sleep or death, its longest single
# action is a night's sleep or a long craft, and a genuine crossing of
# the new year advances the calendar by a day or two.
MAX_DATE_ADVANCE_DAYS = 7

# The most a crossing of midnight may imply when NOTHING evidences it.
# One hour: a genuine crossing observed between two adjacent keystrokes
# lands within minutes of midnight, so an hour is generous for the real
# case while refusing the phantom one -- an unevidenced 08:00:00 ->
# 06:00:00 would otherwise become twenty-two hours of game time that
# nobody observed, and the film would be paced to match.  With date
# evidence this bound does not apply at all: the date is then the
# authority, and one sleep keystroke can legitimately ask the engine for
# a whole day.
MAX_WRAP_ADVANCE = 3600
MONTHS_PER_GROUP = 3
LONG_MONTH_DAYS = 31
SHORT_MONTH_DAYS = 30

# src/calendar.cpp to_string( month ), in calendar order.  "Cataclysm"
# is the engine's own name for an unknown month and is accepted for
# completeness, but it carries no position in the year, so a reading
# naming it yields no ordinal.
MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
UNKNOWN_MONTH_NAME = "Cataclysm"

# src/weather.cpp to_string( const weekdays & ), in week order.  Used
# only as a cross-check: a day count and a weekday step must agree
# modulo seven, and a disagreement means one of the two was misread.
WEEKDAY_NAMES = (
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday",
)
DAYS_PER_WEEK = 7

# src/calendar.cpp name_season(), plus the eternal-season name.
SEASON_NAMES = ("Spring", "Summer", "Autumn", "Winter", "End times")

DATE_MONTH_RE = re.compile(
    r"^(%s), (%s|%s) ([0-9]{1,2})$"
    % ("|".join(WEEKDAY_NAMES), "|".join(MONTH_NAMES),
       UNKNOWN_MONTH_NAME))
DATE_SEASON_RE = re.compile(
    r"^(%s), day ([0-9]{1,3})$" % "|".join(SEASON_NAMES))

# What kind of date reading a frame carried.
DATE_MONTH = "month"
DATE_SEASON = "season"
DATE_ABSENT = "absent"
DATE_UNRECOGNISED = "unrecognised"

# How the day decision for a frame stands against the date evidence.
# These end up in the committed artifact, so they are part of its
# contract:
#
#   confirmed   the date agreed with what the clock implied
#   corrected   the date changed the day count the clock implied, and
#               the date won
#   unverified  no usable date evidence for this frame or its
#               predecessor, so the clock-only rule was applied
#   conflict    the date evidence could not be reconciled at all -- it
#               moved backwards, or it disagreed with itself -- and the
#               reading was refused rather than believed
#   none        the timeline was computed with no date evidence at all,
#               so there was nothing for any frame's day decision to be
#               checked against.  Distinct from "unverified", which
#               says evidence WAS consulted and did not cover this pair
AGREE_CONFIRMED = "confirmed"
AGREE_CORRECTED = "corrected"
AGREE_UNVERIFIED = "unverified"
AGREE_CONFLICT = "conflict"
AGREE_NONE = "none"

# The capture telemetry sidecar: env.sh's PLAYTHROUGH_OBSERVATIONS,
# with the same repository-relative location built from literals when
# nothing has been sourced.  It holds the per-frame date evidence and
# deliberately is NOT the manifest, whose schema is exactly six fields.
ENV_OBSERVATIONS = "PLAYTHROUGH_OBSERVATIONS"
OBSERVATIONS_REL_PARTS = ("build", "observations.jsonl")

# capture.sh's own account of whether it read the date line.  Only
# "read" is evidence; every other value means the line was not read and
# the field must not be treated as one.
DATE_STATUS_READ = "read"

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
# Emitted by the defensive guard in absolutise_clocks alone -- the last
# stop before a negative delta could reach the artifact.  The two named
# backwards cases below are decided from date evidence and carry their
# own reasons, so a reader seeing this code is looking at a reading no
# earlier branch accounted for.
RECONCILED_BACKWARDS = "clock-not-monotonic"
# A backwards clock WITH date evidence proving the date did not change:
# the day demonstrably did not turn, so the reading is a misread.
RECONCILED_SAME_DAY = "clock-backwards-same-date"
# A backwards clock with NO date evidence either way.  Distinguished
# from the case above because the two call for different remedies: this
# one means the evidence is missing (an inline-reader frame, or a
# sidecar that was never written), and the fix is to recapture with the
# date audit enabled rather than to distrust the clock.
RECONCILED_NO_DATE_EVIDENCE = "clock-rollover-unevidenced"

# A backwards reading that the DATE line positively contradicts.  It is
# a distinct code from the plain non-monotonic case because the two are
# distinguishable evidence: this one is a misread the date proved,
# rather than one the rollover bound merely made implausible.
RECONCILED_DATE_CONTRADICTS = "clock-contradicted-by-date"

# A DATE line that moved backwards, or forwards by more days than one
# keystroke can plausibly have produced (MAX_DATE_ADVANCE_DAYS).  The
# date evidence is what failed here, not the clock, so it carries its
# own code: a reader can tell a misread calendar from a misread clock
# without re-deriving either.
RECONCILED_DATE_IMPLAUSIBLE = "date-implausible-advance"

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
    # The date evidence for this frame and how the day decision stands
    # against it.  They travel with the entry so that a reader can
    # audit the rollover and day-count decisions from the artifact
    # alone, without re-reading the sidecar or the frames.
    "ingame_date",
    "date_kind",
    "date_agreement",
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
    # WHAT THIS TIMELINE WAS COMPUTED FROM, so the claim can be checked
    # against the evidence rather than believed.  See
    # MANIFEST_ATTESTATION_FIELDS and manifest_attestation_problems().
    "manifest",
    "floor",
    "ceil",
    "transition",
    "frame_count",
    "transition_count",
    "reconciled_count",
    # How many frames' day decisions the date line established, and how
    # many were inferred from the clock alone or could not be
    # reconciled.  A reader who wants to know whether the pacing rests
    # on evidence can read it off the document header.
    "date_confirmed_count",
    "date_corrected_count",
    "date_unverified_count",
    "date_conflict_count",
    "total_duration",
    "total_transition",
    "total",
    "final_cue_end",
    "frames",
)


# ---------------------------------------------------------------------
# The manifest attestation
#
# WHY A TIMELINE MUST NAME ITS SOURCE.  This document is the single
# source of truth for the movie's pacing AND for the caption timings,
# and three separate producers read it -- make_transitions.py,
# render_movie.py and make_srt.py.  None of them reads the manifest.
# So without provenance recorded IN the document, a timeline computed
# from one session's evidence can pace another session's frames, and
# every internal invariant still holds: the totals agree with the
# entries, the cue windows are contiguous, and nothing anywhere is
# able to notice.
#
# The attestation closes that off.  It records the manifest's
# repository-relative path, the sha256 of its exact bytes, and its row
# count, so a producer can prove -- not assume -- that the timeline in
# its hand describes the evidence on this disk.  A stale timeline left
# beside a re-recorded manifest is then a hard refusal instead of a
# silently mispaced film.
#
# The path is stored RELATIVE so the artifact stays reproducible across
# checkouts and leaks no filesystem layout into a committed file.
# ---------------------------------------------------------------------

MANIFEST_ATTESTATION_FIELDS = ("path", "sha256", "rows")

# 64 lowercase hex digits.  Pinned as a shape so a truncated, uppercase
# or algorithm-swapped digest is a reported problem rather than a
# comparison that silently never matches.
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# Read in blocks: the manifest of a long session is large, and hashing
# it must not depend on holding all of it in memory.
DIGEST_BLOCK = 65536


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
    description of it.

    `date` is the sidebar date line for this frame, exactly as
    capture.sh recorded it in the telemetry sidecar, `date_kind`
    describes it, and `date_agreement` says how the day decision for
    this frame stands against that evidence -- confirmed, corrected,
    unverified, conflict, or none when the session carried no date
    evidence at all.  Carrying all three means a reader can see which
    days were established and which were inferred, instead of having
    to trust that they all were.

    Frozen because a reading is evidence.
    """

    seconds: int
    reconciled: bool
    reason: Optional[str]
    kind: str
    text: Optional[str]
    date: Optional[str] = None
    date_kind: str = DATE_ABSENT
    date_agreement: str = AGREE_NONE


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


def month_ordinal(month: str, day_of_month: int) -> Optional[int]:
    """Return the zero-based day of the year for a month-form date.

    The inverse of ``month_and_day`` (src/calendar.cpp), which is a
    pure function: the twelve months fall into four groups of three
    covering 91 days each, and within a group the first month has 31
    days and the other two have 30.  So the group contributes
    ``group * 91`` and the position within it contributes 0, 31 or 61
    plus the day.

    Returns None for the engine's ``Cataclysm`` placeholder month,
    which names no position in the year, and for a day outside the
    month it claims -- both are readings that cannot be turned into an
    ordinal, and inventing one would be exactly the fabrication this
    module refuses.
    """
    if month not in MONTH_NAMES:
        return None
    if not isinstance(day_of_month, int) or isinstance(
            day_of_month, bool):
        return None
    index = MONTH_NAMES.index(month)
    group, position = divmod(index, MONTHS_PER_GROUP)
    if position == 0:
        length, offset = LONG_MONTH_DAYS, 0
    elif position == 1:
        length, offset = SHORT_MONTH_DAYS, LONG_MONTH_DAYS
    else:
        length = SHORT_MONTH_DAYS
        offset = LONG_MONTH_DAYS + SHORT_MONTH_DAYS
    if day_of_month < 1 or day_of_month > length:
        return None
    return (group * DAYS_PER_MONTH_GROUP + offset +
            day_of_month - 1)


@dataclass(frozen=True)
class DateReading:
    """One frame's sidebar date line, parsed but never repaired.

    `text` is the reading exactly as capture.sh recorded it.  `kind`
    is one of DATE_MONTH, DATE_SEASON, DATE_ABSENT or
    DATE_UNRECOGNISED.  `ordinal` is the zero-based day of the year
    when the month form made one derivable; `season` and
    `day_of_season` carry the season form; `weekday` is the weekday
    name when one was read, used only to cross-check a day count
    modulo seven.  Frozen because a reading is evidence.
    """

    text: Optional[str]
    kind: str
    ordinal: Optional[int] = None
    season: Optional[str] = None
    day_of_season: Optional[int] = None
    weekday: Optional[str] = None

    @property
    def usable(self) -> bool:
        """True when this reading can take part in a day comparison."""
        return self.kind in (DATE_MONTH, DATE_SEASON)


def parse_date_line(value: Any) -> DateReading:
    """Parse one sidebar date line into a :class:`DateReading`.

    Accepts exactly the two forms display::date_string can render
    (src/display.cpp:194-205) and nothing else.  Anything absent is
    DATE_ABSENT and anything else is DATE_UNRECOGNISED -- neither is
    repaired, and neither is allowed to influence a day count.
    """
    if value is None:
        return DateReading(text=None, kind=DATE_ABSENT)
    if not isinstance(value, str):
        return DateReading(text=None, kind=DATE_UNRECOGNISED)
    text = value.strip()
    if not text:
        return DateReading(text=None, kind=DATE_ABSENT)

    match = DATE_MONTH_RE.match(text)
    if match is not None:
        weekday, month, day_text = match.groups()
        return DateReading(
            text=text,
            kind=DATE_MONTH,
            ordinal=month_ordinal(month, int(day_text)),
            weekday=weekday)

    match = DATE_SEASON_RE.match(text)
    if match is not None:
        season, day_text = match.groups()
        return DateReading(
            text=text,
            kind=DATE_SEASON,
            season=season,
            day_of_season=int(day_text))

    return DateReading(text=text, kind=DATE_UNRECOGNISED)


def date_day_delta(
    previous: DateReading,
    current: DateReading,
) -> Optional[int]:
    """Return how many whole days passed between two date readings.

    None means the question cannot be answered honestly from these two
    readings, in which case the caller falls back to the clock-only
    rollover rule and records the decision as unverified.

    The cases, in the order they are decided:

    * identical text -- zero days, whatever the form.  This is the
      case that refuses a backwards clock, and it needs no ordinal
      arithmetic at all, so it works for the season form too;
    * two month-form readings with ordinals -- the difference, with a
      NEGATIVE difference re-read as a crossing of the new year only
      when the day count that implies is plausible for one keystroke
      (see MAX_DATE_ADVANCE_DAYS).  Without that bound the modulo would
      silently turn an obviously backwards date into a 360-day leap
      forward, which is a much bigger lie than the one it was meant to
      avoid;
    * two season-form readings within the SAME season -- the
      difference of their day numbers;
    * anything else -- None, because season length is an option and the
      order of seasons cannot be recovered from a single reading.

    A NEGATIVE result is returned as such: it means the date itself
    went backwards, and the caller treats that as a conflict and
    refuses the reading rather than silently accepting it.
    """
    if not previous.usable or not current.usable:
        return None
    if (previous.text is not None and
            previous.text == current.text):
        return 0
    if (previous.kind == DATE_MONTH and current.kind == DATE_MONTH and
            previous.ordinal is not None and
            current.ordinal is not None):
        step = current.ordinal - previous.ordinal
        if step < 0:
            wrapped = step + DAYS_PER_YEAR
            if wrapped <= MAX_DATE_ADVANCE_DAYS:
                return wrapped
        return step
    if (previous.kind == DATE_SEASON and
            current.kind == DATE_SEASON and
            previous.season == current.season and
            previous.day_of_season is not None and
            current.day_of_season is not None):
        return current.day_of_season - previous.day_of_season
    return None


def weekday_disagreement(
    previous: DateReading,
    current: DateReading,
    days: int,
) -> Optional[str]:
    """Report a weekday that contradicts a day count, or None.

    Weekdays advance one per day (src/calendar.cpp day_of_week), so a
    day count and a weekday step must agree modulo seven.  When they
    do not, one of the two lines was misread; that is worth saying out
    loud, and it is deliberately NOT used to override the day count,
    because a weekday alone cannot say by how much it is wrong.
    """
    if previous.weekday is None or current.weekday is None:
        return None
    if (previous.weekday not in WEEKDAY_NAMES or
            current.weekday not in WEEKDAY_NAMES):
        return None
    expected = (WEEKDAY_NAMES.index(previous.weekday) +
                days) % DAYS_PER_WEEK
    actual = WEEKDAY_NAMES.index(current.weekday)
    if expected == actual:
        return None
    return ("the date line went from %r to %r, a step of %d day(s), "
            "but %s is not %d day(s) after %s; one of the two lines "
            "was misread and the day count is reported as it was read"
            % (previous.text, current.text, days, current.weekday,
               days, previous.weekday))


def normalise_date(value: Any) -> Optional[str]:
    """Return a date line reduced to a comparable form, or None.

    Only ever used to answer "is this the same date as that one", never
    to work out WHICH date it is: the engine renders two different forms
    (`<Weekday>, <Month> <day>` and `<Season>, day N`, chosen by
    SHOW_MONTHS, src/display.cpp:193-205) and parsing either into a
    calendar would be inventing structure this module does not need.
    Case and internal whitespace are flattened so that an OCR pass which
    read "Spring,  day 3" and one which read "Spring, day 3" are not
    mistaken for two different days.
    """
    if not isinstance(value, str):
        return None
    flattened = " ".join(value.split()).strip().lower()
    return flattened or None


def _date_verdict(
    date_here: Optional[str],
    date_previous: Optional[str],
) -> Optional[bool]:
    """Did the day turn between these two frames?

    True when both dates were observed and they differ, False when both
    were observed and they agree, and None when either is missing --
    which is UNKNOWN, not "unchanged".  Keeping the third answer
    distinct is the whole point: a frame with no record proves nothing,
    and collapsing it into False would silently claim the day did not
    turn on exactly the frames where nobody looked.
    """
    here = normalise_date(date_here)
    previous = normalise_date(date_previous)
    if here is None or previous is None:
        return None
    return here != previous


def _next_absolute(
    time_of_day: int,
    day: int,
    previous_time_of_day: Optional[int],
    previous_absolute: Optional[int],
    turned: Optional[bool] = None,
) -> Tuple[int, int, bool, Optional[str]]:
    """Absolutise one parsed reading against the session so far.

    Returns the absolute value, the day counter to carry forward,
    whether the reading was trusted, and -- when it was not -- the
    reason.  The cases, in the order they are decided:

    * no trusted reading yet -- this one anchors the session at day 0;
    * the clock did not go backwards -- same day, straightforward;
    * the clock went backwards AND `turned` is True -- the sidebar's
      date line was observed to change across this pair, so the day
      counter increments and the delta comes out POSITIVE.  The implied
      advance is NOT second-guessed: a wrap implies less than a day by
      construction, and one sleep keystroke asks the engine for a whole
      day (src/handle_action.cpp:1464), so even 23 h 59 m is play rather
      than a misread;
    * the clock went backwards and `turned` is False -- the date was
      observed NOT to change, so the day did not turn and the reading is
      a misread;
    * the clock went backwards and `turned` is None -- no date evidence
      either way, so the SIZE of what the wrap implies is all there is
      to go on, and MAX_WRAP_ADVANCE is the line: a crossing observed
      between two adjacent keystrokes lands within seconds of midnight
      and is believed, while a "crossing" implying most of a day from
      one keystroke is reconciled rather than inflated into a day that
      may never have passed.  A bound is a weaker instrument than the
      date -- a genuinely long sleep across midnight falls the wrong
      side of it -- which is exactly why the capture writes the date
      for every frame and why the evidenced path above does not
      consult it.

    In the last two cases, and in the bounded half of the third, the
    previous absolute is carried forward and the reading is flagged, so
    a single bad frame cannot corrupt the delta of the frame after it.
    """
    if previous_time_of_day is None:
        return day * SECONDS_PER_DAY + time_of_day, day, True, None
    if time_of_day >= previous_time_of_day:
        return day * SECONDS_PER_DAY + time_of_day, day, True, None
    anchor = 0 if previous_absolute is None else previous_absolute
    if turned is None:
        # No date either way.  A wrap is BELIEVED only when what it
        # implies is small enough to be a crossing rather than a
        # phantom: 23:59:58 -> 00:00:04 implies six seconds and is
        # overwhelmingly a real crossing, while 08:00:00 -> 06:00:00
        # implies twenty-two hours of game time from one keystroke, and
        # nothing here can tell that from a misread digit.  The bound is
        # what separates the two; above it the reading is reconciled and
        # flagged rather than inflated into a day that may never have
        # passed.
        implied = SECONDS_PER_DAY - previous_time_of_day + time_of_day
        if implied > MAX_WRAP_ADVANCE:
            return anchor, day, False, RECONCILED_NO_DATE_EVIDENCE
        return ((day + 1) * SECONDS_PER_DAY + time_of_day, day + 1,
                True, None)
    if not turned:
        return anchor, day, False, RECONCILED_SAME_DAY
    return ((day + 1) * SECONDS_PER_DAY + time_of_day, day + 1, True,
            None)


def absolutise_clocks(
    readings: Sequence[Any],
    dates: Optional[Sequence[Any]] = None,
) -> List[ClockReading]:
    """Absolutise a session's readings, monotonic forward only.

    Walks the readings once, carrying a day counter, so that
    23:59:58 -> 00:00:04 yields a POSITIVE six-second step rather than
    a negative one.  A reading that cannot be parsed, or that would
    move time backwards without being explicable as a crossing of
    midnight, is reconciled against the last trusted reading and
    flagged; the day counter and the trusted time of day stay anchored
    to that last good reading, so a single misread frame cannot corrupt
    the delta of the frame after it.

    THE DAY COUNTER PREFERS EVIDENCE OVER INFERENCE.  When `dates`
    supplies the sidebar date line for the frames -- capture.sh reports
    it and session.py records it in the telemetry sidecar -- the number
    of whole days between two frames is taken from the DATE, and the
    clock supplies only the time within that day.  Three things follow,
    and each one fixes a defect the clock alone cannot avoid:

    * a clock that went backwards while the date did not change is a
      MISREAD, refused and flagged clock-contradicted-by-date, instead
      of being inflated into a day that never passed;
    * a clock that went backwards while the date advanced is a
      CONFIRMED crossing of midnight;
    * a clock that did NOT go backwards while the date advanced has the
      missing whole days ADDED, so an action spanning 24 hours is
      86400 seconds rather than the 0 the time of day implies.

    `dates` is a sequence of date lines parallel to `readings`, each
    the verbatim reading for that frame or None where none was
    observed; ocr_clock.py records them per frame and
    date_lines_for_rows() lines them up.  A sequence SHORTER than
    `readings` reads as None for the frames it does not reach -- a
    session whose date evidence stops partway is a real case.  A LONGER
    one is REFUSED with TimelineError rather than truncated: a surplus
    means the evidence was lined up against some other frame list, so
    the entries that do get used may belong to different frames
    entirely, and the timeline built from them would look perfectly
    plausible.

    WHERE NO USABLE DATE EVIDENCE EXISTS for a pair of frames the
    clock-only rule applies, and that rule is BOUNDED rather than
    absolute: a wrap is believed only where what it implies is small
    enough to be a crossing rather than a phantom day.  23:59:58 ->
    00:00:04 implies six seconds and is believed; 08:00:00 -> 06:00:00
    implies twenty-two hours of game time from a single keystroke,
    which nothing here can tell apart from a misread digit, so it is
    reconciled against the last trusted reading and flagged instead.
    MAX_WRAP_ADVANCE is that bound.  Believed or reconciled, the
    decision is recorded as UNVERIFIED wherever date evidence was
    supplied but none was usable for that pair, and as NONE where the
    caller passed no dates at all, so the artifact distinguishes a day
    that was established from one that was merely inferred, and both
    from a run that had no date evidence to consult -- and a bound is a
    weaker instrument than the date, since
    a genuinely long sleep across midnight falls the wrong side of it,
    which is why the capture reads the date for every frame and why the
    evidenced path above never consults it.

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
    values = list(readings)
    date_values = list(dates) if dates is not None else []
    if len(date_values) > len(values):
        raise TimelineError(
            "%d date lines were supplied for %d readings; `dates` is "
            "parallel to `readings`, so a longer sequence means the "
            "evidence was assembled against a different frame list.  "
            "Ignoring the surplus would silently pair frames with "
            "other frames' dates and still return a plausible "
            "timeline." % (len(date_values), len(values)))
    day = 0
    previous_time_of_day: Optional[int] = None
    previous_absolute: Optional[int] = None
    previous_date: Optional[DateReading] = None
    out: List[ClockReading] = []
    for position, value in enumerate(values):
        raw_date = (date_values[position]
                    if position < len(date_values) else None)
        date = parse_date_line(raw_date)
        kind = clock_kind(value)
        time_of_day = parse_time_of_day(value)
        agreement = AGREE_NONE
        note = None
        if time_of_day is None:
            trusted = False
            seconds = (0 if previous_absolute is None
                       else previous_absolute)
            reason = _REASON_BY_KIND.get(kind, RECONCILED_UNPARSEABLE)
            if dates is not None:
                agreement = AGREE_UNVERIFIED
        else:
            (seconds, day, trusted, agreement,
             reason, note) = _absolutise_one(
                time_of_day=time_of_day,
                day=day,
                previous_time_of_day=previous_time_of_day,
                previous_absolute=previous_absolute,
                previous_date=previous_date,
                date=date,
                have_dates=dates is not None,
                position=position)
        if previous_absolute is not None and seconds < previous_absolute:
            # Unreachable through the branches above; kept because a
            # negative delta would be a silent lie about game time,
            # and this is the one place it can be made impossible.
            seconds = previous_absolute
            trusted = False
            reason = RECONCILED_BACKWARDS
            agreement = AGREE_CONFLICT
        if note is not None:
            _warn(note)
        if trusted:
            previous_time_of_day = time_of_day
        if date.usable and trusted:
            previous_date = date
        elif previous_date is None and date.usable:
            previous_date = date
        previous_absolute = seconds
        out.append(ClockReading(
            seconds=seconds, reconciled=not trusted, reason=reason,
            kind=kind, text=value if isinstance(value, str) else None,
            date=date.text, date_kind=date.kind,
            date_agreement=agreement))
    return _anchor_leading_readings(out)


def _absolutise_one(
    time_of_day: int,
    day: int,
    previous_time_of_day: Optional[int],
    previous_absolute: Optional[int],
    previous_date: Optional[DateReading],
    date: DateReading,
    have_dates: bool,
    position: int,
) -> Tuple[int, int, bool, str, Optional[str], Optional[str]]:
    """Absolutise one parsed clock against the session and the date.

    Returns ``(absolute, day, trusted, agreement, reason, note)``.
    The date decides the DAY; the clock decides the time within it.
    Every branch that departs from what the clock alone would have
    concluded says so, either in the returned agreement or in the note
    the caller warns with.
    """
    # The clock-only answer, from the one function that owns that rule.
    # It never advances the day without observed date evidence, so its
    # reason -- clock-rollover-unevidenced when nothing could say
    # whether the day turned, clock-backwards-same-date when the date
    # said it did not -- is carried through verbatim rather than being
    # flattened into a generic "not monotonic".
    #
    # `turned` is the coarse verdict -- did the observed date line
    # change across this pair, yes, no, or nobody looked -- so the
    # baseline is already date-informed even where the two readings
    # cannot be turned into a day COUNT (an unrecognised form, or two
    # season-form lines from different seasons).  The exact count, when
    # one is derivable, is applied by the branches below.
    (clock_only, clock_only_day, clock_only_trusted,
     clock_only_reason) = _next_absolute(
        time_of_day, day, previous_time_of_day, previous_absolute,
        _date_verdict(
            date.text,
            previous_date.text if previous_date is not None else None)
        if have_dates else None)

    if not have_dates:
        return (clock_only, clock_only_day, clock_only_trusted,
                AGREE_NONE, clock_only_reason, None)

    if previous_time_of_day is None:
        # The session's first trusted reading anchors day 0; there is
        # nothing before it to compare a date against.
        agreement = (AGREE_CONFIRMED if date.usable
                     else AGREE_UNVERIFIED)
        return (clock_only, clock_only_day, clock_only_trusted,
                agreement, clock_only_reason, None)

    days = (date_day_delta(previous_date, date)
            if previous_date is not None else None)
    if days is None:
        # No usable date evidence for THIS PAIR: the clock-only rule
        # stands -- which believes a wrap only within MAX_WRAP_ADVANCE
        # and reconciles anything larger -- and the artifact records
        # that the decision was not verified against a date.
        return (clock_only, clock_only_day, clock_only_trusted,
                AGREE_UNVERIFIED, clock_only_reason, None)

    note = weekday_disagreement(previous_date, date, days)

    if days < 0:
        # The date itself went backwards.  Nothing here can be
        # believed, so the reading is refused rather than reconciled
        # into a plausible number.
        anchor = 0 if previous_absolute is None else previous_absolute
        return (anchor, day, False, AGREE_CONFLICT,
                RECONCILED_DATE_IMPLAUSIBLE,
                "frame %d reports the date going backwards, from %r to "
                "%r; the reading is refused rather than believed"
                % (position + 1, previous_date.text, date.text))

    if days > MAX_DATE_ADVANCE_DAYS:
        # More whole days than one keystroke can have produced, so one
        # of the two date lines was misread -- a month misread jumps
        # months, and a day number misread downward reappears here as a
        # near-year leap once the new-year reading has been ruled out.
        # Refused for the same reason as a backwards date: an advance
        # this large is indistinguishable from the truth by arithmetic
        # and must not be manufactured.
        anchor = 0 if previous_absolute is None else previous_absolute
        return (anchor, day, False, AGREE_CONFLICT,
                RECONCILED_DATE_IMPLAUSIBLE,
                "frame %d reports the date advancing %d day(s), from %r "
                "to %r, which exceeds the %d day(s) one keystroke can "
                "plausibly produce; the reading is refused rather than "
                "believed"
                % (position + 1, days, previous_date.text, date.text,
                   MAX_DATE_ADVANCE_DAYS))

    if days == 0 and time_of_day < previous_time_of_day:
        # THE DEFECT THIS EXISTS FOR.  A clock-only reading would have
        # called this a crossing of midnight and manufactured a day.
        # The date says the day did not change, so it is a misread.
        anchor = 0 if previous_absolute is None else previous_absolute
        return (anchor, day, False, AGREE_CONFLICT,
                RECONCILED_SAME_DAY,
                "frame %d reads %02d:%02d:%02d after %02d:%02d:%02d "
                "while the date line stayed %r, so the clock did NOT "
                "cross midnight; the reading is refused instead of "
                "being inflated into a day that did not pass"
                % (position + 1,
                   time_of_day // SECONDS_PER_HOUR,
                   (time_of_day % SECONDS_PER_HOUR) //
                   SECONDS_PER_MINUTE,
                   time_of_day % SECONDS_PER_MINUTE,
                   previous_time_of_day // SECONDS_PER_HOUR,
                   (previous_time_of_day % SECONDS_PER_HOUR) //
                   SECONDS_PER_MINUTE,
                   previous_time_of_day % SECONDS_PER_MINUTE,
                   date.text))

    # The date is the authority for the day.  Rebuild the absolute
    # reading from it rather than from the clock's inference.
    resolved_day = day + days
    absolute = resolved_day * SECONDS_PER_DAY + time_of_day
    if previous_absolute is not None and absolute < previous_absolute:
        # Two readings whose date and time cannot both be true.
        return (previous_absolute, day, False, AGREE_CONFLICT,
                RECONCILED_DATE_CONTRADICTS,
                "frame %d places game time before frame %d even with "
                "the date line taken as authoritative (%r); the "
                "reading is refused"
                % (position + 1, position, date.text))

    agreement = (AGREE_CONFIRMED if absolute == clock_only
                 else AGREE_CORRECTED)
    if agreement == AGREE_CORRECTED and note is None:
        note = (
            "frame %d advances %d day(s) by the sidebar date line, "
            "placing it %+d second(s) from where the clock alone would "
            "have put it; the date is authoritative for the day"
            % (position + 1, days, absolute - clock_only))
    return absolute, resolved_day, True, agreement, None, note


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
            text=readings[index].text,
            date=readings[index].date,
            date_kind=readings[index].date_kind,
            date_agreement=readings[index].date_agreement)
    return adjusted


# ---------------------------------------------------------------------
# The per-frame date evidence.
#
# ocr_clock.py appends one record per frame to
# $PLAYTHROUGH_DATE_AUDIT (playthrough/build/frame_dates.jsonl) as it
# reads that frame, in the shape its DATE_AUDIT_FIELDS declares:
#
#     {"frame": 42, "file": "playthrough/frames/frame_00042.png",
#      "clock": "08:15:32", "phrase": null,
#      "date": "Spring, day 3", "agreement": true}
#
# READ WITH THE STANDARD LIBRARY, NOT BY IMPORTING ocr_clock: that
# module imports Pillow and pytesseract at module scope, and importing
# it here would make the OCR stack a hard dependency of computing a
# timeline -- so a checkout could no longer recompute or audit the
# artifact without the capture toolchain installed.  The field names
# below are therefore the contract between the two modules, and
# test_timeline.py asserts the round trip against a sidecar that
# ocr_clock.py's own writer produced, so the two cannot drift apart
# unnoticed.
# ---------------------------------------------------------------------

AUDIT_FRAME_FIELD = "frame"
AUDIT_DATE_FIELD = "date"
ENV_DATE_AUDIT = "PLAYTHROUGH_DATE_AUDIT"


def default_date_audit_path(root: Optional[str] = None) -> str:
    """Absolute path of the date-evidence sidecar.

    A nominated `root` outranks $PLAYTHROUGH_DATE_AUDIT because the
    nomination is the containment boundary this path is then held to, so
    an ambient export pointing outside it could only be refused.  With no
    nomination the export wins (env.sh is the single definition of the
    artifact layout); with neither, the path comes from this file's own
    location.  read_date_audit() takes an explicit path, which outranks
    every default here.
    """
    if root is not None:
        return os.path.join(approved_root(root), "frame_dates.jsonl")
    from_env = os.environ.get(ENV_DATE_AUDIT)
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), "build",
                        "frame_dates.jsonl")


def read_date_audit(
    audit_path: Optional[str] = None,
    root: Optional[str] = None,
) -> Dict[int, Optional[str]]:
    """Return {frame index: date line} from the sidecar.  Read-only.

    An ABSENT sidecar yields an empty mapping rather than an error: a
    session captured before the audit existed, or one whose clock reads
    all came from the inline last-resort reader, legitimately has none.
    Every frame's date is then UNKNOWN, a backwards clock is believed
    only within the MAX_WRAP_ADVANCE bound and reconciled beyond it,
    and nothing is invented -- which is the correct outcome, not a
    silent downgrade.

    THE LAST RECORD FOR AN INDEX WINS.  A recapture appends a second
    record for the same frame, and the last one describes the frame that
    is actually on disk now.  Two records that DISAGREE about the date
    are reported and the date is treated as unobserved, because a
    contradiction is not evidence.

    A malformed line is reported and skipped rather than raising: this
    is corroborating evidence, and losing one frame's worth of it
    degrades a rollover to "unevidenced" instead of stopping the
    pipeline.  A malformed sidecar cannot make the timeline WRONG -- it
    can only leave it unable to justify advancing a day.
    """
    resolved = _validated_evidence_path(
        default_date_audit_path(root) if audit_path is None
        else audit_path,
        "date audit path", root)
    dates: Dict[int, Optional[str]] = {}
    if not os.path.isfile(resolved):
        return dates
    conflicting: List[int] = []
    with _open_evidence(resolved, "date audit") as handle:
        for number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except ValueError as err:
                _warn("%s line %d is not JSON (%s); that frame's date "
                      "is treated as unobserved"
                      % (resolved, number, err))
                continue
            if not isinstance(record, dict):
                _warn("%s line %d is a %s, not an object; that "
                      "frame's date is treated as unobserved"
                      % (resolved, number, type(record).__name__))
                continue
            index = record.get(AUDIT_FRAME_FIELD)
            if isinstance(index, bool) or not isinstance(index, int):
                _warn("%s line %d records %r as its frame index; the "
                      "record is skipped"
                      % (resolved, number, index))
                continue
            value = record.get(AUDIT_DATE_FIELD)
            if value is not None and not isinstance(value, str):
                _warn("%s line %d records %r as its date; the record "
                      "is skipped" % (resolved, number, value))
                continue
            if index in dates and dates[index] is not None and \
                    value is not None and \
                    normalise_date(value) != normalise_date(
                        dates[index]):
                conflicting.append(index)
            dates[index] = value
    for index in sorted(set(conflicting)):
        _warn("the date audit records two different dates for frame "
              "%d; the later record is used, but a contradiction is "
              "not evidence, so verify the recapture" % index)
    return dates


def date_lines_for_rows(
    rows: Sequence[Any],
    dates: Optional[Dict[int, Optional[str]]] = None,
    audit_path: Optional[str] = None,
    root: Optional[str] = None,
) -> List[Optional[str]]:
    """Line the date evidence up with the manifest rows.  Pure.

    KEYED OFF THE ROWS, never off the sidecar: the manifest is the
    session's evidence and the sidecar only corroborates it, so a record
    for a frame that no row mentions is ignored.  That case is real
    rather than hypothetical -- a frame withdrawn by capture.sh after
    its audit record was already written leaves exactly such an orphan
    record behind, and its date must not be attributed to whatever
    frame later took that index.  The returned list is always the same
    length as `rows`, with None wherever nothing was observed.
    """
    resolved = (read_date_audit(audit_path, root) if dates is None
                else dates)
    out: List[Optional[str]] = []
    for position, row in enumerate(rows, start=1):
        index = position
        if isinstance(row, dict):
            candidate = row.get("frame")
            if not isinstance(candidate, bool) and \
                    isinstance(candidate, int):
                index = candidate
        out.append(resolved.get(index))
    return out


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
        # The date line verbatim, or JSON null when the frame carried
        # none.  Never derived from the clock, never carried forward.
        "ingame_date": reading.date,
        "date_kind": reading.date_kind,
        "date_agreement": reading.date_agreement,
        "raw_delta": round_seconds(raw),
        "duration": round_seconds(duration),
        "transition_after": bool(flagged),
        "cue_start": round_seconds(window[0]),
        "cue_end": round_seconds(window[1]),
        "action": _row_text(row, "action"),
        "commentary": _row_text(row, "commentary"),
    }
    return {name: entry[name] for name in ENTRY_FIELDS}


def build_timeline(
    rows: Iterable[Dict[str, Any]],
    observations: Optional[Dict[int, Dict[str, Any]]] = None,
    dates: Optional[Sequence[Any]] = None,
    manifest_attestation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the whole timeline from manifest rows.  Pure.

    Takes the rows of playthrough/manifest.jsonl -- or any sequence of
    mappings shaped like them -- and returns the document that
    playthrough/timeline.json holds: one entry per row in the same
    order, plus the totals and the constants they were computed under.
    Nothing is dropped, merged, reordered or decimated, so the length
    of the frames array is always the number of rows given.

    :param observations: the capture telemetry, keyed by frame index,
        as :func:`load_observations` returns it.  Its ``date`` values
        are the sidebar date lines the day counter is cross-checked
        against.  It is a parameter rather than a file read so that the
        whole computation stays pure and testable.  A SEQUENCE is
        accepted here too and is read as ``dates`` below: the two
        records carry the same evidence in two shapes, and this
        argument is the one every caller reaches for first.
    :param dates: the same evidence in its other form -- the per-frame
        date lines ocr_clock.py recorded as it read them, parallel to
        ``rows``, as :func:`date_lines_for_rows` returns them.  It is
        consulted for any frame the telemetry has no date for, so the
        two records complement rather than compete.

    Passing NEITHER means NO EVIDENCE: the timeline is then computed
    from the clock alone under the MAX_WRAP_ADVANCE bound, so a
    backwards clock is believed only where the crossing it implies is
    small enough to be a crossing and is otherwise reconciled rather
    than inferred into a day that may never have passed; and every
    day decision is recorded as AGREE_NONE -- no date was read at all,
    which is a different statement from AGREE_UNVERIFIED and is kept
    distinct from it (see :func:`_audit_evidence`).  This function
    stays pure and reads nothing from the disk; main() supplies the
    evidence.

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
    # The evidence argument is shape-tolerant on purpose.  The telemetry
    # is a MAPPING keyed by frame index; the audit is a SEQUENCE
    # parallel to the rows.  Both are date evidence for the same
    # frames, and both callers pass theirs in the same position, so a
    # sequence arriving as `observations` is read as `dates` rather than
    # being misindexed by frame number.
    if observations is not None and not isinstance(observations, dict):
        if dates is None:
            dates = observations
        observations = None
    # THE TWO DATE RECORDS COMPLEMENT EACH OTHER, they do not compete.
    # capture.sh's telemetry row carries the date it emitted for a
    # frame; ocr_clock.py's audit carries the date the module recorded
    # as it read the very pixels.  Either alone is evidence; where both
    # exist the telemetry is taken first and the audit fills any frame
    # the telemetry had no date for, so a gap in one record does not
    # become an unevidenced rollover.  With neither, `resolved` stays
    # None and absolutise_clocks falls back to its BOUNDED clock-only
    # rule: a wrap within MAX_WRAP_ADVANCE is believed, anything larger
    # is reconciled rather than inflated into a day that may never have
    # passed.
    audit_dates = list(dates) if dates is not None else []
    resolved: Optional[List[Any]] = None
    if observations is not None or dates is not None:
        resolved = []
        for position, row in enumerate(materialised, start=1):
            observed = (
                _observed_date(observations, _row_index(row, position))
                if observations is not None else None)
            if observed is None and position <= len(audit_dates):
                observed = audit_dates[position - 1]
            resolved.append(observed)
    readings = absolutise_clocks(
        [row.get("ingame_clock") for row in materialised], resolved)
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
        # The provenance of this computation.  Supplied by the caller
        # rather than read here, because this function is PURE: the
        # caller is the one that resolved and read the manifest, so it
        # is the only party that can honestly say which file that was.
        # An unattested document is refused by
        # assert_timeline_document(), which is the gate every producer
        # of a rendered artifact passes.
        "manifest": (dict(manifest_attestation)
                     if isinstance(manifest_attestation, dict)
                     else manifest_attestation),
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
        "date_confirmed_count": sum(
            1 for entry in entries
            if entry["date_agreement"] == AGREE_CONFIRMED),
        "date_corrected_count": sum(
            1 for entry in entries
            if entry["date_agreement"] == AGREE_CORRECTED),
        "date_unverified_count": sum(
            1 for entry in entries
            if entry["date_agreement"] == AGREE_UNVERIFIED),
        "date_conflict_count": sum(
            1 for entry in entries
            if entry["date_agreement"] == AGREE_CONFLICT),
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

# ---------------------------------------------------------------------
# PROBLEM CODES -- one per check, and exactly one check per code.
#
# validate_timeline() returns human-readable sentences, because the
# operator reading a failed pipeline is who they are for.  But several
# checks legitimately fire at once -- a duration outside the clamp is
# also, necessarily, a duration that does not clamp its raw delta and a
# cue window of the wrong length -- so a sentence alone cannot say
# WHICH check caught a defect.
#
# That distinction is load-bearing for the regression suite rather than
# cosmetic.  A test that asserts only "something was reported" stays
# green when the very check it is named after is deleted, because a
# neighbouring invariant reports an unrelated symptom of the same
# breakage; the test then measures nothing while claiming to protect a
# branch.  Pairing every check with a stable code, and exposing the
# pairs through timeline_problems(), is what lets
# playthrough/tooling/test_timeline.py assert the branch it means and
# therefore fail when that branch goes away.
#
# Two properties are relied on downstream and are asserted by the suite
# itself:
#   * each code names EXACTLY ONE check site in this module, so a
#     code-specific assertion is a branch-specific assertion;
#   * validate_timeline()'s messages are unchanged by the codes, so the
#     command line, write_timeline()'s refusal text and every existing
#     caller read exactly as they did before.
# ---------------------------------------------------------------------

# Document-level shape.
PROBLEM_TIMELINE_NOT_OBJECT = "timeline-not-object"
PROBLEM_TIMELINE_MISSING_FIELD = "timeline-missing-field"
# The provenance checks.  Separate ids because a test that proves a
# stale timeline is caught must be able to name the check that caught
# it, rather than matching prose that may be reworded.
PROBLEM_MANIFEST_NOT_OBJECT = "manifest-attestation-not-object"
PROBLEM_MANIFEST_MISSING_FIELD = "manifest-attestation-missing-field"
PROBLEM_MANIFEST_EXTRA_FIELD = "manifest-attestation-extra-field"
PROBLEM_MANIFEST_PATH_NOT_TEXT = "manifest-attestation-path-not-text"
PROBLEM_MANIFEST_PATH_ABSOLUTE = "manifest-attestation-path-absolute"
PROBLEM_MANIFEST_PATH_UPWARDS = "manifest-attestation-path-upwards"
PROBLEM_MANIFEST_DIGEST = "manifest-attestation-digest"
PROBLEM_MANIFEST_ROWS_NOT_INT = "manifest-attestation-rows-not-integer"
PROBLEM_MANIFEST_ROWS_NEGATIVE = "manifest-attestation-rows-negative"
PROBLEM_MANIFEST_ROWS_MISMATCH = "manifest-attestation-rows-mismatch"
PROBLEM_FRAMES_NOT_ARRAY = "frames-not-array"
PROBLEM_DOCUMENT_COUNT_NOT_INT = "document-count-not-integer"
PROBLEM_DOCUMENT_NOT_NUMBER = "document-field-not-number"
PROBLEM_DOCUMENT_NOT_FINITE = "document-field-not-finite"
PROBLEM_DOCUMENT_COUNT_NEGATIVE = "document-count-negative"
PROBLEM_DOCUMENT_NUMBER_NEGATIVE = "document-number-negative"
PROBLEM_DOCUMENT_VERSION = "document-version-mismatch"
PROBLEM_CONSTANT_REWRITTEN = "constant-rewritten"
PROBLEM_FRAME_COUNT = "frame-count-mismatch"

# One entry of the frames array.
PROBLEM_ENTRY_NOT_OBJECT = "entry-not-object"
PROBLEM_ENTRY_MISSING_FIELD = "entry-missing-field"
PROBLEM_ENTRY_INDEX_NOT_INT = "entry-index-not-int"
PROBLEM_ENTRY_INDEX_SEQUENCE = "entry-index-out-of-sequence"
PROBLEM_ENTRY_NOT_NUMBER = "entry-field-not-number"
PROBLEM_RAW_DELTA_NEGATIVE = "raw-delta-negative"
PROBLEM_DURATION_CLAMP = "duration-outside-clamp"
PROBLEM_TRANSITION_FLAG = "transition-flag-mismatch"
PROBLEM_DURATION_NOT_CLAMPED = "duration-not-clamped"
PROBLEM_CUE_LENGTH = "cue-window-length"
PROBLEM_TRANSITION_NOT_BOOL = "transition-flag-not-boolean"
PROBLEM_CLOCK_SECONDS_NOT_INT = "clock-seconds-not-integer"
PROBLEM_FIELD_NOT_TEXT = "entry-field-not-text"
PROBLEM_FIELD_NOT_TEXT_OR_NULL = "entry-field-not-text-or-null"
PROBLEM_RECONCILED_NOT_BOOL = "reconciled-not-boolean"
PROBLEM_RECONCILED_NO_REASON = "reconciled-without-reason"
PROBLEM_REASON_NOT_RECONCILED = "reason-without-reconciled"

# Properties that only exist across entries.
PROBLEM_FIRST_CUE = "first-cue-not-zero"
PROBLEM_CUE_START = "cue-start-mismatch"
PROBLEM_CLOCK_BACKWARDS = "clock-not-monotonic"
PROBLEM_FINAL_FLAGGED = "final-frame-flagged"
PROBLEM_FINAL_DELTA = "final-frame-delta"

# The totals, including THE INVARIANT.
PROBLEM_TOTAL_DURATION = "total-duration-mismatch"
PROBLEM_TRANSITION_COUNT = "transition-count-mismatch"
PROBLEM_RECONCILED_COUNT = "reconciled-count-mismatch"
PROBLEM_TOTAL_TRANSITION = "total-transition-mismatch"
PROBLEM_TOTAL = "total-mismatch"
PROBLEM_FINAL_CUE_END = "final-cue-end-mismatch"
PROBLEM_TOTAL_VS_CUE = "total-final-cue-disagreement"

# Every code this module can report, so a caller -- and the regression
# suite -- can enumerate them without scraping the source.
PROBLEM_CODES = (
    PROBLEM_TIMELINE_NOT_OBJECT,
    PROBLEM_TIMELINE_MISSING_FIELD,
    PROBLEM_MANIFEST_NOT_OBJECT,
    PROBLEM_MANIFEST_MISSING_FIELD,
    PROBLEM_MANIFEST_EXTRA_FIELD,
    PROBLEM_MANIFEST_PATH_NOT_TEXT,
    PROBLEM_MANIFEST_PATH_ABSOLUTE,
    PROBLEM_MANIFEST_PATH_UPWARDS,
    PROBLEM_MANIFEST_DIGEST,
    PROBLEM_MANIFEST_ROWS_NOT_INT,
    PROBLEM_MANIFEST_ROWS_NEGATIVE,
    PROBLEM_MANIFEST_ROWS_MISMATCH,
    PROBLEM_FRAMES_NOT_ARRAY,
    PROBLEM_DOCUMENT_COUNT_NOT_INT,
    PROBLEM_DOCUMENT_NOT_NUMBER,
    PROBLEM_DOCUMENT_NOT_FINITE,
    PROBLEM_DOCUMENT_COUNT_NEGATIVE,
    PROBLEM_DOCUMENT_NUMBER_NEGATIVE,
    PROBLEM_DOCUMENT_VERSION,
    PROBLEM_CONSTANT_REWRITTEN,
    PROBLEM_FRAME_COUNT,
    PROBLEM_ENTRY_NOT_OBJECT,
    PROBLEM_ENTRY_MISSING_FIELD,
    PROBLEM_ENTRY_INDEX_NOT_INT,
    PROBLEM_ENTRY_INDEX_SEQUENCE,
    PROBLEM_ENTRY_NOT_NUMBER,
    PROBLEM_RAW_DELTA_NEGATIVE,
    PROBLEM_DURATION_CLAMP,
    PROBLEM_TRANSITION_FLAG,
    PROBLEM_TRANSITION_NOT_BOOL,
    PROBLEM_DURATION_NOT_CLAMPED,
    PROBLEM_CUE_LENGTH,
    PROBLEM_CLOCK_SECONDS_NOT_INT,
    PROBLEM_FIELD_NOT_TEXT,
    PROBLEM_FIELD_NOT_TEXT_OR_NULL,
    PROBLEM_RECONCILED_NOT_BOOL,
    PROBLEM_RECONCILED_NO_REASON,
    PROBLEM_REASON_NOT_RECONCILED,
    PROBLEM_FIRST_CUE,
    PROBLEM_CUE_START,
    PROBLEM_CLOCK_BACKWARDS,
    PROBLEM_FINAL_FLAGGED,
    PROBLEM_FINAL_DELTA,
    PROBLEM_TOTAL_DURATION,
    PROBLEM_TRANSITION_COUNT,
    PROBLEM_RECONCILED_COUNT,
    PROBLEM_TOTAL_TRANSITION,
    PROBLEM_TOTAL,
    PROBLEM_FINAL_CUE_END,
    PROBLEM_TOTAL_VS_CUE,
)


class Problem(NamedTuple):
    """One reported defect: which check caught it, and what it says.

    `code` is one of :data:`PROBLEM_CODES` and identifies the check;
    `message` is the sentence :func:`validate_timeline` returns for it,
    unchanged.  A tuple rather than a class with behaviour, because a
    problem is a fact about a document and nothing more.
    """

    code: str
    message: str


def _close(left: float, right: float) -> bool:
    """Return whether two second counts agree to the millisecond."""
    return abs(float(left) - float(right)) <= EPSILON


def _entry_problems(
    entry: Any,
    position: int,
    allow_index_gaps: bool,
) -> List[Problem]:
    """Report every defect in one entry of the frames array."""
    if not isinstance(entry, dict):
        return [Problem(
            PROBLEM_ENTRY_NOT_OBJECT,
            "entry %d is a %s, not an object"
            % (position, type(entry).__name__))]
    missing = [name for name in ENTRY_FIELDS if name not in entry]
    if missing:
        return [Problem(
            PROBLEM_ENTRY_MISSING_FIELD,
            "entry %d is missing %s"
            % (position, ", ".join(missing)))]
    problems = []
    index = entry["frame"]
    if isinstance(index, bool) or not isinstance(index, int):
        problems.append(Problem(
            PROBLEM_ENTRY_INDEX_NOT_INT,
            "entry %d records a %s as its frame index"
            % (position, type(index).__name__)))
    elif index != position and not allow_index_gaps:
        problems.append(Problem(
            PROBLEM_ENTRY_INDEX_SEQUENCE,
            "entry %d records frame %d; the indices run 1..n with no "
            "gap, no repeat and no reordering" % (position, index)))
    duration = entry["duration"]
    raw = entry["raw_delta"]
    for name in ("raw_delta", "duration", "cue_start", "cue_end"):
        value = entry[name]
        if isinstance(value, bool) or not isinstance(
                value, (int, float)):
            problems.append(Problem(
                PROBLEM_ENTRY_NOT_NUMBER,
                "entry %d %s is not a number: %r"
                % (position, name, value)))
            return problems
    if raw < -EPSILON:
        problems.append(Problem(
            PROBLEM_RAW_DELTA_NEGATIVE,
            "entry %d raw_delta is negative (%r); game time only ever "
            "runs forward" % (position, raw)))
    if duration < FLOOR - EPSILON or duration > CEIL + EPSILON:
        problems.append(Problem(
            PROBLEM_DURATION_CLAMP,
            "entry %d duration %r is outside the clamp [%s, %s]"
            % (position, duration, FLOOR, CEIL)))
    # A REAL JSON BOOLEAN, not something that merely coerces to one.
    # bool("") is False and bool("no") is True, so a truthiness test
    # would accept a string in a field the renderer and the caption
    # generator both branch on -- and accept it as whichever value the
    # coercion happened to give, which for "" is the same as a correct
    # false.  A wrong type here is a wrong artifact, so it is reported.
    flag = entry["transition_after"]
    if not isinstance(flag, bool):
        problems.append(Problem(
            PROBLEM_TRANSITION_NOT_BOOL,
            "entry %d transition_after is %r (%s), which is not a "
            "JSON boolean; the flag decides whether a second of video "
            "is charged between two frames, so a value that merely "
            "coerces to true or false is refused"
            % (position, flag, type(flag).__name__)))
    else:
        expected_flag = raw > CEIL
        if flag != expected_flag:
            problems.append(Problem(
                PROBLEM_TRANSITION_FLAG,
                "entry %d transition_after is %r for a raw delta of "
                "%r; the flag is set when and only when the delta "
                "exceeds %s" % (position, flag, raw, CEIL)))
    expected_duration = clamp_duration(raw)
    if not _close(duration, expected_duration):
        problems.append(Problem(
            PROBLEM_DURATION_NOT_CLAMPED,
            "entry %d duration %r does not clamp its raw delta %r, "
            "which gives %r" % (position, duration, raw,
                                expected_duration)))
    if not _close(entry["cue_end"], entry["cue_start"] + duration):
        problems.append(Problem(
            PROBLEM_CUE_LENGTH,
            "entry %d cue window [%r, %r) is not %r long"
            % (position, entry["cue_start"], entry["cue_end"],
               duration)))
    # The remaining fields are type-checked for the same reason: every
    # one of them is read by make_srt.py or render_movie.py, and a
    # number where text belongs (or the reverse) produces a caption file
    # or a concat list that is wrong rather than absent.
    if not isinstance(entry["clock_seconds"], int) or \
            isinstance(entry["clock_seconds"], bool):
        problems.append(Problem(
            PROBLEM_CLOCK_SECONDS_NOT_INT,
            "entry %d clock_seconds is %r (%s), which is not an "
            "integer count of seconds"
            % (position, entry["clock_seconds"],
               type(entry["clock_seconds"]).__name__)))
    for name in ("file", "clock_kind", "action", "commentary"):
        if not isinstance(entry[name], str):
            problems.append(Problem(
                PROBLEM_FIELD_NOT_TEXT,
                "entry %d %s is %r (%s), which is not text"
                % (position, name, entry[name],
                   type(entry[name]).__name__)))
    for name in ("real_ts", "ingame_clock", "reconciled_reason"):
        value = entry[name]
        if value is not None and not isinstance(value, str):
            problems.append(Problem(
                PROBLEM_FIELD_NOT_TEXT_OR_NULL,
                "entry %d %s is %r (%s); it is text or JSON null"
                % (position, name, value, type(value).__name__)))
    reconciled = entry["reconciled"]
    if not isinstance(reconciled, bool):
        problems.append(Problem(
            PROBLEM_RECONCILED_NOT_BOOL,
            "entry %d reconciled is %r (%s), which is not a JSON "
            "boolean" % (position, reconciled,
                         type(reconciled).__name__)))
    elif reconciled and not entry["reconciled_reason"]:
        problems.append(Problem(
            PROBLEM_RECONCILED_NO_REASON,
            "entry %d is reconciled but records no reason; a "
            "reconciled clock is flagged with why, never silently"
            % position))
    elif not reconciled and entry["reconciled_reason"]:
        problems.append(Problem(
            PROBLEM_REASON_NOT_RECONCILED,
            "entry %d records the reason %r but is not flagged "
            "reconciled" % (position, entry["reconciled_reason"])))
    return problems


def timeline_problems(
    document: Any,
    allow_index_gaps: bool = False,
) -> List[Problem]:
    """Return every problem with a timeline, WITH its check's code.

    The structured form of :func:`validate_timeline`, which is a thin
    view of this function.  Each :class:`Problem` names the check that
    caught the defect, so a caller can act on -- or assert on -- one
    specific invariant instead of matching on prose.

    Pure, and evaluated in exactly the order the invariants are stated:
    document shape, then the per-entry checks, then the properties that
    only exist across entries, then the totals.
    """
    if not isinstance(document, dict):
        return [Problem(
            PROBLEM_TIMELINE_NOT_OBJECT,
            "the timeline is a %s, not an object with a frames array"
            % type(document).__name__)]
    missing = [name for name in DOCUMENT_FIELDS
               if name not in document]
    if missing:
        return [Problem(
            PROBLEM_TIMELINE_MISSING_FIELD,
            "the timeline is missing %s" % ", ".join(missing))]
    frames = document["frames"]
    if not isinstance(frames, list):
        return [Problem(
            PROBLEM_FRAMES_NOT_ARRAY,
            "frames is a %s, not an array" % type(frames).__name__)]
    # THE DOCUMENT'S OWN NUMBERS ARE TYPE-CHECKED BEFORE ANY ARITHMETIC
    # TOUCHES THEM.  _close() and math.fsum() below take float() of
    # whatever they are given, so a string or a null in one of these
    # fields raised an uncaught TypeError or ValueError out of a
    # function whose entire contract is to RETURN a list of problems --
    # turning a malformed artifact into a traceback instead of a
    # diagnosis, and one that named no field.  Reported as validation
    # problems instead, and returned immediately so the arithmetic never
    # runs on them.
    shape = _document_numeric_problems(document)
    if shape:
        return shape
    # Provenance is checked before the arithmetic it describes: a
    # document that cannot say what it was computed from is not made
    # trustworthy by its totals adding up.
    attested = _document_manifest_problems(document)
    if attested:
        return attested
    problems = []
    for name, expected in (("floor", FLOOR), ("ceil", CEIL),
                           ("transition", TRANSITION)):
        if not _close(document[name], expected):
            problems.append(Problem(
                PROBLEM_CONSTANT_REWRITTEN,
                "the timeline was written under %s=%r but this module "
                "uses %r; the constants are fixed, not tunable"
                % (name, document[name], expected)))
    if document["frame_count"] != len(frames):
        problems.append(Problem(
            PROBLEM_FRAME_COUNT,
            "frame_count is %r for %d entr(ies)"
            % (document["frame_count"], len(frames))))
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

    The messages are what an operator reads, so this is the form the
    command line and every existing caller use.  Use
    :func:`timeline_problems` when the identity of the check matters --
    for instance to prove in a test that a specific invariant, and not
    a neighbouring one, is what caught a specific defect.
    """
    return [problem.message
            for problem in timeline_problems(document,
                                             allow_index_gaps)]


def _document_numeric_problems(
    document: Dict[str, Any],
) -> List[Problem]:
    """Report document-level fields that are not usable numbers.

    Separated from the checks that compare those numbers, and run before
    them, so that every arithmetic comparison downstream is guaranteed a
    real, finite number to work with.  Counts must be integers because
    they count things; the constants and totals may be either integer or
    float because JSON writes 10.0 and 10 alike.
    """
    problems = []
    for name in ("version", "frame_count", "transition_count",
                 "reconciled_count"):
        value = document[name]
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(Problem(
                PROBLEM_DOCUMENT_COUNT_NOT_INT,
                "%s is %r (%s), which is not an integer"
                % (name, value, type(value).__name__)))
        elif value < 0:
            problems.append(Problem(
                PROBLEM_DOCUMENT_COUNT_NEGATIVE,
                "%s is negative (%r)" % (name, value)))
    for name in ("floor", "ceil", "transition", "total_duration",
                 "total_transition", "total", "final_cue_end"):
        value = document[name]
        if isinstance(value, bool) or not isinstance(
                value, (int, float)):
            problems.append(Problem(
                PROBLEM_DOCUMENT_NOT_NUMBER,
                "%s is %r (%s), which is not a number"
                % (name, value, type(value).__name__)))
        elif math.isnan(value) or math.isinf(value):
            problems.append(Problem(
                PROBLEM_DOCUMENT_NOT_FINITE,
                "%s is %r; a second count must be finite"
                % (name, value)))
        elif value < 0:
            problems.append(Problem(
                PROBLEM_DOCUMENT_NUMBER_NEGATIVE,
                "%s is negative (%r)" % (name, value)))
    if not problems and document["version"] != TIMELINE_VERSION:
        problems.append(Problem(
            PROBLEM_DOCUMENT_VERSION,
            "the timeline declares version %r but this module writes "
            "version %r" % (document["version"], TIMELINE_VERSION)))
    return problems


def _sequence_problems(
    frames: Sequence[Dict[str, Any]],
) -> List[Problem]:
    """Report defects that only show up across entries."""
    problems = []
    if frames and not _close(frames[0]["cue_start"], 0.0):
        problems.append(Problem(
            PROBLEM_FIRST_CUE,
            "the first cue starts at %r; a timeline starts at zero"
            % frames[0]["cue_start"]))
    for position in range(len(frames) - 1):
        here = frames[position]
        nxt = frames[position + 1]
        gap = TRANSITION if here["transition_after"] else 0.0
        expected = here["cue_end"] + gap
        if not _close(nxt["cue_start"], expected):
            problems.append(Problem(
                PROBLEM_CUE_START,
                "entry %d starts at %r; entry %d ends at %r and is "
                "followed by %rs of transition, so it should start at "
                "%r" % (position + 2, nxt["cue_start"], position + 1,
                        here["cue_end"], gap, expected)))
        if nxt["clock_seconds"] < here["clock_seconds"]:
            problems.append(Problem(
                PROBLEM_CLOCK_BACKWARDS,
                "the absolutised clock falls from %r to %r between "
                "entry %d and entry %d"
                % (here["clock_seconds"], nxt["clock_seconds"],
                   position + 1, position + 2)))
    if frames and frames[-1]["transition_after"]:
        problems.append(Problem(
            PROBLEM_FINAL_FLAGGED,
            "the last entry is flagged for a transition; the final "
            "frame has no successor, so its raw delta is zero and "
            "nothing follows it to transition into"))
    if frames and not _close(frames[-1]["raw_delta"], 0.0):
        problems.append(Problem(
            PROBLEM_FINAL_DELTA,
            "the last entry records a raw delta of %r; the final "
            "frame has no successor to difference against"
            % frames[-1]["raw_delta"]))
    return problems


def _total_problems(
    document: Dict[str, Any],
    frames: Sequence[Dict[str, Any]],
) -> List[Problem]:
    """Report defects in the totals, including THE INVARIANT."""
    problems = []
    durations = math.fsum(entry["duration"] for entry in frames)
    flagged = sum(1 for entry in frames if entry["transition_after"])
    reconciled = sum(1 for entry in frames if entry["reconciled"])
    if not _close(document["total_duration"], durations):
        problems.append(Problem(
            PROBLEM_TOTAL_DURATION,
            "total_duration is %r but the frames sum to %r"
            % (document["total_duration"], round_seconds(durations))))
    if document["transition_count"] != flagged:
        problems.append(Problem(
            PROBLEM_TRANSITION_COUNT,
            "transition_count is %r but %d entr(ies) are flagged"
            % (document["transition_count"], flagged)))
    if document["reconciled_count"] != reconciled:
        problems.append(Problem(
            PROBLEM_RECONCILED_COUNT,
            "reconciled_count is %r but %d entr(ies) are flagged"
            % (document["reconciled_count"], reconciled)))
    if not _close(document["total_transition"],
                  TRANSITION * flagged):
        problems.append(Problem(
            PROBLEM_TOTAL_TRANSITION,
            "total_transition is %r for %d transition(s) of %rs"
            % (document["total_transition"], flagged, TRANSITION)))
    grand = document["total_duration"] + document["total_transition"]
    if not _close(document["total"], grand):
        problems.append(Problem(
            PROBLEM_TOTAL,
            "total is %r but %r of frames plus %r of transitions is "
            "%r" % (document["total"], document["total_duration"],
                    document["total_transition"],
                    round_seconds(grand))))
    end = frames[-1]["cue_end"] if frames else 0.0
    if not _close(document["final_cue_end"], end):
        problems.append(Problem(
            PROBLEM_FINAL_CUE_END,
            "final_cue_end is %r but the last cue ends at %r"
            % (document["final_cue_end"], end)))
    if not _close(document["total"], document["final_cue_end"]):
        problems.append(Problem(
            PROBLEM_TOTAL_VS_CUE,
            "total is %r but the final cue ends at %r; the captions "
            "and the container would not agree"
            % (document["total"], document["final_cue_end"])))
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


def approved_root(root: Optional[str] = None) -> str:
    """Return the only directory tree this module may read or write.

    Derived from this module's own location and NEVER from the
    environment.  PLAYTHROUGH_TIMELINE, a -o argument and a caller's
    typo are untrusted input, and this file is the single source of
    truth the renderer and the caption generator both consume: if
    either of them can be pointed at a document written somewhere
    else, "single source of truth" stops meaning anything.
    playthrough/ is the root because every artifact lives beneath it.

    `root` exists so that a test can hold the same rules against a
    temporary directory it owns -- an explicit argument at the call
    site, never something the environment can reach.
    """
    if root is None:
        return os.path.realpath(_playthrough_dir())
    if isinstance(root, os.PathLike):
        root = os.fspath(root)
    if not isinstance(root, str):
        raise TimelineError(
            "the approved root must be a string path, got %s"
            % type(root).__name__)
    if not root.strip():
        raise TimelineError("the approved root must not be empty")
    if "\x00" in root:
        raise TimelineError(
            "the approved root must not contain a NUL byte")
    resolved = os.path.realpath(root)
    if not os.path.isdir(resolved):
        raise TimelineError("no approved root at %s" % resolved)
    return resolved


def _within(path: str, root: str) -> bool:
    """Return True when `path` is `root` itself or lies beneath it."""
    return path == root or path.startswith(root + os.sep)


def _assert_within_root(
    resolved: str,
    label: str,
    root: Optional[str] = None,
) -> str:
    """Refuse a path that does not resolve inside the approved root.

    The FULLY RESOLVED form is what is tested, so `../` sequences and
    a symlink pointing out of the tree are both caught: /etc/anything,
    a device node and a sibling checkout are refused rather than
    written.  Returns the approved root for the caller to reuse.
    """
    approved = approved_root(root)
    canonical = os.path.realpath(resolved)
    if not _within(canonical, approved):
        raise TimelineError(
            "%s must stay inside %s, but %s resolves to %s"
            % (label, approved, resolved, canonical))
    return approved


def _assert_no_symlink(resolved: str, root: str, label: str) -> None:
    """Refuse `resolved` if it or a component below `root` is a link.

    Containment alone is not enough: a link inside the tree still
    points at something else inside the tree, and one planted link
    could make a write land on the manifest, a frame or the movie
    while the write itself reported success.
    """
    if os.path.islink(resolved):
        raise TimelineError(
            "%s is a symbolic link: %s.  This module writes files, it "
            "does not follow links to them." % (label, resolved))
    if not _within(resolved, root):
        # Reached through a symlinked ancestor ABOVE the root -- a
        # checkout under a linked directory.  Containment is already
        # proved, and components above the root are not ours to police.
        return
    current = root
    for part in os.path.relpath(resolved, root).split(os.sep):
        if part in ("", os.curdir):
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise TimelineError(
                "%s has a symlinked component at %s; a link there "
                "could redirect the timeline inside %s"
                % (label, current, root))


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


def _validated_evidence_path(
    value: Any,
    label: str,
    root: Optional[str] = None,
) -> str:
    """Return an absolute EVIDENCE path this module may read.

    The date audit and the capture telemetry are read with exactly the
    contract the timeline artifact itself is read with: shape, then
    canonical containment inside the approved root, then no symbolic
    link on the path or on any component below that root.  Reading is
    not harmless -- these two files decide whether a day passed, so a
    redirected read paces the film from somebody else's evidence while
    every downstream check still passes.  Unlike the timeline target
    the NAME is not pinned, because a caller legitimately points
    --observations or --date-audit at a second capture's sidecar inside
    the tree.
    """
    resolved = _validated_path(value, label)
    approved = _assert_within_root(resolved, label, root)
    _assert_no_symlink(resolved, approved, label)
    return resolved


def _open_evidence(path: str, label: str) -> Any:
    """Open an evidence file for reading with O_NOFOLLOW.

    The gate above reads the path and this opens it; a link planted
    between the two would otherwise be followed, so the kernel refuses
    the final component instead and the race has no window.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as err:
        if err.errno in (errno.ELOOP, errno.EMLINK):
            raise TimelineError(
                "the %s is a symbolic link: %s.  Refusing to follow "
                "it." % (label, path)) from err
        raise TimelineError(
            "could not read the %s %s: %s" % (label, path, err)) from err
    try:
        return os.fdopen(descriptor, "r", encoding="utf-8")
    except OSError as err:
        os.close(descriptor)
        raise TimelineError(
            "could not read the %s %s: %s" % (label, path, err)) from err


def _validated_timeline_target(
    value: Any,
    root: Optional[str] = None,
) -> str:
    """Return an absolute timeline path this module may touch.

    The shared half of reading and writing, so neither entry point can
    be the lenient one: the path must resolve inside the approved root,
    must not be reached through a symlinked component, and must not
    name anything other than a regular file.  A FIFO, a device node,
    /etc/anything and a path outside playthrough/ are refused here
    rather than opened.
    """
    resolved = _validated_path(value, "timeline path")
    approved = _assert_within_root(resolved, "the timeline path", root)
    _assert_no_symlink(resolved, approved, "the timeline path")
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise TimelineError(
            "the timeline path is not a regular file: %s" % resolved)
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


# ---------------------------------------------------------------------
# The artifact lock
#
# THREE PRODUCERS PUBLISH FROM THIS ONE DOCUMENT -- make_transitions.py,
# render_movie.py and make_srt.py -- and each publishes a file or a
# directory that the next stage reads.  Two runs of the same producer, or
# a producer racing a reader, used to interleave: a half-composed
# transitions directory, a movie truncated by `ffmpeg -y` before its
# replacement was verified, an SRT published while its Markdown twin was
# still the previous generation.
#
# So each publication takes an exclusive lock first.  The lock lives
# OUTSIDE the artifact tree, and that is not incidental: .gitignore ends
# with `!/playthrough/**`, which re-includes everything under
# playthrough/ -- so a lock file placed beside the artifacts would be
# committed as though it were evidence.
#
# The scratch location matches session.py's, deliberately, so a sourced
# pipeline and a bare invocation agree on where the pipeline's runtime
# state lives, and the directory is keyed by a digest of the approved
# root so two clones never block each other while two processes over one
# clone always do.
# ---------------------------------------------------------------------

ENV_RUNTIME_DIR = "PLAYTHROUGH_RUNTIME_DIR"
ENV_XDG_RUNTIME_DIR = "XDG_RUNTIME_DIR"
SCRATCH_DIR_NAME = "playthrough"
SESSION_DIR_PREFIX = "session-"

# How long a second publisher waits before refusing.  Rendering a long
# film legitimately takes minutes, so this is generous; an unbounded
# wait is a hang nobody can diagnose.
DEFAULT_LOCK_TIMEOUT = 600.0
LOCK_POLL = 0.1


def _digest_of(text: str) -> str:
    """A short, stable digest of a path, for a directory name."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _secure_dir(path: str, label: str) -> str:
    """Create `path` mode 0700, refusing a link or a foreign owner.

    The same rule env.sh's playthrough_secure_dir applies and the same
    one session.py restates, because a directory another account can
    write to is a directory another account can plant a lock in.
    """
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError as err:
        raise TimelineError(
            "cannot create %s at %s: %s" % (label, path, err)) from err
    try:
        info = os.lstat(path)
    except OSError as err:
        raise TimelineError(
            "cannot inspect %s at %s: %s" % (label, path, err)) from err
    if stat.S_ISLNK(info.st_mode):
        raise TimelineError(
            "%s at %s is a symbolic link; refused, because a link there "
            "redirects whatever is written through it" % (label, path))
    if not stat.S_ISDIR(info.st_mode):
        raise TimelineError(
            "%s at %s is not a directory" % (label, path))
    if info.st_uid != os.getuid():
        raise TimelineError(
            "%s at %s is owned by uid %d, not by uid %d"
            % (label, path, info.st_uid, os.getuid()))
    if info.st_mode & 0o077:
        raise TimelineError(
            "%s at %s is group- or world-accessible (mode %04o)"
            % (label, path, info.st_mode & 0o7777))
    return path


def scratch_dir(root: Optional[str] = None) -> str:
    """Return this checkout's private scratch directory, mode 0700.

    $PLAYTHROUGH_RUNTIME_DIR wins where env.sh has set it, then
    $XDG_RUNTIME_DIR, then /tmp keyed by uid -- the same order
    session.py uses, so the whole pipeline agrees on one location.
    """
    nominated = os.environ.get(ENV_RUNTIME_DIR, "").strip()
    if nominated:
        base = nominated
    else:
        runtime = os.environ.get(ENV_XDG_RUNTIME_DIR, "").strip()
        if runtime:
            base = os.path.join(runtime, SCRATCH_DIR_NAME)
        else:
            base = os.path.join(
                "/tmp", "%s-%d" % (SCRATCH_DIR_NAME, os.getuid()))
    _secure_dir(base, "the pipeline runtime directory")
    private = os.path.join(
        base, SESSION_DIR_PREFIX + _digest_of(approved_root(root)))
    return _secure_dir(private, "the session scratch directory")


def artifact_lock_path(name: str, root: Optional[str] = None) -> str:
    """Return the lock file that serialises one artifact's publication.

    :param name: a bare stem naming the artifact -- "transitions",
        "movie", "transcripts".  Refused if it could reach outside the
        scratch directory.
    """
    if not isinstance(name, str) or not name.strip():
        raise TimelineError("the lock name must be a non-empty string")
    if os.sep in name or (os.altsep and os.altsep in name) \
            or name in (".", "..") or "\x00" in name:
        raise TimelineError(
            "the lock name %r must be a bare name, not a path" % name)
    return os.path.join(scratch_dir(root), "%s.lock" % name)


class ArtifactLock:
    """The exclusive right to publish one artifact.

    Held across build-then-verify-then-switch, so a concurrent run waits
    for a whole generation rather than interleaving with half of one.
    The lock file is never unlinked: removing a lock another process is
    waiting on is how a lock stops working.
    """

    def __init__(self, name: str, root: Optional[str] = None,
                 timeout: float = DEFAULT_LOCK_TIMEOUT) -> None:
        self.name = name
        self.path = artifact_lock_path(name, root)
        self.timeout = float(timeout)
        self._descriptor: Optional[int] = None

    def __enter__(self) -> "ArtifactLock":
        try:
            self._descriptor = os.open(
                self.path, os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC,
                0o600)
        except OSError as err:
            raise TimelineError(
                "could not open the %s lock %s: %s"
                % (self.name, self.path, err)) from err
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._descriptor,
                            fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as err:
                if err.errno not in (errno.EACCES, errno.EAGAIN):
                    self._close()
                    raise TimelineError(
                        "could not lock %s: %s"
                        % (self.path, err)) from err
            if time.monotonic() >= deadline:
                self._close()
                raise TimelineError(
                    "another run has held the %s lock %s for more than "
                    "%.0fs.  Two runs publishing the same artifact would "
                    "overwrite each other, so this one refuses rather "
                    "than interleaving"
                    % (self.name, self.path, self.timeout))
            time.sleep(LOCK_POLL)

    def __exit__(self, *exc_info: Any) -> None:
        if self._descriptor is not None:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            finally:
                self._close()

    def _close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None


def fsync_directory(directory: str) -> None:
    """Force a directory's entries to the device.

    Without this a rename is durable but the FILES it now names may not
    be, so a crash could leave a switch visible and the artifact it
    published empty.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as err:
        raise TimelineError(
            "could not open %s to flush it: %s"
            % (directory, err)) from err
    try:
        os.fsync(descriptor)
    except OSError as err:
        raise TimelineError(
            "could not flush %s: %s" % (directory, err)) from err
    finally:
        os.close(descriptor)


def file_digest(path: str) -> str:
    """Return the sha256 of a file's exact bytes, in hex.

    Block-wise, so the size of a long session's manifest is irrelevant.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(DIGEST_BLOCK), b""):
                digest.update(block)
    except OSError as err:
        raise TimelineError(
            "cannot read %s to attest it: %s" % (path, err)) from err
    return digest.hexdigest()


# ---------------------------------------------------------------------
# GENERATION JOURNALS AND GENERATION MANIFESTS
#
# Shared by the three producers downstream of this module -- the
# transitions, the movie and the pair of transcripts -- because the
# review found the same defect in all three and one implementation is
# the only way they can be fixed the same way.
#
# THE DEFECT.  Each of them published SEVERAL artifacts that only mean
# anything together: a transitions directory whose group set has to match
# the flags in one timeline; a concat list and the movie encoded from it;
# an SRT and the Markdown transcript beside it.  Each publication is
# atomic on its own, and each producer said so -- but a set of atomic
# renames is not an atomic set.  An interruption between two of them left
# a MIXED GENERATION on disk, permanently and undetectably: two files,
# each internally valid, describing different sessions.  Worse, a stale
# survivor is structurally indistinguishable from a fresh one, so a later
# stage would accept it and every count would still tally.
#
# THE TWO PIECES.
#
#   * A GENERATION JOURNAL, in the private scratch directory OUTSIDE the
#     working tree (a journal is machinery, not evidence, and
#     .gitignore's terminal negation would make anything inside
#     playthrough/ committable).  It names every target and the digest
#     each one is about to carry, and it is written durably BEFORE the
#     first rename and cleared AFTER the last verified one.  Its presence
#     at startup is therefore proof that a publication was interrupted,
#     and its contents say exactly which files should now hold what.
#   * A GENERATION MANIFEST, INSIDE the tree beside the artifacts, which
#     is committed with them.  It binds the outputs to the timeline they
#     were computed from -- by that document's own digest -- and to their
#     own sources and bytes.  That is what lets the NEXT stage refuse a
#     stale generation instead of accepting it: the manifest says which
#     timeline these bytes belong to, and a digest is not a matter of
#     opinion.
#
# Neither carries a timestamp, a host name or an absolute path.  Every
# stage in this pipeline is deterministic for a given timeline, so a
# re-run must produce byte-identical files -- including these -- or a
# committed tree would churn on every render.
# ---------------------------------------------------------------------

GENERATION_JOURNAL_SUFFIX = ".generation.json"

# The schema version of both records.  Bump it when a field's MEANING
# changes: a consumer that cannot interpret a journal must refuse it
# rather than half-read it, exactly as session.py refuses a journal from
# an older version of its own schema.
GENERATION_VERSION = 1


def generation_journal_path(name: str,
                            root: Optional[str] = None) -> str:
    """Return the interrupted-publication journal for one stage."""
    if not isinstance(name, str) or not name.strip():
        raise TimelineError("the generation name must be a bare name")
    if os.sep in name or (os.altsep and os.altsep in name) \
            or name in (".", "..") or "\x00" in name:
        raise TimelineError(
            "the generation name %r must be a bare name, not a path"
            % name)
    return os.path.join(scratch_dir(root),
                        name + GENERATION_JOURNAL_SUFFIX)


def write_generation_journal(name: str, record: Mapping[str, Any],
                             root: Optional[str] = None) -> str:
    """Record a publication about to happen, durably.  Returns the path.

    Written and fsynced before the first rename, so an interruption
    anywhere in the switch leaves a description of what the tree should
    hold rather than a set of files nobody can classify.
    """
    path = generation_journal_path(name, root)
    payload = json.dumps(
        dict(record), ensure_ascii=False, sort_keys=True,
        indent=None) + "\n"
    descriptor = os.open(
        path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_CLOEXEC,
        0o600)
    try:
        data = payload.encode("utf-8")
        written = os.write(descriptor, data)
        if written != len(data):
            raise TimelineError(
                "only %d of %d bytes of the %s generation journal "
                "reached %s" % (written, len(data), name, path))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def read_generation_journal(name: str, root: Optional[str] = None,
                            ) -> Optional[Dict[str, Any]]:
    """Return the outstanding publication record for one stage, or None.

    A journal that will not parse is a FAULT rather than an absence: it
    says a publication was interrupted and says nothing usable about
    which, and guessing is what this whole facility exists to avoid.
    """
    path = generation_journal_path(name, root)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    except OSError as err:
        raise TimelineError(
            "cannot read the %s generation journal %s: %s.  It records "
            "a publication that may be half-finished, so it is not "
            "ignored" % (name, path, err)) from err
    if not text.strip():
        return None
    try:
        record = json.loads(text)
    except ValueError as err:
        raise TimelineError(
            "the %s generation journal %s is not valid JSON (%s).  "
            "Establish what is on disk and remove it deliberately"
            % (name, path, err)) from err
    if not isinstance(record, dict):
        raise TimelineError(
            "the %s generation journal %s holds a %s, not a record"
            % (name, path, type(record).__name__))
    return record


def clear_generation_journal(name: str,
                             root: Optional[str] = None) -> None:
    """Remove a journal once every target it names is verified."""
    path = generation_journal_path(name, root)
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as err:
        raise TimelineError(
            "could not clear the %s generation journal %s: %s.  The "
            "next run would report a publication that has completed"
            % (name, path, err)) from err
    try:
        fsync_directory(os.path.dirname(path))
    except TimelineError:
        # The unlink itself is what matters; a filesystem that will not
        # flush the directory has not resurrected the file.
        pass


def generation_journal_problems(name: str,
                                root: Optional[str] = None) -> List[str]:
    """Report a publication that was interrupted.  Read-only.

    Empty means either no journal or a journal whose every target already
    carries the digest it names -- which is the state after a switch that
    completed but was killed before the journal was cleared, and is not a
    fault.  Anything else is a MIXED GENERATION, named file by file, with
    the digest that was expected and the one that is there.
    """
    record = read_generation_journal(name, root)
    if record is None:
        return []
    if record.get("version") != GENERATION_VERSION:
        return ["the %s generation journal is version %r, which this "
                "module cannot interpret; establish what is on disk and "
                "remove it deliberately"
                % (name, record.get("version"))]
    targets = record.get("targets")
    if not isinstance(targets, list) or not targets:
        return ["the %s generation journal names no targets" % name]
    problems = []
    for target in targets:
        if not isinstance(target, dict):
            problems.append(
                "the %s generation journal holds a malformed target "
                "entry" % name)
            continue
        path = target.get("path")
        expected = target.get("sha256")
        if not isinstance(path, str) or not isinstance(expected, str):
            problems.append(
                "the %s generation journal holds a target with no path "
                "or no digest" % name)
            continue
        absolute = os.path.join(approved_root(root), os.pardir, path) \
            if not os.path.isabs(path) else path
        absolute = os.path.normpath(absolute)
        if not os.path.exists(absolute):
            problems.append(
                "%s was to be published by an interrupted %s run and is "
                "not there" % (path, name))
            continue
        if os.path.isdir(absolute):
            # A directory generation is verified by its own manifest,
            # which the producer publishes inside it; the journal only
            # records that the switch was attempted.
            continue
        found = file_digest(absolute)
        if found != expected:
            problems.append(
                "%s carries %s but the interrupted %s run was "
                "publishing %s, so the generation on disk is MIXED: "
                "some of these files are from one run and some from "
                "another" % (path, found[:16], name, expected[:16]))
    return problems


def count_manifest_lines(path: str) -> int:
    """Return the number of rows in a JSONL file.

    Counted from the BYTES, not from parsed rows, because this number
    is part of an attestation of the file as it sits on disk.  A blank
    line is not a row; manifest.py's own schema check is what refuses
    one.
    """
    total = 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    total += 1
    except OSError as err:
        raise TimelineError(
            "cannot read %s to attest it: %s" % (path, err)) from err
    return total


def attest_manifest(
    manifest_path: Optional[str] = None,
    root: Optional[str] = None,
) -> Dict[str, Any]:
    """Describe the manifest this timeline is being computed from.

    Returns the attestation that travels in the document: the
    repository-relative path, the sha256 of the file's exact bytes, and
    the row count.  Read-only.

    The path is resolved through manifest.py's own containment gate
    first, so an attestation can only ever name a manifest this
    pipeline was allowed to read in the first place -- the record and
    the read cannot disagree about which file was used.  ``None`` means
    the canonical manifest, exactly as :func:`load_manifest_rows` reads
    it, so the attestation and the read cannot default differently.
    """
    if manifest_path is None:
        manifest_path = manifest.default_manifest_path()
    try:
        resolved = manifest._validated_manifest_path(manifest_path, root)
    except manifest.ManifestError as err:
        raise TimelineError(str(err)) from err
    return {
        "path": _attested_relpath(resolved, root),
        "sha256": file_digest(resolved),
        "rows": count_manifest_lines(resolved),
    }


def _attested_relpath(resolved: str, root: Optional[str] = None) -> str:
    """Express a path relative to the parent of the approved root.

    In production the approved root is ``<repo>/playthrough``, so this
    yields ``playthrough/manifest.jsonl`` -- the same repository-relative
    form every other record in this pipeline uses.  Deriving it from the
    NOMINATED root rather than from the real checkout is what lets a
    test hold the identical rule against a directory it owns: the
    attestation a confined caller writes is resolvable by the confined
    verifier, and neither reaches outside the tree it was given.
    """
    base = os.path.dirname(approved_root(root))
    return os.path.relpath(resolved, base).replace(os.sep, "/")


def _document_manifest_problems(
    document: Dict[str, Any],
) -> List[Problem]:
    """Check the attestation's SHAPE.  Pure -- no file is read.

    Shape only: that the field is an object carrying exactly the three
    attestation fields, that the path is relative and free of parent
    references, that the digest is 64 lowercase hex digits, and that the
    row count is a non-negative integer agreeing with frame_count.  The
    bytes on disk are checked separately by
    manifest_attestation_problems(), which is I/O and therefore cannot
    live inside a pure validator.

    ``null`` IS ACCEPTED HERE, and the division of labour is deliberate.
    This validator's subject is the timing: the clamp bounds, the
    contiguity of the cue windows, the invariant sum(durations) +
    sum(transitions) == total == final cue end.  Those are properties of
    the numbers and are checkable with no file anywhere -- which is what
    lets the arithmetic be tested, and audited, without a manifest on
    disk.  Provenance is a different question, and it is asked where it
    bites: assert_timeline_document() REQUIRES an attestation and
    requires it to match, and that gate is what every producer of a
    rendered artifact passes.  So an unattested document is not a
    malformed document -- it is simply one that may not pace a film.
    """
    attestation = document.get("manifest")
    if attestation is None:
        return []
    if not isinstance(attestation, dict):
        return [Problem(
            PROBLEM_MANIFEST_NOT_OBJECT,
            "the timeline's manifest attestation is a %s, not an "
            "object naming the evidence it was computed from"
            % type(attestation).__name__)]
    missing = [name for name in MANIFEST_ATTESTATION_FIELDS
               if name not in attestation]
    if missing:
        return [Problem(
            PROBLEM_MANIFEST_MISSING_FIELD,
            "the timeline's manifest attestation is missing %s"
            % ", ".join(missing))]
    extra = sorted(set(attestation) - set(MANIFEST_ATTESTATION_FIELDS))
    if extra:
        return [Problem(
            PROBLEM_MANIFEST_EXTRA_FIELD,
            "the timeline's manifest attestation carries unexpected "
            "field(s) %s; it is exactly %s"
            % (", ".join(extra),
               ", ".join(MANIFEST_ATTESTATION_FIELDS)))]
    problems = []
    stated = attestation["path"]
    if not isinstance(stated, str) or not stated.strip():
        problems.append(Problem(
            PROBLEM_MANIFEST_PATH_NOT_TEXT,
            "the attested manifest path is %r, not a path" % (stated,)))
    elif os.path.isabs(stated) or stated.startswith("~"):
        problems.append(Problem(
            PROBLEM_MANIFEST_PATH_ABSOLUTE,
            "the attested manifest path %r is absolute; it is stored "
            "relative to the repository so the artifact stays "
            "reproducible and leaks no filesystem layout" % stated))
    elif ".." in stated.replace("\\", "/").split("/"):
        problems.append(Problem(
            PROBLEM_MANIFEST_PATH_UPWARDS,
            "the attested manifest path %r walks upwards" % stated))
    digest = attestation["sha256"]
    if not isinstance(digest, str) or not SHA256_RE.match(digest):
        problems.append(Problem(
            PROBLEM_MANIFEST_DIGEST,
            "the attested manifest digest %r is not 64 lowercase hex "
            "digits" % (digest,)))
    rows = attestation["rows"]
    if isinstance(rows, bool) or not isinstance(rows, int):
        problems.append(Problem(
            PROBLEM_MANIFEST_ROWS_NOT_INT,
            "the attested manifest row count is %r, not an integer"
            % (rows,)))
    elif rows < 0:
        problems.append(Problem(
            PROBLEM_MANIFEST_ROWS_NEGATIVE,
            "the attested manifest row count is %d" % rows))
    elif rows != document.get("frame_count"):
        problems.append(Problem(
            PROBLEM_MANIFEST_ROWS_MISMATCH,
            "the attestation names %d manifest row(s) but the timeline "
            "holds %r frame(s); one keystroke makes exactly one row and "
            "one frame, so these cannot differ"
            % (rows, document.get("frame_count"))))
    return problems


def manifest_attestation_problems(
    document: Any,
    root: Optional[str] = None,
) -> List[str]:
    """Check the attestation against the manifest ON DISK.

    This is the check that makes the attestation worth carrying: it
    re-reads the named manifest, recomputes its digest, and reports any
    difference.  A stale timeline beside a re-recorded manifest fails
    here, which is exactly the case no internal invariant can catch.

    Read-only.  Returns messages, like :func:`validate_timeline`, so a
    caller has one reporting shape for both gates.
    """
    if not isinstance(document, dict):
        return ["the timeline is a %s, not an object"
                % type(document).__name__]
    if document.get("manifest") is None:
        return [
            "the timeline carries no manifest attestation, so there is "
            "nothing to prove it was computed from the evidence on this "
            "disk.  timeline.py records the manifest's path, sha256 and "
            "row count when it writes the document; recompute it rather "
            "than pacing a film from a timeline of unknown provenance"]
    shape = _document_manifest_problems(document)
    if shape:
        return [problem.message for problem in shape]
    attestation = document["manifest"]
    stated = attestation["path"]
    base = os.path.dirname(approved_root(root))
    candidate = os.path.join(base, stated)
    try:
        resolved = manifest._validated_manifest_path(candidate, root)
    except manifest.ManifestError as err:
        return ["the attested manifest %s cannot be read: %s"
                % (stated, err)]
    problems = []
    try:
        observed_digest = file_digest(resolved)
        observed_rows = count_manifest_lines(resolved)
    except TimelineError as err:
        return [str(err)]
    if observed_digest != attestation["sha256"]:
        problems.append(
            "the timeline attests manifest %s with sha256 %s, but that "
            "file now hashes to %s.  This timeline was computed from "
            "DIFFERENT evidence than is on disk: recompute it from the "
            "current manifest rather than pacing a film and its "
            "captions from a stale one"
            % (stated, attestation["sha256"], observed_digest))
    if observed_rows != attestation["rows"]:
        problems.append(
            "the timeline attests %d row(s) in manifest %s, but that "
            "file now holds %d"
            % (attestation["rows"], stated, observed_rows))
    return problems


def assert_timeline_document(
    document: Any,
    root: Optional[str] = None,
    allow_index_gaps: bool = False,
    label: str = "timeline",
) -> Dict[str, Any]:
    """The gate every producer of a rendered artifact must pass.

    THE ONE ENTRY POINT FOR TRUSTING A TIMELINE.  make_transitions.py,
    render_movie.py and make_srt.py each read this document and each
    used to accept a bare ARRAY of entries -- which skipped
    validate_timeline() entirely, because that validator's first act is
    to require an object.  An array carried no totals to check the
    entries against, no constants to prove the clamp under, and no
    provenance at all, so a hand-edited list of durations paced the film
    and its captions with nothing objecting.

    Three things are required here, and all three are refusals rather
    than warnings:

      * the document is an OBJECT, so the canonical validator applies;
      * validate_timeline() reports ZERO problems;
      * the manifest attestation matches the manifest on disk.

    :returns: the document, so a caller can gate and bind in one step.
    :raises TimelineError: naming every problem found.
    """
    if not isinstance(document, dict):
        raise TimelineError(
            "the %s is a %s, not an object with a frames array.  A "
            "bare array skips every document-level check -- the totals, "
            "the constants the clamp was applied under, and the "
            "manifest attestation -- so it is refused rather than "
            "paced" % (label, type(document).__name__))
    problems = validate_timeline(document, allow_index_gaps)
    problems.extend(manifest_attestation_problems(document, root))
    if problems:
        raise TimelineError(
            "refusing to use a %s that fails its own checks: %s"
            % (label, "; ".join(problems)))
    return document


def load_manifest_rows(
    manifest_path: Optional[str] = None,
    root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the manifest's rows, in file order.  Read-only.

    Delegates to manifest.read_rows(), which reports a malformed line
    by path and line number, and re-raises its complaint as a
    TimelineError so that a caller of this module has one exception
    type to catch.  `root` is passed straight through and exists for
    the same reason approved_root() takes one: a caller may hold the
    same containment rules against a directory it owns.
    """
    try:
        return manifest.read_rows(manifest_path, root)
    except manifest.ManifestError as err:
        raise TimelineError(str(err)) from err


def default_observations_path(root: Optional[str] = None) -> str:
    """Where the capture telemetry sidecar lives.

    Same precedence as default_date_audit_path(): a nominated root
    outranks $PLAYTHROUGH_OBSERVATIONS because it is the containment
    boundary, then the export, then this file's own location.
    load_observations() takes an explicit path and outranks both.
    """
    if root is not None:
        return os.path.join(approved_root(root),
                            *OBSERVATIONS_REL_PARTS[1:])
    from_env = os.environ.get(ENV_OBSERVATIONS)
    if from_env:
        return _validated_path(from_env, "observations path")
    return os.path.join(_playthrough_dir(), *OBSERVATIONS_REL_PARTS)


def load_observations(
    observations_path: Optional[str] = None,
    required: bool = False,
    root: Optional[str] = None,
) -> Optional[Dict[int, Dict[str, Any]]]:
    """Read the capture telemetry sidecar, keyed by frame index.

    One JSON object per captured frame is appended to
    playthrough/build/observations.jsonl, carrying the sidebar DATE
    line this module cross-checks its day decisions against.  capture.sh
    REPORTS each row on its machine payload and session.py appends it
    beside the manifest row for the same frame, so one record has one
    writer and the capture's own write surface stays the frame.  The
    file
    is APPEND-ONLY, so a frame captured twice has two rows: the LAST
    row for a frame wins, which is the same last-occurrence rule the
    engine applies to duplicated option entries and the only rule that
    makes a re-capture mean what it obviously means.

    An ABSENT file returns None -- the timeline is then computed from
    the clock alone and every day decision is recorded as AGREE_NONE,
    which says no date was read rather than that one was read and
    disagreed -- unless `required`, which turns it into a hard failure
    for a run that must not accept unevidenced rollovers.

    A file that EXISTS but cannot be read or parsed always raises: a
    sidecar that cannot be believed is not the same thing as no
    sidecar, and quietly falling back to the clock would hide the
    difference.

    :param root: a CALL SITE's argument and nothing else -- argparse
        never produces one and the shell entry point never passes one.
        It exists so a test can hold this reader against a temporary
        directory it owns, the same discipline read_timeline() and
        load_manifest_rows() already follow.

    :raises TimelineError: on a missing required file, an unreadable
        file, a malformed line, or a row without a usable frame index.
    """
    path = _validated_evidence_path(
        observations_path or default_observations_path(root),
        "observations path", root)
    if not os.path.exists(path):
        if required:
            raise TimelineError(
                "no capture telemetry at %s, so no rollover or "
                "day-count decision can be checked against the "
                "sidebar date line.  session.py writes it as the "
                "session runs, from what capture.sh reports for each "
                "frame; drop --require-date to pace the film "
                "from whatever evidence there is, and every frame no "
                "date was read for is then recorded '%s'"
                % (path, AGREE_NONE))
        return None

    rows: Dict[int, Dict[str, Any]] = {}
    try:
        with _open_evidence(path, "capture telemetry") as handle:
            for number, raw in enumerate(handle, start=1):
                text = raw.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except ValueError as err:
                    raise TimelineError(
                        "%s line %d is not valid JSON: %s"
                        % (path, number, err)) from err
                if not isinstance(row, dict):
                    raise TimelineError(
                        "%s line %d holds a %s, not an object"
                        % (path, number, type(row).__name__))
                index = row.get("frame")
                if isinstance(index, bool) or not isinstance(
                        index, int):
                    raise TimelineError(
                        "%s line %d records %r as its frame index; "
                        "the sidecar is keyed by frame and an "
                        "unkeyed row cannot be matched to one"
                        % (path, number, index))
                # Last row for a frame wins; see the docstring.
                rows[index] = row
    except OSError as err:
        raise TimelineError(
            "cannot read the capture telemetry at %s: %s"
            % (path, err)) from err
    return rows


def _observed_date(
    observations: Dict[int, Dict[str, Any]],
    frame: int,
) -> Optional[str]:
    """Return the date line observed for one frame, or None.

    A row that reports a status other than "read" carries no date this
    module may use, even if the field happens to be non-empty: the
    status is capture.sh's own account of whether the line was read,
    and honouring it is what keeps a faulted read from being treated
    as evidence.
    """
    row = observations.get(frame)
    if not isinstance(row, dict):
        return None
    status = row.get("date_status")
    if (isinstance(status, str) and status and
            status != DATE_STATUS_READ):
        return None
    value = row.get("date")
    if isinstance(value, str) and value.strip():
        return value
    return None


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


def _sync_directory(parent: str) -> None:
    """Force a rename in `parent` to the device, tolerating refusal.

    os.replace() below is atomic with respect to a reader, but the
    directory entry it creates is not durable until the directory
    itself is synced.  Without this a crash immediately after a
    successful write could leave the OLD timeline in place while the
    renderer had already been told the new one existed.  A filesystem
    that refuses to sync a directory is reported rather than allowed to
    end the run: the data itself is already fsynced.
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
        _warn("could not sync %s after the rename (%s)"
              % (parent, err))
    finally:
        os.close(descriptor)


def write_timeline(
    timeline_path: Optional[str],
    document: Dict[str, Any],
    allow_index_gaps: bool = False,
    root: Optional[str] = None,
) -> str:
    """Validate a timeline and write it.  Returns the path written.

    The document is verified before a byte is written, because a
    timeline that fails its own invariant must not reach the disk where
    the renderer and the caption generator would both trust it.
    newline="\\n" pins LF whatever the platform, which is what the
    committed artifact's `*.json text` attribute expects.

    THE REPLACEMENT IS ATOMIC.  Opening the destination "w" truncates it
    first, so an interruption between the truncation and the last byte
    -- a full disk, a signal, a crash -- destroyed a timeline that was
    valid and left a half-written one in its place.  That artifact is
    the single source of truth for both the movie's pacing and the
    caption timings, and a truncated one is worse than a stale one: the
    stale one is at least internally consistent.  So the text is written
    to a temporary file IN THE SAME DIRECTORY -- the same filesystem is
    what makes the rename atomic -- flushed and fsynced so the bytes are
    durable before anything is swapped, and then moved into place with
    os.replace(), which either fully succeeds or leaves the previous
    file untouched.  The directory entry itself is fsynced afterwards so
    the rename survives a crash too, and a failed attempt cleans up its
    temporary file rather than leaving litter beside the artifact.
    """
    if timeline_path is None:
        timeline_path = default_timeline_path()
    path = _validated_timeline_target(timeline_path, root)
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
    # mkstemp in the destination directory: same filesystem, so the
    # replace below is a rename rather than a copy, and O_EXCL, so no
    # existing file is ever opened by surprise.
    descriptor, temporary = tempfile.mkstemp(
        dir=parent, prefix=".timeline-", suffix=".json.tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8",
                       newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates at 0600; the artifact is committed and read by
        # the renderer and the caption generator, so it carries the
        # ordinary file mode a plain open() would have produced.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except OSError:
        # The destination is untouched at this point, so removing the
        # temporary file restores the directory exactly as it was.
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _sync_directory(parent)
    return path


def read_timeline(
    timeline_path: Optional[str] = None,
    root: Optional[str] = None,
) -> Any:
    """Return the timeline document on disk.  Read-only.

    Held to the same approved-root and no-symlink rules as the write
    path, and opened with O_NOFOLLOW: a redirected read would hand the
    renderer and the caption generator somebody else's document while
    every downstream check still passed.
    """
    if timeline_path is None:
        timeline_path = default_timeline_path()
    path = _validated_timeline_target(timeline_path, root)
    if not os.path.isfile(path):
        raise TimelineError("no timeline at %s" % path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as err:
        if err.errno in (errno.ELOOP, errno.EMLINK):
            raise TimelineError(
                "the timeline path is a symbolic link: %s.  Refusing "
                "to follow it." % path) from err
        raise TimelineError(
            "could not read the timeline %s: %s" % (path, err)) from err
    try:
        handle = os.fdopen(descriptor, "r", encoding="utf-8")
    except OSError as err:
        os.close(descriptor)
        raise TimelineError(
            "could not read the timeline %s: %s" % (path, err)) from err
    with handle:
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
    integer index running 1..n whose `file` names the capture that
    index formats to, a real_ts in the one canonical form, and text
    where text is required.  Applied by BOTH command line paths --
    before a timeline is written, and before one already on disk is
    attested to -- so a manifest that lost a field, or that points a
    row at somebody else's capture, cannot become a timeline that
    quietly filled it in.

    The rules themselves live in manifest.row_problems() and are
    delegated to rather than restated here.  A second copy is exactly
    how a defect slips through: the copy this function used to carry
    checked only that `file` was non-empty text and never looked at
    real_ts at all, so a row whose `file` named frame_00099.png while
    its `frame` said 1, with "yesterday" for a capture timestamp,
    passed a gate that was believed to be authoritative.  One
    implementation, both callers, same words.

    manifest.verify_manifest() additionally checks the file's byte
    shape -- LF endings, one trailing newline -- and is run by
    verify_artifacts.sh; reproducing that here would report every
    schema defect twice and read the file a second time to do it.
    """
    return manifest.row_problems(rows, allow_index_gaps)


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
              "invariant AND match a fresh computation from the "
              "manifest once both are encoded canonically, which is "
              "what proves it describes this session and no other.  "
              "Every difference of CONTENT is drift -- a duration, a "
              "cue, a clock reading, a total, an added or removed "
              "frame, an unexpected key; a difference of layout alone, "
              "such as a reindent, is not"))
    parser.add_argument(
        "--observations", default=None, metavar="PATH",
        help=("the capture telemetry holding the per-frame sidebar "
              "date line, which every rollover and day-count decision "
              "is cross-checked against; defaults to "
              "PLAYTHROUGH_OBSERVATIONS or "
              "<repository>/playthrough/build/observations.jsonl"))
    parser.add_argument(
        "--require-date", action="store_true",
        help=("fail rather than pace the film from the clock alone: "
              "the telemetry must exist and every frame's day "
              "decision must be established by the date line instead "
              "of inferred"))
    parser.add_argument(
        "--allow-index-gaps", action="store_true",
        help=("DIAGNOSTIC ONLY: proceed when the frame indices are not "
              "1..n.  Every other row defect is still refused, the gap "
              "is still reported by `manifest.py verify`, and the "
              "override names itself on stderr, because one keystroke "
              "makes exactly one frame and one row"))
    parser.add_argument(
        "--ignore-manifest-problems", action="store_true",
        help=("DIAGNOSTIC ONLY: compute a timeline from a manifest "
              "that failed its own schema.  Every problem is still "
              "reported and the override is named on stderr, so the "
              "result is never mistaken for a clean one"))
    parser.add_argument(
        "--allow-empty", action="store_true",
        help="proceed when the manifest has no rows at all")
    parser.add_argument(
        "--date-audit", default=None, metavar="PATH",
        help=("the per-frame date evidence ocr_clock.py recorded; "
              "defaults to PLAYTHROUGH_DATE_AUDIT or "
              "<repository>/playthrough/build/frame_dates.jsonl.  It "
              "is what lets a backwards clock be recognised as a "
              "crossing of midnight rather than reconciled as a "
              "misread; an absent file is not an error, it simply "
              "means no rollover can be evidenced"))
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


def _load_rows(
    args: argparse.Namespace,
    root: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read the manifest and gate it, or raise TimelineError.

    The single way rows enter either command line path -- generation
    and verification both come through here, so neither can be the
    lenient one.  The gate is manifest_row_problems(), i.e.
    manifest.row_problems(), which works on the rows already in memory
    and covers everything a correct timeline depends on.
    manifest.verify_manifest() additionally checks the file's byte
    shape -- LF endings, one trailing newline -- and is run by
    verify_artifacts.sh; reproducing it here would report every
    schema defect twice and read the file a second time to do it.

    THE GATE IS THE DEFAULT AND IT REFUSES.  A manifest that fails its
    own schema stops the run, nothing is written, and the remedy named
    in the message is to fix the manifest or recapture -- because a
    timeline written from evidence that had already been reported as
    invalid would look exactly like a correct one to render_movie.py and
    make_srt.py, which read it as the single source of truth and never
    see the warning.

    The two overrides exist ONLY as diagnostics and neither is ever
    implicit.  --ignore-manifest-problems and --allow-index-gaps each
    report every problem they pass over AND announce themselves by name
    on stderr, so a timeline computed under one is never mistaken for a
    clean one.  They are for looking at a broken session, not for
    shipping it; `--verify` is the fully read-only route and reports
    every problem while returning non-zero without writing anything.
    """
    rows = load_manifest_rows(args.manifest, root)
    if not rows and not args.allow_empty:
        raise TimelineError(
            "the manifest has no rows; there is no session to pace.  "
            "Pass --allow-empty if an empty timeline really is what "
            "is wanted")
    problems = manifest_row_problems(
        rows, allow_index_gaps=args.allow_index_gaps)
    if problems:
        _report(problems)
        if not args.ignore_manifest_problems:
            raise TimelineError(
                "%d problem(s) in the manifest; refusing to pace a "
                "film from it.  Fix the manifest or recapture the "
                "affected frames.  --ignore-manifest-problems computes "
                "a timeline anyway, for a diagnosis only: it says so on "
                "stderr, because an artifact built on evidence that "
                "failed its own check would otherwise look exactly "
                "like a correct one to every stage that reads it"
                % len(problems))
        _warn(
            "--ignore-manifest-problems was given, so this timeline is "
            "computed from a manifest with %d reported problem(s).  It "
            "is a DIAGNOSTIC artifact: do not render or caption a "
            "session from it" % len(problems))
    return rows


def _date_evidence_problems(
    document: Dict[str, Any],
) -> List[str]:
    """Report frames whose day decision the date line did not settle.

    Only consulted under --require-date, which is for a run that must
    not accept an inferred day: every frame carrying an exact clock has
    to have had its day either confirmed or corrected by the sidebar
    date line.  A frame with no clock at all is exempt -- there is no
    day decision to verify on a menu screen.

    Two different failures reach here and are reported as the different
    things they are: a day nothing established, and a day the evidence
    positively contradicted.  Both refuse the run, because in neither
    case is the frame's position on the timeline something the date
    line settled -- but an operator reading the failure needs to know
    which one to go and look at.
    """
    problems = []
    for entry in document.get("frames", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("clock_kind") != manifest.CLOCK_EXACT:
            continue
        agreement = entry.get("date_agreement")
        if agreement in (AGREE_CONFIRMED, AGREE_CORRECTED):
            continue
        if agreement == AGREE_CONFLICT:
            problems.append(
                "frame %s carries the clock %r, which the sidebar date "
                "line %r contradicts; the frame is paced from the last "
                "reading that could be believed, so its day was not "
                "established and --require-date refuses it"
                % (entry.get("frame"), entry.get("ingame_clock"),
                   entry.get("ingame_date")))
            continue
        problems.append(
            "frame %s carries the clock %r but no usable sidebar date "
            "line, so its day is %s; --require-date refuses a day that "
            "was inferred from the clock rather than read"
            % (entry.get("frame"), entry.get("ingame_clock"),
               agreement))
    return problems


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


def _audit_evidence(
    args: argparse.Namespace,
    rows: Sequence[Dict[str, Any]],
    root: Optional[str] = None,
) -> Optional[List[Any]]:
    """Return the audit's date lines, or None when it observed none.

    ``date_lines_for_rows`` always returns one slot per row, so an
    absent or empty audit comes back as a list of nulls.  Passing that
    on would make every entry claim its day decision was CHECKED
    against evidence and found unverified, when in truth no date was
    read at all -- a materially different statement, and the artifact
    distinguishes them (AGREE_NONE versus AGREE_UNVERIFIED).  So a
    record that observed nothing is reported as no record.
    """
    lines = date_lines_for_rows(
        rows, audit_path=args.date_audit, root=root)
    if any(line is not None for line in lines):
        return lines
    return None


def _verify(
    args: argparse.Namespace,
    root: Optional[str] = None,
) -> int:
    """Check the timeline on disk against the manifest.  Read-only.

    THE MANIFEST IS GATED FIRST, and by the same gate a write passes.
    --verify claims that the artifact on disk describes THIS session,
    and that claim cannot rest on evidence the canonical validator
    rejects: a row whose `file` names frame_00099.png while its
    `frame` says 1, or whose real_ts is not a timestamp, is a defect
    the drift comparison is structurally blind to, because a timeline
    computed from that manifest carries the same defect on both sides
    and matches itself byte for byte.  Reading the rows through
    _load_rows() is what keeps this an attestation rather than a
    self-consistency check; --ignore-manifest-problems remains the
    only way past it, and it says so on stderr.

    The order matters as much as the gate.  The manifest is the
    evidence and the timeline is the claim about it, so the evidence is
    checked before the claim -- an operator is told the record is
    malformed instead of being handed a drift report computed from it.

    The fresh computation reads the SAME telemetry and the SAME date
    evidence the write used, so the byte comparison still means "this
    file was computed from this manifest and this evidence by this
    code".  Verifying without them would report drift on every session
    that legitimately crossed midnight.
    """
    rows = _load_rows(args, root)
    observations = load_observations(
        args.observations, required=args.require_date, root=root)
    fresh = build_timeline(
        rows, observations, _audit_evidence(args, rows, root),
        attest_manifest(args.manifest, root))
    destination = args.output or default_timeline_path()
    path = _validated_timeline_target(destination, root)
    stored = read_timeline(path, root)
    problems = validate_timeline(stored, args.allow_index_gaps)
    # The stored document's own attestation is checked against the
    # manifest on disk BEFORE the drift comparison, so "this file
    # describes this session" is established rather than inferred from
    # the two computations matching.
    if not problems:
        problems.extend(manifest_attestation_problems(stored, root))
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

    BOTH SIDES ARE RE-ENCODED AND THE ENCODINGS COMPARED, because the
    encoder is deterministic and total (stable key order, fixed float
    formatting, every key it was given).  So a semantic change -- an
    altered value, a new key, a frame added or dropped, a total that no
    longer follows -- fails, while a formatting-only difference passes:
    raising drift for whitespace would train an operator to ignore the
    one check that guards the timing evidence.
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


def main(
    argv: Optional[Sequence[str]] = None,
    root: Optional[str] = None,
) -> int:
    """Run the command line and return an exit status.

    `root` is a call site's argument and nothing else: argparse never
    produces it, no environment variable reaches it, and the shell
    entry point below never passes one.  It exists so that
    test_timeline.py can hold the REAL command line -- this function,
    its gate and its exit status -- against a temporary directory it
    owns, instead of either testing a paraphrase of it or writing into
    the committed artifact tree, which is the captured evidence of a
    session and is not a test fixture.
    """
    args = build_parser().parse_args(argv)
    # --allow-index-gaps reaches the row gate, the document validator
    # and --verify alike, so it announces itself HERE, once, before any
    # of them runs.  Its help text promises that announcement, and an
    # override that relaxes the one-keystroke-one-frame identity
    # without saying so is the whole reason the flag was nearly
    # removed rather than kept.
    if args.allow_index_gaps:
        _warn(
            "--allow-index-gaps was given, so frame indices that are "
            "not 1..n will be accepted.  One keystroke makes exactly "
            "one frame and one row, so this is a DIAGNOSTIC override: "
            "the gap is still reported by `manifest.py verify` and "
            "the artifact it produces is not a session's evidence")
    try:
        if args.verify:
            return _verify(args, root)
        rows = _load_rows(args, root)
        observations = load_observations(
            args.observations, required=args.require_date, root=root)
        document = build_timeline(
            rows, observations, _audit_evidence(args, rows, root),
            attest_manifest(args.manifest, root))
        problems = validate_timeline(document, args.allow_index_gaps)
        problems.extend(manifest_attestation_problems(document, root))
        if args.require_date:
            problems.extend(_date_evidence_problems(document))
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
                args.output, document, args.allow_index_gaps, root)
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
