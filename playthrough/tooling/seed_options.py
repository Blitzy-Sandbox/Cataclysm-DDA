#!/usr/bin/env python3
"""Patch the game-written option files in place, key by key.

This module seeds the Cataclysm-DDA option values the playthrough
capture pipeline depends on, into files **the engine itself wrote**:

    playthrough/userdir/config/options.json              (always)
    playthrough/userdir/save/<World>/worldoptions.json   (see below)

Nothing under ``src/``, ``data/`` or ``gfx/`` is touched, and this
module modifies no repository configuration file.

WHERE THE TARGET LIVES, AND WHY
    ``--userdir <path>`` routes to ``PATH_INFO::init_user_dir``
    [src/main.cpp:415-426], which normalises but deliberately does NOT
    absolutise the value [src/path_info.cpp:105], so
    ``--userdir ./playthrough/userdir/`` resolves against the process
    working directory -- the repository root.  From there
    ``config_dir_value = user_dir_value + "config/"``
    [src/path_info.cpp:164] and ``options_value = config_dir_value +
    "options.json"`` [src/path_info.cpp:167].

    Two build flags would move that ground, for two DIFFERENT reasons,
    and ``launch_game.sh`` owns both prohibitions.  ``USE_XDG_DIR=1`` is
    the only one that touches ``config_dir``: it is the ``#if`` arm of
    [src/path_info.cpp:152-166] and relocates ``config/`` to
    ``$XDG_CONFIG_HOME/cataclysm-dda/``, so this module's target would
    not be there at all.  ``USE_HOME_DIR=1`` leaves ``config_dir``
    alone and only changes the DEFAULT user directory
    [src/main.cpp:684; src/path_info.cpp:99-102], which an explicit
    ``--userdir`` never consults.  This module verifies the file is
    where it expects and fails loudly when it is not.

IN PLACE, KEY BY KEY -- NEVER WHOLESALE
    The engine writes an entry for every option it knows about.  Only
    the eight named below are touched; every other entry, and every
    member of every entry including the engine's own ``info`` and
    ``default`` annotations, is preserved byte for byte.  There is no
    code path here that builds an options document from nothing: a
    wholesale rewrite is the fastest way to make the game regenerate
    defaults and quietly lose the seeded values, so the file is always
    loaded first and an absent file is a hard error rather than an
    invitation to create one.

THE FILE FORMAT IS REPRODUCED EXACTLY
    ``options_manager::serialize`` writes an ARRAY of objects, each with
    ``info``, ``default``, ``name`` and ``value``
    [src/options.cpp:4052-4078], and ``deserialize`` reads ``name`` and
    ``value`` with ``get_string`` [src/options.cpp:4080-4102] -- so
    every value is a JSON STRING, even for numeric and boolean options:
    ``TERMINAL_X`` is ``"240"`` and ``SOUND_ENABLED`` is ``"false"``.
    ``options_manager::load`` hands the file to a ``JsonArray``
    [src/options.cpp:4197-4202], so the top level MUST be an array; a
    name-to-value mapping would not load at all, which is why this
    module rejects one instead of "helpfully" accepting it.

    Two layouts exist -- pretty for the global file, compact for a
    world's -- and :func:`load_entries` reports which one it found so
    :func:`serialize_entries` can write the same one back.  Seeding a
    value therefore produces a one-line diff rather than reformatting
    the file, and running this module twice leaves it byte-identical.

    The engine's own escaping rules are reproduced with it
    [src/json.cpp:2363-2404], so a value carrying a quote or a
    backslash survives a round trip unchanged.

THE EIGHT VALUES, AND THE REASON FOR EACH
    Counted from :data:`SEEDED_OPTIONS`, which is the same list the
    plan, the patch and the verifier all read: ``24_HOUR``,
    ``SOUND_ENABLED``, ``USE_TILES``, ``TILES``, ``TERMINAL_X``,
    ``TERMINAL_Y``, ``CHARACTER_POINT_POOLS``, ``WORLD_COMPRESSION2``.
    All eight are decided on every production run; none of them is
    optional, and there is no command-line path that omits one.

    :data:`REASONS` is the single source of truth for WHY each is
    needed, and it is quoted in the report and in every change record,
    so the reason travels with the change rather than living only here.
    Each engine-declared value set, default and range is recorded
    beside the constant it is checked against.  The three that fail
    SILENTLY when they are wrong -- ``24_HOUR``, ``TILES`` and the
    terminal dimensions -- are called out as such below.

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
        The MSXotto+ pack, which the run requires.  SILENT when it is
        wrong: an ASCII capture looks like a perfectly good frame, so a
        session recorded in the wrong artwork passes every other check.
        Ids come from the ``NAME:`` field of each ``tileset.txt`` and
        never from the directory name -- the required pack's directory
        is ``MShockXotto+`` while its id is ``MshockXottoplus``, and
        the checkout's own directory is ``ASCIITileset`` while its id
        is ``ASCIITiles``.  An id that is not installed is never
        written, and neither is a DIFFERENT installed one: when the
        pack is missing this module refuses rather than quietly writing
        the ``ASCIITiles`` that ship with the checkout, because that
        would record the session in the wrong tileset while every other
        check still passed.  ``--allow-tileset-fallback`` (or
        ``$PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1``) is the deliberate
        opt-in for a diagnostic run.
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
    exists is what the world inherits.  An existing world instead reads
    its own ``save/<World>/worldoptions.json``
    [src/path_info.cpp:416-419; src/worldfactory.cpp:2021-2035], and
    the pipeline's rule for a run that finds a save is to RESUME it,
    not to reshape it -- so the default ``--worlds`` mode reports an
    existing world's value and warns when it is not point-buy capable
    but changes nothing.

WHAT IS DELIBERATELY NOT TOUCHED
    ``SIDEBAR_POSITION`` stays ``"right"`` [src/options.cpp:2132-2136]
    because ``sidebar_geometry.py`` reads it rather than assuming it;
    ``SHOW_MONTHS`` stays ``true`` [src/options.cpp:1878-1880] so the
    date line renders and the timeline's rollover guard has something to
    cross-check; ``FULLSCREEN`` stays ``"windowedbl"``
    [src/options.cpp:2715-2724], which leaves the 1920x1072 render grid
    inside the 1920x1080 X root the crop is measured against; and
    ``OVERMAP_TILES`` stays ``"Larwick Overmap"``
    [src/options.cpp:2552-2557], which is installed.

    No debug option is ever enabled, and ``config/keybindings.json`` is
    never written by this module: it is committed so the captured state
    can be audited for a debug binding, and it is not this module's to
    edit.  The complementary evidence is source-level --
    data/raw/keybindings.json declares ``debug_mode`` (3398-3403),
    ``debug`` (3404-3409) and ``debug_hour_timer`` (3466-3471) with no
    ``bindings`` array, so they are unbound by default.

FIRST-LAUNCH REALITY
    A fresh userdir has no ``options.json``: the engine writes it on
    exit from its first run, and that run opens on a
    ``Select your language`` prompt rather than the main menu.  This
    module therefore runs AFTER a first, throwaway calibration launch,
    and says so precisely when the file is missing instead of inventing
    one.

EVERY WRITE IS CONFINED, AND ALL WRITES COMMIT TOGETHER
    CONFINEMENT.  Every path this module opens for writing goes through
    :func:`_validated_target`, which enumerates the conditions it
    requires; the point of them is that a write outside this pipeline's
    own userdir is impossible rather than merely unlikely.

    TRANSACTIONALITY.  Every file's new content is computed in memory
    first; only then is anything written, in one pass, and if any write
    fails the ones already made are restored from the exact bytes they
    held before.  Writing the global file and only then discovering a
    world cannot be patched would leave ``24_HOUR=24h`` and a new
    tileset applied while the world still forced a read-only pool tab,
    with nobody told which half landed.

USAGE
    $ python3 playthrough/tooling/seed_options.py
    $ python3 playthrough/tooling/seed_options.py --dry-run --explain
    $ python3 playthrough/tooling/seed_options.py --verify-only

    Standard output carries only ``KEY=value`` lines, the same
    machine-readable channel ``launch_game.sh`` uses, so the resolved
    tileset and the change count can be read with ``grep '^KEY='``.
    Every diagnostic goes to stderr, and ``--explain`` writes a
    human-readable report there.

EXIT CODES
    0  the file already held, or now holds, every seeded value
    1  the file is missing, unreadable, not engine-shaped, or a value
       could not be seeded honestly
    2  command line usage error (argparse)
"""
import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import stat
import sys
import tempfile
import time

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
# Tileset resolution -- ONE REQUIRED TILESET, NO FALLBACK
#
# The required pack is asked for by both its NAME: id and its VIEW:
# display name, because the two differ: the pack that displays as
# "MSXotto+" declares NAME: MshockXottoplus, and that id -- not the
# display name -- is what goes into options.json.
#
# There is deliberately no fallback.  The requirement is to install the
# CDDA-Tilesets pack and configure MSXotto+, and the checkout's own
# ASCIITiles [gfx/ASCIITileset/tileset.txt:3] would satisfy nothing
# except the appearance of it: the game would render, every frame would
# be a real capture, every count would tally, and the requirement would
# have gone unmet with no symptom other than ASCII art in the finished
# film.  So an absent required tileset is a hard failure here, exactly
# as it is in ``launch_game.sh`` -- which hydrates the pack from its
# pre-placed copy before this module ever runs.
#
# An operator who genuinely wants a different tileset sets
# ``$PLAYTHROUGH_TILESET`` or passes ``--tileset``; that value is then
# validated against what is installed just as strictly, and nothing is
# ever substituted behind their back.  The compiled default
# "UltimateCataclysm" [src/options.cpp:2505-2508] is not present in a
# stock checkout and is never assumed to be available.
# ---------------------------------------------------------------------
TILESET_REQUIRED = "MshockXottoplus"
TILESET_REQUIRED_ALIASES = (
    "MshockXottoplus", "MSXotto+", "MShockXotto+")

