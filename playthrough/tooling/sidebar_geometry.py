#!/usr/bin/env python3
"""Compute the sidebar OCR crop rectangle from configuration.

This is the resolution of the ``<sidebar region>`` placeholder left open
by the capture request.  ``ocr_clock.py`` imports it and ``capture.sh``
invokes it as a script; both need the same ImageMagick geometry string
``WxH+X+Y``, and they get it from here so the two cannot disagree.

THE FORMULA
    cols   = engine_cells(TERMINAL_X, SCALING_FACTOR, 80)
    rows   = engine_cells(TERMINAL_Y, SCALING_FACTOR, 24)
    width  = sidebar_width_cells * FONT_WIDTH   * SCALING_FACTOR
    height = rows                * FONT_HEIGHT  * SCALING_FACTOR
    x      = window.x + window.width - width  (SIDEBAR_POSITION right)
    x      = window.x                         (SIDEBAR_POSITION left)
    y      = window.y

The game window is derived exactly as the engine derives it, in the
engine's own ORDER, and the order is the part worth reading twice: the
engine first turns the SAVED ``TERMINAL_X``/``TERMINAL_Y`` into a LOGICAL
grid -- trimming to a multiple of the scaling factor, flooring at
``EVEN_MINIMUM_TERM_*`` times that factor, then DIVIDING by it
[src/sdltiles.cpp:6235-6252] -- and only then computes
``WindowWidth = TERMINAL_WIDTH * fontwidth * scaling_factor``
[src/sdltiles.cpp:595-596].  Multiplying the saved values by the factor
WITHOUT dividing first overstates a scaled window by the square of the
factor: a saved 240x67 at factor 2 is a 120x33 logical grid in a
1920x1056 window, not a 3840x2144 one.

The window is then centred inside the X root, which produces the
letterbox: at factor 1 it measures 1920x1072 at ``+0+4`` inside a
1920x1080 root, so ``y`` is COMPUTED as ``(1080 - 1072) // 2`` and is not
a constant anywhere in this file.  READ THAT ``y`` AS "WHERE A CENTRED
WINDOW WOULD PUT THE GRID", NEVER AS "WHERE THE GRID WAS": a window
manager that hands a borderless window the whole root leaves the engine
blitting the grid at the top-left with the whole remainder as border at
the bottom [src/sdltiles.cpp:311-320, :1046-1050], so the real grid can
begin up to four rows above this.  The centred form is kept deliberately,
because the crop is 1072 rows tall and the clock row it exists to capture
sits at y288, far inside it either way -- and ``ocr_clock.py`` does not
trust this ``y`` for glyph slicing at all: it MEASURES which vertical
phase the cell grid is on by scoring candidates against the game's own
font.

WHICH SIDEBAR, AND ON WHOSE AUTHORITY
The width in cells belongs to the layout the engine is CURRENTLY drawing,
which is not necessarily ``custom_sidebar``:

* ``current_layout_id`` is read from the game's own
  ``<userdir>/config/panel_options.json`` [src/panels.cpp:492-503,
  :544-548; src/path_info.cpp:356-358];
* before the game has written one, the engine's constructor default
  applies -- ``legacy_labels_sidebar`` on every non-Android build
  [src/panels.cpp:412-418], whose width is 44 cells and NOT
  ``custom_sidebar``'s 36;
* the id is looked up among the ``style: sidebar`` widgets of the whole
  ``data/json/ui`` tree, because that is where the engine builds its
  layout map from [src/panels.cpp:398-408], and the width used is that
  widget's own ``width`` [src/panels.cpp:484].

So a fresh userdir evaluates to ``352x1072+1568+4`` and a game selecting
``custom_sidebar`` to ``288x1072+1632+4``.  Both are expected results,
never return values.

WHY THIS IS COMPUTED AND NOT A LITERAL
Twelve widgets in this checkout declare ``"style": "sidebar"`` at eight
distinct widths -- 32, 36, 43, 44, 48, 58, 62 and 66 cells.  A hard-coded
rectangle, or a correctly computed one taken from the wrong preset, would
crop the wrong column the moment the layout changed, and it would do so
SILENTLY: nothing crashes, the OCR simply stops matching, every
``ingame_clock`` goes null and every duration collapses to the 0.25 s
floor while the finished movie still looks plausible.  Preventing that one
silent failure is the entire reason this module exists, which is why every
fallback is announced on stderr through ``logging`` and a malformed input
raises :class:`GeometryError` rather than falling back to a default.

READ-ONLY BY CONSTRUCTION
The widget JSON under ``data/json/ui`` and the game-written
``options.json`` and ``panel_options.json`` are opened for reading only;
no widget is modified, no layout is selected, the in-game sidebar manager
is never invoked, no subprocess is started, and no network call of any
kind is made.

USAGE
    $ . playthrough/tooling/env.sh
    $ "$PLAYTHROUGH_PYTHON" -B playthrough/tooling/sidebar_geometry.py
    352x1072+1568+4

``env.sh`` exports ``PLAYTHROUGH_PYTHON``, the pinned CPython 3.12 this
tooling is installed against; the system ``python3`` is not it.

Standard output carries exactly the geometry string and nothing else, so
capturing that invocation in a ``RECT="$(...)"`` substitution is safe, and
``--layout-id`` pins a named layout instead of reading the game's own
choice.  Every diagnostic, warning and fallback notice goes to stderr.
"""
import argparse
import json
import logging
import os
import sys

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

LOG = logging.getLogger("playthrough.sidebar_geometry")

# ---------------------------------------------------------------------
# Documented defaults.
#
# Every value below is the engine's own default, cited to the line that
# declares it.  They are used ONLY when the corresponding key is absent
# from the game-written options file, and never silently: each fallback
# is logged at WARNING and recorded in SidebarGeometry.notes.
#
# TERMINAL_X and TERMINAL_Y default to the compiled-in 80x24 rather than
# to the 240x67 this pipeline runs at.  That is deliberate: 80x24 is what
# the engine writes on a first launch before it has derived screen-based
# values, and reporting the real default is what makes the accompanying
# warning worth reading.  Anything else would be inventing a default the
# engine does not have.
# ---------------------------------------------------------------------

# src/options.cpp:2408-2411 add( "TERMINAL_X", ..., 80, 960, 80, ... )
DEFAULT_TERMINAL_X = 80
TERMINAL_X_RANGE = (80, 960)

# src/options.cpp:2413-2416 add( "TERMINAL_Y", ..., 24, 270, 24, ... )
DEFAULT_TERMINAL_Y = 24
TERMINAL_Y_RANGE = (24, 270)

# src/options.cpp:2430-2433 add( "FONT_WIDTH", ..., 6, 100, 8, ... )
DEFAULT_FONT_WIDTH = 8
FONT_WIDTH_RANGE = (6, 100)

# src/options.cpp:2435-2438 add( "FONT_HEIGHT", ..., 8, 100, 16, ... )
DEFAULT_FONT_HEIGHT = 16
FONT_HEIGHT_RANGE = (8, 100)

# src/options.cpp:2818-2824 SCALING_FACTOR values { 1, 2, 4 }, "1".
#
# It does NOT simply multiply the saved terminal dimensions.  The
# engine's order is divide, then multiply [src/sdltiles.cpp:6160-6252]:
#
#   terminal        = ( TERMINAL_X, TERMINAL_Y )      from options.json
#   terminal.x     -= terminal.x % scaling_factor     :6235-6236
#   terminal.x      = max( 80 * scaling_factor, ... ) :6238-6239
#   TERMINAL_WIDTH  = terminal.x / scaling_factor     :6251
#   WindowWidth     = TERMINAL_WIDTH * fontwidth
#                     * scaling_factor                :595
#
# So the saved TERMINAL_X is a PHYSICAL cell count while TERMINAL_WIDTH
# -- the LOGICAL grid everything on screen is laid out in, including the
# sidebar's width in cells -- is that number divided by the factor.  The
# trim and the floor are mirrored here because they are what the engine
# actually stored before it divided.  Mirroring this order avoids the
# squared-scaling error: dividing by the factor after multiplying the
# physical cell count by it would apply the factor twice.
DEFAULT_SCALING_FACTOR = 1
SCALING_FACTORS = (1, 2, 4)

# src/game_constants.h:11-12 EVEN_MINIMUM_TERM_WIDTH = 80 and
# EVEN_MINIMUM_TERM_HEIGHT = 24.  The engine refuses a terminal
# smaller than these times the scaling factor
# [src/sdltiles.cpp:6238-6239], so a smaller saved value never
# reaches the window computation.
EVEN_MINIMUM_TERM_WIDTH = 80
EVEN_MINIMUM_TERM_HEIGHT = 24

# src/options.cpp:2132-2136 SIDEBAR_POSITION { left, right }, "right".
# Both values are honoured.  Supporting only the default would make
# this module a constant wearing a function's clothes.
DEFAULT_SIDEBAR_POSITION = "right"
SIDEBAR_POSITIONS = ("left", "right")

# data/json/ui/sidebar.json:7 custom_sidebar "width": 36, recorded for
# reference only.  It is deliberately NOT a default of any kind: the width
# always comes from the widget the ACTIVE layout names, and there is no code
# path on which this number is substituted for it.
CUSTOM_SIDEBAR_CELLS = 36

