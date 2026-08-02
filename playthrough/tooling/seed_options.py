#!/usr/bin/env python3
"""Patch the game-written ``options.json`` in place, key by key.

This module seeds the handful of Cataclysm-DDA option values the
playthrough capture pipeline depends on, into the configuration file
**the engine itself wrote**:

    playthrough/userdir/config/options.json

It is the only configuration this feature reads or writes.  Nothing
under ``src/``, ``data/`` or ``gfx/`` is touched, no repository
configuration file (``.flake8``, ``pyproject.toml``, ``.gitignore``,
``.gitattributes``) is modified, and no YAML or dotenv is introduced.

WHERE THE TARGET LIVES, AND WHY
    ``--userdir <path>`` routes to ``PATH_INFO::init_user_dir``
    [src/main.cpp:415-426], which normalises but deliberately does NOT
    absolutise the value [src/path_info.cpp:105], so
    ``--userdir ./playthrough/userdir/`` resolves against the process
    working directory -- the repository root.  From there
    ``config_dir_value = user_dir_value + "config/"``
    [src/path_info.cpp:164] and ``options_value = config_dir_value +
    "options.json"`` [src/path_info.cpp:167].

    That derivation is guarded in the engine by
    ``#if defined(USE_XDG_DIR) ... #else config_dir_value =
    user_dir_value + "config/" ... #endif``, so building with
    ``USE_XDG_DIR=1`` or ``USE_HOME_DIR=1`` would move ``config/`` out
    of the userdir entirely and this module's target would vanish --
    along with the committed ``keybindings.json`` that proves no debug
    action was ever bound.  ``launch_game.sh`` owns that prohibition;
    this module only verifies the file is where it expects and fails
    loudly when it is not.

IN PLACE, KEY BY KEY -- NEVER WHOLESALE
    The engine writes 175 option entries into that file.  Only the
    seven named below are touched; every other entry, and every
    member of every entry including the engine's own ``info`` and
    ``default`` annotations, is preserved byte for byte.  A wholesale
    rewrite is the fastest way to make the game regenerate defaults
    and quietly lose the seeded values, so there is no code path here
    that builds an options document from nothing: the file is always
    loaded first, and an absent file is a hard error rather than an
    invitation to create one.

THE FILE FORMAT IS REPRODUCED EXACTLY
    ``options_manager::serialize`` writes an ARRAY of objects, each
    with ``info``, ``default``, ``name`` and ``value``
    [src/options.cpp:4052-4078], and ``options_manager::deserialize``
    reads both ``name`` and ``value`` with ``get_string``
    [src/options.cpp:4080-4100] -- so every value is a JSON STRING,
    even for numeric and boolean options: ``TERMINAL_X`` is ``"240"``
    and ``SOUND_ENABLED`` is ``"false"``.  ``options_manager::load``
    hands the file to a ``JsonArray`` [src/options.cpp:4022-4027], so
    the top level MUST be an array; a name-to-value mapping would not
    load at all, which is why this module rejects one instead of
    "helpfully" accepting it.

    ``options_manager::save`` uses ``JsonOut jout( fout, true )``, and
    that pretty printer emits objects INLINE while wrapping array
    members [src/json.cpp:2251-2350]:

        [
          { "info": "...", "default": "...", "name": "X", "value": "1" },
          { "info": "...", "default": "...", "name": "Y", "value": "2" }
        ]

    with two-space indentation, ``", "`` between members, ``": "``
    after each key, and no trailing newline after the closing bracket.
    ``WORLD::save_world_options`` uses ``JsonOut jout( fout )``
    [src/worldfactory.cpp:337-359] -- no pretty flag -- so a world's
    ``worldoptions.json`` is compact instead.

    :func:`serialize_entries` reproduces both layouts, including the
    engine's escaping rules [src/json.cpp:2363-2404], and
    :func:`load_entries` reports which one it found so a file is
    always rewritten in the layout its writer used.  The result is
    that seeding a value produces a ONE-LINE diff rather than
    reformatting all 176 lines, and that running this module twice
    leaves the file byte-identical.

THE SEVEN VALUES, AND THE REASON FOR EACH
    ``24_HOUR = "24h"``
        Values are ``{ "12h", "military", "24h" }``, default ``"12h"``
        [src/options.cpp:1868-1877].  ``to_string_time_of_day``
        renders ``"military"`` as ``"%02d%02d.%02d"`` (``0815.32``),
        ``"24h"`` as the fixed-width ``"%02d:%02d:%02d"``, and
        otherwise a variable-width AM/PM form
        [src/calendar.cpp:638-662].  Only ``"24h"`` matches the
        pipeline's ``[0-9]{2}:[0-9]{2}:[0-9]{2}`` clock regex.
        ``"military"`` is the trap this module exists to prevent: a
        legal value that matches nothing, sends every ``ingame_clock``
        to null, collapses every duration onto the 0.25 s floor and
        yields a plausible-looking movie built on nothing.  The
        written value is therefore verified, and ``"military"`` is
        rejected by name.
    ``SOUND_ENABLED = "false"``
        Default ``true`` [src/options.cpp:1774-1777].  Matches
        ``SDL_AUDIODRIVER=dummy`` so the game does not spend the
        session retrying an audio device that will never appear.
    ``USE_TILES = "true"``
        Default ``true`` [src/options.cpp:2500-2503], but set
        explicitly because ``TILES`` is gated on it --
        ``get_option( "TILES" ).setPrerequisite( "USE_TILES" )``
        [src/options.cpp:2530].  Without it the seeded tileset is
        inert.
    ``TILES = <resolved>``
        Preference with fallback: the MSXotto+ pack when it is
        installed, otherwise the ``ASCIITiles`` that ship with the
        checkout.  Ids come from the ``NAME:`` field of each
        ``tileset.txt`` and never from the directory name -- the
        directory is ``ASCIITileset`` while the id is ``ASCIITiles``.
        An id that is not installed is never written.
    ``TERMINAL_X = "240"`` and ``TERMINAL_Y = "67"``
        Ranges 80-960 and 24-270, defaults 80 and 24
        [src/options.cpp:2408-2416].  240x67 is what the engine
        derives on a 1920x1080 display, and seeding it removes the
        first-launch geometry discrepancy: 640x384 on launch one (the
        compiled 80 columns x 8 px by 24 rows x 16 px) against
        1920x1072 on launch two, since ``WindowWidth =
        TERMINAL_WIDTH * fontwidth * scaling_factor``
        [src/sdltiles.cpp:595-596].  Both are range-checked before
        anything is written.
    ``CHARACTER_POINT_POOLS = "any"``
        A ``world_default`` option with values ``{ "any",
        "multi_pool", "story_teller" }`` and default
        ``"story_teller"`` [src/options.cpp:2893-2897].  At that
        default ``pool_selection_modes_for_option`` offers FREEFORM
        only and ``pool_selection_is_fixed`` makes the pool tab
        informational and read-only [src/newcharacter.cpp:438-446,
        462-467] -- that is, there is no point-buy at all.  ``"any"``
        offers FREEFORM, MULTI_POOL and ONE_POOL, so the tab is live.
    ``WORLD_COMPRESSION2 = "false"``
        Default ``true`` [src/options.cpp:1816-1819].  With it on,
        ``game::save_player_data`` writes ``playerfile +
        SAVE_EXTENSION + zzip_suffix``, i.e. ``#<b64>.sav.zzip``
        [src/game_io.cpp:601-621; src/worldfactory.h:25], so the
        committed character file would be a compressed archive.
        Seeding ``false`` keeps it a plain, auditable ``#<b64>.sav``.

WORLD DEFAULTS LAND IN TWO PLACES
    A new world copies the global world defaults at creation --
    ``WORLD_OPTIONS = get_options().get_world_defaults()``
    [src/worldfactory.cpp:2039] -- so seeding
    ``CHARACTER_POINT_POOLS`` into ``options.json`` BEFORE the world
    exists is what the world inherits.  An existing world instead
    reads its own ``save/<World>/worldoptions.json``
    [src/path_info.cpp:416-419; src/worldfactory.cpp:2021-2035], and
    the pipeline's rule for a run that finds a save is to RESUME it,
    not to reshape it.  ``--worlds auto``, the default, therefore
    reports an existing world's value and warns when it is not
    point-buy capable but changes nothing; ``--worlds patch`` is the
    explicit opt-in that edits it.

WHAT IS DELIBERATELY NOT TOUCHED
    ``SIDEBAR_POSITION`` stays ``"right"``
    [src/options.cpp:2132-2136] because ``sidebar_geometry.py`` reads
    it rather than assuming it; ``SHOW_MONTHS`` stays ``true``
    [src/options.cpp:1878-1880] so the date line renders and the
    timeline's midnight-rollover guard has something to cross-check;
    ``FULLSCREEN`` stays as the engine left it, which is what
    produces the 1920x1072-at-+0+4 window inside the 1920x1080 root;
    ``OVERMAP_TILES`` stays ``"Larwick Overmap"``
    [src/options.cpp:2552-2557], which is installed.  No debug option
    is ever enabled and ``config/keybindings.json`` is never written
    by this module -- that file is the committed, auditable evidence
    that no debug action was bound, and it is not this module's to
    edit.

FIRST-LAUNCH REALITY
    A fresh userdir has no ``options.json`` at all: the engine writes
    it on exit from its first run, and that first run opens on a
    ``Select your language`` prompt rather than the main menu.  This
    module therefore runs AFTER a first (throwaway, calibration)
    launch, and says so precisely when the file is missing instead of
    inventing one.

USAGE
    $ python3 playthrough/tooling/seed_options.py
    $ python3 playthrough/tooling/seed_options.py --dry-run --explain
    $ python3 playthrough/tooling/seed_options.py --verify-only

    >>> import seed_options
    >>> report = seed_options.patch()
    >>> [c.name for c in report.changes]
    ['24_HOUR', 'CHARACTER_POINT_POOLS']

    Standard output carries only ``KEY=value`` lines, the same
    machine-readable channel ``launch_game.sh`` uses, so the resolved
    tileset and the change count can be read with ``grep '^KEY='``.
    Every diagnostic goes to stderr.  ``--explain`` writes a
    human-readable report to stderr, which is the text to paste into
    ``playthrough/TECHNICAL_NOTES.md``.

EXIT CODES
    0  the file already held, or now holds, every seeded value
    1  the file is missing, unreadable, not engine-shaped, or a value
       could not be seeded honestly
    2  command line usage error (argparse)
"""
import argparse
import json
import logging
import os
import re
import sys
import tempfile

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