# The checkout's own tileset -- the one that is always present, because
# .gitignore:52 negates gfx/ASCIITileset -- and DIAGNOSTIC ONLY.  It is
# NAMED here and defaulted from $PLAYTHROUGH_TILESET_FALLBACK, but
# naming it authorises nothing: _fallback_allowed() has to say yes
# first, and only an explicit --allow-tileset-fallback or
# $PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1 makes it do so.
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
# env.sh exports the eight below from its "Artifact layout" and
# "Display, window and grid geometry" sections.  They are cited by
# NAME rather than by line: env.sh is a sibling that changes in the
# same commit as this file, so a line number there rots, while
# `grep 'export PLAYTHROUGH_USERDIR' playthrough/tooling/env.sh`
# does not.  Engine-source citations keep their line numbers, because
# that tree is upstream and frozen.
ENV_REPO_ROOT = "PLAYTHROUGH_REPO_ROOT"
ENV_USERDIR = "PLAYTHROUGH_USERDIR"
ENV_OPTIONS_JSON = "PLAYTHROUGH_OPTIONS_JSON"
ENV_CONFIG_DIR = "PLAYTHROUGH_CONFIG_DIR"
ENV_SAVE_DIR = "PLAYTHROUGH_SAVE_DIR"
ENV_TERMINAL_X = "PLAYTHROUGH_TERMINAL_X"
ENV_TERMINAL_Y = "PLAYTHROUGH_TERMINAL_Y"
ENV_TILESET = "PLAYTHROUGH_TILESET"
# env.sh -- the spellings ONE required pack goes by, never a list
# of acceptable alternatives.  Whitespace-separated, as a shell
# variable has to be.
ENV_TILESET_ALIASES = "PLAYTHROUGH_TILESET_ALIASES"
# env.sh -- the checkout's own tileset, and DIAGNOSTIC ONLY.
# Nothing here consults it unless the substitution is asked for by
# name through the opt-in below.
ENV_TILESET_FALLBACK = "PLAYTHROUGH_TILESET_FALLBACK"
# The one opt-in that lets a tileset other than MSXotto+ be
# written; launch_game.sh reads the same variable, so a single
# setting governs the whole pipeline -- and both stages announce
# themselves on stderr when it is set.
ENV_ALLOW_TILESET_FALLBACK = "PLAYTHROUGH_ALLOW_TILESET_FALLBACK"
# Emitted by launch_game.sh on its KEY=value stdout channel
# [playthrough/tooling/launch_game.sh, resolve_tileset]; consumed
# here as a HINT
# and always validated independently against what is installed.
ENV_TILESET_RESOLVED = "PLAYTHROUGH_TILESET_RESOLVED"
# "create" or "resume"
# [playthrough/tooling/launch_game.sh, probe_save_resume].
ENV_SESSION_MODE = "PLAYTHROUGH_SESSION_MODE"
SESSION_MODE_RESUME = "resume"

# ---------------------------------------------------------------------
# Paths.  Literal components only -- no value read from the
# environment or the command line is ever concatenated into a write
# target without going through _validated_target().
# ---------------------------------------------------------------------
USERDIR_PARTS = ("playthrough", "userdir")
CONFIG_DIR_NAME = "config"
SAVE_DIR_NAME = "save"
CONFIG_PARTS = USERDIR_PARTS + (CONFIG_DIR_NAME,)
OPTIONS_JSON_PARTS = CONFIG_PARTS + ("options.json",)
SAVE_PARTS = USERDIR_PARTS + (SAVE_DIR_NAME,)

# PATH_INFO::worldoptions() [src/path_info.cpp:416-419].
WORLD_OPTIONS_NAME = "worldoptions.json"
OPTIONS_NAME = "options.json"

# Per-character save files, written by save_player_data() as
# ``playerfile + SAVE_EXTENSION`` and, with WORLD_COMPRESSION2 -- which
# DEFAULTS TO TRUE -- as that plus ``zzip_suffix``
# [src/game_io.cpp; src/path_info.h:14; src/worldfactory.h:25].  The
# engine names them ``#<base64-of-character-name>``, so the "#" prefix
# separates a character file from any other .sav-suffixed file.  BOTH
# FORMS COUNT: counting only "*.sav" reports zero survivors for a
# perfectly real compressed save, and the world-patch prohibition below
# turns on that count.
CHARACTER_PREFIX = "#"
SAVE_EXTENSION = ".sav"
ZZIP_SUFFIX = ".zzip"
COMPRESSED_SAVE_EXTENSION = SAVE_EXTENSION + ZZIP_SUFFIX

