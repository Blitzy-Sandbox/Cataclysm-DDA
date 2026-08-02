#!/usr/bin/env python3
"""Compute the sidebar OCR crop rectangle from configuration.

This module is the resolution of the ``<sidebar region>`` placeholder
left open by the playthrough capture request.  It is imported by
``playthrough/tooling/ocr_clock.py`` and invoked as a script by
``playthrough/tooling/capture.sh``; both need one and the same
ImageMagick geometry string of the form ``WxH+X+Y``, and they get it
from here so that the two cannot disagree.

THE FORMULA
    width  = sidebar_width_cells * FONT_WIDTH   * SCALING_FACTOR
    height = TERMINAL_Y          * FONT_HEIGHT  * SCALING_FACTOR
    x      = window.x + window.width - width  (SIDEBAR_POSITION right)
    x      = window.x                         (SIDEBAR_POSITION left)
    y      = window.y

where the game window itself is derived exactly as the engine derives
it -- ``WindowWidth = TERMINAL_WIDTH * fontwidth * scaling_factor`` and
``WindowHeight = TERMINAL_HEIGHT * fontheight * scaling_factor``
[src/sdltiles.cpp:595-596] -- and is then centred inside the X root,
which is what produces the four-pixel letterbox: the window measures
1920x1072 at ``+0+4`` inside a 1920x1080 root, so ``y`` is 4 rather
than 0.  That 4 is COMPUTED as ``(1080 - 1072) // 2``; it is not a
constant anywhere in this file.

On the configuration this pipeline runs under the formula evaluates to
``288x1072+1632+4``.  That string appears in this docstring as an
expected result and nowhere on any return path.

WHY THIS IS COMPUTED AND NOT A LITERAL
Measured in this checkout, not estimated: nine files match
``data/json/ui/sidebar*.json``, and across the whole ``data/json/ui``
tree -- including the ``zenfs/``, ``structured/`` and ``spacebar/``
bundles -- twelve widgets declare ``"style": "sidebar"`` at eight
distinct widths: 32, 36, 43, 44, 48, 58, 62 and 66 cells.  The default
``custom_sidebar`` is 36 [data/json/ui/sidebar.json:7].  A hard-coded
rectangle would therefore crop the wrong column the moment the layout
changed -- and it would do so SILENTLY.  Nothing crashes: the OCR
simply stops matching, every ``ingame_clock`` goes null, every
duration collapses to the 0.25 s floor, and the finished movie looks
plausible while meaning nothing.  Preventing that specific silent
failure is the entire reason this module exists, which is why every
fallback below is announced on stderr through ``logging`` and why a
malformed input raises :class:`GeometryError` instead of being papered
over with a default.

WHAT THIS RETURNS -- THE WHOLE COLUMN, NEVER A BAND
The clock is drawn by the ``time_desc_label`` widget bound to
``time_text`` [data/json/ui/time.json:2-8], and its row depends on the
order of ``custom_sidebar``'s ``widgets`` array, so its ``y`` cannot be
known from configuration alone.  This module therefore returns the
full-height sidebar strip and ``ocr_clock.py`` locates the clock row by
regex inside the OCR output.  :func:`narrow_to_rows` can trim the strip
for performance, but it is opt-in, it returns the full column unless
BOTH bounds are supplied, and it is never the only path.

READ-ONLY BY CONSTRUCTION
Nothing here writes anywhere.  ``data/json/ui/sidebar.json`` and the
game-written ``options.json`` are opened for reading only; no widget is
modified, the in-game sidebar manager is never invoked, no subprocess
is started, and no network call of any kind is made.

USAGE
    $ python3 playthrough/tooling/sidebar_geometry.py
    288x1072+1632+4

    >>> import sidebar_geometry
    >>> sidebar_geometry.sidebar_crop_geometry()
    '288x1072+1632+4'

Standard output carries exactly the geometry string and nothing else,
so ``RECT="$(python3 playthrough/tooling/sidebar_geometry.py)"`` is
safe.  Every diagnostic, warning and fallback notice goes to stderr.
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
# Note that TERMINAL_X and TERMINAL_Y default to the compiled-in 80x24
# rather than to the 240x67 this pipeline runs at.  That is deliberate
# and correct: 80x24 is what the engine writes on a first launch before
# it has derived screen-based values, and reporting the real default is
# what makes the accompanying warning worth reading.  Anything else
# would be inventing a default the engine does not have.
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
# It multiplies both window axes at src/sdltiles.cpp:595-596, so it
# multiplies the crop too.
DEFAULT_SCALING_FACTOR = 1
SCALING_FACTORS = (1, 2, 4)

# src/options.cpp:2132-2136 SIDEBAR_POSITION { left, right }, "right".
# Both values are honoured.  Supporting only the default would make
# this module a constant wearing a function's clothes.
DEFAULT_SIDEBAR_POSITION = "right"
SIDEBAR_POSITIONS = ("left", "right")

# data/json/ui/sidebar.json:7 custom_sidebar "width": 36.  Used only if
# that widget cannot be read AND a caller passes the value explicitly;
# the JSON is the source of truth and a failure to read it raises.
DEFAULT_SIDEBAR_CELLS = 36

# The headless contract from playthrough/tooling/env.sh:375-378,
# `Xvfb :99 -screen 0 1920x1080x24`.  Capture targets the X ROOT, not
# the game window, so the root size is what the crop is aligned in.
DEFAULT_SCREEN_WIDTH = 1920
DEFAULT_SCREEN_HEIGHT = 1080

# The widget this module reads, by id first and by style second.
# data/json/ui/sidebar.json:3 "id", :5 "style".
DEFAULT_SIDEBAR_WIDGET_ID = "custom_sidebar"
SIDEBAR_WIDGET_STYLE = "sidebar"

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
# when the game-written options file does not carry the key -- which is
# the real state of a fresh userdir, since the engine writes
# options.json on its first launch [src/path_info.cpp:167].  Preferring
# the pipeline's declared contract (env.sh:386-389) over the engine's
# compiled-in first-launch default in that window is what makes the
# crop match the frames actually being captured: those defaults are
# 80x24 cells, a 640x384 window, whereas capture runs at 240x67 cells
# in a 1920x1072 window.  Every such substitution is announced.
#
# There is deliberately NO environment tier for the sidebar width.
# env.sh:390 does export PLAYTHROUGH_SIDEBAR_CELLS, and honouring it
# would let a constant back in through the side door; the width is read
# from the game's own widget definition, which always ships, or the
# computation fails.  An explicit argument remains available for
# exercising other presets.
ENV_REPO_ROOT = "PLAYTHROUGH_REPO_ROOT"
ENV_OPTIONS_JSON = "PLAYTHROUGH_OPTIONS_JSON"
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
# ./playthrough/userdir/ (env.sh:300, 310-311).
SIDEBAR_JSON_PARTS = ("data", "json", "ui", "sidebar.json")
OPTIONS_JSON_PARTS = ("playthrough", "userdir", "config", "options.json")

# Markers proving a directory really is a Cataclysm-DDA checkout.  The
# same pair env.sh:147-152 asserts, for the same reason: a wrong root
# would otherwise surface much later as an unreadable clock.
ROOT_MARKER_DIR_PARTS = ("data", "json", "ui")
ROOT_MARKER_FILE_PARTS = ("src", "path_info.cpp")


class GeometryError(Exception):
    """The crop rectangle could not be computed honestly.

    Raised rather than returning a plausible-looking rectangle.  A
    wrong crop does not crash anything downstream -- it yields null
    clock readings, floor-clamped durations and a movie that looks
    fine and means nothing -- so every condition under which the
    answer would be a guess is turned into a hard, loud failure here.
    """


def _note(message: str, notes: Optional[List[str]] = None) -> None:
    """Announce a fallback and record it.

    Emitted at WARNING so it is visible with no logging configuration
    at all: Python's ``logging.lastResort`` handler writes WARNING and
    above to stderr.  Standard output is reserved for the geometry
    string, so a caller capturing stdout still sees this.
    """
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
class SidebarGeometry:
    """The computed crop plus every input it was computed from.

    Carrying the inputs alongside the answer is what lets a caller --
    or a reviewer -- confirm the rectangle was derived rather than
    assumed.  :attr:`notes` lists every substitution that had to be
    made, in the order it was made; an empty tuple means every value
    came from the game's own configuration files.
    """

    rect: Rect
    window: Rect
    screen_width: int
    screen_height: int
    sidebar_cells: int
    sidebar_widget_id: str
    terminal_x: int
    terminal_y: int
    font_width: int
    font_height: int
    scaling_factor: int
    position: str
    sidebar_json: str
    options_json: str
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
            f"  sidebar json          {self.sidebar_json}",
            f"  sidebar widget        {self.sidebar_widget_id}",
            f"  options json          {self.options_json}",
            f"  X root                {self.screen_width}"
            f"x{self.screen_height}",
            f"  terminal grid         {self.terminal_x}"
            f"x{self.terminal_y} cells",
            f"  font cell             {self.font_width}"
            f"x{self.font_height} px",
            f"  scaling factor        {self.scaling_factor}",
            f"  effective cell        {cell_w}x{cell_h} px",
            f"  game window           {self.window.geometry}",
            f"  sidebar position      {self.position}",
            f"  sidebar width         {self.sidebar_cells} cells"
            f" * {cell_w} px = {self.rect.width} px",
            f"  sidebar height        {self.terminal_y} cells"
            f" * {cell_h} px = {self.rect.height} px",
            f"  letterbox y           ({self.screen_height}"
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

    Resolution order, first match wins:

    1. ``explicit``, when a caller passes one;
    2. ``$PLAYTHROUGH_REPO_ROOT``, exported by
       ``playthrough/tooling/env.sh:294``, so that every stage of the
       pipeline agrees on the root;
    3. two directories above this file, which is the idiom
       ``tools/json_tools/util.py:13-16`` uses.

    :raises GeometryError: when the resolved directory is not a
        Cataclysm-DDA checkout.  This is deliberately fatal.  The
        module's whole purpose is to avoid a plausible-but-wrong
        rectangle, and a wrong root produces exactly that.
    """
    candidates = []
    if explicit:
        candidates.append(("explicit argument", explicit))
    env_root = os.environ.get(ENV_REPO_ROOT)
    if env_root:
        candidates.append((f"${ENV_REPO_ROOT}", env_root))
    here = os.path.abspath(os.path.dirname(__file__))
    candidates.append(
        ("this file's location", _join(here, ("..", ".."))))

    tried = []
    for origin, candidate in candidates:
        resolved = os.path.abspath(os.path.normpath(candidate))
        if _looks_like_checkout(resolved):
            LOG.debug("repository root from %s: %s", origin, resolved)
            return resolved
        tried.append(f"{origin} -> {resolved}")

    marker_dir = os.path.join(*ROOT_MARKER_DIR_PARTS)
    marker_file = os.path.join(*ROOT_MARKER_FILE_PARTS)
    attempts = "; ".join(tried)
    raise GeometryError(
        f"cannot locate a Cataclysm-DDA checkout (no {marker_dir} "
        f"directory and no {marker_file} file); tried: {attempts}")