LOG = logging.getLogger("playthrough.seed_options")

# ---------------------------------------------------------------------
# Option names, exactly as the engine spells them in options.json.
# ---------------------------------------------------------------------
OPT_24_HOUR = "24_HOUR"
OPT_SOUND_ENABLED = "SOUND_ENABLED"
OPT_USE_TILES = "USE_TILES"
OPT_TILES = "TILES"
OPT_TERMINAL_X = "TERMINAL_X"
OPT_TERMINAL_Y = "TERMINAL_Y"
OPT_POINT_POOLS = "CHARACTER_POINT_POOLS"
OPT_WORLD_COMPRESSION = "WORLD_COMPRESSION2"

# ---------------------------------------------------------------------
# The values that are seeded, and the constraints they are checked
# against.  Every constant below is the engine's own declaration,
# cited to the line that declares it.
# ---------------------------------------------------------------------

# src/options.cpp:1868-1877 { "12h", "military", "24h" }, "12h".
CLOCK_FORMATS = ("12h", "military", "24h")
CLOCK_FORMAT_WANTED = "24h"
# The legal-but-fatal value.  src/calendar.cpp:643-644 renders it as
# "%02d%02d.%02d", which the pipeline's clock regex cannot match.
CLOCK_FORMAT_FORBIDDEN = "military"

# src/options.cpp:2408-2411 add( "TERMINAL_X", ..., 80, 960, 80, ... )
TERMINAL_X_RANGE = (80, 960)
TERMINAL_X_WANTED = 240

# src/options.cpp:2413-2416 add( "TERMINAL_Y", ..., 24, 270, 24, ... )
TERMINAL_Y_RANGE = (24, 270)
TERMINAL_Y_WANTED = 67

# src/options.cpp:2893-2897 { "any", "multi_pool", "story_teller" },
# "story_teller".  src/newcharacter.cpp:462-467: the first two below
# are the only values under which the creator's pool tab is live.
POINT_POOLS = ("any", "multi_pool", "story_teller")
POINT_POOLS_WANTED = "any"
POINT_POOLS_POINT_BUY = ("any", "multi_pool")

# src/options.cpp:1816-1819 default true; seeded false so the
# character save is a plain #<b64>.sav rather than #<b64>.sav.zzip
# [src/game_io.cpp:601-621; src/worldfactory.h:25].
WORLD_COMPRESSION_WANTED = False

# The engine's boolean spelling in options.json -- getValue( true )
# stringifies through std::ios_base::boolalpha [src/json.cpp:2235].
BOOL_TRUE = "true"
BOOL_FALSE = "false"

# ---------------------------------------------------------------------
# Tileset resolution
#
# The preferred pack is asked for by both its NAME: id and its VIEW:
# display name, because the two differ: the pack that displays as
# "MSXotto+" declares NAME: MshockXottoplus, and that id -- not the
# display name -- is what goes into options.json.
#
# ASCIITiles ships with the checkout [gfx/ASCIITileset/tileset.txt:3]
# and is the fallback.  The compiled default "UltimateCataclysm"
# [src/options.cpp:2505-2508] is NOT present in a stock checkout, so
# it is never assumed to be available.
# ---------------------------------------------------------------------
TILESET_PREFERRED = "MshockXottoplus"
TILESET_PREFERRED_ALIASES = ("MshockXottoplus", "MSXotto+", "MShockXotto+")
TILESET_FALLBACK = "ASCIITiles"

# PATH_INFO::tileset_conf() [src/path_info.cpp:432-435].
TILESET_CONF = "tileset.txt"

# The engine searches PATH_INFO::user_gfx() = <userdir>/gfx and
# PATH_INFO::gfxdir() = gfx/ [src/options.cpp:1297-1304], recursively.
# Both are searched here, in that order, and the walk is depth-limited
# so a mis-pointed root cannot turn into an unbounded traversal.
GFX_DIR_NAME = "gfx"
TILESET_SEARCH_DEPTH = 3

# ---------------------------------------------------------------------
# Environment contract, defined once in playthrough/tooling/env.sh and
# only ever read here.  Nothing in this module exports or mutates an
# environment variable.
# ---------------------------------------------------------------------
ENV_REPO_ROOT = "PLAYTHROUGH_REPO_ROOT"          # env.sh:294
ENV_USERDIR = "PLAYTHROUGH_USERDIR"              # env.sh:300
ENV_OPTIONS_JSON = "PLAYTHROUGH_OPTIONS_JSON"    # env.sh:311
ENV_SAVE_DIR = "PLAYTHROUGH_SAVE_DIR"            # env.sh:309
ENV_TERMINAL_X = "PLAYTHROUGH_TERMINAL_X"        # env.sh:386
ENV_TERMINAL_Y = "PLAYTHROUGH_TERMINAL_Y"        # env.sh:387
ENV_TILESET = "PLAYTHROUGH_TILESET"              # env.sh:396
ENV_TILESET_FALLBACK = "PLAYTHROUGH_TILESET_FALLBACK"  # env.sh:397
# Emitted by launch_game.sh on its KEY=value stdout channel
# [playthrough/tooling/launch_game.sh:983]; consumed here as a HINT
# and always validated independently against what is installed.
ENV_TILESET_RESOLVED = "PLAYTHROUGH_TILESET_RESOLVED"
# "create" or "resume" [playthrough/tooling/launch_game.sh:1017,1044].
ENV_SESSION_MODE = "PLAYTHROUGH_SESSION_MODE"
SESSION_MODE_RESUME = "resume"

# ---------------------------------------------------------------------
# Paths.  Literal components only -- no value read from the
# environment or the command line is ever concatenated into a write
# target without going through _validated_target().
# ---------------------------------------------------------------------
USERDIR_PARTS = ("playthrough", "userdir")
CONFIG_PARTS = USERDIR_PARTS + ("config",)
OPTIONS_JSON_PARTS = CONFIG_PARTS + ("options.json",)
SAVE_PARTS = USERDIR_PARTS + ("save",)

# PATH_INFO::worldoptions() [src/path_info.cpp:416-419].
WORLD_OPTIONS_NAME = "worldoptions.json"
OPTIONS_NAME = "options.json"

# The only two filenames this module will ever write.  Combined with
# the requirement that the target already exists and already parses as
# an engine-shaped option array, this makes it impossible for a
# mistyped path to damage a repository file: no file under src/,
# data/, gfx/, tools/, tests/ or .github/ carries either name.
WRITABLE_NAMES = (OPTIONS_NAME, WORLD_OPTIONS_NAME)

# Markers that identify a Cataclysm-DDA checkout, the same pair
# playthrough/tooling/sidebar_geometry.py uses.
ROOT_MARKER_DIR_PARTS = ("data", "json", "ui")
ROOT_MARKER_FILE_PARTS = ("src", "path_info.cpp")

# A pretty-printed engine file opens with '[' then a newline
# [src/json.cpp:2288-2295]; a compact one opens with '[' then '{'.
_PRETTY_OPENING = re.compile(r"\A\s*\[\s*\n")

# The four members options_manager::serialize writes, in order
# [src/options.cpp:4066-4072].
ENTRY_MEMBERS = ("info", "default", "name", "value")


class SeedError(Exception):
    """A seeding operation could not be completed honestly.

    Raised for every condition that must be loud rather than
    silent: an absent options file (the first launch has not
    happened), an unparseable or non-engine-shaped one, an expected
    option missing from it, a tileset id that is not installed, a
    terminal dimension outside the engine's documented range, and a
    written value that does not read back as intended.
    """


# ---------------------------------------------------------------------
# Value objects
#
# The module reports what it did rather than asserting that it worked:
# every seeded key is accounted for either as a Change carrying its
# before and after values, or as an already-correct key.  That is what
# makes "the module reports precisely which keys it changed, from what
# to what" a property of the data rather than of the log formatting.
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Tileset:
    """One installed tileset, as the engine would enumerate it.

    :param ident: the ``NAME:`` field -- the value that goes into the
        ``TILES`` option.
    :param view: the ``VIEW:`` field, the human-facing name shown in
        the options menu; empty when the pack omits it, in which case
        the engine falls back to the id [src/options.cpp:1227-1229].
    :param directory: absolute path of the directory holding the
        ``tileset.txt`` that declared it.
    """

    ident: str
    view: str
    directory: str

    def __str__(self) -> str:
        if self.view and self.view != self.ident:
            return f"{self.ident} (\"{self.view}\")"
        return self.ident


