#!/usr/bin/env python3
"""The atomic keystroke step, and the SOLE owner of the frame counter.

ONE KEY, ONE PNG, ONE ROW.  :meth:`Session.step` focuses the game
window by class, sends exactly one keystroke, lets capture.sh settle
and photograph the screen, reads the sidebar clock out of those pixels
and appends exactly one manifest row.  It is the only place in this
pipeline where the frame counter moves, and it moves once per call.

THE INVARIANT IS STRUCTURAL, NOT MERELY INTENDED.  The index is
computed here, handed to capture.sh, and used to build the manifest
row's `file` field through manifest.frame_file(), so a frame with no
row and a row with no frame are both impossible without editing this
one function:

    focus the window by class
      -> send EXACTLY ONE key with `xdotool key --window <id>`
        -> settle, then capture EXACTLY ONE PNG (capture.sh)
          -> read the clock (ocr_clock.py, via capture.sh)
            -> append EXACTLY ONE manifest row (manifest.py)

Nothing here loops over keys.  There is deliberately NO helper that
takes a list of keystrokes: the operational directive is observe ->
decide in character -> act -> capture -> log, and a batching
convenience is precisely how that becomes blind key-spam.  A UI that
needs four keystrokes is four calls, four frames, four rows and four
transcript entries -- which is what "exactly one screenshot after
every single key press" means.

WHY A FAILED STEP POISONS THE SESSION.  A keystroke is not undoable.
Once xdotool has delivered it the engine has already acted, so a
capture or a record failure after that point leaves a keystroke with
no frame, and no retry can put the game back.  Rather than continue
and quietly break the frame-to-row identity that verify_artifacts.sh
asserts, the session is marked aborted and every later step refuses.
A key REFUSED before anything is sent is the opposite case: nothing
happened, so the session stays usable.

THE COUNTER IS RECOVERED FROM THE MANIFEST, NEVER FROM A DIRECTORY.
manifest.last_recorded_frame() is the append-only record of what was
captured; counting PNGs would be a second source of truth that a
retry could silently renumber.  The frames directory is still read --
but only to CHECK that it agrees with the manifest, and a
disagreement stops the session instead of being reconciled.

THE CLOCK MAY BE UNREADABLE, AND THAT IS RECORDED AS SUCH.
`ingame_clock` is the honesty field: display::time_string() returns an
exact time only when the survivor has a watch
(src/display.cpp:207-218), otherwise a coarse phrase from
display::time_approx() (src/display.cpp:159-185), otherwise "???".
Whatever the frame showed is recorded verbatim, an empty reading is
recorded as JSON null, and nothing is ever interpolated, carried
forward from the previous frame or guessed.

WHAT IS BEING KEYED IS THE SDL TILES BUILD, AND IT CANNOT BE ANYTHING
ELSE.  The window class this module searches for is the tiles binary's
own -- `cataclysm-tiles`, which self-reports "+tiles, +sound" -- and the
curses build creates no X window at all, so it is not merely forbidden
here but unreachable: there is nothing for `xdotool search --class` to
find and nothing for `import -window root` to photograph.

WINDOW TARGETING IS BY CLASS, AND ONLY BY CLASS.
`xdotool search --class cataclysm-tiles` finds this window;
`xdotool search --name 'Cataclysm'` returns EMPTY for it even though
`xwininfo -root -children` lists it with the title "Cataclysm: Dark
Days Ahead - <hash>".  Scraping an id out of xwininfo with a loose
hexadecimal pattern is actively unsafe, because the geometry substring
xwininfo prints mis-matches such patterns.  A window id supplied by
launch_game.sh (PLAYTHROUGH_WINDOW_ID) is accepted but RE-VERIFIED
against that class search before every keystroke: if the window has
gone, the game crashed or exited and the session stops.

THE SAVE-RESUME PRE-FLIGHT IS MANDATORY.  :func:`probe_save_resume`
inspects playthrough/userdir/save/*/ BEFORE anything could create a
character, because an existing save must be CONTINUED rather than
replaced.  A fresh checkout has no save at all, so this run creates a
character -- and the resume branch is implemented in full regardless,
since a branch that is only correct when it never runs is not correct.

CHARACTER CREATION HAS EXACTLY ONE PERMITTED DOOR.  The new-game
submenu strings are quoted verbatim from src/main_menu.cpp:475-483:
"C<u|U>stom Character" is the only permitted entry, and "<P|p>reset
Character", "<R|r>andom Character", "Play Now!  (<D|d>efault
Scenario)" (two spaces after the "!") and "Play N<o|O>w!" are all
forbidden.  The scenario is "missed" / "Missed"
(data/json/scenarios.json), which starts the survivor in a house
inside a city.  Point-buy is a world option: CHARACTER_POINT_POOLS
defaults to "story_teller", at which the pool tab is read-only
(src/newcharacter.cpp:438-446, 462-467), so
:func:`assert_point_buy_available` refuses a create run whose options
file has not been seeded to "any" or "multi_pool".

HOW A SESSION ENDS, AND THE ONLY TWO WAYS IT MAY.  Play continues
until the survivor sleeps or dies -- there is no in-game time cap --
and the exit is then taken through the game's own Save & Quit path,
immediately after waking if the ending was sleep.  This module offers
no shortcut to that: there is no "finish" or "quit" call here, because
every keystroke of the exit is a step like any other and therefore gets
its own frame, its own manifest row and its own transcript entry.  The
last frame of the film is a captured one.

ABSOLUTELY NO CHEATING.  This module sends no keystroke that could
reach the debug menu, and it CANNOT: "debug_mode", "debug" and
"debug_hour_timer" are declared in data/raw/keybindings.json without a
`bindings` array (L3398-3409, L3466-3471), so they are unbound by
default and unreachable by any keystroke unless somebody deliberately
binds them.  Nothing here writes <userdir>/config/keybindings.json --
that file is a committed artifact and therefore R12's independent,
auditable evidence -- and :func:`assert_no_debug_bindings` READS it to
prove no such binding exists before a session begins.  No spawning, no
stat editing, no teleport, no god mode, no map reveal, for any reason,
explicitly including avoiding death.

WHAT THIS MODULE WRITES, EXHAUSTIVELY: one row per frame in
playthrough/manifest.jsonl (through manifest.py, which locks and
fsyncs), and one corroborating row per frame in
playthrough/build/observations.jsonl -- the telemetry sidecar
capture.sh REPORTS and hands off, so that one logical record has one
writer.  The PNG itself is written by capture.sh and by nothing here.
No save data, no options, no keybindings, no network call of any kind.

Standard library plus the flat siblings manifest, ocr_clock and
seed_options, imported the way tools/json_tools/ imports util.  Paths
follow playthrough/tooling/env.sh, the single definition of the
artifact layout, whose exports are honoured when they are set and
confined to the playthrough/ tree in every case.
"""

from __future__ import annotations

import argparse
import fcntl
import itertools
import json
import logging
import os
import re
import subprocess
import sys

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

# Set BEFORE the sibling imports below, which are the only imports that
# could write into the repository working tree.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1, but this module is documented as runnable
# on its own, and a standalone `python3 playthrough/tooling/session.py`
# without that environment would compile the siblings to
# playthrough/tooling/__pycache__/, which .gitignore's terminal
# `!/playthrough/**` negation then makes COMMITTABLE.  A stray .pyc in
# a committed evidence tree is an artifact nobody authored.  The flag
# must be set before the import it protects, because the interpreter
# consults it at compile time.
sys.dont_write_bytecode = True

try:
    import manifest
    import ocr_clock
    import seed_options
except ImportError:  # pragma: no cover - flat siblings, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import manifest
    import ocr_clock
    import seed_options

LOG = logging.getLogger("playthrough.session")


# ---------------------------------------------------------------------
# The window, the display and the tools.
# ---------------------------------------------------------------------

# env.sh's PLAYTHROUGH_WINDOW_CLASS.  Restated here with its own
# environment override so this module is correct when nothing has been
# sourced, which is how an ad-hoc test runs it.
WINDOW_CLASS = "cataclysm-tiles"
ENV_WINDOW_CLASS = "PLAYTHROUGH_WINDOW_CLASS"

# The window id launch_game.sh emits on its machine payload.  Accepted
# as a hint and re-verified; never trusted on its own.
ENV_WINDOW_ID = "PLAYTHROUGH_WINDOW_ID"

# xdotool has no --display option: it reads DISPLAY from the
# environment, which is why the resolved value is placed into the child
# environment explicitly rather than assumed to be inherited.
XDOTOOL = "xdotool"
ENV_DISPLAY = "DISPLAY"
ENV_PLAYTHROUGH_DISPLAY = "PLAYTHROUGH_DISPLAY"
ENV_CLONE_INDEX = "CLONE_INDEX"

# env.sh's own derivation, mirrored: index N yields DISPLAY=:(99 + N),
# an absent index means zero, and an index that is SET but unreadable
# is refused rather than coerced to 0 -- 0 owns the canonical :99, so a
# clone silently routed there would key another clone's window.
DISPLAY_BASE = 99
MAX_CLONE_INDEX = 99
DISPLAY_RE = re.compile(r"\A:\d{1,4}(\.\d{1,3})?\Z")

# One keystroke's whole round trip is bounded, because both xdotool and
# the capture talk to an X server that can stop answering without
# exiting.  capture.sh bounds every stage of its own work, so the
# ceiling here only has to be generous enough not to pre-empt it.
DEFAULT_TOOL_TIMEOUT = 60
DEFAULT_CAPTURE_TIMEOUT = 900
ENV_TOOL_TIMEOUT = "PLAYTHROUGH_SESSION_TOOL_TIMEOUT"
ENV_CAPTURE_TIMEOUT = "PLAYTHROUGH_SESSION_CAPTURE_TIMEOUT"
MIN_TIMEOUT = 1
MAX_TIMEOUT = 3600


# ---------------------------------------------------------------------
# The capture delegate.
#
# capture.sh owns the settle, the photograph and the clock read; this
# module owns the keystroke, the index and the record.  FRAME_INDEX is
# the only input it takes and it is REQUIRED, so the index crosses the
# boundary explicitly instead of being derived twice.
# ---------------------------------------------------------------------

CAPTURE_SCRIPT_NAME = "capture.sh"
CAPTURE_ENV_INDEX = "FRAME_INDEX"

# The payload keys this module reads.  capture.sh emits more than these
# and documents all of them; every key named here is required, so a
# payload missing one is a contract failure rather than a field to
# default.
PAYLOAD_KEY_RE = re.compile(r"\A[A-Z][A-Z0-9_]*\Z")
CAPTURE_MODE_KEY = "CAPTURE_MODE"
CAPTURE_MODE_PRODUCTION = "production"
REQUIRED_PAYLOAD_KEYS = (
    CAPTURE_MODE_KEY,
    "FRAME_INDEX",
    "FRAME_NAME",
    "FRAME_FILE",
    "FRAME_PATH",
    "FRAME_GEOMETRY",
    "REAL_TS",
    "CAPTURE_TOOL",
    "LUMA_MEAN",
    "LUMA_STDDEV",
    "CLOCK_RECT",
    "CLOCK_RECT_FROM",
    "CLOCK_SOURCE",
    "CLOCK_STATUS",
    "CLOCK",
    "TIME_PHRASE",
    "DATE",
    "DATE_STATUS",
    "OBSERVATIONS",
)

# capture.sh's exit codes, named so a failure reads as a cause rather
# than a number.  9 is a DIAGNOSTIC capture that was withdrawn from the
# working tree: non-zero by design, and never acceptable here.
CAPTURE_EXITS = {
    0: "one frame captured and the whole payload delivered",
    1: "usage error -- a missing, malformed or out-of-range index, or "
       "a production run that tried to relax a safeguard",
    2: "layout error -- not inside a checkout, or env.sh is missing",
    3: "the capture failed, or produced something that is not a frame",
    4: "the frame is blank -- the black-movie guard fired, which is "
       "the signature of SDL_VIDEODRIVER=dummy",
    5: "no usable display at the contracted geometry, a frame that is "
       "not that geometry, or a crop that could not be computed",
    6: "the clock read hit a FAULT rather than an unreadable clock",
    7: "refusing to overwrite an existing frame at this index",
    8: "a prerequisite command is missing, or the date-audit "
       "directory does not exist",
    9: "a DIAGNOSTIC capture completed and was withdrawn out of the "
       "working tree, so no frame was added to playthrough/frames/",
}


# ---------------------------------------------------------------------
# The record and the sidecar.
#
# The manifest is the evidence; the sidecar corroborates it.  Both are
# append-only, and neither is ever rewritten: a correction is a note in
# playthrough/TECHNICAL_NOTES.md, not an edit to a captured history.
# ---------------------------------------------------------------------

ENV_OBSERVATIONS = "PLAYTHROUGH_OBSERVATIONS"
OBSERVATIONS_REL_PARTS = ("build", "observations.jsonl")