# ---------------------------------------------------------------------
# WHICH SIDEBAR IS ACTUALLY ON SCREEN
#
# The crop must be taken from the layout the engine is CURRENTLY
# drawing, and that is not custom_sidebar on a fresh userdir.  Three
# facts decide it:
#
#   * panel_manager's constructor sets current_layout_id to
#     "legacy_labels_sidebar" on every non-Android build, and to
#     "sidebar-mobile" on Android [src/panels.cpp:412-418].
#   * The selection is persisted to and restored from
#     <userdir>/config/panel_options.json [src/panels.cpp:492-503,
#     :548, src/path_info.cpp:356-358], which is where a layout chosen
#     in game with the sidebar manager ends up.
#   * A layout id that no longer names a known layout falls back to
#     "legacy_classic_sidebar" [src/panels.cpp:426-431]; a persisted id
#     absent from the layout map falls back to "labels"
#     [src/panels.cpp:548-553].
#   * The layout map is built from EVERY widget whose style is
#     "sidebar" [src/panels.cpp:398-408], across the whole
#     data/json/ui tree -- not only data/json/ui/sidebar.json.
#   * The sidebar's width in cells is that layout widget's own "width"
#     [src/panels.cpp:484 update_offsets( ...panels().begin()
#     ->get_width() )].
#
# The consequence, measured in this checkout: legacy_labels_sidebar
# declares "width": 44, so a fresh non-Android game renders a 352 px
# sidebar where custom_sidebar's 36 cells would imply 288 px.  Reading
# the wrong one crops 64 pixels of the wrong column.
# ---------------------------------------------------------------------
DEFAULT_LAYOUT_ID = "legacy_labels_sidebar"
ANDROID_LAYOUT_ID = "sidebar-mobile"
INVALID_LAYOUT_FALLBACK_ID = "legacy_classic_sidebar"
MISSING_LAYOUT_FALLBACK_ID = "labels"
LAYOUT_KEY = "current_layout_id"

# THE WIDGETS THAT MAKE A LAYOUT USABLE FOR THIS PIPELINE.  What
# identifies the clock is not a widget id but the VARIABLE a widget
# renders, and the engine declares exactly two that carry a readable
# time:
#
#   time_text          "Current time - exact if character has a watch,
#                      approximate otherwise" [src/widget.h:92]
#   sundial_time_text  "Current time - exact if character has a watch,
#                      sundial otherwise" [src/widget.h:91]
#
# Both are exact with a watch, which is the condition this run satisfies
# in play, so either one makes a layout readable.  Matching on the
# variable rather than on `time_desc_label` means an alternate preset
# that draws the clock through a differently-named widget still counts --
# what matters is whether the clock is on the screen being cropped.
CLOCK_WIDGET_VARS = ("time_text", "sundial_time_text")

# The JSON inheritance key the content tree uses.  `time_desc_no_label`
# carries no `var` of its own and copies `time_desc_label`
# [data/json/ui/time.json], and the default sidebar reaches its clock
# through exactly such a chain -- ll_place_info copies
# all_location_info_rows_layout -- so a walk that did not follow
# copy-from would answer "no clock" for the layout this pipeline
# actually records under.  Measured: it did, before this was added.
COPY_FROM_KEY = "copy-from"

# The headless contract from playthrough/tooling/env.sh,
# "Display, window and grid geometry":
# `Xvfb :99 -screen 0 1920x1080x24`.  Capture targets the X ROOT, not
# the game window, so the root size is what the crop is aligned in.
DEFAULT_SCREEN_WIDTH = 1920
DEFAULT_SCREEN_HEIGHT = 1080

# The widget this module reads, by id first and by style second.
# data/json/ui/sidebar.json:3 "id", :5 "style".  The layout in force is
# resolved from the game's own configuration rather than fixed to one
# preset; DEFAULT_SIDEBAR_WIDGET_ID is the documented id of the
# custom_sidebar preset, for a caller that wants to ask for it by name.
DEFAULT_SIDEBAR_WIDGET_ID = "custom_sidebar"
SIDEBAR_WIDGET_STYLE = "sidebar"

# Where the sidebar widgets live.  data/json/ui/sidebar.json is looked
# at first because it is the file the pipeline documents, but the
# engine loads the WHOLE tree, so every *.json under data/json/ui --
# including the spacebar/, structured/ and zenfs/ bundles -- is
# searched for the resolved layout id, because the widths differ
# between presets and cropping the wrong column fails silently.
UI_JSON_PARTS = ("data", "json", "ui")
JSON_SUFFIX = ".json"

# Option names as the engine spells them in options.json.
OPT_TERMINAL_X = "TERMINAL_X"
OPT_TERMINAL_Y = "TERMINAL_Y"
OPT_FONT_WIDTH = "FONT_WIDTH"
OPT_FONT_HEIGHT = "FONT_HEIGHT"
OPT_SCALING_FACTOR = "SCALING_FACTOR"
OPT_SIDEBAR_POSITION = "SIDEBAR_POSITION"

# Environment variables exported by playthrough/tooling/env.sh, read
# here so that the display geometry and the artifact layout have a
# single definition shared with every other stage of the pipeline.
#
# The four grid and font names below form a MIDDLE tier, consulted only
# when the game-written options file does not carry the key -- the real
# state of a fresh userdir, since the engine writes options.json on its
# first launch [src/path_info.cpp:167].  Preferring the pipeline's
# declared contract in that window is what makes the crop match the
# frames actually being captured: the compiled-in defaults are 80x24
# cells, a 640x384 render grid, whereas capture runs at 240x67 cells and
# 1920x1072.  Every such substitution is announced.
#
# There is deliberately NO environment tier for the sidebar width.
# env.sh does export PLAYTHROUGH_SIDEBAR_CELLS, and honouring it
# would let a constant back in through the side door; the width is read
# from the game's own widget definition, which always ships, or the
# computation fails.  An explicit argument remains available for
# exercising other presets.
ENV_REPO_ROOT = "PLAYTHROUGH_REPO_ROOT"
ENV_OPTIONS_JSON = "PLAYTHROUGH_OPTIONS_JSON"
ENV_PANEL_OPTIONS = "PLAYTHROUGH_PANEL_OPTIONS_JSON"
ENV_CONFIG_DIR = "PLAYTHROUGH_CONFIG_DIR"
ENV_SCREEN_WIDTH = "PLAYTHROUGH_SCREEN_WIDTH"
ENV_SCREEN_HEIGHT = "PLAYTHROUGH_SCREEN_HEIGHT"
ENV_TERMINAL_X = "PLAYTHROUGH_TERMINAL_X"
ENV_TERMINAL_Y = "PLAYTHROUGH_TERMINAL_Y"
ENV_FONT_WIDTH = "PLAYTHROUGH_FONT_WIDTH"
ENV_FONT_HEIGHT = "PLAYTHROUGH_FONT_HEIGHT"

# Repository-relative locations, joined only from these literals.
# src/path_info.cpp:164 config_dir_value = user_dir_value + "config/";
# src/path_info.cpp:167 options_value = config_dir_value +
# "options.json";  The userdir itself is the pipeline's own
# ./playthrough/userdir/ (env.sh's PLAYTHROUGH_USERDIR,
# PLAYTHROUGH_CONFIG_DIR and PLAYTHROUGH_OPTIONS_JSON).
SIDEBAR_JSON_PARTS = ("data", "json", "ui", "sidebar.json")
OPTIONS_JSON_PARTS = ("playthrough", "userdir", "config", "options.json")
# src/path_info.cpp:356-358 panel_options() = config_dir /
# "panel_options.json"; src/panels.cpp:492-503 writes and reads it.
PANEL_OPTIONS_PARTS = ("playthrough", "userdir", "config",
                       "panel_options.json")

# Markers proving a directory really is a Cataclysm-DDA checkout.  The
# same pair env.sh asserts on sourcing, for the same reason: a wrong
# root would otherwise surface much later as an unreadable clock.
ROOT_MARKER_DIR_PARTS = ("data", "json", "ui")
ROOT_MARKER_FILE_PARTS = ("src", "path_info.cpp")


class GeometryError(Exception):
    """The crop rectangle could not be computed honestly.

    Raised rather than returning a plausible-looking rectangle, because
    a wrong crop crashes nothing downstream: every condition under which
    the answer would be a guess is turned into a hard, loud failure here.
    """


def _note(message: str, notes: Optional[List[str]] = None) -> None:
    """Announce a fallback and record it."""
    LOG.warning("%s", message)
    if notes is not None:
        notes.append(message)