def sidebar_json_path(root: Optional[str] = None) -> str:
    """Absolute path of ``data/json/ui/sidebar.json``.

    Read-only input.  This file belongs to the game's content tree and
    is never written by this pipeline.
    """
    return _join(repo_root(root), SIDEBAR_JSON_PARTS)


def options_json_path(root: Optional[str] = None) -> str:
    """Absolute path of the game-written ``options.json``.

    ``$PLAYTHROUGH_OPTIONS_JSON`` wins when set
    [playthrough/tooling/env.sh:311], so the value is defined once for
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


def read_sidebar_cells(
    path: Optional[str] = None,
    widget_id: str = DEFAULT_SIDEBAR_WIDGET_ID,
    notes: Optional[List[str]] = None,
    root: Optional[str] = None,
) -> Tuple[int, str]:
    """Read the sidebar width in terminal cells from the game's JSON.

    ``data/json/ui/sidebar.json`` is a JSON array of widget objects.
    The wanted one is located by ``"id"`` first
    [data/json/ui/sidebar.json:3] and, failing that, by
    ``"style": "sidebar"`` [data/json/ui/sidebar.json:5], which is the
    more robust match because it identifies the role rather than the
    name.  The width itself is at
    [data/json/ui/sidebar.json:7] -- ``"width": 36``.

    The JSON is parsed with :mod:`json`, never pattern-matched: a
    regex over this file would match ``"width"`` keys belonging to
    nested layout widgets, of which the presets contain many.

    :returns: ``(cells, widget_id_used)``.  The second element names
        the widget the value actually came from, which differs from
        ``widget_id`` whenever the style fallback fired.
    :raises GeometryError: when the file is unreadable, is not an
        array, contains no sidebar widget, or carries a width that is
        not a positive integer.  No default is substituted here -- the
        file ships with the game and is always present, so a failure
        to read it means the root is wrong or the content tree has
        been altered, and both must be loud.
    """
    resolved = path or sidebar_json_path(root)
    data = _load_json(resolved, "sidebar widget definition")
    if not isinstance(data, list):
        raise GeometryError(
            f"{resolved} must contain a JSON array of widgets, got "
            f"{type(data).__name__}")

    widgets = [item for item in data if isinstance(item, dict)]
    by_id = [w for w in widgets if w.get("id") == widget_id]
    chosen = None
    if by_id:
        chosen = by_id[0]
    else:
        by_style = [
            w for w in widgets
            if w.get("style") == SIDEBAR_WIDGET_STYLE and "width" in w
        ]
        if by_style:
            chosen = by_style[0]
            _note(
                f"{resolved} has no widget with id '{widget_id}'; used "
                f"the first widget whose style is "
                f"'{SIDEBAR_WIDGET_STYLE}' instead, id "
                f"'{chosen.get('id')}'",
                notes)

    if chosen is None:
        raise GeometryError(
            f"{resolved} contains no widget with id '{widget_id}' and "
            f"none with style '{SIDEBAR_WIDGET_STYLE}'; the sidebar "
            f"width cannot be read and will not be guessed")

    if "width" not in chosen:
        raise GeometryError(
            f"widget '{chosen.get('id')}' in {resolved} declares no "
            f"'width'; the sidebar width cannot be read and will not "
            f"be guessed")

    cells = chosen["width"]
    if isinstance(cells, bool) or not isinstance(cells, int):
        raise GeometryError(
            f"widget '{chosen.get('id')}' in {resolved} declares "
            f"width {cells!r}, which is not an integer")
    if cells <= 0:
        raise GeometryError(
            f"widget '{chosen.get('id')}' in {resolved} declares "
            f"width {cells}, which is not a positive cell count")

    used_id = chosen.get("id")
    if not isinstance(used_id, str):
        used_id = widget_id
    LOG.debug("sidebar width %d cells from %s (%s)",
              cells, resolved, used_id)
    return cells, used_id


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
    ``joOptions.get_string( "value" )``
    [src/options.cpp:4080-4100].  Verified against a real game-written
    file: ``TERMINAL_X`` reads back as ``"240"``, not ``240``.

    Two further shapes are accepted so that a hand-seeded or
    hand-inspected file still works: a flat ``{"NAME": value}`` mapping
    and a nested ``{"NAME": {"value": value}}`` mapping.  Every value
    is normalised to :class:`str`, matching the engine's own contract.

    An ABSENT file yields an empty map plus a visible note: a fresh
    userdir has no ``options.json`` until the game has been launched
    once, so this is an ordinary state and the caller then falls back
    to documented defaults.  A file that exists but cannot be parsed
    raises instead.

    :raises GeometryError: when the file exists but is unreadable,
        unparseable, or of an unrecognised shape.
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

    An absent key is an expected condition and yields ``default`` with
    a WARNING naming both the key and the value substituted.  A key
    that is present but not an integer raises: the engine only ever
    writes integers for these options, so anything else means the file
    is not what this module believes it to be.

    ``valid_range`` is the engine's own declared minimum and maximum.
    A value outside it is reported at WARNING and then used as read --
    the file is authoritative about what the game is actually running
    with, and clamping it here would hide a real misconfiguration.

    :raises GeometryError: when the value is present but not a
        positive integer.
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

    :raises GeometryError: when the value is present but outside
        ``allowed``.  For ``SIDEBAR_POSITION`` that matters concretely:
        an unrecognised value means the side the sidebar is drawn on is
        unknown, and picking one would be a coin toss dressed as a
        computation.
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

    Capture targets the X ROOT rather than the game window -- the root
    is 1920x1080 while the window is 1920x1072, so photographing the
    root yields a true-resolution PNG with a four-pixel letterbox and
    needs no rescaling, and rescaling would soften exactly the 8x16
    glyphs the clock OCR depends on
    [playthrough/tooling/env.sh:351-360].

    Resolution order per axis: an explicit argument, then the
    ``PLAYTHROUGH_SCREEN_WIDTH`` / ``PLAYTHROUGH_SCREEN_HEIGHT``
    exports [playthrough/tooling/env.sh:375-376], then the documented
    default with a visible note.  Taking it from the environment rather
    than baking it into the arithmetic is what keeps the
    right-alignment correct if the display ever changes.

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
    """Resolve one integer term through the three-tier order.

    Explicit argument, then the game-written options file, then the
    pipeline's ``env.sh`` contract, then the engine's documented
    default.  Every tier below the first two is announced at WARNING,
    so a reader always knows which of them supplied the number.
    """
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

def window_rect(
    terminal_x: int,
    terminal_y: int,
    font_width: int,
    font_height: int,
    scaling_factor: int = DEFAULT_SCALING_FACTOR,
    screen_width: int = DEFAULT_SCREEN_WIDTH,
    screen_height: int = DEFAULT_SCREEN_HEIGHT,
    notes: Optional[List[str]] = None,
) -> Rect:
    """Derive the game window's rectangle inside the X root.

    The extent is the engine's own arithmetic --
    ``WindowWidth = TERMINAL_WIDTH * fontwidth * scaling_factor`` and
    ``WindowHeight = TERMINAL_HEIGHT * fontheight * scaling_factor``
    [src/sdltiles.cpp:595-596].  The window is then centred in the
    root, which is where the letterbox comes from: on this pipeline's
    configuration 67 rows of 16 pixels is 1072, inside a 1080-pixel
    root, so ``y`` computes to ``(1080 - 1072) // 2 == 4``.

    A window larger than the root is clamped to the root and reported,
    because the engine does the same thing in that situation -- it
    calls ``GetWindowSize`` and recomputes ``TERMINAL_WIDTH`` and
    ``TERMINAL_HEIGHT`` from the actual window
    [src/sdltiles.cpp:672-676] -- so the root is the honest bound.

    :raises GeometryError: when any input is not a positive integer.
    """
    cell_w = (_positive_int(font_width, "font width") *
              _positive_int(scaling_factor, "scaling factor"))
    cell_h = (_positive_int(font_height, "font height") *
              _positive_int(scaling_factor, "scaling factor"))
    width = _positive_int(terminal_x, "terminal width") * cell_w
    height = _positive_int(terminal_y, "terminal height") * cell_h
    root_w = _positive_int(screen_width, "screen width")
    root_h = _positive_int(screen_height, "screen height")

    if width > root_w:
        _note(
            f"the terminal grid implies a {width} px wide window but "
            f"the X root is only {root_w} px wide; clamping to the "
            f"root, which is what the engine itself does when the "
            f"window cannot be honoured (src/sdltiles.cpp:672-676)",
            notes)
        width = root_w
    if height > root_h:
        _note(
            f"the terminal grid implies a {height} px tall window but "
            f"the X root is only {root_h} px tall; clamping to the "
            f"root, which is what the engine itself does when the "
            f"window cannot be honoured (src/sdltiles.cpp:672-676)",
            notes)
        height = root_h

    return Rect(
        width=width,
        height=height,
        x=(root_w - width) // 2,
        y=(root_h - height) // 2)


def compute_sidebar_geometry(
    repo_root_dir: Optional[str] = None,
    sidebar_json: Optional[str] = None,
    options_json: Optional[str] = None,
    sidebar_widget_id: str = DEFAULT_SIDEBAR_WIDGET_ID,
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

    This is the module's primary entry point.  Every parameter is an
    optional override that exists so the computation can be exercised
    against configurations other than the live one; supplying none of
    them reads the real repository JSON and the real game-written
    options file, which is the path the pipeline takes.

    Resolution order for each term is: the explicit override, then the
    game-written ``options.json``, then the ``env.sh`` contract, then
    the engine's documented default -- with every tier below the first
    two announced at WARNING and recorded in
    :attr:`SidebarGeometry.notes`.  The sidebar width in cells is the
    one exception -- it is read from ``data/json/ui/sidebar.json``,
    which ships with the game and is therefore always present, and a
    failure to read it raises rather than defaulting.  Letting an
    environment variable or a constant stand in for that value would
    reintroduce the hard-coded rectangle this module exists to
    eliminate.

    :returns: a :class:`SidebarGeometry` carrying the crop and every
        input it was derived from.
    :raises GeometryError: on any malformed input, on a sidebar wider
        than the window, or if the crop would fall outside the root.
    """
    notes: List[str] = []
    root = repo_root(repo_root_dir)
    resolved_sidebar_json = sidebar_json or sidebar_json_path(root)
    resolved_options_json = options_json or options_json_path(root)

    options = load_options(
        path=resolved_options_json, notes=notes, root=root)

    if sidebar_cells is None:
        cells, widget_used = read_sidebar_cells(
            path=resolved_sidebar_json,
            widget_id=sidebar_widget_id,
            notes=notes,
            root=root)
    else:
        cells = _positive_int(sidebar_cells, "sidebar width in cells")
        widget_used = sidebar_widget_id
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
    scale = _resolve_int(
        scaling_factor, options, OPT_SCALING_FACTOR, None,
        DEFAULT_SCALING_FACTOR, notes,
        (min(SCALING_FACTORS), max(SCALING_FACTORS)))
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

    window = window_rect(
        terminal_x=grid_x,
        terminal_y=grid_y,
        font_width=font_w,
        font_height=font_h,
        scaling_factor=scale,
        screen_width=root_w,
        screen_height=root_h,
        notes=notes)

    sidebar_px = cells * font_w * scale
    if sidebar_px > window.width:
        raise GeometryError(
            f"the sidebar is {cells} cells ({sidebar_px} px) wide but "
            f"the game window is only {window.width} px wide; the "
            f"crop would extend past the window and the clock could "
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
        terminal_x=grid_x,
        terminal_y=grid_y,
        font_width=font_w,
        font_height=font_h,
        scaling_factor=scale,
        position=side,
        sidebar_json=resolved_sidebar_json,
        options_json=resolved_options_json,
        notes=tuple(notes))