# The sidecar's schema, as capture.sh reports it: each field beside the
# payload key that carries it.  Insertion order is the order the row is
# written in, and `frame` comes first because the file is keyed by it.
#
# It exists SEPARATELY from the manifest because the manifest schema is
# exactly six fields and the sidebar DATE line
# (display::date_string, src/display.cpp:193-205) is not one of them --
# yet timeline.py needs it: without a date, a clock that reads 08:00:00
# and then 07:59:00 cannot be told apart from a genuine crossing of
# midnight, and an action spanning a whole day is undercounted by
# exactly 24 hours because the time of day came back the same.
OBSERVATION_FIELDS = (
    ("frame", "FRAME_INDEX"),
    ("file", "FRAME_FILE"),
    ("real_ts", "REAL_TS"),
    ("ingame_clock", "CLOCK"),
    ("clock_status", "CLOCK_STATUS"),
    ("clock_source", "CLOCK_SOURCE"),
    ("clock_rect", "CLOCK_RECT"),
    ("clock_rect_from", "CLOCK_RECT_FROM"),
    ("time_phrase", "TIME_PHRASE"),
    ("date", "DATE"),
    ("date_status", "DATE_STATUS"),
    ("frame_geometry", "FRAME_GEOMETRY"),
    ("luma_mean", "LUMA_MEAN"),
    ("luma_stddev", "LUMA_STDDEV"),
    ("capture_tool", "CAPTURE_TOOL"),
)


# ---------------------------------------------------------------------
# The save layout, from the engine's own source.
# ---------------------------------------------------------------------

# `savedir_value = user_dir_value + "save/"` (src/path_info.cpp:144),
# each world a directory holding master.gsav (SAVE_MASTER,
# src/path_info.h:11) and worldoptions.json (src/path_info.cpp:418).
SAVE_MASTER_NAME = "master.gsav"
WORLD_OPTIONS_NAME = "worldoptions.json"

# Per-character files are written by save_player_data()
# (src/game_io.cpp) as `playerfile + SAVE_EXTENSION`, and with
# WORLD_COMPRESSION2 -- which DEFAULTS TO TRUE -- as that plus
# zzip_suffix = ".zzip" (src/worldfactory.h:25).  The engine names them
# `#<base64-of-character-name>`, so the "#" prefix is what separates a
# character file from any other .sav-suffixed file a world may hold.
#
# BOTH FORMS MUST BE COUNTED.  Counting only "*.sav" reports zero
# characters for a perfectly real compressed save, and because the
# resume decision turns on that count it would resolve to "create" and
# overwrite the very save that must be continued.
CHARACTER_PREFIX = "#"
SAVE_EXTENSION = ".sav"
ZZIP_SUFFIX = ".zzip"
COMPRESSED_SAVE_EXTENSION = SAVE_EXTENSION + ZZIP_SUFFIX

# The userdir tree, exactly as the engine derives it from
# `--userdir ./playthrough/userdir/`: config_dir = user_dir + "config/"
# (src/path_info.cpp:164) and savedir = user_dir + "save/"
# (src/path_info.cpp:144).  Spelled relative to the approved
# playthrough/ tree so that every path in this module is confined by one
# rule; env.sh's exports are honoured where they are set.
USERDIR_NAME = "userdir"
CONFIG_DIR_NAME = "config"
SAVE_DIR_NAME = "save"
ENV_SAVE_DIR = "PLAYTHROUGH_SAVE_DIR"
ENV_CONFIG_DIR = "PLAYTHROUGH_CONFIG_DIR"

SESSION_MODE_CREATE = "create"
SESSION_MODE_RESUME = "resume"
ENV_RESUME_WORLD = "PLAYTHROUGH_RESUME_WORLD"


# ---------------------------------------------------------------------
# Character creation: the one permitted door, and the four that are
# shut.  Quoted verbatim from src/main_menu.cpp:475-483 rather than
# from memory -- note the TWO spaces after the "!" in the fourth entry.
#
# These are declarations, not keystrokes.  Nothing in this module
# navigates a menu on the caller's behalf: the caller reads each
# captured frame and chooses the next key in character, and these
# constants are what a caller (and a reviewer) checks that choice
# against.
# ---------------------------------------------------------------------

MENU_CUSTOM_CHARACTER = "C<u|U>stom Character"
MENU_CUSTOM_CHARACTER_HOTKEYS = ("u", "U")
MENU_FORBIDDEN_ENTRIES = (
    "<P|p>reset Character",
    "<R|r>andom Character",
    "Play Now!  (<D|d>efault Scenario)",
    "Play N<o|O>w!",
)

# data/json/scenarios.json: "id": "missed", "name": "Missed",
# "points": 0, allowed_locs beginning sloc_house / sloc_house_boarded,
# so the survivor wakes in a house inside a city rather than an
# evacuation shelter.
SCENARIO_ID = "missed"
SCENARIO_NAME = "Missed"

# A fresh userdir does NOT open on the main menu: the first screen is a
# "Select your language" prompt, and the window is 640x384 on that
# launch against 1920x1072 on the second, once the engine has written
# screen-derived values into options.json.  Automation that assumes the
# main menu desynchronises on its very first keystroke.
FIRST_LAUNCH_SCREEN = "Select your language"

# The world option that decides whether the points pool is live.
# CHARACTER_POINT_POOLS defaults to "story_teller", at which
# pool_selection_modes_for_option() offers only FREEFORM
# (src/newcharacter.cpp:438-446) and the pool tab is informational and
# read-only (src/newcharacter.cpp:462-467).  seed_options.py seeds
# "any"; a create run against an unseeded options file is refused,
# because the creation frames would show a read-only pool tab and the
# point-buy requirement would not be satisfied.
POINT_BUY_POOLS = seed_options.POINT_POOLS_POINT_BUY


# ---------------------------------------------------------------------
# The cheat guard.
#
# These three actions are declared in data/raw/keybindings.json WITHOUT
# a `bindings` array (L3398-3409, L3466-3471), so they are unbound by
# default and unreachable by any keystroke.  User overrides live at
# <userdir>/config/keybindings.json (src/path_info.cpp:400-402), which
# the engine writes as a JSON array of objects carrying "id" and -- only
# when it is non-empty -- "bindings" (src/input.cpp:381-402).  That file
# is COMMITTED, which is what makes the no-cheating claim auditable by
# somebody who was not here.
#
# This module reads it and never writes it.
# ---------------------------------------------------------------------

DEBUG_ACTION_IDS = ("debug", "debug_mode", "debug_hour_timer")
KEYBINDINGS_NAME = "keybindings.json"
ENV_KEYBINDINGS = "PLAYTHROUGH_KEYBINDINGS_JSON"


# ---------------------------------------------------------------------
# The keystroke allow-list.
#
# A key name reaches an external command, so it is validated against a
# closed vocabulary BEFORE it is passed anywhere -- not escaped, not
# quoted, not sanitised.  Every subprocess in this module is invoked
# with an argument LIST and there is no shell anywhere, so this is
# defence in depth rather than the only defence; it is also what keeps
# a typo from being delivered to the engine as some other command.
#
# Two spellings are accepted for one keystroke, and only two: a name
# from NAMED_KEYSYMS, or a single printable ASCII character from
# SINGLE_CHARACTER_KEYS.  A chord is modifiers joined to that token by
# "+", each modifier from MODIFIER_KEYS and none repeated.
# ---------------------------------------------------------------------

MODIFIER_KEYS = frozenset({"ctrl", "alt", "shift", "super", "meta"})
CHORD_SEPARATOR = "+"
MAX_KEY_LENGTH = 40

# X keysym names for the keys a terminal game actually needs.  Built as
# an explicit set rather than a pattern: a pattern that admits any
# identifier would admit a typo, and a typo delivered to the engine is
# an action nobody chose.
_FUNCTION_KEYS = tuple("F%d" % number for number in range(1, 13))
_KEYPAD_DIGITS = tuple("KP_%d" % number for number in range(10))

_NAMED_KEYS_CORE = (
    # Confirm, cancel, edit.
    "Return", "KP_Enter", "Escape", "Tab", "ISO_Left_Tab",
    "space", "BackSpace", "Delete", "Insert",
    # Movement and paging, including the keypad the game maps to
    # the eight compass directions.
    "Up", "Down", "Left", "Right",
    "Home", "End", "Prior", "Next", "Begin",
    "KP_Up", "KP_Down", "KP_Left", "KP_Right",
    "KP_Home", "KP_End", "KP_Prior", "KP_Next", "KP_Begin",
    "KP_Insert", "KP_Delete",
    "KP_Add", "KP_Subtract", "KP_Multiply", "KP_Divide",
    "KP_Decimal",
    # The named spellings of the printable punctuation the game
    # binds.  "plus" has no single-character spelling here because
    # a bare "+" is the chord separator.
    "exclam", "quotedbl", "numbersign", "dollar", "percent",
    "ampersand", "apostrophe", "parenleft", "parenright",
    "asterisk", "plus", "comma", "minus", "period", "slash",
    "colon", "semicolon", "less", "equal", "greater", "question",
    "at", "bracketleft", "backslash", "bracketright",
    "asciicircum", "underscore", "grave", "braceleft", "bar",
    "braceright", "asciitilde",
)

NAMED_KEYSYMS = frozenset(
    _NAMED_KEYS_CORE + _FUNCTION_KEYS + _KEYPAD_DIGITS)

# Single printable ASCII characters, which xdotool maps to a keysym
# itself.  "+" is deliberately absent -- spell it "plus" -- and so is
# every whitespace character, because "space" is the keysym and a
# literal blank in a key argument is a mistake, not a keystroke.
SINGLE_CHARACTER_KEYS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "!\"#$%&'()*,-./:;<=>?@[\\]^_`{|}~"
)


# ---------------------------------------------------------------------
# Failures, typed so a caller can tell a refusal apart from a fault.
# ---------------------------------------------------------------------

class SessionError(Exception):
    """A step could not be completed, or was refused before it began.

    Raised in place of continuing.  A session that stops is recoverable
    -- the manifest, the frames and the save are all intact and the
    next process resumes from them -- whereas a session that carries on
    past a failure produces a record whose counts no longer mean what
    they say.
    """


class KeyRejected(SessionError):
    """The key argument is not one keystroke this module will send.

    Raised BEFORE anything is sent, so the game is untouched and the
    session stays usable.  This is the one failure that does not abort
    a session: nothing happened.
    """


class WindowError(SessionError):
    """The game window could not be found, focused or keyed.

    A missing window means the engine crashed or exited, which is not
    something to retry through: the run's own record of why it stopped
    is worth more than a session that limps on against no window.
    """


class ToolMissing(SessionError):
    """A command this module needs is absent or untrustworthy."""


class CaptureError(SessionError):
    """capture.sh did not deliver exactly one frame and its payload."""


class RecordError(SessionError):
    """The manifest or its sidecar could not be believed or appended.

    Also raised when the frames directory and the manifest disagree,
    which is the one condition that must never be reconciled silently:
    the count identity between them is the whole proof of one capture
    per keystroke.
    """


class CheatGuard(SessionError):
    """A debug or cheat capability was found to be reachable.

    The session refuses to start rather than play on and produce a
    record whose integrity cannot be checked afterwards.
    """


# Keys of the advisories already emitted in this process, so that a
# standing condition is reported once instead of once per keystroke.
_WARNED = set()


def _warn(message: str) -> None:
    """Report a non-fatal problem on stderr and carry on.

    The prefix matches playthrough_warn() in
    playthrough/tooling/env.sh, so one grep finds every advisory the
    pipeline raised whichever stage raised it.  stderr, always:
    engineering observations stay out of the in-character record and
    out of any machine payload.
    """
    sys.stderr.write("playthrough: WARNING: %s\n" % message)
    sys.stderr.flush()


def _warn_once(key: str, message: str) -> None:
    """Emit `message` the first time `key` is seen in this process."""
    if key in _WARNED:
        return
    _WARNED.add(key)
    _warn(message)


def reset_advisories() -> None:
    """Forget which advisories have been emitted.  For tests only."""
    _WARNED.clear()


# ---------------------------------------------------------------------
# Paths.
#
# Every path is derived from this module's own location, confined to
# the playthrough/ tree by manifest.approved_root(), and only then
# used.  An environment variable may name a path INSIDE that tree and
# is refused outside it: a record an environment variable could
# redirect to somebody else's checkout is not evidence of anything.
# ---------------------------------------------------------------------

def _module_dir() -> str:
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _playthrough_dir() -> str:
    """Return the absolute playthrough/ directory.

    Derived from this module's own location rather than the working
    directory, so the module is correct when it is invoked from
    somewhere other than the repository root.
    """
    return os.path.dirname(_module_dir())


