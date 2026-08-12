#!/usr/bin/env python3
"""Read the Cataclysm-DDA sidebar clock out of a captured frame.

Crop the computed sidebar column out of a captured PNG, preprocess it
for legibility, run OCR over it, extract the clock by regular
expression, and return the matched string -- or NOTHING AT ALL.

THE HONESTY CONTRACT: None VERSUS AN EXCEPTION
This module is the single place where "never fabricate" is enforced in
code, because every frame duration, the pacing of the movie and the
caption timings rest on it never inventing a number.  The contract has
four clauses:

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
``+repage`` resets the virtual canvas the crop leaves behind,
``-colorspace Gray`` removes chroma noise from coloured text,
``-resize 200%`` enlarges 8x16 terminal glyphs tesseract cannot read at
native size, and ``-normalize`` stretches contrast so strokes separate.
``$RECT`` is COMPUTED at run time by :mod:`sidebar_geometry`.

Two refinements are appended rather than substituted, each documented
at its own definition: reading ROW BY ROW under ``--psm 7`` with
per-row normalisation, because tesseract's layout analysis mangles the
clock line when the whole column is read at once and a column-global
``-normalize`` leaves it too dim to match; and :data:`DESLASH_BLUR`
after ``-normalize``.  The unblurred prescribed chain still runs as its
own pass on every frame the blurred form cannot read.

The passes are ordered, documented and deterministic (:data:`PASSES`),
and ``cross_check=True`` runs all of them and requires that they AGREE.
A frame whose readers disagree is reported as UNREADABLE rather than
resolved by pass order -- with one exception, and it is about proof
rather than preference: an EXACT glyph match stands, meaning every
character's ink is bit-identical to what the attested
``data/font/Terminus.ttf`` draws for it, so the engine demonstrably drew
that time in those pixels.  Anything short of a proof is withheld.
capture.sh always cross-checks, so a style-induced misread cannot
become the record.

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
``48:48:48`` matches the pattern but cannot be a clock.  Such a reading
is declined with a warning and the search continues through the same
real OCR output.  Declining is not repair: no digit is substituted, no
value reconstructed, and if nothing possible is found the answer is
``None``.

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
absence.  A ``"???"`` sidebar often comes back from OCR as something
other than the literal marker, and that is reported as ``None``.

WHY THE PATTERN IS EXACTLY ``[0-9]{2}:[0-9]{2}:[0-9]{2}``
``to_string_time_of_day()`` [src/calendar.cpp:638-663] branches three
ways on ``24_HOUR``: ``"military"`` gives ``"%02d%02d.%02d"``
(``0815.32``) which is colon-free and silently defeats the pattern;
``"24h"`` gives the fixed-width colon-delimited ``"%02d:%02d:%02d"``
[src/calendar.cpp:649], the only form the pattern matches; and the
shipped ``"12h"`` default [src/options.cpp:1868-1877] gives a
variable-width AM/PM form.  ``seed_options.py`` sets ``24_HOUR=24h`` so
the pattern is deterministic, and :func:`assert_24_hour_option` REFUSES
to read frames under any other value -- and just as firmly when the
value cannot be established at all, because "unknown format" and "wrong
format" have the same consequence: zero matches, every duration
collapsed to the floor, and a movie that looks plausible and means
nothing.  The one way past it is the explicitly diagnostic
``--no-check-options``, whose reading must not be treated as evidence
for timing.

TRUSTED TOOL RESOLUTION, NO SHELL, AND ONE DECLARED WRITE
The legacy ``convert`` and ``identify`` commands are called directly,
because they exist on both the ImageMagick 6.x and 7.x branches while
the unified version-7 entry point does not exist on 6.x at all.  Every
external command runs through ``subprocess.run([...])`` with an
argument LIST and a timeout -- never a shell, never a command assembled
by string interpolation -- nothing is evaluated dynamically, no path is
joined without validation, and there is no network surface of any kind.

The frame and the game-written ``options.json`` are opened for READING
only, and no game state, save file or memory is ever consulted: the
clock comes from rendered pixels and nothing else.  Every reading
leaves on STDOUT, with diagnostics on stderr, and is not persisted
here -- a boundary rather than an omission, since the capture step's
declared output is one PNG and a file written here would be a second
output of a capture.

THE ONE EXCEPTION IS ASKED FOR BY NAME.  When a caller passes
``--audit``, :func:`append_date_audit` appends one record per frame to
``$PLAYTHROUGH_DATE_AUDIT`` -- the date evidence ``timeline.py`` needs
to tell a midnight rollover from a misread clock.  It lives outside the
manifest because that schema is exactly six fields, and it is written
HERE because reading the date in the same OCR pass as the clock is what
stops the two from ever disagreeing.  Without ``--audit`` there is no
write at all.  No bytecode is written either
(``sys.dont_write_bytecode``, plus ``-B`` on every standalone command,
so importing the sibling cannot leave a ``__pycache__`` inside the
committed ``playthrough/`` tree).

A VERIFIED TOOLCHAIN
Two conditions hold before any pixels are parsed, because this module's
output is what every duration in the finished movie is computed from.
``convert`` and ``tesseract`` are resolved to absolute paths --
preferring env.sh's already-checked ``$PLAYTHROUGH_BIN_*`` -- and each
binary and every directory above it is checked for third-party
ownership and group- or world-writability; one that fails is treated as
absent rather than run, which for ``convert`` means the Pillow engine
takes over loudly.  And the installed Pillow must satisfy
:data:`PILLOW_MIN_VERSION`, which tracks the requirements-file pin.
Each refusal has a documented, loud, per-invocation override defined
alongside it; neither is ever the default.

CLI CHANNELS
    $ . playthrough/tooling/env.sh
    $ OC='playthrough/tooling/ocr_clock.py'
    $ "$PLAYTHROUGH_PYTHON" -B "$OC" FRAME
    08:00:00

    $ "$PLAYTHROUGH_PYTHON" -B "$OC" --field date FRAME
    Thursday, Dec 21

    $ "$PLAYTHROUGH_PYTHON" -B "$OC" --kv \
          --audit "$PLAYTHROUGH_DATE_AUDIT" --audit-frame 42 FRAME
    CLOCK=08:00:00
    TIME_PHRASE=
    CLOCK_DATE=Thursday, Dec 21

``env.sh`` exports ``PLAYTHROUGH_PYTHON``, the pinned CPython 3.12 that
carries Pillow and pytesseract; the system ``python3`` does not.

Standard output carries exactly the reading and nothing else, so
capturing it in a ``CLOCK="$(...)"`` substitution is safe; an
unreadable clock prints nothing and exits 1, and a fault prints a
diagnosis on stderr and exits 2.  Every warning, note and derivation
goes to stderr, which keeps engineering observations out of the
in-character record.

Status 1 means ONE thing: this module ran, read the frame, and the
frame held no such reading.  It is never the status of a module that
failed to start, because ``capture.sh`` acts on that distinction -- it
carries on past an unreadable clock and stops on a fault -- and a
missing dependency reported as "no clock on this frame" would collapse
every duration in the film to the floor while every count still
tallied.  Every import that can fail is therefore guarded (see
BOOTSTRAP IMPORTS below) and ``--preflight`` checks them all before the
session starts.  An ORDINARY unreadable frame -- what most menu
keystrokes capture -- is explained at INFO and surfaces with ``-v``.
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
import functools
import hashlib
import io
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys

try:
    # POSIX only, and present on every platform this pipeline
    # supports.  Guarded so the module stays importable where it
    # is not, with decode_limits degrading to a no-op rather
    # than the module failing to load.
    import resource
except ImportError:            # pragma: no cover - POSIX only
    resource = None

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
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    from PIL import __version__ as PILLOW_VERSION
    PILLOW_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _pillow_import_error:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageFilter = None
    ImageFont = None
    ImageOps = None
    PILLOW_VERSION = ""
    PILLOW_IMPORT_ERROR = _pillow_import_error

# NumPy is the same kind of dependency for the exact glyph reader: a
# cell-by-cell comparison against the game's own font is a boolean
# array operation, and the pin is already required by the render stage.
try:
    import numpy
    NUMPY_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _numpy_import_error:  # pragma: no cover
    numpy = None
    NUMPY_IMPORT_ERROR = _numpy_import_error

# Set BEFORE the sibling import below, which is the only import that can write
# into the repository working tree.  env.sh exports PYTHONDONTWRITEBYTECODE=1,
# but this module is documented as runnable on its own -- and a standalone
# `python3 playthrough/tooling/ ocr_clock.py ...` without that environment
# would compile the sibling to playthrough/tooling/__pycache__/, which
# .gitignore's terminal `!/playthrough/**` negation then makes COMMITTABLE.  A
# stray .pyc in a committed evidence tree is an artifact nobody authored, so
# the module refuses to create one whatever environment it is run under.
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
        sidebar_geometry = None
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

# The lowest Pillow this module will decode a captured frame with, and it is
# exactly the version playthrough/tooling/requirements.txt pins.  THIS TRACKS
# THE PIN, and that is the whole contract: it is exactly `pillow==11.3.0` from
# playthrough/tooling/requirements.txt, so an interpreter that satisfies the
# requirements file satisfies this check and one that does not is named before
# a frame is read rather than after a duration comes out wrong.
PILLOW_MIN_VERSION = (11, 3, 0)

# The pinned version as a requirement specifier, for the diagnostics
# that tell an operator what to install.  Derived, never repeated,
# so a remediation message can never name a release this check would
# then refuse.
PILLOW_PIN_SPEC = "pillow==%s" % ".".join(
    str(part) for part in PILLOW_MIN_VERSION)

# The documented, deliberate override, for diagnosing on a host whose
# interpreter carries an older Pillow than the pin.  It is loud, it is
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

# The Pillow equivalent of the appended blur.  Radius 0.8-1.0 reproduces
# a match where radius 0.5 does not, so the two engines are equivalent in
# kind rather than in arithmetic, and the difference is recorded in
# ENGINE_NOTES.
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

# ---------------------------------------------------------------------
# THE GLYPH GRID, and why an exact reader had to be added
#
# Every OCR pass below fails on this host in one specific way, measured
# on a real captured frame whose Time row says 08:00:00: the prescribed
# chain reads "Time: 08:80:88", and no amount of blur, threshold,
# morphology or upscaling recovers it.  The cause is the game's own
# typeface.  data/font/Terminus.ttf draws a SLASHED zero, and a slashed
# zero is an 8 to every engine tesseract has -- 200% + -normalize +
# -gaussian-blur 0x0.5 was calibrated against a frame where it happened
# to survive, and it does not survive here.
#
# The sidebar, however, is not a photograph of text.  It is a character
# grid: FONT_WIDTH x FONT_HEIGHT cells, no anti-aliasing under the
# "Bitmap" hinting the engine's own config/fonts.json asks for, drawn
# from a font file that ships in this repository.  So each cell can be
# compared against the SAME font rendered by Pillow, and the comparison
# is exact rather than statistical: at size 16 Pillow reproduces the
# engine's slashed-zero bitmap pixel for pixel (verified against the
# captured frame before this was written).
#
# That makes this pass strictly more truthful than the OCR ones, so it
# runs FIRST, with the tesseract passes behind it for any frame it
# cannot decode.  It is also free: it spends no OCR calls at all, which
# removes ~139 tesseract invocations from every captured frame.
#
# BUT NOT EVERY CHARACTER IT RETURNS IS A PROOF.  A cell either matches
# a template bit for bit -- which is proof -- or it matches one template
# UNIQUELY AND SEPARATELY inside a radius under half the distance
# between templates, which is a very tightly bounded near match and
# still not proof -- or it becomes a space.  read_column_by_glyphs()
# reports which characters were exact, and read_sidebar() uses that to
# decide whether this pass may stand against a disagreeing OCR pass: an
# exact reading may, a near one must be confirmed.
#
# It reads only what the game can draw in that column, and it never
# guesses: a cell that matches no template within GLYPH_MAX_DISTANCE
# becomes a space, and a row that decodes to nothing is dropped.  The
# resulting text is handed to the very same find_clocks(),
# extract_date() and extract_phrase() the OCR passes feed, so the
# honesty rules downstream -- impossible clocks declined, nothing
# repaired -- apply unchanged.
# ---------------------------------------------------------------------

GLYPH_PASS_NAME = "glyph-grid"

# The engine's interface typeface, from config/fonts.json's own
# `typeface` list.  Resolved relative to the repository root, which is
# this module's grandparent: playthrough/tooling -> playthrough -> root.
GLYPH_FONT_PARTS = ("data", "font", "Terminus.ttf")

# The sha256 of that file as this repository ships it.  A FONT IS NATIVE
# PARSER INPUT -- FreeType, reached through Pillow -- and the path above
# is derived rather than configured, which is safe until somebody puts a
# different file there.  Attesting the bytes turns "the font we expect"
# into a checkable fact; see _attested_font().
GLYPH_FONT_SHA256 = (
    "e0d645677fa32557a16b3be8533c552c2939fd507d7b8515ead5d9cf494cb2a6")

# A hard ceiling on the pixels any capture may declare, so a malformed
# or crafted header cannot ask for an unbounded allocation.  The root
# window these captures photograph is 1920x1080 = 2 073 600 pixels, so
# 64 megapixels is generous by a factor of thirty and still far below
# Pillow's own 89-megapixel bomb threshold.
MAX_PIXELS = 64 * 1024 * 1024

# A hard ceiling on the BYTES one capture may occupy, which is a different
# question from its pixel count and is asked earlier.  The provenance check now
# reads the file it validated (see read_verified_frame), so a planted enormous
# file would otherwise be read into memory before anything looked at its
# header.
MAX_FRAME_BYTES = 64 * 1024 * 1024

# The CPU budget, in seconds, granted to one decode.  MEASURED, NOT GUESSED:
# twenty consecutive open_png() calls over a real 1920x1080 capture on this
# host cost 0.0903 s of process CPU time, 0.0045 s each.
DECODE_CPU_SECONDS = 30

# Everything the sidebar's clock, date and coarse-time rows can contain.
# Ordered so that a tie prefers a digit over a letter, which matters for
# nothing except reproducibility.
GLYPH_ALPHABET = (
    "0123456789"
    ":,.-?!/%()+'"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
)

# A cell is ink where the grayscale value clears this, matching the
# threshold the bitmaps were verified at.  The sidebar is drawn as
# bright text on black, so the split is wide and not delicate.
GLYPH_INK_THRESHOLD = 100

# The most differing pixels a match may carry over a cell of FONT_WIDTH x
# FONT_HEIGHT.  Zero is what a clean capture actually produces; a small
# allowance absorbs a colour whose dimmest stroke pixel falls near the
# threshold.
GLYPH_MAX_DISTANCE = 4

# How much further away the runner-up must be before the nearest match
# is believed.  Two, so that an exact TIE -- which would otherwise fall
# to GLYPH_ALPHABET order, i.e. arbitrarily -- and a one-pixel preference
# are both refused.
GLYPH_MATCH_MARGIN = 2

# Cell width is derived from the row height rather than read from the
# options file: every font the engine ships for this grid is drawn at
# FONT_WIDTH = FONT_HEIGHT / 2 [src/options.cpp:2408-2438], and the
# ratio is asserted against the crop width before it is used.
GLYPH_WIDTH_DIVISOR = 2

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

# The eight-byte PNG signature [RFC 2083 section 3.1].  Every image this
# module decodes must begin with it, checked before Pillow is handed the
# bytes: Pillow identifies a format by CONTENT, so without this a
# crafted PSD, DDS or TIFF named .png would reach that format's native
# decoder.  See open_png(), open_png_bytes() and png_size().
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
    """The game is configured so that the clock cannot be parsed."""


class BootstrapError(ToolchainError):
    """A dependency this module cannot work without did not import."""


def _require_pillow() -> None:
    """Fail as a FAULT when Pillow is unavailable.

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
    """Return one diagnostic per dependency that did not import."""
    problems = []
    for require in (_require_pillow, _require_sidebar_geometry):
        try:
            require()
        except BootstrapError as exc:
            problems.append(str(exc))
    return problems