def sidebar_crop_geometry(**overrides: Any) -> str:
    """Return just the ImageMagick ``WxH+X+Y`` crop string.

    The convenience wrapper ``ocr_clock.py`` and ``capture.sh`` use.
    Accepts exactly the keyword overrides of
    :func:`compute_sidebar_geometry` and discards everything except the
    geometry, so a consumer that only needs the rectangle does not have
    to reach through the record to reach it.

        >>> sidebar_crop_geometry(sidebar_cells=36, terminal_y=67,
        ...                       font_width=8, font_height=16,
        ...                       position="right", screen_width=1920,
        ...                       screen_height=1080)
        '288x1072+1632+4'
    """
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

    Supplying both bounds trades that robustness for OCR speed and is
    only ever correct when the caller has independently established
    which rows the clock occupies for the layout in play.  The
    narrowing is announced at WARNING for exactly that reason.

    :param first_row: zero-based text row the band starts at.
    :param row_count: number of text rows the band covers.
    :raises GeometryError: when the bounds are not positive integers
        or fall outside the column.
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
#     RECT="$(python3 playthrough/tooling/sidebar_geometry.py)"
#     convert "${FRAME}" -crop "${RECT}" +repage ... png:-
#
# is safe with no parsing, no trimming and no decoration to strip.
# Every warning, note, derivation and error message goes to stderr,
# which is what makes a substituted default visible to a human without
# corrupting the value a script just captured.
# ---------------------------------------------------------------------