def _confined(candidate: str, label: str,
              root: Optional[str] = None) -> str:
    """Return `candidate` resolved inside the approved tree, or raise.

    manifest.approved_root() is the single implementation of what
    "inside the tree" means, reused rather than restated so this module
    and the writer it appends through cannot disagree about it.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        raise SessionError(
            "%s must be a non-empty path, got %r" % (label, candidate))
    if "\x00" in candidate:
        raise SessionError(
            "%s must not contain a NUL byte" % label)
    approved = manifest.approved_root(root)
    resolved = os.path.realpath(os.path.abspath(candidate))
    if resolved != approved and not resolved.startswith(
            approved + os.sep):
        raise SessionError(
            "%s resolves to %s, outside the approved tree %s.  Every "
            "artifact this pipeline reads or writes lives beneath "
            "that directory, and a path an environment variable could "
            "move elsewhere is not evidence"
            % (label, resolved, approved))
    return resolved


def _from_env_or(variable: str, fallback: str, label: str,
                 root: Optional[str] = None) -> str:
    """Return the confined value of `variable`, else `fallback`.

    env.sh is the single definition of the artifact layout, so its
    exports win where they are set -- within the approved tree.
    """
    from_env = os.environ.get(variable)
    if from_env and from_env.strip():
        return _confined(from_env, "%s from $%s" % (label, variable),
                         root)
    return _confined(fallback, label, root)


def default_manifest_path(root: Optional[str] = None) -> str:
    """Return the manifest this session appends to.

    manifest.default_manifest_path() already honours
    $PLAYTHROUGH_MANIFEST; the result is confined here as well, because
    this module is the one that hands the writer its target.
    """
    return _confined(
        manifest.default_manifest_path(), "the manifest", root)


def default_frames_dir(root: Optional[str] = None) -> str:
    """Return the directory holding exactly one PNG per keystroke."""
    return _confined(
        manifest.default_frames_dir(), "the frames directory", root)


def default_observations_path(root: Optional[str] = None) -> str:
    """Return the capture telemetry sidecar this session appends to.

    env.sh's PLAYTHROUGH_OBSERVATIONS
    (playthrough/build/observations.jsonl).  capture.sh reports the
    destination on its payload and this module writes it, so the row
    and the manifest row for the same frame have one writer between
    them.
    """
    fallback = os.path.join(_playthrough_dir(), *OBSERVATIONS_REL_PARTS)
    return _from_env_or(
        ENV_OBSERVATIONS, fallback, "the telemetry sidecar", root)


def _executable(path: object) -> str:
    """Return `path` as a runnable absolute command, or raise.

    Used for the capturer.  A path that is not there, or is there and
    cannot be executed, is named as such before a keystroke is sent
    rather than after -- the keystroke is the thing that cannot be
    taken back.
    """
    if not isinstance(path, str) or not path.strip():
        raise ToolMissing(
            "a command path must be a non-empty string, got %r" % path)
    resolved = os.path.abspath(path)
    if not os.path.isfile(resolved):
        raise ToolMissing(
            "%s is missing, so no frame can be captured" % resolved)
    if not os.access(resolved, os.X_OK):
        raise ToolMissing(
            "%s is not executable, so no frame can be captured"
            % resolved)
    return resolved


def capture_script_path() -> str:
    """Return the capture helper that photographs one frame.

    Beside this module, always: the two halves of a step ship together
    and a capturer from somewhere else is not the one whose invariant
    this module relies on.  It is committed with mode 0755.
    """
    return _executable(
        os.path.join(_module_dir(), CAPTURE_SCRIPT_NAME))


def userdir_path(root: Optional[str] = None) -> str:
    """Return the engine-managed userdir inside the approved tree.

    The launcher passes `--userdir ./playthrough/userdir/`, which is
    normalised but NOT absolutised (src/path_info.cpp:105), so the tree
    lands here whenever the game is started from the repository root --
    which it always is.
    """
    return _confined(
        os.path.join(_playthrough_dir(), USERDIR_NAME),
        "the userdir", root)


def config_dir_path(root: Optional[str] = None) -> str:
    """Return <userdir>/config.

    `config_dir_value = user_dir_value + "config/"`
    (src/path_info.cpp:164), exported as $PLAYTHROUGH_CONFIG_DIR.
    """
    fallback = os.path.join(userdir_path(root), CONFIG_DIR_NAME)
    return _from_env_or(
        ENV_CONFIG_DIR, fallback, "the config directory", root)


def save_dir_path(root: Optional[str] = None) -> str:
    """Return <userdir>/save.

    `savedir_value = user_dir_value + "save/"`
    (src/path_info.cpp:144), exported as $PLAYTHROUGH_SAVE_DIR.  It may
    not exist: a checkout that has never been played has no save tree at
    all, which is precisely the create branch.
    """
    fallback = os.path.join(userdir_path(root), SAVE_DIR_NAME)
    return _from_env_or(
        ENV_SAVE_DIR, fallback, "the save directory", root)


def keybindings_path(root: Optional[str] = None) -> str:
    """Return <userdir>/config/keybindings.json.  Read-only, always.

    user_keybindings() = config_dir + "keybindings.json"
    (src/path_info.cpp:400-402).  The file may not exist -- the engine
    writes it only once a binding has been touched -- and its absence
    is the strongest possible evidence for R12 rather than a problem.
    """
    fallback = os.path.join(config_dir_path(root), KEYBINDINGS_NAME)
    return _from_env_or(
        ENV_KEYBINDINGS, fallback, "the keybindings file", root)


# ---------------------------------------------------------------------
# The keystroke.
# ---------------------------------------------------------------------

def _required_text(value: object, label: str) -> str:
    """Return `value` as required, non-empty, single-line text.

    `action` and `commentary` are both mandatory: a row that says what
    was pressed but not why, or why but not what, is not the record this
    pipeline promises.  manifest.py refuses an empty field too; this
    refuses it before the keystroke is sent, so a caller who forgot one
    has not already changed the game state.
    """
    if not isinstance(value, str):
        raise SessionError(
            "%s must be text, got %s" % (label, type(value).__name__))
    text = value.strip()
    if not text:
        raise SessionError(
            "%s must not be empty: every frame records what was "
            "pressed and the survivor's own reason for it" % label)
    if "\n" in text or "\r" in text:
        raise SessionError(
            "%s must be one line -- a row is one JSON object on one "
            "line" % label)
    return text


def _indices_through(last: int) -> Tuple[int, ...]:
    """Return the capture indices 1..`last`, inclusive.

    Built by counting rather than by arithmetic on an index, so the
    only place in this module where an index is advanced remains
    :meth:`Session.step`.  `last` <= 0 yields nothing, which is the
    fresh-session case.
    """
    if last <= 0:
        return ()
    counter = itertools.count(manifest.MIN_FRAME_INDEX)
    return tuple(itertools.islice(counter, last))


def validated_frame(frame: object) -> int:
    """Return `frame` as a usable capture index, or raise.

    The bounds are manifest.py's public MIN_FRAME_INDEX and
    MAX_FRAME_INDEX, so this module and the writer it appends through
    agree on what an index is: from 1, and never wide enough to break
    the five-digit field that keeps a lexical sort of the frames
    identical to a numeric one.

    This VALIDATES an index.  It never generates, defaults or
    increments one -- that happens in exactly one place, and the place
    is :meth:`Session.step`.
    """
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise RecordError(
            "a frame index is an int, got %s" % type(frame).__name__)
    if frame < manifest.MIN_FRAME_INDEX:
        raise RecordError(
            "a frame index starts at %d, got %d"
            % (manifest.MIN_FRAME_INDEX, frame))
    if frame > manifest.MAX_FRAME_INDEX:
        raise RecordError(
            "frame %d exceeds %d, which would widen the %s field and "
            "stop a lexical sort of the frames matching a numeric one"
            % (frame, manifest.MAX_FRAME_INDEX,
               manifest.FRAME_NAME_FORMAT))
    return frame


def validate_key(key: object) -> str:
    """Return `key` unchanged if it is exactly one keystroke, or raise.

    THE gate between a caller's intent and an external command.  The
    value is checked against a closed vocabulary rather than escaped,
    so nothing outside NAMED_KEYSYMS, SINGLE_CHARACTER_KEYS and
    MODIFIER_KEYS can reach xdotool at all.

    One keystroke means one: a string of characters, a space-separated
    list of keysyms and anything xdotool would `type` rather than
    `key` are all refused, because each would send several keystrokes
    behind one screenshot and break the one-frame-per-key relation
    irrecoverably.

    :raises KeyRejected: with what was wrong and how to spell it.  This
        happens BEFORE the game is touched, so a rejected key costs
        nothing but the call.
    """
    if not isinstance(key, str):
        raise KeyRejected(
            "a keystroke is a string such as 'j', 'Return' or "
            "'ctrl+c', got %s" % type(key).__name__)
    if not key:
        raise KeyRejected(
            "a keystroke must not be empty; the keysym for the space "
            "bar is 'space'")
    if len(key) > MAX_KEY_LENGTH:
        raise KeyRejected(
            "%r is %d characters, past the %d-character limit on a "
            "single keystroke; a long value is a string of keys, and "
            "a string of keys is several steps"
            % (key, len(key), MAX_KEY_LENGTH))
    if any(character.isspace() for character in key):
        raise KeyRejected(
            "%r contains whitespace.  A space-separated list is "
            "several keystrokes and therefore several steps, one "
            "frame each; the space bar itself is 'space'" % key)
    parts = key.split(CHORD_SEPARATOR)
    if any(not part for part in parts):
        raise KeyRejected(
            "%r is not a well-formed chord: '%s' joins modifiers to "
            "exactly one key, as in 'ctrl+c'.  A bare '%s' is spelled "
            "'plus'"
            % (key, CHORD_SEPARATOR, CHORD_SEPARATOR))
    modifiers = parts[:-1]
    token = parts[-1]
    for modifier in modifiers:
        if modifier not in MODIFIER_KEYS:
            raise KeyRejected(
                "%r modifies with '%s', which is not one of %s"
                % (key, modifier,
                   ", ".join(sorted(MODIFIER_KEYS))))
    if len(set(modifiers)) != len(modifiers):
        raise KeyRejected(
            "%r repeats a modifier; each one appears at most once"
            % key)
    if token in NAMED_KEYSYMS:
        return key
    if len(token) == 1 and token in SINGLE_CHARACTER_KEYS:
        return key
    raise KeyRejected(
        "%r does not name one keystroke.  A key is either a single "
        "printable ASCII character or one of the %d keysym names this "
        "module accepts (Return, Escape, Tab, space, BackSpace, the "
        "arrows, Home/End/Prior/Next, F1-F12, KP_0-KP_9 and the "
        "punctuation names such as 'semicolon' or 'plus').  Nothing "
        "outside that vocabulary is sent"
        % (key, len(NAMED_KEYSYMS)))


def describe_key(key: str) -> str:
    """Return a plain description of one validated keystroke.

    Used to build the manifest's `action` field, which must be
    unambiguous about what was pressed: "press 'j'" and "press
    'ctrl+c'" read the same way whether the keystroke was spelled as a
    character or as a keysym name.
    """
    return "press '%s'" % validate_key(key)


# ---------------------------------------------------------------------
# The display and the external tools.
# ---------------------------------------------------------------------

def _clone_index() -> int:
    """Return CLONE_INDEX as an integer, mirroring env.sh exactly.

    AN ABSENT INDEX MEANS ZERO; AN EXPLICIT BAD INDEX IS REFUSED.  The
    asymmetry is env.sh's and it is not pedantry: index 0 owns the
    canonical DISPLAY=:99, so a clone whose unreadable index was
    coerced to 0 would key the window of the clone that genuinely holds
    index 0 -- two engines keying each other, one capturer
    photographing another clone's screen, and a plausible-looking movie
    of somebody else's session.
    """
    raw = os.environ.get(ENV_CLONE_INDEX)
    if raw is None:
        return 0
    text = raw.strip()
    if not text or not text.isdigit():
        raise SessionError(
            "$%s is %r, which is not a decimal non-negative integer. "
            "It is refused rather than coerced to 0, because 0 owns "
            "the canonical DISPLAY=:%d: a clone silently routed there "
            "would key the window of the clone that really is index 0"
            % (ENV_CLONE_INDEX, raw, DISPLAY_BASE))
    index = int(text, 10)
    if index > MAX_CLONE_INDEX:
        raise SessionError(
            "$%s is %r, above the maximum of %d.  The index becomes "
            "the X display number, and no server in this pipeline is "
            "started that high"
            % (ENV_CLONE_INDEX, raw, MAX_CLONE_INDEX))
    return index


def resolve_display() -> str:
    """Return the X display this session keys and photographs.

    $PLAYTHROUGH_DISPLAY first, because env.sh is the single definition
    of the headless contract; then $DISPLAY; then env.sh's own
    derivation from CLONE_INDEX, so a caller who exported nothing but
    an index still lands on that clone's own server rather than on
    another one's.

    xdotool takes no --display option, so the resolved value is placed
    into the child environment explicitly.
    """
    for variable in (ENV_PLAYTHROUGH_DISPLAY, ENV_DISPLAY):
        value = os.environ.get(variable)
        if value and value.strip():
            display = value.strip()
            if not DISPLAY_RE.match(display):
                raise SessionError(
                    "$%s is %r, which is not an X display of the form "
                    "':99'" % (variable, value))
            return display
    return ":%d" % (DISPLAY_BASE + _clone_index())


def _verified(name: str) -> str:
    """Return a verified absolute path for the tool called `name`.

    ocr_clock.verified_tool() is reused rather than reimplemented: it
    prefers env.sh's own $PLAYTHROUGH_BIN_<NAME>, refuses an executable
    another account could rewrite, and is already the discipline every
    other stage resolves its tools through.
    """
    try:
        return ocr_clock.verified_tool(name)
    except ocr_clock.OcrClockError as err:
        raise ToolMissing(
            "%s is unusable, so no keystroke can be delivered: %s"
            % (name, err)) from err


def _child_environment() -> Dict[str, str]:
    """Return the environment an external stage is run with.

    The parent environment plus the resolved DISPLAY.  Nothing is
    removed: capture.sh sources env.sh and needs the whole headless
    contract, including XAUTHORITY and XDG_RUNTIME_DIR, and stripping
    it here would leave that stage unable to open the very display this
    one just resolved.
    """
    child = dict(os.environ)
    child[ENV_DISPLAY] = resolve_display()
    return child


def _run(command: Sequence[str], timeout: int, what: str,
         env: Optional[Mapping[str, str]] = None,
         cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run one external command as an argument LIST and return it.

    No shell, no string interpolation and no eval anywhere: the
    keystroke below is caller-supplied, so the only thing that ever
    reaches a process is a validated token in its own argv slot.
    `check=False` because several callers read a non-zero status as an
    ordinary answer -- an empty class search, for one -- and the ones
    that do not raise their own diagnostic instead.
    """
    LOG.debug("%s: %s", what, " ".join(command))
    try:
        return subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=dict(env) if env is not None else None,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as err:
        raise SessionError(
            "%s did not finish within %d s; the X server or the "
            "engine has stopped answering" % (what, timeout)) from err
    except OSError as err:
        raise SessionError(
            "%s could not be run: %s" % (what, err)) from err