class AuditError(OcrClockError):
    """The per-frame date evidence could not be recorded."""


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
# cross_check=True every pass runs and any disagreement WITHHOLDS the
# reading rather than resolving it by pass order, unless an exact glyph
# match proves the answer.  Nothing here repairs, substitutes or
# interpolates.
# ---------------------------------------------------------------------

def _glyph_font_path() -> str:
    """Return the engine's interface font, from this checkout."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return os.path.join(root, *GLYPH_FONT_PARTS)


def font_digest(path: Optional[str] = None) -> str:
    """Return the sha256 of the interface font, as installed."""
    target = _glyph_font_path() if path is None else path
    digest = hashlib.sha256()
    try:
        with open(target, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
    except OSError as exc:
        raise ToolchainError(
            "cannot read the interface font %s: %s" % (target, exc)
        ) from exc
    return digest.hexdigest()


def _attested_font(row_height: int) -> "ImageFont.FreeTypeFont":
    """Load the interface font, having proved it is the shipped one.

    A FONT IS PARSED INPUT.  FreeType is a native parser reached through
    Pillow, and the file it parses is named by a path derived from this
    module's own location -- which is exactly the kind of derivation that
    is safe until somebody plants a file there.  So the font is attested
    on three counts before it is opened:

    * it is a REGULAR FILE reached without a symbolic link, so the name
      cannot be redirected;
    * its sha256 equals GLYPH_FONT_SHA256, the digest of the
      data/font/Terminus.ttf this repository ships -- so a substituted
      or corrupted face is refused rather than parsed;
    * it is inside this checkout.
    """
    path = _glyph_font_path()
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ToolchainError(
            "the interface font %s cannot be inspected: %s"
            % (path, exc)) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ToolchainError(
            "the interface font %s is not a regular file.  A font is "
            "parsed by FreeType through Pillow, so the file behind that "
            "name is refused unless it is the one this repository "
            "ships" % path)
    observed = font_digest(path)
    if observed != GLYPH_FONT_SHA256:
        raise ToolchainError(
            "the interface font %s has sha256 %s, but this pipeline is "
            "written against %s -- the data/font/Terminus.ttf this "
            "repository ships.  A font is native parser input, so a "
            "face that is not the attested one is refused rather than "
            "parsed.  If the font was legitimately updated upstream, "
            "update GLYPH_FONT_SHA256 in this module deliberately and "
            "re-verify the glyph templates: the reader's whole "
            "correctness rests on the bitmaps this face produces"
            % (path, observed, GLYPH_FONT_SHA256))
    try:
        return ImageFont.truetype(path, row_height)
    except OSError as exc:
        raise ToolchainError(
            "the attested interface font %s could not be loaded at "
            "%dpx: %s" % (path, row_height, exc)) from exc


def assert_decodable_provenance(path: str) -> None:
    """Refuse to decode a file anybody but this account could rewrite.

    THE POINT OF THIS CHECK IS THE PIN, NOT THE FILE.  Pillow 11.3.0 is
    pinned because moviepy 2.2.1 declares `pillow<12.0`, and 11.3.0
    carries published advisories in native decoders that are first fixed
    in 12.1.1.  The reason that is an acceptable risk is stated in
    requirements.txt and rests on ONE property: the only images this
    pipeline decodes are PNGs it captured itself, from an X server it
    started, on the machine doing the decoding.  A mode set at creation
    is a fact about the past, so the property is checked here at the
    moment it matters: immediately before the bytes reach a native
    parser.

    Refused, each for its own reason:

    * not a regular file -- a fifo or a device makes the read itself the
      attack, and a symlink means the name and the bytes are two
      different decisions;
    * owned by another account -- then its owner chooses what this
      decoder parses;
    * group- or world-writable -- then so does anybody in that group,
      or anybody at all.

    THE CHECK AND THE READ ARE ONE OPERATION.  Reading the properties
    above with `lstat` and then REOPENING THE FILE BY NAME for the decode
    would leave half the race open: a concurrent writer with the same uid
    could replace the inode between the two (CWE-367), and the bytes that
    reached Pillow would not be the bytes that were validated.
    read_verified_frame() closes that by
    opening once with O_NOFOLLOW, asking `fstat` about the DESCRIPTOR,
    and decoding what it read through that same descriptor.  This
    function is the descriptor-less half, kept public because a caller
    may legitimately want the question answered about a path it is not
    about to decode; it delegates so there is one implementation of the
    rule.

    :raises FrameUnreadableError: with the property that failed.
    """
    descriptor = _open_frame_descriptor(path)
    try:
        _refuse_undecodable_stat(os.fstat(descriptor), path)
    finally:
        os.close(descriptor)


def _open_frame_descriptor(path: str) -> int:
    """Open `path` for reading without following a final symlink.

    O_NOFOLLOW makes "this is not a symlink" a property of the OPEN
    rather than of a preceding stat, so there is no window between the
    two.  O_NONBLOCK is there because this is the call that would
    otherwise BLOCK FOREVER on a fifo planted under a capture's name --
    the descriptor is checked for being a regular file immediately after,
    and O_NONBLOCK changes nothing for one.

    :raises FrameUnreadableError: naming what the open refused.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise FrameUnreadableError(
                "%s is a symbolic link, so the name checked and the "
                "bytes decoded are two separate decisions and only one "
                "of them was verified.  Every capture this pipeline "
                "reads is a regular file written by capture.sh"
                % path) from exc
        raise FrameUnreadableError(
            "%s could not be examined before decoding: %s"
            % (path, exc)) from exc


