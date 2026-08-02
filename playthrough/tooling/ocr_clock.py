#!/usr/bin/env python3
"""Read the Cataclysm-DDA sidebar clock out of a captured frame.

Crop the computed sidebar column out of a captured PNG, preprocess it
for legibility, run OCR over it, extract the clock by regular
expression, and return the matched string -- or NOTHING AT ALL.

THE HONESTY CONTRACT
This module is the single place where "never fabricate" is enforced in
code.  Everything downstream -- every frame duration, the pacing of the
movie, the caption timings, the honesty of the whole film -- rests on
it never inventing a number.  Therefore:

  * a genuine ``HH:MM:SS`` reading is returned verbatim;
  * anything else returns ``None``: never ``"00:00:00"``, never the
    previous frame's value, never an interpolation, and never a repair
    of a partial match such as ``08:1S:32``;
  * this module is STATELESS.  It holds no reading from one call to the
    next, so it CANNOT silently continue a sequence.  Reconciling a
    missing or non-monotonic reading is ``timeline.py``'s job, and it
    happens downstream, visibly, against the previous frame;
  * a genuine fault RAISES: a missing input file, an unreadable file, a
    path outside the frames directory under a strict caller, an absent
    toolchain, a misconfigured ``24_HOUR`` option.  Only a genuinely
    unreadable clock is allowed to be quiet, and even then it is an
    explicit ``None`` that ``manifest.py`` records as JSON ``null``.

THE REFERENCE PIPELINE
The preprocessing chain is prescribed, and this is its canonical
shell form::

    convert "$FRAME" -crop "$RECT" +repage -colorspace Gray \\
        -resize 200% -normalize png:- \\
      | tesseract stdin stdout \\
      | grep -Eo '[0-9]{2}:[0-9]{2}:[0-9]{2}'

Every operator is load-bearing and none is dropped or reordered here.
``-crop "$RECT" +repage`` takes the sidebar column and resets the
virtual canvas; ``-colorspace Gray`` removes chroma noise from coloured
text on a dark background; ``-resize 200%`` enlarges 8x16 terminal
glyphs, which tesseract cannot read at native size; ``-normalize``
stretches contrast so the strokes separate from the background.
``$RECT`` is COMPUTED at run time by :mod:`sidebar_geometry` -- never
hard-coded -- and evaluates to ``288x1072+1632+4`` for the
configuration this pipeline runs under.

TWO MEASURED REFINEMENTS, AND THE EVIDENCE FOR THEM
Both were measured against a real captured 1920x1080 frame whose
sidebar clock was read directly off the pixels, magnified 800%, as
``08:00:00``.  That observation is the authority; the OCR is the assist.

1.  ROW-WISE OCR.  Applied to the whole column at once, the chain
    yields NO ``[0-9]{2}:[0-9]{2}:[0-9]{2}`` match at all: tesseract's
    layout analysis mangles the clock line into ``48:48; 48``.  Across
    thirty-two whole-column configurations (four resample filters, two
    scales, two crop widths, page-segmentation modes 3 and 6) only two
    matched, and both matched WRONGLY (``48:48:48``, ``88:48:48``).
    Applied to the single 16 px clock row with ``--psm 7`` -- one text
    line -- the same chain reads ``08:00:08``.  Rows are therefore read
    one text row at a time, and each row is normalised locally: a
    column-global ``-normalize`` leaves the clock dim and kills the
    match.  All rows are still scanned and the clock is still located
    BY REGEX, never at a fixed ``y``; see "Finding the row" below.

2.  ONE APPENDED OPERATOR, ``-gaussian-blur 0x0.5``.  The game's
    Terminus face draws a SLASHED ZERO, and tesseract 5.5.0 reads that
    slash as an ``8``: hence ``08:00:08`` for a clock that says
    ``08:00:00``.  A half-pixel blur after ``-normalize`` softens the
    slash and the same row then reads ``08:00:00`` exactly -- confirmed
    at ``0x0.5`` and ``0x0.8``, and at 600% with ``0x2``.  Nothing is
    dropped or reordered: the four prescribed operators remain, in
    order, and this is appended after them.  The unblurred chain is
    still run, as its own pass, so the prescribed form is exercised on
    every frame that the blurred form cannot read.

The passes are ordered, documented and deterministic (:data:`PASSES`).
``cross_check=True`` runs all of them and reports whether they agree,
which is how a slashed-zero style misread becomes visible rather than
authoritative.

IMPOSSIBLE READINGS ARE DECLINED, NOT REPAIRED
``48:48:48`` matches the pattern but cannot be a clock: the engine
cannot render hour 48.  Such a reading is declined with a warning and
the search continues through the same real OCR output.  Declining is
not repair -- no digit is ever substituted, no value is ever
reconstructed, and if nothing possible is found the answer is ``None``.

FINDING THE ROW
``sidebar_geometry`` returns the WHOLE sidebar column, because the
clock's row cannot be derived from configuration: it is drawn by the
``time_desc_label`` widget bound to ``time_text``
[data/json/ui/time.json:2-8] at whatever position the enclosing
``custom_sidebar`` ``widgets`` array puts it
[data/json/ui/sidebar.json:3-40], and eight distinct sidebar widths
ship in ``data/json/ui``.  Every row of the column is therefore read
and the clock is located by pattern inside the OCR text.  When more
than one possible clock appears, the FIRST in reading order (top row
to bottom row, left to right within a row) wins; that rule is fixed
here so the same PNG always reads the same way.

WHAT THE ENGINE CAN LEGITIMATELY RENDER
``display::time_string( const Character &u )``
[src/display.cpp:207-218] renders one of three things:

  * with a watch, an exact time from ``to_string_time_of_day()``;
  * otherwise, if the survivor can see the sky, a coarse phrase from
    ``display::time_approx()`` [src/display.cpp:159-186];
  * otherwise ``"???"`` [src/display.cpp:216].

The coarse phrases and ``"???"`` are REAL READINGS, not failures, so
:func:`read_time_phrase` returns them verbatim for ``manifest.py`` to
record honestly -- while :func:`read_clock` still returns ``None``,
because they are not parseable clocks.  Second-resolution deltas
require a watch, and acquiring one is a character decision made in
play; this module never works around its absence.

A measured caveat on ``"???"``: the coarse phrases are words and OCR
reads them reliably, but three question marks rendered in the game's
8x16 face come back from tesseract 5.5.0 as ``222?``, so a ``"???"``
sidebar usually reads as no phrase at all.  That is reported as
``None`` -- the honest answer, since the marker was not actually
recognised -- and never as an invented time.  The recogniser itself
handles the literal marker, so a cleaner render is reported verbatim.

WHY THE PATTERN IS EXACTLY ``[0-9]{2}:[0-9]{2}:[0-9]{2}``
``to_string_time_of_day()`` [src/calendar.cpp:638-663] branches three
ways on the ``24_HOUR`` option:

  * ``"military"`` -> ``"%02d%02d.%02d"``, e.g. ``0815.32``
    [src/calendar.cpp:646] -- which would silently defeat the pattern;
  * ``"24h"`` -> ``"%02d:%02d:%02d"`` [src/calendar.cpp:649], fixed
    width, the only OCR-friendly form;
  * otherwise ``"12h"``, the shipped default
    [src/options.cpp:1868-1877] -> ``"%d:%02d:%02d%sAM"`` or ``PM``
    with variable padding [src/calendar.cpp:657-661].

``seed_options.py`` sets ``24_HOUR=24h`` precisely so the pattern is
deterministic, and :func:`assert_24_hour_option` refuses to read
frames under any other value: ``military`` produces zero matches, so
every duration would collapse to the floor and the movie would look
plausible and mean nothing.  That is the failure mode this assertion
exists to make loud.

IMAGEMAGICK 6, NOT 7
The legacy ``convert`` and ``identify`` commands are called directly.
They exist on both the 6.x and 7.x branches, whereas the unified
version-7 entry point does not exist on 6.x at all, where this
pipeline is specified to run.  Code written against version-7 examples
fails there with a command-not-found error.

READ-ONLY, OFFLINE, NO SHELL
Nothing here writes to disk.  The frame and the game-written
``options.json`` are opened for reading only; no game state, save file
or memory is ever consulted -- the clock comes from rendered pixels
and nothing else.  Every external command is run through
``subprocess.run([...])`` with an argument LIST and a timeout, never
through a shell and never with a command assembled by string
interpolation; nothing is evaluated or executed dynamically, no path is
joined without validation, and there is no network surface of any kind.

USAGE
    $ python3 playthrough/tooling/ocr_clock.py \\
          playthrough/frames/frame_00042.png
    08:00:00

    $ python3 playthrough/tooling/ocr_clock.py --field date FRAME
    Thursday, Dec 21

    >>> import ocr_clock
    >>> ocr_clock.read_clock("playthrough/frames/frame_00042.png")
    '08:00:00'

Standard output carries exactly the reading and nothing else, so
``CLOCK="$(ocr_clock.py "$FRAME")"`` is safe; an unreadable clock
prints nothing and exits 1, and a fault prints a diagnosis on stderr
and exits 2.  Every warning, note and derivation goes to stderr, which
keeps engineering observations out of the in-character record.

Diagnostic level is calibrated so that the noisy case stays quiet:
anything MISCONFIGURED or suspicious -- an off-contract ``24_HOUR``, a
crop that read no pixels at all, OCR passes that disagree, a reading
declined as impossible -- is a warning and needs no logging setup,
while an ORDINARY unreadable frame, which is what most menu keystrokes
capture, is explained at INFO and surfaces with ``-v``.
"""
import argparse
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