def _diagnostic(completed: subprocess.CompletedProcess) -> str:
    """Return a finished command's stderr as text, never empty.

    A failure diagnostic that says nothing is worse than one that says
    it said nothing, so an empty stream is reported as such.
    """
    text = completed.stderr.decode("utf-8", "replace").strip()
    return text if text else "no output"


def _timeout(variable: str, fallback: int) -> int:
    """Return a whole number of seconds from the environment.

    A value that is SET but unreadable is refused rather than defaulted,
    because defaulting it silently hides an operator's mistake behind a
    working run.  Zero is refused too: it would mean no limit at all,
    and an unbounded wait on an X server that has stopped answering is
    how a session hangs instead of failing.
    """
    raw = os.environ.get(variable)
    if raw is None:
        return fallback
    text = raw.strip()
    if not text.isdigit():
        raise SessionError(
            "$%s is %r, which is not a whole number of seconds from "
            "%d to %d" % (variable, raw, MIN_TIMEOUT, MAX_TIMEOUT))
    value = int(text, 10)
    if value < MIN_TIMEOUT or value > MAX_TIMEOUT:
        raise SessionError(
            "$%s is %d s, outside %d..%d.  0 would mean no limit at "
            "all, and an unbounded wait on a display that has stopped "
            "answering hangs a session instead of failing it"
            % (variable, value, MIN_TIMEOUT, MAX_TIMEOUT))
    return value


# ---------------------------------------------------------------------
# The game window.
#
# WINDOW TARGETING IS BY CLASS, AND ONLY BY CLASS.
#   * `xdotool search --class cataclysm-tiles` finds this window and
#     prints one decimal id per line, newest last.
#   * `xdotool search --name 'Cataclysm'` returns EMPTY for it, even
#     though `xwininfo -root -children` lists it with the title
#     "Cataclysm: Dark Days Ahead - <hash>".  Name matching is not an
#     available alternative here.
#   * Scraping an id out of `xwininfo` with a loose hexadecimal pattern
#     is actively unsafe: the geometry substring xwininfo prints for
#     this window mis-matches such patterns.
# ---------------------------------------------------------------------