def _refuse_undecodable_stat(info: os.stat_result, path: str) -> None:
    """Refuse a stat result that is not a capture this account wrote.

    :raises FrameUnreadableError: with the property that failed.
    """
    if stat.S_ISLNK(info.st_mode):              # pragma: no cover
        raise FrameUnreadableError(
            "%s is a symbolic link, so the name checked and the bytes "
            "decoded are two separate decisions and only one of them "
            "was verified.  Every capture this pipeline reads is a "
            "regular file written by capture.sh" % path)
    if not stat.S_ISREG(info.st_mode):
        raise FrameUnreadableError(
            "%s is not a regular file (mode %#o), so reading it is "
            "itself an operation on something else -- a pipe, a socket "
            "or a device -- rather than a capture" % (path, info.st_mode))
    if info.st_uid != os.geteuid():
        raise FrameUnreadableError(
            "%s is owned by uid %d and this process runs as uid %d, so "
            "its owner rather than this pipeline decides what the "
            "decoder parses.  It is refused: the accepted risk in the "
            "pinned Pillow rests on decoding only frames this account "
            "captured" % (path, info.st_uid, os.geteuid()))
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise FrameUnreadableError(
            "%s is mode %04o, which is writable beyond its owner, so "
            "its contents can be replaced between the capture that "
            "wrote it and this decode.  It is refused: the pinned "
            "Pillow carries advisories in its native decoders, and the "
            "reason that is acceptable is that nothing but this account "
            "can choose their input"
            % (path, stat.S_IMODE(info.st_mode)))


