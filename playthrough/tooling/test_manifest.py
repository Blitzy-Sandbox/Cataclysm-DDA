#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/manifest.py.

The manifest is the EVIDENCE of a captured session: one row per
keystroke, in the order the keystrokes were sent, each row naming the
PNG that keystroke produced and the clock that was on screen when it
did.  Every downstream claim rests on it -- the film's pacing comes
from its `ingame_clock` column, and the acceptance gate proves one
frame per keystroke by comparing the number of rows in this file with
the number of PNGs in playthrough/frames/.

That is why this module gets its own suite rather than being covered
incidentally by the timeline tests.  A timeline test builds its rows in
memory, so it cannot notice that the writer dropped a field, reordered
the schema, invented a clock for an unreadable frame, or truncated the
file instead of appending to it.  Every one of those defects would leave
the arithmetic tests green and the record wrong.

    python3 playthrough/tooling/test_manifest.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED, AND WHY
* THE SCHEMA -- exactly the six declared fields, in the declared order,
  on every row.  A seventh field is how a second source of truth for
  timing would get in, so it is refused rather than ignored.
* THE FILENAME -- a row's `file` is the canonical
  playthrough/frames/frame_%05d.png for its own index and nothing else,
  which is what stops a row from pointing at a derived transition image
  or at another row's capture.
* NULL, NOT A GUESS -- an unreadable clock is recorded as JSON null.
  This is the honesty rule made mechanical: no default is substituted,
  no neighbouring row is consulted, and a coarse phrase or "???" is
  kept verbatim because it is a real observation of the frame.
* APPEND-ONLY -- one line per append, never a truncation, never a
  rewrite, and a refused row leaves the file byte-identical.  The record
  of what was captured is not edited afterwards.
* THE COUNT IDENTITY -- verify_manifest() reports a gap, a repeat, a
  reordering and a row whose capture is missing on disk, because those
  are the four ways the one-frame-per-keystroke invariant breaks.
* THE SENTINEL RULE -- a field marked as not yet filled in, or an action
  that defers the record elsewhere, is refused by the writer AND
  reported by the reader.  This is the one text rule in the module that
  is a hard problem rather than an advisory, and it exists because a row
  of the real record once passed every structural check while saying
  something untrue.  The tests below hold both ends of it, and hold the
  line between it and the advisory it must not become.

WHAT IS DELIBERATELY NOT ASSERTED
Nothing here writes to the real playthrough/manifest.jsonl or
playthrough/frames/.  Every test works inside a temporary directory it
removes, and one test asserts the real artifacts were untouched.  The
engine strings quoted below -- the coarse time phrases, "???" and the
military clock shape -- are taken verbatim from src/display.cpp and
src/calendar.cpp, so a test claiming the writer accepts a real engine
reading is passing it a string the engine really emits.

Standard library only, plus the sibling manifest module: the record has
to be auditable in a checkout where the render toolchain was never
provisioned.
"""

import contextlib
import datetime
import errno
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

# The import below must not drop a __pycache__ into
# playthrough/tooling/: .gitignore's terminal `!/playthrough/**`
# negation -- the one that makes the save data trackable at all --
# re-includes bytecode written there.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1 for the pipeline; this is the same thing for
# a suite run by hand, and it has to precede the import to affect it.
sys.dont_write_bytecode = True

try:
    import manifest
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import manifest


# A fixed instant for the real_ts column, in the canonical form.  A
# literal rather than a reading of the machine clock, because a suite
# that consulted the time of day would not be reproducible.
FIXED_REAL_TS = "2026-05-14T09:12:03.481Z"

# The eight-byte PNG signature validate-and-verify paths look for.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Real engine readings, quoted verbatim.  The eleven coarse phrases are
# display::time_approx() (src/display.cpp:159-185); "???" is what
# display::time_string() falls back to when the sky is not visible
# (src/display.cpp:216); the military and 12h shapes are the other two
# branches of to_string_time_of_day (src/calendar.cpp:646, 657-661).
COARSE_PHRASE = "Around dawn"
UNKNOWN_TIME_TEXT = "???"
MILITARY_CLOCK = "0815.32"
TWELVE_HOUR_CLOCK = "8:15:32 AM"


def _write_lines(path, lines):
    """Write one LF-terminated line per element; return the path."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


def _read_bytes(path):
    """Return a file's bytes, read-only."""
    with open(path, "rb") as handle:
        return handle.read()