# The only two filenames this module will ever write.  Combined with
# the requirement that the target already exists, is not a symlink,
# resolves inside this pipeline's own userdir, and already parses as an
# engine-shaped option array, this makes it impossible for a mistyped
# or hostile path to damage a file this module does not own: no file
# under src/, data/, gfx/, tools/, tests/ or .github/ carries either
# name, and nothing outside <userdir>/config and <userdir>/save/<World>
# is writable at all.
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

    ``origin`` is ``requested`` when a caller named the tileset,
    ``required`` when the pipeline's own required pack was resolved,
    and ``fallback`` when a deliberately allowed substitute was used.
    The distinction is worth recording in
    ``playthrough/TECHNICAL_NOTES.md``: a run that used an
    operator-nominated tileset, or that fell back to the checkout's
    own ``ASCIITiles`` because the MSXotto+ pack was not installed, is
    a materially different run from one that used the required pack.
    ``fallback`` is why the third value exists at all, and it is
    reachable only deliberately, through
    ``--allow-tileset-fallback`` -- without that, an unavailable
    required tileset raises instead of resolving.
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

    :param before: the value the ENGINE was using, verbatim.  With a
        duplicated key that is the LAST occurrence's value, because the
        engine applies them in order and each overwrites the previous.
    :param after: the value written, verbatim.
    :param reason: why the pipeline needs it, for the report.
    :param path: the file the change was made in, when it is not the
        global options file.  Carried so a world change can be
        confirmed against the file it actually landed in.
    """

    name: str
    before: str
    after: str
    reason: str
    path: Optional[str] = None

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


# ---------------------------------------------------------------------
# Where this module is allowed to write
#
# Everything below exists because "which file gets patched" is decided
# by untrusted input: $PLAYTHROUGH_OPTIONS_JSON, $PLAYTHROUGH_USERDIR,
# $PLAYTHROUGH_SAVE_DIR, $PLAYTHROUGH_REPO_ROOT and the command line.
# Checking the BASENAME and that the file parses is not enough: any
# writable options.json anywhere on the host satisfies both, and a
# symlink named options.json satisfies them while pointing at
# something else entirely.
#
# The rule enforced here is positional, not nominal.  The file must sit
# where the ENGINE puts it -- <userdir>/config/options.json, or
# <userdir>/save/<World>/worldoptions.json -- inside the userdir of a
# checkout this module can vouch for, with no symlinked component
# anywhere below that userdir.  The one way to move the tree is an
# explicit --repo-root/root= naming a genuine checkout, which is a
# deliberate act at the call site; the environment may CONFIRM the
# location but can no longer redirect it.
# ---------------------------------------------------------------------
def _module_repo_root() -> str:
    """Return the checkout this file is part of, from its own path.

    Derived from ``__file__`` alone, so it is the one root no
    environment variable can influence.  It is what an environment
    variable is checked AGAINST.
    """
    here = os.path.realpath(os.path.dirname(__file__))
    return os.path.realpath(os.path.join(here, "..", ".."))


def _within(path: str, root: str) -> bool:
    """True when ``path`` is ``root`` itself or lies beneath it."""
    return path == root or path.startswith(root + os.sep)


def _assert_within(resolved: str, root: str, label: str) -> None:
    """Refuse a path that does not resolve inside ``root``.

    The FULLY RESOLVED form is tested, so ``../`` and a symlink
    pointing out of the tree are both caught.

    :raises SeedError: when the path resolves outside ``root``.
    """
    canonical = os.path.realpath(resolved)
    if not _within(canonical, root):
        raise SeedError(
            f"refusing to use {label} '{resolved}': it resolves to "
            f"'{canonical}', which is outside '{root}'.  This module "
            f"only ever touches the engine's own configuration inside "
            f"the pipeline's userdir")


def _assert_no_symlink(resolved: str, root: str, label: str) -> None:
    """Refuse ``resolved`` if it or a component below ``root`` links.

    A link inside the tree still points somewhere else, and following
    one would let a single planted link turn a configuration patch
    into a write to an arbitrary file that the caller believes is
    options.json.  The final component is checked first because that
    case is well defined however the path was spelled.

    :raises SeedError: when any component is a symbolic link.
    """
    if os.path.islink(resolved):
        raise SeedError(
            f"refusing to use {label} '{resolved}': it is a symbolic "
            f"link, and this module patches files rather than "
            f"following links to them")
    if not _within(resolved, root):
        # Reached through a link ABOVE the root, e.g. a checkout under
        # a linked directory.  _assert_within() has already proved the
        # destination is inside the tree.
        return
    current = root
    for part in os.path.relpath(resolved, root).split(os.sep):
        if part in ("", os.curdir):
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise SeedError(
                f"refusing to use {label} '{resolved}': '{current}' "
                f"is a symbolic link, so the path could be redirected "
                f"inside '{root}'")


def _confined(resolved: str, root: str, label: str) -> str:
    """Return ``resolved`` once it is proved to be inside ``root``."""
    _assert_within(resolved, root, label)
    _assert_no_symlink(resolved, root, label)
    return resolved


def approved_userdir(root: Optional[str] = None) -> str:
    """Return the only userdir tree this module may read or write.

    Derived from :func:`repo_root`, which honours an explicit argument
    but requires the environment to agree with this file's own
    location.  Every path this module opens is checked against the
    result.
    """
    return _join(repo_root(root), USERDIR_PARTS)


def repo_root(explicit: Optional[str] = None) -> str:
    """Return the absolute repository root, verified to be one.

    Resolution order: an explicit argument,
    ``$PLAYTHROUGH_REPO_ROOT`` [playthrough/tooling/env.sh], then
    two directories above this file.

    An explicit argument is AUTHORITATIVE: when it is supplied and is
    not a checkout, this raises instead of quietly falling through to a
    root that happens to work.  Silently disagreeing with the root a
    caller named is exactly the sort of plausible-but-wrong behaviour
    this module exists to avoid, and it would leave every sibling in
    the pipeline pointed somewhere else.

    ``$PLAYTHROUGH_REPO_ROOT`` may CONFIRM the root but can no longer
    move it.  env.sh derives that variable from its own location
    [playthrough/tooling/env.sh] and this file sits beside env.sh,
    so in every legitimate invocation the two agree; a value that
    names a DIFFERENT checkout is a redirection of every subsequent
    write and is refused rather than followed.  Relocating the tree is
    the explicit argument's job.

    :raises SeedError: when a supplied candidate, or the fallback, is
        not a Cataclysm-DDA checkout, or when the environment names a
        different checkout from the trusted one.
    """
    marker_dir = os.path.join(*ROOT_MARKER_DIR_PARTS)
    marker_file = os.path.join(*ROOT_MARKER_FILE_PARTS)
    env_root = os.environ.get(ENV_REPO_ROOT)

    if explicit:
        resolved = os.path.abspath(os.path.normpath(explicit))
        if not _looks_like_checkout(resolved):
            raise SeedError(
                f"the repository root given by explicit argument "
                f"('{resolved}') is not a Cataclysm-DDA checkout: it "
                f"has no {marker_dir} directory or no {marker_file} "
                f"file")
        trusted = resolved
        origin = "explicit argument"
    else:
        trusted = _module_repo_root()
        if not _looks_like_checkout(trusted):
            raise SeedError(
                f"cannot locate a Cataclysm-DDA checkout (no "
                f"{marker_dir} directory and no {marker_file} file); "
                f"tried this file's location -> {trusted}")
        origin = "this file's location"

    if env_root:
        from_env = os.path.realpath(
            os.path.abspath(os.path.normpath(env_root)))
        if from_env != os.path.realpath(trusted):
            raise SeedError(
                f"${ENV_REPO_ROOT} names '{from_env}', but the "
                f"trusted root from {origin} is "
                f"'{os.path.realpath(trusted)}'.  The environment may "
                f"confirm the checkout this module patches; it may not "
                f"redirect it.  Pass --repo-root to work on another "
                f"checkout deliberately")

    LOG.debug("repository root from %s: %s", origin, trusted)
    return trusted


def userdir_path(root: Optional[str] = None) -> str:
    """Absolute path of the pipeline's userdir.

    ``$PLAYTHROUGH_USERDIR`` wins when set
    [playthrough/tooling/env.sh]; otherwise the path is derived
    from the repository root, matching the ``--userdir
    ./playthrough/userdir/`` the launcher passes
    [playthrough/tooling/env.sh].
    """
    approved = _join(repo_root(root), USERDIR_PARTS)
    from_env = os.environ.get(ENV_USERDIR)
    if from_env:
        return _confined(
            os.path.abspath(os.path.normpath(from_env)), approved,
            f"the userdir from ${ENV_USERDIR}")
    return approved


def config_dir_path(root: Optional[str] = None) -> str:
    """Absolute path of ``<userdir>/config``.

    ``config_dir_value = user_dir_value + "config/"``
    [src/path_info.cpp:164], exported as ``$PLAYTHROUGH_CONFIG_DIR``.
    Derived from :func:`userdir_path` when that is unset, so the
    config directory always sits under the same userdir the save
    directory does -- which is what lets
    :func:`_permitted_write_locations` describe one coherent tree.
    """
    from_env = os.environ.get(ENV_CONFIG_DIR)
    if from_env:
        return os.path.abspath(os.path.normpath(from_env))
    return os.path.join(userdir_path(root), CONFIG_DIR_NAME)


def options_json_path(root: Optional[str] = None) -> str:
    """Absolute path of the game-written ``options.json``.

    ``$PLAYTHROUGH_OPTIONS_JSON`` wins when set
    [playthrough/tooling/env.sh]; otherwise the path is derived
    exactly as the engine derives it -- ``config_dir_value =
    user_dir_value + "config/"`` [src/path_info.cpp:164] and
    ``options_value = config_dir_value + "options.json"``
    [src/path_info.cpp:167].
    """
    approved = approved_userdir(root)
    from_env = os.environ.get(ENV_OPTIONS_JSON)
    if from_env:
        return _confined(
            os.path.abspath(os.path.normpath(from_env)), approved,
            f"the options file from ${ENV_OPTIONS_JSON}")
    return _join(repo_root(root), OPTIONS_JSON_PARTS)


def save_dir_path(root: Optional[str] = None) -> str:
    """Absolute path of ``<userdir>/save``.

    ``savedir_value = user_dir_value + "save/"``
    [src/path_info.cpp:144], exported as ``$PLAYTHROUGH_SAVE_DIR``
    [playthrough/tooling/env.sh].
    """
    approved = approved_userdir(root)
    from_env = os.environ.get(ENV_SAVE_DIR)
    if from_env:
        return _confined(
            os.path.abspath(os.path.normpath(from_env)), approved,
            f"the save directory from ${ENV_SAVE_DIR}")
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
    approved = approved_userdir(root)
    found = []
    for entry in sorted(os.listdir(saves)):
        candidate = os.path.join(saves, entry, WORLD_OPTIONS_NAME)
        if not os.path.isfile(candidate):
            continue
        # A world directory or world options file that is a link is
        # refused rather than skipped: this list is what gets PATCHED,
        # so a link here would redirect the patch, and quietly ignoring
        # it would hide a world the caller believes was inspected.
        found.append(
            _confined(candidate, approved,
                      "the world options file"))
    return found


def character_saves_in(world_dir: str) -> List[str]:
    """Every character save in one world directory, deduplicated.

    ``#<base64-name>.sav`` and ``#<base64-name>.sav.zzip`` are the SAME
    survivor -- WORLD_COMPRESSION2 decides which form is written and it
    defaults to true -- so the ``.zzip`` suffix is stripped and each base
    name counted once.  Every candidate is ``lstat``-ed: a symlink is
    refused rather than counted, because the engine writes the save
    through that name and a link puts it outside the committed tree.

    This is what makes "does a survivor exist in this world?" a question
    with an answer, which is the question ``--worlds patch`` must not be
    allowed to ignore.
    """
    names = set()
    try:
        entries = sorted(os.listdir(world_dir))
    except OSError as err:
        raise SeedError(
            f"cannot read the world directory {world_dir}: {err}"
        ) from err
    for entry in entries:
        if not entry.startswith(CHARACTER_PREFIX):
            continue
        if entry.endswith(COMPRESSED_SAVE_EXTENSION):
            base = entry[:-len(ZZIP_SUFFIX)]
        elif entry.endswith(SAVE_EXTENSION):
            base = entry
        else:
            continue
        candidate = os.path.join(world_dir, entry)
        try:
            info = os.lstat(candidate)
        except OSError as err:
            raise SeedError(
                f"cannot inspect the character save {candidate}: {err}"
            ) from err
        if stat.S_ISLNK(info.st_mode):
            raise SeedError(
                f"{candidate} is a symbolic link.  A character save is "
                f"a real file inside playthrough/userdir/: the engine "
                f"writes through that name, so a link would put the "
                f"save outside the committed tree")
        if not stat.S_ISREG(info.st_mode):
            continue
        names.add(base)
    return sorted(names)


# ---------------------------------------------------------------------
# THE LIVE ENGINE.
#
# The engine holds its options IN MEMORY and writes them back to
# options.json when it exits, so a seed applied underneath a running
# instance is silently overwritten on that exit -- and the run that
# applied it has already reported success.  That is not hypothetical:
# it is why launch_game.sh stops its calibration instance before
# seeding, and the failure is invisible at the time, costing a whole
# captured session whose clock came out in the compiled 12h default.
#
# So a write refuses while an AUTHENTICATED engine is using this
# userdir.  Authenticated means /proc says so -- the executable is this
# checkout's binary and the command line names this userdir -- rather
# than a name match on a process list, which any process could satisfy.
# ---------------------------------------------------------------------

GAME_BIN_NAME = "cataclysm-tiles"
ENV_GAME_BIN = "PLAYTHROUGH_GAME_BIN"
USERDIR_FLAG = "--userdir"


def engine_binary_path(root: Optional[str] = None) -> str:
    """Return this checkout's tiles binary, absolute and canonical.

    env.sh's ``$PLAYTHROUGH_GAME_BIN`` where it is set -- it is exactly
    this path -- and the repository root's own ``./cataclysm-tiles``
    otherwise, so the check works with nothing sourced.
    """
    nominated = os.environ.get(ENV_GAME_BIN, "").strip()
    if nominated:
        return os.path.realpath(nominated)
    return os.path.realpath(
        os.path.join(repo_root(root), GAME_BIN_NAME))


def proc_link(pid: int, name: str) -> Optional[str]:
    """Return a canonical ``/proc/<pid>/<name>`` target, or None.

    None for a process that has gone or that this user may not inspect;
    both are ordinary answers when scanning for a live engine.
    """
    try:
        return os.path.realpath(
            os.readlink(os.path.join("/proc", str(pid), name)))
    except OSError:
        return None


def proc_fields(pid: int, name: str) -> Tuple[str, ...]:
    """Return a NUL-separated ``/proc/<pid>/<name>`` file as fields."""
    try:
        with open(os.path.join("/proc", str(pid), name), "rb") as handle:
            raw = handle.read()
    except OSError:
        return ()
    return tuple(
        part.decode("utf-8", "replace")
        for part in raw.split(b"\x00") if part)


def userdir_of(pid: int) -> Optional[str]:
    """Return the ``--userdir`` a process was started with, canonical.

    ``--userdir <path>`` and ``--userdir=<path>`` both reach
    PATH_INFO::init_user_dir, and the value is resolved against the
    process's OWN working directory because src/path_info.cpp:105
    normalises it without absolutising it.
    """
    argv = proc_fields(pid, "cmdline")
    cwd = proc_link(pid, "cwd")
    if not argv or cwd is None:
        return None
    for position, argument in enumerate(argv):
        if argument == USERDIR_FLAG and position + 1 < len(argv):
            value = argv[position + 1]
        elif argument.startswith(USERDIR_FLAG + "="):
            value = argument[len(USERDIR_FLAG) + 1:]
        else:
            continue
        if value:
            return os.path.realpath(os.path.join(cwd, value))
    return None


def live_engine_pids(root: Optional[str] = None) -> List[int]:
    """Return every running engine using THIS userdir, authenticated.

    Read from /proc rather than from a process-name match: the check is
    that the executable is this checkout's binary AND that the command
    line names this userdir, so another checkout's engine, another
    userdir's engine and an unrelated process that merely looks like one
    are all excluded.
    """
    binary = engine_binary_path(root)
    wanted = os.path.realpath(userdir_path(root))
    found = []
    try:
        entries = os.listdir("/proc")
    except OSError as err:
        raise SeedError(
            f"cannot read /proc, so whether an engine is running "
            f"cannot be established: {err}") from err
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry, 10)
        if proc_link(pid, "exe") != binary:
            continue
        if userdir_of(pid) != wanted:
            continue
        found.append(pid)
    return sorted(found)


def assert_no_live_engine(root: Optional[str] = None) -> str:
    """Refuse to write while an engine is using this userdir.

    :returns: a sentence describing what was found, for the record.
    :raises SeedError: naming the pids, because the operator's next
        action is to stop them -- ``launch_game.sh stop``.
    """
    pids = live_engine_pids(root)
    if not pids:
        return ("no engine is running against "
                f"{relative_to_repo(userdir_path(root))}, so an option "
                f"written now is the one the next launch reads")
    raise SeedError(
        f"{len(pids)} engine process(es) "
        f"({', '.join(str(one) for one in pids)}) are running against "
        f"{relative_to_repo(userdir_path(root))}.  The engine holds its "
        f"options in memory and writes them back when it exits, so a "
        f"seed applied now would be silently overwritten -- and this "
        f"run would already have reported success.  Stop the instance "
        f"first: playthrough/tooling/launch_game.sh stop")


def relative_to_repo(path: object, root: Optional[str] = None) -> str:
    """Return ``path`` spelled relative to the repository root.

    The only form a diagnostic reports: an absolute path discloses where
    this checkout lives on the host, and these lines end up in logs.
    Mirrors manifest.relative_to_repo() and env.sh's playthrough_rel.
    """
    if path is None:
        return ""
    text = os.fspath(path) if isinstance(path, os.PathLike) else str(path)
    if not text:
        return ""
    base = repo_root(root)
    resolved = os.path.realpath(os.path.abspath(text))
    if resolved == base:
        return "."
    if resolved.startswith(base + os.sep):
        return os.path.relpath(resolved, base)
    return "<outside the checkout>/" + os.path.basename(resolved)


# ---------------------------------------------------------------------
# THE SHARED SESSION LOCK.
#
# launch_game.sh takes `playthrough_acquire_lock session` around the
# launch, and this module writes the very file that launch reads.  Two
# runs that interleave -- a seed and a launch, or two seeds -- leave the
# options file in a state neither of them reported.  The SAME lock name
# is used here so the exclusion is real rather than parallel:
# $PLAYTHROUGH_LOCK_DIR/session.lock when env.sh has been sourced, and a
# per-checkout equivalent otherwise, so the guarantee does not depend on
# a variable being set.
# ---------------------------------------------------------------------

ENV_LOCK_DIR = "PLAYTHROUGH_LOCK_DIR"
ENV_RUNTIME_DIR = "PLAYTHROUGH_RUNTIME_DIR"
ENV_XDG_RUNTIME_DIR = "XDG_RUNTIME_DIR"
SESSION_LOCK_NAME = "session.lock"
DEFAULT_LOCK_TIMEOUT = 60
ENV_LOCK_TIMEOUT = "PLAYTHROUGH_SEED_LOCK_TIMEOUT"


def _secure_scratch(path: str, label: str) -> str:
    """Create ``path`` mode 0700, refusing a link or a foreign owner."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        info = os.lstat(path)
    except OSError as err:
        raise SeedError(
            f"cannot prepare {label} at {path}: {err}") from err
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SeedError(
            f"{label} at {path} is not a real directory")
    if info.st_uid != os.getuid():
        raise SeedError(
            f"{label} at {path} is owned by uid {info.st_uid}, not by "
            f"uid {os.getuid()}")
    if info.st_mode & 0o077:
        try:
            os.chmod(path, 0o700)
        except OSError as err:
            raise SeedError(
                f"{label} at {path} is mode "
                f"{info.st_mode & 0o777:o} and could not be tightened: "
                f"{err}") from err
    return path