def read_verified_frame(path: str) -> bytes:
    """Return the bytes of a capture, validated as it was read.

    The read is bounded by MAX_FRAME_BYTES, which is asked twice -- once
    of the size `fstat` reported and once of what was actually read --
    because a file being appended to while it is read can pass the first
    and not the second.

    :raises FrameUnreadableError: naming the property that failed.
    """
    descriptor = _open_frame_descriptor(path)
    try:
        info = os.fstat(descriptor)
        _refuse_undecodable_stat(info, path)
        if info.st_size > MAX_FRAME_BYTES:
            raise FrameUnreadableError(
                "%s is %d bytes and the ceiling is %d.  A 1920x1080 "
                "capture is under two hundred kilobytes, so a file this "
                "large is not one and is refused before it is read into "
                "memory" % (path, info.st_size, MAX_FRAME_BYTES))
        chunks: List[bytes] = []
        total = 0
        while True:
            try:
                block = os.read(descriptor, 1024 * 1024)
            except OSError as exc:
                raise FrameUnreadableError(
                    "%s could not be read: %s" % (path, exc)) from exc
            if not block:
                break
            total += len(block)
            if total > MAX_FRAME_BYTES:
                raise FrameUnreadableError(
                    "%s grew past the %d-byte ceiling while it was "
                    "being read, so it is being written to and is not a "
                    "finished capture" % (path, MAX_FRAME_BYTES))
            chunks.append(block)
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    if data[:len(PNG_MAGIC)] != PNG_MAGIC:
        raise FrameUnreadableError(
            "%s does not begin with the PNG signature (it begins %r).  "
            "Every capture this pipeline reads is a PNG written by "
            "capture.sh; a file with another format's content is "
            "refused rather than handed to whichever native decoder it "
            "would reach" % (path, data[:len(PNG_MAGIC)]))
    return data


class decode_limits(object):
    """Bound one decode in CPU time, and forbid a core dump.

    WHAT THIS DOES AND, MORE IMPORTANTLY, WHAT IT DOES NOT.

    RLIMIT_AS IS DELIBERATELY NOT SET, and that is a measurement rather
    than an omission. Importing this module reserves 2.6 GiB of virtual
    address space before any decode happens -- numpy alone accounts for
    2.5 GiB of VmData -- so an address-space ceiling tight enough to
    bound a 64-megapixel decode would refuse the import, and one loose
    enough to permit the import bounds nothing. It was tried on this
    host: with the limit lowered to 300 MiB AFTER import, a full decode
    still completed, because RLIMIT_AS constrains new mappings and the
    mappings were already made. Shipping it would have looked like a
    control and enforced nothing, so the pixel ceiling
    (Image.MAX_IMAGE_PIXELS = MAX_PIXELS) is what bounds allocation
    here, and it does so at the only layer that can distinguish a
    legitimate 1920x1080 frame from a bomb.
    """

    def __init__(self) -> None:
        self._saved: List[Tuple[int, Tuple[int, int]]] = []

    def __enter__(self) -> "decode_limits":
        if resource is None:            # pragma: no cover - POSIX only
            return self
        for name, wanted in self._targets():
            limit = getattr(resource, name, None)
            if limit is None:           # pragma: no cover - POSIX only
                continue
            try:
                soft, hard = resource.getrlimit(limit)
            except (OSError, ValueError):    # pragma: no cover
                continue
            # NEVER RAISE A LIMIT AND NEVER TOUCH THE HARD ONE.  If the
            # environment already bounds this process more tightly than
            # asked, that decision wins -- a guard that loosened an
            # operator's limit would be a hole wearing the name of a
            # control.
            target = wanted if hard in (resource.RLIM_INFINITY,) \
                else min(wanted, hard)
            if soft != resource.RLIM_INFINITY and soft <= target:
                continue
            try:
                resource.setrlimit(limit, (target, hard))
            except (OSError, ValueError):    # pragma: no cover
                continue
            self._saved.append((limit, (soft, hard)))
        return self

    def __exit__(self, *_exc: object) -> bool:
        if resource is not None:
            for limit, original in reversed(self._saved):
                try:
                    resource.setrlimit(limit, original)
                except (OSError, ValueError):   # pragma: no cover
                    pass
        self._saved = []
        return False

    @staticmethod
    def _targets() -> List[Tuple[str, int]]:
        """The limits to impose, as (RLIMIT name, soft value)."""
        used = 0.0
        if resource is not None:
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                used = usage.ru_utime + usage.ru_stime
            except (OSError, ValueError):       # pragma: no cover
                used = 0.0
        return [
            ("RLIMIT_CORE", 0),
            ("RLIMIT_CPU", int(used) + DECODE_CPU_SECONDS),
        ]


def open_png(path: str) -> "Image.Image":
    """Open `path` as a PNG, and refuse anything that is not one.

    THE ONE DOOR EVERY IMAGE THIS MODULE DECODES COMES THROUGH.

    Pillow identifies a file by its CONTENT, not by its name, and ships
    a plugin for every format it supports -- so `Image.open` on a file
    called frame_00001.png will happily hand a PSD, a DDS, a TIFF or a
    FLI to the native parser that format needs, and those parsers are
    where Pillow's memory-corruption advisories live.  Two controls
    close that off completely:

    * the first eight bytes must be the PNG signature, checked here
      rather than trusted;
    * `formats=["PNG"]` restricts Pillow to the PNG plugin alone, so
      even a file that got past the signature check cannot reach
      another decoder.

    THE BYTES DECODED ARE THE BYTES VALIDATED.  Checking the path with
    `lstat`, reading its signature by name, and then handing the NAME to
    Image.open is three separate reads of one pathname -- a check-to-use
    race (CWE-367), because a concurrent writer with this account's uid
    can replace the inode after the checks and the decoder then parses a
    file nothing validated.  read_verified_frame does all of it through
    ONE descriptor and returns the bytes, and the decode is handed those
    bytes.

    A decompression bomb is bounded as well: MAX_PIXELS is a hard cap on
    the pixel count, which is generous beside the 1920x1080 root window
    these captures actually are.
    """
    data = read_verified_frame(path)
    _require_pillow()
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with decode_limits():
            image = Image.open(io.BytesIO(data), formats=["PNG"])
            image.load()
    except Image.DecompressionBombError as exc:
        raise FrameUnreadableError(
            "%s declares more than %d pixels: %s"
            % (path, MAX_PIXELS, exc)) from exc
    except (OSError, ValueError) as exc:
        raise FrameUnreadableError(
            "%s is not a decodable PNG: %s" % (path, exc)) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    return image