def window_class() -> str:
    """Return the window class this session keys.

    env.sh's PLAYTHROUGH_WINDOW_CLASS when it is set, so one edit moves
    every stage; the compiled-in default otherwise.  Validated, because
    the value becomes a search pattern in an argument list.
    """
    value = os.environ.get(ENV_WINDOW_CLASS, "").strip()
    if not value:
        return WINDOW_CLASS
    if not re.match(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", value):
        raise SessionError(
            "$%s is %r, which is not a plausible X window class"
            % (ENV_WINDOW_CLASS, value))
    return value


def validate_window_id(value: object) -> int:
    """Return `value` as a positive decimal X window id, or raise.

    Decimal, because that is what `xdotool search` prints and what
    `xdotool key --window` expects.  A hexadecimal-looking string is
    refused outright rather than converted: accepting one would mean
    somebody scraped it out of xwininfo, which is the unsafe path this
    module exists to avoid.
    """
    if isinstance(value, bool):
        raise WindowError(
            "a window id is a decimal integer, not a boolean")
    if isinstance(value, int):
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise WindowError(
                "%r is not a decimal X window id.  `xdotool search "
                "--class %s` prints them in decimal; a hexadecimal "
                "value means it was scraped out of xwininfo, whose "
                "geometry substring mis-matches such patterns"
                % (value, window_class()))
        number = int(text, 10)
    else:
        raise WindowError(
            "a window id is a decimal integer, got %s"
            % type(value).__name__)
    if number <= 0:
        raise WindowError(
            "a window id must be positive, got %d" % number)
    return number


def window_ids(timeout: Optional[int] = None) -> Tuple[int, ...]:
    """Return every window of the game's class, newest last.

    An empty result is an ordinary answer, not an error: `xdotool
    search` exits non-zero when nothing matches, which is how it says
    the game is not running.
    """
    if timeout is None:
        timeout = _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
    completed = _run(
        [_verified(XDOTOOL), "search", "--class", window_class()],
        timeout, "the window class search", env=_child_environment())
    found: List[int] = []
    for line in completed.stdout.decode("utf-8", "replace").split("\n"):
        text = line.strip()
        if not text:
            continue
        if not text.isdigit():
            # xdotool prints ids and nothing else on stdout, so a
            # non-numeric line means the tool behaved unexpectedly.
            # Reported rather than parsed around.
            _warn_once(
                "window-search-noise",
                "`xdotool search --class %s` printed %r, which is not "
                "a window id; only the numeric lines are used"
                % (window_class(), text))
            continue
        found.append(int(text, 10))
    if not found and completed.returncode != 0:
        LOG.debug("no window of class %s (xdotool exited %d)",
                  window_class(), completed.returncode)
    return tuple(found)


def window_is_alive(window_id: object,
                    timeout: Optional[int] = None) -> bool:
    """True when `window_id` is still a window of the game's class.

    The re-verification every keystroke goes through.  A window that
    has gone means the engine crashed or exited between one step and
    the next, which is a fact about the session and not something to
    key blindly past.
    """
    return validate_window_id(window_id) in window_ids(timeout)


def find_window(prefer: object = None,
                timeout: Optional[int] = None) -> int:
    """Return the one window id this session keys.

    `prefer` is a hint -- launch_game.sh emits PLAYTHROUGH_WINDOW_ID on
    its machine payload -- and it is RE-VERIFIED against the class
    search rather than trusted: a stale id from a previous run would
    otherwise deliver every keystroke into nothing, or worse into
    another window that reused the number.

    More than one match is reported and the newest is used, because
    that is the instance a fresh launch just created; the operator is
    told, since two engines on one display means two sessions racing
    for one screen.

    :raises WindowError: when no window of the class exists, or when a
        preferred id is not among those that do.
    """
    candidates = window_ids(timeout)
    if not candidates:
        raise WindowError(
            "no window of class '%s' is on display %s.  The tiles "
            "build must already be running -- start it with "
            "playthrough/tooling/launch_game.sh -- and note that "
            "`xdotool search --name 'Cataclysm'` finds nothing for "
            "this window, so the class search is the only way to "
            "reach it" % (window_class(), resolve_display()))
    if prefer is not None:
        wanted = validate_window_id(prefer)
        if wanted not in candidates:
            raise WindowError(
                "window %d is not among the windows of class '%s' now "
                "on display %s (%s).  A keystroke aimed at a window "
                "that has gone is a keystroke nothing receives, so "
                "this stops rather than continuing"
                % (wanted, window_class(), resolve_display(),
                   ", ".join(str(one) for one in candidates)))
        return wanted
    if len(candidates) > 1:
        _warn_once(
            "many-windows",
            "%d windows of class '%s' are on display %s (%s); the "
            "newest is used.  Two engines on one display means two "
            "sessions competing for one screen, and every capture "
            "photographs the root window, so confirm which instance "
            "is being recorded"
            % (len(candidates), window_class(), resolve_display(),
               ", ".join(str(one) for one in candidates)))
    return candidates[-1]


def focus_window(window_id: object,
                 timeout: Optional[int] = None) -> int:
    """Focus the game window, and confirm it exists first.

    Focus is taken before every keystroke rather than once per session:
    the window manager is a separate process and focus can move for
    reasons this module never sees, and a keystroke delivered to an
    unfocused window is a keystroke the engine may never read.
    """
    if timeout is None:
        timeout = _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
    identifier = find_window(window_id, timeout)
    completed = _run(
        [_verified(XDOTOOL), "windowfocus", str(identifier)],
        timeout, "focusing the game window",
        env=_child_environment())
    if completed.returncode != 0:
        raise WindowError(
            "could not focus window %d on display %s (xdotool exited "
            "%d: %s)"
            % (identifier, resolve_display(), completed.returncode,
               _diagnostic(completed)))
    return identifier


def send_key(window_id: object, key: str,
             timeout: Optional[int] = None) -> str:
    """Send EXACTLY ONE keystroke to the game window.

    One key, one call, one argv slot.  There is no variant of this
    function that takes several: `xdotool key` will happily accept a
    list of keysyms and `xdotool type` a whole string, and either would
    put more than one keystroke behind a single screenshot, which is
    the one thing this pipeline cannot recover from afterwards.

    The key is validated first, so a rejected value never reaches the
    process and the game is left untouched.

    :returns: the key as sent, so a caller records what happened rather
        than what it meant to happen.
    :raises KeyRejected: for anything that is not one keystroke.
    :raises WindowError: when the keystroke could not be delivered.
    """
    validated = validate_key(key)
    if timeout is None:
        timeout = _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
    identifier = validate_window_id(window_id)
    completed = _run(
        [_verified(XDOTOOL), "key", "--window", str(identifier),
         validated],
        timeout, "sending one keystroke", env=_child_environment())
    if completed.returncode != 0:
        raise WindowError(
            "could not send '%s' to window %d on display %s (xdotool "
            "exited %d: %s).  Whether the engine received it cannot be "
            "known, so the session stops rather than recording a frame "
            "against a keystroke that may not have landed"
            % (validated, identifier, resolve_display(),
               completed.returncode, _diagnostic(completed)))
    return validated


# ---------------------------------------------------------------------
# The save-resume pre-flight probe.
#
# The survivor is unique AND an existing save is CONTINUED rather than
# replaced.  This probe is what makes the second half real: it inspects
# playthrough/userdir/save/*/ BEFORE anything could create a character.
#
# A fresh checkout has no playthrough/, no userdir and no save/, so on
# a first run this reports "create".  The resume branch is implemented
# in full regardless -- a branch that is only correct when it never
# runs is not correct.
#
# It mirrors launch_game.sh's own probe exactly, so the launcher and
# this module cannot reach different conclusions about the same tree.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class WorldSave:
    """One world directory under save/, and what it actually holds."""

    name: str
    path: str
    characters: Tuple[str, ...]
    forms: Tuple[str, ...]
    has_world_options: bool

    @property
    def resumable(self) -> bool:
        """True when this world holds at least one character.

        master.gsav proves a WORLD exists, not that anybody lives in
        it: the engine writes the world as soon as it is created, so a
        run interrupted during character creation leaves a world with
        no character at all.  Loading that opens an empty character
        list, which is a dead end, so it is not resumable.
        """
        return bool(self.characters)


@dataclass(frozen=True)
class SaveProbe:
    """The create-versus-resume decision, with its evidence."""

    mode: str
    save_dir: str
    world: Optional[str]
    worlds: Tuple[WorldSave, ...]
    notes: Tuple[str, ...] = ()

    @property
    def resume(self) -> bool:
        """True when an existing save must be continued."""
        return self.mode == SESSION_MODE_RESUME

    @property
    def resumable_worlds(self) -> Tuple[WorldSave, ...]:
        """Every world holding at least one character save."""
        return tuple(one for one in self.worlds if one.resumable)

    @property
    def character_count(self) -> int:
        """How many distinct characters exist across every world."""
        return sum(len(one.characters) for one in self.worlds)

    @property
    def character_forms(self) -> Tuple[str, ...]:
        """Which canonical character-file forms are in use, sorted.

        Reported rather than inferred from the seeded
        WORLD_COMPRESSION2 option, because this probe runs BEFORE any
        seeding on a resumed run and the world may not have been
        created under this pipeline's seed at all.
        """
        forms = set()
        for one in self.worlds:
            forms.update(one.forms)
        return tuple(sorted(forms))

    def as_dict(self) -> Dict[str, object]:
        """A JSON-serialisable account of the decision."""
        return {
            "mode": self.mode,
            "save_dir": self.save_dir,
            "world": self.world,
            "world_count": len(self.worlds),
            "resumable_count": len(self.resumable_worlds),
            "character_count": self.character_count,
            "character_forms": list(self.character_forms),
            "worlds": [
                {
                    "name": one.name,
                    "characters": list(one.characters),
                    "forms": list(one.forms),
                    "resumable": one.resumable,
                    "worldoptions": one.has_world_options,
                }
                for one in self.worlds
            ],
            "notes": list(self.notes),
        }


def _character_saves(world_dir: str) -> Tuple[Tuple[str, ...],
                                              Tuple[str, ...]]:
    """Return one world's character names and the forms they use.

    BOTH CANONICAL FORMS COUNT, AND ONE CHARACTER COUNTS ONCE.
    save_player_data() writes `playerfile + SAVE_EXTENSION` plainly and
    `playerfile + SAVE_EXTENSION + zzip_suffix` when the world
    compresses (src/game_io.cpp; zzip_suffix = ".zzip" at
    src/worldfactory.h:25), and WORLD_COMPRESSION2 DEFAULTS TO TRUE --
    so scanning only "*.sav" reports zero characters for a perfectly
    real save.  Because the resume decision turns on that count, doing
    so would resolve to "create" and overwrite the very save that must
    be continued.

    A world holding both forms of the SAME character counts one
    character: the ".zzip" suffix is stripped and each distinct base
    name is counted once.

    The listing here is EVIDENCE, never an index: nothing in this
    module derives a frame number from a directory.
    """
    names = set()
    forms = set()
    try:
        entries = sorted(os.listdir(world_dir))
    except OSError as err:
        raise SessionError(
            "cannot read the world directory %s: %s"
            % (world_dir, err)) from err
    for entry in entries:
        if not entry.startswith(CHARACTER_PREFIX):
            continue
        if entry.endswith(COMPRESSED_SAVE_EXTENSION):
            form = COMPRESSED_SAVE_EXTENSION
            base = entry[:-len(ZZIP_SUFFIX)]
        elif entry.endswith(SAVE_EXTENSION):
            form = SAVE_EXTENSION
            base = entry
        else:
            continue
        if not os.path.isfile(os.path.join(world_dir, entry)):
            continue
        names.add(base)
        forms.add(form)
    return tuple(sorted(names)), tuple(sorted(forms))


def probe_save_resume(save_dir: Optional[str] = None,
                      requested_world: Optional[str] = None,
                      root: Optional[str] = None) -> SaveProbe:
    """Decide whether this session creates a character or resumes one.

    Read-only, and it runs BEFORE anything could create a character --
    that ordering is the whole point, because the hard rule is that an
    existing save is continued rather than replaced.

    AMBIGUITY IS REFUSED, NOT GUESSED.  With more than one resumable
    world this raises and asks for $PLAYTHROUGH_RESUME_WORLD: directory
    order is locale- and filesystem-dependent, so taking the first
    world could continue a different survivor on the next run of the
    same command.  A second CHARACTER inside one world is a warning
    instead, because which survivor to load happens inside the game's
    own character list, where the operator can read the names.

    :param save_dir: an explicit save directory; seed_options'
        confined <userdir>/save by default.
    :param requested_world: the world to continue;
        $PLAYTHROUGH_RESUME_WORLD by default.
    :raises SessionError: on an unreadable tree, or on an ambiguity
        that must be resolved by a human rather than by this module.
    """
    if save_dir is None:
        save_dir = save_dir_path(root)
    directory = _confined(save_dir, "the save directory", root)
    if requested_world is None:
        requested_world = os.environ.get(ENV_RESUME_WORLD, "").strip()

    notes: List[str] = []
    worlds: List[WorldSave] = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            world_dir = os.path.join(directory, name)
            if not os.path.isdir(world_dir):
                continue
            if not os.path.isfile(
                    os.path.join(world_dir, SAVE_MASTER_NAME)):
                notes.append(
                    "save/%s has no %s, so it is not treated as a "
                    "world" % (name, SAVE_MASTER_NAME))
                continue
            characters, forms = _character_saves(world_dir)
            worlds.append(WorldSave(
                name=name,
                path=world_dir,
                characters=characters,
                forms=forms,
                has_world_options=os.path.isfile(
                    os.path.join(world_dir, WORLD_OPTIONS_NAME)),
            ))
    else:
        notes.append(
            "no save directory at %s yet, so this session creates a "
            "character" % directory)

    for world in worlds:
        if not world.resumable:
            notes.append(
                "save/%s is a world with NO character save (neither "
                "%s%s nor %s%s).  A world is written as soon as it is "
                "created, so this is most likely a run interrupted "
                "during character creation; it is not resumable and is "
                "excluded from the decision"
                % (world.name, CHARACTER_PREFIX, SAVE_EXTENSION,
                   CHARACTER_PREFIX, COMPRESSED_SAVE_EXTENSION))

    resumable = [one.name for one in worlds if one.resumable]
    if not resumable:
        notes.append(
            "CREATE: no character save under %s, so this session "
            "creates a survivor through the custom point-buy creator "
            "-- the '%s' entry, never '%s'"
            % (directory, MENU_CUSTOM_CHARACTER,
               "', '".join(MENU_FORBIDDEN_ENTRIES)))
        return SaveProbe(
            mode=SESSION_MODE_CREATE,
            save_dir=directory,
            world=None,
            worlds=tuple(worlds),
            notes=tuple(notes),
        )

    chosen: Optional[str] = None
    if requested_world:
        if requested_world not in resumable:
            raise SessionError(
                "$%s is '%s', which is not a resumable world.  The "
                "worlds holding at least one character save are: %s"
                % (ENV_RESUME_WORLD, requested_world,
                   ", ".join(resumable)))
        chosen = requested_world
        notes.append(
            "resuming world '%s', chosen explicitly by $%s"
            % (chosen, ENV_RESUME_WORLD))
    elif len(resumable) == 1:
        chosen = resumable[0]
    else:
        raise SessionError(
            "%d worlds hold character saves (%s), so which save to "
            "continue is ambiguous.  This is refused rather than "
            "guessed: directory order is locale- and "
            "filesystem-dependent, so a guess could continue a "
            "different survivor on the next run of the same command. "
            "Set $%s to the one you mean"
            % (len(resumable), ", ".join(resumable), ENV_RESUME_WORLD))

    characters = sum(len(one.characters) for one in worlds)
    forms = sorted({form for one in worlds for form in one.forms})
    notes.append(
        "RESUME: %d world(s) and %d character save(s) (%s) exist "
        "under %s.  The existing save MUST be continued -- load world "
        "'%s' and do not create a new character"
        % (len(worlds), characters,
           ", ".join(forms) or "no character file yet",
           directory, chosen))
    if characters > 1:
        notes.append(
            "%d distinct character saves are present, and this run "
            "records exactly one survivor; confirm which one is being "
            "continued before loading, and do not create another"
            % characters)
    for note in notes:
        LOG.info("%s", note)
    return SaveProbe(
        mode=SESSION_MODE_RESUME,
        save_dir=directory,
        world=chosen,
        worlds=tuple(worlds),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------
# The integrity pre-flights.
#
# Both are READ-ONLY, and both are checks on committed artifacts rather
# than assertions about this module's good intentions.  That is the
# point: a reviewer who was not here can run them.
# ---------------------------------------------------------------------

def _bound_debug_actions(entries: object, path: str) -> List[str]:
    """Return every debug action that carries a binding.

    The engine writes the user keybindings file as a JSON array of
    objects with "id", "version", "category" and -- only when it is
    non-empty -- "bindings" (src/input.cpp:381-402).  An object for a
    debug action with no "bindings" member is therefore the ordinary,
    correct state and is not a finding; one WITH a non-empty bindings
    array means somebody deliberately made the debug menu reachable.
    """
    if not isinstance(entries, list):
        raise CheatGuard(
            "%s is not a JSON array of keybinding objects, so whether "
            "a debug action is bound cannot be established.  A "
            "keybindings file that cannot be read is not evidence of "
            "anything" % path)
    bound = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise CheatGuard(
                "%s entry %d is a %s, not a keybinding object"
                % (path, position, type(entry).__name__))
        identifier = entry.get("id")
        if identifier not in DEBUG_ACTION_IDS:
            continue
        bindings = entry.get("bindings")
        if isinstance(bindings, list) and bindings:
            bound.append(str(identifier))
    return bound


def assert_no_debug_bindings(path: Optional[str] = None,
                             root: Optional[str] = None) -> str:
    """Prove no debug action is reachable by a keystroke.  Read-only.

    "debug_mode" ("Toggle debug mode"), "debug" ("Debug menu") and
    "debug_hour_timer" are declared in data/raw/keybindings.json
    WITHOUT a `bindings` array (L3398-3409, L3466-3471), so they are
    unbound by default and unreachable by any keystroke unless somebody
    deliberately binds one.  A binding could only live in the user
    override at <userdir>/config/keybindings.json
    (src/path_info.cpp:400-402), and that file is COMMITTED -- which is
    what turns "no cheating" from a claim into a property a stranger
    can check.

    An ABSENT file passes, and passes for a good reason: the engine
    writes it only once a binding has been touched at all, so its
    absence is the strongest evidence available that none was.

    This module never writes that file, here or anywhere.

    :returns: a sentence describing what was found, for the record.
    :raises CheatGuard: when a debug action carries a binding, or when
        the file exists and cannot be believed.
    """
    target = keybindings_path(root) if path is None else _confined(
        path, "the keybindings file", root)
    if not os.path.exists(target):
        return ("no user keybindings file at %s, so none of %s can be "
                "reached by any keystroke: the engine writes that file "
                "only once a binding is touched, and these three ship "
                "with no bindings array at all"
                % (target, ", ".join(DEBUG_ACTION_IDS)))
    try:
        with open(target, "r", encoding="utf-8") as handle:
            entries = json.load(handle)
    except OSError as err:
        raise CheatGuard(
            "cannot read %s (%s), so whether a debug action is bound "
            "cannot be established" % (target, err)) from err
    except ValueError as err:
        raise CheatGuard(
            "%s is not valid JSON (%s), so whether a debug action is "
            "bound cannot be established" % (target, err)) from err
    bound = _bound_debug_actions(entries, target)
    if bound:
        raise CheatGuard(
            "%s binds %s.  Those actions are unbound in the shipped "
            "keybindings and must stay that way: no debug menu, no "
            "debug mode, no hour timer, for any reason and explicitly "
            "including avoiding death.  Remove the binding before "
            "playing; death by legitimate play is an acceptable, "
            "honest ending" % (target, ", ".join(bound)))
    return ("%s carries no binding for any of %s"
            % (target, ", ".join(DEBUG_ACTION_IDS)))


def assert_point_buy_available(options_json: Optional[str] = None,
                               repo: Optional[str] = None) -> str:
    """Prove the character creator's points pool is live.  Read-only.

    CHARACTER_POINT_POOLS is a world_default option whose shipped value
    is "story_teller", and at that value
    pool_selection_modes_for_option() offers only FREEFORM
    (src/newcharacter.cpp:438-446) with pool_selection_is_fixed() true
    and the pool tab informational and read-only
    (src/newcharacter.cpp:462-467).  Creating a character then produces
    frames showing a read-only pool tab, and the point-buy requirement
    is not satisfied -- silently, because everything else about the run
    looks right.

    seed_options.py seeds "any"; this refuses a create run against an
    options file that has not been seeded, so the failure happens
    before the survivor exists rather than after the session is over.

    Only meaningful on the create branch: a resumed character was
    already built, and its pool choice is history.

    `repo` is a REPOSITORY root, not the artifact root the rest of this
    module's `root` arguments take: the options file belongs to
    seed_options.py, so its confinement is that module's -- it holds
    every target to <repo>/playthrough/userdir and refuses anything
    outside it.  Naming the parameter differently is deliberate, so the
    two kinds of root cannot be passed to one another by accident.

    :returns: a sentence naming the value found, for the record.
    :raises SessionError: when the option is missing or not a point-buy
        value, or when the options file cannot be believed.
    """
    if options_json is None:
        options_json = seed_options.options_json_path(repo)
    target = os.path.abspath(options_json)
    if not os.path.isfile(target):
        raise SessionError(
            "no options file at %s, so the points pool cannot be "
            "confirmed live.  The engine writes it on its first "
            "launch; run playthrough/tooling/launch_game.sh and then "
            "seed_options.py before creating a character" % target)
    try:
        observed = seed_options.read_values(target, repo)
    except seed_options.SeedError as err:
        raise SessionError(
            "cannot read the seeded options from %s: %s"
            % (target, err)) from err
    value = observed.get(seed_options.OPT_POINT_POOLS)
    if value is None:
        raise SessionError(
            "%s does not set %s, so the character creator's pool tab "
            "would be whatever the engine defaults to -- "
            "'story_teller', at which the tab is read-only "
            "(src/newcharacter.cpp:462-467) and the point-buy "
            "requirement is not met.  Run seed_options.py first"
            % (target, seed_options.OPT_POINT_POOLS))
    if value not in POINT_BUY_POOLS:
        raise SessionError(
            "%s sets %s='%s', at which the character creator's pool "
            "tab is informational and read-only "
            "(src/newcharacter.cpp:438-446, 462-467).  A point-buy "
            "creation needs one of %s; run seed_options.py"
            % (target, seed_options.OPT_POINT_POOLS, value,
               ", ".join(POINT_BUY_POOLS)))
    return ("%s='%s' in %s, so the creator's points pool is live and "
            "the '%s' entry really is the point-buy path"
            % (seed_options.OPT_POINT_POOLS, value, target,
               MENU_CUSTOM_CHARACTER))


# ---------------------------------------------------------------------
# The capture payload.
#
# capture.sh's stdout is a machine contract: KEY=value, one per line,
# nothing else, with every diagnostic on stderr.  It is parsed
# strictly, because every field of the manifest row that is not the
# survivor's own words comes from it.
# ---------------------------------------------------------------------

def parse_payload(text: str) -> Dict[str, str]:
    """Return capture.sh's KEY=value payload as a mapping.

    Strict on purpose.  A line that is not KEY=value, a key that is not
    upper snake case and a key that appears twice are all contract
    failures rather than noise to skip: the alternative is reading one
    of two values for a field and not knowing which.
    """
    payload: Dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        if "=" not in line:
            raise CaptureError(
                "capture.sh line %d is %r, which is not KEY=value; "
                "its stdout is a machine contract and every "
                "diagnostic belongs on stderr" % (number, line))
        key, _, value = line.partition("=")
        if not PAYLOAD_KEY_RE.match(key):
            raise CaptureError(
                "capture.sh line %d names the field %r, which is not "
                "an upper-case key" % (number, key))
        if key in payload:
            raise CaptureError(
                "capture.sh reported %s twice (%r then %r); one "
                "capture reports each field once, and choosing "
                "between two values would be a guess"
                % (key, payload[key], value))
        payload[key] = value
    missing = [key for key in REQUIRED_PAYLOAD_KEYS
               if key not in payload]
    if missing:
        raise CaptureError(
            "capture.sh did not report %s.  Every one of those fields "
            "becomes part of this frame's record, and a field that is "
            "absent is not a field to default"
            % ", ".join(missing))
    return payload


def clock_from_payload(payload: Mapping[str, str]) -> Optional[str]:
    """Return the sidebar reading for this frame, or None.

    THE HONESTY FIELD, and the whole of its rule in four lines.  An
    exact clock when the survivor has a watch; otherwise the coarse
    phrase the sidebar showed instead of one, verbatim -- that is a
    real observation, not a failure (src/display.cpp:207-218); and
    None when neither could be read.

    None is never a stand-in for a value.  Nothing is interpolated,
    nothing is carried forward from the previous frame, and nothing is
    converted between the two kinds of reading.  Reconciling an
    unreadable or non-monotonic reading is timeline.py's job, downstream
    and visibly flagged.
    """
    clock = payload.get("CLOCK", "").strip()
    if clock:
        return clock
    phrase = payload.get("TIME_PHRASE", "").strip()
    if phrase:
        return phrase
    return None


def observation_row(frame: int,
                    payload: Mapping[str, str]) -> Dict[str, object]:
    """Build this frame's telemetry row.  Pure -- nothing is written.

    capture.sh REPORTS the row and names its destination; this module
    appends it, because it already owns the frame counter and the
    manifest row for the same frame and one logical record should have
    one writer.  Exposed separately from the append so a caller can
    inspect exactly what would be recorded.

    The frame index is the caller's, taken from this module's counter
    and cross-checked against the payload's own FRAME_INDEX by
    :func:`assert_payload_matches`, so the sidecar and the manifest
    cannot key the same capture differently.
    """
    row: Dict[str, object] = {}
    for name, key in OBSERVATION_FIELDS:
        value = payload.get(key, "")
        row[name] = value.strip() if isinstance(value, str) else value
    # The one field that is not a verbatim copy: the sidecar is keyed by
    # an integer frame index, which is what timeline.py matches its rows
    # against (a row it cannot key is a row it cannot use).
    row["frame"] = validated_frame(frame)
    return row


def append_observation(path: str, row: Mapping[str, object],
                       require_durable: bool = True,
                       root: Optional[str] = None) -> Dict[str, object]:
    """Append one telemetry row, all-or-nothing.  Returns the row.

    The same discipline manifest.py applies to the record itself, for
    the same reasons: the destination is confined to the playthrough/
    tree, the descriptor is opened O_NOFOLLOW so a planted symlink is
    refused by the kernel rather than followed, the append is
    serialised by an exclusive advisory lock, the row is written with a
    single unbuffered os.write, a short write is truncated straight back
    to the offset the file had, and the row is not reported as recorded
    until it has been forced to the device.

    A half-written line is not JSON, and timeline.py refuses a sidecar
    it cannot parse outright rather than falling back to the clock
    alone -- so a fragment here would stop the render, not degrade it.

    :raises RecordError: on any failure along that path.
    """
    target = _confined(path, "the telemetry sidecar", root)
    line = json.dumps(dict(row), ensure_ascii=False) + "\n"
    payload = line.encode("utf-8")
    directory = os.path.dirname(target)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as err:
        raise RecordError(
            "cannot create %s for the telemetry sidecar: %s"
            % (directory, err)) from err
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
            0o600)
    except OSError as err:
        raise RecordError(
            "cannot open the telemetry sidecar %s for appending: %s"
            % (target, err)) from err
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            committed = os.lseek(descriptor, 0, os.SEEK_END)
            written = os.write(descriptor, payload)
        except OSError as err:
            raise RecordError(
                "could not append frame %s's telemetry row to %s: %s"
                % (row.get("frame"), target, err)) from err
        if written != len(payload):
            _truncate_back(descriptor, committed, target)
            raise RecordError(
                "only %d of %d bytes of frame %s's telemetry row "
                "reached %s; the partial line was removed, because a "
                "fragment is not JSON and would stop the render"
                % (written, len(payload), row.get("frame"), target))
        if require_durable:
            try:
                os.fsync(descriptor)
            except OSError as err:
                raise RecordError(
                    "could not force frame %s's telemetry row to the "
                    "device (%s); it is not reported as recorded"
                    % (row.get("frame"), err)) from err
    finally:
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "sidecar-close",
                "could not close %s after appending (%s); the row was "
                "written and forced to the device before this point, "
                "so the sidecar is intact" % (target, err))
    return dict(row)


