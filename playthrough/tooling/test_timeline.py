#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/timeline.py.

The timeline mathematics is the one genuinely deterministic component of
the playthrough capture subsystem: given a sequence of sidebar clock
readings it must always produce the same durations, transition flags,
cue windows and SubRip timecodes.  Everything else in the pipeline
photographs a running game, so this module is where the feature's
arithmetic is held to account.

    python3 playthrough/tooling/test_timeline.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

The first form is an acceptance gate in its own right, which is why
unittest.main() is wired up at the bottom of the file.  The -B on the
second is not decoration: the discovery loader compiles what it imports,
and .gitignore's `!/playthrough/**` negation would re-include a
__pycache__ landing under playthrough/tooling/.

WHAT IS ASSERTED
Four arithmetic areas, in the order the requirements fix them:

* THE CLAMP -- duration = min(max(raw, FLOOR), CEIL), including the
  boundary that a raw delta of exactly CEIL is NOT a transition, because
  the comparison is strictly greater;
* THE ROLLOVER GUARD -- midnight is crossed as a positive step only WHEN
  THE SIDEBAR DATE IS OBSERVED TO TURN WITH IT.  A reading that cannot
  be parsed, or that moves backwards with no date evidence, is
  reconciled against its predecessor AND FLAGGED: from the clock alone a
  backwards step is indistinguishable from a misread digit, and assuming
  a rollover would invent hours nobody played;
* THE CUE ARITHMETIC -- a transition's duration is charged to VIDEO time,
  advancing the shared cursor before the following cue begins.  That is
  all that stands between the film and captions that drift further out
  of step with every transition;
* THE SUBRIP FORMATTER -- a comma before the milliseconds, not a full
  stop.

Then the two things the arithmetic alone cannot vouch for:

* the VALIDATOR, branch by branch.  Every check in timeline.py carries a
  stable problem code and every test names the code it means, because
  several invariants legitimately fail together and a test asserting
  only "something was reported" stays green with the very check it is
  named after deleted.  Asserting the code, plus the structural proof
  that each code has exactly one check site, is what makes these
  mutation kills;
* the COMMAND LINE and the FILE CONTRACT, including the exit status of
  each path -- a run_pipeline.sh stage reads only the exit status, so a
  wrong one is a whole stage that appears to have worked -- and the
  manifest gate, which holds generation and verification to ONE
  canonical validator so --verify cannot degenerate into a
  self-consistency check over a manifest describing other frames.

Finally, two properties of the suite itself.
TestTheSuiteCatchesABrokenAlgorithm substitutes a wrong transition
predicate (`>=` for `>`) and a cue walk that forgets to charge the
transition, and proves the canonical expectations stop holding; the
substitution is a module rebinding undone by addCleanup, so the check is
permanent rather than something an author must remember to undo.  The
same class compares against a deepcopy to prove build_timeline() and
validate_timeline() leave their inputs byte-for-byte alone: manifest
rows are the committed record of a session, and a builder that quietly
repaired one would be rewriting evidence.

NO REAL ARTIFACT IS EVER WRITTEN.  Nothing here touches
playthrough/frames/, playthrough/manifest.jsonl or
playthrough/timeline.json.  Pure functions are exercised in memory;
every test needing files works in a temporary directory it creates,
nominates as the approved root and removes, with ALL FOUR of
PLAYTHROUGH_MANIFEST, PLAYTHROUGH_TIMELINE, PLAYTHROUGH_OBSERVATIONS and
PLAYTHROUGH_DATE_AUDIT redirected into it.  Four and not three:
redirecting only the first three leaves the date-evidence sidecar
resolving from whatever env.sh exported, outside the nominated root and
refused by the containment guard -- a failure that arrives only for
whoever sourced the pipeline's environment first.  So the count is
asserted rather than promised (TestTheSuiteIsHermetic), and the suite
must be green both with env.sh sourced and without it.