def open_png_bytes(data: bytes, source: str) -> "Image.Image":
    """Open in-memory PNG bytes, and refuse anything that is not one.

    :param source: what produced the bytes, for the error message.
    """
    if data[:len(PNG_MAGIC)] != PNG_MAGIC:
        raise ToolchainError(
            "%s did not produce a PNG (its output begins %r)"
            % (source, data[:len(PNG_MAGIC)]))
    _require_pillow()
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with decode_limits():
            image = Image.open(io.BytesIO(data), formats=["PNG"])
            image.load()
    except Image.DecompressionBombError as exc:
        raise ToolchainError(
            "%s produced an image past the %d-pixel ceiling: %s"
            % (source, MAX_PIXELS, exc)) from exc
    except (OSError, ValueError) as exc:
        raise ToolchainError(
            "%s produced an image that could not be decoded as a PNG: "
            "%s" % (source, exc)) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    return image


def png_size(path: str) -> Tuple[int, int]:
    """Return a PNG's pixel dimensions WITHOUT decoding it.

    :raises FrameUnreadableError: for anything that is not a PNG whose first
        chunk is a well-formed IHDR.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(len(PNG_MAGIC) + 8 + 8)
    except OSError as exc:
        raise FrameUnreadableError(
            "%s could not be read: %s" % (path, exc)) from exc
    if header[:len(PNG_MAGIC)] != PNG_MAGIC:
        raise FrameUnreadableError(
            "%s does not begin with the PNG signature" % path)
    body = header[len(PNG_MAGIC):]
    if len(body) < 16 or body[4:8] != b"IHDR":
        raise FrameUnreadableError(
            "%s does not open with an IHDR chunk, so it is not a PNG "
            "this pipeline wrote" % path)
    width = int.from_bytes(body[8:12], "big")
    height = int.from_bytes(body[12:16], "big")
    if width <= 0 or height <= 0:
        raise FrameUnreadableError(
            "%s declares a %dx%d image" % (path, width, height))
    if width * height > MAX_PIXELS:
        raise FrameUnreadableError(
            "%s declares %dx%d = %d pixels, past the %d-pixel ceiling"
            % (path, width, height, width * height, MAX_PIXELS))
    return width, height


@functools.lru_cache(maxsize=4)
def _glyph_templates(
    cell_width: int, row_height: int
) -> Tuple[Dict[bytes, str],
           Tuple[Tuple[str, "numpy.ndarray"], ...],
           Dict[str, int]]:
    """Render one template per glyph from the game's own font."""
    _require_pillow()
    font = _attested_font(row_height)
    exact: Dict[bytes, str] = {}
    ordered = []
    for character in GLYPH_ALPHABET:
        cell = Image.new("L", (cell_width, row_height), 0)
        ImageDraw.Draw(cell).text((0, 0), character, fill=255, font=font)
        mask = numpy.ascontiguousarray(
            numpy.asarray(cell) > GLYPH_INK_THRESHOLD)
        exact.setdefault(mask.tobytes(), character)
        ordered.append((character, mask))
    neighbour: Dict[str, int] = {}
    for index, (character, mask) in enumerate(ordered):
        closest = None
        for other_index, (other, other_mask) in enumerate(ordered):
            if other_index == index or other == character:
                continue
            distance = int(numpy.count_nonzero(mask != other_mask))
            if closest is None or distance < closest:
                closest = distance
        neighbour[character] = (
            GLYPH_MAX_DISTANCE * 2 + 2 if closest is None else closest)
    return exact, tuple(ordered), neighbour


def _glyph_cells(
    band: "numpy.ndarray", cell_width: int
) -> Tuple["numpy.ndarray", ...]:
    """Split one grid row into contiguous per-character cells."""
    columns = band.shape[1] // cell_width
    return tuple(
        numpy.ascontiguousarray(
            band[:, index * cell_width:(index + 1) * cell_width])
        for index in range(columns))


def _glyph_bands(
    ink: "numpy.ndarray", phase: int, row_height: int
) -> Tuple[Tuple[int, "numpy.ndarray"], ...]:
    """Return the inked grid rows at one vertical phase."""
    bands = []
    top = phase
    while top + row_height <= ink.shape[0]:
        band = ink[top:top + row_height]
        if band.any():
            bands.append((top, band))
        top += row_height
    return tuple(bands)


def _glyph_phase(
    ink: "numpy.ndarray",
    exact: Dict[bytes, str],
    cell_width: int,
    row_height: int,
) -> int:
    """Find which vertical phase the engine's cell grid actually sits on.

    THE PHASE IS MEASURED, NOT ASSUMED, and that is the whole reason
    this helper exists.  sidebar_geometry.py places the crop from the
    window's letterbox, while the engine anchors its character grid to
    the window itself; on this host the two differed by 14 pixels, and
    slicing on the wrong phase splits every glyph across two bands and
    reads nothing at all.  So every candidate phase is scored by how
    many cells it makes EXACTLY equal to a glyph of the game's own
    font, and the winner is the one the engine was really drawing on.
    """
    best_phase, best_score = 0, -1
    for phase in range(row_height):
        score = 0
        for _, band in _glyph_bands(ink, phase, row_height):
            for cell in _glyph_cells(band, cell_width):
                if cell.any() and cell.tobytes() in exact:
                    score += 1
        if score > best_score:
            best_phase, best_score = phase, score
    return best_phase


def _decode_glyph_row(
    band: "numpy.ndarray",
    exact: Dict[bytes, str],
    ordered: Tuple[Tuple[str, "numpy.ndarray"], ...],
    neighbour: Dict[str, int],
    cell_width: int,
    ambiguous: Optional[List[str]] = None,
    marks: Optional[List[bool]] = None,
) -> str:
    """Decode one grid row of cells into text.

    An exact match answers immediately.  Anything else must be a match
    that is UNIQUE AND SEPARATED, on three conditions that all have to
    hold:

    * the nearest template is within GLYPH_MAX_DISTANCE;
    * twice that distance is strictly less than the distance from that
      template to its own nearest neighbour -- the classic
      unique-decoding radius, so no other template can be as close;
    * the runner-up is at least GLYPH_MATCH_MARGIN further away, which
      also settles an exact TIE, where two templates sit at the same
      distance and the answer would otherwise be whichever came first
      in GLYPH_ALPHABET.

    :param marks: filled, if given, with one flag per returned character saying
        whether that character came from an EXACT match.
    """
    out: List[str] = []
    exactly: List[bool] = []
    for cell in _glyph_cells(band, cell_width):
        if not cell.any():
            out.append(" ")
            exactly.append(False)
            continue
        hit = exact.get(cell.tobytes())
        if hit is not None:
            out.append(hit)
            exactly.append(True)
            continue
        best = " "
        first, second = GLYPH_MAX_DISTANCE + 1, GLYPH_MAX_DISTANCE + 1
        runner = ""
        for character, template in ordered:
            differing = int(numpy.count_nonzero(cell != template))
            if differing < first:
                best, runner = character, best
                first, second = differing, first
            elif differing < second:
                runner, second = character, differing
        if first > GLYPH_MAX_DISTANCE:
            out.append(" ")
            exactly.append(False)
            continue
        safe = neighbour.get(best, 0)
        if first * 2 >= safe or second - first < GLYPH_MATCH_MARGIN:
            if ambiguous is not None:
                ambiguous.append(
                    "a cell is %d pixel(s) from %r and %d from %r "
                    "(%r's nearest neighbour is %d away), which is not "
                    "a unique match; it was read as a space rather "
                    "than guessed"
                    % (first, best, second, runner or "nothing", best,
                       safe))
            out.append(" ")
            exactly.append(False)
            continue
        out.append(best)
        # A near match, however tightly bounded, is not a proof.
        exactly.append(False)
    text = "".join(out).rstrip()
    if marks is not None:
        marks.extend(exactly[:len(text)])
    return text