from PIL import Image, ImageFilter, ImageOps

try:
    import pytesseract
except ImportError:  # pragma: no cover - exercised only without the pin
    pytesseract = None

try:
    import sidebar_geometry
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sidebar_geometry

LOG = logging.getLogger("playthrough.ocr_clock")

# ---------------------------------------------------------------------
# What the engine can render, cited to the line that renders it.
#
# These constants are re-declared here rather than imported because
# this module's declared internal dependency is sidebar_geometry alone.
# manifest.py carries the same vocabulary for the same reason; the two
# are kept in step by citing one source of truth -- the engine.
# ---------------------------------------------------------------------

# The contracted reading under 24_HOUR=24h: fixed-width
# "%02d:%02d:%02d" [src/calendar.cpp:649].  UNANCHORED on purpose --
# it is searched for inside OCR text that also holds the rest of the
# sidebar.
CLOCK_RE = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}")

# The two other shapes to_string_time_of_day() can emit, used ONLY to
# explain a failed read, never to produce a return value: "military"
# "%02d%02d.%02d" [src/calendar.cpp:646] and the 12h default
# "%d:%02d:%02d%sAM/PM" [src/calendar.cpp:657-661].
MILITARY_RE = re.compile(r"[0-9]{4}\.[0-9]{2}")
TWELVE_HOUR_RE = re.compile(r"[0-9]{1,2}:[0-9]{2}:[0-9]{2} ?[AP]M")

# An hour, minute and second the engine could actually have rendered.
# hour_of_day is 0-23 and minute_of_hour and the seconds term are
# 0-59 [src/calendar.cpp:640-642], so 48:48:48 -- a real OCR reading of
# a real frame, measured on this host -- is impossible and is declined.
MAX_HOUR = 23
MAX_MINUTE = 59
MAX_SECOND = 59

# display::time_approx() [src/display.cpp:159-186], verbatim and in
# source order.  A reading that is one of these is a genuine
# observation of a watchless survivor's sidebar, not a failure.
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

# What time_string() renders when there is no watch and no sky
# [src/display.cpp:216].
UNKNOWN_TIME_TEXT = "???"

# display::date_string() [src/display.cpp:193-205] renders either
# "<Season>, day <N>" -- when the year is not 364 days or SHOW_MONTHS
# is off -- or "<Weekday>, <Month> <day>", SHOW_MONTHS defaulting to
# true [src/options.cpp:1878-1880].  The vocabularies come from
# calendar::name_season() [src/calendar.cpp:761-780], to_string( const
# weekdays & ) [src/weather.cpp:495-507] and to_string( month )
# [src/calendar.cpp:910-928], whose month names are abbreviated and
# whose unknown month is "Cataclysm".
SEASON_NAMES = ("Spring", "Summer", "Autumn", "Winter", "End times")
WEEKDAY_NAMES = (
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday",
)
MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
    "Oct", "Nov", "Dec", "Cataclysm",
)
DATE_MONTH_RE = re.compile(
    r"\b(?:%s), (?:%s) [0-9]{1,2}\b"
    % ("|".join(WEEKDAY_NAMES), "|".join(MONTH_NAMES)))
DATE_SEASON_RE = re.compile(
    r"\b(?:%s), day [0-9]{1,3}\b" % "|".join(SEASON_NAMES))

# ---------------------------------------------------------------------
# The 24_HOUR contract
# ---------------------------------------------------------------------
OPT_24_HOUR = "24_HOUR"
OPT_24_HOUR_REQUIRED = "24h"
OPT_24_HOUR_MILITARY = "military"
OPT_24_HOUR_12H = "12h"

# ---------------------------------------------------------------------
# Preprocessing
#
# The prescribed chain, plus the one appended operator the measurement
# in this module's docstring justified.  These are the exact strings
# handed to convert as separate argv entries.
# ---------------------------------------------------------------------
CONVERT_BIN = "convert"
TESSERACT_BIN = "tesseract"

# The prescribed enlargement, in the two forms the two engines need.
# THEY MUST AGREE: RESIZE_PERCENT is what convert is told and
# SCALE_FACTOR is how the band offsets are computed afterwards, so a
# mismatch would slice the strip between text rows and read nothing.
# The agreement is asserted by this module's tests rather than trusted.
RESIZE_PERCENT = "200%"
SCALE_FACTOR = 2

# The one appended operator, and the measurement that earned it: the
# game's Terminus face draws a slashed zero that tesseract 5.5.0 reads
# as an 8, and half a pixel of blur after -normalize turns a real
# frame's "08:00:08" misread into the "08:00:00" the pixels actually say.
DESLASH_BLUR = "0x0.5"

# The Pillow equivalent of the appended blur.  Measured on the same
# real frame: radius 0.8-1.0 reproduces a match where radius 0.5 does
# not, so the two engines are equivalent in kind rather than in
# arithmetic, and the difference is recorded in ENGINE_NOTES.
PILLOW_BLUR_RADIUS = 0.9

# Page-segmentation modes.  7 is "treat the image as a single text
# line", which is exactly what one sidebar text row is; 3 is
# tesseract's default full-page analysis, used for the whole-column
# pass so the prescribed pipeline is reproduced literally.
PSM_SINGLE_LINE = 7
PSM_FULL_PAGE = 3

# FONT_HEIGHT's documented default [src/options.cpp:2435-2438], used
# only when the real value cannot be resolved, and never silently.
DEFAULT_ROW_HEIGHT = 16

# Wall-clock ceilings for the two external commands.  A hung tool is a
# fault to report, not a reason to wait forever.
CONVERT_TIMEOUT = 180
TESSERACT_TIMEOUT = 180

ENGINE_CONVERT = "convert"
ENGINE_PILLOW = "pillow"
ENGINES = (ENGINE_CONVERT, ENGINE_PILLOW)
ENGINE_NOTES = {
    ENGINE_CONVERT:
        "ImageMagick 'convert' runs the prescribed chain literally and "
        "read the calibration frame's clock exactly right",
    ENGINE_PILLOW:
        "Pillow reproduces the chain in kind (crop, L, 200%, "
        "autocontrast, blur); on the calibration frame it read one "
        "digit of the slashed zero wrong, so it is the fallback",
}

OCR_PYTESSERACT = "pytesseract"
OCR_TESSERACT = "tesseract"
OCR_ENGINES = (OCR_PYTESSERACT, OCR_TESSERACT)

# The prescribed shell form, kept verbatim for --explain and for
# anyone reproducing a single frame by hand.
REFERENCE_PIPELINE = (
    'convert "$FRAME" -crop "$RECT" +repage -colorspace Gray '
    '-resize 200% -normalize png:- \\\n'
    '  | tesseract stdin stdout \\\n'
    "  | grep -Eo '[0-9]{2}:[0-9]{2}:[0-9]{2}'"
)

# ---------------------------------------------------------------------
# Frame paths
#
# Joined from literal components onto a directory that is either
# exported by env.sh or derived from this file's own location, so that
# no caller-supplied fragment is ever concatenated into a path.  A
# caller who wants a different frame passes the whole path, which is
# resolved, checked for containment and checked for existence.
# ---------------------------------------------------------------------
ENV_FRAMES_DIR = "PLAYTHROUGH_FRAMES_DIR"
FRAMES_REL_PARTS = ("playthrough", "frames")
FRAMES_DIR_NAME = "frames"
PNG_SUFFIX = ".png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# An ImageMagick geometry, the form sidebar_geometry prints and the
# only textual rectangle accepted here.
GEOMETRY_RE = re.compile(r"^([0-9]+)x([0-9]+)\+([0-9]+)\+([0-9]+)$")

# CLI exit codes.  A quiet 1 means the frame was read and held no
# clock; a loud 2 means something is wrong with the setup.  They are
# distinct so a shell script can tell "no watch" from "no tesseract".
EXIT_OK = 0
EXIT_UNREADABLE = 1
EXIT_FAULT = 2


# ---------------------------------------------------------------------
# Faults
#
# Every one of these is LOUD.  None of them is raised because a clock
# could not be read -- that case returns None -- so catching
# OcrClockError never swallows an honest "unreadable".  The split
# matters operationally: a shell script can tell a misconfigured option
# from a missing tool from a bad path without parsing a message.
# ---------------------------------------------------------------------