def _truncate_back(descriptor: int, offset: int, path: str) -> None:
    """Remove the bytes a failing append had begun to write.

    Only ever called under the exclusive lock and only with the offset
    the file held before this append, so it can remove nothing but the
    fragment this process itself produced.
    """
    try:
        os.ftruncate(descriptor, offset)
    except OSError as err:
        _warn(
            "could not remove a partial telemetry row from %s (%s); "
            "the file now ends mid-line and timeline.py will refuse "
            "it until the last line is deleted by hand" % (path, err))


def assert_payload_matches(frame: int, payload: Mapping[str, str],
                           frames_dir: str) -> str:
    """Confirm the capture is the one this step asked for.  Read-only.

    The boundary check between the index this module owns and the frame
    that actually reached the disk.  Everything the manifest row will
    say about the capture comes from the payload, so a payload
    describing a DIFFERENT frame -- a stale index, a diagnostic capture
    that was withdrawn, a filename built from another format -- must
    stop the step before a row is appended, not be reconciled.

    :returns: the absolute path of the verified PNG.
    :raises CaptureError: when the payload and the index disagree, or
        when the frame the payload names is not on disk.
    """
    index = validated_frame(frame)
    mode = payload.get(CAPTURE_MODE_KEY, "")
    if mode != CAPTURE_MODE_PRODUCTION:
        raise CaptureError(
            "capture.sh reported %s=%r for frame %d.  Only a "
            "'%s' capture belongs in the record: a diagnostic one is "
            "withdrawn from the working tree, so there is no frame to "
            "append a row for"
            % (CAPTURE_MODE_KEY, mode, index,
               CAPTURE_MODE_PRODUCTION))
    reported = payload.get("FRAME_INDEX", "")
    if reported != str(index):
        raise CaptureError(
            "this step owns index %d but capture.sh reported "
            "FRAME_INDEX=%r.  The index crosses that boundary exactly "
            "once, in one direction, and a mismatch means the two "
            "halves of the step are no longer talking about the same "
            "frame" % (index, reported))
    expected_file = manifest.frame_file(index)
    if payload.get("FRAME_FILE") != expected_file:
        raise CaptureError(
            "capture.sh reported FRAME_FILE=%r for frame %d, but the "
            "record's `file` field is %r; the capturer and the "
            "manifest build that name from one format so a spelling "
            "difference cannot break the count identity"
            % (payload.get("FRAME_FILE"), index, expected_file))
    if not payload.get("REAL_TS", "").strip():
        raise CaptureError(
            "capture.sh reported no REAL_TS for frame %d, so when the "
            "capture happened is unknown.  It is not defaulted to now: "
            "the instant a row is appended is not the instant the "
            "frame was taken" % index)
    # The path is REBUILT from this module's own index and format and
    # then compared, so nothing unvalidated from the payload is ever
    # joined onto a directory.
    expected_path = os.path.join(
        frames_dir, manifest.FRAME_NAME_FORMAT % index)
    reported_path = payload.get("FRAME_PATH", "").strip()
    if not reported_path:
        raise CaptureError(
            "capture.sh reported no FRAME_PATH for frame %d" % index)
    if os.path.realpath(reported_path) != os.path.realpath(
            expected_path):
        raise CaptureError(
            "capture.sh wrote frame %d to %r, but this session's "
            "frames directory is %s.  Two capture destinations means "
            "the count identity is measured against the wrong one"
            % (index, reported_path, frames_dir))
    if not os.path.isfile(expected_path):
        raise CaptureError(
            "no capture on disk at %s for frame %d, so no row is "
            "appended: a row for a PNG that does not exist would break "
            "the frames-count == manifest-line-count identity"
            % (expected_path, index))
    return expected_path


# ---------------------------------------------------------------------
# One step's result.
#
# It carries the frame and the reading BACK to the caller, because the
# loop is observe -> decide in character -> act -> capture -> log and
# the caller cannot decide the next keystroke without them.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class StepResult:
    """Everything one keystroke produced, and what the frame said."""

    frame: int
    key: str
    action: str
    commentary: str
    file: str
    path: str
    real_ts: str
    ingame_clock: Optional[str]
    clock_status: str
    time_phrase: Optional[str]
    date: Optional[str]
    date_status: str
    geometry: str
    luma_mean: str
    luma_stddev: str
    row: Dict[str, object] = field(default_factory=dict)
    observation: Dict[str, object] = field(default_factory=dict)

    @property
    def clock_readable(self) -> bool:
        """True when the sidebar gave a reading of any kind."""
        return self.ingame_clock is not None

    def describe(self) -> str:
        """A human-readable account of the step, for stderr."""
        return ("frame %05d  %-12s  clock %-12s  %s"
                % (self.frame, self.key,
                   self.ingame_clock or "unreadable",
                   self.file))


# ---------------------------------------------------------------------
# The session, and the counter it owns.
# ---------------------------------------------------------------------