def _remove_tree(path):
    """Remove a temporary directory tree created by this suite."""
    shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def _patched(module, **attributes):
    """Swap module attributes for a block, then restore them.

    Used to make a write fail the way a full disk makes it fail, which
    is not something a test can arrange any other way without a
    filesystem it owns.  Restoring in a `finally` matters: os.write left
    swapped would break every test after it.
    """
    previous = {name: getattr(module, name) for name in attributes}
    try:
        for name, value in attributes.items():
            setattr(module, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(module, name, value)


@contextlib.contextmanager
def _environment(**values):
    """Set environment variables for a block, then restore them.

    A value of None UNSETS the variable, which is how a test proves
    what the module does when env.sh has not been sourced.  Restoring
    matters because these variables ARE the artifact layout: one left
    pointing at a temporary directory would silently redirect every
    test after it.
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


class ManifestFixture(unittest.TestCase):
    """A temporary manifest and frames directory, and nothing else.

    THE TEMPORARY DIRECTORY IS PASSED IN AS THE APPROVED ROOT.
    manifest.py resolves every path it opens inside a tree derived from
    its own location and refuses anything outside it, so that no
    environment variable and no argument can move the record of a
    captured session somewhere else on the host.  The one supported way
    to work elsewhere is the call-site-only `root=` argument, and this
    fixture uses exactly that: the layout below mirrors the real one --
    manifest.jsonl directly under the root, frames/ beside it -- so the
    rules being exercised are the production rules and not a weaker set.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="blitzy_manifest_")
        self.addCleanup(_remove_tree, self.directory)
        self.frames = os.path.join(self.directory, "frames")
        os.mkdir(self.frames)
        self.manifest = os.path.join(self.directory, "manifest.jsonl")
        manifest._WARNED.clear()

    def row(self, frame=1, clock="08:15:33", action="press '5'",
            commentary="I wait, and listen."):
        """Return one valid row for `frame`, built by the module."""
        return manifest.build_row(
            frame, manifest.frame_file(frame), FIXED_REAL_TS, clock,
            action, commentary)

    def append(self, frame=1, clock="08:15:33", action="press '5'",
               commentary="I wait, and listen."):
        """Append one valid row for `frame` and return it."""
        return manifest.append_row(
            self.manifest, frame, manifest.frame_file(frame),
            FIXED_REAL_TS, clock, action, commentary,
            root=self.directory)

    def append_many(self, count, clock="08:15:33"):
        """Append `count` rows indexed 1..count."""
        return [self.append(frame=index, clock=clock)
                for index in range(1, count + 1)]

    def write_frames(self, indexes):
        """Create a minimal real PNG for each index given."""
        for index in indexes:
            path = os.path.join(self.frames,
                                manifest.FRAME_NAME_FORMAT % index)
            with open(path, "wb") as handle:
                handle.write(PNG_MAGIC)

    def lines(self):
        """Return the manifest's lines exactly as written."""
        with open(self.manifest, "r", encoding="utf-8",
                  newline="") as handle:
            return handle.readlines()

    def capture_stderr(self, call, *args, **kwargs):
        """Run `call`, returning (result, stderr text)."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = call(*args, **kwargs)
        return result, err.getvalue()


class TestTheSchema(ManifestFixture):
    """Exactly six fields, in one order, on every row."""

    def test_the_declared_schema_is_the_prescribed_one(self):
        self.assertEqual(
            manifest.FIELDS,
            ("frame", "file", "real_ts", "ingame_clock", "action",
             "commentary"),
            msg=("the six fields and their order are the contract the "
                 "capture, the timeline and the transcript all read"))

    def test_a_row_is_written_in_the_declared_order(self):
        row = self.row()
        self.assertEqual(
            list(row), list(manifest.FIELDS),
            msg="build_row returns the fields in the declared order")
        encoded = manifest.encode_row(row)
        self.assertEqual(
            list(json.loads(encoded)), list(manifest.FIELDS),
            msg=("the ORDER survives into the JSON text, which is what "
                 "makes the committed file diffable"))

    def test_a_row_supplied_out_of_order_is_reordered_not_refused(self):
        scrambled = {name: self.row()[name]
                     for name in reversed(manifest.FIELDS)}
        self.assertEqual(
            list(scrambled), list(reversed(manifest.FIELDS)),
            msg="the fixture really is in the wrong order")
        written = json.loads(manifest.encode_row(scrambled))
        self.assertEqual(
            list(written), list(manifest.FIELDS),
            msg=("the schema fixes the order on disk, so a caller's "
                 "insertion order is normalised rather than rejected"))

    def test_a_missing_field_is_refused_and_named(self):
        for name in manifest.FIELDS:
            with self.subTest(field=name):
                row = self.row()
                del row[name]
                with self.assertRaises(manifest.ManifestError) as bad:
                    manifest.encode_row(row)
                self.assertIn(name, str(bad.exception))

    def test_an_extra_field_is_refused_and_named(self):
        row = self.row()
        row["duration"] = 0.25
        with self.assertRaises(manifest.ManifestError) as bad:
            manifest.encode_row(row)
        message = str(bad.exception)
        self.assertIn("duration", message)
        self.assertIn(
            "playthrough/timeline.json", message,
            msg=("the message says where a duration BELONGS, because a "
                 "seventh column is how a second source of truth for "
                 "timing would get in"))

    def test_a_row_that_is_not_a_mapping_is_refused(self):
        for value in ([], "row", 17, None):
            with self.subTest(value=value):
                with self.assertRaises(manifest.ManifestError):
                    manifest.encode_row(value)

    def test_a_row_is_one_json_object_on_one_line(self):
        encoded = manifest.encode_row(self.row())
        self.assertTrue(encoded.endswith("\n"))
        self.assertEqual(
            encoded.count("\n"), 1,
            msg="one row is one line: no indentation, no wrapping")
        self.assertNotIn("\r", encoded, msg="LF only, whatever the host")
        self.assertFalse(
            encoded.startswith("[") or encoded.rstrip().endswith(","),
            msg="JSON Lines, not a JSON array with commas")

    def test_non_ascii_is_written_as_itself(self):
        row = self.row(commentary="I keep going \u2014 north.")
        self.assertIn(
            "\u2014", manifest.encode_row(row),
            msg=("the repository's own tooling writes UTF-8 rather than "
                 "escapes, and the survivor's own words are the record"))


class TestTheFrameIndexAndFilename(ManifestFixture):
    """One row, one index, one canonical capture filename."""

    def test_the_canonical_filename_is_built_from_the_index(self):
        self.assertEqual(
            manifest.frame_file(42),
            "playthrough/frames/frame_00042.png",
            msg=("repository-relative and five digits wide, so a "
                 "lexical sort of the frames is a numeric one"))

    def test_the_index_bounds_are_the_five_digit_field(self):
        self.assertEqual(manifest.MIN_FRAME_INDEX, 1)
        self.assertEqual(manifest.MAX_FRAME_INDEX, 99999)
        self.assertEqual(
            manifest.frame_file(manifest.MAX_FRAME_INDEX),
            "playthrough/frames/frame_99999.png")

    def test_an_index_outside_the_field_is_refused(self):
        for index, why in (
                (0, "an index below one"),
                (-1, "a negative index"),
                (100000, "an index that would widen the field")):
            with self.subTest(index=index):
                with self.assertRaises(manifest.ManifestError,
                                       msg=why):
                    manifest.frame_file(index)

    def test_an_index_that_is_not_an_integer_is_refused(self):
        for index in ("1", 1.0, True, None, [1]):
            with self.subTest(index=index):
                with self.assertRaises(manifest.ManifestError):
                    manifest.frame_file(index)

    def test_a_boolean_index_is_refused_specifically(self):
        # bool is a subclass of int in Python, so `isinstance(True, int)`
        # is true and True would otherwise be filed as frame 1.
        with self.assertRaises(manifest.ManifestError):
            self.row(frame=True)

    def test_a_file_that_is_not_this_row_s_capture_is_refused(self):
        for value, why in (
                ("playthrough/frames/frame_00002.png",
                 "another row's capture"),
                ("playthrough/build/transitions/trans_00001_00.png",
                 "a derived transition image"),
                ("frame_00001.png", "a bare basename"),
                ("/abs/playthrough/frames/frame_00001.png",
                 "an absolute path"),
                ("playthrough/frames/frame_1.png",
                 "an index that is not five digits wide")):
            with self.subTest(file=value):
                with self.assertRaises(manifest.ManifestError,
                                       msg=why) as bad:
                    manifest.build_row(
                        1, value, FIXED_REAL_TS, "08:15:33", "a",
                        "b")
                self.assertIn("one keystroke capture", str(bad.exception))

    def test_a_frame_format_drift_is_warned_about_once(self):
        with _environment(PLAYTHROUGH_FRAME_FORMAT="shot_%d.png"):
            _, first = self.capture_stderr(self.row)
            _, second = self.capture_stderr(self.row)
        self.assertIn("PLAYTHROUGH_FRAME_FORMAT", first)
        self.assertIn(
            "agree byte", first,
            msg=("a capturer and a writer that disagree about the "
                 "filename break the count identity silently"))
        self.assertEqual(
            second, "",
            msg=("a standing condition is reported once per process, "
                 "not once per row of a session"))

    def test_a_matching_frame_format_is_not_warned_about(self):
        with _environment(
                PLAYTHROUGH_FRAME_FORMAT=manifest.FRAME_NAME_FORMAT):
            _, err = self.capture_stderr(self.row)
        self.assertEqual(err, "")


class TestTheClockColumn(ManifestFixture):
    """A reading is recorded as read, or as null.  Never invented."""

    def test_every_classification_is_the_engine_s_own_shape(self):
        cases = (
            (None, manifest.CLOCK_NULL),
            ("08:15:33", manifest.CLOCK_EXACT),
            ("00:00:00", manifest.CLOCK_EXACT),
            (MILITARY_CLOCK, manifest.CLOCK_NONSTANDARD),
            (TWELVE_HOUR_CLOCK, manifest.CLOCK_NONSTANDARD),
            ("8:15:32AM", manifest.CLOCK_NONSTANDARD),
            (UNKNOWN_TIME_TEXT, manifest.CLOCK_UNKNOWN),
            ("48:48:48", manifest.CLOCK_UNRECOGNISED),
            ("half past something", manifest.CLOCK_UNRECOGNISED),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    manifest.classify_ingame_clock(value), expected)

    def test_a_clock_shaped_impossible_time_is_not_called_exact(self):
        """'exact' means a clock that can be believed, so range counts.

        ocr_clock.py applies the same bounds and DECLINES a reading like
        these outright, so labelling one 'exact' here would have the two
        modules describing the same string differently -- and would put
        a self-contradictory pair in timeline.json.
        """
        for value in ("24:00:00", "23:60:00", "23:59:60", "99:99:99",
                      "48:48:48"):
            with self.subTest(value=value):
                self.assertFalse(
                    manifest.is_possible_clock(value),
                    msg="hour <= 23, minute and second <= 59")
                self.assertEqual(
                    manifest.classify_ingame_clock(value),
                    manifest.CLOCK_UNRECOGNISED)

    def test_the_extremes_a_clock_can_show_stay_exact(self):
        for value in ("00:00:00", "23:59:59", "08:15:32"):
            with self.subTest(value=value):
                self.assertTrue(manifest.is_possible_clock(value))
                self.assertEqual(
                    manifest.classify_ingame_clock(value),
                    manifest.CLOCK_EXACT,
                    msg=("the boundaries are readings the engine really "
                         "can render, and they are believable"))

    def test_an_impossible_clock_is_recorded_verbatim_and_warned(self):
        row, err = self.capture_stderr(self.append, clock="24:00:00")
        self.assertEqual(
            row["ingame_clock"], "24:00:00",
            msg=("the reading is evidence: it is recorded exactly as it "
                 "was given and NOT repaired into a plausible time"))
        self.assertIn("no in-game clock can show", err)
        self.assertIn("NOT repaired", err)
        self.assertIn(
            "24:00:00",
            json.loads(self.lines()[0])["ingame_clock"])

    def test_every_coarse_phrase_the_engine_emits_is_recognised(self):
        self.assertEqual(
            len(manifest.COARSE_TIME_PHRASES), 11,
            msg=("display::time_approx() has eleven branches "
                 "(src/display.cpp:159-185)"))
        for phrase in manifest.COARSE_TIME_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    manifest.classify_ingame_clock(phrase),
                    manifest.CLOCK_COARSE,
                    msg=("a survivor with no watch but a view of the "
                         "sky reads one of these; it is a real "
                         "observation, not a failure"))

    def test_a_classification_never_alters_the_reading(self):
        for value in ("08:15:33", COARSE_PHRASE, UNKNOWN_TIME_TEXT,
                      MILITARY_CLOCK):
            with self.subTest(value=value):
                row = self.row(clock=value)
                self.assertEqual(
                    row["ingame_clock"], value,
                    msg="the reading is recorded exactly as it was read")

    def test_a_clock_that_is_not_a_string_is_refused(self):
        for value in (0, 81533, 8.15, True, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(manifest.ManifestError):
                    manifest.classify_ingame_clock(value)
                with self.assertRaises(manifest.ManifestError):
                    self.row(clock=value)

    def test_an_unreadable_clock_is_recorded_as_json_null(self):
        row = self.append(clock=None)
        self.assertIsNone(row["ingame_clock"])
        self.assertIn(
            '"ingame_clock": null', self.lines()[0],
            msg=("null is how an unreadable clock is recorded: no "
                 "default, no neighbouring row, no interpolation"))
        self.assertIsNone(
            manifest.read_rows(
                self.manifest,
                root=self.directory)[0]["ingame_clock"],
            msg="and it reads back as None, not as the string 'null'")

    def test_a_blank_clock_is_refused_in_favour_of_null(self):
        for value in ("", "   ", "\t"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(manifest.ManifestError) as bad:
                    self.row(clock=value)
                self.assertIn("pass None", str(bad.exception))

    def test_an_unrecognised_reading_is_kept_with_a_warning(self):
        row, err = self.capture_stderr(self.row, clock="0O:15:33")
        self.assertEqual(
            row["ingame_clock"], "0O:15:33",
            msg=("refusing it would pressure the caller into inventing "
                 "a value, which is the one thing that must not happen"))
        self.assertIn("matches no known form", err)
        self.assertIn("timeline.py to reconcile", err)

    def test_an_off_contract_clock_shape_is_warned_about_once(self):
        _, first = self.capture_stderr(self.row, clock=MILITARY_CLOCK)
        _, second = self.capture_stderr(
            self.row, clock=TWELVE_HOUR_CLOCK)
        self.assertIn("24_HOUR=24h", first)
        self.assertEqual(
            second, "",
            msg=("the option is either set or it is not: saying so "
                 "once per session is enough"))

    def test_a_multi_line_reading_is_refused(self):
        for value in ("08:15:33\n08:15:34", "08:15:33\r"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(manifest.ManifestError):
                    self.row(clock=value)


class TestTheTimestampColumn(ManifestFixture):
    """One fixed form, so the column sorts as well as it reads."""

    def test_the_canonical_form_round_trips_byte_for_byte(self):
        self.assertEqual(
            manifest.canonical_real_ts(FIXED_REAL_TS), FIXED_REAL_TS)

    def test_the_capture_helper_s_date_output_is_accepted(self):
        # capture.sh stamps `date -u +%Y-%m-%dT%H:%M:%S.%3NZ`, which is
        # exactly this form; the module documents accepting it so the
        # value can pass straight through from the shutter.
        self.assertEqual(
            manifest.canonical_real_ts("2026-05-14T09:12:03.481Z"),
            FIXED_REAL_TS)

    def test_an_offset_timestamp_is_normalised_to_utc(self):
        self.assertEqual(
            manifest.canonical_real_ts("2026-05-14T11:12:03.481+02:00"),
            FIXED_REAL_TS,
            msg="one column, one zone, so a lexical sort is a real sort")

    def test_an_aware_datetime_is_accepted(self):
        moment = datetime.datetime(
            2026, 5, 14, 9, 12, 3, 481000,
            tzinfo=datetime.timezone.utc)
        self.assertEqual(manifest.utc_timestamp(moment), FIXED_REAL_TS)
        self.assertEqual(
            manifest.canonical_real_ts(moment), FIXED_REAL_TS)

    def test_a_naive_datetime_is_refused_rather_than_assumed_utc(self):
        naive = datetime.datetime(2026, 5, 14, 9, 12, 3, 481000)
        for call in (manifest.utc_timestamp,
                     manifest.canonical_real_ts):
            with self.subTest(call=call.__name__):
                with self.assertRaises(manifest.ManifestError) as bad:
                    call(naive)
                self.assertIn("timezone", str(bad.exception))

    def test_the_millisecond_field_is_always_three_digits(self):
        moment = datetime.datetime(
            2026, 1, 2, 3, 4, 5, 6000,
            tzinfo=datetime.timezone.utc)
        self.assertEqual(
            manifest.utc_timestamp(moment),
            "2026-01-02T03:04:05.006Z",
            msg="fixed width, so the column sorts lexically")

    def test_a_timestamp_that_is_not_iso_8601_is_refused(self):
        for value in ("14/05/2026 09:12", "yesterday", "2026-13-45",
                      ""):
            with self.subTest(value=value):
                with self.assertRaises(manifest.ManifestError):
                    manifest.canonical_real_ts(value)

    def test_a_timestamp_of_the_wrong_type_is_refused(self):
        for value in (1747213923, 17.5, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(manifest.ManifestError):
                    manifest.canonical_real_ts(value)

    def test_what_is_written_is_always_the_canonical_form(self):
        # The writer is lenient at the door and strict on the file: each
        # of these is a real instant in another ISO-8601 spelling, and
        # each lands in the column's one form.
        self.write_frames([1, 2, 3])
        for index, supplied, stored in (
            (1, "2026-05-14T09:12:03Z", "2026-05-14T09:12:03.000Z"),
            (2, "2026-05-14 09:12:03.481Z", FIXED_REAL_TS),
            (3, "2026-05-14T11:12:03.481+02:00", FIXED_REAL_TS),
        ):
            with self.subTest(supplied=supplied):
                row = manifest.append_row(
                    self.manifest, index, manifest.frame_file(index),
                    supplied, None, "press 'j'",
                    "South, one step off the kerb.",
                    root=self.directory)
                self.assertEqual(row["real_ts"], stored)
        written = manifest.read_rows(self.manifest, root=self.directory)
        self.assertEqual(
            [row["real_ts"] for row in written],
            ["2026-05-14T09:12:03.000Z", FIXED_REAL_TS,
             FIXED_REAL_TS])
        self.assertEqual(
            manifest.verify_manifest(
                self.manifest, self.frames, require_frames=True,
                root=self.directory),
            [],
            msg="normalised on the way in, so the record is clean")

    def test_a_normalisation_is_disclosed_once(self):
        self.write_frames([1])
        _, first = self.capture_stderr(
            manifest.append_row, self.manifest, 1,
            manifest.frame_file(1), "2026-05-14T09:12:03Z", None,
            "press 'j'", "South, one step off the kerb.",
            root=self.directory)
        self.assertIn("was rewritten to", first)
        self.assertIn("the instant is unchanged", first)
        self.assertIn("capture.sh", first)
        # Standing conditions are reported once per process, as
        # everything else advisory in this module is.
        self.write_frames([2])
        _, second = self.capture_stderr(
            manifest.append_row, self.manifest, 2,
            manifest.frame_file(2), "2026-05-14T09:12:04Z", None,
            "press 'k'", "North again, back the way I came.",
            root=self.directory)
        self.assertEqual(second, "")

    def test_the_canonical_form_is_written_without_a_word(self):
        self.write_frames([1])
        _, said = self.capture_stderr(
            manifest.append_row, self.manifest, 1,
            manifest.frame_file(1), FIXED_REAL_TS, None, "press 'j'",
            "South, one step off the kerb.", root=self.directory)
        self.assertEqual(
            said, "",
            msg="the ordinary case is the whole session; it is silent")

    def test_a_stored_value_in_another_form_is_reported(self):
        # The only way one can arrive: a hand edit or a foreign tool.
        # Every spelling below is the same instant as FIXED_REAL_TS and
        # parses perfectly, which is exactly why row-by-row parsing
        # cannot catch it.
        for other in ("2026-05-14T09:12:03Z",
                      "2026-05-14 09:12:03.481Z",
                      "2026-05-14T11:12:03.481+02:00",
                      "2026-05-14T09:12:03.481000Z"):
            with self.subTest(other=other):
                row = dict(self.row())
                row["real_ts"] = other
                problems = manifest.row_field_problems(row, 1)
                self.assertTrue(
                    any("not the one form" in problem
                        for problem in problems),
                    msg=problems)

    def test_a_mixed_column_fails_verification(self):
        # The end-to-end shape of it: a record whose rows are each
        # valid, whose lexical order is no longer chronological.
        self.write_frames([1, 2])
        self.append(frame=1)
        self.append(frame=2)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        # A LATER instant, spelled with a space instead of the 'T'.  The
        # space sorts before 'T', so this row is chronologically after
        # its neighbour and lexically before it.
        rows[1]["real_ts"] = "2026-05-14 09:12:04.000Z"
        with open(self.manifest, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(manifest.encode_row(row))
        stored = [row["real_ts"] for row in
                  manifest.read_rows(self.manifest,
                                     root=self.directory)]
        self.assertNotEqual(
            stored, sorted(stored),
            msg="the defect being caught: the column no longer sorts")
        problems = manifest.verify_manifest(
            self.manifest, self.frames, require_frames=True,
            root=self.directory)
        self.assertTrue(
            any("not the one form" in problem for problem in problems),
            msg=problems)

    def test_a_stamp_taken_now_is_in_the_canonical_form(self):
        stamped = manifest.utc_timestamp()
        self.assertEqual(
            manifest.canonical_real_ts(stamped), stamped,
            msg="what the module stamps, the module accepts")
        self.assertTrue(stamped.endswith("Z"))
        self.assertEqual(len(stamped), len(FIXED_REAL_TS))


class TestTheNarrativeColumns(ManifestFixture):
    """Every row documents a real keystroke and a real reason for it."""

    def test_an_empty_action_or_commentary_is_refused(self):
        for field in ("action", "commentary"):
            for value in ("", "   ", None):
                with self.subTest(field=field, value=repr(value)):
                    values = {"action": "press '5'",
                              "commentary": "I wait."}
                    values[field] = value
                    with self.assertRaises(manifest.ManifestError):
                        self.row(**values)

    def test_a_non_string_action_or_commentary_is_refused(self):
        with self.assertRaises(manifest.ManifestError):
            self.row(action=5)
        with self.assertRaises(manifest.ManifestError):
            self.row(commentary=["I wait."])

    def test_a_multi_line_action_is_refused(self):
        with self.assertRaises(manifest.ManifestError):
            self.row(action="press '5'\nthen wait")

    def test_a_control_character_is_refused_in_either_column(self):
        """These strings become transcript lines and SRT cue text.

        JSON carries a NUL through as an escape perfectly happily, so
        the manifest would look fine while a later artifact -- or the
        terminal printing it -- would not.
        """
        for char in ("\x00", "\x1b", "\x08", "\x7f", "\x85"):
            for field in ("action", "commentary"):
                with self.subTest(char=repr(char), field=field):
                    values = {"action": "press '5'",
                              "commentary": "I wait."}
                    values[field] = "I wait%s and listen." % char
                    with self.assertRaises(manifest.ManifestError):
                        self.row(**values)
                    self.assertFalse(
                        os.path.exists(self.manifest),
                        msg="a refused row writes nothing at all")

    def test_ordinary_punctuation_and_unicode_are_not_controls(self):
        text = "\u00c9clair -- \u4e2d\u6587 -- \U0001f600, still here."
        self.assertEqual(self.row(commentary=text)["commentary"], text)

    def test_a_runaway_field_is_refused_and_a_long_one_is_advised(self):
        # TWO WORDS AT LEAST, in every fixture here: a one-word
        # commentary is refused on its own account (see
        # narration_substance_problem), and this test is about LENGTH.
        with self.assertRaises(manifest.ManifestError):
            self.row(commentary="cold " * manifest.MAX_FIELD_LENGTH)
        long_enough = "cold " * (manifest.CUE_ADVISORY_LENGTH // 4)
        row, err = self.capture_stderr(self.row,
                                       commentary=long_enough)
        self.assertEqual(
            row["commentary"], long_enough,
            msg=("length that is merely long is advised about, never "
                 "edited: the survivor's words are the survivor's"))
        self.assertIn("more than a reader can take in", err)

    def test_out_of_character_wording_is_refused_not_advised(self):
        """The voice gate REFUSES, and it refuses before the row exists.

        THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE.  This check used
        to print a warning and append the row anyway, which meant one
        stderr line during a four-hundred-row session decided whether an
        engineering observation reached the committed transcript and the
        film's caption track.  Seven rows of the first re-recorded
        session got through that way -- "the game", "the sidebar", "the
        move counter", "the engine's own pathfinding", "cheat" -- and by
        the time anybody read the warning the rows were evidence, and
        evidence is not rewritten afterwards.  So the refusal happens
        here, where nothing has been written yet.
        """
        text = "I check the frame counter before the next screenshot."
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(commentary=text)
        message = str(caught.exception)
        self.assertIn("TECHNICAL_NOTES.md", message)
        self.assertIn(
            text, message,
            msg="the refusal quotes the sentence the writer has to redo")
        self.assertFalse(
            os.path.exists(self.manifest),
            msg="a refused row writes nothing at all")

    def test_the_meta_vocabulary_matches_only_the_meta_sense(self):
        """Precise patterns, because a blunt one refuses honest prose.

        A blunt substring test would have to choose between refusing
        "mechanical engineer" and "the frame of the door" -- both of
        which the survivor says in this very record -- or letting "the
        engine's own pathfinding" through.  Since the gate now BLOCKS,
        that choice is not available: the patterns match the meta sense
        and nothing else.
        """
        for honest in ("She was a mechanical engineer before this.",
                       "The frame of the door is split at the hinge.",
                       "I sharpen the spear.",
                       "The window frames are all broken."):
            with self.subTest(text=honest):
                self.assertEqual(
                    manifest.find_meta_vocabulary(honest), [],
                    msg="in-character prose is not refused")
        for meta, concept in (
                ("the engine's own pathfinding", "engine"),
                ("the game decided otherwise", "game"),
                ("the sidebar says otherwise", "sidebar"),
                ("frame 308 shows the door", "frame index"),
                ("the move counter ticked over", "move counter"),
                ("I could cheat here", "cheat"),
                ("source file monmove.cpp explains it", "source file"),
                ("I open the debug menu", "debug"),
                ("the screenshot after this one", "screenshot")):
            with self.subTest(text=meta):
                self.assertIn(
                    concept, manifest.find_meta_vocabulary(meta),
                    msg="the meta sense is caught by concept name")
        self.assertEqual(
            manifest.find_meta_vocabulary(None), [],
            msg="a non-string is not a text to search")

    def test_the_interface_and_the_character_sheet_are_refused(self):
        """The second class of meta wording a review found shipped.

        Every string below is the wording of a row that actually
        reached playthrough/transcript.md and became a caption on the
        film in the recording this class was written against: the input
        device and the screen furniture the survivor was looking at, and
        that survivor's own body accounted for in the numbers the creator
        prices it in.  None of it is a survivor's sentence, so the gate
        names it -- and none of it is in the record shipped here, which
        is what the gate being blocking rather than advisory bought.
        """
        for meta, concept in (
                ("Stat money goes downhill into the other two",
                 "character sheet"),
                ("it pays me three points for being honest",
                 "character sheet"),
                ("what I cannot do comes later on the trait page",
                 "character sheet"),
                ("the first key I tried did nothing", "keyboard"),
                ("it was moving the cursor down the list", "cursor"),
                ("there is a tab for what I did with my evenings",
                 "form control"),
                ("leave the sex field for a moment", "form control"),
                ("thirty-five per cent off what I can carry",
                 "percentage"),
                ("keep safe mode on and use the opening", "game mode"),
                ("Scores do not change what happened", "game mode")):
            with self.subTest(text=meta):
                self.assertIn(
                    concept, manifest.find_meta_vocabulary(meta),
                    msg="the meta sense is caught by concept name")

    def test_the_survivors_own_numbers_and_keys_are_not_refused(self):
        """The precision half, held against the record's own prose.

        Each sentence below was in the record these patterns were
        measured against and belonged to its survivor: a set of car keys,
        the idiom "no point", a nip point on a mill floor, and hours of
        sleep counted in an ordinary way.  The precision they establish is
        what keeps the gate from refusing prose like it.
        """
        for honest in ("Give me something with keys in it and a road.",
                       "No point being coy about my back.",
                       "A man went into a nip point in ninety-nine.",
                       "Two hours a night. Two more if I am owed one.",
                       "Half an hour. Long enough to breathe.",
                       "I keep the boarded window at my back."):
            with self.subTest(text=honest):
                self.assertEqual(
                    manifest.find_meta_vocabulary(honest), [],
                    msg="in-character prose is not refused")

    def test_the_published_narration_passes_the_voice_gate(self):
        """The evidence in this checkout is held to the gate as well.

        HELD AGAINST THE RESOLVED ROWS, WHICH IS WHERE IT BELONGS.  This
        used to read the recorded commentaries directly, from a tree
        whose record had been rewritten to satisfy it.  A captured row is
        not editable -- rewriting one is the defect the amendment ledger
        exists to replace -- so the sentence held to the voice gate is
        the one a reader actually meets: the resolved sentence, which is
        what goes verbatim into playthrough/transcript.md and onto the
        caption track.  Nothing is thereby excused: a recorded meta word
        with no amendment behind it survives resolution unchanged and is
        reported by the same assertion, and the second check below is the
        stronger statement that every offender has a correction bound to
        its own digest rather than merely being tolerated.

        Read-only, and skipped rather than failed where the record is
        absent, so the suite still runs in a checkout without it.
        """
        tree = os.path.join(
            os.path.dirname(os.path.abspath(manifest.__file__)),
            os.pardir)
        real = os.path.join(tree, "manifest.jsonl")
        if not os.path.exists(real):
            self.skipTest("no captured record in this checkout")
        rows = manifest.read_rows(real)
        ledger = os.path.join(tree, manifest.AMENDMENTS_NAME)
        amendments = (manifest.read_amendments(ledger)
                      if os.path.exists(ledger) else ())
        resolved, _amended = manifest.resolve_rows(rows, amendments)
        offenders = [
            (row["frame"], manifest.find_meta_vocabulary(
                row["commentary"]))
            for row in resolved
            if manifest.find_meta_vocabulary(row["commentary"])]
        self.assertEqual(
            offenders, [],
            msg=("every published commentary is in the survivor's own "
                 "voice; a hit here is a row to amend in "
                 "playthrough/amendments.jsonl"))
        # And every recorded row the gate does name carries an
        # amendment, so none of them is simply being lived with.
        amended = {(one["frame"], one["field"]) for one in amendments}
        for row in rows:
            if manifest.find_meta_vocabulary(row["commentary"]):
                with self.subTest(frame=row["frame"]):
                    self.assertIn(
                        (row["frame"], "commentary"), amended,
                        msg=("a recorded commentary the voice gate "
                             "names must be corrected by an "
                             "amendment, not left to the reader"))

    def test_every_concept_is_named_in_the_declared_order(self):
        """A refusal reads the same way every time it is produced."""
        self.assertEqual(
            manifest.find_meta_vocabulary(
                "the ocr pipeline read the sidebar"),
            ["sidebar", "ocr", "pipeline"],
            msg=("the concepts come back in META_PATTERNS order, so the "
                 "message is stable across runs"))
        self.assertEqual(
            manifest.find_meta_vocabulary("sidebar, sidebar, sidebar"),
            ["sidebar"],
            msg="a concept is named once however often it is said")
        self.assertEqual(
            list(manifest.META_VOCABULARY),
            [name for name, _ in manifest.META_PATTERNS],
            msg=("the published vocabulary IS the concept names of the "
                 "pattern table, not a second list beside it"))

    def test_the_refusal_names_the_concepts_and_where_they_belong(self):
        """One message, shared by every consumer of the gate."""
        problem = manifest.meta_vocabulary_problem(
            "the engine's own pathfinding", "row 12 commentary")
        self.assertIsNotNone(problem)
        self.assertIn("row 12 commentary", problem)
        self.assertIn("engine", problem)
        self.assertIn("pathfinding", problem)
        self.assertIn("TECHNICAL_NOTES.md", problem)
        self.assertIn("REFUSED", problem)
        self.assertIsNone(
            manifest.meta_vocabulary_problem("I sharpen the spear."),
            msg="clean prose produces no problem at all")


class TestSentinelsAreRefusedNotAdvised(ManifestFixture):
    """A field that says it is not a record is refused at both ends.

    THE DEFECT THIS CLASS EXISTS FOR IS A REAL ONE.  Row 116 of
    playthrough/manifest.jsonl carried the action
    `press 'X' -- nothing; see note` with the commentary `placeholder`,
    while row 117 stated that the key actually delivered was `-`.  Six
    fields, the right index, the right capture path, a real timestamp,
    non-empty strings: every structural check in this suite passed over
    it, and the false statement propagated into a timeline, a transcript
    and a caption file.

    So the assertions below are not about tone.  They hold that the
    writer refuses such a row outright, that the reader reports one that
    is already on disk, that BOTH go through the single gate
    sentinel_problems() -- which is also the gate timeline.py reaches
    through row_problems() -- and that the rule stays narrow enough not
    to catch the survivor's ordinary prose.
    """

    # The historical defect, quoted exactly, so a regression is caught by
    # the very text that motivated the rule.
    BAD_ACTION = "press 'X' -- nothing; see note"
    BAD_COMMENTARY = "placeholder"

    def test_every_declared_placeholder_word_is_found(self):
        for word in manifest.PLACEHOLDER_WORDS:
            with self.subTest(word=word):
                self.assertEqual(
                    manifest.find_placeholder_words(
                        "I waited. %s. Then I moved." % word),
                    [word],
                    msg=("every word on the declared list has to be "
                         "reachable, or the list lies about its scope"))

    def test_a_placeholder_word_is_matched_case_folded(self):
        self.assertEqual(
            manifest.find_placeholder_words("PLACEHOLDER"), ["placeholder"])
        self.assertEqual(
            manifest.find_placeholder_words("ToDo"), ["todo"])

    def test_every_hit_is_listed_once_and_sorted(self):
        self.assertEqual(
            manifest.find_placeholder_words("todo placeholder TODO"),
            ["placeholder", "todo"],
            msg="de-duplicated and sorted, so the report is stable")

    def test_ordinary_prose_is_not_caught(self):
        """The rule is whole-word for a reason: prose has to survive it.

        Each string below is something a survivor could plausibly write,
        and each one would be caught by a naive substring test.
        """
        for text in ("I placed the crowbar on the counter.",
                     "I did nothing but listen.",
                     "The wipers were still going.",
                     "A wide-brimmed hat, of all things.",
                     "Todos are not a word I would use.",
                     "Two boxes of .22, then a wipe-down of the barrel."):
            with self.subTest(text=text):
                self.assertEqual(
                    manifest.find_placeholder_words(text), [],
                    msg="in-character prose must pass untouched")

    def test_every_declared_deferral_phrase_is_found(self):
        for phrase in manifest.UNRECORDED_ACTION_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    manifest.find_unrecorded_action_phrases(
                        "press 'X' -- %s" % phrase.upper()),
                    [phrase],
                    msg="case-folded, and every declared phrase reachable")

    def test_a_non_string_is_not_a_text_to_search(self):
        for value in (None, 5, ["placeholder"], {"a": "todo"}):
            with self.subTest(value=repr(value)):
                self.assertEqual(
                    manifest.find_placeholder_words(value), [])
                self.assertEqual(
                    manifest.find_unrecorded_action_phrases(value), [])

    def test_the_writer_refuses_a_placeholder_commentary(self):
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(commentary=self.BAD_COMMENTARY)
        self.assertIn("placeholder marker", str(caught.exception))
        self.assertIn("commentary", str(caught.exception))

    def test_the_writer_refuses_a_placeholder_action(self):
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(action="press 'X' -- TODO")
        self.assertIn("placeholder marker", str(caught.exception))
        self.assertIn("action", str(caught.exception))

    def test_the_writer_refuses_an_action_that_defers_the_record(self):
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(action=self.BAD_ACTION)
        self.assertIn("defers the record elsewhere",
                      str(caught.exception))

    def test_a_deferral_in_the_commentary_is_not_this_rule(self):
        """Only `action` is held to the deferral list, deliberately.

        A survivor may legitimately write "the shelf I saw above", and
        commentary is prose about a reason rather than a statement of
        which key was pressed.  The placeholder half still applies to
        both fields; this half applies to one.
        """
        row = self.row(commentary="I took the tin from the shelf above.")
        self.assertEqual(
            row["commentary"], "I took the tin from the shelf above.")

    def test_the_historical_defect_is_refused_as_it_was_written(self):
        with self.assertRaises(manifest.ManifestError):
            self.row(action=self.BAD_ACTION,
                     commentary=self.BAD_COMMENTARY)

    def test_a_refused_sentinel_row_writes_nothing_at_all(self):
        with self.assertRaises(manifest.ManifestError):
            self.append(commentary=self.BAD_COMMENTARY)
        self.assertFalse(
            os.path.exists(self.manifest),
            msg=("the writer refuses before it opens the file, so a "
                 "sentinel row never has to be corrected afterwards"))

    def test_a_refused_sentinel_row_leaves_the_record_byte_identical(self):
        self.append(frame=1)
        before = _read_bytes(self.manifest)
        with self.assertRaises(manifest.ManifestError):
            self.append(frame=2, action="press 'X' -- see note")
        self.assertEqual(
            _read_bytes(self.manifest), before,
            msg="a refused row cannot disturb the rows already written")

    def test_the_reader_reports_a_sentinel_row_already_on_disk(self):
        """The writer cannot help a record that predates the gate.

        The row is written by hand, because build_row() would refuse it
        -- which is the point: this is the path by which the real
        defect was found, and it has to keep working.
        """
        row = self.row(frame=1)
        row["action"] = self.BAD_ACTION
        row["commentary"] = self.BAD_COMMENTARY
        _write_lines(self.manifest, [json.dumps(row)])
        self.write_frames([1])
        problems = manifest.verify_manifest(
            self.manifest, frames_dir=self.frames,
            require_frames=True, root=self.directory)
        self.assertTrue(
            any("placeholder marker" in problem for problem in problems),
            msg="the placeholder commentary must be reported: %r"
                % problems)
        self.assertTrue(
            any("defers the record elsewhere" in problem
                for problem in problems),
            msg="the deferring action must be reported: %r" % problems)

    def test_the_reader_and_the_writer_share_one_gate(self):
        """row_field_problems() is the gate, and row_problems() is how
        every reader in the pipeline -- verify_manifest() here,
        timeline.py through row_problems() -- reaches it."""
        row = self.row(frame=1)
        row["commentary"] = self.BAD_COMMENTARY
        field = manifest.row_field_problems(row, 1)
        shared = manifest.row_problems([row])
        self.assertTrue(
            any("placeholder marker" in problem for problem in field),
            msg="the field gate reports it: %r" % field)
        self.assertTrue(
            any("placeholder marker" in problem for problem in shared),
            msg=("row_problems() is what timeline.py calls, so the same "
                 "sentinel must surface there: %r" % shared))

    def test_the_message_names_the_row_the_reader_is_reading(self):
        row = self.row(frame=7)
        row["commentary"] = self.BAD_COMMENTARY
        problems = manifest.row_field_problems(row, 7)
        self.assertTrue(
            any(problem.startswith("row 7") for problem in problems),
            msg="a report has to say which row: %r" % problems)

    def test_the_message_names_the_frame_the_writer_refused(self):
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(frame=7, commentary=self.BAD_COMMENTARY)
        self.assertIn("frame 7", str(caught.exception))

    def test_sentinel_problems_reports_and_changes_nothing(self):
        action = self.BAD_ACTION
        commentary = self.BAD_COMMENTARY
        problems = manifest.sentinel_problems(action, commentary, "row 1")
        self.assertEqual(len(problems), 2)
        self.assertEqual(action, self.BAD_ACTION)
        self.assertEqual(commentary, self.BAD_COMMENTARY)
        self.assertEqual(
            manifest.sentinel_problems("press '5'", "I wait.", "row 1"),
            [],
            msg="a real row produces no problems")

    def test_the_sentinel_rule_and_the_voice_rule_stay_distinct(self):
        """Both refuse now, and they refuse for different reasons.

        They used to differ in kind -- one raised, the other warned --
        and that difference is gone: an out-of-character sentence is
        refused too.  What has to stay distinct is WHICH rule fired,
        because the operator's remedy differs: a sentinel means the row
        does not record anything and has to be written; a voice hit means
        the observation is real but belongs in TECHNICAL_NOTES.md.
        """
        text = "I check the frame counter before the next screenshot."
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(commentary=text)
        self.assertIn("TECHNICAL_NOTES.md", str(caught.exception))
        self.assertEqual(
            manifest.sentinel_problems("press '5'", text, "row 1"), [],
            msg=("a voice hit is not a sentinel: the sentence says "
                 "something, it just says the wrong sort of thing"))
        self.assertNotEqual(
            manifest.sentinel_problems(
                self.BAD_ACTION, self.BAD_COMMENTARY, "row 1"), [],
            msg="and a sentinel is still a sentinel")

    def test_the_two_lists_do_not_overlap_with_the_voice_vocabulary(self):
        """A word cannot belong to two rules with two messages.

        If it did, the same string would produce a different refusal
        depending on which check ran first, and the distinction the
        module documents would be undecidable from the outside.
        """
        voice = {word.lower() for word in manifest.META_VOCABULARY}
        fatal = {word.lower() for word in manifest.PLACEHOLDER_WORDS}
        self.assertEqual(voice & fatal, set())

    def test_the_real_record_carries_no_sentinel(self):
        """The evidence in this checkout is held to the rule as well.

        Read-only, and skipped rather than failed where the record is
        absent, so the suite still runs in a checkout without it.
        """
        real = os.path.join(
            os.path.dirname(os.path.abspath(manifest.__file__)),
            os.pardir, "manifest.jsonl")
        if not os.path.exists(real):
            self.skipTest("no captured record in this checkout")
        offenders = []
        with open(real, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if manifest.sentinel_problems(
                        row.get("action"), row.get("commentary"),
                        "row %d" % number):
                    offenders.append(number)
        self.assertEqual(
            offenders, [],
            msg=("every row of the committed record has to say what was "
                 "pressed and why; these do not: %r" % offenders))


class TestRawMarkupNeverReachesTheRecord(ManifestFixture):
    """A review finding, end to end: the payload and where it landed.

    playthrough/transcript.md is Markdown and Markdown passes raw HTML
    to whatever renders it.  The wide guard existed -- it held the
    transcript's generated HEADING -- while the body was held only to the
    caption gate, which names the styling tags a cue could carry (font,
    i, b, u, s) and does not name `img`.  So a commentary reading
    `<img src=x onerror=alert(1)>` passed every check in the pipeline and
    was written verbatim into a committed document.

    The rule now lives in this module and is applied where text ENTERS
    the record, on both narrations and on both sides of an amendment.
    Refused rather than escaped: this artifact is evidence, and a
    sentence carrying markup is a fault to report rather than a string to
    clean.
    """

    PAYLOADS = (
        '<img src=x onerror=alert(1)>',
        'I look at <b>the shelf</b> and take the tin.',
        'The tin says beans &amp; frankfurters, so I keep it.',
        'I check the shelf onerror=alert(1) and move on.',
    )

    def test_the_writer_refuses_a_payload_in_the_commentary(self):
        for payload in self.PAYLOADS:
            with self.subTest(payload=payload):
                with self.assertRaises(manifest.ManifestError) as caught:
                    self.row(commentary=payload)
                self.assertIn("frame 1 commentary",
                              str(caught.exception))

    def test_the_writer_refuses_a_payload_in_the_action(self):
        with self.assertRaises(manifest.ManifestError) as caught:
            self.row(action="press '5' -- wait <script>alert(1)</script>")
        self.assertIn("frame 1 action", str(caught.exception))

    def test_nothing_is_written_when_a_payload_is_refused(self):
        self.write_frames([1])
        with self.assertRaises(manifest.ManifestError):
            self.append(commentary=self.PAYLOADS[0])
        self.assertFalse(
            os.path.exists(self.manifest),
            msg="a refused row writes nothing at all")

    def test_ordinary_prose_with_a_hyphen_or_a_quote_still_passes(self):
        for text in ("I take the tin -- it is the only food here.",
                     "The label says 'beans', so it is food.",
                     "I am not sure it is safe, but I am hungry."):
            with self.subTest(text=text):
                self.assertEqual(self.row(commentary=text)["commentary"],
                                 text)

    def test_the_rule_is_reported_rather_than_raised_for_a_caller(self):
        """A pure predicate, so a caller can ask before it writes."""
        self.assertIsNone(
            manifest.raw_markup_problem("I take the tin.", "commentary"))
        problem = manifest.raw_markup_problem(
            "<img src=x onerror=alert(1)>", "commentary")
        self.assertIn("angle bracket", problem)
        self.assertIn("transcript.md", problem)

    def test_the_real_record_carries_no_markup(self):
        """The delivered evidence is held to the rule as well."""
        real = os.path.join(
            os.path.dirname(os.path.abspath(manifest.__file__)),
            os.pardir, "manifest.jsonl")
        if not os.path.exists(real):
            self.skipTest("no captured record in this checkout")
        offenders = []
        with open(real, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                for name in ("action", "commentary"):
                    if manifest.raw_markup_problem(row.get(name), name):
                        offenders.append((number, name))
        self.assertEqual(offenders, [], msg=repr(offenders))


class TestAOneWordCommentaryIsNotAReason(ManifestFixture):
    """R7 asks WHY, and a review found 44 entries answering with a label.

    42 of them were the letter that had just been typed into a search
    box, plus "Next." and "Five.".  Each passed every structural check --
    non-empty, in voice, free of markup, closing as a sentence -- and
    accounted for nothing.  The one-word shape is the part of that class
    a program can tell from a reason, so the writer refuses it, where the
    driver still knows what they were doing.

    THE READER IS DELIBERATELY NOT GIVEN THIS RULE.  The delivered record
    still holds those 44 rows, because it is append-only; they are
    corrected in playthrough/amendments.jsonl and every derivative reads
    through resolve_rows().  A reader that refused them would refuse to
    read the very record the ledger exists to correct.
    """

    def test_the_writer_refuses_a_single_word(self):
        for payload in ("M.", "Next.", "Five.", "South", "Again!"):
            with self.subTest(payload=payload):
                with self.assertRaises(manifest.ManifestError) as caught:
                    self.row(commentary=payload)
                self.assertIn("which is one word", str(caught.exception))

    def test_two_words_are_the_writer_s_whole_rule(self):
        """Length is a judgement; naming the keystroke is not."""
        self.assertEqual(self.row(commentary="South, quickly.")[
            "commentary"], "South, quickly.")

    def test_the_reader_still_reads_a_one_word_row(self):
        """The property that keeps the delivered record readable."""
        row = dict(self.row())
        row["commentary"] = "M."
        self.assertEqual(
            [problem for problem in manifest.row_field_problems(row, 1)
             if "one word" in problem], [])

    def test_the_rule_is_reported_rather_than_raised_for_a_caller(self):
        self.assertIsNone(
            manifest.narration_substance_problem("South, quickly."))
        problem = manifest.narration_substance_problem("M.")
        self.assertIn("one word", problem)
        self.assertIn("in the survivor's own voice", problem)


class TestTheActionNamesAKeystroke(ManifestFixture):
    """Runtime QA finding: the writer took any non-empty action text.

    session.py derives the identity half of every action from the string
    that reaches xdotool, so a row cannot name a key that was not sent --
    but the guarantee lived entirely in that caller, and this writer
    accepted `step`, `a` or any other prose.  A QA pass recorded it as a
    defence-in-depth gap: unreachable through `session.py step`, open to
    anything else importing this module.  The shape is now the writer's
    rule too.
    """

    CONFORMING = (
        "press '5'",
        "press '5' -- wait thirty minutes in the wall-backed position",
        "press 'period' -- interrupt; nothing on the screen changed",
        "press 'shift+2' -- strike the at sign for the sex field",
        "press 'Return'",
    )

    REFUSED = (
        "step",
        "a",
        "pressed '5'",
        "press 5",
        "press '' -- the key that is not there",
        "press '5' -- ",
        "press '5' -- a -- b",
    )

    def test_the_shape_of_every_real_action_is_accepted(self):
        for action in self.CONFORMING:
            with self.subTest(action=action):
                self.assertIsNone(
                    manifest.action_shape_problem(action, "row 1"))
                self.assertEqual(self.row(action=action)["action"],
                                 action)

    def test_prose_that_names_no_keystroke_is_refused(self):
        for action in self.REFUSED:
            with self.subTest(action=action):
                self.assertIsNotNone(
                    manifest.action_shape_problem(action, "row 1"))
                with self.assertRaises(manifest.ManifestError) as caught:
                    self.row(action=action)
                self.assertIn("does not name a keystroke",
                              str(caught.exception))

    def test_a_refused_action_writes_nothing_at_all(self):
        self.append(frame=1)
        before = _read_bytes(self.manifest)
        with self.assertRaises(manifest.ManifestError):
            self.append(frame=2, action="step")
        self.assertEqual(
            _read_bytes(self.manifest), before,
            msg="a refused row cannot disturb the rows already written")
        self.assertEqual(len(self.lines()), 1)

    def test_the_reader_still_reports_rather_than_refuses(self):
        """A foreign row is a REPORTED problem, not an unreadable file.

        The reader deliberately does not apply this rule: the committed
        record is 419 rows of exactly this shape, and a reader that
        refused anything else would turn one bad row into a manifest no
        stage could count.
        """
        self.append(frame=1)
        with open(self.manifest, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "frame": 2, "file": manifest.frame_file(2),
                "real_ts": FIXED_REAL_TS, "ingame_clock": "08:15:34",
                "action": "step", "commentary": "I move."}) + "\n")
        rows = manifest.read_rows(self.manifest, root=self.directory)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            manifest.row_field_problems(rows[1], 2), [],
            msg="the schema gate is unchanged; only the writer is new")

    def test_the_shape_rule_names_no_keysym_vocabulary(self):
        """Which keys may be SENT stays session.py's single answer.

        Two tables would be two answers to one question, so this module
        checks that a keystroke is named and not which one it is.
        """
        for key in ("q", "F12", "KP_7", "shift+plus", "semicolon"):
            with self.subTest(key=key):
                self.assertIsNone(manifest.action_shape_problem(
                    "press '%s' -- reach for it" % key, "row 1"))

    def test_the_real_record_names_a_keystroke_on_every_row(self):
        real = os.path.join(
            os.path.dirname(os.path.abspath(manifest.__file__)),
            os.pardir, "manifest.jsonl")
        if not os.path.exists(real):
            self.skipTest("no captured record in this checkout")
        offenders = []
        with open(real, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if manifest.action_shape_problem(
                        row.get("action"), "row %d" % number):
                    offenders.append(number)
        self.assertEqual(offenders, [], msg=repr(offenders))


class TestReadingATimeOutOfProse(unittest.TestCase):
    """The parser under the clock-honesty gate.  Pure, read-only.

    Deliberately conservative twice over.  It reads only a time the
    sentence ASSERTS IS THE CASE NOW -- see TestOnlyAnAssertedTimeIsRead
    below for why -- and within that, only the three shapes the module
    declares, so a way of saying a time that it does not recognise is
    simply NOT CHECKED rather than guessed at.  A gate that guessed would
    refuse honest sentences, and there would be no honest way to tell
    from the outside which it had done.
    """

    def test_digits_are_read_as_written(self):
        self.assertEqual(
            manifest.stated_times("The clock reads 20:15."),
            [((20 * 3600 + 15 * 60,), False)],
            msg="a 24-hour reading is unambiguous")
        self.assertEqual(
            manifest.stated_times("The clock reads 08:05:36."),
            [((8 * 3600 + 5 * 60,), False)],
            msg=("a leading zero says which half of the day is meant, "
                 "so there is one candidate and not two"))

    def test_a_bare_twelve_hour_statement_yields_both_readings(self):
        """English is ambiguous and the gate does not pretend otherwise.

        "5:30" could be either half of the day, so BOTH are candidates
        and the comparison accepts whichever is closer.  Refusing a
        sentence for the ambiguity of English would catch nothing real.
        """
        times = manifest.stated_times("The clock says 5:30.")
        self.assertEqual(len(times), 1)
        candidates, hedged = times[0]
        self.assertEqual(
            sorted(candidates),
            [5 * 3600 + 30 * 60, 17 * 3600 + 30 * 60])
        self.assertFalse(hedged)

    def test_a_meridiem_resolves_the_ambiguity(self):
        for text, expected in (
                ("five in the afternoon", 17 * 3600),
                ("five in the morning", 5 * 3600),
                ("nine at night", 21 * 3600),
                ("seven o'clock this evening", 19 * 3600)):
            with self.subTest(text=text):
                times = manifest.stated_times("It is %s." % text)
                self.assertTrue(times, msg="the shape is recognised")
                self.assertIn(
                    expected, times[0][0],
                    msg="the half of the day is taken from the phrase")

    def test_relative_statements_are_read(self):
        for text, expected in (
                ("ten past eight in the morning", 8 * 3600 + 10 * 60),
                ("quarter past six in the morning", 6 * 3600 + 15 * 60),
                ("half past nine in the morning", 9 * 3600 + 30 * 60),
                ("twenty to nine in the morning", 8 * 3600 + 40 * 60),
                ("five to five in the afternoon", 16 * 3600 + 55 * 60)):
            with self.subTest(text=text):
                candidates = [
                    one for group, _ in manifest.stated_times(
                        "It is %s." % text) for one in group]
                self.assertIn(
                    expected, candidates,
                    msg="the offset and direction are both applied")

    def test_a_hedge_is_carried_out_of_the_same_match(self):
        times = manifest.stated_times("It is about eight in the morning.")
        self.assertTrue(times)
        self.assertTrue(
            any(hedged for _, hedged in times),
            msg=("the hedge has to come from the match that produced the "
                 "time, or the tolerance would be chosen for the wrong "
                 "statement"))
        unhedged = manifest.stated_times("It is eight in the morning.")
        self.assertTrue(unhedged)
        self.assertFalse(
            all(hedged for _, hedged in unhedged),
            msg="and an unhedged statement claims precision")

    def test_prose_with_no_time_in_it_yields_nothing(self):
        for text in ("I push the door open and step through.",
                     "I have five bandages and two cans left.",
                     "", "   ", None, 5):
            with self.subTest(text=repr(text)):
                self.assertEqual(manifest.stated_times(text), [])

    def test_an_impossible_hour_is_not_a_time(self):
        self.assertEqual(
            manifest.stated_times("It is 25:99 by the loading dock."), [],
            msg="an hour above 23 is not a time of day")

    def test_dates_are_read_in_both_orders(self):
        for text in ("the twenty-eighth of May", "the 28th of May",
                     "May 28", "May the twenty-eighth"):
            with self.subTest(text=text):
                self.assertIn(
                    (28, "may"), manifest.stated_dates("It is %s." % text))

    def test_a_day_outside_the_month_is_not_a_date(self):
        self.assertEqual(
            [pair for pair in manifest.stated_dates("Today is May 47")
             if pair[0]],
            [], msg="47 is not a day of any month")

    def test_the_sidebar_date_line_is_read_as_the_engine_writes_it(self):
        self.assertEqual(
            manifest.observed_date_parts("Thursday, May 20"), (20, "may"),
            msg="the default SHOW_MONTHS form")
        self.assertEqual(
            manifest.observed_date_parts("Summer, day 12"),
            (12, "summer"),
            msg=("with SHOW_MONTHS off the line names a season, and a "
                 "statement naming one is checked the same way"))
        for text in ("", "   ", None, "nothing legible here"):
            with self.subTest(text=repr(text)):
                self.assertIsNone(
                    manifest.observed_date_parts(text),
                    msg=("a line that says nothing comparable is 'cannot "
                         "check', never 'agrees'"))

    def test_only_a_fixed_width_reading_becomes_seconds(self):
        self.assertEqual(
            manifest.clock_seconds_of_day("08:05:36"),
            8 * 3600 + 5 * 60 + 36)
        for value in ("Around dawn", "???", "8:5:6", "25:00:00",
                      "08:61:00", "08:05", "", None, 5):
            with self.subTest(value=repr(value)):
                self.assertIsNone(
                    manifest.clock_seconds_of_day(value),
                    msg=("a reading that cannot be compared is None, "
                         "which the gate treats as 'cannot check'"))


class TestOnlyAnAssertedTimeIsRead(unittest.TestCase):
    """The scope of the gate, and the reason it is this narrow.

    THE CORPUS BELOW IS REAL PROSE FROM THE COMMITTED RECORD.  An earlier
    version of this gate adjudicated every time and date a sentence
    contained, and run over the 395 rows of the first re-recorded session
    it reported 43 problems of which exactly ONE was the defect the review
    found.  The other 42 were honest English -- reminiscence about a life
    twenty years before the Cataclysm, generalisations about cold houses,
    retrospect about a lamp left burning, intentions, and spans of hours.

    A gate that cries wolf 42 times out of 43 is a gate somebody switches
    off, which is precisely the failure the advisory voice check already
    demonstrated.  So the gate reads only a time or date the sentence
    asserts IS THE CASE NOW, and these tests hold it to that -- in both
    directions, because a narrow gate that stopped catching frame 308
    would be no gate at all.
    """

    # Sentences that MENTION a time without asserting one.  Every one of
    # these is real, and every one was refused by the unrestricted gate.
    HONEST = (
        "Not a hobbyist. I was the one they phoned at three in the "
        "morning.",
        "Twenty-two years of standing outside a fire door at two in the "
        "morning.",
        "Forty-seven years old, mechanical engineer, and still here at "
        "seven in the morning on the fifth day.",
        "layers are the whole argument at four in the morning when the "
        "house is the same temperature as the yard",
        "That lamp has been burning since eight o'clock for a room I "
        "have now looked at from every corner.",
        "the floral blanket still folded back exactly where I left it "
        "at half past eight",
        "It has been burning since five o'clock and I want every hour "
        "of it I can keep.",
        "Three hours. That puts me at ten past eight with the sun off "
        "the roofs.",
        "Six hours this time. Eleven to five in the afternoon.",
        "Twenty past eight until quarter past two, tossing and "
        "turning.",
        "the alarm was set for five past five",
        "the toilet I did not find until five in the afternoon",
    )

    def test_no_sentence_that_merely_mentions_a_time_is_read(self):
        for text in self.HONEST:
            with self.subTest(text=text[:48]):
                self.assertEqual(
                    manifest.stated_times(text), [],
                    msg=("this sentence states no time; adjudicating it "
                         "would refuse honest English"))

    def test_none_of_the_honest_corpus_is_a_problem(self):
        for text in self.HONEST:
            with self.subTest(text=text[:48]):
                self.assertEqual(
                    manifest.clock_honesty_problems(
                        text, "02:14:49", "Thursday, May 20"),
                    [], msg="and none of them fails the gate")

    def test_every_assertion_form_is_recognised(self):
        for prefix in ("It is", "it's", "It is now", "The clock reads",
                       "The clock says", "The clock shows",
                       "The time is"):
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    manifest.stated_times("%s 20:15." % prefix),
                    msg="this is how a person states the case")
        for prefix in ("Today is", "The date is", "It is"):
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    manifest.stated_dates("%s May 20." % prefix),
                    msg="and this is how a person states the day")

    def test_the_four_ways_a_reference_gets_in_are_excluded(self):
        for text in ("at 20:15", "since 20:15", "until 20:15",
                     "for 20:15", "it has been 20:15 for an hour",
                     "it was 20:15 when I lay down"):
            with self.subTest(text=text):
                self.assertEqual(
                    manifest.stated_times(text), [],
                    msg=("a preposition or a past tense is a reference, "
                         "not an assertion"))

    def test_the_window_keeps_a_distant_mention_out(self):
        """An assertion introduces the time next to it, not any time.

        Without the window, "It is cold, and I remember being phoned at
        three in the morning" would be adjudicated as a statement that it
        is three in the morning.
        """
        self.assertEqual(
            manifest.stated_times(
                "It is cold, and I remember being phoned at three in "
                "the morning."),
            [], msg="the mention is too far from the assertion")
        self.assertTrue(
            manifest.stated_times("It is ten past eight in the morning."),
            msg="and the statement next to it is read")

    def test_only_the_time_the_assertion_introduced_is_read(self):
        """One assertion, one statement -- not every time after it.

        Real row: "It is six minutes past eight now and nine hours puts
        me at five past five" -- the first clause is a statement of the
        present and the second is arithmetic about tomorrow morning.
        """
        times = manifest.stated_times(
            "It is six minutes past eight now and nine hours puts me at "
            "five past five in the morning.")
        self.assertEqual(len(times), 1, msg=repr(times))
        self.assertIn(20 * 3600 + 6 * 60, times[0][0])

    def test_a_date_is_reached_across_the_time_it_follows(self):
        """The exact shape the false frame-308 statement took."""
        self.assertEqual(
            manifest.stated_dates(
                "It is ten past eight in the morning on the "
                "twenty-eighth of May."),
            [(28, "may")],
            msg=("the date clause follows the time clause inside one "
                 "assertion, and both are adjudicated"))

    def test_a_bare_am_is_a_verb_and_not_a_meridiem(self):
        """THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE, TWICE.

        The meridiem markers were once tested as substrings, so "am"
        matched inside "game" and resolved "Half past eight and the game
        asked me" to 08:30 -- refusing a true statement made at 20:30.
        Matched as a whole word it was still wrong, because "am" is the
        commonest verb in English: " and I am not starting anything"
        resolved "ten past five" to 05:10.
        """
        times = manifest.stated_times(
            "It is half past eight and the flame is out.")
        self.assertTrue(times)
        self.assertIn(
            20 * 3600 + 30 * 60, times[0][0],
            msg="'flame' does not make it the morning")
        times = manifest.stated_times(
            "It is ten past five and I am not starting anything now.")
        self.assertTrue(times)
        self.assertIn(
            17 * 3600 + 10 * 60, times[0][0],
            msg="'I am' does not make it the morning")
        times = manifest.stated_times("It is 8am.")
        self.assertEqual(
            times[0][0], (8 * 3600,),
            msg=("but a meridiem where a meridiem goes -- right after "
                 "the number -- is still read"))
        times = manifest.stated_times("It is 8 pm.")
        self.assertEqual(times[0][0], (20 * 3600,))


class TestTheClockHonestyGate(unittest.TestCase):
    """A statement of time or date is held to what the frame showed.

    THE DEFECT THIS CLASS EXISTS FOR IS A REAL ONE, AND IT IS THE WORST
    KIND THE RECORD CAN CARRY, because every structural check passed
    straight over it.  Frame 308 of the first re-recorded session was
    captured at 08:05:36 on Thursday, May 20 -- the clock and the date
    line the sidebar actually showed, read by ocr_clock.py, stored in the
    row and copied into the timeline -- and its commentary says, in the
    survivor's own voice: "It is ten past eight in the morning on the
    twenty-eighth of May."  Neither statement is true.  The row was
    internally consistent, the counts all tallied, the timeline
    arithmetic was exact, and the film shipped a false statement of fact
    in a record whose first requirement is that nothing in it is
    fabricated.
    """

    FALSE_308 = ("It is ten past eight in the morning on the "
                 "twenty-eighth of May.")
    CLOCK_308 = "08:05:36"
    DATE_308 = "Thursday, May 20"

    def test_the_exact_frame_308_sentence_is_caught(self):
        problems = manifest.clock_honesty_problems(
            self.FALSE_308, self.CLOCK_308, self.DATE_308)
        self.assertEqual(
            len(problems), 2,
            msg=("both false statements are reported -- the time and the "
                 "date -- because fixing one leaves the other: %r"
                 % problems))
        joined = " ".join(problems)
        self.assertIn("08:10:00", joined)
        self.assertIn(self.CLOCK_308, joined)
        self.assertIn("28", joined)
        self.assertIn(self.DATE_308, joined)
        self.assertIn(
            "authoritative", joined,
            msg="the message says which of the two the record believes")

    def test_the_true_version_of_the_same_sentence_passes(self):
        self.assertEqual(
            manifest.clock_honesty_problems(
                "It is six past eight in the morning on the twentieth "
                "of May.", self.CLOCK_308, self.DATE_308),
            [], msg=("the gate exists to make the honest sentence "
                     "writable, not to make every sentence suspect"))

    def test_a_hedge_buys_a_wider_tolerance_and_no_more(self):
        self.assertGreater(manifest.HEDGED_TIME_TOLERANCE,
                           manifest.TIME_TOLERANCE)
        self.assertEqual(
            manifest.clock_honesty_problems(
                "It is around ten past eight in the morning.",
                self.CLOCK_308, self.DATE_308),
            [], msg="a hedged statement four minutes out is honest")
        far = manifest.clock_honesty_problems(
            "It is around eleven in the morning.",
            self.CLOCK_308, self.DATE_308)
        self.assertTrue(
            far, msg=("a hedge is not a licence: three hours out is not "
                      "'around': %r" % far))
        self.assertIn("a hedged", " ".join(far))

    def test_a_statement_just_inside_the_tolerance_passes(self):
        observed = manifest.clock_seconds_of_day(self.CLOCK_308)
        inside = observed + manifest.TIME_TOLERANCE - 60
        text = "The clock reads %02d:%02d." % (
            int(inside) // 3600, (int(inside) % 3600) // 60)
        self.assertEqual(
            manifest.clock_honesty_problems(
                text, self.CLOCK_308, self.DATE_308),
            [], msg=("the tolerance is for rounding a reading to the "
                     "nearest minute, not for inventing one"))

    def test_a_precise_time_on_an_unreadable_clock_is_refused(self):
        """A number nobody could see is not recorded as though they could.

        This is the one case where the gate cannot compare, and it refuses
        rather than passing: an exact time stated over a sidebar that read
        nothing is fabricated by definition.
        """
        for clock in (None, "", "   "):
            with self.subTest(clock=repr(clock)):
                problems = manifest.clock_honesty_problems(
                    "It is 08:15.", clock, None)
                self.assertEqual(len(problems), 1, msg=repr(problems))
                self.assertIn("not read at all", problems[0])
        coarse = manifest.clock_honesty_problems(
            "It is 08:15.", "Around dawn", None)
        self.assertEqual(len(coarse), 1)
        self.assertIn("coarse reading", coarse[0])
        self.assertIn("Around dawn", coarse[0])

    def test_a_hedged_time_on_an_unreadable_clock_is_allowed(self):
        """Without a watch a survivor still knows roughly where the sun
        is.

        display::time_string() falls back to a coarse phrase when the
        survivor carries no timepiece, and a hedged sentence is exactly
        the honest thing to write over one.
        """
        self.assertEqual(
            manifest.clock_honesty_problems(
                "It must be somewhere near eight in the morning.",
                None, None),
            [])
        self.assertEqual(
            manifest.clock_honesty_problems(
                "It is getting on for dusk, by the light.", None, None),
            [], msg="and a sentence stating no time at all is fine")

    def test_a_date_with_no_date_line_to_check_it_is_refused(self):
        problems = manifest.clock_honesty_problems(
            "It is the twentieth of May.", self.CLOCK_308, None)
        self.assertEqual(len(problems), 1, msg=repr(problems))
        self.assertIn("nothing to check it against", problems[0])

    def test_no_date_evidence_channel_is_not_an_unreadable_date(self):
        """The two are different in kind, and conflating them refuses
        every honest sentence that names the day.

        A date line that could not be read says the survivor could not see
        a date, so stating one is fabrication.  A CALLER that holds no
        date column at all -- the manifest schema has none -- says nothing
        whatever about what was observed, and adjudicating on that basis
        would be the gate inventing evidence of its own.
        """
        text = "It is the twentieth of May."
        self.assertTrue(
            manifest.clock_honesty_problems(text, self.CLOCK_308, None),
            msg="unreadable line, precise date: refused")
        self.assertEqual(
            manifest.clock_honesty_problems(text, self.CLOCK_308, None,
                                            check_dates=False),
            [], msg="no channel at all: left unadjudicated")
        self.assertTrue(
            manifest.clock_honesty_problems(
                "The clock reads 14:30.", self.CLOCK_308, None,
                check_dates=False),
            msg=("and the flag governs DATES only -- a false time is "
                 "still a false time"))

    def test_a_wrong_month_is_reported_separately_from_a_wrong_day(self):
        month = manifest.clock_honesty_problems(
            "It is the twentieth of June.", self.CLOCK_308, self.DATE_308)
        self.assertTrue(any("month" in one for one in month),
                        msg=repr(month))
        day = manifest.clock_honesty_problems(
            "It is the twenty-first of May.", self.CLOCK_308,
            self.DATE_308)
        self.assertTrue(any("day of the month" in one for one in day),
                        msg=repr(day))
        self.assertIn(
            "not approximate", " ".join(day),
            msg="a date has no tolerance at all, hedged or otherwise")

    def test_prose_that_states_nothing_is_never_a_problem(self):
        for text in ("I push the door open and step through.",
                     "Two cans and a bandage, and the road is empty.",
                     "", "   ", None):
            with self.subTest(text=repr(text)):
                self.assertEqual(
                    manifest.clock_honesty_problems(
                        text, self.CLOCK_308, self.DATE_308),
                    [], msg="the gate checks statements, not sentences")

    def test_agreement_with_either_observed_reading_is_honest(self):
        """Both readings were observed, and both are committed.

        Real row: after a five-minute wait the commentary reads "the five
        minutes did pass in the end and it is 08:05".  The reading its
        author had in front of them was 08:00:41 and the frame the caption
        is DISPLAYED OVER reads 08:05:28.  A sentence that agrees with what
        the viewer can see is not a fabrication, so the auditing callers
        accept either -- while the write-time gate, which has only the
        first, stays the stricter of the two.
        """
        text = "The five minutes did pass and it is 08:05."
        self.assertTrue(
            manifest.clock_honesty_problems(text, "08:00:41", None),
            msg=("at write time the key has not been sent, so only the "
                 "earlier reading exists and this is refused"))
        self.assertEqual(
            manifest.clock_honesty_problems(
                text, "08:00:41", None, also_clock="08:05:28"),
            [], msg="at audit time the captioned frame's reading counts")
        self.assertTrue(
            manifest.clock_honesty_problems(
                text, "08:00:41", None, also_clock="11:05:28"),
            msg=("and a statement matching NEITHER reading is still "
                 "refused: the union is of observed evidence, not of "
                 "everything"))

    def test_either_date_line_may_be_the_one_that_agrees(self):
        text = "It is the twenty-first of May."
        self.assertTrue(
            manifest.clock_honesty_problems(
                text, self.CLOCK_308, "Thursday, May 20"))
        self.assertEqual(
            manifest.clock_honesty_problems(
                text, self.CLOCK_308, "Thursday, May 20",
                also_date="Friday, May 21"),
            [], msg="the day rolled over between the two frames")

    def test_an_unreadable_primary_falls_through_to_the_alternate(self):
        self.assertEqual(
            manifest.clock_honesty_problems(
                "It is 08:05.", None, None, also_clock="08:05:28"),
            [], msg=("'cannot be compared' is about the evidence, not "
                     "about which argument carried it"))
        self.assertTrue(
            manifest.clock_honesty_problems(
                "It is 08:05.", None, None, also_clock="Around dawn"),
            msg="and two unreadable readings are still unreadable")

    def test_nothing_is_rewritten_by_the_check(self):
        text = self.FALSE_308
        manifest.clock_honesty_problems(text, self.CLOCK_308,
                                        self.DATE_308)
        self.assertEqual(
            text, self.FALSE_308,
            msg=("read-only: the survivor's words are refused, never "
                 "corrected on her behalf"))

    def test_the_label_is_what_the_message_calls_the_field(self):
        problems = manifest.clock_honesty_problems(
            "It is 20:15.", self.CLOCK_308, self.DATE_308,
            "row 308 commentary")
        self.assertTrue(problems)
        self.assertTrue(
            all(one.startswith("row 308 commentary")
                for one in problems),
            msg="so a report of a whole file says which row: %r"
                % problems)


class TestTheCommittedRecordHalfOfTheHonestyGate(ManifestFixture):
    """honesty_problems() holds the FILE to the same rule.

    session.py refuses a sentence before the key is sent; this audits a
    manifest that was assembled some other way -- an older session, a
    hand edit, a run whose writer gate was bypassed -- because every
    stage downstream turns this file into a timeline, a transcript and a
    caption track.
    """

    def rows_with(self, *pairs):
        """Return rows 1..n from (clock, commentary) pairs."""
        return [
            manifest.build_row(
                index, manifest.frame_file(index), FIXED_REAL_TS, clock,
                "press '5'", commentary)
            for index, (clock, commentary) in enumerate(pairs, start=1)]

    def test_a_row_is_judged_against_the_reading_before_it(self):
        """The reason for a key belongs to the moment BEFORE the key.

        `commentary` says why the survivor pressed it, so it is judged
        against the clock she had in front of her -- the PREVIOUS row's --
        while the row's own reading is what the action then consumed.
        Judging "five past eight, so I am going to lie down" against the
        clock a nine-hour sleep produced would refuse an honest sentence.
        """
        rows = self.rows_with(
            ("20:05:00", "I bank the fire and lie down."),
            ("05:12:00", "It is about eight in the evening; I sleep."))
        self.assertEqual(
            manifest.honesty_problems(rows), [],
            msg=("the second row states the time it was when she lay "
                 "down, which is the reading on the row before it"))

    def test_the_first_row_is_judged_against_its_own_reading(self):
        rows = self.rows_with(
            ("08:05:36", "It is about ten past eight in the morning."))
        self.assertEqual(
            manifest.honesty_problems(rows), [],
            msg="there is nothing before the first row to judge it by")
        wrong = self.rows_with(
            ("08:05:36", "The clock reads 14:30."))
        self.assertTrue(
            manifest.honesty_problems(wrong),
            msg="and it is still judged: %r" % wrong)

    def test_a_false_statement_anywhere_in_the_file_is_reported(self):
        rows = self.rows_with(
            ("08:05:36", "I stand up and look around."),
            ("08:05:40", "The clock reads 14:30, and the light is wrong."))
        problems = manifest.honesty_problems(rows)
        self.assertEqual(len(problems), 1, msg=repr(problems))
        self.assertIn("row 2 commentary", problems[0])

    def test_a_date_is_only_checked_when_a_date_line_is_supplied(self):
        """The manifest carries no date column; the sidecar does.

        So a date statement is adjudicated when the telemetry lines are
        passed in and left alone when they are not -- which is 'no
        evidence either way', not 'agrees' and not 'unreadable'.  A file
        audited on its own must not refuse every honest sentence that
        names the day, and it must not pass a false one when the evidence
        to catch it has been handed over.
        """
        rows = self.rows_with(
            ("08:05:36", "It is the twentieth of May."),
            ("08:05:40", "It is the twenty-eighth of May."))
        self.assertEqual(
            manifest.honesty_problems(rows), [],
            msg="no date channel, so no date claim is adjudicated")
        for empty in ({}, None, "not a mapping"):
            with self.subTest(dates=repr(empty)):
                self.assertEqual(
                    manifest.honesty_problems(rows, empty), [],
                    msg="and neither is an empty or unusable one")
        problems = manifest.honesty_problems(
            rows, {1: "Thursday, May 20", 2: "Thursday, May 20"})
        self.assertTrue(problems, msg="with the lines, the false one is "
                                      "caught: %r" % problems)
        self.assertIn("row 2 commentary", " ".join(problems))
        self.assertFalse(
            any("row 1 commentary" in one for one in problems),
            msg="and the true one is not: %r" % problems)

    def test_an_unreadable_clock_does_not_make_honest_prose_a_problem(self):
        rows = self.rows_with(
            (None, "I cannot see the sky from in here."),
            (None, "I keep moving while it is quiet."))
        self.assertEqual(manifest.honesty_problems(rows), [])

    def test_a_non_row_in_the_sequence_is_skipped_not_raised(self):
        self.assertEqual(
            manifest.honesty_problems(["not a row", 5, None]), [],
            msg=("the schema gate reports those; this one has nothing "
                 "to say about them"))

    def test_verify_manifest_applies_the_gate_to_the_file(self):
        row = self.row(frame=1, clock="08:05:36")
        row["commentary"] = ("It is ten past eight in the morning on the "
                             "twenty-eighth of May.")
        _write_lines(self.manifest, [json.dumps(row)])
        problems = manifest.verify_manifest(self.manifest,
                                            root=self.directory)
        self.assertTrue(
            any("08:10:00" in one for one in problems),
            msg=("the committed record is audited by the same gate that "
                 "refuses the row: %r" % problems))

    def test_a_truthful_record_reports_nothing(self):
        rows = self.rows_with(
            ("08:05:36", "It is about eight in the morning; I set out."),
            ("08:06:12", "Six minutes past eight, and the road is "
                         "clear."))
        _write_lines(self.manifest,
                     [json.dumps(one) for one in rows])
        self.assertEqual(
            manifest.verify_manifest(self.manifest,
                                     root=self.directory),
            [], msg="an honest record passes cleanly")


class TestAppendingIsAppendOnly(ManifestFixture):
    """The record grows by one line; it is never rewritten."""

    def test_one_append_writes_exactly_one_line(self):
        self.append(frame=1)
        self.assertEqual(len(self.lines()), 1)
        self.append(frame=2)
        lines = self.lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            json.loads(lines[0])["frame"], 1,
            msg=("the earlier row is still there and still first: the "
                 "file is opened for append and nothing else"))

    def test_an_append_returns_the_row_exactly_as_written(self):
        row = self.append(frame=3)
        self.assertEqual(
            row, json.loads(self.lines()[0]),
            msg=("the caller can log or assert on what was written "
                 "without re-reading the file"))

    def test_a_refused_row_writes_nothing_at_all(self):
        self.append(frame=1)
        before = _read_bytes(self.manifest)
        with self.assertRaises(manifest.ManifestError):
            manifest.append_row(
                self.manifest, 2, manifest.frame_file(2),
                FIXED_REAL_TS, "08:15:34", "", "no action text",
                root=self.directory)
        self.assertEqual(
            _read_bytes(self.manifest), before,
            msg=("there is no partial row: a bad field means nothing "
                 "reaches the file"))

    def test_the_two_entry_points_share_one_validation_path(self):
        row = self.row(frame=1)
        manifest.append_record(self.manifest, row, root=self.directory)
        self.assertEqual(json.loads(self.lines()[0]), row)
        row["ingame_clock"] = 5
        with self.assertRaises(manifest.ManifestError):
            manifest.append_record(self.manifest, row, root=self.directory)
        self.assertEqual(
            len(self.lines()), 1,
            msg="neither entry point is the lenient one")

    def test_a_repeated_index_is_recorded_rather_than_policed(self):
        # Deliberate: checking the sequence on every append would mean
        # reading the whole file each time, and a writer that behaved
        # differently depending on what was already on disk.  The
        # repeat is reported afterwards, loudly, by verify_manifest().
        self.append(frame=1)
        self.append(frame=1)
        self.assertEqual(len(self.lines()), 2)
        problems = manifest.verify_manifest(self.manifest, root=self.directory)
        self.assertTrue(
            any("no gap, no repeat" in problem for problem in problems),
            msg="the repeat is not lost, it is reported: %r" % problems)

    def test_a_manifest_anywhere_but_its_one_place_is_refused(self):
        # Containment alone would not be enough: EVERYTHING this
        # pipeline produces lives inside the tree, so a --manifest or a
        # PLAYTHROUGH_MANIFEST naming timeline.json, a frame or the
        # movie would be accepted and APPENDED TO -- JSON Lines rows
        # written onto the end of another artifact, every write
        # reporting success, and no manifest of the session existing at
        # all.  The record has exactly one place to live.  A parent
        # directory that does not exist is refused by the same rule
        # rather than by a check of its own, because the only path this
        # accepts is manifest.jsonl directly under a root that must
        # already be a directory.
        for name in (os.path.join("absent", "m.jsonl"),
                     "timeline.json",
                     os.path.join("frames", "frame_00001.png")):
            with self.subTest(name=name):
                with self.assertRaises(manifest.ManifestError) as bad:
                    manifest.append_row(
                        os.path.join(self.directory, name),
                        1, manifest.frame_file(1), FIXED_REAL_TS, None,
                        "a", "b",
                        root=self.directory)
                self.assertIn("and nothing else", str(bad.exception))

    def test_a_path_that_is_a_directory_is_refused(self):
        with self.assertRaises(manifest.ManifestError):
            manifest.append_row(
                self.frames, 1, manifest.frame_file(1), FIXED_REAL_TS,
                None, "a", "b",
                root=self.directory)

    def test_a_path_that_is_not_a_usable_string_is_refused(self):
        for path in (None, "", "   ", 17, "with\x00nul"):
            with self.subTest(path=repr(path)):
                with self.assertRaises(manifest.ManifestError):
                    manifest.append_row(
                        path, 1, manifest.frame_file(1),
                        FIXED_REAL_TS, None, "a", "b",
                        root=self.directory)

    def test_the_file_is_lf_terminated_whatever_the_platform(self):
        self.append_many(3)
        data = _read_bytes(self.manifest)
        self.assertNotIn(b"\r", data)
        self.assertTrue(data.endswith(b"\n"))
        self.assertFalse(data.endswith(b"\n\n"))

    def test_a_write_that_cannot_finish_leaves_no_partial_row(self):
        """A failed append restores the file, byte for byte.

        The realistic cause is a full disk part way through a long
        session -- one PNG per keystroke fills a volume long before a
        session ends -- and a half-written line is not JSON, which
        makes the WHOLE record unreadable and blocks timeline.py, the
        render, the captions and every gate that counts rows.  Simulated
        here by refusing the write itself, which is the same failure the
        row has to survive.
        """
        self.append_many(2)
        before = _read_bytes(self.manifest)
        real_write = os.write
        torn = {"count": 0}

        def short_then_fail(descriptor, payload):
            # Write a fragment, exactly as a filling disk does, then
            # refuse: the fragment must not be left behind.
            torn["count"] += 1
            real_write(descriptor, payload[:40])
            raise OSError(errno.ENOSPC, "No space left on device")

        with _patched(os, write=short_then_fail):
            with self.assertRaises(manifest.ManifestError) as bad:
                self.append(frame=3)
        self.assertEqual(torn["count"], 1, msg="the fragment was written")
        self.assertIn("left exactly as it was", str(bad.exception))
        self.assertEqual(
            _read_bytes(self.manifest), before,
            msg=("the fragment was truncated away: the file is exactly "
                 "what the last COMPLETE row left behind"))
        rows = manifest.read_rows(self.manifest, root=self.directory)
        self.assertEqual([row["frame"] for row in rows], [1, 2],
                         msg="the record is still readable")
        self.assertEqual(
            manifest.verify_manifest(
                self.manifest, frames_dir=self.frames,
                root=self.directory),
            [],
            msg="and still passes its own verification")

    def test_a_rollback_that_fails_reports_the_state_as_unknown(self):
        """A failed truncate says so, and claims nothing about the file.

        The two outcomes of a rollback are two different facts and are
        reported as two different messages: a message that asserts the
        file was restored exactly AND that it may end mid-row tells an
        operator both that nothing needs doing and that something does,
        and the one that gets acted on is whichever was read first.
        """
        self.append_many(2)
        real_write = os.write

        def fail_after_a_fragment(descriptor, payload):
            real_write(descriptor, payload[:40])
            raise OSError(errno.ENOSPC, "No space left on device")

        def refuse_truncate(descriptor, length):
            raise OSError(errno.EIO, "I/O error")

        with _patched(os, write=fail_after_a_fragment,
                      ftruncate=refuse_truncate):
            with self.assertRaises(manifest.ManifestError) as bad:
                self.append(frame=3)
        message = str(bad.exception)
        self.assertIn("ROLLBACK TO", message)
        self.assertIn("UNKNOWN", message)
        self.assertIn("INSPECT IT", message)
        self.assertNotIn(
            "left exactly as it was", message,
            msg=("a rollback that failed must not be reported as one "
                 "that succeeded: %r" % message))
        # The fragment really is still on disk, which is precisely why
        # the message must not promise otherwise.
        after = _read_bytes(self.manifest)
        self.assertFalse(
            after.endswith(b"\n"),
            msg=("the truncate was refused, so the file really does "
                 "end mid-row: %r" % after[-20:]))
        problems = manifest.verify_manifest(
            self.manifest, root=self.directory)
        self.assertTrue(
            any("not JSON" in problem for problem in problems),
            msg=("verify names the line to repair, as the message "
                 "instructs: %r" % problems))

    def test_a_lock_that_cannot_be_taken_fails_the_append(self):
        """No exclusion, no append.  FAIL CLOSED.

        The append is measure-the-end, write, and truncate back to that
        offset on failure.  That is only safe while no other writer can
        move the end of the file, so a lock this module cannot take
        stops the row instead of being warned about: a stale offset
        would let a rollback delete a row ANOTHER writer had already
        been told was stored.
        """
        self.append_many(2)
        before = _read_bytes(self.manifest)
        attempts = {"count": 0}

        def refuse_lock(descriptor, operation):
            attempts["count"] += 1
            raise OSError(errno.ENOLCK, "No locks available")

        with _patched(manifest.fcntl, flock=refuse_lock):
            with self.assertRaises(manifest.ManifestError) as bad:
                self.append(frame=3)
        self.assertEqual(attempts["count"], 1)
        message = str(bad.exception)
        self.assertIn("exclusive lock", message)
        # The CONTRACT is that the refusal says nothing was written, not
        # that it says so in any one capitalisation.
        self.assertIn("nothing was written", message.lower())
        self.assertEqual(
            _read_bytes(self.manifest), before,
            msg="not one byte reached the record")
        self.assertEqual(
            manifest.verify_manifest(
                self.manifest, frames_dir=self.frames,
                root=self.directory),
            [],
            msg="and the record still passes its own verification")

    def test_appending_onto_an_unfinished_row_is_refused(self):
        """A tear no rollback could reach is refused, not fused.

        A process killed outright mid-write -- SIGKILL, a power loss --
        leaves a row with no newline and no chance to undo it.  Appending
        then joins two half-rows into one line that is neither, turning a
        recoverable tear into a corrupt record.
        """
        self.append_many(2)
        with open(self.manifest, "ab") as handle:
            handle.write(b'{"frame": 3, "file": "playthrough/frames/f')
        torn = _read_bytes(self.manifest)
        with self.assertRaises(manifest.ManifestError) as bad:
            self.append(frame=4)
        self.assertIn("ends mid-row", str(bad.exception))
        self.assertEqual(
            _read_bytes(self.manifest), torn,
            msg="the refusal changes nothing, including the tear")
        problems = manifest.verify_manifest(
            self.manifest, root=self.directory)
        self.assertTrue(
            any("not JSON" in problem for problem in problems),
            msg=("verify names the line to repair rather than the "
                 "writer hiding it: %r" % problems))


class TestTheAppendTargetIsCheckableInAdvance(ManifestFixture):
    """The writer's rule can be applied before anything is written.

    session.py delivers a keystroke it cannot take back and only then
    appends the row.  Every condition this module can decide from the
    PATH -- the name, the containment, the symlink-freedom, the
    existence of the directory -- must therefore be available to it at
    open, and it must be the SAME rule, not a kinder restatement of it:
    a path that passes the early check and fails the append would be
    the ordering defect all over again.
    """

    def test_the_record_s_own_path_is_accepted(self):
        self.assertEqual(
            manifest.assert_appendable(self.manifest, self.directory),
            os.path.realpath(self.manifest))

    def test_an_absent_record_is_accepted_and_not_created(self):
        self.assertFalse(os.path.exists(self.manifest))
        manifest.assert_appendable(self.manifest, self.directory)
        self.assertFalse(
            os.path.exists(self.manifest),
            msg=("checking must not manufacture an empty manifest: an "
                 "empty file is a problem every reader reports"))

    def test_another_name_inside_the_tree_is_refused(self):
        for name in ("other.jsonl", "timeline.json",
                     "manifest.jsonl.bak", "cata-play.mp4"):
            with self.subTest(name=name):
                with self.assertRaises(manifest.ManifestError) as bad:
                    manifest.assert_appendable(
                        os.path.join(self.directory, name),
                        self.directory)
                self.assertIn("and nothing else", str(bad.exception))

    def test_a_subdirectory_of_the_tree_is_refused(self):
        build = os.path.join(self.directory, "build")
        os.mkdir(build)
        with self.assertRaises(manifest.ManifestError):
            manifest.assert_appendable(
                os.path.join(build, "manifest.jsonl"), self.directory)

    def test_a_path_outside_the_tree_is_refused(self):
        with self.assertRaises(manifest.ManifestError) as bad:
            manifest.assert_appendable(
                "/tmp/manifest.jsonl", self.directory)
        self.assertIn("must stay inside", str(bad.exception))

    def test_the_early_check_and_the_append_agree(self):
        # The property that matters: whatever this accepts, append_row
        # accepts, and whatever it refuses, append_row refuses.  Both
        # go through the same private validator, and this is the test
        # that would fail if a second copy of the rule appeared.
        self.write_frames([1])
        accepted = os.path.join(self.directory, "manifest.jsonl")
        refused = os.path.join(self.directory, "not-the-record.jsonl")
        manifest.assert_appendable(accepted, self.directory)
        self.append(frame=1)
        self.assertEqual(
            manifest.count_rows(self.manifest, root=self.directory), 1)
        for call in (
            lambda: manifest.assert_appendable(refused, self.directory),
            lambda: manifest.append_row(
                refused, 2, manifest.frame_file(2), FIXED_REAL_TS,
                None, "press 'k'", "North.", root=self.directory),
        ):
            with self.assertRaises(manifest.ManifestError):
                call()
        self.assertFalse(os.path.exists(refused))


class TestReadingTheRecord(ManifestFixture):
    """Reading is read-only, and says where a bad line is."""

    def test_rows_come_back_in_file_order(self):
        self.append_many(3)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        self.assertEqual([row["frame"] for row in rows], [1, 2, 3])
        self.assertEqual(
            manifest.count_rows(self.manifest, root=self.directory), 3)

    def test_reading_does_not_alter_the_file(self):
        self.append_many(2)
        before = _read_bytes(self.manifest)
        manifest.read_rows(self.manifest, root=self.directory)
        manifest.count_rows(self.manifest, root=self.directory)
        manifest.last_recorded_frame(self.manifest, root=self.directory)
        manifest.verify_manifest(self.manifest, root=self.directory)
        self.assertEqual(_read_bytes(self.manifest), before)

    def test_a_missing_manifest_is_reported_when_read(self):
        with self.assertRaises(manifest.ManifestError) as bad:
            manifest.read_rows(self.manifest, root=self.directory)
        self.assertIn("no manifest at", str(bad.exception))

    def test_a_bad_line_is_reported_with_its_number(self):
        cases = (
            (["{not json"], "is not JSON"),
            (['["a"]'], "not a JSON object"),
            (["", "{}"], "is blank"),
        )
        for lines, expected in cases:
            with self.subTest(lines=lines):
                _write_lines(self.manifest, lines)
                with self.assertRaises(manifest.ManifestError) as bad:
                    manifest.read_rows(self.manifest, root=self.directory)
                message = str(bad.exception)
                self.assertIn(expected, message)
                self.assertIn("line 1", message)

    def test_a_crlf_line_is_reported(self):
        with open(self.manifest, "w", encoding="utf-8",
                  newline="") as handle:
            handle.write(json.dumps(self.row()) + "\r\n")
        with self.assertRaises(manifest.ManifestError) as bad:
            manifest.read_rows(self.manifest, root=self.directory)
        self.assertIn("CRLF", str(bad.exception))

    def test_the_last_index_is_an_observation_not_a_generator(self):
        self.assertEqual(
            manifest.last_recorded_frame(
                self.manifest, root=self.directory), 0,
            msg=("a manifest that does not exist yet answers 0, which "
                 "is how a fresh session is told from a resumed one"))
        self.append_many(3)
        self.assertEqual(
            manifest.last_recorded_frame(
                self.manifest, root=self.directory), 3)
        self.assertEqual(
            manifest.last_recorded_frame(
                self.manifest, root=self.directory), 3,
            msg="asking twice does not increment anything")

    def test_an_empty_manifest_reports_no_last_index(self):
        _write_lines(self.manifest, [])
        self.assertEqual(
            manifest.last_recorded_frame(
                self.manifest, root=self.directory), 0)

    def test_a_non_integer_last_index_is_refused(self):
        _write_lines(self.manifest, [json.dumps(
            {"frame": "3", "file": manifest.frame_file(3),
             "real_ts": FIXED_REAL_TS, "ingame_clock": None,
             "action": "a", "commentary": "b"})])
        with self.assertRaises(manifest.ManifestError):
            manifest.last_recorded_frame(self.manifest, root=self.directory)


class TestVerifyingTheRecord(ManifestFixture):
    """verify_manifest() reports; it never repairs."""

    def test_a_good_manifest_reports_nothing(self):
        self.append_many(3)
        self.assertEqual(
            manifest.verify_manifest(self.manifest,
                                     root=self.directory), [])

    def test_an_absent_manifest_is_reported_not_raised(self):
        problems = manifest.verify_manifest(self.manifest, root=self.directory)
        self.assertEqual(len(problems), 1)
        self.assertIn("no manifest at", problems[0])

    def test_an_empty_manifest_is_reported(self):
        _write_lines(self.manifest, [])
        self.assertTrue(
            any("is empty" in problem
                for problem in manifest.verify_manifest(
                    self.manifest,
                    root=self.directory)))

    def test_a_gap_a_repeat_and_a_reordering_are_all_reported(self):
        cases = (
            ([1, 3], "a gap in the sequence"),
            ([1, 1], "a repeated index"),
            ([2, 1], "a reordering"),
        )
        for indexes, why in cases:
            with self.subTest(indexes=indexes):
                _write_lines(self.manifest, [
                    json.dumps(self.row(frame=index))
                    for index in indexes])
                problems = manifest.verify_manifest(
                    self.manifest, root=self.directory)
                self.assertTrue(
                    any("no gap, no repeat and no reordering" in problem
                        for problem in problems),
                    msg="%s must be reported: %r" % (why, problems))

    def test_a_row_with_the_wrong_keys_is_reported(self):
        _write_lines(self.manifest, [json.dumps(
            {"file": manifest.frame_file(1), "frame": 1,
             "real_ts": FIXED_REAL_TS, "ingame_clock": None,
             "action": "a", "commentary": "b"})])
        problems = manifest.verify_manifest(self.manifest, root=self.directory)
        self.assertTrue(
            any("expected exactly" in problem for problem in problems),
            msg=("the ORDER on disk is part of the schema: %r"
                 % problems))

    def test_a_row_whose_file_is_wrong_is_reported(self):
        row = self.row(frame=1)
        row["file"] = manifest.frame_file(2)
        _write_lines(self.manifest, [json.dumps(row)])
        self.assertTrue(
            any("expected" in problem
                for problem in manifest.verify_manifest(
                    self.manifest,
                    root=self.directory)))

    def test_a_row_with_an_empty_narrative_field_is_reported(self):
        for field in ("real_ts", "action", "commentary"):
            with self.subTest(field=field):
                row = self.row(frame=1)
                row[field] = ""
                _write_lines(self.manifest, [json.dumps(row)])
                self.assertTrue(
                    any(field in problem
                        for problem in manifest.verify_manifest(
                            self.manifest,
                            root=self.directory)))

    def test_a_row_with_a_malformed_timestamp_is_reported(self):
        row = self.row(frame=1)
        row["real_ts"] = "yesterday"
        _write_lines(self.manifest, [json.dumps(row)])
        self.assertTrue(
            any("real_ts is malformed" in problem
                for problem in manifest.verify_manifest(
                    self.manifest,
                    root=self.directory)))

    def test_a_clock_that_is_neither_a_reading_nor_null_is_reported(self):
        for value in (5, "", []):
            with self.subTest(value=value):
                row = self.row(frame=1)
                row["ingame_clock"] = value
                _write_lines(self.manifest, [json.dumps(row)])
                self.assertTrue(
                    any("neither a reading nor null" in problem
                        for problem in manifest.verify_manifest(
                            self.manifest,
                            root=self.directory)))

    def test_a_null_clock_is_not_a_problem(self):
        row = self.row(frame=1, clock=None)
        _write_lines(self.manifest, [json.dumps(row)])
        self.assertEqual(
            manifest.verify_manifest(self.manifest, root=self.directory), [],
            msg=("an unreadable clock is an honest outcome, so it must "
                 "not fail the gate"))

    def test_a_frame_index_out_of_range_is_reported(self):
        row = self.row(frame=1)
        row["frame"] = 0
        _write_lines(self.manifest, [json.dumps(row)])
        self.assertTrue(
            any("out of range" in problem
                for problem in manifest.verify_manifest(
                    self.manifest,
                    root=self.directory)))

    def test_a_non_integer_frame_index_is_reported(self):
        row = self.row(frame=1)
        row["frame"] = "1"
        _write_lines(self.manifest, [json.dumps(row)])
        self.assertTrue(
            any("not an integer" in problem
                for problem in manifest.verify_manifest(
                    self.manifest,
                    root=self.directory)))

    def test_a_missing_trailing_newline_is_reported(self):
        with open(self.manifest, "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(json.dumps(self.row()))
        self.assertTrue(
            any("does not end with a newline" in problem
                for problem in manifest.verify_manifest(
                    self.manifest,
                    root=self.directory)))

    def test_a_trailing_blank_line_is_reported(self):
        # The reader complains first, by line number, which is the more
        # useful of the two answers -- so the shape check behind it is
        # never reached for this file.  What matters is that the blank
        # line is REPORTED rather than skipped, because a skipped blank
        # line would put the row count one below the frame count.
        with open(self.manifest, "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(json.dumps(self.row()) + "\n\n")
        problems = manifest.verify_manifest(self.manifest, root=self.directory)
        self.assertTrue(
            any("blank" in problem for problem in problems),
            msg=repr(problems))
        self.assertTrue(
            any("line 2" in problem for problem in problems),
            msg="and the offending line is named: %r" % problems)

    def test_the_capture_for_every_row_may_be_required(self):
        self.append_many(2)
        self.write_frames([1])
        self.assertEqual(
            manifest.verify_manifest(self.manifest,
                                     frames_dir=self.frames,
                                     root=self.directory),
            [],
            msg=("the frames are only checked when the caller asks, "
                 "because the manifest is also read mid-session"))
        problems = manifest.verify_manifest(
            self.manifest, frames_dir=self.frames,
            require_frames=True,
            root=self.directory)
        self.assertEqual(len(problems), 1)
        self.assertIn("no capture on disk for frame 2", problems[0])

    def test_every_capture_present_satisfies_the_identity(self):
        self.append_many(3)
        self.write_frames([1, 2, 3])
        self.assertEqual(
            manifest.verify_manifest(self.manifest,
                                     frames_dir=self.frames,
                                     require_frames=True,
                                     root=self.directory),
            [],
            msg=("one keystroke, one capture, one row -- the identity "
                 "the acceptance gate asserts"))

    def test_a_missing_frames_directory_is_refused(self):
        self.append_many(1)
        with self.assertRaises(manifest.ManifestError):
            manifest.verify_manifest(
                self.manifest,
                frames_dir=os.path.join(self.directory, "absent"),
                require_frames=True,
                root=self.directory)

    def test_a_malformed_manifest_reports_the_line_and_stops(self):
        _write_lines(self.manifest, ["{not json"])
        problems = manifest.verify_manifest(self.manifest, root=self.directory)
        self.assertEqual(len(problems), 1)
        self.assertIn("is not JSON", problems[0])

    def test_out_of_character_commentary_is_a_problem_on_disk_too(self):
        """The reader holds the FILE to the rule the writer enforces.

        A manifest assembled some other way -- an older session, a hand
        edit, a run whose writer gate was bypassed -- is still audited,
        because every stage downstream reads this file and turns it into
        a transcript and a caption track.
        """
        row = self.row(frame=1)
        row["commentary"] = "I check the ocr output."
        _write_lines(self.manifest, [json.dumps(row)])
        problems = manifest.verify_manifest(self.manifest,
                                            root=self.directory)
        self.assertTrue(
            any("survivor's own voice" in problem
                for problem in problems),
            msg=("an out-of-character row already on disk is REPORTED, "
                 "not warned about: %r" % problems))
        self.assertTrue(
            any("row 1 commentary" in problem for problem in problems),
            msg="and the report says which row: %r" % problems)

    def test_honest_commentary_still_passes_the_voice_gate_on_disk(self):
        """The precise patterns matter most where prose is real.

        The survivor is a mechanical engineer and she walks through split
        door frames; neither sentence may fail the gate, or the record
        could not be written in her own words at all.
        """
        for text in ("She was a mechanical engineer before this.",
                     "The frame of the door is split at the hinge."):
            with self.subTest(text=text):
                row = self.row(frame=1)
                row["commentary"] = text
                _write_lines(self.manifest, [json.dumps(row)])
                self.assertEqual(
                    manifest.verify_manifest(self.manifest,
                                             root=self.directory), [],
                    msg="honest prose passes the gate unchanged")


class TestTheCommandLine(ManifestFixture):
    """Read-only by construction: there is no append subcommand."""

    def run_main(self, *argv):
        """Call main(argv) and return (status, stdout, stderr)."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            status = manifest.main(list(argv), root=self.directory)
        return status, out.getvalue(), err.getvalue()

    def test_count_prints_the_number_of_rows(self):
        self.append_many(3)
        status, out, _ = self.run_main("--manifest", self.manifest,
                                       "count")
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), "3")

    def test_verify_reports_success_with_the_row_count(self):
        self.append_many(2)
        status, out, _ = self.run_main("--manifest", self.manifest,
                                       "verify")
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), "manifest ok: 2 row(s)")

    def test_verify_exits_non_zero_and_lists_every_problem(self):
        _write_lines(self.manifest, [
            json.dumps(self.row(frame=1)),
            json.dumps(self.row(frame=3)),
        ])
        status, out, err = self.run_main(
            "--manifest", self.manifest, "verify")
        self.assertEqual(
            status, 1,
            msg="a pipeline stage reads the status, so it must be right")
        self.assertEqual(out, "", msg="stdout stays quiet on failure")
        self.assertIn("no gap, no repeat", err)
        self.assertIn("problem(s) found", err)

    def test_verify_can_require_the_captures(self):
        self.append_many(2)
        self.write_frames([1])
        status, _, err = self.run_main(
            "--manifest", self.manifest, "verify",
            "--frames-dir", self.frames, "--require-frames")
        self.assertEqual(status, 1)
        self.assertIn("no capture on disk for frame 2", err)

    def test_a_missing_manifest_exits_non_zero(self):
        status, _, err = self.run_main("--manifest", self.manifest,
                                       "count")
        self.assertEqual(status, 1)
        self.assertIn("no manifest at", err)

    def test_a_subcommand_is_required(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                manifest.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_there_is_no_way_to_append_from_the_command_line(self):
        parser = manifest._build_parser()
        actions = {action.dest for action in parser._actions}
        self.assertNotIn(
            "append", actions,
            msg=("appending is available to importers only, so that "
                 "session.py keeps sole ownership of the frame "
                 "counter"))
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                manifest.main(["append"])

    def test_the_default_manifest_follows_the_environment(self):
        with _environment(PLAYTHROUGH_MANIFEST=self.manifest):
            self.assertEqual(
                manifest.default_manifest_path(), self.manifest,
                msg=("env.sh is the single definition of the artifact "
                     "layout, so its export wins"))
        with _environment(PLAYTHROUGH_MANIFEST=None):
            self.assertTrue(
                manifest.default_manifest_path().endswith(
                    os.path.join("playthrough", "manifest.jsonl")),
                msg=("and with nothing sourced the path is derived from "
                     "the module's own location, so an ad-hoc import "
                     "still works"))

    def test_the_default_frames_directory_follows_the_environment(self):
        with _environment(PLAYTHROUGH_FRAMES_DIR=self.frames):
            self.assertEqual(
                manifest.default_frames_dir(), self.frames)
        with _environment(PLAYTHROUGH_FRAMES_DIR=None):
            self.assertTrue(
                manifest.default_frames_dir().endswith(
                    os.path.join("playthrough", "frames")))


class TestTheCapturePayloadContract(ManifestFixture):
    """The seam between capture.sh and this writer, exercised.

    capture.sh emits KEY=value lines and session.py turns them into one
    manifest row.  The three fields that cross that boundary are the
    ones that can silently disagree -- the frame filename, the capture
    instant and the clock reading -- so the payload's own values are fed
    through the writer here rather than being assumed compatible.
    """

    # A real capture.sh payload, keys and forms as documented in the
    # header of that file.
    PAYLOAD = {
        "FRAME_INDEX": "7",
        "FRAME_NAME": "frame_00007.png",
        "FRAME_FILE": "playthrough/frames/frame_00007.png",
        "REAL_TS": "2026-05-14T09:12:03.481Z",
        "CLOCK_STATUS": "read",
        "CLOCK": "08:15:33",
        "TIME_PHRASE": "",
        "DATE": "Thursday, Mar 8",
    }

    def row_from_payload(self, payload):
        """Build a row the way session.py builds one from a capture."""
        clock = payload["CLOCK"] or payload["TIME_PHRASE"] or None
        return manifest.build_row(
            int(payload["FRAME_INDEX"]),
            payload["FRAME_FILE"],
            payload["REAL_TS"],
            clock,
            "press '5'",
            "I hold still and let the street settle.")

    def test_a_read_payload_becomes_a_row_unchanged(self):
        row = self.row_from_payload(dict(self.PAYLOAD))
        self.assertEqual(row["frame"], 7)
        self.assertEqual(row["file"], self.PAYLOAD["FRAME_FILE"])
        self.assertEqual(
            row["real_ts"], self.PAYLOAD["REAL_TS"],
            msg=("the shutter's own stamp passes through byte for "
                 "byte, so the row records when the capture happened "
                 "rather than when the row was written"))
        self.assertEqual(row["ingame_clock"], self.PAYLOAD["CLOCK"])

    def test_the_payload_s_filename_is_the_writer_s_filename(self):
        self.assertEqual(
            self.PAYLOAD["FRAME_FILE"],
            manifest.frame_file(int(self.PAYLOAD["FRAME_INDEX"])),
            msg=("capture.sh and manifest.py build the name from one "
                 "format, so the count identity cannot be broken by a "
                 "spelling difference"))
        self.assertEqual(
            self.PAYLOAD["FRAME_NAME"],
            manifest.FRAME_NAME_FORMAT % 7)

    def test_an_unreadable_payload_becomes_a_null_clock(self):
        payload = dict(self.PAYLOAD,
                       CLOCK_STATUS="unreadable", CLOCK="")
        row = self.row_from_payload(payload)
        self.assertIsNone(
            row["ingame_clock"],
            msg=("an empty CLOCK is an honest absence and is recorded "
                 "as null, never as 00:00:00 and never as the previous "
                 "frame's reading"))

    def test_a_watchless_payload_records_the_phrase_verbatim(self):
        payload = dict(self.PAYLOAD, CLOCK_STATUS="unreadable",
                       CLOCK="", TIME_PHRASE=COARSE_PHRASE)
        row = self.row_from_payload(payload)
        self.assertEqual(row["ingame_clock"], COARSE_PHRASE)
        self.assertEqual(
            manifest.classify_ingame_clock(row["ingame_clock"]),
            manifest.CLOCK_COARSE,
            msg=("the phrase a survivor without a watch sees is a real "
                 "reading, classified as coarse rather than discarded"))

    def test_the_payload_s_date_line_has_no_column_here(self):
        # The schema is six fields.  The sidebar date lives in the
        # telemetry sidecar, which is why capture.sh emits it on stdout
        # and appends it there instead.
        with self.assertRaises(manifest.ManifestError):
            manifest.encode_row(
                dict(self.row_from_payload(dict(self.PAYLOAD)),
                     date=self.PAYLOAD["DATE"]))


class TestTheRecordHasNoWriterButAppend(ManifestFixture):
    """Code review finding: 26 captured rows were rewritten.

    This module once carried a narrow rewrite facility so that the
    observed-effect marker could be added to rows captured before the
    live guard existed.  The review found the facility itself to be the
    defect: a captured row is evidence, the correction belongs in
    playthrough/TECHNICAL_NOTES.md, and the file's own contract says so
    in as many words.  Every rewrite entry point was removed, and these
    tests hold that removal against both the API and the source, because
    a re-introduction would be a one-function change.
    """

    RETIRED = (
        "extend_action",
        "extend_actions",
        "plan_action_extensions",
        "publish_action_extensions",
        "ActionExtensionPlan",
        "open_staging",
        "_rewrite_rows",
        "STAGING_NAME",
    )

    def test_no_rewrite_entry_point_is_exposed(self):
        for name in self.RETIRED:
            self.assertFalse(
                hasattr(manifest, name),
                "%s is a rewrite surface this module must not have" % name)

    def test_the_source_opens_nothing_for_writing(self):
        """The append path uses os.open with O_APPEND, never "w"."""
        pattern = re.compile(
            r"""open\([^)]*['"]w|\.truncate\(|\.seek\(""")
        with open(manifest.__file__, "r", encoding="utf-8") as handle:
            offenders = [
                (number, line.rstrip())
                for number, line in enumerate(handle, 1)
                if pattern.search(line)]
        self.assertEqual(offenders, [])

    def test_the_only_write_flags_are_append_flags(self):
        with open(manifest.__file__, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("os.O_APPEND", source)
        self.assertNotIn("os.O_TRUNC", source)

    def test_reading_hands_back_copies_the_caller_cannot_write_through(
            self):
        self.append_many(2)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        rows[0]["action"] = "press 'q' -- something else entirely"
        again = manifest.read_rows(self.manifest, root=self.directory)
        self.assertEqual(again[0]["action"], "press '5'")

    def test_a_second_append_leaves_the_first_row_byte_identical(self):
        self.append(frame=1)
        first = self.lines()[0]
        self.append(frame=2)
        self.assertEqual(self.lines()[0], first)


class TestStagingSiblingsCannotAccumulate(ManifestFixture):
    """Performance QA finding: hard-kill leftovers in a tracked tree.

    The retired rewrite wrote a sibling and renamed it; a SIGKILL left
    the sibling behind, and .gitignore re-includes everything under
    playthrough/ with its terminal negation, so a leftover is an
    untracked file `git add -A playthrough/` would commit.  Unique
    temporary names let them accumulate without bound and nothing swept
    them.

    Nothing writes one any more, which makes the sweep the ONLY thing
    that can still clear a survivor -- so it is kept, and these tests
    exercise it directly rather than through a writer that no longer
    exists.
    """

    def staging(self, name=".manifest-staging.jsonl"):
        """Return a path in the record's directory."""
        return os.path.join(self.directory, name)

    def sweep(self):
        """Sweep the record's directory, returning (removed, stderr)."""
        return self.capture_stderr(
            manifest.sweep_staging, self.directory,
            manifest.STAGING_PREFIX, manifest.STAGING_SUFFIX,
            manifest.STAGING_OF)

    def test_the_staging_prefix_is_private_and_dot_leading(self):
        self.assertTrue(manifest.STAGING_PREFIX.startswith("."))
        self.assertEqual(manifest.STAGING_SUFFIX, ".jsonl")

    def test_leftovers_from_interrupted_rewrites_are_swept(self):
        self.append_many(2)
        for name in (".manifest-staging.jsonl",
                     ".manifest-abc123.jsonl",
                     ".manifest-def456.jsonl"):
            _write_lines(self.staging(name), ['{"frame": 1}'])
        self.assertEqual(
            len(manifest.staging_candidates(
                self.directory, manifest.STAGING_PREFIX,
                manifest.STAGING_SUFFIX)), 3)
        removed, noise = self.sweep()
        self.assertEqual(len(removed), 3)
        self.assertIn("interrupted rewrite", noise)
        self.assertEqual(
            manifest.staging_candidates(
                self.directory, manifest.STAGING_PREFIX,
                manifest.STAGING_SUFFIX),
            ())
        self.assertEqual(
            len(manifest.read_rows(self.manifest, root=self.directory)),
            2)

    def test_a_name_that_is_not_a_staging_name_is_left_alone(self):
        keep = os.path.join(self.directory, "manifest.jsonl.bak")
        other = os.path.join(self.directory, ".manifest-.jsonl")
        for path in (keep, other):
            _write_lines(path, ["{}"])
        manifest.sweep_staging(
            self.directory, manifest.STAGING_PREFIX,
            manifest.STAGING_SUFFIX, manifest.STAGING_OF)
        self.assertTrue(os.path.exists(keep))
        self.assertTrue(os.path.exists(other))

    def test_a_symlink_at_a_staging_name_is_left_not_followed(self):
        self.append_many(2)
        before = _read_bytes(self.manifest)
        elsewhere = os.path.join(self.directory, "elsewhere.jsonl")
        _write_lines(elsewhere, ["{}"])
        os.symlink(elsewhere, self.staging())
        removed, noise = self.sweep()
        self.assertEqual(removed, ())
        self.assertIn("not a regular file", noise)
        self.assertTrue(os.path.islink(self.staging()))
        self.assertEqual(_read_bytes(self.manifest), before)
        self.assertEqual(_read_bytes(elsewhere), b"{}\n")

    def test_a_directory_at_a_staging_name_is_left_alone(self):
        self.append_many(2)
        before = _read_bytes(self.manifest)
        os.mkdir(self.staging())
        removed, noise = self.sweep()
        self.assertEqual(removed, ())
        self.assertIn("not a regular file", noise)
        self.assertTrue(os.path.isdir(self.staging()))
        self.assertEqual(_read_bytes(self.manifest), before)

    def test_a_leftover_owned_by_another_account_is_left_alone(self):
        if os.getuid() != 0:  # pragma: no cover - depends on the host
            self.skipTest("changing a file's owner requires privilege")
        self.append_many(2)
        before = _read_bytes(self.manifest)
        _write_lines(self.staging(), ["{}"])
        os.chown(self.staging(), 12345, -1)
        removed, noise = self.sweep()
        self.assertEqual(removed, ())
        self.assertIn("owned by uid 12345", noise)
        self.assertTrue(os.path.exists(self.staging()))
        self.assertEqual(_read_bytes(self.manifest), before)


class TestTheAmendmentLedger(ManifestFixture):
    """A correction is an append to a second file, never an edit.

    THE DEFECT THIS SUITE EXISTS FOR.  A security review found that a
    row of the committed record had been rewritten after capture -- a
    narration corrected in place by a function built for the purpose --
    and named the consequence precisely: once evidence can be rewritten,
    every artifact derived from it is deniable.  The function is gone,
    and this ledger is what replaced it: the manifest keeps the bytes
    the session wrote, and each later correction is one append-only row
    bound to the sha256 of the line it concerns.

    So the assertions below hold three separate things.  That the
    WRITER validates an amendment as strictly as a row (an amendable
    field, a changed value, a stated basis and reason, a real digest).
    That the RESOLVER fails CLOSED -- a digest that has moved, a
    `recorded` value that no longer matches, a frame the rows do not
    carry and a doubly-amended narration are all refusals, never skips.
    And that the record itself is never touched on any path.
    """

    def ledger_path(self):
        """The one path the ledger may live at in this tree."""
        return os.path.join(self.directory, manifest.AMENDMENTS_NAME)

    MARKER = "nothing on the screen changed"

    def amend(self, frame=2, field="action",
              recorded=None, amended=None, number=1, digest=None,
              basis="the two captures were compared and are identical.",
              reason="the note claims an effect the capture contradicts."):
        """Append one amendment against this tree's manifest."""
        rows = {row["frame"]: row for row in
                manifest.read_rows(self.manifest, root=self.directory)}
        digests = manifest.row_digests(self.manifest,
                                       root=self.directory)
        if recorded is None:
            recorded = rows[frame][field]
        if amended is None:
            # Joined exactly as session.annotate_action() joins it: the
            # marker becomes the note when the action has none.
            joiner = (manifest.ACTION_SEPARATOR
                      if manifest.ACTION_SEPARATOR not in recorded
                      else "; ")
            amended = recorded + joiner + self.MARKER
        return manifest.append_amendment(
            self.ledger_path(), number, FIXED_REAL_TS, frame, field,
            digests[frame] if digest is None else digest,
            recorded, amended, basis, reason, root=self.directory)

    def ledger(self):
        """Every amendment written so far."""
        return manifest.read_amendments(self.ledger_path(),
                                        self.directory)

    def test_the_declared_schema_is_the_nine_fields(self):
        self.assertEqual(
            manifest.AMENDMENT_FIELDS,
            ("amendment", "amended_ts", "frame", "field",
             "source_sha256", "recorded", "amended", "basis", "reason"))
        self.assertEqual(manifest.AMENDABLE_FIELDS,
                         ("action", "commentary"))

    def test_an_amendment_is_appended_and_the_record_is_not_touched(self):
        self.append_many(2)
        before = _read_bytes(self.manifest)
        row = self.amend()
        self.assertEqual(_read_bytes(self.manifest), before)
        self.assertEqual(list(row), list(manifest.AMENDMENT_FIELDS))
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(
            manifest.verify_amendments(
                self.ledger_path(), self.manifest, root=self.directory),
            [])

    def test_the_ledger_is_append_only(self):
        self.append_many(3)
        self.amend(frame=2, number=1)
        first = _read_bytes(self.ledger_path())
        self.amend(frame=3, number=2)
        grown = _read_bytes(self.ledger_path())
        self.assertTrue(grown.startswith(first))
        self.assertEqual(len(self.ledger()), 2)

    def test_only_the_two_narrations_may_be_amended(self):
        self.append_many(2)
        for field in ("frame", "file", "real_ts", "ingame_clock",
                      "made up"):
            with self.subTest(field=field):
                with self.assertRaises(manifest.ManifestError):
                    self.amend(field=field, recorded="a", amended="b")
        self.assertEqual(self.ledger(), ())

    def test_an_amendment_that_changes_nothing_is_refused(self):
        self.append_many(2)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        with self.assertRaises(manifest.ManifestError):
            self.amend(amended=rows[1]["action"])
        self.assertEqual(self.ledger(), ())

    def test_a_basis_and_a_reason_are_mandatory(self):
        self.append_many(2)
        for missing in ("basis", "reason"):
            with self.subTest(field=missing):
                with self.assertRaises(manifest.ManifestError):
                    self.amend(**{missing: "   "})
        self.assertEqual(self.ledger(), ())

    def test_a_digest_that_is_not_a_sha256_is_refused(self):
        self.append_many(2)
        for value in ("", "not-a-digest", "AB" * 32, "ab" * 31):
            with self.subTest(digest=value):
                with self.assertRaises(manifest.ManifestError):
                    self.amend(digest=value)
        self.assertEqual(self.ledger(), ())

    def test_an_amended_commentary_is_held_to_the_voice_gate(self):
        self.append_many(2)
        with self.assertRaises(manifest.ManifestError):
            self.amend(field="commentary",
                       amended="I check the tileset and the manifest.")
        self.assertEqual(self.ledger(), ())

    def test_an_amended_action_keeps_the_derived_shape(self):
        self.append_many(2)
        with self.assertRaises(manifest.ManifestError):
            self.amend(amended="something else entirely")
        self.assertEqual(self.ledger(), ())

    def test_an_amendment_may_not_introduce_raw_markup(self):
        """The ledger is a publication path, so it carries the rule too.

        A review found the markup gate applied to the transcript's
        heading alone.  This is the other door into the published
        Markdown: whatever `amended` says is what a derivative prints.
        `recorded` is held to it as well, because that field QUOTES a
        manifest row and the row writer refuses markup -- so a
        `recorded` value carrying any is a claim about a row that cannot
        exist.
        """
        self.append_many(2)
        for field, amended in (
                ("commentary",
                 "I take the tin <img src=x onerror=alert(1)>."),
                ("action", "press '5' -- wait <b>here</b>")):
            with self.subTest(field=field):
                with self.assertRaises(manifest.ManifestError) as caught:
                    self.amend(field=field, amended=amended)
                self.assertIn("angle bracket", str(caught.exception))
        with self.assertRaises(manifest.ManifestError):
            self.amend(field="commentary",
                       recorded="I wait <b>here</b>, and listen.",
                       amended="I wait, and listen to the corridor.")
        self.assertEqual(self.ledger(), ())

    def test_an_amended_commentary_may_not_be_one_word(self):
        """A correction that restates the defect is not a correction."""
        self.append_many(2)
        with self.assertRaises(manifest.ManifestError) as caught:
            self.amend(field="commentary", amended="South.")
        self.assertIn("which is one word", str(caught.exception))
        self.assertEqual(self.ledger(), ())

    def test_a_one_word_row_can_still_be_amended_into_a_reason(self):
        """The path the 44 delivered entries are corrected through.

        The `recorded` side is a one-word label -- that is the whole
        point of the amendment -- so the substance rule applies to the
        amended value alone.  The row is written as a LINE rather than
        through the writer, because the writer now refuses it: that is
        the shape of the delivered record, which was captured before the
        rule existed and is append-only.
        """
        self.write_frames([1, 2])
        self.append(frame=1)
        with open(self.manifest, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"frame": 2, "file": manifest.frame_file(2),
                 "real_ts": FIXED_REAL_TS, "ingame_clock": "08:15:33",
                 "action": "press 'm' -- begin spelling the start",
                 "commentary": "M."}, ensure_ascii=False) + "\n")
        row = self.amend(
            frame=2, field="commentary",
            amended="Spelling it is faster than reading the whole list.",
            basis="the capture shows the search box with an M in it.",
            reason="the recorded note transcribed the key rather than "
                   "saying why the search was opened.")
        self.assertEqual(row["recorded"], "M.")
        self.assertEqual(
            manifest.verify_amendments(
                self.ledger_path(), self.manifest, root=self.directory),
            [])

    def test_the_ledger_may_not_be_pointed_at_another_artifact(self):
        """The exploit this closes is a write, not a read.

        Every artifact of this pipeline lives inside playthrough/, so
        containment alone would let a path name the manifest, a frame or
        the movie and have amendment rows appended onto the end of it.
        """
        self.append_many(2)
        for name in ("manifest.jsonl", "timeline.json",
                     os.path.join("frames", "frame_00001.png")):
            with self.subTest(target=name):
                with self.assertRaises(manifest.ManifestError):
                    manifest.append_amendment(
                        os.path.join(self.directory, name), 1,
                        FIXED_REAL_TS, 1, "action", "ab" * 32,
                        "press '5'", "press '5' -- x", "b", "r",
                        root=self.directory)

    def test_resolution_applies_only_the_named_narration(self):
        self.append_many(3)
        self.amend(frame=2)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        resolved, touched = manifest.resolve_rows(rows, self.ledger())
        self.assertEqual(touched, (2,))
        self.assertTrue(resolved[1]["action"].endswith(self.MARKER))
        self.assertEqual(resolved[0], rows[0])
        self.assertEqual(resolved[2], rows[2])
        # And the input rows were not mutated in place.
        self.assertNotIn(self.MARKER, rows[1]["action"])

    def test_a_digest_that_has_moved_is_a_refusal_not_a_skip(self):
        self.append_many(2)
        self.amend(frame=2)
        ledger = [dict(one) for one in self.ledger()]
        ledger[0]["source_sha256"] = "ab" * 32
        rows = manifest.read_rows(self.manifest, root=self.directory)
        with self.assertRaises(manifest.ManifestError):
            manifest.resolve_rows(rows, ledger)
        # The LEDGER ON DISK is untouched by the tampering above, so it
        # still verifies: the refusal came from the altered copy.
        self.assertEqual(
            manifest.verify_amendments(
                self.ledger_path(), self.manifest, root=self.directory),
            [])

    def test_a_recorded_value_that_no_longer_matches_is_refused(self):
        self.append_many(2)
        self.amend(frame=2)
        ledger = [dict(one) for one in self.ledger()]
        ledger[0]["recorded"] = "press '5' -- something else"
        rows = manifest.read_rows(self.manifest, root=self.directory)
        with self.assertRaises(manifest.ManifestError):
            manifest.resolve_rows(rows, ledger)

    def test_a_frame_the_rows_do_not_carry_is_refused(self):
        self.append_many(2)
        self.amend(frame=2)
        ledger = [dict(one) for one in self.ledger()]
        ledger[0]["frame"] = 9
        rows = manifest.read_rows(self.manifest, root=self.directory)
        with self.assertRaises(manifest.ManifestError):
            manifest.resolve_rows(rows, ledger)

    def test_one_narration_may_not_be_amended_twice(self):
        self.append_many(2)
        self.amend(frame=2, number=1)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        digests = manifest.row_digests(self.manifest,
                                       root=self.directory)
        manifest.append_amendment(
            self.ledger_path(), 2, FIXED_REAL_TS, 2, "action",
            digests[2], rows[1]["action"],
            rows[1]["action"] + manifest.ACTION_SEPARATOR +
            "nothing in the map column changed",
            "a second measurement", "a second reason",
            root=self.directory)
        problems = manifest.verify_amendments(
            self.ledger_path(), self.manifest, root=self.directory)
        self.assertTrue(any("amended by rows" in one
                            for one in problems), problems)
        with self.assertRaises(manifest.ManifestError):
            manifest.resolve_rows(rows, self.ledger())

    def test_the_numbering_runs_one_to_n(self):
        self.append_many(2)
        self.amend(frame=2, number=7)
        problems = manifest.verify_amendments(
            self.ledger_path(), self.manifest, root=self.directory)
        self.assertTrue(any("numbered 7" in one for one in problems),
                        problems)

    def test_an_amendment_naming_an_unrecorded_frame_is_reported(self):
        self.append_many(2)
        rows = manifest.read_rows(self.manifest, root=self.directory)
        digests = manifest.row_digests(self.manifest,
                                       root=self.directory)
        manifest.append_amendment(
            self.ledger_path(), 1, FIXED_REAL_TS, 2, "action",
            digests[2], rows[1]["action"],
            rows[1]["action"] + manifest.ACTION_SEPARATOR + self.MARKER,
            "basis", "reason", root=self.directory)
        # Now the record grows a row, which moves nothing -- the
        # amendment still names the same bytes -- so the ledger stays
        # verifiable.  This is the property that makes the ledger usable
        # during a session rather than only after one.
        self.append(frame=3)
        self.assertEqual(
            manifest.verify_amendments(
                self.ledger_path(), self.manifest, root=self.directory),
            [])

    def test_an_absent_ledger_is_the_ordinary_case(self):
        self.append_many(2)
        self.assertEqual(self.ledger(), ())
        self.assertEqual(
            manifest.verify_amendments(
                self.ledger_path(), self.manifest, root=self.directory),
            [])
        rows = manifest.read_rows(self.manifest, root=self.directory)
        resolved, touched = manifest.resolve_rows(rows, ())
        self.assertEqual(resolved, rows)
        self.assertEqual(touched, ())

    def test_the_digest_is_of_the_line_the_writer_wrote(self):
        self.append_many(1)
        line = self.lines()[0]
        row = manifest.read_rows(self.manifest, root=self.directory)[0]
        self.assertEqual(manifest.line_digest(line),
                         manifest.line_digest(row))
        self.assertEqual(
            manifest.row_digests(self.manifest,
                                 root=self.directory)[1],
            manifest.line_digest(line))

    def test_no_rewriting_function_survives_in_the_module(self):
        for name in ("extend_action", "_rewrite_rows"):
            with self.subTest(function=name):
                self.assertFalse(
                    hasattr(manifest, name),
                    msg=("%s could rewrite captured evidence; it was "
                         "deleted rather than guarded" % name))