@dataclass(frozen=True)
class Rect:
    """An immutable pixel rectangle in X root coordinates.

    Field order matches the ImageMagick geometry it renders to,
    ``WxH+X+Y``, so that reading the constructor call and reading the
    output string are the same exercise.
    """

    width: int
    height: int
    x: int
    y: int

    def __post_init__(self) -> None:
        """Reject a rectangle that cannot describe real pixels."""
        for name in ("width", "height", "x", "y"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise GeometryError(
                    f"Rect.{name} must be an int, got "
                    f"{type(value).__name__} ({value!r})")
        if self.width <= 0 or self.height <= 0:
            raise GeometryError(
                f"Rect must have positive extent, got "
                f"{self.width}x{self.height}")
        if self.x < 0 or self.y < 0:
            raise GeometryError(
                f"Rect origin must be non-negative, got "
                f"+{self.x}+{self.y}")

    @property
    def right(self) -> int:
        """One past the rightmost pixel column."""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """One past the bottommost pixel row."""
        return self.y + self.height

    @property
    def geometry(self) -> str:
        """The ImageMagick ``WxH+X+Y`` form of this rectangle.

        This is the exact string ``convert -crop`` expects, and the
        exact string this module prints on stdout.
        """
        return f"{self.width}x{self.height}+{self.x}+{self.y}"

    def contains(self, other: "Rect") -> bool:
        """True when ``other`` lies wholly inside this rectangle."""
        return (self.x <= other.x and
                self.y <= other.y and
                other.right <= self.right and
                other.bottom <= self.bottom)

    def __str__(self) -> str:
        """Render as the geometry string, for painless interpolation."""
        return self.geometry


@dataclass(frozen=True)
class WindowGeometry:
    """The game window, plus the grid and scale it was derived from.

    ``scale`` is the scaling factor that was actually IN FORCE, which
    is not always the one the options file asked for: the engine
    resets a factor too large for the display back to 1
    [src/sdltiles.cpp:6209-6232].  Returning it alongside the
    rectangle is what stops a caller from sizing the sidebar with a
    factor the engine had already abandoned.
    """

    rect: Rect
    cols: int
    rows: int
    scale: int


@dataclass(frozen=True)
class SidebarGeometry:
    """The computed crop plus every input it was computed from."""

    rect: Rect
    window: Rect
    screen_width: int
    screen_height: int
    sidebar_cells: int
    sidebar_widget_id: str
    # Which sidebar layout the crop was taken from, and on whose
    # authority: the game's own panel_options.json, the engine's
    # documented default, or a caller's explicit override.  Carried
    # because "44 cells" is only checkable if the reader knows which
    # of the eight shipped presets it came from.
    layout_id: str
    layout_source: str
    # terminal_x/y are the SAVED option values; terminal_cols/rows are
    # the LOGICAL grid the engine derives from them at this scaling
    # factor [src/sdltiles.cpp:6235-6252].  They differ only when the
    # scaling factor is above 1, and keeping both is what makes that
    # difference visible instead of quietly folded away.
    terminal_x: int
    terminal_y: int
    terminal_cols: int
    terminal_rows: int
    font_width: int
    font_height: int
    # The factor actually IN FORCE, which is the one the window was drawn
    # at: the SCALING_FACTOR option value except where the engine reset a
    # factor too large for the display back to 1 (recorded in notes).
    # Reporting the requested value would let a consumer -- the OCR row
    # height, for one -- measure a window that was never made.
    scaling_factor: int
    position: str
    sidebar_json: str
    options_json: str
    panel_options_json: str
    notes: Tuple[str, ...] = field(default=())

    @property
    def geometry(self) -> str:
        """The ImageMagick ``WxH+X+Y`` crop for the sidebar column."""
        return self.rect.geometry

    @property
    def used_fallbacks(self) -> bool:
        """True when at least one value did not come from the game.

        A caller that wants to refuse a derived-from-defaults crop --
        ``verify_artifacts.sh``, say -- can gate on this instead of
        parsing :attr:`notes`.
        """
        return bool(self.notes)

    def describe(self) -> str:
        """A human-readable derivation of the crop, for stderr.

        Every term is shown with the arithmetic that produced it, so
        that a surprising rectangle can be traced to the input that
        surprised, rather than merely disbelieved.
        """
        cell_w = self.font_width * self.scaling_factor
        cell_h = self.font_height * self.scaling_factor
        lines = [
            "sidebar OCR crop derivation",
            f"  panel options         {self.panel_options_json}",
            f"  sidebar layout        {self.layout_id}"
            f" (from {self.layout_source})",
            f"  sidebar json          {self.sidebar_json}",
            f"  sidebar widget        {self.sidebar_widget_id}",
            f"  options json          {self.options_json}",
            f"  X root                {self.screen_width}"
            f"x{self.screen_height}",
            f"  saved terminal        {self.terminal_x}"
            f"x{self.terminal_y} cells",
            f"  logical grid          {self.terminal_cols}"
            f"x{self.terminal_rows} cells",
            f"  font cell             {self.font_width}"
            f"x{self.font_height} px",
            f"  scaling factor        {self.scaling_factor}",
            f"  effective cell        {cell_w}x{cell_h} px",
            f"  render grid           {self.window.geometry}",
            f"  sidebar position      {self.position}",
            f"  sidebar width         {self.sidebar_cells} cells"
            f" * {cell_w} px = {self.rect.width} px",
            f"  sidebar height        {self.terminal_rows} cells"
            f" * {cell_h} px = {self.rect.height} px",
            f"  grid origin y         ({self.screen_height}"
            f" - {self.window.height}) // 2 = {self.rect.y}",
            f"  crop                  {self.rect.geometry}",
        ]
        if self.notes:
            lines.append("  substitutions made:")
            for note in self.notes:
                lines.append(f"    - {note}")
        else:
            lines.append(
                "  substitutions made: none, every value came from "
                "the game's own configuration")
        return "\n".join(lines)


# ---------------------------------------------------------------------
# Path resolution
#
# Every path this module builds is joined from module-level literal
# components onto a directory that has already been validated as a
# Cataclysm-DDA checkout.  Nothing user-supplied is ever concatenated
# into a path: a caller who wants a different file passes the whole
# path, which is used verbatim and checked for existence.  That keeps
# the module free of the unvalidated-path-join pattern the repository's
# CodeQL python leg gates on
# [.github/workflows/codeql-analysis.yml:35].
# ---------------------------------------------------------------------

def _join(base: str, parts: Sequence[str]) -> str:
    """Join literal path components onto a base directory."""
    return os.path.normpath(os.path.join(base, *parts))


def _looks_like_checkout(candidate: str) -> bool:
    """True when ``candidate`` holds this repository's marker paths."""
    return (os.path.isdir(_join(candidate, ROOT_MARKER_DIR_PARTS)) and
            os.path.isfile(_join(candidate, ROOT_MARKER_FILE_PARTS)))


def repo_root(explicit: Optional[str] = None) -> str:
    """Return the absolute repository root, verified to be one.

    Resolution order:

    1. ``explicit``, when a caller passes one;
    2. ``$PLAYTHROUGH_REPO_ROOT``, exported by
       ``playthrough/tooling/env.sh``, so that every stage of the
       pipeline agrees on the root;
    3. two directories above this file, which is the idiom
       ``tools/json_tools/util.py:13-16`` uses.

    AN INVALID NOMINATED ROOT IS FATAL; IT IS NOT SKIPPED.  Steps 1 and
    2 are *instructions*, not guesses: someone stated which checkout to
    read, and falling through to this module's own checkout would compute
    a well-formed rectangle from the wrong sidebar layout and the wrong
    options file -- the silent failure described at the top of this
    module.  So a nominated root that is not a checkout raises, NAMING
    the path that was rejected.  Step 3 is the only fallback, and it is a
    derivation rather than an instruction.

    :raises GeometryError: when a nominated root is not a Cataclysm-DDA
        checkout, or when no root could be located at all.
    """
    marker_dir = os.path.join(*ROOT_MARKER_DIR_PARTS)
    marker_file = os.path.join(*ROOT_MARKER_FILE_PARTS)

    nominated = []
    if explicit:
        nominated.append(("the explicit root argument", explicit))
    env_root = os.environ.get(ENV_REPO_ROOT)
    if env_root and env_root.strip():
        nominated.append((f"${ENV_REPO_ROOT}", env_root))

    for origin, candidate in nominated:
        resolved = os.path.abspath(os.path.normpath(candidate))
        if _looks_like_checkout(resolved):
            LOG.debug("repository root from %s: %s", origin, resolved)
            return resolved
        raise GeometryError(
            f"{origin} names '{candidate}' (resolved to "
            f"'{resolved}'), which is not a Cataclysm-DDA checkout: it "
            f"has no {marker_dir} directory or no {marker_file} file.  "
            f"That root was asked for explicitly, so it is not "
            f"silently replaced with this module's own checkout -- "
            f"which would compute a crop from a different sidebar "
            f"layout and a different options file, and the wrong "
            f"column reads as an unreadable clock rather than as an "
            f"error")

    here = os.path.abspath(os.path.dirname(__file__))
    derived = os.path.abspath(os.path.normpath(_join(here, ("..", ".."))))
    if _looks_like_checkout(derived):
        LOG.debug("repository root from this file's location: %s",
                  derived)
        return derived

    raise GeometryError(
        f"cannot locate a Cataclysm-DDA checkout (no {marker_dir} "
        f"directory and no {marker_file} file); this module resolves "
        f"to '{derived}' from its own location, and no root was "
        f"nominated by an argument or ${ENV_REPO_ROOT}")


def sidebar_json_path(root: Optional[str] = None) -> str:
    """Absolute path of ``data/json/ui/sidebar.json``.

    Read-only input.  This file belongs to the game's content tree and
    is never written by this pipeline.
    """
    return _join(repo_root(root), SIDEBAR_JSON_PARTS)


def options_json_path(root: Optional[str] = None) -> str:
    """Absolute path of the game-written ``options.json``.

    ``$PLAYTHROUGH_OPTIONS_JSON`` wins when set
    [playthrough/tooling/env.sh], so the value is defined once for
    the whole pipeline.  Otherwise the path is derived exactly as the
    engine derives it -- ``config_dir_value = user_dir_value +
    "config/"`` [src/path_info.cpp:164] and ``options_value =
    config_dir_value + "options.json"`` [src/path_info.cpp:167] --
    under this pipeline's own ``./playthrough/userdir/``.
    """
    from_env = os.environ.get(ENV_OPTIONS_JSON)
    if from_env:
        return os.path.abspath(os.path.normpath(from_env))
    return _join(repo_root(root), OPTIONS_JSON_PARTS)


def panel_options_path(root: Optional[str] = None) -> str:
    """Absolute path of the game-written ``panel_options.json``.

    This is where the engine persists which sidebar layout is on
    screen -- ``PATH_INFO::panel_options()`` is
    ``config_dir_path_value / "panel_options.json"``
    [src/path_info.cpp:356-358], written by ``panel_manager::save()``
    and read by ``panel_manager::load()`` [src/panels.cpp:492-503].

    ``$PLAYTHROUGH_PANEL_OPTIONS_JSON`` wins when set, then
    ``$PLAYTHROUGH_CONFIG_DIR`` -- both from env.sh, which owns the
    artifact layout -- and otherwise the path is derived as the engine
    derives it under this pipeline's own ``./playthrough/userdir/``.
    """
    from_env = os.environ.get(ENV_PANEL_OPTIONS)
    if from_env:
        return os.path.abspath(os.path.normpath(from_env))
    config_dir = os.environ.get(ENV_CONFIG_DIR)
    if config_dir:
        return _join(os.path.abspath(os.path.normpath(config_dir)),
                     ("panel_options.json",))
    return _join(repo_root(root), PANEL_OPTIONS_PARTS)


def ui_json_dir(root: Optional[str] = None) -> str:
    """Absolute path of the widget tree ``data/json/ui``.

    Read-only input.  The engine loads every widget in this tree, so
    the layout resolved from ``panel_options.json`` may be defined in
    any file under it, not only in ``sidebar.json``.
    """
    return _join(repo_root(root), UI_JSON_PARTS)


# ---------------------------------------------------------------------
# Readers
#
# The distinction these two functions draw, and hold to deliberately:
#
#   ABSENT input   -> substitute the engine's documented default,
#                     announce it at WARNING and record it in notes.
#                     A fresh userdir genuinely has no options.json
#                     until the game has been launched once, so this
#                     is an ordinary, expected state.
#   MALFORMED input-> raise GeometryError.  A file that exists but
#                     cannot be believed is not a missing value; it
#                     means the input is not what this module thinks
#                     it is, and defaulting past it would manufacture
#                     precisely the confident-but-wrong rectangle
#                     everything here exists to prevent.
# ---------------------------------------------------------------------


def _load_json(path: str, what: str) -> object:
    """Read and parse one JSON file, loudly.

    :raises GeometryError: on any read or parse failure, with the path
        and the underlying reason preserved.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as err:
        raise GeometryError(
            f"cannot read {what} at {path}: {err}") from err
    except ValueError as err:
        raise GeometryError(
            f"{what} at {path} is not valid JSON: {err}") from err


def read_current_layout_id(
    path: Optional[str] = None,
    notes: Optional[List[str]] = None,
    root: Optional[str] = None,
) -> Tuple[str, str]:
    """Return the sidebar layout the engine is currently drawing.

    ``panel_manager::serialize`` writes a one-element JSON array whose
    single object carries ``current_layout_id`` [src/panels.cpp:
    508-513], and ``deserialize`` reads it back from element 0
    [src/panels.cpp:544-548].  That file only exists once the game has
    saved its panel options; until then the engine's own constructor
    default applies -- ``legacy_labels_sidebar`` on every non-Android
    build [src/panels.cpp:412-418].

    :returns: ``(layout_id, source)`` where ``source`` is
        ``"panel_options.json"`` or ``"engine default"``. :raises
        GeometryError: when the file exists but is not the shape the engine
        writes.
    """
    resolved = path or panel_options_path(root)
    if not os.path.exists(resolved):
        _note(
            f"{resolved} does not exist yet, so the sidebar layout is "
            f"the engine's own default '{DEFAULT_LAYOUT_ID}' "
            f"[src/panels.cpp:412-418]; it is written once the game "
            f"saves its panel options",
            notes)
        return DEFAULT_LAYOUT_ID, "engine default"

    data = _load_json(resolved, "panel options")
    holder: object = data
    if isinstance(data, list):
        if not data:
            raise GeometryError(
                f"{resolved} is an empty JSON array; the engine writes "
                f"exactly one object into it "
                f"[src/panels.cpp:508-513], so this file cannot say "
                f"which sidebar is on screen and no layout will be "
                f"guessed for it")
        holder = data[0]
    if not isinstance(holder, dict):
        raise GeometryError(
            f"{resolved} holds a {type(holder).__name__} where the "
            f"engine writes an object carrying '{LAYOUT_KEY}' "
            f"[src/panels.cpp:508-513]")
    if LAYOUT_KEY not in holder:
        raise GeometryError(
            f"{resolved} carries no '{LAYOUT_KEY}'; the engine always "
            f"writes it [src/panels.cpp:512], so this is not a panel "
            f"options file and the layout will not be guessed")
    layout_id = holder[LAYOUT_KEY]
    if not isinstance(layout_id, str) or not layout_id.strip():
        raise GeometryError(
            f"{resolved} declares {LAYOUT_KEY}={layout_id!r}, which is "
            f"not a layout id")
    LOG.debug("current sidebar layout %r from %s", layout_id, resolved)
    return layout_id.strip(), "panel_options.json"


def _widget_files(root: Optional[str] = None) -> List[str]:
    """Every widget JSON file the engine loads, in a stable order."""
    base = ui_json_dir(root)
    documented = _join(repo_root(root), SIDEBAR_JSON_PARTS)
    found: List[str] = []
    if os.path.isfile(documented):
        found.append(documented)
    for current, directories, files in os.walk(base):
        directories.sort()
        for name in sorted(files):
            if not name.endswith(JSON_SUFFIX):
                continue
            candidate = os.path.normpath(os.path.join(current, name))
            if candidate not in found:
                found.append(candidate)
    return found


def _sidebar_widgets(
    paths: Sequence[str],
) -> List[Tuple[str, Dict[str, object]]]:
    """Return every ``style: sidebar`` widget in ``paths``."""
    widgets: List[Tuple[str, Dict[str, object]]] = []
    for path in paths:
        try:
            data = _load_json(path, "widget definition")
        except GeometryError as err:
            LOG.debug("skipping unreadable widget file: %s", err)
            continue
        if not isinstance(data, list):
            continue
        for entry in data:
            if (isinstance(entry, dict) and
                    entry.get("style") == SIDEBAR_WIDGET_STYLE):
                widgets.append((path, entry))
    return widgets


def _widget_width(
    path: str, widget: Dict[str, object],
) -> int:
    """Return one widget's declared width in cells, or raise."""
    if "width" not in widget:
        raise GeometryError(
            f"widget '{widget.get('id')}' in {path} declares no "
            f"'width'; the sidebar width cannot be read and will not "
            f"be guessed")
    cells = widget["width"]
    if isinstance(cells, bool) or not isinstance(cells, int):
        raise GeometryError(
            f"widget '{widget.get('id')}' in {path} declares width "
            f"{cells!r}, which is not an integer")
    if cells <= 0:
        raise GeometryError(
            f"widget '{widget.get('id')}' in {path} declares width "
            f"{cells}, which is not a positive cell count")
    return cells


def _all_widgets(
    paths: Sequence[str],
) -> Dict[str, Tuple[str, Dict[str, object]]]:
    """Return {widget id: (file, widget)} for the whole widget tree."""
    found: Dict[str, Tuple[str, Dict[str, object]]] = {}
    for path in paths:
        try:
            data = _load_json(path, "widget definition")
        except GeometryError as err:
            LOG.debug("skipping unreadable widget file: %s", err)
            continue
        if not isinstance(data, list):
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("id")
            if isinstance(identifier, str) and identifier not in found:
                found[identifier] = (path, entry)
    return found


def layout_shows_the_clock(
    layout_id: str,
    root: Optional[str] = None,
    paths: Optional[Sequence[str]] = None,
) -> bool:
    """True when this layout draws the sidebar clock.

    WHY A LAYOUT HAS TO BE ASKED THIS.  The crop this module computes is
    where the clock is READ from, and the clock is the sole authority for
    every duration in the film.  A layout that is perfectly resolvable
    and simply does not include the time widget would yield a valid crop
    over a column with no clock in it -- every reading unreadable, every
    duration at the floor, and the pacing fiction.  So the question is
    asked of the layout's own contents rather than of its id.
    """
    widgets = _all_widgets(
        list(paths) if paths is not None else _widget_files(root))
    seen = set()
    pending = [layout_id]
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        entry = widgets.get(identifier)
        if entry is None:
            continue
        _path, widget = entry
        if widget.get("var") in CLOCK_WIDGET_VARS:
            return True
        children = widget.get("widgets")
        if isinstance(children, list):
            pending.extend(
                child for child in children if isinstance(child, str))
        inherited = widget.get(COPY_FROM_KEY)
        if isinstance(inherited, str):
            pending.append(inherited)
    return False


def resolve_sidebar_widget(
    layout_id: str,
    notes: Optional[List[str]] = None,
    root: Optional[str] = None,
    paths: Optional[Sequence[str]] = None,
) -> Tuple[int, str, str]:
    """Resolve one layout id to its widget width, as the engine does.

    The engine builds its layout map from every ``style: sidebar``
    widget in the whole content tree and keys it by widget id
    [src/panels.cpp:398-408]; the sidebar's width in cells is that
    widget's own ``width`` [src/panels.cpp:484].  This mirrors both,
    including the engine's two fallbacks for an id that no longer
    names a layout: ``legacy_classic_sidebar``
    [src/panels.cpp:426-431] and then ``labels``
    [src/panels.cpp:548-553].  Every fallback is announced, because a
    crop taken from a layout other than the one asked for is exactly
    the kind of substitution a reader needs to see.

    :returns: ``(cells, widget_id_used, widget_file)``.
    :raises GeometryError: when no sidebar widget can be found at all,
        or when the resolved widget's width cannot be believed.
    """
    searched = list(paths) if paths is not None else _widget_files(root)
    widgets = _sidebar_widgets(searched)
    if not widgets:
        raise GeometryError(
            f"no widget with style '{SIDEBAR_WIDGET_STYLE}' exists "
            f"anywhere under {ui_json_dir(root)}; the sidebar width "
            f"cannot be read and will not be guessed")

    by_id = {}
    for path, widget in widgets:
        identifier = widget.get("id")
        if isinstance(identifier, str) and identifier not in by_id:
            by_id[identifier] = (path, widget)

    for candidate, why in (
            (layout_id, None),
            (INVALID_LAYOUT_FALLBACK_ID,
             "src/panels.cpp:426-431"),
            (MISSING_LAYOUT_FALLBACK_ID,
             "src/panels.cpp:548-553")):
        if candidate not in by_id:
            continue
        path, widget = by_id[candidate]
        if why is not None:
            _note(
                f"no sidebar widget is named '{layout_id}', so the "
                f"engine's own fallback layout '{candidate}' [{why}] "
                f"was used for the crop instead",
                notes)
        return _widget_width(path, widget), candidate, path

    path, widget = widgets[0]
    identifier = widget.get("id")
    used = identifier if isinstance(identifier, str) else layout_id
    _note(
        f"neither '{layout_id}' nor either of the engine's fallback "
        f"layouts ('{INVALID_LAYOUT_FALLBACK_ID}', "
        f"'{MISSING_LAYOUT_FALLBACK_ID}') exists under "
        f"{ui_json_dir(root)}; used the first sidebar widget found, "
        f"'{used}' in {path}",
        notes)
    return _widget_width(path, widget), used, path


def load_options(
    path: Optional[str] = None,
    notes: Optional[List[str]] = None,
    root: Optional[str] = None,
) -> Dict[str, str]:
    """Load the game-written ``options.json`` as a name-to-value map.

    The engine serialises this file as a JSON **array** of objects, one
    per option, each carrying ``info``, ``default``, ``name`` and
    ``value``, and ``value`` is always a **string** even for numeric
    options -- ``json.member( "value", opt.getValue( true ) )``
    [src/options.cpp:4052-4078], read back with
    ``joOptions.get_string( "value" )`` [src/options.cpp:4080-4100].  So
    ``TERMINAL_X`` arrives as ``"240"``, not ``240``.

    :raises GeometryError: when the file exists but is unreadable, unparseable,
        or of an unrecognised shape.
    """
    resolved = path or options_json_path(root)
    if not os.path.isfile(resolved):
        _note(
            f"no options file at {resolved}; every value it would "
            f"supply falls back to the engine's documented default "
            f"(the game writes this file on its first launch)",
            notes)
        return {}

    data = _load_json(resolved, "game options")
    values: Dict[str, str] = {}

    if isinstance(data, list):
        for index, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise GeometryError(
                    f"{resolved} entry {index} is "
                    f"{type(entry).__name__}, expected an object with "
                    f"'name' and 'value' members")
            if "name" not in entry or "value" not in entry:
                raise GeometryError(
                    f"{resolved} entry {index} lacks 'name' or "
                    f"'value'; keys present: "
                    f"{sorted(entry)}")
            name = entry["name"]
            if not isinstance(name, str):
                raise GeometryError(
                    f"{resolved} entry {index} has a non-string "
                    f"'name' ({name!r})")
            values[name] = _scalar_str(entry["value"], name, resolved)
    elif isinstance(data, dict):
        for name, raw in data.items():
            if isinstance(raw, dict) and "value" in raw:
                raw = raw["value"]
            values[name] = _scalar_str(raw, name, resolved)
    else:
        raise GeometryError(
            f"{resolved} must be a JSON array of option objects or a "
            f"name-to-value object, got {type(data).__name__}")

    LOG.debug("loaded %d option values from %s", len(values), resolved)
    return values


def _scalar_str(raw: object, name: str, source: str) -> str:
    """Normalise one option value to the engine's string form."""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (str, int, float)):
        return str(raw)
    raise GeometryError(
        f"option '{name}' in {source} has value {raw!r} of type "
        f"{type(raw).__name__}, which is not a scalar")