Standard library only, plus the sibling timeline module, so the
arithmetic is auditable without provisioning a render toolchain.
Nothing is added to tests/, which globs tests/*.cpp into the Catch2
binary.
"""

import ast
import contextlib
import copy
import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

# Importing the sibling module would otherwise drop a __pycache__
# directory into playthrough/tooling/, and the .gitignore negation that
# keeps the save data trackable re-includes the whole playthrough tree
# -- so that directory would surface as an untracked artifact in a
# subtree whose acceptance gate is an empty `git status`.  env.sh
# exports PYTHONDONTWRITEBYTECODE=1 for the pipeline; setting the same
# flag here means running this suite by hand leaves the tree clean too.
# It must precede the import below to have any effect on it.
sys.dont_write_bytecode = True

try:
    import timeline
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import timeline

# The writer of the record and of the amendment ledger.  Imported here
# rather than reached through timeline.manifest so that the suite states
# its own dependency: the amendment tests below WRITE evidence through
# the production writer, which is the only way to prove that what this
# module resolves is what the writer produced.
try:
    import manifest
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import manifest


# ---------------------------------------------------------------------
# The reference sequence.
#
# THE CANONICAL FIXTURE IS THE PUBLISHED ADVERSARIAL TABLE, ROW FOR ROW.
# Seven readings, producing exactly the seven (raw delta, duration,
# transition) rows the requirements enumerate -- no more and no fewer.
# That is deliberate and it is the whole point of calling it the
# reference: an extra row, however ordinary, makes every total in this
# file a number that appears nowhere in the specification, and a suite
# whose headline arithmetic cannot be checked against the document it
# implements is asserting its own invention.  An ordinary post-wake step
# IS worth covering, so it is covered -- in
# TestAnOrdinaryStepAfterWaking below, on its own sequence, where it
# cannot move these constants.
#
# Between them the seven exercise every branch of the duration model: a
# keystroke that consumed no game time, two ordinary steps, two waits
# long enough to engage the ceiling, a crossing of midnight, and a final
# frame with no successor to difference against.  The clock strings are
# the fixed-width 24h form that to_string_time_of_day emits under
# 24_HOUR=24h (src/calendar.cpp:649), which is the shape the session is
# configured to render and the only shape the parser accepts.
#
# Reading                 raw delta   why it is here
#   1  08:15:33               0.0 s   a menu keystroke: no game time
#   2  08:15:33               1.0 s   an ordinary one-second step
#   3  08:15:34               5.0 s   an ordinary five-second step
#   4  08:15:39             300.0 s   a five-minute wait: ceiling
#   5  08:20:39          56 359.0 s   sleeping the night: ceiling
#   6  23:59:58               6.0 s   crosses midnight -- POSITIVE
#   7  00:00:04               0.0 s   final frame: no successor
# ---------------------------------------------------------------------

REFERENCE_CLOCKS = (
    "08:15:33",
    "08:15:33",
    "08:15:34",
    "08:15:39",
    "08:20:39",
    "23:59:58",
    "00:00:04",
)

# The sidebar date line for each of those readings, as ocr_clock.py
# records it per frame.  It is REQUIRED evidence, not decoration: the
# day advances only where this changes, so the 23:59:58 -> 00:00:04 step
# is a crossing of midnight because the date is observed to turn with it
# -- and would be reconciled as a misread if it were not.  Both forms
# display::date_string can render are legal (src/display.cpp:193-205);
# the season form is used here.
#
# EXACTLY SEVEN VALUES, one per reading, and the count is asserted
# rather than eyeballed (see the reference-sequence tests).  An eighth
# value sat here previously: absolutise_clocks() used to ignore a
# surplus silently, so the headline fixture claimed a one-date-per-frame
# cardinality it did not have, and the extra day-4 line proved nothing
# about the crossing it appeared to evidence.  The reader now refuses a
# longer sequence outright, and this tuple is the length it says it is.
REFERENCE_DATES = (
    "Spring, day 3",
    "Spring, day 3",
    "Spring, day 3",
    "Spring, day 3",
    "Spring, day 3",
    "Spring, day 3",
    "Spring, day 4",
)

# raw[i] is the clock advance from frame i to frame i + 1; the last frame
# has no successor and is therefore 0.0, which the floor turns into the
# minimum on-screen duration.
REFERENCE_RAW_DELTAS = (0.0, 1.0, 5.0, 300.0, 56359.0, 6.0, 0.0)
REFERENCE_DURATIONS = (0.25, 1.0, 5.0, 10.0, 10.0, 6.0, 0.25)
REFERENCE_TRANSITIONS = (False, False, False, True, True,
                         False, False)

# The cue windows the walk produces.  Each flagged frame leaves a gap
# between its own cue end and the next cue start: that is its transition,
# charged to video time between the two windows.
REFERENCE_CUES = (
    (0.0, 0.25),
    (0.25, 1.25),
    (1.25, 6.25),
    (6.25, 16.25),
    (17.25, 27.25),
    (28.25, 34.25),
    (34.25, 34.5),
)

# THE INVARIANT this fixture exists to hold:
#     sum(durations) + sum(transitions) == total == final cue end
# The transition term is one TRANSITION second per flagged frame.
REFERENCE_TOTAL_DURATION = 32.5
REFERENCE_TOTAL_TRANSITION = 2.0
REFERENCE_TOTAL = 34.5
REFERENCE_TRANSITION_COUNT = 2

# The index of the frame whose cue opens immediately after the first
# transition: the one that must start a full TRANSITION later than its
# predecessor's cue ended.  Zero-based.
FIRST_POST_TRANSITION = 4

# The clamp table exactly as the requirements state it.  Each row is
# (raw delta, expected duration, expected transition flag), one row per
# distinct behaviour of the model.
CLAMP_TABLE = (
    (0.0, 0.25, False),
    (1.0, 1.0, False),
    (5.0, 5.0, False),
    (300.0, 10.0, True),
    (56359.0, 10.0, True),
    (6.0, 6.0, False),
    (0.0, 0.25, False),
)

# Every coarse phrase display::time_approx() can return, verbatim and
# in source order (src/display.cpp:159-185).  A survivor without a
# watch who can see the sky reads one of these instead of a clock, so
# they are genuine observations of a frame -- and none of them is a
# parseable time.
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

# What display::time_string() falls back to when the sky is not
# visible -- underground, or indoors (src/display.cpp:216).
UNKNOWN_TIME_TEXT = "???"

# A military reading, the shape to_string_time_of_day() emits when
# 24_HOUR is set to "military" (src/calendar.cpp:646, "%02d%02d.%02d").
# It is a legal option value and a genuine clock, and mistaking it for
# the 24h form would be a silent catastrophe: 0815.32 read as 08:15:32
# would invent a time of day that was never on screen.
MILITARY_CLOCK = "0815.32"

# The 12h default form (src/calendar.cpp:657-661), variable width with
# an AM/PM suffix -- the reason seed_options.py selects 24h.
TWELVE_HOUR_CLOCK = "8:15:32 AM"

# The six fields of one manifest row, in order.  Declared here rather
# than imported so that the suite depends on timeline.py alone.
MANIFEST_FIELDS = ("frame", "file", "real_ts", "ingame_clock",
                   "action", "commentary")

# The capture path recorded in the `file` field, repository-relative.
FRAME_FILE_FORMAT = "playthrough/frames/frame_%05d.png"

# A fixed instant for the real_ts column.  A literal rather than a
# reading of the machine clock, because a suite that consulted the
# time of day would not be reproducible.
FIXED_REAL_TS = "2026-05-14T09:12:03.481Z"

# Tolerance for comparing second counts.  Every number the module
# emits is a whole multiple of a quarter second and so is exact in
# binary floating point; the tolerance is here so that a comparison
# against a value this suite computes itself cannot fail on a rounding
# step invisible at millisecond resolution.
PLACES = 6


# ---------------------------------------------------------------------
# Helpers.  Deliberately tiny and deliberately pure: they build inputs
# in memory and read nothing from the environment, so every test below
# is reproducible on any machine.
# ---------------------------------------------------------------------


def make_row(index, clock):
    """Return one manifest-shaped row for `clock`.

    The six declared fields in the declared order, so the same rows can
    be handed to timeline.manifest_row_problems() as well as to
    timeline.build_timeline().  `action` and `commentary` carry short
    in-character text because the schema gate requires them to be
    non-empty; their content is irrelevant to the arithmetic and is
    copied through verbatim.
    """
    return {
        "frame": index,
        "file": FRAME_FILE_FORMAT % index,
        "real_ts": FIXED_REAL_TS,
        "ingame_clock": clock,
        "action": "step",
        "commentary": "I keep moving.",
    }


def make_rows(clocks):
    """Return one row per reading, indexed from 1 in the given order."""
    return [make_row(index, clock)
            for index, clock in enumerate(clocks, start=1)]


def build(clocks, dates=None):
    """Return the timeline document for a sequence of readings.

    `dates` is the per-frame date evidence.  It is passed explicitly in
    every test that depends on a crossing of midnight, because the day
    advances only on observed evidence and a test that omitted it would
    be asserting the behaviour of a session that had none.
    """
    return timeline.build_timeline(make_rows(clocks), dates)


def reference_document():
    """Return the timeline of the reference sequence."""
    return build(REFERENCE_CLOCKS, REFERENCE_DATES)


def field(document, name):
    """Return one field of every frame, in order."""
    return [entry[name] for entry in document["frames"]]


def absolute_seconds(clocks, dates=None):
    """Return the absolutised second count of every reading."""
    return [reading.seconds
            for reading in timeline.absolutise_clocks(clocks, dates)]


def readings_of(clocks, dates=None):
    """Return the ClockReading list for a sequence of readings."""
    return timeline.absolutise_clocks(clocks, dates)


def turning_dates(clocks, turn_at=()):
    """Return date lines that change at each index in `turn_at`.

    A convenience for the rollover tests: `turn_at` lists the positions
    at which the day is observed to turn, so a test states its evidence
    in one place instead of spelling out a parallel tuple of strings.
    """
    day = 1
    out = []
    for position in range(len(clocks)):
        if position in turn_at:
            day += 1
        out.append("Spring, day %d" % day)
    return out


def dated_readings(pairs):
    """Absolutise (clock, date) pairs against the date evidence.

    The one-argument form of absolutise_clocks() computes from the
    clock alone; passing dates is what engages the cross-check, so
    every test of that behaviour goes through here.
    """
    return timeline.absolutise_clocks([clock for clock, _ in pairs],
                                      [date for _, date in pairs])


def observations_of(pairs, status=timeline.DATE_STATUS_READ):
    """Return a sidecar mapping shaped like load_observations()'s.

    Keyed by frame index from 1, carrying the date and the status
    capture.sh reports beside it, which is the only part of the row
    this module reads.
    """
    return {
        index: {"frame": index, "date": date, "date_status": status}
        for index, (_, date) in enumerate(pairs, start=1)
    }


def build_dated(pairs):
    """Return the timeline of (clock, date) pairs with the sidecar."""
    rows = make_rows([clock for clock, _ in pairs])
    return timeline.build_timeline(rows, observations_of(pairs))


def day_delta(previous, current):
    """Return the whole-day step between two date lines."""
    return timeline.date_day_delta(timeline.parse_date_line(previous),
                                   timeline.parse_date_line(current))


# ---------------------------------------------------------------------
# Mutators.  Each one breaks a known-good timeline in exactly one way,
# and the ones that touch the MODEL -- a delta, a duration, a flag --
# re-derive the numbers that follow from it, because otherwise the
# per-entry checks fire first and the cross-entry invariant under test
# is never reached.  They are module-level functions rather than methods
# so the branch-isolation table can name them directly.
# ---------------------------------------------------------------------


def rederive_document(document):
    """Recompute every derived number from the model in `document`.

    The cue windows, the totals and the counts are all consequences of
    (raw_delta, duration, transition_after).  Re-deriving them is what
    isolates the invariant a test is aiming at from the bookkeeping
    around it.
    """
    frames = document["frames"]
    durations = [entry["duration"] for entry in frames]
    flags = [bool(entry["transition_after"]) for entry in frames]
    windows, _ = timeline.cue_windows(durations, flags)
    for entry, (start, end) in zip(frames, windows):
        entry["cue_start"] = start
        entry["cue_end"] = end
    document["frame_count"] = len(frames)
    document["transition_count"] = sum(1 for flag in flags if flag)
    document["reconciled_count"] = sum(
        1 for entry in frames if entry["reconciled"])
    document["total_duration"] = timeline.round_seconds(
        math.fsum(durations))
    document["total_transition"] = timeline.round_seconds(
        timeline.TRANSITION * document["transition_count"])
    document["total"] = timeline.round_seconds(
        document["total_duration"] + document["total_transition"])
    document["final_cue_end"] = (
        frames[-1]["cue_end"] if frames else 0.0)
    return document


def seal_captures(root, indexes):
    """Create one capture per index inside `root` and attest its bytes.

    THE FIXTURES HAVE TO PRODUCE FRAMES NOW.  timeline.py verifies the
    pixels it is about to time against the append-only attestation ledger
    BEFORE it computes a duration, because a duration is derived from a
    clock read off a frame and a timeline over frames nothing attests is a
    claim about files rather than about a session.  A fixture that wrote
    only a manifest would therefore exercise that refusal instead of the
    run it means to test.

    Each body is derived from the index, so no two frames share a digest
    and a substitution is detectable.  Returns the ledger's path.
    """
    frames = os.path.join(root, "frames")
    if not os.path.isdir(frames):
        os.mkdir(frames)
    build = os.path.join(root, "build")
    if not os.path.isdir(build):
        os.mkdir(build)
    ledger = os.path.join(root, *manifest.DIGESTS_REL_PARTS)
    for index in indexes:
        payload = b"\x89PNG\r\n\x1a\nframe %d\n" % index
        with open(os.path.join(frames, "frame_%05d.png" % index),
                  "wb") as handle:
            handle.write(payload)
        manifest.append_frame_digest(
            ledger, index, "playthrough/frames/frame_%05d.png" % index,
            hashlib.sha256(payload).hexdigest(), len(payload),
            manifest.DIGEST_AT_CAPTURE,
            "2026-08-03T17:56:%02d.400Z" % (index % 60), root=root)
    return ledger


def reseal_captures(root, indexes):
    """Start `root`'s capture ledger over for a different frame set.

    THE LEDGER IS APPEND-ONLY IN PRODUCTION, and that property is
    asserted where it belongs -- in test_manifest.py, against the writer.
    This is a FIXTURE's scratch file rather than evidence, and a test
    whose subject is a differently-shaped record needs the frames and the
    attestations THAT record describes, not the ones setUp happened to
    write first.
    """
    ledger = os.path.join(root, *manifest.DIGESTS_REL_PARTS)
    if os.path.isfile(ledger):
        os.unlink(ledger)
    frames = os.path.join(root, "frames")
    if os.path.isdir(frames):
        for name in os.listdir(frames):
            os.unlink(os.path.join(frames, name))
    return seal_captures(root, indexes)


def frame_indexes(rows):
    """The frame indexes a sequence of manifest rows names."""
    return [row["frame"] for row in rows
            if isinstance(row.get("frame"), int) and
            not isinstance(row.get("frame"), bool)]


def broken_document(**updates):
    """Return the reference timeline with top-level fields replaced."""
    document = reference_document()
    document.update(updates)
    return document


def reference_attestation():
    """A well-formed manifest attestation for the reference document.

    The digest is a placeholder of the right SHAPE rather than a real
    one, because the pure validator's subject is exactly that -- shape.
    Whether the bytes on disk match is manifest_attestation_problems()'
    question, and it needs a file, so it cannot be asked here.
    """
    return {
        "path": "playthrough/manifest.jsonl",
        "sha256": "0" * 64,
        "rows": len(REFERENCE_CLOCKS),
    }


def broken_attestation(**updates):
    """Return the reference timeline with a mutated attestation."""
    attestation = reference_attestation()
    attestation.update(updates)
    return broken_document(manifest=attestation)


def reference_amendment_attestation():
    """A well-formed amendment attestation for the reference document.

    Same discipline as reference_attestation(): the digest is the right
    SHAPE, because the pure validator's subject is shape and whether the
    bytes match belongs to amendment_attestation_problems(), which needs
    a file on disk to answer.
    """
    return {
        "path": "playthrough/amendments.jsonl",
        "sha256": "1" * 64,
        "rows": 2,
        "applied": 2,
    }


def broken_amendments(**updates):
    """Return the reference timeline with a mutated ledger attestation."""
    attestation = reference_amendment_attestation()
    attestation.update(updates)
    return broken_document(amendments=attestation)


def reference_capture_attestation():
    """A well-formed capture attestation for the reference document.

    Same discipline again: the digest is the right SHAPE.  Whether the
    ledger on disk hashes to it -- and whether every frame the document
    paces still hashes to the digest sealed for it -- belongs to
    capture_attestation_problems(), which needs the files to answer.
    """
    return {
        "path": "playthrough/build/frame_digests.jsonl",
        "sha256": "2" * 64,
        "rows": len(REFERENCE_CLOCKS),
        "verified": len(REFERENCE_CLOCKS),
    }


def broken_captures(**updates):
    """Return the reference timeline with a mutated capture attestation."""
    attestation = reference_capture_attestation()
    attestation.update(updates)
    return broken_document(captures=attestation)


def broken_entry(index, **updates):
    """Return the reference timeline with one entry's fields replaced."""
    document = reference_document()
    document["frames"][index].update(updates)
    return document


def _without_entry_field(name):
    """Return a timeline whose first entry lost one field."""
    document = reference_document()
    del document["frames"][0][name]
    return document


def _without_document_field(name):
    """Return a timeline that lost one top-level field."""
    document = reference_document()
    del document[name]
    return document


def _entry_replaced_with(value):
    """Return a timeline whose first entry is not an object."""
    document = reference_document()
    document["frames"][0] = value
    return document


def _shifted_cues(offset):
    """Return a timeline whose cues all moved, lengths unchanged."""
    document = reference_document()
    for entry in document["frames"]:
        entry["cue_start"] += offset
        entry["cue_end"] += offset
    document["final_cue_end"] = document["frames"][-1]["cue_end"]
    return document


def _cues_without_transitions():
    """Return a timeline whose cues charge no transition second.

    The caption-drift bug exactly: correct until the first transition,
    then a second early for the rest of the film.
    """
    document = reference_document()
    cursor = 0.0
    for entry in document["frames"]:
        entry["cue_start"] = cursor
        entry["cue_end"] = cursor + entry["duration"]
        cursor = entry["cue_end"]
    document["final_cue_end"] = document["frames"][-1]["cue_end"]
    return document


def _final_frame_flagged():
    """Return a timeline whose last frame is flagged, consistently."""
    document = reference_document()
    last = document["frames"][-1]
    last["raw_delta"] = 300.0
    last["duration"] = timeline.CEIL
    last["transition_after"] = True
    return rederive_document(document)


def _final_frame_with_a_delta():
    """Return a timeline whose last frame has an impossible delta."""
    document = reference_document()
    last = document["frames"][-1]
    last["raw_delta"] = 5.0
    last["duration"] = 5.0
    return rederive_document(document)


def _timeline_source():
    """Return timeline.py's own source text, read once, read-only."""
    with open(timeline.__file__, "r", encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------
# Filesystem and environment helpers for the command line tests.
#
# Every one of them works inside a temporary directory the caller owns.
# Nothing here writes to playthrough/frames/, playthrough/manifest.jsonl
# or playthrough/timeline.json: those are the captured evidence of a
# session, and a suite that wrote to the record it exists to protect
# would be worse than no suite at all.
# ---------------------------------------------------------------------


def _write_lines(path, lines):
    """Write one line per element, LF-terminated, and return the path."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


def _read_text(path):
    """Return a file's whole text, read-only."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _remove_tree(path):
    """Remove a temporary directory tree created by this suite."""
    shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def _environment(**values):
    """Set environment variables for a block, then restore them.

    A value of None UNSETS the variable, which is how a test proves what
    the module does when env.sh has not been sourced at all.  Restoring
    afterwards matters because these variables are the pipeline's own
    artifact layout: a test that left one pointing at a temporary
    directory would silently redirect every test after it.
    """
    previous = {name: os.environ.get(name) for name in values}
    try:
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestFloorAndCeilingClamp(unittest.TestCase):
    """The duration model: min(max(raw, FLOOR), CEIL)."""

    def test_the_three_constants_are_the_requirement_values(self):
        self.assertEqual(
            timeline.FLOOR, 0.25,
            msg="the floor is a quarter second, not a tunable")
        self.assertEqual(
            timeline.CEIL, 10.0,
            msg="the ceiling is ten seconds, not a tunable")
        self.assertEqual(
            timeline.TRANSITION, 1.0,
            msg="a transition buys one second of video, not a tunable")

    def test_the_adversarial_clamp_table(self):
        for raw, expected_duration, expected_flag in CLAMP_TABLE:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(
                    timeline.clamp_duration(raw), expected_duration,
                    places=PLACES,
                    msg=("a raw delta of %rs must be shown for %rs"
                         % (raw, expected_duration)))
                self.assertIs(
                    timeline.is_transition(raw), expected_flag,
                    msg=("a raw delta of %rs must%s earn a transition"
                         % (raw, "" if expected_flag else " not")))

    def test_a_zero_delta_rises_to_the_floor(self):
        self.assertEqual(
            timeline.clamp_duration(0.0), timeline.FLOOR,
            msg=("a keystroke that consumed no game time is still on "
                 "screen for the floor; it is not dropped"))

    def test_a_sub_floor_delta_rises_to_the_floor(self):
        self.assertEqual(
            timeline.clamp_duration(0.1), timeline.FLOOR,
            msg="anything under the floor is shown at the floor")

    def test_a_delta_exactly_at_the_floor_is_unchanged(self):
        self.assertEqual(
            timeline.clamp_duration(0.25), 0.25,
            msg="a raw delta of exactly the floor passes through")
        self.assertIs(
            timeline.is_transition(0.25), False,
            msg="the floor is nowhere near the ceiling")

    def test_a_delta_exactly_at_the_ceiling_is_not_a_transition(self):
        # The single easiest thing in the feature to get wrong: the
        # comparison is strictly greater, so ten seconds exactly is
        # shown at full length with nothing inserted after it.
        self.assertEqual(
            timeline.clamp_duration(10.0), 10.0,
            msg="a raw delta of exactly the ceiling passes through")
        self.assertIs(
            timeline.is_transition(10.0), False,
            msg=("a raw delta of exactly 10.0s must NOT be flagged; "
                 "the transition test is strictly greater than the "
                 "ceiling, not greater than or equal to it"))

    def test_a_delta_just_over_the_ceiling_is_a_transition(self):
        self.assertEqual(
            timeline.clamp_duration(10.001), 10.0,
            msg="anything over the ceiling is shown at the ceiling")
        self.assertIs(
            timeline.is_transition(10.001), True,
            msg=("a raw delta of 10.001s exceeds the ceiling and must "
                 "be flagged for a transition"))

    def test_the_ceiling_caps_a_night_of_sleep(self):
        self.assertEqual(
            timeline.clamp_duration(56359.0), 10.0,
            msg="sleeping the night through is capped, not sped up")
        self.assertIs(
            timeline.is_transition(56359.0), True,
            msg="the archetypal sleep case earns a transition")

    def test_zero_delta_frames_are_retained_never_merged(self):
        # Six identical readings: every delta is zero.  A model that
        # "optimised away" a frame with nothing to show would break the
        # one-keystroke-one-capture relation the whole feature rests
        # on, so the entry count must survive untouched.
        clocks = ("08:15:33",) * 6
        document = build(clocks)
        self.assertEqual(
            document["frame_count"], len(clocks),
            msg=("%d zero-delta readings must yield %d entries; not "
                 "one is merged, dropped or optimised away"
                 % (len(clocks), len(clocks))))
        self.assertEqual(
            field(document, "duration"), [timeline.FLOOR] * len(clocks),
            msg="every zero-delta frame sits at the floor")
        self.assertEqual(
            document["transition_count"], 0,
            msg="a session that consumed no game time has no cap")

    def test_every_reference_duration_is_inside_the_clamp(self):
        for index, duration in enumerate(
                field(reference_document(), "duration"), start=1):
            with self.subTest(frame=index):
                self.assertGreaterEqual(
                    duration, timeline.FLOOR,
                    msg="frame %d is below the floor" % index)
                self.assertLessEqual(
                    duration, timeline.CEIL,
                    msg="frame %d is above the ceiling" % index)

    def test_clamp_durations_preserves_length_and_order(self):
        self.assertEqual(
            timeline.clamp_durations(REFERENCE_RAW_DELTAS),
            list(REFERENCE_DURATIONS),
            msg=("the clamp is applied per frame, in order, with no "
                 "frame added or removed"))

    def test_transition_flags_preserves_length_and_order(self):
        self.assertEqual(
            timeline.transition_flags(REFERENCE_RAW_DELTAS),
            list(REFERENCE_TRANSITIONS),
            msg="one transition flag per frame, in order")

    def test_the_clamp_alias_is_the_clamp(self):
        self.assertIs(
            timeline.clamp, timeline.clamp_duration,
            msg=("the requirements call this operation 'the clamp'; "
                 "the alias must not drift from the function"))


class TestRolloverGuard(unittest.TestCase):
    """Absolutisation: monotonic forward only, midnight included."""

    def test_midnight_rollover_yields_a_positive_delta(self):
        # The headline rollover assertion.  A naive difference of the
        # times of day would give -86394 s here, which would then be
        # clamped to the floor and hide a whole night of play.
        clocks = ("23:59:58", "00:00:04")
        seconds = absolute_seconds(
            clocks, turning_dates(clocks, turn_at=(1,)))
        self.assertEqual(
            seconds, [86398, 86404],
            msg=("23:59:58 -> 00:00:04 crosses midnight AND the date "
                 "line is observed to turn with it, so the day counter "
                 "must advance and the absolute values must rise"))
        self.assertEqual(
            timeline.raw_deltas(seconds), [6.0, 0.0],
            msg=("23:59:58 -> 00:00:04 is a POSITIVE six-second step, "
                 "not a negative one"))
        self.assertAlmostEqual(
            timeline.clamp_duration(6.0), 6.0, places=PLACES,
            msg="six seconds of game time is six seconds of video")

    def test_two_consecutive_midnight_crossings_accumulate_days(self):
        clocks = ("23:59:58", "00:00:04", "23:59:59", "00:00:03")
        seconds = absolute_seconds(
            clocks, turning_dates(clocks, turn_at=(1, 3)))
        self.assertEqual(
            [value // timeline.SECONDS_PER_DAY for value in seconds],
            [0, 1, 1, 2],
            msg=("two crossings of midnight must leave the day "
                 "counter at 2; a counter that reset would fold the "
                 "second day back onto the first"))
        self.assertEqual(
            seconds, [86398, 86404, 172799, 172803],
            msg="each crossing adds exactly one day of seconds")
        for delta in timeline.raw_deltas(seconds):
            self.assertGreaterEqual(
                delta, 0.0,
                msg="no delta may be negative across two crossings")

    def test_a_night_of_sleep_across_midnight_is_one_positive_step(self):
        clocks = ("22:10:00", "06:30:00")
        deltas = timeline.raw_deltas(absolute_seconds(
            clocks, turning_dates(clocks, turn_at=(1,))))
        self.assertAlmostEqual(
            deltas[0], 30000.0, places=PLACES,
            msg=("22:10:00 -> 06:30:00 is eight hours and twenty "
                 "minutes forward, across midnight"))
        self.assertIs(
            timeline.is_transition(deltas[0]), True,
            msg="a night of sleep engages the ceiling")

    def test_an_unevidenced_wrap_is_believed_only_within_the_bound(
            self):
        """MAX_WRAP_ADVANCE, both branches, with no date evidence.

        The bound is what lets the timeline tell a genuine crossing
        from a phantom one when nothing corroborates either.  A
        crossing observed between two adjacent keystrokes lands within
        seconds of midnight, so it is believed; a "crossing" that
        implies most of a day from one keystroke is not, and is
        reported as unevidenced rather than inflated.
        """
        self.assertLessEqual(
            timeline.MAX_WRAP_ADVANCE, timeline.SECONDS_PER_HOUR,
            msg=("the bound has to stay far below a day, or a phantom "
                 "advance is exactly what it lets through"))
        near = timeline.absolutise_clocks(["23:59:58", "00:00:04"])
        self.assertEqual(
            [reading.seconds for reading in near], [86398, 86404],
            msg=("six implied seconds is a real crossing of midnight "
                 "and needs no corroboration to be believed"))
        self.assertIs(near[1].reconciled, False)
        self.assertIsNone(near[1].reason)
        self.assertEqual(
            timeline.raw_deltas([r.seconds for r in near]), [6.0, 0.0],
            msg="and the step it produces is positive")
        far = timeline.absolutise_clocks(["08:00:00", "06:00:00"])
        self.assertEqual(
            far[1].seconds, far[0].seconds,
            msg=("twenty-two implied hours from one keystroke is not a "
                 "crossing; the previous absolute is carried forward"))
        self.assertIs(far[1].reconciled, True)
        self.assertEqual(far[1].reason,
                         timeline.RECONCILED_NO_DATE_EVIDENCE,
                         msg="and it says WHY it was not believed")
        self.assertEqual(
            timeline.raw_deltas([r.seconds for r in far]), [0.0, 0.0],
            msg=("a refused wrap contributes no game time at all, so "
                 "the frame falls to the floor rather than to ten "
                 "seconds of invented night"))

    def test_the_absolutised_sequence_never_decreases(self):
        # Every awkward case in one session: unreadable clocks, a
        # coarse phrase, an off-contract format, a crossing of
        # midnight, and ordinary steps after it.
        clocks = ("08:15:33", None, "Dead of night", UNKNOWN_TIME_TEXT,
                  MILITARY_CLOCK, "23:59:58", "00:00:04", "07:59:00",
                  "08:00:00")
        seconds = absolute_seconds(
            clocks, turning_dates(clocks, turn_at=(6,)))
        for index in range(len(seconds) - 1):
            with self.subTest(frame=index + 1):
                self.assertLessEqual(
                    seconds[index], seconds[index + 1],
                    msg=("the absolutised clock fell between frame %d "
                         "and frame %d; game time only runs forward"
                         % (index + 1, index + 2)))
        for index, delta in enumerate(
                timeline.raw_deltas(seconds), start=1):
            with self.subTest(frame=index):
                self.assertGreaterEqual(
                    delta, 0.0,
                    msg="frame %d has a negative raw delta" % index)

    def test_the_final_frame_has_no_delta_to_difference(self):
        deltas = timeline.raw_deltas(
            absolute_seconds(REFERENCE_CLOCKS))
        self.assertEqual(
            deltas[-1], 0.0,
            msg=("the last frame has no successor, so its raw delta "
                 "is zero and the floor gives it 0.25s"))

    def test_raw_deltas_refuses_a_decreasing_input(self):
        # absolutise_clocks() cannot produce this, but a caller that
        # hand-built a sequence could -- and a negative delta would be
        # a silent lie about game time rather than a loud failure.
        with self.assertRaises(
                timeline.TimelineError,
                msg="a decreasing absolute sequence must be refused"):
            timeline.raw_deltas([10, 5])

    def test_an_empty_session_produces_no_deltas(self):
        self.assertEqual(
            timeline.raw_deltas([]), [],
            msg="no readings means no deltas, not a spurious zero")

    def test_a_single_reading_produces_one_zero_delta(self):
        self.assertEqual(
            timeline.raw_deltas([29733]), [0.0],
            msg="one frame has no successor and so a zero delta")

    def test_the_absolutise_alias_is_the_function(self):
        self.assertIs(
            timeline.absolutize_clocks, timeline.absolutise_clocks,
            msg="the spelling alias must not drift from the function")


class TestClockReconciliation(unittest.TestCase):
    """An unreadable clock is flagged, never guessed at.

    Every test here defends the same rule: the reading of the frame is
    authoritative, OCR is an assist, and a value that cannot be read is
    reported as unread rather than replaced by a plausible number.  The
    flag matters as much as the number -- a carried-forward value that
    was not flagged would be indistinguishable from a real reading.
    """

    def test_the_clock_parser_accepts_only_the_contracted_shape(self):
        # The parser every reading passes through, exercised directly:
        # the fixed-width 24h form and nothing else, with None for
        # anything it cannot read rather than a nearest guess.
        self.assertEqual(
            timeline.parse_time_of_day("08:15:33"),
            8 * 3600 + 15 * 60 + 33,
            msg="a reading becomes seconds past midnight")
        self.assertEqual(
            timeline.parse_time_of_day("00:00:00"), 0,
            msg="midnight is zero, not falsy-and-therefore-missing")
        self.assertEqual(
            timeline.parse_time_of_day("  08:15:33  "),
            timeline.parse_time_of_day("08:15:33"),
            msg=("surrounding whitespace is a transcription detail "
                 "rather than part of the reading, and is ignored the "
                 "same way manifest.classify_ingame_clock() ignores it"))
        for value, why in (
                (MILITARY_CLOCK, "the military form the engine can emit"),
                (TWELVE_HOUR_CLOCK, "the 12h default form"),
                ("8:15:33", "a variable-width hour"),
                ("24:00:00", "an hour the engine cannot render"),
                ("08:60:00", "a minute out of range"),
                ("08:15:60", "a second out of range"),
                ("x08:15:33", "OCR debris around a real time"),
                (None, "no reading at all"),
                (81533, "a number where text belongs"),
                (True, "a boolean where text belongs")):
            with self.subTest(value=value):
                self.assertIsNone(
                    timeline.parse_time_of_day(value),
                    msg=("%s must be refused rather than coerced into "
                         "a time that was never on screen" % why))

    def test_the_reason_codes_are_the_contracted_strings(self):
        # These end up in the committed artifact, so their literal
        # values are part of its contract and are pinned here.
        self.assertEqual(timeline.RECONCILED_MISSING, "clock-missing")
        self.assertEqual(timeline.RECONCILED_COARSE, "clock-coarse")
        self.assertEqual(timeline.RECONCILED_UNKNOWN, "clock-unknown")
        self.assertEqual(timeline.RECONCILED_NONSTANDARD,
                         "clock-nonstandard-format")
        self.assertEqual(timeline.RECONCILED_UNPARSEABLE,
                         "clock-unparseable")
        self.assertEqual(timeline.RECONCILED_BACKWARDS,
                         "clock-not-monotonic")

    def test_a_missing_clock_is_carried_forward_and_flagged(self):
        # A menu keystroke in the middle of play: the clock could not
        # be read, and the reading either side of it is the same, so
        # nothing advanced and the frame lands on the floor.
        document = build(("08:00:00", None, "08:00:00"))
        entry = document["frames"][1]
        self.assertEqual(
            entry["clock_seconds"], 28800,
            msg=("a null reading carries the previous absolute value "
                 "forward; it does not reset to zero or interpolate"))
        self.assertEqual(
            entry["raw_delta"], 0.0,
            msg=("nothing advanced across an unreadable clock, so the "
                 "raw delta is zero rather than a guess"))
        self.assertEqual(
            entry["duration"], timeline.FLOOR,
            msg="a carried-forward reading lands on the floor")
        self.assertIs(
            entry["reconciled"], True,
            msg=("a null clock must be FLAGGED reconciled; an "
                 "unflagged carried value would be indistinguishable "
                 "from a real reading"))
        self.assertEqual(
            entry["reconciled_reason"], timeline.RECONCILED_MISSING,
            msg="a null clock is reconciled as missing")
        self.assertIsNone(
            entry["ingame_clock"],
            msg=("the manifest reading is preserved verbatim, "
                 "including JSON null; it is never repaired"))

    def test_a_carried_reading_invents_no_time_of_its_own(self):
        # When the next trusted reading HAS advanced, that advance is
        # charged to the frame holding the carried value, because
        # raw[i] is always abs[i + 1] - abs[i].  What must never happen
        # is an absolute value interpolated somewhere in between: the
        # carried frame keeps the last value that was actually read.
        document = build(("08:00:00", None, "08:00:05"))
        entry = document["frames"][1]
        self.assertEqual(
            entry["clock_seconds"], 28800,
            msg=("the carried frame holds the last value actually "
                 "read; nothing is interpolated into the gap"))
        self.assertAlmostEqual(
            sum(field(document, "raw_delta")), 5.0, places=PLACES,
            msg=("the session advanced five seconds in total, so the "
                 "deltas must sum to five: an unreadable clock loses "
                 "no game time and manufactures none"))

    def test_no_advance_is_lost_or_manufactured(self):
        clocks = ("08:15:33", None, "Dead of night", "08:20:39",
                  "23:59:58", "00:00:04")
        seconds = absolute_seconds(clocks)
        self.assertAlmostEqual(
            sum(timeline.raw_deltas(seconds)),
            float(seconds[-1] - seconds[0]), places=PLACES,
            msg=("the deltas must account for exactly the advance "
                 "between the first and last absolutised readings"))

    def test_every_coarse_phrase_is_unparseable_and_flagged(self):
        for phrase in COARSE_TIME_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    timeline.parse_clock(phrase),
                    msg=("%r is a coarse phrase from "
                         "display::time_approx(), not a clock; it "
                         "must not parse" % phrase))
                self.assertEqual(
                    timeline.reason_for_reading(phrase),
                    timeline.RECONCILED_COARSE,
                    msg="%r is reconciled as coarse" % phrase)
                entry = build(("08:00:00", phrase))["frames"][1]
                self.assertIs(
                    entry["reconciled"], True,
                    msg="a coarse phrase must be flagged")
                self.assertEqual(
                    entry["ingame_clock"], phrase,
                    msg="the phrase is recorded exactly as read")

    def test_the_unknown_reading_is_unparseable_and_flagged(self):
        self.assertIsNone(
            timeline.parse_clock(UNKNOWN_TIME_TEXT),
            msg=("'???' is what display::time_string() shows when the "
                 "sky is not visible; it is not a time"))
        entry = build(("08:00:00", UNKNOWN_TIME_TEXT))["frames"][1]
        self.assertIs(
            entry["reconciled"], True,
            msg="'???' must be flagged reconciled")
        self.assertEqual(
            entry["reconciled_reason"], timeline.RECONCILED_UNKNOWN,
            msg="'???' is reconciled as unknown, not as missing")
        self.assertEqual(
            entry["clock_seconds"], 28800,
            msg="'???' carries the previous absolute value forward")

    def test_a_military_reading_is_refused_not_misparsed(self):
        # 0815.32 is what to_string_time_of_day() emits under
        # 24_HOUR=military.  Reading it as 08:15:32 would invent a
        # time of day that was never on screen, and would do it
        # silently -- so the parser must refuse it outright.
        misreading = timeline.parse_clock("08:15:32")
        self.assertEqual(
            misreading, 29732,
            msg="the 24h form of that time is 29732s past midnight")
        self.assertIsNone(
            timeline.parse_clock(MILITARY_CLOCK),
            msg=("%r is a military reading and must be REFUSED, not "
                 "mis-parsed" % MILITARY_CLOCK))
        entry = build(("08:00:00", MILITARY_CLOCK))["frames"][1]
        self.assertNotEqual(
            entry["clock_seconds"], misreading,
            msg=("%r must not be silently read as 08:15:32; that "
                 "would fabricate a clock the frame never showed"
                 % MILITARY_CLOCK))
        self.assertEqual(
            entry["clock_seconds"], 28800,
            msg="a military reading carries the previous value on")
        self.assertIs(
            entry["reconciled"], True,
            msg="a military reading must be flagged reconciled")
        self.assertEqual(
            entry["reconciled_reason"],
            timeline.RECONCILED_NONSTANDARD,
            msg=("a military reading is a genuine clock in the wrong "
                 "format, which is what its reason code says"))

    def test_a_twelve_hour_reading_is_refused(self):
        self.assertIsNone(
            timeline.parse_clock(TWELVE_HOUR_CLOCK),
            msg=("the 12h form is variable width and off contract; "
                 "it must not parse"))
        self.assertEqual(
            timeline.reason_for_reading(TWELVE_HOUR_CLOCK),
            timeline.RECONCILED_NONSTANDARD,
            msg="a 12h reading is off-contract, not unrecognisable")

    def assertReconciledBackwards(self, document, reason):
        """A backwards reading is clamped, flagged and kept verbatim."""
        entry = document["frames"][1]
        self.assertEqual(
            entry["clock_seconds"], 28800,
            msg=("a backwards reading is clamped to the previous "
                 "absolute value, not inflated into a phantom day"))
        self.assertEqual(
            document["frames"][0]["raw_delta"], 0.0,
            msg="the refused reading contributes no advance")
        self.assertIs(
            entry["reconciled"], True,
            msg="a backwards reading must be flagged reconciled")
        self.assertEqual(
            entry["reconciled_reason"], reason,
            msg="the reason must say WHY the reading was refused")
        self.assertEqual(
            entry["ingame_clock"], document["frames"][1]["ingame_clock"],
            msg=("the refused reading is still recorded verbatim; "
                 "the evidence is kept, only the pacing is corrected"))

    def test_a_backwards_reading_without_date_evidence_is_refused(self):
        # THE PROPERTY THIS RULE PROTECTS.  Reading 08:00:00 ->
        # 06:00:00 as a crossing of midnight would invent most of a day
        # of game time and pace the film to match.  With no date
        # evidence nothing can tell that from a misread digit, so it is
        # reconciled rather than guessed.
        document = build(("08:00:00", "06:00:00", "08:00:02"))
        self.assertReconciledBackwards(
            document, timeline.RECONCILED_NO_DATE_EVIDENCE)

    def test_a_backwards_reading_on_the_same_date_is_refused(self):
        # The date line was read on both frames and did not change, so
        # the day demonstrably did not turn.
        clocks = ("08:00:00", "06:00:00", "08:00:02")
        document = build(clocks, turning_dates(clocks))
        self.assertReconciledBackwards(
            document, timeline.RECONCILED_SAME_DAY)

    def test_a_long_dated_rollover_is_trusted(self):
        # 08:00:00 -> 07:59:00 with the date observed to turn implies
        # 23h59m, and that is ORDINARY PLAY rather than a misread: one
        # sleep keystroke asks the engine for a whole day
        # (`time_duration try_sleep_dur = 24_hours`,
        # src/handle_action.cpp:1464), so an evidenced advance of this
        # size is ordinary play.  No arithmetic plausibility bound is
        # applied on top of the evidence, because any such bound would
        # reconcile away time the survivor genuinely slept through: the
        # captured date is the only authority, so the reading is trusted
        # and the delta comes out positive.
        clocks = ("08:00:00", "07:59:00", "08:00:02")
        document = build(clocks, turning_dates(clocks, turn_at=(1,)))
        self.assertIs(
            document["frames"][1]["reconciled"], False,
            msg=("a date-evidenced rollover is read, however much it "
                 "implies; no bound on the advance is defensible"))
        self.assertAlmostEqual(
            document["frames"][0]["raw_delta"],
            float(23 * 3600 + 59 * 60), places=PLACES,
            msg=("an evidenced rollover from 08:00:00 to 07:59:00 is a "
                 "23h59m step forward, not a negative one"))
        self.assertTrue(
            document["frames"][0]["transition_after"],
            msg=("a night that long is far past the ceiling, so the "
                 "frame carries a transition"))
        self.assertAlmostEqual(
            document["frames"][1]["raw_delta"], 62.0, places=PLACES,
            msg=("the frame after an evidenced rollover differs "
                 "against the new day (08:00:02 - 07:59:00), not "
                 "against the old one"))

    def test_a_dated_rollover_is_trusted(self):
        # The counterpart: the same shape of step, evidenced, is a
        # genuine crossing of midnight and is NOT reconciled.
        clocks = ("23:59:58", "00:00:04")
        document = build(clocks, turning_dates(clocks, turn_at=(1,)))
        self.assertIs(
            document["frames"][1]["reconciled"], False,
            msg="an evidenced rollover is read, not reconciled")
        self.assertAlmostEqual(
            document["frames"][0]["raw_delta"], 6.0, places=PLACES,
            msg="an evidenced rollover yields its positive step")

    def test_an_out_of_range_reading_is_refused(self):
        # Syntactically the contracted shape, arithmetically impossible
        # -- the signature of OCR reading a digit wrongly.
        for text in ("24:00:00", "08:75:00", "08:00:61", "99:99:99"):
            with self.subTest(text=text):
                self.assertIsNone(
                    timeline.parse_clock(text),
                    msg=("%r has an out-of-range field and must be "
                         "refused rather than wrapped" % text))

    def test_ocr_debris_is_refused(self):
        for text in ("", "   ", "O8:I5:32", "8:15:32", "08:15",
                     "08:15:32:44", "x08:15:32", "08:15:32x"):
            with self.subTest(text=text):
                self.assertIsNone(
                    timeline.parse_clock(text),
                    msg=("%r is not the contracted fixed-width 24h "
                         "reading and must not parse" % text))

    def test_a_non_string_reading_is_refused(self):
        for value in (0, 29733, 29733.0, [], {}, True):
            with self.subTest(value=value):
                self.assertIsNone(
                    timeline.parse_clock(value),
                    msg=("a reading is a string or null; %r must not "
                         "parse" % (value,)))

    def test_surrounding_whitespace_is_a_transcription_detail(self):
        self.assertEqual(
            timeline.parse_clock("  08:15:32  "), 29732,
            msg=("whitespace around a reading is transcription, not "
                 "part of the clock"))

    def test_an_exact_reading_is_never_flagged(self):
        document = reference_document()
        self.assertEqual(
            document["reconciled_count"], 0,
            msg=("every reading in the reference sequence is exact, "
                 "so nothing may be flagged reconciled"))
        for index, entry in enumerate(document["frames"], start=1):
            with self.subTest(frame=index):
                self.assertIs(
                    entry["reconciled"], False,
                    msg="frame %d was read, not reconciled" % index)
                self.assertIsNone(
                    entry["reconciled_reason"],
                    msg=("frame %d records a reason but was not "
                         "reconciled" % index))
        self.assertIsNone(
            timeline.reason_for_reading("08:15:32"),
            msg="a parseable reading has no reason to reconcile")

    def test_every_flagged_entry_records_why(self):
        # "07:59:00" after "08:00:00" goes backwards, and this sequence
        # carries NO date evidence, so nothing here can tell a crossing
        # of midnight from a misread digit and the reading is reconciled
        # rather than guessed at.  With the date observed to turn the
        # same step would be trusted -- see
        # test_a_long_dated_rollover_is_trusted.
        clocks = ("08:00:00", None, "Dead of night", UNKNOWN_TIME_TEXT,
                  MILITARY_CLOCK, "07:59:00", "08:00:05")
        document = build(clocks)
        flagged = [entry for entry in document["frames"]
                   if entry["reconciled"]]
        self.assertEqual(
            len(flagged), 5,
            msg=("five of these seven readings are unusable and every "
                 "one must be flagged"))
        self.assertEqual(
            document["reconciled_count"], 5,
            msg="the document count must agree with the entries")
        for entry in flagged:
            with self.subTest(frame=entry["frame"]):
                self.assertTrue(
                    entry["reconciled_reason"],
                    msg=("frame %d is reconciled but records no "
                         "reason; a reconciled clock is always "
                         "flagged with why" % entry["frame"]))

    def test_a_leading_run_of_unreadable_clocks_anchors_forward(self):
        # The language prompt, the main menu and character creation
        # are captured before a world exists, so they have no clock at
        # all.  Anchoring them at zero would charge the whole of the
        # first real reading to the last menu frame as a phantom
        # advance; anchoring forward gives them the floor instead.
        clocks = (None, UNKNOWN_TIME_TEXT, "08:00:00", "08:00:04")
        document = build(clocks)
        self.assertEqual(
            field(document, "clock_seconds"),
            [28800, 28800, 28800, 28804],
            msg=("readings before the first trusted clock anchor "
                 "forward to it, not back to zero"))
        self.assertEqual(
            field(document, "duration")[:2],
            [timeline.FLOOR, timeline.FLOOR],
            msg="menu frames sit at the floor, not at the ceiling")
        self.assertEqual(
            field(document, "reconciled")[:2], [True, True],
            msg=("anchoring is visible in the artifact: the leading "
                 "frames keep their reconciled flag"))

    def test_a_session_with_no_readable_clock_at_all(self):
        # A survivor with no watch and no sight of the sky.  Every
        # frame falls to the floor, every frame is flagged, and
        # nothing is invented to fill the gap.
        clocks = (None, UNKNOWN_TIME_TEXT, "Dead of night", None)
        document = build(clocks)
        self.assertEqual(
            document["reconciled_count"], len(clocks),
            msg="not one reading was usable, so all are flagged")
        self.assertEqual(
            field(document, "duration"), [timeline.FLOOR] * len(clocks),
            msg="with no clock to difference, every frame is floored")
        self.assertAlmostEqual(
            document["total"], timeline.FLOOR * len(clocks),
            places=PLACES,
            msg="the film is the floor times the frame count")

    def test_the_clock_kind_of_each_shape(self):
        self.assertEqual(timeline.clock_kind("08:15:32"), "exact")
        self.assertEqual(timeline.clock_kind(None), "null")
        self.assertEqual(timeline.clock_kind(MILITARY_CLOCK),
                         "nonstandard")
        self.assertEqual(timeline.clock_kind("Dead of night"), "coarse")
        self.assertEqual(timeline.clock_kind(UNKNOWN_TIME_TEXT),
                         "unknown")
        self.assertEqual(timeline.clock_kind("O8:I5:32"),
                         "unrecognised")
        self.assertEqual(
            timeline.clock_kind(17),
            "unrecognised",
            msg=("a reading of the wrong type is described as "
                 "unrecognised rather than raising"))


class TestDateParsing(unittest.TestCase):
    """Reading the sidebar date line, and inverting it to a day.

    src/display.cpp:194-205 renders one of two forms, and
    src/calendar.cpp month_and_day() is exactly invertible for the
    month form: twelve months in four groups of three, each group
    covering 91 days, the first month of a group holding 31 days and
    the other two 30.  These tests pin that inversion, because every
    day count the cross-check makes rests on it.
    """

    def test_the_year_is_four_groups_of_ninety_one_days(self):
        self.assertEqual(
            timeline.DAYS_PER_YEAR,
            timeline.DAYS_PER_MONTH_GROUP * 4,
            msg="364 days, four groups of 91 (src/calendar.cpp)")
        self.assertEqual(
            timeline.DAYS_PER_MONTH_GROUP,
            timeline.LONG_MONTH_DAYS + 2 * timeline.SHORT_MONTH_DAYS,
            msg="31 + 30 + 30, the shape of one group")
        self.assertEqual(
            len(timeline.MONTH_NAMES),
            timeline.MONTHS_PER_GROUP * 4,
            msg="twelve months, three to a group")

    def test_the_first_day_of_the_year_is_ordinal_zero(self):
        self.assertEqual(timeline.month_ordinal("Jan", 1), 0)

    def test_each_group_starts_on_a_multiple_of_ninety_one(self):
        for group, month in enumerate(("Jan", "Apr", "Jul", "Oct")):
            self.assertEqual(
                timeline.month_ordinal(month, 1),
                group * timeline.DAYS_PER_MONTH_GROUP,
                msg="%s opens group %d" % (month, group))

    def test_the_last_day_of_the_year_is_ordinal_three_six_three(self):
        self.assertEqual(
            timeline.month_ordinal("Dec", timeline.SHORT_MONTH_DAYS),
            timeline.DAYS_PER_YEAR - 1,
            msg="Dec 30 is the last day; the year is 364 days")

    def test_a_day_past_the_end_of_a_short_month_is_refused(self):
        # Mar is the third month of its group, so it has 30 days.  A
        # reading of Mar 31 is impossible and must not be inverted into
        # the first of the next month.
        self.assertIsNone(
            timeline.month_ordinal("Mar", 31),
            msg="Mar 31 does not exist in the engine's calendar")
        self.assertIsNone(timeline.month_ordinal("Jan", 32))
        self.assertIsNone(timeline.month_ordinal("Jan", 0))

    def test_an_unknown_month_name_yields_no_ordinal(self):
        self.assertIsNone(
            timeline.month_ordinal(timeline.UNKNOWN_MONTH_NAME, 1),
            msg=("Cataclysm is the engine's name for an unknown month "
                 "and carries no position in the year"))
        self.assertIsNone(timeline.month_ordinal("Smarch", 1))

    def test_the_month_form_is_parsed_with_its_weekday(self):
        reading = timeline.parse_date_line("Thursday, Mar 8")
        self.assertEqual(reading.kind, timeline.DATE_MONTH)
        self.assertEqual(reading.weekday, "Thursday")
        self.assertEqual(reading.ordinal,
                         timeline.month_ordinal("Mar", 8))
        self.assertTrue(reading.usable)

    def test_the_season_form_is_parsed_without_an_ordinal(self):
        reading = timeline.parse_date_line("Spring, day 5")
        self.assertEqual(reading.kind, timeline.DATE_SEASON)
        self.assertEqual(reading.day_of_season, 5)
        self.assertIsNone(
            reading.ordinal,
            msg=("season length is an option, so a season reading "
                 "fixes no position in the year"))
        self.assertTrue(reading.usable)

    def test_absent_and_unrecognised_dates_are_distinguished(self):
        self.assertEqual(timeline.parse_date_line(None).kind,
                         timeline.DATE_ABSENT)
        self.assertEqual(timeline.parse_date_line("").kind,
                         timeline.DATE_ABSENT)
        self.assertEqual(timeline.parse_date_line("Wenceslas").kind,
                         timeline.DATE_UNRECOGNISED)
        for text in (None, "", "Wenceslas"):
            self.assertFalse(
                timeline.parse_date_line(text).usable,
                msg="%r is not evidence of a day" % text)

    def test_identical_readings_are_always_zero_days(self):
        for text in ("Thursday, Mar 8", "Spring, day 5"):
            self.assertEqual(
                day_delta(text, text), 0,
                msg="%r to itself is no days, whatever the form" % text)

    def test_a_month_pair_gives_the_exact_day_count(self):
        self.assertEqual(day_delta("Thursday, Mar 8",
                                   "Friday, Mar 9"), 1)
        self.assertEqual(day_delta("Thursday, Mar 8",
                                   "Thursday, Mar 15"), 7)

    def test_a_new_year_crossing_reads_forward(self):
        # Dec 30 is the last day of the year, so Jan 1 is the next day
        # and not 363 days backwards.
        self.assertEqual(day_delta("Tuesday, Dec 30",
                                   "Wednesday, Jan 1"), 1)
        self.assertEqual(day_delta("Thursday, Dec 28",
                                   "Tuesday, Jan 3"), 5)

    def test_a_season_pair_counts_only_within_one_season(self):
        self.assertEqual(day_delta("Spring, day 5", "Spring, day 9"), 4)
        self.assertIsNone(
            day_delta("Spring, day 88", "Summer, day 2"),
            msg=("season length is an option, so a crossing of a "
                 "season boundary yields no day count"))

    def test_mixed_and_unusable_forms_yield_no_day_count(self):
        self.assertIsNone(day_delta("Thursday, Mar 8", "Spring, day 5"))
        self.assertIsNone(day_delta("Thursday, Mar 8", None))
        self.assertIsNone(day_delta(None, "Thursday, Mar 8"))
        self.assertIsNone(day_delta("Thursday, Mar 8", "Wenceslas"))

    def test_a_backwards_date_stays_negative(self):
        # The regression this bound exists for.  Taken modulo the year,
        # Mar 8 -> Mar 4 would read as 360 days forward, turning an
        # obvious misread into a far larger lie than the one the
        # modulo was there to avoid.
        self.assertEqual(
            day_delta("Thursday, Mar 8", "Sunday, Mar 4"), -4,
            msg=("a backwards date is reported backwards, not wrapped "
                 "into a near-year leap forward"))
        self.assertEqual(
            day_delta("Spring, day 9", "Spring, day 5"), -4,
            msg="the season form reports backwards too")

    def test_the_wrap_is_taken_only_within_the_plausible_bound(self):
        bound = timeline.MAX_DATE_ADVANCE_DAYS
        self.assertGreater(bound, 0)
        # A step whose wrap lands exactly on the bound is a crossing of
        # the new year; one day further back is a misread.
        self.assertEqual(
            day_delta("Thursday, Dec 30",
                      "Thursday, Jan %d" % bound), bound,
            msg="a wrap of exactly the bound is still a crossing")
        self.assertLess(
            day_delta("Thursday, Dec 30",
                      "Thursday, Jan %d" % (bound + 1)), 0,
            msg=("a wrap beyond the bound is a misread and stays "
                 "negative"))

    def test_a_weekday_that_contradicts_the_day_count_is_reported(self):
        previous = timeline.parse_date_line("Thursday, Mar 8")
        current = timeline.parse_date_line("Sunday, Mar 9")
        self.assertIsNotNone(
            timeline.weekday_disagreement(previous, current, 1),
            msg="Sunday is not one day after Thursday")
        agreeing = timeline.parse_date_line("Friday, Mar 9")
        self.assertIsNone(
            timeline.weekday_disagreement(previous, agreeing, 1),
            msg="Friday is one day after Thursday")

    def test_weekdays_agree_modulo_the_week(self):
        previous = timeline.parse_date_line("Thursday, Mar 8")
        current = timeline.parse_date_line("Thursday, Mar 15")
        self.assertIsNone(
            timeline.weekday_disagreement(previous, current,
                                          timeline.DAYS_PER_WEEK),
            msg="seven days on is the same weekday")


class TestDateCrossCheck(unittest.TestCase):
    """The day comes from the date line; the clock gives the time.

    Three defects a clock-only model cannot avoid, each of which
    changes the pacing of the film:

    * a clock that goes backwards while the date does not is a MISREAD,
      and inflating it into a crossing of midnight manufactures a day
      that never passed;
    * a clock that does NOT go backwards while the date advances hides
      whole days, so a 24-hour action reads as no time at all;
    * a date that itself moves backwards, or forwards by more days than
      one keystroke can produce, is evidence that cannot be believed
      and must be refused rather than reconciled into a plausible
      number.

    Every test here drives absolutise_clocks() with the sidecar the
    capture writes, because that is the path the pipeline takes.
    """

    def test_a_phantom_day_is_refused_when_the_date_did_not_change(self):
        # THE DEFECT THE CROSS-CHECK EXISTS FOR.  08:00:00 -> 07:00:00
        # implies a 23-hour advance from one keystroke.  Two independent
        # guards refuse it: MAX_WRAP_ADVANCE refuses it with no date at
        # all, and the date cross-check refuses it again when the date
        # is observed NOT to have turned.  Either alone is enough; both
        # are asserted here because they report it differently.
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("07:00:00", "Thursday, Mar 8"))
        clock_only = timeline.absolutise_clocks(
            [clock for clock, _ in pairs])
        self.assertEqual(
            clock_only[1].seconds - clock_only[0].seconds, 0,
            msg=("the clock alone must not manufacture most of a day "
                 "from a reading that went backwards: an unevidenced "
                 "wrap implying 23 hours is over MAX_WRAP_ADVANCE, so "
                 "it is refused rather than believed"))
        self.assertEqual(
            clock_only[1].reason,
            timeline.RECONCILED_NO_DATE_EVIDENCE,
            msg=("and the refusal is recorded as one for want of "
                 "evidence -- which is exactly what the date supplies "
                 "below"))
        readings = dated_readings(pairs)
        self.assertEqual(
            readings[1].seconds, readings[0].seconds,
            msg="the date says the day did not change, so nothing "
                "advanced")
        self.assertTrue(readings[1].reconciled)
        self.assertEqual(readings[1].reason,
                         timeline.RECONCILED_SAME_DAY,
                         msg=("one condition, one code: a backwards "
                              "clock on an unchanged date reads as "
                              "clock-backwards-same-date wherever it "
                              "is caught"))
        self.assertEqual(readings[1].date_agreement,
                         timeline.AGREE_CONFLICT)

    def test_a_genuine_midnight_crossing_is_confirmed(self):
        pairs = (("23:59:58", "Thursday, Mar 8"),
                 ("00:00:04", "Friday, Mar 9"))
        readings = dated_readings(pairs)
        self.assertEqual(
            readings[1].seconds - readings[0].seconds, 6,
            msg="six seconds forward, not a day backwards")
        self.assertFalse(readings[1].reconciled)
        self.assertEqual(
            readings[1].date_agreement, timeline.AGREE_CONFIRMED,
            msg="the date confirmed what the clock implied")

    def test_a_full_day_at_the_same_time_is_not_zero_seconds(self):
        # The second defect: the time of day is identical, so the clock
        # alone sees no elapsed time at all across a whole day.
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("08:00:00", "Friday, Mar 9"))
        clock_only = timeline.absolutise_clocks(
            [clock for clock, _ in pairs])
        self.assertEqual(
            clock_only[1].seconds - clock_only[0].seconds, 0,
            msg="the clock alone sees no time passing; that is the "
                "defect")
        readings = dated_readings(pairs)
        self.assertEqual(
            readings[1].seconds - readings[0].seconds, 86400,
            msg="the date supplies the missing whole day")
        self.assertFalse(readings[1].reconciled)
        self.assertEqual(readings[1].date_agreement,
                         timeline.AGREE_CORRECTED)

    def test_a_multi_day_span_is_counted_from_the_date(self):
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("09:30:00", "Sunday, Mar 11"))
        readings = dated_readings(pairs)
        self.assertEqual(
            readings[1].seconds - readings[0].seconds,
            3 * 86400 + 5400,
            msg="three whole days plus an hour and a half")
        self.assertEqual(readings[1].date_agreement,
                         timeline.AGREE_CORRECTED)

    def test_a_backwards_date_is_refused_not_wrapped(self):
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("09:00:00", "Sunday, Mar 4"))
        readings = dated_readings(pairs)
        self.assertEqual(
            readings[1].seconds, readings[0].seconds,
            msg=("a backwards date carries the previous reading "
                 "forward; it does not leap 360 days"))
        self.assertTrue(readings[1].reconciled)
        self.assertEqual(readings[1].reason,
                         timeline.RECONCILED_DATE_IMPLAUSIBLE)
        self.assertEqual(readings[1].date_agreement,
                         timeline.AGREE_CONFLICT)

    def test_an_implausible_forward_leap_is_refused(self):
        # A month misread -- Mar read as Aug -- jumps 152 days.  It is
        # indistinguishable from the truth by arithmetic, so it is
        # refused rather than believed.
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("09:00:00", "Thursday, Aug 8"))
        readings = dated_readings(pairs)
        self.assertEqual(readings[1].seconds, readings[0].seconds)
        self.assertEqual(readings[1].reason,
                         timeline.RECONCILED_DATE_IMPLAUSIBLE)
        self.assertEqual(readings[1].date_agreement,
                         timeline.AGREE_CONFLICT)

    def test_the_plausibility_bound_is_inclusive(self):
        bound = timeline.MAX_DATE_ADVANCE_DAYS
        accepted = dated_readings(
            (("08:00:00", "Thursday, Mar 1"),
             ("08:00:00", "Thursday, Mar %d" % (1 + bound))))
        self.assertEqual(
            accepted[1].seconds - accepted[0].seconds, bound * 86400,
            msg="a step of exactly the bound is accepted")
        self.assertFalse(accepted[1].reconciled)
        refused = dated_readings(
            (("08:00:00", "Thursday, Mar 1"),
             ("08:00:00", "Friday, Mar %d" % (2 + bound))))
        self.assertTrue(
            refused[1].reconciled,
            msg="one day past the bound is refused")
        self.assertEqual(refused[1].date_agreement,
                         timeline.AGREE_CONFLICT)

    def test_without_a_sidecar_the_clock_only_rule_still_stands(self):
        clocks = ("23:59:58", "00:00:04")
        readings = timeline.absolutise_clocks(clocks)
        self.assertEqual(
            readings[1].seconds - readings[0].seconds, 6,
            msg="the rollover guard is unchanged when no date is given")
        for reading in readings:
            self.assertEqual(
                reading.date_agreement, timeline.AGREE_NONE,
                msg=("no date evidence was offered at all, which is "
                     "distinct from evidence that was missing"))

    def test_a_missing_date_for_one_pair_is_unverified(self):
        pairs = (("23:59:58", None), ("00:00:04", None))
        readings = dated_readings(pairs)
        self.assertEqual(
            readings[1].seconds - readings[0].seconds, 6,
            msg="the clock-only rule applies where evidence is absent")
        self.assertEqual(
            readings[1].date_agreement, timeline.AGREE_UNVERIFIED,
            msg=("the sidecar existed but carried no date for this "
                 "frame, and the artifact says so"))

    def test_a_faulted_read_is_not_treated_as_evidence(self):
        # capture.sh reports its own account of the read.  A row whose
        # status is not "read" carries no date this module may use,
        # even when the field is non-empty.
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("07:00:00", "Thursday, Mar 8"))
        faulted = observations_of(pairs, status="unreadable")
        rows = make_rows([clock for clock, _ in pairs])
        document = timeline.build_timeline(rows, faulted)
        entry = document["frames"][1]
        self.assertIn(
            entry["date_agreement"],
            (timeline.AGREE_UNVERIFIED, timeline.AGREE_CONFLICT),
            msg="a faulted read is never confirmed or corrected")
        self.assertIsNone(
            entry["ingame_date"],
            msg="a date the capture could not read is not recorded as "
                "one it did")

    def test_a_single_misread_date_does_not_corrupt_the_next_frame(self):
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("09:00:00", "Sunday, Mar 4"),
                 ("10:00:00", "Thursday, Mar 8"))
        readings = dated_readings(pairs)
        self.assertTrue(
            readings[1].reconciled,
            msg="the misread frame is refused")
        self.assertFalse(
            readings[2].reconciled,
            msg=("the frame after a refusal is measured from the last "
                 "trusted reading, so one bad frame cannot cascade"))
        self.assertEqual(
            readings[2].seconds - readings[0].seconds, 2 * 3600,
            msg="two hours from the last reading that was believed")

    def test_the_document_counts_every_agreement(self):
        # One frame of each kind: the anchor and a frame the clock got
        # right (confirmed), a whole day the clock could not see
        # (corrected), a clock the date contradicts (conflict), and a
        # frame the sidecar holds no date for (unverified).
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("09:00:00", "Thursday, Mar 8"),
                 ("09:00:00", "Friday, Mar 9"),
                 ("08:00:00", "Friday, Mar 9"),
                 ("08:00:00", None))
        document = build_dated(pairs)
        self.assertEqual(
            document["date_confirmed_count"], 2,
            msg="the anchor and the frame the date agreed with")
        self.assertEqual(
            document["date_corrected_count"], 1,
            msg="the frame whose day the date supplied")
        self.assertEqual(
            document["date_conflict_count"], 1,
            msg="the frame whose clock the date contradicted")
        self.assertEqual(
            document["date_unverified_count"], 1,
            msg="the frame the sidecar carried no date for")
        self.assertEqual(
            sum(document[name] for name in
                ("date_confirmed_count", "date_corrected_count",
                 "date_conflict_count", "date_unverified_count")),
            document["frame_count"],
            msg=("every frame is accounted for by exactly one "
                 "agreement, so the counts cannot hide a frame"))

    def test_the_date_evidence_reaches_the_artifact(self):
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("08:00:00", "Friday, Mar 9"))
        document = build_dated(pairs)
        self.assertEqual(
            field(document, "ingame_date"),
            ["Thursday, Mar 8", "Friday, Mar 9"],
            msg="the date read for each frame is committed with it")
        self.assertEqual(
            field(document, "date_kind"),
            [timeline.DATE_MONTH] * 2)
        self.assertEqual(
            field(document, "date_agreement"),
            [timeline.AGREE_CONFIRMED, timeline.AGREE_CORRECTED])
        for name in ("ingame_date", "date_kind", "date_agreement"):
            self.assertIn(
                name, timeline.ENTRY_FIELDS,
                msg="%s is part of the declared entry shape" % name)

    def test_the_invariant_holds_with_the_cross_check_engaged(self):
        # The whole point of the single source of truth: whatever the
        # date evidence does to the day counter, the film's length and
        # the last cue's end must still be the same number.
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("08:00:00", "Friday, Mar 9"),
                 ("08:00:05", "Friday, Mar 9"),
                 ("07:00:00", "Friday, Mar 9"),
                 ("09:00:00", "Sunday, Mar 11"))
        document = build_dated(pairs)
        self.assertEqual([], timeline.validate_timeline(document),
                         msg="the timeline passes its own checks")
        self.assertAlmostEqual(
            document["total_duration"] + document["total_transition"],
            document["total"], places=PLACES)
        self.assertAlmostEqual(
            document["frames"][-1]["cue_end"], document["total"],
            places=PLACES,
            msg="the last cue ends where the film ends")

    def test_a_cross_checked_timeline_still_clamps_every_frame(self):
        pairs = (("08:00:00", "Thursday, Mar 8"),
                 ("08:00:00", "Friday, Mar 9"),
                 ("08:00:00", "Friday, Mar 9"))
        document = build_dated(pairs)
        for entry in document["frames"]:
            self.assertGreaterEqual(entry["duration"], timeline.FLOOR)
            self.assertLessEqual(entry["duration"], timeline.CEIL)
        self.assertEqual(
            field(document, "transition_after"),
            [True, False, False],
            msg=("the whole day the date supplied is capped and given "
                 "a transition, exactly as a long clock delta is"))

    def test_more_dates_than_readings_is_refused_not_truncated(self):
        """Evidence that does not line up is not evidence.

        `dates` is parallel to `readings`, so a longer sequence means
        the evidence was assembled against some other frame list -- and
        truncating it pairs frames with other frames' dates while still
        returning a perfectly plausible timeline.  That is exactly how
        this suite's own reference fixture came to carry eight date
        lines for seven readings without a single test noticing.
        """
        with self.assertRaises(timeline.TimelineError) as caught:
            timeline.absolutise_clocks(
                ["08:00:00", "08:00:01"],
                ["Spring, day 3", "Spring, day 3", "Spring, day 4"])
        message = str(caught.exception)
        self.assertIn("3 date lines", message)
        self.assertIn("2 readings", message)

    def test_fewer_dates_than_readings_is_an_ordinary_case(self):
        """Date evidence that stops partway is real, and tolerated.

        A session whose sidecar ends early -- the last frames withdrawn,
        the audit lost -- still has to produce a timeline; the frames it
        does not reach simply have no date, which is what the
        clock-only rule is for.
        """
        readings = timeline.absolutise_clocks(
            ["08:00:00", "08:00:01", "08:00:02"],
            ["Spring, day 3"])
        self.assertEqual(len(readings), 3)
        self.assertEqual(
            [reading.date_agreement for reading in readings],
            [timeline.AGREE_CONFIRMED, timeline.AGREE_UNVERIFIED,
             timeline.AGREE_UNVERIFIED],
            msg=("the frames the evidence did not reach are recorded "
                 "as unverified rather than silently confirmed"))


class TestObservationSidecar(unittest.TestCase):
    """Reading the capture telemetry, and refusing one that lies.

    The sidecar is a second artifact deliberately kept OUT of the
    manifest, whose schema is exactly six fields.  It is append-only,
    so a frame captured twice appears twice and the last row wins.
    """

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.directory = os.path.realpath(holder.name)

    def load(self, path, required=False):
        """Load telemetry, holding the module to THIS directory."""
        return timeline.load_observations(
            path, required=required, root=self.directory)

    def sidecar(self, text):
        """Write `text` as a sidecar and return its path."""
        path = os.path.join(self.directory, "observations.jsonl")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return path

    def test_an_absent_sidecar_is_not_an_error(self):
        path = os.path.join(self.directory, "absent.jsonl")
        self.assertIsNone(
            self.load(path),
            msg=("no telemetry means the film is paced from the clock "
                 "alone, which is a documented mode, not a failure"))

    def test_an_absent_sidecar_is_fatal_when_required(self):
        path = os.path.join(self.directory, "absent.jsonl")
        with self.assertRaises(timeline.TimelineError):
            self.load(path, required=True)

    def test_rows_are_keyed_by_frame(self):
        path = self.sidecar(
            '{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n'
            '{"frame": 2, "date": "Friday, Mar 9", '
            '"date_status": "read"}\n')
        rows = self.load(path)
        self.assertEqual(sorted(rows), [1, 2])
        self.assertEqual(rows[2]["date"], "Friday, Mar 9")

    def test_two_readings_that_agree_corroborate_each_other(self):
        """A re-capture within one step legitimately appends a row.

        Two readings of the same screen are corroboration, not conflict,
        so the frame keeps the date both of them report.
        """
        path = self.sidecar(
            '{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n'
            '{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n')
        self.assertEqual(self.load(path)[1]["date"], "Thursday, Mar 8")

    def test_two_readings_that_disagree_leave_the_date_unobserved(self):
        """LAST-ROW-WINS WAS THE DEFECT, and this is the fix.

        This reader used to take the later row unconditionally, so a
        contradiction still decided a day of game time on nothing better
        than write order -- while read_date_audit(), reading the very
        same kind of evidence, had already been hardened to require
        unanimity.  A code review named the asymmetry: build_timeline
        PREFERRED this record, so the unhardened one was the one that
        decided.  There is no rule by which being written later makes one
        of two contradictory observations the true one.
        """
        path = self.sidecar(
            '{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n'
            '{"frame": 1, "date": "Friday, Mar 9", '
            '"date_status": "read"}\n')
        self.assertIsNone(self.load(path)[1]["date"])

    def test_a_null_reading_does_not_erase_one_that_succeeded(self):
        """An absence of evidence is not counter-evidence.

        `null` is the ordinary shape of an unreadable reading, and under
        last-row-wins a later one silently erased a date that had been
        read -- with no warning at all, because a null is not a conflict.
        """
        path = self.sidecar(
            '{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n'
            '{"frame": 1, "date": null, '
            '"date_status": "unreadable"}\n')
        self.assertEqual(self.load(path)[1]["date"], "Thursday, Mar 8")

    def test_two_keystrokes_for_one_frame_are_refused(self):
        """One keystroke makes one frame, so this is not a re-capture."""
        path = self.sidecar(
            '{"frame": 1, "key": "j", "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n'
            '{"frame": 1, "key": "k", "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n')
        with self.assertRaises(timeline.TimelineError) as caught:
            self.load(path)
        self.assertIn("different keystrokes", str(caught.exception))

    def test_a_row_the_ledger_contradicts_is_discarded(self):
        """A reading of pixels that are no longer at that index.

        The digest binding read_date_audit() already applied, applied
        here too: a row naming a frame_sha256 that is not the digest
        attested for the frame describes a photograph that has been
        withdrawn or re-taken, and attributing its date to whatever now
        holds the index would be a reading of one screen reported as
        another.
        """
        path = self.sidecar(
            '{"frame": 1, "frame_sha256": "%s", '
            '"date": "Thursday, Mar 8", "date_status": "read"}\n'
            % ("a" * 64))
        rows = timeline.load_observations(
            path, root=self.directory, digests={1: "b" * 64})
        self.assertEqual(rows, {})

    def test_a_row_the_ledger_confirms_is_kept(self):
        path = self.sidecar(
            '{"frame": 1, "frame_sha256": "%s", '
            '"date": "Thursday, Mar 8", "date_status": "read"}\n'
            % ("a" * 64))
        rows = timeline.load_observations(
            path, root=self.directory, digests={1: "a" * 64})
        self.assertEqual(rows[1]["date"], "Thursday, Mar 8")

    def test_an_unbound_row_is_used_and_reported(self):
        """Every row of the committed record is in this state.

        The telemetry predates the attestation ledger, so discarding
        unbound rows would throw away a whole captured session's date
        evidence; presenting them as checked would be a false claim.
        """
        path = self.sidecar(
            '{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n')
        rows = timeline.load_observations(
            path, root=self.directory, digests={1: "a" * 64})
        self.assertEqual(rows[1]["date"], "Thursday, Mar 8")

    def test_a_row_of_the_wrong_shape_is_refused(self):
        """The schema is part of the evidence.

        A field of the wrong TYPE is not coerced: `"date": 3` is not a
        date line, `"capture_attempts": 0` is not a count of a capture
        that happened, and a row naming another frame's file cannot be
        attributed to either frame.
        """
        for text in ('{"frame": 1, "date": 3}\n',
                     '{"frame": 1, "date": "x", "date_status": 7}\n',
                     '{"frame": 1, "recovered": "yes"}\n',
                     '{"frame": 1, "capture_attempts": 0}\n',
                     '{"frame": 1, "capture_attempts": "many"}\n',
                     '{"frame": 0, "date": "x"}\n',
                     '{"frame": 1, '
                     '"file": "playthrough/frames/frame_00002.png"}\n'):
            with self.subTest(text=text):
                with self.assertRaises(timeline.TimelineError):
                    timeline.load_observations(
                        self.sidecar(text), root=self.directory)

    def test_a_row_written_by_the_real_writer_validates(self):
        """The contract between the two modules, round-tripped.

        timeline.py restates the schema rather than importing session.py,
        so this is what holds the copy to the original: a row built by
        the real writer, from the real payload contract, must satisfy the
        reader's own validation unchanged.
        """
        tooling = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isfile(os.path.join(tooling, "session.py")):
            self.skipTest("session.py is not beside this test")
        if tooling not in sys.path:
            sys.path.insert(0, tooling)
        try:
            import session as writer
        except ImportError as err:
            # session.py reaches ocr_clock, which needs the capture
            # toolchain; recomputing a timeline deliberately does not.
            self.skipTest("the writer cannot be imported here: %s" % err)
        row = writer.observation_row(
            1,
            {"FRAME_INDEX": "1",
             "FRAME_FILE": "playthrough/frames/frame_00001.png",
             "FRAME_SHA256": "c" * 64,
             "REAL_TS": "2026-08-04T19:18:22.200Z",
             "CLOCK": "08:00:00", "CLOCK_STATUS": "exact",
             "TIME_PHRASE": "", "DATE": "Thursday, Mar 8",
             "DATE_STATUS": "read", "FRAME_GEOMETRY": "1920x1080",
             "LUMA_MEAN": "0.27", "LUMA_STDDEV": "0.19",
             "CAPTURE_TOOL": "import", "CLOCK_RECT": "352x1072+1568+4",
             "CLOCK_RECT_FROM": "computed",
             "CLOCK_SOURCE": "ocr_clock.py"},
            key="j", action="press 'j' -- step south")
        path = self.sidecar(json.dumps(row) + "\n")
        rows = timeline.load_observations(path, root=self.directory)
        self.assertEqual(rows[1]["date"], "Thursday, Mar 8")
        self.assertLessEqual(
            set(row) - timeline.OBSERVATION_KNOWN_FIELDS, set(),
            msg=("every column the writer produces has a declared type "
                 "in the reader's copy of the schema"))

    def test_blank_lines_are_tolerated(self):
        path = self.sidecar(
            '\n{"frame": 1, "date": "Thursday, Mar 8", '
            '"date_status": "read"}\n\n')
        self.assertEqual(sorted(self.load(path)), [1])

    def test_a_malformed_line_is_refused_outright(self):
        for text in ('{"frame": 1, "date": "x"\n',
                     '[1, 2, 3]\n',
                     '{"date": "Thursday, Mar 8"}\n',
                     '{"frame": "1", "date": "x"}\n',
                     '{"frame": true, "date": "x"}\n'):
            with self.subTest(text=text):
                with self.assertRaises(timeline.TimelineError):
                    timeline.load_observations(self.sidecar(text))

    def test_a_row_whose_status_is_not_read_carries_no_date(self):
        rows = {1: {"frame": 1, "date": "Thursday, Mar 8",
                    "date_status": "unreadable"}}
        document = timeline.build_timeline(make_rows(["08:00:00"]), rows)
        self.assertIsNone(document["frames"][0]["ingame_date"])

    def test_the_telemetry_no_longer_outranks_the_audit(self):
        """NEITHER RECORD IS PREFERRED, which was the defect.

        build_timeline() used to take the telemetry's date and consult
        the audit only where the telemetry had none -- so the record with
        no unanimity rule and no digest binding decided, and one stale
        telemetry row could override unanimous, digest-bound audit
        evidence and move a day of game time.  The two records read the
        same photographs: agreement corroborates, and a contradiction
        leaves the frame's date unobserved rather than settled by which
        file it came out of.
        """
        telemetry = {
            1: {"frame": 1, "date": "Thursday, Mar 8",
                "date_status": "read"},
            2: {"frame": 2, "date": "Friday, Mar 9",
                "date_status": "read"},
        }
        agreeing = timeline.build_timeline(
            make_rows(["08:00:00", "08:00:01"]), telemetry,
            ["Thursday, Mar 8", "Friday, Mar 9"])
        self.assertEqual(
            [entry["ingame_date"] for entry in agreeing["frames"]],
            ["Thursday, Mar 8", "Friday, Mar 9"],
            msg="two records that agree are two readings of one screen")
        disputed = timeline.build_timeline(
            make_rows(["08:00:00", "08:00:01"]), telemetry,
            ["Thursday, Mar 8", "Saturday, Mar 10"])
        self.assertEqual(
            [entry["ingame_date"] for entry in disputed["frames"]],
            ["Thursday, Mar 8", None],
            msg=("frame 2's records contradict each other, so its date "
                 "is UNOBSERVED -- not the telemetry's reading because "
                 "the telemetry used to be preferred"))
        self.assertEqual(
            disputed["frames"][1]["date_agreement"],
            timeline.AGREE_UNVERIFIED,
            msg=("an unobserved date is unverified rather than "
                 "confirmed; nothing was established for that frame"))

    def test_the_audit_alone_still_settles_a_day(self):
        """A gap in one record is not a gap in the evidence."""
        telemetry = {1: {"frame": 1, "date": None,
                         "date_status": "unreadable"}}
        document = timeline.build_timeline(
            make_rows(["08:00:00"]), telemetry, ["Thursday, Mar 8"])
        self.assertEqual(document["frames"][0]["ingame_date"],
                         "Thursday, Mar 8")

    def test_the_default_path_is_the_documented_one(self):
        parts = timeline.OBSERVATIONS_REL_PARTS
        self.assertEqual(
            parts, ("build", "observations.jsonl"),
            msg=("the sidecar lives under playthrough/build/, outside "
                 "frames/ and distinct from the manifest"))
        self.assertTrue(
            timeline.default_observations_path().endswith(
                os.path.join(*parts)))

    def test_the_manifest_schema_is_untouched_by_the_sidecar(self):
        # The date is carried in the sidecar precisely so the manifest
        # stays exactly the six declared fields.
        self.assertEqual(
            len(MANIFEST_FIELDS), 6,
            msg="the manifest schema is six fields and stays six")
        self.assertNotIn("date", MANIFEST_FIELDS)
        self.assertNotIn("ingame_date", MANIFEST_FIELDS)
        self.assertEqual(
            list(make_row(1, "08:00:00")), list(MANIFEST_FIELDS),
            msg=("a row still carries exactly the six fields in the "
                 "declared order; the date lives beside it, not in it"))


class TestCueArithmetic(unittest.TestCase):
    """The cue walk, and the transition second charged to video time.

    This is where captions either stay on the picture or drift off it.
    A generator that walked the frame durations without charging the
    inserted transition seconds would be correct at the start of the
    film and increasingly wrong by the end -- correct enough to look
    plausible, which is what makes it dangerous.
    """

    def test_each_cue_is_exactly_its_frames_duration_long(self):
        for index, entry in enumerate(
                reference_document()["frames"], start=1):
            with self.subTest(frame=index):
                self.assertAlmostEqual(
                    entry["cue_end"] - entry["cue_start"],
                    entry["duration"], places=PLACES,
                    msg=("frame %d occupies [cue_start, cue_start + "
                         "duration); its window is the wrong length"
                         % index))

    def test_the_first_cue_starts_at_zero(self):
        self.assertEqual(
            reference_document()["frames"][0]["cue_start"], 0.0,
            msg="a timeline starts at zero, not at an offset")

    def test_the_transition_second_is_charged_to_video_time(self):
        frames = reference_document()["frames"]
        for index in range(len(frames) - 1):
            here = frames[index]
            following = frames[index + 1]
            gap = (timeline.TRANSITION
                   if here["transition_after"] else 0.0)
            with self.subTest(frame=index + 1):
                self.assertAlmostEqual(
                    following["cue_start"], here["cue_end"] + gap,
                    places=PLACES,
                    msg=("frame %d ends at %r and is followed by %rs "
                         "of transition, so frame %d must start at %r"
                         % (index + 1, here["cue_end"], gap,
                            index + 2, here["cue_end"] + gap)))

    def test_the_cue_after_a_transition_starts_at_17_250(self):
        # THE regression this file exists for.  The frame before this
        # one ends at 16.25s; one second of fade-out, title card and
        # fade-in is inserted; so this cue opens at 17.25s.  A cue
        # walk that forgot the insert would put it at 16.25s and every
        # later caption would be a second early, then two, then three.
        document = reference_document()
        previous = document["frames"][FIRST_POST_TRANSITION - 1]
        entry = document["frames"][FIRST_POST_TRANSITION]
        self.assertIs(
            previous["transition_after"], True,
            msg=("the frame before the one under test must be the "
                 "flagged frame, or this test proves nothing"))
        self.assertEqual(
            timeline.format_srt_timecode(previous["cue_end"]),
            "00:00:16,250",
            msg="the flagged frame's window still closes at 16.250")
        self.assertEqual(
            timeline.format_srt_timecode(entry["cue_start"]),
            "00:00:17,250",
            msg=("the cue after a transition MUST begin at "
                 "00:00:17,250 and not at 00:00:16,250; the inserted "
                 "second is charged to video time, and a walk that "
                 "skipped it drifts further out of sync with every "
                 "transition in the film"))

    def test_every_cue_window_matches_the_measured_walk(self):
        document = reference_document()
        windows = list(zip(field(document, "cue_start"),
                           field(document, "cue_end")))
        self.assertEqual(
            windows, [tuple(pair) for pair in REFERENCE_CUES],
            msg="the cue walk of the reference sequence has changed")

    def test_no_cue_overlaps_its_neighbour(self):
        frames = reference_document()["frames"]
        for index in range(len(frames) - 1):
            with self.subTest(frame=index + 1):
                self.assertGreaterEqual(
                    frames[index + 1]["cue_start"],
                    frames[index]["cue_end"],
                    msg=("frame %d opens before frame %d has closed; "
                         "two captions would be on screen at once"
                         % (index + 2, index + 1)))

    def test_no_cue_is_empty_or_negative(self):
        for index, entry in enumerate(
                reference_document()["frames"], start=1):
            with self.subTest(frame=index):
                self.assertGreater(
                    entry["cue_end"], entry["cue_start"],
                    msg=("frame %d has an empty or reversed window; "
                         "the floor guarantees at least 250ms"
                         % index))
                self.assertGreaterEqual(
                    entry["cue_end"] - entry["cue_start"],
                    timeline.FLOOR,
                    msg="frame %d is shorter than the floor" % index)

    def test_a_transition_on_every_frame_is_charged_every_time(self):
        # Not a shape the pipeline produces -- the last frame is never
        # flagged -- but the cue walk is a pure function and the
        # accounting has to hold for any input it is handed.
        durations = [1.0, 1.0, 1.0]
        flags = [True, True, True]
        windows, total = timeline.cue_windows(durations, flags)
        self.assertEqual(
            windows, [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)],
            msg="one transition second between every pair of windows")
        self.assertAlmostEqual(
            total, 6.0, places=PLACES,
            msg="three seconds of frames plus three of transitions")

    def test_no_transition_means_contiguous_windows(self):
        windows, total = timeline.cue_windows(
            [0.25, 0.25, 0.25], [False, False, False])
        self.assertEqual(
            windows, [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75)],
            msg="without a transition each cue abuts the next")
        self.assertAlmostEqual(
            total, 0.75, places=PLACES,
            msg="the cursor total is the sum of the durations")

    def test_cue_windows_refuses_mismatched_inputs(self):
        with self.assertRaises(
                timeline.TimelineError,
                msg=("every frame has exactly one duration and one "
                     "flag; a mismatch must be refused, not zipped "
                     "short")):
            timeline.cue_windows([1.0, 2.0], [False])

    def test_an_empty_walk_produces_nothing(self):
        windows, total = timeline.cue_windows([], [])
        self.assertEqual(windows, [],
                         msg="no frames means no cues")
        self.assertEqual(total, 0.0,
                         msg="no frames means no running time")


class TestTimelineInvariant(unittest.TestCase):
    """sum(durations) + sum(transitions) == total == final cue end.

    Three quantities computed by three different routes -- fsum over
    the durations plus a count of the flags, the cue walk's cursor, and
    the last window's end.  They are compared rather than derived from
    one another, so an error in any one of the three shows up here
    instead of pacing the film and the captions from the same bad
    number and looking consistent while doing it.
    """

    def test_the_measured_reference_totals(self):
        document = reference_document()
        self.assertAlmostEqual(
            document["total_duration"], REFERENCE_TOTAL_DURATION,
            places=PLACES,
            msg="the reference frames sum to 32.500s of video")
        self.assertAlmostEqual(
            document["total_transition"], REFERENCE_TOTAL_TRANSITION,
            places=PLACES,
            msg="two transitions of one second is 2.000s")
        self.assertAlmostEqual(
            document["total"], REFERENCE_TOTAL, places=PLACES,
            msg="32.500 + 2.000 is 34.500s of film")

    def test_the_three_quantities_agree(self):
        document = reference_document()
        left = document["total_duration"] + document["total_transition"]
        self.assertAlmostEqual(
            left, document["total"], places=PLACES,
            msg=("sum(durations) + sum(transitions) must equal the "
                 "cursor total"))
        self.assertAlmostEqual(
            document["total"], document["final_cue_end"],
            places=PLACES,
            msg=("the cursor total must equal the final cue end, or "
                 "the captions and the container disagree"))
        self.assertAlmostEqual(
            document["final_cue_end"],
            document["frames"][-1]["cue_end"], places=PLACES,
            msg="final_cue_end must be the last window's end")

    def test_the_invariant_computed_independently(self):
        durations = list(REFERENCE_DURATIONS)
        flags = list(REFERENCE_TRANSITIONS)
        windows, cursor = timeline.cue_windows(durations, flags)
        self.assertAlmostEqual(
            timeline.timeline_total(durations, flags), cursor,
            places=PLACES,
            msg=("timeline_total() and the cue walk compute the same "
                 "quantity by different routes and must agree"))
        self.assertAlmostEqual(
            cursor, windows[-1][1], places=PLACES,
            msg="the cursor ends where the last window ends")
        self.assertAlmostEqual(
            cursor, REFERENCE_TOTAL, places=PLACES,
            msg="the measured total of the reference sequence")

    def test_the_invariant_holds_with_no_transition(self):
        document = build(("08:00:00", "08:00:01", "08:00:02"))
        self.assertEqual(
            document["transition_count"], 0,
            msg="one-second steps never engage the ceiling")
        self.assertAlmostEqual(
            document["total_transition"], 0.0, places=PLACES,
            msg="no transition means no transition seconds")
        self.assertAlmostEqual(
            document["total"], document["total_duration"],
            places=PLACES,
            msg="with no insert the total is the durations alone")
        self.assertAlmostEqual(
            document["total"], document["final_cue_end"],
            places=PLACES,
            msg="the invariant holds without a transition too")

    def test_the_invariant_holds_for_a_single_frame(self):
        document = build(("08:00:00",))
        self.assertEqual(
            document["frame_count"], 1,
            msg="one keystroke, one frame")
        self.assertAlmostEqual(
            document["total"], timeline.FLOOR, places=PLACES,
            msg="a one-frame film runs for the floor")
        self.assertAlmostEqual(
            document["final_cue_end"], timeline.FLOOR, places=PLACES,
            msg="its single cue ends at the floor")

    def test_the_invariant_holds_for_an_empty_session(self):
        document = timeline.build_timeline([])
        self.assertEqual(
            document["frame_count"], 0,
            msg="no rows means no frames")
        self.assertEqual(
            document["total"], 0.0,
            msg="an empty timeline has no running time")
        self.assertEqual(
            document["final_cue_end"], 0.0,
            msg="an empty timeline has no final cue")
        self.assertEqual(
            timeline.validate_timeline(document), [],
            msg="an empty timeline is still a consistent one")

    def test_the_transition_count_matches_the_flags(self):
        document = reference_document()
        self.assertEqual(
            document["transition_count"], REFERENCE_TRANSITION_COUNT,
            msg="two frames of the reference sequence are flagged")
        self.assertEqual(
            document["transition_count"],
            sum(1 for flag in field(document, "transition_after")
                if flag),
            msg=("the count in the document must equal the number of "
                 "flagged entries; the renderer materialises one "
                 "group of transition images per flag"))


class TestSrtTimecodeFormatter(unittest.TestCase):
    """SubRip timecodes: HH:MM:SS,mmm with a comma."""

    def test_the_verified_round_trip(self):
        self.assertEqual(
            timeline.format_srt_timecode(3661.5), "01:01:01,500",
            msg=("3661.5s is one hour, one minute, one and a half "
                 "seconds: 01:01:01,500 exactly"))

    def test_the_separator_is_a_comma_not_a_full_stop(self):
        timecode = timeline.format_srt_timecode(3661.5)
        self.assertIn(
            ",", timecode,
            msg=("SubRip separates the milliseconds with a comma; a "
                 "full stop there is WebVTT and some players ignore "
                 "the file outright"))
        self.assertNotIn(
            ".", timecode,
            msg="a SubRip timecode carries no full stop at all")

    def test_hours_are_zero_padded_when_there_are_none(self):
        self.assertEqual(
            timeline.format_srt_timecode(0.0), "00:00:00,000",
            msg=("the hours field is two digits even at zero, so "
                 "every cue in the file has the same width"))

    def test_the_floor_formats_at_millisecond_resolution(self):
        self.assertEqual(
            timeline.format_srt_timecode(0.25), "00:00:00,250",
            msg="a quarter second is 250 milliseconds")

    def test_the_reference_total_formats_exactly(self):
        self.assertEqual(
            timeline.format_srt_timecode(REFERENCE_TOTAL),
            "00:00:34,500",
            msg="the reference film runs 34.5s")

    def test_rounding_carries_deterministically(self):
        self.assertEqual(
            timeline.format_srt_timecode(59.999), "00:00:59,999",
            msg="a millisecond below the minute stays in the minute")
        self.assertEqual(
            timeline.format_srt_timecode(59.9995), "00:01:00,000",
            msg=("half a millisecond rounds up and carries into the "
                 "minutes field; the same input must always give the "
                 "same timecode, on every platform"))

    def test_a_long_film_widens_rather_than_truncates(self):
        self.assertEqual(
            timeline.format_srt_timecode(359999.999), "99:59:59,999",
            msg="just under a hundred hours still fits two digits")
        self.assertEqual(
            timeline.format_srt_timecode(360000.0), "100:00:00,000",
            msg=("beyond a hundred hours the field widens rather than "
                 "wrapping to zero, which SubRip tolerates"))

    def test_whole_minutes_and_hours(self):
        self.assertEqual(timeline.format_srt_timecode(60.0),
                         "00:01:00,000")
        self.assertEqual(timeline.format_srt_timecode(3600.0),
                         "01:00:00,000")
        self.assertEqual(timeline.format_srt_timecode(3599.999),
                         "00:59:59,999")

    def test_an_integer_is_accepted(self):
        self.assertEqual(
            timeline.format_srt_timecode(17), "00:00:17,000",
            msg="a whole number of seconds needs no decimal point")

    def test_negative_time_is_refused(self):
        with self.assertRaises(
                timeline.TimelineError,
                msg=("negative time has no meaning in a caption file "
                     "and must be refused, not wrapped")):
            timeline.format_srt_timecode(-1.0)

    def test_a_non_finite_timecode_is_refused(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(timeline.TimelineError):
                    timeline.format_srt_timecode(value)

    def test_a_non_numeric_timecode_is_refused(self):
        for value in ("17", None, [], True):
            with self.subTest(value=value):
                with self.assertRaises(
                        timeline.TimelineError,
                        msg=("a timecode needs a number of seconds; "
                             "%r must be refused" % (value,))):
                    timeline.format_srt_timecode(value)

    def test_every_reference_cue_formats_to_a_full_width_timecode(self):
        for index, entry in enumerate(
                reference_document()["frames"], start=1):
            for name in ("cue_start", "cue_end"):
                with self.subTest(frame=index, field=name):
                    timecode = timeline.format_srt_timecode(
                        entry[name])
                    self.assertEqual(
                        len(timecode), 12,
                        msg=("frame %d %s formatted to %r, which is "
                             "not HH:MM:SS,mmm"
                             % (index, name, timecode)))
                    self.assertEqual(
                        timecode[2], ":",
                        msg="the hours field must be two digits")
                    self.assertEqual(
                        timecode[8], ",",
                        msg="the milliseconds follow a comma")

    def test_cue_timecodes_never_run_backwards(self):
        previous = "00:00:00,000"
        for entry in reference_document()["frames"]:
            for name in ("cue_start", "cue_end"):
                timecode = timeline.format_srt_timecode(entry[name])
                self.assertGreaterEqual(
                    timecode, previous,
                    msg=("cue timecodes are lexically ordered because "
                         "they are fixed width; %r follows %r"
                         % (timecode, previous)))
                previous = timecode


class TestReferenceSequence(unittest.TestCase):
    """The whole computation, end to end and in memory."""

    def test_the_fixture_carries_one_date_line_per_reading(self):
        """The headline fixture must be the shape it claims to be.

        REFERENCE_DATES once held eight values for seven readings, and
        nothing said so: absolutise_clocks() ignored the surplus, every
        assertion below still passed, and the fixture that documents
        one-date-per-frame cardinality did not have it.  A published
        table nobody checks the shape of is a table that can drift, so
        the shape is asserted here alongside the numbers it produces --
        and every derived expectation is held to the same count, since
        a table with the wrong number of rows would otherwise assert
        the wrong thing about the right sequence.
        """
        self.assertEqual(
            len(REFERENCE_DATES), len(REFERENCE_CLOCKS),
            msg=("the date evidence is parallel to the readings: one "
                 "sidebar date line per captured frame"))
        for name, values in (
                ("REFERENCE_RAW_DELTAS", REFERENCE_RAW_DELTAS),
                ("REFERENCE_DURATIONS", REFERENCE_DURATIONS),
                ("REFERENCE_TRANSITIONS", REFERENCE_TRANSITIONS),
                ("REFERENCE_CUES", REFERENCE_CUES)):
            with self.subTest(table=name):
                self.assertEqual(
                    len(values), len(REFERENCE_CLOCKS),
                    msg="%s must have one row per reading" % name)

    def test_one_entry_per_row_nothing_dropped(self):
        document = reference_document()
        self.assertEqual(
            document["frame_count"], len(REFERENCE_CLOCKS),
            msg=("one keystroke made one capture and one row, so the "
                 "timeline must carry one entry per row"))
        self.assertEqual(
            len(document["frames"]), len(REFERENCE_CLOCKS),
            msg="the frames array length must equal the row count")

    def test_the_measured_raw_deltas(self):
        self.assertEqual(
            field(reference_document(), "raw_delta"),
            list(REFERENCE_RAW_DELTAS),
            msg=("the raw deltas of the reference sequence, measured "
                 "from the module's own output"))

    def test_the_measured_durations(self):
        self.assertEqual(
            field(reference_document(), "duration"),
            list(REFERENCE_DURATIONS),
            msg="the clamped durations of the reference sequence")

    def test_the_measured_transition_flags(self):
        self.assertEqual(
            field(reference_document(), "transition_after"),
            list(REFERENCE_TRANSITIONS),
            msg=("only the 300s wait and the 56 359s sleep exceed the "
                 "ceiling, so only those two frames are flagged"))

    def test_the_measured_absolute_clocks(self):
        # 86398 is 23:59:58 on day 0; 86404 is 00:00:04 on day 1, which
        # is 86400 + 4 -- the day counter advancing is what turns the
        # crossing of midnight into a POSITIVE six-second step.
        self.assertEqual(
            field(reference_document(), "clock_seconds"),
            [29733, 29733, 29734, 29739, 30039, 86398, 86404],
            msg=("the absolutised readings, with the day counter "
                 "advancing once at midnight"))

    def test_the_reading_is_recorded_verbatim(self):
        self.assertEqual(
            field(reference_document(), "ingame_clock"),
            list(REFERENCE_CLOCKS),
            msg=("the clock column is the reading exactly as the "
                 "manifest recorded it; it is never rewritten"))

    def test_the_frame_indices_run_from_one(self):
        self.assertEqual(
            field(reference_document(), "frame"),
            list(range(1, len(REFERENCE_CLOCKS) + 1)),
            msg="indices run 1..n with no gap, repeat or reordering")

    def test_the_capture_paths_are_repository_relative(self):
        self.assertEqual(
            field(reference_document(), "file"),
            [FRAME_FILE_FORMAT % index
             for index in range(1, len(REFERENCE_CLOCKS) + 1)],
            msg=("the file column must match the frames directory so "
                 "the concat list and the manifest cannot disagree"))

    def test_the_in_character_text_is_copied_untouched(self):
        for entry in reference_document()["frames"]:
            with self.subTest(frame=entry["frame"]):
                self.assertEqual(
                    entry["action"], "step",
                    msg="action is carried through verbatim")
                self.assertEqual(
                    entry["commentary"], "I keep moving.",
                    msg=("commentary belongs to the in-character "
                         "record and is never edited or annotated"))

    def test_the_document_declares_the_constants_it_used(self):
        document = reference_document()
        self.assertEqual(document["version"], timeline.TIMELINE_VERSION)
        self.assertEqual(document["floor"], timeline.FLOOR)
        self.assertEqual(document["ceil"], timeline.CEIL)
        self.assertEqual(
            document["transition"], timeline.TRANSITION,
            msg=("the clamp travels with the data so a reader can "
                 "check every duration against it"))

    def test_the_field_order_is_the_declared_order(self):
        document = reference_document()
        self.assertEqual(
            tuple(document), timeline.DOCUMENT_FIELDS,
            msg="the top-level keys are written in a fixed order")
        for entry in document["frames"]:
            with self.subTest(frame=entry["frame"]):
                self.assertEqual(
                    tuple(entry), timeline.ENTRY_FIELDS,
                    msg="every entry carries the fields in order")

    def test_the_reference_rows_pass_the_manifest_schema_gate(self):
        self.assertEqual(
            timeline.manifest_row_problems(
                make_rows(REFERENCE_CLOCKS)),
            [],
            msg=("the rows this suite builds must be the six declared "
                 "fields in the declared order, or the tests would be "
                 "asserting against a shape the pipeline never sees"))

    def test_the_reference_document_passes_its_own_validation(self):
        self.assertEqual(
            timeline.validate_timeline(reference_document()), [],
            msg=("every invariant the module checks must hold on the "
                 "reference sequence"))

    def test_the_compute_alias_is_the_builder(self):
        self.assertIs(
            timeline.compute_timeline, timeline.build_timeline,
            msg="the alias must not drift from the function")

    def test_a_malformed_row_is_refused(self):
        for rows, label in (
                ([1], "a row that is not an object"),
                ([{"frame": 0}], "a frame index below one"),
                ([{"frame": "1"}], "a frame index that is not an int"),
                ([{"frame": True}], "a boolean frame index"),
                ([{"action": 1}], "an action that is not text"),
                ([{"file": 1}], "a file that is not text"),
                ([{"real_ts": 1}], "a real_ts that is not text")):
            with self.subTest(label=label):
                with self.assertRaises(
                        timeline.TimelineError,
                        msg=("%s must be refused rather than paced "
                             "around" % label)):
                    timeline.build_timeline(rows)


class TestAnOrdinaryStepAfterWaking(unittest.TestCase):
    """One more one-second step, on its OWN sequence.

    A survivor who wakes takes an ordinary step before doing anything
    else, so the step deserves coverage -- but it does not belong in the
    canonical fixture, because adding a row there changes every total in
    it.  So it lives here on a sequence of its own, and its constants are
    DERIVED from the reference ones rather than restated: the extra frame
    contributes its own second, turns the previously final floored frame
    into a full second, and adds no transition.  Each sequence's totals
    are true only of itself, which is why the two are kept apart.
    """

    # The reference readings plus one more second on the clock, so the
    # sixth frame's rollover step is unchanged and the seventh becomes an
    # ordinary one-second step instead of the final frame.
    CLOCKS = REFERENCE_CLOCKS + ("00:00:05",)

    EXPECTED_RAW_DELTAS = (0.0, 1.0, 5.0, 300.0, 56359.0, 6.0, 1.0, 0.0)
    EXPECTED_DURATIONS = (0.25, 1.0, 5.0, 10.0, 10.0, 6.0, 1.0, 0.25)
    EXPECTED_TOTAL_DURATION = 33.5
    EXPECTED_TOTAL = 35.5

    def setUp(self):
        self.document = build(self.CLOCKS)

    def test_the_extra_reading_is_one_more_frame(self):
        self.assertEqual(
            self.document["frame_count"], len(REFERENCE_CLOCKS) + 1,
            msg=("one reading is one frame, always; the post-wake step "
                 "is a frame of its own and merges with nothing"))

    def test_the_step_is_a_one_second_frame(self):
        self.assertEqual(
            field(self.document, "raw_delta"),
            list(self.EXPECTED_RAW_DELTAS),
            msg="an ordinary step after waking advances one second")
        self.assertEqual(
            field(self.document, "duration"),
            list(self.EXPECTED_DURATIONS),
            msg=("the step passes through the clamp untouched, and the "
                 "new final frame takes the floor"))

    def test_it_adds_no_transition_of_its_own(self):
        self.assertEqual(
            self.document["transition_count"],
            REFERENCE_TRANSITION_COUNT,
            msg=("a one-second step is nowhere near the ceiling, so "
                 "the transition count is still the reference's two"))

    def test_the_totals_are_the_reference_plus_one_second(self):
        self.assertAlmostEqual(
            self.document["total_duration"],
            self.EXPECTED_TOTAL_DURATION, places=PLACES,
            msg=("32.500 for the reference rows plus 1.000 for the "
                 "step is 33.500s of frames"))
        self.assertAlmostEqual(
            self.document["total_transition"],
            REFERENCE_TOTAL_TRANSITION, places=PLACES,
            msg="the same two transition seconds as the reference")
        self.assertAlmostEqual(
            self.document["total"], self.EXPECTED_TOTAL, places=PLACES,
            msg="33.500 + 2.000 is 35.500s of film")
        self.assertAlmostEqual(
            self.document["total_duration"],
            REFERENCE_TOTAL_DURATION + 1.0, places=PLACES,
            msg=("stated as a relationship as well as a literal, so "
                 "the two fixtures cannot drift apart silently"))

    def test_the_invariant_still_holds(self):
        left = (self.document["total_duration"] +
                self.document["total_transition"])
        self.assertAlmostEqual(
            left, self.document["total"], places=PLACES,
            msg="sum(durations) + sum(transitions) == total")
        self.assertAlmostEqual(
            self.document["total"], self.document["final_cue_end"],
            places=PLACES,
            msg="total == final cue end")

    def test_the_transition_second_is_still_charged(self):
        entry = self.document["frames"][FIRST_POST_TRANSITION]
        self.assertEqual(
            timeline.format_srt_timecode(entry["cue_start"]),
            "00:00:17,250",
            msg=("the post-transition cue does not move: an extra "
                 "frame at the END cannot shift a window before it"))

    def test_the_document_passes_its_own_validation(self):
        self.assertEqual(
            timeline.validate_timeline(self.document), [],
            msg="the extended sequence must be internally consistent")


class TestTheSuiteCatchesABrokenAlgorithm(unittest.TestCase):
    """Prove this suite can FAIL, and that it does not mutate its input.

    A green suite is evidence of nothing until it has been shown to go
    red for the right reasons.  These tests do to the production logic
    exactly what a careless edit would do, and assert that the canonical
    expectations stop holding:

      * the transition predicate relaxed from `>` to `>=`, which is the
        single easiest mistake to make in this feature -- a raw delta of
        exactly CEIL would earn a transition it must not have;
      * the transition second dropped from the cue walk, which is the
        defect that puts the captions progressively out of step with the
        picture and is invisible until the end of the film.

    The substitution is done by rebinding the module attribute and
    restoring it in tearDown through addCleanup, so a failure part way
    through cannot leave a mutated module behind for the tests that run
    after it.  Nothing on disk is touched and no file is edited: the
    "break it and watch it fail" check is a permanent part of the suite
    rather than something an author has to remember to do by hand and
    remember to undo.

    The last test here asserts the complementary property -- that
    build_timeline does not mutate the rows it is given.  Manifest rows
    are the committed record of a session; a builder that quietly
    repaired one would rewrite evidence, and a caller that reused its
    rows afterwards would be holding something it never wrote.
    """

    def substitute(self, name, replacement):
        """Rebind timeline.<name>, restoring it after the test."""
        original = getattr(timeline, name)
        self.addCleanup(setattr, timeline, name, original)
        setattr(timeline, name, replacement)
        return original

    def test_relaxing_the_transition_predicate_is_caught(self):
        # `>=` instead of `>`: a delta of exactly CEIL becomes a
        # transition.  The reference sequence has no delta at exactly
        # CEIL, so the flags below are unchanged -- which is why the
        # assertion is made on the boundary case the requirements state
        # explicitly, and then on a sequence that contains it.
        self.substitute(
            "is_transition",
            lambda raw: timeline.round_seconds(raw) >= timeline.CEIL)
        self.assertTrue(
            timeline.is_transition(timeline.CEIL),
            msg="the mutant must really be installed for this to mean "
                "anything")
        # 08:15:33 -> 08:15:43 is exactly CEIL seconds.
        document = build(("08:15:33", "08:15:43", "08:15:43"))
        self.assertEqual(
            field(document, "transition_after"), [True, False, False],
            msg=("with the mutant installed the boundary frame IS "
                 "flagged, which is exactly the wrong behaviour"))
        self.assertNotEqual(
            document["total_transition"], 0.0,
            msg=("and the mutant therefore charges a transition "
                 "second that the requirements forbid"))

    def test_the_boundary_assertion_fails_under_the_mutant(self):
        # The same mutation, checked the way it matters: the assertion
        # this suite makes about the boundary must stop holding.  A
        # nested assertRaises around the real expectation is the only
        # honest way to say "this test would fail".
        self.substitute(
            "is_transition",
            lambda raw: timeline.round_seconds(raw) >= timeline.CEIL)
        with self.assertRaises(
                AssertionError,
                msg=("the canonical expectation -- a raw delta of "
                     "exactly CEIL is NOT a transition -- must fail "
                     "while the predicate is relaxed; if it passes, "
                     "this suite is not testing the predicate at "
                     "all")):
            self.assertFalse(timeline.is_transition(timeline.CEIL))

    def test_dropping_the_transition_second_is_caught(self):
        # A cue walk that advances only by the duration.  Same signature,
        # same return shape, one missing line -- the defect the shared
        # timeline exists to prevent.
        def walk_without_charging(durations, flags):
            cursor = 0.0
            windows = []
            for duration in durations:
                start = timeline.round_seconds(cursor)
                end = timeline.round_seconds(start + duration)
                windows.append((start, end))
                cursor = end
            return windows, timeline.round_seconds(cursor)

        self.substitute("cue_windows", walk_without_charging)
        document = reference_document()
        self.assertNotEqual(
            [tuple(pair) for pair in zip(field(document, "cue_start"),
                                         field(document, "cue_end"))],
            [tuple(pair) for pair in REFERENCE_CUES],
            msg=("the canonical cue windows must NOT survive a walk "
                 "that forgets the transition second"))
        self.assertAlmostEqual(
            document["final_cue_end"],
            REFERENCE_TOTAL - REFERENCE_TOTAL_TRANSITION,
            places=PLACES,
            msg=("the mutant ends two seconds short -- 32.500 rather "
                 "than 34.500 -- which is the caption drift itself"))
        # WHICH of the three quantities diverges is the whole value of
        # computing them by three different routes.  `total` and
        # `final_cue_end` both come out of the walk, so the mutant keeps
        # them agreeing with each other.  It is the independently
        # computed side, sum(durations) + sum(transitions), that no
        # longer matches -- which is why the invariant is checked against
        # a figure the walk did not produce.
        self.assertAlmostEqual(
            document["final_cue_end"], document["total"],
            places=PLACES,
            msg=("the mutant is self-consistent -- both of these come "
                 "from the walk -- which is why a self-consistency "
                 "check alone would pass it"))
        independent = (document["total_duration"] +
                       document["total_transition"])
        self.assertNotAlmostEqual(
            independent, document["total"], places=PLACES,
            msg=("the invariant's independently computed side, 32.500 "
                 "+ 2.000, no longer equals the walk's 32.500; that "
                 "disagreement is what the check exists to surface"))
        self.assertNotEqual(
            timeline.validate_timeline(document), [],
            msg=("validate_timeline must REPORT the mutant's output; a "
                 "checker that passed it would be worse than none"))

    def test_the_post_transition_cue_moves_under_the_mutant(self):
        # The same assertion from the other side: the post-transition
        # cue must move a whole TRANSITION earlier once the inserted
        # second is not charged.
        def walk_without_charging(durations, flags):
            cursor = 0.0
            windows = []
            for duration in durations:
                start = timeline.round_seconds(cursor)
                end = timeline.round_seconds(start + duration)
                windows.append((start, end))
                cursor = end
            return windows, timeline.round_seconds(cursor)

        self.substitute("cue_windows", walk_without_charging)
        entry = reference_document()["frames"][FIRST_POST_TRANSITION]
        self.assertEqual(
            timeline.format_srt_timecode(entry["cue_start"]),
            "00:00:16,250",
            msg=("the mutant produces exactly the wrong timecode the "
                 "canonical test asserts against, so that test is "
                 "genuinely load-bearing"))

    def test_the_canonical_expectations_hold_once_restored(self):
        # addCleanup restores the module after each test above; this one
        # runs the canonical checks again so a mutation that leaked
        # would be caught here rather than in some unrelated test.
        self.assertFalse(
            timeline.is_transition(timeline.CEIL),
            msg="a raw delta of exactly CEIL is not a transition")
        document = reference_document()
        self.assertEqual(
            [tuple(pair) for pair in zip(field(document, "cue_start"),
                                         field(document, "cue_end"))],
            [tuple(pair) for pair in REFERENCE_CUES],
            msg="the real walk produces the canonical cue windows")
        self.assertAlmostEqual(
            document["total"], REFERENCE_TOTAL, places=PLACES,
            msg="and the canonical total")

    def test_build_timeline_does_not_mutate_its_input_rows(self):
        rows = make_rows(REFERENCE_CLOCKS)
        before = copy.deepcopy(rows)
        document = timeline.build_timeline(rows)
        self.assertEqual(
            rows, before,
            msg=("build_timeline must leave the manifest rows exactly "
                 "as it received them: they are the committed record "
                 "of the session, and a builder that repaired one "
                 "would be rewriting evidence"))
        # Deep, not shallow: a mutation of a nested value would not
        # change the top-level list at all.
        for index, (now, then) in enumerate(zip(rows, before)):
            self.assertEqual(
                list(now), list(then),
                msg=("row %d must keep its keys, in order"
                     % (index + 1)))
            self.assertEqual(
                now, then,
                msg="row %d must keep every value" % (index + 1))
        self.assertIsNot(
            document["frames"][0], rows[0],
            msg=("an entry must be a NEW object rather than the input "
                 "row decorated in place, or a caller holding the rows "
                 "would find timing fields it never wrote"))

    def test_validate_timeline_does_not_mutate_the_document(self):
        document = reference_document()
        before = copy.deepcopy(document)
        self.assertEqual(
            timeline.validate_timeline(document), [],
            msg="the reference document is valid")
        self.assertEqual(
            document, before,
            msg=("a checker must observe and report, never repair: a "
                 "validator that fixed what it found would make the "
                 "artifact and the report disagree"))


class TestValidationFailsLoudly(unittest.TestCase):
    """validate_timeline() must catch a broken timeline, not tolerate it.

    A checker that passed everything would be worse than no checker,
    because it would manufacture confidence.  Every test here breaks a
    known-good document in one specific way and insists the breakage is
    reported BY THE CHECK IT IS NAMED AFTER.

    WHY THE CODE, AND NOT MERELY "SOMETHING WAS REPORTED"
    Several invariants legitimately fail together.  A duration outside
    the clamp is also a duration that does not clamp its raw delta, and
    also gives a cue window of the wrong length -- one edit, three true
    complaints.  A test that asserted only a non-empty problem list
    would therefore stay green if the clamp-bounds check were deleted
    outright, because a neighbour would still report a symptom: the test
    would measure nothing while its name claimed a branch was protected.
    So every assertion below names the code of the check it means,
    timeline.timeline_problems() supplies it, and
    TestValidatorBranchIsolation proves each code has exactly one check
    site -- which is what makes a code-specific assertion a
    branch-specific one.
    """

    def setUp(self):
        self.document = reference_document()
        self.assertEqual(
            timeline.validate_timeline(self.document), [],
            msg=("the fixture must start clean, or these tests prove "
                 "nothing about what the checker catches"))

    def broken(self):
        """Return an independent copy of the good document."""
        return copy.deepcopy(self.document)

    def assertReported(self, document, label, code):
        """Assert that the check named by `code` reported a problem.

        Returns the whole list of :class:`timeline.Problem` records, so
        a caller can go on to assert something further about them.
        """
        problems = timeline.timeline_problems(document)
        self.assertTrue(
            problems,
            msg=("%s must be reported; validation returned no "
                 "problems at all" % label))
        self.assertIn(
            code, [problem.code for problem in problems],
            msg=("%s must be reported by the '%s' check itself, not "
                 "merely by some neighbouring invariant; got %r"
                 % (label, code,
                    [(problem.code, problem.message)
                     for problem in problems])))
        self.assertEqual(
            [problem.message for problem in problems],
            timeline.validate_timeline(document),
            msg=("the message-only view must carry exactly the same "
                 "complaints, in the same order, as the structured "
                 "one"))
        return problems

    def test_a_duration_below_the_floor_is_reported(self):
        document = self.broken()
        document["frames"][0]["duration"] = 0.1
        self.assertReported(document, "a duration under the floor",
                            timeline.PROBLEM_DURATION_CLAMP)

    def test_a_duration_above_the_ceiling_is_reported(self):
        document = self.broken()
        document["frames"][3]["duration"] = 11.0
        self.assertReported(document, "a duration over the ceiling",
                            timeline.PROBLEM_DURATION_CLAMP)

    def test_a_duration_that_does_not_clamp_its_delta_is_reported(self):
        document = self.broken()
        document["frames"][1]["duration"] = 2.0
        self.assertReported(
            document, "a duration that is not its raw delta clamped",
            timeline.PROBLEM_DURATION_NOT_CLAMPED)

    def test_a_missing_transition_flag_is_reported(self):
        # The strictly-greater boundary, from the other side: an entry
        # whose raw delta exceeded the ceiling but which is not flagged
        # would leave the film with a hard cut where a fade belongs.
        document = self.broken()
        self.assertIs(
            document["frames"][3]["transition_after"], True,
            msg="frame 4 is the flagged frame in the fixture")
        document["frames"][3]["transition_after"] = False
        self.assertReported(document, "a cleared transition flag",
                            timeline.PROBLEM_TRANSITION_FLAG)

    def test_a_spurious_transition_flag_is_reported(self):
        document = self.broken()
        document["frames"][1]["transition_after"] = True
        self.assertReported(
            document,
            "a transition flag on a frame under the ceiling",
            timeline.PROBLEM_TRANSITION_FLAG)

    def test_a_dropped_transition_second_is_reported(self):
        # The caption-drift bug, reproduced exactly: walk the cue
        # cursor over the durations without charging the inserted
        # transition seconds.  Every cue from the first transition
        # onwards is then a second early, and the final cue end no
        # longer matches the container's running time.
        document = self.broken()
        cursor = 0.0
        for entry in document["frames"]:
            entry["cue_start"] = cursor
            entry["cue_end"] = cursor + entry["duration"]
            cursor = entry["cue_end"]
        document["final_cue_end"] = document["frames"][-1]["cue_end"]
        problems = self.assertReported(
            document, "a cue walk that forgot the transition second",
            timeline.PROBLEM_CUE_START)
        self.assertAlmostEqual(
            document["final_cue_end"],
            REFERENCE_TOTAL - REFERENCE_TOTAL_TRANSITION,
            places=PLACES,
            msg=("the broken walk must end two seconds short, which "
                 "is precisely the drift the check exists to catch"))
        self.assertIn(
            timeline.PROBLEM_TOTAL_VS_CUE,
            [problem.code for problem in problems],
            msg=("the invariant total == final cue end must also "
                 "report the drift, because that is the property the "
                 "captions and the container are compared on"))

    def test_a_shifted_cue_is_reported(self):
        # The whole window moves, so its LENGTH is still right: that is
        # what leaves the per-entry checks satisfied and lets the
        # cross-entry contiguity check be the one that catches it.
        document = self.broken()
        document["frames"][2]["cue_start"] -= 1.0
        document["frames"][2]["cue_end"] -= 1.0
        self.assertReported(document, "a cue that starts too early",
                            timeline.PROBLEM_CUE_START)

    def test_a_cue_of_the_wrong_length_is_reported(self):
        document = self.broken()
        document["frames"][2]["cue_end"] += 0.5
        self.assertReported(document, "a cue window of the wrong size",
                            timeline.PROBLEM_CUE_LENGTH)

    def test_a_first_cue_that_does_not_start_at_zero_is_reported(self):
        document = self.broken()
        for entry in document["frames"]:
            entry["cue_start"] += 1.0
            entry["cue_end"] += 1.0
        self.assertReported(document, "a timeline that starts late",
                            timeline.PROBLEM_FIRST_CUE)

    def test_a_backwards_absolute_clock_is_reported(self):
        document = self.broken()
        document["frames"][5]["clock_seconds"] = 1
        self.assertReported(
            document, "an absolutised clock that runs backwards",
            timeline.PROBLEM_CLOCK_BACKWARDS)

    def test_a_negative_raw_delta_is_reported(self):
        document = self.broken()
        document["frames"][1]["raw_delta"] = -1.0
        self.assertReported(document, "a negative raw delta",
                            timeline.PROBLEM_RAW_DELTA_NEGATIVE)

    def test_a_flagged_final_frame_is_reported(self):
        # A flag on the last frame is only REACHABLE by the cross-entry
        # check when the entry is otherwise self-consistent, so the
        # delta and the duration are made to agree with the flag and
        # every derived number is recomputed.  The final frame then has
        # a delta it cannot have, which is the sibling check below, and
        # a transition nothing follows -- and this test insists on the
        # second of those specifically.
        document = self.broken()
        last = document["frames"][-1]
        last["raw_delta"] = 300.0
        last["duration"] = timeline.CEIL
        last["transition_after"] = True
        rederive_document(document)
        self.assertReported(
            document,
            "a transition after the last frame, which has no "
            "successor to transition into",
            timeline.PROBLEM_FINAL_FLAGGED)

    def test_a_final_frame_with_a_delta_is_reported(self):
        document = self.broken()
        last = document["frames"][-1]
        last["raw_delta"] = 5.0
        last["duration"] = 5.0
        rederive_document(document)
        self.assertReported(
            document, "a raw delta on the frame with no successor",
            timeline.PROBLEM_FINAL_DELTA)

    def test_a_reconciled_entry_without_a_reason_is_reported(self):
        document = self.broken()
        document["frames"][0]["reconciled"] = True
        self.assertReported(
            document, "a reconciled clock with no reason recorded",
            timeline.PROBLEM_RECONCILED_NO_REASON)

    def test_a_reason_without_the_flag_is_reported(self):
        document = self.broken()
        document["frames"][0]["reconciled_reason"] = "clock-missing"
        self.assertReported(
            document, "a reason recorded on an unflagged entry",
            timeline.PROBLEM_REASON_NOT_RECONCILED)

    def test_a_non_boolean_reconciled_flag_is_reported(self):
        # The flag is what says a reading was carried rather than read,
        # so a truthy string in its place is not a near-miss: it is a
        # document whose reconciliation cannot be believed.
        document = self.broken()
        document["frames"][0]["reconciled"] = "yes"
        self.assertReported(
            document, "a reconciled flag that is not a boolean",
            timeline.PROBLEM_RECONCILED_NOT_BOOL)

    def test_a_non_integer_frame_index_is_reported(self):
        document = self.broken()
        document["frames"][0]["frame"] = "1"
        self.assertReported(
            document, "a frame index that is not an integer",
            timeline.PROBLEM_ENTRY_INDEX_NOT_INT)

    def test_a_disagreeing_total_is_reported(self):
        document = self.broken()
        document["total"] = 99.0
        self.assertReported(document, "a total that is not the sum",
                            timeline.PROBLEM_TOTAL)

    def test_a_disagreeing_duration_total_is_reported(self):
        document = self.broken()
        document["total_duration"] = 1.0
        self.assertReported(document, "a wrong total_duration",
                            timeline.PROBLEM_TOTAL_DURATION)

    def test_a_disagreeing_transition_total_is_reported(self):
        # Two flagged frames buy two seconds of video.  Claiming any
        # other number is how the container and the captions would end
        # up describing different films.
        document = self.broken()
        document["total_transition"] = 5.0
        self.assertReported(document, "a wrong total_transition",
                            timeline.PROBLEM_TOTAL_TRANSITION)

    def test_a_disagreeing_final_cue_end_is_reported(self):
        document = self.broken()
        document["final_cue_end"] = 99.0
        self.assertReported(document, "a wrong final_cue_end",
                            timeline.PROBLEM_FINAL_CUE_END)

    def test_a_total_that_is_not_the_final_cue_end_is_reported(self):
        # THE INVARIANT, broken on both sides at once so that each
        # half stays internally consistent: the totals still add up to
        # `total` and the cue walk still ends at `final_cue_end`, but
        # the two no longer agree -- which is precisely the state a
        # caption generator that ignored transitions would produce.
        document = self.broken()
        document["total_duration"] = REFERENCE_TOTAL_DURATION + 1.0
        document["total"] = REFERENCE_TOTAL + 1.0
        problems = self.assertReported(
            document,
            "a total that disagrees with the final cue end",
            timeline.PROBLEM_TOTAL_VS_CUE)
        self.assertIn(
            timeline.PROBLEM_TOTAL_DURATION,
            [problem.code for problem in problems],
            msg=("the frames' own sum must be reported too, since it "
                 "is the number that was falsified"))

    def test_a_disagreeing_frame_count_is_reported(self):
        document = self.broken()
        document["frame_count"] = 99
        self.assertReported(document, "a wrong frame_count",
                            timeline.PROBLEM_FRAME_COUNT)

    def test_a_disagreeing_transition_count_is_reported(self):
        document = self.broken()
        document["transition_count"] = 0
        self.assertReported(document, "a wrong transition_count",
                            timeline.PROBLEM_TRANSITION_COUNT)

    def test_a_disagreeing_reconciled_count_is_reported(self):
        document = self.broken()
        document["reconciled_count"] = 3
        self.assertReported(document, "a wrong reconciled_count",
                            timeline.PROBLEM_RECONCILED_COUNT)

    def test_a_rewritten_constant_is_reported(self):
        for name in ("floor", "ceil", "transition"):
            with self.subTest(constant=name):
                document = self.broken()
                document[name] = 42.0
                self.assertReported(
                    document,
                    "a timeline written under a different %s; the "
                    "constants are fixed, not tunable" % name,
                    timeline.PROBLEM_CONSTANT_REWRITTEN)

    def test_a_reordered_index_is_reported(self):
        document = self.broken()
        document["frames"][2]["frame"] = 99
        self.assertReported(document, "a frame index out of sequence",
                            timeline.PROBLEM_ENTRY_INDEX_SEQUENCE)

    def test_a_reordered_index_cannot_be_blessed_by_accident(self):
        # A written timeline built on an invalid sequence would be
        # indistinguishable from a correct one to every stage that read
        # it, so an out-of-sequence index is a refusal by DEFAULT and
        # the tolerance has to be asked for by name -- there is no
        # implicit path, and no positional argument that could be
        # supplied without meaning to.
        document = self.broken()
        document["frames"][2]["frame"] = 99
        self.assertTrue(
            timeline.validate_timeline(document),
            msg="a reordered index is always a problem by default")
        self.assertEqual(
            timeline.validate_timeline(
                document, allow_index_gaps=True), [],
            msg=("the only way past it is the named keyword, which the "
                 "command line exposes as DIAGNOSTIC ONLY"))

    def test_a_missing_entry_field_is_reported(self):
        for name in timeline.ENTRY_FIELDS:
            with self.subTest(field=name):
                document = self.broken()
                del document["frames"][0][name]
                self.assertReported(
                    document, "an entry missing %s" % name,
                    timeline.PROBLEM_ENTRY_MISSING_FIELD)

    def test_a_missing_document_field_is_reported(self):
        for name in timeline.DOCUMENT_FIELDS:
            with self.subTest(field=name):
                document = self.broken()
                del document[name]
                self.assertReported(
                    document, "a timeline missing %s" % name,
                    timeline.PROBLEM_TIMELINE_MISSING_FIELD)

    def test_a_non_document_is_reported(self):
        for value in ([], "timeline", 17, None):
            with self.subTest(value=value):
                self.assertReported(
                    value, "a timeline that is not an object",
                    timeline.PROBLEM_TIMELINE_NOT_OBJECT)

    def test_frames_that_are_not_an_array_is_reported(self):
        document = self.broken()
        document["frames"] = {}
        self.assertReported(document, "a frames field that is not an "
                                      "array",
                            timeline.PROBLEM_FRAMES_NOT_ARRAY)

    def test_an_entry_that_is_not_an_object_is_reported(self):
        document = self.broken()
        document["frames"][0] = "frame one"
        self.assertReported(document, "an entry that is not an object",
                            timeline.PROBLEM_ENTRY_NOT_OBJECT)

    def test_a_non_numeric_cue_is_reported(self):
        document = self.broken()
        document["frames"][0]["cue_end"] = "0.25"
        self.assertReported(document, "a cue time that is not a number",
                            timeline.PROBLEM_ENTRY_NOT_NUMBER)


class TestValidatorBranchIsolation(unittest.TestCase):
    """Every validator branch must be independently provable.

    The class above asserts that each specific check fires for the
    defect it exists to catch.  This one closes the two gaps that would
    otherwise let that reassurance be hollow:

    * COMPLETENESS -- every code timeline.py can report has a mutation
      here that provokes it, so a branch cannot exist unprotected.  If
      someone adds a check without adding a case, this fails.
    * ISOLATION -- each code names exactly ONE check site in the module,
      which is what makes "the code was reported" mean "that branch ran
      and complained".  Without it, two checks could share a code and a
      code-specific assertion would be no better than the generic one
      it replaced.

    Together they are the mutation argument made structural: deleting
    any single check removes the only site that can emit its code, so
    the case naming that code stops passing.
    """

    # (label, build, expected code).  `build` takes no arguments and
    # returns the subject to validate, so there is no ambiguity between
    # editing a document and replacing it wholesale.
    CASES = (
        ("a duration below the floor",
         lambda: broken_entry(0, duration=0.1),
         timeline.PROBLEM_DURATION_CLAMP),
        ("a duration that does not clamp its delta",
         lambda: broken_entry(1, duration=2.0),
         timeline.PROBLEM_DURATION_NOT_CLAMPED),
        ("a raw delta running backwards",
         lambda: broken_entry(1, raw_delta=-1.0),
         timeline.PROBLEM_RAW_DELTA_NEGATIVE),
        ("a cleared transition flag",
         lambda: broken_entry(3, transition_after=False),
         timeline.PROBLEM_TRANSITION_FLAG),
        ("a cue window of the wrong length",
         lambda: broken_entry(2, cue_end=99.0),
         timeline.PROBLEM_CUE_LENGTH),
        ("a frame index that is not an integer",
         lambda: broken_entry(0, frame="1"),
         timeline.PROBLEM_ENTRY_INDEX_NOT_INT),
        ("a frame index out of sequence",
         lambda: broken_entry(2, frame=99),
         timeline.PROBLEM_ENTRY_INDEX_SEQUENCE),
        ("a cue time that is not a number",
         lambda: broken_entry(0, cue_end="0.25"),
         timeline.PROBLEM_ENTRY_NOT_NUMBER),
        ("a reconciled flag that is not a boolean",
         lambda: broken_entry(0, reconciled="yes"),
         timeline.PROBLEM_RECONCILED_NOT_BOOL),
        ("a reconciled reading with no reason",
         lambda: broken_entry(0, reconciled=True),
         timeline.PROBLEM_RECONCILED_NO_REASON),
        ("a reason on an unflagged reading",
         lambda: broken_entry(0, reconciled_reason="clock-missing"),
         timeline.PROBLEM_REASON_NOT_RECONCILED),
        ("an entry that is not an object",
         lambda: _entry_replaced_with("frame one"),
         timeline.PROBLEM_ENTRY_NOT_OBJECT),
        ("an entry missing a field",
         lambda: _without_entry_field("duration"),
         timeline.PROBLEM_ENTRY_MISSING_FIELD),
        ("a timeline that is not an object",
         lambda: "not a timeline",
         timeline.PROBLEM_TIMELINE_NOT_OBJECT),
        ("a timeline missing a field",
         lambda: _without_document_field("total"),
         timeline.PROBLEM_TIMELINE_MISSING_FIELD),
        ("a frames field that is not an array",
         lambda: broken_document(frames={}),
         timeline.PROBLEM_FRAMES_NOT_ARRAY),
        ("a rewritten constant",
         lambda: broken_document(ceil=42.0),
         timeline.PROBLEM_CONSTANT_REWRITTEN),
        ("a count that is not an integer",
         lambda: broken_document(frame_count="8"),
         timeline.PROBLEM_DOCUMENT_COUNT_NOT_INT),
        ("a negative count",
         lambda: broken_document(reconciled_count=-1),
         timeline.PROBLEM_DOCUMENT_COUNT_NEGATIVE),
        ("a total that is not a number",
         lambda: broken_document(total="34.5"),
         timeline.PROBLEM_DOCUMENT_NOT_NUMBER),
        ("a total that is not finite",
         lambda: broken_document(total=float("inf")),
         timeline.PROBLEM_DOCUMENT_NOT_FINITE),
        ("a negative total",
         lambda: broken_document(total_duration=-1.0),
         timeline.PROBLEM_DOCUMENT_NUMBER_NEGATIVE),
        ("a version this module does not write",
         lambda: broken_document(version=99),
         timeline.PROBLEM_DOCUMENT_VERSION),
        ("a transition flag that is not a boolean",
         lambda: broken_entry(0, transition_after="no"),
         timeline.PROBLEM_TRANSITION_NOT_BOOL),
        ("an absolutised clock that is not an integer",
         lambda: broken_entry(0, clock_seconds=28800.0),
         timeline.PROBLEM_CLOCK_SECONDS_NOT_INT),
        ("a text field carrying a number",
         lambda: broken_entry(0, action=7),
         timeline.PROBLEM_FIELD_NOT_TEXT),
        ("a nullable text field carrying a number",
         lambda: broken_entry(0, ingame_clock=8),
         timeline.PROBLEM_FIELD_NOT_TEXT_OR_NULL),
        ("a wrong frame_count",
         lambda: broken_document(frame_count=99),
         timeline.PROBLEM_FRAME_COUNT),
        ("a first cue that does not start at zero",
         lambda: _shifted_cues(1.0),
         timeline.PROBLEM_FIRST_CUE),
        ("a cue that ignores the transition second",
         _cues_without_transitions,
         timeline.PROBLEM_CUE_START),
        ("an absolutised clock that falls",
         lambda: broken_entry(5, clock_seconds=1),
         timeline.PROBLEM_CLOCK_BACKWARDS),
        ("a transition after the final frame",
         _final_frame_flagged,
         timeline.PROBLEM_FINAL_FLAGGED),
        ("a delta on the final frame",
         _final_frame_with_a_delta,
         timeline.PROBLEM_FINAL_DELTA),
        ("a wrong total_duration",
         lambda: broken_document(total_duration=1.0),
         timeline.PROBLEM_TOTAL_DURATION),
        ("a wrong transition_count",
         lambda: broken_document(transition_count=0),
         timeline.PROBLEM_TRANSITION_COUNT),
        ("a wrong reconciled_count",
         lambda: broken_document(reconciled_count=3),
         timeline.PROBLEM_RECONCILED_COUNT),
        ("a wrong total_transition",
         lambda: broken_document(total_transition=5.0),
         timeline.PROBLEM_TOTAL_TRANSITION),
        ("a total that is not the sum",
         lambda: broken_document(total=99.0),
         timeline.PROBLEM_TOTAL),
        ("a wrong final_cue_end",
         lambda: broken_document(final_cue_end=99.0),
         timeline.PROBLEM_FINAL_CUE_END),
        ("a total that is not the final cue end",
         lambda: broken_document(
             total_duration=REFERENCE_TOTAL_DURATION + 1.0,
             total=REFERENCE_TOTAL + 1.0),
         timeline.PROBLEM_TOTAL_VS_CUE),
        # THE PROVENANCE BRANCHES.  A null attestation is accepted -- an
        # unattested document is one that may not pace a film, which is
        # assert_timeline_document()'s business rather than this
        # validator's -- but an attestation that IS present has to be
        # well formed, or it could never be checked against the manifest
        # it claims to describe.
        ("an attestation that is not an object",
         lambda: broken_document(manifest="playthrough/manifest.jsonl"),
         timeline.PROBLEM_MANIFEST_NOT_OBJECT),
        ("an attestation missing a field",
         lambda: broken_document(
             manifest={"path": "playthrough/manifest.jsonl"}),
         timeline.PROBLEM_MANIFEST_MISSING_FIELD),
        ("an attestation carrying an unexpected field",
         lambda: broken_attestation(mtime=1),
         timeline.PROBLEM_MANIFEST_EXTRA_FIELD),
        ("an attested path that is not a path",
         lambda: broken_attestation(path=None),
         timeline.PROBLEM_MANIFEST_PATH_NOT_TEXT),
        ("an attested path that is absolute",
         lambda: broken_attestation(path="/etc/passwd"),
         timeline.PROBLEM_MANIFEST_PATH_ABSOLUTE),
        ("an attested path that walks upwards",
         lambda: broken_attestation(path="../manifest.jsonl"),
         timeline.PROBLEM_MANIFEST_PATH_UPWARDS),
        ("an attested digest that is not sha256",
         lambda: broken_attestation(sha256="deadbeef"),
         timeline.PROBLEM_MANIFEST_DIGEST),
        ("an attested row count that is not an integer",
         lambda: broken_attestation(rows="7"),
         timeline.PROBLEM_MANIFEST_ROWS_NOT_INT),
        ("an attested row count below zero",
         lambda: broken_attestation(rows=-1),
         timeline.PROBLEM_MANIFEST_ROWS_NEGATIVE),
        ("an attested row count that disagrees with the entries",
         lambda: broken_attestation(rows=99),
         timeline.PROBLEM_MANIFEST_ROWS_MISMATCH),
        # THE AMENDMENT-PROVENANCE BRANCHES.  A null ledger attestation
        # is the ordinary case -- most sessions have nothing to amend --
        # but a present one has to be well formed, because the entries it
        # accompanies may carry narration a correction supplied and a
        # reader has to be able to prove which ledger supplied it.
        ("a ledger attestation that is not an object",
         lambda: broken_document(
             amendments="playthrough/amendments.jsonl"),
         timeline.PROBLEM_AMENDMENTS_NOT_OBJECT),
        ("a ledger attestation missing a field",
         lambda: broken_document(
             amendments={"path": "playthrough/amendments.jsonl"}),
         timeline.PROBLEM_AMENDMENTS_MISSING_FIELD),
        ("a ledger attestation with an unexpected field",
         lambda: broken_amendments(mtime=1),
         timeline.PROBLEM_AMENDMENTS_EXTRA_FIELD),
        ("an attested ledger path that is not a path",
         lambda: broken_amendments(path=None),
         timeline.PROBLEM_AMENDMENTS_PATH_NOT_TEXT),
        ("an attested ledger path that walks upwards",
         lambda: broken_amendments(path="../amendments.jsonl"),
         timeline.PROBLEM_AMENDMENTS_PATH_UNSAFE),
        ("an attested ledger digest that is not sha256",
         lambda: broken_amendments(sha256="deadbeef"),
         timeline.PROBLEM_AMENDMENTS_DIGEST),
        ("an attested ledger holding no rows",
         lambda: broken_amendments(rows=0),
         timeline.PROBLEM_AMENDMENTS_ROWS),
        ("an applied count that is not an integer",
         lambda: broken_amendments(applied="2"),
         timeline.PROBLEM_AMENDMENTS_APPLIED),
        ("more amendments applied than the ledger holds",
         lambda: broken_amendments(rows=1, applied=2),
         timeline.PROBLEM_AMENDMENTS_APPLIED_EXCEEDS),
        ("an amended flag that is not a boolean",
         lambda: broken_entry(0, amended="yes"),
         timeline.PROBLEM_AMENDED_NOT_BOOL),
        # THE CAPTURE-PROVENANCE BRANCHES.  A null capture attestation is
        # shape-valid here for the same reason a null ledger is -- a
        # session captured before the digest ledger existed has none, and
        # whether one OUGHT to be present is a question only
        # capture_attestation_problems() can answer, because it needs the
        # ledger on disk.  A present one has to be well formed, since it
        # is the only statement in the document about the PIXELS it paces.
        ("a capture attestation that is not an object",
         lambda: broken_document(
             captures="playthrough/build/frame_digests.jsonl"),
         timeline.PROBLEM_CAPTURES_NOT_OBJECT),
        ("a capture attestation missing a field",
         lambda: broken_document(captures={
             "path": "playthrough/build/frame_digests.jsonl"}),
         timeline.PROBLEM_CAPTURES_MISSING_FIELD),
        ("a capture attestation with an unexpected field",
         lambda: broken_captures(mtime=1),
         timeline.PROBLEM_CAPTURES_EXTRA_FIELD),
        ("an attested capture ledger path that is not a path",
         lambda: broken_captures(path=None),
         timeline.PROBLEM_CAPTURES_PATH_NOT_TEXT),
        ("an attested capture ledger path that walks upwards",
         lambda: broken_captures(path="../frame_digests.jsonl"),
         timeline.PROBLEM_CAPTURES_PATH_UNSAFE),
        ("an attested capture ledger digest that is not sha256",
         lambda: broken_captures(sha256="deadbeef"),
         timeline.PROBLEM_CAPTURES_DIGEST),
        ("an attested capture ledger holding no rows",
         lambda: broken_captures(rows=0),
         timeline.PROBLEM_CAPTURES_ROWS),
        ("fewer frames verified than the timeline paces",
         lambda: broken_captures(verified=1),
         timeline.PROBLEM_CAPTURES_VERIFIED),
    )

    def test_every_case_is_caught_by_the_check_it_names(self):
        for label, build, code in self.CASES:
            with self.subTest(case=label):
                self.assertEqual(
                    timeline.timeline_problems(reference_document()),
                    [],
                    msg=("the fixture must start clean, or this case "
                         "proves nothing"))
                codes = [problem.code
                         for problem in
                         timeline.timeline_problems(build())]
                self.assertIn(
                    code, codes,
                    msg=("%s must be caught by '%s'; got %r"
                         % (label, code, codes)))

    def test_every_declared_code_has_a_case(self):
        covered = {code for _, _, code in self.CASES}
        self.assertEqual(
            sorted(covered), sorted(timeline.PROBLEM_CODES),
            msg=("every problem code must have a mutation that "
                 "provokes it, or a validator branch is going "
                 "unprotected"))

    def test_no_code_is_declared_twice(self):
        self.assertEqual(
            len(timeline.PROBLEM_CODES),
            len(set(timeline.PROBLEM_CODES)),
            msg="a code must name one check, so the list has no repeats")

    def test_each_code_has_exactly_one_check_site(self):
        # The structural half of the mutation argument.  Every problem
        # is constructed as `Problem(PROBLEM_..., "...")`, so counting
        # those constructions counts check sites: if a code appeared at
        # two of them, deleting one would leave a case here passing on
        # the other, and the assertion in
        # TestValidationFailsLoudly.assertReported would be no stronger
        # than the generic oracle it replaced.
        source = _timeline_source()
        sites = re.findall(r"Problem\(\s*(PROBLEM_[A-Z_]+)", source)
        self.assertTrue(
            sites, msg="the problem construction sites must be found")
        for code_name in sites:
            with self.subTest(code=code_name):
                self.assertEqual(
                    sites.count(code_name), 1,
                    msg=("%s is used at %d check sites; a code must "
                         "name exactly one, or asserting on it cannot "
                         "prove which branch ran"
                         % (code_name, sites.count(code_name))))
        declared = {
            name for name in dir(timeline)
            if name.startswith("PROBLEM_") and name != "PROBLEM_CODES"}
        self.assertEqual(
            sorted(set(sites)), sorted(declared),
            msg=("every declared code must have a check site and "
                 "every check site must use a declared code"))

    def test_a_clean_document_reports_nothing_at_all(self):
        self.assertEqual(
            timeline.timeline_problems(reference_document()), [],
            msg=("the structured view must agree with the message "
                 "view that a correct timeline is correct"))

    def test_a_problem_carries_both_a_code_and_a_message(self):
        document = reference_document()
        document["total"] = 99.0
        problem = timeline.timeline_problems(document)[0]
        self.assertIsInstance(
            problem, timeline.Problem,
            msg="the structured view returns Problem records")
        self.assertEqual(
            problem.code, timeline.PROBLEM_TOTAL,
            msg="the code names the check that complained")
        self.assertIn(
            "99.0", problem.message,
            msg=("the message still carries the offending value, "
                 "because it is what an operator reads"))
        self.assertEqual(
            (problem[0], problem[1]), (problem.code, problem.message),
            msg="a Problem is a plain tuple of (code, message)")


class TestTimelineCliAndIo(unittest.TestCase):
    """The command line and the file contract, exercised for real.

    The arithmetic above is pure and is tested in memory.  This class
    tests the OTHER half of the module -- reading the manifest, reading
    the telemetry sidecar, choosing where to write, verifying what is
    already on disk, and the exit status each of those produces -- by
    calling main(argv) directly against files in a temporary directory.

    WHY IT MATTERS THAT THIS IS COVERED
    Every operational path here can fail while every arithmetic test
    still passes: an empty manifest that silently produced an empty
    film, a --verify that reported success on a timeline computed from
    some other session, a --require-date run that accepted an inferred
    day, an exit status of 0 on a failure.  A run_pipeline.sh step reads
    only the exit status, so an exit status that is wrong is a whole
    stage that appears to have worked.

    Nothing here touches the real artifacts: every path is inside a
    fresh temporary directory, and the environment variables that would
    otherwise point the module at the committed tree are redirected
    there for the duration of each test.
    """

    def setUp(self):
        self.directory = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_timeline_cli_"))
        self.addCleanup(_remove_tree, self.directory)
        self.manifest = os.path.join(self.directory, "manifest.jsonl")
        self.output = os.path.join(self.directory, "timeline.json")
        self.observations = os.path.join(
            self.directory, "observations.jsonl")
        self.audit = os.path.join(self.directory, "frame_dates.jsonl")
        self.frames = os.path.join(self.directory, "frames")
        self.digests = os.path.join(self.directory,
                                    *manifest.DIGESTS_REL_PARTS)
        self.write_manifest(REFERENCE_CLOCKS)
        self.seal(len(REFERENCE_CLOCKS))
        # Redirect the module's defaults into the temporary directory so
        # that even a bug in this suite cannot reach the committed
        # manifest or timeline.
        # (see self.expected_document() for what the CLI now writes)
        self.env = _environment(
            PLAYTHROUGH_MANIFEST=self.manifest,
            PLAYTHROUGH_TIMELINE=self.output,
            PLAYTHROUGH_OBSERVATIONS=self.observations,
            PLAYTHROUGH_DATE_AUDIT=self.audit)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    def write_manifest(self, clocks, path=None):
        """Write one manifest row per reading and return the path."""
        return _write_lines(
            path or self.manifest,
            [json.dumps(row) for row in make_rows(clocks)])

    def seal(self, count, indexes=None):
        """Create `count` captures and attest each one's bytes.

        THE FIXTURE HAS TO PRODUCE FRAMES NOW, because the CLI verifies
        the pixels it is about to time against the attestation ledger
        before it computes a single duration.  A fixture that wrote only
        a manifest would exercise that refusal rather than the run.

        Each frame's body is derived from its index, so two frames never
        share a digest and a substitution is detectable.
        """
        return seal_captures(
            self.directory,
            range(1, count + 1) if indexes is None else indexes)

    def reseal(self, indexes):
        """Start the fixture's ledger over for a different frame set.

        THE LEDGER IS APPEND-ONLY IN PRODUCTION and that property is
        asserted where it belongs, in test_manifest.py.  This is a
        FIXTURE's scratch file, not evidence, and a test whose subject is
        a differently-numbered record needs the frames and the
        attestations that record describes rather than the ones setUp
        happened to write.
        """
        return reseal_captures(self.directory, indexes)

    def attest_frames(self, count=None):
        """The capture attestation the CLI records for this tree."""
        return timeline.attest_captures(
            self.digests, self.directory,
            verified=len(REFERENCE_CLOCKS) if count is None else count)

    def expected_document(self, clocks=None, manifest=None):
        """The document the CLI writes for a manifest on disk.

        The pure computation PLUS the provenance the CLI records with it:
        the manifest's repository-relative path, the sha256 of its exact
        bytes and its row count.  A test that compared against the bare
        computation would be asserting that the artifact carries NO
        provenance -- which is the state the three producers now refuse,
        so it would be asserting the wrong thing.
        """
        rows = make_rows(REFERENCE_CLOCKS if clocks is None else clocks)
        return timeline.build_timeline(
            rows, None, None,
            timeline.attest_manifest(manifest or self.manifest,
                                     self.directory),
            capture_attestation=self.attest_frames(len(rows)))

    def write_observations(self, dates, status=None, path=None):
        """Write one telemetry row per frame and return the path."""
        rows = []
        for index, date in enumerate(dates, start=1):
            row = {"frame": index, "file": FRAME_FILE_FORMAT % index}
            if date is not None:
                row["date"] = date
            if status is not None:
                row["date_status"] = status
            rows.append(json.dumps(row))
        return _write_lines(path or self.observations, rows)

    def run_main(self, *argv):
        """Call main(argv) and return (status, stdout, stderr)."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            status = timeline.main(list(argv), root=self.directory)
        return status, out.getvalue(), err.getvalue()

    # -- the ordinary run -------------------------------------------

    def test_a_bare_run_writes_the_timeline_and_summarises_it(self):
        status, out, err = self.run_main()
        self.assertEqual(
            status, 0,
            msg="a manifest that is fine must produce exit 0: %s" % err)
        self.assertTrue(
            os.path.isfile(self.output),
            msg=("with no arguments the module writes "
                 "$PLAYTHROUGH_TIMELINE, which is how run_pipeline.sh "
                 "invokes it"))
        self.assertIn(
            "timeline ok: 7 frame(s), 2 transition(s)", out,
            msg="the summary reports what was computed")
        self.assertIn(
            "32.500 + 2.000 = 34.500 s", out,
            msg=("the summary carries THE INVARIANT in the form an "
                 "operator can check against ffprobe"))
        self.assertIn(
            self.output, out,
            msg="the summary names the file it wrote")
        written = timeline.read_timeline(self.output, root=self.directory)
        self.assertEqual(
            written, self.expected_document(),
            msg=("the file on disk must be exactly what the pure "
                 "computation produces from the same rows, plus the "
                 "attestation naming the manifest it came from"))
        self.assertEqual(
            written["manifest"]["rows"], written["frame_count"],
            msg="the attestation and the entries must agree")

    def test_the_output_path_may_be_given_explicitly(self):
        elsewhere = os.path.join(self.directory, "other.json")
        status, out, _ = self.run_main("-o", elsewhere)
        self.assertEqual(status, 0)
        self.assertTrue(os.path.isfile(elsewhere))
        self.assertFalse(
            os.path.exists(self.output),
            msg="-o must replace the default, not add to it")

    def test_stdout_mode_prints_the_timeline_and_writes_nothing(self):
        status, out, _ = self.run_main("--stdout")
        self.assertEqual(status, 0)
        self.assertFalse(
            os.path.exists(self.output),
            msg=("--stdout exists so a timeline can be inspected "
                 "without touching the committed artifact"))
        self.assertEqual(
            json.loads(out), self.expected_document(),
            msg="what is printed is the timeline itself, not a summary")
        self.assertEqual(
            out, timeline.encode_timeline(self.expected_document()),
            msg=("byte for byte the same text the file would hold, so "
                 "a caller can diff one against the other"))

    def test_quiet_suppresses_the_summary_but_still_writes(self):
        status, out, _ = self.run_main("--quiet")
        self.assertEqual(status, 0)
        self.assertEqual(
            out, "",
            msg="--quiet is for a pipeline stage, not for a human")
        self.assertTrue(os.path.isfile(self.output))

    def test_an_explicit_manifest_is_confirmed_not_redirected(self):
        # The option is READ rather than ignored -- naming the record
        # explicitly is accepted -- but the record of a captured session
        # has exactly one place to live, so naming anything else is
        # refused.  A --manifest that could point elsewhere would let a
        # film be paced from rows nobody captured, and every count
        # downstream would still tally.
        status, out, err = self.run_main("--manifest", self.manifest)
        self.assertEqual(status, 0, msg=err)
        self.assertIn("7 frame(s)", out)
        other = os.path.join(self.directory, "other.jsonl")
        self.write_manifest(("08:15:33", "08:15:34"), path=other)
        status, out, err = self.run_main("--manifest", other)
        self.assertEqual(
            status, 1,
            msg="a manifest anywhere but its one place is refused")
        self.assertIn("and nothing else", err)

    # -- the empty and the malformed --------------------------------

    def test_an_empty_manifest_is_refused_by_default(self):
        _write_lines(self.manifest, [])
        status, _, err = self.run_main()
        self.assertEqual(
            status, 1,
            msg=("a session with no frames is not something to pace a "
                 "film from silently"))
        self.assertIn("no rows", err)
        self.assertFalse(os.path.exists(self.output))

    def test_an_empty_manifest_may_be_accepted_explicitly(self):
        _write_lines(self.manifest, [])
        # A record with no rows describes a session in which nothing was
        # captured, so it has no frames and no attestations either.  A
        # ledger left standing beside it would be a real inconsistency,
        # and is reported as one.
        self.reseal([])
        status, out, _ = self.run_main("--allow-empty")
        self.assertEqual(status, 0)
        document = timeline.read_timeline(self.output, root=self.directory)
        self.assertEqual(document["frame_count"], 0)
        self.assertEqual(document["frames"], [])
        self.assertEqual(document["total"], 0.0)
        self.assertEqual(document["final_cue_end"], 0.0)
        self.assertEqual(
            timeline.validate_timeline(document), [],
            msg="an empty timeline still satisfies every invariant")

    def test_a_missing_manifest_is_reported_not_invented(self):
        os.unlink(self.manifest)
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("no manifest at", err)

    def test_a_manifest_line_that_is_not_json_is_refused(self):
        _write_lines(self.manifest, ["{not json"])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("is not JSON", err)

    def test_a_manifest_row_that_is_not_an_object_is_refused(self):
        _write_lines(self.manifest, ["[1, 2, 3]"])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("not a JSON object", err)

    def test_a_schema_problem_stops_the_run_and_is_reported(self):
        rows = make_rows(REFERENCE_CLOCKS)
        rows[2]["extra"] = "a seventh field"
        _write_lines(self.manifest,
                     [json.dumps(row) for row in rows])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn(
            "expected exactly", err,
            msg="the row's keys are named in the complaint")
        self.assertIn("--ignore-manifest-problems", err)
        self.assertFalse(
            os.path.exists(self.output),
            msg="nothing is written while the manifest is in doubt")

    def test_a_schema_problem_may_be_overridden_explicitly(self):
        rows = make_rows(REFERENCE_CLOCKS)
        rows[2]["extra"] = "a seventh field"
        _write_lines(self.manifest,
                     [json.dumps(row) for row in rows])
        status, _, err = self.run_main("--ignore-manifest-problems")
        self.assertEqual(
            status, 0,
            msg="the override exists, and it still reports everything")
        self.assertIn("expected exactly", err)
        self.assertIn(
            "--ignore-manifest-problems was given", err,
            msg=("the override must be recorded in the log, so a "
                 "timeline computed under it is never mistaken for a "
                 "clean one"))
        self.assertTrue(os.path.isfile(self.output))

    def test_an_index_gap_is_refused_and_may_be_allowed(self):
        rows = make_rows(REFERENCE_CLOCKS)
        rows[2]["frame"] = 99
        rows[2]["file"] = FRAME_FILE_FORMAT % 99
        _write_lines(self.manifest,
                     [json.dumps(row) for row in rows])
        # The frames follow the record: the gapped session photographed
        # frame 99 and never photographed frame 3, so that is what is on
        # disk and what is attested.  Otherwise the capture gate would
        # refuse first and this test would prove nothing about the gap.
        self.reseal([1, 2, 99, 4, 5, 6, 7])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("no gap, no repeat and no reordering", err)
        status, _, err = self.run_main("--allow-index-gaps")
        self.assertEqual(
            status, 0,
            msg="a gap is proceeded past only when asked for")
        self.assertIn(
            "--allow-index-gaps was given", err,
            msg=("the flag's own help promises the override names "
                 "itself on stderr; an integrity relaxation that "
                 "stays silent is indistinguishable from a clean run "
                 "in the session log"))
        self.assertIn(
            "DIAGNOSTIC", err,
            msg="and it says what kind of artifact this now is")

    def test_a_missing_output_directory_is_reported(self):
        status, _, err = self.run_main(
            "-o", os.path.join(self.directory, "absent", "t.json"))
        self.assertEqual(status, 1)
        self.assertIn(
            "the directory for the timeline does not exist", err,
            msg=("the directory is not created here: a mistyped path "
                 "must not grow a second timeline somewhere else"))

    # -- the telemetry sidecar --------------------------------------

    def test_without_telemetry_no_day_decision_rests_on_evidence(self):
        status, _, _ = self.run_main()
        self.assertEqual(status, 0)
        document = timeline.read_timeline(self.output, root=self.directory)
        self.assertEqual(
            [entry["date_agreement"] for entry in document["frames"]],
            [timeline.AGREE_NONE] * document["frame_count"],
            msg=("with no sidecar at all the clock is the only source, "
                 "and every entry has to say so rather than claim a "
                 "day that was checked against nothing"))
        for name in ("date_confirmed_count", "date_corrected_count",
                     "date_unverified_count", "date_conflict_count"):
            with self.subTest(field=name):
                self.assertEqual(
                    document[name], 0,
                    msg=("no frame was confirmed, corrected, left "
                         "unverified or found in conflict, because no "
                         "date was read at all"))
        self.assertEqual(
            [entry["ingame_date"] for entry in document["frames"]],
            [None] * document["frame_count"],
            msg="and no date is invented to fill the column")

    def test_require_date_refuses_to_run_without_telemetry(self):
        status, _, err = self.run_main("--require-date")
        self.assertEqual(
            status, 1,
            msg=("--require-date is for a run that must not accept an "
                 "inferred day"))
        self.assertIn("no capture telemetry at", err)
        self.assertIn("--require-date", err)

    def test_telemetry_confirms_the_day_and_is_reported(self):
        # The reference sequence crosses midnight between frame 6
        # (23:59:58) and frame 7 (00:00:04), so the date line advances
        # there and nowhere else.
        self.write_observations(
            ["Thursday, Mar 8"] * 6 + ["Friday, Mar 9"] * 2,
            status=timeline.DATE_STATUS_READ)
        status, _, _ = self.run_main("--require-date")
        self.assertEqual(status, 0)
        document = timeline.read_timeline(self.output, root=self.directory)
        self.assertEqual(
            document["date_unverified_count"], 0,
            msg="every frame's day was established by the date line")
        self.assertEqual(
            document["date_confirmed_count"] +
            document["date_corrected_count"],
            document["frame_count"])

    def test_require_date_refuses_a_frame_the_date_did_not_settle(self):
        # The first five frames carry a date; the last three do not, so
        # their day was inferred from the clock alone.
        self.write_observations(
            ["Thursday, Mar 8"] * 5 + [None] * 3,
            status=timeline.DATE_STATUS_READ)
        status, _, err = self.run_main("--require-date")
        self.assertEqual(status, 1)
        self.assertIn(
            "no usable sidebar date line", err,
            msg="the frame and the reason are both named")
        self.assertIn(timeline.AGREE_UNVERIFIED, err)

    def test_a_faulted_date_reading_is_not_treated_as_evidence(self):
        self.write_observations(
            ["Thursday, Mar 8"] * 8, status="fault")
        status, _, _ = self.run_main()
        self.assertEqual(status, 0)
        document = timeline.read_timeline(self.output, root=self.directory)
        self.assertEqual(
            document["date_confirmed_count"], 0,
            msg=("capture.sh's own account of the read is honoured: a "
                 "faulted row carries no date this module may use, "
                 "however non-empty the field is"))

    def test_a_malformed_telemetry_line_is_a_hard_failure(self):
        _write_lines(self.observations, ["{not json"])
        status, _, err = self.run_main()
        self.assertEqual(
            status, 1,
            msg=("a sidecar that cannot be believed is not the same "
                 "thing as no sidecar"))
        self.assertIn("is not valid JSON", err)

    def test_a_malformed_audit_row_refuses_to_publish(self):
        """FAIL CLOSED, and leave what is already published alone.

        The audit used to warn and skip a row it could not parse, which
        is not the neutral loss it looks like: two rows carrying one date
        make a backwards clock a same-date reconciliation, and losing one
        of them makes the same clock an unevidenced wrap -- a different
        timeline, published while every count still tallies.  So each
        malformed shape stops the run, names the file and the line, and
        the timeline already on disk is left exactly as it was.
        """
        good = json.dumps({"frame": 1, "file": FRAME_FILE_FORMAT % 1,
                           "clock": None, "phrase": None,
                           "date": "Spring, day 3", "agreement": True})
        for name, line in (
            ("invalid JSON", "{not json"),
            ("not an object", "[1, 2, 3]"),
            ("no frame index", '{"date": "Spring, day 3"}'),
            ("a string index", '{"frame": "1", "date": "x"}'),
            ("a boolean index", '{"frame": true, "date": "x"}'),
            ("a numeric date", '{"frame": 1, "date": 3}'),
        ):
            with self.subTest(shape=name):
                # A timeline computed from sound evidence, published.
                _write_lines(self.audit, [good])
                first, _, _ = self.run_main()
                self.assertEqual(first, 0)
                published = _read_text(self.output)
                # Now the same run over an audit with one bad row.
                _write_lines(self.audit, [good, line])
                status, out, err = self.run_main()
                self.assertEqual(
                    status, 1,
                    msg=("a malformed audit row must refuse "
                         "publication: %s / %s" % (out, err)))
                self.assertIn("frame_dates.jsonl", err)
                self.assertEqual(
                    _read_text(self.output), published,
                    msg=("the timeline already on disk is not "
                         "replaced, truncated or half-written by a run "
                         "that refused"))

    def test_an_absent_audit_still_publishes(self):
        """The boundary of the refusal above, asserted from the CLI."""
        if os.path.exists(self.audit):
            os.unlink(self.audit)
        status, _, err = self.run_main()
        self.assertEqual(
            status, 0,
            msg="no audit at all is a documented mode: %s" % err)

    def test_a_telemetry_row_without_a_frame_index_is_refused(self):
        _write_lines(self.observations, [json.dumps({"date": "x"})])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("frame index", err)

    def test_telemetry_rows_for_a_frame_must_agree(self):
        """Through the real reader, on the real file, at the CLI.

        The rule this asserts replaced last-row-wins, which is the
        defect: two rows that contradicted each other about the date
        still decided a day of game time, settled by write order alone.
        A `null` remains an absence of evidence rather than
        counter-evidence, so the two halves are asserted together.
        """
        _write_lines(self.observations, [
            json.dumps({"frame": 1, "date": "Thursday, Mar 8",
                        "date_status": timeline.DATE_STATUS_READ}),
            json.dumps({"frame": 1, "date": "Friday, Mar 9",
                        "date_status": timeline.DATE_STATUS_READ}),
        ])
        rows = timeline.load_observations(
            self.observations, root=self.directory)
        self.assertIsNone(
            rows[1]["date"],
            msg=("a contradiction is not evidence, and being written "
                 "later does not make one of two readings the true one"))
        _write_lines(self.observations, [
            json.dumps({"frame": 1, "date": "Thursday, Mar 8",
                        "date_status": timeline.DATE_STATUS_READ}),
            json.dumps({"frame": 1, "date": None,
                        "date_status": "unreadable"}),
        ])
        rows = timeline.load_observations(
            self.observations, root=self.directory)
        self.assertEqual(
            rows[1]["date"], "Thursday, Mar 8",
            msg=("an unreadable second look does not erase a reading "
                 "that succeeded"))

    def test_an_absent_sidecar_reads_as_no_evidence_at_all(self):
        self.assertIsNone(
            timeline.load_observations(
                self.observations, root=self.directory),
            msg=("an absent sidecar is an ordinary state: the timeline "
                 "is then computed from the clock alone"))
        with self.assertRaises(timeline.TimelineError):
            timeline.load_observations(
                self.observations, required=True, root=self.directory)

    def test_the_default_observations_path_follows_the_environment(self):
        self.assertEqual(
            timeline.default_observations_path(), self.observations,
            msg=("env.sh is the single definition of the artifact "
                 "layout, so its export wins"))
        with _environment(PLAYTHROUGH_OBSERVATIONS=None):
            self.assertTrue(
                timeline.default_observations_path().endswith(
                    os.path.join("build", "observations.jsonl")),
                msg=("with nothing exported the path is derived from "
                     "the module's own location, so the module works "
                     "in any checkout without configuration"))

    def test_the_default_timeline_path_follows_the_environment(self):
        self.assertEqual(
            timeline.default_timeline_path(), self.output)
        with _environment(PLAYTHROUGH_TIMELINE=None):
            self.assertTrue(
                timeline.default_timeline_path().endswith(
                    os.path.join("playthrough", "timeline.json")))

    # -- verification ------------------------------------------------

    def test_verify_accepts_a_timeline_that_matches_its_manifest(self):
        self.assertEqual(self.run_main("--quiet")[0], 0)
        status, out, err = self.run_main("--verify")
        self.assertEqual(
            status, 0,
            msg="a timeline just written must verify: %s" % err)
        self.assertIn("timeline ok:", out)

    def test_verify_reports_a_timeline_that_no_longer_matches(self):
        self.assertEqual(self.run_main("--quiet")[0], 0)
        # The session grew by one frame after the timeline was written,
        # which is exactly the drift --verify exists to catch.
        self.write_manifest(REFERENCE_CLOCKS + ("00:00:06",))
        # The eighth keystroke took an eighth photograph and sealed it,
        # so the drift under test is the TIMELINE's -- it was computed
        # before that step and describes a session that has since grown.
        self.seal(0, indexes=[8])
        status, _, err = self.run_main("--verify")
        self.assertEqual(status, 1)
        # THE ATTESTATION CATCHES IT FIRST, and says something sharper
        # than the byte comparison could: not merely "these differ" but
        # "this timeline was computed from different evidence than is on
        # disk", with both digests and both row counts named.  The byte
        # diff is still there behind it; provenance simply fails earlier
        # and more usefully, which is the point of carrying it.
        self.assertIn("DIFFERENT evidence", err)
        self.assertIn(
            "7 row(s)", err,
            msg=("the counts are named, because that is the first "
                 "thing an operator needs to know"))
        self.assertIn(
            "now holds 8", err,
            msg="and what the manifest holds now")
        # AND ONLY THOSE TWO.  --verify checks the evidence before the
        # claim and stops at the first layer that objects, so an operator
        # is told "the record has grown" rather than being handed the
        # consequences of that in four more forms.
        self.assertIn(
            "2 problem(s) found", err,
            msg="the count of problems is reported, not just the list")

    def test_verify_reports_a_timeline_that_fails_its_invariants(self):
        document = reference_document()
        document["total"] = 99.0
        _write_lines(
            self.output, [json.dumps(document, indent=2)])
        status, _, err = self.run_main("--verify")
        self.assertEqual(status, 1)
        self.assertIn("total is 99.0", err)

    def test_verify_refuses_a_timeline_that_is_not_there(self):
        status, _, err = self.run_main("--verify")
        self.assertEqual(status, 1)
        self.assertIn("no timeline at", err)

    def test_verify_is_quiet_when_asked(self):
        self.assertEqual(self.run_main("--quiet")[0], 0)
        status, out, _ = self.run_main("--verify", "--quiet")
        self.assertEqual(status, 0)
        self.assertEqual(out, "")

    def test_verify_writes_nothing(self):
        self.assertEqual(self.run_main("--quiet")[0], 0)
        before = os.path.getmtime(self.output)
        digest = _read_text(self.output)
        self.assertEqual(self.run_main("--verify", "--quiet")[0], 0)
        self.assertEqual(os.path.getmtime(self.output), before)
        self.assertEqual(_read_text(self.output), digest)

    def test_drift_problems_compares_the_canonical_form(self):
        fresh = timeline.build_timeline(make_rows(REFERENCE_CLOCKS))
        self.assertEqual(
            timeline._drift_problems(
                copy.deepcopy(fresh), fresh, self.output,
                self.manifest),
            [],
            msg=("both sides are re-encoded and the encodings "
                 "compared, which is exactly the claim worth making: "
                 "this file was computed from this manifest by this "
                 "code"))
        shorter = timeline.build_timeline(
            make_rows(REFERENCE_CLOCKS[:4]))
        problems = timeline._drift_problems(
            shorter, fresh, self.output, self.manifest)
        self.assertEqual(len(problems), 2)
        self.assertIn("regenerate it with", problems[0])
        self.assertIn("4 entr(ies) against 7 row(s)", problems[1])

    def test_a_reindent_is_not_drift_but_a_changed_value_is(self):
        # WHAT --verify CLAIMS, EXACTLY, AND WHAT IT DOES NOT.  The
        # stored document is passed through the same encoder as the
        # fresh one, so a rewrite that changed only LAYOUT -- an editor
        # that pretty-printed the artifact, a tool that normalised line
        # endings -- is not drift, because nothing the artifact SAYS has
        # moved.  A duration that moved by a nanosecond is.  The help
        # text promises this distinction; this is where it is held to it,
        # so neither half can be lost: raising on whitespace would train
        # an operator to ignore the one check guarding the timing
        # evidence, and passing a changed value would make the check
        # worthless.
        self.assertEqual(self.run_main("--quiet")[0], 0)
        stored = json.loads(_read_text(self.output))
        _write_lines(
            self.output,
            [json.dumps(stored, indent=4, ensure_ascii=False)])
        self.assertNotEqual(
            _read_text(self.output), timeline.encode_timeline(stored),
            msg=("the fixture has to differ in BYTES for this to be "
                 "testing anything"))
        status, _, err = self.run_main("--verify", "--quiet")
        self.assertEqual(
            status, 0,
            msg=("a layout-only rewrite is not drift: %s" % err))
        # A rewritten commentary is the sharpest case: the document
        # stays internally consistent, so every invariant still passes
        # and this comparison is the ONLY thing that can catch it -- a
        # caption put into the survivor's mouth after the fact.
        stored["frames"][0]["commentary"] = "something else entirely"
        _write_lines(
            self.output,
            [json.dumps(stored, indent=4, ensure_ascii=False)])
        self.assertEqual(
            timeline.validate_timeline(stored), [],
            msg=("the tampered document is internally consistent, "
                 "which is why the drift check has to be the one that "
                 "notices"))
        status, _, err = self.run_main("--verify", "--quiet")
        self.assertEqual(
            status, 1,
            msg="changed CONTENT is drift, whatever the layout")
        self.assertIn(
            "does not match a fresh computation", err,
            msg="and the refusal says the artifact is stale")

    # -- the parser, the reporting helpers and the wrappers ---------

    def test_the_parser_defaults_are_the_pipeline_s_own_behaviour(self):
        args = timeline.build_parser().parse_args([])
        self.assertIsNone(args.manifest)
        self.assertIsNone(args.output)
        self.assertIsNone(args.observations)
        for flag in ("stdout", "verify", "require_date",
                     "allow_index_gaps", "allow_empty",
                     "ignore_manifest_problems", "quiet"):
            with self.subTest(flag=flag):
                self.assertFalse(
                    getattr(args, flag),
                    msg=("a bare invocation must do the pipeline's "
                         "job, so every deviation is opt-in"))

    def test_every_documented_switch_is_accepted(self):
        args = timeline.build_parser().parse_args([
            "--manifest", "m", "--output", "o", "--stdout", "--verify",
            "--observations", "obs", "--require-date",
            "--allow-index-gaps", "--allow-empty",
            "--ignore-manifest-problems", "--quiet"])
        self.assertEqual(args.manifest, "m")
        self.assertEqual(args.output, "o")
        self.assertEqual(args.observations, "obs")
        self.assertTrue(args.stdout and args.verify and
                        args.require_date and args.allow_index_gaps and
                        args.allow_empty and
                        args.ignore_manifest_problems and args.quiet)

    def test_an_unknown_switch_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                timeline.build_parser().parse_args(["--wat"])
        self.assertEqual(caught.exception.code, 2)

    def test_report_prints_one_prefixed_line_per_problem(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            timeline._report(["first", "second"])
        self.assertEqual(
            err.getvalue(),
            "timeline.py: first\ntimeline.py: second\n",
            msg=("every diagnostic is prefixed and goes to stderr, so "
                 "stdout stays a machine channel"))

    def test_warn_carries_the_pipeline_s_own_prefix(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            timeline._warn("something to note")
        self.assertEqual(
            err.getvalue(),
            "playthrough: WARNING: timeline.py: something to note\n",
            msg=("the prefix matches playthrough_warn() in env.sh so "
                 "one session log reads consistently"))

    def test_the_summary_is_the_invariant_in_one_line(self):
        document = reference_document()
        self.assertEqual(
            timeline._summarise(document, "/tmp/t.json"),
            "timeline ok: 7 frame(s), 2 transition(s), 0 reconciled "
            "clock(s), 32.500 + 2.000 = 34.500 s -> /tmp/t.json")

    def test_reconciled_clocks_are_reported_loudly(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            timeline._warn_reconciliation(
                build((None, "08:15:33", "08:15:34")))
        self.assertIn(
            "1 of 3 clock reading(s) were reconciled", err.getvalue(),
            msg=("a frame paced from a carried-forward clock is worth "
                 "saying out loud while the session is fresh"))

    def test_a_session_with_no_readable_clock_at_all_is_reported(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            timeline._warn_reconciliation(build((None, None, None)))
        self.assertIn("not one clock reading", err.getvalue())
        self.assertIn(
            "carries a watch", err.getvalue(),
            msg=("the message names the in-game cause, because that is "
                 "what the operator would otherwise go hunting for"))

    def test_a_conflicting_date_is_reported_differently(self):
        # A date line that positively contradicts the clock's day is a
        # different failure from a day nothing established, and
        # --require-date has to say which.
        document = build_dated((
            ("08:15:33", "Thursday, Mar 8"),
            ("08:15:30", "Thursday, Mar 8"),
        ))
        self.assertEqual(
            document["date_conflict_count"], 1,
            msg=("a clock that went backwards while the date line "
                 "stayed put did NOT cross midnight, and the artifact "
                 "records the conflict"))
        problems = timeline._date_evidence_problems(document)
        self.assertTrue(problems)
        self.assertTrue(
            any("contradicts" in problem for problem in problems),
            msg="the contradiction is named as one: %r" % problems)
        self.assertFalse(
            any(timeline.AGREE_UNVERIFIED in problem
                for problem in problems),
            msg=("a day the evidence contradicted must not be reported "
                 "as a day nothing established: an operator needs to "
                 "know which one to go and look at"))

    def test_load_manifest_rows_speaks_one_exception_type(self):
        _write_lines(self.manifest, ["{not json"])
        with self.assertRaises(timeline.TimelineError):
            timeline.load_manifest_rows(self.manifest, root=self.directory)
        with self.assertRaises(timeline.TimelineError):
            timeline.load_manifest_rows(
                os.path.join(self.directory, "absent.jsonl"),
                root=self.directory)
        self.write_manifest(("08:15:33",))
        self.assertEqual(
            len(timeline.load_manifest_rows(
                self.manifest, root=self.directory)), 1,
            msg="and it returns the rows in file order when it can")

    def test_the_committed_artifacts_are_never_touched(self):
        # The belt to the braces of the redirected environment: after a
        # full run in the temporary directory, the real playthrough/
        # tree must be exactly as it was.
        tooling = os.path.dirname(os.path.abspath(timeline.__file__))
        root = os.path.dirname(tooling)
        watched = [os.path.join(root, "timeline.json"),
                   os.path.join(root, "manifest.jsonl"),
                   os.path.join(root, "build")]
        before = [(path, os.path.exists(path)) for path in watched]
        self.assertEqual(self.run_main("--quiet")[0], 0)
        for path, existed in before:
            with self.subTest(path=path):
                self.assertEqual(
                    os.path.exists(path), existed,
                    msg="%s was created or removed by a test" % path)


class TestArtifactSafetyAndPurity(unittest.TestCase):
    """The suite must not touch the record it exists to protect.

    playthrough/frames/, playthrough/manifest.jsonl and
    playthrough/timeline.json are the captured evidence of a session.
    Recomputing a timeline in memory must leave all of them exactly as
    they were, and the one test that needs a file on disk works in a
    temporary directory it removes afterwards.
    """

    # The distributions declared in playthrough/tooling/requirements.txt.
    # None of them may be reachable from the module under test, because
    # the timeline has to be recomputable and auditable in a checkout
    # where the render toolchain was never provisioned.
    THIRD_PARTY = ("moviepy", "PIL", "pytesseract", "numpy",
                   "imageio", "imageio_ffmpeg")

    def playthrough_dir(self):
        """Return the real playthrough/ directory, read-only."""
        tooling = os.path.dirname(os.path.abspath(timeline.__file__))
        return os.path.dirname(tooling)

    def artifact_paths(self):
        """Return the committed artifacts this suite must not touch."""
        root = self.playthrough_dir()
        return (os.path.join(root, "timeline.json"),
                os.path.join(root, "manifest.jsonl"),
                os.path.join(root, "frames"))

    def test_the_module_imports_nothing_from_requirements(self):
        for name in self.THIRD_PARTY:
            with self.subTest(package=name):
                self.assertNotIn(
                    name, vars(timeline),
                    msg=("timeline.py must not reach for %s; the "
                         "arithmetic has to run on a bare interpreter"
                         % name))

    def test_computing_a_timeline_touches_no_artifact(self):
        before = [(path, os.path.exists(path))
                  for path in self.artifact_paths()]
        stamps = [(path, os.path.getmtime(path))
                  for path, exists in before if exists]
        document = reference_document()
        timeline.encode_timeline(document)
        timeline.validate_timeline(document)
        for path, existed in before:
            with self.subTest(path=path):
                self.assertEqual(
                    os.path.exists(path), existed,
                    msg=("%s was created or removed by a computation "
                         "that must be pure" % path))
        for path, stamp in stamps:
            with self.subTest(path=path):
                self.assertEqual(
                    os.path.getmtime(path), stamp,
                    msg="%s was modified by a pure computation" % path)

    def test_the_computation_is_repeatable(self):
        first = reference_document()
        second = reference_document()
        self.assertEqual(
            first, second,
            msg=("the same rows must always give the same timeline; "
                 "nothing may depend on the clock, the environment or "
                 "iteration order"))
        self.assertEqual(
            timeline.encode_timeline(first),
            timeline.encode_timeline(second),
            msg=("the encoding must be byte-identical, which is what "
                 "makes the committed artifact diffable"))

    def test_the_encoding_ends_with_exactly_one_newline(self):
        text = timeline.encode_timeline(reference_document())
        self.assertTrue(
            text.endswith("\n"),
            msg="a committed text artifact ends with a newline")
        self.assertFalse(
            text.endswith("\n\n"),
            msg="one trailing newline, not two")
        self.assertNotIn(
            "\r", text,
            msg="LF endings only, whatever the platform")

    def test_a_write_and_read_round_trip_in_a_temporary_directory(self):
        document = reference_document()
        with tempfile.TemporaryDirectory() as directory:
            # The temporary directory is passed as the approved root,
            # which is the ONLY supported way to move the tree: the
            # module derives it from its own location otherwise, so no
            # environment variable can redirect a real artifact.
            root = os.path.realpath(directory)
            path = os.path.join(root, "timeline.json")
            written = timeline.write_timeline(path, document, root=root)
            self.assertEqual(
                written, path,
                msg="write_timeline returns the path it wrote")
            restored = timeline.read_timeline(path, root=root)
            self.assertEqual(
                restored, document,
                msg=("the artifact must round trip through JSON "
                     "without losing or changing a number"))
            self.assertEqual(
                timeline.validate_timeline(restored), [],
                msg="the reloaded timeline still passes every check")
            self.assertEqual(
                sorted(os.listdir(root)), ["timeline.json"],
                msg=("an atomic write leaves no temporary file "
                     "beside the artifact"))

    def test_writing_a_failing_timeline_is_refused(self):
        document = reference_document()
        document["total"] = 99.0
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.realpath(directory)
            path = os.path.join(root, "timeline.json")
            with self.assertRaises(
                    timeline.TimelineError,
                    msg=("a timeline that fails its own checks must "
                         "not reach the disk, where the renderer and "
                         "the caption generator would both trust it")):
                timeline.write_timeline(path, document, root=root)
            self.assertFalse(
                os.path.exists(path),
                msg="nothing may be written when validation fails")
            self.assertEqual(
                os.listdir(root), [],
                msg=("a refused write leaves no temporary file "
                     "either"))

    def test_reading_a_missing_timeline_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.realpath(directory)
            path = os.path.join(root, "absent.json")
            with self.assertRaises(timeline.TimelineError):
                timeline.read_timeline(path, root=root)

    def test_round_seconds_normalises_to_milliseconds(self):
        self.assertEqual(
            timeline.round_seconds(0.2500004), 0.25,
            msg="anything finer than a millisecond is false precision")
        self.assertEqual(
            timeline.round_seconds(-0.0), 0.0,
            msg=("a negative zero in a committed artifact is diff "
                 "noise and is normalised away"))
        for value in (True, "1.0", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(timeline.TimelineError):
                    timeline.round_seconds(value)


class TestDateEvidenceSidecar(unittest.TestCase):
    """The per-frame date audit: read it, key it off the rows, trust
    only what was actually observed."""

    def setUp(self):
        self.tmp = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_tl_audit_"))
        # build/frame_dates.jsonl inside the nominated root: ocr_clock.py
        # now appends to exactly that relative name, so the round-trip
        # test below has to write where the real writer writes.
        os.mkdir(os.path.join(self.tmp, "build"))
        self.audit = os.path.join(self.tmp, "build",
                                  "frame_dates.jsonl")

    def read(self, path=None, digests=None):
        """Read the sidecar, holding the module to THIS directory.

        `root=` is the call-site-only seam every filesystem entry point
        in the module carries: the reader is confined to an approved
        tree, and a suite that owns a temporary directory says so
        rather than being exempted from the confinement.
        """
        return timeline.read_date_audit(
            self.audit if path is None else path, root=self.tmp,
            digests=digests)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, records):
        with open(self.audit, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def record(self, index, date, frame_sha256=None):
        row = {"frame": index,
               "file": FRAME_FILE_FORMAT % index,
               "clock": None, "phrase": None,
               "date": date, "agreement": True}
        if frame_sha256 is not None:
            row["frame_sha256"] = frame_sha256
        return row

    def test_an_absent_sidecar_is_not_an_error(self):
        missing = os.path.join(self.tmp, "nope.jsonl")
        self.assertEqual(
            self.read(missing), {},
            msg=("a session with no date audit has no evidence, which "
                 "is a state to report rather than a failure"))

    def test_a_record_is_read_by_frame_index(self):
        self.write([self.record(1, "Spring, day 3")])
        self.assertEqual(
            self.read(),
            {1: "Spring, day 3"})

    def test_two_readings_that_disagree_leave_the_date_unobserved(self):
        """THE DEFECT THIS TEST EXISTS FOR.

        This used to be a last-occurrence rule: two records that
        contradicted each other about the date were warned about and the
        LATER value was returned anyway, so a contradiction still decided
        a day of game time on nothing but write order.  There is no rule
        by which being written second makes one of two contradictory
        observations the true one.
        """
        self.write([self.record(1, "Spring, day 3"),
                    self.record(1, "Spring, day 4")])
        self.assertEqual(
            self.read(), {1: None},
            msg=("a contradiction is not evidence, so the frame's date "
                 "is unobserved and the rollover guard falls back to "
                 "the bounded rule"))

    def test_two_readings_that_agree_corroborate_each_other(self):
        """A retry within one step legitimately appends a second row."""
        self.write([self.record(1, "Spring, day 3"),
                    self.record(1, "Spring, day 3")])
        self.assertEqual(self.read(), {1: "Spring, day 3"})

    def test_a_later_null_does_not_erase_a_reading(self):
        """THE OTHER HALF OF THE SAME DEFECT, and it was silent.

        `null` is the ordinary shape of an unreadable reading, and under
        the last-occurrence rule a later null ERASED a date that had been
        read successfully -- with no warning at all, because a null is
        not a conflict.  An absence of evidence is not counter-evidence.
        """
        self.write([self.record(1, "Spring, day 3"),
                    self.record(1, None)])
        self.assertEqual(self.read(), {1: "Spring, day 3"})

    def test_an_earlier_null_does_not_suppress_a_later_reading(self):
        self.write([self.record(1, None),
                    self.record(1, "Spring, day 3")])
        self.assertEqual(self.read(), {1: "Spring, day 3"})

    def test_a_row_bound_to_other_pixels_is_discarded(self):
        """A reading of a frame that is no longer at that index.

        A withdrawn capture, or a re-photographed step, leaves a row
        describing pixels the frame no longer holds.  Attributing that
        date to whatever now occupies the index is exactly the
        misattribution the binding exists to prevent.
        """
        self.write([self.record(1, "Spring, day 9",
                                frame_sha256="b" * 64)])
        self.assertEqual(
            self.read(digests={1: "a" * 64}), {})

    def test_a_row_bound_to_the_attested_pixels_is_read(self):
        self.write([self.record(1, "Spring, day 3",
                                frame_sha256="a" * 64)])
        for digests in ({1: "a" * 64},
                        {1: {"sha256": "a" * 64, "frame": 1}}):
            with self.subTest(shape=type(digests[1]).__name__):
                self.assertEqual(
                    self.read(digests=digests),
                    {1: "Spring, day 3"})

    def test_an_unbound_row_is_used_and_reported(self):
        """Every row written before the ledger existed is in this state.

        Discarding them would throw away the whole captured session's
        date evidence; presenting them as checked would be a false
        claim.  They are used, and the fact is reported.
        """
        self.write([self.record(1, "Spring, day 3")])
        self.assertEqual(
            self.read(digests={1: "a" * 64}),
            {1: "Spring, day 3"})

    def test_a_malformed_line_is_fatal_not_skipped(self):
        """DROPPING A ROW CHANGES THE EVIDENCE, which is the point.

        This used to be reported and skipped, on the reasoning that
        corroborating evidence can only be lost, never made wrong.  A
        code review showed the reasoning is false: two rows carrying one
        date make a backwards clock a same-date reconciliation, and
        losing one of them makes the same clock an unevidenced wrap the
        bounded rule may believe -- a different, wrong timeline,
        published while every count still tallies.  So a file that
        exists is read whole or not at all.
        """
        with open(self.audit, "w", encoding="utf-8") as handle:
            handle.write("{not json\n")
            handle.write(json.dumps(self.record(2, "Spring, day 3")))
            handle.write("\n")
        with self.assertRaises(timeline.TimelineError) as caught:
            self.read()
        self.assertIn("is not JSON", str(caught.exception))

    def test_every_malformed_shape_is_fatal(self):
        """Each shape the reader can meet, and none of them is skipped."""
        for name, rows in (
            ("not an object", ["[1, 2, 3]"]),
            ("no frame index", ['{"date": "Spring, day 3"}']),
            ("a string index", '{"frame": "1", "date": "x"}'),
            ("a boolean index", '{"frame": true, "date": "x"}'),
            ("a numeric date", '{"frame": 1, "date": 3}'),
            ("a listed date", '{"frame": 1, "date": ["x"]}'),
        ):
            with self.subTest(shape=name):
                with open(self.audit, "w", encoding="utf-8") as handle:
                    for line in ([rows] if isinstance(rows, str)
                                 else rows):
                        handle.write(line + "\n")
                    handle.write(
                        json.dumps(self.record(2, "Spring, day 3")))
                    handle.write("\n")
                with self.assertRaises(timeline.TimelineError):
                    self.read()

    def test_an_absent_audit_is_still_no_evidence_at_all(self):
        """The one state that legitimately means "nothing was read".

        Asserted beside the refusals above so the boundary is explicit:
        a file that EXISTS is a claim and is read whole or not at all,
        while no file at all is a complete, honest state.
        """
        self.write([self.record(1, "Spring, day 3")])
        os.unlink(self.audit)
        self.assertEqual(self.read(), {})

    def test_an_unread_date_is_recorded_as_none(self):
        self.write([self.record(1, None)])
        self.assertEqual(self.read(),
                         {1: None})

    def test_the_evidence_is_keyed_off_the_rows(self):
        # A frame withdrawn after its audit record was written leaves an
        # orphan record behind.  It must not be attributed to any row.
        rows = make_rows(("08:00:00", "08:00:01"))
        dates = {1: "Spring, day 3", 99: "Autumn, day 61"}
        self.assertEqual(
            timeline.date_lines_for_rows(rows, dates),
            ["Spring, day 3", None],
            msg=("the manifest is the evidence and the sidecar only "
                 "corroborates it; a record for a frame no row "
                 "mentions is ignored"))

    def test_the_lineup_is_always_as_long_as_the_rows(self):
        rows = make_rows(("08:00:00", None, "08:00:05"))
        self.assertEqual(
            len(timeline.date_lines_for_rows(rows, {})), len(rows))

    def test_normalise_date_compares_only_for_change(self):
        self.assertEqual(
            timeline.normalise_date("Spring,  day 3"),
            timeline.normalise_date("Spring, day 3"),
            msg=("two OCR passes that spaced the same date "
                 "differently must not read as two different days"))
        self.assertNotEqual(
            timeline.normalise_date("Spring, day 3"),
            timeline.normalise_date("Spring, day 4"))
        for value in (None, 3, ""):
            with self.subTest(value=value):
                self.assertIsNone(timeline.normalise_date(value))

    # The exit status the writer subprocess uses to report that
    # ocr_clock.py could not be IMPORTED, as distinct from any other
    # failure.  It has to be distinguishable: a refused write and an
    # absent dependency are different facts, and a suite that skipped
    # on both would report the wrong cause for the wrong one -- which
    # is exactly how this assertion came to be silently unrunnable.
    IMPORT_FAILED_STATUS = 3

    def test_the_sidecar_round_trips_from_ocr_clocks_own_writer(self):
        # THE CONTRACT BETWEEN THE TWO MODULES.  timeline.py cannot
        # import ocr_clock.py -- that would make Pillow a dependency of
        # computing a timeline -- so the field names are asserted
        # against a sidecar the real writer produced.
        #
        # THE ROOT IS PASSED TO THE WRITER.  ocr_clock.append_date_audit
        # confines its one write to approved_artifact_root(root), which
        # without a nomination is the committed playthrough/ tree -- so a
        # call that omitted the root would be REFUSED for a temporary
        # path, which is not a missing dependency and must never be
        # reported as one.  read_date_audit() below is held to the same
        # directory, so both sides of the round trip are confined to a
        # directory this test owns.
        tooling = os.path.dirname(os.path.abspath(timeline.__file__))
        script = os.path.join(tooling, "ocr_clock.py")
        if not os.path.isfile(script):
            self.skipTest("ocr_clock.py is not beside timeline.py")
        program = (
            "import sys;"
            "sys.dont_write_bytecode = True;"
            "sys.path.insert(0, %r);"
            "\ntry:\n"
            "    import ocr_clock\n"
            "except Exception as err:\n"
            "    sys.stderr.write('import failed: %%r' %% (err,))\n"
            "    raise SystemExit(%d)\n"
            "r = ocr_clock.SidebarReading("
            "    png='p', rect='288x1072+1632+4', clock='08:15:32',"
            "    phrase=None, date='Spring, day 3', text='')\n"
            "ocr_clock.append_date_audit(%r, 1, r, %r)\n"
            % (tooling, self.IMPORT_FAILED_STATUS, self.audit,
               self.tmp))
        done = subprocess.run(
            [sys.executable, "-B", "-c", program],
            capture_output=True, text=True, timeout=120)
        if done.returncode == self.IMPORT_FAILED_STATUS:
            # The only legitimate skip: this interpreter cannot load the
            # OCR module at all.  The suite is required to run on a bare
            # interpreter, so that is a real state -- and it is now
            # stated as itself rather than standing in for everything.
            self.skipTest(
                "ocr_clock.py cannot be imported by %s, so its writer "
                "cannot be exercised here: %s"
                % (sys.executable, done.stderr.strip()[:200]))
        self.assertEqual(
            done.returncode, 0,
            msg=("ocr_clock.py imported but its writer failed, which is "
                 "a broken contract rather than a missing dependency: "
                 "%s" % done.stderr.strip()[:400]))
        self.assertEqual(
            self.read(),
            {1: "Spring, day 3"},
            msg=("timeline.py must read what ocr_clock.py writes; if "
                 "this fails the two have drifted apart"))

    def test_the_sidecar_field_names_are_the_agreed_contract(self):
        # THE HALF OF THE CONTRACT THAT NEEDS NO INTERPRETER.  The round
        # trip above is the stronger check but it can only run where
        # ocr_clock.py imports.  The field NAMES are readable from its
        # source with the standard library alone, so a rename on either
        # side is caught even on a bare interpreter -- which is where
        # this suite is required to run.
        tooling = os.path.dirname(os.path.abspath(timeline.__file__))
        script = os.path.join(tooling, "ocr_clock.py")
        if not os.path.isfile(script):
            self.skipTest("ocr_clock.py is not beside timeline.py")
        declared = None
        for node in ast.walk(ast.parse(_read_text(script))):
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets
                     if isinstance(target, ast.Name)]
            if "DATE_AUDIT_FIELDS" not in names:
                continue
            declared = tuple(
                element.value for element in node.value.elts
                if isinstance(element, ast.Constant))
        self.assertEqual(
            declared,
            ("frame", "file", "clock", "phrase", "date", "agreement",
             "frame_sha256"),
            msg=("ocr_clock.DATE_AUDIT_FIELDS is the sidecar's shape "
                 "and timeline.py reads it by name; a change here is a "
                 "change to a cross-module contract"))
        self.assertIn(
            timeline.AUDIT_SHA256_FIELD, declared,
            msg=("timeline.py binds a row to the pixels it was read "
                 "from through %r, which the writer must emit"
                 % timeline.AUDIT_SHA256_FIELD))
        self.assertIn(
            timeline.AUDIT_FRAME_FIELD, declared,
            msg=("timeline.py keys the sidecar off %r, which the writer "
                 "must still emit" % timeline.AUDIT_FRAME_FIELD))
        self.assertIn(
            timeline.AUDIT_DATE_FIELD, declared,
            msg=("timeline.py takes the date from %r, which the writer "
                 "must still emit" % timeline.AUDIT_DATE_FIELD))


class TestManifestGateIsAuthoritative(unittest.TestCase):
    """F11: the gate delegates to manifest.py's own validators."""

    def rows(self):
        return make_rows(("08:00:00", "08:00:01"))

    def test_a_correct_manifest_passes(self):
        self.assertEqual(timeline.manifest_row_problems(self.rows()), [])

    def test_a_wrong_frame_path_is_caught(self):
        # A non-empty string that is not the canonical name for its
        # index is exactly what a shape-only check would let through.
        rows = self.rows()
        rows[1]["file"] = "playthrough/frames/frame_00001.png"
        self.assertTrue(
            timeline.manifest_row_problems(rows),
            msg=("a row naming another frame's capture must be "
                 "refused, not merely checked for emptiness"))

    def test_a_malformed_timestamp_is_caught(self):
        rows = self.rows()
        rows[0]["real_ts"] = "yesterday"
        self.assertTrue(
            timeline.manifest_row_problems(rows),
            msg="a real_ts that does not parse must be refused")

    def test_a_missing_field_is_caught(self):
        rows = self.rows()
        del rows[0]["commentary"]
        self.assertTrue(timeline.manifest_row_problems(rows))

    def test_an_index_gap_is_caught(self):
        rows = self.rows()
        rows[1]["frame"] = 3
        rows[1]["file"] = FRAME_FILE_FORMAT % 3
        self.assertTrue(timeline.manifest_row_problems(rows))

    def test_the_gate_is_strict_unless_explicitly_relaxed(self):
        rows = self.rows()
        rows[1]["frame"] = 3
        rows[1]["file"] = FRAME_FILE_FORMAT % 3
        self.assertTrue(
            timeline.manifest_row_problems(rows),
            msg="the default gate reports an out-of-sequence index")
        self.assertEqual(
            timeline.manifest_row_problems(
                rows, allow_index_gaps=True), [],
            msg=("the tolerance is an explicit argument, so the strict "
                 "gate can never be relaxed by accident"))


class TestNoWriteBypassRemains(unittest.TestCase):
    """F12: nothing writes a timeline from invalid evidence.

    Every path here is inside a temporary directory this class owns and
    nominates as the approved root, and all four PLAYTHROUGH_*
    variables are redirected into it for the duration -- the same
    discipline TestTimelineCliAndIo follows, for the same two reasons.
    A bug in this suite must not be able to reach the committed
    evidence; and main() resolves the telemetry and date-audit
    DEFAULTS, which an ambient export from env.sh would otherwise point
    at the committed tree, outside the root nominated here, where the
    containment guard would rightly refuse them.  The suite has to be
    green whether or not the pipeline's environment has been sourced.
    """

    def setUp(self):
        self.tmp = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_tl_cli_"))
        self.addCleanup(_remove_tree, self.tmp)
        self.manifest = os.path.join(self.tmp, "manifest.jsonl")
        self.output = os.path.join(self.tmp, "timeline.json")
        self.observations = os.path.join(self.tmp, "observations.jsonl")
        self.audit = os.path.join(self.tmp, "frame_dates.jsonl")
        self.env = _environment(
            PLAYTHROUGH_MANIFEST=self.manifest,
            PLAYTHROUGH_TIMELINE=self.output,
            PLAYTHROUGH_OBSERVATIONS=self.observations,
            PLAYTHROUGH_DATE_AUDIT=self.audit)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    def write_manifest(self, rows):
        """Write the rows AND seal the captures they name.

        The frames follow the record here, because the subject of this
        suite is which manifests produce a write -- so every manifest it
        writes has to arrive with the captures it describes, attested.
        """
        with open(self.manifest, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        reseal_captures(self.tmp, frame_indexes(rows))

    def run_cli(self, *args):
        return timeline.main(
            ["--manifest", self.manifest, "-o", self.output,
             "--quiet"] + list(args),
            root=self.tmp)

    def test_every_bypass_is_off_by_default_and_announces_itself(self):
        # The two overrides survive as DIAGNOSTICS, which is what keeps
        # a broken session inspectable.  What must never happen is a
        # bypass that is implicit, or one whose output is
        # indistinguishable from a clean run -- so each is off unless
        # asked for, each says DIAGNOSTIC ONLY in the help, and each
        # names itself on stderr when it is used.
        parser = timeline.build_parser()
        defaults = parser.parse_args([])
        for name in ("allow_index_gaps", "ignore_manifest_problems"):
            with self.subTest(flag=name):
                self.assertIs(
                    getattr(defaults, name), False,
                    msg="no bypass may be the default")
                self.assertIs(
                    getattr(parser.parse_args(
                        ["--" + name.replace("_", "-")]), name), True)
        self.assertEqual(
            parser.format_help().count("DIAGNOSTIC ONLY"), 2,
            msg=("both overrides must say what they are for, so "
                 "neither is reached for as a way to make a failing "
                 "run pass"))

    def test_a_good_manifest_is_written(self):
        self.write_manifest(make_rows(("08:00:00", "08:00:01")))
        self.assertEqual(self.run_cli(), 0)
        self.assertTrue(os.path.isfile(self.output))

    def test_an_index_gap_refuses_to_write(self):
        rows = make_rows(("08:00:00", "08:00:01"))
        rows[1]["frame"] = 3
        rows[1]["file"] = FRAME_FILE_FORMAT % 3
        self.write_manifest(rows)
        self.assertEqual(
            self.run_cli(), 1,
            msg="an index gap must fail, with no flag to override it")
        self.assertFalse(
            os.path.exists(self.output),
            msg=("nothing may reach the disk from evidence that failed "
                 "its own check"))

    def test_a_malformed_row_refuses_to_write(self):
        rows = make_rows(("08:00:00", "08:00:01"))
        rows[0]["real_ts"] = "yesterday"
        self.write_manifest(rows)
        self.assertEqual(self.run_cli(), 1)
        self.assertFalse(os.path.exists(self.output))

    def test_a_previous_timeline_survives_a_refused_run(self):
        self.write_manifest(make_rows(("08:00:00", "08:00:01")))
        self.assertEqual(self.run_cli(), 0)
        with open(self.output, encoding="utf-8") as handle:
            good = handle.read()
        rows = make_rows(("08:00:00", "08:00:01"))
        rows[0]["real_ts"] = "yesterday"
        self.write_manifest(rows)
        self.assertEqual(self.run_cli(), 1)
        with open(self.output, encoding="utf-8") as handle:
            self.assertEqual(
                handle.read(), good,
                msg=("a refused run must leave the previous artifact "
                     "byte-identical, not truncated"))


class TestAtomicWrite(unittest.TestCase):
    """F27: the artifact is replaced, never truncated in place."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="blitzy_tl_write_")
        self.output = os.path.join(self.tmp, "timeline.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_write_leaves_no_temporary_file_behind(self):
        timeline.write_timeline(
            self.output, build(("08:00:00", "08:00:01")),
            root=self.tmp)
        self.assertEqual(os.listdir(self.tmp), ["timeline.json"])

    def test_a_refused_document_leaves_the_directory_untouched(self):
        document = build(("08:00:00", "08:00:01"))
        document["total"] = 999.0
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(self.output, document, root=self.tmp)
        self.assertEqual(
            os.listdir(self.tmp), [],
            msg="a document that fails validation writes nothing at all")

    def test_the_artifact_is_readable_after_replacement(self):
        timeline.write_timeline(
            self.output, build(("08:00:00", "08:00:01")),
            root=self.tmp)
        mode = os.stat(self.output).st_mode & 0o777
        self.assertEqual(
            mode, 0o644,
            msg=("the committed artifact carries an ordinary file mode, "
                 "not mkstemp's private 0600"))

    def test_rewriting_replaces_rather_than_appends(self):
        timeline.write_timeline(
            self.output, build(("08:00:00", "08:00:01")),
            root=self.tmp)
        timeline.write_timeline(
            self.output, build(("08:00:00", "08:00:01")),
            root=self.tmp)
        with open(self.output, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["frame_count"], 2)

    def test_the_writer_refuses_a_gap_unless_told_it_is_a_diagnosis(
            self):
        document = build(("08:00:00", "08:00:01", "08:00:02"))
        document["frames"][2]["frame"] = 99
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(self.output, document, root=self.tmp)
        self.assertFalse(
            os.path.exists(self.output),
            msg="nothing reaches the disk from an invalid document")
        timeline.write_timeline(
            self.output, document, allow_index_gaps=True,
            root=self.tmp)
        self.assertTrue(
            os.path.isfile(self.output),
            msg=("the tolerance is explicit and named, so a diagnostic "
                 "artifact is always an asked-for one"))


class TestStrictDocumentTypes(unittest.TestCase):
    """F26 and F32: exact types, and no traceback from a bad artifact."""

    def document(self):
        return build(("08:00:00", "08:15:00", "08:15:01"))

    def test_a_non_boolean_transition_flag_is_reported(self):
        for value in ("", "no", 0, 1, None):
            with self.subTest(value=value):
                document = self.document()
                document["frames"][0]["transition_after"] = value
                problems = timeline.validate_timeline(document)
                self.assertTrue(
                    any("not a JSON boolean" in problem
                        for problem in problems),
                    msg=("truthiness is not a type check: %r must be "
                         "refused rather than coerced" % value))

    def test_a_non_boolean_reconciled_flag_is_reported(self):
        document = self.document()
        document["frames"][0]["reconciled"] = "yes"
        self.assertTrue(timeline.validate_timeline(document))

    def test_text_fields_must_be_text(self):
        for name in ("file", "clock_kind", "action", "commentary"):
            with self.subTest(field=name):
                document = self.document()
                document["frames"][0][name] = 42
                self.assertTrue(
                    any("not text" in problem for problem in
                        timeline.validate_timeline(document)))

    def test_nullable_text_fields_reject_other_types(self):
        for name in ("real_ts", "ingame_clock", "reconciled_reason"):
            with self.subTest(field=name):
                document = self.document()
                document["frames"][0][name] = 42
                self.assertTrue(timeline.validate_timeline(document))

    def test_a_malformed_document_number_is_reported_not_raised(self):
        for name in ("floor", "ceil", "transition", "total_duration",
                     "total_transition", "total", "final_cue_end"):
            for value in ("ten", None, [], float("nan"),
                          float("inf")):
                with self.subTest(field=name, value=value):
                    document = self.document()
                    document[name] = value
                    try:
                        problems = timeline.validate_timeline(document)
                    except (ValueError, TypeError) as err:
                        self.fail(
                            "validate_timeline raised %s for %s=%r; a "
                            "malformed artifact must be diagnosed, not "
                            "crash the validator"
                            % (type(err).__name__, name, err))
                    self.assertTrue(
                        problems,
                        msg="%s=%r must be reported" % (name, value))

    def test_a_malformed_count_is_reported_not_raised(self):
        for name in ("version", "frame_count", "transition_count",
                     "reconciled_count"):
            for value in ("two", 2.5, None, True):
                with self.subTest(field=name, value=value):
                    document = self.document()
                    document[name] = value
                    try:
                        problems = timeline.validate_timeline(document)
                    except (ValueError, TypeError) as err:
                        self.fail("validate_timeline raised %s: %s"
                                  % (type(err).__name__, err))
                    self.assertTrue(problems)

    def test_a_negative_total_is_reported(self):
        document = self.document()
        document["total"] = -1.0
        self.assertTrue(timeline.validate_timeline(document))

    def test_a_correct_document_still_validates(self):
        self.assertEqual(
            timeline.validate_timeline(self.document()), [],
            msg=("the strictness must not reject the module's own "
                 "output"))


class TestBytecodeHygiene(unittest.TestCase):
    """F33: running the module standalone leaves no __pycache__.

    WHY THIS RUNS A COPY, IN A TEMPORARY DIRECTORY.  The regression it
    detects is bytecode being written beside the module -- and beside the
    REAL module means inside playthrough/tooling/, the one tree whose
    terminal `!/playthrough/**` negation re-includes everything, where the
    checkpoint's own hygiene gate then refuses to commit while it is
    there.  So a test that detected the regression by provoking it in the
    working tree would leave the working tree needing a repair, and it
    had to skip itself whenever a __pycache__ was already present, which
    is exactly when the question matters least.

    A copy in a system temporary directory answers the same question --
    the module's `sys.dont_write_bytecode = True` is what suppresses the
    cache, and it travels with the bytes -- and its residue is thrown
    away with the directory.  The real folder is checked too, as an
    assertion rather than as a skip condition.
    """

    # The module under test, and the sibling it imports.  timeline.py
    # imports manifest at module scope, so a copy without it would fail
    # to start and the test would pass for the wrong reason.
    COPIED = ("timeline.py", "manifest.py")

    def setUp(self):
        self.tooling = os.path.dirname(os.path.abspath(timeline.__file__))
        self.temporary = tempfile.TemporaryDirectory(
            prefix="blitzy_bytecode_")
        self.addCleanup(self.temporary.cleanup)
        self.copy = os.path.join(self.temporary.name, "tooling")
        os.makedirs(self.copy)
        for name in self.COPIED:
            shutil.copyfile(os.path.join(self.tooling, name),
                            os.path.join(self.copy, name))

    def run_without_the_environment_guard(self, directory):
        """Run `timeline.py --help` from `directory`, bytecode enabled.

        PYTHONDONTWRITEBYTECODE is removed and -B is NOT passed, so the
        only thing left standing between a run and a __pycache__ is the
        module's own statement -- which is the subject.
        """
        environment = dict(os.environ)
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        done = subprocess.run(
            [sys.executable, os.path.join(directory, "timeline.py"),
             "--help"],
            capture_output=True, text=True, timeout=120,
            env=environment)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def test_a_standalone_run_writes_no_pycache(self):
        self.run_without_the_environment_guard(self.copy)
        cache = os.path.join(self.copy, "__pycache__")
        self.assertFalse(
            os.path.exists(cache),
            msg=("a standalone run left %s behind; against the real "
                 "module that residue would be committable and the "
                 "checkpoint's hygiene gate would refuse until it was "
                 "removed" % cache))

    def test_the_copy_really_is_the_module_under_test(self):
        """Byte for byte, so this cannot pass against a stale copy."""
        for name in self.COPIED:
            with self.subTest(module=name):
                with open(os.path.join(self.tooling, name), "rb") as one:
                    with open(os.path.join(self.copy, name), "rb") as two:
                        self.assertEqual(one.read(), two.read())

    def test_the_copy_would_have_shown_the_regression(self):
        """The harness is proved able to FAIL before it is trusted.

        A copy with the statement removed writes a __pycache__ where the
        real one does not -- so the assertion above is measuring the
        module's own instruction and not the interpreter's mood.
        """
        source = os.path.join(self.copy, "timeline.py")
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        marker = "sys.dont_write_bytecode = True"
        self.assertIn(marker, text)
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(text.replace(
                marker, "sys.dont_write_bytecode = False", 1))
        self.run_without_the_environment_guard(self.copy)
        self.assertTrue(
            os.path.isdir(os.path.join(self.copy, "__pycache__")),
            msg="the harness cannot detect the regression it exists for")

    def test_the_real_tooling_folder_holds_no_bytecode(self):
        """Asserted, not skipped over.

        The old form of this test skipped when a __pycache__ was already
        present, which is the one state worth reporting.
        """
        for name in ("__pycache__",):
            with self.subTest(name=name):
                self.assertFalse(
                    os.path.exists(os.path.join(self.tooling, name)),
                    msg=("%s is in playthrough/tooling/, where the "
                         "terminal negation makes it committable and a "
                         "checkpoint refuses it" % name))
        stray = [name for name in os.listdir(self.tooling)
                 if name.endswith((".pyc", ".pyo"))]
        self.assertEqual(stray, [])

    def test_the_module_disables_bytecode_writing(self):
        self.assertTrue(sys.dont_write_bytecode)


class TestPathsAreConfinedToTheArtifactTree(unittest.TestCase):
    """The timeline may only be read from or written inside the tree.

    The single source of truth for timing is only single if it cannot
    be redirected.  These are the checks that make PLAYTHROUGH_TIMELINE
    and a -o argument safe to accept at all: a path outside
    playthrough/, one reached through a symlink, and one naming
    something other than a regular file are all refused before
    anything is opened.
    """

    def setUp(self):
        self.document = reference_document()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_the_default_path_is_derived_from_the_module(self):
        tooling = os.path.dirname(os.path.abspath(timeline.__file__))
        expected = os.path.realpath(os.path.dirname(tooling))
        self.assertEqual(
            timeline.approved_root(), expected,
            msg=("the approved root comes from this module's own "
                 "location, never from the environment"))
        # UNSET while the module-derived fallback is asserted.  With
        # PLAYTHROUGH_TIMELINE exported the default is that export by
        # design -- test_the_default_timeline_path_follows_the_
        # environment covers it -- so reading the ambient value here
        # would test the shell instead of the module.
        with _environment(PLAYTHROUGH_TIMELINE=None):
            self.assertTrue(
                os.path.realpath(
                    timeline.default_timeline_path()).startswith(
                        expected + os.sep),
                msg=("with nothing exported the default artifact is "
                     "derived from the module and lives inside the "
                     "approved root"))

    def test_a_path_outside_the_tree_is_refused(self):
        for candidate in ("/etc/blitzy-timeline.json",
                          "/dev/null",
                          "/tmp/timeline.json"):
            with self.subTest(path=candidate):
                with self.assertRaises(timeline.TimelineError):
                    timeline.write_timeline(candidate, self.document)
                with self.assertRaises(timeline.TimelineError):
                    timeline.read_timeline(candidate)

    def test_a_traversal_out_of_the_tree_is_refused(self):
        escape = os.path.join(
            timeline.approved_root(), "..", "..", "escaped.json")
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(escape, self.document)
        self.assertFalse(
            os.path.exists(os.path.realpath(escape)),
            msg="a refused traversal must not create anything")

    def test_a_symlinked_target_is_refused_and_not_followed(self):
        victim = os.path.join(self.root, "victim.json")
        link = os.path.join(self.root, "timeline.json")
        os.symlink(victim, link)
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(link, self.document, root=self.root)
        self.assertFalse(
            os.path.exists(victim),
            msg=("writing through a link would put the timeline "
                 "wherever the link pointed"))
        with self.assertRaises(timeline.TimelineError):
            timeline.read_timeline(link, root=self.root)

    def test_a_symlinked_directory_component_is_refused(self):
        real = os.path.join(self.root, "real")
        os.mkdir(real)
        os.symlink(real, os.path.join(self.root, "linked"))
        through = os.path.join(self.root, "linked", "timeline.json")
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(
                through, self.document, root=self.root)
        self.assertEqual(
            os.listdir(real), [],
            msg="nothing may be written through a linked directory")

    def test_a_target_that_is_not_a_regular_file_is_refused(self):
        fifo = os.path.join(self.root, "timeline.json")
        os.mkfifo(fifo)
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(fifo, self.document, root=self.root)

    def test_an_injected_root_must_be_a_real_directory(self):
        with self.assertRaises(timeline.TimelineError):
            timeline.approved_root(
                os.path.join(self.root, "not-there"))
        for bad in ("", "   ", "\x00", 7):
            with self.subTest(root=bad):
                with self.assertRaises(timeline.TimelineError):
                    timeline.approved_root(bad)

    # -- the EVIDENCE readers, held to the same contract ------------
    #
    # The date audit and the capture telemetry decide whether a day
    # passed.  Reading them is not harmless: a redirected read paces
    # the film from another session's evidence while the timeline it
    # produces still validates, still matches its own manifest and
    # still reports success.  Both readers are therefore confined
    # exactly as the artifact itself is.

    def test_the_evidence_readers_refuse_a_path_outside_the_tree(self):
        for candidate in ("/etc/passwd", "/dev/null",
                          "/tmp/observations.jsonl"):
            with self.subTest(path=candidate):
                with self.assertRaises(timeline.TimelineError):
                    timeline.load_observations(candidate)
                with self.assertRaises(timeline.TimelineError):
                    timeline.read_date_audit(candidate)

    def test_the_evidence_readers_refuse_a_traversal(self):
        escape = os.path.join(
            timeline.approved_root(), "..", "..", "evidence.jsonl")
        with self.assertRaises(timeline.TimelineError):
            timeline.load_observations(escape)
        with self.assertRaises(timeline.TimelineError):
            timeline.read_date_audit(escape)

    def test_the_evidence_readers_refuse_a_symlink(self):
        victim = os.path.join(self.root, "somebody-elses.jsonl")
        with open(victim, "w", encoding="utf-8") as handle:
            handle.write('{"frame": 1, "date": "Friday, Mar 9"}\n')
        link = os.path.join(self.root, "observations.jsonl")
        os.symlink(victim, link)
        with self.assertRaises(timeline.TimelineError):
            timeline.load_observations(link, root=self.root)
        with self.assertRaises(timeline.TimelineError):
            timeline.read_date_audit(link, root=self.root)

    def test_the_evidence_readers_refuse_a_linked_component(self):
        real = os.path.join(self.root, "real")
        os.mkdir(real)
        with open(os.path.join(real, "observations.jsonl"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"frame": 1, "date": "Friday, Mar 9"}\n')
        os.symlink(real, os.path.join(self.root, "linked"))
        through = os.path.join(
            self.root, "linked", "observations.jsonl")
        with self.assertRaises(timeline.TimelineError):
            timeline.load_observations(through, root=self.root)
        with self.assertRaises(timeline.TimelineError):
            timeline.read_date_audit(through, root=self.root)

    def test_the_evidence_defaults_follow_the_approved_root(self):
        with _environment(PLAYTHROUGH_OBSERVATIONS=None,
                          PLAYTHROUGH_DATE_AUDIT=None):
            for path in (timeline.default_observations_path(self.root),
                         timeline.default_date_audit_path(self.root)):
                with self.subTest(path=path):
                    self.assertTrue(
                        path.startswith(self.root + os.sep),
                        msg=("a nominated root that did not move the "
                             "defaults would send a confined reader "
                             "at the committed tree"))
            self.assertTrue(
                timeline.default_observations_path().startswith(
                    timeline.approved_root() + os.sep),
                msg="and with no nomination the committed tree is it")

    def test_a_nominated_root_outranks_the_environment(self):
        # THE PRECEDENCE THAT KEEPS A CONFINED CALLER USABLE.  env.sh
        # exports both sidecar paths at the committed tree.  If an
        # ambient export outranked a nomination, a caller that confined
        # itself to its own directory would be handed a path OUTSIDE
        # that directory and then refused by the guard above -- so the
        # nomination, which IS the containment boundary, comes first.
        # A caller wanting a particular file inside its own root names
        # it in the argument, which outranks either default.
        committed = timeline.approved_root()
        exported = os.path.join(
            committed, "build", "observations.jsonl")
        exported_audit = os.path.join(
            committed, "build", "frame_dates.jsonl")
        with _environment(PLAYTHROUGH_OBSERVATIONS=exported,
                          PLAYTHROUGH_DATE_AUDIT=exported_audit):
            self.assertEqual(
                timeline.default_observations_path(self.root),
                os.path.join(self.root, "observations.jsonl"),
                msg=("an ambient export must not defeat a nominated "
                     "root; it names a path the guard would refuse"))
            self.assertEqual(
                timeline.default_date_audit_path(self.root),
                os.path.join(self.root, "frame_dates.jsonl"),
                msg=("the date-evidence default follows the same "
                     "precedence -- it is the fourth variable, and "
                     "the one whose omission broke this suite"))
            self.assertIsNone(
                timeline.load_observations(root=self.root),
                msg=("and the reader must WORK rather than raise: an "
                     "absent sidecar inside the nominated root is an "
                     "ordinary state, not a containment failure"))
            self.assertEqual(
                timeline.read_date_audit(root=self.root), {},
                msg="the same for the date evidence")
            self.assertEqual(
                timeline.default_observations_path(), exported,
                msg=("with NO nomination env.sh still defines the "
                     "layout, which is how the pipeline finds the "
                     "sidecar capture.sh actually wrote"))

    def test_evidence_inside_the_approved_root_is_read_normally(self):
        path = os.path.join(self.root, "observations.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"frame": 1, "date": "Friday, Mar 9"}\n')
        self.assertEqual(
            timeline.load_observations(path, root=self.root)[1]["date"],
            "Friday, Mar 9",
            msg=("the confinement must refuse only what is outside it; "
                 "a gate that refused the real sidecar would be worse "
                 "than none"))


class TestTheWriteIsAtomic(unittest.TestCase):
    """A reader sees the whole timeline or the whole previous one.

    render_movie.py and make_srt.py both consume this file, so a
    half-written document would desynchronise the movie from its
    captions while every count still tallied.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.path = os.path.join(self.root, "timeline.json")
        self.addCleanup(self.temporary.cleanup)

    def contents(self):
        """Return the artifact's text, without leaking a handle."""
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_a_rewrite_replaces_the_file_rather_than_truncating_it(
            self):
        timeline.write_timeline(
            self.path, reference_document(), root=self.root)
        before = os.stat(self.path)
        second = build(["08:15:32", "08:15:33"])
        timeline.write_timeline(self.path, second, root=self.root)
        after = os.stat(self.path)
        self.assertNotEqual(
            before.st_ino, after.st_ino,
            msg=("the artifact must arrive by rename: a new inode is "
                 "the observable signature of an atomic replacement, "
                 "and truncating the old file in place would reuse "
                 "the same one"))
        self.assertEqual(
            timeline.read_timeline(self.path, root=self.root), second,
            msg="the replacement is the whole new document")
        self.assertEqual(
            sorted(os.listdir(self.root)), ["timeline.json"],
            msg="no temporary file survives a successful write")

    def test_a_reader_holding_the_old_file_never_sees_a_partial_one(
            self):
        first = reference_document()
        timeline.write_timeline(self.path, first, root=self.root)
        original = timeline.encode_timeline(first)
        # A reader that opened the artifact before the rewrite is the
        # concrete case this protects: render_movie.py and make_srt.py
        # both read this file, and an in-place rewrite would change --
        # or truncate -- what they are part way through reading.
        with open(self.path, "r", encoding="utf-8") as reader:
            timeline.write_timeline(
                self.path, build(["08:15:32", "08:15:33"]),
                root=self.root)
            self.assertEqual(
                reader.read(), original,
                msg=("an open reader must still see the WHOLE previous "
                     "document; with an in-place write it would see "
                     "the new bytes or none at all"))

    def test_a_refused_write_leaves_the_previous_artifact_intact(self):
        timeline.write_timeline(
            self.path, reference_document(), root=self.root)
        original = self.contents()
        broken = reference_document()
        broken["total"] = 99.0
        with self.assertRaises(timeline.TimelineError):
            timeline.write_timeline(self.path, broken, root=self.root)
        self.assertEqual(
            self.contents(), original,
            msg=("a failed write must leave the previous artifact "
                 "exactly as it was"))
        self.assertEqual(
            sorted(os.listdir(self.root)), ["timeline.json"],
            msg="a failed write leaves no debris either")


class TestTheCommandLineGatesTheManifest(unittest.TestCase):
    """--verify must attest, not merely agree with itself.

    Byte-identity between the stored timeline and a fresh computation
    proves that this file was computed from this manifest by this code.
    It proves NOTHING about whether the manifest is a record of a
    session, because a defect in a row lands on both sides of the
    comparison and cancels out: a row whose `file` names
    frame_00099.png while its `frame` says 1, with "yesterday" where a
    capture timestamp belongs, produces a timeline that matches itself
    exactly.  These tests exist because that hole was real -- the
    verification path read its rows straight past the gate that
    generation applies -- and they fail if it is ever reopened.

    The real command line is exercised, exit status included, against a
    temporary directory passed as the approved root, with all four
    PLAYTHROUGH_* variables redirected into it so that the run depends
    on nothing ambient.  Nothing here touches playthrough/manifest.jsonl
    or playthrough/timeline.json.
    """

    # The reviewer's reproduction, kept verbatim: frame 1 pointing at
    # another frame's capture, and a real_ts that is not a timestamp.
    WRONG_CAPTURE = "playthrough/frames/frame_00099.png"
    MALFORMED_REAL_TS = "yesterday"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        # main() resolves the telemetry and date-audit defaults from the
        # environment when nothing is nominated, and env.sh exports both
        # at the committed tree.  Redirecting all four into this root
        # keeps the exit statuses asserted below a property of the code
        # under test rather than of whether env.sh was sourced first.
        self.env = _environment(
            PLAYTHROUGH_MANIFEST=os.path.join(
                self.root, "manifest.jsonl"),
            PLAYTHROUGH_TIMELINE=os.path.join(
                self.root, "timeline.json"),
            PLAYTHROUGH_OBSERVATIONS=os.path.join(
                self.root, "observations.jsonl"),
            PLAYTHROUGH_DATE_AUDIT=os.path.join(
                self.root, "frame_dates.jsonl"))
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        # Two captures, sealed.  Every manifest this suite writes has two
        # rows; the defects under test are in the ROWS, so the frames they
        # name have to exist and be attested or the capture gate would
        # refuse before the row gate is reached.
        seal_captures(self.root, (1, 2))

    def malformed_rows(self):
        """Return rows the canonical gate must refuse."""
        rows = make_rows(("08:15:33", "08:15:34"))
        rows[0]["file"] = self.WRONG_CAPTURE
        rows[0]["real_ts"] = self.MALFORMED_REAL_TS
        return rows

    def write_manifest(self, rows, name="manifest.jsonl"):
        """Write rows as JSON Lines and return the path.

        Written here rather than through manifest.append_row(), which
        validates every field and would refuse a malformed row -- which
        is the point: a manifest like this cannot come from the writer,
        only from tampering or from a defect, and that is exactly the
        input verification has to refuse.
        """
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        # The captures the rows name, sealed, so that the capture gate is
        # satisfied and the ROW gate is the one under test.  A malformed
        # row still names a frame index, and that frame is what a session
        # with this record would have photographed.
        reseal_captures(self.root, frame_indexes(rows))
        return path

    def store_timeline(self, document, name="timeline.json"):
        """Write a timeline into the temporary root and return it."""
        return timeline.write_timeline(
            os.path.join(self.root, name), document, root=self.root)

    def attested(self, rows, manifest_path):
        """Build the document the CLI would write for `manifest_path`.

        --verify claims the artifact on disk describes THIS session, and
        that claim now rests on the attestation the document carries:
        the manifest's relative path, the sha256 of its bytes and its row
        count.  A fixture storing an unattested document would be
        asserting that a timeline of unknown provenance verifies, which
        is exactly the state the gate exists to refuse.
        """
        return timeline.build_timeline(
            rows, None, None,
            timeline.attest_manifest(manifest_path, self.root),
            capture_attestation=timeline.attest_captures(
                os.path.join(self.root, *manifest.DIGESTS_REL_PARTS),
                self.root, verified=len(rows)))

    def run_cli(self, argv):
        """Return (exit status, stdout, stderr) of the real main()."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                status = timeline.main(argv, root=self.root)
        return status, out.getvalue(), err.getvalue()

    def test_the_gate_refuses_a_capture_that_is_not_the_rows_frame(
            self):
        problems = timeline.manifest_row_problems(self.malformed_rows())
        self.assertTrue(
            any(self.WRONG_CAPTURE in problem for problem in problems),
            msg=("a row must name the capture its own index formats "
                 "to; %r against frame 1 has to be reported, or the "
                 "timeline paces a frame nobody photographed"
                 % self.WRONG_CAPTURE))

    def test_the_gate_refuses_a_real_ts_that_is_not_a_timestamp(self):
        problems = timeline.manifest_row_problems(self.malformed_rows())
        self.assertTrue(
            any("real_ts" in problem for problem in problems),
            msg=("real_ts records when the capture actually happened; "
                 "%r is not a moment in time and must be reported"
                 % self.MALFORMED_REAL_TS))

    def test_the_gate_passes_well_formed_rows(self):
        self.assertEqual(
            timeline.manifest_row_problems(
                make_rows(REFERENCE_CLOCKS)),
            [],
            msg=("the gate must refuse only what is wrong; a suite "
                 "whose own rows failed it would be asserting against "
                 "a shape the pipeline never produces"))

    def test_verify_refuses_a_timeline_that_matches_a_bad_manifest(
            self):
        rows = self.malformed_rows()
        manifest_path = self.write_manifest(rows)
        document = timeline.build_timeline(rows)
        timeline_path = self.store_timeline(document)
        # The two checks that used to be the whole of verification.
        # Both pass here, which is precisely why they are not enough.
        self.assertEqual(
            timeline.validate_timeline(document), [],
            msg=("the timeline computed from these rows is internally "
                 "consistent -- the defect is in the evidence, not in "
                 "the arithmetic"))
        self.assertEqual(
            timeline.encode_timeline(
                timeline.read_timeline(timeline_path, root=self.root)),
            timeline.encode_timeline(document),
            msg=("the stored artifact is a faithful computation of "
                 "this manifest, so the drift comparison cannot see "
                 "the malformed rows"))
        status, _, err = self.run_cli(
            ["--verify", "--manifest", manifest_path,
             "-o", timeline_path])
        self.assertEqual(
            status, 1,
            msg=("--verify must exit non-zero: it claims the artifact "
                 "describes this session, and a manifest the "
                 "canonical validator rejects cannot support that "
                 "claim however exactly the timeline mirrors it"))
        self.assertIn(
            self.WRONG_CAPTURE, err,
            msg="the refusal must name the wrong capture path")
        self.assertIn(
            "real_ts", err,
            msg="the refusal must name the malformed timestamp")

    def test_verify_accepts_and_never_rewrites_good_evidence(self):
        rows = make_rows(REFERENCE_CLOCKS)
        manifest_path = self.write_manifest(rows)
        timeline_path = self.store_timeline(
            self.attested(rows, manifest_path))
        with open(timeline_path, "rb") as handle:
            before = handle.read()
        stamp = os.stat(timeline_path)
        status, out, _ = self.run_cli(
            ["--verify", "--manifest", manifest_path,
             "-o", timeline_path])
        self.assertEqual(
            status, 0,
            msg=("a timeline computed from a well-formed manifest must "
                 "verify; a gate that refused this one would be "
                 "useless in the pipeline it guards"))
        self.assertIn(
            "timeline ok", out,
            msg="a successful verification says so on stdout")
        with open(timeline_path, "rb") as handle:
            self.assertEqual(
                handle.read(), before,
                msg="--verify is read-only; it may not rewrite bytes")
        self.assertEqual(
            os.stat(timeline_path).st_mtime, stamp.st_mtime,
            msg="--verify may not touch the artifact at all")

    def test_verify_still_reports_a_timeline_that_drifted(self):
        rows = make_rows(REFERENCE_CLOCKS)
        manifest_path = self.write_manifest(rows)
        # A valid timeline of a DIFFERENT session, attested to THIS
        # manifest, and with the SAME NUMBER OF FRAMES -- so the manifest
        # gate passes, the attestation passes (its row count agrees with
        # the entry count and its digest is of the real file), and only
        # the byte comparison can catch it.  That is this test's subject:
        # gating provenance must not cost the drift check.
        #
        # Note what the equal frame count is for.  The attestation
        # cross-checks its row count against frame_count, so a document
        # whose entries describe a different-LENGTH session cannot attest
        # truthfully to this manifest at all -- provenance makes that
        # case unreachable rather than merely detectable.  Same length,
        # different clocks, is what is left for the byte diff to catch.
        other = build(("08:15:32", "08:15:35", "08:15:36", "08:15:41",
                       "08:20:41", "23:59:59", "00:00:05"))
        other["manifest"] = timeline.attest_manifest(
            manifest_path, self.root)
        # The capture attestation is truthful too, for the same reason:
        # the frames on disk ARE the seven this document paces, and their
        # digests match.  A different session with the same frames and
        # different CLOCKS is precisely the drift no provenance can see,
        # which is what leaves the byte diff a job to do.
        other["captures"] = timeline.attest_captures(
            os.path.join(self.root, *manifest.DIGESTS_REL_PARTS),
            self.root, verified=len(rows))
        timeline_path = self.store_timeline(other)
        status, _, err = self.run_cli(
            ["--verify", "--manifest", manifest_path,
             "-o", timeline_path])
        self.assertEqual(
            status, 1,
            msg=("gating the manifest must not cost the drift check: "
                 "an artifact that no longer matches its manifest is "
                 "still a failure"))
        self.assertIn(
            "does not match a fresh computation", err,
            msg="the refusal must say the artifact is stale")

    def test_generation_refuses_the_same_manifest(self):
        manifest_path = self.write_manifest(self.malformed_rows())
        destination = os.path.join(self.root, "timeline.json")
        status, _, err = self.run_cli(
            ["--manifest", manifest_path, "-o", destination])
        self.assertEqual(
            status, 1,
            msg=("generation and verification apply ONE gate; if "
                 "either is the lenient one, the other's result stops "
                 "meaning anything"))
        self.assertIn(
            self.WRONG_CAPTURE, err,
            msg="generation reports the same problem in the same words")
        self.assertFalse(
            os.path.exists(destination),
            msg=("nothing may be written from a manifest that was "
                 "refused"))

    def test_the_only_way_past_the_gate_is_explicit_and_reported(self):
        rows = self.malformed_rows()
        manifest_path = self.write_manifest(rows)
        timeline_path = self.store_timeline(
            self.attested(rows, manifest_path))
        status, _, err = self.run_cli(
            ["--verify", "--manifest", manifest_path,
             "-o", timeline_path, "--ignore-manifest-problems"])
        self.assertEqual(
            status, 0,
            msg=("--ignore-manifest-problems is a deliberate operator "
                 "decision and must still work"))
        self.assertIn(
            self.WRONG_CAPTURE, err,
            msg=("every problem is reported even when it is being "
                 "ignored -- an override is not a silence"))
        self.assertIn(
            "--ignore-manifest-problems was given", err,
            msg=("the log must record that the gate was overridden, "
                 "so a green verification is never mistaken for a "
                 "clean one"))

    def test_verify_refuses_an_empty_manifest_unless_it_is_allowed(
            self):
        manifest_path = self.write_manifest([])
        empty = build(())
        empty["manifest"] = timeline.attest_manifest(
            manifest_path, self.root)
        timeline_path = self.store_timeline(empty)
        status, _, err = self.run_cli(
            ["--verify", "--manifest", manifest_path,
             "-o", timeline_path])
        self.assertEqual(
            status, 1,
            msg=("an empty manifest is not a session, and attesting "
                 "to an empty timeline of it proves nothing"))
        self.assertIn(
            "--allow-empty", err,
            msg="the refusal must name the flag that permits it")
        status, out, _ = self.run_cli(
            ["--verify", "--manifest", manifest_path,
             "-o", timeline_path, "--allow-empty"])
        self.assertEqual(
            status, 0,
            msg=("with --allow-empty the empty case verifies, exactly "
                 "as generation treats it"))
        self.assertIn(
            "timeline ok", out,
            msg="the successful path still summarises")


class TestTheAmendmentLedgerReachesTheDerivative(unittest.TestCase):
    """A correction is applied to a copy, attested, and provable.

    THE DEFECT BEHIND THIS SUITE.  A security review found that the
    committed record had been edited after capture to correct two
    narrations, and that every derivative -- this timeline, both
    transcripts, the captioned film -- had then been regenerated to agree
    with the altered history.  The record is now restored and immutable,
    the corrections live in playthrough/amendments.jsonl, and THIS module
    is where they enter the derived chain.

    So the assertions are: the ledger reaches the entries; the document
    says which ledger it reached them through; the pacing is untouched by
    a correction to prose; a ledger that no longer binds to the record is
    a refusal rather than a silent skip; and a document computed before
    the corrections were recorded is caught rather than published.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.manifest = os.path.join(self.root, "manifest.jsonl")
        self.ledger = os.path.join(self.root, "amendments.jsonl")
        self.env = _environment(
            PLAYTHROUGH_MANIFEST=self.manifest,
            PLAYTHROUGH_TIMELINE=os.path.join(self.root,
                                              "timeline.json"),
            PLAYTHROUGH_AMENDMENTS=self.ledger,
            PLAYTHROUGH_OBSERVATIONS=os.path.join(
                self.root, "observations.jsonl"),
            PLAYTHROUGH_DATE_AUDIT=os.path.join(
                self.root, "frame_dates.jsonl"))
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        for index, clock in enumerate(("08:15:33", "08:15:34"), start=1):
            manifest.append_row(
                self.manifest, index, manifest.frame_file(index),
                "2026-05-14T09:12:0%d.000Z" % index, clock,
                "press '5' -- wait and listen",
                "I wait, and listen.", root=self.root)
        # The two captures those rows describe, sealed.  A correction
        # changes prose and never pixels, so the frames are the same
        # frames before and after an amendment -- which is one of the
        # things this suite asserts.
        seal_captures(self.root, (1, 2))

    def amend(self, frame=2, field="action", amended=None):
        """Append one amendment for `frame` and return it."""
        rows = {row["frame"]: row for row in
                manifest.read_rows(self.manifest, root=self.root)}
        digests = manifest.row_digests(self.manifest, root=self.root)
        recorded = rows[frame][field]
        if amended is None:
            amended = recorded + "; nothing on the screen changed"
        return manifest.append_amendment(
            self.ledger, 1, "2026-05-14T10:00:00.000Z", frame, field,
            digests[frame], recorded, amended,
            "the two captures were compared and are identical.",
            "the note claims an effect the capture contradicts.",
            root=self.root)

    def run_cli(self, argv):
        """Return (exit status, stdout, stderr) of the real main()."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                status = timeline.main(argv, root=self.root)
        return status, out.getvalue(), err.getvalue()

    def written(self):
        """The timeline the CLI wrote, read back."""
        return timeline.read_timeline(
            os.path.join(self.root, "timeline.json"), root=self.root)

    def test_with_no_ledger_the_attestation_is_null(self):
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        document = self.written()
        self.assertIsNone(document["amendments"])
        self.assertEqual([entry["amended"]
                          for entry in document["frames"]],
                         [False, False])

    def test_an_amendment_reaches_the_entry_and_is_attested(self):
        self.amend()
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        document = self.written()
        attestation = document["amendments"]
        self.assertEqual(list(attestation),
                         list(timeline.AMENDMENT_ATTESTATION_FIELDS))
        # The relative form is derived from the PARENT of the approved
        # root, exactly as the manifest attestation's is, so in a
        # temporary tree it carries that tree's own last component.
        self.assertEqual(
            attestation["path"],
            os.path.join(os.path.basename(self.root),
                         "amendments.jsonl"))
        self.assertEqual(attestation["rows"], 1)
        self.assertEqual(attestation["applied"], 1)
        self.assertEqual(attestation["sha256"],
                         timeline.file_digest(self.ledger))
        entries = document["frames"]
        self.assertEqual([entry["amended"] for entry in entries],
                         [False, True])
        self.assertTrue(entries[1]["action"].endswith(
            "; nothing on the screen changed"))
        # THE RECORD IS UNTOUCHED: the row still reads as recorded.
        rows = manifest.read_rows(self.manifest, root=self.root)
        self.assertNotIn("nothing on the screen changed",
                         rows[1]["action"])

    def test_a_correction_to_prose_moves_no_duration(self):
        before, _, err = self.run_cli(["-q"]), None, None
        self.assertEqual(before[0], 0, before[2])
        paced = self.written()
        self.amend()
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        amended = self.written()
        for name in ("total_duration", "total_transition", "total",
                     "final_cue_end", "frame_count",
                     "transition_count"):
            with self.subTest(field=name):
                self.assertEqual(amended[name], paced[name])
        for index, (was, now) in enumerate(
                zip(paced["frames"], amended["frames"]), start=1):
            for name in ("raw_delta", "duration", "transition_after",
                         "cue_start", "cue_end", "ingame_clock",
                         "clock_seconds", "real_ts"):
                with self.subTest(frame=index, field=name):
                    self.assertEqual(now[name], was[name])

    def test_a_ledger_that_no_longer_binds_is_refused(self):
        self.amend()
        # A THIRD ROW MOVES NOTHING -- the amendment names frame 2's own
        # bytes -- so this must still pass.  Then the ledger is tampered
        # with, and the run must stop.
        manifest.append_row(
            self.manifest, 3, manifest.frame_file(3),
            "2026-05-14T09:12:03.000Z", "08:15:35",
            "press '5' -- wait and listen", "Still listening.",
            root=self.root)
        seal_captures(self.root, (3,))
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        with open(self.ledger, "r", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        rows[0]["source_sha256"] = "ab" * 32
        with open(self.ledger, "w", encoding="utf-8",
                  newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 1)
        self.assertIn("amendment", err.lower())

    def test_a_timeline_written_before_the_ledger_is_caught(self):
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        stored = self.written()
        self.assertIsNone(stored["amendments"])
        self.amend()
        problems = timeline.amendment_attestation_problems(
            stored, self.root)
        self.assertTrue(
            any("attests no ledger" in one for one in problems),
            problems)
        with self.assertRaises(timeline.TimelineError):
            timeline.assert_timeline_document(stored, self.root)

    def test_a_document_claiming_a_ledger_it_cannot_show_is_caught(self):
        self.amend()
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        stored = self.written()
        self.assertEqual(
            timeline.amendment_attestation_problems(stored, self.root),
            [])
        os.remove(self.ledger)
        problems = timeline.amendment_attestation_problems(
            stored, self.root)
        self.assertTrue(any("does not exist" in one
                            for one in problems), problems)

    def test_verify_reads_the_ledger_too(self):
        self.amend()
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        status, out, err = self.run_cli(["--verify", "-q"])
        self.assertEqual(status, 0, err)


class TestTheCaptureLedgerReachesTheDerivative(unittest.TestCase):
    """The frames are verified BEFORE anything is timed, and attested.

    THE DEFECT BEHIND THIS SUITE.  A security review observed that no
    part of this pipeline had ever recorded what a capture's bytes were:
    every check on a frame was structural -- it exists, it is 1920x1080,
    it is not blank, the counts agree -- so a same-sized, non-blank,
    correctly-named replacement PNG paced the film, timed the captions and
    reached the commit with nothing objecting.

    A duration is derived from a clock READ OFF A FRAME.  So the frames
    are re-hashed against the append-only attestation ledger before the
    first delta is computed, the ledger is named in the document, and
    every later consumer -- the transition composer, the encoder, the
    caption generator -- inherits the check through
    assert_timeline_document() rather than each remembering to repeat it.
    """

    CLOCKS = ("08:15:33", "08:15:34", "08:15:40")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.manifest = os.path.join(self.root, "manifest.jsonl")
        self.output = os.path.join(self.root, "timeline.json")
        self.env = _environment(
            PLAYTHROUGH_MANIFEST=self.manifest,
            PLAYTHROUGH_TIMELINE=self.output,
            PLAYTHROUGH_OBSERVATIONS=os.path.join(
                self.root, "observations.jsonl"),
            PLAYTHROUGH_DATE_AUDIT=os.path.join(
                self.root, "frame_dates.jsonl"))
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        for index, clock in enumerate(self.CLOCKS, start=1):
            manifest.append_row(
                self.manifest, index, manifest.frame_file(index),
                "2026-05-14T09:12:0%d.000Z" % index, clock,
                "press '5' -- wait and listen",
                "I wait, and listen.", root=self.root)
        self.digests = seal_captures(self.root,
                                     range(1, len(self.CLOCKS) + 1))
        self.frames = os.path.join(self.root, "frames")

    def run_cli(self, argv):
        """Return (exit status, stdout, stderr) of the real main()."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                status = timeline.main(argv, root=self.root)
        return status, out.getvalue(), err.getvalue()

    def written(self):
        """The timeline the CLI wrote, read back."""
        return timeline.read_timeline(self.output, root=self.root)

    def substitute(self, index):
        """Replace one capture's bytes, keeping its name."""
        path = os.path.join(self.frames, "frame_%05d.png" % index)
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\nsubstituted afterwards\n")
        return path

    def test_the_ledger_is_named_in_the_document(self):
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 0, err)
        attestation = self.written()["captures"]
        # Spelled relative to the parent of the approved root, which in
        # production is the checkout root and here is the sandbox's
        # parent -- the same rule the manifest attestation follows, so a
        # confined run is resolvable by a confined verifier.
        self.assertTrue(
            attestation["path"].endswith(
                "/build/frame_digests.jsonl"),
            msg=attestation["path"])
        self.assertEqual(attestation["sha256"],
                         timeline.file_digest(self.digests))
        self.assertEqual(attestation["rows"], len(self.CLOCKS))
        self.assertEqual(
            attestation["verified"], len(self.CLOCKS),
            msg=("every frame the document paces was checked, not a "
                 "sample of them"))

    def test_a_substituted_frame_refuses_generation(self):
        """THE SUBSTITUTION EVERY STRUCTURAL CHECK PASSES."""
        self.substitute(2)
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 1)
        self.assertIn("frame 2 is attested as sha256", err)
        self.assertIn("not the bytes that were captured", err)
        self.assertFalse(
            os.path.exists(self.output),
            msg=("nothing may reach the disk from frames whose bytes "
                 "are not the bytes that were captured"))

    def test_a_substituted_frame_is_refused_even_under_the_override(self):
        """--allow-unattested-frames forgives an ABSENCE, never a change.

        The one honest case the override exists for is a session captured
        before the ledger did.  A frame that IS attested and no longer
        matches is a different thing entirely, and no flag reaches it.
        """
        self.substitute(2)
        status, _, err = self.run_cli(
            ["-q", "--allow-unattested-frames"])
        self.assertEqual(status, 1)
        self.assertIn("frame 2 is attested as sha256", err)

    def test_an_unattested_frame_refuses_generation(self):
        manifest.append_row(
            self.manifest, 4, manifest.frame_file(4),
            "2026-05-14T09:12:04.000Z", "08:15:44",
            "press '5' -- wait and listen", "Still listening.",
            root=self.root)
        with open(os.path.join(self.frames, "frame_00004.png"),
                  "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\nnever sealed\n")
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 1)
        self.assertIn("frame 4 is recorded but its bytes are not "
                      "attested", err)

    def test_a_session_recorded_before_the_ledger_may_be_paced(self):
        """The override exists, announces itself, and is diagnostic."""
        os.unlink(self.digests)
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(
            status, 1,
            msg="an absent ledger is a refusal by default")
        self.assertIn("no capture attestation ledger", err)
        status, _, err = self.run_cli(
            ["-q", "--allow-unattested-frames"])
        self.assertEqual(status, 0, err)
        self.assertIn("not proven to be the frames that were captured",
                      err)
        self.assertIsNone(
            self.written()["captures"],
            msg=("a document that verified nothing attests nothing; "
                 "silence here is the honest value"))

    def test_a_missing_frame_refuses_generation(self):
        os.unlink(os.path.join(self.frames, "frame_00002.png"))
        status, _, err = self.run_cli(["-q"])
        self.assertEqual(status, 1)
        self.assertIn("frame 2 is attested but", err)

    def test_verify_reads_the_captures_too(self):
        self.assertEqual(self.run_cli(["-q"])[0], 0)
        status, _, err = self.run_cli(["--verify", "-q"])
        self.assertEqual(status, 0, err)
        self.substitute(3)
        status, _, err = self.run_cli(["--verify", "-q"])
        self.assertEqual(
            status, 1,
            msg=("--verify re-hashes the frames as well: an artifact "
                 "that still matches a fresh computation is not "
                 "evidence if the pixels beneath it moved"))
        self.assertIn("frame 3 is attested as sha256", err)

    def test_a_document_written_before_the_seal_is_caught(self):
        """A timeline computed before the frames were sealed is stale.

        It is perfectly self-consistent -- that is exactly why the check
        has to be about provenance rather than about internal agreement.
        """
        status, _, err = self.run_cli(
            ["-q", "--allow-unattested-frames"], )
        del status, err
        os.unlink(self.output)
        os.unlink(self.digests)
        self.assertEqual(
            self.run_cli(["-q", "--allow-unattested-frames"])[0], 0)
        stored = self.written()
        self.assertIsNone(stored["captures"])
        seal_captures(self.root, range(1, len(self.CLOCKS) + 1))
        problems = timeline.capture_attestation_problems(
            stored, self.root)
        self.assertTrue(
            any("attests no capture ledger" in one for one in problems),
            problems)
        with self.assertRaises(timeline.TimelineError):
            timeline.assert_timeline_document(stored, self.root)

    def test_a_document_claiming_a_ledger_it_cannot_show_is_caught(self):
        self.assertEqual(self.run_cli(["-q"])[0], 0)
        stored = self.written()
        self.assertEqual(
            timeline.capture_attestation_problems(stored, self.root), [])
        os.unlink(self.digests)
        problems = timeline.capture_attestation_problems(
            stored, self.root)
        self.assertTrue(any("does not exist" in one
                            for one in problems), problems)

    def test_a_ledger_that_grew_after_the_document_is_caught(self):
        """The document names the ledger's own digest and row count."""
        self.assertEqual(self.run_cli(["-q"])[0], 0)
        stored = self.written()
        manifest.append_row(
            self.manifest, 4, manifest.frame_file(4),
            "2026-05-14T09:12:04.000Z", "08:15:44",
            "press '5' -- wait and listen", "Still listening.",
            root=self.root)
        seal_captures(self.root, (4,))
        problems = timeline.capture_attestation_problems(
            stored, self.root)
        self.assertTrue(
            any("now hashes to" in one for one in problems), problems)
        self.assertTrue(
            any("now holds 4" in one for one in problems), problems)


class TestTheSuiteIsHermetic(unittest.TestCase):
    """The suite depends on nothing the environment carries.

    THE DEFECT THIS EXISTS TO PREVENT, STATED PLAINLY.  Two of the
    three classes that drive main() once nominated a temporary root but
    left the ambient PLAYTHROUGH_* exports alone.  main() resolved its
    telemetry and date-audit DEFAULTS from those exports, landed outside
    the root the class had nominated, and was refused by the containment
    guard -- six deterministic failures and a non-zero exit status for
    anyone who sourced playthrough/tooling/env.sh first, which is
    exactly what the pipeline's own documentation tells an operator to
    do.  The arithmetic under test was never involved.

    A green suite in a bare shell is therefore not evidence of anything
    on its own, and a prose invariant in a docstring is not either.  So
    this class reads THIS FILE and asserts the invariant structurally:
    every class that calls timeline.main() must redirect all four
    variables in setUp.  Adding a fifth artifact variable to env.sh
    means adding it here, and the omission then fails immediately
    instead of at the next checkpoint.

    Its second reason for existing is the more dangerous failure mode:
    the obvious way to make a red suite green is to relax the
    containment guard, and that guard is the only thing standing
    between a test run and the committed evidence of the session.  The
    redirection is the correct fix; this test is what keeps it in place.
    """

    # The artifact layout env.sh exports and this module reads defaults
    # from.  Every variable here must be redirected by any test class
    # that lets the command line resolve a default.
    ARTIFACT_VARIABLES = (
        "PLAYTHROUGH_MANIFEST",
        "PLAYTHROUGH_TIMELINE",
        "PLAYTHROUGH_OBSERVATIONS",
        "PLAYTHROUGH_DATE_AUDIT",
    )

    @classmethod
    def setUpClass(cls):
        """Parse this file once; every test below reads the tree."""
        cls.tree = ast.parse(_read_text(os.path.abspath(__file__)))

    @staticmethod
    def _drives_the_command_line(node):
        """True when a class body calls timeline.main() anywhere."""
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            function = child.func
            if (isinstance(function, ast.Attribute) and
                    function.attr == "main" and
                    isinstance(function.value, ast.Name) and
                    function.value.id == "timeline"):
                return True
        return False

    @staticmethod
    def _redirected_variables(node):
        """Names passed to _environment() with a real value."""
        names = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            function = child.func
            if not (isinstance(function, ast.Name) and
                    function.id == "_environment"):
                continue
            for keyword in child.keywords:
                if keyword.arg is None:
                    continue
                unset = (isinstance(keyword.value, ast.Constant) and
                         keyword.value.value is None)
                if not unset:
                    names.add(keyword.arg)
        return names

    def _cli_classes(self):
        """Return (name, ClassDef) for every class driving main()."""
        found = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if self._drives_the_command_line(node):
                found.append((node.name, node))
        return found

    def test_every_class_that_drives_the_cli_redirects_all_four(self):
        classes = self._cli_classes()
        self.assertGreaterEqual(
            len(classes), 3,
            msg=("the command line is exercised by at least three "
                 "classes; finding fewer means this check stopped "
                 "seeing them and is no longer protecting anything"))
        for name, node in classes:
            with self.subTest(test_class=name):
                setup = next(
                    (child for child in node.body
                     if isinstance(child, ast.FunctionDef) and
                     child.name == "setUp"), None)
                self.assertIsNotNone(
                    setup,
                    msg=("%s calls timeline.main() and so must have a "
                         "setUp that redirects the artifact layout"
                         % name))
                redirected = self._redirected_variables(setup)
                for variable in self.ARTIFACT_VARIABLES:
                    self.assertIn(
                        variable, redirected,
                        msg=("%s does not redirect %s, so a run with "
                             "env.sh sourced resolves that default at "
                             "the committed tree, outside the root it "
                             "nominated, and is refused"
                             % (name, variable)))

    def test_the_four_variables_are_the_ones_the_module_reads(self):
        # The list above is only protective if it matches the module's
        # own vocabulary; a renamed variable would otherwise be
        # asserted under its old name for ever.
        self.assertIn(
            timeline.ENV_OBSERVATIONS, self.ARTIFACT_VARIABLES,
            msg="the module's own name for the telemetry variable")
        self.assertIn(
            timeline.ENV_DATE_AUDIT, self.ARTIFACT_VARIABLES,
            msg="and for the date-evidence variable")
        source = _timeline_source()
        for variable in ("PLAYTHROUGH_MANIFEST", "PLAYTHROUGH_TIMELINE"):
            with self.subTest(variable=variable):
                self.assertIn(
                    variable, source,
                    msg=("%s names an artifact this module resolves a "
                         "default from; if it no longer appears there "
                         "the layout has moved" % variable))

    def test_the_suite_reads_no_environment_at_import_time(self):
        # A module-scope os.environ read would make even collection
        # environment-dependent, and no per-test redirection could
        # repair that: the value would already have been captured.
        for node in self.tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                continue
            for child in ast.walk(node):
                if (isinstance(child, ast.Attribute) and
                        child.attr == "environ" and
                        isinstance(child.value, ast.Name) and
                        child.value.id == "os"):
                    self.fail(
                        "os.environ is read at module scope (line %d); "
                        "the environment must only be consulted inside "
                        "a test, where it can be redirected"
                        % child.lineno)


class TestTheAttestationIsCheckedOnDisk(unittest.TestCase):
    """The gate every producer of a rendered artifact passes.

    A stale timeline left beside a re-recorded manifest is the one
    failure no internal invariant can catch: the document is perfectly
    self-consistent, its totals agree with its entries, its cue windows
    are contiguous, and it describes a session that no longer exists.
    Three producers read it and none of them reads the manifest, so
    without provenance recorded IN the document a film could be paced
    from one session's numbers over another session's frames.
    """

    def setUp(self):
        self.directory = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_attest_"))
        self.addCleanup(_remove_tree, self.directory)
        self.manifest = os.path.join(self.directory, "manifest.jsonl")
        _write_lines(self.manifest,
                     [json.dumps(row)
                      for row in make_rows(REFERENCE_CLOCKS)])

    def attested(self):
        return timeline.build_timeline(
            make_rows(REFERENCE_CLOCKS), None, None,
            timeline.attest_manifest(self.manifest, self.directory))

    def test_an_attested_document_passes_the_gate(self):
        document = self.attested()
        self.assertEqual(
            timeline.manifest_attestation_problems(
                document, self.directory), [])
        self.assertIs(
            timeline.assert_timeline_document(document, self.directory),
            document,
            msg="the gate returns the document so a caller can bind it")

    def test_the_attestation_records_path_digest_and_rows(self):
        attestation = self.attested()["manifest"]
        self.assertEqual(
            sorted(attestation),
            sorted(timeline.MANIFEST_ATTESTATION_FIELDS))
        self.assertEqual(attestation["rows"], len(REFERENCE_CLOCKS))
        self.assertRegex(attestation["sha256"], r"\A[0-9a-f]{64}\Z")
        self.assertFalse(os.path.isabs(attestation["path"]),
                         msg="stored relative, so the artifact travels")
        self.assertTrue(attestation["path"].endswith("manifest.jsonl"))

    def test_the_digest_is_of_the_manifest_bytes(self):
        with open(self.manifest, "rb") as handle:
            expected = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(self.attested()["manifest"]["sha256"], expected)

    def test_a_manifest_that_changed_after_the_write_is_caught(self):
        document = self.attested()
        # The session grew by one keystroke after the timeline was
        # computed.  Nothing INSIDE the document can notice.
        _write_lines(self.manifest,
                     [json.dumps(row) for row in
                      make_rows(REFERENCE_CLOCKS + ("00:00:06",))])
        self.assertEqual(timeline.validate_timeline(document), [],
                         msg="the document is still self-consistent")
        problems = timeline.manifest_attestation_problems(
            document, self.directory)
        self.assertTrue(problems, msg="but its provenance is stale")
        self.assertIn("DIFFERENT evidence", problems[0])
        with self.assertRaises(timeline.TimelineError):
            timeline.assert_timeline_document(document, self.directory)

    def test_a_manifest_edited_in_place_is_caught(self):
        # Same row count, different bytes: only the digest can see it.
        document = self.attested()
        rows = make_rows(REFERENCE_CLOCKS)
        rows[0]["commentary"] = "something else entirely"
        _write_lines(self.manifest, [json.dumps(row) for row in rows])
        problems = timeline.manifest_attestation_problems(
            document, self.directory)
        self.assertTrue(problems)
        self.assertIn("sha256", problems[0])

    def test_an_unattested_document_is_refused_by_the_gate(self):
        document = timeline.build_timeline(make_rows(REFERENCE_CLOCKS))
        self.assertEqual(
            timeline.validate_timeline(document), [],
            msg=("the arithmetic validator accepts it: provenance is a "
                 "different question and is asked where it bites"))
        with self.assertRaises(timeline.TimelineError) as caught:
            timeline.assert_timeline_document(document, self.directory)
        self.assertIn("no manifest attestation", str(caught.exception))

    def test_a_bare_array_is_refused_by_the_gate(self):
        with self.assertRaises(timeline.TimelineError) as caught:
            timeline.assert_timeline_document(
                self.attested()["frames"], self.directory)
        self.assertIn("bare array", str(caught.exception))

    def test_the_gate_names_the_label_it_was_given(self):
        with self.assertRaises(timeline.TimelineError) as caught:
            timeline.assert_timeline_document(
                7, self.directory, label="the pacing document")
        self.assertIn("the pacing document", str(caught.exception))


class TestTheArtifactLock(unittest.TestCase):
    """Publication is serialised, and the lock lives outside the tree.

    Three producers publish from one timeline, and each publishes
    something the next stage reads.  Two runs of one producer used to
    interleave -- a half-composed transitions directory, a movie
    truncated before its replacement was verified, an SRT published
    while its Markdown twin was still the previous generation.
    """

    def setUp(self):
        self.directory = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_lock_"))
        self.addCleanup(_remove_tree, self.directory)
        self.runtime = os.path.join(self.directory, "runtime")
        # THE INHERITED RE-ENTRANCY MARKER IS CLEARED, and it has to be.
        # env.sh exports PLAYTHROUGH_MUTATION_LOCK_HELD so that a child
        # stage which inherits an already-held checkout lock does not
        # try to take it again and deadlock against its own parent.  The
        # acceptance gate takes that lock EXCLUSIVE and then runs this
        # suite as a child, so without this the eight tests below would
        # inherit "the lock is already held", skip the acquisition they
        # exist to measure, and error -- measured exactly that way, as
        # eight errors inside a gate run and none outside it.  A suite
        # that tests acquisition must own that variable rather than
        # inherit a claim about it.
        self.env = _environment(PLAYTHROUGH_RUNTIME_DIR=self.runtime,
                                PLAYTHROUGH_MUTATION_LOCK_HELD=None,
                                PLAYTHROUGH_MUTATION_LOCK_FD=None)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    def test_the_lock_is_not_inside_the_artifact_tree(self):
        # .gitignore ends with `!/playthrough/**`, which re-includes
        # everything under it -- so a lock file beside the artifacts
        # would be committed as though it were a session's evidence.
        path = timeline.artifact_lock_path("movie", self.directory)
        self.assertTrue(path.startswith(self.runtime + os.sep))
        self.assertFalse(path.startswith(self.directory + os.sep + "p"))
        self.assertTrue(path.endswith("movie.lock"))

    def test_the_scratch_directory_is_private(self):
        holder = timeline.scratch_dir(self.directory)
        mode = os.lstat(holder).st_mode
        self.assertEqual(mode & 0o777, 0o700,
                         msg="another account must not plant a lock")

    def test_two_clones_do_not_block_each_other(self):
        other = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_lock_other_"))
        self.addCleanup(_remove_tree, other)
        self.assertNotEqual(
            timeline.artifact_lock_path("movie", self.directory),
            timeline.artifact_lock_path("movie", other),
            msg=("the scratch directory is keyed by a digest of the "
                 "approved root, so two checkouts are independent"))

    def test_the_lock_is_exclusive(self):
        with timeline.ArtifactLock("movie", self.directory):
            with self.assertRaises(timeline.TimelineError) as caught:
                with timeline.ArtifactLock("movie", self.directory,
                                           timeout=0.2):
                    pass
        self.assertIn("refuses rather than interleaving",
                      str(caught.exception))

    def test_the_lock_is_released_afterwards(self):
        with timeline.ArtifactLock("movie", self.directory):
            pass
        with timeline.ArtifactLock("movie", self.directory, timeout=0.2):
            pass

    def test_different_artifacts_do_not_block_each_other(self):
        with timeline.ArtifactLock("movie", self.directory):
            with timeline.ArtifactLock("transcripts", self.directory,
                                       timeout=0.2):
                pass

    def test_a_lock_name_that_is_a_path_is_refused(self):
        for name in ("../escape", "a/b", ".", "..", "", "  "):
            with self.subTest(name=repr(name)):
                with self.assertRaises(timeline.TimelineError):
                    timeline.artifact_lock_path(name, self.directory)

    def test_the_lock_file_survives_release(self):
        # Unlinking a lock another process is waiting on is how a lock
        # stops working, so it is created once and left.
        path = timeline.artifact_lock_path("movie", self.directory)
        with timeline.ArtifactLock("movie", self.directory):
            pass
        self.assertTrue(os.path.isfile(path))

    # -- and the checkout's quiescence, taken with it -----------------

    def mutation_path(self):
        return manifest.mutation_lock_path(self.directory)

    def test_a_publication_holds_the_checkouts_mutation_lock(self):
        with timeline.ArtifactLock("movie", self.directory):
            self.assertTrue(
                manifest._mutation_is_held(self.mutation_path()),
                msg="a publication must exclude the gate that measures "
                    "the artifact and the checkpoint that commits it")
        self.assertFalse(
            manifest._mutation_is_held(self.mutation_path()))

    def test_it_is_taken_shared_so_another_producer_may_run(self):
        with timeline.ArtifactLock("movie", self.directory):
            descriptor = os.open(self.mutation_path(),
                                 os.O_RDWR | os.O_CREAT, 0o600)
            self.addCleanup(os.close, descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            with self.assertRaises(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_a_gate_holding_the_checkout_stops_a_publication(self):
        descriptor = os.open(self.mutation_path(),
                             os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with self.assertRaises(timeline.TimelineError) as caught:
            with timeline.ArtifactLock("movie", self.directory,
                                       timeout=0.2):
                pass
        self.assertIn("could not join", str(caught.exception))

    def test_the_artifact_lock_is_free_when_the_checkout_is_refused(
            self):
        # Mutation first, artifact second, everywhere -- so a refusal of
        # the outer lock must leave the inner one untaken, or a busy
        # checkout would wedge the next publication as well.
        descriptor = os.open(self.mutation_path(),
                             os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with self.assertRaises(timeline.TimelineError):
            with timeline.ArtifactLock("movie", self.directory,
                                       timeout=0.2):
                pass
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        with timeline.ArtifactLock("movie", self.directory, timeout=0.2):
            pass

    def test_two_artifact_locks_share_one_quiescence(self):
        # Nested publications in one process: the inner one must find the
        # outer one's own hold and reuse it rather than taking a second
        # descriptor, which would be a shared-beside-shared no-op here but
        # is a deadlock the moment either side is exclusive.
        with timeline.ArtifactLock("movie", self.directory):
            with timeline.ArtifactLock("transcripts", self.directory,
                                       timeout=0.2):
                self.assertTrue(
                    manifest._mutation_is_held(self.mutation_path()))
        self.assertFalse(
            manifest._mutation_is_held(self.mutation_path()))


class TestGenerationJournalDurability(unittest.TestCase):
    """A journal that is not whole, or not durable, is not a journal."""

    def setUp(self):
        self.directory = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_journal_"))
        self.addCleanup(_remove_tree, self.directory)
        self.runtime = os.path.join(self.directory, "runtime")
        self.env = _environment(PLAYTHROUGH_RUNTIME_DIR=self.runtime)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    def test_a_short_write_is_retried_rather_than_refused(self):
        # A partial os.write is ORDINARY -- it is why the call returns a
        # count.  Treating it as a failed publication conflated "the
        # device took what it could" with "the device cannot take it".
        original = os.write

        def dribble(descriptor, data):
            return original(descriptor, data[:1])

        os.write = dribble
        self.addCleanup(setattr, os, "write", original)
        timeline.write_generation_journal(
            "movie", {"version": timeline.GENERATION_VERSION},
            self.directory)
        os.write = original
        record = timeline.read_generation_journal("movie", self.directory)
        self.assertEqual(record["version"], timeline.GENERATION_VERSION)

    def test_a_write_that_makes_no_progress_is_refused(self):
        original = os.write

        def stall(descriptor, data):
            return 0

        os.write = stall
        self.addCleanup(setattr, os, "write", original)
        with self.assertRaises(timeline.TimelineError) as caught:
            timeline.write_generation_journal(
                "movie", {"version": timeline.GENERATION_VERSION},
                self.directory)
        os.write = original
        self.assertIn("no further progress", str(caught.exception))

    def test_a_failing_directory_flush_is_reported_not_swallowed(self):
        timeline.write_generation_journal(
            "movie", {"version": timeline.GENERATION_VERSION},
            self.directory)
        original = os.fsync

        def refuse(descriptor):
            raise OSError(5, "I/O error")

        os.fsync = refuse
        self.addCleanup(setattr, os, "fsync", original)
        with self.assertRaises(timeline.TimelineError) as caught:
            timeline.clear_generation_journal("movie", self.directory)
        os.fsync = original
        self.assertIn("could not flush", str(caught.exception))
        self.assertIsNone(
            timeline.read_generation_journal("movie", self.directory),
            msg="the unlink succeeded; what is reported is that it may "
                "not survive a crash")

    def test_clearing_an_absent_journal_is_silent(self):
        timeline.clear_generation_journal("movie", self.directory)


class TestTheDocumentCanBeReadWithoutBeingHeld(unittest.TestCase):
    """The event reader, and the header beside it.

    read_timeline() returns the whole document, which is what the
    producers need -- this module builds it, the renderer plans from it,
    the caption generator walks it.  It is the wrong answer for a
    consumer that only WALKS: one entry per keystroke is roughly a
    kilobyte of interpreter objects, so a session nobody has bounded is
    hundreds of megabytes resident on a host with under four gigabytes.

    Three consumers in the acceptance gate walk the entries in order and
    never look back.  iter_timeline_frames() is what they use, and this
    is where it is held to being EXACTLY equivalent to the whole read --
    a streamed read that is also a lenient one would be worse than the
    memory it saves.
    """

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.directory = os.path.realpath(holder.name)

    def write(self, name, text):
        path = os.path.join(self.directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def document(self, count=5):
        """A real document, written by this module's own encoder."""
        frames = [{"frame": index,
                   "file": "playthrough/frames/frame_%05d.png" % index,
                   "real_ts": "2026-08-08T07:52:%02d.000Z" % index,
                   "ingame_clock": None,
                   "duration": 0.25,
                   "cue_start": 0.25 * (index - 1),
                   "cue_end": 0.25 * index,
                   "transition_after": False}
                  for index in range(1, count + 1)]
        return {"version": 1,
                "manifest": {"path": "playthrough/manifest.jsonl",
                             "sha256": "0" * 64, "rows": count},
                "floor": timeline.FLOOR, "ceil": timeline.CEIL,
                "frames": frames, "total": 0.25 * count}

    def test_the_stream_is_the_whole_read(self):
        document = self.document()
        path = self.write("timeline.json",
                          timeline.encode_timeline(document))
        self.assertEqual(
            list(timeline.iter_timeline_frames(path)),
            document["frames"],
            msg="a streamed entry must be the entry json.load() returns")

    def test_the_header_is_everything_but_the_entries(self):
        document = self.document()
        path = self.write("timeline.json",
                          timeline.encode_timeline(document))
        header = timeline.read_timeline_header(path)
        self.assertEqual(header["frames"], [],
                         msg="the array is emptied, not removed, so a "
                             "caller cannot mistake a streamed read for "
                             "a document that never had entries")
        for key, value in document.items():
            if key == "frames":
                continue
            self.assertEqual(header[key], value)

    def test_an_empty_array_streams_as_nothing(self):
        document = self.document(0)
        path = self.write("timeline.json",
                          timeline.encode_timeline(document))
        self.assertEqual(list(timeline.iter_timeline_frames(path)), [])
        self.assertEqual(timeline.read_timeline_header(path)["frames"],
                         [])

    def test_a_document_with_no_array_streams_as_nothing(self):
        path = self.write("timeline.json", '{"version": 1}\n')
        self.assertEqual(list(timeline.iter_timeline_frames(path)), [])
        self.assertEqual(timeline.read_timeline_header(path),
                         {"version": 1})

    def test_a_string_that_spells_the_key_is_not_the_array(self):
        """Valid JSON cannot carry an unescaped quote inside a string.

        The array is found by searching the raw text for the KEY, quotes
        included, and a value that spelled it out would have to escape
        them -- so the first match is the array itself.  Asserted rather
        than assumed, because the whole streaming design rests on it.
        """
        path = self.write(
            "timeline.json",
            '{"note": "beware \\"frames\\": [ in a value",'
            ' "frames": [{"frame": 7}], "total": 1}\n')
        self.assertEqual(
            [entry["frame"]
             for entry in timeline.iter_timeline_frames(path)], [7])
        self.assertEqual(
            timeline.read_timeline_header(path)["note"],
            'beware "frames": [ in a value')

    def test_a_truncated_array_is_refused_rather_than_shortened(self):
        """A short read must not look like a short session.

        Silently yielding the entries it managed to decode is the one
        behaviour that would make this reader dangerous: every count
        downstream would tally against a document that had been cut.
        """
        for text in ('{"frames": [{"frame": 1}',
                     '{"frames": [{"frame": ',
                     '{"frames": [{"frame": 1}, {"frame"'):
            path = self.write("timeline.json", text)
            with self.subTest(text=text):
                with self.assertRaises(timeline.TimelineError):
                    list(timeline.iter_timeline_frames(path))
                with self.assertRaises(timeline.TimelineError):
                    timeline.read_timeline_header(path)

    def test_a_bare_array_document_is_read_whole(self):
        """The defensive form: no object, so no header to separate."""
        path = self.write("timeline.json", '[{"frame": 1}, {"frame": 2}]')
        self.assertEqual(list(timeline.iter_timeline_frames(path)), [])
        self.assertEqual(timeline.read_timeline_header(path),
                         [{"frame": 1}, {"frame": 2}])

    def test_a_symbolic_link_is_refused(self):
        """The same rule read_timeline() applies, for the same reason.

        A redirected read would hand a consumer somebody else's document
        while every downstream count still tallied.
        """
        target = self.write("timeline.json",
                            timeline.encode_timeline(self.document()))
        link = os.path.join(self.directory, "link.json")
        os.symlink(target, link)
        with self.assertRaises(timeline.TimelineError):
            list(timeline.iter_timeline_frames(link))
        with self.assertRaises(timeline.TimelineError):
            timeline.read_timeline_header(link)

    def test_an_entry_larger_than_the_chunk_still_arrives_whole(self):
        """The reader refills its buffer rather than giving up.

        An entry longer than the read size is ordinary -- a commentary is
        a sentence, and the chunk is 64 KiB -- but the failure mode if it
        were not handled is a refusal on a perfectly good document.
        """
        document = self.document(2)
        document["frames"][0]["commentary"] = "x" * 200000
        path = self.write("timeline.json",
                          timeline.encode_timeline(document))
        entries = list(timeline.iter_timeline_frames(path))
        self.assertEqual(len(entries), 2)
        self.assertEqual(len(entries[0]["commentary"]), 200000)
        self.assertEqual(timeline.read_timeline_header(path)["total"],
                         document["total"])

    def test_the_reader_holds_one_entry_at_a_time(self):
        """The point of it, asserted on the object graph itself.

        A generator that had materialised the array would hand back the
        SAME objects on a second pass; this one decodes afresh, which is
        what proves nothing was retained between yields.
        """
        path = self.write("timeline.json",
                          timeline.encode_timeline(self.document(3)))
        first = list(timeline.iter_timeline_frames(path))
        second = list(timeline.iter_timeline_frames(path))
        self.assertEqual(first, second)
        for left, right in zip(first, second):
            self.assertIsNot(left, right)


if __name__ == "__main__":
    # Wired up so that `python3 playthrough/tooling/test_timeline.py`
    # runs the suite and exits non-zero on any failure, which is how
    # the acceptance gate invokes it.
    unittest.main(verbosity=2)
