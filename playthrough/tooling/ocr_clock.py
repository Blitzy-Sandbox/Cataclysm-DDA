#!/usr/bin/env python3
"""Read the Cataclysm-DDA sidebar clock out of a captured frame.

Crop the computed sidebar column out of a captured PNG, preprocess it
for legibility, run OCR over it, extract the clock by regular
expression, and return the matched string -- or NOTHING AT ALL.

THE HONESTY CONTRACT: None VERSUS AN EXCEPTION
This module is the single place where "never fabricate" is enforced in
code, because every frame duration, the pacing of the movie and the
caption timings rest on it never inventing a number.

  * a genuine ``HH:MM:SS`` reading is returned verbatim;
  * anything else returns ``None``: never ``"00:00:00"``, never the
    previous frame's value, never an interpolation, and never a repair
    of a partial match such as ``08:1S:32``;
  * this module is STATELESS, so it CANNOT silently continue a
    sequence.  Reconciling a missing or non-monotonic reading is
    ``timeline.py``'s job, downstream and visibly;
  * a genuine fault RAISES -- a missing or unreadable input, a path
    outside the frames directory under a strict caller, an absent
    toolchain, a misconfigured ``24_HOUR``.  Only a genuinely
    unreadable clock is allowed to be quiet, and even then it is an
    explicit ``None`` that ``manifest.py`` records as JSON ``null``.

THE CANONICAL PREPROCESSING
The prescribed chain, in its shell form::

    convert "$FRAME" -crop "$RECT" +repage -colorspace Gray \
        -resize 200% -normalize png:- \
      | tesseract stdin stdout \
      | grep -Eo '[0-9]{2}:[0-9]{2}:[0-9]{2}'

Every operator is load-bearing and none is dropped or reordered:
``-crop "$RECT" +repage`` takes the sidebar column and resets the
virtual canvas, ``-colorspace Gray`` removes chroma noise from coloured
text on a dark background, ``-resize 200%`` enlarges 8x16 terminal
glyphs that tesseract cannot read at native size, and ``-normalize``
stretches contrast so the strokes separate.  ``$RECT`` is COMPUTED at
run time by :mod:`sidebar_geometry`, never hard-coded.

Two refinements are appended rather than substituted.  ``--psm 7`` is
used ROW BY ROW with per-row normalisation, because tesseract's layout
analysis mangles the clock line when the whole column is read at once
and a column-global ``-normalize`` leaves the clock too dim to match.
And ``-gaussian-blur 0x0.5`` follows ``-normalize``, because the game's
Terminus face draws a SLASHED ZERO that tesseract reads as an ``8``; the
half-pixel blur softens the slash.  The unblurred prescribed chain is
still run as its own pass on every frame the blurred form cannot read.
The passes are ordered, documented and deterministic (:data:`PASSES`),
and ``cross_check=True`` runs all of them and reports whether they
agree, so a style-induced misread becomes visible rather than
authoritative.

FINDING THE ROW
:mod:`sidebar_geometry` returns the WHOLE sidebar column, because the
clock's row cannot be derived from configuration: it is drawn by the
``time_desc_label`` widget bound to ``time_text``
[data/json/ui/time.json:2-8] at whatever position the enclosing
``custom_sidebar`` ``widgets`` array puts it
[data/json/ui/sidebar.json:3-40], and eight distinct sidebar widths ship
in ``data/json/ui``.  Every row is therefore read and the clock located
BY REGEX, never at a fixed ``y``.  When more than one possible clock
appears the FIRST in reading order wins, so the same PNG always reads
the same way.

IMPOSSIBLE READINGS ARE DECLINED, NOT REPAIRED
``48:48:48`` matches the pattern but cannot be a clock -- the engine
cannot render hour 48.  Such a reading is declined with a warning and
the search continues through the same real OCR output.  Declining is not
repair: no digit is ever substituted, no value reconstructed, and if
nothing possible is found the answer is ``None``.

WHAT THE ENGINE CAN LEGITIMATELY RENDER
``display::time_string( const Character &u )``
[src/display.cpp:207-218] renders one of three things: with a watch, an
exact time from ``to_string_time_of_day()``; otherwise, if the survivor
can see the sky, a coarse phrase from ``display::time_approx()``
[src/display.cpp:159-186]; otherwise ``"???"``
[src/display.cpp:216].  The phrases and ``"???"`` are REAL READINGS, not
failures, so :func:`read_time_phrase` returns them verbatim for
``manifest.py`` to record honestly -- while :func:`read_clock` still
returns ``None``, because they are not parseable clocks.
Second-resolution deltas require a watch, and acquiring one is a
character decision made in play; this module never works around its
absence.  A ``"???"`` sidebar frequently comes back from OCR as
something other than the literal marker, and that is reported as
``None`` -- the honest answer, since nothing was recognised -- never as
an invented time.

WHY THE PATTERN IS EXACTLY ``[0-9]{2}:[0-9]{2}:[0-9]{2}``
``to_string_time_of_day()`` [src/calendar.cpp:638-663] branches three
ways on ``24_HOUR``: ``"military"`` gives ``"%02d%02d.%02d"``
(``0815.32``) which is colon-free and silently defeats the pattern;
``"24h"`` gives the fixed-width colon-delimited ``"%02d:%02d:%02d"``
[src/calendar.cpp:649], the only form the pattern matches; and the
shipped ``"12h"`` default [src/options.cpp:1868-1877] gives a
variable-width AM/PM form.  ``seed_options.py`` sets ``24_HOUR=24h``
precisely so the pattern is deterministic, and
:func:`assert_24_hour_option` REFUSES to read frames under any other
value -- and just as firmly when the value cannot be established at all,
because "unknown format" and "wrong format" have the same consequence:
zero matches, every duration collapsed to the floor, and a movie that
looks plausible and means nothing.  The one way past it is the
explicitly diagnostic ``--no-check-options``, which reports what it
found, refuses nothing, and yields a reading that must not be treated as
evidence for timing.

TRUSTED TOOL RESOLUTION, NO SHELL, AND ONE DECLARED WRITE
The legacy ``convert`` and ``identify`` commands are called directly:
they exist on both the ImageMagick 6.x and 7.x branches, whereas the
unified version-7 entry point does not exist on 6.x at all, so calling
only the legacy names is what lets this module run against either.
Code written against version-7 examples fails on 6.x with a
command-not-found error.  Every external command runs through
``subprocess.run([...])`` with an argument LIST and a timeout -- never a
shell, never a command assembled by string interpolation -- nothing is
evaluated dynamically, no path is joined without validation, and there
is no network surface of any kind.

The frame and the game-written ``options.json`` are opened for READING
only, and no game state, save file or memory is ever consulted: the
clock comes from rendered pixels and nothing else.  Every reading --
the clock, the coarse phrase, the date line, the per-pass evidence
behind ``--json`` -- leaves on STDOUT, with diagnostics on stderr, and
is not persisted here.  That is a boundary rather than an omission:
this module is called from the capture step, whose declared output is
one PNG, so a file written here would be a second output of a capture
and an artifact nobody asked for.

THE ONE EXCEPTION IS ASKED FOR BY NAME.  When a caller passes
``--audit``, :func:`append_date_audit` appends one record per frame to
``$PLAYTHROUGH_DATE_AUDIT`` -- the date evidence ``timeline.py`` needs
to tell a midnight rollover from a misread clock.  It lives outside the
manifest because that schema is exactly six fields, and it is written
HERE because reading the date in the same OCR pass as the clock is what
stops the two from ever disagreeing.  Without ``--audit`` there is no
write at all, and the caller that owns the session record decides
whether any of this evidence is kept and where.  No bytecode is written
either (``sys.dont_write_bytecode``, plus ``-B`` on every standalone
command, so importing the sibling cannot leave a ``__pycache__`` inside
the committed ``playthrough/`` tree).

A VERIFIED TOOLCHAIN
Two further conditions hold before any pixels are parsed, because this
module's output is what every duration in the finished movie is
computed from.  ``convert`` and ``tesseract`` are resolved to absolute
paths -- preferring env.sh's already-checked ``$PLAYTHROUGH_BIN_*`` --
and the binary and every directory above it are checked for
third-party ownership and group- or world-writability; one that fails
is treated as absent rather than run, which for ``convert`` means the
Pillow engine takes over loudly.  And the installed Pillow must be at
least PILLOW_MIN_VERSION -- the version requirements.txt pins -- since
every frame is decoded by Pillow and an older release is a different
decoder than the one this pipeline reviewed.  Both refusals have a
documented, per-invocation override for diagnosis
(``$PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1``,
``$PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW=1``); neither is ever the
default.

CLI CHANNELS
    $ python3 -B playthrough/tooling/ocr_clock.py FRAME
    08:00:00

    $ python3 -B playthrough/tooling/ocr_clock.py --field date FRAME
    Thursday, Dec 21

    $ python3 -B playthrough/tooling/ocr_clock.py --kv \
          --audit "$PLAYTHROUGH_DATE_AUDIT" --audit-frame 42 FRAME
    CLOCK=08:00:00
    TIME_PHRASE=
    CLOCK_DATE=Thursday, Dec 21

Standard output carries exactly the reading and nothing else, so
``CLOCK="$(ocr_clock.py "$FRAME")"`` is safe; an unreadable clock prints
nothing and exits 1, and a fault prints a diagnosis on stderr and exits
2.  Every warning, note and derivation goes to stderr, which keeps
engineering observations out of the in-character record.

Status 1 means ONE thing and nothing else: this module ran, read the
frame, and the frame held no such reading.  It is never the status of a
module that failed to start, because ``capture.sh`` acts on that
distinction -- it carries on past an unreadable clock and stops on a
fault -- and a missing dependency reported as "no clock on this frame"
would collapse every duration in the film to the floor while every
count still tallied.  Every import that can fail is therefore guarded
(see BOOTSTRAP IMPORTS below) and ``--preflight`` checks them all
before the session starts.

Anything MISCONFIGURED or suspicious is a warning and needs no logging
setup, while an ORDINARY unreadable frame -- what most menu keystrokes
capture -- is explained at INFO and surfaces with ``-v``.
"""
# Annotations are strings under PEP 563, which is what lets this module
# keep its `-> Image.Image` and `rect: sidebar_geometry.Rect`
# signatures while importing Pillow and the sibling module DEFENSIVELY
# below.  Without it, every annotation would be evaluated at def time
# and a missing dependency would take the module down before it could
# report the fault properly -- which is the exact defect the guarded
# imports exist to fix.
from __future__ import annotations