class Session:
    """The keystroke loop's state: one window, one counter, one record.

    THE COUNTER LIVES HERE AND NOWHERE ELSE.  It is recovered from the
    manifest when the session opens, advanced in exactly one statement
    inside :meth:`step`, and used for the capture filename and the
    manifest row alike -- so a frame without a row, a row without a
    frame, and two frames sharing an index are all impossible without
    editing that one method.

    A session is deliberately cheap to open, because the honest way to
    drive this is one process per step: each `session.py step` recovers
    the counter from the append-only record and re-verifies that the
    record and the frames directory still agree before it presses
    anything.  Holding one long-lived instance works identically.

    Usage -- observe, decide in character, act, capture, log:

        session = Session()
        result = session.step(
            "u", "press 'u' for Custom Character",
            "I am not letting a dice roll decide who I am.")
        # read result.path and result.ingame_clock, THEN choose again
    """

    def __init__(self, manifest_path: Optional[str] = None,
                 frames_dir: Optional[str] = None,
                 observations_path: Optional[str] = None,
                 window_id: object = None,
                 capture_script: Optional[str] = None,
                 tool_timeout: Optional[int] = None,
                 capture_timeout: Optional[int] = None,
                 require_durable: bool = True,
                 root: Optional[str] = None) -> None:
        """Open a session against an existing or an empty record.

        :param manifest_path: the record to append to; the pipeline's
            own manifest by default.
        :param frames_dir: the capture directory to cross-check the
            record against.
        :param observations_path: the telemetry sidecar to append.
        :param window_id: a hint from launch_game.sh; re-verified
            before every keystroke, never trusted.
            $PLAYTHROUGH_WINDOW_ID is read when this is None.
        :param capture_script: the capturer; the one beside this module
            by default.
        :param require_durable: False weakens only the fsync step, for
            a scratch run whose record is not evidence.
        :param root: a test's own artifact tree.  A CALL-SITE argument
            only -- no environment variable reaches it.
        :raises RecordError: when the manifest and the frames directory
            do not agree, which must never be reconciled silently.
        """
        self._root = root
        self._manifest = (default_manifest_path(root)
                          if manifest_path is None
                          else _confined(manifest_path,
                                         "the manifest", root))
        self._frames = (default_frames_dir(root)
                        if frames_dir is None
                        else _confined(frames_dir,
                                       "the frames directory", root))
        self._observations = (
            default_observations_path(root)
            if observations_path is None
            else _confined(observations_path,
                           "the telemetry sidecar", root))
        self._capture = (capture_script_path()
                         if capture_script is None
                         else _executable(capture_script))
        self._tool_timeout = (
            _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
            if tool_timeout is None else int(tool_timeout))
        self._capture_timeout = (
            _timeout(ENV_CAPTURE_TIMEOUT, DEFAULT_CAPTURE_TIMEOUT)
            if capture_timeout is None else int(capture_timeout))
        self._require_durable = bool(require_durable)
        if window_id is None:
            hint = os.environ.get(ENV_WINDOW_ID, "").strip()
            self._window_hint: Optional[int] = (
                validate_window_id(hint) if hint else None)
        else:
            self._window_hint = validate_window_id(window_id)
        self._window: Optional[int] = None
        self._aborted: Optional[str] = None
        # The counter, recovered from the record rather than invented.
        self._frame = self._recover_counter()

    # -- state ------------------------------------------------------

    @property
    def frame(self) -> int:
        """The last index recorded, or 0 before the first step.

        Deliberately NOT "the next index": exposing that would mean
        computing the increment somewhere other than :meth:`step`, and
        one increment in one place is the whole guarantee.
        """
        return self._frame

    @property
    def manifest_path(self) -> str:
        """The record this session appends to."""
        return self._manifest

    @property
    def frames_dir(self) -> str:
        """The directory holding one PNG per keystroke."""
        return self._frames

    @property
    def observations_path(self) -> str:
        """The telemetry sidecar this session appends beside the row."""
        return self._observations

    @property
    def aborted(self) -> Optional[str]:
        """Why the session stopped, or None while it is usable.

        A keystroke is not undoable, so a failure after one has been
        delivered leaves the game somewhere this module can no longer
        account for.  The session is closed rather than continued, and
        this says what happened.
        """
        return self._aborted

    def _abort(self, reason: str) -> None:
        """Close the session, keeping the first reason it closed."""
        if self._aborted is None:
            self._aborted = reason

    def _assert_usable(self) -> None:
        """Refuse to act on a session that has already failed."""
        if self._aborted is not None:
            raise SessionError(
                "this session stopped and will not send another "
                "keystroke: %s.  A keystroke cannot be taken back, so "
                "the record is left exactly as it stands; inspect it, "
                "fix the cause, and start a new session, which "
                "recovers the counter from the manifest"
                % self._aborted)

    # -- the record -------------------------------------------------

    def _frames_on_disk(self) -> Tuple[str, ...]:
        """Return the capture filenames present, sorted.  VALIDATION.

        Read ONLY to check that the frames directory agrees with the
        manifest.  It is never the source of an index: counting files
        would be a second source of truth, and a capture that failed
        and was withdrawn -- or one written twice -- could silently
        renumber every frame after it.
        """
        if not os.path.isdir(self._frames):
            return ()
        try:
            entries = os.listdir(self._frames)
        except OSError as err:
            raise RecordError(
                "cannot read the frames directory %s: %s"
                % (self._frames, err)) from err
        return tuple(sorted(
            name for name in entries if name.endswith(".png")))

    def _recover_counter(self) -> int:
        """Return the last index recorded, having verified the record.

        THE MANIFEST IS THE AUTHORITY.  manifest.last_recorded_frame()
        reads the append-only record; the frames directory is then
        checked against it and a disagreement STOPS the session.

        Three disagreements are possible and each is fatal, because
        each one means the count identity verify_artifacts.sh asserts is
        already broken:

          * frames on disk with no manifest at all;
          * a different number of PNGs than rows;
          * a PNG whose row is missing, or a row whose PNG is missing.

        None of them is repaired here.  A record that has been silently
        renumbered is worse than a session that stops, because the
        renumbering is invisible afterwards.
        """
        on_disk = self._frames_on_disk()
        if not os.path.isfile(self._manifest):
            if on_disk:
                raise RecordError(
                    "%d capture(s) are in %s but there is no manifest "
                    "at %s.  Every frame is one keystroke and one row; "
                    "frames with no record cannot be paired with the "
                    "keystrokes that produced them, and this session "
                    "will not renumber them by guessing.  Move them "
                    "aside deliberately, or restore the manifest"
                    % (len(on_disk), self._frames, self._manifest))
            LOG.info("fresh session: no manifest at %s yet",
                     self._manifest)
            return 0
        problems = manifest.verify_manifest(
            self._manifest, self._frames, require_frames=True,
            root=self._root)
        if problems:
            raise RecordError(
                "the record at %s cannot be continued until it is "
                "sound.  %d problem(s):\n  %s"
                % (self._manifest, len(problems),
                   "\n  ".join(problems)))
        last = manifest.last_recorded_frame(self._manifest, self._root)
        expected = {manifest.FRAME_NAME_FORMAT % index
                    for index in _indices_through(last)}
        extra = sorted(set(on_disk) - expected)
        if extra:
            raise RecordError(
                "%s holds %d capture(s) the manifest does not mention "
                "(%s).  The record runs 1..%d, so those frames belong "
                "to no keystroke; the identity between the two is what "
                "proves one capture per key press, and it is not "
                "restored by ignoring them"
                % (self._frames, len(extra), ", ".join(extra), last))
        LOG.info("resuming at frame %d (%d row(s), %d capture(s))",
                 last, last, len(on_disk))
        return last

    def verify_record(self) -> Tuple[str, ...]:
        """Re-check the record against the frames.  Read-only.

        Exposed so a caller can assert the invariant between steps
        without opening a new session.  An empty result means the
        manifest satisfies its schema, every row's capture is on disk
        and no capture is unaccounted for.
        """
        if not os.path.isfile(self._manifest):
            on_disk = self._frames_on_disk()
            if on_disk:
                return ("%d capture(s) in %s with no manifest at %s"
                        % (len(on_disk), self._frames, self._manifest),)
            return ()
        problems = list(manifest.verify_manifest(
            self._manifest, self._frames, require_frames=True,
            root=self._root))
        last = manifest.last_recorded_frame(self._manifest, self._root)
        expected = {manifest.FRAME_NAME_FORMAT % index
                    for index in _indices_through(last)}
        for name in sorted(set(self._frames_on_disk()) - expected):
            problems.append(
                "%s is in %s but no row mentions it"
                % (name, self._frames))
        return tuple(problems)

    # -- the window -------------------------------------------------

    @property
    def window(self) -> Optional[int]:
        """The window id last resolved, or None before the first step.

        A cached answer, not a trusted one: :meth:`step` re-verifies it
        against the class search before every keystroke.
        """
        return self._window

    def refresh_window(self) -> int:
        """Resolve the game window again and remember it.

        Called before every keystroke.  The hint -- launch_game.sh's
        PLAYTHROUGH_WINDOW_ID, or the id resolved for the last step --
        is re-verified against `xdotool search --class`, so a window
        that has gone is reported as gone instead of being keyed into
        nothing.  When there was no hint the newest window of the class
        is taken, which is the instance a fresh launch just created.

        :raises WindowError: when no window of the class exists, or a
            remembered one no longer does.
        """
        hint = self._window if self._window is not None else (
            self._window_hint)
        self._window = find_window(hint, self._tool_timeout)
        return self._window

    # -- the capture ------------------------------------------------

    def _capture_frame(self, index: int) -> Dict[str, str]:
        """Run the capturer for exactly one index and parse its report.

        The index is HANDED IN through FRAME_INDEX, capture.sh's only
        input, so neither half of the step derives it twice.  The
        capturer owns the settle, the root-window photograph
        (`import -window root`: the root is 1920x1080 while the engine
        paints 1920x1072 at +0+4, so photographing the root needs no
        rescaling and leaves the 8x16 glyphs the clock read depends on
        crisp), the non-blank luminance gate and the clock read.

        `exit 0` from that script means exactly one NEW frame exists AND
        its whole payload was delivered; any other status means no frame
        was added, and this raises rather than appending a row.

        The working directory is the repository root, as it is for every
        stage: --userdir is normalised but not absolutised
        (src/path_info.cpp:105) and the asset roots are
        working-directory relative (src/path_info.cpp:127-137), so the
        root is the only place under which this checkout's own data/ and
        gfx/ resolve AND the artifacts land inside the working tree.
        """
        environment = _child_environment()
        environment[CAPTURE_ENV_INDEX] = str(index)
        completed = _run(
            [self._capture], self._capture_timeout,
            "capturing frame %05d" % index,
            env=environment, cwd=seed_options.repo_root())
        text = completed.stdout.decode("utf-8", "replace")
        if completed.returncode != 0:
            raise CaptureError(
                "capture.sh exited %d for frame %d (%s): %s.  No frame "
                "was added to %s, and the keystroke that produced this "
                "step has already been delivered, so the session "
                "stops: it cannot be un-pressed and a frame cannot be "
                "invented for it"
                % (completed.returncode, index,
                   CAPTURE_EXITS.get(completed.returncode,
                                     "unrecognised status"),
                   _diagnostic(completed), self._frames))
        return parse_payload(text)

    # -- THE STEP ---------------------------------------------------

    def step(self, key: str, action: str,
             commentary: str) -> StepResult:
        """Send ONE keystroke and record ONE frame.  The whole step.

        THIS IS THE ONLY PLACE THE FRAME COUNTER MOVES, and it moves
        once per call.  In order:

          1. validate the key, before anything can happen;
          2. focus the game window, found by class and re-verified;
          3. send EXACTLY ONE keystroke;
          4. let capture.sh settle, photograph the root window and read
             the sidebar clock -- one frame, at this step's index;
          5. check that the capture is the one this step asked for;
          6. append EXACTLY ONE manifest row;
          7. advance the counter;
          8. append the corroborating telemetry row.

        One key per call, always.  There is no argument that takes
        several, and adding one would destroy the one-frame-per-key
        relation in a way nothing downstream could repair.

        :param key: one keystroke, as a keysym name or a single
            printable character; validated against a closed vocabulary.
        :param action: what was pressed, plainly enough to be
            unambiguous -- :func:`describe_key` builds the usual form.
        :param commentary: the survivor's own first-person reason, in
            the voice playthrough/dossier.md establishes.  Engineering
            and meta observations belong in
            playthrough/TECHNICAL_NOTES.md, never here.
        :returns: a :class:`StepResult` carrying the frame path and the
            clock reading, so the caller reads what happened before
            choosing the next keystroke.
        :raises KeyRejected: for a value that is not one keystroke.
            Nothing was sent and the session stays usable.
        :raises WindowError, CaptureError, RecordError: after the
            keystroke has been delivered.  The session is closed: a
            keystroke cannot be taken back, so continuing would record
            later frames against a game state this module can no longer
            account for.
        """
        self._assert_usable()
        validated = validate_key(key)
        text = _required_text(action, "action")
        voice = _required_text(commentary, "commentary")
        self._advise_on_voice(voice)

        # The index this step owns.  ONE increment, ONE statement, and
        # the only one in this module: everything below -- the capture
        # filename, the payload check, the manifest row's `file` field
        # and the sidecar key -- is derived from this single value.
        index = validated_frame(self._frame + 1)

        try:
            window = self.refresh_window()
            focus_window(window, self._tool_timeout)
            send_key(window, validated, self._tool_timeout)
        except SessionError as err:
            # Nothing was captured and nothing was recorded.  A focus
            # or delivery failure still closes the session, because
            # whether the engine received the keystroke cannot be
            # established from here.
            self._abort("keystroke '%s' for frame %d could not be "
                        "delivered: %s" % (validated, index, err))
            raise

        try:
            payload = self._capture_frame(index)
            path = assert_payload_matches(index, payload, self._frames)
        except SessionError as err:
            self._abort(
                "frame %d was not captured after '%s' was pressed: %s"
                % (index, validated, err))
            raise

        clock = clock_from_payload(payload)
        try:
            row = manifest.append_row(
                self._manifest,
                index,
                manifest.frame_file(index),
                payload["REAL_TS"],
                clock,
                text,
                voice,
                require_durable=self._require_durable,
                root=self._root,
            )
        except manifest.ManifestError as err:
            self._abort(
                "frame %d was captured to %s but its row could not be "
                "appended to %s: %s.  The capture is on disk with no "
                "row, which breaks the frames-count == "
                "manifest-line-count identity; withdraw that PNG "
                "deliberately or repair the record before resuming"
                % (index, path, self._manifest, err))
            raise RecordError(self._aborted) from err

        # THE COUNTER ADVANCES HERE, and only once the row is on the
        # device.  The manifest is the authority for what was captured,
        # so a row that is stored is a frame that happened; anything
        # that fails after this point leaves a complete, consistent
        # record that the next session resumes from correctly.
        self._frame = index

        observation = observation_row(index, payload)
        try:
            append_observation(
                self._observations, observation,
                require_durable=self._require_durable,
                root=self._root)
        except SessionError as err:
            # The frame and its row are intact and the counter has
            # advanced, so the record is sound -- but the sidebar DATE
            # line for this frame is now missing, and timeline.py needs
            # it to tell a crossing of midnight from a clock that read
            # backwards.  That is real evidence lost, so it stops the
            # session loudly instead of degrading in silence.  Resuming
            # continues at the next index; this frame's date is
            # recovered by re-reading the PNG with
            # `ocr_clock.py --audit`, never by inventing one.
            self._abort(
                "frame %d is captured and recorded, but its telemetry "
                "row could not be appended to %s: %s"
                % (index, self._observations, err))
            raise

        result = StepResult(
            frame=index,
            key=validated,
            action=text,
            commentary=voice,
            file=row["file"],
            path=path,
            real_ts=row["real_ts"],
            ingame_clock=row["ingame_clock"],
            clock_status=payload.get("CLOCK_STATUS", ""),
            time_phrase=payload.get("TIME_PHRASE") or None,
            date=payload.get("DATE") or None,
            date_status=payload.get("DATE_STATUS", ""),
            geometry=payload.get("FRAME_GEOMETRY", ""),
            luma_mean=payload.get("LUMA_MEAN", ""),
            luma_stddev=payload.get("LUMA_STDDEV", ""),
            row=dict(row),
            observation=dict(observation),
        )
        LOG.info("%s", result.describe())
        return result

    def _advise_on_voice(self, commentary: str) -> None:
        """Warn when the commentary reads as meta rather than in voice.

        Advisory only, and never a rewrite: `commentary` is part of the
        in-character record, and the transcript gate downstream applies
        the same substring check, so a warning here predicts a failure
        there.  manifest.py owns the vocabulary; this only reports what
        it finds, once per word per process, so a habit is mentioned
        rather than nagged about.
        """
        found = manifest.find_meta_vocabulary(commentary)
        for word in found:
            _warn_once(
                "meta-%s" % word,
                "the commentary uses %r, which reads as an engineering "
                "observation rather than the survivor's own voice.  "
                "Meta and 'gamey' remarks belong in "
                "playthrough/TECHNICAL_NOTES.md; this text goes into "
                "playthrough/transcript.md and becomes a caption"
                % word)