def session_lock_path(root: Optional[str] = None) -> str:
    """Return the lock file this module shares with the launcher."""
    nominated = os.environ.get(ENV_LOCK_DIR, "").strip()
    if nominated:
        return os.path.join(
            _secure_scratch(nominated, "the lock directory"),
            SESSION_LOCK_NAME)
    runtime = os.environ.get(ENV_RUNTIME_DIR, "").strip()
    if not runtime:
        xdg = os.environ.get(ENV_XDG_RUNTIME_DIR, "").strip()
        runtime = (os.path.join(xdg, "playthrough") if xdg
                   else f"/tmp/playthrough-{os.getuid()}")
    base = _secure_scratch(runtime, "the runtime directory")
    digest = hashlib.sha256(
        repo_root(root).encode("utf-8")).hexdigest()[:16]
    return os.path.join(
        _secure_scratch(os.path.join(base, "lock-" + digest),
                        "the lock directory"),
        SESSION_LOCK_NAME)


class SessionLock:
    """Exclusive access to the userdir's configuration, while held.

    Shared with launch_game.sh by NAME, so a launch and a seed cannot
    overlap.  Released by the kernel if the holder dies, so a crashed
    run does not wedge the next one.
    """

    def __init__(self, path: str, timeout: int) -> None:
        self._path = path
        self._timeout = int(timeout)
        self._descriptor: Optional[int] = None

    @property
    def held(self) -> bool:
        """True while this process holds the lock."""
        return self._descriptor is not None

    def acquire(self) -> None:
        """Take the lock, waiting at most the configured timeout."""
        if self._descriptor is not None:
            return
        try:
            descriptor = os.open(
                self._path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600)
        except OSError as err:
            raise SeedError(
                f"cannot open the session lock {self._path}: {err}"
            ) from err
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._descriptor = descriptor
                return
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise SeedError(
                        f"another run has held the session lock "
                        f"{self._path} for more than {self._timeout}s.  "
                        f"A launch and a seed over one userdir would "
                        f"leave the options file in a state neither "
                        f"reported, so this one stops rather than "
                        f"racing it")
                time.sleep(0.05)

    def release(self) -> None:
        """Release the lock and close its descriptor."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass

    def __enter__(self) -> "SessionLock":
        """Support `with SessionLock(...):`."""
        self.acquire()
        return self

    def __exit__(self, kind: object, value: object,
                 trace: object) -> bool:
        """Release the lock however the block ended."""
        self.release()
        return False


def _validated_target(path: str, root: Optional[str] = None) -> str:
    """Return ``path`` as an absolute path this module may write.

    Five conditions must hold, and together they make a write outside
    the engine's own configuration impossible rather than merely
    unlikely:

    1. the basename is ``options.json`` or ``worldoptions.json`` --
       the only two files the engine keeps option values in;
    2. the path resolves INSIDE the pipeline's userdir
       [playthrough/userdir], the tree the engine owns and this
       pipeline commits;
    3. it sits exactly where the engine puts it: ``options.json``
       directly in ``<userdir>/config`` ``[src/path_info.cpp:164,167]``
       and ``worldoptions.json`` directly in a world directory under
       ``<userdir>/save`` ``[src/path_info.cpp:144]``;
    4. no component below the userdir is a symbolic link, and the
       target itself is not one;
    5. the file already EXISTS, because this module patches what the
       engine wrote and never creates a configuration document.

    :func:`load_entries` then requires it to parse as an engine-shaped
    option array before any write is attempted.

    Conditions 2 to 4 are the ones that matter for anything but a typo.
    A basename check alone accepts ANY writable ``options.json`` on the
    host -- another checkout's, another user's, one planted in a
    world-writable directory -- and accepts a symlink wearing the right
    name while pointing somewhere else entirely.  A caller-supplied
    ``--options`` path, or an unexpected
    ``$PLAYTHROUGH_OPTIONS_JSON``, is exactly how that would happen,
    so both are confined here rather than trusted.  Condition 4 is a
    REFUSAL rather than a resolution for a reason worth stating: a
    link planted at ``save/<World>`` that was followed would make
    whatever it points at writable, which is the escape this function
    exists to close.  Position inside a tree this module can vouch for
    is what makes the authorisation real.

    :raises SeedError: when the basename is not writable by this
        module, when the path is outside or misplaced within the
        userdir, when any component is a link, or when the file does
        not exist.
    """
    resolved = os.path.abspath(os.path.normpath(path))
    name = os.path.basename(resolved)
    if name not in WRITABLE_NAMES:
        raise SeedError(
            f"refusing to write '{resolved}': this module only ever "
            f"writes {' or '.join(WRITABLE_NAMES)}, and the basename "
            f"is '{name}'")
    approved = approved_userdir(root)
    _confined(resolved, approved, "the options file")
    parent = os.path.dirname(os.path.realpath(resolved))
    config_dir = os.path.realpath(_join(approved, ("config",)))
    save_dir = os.path.realpath(_join(approved, ("save",)))
    if name == OPTIONS_NAME:
        if parent != config_dir:
            raise SeedError(
                f"refusing to write '{resolved}': the engine keeps "
                f"{OPTIONS_NAME} in '{config_dir}' "
                f"[src/path_info.cpp:164,167], and this one is in "
                f"'{parent}'")
    elif os.path.dirname(parent) != save_dir:
        raise SeedError(
            f"refusing to write '{resolved}': the engine keeps "
            f"{WORLD_OPTIONS_NAME} in a world directory directly "
            f"under '{save_dir}' [src/path_info.cpp:144], and this "
            f"one is in '{parent}'")
    if not os.path.isfile(resolved):
        raise SeedError(
            f"no options file at '{resolved}'.  The engine writes it "
            f"on its first launch, so run "
            f"playthrough/tooling/launch_game.sh first; this module "
            f"patches the file the game wrote and deliberately never "
            f"creates one from scratch")
    # A symlink AT the target is refused outright rather than followed:
    # even a link that currently points somewhere permitted is a
    # standing invitation to be repointed between this check and the
    # write.
    if os.path.islink(resolved):
        raise SeedError(
            f"refusing to write '{resolved}': it is a symbolic link, "
            f"and this module rewrites the file it opens.  Replace it "
            f"with the engine's own regular file")
    # The name is re-checked AFTER resolution.  The positional check
    # above proves the real parent, and this proves the real leaf: a
    # link named options.json pointing at a file called something else
    # would otherwise satisfy every check while rewriting that file.
    real = os.path.realpath(resolved)
    if os.path.basename(real) != name:
        raise SeedError(
            f"refusing to write '{path}': it resolves to '{real}', "
            f"whose name differs from '{name}'")
    return real


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
    [playthrough/tooling/launch_game.sh, install_tileset_from_pack].
    """
    for tileset in tilesets:
        if tileset.ident == wanted or tileset.view == wanted:
            return tileset
    return None


