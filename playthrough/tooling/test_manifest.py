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
import io
import json
import os
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
            ("48:48:48", manifest.CLOCK_EXACT),
            ("half past something", manifest.CLOCK_UNRECOGNISED),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    manifest.classify_ingame_clock(value), expected)

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

    def test_out_of_character_wording_is_reported_never_rewritten(self):
        text = "I check the frame counter before the next screenshot."
        row, err = self.capture_stderr(self.row, commentary=text)
        self.assertEqual(
            row["commentary"], text,
            msg=("the advisory is advisory: the survivor's words are "
                 "reported, not edited"))
        self.assertIn("out-of-character wording", err)
        self.assertIn("TECHNICAL_NOTES.md", err)

    def test_the_meta_vocabulary_is_a_blunt_substring_test(self):
        self.assertEqual(
            manifest.find_meta_vocabulary("The FRAME of the door"),
            ["frame"],
            msg=("the match is deliberately blunt and case-folded, so "
                 "that a warning here predicts the transcript gate's "
                 "own grep"))
        self.assertEqual(
            manifest.find_meta_vocabulary("I sharpen the spear."), [],
            msg="in-character text produces no advisory")
        self.assertEqual(
            manifest.find_meta_vocabulary(None), [],
            msg="a non-string is not a text to search")

    def test_the_advisory_lists_every_hit_sorted(self):
        self.assertEqual(
            manifest.find_meta_vocabulary(
                "the ocr pipeline read the sidebar"),
            ["ocr", "pipeline", "sidebar"],
            msg="sorted and de-duplicated, so the report is stable")


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

    def test_out_of_character_commentary_is_advisory_not_a_problem(self):
        row = self.row(frame=1, commentary="I check the ocr output.")
        _write_lines(self.manifest, [json.dumps(row)])
        problems, err = self.capture_stderr(
            manifest.verify_manifest, self.manifest,
            root=self.directory)
        self.assertEqual(
            problems, [],
            msg=("a blunt substring match must not fail the gate on a "
                 "false positive"))
        self.assertIn("advisory only", err)


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
