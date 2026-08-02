#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/timeline.py.

The timeline mathematics is the one genuinely deterministic component
of the playthrough capture subsystem: given a sequence of sidebar clock
readings it must always produce the same durations, the same transition
flags, the same cue windows and the same SubRip timecodes.  Everything
else in the pipeline photographs a running game, so it can only be
verified by looking at what it captured.  This module is therefore
where the feature's arithmetic is held to account.

WHY THE STANDARD LIBRARY
This suite uses unittest from the standard library.  The repository
carries 65 Python scripts under tools/ and build-scripts/ and not one
of them imports a test framework -- there is no Python test framework
here at all -- so adding a third-party runner to gain a decorator or
two would be a gratuitous new dependency for no benefit.  Nothing is
added to tests/ either: tests/CMakeLists.txt globs tests/*.cpp into the
Catch2 C++ binary, so a Python file there would be swept into the C++
test build.

    python3 playthrough/tooling/test_timeline.py
    python3 -m unittest discover -s playthrough/tooling -p 'test_*.py'

The first form is an acceptance gate in its own right, which is why
unittest.main() is wired up at the bottom of the file.

WHAT IS ASSERTED, AND WHY THESE NUMBERS
Four areas, in the order the requirements fix them:

* the clamp -- duration = min(max(raw, FLOOR), CEIL), including the
  boundary that a raw delta of exactly CEIL is NOT a transition,
  because the comparison is strictly greater and that is the easiest
  thing in the whole feature to get wrong;
* the rollover guard -- 23:59:58 -> 00:00:04 is a POSITIVE six-second
  step, and a reading that cannot be parsed or that moves backwards
  without being explicable as a crossing of midnight is reconciled
  against its predecessor AND FLAGGED, never quietly replaced by a
  plausible-looking number;
* the cue arithmetic -- the transition second is charged to VIDEO
  time, which is why the cue after the first transition of the
  reference sequence starts at 00:00:17,250 and not at 00:00:16,250.
  That single assertion is all that stands between the film and
  captions that drift further out of step with every transition;
* the SubRip formatter -- 3661.5 s is 01:01:01,500 exactly, with a
  comma and not a full stop.

Every expected value in this file is a MEASURED value: the reference
sequence below was run through timeline.py and the numbers recorded
from its output, rather than being reasoned out and hoped for.  The
same applies to the engine strings -- the coarse time phrases and the
"???" fallback are quoted verbatim from src/display.cpp, and the
military clock shape from src/calendar.cpp, so a test that claims the
parser refuses a real engine reading is refusing a string the engine
really emits.

WHAT IS DELIBERATELY NOT ASSERTED
Nothing here touches playthrough/frames/, playthrough/manifest.jsonl
or playthrough/timeline.json.  Those are the captured evidence of a
session, and a test suite that wrote to the record it exists to
protect would be worse than no suite at all.  The pure functions are
exercised in memory; the one test that needs a file on disk uses a
temporary directory and removes it.

Standard library only, plus the sibling timeline module.  Nothing from
playthrough/tooling/requirements.txt is imported, so the suite runs on
a bare interpreter in any checkout -- which is the point, because the
arithmetic must be auditable without provisioning a render toolchain
first.
"""

import copy
import os
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


# ---------------------------------------------------------------------
# The reference sequence.
#
# Eight readings that between them exercise every branch of the
# duration model: a keystroke that consumed no game time, three
# ordinary steps, two waits long enough to engage the ceiling, a
# crossing of midnight, and a final frame with no successor to
# difference against.  The clock strings are the fixed-width 24h form
# that to_string_time_of_day emits under 24_HOUR=24h
# (src/calendar.cpp:649), which is the shape the session is configured
# to render and the only shape the parser accepts.
#
# Reading                 raw delta   why it is here
#   1  08:15:33               0.0 s   a menu keystroke: no game time
#   2  08:15:33               1.0 s   an ordinary one-second step
#   3  08:15:34               5.0 s   an ordinary five-second step
#   4  08:15:39             300.0 s   a five-minute wait: ceiling
#   5  08:20:39          56 359.0 s   sleeping the night: ceiling
#   6  23:59:58               6.0 s   crosses midnight -- POSITIVE
#   7  00:00:04               1.0 s   a step taken after waking
#   8  00:00:05               0.0 s   final frame: no successor
# ---------------------------------------------------------------------

REFERENCE_CLOCKS = (
    "08:15:33",
    "08:15:33",
    "08:15:34",
    "08:15:39",
    "08:20:39",
    "23:59:58",
    "00:00:04",
    "00:00:05",
)

# Measured against timeline.py, not predicted.  raw[i] is the clock
# advance from frame i to frame i + 1; the last frame has no successor
# and is therefore 0.0, which the floor turns into 0.25 s of video.
REFERENCE_RAW_DELTAS = (0.0, 1.0, 5.0, 300.0, 56359.0, 6.0, 1.0, 0.0)
REFERENCE_DURATIONS = (0.25, 1.0, 5.0, 10.0, 10.0, 6.0, 1.0, 0.25)
REFERENCE_TRANSITIONS = (False, False, False, True, True,
                         False, False, False)

# The cue windows the walk produces.  Note the jump from an end of
# 16.25 to a start of 17.25 and from 27.25 to 28.25: that is the
# transition second, charged to video time between the two windows.
REFERENCE_CUES = (
    (0.0, 0.25),
    (0.25, 1.25),
    (1.25, 6.25),
    (6.25, 16.25),
    (17.25, 27.25),
    (28.25, 34.25),
    (34.25, 35.25),
    (35.25, 35.5),
)

# THE INVARIANT, in numbers:
#     sum(durations) + sum(transitions) == total == final cue end
#             33.500  +           2.000 ==  35.500
REFERENCE_TOTAL_DURATION = 33.5
REFERENCE_TOTAL_TRANSITION = 2.0
REFERENCE_TOTAL = 35.5
REFERENCE_TRANSITION_COUNT = 2

# The index of the frame whose cue opens immediately after the first
# transition.  Zero-based, so this is the fifth reading -- the one
# that must start at 17.25 s rather than 16.25 s.
FIRST_POST_TRANSITION = 4

# The clamp table exactly as the requirements state it.  Each row is
# (raw delta, expected duration, expected transition flag).  The rows
# are the distinct behaviours of the model, which is why the second
# one-second step of the reference sequence does not appear again
# here: it would restate the pass-through case.
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


def build(clocks):
    """Return the timeline document for a sequence of readings."""
    return timeline.build_timeline(make_rows(clocks))


def reference_document():
    """Return the timeline of the reference sequence."""
    return build(REFERENCE_CLOCKS)


def field(document, name):
    """Return one field of every frame, in order."""
    return [entry[name] for entry in document["frames"]]


def absolute_seconds(clocks):
    """Return the absolutised second count of every reading."""
    return [reading.seconds
            for reading in timeline.absolutise_clocks(clocks)]


def readings_of(clocks):
    """Return the ClockReading list for a sequence of readings."""
    return timeline.absolutise_clocks(clocks)


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
        seconds = absolute_seconds(clocks)
        self.assertEqual(
            seconds, [86398, 86404],
            msg=("23:59:58 -> 00:00:04 crosses midnight, so the day "
                 "counter must advance and the absolute values must "
                 "rise"))
        self.assertEqual(
            timeline.raw_deltas(seconds), [6.0, 0.0],
            msg=("23:59:58 -> 00:00:04 is a POSITIVE six-second step, "
                 "not a negative one"))
        self.assertAlmostEqual(
            timeline.clamp_duration(6.0), 6.0, places=PLACES,
            msg="six seconds of game time is six seconds of video")

    def test_two_consecutive_midnight_crossings_accumulate_days(self):
        clocks = ("23:59:58", "00:00:04", "23:59:59", "00:00:03")
        seconds = absolute_seconds(clocks)
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
        deltas = timeline.raw_deltas(absolute_seconds(clocks))
        self.assertAlmostEqual(
            deltas[0], 30000.0, places=PLACES,
            msg=("22:10:00 -> 06:30:00 is eight hours and twenty "
                 "minutes forward, across midnight"))
        self.assertIs(
            timeline.is_transition(deltas[0]), True,
            msg="a night of sleep engages the ceiling")

    def test_the_absolutised_sequence_never_decreases(self):
        # Every awkward case in one session: unreadable clocks, a
        # coarse phrase, an off-contract format, a crossing of
        # midnight, and ordinary steps after it.
        clocks = ("08:15:33", None, "Dead of night", UNKNOWN_TIME_TEXT,
                  MILITARY_CLOCK, "23:59:58", "00:00:04", "07:59:00",
                  "08:00:00")
        seconds = absolute_seconds(clocks)
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

    def test_a_non_monotonic_reading_is_clamped_and_flagged(self):
        # 08:00:00 -> 07:59:00 would imply an advance of 23h59m if it
        # were treated as a crossing of midnight, which no single
        # keystroke produces.  It is a misread going backwards.
        document = build(("08:00:00", "07:59:00", "08:00:02"))
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
            entry["reconciled_reason"], timeline.RECONCILED_BACKWARDS,
            msg="a backwards reading is reconciled as non-monotonic")
        self.assertEqual(
            entry["ingame_clock"], "07:59:00",
            msg=("the refused reading is still recorded verbatim; "
                 "the evidence is kept, only the pacing is corrected"))

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
        # "07:59:00" after "08:00:00" implies an advance of 23h59m if
        # read as a crossing of midnight, which exceeds the wrap bound
        # and so is refused; "07:00:00" would sit exactly on the bound
        # and be accepted as a genuine crossing instead.
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
            msg="the reference frames sum to 33.500s of video")
        self.assertAlmostEqual(
            document["total_transition"], REFERENCE_TOTAL_TRANSITION,
            places=PLACES,
            msg="two transitions of one second is 2.000s")
        self.assertAlmostEqual(
            document["total"], REFERENCE_TOTAL, places=PLACES,
            msg="33.500 + 2.000 is 35.500s of film")

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
            "00:00:35,500",
            msg="the reference film runs 35.5s")

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
        self.assertEqual(
            field(reference_document(), "clock_seconds"),
            [29733, 29733, 29734, 29739, 30039, 86398, 86404, 86405],
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


class TestValidationFailsLoudly(unittest.TestCase):
    """validate_timeline() must catch a broken timeline, not tolerate it.

    A checker that passed everything would be worse than no checker,
    because it would manufacture confidence.  Every test here breaks a
    known-good document in one specific way and insists the breakage is
    reported.
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

    def assertReported(self, document, label):
        """Assert that validation reports at least one problem."""
        problems = timeline.validate_timeline(document)
        self.assertTrue(
            problems,
            msg=("%s must be reported; validation returned no "
                 "problems at all" % label))
        return problems

    def test_a_duration_below_the_floor_is_reported(self):
        document = self.broken()
        document["frames"][0]["duration"] = 0.1
        self.assertReported(document, "a duration under the floor")

    def test_a_duration_above_the_ceiling_is_reported(self):
        document = self.broken()
        document["frames"][3]["duration"] = 11.0
        self.assertReported(document, "a duration over the ceiling")

    def test_a_duration_that_does_not_clamp_its_delta_is_reported(self):
        document = self.broken()
        document["frames"][1]["duration"] = 2.0
        self.assertReported(
            document, "a duration that is not its raw delta clamped")

    def test_a_missing_transition_flag_is_reported(self):
        # The strictly-greater boundary, from the other side: an entry
        # whose raw delta exceeded the ceiling but which is not flagged
        # would leave the film with a hard cut where a fade belongs.
        document = self.broken()
        self.assertIs(
            document["frames"][3]["transition_after"], True,
            msg="frame 4 is the flagged frame in the fixture")
        document["frames"][3]["transition_after"] = False
        self.assertReported(document, "a cleared transition flag")

    def test_a_spurious_transition_flag_is_reported(self):
        document = self.broken()
        document["frames"][1]["transition_after"] = True
        self.assertReported(
            document,
            "a transition flag on a frame under the ceiling")

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
            document, "a cue walk that forgot the transition second")
        self.assertAlmostEqual(
            document["final_cue_end"],
            REFERENCE_TOTAL - REFERENCE_TOTAL_TRANSITION,
            places=PLACES,
            msg=("the broken walk must end two seconds short, which "
                 "is precisely the drift the check exists to catch"))
        self.assertTrue(
            any("transition" in problem or "final cue" in problem or
                "total" in problem for problem in problems),
            msg=("the report must name the drift rather than some "
                 "unrelated symptom; got %r" % problems))

    def test_a_shifted_cue_is_reported(self):
        document = self.broken()
        document["frames"][2]["cue_start"] -= 1.0
        self.assertReported(document, "a cue that starts too early")

    def test_a_cue_of_the_wrong_length_is_reported(self):
        document = self.broken()
        document["frames"][2]["cue_end"] += 0.5
        self.assertReported(document, "a cue window of the wrong size")

    def test_a_first_cue_that_does_not_start_at_zero_is_reported(self):
        document = self.broken()
        for entry in document["frames"]:
            entry["cue_start"] += 1.0
            entry["cue_end"] += 1.0
        self.assertReported(document, "a timeline that starts late")

    def test_a_backwards_absolute_clock_is_reported(self):
        document = self.broken()
        document["frames"][5]["clock_seconds"] = 1
        self.assertReported(
            document, "an absolutised clock that runs backwards")

    def test_a_negative_raw_delta_is_reported(self):
        document = self.broken()
        document["frames"][1]["raw_delta"] = -1.0
        self.assertReported(document, "a negative raw delta")

    def test_a_flagged_final_frame_is_reported(self):
        document = self.broken()
        document["frames"][-1]["transition_after"] = True
        self.assertReported(
            document,
            "a transition after the last frame, which has no "
            "successor to transition into")

    def test_a_final_frame_with_a_delta_is_reported(self):
        document = self.broken()
        document["frames"][-1]["raw_delta"] = 5.0
        self.assertReported(
            document, "a raw delta on the frame with no successor")

    def test_a_reconciled_entry_without_a_reason_is_reported(self):
        document = self.broken()
        document["frames"][0]["reconciled"] = True
        self.assertReported(
            document, "a reconciled clock with no reason recorded")

    def test_a_reason_without_the_flag_is_reported(self):
        document = self.broken()
        document["frames"][0]["reconciled_reason"] = "clock-missing"
        self.assertReported(
            document, "a reason recorded on an unflagged entry")

    def test_a_disagreeing_total_is_reported(self):
        document = self.broken()
        document["total"] = 99.0
        self.assertReported(document, "a total that is not the sum")

    def test_a_disagreeing_duration_total_is_reported(self):
        document = self.broken()
        document["total_duration"] = 1.0
        self.assertReported(document, "a wrong total_duration")

    def test_a_disagreeing_frame_count_is_reported(self):
        document = self.broken()
        document["frame_count"] = 99
        self.assertReported(document, "a wrong frame_count")

    def test_a_disagreeing_transition_count_is_reported(self):
        document = self.broken()
        document["transition_count"] = 0
        self.assertReported(document, "a wrong transition_count")

    def test_a_disagreeing_reconciled_count_is_reported(self):
        document = self.broken()
        document["reconciled_count"] = 3
        self.assertReported(document, "a wrong reconciled_count")

    def test_a_rewritten_constant_is_reported(self):
        for name in ("floor", "ceil", "transition"):
            with self.subTest(constant=name):
                document = self.broken()
                document[name] = 42.0
                self.assertReported(
                    document,
                    "a timeline written under a different %s; the "
                    "constants are fixed, not tunable" % name)

    def test_a_reordered_index_is_reported(self):
        document = self.broken()
        document["frames"][2]["frame"] = 99
        self.assertReported(document, "a frame index out of sequence")

    def test_a_reordered_index_may_be_allowed_explicitly(self):
        document = self.broken()
        document["frames"][2]["frame"] = 99
        self.assertEqual(
            timeline.validate_timeline(document,
                                       allow_index_gaps=True),
            [],
            msg=("a gap is tolerated only when it is asked for "
                 "explicitly, and everything else still holds"))

    def test_a_missing_entry_field_is_reported(self):
        for name in timeline.ENTRY_FIELDS:
            with self.subTest(field=name):
                document = self.broken()
                del document["frames"][0][name]
                self.assertReported(
                    document, "an entry missing %s" % name)

    def test_a_missing_document_field_is_reported(self):
        for name in timeline.DOCUMENT_FIELDS:
            with self.subTest(field=name):
                document = self.broken()
                del document[name]
                self.assertReported(
                    document, "a timeline missing %s" % name)

    def test_a_non_document_is_reported(self):
        for value in ([], "timeline", 17, None):
            with self.subTest(value=value):
                self.assertReported(
                    value, "a timeline that is not an object")

    def test_frames_that_are_not_an_array_is_reported(self):
        document = self.broken()
        document["frames"] = {}
        self.assertReported(document, "a frames field that is not an "
                                      "array")

    def test_an_entry_that_is_not_an_object_is_reported(self):
        document = self.broken()
        document["frames"][0] = "frame one"
        self.assertReported(document, "an entry that is not an object")

    def test_a_non_numeric_cue_is_reported(self):
        document = self.broken()
        document["frames"][0]["cue_end"] = "0.25"
        self.assertReported(document, "a cue time that is not a number")


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
            path = os.path.join(directory, "timeline.json")
            written = timeline.write_timeline(path, document)
            self.assertEqual(
                written, path,
                msg="write_timeline returns the path it wrote")
            restored = timeline.read_timeline(path)
            self.assertEqual(
                restored, document,
                msg=("the artifact must round trip through JSON "
                     "without losing or changing a number"))
            self.assertEqual(
                timeline.validate_timeline(restored), [],
                msg="the reloaded timeline still passes every check")

    def test_writing_a_failing_timeline_is_refused(self):
        document = reference_document()
        document["total"] = 99.0
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "timeline.json")
            with self.assertRaises(
                    timeline.TimelineError,
                    msg=("a timeline that fails its own checks must "
                         "not reach the disk, where the renderer and "
                         "the caption generator would both trust it")):
                timeline.write_timeline(path, document)
            self.assertFalse(
                os.path.exists(path),
                msg="nothing may be written when validation fails")

    def test_reading_a_missing_timeline_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "absent.json")
            with self.assertRaises(timeline.TimelineError):
                timeline.read_timeline(path)

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


if __name__ == "__main__":
    # Wired up so that `python3 playthrough/tooling/test_timeline.py`
    # runs the suite and exits non-zero on any failure, which is how
    # the acceptance gate invokes it.
    unittest.main(verbosity=2)