def option_int(
    options: Dict[str, str],
    name: str,
    default: int,
    notes: Optional[List[str]] = None,
    valid_range: Optional[Tuple[int, int]] = None,
) -> int:
    """Read one integer option, substituting its default visibly.

    :raises GeometryError: when the value is present but not a positive
        integer.
    """
    if name not in options:
        _note(
            f"option '{name}' is absent; using the engine's "
            f"documented default {default}",
            notes)
        return default

    raw = options[name]
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as err:
        raise GeometryError(
            f"option '{name}' is {raw!r}, which is not an integer; "
            f"refusing to guess a crop from it") from err

    if value <= 0:
        raise GeometryError(
            f"option '{name}' is {value}, which cannot describe a "
            f"pixel dimension")

    if valid_range is not None:
        low, high = valid_range
        if value < low or value > high:
            _note(
                f"option '{name}' is {value}, outside the engine's "
                f"declared range {low}-{high}; using it as read "
                f"because the options file is authoritative about "
                f"what the game is running with",
                notes)

    return value


def option_str(
    options: Dict[str, str],
    name: str,
    default: str,
    notes: Optional[List[str]] = None,
    allowed: Optional[Sequence[str]] = None,
) -> str:
    """Read one string option, substituting its default visibly.

    :raises GeometryError: when the value is present but outside ``allowed``.
        For ``SIDEBAR_POSITION`` that matters concretely: an unrecognised value
        means the side the sidebar is drawn on is unknown, and picking one
        would be a coin toss dressed as a computation.
    """
    if name not in options:
        _note(
            f"option '{name}' is absent; using the engine's "
            f"documented default '{default}'",
            notes)
        return default

    value = str(options[name]).strip()
    if allowed is not None and value not in allowed:
        permitted = ", ".join(allowed)
        raise GeometryError(
            f"option '{name}' is '{value}', which is not one of "
            f"{permitted}; refusing to guess which side the sidebar "
            f"is drawn on")
    return value