def read_column_by_glyphs(
    png_path: str,
    rect: sidebar_geometry.Rect,
    row_height: int,
    notes: Optional[List[str]] = None,
    marks: Optional[List[bool]] = None,
) -> str:
    """Decode the sidebar column cell by cell against the game's font.

    :param marks: filled, if given, with one flag per character of the returned
        text saying whether that character was an EXACT match against the
        attested font. Newlines are marked False, so the list indexes the
        returned string directly.
    """
    _require_pillow()
    if numpy is None or ImageFont is None or ImageDraw is None:
        _warn("the exact glyph reader needs numpy and Pillow's font "
              "modules (%s), so the OCR passes answer for this frame"
              % (NUMPY_IMPORT_ERROR or "unavailable"), notes)
        return ""
    if row_height < GLYPH_WIDTH_DIVISOR * 2:
        return ""
    cell_width = row_height // GLYPH_WIDTH_DIVISOR
    if rect.width < cell_width or rect.x % cell_width:
        _warn(
            "the crop %s does not sit on the %d-pixel character grid, "
            "so the exact glyph reader is skipped and the OCR passes "
            "answer for this frame" % (rect.geometry, cell_width),
            notes)
        return ""
    try:
        font_path = _glyph_font_path()
        if not os.path.isfile(font_path):
            _warn("the interface font %s is not in this checkout, so "
                  "the exact glyph reader is skipped" % font_path, notes)
            return ""
        with open_png(png_path) as opened:
            grey = opened.convert("L")
            column = grey.crop(
                (rect.x, rect.y,
                 rect.x + rect.width, rect.y + rect.height))
        ink = numpy.ascontiguousarray(
            numpy.asarray(column) > GLYPH_INK_THRESHOLD)
        exact, ordered, neighbour = _glyph_templates(
            cell_width, row_height)
    except (FrameUnreadableError, ToolchainError) as exc:
        _warn("the exact glyph reader refused to read %s (%s), so the "
              "OCR passes answer for this frame" % (png_path, exc),
              notes)
        return ""
    except (OSError, ValueError) as exc:
        _warn("the exact glyph reader could not prepare %s (%s), so "
              "the OCR passes answer for this frame"
              % (png_path, exc), notes)
        return ""

    if not ink.any():
        return ""
    phase = _glyph_phase(ink, exact, cell_width, row_height)
    ambiguous: List[str] = []
    lines = []
    row_marks: List[List[bool]] = []
    for _, band in _glyph_bands(ink, phase, row_height):
        band_marks: List[bool] = []
        text = _decode_glyph_row(
            band, exact, ordered, neighbour, cell_width, ambiguous,
            band_marks)
        if text.strip():
            lines.append(text)
            row_marks.append(band_marks)
    text = "\n".join(lines)
    if marks is not None:
        for index, band_marks in enumerate(row_marks):
            if index:
                # The "\n" join() inserted, which is nobody's glyph.
                marks.append(False)
            marks.extend(band_marks)
    if ambiguous and find_clocks(text)[0] is None:
        # PROPORTIONATE REPORTING.  A refused cell is only worth a reader's
        # attention when the refusal cost the reading: the sidebar draws
        # box-rules and symbols this alphabet does not contain, so a column
        # normally carries dozens of cells that match nothing, and answering
        # those with whichever template happened to be nearest is exactly what
        # this refuses.
        _warn(
            "the exact glyph reader refused %d ambiguous cell(s) in %s "
            "and found no clock, so the OCR passes answer for this "
            "frame; the closest call was: %s"
            % (len(ambiguous), png_path, ambiguous[0]), notes)
    return text


def _all_exact(text: str, value: str,
               marks: Sequence[bool]) -> bool:
    """True when every character of ``value`` was an EXACT match.

    THE DIFFERENCE BETWEEN A PROOF AND A PREFERENCE.  An exact match
    means the cell's ink is bit-identical to what the attested font
    draws for that glyph, so the engine demonstrably drew that
    character there.  A near match -- however tightly its
    unique-decoding radius is bounded -- is strong evidence but not
    proof, and only a proof is allowed to stand against a disagreeing
    OCR pass in read_sidebar().
    """
    if not value or len(marks) != len(text):
        return False
    start = text.find(value)
    if start < 0:
        return False
    return all(marks[start:start + len(value)])


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
    """Everything one frame's sidebar actually said, and how."""

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


# Everything :func:`resolve_rect` accepts.  A bare sequence is ``(width,
# height, x, y)`` -- the order of the geometry string, so that reading a call
# and reading the crop are the same exercise.
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

    :returns: the option's value when it is ``24h``; the value found, or
        ``None`` when there was none, in the diagnostic mode.
    :raises OptionsError: when ``require`` is true and the value is anything
        other than ``24h``, including the cases where the options file cannot
        be read or carries no such value.
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

    :param rect: an explicit crop, or ``None`` to compute one.
    :param row_height: one text row in pixels; derived when omitted.
    :param notes: a list every substitution is appended to.
    :param options_json: the game-written ``options.json`` the crop computation
        should read.
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
# reading every duration in the finished movie is computed from.  So the
# binary is resolved to an absolute path, and that path -- and every
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
    """Return why `path` cannot be trusted, or None when it can."""
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
        untrustworthy. ``$PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES=1``
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
                "every captured frame is decoded by Pillow, and %s is "
                "the version playthrough/tooling/requirements.txt pins "
                "and this pipeline was verified against -- it is the "
                "last release of its series, so anything older is a "
                "decoder missing fixes that one carries.  Install "
                "playthrough/tooling/requirements.lock (%s) into the "
                "interpreter this pipeline runs; env.sh reports it as "
                "PLAYTHROUGH_PYTHON."
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