@dataclass(frozen=True)
class TilesetChoice:
    """The resolved tileset, with the reason it was chosen.

    ``origin`` is one of ``requested``, ``preferred``, ``fallback``.
    The distinction is worth recording in
    ``playthrough/TECHNICAL_NOTES.md``: a run that fell back to
    ``ASCIITiles`` because the MSXotto+ pack was not installed is a
    materially different run from one that used it.
    """

    tileset: Tileset
    origin: str
    reason: str
    installed: Tuple[str, ...]

    @property
    def ident(self) -> str:
        """The value to write into the ``TILES`` option."""
        return self.tileset.ident


@dataclass(frozen=True)
class Change:
    """One option value that this module altered.

    :param before: the value found in the file, verbatim.
    :param after: the value written, verbatim.
    :param reason: why the pipeline needs it, for the report.
    """

    name: str
    before: str
    after: str
    reason: str

    def __str__(self) -> str:
        return f"{self.name}: {self.before!r} -> {self.after!r}"


@dataclass
class SeedReport:
    """The outcome of one patch run.

    :param path: the file that was inspected, and written when
        ``changes`` is non-empty and this was not a dry run.
    :param changes: the values altered, in the order they were
        applied.
    :param already: names that already held the wanted value, so no
        write was needed for them.
    :param notes: everything the operator should know that is not a
        change -- fallbacks taken, worlds found, decisions recorded.
    :param tileset: the resolved tileset, or ``None`` when tileset
        resolution was skipped.
    :param written: whether the file on disk was actually replaced.
    :param dry_run: whether writing was suppressed.
    :param pretty: the layout the file used, and was rewritten in.
    """

    path: str
    changes: List[Change] = field(default_factory=list)
    already: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    world_changes: List[Change] = field(default_factory=list)
    tileset: Optional[TilesetChoice] = None
    written: bool = False
    dry_run: bool = False
    pretty: bool = True

    def describe(self) -> str:
        """A human-readable report, for stderr and for the notes."""
        lines = [
            "seed_options report",
            f"  options file          {self.path}",
            f"  layout                "
            f"{'pretty (engine)' if self.pretty else 'compact'}",
            f"  written               {self.written}"
            f"{' (dry run)' if self.dry_run else ''}",
        ]
        if self.tileset is not None:
            choice = self.tileset
            lines.append(f"  tileset               {choice.tileset}")
            lines.append(f"  tileset origin        {choice.origin}")
            lines.append(f"  tileset reason        {choice.reason}")
            installed = ", ".join(choice.installed) or "(none)"
            lines.append(f"  tilesets installed    {installed}")
        if self.changes:
            lines.append("  changed")
            for change in self.changes:
                lines.append(f"    {change}")
                lines.append(f"        why: {change.reason}")
        else:
            lines.append("  changed               (nothing)")
        if self.already:
            lines.append(
                f"  already correct       {', '.join(self.already)}")
        if self.world_changes:
            lines.append("  world options changed")
            for change in self.world_changes:
                lines.append(f"    {change}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


# ---------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------
def _note(message: str, notes: Optional[List[str]] = None) -> None:
    """Record a note and make it visible at WARNING."""
    LOG.warning("%s", message)
    if notes is not None:
        notes.append(message)


# ---------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------
def _join(base: str, parts: Sequence[str]) -> str:
    """Join literal path components onto a base directory."""
    return os.path.normpath(os.path.join(base, *parts))


def _looks_like_checkout(candidate: str) -> bool:
    """True when ``candidate`` holds this repository's markers."""
    return (os.path.isdir(_join(candidate, ROOT_MARKER_DIR_PARTS)) and
            os.path.isfile(_join(candidate, ROOT_MARKER_FILE_PARTS)))


def repo_root(explicit: Optional[str] = None) -> str:
    """Return the absolute repository root, verified to be one.

    Resolution order: an explicit argument,
    ``$PLAYTHROUGH_REPO_ROOT`` [playthrough/tooling/env.sh:294], then
    two directories above this file.

    An explicit argument and the environment variable are
    AUTHORITATIVE: when either is supplied and is not a checkout, this
    raises instead of quietly falling through to a root that happens to
    work.  Silently disagreeing with the root a caller named is exactly
    the sort of plausible-but-wrong behaviour this module exists to
    avoid, and it would leave every sibling in the pipeline pointed
    somewhere else.

    :raises SeedError: when a supplied candidate, or the fallback, is
        not a Cataclysm-DDA checkout.
    """
    marker_dir = os.path.join(*ROOT_MARKER_DIR_PARTS)
    marker_file = os.path.join(*ROOT_MARKER_FILE_PARTS)
    here = os.path.abspath(os.path.dirname(__file__))

    env_root = os.environ.get(ENV_REPO_ROOT)
    named = []
    if explicit:
        named.append(("explicit argument", explicit))
    if env_root:
        named.append((f"${ENV_REPO_ROOT}", env_root))

    for origin, candidate in named:
        resolved = os.path.abspath(os.path.normpath(candidate))
        if _looks_like_checkout(resolved):
            LOG.debug("repository root from %s: %s", origin, resolved)
            return resolved
        raise SeedError(
            f"the repository root given by {origin} "
            f"('{resolved}') is not a Cataclysm-DDA checkout: it has "
            f"no {marker_dir} directory or no {marker_file} file")

    fallback = _join(here, ("..", ".."))
    if _looks_like_checkout(fallback):
        LOG.debug("repository root from this file's location: %s",
                  fallback)
        return fallback
    raise SeedError(
        f"cannot locate a Cataclysm-DDA checkout (no {marker_dir} "
        f"directory and no {marker_file} file); tried this file's "
        f"location -> {fallback}")


def userdir_path(root: Optional[str] = None) -> str:
    """Absolute path of the pipeline's userdir.

    ``$PLAYTHROUGH_USERDIR`` wins when set
    [playthrough/tooling/env.sh:300]; otherwise the path is derived
    from the repository root, matching the ``--userdir
    ./playthrough/userdir/`` the launcher passes
    [playthrough/tooling/env.sh:341].
    """
    from_env = os.environ.get(ENV_USERDIR)
    if from_env:
        return os.path.abspath(os.path.normpath(from_env))
    return _join(repo_root(root), USERDIR_PARTS)


def options_json_path(root: Optional[str] = None) -> str:
    """Absolute path of the game-written ``options.json``.

    ``$PLAYTHROUGH_OPTIONS_JSON`` wins when set
    [playthrough/tooling/env.sh:311]; otherwise the path is derived
    exactly as the engine derives it -- ``config_dir_value =
    user_dir_value + "config/"`` [src/path_info.cpp:164] and
    ``options_value = config_dir_value + "options.json"``
    [src/path_info.cpp:167].
    """
    from_env = os.environ.get(ENV_OPTIONS_JSON)
    if from_env:
        return os.path.abspath(os.path.normpath(from_env))
    return _join(repo_root(root), OPTIONS_JSON_PARTS)


def save_dir_path(root: Optional[str] = None) -> str:
    """Absolute path of ``<userdir>/save``.

    ``savedir_value = user_dir_value + "save/"``
    [src/path_info.cpp:144], exported as ``$PLAYTHROUGH_SAVE_DIR``
    [playthrough/tooling/env.sh:309].
    """
    from_env = os.environ.get(ENV_SAVE_DIR)
    if from_env:
        return os.path.abspath(os.path.normpath(from_env))
    return _join(repo_root(root), SAVE_PARTS)


def world_options_paths(root: Optional[str] = None) -> List[str]:
    """Every existing ``save/<World>/worldoptions.json``, sorted.

    An empty list is the ordinary state before a world exists, and is
    not an error: a world created later inherits the global world
    defaults seeded into ``options.json``
    [src/worldfactory.cpp:2039].
    """
    saves = save_dir_path(root)
    if not os.path.isdir(saves):
        return []
    found = []
    for entry in sorted(os.listdir(saves)):
        candidate = os.path.join(saves, entry, WORLD_OPTIONS_NAME)
        if os.path.isfile(candidate):
            found.append(candidate)
    return found


def _validated_target(path: str) -> str:
    """Return ``path`` as an absolute path this module may write.

    Three conditions must hold, and together they make an accidental
    write outside the engine's own configuration impossible:

    1. the basename is ``options.json`` or ``worldoptions.json`` --
       the only two files the engine keeps option values in;
    2. the file already EXISTS, because this module patches what the
       engine wrote and never creates a configuration document;
    3. it parses as an engine-shaped option array, which is checked
       by :func:`load_entries` before any write is attempted.

    No file under ``src/``, ``data/``, ``gfx/``, ``tools/``,
    ``tests/`` or ``.github/`` carries either name, so a mistyped
    path fails condition 1 or 2 rather than damaging the repository.

    :raises SeedError: when the basename is not writable by this
        module, or the file does not exist.
    """
    resolved = os.path.abspath(os.path.normpath(path))
    name = os.path.basename(resolved)
    if name not in WRITABLE_NAMES:
        raise SeedError(
            f"refusing to write '{resolved}': this module only ever "
            f"writes {' or '.join(WRITABLE_NAMES)}, and the basename "
            f"is '{name}'")
    if not os.path.isfile(resolved):
        raise SeedError(
            f"no options file at '{resolved}'.  The engine writes it "
            f"on its first launch, so run "
            f"playthrough/tooling/launch_game.sh first; this module "
            f"patches the file the game wrote and deliberately never "
            f"creates one from scratch")
    return resolved


# ---------------------------------------------------------------------
# Tileset discovery
#
# This mirrors build_resource_list [src/options.cpp:1189-1236] rather
# than inventing a parser, because the id the engine will accept is
# defined by that function and by nothing else:
#
#   * a whitespace-delimited token is read from each line;
#   * an empty token, or one whose first character is '#', means the
#     line is a comment and the rest of it is discarded;
#   * a token CONTAINING "NAME" makes the remainder of the line, once
#     trimmed, the tileset id;
#   * a token containing "VIEW" makes the remainder the display name
#     and ends the scan;
#   * where two packs declare the same id, the first wins.
#
# The directory name is never used: gfx/ASCIITileset declares
# NAME: ASCIITiles [gfx/ASCIITileset/tileset.txt:3], and writing
# "ASCIITileset" into the TILES option would select nothing.
# ---------------------------------------------------------------------
def _parse_tileset_conf(path: str) -> Optional[Tuple[str, str]]:
    """Return ``(ident, view)`` from one ``tileset.txt``, or None.

    A file that cannot be read, or that declares no ``NAME:``, yields
    ``None`` and a debug line: an unreadable pack is simply not an
    installed tileset, and treating it as one would risk writing an id
    the engine cannot resolve.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as err:
        LOG.debug("cannot read %s: %s", path, err)
        return None

    ident = ""
    view = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        token = parts[0]
        remainder = parts[1] if len(parts) > 1 else ""
        if "NAME" in token:
            ident = remainder.strip()
        elif "VIEW" in token:
            view = remainder.strip()
            break
    if not ident:
        LOG.debug("%s declares no NAME: field", path)
        return None
    return ident, view


def _tileset_confs(base: str, depth: int) -> List[str]:
    """Every ``tileset.txt`` under ``base``, to ``depth`` levels.

    Depth-limited on purpose.  The engine's own search is recursive
    [src/options.cpp:1304], and real packs sit either directly under
    ``gfx/`` or one level deeper, so three levels covers every layout
    that exists while keeping a mis-pointed root from turning into a
    walk of the whole filesystem.
    """
    if not os.path.isdir(base):
        return []
    found = []
    base_depth = base.rstrip(os.sep).count(os.sep)
    for current, dirnames, filenames in os.walk(base):
        if current.rstrip(os.sep).count(os.sep) - base_depth >= depth:
            dirnames[:] = []
        else:
            dirnames.sort()
        if TILESET_CONF in filenames:
            found.append(os.path.join(current, TILESET_CONF))
    return sorted(found)


def discover_tilesets(root: Optional[str] = None) -> List[Tileset]:
    """Enumerate the installed tilesets, engine-style.

    Both of the engine's search roots are scanned, in the engine's own
    order -- ``PATH_INFO::user_gfx()`` (``<userdir>/gfx``) then
    ``PATH_INFO::gfxdir()`` (``gfx/``) [src/options.cpp:1300-1304] --
    and a duplicate id keeps its first definition, matching
    ``search_resource``'s "only add if not a duplicate" behaviour
    [src/options.cpp:1250-1262].

    Returns an empty list when nothing is installed.  That is not
    raised here: :func:`resolve_tileset` is the function that has to
    fail, and it produces a far more useful message because it knows
    what was being looked for.
    """
    resolved_root = repo_root(root)
    bases = [
        os.path.join(userdir_path(resolved_root), GFX_DIR_NAME),
        os.path.join(resolved_root, GFX_DIR_NAME),
    ]
    seen: Dict[str, Tileset] = {}
    for base in bases:
        for conf in _tileset_confs(base, TILESET_SEARCH_DEPTH):
            parsed = _parse_tileset_conf(conf)
            if parsed is None:
                continue
            ident, view = parsed
            if ident in seen:
                LOG.debug(
                    "ignoring duplicate tileset id '%s' from %s "
                    "(already defined by %s)",
                    ident, conf, seen[ident].directory)
                continue
            seen[ident] = Tileset(
                ident=ident,
                view=view,
                directory=os.path.dirname(os.path.abspath(conf)))
    tilesets = sorted(seen.values(), key=lambda item: item.ident)
    LOG.debug("discovered %d tileset(s)", len(tilesets))
    return tilesets


def _match_tileset(
    tilesets: Sequence[Tileset],
    wanted: str,
) -> Optional[Tileset]:
    """Find ``wanted`` among ``tilesets`` by id or display name.

    Comparison is a literal string equality, never a pattern: real ids
    contain characters such as ``+`` that a regular expression would
    misread.  This is the same rule ``launch_game.sh`` applies
    [playthrough/tooling/launch_game.sh:853-864].
    """
    for tileset in tilesets:
        if tileset.ident == wanted or tileset.view == wanted:
            return tileset
    return None


def resolve_tileset(
    root: Optional[str] = None,
    requested: Optional[str] = None,
    preferred: Optional[str] = None,
    fallback: Optional[str] = None,
    tilesets: Optional[Sequence[Tileset]] = None,
) -> TilesetChoice:
    """Choose a tileset id that is genuinely installed.

    Order of preference:

    1. ``requested`` -- an explicit ``--tileset`` argument, or
       ``$PLAYTHROUGH_TILESET_RESOLVED`` as emitted by
       ``launch_game.sh`` [playthrough/tooling/launch_game.sh:983].
       It is treated as a HINT and validated independently: the
       launcher and this module must agree, and if they do not, the
       installed set decides.
    2. ``preferred`` -- the MSXotto+ pack, asked for by every name it
       goes by, defaulting to ``$PLAYTHROUGH_TILESET``
       [playthrough/tooling/env.sh:396].
    3. ``fallback`` -- ``ASCIITiles``, which ships with the checkout,
       defaulting to ``$PLAYTHROUGH_TILESET_FALLBACK``
       [playthrough/tooling/env.sh:397].

    :raises SeedError: when none of the three is installed.  Writing
        an id that is not installed would leave the game with a
        tileset it cannot load, and claiming otherwise in the run's
        notes would be a fabrication.
    """
    available = (list(tilesets) if tilesets is not None
                 else discover_tilesets(root))
    installed = tuple(item.ident for item in available)

    wanted_pref = preferred or os.environ.get(ENV_TILESET) or \
        TILESET_PREFERRED
    wanted_back = fallback or os.environ.get(ENV_TILESET_FALLBACK) or \
        TILESET_FALLBACK
    hint = requested or os.environ.get(ENV_TILESET_RESOLVED) or ""

    if hint:
        match = _match_tileset(available, hint)
        if match is not None:
            return TilesetChoice(
                tileset=match,
                origin="requested",
                reason=(
                    f"'{hint}' was requested explicitly and is "
                    f"installed at {match.directory}"),
                installed=installed)
        raise SeedError(
            f"tileset '{hint}' was requested but is not installed; "
            f"installed ids: {', '.join(installed) or '(none)'}.  "
            f"Install it under gfx/ (which is git-ignored by "
            f".gitignore:52, so installing it changes nothing "
            f"tracked) or drop the request and let the preferred or "
            f"fallback tileset be used")

    aliases = list(TILESET_PREFERRED_ALIASES)
    if wanted_pref not in aliases:
        aliases.insert(0, wanted_pref)
    for alias in aliases:
        match = _match_tileset(available, alias)
        if match is not None:
            return TilesetChoice(
                tileset=match,
                origin="preferred",
                reason=(
                    f"the preferred tileset is installed at "
                    f"{match.directory} (matched on '{alias}')"),
                installed=installed)

    match = _match_tileset(available, wanted_back)
    if match is not None:
        return TilesetChoice(
            tileset=match,
            origin="fallback",
            reason=(
                f"the preferred tileset ({wanted_pref}) is not "
                f"installed, so the checkout's own {match.ident} is "
                f"used instead"),
            installed=installed)

    raise SeedError(
        f"no usable tileset: neither the preferred '{wanted_pref}' "
        f"nor the fallback '{wanted_back}' is installed. Installed "
        f"ids: {', '.join(installed) or '(none)'}. Ids come from the "
        f"NAME: field of each gfx/*/tileset.txt, never from the "
        f"directory name")


# ---------------------------------------------------------------------
# Reading and writing the engine's option documents
# ---------------------------------------------------------------------
def load_entries(path: str) -> Tuple[List[Dict[str, object]], bool]:
    """Load one engine option document.

    :returns: ``(entries, pretty)`` where ``entries`` is the array of
        option objects exactly as stored -- member order preserved,
        unknown members preserved -- and ``pretty`` records whether the
        file was written by the pretty printer, so it can be rewritten
        in the same layout.
    :raises SeedError: when the file cannot be read, is not valid
        JSON, is not a JSON array, or holds an entry that is not an
        object with string ``name`` and ``value`` members.  Every one
        of those means the file is not what this module thinks it is,
        and patching past it would corrupt the engine's configuration.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as err:
        raise SeedError(f"cannot read {path}: {err}") from err

    try:
        data = json.loads(text)
    except ValueError as err:
        raise SeedError(
            f"{path} is not valid JSON: {err}.  The engine rewrites "
            f"this file on exit; do not hand-edit it while the game "
            f"is running") from err

    if not isinstance(data, list):
        raise SeedError(
            f"{path} must be a JSON array of option objects, got "
            f"{type(data).__name__}. options_manager::load hands the "
            f"file to a JsonArray [src/options.cpp:4022-4027], so a "
            f"name-to-value mapping would not load at all")

    entries: List[Dict[str, object]] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise SeedError(
                f"{path} entry {index} is {type(entry).__name__}, "
                f"expected an object with 'name' and 'value' members")
        for member in ("name", "value"):
            if member not in entry:
                raise SeedError(
                    f"{path} entry {index} lacks '{member}'; members "
                    f"present: {sorted(entry)}")
            if not isinstance(entry[member], str):
                raise SeedError(
                    f"{path} entry {index} has a non-string "
                    f"'{member}' ({entry[member]!r}); the engine "
                    f"reads both with get_string "
                    f"[src/options.cpp:4093-4096], so a non-string "
                    f"would make the file unloadable")
        entries.append(entry)

    pretty = bool(_PRETTY_OPENING.match(text))
    LOG.debug(
        "loaded %d option entries from %s (%s layout)",
        len(entries), path, "pretty" if pretty else "compact")
    return entries, pretty


def _json_string(value: str) -> str:
    """Encode one string exactly as ``JsonOut::write`` would.

    Reproduced from [src/json.cpp:2363-2404] rather than delegating to
    :func:`json.dumps` so that the output is byte-identical to what
    the engine wrote: ``/`` is left unescaped, characters at or above
    ``0x20`` are emitted raw -- which is what makes UTF-8 pass through
    untouched, the same effect as ``ensure_ascii=False`` -- and the
    remaining control characters use the engine's UPPERCASE hex form.
    """
    out = ['"']
    for char in value:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\b":
            out.append("\\b")
        elif char == "\f":
            out.append("\\f")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif char < " ":
            out.append("\\u%04X" % ord(char))
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _json_member_value(value: object) -> str:
    """Encode one member value for the engine's layout.

    Strings go through :func:`_json_string`, which is the engine's own
    encoder.  Anything else -- which the engine never writes into
    these documents, but which a future option type or a hand-edit
    could introduce -- is encoded compactly and non-ASCII-safe, the
    repository's ``json.dump(..., ensure_ascii=False)`` convention, so
    that an unexpected member survives a round trip instead of being
    dropped.
    """
    if isinstance(value, str):
        return _json_string(value)
    return json.dumps(value, ensure_ascii=False,
                      separators=(",", ":"))


def serialize_entries(
    entries: Sequence[Dict[str, object]],
    pretty: bool = True,
) -> str:
    """Render option entries in the engine's own JSON layout.

    ``pretty`` reproduces ``JsonOut( stream, true )``, which
    ``options_manager::save`` uses: array members wrapped and indented
    two spaces, objects kept inline with ``", "`` between members and
    ``": "`` after each key, and NO trailing newline after the closing
    bracket [src/json.cpp:2251-2350].  ``pretty=False`` reproduces
    ``JsonOut( stream )``, which ``WORLD::save_world_options`` uses
    [src/worldfactory.cpp:339], i.e. fully compact.

    Reproducing the layout rather than reformatting with
    ``json.dump(indent=...)`` is what keeps a seeded value to a
    one-line diff against what the game wrote, and what makes a second
    run byte-identical to the first.
    """
    rendered = []
    for entry in entries:
        members = [
            f"{_json_string(str(name))}: {_json_member_value(value)}"
            if pretty else
            f"{_json_string(str(name))}:{_json_member_value(value)}"
            for name, value in entry.items()
        ]
        if pretty:
            rendered.append("{ " + ", ".join(members) + " }")
        else:
            rendered.append("{" + ",".join(members) + "}")
    if not pretty:
        return "[" + ",".join(rendered) + "]"
    if not rendered:
        return "[\n]"
    body = ",\n  ".join(rendered)
    return "[\n  " + body + "\n]"


def write_atomic(path: str, text: str) -> None:
    """Replace ``path`` with ``text``, atomically.

    The engine has to be able to read this file at any moment, so a
    truncated write is not an acceptable failure mode: the content is
    written to a temporary file in the SAME directory -- so that
    :func:`os.replace` is a rename within one filesystem and therefore
    atomic -- flushed and fsynced, then moved into place.  A failure
    anywhere before the rename leaves the original file untouched.

    :raises SeedError: on any write failure, with the path preserved.
    """
    directory = os.path.dirname(path) or "."
    handle = None
    tmp_path = ""
    try:
        descriptor, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(path) + ".", suffix=".tmp",
            dir=directory)
        handle = os.fdopen(descriptor, "w", encoding="utf-8",
                           newline="\n")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(tmp_path, path)
        tmp_path = ""
    except OSError as err:
        raise SeedError(f"cannot write {path}: {err}") from err
    finally:
        if handle is not None:
            handle.close()
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as err:
                LOG.warning(
                    "left a temporary file behind at %s: %s",
                    tmp_path, err)