class TestTheCaptureAttestationLedger(ManifestFixture):
    """What the frames' BYTES were, recorded when they were published.

    THE DEFECT THIS SUITE EXISTS FOR.  A security review observed that
    nothing anywhere in this pipeline had ever recorded a capture's
    digest: every check on a frame was structural -- the count identity,
    the file exists, it is 1920x1080, it is not blank -- and a
    same-sized, non-blank, correctly-named replacement PNG dropped into
    playthrough/frames/ therefore passed the entire chain, all the way
    into the film and the commit.

    So the assertions below hold four things.  That an attestation is
    validated as strictly as a row.  That the STRENGTH of the claim is
    part of the row -- "capture" at publication, "recovery" when an
    interrupted step was completed, "commit" when a session captured
    before this ledger existed was sealed afterwards from its own
    committed blob -- and that a post-hoc seal must name the git objects
    it rests on rather than asserting a digest nobody can re-derive.
    That the ledger is APPEND-ONLY, like the record it describes.  And
    that verification is a real re-hash of the file on disk, so the one
    substitution every other gate passes is refused here.
    """

    PAYLOAD = b"\x89PNG\r\n\x1a\n" + b"pretend pixels, but real bytes\n"

    def setUp(self):
        """The ledger lives under build/, so the tree needs one."""
        super().setUp()
        os.mkdir(os.path.join(self.directory, "build"))

    def ledger_path(self):
        """The one path the attestation ledger may live at."""
        return os.path.join(self.directory,
                            *manifest.DIGESTS_REL_PARTS)

    def frame_bytes(self, index, payload=None):
        """Write one frame and return (path, sha256, length)."""
        path = os.path.join(self.frames,
                            manifest.FRAME_NAME_FORMAT % index)
        body = self.PAYLOAD if payload is None else payload
        with open(path, "wb") as handle:
            handle.write(body)
        return path, hashlib.sha256(body).hexdigest(), len(body)

    def attest(self, index=1, attested="capture", payload=None,
               sha256=None, byte_count=None, git_blob=None,
               git_commit=None):
        """Seal one frame into the ledger and return the row."""
        _, digest, size = self.frame_bytes(index, payload)
        return manifest.append_frame_digest(
            self.ledger_path(), index, manifest.frame_file(index),
            digest if sha256 is None else sha256,
            size if byte_count is None else byte_count,
            attested, FIXED_REAL_TS, git_blob, git_commit,
            root=self.directory)

    def ledger(self):
        """Every attestation written so far."""
        return manifest.read_frame_digests(self.ledger_path(),
                                           self.directory)

    def problems(self, require_all=True):
        """Verify the tree's rows against its ledger."""
        return manifest.verify_frame_digests(
            manifest.read_rows(self.manifest, root=self.directory),
            self.ledger(), frames_dir=self.frames,
            root=self.directory, require_all=require_all)

    def test_the_declared_schema_is_the_eight_fields(self):
        self.assertEqual(
            manifest.DIGEST_FIELDS,
            ("frame", "file", "sha256", "bytes", "attested",
             "attested_ts", "git_blob", "git_commit"))
        self.assertEqual(
            manifest.DIGEST_ATTESTATIONS,
            ("capture", "recovery", "commit"))

    def test_the_ledger_lives_under_build(self):
        """It is derived evidence, not a narrative artifact."""
        self.assertEqual(manifest.DIGESTS_REL_PARTS,
                         ("build", "frame_digests.jsonl"))

    def test_an_attestation_is_appended_in_declared_order(self):
        self.append_many(1)
        row = self.attest(1)
        self.assertEqual(list(row), list(manifest.DIGEST_FIELDS))
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(self.problems(), [])

    def test_a_frame_that_still_hashes_the_same_verifies(self):
        self.append_many(3)
        for index in (1, 2, 3):
            self.attest(index)
        self.assertEqual(self.problems(), [])

    def test_a_replaced_frame_is_reported(self):
        """THE SUBSTITUTION EVERY STRUCTURAL CHECK PASSES."""
        self.append_many(1)
        self.attest(1)
        self.frame_bytes(1, b"\x89PNG\r\n\x1a\na different image\n")
        problems = self.problems()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("frame 1 is attested as sha256", problems[0])
        self.assertIn("these are not the bytes that were captured",
                      problems[0])

    def test_a_missing_frame_is_reported(self):
        self.append_many(1)
        self.attest(1)
        os.unlink(os.path.join(self.frames,
                               manifest.FRAME_NAME_FORMAT % 1))
        problems = self.problems()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("frame 1 is attested but", problems[0])

    def test_a_recorded_frame_with_no_attestation_is_reported(self):
        self.append_many(2)
        self.attest(1)
        self.frame_bytes(2)
        problems = self.problems()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("frame 2 is recorded but its bytes are not "
                      "attested", problems[0])

    def test_an_unattested_frame_can_be_tolerated_explicitly(self):
        """The one honest case: a session captured before the ledger.

        It is never the default, and the consumers that must not proceed
        without attestation leave it off.
        """
        self.append_many(2)
        self.attest(1)
        self.frame_bytes(2)
        self.assertEqual(self.problems(require_all=False), [])

    def test_an_attestation_for_an_unrecorded_frame_is_reported(self):
        """The other direction: a digest with no row behind it."""
        self.append_many(1)
        self.attest(1)
        self.attest(2)
        problems = self.problems()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("attests frame 2, which the record does not "
                      "carry", problems[0])

    def test_a_byte_count_that_disagrees_is_reported(self):
        """Length is checked as well as content.

        A digest and a length are cheap to record together and the pair
        makes a truncation report itself even in the impossible case that
        a collision were found.
        """
        self.append_many(1)
        _, digest, size = self.frame_bytes(1)
        manifest.append_frame_digest(
            self.ledger_path(), 1, manifest.frame_file(1), digest,
            size + 1, "capture", FIXED_REAL_TS, root=self.directory)
        problems = self.problems()
        self.assertTrue(
            any("byte(s) but" in problem for problem in problems),
            msg=problems)

    def test_a_second_attestation_for_one_frame_is_the_last_one(self):
        """A retry at one index legitimately produces two rows.

        The LAST is the capture on disk, exactly as the sidecar's
        last-row rule works -- and the repeat is reported rather than
        being silent.
        """
        self.append_many(1)
        self.attest(1)
        self.attest(1, payload=b"\x89PNG\r\n\x1a\nthe retry's bytes\n")
        latest = manifest.attested_digests(self.ledger())
        _, digest, _ = self.frame_bytes(
            1, b"\x89PNG\r\n\x1a\nthe retry's bytes\n")
        self.assertEqual(latest[1]["sha256"], digest)
        problems = self.problems()
        self.assertTrue(
            any("attested by rows 1 and 2" in problem
                for problem in problems), msg=problems)

    def test_an_unknown_attestation_strength_is_refused(self):
        with self.assertRaises(manifest.ManifestError) as caught:
            self.attest(1, attested="eyeballed")
        self.assertIn("eyeballed", str(caught.exception))

    def test_a_commit_attestation_must_name_its_git_objects(self):
        """A post-hoc seal that names nothing is an assertion.

        The whole reason for recording the weaker claim is that a reader
        can re-derive it from content-addressed evidence.
        """
        with self.assertRaises(manifest.ManifestError) as caught:
            self.attest(1, attested="commit")
        self.assertIn("must name the blob and the commit",
                      str(caught.exception))

    def test_a_commit_attestation_with_its_objects_is_accepted(self):
        row = self.attest(1, attested="commit", git_blob="a" * 40,
                          git_commit="b" * 40)
        self.assertEqual(row["attested"], "commit")
        self.assertEqual(row["git_blob"], "a" * 40)

    def test_a_capture_attestation_may_not_name_a_git_object(self):
        """It came from the running pipeline; a blob would be invented."""
        for field in ("git_blob", "git_commit"):
            with self.subTest(field=field):
                with self.assertRaises(manifest.ManifestError) as caught:
                    self.attest(1, **{field: "c" * 40})
                self.assertIn("may not name a git object",
                              str(caught.exception))

    def test_a_git_object_that_is_not_an_object_name_is_refused(self):
        for value in ("", "nope", "a" * 39, "A" * 40, "a" * 41):
            with self.subTest(value=value):
                with self.assertRaises(manifest.ManifestError):
                    self.attest(1, attested="commit", git_blob=value,
                                git_commit="b" * 40)

    def test_a_digest_that_is_not_a_sha256_is_refused(self):
        for value in ("", "not-a-digest", "AB" * 32, "ab" * 31):
            with self.subTest(sha256=value):
                with self.assertRaises(manifest.ManifestError):
                    self.attest(1, sha256=value)

    def test_an_empty_frame_is_refused(self):
        """A published frame is not zero bytes long."""
        for value in (0, -1):
            with self.subTest(bytes=value):
                with self.assertRaises(manifest.ManifestError):
                    self.attest(1, byte_count=value)

    def test_a_byte_count_that_is_not_an_integer_is_refused(self):
        """Held against the builder, so None is covered too.

        The fixture reads a missing byte count as "measure the file",
        which is what a caller means by omitting it; the builder is where
        an explicitly wrong value has to be refused.
        """
        for value in (True, 12.0, "12", None, [4]):
            with self.subTest(bytes=value):
                with self.assertRaises(manifest.ManifestError):
                    manifest.build_digest_row(
                        1, manifest.frame_file(1), "a" * 64, value,
                        "capture", FIXED_REAL_TS)

    def test_the_ledger_is_append_only(self):
        """Every row written stays written, byte for byte."""
        self.append_many(2)
        self.attest(1)
        before = _read_bytes(self.ledger_path())
        self.attest(2)
        after = _read_bytes(self.ledger_path())
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))

    def test_the_module_has_no_way_to_edit_the_ledger(self):
        """Asserted against the SOURCE, not against a run.

        An attestation that can be rewritten attests nothing, so the
        property is that no truncating writer EXISTS in this module --
        not merely that no test happened to reach one.
        """
        source = _read_bytes(manifest.__file__).decode("utf-8")
        for pattern in (', "w"', ", 'w'", 'mode="w"', "os.replace",
                        "mkstemp", "shutil.copy"):
            with self.subTest(pattern=pattern):
                self.assertNotIn(
                    pattern, source,
                    msg=("manifest.py writes by APPEND only; %r is a "
                         "way to rewrite what was recorded" % pattern))
        self.assertEqual(
            source.count("os.ftruncate("), 1,
            msg=("the ONE truncate in this module is the rollback that "
                 "removes a PARTIAL append's own bytes and can only "
                 "ever shorten the file back to where that append "
                 "began; a second call site would be a way to shorten "
                 "a ledger that was already complete"))

    def test_the_ledger_path_is_locked_to_its_canonical_name(self):
        """An export may not point the appends at another artifact."""
        with self.assertRaises(manifest.ManifestError):
            manifest._validated_digests_target(
                os.path.join(self.directory, "manifest.jsonl"),
                self.directory)

    def test_the_ledger_path_must_stay_inside_the_tree(self):
        with self.assertRaises(manifest.ManifestError):
            manifest._validated_digests_target(
                os.path.join(os.path.dirname(self.directory),
                             "build", "frame_digests.jsonl"),
                self.directory)

    def test_a_malformed_ledger_line_is_reported_by_position(self):
        self.append_many(1)
        self.attest(1)
        with open(self.ledger_path(), "a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaises(manifest.ManifestError) as caught:
            self.ledger()
        self.assertIn("line 2", str(caught.exception))

    def test_a_row_out_of_field_order_is_reported(self):
        rows = [{name: value for name, value in
                 reversed(list(self.attest(1).items()))}]
        problems = manifest.digest_row_problems(rows)
        self.assertTrue(
            any("writes its fields in the order" in problem
                for problem in problems), msg=problems)

    def test_the_command_line_verifies_the_captures(self):
        self.append_many(2)
        self.attest(1)
        self.attest(2)
        status = manifest.main(
            ["--manifest", self.manifest, "digests",
             "--ledger", self.ledger_path(),
             "--frames-dir", self.frames], root=self.directory)
        self.assertEqual(status, 0)

    def test_the_command_line_fails_on_a_replaced_frame(self):
        self.append_many(1)
        self.attest(1)
        self.frame_bytes(1, b"\x89PNG\r\n\x1a\nsubstituted\n")
        status = manifest.main(
            ["--manifest", self.manifest, "digests",
             "--ledger", self.ledger_path(),
             "--frames-dir", self.frames], root=self.directory)
        self.assertEqual(status, 1)


# ---------------------------------------------------------------------
# THE EVIDENCE ANCHOR
#
# Every other ledger in this module vouches for something ELSE in the
# tree: the digest ledger vouches for the frames, the observation sidecar
# for what was on screen.  None of them vouches for ITSELF, and a review
# named the cost precisely -- "every attestation is mutable with its
# evidence".  Rewrite a frame and rewrite its digest row in the same
# breath and the ledger, recomputed from the forged frame, agrees with
# itself perfectly.
#
# The anchor answers that with a hash chain: each row seals one artifact
# by sha256, by byte count and by GIT'S OWN blob name, and carries the
# previous row's chain hash, so the rows cannot be edited, reordered or
# dropped independently of one another.  The chain's head is then
# published as a commit trailer by commit_artifacts.sh, which is the half
# that puts it beyond the reach of anybody editing the working tree.
#
# THREE ATTACKS, THREE DIFFERENT DEFENCES, and the tests below hold each
# one separately because a single "it detects tampering" test would not
# say which layer did the detecting:
#   * change a sealed artifact          -> its seal no longer matches;
#   * change the row to match           -> the row's own chain no longer
#                                          derives from its fields;
#   * delete or reorder rows            -> seq is no longer contiguous
#                                          and prev_chain no longer
#                                          links.
# ---------------------------------------------------------------------
class AnchorFixture(unittest.TestCase):
    """A temporary approved tree carrying the sealed artifact set.

    The same `root=` discipline the rest of this suite uses: every path
    is resolved inside a tree the test owns, so the production
    confinement rules are the ones being exercised and the real
    playthrough/ is never opened.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="blitzy_anchor_")
        self.addCleanup(_remove_tree, self.directory)
        os.mkdir(os.path.join(self.directory, "build"))
        manifest._WARNED.clear()
        self.anchor = os.path.join(
            self.directory, *manifest.ANCHOR_REL_PARTS)

    def artifact(self, *parts):
        """Return the absolute path of a sealed artifact."""
        return os.path.join(self.directory, *parts)

    def write(self, parts, text):
        """Create one sealed artifact with `text` as its content."""
        path = self.artifact(*parts)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return path

    def populate(self, count=None):
        """Create the first `count` sealed artifacts (all, by default).

        Each gets content derived from its own name, so no two artifacts
        share a digest and a row that named the wrong file would be
        visible rather than coincidentally correct.
        """
        chosen = manifest.ANCHOR_SEALED[:count]
        created = []
        for parts in chosen:
            created.append(self.write(parts, "content of %s\n"
                                      % "/".join(parts)))
        return created

    def seal(self, sealed_by="creation"):
        """Seal everything present, returning (written, absent)."""
        return manifest.seal_artifacts(
            sealed_by, anchor_path=self.anchor,
            require_durable=False, root=self.directory)

    def rows(self):
        """Return the ledger's rows as the module reads them."""
        return manifest.read_anchor_rows(self.anchor, self.directory)

    def raw(self):
        """Return the ledger's lines exactly as written."""
        with open(self.anchor, "r", encoding="utf-8",
                  newline="") as handle:
            return handle.readlines()

    def rewrite(self, lines):
        """Replace the ledger with `lines` (each already terminated)."""
        with open(self.anchor, "w", encoding="utf-8",
                  newline="") as handle:
            handle.writelines(lines)

    def problems(self, require_all=True):
        """Return verify_anchor's findings for this tree."""
        return manifest.verify_anchor(
            self.anchor, self.directory, require_all=require_all)


class TestGitIsTheIndependentWitness(AnchorFixture):
    """The blob name is git's, computed here without running git.

    A second digest computed by the SAME code over the same bytes adds
    nothing -- it fails and succeeds in exactly the cases the first one
    does.  Git's blob name is different in kind: it is the name the
    repository itself will use for that content, derived by an algorithm
    this module reimplements, so agreement between the two is agreement
    between two independent descriptions of the same bytes.
    """

    # `git hash-object` on this host, for content whose hash is a matter
    # of public record rather than of this suite's opinion.
    EMPTY = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    HELLO = "ce013625030ba8dba906f756967f9e9ca394464a"

    def test_the_empty_blob_is_gits_empty_blob(self):
        path = self.write(("dossier.md",), "")
        self.assertEqual(manifest.git_blob_name(path, "test"), self.EMPTY)

    def test_a_known_blob_matches_gits_own_name_for_it(self):
        path = self.write(("dossier.md",), "hello\n")
        self.assertEqual(manifest.git_blob_name(path, "test"), self.HELLO)

    def test_the_name_covers_the_length_not_only_the_bytes(self):
        """Git prefixes the length, so two lengths cannot collide."""
        short = self.write(("dossier.md",), "a")
        longer = self.write(("transcript.md",), "aa")
        self.assertNotEqual(manifest.git_blob_name(short, "test"),
                            manifest.git_blob_name(longer, "test"))

    def test_the_blob_name_is_not_the_sha256(self):
        """Two descriptions, not one written twice."""
        path = self.write(("dossier.md",), "hello\n")
        self.assertNotEqual(manifest.git_blob_name(path, "test"),
                            manifest.file_digest(path, "test"))


class TestSealingTheEvidence(AnchorFixture):
    """One chained row per artifact, appended and never rewritten."""

    def test_every_present_artifact_is_sealed(self):
        self.populate()
        written, absent = self.seal()
        self.assertEqual(len(written), len(manifest.ANCHOR_SEALED))
        self.assertEqual(absent, ())
        self.assertEqual(
            [row["path"] for row in written],
            ["/".join(parts) for parts in manifest.ANCHOR_SEALED])

    def test_an_absent_artifact_is_reported_and_not_invented(self):
        self.populate(3)
        written, absent = self.seal()
        self.assertEqual(len(written), 3)
        self.assertEqual(len(absent),
                         len(manifest.ANCHOR_SEALED) - 3)
        self.assertNotIn("cata-play.mp4",
                         [row["path"] for row in written])
        self.assertIn("cata-play.mp4", absent)

    def test_the_row_carries_both_digests_and_the_byte_count(self):
        path = self.populate(1)[0]
        written, _ = self.seal()
        row = written[0]
        self.assertEqual(row["sha256"],
                         manifest.file_digest(path, "test"))
        self.assertEqual(row["git_blob"],
                         manifest.git_blob_name(path, "test"))
        self.assertEqual(row["bytes"], os.path.getsize(path))

    def test_the_declared_schema_is_the_written_schema(self):
        self.populate(1)
        written, _ = self.seal()
        self.assertEqual(tuple(written[0]), manifest.ANCHOR_FIELDS)

    def test_the_path_column_is_relative_to_the_approved_tree(self):
        """Not to the repository, and not absolute.

        A row that stored an absolute path would name this host, and a
        row that stored a repository-relative path would lose its
        directory component when the tree is read anywhere else -- which
        is a defect this column was corrected for.
        """
        self.populate()
        written, _ = self.seal()
        paths = [row["path"] for row in written]
        self.assertIn("build/frame_digests.jsonl", paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(os.path.isabs(path))
                self.assertNotIn("..", path.split("/"))

    def test_a_second_seal_appends_rather_than_replaces(self):
        self.populate(2)
        first, _ = self.seal()
        before = self.raw()
        second, _ = self.seal("media")
        after = self.raw()
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(len(after), len(before) + len(second))
        self.assertEqual([row["seq"] for row in self.rows()],
                         [1, 2, 3, 4])

    def test_the_seal_records_who_took_it(self):
        self.populate(1)
        self.seal("attest")
        self.assertEqual(self.rows()[0]["sealed_by"], "attest")

    def test_a_sealer_name_outside_the_grammar_is_refused(self):
        self.populate(1)
        for name in ("Creation", "with space", "", "x" * 33, "9lives"):
            with self.subTest(name=name):
                with self.assertRaises(manifest.ManifestError):
                    self.seal(name)

    def test_sealing_an_unsound_chain_is_refused_outright(self):
        """A broken ledger is not extended; it is reported.

        Appending onto a chain that is already broken would bury the
        break under new rows that all verify against each other.
        """
        self.populate(2)
        self.seal()
        lines = self.raw()
        self.rewrite([lines[1]])
        with self.assertRaises(manifest.ManifestError):
            self.seal()

    def test_a_sound_chain_reports_no_problems(self):
        self.populate()
        self.seal()
        self.assertEqual(manifest.anchor_chain_problems(self.rows()), [])
        self.assertEqual(self.problems(), [])

    def test_the_head_is_the_last_rows_chain(self):
        self.populate()
        self.seal()
        rows = self.rows()
        self.assertEqual(manifest.anchor_head(rows), rows[-1]["chain"])

    def test_an_empty_ledger_has_no_head(self):
        self.assertEqual(manifest.anchor_head(()), "")

    def test_the_head_moves_when_anything_is_resealed(self):
        self.populate(1)
        self.seal()
        first = manifest.anchor_head(self.rows())
        self.seal("media")
        self.assertNotEqual(manifest.anchor_head(self.rows()), first)


class TestTheChainDetectsTampering(AnchorFixture):
    """Each of the three attacks, and which layer catches it."""

    def test_changing_a_sealed_artifact_breaks_its_seal(self):
        self.populate()
        self.seal()
        self.write(("build", "frame_digests.jsonl"), "forged\n")
        problems = self.problems()
        self.assertTrue(problems)
        self.assertIn("build/frame_digests.jsonl", problems[0])
        self.assertIn("changed after it was sealed", problems[0])
        # The chain itself is untouched, so the diagnosis is about the
        # artifact rather than about the ledger.
        self.assertEqual(manifest.anchor_chain_problems(self.rows()), [])

    def test_rewriting_the_row_to_match_breaks_the_chain(self):
        """The second move an attacker makes, and its own detection."""
        self.populate()
        self.seal()
        path = self.write(("build", "frame_digests.jsonl"), "forged\n")
        lines = self.raw()
        for index, line in enumerate(lines):
            row = json.loads(line)
            if row["path"] != "build/frame_digests.jsonl":
                continue
            row["sha256"] = manifest.file_digest(path, "test")
            row["git_blob"] = manifest.git_blob_name(path, "test")
            row["bytes"] = os.path.getsize(path)
            lines[index] = json.dumps(row, separators=(",", ":")) + "\n"
        self.rewrite(lines)
        # The artifact now matches its row exactly ...
        drift = [p for p in self.problems()
                 if "changed after it was sealed" in p]
        self.assertEqual(drift, [])
        # ... and the row no longer hashes to the chain it declares.
        problems = manifest.anchor_chain_problems(self.rows())
        self.assertTrue(problems)
        self.assertIn("altered after it was sealed", problems[0])

    def test_deleting_a_row_breaks_the_sequence(self):
        self.populate()
        self.seal()
        lines = self.raw()
        del lines[9]
        self.rewrite(lines)
        problems = manifest.anchor_chain_problems(self.rows())
        self.assertTrue(problems)
        self.assertTrue(
            any("removed, reordered or inserted" in p for p in problems),
            msg=problems)

    def test_reordering_two_rows_breaks_the_sequence(self):
        self.populate()
        self.seal()
        lines = self.raw()
        lines[3], lines[4] = lines[4], lines[3]
        self.rewrite(lines)
        self.assertTrue(manifest.anchor_chain_problems(self.rows()))

    def test_a_sealed_artifact_that_vanished_is_reported(self):
        self.populate()
        self.seal()
        os.unlink(self.artifact("cata-play-cc.mp4"))
        problems = self.problems()
        self.assertTrue(any("cata-play-cc.mp4" in p and "not on disk" in p
                            for p in problems), msg=problems)

    def test_an_absent_ledger_is_a_finding_when_all_is_required(self):
        self.populate()
        self.assertTrue(self.problems(require_all=True))

    def test_an_absent_ledger_is_silent_when_all_is_not_required(self):
        """Mid-pipeline, an unsealed tree is not yet a failure."""
        self.populate()
        self.assertEqual(self.problems(require_all=False), [])


class TestCoverageIsReportedApartFromDrift(AnchorFixture):
    """An unsealed artifact is a question about ORDER, not integrity.

    The committer seals at each checkpoint, and the render stages write
    the timeline, the film and the transcripts AFTER the last session
    checkpoint.  So an artifact that exists and carries no seal is the
    normal mid-pipeline state, and the gate has to be able to say so
    without calling it tampering -- while still failing on an artifact
    that IS sealed and no longer matches.
    """

    def test_an_unsealed_artifact_is_named_as_pending(self):
        self.populate(2)
        self.seal()
        self.write(("cata-play.mp4",), "a film\n")
        self.assertEqual(
            manifest.unsealed_artifacts(self.anchor, self.directory),
            ("cata-play.mp4",))

    def test_a_fully_sealed_tree_has_nothing_pending(self):
        self.populate()
        self.seal()
        self.assertEqual(
            manifest.unsealed_artifacts(self.anchor, self.directory), ())

    def test_pending_coverage_is_a_finding_only_when_all_is_required(self):
        self.populate(2)
        self.seal()
        self.write(("cata-play.mp4",), "a film\n")
        self.assertEqual(self.problems(require_all=False), [])
        strict = self.problems(require_all=True)
        self.assertTrue(any("cata-play.mp4" in p and "outside the chain"
                            in p for p in strict), msg=strict)

    def test_pending_coverage_does_not_mask_drift(self):
        self.populate(2)
        self.seal()
        self.write(("cata-play.mp4",), "a film\n")
        self.write(("manifest.jsonl",), "forged\n")
        problems = self.problems(require_all=False)
        self.assertTrue(any("manifest.jsonl" in p for p in problems),
                        msg=problems)

    def test_reading_the_rows_twice_is_avoidable(self):
        """The `rows` argument is honoured rather than ignored."""
        self.populate(2)
        self.seal()
        self.write(("cata-play.mp4",), "a film\n")
        self.assertEqual(
            manifest.unsealed_artifacts(self.anchor, self.directory,
                                        rows=self.rows()),
            ("cata-play.mp4",))


class TestTheChainIsReimplementable(AnchorFixture):
    """The chain hash is derivable from the published rows alone.

    The point of an anchor an auditor can check is that they need this
    module's OUTPUT, not this module.  So the derivation is held to a
    definition written out independently here: sha256 over the previous
    chain value, a newline, and the row's own fields in compact JSON
    without the chain column.
    """

    def derive(self, row):
        fields = {name: row[name] for name in manifest.ANCHOR_FIELDS
                  if name != "chain"}
        payload = "%s\n%s" % (
            row["prev_chain"],
            json.dumps(fields, separators=(",", ":"), sort_keys=False))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def test_each_row_hashes_to_the_chain_it_declares(self):
        self.populate()
        self.seal()
        for row in self.rows():
            with self.subTest(seq=row["seq"]):
                self.assertEqual(self.derive(row), row["chain"])

    def test_each_row_links_to_the_one_before_it(self):
        self.populate()
        self.seal()
        previous = ""
        for row in self.rows():
            with self.subTest(seq=row["seq"]):
                self.assertEqual(row["prev_chain"], previous)
                previous = row["chain"]

    def test_the_first_rows_predecessor_is_the_empty_string(self):
        self.populate(1)
        self.seal()
        self.assertEqual(self.rows()[0]["prev_chain"], "")


class TestSealingRefusesToLeaveTheTree(AnchorFixture):
    """The anchor is confined exactly as every other ledger is."""

    def test_a_ledger_outside_the_approved_tree_is_refused(self):
        self.populate(1)
        with tempfile.TemporaryDirectory() as elsewhere:
            outside = os.path.join(elsewhere, "evidence_anchor.jsonl")
            with self.assertRaises(manifest.ManifestError):
                manifest.seal_artifacts(
                    "creation", anchor_path=outside,
                    require_durable=False, root=self.directory)

    def test_a_missing_build_directory_is_refused_not_created(self):
        target = os.path.join(self.directory, "build")
        shutil.rmtree(target)
        with self.assertRaises(manifest.ManifestError):
            self.seal()
        self.assertFalse(os.path.exists(target))

    def test_a_row_naming_a_path_outside_the_tree_is_a_finding(self):
        self.populate(1)
        self.seal()
        lines = self.raw()
        row = json.loads(lines[0])
        row["path"] = "../escaped.txt"
        lines[0] = json.dumps(row, separators=(",", ":")) + "\n"
        self.rewrite(lines)
        self.assertTrue(self.problems(require_all=False))


class TestTheSuiteTouchesNoEvidence(unittest.TestCase):
    """The record this module protects must survive its own tests."""

    THIRD_PARTY = ("moviepy", "PIL", "pytesseract", "numpy",
                   "imageio", "imageio_ffmpeg")

    def playthrough_dir(self):
        """Return the real playthrough/ directory, read-only."""
        tooling = os.path.dirname(os.path.abspath(manifest.__file__))
        return os.path.dirname(tooling)

    def test_the_module_imports_nothing_from_requirements(self):
        for name in self.THIRD_PARTY:
            with self.subTest(package=name):
                self.assertNotIn(
                    name, vars(manifest),
                    msg=("manifest.py must run on a bare interpreter: "
                         "the record has to be writable and auditable "
                         "without a render toolchain"))

    def test_the_committed_artifacts_are_untouched(self):
        root = self.playthrough_dir()
        watched = (os.path.join(root, "manifest.jsonl"),
                   os.path.join(root, "frames"),
                   os.path.join(root, "timeline.json"))
        before = [(path, os.path.exists(path)) for path in watched]
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "manifest.jsonl")
            manifest.append_row(
                target, 1, manifest.frame_file(1), FIXED_REAL_TS,
                "08:15:33", "press '5'", "I wait.",
                root=directory)
            self.assertEqual(
                manifest.count_rows(target, root=directory), 1)
        for path, existed in before:
            with self.subTest(path=path):
                self.assertEqual(
                    os.path.exists(path), existed,
                    msg=("this suite created or removed %s, which is "
                         "captured evidence" % path))


if __name__ == "__main__":
    # Wired up so that `python3 playthrough/tooling/test_manifest.py`
    # runs the suite and exits non-zero on any failure, which is how the
    # acceptance gate invokes it.
    unittest.main(verbosity=2)