def preflight_problems() -> List[str]:
    """Return every reason this module could not read a frame yet.

    Both failures have the same shape -- a whole session of frames that
    each look like an honest unreadable clock while every count still
    tallies -- so both belong in the check that runs ONCE before any
    frame exists rather than in the one that runs per frame.  The
    documented override is honoured exactly as it is at the point of
    use: with ``$PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW=1`` the mismatch is
    announced and is not a problem.
    """
    problems = bootstrap_problems()
    if problems:
        return problems
    try:
        assert_pillow_supported()
    except ToolchainError as exc:
        problems.append(str(exc))
    return problems


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
    """Choose the preprocessing engine, announcing any substitution."""
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
    """Choose the OCR front end, announcing any substitution."""
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
    image = open_png_bytes(data, CONVERT_BIN)
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
    source = open_png(png_path)

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

    :raises ToolchainError: when tesseract is absent, exceeds the timeout, or
        fails. A blank result is NOT an error: an empty band legitimately reads
        empty.
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

    :returns: ``(clock_or_None, impossible_readings)``. The second element
        exists so a caller can report what was declined; no declined reading is
        ever repaired into the first element.
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
    """Explain why OCR text held no readable clock."""
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

    :returns: ``(text, ocr_call_count)`` with one line per band, so the row
        structure survives into the extraction step.
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
    # The dimensions come from the IHDR chunk, not from a decode: the
    # commonest question asked of a capture is answered by 24 bytes of
    # pure Python, so a malformed or hostile frame is refused here
    # rather than being handed to a native decoder first.
    size = png_size(png_path)
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

    :param png_path: the captured PNG. Validated, and expected inside the
        frames directory.
    :param rect: the crop; ``None`` computes it from configuration.
    :param row_height: one text row in pixels; derived when omitted.
    :param engine: ``convert`` (default) or ``pillow`` preprocessing.
    :param ocr_engine: ``pytesseract`` (default) or ``tesseract``.
    :param passes: an explicit pass list; :data:`PASSES` by default.
    :param cross_check: run every pass even after one succeeds. A disagreement
        then makes the clock ``None`` -- withheld, not resolved by pass order
        -- UNLESS an exact glyph match settles it, which is a proof and stands.
    :param full_scan: read every text row. ``False`` stops at the first row
        holding a clock, which is faster and is what :func:`read_clock` does;
        the date line may then be missed.
    :param check_options: assert ``24_HOUR`` is ``24h`` before reading.
    :param options_json: an explicit options file, used both for that assertion
        and for the crop computation, so a hand-picked configuration cannot be
        asserted against one file while the sidebar is located from another.
    :param frames_dir: an explicit frames directory for path checking.
    :param strict_path: refuse a frame outside the frames directory.
    :returns: a :class:`SidebarReading`; ``.clock`` is ``None`` when no
        possible clock was read.
    :raises OcrClockError: for any fault -- a bad or missing frame, an unusable
        crop, a missing tool, a misconfigured option. Never for an unreadable
        clock.
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

    # THE GLYPH PASS RUNS FIRST.  It spends no OCR calls, and its output
    # goes through the same find_clocks() as every OCR pass -- so an
    # impossible reading is declined here exactly as it would be there.
    # glyph_marks comes back saying which characters were bit-exact,
    # because only those let this pass stand against a disagreeing OCR
    # pass; a near match, however tightly bounded, is confirmed first.
    glyph_marks: List[bool] = []
    glyph_exact = False
    glyph_text = read_column_by_glyphs(
        resolved_png, rectangle, rows, notes, glyph_marks)
    if glyph_text.strip():
        attempted.append(GLYPH_PASS_NAME)
        found, impossible = find_clocks(glyph_text)
        for value in impossible:
            if value not in declined:
                declined.append(value)
                _warn(
                    "pass '%s' read %r, which no in-game clock can say "
                    "(hour <= %d, minute and second <= %d); declined, "
                    "and NOT repaired into a plausible time"
                    % (GLYPH_PASS_NAME, value, MAX_HOUR, MAX_MINUTE),
                    notes)
        if found is not None:
            candidates.append(found)
            clock, winner, winning_text = (
                found, GLYPH_PASS_NAME, glyph_text)
            glyph_exact = _all_exact(glyph_text, found, glyph_marks)
            LOG.debug("pass '%s' read the clock as %s (exact=%s)",
                      GLYPH_PASS_NAME, found, glyph_exact)
        elif not fallback_text.strip():
            fallback_text = glyph_text

    for ocr_pass in selected:
        if clock is not None and not cross_check:
            break
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

    disagreed = len(candidates) > 1
    settled = disagreed and winner == GLYPH_PASS_NAME and glyph_exact
    if disagreed and not settled:
        # DISAGREEMENT WITHOUT A PROOF MEANS UNREADABLE.  Probabilistic
        # readers of the same pixels that return different times have
        # established that the time is NOT established, and choosing
        # between them by pass order is choosing arbitrarily.  So the
        # clock is withheld rather than picked, which is the only safe
        # direction: a missing reading is reconciled downstream against
        # the previous frame and is visible in the record as null,
        # whereas a wrong one is undetectable and becomes a wrong
        # duration, a wrong caption and a wrong line in the transcript.
        #
        # Nothing is hidden by withholding: every candidate stays in
        # `candidates`, the text stays in `text`, and the frame itself
        # remains the authority a human can inspect.
        _warn(
            "the readers disagree about the clock in %s: %s, and no "
            "exact match settles it.  The reading is therefore "
            "reported as UNREADABLE rather than resolved by pass "
            "order; every candidate is recorded and nothing is "
            "averaged or repaired.  The frame itself is authoritative "
            "-- inspect it"
            % (resolved_png,
               ", ".join(repr(value) for value in candidates)),
            notes)
        clock, winner = None, None
    elif settled:
        # AN EXACT MATCH IS A PROOF, NOT A PREFERENCE.  Every character
        # of this reading is bit-identical to what the attested
        # data/font/Terminus.ttf draws for it, so the engine
        # demonstrably drew that time in those pixels.  tesseract
        # disagreeing with a proof is tesseract being wrong -- measured
        # on this evidence: of 26 cross-checked frames, three drew OCR
        # contradictions ('19:40:10' against an exact '15:28:18', and
        # the like), and every contradiction was impossible in sequence
        # against the neighbouring frames while every exact reading fit.
        #
        # Discarding a proof because a probabilistic reader was noisy
        # would lose true observations, which is its own kind of
        # dishonesty.  So the proof stands, the contradiction is
        # recorded, and `agreement` stays false so the evidence shows
        # that this frame was contested and how it was settled.
        _warn(
            "the OCR passes read %s in %s, contradicting the exact "
            "glyph match %r.  The exact match STANDS: every one of its "
            "characters is bit-identical to what the attested "
            "interface font draws, which is a proof rather than a "
            "preference.  The contradicting readings are recorded and "
            "nothing is averaged or repaired"
            % (", ".join(repr(value) for value in candidates
                         if value != clock),
               resolved_png, clock),
            notes)

    if clock is None and not disagreed:
        if text.strip():
            diagnose_clock_text(text, notes)
        else:
            _warn(
                "the sidebar column of %s produced no text at all; the "
                "frame may be blank, which is what SDL_VIDEODRIVER="
                "dummy produces, or the crop %s may cover empty pixels"
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

    :returns: the reading, or ``None``. :raises OcrClockError: for a fault,
        never for an unreadable clock.
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
    """Return the sidebar date line, verbatim, or ``None``."""
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

# frame_sha256 is LAST on purpose: the six fields before it are the
# original contract and their order is unchanged, so a row written before
# this field existed and a row written after it line up column for column
# in a diff of the committed sidecar.
DATE_AUDIT_FIELDS = ("frame", "file", "clock", "phrase", "date",
                     "agreement", "frame_sha256")

# WHERE THAT SIDECAR LIVES, RELATIVE TO THE APPROVED ROOT, and why the
# location is a constant rather than a parameter.
#
# A security review reproduced this exactly: `--audit` accepted ANY
# regular file under playthrough/, and appending an audit-shaped line to
# a chosen one succeeded.  The containment check below was doing its job
# -- the target was inside the tree, and no component was a symlink --
# but containment is the wrong question for an append.  Every artifact of
# this pipeline is inside that tree, so "inside the tree" includes the
# manifest, the transcripts, a save file, a PNG and both MP4s.
#
# So the destination is pinned to one relative name.  A caller may
# still relocate the whole TREE (see approved_artifact_root's `root`
# argument, which is a call-site seam for a test that owns a temporary
# directory), and inside whatever tree that is, the sidecar has exactly
# one place it can be.  The command line cannot even relocate the tree.
DATE_AUDIT_REL_PARTS = ("build", "frame_dates.jsonl")

# A capture digest, pinned as a SHAPE so that a truncated, upper-cased or
# decorated reading is refused rather than written into the sidecar as
# though it bound anything.
AUDIT_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

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
    """Return the tree this module may write inside, absolute."""
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


def canonical_audit_path(root: Optional[str] = None) -> str:
    """Return the ONE path the date audit may be appended to.

    env.sh exports the same value as ``$PLAYTHROUGH_DATE_AUDIT`` for the
    shell half of the pipeline; it is not READ here, because a variable
    that could move the destination is exactly what this function exists
    to remove.
    """
    return os.path.join(approved_artifact_root(root),
                        *DATE_AUDIT_REL_PARTS)


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
    # THE EXACT DESTINATION, not merely a contained one.  See
    # DATE_AUDIT_REL_PARTS: containment is satisfied by every artifact in
    # the tree, so it cannot be what decides where an APPEND lands.
    expected = canonical_audit_path(root)
    if resolved != expected:
        raise AuditError(
            "the date audit is appended to %s and to nothing else, but "
            "%s was given.  Every artifact of this pipeline lives inside "
            "the same tree, so a contained path is not a safe one: a "
            "line of audit-shaped JSON appended to the manifest, a "
            "transcript, a save or a frame would be growing evidence "
            "nobody wrote" % (expected, resolved))
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
                      reading: SidebarReading,
                      frame_sha256: Optional[str] = None
                      ) -> Dict[str, object]:
    """Build the audit record for one frame's reading."""
    index = _validated_audit_frame(frame)
    return {
        "frame": index,
        "file": FRAME_FILE_FORMAT % index,
        "clock": _audit_scalar(reading.clock),
        "phrase": _audit_scalar(reading.phrase),
        "date": _audit_scalar(reading.date),
        "agreement": bool(reading.agreement),
        "frame_sha256": _validated_audit_digest(frame_sha256),
    }