def resolve_screen_size(
    width: Optional[int] = None,
    height: Optional[int] = None,
    notes: Optional[List[str]] = None,
) -> Tuple[int, int]:
    """Resolve the X root size the crop is aligned inside.

    Capture targets the X ROOT rather than the game X window, because
    photographing the root yields a true-resolution PNG whose only
    non-game pixels are the letterbox band and which needs no
    rescaling -- rescaling would soften exactly the 8x16 glyphs the
    clock OCR depends on [playthrough/tooling/env.sh, "Display, window
    and grid geometry"].

    Resolution order per axis: an explicit argument, then the
    ``PLAYTHROUGH_SCREEN_WIDTH`` / ``PLAYTHROUGH_SCREEN_HEIGHT`` exports
    [playthrough/tooling/env.sh], then the documented default with a
    visible note.  Taking it from the environment rather than baking it
    into the arithmetic keeps the right-alignment correct if the display
    ever changes.

    :raises GeometryError: when an explicit argument or an environment
        value is not a positive integer.
    """
    axes = (
        ("width", width, ENV_SCREEN_WIDTH, DEFAULT_SCREEN_WIDTH),
        ("height", height, ENV_SCREEN_HEIGHT, DEFAULT_SCREEN_HEIGHT),
    )
    resolved: List[int] = []
    for axis, explicit, env_name, default in axes:
        if explicit is not None:
            resolved.append(_positive_int(explicit, f"screen {axis}"))
            continue
        from_env = os.environ.get(env_name)
        if from_env is not None and from_env.strip():
            resolved.append(
                _positive_int(from_env.strip(), f"${env_name}"))
            continue
        _note(
            f"screen {axis} is not set (no argument and no "
            f"${env_name}); using the headless contract's documented "
            f"{default}",
            notes)
        resolved.append(default)
    return resolved[0], resolved[1]


def _resolve_int(
    explicit: Optional[int],
    options: Dict[str, str],
    name: str,
    env_name: Optional[str],
    default: int,
    notes: Optional[List[str]] = None,
    valid_range: Optional[Tuple[int, int]] = None,
) -> int:
    """Resolve one integer term through the three-tier order."""
    if explicit is not None:
        return _positive_int(explicit, f"{name} override")
    if name in options:
        return option_int(options, name, default, notes, valid_range)
    if env_name:
        raw = os.environ.get(env_name)
        if raw is not None and raw.strip():
            value = _positive_int(raw.strip(), f"${env_name}")
            _note(
                f"option '{name}' is absent; using ${env_name} = "
                f"{value} from the pipeline's environment contract "
                f"(playthrough/tooling/env.sh) in preference to the "
                f"engine's first-launch default {default}",
                notes)
            return value
    return option_int(options, name, default, notes, valid_range)