class OcrClockError(Exception):
    """A fault that must not be mistaken for an unreadable clock."""


class FramePathError(OcrClockError):
    """The frame path is unusable or outside the frames directory."""


class FrameMissingError(OcrClockError):
    """The frame does not exist, so nothing was read at all.

    Distinct from an unreadable clock on purpose: a missing file is a
    programming or orchestration fault, and reporting it as ``None``
    would let a broken capture masquerade as a watchless survivor.
    """


class FrameUnreadableError(OcrClockError):
    """The file exists but is not a decodable PNG."""


class RectError(OcrClockError):
    """The crop rectangle could not be resolved or is malformed."""


class ToolchainError(OcrClockError):
    """A required external tool is absent or failed."""


class OptionsError(OcrClockError):
    """The game is configured so that the clock cannot be parsed.

    Raised when ``24_HOUR`` is not ``24h``.  ``military`` renders
    ``0815.32``, which matches nothing this module looks for, so every
    frame would report an unreadable clock, every duration would
    collapse to the floor, and the finished movie would look plausible
    and mean nothing.  That silent catastrophe is turned into a hard
    failure here.
    """


# ---------------------------------------------------------------------
# Diagnostics
#
# WARNING and above, on stderr, through logging.lastResort when no
# handler is configured -- so a fallback is visible to a human without
# corrupting the value a shell script just captured from stdout.
#
# _WARNED de-duplicates repeated environmental complaints across the
# hundreds of frames one session captures.  It is the module's ONLY
# state, it holds no reading, and it cannot influence a returned value:
# every read is computed from the frame in front of it.
# ---------------------------------------------------------------------

_WARNED = set()


def _warn(message: str, notes: Optional[List[str]] = None) -> None:
    """Announce a condition on stderr and record it in ``notes``."""
    LOG.warning("%s", message)
    if notes is not None:
        notes.append(message)


def _warn_once(key: str, message: str,
               notes: Optional[List[str]] = None) -> None:
    """Announce a repeating environmental condition once per process.

    The note is still recorded every time, so the record of an
    individual reading is complete even when the warning is quiet.
    """
    if key not in _WARNED:
        _WARNED.add(key)
        LOG.warning("%s", message)
    else:
        LOG.debug("%s", message)
    if notes is not None:
        notes.append(message)


def reset_diagnostics() -> None:
    """Forget which one-shot warnings have already been emitted.

    Provided for tests and for long-lived callers that want each
    session's diagnostics complete.  It clears warning bookkeeping
    only; there is no reading to reset, because none is ever kept.
    """
    _WARNED.clear()


# ---------------------------------------------------------------------
# The passes
#
# ORDERED, DOCUMENTED AND DETERMINISTIC.  Each pass is a genuine read
# of the same real pixels, differing only in preprocessing and in how
# tesseract is asked to segment them.  They are attempted in the order
# below and the first one that yields a POSSIBLE clock wins; with
# cross_check=True every pass runs and disagreement is reported instead
# of hidden.  Nothing here repairs, substitutes or interpolates.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class OcrPass:
    """One preprocessing-and-OCR configuration, by name."""

    name: str
    row_wise: bool
    psm: int
    deslash: bool
    negate: bool
    description: str


PASSES = (
    OcrPass(
        name="deslash-rows",
        row_wise=True,
        psm=PSM_SINGLE_LINE,
        deslash=True,
        negate=False,
        description=(
            "the prescribed chain plus -gaussian-blur 0x0.5, one text "
            "row at a time as a single line; measured to read the "
            "calibration frame's slashed-zero clock exactly right"),
    ),
    OcrPass(
        name="reference-rows",
        row_wise=True,
        psm=PSM_SINGLE_LINE,
        deslash=False,
        negate=False,
        description=(
            "the prescribed chain exactly, one text row at a time as a "
            "single line; measured to read the calibration frame's "
            "clock with one slashed zero as an 8"),
    ),
    OcrPass(
        name="reference-column",
        row_wise=False,
        psm=PSM_FULL_PAGE,
        deslash=False,
        negate=False,
        description=(
            "the prescribed chain over the whole column in one "
            "tesseract call, page segmentation left at the default; "
            "the literal shell pipeline, reproduced"),
    ),
    OcrPass(
        name="deslash-negate-rows",
        row_wise=True,
        psm=PSM_SINGLE_LINE,
        deslash=True,
        negate=True,
        description=(
            "as deslash-rows but inverted to dark-on-light, which "
            "tesseract prefers; the last resort for a frame whose "
            "contrast defeats the other three"),
    ),
)