# ---------------------------------------------------------------------
# Value normalisation and validation
#
# Everything the engine stores is a string, so these helpers convert
# the module's typed intent into the engine's spelling and check it
# against the engine's own declared domain before it is written.  A
# value that cannot be validated is never written: that is the whole
# difference between this module and a sed script.
# ---------------------------------------------------------------------
def _bool_text(value: bool) -> str:
    """The engine's spelling of a boolean option value."""
    return BOOL_TRUE if value else BOOL_FALSE


def _validated_choice(name: str, value: str,
                      allowed: Sequence[str]) -> str:
    """Return ``value`` when the engine would accept it for ``name``.

    :raises SeedError: when it is outside the declared domain.
    """
    if value not in allowed:
        raise SeedError(
            f"'{value}' is not a legal {name} value; the engine "
            f"declares {{{', '.join(allowed)}}}")
    return value


def _validated_range(name: str, value: int,
                     bounds: Tuple[int, int]) -> str:
    """Return ``value`` as the engine's text, once range-checked.

    :raises SeedError: when it falls outside the engine's documented
        minimum and maximum.  Seeding a terminal dimension the engine
        rejects would silently leave the window at its compiled 80x24
        default, and the capture geometry would be wrong for the whole
        session.
    """
    low, high = bounds
    if not isinstance(value, int) or isinstance(value, bool):
        raise SeedError(
            f"{name} must be an integer, got {value!r}")
    if value < low or value > high:
        raise SeedError(
            f"{name}={value} is outside the engine's declared range "
            f"{low}-{high}")
    return str(value)