def _resolve_scaling_factor(
    explicit: Optional[int],
    options: Dict[str, str],
    notes: Optional[List[str]] = None,
) -> int:
    """Resolve ``SCALING_FACTOR`` as a SET, never as a range.

    The engine declares it as an enumeration of exactly ``{1, 2, 4}``
    [src/options.cpp:2818-2824] -- a copt with three named values, not a
    numeric option with bounds -- so a range test of 1 to 4 is the wrong
    shape of check: it admits 3, which the engine cannot produce and
    would not accept.

    That matters because this value multiplies BOTH window axes
    [src/sdltiles.cpp:595-596] and therefore multiplies the crop: a scale
    of 3 would compute a sidebar rectangle for a window the game never
    renders, landing on the wrong pixels.  A value the engine cannot hold
    is therefore refused rather than used.

    :raises GeometryError: when an explicit argument or the value in the
        options file is not one of the three the engine permits.
    """
    permitted = ", ".join(str(value) for value in SCALING_FACTORS)
    if explicit is not None:
        value = _positive_int(explicit, f"{OPT_SCALING_FACTOR} override")
        if value not in SCALING_FACTORS:
            raise GeometryError(
                f"{OPT_SCALING_FACTOR} override is {value}, which is "
                f"not one of the {permitted} the engine declares "
                f"[src/options.cpp:2818-2824].  It multiplies both "
                f"window axes, so an impossible value would compute a "
                f"crop for a window the game never renders")
        return value

    if OPT_SCALING_FACTOR not in options:
        _note(
            f"option '{OPT_SCALING_FACTOR}' is absent; using the "
            f"engine's documented default {DEFAULT_SCALING_FACTOR}",
            notes)
        return DEFAULT_SCALING_FACTOR

    raw = options[OPT_SCALING_FACTOR]
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as err:
        raise GeometryError(
            f"option '{OPT_SCALING_FACTOR}' is {raw!r}, which is not "
            f"an integer; refusing to guess a crop from it") from err
    if value not in SCALING_FACTORS:
        raise GeometryError(
            f"option '{OPT_SCALING_FACTOR}' is {value}, which is not "
            f"one of the {permitted} the engine declares "
            f"[src/options.cpp:2818-2824].  Unlike a numeric option "
            f"that is merely out of range, an unlisted value here is "
            f"one the engine cannot hold, so the options file is not "
            f"describing a state the game can be in -- and the crop "
            f"derived from it would silently read the wrong pixels")
    return value


def _positive_int(raw: object, what: str) -> int:
    """Coerce ``raw`` to a positive int or raise loudly."""
    if isinstance(raw, bool):
        raise GeometryError(f"{what} is {raw!r}, not an integer")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as err:
        raise GeometryError(
            f"{what} is {raw!r}, which is not an integer") from err
    if value <= 0:
        raise GeometryError(
            f"{what} is {value}, which is not a positive pixel count")
    return value


# ---------------------------------------------------------------------
# The computation
# ---------------------------------------------------------------------

def engine_logical_grid(
    terminal_x: int,
    terminal_y: int,
    font_width: int,
    font_height: int,
    scaling_factor: int,
    screen_width: int,
    screen_height: int,
    notes: Optional[List[str]] = None,
) -> Tuple[int, int, int]:
    """Turn the SAVED terminal option values into the LOGICAL grid.

    A faithful mirror of ``init_term_size_and_scaling_factor``
    [src/sdltiles.cpp:6159-6253], in the engine's own order, including
    the two branches that are easy to miss:

    1. At scaling factor 1 the saved values pass through untouched --
       every adjustment below lives inside ``if( scaling_factor > 1 )``
       [:6172-6247].
    2. A factor too large for the display is RESET TO 1 and the
       terminal is recomputed from the display size [:6209-6232]: the
       engine refuses to run a scaled grid it cannot fit even at the
       minimum terminal size, and says so with "SCALING_FACTOR set too
       high for display size, resetting to 1".  A caller that models
       only the arithmetic and not this reset computes a crop four
       times too wide for a display the engine is in fact drawing
       unscaled.
    3. Only then is the value trimmed to a multiple of the factor
       [:6235-6236], floored at ``EVEN_MINIMUM_TERM_* * factor``
       [:6238-6239], and DIVIDED by the factor to give
       ``TERMINAL_WIDTH``/``TERMINAL_HEIGHT`` [:6251-6252].

    The display bound used here is the X root, which is what the engine
    uses when ``FULLSCREEN`` is anything but ``"no"``: it takes the
    desktop display mode rather than probing a maximised test window
    [:6180-6202].  ``FULLSCREEN`` defaults to windowed borderless
    [src/options.cpp:2715-2724] and this pipeline never changes it.

    ``scaling_factor`` is checked against the engine's enumeration
    ``{1, 2, 4}`` [src/options.cpp:2818-2824] rather than merely for
    positivity.  :func:`_resolve_scaling_factor` already refuses an
    unlisted value on the configuration path, but this is the function
    that multiplies both axes, so it enforces the same set itself: a
    scale of 3 from any other caller would produce a well-formed
    rectangle for a window the game never renders.

    :returns: ``(cols, rows, effective_scaling_factor)``. :raises
        GeometryError: when any input is not a positive integer, or when
        ``scaling_factor`` is not one of the three the engine permits.
    """
    grid_x = _positive_int(terminal_x, "terminal width")
    grid_y = _positive_int(terminal_y, "terminal height")
    font_w = _positive_int(font_width, "font width")
    font_h = _positive_int(font_height, "font height")
    scale = _positive_int(scaling_factor, "scaling factor")
    if scale not in SCALING_FACTORS:
        permitted = ", ".join(str(value) for value in SCALING_FACTORS)
        raise GeometryError(
            f"scaling factor is {scale}, which is not one of the "
            f"{permitted} the engine declares "
            f"[src/options.cpp:2818-2824]; it multiplies both window "
            f"axes, so an impossible value would describe a window "
            f"geometry the game never renders")
    max_w = _positive_int(screen_width, "screen width")
    max_h = _positive_int(screen_height, "screen height")

    if scale == 1:
        # src/sdltiles.cpp:6172 -- everything below is conditional on a
        # scaling factor above 1, so an unscaled grid is used verbatim.
        return grid_x, grid_y, scale

    def _reset_to_unscaled(axis: str, minimum: int) -> Tuple[int, int]:
        _note(
            f"scaling factor {scale} cannot fit the minimum terminal "
            f"{axis} of {minimum} cells on a {max_w}x{max_h} display, "
            f"so the engine resets the factor to 1 and recomputes the "
            f"terminal from the display size "
            f"[src/sdltiles.cpp:6209-6232]",
            notes)
        return max_w // font_w, max_h // font_h

    if (grid_x * font_w > max_w or
            EVEN_MINIMUM_TERM_WIDTH * font_w * scale > max_w):
        if EVEN_MINIMUM_TERM_WIDTH * font_w * scale > max_w:
            grid_x, grid_y = _reset_to_unscaled(
                "width", EVEN_MINIMUM_TERM_WIDTH)
            scale = 1
        else:
            _note(
                f"the saved terminal width {grid_x} cells would need "
                f"{grid_x * font_w} px on a {max_w} px display, so the "
                f"engine reduces it to {max_w // font_w} cells "
                f"[src/sdltiles.cpp:6209-6219]",
                notes)
            grid_x = max_w // font_w

    if (grid_y * font_h > max_h or
            EVEN_MINIMUM_TERM_HEIGHT * font_h * scale > max_h):
        if EVEN_MINIMUM_TERM_HEIGHT * font_h * scale > max_h:
            grid_x, grid_y = _reset_to_unscaled(
                "height", EVEN_MINIMUM_TERM_HEIGHT)
            scale = 1
        else:
            _note(
                f"the saved terminal height {grid_y} cells would need "
                f"{grid_y * font_h} px on a {max_h} px display, so the "
                f"engine reduces it to {max_h // font_h} cells "
                f"[src/sdltiles.cpp:6221-6233]",
                notes)
            grid_y = max_h // font_h

    if scale == 1:
        # The reset above already recomputed the terminal from the
        # display, and the engine's remaining adjustments are no-ops at
        # factor 1.
        return grid_x, grid_y, scale

    trimmed_x = max(EVEN_MINIMUM_TERM_WIDTH * scale,
                    grid_x - (grid_x % scale))
    trimmed_y = max(EVEN_MINIMUM_TERM_HEIGHT * scale,
                    grid_y - (grid_y % scale))
    if trimmed_x != grid_x or trimmed_y != grid_y:
        _note(
            f"at scaling factor {scale} the engine trims the terminal "
            f"to a multiple of the factor and floors it at "
            f"{EVEN_MINIMUM_TERM_WIDTH} x {EVEN_MINIMUM_TERM_HEIGHT} "
            f"cells times the factor [src/sdltiles.cpp:6235-6239], "
            f"turning {grid_x}x{grid_y} into {trimmed_x}x{trimmed_y} "
            f"physical cells",
            notes)
    return trimmed_x // scale, trimmed_y // scale, scale