# ---------------------------------------------------------------------
# The reading
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class SidebarReading:
    """Everything one frame's sidebar actually said, and how.

    Carrying the evidence beside the answer is what lets a caller -- or
    a reviewer -- confirm the reading was observed rather than assumed.
    :attr:`candidates` lists every distinct clock any pass read, in
    pass order, so a disagreement is inspectable; :attr:`agreement` is
    false exactly when there is more than one.  :attr:`clock` is the
    winning pass's reading, or ``None``.
    """

    png: str
    rect: str
    clock: Optional[str]
    phrase: Optional[str]
    date: Optional[str]
    text: str
    candidates: Tuple[str, ...] = ()
    declined: Tuple[str, ...] = ()
    passes_run: Tuple[str, ...] = ()
    pass_name: Optional[str] = None
    ocr_calls: int = 0
    engine: str = ENGINE_CONVERT
    ocr_engine: str = OCR_PYTESSERACT
    notes: Tuple[str, ...] = ()

    @property
    def agreement(self) -> bool:
        """True when no two passes read different clocks."""
        return len(self.candidates) < 2

    @property
    def readable(self) -> bool:
        """True when a possible clock was read from the pixels."""
        return self.clock is not None

    def as_dict(self) -> Dict[str, object]:
        """A JSON-serialisable record of the reading and its evidence."""
        return {
            "png": self.png,
            "rect": self.rect,
            "clock": self.clock,
            "phrase": self.phrase,
            "date": self.date,
            "candidates": list(self.candidates),
            "declined": list(self.declined),
            "agreement": self.agreement,
            "pass": self.pass_name,
            "passes_run": list(self.passes_run),
            "ocr_calls": self.ocr_calls,
            "engine": self.engine,
            "ocr_engine": self.ocr_engine,
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        """A human-readable account of the read, for stderr."""
        lines = [
            "sidebar reading",
            "  frame                 %s" % self.png,
            "  crop                  %s" % self.rect,
            "  preprocess engine     %s" % self.engine,
            "  ocr engine            %s" % self.ocr_engine,
            "  passes run            %s" % (
                ", ".join(self.passes_run) or "none"),
            "  ocr calls             %d" % self.ocr_calls,
            "  clock                 %s" % (
                self.clock if self.clock else "unreadable (None)"),
            "  winning pass          %s" % (self.pass_name or "none"),
            "  candidates            %s" % (
                ", ".join(self.candidates) or "none"),
            "  agreement             %s" % (
                "yes" if self.agreement else "NO"),
            "  time phrase           %s" % (self.phrase or "none"),
            "  date line             %s" % (self.date or "none"),
        ]
        if self.declined:
            lines.append("  declined as impossible: %s"
                         % ", ".join(self.declined))
        for note in self.notes:
            lines.append("  note: %s" % note)
        return "\n".join(lines)


# Everything :func:`resolve_rect` accepts.  A bare sequence is
# ``(width, height, x, y)`` -- the order of the geometry string, so
# that reading a call and reading the crop are the same exercise.
RectLike = Union[
    None,
    str,
    sidebar_geometry.Rect,
    sidebar_geometry.SidebarGeometry,
    Sequence[int],
]


# ---------------------------------------------------------------------
# Frame path validation
# ---------------------------------------------------------------------

def default_frames_dir() -> str:
    """Return the canonical capture directory, absolute.

    ``$PLAYTHROUGH_FRAMES_DIR`` from ``playthrough/tooling/env.sh``
    wins, so that a clone-indexed run and this module agree.  Otherwise
    the directory is derived from THIS FILE's location -- the sibling
    ``frames`` directory of ``playthrough/tooling`` -- which is correct
    in any checkout and needs no working directory.
    """
    from_env = os.environ.get(ENV_FRAMES_DIR)
    if from_env:
        return os.path.realpath(os.path.abspath(from_env))
    tooling = os.path.dirname(os.path.abspath(__file__))
    return os.path.realpath(
        os.path.join(os.path.dirname(tooling), FRAMES_DIR_NAME))


def _is_inside(path: str, directory: str) -> bool:
    """True when ``path`` lies within ``directory``.

    Both are fully resolved first, so a symlink or a ``..`` segment
    cannot smuggle a path past the check.
    """
    try:
        common = os.path.commonpath([path, directory])
    except ValueError:  # different drives, or a relative mix
        return False
    return common == directory


def validate_frame_path(
    png_path: str,
    frames_dir: Optional[str] = None,
    strict: bool = False,
    notes: Optional[List[str]] = None,
) -> str:
    """Resolve and check a frame path, or fail loudly.

    The checks, in order: the argument is a non-empty string; it names
    a ``.png``; it resolves inside the canonical frames directory; the
    file exists; it is a regular file; and it begins with the PNG
    signature.

    Containment is a WARNING by default rather than a refusal, because
    reading one arbitrary frame is exactly how a human debugs this
    module -- and ``main()`` says so on stderr when it happens.  Pass
    ``strict=True`` (``--strict-path`` on the command line) to refuse
    instead, which is what an automated caller should do.

    :returns: the resolved absolute path.
    :raises FramePathError: for an unusable path, or for a path outside
        ``frames_dir`` when ``strict`` is set.
    :raises FrameMissingError: when nothing is there to read.
    :raises FrameUnreadableError: when the file is not a PNG.
    """
    if not isinstance(png_path, str) or not png_path.strip():
        raise FramePathError(
            "a frame path must be a non-empty string, got %r" % png_path)

    resolved = os.path.realpath(
        os.path.abspath(os.path.expanduser(png_path)))

    if not resolved.lower().endswith(PNG_SUFFIX):
        raise FramePathError(
            "%s is not a %s; capture writes one PNG per keystroke and "
            "this module reads nothing else" % (resolved, PNG_SUFFIX))

    canonical = frames_dir or default_frames_dir()
    canonical = os.path.realpath(os.path.abspath(canonical))
    if not _is_inside(resolved, canonical):
        message = (
            "%s is outside the capture directory %s; a session frame "
            "always lives there, so this is either a hand-picked frame "
            "being debugged or a wrong path"
            % (resolved, canonical))
        if strict:
            raise FramePathError(message)
        _warn(message, notes)

    if not os.path.exists(resolved):
        raise FrameMissingError(
            "no such frame: %s.  This is a fault, not an unreadable "
            "clock, and it is reported rather than returned as None"
            % resolved)
    if not os.path.isfile(resolved):
        raise FrameMissingError(
            "%s is not a regular file" % resolved)

    try:
        with open(resolved, "rb") as handle:
            header = handle.read(len(PNG_MAGIC))
    except OSError as exc:
        raise FrameUnreadableError(
            "%s could not be opened: %s" % (resolved, exc)) from exc
    if header != PNG_MAGIC:
        raise FrameUnreadableError(
            "%s does not start with the PNG signature, so it is not a "
            "capture this module can read" % resolved)

    return resolved


# ---------------------------------------------------------------------
# The 24_HOUR assertion
# ---------------------------------------------------------------------

def assert_24_hour_option(
    options_json: Optional[str] = None,
    options: Optional[Dict[str, str]] = None,
    notes: Optional[List[str]] = None,
) -> Optional[str]:
    """Refuse to read frames unless the clock is the fixed-width form.

    ``military`` is the trap this exists for: it is a legal ``24_HOUR``
    value that renders ``0815.32`` [src/calendar.cpp:646], matches
    nothing this module looks for, and would therefore report every
    frame as unreadable -- collapsing every duration to the floor while
    every count still tallied.  The 12h default is equally hostile:
    variable padding and an AM/PM suffix [src/calendar.cpp:657-661].

    An ABSENT options file is an ordinary state, not a fault: the
    engine writes it on its first launch [src/path_info.cpp:167], so a
    fresh userdir has none.  That case warns once and returns ``None``.

    :returns: the option's value when it is ``24h``, or ``None`` when
        no options file exists yet.
    :raises OptionsError: when the value is anything other than ``24h``,
        or when the options file exists but cannot be parsed.
    """
    if options is None:
        try:
            options = sidebar_geometry.load_options(path=options_json)
        except sidebar_geometry.GeometryError as exc:
            raise OptionsError(
                "the game options file could not be read, so the clock "
                "format cannot be confirmed: %s" % exc) from exc

    raw = options.get(OPT_24_HOUR)
    if raw is None:
        _warn_once(
            "24-hour-absent",
            "the game options file carries no '%s' value, so the clock "
            "format is unconfirmed; the engine writes options.json on "
            "its first launch and seed_options.py then sets '%s'"
            % (OPT_24_HOUR, OPT_24_HOUR_REQUIRED),
            notes)
        return None

    value = str(raw).strip()
    if value == OPT_24_HOUR_REQUIRED:
        LOG.debug("%s is '%s', the fixed-width form",
                  OPT_24_HOUR, value)
        return value

    if value == OPT_24_HOUR_MILITARY:
        raise OptionsError(
            "%s is '%s', which renders the clock as '0815.32' "
            "[src/calendar.cpp:646].  Nothing here matches that, so "
            "every frame would report an unreadable clock and every "
            "duration would collapse to the floor.  Set '%s' with "
            "seed_options.py and recapture."
            % (OPT_24_HOUR, value, OPT_24_HOUR_REQUIRED))

    raise OptionsError(
        "%s is '%s', not '%s'.  The '%s' form renders '8:15:32 AM' with "
        "variable padding [src/calendar.cpp:657-661], which is not the "
        "fixed-width reading this module and timeline.py depend on.  "
        "Set '%s' with seed_options.py and recapture."
        % (OPT_24_HOUR, value, OPT_24_HOUR_REQUIRED, OPT_24_HOUR_12H,
           OPT_24_HOUR_REQUIRED))


# ---------------------------------------------------------------------
# The crop rectangle
#
# Computed by sidebar_geometry, never hard-coded here.  A caller may
# pass one in -- as the geometry string capture.sh already captures, as
# a Rect, as a whole SidebarGeometry, or as (width, height, x, y) -- and
# anything malformed raises rather than being coerced into something
# plausible.
# ---------------------------------------------------------------------

def parse_geometry(text: str) -> sidebar_geometry.Rect:
    """Parse an ImageMagick ``WxH+X+Y`` string into a rectangle.

    :raises RectError: when the string is not that form, or describes a
        rectangle that cannot hold pixels.
    """
    if not isinstance(text, str):
        raise RectError(
            "a crop geometry must be a string, got %s"
            % type(text).__name__)
    match = GEOMETRY_RE.match(text.strip())
    if match is None:
        raise RectError(
            "%r is not an ImageMagick geometry of the form WxH+X+Y, "
            "which is what sidebar_geometry.py prints" % text)
    width, height, x, y = (int(group) for group in match.groups())
    try:
        return sidebar_geometry.Rect(
            width=width, height=height, x=x, y=y)
    except sidebar_geometry.GeometryError as exc:
        raise RectError("%s: %s" % (text, exc)) from exc


def _probe_row_height(notes: Optional[List[str]] = None) -> int:
    """Resolve one text row's height in pixels, or say why not.

    A row is ``FONT_HEIGHT * SCALING_FACTOR`` pixels tall, exactly as
    the engine derives its window [src/sdltiles.cpp:595-596], and
    sidebar_geometry reads both from the game-written options file.
    When that computation is impossible -- outside a checkout, say --
    the engine's documented FONT_HEIGHT default is used and the
    substitution is announced, never made silently.
    """
    try:
        geometry = sidebar_geometry.compute_sidebar_geometry()
    except sidebar_geometry.GeometryError as exc:
        _warn_once(
            "row-height-default",
            "the sidebar geometry could not be computed (%s), so one "
            "text row is assumed to be the engine's default "
            "FONT_HEIGHT of %d px [src/options.cpp:2435-2438]; pass "
            "row_height explicitly to be certain"
            % (exc, DEFAULT_ROW_HEIGHT),
            notes)
        return DEFAULT_ROW_HEIGHT
    return geometry.font_height * geometry.scaling_factor


def resolve_rect(
    rect: RectLike = None,
    row_height: Optional[int] = None,
    notes: Optional[List[str]] = None,
    options_json: Optional[str] = None,
) -> Tuple[sidebar_geometry.Rect, int]:
    """Return the sidebar crop and the height of one text row.

    With ``rect=None`` the crop is computed from configuration by
    :func:`sidebar_geometry.compute_sidebar_geometry`, which is the
    path the pipeline takes, and every substitution that computation
    had to make is copied into ``notes``.

    :param rect: an explicit crop, or ``None`` to compute one.
    :param row_height: one text row in pixels; derived when omitted.
    :param notes: a list every substitution is appended to.
    :param options_json: the game-written ``options.json`` the crop
        computation should read.  ``None`` leaves
        :mod:`sidebar_geometry` on its own default location, which is
        the production path; passing it keeps the crop and the
        ``24_HOUR`` assertion on one single configuration file, since
        the terminal and font dimensions that place the sidebar live in
        the same file as the clock format that makes it readable.
    :returns: ``(rect, row_height)``.
    :raises RectError: for a malformed rectangle or row height.
    """
    resolved_rows = row_height

    if rect is None:
        try:
            geometry = sidebar_geometry.compute_sidebar_geometry(
                options_json=options_json)
        except sidebar_geometry.GeometryError as exc:
            raise RectError(
                "the sidebar crop could not be computed: %s" % exc
            ) from exc
        rectangle = geometry.rect
        if resolved_rows is None:
            resolved_rows = (geometry.font_height *
                             geometry.scaling_factor)
        if notes is not None:
            notes.extend(geometry.notes)
    elif isinstance(rect, sidebar_geometry.SidebarGeometry):
        rectangle = rect.rect
        if resolved_rows is None:
            resolved_rows = rect.font_height * rect.scaling_factor
        if notes is not None:
            notes.extend(rect.notes)
    elif isinstance(rect, sidebar_geometry.Rect):
        rectangle = rect
    elif isinstance(rect, str):
        rectangle = parse_geometry(rect)
    elif isinstance(rect, (tuple, list)):
        if len(rect) != 4:
            raise RectError(
                "a sequence crop must be (width, height, x, y), got %d "
                "values: %r" % (len(rect), rect))
        try:
            rectangle = sidebar_geometry.Rect(
                width=int(rect[0]), height=int(rect[1]),
                x=int(rect[2]), y=int(rect[3]))
        except (TypeError, ValueError,
                sidebar_geometry.GeometryError) as exc:
            raise RectError(
                "%r is not a usable (width, height, x, y): %s"
                % (rect, exc)) from exc
    else:
        raise RectError(
            "a crop must be None, a WxH+X+Y string, a Rect, a "
            "SidebarGeometry or (width, height, x, y), got %s"
            % type(rect).__name__)

    if resolved_rows is None:
        resolved_rows = _probe_row_height(notes)

    if isinstance(resolved_rows, bool) or not isinstance(
            resolved_rows, int) or resolved_rows <= 0:
        raise RectError(
            "a text row height must be a positive int, got %r"
            % (resolved_rows,))
    if resolved_rows > rectangle.height:
        raise RectError(
            "one text row is %d px but the crop is only %d px tall, so "
            "the column holds no complete row"
            % (resolved_rows, rectangle.height))
    if rectangle.height % resolved_rows:
        _warn(
            "the %d px crop is not a whole number of %d px text rows; "
            "the %d px remainder at the bottom is not read"
            % (rectangle.height, resolved_rows,
               rectangle.height % resolved_rows),
            notes)

    return rectangle, resolved_rows


# ---------------------------------------------------------------------
# External commands
#
# ARGUMENT LISTS ONLY.  No shell, no string interpolation into a
# command, no PATH search by the shell: shutil.which resolves the tool
# first so an absent one is reported as an absent one, and every call
# carries a timeout so a hung tool is a fault rather than a hang.
# ---------------------------------------------------------------------

def _run(
    command: List[str],
    timeout: int,
    what: str,
    stdin_bytes: Optional[bytes] = None,
) -> bytes:
    """Run one external command and return its standard output."""
    if shutil.which(command[0]) is None:
        raise ToolchainError(
            "%s is not on PATH.  The capture and OCR toolchain is "
            "listed in playthrough/tooling/requirements.txt; on this "
            "host it comes from the imagemagick and tesseract-ocr "
            "packages." % command[0])
    LOG.debug("%s: %s", what, " ".join(command))
    try:
        completed = subprocess.run(
            command,
            input=stdin_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolchainError(
            "%s did not finish within %d s" % (what, timeout)) from exc
    except OSError as exc:
        raise ToolchainError(
            "%s could not be run: %s" % (what, exc)) from exc

    diagnostic = completed.stderr.decode("utf-8", "replace").strip()
    if completed.returncode != 0:
        raise ToolchainError(
            "%s exited %d: %s"
            % (what, completed.returncode, diagnostic or "no output"))
    if diagnostic:
        LOG.debug("%s stderr: %s", what, diagnostic)
    return completed.stdout


def resolve_engine(requested: Optional[str] = None,
                   notes: Optional[List[str]] = None) -> str:
    """Choose the preprocessing engine, announcing any substitution.

    ``convert`` is the default because it IS the prescribed chain and
    because it measurably read the calibration frame correctly where
    Pillow read one digit of the slashed zero wrong.  When ImageMagick
    is absent the Pillow path is used instead -- loudly, since the
    reading may differ.
    """
    engine = requested or ENGINE_CONVERT
    if engine not in ENGINES:
        raise ToolchainError(
            "unknown preprocessing engine %r; choose one of %s"
            % (engine, ", ".join(ENGINES)))
    if engine == ENGINE_CONVERT and shutil.which(CONVERT_BIN) is None:
        _warn_once(
            "convert-missing",
            "ImageMagick's '%s' is not on PATH, so preprocessing falls "
            "back to Pillow: %s"
            % (CONVERT_BIN, ENGINE_NOTES[ENGINE_PILLOW]),
            notes)
        return ENGINE_PILLOW
    return engine


def resolve_ocr_engine(requested: Optional[str] = None,
                       notes: Optional[List[str]] = None) -> str:
    """Choose the OCR front end, announcing any substitution.

    ``pytesseract`` is the default -- it is the declared dependency for
    this module -- and the ``tesseract`` binary is called directly when
    it is not installed, which is also the literal form of the
    prescribed pipeline.
    """
    engine = requested or OCR_PYTESSERACT
    if engine not in OCR_ENGINES:
        raise ToolchainError(
            "unknown OCR engine %r; choose one of %s"
            % (engine, ", ".join(OCR_ENGINES)))
    if engine == OCR_PYTESSERACT and pytesseract is None:
        _warn_once(
            "pytesseract-missing",
            "pytesseract is not importable, so OCR calls the tesseract "
            "binary directly; install "
            "playthrough/tooling/requirements.txt to use the pinned "
            "wrapper",
            notes)
        return OCR_TESSERACT
    return engine


# ---------------------------------------------------------------------
# Preprocessing
#
# Both engines produce the same artifact: ONE tall greyscale strip in
# which each text row of the sidebar occupies a fixed band.  For a
# row-wise pass the strip is built by tiling the column into text rows
# BEFORE the contrast stretch, so each row is normalised against its
# own content -- measured to be the difference between reading the
# clock and reading nothing, because a column-global stretch leaves the
# clock dim next to the bright hit-point bars.
# ---------------------------------------------------------------------

def _convert_strip(
    png_path: str,
    rect: sidebar_geometry.Rect,
    row_height: int,
    ocr_pass: OcrPass,
) -> Image.Image:
    """Build the preprocessed strip with ImageMagick ``convert``."""
    command = [
        CONVERT_BIN, png_path,
        "-crop", rect.geometry, "+repage",
    ]
    if ocr_pass.row_wise:
        command += ["-crop", "%dx%d" % (rect.width, row_height),
                    "+repage"]
    command += ["-colorspace", "Gray", "-resize", RESIZE_PERCENT,
                "-normalize"]
    if ocr_pass.deslash:
        command += ["-gaussian-blur", DESLASH_BLUR]
    if ocr_pass.negate:
        command.append("-negate")
    if ocr_pass.row_wise:
        command.append("-append")
    command.append("png:-")

    data = _run(command, CONVERT_TIMEOUT, CONVERT_BIN)
    if not data:
        raise ToolchainError(
            "%s produced no image for %s at %s"
            % (CONVERT_BIN, png_path, rect.geometry))
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except OSError as exc:
        raise ToolchainError(
            "%s produced an image that could not be decoded: %s"
            % (CONVERT_BIN, exc)) from exc
    return image if image.mode == "L" else image.convert("L")


def _pillow_finish(band: Image.Image,
                   ocr_pass: OcrPass) -> Image.Image:
    """Apply the enlarge, stretch, blur and invert stages in Pillow."""
    enlarged = band.resize(
        (band.width * SCALE_FACTOR, band.height * SCALE_FACTOR),
        Image.BICUBIC)
    stretched = ImageOps.autocontrast(enlarged, cutoff=0)
    if ocr_pass.deslash:
        stretched = stretched.filter(
            ImageFilter.GaussianBlur(PILLOW_BLUR_RADIUS))
    if ocr_pass.negate:
        stretched = ImageOps.invert(stretched)
    return stretched


def _pillow_strip(
    png_path: str,
    rect: sidebar_geometry.Rect,
    row_height: int,
    ocr_pass: OcrPass,
) -> Image.Image:
    """Build the preprocessed strip with Pillow alone."""
    try:
        source = Image.open(png_path)
        source.load()
    except OSError as exc:
        raise FrameUnreadableError(
            "%s could not be decoded: %s" % (png_path, exc)) from exc

    column = source.crop(
        (rect.x, rect.y, rect.right, rect.bottom)).convert("L")
    if not ocr_pass.row_wise:
        return _pillow_finish(column, ocr_pass)

    bands = [
        _pillow_finish(
            column.crop((0, top, column.width, top + row_height)),
            ocr_pass)
        for top in range(0, column.height - row_height + 1, row_height)
    ]
    strip = Image.new(
        "L",
        (bands[0].width, sum(band.height for band in bands)))
    offset = 0
    for band in bands:
        strip.paste(band, (0, offset))
        offset += band.height
    return strip


def preprocess(
    png_path: str,
    rect: sidebar_geometry.Rect,
    row_height: int,
    ocr_pass: OcrPass,
    engine: str = ENGINE_CONVERT,
) -> Tuple[Image.Image, int]:
    """Return the preprocessed strip and the height of one band.

    :returns: ``(strip, band_height)``, where ``band_height`` is the
        row height after enlargement for a row-wise pass, or the whole
        strip height for a whole-column pass.
    """
    if engine == ENGINE_PILLOW:
        strip = _pillow_strip(png_path, rect, row_height, ocr_pass)
    else:
        strip = _convert_strip(png_path, rect, row_height, ocr_pass)
    band_height = (row_height * SCALE_FACTOR if ocr_pass.row_wise
                   else strip.height)
    return strip, band_height


# ---------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------

def ocr_image(image: Image.Image, psm: int,
              ocr_engine: str = OCR_PYTESSERACT) -> str:
    """Run tesseract over one image and return its text.

    :raises ToolchainError: when tesseract is absent or fails.  A blank
        result is NOT an error: an empty band legitimately reads empty.
    """
    config = "--psm %d" % psm
    if ocr_engine == OCR_PYTESSERACT:
        if pytesseract is None:
            raise ToolchainError(
                "pytesseract is not importable; install "
                "playthrough/tooling/requirements.txt or pass "
                "ocr_engine='%s'" % OCR_TESSERACT)
        try:
            return pytesseract.image_to_string(image, config=config)
        except Exception as exc:  # pytesseract raises its own types
            raise ToolchainError(
                "pytesseract failed with %s: %s"
                % (type(exc).__name__, exc)) from exc

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = _run(
        [TESSERACT_BIN, "stdin", "stdout", "--psm", str(psm)],
        TESSERACT_TIMEOUT,
        TESSERACT_BIN,
        buffer.getvalue())
    return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------
# Extraction
#
# Pure functions of the OCR text: no file access, no state, no repair.
# They are separate from the reading pipeline so the selection rules can
# be tested directly against text, without pixels or a toolchain.
# ---------------------------------------------------------------------

def is_possible_clock(value: object) -> bool:
    """True when a reading is a time the engine could have rendered.

    ``hour_of_day`` is 0-23 and both the minute and the second term are
    0-59 [src/calendar.cpp:640-642].  ``48:48:48`` -- a real OCR
    reading of a real frame on this host -- is therefore impossible,
    and saying so is how a confident misread is kept out of the record.
    """
    if not isinstance(value, str) or not CLOCK_RE.fullmatch(value):
        return False
    hour, minute, second = (int(part) for part in value.split(":"))
    return (hour <= MAX_HOUR and minute <= MAX_MINUTE and
            second <= MAX_SECOND)


def find_clocks(text: str) -> Tuple[Optional[str], Tuple[str, ...]]:
    """Return the first possible clock in ``text``, and the rest.

    Matches are considered in reading order -- top row to bottom row,
    left to right within a row -- and the first one that could be a
    real time wins.  That rule is fixed so the same OCR text always
    yields the same answer.

    :returns: ``(clock_or_None, impossible_readings)``.  The second
        element exists so a caller can report what was declined; no
        declined reading is ever repaired into the first element.
    """
    if not text:
        return None, ()
    impossible: List[str] = []
    for match in CLOCK_RE.finditer(text):
        value = match.group(0)
        if is_possible_clock(value):
            return value, tuple(impossible)
        if value not in impossible:
            impossible.append(value)
    return None, tuple(impossible)


def extract_clock(text: str,
                  notes: Optional[List[str]] = None) -> Optional[str]:
    """Return the clock read from OCR text, or ``None``.

    Every impossible reading encountered on the way is announced, so
    that a systematically misread frame is visible rather than merely
    unreadable.
    """
    clock, impossible = find_clocks(text)
    for value in impossible:
        _warn(
            "declined the reading %r: no in-game clock can say that "
            "(hour <= %d, minute and second <= %d).  It is NOT "
            "repaired into a plausible time; the search simply "
            "continued" % (value, MAX_HOUR, MAX_MINUTE),
            notes)
    return clock


def extract_phrase(text: str) -> Optional[str]:
    """Return the coarse time phrase in ``text``, verbatim, or ``None``.

    These are what a survivor without a watch actually sees
    [src/display.cpp:159-186, 212-216], so they are genuine readings
    and are returned exactly as the engine spells them, for
    ``manifest.py`` to record in ``ingame_clock``.

    When several appear, the earliest in the text wins, and the longer
    phrase wins a tie -- so "Around midnight" is never truncated to a
    shorter match that starts at the same place.  ``"???"`` is reported
    only when no phrase was found, since a phrase says strictly more.
    """
    if not text:
        return None
    best = None
    for phrase in COARSE_TIME_PHRASES:
        position = text.find(phrase)
        if position < 0:
            continue
        candidate = (position, -len(phrase), phrase)
        if best is None or candidate < best:
            best = candidate
    if best is not None:
        return best[2]
    if UNKNOWN_TIME_TEXT in text:
        return UNKNOWN_TIME_TEXT
    return None


def extract_date(text: str) -> Optional[str]:
    """Return the sidebar date line, verbatim, or ``None``.

    Both forms ``display::date_string()`` can render are recognised
    [src/display.cpp:193-205].  ``timeline.py``'s midnight-rollover
    guard cross-checks against this, which is why it is read here and
    returned SEPARATELY -- it is never folded into the clock string.

    The earliest match wins; the ``<Weekday>, <Month> <day>`` form wins
    a tie, because ``SHOW_MONTHS`` defaults to true
    [src/options.cpp:1878-1880] and it is therefore the form in play.
    """
    if not text:
        return None
    best = None
    for order, pattern in enumerate((DATE_MONTH_RE, DATE_SEASON_RE)):
        match = pattern.search(text)
        if match is None:
            continue
        candidate = (match.start(), order, match.group(0))
        if best is None or candidate < best:
            best = candidate
    return best[2] if best is not None else None


def diagnose_clock_text(text: str,
                        notes: Optional[List[str]] = None) -> None:
    """Explain why OCR text held no readable clock.

    An unreadable clock is a legitimate outcome, but the REASON is
    worth reporting: an off-contract ``24_HOUR`` value looks exactly
    like a watchless survivor from the outside, and confusing the two
    would send someone hunting for a wristwatch that was never the
    problem.

    The level is calibrated deliberately.  A cause that means
    something is MISCONFIGURED -- a ``military`` or ``12h`` clock in
    the sidebar -- is a warning, visible with no logging setup at all.
    A cause that is ORDINARY -- a watchless survivor, or a menu frame
    with no sidebar drawn, which is what most character-creation
    keystrokes capture -- is reported at INFO and surfaces with
    ``-v``.  Warning on every expected menu frame would bury the two
    lines that actually mean someone must intervene, so the split is
    load-bearing and should not be flattened.
    """
    military = MILITARY_RE.search(text)
    if military is not None:
        _warn(
            "the sidebar reads %r, which is the '%s' clock format "
            "[src/calendar.cpp:646]; set %s to '%s' with "
            "seed_options.py, because nothing downstream can parse that"
            % (military.group(0), OPT_24_HOUR_MILITARY, OPT_24_HOUR,
               OPT_24_HOUR_REQUIRED),
            notes)
        return
    twelve = TWELVE_HOUR_RE.search(text)
    if twelve is not None:
        _warn(
            "the sidebar reads %r, which is the '%s' clock format "
            "[src/calendar.cpp:657-661]; set %s to '%s' with "
            "seed_options.py for the fixed-width form"
            % (twelve.group(0), OPT_24_HOUR_12H, OPT_24_HOUR,
               OPT_24_HOUR_REQUIRED),
            notes)
        return
    phrase = extract_phrase(text)
    if phrase is not None:
        LOG.info(
            "no exact clock: the sidebar reads %r, which is what the "
            "engine renders without a watch [src/display.cpp:212-216]. "
            "That is a real reading, recorded as it stands; only a "
            "time-telling device in the survivor's possession makes "
            "second-resolution readings possible, and acquiring one is "
            "a decision made in play", phrase)
        return
    LOG.info(
        "no clock and no time phrase in the sidebar column; the frame "
        "is most likely a menu, a full-screen view or a load screen, "
        "where the sidebar is not drawn at all")


def _scan_strip(
    strip: Image.Image,
    band_height: int,
    ocr_pass: OcrPass,
    ocr_engine: str,
    stop_early: bool,
) -> Tuple[str, int]:
    """OCR a preprocessed strip band by band, top to bottom.

    Bands that hold a single flat colour are skipped without an OCR
    call -- a blank sidebar row cannot contain a clock, and on a black
    frame this reduces the whole read to no OCR calls at all.

    :returns: ``(text, ocr_call_count)`` with one line per band, so the
        row structure survives into the extraction step.
    """
    lines: List[str] = []
    calls = 0
    bands = max(1, strip.height // band_height)
    for index in range(bands):
        top = index * band_height
        band = strip.crop((0, top, strip.width, top + band_height))
        low, high = band.getextrema()
        if low == high:
            lines.append("")
            continue
        calls += 1
        lines.append(ocr_image(band, ocr_pass.psm, ocr_engine).strip())
        if stop_early and find_clocks("\n".join(lines))[0] is not None:
            LOG.debug("pass '%s' stopped at band %d of %d",
                      ocr_pass.name, index + 1, bands)
            break
    return "\n".join(lines), calls


def _assert_rect_fits(png_path: str,
                      rect: sidebar_geometry.Rect) -> Tuple[int, int]:
    """Confirm the crop lies inside the frame, or fail loudly."""
    try:
        with Image.open(png_path) as image:
            size = image.size
    except OSError as exc:
        raise FrameUnreadableError(
            "%s could not be opened as an image: %s"
            % (png_path, exc)) from exc
    if rect.right > size[0] or rect.bottom > size[1]:
        raise RectError(
            "the crop %s does not fit inside the %dx%d frame %s.  "
            "Capture targets the X root, so a mismatch means the crop "
            "was computed for a different display than the one "
            "photographed."
            % (rect.geometry, size[0], size[1], png_path))
    return size


# ---------------------------------------------------------------------
# The reading pipeline
# ---------------------------------------------------------------------

def read_sidebar(
    png_path: str,
    rect: RectLike = None,
    row_height: Optional[int] = None,
    engine: Optional[str] = None,
    ocr_engine: Optional[str] = None,
    passes: Optional[Sequence[OcrPass]] = None,
    cross_check: bool = False,
    full_scan: bool = True,
    check_options: bool = True,
    options_json: Optional[str] = None,
    frames_dir: Optional[str] = None,
    strict_path: bool = False,
) -> SidebarReading:
    """Read one captured frame's sidebar and report what it said.

    This is the module's primary entry point; :func:`read_clock`,
    :func:`read_time_phrase` and :func:`read_date_line` are thin views
    of it.  The read is a pure function of the frame and the crop: no
    value is carried from any previous call, so a sequence cannot be
    silently continued.

    :param png_path: the captured PNG.  Validated, and expected inside
        the frames directory.
    :param rect: the crop; ``None`` computes it from configuration.
    :param row_height: one text row in pixels; derived when omitted.
    :param engine: ``convert`` (default) or ``pillow`` preprocessing.
    :param ocr_engine: ``pytesseract`` (default) or ``tesseract``.
    :param passes: an explicit pass list; :data:`PASSES` by default.
    :param cross_check: run every pass even after one succeeds, so that
        disagreement between them is reported rather than hidden.
    :param full_scan: read every text row.  ``False`` stops at the
        first row holding a clock, which is faster and is what
        :func:`read_clock` does; the date line may then be missed.
    :param check_options: assert ``24_HOUR`` is ``24h`` before reading.
    :param options_json: an explicit options file, used both for that
        assertion and for the crop computation, so a hand-picked
        configuration cannot be asserted against one file while the
        sidebar is located from another.
    :param frames_dir: an explicit frames directory for path checking.
    :param strict_path: refuse a frame outside the frames directory.
    :returns: a :class:`SidebarReading`; ``.clock`` is ``None`` when no
        possible clock was read.
    :raises OcrClockError: for any fault -- a bad or missing frame, an
        unusable crop, a missing tool, a misconfigured option.  Never
        for an unreadable clock.
    """
    notes: List[str] = []
    resolved_png = validate_frame_path(
        png_path, frames_dir=frames_dir, strict=strict_path, notes=notes)

    if check_options:
        assert_24_hour_option(options_json=options_json, notes=notes)

    rectangle, rows = resolve_rect(
        rect, row_height, notes, options_json=options_json)
    chosen_engine = resolve_engine(engine, notes)
    chosen_ocr = resolve_ocr_engine(ocr_engine, notes)
    frame_size = _assert_rect_fits(resolved_png, rectangle)
    LOG.debug("reading %s (%dx%d) at %s, %d px rows, %s + %s",
              resolved_png, frame_size[0], frame_size[1],
              rectangle.geometry, rows, chosen_engine, chosen_ocr)

    selected = tuple(passes) if passes else PASSES
    if not selected:
        raise OcrClockError(
            "no OCR passes were given, so nothing would be read")

    clock: Optional[str] = None
    winner: Optional[str] = None
    winning_text = ""
    fallback_text = ""
    candidates: List[str] = []
    declined: List[str] = []
    attempted: List[str] = []
    calls = 0

    for ocr_pass in selected:
        strip, band_height = preprocess(
            resolved_png, rectangle, rows, ocr_pass, chosen_engine)
        text, pass_calls = _scan_strip(
            strip, band_height, ocr_pass, chosen_ocr, not full_scan)
        calls += pass_calls
        attempted.append(ocr_pass.name)
        if not fallback_text.strip() and text.strip():
            fallback_text = text

        found, impossible = find_clocks(text)
        for value in impossible:
            if value in declined:
                continue
            declined.append(value)
            _warn(
                "pass '%s' read %r, which no in-game clock can say "
                "(hour <= %d, minute and second <= %d); declined, and "
                "NOT repaired into a plausible time"
                % (ocr_pass.name, value, MAX_HOUR, MAX_MINUTE),
                notes)

        if found is None:
            LOG.debug("pass '%s' found no clock", ocr_pass.name)
            continue
        if found not in candidates:
            candidates.append(found)
        if clock is None:
            clock, winner, winning_text = found, ocr_pass.name, text
            LOG.debug("pass '%s' read the clock as %s",
                      ocr_pass.name, found)
        if not cross_check:
            break

    text = winning_text or fallback_text

    if len(candidates) > 1:
        _warn(
            "the OCR passes disagree about the clock: %s.  The first in "
            "pass order (%r from '%s') is reported and every candidate "
            "is recorded; nothing is averaged or repaired.  The reading "
            "of the frame itself is authoritative -- inspect %s"
            % (", ".join(repr(value) for value in candidates),
               clock, winner, resolved_png),
            notes)

    if clock is None and text.strip():
        diagnose_clock_text(text, notes)
    elif clock is None:
        _warn(
            "the sidebar column of %s produced no text at all; the "
            "frame may be blank, which is what SDL_VIDEODRIVER=dummy "
            "produces, or the crop %s may cover empty pixels"
            % (resolved_png, rectangle.geometry),
            notes)

    reading = SidebarReading(
        png=resolved_png,
        rect=rectangle.geometry,
        clock=clock,
        phrase=extract_phrase(text),
        date=extract_date(text),
        text=text,
        candidates=tuple(candidates),
        declined=tuple(declined),
        passes_run=tuple(attempted),
        pass_name=winner,
        ocr_calls=calls,
        engine=chosen_engine,
        ocr_engine=chosen_ocr,
        notes=tuple(notes),
    )
    LOG.debug("read %s -> clock=%r phrase=%r date=%r (%d ocr calls)",
              resolved_png, reading.clock, reading.phrase, reading.date,
              reading.ocr_calls)
    return reading


def read_clock(
    png_path: str,
    rect: RectLike = None,
    row_height: Optional[int] = None,
    engine: Optional[str] = None,
    ocr_engine: Optional[str] = None,
    cross_check: bool = False,
    full_scan: bool = False,
    check_options: bool = True,
    options_json: Optional[str] = None,
    frames_dir: Optional[str] = None,
    strict_path: bool = False,
) -> Optional[str]:
    """Return the sidebar clock as ``HH:MM:SS``, or ``None``.

    THE contract of this module.  ``None`` means the clock could not be
    read from these pixels -- because the survivor carries no watch,
    because the sidebar is not drawn on this frame, or because OCR
    could not make out a possible time.  ``None`` is never a stand-in
    for a value: no default, no neighbouring frame, no interpolation
    and no repair of a partial match.

    Scanning stops at the first row holding a clock, which is why the
    default here is ``full_scan=False``; use :func:`read_sidebar` when
    the date line or the raw text is wanted too.

    :returns: the reading, or ``None``.
    :raises OcrClockError: for a fault, never for an unreadable clock.
    """
    return read_sidebar(
        png_path,
        rect=rect,
        row_height=row_height,
        engine=engine,
        ocr_engine=ocr_engine,
        cross_check=cross_check,
        full_scan=full_scan,
        check_options=check_options,
        options_json=options_json,
        frames_dir=frames_dir,
        strict_path=strict_path,
    ).clock


def read_time_phrase(
    png_path: str,
    rect: RectLike = None,
    row_height: Optional[int] = None,
    engine: Optional[str] = None,
    ocr_engine: Optional[str] = None,
    check_options: bool = False,
    options_json: Optional[str] = None,
    frames_dir: Optional[str] = None,
    strict_path: bool = False,
) -> Optional[str]:
    """Return the coarse time phrase on the frame, verbatim, or ``None``.

    The secondary reader.  A survivor with no watch but a view of the
    sky sees one of eleven phrases [src/display.cpp:159-186], and
    without either sees ``"???"`` [src/display.cpp:216].  Those are
    honest observations of the frame, so they are returned exactly as
    the engine spells them for ``manifest.py`` to record -- while
    :func:`read_clock` still returns ``None`` for the same frame,
    because a phrase is not a parseable clock.

    ``check_options`` defaults to ``False`` here: the ``24_HOUR`` value
    is irrelevant to a phrase, so a misconfigured option must not stop
    a phrase from being read honestly.
    """
    return read_sidebar(
        png_path,
        rect=rect,
        row_height=row_height,
        engine=engine,
        ocr_engine=ocr_engine,
        full_scan=True,
        check_options=check_options,
        options_json=options_json,
        frames_dir=frames_dir,
        strict_path=strict_path,
    ).phrase


def read_date_line(
    png_path: str,
    rect: RectLike = None,
    row_height: Optional[int] = None,
    engine: Optional[str] = None,
    ocr_engine: Optional[str] = None,
    check_options: bool = False,
    options_json: Optional[str] = None,
    frames_dir: Optional[str] = None,
    strict_path: bool = False,
) -> Optional[str]:
    """Return the sidebar date line, verbatim, or ``None``.

    Exposed separately from the clock because ``timeline.py``'s
    midnight-rollover guard needs it: with the date in hand a
    ``23:59:58`` to ``00:00:04`` step is a positive six-second delta
    rather than a negative one.  It is never folded into the clock
    string.
    """
    return read_sidebar(
        png_path,
        rect=rect,
        row_height=row_height,
        engine=engine,
        ocr_engine=ocr_engine,
        full_scan=True,
        check_options=check_options,
        options_json=options_json,
        frames_dir=frames_dir,
        strict_path=strict_path,
    ).date


# ---------------------------------------------------------------------
# Command line
#
# STDOUT CARRIES EXACTLY THE READING AND NOTHING ELSE, so that
#
#     CLOCK="$(python3 playthrough/tooling/ocr_clock.py "$FRAME")"
#
# needs no parsing, no trimming and no decoration to strip -- and so
# that an unreadable clock yields an empty string rather than a
# plausible-looking placeholder.  Every warning, note, derivation and
# error goes to stderr, which is also what keeps this module's
# engineering observations out of the in-character record.
# ---------------------------------------------------------------------

FIELDS = ("clock", "phrase", "date", "text")

_EPILOG = """\
exit codes:
  0  the requested field was read
  1  the frame was read and held no such reading (stdout is empty)
  2  a fault: bad or missing frame, unusable crop, missing tool, or a
     24_HOUR option that is not 24h

examples:
  # the pipeline's own call, crop computed from configuration
  ocr_clock.py playthrough/frames/frame_00042.png

  # the crop capture.sh already has in hand
  ocr_clock.py --rect "$(sidebar_geometry.py)" "$FRAME"

  # audit one frame: run every pass and show the evidence
  ocr_clock.py --cross-check -v "$FRAME"

  # the whole reading, for a tool rather than a human
  ocr_clock.py --json "$FRAME"

  # what a watchless survivor's sidebar says
  ocr_clock.py --field phrase "$FRAME"
"""


def explain_text() -> str:
    """Return the prescribed pipeline and the pass table, as text."""
    lines = [
        "the prescribed pipeline, verbatim:",
        "",
        REFERENCE_PIPELINE,
        "",
        "passes, in the order they are attempted:",
    ]
    for index, ocr_pass in enumerate(PASSES, start=1):
        lines.append("  %d. %s (psm %d, %s)"
                     % (index, ocr_pass.name, ocr_pass.psm,
                        "row-wise" if ocr_pass.row_wise
                        else "whole column"))
        lines.append("     %s" % ocr_pass.description)
    lines.append("")
    lines.append("the first pass that reads a POSSIBLE clock wins; with")
    lines.append("--cross-check every pass runs and disagreement is")
    lines.append("reported.  An impossible reading such as 48:48:48 is")
    lines.append("declined, never repaired, and an unreadable clock is")
    lines.append("reported as unreadable -- never guessed.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Read the Cataclysm-DDA sidebar clock out of a captured "
            "frame, or report that it could not be read."),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "frame", nargs="?",
        help=("the captured PNG, normally under playthrough/frames/; "
              "optional only with --explain"))
    parser.add_argument(
        "--rect", metavar="WxH+X+Y",
        help=("the sidebar crop; computed by sidebar_geometry.py when "
              "omitted, which is the pipeline's own path"))
    parser.add_argument(
        "--row-height", type=int, metavar="PX",
        help=("one text row in pixels (FONT_HEIGHT * SCALING_FACTOR); "
              "derived from the game options when omitted"))
    parser.add_argument(
        "--engine", choices=ENGINES, default=None,
        help="preprocessing engine (default: %s)" % ENGINE_CONVERT)
    parser.add_argument(
        "--ocr", choices=OCR_ENGINES, default=None, dest="ocr_engine",
        help="OCR front end (default: %s)" % OCR_PYTESSERACT)
    parser.add_argument(
        "--field", choices=FIELDS, default="clock",
        help="which reading to print (default: clock)")
    parser.add_argument(
        "--json", action="store_true",
        help=("print the whole reading, with its candidates and notes, "
              "as JSON instead of one value"))
    parser.add_argument(
        "--cross-check", action="store_true",
        help=("run every pass even after one succeeds, so that "
              "disagreement between them is reported"))
    parser.add_argument(
        "--stop-early", action="store_true",
        help=("stop at the first text row holding a clock; faster, but "
              "the date line and the rest of the column go unread"))
    parser.add_argument(
        "--frames-dir", metavar="DIR",
        help=("the capture directory a frame is expected inside "
              "(default: $%s, else playthrough/frames)"
              % ENV_FRAMES_DIR))
    parser.add_argument(
        "--strict-path", action="store_true",
        help=("refuse a frame outside the capture directory instead of "
              "warning; automated callers should pass this"))
    parser.add_argument(
        "--options-json", metavar="PATH",
        help=("the game-written options.json to assert 24_HOUR against "
              "and to compute the sidebar crop from "
              "(default: playthrough/userdir/config/options.json)"))
    parser.add_argument(
        "--no-check-options", action="store_false",
        dest="check_options",
        help=("skip the 24_HOUR assertion; only for reading a frame "
              "captured under some other configuration"))
    parser.add_argument(
        "--explain", action="store_true",
        help="describe the pipeline and the passes, then read if asked")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help=("report the derivation on stderr; repeat for the "
              "per-pass and per-band detail"))
    return parser


def _configure_cli_logging(verbosity: int) -> None:
    """Send diagnostics to stderr at a verbosity, never to stdout."""
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("ocr_clock: %(levelname)s: %(message)s"))
    for existing in list(LOG.handlers):
        LOG.removeHandler(existing)
    LOG.addHandler(handler)
    LOG.setLevel(level)
    LOG.propagate = False


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Read one frame and print the requested reading, or nothing."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_cli_logging(args.verbose)

    if args.explain:
        # Only ever stdout when there is no reading to print there.
        print(explain_text(),
              file=sys.stdout if args.frame is None else sys.stderr)
        if args.frame is None:
            return EXIT_OK
    if args.frame is None:
        parser.error("a frame is required unless --explain is given")

    try:
        reading = read_sidebar(
            args.frame,
            rect=args.rect,
            row_height=args.row_height,
            engine=args.engine,
            ocr_engine=args.ocr_engine,
            cross_check=args.cross_check,
            full_scan=not args.stop_early,
            check_options=args.check_options,
            options_json=args.options_json,
            frames_dir=args.frames_dir,
            strict_path=args.strict_path,
        )
    except OcrClockError as exc:
        LOG.error("%s", exc)
        return EXIT_FAULT

    if args.verbose:
        print(reading.describe(), file=sys.stderr)

    if args.json:
        print(json.dumps(reading.as_dict(), indent=2, sort_keys=True))
        return EXIT_OK if reading.readable else EXIT_UNREADABLE

    value = {
        "clock": reading.clock,
        "phrase": reading.phrase,
        "date": reading.date,
        "text": reading.text.strip() or None,
    }[args.field]
    if not value:
        LOG.info(
            "no %s could be read from %s; reporting nothing rather "
            "than guessing", args.field, reading.png)
        return EXIT_UNREADABLE
    print(value)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