import argparse
import errno
import io
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

# ---------------------------------------------------------------------
# BOOTSTRAP IMPORTS -- WHY EVERY ONE OF THEM IS GUARDED
#
# This module's command line reserves its exit codes for meanings a
# shell caller acts on:
#
#     0  a reading was produced
#     1  the frame was read successfully and held no such reading
#     2  a FAULT -- something about the setup is wrong
#
# capture.sh treats 1 as a legitimate observation of a watchless
# survivor's sidebar and carries on; it treats 2 as a standing
# misconfiguration and stops.  An UNGUARDED import turns a missing
# dependency into a Python traceback and exit status 1, which the
# caller then records as "the clock could not be read" -- for every
# frame of the session, while every count still tallies and every
# duration collapses to the floor.  That is precisely the silent,
# plausible-looking failure this pipeline is built to make loud.
#
# So nothing that can be absent is imported bare.  Each failure is
# captured, and the point of use raises ToolchainError, which main()
# turns into the dedicated fault status with a diagnostic naming the
# package to install.
# ---------------------------------------------------------------------

# Pillow is a HARD runtime dependency of both preprocessing engines --
# even the ImageMagick path decodes convert's output with it -- so its
# absence is a fault, never an unreadable frame.  Its VERSION is
# imported in the same guarded breath, because the version floor below
# is a security condition and an unreadable version would otherwise
# have to be treated as a passing one.
try:
    from PIL import Image, ImageFilter, ImageOps
    from PIL import __version__ as PILLOW_VERSION
    PILLOW_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _pillow_import_error:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    PILLOW_VERSION = ""
    PILLOW_IMPORT_ERROR = _pillow_import_error

# Set BEFORE the sibling import below, which is the only import that
# can write into the repository working tree.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1, but this module is documented as runnable
# on its own -- and a standalone `python3 playthrough/tooling/
# ocr_clock.py ...` without that environment would compile the sibling
# to playthrough/tooling/__pycache__/, which .gitignore's terminal
# `!/playthrough/**` negation then makes COMMITTABLE.  A stray .pyc in
# a committed evidence tree is an artifact nobody authored, so the
# module refuses to create one whatever environment it is run under.
# The flag only suppresses .pyc writing; it changes nothing else, and
# it must be set before the import it protects because the interpreter
# consults it at compile time.
sys.dont_write_bytecode = True

try:
    import pytesseract
except ImportError:  # pragma: no cover - exercised only without the pin
    pytesseract = None