def _required_aliases(required: str) -> List[str]:
    """Return every spelling the required tileset may be known by.

    ``$PLAYTHROUGH_TILESET_ALIASES`` is honoured when it is set, so the
    list lives in one place -- ``env.sh`` -- rather than being
    maintained twice.  The requested id always comes first, and the
    module's own constants are the floor, so an environment that
    supplies nothing still resolves the pack correctly.

    The pack genuinely is spelled several ways -- the ``NAME:`` id, the
    ``VIEW:`` display name and the directory the upstream repository
    ships it as -- so matching on one spelling alone would fail to find
    an installed pack and report it as absent.
    """
    aliases = [required]
    from_env = os.environ.get(ENV_TILESET_ALIASES) or ""
    for name in from_env.split():
        if name and name not in aliases:
            aliases.append(name)
    for name in TILESET_REQUIRED_ALIASES:
        if name not in aliases:
            aliases.append(name)
    return aliases


def _is_required(tileset: Tileset, wanted: str) -> bool:
    """True when ``tileset`` IS the MSXotto+ pack the run requires.

    Asked through :func:`_required_aliases` rather than against a
    literal, so the id, the display name and every directory spelling
    are accepted from the ONE list ``env.sh`` owns.  Used to decide
    whether an explicitly requested tileset is the required pack under
    another of its names or a genuine substitution.
    """
    names = set(_required_aliases(wanted))
    return tileset.ident in names or tileset.view in names


def _fallback_allowed(explicit: Optional[bool] = None) -> bool:
    """True when the ASCII fallback tileset may be written.

    ``False`` unless the caller says otherwise, because the pipeline's
    requirement names the MSXotto+ pack specifically.  The opt-in is
    the ``allow_fallback`` argument, ``--allow-tileset-fallback`` on
    the command line, or ``$PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1`` --
    the same variable ``launch_game.sh`` reads, so one setting governs
    the whole pipeline.  Note what is NOT an opt-in:
    ``$PLAYTHROUGH_TILESET_FALLBACK`` only NAMES the substitute, and
    setting it alone changes nothing.
    """
    if explicit is not None:
        return bool(explicit)
    return os.environ.get(ENV_ALLOW_TILESET_FALLBACK, "") == "1"