# ---------------------------------------------------------------------
# The command line.
#
# Small on purpose, and one step at a time on purpose.  Driving a
# session as `session.py step` per keystroke IS the intended shape: each
# invocation recovers the counter from the append-only record and
# re-verifies that the record and the frames directory agree before it
# presses anything, so the loop cannot run ahead of the operator who is
# reading the frames.
#
# stdout is KEY=value, one per line, and nothing else -- the same
# machine contract capture.sh and launch_game.sh keep.  Every log,
# warning and diagnostic goes to stderr, which is also what keeps
# engineering observations out of the in-character record.
# ---------------------------------------------------------------------

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_RECORD = 2
EXIT_CAPTURE = 3
EXIT_WINDOW = 4
EXIT_CHEAT = 5

_EPILOG = """\
the permitted door, and the four that are shut
  Custom Character (hotkey u/U)   THE ONLY permitted new-game entry
  Preset Character                FORBIDDEN -- the template picker
  Random Character                FORBIDDEN
  Play Now!  (Default Scenario)   FORBIDDEN (two spaces after the !)
  Play Now!                       FORBIDDEN
  scenario                        missed / "Missed"
  first screen of a fresh userdir "Select your language", NOT the menu

no cheating, ever
  debug, debug_mode and debug_hour_timer ship UNBOUND in
  data/raw/keybindings.json, so no keystroke reaches them.  `audit`
  proves it against the committed <userdir>/config/keybindings.json,
  which this module reads and never writes.  No spawning, no stat
  editing, no teleport, no god mode, no map reveal -- for any reason,
  including avoiding death.

one key, one frame, one row
  `step` sends exactly one keystroke.  Several keystrokes are several
  invocations, and therefore several frames and several rows.  Read the
  frame and the clock this prints before choosing the next key.

how the session ends
  Only by realistic sleep or by death, with no in-game time cap, and
  then through the game's own Save & Quit path -- immediately after
  waking if the ending was sleep.  There is no `finish` subcommand: the
  exit is keystrokes, so it is `step` calls, so it is captured frames.
"""


def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(
        prog="session.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Send one keystroke to the running tiles build, capture "
            "exactly one frame for it, and append exactly one manifest "
            "row.  Sole owner of the frame counter."),
        epilog=_EPILOG)
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="log progress to stderr; repeat for debug detail")
    parser.add_argument(
        "--manifest", default=None, metavar="PATH",
        help="the record to append to (default: the pipeline's own)")
    parser.add_argument(
        "--frames-dir", default=None, metavar="DIR",
        help="the capture directory to check the record against")
    parser.add_argument(
        "--observations", default=None, metavar="PATH",
        help="the telemetry sidecar to append beside each row")
    sub = parser.add_subparsers(dest="command", required=True)

    step = sub.add_parser(
        "step", help="send ONE keystroke and record ONE frame")
    step.add_argument(
        "--key", required=True, metavar="KEY",
        help="one keystroke: a single printable character, or a keysym "
             "name such as Return, Escape, space or KP_7, optionally "
             "with ctrl/alt/shift/super/meta joined by '+'")
    step.add_argument(
        "--action", default=None, metavar="TEXT",
        help="what was pressed, plainly (default: \"press '<key>'\")")
    step.add_argument(
        "--commentary", required=True, metavar="TEXT",
        help="the survivor's own first-person reason for it")
    step.add_argument(
        "--window-id", default=None, metavar="ID",
        help="a decimal window id from launch_game.sh; re-verified")

    probe = sub.add_parser(
        "probe", help="report create-versus-resume, before any play")
    probe.add_argument(
        "--save-dir", default=None, metavar="DIR",
        help="the save directory to inspect (default: the userdir's)")
    probe.add_argument(
        "--world", default=None, metavar="NAME",
        help="which world to continue when more than one is resumable")
    probe.add_argument(
        "--json", action="store_true",
        help="report the decision and its evidence as JSON")

    window = sub.add_parser(
        "window", help="resolve the game window by class")
    window.add_argument(
        "--window-id", default=None, metavar="ID",
        help="re-verify this id instead of taking the newest")

    audit = sub.add_parser(
        "audit", help="prove no debug binding and a live points pool")
    audit.add_argument(
        "--keybindings", default=None, metavar="PATH",
        help="the user keybindings file to read (never written)")
    audit.add_argument(
        "--options", default=None, metavar="PATH",
        help="the options file to read the points pool from")
    audit.add_argument(
        "--skip-point-pools", action="store_true",
        help="omit the points-pool check, which only applies to a "
             "character being created")

    sub.add_parser(
        "status", help="report the counter and verify the record")
    return parser


def _configure_logging(verbosity: int) -> None:
    """Send logs to stderr, never to the machine payload."""
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level, stream=sys.stderr,
        format="playthrough: %(levelname)s: %(message)s")


def _emit(key: str, value: object) -> None:
    """Write one KEY=value line of the machine payload."""
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value)
    sys.stdout.write("%s=%s\n" % (key, text))


def _open_session(args: argparse.Namespace,
                  window_id: object = None) -> Session:
    """Build a Session from the parsed command line."""
    return Session(
        manifest_path=args.manifest,
        frames_dir=args.frames_dir,
        observations_path=args.observations,
        window_id=window_id,
    )


def _command_step(args: argparse.Namespace) -> int:
    """Send one keystroke, record one frame, report what it showed."""
    key = validate_key(args.key)
    action = args.action if args.action else describe_key(key)
    session = _open_session(args, args.window_id)
    result = session.step(key, action, args.commentary)
    _emit("FRAME_INDEX", result.frame)
    _emit("FRAME_FILE", result.file)
    _emit("FRAME_PATH", result.path)
    _emit("REAL_TS", result.real_ts)
    _emit("KEY", result.key)
    _emit("ACTION", result.action)
    _emit("CLOCK", result.ingame_clock)
    _emit("CLOCK_STATUS", result.clock_status)
    _emit("TIME_PHRASE", result.time_phrase)
    _emit("DATE", result.date)
    _emit("DATE_STATUS", result.date_status)
    _emit("FRAME_GEOMETRY", result.geometry)
    _emit("LUMA_MEAN", result.luma_mean)
    _emit("LUMA_STDDEV", result.luma_stddev)
    _emit("MANIFEST", session.manifest_path)
    _emit("OBSERVATIONS", session.observations_path)
    return EXIT_OK


def _command_probe(args: argparse.Namespace) -> int:
    """Report whether this session creates a character or resumes one."""
    probe = probe_save_resume(args.save_dir, args.world)
    if args.json:
        sys.stdout.write(
            json.dumps(probe.as_dict(), indent=2, ensure_ascii=False))
        sys.stdout.write("\n")
        return EXIT_OK
    _emit("PLAYTHROUGH_SESSION_MODE", probe.mode)
    _emit("PLAYTHROUGH_SAVE_DIR", probe.save_dir)
    _emit("PLAYTHROUGH_SAVE_WORLD", probe.world)
    _emit("PLAYTHROUGH_SAVE_WORLD_COUNT", len(probe.worlds))
    _emit("PLAYTHROUGH_SAVE_RESUMABLE_COUNT",
          len(probe.resumable_worlds))
    _emit("PLAYTHROUGH_SAVE_CHAR_COUNT", probe.character_count)
    _emit("PLAYTHROUGH_SAVE_CHAR_FORMS",
          ",".join(probe.character_forms))
    _emit("PLAYTHROUGH_SCENARIO", SCENARIO_ID)
    for note in probe.notes:
        LOG.info("%s", note)
    return EXIT_OK


def _command_window(args: argparse.Namespace) -> int:
    """Resolve the game window by class and report it."""
    identifier = find_window(args.window_id)
    _emit("PLAYTHROUGH_WINDOW_ID", identifier)
    _emit("PLAYTHROUGH_WINDOW_CLASS", window_class())
    _emit("DISPLAY", resolve_display())
    return EXIT_OK


def _command_audit(args: argparse.Namespace) -> int:
    """Prove the integrity conditions a session depends on."""
    finding = assert_no_debug_bindings(args.keybindings)
    _emit("DEBUG_BINDINGS", "none")
    _emit("DEBUG_ACTIONS_CHECKED", ",".join(DEBUG_ACTION_IDS))
    LOG.info("%s", finding)
    if args.skip_point_pools:
        _emit("POINT_POOLS", "")
        return EXIT_OK
    pools = assert_point_buy_available(args.options)
    _emit("POINT_POOLS", seed_options.POINT_POOLS_WANTED)
    _emit("MENU_ENTRY", MENU_CUSTOM_CHARACTER)
    LOG.info("%s", pools)
    return EXIT_OK


def _command_status(args: argparse.Namespace) -> int:
    """Report the counter and verify the record against the frames."""
    session = _open_session(args)
    problems = session.verify_record()
    _emit("FRAME_LAST", session.frame)
    _emit("MANIFEST", session.manifest_path)
    _emit("FRAMES_DIR", session.frames_dir)
    _emit("OBSERVATIONS", session.observations_path)
    _emit("RECORD_PROBLEMS", len(problems))
    for problem in problems:
        sys.stderr.write("playthrough: %s\n" % problem)
    return EXIT_RECORD if problems else EXIT_OK


_COMMANDS = {
    "step": _command_step,
    "probe": _command_probe,
    "window": _command_window,
    "audit": _command_audit,
    "status": _command_status,
}

_EXIT_FOR = (
    (CheatGuard, EXIT_CHEAT),
    (KeyRejected, EXIT_USAGE),
    (WindowError, EXIT_WINDOW),
    (CaptureError, EXIT_CAPTURE),
    (RecordError, EXIT_RECORD),
    (ToolMissing, EXIT_USAGE),
)


def _status_for(error: SessionError) -> int:
    """Return the exit status that names this failure."""
    for kind, status in _EXIT_FOR:
        if isinstance(error, kind):
            return status
    return EXIT_RECORD


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run one command.  Returns the process exit status.

    Every failure is reported on stderr with the cause named, and the
    status distinguishes a refused keystroke from a lost window, a
    failed capture, an unbelievable record and a cheat guard tripping,
    so a driver can tell "you asked for the wrong thing" apart from
    "the session is over".
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        return _COMMANDS[args.command](args)
    except SessionError as err:
        sys.stderr.write("playthrough: FATAL: %s\n" % err)
        return _status_for(err)
    except manifest.ManifestError as err:
        sys.stderr.write(
            "playthrough: FATAL: the record refused a row: %s\n" % err)
        return EXIT_RECORD
    except seed_options.SeedError as err:
        sys.stderr.write(
            "playthrough: FATAL: the options file could not be "
            "believed: %s\n" % err)
        return EXIT_RECORD
    except ocr_clock.OcrClockError as err:
        sys.stderr.write(
            "playthrough: FATAL: the capture toolchain refused: %s\n"
            % err)
        return EXIT_CAPTURE


if __name__ == "__main__":
    sys.exit(main())