# The sibling module, imported flat as the repository's own tools/ do.
# A second failure means the checkout is broken rather than merely
# unpinned, but it is still recorded rather than raised: raising here
# would exit 1 and be read as an unreadable clock.
SIDEBAR_GEOMETRY_IMPORT_ERROR: Optional[BaseException] = None
try:
    import sidebar_geometry
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import sidebar_geometry
    except ImportError as _geometry_import_error:  # pragma: no cover
        sidebar_geometry = None  # type: ignore[assignment]
        SIDEBAR_GEOMETRY_IMPORT_ERROR = _geometry_import_error

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
# 0-59 [src/calendar.cpp:640-642], so 48:48:48 -- a shape the OCR
# really does return for a real frame -- is impossible and is declined.
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

# The lowest Pillow this module will decode a captured frame with, and
# it is exactly the version playthrough/tooling/requirements.txt pins.
#
# Every frame goes through Pillow -- the convert path decodes convert's
# output with it, the Pillow path does the whole chain in it, and
# _assert_rect_fits() opens the PNG with it -- so the decoder is the
# one component every reading in the finished movie depends on, and it
# is held to the reviewed pin rather than to whatever happens to be
# installed.  11.3.0 is that pin: the last release of the 11 line, so
# it carries every fix published in the series, and inside the range
# moviepy 2.2.1 declares (`pillow<12.0`), which is what keeps the
# pipeline's six pins one resolvable set with a silent `pip check`.
# requirements.txt records that trade-off in full.
#
# THIS TUPLE AND THAT PIN ARE ONE DECISION.  The diagnostics below
# quote this constant rather than a literal version, so a remediation
# message can never name a release this check would then refuse.
PILLOW_MIN_VERSION = (11, 3, 0)

# The pinned version as a requirement specifier, for the diagnostics
# that tell an operator what to install.  Derived, never repeated.
PILLOW_PIN_SPEC = "pillow==%s" % ".".join(
    str(part) for part in PILLOW_MIN_VERSION)

# The documented, deliberate override, for diagnosing on a host that
# cannot yet be moved to the pinned release.  It is loud, it is
# per-invocation, and it never becomes the default.
ENV_ALLOW_VULNERABLE_PILLOW = "PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW"

# env.sh exports the tool paths it has already verified as
# PLAYTHROUGH_BIN_<NAME>; this module prefers them and verifies
# whatever it uses either way.  The same variable env.sh reads is the
# one escape hatch.
TOOL_ENV_PREFIX = "PLAYTHROUGH_BIN_"
ENV_ALLOW_UNVERIFIED = "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES"

# The prescribed enlargement, in the two forms the two engines need.
# THEY MUST AGREE: RESIZE_PERCENT is what convert is told and
# SCALE_FACTOR is how the band offsets are computed afterwards, so a
# mismatch would slice the strip between text rows and read nothing.
# The agreement is asserted by this module's tests rather than trusted.
RESIZE_PERCENT = "200%"
SCALE_FACTOR = 2

# The one appended operator, and the reason it is needed: the game's
# Terminus face draws a slashed zero that the OCR engine reads as an 8,
# and half a pixel of blur after -normalize turns that "08:00:08" misread
# back into the "08:00:00" the pixels actually say.
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

# The date-evidence sidecar, exported by playthrough/tooling/env.sh as
# playthrough/build/frame_dates.jsonl.  Named here only so the help
# text can cite it; nothing is written unless --audit asks for it.
ENV_DATE_AUDIT = "PLAYTHROUGH_DATE_AUDIT"

FRAMES_REL_PARTS = ("playthrough", "frames")
FRAMES_DIR_NAME = "frames"
PNG_SUFFIX = ".png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# The repository-relative frame path, the one format capture.sh writes
# and manifest.py records.  Used only to label a date-audit record, so
# that a record identifies its own frame without the reader having to
# rebuild the name.
FRAME_FILE_FORMAT = "/".join(FRAMES_REL_PARTS) + "/frame_%05d" + \
    PNG_SUFFIX

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


class BootstrapError(ToolchainError):
    """A dependency this module cannot work without did not import.

    A subclass of :class:`ToolchainError` because that is exactly what
    it is -- a missing part of the toolchain -- and because every
    caller that already treats a toolchain fault as a fault then
    treats this one the same way.  It exists as its own class so the
    diagnostic can name the import that failed and the file that
    declares it.
    """


def _require_pillow() -> None:
    """Fail as a FAULT when Pillow is unavailable.

    Called at every point Pillow is actually used, rather than at
    import time, so that ``--explain``, ``--help`` and the module's
    pure text helpers keep working on a host where the pin has not
    been installed -- and so that the failure, when it comes, carries
    the dedicated fault status instead of the status that means "this
    frame held no clock".

    :raises BootstrapError: when ``PIL`` could not be imported.
    """
    if Image is None:
        raise BootstrapError(
            "Pillow (PIL) is not importable (%s), so no frame can be "
            "decoded at all.  This is a FAULT, not an unreadable "
            "clock: install playthrough/tooling/requirements.lock "
            "(%s) into the interpreter running this module"
            % (PILLOW_IMPORT_ERROR, PILLOW_PIN_SPEC))


def _require_sidebar_geometry() -> None:
    """Fail as a FAULT when the sibling geometry module is missing.

    :raises BootstrapError: when ``sidebar_geometry`` could not be
        imported from beside this file.
    """
    if sidebar_geometry is None:
        raise BootstrapError(
            "playthrough/tooling/sidebar_geometry.py is not importable "
            "(%s), so the sidebar crop cannot be computed.  This is a "
            "FAULT, not an unreadable clock: the module must sit "
            "beside this one"
            % SIDEBAR_GEOMETRY_IMPORT_ERROR)


def bootstrap_problems() -> List[str]:
    """Return one diagnostic per dependency that did not import.

    Exposed so a caller can PREFLIGHT the toolchain before it starts
    capturing -- ``capture.sh`` runs ``--preflight`` once before the
    first frame -- instead of discovering a missing package one
    unreadable-looking frame at a time.
    """
    problems = []
    for require in (_require_pillow, _require_sidebar_geometry):
        try:
            require()
        except BootstrapError as exc:
            problems.append(str(exc))
    return problems