def resolve_tileset(
    root: Optional[str] = None,
    requested: Optional[str] = None,
    required: Optional[str] = None,
    tilesets: Optional[Sequence[Tileset]] = None,
    allow_fallback: Optional[bool] = None,
) -> TilesetChoice:
    """Resolve the ONE tileset this pipeline is allowed to write.

    Order:

    1. ``requested`` -- an explicit ``--tileset`` argument, or
       ``$PLAYTHROUGH_TILESET_RESOLVED`` as emitted by
       ``launch_game.sh``.  It is treated as a HINT and validated
       independently: the launcher and this module must agree, and if
       they do not, the installed set decides.
    2. ``required`` -- the MSXotto+ pack, asked for by every name it
       goes by, defaulting to ``$PLAYTHROUGH_TILESET``
       [playthrough/tooling/env.sh].
    3. ``fallback`` -- the checkout's own ``ASCIITiles``, defaulting to
       ``$PLAYTHROUGH_TILESET_FALLBACK``
       [playthrough/tooling/env.sh] -- and ONLY when the caller
       has explicitly allowed it.

    STEP 3 IS OPT-IN, AND OFF BY DEFAULT.  The requirement is not
    "some tileset": the game must be configured to use MSXotto+.
    Quietly writing ``ASCIITiles`` instead produced a run that looked
    entirely successful -- every count tallied, every frame was
    captured -- while recording a session in the wrong tileset, which
    is precisely the kind of silent substitution this pipeline is built
    to refuse.  ``launch_game.sh`` hydrates the pack from its
    pre-placed copy before this module runs, so reaching step 3 at all
    means the pack is genuinely unavailable; the remedy is to install
    it with ``playthrough/tooling/launch_game.sh tileset``, not to
    substitute for it.  When the substitution IS asked for by name it
    is recorded in the report's notes and on stderr, so a diagnostic
    run cannot be mistaken for a compliant one.

    :param allow_fallback: ``True`` to accept the ASCII fallback,
        ``False`` to refuse it, ``None`` to read
        ``$PLAYTHROUGH_ALLOW_TILESET_FALLBACK``.
    :raises SeedError: when the hint is not installed, when the
        required tileset is not installed and the fallback has not been
        allowed, and when nothing usable is installed at all.  Writing
        an id that is not installed would leave the game with a tileset
        it cannot load, and claiming otherwise in the run's notes would
        be a fabrication.
    """
    available = (list(tilesets) if tilesets is not None
                 else discover_tilesets(root))
    installed = tuple(item.ident for item in available)
    wanted = required or os.environ.get(ENV_TILESET) or TILESET_REQUIRED
    fallback = (os.environ.get(ENV_TILESET_FALLBACK) or
                TILESET_FALLBACK)
    hint = requested or os.environ.get(ENV_TILESET_RESOLVED) or ""

    if hint:
        match = _match_tileset(available, hint)
        if match is not None:
            if not _is_required(match, wanted) and \
                    not _fallback_allowed(allow_fallback):
                raise SeedError(
                    f"'{hint}' was requested, but it is not the "
                    f"required '{wanted}' (MSXotto+) and the "
                    f"substitution was not allowed.  Recording the "
                    f"session in another tileset while every check "
                    f"passed is exactly the silent substitution this "
                    f"module refuses: pass --allow-tileset-fallback or "
                    f"set ${ENV_ALLOW_TILESET_FALLBACK}=1 to ask for "
                    f"it deliberately")
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
            f"tracked), or drop the request so the required "
            f"'{wanted}' is used")

    for alias in _required_aliases(wanted):
        match = _match_tileset(available, alias)
        if match is not None:
            return TilesetChoice(
                tileset=match,
                origin="required",
                reason=(
                    f"the required tileset is installed at "
                    f"{match.directory} (matched on '{alias}')"),
                installed=installed)

    if not _fallback_allowed(allow_fallback):
        raise SeedError(
            f"the required tileset '{wanted}' (MSXotto+) is not "
            f"installed, so there is nothing honest to write to "
            f"{OPT_TILES}.  Installed ids: "
            f"{', '.join(installed) or '(none)'}.  Run "
            f"'playthrough/tooling/launch_game.sh tileset' to hydrate "
            f"it from the pre-placed pack (gfx/ is git-ignored by "
            f".gitignore:52, so installing it changes nothing "
            f"tracked).  Ids come from the NAME: field of each "
            f"gfx/*/tileset.txt, never from the directory name.  "
            f"Falling back to '{fallback}' would render a plausible "
            f"film while failing the requirement to configure "
            f"MSXotto+, with no symptom but the artwork, so it is "
            f"refused unless it is asked for explicitly: pass "
            f"--allow-tileset-fallback or set "
            f"${ENV_ALLOW_TILESET_FALLBACK}=1 for a diagnostic run")

    match = _match_tileset(available, fallback)
    if match is not None:
        return TilesetChoice(
            tileset=match,
            origin="fallback",
            reason=(
                f"the required tileset ({wanted}) is not installed and "
                f"the fallback was explicitly allowed, so the "
                f"checkout's own {match.ident} is used instead -- this "
                f"is a DIAGNOSTIC configuration and does not satisfy "
                f"the requirement"),
            installed=installed)

    raise SeedError(
        f"the required tileset '{wanted}' is not installed, and there "
        f"is deliberately no fallback: a run that quietly used the "
        f"checkout's own ASCIITiles would render a plausible film "
        f"while failing the requirement to configure MSXotto+, with "
        f"no symptom but the artwork.  Installed ids: "
        f"{', '.join(installed) or '(none)'}.  Run "
        f"'playthrough/tooling/launch_game.sh tileset' to hydrate it "
        f"from the pre-placed pack.  Ids come from the NAME: field of "
        f"each gfx/*/tileset.txt, never from the directory name")