# ---------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------
# What to do about an existing world's worldoptions.json.
WORLDS_AUTO = "auto"
WORLDS_PATCH = "patch"
WORLDS_SKIP = "skip"
WORLDS_MODES = (WORLDS_AUTO, WORLDS_PATCH, WORLDS_SKIP)

# Why each seeded value is needed, quoted in the report and in every
# change record so that the reason travels with the change.
REASONS = {
    OPT_24_HOUR: (
        "fixed-width %02d:%02d:%02d clock; the 12h default is "
        "variable-width and 'military' emits 0815.32, neither of "
        "which the OCR regex can match [src/calendar.cpp:638-662]"),
    OPT_SOUND_ENABLED: (
        "matches SDL_AUDIODRIVER=dummy so the game does not retry an "
        "audio device that will never appear "
        "[src/options.cpp:1774-1777]"),
    OPT_USE_TILES: (
        "TILES is gated on it -- setPrerequisite( \"USE_TILES\" ) "
        "[src/options.cpp:2530] -- so without it the seeded tileset "
        "is inert"),
    OPT_TILES: (
        "the tileset actually installed under gfx/, resolved from the "
        "NAME: field of its tileset.txt "
        "[src/options.cpp:1189-1236]"),
    OPT_TERMINAL_X: (
        "240 columns x 8 px = the 1920 px window the capture geometry "
        "assumes [src/sdltiles.cpp:595-596]"),
    OPT_TERMINAL_Y: (
        "67 rows x 16 px = 1072 px, the window height inside the "
        "1920x1080 root [src/sdltiles.cpp:595-596]"),
    OPT_POINT_POOLS: (
        "the shipped story_teller default offers FREEFORM only and "
        "makes the pool tab read-only [src/newcharacter.cpp:438-446, "
        "462-467], i.e. no point-buy at all"),
    OPT_WORLD_COMPRESSION: (
        "keeps the committed character file a plain #<b64>.sav rather "
        "than #<b64>.sav.zzip [src/game_io.cpp:601-621; "
        "src/worldfactory.h:25]"),
}


def _index_entries(
    entries: Sequence[Dict[str, object]],
) -> Dict[str, List[Dict[str, object]]]:
    """Group entries by option name, keeping every occurrence.

    Every occurrence matters: ``options_manager::deserialize`` walks
    the array in order and calls ``setValue`` for each element
    [src/options.cpp:4080-4100], so a duplicate later in the file
    would win on load.  Patching all occurrences is therefore the only
    safe behaviour, and a duplicate is reported rather than hidden.
    """
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for entry in entries:
        name = str(entry["name"])
        grouped.setdefault(name, []).append(entry)
    return grouped


