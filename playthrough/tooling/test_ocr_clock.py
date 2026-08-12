#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/ocr_clock.py.

This module is the pipeline's only boundary with a genuinely
probabilistic tool, and the AAP's rule for it is absolute: OCR is an
ASSIST, the reading of the frame is authoritative, and an unreadable
value is reported as unreadable and never guessed.  Every honest failure
mode here looks exactly like a successful run from the outside -- a
frame reports no clock, the duration falls to the 0.25 s floor, and the
movie still renders -- so the properties that keep it honest have to be
asserted rather than assumed.

    python3 playthrough/tooling/test_ocr_clock.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED
* NOTHING IS EVER REPAIRED.  An impossible reading -- 88:15:32, which
  is what tesseract genuinely makes of a slashed zero in the game's own
  Terminus face -- is DECLINED and recorded as declined, never bent
  into 08:15:32.  This is measured against a real OCR run, not a mock.
* THE READ IS STATELESS.  unreadable then readable then unreadable
  returns None, the clock, then None again: no previous frame's value
  can leak forward, which is the only thing standing between a null
  reading and a fabricated one.
* THE 24_HOUR GATE.  'military' is a legal option value that renders
  0815.32 and would make every frame unreadable while every count still
  tallied, so it is refused by name before a single pixel is read.
* CONFINEMENT AND VALIDATION.  A frame path must name a real PNG, and
  is expected inside the capture directory -- a warning when a human is
  debugging, a refusal under --strict-path.
* THE CROP IS COMPUTED, NEVER GUESSED.  Every accepted form of an
  explicit rectangle is exercised, and a malformed one raises instead of
  being coerced into something plausible.
* THE THREE EXIT CODES ARE KEPT APART.  0 carries a reading on stdout,
  1 means the frame was read and held no such reading and stdout is
  EMPTY, 2 means a fault.  capture.sh maps those three onto its own
  clock_status, so conflating any two of them corrupts the manifest.
* THE DIAGNOSTIC LEVELS.  A misconfiguration warns; an ordinary
  watchless or menu frame is INFO.  Warning on every menu frame would
  bury the two lines that mean someone must intervene.

HOW THE PIPELINE IS EXERCISED WITHOUT A GAME
Two ways, deliberately.  Most tests substitute the preprocessing and
OCR steps with canned text, which makes the ORCHESTRATION -- pass order,
disagreement, statelessness, exit codes -- exactly reproducible.  A
final class renders synthetic sidebars with the game's own
data/font/Terminus.ttf and runs them through the REAL convert and
tesseract chain, so the substituted tests cannot all be passing against
a fiction; it skips itself when the toolchain is absent.

Standard library only, plus the sibling modules under test.  Every file
is written inside a temporary directory: playthrough/frames/ is
committed evidence and is never touched.
"""

import contextlib
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything
# written there.  This must precede the imports below to affect them.
sys.dont_write_bytecode = True

try:
    import ocr_clock
    import sidebar_geometry
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ocr_clock
    import sidebar_geometry

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - guarded, like the module's own
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    import numpy
except ImportError:  # pragma: no cover - guarded, like the module's own
    numpy = None

try:
    # POSIX only, and guarded exactly as the module under test guards it,
    # so the limit tests skip rather than error where it is absent.
    import resource
except ImportError:  # pragma: no cover - POSIX only
    resource = None


# The capture geometry the pipeline runs at, and the crop over it.
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
CROP = "288x1072+1632+4"
ROW_HEIGHT = 16
# Every font the engine ships for this grid draws FONT_WIDTH as half
# FONT_HEIGHT [src/options.cpp:2408-2438], which is what
# GLYPH_WIDTH_DIVISOR encodes.
CELL_WIDTH = ROW_HEIGHT // ocr_clock.GLYPH_WIDTH_DIVISOR

# A clock with no zero in it.  Terminus draws a SLASHED zero, which
# tesseract reads as an 8 -- measured, repeatedly, on this host -- so a
# zero-free time is the one that reads back exactly and a zero-bearing
# one is the honest hard case.  Both are used, for opposite purposes.
CLEAN_CLOCK = "13:45:27"
SLASHED_CLOCK = "08:15:32"
IMPOSSIBLE_CLOCK = "88:15:32"

# What the engine renders for a survivor with no watch.
PHRASE = "Around dawn"
DATE_LINE = "Thursday, Mar 8"

TOOLING = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(TOOLING))
TERMINUS = os.path.join(REPO_ROOT, "data", "font", "Terminus.ttf")

ENVIRONMENT_KEYS = (
    "PLAYTHROUGH_FRAMES_DIR",
    "PLAYTHROUGH_REPO_ROOT",
    "PLAYTHROUGH_OPTIONS_JSON",
    "PLAYTHROUGH_PANEL_OPTIONS_JSON",
    "PLAYTHROUGH_CONFIG_DIR",
    "PLAYTHROUGH_SCREEN_WIDTH",
    "PLAYTHROUGH_SCREEN_HEIGHT",
    "PLAYTHROUGH_TERMINAL_X",
    "PLAYTHROUGH_TERMINAL_Y",
    "PLAYTHROUGH_FONT_WIDTH",
    "PLAYTHROUGH_FONT_HEIGHT",
)


def _toolchain_ready():
    """True when a real end-to-end read is possible on this host."""
    if Image is None or numpy is None or not os.path.isfile(TERMINUS):
        return False
    if ocr_clock.bootstrap_problems():
        return False
    if ocr_clock.pytesseract is not None:
        return True
    return shutil.which(ocr_clock.TESSERACT_BIN) is not None


_TOOLCHAIN_READY = _toolchain_ready()


@contextlib.contextmanager
def _environment(**values):
    """Set environment variables for a block, then restore them."""
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


@contextlib.contextmanager
def _patched(module, **attributes):
    """Swap module attributes for a block, then restore them."""
    previous = {name: getattr(module, name) for name in attributes}
    try:
        for name, value in attributes.items():
            setattr(module, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(module, name, value)


class _Collector(logging.Handler):
    """A handler that keeps records, for asserting on log LEVELS."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self, level):
        """Every message logged at exactly ``level``."""
        return [record.getMessage() for record in self.records
                if record.levelno == level]


@contextlib.contextmanager
def _collected():
    """Collect this module's log records for a block."""
    collector = _Collector()
    handlers = list(ocr_clock.LOG.handlers)
    level = ocr_clock.LOG.level
    for handler in handlers:
        ocr_clock.LOG.removeHandler(handler)
    ocr_clock.LOG.addHandler(collector)
    ocr_clock.LOG.setLevel(logging.DEBUG)
    try:
        yield collector
    finally:
        ocr_clock.LOG.removeHandler(collector)
        for handler in handlers:
            ocr_clock.LOG.addHandler(handler)
        ocr_clock.LOG.setLevel(level)


def setUpModule():
    """Silence the module's WARNING stream for the whole suite.

    The warnings are how a substitution stays visible to an operator,
    and they are asserted here through the ``notes`` tuple every
    reading carries -- the checkable form of the same fact -- and
    through :class:`_Collector` where the LEVEL is the point.
    """
    ocr_clock.LOG.addHandler(logging.NullHandler())
    ocr_clock.LOG.propagate = False
    sidebar_geometry.LOG.addHandler(logging.NullHandler())
    sidebar_geometry.LOG.propagate = False