_EPILOG = """\
examples:
  # the live configuration, for capture.sh
  sidebar_geometry.py

  # show how the rectangle was derived (stderr) as well
  sidebar_geometry.py --explain

  # a different preset, without touching any file
  sidebar_geometry.py --sidebar-cells 44

  # a left-hand sidebar
  sidebar_geometry.py --position left

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
        help="widget definition to read the sidebar width from; "
             "defaults to data/json/ui/sidebar.json")
    paths.add_argument(
        "--options-json", metavar="FILE",
        help="game-written options file; defaults to "
             "$PLAYTHROUGH_OPTIONS_JSON or "
             "playthrough/userdir/config/options.json")
    paths.add_argument(
        "--widget-id", metavar="ID",
        default=DEFAULT_SIDEBAR_WIDGET_ID,
        help="sidebar widget id to read (default: %(default)s); the "
             "first widget with style '" + SIDEBAR_WIDGET_STYLE +
             "' is used if that id is absent")

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
        "--scaling-factor", type=int, metavar="N",
        help="display scaling factor (option SCALING_FACTOR)")
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
    """Route this module's log records to the current stderr.

    Deliberately NOT ``logging.basicConfig``.  That call is a silent
    no-op once the root logger already has a handler, so a second
    invocation inside one process -- or an embedding application that
    configured logging first -- would send this module's warnings
    somewhere the operator is not looking.  Given that the warnings
    are the mechanism by which a substituted default stays visible,
    losing them would defeat the module's purpose.

    A handler owned by this module and rebuilt on every call always
    lands on the ``sys.stderr`` in force right now, and
    ``propagate = False`` keeps it from being echoed a second time by
    a root handler an application installed.  Library callers that do
    not run :func:`main` are untouched: with no handler anywhere,
    ``logging.lastResort`` still writes WARNING and above to stderr.
    """
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

    try:
        geometry = compute_sidebar_geometry(
            repo_root_dir=args.repo_root,
            sidebar_json=args.sidebar_json,
            options_json=args.options_json,
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

    # The one and only thing written to stdout.
    sys.stdout.write(rect.geometry + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