def resolve_window(
    terminal_x: int,
    terminal_y: int,
    font_width: int,
    font_height: int,
    scaling_factor: int = DEFAULT_SCALING_FACTOR,
    screen_width: int = DEFAULT_SCREEN_WIDTH,
    screen_height: int = DEFAULT_SCREEN_HEIGHT,
    notes: Optional[List[str]] = None,
) -> "WindowGeometry":
    """Derive the game window's rectangle inside the X root.

    The extent is the engine's own arithmetic in the engine's own order,
    mirrored through :func:`engine_logical_grid`: ``TERMINAL_WIDTH`` is
    NOT the saved ``TERMINAL_X`` but that value trimmed, floored and
    DIVIDED by the scaling factor [src/sdltiles.cpp:6235-6252], which
    ``WindowWidth = TERMINAL_WIDTH * fontwidth * scaling_factor``
    [:595-596] then multiplies back up.  THE FORMULA at the top of this
    module has why performing only the multiplication is wrong.

    The window is then centred in the root, which is where the letterbox
    comes from.  A grid larger than the root is clamped to the root and
    reported, because the engine does the same thing in that situation --
    it calls ``GetWindowSize`` and recomputes ``TERMINAL_WIDTH`` and
    ``TERMINAL_HEIGHT`` from the actual window
    [src/sdltiles.cpp:671-675] -- so the root is the honest bound.

    :returns: a :class:`WindowGeometry` carrying the rectangle, the
        logical grid it was built from, and the scaling factor that
        was actually in force after the engine's own adjustments.
    :raises GeometryError: when any input is not a positive integer.
    """
    root_w = _positive_int(screen_width, "screen width")
    root_h = _positive_int(screen_height, "screen height")
    cols, rows, scale = engine_logical_grid(
        terminal_x=terminal_x,
        terminal_y=terminal_y,
        font_width=font_width,
        font_height=font_height,
        scaling_factor=scaling_factor,
        screen_width=root_w,
        screen_height=root_h,
        notes=notes)
    cell_w = _positive_int(font_width, "font width") * scale
    cell_h = _positive_int(font_height, "font height") * scale
    width = cols * cell_w
    height = rows * cell_h

    if width > root_w:
        _note(
            f"the terminal grid implies a {width} px wide window but "
            f"the X root is only {root_w} px wide; clamping to the "
            f"root, which is what the engine itself does when the "
            f"window cannot be honoured (src/sdltiles.cpp:671-675)",
            notes)
        width = root_w
        cols = width // cell_w
    if height > root_h:
        _note(
            f"the terminal grid implies a {height} px tall window but "
            f"the X root is only {root_h} px tall; clamping to the "
            f"root, which is what the engine itself does when the "
            f"window cannot be honoured (src/sdltiles.cpp:671-675)",
            notes)
        height = root_h
        rows = height // cell_h

    rect = Rect(
        width=width,
        height=height,
        x=(root_w - width) // 2,
        y=(root_h - height) // 2)
    return WindowGeometry(rect=rect, cols=cols, rows=rows, scale=scale)


def window_rect(*args: Any, **kwargs: Any) -> Rect:
    """Return just the game window's rectangle.

    The convenience wrapper for a caller that wants the rectangle and
    not the grid it was derived from.  Takes exactly
    :func:`resolve_window`'s arguments.
    """
    return resolve_window(*args, **kwargs).rect


def compute_sidebar_geometry(
    repo_root_dir: Optional[str] = None,
    sidebar_json: Optional[str] = None,
    options_json: Optional[str] = None,
    panel_options_json: Optional[str] = None,
    layout_id: Optional[str] = None,
    sidebar_widget_id: Optional[str] = None,
    sidebar_cells: Optional[int] = None,
    terminal_x: Optional[int] = None,
    terminal_y: Optional[int] = None,
    font_width: Optional[int] = None,
    font_height: Optional[int] = None,
    scaling_factor: Optional[int] = None,
    position: Optional[str] = None,
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
) -> SidebarGeometry:
    """Compute the full-height sidebar crop from configuration.

    :returns: a :class:`SidebarGeometry` carrying the crop and every input it
        was derived from. :raises GeometryError: on any malformed input, on a
        sidebar wider than the window, or if the crop would fall outside the
        root.
    """
    notes: List[str] = []
    root = repo_root(repo_root_dir)
    resolved_sidebar_json = sidebar_json or sidebar_json_path(root)
    resolved_options_json = options_json or options_json_path(root)
    resolved_panel_options = (panel_options_json or
                              panel_options_path(root))

    options = load_options(
        path=resolved_options_json, notes=notes, root=root)

    # Which layout, and on whose authority.  An explicit layout id or
    # widget id wins; otherwise the game's own persisted selection
    # does; otherwise the engine's constructor default.
    if sidebar_widget_id is not None:
        resolved_layout = sidebar_widget_id
        layout_source = "widget id override"
    elif layout_id is not None:
        resolved_layout = layout_id
        layout_source = "layout id override"
    else:
        resolved_layout, layout_source = read_current_layout_id(
            path=resolved_panel_options, notes=notes, root=root)

    widget_file = resolved_sidebar_json
    if sidebar_cells is None:
        # An explicitly named widget file is searched FIRST and the
        # rest of the tree still follows, because the engine loads the
        # whole tree; naming one file narrows the answer, it does not
        # hide the others.
        search: Optional[List[str]] = None
        if sidebar_json is not None:
            search = [resolved_sidebar_json]
            search.extend(
                path for path in _widget_files(root)
                if path != resolved_sidebar_json)
        cells, widget_used, widget_file = resolve_sidebar_widget(
            resolved_layout, notes=notes, root=root, paths=search)
    else:
        cells = _positive_int(sidebar_cells, "sidebar width in cells")
        widget_used = resolved_layout
        LOG.debug("sidebar width overridden to %d cells", cells)

    grid_x = _resolve_int(
        terminal_x, options, OPT_TERMINAL_X, ENV_TERMINAL_X,
        DEFAULT_TERMINAL_X, notes, TERMINAL_X_RANGE)
    grid_y = _resolve_int(
        terminal_y, options, OPT_TERMINAL_Y, ENV_TERMINAL_Y,
        DEFAULT_TERMINAL_Y, notes, TERMINAL_Y_RANGE)
    # font_w and font_h are the UNSCALED font cell; window_rect and
    # the sidebar width below both apply `scale` themselves, exactly as
    # src/sdltiles.cpp:595-596 does.
    font_w = _resolve_int(
        font_width, options, OPT_FONT_WIDTH, ENV_FONT_WIDTH,
        DEFAULT_FONT_WIDTH, notes, FONT_WIDTH_RANGE)
    font_h = _resolve_int(
        font_height, options, OPT_FONT_HEIGHT, ENV_FONT_HEIGHT,
        DEFAULT_FONT_HEIGHT, notes, FONT_HEIGHT_RANGE)
    scale = _resolve_scaling_factor(scaling_factor, options, notes)
    side = (position if position is not None else
            option_str(options, OPT_SIDEBAR_POSITION,
                       DEFAULT_SIDEBAR_POSITION, notes,
                       SIDEBAR_POSITIONS))
    if side not in SIDEBAR_POSITIONS:
        permitted = ", ".join(SIDEBAR_POSITIONS)
        raise GeometryError(
            f"sidebar position '{side}' is not one of {permitted}")

    root_w, root_h = resolve_screen_size(
        width=screen_width, height=screen_height, notes=notes)

    resolved = resolve_window(
        terminal_x=grid_x,
        terminal_y=grid_y,
        font_width=font_w,
        font_height=font_h,
        scaling_factor=scale,
        screen_width=root_w,
        screen_height=root_h,
        notes=notes)
    window = resolved.rect
    # The factor the engine ended up drawing at, which is what the
    # sidebar's physical width must be computed from.  It differs from
    # the requested one only when the engine reset a factor too large
    # for the display [src/sdltiles.cpp:6209-6232], and using the
    # requested one there would size the crop for a window that was
    # never created.
    scale = resolved.scale

    # A widget's "width" is in LOGICAL cells, the same unit
    # TERMINAL_WIDTH is in, so the physical width is that cell count
    # times the physical cell -- font times scaling factor
    # [src/sdltiles.cpp:595].
    sidebar_px = cells * font_w * scale
    if sidebar_px > window.width:
        raise GeometryError(
            f"the sidebar is {cells} cells ({sidebar_px} px) wide but "
            f"the render grid is only {window.width} px wide; the "
            f"crop would extend past the grid and the clock could "
            f"not be read from it")

    if side == "left":
        x = window.x
    else:
        x = window.right - sidebar_px

    rect = Rect(
        width=sidebar_px,
        height=window.height,
        x=x,
        y=window.y)

    root_rect = Rect(width=root_w, height=root_h, x=0, y=0)
    if not root_rect.contains(rect):
        raise GeometryError(
            f"the computed crop {rect.geometry} falls outside the "
            f"{root_w}x{root_h} X root; capture targets the root, so "
            f"this crop could not be taken")

    LOG.debug("sidebar crop %s (%s, %d cells, window %s)",
              rect.geometry, side, cells, window.geometry)

    return SidebarGeometry(
        rect=rect,
        window=window,
        screen_width=root_w,
        screen_height=root_h,
        sidebar_cells=cells,
        sidebar_widget_id=widget_used,
        layout_id=resolved_layout,
        layout_source=layout_source,
        terminal_x=grid_x,
        terminal_y=grid_y,
        terminal_cols=resolved.cols,
        terminal_rows=resolved.rows,
        font_width=font_w,
        font_height=font_h,
        scaling_factor=scale,
        position=side,
        sidebar_json=widget_file,
        options_json=resolved_options_json,
        panel_options_json=resolved_panel_options,
        notes=tuple(notes))


def sidebar_crop_geometry(**overrides: Any) -> str:
    """Return just the ImageMagick ``WxH+X+Y`` crop string."""
    return compute_sidebar_geometry(**overrides).geometry


def narrow_to_rows(
    geometry: SidebarGeometry,
    first_row: Optional[int] = None,
    row_count: Optional[int] = None,
) -> Rect:
    """Optionally trim the sidebar column to a band of text rows.

    OPT-IN ONLY, AND NOT THE PRIMARY PATH.  With either bound left as
    ``None`` -- which is the default -- this returns the full-height
    column unchanged, because the clock's row cannot be derived from
    configuration: it is drawn by the ``time_desc_label`` widget
    [data/json/ui/time.json:2-8] at whatever position the enclosing
    ``custom_sidebar`` ``widgets`` array puts it, so ``ocr_clock.py``
    finds it by regex inside the OCR output of the whole column.

    :param geometry: the resolved full sidebar geometry from
        :func:`compute_sidebar_geometry`, whose ``rect`` is returned unchanged
        unless both bounds are given and whose ``font_height`` and
        ``scaling_factor`` give the pixel height of one text row.
    :param first_row: zero-based text row the band starts at.
    :param row_count: number of text rows the band covers.
    :raises GeometryError: when the bounds are not positive integers or fall
        outside the column.
    """
    if first_row is None or row_count is None:
        LOG.debug(
            "narrow_to_rows: no complete band given, returning the "
            "full sidebar column %s", geometry.rect.geometry)
        return geometry.rect

    row_px = geometry.font_height * geometry.scaling_factor
    if isinstance(first_row, bool) or not isinstance(first_row, int):
        raise GeometryError(
            f"first_row must be an int, got {first_row!r}")
    if first_row < 0:
        raise GeometryError(
            f"first_row must be non-negative, got {first_row}")
    rows = _positive_int(row_count, "row_count")

    top = geometry.rect.y + (first_row * row_px)
    height = rows * row_px
    if top + height > geometry.rect.bottom:
        raise GeometryError(
            f"rows {first_row}-{first_row + rows - 1} at {row_px} px "
            f"per row end at y={top + height}, past the bottom of the "
            f"{geometry.rect.height} px sidebar column "
            f"(y={geometry.rect.bottom})")

    band = Rect(
        width=geometry.rect.width,
        height=height,
        x=geometry.rect.x,
        y=top)
    LOG.warning(
        "narrowing the sidebar crop from the full column %s to rows "
        "%d-%d (%s); the clock row is NOT fixed by configuration, so "
        "the caller must have established this band independently and "
        "must still locate the clock by regex",
        geometry.rect.geometry, first_row, first_row + rows - 1,
        band.geometry)
    return band


# ---------------------------------------------------------------------
# Command line
#
# STDOUT CARRIES EXACTLY THE GEOMETRY STRING AND NOTHING ELSE, so that
#
#     RECT="$("${PLAYTHROUGH_PYTHON}" -B \
#         playthrough/tooling/sidebar_geometry.py)"
#     convert "${FRAME}" -crop "${RECT}" +repage ... png:-
#
# is safe with no parsing, no trimming and no decoration to strip.
# Every warning, note, derivation and error message goes to stderr,
# which is what makes a substituted default visible to a human without
# corrupting the value a script just captured.
# ---------------------------------------------------------------------

_EPILOG = """\
examples (run from the repository root; this file is tracked mode 644
and is not on PATH, so it is always invoked through the pinned
interpreter -- source playthrough/tooling/env.sh first, which exports
it as PLAYTHROUGH_PYTHON):
  SG='playthrough/tooling/sidebar_geometry.py'

  # the live configuration, for capture.sh
  "$PLAYTHROUGH_PYTHON" -B "$SG"

  # show how the rectangle was derived (stderr) as well
  "$PLAYTHROUGH_PYTHON" -B "$SG" --explain

  # a different layout, without touching any file
  "$PLAYTHROUGH_PYTHON" -B "$SG" --layout-id custom_sidebar

  # a width no shipped preset declares
  "$PLAYTHROUGH_PYTHON" -B "$SG" --sidebar-cells 40

  # a left-hand sidebar
  "$PLAYTHROUGH_PYTHON" -B "$SG" --position left

Exit status: 0 on success, 1 when the crop cannot be computed
honestly, 2 on a command line error.
"""


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line parser.

    Exposed as a function so the flag set can be inspected and tested
    without running the tool.
    """
    parser = argparse.ArgumentParser(
        prog="sidebar_geometry.py",
        description=(
            "Compute the Cataclysm-DDA sidebar OCR crop rectangle "
            "from configuration and print it as an ImageMagick "
            "WxH+X+Y geometry on standard output."),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    paths = parser.add_argument_group("input locations")
    paths.add_argument(
        "--repo-root", metavar="DIR",
        help="repository root; defaults to $PLAYTHROUGH_REPO_ROOT or "
             "two directories above this script")
    paths.add_argument(
        "--sidebar-json", metavar="FILE",
        help="widget definition looked at first; the whole "
             "data/json/ui tree is searched for the resolved layout, "
             "as the engine does")
    paths.add_argument(
        "--options-json", metavar="FILE",
        help="game-written options file; defaults to "
             "$PLAYTHROUGH_OPTIONS_JSON or "
             "playthrough/userdir/config/options.json")
    paths.add_argument(
        "--panel-options-json", metavar="FILE",
        help="game-written panel options file, which names the active "
             "sidebar layout; defaults to $" + ENV_PANEL_OPTIONS +
             " or playthrough/userdir/config/panel_options.json")
    paths.add_argument(
        "--layout-id", metavar="ID",
        help="sidebar layout to use instead of the one the game has "
             "persisted (engine default: " + DEFAULT_LAYOUT_ID + ")")
    paths.add_argument(
        "--widget-id", metavar="ID",
        help="synonym for --layout-id, kept because a sidebar layout "
             "IS a widget id [src/panels.cpp:398-408]; e.g. " +
             DEFAULT_SIDEBAR_WIDGET_ID)

    over = parser.add_argument_group(
        "overrides",
        "Each of these replaces one term of the computation. They "
        "exist so the arithmetic can be exercised against "
        "configurations other than the live one; omit them all to "
        "read the real repository JSON and the real options file.")
    over.add_argument(
        "--sidebar-cells", type=int, metavar="N",
        help="sidebar width in terminal cells")
    over.add_argument(
        "--terminal-x", type=int, metavar="N",
        help="terminal width in cells (option TERMINAL_X)")
    over.add_argument(
        "--terminal-y", type=int, metavar="N",
        help="terminal height in cells (option TERMINAL_Y)")
    over.add_argument(
        "--font-width", type=int, metavar="PX",
        help="font cell width in pixels (option FONT_WIDTH)")
    over.add_argument(
        "--font-height", type=int, metavar="PX",
        help="font cell height in pixels (option FONT_HEIGHT)")
    over.add_argument(
        "--scaling-factor", type=int, choices=list(SCALING_FACTORS),
        help="display scaling factor (option SCALING_FACTOR); the "
             "engine declares exactly these values "
             "(src/options.cpp:2818-2824)")
    over.add_argument(
        "--position", choices=list(SIDEBAR_POSITIONS),
        help="which side the sidebar is drawn on (option "
             "SIDEBAR_POSITION)")
    over.add_argument(
        "--screen-width", type=int, metavar="PX",
        help="X root width; defaults to $" + ENV_SCREEN_WIDTH)
    over.add_argument(
        "--screen-height", type=int, metavar="PX",
        help="X root height; defaults to $" + ENV_SCREEN_HEIGHT)

    band = parser.add_argument_group(
        "optional narrowing",
        "Off by default. The clock's row is not fixed by "
        "configuration, so the full-height column is the correct "
        "answer and ocr_clock.py locates the clock row by regex. Both "
        "bounds must be given together.")
    band.add_argument(
        "--first-row", type=int, metavar="ROW",
        help="zero-based text row the band starts at")
    band.add_argument(
        "--row-count", type=int, metavar="N",
        help="number of text rows the band covers")

    report = parser.add_argument_group("reporting (all on stderr)")
    report.add_argument(
        "--explain", action="store_true",
        help="write the full derivation to stderr as well")
    report.add_argument(
        "-v", "--verbose", action="store_true",
        help="also report the resolution steps at DEBUG level")
    return parser


def _configure_cli_logging(verbose: bool) -> None:
    """Route this module's log records to the current stderr."""
    for existing in list(LOG.handlers):
        LOG.removeHandler(existing)
        existing.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("sidebar_geometry: %(levelname)s: "
                          "%(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG if verbose else logging.WARNING)
    LOG.propagate = False


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print the sidebar crop geometry on standard output.

    :param argv: argument list excluding the program name; defaults to
        :data:`sys.argv` ``[1:]``.
    :returns: 0 on success, 1 when the crop cannot be computed
        honestly.  Command line errors exit 2 through argparse.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    _configure_cli_logging(args.verbose)

    if (args.first_row is None) != (args.row_count is None):
        parser.error(
            "--first-row and --row-count must be given together; "
            "either narrow the crop deliberately or leave it as the "
            "full sidebar column")

    if args.layout_id is not None and args.widget_id is not None:
        parser.error(
            "--layout-id and --widget-id name the same thing; give "
            "one of them, not both")

    try:
        geometry = compute_sidebar_geometry(
            repo_root_dir=args.repo_root,
            sidebar_json=args.sidebar_json,
            options_json=args.options_json,
            panel_options_json=args.panel_options_json,
            layout_id=args.layout_id,
            sidebar_widget_id=args.widget_id,
            sidebar_cells=args.sidebar_cells,
            terminal_x=args.terminal_x,
            terminal_y=args.terminal_y,
            font_width=args.font_width,
            font_height=args.font_height,
            scaling_factor=args.scaling_factor,
            position=args.position,
            screen_width=args.screen_width,
            screen_height=args.screen_height)
        rect = narrow_to_rows(
            geometry,
            first_row=args.first_row,
            row_count=args.row_count)
    except GeometryError as err:
        LOG.error("%s", err)
        return 1

    if args.explain:
        sys.stderr.write(geometry.describe() + "\n")

    sys.stdout.write(rect.geometry + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