class OcrFixture(unittest.TestCase):
    """A temporary frames directory and a fake capture inside it."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_ocr_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.frames = os.path.join(self.root, "frames")
        os.makedirs(self.frames)
        self.frame = self.write_png("frame_00001.png")
        cleared = {name: None for name in ENVIRONMENT_KEYS}
        self.env = _environment(**cleared)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        # The module's only state is which one-shot warnings have been
        # emitted.  Clearing it per test makes the log assertions
        # independent of test order.
        ocr_clock.reset_diagnostics()
        self.addCleanup(ocr_clock.reset_diagnostics)

    def write_png(self, name, body=b"not really an image"):
        """Write a file that passes the PNG signature check."""
        path = os.path.join(self.frames, name)
        with open(path, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC + body)
        return path

    def write_bytes(self, name, data):
        """Write arbitrary bytes into the frames directory."""
        path = os.path.join(self.frames, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def options_file(self, values):
        """Write an engine-shaped options.json and return its path."""
        holder = os.path.join(self.root, "config")
        os.makedirs(holder, exist_ok=True)
        path = os.path.join(holder, "options.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"name": name, "value": value}
                       for name, value in values.items()], handle)
        return path

    def fake_pipeline(self, texts, calls=1):
        """Substitute preprocessing and OCR with canned pass output.

        ``texts`` maps a pass name to the text that pass "reads"; a
        missing pass reads nothing.  The frame is still validated and
        the crop still resolved, so only the two steps that need a real
        toolchain are replaced.
        """
        seen = []

        def preprocess(png_path, rect, row_height, ocr_pass, engine):
            return object(), row_height

        def scan(strip, band_height, ocr_pass, ocr_engine, stop_early):
            seen.append(ocr_pass.name)
            return texts.get(ocr_pass.name, ""), calls

        def fits(png_path, rect):
            return (FRAME_WIDTH, FRAME_HEIGHT)

        context = _patched(ocr_clock, preprocess=preprocess,
                           _scan_strip=scan, _assert_rect_fits=fits)
        return context, seen

    def read(self, texts, calls=1, **kwargs):
        """Read the fixture frame through a canned pipeline."""
        arguments = {
            "rect": CROP,
            "row_height": ROW_HEIGHT,
            "check_options": False,
            "frames_dir": self.frames,
        }
        arguments.update(kwargs)
        context, seen = self.fake_pipeline(texts, calls)
        with context:
            reading = ocr_clock.read_sidebar(self.frame, **arguments)
        return reading, seen


class TestWhatCouldBeAClock(unittest.TestCase):
    """A reading is a time the engine could actually have rendered."""

    def test_a_fixed_width_reading_in_range_is_possible(self):
        for value in ("00:00:00", "08:15:32", "23:59:59", "13:45:27"):
            with self.subTest(value=value):
                self.assertTrue(ocr_clock.is_possible_clock(value))

    def test_a_time_the_engine_could_not_render_is_impossible(self):
        for value, why in (
                ("24:00:00", "hour_of_day is 0-23"),
                ("88:15:32", "the slashed-zero misread"),
                ("48:48:48", "a real OCR reading of a real frame"),
                ("12:60:00", "minute_of_hour is 0-59"),
                ("12:00:60", "the seconds term is 0-59"),
                ("99:99:99", "nothing about it is a time")):
            with self.subTest(value=value, why=why):
                self.assertFalse(
                    ocr_clock.is_possible_clock(value),
                    msg="%s: %s" % (value, why))

    def test_anything_that_is_not_the_engine_s_spelling_is_refused(self):
        for value in ("8:15:32", "0815.32", "08:15:32 AM", "08:15",
                      "108:15:32x", "", None, 81532, ["08:15:32"],
                      "08-15-32"):
            with self.subTest(value=value):
                self.assertFalse(ocr_clock.is_possible_clock(value))

    def test_a_longer_run_of_digits_is_not_silently_windowed(self):
        self.assertFalse(
            ocr_clock.is_possible_clock("108:15:322"),
            msg=("fullmatch, not search: taking a substring of a "
                 "longer number would invent a time nobody rendered"))

    def test_the_first_possible_clock_in_reading_order_wins(self):
        clock, impossible = ocr_clock.find_clocks(
            "%s\n%s" % (IMPOSSIBLE_CLOCK, CLEAN_CLOCK))
        self.assertEqual(clock, CLEAN_CLOCK)
        self.assertEqual(
            impossible, (IMPOSSIBLE_CLOCK,),
            msg=("what was declined is reported, and is never repaired "
                 "into the answer"))

    def test_a_second_possible_clock_does_not_displace_the_first(self):
        self.assertEqual(
            ocr_clock.find_clocks("13:45:27 and 14:00:00")[0],
            CLEAN_CLOCK,
            msg="the rule is fixed, so the same text always reads the "
                "same way")

    def test_a_repeated_impossible_reading_is_reported_once(self):
        clock, impossible = ocr_clock.find_clocks(
            "88:15:32 88:15:32 99:99:99")
        self.assertIsNone(clock)
        self.assertEqual(impossible, ("88:15:32", "99:99:99"))

    def test_empty_text_holds_no_clock_and_no_complaint(self):
        self.assertEqual(ocr_clock.find_clocks(""), (None, ()))

    def test_every_declined_reading_is_announced(self):
        notes = []
        self.assertEqual(
            ocr_clock.extract_clock(
                "%s\n%s" % (IMPOSSIBLE_CLOCK, CLEAN_CLOCK), notes),
            CLEAN_CLOCK)
        self.assertEqual(len(notes), 1)
        self.assertIn("NOT\n   repaired".replace("\n   ", " "),
                      notes[0])
        self.assertIn(IMPOSSIBLE_CLOCK, notes[0])


class TestTheCoarsePhrase(unittest.TestCase):
    """What a survivor without a watch actually sees, verbatim."""

    def test_every_phrase_the_engine_can_render_is_recognised(self):
        self.assertEqual(
            len(ocr_clock.COARSE_TIME_PHRASES), 11,
            msg="display::time_approx renders eleven phrases")
        for phrase in ocr_clock.COARSE_TIME_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    ocr_clock.extract_phrase(
                        "Wed, Mar 8\n%s\nMood" % phrase),
                    phrase,
                    msg="returned exactly as the engine spells it")

    def test_the_earliest_phrase_in_the_column_wins(self):
        self.assertEqual(
            ocr_clock.extract_phrase("Early morning then Morning"),
            "Early morning")

    def test_no_shipped_phrase_can_shadow_another_at_one_position(self):
        # The tie-break -- longer wins at the same position -- is
        # defensive, and this is why: no phrase is a prefix of another,
        # so the shipped vocabulary cannot produce a tie at all.  If a
        # future phrase breaks that, this test says so before the
        # tie-break silently starts mattering.
        for phrase in ocr_clock.COARSE_TIME_PHRASES:
            for other in ocr_clock.COARSE_TIME_PHRASES:
                if phrase == other:
                    continue
                with self.subTest(phrase=phrase, other=other):
                    self.assertFalse(phrase.startswith(other))

    def test_the_unknown_marker_is_a_reading_of_last_resort(self):
        self.assertEqual(
            ocr_clock.extract_phrase("Time    ???"),
            ocr_clock.UNKNOWN_TIME_TEXT,
            msg="what time_string renders with no watch and no sky")
        self.assertEqual(
            ocr_clock.extract_phrase("??? Morning"), "Morning",
            msg="a phrase says strictly more, so it wins")

    def test_a_sidebar_with_no_phrase_yields_nothing(self):
        for text in ("", "Str 8 Dex 9", "13:45:27"):
            with self.subTest(text=text):
                self.assertIsNone(ocr_clock.extract_phrase(text))

    def test_a_phrase_is_not_a_clock(self):
        self.assertIsNone(
            ocr_clock.extract_clock(PHRASE),
            msg=("read_clock must still return None for a watchless "
                 "frame, because a phrase is not a parseable clock"))


class TestTheDateLine(unittest.TestCase):
    """Read separately, and never folded into the clock."""

    def test_the_month_form_is_recognised(self):
        self.assertEqual(
            ocr_clock.extract_date("Thursday, Mar 8 08:15:32"),
            DATE_LINE,
            msg="SHOW_MONTHS defaults to true, so this is the form in "
                "play")

    def test_the_season_form_is_recognised(self):
        self.assertEqual(
            ocr_clock.extract_date("Spring, day 12"), "Spring, day 12")

    def test_the_earliest_form_in_the_text_wins(self):
        self.assertEqual(
            ocr_clock.extract_date("Spring, day 3 Thursday, Mar 8"),
            "Spring, day 3")
        self.assertEqual(
            ocr_clock.extract_date("Thursday, Mar 8 Spring, day 3"),
            DATE_LINE)

    def test_every_weekday_and_month_the_engine_spells_is_read(self):
        for weekday in ocr_clock.WEEKDAY_NAMES:
            with self.subTest(weekday=weekday):
                self.assertEqual(
                    ocr_clock.extract_date("%s, Mar 8" % weekday),
                    "%s, Mar 8" % weekday)
        for month in ocr_clock.MONTH_NAMES:
            with self.subTest(month=month):
                self.assertEqual(
                    ocr_clock.extract_date("Sunday, %s 1" % month),
                    "Sunday, %s 1" % month)

    def test_every_season_including_the_engine_s_last_is_read(self):
        for season in ocr_clock.SEASON_NAMES:
            with self.subTest(season=season):
                self.assertEqual(
                    ocr_clock.extract_date("%s, day 7" % season),
                    "%s, day 7" % season)

    def test_something_that_is_not_a_date_line_is_not_one(self):
        for text in ("", "Marchish, Mar 8", "Thursday Mar 8",
                     "Thursday, Mars 8", "Spring day 3",
                     "Thursday, Mar"):
            with self.subTest(text=text):
                self.assertIsNone(ocr_clock.extract_date(text))

    def test_the_date_is_never_part_of_the_clock(self):
        self.assertEqual(
            ocr_clock.extract_clock("Thursday, Mar 8 13:45:27"),
            CLEAN_CLOCK,
            msg=("timeline.py's rollover guard cross-checks the date, "
                 "so it is read separately and returned separately"))


class TestDiagnosingAFailedRead(unittest.TestCase):
    """The level is calibrated: misconfiguration warns, life informs."""

    def setUp(self):
        ocr_clock.reset_diagnostics()
        self.addCleanup(ocr_clock.reset_diagnostics)

    def test_a_military_clock_in_the_pixels_is_a_warning(self):
        notes = []
        with _collected() as log:
            ocr_clock.diagnose_clock_text("Time 0815.32", notes)
        warnings = log.messages(logging.WARNING)
        self.assertEqual(len(warnings), 1)
        self.assertIn("0815.32", warnings[0])
        self.assertIn("seed_options.py", warnings[0])
        self.assertEqual(len(notes), 1)

    def test_a_twelve_hour_clock_in_the_pixels_is_a_warning(self):
        notes = []
        with _collected() as log:
            ocr_clock.diagnose_clock_text("Time 8:15:32 AM", notes)
        self.assertEqual(len(log.messages(logging.WARNING)), 1)
        self.assertIn("12h", notes[0])

    def test_a_watchless_survivor_is_reported_at_info(self):
        with _collected() as log:
            ocr_clock.diagnose_clock_text("Time %s" % PHRASE)
        self.assertEqual(
            log.messages(logging.WARNING), [],
            msg=("warning on every expected frame would bury the two "
                 "lines that mean someone must intervene"))
        self.assertEqual(len(log.messages(logging.INFO)), 1)
        self.assertIn(PHRASE, log.messages(logging.INFO)[0])

    def test_a_menu_frame_is_reported_at_info(self):
        with _collected() as log:
            ocr_clock.diagnose_clock_text("New Game    Load")
        self.assertEqual(log.messages(logging.WARNING), [])
        self.assertIn("most likely a menu",
                      log.messages(logging.INFO)[0])

    def test_the_misconfiguration_check_comes_first(self):
        # A frame could show both a military clock and a phrase; the
        # actionable cause has to win, or the run reports a watchless
        # survivor while the real problem is an option value.
        with _collected() as log:
            ocr_clock.diagnose_clock_text("0815.32 %s" % PHRASE)
        self.assertEqual(len(log.messages(logging.WARNING)), 1)
        self.assertEqual(log.messages(logging.INFO), [])


class TestTheFramePath(OcrFixture):
    """A frame is a real PNG, and is expected where capture puts them."""

    def test_a_valid_capture_resolves_to_its_absolute_path(self):
        self.assertEqual(
            ocr_clock.validate_frame_path(
                self.frame, frames_dir=self.frames),
            os.path.realpath(self.frame))

    def test_something_that_is_not_a_path_is_refused(self):
        for value in ("", "   ", None, 42, ["frame.png"]):
            with self.subTest(value=value):
                with self.assertRaises(ocr_clock.FramePathError):
                    ocr_clock.validate_frame_path(
                        value, frames_dir=self.frames)

    def test_a_file_that_is_not_a_png_is_refused(self):
        path = os.path.join(self.frames, "frame_00001.jpg")
        with open(path, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        with self.assertRaises(ocr_clock.FramePathError) as bad:
            ocr_clock.validate_frame_path(path, frames_dir=self.frames)
        self.assertIn("one PNG per keystroke", str(bad.exception))

    def test_a_missing_frame_is_a_fault_not_an_unreadable_clock(self):
        with self.assertRaises(ocr_clock.FrameMissingError) as bad:
            ocr_clock.validate_frame_path(
                os.path.join(self.frames, "frame_09999.png"),
                frames_dir=self.frames)
        self.assertIn(
            "reported rather than returned as None",
            str(bad.exception),
            msg=("returning None here would turn a wrong path into a "
                 "floored duration instead of an error"))

    def test_a_directory_named_like_a_frame_is_refused(self):
        path = os.path.join(self.frames, "frame_00002.png")
        os.makedirs(path)
        with self.assertRaises(ocr_clock.FrameMissingError):
            ocr_clock.validate_frame_path(path, frames_dir=self.frames)

    def test_a_file_without_the_png_signature_is_refused(self):
        path = self.write_bytes("frame_00003.png", b"GIF89a nope")
        with self.assertRaises(ocr_clock.FrameUnreadableError) as bad:
            ocr_clock.validate_frame_path(path, frames_dir=self.frames)
        self.assertIn("PNG signature", str(bad.exception))

    def test_a_truncated_signature_is_refused(self):
        path = self.write_bytes("frame_00004.png",
                                ocr_clock.PNG_MAGIC[:4])
        with self.assertRaises(ocr_clock.FrameUnreadableError):
            ocr_clock.validate_frame_path(path, frames_dir=self.frames)

    def test_an_empty_file_is_refused(self):
        path = self.write_bytes("frame_00005.png", b"")
        with self.assertRaises(ocr_clock.FrameUnreadableError):
            ocr_clock.validate_frame_path(path, frames_dir=self.frames)

    def test_a_frame_outside_the_capture_directory_warns(self):
        outside = os.path.join(self.root, "hand_picked.png")
        with open(outside, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        notes = []
        resolved = ocr_clock.validate_frame_path(
            outside, frames_dir=self.frames, notes=notes)
        self.assertEqual(resolved, os.path.realpath(outside))
        self.assertEqual(
            len(notes), 1,
            msg=("reading one arbitrary frame is how a human debugs "
                 "this module, so it warns rather than refusing"))
        self.assertIn("outside the capture directory", notes[0])

    def test_strict_mode_refuses_the_same_frame(self):
        outside = os.path.join(self.root, "hand_picked.png")
        with open(outside, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        with self.assertRaises(ocr_clock.FramePathError):
            ocr_clock.validate_frame_path(
                outside, frames_dir=self.frames, strict=True)

    def test_a_symlink_cannot_smuggle_a_frame_past_the_check(self):
        outside = os.path.join(self.root, "elsewhere.png")
        with open(outside, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        link = os.path.join(self.frames, "frame_00006.png")
        os.symlink(outside, link)
        with self.assertRaises(ocr_clock.FramePathError):
            ocr_clock.validate_frame_path(
                link, frames_dir=self.frames, strict=True)

    def test_a_traversal_segment_cannot_either(self):
        outside = os.path.join(self.root, "elsewhere.png")
        with open(outside, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        sneaky = os.path.join(self.frames, "..", "elsewhere.png")
        with self.assertRaises(ocr_clock.FramePathError):
            ocr_clock.validate_frame_path(
                sneaky, frames_dir=self.frames, strict=True)

    def test_a_sibling_directory_with_a_shared_prefix_is_outside(self):
        sibling = self.frames + "_extra"
        os.makedirs(sibling)
        path = os.path.join(sibling, "frame_00001.png")
        with open(path, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        with self.assertRaises(ocr_clock.FramePathError):
            ocr_clock.validate_frame_path(
                path, frames_dir=self.frames, strict=True)

    def test_the_capture_directory_comes_from_the_environment(self):
        with _environment(PLAYTHROUGH_FRAMES_DIR=self.frames):
            self.assertEqual(ocr_clock.default_frames_dir(),
                             os.path.realpath(self.frames))
            self.assertEqual(
                ocr_clock.validate_frame_path(self.frame, strict=True),
                os.path.realpath(self.frame),
                msg=("a clone-indexed run exports its own frames "
                     "directory, and this module must agree with it"))

    def test_the_default_capture_directory_is_the_committed_one(self):
        self.assertEqual(
            ocr_clock.default_frames_dir(),
            os.path.realpath(os.path.join(
                os.path.dirname(TOOLING), "frames")),
            msg=("derived from this file's own location, so it is "
                 "correct in any checkout and needs no working "
                 "directory"))


class TestThe24HourGate(OcrFixture):
    """The clock format is asserted before a pixel is read."""

    def test_the_required_value_is_accepted_quietly(self):
        notes = []
        self.assertEqual(
            ocr_clock.assert_24_hour_option(
                options={"24_HOUR": "24h"}, notes=notes),
            "24h")
        self.assertEqual(notes, [])

    def test_surrounding_whitespace_does_not_change_the_answer(self):
        self.assertEqual(
            ocr_clock.assert_24_hour_option(
                options={"24_HOUR": " 24h "}), "24h")

    def test_the_military_value_is_refused_by_name(self):
        with self.assertRaises(ocr_clock.OptionsError) as bad:
            ocr_clock.assert_24_hour_option(
                options={"24_HOUR": "military"})
        message = str(bad.exception)
        self.assertIn("0815.32", message)
        self.assertIn(
            "collapse to the floor", message,
            msg=("a legal option value that quietly destroys every "
                 "duration has to explain itself"))
        self.assertIn("seed_options.py", message)

    def test_the_twelve_hour_default_is_refused_too(self):
        with self.assertRaises(ocr_clock.OptionsError) as bad:
            ocr_clock.assert_24_hour_option(options={"24_HOUR": "12h"})
        self.assertIn("variable padding", str(bad.exception))

    def test_any_other_value_is_refused(self):
        for value in ("", "24H", "twentyfour", "24h "[0:2]):
            with self.subTest(value=value):
                with self.assertRaises(ocr_clock.OptionsError):
                    ocr_clock.assert_24_hour_option(
                        options={"24_HOUR": value})

    def test_an_absent_option_is_refused_under_the_production_gate(
            self):
        # AN UNCONFIRMED FORMAT IS A FAULT, not a warning.  Under
        # 'military' the sidebar renders 0815.32 and under '12h' it
        # renders 8:15:32 AM, and the clock pattern matches neither --
        # so every frame would read as unreadable, every duration would
        # collapse onto the floor, and every count would still tally.
        # The production gate therefore raises rather than proceeding.
        with self.assertRaises(ocr_clock.OptionsError) as bad:
            ocr_clock.assert_24_hour_option(options={})
        self.assertIn("24_HOUR", str(bad.exception))

    def test_an_absent_option_warns_once_in_the_diagnostic_mode(self):
        notes = []
        with _collected() as log:
            self.assertIsNone(
                ocr_clock.assert_24_hour_option(options={}, notes=notes,
                                                require=False))
            self.assertIsNone(
                ocr_clock.assert_24_hour_option(options={}, notes=notes,
                                                require=False))
        self.assertEqual(
            len(log.messages(logging.WARNING)), 1,
            msg=("one complaint per process, not one per frame, "
                 "across the hundreds a session captures"))
        self.assertEqual(
            len(notes), 2,
            msg=("the note is still recorded every time, so an "
                 "individual reading's record stays complete"))

    def test_a_fresh_userdir_with_no_options_file_is_still_unconfirmed(
            self):
        absent = os.path.join(self.root, "config", "options.json")
        with self.assertRaises(ocr_clock.OptionsError):
            ocr_clock.assert_24_hour_option(options_json=absent)
        self.assertIsNone(
            ocr_clock.assert_24_hour_option(options_json=absent,
                                            require=False),
            msg=("the engine writes options.json on its first launch, "
                 "so its absence is an ordinary state to LOOK at -- "
                 "just never one to capture a session under"))

    def test_an_options_file_that_cannot_be_read_is_a_fault(self):
        holder = os.path.join(self.root, "config")
        os.makedirs(holder, exist_ok=True)
        path = os.path.join(holder, "options.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(ocr_clock.OptionsError) as bad:
            ocr_clock.assert_24_hour_option(options_json=path)
        self.assertIn("cannot be confirmed", str(bad.exception))

    def test_the_real_options_file_is_read_when_one_is_given(self):
        path = self.options_file({"24_HOUR": "24h",
                                  "TERMINAL_X": "240"})
        self.assertEqual(
            ocr_clock.assert_24_hour_option(options_json=path), "24h")

    def test_the_gate_runs_before_any_pixel_is_touched(self):
        path = self.options_file({"24_HOUR": "military"})

        def explode(*args, **kwargs):
            raise AssertionError("preprocessing must not be reached")

        context, _ = self.fake_pipeline({})
        with context, _patched(ocr_clock, preprocess=explode):
            with self.assertRaises(ocr_clock.OptionsError):
                ocr_clock.read_sidebar(
                    self.frame, rect=CROP, row_height=ROW_HEIGHT,
                    check_options=True, options_json=path,
                    frames_dir=self.frames)


class TestTheCropRectangle(OcrFixture):
    """Computed by sidebar_geometry, or given explicitly, never guessed."""

    def test_the_geometry_string_form_is_parsed(self):
        rect = ocr_clock.parse_geometry(CROP)
        self.assertEqual(rect.geometry, CROP)
        self.assertEqual((rect.width, rect.height, rect.x, rect.y),
                         (288, 1072, 1632, 4))

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(
            ocr_clock.parse_geometry("  %s\n" % CROP).geometry, CROP,
            msg="the string arrives from a shell command substitution")

    def test_anything_that_is_not_that_form_is_refused(self):
        for value in ("288x1072", "288x1072+1632", "288 1072 1632 4",
                      "288x1072-1632+4", "0x1072+1632+4",
                      "288x0+1632+4", "abcxdef+1+1", "", CROP + "x",
                      None, 288):
            with self.subTest(value=value):
                with self.assertRaises(ocr_clock.RectError):
                    ocr_clock.parse_geometry(value)

    def test_an_explicit_rectangle_is_used_as_given(self):
        rect, rows = ocr_clock.resolve_rect(CROP, ROW_HEIGHT)
        self.assertEqual(rect.geometry, CROP)
        self.assertEqual(rows, ROW_HEIGHT)

    def test_every_accepted_form_names_the_same_rectangle(self):
        forms = (
            CROP,
            sidebar_geometry.Rect(width=288, height=1072, x=1632, y=4),
            (288, 1072, 1632, 4),
            [288, 1072, 1632, 4],
        )
        for form in forms:
            with self.subTest(form=type(form).__name__):
                self.assertEqual(
                    ocr_clock.resolve_rect(form, ROW_HEIGHT)[0].geometry,
                    CROP,
                    msg=("the sequence order is the geometry order, so "
                         "reading a call and reading a crop are the "
                         "same exercise"))

    def test_a_whole_geometry_record_carries_its_own_row_height(self):
        geometry = sidebar_geometry.compute_sidebar_geometry(
            sidebar_cells=36, terminal_x=240, terminal_y=67,
            font_width=8, font_height=16, screen_width=FRAME_WIDTH,
            screen_height=FRAME_HEIGHT)
        rect, rows = ocr_clock.resolve_rect(geometry)
        self.assertEqual(rect.geometry, CROP)
        self.assertEqual(
            rows, ROW_HEIGHT,
            msg="FONT_HEIGHT * SCALING_FACTOR, from the same record")

    def test_a_scaled_geometry_scales_the_row_height_with_it(self):
        geometry = sidebar_geometry.compute_sidebar_geometry(
            sidebar_cells=36, terminal_x=240, terminal_y=67,
            font_width=8, font_height=16, scaling_factor=2,
            screen_width=FRAME_WIDTH, screen_height=FRAME_HEIGHT)
        self.assertEqual(ocr_clock.resolve_rect(geometry)[1], 32)

    def test_a_sequence_of_the_wrong_length_is_refused(self):
        for form in ((288, 1072, 1632), (288, 1072, 1632, 4, 0), ()):
            with self.subTest(form=form):
                with self.assertRaises(ocr_clock.RectError) as bad:
                    ocr_clock.resolve_rect(form, ROW_HEIGHT)
                self.assertIn("(width, height, x, y)",
                              str(bad.exception))

    def test_a_sequence_that_is_not_a_rectangle_is_refused(self):
        for form in ((288, 1072, 1632, -4), (0, 1072, 1632, 4),
                     ("wide", 1072, 1632, 4)):
            with self.subTest(form=form):
                with self.assertRaises(ocr_clock.RectError):
                    ocr_clock.resolve_rect(form, ROW_HEIGHT)

    def test_a_crop_of_an_unusable_type_is_refused(self):
        for form in (17, 4.0, {"width": 288}, object()):
            with self.subTest(form=type(form).__name__):
                with self.assertRaises(ocr_clock.RectError) as bad:
                    ocr_clock.resolve_rect(form, ROW_HEIGHT)
                self.assertIn("must be None", str(bad.exception))

    def test_a_row_height_that_is_not_one_is_refused(self):
        for rows in (0, -16, "16", 16.0, True):
            with self.subTest(rows=rows):
                with self.assertRaises(ocr_clock.RectError):
                    ocr_clock.resolve_rect(CROP, rows)

    def test_a_row_taller_than_the_crop_holds_no_row_at_all(self):
        with self.assertRaises(ocr_clock.RectError) as bad:
            ocr_clock.resolve_rect("288x16+1632+4", 32)
        self.assertIn("no complete row", str(bad.exception))

    def test_a_crop_that_is_not_whole_rows_reports_the_remainder(self):
        notes = []
        ocr_clock.resolve_rect("288x100+1632+4", ROW_HEIGHT, notes)
        self.assertTrue(
            any("remainder at the bottom is not read" in note
                for note in notes),
            msg="4 px of the column go unread, and that is said")

    def test_an_absent_crop_is_computed_from_configuration(self):
        absent = os.path.join(self.root, "config", "options.json")
        notes = []
        rect, rows = ocr_clock.resolve_rect(None, None, notes,
                                            options_json=absent)
        self.assertIsInstance(rect, sidebar_geometry.Rect)
        self.assertEqual(rows, ROW_HEIGHT)
        self.assertTrue(
            any("no options file at" in note for note in notes),
            msg=("every substitution the computation had to make is "
                 "copied into the reading's notes: %r" % (notes,)))

    def test_a_computation_that_cannot_be_made_is_a_fault(self):
        def refuse(**kwargs):
            raise sidebar_geometry.GeometryError("no widget anywhere")

        with _patched(sidebar_geometry,
                      compute_sidebar_geometry=refuse):
            with self.assertRaises(ocr_clock.RectError) as bad:
                ocr_clock.resolve_rect(None, ROW_HEIGHT)
        self.assertIn("could not be computed", str(bad.exception))


class TestTheToolchain(OcrFixture):
    """A missing tool is a fault, and a substitution is announced."""

    def test_the_prescribed_engines_are_the_defaults(self):
        self.assertEqual(ocr_clock.ENGINE_CONVERT, "convert")
        self.assertEqual(ocr_clock.OCR_PYTESSERACT, "pytesseract")

    def test_an_unknown_engine_is_refused(self):
        for name in ("magick", "opencv", "convert2"):
            with self.subTest(name=name):
                with self.assertRaises(ocr_clock.ToolchainError):
                    ocr_clock.resolve_engine(name)
        for name in ("easyocr", "tesseract4"):
            with self.subTest(name=name):
                with self.assertRaises(ocr_clock.ToolchainError):
                    ocr_clock.resolve_ocr_engine(name)

    def test_an_empty_request_means_no_preference(self):
        for resolve, expected in (
                (ocr_clock.resolve_engine, ocr_clock.ENGINE_CONVERT),
                (ocr_clock.resolve_ocr_engine,
                 ocr_clock.OCR_PYTESSERACT)):
            with self.subTest(resolve=resolve.__name__):
                with _patched(ocr_clock.shutil,
                              which=lambda name: "/usr/bin/" + name):
                    with _patched(ocr_clock, pytesseract=object()):
                        self.assertEqual(resolve(""), expected)
                        self.assertEqual(resolve(None), expected)

    def test_the_pillow_engine_is_selected_when_asked_for(self):
        self.assertEqual(
            ocr_clock.resolve_engine(ocr_clock.ENGINE_PILLOW),
            ocr_clock.ENGINE_PILLOW)

    def test_an_absent_convert_falls_back_to_pillow_loudly(self):
        notes = []
        # The verified-tool cache is per session, and an earlier test in
        # this suite will have resolved `convert` for real -- so PATH is
        # only asked again once that bookkeeping is forgotten.
        ocr_clock.reset_diagnostics()
        self.addCleanup(ocr_clock.reset_diagnostics)
        with _patched(ocr_clock.shutil, which=lambda name: None):
            self.assertEqual(
                ocr_clock.resolve_engine(notes=notes),
                ocr_clock.ENGINE_PILLOW)
        self.assertTrue(
            any("falls back to Pillow" in note for note in notes),
            msg="the reading may differ, so the substitution is said")

    def test_an_absent_pytesseract_calls_the_binary_loudly(self):
        notes = []
        with _patched(ocr_clock, pytesseract=None):
            self.assertEqual(
                ocr_clock.resolve_ocr_engine(notes=notes),
                ocr_clock.OCR_TESSERACT)
        self.assertTrue(
            any("tesseract binary directly" in note
                for note in notes))

    def test_a_missing_dependency_is_a_preflightable_problem(self):
        with _patched(ocr_clock, Image=None):
            problems = ocr_clock.bootstrap_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("Pillow", problems[0])
        self.assertIn(
            "FAULT, not an unreadable", problems[0],
            msg=("a missing package must not look like a frame that "
                 "held no clock"))

    def test_a_missing_sibling_module_is_one_too(self):
        with _patched(ocr_clock, sidebar_geometry=None):
            problems = ocr_clock.bootstrap_problems()
            self.assertEqual(len(problems), 1)
            self.assertIn("sidebar_geometry.py", problems[0])
            with self.assertRaises(ocr_clock.BootstrapError):
                ocr_clock.parse_geometry(CROP)

    def test_a_bootstrap_failure_is_an_ocr_clock_error(self):
        self.assertTrue(
            issubclass(ocr_clock.BootstrapError,
                       ocr_clock.OcrClockError),
            msg="so main() maps it onto the fault status like any "
                "other")

    def test_the_one_shot_warnings_can_be_forgotten(self):
        with _collected() as log:
            with _patched(ocr_clock, pytesseract=None):
                ocr_clock.resolve_ocr_engine()
                ocr_clock.resolve_ocr_engine()
                self.assertEqual(
                    len(log.messages(logging.WARNING)), 1)
                ocr_clock.reset_diagnostics()
                ocr_clock.resolve_ocr_engine()
                self.assertEqual(
                    len(log.messages(logging.WARNING)), 2)

    def test_the_pillow_minimum_is_the_pin_requirements_declares(self):
        """One version, in one place, for the check and the advice.

        The remediation an operator is given has to be a version this
        module would then ACCEPT.  When the two were written out
        separately they disagreed -- the diagnostic said to install
        11.3.0 while the check refused anything below 12.3.0 -- so
        following the advice reproduced the failure it was answering.
        The specifier is now derived from the constant, and the constant
        is compared against the declaration here.
        """
        wanted = ".".join(
            str(part) for part in ocr_clock.PILLOW_MIN_VERSION)
        self.assertEqual(ocr_clock.PILLOW_PIN_SPEC,
                         "pillow==%s" % wanted)
        declared = None
        path = os.path.join(TOOLING, "requirements.txt")
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("pillow=="):
                    declared = stripped.split("#", 1)[0].strip()
                    break
        self.assertEqual(
            declared, ocr_clock.PILLOW_PIN_SPEC,
            msg=("playthrough/tooling/requirements.txt pins the Pillow "
                 "this module decodes frames with; the two cannot "
                 "disagree"))

    def test_every_pillow_diagnostic_quotes_the_accepted_pin(self):
        with _patched(ocr_clock, Image=None):
            problems = ocr_clock.bootstrap_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn(ocr_clock.PILLOW_PIN_SPEC, problems[0])
        with _patched(ocr_clock, PILLOW_VERSION="9.0.0"):
            complaint = ocr_clock.pillow_complaint()
        self.assertIsNotNone(complaint)
        self.assertIn(ocr_clock.PILLOW_PIN_SPEC, complaint)
        self.assertIn("requirements.lock", complaint)

    def test_the_installed_pillow_satisfies_the_pin(self):
        """The environment this suite runs in is the pinned one.

        Not a tautology: it fails when an interpreter carrying some
        other Pillow is used, which is exactly the provisioning mistake
        the pin exists to catch.
        """
        self.assertIsNone(
            ocr_clock.pillow_complaint(),
            msg=("install playthrough/tooling/requirements.lock into "
                 "the interpreter running this suite"))


class TestTheReadingRecord(unittest.TestCase):
    """The evidence travels beside the answer."""

    def reading(self, **overrides):
        arguments = {
            "png": "/frames/frame_00001.png",
            "rect": CROP,
            "clock": CLEAN_CLOCK,
            "phrase": None,
            "date": DATE_LINE,
            "text": "Thursday, Mar 8\n13:45:27",
        }
        arguments.update(overrides)
        return ocr_clock.SidebarReading(**arguments)

    def test_a_reading_with_a_clock_is_readable(self):
        self.assertTrue(self.reading().readable)
        self.assertFalse(self.reading(clock=None).readable)

    def test_agreement_is_false_exactly_when_passes_disagree(self):
        self.assertTrue(self.reading(candidates=()).agreement)
        self.assertTrue(
            self.reading(candidates=(CLEAN_CLOCK,)).agreement)
        self.assertFalse(
            self.reading(
                candidates=(CLEAN_CLOCK, "13:45:28")).agreement)

    def test_the_record_is_json_serialisable_and_complete(self):
        record = self.reading(candidates=(CLEAN_CLOCK,),
                              declined=(IMPOSSIBLE_CLOCK,)).as_dict()
        json.dumps(record)
        for key in ("png", "rect", "clock", "phrase", "date",
                    "candidates", "declined", "agreement", "pass",
                    "passes_run", "ocr_calls", "engine", "ocr_engine",
                    "notes"):
            with self.subTest(key=key):
                self.assertIn(key, record)
        self.assertNotIn(
            "text", record,
            msg=("the raw OCR text is deliberately not in the JSON "
                 "record; --field text prints it when it is wanted"))

    def test_an_unreadable_reading_says_so_in_words(self):
        text = self.reading(clock=None).describe()
        self.assertIn("unreadable (None)", text)
        self.assertIn(CROP, text)

    def test_a_disagreement_is_visible_in_the_description(self):
        text = self.reading(
            candidates=(CLEAN_CLOCK, "13:45:28"),
            declined=(IMPOSSIBLE_CLOCK,)).describe()
        self.assertIn("agreement             NO", text)
        self.assertIn("declined as impossible", text)

    def test_a_reading_cannot_be_edited_after_the_fact(self):
        record = self.reading()
        with self.assertRaises(Exception):
            record.clock = "00:00:00"


class TestReadingOneFrame(OcrFixture):
    """The orchestration, against canned pass output."""

    def test_a_clock_is_read_and_the_winning_pass_is_named(self):
        reading, seen = self.read({"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertEqual(reading.pass_name, "deslash-rows")
        self.assertEqual(reading.candidates, (CLEAN_CLOCK,))
        self.assertEqual(reading.passes_run, ("deslash-rows",))
        self.assertEqual(
            seen, ["deslash-rows"],
            msg=("the first pass that yields a possible clock wins and "
                 "the rest are not run"))
        self.assertEqual(reading.ocr_calls, 1)

    def test_a_later_pass_reads_what_an_earlier_one_could_not(self):
        reading, seen = self.read({"reference-column": CLEAN_CLOCK})
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertEqual(reading.pass_name, "reference-column")
        self.assertEqual(
            seen,
            ["deslash-rows", "reference-rows", "reference-column"],
            msg="the passes are attempted in their documented order")

    def test_an_impossible_reading_is_declined_and_never_repaired(self):
        reading, seen = self.read({
            "deslash-rows": IMPOSSIBLE_CLOCK,
            "reference-rows": CLEAN_CLOCK})
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertEqual(reading.declined, (IMPOSSIBLE_CLOCK,))
        self.assertEqual(reading.pass_name, "reference-rows")
        self.assertTrue(
            any("NOT repaired into a plausible time" in note
                for note in reading.notes),
            msg=repr(reading.notes))

    def test_a_frame_no_pass_can_read_is_unreadable_not_wrong(self):
        reading, seen = self.read({"deslash-rows": IMPOSSIBLE_CLOCK})
        self.assertIsNone(
            reading.clock,
            msg=("None is never a stand-in for a value: no default, no "
                 "neighbouring frame, no interpolation, no repair"))
        self.assertEqual(reading.candidates, ())
        self.assertIsNone(reading.pass_name)
        self.assertEqual(
            len(seen), len(ocr_clock.PASSES),
            msg="every pass is tried before a frame is called "
                "unreadable")

    def test_disagreeing_passes_are_reported_rather_than_hidden(self):
        # THIS ASSERTED THE OPPOSITE ONCE.  The reading used to be
        # resolved by pass order -- the first pass that produced a
        # possible clock won, and the disagreement was recorded as a
        # note beside it.  That made an arbitrary choice the permanent
        # record of the frame, and the wrong choice is undetectable
        # downstream: it becomes a wrong duration, a wrong caption and a
        # wrong line in the transcript.  Two readers of the same pixels
        # returning different times have established that the time is
        # NOT established, so the clock is now WITHHELD while every
        # candidate is kept as evidence.  A null reading is reconciled
        # against the previous frame by timeline.py and is visible in
        # the manifest; a wrong one is not.
        reading, seen = self.read(
            {"deslash-rows": CLEAN_CLOCK,
             "reference-rows": "13:45:28",
             "reference-column": CLEAN_CLOCK},
            cross_check=True)
        self.assertIsNone(
            reading.clock,
            msg="a disagreed frame is unreadable, not resolved by order")
        self.assertIsNone(reading.pass_name)
        self.assertEqual(reading.candidates, (CLEAN_CLOCK, "13:45:28"))
        self.assertFalse(reading.agreement)
        self.assertFalse(reading.readable)
        self.assertEqual(len(seen), len(ocr_clock.PASSES))
        self.assertTrue(
            any("UNREADABLE" in note for note in reading.notes),
            msg=repr(reading.notes))
        self.assertTrue(
            any("nothing is averaged or repaired" in note
                for note in reading.notes),
            msg=repr(reading.notes))

    def test_a_cross_check_that_agrees_reports_one_candidate(self):
        reading, _ = self.read(
            {name: CLEAN_CLOCK
             for name in (item.name for item in ocr_clock.PASSES)},
            cross_check=True)
        self.assertEqual(reading.candidates, (CLEAN_CLOCK,))
        self.assertTrue(reading.agreement)

    def test_the_phrase_and_the_date_come_from_the_winning_text(self):
        reading, _ = self.read({
            "deslash-rows": "%s\n%s\n%s"
                            % (DATE_LINE, CLEAN_CLOCK, PHRASE)})
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertEqual(reading.date, DATE_LINE)
        self.assertEqual(reading.phrase, PHRASE)

    def test_a_watchless_sidebar_yields_a_phrase_and_no_clock(self):
        reading, _ = self.read({
            "deslash-rows": "%s\n%s" % (DATE_LINE, PHRASE),
            "reference-rows": "%s\n%s" % (DATE_LINE, PHRASE),
            "reference-column": "%s\n%s" % (DATE_LINE, PHRASE),
            "deslash-negate-rows": "%s\n%s" % (DATE_LINE, PHRASE)})
        self.assertIsNone(reading.clock)
        self.assertEqual(
            reading.phrase, PHRASE,
            msg=("a phrase is a genuine observation and is recorded as "
                 "it stands, while the clock stays None"))
        self.assertEqual(reading.date, DATE_LINE)

    def test_the_text_of_a_failed_read_is_still_reported(self):
        reading, _ = self.read({"reference-rows": "Str 8 Dex 9"})
        self.assertIn(
            "Str 8", reading.text,
            msg=("the first pass that produced any text at all is kept "
                 "as the fallback, so a failed read is inspectable"))

    def test_a_blank_column_is_called_out_as_possibly_dummy(self):
        reading, _ = self.read({})
        self.assertIsNone(reading.clock)
        self.assertEqual(reading.text, "")
        self.assertTrue(
            any("SDL_VIDEODRIVER=dummy" in note
                for note in reading.notes),
            msg=("a black frame is the signature of the banned video "
                 "driver, and it must not pass as an unreadable "
                 "clock"))

    def test_reading_the_same_frame_twice_gives_the_same_answer(self):
        first, _ = self.read({"deslash-rows": CLEAN_CLOCK})
        second, _ = self.read({"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_no_value_is_carried_from_one_frame_to_the_next(self):
        # THE statelessness proof.  A readable frame between two
        # unreadable ones must not leak into either of them, in either
        # direction: that leak is the difference between a null reading
        # and a fabricated one.
        sequence = [{}, {"deslash-rows": CLEAN_CLOCK}, {},
                    {"deslash-rows": IMPOSSIBLE_CLOCK}]
        expected = [None, CLEAN_CLOCK, None, None]
        observed = [self.read(texts)[0].clock for texts in sequence]
        self.assertEqual(observed, expected)
        again = [self.read(texts)[0].clock
                 for texts in reversed(sequence)]
        self.assertEqual(
            again, list(reversed(expected)),
            msg="and the order the frames are read in changes nothing")

    def test_the_only_module_state_holds_no_reading(self):
        self.read({"deslash-rows": CLEAN_CLOCK})
        self.assertNotIn(
            CLEAN_CLOCK, "".join(str(item) for item in
                                 ocr_clock._WARNED),
            msg=("_WARNED de-duplicates environmental complaints; it "
                 "must never hold a value read from a frame"))

    def test_an_empty_pass_argument_is_refused(self):
        # An explicitly empty sequence is not 'no preference' -- it asks
        # for no OCR at all, which can only report every frame as
        # unreadable.  Defaulting it would silently make the caller's
        # error look like a session without a watch, so only None means
        # 'use the documented table'.
        with self.assertRaises(ocr_clock.OcrClockError) as bad:
            self.read({"deslash-rows": CLEAN_CLOCK}, passes=())
        self.assertIn("nothing would be read", str(bad.exception))

    def test_a_read_with_no_passes_at_all_is_a_fault(self):
        # Reachable only if the module's own PASSES table were emptied,
        # which is exactly the regression the guard exists for: reading
        # nothing must be an error, never an unreadable frame.
        context, _ = self.fake_pipeline({})
        with context, _patched(ocr_clock, PASSES=()):
            with self.assertRaises(ocr_clock.OcrClockError) as bad:
                ocr_clock.read_sidebar(
                    self.frame, rect=CROP, row_height=ROW_HEIGHT,
                    check_options=False, frames_dir=self.frames,
                    passes=None)
        self.assertIn("no OCR pass", str(bad.exception))

    def test_an_explicit_pass_list_is_honoured(self):
        only = (ocr_clock.PASSES[-1],)
        reading, seen = self.read(
            {"deslash-negate-rows": CLEAN_CLOCK}, passes=only)
        self.assertEqual(seen, ["deslash-negate-rows"])
        self.assertEqual(reading.clock, CLEAN_CLOCK)

    def test_the_crop_and_the_engines_are_recorded_on_the_reading(self):
        reading, _ = self.read({"deslash-rows": CLEAN_CLOCK},
                               engine=ocr_clock.ENGINE_PILLOW)
        self.assertEqual(reading.rect, CROP)
        self.assertEqual(reading.engine, ocr_clock.ENGINE_PILLOW)
        self.assertIn(reading.ocr_engine, ocr_clock.OCR_ENGINES)
        self.assertEqual(reading.png, os.path.realpath(self.frame))

    def test_the_thin_views_return_exactly_one_field_each(self):
        column = "%s\n%s\n%s" % (DATE_LINE, CLEAN_CLOCK, PHRASE)
        texts = {"deslash-rows": column}
        context, _ = self.fake_pipeline(texts)
        arguments = {"rect": CROP, "row_height": ROW_HEIGHT,
                     "check_options": False,
                     "frames_dir": self.frames}
        with context:
            self.assertEqual(
                ocr_clock.read_clock(self.frame, **arguments),
                CLEAN_CLOCK)
            self.assertEqual(
                ocr_clock.read_time_phrase(self.frame, **arguments),
                PHRASE)
            self.assertEqual(
                ocr_clock.read_date_line(self.frame, **arguments),
                DATE_LINE)

    def test_the_secondary_readers_do_not_require_the_24_hour_value(self):
        # A misconfigured clock format must not stop a phrase from
        # being read honestly: the option is irrelevant to a phrase.
        parser = ocr_clock.read_time_phrase.__defaults__
        self.assertIn(
            False, parser,
            msg="check_options defaults to False for the phrase reader")
        path = self.options_file({"24_HOUR": "military"})
        context, _ = self.fake_pipeline(
            {"deslash-rows": PHRASE, "reference-rows": PHRASE,
             "reference-column": PHRASE,
             "deslash-negate-rows": PHRASE})
        with context:
            self.assertEqual(
                ocr_clock.read_time_phrase(
                    self.frame, rect=CROP, row_height=ROW_HEIGHT,
                    options_json=path, frames_dir=self.frames),
                PHRASE)
            with self.assertRaises(ocr_clock.OptionsError):
                ocr_clock.read_clock(
                    self.frame, rect=CROP, row_height=ROW_HEIGHT,
                    options_json=path, frames_dir=self.frames)

    def test_a_fault_is_raised_and_never_returned_as_a_reading(self):
        context, _ = self.fake_pipeline({})
        with context:
            with self.assertRaises(ocr_clock.FrameMissingError):
                ocr_clock.read_clock(
                    os.path.join(self.frames, "frame_09999.png"),
                    rect=CROP, row_height=ROW_HEIGHT,
                    check_options=False, frames_dir=self.frames)

    def test_a_frame_outside_the_capture_directory_can_be_refused(self):
        outside = os.path.join(self.root, "hand_picked.png")
        with open(outside, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
        context, _ = self.fake_pipeline({"deslash-rows": CLEAN_CLOCK})
        with context:
            self.assertEqual(
                ocr_clock.read_clock(
                    outside, rect=CROP, row_height=ROW_HEIGHT,
                    check_options=False, frames_dir=self.frames),
                CLEAN_CLOCK,
                msg="a warning by default, for debugging by hand")
            with self.assertRaises(ocr_clock.FramePathError):
                ocr_clock.read_clock(
                    outside, rect=CROP, row_height=ROW_HEIGHT,
                    check_options=False, frames_dir=self.frames,
                    strict_path=True)


class TestTheCommandLine(OcrFixture):
    """Three exit codes, kept strictly apart, and a bare stdout."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.reset_log)

    def reset_log(self):
        """Undo the CLI's handler installation."""
        for handler in list(ocr_clock.LOG.handlers):
            ocr_clock.LOG.removeHandler(handler)
        ocr_clock.LOG.addHandler(logging.NullHandler())
        ocr_clock.LOG.propagate = False

    def run_main(self, *argv, **kwargs):
        """Call main(argv) and return (status, stdout, stderr)."""
        texts = kwargs.pop("texts", None)
        out = io.StringIO()
        err = io.StringIO()
        context = contextlib.nullcontext()
        if texts is not None:
            context, _ = self.fake_pipeline(texts)
        with context, contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            status = ocr_clock.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def base(self, *extra):
        """The arguments every reading run needs in the fixture."""
        return (self.frame, "--rect", CROP,
                "--row-height", str(ROW_HEIGHT),
                "--frames-dir", self.frames,
                "--no-check-options") + extra

    def test_a_reading_exits_zero_with_only_the_value_on_stdout(self):
        status, out, _ = self.run_main(
            *self.base(), texts={"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(status, ocr_clock.EXIT_OK)
        self.assertEqual(
            out, CLEAN_CLOCK + "\n",
            msg=('CLOCK="$(ocr_clock.py "$FRAME")" must need no '
                 "parsing, no trimming and no decoration stripped"))

    def test_the_command_line_accepts_only_the_canonical_audit(self):
        """THE DEFECT THIS TEST EXISTS FOR.

        A security review published this reproduction:

            ocr_clock.py --audit playthrough/manifest.jsonl \\
                --audit-frame 99999 <frame>

        It appended an audit-shaped line to the record and exited
        reporting success, because the writer's rule was CONTAINMENT and
        the manifest is inside the tree -- as is every other artifact
        this pipeline produces.  The command line now names the sidecar
        it already knows, or nothing.
        """
        tooling = os.path.dirname(os.path.abspath(ocr_clock.__file__))
        expected = os.path.join(
            os.path.realpath(os.path.dirname(tooling)),
            *ocr_clock.DATE_AUDIT_REL_PARTS)
        for candidate in (os.path.join(self.root, "frame_dates.jsonl"),
                          "playthrough/manifest.jsonl",
                          "playthrough/transcript.srt",
                          "/tmp/frame_dates.jsonl"):
            with self.subTest(path=candidate):
                with self.assertRaises(SystemExit) as caught:
                    self.run_main(*self.base(
                        "--audit", candidate, "--audit-frame", "1"))
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(
            ocr_clock.canonical_audit_path(), expected,
            msg="and the one accepted path is derived, never read")

    def test_a_malformed_bound_digest_is_a_usage_error(self):
        for bad in ("nope", "AB" * 32, "ab" * 31):
            with self.subTest(digest=bad):
                with self.assertRaises(SystemExit) as caught:
                    self.run_main(*self.base(
                        "--audit", ocr_clock.canonical_audit_path(),
                        "--audit-frame", "1", "--audit-sha256", bad))
                self.assertEqual(caught.exception.code, 2)

    def test_the_bound_digest_needs_the_audit(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(*self.base("--audit-sha256", "a" * 64))
        self.assertEqual(caught.exception.code, 2)

    def test_an_unreadable_clock_exits_one_with_an_empty_stdout(self):
        status, out, _ = self.run_main(*self.base(), texts={})
        self.assertEqual(status, ocr_clock.EXIT_UNREADABLE)
        self.assertEqual(
            out, "",
            msg=("an unreadable clock yields an empty string, never a "
                 "plausible-looking placeholder"))

    def test_an_impossible_reading_also_exits_one_and_prints_nothing(self):
        status, out, _ = self.run_main(
            *self.base(), texts={"deslash-rows": IMPOSSIBLE_CLOCK})
        self.assertEqual(status, ocr_clock.EXIT_UNREADABLE)
        self.assertEqual(out, "")

    def test_a_missing_frame_exits_two(self):
        status, out, err = self.run_main(
            os.path.join(self.frames, "frame_09999.png"),
            "--rect", CROP, "--row-height", str(ROW_HEIGHT),
            "--frames-dir", self.frames, "--no-check-options")
        self.assertEqual(
            status, ocr_clock.EXIT_FAULT,
            msg=("capture.sh maps 2 onto a clock fault and 1 onto an "
                 "honest unreadable reading; conflating them would "
                 "corrupt the manifest"))
        self.assertEqual(out, "")
        self.assertIn("no such frame", err)

    def test_a_forbidden_clock_format_exits_two(self):
        path = self.options_file({"24_HOUR": "military"})
        status, out, err = self.run_main(
            self.frame, "--rect", CROP,
            "--row-height", str(ROW_HEIGHT),
            "--frames-dir", self.frames, "--options-json", path,
            texts={"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(status, ocr_clock.EXIT_FAULT)
        self.assertEqual(out, "")
        self.assertIn("0815.32", err)

    def test_an_unusable_crop_exits_two(self):
        status, out, err = self.run_main(
            self.frame, "--rect", "not-a-geometry",
            "--frames-dir", self.frames, "--no-check-options")
        self.assertEqual(status, ocr_clock.EXIT_FAULT)
        self.assertEqual(out, "")
        self.assertIn("WxH+X+Y", err)

    def test_a_missing_dependency_exits_two_rather_than_one(self):
        with _patched(ocr_clock, Image=None):
            status, out, err = self.run_main(*self.base())
        self.assertEqual(status, ocr_clock.EXIT_FAULT)
        self.assertEqual(out, "")
        self.assertIn("Pillow", err)

    def test_the_preflight_reports_the_toolchain_and_reads_nothing(self):
        status, out, _ = self.run_main("--preflight")
        self.assertEqual(status, ocr_clock.EXIT_OK)
        self.assertEqual(out, "")
        with _patched(ocr_clock, Image=None):
            status, out, err = self.run_main("--preflight")
        self.assertEqual(
            status, ocr_clock.EXIT_FAULT,
            msg=("run once before capturing, so a missing package is a "
                 "fault reported before any frame exists rather than "
                 "an unreadable clock reported for every frame"))
        self.assertIn("Pillow", err)

    def test_each_field_can_be_asked_for_on_its_own(self):
        column = "%s\n%s\n%s" % (DATE_LINE, CLEAN_CLOCK, PHRASE)
        texts = {"deslash-rows": column}
        for field, expected in (("clock", CLEAN_CLOCK),
                                ("phrase", PHRASE),
                                ("date", DATE_LINE)):
            with self.subTest(field=field):
                status, out, _ = self.run_main(
                    *self.base("--field", field), texts=texts)
                self.assertEqual(status, ocr_clock.EXIT_OK)
                self.assertEqual(out.strip(), expected)

    def test_the_raw_text_can_be_asked_for_too(self):
        status, out, _ = self.run_main(
            *self.base("--field", "text"),
            texts={"deslash-rows": "Str 8"})
        self.assertEqual(
            status, ocr_clock.EXIT_OK,
            msg=("the status describes the REQUESTED field: the text "
                 "was read, even though it held no clock"))
        self.assertEqual(out.strip(), "Str 8")

    def test_the_raw_text_of_a_blank_column_exits_one(self):
        status, out, _ = self.run_main(
            *self.base("--field", "text"), texts={})
        self.assertEqual(status, ocr_clock.EXIT_UNREADABLE)
        self.assertEqual(out, "")

    def test_a_field_that_is_absent_exits_one(self):
        status, out, _ = self.run_main(
            *self.base("--field", "date"),
            texts={"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(status, ocr_clock.EXIT_UNREADABLE)
        self.assertEqual(out, "")

    def test_the_whole_reading_can_be_printed_as_json(self):
        status, out, _ = self.run_main(
            *self.base("--json"),
            texts={"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(status, ocr_clock.EXIT_OK)
        record = json.loads(out)
        self.assertEqual(record["clock"], CLEAN_CLOCK)
        self.assertTrue(record["agreement"])
        self.assertEqual(record["pass"], "deslash-rows")

    def test_json_for_an_unreadable_frame_still_exits_one(self):
        status, out, _ = self.run_main(*self.base("--json"), texts={})
        self.assertEqual(status, ocr_clock.EXIT_UNREADABLE)
        self.assertIsNone(
            json.loads(out)["clock"],
            msg=("the record is complete and the status is honest at "
                 "the same time"))

    def test_the_explanation_goes_to_stdout_only_with_no_frame(self):
        status, out, err = self.run_main("--explain")
        self.assertEqual(status, ocr_clock.EXIT_OK)
        self.assertIn("the prescribed pipeline", out)
        status, out, err = self.run_main(
            *self.base("--explain"),
            texts={"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(status, ocr_clock.EXIT_OK)
        self.assertEqual(
            out, CLEAN_CLOCK + "\n",
            msg=("stdout carries the reading and nothing else when "
                 "there is a reading to carry"))
        self.assertIn("the prescribed pipeline", err)

    def test_a_frame_is_required_unless_the_pipeline_is_explained(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                ocr_clock.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_an_unknown_switch_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                ocr_clock.main(["--repair", self.frame])
        self.assertEqual(caught.exception.code, 2)

    def test_the_verbose_report_goes_to_stderr(self):
        status, out, err = self.run_main(
            *self.base("-v"), texts={"deslash-rows": CLEAN_CLOCK})
        self.assertEqual(out, CLEAN_CLOCK + "\n")
        self.assertIn("sidebar reading", err)
        self.assertIn("winning pass", err)

    def test_the_parser_defaults_are_the_pipeline_s(self):
        args = ocr_clock.build_parser().parse_args(["frame.png"])
        self.assertIsNone(args.rect)
        self.assertIsNone(args.row_height)
        self.assertIsNone(args.engine)
        self.assertIsNone(args.ocr_engine)
        self.assertEqual(args.field, "clock")
        self.assertTrue(args.check_options)
        self.assertFalse(args.cross_check)
        self.assertFalse(args.stop_early)
        self.assertFalse(args.strict_path)
        self.assertFalse(args.json)
        self.assertEqual(args.verbose, 0)

    def test_the_field_choices_are_the_four_readings(self):
        self.assertEqual(ocr_clock.FIELDS,
                         ("clock", "phrase", "date", "text"))

    def test_the_exit_codes_are_the_documented_three(self):
        self.assertEqual(
            (ocr_clock.EXIT_OK, ocr_clock.EXIT_UNREADABLE,
             ocr_clock.EXIT_FAULT), (0, 1, 2),
            msg="capture.sh switches on these exact numbers")


@unittest.skipUnless(
    _TOOLCHAIN_READY,
    "needs Pillow, data/font/Terminus.ttf and a tesseract front end")
class TestTheRealPipeline(OcrFixture):
    """Real pixels, real convert, real tesseract -- no substitution.

    Synthetic sidebars, rendered with the game's OWN 8x16 Terminus face
    at the row height the pipeline runs at, then read through the whole
    chain.  This is what keeps the substituted tests above honest: the
    orchestration they assert has to work on pixels too.
    """

    def render(self, name, rows, colour=(255, 255, 255)):
        """Draw text into the sidebar column of a black 1920x1080 frame.

        ``rows`` maps a zero-based text row to the line drawn on it, so
        a fixture reads like the sidebar it imitates.
        """
        font = ImageFont.truetype(TERMINUS, ROW_HEIGHT)
        image = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT),
                          (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for row, line in sorted(rows.items()):
            draw.text((1632, 4 + ROW_HEIGHT * row), line, font=font,
                      fill=colour)
        path = os.path.join(self.frames, name)
        image.save(path)
        return path

    def read_real(self, path, **kwargs):
        """Read a rendered frame through the real chain."""
        arguments = {"rect": CROP, "row_height": ROW_HEIGHT,
                     "check_options": False,
                     "frames_dir": self.frames, "full_scan": True}
        arguments.update(kwargs)
        return ocr_clock.read_sidebar(path, **arguments)

    def test_a_clean_clock_is_read_exactly_by_both_engines(self):
        path = self.render("frame_00010.png", {3: CLEAN_CLOCK})
        for engine in ocr_clock.ENGINES:
            with self.subTest(engine=engine):
                reading = self.read_real(path, engine=engine)
                self.assertEqual(
                    reading.clock, CLEAN_CLOCK,
                    msg=("the prescribed chain reads the game's own "
                         "face at its own row height"))
                self.assertEqual(reading.declined, ())

    def test_the_hours_the_engine_can_render_read_back(self):
        for clock in ("13:45:27", "11:22:33", "23:59:58", "14:37:41"):
            with self.subTest(clock=clock):
                path = self.render("frame_00011.png", {3: clock})
                self.assertEqual(self.read_real(path).clock, clock)

    def test_a_slashed_zero_is_read_exactly_and_never_repaired(self):
        # Terminus draws a slashed zero and every tesseract pass reads
        # it as an 8, so those passes really do yield 88:15:32 -- an
        # hour no clock can show, which is declined rather than
        # repaired into something plausible.  The glyph-grid pass reads
        # the same pixels against the very font that drew them and gets
        # the true value, which is why it runs first: an exact reading
        # is better than an honest refusal, and both beat a guess.
        path = self.render("frame_00012.png", {3: SLASHED_CLOCK})
        reading = self.read_real(path, cross_check=True)
        self.assertEqual(
            reading.clock, SLASHED_CLOCK,
            msg="the exact pass reads what the pixels actually say")
        self.assertEqual(reading.pass_name, ocr_clock.GLYPH_PASS_NAME)
        self.assertIn(ocr_clock.GLYPH_PASS_NAME, reading.passes_run)
        self.assertTrue(
            reading.declined,
            msg="the tesseract misreads are still reported, not hidden")
        for value in reading.declined:
            with self.subTest(value=value):
                self.assertFalse(ocr_clock.is_possible_clock(value))
        self.assertTrue(
            any("NOT repaired" in note for note in reading.notes),
            msg=repr(reading.notes))

    def test_the_exact_pass_spends_no_ocr_call_and_still_answers(self):
        path = self.render("frame_00021.png", {3: CLEAN_CLOCK})
        reading = self.read_real(path, full_scan=False)
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertEqual(reading.pass_name, ocr_clock.GLYPH_PASS_NAME)
        self.assertEqual(
            reading.ocr_calls, 0,
            msg=("matching the game's own font needs no OCR engine at "
                 "all, which is what makes it affordable per frame"))

    def test_the_grid_phase_is_measured_rather_than_assumed(self):
        # The crop's own y offset and the engine's character grid need
        # not share a phase -- on the capture host they differed by 14
        # pixels -- so a reader that assumed the crop's offset would
        # split every glyph across two bands and read nothing.
        path = self.render("frame_00022.png", {3: CLEAN_CLOCK})
        rect = ocr_clock.sidebar_geometry.Rect(288, 1072, 1632, 4 + 7)
        text = ocr_clock.read_column_by_glyphs(path, rect, ROW_HEIGHT, [])
        self.assertIn(CLEAN_CLOCK, text)

    def test_a_watchless_sidebar_reads_its_phrase_and_date(self):
        path = self.render("frame_00013.png",
                           {2: DATE_LINE, 5: PHRASE})
        reading = self.read_real(path)
        self.assertEqual(reading.phrase, PHRASE)
        self.assertEqual(reading.date, DATE_LINE)
        self.assertIsNone(
            reading.clock,
            msg="a phrase is a real reading, and it is not a clock")

    def test_a_black_frame_costs_no_ocr_calls_at_all(self):
        path = os.path.join(self.frames, "frame_00014.png")
        Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT),
                  (0, 0, 0)).save(path)
        reading = self.read_real(path)
        self.assertEqual(reading.text.strip(), "")
        self.assertEqual(
            reading.ocr_calls, 0,
            msg=("a flat band cannot hold a clock, so it is skipped "
                 "without an OCR call: on a blank frame the whole read "
                 "costs nothing"))
        self.assertIsNone(reading.clock)
        self.assertTrue(
            any("SDL_VIDEODRIVER=dummy" in note
                for note in reading.notes))

    def test_only_the_cropped_column_is_read(self):
        font = ImageFont.truetype(TERMINUS, ROW_HEIGHT)
        image = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT),
                          (0, 0, 0))
        draw = ImageDraw.Draw(image)
        # A clock drawn in the MAP area, well left of the sidebar.
        draw.text((100, 4 + ROW_HEIGHT * 3), CLEAN_CLOCK, font=font,
                  fill=(255, 255, 255))
        path = os.path.join(self.frames, "frame_00015.png")
        image.save(path)
        self.assertIsNone(
            self.read_real(path).clock,
            msg=("the crop is what makes the reading a reading of the "
                 "sidebar clock rather than of any digits on screen"))

    def test_stopping_early_still_finds_a_clock_above_the_date(self):
        path = self.render("frame_00016.png",
                           {2: DATE_LINE, 3: CLEAN_CLOCK})
        reading = self.read_real(path, full_scan=False)
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertLess(
            reading.ocr_calls,
            len(ocr_clock.PASSES) * (1072 // ROW_HEIGHT),
            msg="stopping early means fewer calls, not a worse answer")

    def test_a_crop_that_does_not_fit_the_frame_is_a_fault(self):
        path = self.render("frame_00017.png", {3: CLEAN_CLOCK})
        with self.assertRaises(ocr_clock.RectError) as bad:
            self.read_real(path, rect="288x1072+1700+4")
        self.assertIn(
            "does not fit inside", str(bad.exception),
            msg=("capture targets the X root, so a mismatch means the "
                 "crop was computed for another display"))

    def test_a_file_that_is_not_an_image_is_a_fault(self):
        with self.assertRaises(ocr_clock.OcrClockError):
            self.read_real(self.frame)

    def test_the_command_line_maps_real_readings_onto_real_codes(self):
        readable = self.render("frame_00018.png", {3: CLEAN_CLOCK})
        blank = os.path.join(self.frames, "frame_00019.png")
        Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT),
                  (0, 0, 0)).save(blank)
        cases = (
            (readable, ocr_clock.EXIT_OK, CLEAN_CLOCK + "\n"),
            (blank, ocr_clock.EXIT_UNREADABLE, ""),
        )
        for path, status, expected in cases:
            with self.subTest(frame=os.path.basename(path)):
                out = io.StringIO()
                err = io.StringIO()
                with contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(err):
                    observed = ocr_clock.main([
                        path, "--rect", CROP,
                        "--row-height", str(ROW_HEIGHT),
                        "--frames-dir", self.frames,
                        "--no-check-options"])
                self.assertEqual(observed, status)
                self.assertEqual(out.getvalue(), expected)
        self.reset_cli_log()

    def reset_cli_log(self):
        """Undo the handler main() installed on the module logger."""
        for handler in list(ocr_clock.LOG.handlers):
            ocr_clock.LOG.removeHandler(handler)
        ocr_clock.LOG.addHandler(logging.NullHandler())
        ocr_clock.LOG.propagate = False

    # The glyph reader's recognise-exactly-or-refuse contract is
    # asserted against the shipping decoder by
    # TestAGlyphIsRecognisedOrRefused below, on the real templates:
    # an exact match is a lookup, a near match is accepted only
    # inside its own unique-decoding radius, and a tie is refused
    # rather than settled by alphabet order.  The earlier tests here
    # exercised a provenance API the module no longer exposes, so
    # they were duplicate coverage of a replaced implementation.


class TestTheOneWriteIsConfined(OcrFixture):
    """The date-evidence sidecar is the only file this module writes.

    Everything else here reads: frames, the options file, the tools.
    The one write is append-only evidence about what the sidebar
    showed, and it is held to exactly the contract every other writer
    in this tree is held to -- inside the approved artifact root, no
    symbolic link on the path, and O_NOFOLLOW on the open so the gap
    between checking a path and opening it has no window in it.

    Without that, `--audit` accepted any path the caller named: a
    sidecar pointed at the manifest, at a frame or at the finished
    movie would have had a line of JSON appended to it while this
    module reported the record written.
    """

    def setUp(self):
        super().setUp()
        # THE SIDECAR HAS EXACTLY ONE PLACE INSIDE A TREE, and this
        # fixture nominates the tree rather than the file.  A security
        # review reproduced the alternative -- `--audit
        # playthrough/manifest.jsonl` appended an audit-shaped line to the
        # record and reported success -- so containment is no longer the
        # rule for this write; the exact relative name is.
        os.mkdir(os.path.join(self.root,
                              *ocr_clock.DATE_AUDIT_REL_PARTS[:-1]))
        self.audit = os.path.join(self.root,
                                  *ocr_clock.DATE_AUDIT_REL_PARTS)
        self.reading = ocr_clock.SidebarReading(
            png=self.frame, rect=None, clock="08:15:33", phrase=None,
            date="Thursday, Mar 8", text="08:15:33")

    def append(self, path, **extra):
        """Append one record, holding the writer to our own root."""
        return ocr_clock.append_date_audit(
            path, 1, self.reading, root=self.root, **extra)

    def test_a_record_lands_where_it_was_asked_to(self):
        record = self.append(self.audit)
        self.assertEqual(record["date"], "Thursday, Mar 8")
        self.assertEqual(record["clock"], "08:15:33")
        with open(self.audit, encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().splitlines()), 1)
        self.assertEqual(
            os.stat(self.audit).st_mode & 0o777, 0o600,
            msg="evidence is created private, like every other artifact")

    def test_the_sidecar_is_append_only(self):
        self.append(self.audit)
        ocr_clock.append_date_audit(self.audit, 2, self.reading,
                                    root=self.root)
        with open(self.audit, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('"frame": 1', lines[0])

    def test_a_path_outside_the_approved_root_is_refused(self):
        outside = os.path.join(
            tempfile.mkdtemp(prefix="blitzy_ocr_victim_"), "a.jsonl")
        self.addCleanup(shutil.rmtree, os.path.dirname(outside), True)
        for candidate in ("/etc/blitzy-audit.jsonl", "/dev/null",
                          outside):
            with self.subTest(path=candidate):
                with self.assertRaises(ocr_clock.AuditError):
                    self.append(candidate)
        self.assertFalse(os.path.exists(outside))

    def test_a_traversal_out_of_the_root_is_refused(self):
        escape = os.path.join(self.root, "..", "escaped.jsonl")
        with self.assertRaises(ocr_clock.AuditError):
            self.append(escape)
        self.assertFalse(os.path.exists(os.path.realpath(escape)))

    def test_a_symlinked_sidecar_is_refused_and_not_followed(self):
        """The link is planted AT the canonical name, on purpose.

        A link somewhere else would be caught by the exact-name check
        before the symlink check was reached, and this test's subject is
        the symlink handling.
        """
        victim = os.path.join(self.root, "manifest.jsonl")
        with open(victim, "w", encoding="utf-8") as handle:
            handle.write("this is another artifact\n")
        os.symlink(victim, self.audit)
        with self.assertRaises(ocr_clock.AuditError):
            self.append(self.audit)
        with open(victim, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "this is another artifact\n")

    def test_a_symlinked_component_is_refused(self):
        """Again at the canonical name: build/ itself is the link."""
        real = os.path.join(self.root, "real")
        os.mkdir(real)
        os.rmdir(os.path.dirname(self.audit))
        os.symlink(real, os.path.dirname(self.audit))
        with self.assertRaises(ocr_clock.AuditError):
            self.append(self.audit)
        self.assertEqual(
            os.listdir(real), [],
            msg="nothing may be appended through a linked directory")

    def test_a_directory_and_a_fifo_are_refused(self):
        os.mkfifo(self.audit)
        with self.assertRaises(ocr_clock.AuditError):
            self.append(self.audit)
        os.unlink(self.audit)
        os.mkdir(self.audit)
        with self.assertRaises(ocr_clock.AuditError):
            self.append(self.audit)

    def test_a_missing_parent_is_reported_not_created(self):
        os.rmdir(os.path.dirname(self.audit))
        with self.assertRaises(ocr_clock.AuditError):
            self.append(self.audit)
        self.assertFalse(
            os.path.exists(os.path.dirname(self.audit)),
            msg=("directory creation is playthrough_mkdirs()' job; a "
                 "mistyped path must not grow a second sidecar"))

    def test_only_the_canonical_name_is_accepted(self):
        """THE DEFECT THIS TEST EXISTS FOR.

        Every artifact of this pipeline lives inside the same tree, so a
        CONTAINED path is not a safe one for an append.  Each candidate
        below is inside the approved root and each names something that is
        not the sidecar.
        """
        for name in ("manifest.jsonl", "transcript.srt",
                     "cata-play.mp4", "amendments.jsonl",
                     os.path.join("build", "observations.jsonl"),
                     os.path.join("build", "frame_dates.json"),
                     os.path.join("frame_dates.jsonl")):
            candidate = os.path.join(self.root, name)
            parent = os.path.dirname(candidate)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with open(candidate, "w", encoding="utf-8") as handle:
                handle.write("this is another artifact\n")
            with self.subTest(path=name):
                with self.assertRaises(ocr_clock.AuditError) as caught:
                    self.append(candidate)
                self.assertIn("and to nothing else",
                              str(caught.exception))
                with open(candidate, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(),
                                     "this is another artifact\n")

    def test_the_canonical_path_is_derived_not_read(self):
        self.assertEqual(
            ocr_clock.canonical_audit_path(self.root), self.audit)
        tooling = os.path.dirname(os.path.abspath(ocr_clock.__file__))
        self.assertEqual(
            ocr_clock.canonical_audit_path(),
            os.path.join(os.path.realpath(os.path.dirname(tooling)),
                         *ocr_clock.DATE_AUDIT_REL_PARTS))

    def test_the_record_can_be_bound_to_the_capture_digest(self):
        """The reading names the pixels it was taken from."""
        digest = "a" * 64
        record = self.append(self.audit, frame_sha256=digest)
        self.assertEqual(record["frame_sha256"], digest)
        self.assertEqual(list(record), list(ocr_clock.DATE_AUDIT_FIELDS))

    def test_an_unbound_record_says_so_rather_than_guessing(self):
        record = self.append(self.audit)
        self.assertIsNone(
            record["frame_sha256"],
            msg=("a digest measured now and presented as one taken at "
                 "publication would be a fabrication; null is the "
                 "honest value"))

    def test_a_malformed_capture_digest_is_refused(self):
        for bad in ("not-a-digest", "AB" * 32, "ab" * 31, "ab" * 33, 7):
            with self.subTest(digest=bad):
                with self.assertRaises(ocr_clock.AuditError):
                    self.append(self.audit, frame_sha256=bad)
        self.assertFalse(os.path.exists(self.audit))

    def test_the_default_root_is_the_module_s_own_tree(self):
        tooling = os.path.dirname(os.path.abspath(ocr_clock.__file__))
        self.assertEqual(
            ocr_clock.approved_artifact_root(),
            os.path.realpath(os.path.dirname(tooling)),
            msg=("the root comes from this file's location, never from "
                 "the environment"))
        for bad in ("", "   ", os.path.join(self.root, "not-there")):
            with self.subTest(root=bad):
                with self.assertRaises(ocr_clock.AuditError):
                    ocr_clock.approved_artifact_root(bad)


class TestTheSuiteTouchesNoEvidence(unittest.TestCase):
    """The captured run's own frames are never read or written."""

    def test_the_committed_frames_directory_is_left_alone(self):
        frames = os.path.join(os.path.dirname(TOOLING), "frames")
        before = (sorted(os.listdir(frames))
                  if os.path.isdir(frames) else None)
        # Every fixture above writes inside a temporary directory; this
        # is the assertion that says so out loud.
        self.assertEqual(
            before,
            sorted(os.listdir(frames))
            if os.path.isdir(frames) else None)

    def test_the_module_needs_no_network_and_no_shell(self):
        source_path = os.path.join(TOOLING, "ocr_clock.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("shell=True", "os.system(", "eval(",
                          "urllib", "requests"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, source,
                    msg=("the CodeQL python leg scans this tree under "
                         "a no-new-alerts gate"))


@unittest.skipUnless(_TOOLCHAIN_READY, "needs Pillow and the font")
class TestAGlyphIsRecognisedOrRefused(unittest.TestCase):
    """The near-match rule must be UNIQUE, not merely nearest.

    The reader answers a cell by comparing it with a template rendered
    from the game's own font.  An exact match is a lookup and is not at
    issue.  The danger is the near match: measured on this checkout's
    Terminus.ttf at 8x16, '3' and '8' differ by only FOUR pixels and '.'
    and ',' by ONE, so a fixed four-pixel tolerance was wide enough for
    a smudged '3' to be answered with an '8' -- and a wrong clock is a
    wrong duration, a wrong caption and a wrong line in the transcript,
    with nothing downstream able to detect it.

    So a near match is accepted only inside its own unique-decoding
    radius, and a tie is refused outright rather than settled by
    alphabet order.  These tests assert that on the real templates.
    """

    def setUp(self):
        self.cell_width = CELL_WIDTH
        self.row_height = ROW_HEIGHT
        self.exact, self.ordered, self.neighbour = (
            ocr_clock._glyph_templates(self.cell_width, self.row_height))
        self.by_char = dict(self.ordered)

    def decode(self, cell, ambiguous=None):
        """Decode one cell by presenting it as a one-cell row."""
        return ocr_clock._decode_glyph_row(
            cell, self.exact, self.ordered, self.neighbour,
            self.cell_width, ambiguous)

    def test_the_measured_distances_the_rule_rests_on(self):
        # Not a tautology: these are the numbers that make a fixed
        # tolerance unsafe, so if the font ever changes such that they
        # grow, this test says so rather than letting the rationale rot.
        self.assertLessEqual(
            self.neighbour["3"], ocr_clock.GLYPH_MAX_DISTANCE,
            msg="'3' sits within the ceiling of another template")
        self.assertEqual(
            self.neighbour["."], 1,
            msg="'.' and ',' differ by a single pixel")

    def test_an_exact_cell_reads_as_itself(self):
        for character in "0123456789:":
            with self.subTest(character=character):
                self.assertEqual(
                    self.decode(self.by_char[character]), character)

    def test_a_cell_between_two_templates_is_refused(self):
        # Walk a '3' towards an '8' one differing pixel at a time and
        # stop where the two are equidistant.  That cell is a genuine
        # tie: it is EXACTLY as much an '8' as it is a '3'.
        three, eight = self.by_char["3"], self.by_char["8"]
        differing = numpy.argwhere(three != eight)
        self.assertTrue(len(differing) >= 2, "need a gap to walk")
        blend = three.copy()
        half = len(differing) // 2
        for row, column in differing[:half]:
            blend[row][column] = eight[row][column]
        to_three = int(numpy.count_nonzero(blend != three))
        to_eight = int(numpy.count_nonzero(blend != eight))
        self.assertEqual(to_three, to_eight, "the blend must be a tie")
        ambiguous = []
        self.assertEqual(self.decode(blend, ambiguous), "")
        self.assertTrue(
            ambiguous,
            msg="a refusal must be recorded, not silently absorbed")
        self.assertIn("not a unique match", ambiguous[0])

    def test_the_refusal_names_both_candidates(self):
        three, eight = self.by_char["3"], self.by_char["8"]
        differing = numpy.argwhere(three != eight)
        blend = three.copy()
        for row, column in differing[:len(differing) // 2]:
            blend[row][column] = eight[row][column]
        ambiguous = []
        self.decode(blend, ambiguous)
        self.assertRegex(ambiguous[0], r"pixel\(s\) from")

    def test_a_cell_outside_the_ceiling_is_refused(self):
        # Ink in a shape no template carries: far from everything.
        cell = numpy.zeros(
            (self.row_height, self.cell_width), dtype=bool)
        cell[::2, ::2] = True
        self.assertEqual(self.decode(cell), "")

    def test_an_empty_cell_is_a_space_not_a_guess(self):
        cell = numpy.zeros(
            (self.row_height, self.cell_width), dtype=bool)
        self.assertEqual(self.decode(cell), "")

    def test_every_template_pair_is_distinguishable_or_refused(self):
        # The invariant the rule guarantees: no cell can be accepted as
        # a glyph while lying inside another glyph's decoding radius.
        for character, mask in self.ordered:
            radius = (self.neighbour[character] - 1) // 2
            with self.subTest(character=character):
                self.assertLess(
                    radius * 2, max(self.neighbour[character], 1),
                    msg="the accepted radius must stay unique")

    def test_the_real_frames_still_read_exactly(self):
        # The tightening must not have cost a single real reading.
        manifest = os.path.join(
            REPO_ROOT, "playthrough", "manifest.jsonl")
        if not os.path.isfile(manifest):
            self.skipTest("no captured evidence in this checkout")
        rows = []
        with open(manifest, encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("ingame_clock"):
                    rows.append(row)
        if not rows:
            self.skipTest("no frame in the evidence carries a clock")
        rect = sidebar_geometry.Rect(
            x=1632, y=4, width=288, height=1072)
        checked = 0
        for row in rows[::max(1, len(rows) // 12)]:
            frame = os.path.join(REPO_ROOT, row["file"])
            if not os.path.isfile(frame):
                continue
            text = ocr_clock.read_column_by_glyphs(
                frame, rect, ROW_HEIGHT, [])
            with self.subTest(frame=row["frame"]):
                self.assertEqual(
                    ocr_clock.find_clocks(text)[0], row["ingame_clock"])
            checked += 1
        self.assertGreater(checked, 0, "no frame could be re-read")


class TestEveryImageComesThroughOneDoor(unittest.TestCase):
    """Pillow decodes only what has been proved to be a PNG.

    Pillow identifies a file by CONTENT and ships a plugin per format,
    so a plain ``Image.open`` on a path called frame_00001.png will hand
    a PSD, DDS, TIFF or FLI to that format's native decoder -- which is
    where Pillow's memory-corruption advisories live.  This pipeline
    runs Pillow 11.3.0, pinned there because moviepy 2.2.1 declares
    ``pillow<12.0``, so the format restriction IS the control rather
    than a belt over a fixed version.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_png_")
        self.addCleanup(shutil.rmtree, self.root, True)

    def path(self, name):
        return os.path.join(self.root, name)

    def test_the_module_opens_no_image_outside_the_doors(self):
        # The structural assertion: every Image.open in the module is
        # inside a door and every door names formats=["PNG"].
        source_path = os.path.join(TOOLING, "ocr_clock.py")
        with open(source_path, encoding="utf-8") as handle:
            lines = handle.readlines()
        opens = []
        for line in lines:
            stripped = line.strip()
            if "Image.open(" in line and not stripped.startswith("#"):
                opens.append(stripped)
        self.assertTrue(opens, "expected the doors themselves")
        for line in opens:
            with self.subTest(line=line):
                self.assertIn('formats=["PNG"]', line)

    def test_no_door_hands_a_pathname_to_the_decoder(self):
        """The check-to-use race, asserted structurally.

        A review found the provenance rule applied with `lstat` and the
        file then REOPENED BY NAME for the decode, so the bytes Pillow
        parsed were not the bytes that were validated.  Both doors decode
        an in-memory buffer now, so a `Image.open(path` anywhere in this
        module would be that defect coming back.
        """
        source_path = os.path.join(TOOLING, "ocr_clock.py")
        with open(source_path, encoding="utf-8") as handle:
            lines = handle.readlines()
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#") or "Image.open(" not in line:
                continue
            with self.subTest(line=number):
                self.assertIn("Image.open(io.BytesIO(", line,
                              "a decoder is being handed a pathname")

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_a_bmp_named_png_is_refused(self):
        target = self.path("frame_00001.png")
        Image.new("RGB", (4, 4), (9, 9, 9)).save(target, format="BMP")
        with self.assertRaises(ocr_clock.FrameUnreadableError):
            ocr_clock.open_png(target)

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_a_real_png_is_accepted_and_loaded(self):
        target = self.path("frame_00002.png")
        Image.new("L", (6, 5), 200).save(target, format="PNG")
        with ocr_clock.open_png(target) as image:
            self.assertEqual(image.size, (6, 5))

    def test_a_truncated_signature_is_refused(self):
        target = self.path("frame_00003.png")
        with open(target, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC[:4])
        with self.assertRaises(ocr_clock.FrameUnreadableError):
            ocr_clock.open_png(target)

    def test_bytes_that_are_not_a_png_are_refused(self):
        with self.assertRaises(ocr_clock.ToolchainError):
            ocr_clock.open_png_bytes(b"BM\x00\x00 not a png", "probe")

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_png_bytes_are_accepted(self):
        buffer = io.BytesIO()
        Image.new("L", (3, 2), 5).save(buffer, format="PNG")
        image = ocr_clock.open_png_bytes(buffer.getvalue(), "probe")
        self.assertEqual(image.size, (3, 2))

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_the_size_is_read_without_a_decoder(self):
        target = self.path("frame_00004.png")
        Image.new("RGB", (1920, 1080)).save(target, format="PNG")
        self.assertEqual(ocr_clock.png_size(target), (1920, 1080))

    def test_a_header_declaring_too_many_pixels_is_refused(self):
        # A crafted IHDR asking for an unbounded allocation never
        # reaches an allocator: the ceiling is checked on the declared
        # numbers, in pure Python.
        target = self.path("frame_00005.png")
        header = b"".join((
            ocr_clock.PNG_MAGIC,
            (13).to_bytes(4, "big"), b"IHDR",
            (100000).to_bytes(4, "big"),
            (100000).to_bytes(4, "big")))
        with open(target, "wb") as handle:
            handle.write(header)
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.png_size(target)
        self.assertIn("ceiling", str(caught.exception))

    def test_a_file_without_an_ihdr_chunk_is_refused(self):
        target = self.path("frame_00006.png")
        with open(target, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC + b"\x00" * 16)
        with self.assertRaises(ocr_clock.FrameUnreadableError):
            ocr_clock.png_size(target)


@unittest.skipUnless(os.path.isfile(TERMINUS), "needs the font")
class TestTheDecoderIsEnteredUnderConditions(unittest.TestCase):
    """The pin's own justification, made into a check.

    Pillow 11.3.0 is pinned because moviepy 2.2.1 declares
    ``pillow<12.0``, and 11.3.0 carries published advisories in native
    decoders first fixed across 12.1.1, 12.2.0 and 12.3.0 -- all of them
    above that cap.  requirements.txt enumerates them and accepts the
    risk on ONE stated ground: the only images this pipeline decodes are
    PNGs it captured itself, on the machine doing the decoding.

    A security review found the ground was not enforced -- 151 frames at
    mode 0666 and 15 directories at 02777, so any local account could
    substitute a crafted PNG between the capture and the decode.  The
    modes were repaired, but a mode set at creation is a fact about the
    past.  These tests are about the check that runs at the moment the
    bytes reach the parser.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_decode_")
        self.addCleanup(shutil.rmtree, self.root, True)

    def frame(self, name="frame_00001.png", mode=0o600):
        """A real, decodable PNG, owned by this account."""
        path = os.path.join(self.root, name)
        if Image is None:                       # pragma: no cover
            self.skipTest("needs Pillow")
        Image.new("RGB", (8, 8), (10, 20, 30)).save(path, "PNG")
        os.chmod(path, mode)
        return path

    # -- the door admits what it should ------------------------------

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_an_owner_only_capture_is_admitted(self):
        """The control must not refuse the ordinary case."""
        image = ocr_clock.open_png(self.frame())
        self.assertEqual(image.size, (8, 8))

    # -- and refuses each property, one at a time --------------------

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_a_world_writable_capture_is_refused(self):
        """The exact condition the review measured."""
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.open_png(self.frame(mode=0o666))
        self.assertIn("writable beyond its owner", str(caught.exception))

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_a_group_writable_capture_is_refused(self):
        """A group is still somebody else."""
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.open_png(self.frame(mode=0o660))
        self.assertIn("writable beyond its owner", str(caught.exception))

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_a_symlink_is_refused(self):
        """The name checked and the bytes decoded must be one decision."""
        target = self.frame()
        link = os.path.join(self.root, "link.png")
        os.symlink(target, link)
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.open_png(link)
        self.assertIn("symbolic link", str(caught.exception))

    def test_a_fifo_is_refused(self):
        """Reading it is an operation on something else entirely."""
        fifo = os.path.join(self.root, "fifo.png")
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.open_png(fifo)
        self.assertIn("not a regular file", str(caught.exception))

    @unittest.skipIf(Image is None, "needs Pillow")
    @unittest.skipIf(os.geteuid() != 0, "chown needs privilege")
    def test_a_capture_owned_by_another_account_is_refused(self):
        """Then its owner chooses what this decoder parses."""
        path = self.frame()
        os.chown(path, 12345, 12345)
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.open_png(path)
        self.assertIn("owned by uid 12345", str(caught.exception))

    def test_a_missing_file_says_so_before_decoding(self):
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.open_png(os.path.join(self.root, "absent.png"))
        self.assertIn("could not be examined", str(caught.exception))

    # -- one open, one fstat, one read --------------------------------

    @unittest.skipIf(Image is None, "needs Pillow")
    def test_the_verified_read_returns_the_bytes_it_validated(self):
        path = self.frame()
        with open(path, "rb") as handle:
            expected = handle.read()
        self.assertEqual(ocr_clock.read_verified_frame(path), expected)

    def test_the_verified_read_refuses_each_property(self):
        """The same rule, asked of the descriptor the bytes come from."""
        fifo = os.path.join(self.root, "fifo.png")
        os.mkfifo(fifo, 0o600)
        cases = [(fifo, "not a regular file"),
                 (os.path.join(self.root, "absent.png"),
                  "could not be examined")]
        if Image is not None:
            link = os.path.join(self.root, "link.png")
            os.symlink(self.frame(), link)
            cases.append((link, "symbolic link"))
            cases.append((self.frame(name="loose.png", mode=0o666),
                          "writable beyond its owner"))
        for path, expected in cases:
            with self.subTest(path=os.path.basename(path)):
                with self.assertRaises(
                        ocr_clock.FrameUnreadableError) as caught:
                    ocr_clock.read_verified_frame(path)
                self.assertIn(expected, str(caught.exception))

    def test_a_file_past_the_byte_ceiling_is_not_read_into_memory(self):
        """A planted enormous file is refused from its size alone."""
        path = os.path.join(self.root, "huge.png")
        with open(path, "wb") as handle:
            handle.write(ocr_clock.PNG_MAGIC)
            handle.truncate(ocr_clock.MAX_FRAME_BYTES + 1)
        os.chmod(path, 0o600)
        with self.assertRaises(ocr_clock.FrameUnreadableError) as caught:
            ocr_clock.read_verified_frame(path)
        self.assertIn("ceiling", str(caught.exception))

    def test_a_fifo_does_not_block_the_reader(self):
        """O_NONBLOCK is why this test can be written at all.

        Opening a fifo for reading blocks until a writer arrives, so the
        refusal has to happen without ever waiting for one -- a capture
        path replaced by a fifo would otherwise hang the pipeline instead
        of failing it.
        """
        fifo = os.path.join(self.root, "hang.png")
        os.mkfifo(fifo, 0o600)
        started = time.monotonic()
        with self.assertRaises(ocr_clock.FrameUnreadableError):
            ocr_clock.read_verified_frame(fifo)
        self.assertLess(time.monotonic() - started, 5.0)

    # -- the limits around the decode --------------------------------

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_a_core_dump_is_forbidden_during_a_decode(self):
        """A native crash must not write the frames to disk.

        The advisories the pinned Pillow carries are memory-safety ones,
        so a segfault mid-decode is the failure mode to plan for.  A core
        file would contain the decoded frame and everything else
        resident, and it lands wherever the host core pattern points --
        not a path this pipeline controls or cleans.
        """
        with ocr_clock.decode_limits():
            soft, _hard = resource.getrlimit(resource.RLIMIT_CORE)
        self.assertEqual(soft, 0)

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_cpu_time_is_bounded_during_a_decode(self):
        with ocr_clock.decode_limits():
            soft, _hard = resource.getrlimit(resource.RLIMIT_CPU)
        self.assertNotEqual(soft, resource.RLIM_INFINITY)

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_the_cpu_bound_is_relative_to_what_was_already_used(self):
        """RLIMIT_CPU is cumulative over the process, not per call.

        A fixed absolute value would fire partway through a long run for
        no reason at all, and a control that fires on legitimate work
        gets removed rather than fixed.
        """
        usage = resource.getrusage(resource.RUSAGE_SELF)
        used = int(usage.ru_utime + usage.ru_stime)
        with ocr_clock.decode_limits():
            soft, _hard = resource.getrlimit(resource.RLIMIT_CPU)
        self.assertGreaterEqual(soft, used + ocr_clock.DECODE_CPU_SECONDS)

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_every_limit_is_restored_afterwards(self):
        """Nothing here changes the process for the next stage."""
        before = [resource.getrlimit(limit) for limit in
                  (resource.RLIMIT_CORE, resource.RLIMIT_CPU)]
        with ocr_clock.decode_limits():
            pass
        after = [resource.getrlimit(limit) for limit in
                 (resource.RLIMIT_CORE, resource.RLIMIT_CPU)]
        self.assertEqual(before, after)

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_the_limits_are_restored_even_when_the_body_raises(self):
        before = resource.getrlimit(resource.RLIMIT_CORE)
        with self.assertRaises(ValueError):
            with ocr_clock.decode_limits():
                raise ValueError("the decode failed")
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CORE),
                         before)

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_a_tighter_existing_limit_is_left_alone(self):
        """An operator's own bound is a decision, not an obstacle.

        A guard that RAISED a limit somebody else had lowered would be a
        hole wearing the name of a control.
        """
        original = resource.getrlimit(resource.RLIMIT_CPU)
        self.addCleanup(resource.setrlimit, resource.RLIMIT_CPU,
                        original)
        tighter = 5
        resource.setrlimit(resource.RLIMIT_CPU, (tighter, original[1]))
        with ocr_clock.decode_limits():
            soft, _hard = resource.getrlimit(resource.RLIMIT_CPU)
        self.assertEqual(soft, tighter)

    @unittest.skipIf(resource is None, "needs POSIX resource limits")
    def test_a_real_decode_runs_and_leaves_no_trace_of_the_limits(self):
        """The guard is exercised through the door, not only directly."""
        before = resource.getrlimit(resource.RLIMIT_CORE)
        ocr_clock.open_png(self.frame())
        self.assertEqual(resource.getrlimit(resource.RLIMIT_CORE),
                         before)

    def test_the_address_space_is_deliberately_not_bounded(self):
        """A measurement, recorded as a test so it is not "fixed".

        RLIMIT_AS looks like the obvious control here and is useless for
        it, which is worth pinning down so a future reader does not add
        it back believing it does something.  Importing this module
        reserves about 2.6 GiB of virtual address space before any decode
        happens -- numpy accounts for roughly 2.5 GiB of it -- so a
        ceiling tight enough to bound a 64-megapixel decode refuses the
        import, and one loose enough to import bounds nothing.  Measured
        on this host: with RLIMIT_AS lowered to 300 MiB AFTER import, a
        full 1920x1080 decode still completed, because the limit
        constrains new mappings and the mappings were already made.

        The pixel ceiling is what bounds allocation instead, and it does
        it at the only layer that can tell a legitimate frame from a
        bomb.
        """
        limits = ocr_clock.decode_limits()
        names = [name for name, _value in limits._targets()]
        self.assertNotIn("RLIMIT_AS", names)
        self.assertIn("RLIMIT_CORE", names)
        self.assertIn("RLIMIT_CPU", names)
        self.assertEqual(ocr_clock.MAX_PIXELS, 64 * 1024 * 1024)


class TestTheFontIsTheOneThisRepositoryShips(unittest.TestCase):
    """FreeType is a native parser; the face it parses is attested.

    The font is named by a path derived from this module's location, so
    "the font we expect" is an assumption until the bytes are hashed.
    """

    def test_the_shipped_font_matches_the_recorded_digest(self):
        self.assertEqual(
            ocr_clock.font_digest(), ocr_clock.GLYPH_FONT_SHA256,
            msg=("data/font/Terminus.ttf does not match the digest this "
                 "module was written against; if it was legitimately "
                 "updated, update GLYPH_FONT_SHA256 deliberately and "
                 "re-verify the glyph templates"))

    def test_the_digest_is_of_the_font_this_module_resolves(self):
        resolved = ocr_clock._glyph_font_path()
        self.assertTrue(os.path.isfile(resolved))
        self.assertEqual(
            os.path.realpath(resolved), os.path.realpath(TERMINUS))

    @unittest.skipUnless(_TOOLCHAIN_READY, "needs Pillow")
    def test_a_font_that_is_not_the_attested_one_is_refused(self):
        holder = tempfile.mkdtemp(prefix="blitzy_font_")
        self.addCleanup(shutil.rmtree, holder, True)
        tampered = os.path.join(holder, "Terminus.ttf")
        with open(TERMINUS, "rb") as source:
            body = bytearray(source.read())
        body[-1] = (body[-1] + 1) % 256
        with open(tampered, "wb") as handle:
            handle.write(bytes(body))
        self.assertNotEqual(
            ocr_clock.font_digest(tampered),
            ocr_clock.GLYPH_FONT_SHA256)
        with _patched(ocr_clock, _glyph_font_path=lambda: tampered):
            ocr_clock._glyph_templates.cache_clear()
            self.addCleanup(ocr_clock._glyph_templates.cache_clear)
            with self.assertRaises(ocr_clock.ToolchainError) as caught:
                ocr_clock._attested_font(ROW_HEIGHT)
        self.assertIn("sha256", str(caught.exception))

    @unittest.skipUnless(_TOOLCHAIN_READY, "needs Pillow")
    def test_a_symlinked_font_is_refused(self):
        holder = tempfile.mkdtemp(prefix="blitzy_font_")
        self.addCleanup(shutil.rmtree, holder, True)
        link = os.path.join(holder, "Terminus.ttf")
        os.symlink(TERMINUS, link)
        with _patched(ocr_clock, _glyph_font_path=lambda: link):
            with self.assertRaises(ocr_clock.ToolchainError) as caught:
                ocr_clock._attested_font(ROW_HEIGHT)
        self.assertIn("regular file", str(caught.exception))


class TestReadersMustAgree(OcrFixture):
    """Disagreement withholds the reading; it never picks a winner.

    Two independent readers of the same pixels that return different
    times have established that the time is NOT established.  Choosing
    between them by pass order is choosing arbitrarily, and the wrong
    choice is undetectable downstream -- so the clock is reported as
    unreadable, which timeline.py reconciles and the manifest records
    as null.  capture.sh therefore always cross-checks.
    """

    def test_agreement_is_reported(self):
        reading, _ = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "08:15:32",
             "reference-column": "08:15:32",
             "deslash-negate-rows": "08:15:32"},
            cross_check=True)
        self.assertEqual(reading.clock, "08:15:32")
        self.assertEqual(reading.candidates, ("08:15:32",))

    def test_disagreement_withholds_the_clock(self):
        reading, seen = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "08:15:33"},
            cross_check=True)
        self.assertIsNone(
            reading.clock,
            msg="a disagreed reading must be withheld, not resolved")
        self.assertIsNone(reading.pass_name)
        self.assertEqual(len(seen), len(ocr_clock.PASSES),
                         msg="cross-check runs every pass")

    def test_disagreement_keeps_every_candidate_as_evidence(self):
        reading, _ = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "08:15:33"},
            cross_check=True)
        self.assertEqual(set(reading.candidates),
                         {"08:15:32", "08:15:33"})
        self.assertTrue(
            any("UNREADABLE" in note for note in reading.notes),
            msg="the withholding must be stated in the record")

    def test_disagreement_still_reports_the_text_it_read(self):
        reading, _ = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "08:15:33"},
            cross_check=True)
        self.assertTrue(reading.text.strip(),
                        msg="the pixels read stay in the record")

    def test_without_cross_check_the_first_pass_still_wins(self):
        # The flag controls whether we LOOK for disagreement.  Without
        # it the behaviour is unchanged: one pass answers and stops.
        reading, seen = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "08:15:33"})
        self.assertEqual(reading.clock, "08:15:32")
        self.assertEqual(seen, ["deslash-rows"])

    def test_an_impossible_reading_does_not_count_as_disagreement(self):
        # 48:85:89 is declined before it can ever be a candidate, so a
        # frame one pass misreads impossibly is still readable.
        reading, _ = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "48:85:89",
             "reference-column": "08:15:32",
             "deslash-negate-rows": "08:15:32"},
            cross_check=True)
        self.assertEqual(reading.clock, "08:15:32")
        self.assertIn("48:85:89", reading.declined)

    def test_a_withheld_reading_is_distinguishable_in_the_evidence(self):
        # Both a disagreed frame and a genuinely blank one carry a null
        # clock, and they are NOT the same event.  The audit sidecar
        # already separates them by `agreement`, which is what lets a
        # later reader tell "nobody could read it" from "the readers
        # contradicted each other", so the distinction is asserted here
        # rather than left to survive by luck.
        withheld, _ = self.read(
            {"deslash-rows": "08:15:32",
             "reference-rows": "08:15:33"},
            cross_check=True)
        blank, _ = self.read({}, cross_check=True)
        self.assertIsNone(withheld.clock)
        self.assertIsNone(blank.clock)
        withheld_record = ocr_clock.date_audit_record(1, withheld)
        blank_record = ocr_clock.date_audit_record(2, blank)
        self.assertFalse(withheld_record["agreement"])
        self.assertTrue(blank_record["agreement"])
        self.assertIsNone(withheld_record["clock"])
        self.assertIsNone(blank_record["clock"])

    def test_capture_asks_for_the_cross_check(self):
        # The production invocation, not just the capability.
        script = os.path.join(TOOLING, "capture.sh")
        with open(script, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("--cross-check", body,
                      msg=("capture.sh must cross-check, or a misread "
                           "by the first pass becomes the record"))


@unittest.skipUnless(
    _TOOLCHAIN_READY,
    "needs Pillow, data/font/Terminus.ttf and a tesseract front end")
class TestAProofOutranksAPreference(OcrFixture):
    """An exact glyph match stands against a disagreeing OCR pass.

    Withholding on disagreement is right when the disagreeing readers
    are all probabilistic.  It is WRONG when one of them is a proof: an
    exact glyph match means the cell's ink is bit-identical to what the
    attested data/font/Terminus.ttf draws for that character, so the
    engine demonstrably drew that time in those pixels.

    This is measured, not assumed.  Cross-checking the committed
    evidence turned up three frames where tesseract contradicted an
    exact match -- '19:40:10' against '15:28:18' on frame 501, and the
    like -- and in every case the contradiction was impossible in
    sequence against the neighbouring frames while the exact reading fit
    them precisely.  Discarding a proof because a probabilistic reader
    was noisy would throw away true observations, which is its own kind
    of dishonesty.

    So: proof wins, the contradiction is recorded, and `agreement`
    stays false so the evidence shows the frame was contested.
    """

    def render(self, name, rows):
        font = ImageFont.truetype(TERMINUS, ROW_HEIGHT)
        image = Image.new("RGB", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for row, line in sorted(rows.items()):
            draw.text((1632, 4 + ROW_HEIGHT * row), line, font=font,
                      fill=(255, 255, 255))
        path = os.path.join(self.frames, name)
        image.save(path)
        return path

    def read_with_ocr_saying(self, path, spoken):
        """Read real pixels while every OCR pass "reads" ``spoken``."""
        def preprocess(png_path, rect, row_height, ocr_pass, engine):
            return object(), row_height

        def scan(strip, band_height, ocr_pass, ocr_engine, stop_early):
            return spoken, 1

        with _patched(ocr_clock, preprocess=preprocess,
                      _scan_strip=scan):
            return ocr_clock.read_sidebar(
                path, rect=CROP, row_height=ROW_HEIGHT,
                check_options=False, frames_dir=self.frames,
                cross_check=True)

    def test_an_exact_match_stands_against_a_contradiction(self):
        path = self.render("frame_00020.png", {3: CLEAN_CLOCK})
        reading = self.read_with_ocr_saying(path, "13:45:28")
        self.assertEqual(
            reading.clock, CLEAN_CLOCK,
            msg="a bit-identical match is not overridden by OCR")
        self.assertEqual(reading.pass_name, ocr_clock.GLYPH_PASS_NAME)
        self.assertIn("13:45:28", reading.candidates)
        self.assertFalse(
            reading.agreement,
            msg="the frame was contested and the record must say so")
        self.assertTrue(
            any("STANDS" in note for note in reading.notes),
            msg=repr(reading.notes))

    def test_the_contradiction_is_named_in_the_record(self):
        path = self.render("frame_00021.png", {3: CLEAN_CLOCK})
        reading = self.read_with_ocr_saying(path, "13:45:28")
        self.assertTrue(
            any("13:45:28" in note for note in reading.notes),
            msg="the reading that was overruled stays visible")

    def test_agreement_survives_when_the_ocr_agrees(self):
        path = self.render("frame_00022.png", {3: CLEAN_CLOCK})
        reading = self.read_with_ocr_saying(path, CLEAN_CLOCK)
        self.assertEqual(reading.clock, CLEAN_CLOCK)
        self.assertTrue(reading.agreement)
        self.assertFalse(
            any("STANDS" in note for note in reading.notes),
            msg="an uncontested frame needs no adjudication note")

    def test_a_reading_that_is_not_a_proof_is_withheld(self):
        # Same contradiction, but the glyph pass contributes nothing --
        # so there is no proof to settle it and the reading is withheld.
        path = self.render("frame_00023.png", {})

        def preprocess(png_path, rect, row_height, ocr_pass, engine):
            return object(), row_height

        def scan(strip, band_height, ocr_pass, ocr_engine, stop_early):
            return ("13:45:27" if ocr_pass.name == "deslash-rows"
                    else "13:45:28"), 1

        with _patched(ocr_clock, preprocess=preprocess,
                      _scan_strip=scan):
            reading = ocr_clock.read_sidebar(
                path, rect=CROP, row_height=ROW_HEIGHT,
                check_options=False, frames_dir=self.frames,
                cross_check=True)
        self.assertIsNone(
            reading.clock,
            msg="without a proof, disagreement withholds the reading")
        self.assertTrue(
            any("UNREADABLE" in note for note in reading.notes),
            msg=repr(reading.notes))

    def test_exactness_is_tracked_per_character(self):
        path = self.render("frame_00024.png", {3: CLEAN_CLOCK})
        marks = []
        text = ocr_clock.read_column_by_glyphs(
            path,
            sidebar_geometry.Rect(width=288, height=1072, x=1632, y=4),
            ROW_HEIGHT, [], marks)
        self.assertEqual(
            len(marks), len(text),
            msg="the mark list must index the text directly")
        start = text.find(CLEAN_CLOCK)
        self.assertGreaterEqual(start, 0)
        self.assertTrue(all(marks[start:start + len(CLEAN_CLOCK)]))

    def test_a_value_that_cannot_be_located_is_not_a_proof(self):
        self.assertFalse(ocr_clock._all_exact("abc", "zz", [True] * 3))
        self.assertFalse(ocr_clock._all_exact("abc", "", [True] * 3))
        self.assertFalse(
            ocr_clock._all_exact("abc", "a", [True]),
            msg="a mark list that does not index the text is refused")
        self.assertTrue(
            ocr_clock._all_exact("abc", "b", [True, True, True]))
        self.assertFalse(
            ocr_clock._all_exact("abc", "b", [True, False, True]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