class AuditError(OcrClockError):
    """The per-frame date evidence could not be recorded.

    Distinct from an unreadable date, which is recorded as ``null``.
    This is raised only when the sidecar itself cannot be written --
    a bad path, a bad frame index, or a write the module could not
    complete -- because timeline.py's rollover rule is only as good as
    the evidence it can read back.
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
    """Forget this session's environmental bookkeeping.

    Two caches, and both are about the ENVIRONMENT rather than about any
    reading -- there is no reading to reset, because none is ever kept:

    * the one-shot warnings, so a long-lived caller that wants each
      session's diagnostics complete gets them again rather than having
      them suppressed by a previous session's copy;
    * the verified-tool paths, because a tool is trusted on the strength
      of a check made when it was first resolved.  A caller whose PATH
      or whose filesystem has changed since then is entitled to have
      that check made again rather than inherited.

    Forward reference: ``_VERIFIED_TOOLS`` is defined further down, with
    ``verified_tool`` that populates it.  It is cleared here rather than
    beside it so that there is ONE way to say "start again", instead of
    a caller having to know how many caches this module keeps.
    """
    _WARNED.clear()
    _VERIFIED_TOOLS.clear()


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
# The two sibling types are named as forward references so that this
# alias -- which IS evaluated at import time, unlike an annotation --
# does not require the sibling module to have imported.  See BOOTSTRAP
# IMPORTS above.
RectLike = Union[
    None,
    str,
    "sidebar_geometry.Rect",
    "sidebar_geometry.SidebarGeometry",
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
    require: bool = True,
) -> Optional[str]:
    """Refuse to read frames unless the clock is the fixed-width form.

    ``military`` is the trap this exists for: it is a legal ``24_HOUR``
    value that renders ``0815.32`` [src/calendar.cpp:646], matches
    nothing this module looks for, and would therefore report every
    frame as unreadable -- collapsing every duration to the floor while
    every count still tallied.  The 12h default is equally hostile:
    variable padding and an AM/PM suffix [src/calendar.cpp:657-661].

    AN UNCONFIRMABLE FORMAT IS A FAULT, NOT A WARNING.  A missing
    options file and a missing ``24_HOUR`` key both mean the same thing
    -- that nothing here knows which of the three renderings the
    sidebar is using -- and reading on regardless is how the whole
    session becomes worthless without a single error: under ``military``
    or ``12h`` every frame reports an unreadable clock, every duration
    falls to the floor, every count still tallies, and the movie plays
    at a pace that means nothing.  The evidence that the format is right
    must exist BEFORE the frames are read, so this raises.

    That the engine only writes ``options.json`` on its first launch
    [src/path_info.cpp:167] is exactly why the file's absence matters
    here: it means the capture is running ahead of
    ``seed_options.py``, which is a mis-sequenced pipeline rather than
    an ordinary state to warn about.

    ``require=False`` is the explicitly diagnostic path, for inspecting
    a frame captured under some other configuration by hand.  It NEVER
    raises: it reports what it found on stderr, says plainly that the
    assertion was skipped, and returns whatever the value was.  A
    reading obtained that way carries no assurance about its format and
    must not feed a timeline.  :func:`read_time_phrase` and
    :func:`read_date_line` take that path because neither the coarse
    phrase nor the date line depends on the clock rendering at all --
    both read identically under all three values -- so refusing them
    over ``24_HOUR`` would reject a legitimate read.

    :returns: the option's value when it is ``24h``; the value found,
        or ``None`` when there was none, in the diagnostic mode.
    :raises OptionsError: when ``require`` is true and the value is
        anything other than ``24h``, including the cases where the
        options file cannot be read or carries no such value.
    """
    if options is None:
        try:
            options = sidebar_geometry.load_options(path=options_json)
        except sidebar_geometry.GeometryError as exc:
            if require:
                raise OptionsError(
                    "the game options file could not be read, so the "
                    "clock format cannot be confirmed: %s" % exc) from exc
            _warn_once(
                "24-hour-unreadable",
                "the game options file could not be read (%s); the "
                "format assertion was explicitly skipped, so this "
                "reading proves nothing about the clock rendering"
                % exc,
                notes)
            return None

    raw = options.get(OPT_24_HOUR)
    if raw is None:
        where = options_json or "the game options file"
        detail = (
            "no '%s' value could be found (looked in %s), so the clock "
            "rendering is unknown.  It is one of three: the fixed-width "
            "'%s' this module reads, '%s' which renders '0815.32', or "
            "'%s' which renders '8:15:32 AM' -- and under either of the "
            "latter two every frame reads as unreadable while every "
            "count still tallies"
            % (OPT_24_HOUR, where, OPT_24_HOUR_REQUIRED,
               OPT_24_HOUR_MILITARY, OPT_24_HOUR_12H))
        if require:
            raise OptionsError(
                "%s.  Run seed_options.py to set '%s' = '%s' before "
                "capturing, or pass require=False "
                "(--no-check-options) to inspect this frame as a "
                "diagnostic, accepting that its reading proves nothing "
                "about the format"
                % (detail, OPT_24_HOUR, OPT_24_HOUR_REQUIRED))
        _warn_once(
            "24-hour-absent",
            "%s; the format assertion was explicitly skipped, so this "
            "reading must not be treated as evidence for timing"
            % detail,
            notes)
        return None

    value = str(raw).strip()
    if value == OPT_24_HOUR_REQUIRED:
        LOG.debug("%s is '%s', the fixed-width form",
                  OPT_24_HOUR, value)
        return value

    if value == OPT_24_HOUR_MILITARY:
        message = (
            "%s is '%s', which renders the clock as '0815.32' "
            "[src/calendar.cpp:646].  Nothing here matches that, so "
            "every frame would report an unreadable clock and every "
            "duration would collapse to the floor.  Set '%s' with "
            "seed_options.py and recapture."
            % (OPT_24_HOUR, value, OPT_24_HOUR_REQUIRED))
    else:
        message = (
            "%s is '%s', not '%s'.  The '%s' form renders '8:15:32 AM' "
            "with variable padding [src/calendar.cpp:657-661], which is "
            "not the fixed-width reading this module and timeline.py "
            "depend on.  Set '%s' with seed_options.py and recapture."
            % (OPT_24_HOUR, value, OPT_24_HOUR_REQUIRED,
               OPT_24_HOUR_12H, OPT_24_HOUR_REQUIRED))

    if require:
        raise OptionsError(message)
    # Diagnostic mode reports the same finding without refusing: the
    # caller has said it is reading a frame from some other
    # configuration, and a phrase or a date line reads the same under
    # every value of this option.
    _warn_once("24-hour-offcontract", message, notes)
    return value


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
    _require_sidebar_geometry()
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
    _require_sidebar_geometry()
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
    _require_sidebar_geometry()
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
# command, no PATH search by the shell.  Beyond that, FINDING a tool on
# PATH is not the same as trusting it: PATH is mutable, this runs
# unattended, and what convert and tesseract produce is the clock
# reading every duration in the finished movie is computed from.  So
# the binary is resolved to an absolute path, and that path -- and every
# directory above it -- is checked for third-party ownership and for
# group- or world-writability before it is run.  A tool that fails the
# check is treated exactly like a missing one, with the reason given.
# ---------------------------------------------------------------------

def _tool_env_var(name: str) -> str:
    """Return env.sh's exported variable name for a tool."""
    safe = "".join(
        char if char.isalnum() else "_" for char in name)
    return TOOL_ENV_PREFIX + safe.upper()