def _apply(
    grouped: Dict[str, List[Dict[str, object]]],
    name: str,
    wanted: str,
    path: str,
    changes: List[Change],
    already: List[str],
    notes: List[str],
) -> None:
    """Set one option's value in situ, or record that it was correct.

    Only the ``value`` member is touched.  The entry object itself is
    never replaced, so the engine's ``info`` and ``default``
    annotations -- which are useful evidence in their own right, the
    ``TILES`` entry's ``default`` text being a live inventory of what
    is installed -- survive untouched.

    :raises SeedError: when the option is absent from the file.  The
        engine writes every option it knows about, so a missing one
        means this file is not the document this module thinks it is,
        and adding an entry would mean inventing the ``info`` and
        ``default`` strings the engine owns.
    """
    occurrences = grouped.get(name)
    if not occurrences:
        raise SeedError(
            f"{path} has no '{name}' entry.  The engine serialises "
            f"every registered option [src/options.cpp:4052-4078], so "
            f"its absence means this is not a complete game-written "
            f"options file; this module will not invent an entry")
    if len(occurrences) > 1:
        _note(
            f"{name} appears {len(occurrences)} times in {path}; "
            f"every occurrence is being set, because the engine "
            f"applies them in order and the last one would win",
            notes)

    changed_from = None
    for entry in occurrences:
        before = str(entry["value"])
        if before != wanted:
            entry["value"] = wanted
            if changed_from is None:
                changed_from = before
    if changed_from is None:
        already.append(name)
        LOG.debug("%s already holds %r", name, wanted)
        return
    changes.append(
        Change(name=name, before=changed_from, after=wanted,
               reason=REASONS.get(name, "required by the pipeline")))


def patch(
    path: Optional[str] = None,
    root: Optional[str] = None,
    tileset: Optional[str] = None,
    terminal_x: Optional[int] = None,
    terminal_y: Optional[int] = None,
    point_pools: Optional[str] = None,
    world_compression: Optional[bool] = None,
    resolve_tiles: bool = True,
    worlds: str = WORLDS_AUTO,
    dry_run: bool = False,
) -> SeedReport:
    """Seed the pipeline's option values into ``path``, in place.

    :param path: the options file; defaults to
        :func:`options_json_path`, i.e.
        ``playthrough/userdir/config/options.json``.
    :param root: repository root override, for tileset discovery and
        the default path.
    :param tileset: an explicit ``TILES`` id or display name.  Treated
        as a hint and validated against what is installed.
    :param terminal_x: ``TERMINAL_X``; defaults to 240, range-checked
        against 80-960 [src/options.cpp:2408-2411].
    :param terminal_y: ``TERMINAL_Y``; defaults to 67, range-checked
        against 24-270 [src/options.cpp:2413-2416].
    :param point_pools: ``CHARACTER_POINT_POOLS``; defaults to
        ``"any"``.  A value that disables point-buy is accepted only
        because the engine accepts it, and is warned about.
    :param world_compression: ``WORLD_COMPRESSION2``; defaults to
        ``False``.
    :param resolve_tiles: when ``False``, ``TILES`` is left exactly as
        the engine wrote it and no tileset discovery is performed.
        Useful when patching a copy of the file on a host with no
        ``gfx/`` tree.
    :param worlds: what to do about an existing world's
        ``worldoptions.json`` -- ``"auto"`` reports but does not touch
        it, ``"patch"`` edits it, ``"skip"`` ignores it entirely.
    :param dry_run: compute and report everything, write nothing.

    ``24_HOUR``, ``SOUND_ENABLED`` and ``USE_TILES`` are deliberately
    NOT parameters.  There is no legitimate configuration of this
    pipeline in which the clock is not ``"24h"``, and offering the
    knob would offer ``"military"`` with it -- the one legal value that
    silently destroys every duration in the finished movie.

    :returns: a :class:`SeedReport` naming every change.
    :raises SeedError: for any condition that cannot be resolved
        honestly; nothing is written when one is raised.
    """
    if worlds not in WORLDS_MODES:
        raise SeedError(
            f"unknown worlds mode '{worlds}'; expected one of "
            f"{', '.join(WORLDS_MODES)}")

    target = _validated_target(path or options_json_path(root))
    entries, pretty = load_entries(target)
    grouped = _index_entries(entries)

    report = SeedReport(path=target, dry_run=dry_run, pretty=pretty)
    notes = report.notes

    wanted_x = TERMINAL_X_WANTED if terminal_x is None else terminal_x
    wanted_y = TERMINAL_Y_WANTED if terminal_y is None else terminal_y
    wanted_pools = (POINT_POOLS_WANTED if point_pools is None
                    else point_pools)
    wanted_zip = (WORLD_COMPRESSION_WANTED
                  if world_compression is None else world_compression)

    if wanted_pools not in POINT_POOLS_POINT_BUY:
        _note(
            f"{OPT_POINT_POOLS}='{wanted_pools}' does NOT enable "
            f"point-buy: pool_selection_is_fixed() is true for it and "
            f"the creator's pool tab is informational and read-only "
            f"[src/newcharacter.cpp:462-467].  Use "
            f"{' or '.join(POINT_POOLS_POINT_BUY)} for a live tab",
            notes)

    # Resolve the tileset before anything is mutated, so that an
    # unresolvable tileset leaves the file completely untouched.
    if resolve_tiles:
        report.tileset = resolve_tileset(
            root=root, requested=tileset)
        if report.tileset.origin == "fallback":
            _note(report.tileset.reason, notes)
        else:
            LOG.debug("tileset: %s", report.tileset.reason)
    elif tileset:
        raise SeedError(
            "a tileset was requested but tileset resolution is "
            "disabled; drop one of the two, because writing an "
            "unvalidated tileset id is exactly what this module "
            "refuses to do")

    plan: List[Tuple[str, str]] = [
        (OPT_24_HOUR, _validated_choice(
            OPT_24_HOUR, CLOCK_FORMAT_WANTED, CLOCK_FORMATS)),
        (OPT_SOUND_ENABLED, _bool_text(False)),
        (OPT_USE_TILES, _bool_text(True)),
        (OPT_TERMINAL_X, _validated_range(
            OPT_TERMINAL_X, wanted_x, TERMINAL_X_RANGE)),
        (OPT_TERMINAL_Y, _validated_range(
            OPT_TERMINAL_Y, wanted_y, TERMINAL_Y_RANGE)),
        (OPT_POINT_POOLS, _validated_choice(
            OPT_POINT_POOLS, wanted_pools, POINT_POOLS)),
        (OPT_WORLD_COMPRESSION, _bool_text(bool(wanted_zip))),
    ]
    if report.tileset is not None:
        plan.insert(3, (OPT_TILES, report.tileset.ident))

    for name, value in plan:
        _apply(grouped, name, value, target,
               report.changes, report.already, notes)

    if report.changes and not dry_run:
        write_atomic(target, serialize_entries(entries, pretty))
        report.written = True
        LOG.debug("wrote %d change(s) to %s",
                  len(report.changes), target)
    elif report.changes:
        _note(
            f"dry run: {len(report.changes)} change(s) computed but "
            f"{target} was not written",
            notes)
    else:
        LOG.debug("%s already held every seeded value", target)

    if report.written:
        _confirm_written(target, plan)

    _handle_worlds(report, root, wanted_pools, worlds, dry_run)
    return report


def _confirm_written(
    target: str,
    plan: Sequence[Tuple[str, str]],
) -> None:
    """Re-read ``target`` and prove the write took effect.

    This answers one narrow question -- did every planned value land on
    disk? -- and deliberately not the broader "does this file satisfy
    the pipeline's requirements?", which is :func:`verify`'s job.
    Keeping them apart means a caller who deliberately seeds an unusual
    value still gets an honest confirmation of what was written, while
    the acceptance gate stays strict.

    Reporting a change that did not take effect would be a fabrication,
    which is why this runs unconditionally after every write.

    :raises SeedError: when any planned value is not what the file now
        holds, naming the ``24_HOUR`` trap explicitly when that is the
        value at fault.
    """
    observed = read_values(target)
    problems = []
    for name, wanted in plan:
        actual = observed.get(name)
        if actual == wanted:
            continue
        detail = f"{name} reads back as {actual!r}, not {wanted!r}"
        if name == OPT_24_HOUR and actual == CLOCK_FORMAT_FORBIDDEN:
            detail += (
                f" -- '{CLOCK_FORMAT_FORBIDDEN}' renders the clock as "
                f"%02d%02d.%02d (0815.32) "
                f"[src/calendar.cpp:643-644], which the pipeline's "
                f"clock regex cannot match")
        problems.append(detail)
    if problems:
        raise SeedError(
            f"the write to {target} did not take effect:\n  - " +
            "\n  - ".join(problems))
    LOG.debug("confirmed %d written value(s) in %s",
              len(plan), target)