# ---------------------------------------------------------------------
# Reading and writing the engine's option documents
# ---------------------------------------------------------------------
def _read_text(path: str) -> str:
    """Return a file's exact text, or raise SeedError.

    Separate from :func:`load_entries` because the rollback in
    :func:`_commit_writes` restores the ORIGINAL BYTES rather than a
    re-serialisation of the parsed values: those two differ in
    whitespace, and "the file is exactly as you found it" is a claim
    worth being literally true.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as err:
        raise SeedError(f"cannot read {path}: {err}") from err


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
            f"file to a JsonArray [src/options.cpp:4197-4202], so a "
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
        "240 columns x 8 px = the 1920 px render grid width the capture "
        "geometry assumes [src/sdltiles.cpp:595-596]"),
    OPT_TERMINAL_Y: (
        "67 rows x 16 px = 1072 px, the render grid height inside "
        "the 1920x1080 X root [src/sdltiles.cpp:595-596]"),
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
    [src/options.cpp:4080-4102], so a duplicate later in the file
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
            f"{name} appears {len(occurrences)} times in {path} with "
            f"the values "
            f"{', '.join(repr(str(e['value'])) for e in occurrences)}; "
            f"every occurrence is being set, and the LAST one "
            f"({str(occurrences[-1]['value'])!r}) is what the engine "
            f"was actually using, because it applies them in order",
            notes)

    # The value the ENGINE was using is the last occurrence's, since it
    # applies them in order and each assignment overwrites the previous
    # one.  Reporting the first occurrence's value as "before" would
    # describe a state the game never had -- a small fabrication, and
    # exactly the kind that makes a change log untrustworthy.
    effective_before = str(occurrences[-1]["value"])
    changed = False
    for entry in occurrences:
        if str(entry["value"]) != wanted:
            entry["value"] = wanted
            changed = True
    if not changed:
        already.append(name)
        LOG.debug("%s already holds %r", name, wanted)
        return
    changes.append(
        Change(name=name, before=effective_before, after=wanted,
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
    allow_tileset_fallback: Optional[bool] = None,
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
        the engine wrote it and no tileset discovery is performed --
        for a caller patching a COPY of the file on a host with no
        ``gfx/`` tree.  CALL-SITE ONLY: :func:`build_parser` exposes no
        flag that sets it, so no command line and therefore no
        pipeline stage can drop ``TILES`` out of the plan.  A
        production run always decides all eight values.
    :param worlds: what to do about an existing world's
        ``worldoptions.json`` -- ``"auto"`` reports but does not touch
        it, ``"patch"`` edits it, ``"skip"`` ignores it entirely.
    :param dry_run: compute and report everything, write nothing.
    :param allow_tileset_fallback: ``True`` to accept a tileset other
        than MSXotto+, ``False`` to refuse one, ``None`` to read
        ``$PLAYTHROUGH_ALLOW_TILESET_FALLBACK``.  Refused by default:
        see :func:`resolve_tileset`.

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

    target = _validated_target(path or options_json_path(root), root)
    # The file's exact bytes, kept for the rollback in _commit_writes:
    # "left exactly as it was found" has to mean the original text, not
    # a re-serialisation of it.
    original = _read_text(target)
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
            root=root, requested=tileset,
            allow_fallback=allow_tileset_fallback)
        if report.tileset.origin != "required":
            # An operator-nominated tileset, and a deliberately allowed
            # fallback, are both deviations from the required pack, so
            # each is recorded in the report's notes rather than merely
            # logged.
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

    # ------------------------------------------------------------------
    # PREFLIGHT EVERYTHING, THEN WRITE.  Nothing above this point has
    # touched the disk: the global file's new content is computed in
    # memory, and _plan_worlds() below validates and computes every
    # world file's new content the same way -- resolving each target
    # under the confinement rules, loading it, and raising for anything
    # it cannot do honestly.
    #
    # The old sequence wrote the global options file first and only then
    # looked at the worlds, so a world that could not be patched left
    # the configuration half-applied: the global file already carried
    # 24_HOUR=24h and the new tileset while the world still carried a
    # point-pool setting that makes the creator's pool tab read-only,
    # and the run had failed, so nobody had been told which half had
    # landed.  Recovering from that means knowing what the file used to
    # say, which is precisely what an aborted run does not record.
    #
    # So the writes happen together, last, and if any one of them fails
    # the ones already made are restored from the bytes they had before.
    # ------------------------------------------------------------------
    planned: List[_PlannedWrite] = []
    if report.changes:
        planned.append(_PlannedWrite(
            target=target,
            text=serialize_entries(entries, pretty),
            original=original,
            label="the global options file",
            plan=tuple(plan)))
    planned.extend(
        _plan_worlds(report, root, wanted_pools, worlds,
                     dry_run))

    if not planned:
        LOG.debug("%s already held every seeded value, and no world "
                  "needed a change", target)
        return report
    if dry_run:
        _note(
            f"dry run: {len(report.changes) + len(report.world_changes)}"
            f" change(s) computed across {len(planned)} file(s), none "
            f"written",
            notes)
        return report

    # THE WRITE HAPPENS UNDER THE SHARED SESSION LOCK, AND ONLY WITH NO
    # ENGINE RUNNING.  Both conditions exist because a successful report
    # from this function is otherwise not a statement about the file:
    # the engine holds its options in memory and writes them back when it
    # exits, so a seed applied underneath a live instance is silently
    # overwritten afterwards, and a launch racing this write reads
    # whichever half landed first.  The live-engine check is re-taken
    # INSIDE the lock, so a launch cannot start between the check and the
    # write -- it would have to take the same lock to do so.
    with SessionLock(
            session_lock_path(root),
            _lock_timeout()) as lock:
        assert lock.held, "the session lock was not taken"
        _note(assert_no_live_engine(root), notes)
        _commit_writes(planned, report, root)
        # And re-asserted afterwards, because "no engine was running
        # when this began" is not the claim being made -- the claim is
        # that the bytes now on disk are the ones the next launch reads.
        _note(assert_no_live_engine(root), notes)
    return report


def _lock_timeout() -> int:
    """Return how long to wait for the shared session lock."""
    raw = os.environ.get(ENV_LOCK_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_LOCK_TIMEOUT
    if not raw.isdigit():
        raise SeedError(
            f"${ENV_LOCK_TIMEOUT} is {raw!r}, which is not a whole "
            f"number of seconds")
    seconds = int(raw, 10)
    if not 1 <= seconds <= 3600:
        raise SeedError(
            f"${ENV_LOCK_TIMEOUT} is {seconds}, outside 1-3600 seconds")
    return seconds


@dataclass(frozen=True)
class _PlannedWrite:
    """One file's fully computed new content, not yet written.

    ``original`` is the exact text the file held when it was read, kept
    so that a failure part-way through a multi-file commit can put every
    already-written file back the way it was.  ``plan`` is the
    name/value pairs to confirm afterwards, empty for a world file whose
    single change is confirmed directly.
    """

    target: str
    text: str
    original: str
    label: str
    plan: Tuple[Tuple[str, str], ...] = ()


def _commit_writes(
    planned: Sequence[_PlannedWrite],
    report: SeedReport,
    root: Optional[str] = None,
) -> None:
    """Write every planned file, or restore the ones already written.

    Each individual write is atomic already (:func:`write_atomic`
    renames into place), so the only failure this has to handle is a
    write that succeeds followed by one that does not.  In that case
    every file written by this call is put back to the bytes it held
    before, in reverse order, and the original error is re-raised: the
    configuration is then exactly as it was found, which is a state the
    operator can reason about.

    A rollback write that itself fails is reported at ERROR with the
    path and the content that could not be restored, because at that
    point the module genuinely cannot fix it and saying so is the only
    honest thing left to do.

    :raises SeedError: the first write failure, after rolling back.
    """
    written: List[_PlannedWrite] = []
    for item in planned:
        try:
            write_atomic(item.target, item.text)
        except SeedError as err:
            if written:
                LOG.error(
                    "failed to write %s (%s); restoring %d file(s) "
                    "already written so the configuration is left "
                    "exactly as it was found",
                    item.label, err, len(written))
                _rollback_writes(written)
            raise
        written.append(item)
        if item.plan:
            report.written = True
        LOG.debug("wrote %s (%s)", item.label, item.target)

    # Confirmation happens only once every write has landed, so a
    # confirmation failure cannot be mistaken for a partial write.
    for item in written:
        if item.plan:
            _confirm_written(item.target, item.plan, root)
    if report.world_changes:
        _confirm_world_writes(report, root)


def _rollback_writes(written: Sequence[_PlannedWrite]) -> None:
    """Restore each already-written file to its original bytes."""
    for item in reversed(written):
        try:
            write_atomic(item.target, item.original)
            LOG.warning("restored %s to its previous content (%s)",
                        item.label, item.target)
        except SeedError as err:
            LOG.error(
                "could not restore %s at %s (%s).  That file now holds "
                "this run's partial change and must be repaired by "
                "hand or regenerated by the engine",
                item.label, item.target, err)


def _confirm_world_writes(
    report: SeedReport,
    root: Optional[str],
) -> None:
    """Prove every world change actually reached the disk.

    The same argument as :func:`_confirm_written`: reporting a change
    that did not take effect would be a fabrication, and a world file is
    no less load-bearing than the global one -- it is what decides
    whether the character creator's pool tab is live or read-only.

    :raises SeedError: when a recorded world change is not on disk.
    """
    problems = []
    for change in report.world_changes:
        if change.path is None:
            continue
        observed = read_values(change.path, root)
        actual = observed.get(change.name)
        if actual != change.after:
            problems.append(
                f"{change.path} reads {change.name} back as "
                f"{actual!r}, not {change.after!r}")
    if problems:
        raise SeedError(
            "a world write did not take effect:\n  - " +
            "\n  - ".join(problems))


def _confirm_written(
    target: str,
    plan: Sequence[Tuple[str, str]],
    root: Optional[str] = None,
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
    observed = read_values(target, root)
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


def _plan_worlds(
    report: SeedReport,
    root: Optional[str],
    point_pools: str,
    mode: str,
    dry_run: bool = False,
) -> List["_PlannedWrite"]:
    """Preflight existing worlds and RETURN their planned writes.

    Nothing here touches the disk.  Every world target is resolved
    under the confinement rules, loaded, and checked; the new content is
    computed in memory and handed back so that :func:`patch` can commit
    the global file and the world files together, or neither.  A
    condition this cannot handle honestly -- ``--worlds patch`` against
    a world that carries no such entry -- still raises here, BEFORE any
    write has happened, which is the whole point of preflighting.

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
    planned: List[_PlannedWrite] = []
    if mode == WORLDS_SKIP:
        report.notes.append(
            "existing world options were not inspected "
            "(--worlds skip)")
        return planned

    paths = world_options_paths(root)
    if not paths:
        report.notes.append(
            f"no world exists yet, so the new world will inherit "
            f"{OPT_POINT_POOLS}='{point_pools}' from the seeded "
            f"global world defaults "
            f"[src/worldfactory.cpp:2039]")
        return planned

    session_mode = os.environ.get(ENV_SESSION_MODE, "")
    # A RESUMED SESSION MAY NOT RESHAPE THE WORLD IT RESUMES.  The hard
    # rule is that an existing save is CONTINUED rather than replaced,
    # and rewriting that world's CHARACTER_POINT_POOLS is a change to the
    # rules the survivor already lives under -- applied behind the back
    # of a session whose whole claim is that it continued what it found.
    # `--worlds patch` was an unconditional opt-in, so the refusal is
    # placed here, once, ahead of every world.
    if mode == WORLDS_PATCH and session_mode == SESSION_MODE_RESUME:
        raise SeedError(
            f"--worlds patch is refused because ${ENV_SESSION_MODE} is "
            f"'{SESSION_MODE_RESUME}': a resumed session continues the "
            f"save it found and does not rewrite that world's options. "
            f"Seed world defaults BEFORE the first world is created, "
            f"where they are inherited [src/worldfactory.cpp:2039], or "
            f"re-run without --worlds patch to report the world's "
            f"current value and change nothing")
    for world_path in paths:
        world_name = os.path.basename(os.path.dirname(world_path))
        # THE SAME REFUSAL FROM THE EVIDENCE SIDE.  The declaration above
        # can be absent -- nothing forces $PLAYTHROUGH_SESSION_MODE to be
        # exported -- so the save tree is asked directly: a world holding
        # a character save is a world somebody is playing, whatever any
        # variable says.  A world with NO character save is the
        # interrupted-creation case, and patching that is exactly what
        # the mode is for.
        if mode == WORLDS_PATCH:
            survivors = character_saves_in(os.path.dirname(world_path))
            if survivors:
                raise SeedError(
                    f"--worlds patch is refused for world "
                    f"'{world_name}': it holds "
                    f"{len(survivors)} character save(s) "
                    f"({', '.join(survivors)}), so a survivor already "
                    f"exists there and an existing save is continued, "
                    f"never reshaped.  Rewriting "
                    f"{OPT_POINT_POOLS} would change the rules that "
                    f"character was created under.  Only a world with "
                    f"no character save -- a run interrupted during "
                    f"creation -- may be patched")
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

        # The LAST occurrence, not the first.  A world options file may
        # legally carry the same key twice, and the engine deserialises
        # the array in order -- each assignment overwriting the one
        # before it -- so the final occurrence is the value the game is
        # actually running under.  Reading occurrences[0] would report
        # a value the world does not have, and would then decide
        # "point-buy is available" (or not) from it: a wrong answer to
        # the one question this branch exists to answer.
        current = str(occurrences[-1]["value"])
        if len(occurrences) > 1:
            _note(
                f"world '{world_name}' declares {OPT_POINT_POOLS} "
                f"{len(occurrences)} times in {world_path} with the "
                f"values "
                f"{', '.join(repr(str(e['value'])) for e in occurrences)}"
                f"; the engine applies them in order, so the "
                f"effective value is the last one, '{current}', which "
                f"is what is reported below",
                report.notes)
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
        world_target = _validated_target(world_path, root)
        original = _read_text(world_target)
        changes: List[Change] = []
        already: List[str] = []
        _apply(grouped, OPT_POINT_POOLS, point_pools, world_target,
               changes, already, report.notes)
        if not changes:
            report.notes.append(
                f"world '{world_name}' already held "
                f"{OPT_POINT_POOLS}='{point_pools}'")
            continue
        # The change is recorded with the file it belongs to, so
        # _confirm_world_writes can prove it landed there.
        located = [
            Change(name=change.name, before=change.before,
                   after=change.after, reason=change.reason,
                   path=world_target)
            for change in changes]
        report.world_changes.extend(located)
        report.notes.append(
            f"world '{world_name}': {located[0]} in {world_target}"
            f"{' -- dry run, nothing written' if dry_run else ''}")
        if dry_run:
            report.notes.append(
                f"world '{world_name}' would change: "
                f"{OPT_POINT_POOLS} -> '{point_pools}' in "
                f"{world_target}")
        planned.append(_PlannedWrite(
            target=world_target,
            text=serialize_entries(entries, pretty),
            original=original,
            label=f"world '{world_name}'"))
    return planned


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
    target = _validated_target(path or options_json_path(root), root)
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
    allow_tileset_fallback: Optional[bool] = None,
) -> Dict[str, str]:
    """Read the options file back and assert every seeded value.

    :param tileset: the id that should be present.  When ``None`` the
        stored value is instead checked against what is installed,
        which is the stronger check of the two whenever ``gfx/`` is
        reachable.
    :param require_installed: when ``True``, the stored ``TILES`` value
        must name an installed tileset AND, unless the fallback is
        allowed, must be the MSXotto+ pack the run requires.  Set
        ``False`` only when verifying a copy of the file away from a
        ``gfx/`` tree.  CALL-SITE ONLY: :func:`build_parser` exposes no
        flag that sets it, so every command-line verification -- and so
        every production verification -- makes the strong check.
    :param allow_tileset_fallback: ``True`` to accept a stored tileset
        other than MSXotto+, ``None`` to read
        ``$PLAYTHROUGH_ALLOW_TILESET_FALLBACK``.
    :returns: the observed values of every seeded option.
    :raises SeedError: listing every mismatch found, so one run
        reports all of them rather than one at a time.
    """
    target = _validated_target(path or options_json_path(root), root)
    # `root` is forwarded, not dropped: read_values confines its own
    # target too, and a reader that fell back to the module's checkout
    # would refuse the very file this function just authorised.
    observed = read_values(target, root)

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
        available = discover_tilesets(root)
        installed = [item.ident for item in available]
        if stored_tiles not in installed:
            problems.append(
                f"{OPT_TILES} is {stored_tiles!r}, which is not "
                f"installed; installed ids: "
                f"{', '.join(installed) or '(none)'}")
        elif not _fallback_allowed(allow_tileset_fallback):
            # Installed is not the same as required.  The run has to be
            # recorded in MSXotto+, so a stored id that is merely
            # present -- ASCIITiles, say -- is reported here rather
            # than passing verification and being discovered in the
            # finished movie.
            match = _match_tileset(available, stored_tiles)
            wanted = os.environ.get(ENV_TILESET) or TILESET_REQUIRED
            if match is not None and not _is_required(match, wanted):
                problems.append(
                    f"{OPT_TILES} is {stored_tiles!r}, but the run "
                    f"requires {wanted!r} (MSXotto+).  Install it with "
                    f"`playthrough/tooling/launch_game.sh tileset`, or "
                    f"pass --allow-tileset-fallback / set "
                    f"${ENV_ALLOW_TILESET_FALLBACK}=1 to accept "
                    f"another tileset deliberately")

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
             f"launch_game.sh, then the required "
             f"'{TILESET_REQUIRED}'.  An uninstalled tileset is an "
             f"error, never a substitution")
    # THERE IS DELIBERATELY NO --no-tileset FLAG.
    #
    # It used to exist, and it was a production bypass: it dropped
    # TILES out of the plan -- eight decided values became seven -- and
    # it turned off the verifier's installed-tileset check, so a run
    # could report complete success with ASCIITiles, or the absent
    # compiled default UltimateCataclysm, left in place.  The run is
    # required to be recorded in MSXotto+, and a flag that quietly
    # removes the only check of that is worse than no check at all,
    # because every other gate still passes.
    #
    # `patch(resolve_tiles=False)` and `verify(require_installed=False)`
    # remain as call-site-only parameters, for a caller holding these
    # rules against a copy of an options file on a host with no gfx/
    # tree.  argparse cannot produce either of them, so no command line
    # -- and therefore no pipeline stage -- can reach the relaxed
    # behaviour.  The one sanctioned way to record a session in another
    # tileset is --allow-tileset-fallback, which announces itself in
    # the report and on stderr.
    parser.add_argument(
        "--allow-tileset-fallback", dest="allow_tileset_fallback",
        action="store_true", default=None,
        help=f"accept a tileset other than '{TILESET_REQUIRED}' "
             f"(MSXotto+) -- for instance the checkout's own "
             f"'{TILESET_FALLBACK}'.  Refused by default, because the "
             f"run is required to be recorded in MSXotto+ and a silent "
             f"substitution would pass every other check.  Equivalent "
             f"to ${ENV_ALLOW_TILESET_FALLBACK}=1")
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
    [playthrough/tooling/launch_game.sh, EX_LAYOUT], so the resolved
    tileset and the change count can be read with ``grep '^KEY='``.
    """
    sys.stdout.write(f"{key}={value}\n")


def _report_stdout(report: SeedReport,
                   observed: Dict[str, str]) -> None:
    """Emit the machine-readable summary of one run.

    THE PATH IS REPORTED RELATIVE, like every other path this module
    prints.  An absolute one discloses where this checkout lives on the
    host, and these lines are captured into logs and quoted into
    reports; the relative form is what a reader would type and is the
    same rule playthrough_rel applies in the shell and
    manifest.relative_to_repo applies in the other Python stages.  This
    was the last summary emitter still printing the full path.
    """
    _emit("PLAYTHROUGH_OPTIONS_JSON", relative_to_repo(report.path))
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
            # require_installed is not passed and not exposed: every
            # command-line path takes the default True, so verification
            # always asserts that TILES names an INSTALLED tileset and,
            # unless the fallback was deliberately allowed, that it is
            # the MSXotto+ pack the run requires.
            observed = verify(
                path,
                root=args.repo_root,
                tileset=args.tileset,
                terminal_x=args.terminal_x,
                terminal_y=args.terminal_y,
                point_pools=args.point_pools,
                world_compression=args.world_compression,
                allow_tileset_fallback=args.allow_tileset_fallback)
            report = SeedReport(path=os.path.abspath(path))
            report.already.extend(sorted(observed))
            report.notes.append(
                "verify-only: nothing was written")
        else:
            # resolve_tiles is likewise not passed and not exposed, so
            # TILES is always in the plan and all eight values are
            # decided on every command-line run.
            report = patch(
                path=args.options_json,
                root=args.repo_root,
                tileset=args.tileset,
                terminal_x=args.terminal_x,
                terminal_y=args.terminal_y,
                point_pools=args.point_pools,
                world_compression=args.world_compression,
                worlds=args.worlds,
                dry_run=args.dry_run,
                allow_tileset_fallback=args.allow_tileset_fallback)
            if args.dry_run:
                # A dry run must not assert values it deliberately did
                # not write; it reports what the file actually holds
                # and lets --explain list what would change.
                observed = read_values(report.path, args.repo_root)
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
                    allow_tileset_fallback=(
                        args.allow_tileset_fallback))
    except SeedError as err:
        LOG.error("%s", err)
        return 1

    if args.explain:
        sys.stderr.write(report.describe() + "\n")
    _report_stdout(report, observed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