def _writable_by_others(info: os.stat_result) -> bool:
    """True when group or other may write the thing described."""
    return bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _owned_by_a_third_party(info: os.stat_result) -> bool:
    """True when neither root nor this user owns the thing."""
    return info.st_uid not in (0, os.geteuid())


def _executable_complaint(path: str) -> Optional[str]:
    """Return why `path` cannot be trusted, or None when it can.

    The realpath is what is inspected, because a link's own permissions
    say nothing about the file that would actually run, and every
    ancestor directory is inspected too: a writable directory anywhere
    above the binary means it can be replaced between this check and
    the next invocation.
    """
    real = os.path.realpath(path)
    try:
        info = os.stat(real)
    except OSError as exc:
        return "%s cannot be examined: %s" % (real, exc)
    if not stat.S_ISREG(info.st_mode):
        return "%s is not a regular file" % real
    if not os.access(real, os.X_OK):
        return "%s is not executable" % real
    if _writable_by_others(info):
        return ("%s is mode %o, i.e. group- or world-writable"
                % (real, stat.S_IMODE(info.st_mode)))
    if _owned_by_a_third_party(info):
        return ("%s is owned by uid %d, which is neither root nor this "
                "user" % (real, info.st_uid))
    current = os.path.dirname(real)
    while True:
        try:
            directory = os.stat(current)
        except OSError as exc:
            return "%s cannot be examined: %s" % (current, exc)
        if _writable_by_others(directory):
            return ("%s is mode %o, i.e. group- or world-writable, so "
                    "%s can be replaced by another account"
                    % (current, stat.S_IMODE(directory.st_mode), real))
        if _owned_by_a_third_party(directory):
            return ("%s is owned by uid %d, which is neither root nor "
                    "this user" % (current, directory.st_uid))
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


_VERIFIED_TOOLS: Dict[str, str] = {}


def verified_tool(name: str) -> str:
    """Return an absolute, verified path for the tool called `name`.

    ``$PLAYTHROUGH_BIN_<NAME>`` is preferred, because env.sh has
    already verified it and using the same path keeps this module and
    the shell stages in step; otherwise PATH is searched once.  Either
    way the result is verified here rather than trusted.

    The returned path is NOT dereferenced through its final symlink:
    ImageMagick dispatches on argv[0], so ``/usr/bin/convert`` must stay
    spelled that way even though it links to ``magick-im7.q16``.  The
    link's TARGET is what gets inspected.

    :raises ToolchainError: when the tool is absent, or present and
        untrustworthy.  ``$PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1``
        downgrades the refusal to a warning for a diagnostic run.
    """
    cached = _VERIFIED_TOOLS.get(name)
    if cached is not None:
        return cached
    from_env = os.environ.get(_tool_env_var(name), "").strip()
    if from_env and os.path.isabs(from_env):
        candidate: Optional[str] = from_env
        origin = "$%s" % _tool_env_var(name)
    else:
        candidate = shutil.which(name)
        origin = "PATH"
    if not candidate:
        raise ToolchainError(
            "%s is not on PATH.  The capture and OCR toolchain is "
            "listed in playthrough/tooling/requirements.txt; on this "
            "host it comes from the imagemagick and tesseract-ocr "
            "packages." % name)
    complaint = _executable_complaint(candidate)
    if complaint is not None:
        if os.environ.get(ENV_ALLOW_UNVERIFIED, "") != "1":
            raise ToolchainError(
                "refusing to run %s from %s ('%s'): %s.  A tool that "
                "can be replaced by another account decides every "
                "clock reading in this session.  Fix the permissions, "
                "or set %s=1 to accept the risk explicitly for a "
                "diagnostic run."
                % (name, origin, candidate, complaint,
                   ENV_ALLOW_UNVERIFIED))
        _warn_once(
            "unverified-%s" % name,
            "running the unverified %s at '%s' because %s=1: %s"
            % (name, candidate, ENV_ALLOW_UNVERIFIED, complaint))
    _VERIFIED_TOOLS[name] = candidate
    LOG.debug("%s resolved from %s to %s", name, origin, candidate)
    return candidate


def tool_available(name: str) -> bool:
    """True when `name` is installed AND passes verification.

    A tool that cannot be trusted is reported and then treated as
    absent, which is what lets the caller fall back to another engine
    rather than run something it cannot vouch for.
    """
    try:
        verified_tool(name)
    except ToolchainError as exc:
        LOG.debug("%s is unusable: %s", name, exc)
        return False
    return True


def _pillow_version() -> Tuple[int, ...]:
    """Return the installed Pillow version as a tuple of integers."""
    parts: List[int] = []
    for piece in str(PILLOW_VERSION).split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _at_least(
    found: Sequence[int],
    wanted: Sequence[int],
) -> bool:
    """True when version `found` is at least version `wanted`.

    Both are padded to the same length before comparing, so 12.3 and
    12.3.0 are the same version, and each field is compared as a NUMBER
    -- 12.10 is newer than 12.3, which a string comparison gets wrong.
    """
    length = max(len(found), len(wanted))
    left = tuple(found) + (0,) * (length - len(found))
    right = tuple(wanted) + (0,) * (length - len(wanted))
    return left >= right


def pillow_complaint() -> Optional[str]:
    """Return why the installed Pillow is unfit, or None when it is.

    An unparseable version is reported rather than assumed to be fine:
    the point of the check is to be certain, and "I could not tell" is
    not certainty.
    """
    found = _pillow_version()
    wanted = ".".join(str(part) for part in PILLOW_MIN_VERSION)
    if not found:
        return ("the installed Pillow reports version %r, which cannot "
                "be compared against the required %s."
                % (PILLOW_VERSION, wanted))
    if not _at_least(found, PILLOW_MIN_VERSION):
        return ("Pillow %s is installed, but %s or newer is required: "
                "every captured frame is decoded by Pillow, %s is the "
                "version this pipeline pins and reviewed, and it is "
                "the last release of its series -- so anything older "
                "is a decoder missing fixes that one carries.  "
                "Install playthrough/tooling/requirements.lock (%s)."
                % (PILLOW_VERSION, wanted, wanted, PILLOW_PIN_SPEC))
    return None