def _handle_worlds(
    report: SeedReport,
    root: Optional[str],
    point_pools: str,
    mode: str,
    dry_run: bool,
) -> None:
    """Report on, or patch, existing worlds' ``worldoptions.json``.

    ``CHARACTER_POINT_POOLS`` is a ``world_default`` option
    [src/options.cpp:2893], and a world captures the global world
    defaults when it is created --
    ``WORLD_OPTIONS = get_options().get_world_defaults()``
    [src/worldfactory.cpp:2039] -- after which its own
    ``worldoptions.json`` is authoritative for it
    [src/worldfactory.cpp:2021-2035].  So:

    * with no world yet, seeding ``options.json`` is sufficient and
      this function only says so;
    * with a world already present, the pipeline's rule is to RESUME
      that save rather than reshape it, so ``auto`` reports the
      world's current value and warns when it is not point-buy
      capable, but changes nothing.  ``patch`` is the explicit opt-in.
    """
    if mode == WORLDS_SKIP:
        report.notes.append(
            "existing world options were not inspected "
            "(--worlds skip)")
        return

    paths = world_options_paths(root)
    if not paths:
        report.notes.append(
            f"no world exists yet, so the new world will inherit "
            f"{OPT_POINT_POOLS}='{point_pools}' from the seeded "
            f"global world defaults "
            f"[src/worldfactory.cpp:2039]")
        return

    session_mode = os.environ.get(ENV_SESSION_MODE, "")
    for world_path in paths:
        world_name = os.path.basename(os.path.dirname(world_path))
        entries, pretty = load_entries(world_path)
        grouped = _index_entries(entries)
        occurrences = grouped.get(OPT_POINT_POOLS)
        if not occurrences:
            message = (
                f"world '{world_name}' has no {OPT_POINT_POOLS} entry "
                f"in {world_path}; it therefore inherits the global "
                f"world default and nothing was invented for it")
            if mode == WORLDS_PATCH:
                raise SeedError(
                    message + ", so --worlds patch cannot take effect")
            _note(message, report.notes)
            continue

        current = str(occurrences[0]["value"])
        if mode == WORLDS_AUTO:
            detail = (
                f"world '{world_name}' already exists with "
                f"{OPT_POINT_POOLS}='{current}' and was left "
                f"untouched: a run that finds a save resumes it")
            if session_mode == SESSION_MODE_RESUME:
                detail += (
                    f" (${ENV_SESSION_MODE}="
                    f"{SESSION_MODE_RESUME})")
            if current not in POINT_POOLS_POINT_BUY:
                _note(
                    f"{detail}.  Its creator pool tab is read-only; "
                    f"re-run with --worlds patch if that world still "
                    f"needs point-buy",
                    report.notes)
            else:
                report.notes.append(detail)
            continue

        _validated_choice(OPT_POINT_POOLS, point_pools, POINT_POOLS)
        world_target = _validated_target(world_path)
        changes: List[Change] = []
        already: List[str] = []
        _apply(grouped, OPT_POINT_POOLS, point_pools, world_target,
               changes, already, report.notes)
        if not changes:
            report.notes.append(
                f"world '{world_name}' already held "
                f"{OPT_POINT_POOLS}='{point_pools}'")
            continue
        if dry_run:
            report.notes.append(
                f"dry run: world '{world_name}' would change "
                f"{changes[0]}")
            continue
        write_atomic(world_target, serialize_entries(entries, pretty))
        report.world_changes.extend(changes)
        report.notes.append(
            f"world '{world_name}': {changes[0]} in {world_target}")


# ---------------------------------------------------------------------
# Verification
#
# Reading the file back is not belt-and-braces here: the failure this
# guards against is silent by nature.  A 24_HOUR value of "military"
# is legal, is accepted by the engine, and renders 0815.32 -- which
# the pipeline's [0-9]{2}:[0-9]{2}:[0-9]{2} clock regex never matches,
# so every ingame_clock goes null, every duration collapses onto the
# 0.25 s floor, and the finished movie looks entirely plausible while
# its pacing means nothing at all.  So the value is asserted, and the
# forbidden one is named in the failure.
# ---------------------------------------------------------------------
SEEDED_OPTIONS = (
    OPT_24_HOUR, OPT_SOUND_ENABLED, OPT_USE_TILES, OPT_TILES,
    OPT_TERMINAL_X, OPT_TERMINAL_Y, OPT_POINT_POOLS,
    OPT_WORLD_COMPRESSION,
)


def read_values(
    path: Optional[str] = None,
    root: Optional[str] = None,
) -> Dict[str, str]:
    """Return the current on-disk value of every seeded option.

    Observation only: nothing is asserted and nothing is written, so a
    dry run can report what the file actually holds without turning a
    not-yet-applied change into a failure.  An option absent from the
    file is absent from the result rather than defaulted, because the
    engine's compiled default is not what the file says.

    :raises SeedError: only when the file itself cannot be believed --
        missing, unreadable, or not an engine-shaped option array.
    """
    target = _validated_target(path or options_json_path(root))
    entries, _ = load_entries(target)
    grouped = _index_entries(entries)
    observed: Dict[str, str] = {}
    for name in SEEDED_OPTIONS:
        occurrences = grouped.get(name)
        if occurrences:
            # The engine applies the array in order, so the effective
            # value is the last occurrence's.
            observed[name] = str(occurrences[-1]["value"])
    return observed


def verify(
    path: Optional[str] = None,
    root: Optional[str] = None,
    tileset: Optional[str] = None,
    terminal_x: Optional[int] = None,
    terminal_y: Optional[int] = None,
    point_pools: Optional[str] = None,
    world_compression: Optional[bool] = None,
    require_installed: bool = True,
) -> Dict[str, str]:
    """Read the options file back and assert every seeded value.

    :param tileset: the id that should be present.  When ``None`` the
        stored value is instead checked against what is installed,
        which is the stronger check of the two whenever ``gfx/`` is
        reachable.
    :param require_installed: when ``True``, the stored ``TILES`` value
        must name an installed tileset.  Set ``False`` only when
        verifying a copy of the file away from a ``gfx/`` tree.
    :returns: the observed values of every seeded option.
    :raises SeedError: listing every mismatch found, so one run
        reports all of them rather than one at a time.
    """
    target = _validated_target(path or options_json_path(root))
    observed = read_values(target)

    problems: List[str] = []
    for name in SEEDED_OPTIONS:
        if name not in observed:
            problems.append(f"{name} is absent from {target}")

    clock = observed.get(OPT_24_HOUR)
    if clock == CLOCK_FORMAT_FORBIDDEN:
        problems.append(
            f"{OPT_24_HOUR} is '{CLOCK_FORMAT_FORBIDDEN}', which "
            f"renders the clock as %02d%02d.%02d (0815.32) "
            f"[src/calendar.cpp:643-644].  It is legal and it is "
            f"fatal: the pipeline's clock regex would match nothing, "
            f"every duration would fall to the floor, and the movie's "
            f"pacing would be fiction")
    elif clock != CLOCK_FORMAT_WANTED:
        problems.append(
            f"{OPT_24_HOUR} is {clock!r}, expected "
            f"{CLOCK_FORMAT_WANTED!r} for a fixed-width "
            f"%02d:%02d:%02d clock [src/calendar.cpp:645-647]")

    if observed.get(OPT_SOUND_ENABLED) != BOOL_FALSE:
        problems.append(
            f"{OPT_SOUND_ENABLED} is "
            f"{observed.get(OPT_SOUND_ENABLED)!r}, expected "
            f"{BOOL_FALSE!r}")
    if observed.get(OPT_USE_TILES) != BOOL_TRUE:
        problems.append(
            f"{OPT_USE_TILES} is {observed.get(OPT_USE_TILES)!r}, "
            f"expected {BOOL_TRUE!r}; TILES is inert without it "
            f"[src/options.cpp:2530]")

    wanted_zip = (WORLD_COMPRESSION_WANTED
                  if world_compression is None else world_compression)
    if observed.get(OPT_WORLD_COMPRESSION) != _bool_text(wanted_zip):
        problems.append(
            f"{OPT_WORLD_COMPRESSION} is "
            f"{observed.get(OPT_WORLD_COMPRESSION)!r}, expected "
            f"{_bool_text(wanted_zip)!r}")

    expected_x = str(TERMINAL_X_WANTED if terminal_x is None
                     else terminal_x)
    expected_y = str(TERMINAL_Y_WANTED if terminal_y is None
                     else terminal_y)
    for name, expected, bounds in (
        (OPT_TERMINAL_X, expected_x, TERMINAL_X_RANGE),
        (OPT_TERMINAL_Y, expected_y, TERMINAL_Y_RANGE),
    ):
        value = observed.get(name)
        if value != expected:
            problems.append(
                f"{name} is {value!r}, expected {expected!r}")
            continue
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            problems.append(
                f"{name} is {value!r}, which is not an integer")
            continue
        if not bounds[0] <= numeric <= bounds[1]:
            problems.append(
                f"{name}={numeric} is outside the engine's range "
                f"{bounds[0]}-{bounds[1]}")

    pools = observed.get(OPT_POINT_POOLS)
    expected_pools = (POINT_POOLS_WANTED if point_pools is None
                      else point_pools)
    if pools != expected_pools:
        problems.append(
            f"{OPT_POINT_POOLS} is {pools!r}, expected "
            f"{expected_pools!r}")
    elif pools not in POINT_POOLS_POINT_BUY:
        problems.append(
            f"{OPT_POINT_POOLS} is {pools!r}, which disables "
            f"point-buy: the creator's pool tab is informational and "
            f"read-only [src/newcharacter.cpp:462-467].  Expected one "
            f"of {', '.join(POINT_POOLS_POINT_BUY)}")

    stored_tiles = observed.get(OPT_TILES)
    if tileset is not None and stored_tiles != tileset:
        problems.append(
            f"{OPT_TILES} is {stored_tiles!r}, expected "
            f"{tileset!r}")
    if require_installed and stored_tiles is not None:
        installed = [item.ident for item in discover_tilesets(root)]
        if stored_tiles not in installed:
            problems.append(
                f"{OPT_TILES} is {stored_tiles!r}, which is not "
                f"installed; installed ids: "
                f"{', '.join(installed) or '(none)'}")

    if problems:
        raise SeedError(
            f"{target} does not hold the seeded values:\n  - " +
            "\n  - ".join(problems))
    LOG.debug("verified every seeded value in %s", target)
    return observed