def _validated_audit_digest(value: object) -> Optional[str]:
    """Return a sha256 in canonical form, or None. Never a guess."""
    if value is None:
        return None
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise AuditError(
            "the capture digest must be a string, got %s"
            % type(value).__name__)
    text = value.strip()
    if not text:
        return None
    if not AUDIT_SHA256_RE.match(text):
        raise AuditError(
            "the capture digest %r is not 64 lowercase hex digits; a "
            "reading bound to an unreadable digest is worse than one "
            "that says plainly it is unbound" % (value,))
    return text


def append_date_audit(path: str, frame: int,
                      reading: SidebarReading,
                      root: Optional[str] = None,
                      frame_sha256: Optional[str] = None
                      ) -> Dict[str, object]:
    """Append one frame's date evidence to the sidecar.

    :returns: the record exactly as written. :raises AuditError: for a bad
        path, a bad index, or a write this module could not complete.
    """
    resolved = _validated_audit_path(path, root)
    record = date_audit_record(frame, reading, frame_sha256)
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
#     CLOCK="$("${PLAYTHROUGH_PYTHON}" -B \
#         playthrough/tooling/ocr_clock.py "$FRAME")"
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
and is not on PATH, so it is always invoked through the pinned
interpreter -- source playthrough/tooling/env.sh first, which exports it
as PLAYTHROUGH_PYTHON and is the only interpreter carrying Pillow and
pytesseract -- with -B so no __pycache__ is left in the tree):
  OC='playthrough/tooling/ocr_clock.py'
  SG='playthrough/tooling/sidebar_geometry.py'

  # the pipeline's own call, crop computed from configuration
  "$PLAYTHROUGH_PYTHON" -B "$OC" \\
      playthrough/frames/frame_00042.png

  # the crop capture.sh already has in hand
  "$PLAYTHROUGH_PYTHON" -B "$OC" --rect \\
      "$("$PLAYTHROUGH_PYTHON" -B "$SG")" "$FRAME"

  # audit one frame: run every pass and show the evidence
  "$PLAYTHROUGH_PYTHON" -B "$OC" --cross-check -v "$FRAME"

  # the whole reading, for a tool rather than a human
  "$PLAYTHROUGH_PYTHON" -B "$OC" --json "$FRAME"

  # what a watchless survivor's sidebar says
  "$PLAYTHROUGH_PYTHON" -B "$OC" --field phrase "$FRAME"

  # capture.sh's own call: every reading from ONE OCR pass, and the
  # date evidence timeline.py needs persisted in the same breath
  "$PLAYTHROUGH_PYTHON" -B "$OC" --kv \\
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
        help=("append this frame's date evidence to the append-only "
              "JSONL sidecar at build/frame_dates.jsonl (the pipeline "
              "passes $%s, which is that path); requires --audit-frame. "
              "NO OTHER DESTINATION IS ACCEPTED: every artifact of this "
              "pipeline is inside the same tree, so a merely contained "
              "path could append audit-shaped JSON to the manifest, a "
              "transcript, a save or a frame" % ENV_DATE_AUDIT))
    parser.add_argument(
        "--audit-frame", type=int, metavar="N",
        help=("the frame index to record in the audit sidecar; "
              "session.py owns this counter, so it is never derived "
              "from the file name"))
    parser.add_argument(
        "--audit-sha256", metavar="HEX",
        help=("the sha256 capture.sh took of this frame the instant it "
              "was published, recorded in the audit row so the reading "
              "is bound to the pixels it came from rather than to "
              "whatever file later occupies that index.  Omitted only "
              "for a frame that predates the attestation ledger, where "
              "the row says plainly that it is unbound"))
    parser.add_argument(
        "--cross-check", action="store_true",
        help=("run every pass even after one succeeds and report the "
              "clock as unreadable if they disagree, unless an exact "
              "glyph match settles it, rather than resolving the "
              "disagreement by pass order; capture.sh always does this"))
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
    """Read one frame and print the requested reading, or nothing."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_cli_logging(args.verbose)

    problems = bootstrap_problems()
    if args.preflight:
        # The preflight asks the WIDER question: not just whether the
        # dependencies imported, but whether the Pillow that decodes
        # every frame is the pinned one.  See preflight_problems().
        problems = preflight_problems()
        for problem in problems:
            LOG.error("%s", problem)
        if problems:
            return EXIT_FAULT
        LOG.info(
            "every dependency of ocr_clock.py is importable, and "
            "Pillow %s satisfies the pinned %s", PILLOW_VERSION,
            ".".join(str(part) for part in PILLOW_MIN_VERSION))
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
    if args.audit_sha256 is not None and not args.audit:
        parser.error(
            "--audit-sha256 is only meaningful with --audit PATH")
    if args.audit_sha256 is not None and \
            not AUDIT_SHA256_RE.match(args.audit_sha256.strip()):
        parser.error(
            "--audit-sha256 %r is not 64 lowercase hex digits; a "
            "reading bound to an unreadable digest is worse than one "
            "that says plainly it is unbound" % args.audit_sha256)
    # AND THE DESTINATION IS THE CANONICAL SIDECAR OR NOTHING.
    #
    # A security review reproduced the alternative: `--audit
    # playthrough/manifest.jsonl` appended an audit-shaped line to the
    # record itself and exited reporting success.  The containment check
    # inside the writer was satisfied -- the manifest is inside the tree
    # -- which is precisely why containment cannot be the rule for an
    # append: every artifact this pipeline produces is inside that tree.
    #
    # Relocating the tree stays available to a CALL SITE (see
    # approved_artifact_root's `root` argument, which is how a test holds
    # this writer to a directory it owns).  It is deliberately NOT
    # available here: argparse never produces a root, and the one thing
    # the command line may do is name the sidecar it already knows.
    if args.audit:
        try:
            expected = canonical_audit_path()
        except OcrClockError as exc:
            parser.error(str(exc))
        if os.path.abspath(args.audit) != expected:
            parser.error(
                "--audit accepts only %s, the sidecar timeline.py reads. "
                "%r is somewhere else, and a date record written "
                "somewhere else is either evidence nothing consults or a "
                "line of JSON appended to another artifact"
                % (expected, args.audit))
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
            append_date_audit(args.audit, args.audit_frame, reading,
                              frame_sha256=args.audit_sha256)
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