def assert_pillow_supported(
    notes: Optional[List[str]] = None,
) -> None:
    """Refuse to decode a frame with a Pillow older than the pin.

    :raises ToolchainError: unless
        ``$PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW=1``, which downgrades the
        refusal to a warning recorded in the reading's notes.
    """
    complaint = pillow_complaint()
    if complaint is None:
        return
    if os.environ.get(ENV_ALLOW_VULNERABLE_PILLOW, "") != "1":
        raise ToolchainError(
            "%s  Set %s=1 to read frames with it anyway for a "
            "diagnostic run." % (complaint, ENV_ALLOW_VULNERABLE_PILLOW))
    _warn(
        "%s Continuing because %s=1"
        % (complaint, ENV_ALLOW_VULNERABLE_PILLOW), notes)


def _run(
    command: List[str],
    timeout: int,
    what: str,
    stdin_bytes: Optional[bytes] = None,
) -> bytes:
    """Run one external command and return its standard output."""
    command = [verified_tool(command[0])] + list(command[1:])
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
    if engine == ENGINE_CONVERT and not tool_available(CONVERT_BIN):
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
    _require_pillow()
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
    _require_pillow()
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

    BOTH front ends are bounded by :data:`TESSERACT_TIMEOUT`.  The
    subprocess path always was; the pytesseract path defaults to
    ``timeout=0``, meaning no limit at all, so it is passed explicitly.
    Without it a single wedged tesseract child would hang the capture
    loop indefinitely, mid-session, with the game still running and no
    error to show for it -- and a hung tool is a fault to report, not a
    reason to wait forever.

    :raises ToolchainError: when tesseract is absent, exceeds the
        timeout, or fails.  A blank result is NOT an error: an empty
        band legitimately reads empty.
    """
    config = "--psm %d" % psm
    if ocr_engine == OCR_PYTESSERACT:
        if pytesseract is None:
            raise ToolchainError(
                "pytesseract is not importable; install "
                "playthrough/tooling/requirements.txt or pass "
                "ocr_engine='%s'" % OCR_TESSERACT)
        # pytesseract would otherwise search PATH itself, bypassing the
        # verification above; pointing it at the checked binary keeps
        # both OCR front ends on exactly the same tesseract.
        pytesseract.pytesseract.tesseract_cmd = verified_tool(
            TESSERACT_BIN)
        try:
            return pytesseract.image_to_string(
                image, config=config, timeout=TESSERACT_TIMEOUT)
        except RuntimeError as exc:
            # pytesseract's own timeout_manager raises exactly
            # RuntimeError("Tesseract process timeout") when the child
            # outlives the limit; it is reported as the timeout it is
            # rather than as an anonymous runtime failure.
            if "timeout" in str(exc).lower():
                raise ToolchainError(
                    "tesseract did not finish within %d s via "
                    "pytesseract and was stopped; the frame was left "
                    "unread rather than waited on indefinitely"
                    % TESSERACT_TIMEOUT) from exc
            raise ToolchainError(
                "pytesseract failed with %s: %s"
                % (type(exc).__name__, exc)) from exc
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
    0-59 [src/calendar.cpp:640-642].  ``48:48:48`` -- a shape the OCR
    really does return for a real frame -- is therefore impossible, and
    saying so is how a confident misread is kept out of the record.
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
    _require_pillow()
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

    # Always consulted, never skipped silently.  `check_options` selects
    # which of the two documented behaviours applies -- the production
    # gate that refuses an unconfirmed clock rendering, or the
    # explicitly diagnostic report that names what it found and refuses
    # nothing -- so there is no path on which the format simply goes
    # unmentioned.
    assert_24_hour_option(
        options_json=options_json, notes=notes, require=check_options)

    rectangle, rows = resolve_rect(
        rect, row_height, notes, options_json=options_json)
    # Pillow decodes this frame whichever engine is chosen, so its
    # fitness is asserted before a single byte of the PNG is parsed.
    assert_pillow_supported(notes)
    chosen_engine = resolve_engine(engine, notes)
    chosen_ocr = resolve_ocr_engine(ocr_engine, notes)
    frame_size = _assert_rect_fits(resolved_png, rectangle)
    LOG.debug("reading %s (%dx%d) at %s, %d px rows, %s + %s",
              resolved_png, frame_size[0], frame_size[1],
              rectangle.geometry, rows, chosen_engine, chosen_ocr)

    # `passes is None` means "use the default table"; an explicitly
    # supplied sequence is honoured exactly as given, INCLUDING an empty
    # one, which is refused.  Treating an empty list as "no preference"
    # -- which a plain truthiness test does -- would silently substitute
    # the defaults for a caller who had computed a pass list and got
    # nothing, reading the frame with passes it never asked for and
    # making this error unreachable.
    if passes is None:
        selected = PASSES
        if not selected:
            # Reachable only if the module's own table were emptied,
            # which is exactly the regression this guards: reading
            # NOTHING must be an error, never an unreadable frame,
            # because an unreadable frame is an ordinary answer and
            # would hide the defect behind every menu keystroke.
            raise OcrClockError(
                "no OCR pass is configured at all, so nothing would "
                "be read and every frame would report as unreadable; "
                "the PASSES table must not be empty")
    else:
        selected = tuple(passes)
        if not selected:
            raise OcrClockError(
                "an empty OCR pass list was given explicitly, so "
                "nothing would be read; pass None to use the default "
                "table of %d passes" % len(PASSES))

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
# The per-frame date audit
#
# WHY THIS EXISTS.  timeline.py has to decide, for every pair of
# consecutive frames, whether a clock that went backwards means the
# night rolled over or means the reading was wrong.  From the clock
# alone those two are indistinguishable -- 08:00:00 followed by
# 06:00:00 is either a 22-hour day or a misread digit, and guessing
# "rollover" invents 22 hours of game time that nobody played.  The
# sidebar draws the date on its own line [src/display.cpp:193-205], and
# THAT is the evidence which settles it.
#
# This module could already read that line; what was missing was a
# place to keep it.  The manifest cannot hold it: its schema is exactly
# six fields and adding a seventh would create the second source of
# truth the pipeline is built to avoid.  So the date is persisted
# beside the build products, in an append-only JSONL sidecar at
# $PLAYTHROUGH_DATE_AUDIT (playthrough/build/frame_dates.jsonl), one
# record per captured frame, written by the SAME read that capture.sh
# already performs for the clock -- no second OCR pass, no second
# opportunity for the two to disagree.
#
# The record, one JSON object per line:
#
#     {"frame": 42,
#      "file": "playthrough/frames/frame_00042.png",
#      "clock": "08:15:32",       # or null
#      "phrase": null,            # or the coarse phrase, verbatim
#      "date": "Spring, day 3",   # or null
#      "agreement": true}         # false when passes disagreed
#
# Every field is what was READ, never what would be convenient:
# `null` is the honest answer for an unreadable value and the consumer
# is required to treat it as unknown rather than as unchanged.
# timeline.py reads this file with the standard library alone -- it must
# never import this module, which would make Pillow and pytesseract
# hard dependencies of the render stage -- so DATE_AUDIT_FIELDS below
# is the contract between the two, and the round-trip is asserted by
# test_timeline.py against a sidecar this writer produced.
# ---------------------------------------------------------------------

DATE_AUDIT_FIELDS = ("frame", "file", "clock", "phrase", "date",
                     "agreement")

# The frame index bounds manifest.py enforces, restated rather than
# imported for the same reason the clock vocabulary is: this module's
# only declared internal dependency is sidebar_geometry.
MIN_FRAME_INDEX = 1
MAX_FRAME_INDEX = 99999


def _validated_audit_frame(frame: object) -> int:
    """Return `frame` as a usable frame index, or raise."""
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise AuditError(
            "the audit frame index must be an integer, got %s (%r)"
            % (type(frame).__name__, frame))
    if frame < MIN_FRAME_INDEX or frame > MAX_FRAME_INDEX:
        raise AuditError(
            "the audit frame index must be between %d and %d, got %d"
            % (MIN_FRAME_INDEX, MAX_FRAME_INDEX, frame))
    return frame


def approved_artifact_root(root: Optional[str] = None) -> str:
    """Return the tree this module may write inside, absolute.

    Derived from THIS FILE's location and from nothing else: the
    ``playthrough`` directory that holds ``tooling``.  No environment
    variable participates, because the one thing this module writes is
    evidence about a captured session, and a variable that could move
    it somewhere else could move it on top of something else.

    ``root`` is a CALL SITE's argument and nothing else -- argparse
    never produces one and ``main()`` never passes one.  It exists so a
    test can hold this writer to a temporary directory it owns instead
    of appending to the committed evidence, which is the same seam
    timeline.py and manifest.py already carry.
    """
    if root is None:
        tooling = os.path.dirname(os.path.abspath(__file__))
        return os.path.realpath(os.path.dirname(tooling))
    if isinstance(root, os.PathLike):
        root = os.fspath(root)
    if not isinstance(root, str) or not root.strip():
        raise AuditError(
            "the approved root must be a non-empty string path, got %r"
            % (root,))
    resolved = os.path.realpath(root)
    if not os.path.isdir(resolved):
        raise AuditError("no approved root at %s" % resolved)
    return resolved


def _validated_audit_path(path: object,
                          root: Optional[str] = None) -> str:
    """Return an absolute audit path that is safe to append to.

    THE ONE WRITE THIS MODULE MAKES IS HELD TO THE SAME CONTRACT AS
    EVERY OTHER WRITE IN THIS TREE.  Shape first -- a non-empty string
    or os.PathLike with no NUL byte, naming a regular file rather than
    a directory -- then position: the fully resolved path must stay
    inside :func:`approved_artifact_root`, and neither it nor any
    component below that root may be a symbolic link.  Containment
    alone would not be enough, because a link planted inside the tree
    still points at something else inside the tree, and the sidecar is
    appended to: one link could grow the manifest, a frame or the
    movie by a line of JSON while this function reported success.

    The parent directory must already exist: creating it here would let
    a mistyped path grow a second sidecar somewhere else in the tree,
    and directory creation is playthrough_mkdirs()' job in
    playthrough/tooling/env.sh.
    """
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if not isinstance(path, str):
        raise AuditError(
            "the audit path must be a string, got %s"
            % type(path).__name__)
    if not path.strip():
        raise AuditError("the audit path must not be empty")
    if "\x00" in path:
        raise AuditError("the audit path must not contain a NUL byte")
    resolved = os.path.abspath(path)
    if os.path.isdir(resolved):
        raise AuditError(
            "the audit path names a directory, not a file: %s"
            % resolved)
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise AuditError(
            "the audit path is not a regular file: %s" % resolved)

    approved = approved_artifact_root(root)
    canonical = os.path.realpath(resolved)
    if not _is_inside(canonical, approved):
        raise AuditError(
            "the audit path must stay inside %s, but %s resolves to "
            "%s.  This module appends evidence about a captured "
            "session; it does not write anywhere else"
            % (approved, resolved, canonical))
    if os.path.islink(resolved):
        raise AuditError(
            "the audit path is a symbolic link: %s.  This module "
            "appends to files, it does not follow links to them"
            % resolved)
    walked = approved
    for part in os.path.relpath(resolved, approved).split(os.sep):
        if part in ("", os.curdir):
            continue
        walked = os.path.join(walked, part)
        if os.path.islink(walked):
            raise AuditError(
                "the audit path has a symlinked component at %s; a "
                "link there could append this record to another "
                "artifact inside %s" % (walked, approved))

    parent = os.path.dirname(resolved)
    if not os.path.isdir(parent):
        raise AuditError(
            "the directory for the date audit does not exist: %s -- "
            "run playthrough_mkdirs (playthrough/tooling/env.sh) first"
            % parent)
    return resolved


def _audit_scalar(value: Optional[str]) -> Optional[str]:
    """Return a one-line reading, or None.  Never a guess."""
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None


def date_audit_record(frame: int,
                      reading: SidebarReading) -> Dict[str, object]:
    """Build the audit record for one frame's reading.

    Pure: it touches no file, so a caller can inspect exactly what
    would be written.  The frame index is the caller's -- session.py
    owns the counter and this module never generates one.
    """
    index = _validated_audit_frame(frame)
    return {
        "frame": index,
        "file": FRAME_FILE_FORMAT % index,
        "clock": _audit_scalar(reading.clock),
        "phrase": _audit_scalar(reading.phrase),
        "date": _audit_scalar(reading.date),
        "agreement": bool(reading.agreement),
    }


def append_date_audit(path: str, frame: int,
                      reading: SidebarReading,
                      root: Optional[str] = None
                      ) -> Dict[str, object]:
    """Append one frame's date evidence to the sidecar.

    Append-only, one line, flushed and forced to the device: this is
    evidence about what the sidebar showed, and evidence is neither
    rewritten nor reported as stored until it is.  A repeated frame
    index is NOT an error here -- a recapture legitimately produces a
    second record for the same frame -- and resolving that is the
    consumer's job, which takes the last record for an index and warns
    when two disagree.

    :returns: the record exactly as written.
    :raises AuditError: for a bad path, a bad index, or a write this
        module could not complete.
    """
    resolved = _validated_audit_path(path, root)
    record = date_audit_record(frame, reading)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    # O_NOFOLLOW as well as the check above: the check reads the path
    # and the open acts on it, and a link planted between the two
    # would otherwise be followed.  The kernel refuses the final
    # component instead, so the race has no window at all.
    try:
        descriptor = os.open(
            resolved,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
            0o600)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise AuditError(
                "the audit path became a symbolic link: %s.  Refusing "
                "to append through it" % resolved) from exc
        raise AuditError(
            "could not open the date-evidence sidecar %s (%s)"
            % (resolved, exc)) from exc
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8",
                       newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise AuditError(
            "could not append frame %d's date evidence to %s (%s); the "
            "sidecar is what lets timeline.py tell a midnight rollover "
            "from a misread clock, so a write that cannot be completed "
            "is reported rather than passed over"
            % (record["frame"], resolved, exc)) from exc
    LOG.debug("date audit: frame %d -> %s (date %r, clock %r)",
              record["frame"], resolved, record["date"],
              record["clock"])
    return record


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
  2  a fault: bad or missing frame, unusable crop, missing tool, a
     24_HOUR option that is not 24h, or a date audit that could not be
     written

examples (run from the repository root; this file is tracked mode 644
and is not on PATH, so it is always invoked through the interpreter,
with -B so no __pycache__ is left in the tree):
  # the pipeline's own call, crop computed from configuration
  python3 -B playthrough/tooling/ocr_clock.py \\
      playthrough/frames/frame_00042.png

  # the crop capture.sh already has in hand
  python3 -B playthrough/tooling/ocr_clock.py --rect \\
      "$(python3 -B playthrough/tooling/sidebar_geometry.py)" "$FRAME"

  # audit one frame: run every pass and show the evidence
  python3 -B playthrough/tooling/ocr_clock.py --cross-check -v "$FRAME"

  # the whole reading, for a tool rather than a human
  python3 -B playthrough/tooling/ocr_clock.py --json "$FRAME"

  # what a watchless survivor's sidebar says
  python3 -B playthrough/tooling/ocr_clock.py --field phrase "$FRAME"

  # capture.sh's own call: every reading from ONE OCR pass, and the
  # date evidence timeline.py needs persisted in the same breath
  python3 -B playthrough/tooling/ocr_clock.py --kv \\
      --audit "$PLAYTHROUGH_DATE_AUDIT" --audit-frame 42 "$FRAME"

note on --kv: the values are printed unquoted as KEY=value, one per
line, so a shell reads them with `while IFS='=' read -r key value`.
NEVER eval that output -- a sidebar phrase is OCR text, not code.
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
        "--kv", action="store_true",
        help=("print CLOCK=, TIME_PHRASE= and CLOCK_DATE= as unquoted "
              "KEY=value lines, so one read serves a shell caller that "
              "needs all three; parse with IFS='=' read, never eval"))
    parser.add_argument(
        "--audit", metavar="PATH",
        help=("append this frame's date evidence to an append-only "
              "JSONL sidecar (the pipeline passes "
              "$%s); requires --audit-frame" % ENV_DATE_AUDIT))
    parser.add_argument(
        "--audit-frame", type=int, metavar="N",
        help=("the frame index to record in the audit sidecar; "
              "session.py owns this counter, so it is never derived "
              "from the file name"))
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
        "--preflight", action="store_true",
        help=("check that every dependency this module needs is "
              "importable and exit: 0 when it is, 2 when it is not.  "
              "Run it ONCE before capturing, so a missing package is a "
              "fault reported before any frame exists rather than an "
              "unreadable clock reported for every frame"))
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
    """Read one frame and print the requested reading, or nothing.

    The three exit codes are a contract with ``capture.sh`` and are
    kept strictly apart: 0 carries a reading on stdout, 1 means the
    frame was read and held no such reading, and 2 means a FAULT --
    including a dependency that did not import, which is why the
    bootstrap check below runs before anything else and why every
    fragile import in this module is guarded.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_cli_logging(args.verbose)

    problems = bootstrap_problems()
    if args.preflight:
        for problem in problems:
            LOG.error("%s", problem)
        if problems:
            return EXIT_FAULT
        LOG.info("every dependency of ocr_clock.py is importable")
        return EXIT_OK
    if problems:
        # Reported here rather than at import time so that this status
        # is 2 (a fault) and never 1 (an unreadable observation).
        for problem in problems:
            LOG.error("%s", problem)
        return EXIT_FAULT

    if args.explain:
        # Only ever stdout when there is no reading to print there.
        print(explain_text(),
              file=sys.stdout if args.frame is None else sys.stderr)
        if args.frame is None:
            return EXIT_OK
    if args.frame is None:
        parser.error("a frame is required unless --explain is given")
    if args.audit and args.audit_frame is None:
        parser.error(
            "--audit needs --audit-frame N: the record identifies the "
            "frame it describes, and that index belongs to the session "
            "counter rather than being guessed from a file name")
    if args.audit_frame is not None and not args.audit:
        parser.error(
            "--audit-frame is only meaningful with --audit PATH")
    if args.json and args.kv:
        parser.error(
            "--json and --kv are two different output shapes; ask for "
            "one")

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

    # The audit is written BEFORE anything reaches stdout, so a sidecar
    # that could not be recorded is a fault with an empty stdout rather
    # than a value the caller banks while the evidence behind it was
    # lost.
    if args.audit:
        try:
            append_date_audit(args.audit, args.audit_frame, reading)
        except OcrClockError as exc:
            LOG.error("%s", exc)
            return EXIT_FAULT

    if args.json:
        print(json.dumps(reading.as_dict(), indent=2, sort_keys=True))
        return EXIT_OK if reading.readable else EXIT_UNREADABLE

    if args.kv:
        # Empty on the right of the '=' is the honest form of "not
        # read": the shell then holds an empty variable rather than a
        # placeholder that looks like a reading.
        for key, raw in (("CLOCK", reading.clock),
                         ("TIME_PHRASE", reading.phrase),
                         ("CLOCK_DATE", reading.date)):
            print("%s=%s" % (key, _audit_scalar(raw) or ""))
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