# ---------------------------------------------------------------------
# Command line interface
# ---------------------------------------------------------------------
_EPILOG = """\
Run this AFTER the game's first launch has written options.json.  A
fresh userdir has no options file at all, and this module patches what
the engine wrote rather than creating one.

Standard output carries only KEY=value lines, so it can be read with
  SEEDED="$(python3 playthrough/tooling/seed_options.py)"
  echo "$SEEDED" | grep '^PLAYTHROUGH_TILESET_SEEDED='
Every diagnostic goes to stderr; --explain writes the human-readable
report there, which is the text to paste into
playthrough/TECHNICAL_NOTES.md.

Examples:
  python3 playthrough/tooling/seed_options.py
  python3 playthrough/tooling/seed_options.py --dry-run --explain
  python3 playthrough/tooling/seed_options.py --verify-only
  python3 playthrough/tooling/seed_options.py --worlds patch
"""


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line parser."""
    parser = argparse.ArgumentParser(
        prog="seed_options.py",
        description=(
            "Patch the game-written options.json in place, key by "
            "key, with the values the playthrough capture pipeline "
            "depends on."),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--options-json", metavar="FILE",
        help="the game-written options file; defaults to "
             "$PLAYTHROUGH_OPTIONS_JSON, then "
             "playthrough/userdir/config/options.json")
    parser.add_argument(
        "--repo-root", metavar="DIR",
        help="repository root; defaults to $PLAYTHROUGH_REPO_ROOT, "
             "then two directories above this file")
    parser.add_argument(
        "--tileset", metavar="ID",
        help="TILES id or display name; validated against the "
             "tilesets actually installed under gfx/.  Defaults to "
             "$PLAYTHROUGH_TILESET_RESOLVED as emitted by "
             f"launch_game.sh, then '{TILESET_PREFERRED}', then "
             f"'{TILESET_FALLBACK}'")
    parser.add_argument(
        "--no-tileset", dest="resolve_tiles", action="store_false",
        help="leave TILES exactly as the engine wrote it and perform "
             "no tileset discovery")
    parser.add_argument(
        "--terminal-x", type=int, metavar="N",
        default=TERMINAL_X_WANTED,
        help=f"TERMINAL_X, range {TERMINAL_X_RANGE[0]}-"
             f"{TERMINAL_X_RANGE[1]} (default "
             f"{TERMINAL_X_WANTED})")
    parser.add_argument(
        "--terminal-y", type=int, metavar="N",
        default=TERMINAL_Y_WANTED,
        help=f"TERMINAL_Y, range {TERMINAL_Y_RANGE[0]}-"
             f"{TERMINAL_Y_RANGE[1]} (default "
             f"{TERMINAL_Y_WANTED})")
    parser.add_argument(
        "--point-pools", choices=POINT_POOLS_POINT_BUY,
        default=POINT_POOLS_WANTED,
        help="CHARACTER_POINT_POOLS (default "
             f"{POINT_POOLS_WANTED}).  Only "
             f"{' and '.join(POINT_POOLS_POINT_BUY)} leave the "
             f"creator's pool tab live, so the engine's third value "
             f"'{POINT_POOLS[-1]}' is not offered here: it silently "
             f"removes point-buy altogether "
             f"[src/newcharacter.cpp:462-467]")
    compression = parser.add_mutually_exclusive_group()
    compression.add_argument(
        "--world-compression", dest="world_compression",
        action="store_true", default=WORLD_COMPRESSION_WANTED,
        help="set WORLD_COMPRESSION2 true, which makes a new world's "
             "character file #<b64>.sav.zzip")
    compression.add_argument(
        "--no-world-compression", dest="world_compression",
        action="store_false",
        help="set WORLD_COMPRESSION2 false so the character file is a "
             "plain #<b64>.sav (default)")
    parser.add_argument(
        "--worlds", choices=WORLDS_MODES, default=WORLDS_AUTO,
        help="what to do about an existing world's "
             "worldoptions.json: report it without touching it "
             "(auto, the default, which is what resuming a save "
             "requires), edit it (patch), or ignore it (skip)")
    parser.add_argument(
        "--verify-only", action="store_true",
        help="assert the seeded values without writing anything")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="compute and report every change, write nothing")
    parser.add_argument(
        "--explain", action="store_true",
        help="write the human-readable report to stderr")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="include debug detail on stderr")
    return parser


def _configure_cli_logging(verbose: bool) -> None:
    """Route this module's log records to the current stderr.

    Deliberately not :func:`logging.basicConfig`, which is a silent
    no-op once the root logger has a handler: a warning about a
    substituted default is the mechanism by which a fallback stays
    visible, so it must not be routed somewhere nobody is looking.
    """
    for existing in list(LOG.handlers):
        LOG.removeHandler(existing)
        existing.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("seed_options: %(levelname)s: %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG if verbose else logging.WARNING)
    LOG.propagate = False


def _emit(key: str, value: object) -> None:
    """Write one KEY=value line to stdout.

    The same machine-readable channel ``launch_game.sh`` uses
    [playthrough/tooling/launch_game.sh:257-259], so the resolved
    tileset and the change count can be read with ``grep '^KEY='``.
    """
    sys.stdout.write(f"{key}={value}\n")


def _report_stdout(report: SeedReport,
                   observed: Dict[str, str]) -> None:
    """Emit the machine-readable summary of one run."""
    _emit("PLAYTHROUGH_OPTIONS_JSON", report.path)
    _emit("PLAYTHROUGH_OPTIONS_WRITTEN", 1 if report.written else 0)
    _emit("PLAYTHROUGH_OPTIONS_CHANGED", len(report.changes))
    _emit("PLAYTHROUGH_WORLD_OPTIONS_CHANGED",
          len(report.world_changes))
    if report.tileset is not None:
        _emit("PLAYTHROUGH_TILESET_SEEDED", report.tileset.ident)
        _emit("PLAYTHROUGH_TILESET_SEEDED_VIEW",
              report.tileset.tileset.view)
        _emit("PLAYTHROUGH_TILESET_SEEDED_ORIGIN",
              report.tileset.origin)
    for key, option in (
        ("PLAYTHROUGH_SEEDED_24_HOUR", OPT_24_HOUR),
        ("PLAYTHROUGH_SEEDED_SOUND_ENABLED", OPT_SOUND_ENABLED),
        ("PLAYTHROUGH_SEEDED_USE_TILES", OPT_USE_TILES),
        ("PLAYTHROUGH_SEEDED_TILES", OPT_TILES),
        ("PLAYTHROUGH_SEEDED_TERMINAL_X", OPT_TERMINAL_X),
        ("PLAYTHROUGH_SEEDED_TERMINAL_Y", OPT_TERMINAL_Y),
        ("PLAYTHROUGH_SEEDED_CHARACTER_POINT_POOLS", OPT_POINT_POOLS),
        ("PLAYTHROUGH_SEEDED_WORLD_COMPRESSION2",
         OPT_WORLD_COMPRESSION),
    ):
        if option in observed:
            _emit(key, observed[option])


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Seed, or verify, the game-written options file.

    :param argv: argument list excluding the program name; defaults to
        :data:`sys.argv` ``[1:]``.
    :returns: 0 on success, 1 when the values cannot be seeded or
        verified honestly.  Usage errors exit 2 through argparse.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_cli_logging(args.verbose)

    if args.verify_only and args.dry_run:
        parser.error(
            "--verify-only and --dry-run are redundant together; "
            "--verify-only already writes nothing")

    try:
        if args.verify_only:
            path = args.options_json or options_json_path(
                args.repo_root)
            observed = verify(
                path,
                root=args.repo_root,
                tileset=args.tileset,
                terminal_x=args.terminal_x,
                terminal_y=args.terminal_y,
                point_pools=args.point_pools,
                world_compression=args.world_compression,
                require_installed=args.resolve_tiles)
            report = SeedReport(path=os.path.abspath(path))
            report.already.extend(sorted(observed))
            report.notes.append(
                "verify-only: nothing was written")
        else:
            report = patch(
                path=args.options_json,
                root=args.repo_root,
                tileset=args.tileset,
                terminal_x=args.terminal_x,
                terminal_y=args.terminal_y,
                point_pools=args.point_pools,
                world_compression=args.world_compression,
                resolve_tiles=args.resolve_tiles,
                worlds=args.worlds,
                dry_run=args.dry_run)
            if args.dry_run:
                # A dry run must not assert values it deliberately did
                # not write; it reports what the file actually holds
                # and lets --explain list what would change.
                observed = read_values(report.path)
            else:
                observed = verify(
                    report.path,
                    root=args.repo_root,
                    tileset=(report.tileset.ident
                             if report.tileset is not None else None),
                    terminal_x=args.terminal_x,
                    terminal_y=args.terminal_y,
                    point_pools=args.point_pools,
                    world_compression=args.world_compression,
                    require_installed=args.resolve_tiles)
    except SeedError as err:
        LOG.error("%s", err)
        return 1

    if args.explain:
        sys.stderr.write(report.describe() + "\n")
    _report_stdout(report, observed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
