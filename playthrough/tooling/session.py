#!/usr/bin/env python3
"""The serialized keystroke step, and the SOLE owner of the frame counter.

ONE KEY, ONE PNG, ONE ROW.  One normal successful call to
:meth:`Session.step` authenticates the game window against the process
behind it, sends exactly one keystroke, lets capture.sh settle and
photograph the screen, reads the sidebar clock out of those pixels and
appends exactly one manifest row.  It is the only place in this pipeline
where the frame counter moves, and it moves once per call, under an
exclusive lock, with the intent to press made durable before the key
leaves.

THE STEP IS SERIALIZED, JOURNALED AND RECOVERABLE -- not atomic.  A
keystroke reaching an X server, a screenshot landing on disk and a row
reaching a file are three separate events in three processes, and no
mechanism available here makes them indivisible.  What is guaranteed is
narrower and stated as such: only one process advances the counter, the
intent to press is on the device before the key leaves, and an
interruption anywhere in the sequence leaves an IN-FLIGHT state that
BLOCKS every later key until recover() has dealt with it.  So the 1:1
identity is not maintained by hoping nothing is interrupted; it is
maintained by refusing to continue past an interruption.

THE INDEX IS COMPUTED IN ONE PLACE.  It is computed here, handed to
capture.sh, and used to build the manifest row's `file` field through
manifest.frame_file(), so a frame and its row cannot disagree about
which keystroke they belong to without editing this one function:

    take the step lock -- exactly one process may advance the counter
      -> audit the keybindings and re-check the pinned save decision
        -> authenticate the window against /proc
          -> journal the intent, forced to the device
            -> send EXACTLY ONE key with `xdotool key --window <id>`
              -> settle, then capture EXACTLY ONE PNG (capture.sh)
                -> journal the payload the capture reported
                  -> read the clock (ocr_clock.py, via capture.sh)
                    -> append EXACTLY ONE manifest row (manifest.py)
                      -> attest the key in the sidecar, clear the
                         journal, release the lock

THE ROW'S `action` IS DERIVED FROM THE KEY, never supplied beside it.
A caller passes the REASON; the identity half is computed from the same
validated string that reaches xdotool.  The first recorded session
carries a row reading `press 'X'` for a step that delivered `-`, which
satisfied every schema check downstream -- so a record that can say a
key was pressed which was not is not evidence, and the derivation is
what makes the two unable to differ.  The validated key itself is stored
in the telemetry sidecar, because the manifest's schema is exactly six
fields; see OBSERVATION_FIELDS and ATTESTED_FIELDS.

THE ROW ALSO CARRIES AN OBSERVATION, not only an intent.  Every capture
is compared with the one before it and the verdict is written into the
row: `nothing on the screen changed` when the two are identical pixel
for pixel, `nothing in the map column changed` when only a panel, a
counter or the message log moved.  This exists because the first
recorded session was found to contain 45 rows narrating events their own
capture contradicts -- nine letters of a world name "typed" into a
Yes/No question that had the screen, steps that never happened because
the map never moved, a phone chosen that was a sewing kit.  A keystroke
cannot be un-pressed, so the row is never REFUSED at that point; the
marker is appended to the note the operator wrote, both are kept, and a
warning goes to stderr so the NEXT row is written from the pixels.  See
THE OBSERVED-EFFECT GUARD, classify_effect() and annotate_action().

SHIFT IS THE ONLY MODIFIER THAT CAN BE SENT.  ctrl reaches the five
DEBUG_DIALOGUE_* toggles the game ships already bound; alt, super and
meta reach the window manager, alt+F4 included.  See MODIFIER_KEYS for
the evidence and PROHIBITED_CHORDS for the refusal messages.

Nothing here loops over keys.  There is deliberately NO helper that
takes a list of keystrokes: the operational directive is observe ->
decide in character -> act -> capture -> log, and a batching
convenience is precisely how that becomes blind key-spam.  A UI that
needs four keystrokes is four calls, four frames, four rows and four
transcript entries -- which is what "exactly one screenshot after
every single key press" means.

WHY A FAILED STEP STOPS THE SESSION, AND WHY IT NO LONGER LOSES A
FRAME.  A keystroke is not undoable: once xdotool has delivered it the
engine has already acted, and no retry can put the game back.  So the
session is marked aborted and every later step refuses -- but the
journal means the step itself is RECOVERABLE.  The next open finds the
outstanding entry and finishes that index: it appends the row from the
payload the capture reported, or, when no frame exists for the key at
all, re-authenticates the engine and captures one at the SAME index,
recording the attempt count and `recovered: true` beside it.  This is
the failure the first recorded session could not repair -- a delivered
`Y` whose black capture the non-blank gate correctly refused, leaving a
keystroke with no frame and no row -- and it is why the journal exists.
A key REFUSED before anything is sent is the opposite case: nothing
happened, nothing was journalled, and the session stays usable.

AND WHERE RECOVERY STOPS, BECAUSE ONE STATE IS GENUINELY UNKNOWABLE.
The journal records `sending` before the key leaves and `delivered` only
once xdotool has returned 0.  An interruption in between -- or xdotool
itself failing, which says nothing about whether the X server acted --
leaves `sending`, and NOTHING here resolves that: capturing a frame for
it would invent evidence for a keystroke that may never have happened,
and discarding it would drop one that did.  So the session HALTS and
`session.py reconcile --outcome delivered|not-delivered` is where
somebody who has looked at the game says which it was.  The earlier
design wrote one phase before the send and treated it on recovery as
delivered, which auto-committed a frame, a row and a first-person
sentence for a key that had not been pressed.

WHAT IS DECIDABLE BEFORE THE KEYSTROKE IS DECIDED BEFORE THE KEYSTROKE.
Opening a session proves the manifest is the ONE record this pipeline
writes -- the writer's own rule, applied at open through
manifest.assert_appendable() instead of when a row is written -- and
proves that both append targets, the manifest and the telemetry
sidecar, will take an append.  Neither condition depends on anything
the game does, so discovering either afterwards would spend the one
irreversible act for nothing: a key delivered, a frame captured, and no
row or no attestation to be written for it.

THE ATTESTATION IS PART OF THE IDENTITY, AND IT IS CHECKED.  One
keystroke is one frame, one manifest row AND one telemetry row, so
:meth:`Session.verify_record` compares all three: a recorded frame
whose sidecar row is missing is reported, because the sidecar is the
only place the immutable key and the sidebar date line were ever
written down, and a shortfall there cannot be repaired honestly
afterwards -- the key is not recoverable from the pixels.

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

AND THE PIN IS ENFORCED AT THE KEY, not only observed in the save tree.
A resumed session is in the `menu` UI phase until a captured frame shows
the sidebar, and while it is there the five main-menu hotkeys that open
a new survivor are REFUSED BEFORE send_key is reached -- because
comparing the save tree with what it looked like a keystroke ago detects
a second character only after the keystroke that created one has already
landed.  The save-set comparison now also runs IMMEDIATELY after each
key rather than before the next one, and when the sidebar first appears
the engine's own <userdir>/config/lastworld.json must name the pinned
world and character (src/main_menu.cpp:1080-1083), so "the existing save
was continued" is a checked property rather than an assurance.  The one
legitimate disappearance is the engine's own death cleanup: it is
accepted only when the graveyard save, character log, memorial pair and
captured post-death record all agree on the pinned survivor.  A bare
deletion, or any incomplete imitation of that evidence, still stops the
session.

CHARACTER CREATION HAS EXACTLY ONE PERMITTED DOOR, AND ITS HOTKEY IS A
TRAP.  The new-game submenu strings are quoted verbatim from
src/main_menu.cpp:475-483: "C<u|U>stom Character" is the only permitted
entry, and "<P|p>reset Character", "<R|r>andom Character", "Play Now!
(<D|d>efault Scenario)" (two spaces after the "!") and "Play N<o|O>w!"
are all forbidden.  BUT the top row of the same menu carries
"T<u|U>torial Game" (src/main_menu.cpp:466), whose hotkeys are the SAME
"u" and "U" -- and the top row wins.  Runtime testing caught this: the
second capture of the first recorded session shows the submenu folded
away and the top-row highlight sitting on [Tutorial Game] after a "u"
was sent for Custom Character, which took three Left presses to walk
back.  So the letter is never used for that entry -- and that is
ENFORCED rather than advised: a colliding letter whose own action or
commentary says it is meant for the custom sheet is REFUSED while the
observed UI phase is `menu`, before the journal and before delivery
(:meth:`Session._assert_menu_hotkey_permitted`).  An in-world "u" is the
north-east step and is never touched by it, because the phase is read
from the sidebar in the record rather than asserted.  The verified route
is MENU_CUSTOM_CHARACTER_ROUTE: reach [New Game] along the top row with
Left/Right, READ the capture to see which submenu row carries the
selection bar, move with Up/Down until it is on "Custom Character",
read again, and only then press Return.  The bar's opening position is
not assumed: on the first capture of this record it was on "Preset
Character", the template picker.  The scenario is "missed" / "Missed"
(data/json/scenarios.json), which starts the survivor in a house
inside a city.  Point-buy is a world option: CHARACTER_POINT_POOLS
defaults to "story_teller", at which the pool tab is read-only
(src/newcharacter.cpp:438-446, 462-467), so
:func:`assert_point_buy_available` refuses a create run whose options
file has not been seeded to "any" or "multi_pool".

AND THE ROUTE ITSELF IS GUARDED, not just the five letters.  A resumed
session may not reach the creator at all, and refusing only the hotkeys
would have refused only the shortcuts: the verified route is Left/Right,
Up/Down and Return, none of which is a new-survivor hotkey.  So while a
resumed session is on a menu, ANY keystroke whose own action or
commentary says it is opening the custom sheet is refused
(:meth:`Session._assert_key_allowed_in_phase`).  The launcher is coupled
in as well: launch_game.sh publishes the starting screen it VERIFIED as
$PLAYTHROUGH_INITIAL_UI_STATE, and :meth:`Session._assert_launch_state`
holds that against this module's own probe of the save tree, refusing to
open a session at all when the two disagree.  Neither addition can
permit anything -- both only refuse -- and every refusal here stands
whatever the launcher says, including when it says nothing.

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
import base64
import fcntl
import itertools
import json
import logging
import os
import re
import stat
import subprocess
import sys
import time

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
    import sidebar_geometry
except ImportError:  # pragma: no cover - flat siblings, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import manifest
    import ocr_clock
    import seed_options
    import sidebar_geometry

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
# ROOM FOR THE NEXT FRAME, CHECKED BEFORE THE KEY IS SENT.
#
# A session is deliberately unbounded and every capture is kept at full
# resolution, so the frames directory only ever grows.  A disk that
# fills DURING a step is the worst shape that failure can take: the
# keystroke has already been delivered and cannot be un-pressed, the
# capture is truncated or missing, and the one-frame-per-keystroke
# identity the whole record rests on is broken for a reason no later
# stage can repair.  Refusing BEFORE the key leaves the session exactly
# where it was.
#
# THE RESERVE IS SELF-CALIBRATING AND COSTS ONE SYSCALL.  It is the size
# of the PREVIOUS capture -- one stat of one file, never a walk of the
# directory, because a per-key directory walk is the O(N-per-key)
# pattern this module already has too much of -- multiplied by a
# lookahead, plus a fixed floor for the sidecars, the journal and the
# save the engine rewrites.  Sixty-four keystrokes of headroom is enough
# to notice and act without being so large that a small disk is refused
# a session it could have completed.
#
# There is no way to switch this off.  PLAYTHROUGH_CAPTURE_RESERVE sets
# the reserve exactly, for a host whose figures are unusual, and a
# session on a nearly full disk is a session that should stop.
CAPTURE_RESERVE_LOOKAHEAD = 64
CAPTURE_RESERVE_FLOOR = 16777216
CAPTURE_RESERVE_PER_FRAME_FLOOR = 65536
ENV_CAPTURE_RESERVE = "PLAYTHROUGH_CAPTURE_RESERVE"
MIN_CAPTURE_RESERVE = 1
MAX_CAPTURE_RESERVE = 1099511627776


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
# append-only, and NEITHER IS EVER REWRITTEN BY ANY CODE PATH IN THIS
# MODULE: the rewriters that used to sit here -- one for the sidecar,
# one called through into manifest.py -- were deleted after a security
# review found that a mechanism able to rewrite captured evidence makes
# every artifact derived from it deniable, and that rewriting two files
# in sequence leaves a window in which a crash splits the record.
#
# A correction is therefore an AMENDMENT: one row appended to
# playthrough/amendments.jsonl, keyed to the sha256 of the manifest line
# it concerns, applied to a derivative by manifest.resolve_rows() and to
# the record by nothing at all.  Because every correction lands in ONE
# artifact through ONE locked durable append, there is no longer any
# multi-file transaction to get wrong.  The human-readable account of
# what was amended and why belongs, as it always did, in
# playthrough/TECHNICAL_NOTES.md.
# ---------------------------------------------------------------------

ENV_OBSERVATIONS = "PLAYTHROUGH_OBSERVATIONS"
OBSERVATIONS_REL_PARTS = ("build", "observations.jsonl")

# The staging prefix for the sidecar, kept only so that leftovers can
# still be swept, on the same terms manifest.STAGING_PREFIX states for
# the record.  NOTHING WRITES ONE ANY MORE: this module could once
# rewrite the sidecar so that an attestation could be corrected in place
# alongside its manifest row, and code review found the pair of
# rewrites to be the defect rather than the fix -- captured evidence is
# not edited after the keystroke that produced it, and two independent
# renames could not be the all-or-nothing publication they claimed to
# be.  Both were removed; the sidecar is append-only.
#
# A sibling left by the retired writer, or by an interruption of it,
# would still be an untracked file inside the tree .gitignore
# re-includes wholesale, so sweep_observation_staging() still runs when
# a session opens.  The prefix matches the deterministic name that
# writer used and the unique names earlier versions produced, so one
# sweep clears every generation of them.
OBSERVATIONS_STAGING_PREFIX = ".observations-"
OBSERVATIONS_STAGING_SUFFIX = ".jsonl"
OBSERVATIONS_STAGING_OF = "the telemetry sidecar"

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
#
# THE SIDECAR ALSO CARRIES THE IMMUTABLE KEY, for the same reason: the
# manifest's six fields are fixed and none of them is the keystroke as a
# machine value.  `key` is the exact string handed to `xdotool key`,
# written by the one function that sends it, and `action` is the text
# derived from it -- so the record does not merely assert which key was
# pressed, it stores it in a form a reviewer can compare against the
# manifest row's prose without trusting either.  See ATTESTED_FIELDS.
# AND timeline.py RESTATES THIS SCHEMA AND VALIDATES EVERY ROW AGAINST
# IT.  It cannot import this module -- doing so would make Pillow and
# pytesseract a hard dependency of recomputing a timeline -- so
# timeline.OBSERVATION_FIELD_TYPES is the reader's copy of the contract
# and test_timeline.py round-trips a sidecar this writer produced to
# hold the two together.  A column added here without a type there is
# reported by the reader as unknown rather than silently half-read.
OBSERVATION_FIELDS = (
    ("frame", "FRAME_INDEX"),
    ("file", "FRAME_FILE"),
    # THE DIGEST OF THE BYTES THAT WERE PUBLISHED, taken by capture.sh
    # the instant the frame was renamed into place.  It is the column
    # that makes every other one mean something: without it a reader
    # knows the geometry and the luminance of *a* file at that path, and
    # has no way to establish that the pixels there are the pixels the
    # keystroke produced.  A security review found exactly that gap --
    # a same-sized, non-blank replacement passed the entire chain -- so
    # the digest travels here AND in the append-only attestation ledger
    # manifest.py owns, and every consumer verifies against it.
    ("frame_sha256", "FRAME_SHA256"),
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

# The fields this module contributes itself rather than copying off
# capture.sh's payload.  `key` is the keystroke as delivered, `action`
# the text derived from it, `capture_attempts` how many photographs the
# index needed (more than one means a capture was refused and retried at
# the SAME index, never renumbered), and `recovered` whether this row
# was completed from a pre-send journal entry after an interrupted step.
ATTESTED_FIELDS = ("key", "action", "capture_attempts", "recovered")


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
GRAVEYARD_DIR_NAME = "graveyard"
MEMORIAL_DIR_NAME = "memorial"
ENV_SAVE_DIR = "PLAYTHROUGH_SAVE_DIR"
ENV_CONFIG_DIR = "PLAYTHROUGH_CONFIG_DIR"

SESSION_MODE_CREATE = "create"
SESSION_MODE_RESUME = "resume"
ENV_RESUME_WORLD = "PLAYTHROUGH_RESUME_WORLD"

# seed_options.py owns this variable's name; it is reused rather than
# restated so the launcher, the seeder and this module cannot disagree
# about which one they mean.
ENV_SESSION_MODE = seed_options.ENV_SESSION_MODE

# THE LAUNCHER'S OWN STATEMENT ABOUT THE SCREEN THIS SESSION BEGINS ON.
# launch_game.sh publishes $PLAYTHROUGH_INITIAL_UI_STATE from what it
# VERIFIED after the captured launch came up -- for a resume, from a
# diagnostic capture of the sidebar region that establishes the engine is
# not already in the world -- and its own comment says the value exists
# "so session.py's own mode-aware refusal and the operator are working
# from the same declared state rather than from two assumptions".
#
# A security review found that coupling did not exist: nothing in this
# module had ever read the variable, so the launcher verified a state and
# this module went on assuming one.  It is read now, and it can only
# REFUSE -- a declared state that contradicts this module's own probe of
# the save tree stops the session before its first keystroke.  It never
# relaxes anything: every refusal below stands whatever the launcher says,
# including when it says nothing.
ENV_INITIAL_UI_STATE = "PLAYTHROUGH_INITIAL_UI_STATE"

# The launcher's vocabulary, quoted from launch_game.sh (:3225, :3247,
# :3643).  An empty value means the launcher did not establish a starting
# screen -- a build, headless or calibration phase, or a session driven
# without it -- and is legitimate.  Anything OUTSIDE this vocabulary is a
# refusal rather than a shrug: a value this module cannot reason about is
# not a value it may act on.
LAUNCH_STATE_UNDECLARED = ""
LAUNCH_STATE_LOAD_REQUIRED = "main-menu-load-required"
LAUNCH_STATE_CREATE_PERMITTED = "main-menu-create-permitted"
LAUNCH_STATE_UNVERIFIED = "unverified"
LAUNCH_UI_STATES = (
    LAUNCH_STATE_LOAD_REQUIRED,
    LAUNCH_STATE_CREATE_PERMITTED,
    LAUNCH_STATE_UNVERIFIED,
)


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

# The entry's OWN declared hotkeys (src/main_menu.cpp:476).  Kept
# because the declaration is a fact -- and marked here as unusable,
# because the top row of the same menu declares the same two letters for
# the tutorial (src/main_menu.cpp:466) and the top row wins.  See
# MENU_HOTKEY_COLLISION.
MENU_CUSTOM_CHARACTER_HOTKEYS = ("u", "U")
# ...and unusable is now enforced, not merely documented: see
# _assert_menu_hotkey_permitted, which refuses either letter while the
# observed UI phase is `menu` and the caller's own words say the key is
# meant for that entry.

MENU_TUTORIAL_ENTRY = "T<u|U>torial Game"

# THE COLLISION, and why no letter may be used to open the custom sheet.
# "u"/"U" belong to the top row's tutorial entry as well as to the
# submenu's Custom Character, and the observed winner is the top row:
# the submenu folds away and the highlight lands on [Tutorial Game].
MENU_HOTKEY_COLLISION = ("u", "U")

# The route that was actually verified, key by key, against the
# captures: Left/Right along the top row to [New Game], then Up/Down
# inside the submenu with the capture READ between presses, then Return.
# No letter, and no Return until the bar has been seen on the right row.
MENU_CUSTOM_CHARACTER_ROUTE = (
    "walk the top row with Left/Right to [New Game]",
    "read the capture: which submenu row carries the selection bar?",
    "move with Up/Down until the bar is on Custom Character",
    "read the capture again, then press Return",
)

MENU_FORBIDDEN_ENTRIES = (
    "<P|p>reset Character",
    "<R|r>andom Character",
    "Play Now!  (<D|d>efault Scenario)",
    "Play N<o|O>w!",
)

# EVERY HOTKEY THAT OPENS A NEW SURVIVOR, taken from the five entries
# above -- the one permitted door and the four that are shut.  They are
# the letters inside the <>: `u`/`U` for Custom Character, `p`/`P` for
# Preset, `r`/`R` for Random, `d`/`D` for Play Now! (Default Scenario)
# and `o`/`O` for Play Now!.
#
# WHY THIS SET IS ONLY REFUSED IN THE MENU PHASE OF A RESUMED SESSION.
# Every one of these letters is also an ordinary in-world command -- `r`
# reads, `p` and `o` and `d` are all bound to something a survivor does
# -- so refusing them outright would make a session unplayable, and
# refusing them by "what screen are we on" is the only refusal that is
# both correct and enforceable.  A resumed session is at the main menu
# until the pinned character is loaded, and while it is there NONE of
# these may be pressed: the existing save is continued, never replaced.
MENU_NEW_SURVIVOR_HOTKEYS = (
    "u", "U",   # Custom Character  -- the only permitted door, and even
                #                      it is shut while resuming
    "p", "P",   # Preset Character  -- the template picker
    "r", "R",   # Random Character
    "d", "D",   # Play Now!  (Default Scenario)
    "o", "O",   # Play Now!
)


# ---------------------------------------------------------------------
# THE OBSERVED SCREEN, read off the capture with the game's own font.
#
# WHY THIS EXISTS.  Refusing the five new-survivor letters refuses five
# doors, and refusing prose that SAYS it is opening the custom sheet
# refuses an honest caller.  Neither refuses the ROUTE: a code review
# demonstrated that ordinary, truthful-looking wording -- "move
# selection", "activate selected item" -- walks the verified
# MENU_CUSTOM_CHARACTER_ROUTE (Left/Right, Up/Down, Return) straight into
# the creator with the letter guard never firing and the prose guard
# never matching, and that the save pin only notices afterwards, once a
# second survivor's save already exists and the prohibited route has been
# taken AND photographed.
#
# So the route is enforced from the SCREEN instead of from the caller's
# words.  ocr_clock.read_column_by_glyphs() decodes a band of the capture
# cell by cell against data/font/Terminus.ttf -- the very font the engine
# drew it with -- so this is a reading of the photograph, not an OCR
# guess, and it is the same class of evidence the UI phase already comes
# from (SIDEBAR_READING_FIELDS).  Measured against the committed record:
# the two frames that show the submenu yield all four labels below, and
# 22 other frames spanning menus, the creator, the world dialog, play and
# the death screens yield none.
#
# The band is the BOTTOM of the capture, computed from the frame's own
# height rather than hard-coded, because that is where the engine draws
# the main menu's entry row and the submenu that opens above it.  A
# whole-screen decode is deliberately not used: on a frame dominated by
# the title's ASCII art the row-phase detection locks onto the art and
# the menu text is lost, which would report a screen that is plainly
# readable as unreadable.
# ---------------------------------------------------------------------

# The engine's own strings, quoted from the same source as
# MENU_CUSTOM_CHARACTER and MENU_FORBIDDEN_ENTRIES
# (src/main_menu.cpp:475-483) but WITHOUT the <> hotkey markup, because
# what is drawn on the screen has the brackets resolved away.
MENU_NEW_GAME_SUBMENU_LABELS = (
    "Custom Character",
    "Preset Character",
    "Random Character",
    "Play Now!",
)

# Two, not one.  The submenu draws all five entries together, so any two
# of them is conclusive -- while a single "Play Now!" or "Load" appearing
# in a message log, a book or a note is not, and a guard that refuses on
# one word the game might print anywhere would refuse the wrong screens.
MENU_SUBMENU_LABELS_REQUIRED = 2

# The main menu's entry row (src/main_menu.cpp:466-474), as drawn.  The
# row is the load route's own landmark: every screen the resumed route
# passes through -- the world list and the character list open above it
# -- carries it, and no other screen in the record does.
MENU_ENTRY_ROW_MARKERS = (
    "MOTD", "New Game", "Load", "World", "Tutorial Game", "Settings",
)
MENU_ENTRY_ROW_MARKERS_REQUIRED = 4

# How much of the capture the menu band covers, in grid rows.  23 rows
# reaches from the submenu's top rule to the bottom of the frame at the
# 240x67 grid this pipeline captures, and it is multiplied by the row
# height the options file yields rather than by an assumed 16.
MENU_BAND_ROWS = 23

# What the classifier can conclude.
SCREEN_MAIN_MENU = "main-menu"
SCREEN_NEW_GAME_SUBMENU = "new-game-submenu"
SCREEN_OTHER = "other"
SCREEN_UNREADABLE = "unreadable"

# The keys that CONFIRM the highlighted entry.  On the new-game submenu
# each one opens a new survivor, which is the door this guard shuts.
MENU_ACTIVATION_KEYS = ("Return", "KP_Enter", "space")

# The keys that move DEEPER into an open submenu -- onto another
# new-character entry.  Nothing in the load route needs one while the
# new-game submenu is on screen.
MENU_DESCENT_KEYS = (
    "Up", "Down", "KP_Up", "KP_Down", "Page_Up", "Page_Down",
    "Home", "End",
)

# The keys that walk AWAY from the new-game entry along the top row, or
# close the submenu outright.  These stay available at all times, because
# a guard that refused them would strand a resumed session on the one
# screen it must leave.
MENU_WITHDRAWAL_KEYS = (
    "Left", "Right", "KP_Left", "KP_Right", "Escape",
)

# The two UI phases this module distinguishes, and the ONLY evidence it
# accepts for the second.  `menu` is any screen the engine shows before a
# survivor is in the world; `in-world` begins when a captured frame
# carries a sidebar reading -- an exact clock, a coarse time phrase or
# the date line -- because the sidebar is drawn for a loaded character
# and for nothing else.  The phase is therefore OBSERVED from the pixels
# that were photographed, never asserted by the driver.
#
# AND IT IS RECOVERED FROM THE RECORD, not remembered.  `step` is one
# process per keystroke, so the phase a later step is refused or
# permitted by cannot live in memory: it is read back out of the
# telemetry sidecar's own reading columns -- SIDEBAR_READING_FIELDS
# below -- which is the stored form of exactly the payload
# _settle_ui_phase() classifies live.  A QA pass found the earlier
# recovery asking <userdir>/config/lastworld.json instead, which is the
# engine's statement about the PREVIOUS session's survivor and therefore
# already names the pinned character in any resumed session before this
# one has photographed anything; the refusal that is supposed to make
# "continue the existing save" impossible to violate consequently lapsed
# from the second frame onward.  File state cannot testify to what was
# photographed, and nothing but the photograph is accepted here.
UI_PHASE_MENU = "menu"
UI_PHASE_IN_WORLD = "in-world"

# The three telemetry columns that ARE a sidebar reading, named once so
# the live classification and the recovery ask the same question of the
# same evidence.  append_observation() copies them off capture.sh's
# payload (CLOCK, TIME_PHRASE, DATE -- see OBSERVATION_FIELDS), and
# _settle_ui_phase() classifies that payload as it arrives, so a row
# carrying any one of them is a photograph of a drawn sidebar.
SIDEBAR_READING_FIELDS = ("ingame_clock", "time_phrase", "date")

# <userdir>/config/lastworld.json, which main_menu::load_game() writes AT
# THE MOMENT a character is loaded -- `world_name` and the decoded
# `character_name` (src/main_menu.cpp:1080-1083), and again on save
# (src/game_io.cpp:763-766).  It is the engine's own statement about
# which survivor is being played, which is what makes "the pinned
# character was loaded" checkable rather than assumed.
LASTWORLD_NAME = "lastworld.json"

# Wording that says a caller believes this keystroke opens the custom
# sheet.  It guards TWO refusals and on its own it refuses nothing --
# every use of it also requires the observed UI phase to be `menu`,
# because "u" is the game's own north-east step and "Return" is how
# anything at all is confirmed:
#
#   * _assert_menu_hotkey_permitted -- the colliding letter u/U, which
#     lands on the tutorial rather than on the custom sheet;
#   * _assert_key_allowed_in_phase -- ANY key, during a RESUME.  The
#     five-hotkey refusal below is keyed on the letters, and the VERIFIED
#     route to Custom Character (MENU_CUSTOM_CHARACTER_ROUTE) uses none of
#     them: Left/Right, Up/Down and Return walk straight past it.  A
#     resumed session that says it is opening the creator is refused
#     whichever key it says it with.
CUSTOM_CHARACTER_MENTION_RE = re.compile(
    r"custom\s+(?:character|sheet|creator)", re.IGNORECASE)

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

# The five dialogue toggles data/raw/keybindings.json ships ALREADY
# BOUND, each to a ctrl chord.  They are audited too -- a user override
# for one of them is deliberate -- and, decisively, the chord that
# reaches each of them is refused outright by validate_key(), so no
# keystroke this module can be asked to send arrives at one whatever any
# keybindings file says.
DEBUG_DIALOGUE_ACTION_IDS = (
    "DEBUG_DIALOGUE_DL_CONDITIONAL",
    "DEBUG_DIALOGUE_DL_EFFECT",
    "DEBUG_DIALOGUE_RESP_CONDITIONAL",
    "DEBUG_DIALOGUE_RESP_EFFECT",
    "DEBUG_DIALOGUE_SHOW_ALL_RESPONSE",
)

# The audit matches on this substring rather than on a fixed list, so an
# action added to the engine after this was written is still audited.
DEBUG_ID_MARKER = "debug"

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
#
# SHIFT IS THE ONLY MODIFIER THIS MODULE WILL SEND, and that is a
# security control rather than a simplification.  Read against the
# shipped bindings, the whole modifier space divides cleanly:
#
#   * shift  -- 216 distinct actions in data/raw/keybindings.json use
#     it and NOT ONE of them is a debug action.  Every command a
#     survivor needs that is not a bare character is spelled this way:
#     `save` (Save and quit) is shift+s, `sleep` is shift+4,
#     `player_data` is shift+2, PREV_TAB is shift+TAB.
#   * ctrl   -- the ONLY ctrl bindings the game ships are the five
#     DEBUG_DIALOGUE_* toggles below, which are bound BY DEFAULT and
#     therefore reachable without anybody rebinding anything, plus
#     three text-field helpers (TEXT.CLEAR ctrl+u, TEXT.PASTE ctrl+v,
#     TEXT.CONFIRM ctrl+s).  Nothing needs the helpers -- BackSpace
#     clears and Return confirms -- and TEXT.PASTE would put a whole
#     clipboard behind one screenshot, which breaks the
#     one-frame-per-keystroke relation outright.  So ctrl buys nothing
#     and reaches a debug surface: it is refused entirely.
#   * alt, super, meta -- the game binds NO action to any of them.
#     Every chord that uses one therefore belongs to the window manager
#     or to the session itself: alt+F4 closes the window, alt+Tab and
#     alt+space are openbox's, ctrl+alt+* is the desktop's.  Closing
#     the engine that way would end the session outside the game's own
#     Save & Quit path, which is the one exit the requirements allow.
#     They are refused entirely.
#
# The refusal is therefore structural: no keystroke this module can be
# asked to send is capable of reaching a debug action or of terminating
# the engine behind the record's back.  PROHIBITED_CHORDS exists so the
# refusal MESSAGE can name what was asked for; the allow-list above is
# what does the work, and it would still refuse every one of them if
# that table were empty.
# ---------------------------------------------------------------------

MODIFIER_KEYS = frozenset({"shift"})
REFUSED_MODIFIER_KEYS = frozenset({"ctrl", "alt", "super", "meta"})
CHORD_SEPARATOR = "+"
MAX_KEY_LENGTH = 40

# The five debug actions data/raw/keybindings.json ships ALREADY BOUND,
# each to a ctrl chord, mapped to the action they would toggle.  Unlike
# "debug", "debug_mode" and "debug_hour_timer" -- which ship with no
# bindings array at all -- these need no user override to be reachable,
# which is exactly why the chord that reaches them must be refused
# rather than merely audited.
PROHIBITED_DEBUG_CHORDS = {
    "ctrl+c": "DEBUG_DIALOGUE_DL_CONDITIONAL",
    "ctrl+d": "DEBUG_DIALOGUE_RESP_CONDITIONAL",
    "ctrl+t": "DEBUG_DIALOGUE_DL_EFFECT",
    "ctrl+y": "DEBUG_DIALOGUE_RESP_EFFECT",
    "ctrl+r": "DEBUG_DIALOGUE_SHOW_ALL_RESPONSE",
}

# The two tables above describe the same five actions from the two sides
# -- the chord and the id -- so they are held against each other rather
# than trusted to have been edited together.
_REFUSED_DEBUG_ACTIONS = tuple(sorted(PROHIBITED_DEBUG_CHORDS.values()))
assert _REFUSED_DEBUG_ACTIONS == DEBUG_DIALOGUE_ACTION_IDS, (
    "the refused ctrl chords and DEBUG_DIALOGUE_ACTION_IDS name "
    "different actions")

# Chords that belong to the window manager or the process rather than to
# the game.  Named for the refusal message; the modifier allow-list
# already refuses each of them.
PROHIBITED_CONTROL_CHORDS = {
    "alt+f4": "closes the window, ending the session outside the "
              "game's own Save & Quit",
    "alt+tab": "switches windows, so the keystroke lands elsewhere",
    "alt+space": "opens the window manager's client menu",
    "ctrl+alt+delete": "a desktop or virtual-console chord",
    "ctrl+alt+f1": "a virtual-console chord",
}

PROHIBITED_CHORDS = dict(PROHIBITED_CONTROL_CHORDS)
PROHIBITED_CHORDS.update(
    {chord: "reaches %s, a debug action the game ships already bound"
            % action
     for chord, action in PROHIBITED_DEBUG_CHORDS.items()})

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


class CapacityError(SessionError):
    """There is not enough room to record the next frame safely.

    Raised BEFORE the keystroke is sent, which is the whole point: a
    disk that fills between the key and the capture produces a
    truncated frame or none at all for a keystroke the game has
    already acted on, and neither can be undone.  Refusing first
    leaves the session exactly where it was, so the operator frees
    space and presses the same key.
    """


class ObservationRequired(SessionError):
    """The capture before this one has not been read and classified.

    Raised BEFORE the keystroke is sent.  "Observe, decide in character,
    act" is a hard rule of this pipeline, and a rule enforced only by
    the operator's good intentions was measurably not enforced at all:
    frames 91-106 of the retired session were keyed into an unchanged
    modal because nobody read the picture between the keys.  So the
    reading is now a PRECONDITION of the next key, recorded durably
    before that key is delivered, and this is the refusal when it is
    missing.  Nothing was sent; supply the reading and press again.
    """


class GuardHalt(SessionError):
    """The capture contradicts what the step declared it would show.

    Raised AFTER the key was delivered and the frame and row were
    recorded -- deliberately in that order, because the keystroke and
    the photograph really happened and the record must say so.  What
    stops is everything AFTER them: the session refuses to deliver
    another key until an operator has read the capture and said what it
    shows (`session.py ack`).  This is the enforcing half of the
    observed-effect guard, which used to be advisory.
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
    fallback = os.path.join(
        manifest.approved_root(root), *OBSERVATIONS_REL_PARTS)
    return _from_env_or(
        ENV_OBSERVATIONS, fallback, "the telemetry sidecar", root)


def default_amendments_path(root: Optional[str] = None) -> str:
    """Return the amendment ledger this session may append to.

    manifest.py owns the ledger's name and its containment rules, in the
    same way it owns the manifest's; this wrapper exists so that a
    relocated tree -- a test's own artifact directory -- resolves to the
    ledger inside THAT tree rather than to the committed one.
    """
    return os.path.join(manifest.approved_root(root),
                        manifest.AMENDMENTS_NAME)


def default_digests_path(root: Optional[str] = None) -> str:
    """Return the capture attestation ledger this session appends to.

    manifest.py owns the ledger's name and its containment rules; this
    wrapper exists so a relocated tree -- a test's own artifact directory
    -- resolves to the ledger inside THAT tree.
    """
    return os.path.join(manifest.approved_root(root),
                        *manifest.DIGESTS_REL_PARTS)


def default_acknowledgments_path(root: Optional[str] = None) -> str:
    """Return the observe-before-the-next-key ledger for this tree.

    It lives beside the telemetry sidecar, in playthrough/build/, because
    it is the same kind of thing: a per-frame record about the CAPTURE
    rather than a row of the in-character account.  It is an artifact of
    the session and is committed with the rest, so the discipline the
    hard rule asks for is auditable after the fact instead of resting on
    the executing operator's word.
    """
    return os.path.join(manifest.approved_root(root), "build",
                        ACKNOWLEDGMENTS_NAME)


def manifest_target(candidate: Optional[str] = None,
                    root: Optional[str] = None) -> str:
    """Return the manifest to append to, held to the WRITER's own rule.

    THE ORDERING MATTERS MORE THAN THE RULE.  _confined() proves a path
    lies inside playthrough/ -- which EVERY artifact of this pipeline
    does, so containment alone accepts build/observations.jsonl, a
    frame, timeline.json or the movie as a "manifest".  The rule that
    the record lives at exactly <approved root>/manifest.jsonl belongs
    to manifest.py, and it used to be reached only when a row was
    written: by then a keystroke had been delivered and a frame
    captured for it, and a misconfiguration that is decidable from the
    path ALONE had already cost the one act this pipeline cannot take
    back.  So the writer's rule is applied HERE, at open, through
    manifest.assert_appendable() -- one implementation of it, applied
    earlier -- and $PLAYTHROUGH_MANIFEST goes through it too, because
    the environment is exactly where such a value comes from.

    :raises RecordError: naming what append_row() would have refused.
        RecordError rather than ManifestError so the exit status stays
        the one that already means "the record cannot be believed"; the
        cause is chained, so the writer's own diagnostic is preserved.
    """
    resolved = (default_manifest_path(root) if candidate is None
                else _confined(candidate, "the manifest", root))
    try:
        return manifest.assert_appendable(resolved, root)
    except manifest.ManifestError as err:
        raise RecordError(
            "this session cannot append to that manifest: %s.  NOTHING "
            "HAS BEEN SENT to the game: the name is decidable from the "
            "path alone, so it is refused while the record is still "
            "untouched rather than after a keystroke has bought a "
            "frame no row can be written for" % err) from err


def assert_append_target(target: str, label: str,
                         create_parent: bool = False) -> str:
    """Prove an append target will take an append.  Writes NOTHING.

    A step appends to two files -- the manifest, which is the record,
    and the telemetry sidecar, which carries the immutable key and the
    sidebar DATE line -- and both appends happen AFTER the keystroke.
    An unappendable target therefore used to be discovered at the worst
    possible moment: the key delivered, the frame captured, and for the
    sidecar the manifest row already stored, leaving the attestation
    permanently missing for that frame.  This is the pre-flight that
    moves that discovery to before the transaction, the same way the
    capturer and the external tools are pre-flighted.

    WHAT IS PROVED, exactly:

    * an EXISTING target is opened for appending with O_NOFOLLOW and
      closed again without a byte being written, which is the same
      descriptor discipline the writers use -- so a permission, an
      immutable flag (chattr +i), a read-only filesystem, a directory
      in the file's place and a planted symlink are all reported here
      rather than mid-step;
    * an ABSENT target's directory exists, is a directory, and admits
      creation as far as the kernel will say without writing to it
      (os.access, which reports a read-only filesystem even for uid 0).

    WHAT IS NOT PROVED, stated rather than implied: this is a check at
    a moment, not a reservation.  A target that becomes unappendable
    between this call and the append still fails at the append -- which
    is why the writers keep every one of their own guards, and why the
    step journal exists.  It removes the whole class of failures that
    was already true at open, which is the class an operator can fix.

    `create_parent` mirrors append_observation(), which creates the
    sidecar's directory itself; the manifest's directory is never
    created here, because manifest.py deliberately refuses to create it
    (a mistyped path would grow a second record elsewhere in the tree).

    :returns: `target`, so a caller can chain the call.
    :raises RecordError: naming the target, the label and the cause.
    """
    directory = os.path.dirname(target)
    if create_parent:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as err:
            raise RecordError(
                "cannot create %s for %s: %s" % (directory, label, err)
            ) from err
    # islink() as well as exists(), so a DANGLING symlink planted at the
    # name is opened (and refused by O_NOFOLLOW) rather than treated as
    # an absent file whose directory looks fine.
    if os.path.exists(target) or os.path.islink(target):
        try:
            descriptor = os.open(
                target, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        except OSError as err:
            raise RecordError(
                "%s at %s exists but cannot be appended to: %s.  A "
                "step appends to it after the keystroke, so this is "
                "refused now, while nothing has been sent and the "
                "record is exactly as it stands"
                % (label, target, err)) from err
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "append-preflight-close",
                "could not close %s after checking that %s is "
                "appendable (%s); nothing was written to it"
                % (target, label, err))
        return target
    if not os.path.isdir(directory):
        raise RecordError(
            "%s at %s does not exist and its directory %s is not "
            "there, so the first append of the session would fail "
            "after a keystroke had already been delivered"
            % (label, target, directory))
    if not os.access(directory, os.W_OK | os.X_OK):
        raise RecordError(
            "%s at %s does not exist yet and %s does not admit "
            "creating it, so the first append of the session would "
            "fail after a keystroke had already been delivered"
            % (label, target, directory))
    return target


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

    Derived from the APPROVED ROOT rather than from this module's own
    directory, so that a test which owns a temporary artifact tree gets
    that tree's userdir instead of the committed one.  With `root` unset
    the two are the same directory.
    """
    return _confined(
        os.path.join(manifest.approved_root(root), USERDIR_NAME),
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


def lastworld_path(root: Optional[str] = None) -> str:
    """Return <userdir>/config/lastworld.json.

    PATH_INFO::lastworld() = config_dir + "lastworld.json"
    (src/path_info.cpp:316-318).  Absent until a character has been
    loaded or saved, which is itself the answer on a fresh userdir.
    """
    return os.path.join(config_dir_path(root), LASTWORLD_NAME)


def decoded_character_name(save_name: object) -> Optional[str]:
    """Decode `#<b64>.sav` into the survivor's own name, or None.

    The engine names a character file `#` + base64 of the save id
    (src/catacharset.cpp:266-303, called from src/game_io.cpp), and
    lastworld.json records the DECODED name -- so comparing the two needs
    this one decode.  Two details of the engine's encoder matter and are
    the reason this is not a plain b64decode:

      * its alphabet's 63rd character is '-' rather than '/'
        (src/catacharset.cpp:215), hence `altchars`;
      * the '#' is a marker and not part of the payload
        (src/catacharset.cpp:269-272).

    Returns None for anything that does not decode to valid UTF-8.  An
    undecodable name is reported as unknown, never guessed at: it is used
    to CHECK which survivor was loaded, and a wrong answer there would
    approve continuing the wrong one.
    """
    if not isinstance(save_name, str) or not save_name:
        return None
    body = save_name
    for suffix in (COMPRESSED_SAVE_EXTENSION, SAVE_EXTENSION):
        if body.endswith(suffix):
            body = body[:-len(suffix)]
            break
    if not body.startswith(CHARACTER_PREFIX):
        return None
    body = body[len(CHARACTER_PREFIX):]
    if not body or len(body) % 4 != 0:
        return None
    try:
        return base64.b64decode(
            body.encode("ascii"), altchars=b"+-",
            validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def encoded_character_stem(character_name: object) -> Optional[str]:
    """Return the engine's `#<base64-name>` save stem, or None.

    This is the inverse of :func:`decoded_character_name`, using the
    engine's `+`/`-` alphabet rather than Python's default `+`/`/`
    alphabet.  Death cleanup moves the existing character files into
    <userdir>/graveyard/, so the stem is the immutable identity that
    binds the live save this session pinned to the graveyard generation
    the engine produced after death.
    """
    if not isinstance(character_name, str) or not character_name:
        return None
    encoded = base64.b64encode(
        character_name.encode("utf-8"),
        altchars=b"+-").decode("ascii")
    return CHARACTER_PREFIX + encoded


def read_lastworld(path: Optional[str] = None,
                   root: Optional[str] = None,
                   ) -> Optional[Tuple[str, str]]:
    """Return (world_name, character_name) from lastworld.json, or None.

    THE ENGINE'S OWN STATEMENT about which survivor is being played,
    written at the moment a character is loaded
    (src/main_menu.cpp:1080-1083).  None means the question has no answer
    yet -- no file, or a file this module will not interpret -- and every
    caller treats that as "not loaded" rather than as permission.
    """
    target = lastworld_path(root) if path is None else _confined(
        path, "the last-world record", root)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    except OSError as err:
        raise SessionError(
            "cannot read %s: %s.  It is the engine's own record of which "
            "survivor was loaded, and a resumed session is held against "
            "it" % (target, err)) from err
    try:
        record = json.loads(text)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    world = record.get("world_name")
    character = record.get("character_name")
    if not isinstance(world, str) or not isinstance(character, str):
        return None
    if not world.strip() or not character.strip():
        return None
    return world, character


# ---------------------------------------------------------------------
# THE STEP TRANSACTION'S SCRATCH STATE: the lock and the journal.
#
# Both live OUTSIDE the working tree, for the reason env.sh states about
# every other scratch path: the terminal `!/playthrough/**` negation in
# .gitignore would make anything inside it committable, and these are
# machinery, not artifacts.  The directory is per-checkout -- keyed by a
# digest of the approved root -- so two clones of this repository on one
# host serialise against themselves and not against each other.
# ---------------------------------------------------------------------

ENV_RUNTIME_DIR = "PLAYTHROUGH_RUNTIME_DIR"
ENV_XDG_RUNTIME_DIR = "XDG_RUNTIME_DIR"
SCRATCH_DIR_NAME = "playthrough"
SESSION_DIR_PREFIX = "session-"
STEP_LOCK_NAME = "step.lock"
JOURNAL_NAME = "step.json"

# THE PHASE INDEX: the third piece of scratch state, and the one that
# keeps a step's cost independent of how long the session has run.
#
# `step` is one process per keystroke, so the UI phase has to be
# recovered from the telemetry sidecar on every invocation
# (_recorded_sidebar_frame).  Reading the WHOLE sidecar to answer one
# question -- "which is the earliest recorded frame whose capture showed
# a sidebar?" -- costs O(rows) per step and therefore O(rows^2) over a
# session the requirements deliberately leave uncapped: a QA pass
# measured 87,571 cumulative row parses and 45.63 MiB of reads over the
# 419 frames already recorded, and nothing bounds either number.
#
# So the answer is CACHED here, next to the lock and the journal, with a
# byte cursor saying how much of the sidecar it was computed from.  A
# later step validates the cache in constant time and then reads only
# the bytes appended since -- one row, for one keystroke.
#
# THE SIDECAR REMAINS AUTHORITATIVE, which is the whole reason the
# record cites the row it rests on: the cached frame is accepted only
# when that row's exact bytes are still there and still say what the
# cache claims (PHASE_INDEX_VERSION and _load_phase_index).  A cache
# that cannot be validated is DISCARDED and rebuilt by reading the file,
# never trusted and never repaired -- the same posture every other
# derived value in this pipeline is held to.
#
# It lives outside the working tree for the reason stated above: this is
# machinery, not evidence, and it is rebuildable from the sidecar at any
# time, so losing it costs one full read and nothing else.
PHASE_INDEX_NAME = "phase.json"

# Bumped whenever the record's meaning changes.  An index written by an
# older version is discarded rather than reinterpreted.
PHASE_INDEX_VERSION = 1

# How long a step waits for another process holding the step lock.  A
# step is seconds of work, so a wait this long means a stuck run rather
# than a busy one, and saying so beats blocking for ever.
DEFAULT_LOCK_TIMEOUT = 120
ENV_LOCK_TIMEOUT = "PLAYTHROUGH_SESSION_LOCK_TIMEOUT"

# THE JOURNAL'S THREE PHASES, AND WHY THERE ARE THREE.
#
# There used to be two, `intent` and `captured`, and `intent` was
# written BEFORE xdotool ran.  Recovery then treated every `intent` for
# the next index as a delivered keystroke: it photographed the screen at
# that index and appended a row carrying the journalled key, action and
# commentary.  So an interruption in the window between the journal write
# and the key actually leaving -- a kill, an OOM, a lost X connection --
# produced a frame, a manifest row and a first-person sentence for a
# keystroke THAT NEVER HAPPENED, automatically, with `recovered: true`
# as the only trace.  That is fabricated evidence, which is the one thing
# this record may not contain.
#
# The phases now say what is actually known:
#
#   `sending`    the key has NOT been confirmed delivered.  It may have
#                been (xdotool's own failure says nothing about whether
#                the X server acted) or it may not.  DELIVERY IS
#                UNKNOWN, and an unknown is never resolved by this
#                module: recovery HALTS and asks for a decision from
#                somebody who can look at the game.
#   `delivered`  xdotool returned 0, so the keystroke reached the X
#                server, and no frame is recorded for it yet.  Recovery
#                photographs that index -- after re-authenticating and
#                re-focusing the engine -- and appends the row.
#   `captured`   the frame is committed to playthrough/frames/ and the
#                payload capture.sh reported for it is in the journal, so
#                the row is completed without re-photographing anything.
#
# The version is 2 BECAUSE of that change.  A version-1 journal says
# `intent`, whose meaning was ambiguous, so it is refused rather than
# reinterpreted: nothing may quietly decide after the fact that an
# ambiguous record meant "delivered".
JOURNAL_PHASE_SENDING = "sending"
JOURNAL_PHASE_DELIVERED = "delivered"
JOURNAL_PHASE_CAPTURED = "captured"
JOURNAL_PHASES = (
    JOURNAL_PHASE_SENDING,
    JOURNAL_PHASE_DELIVERED,
    JOURNAL_PHASE_CAPTURED,
)
JOURNAL_VERSION = 2

# What an operator declares to `session.py reconcile` about a `sending`
# journal, having established from the game itself which way it went.
RECONCILE_DELIVERED = "delivered"
RECONCILE_NOT_DELIVERED = "not-delivered"
RECONCILE_OUTCOMES = (RECONCILE_DELIVERED, RECONCILE_NOT_DELIVERED)


def _digest_of(text: str) -> str:
    """Return a short, stable digest of `text`.

    Used only to name a per-checkout scratch directory, so a short hex
    prefix is enough; it never authenticates anything.
    """
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _secure_dir(path: str, label: str) -> str:
    """Create `path` mode 0700, refusing a link or a foreign owner.

    The same rule env.sh's playthrough_secure_dir applies, restated here
    because this module is documented as runnable with nothing sourced.
    A directory another account can write to is a directory another
    account can plant a lock or a journal in.

    "MODE 0700" MEANS THE PERMISSION BITS, in both halves of that
    contract.  A directory created inside a set-group-ID parent inherits
    setgid -- /tmp is 2777 on some hosts -- and GNU chmod preserves that
    bit on a directory, so `stat` reads 2700 for a directory that is
    exactly as private as 0700.  The test below is therefore against the
    group and other bits alone, and env.sh compares only the permission
    digits for the same reason.  Neither side should be "tightened" to
    the whole mode string: that made a host with a setgid temporary
    directory able to run this module and not the shell contract.
    """
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError as err:
        raise SessionError(
            "cannot create %s at %s: %s" % (label, path, err)) from err
    try:
        info = os.lstat(path)
    except OSError as err:
        raise SessionError(
            "cannot inspect %s at %s: %s" % (label, path, err)) from err
    import stat as _stat
    if _stat.S_ISLNK(info.st_mode):
        raise SessionError(
            "%s at %s is a symbolic link; refused, because a link "
            "there redirects whatever is written through it"
            % (label, path))
    if not _stat.S_ISDIR(info.st_mode):
        raise SessionError(
            "%s at %s is not a directory" % (label, path))
    if info.st_uid != os.getuid():
        raise SessionError(
            "%s at %s is owned by uid %d, not by uid %d"
            % (label, path, info.st_uid, os.getuid()))
    if info.st_mode & 0o077:
        try:
            os.chmod(path, 0o700)
        except OSError as err:
            raise SessionError(
                "%s at %s is mode %o, which another account can read "
                "or write, and it could not be tightened: %s"
                % (label, path, info.st_mode & 0o777, err)) from err
    return path


def scratch_dir(root: Optional[str] = None) -> str:
    """Return this checkout's private scratch directory, mode 0700.

    env.sh's $PLAYTHROUGH_RUNTIME_DIR wins where it is set, so a sourced
    pipeline and a bare invocation land in the same place; then
    $XDG_RUNTIME_DIR, then /tmp keyed by uid.  A per-checkout
    subdirectory is appended in every case, which is what makes the step
    lock CHECKOUT-scoped: two clones must not block each other, and two
    processes over one clone must.
    """
    nominated = os.environ.get(ENV_RUNTIME_DIR, "").strip()
    if nominated:
        base = nominated
    else:
        runtime = os.environ.get(ENV_XDG_RUNTIME_DIR, "").strip()
        if runtime:
            base = os.path.join(runtime, SCRATCH_DIR_NAME)
        else:
            base = os.path.join(
                "/tmp", "%s-%d" % (SCRATCH_DIR_NAME, os.getuid()))
    _secure_dir(base, "the pipeline runtime directory")
    private = os.path.join(
        base,
        SESSION_DIR_PREFIX + _digest_of(manifest.approved_root(root)))
    return _secure_dir(private, "the session scratch directory")


def step_lock_path(root: Optional[str] = None) -> str:
    """Return the lock file that serialises one checkout's steps."""
    return os.path.join(scratch_dir(root), STEP_LOCK_NAME)


def journal_path(root: Optional[str] = None) -> str:
    """Return the pre-send journal for this checkout's step."""
    return os.path.join(scratch_dir(root), JOURNAL_NAME)


def phase_index_path(root: Optional[str] = None) -> str:
    """Return the cached UI-phase index for this checkout's record.

    Beside the lock and the journal, and outside the working tree for the
    same reason: see PHASE_INDEX_NAME.
    """
    return os.path.join(scratch_dir(root), PHASE_INDEX_NAME)


class StepLock:
    """The exclusive right to advance this checkout's frame counter.

    A KEYSTROKE IS NOT UNDOABLE, so two processes must never both
    decide that the next index is N.  Without this lock they can: each
    reads the same last-recorded frame, each sends a key, and the
    session ends up with two keystrokes behind one frame and one row --
    an unrecoverable break in the one-frame-per-keystroke relation that
    no later count would reveal, because the counts still match.

    The lock is an advisory flock over a file in the per-checkout
    scratch directory.  It is held from BEFORE the counter is recovered
    until AFTER the manifest row and its telemetry row are on the
    device, which is the whole transaction, and it is released by the
    kernel if the holder dies -- so a crashed session does not wedge
    the next one; the journal is what makes that next one recoverable.
    """

    def __init__(self, path: str, timeout: int) -> None:
        self._path = path
        self._timeout = int(timeout)
        self._descriptor: Optional[int] = None

    @property
    def path(self) -> str:
        """The lock file."""
        return self._path

    @property
    def held(self) -> bool:
        """True while this process holds the lock."""
        return self._descriptor is not None

    def acquire(self) -> None:
        """Take the lock, waiting at most the configured timeout.

        :raises SessionError: when another process holds it for longer
            than the timeout, or when the lock file cannot be opened.
            Nothing has been read or sent at that point.
        """
        if self._descriptor is not None:
            return
        try:
            descriptor = os.open(
                self._path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600)
        except OSError as err:
            raise SessionError(
                "cannot open the step lock %s: %s"
                % (self._path, err)) from err
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fcntl.flock(descriptor,
                            fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._descriptor = descriptor
                return
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise SessionError(
                        "another process has held the step lock %s for "
                        "more than %ds.  Exactly one process may "
                        "advance the frame counter: two would send two "
                        "keystrokes for one index, and a keystroke "
                        "cannot be taken back.  Wait for the running "
                        "step, or find out what is holding it"
                        % (self._path, self._timeout))
                time.sleep(0.1)

    def release(self) -> None:
        """Release the lock and close its descriptor."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as err:
            _warn_once(
                "step-lock-unlock",
                "could not release the step lock %s (%s); closing the "
                "descriptor releases it as well"
                % (self._path, err))
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "step-lock-close",
                "could not close the step lock %s (%s)"
                % (self._path, err))

    def assert_held(self) -> None:
        """Refuse to act outside the transaction.  Cheap, and checked.

        Called at the points that must never run unserialised -- the
        counter recovery, the key, the append -- so that a future edit
        which moved one of them out of the critical section would fail
        immediately instead of racing rarely.
        """
        if self._descriptor is None:
            raise SessionError(
                "the step lock %s is not held, so the frame counter "
                "must not move.  This is a programming error in the "
                "session, not a condition to retry" % self._path)


def _write_durably(path: str, text: str,
                   label: str = "the step journal") -> None:
    """Replace `path` with `text`, forced to the device.

    Written to a sibling and renamed, so a reader sees either the whole
    previous record or the whole new one; both the file and its
    directory are fsynced, because a rename is not durable until the
    directory entry is.

    `label` names the file in the failure message.  Every caller writes
    scratch state next to the step lock, so the temporary sibling is
    outside the working tree and cannot become a committable artifact --
    which is the concern that governs anything staged inside
    playthrough/ (see manifest.sweep_staging).
    """
    directory = os.path.dirname(path)
    temporary = "%s.%d.tmp" % (path, os.getpid())
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600)
        try:
            os.write(descriptor, text.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except OSError as err:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise SessionError(
            "could not record %s at %s: %s.  Scratch state this "
            "pipeline depends on is not reported as written until it is "
            "on the device, because a step that cannot be recovered "
            "afterwards is a keystroke nothing can account for"
            % (label, path, err)) from err


def write_journal(path: str, record: Mapping[str, object]) -> None:
    """Record the in-flight step's intent, durably."""
    text = json.dumps(
        dict(record), ensure_ascii=False, sort_keys=True)
    _write_durably(path, text + "\n")


def read_journal(path: str) -> Optional[Dict[str, object]]:
    """Return the outstanding step record, or None.

    A journal that cannot be parsed is a FAULT rather than an absence:
    it says a step was in flight and says nothing usable about which,
    so guessing would be exactly the fabrication this file exists to
    prevent.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    except OSError as err:
        raise RecordError(
            "cannot read the step journal %s: %s.  It records a "
            "keystroke that may have been delivered, so it is not "
            "ignored" % (path, err)) from err
    if not text.strip():
        return None
    try:
        record = json.loads(text)
    except ValueError as err:
        raise RecordError(
            "the step journal %s is not valid JSON (%s).  It records a "
            "keystroke that may have been delivered; repair or remove "
            "it deliberately, having established what happened, rather "
            "than letting a session continue past it"
            % (path, err)) from err
    if not isinstance(record, dict):
        raise RecordError(
            "the step journal %s holds a %s, not a step record"
            % (path, type(record).__name__))
    return record


def clear_journal(path: str) -> None:
    """Remove the journal once its step is completely recorded."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as err:
        raise RecordError(
            "could not clear the step journal %s: %s.  It would be "
            "replayed by the next session against a step that is "
            "already recorded" % (path, err)) from err
    try:
        parent = os.open(os.path.dirname(path),
                         os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(parent)
    except OSError:
        pass
    finally:
        os.close(parent)


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


def _summarised(indices: Sequence[int], limit: int = 10) -> str:
    """Render indices for a diagnostic, bounded but never rounded.

    A shortfall of three frames should name all three; a shortfall of
    three hundred should not print three hundred numbers into a
    terminal.  So the first `limit` are named and the remainder is
    COUNTED rather than dropped, because "and 290 more" still tells the
    reader the true size of what is missing.
    """
    shown = ", ".join(str(index) for index in indices[:limit])
    if len(indices) > limit:
        return "%s and %d more" % (shown, len(indices) - limit)
    return shown


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

    SHIFT IS THE ONLY MODIFIER ACCEPTED.  ctrl, alt, super and meta are
    refused outright: the game's only ctrl bindings are the five
    DEBUG_DIALOGUE_* toggles it ships already bound (plus text-field
    helpers nothing here needs), and it binds no action at all to alt,
    super or meta, so every such chord belongs to the window manager or
    to the process -- alt+F4 among them.  See the commentary above
    MODIFIER_KEYS for the evidence.

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
    # The refusal is reported against the WHOLE chord, folded to lower
    # case, so "Ctrl+R", "ctrl+r" and "CTRL+R" are one answer.  The
    # named table is consulted first only so the message can say what
    # the chord would have reached; the modifier rule below refuses it
    # either way, which is what makes this closed rather than a
    # blacklist somebody has to keep current.
    folded = key.lower()
    reason = PROHIBITED_CHORDS.get(folded)
    if reason is not None:
        raise KeyRejected(
            "%r is refused: it %s.  This module sends no chord that "
            "can reach a debug action or end the engine outside the "
            "game's own Save & Quit -- no debug menu, no debug mode, "
            "no hour timer, no dialogue toggles, for any reason and "
            "explicitly including avoiding death"
            % (key, reason))
    for modifier in modifiers:
        if modifier in REFUSED_MODIFIER_KEYS:
            raise KeyRejected(
                "%r modifies with '%s', which this module never sends. "
                "The game binds no action to alt, super or meta, and "
                "its only ctrl bindings are the five DEBUG_DIALOGUE_* "
                "toggles it ships already bound plus three text-field "
                "helpers nothing here needs -- so a '%s' chord either "
                "reaches a debug surface or belongs to the window "
                "manager.  '%s' is the only modifier accepted; every "
                "command a survivor needs is a bare character or a "
                "shift chord (Save and quit is 'shift+s', sleep is "
                "'shift+4')"
                % (key, modifier, modifier,
                   ", ".join(sorted(MODIFIER_KEYS))))
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

    THE MANIFEST'S `action` FIELD IS DERIVED FROM THIS AND NOWHERE
    ELSE.  It used to be free text a caller supplied alongside the key,
    which meant the two could disagree -- and did: one row of the first
    recorded session says `press 'X'` for a step that delivered `-`.
    The row satisfied every schema check, so nothing downstream could
    tell, and a record that can say a key was pressed which was not is
    not audit evidence at all.  Now the identity half of `action` is
    computed from the same validated string that reaches xdotool, so
    the two cannot differ.
    """
    return "press '%s'" % validate_key(key)


# The separator between the derived identity of a keystroke and the
# operator's note about WHY it was pressed.  The identity is machine
# checked; the note is prose and is not.
ACTION_SEPARATOR = " -- "


def build_action(key: str, note: object = None) -> str:
    """Return the manifest `action` text for one validated keystroke.

    `note` is the intent half -- "step one tile south, off the counter
    aisle" -- and it is APPENDED to the derived identity rather than
    replacing it, so every row names the key that was actually sent
    whatever else it says.

    :raises KeyRejected: for a key that is not one keystroke.
    :raises RecordError: for a note that is not text, or that carries
        the separator or a line break (either would make the derived
        prefix ambiguous to :func:`assert_action_derived`).
    """
    derived = describe_key(key)
    if note is None:
        return derived
    if not isinstance(note, str):
        raise RecordError(
            "the action note must be text, got %s"
            % type(note).__name__)
    text = note.strip()
    if not text:
        return derived
    if "\n" in text or "\r" in text:
        raise RecordError(
            "the action note must be one line; a manifest row is one "
            "line of JSON")
    if ACTION_SEPARATOR in text:
        raise RecordError(
            "the action note must not contain %r, which separates the "
            "keystroke this row records from the reason for it"
            % ACTION_SEPARATOR)
    return derived + ACTION_SEPARATOR + text


def assert_action_derived(key: str, action: object) -> str:
    """Return `action` if its identity is `key`'s, or raise.

    The gate that makes the manifest's `action` field evidence: it must
    be exactly :func:`describe_key`'s output, or that output followed by
    the separator and a note.  Anything else -- a different key named, a
    key named without the quotes, prose with no key in it -- is refused
    before the keystroke is sent.

    :raises RecordError: naming both texts, so the mismatch is obvious.
    """
    derived = describe_key(key)
    if not isinstance(action, str):
        raise RecordError(
            "the action must be text, got %s" % type(action).__name__)
    text = action.strip()
    if text == derived:
        return text
    if text.startswith(derived + ACTION_SEPARATOR):
        return text
    raise RecordError(
        "the action %r does not record the keystroke being sent.  "
        "Frame rows are evidence: the action must begin with %r -- "
        "optionally followed by %r and the reason -- so a row can "
        "never name a key other than the one delivered.  Pass the "
        "reason as the note and let this module derive the rest"
        % (text, derived, ACTION_SEPARATOR))


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


def _reserve_override() -> Optional[int]:
    """Return the reserve the environment names, in bytes, or None.

    A value that is SET but unreadable is refused rather than defaulted,
    for the same reason a timeout is: defaulting it silently would hide
    an operator's mistake behind a session that then fills the disk.
    """
    raw = os.environ.get(ENV_CAPTURE_RESERVE)
    if raw is None:
        return None
    text = raw.strip()
    if not text.isdigit():
        raise CapacityError(
            "$%s is %r, which is not a whole number of bytes from "
            "%d to %d"
            % (ENV_CAPTURE_RESERVE, raw, MIN_CAPTURE_RESERVE,
               MAX_CAPTURE_RESERVE))
    value = int(text, 10)
    if value < MIN_CAPTURE_RESERVE or value > MAX_CAPTURE_RESERVE:
        raise CapacityError(
            "$%s is %d byte(s), outside %d..%d.  There is deliberately "
            "no value that switches the reserve off: a session on a "
            "nearly full disk is one that should stop before the next "
            "keystroke rather than after it"
            % (ENV_CAPTURE_RESERVE, value, MIN_CAPTURE_RESERVE,
               MAX_CAPTURE_RESERVE))
    return value


def free_bytes(path: str) -> int:
    """Return the bytes available to this user where `path` lives.

    f_bavail rather than f_bfree, which is the difference between what
    an unprivileged writer may actually use and what exists before the
    filesystem's own reserved blocks are subtracted.  One syscall.
    """
    stats = os.statvfs(path)
    return int(stats.f_bavail) * int(stats.f_frsize)


def capture_reserve(previous_bytes: Optional[int] = None) -> int:
    """Return the bytes that must be free before the next keystroke.

    The size of the previous capture is the calibration -- the frames of
    one session are all the same geometry and broadly the same
    complexity, so the last one is a better predictor than any constant
    -- multiplied by a lookahead so there is room to notice and act, and
    floored so an unusually small frame cannot produce a reserve smaller
    than the sidecars and the save the engine rewrites.

    :param previous_bytes: the size of the last capture, or None when
        there is not one yet.
    """
    override = _reserve_override()
    if override is not None:
        return override
    per_frame = CAPTURE_RESERVE_PER_FRAME_FLOOR
    measured = (isinstance(previous_bytes, int) and
                not isinstance(previous_bytes, bool))
    if measured and previous_bytes > per_frame:
        per_frame = previous_bytes
    return per_frame * CAPTURE_RESERVE_LOOKAHEAD + CAPTURE_RESERVE_FLOOR


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

    THIS IS A LIVENESS CHECK, NOT AN IDENTITY CHECK.  The class is a
    name any process can claim, so nothing decides which window to key
    from this function's answer: :func:`authenticated_window` does that,
    against the process behind each candidate.  What this is for is
    confirming that an already-authenticated id is still on the display
    before a keystroke or a focus call is aimed at it.

    More than one match is therefore refused rather than resolved by
    taking the newest, which was a guess: two engines on one display
    means two sessions competing for one screen, and every capture
    photographs the root window.

    :raises WindowError: when no window of the class exists, when a
        preferred id is not among those that do, or when several match
        and none was named.
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
        raise WindowError(
            "%d windows of class '%s' are on display %s (%s) and none "
            "was named.  Two engines on one display means two sessions "
            "competing for one screen, and every capture photographs "
            "the root window, so which one is in the picture could not "
            "be established.  Stop all but one -- "
            "playthrough/tooling/launch_game.sh stop -- or resolve the "
            "instance with authenticated_window(), which checks the "
            "process behind each candidate"
            % (len(candidates), window_class(), resolve_display(),
               ", ".join(str(one) for one in candidates)))
    return candidates[-1]


# ---------------------------------------------------------------------
# WINDOW AUTHENTICATION.
#
# The class is a NAME, and a name is not an identity: any process on the
# display can set WM_CLASS to "cataclysm-tiles", and a second real
# engine -- a stray launch, another clone's instance sharing a display,
# a leftover calibration run -- carries the same class honestly.  Keying
# the newest match was a guess, and a guess here delivers a keystroke
# into a game whose state this record does not describe, which is
# unrecoverable in exactly the way a keystroke always is.
#
# So the window is AUTHENTICATED against the process behind it, from
# /proc, which the launcher already trusts for the same purpose:
#
#   _NET_WM_PID  ->  /proc/<pid>/exe      == this checkout's binary
#                    /proc/<pid>/cwd      == this checkout's root
#                    /proc/<pid>/cmdline  -- --userdir == our userdir
#                    /proc/<pid>/environ  -- DISPLAY   == our display
#
# and exactly ONE window of the class must pass, because two engines on
# one display means two sessions competing for one screen and every
# capture photographs the root window.  Multiplicity used to be a
# warning; it is now fatal.
# ---------------------------------------------------------------------

XPROP = "xprop"
NET_WM_PID = "_NET_WM_PID"

# seed_options owns the engine's identity -- the binary path and the
# --userdir spelling -- because it has to refuse an options write while
# that engine is running.  Reused here rather than restated.
USERDIR_FLAG = seed_options.USERDIR_FLAG
_XPROP_PID_RE = re.compile(r"=\s*(\d+)\s*\Z")


@dataclass(frozen=True)
class WindowIdentity:
    """The process a window belongs to, as read from /proc."""

    window: int
    pid: int
    executable: str
    cwd: str
    userdir: str
    display: str

    def describe(self) -> str:
        """A one-line account, for the log and for a refusal."""
        return ("window %d = pid %d, %s, cwd %s, --userdir %s, DISPLAY "
                "%s" % (self.window, self.pid, self.executable,
                        self.cwd, self.userdir, self.display))


def game_binary_path() -> str:
    """Return this checkout's tiles binary, absolute and canonical.

    seed_options owns the derivation -- $PLAYTHROUGH_GAME_BIN where it is
    set, the repository root's own ./cataclysm-tiles otherwise -- and it
    is reused rather than restated so the module that refuses to seed
    options underneath a live engine and the module that refuses to key a
    window cannot disagree about which binary "the engine" means.
    """
    return seed_options.engine_binary_path()


def _window_pid(window_id: int, timeout: int) -> int:
    """Return the pid that owns `window_id`, from _NET_WM_PID.

    :raises WindowError: when the property is absent or unreadable.  A
        window that will not say which process it belongs to cannot be
        authenticated, and an unauthenticated window is not keyed.
    """
    completed = _run(
        [_verified(XPROP), "-id", str(window_id), NET_WM_PID],
        timeout, "reading %s" % NET_WM_PID, env=_child_environment())
    text = completed.stdout.decode("utf-8", "replace").strip()
    if completed.returncode != 0 or not text:
        raise WindowError(
            "window %d does not report %s (xprop exited %d: %s).  A "
            "window that will not name its process cannot be shown to "
            "be this checkout's engine, and this module keys nothing it "
            "cannot identify"
            % (window_id, NET_WM_PID, completed.returncode,
               _diagnostic(completed)))
    match = _XPROP_PID_RE.search(text.split("\n")[0])
    if match is None:
        raise WindowError(
            "window %d reported %s as %r, which is not a pid"
            % (window_id, NET_WM_PID, text))
    return int(match.group(1), 10)


def _proc_link(pid: int, name: str) -> str:
    """Return a canonical /proc/<pid>/<name> link target, or raise."""
    path = os.path.join("/proc", str(pid), name)
    try:
        return os.path.realpath(os.readlink(path))
    except OSError as err:
        raise WindowError(
            "cannot read %s (%s), so the process behind the game "
            "window cannot be identified" % (path, err)) from err


def _proc_fields(pid: int, name: str) -> Tuple[str, ...]:
    """Return a NUL-separated /proc/<pid>/<name> file as fields."""
    path = os.path.join("/proc", str(pid), name)
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as err:
        raise WindowError(
            "cannot read %s (%s), so the process behind the game "
            "window cannot be identified" % (path, err)) from err
    return tuple(
        part.decode("utf-8", "replace")
        for part in raw.split(b"\x00") if part)


def _userdir_argument(argv: Sequence[str], cwd: str) -> str:
    """Return the --userdir the engine was started with, canonical.

    `--userdir <path>` and `--userdir=<path>` are both accepted, because
    both reach PATH_INFO::init_user_dir the same way.  The value is
    resolved against the process's OWN working directory, since
    src/path_info.cpp:105 normalises it without absolutising it.
    """
    for position, argument in enumerate(argv):
        if argument == USERDIR_FLAG:
            if position + 1 >= len(argv):
                break
            value = argv[position + 1]
        elif argument.startswith(USERDIR_FLAG + "="):
            value = argument[len(USERDIR_FLAG) + 1:]
        else:
            continue
        if not value:
            break
        return os.path.realpath(os.path.join(cwd, value))
    raise WindowError(
        "the process behind the game window was started without a "
        "usable %s, so it is not the instance this session records: "
        "the save would land outside playthrough/userdir/.  Its command "
        "line was: %s" % (USERDIR_FLAG, " ".join(argv)))


def _proc_display(pid: int) -> str:
    """Return the DISPLAY the process was started with, or ''.

    An unreadable environ is reported as unknown rather than as a
    failure: /proc/<pid>/environ is readable for this user's own
    processes, which the engine is, but a hardened kernel may refuse it
    and the other three checks are the load-bearing ones.
    """
    try:
        for entry in _proc_fields(pid, "environ"):
            if entry.startswith(ENV_DISPLAY + "="):
                return entry[len(ENV_DISPLAY) + 1:]
    except WindowError:
        return ""
    return ""


def authenticate_window(window_id: object,
                        timeout: Optional[int] = None,
                        root: Optional[str] = None) -> WindowIdentity:
    """Prove `window_id` belongs to THIS checkout's engine, or raise.

    :raises WindowError: naming the check that failed.  Nothing is sent
        to a window that does not pass.
    """
    if timeout is None:
        timeout = _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
    identifier = validate_window_id(window_id)
    pid = _window_pid(identifier, timeout)
    executable = _proc_link(pid, "exe")
    expected_binary = game_binary_path()
    if executable != expected_binary:
        raise WindowError(
            "window %d belongs to pid %d running %s, not this "
            "checkout's %s.  The class 'cataclysm-tiles' is a name any "
            "process can claim, so the process itself is checked; a "
            "keystroke is not sent to a window that only looks right"
            % (identifier, pid, executable, expected_binary))
    cwd = _proc_link(pid, "cwd")
    expected_cwd = os.path.realpath(seed_options.repo_root())
    if cwd != expected_cwd:
        raise WindowError(
            "window %d belongs to pid %d whose working directory is %s, "
            "not the repository root %s.  --userdir is normalised but "
            "not absolutised (src/path_info.cpp:105) and data/, gfx/ "
            "and lang/mo/ are working-directory relative "
            "(src/path_info.cpp:127-137), so an engine started "
            "elsewhere is reading other assets and writing its save "
            "outside this working tree"
            % (identifier, pid, cwd, expected_cwd))
    userdir = _userdir_argument(_proc_fields(pid, "cmdline"), cwd)
    expected_userdir = os.path.realpath(userdir_path(root))
    if userdir != expected_userdir:
        raise WindowError(
            "window %d belongs to pid %d started with %s %s, not this "
            "session's %s.  That instance's save lands somewhere this "
            "record does not describe"
            % (identifier, pid, USERDIR_FLAG, userdir,
               expected_userdir))
    display = _proc_display(pid)
    wanted_display = resolve_display()
    if display and display != wanted_display:
        raise WindowError(
            "window %d belongs to pid %d started with %s=%s, but this "
            "session captures %s.  Every capture photographs the root "
            "window of one display, so keying an engine on another one "
            "would record a screen it never drew"
            % (identifier, pid, ENV_DISPLAY, display, wanted_display))
    identity = WindowIdentity(
        window=identifier, pid=pid, executable=executable, cwd=cwd,
        userdir=userdir, display=display or wanted_display)
    LOG.debug("authenticated %s", identity.describe())
    return identity


def authenticated_window(prefer: object = None,
                         timeout: Optional[int] = None,
                         root: Optional[str] = None) -> WindowIdentity:
    """Return the ONE window of the class that passes authentication.

    Every candidate is authenticated, not just the preferred one, so
    that a second engine on the display is DETECTED rather than merely
    outranked.  More than one survivor is fatal: two engines on one
    display means two sessions competing for one screen, and the
    captures photograph the root window, so the record could not say
    which was in the picture.

    :raises WindowError: when nothing passes, when the preferred id does
        not, or when more than one does.
    """
    if timeout is None:
        timeout = _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
    candidates = window_ids(timeout)
    if not candidates:
        raise WindowError(
            "no window of class '%s' is on display %s.  The tiles "
            "build must already be running -- start it with "
            "playthrough/tooling/launch_game.sh -- and note that "
            "`xdotool search --name 'Cataclysm'` finds nothing for "
            "this window, so the class search is the only way to "
            "reach it" % (window_class(), resolve_display()))
    passed: List[WindowIdentity] = []
    refused: List[str] = []
    for candidate in candidates:
        try:
            passed.append(
                authenticate_window(candidate, timeout, root))
        except WindowError as err:
            refused.append("%d: %s" % (candidate, err))
    if not passed:
        raise WindowError(
            "%d window(s) of class '%s' are on display %s and NONE is "
            "this checkout's engine.  Each was checked against the "
            "process behind it:\n  %s"
            % (len(candidates), window_class(), resolve_display(),
               "\n  ".join(refused)))
    if len(passed) > 1:
        raise WindowError(
            "%d windows on display %s are all this checkout's engine "
            "(%s).  Two engines over one userdir would write one save "
            "between them, and every capture photographs the root "
            "window, so the record could not say which instance it "
            "shows.  Stop all but one -- "
            "playthrough/tooling/launch_game.sh stop -- and resume: the "
            "counter is recovered from the manifest"
            % (len(passed), resolve_display(),
               ", ".join(one.describe() for one in passed)))
    identity = passed[0]
    if prefer is not None:
        wanted = validate_window_id(prefer)
        if wanted != identity.window:
            raise WindowError(
                "window %d was expected but the authenticated engine on "
                "display %s is %s.  A stale id from a previous run is "
                "not keyed, and neither is a different instance"
                % (wanted, resolve_display(), identity.describe()))
    for note in refused:
        _warn_once(
            "window-refused-%s" % note.split(":", 1)[0],
            "a window of class '%s' on display %s is not this "
            "checkout's engine and was ignored -- %s"
            % (window_class(), resolve_display(), note))
    return identity


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
    # --clearmodifiers IS LOAD-BEARING, NOT TIDINESS.
    #
    # A key like 'Y' is not one X keystroke: xdotool implements it as
    # shift down, y, shift up.  If that trailing shift-up is lost -- and
    # it is, through `key --window`, which delivers synthetic events the
    # server never reconciles against real key state -- the modifier
    # stays DOWN for the rest of the session, and every plain key after
    # it arrives as Shift+key.  The game ignores those, xdotool still
    # exits 0, and this function still reports success.
    #
    # Measured: after one 'Y' confirmed a world, every subsequent Up,
    # Down, Return and Tab was silently discarded.  The engine was alive
    # and idle the whole time (main thread in hrtimer_nanosleep, 4 open X
    # connections, focus and active window both correct) and the screen
    # digest did not move for ninety seconds.  Releasing the stuck
    # modifiers and re-sending with --clearmodifiers moved it on the
    # first key.
    #
    # This is the worst failure shape this pipeline has: a keystroke
    # reported as delivered that the game never acted on, and a frame
    # captured against it.  The row would claim an action that did not
    # happen.  --clearmodifiers clears whatever is held before sending
    # and still applies the modifiers the key itself asks for, so
    # 'shift+Tab' and 'Y' keep working.
    completed = _run(
        [_verified(XDOTOOL), "key", "--clearmodifiers",
         "--window", str(identifier), validated],
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
    #: The frame at which the append-only record shows this world's
    #: pinned survivor entering the death sequence, or None when the
    #: record shows no such thing.  Populated by
    #: :func:`probe_save_resume` from the manifest and lastworld.json,
    #: never from the save's own contents -- see :attr:`resumable`.
    death_recorded_at: Optional[int] = None
    #: Whether the engine's death cleanup left its products behind.
    #: True only when BOTH the graveyard and the memorial directory
    #: exist; a signalled process leaves neither.
    cleanup_complete: bool = False

    @property
    def resumable(self) -> bool:
        """True when this world holds a character who can still be played.

        master.gsav proves a WORLD exists, not that anybody lives in
        it: the engine writes the world as soon as it is created, so a
        run interrupted during character creation leaves a world with
        no character at all.  Loading that opens an empty character
        list, which is a dead end, so it is not resumable.

        A CHARACTER SAVE IS NOT ENOUGH, AND SAVE SHAPE CANNOT SETTLE IT.
        This used to be `bool(self.characters)` alone, and a review found
        what that admits.  CDDA writes the character file during play and
        moves it to the graveyard in ``cleanup_at_end()``, which runs
        AFTER the death screen -- so a process that ends inside the death
        screen leaves a fully live-shaped save on disk for a survivor the
        record shows dying.  Measured on this checkout's own tree: the
        committed save reads as a living character (torso hp_cur 18 of
        83) because it was written before the killing blow, while the
        manifest records that survivor beginning their last words and
        neither graveyard/ nor memorial/ exists.  Nothing in the save
        distinguishes that from an ordinary mid-session snapshot, so no
        amount of reading it more carefully could have caught this; the
        evidence has to come from the append-only record instead.

        Resuming it would load a dead survivor back into play, which is
        not a continuation of the recorded session but a contradiction of
        it -- and it would do so silently, since the loaded character
        looks perfectly ordinary.  So a recorded death disqualifies the
        world while a live character save is still sitting in it,
        whichever way cleanup went: if cleanup never ran the save is a
        pre-death snapshot, and if it ran and a live save is somehow
        still present the tree is inconsistent.  Both are refusals.
        """
        return bool(self.characters) and self.death_recorded_at is None

    @property
    def death_pending(self) -> bool:
        """True for a recorded death whose cleanup never completed.

        The specific state a signalled process leaves: the record shows
        the death, the engine's own products do not exist, and the live
        save was never moved.  Separated from :attr:`resumable` because
        the two answer different questions -- that one decides whether to
        load, this one names the fault so the refusal can say what to do.
        """
        return (self.death_recorded_at is not None and
                not self.cleanup_complete)


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
                    # The death evidence travels with the decision it
                    # changed.  A consumer reading `resumable: false`
                    # against a world that plainly holds a character save
                    # would otherwise have no way to see why.
                    "death_recorded_at": one.death_recorded_at,
                    "cleanup_complete": one.cleanup_complete,
                    "death_pending": one.death_pending,
                }
                for one in self.worlds
            ],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DeathCleanupEvidence:
    """Engine-authored evidence that the pinned survivor really died.

    A vanished live save is not enough: manual deletion has exactly that
    shape.  The exception is admitted only when four independent
    artifacts agree -- the graveyard save and log, the JSON and text
    memorials, and the append-only manifest's last-words/post-death
    sequence.  The paths are returned so the checkpoint layer can hold
    these exact files against git after publication.
    """

    world: str
    character: str
    save_stem: str
    grave_save: str
    grave_log: str
    memorial_json: str
    memorial_text: str
    death_frame: int
    last_words: str


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

    EVERY DESCENDANT IS lstat-ed AND A LINK IS REFUSED.  os.path.isfile
    follows symbolic links, so a link planted at
    save/<World>/#<name>.sav would make an arbitrary file elsewhere on
    the host count as this session's character save -- and the resume
    decision turns on that count, so an external file could decide that
    a survivor exists (or, pointing at a directory, that one does not).
    Worse, the engine would then write the real save THROUGH the link,
    outside the committed tree, and R1 would fail while every count
    still matched.  A link here is deliberate and is reported, not
    skipped.
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
        candidate = os.path.join(world_dir, entry)
        try:
            info = os.lstat(candidate)
        except OSError as err:
            raise SessionError(
                "cannot inspect the character save %s: %s"
                % (candidate, err)) from err
        if stat.S_ISLNK(info.st_mode):
            raise SessionError(
                "%s is a symbolic link.  A character save must be a "
                "real file inside the committed tree: the engine writes "
                "the save through that name, so a link would put this "
                "session's save outside playthrough/userdir/ -- "
                "untracked, uncommittable and invisible to every gate. "
                "Remove the link deliberately, having established what "
                "it points at" % candidate)
        if not stat.S_ISREG(info.st_mode):
            raise SessionError(
                "%s is not a regular file (mode %o).  A character save "
                "is a file; a directory, a FIFO or a device node there "
                "is not this pipeline's and is not counted as one"
                % (candidate, info.st_mode))
        names.add(base)
        forms.add(form)
    return tuple(sorted(names)), tuple(sorted(forms))


def _real_directory(path: str) -> bool:
    """True when `path` is a real directory, not one reached by a link.

    The save root itself: absent is the create branch and is ordinary,
    but a link there would redirect the whole tree, so it is refused.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as err:
        raise SessionError(
            "cannot inspect the save directory %s: %s"
            % (path, err)) from err
    if stat.S_ISLNK(info.st_mode):
        raise SessionError(
            "the save directory %s is a symbolic link; refused, "
            "because the save must live inside the committed working "
            "tree at playthrough/userdir/save/ and a link puts it "
            "somewhere no commit can reach" % path)
    return stat.S_ISDIR(info.st_mode)


def _real_regular_file(path: str, label: str) -> bool:
    """True when `path` is a regular file and not reached by a link.

    lstat rather than os.path.isfile, and False rather than an
    exception, because an ABSENT file is an ordinary answer here -- a
    directory with no master.gsav simply is not a world.  A link is not
    an ordinary answer and is reported.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as err:
        raise SessionError(
            "cannot inspect %s at %s: %s" % (label, path, err)) from err
    if stat.S_ISLNK(info.st_mode):
        raise SessionError(
            "%s at %s is a symbolic link; refused, because the engine "
            "reads and writes the save tree through these names and a "
            "link takes it outside the committed working tree"
            % (label, path))
    return stat.S_ISREG(info.st_mode)


def _real_subdirectory(parent: str, name: str) -> Optional[str]:
    """Return `parent`/`name` when it is a real directory beneath it.

    None when it is not a directory at all.  A symlink is refused
    outright, and so is a directory whose canonical path escapes the
    canonical parent -- which is the mount-point and bind-mount case a
    realpath comparison catches and an lstat alone does not.
    """
    candidate = os.path.join(parent, name)
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        return None
    except OSError as err:
        raise SessionError(
            "cannot inspect %s: %s" % (candidate, err)) from err
    if stat.S_ISLNK(info.st_mode):
        raise SessionError(
            "%s is a symbolic link.  A world must be a real directory "
            "inside playthrough/userdir/save/: the engine writes the "
            "whole world through that name, so a link would put this "
            "session's save outside the committed tree while every "
            "count still matched.  Remove it deliberately, having "
            "established what it points at" % candidate)
    if not stat.S_ISDIR(info.st_mode):
        return None
    canonical_parent = os.path.realpath(parent)
    canonical = os.path.realpath(candidate)
    if canonical != os.path.join(canonical_parent, name):
        raise SessionError(
            "%s resolves to %s, which is not %s.  A world directory "
            "that canonicalises somewhere else is not inside the "
            "committed save tree, whatever its name says"
            % (candidate, canonical,
               os.path.join(canonical_parent, name)))
    return candidate


def _evidence_directory(parent: str, name: str, label: str) -> str:
    """Return one real evidence directory or refuse the missing check."""
    directory = _real_subdirectory(parent, name)
    if directory is None:
        raise CheatGuard(
            "%s is missing under %s, so a vanished live save is not "
            "evidenced as the engine's death cleanup"
            % (label, parent))
    return directory


def _evidence_listing(directory: str, label: str) -> List[str]:
    """List an evidence directory, failing closed on an unreadable one."""
    try:
        return sorted(os.listdir(directory))
    except OSError as err:
        raise CheatGuard(
            "cannot inspect %s at %s: %s.  Death cleanup is accepted "
            "only when every part of its evidence can be checked"
            % (label, directory, err)) from err


def _load_evidence_json(path: str, label: str) -> Mapping[str, object]:
    """Read one engine JSON artifact as an object, never as a guess."""
    if not _real_regular_file(path, label):
        raise CheatGuard(
            "%s is missing at %s, so the engine's death cleanup is not "
            "fully evidenced" % (label, path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, UnicodeError, ValueError) as err:
        raise CheatGuard(
            "%s at %s is unreadable as JSON: %s.  An unverifiable death "
            "artifact is a refusal, not an assumed match"
            % (label, path, err)) from err
    if not isinstance(record, dict):
        raise CheatGuard(
            "%s at %s is not a JSON object, so it cannot identify the "
            "survivor whose live save vanished" % (label, path))
    return record


def _memorial_names_avatar(value: object, character: str) -> bool:
    """True when a memorial stats tree names `character` as its avatar."""
    if isinstance(value, Mapping):
        named = value.get("avatar_name")
        if named == ["string", character]:
            return True
        return any(
            _memorial_names_avatar(one, character)
            for one in value.values())
    if isinstance(value, list):
        return any(
            _memorial_names_avatar(one, character) for one in value)
    return False


def _graveyard_files(userdir: str, save_stem: str
                     ) -> Tuple[str, str]:
    """Return the sole graveyard save and its same-generation log."""
    graveyard = _evidence_directory(
        userdir, GRAVEYARD_DIR_NAME, "the graveyard")
    saves: List[str] = []
    for generation_name in _evidence_listing(
            graveyard, "the graveyard"):
        generation = _real_subdirectory(graveyard, generation_name)
        if generation is None:
            continue
        for entry in _evidence_listing(
                generation, "a graveyard generation"):
            if not (entry.startswith(CHARACTER_PREFIX) and
                    entry.endswith(SAVE_EXTENSION)):
                continue
            candidate = os.path.join(generation, entry)
            if _real_regular_file(candidate, "a graveyard save"):
                saves.append(candidate)
    expected_name = save_stem + SAVE_EXTENSION
    expected = [
        one for one in saves if os.path.basename(one) == expected_name]
    if len(saves) != 1 or len(expected) != 1:
        raise CheatGuard(
            "the graveyard holds %d character save(s), with %d matching "
            "the pinned survivor %s.  Engine death cleanup for this "
            "one-survivor session must move exactly that one save"
            % (len(saves), len(expected), expected_name))
    grave_save = expected[0]
    grave_log = os.path.join(
        os.path.dirname(grave_save), save_stem + ".log")
    if not _real_regular_file(grave_log, "the graveyard character log"):
        raise CheatGuard(
            "the graveyard save %s has no same-generation character log "
            "at %s.  A lone copied save is not sufficient evidence of "
            "the engine's death cleanup" % (grave_save, grave_log))
    return grave_save, grave_log


def _memorial_files(userdir: str, world: str, character: str
                    ) -> Tuple[str, str]:
    """Return the sole JSON/text memorial pair for this survivor."""
    memorial = _evidence_directory(
        userdir, MEMORIAL_DIR_NAME, "the memorial directory")
    world_dir = _evidence_directory(
        memorial, world, "the pinned world's memorial directory")
    prefix = character + "-"
    json_files: List[str] = []
    text_files: List[str] = []
    for entry in _evidence_listing(
            world_dir, "the pinned world's memorial directory"):
        if not entry.startswith(prefix):
            continue
        candidate = os.path.join(world_dir, entry)
        if entry.endswith(".json") and _real_regular_file(
                candidate, "the JSON memorial"):
            json_files.append(candidate)
        if entry.endswith(".txt") and _real_regular_file(
                candidate, "the text memorial"):
            text_files.append(candidate)
    if len(json_files) != 1 or len(text_files) != 1:
        raise CheatGuard(
            "the memorial directory for world '%s' holds %d JSON and "
            "%d text memorial(s) for '%s'.  Engine death cleanup must "
            "produce one matching pair" %
            (world, len(json_files), len(text_files), character))
    return json_files[0], text_files[0]


#: The action-text markers that identify a captured death sequence.
#: Shared by the raising proof below and the non-raising observation
#: beside it, so the two cannot come to disagree about what a death
#: looks like in the record.
DEATH_LAST_WORDS_MARKER = "last words"
DEATH_POST_MARKERS = (
    "post-death",
    "after death",
    "deathcam",
    "scores screen",
    "follower epilogue",
)


def observed_death_frame(manifest_path: Optional[str] = None,
                         root: Optional[str] = None) -> Optional[int]:
    """Return the frame at which the record shows a death beginning.

    A PURE OBSERVATION, and deliberately the opposite shape to
    :func:`assert_death_cleanup_evidence`.  That function PROVES a
    vanished save was a legitimate engine death and raises on anything
    less; this one only reports what the append-only record says, because
    the resume probe has to ask the question about a tree that may be
    broken and must not be stopped by an exception in the middle of
    building its answer.

    AN ABSENT RECORD ANSWERS None; AN UNREADABLE ONE RAISES.  Those two
    are not the same fact and a review found them conflated here: both
    returned "the record shows no death", so a tree whose record
    authority was CORRUPT read exactly like a first run, and a
    live-shaped save that predated a death could be offered for resuming
    on the strength of a manifest nobody could parse.  Resuming such a
    save is the one thing this pipeline must never do -- it would be
    reloading past a death, which the plan forbids by name (AAP
    §0.2.1) -- so the two answers are now distinct:

    * a manifest that is genuinely ABSENT (a first run: no file at the
      path at all) answers None, which leaves resumability to be decided
      by the save contents exactly as it was before;
    * a manifest that EXISTS and cannot be read, decoded, or resolved
      against its own amendment ledger raises, because the question
      "did this tree record a death" then has no trustworthy answer and
      the caller must not proceed as though it were "no".

    THE ROWS ARE AMENDMENT-RESOLVED, not raw.  The ledger is this
    pipeline's only sanctioned way to correct a narration that described
    a capture wrongly, and `action` is exactly the field the death
    markers are read from, so a death screen NAMED correctly through the
    ledger has to be visible here.  manifest.resolve_rows() additionally
    fails closed on a stale amendment, which strengthens this
    observation rather than relaxing it.

    :returns: the frame of the first last-words action, or None when the
        record is genuinely absent.
    :raises RecordError: when a record that exists cannot be trusted.
    """
    # THE PATH IS RESOLVED AGAINST `root` BEFORE THE READ, and it has to
    # be, because neither of the obvious ways works.  manifest.read_rows
    # handed None defaults to the REAL pipeline's manifest and then
    # confines it against `root`; session.default_manifest_path does the
    # same thing one layer up.  So for any root but the live checkout both
    # of them REFUSE THEIR OWN DEFAULT, and the refusal reads back here as
    # "no death recorded" -- meaning a probe against any other tree would
    # always have answered "resumable", the exact wrong direction for a
    # fail-closed check.  Measured: the first version of this function
    # passed its own real-tree test and silently did nothing everywhere
    # else.
    #
    # manifest.approved_root is the single implementation of where the
    # artifact tree is, reused rather than restated so this cannot drift
    # from the writer's own idea of it.
    try:
        if manifest_path is None:
            manifest_path = os.path.join(
                manifest.approved_root(root), manifest.MANIFEST_NAME)
    except (OSError, ValueError, manifest.ManifestError,
            SessionError) as err:
        raise RecordError(
            "the record's own location could not be resolved (%s), so "
            "this tree cannot be asked whether it recorded a death.  A "
            "resume decision taken without that answer could reload "
            "past one, which is the one ending this pipeline may never "
            "step over" % err) from err
    # ABSENCE IS ANSWERED WITHOUT READING.  os.path.isfile is asked
    # BEFORE the read so that a missing file cannot be reported through
    # the same channel as a broken one: read_rows raises ManifestError
    # for both, and telling them apart afterwards would mean matching on
    # its message text.
    if not os.path.isfile(manifest_path):
        return None
    try:
        rows, _amended = manifest.resolve_rows(
            manifest.read_rows(manifest_path, root),
            manifest.read_amendments(
                os.path.join(os.path.dirname(manifest_path),
                             manifest.AMENDMENTS_NAME),
                root),
            manifest.row_digests(manifest_path, root))
    except (OSError, UnicodeError, ValueError,
            manifest.ManifestError, SessionError) as err:
        raise RecordError(
            "the record at %s exists but cannot be read as evidence "
            "(%s), so whether this tree recorded a death is UNKNOWN "
            "rather than 'no'.  It is refused here instead of being "
            "answered: a live-shaped save that predates a death would "
            "otherwise be offered for resuming on the strength of a "
            "record nobody can parse.  Repair or remove the record and "
            "its amendment ledger, then probe again"
            % (manifest.relative_to_repo(manifest_path), err)) from err
    for row in rows:
        frame = row.get("frame")
        action = str(row.get("action") or "").lower()
        if DEATH_LAST_WORDS_MARKER in action and isinstance(frame, int):
            return frame
    return None


def _death_cleanup_present(root: Optional[str] = None) -> bool:
    """True when both engine death-cleanup directories exist.

    ``cleanup_at_end()`` writes the graveyard generation and the memorial
    pair; a process signalled inside the death screen writes neither.
    This is a presence test rather than the full four-artifact proof --
    that is :func:`assert_death_cleanup_evidence`'s job -- because the
    probe needs to distinguish "cleanup ran" from "cleanup never ran",
    not to validate a cleanup that did.
    """
    userdir = userdir_path(root)
    return all(
        _real_directory(os.path.join(userdir, name))
        for name in (GRAVEYARD_DIR_NAME, MEMORIAL_DIR_NAME))


def _manifest_death_observation(
        manifest_path: Optional[str], root: Optional[str],
        last_words: str) -> int:
    """Return the first last-words frame in a captured death sequence.

    READS THE RESOLVED RECORD, NOT THE RAW ROWS.  The amendment ledger
    is this pipeline's ONLY sanctioned way to correct a narration that
    described a capture wrongly, and a row's action is exactly the field
    these markers are read from.  A proof that consulted the raw rows
    would therefore reject a record whose death screens had been named
    correctly through the ledger, while accepting one whose original
    wording happened to contain a marker -- which is the wrong way
    round.  manifest.resolve_rows() also FAILS CLOSED on a stale
    amendment, so routing through it strengthens this proof rather than
    relaxing it: an amendment whose sha256 no longer matches the line it
    names raises here instead of being silently ignored.
    """
    # The ledger is a SIBLING of the manifest it corrects, so an
    # explicit manifest path carries its own ledger with it.  Asking for
    # the default would resolve the pipeline's own playthrough/ directory
    # and then fail validation against a caller-supplied root -- which is
    # every caller that works in a scratch tree.
    amendments_path = None
    if manifest_path is not None:
        amendments_path = os.path.join(
            os.path.dirname(manifest_path), manifest.AMENDMENTS_NAME)
    try:
        rows, _amended = manifest.resolve_rows(
            manifest.read_rows(manifest_path, root),
            manifest.read_amendments(amendments_path, root),
            manifest.row_digests(manifest_path, root))
    except (OSError, UnicodeError, ValueError,
            manifest.ManifestError) as err:
        raise CheatGuard(
            "the append-only record cannot be checked for the captured "
            "death sequence: %s" % err) from err
    last_words_frame: Optional[int] = None
    post_death_frame: Optional[int] = None
    words_recorded = not last_words
    # The shared markers, so this proof and observed_death_frame's
    # observation cannot come to disagree about what a death looks like
    # in the record -- a divergence there would let one of them see a
    # death the other did not.
    post_markers = DEATH_POST_MARKERS
    for row in rows:
        frame = row.get("frame")
        action = str(row.get("action") or "")
        commentary = str(row.get("commentary") or "")
        lowered = action.lower()
        if (last_words_frame is None and
                DEATH_LAST_WORDS_MARKER in lowered):
            if isinstance(frame, int):
                last_words_frame = frame
        elif (last_words_frame is not None and
              isinstance(frame, int) and frame > last_words_frame and
              any(marker in lowered for marker in post_markers)):
            post_death_frame = frame
        if last_words and last_words.lower() in (
                action + "\n" + commentary).lower():
            words_recorded = True
    if last_words_frame is None or post_death_frame is None:
        raise CheatGuard(
            "the manifest does not contain a captured last-words screen "
            "followed by a captured post-death screen.  Graveyard files "
            "alone cannot prove that this recorded session observed the "
            "death cleanup it is asking to accept")
    if not words_recorded:
        raise CheatGuard(
            "the memorial records last words %r, but no manifest action "
            "or commentary records that same text" % last_words)
    return last_words_frame


def assert_death_cleanup_evidence(
        world: str, character: str, expected_stem: Optional[str] = None,
        manifest_path: Optional[str] = None,
        root: Optional[str] = None) -> DeathCleanupEvidence:
    """Prove a vanished live save is the engine's legitimate death path.

    CDDA moves the character files into a timestamped graveyard
    generation, writes JSON and text memorials, then may reset the world
    according to WORLD_END.  That is observably different from a manual
    deletion only when ALL of those products agree with the survivor
    lastworld.json says was loaded and the append-only record shows the
    death UI.  This function is that fail-closed distinction.
    """
    if not isinstance(world, str) or not world.strip():
        raise CheatGuard(
            "death cleanup has no pinned world to attribute it to")
    if not isinstance(character, str) or not character.strip():
        raise CheatGuard(
            "death cleanup has no pinned survivor to attribute it to")
    save_stem = encoded_character_stem(character)
    if save_stem is None:
        raise CheatGuard(
            "the pinned survivor's name cannot be encoded as a save")
    if expected_stem is not None and expected_stem != save_stem:
        raise CheatGuard(
            "lastworld.json names '%s', whose save stem is %s, but the "
            "live save that vanished was %s" %
            (character, save_stem, expected_stem))

    userdir = userdir_path(root)
    grave_save, grave_log = _graveyard_files(userdir, save_stem)
    grave = _load_evidence_json(grave_save, "the graveyard save")
    player = grave.get("player")
    player_name = (
        player.get("name") if isinstance(player, Mapping) else None)
    if player_name != character:
        raise CheatGuard(
            "the graveyard save names player %r rather than the pinned "
            "survivor %r" % (player_name, character))
    if grave.get("debug_mode") is not False:
        raise CheatGuard(
            "the graveyard save does not record debug_mode=false; a "
            "death ending cannot relax the no-cheating evidence")

    memorial_json, memorial_text = _memorial_files(
        userdir, world, character)
    memorial = _load_evidence_json(
        memorial_json, "the JSON memorial")
    entries = memorial.get("log")
    messages = [
        str(one.get("message") or "")
        for one in entries
        if isinstance(one, Mapping)
    ] if isinstance(entries, list) else []
    if "%s was killed." % character not in messages:
        raise CheatGuard(
            "the JSON memorial does not say that %s was killed"
            % character)
    if "Died" not in messages:
        raise CheatGuard(
            "the JSON memorial has no terminal 'Died' event")
    if not _memorial_names_avatar(memorial, character):
        raise CheatGuard(
            "the JSON memorial's death statistics do not name %s as "
            "the avatar" % character)
    last_words = ""
    for message in messages:
        if message.startswith("Last words: "):
            last_words = message[len("Last words: "):]
            break

    if not _real_regular_file(memorial_text, "the text memorial"):
        raise CheatGuard(
            "the text memorial is missing at %s" % memorial_text)
    try:
        with open(memorial_text, "r", encoding="utf-8") as handle:
            memorial_prose = handle.read()
    except (OSError, UnicodeError) as err:
        raise CheatGuard(
            "the text memorial cannot be read: %s" % err) from err
    if "In memory of: %s" % character not in memorial_prose:
        raise CheatGuard(
            "the text memorial is not in memory of %s" % character)
    if " died on " not in memorial_prose:
        raise CheatGuard(
            "the text memorial does not record when the survivor died")

    death_frame = _manifest_death_observation(
        manifest_path, root, last_words)
    return DeathCleanupEvidence(
        world=world,
        character=character,
        save_stem=save_stem,
        grave_save=grave_save,
        grave_log=grave_log,
        memorial_json=memorial_json,
        memorial_text=memorial_text,
        death_frame=death_frame,
        last_words=last_words,
    )


def probe_save_resume(save_dir: Optional[str] = None,
                      requested_world: Optional[str] = None,
                      root: Optional[str] = None,
                      refuse_recorded_death: bool = True) -> SaveProbe:
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
    :param root: the artifact tree to probe under, for a test with its
        own; defaults to the pipeline's playthrough/ directory.  A
        CALL-SITE argument only -- no environment variable can move it.
    :param requested_world: the world to continue;
        $PLAYTHROUGH_RESUME_WORLD by default.
    :param refuse_recorded_death: whether a live save belonging to a
        survivor the record shows dying is a refusal.  True for the
        PRE-FLIGHT, which is the decision this function exists to make.
        False for the one internal caller that wants the world SCAN and
        not the decision -- :meth:`Session._save_fingerprint`, which runs
        on every step of a live session and therefore passes through this
        exact state legitimately: the last-words keystroke is recorded
        while the live save is still on disk, because the engine only
        moves it in ``cleanup_at_end()`` after the death screen.  Raising
        there would make a death ending impossible to record, which is a
        permitted ending, so the distinction is a parameter rather than a
        rule.  It defaults to refusing so that a new caller inherits the
        strict reading and has to ask for the loose one.
    :raises SessionError: on an unreadable tree, on an ambiguity that
        must be resolved by a human rather than by this module, or on a
        recorded death whose live save is still present.
    """
    if save_dir is None:
        save_dir = save_dir_path(root)
    directory = _confined(save_dir, "the save directory", root)
    if requested_world is None:
        requested_world = os.environ.get(ENV_RESUME_WORLD, "").strip()

    notes: List[str] = []
    worlds: List[WorldSave] = []

    # WHAT THE RECORD SAYS ABOUT A DEATH, read once, before any world is
    # classified.  Two independent facts, neither of them read out of a
    # save file: which frame the append-only record shows a survivor
    # beginning their last words at, and whether the engine's own death
    # cleanup left its products behind.
    #
    # THE ATTRIBUTION comes from lastworld.json, which is the engine's own
    # statement of which world and survivor were loaded
    # (src/main_menu.cpp:1080-1083) -- so a recorded death is charged to
    # that world and to no other.  Without it the death is observed but
    # unattributable, which is reported as a note rather than used to
    # disqualify a world that may have nothing to do with it.
    #
    # THE READ IS ALLOWED TO REFUSE, and the refusal is deliberately not
    # caught here.  observed_death_frame answers None only for a record
    # that is genuinely absent -- a first run -- and raises for one that
    # exists and cannot be trusted.  Letting that propagate is what makes
    # this probe fail closed: the alternative, treating an unparsable
    # record as "no death recorded", is how a live-shaped save from
    # BEFORE a death would be offered for resuming.
    death_frame = observed_death_frame(root=root)
    cleanup_done = _death_cleanup_present(root)
    death_world: Optional[str] = None
    death_character: Optional[str] = None
    if death_frame is not None:
        pinned = read_lastworld(root=root)
        if pinned is not None:
            death_world, death_character = pinned
        else:
            notes.append(
                "the append-only record shows a survivor beginning "
                "their last words at frame %d, but %s does not name "
                "which world and survivor were loaded, so the death "
                "cannot be attributed to a world.  Resumability is "
                "therefore decided on the save files alone for this "
                "tree -- confirm by hand which survivor died before "
                "continuing any of them"
                % (death_frame, LASTWORLD_NAME))

    if _real_directory(directory):
        for name in sorted(os.listdir(directory)):
            world_dir = _real_subdirectory(directory, name)
            if world_dir is None:
                continue
            if not _real_regular_file(
                    os.path.join(world_dir, SAVE_MASTER_NAME),
                    "the world save"):
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
                has_world_options=_real_regular_file(
                    os.path.join(world_dir, WORLD_OPTIONS_NAME),
                    "the world options"),
                death_recorded_at=(
                    death_frame if name == death_world else None),
                cleanup_complete=cleanup_done,
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

    # A RECORDED DEATH IS REFUSED, NEVER SILENTLY TURNED INTO A CREATE.
    #
    # This is the second half of the fix beside WorldSave.resumable, and
    # without it the first half would be worse than the bug.  Making a
    # dead survivor's world non-resumable removes it from `resumable`, and
    # the branch below then reports CREATE -- so the probe would answer
    # "make a new character" on a tree that still holds the dead one's
    # save, world and config.  A run that acted on it would start a second
    # survivor beside the first, in the same world directory, and the hard
    # rule is that an existing save is CONTINUED rather than replaced.
    #
    # So the state gets its own refusal, naming the frame, the survivor
    # and the three ways out.  The operator decides; this module will not
    # decide for them, because each way out discards or publishes evidence
    # and that is not a choice an unattended probe should make.
    dead = [one for one in worlds if one.death_recorded_at is not None]
    if dead:
        blocked = [one for one in dead if one.characters]
        if blocked and refuse_recorded_death:
            world = blocked[0]
            raise SessionError(
                "save/%s holds a live character save (%s) for '%s', but "
                "the append-only record shows that survivor beginning "
                "their last words at frame %d, and the engine's death "
                "cleanup %s.  This tree is NOT resumable: CDDA writes "
                "the character file during play and only moves it to the "
                "graveyard in cleanup_at_end(), which runs after the "
                "death screen -- so a session that ended inside that "
                "screen leaves a fully live-shaped save for a survivor "
                "who is dead in the record.  Loading it would put a dead "
                "survivor back into play, and nothing in the save itself "
                "would show that.  Three ways forward, and this refuses "
                "rather than choosing between them because each one "
                "either discards or publishes evidence: (1) if the "
                "recorded session is being superseded, retire this "
                "userdir together with its frames and manifest so "
                "exactly one session remains in the record, then run a "
                "fresh session; (2) if the death is to stand as the "
                "ending, complete the engine's own cleanup by replaying "
                "the death screen to the end so the graveyard and "
                "memorial are written, and let the save be moved rather "
                "than deleting it by hand; (3) if this world genuinely "
                "holds a DIFFERENT, living survivor, set $%s to that "
                "world -- the death is attributed from %s, which names "
                "'%s'"
                % (world.name,
                   ", ".join(world.characters),
                   death_character or "an unnamed survivor",
                   world.death_recorded_at,
                   ("left no graveyard or memorial behind, so it never "
                    "ran" if world.death_pending
                    else "did run, which makes a surviving live save "
                         "inconsistent with it"),
                   ENV_RESUME_WORLD, LASTWORLD_NAME,
                   death_world or "no world"))
        for one in dead:
            notes.append(
                "save/%s recorded a death at frame %d and holds no live "
                "character save, so the engine's cleanup moved it as it "
                "should; the world is not resumable and is excluded from "
                "the decision" % (one.name, one.death_recorded_at))

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

def is_debug_action(identifier: object) -> bool:
    """True when `identifier` names a debug action of any kind.

    A PATTERN, not a list, and deliberately so.  The three authoritative
    actions are named in DEBUG_ACTION_IDS and the five dialogue toggles
    in DEBUG_DIALOGUE_ACTION_IDS, but the audit must not be limited to
    the ids that happened to exist when it was written: the engine's
    keybinding table grows, and an action added later whose id says
    "debug" is exactly the thing this check is for.  Matching on the
    substring makes the audit COMPLETE over the file it reads rather
    than complete over a list somebody has to remember to extend.
    """
    if not isinstance(identifier, str):
        return False
    return DEBUG_ID_MARKER in identifier.lower()


def _bound_debug_actions(entries: object, path: str) -> List[str]:
    """Return every debug action that carries a binding.

    The engine writes the user keybindings file as a JSON array of
    objects with "id", "version", "category" and -- only when it is
    non-empty -- "bindings" (src/input.cpp:381-402).  An object for a
    debug action with no "bindings" member is therefore the ordinary,
    correct state and is not a finding; one WITH a non-empty bindings
    array means somebody deliberately made a debug action reachable.

    EVERY debug action is audited, not only the three that ship unbound.
    The five DEBUG_DIALOGUE_* toggles ship BOUND to ctrl chords, so an
    entry for one of them in the USER file is a deliberate override of
    something already reachable -- and this module refuses to send any
    ctrl chord for precisely that reason, so a binding here would be a
    contradiction worth stopping for.
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
        if not is_debug_action(identifier):
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

    EVERY debug action is audited, matched by id (see
    :func:`is_debug_action`), not just those three -- the five
    DEBUG_DIALOGUE_* toggles ship already bound, and an action the
    engine adds later is covered without this list being updated.

    THIS RUNS BEFORE EVERY KEYSTROKE, not only when somebody asks for
    the `audit` subcommand.  An optional integrity check is one that a
    driver can simply not call, which makes it evidence of nothing;
    :meth:`Session.step` calls it on every step and caches the result
    against the file's identity and mtime, so the cost is one lstat per
    key and a changed file is re-read rather than trusted.

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
            "%s binds %s.  No debug action may carry a user binding: no "
            "debug menu, no debug mode, no hour timer, no dialogue "
            "toggles, for any reason and explicitly including avoiding "
            "death.  Remove the binding before playing; death by "
            "legitimate play is an acceptable, honest ending"
            % (target, ", ".join(bound)))
    return ("%s carries no binding for any action whose id names it a "
            "debug action, including %s"
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


# ---------------------------------------------------------------------
# THE OBSERVED-EFFECT GUARD.
#
# A row used to be written entirely from the keystroke that was
# INTENDED, and an intent is not an observation.  A "(Case Sensitive)"
# question or an open modal box eats the key, the picture does not move,
# and a row written from the intent still says the world name was typed
# or that the survivor stepped north.  Runtime testing of the first
# recorded session found 29 such rows, and the sweep that followed found
# 16 more -- every one of them the same mistake, and every one of them a
# fabrication inside an artifact whose whole purpose is to be truthful.
# playthrough/TECHNICAL_NOTES.md carries the register.
#
# So the row now carries an OBSERVATION beside the intent.  After the
# capture, and before the row is appended, the new frame is compared
# with the one before it and the verdict is written into the row's own
# action text:
#
#   changed      the map column itself changed
#   outside-map  something changed, but nothing in the map column did:
#                only a panel, a counter or the message log moved, so
#                the survivor did not walk and the world did not turn.
#                The "map column" is a REGION -- everything beside the
#                sidebar -- and is named for what it holds in play; on a
#                menu screen it is simply the rest of the window
#   unchanged    the two captures are identical pixel for pixel, so
#                whatever the key was for, the screen did not move
#   first        there is no earlier capture to compare against
#   unknown      the comparison could not be made, which is REPORTED
#                rather than quietly recorded as "changed"
#
# The marker is APPENDED, never substituted: the note stays exactly as
# written, so the row says what was intended AND what was observed and a
# reader can see where the two part company.  Nothing is refused -- by
# the time a frame exists the keystroke has already been delivered, and
# refusing the row would break the one-frame-per-keystroke identity the
# whole record rests on.  A warning goes to stderr as well, because an
# operator who reads it writes the NEXT row from the pixels.
#
# The comparison is ImageMagick's own pixel signature rather than a
# digest of the file, so it answers a question about pixels and not
# about PNG encoding, and it needs no image library beyond the tool
# capture.sh already requires.
# ---------------------------------------------------------------------

# ImageMagick's legacy entry point, resolved the same way as every other
# tool: env.sh's $PLAYTHROUGH_BIN_CONVERT first.  capture.sh measures
# luminance through the same binary, so requiring it here adds no
# dependency the capture did not already have.
CONVERT = "convert"

# The measurement, in one invocation and in ImageMagick's own terms:
# difference-compose the two captures, threshold every non-zero pixel to
# white, and print how many there are and the box they fall in.  It
# counts PIXELS rather than comparing files, so it answers a question
# about what is on the screen and not about PNG encoding, and it needs
# no image library beyond the tool capture.sh already requires.
DIFFERENCE_COUNT_FORMAT = "%[fx:int(mean*w*h+0.5)]"
DIFFERENCE_BOX_FORMAT = "%wx%h%O"

# HOW MANY SIGNIFICANT DIGITS ImageMagick PRINTS AN FX RESULT WITH, and
# why it has to be said.  The default is six, and an FX result is
# formatted with %g -- so a count of 1,027,832 changed pixels came back
# as `1.02783e+06`, which is not a count, and every pair differing by a
# million pixels or more was therefore reported as UNMEASURABLE.  A
# whole-screen change is exactly the case that happens at a scene
# transition, so the verdict was silently unavailable for the most
# visually significant steps in a session: found while running the
# retroactive pass over the committed record, where ten of the 418 pairs
# came back unknown for this reason and no other.  A 1920x1080 frame has
# 2,073,600 pixels, seven digits; sixteen is comfortably inside a double
# and leaves the integer exact.
DIFFERENCE_PRECISION = "16"
COUNT_RE = re.compile(r"\A\d+\Z")
BOX_RE = re.compile(r"\A\d+x\d+[-+]\d+[-+]\d+\Z")

# An advisory floor, used ONLY to decide whether to warn a second time
# and never to write anything into a row.  Measured from this session's
# own captures: a step that actually moved the survivor changed 38,895,
# 49,590 and 55,801 px of the map column, while a change confined to a
# panel drawn over the map changed 6,480, 14,709 and 14,732 px.  A claim
# of movement under this floor is worth a second look, and the number is
# deliberately between the two populations rather than tight to either.
MOVEMENT_ADVISORY_PIXELS = 20000

EFFECT_FIRST = "first"
EFFECT_UNCHANGED = "unchanged"
EFFECT_OUTSIDE_MAP = "outside-map"
EFFECT_CHANGED = "changed"
EFFECT_UNKNOWN = "unknown"

EFFECTS = (EFFECT_FIRST, EFFECT_UNCHANGED, EFFECT_OUTSIDE_MAP,
           EFFECT_CHANGED, EFFECT_UNKNOWN)

# The two sentences the guard is allowed to add to a row, and the only
# two.  They state what was SEEN, never what it means: a trailing
# `space` in a field with no cursor block changes nothing on screen and
# still registers, so "nothing on the screen changed" is the honest
# reading of that capture and "the key was ignored" would not be.
MARKER_UNCHANGED = "nothing on the screen changed"
MARKER_OUTSIDE_MAP = "nothing in the map column changed"

EFFECT_MARKERS = {
    EFFECT_UNCHANGED: MARKER_UNCHANGED,
    EFFECT_OUTSIDE_MAP: MARKER_OUTSIDE_MAP,
}

# ---------------------------------------------------------------------
# THE ENFORCING HALF OF THE GUARD: A DECLARATION, AN ACKNOWLEDGMENT AND
# TWO HALTS.
#
# Everything above this point MEASURES and REPORTS.  A review found that
# insufficient, with evidence: the retired session's frames 91-106 show
# two whole key sequences -- a filter that had already been cleared, and
# a page change -- delivered into an UNCHANGED abandon-creation modal,
# and the guard's warnings were on stderr the entire time.  A control
# that only speaks is a report; the hard rule "never blind-spam keys"
# needs one that refuses.  Three mechanisms now do:
#
#   1. EVERY STEP DECLARES WHAT ITS CAPTURE WILL SHOW.  `--expect
#      changed` is the default because a keystroke that moves nothing on
#      screen is the shape of a swallowed key; `--expect unchanged` is
#      how an operator says in advance that this one legitimately will
#      not (a trailing space in a field with no cursor block, say).  A
#      capture that contradicts the declaration HALTS the session.
#
#   2. EVERY STEP ACKNOWLEDGES THE CAPTURE BEFORE IT.  `--observed TEXT`
#      is the operator's own reading of frame N-1, appended to an
#      append-only ledger, bound to that frame's sha256, and made
#      durable BEFORE the next key is delivered.  A step whose
#      predecessor is unacknowledged refuses to send anything at all, so
#      "read the picture between the keys" is a precondition rather than
#      an instruction.
#
#   3. AN UNDECLARED MODAL HALTS.  The engine's query_yn boxes are drawn
#      in the middle of the screen, and every one of them eats keys
#      aimed at the screen behind it.  The central band of each capture
#      is read and matched against the prompts below; a prompt that is
#      present without having been declared with `--expect-modal` stops
#      the session, and a declared prompt that is NOT present stops it
#      too, because the operator's model of the screen is then wrong in
#      the other direction.
#
# All three are recorded in the telemetry sidecar, so the record shows
# what was declared as well as what was observed.
# ---------------------------------------------------------------------

EXPECT_CHANGED = "changed"
EXPECT_UNCHANGED = "unchanged"
EXPECT_EITHER = "either"
EXPECTATIONS = (EXPECT_CHANGED, EXPECT_UNCHANGED, EXPECT_EITHER)

# What each declaration accepts.  EFFECT_FIRST is accepted by all three:
# the first capture of a session has nothing to be compared against, so
# it can contradict nothing.
#
# EFFECT_UNKNOWN IS REFUSED BY THE TWO PREDICTIONS AND ACCEPTED BY THE
# ADMISSION, and the asymmetry is the whole design.  A step that
# PREDICTED an outcome and then could not have that prediction checked
# has not been checked -- treating the absence of an observation as a
# satisfied one is precisely the failure this block exists to end.  A
# step that declared EXPECT_EITHER predicted nothing, so there is
# nothing to contradict; it is still bound by the acknowledgment
# requirement below, which is what makes the operator read that capture
# before the next key regardless.
EXPECT_ACCEPTS = {
    EXPECT_CHANGED: (EFFECT_CHANGED, EFFECT_OUTSIDE_MAP, EFFECT_FIRST),
    EXPECT_UNCHANGED: (EFFECT_UNCHANGED, EFFECT_FIRST),
    EXPECT_EITHER: (EFFECT_CHANGED, EFFECT_OUTSIDE_MAP,
                    EFFECT_UNCHANGED, EFFECT_FIRST, EFFECT_UNKNOWN),
}

# The engine's own query_yn prompts, quoted from the source rather than
# from memory, each with the token an operator declares it by.  These are
# the boxes that eat a key aimed at the screen behind them.
#
# The match is on a SUBSTRING of the central band's OCR, so the trailing
# "(Case Sensitive)" the engine appends when a prompt wants a capital
# (src/output.cpp:873,894) does not have to be modelled separately.
MODAL_PROMPTS = (
    ("return-to-main-menu", "Return to main menu?",
     "src/newcharacter.cpp:3864,3868 -- leaving character creation"),
    ("really-quit", "Really quit?",
     "src/main_menu.cpp:769 -- leaving the application"),
    ("save-and-quit", "Save and quit?",
     "src/handle_action.cpp:3031 -- the mandated in-game ending"),
    ("abandon-character", "Abandon this character?",
     "src/handle_action.cpp:3021 -- suicide, which this run never takes"),
    ("kill-your-character", "This will kill your character",
     "src/handle_action.cpp:3022 -- suicide's second confirmation"),
)

MODAL_TOKENS = tuple(token for token, _text, _why in MODAL_PROMPTS)

# WHERE A QUERY BOX LANDS.  query_yn is centred, so the band is taken
# around the middle of the capture rather than over the whole frame: one
# tesseract call on a quarter of the pixels, measured at 0.6 s against
# 0.9 s for a whole-frame glyph decode, and with far less of the map's
# artwork in it to confuse the reader.  The fractions are of the
# capture's own height, so a different terminal geometry needs no change
# here.
MODAL_BAND_TOP = 0.28
MODAL_BAND_BOTTOM = 0.72

# The shortest reading that says anything.  A one-word acknowledgment is
# a box being ticked; the ledger exists to hold what the operator SAW.
ACK_MIN_LENGTH = 12

# The ledger's own name, beside the observation sidecar it belongs with.
ACKNOWLEDGMENTS_NAME = "acknowledgments.jsonl"
ACK_VERSION = 1

# The marker joins the note with a semicolon, because ACTION_SEPARATOR
# may appear exactly once in an action and it separates the derived
# keystroke from the note.
MARKER_SEPARATOR = "; "

# Why a measured marker cannot simply be left off a recorded row, stated
# once so that every amendment this module appends gives the same
# reason.  It goes in the amendment ledger, which is an engineering
# record rather than the in-character one, so it speaks plainly.
EFFECT_AMENDMENT_REASON = (
    "the recorded note describes an effect its own capture "
    "contradicts, and a derivative that repeats it would narrate "
    "something the evidence does not show.  The recorded words stand "
    "exactly as written; the observation is appended to them in a "
    "derivative, never substituted for them in the record."
)

# Wording that asserts the survivor's own body went somewhere.  Used
# only to decide whether a warning is worth raising a second time, more
# loudly: a claim of movement over a map that did not change is the
# defect class this guard exists for.
MOVEMENT_CLAIM_RE = re.compile(
    r"\b(step|steps|stepped|stepping|walk|walks|walked|walking|"
    r"move|moves|moved|moving|go|goes|went|going|onto|"
    r"north|south|east|west)\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class ObservedEffect:
    """What comparing two captures actually measured.

    `verdict` is one of :data:`EFFECTS` and is the only part that
    reaches the row's prose.  The counts and the box are measurements,
    recorded in the telemetry sidecar so that the verdict can be
    audited per frame afterwards without re-measuring, and they are
    None whenever the measurement was not made.
    """

    verdict: str
    screen_pixels: Optional[int] = None
    map_pixels: Optional[int] = None
    map_box: Optional[str] = None


def _difference_command(previous: str, current: str,
                        regions: Sequence[Optional[str]]) -> List[str]:
    """Build the ImageMagick graph that measures one pair of captures.

    ONE DECODE, however many regions are wanted.  The two captures are
    read once, difference-composed once and thresholded once; each
    measurement after that is a `-format`/`-write` on the image already
    in hand.  Written as a builder because measuring one region and
    measuring the whole screen plus a region are the SAME graph with a
    stage more or less, and two hand-written command lists would drift
    apart -- which is exactly how the two of them could stop agreeing
    about what they measured.

    `regions` is the crops to measure, in order; None means "the image as
    it stands".  Each crop is applied to the image the previous stage
    left, which for the (None, map-column) pair this module uses means
    the crop is relative to the whole frame.  `+repage` follows every
    crop so `%O` is relative to the cropped region rather than to a
    canvas carrying an offset.

    The output is one count per region and then ONE bounding box, the
    last region's.  `-trim` crops the image to the box it reports, so a
    box can only ever be taken after the last count -- which is why it is
    the last region's and not every region's.

    Thresholding is pointwise, so doing it before the crops gives exactly
    the pixels cropping first would have given.
    """
    if not regions:
        raise CaptureError(
            "a difference measurement needs at least one region")
    command = [_verified(CONVERT), previous, current,
               "-compose", "difference", "-composite", "-threshold", "0",
               # -precision BEFORE the format: the count is an integer
               # of up to seven digits and the default six significant
               # digits turn it into scientific notation, which is not a
               # count.  See DIFFERENCE_PRECISION.
               "-precision", DIFFERENCE_PRECISION]
    for crop in regions:
        if crop is not None:
            command += ["-crop", crop, "+repage"]
        command += ["-format", DIFFERENCE_COUNT_FORMAT + "\n",
                    "-write", "info:-"]
    command += ["-trim", "-format", DIFFERENCE_BOX_FORMAT + "\n",
                "info:"]
    return command


def _difference_values(previous: str, current: str,
                       regions: Sequence[Optional[str]],
                       timeout: Optional[int]) -> List[str]:
    """Run the graph and return one count per region, then the box.

    Every count is checked, not merely the first: a graph that printed
    fewer numbers than it was asked for has not measured what the caller
    is about to record.

    :raises CaptureError: when the tool fails or prints something that is
        not a count.  The measurement is evidence, so a value that cannot
        be trusted is refused rather than returned.
    """
    if timeout is None:
        timeout = _timeout(ENV_TOOL_TIMEOUT, DEFAULT_TOOL_TIMEOUT)
    completed = _run(
        _difference_command(previous, current, regions), timeout,
        "measuring %s against %s" % (os.path.basename(previous),
                                     os.path.basename(current)))
    lines = completed.stdout.decode("utf-8", "replace").split()
    named = [one for one in regions if one is not None]
    counted = (completed.returncode == 0 and
               len(lines) >= len(regions) and
               all(COUNT_RE.match(one) for one in lines[:len(regions)]))
    if not counted:
        raise CaptureError(
            "convert could not measure %s against %s%s: exit %d, %s"
            % (previous, current,
               "" if not named else " over region(s) %s" % ", ".join(
                   named),
               completed.returncode, _diagnostic(completed)))
    return lines


def _box_or_none(pixels: int, token: str) -> Optional[str]:
    """Return a bounding box, or None when there is honestly no box.

    ImageMagick has no box for an image with nothing in it and says so
    on stderr -- expected here rather than a fault -- and it prints a
    degenerate `1x1-1-1` in that case, so a box is only reported
    alongside a non-zero count.
    """
    return token if pixels and BOX_RE.match(token) else None


def measure_difference(previous: str, current: str,
                       geometry: Optional[str] = None,
                       timeout: Optional[int] = None,
                       ) -> Tuple[int, Optional[str]]:
    """Return how many pixels differ between two captures, and where.

    `geometry` is an ImageMagick crop -- "1568x1080+0+0" -- and when it
    is given only that region is compared, which is how the map column
    is measured independently of the sidebar beside it.  `+repage`
    follows the crop so the measurement describes the cropped pixels
    rather than a canvas carrying an offset.

    The box is the difference's own bounding box in the compared
    region's coordinates, or None when nothing differs.

    ONE REGION PER CALL.  :func:`measure_difference_pair` measures the
    whole screen and a region TOGETHER, in one decode, which is what
    :func:`classify_effect` uses; this remains the way to ask about a
    single region, and both go through :func:`_difference_command` so
    neither can drift from the other.

    :raises CaptureError: when the tool fails or prints something that
        is not a count.
    """
    lines = _difference_values(previous, current, (geometry,), timeout)
    pixels = int(lines[0], 10)
    return pixels, _box_or_none(
        pixels, lines[1] if len(lines) > 1 else "")


def measure_difference_pair(previous: str, current: str, geometry: str,
                            timeout: Optional[int] = None,
                            ) -> Tuple[int, int, Optional[str]]:
    """Measure the whole screen AND `geometry`'s region in ONE decode.

    Returns (whole-screen pixels, region pixels, region box).

    WHY THIS EXISTS.  Classifying one keystroke's effect needs two
    numbers -- did anything change, and did anything change in the map
    column -- and taking them with two `convert` invocations decoded the
    same two 1920x1080 PNGs twice, which a performance QA pass measured
    at about 828 processes over the 419 frames already recorded.  Both
    numbers come off one decode here, and BOTH are still measured: the
    region count and its box are exactly the values the two-call path
    produced, which the suite asserts against real captures rather than
    assuming.

    The whole screen's own bounding box is deliberately not returned.
    `-trim` crops the image to the box it reports, so taking it before
    the region crop would measure the wrong pixels -- and no caller has
    ever used it: :func:`classify_effect` discarded it.

    :raises CaptureError: exactly where :func:`measure_difference` does.
    """
    lines = _difference_values(
        previous, current, (None, geometry), timeout)
    screen = int(lines[0], 10)
    region = int(lines[1], 10)
    return screen, region, _box_or_none(
        region, lines[2] if len(lines) > 2 else "")


def map_column_geometry(rect: object, width: int, height: int,
                        ) -> Optional[str]:
    """Return the crop covering the map column beside the sidebar.

    The sidebar is a column at one edge of the window -- right by
    default (src/options.cpp:2132-2136) -- so the map column is
    everything on the other side of it.  `rect` is the sidebar crop
    sidebar_geometry.py computes at runtime, passed through
    ocr_clock.resolve_rect(), and the full frame is `width` x `height`.

    Returns None when the two cannot be reconciled -- a sidebar wider
    than the frame, or one that covers it entirely -- because a crop
    guessed from inconsistent numbers would compare the wrong pixels
    and report the wrong verdict.
    """
    try:
        left = int(getattr(rect, "x"))
        span = int(getattr(rect, "width"))
    except (AttributeError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or span <= 0 or left < 0:
        return None
    if left >= width or left + span > width:
        return None
    if left * 2 >= width:
        # A right-hand sidebar: the map is everything to its left.
        return "%dx%d+0+0" % (left, height) if left else None
    # A left-hand sidebar: the map is everything to its right.
    beyond = width - (left + span)
    return ("%dx%d+%d+0" % (beyond, height, left + span)
            if beyond else None)


def classify_effect(previous: Optional[str], current: str,
                    map_geometry: Optional[str] = None,
                    timeout: Optional[int] = None) -> ObservedEffect:
    """Say what one keystroke visibly did, by comparing two captures.

    `previous` is the capture the operator was looking at when the key
    was chosen and `current` the one the key produced; a `previous` of
    None -- the first frame of the record -- is EFFECT_FIRST, because
    there is nothing to compare it against and a verdict would be
    invented.  `map_geometry` is :func:`map_column_geometry`'s crop;
    without it the map column cannot be isolated, so a frame that moved
    is EFFECT_CHANGED rather than a finer verdict nothing measured.

    Never raises: a measurement that cannot be made is EFFECT_UNKNOWN
    and says so on stderr.  This runs AFTER the keystroke, where an
    exception would abandon a frame that is already on disk.

    ONE `convert` PER PAIR.  Both numbers come off a single decode of the
    two captures (:func:`measure_difference_pair`); taking them
    separately decoded the same two 1920x1080 PNGs twice, for about 828
    processes over the 419 frames already recorded.  The DEGRADATION is
    unchanged, and that is what the fallback below is for: when the
    combined measurement fails, the whole screen alone is measured on its
    own -- one extra process, and only on the failure path -- so a crop
    that cannot be reconciled with these captures still yields the
    screen's verdict instead of losing it along with the region's.
    """
    if previous is None:
        return ObservedEffect(EFFECT_FIRST)
    if map_geometry is not None:
        try:
            screen_pixels, map_pixels, map_box = (
                measure_difference_pair(
                    previous, current, map_geometry, timeout=timeout))
        except SessionError as err:
            return _effect_without_map(
                previous, current, map_geometry, err, timeout)
        if screen_pixels == 0:
            # Nothing differs anywhere, so nothing differs in the map
            # column either -- measured, not assumed.
            return ObservedEffect(
                EFFECT_UNCHANGED, screen_pixels=0,
                map_pixels=map_pixels)
        verdict = (EFFECT_OUTSIDE_MAP if map_pixels == 0
                   else EFFECT_CHANGED)
        return ObservedEffect(
            verdict, screen_pixels=screen_pixels,
            map_pixels=map_pixels, map_box=map_box)
    try:
        screen_pixels, _screen_box = measure_difference(
            previous, current, timeout=timeout)
    except SessionError as err:
        _warn("the captures %s and %s could not be compared (%s), so "
              "this row records no observation of what the keystroke "
              "did; read the two captures yourself before writing the "
              "next row"
              % (os.path.basename(previous), os.path.basename(current),
                 err))
        return ObservedEffect(EFFECT_UNKNOWN)
    if screen_pixels == 0:
        return ObservedEffect(
            EFFECT_UNCHANGED, screen_pixels=0, map_pixels=0)
    return ObservedEffect(EFFECT_CHANGED, screen_pixels=screen_pixels)


def _effect_without_map(previous: str, current: str, map_geometry: str,
                        cause: SessionError,
                        timeout: Optional[int]) -> ObservedEffect:
    """Fall back to the whole screen when the region cannot be measured.

    Which of the two the combined graph choked on is not guessed from its
    stderr -- it is established by asking the simpler question: if the
    whole screen alone measures, the CROP was the problem and the row
    records that the screen changed; if it does not, the CAPTURES are the
    problem and the row records no observation at all.  Both warnings are
    the ones the two-call path emitted for the same two situations.
    """
    try:
        screen_pixels, _screen_box = measure_difference(
            previous, current, timeout=timeout)
    except SessionError:
        _warn("the captures %s and %s could not be compared (%s), so "
              "this row records no observation of what the keystroke "
              "did; read the two captures yourself before writing the "
              "next row"
              % (os.path.basename(previous), os.path.basename(current),
                 cause))
        return ObservedEffect(EFFECT_UNKNOWN)
    if screen_pixels == 0:
        return ObservedEffect(
            EFFECT_UNCHANGED, screen_pixels=0, map_pixels=0)
    _warn("the map column %s of %s and %s could not be measured (%s), "
          "so this row records only that the screen changed"
          % (map_geometry, os.path.basename(previous),
             os.path.basename(current), cause))
    return ObservedEffect(EFFECT_CHANGED, screen_pixels=screen_pixels)


def verdict_of(effect: object) -> str:
    """Return the verdict from an :class:`ObservedEffect` or a string.

    The guard's callers hold whichever is convenient, and every one of
    them wants the same answer, so the coercion lives here instead of
    at each site.  An unrecognised value yields EFFECT_UNKNOWN, which
    annotates nothing -- the safe direction, because a marker is a claim
    about the pixels.
    """
    verdict = getattr(effect, "verdict", effect)
    return verdict if verdict in EFFECTS else EFFECT_UNKNOWN


def annotate_action(action: str, effect: object) -> str:
    """Return `action` with this frame's observed-effect marker.

    Appended to the note, or made the note when there is none, and
    added at most once: a row recovered from the journal already
    carries the marker its first attempt earned, and a second copy
    would say the same thing twice.  EFFECT_CHANGED, EFFECT_FIRST and
    EFFECT_UNKNOWN add nothing -- the first because the ordinary case
    needs no annotation, the other two because neither is an
    observation of what the keystroke did.
    """
    marker = EFFECT_MARKERS.get(verdict_of(effect))
    if marker is None:
        return action
    text = action.strip()
    if marker in text:
        return text
    if ACTION_SEPARATOR in text:
        return text + MARKER_SEPARATOR + marker
    return text + ACTION_SEPARATOR + marker


def movement_claim(text: object) -> bool:
    """True when `text` asserts the survivor's own body went somewhere.

    Deliberately blunt, and only ever used to decide how loudly to
    warn: this never edits a row, and a false positive costs a warning
    an operator can read past.
    """
    if not isinstance(text, str):
        return False
    return bool(MOVEMENT_CLAIM_RE.search(text))


def observation_row(frame: int,
                    payload: Mapping[str, str],
                    key: Optional[str] = None,
                    action: Optional[str] = None,
                    capture_attempts: int = 1,
                    recovered: bool = False,
                    effect: object = None) -> Dict[str, object]:
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

    `effect` is :func:`classify_effect`'s result for this capture -- an
    :class:`ObservedEffect` or a bare verdict -- and it is recorded here
    as well as in the row's action text, so the observation can be
    audited per frame without re-reading the prose.  Its measurements
    are recorded beside it when it carries them, because a verdict whose
    numbers are on record can be re-checked and one whose numbers are
    not has to be taken on trust.  An unrecognised verdict is refused
    rather than stored: a verdict is evidence and a spelling nothing
    understands is not one.
    """
    row: Dict[str, object] = {}
    for name, payload_key in OBSERVATION_FIELDS:
        value = payload.get(payload_key, "")
        row[name] = value.strip() if isinstance(value, str) else value
    # The one field that is not a verbatim copy: the sidecar is keyed by
    # an integer frame index, which is what timeline.py matches its rows
    # against (a row it cannot key is a row it cannot use).
    row["frame"] = validated_frame(frame)
    # THE ATTESTATION.  Written from this module's own values, never
    # from the payload: capture.sh is never told which key was pressed,
    # so nothing it prints could contradict or supply this.
    if key is not None:
        row["key"] = validate_key(key)
        row["action"] = assert_action_derived(
            key, action if action is not None else describe_key(key))
        row["capture_attempts"] = int(capture_attempts)
        row["recovered"] = bool(recovered)
    if effect is not None:
        verdict = getattr(effect, "verdict", effect)
        if verdict not in EFFECTS:
            raise RecordError(
                "%r is not one of the observed-effect verdicts (%s); a "
                "verdict is evidence and a spelling nothing understands "
                "is not one" % (verdict, ", ".join(EFFECTS)))
        row["effect"] = verdict
        for name, attribute in (("screen_diff_px", "screen_pixels"),
                                ("map_diff_px", "map_pixels"),
                                ("map_diff_box", "map_box")):
            measured = getattr(effect, attribute, None)
            if measured is not None:
                row[name] = measured
    return row


def append_observation(path: str, row: Mapping[str, object],
                       require_durable: bool = True,
                       root: Optional[str] = None) -> Dict[str, object]:
    """Append one telemetry row under the record's discipline.

    Returns the row.  The same discipline manifest.py applies to the
    record itself, for the same reasons: the destination is confined to
    the playthrough/ tree, the descriptor is opened O_NOFOLLOW so a
    planted symlink is refused by the kernel rather than followed,
    cooperating writers are serialised by an exclusive advisory lock,
    the row is written with a single unbuffered os.write, a HANDLED
    short write or write failure is truncated straight back to the
    offset the file had, and the row is not reported as recorded until
    it has been forced to the device.

    That is narrower than all-or-nothing, and deliberately stated as
    such: an UNHANDLED interruption -- SIGKILL, or the power going --
    can still leave a torn line, which is why the readers refuse one
    rather than assuming it cannot happen.

    A half-written line is not JSON, and timeline.py refuses a sidecar
    it cannot parse outright rather than falling back to the clock
    alone -- so a fragment here would stop the render, not degrade it.

    :raises RecordError: on any failure along that path.
    """
    return _append_jsonl_row(
        _confined(path, "the telemetry sidecar", root), row,
        "the telemetry sidecar", "telemetry row", require_durable)


def _append_jsonl_row(target: str, row: Mapping[str, object],
                      what: str, row_label: str,
                      require_durable: bool = True) -> Dict[str, object]:
    """Append one JSON line to `target` under the record's discipline.

    ONE IMPLEMENTATION, TWO LEDGERS.  The telemetry sidecar and the
    acknowledgment ledger are the same kind of artifact -- an
    append-only, one-line-per-frame JSONL file beside the record -- and
    the discipline that makes either of them trustworthy is identical.
    Writing it twice would let the two drift, and the weaker copy would
    be the one nobody noticed.

    `target` is already confined by the caller, because the label a
    containment refusal should name belongs to the caller's ledger and
    not to this shared body.

    :raises RecordError: on any failure along the path.
    """
    line = json.dumps(dict(row), ensure_ascii=False) + "\n"
    payload = line.encode("utf-8")
    directory = os.path.dirname(target)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as err:
        raise RecordError(
            "cannot create %s for %s: %s"
            % (directory, what, err)) from err
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
            0o600)
    except OSError as err:
        raise RecordError(
            "cannot open %s %s for appending: %s"
            % (what, target, err)) from err
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            committed = os.lseek(descriptor, 0, os.SEEK_END)
            written = os.write(descriptor, payload)
        except OSError as err:
            raise RecordError(
                "could not append frame %s's %s to %s: %s"
                % (row.get("frame"), row_label, target, err)) from err
        if written != len(payload):
            _truncate_back(descriptor, committed, target)
            raise RecordError(
                "only %d of %d bytes of frame %s's %s "
                "reached %s; the partial line was removed, because a "
                "fragment is not JSON and would stop the render"
                % (written, len(payload), row.get("frame"), row_label,
                   target))
        if require_durable:
            try:
                os.fsync(descriptor)
            except OSError as err:
                raise RecordError(
                    "could not force frame %s's %s to the "
                    "device (%s); it is not reported as recorded"
                    % (row.get("frame"), row_label, err)) from err
    finally:
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "sidecar-close",
                "could not close %s after appending (%s); the row was "
                "written and forced to the device before this point, "
                "so %s is intact" % (target, err, what))
    return dict(row)


def validate_observed(text: object) -> str:
    """Return the operator's reading of a capture, or refuse it.

    The acknowledgment ledger exists to hold what somebody SAW, so an
    empty or perfunctory value is refused rather than recorded: a ledger
    full of "ok" would satisfy the mechanism and defeat its purpose.

    :raises ObservationRequired: when there is nothing usable to record.
    """
    if text is None or not str(text).strip():
        raise ObservationRequired(
            "no reading of the previous capture was supplied.  Look at "
            "the frame and say what is on it -- which screen, which "
            "selection, which prompt -- because the next keystroke is "
            "chosen from that and the record has to show it was")
    reading = " ".join(str(text).split())
    if len(reading) < ACK_MIN_LENGTH:
        raise ObservationRequired(
            "the reading %r is %d character(s); at least %d are "
            "required.  This ledger holds what the operator SAW on the "
            "previous capture, and a value too short to describe a "
            "screen records the mechanism rather than the observation"
            % (reading, len(reading), ACK_MIN_LENGTH))
    return reading


def modal_band(width: int, height: int) -> "sidebar_geometry.Rect":
    """Return the region of a capture a query box is drawn in.

    query_yn centres its box, so the band is a horizontal slice through
    the middle of the frame at the fractions declared above.  Computed
    from the capture's own size rather than hard-coded, for the same
    reason the sidebar crop is: a different terminal geometry must not
    silently read the wrong pixels.
    """
    top = int(height * MODAL_BAND_TOP)
    bottom = int(height * MODAL_BAND_BOTTOM)
    return sidebar_geometry.Rect(width, max(1, bottom - top), 0, top)


def read_modal_text(path: str) -> str:
    """Return the OCR of `path`'s central band.  NEVER raises.

    An unreadable band answers "" -- which the caller treats as "no
    modal was detected", and which is why the declaration-versus-effect
    halt exists beside this one rather than depending on it: an OCR pass
    that fails is the absence of evidence, and this function is not
    permitted to end a session on it.  The failure is logged.
    """
    try:
        width, height = ocr_clock.png_size(path)
        rect = modal_band(width, height)
        chosen = None
        for candidate in ocr_clock.PASSES:
            if not candidate.row_wise:
                chosen = candidate
                break
        if chosen is None:                        # pragma: no cover
            return ""
        strip, _band = ocr_clock.preprocess(
            path, rect, ocr_clock.DEFAULT_ROW_HEIGHT, chosen,
            engine=ocr_clock.ENGINE_PILLOW)
        return ocr_clock.ocr_image(strip, chosen.psm)
    except (ocr_clock.OcrClockError, sidebar_geometry.GeometryError,
            OSError, ValueError) as err:
        LOG.info("the central band of %s could not be read for a "
                 "query box: %s", os.path.basename(path), err)
        return ""


def detect_modals(text: object) -> Tuple[str, ...]:
    """Return the tokens of every declared prompt present in `text`.

    Substring matching on the OCR of the central band.  The comparison
    is case-insensitive and whitespace-collapsed, because tesseract
    reads a proportional-looking cell grid and the engine's own strings
    carry double spaces the reader does not always preserve.
    """
    if not isinstance(text, str) or not text.strip():
        return ()
    flat = " ".join(text.split()).lower()
    found = []
    for token, prompt, _why in MODAL_PROMPTS:
        if " ".join(prompt.split()).lower() in flat:
            found.append(token)
    return tuple(found)


def modal_reason(token: object) -> str:
    """Return the source citation for one modal token, or ''."""
    for candidate, _prompt, why in MODAL_PROMPTS:
        if candidate == token:
            return why
    return ""


def validate_modal_token(token: object) -> str:
    """Return a declared modal token, or refuse an unknown one.

    :raises RecordError: when the token names no prompt this module
        knows, because a declaration nothing can match would silently
        never be satisfied.
    """
    if token in MODAL_TOKENS:
        return str(token)
    raise RecordError(
        "%r is not a query box this module knows.  The declared ones "
        "are: %s" % (token, ", ".join(MODAL_TOKENS)))


def acknowledgment_row(frame: int, observed: str, verdict: object,
                       modals: Sequence[str] = (),
                       digest: Optional[str] = None,
                       expectation: Optional[str] = None
                       ) -> Dict[str, object]:
    """Build one acknowledgment row.  Pure -- nothing is written.

    It binds the operator's reading to the FRAME'S OWN sha256, so an
    acknowledgment cannot later be read as being about a different
    capture: the digest is the same one the capture attestation ledger
    holds for that index.
    """
    return {
        "version": ACK_VERSION,
        "frame": validated_frame(frame),
        "file": manifest.frame_file(validated_frame(frame)),
        "frame_sha256": digest or "",
        "acknowledged_at": manifest.utc_timestamp(),
        "expected": expectation or "",
        "verdict": verdict_of(verdict),
        "modals": list(modals),
        "observed": validate_observed(observed),
    }


def append_acknowledgment(path: str, row: Mapping[str, object],
                          require_durable: bool = True,
                          root: Optional[str] = None
                          ) -> Dict[str, object]:
    """Append one acknowledgment under the record's own discipline.

    Append-only, confined, O_NOFOLLOW, locked and forced to the device,
    exactly as the telemetry sidecar is: this ledger is the evidence
    that the picture was read between the keys, and evidence that can be
    rewritten proves nothing.

    :raises RecordError: on any failure along that path.
    """
    return _append_jsonl_row(
        _confined(path, "the acknowledgment ledger", root), row,
        "the acknowledgment ledger", "acknowledgment", require_durable)


def read_acknowledgments(path: Optional[str] = None,
                         root: Optional[str] = None
                         ) -> Tuple[Dict[str, object], ...]:
    """Return every acknowledgment on disk, in file order.  Read-only.

    An absent ledger is an empty tuple -- a session that has taken no
    step has acknowledged nothing -- but a ledger that EXISTS and cannot
    be parsed raises, for the same reason the record does: the question
    "was the previous capture read" then has no trustworthy answer, and
    the caller must not proceed as though the answer were yes.

    :raises RecordError: when a ledger that exists cannot be read.
    """
    target = _confined(path or default_acknowledgments_path(root),
                       "the acknowledgment ledger", root)
    if not os.path.isfile(target):
        return ()
    rows: List[Dict[str, object]] = []
    try:
        with open(target, "r", encoding="utf-8") as handle:
            for number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                decoded = json.loads(raw)
                if not isinstance(decoded, dict):
                    raise RecordError(
                        "line %d of %s is a %s, not an acknowledgment"
                        % (number, target, type(decoded).__name__))
                rows.append(decoded)
    except (OSError, UnicodeError, ValueError) as err:
        raise RecordError(
            "the acknowledgment ledger %s exists but cannot be read "
            "(%s), so whether the previous capture was read is UNKNOWN "
            "rather than yes.  Repair it before sending another key"
            % (manifest.relative_to_repo(target), err)) from err
    return tuple(rows)


def acknowledged_frames(path: Optional[str] = None,
                        root: Optional[str] = None) -> Dict[int, str]:
    """Return {frame: digest} for every acknowledged capture.

    The digest travels with the index so a caller can prove the reading
    was about the bytes that are on disk now, rather than about a frame
    of the same number in an earlier, discarded attempt.
    """
    seen: Dict[int, str] = {}
    for row in read_acknowledgments(path, root):
        index = row.get("frame")
        if isinstance(index, bool) or not isinstance(index, int):
            raise RecordError(
                "an acknowledgment in %s records %r as its frame index"
                % (manifest.relative_to_repo(
                    path or default_acknowledgments_path(root)), index))
        digest = row.get("frame_sha256")
        seen[index] = digest if isinstance(digest, str) else ""
    return seen


def _reading_or_none(row: Mapping[str, object],
                     name: str) -> Optional[str]:
    """Return one sidecar column as text, or None when it is empty.

    An empty reading and an absent one are the same fact -- nothing was
    observed -- and both must arrive at the honesty gate as None rather
    than as an empty string that a comparison could mistake for a value.
    """
    value = row.get(name)
    text = str(value).strip() if value is not None else ""
    return text or None


def _observation_recorded(path: str, frame: int) -> bool:
    """True when the telemetry sidecar already holds `frame`'s row.

    Read-only, and deliberately tolerant of everything except an answer
    it cannot give.  A sidecar that does not exist holds no rows; a line
    that will not parse is skipped, because this asks ONE question --
    "is this index recorded?" -- and a malformed neighbour is neither a
    yes nor a no for the index being asked about.  verify_manifest() and
    timeline.py are where a malformed sidecar is reported; here it must
    not turn a missing row into a present one.

    :raises RecordError: when the file exists and cannot be read at all,
        because then the question genuinely has no answer and the caller
        is about to discard the journal that could rebuild it.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return False
    except OSError as err:
        raise RecordError(
            "cannot read the telemetry sidecar %s: %s.  A journal is "
            "not discarded while it is unknown whether the row it could "
            "rebuild is already there" % (path, err)) from err
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("frame") == frame:
            return True
    return False


def sweep_observation_staging(path: str) -> Tuple[str, ...]:
    """Remove staging siblings a retired sidecar rewrite left.

    The sidecar's half of manifest.sweep_staging(), which does the work
    -- one implementation of the rule, because both files sit inside the
    tree .gitignore re-includes with its terminal `!/playthrough/**`
    negation and a leftover in either is a file `git add -A playthrough/`
    would commit.  See that function for what is and is not removed.

    Called when a session opens, which is now the only moment that can
    heal the tree: the writer that produced these siblings has been
    removed, so no later rewrite is ever going to clear one.
    """
    return manifest.sweep_staging(
        os.path.dirname(path) or os.curdir,
        OBSERVATIONS_STAGING_PREFIX, OBSERVATIONS_STAGING_SUFFIX,
        OBSERVATIONS_STAGING_OF)


def read_observations(path: Optional[str] = None,
                      root: Optional[str] = None,
                      ) -> Tuple[Dict[str, object], ...]:
    """Read the telemetry sidecar's rows, in the order written.

    THE READER LIVES BESIDE THE WRITER, deliberately: this module owns
    append_observation(), observation_row() and OBSERVATION_FIELDS, so
    the code that reads the file back for an integrity check belongs
    here too -- the discipline manifest.py states for its own schema.
    timeline.py has its own reader for the RENDER, which keys rows by
    frame and applies a last-row-wins rule so a re-captured frame means
    what it obviously means; that collapses exactly the information an
    integrity check needs, which is why this returns the rows as they
    were written instead.

    An ABSENT file is an empty result, not an error: a session that has
    recorded nothing has nothing to attest.  A file that exists but
    cannot be read, or that holds a line which is not a JSON object,
    RAISES -- a sidecar that cannot be believed is not the same thing
    as no sidecar, and the difference must not be silently flattened.

    :raises RecordError: on an unreadable file, a torn or non-JSON
        line, or a line holding something other than an object.
    """
    target = _confined(
        default_observations_path(root) if path is None else path,
        "the telemetry sidecar", root)
    if not os.path.exists(target):
        return ()
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as err:
        raise RecordError(
            "cannot open the telemetry sidecar %s for reading: %s"
            % (target, err)) from err
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except (OSError, UnicodeDecodeError) as err:
        raise RecordError(
            "cannot read the telemetry sidecar %s: %s"
            % (target, err)) from err
    rows: List[Dict[str, object]] = []
    for number, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except ValueError as err:
            raise RecordError(
                "line %d of the telemetry sidecar %s is not JSON (%s); "
                "one row is one JSON object on one line, and a fragment "
                "is not repaired by guessing what it was"
                % (number, target, err)) from err
        if not isinstance(row, dict):
            raise RecordError(
                "line %d of the telemetry sidecar %s holds a %s, not an "
                "object" % (number, target, type(row).__name__))
        rows.append(row)
    return tuple(rows)


def row_shows_sidebar(row: Mapping[str, object]) -> bool:
    """True when this telemetry row's capture carried a sidebar reading.

    ONE definition of the release condition, asked of the stored row.
    :meth:`Session._settle_ui_phase` classifies capture.sh's payload as
    each frame arrives and append_observation() copies exactly those
    three columns into the row (SIDEBAR_READING_FIELDS), so the question
    asked live and the question asked of the record are the same
    question -- and both the full scan and the cached index below ask it
    through this function rather than restating it.
    """
    return any(_reading_or_none(row, name) is not None
               for name in SIDEBAR_READING_FIELDS)


def sidebar_frame_of(row: Mapping[str, object]) -> Optional[int]:
    """Return this row's index when it is evidence of a sidebar.

    None for a row that is not: an index that is missing, not a whole
    number, a bool (which `int` would otherwise accept), below
    MIN_FRAME_INDEX, or a row with no reading in any of
    SIDEBAR_READING_FIELDS.  Every one of those is NO EVIDENCE rather
    than an error, which is the direction
    :meth:`Session._recorded_sidebar_frame` documents.

    The record's OWN last index is deliberately not a parameter here:
    the cached index summarises the whole sidecar and the limit belongs
    to the session asking, which applies it to the one answer rather
    than to every row -- see :meth:`Session._recorded_sidebar_frame` for
    why that is the same value.
    """
    index = row.get("frame")
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    if index < manifest.MIN_FRAME_INDEX:
        return None
    return index if row_shows_sidebar(row) else None


@dataclass(frozen=True)
class PhaseIndex:
    """Where the sidebar first appeared, and how much file said so.

    `frame` is the EARLIEST recorded index whose capture carried a
    sidebar reading across the first `cursor` bytes of the sidecar, or
    None when none of them did.  `offset`, `length` and `digest` cite the
    exact bytes of the row that frame was read from, which is what lets a
    later process re-check the cached answer against the sidecar itself
    rather than believing it (:func:`_validated_phase_index`).

    `cursor` is always a line boundary; the sidecar is append-only, so a
    later process reads only the bytes beyond it and folds them into
    `frame`.  `rows` counts the complete rows those bytes held and is
    provenance for a reader rather than an input to any decision: it is
    what tells somebody inspecting the cache how much of the record it
    claims to summarise.
    """

    cursor: int = 0
    rows: int = 0
    frame: Optional[int] = None
    offset: Optional[int] = None
    length: Optional[int] = None
    digest: Optional[str] = None

    def as_record(self, sidecar: str) -> Dict[str, object]:
        """Return the JSON record for this index, naming its source."""
        return {
            "version": PHASE_INDEX_VERSION,
            "sidecar": sidecar,
            "cursor": self.cursor,
            "rows": self.rows,
            "frame": self.frame,
            "offset": self.offset,
            "length": self.length,
            "digest": self.digest,
        }


def _phase_index_from(record: Mapping[str, object],
                      sidecar: str) -> Optional[PhaseIndex]:
    """Rebuild a :class:`PhaseIndex` from a record, or reject it.

    Pure, and deliberately unforgiving: every field is checked for type
    and range, the version must be this one and the sidecar must be the
    file the caller is asking about.  Anything else returns None, which
    makes the caller read the sidecar from the beginning -- the answer is
    always recoverable, so a doubtful cache is never repaired.
    """
    if record.get("version") != PHASE_INDEX_VERSION:
        return None
    if record.get("sidecar") != sidecar:
        return None
    cursor = record.get("cursor")
    rows = record.get("rows")
    for value in (cursor, rows):
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        if value < 0:
            return None
    frame = record.get("frame")
    if frame is None:
        if any(record.get(name) is not None
               for name in ("offset", "length", "digest")):
            # A citation without a frame, or the other way about, is a
            # record that contradicts itself.
            return None
        return PhaseIndex(cursor=int(cursor), rows=int(rows))
    offset = record.get("offset")
    length = record.get("length")
    digest = record.get("digest")
    for value in (frame, offset, length):
        if isinstance(value, bool) or not isinstance(value, int):
            return None
    if frame < manifest.MIN_FRAME_INDEX or offset < 0 or length <= 0:
        return None
    if offset + length > int(cursor):
        return None
    if not isinstance(digest, str) or not digest:
        return None
    return PhaseIndex(
        cursor=int(cursor), rows=int(rows), frame=int(frame),
        offset=int(offset), length=int(length), digest=digest)


def read_phase_index(path: str, sidecar: str) -> Optional[PhaseIndex]:
    """Return the cached phase index at `path`, or None.

    Absent, unreadable, unparseable and self-contradicting are all the
    same answer here -- None, meaning "no usable cache" -- because this
    file is a derived optimisation and the sidecar it summarises is
    always still there to be read.  An unreadable cache must therefore
    never be able to stop a step; that is the one thing this must not do.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as err:
        _warn_once(
            "phase-index-read",
            "the cached phase index %s could not be read (%s), so the "
            "telemetry sidecar is read in full instead; the answer is "
            "the same, it merely costs more" % (path, err))
        return None
    if not text.strip():
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    return _phase_index_from(record, sidecar)


def write_phase_index(path: str, sidecar: str,
                      index: PhaseIndex) -> None:
    """Store `index` durably, and never let failing to stop a step.

    A cache that cannot be written costs the next process a full read of
    the sidecar and nothing else, so the failure is reported once and
    swallowed.  Everything this pipeline treats as evidence is written
    the other way about -- loudly, and refused if it cannot be made
    durable.
    """
    text = json.dumps(
        index.as_record(sidecar), ensure_ascii=False, sort_keys=True)
    try:
        _write_durably(path, text + "\n", "the cached phase index")
    except SessionError as err:
        _warn_once(
            "phase-index-write",
            "the cached phase index %s could not be stored (%s); the "
            "next step will read the telemetry sidecar in full, which "
            "is slower and equally correct" % (path, err))


def _phase_index_lines(descriptor: int, cursor: int,
                       path: str) -> Tuple[List[Tuple[int, bytes]], int]:
    """Return (offset, line) for every complete line beyond `cursor`.

    The second value is the offset the cursor may advance to: the end of
    the last line that ended in a newline.  A trailing FRAGMENT -- the
    signature of an append the power cut short -- is returned for the
    caller to parse, because :func:`read_observations` would parse it
    too and must reach the same verdict, but the cursor stops in front of
    it so that no future process treats those bytes as consumed.

    :raises RecordError: when the sidecar cannot be read from `cursor`.
    """
    try:
        os.lseek(descriptor, cursor, os.SEEK_SET)
        chunks: List[bytes] = []
        while True:
            block = os.read(descriptor, 1 << 16)
            if not block:
                break
            chunks.append(block)
    except OSError as err:
        raise RecordError(
            "cannot read the telemetry sidecar %s from offset %d: %s"
            % (path, cursor, err)) from err
    payload = b"".join(chunks)
    lines: List[Tuple[int, bytes]] = []
    at = cursor
    settled = cursor
    for line in payload.splitlines(True):
        lines.append((at, line))
        at += len(line)
        if line.endswith(b"\n"):
            settled = at
    return lines, settled


def _phase_index_row(line: bytes, offset: int,
                     path: str) -> Optional[Dict[str, object]]:
    """Decode one sidecar line, holding it to read_observations' rules.

    None for a blank line, which that reader skips as well.

    :raises RecordError: for a line that is not a JSON object, in the
        same words and for the same reason -- a sidecar that cannot be
        believed is not the same thing as no sidecar, and the difference
        must not be flattened by the faster path either.
    """
    try:
        text = line.decode("utf-8").strip()
    except UnicodeDecodeError as err:
        raise RecordError(
            "the telemetry sidecar %s is not UTF-8 at offset %d: %s"
            % (path, offset, err)) from err
    if not text:
        return None
    try:
        row = json.loads(text)
    except ValueError as err:
        raise RecordError(
            "the telemetry sidecar %s holds a line at offset %d that is "
            "not JSON (%s); one row is one JSON object on one line, and "
            "a fragment is not repaired by guessing what it was"
            % (path, offset, err)) from err
    if not isinstance(row, dict):
        raise RecordError(
            "the line at offset %d of the telemetry sidecar %s holds a "
            "%s, not an object" % (offset, path, type(row).__name__))
    return row


def _line_digest(line: bytes) -> str:
    """Return the stable short digest of one sidecar line's bytes.

    Both the citation and its later re-check go through here, so they
    cannot disagree about how the bytes are digested.  This is a
    provenance check rather than a security control -- the cited row must
    ALSO parse and still name the same frame with a reading -- so
    :func:`_digest_of`'s truncated hex is ample.
    """
    return _digest_of(line.decode("utf-8", "replace"))


def _validated_phase_index(descriptor: int, path: str,
                           index: PhaseIndex) -> Optional[PhaseIndex]:
    """Re-check a cached index against the sidecar.  Constant time.

    THE SIDECAR IS THE AUTHORITY AND THIS IS WHERE THAT IS ENFORCED.
    Three things are checked, and each is a way the cache could be stale
    or wrong rather than merely old:

    * the file must be at least as long as the cursor.  Shorter means
      these are not the bytes the cache was computed from -- the sidecar
      is append-only, so it never shrinks by itself.
    * the byte before the cursor must be a newline, so the cursor is
      still a line boundary and the tail read starts on a row.
    * the cited row must still be exactly where the cache says, byte for
      byte (its digest), and must still say what the cache claims: the
      index it names, carrying a sidebar reading.

    Returns the index when all of that holds, and None when any of it
    does not -- whereupon the caller reads the whole file and builds a
    new one.  Nothing is repaired in place, because a cache that
    disagrees with the record has no claim to be corrected.
    """
    try:
        size = os.fstat(descriptor).st_size
    except OSError:
        return None
    if size < index.cursor:
        return None
    if index.cursor:
        try:
            boundary = os.pread(descriptor, 1, index.cursor - 1)
        except OSError:
            return None
        if boundary != b"\n":
            return None
    if index.frame is None:
        return index
    try:
        cited = os.pread(
            descriptor, int(index.length), int(index.offset))
    except OSError:
        return None
    if len(cited) != index.length:
        return None
    if _line_digest(cited) != index.digest:
        return None
    try:
        row = _phase_index_row(cited, int(index.offset), path)
    except RecordError:
        return None
    if row is None:
        return None
    return index if sidebar_frame_of(row) == index.frame else None


def _folded_phase_index(index: PhaseIndex, offset: int, line: bytes,
                        row: Mapping[str, object]) -> PhaseIndex:
    """Fold one row into `index`, keeping the EARLIEST sidebar frame.

    The earliest rather than the latest, because the transition is
    one-way -- see :meth:`Session._recorded_sidebar_frame` -- and taking
    the minimum makes the fold order-independent: the same answer comes
    out whether the file was read in one pass or in a hundred tails.
    """
    found = sidebar_frame_of(row)
    if found is None:
        return index
    if index.frame is not None and index.frame <= found:
        return index
    return PhaseIndex(
        cursor=index.cursor, rows=index.rows, frame=found,
        offset=offset, length=len(line), digest=_line_digest(line))


def refresh_phase_index(observations: Optional[str] = None,
                        root: Optional[str] = None,
                        cached: Optional[PhaseIndex] = None,
                        ) -> PhaseIndex:
    """Return the phase index for the sidecar, reading as little as it
    can.

    The remedy for the quadratic phase recovery a performance QA pass
    found, in one function: a valid cache is extended by the bytes
    appended since it was written, and only an absent or unvalidated one
    costs a read of the entire file.  For the one-process-per-keystroke
    flow that is one row per step instead of the whole record, which is
    what turns O(rows^2) over a session into O(rows).

    The path is held to the same approved-root, no-symlink rules as
    :func:`read_observations`, and for its reason: reading is not
    harmless, because a redirected read would report somebody else's file
    as this session's record.  `cached` is read from
    :func:`phase_index_path` when it is not supplied, so a caller that
    already holds it does not read it twice, and the refreshed index is
    stored again only when it actually changed.

    :raises RecordError: exactly where :func:`read_observations` does --
        an unreadable sidecar, or a line that is not a JSON object.  The
        faster path is not the more forgiving one.
    """
    target = _confined(
        default_observations_path(root) if observations is None
        else observations, "the telemetry sidecar", root)
    sidecar = manifest.relative_to_repo(target)
    index_path = phase_index_path(root)
    if not os.path.exists(target):
        return PhaseIndex()
    if cached is None:
        cached = read_phase_index(index_path, sidecar)
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as err:
        raise RecordError(
            "cannot open the telemetry sidecar %s for reading: %s"
            % (target, err)) from err
    try:
        index = (None if cached is None
                 else _validated_phase_index(
                     descriptor, target, cached))
        if index is None:
            if cached is not None:
                _warn_once(
                    "phase-index-stale",
                    "the cached phase index %s no longer matches %s, so "
                    "it is discarded and rebuilt from the sidecar "
                    "itself; the sidecar is the record and the cache is "
                    "only ever a summary of it"
                    % (index_path, target))
            index = PhaseIndex()
        started = index
        lines, settled = _phase_index_lines(
            descriptor, index.cursor, target)
        seen = 0
        for offset, line in lines:
            row = _phase_index_row(line, offset, target)
            if row is None:
                continue
            if offset + len(line) <= settled:
                # A complete row.  A trailing fragment is still folded
                # below -- read_observations() would parse it too -- but
                # it is not counted as consumed, so the next process
                # reads it again once its newline has landed.
                seen += 1
            index = _folded_phase_index(index, offset, line, row)
        index = PhaseIndex(
            cursor=settled, rows=index.rows + seen, frame=index.frame,
            offset=index.offset, length=index.length,
            digest=index.digest)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    # A citation beyond the settled cursor can only come from a torn
    # trailing line, and a record that cites bytes it does not claim to
    # have consumed would be rejected on the next load anyway.  The
    # answer is returned; only the cache is skipped.
    cited_end = int(index.offset or 0) + int(index.length or 0)
    citable = index.frame is None or cited_end <= index.cursor
    if index != started and citable:
        write_phase_index(index_path, sidecar, index)
    return index


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
    # AND THE BYTES ARE THE BYTES THE CAPTURER PUBLISHED.  capture.sh
    # hashes the PNG the instant it renames it into place and reports
    # FRAME_SHA256; re-hashing it here, before a row exists, is what
    # makes the attestation an observation of this file rather than a
    # claim about it.  A mismatch means the frame changed between the
    # capture and this check -- which is the substitution the digest was
    # added to detect -- and it stops the step.
    reported_digest = payload.get("FRAME_SHA256", "").strip()
    if not manifest.SHA256_RE.match(reported_digest):
        raise CaptureError(
            "capture.sh reported FRAME_SHA256=%r for frame %d, which "
            "is not a sha256.  A frame whose bytes are not attested at "
            "the moment they are published is not evidence: every "
            "later stage would have to assume that the pixels on disk "
            "are the pixels the keystroke produced"
            % (payload.get("FRAME_SHA256"), index))
    try:
        observed_digest = manifest.file_digest(expected_path, "frame")
    except manifest.ManifestError as err:
        raise CaptureError(
            "frame %d could not be hashed for comparison against the "
            "capturer's own digest: %s" % (index, err)) from err
    if observed_digest != reported_digest:
        raise CaptureError(
            "capture.sh published frame %d as sha256 %s but %s now "
            "hashes to %s: the bytes changed between the capture and "
            "this check, so no row is appended"
            % (index, reported_digest, expected_file, observed_digest))
    return expected_path


# ---------------------------------------------------------------------
# One step's result.
#
# It carries the frame and the reading BACK to the caller, because the
# loop is observe -> decide in character -> act -> capture -> log and
# the caller cannot decide the next keystroke without them.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class EffectAnnotation:
    """One frame's retrospective observed-effect measurement.

    What the pixels said, what the row said, and what an AMENDMENT would
    therefore state -- reported per frame so that the measurement is
    something an operator reads, and, when it is recorded, recorded in
    the amendment ledger beside the record rather than in it.

    `amended` is True when this measurement was appended to
    playthrough/amendments.jsonl by this pass.  The recorded row is not
    touched on any path: `action` is what the manifest says and goes on
    saying, and `extended` is what a derivative should use instead.
    """

    frame: int
    verdict: str
    screen_pixels: Optional[int]
    action: str
    extended: str
    amended: bool

    @property
    def marked(self) -> bool:
        """True when the measurement calls for a marker this row lacks."""
        return self.extended != self.action


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
    effect: str = EFFECT_UNKNOWN
    effect_detail: Optional["ObservedEffect"] = None
    row: Dict[str, object] = field(default_factory=dict)
    observation: Dict[str, object] = field(default_factory=dict)

    @property
    def clock_readable(self) -> bool:
        """True when the sidebar gave a reading of any kind."""
        return self.ingame_clock is not None

    @property
    def screen_moved(self) -> bool:
        """True when this capture differs from the one before it.

        False for EFFECT_UNCHANGED, and false for the verdicts that are
        not an observation of movement -- so a caller that branches on
        this never reads "we could not tell" as "something happened".
        """
        return self.effect in (EFFECT_CHANGED, EFFECT_OUTSIDE_MAP)

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
    manifest row alike -- so no ordering of operations inside that one
    method can produce a frame and a row that disagree, and no second
    keystroke can reuse an index.  An interruption mid-step is a
    different matter and is handled differently: it leaves the journal
    in flight, every later key is refused, and recover() is what
    resolves it.

    A session is deliberately cheap to open, because the honest way to
    drive this is one process per step: each `session.py step` recovers
    the counter from the append-only record and re-verifies that the
    record and the frames directory still agree before it presses
    anything.  Holding one long-lived instance works identically.

    Usage -- observe, decide in character, act, capture, log:

        session = Session()
        result = session.step(
            "Left", note="walk the top row toward New Game",
            commentary="Not the tutorial. Back along the row.")
        # READ result.path -- which submenu row carries the bar? -- and
        # only then choose the next key.  Never "u" for Custom
        # Character: those hotkeys belong to the top row's tutorial
        # entry too, and the top row wins.  MENU_CUSTOM_CHARACTER_ROUTE
        # is the sequence that was verified against the captures.
    """

    def __init__(self, manifest_path: Optional[str] = None,
                 frames_dir: Optional[str] = None,
                 observations_path: Optional[str] = None,
                 window_id: object = None,
                 capture_script: Optional[str] = None,
                 tool_timeout: Optional[int] = None,
                 capture_timeout: Optional[int] = None,
                 require_durable: bool = True,
                 root: Optional[str] = None,
                 lock_timeout: Optional[int] = None,
                 requested_world: Optional[str] = None,
                 settle_journal: bool = True) -> None:
        """Open a session against an existing or an empty record.

        Opening proves the manifest is one this pipeline may write and
        that BOTH append targets will take an append, then takes the
        step lock, settles any journal a previous run left behind,
        verifies the record, and pins the create-versus-resume decision
        -- in that order, all of it before a keystroke is possible.  A
        session that could not do all of it does not open.

        The two checks that come first are there because of their
        ORDERING rather than their difficulty: the manifest's name and
        the appendability of the two targets are both decidable while
        the game is untouched, and discovering either after the
        keystroke costs an irreversible act for nothing.  See
        manifest_target() and assert_append_target().

        :param manifest_path: the record to append to; the pipeline's
            own manifest by default.
        :param frames_dir: the capture directory to cross-check the
            record against.
        :param observations_path: the telemetry sidecar to append.
        :param window_id: a hint from launch_game.sh; re-authenticated
            against the process behind it before every keystroke, never
            trusted.  $PLAYTHROUGH_WINDOW_ID is read when this is None.
        :param tool_timeout: the ceiling on each xdotool call, in
            seconds; defaults to $PLAYTHROUGH_TOOL_TIMEOUT.  A window
            search or a keystroke that does not return within it is a
            failure rather than a wait, because an unattended loop that
            blocks forever records nothing and reports nothing.
        :param capture_timeout: the ceiling on the whole capture.sh
            invocation, in seconds; defaults to
            $PLAYTHROUGH_CAPTURE_TIMEOUT.  It covers the settle, the
            grab, the luminance measurement and the OCR read together,
            so it is necessarily the longer of the two.
        :param capture_script: the capturer; the one beside this module
            by default.
        :param require_durable: False weakens only the fsync step, for
            a scratch run whose record is not evidence.
        :param root: a test's own artifact tree.  A CALL-SITE argument
            only -- no environment variable reaches it.
        :param lock_timeout: how long to wait for another process's
            step; $PLAYTHROUGH_SESSION_LOCK_TIMEOUT by default.
        :param requested_world: which world to continue when more than
            one is resumable; $PLAYTHROUGH_RESUME_WORLD by default.
        :param settle_journal: False opens WITHOUT completing an
            outstanding step, which is what `reconcile` needs and the
            only thing it is for.  An ambiguous journal makes an ordinary
            open raise, so a session that is being opened in order to
            RESOLVE that journal cannot settle it first.  Every other
            caller leaves this True: skipping recovery is how a step
            would be lost.
        :raises SessionError: when the step lock cannot be taken, or the
            pinned mode contradicts $PLAYTHROUGH_SESSION_MODE.
        :raises RecordError: when the manifest is not the one record
            this pipeline writes, when either append target cannot be
            appended to, or when the manifest and the frames directory
            do not agree, which must never be reconciled silently.
        """
        self._root = root
        # Held to the WRITER's rule about where a record may live, not
        # merely to containment, and held to it HERE: see
        # manifest_target() for why a check that is decidable from the
        # path must not wait until a row is written.
        self._manifest = manifest_target(manifest_path, root)
        self._frames = (default_frames_dir(root)
                        if frames_dir is None
                        else _confined(frames_dir,
                                       "the frames directory", root))
        self._observations = (
            default_observations_path(root)
            if observations_path is None
            else _confined(observations_path,
                           "the telemetry sidecar", root))
        # The amendment ledger, named through manifest.py so that its
        # location is decided by exactly one module.  It is only ever
        # APPENDED to, by `annotate --amend`, and it is never the
        # manifest: manifest.py refuses any path but its own canonical
        # name for each of the two files.
        self._amendments = default_amendments_path(root)
        # The capture attestation ledger, likewise named through
        # manifest.py.  Appended to once per captured frame with the
        # digest capture.sh took at publication; never rewritten.
        self._digests = default_digests_path(root)
        # The observe-before-the-next-key ledger.  One row per capture
        # the operator has read and classified, appended BEFORE the key
        # that follows it is delivered, so the discipline the hard rule
        # asks for leaves evidence rather than resting on good intent.
        self._acks = _confined(
            default_acknowledgments_path(root),
            "the acknowledgment ledger", root)
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
        self._identity: Optional[WindowIdentity] = None
        self._aborted: Optional[str] = None
        self._audit: Optional[Tuple[object, ...]] = None
        self._row: Dict[str, object] = {}
        self._observation: Dict[str, object] = {}
        # The observed-effect guard's own state: the last verdict, and
        # the map-column crop it was measured with.  The crop is
        # resolved once per session because it comes from configuration
        # that does not change while a session is open.
        self._effect = ObservedEffect(EFFECT_UNKNOWN)
        self._verdict: str = EFFECT_UNKNOWN
        self._map_geometry: Optional[str] = None
        self._map_geometry_resolved = False
        # The query boxes read off the last capture's central band.  Held
        # so the CLI can report them beside the verdict: an operator who
        # sees "save-and-quit" here knows which prompt is waiting.
        self._modals: Tuple[str, ...] = ()
        # BOTH APPEND TARGETS ARE PRE-FLIGHTED BEFORE THE TRANSACTION
        # OPENS.  A step appends twice after the keystroke -- the
        # manifest row, then the attestation that carries the immutable
        # key and the sidebar DATE line -- and journal settlement below
        # appends as well, so a target that cannot be appended to must
        # be reported now, while nothing has been sent.  The manifest is
        # pre-flighted without creating anything (an empty
        # manifest.jsonl is itself a problem the readers report); the
        # sidecar's directory is created exactly as append_observation()
        # would create it.
        assert_append_target(self._manifest, "the manifest")
        assert_append_target(self._observations, "the telemetry sidecar",
                             create_parent=True)
        # THE TRANSACTION OPENS HERE.  The lock is taken before the
        # record is read, because "read the last index, then send a key
        # for the next one" is two operations and two processes that
        # interleave them both send a key for the same index.
        self._journal = journal_path(root)
        self._lock = StepLock(
            step_lock_path(root),
            _timeout(ENV_LOCK_TIMEOUT, DEFAULT_LOCK_TIMEOUT)
            if lock_timeout is None else int(lock_timeout))
        self._lock.acquire()
        try:
            # STALE STAGING FILES ARE CLEARED FIRST, under the lock.  The
            # retired rewrite of either evidence file wrote a sibling and
            # renamed it, and an unhandled interruption -- SIGKILL, the
            # power going -- left that sibling inside the tree
            # .gitignore re-includes wholesale, where `git add -A
            # playthrough/` would commit it into an evidence tree nobody
            # authored it into.  Sweeping HERE is now the ONLY thing that
            # can heal the tree: those writers were removed, so no later
            # rewrite is coming to clear one, while a session opens for
            # every step, every status and every annotate.
            manifest.sweep_staging(
                os.path.dirname(self._manifest) or os.curdir,
                manifest.STAGING_PREFIX, manifest.STAGING_SUFFIX,
                manifest.STAGING_OF)
            sweep_observation_staging(self._observations)
            # An interrupted step is completed BEFORE the record is
            # verified, because an interrupted step is exactly what
            # makes the record fail verification.
            self._recovered: Tuple[str, ...] = (
                self._settle_journal() if settle_journal else ())
            # The counter, recovered from the record rather than
            # invented.
            self._frame = self._recover_counter()
            # The create-versus-resume decision, pinned and mandatory.
            self._pin = self._pin_session(requested_world)
            # And the launcher's own verified statement about the screen
            # this session begins on, held against that pin.
            self._launch_state = self._assert_launch_state()
            self._fingerprint = {
                world.name: world.characters
                for world in self._pin.worlds}
            # THE UI PHASE, observed rather than declared.  A create run
            # is at the menu until its survivor exists too, but only a
            # RESUME run has anything refused while it is there -- see
            # MENU_NEW_SURVIVOR_HOTKEYS for why the refusal has to be
            # scoped to the screen rather than to the letter.  The phase
            # is recovered from what this record PHOTOGRAPHED, because
            # one process per keystroke means it cannot be remembered
            # and no file the engine wrote can stand in for a capture.
            # The recovery reads the sidecar INCREMENTALLY, through the
            # validated cache beside the journal (PHASE_INDEX_NAME), so
            # opening a session costs the rows added since the last open
            # rather than the whole record.
            self._sidebar_frame: Optional[int] = None
            self._ui_phase = self._observed_ui_phase()
            # What each capture was READ to be showing, by index.  The
            # route guard's evidence; see :meth:`_classify_screen`.
            self._screens: Dict[int, str] = {}
        except BaseException:
            self._lock.release()
            raise

    # -- the transaction --------------------------------------------

    def close(self) -> None:
        """Release the step lock.  Idempotent.

        A session holds the right to advance the counter for as long as
        it is open, which is why the intended shape is one process per
        step: `session.py step` opens, presses one key, records it and
        closes.  A long-lived instance works identically and holds the
        lock for its whole life, which is the correct exclusion for a
        capture loop.
        """
        self._lock.release()

    def __enter__(self) -> "Session":
        """Support `with Session() as session:`."""
        return self

    def __exit__(self, kind: object, value: object,
                 trace: object) -> bool:
        """Release the lock however the block ended."""
        self.close()
        return False

    @property
    def recovered(self) -> Tuple[str, ...]:
        """What opening this session had to complete, if anything."""
        return self._recovered

    @property
    def pin(self) -> SaveProbe:
        """The pinned create-versus-resume decision for this session."""
        return self._pin

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
        problems = list(manifest.verify_manifest(
            self._manifest, self._frames, require_frames=True,
            root=self._root))
        # AND THE ATTESTATION LEDGER IS PART OF THAT SOUNDNESS.  A
        # counter recovered over a record whose frames are not all
        # attested carries on into a session whose later stages -- the
        # timing, the transitions, the render, the commit -- all verify
        # bytes against that ledger, so the gap surfaces as a
        # publication failure hours after the keystroke that caused it.
        # It is reported here, where the evidence is still on disk and
        # the journal that could complete it has just been settled.
        problems.extend(self._digest_problems(
            manifest.last_recorded_frame(self._manifest, self._root)))
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

    # -- journal recovery -------------------------------------------

    def _last_recorded(self) -> int:
        """Return the last index the manifest holds, without verifying.

        Used only by the recovery path, which runs BEFORE the strict
        verification precisely because an interrupted step is what makes
        that verification fail.
        """
        if not os.path.isfile(self._manifest):
            return 0
        return manifest.last_recorded_frame(self._manifest, self._root)

    def _validated_journal(self,
                           record: Mapping[str, object],
                           ) -> Dict[str, object]:
        """Return the journal's fields, every one of them checked.

        NOTHING IN A JOURNAL IS TAKEN ON TRUST.  It is scratch state
        outside the working tree, written by a process that is no longer
        running, and what it drives is a capture and an append to the
        append-only record -- so a field this module does not check is a
        field that can steer evidence.  Six of them used to be written
        and never read back: the version, the phase, the manifest, the
        frames directory, the display and the attempt count.  A journal
        from a DIFFERENT checkout or a different X display would have
        been completed against this one's record.

        Every failure here raises rather than discarding: the record
        describes a keystroke that may have been delivered, and a
        keystroke cannot be taken back.
        """
        version = record.get("version")
        if version != JOURNAL_VERSION:
            raise RecordError(
                "the step journal %s is version %r; this module writes "
                "and understands version %d.  Version 1 recorded a "
                "phase called 'intent' that did not distinguish a key "
                "which had been delivered from one that had not, so it "
                "is REFUSED rather than reinterpreted -- deciding after "
                "the fact that an ambiguous record meant 'delivered' is "
                "how a keystroke that never happened acquires a frame "
                "and a sentence.  Establish from the game what happened "
                "and run `\"$PLAYTHROUGH_PYTHON\" -B "
                "playthrough/tooling/session.py reconcile`"
                % (self._journal, version, JOURNAL_VERSION))
        phase = record.get("phase")
        if phase not in JOURNAL_PHASES:
            raise RecordError(
                "the step journal %s records phase %r, which is not one "
                "of %s.  A phase this module cannot interpret says "
                "nothing about whether a keystroke was delivered, and "
                "an uninterpretable state is not resolved by guessing"
                % (self._journal, phase, ", ".join(JOURNAL_PHASES)))
        frame = record.get("frame")
        if not isinstance(frame, int) or isinstance(frame, bool):
            raise RecordError(
                "the step journal %s records frame %r, which is not an "
                "index" % (self._journal, frame))
        try:
            validated_frame(frame)
            validated_key = validate_key(record.get("key"))
        except SessionError as err:
            raise RecordError(
                "the step journal %s cannot be believed (%s).  It "
                "records a keystroke that may have been delivered, so "
                "it is not discarded silently"
                % (self._journal, err)) from err
        for name, expected in (
                ("manifest", manifest.relative_to_repo(self._manifest)),
                ("frames_dir",
                 manifest.relative_to_repo(self._frames))):
            found = record.get(name)
            if found != expected:
                raise RecordError(
                    "the step journal %s was written against %s %r, "
                    "but this session's is %r.  A journal belongs to "
                    "ONE record: completing it against another would "
                    "append this keystroke's row to a manifest it was "
                    "never part of"
                    % (self._journal, name, found, expected))
        display = record.get("display")
        current = resolve_display()
        if display != current:
            raise RecordError(
                "the step journal %s was written against display %r and "
                "this session is on %r.  The keystroke it records was "
                "sent to a different X server, so the window it reached "
                "and the screen this session would photograph are not "
                "the same screen"
                % (self._journal, display, current))
        attempts = record.get("capture_attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool) \
                or attempts < 1:
            raise RecordError(
                "the step journal %s records capture_attempts %r, which "
                "is not a count of at least one"
                % (self._journal, attempts))
        payload = record.get("payload")
        if phase == JOURNAL_PHASE_CAPTURED and not isinstance(
                payload, dict):
            raise RecordError(
                "the step journal %s says frame %d was captured but "
                "carries no payload, so there is nothing to complete "
                "the row from.  The phase and the payload are written "
                "in one durable operation, so this combination means "
                "the file was altered"
                % (self._journal, frame))
        return {
            "phase": phase,
            "frame": frame,
            "key": validated_key,
            "action": assert_action_derived(
                validated_key, record.get("action")),
            "commentary": _required_text(
                record.get("commentary"), "the journal's commentary"),
            "capture_attempts": attempts,
            "payload": ({str(name): str(value)
                         for name, value in payload.items()}
                        if isinstance(payload, dict) else None),
        }

    def _settle_journal(self) -> Tuple[str, ...]:
        """Complete, halt on, or discard an interrupted step.

        THE RECOVERY HALF OF THE TRANSACTION.  A keystroke cannot be
        taken back, so the only way a failure after one has been
        delivered can leave a sound record is if the fact of sending it
        was made durable and the step is finished afterwards.  This is
        that finish, and it runs under the step lock before anything else
        reads the record.

        Five states, each with exactly one honest answer:

        * no journal -- nothing was in flight;
        * a journal for an index the manifest already holds -- the row
          landed and only the journal outlived it.  Its TELEMETRY ROW is
          confirmed present first, and repaired from the journal's own
          payload if the interruption fell between the two appends,
          because the sidecar carries the sidebar DATE line timeline.py
          needs to tell a crossing of midnight from a clock that read
          backwards.  Only then is the journal discarded;
        * `captured` for the next index -- the frame is committed to
          playthrough/frames/ and the journal holds the payload
          capture.sh reported for it.  The payload is re-checked against
          the frame ON DISK before it is believed, and the row is then
          appended from it.  Nothing is measured again and nothing is
          invented;
        * `delivered` for the next index -- xdotool returned 0, so the
          key reached the X server, and no frame exists for it.  The
          engine window is re-found, re-authenticated against the
          process behind it and re-focused, and the frame is captured
          NOW at the SAME index.  The sidecar records `recovered: true`
          and the attempt count, so the later capture is visible rather
          than passed off as a first one;
        * `sending` for the next index -- DELIVERY IS UNKNOWN.  This
          HALTS.  It is not photographed, not committed and not
          discarded, because both answers are consistent with the file:
          the key may have reached the game or it may not, and this
          module cannot tell.  Only somebody who can look at the game
          can, and `session.py reconcile` is where they say so.

        An interruption between capture.sh committing the PNG and this
        module recording that it had leaves `delivered` with the frame
        already on disk.  The frame is real, so it is kept and its clock
        is re-read from the pixels by ocr_clock.py -- the same authority
        that read it the first time -- rather than being invented or
        thrown away.
        """
        self._lock.assert_held()
        record = read_journal(self._journal)
        if record is None:
            return ()
        checked = self._validated_journal(record)
        phase = str(checked["phase"])
        frame = int(checked["frame"])
        validated_key = str(checked["key"])
        action = str(checked["action"])
        commentary = str(checked["commentary"])
        attempts = int(checked["capture_attempts"])
        payload = checked["payload"]
        last = self._last_recorded()
        if frame <= last:
            note = self._settle_recorded_journal(frame, validated_key,
                                                 action, payload)
            clear_journal(self._journal)
            LOG.info("%s", note)
            return (note,)
        if frame != last + 1:
            raise RecordError(
                "the step journal %s records frame %d but the manifest "
                "ends at %d.  The journal describes the ONE step that "
                "was in flight, so a gap between them means the record "
                "was edited or a journal was carried between "
                "checkouts; this is not reconciled by guessing"
                % (self._journal, frame, last))
        if phase == JOURNAL_PHASE_SENDING:
            # THE AMBIGUOUS STATE.  Nothing is captured, nothing is
            # committed and nothing is discarded -- see the class of
            # defect this refusal exists for in the JOURNAL_PHASE_*
            # commentary above.
            raise RecordError(
                "THE STEP JOURNAL %s IS AMBIGUOUS AND THIS SESSION WILL "
                "NOT GUESS.  It records that '%s' was about to be sent "
                "for frame %d, and the run ended before delivery was "
                "confirmed -- so the key may have reached the game or it "
                "may not, and nothing on this host can tell which.  "
                "Capturing a frame and appending a row from here would "
                "invent evidence for a keystroke that may never have "
                "happened, and appending nothing would drop one that "
                "did.\n"
                "  Look at the game and establish which it was (the "
                "screen itself, and %s, which holds every frame up to "
                "%d), then say so:\n"
                "  (source playthrough/tooling/env.sh first; this file "
                "is mode 644 and not on PATH, so it is always run "
                "through the pinned interpreter)\n"
                "    SS='playthrough/tooling/session.py'\n"
                "    # it DID land\n"
                "    \"$PLAYTHROUGH_PYTHON\" -B \"$SS\" reconcile "
                "--outcome %s\n"
                "    # it did NOT\n"
                "    \"$PLAYTHROUGH_PYTHON\" -B \"$SS\" reconcile "
                "--outcome %s\n"
                "Nothing else in this session runs until then."
                % (self._journal, validated_key, frame,
                   manifest.relative_to_repo(self._frames), last,
                   RECONCILE_DELIVERED, RECONCILE_NOT_DELIVERED))
        if phase == JOURNAL_PHASE_CAPTURED:
            # THE PAYLOAD IS RE-CHECKED AGAINST THE FRAME ON DISK before
            # it is believed.  It arrives from a file this session did
            # not write, and it decides the row's `file`, `real_ts` and
            # clock: an index that disagrees with the capture on disk, or
            # a capture that is no longer there, has to fail here rather
            # than become a row.
            assert_payload_matches(frame, payload or {}, self._frames)
            note = ("frame %d was captured before the interruption; its "
                    "row has been appended from the payload the capture "
                    "reported, which was re-checked against the frame "
                    "on disk first" % frame)
            self._commit(frame, validated_key, action, commentary,
                         payload or {}, attempts, True)
            LOG.warning("%s", note)
            return (note,)
        existing = os.path.join(
            self._frames, manifest.FRAME_NAME_FORMAT % frame)
        if os.path.isfile(existing):
            payload = self._payload_from_frame(frame, existing)
            note = ("frame %d was already on disk when the step was "
                    "interrupted; its row has been appended and its "
                    "clock re-read from the capture itself" % frame)
        else:
            # THE ENGINE IS RE-AUTHENTICATED BEFORE THE SHUTTER OPENS.
            # This used to photograph the root window straight away, on
            # the strength of a window id from a process that is no
            # longer running -- so a recovery run could photograph
            # whatever now occupies that display and file it as the
            # frame this keystroke produced.  The window is found again,
            # checked against the engine process behind it and focused,
            # exactly as an ordinary step does it.
            self._prepare_window_for(frame, validated_key, recovery=True)
            payload = self._capture_frame(frame)
            assert_payload_matches(frame, payload, self._frames)
            attempts += 1
            note = ("the keystroke '%s' for frame %d had been delivered "
                    "but no frame existed for it; the engine was "
                    "re-authenticated, the frame captured at the same "
                    "index and its row appended"
                    % (validated_key, frame))
        self._commit(frame, validated_key, action, commentary, payload,
                     attempts, True)
        LOG.warning("%s", note)
        return (note,)

    def _settle_recorded_journal(self, frame: int, key: str,
                                 action: str,
                                 payload: Optional[Dict[str, str]],
                                 ) -> str:
        """Make a recorded frame's telemetry whole, then say what it did.

        A journal for an index the manifest already holds means the row
        landed; it does NOT mean the sidecar row beside it did, and it
        does not mean the capture DIGEST beside that did either.  The
        three are separate appends -- manifest row, telemetry row,
        attestation -- and _commit() clears the journal only after all
        three, so an interruption anywhere between them leaves exactly
        this state, and clearing the journal here without looking used to
        lose whichever records had not landed yet.  What is lost is not
        decorative: the sidecar carries the sidebar DATE line, which is
        how timeline.py tells a crossing of midnight from a clock that
        read backwards, and the `key` attestation that makes the row
        auditable; the ledger carries the sha256 every later stage --
        the timing, the transitions, the render and the commit -- checks
        a frame's bytes against before it uses them.

        THE SECOND GAP WAS THE ONE THIS METHOD USED TO MISS ENTIRELY.  It
        repaired the telemetry row and returned, and the caller then
        cleared the journal -- so an interruption between the telemetry
        append and the attestation left a recorded frame with NO digest
        and nothing that would ever notice, until timeline publication
        failed much later with the frame reported unattested.  Worse, the
        "already recorded" case returned before looking at the ledger at
        all, so the commonest shape of that interruption was the one
        guaranteed to be missed.  A code review found it.  Both gaps are
        settled here now, in the order _commit() writes them, and the
        journal is discarded only once all three records cover the frame.

        The sidecar is repaired from the journal's own payload where
        there is one, or measured from the committed frame where there is
        not.  The attestation is re-hashed from the frame on disk and
        recorded `capture` when the journal carried capture.sh's own
        publication digest and the file still hashes to it -- that claim
        WAS taken at publication -- and `recovery` when the digest could
        only be measured now, which is the honest strength of a claim
        about what the bytes ARE rather than about what was captured.
        Either way every value comes from the capture that really
        happened.  If any of it cannot be repaired, the journal is NOT
        cleared: an unrepaired gap that nothing records is worse than a
        session that stops while the evidence is still on disk.
        """
        # THE JOURNAL'S OWN DIGEST, READ BEFORE ANYTHING REWRITES IT.
        # _verified_recovery_payload() below returns a payload whose
        # FRAME_SHA256 is the digest it MEASURED, which is
        # indistinguishable afterwards from one taken at publication --
        # so the attestation's strength has to be decided from the raw
        # journal payload, here, while the difference still exists.
        published = str((payload or {}).get("FRAME_SHA256", "")).strip()
        if not manifest.SHA256_RE.match(published):
            published = ""
        notes: List[str] = []
        if _observation_recorded(self._observations, frame):
            notes.append("its telemetry row was already there")
        else:
            source = "the payload the capture reported"
            if payload is None:
                existing = os.path.join(
                    self._frames, manifest.FRAME_NAME_FORMAT % frame)
                if not os.path.isfile(existing):
                    raise RecordError(
                        "frame %d has a manifest row but no telemetry "
                        "row in %s, and neither the journal's payload "
                        "nor the capture at %s is available to rebuild "
                        "it from.  The journal is left in place: that "
                        "row carries the sidebar date timeline.py "
                        "reconciles a midnight crossing with, and "
                        "losing it silently is worse than stopping here"
                        % (frame, manifest.relative_to_repo(
                            self._observations), existing))
                # _payload_from_frame() verifies the bytes itself, so the
                # measured payload arrives already attested.
                payload = self._payload_from_frame(frame, existing)
                source = "measurements taken from the committed frame"
            else:
                # THE BYTES ARE VERIFIED BEFORE THEY ARE BELIEVED.
                # Recovery is the one path that reads a frame it did not
                # just take, so it is the path a substituted file would
                # come in through: the journal payload carries the digest
                # capture.sh published at publication, and the file must
                # still hash to it.
                payload = self._verified_recovery_payload(frame, payload)
            append_observation(
                self._observations,
                observation_row(frame, payload, key=key, action=action,
                                capture_attempts=1, recovered=True),
                require_durable=self._require_durable, root=self._root)
            notes.append("its telemetry row has been rebuilt from %s "
                         "and appended" % source)
        notes.append(self._settle_capture_attestation(frame, published))
        return ("frame %d had a manifest row and an interrupted step "
                "journal: %s.  The journal has been discarded only now "
                "that the row, the telemetry and the attestation all "
                "cover the frame" % (frame, "; ".join(notes)))

    def _attested_digest(self, frame: int) -> Optional[Dict[str, object]]:
        """Return the ledger's attestation for `frame`, or None.

        :raises RecordError: when the ledger exists and cannot be read.
            A ledger that cannot be read is not an unattested frame, and
            the two must not arrive at a caller as the same answer.
        """
        try:
            rows = manifest.read_frame_digests(self._digests, self._root)
        except manifest.ManifestError as err:
            raise RecordError(
                "the capture attestation ledger %s cannot be read, so "
                "frame %d's digest can neither be checked nor completed: "
                "%s" % (self._digests, frame, err)) from err
        return manifest.attested_digests(rows).get(frame)

    def _settle_capture_attestation(self, frame: int,
                                    published: str) -> str:
        """Make a recorded frame's capture digest whole.  Returns a note.

        The third record of the transaction, settled by the recovery path
        exactly as _attest_capture() settles it for a live step -- which
        is the point: an interruption between the telemetry append and
        the attestation used to leave a frame recorded and unattested for
        good, and every later stage verifies bytes against this ledger.

        `published` is the digest capture.sh reported when it renamed the
        PNG into place, taken off the raw journal payload, or "" when the
        journal carried none.  It decides the STRENGTH of the claim and
        nothing else:

        * already attested -- the file is re-hashed and held to the
          ledger.  Nothing is appended; a second row would say the same
          thing twice, and a MISMATCH is a substituted frame and stops
          the session with the journal left in place.
        * not attested, and the journal carries the publication digest
          the file still hashes to -- appended as `capture`, because that
          is when the digest was taken.
        * not attested, and no publication digest survives -- appended as
          `recovery`, and the note says so.  It establishes what the
          bytes ARE, not that they are the bytes the keystroke produced.

        :raises RecordError: on an unreadable ledger, an unhashable or
            missing frame, a digest mismatch, or a failed append.  Every
            one of them leaves the journal in place deliberately.
        """
        path = os.path.join(self._frames,
                            manifest.FRAME_NAME_FORMAT % frame)
        attested = self._attested_digest(frame)
        try:
            observed = manifest.file_digest(path, "frame")
            size = os.path.getsize(path)
        except (manifest.ManifestError, OSError) as err:
            raise RecordError(
                "frame %d has a manifest row, and the capture at %s "
                "cannot be hashed for its attestation: %s.  The journal "
                "is left in place rather than clearing it over a frame "
                "whose bytes nothing has checked"
                % (frame, manifest.relative_to_repo(path), err)) from err
        if attested is not None:
            expected = str(attested.get("sha256", ""))
            if expected and expected != observed:
                raise RecordError(
                    "frame %d is attested as sha256 %s in %s but %s now "
                    "hashes to %s.  These are not the bytes that were "
                    "captured; the journal is left in place so the "
                    "frame can be looked at rather than written about"
                    % (frame, expected,
                       manifest.relative_to_repo(self._digests),
                       manifest.frame_file(frame), observed))
            return ("its capture digest was already attested (%s)"
                    % (attested.get("attested") or "unstated"))
        if published and published != observed:
            raise RecordError(
                "frame %d was published as sha256 %s by the capture the "
                "step journal records, but %s now hashes to %s.  These "
                "are not the bytes that were captured, so no "
                "attestation is written about them and the journal is "
                "left in place"
                % (frame, published, manifest.frame_file(frame),
                   observed))
        strength = (manifest.DIGEST_AT_CAPTURE if published
                    else manifest.DIGEST_AT_RECOVERY)
        try:
            manifest.append_frame_digest(
                self._digests, frame, manifest.frame_file(frame),
                observed, size, strength, manifest.utc_timestamp(),
                require_durable=self._require_durable, root=self._root)
        except manifest.ManifestError as err:
            raise RecordError(
                "frame %d has a manifest row but no attestation in %s, "
                "and one could not be appended: %s.  The journal is "
                "left in place; an unattested recorded frame is the "
                "state that ledger exists to prevent"
                % (frame, manifest.relative_to_repo(self._digests),
                   err)) from err
        if not published:
            _warn(
                "frame %d had no capture-time digest to complete its "
                "attestation from -- the interruption fell before the "
                "ledger append and the journal carried none -- so its "
                "digest was measured now and recorded as '%s'.  That "
                "establishes what the bytes ARE; only a digest taken at "
                "publication establishes that they are the bytes the "
                "keystroke produced"
                % (frame, manifest.DIGEST_AT_RECOVERY))
        return ("its capture digest was missing and has been appended "
                "as '%s'" % strength)

    def _verified_recovery_payload(
            self, frame: int,
            payload: Dict[str, str]) -> Dict[str, str]:
        """Hold a recovered payload's frame to an attested digest.

        Returns the payload, with FRAME_SHA256 set to the digest that was
        verified.  Three cases, and each is stated in the row rather than
        smoothed over:

        * THE JOURNAL CARRIES THE CAPTURER'S OWN DIGEST -- the strongest
          case, because it was taken at publication.  The file must hash
          to it.
        * THE LEDGER ALREADY ATTESTS THIS FRAME -- a step that was
          recorded and is being re-examined.  The file must hash to that.
        * NEITHER EXISTS -- a frame captured before the ledger did.  The
          digest is measured now and the row will say `recovery`, which
          is the honest strength of the claim: it establishes what the
          bytes ARE, not that they are what was captured.

        :raises RecordError: on a mismatch, leaving the journal in place
            so the operator can look at the frame rather than having a
            row written about it.
        """
        index = manifest._validated_frame(frame)
        path = os.path.join(self._frames,
                            manifest.FRAME_NAME_FORMAT % index)
        try:
            observed = manifest.file_digest(path, "frame")
        except manifest.ManifestError as err:
            raise RecordError(
                "frame %d cannot be hashed, so its recovered row would "
                "rest on bytes nothing has checked: %s" % (index, err)
            ) from err
        expected = str(payload.get("FRAME_SHA256", "")).strip()
        source = "the journal's own payload"
        if not manifest.SHA256_RE.match(expected):
            expected = ""
            try:
                attested = manifest.attested_digests(
                    manifest.read_frame_digests(self._digests,
                                                self._root))
            except manifest.ManifestError as err:
                raise RecordError(
                    "the capture attestation ledger %s cannot be read, "
                    "so frame %d's bytes cannot be checked before its "
                    "row is rebuilt: %s"
                    % (self._digests, index, err)) from err
            row = attested.get(index)
            if row is not None:
                expected = str(row.get("sha256", ""))
                source = "the capture attestation ledger"
        if expected and expected != observed:
            raise RecordError(
                "frame %d is attested as sha256 %s by %s, but %s now "
                "hashes to %s.  These are not the bytes that were "
                "captured, so no row is rebuilt about them and the "
                "journal is left in place"
                % (index, expected, source,
                   manifest.frame_file(index), observed))
        if not expected:
            _warn(
                "frame %d has no capture-time digest to check against "
                "-- neither the journal nor %s attests it -- so its "
                "digest is measured now and recorded as '%s'.  That "
                "establishes what the bytes ARE; only a digest taken at "
                "publication establishes that they are the bytes the "
                "keystroke produced"
                % (index, manifest.relative_to_repo(self._digests),
                   manifest.DIGEST_AT_RECOVERY))
        payload = dict(payload)
        payload["FRAME_SHA256"] = observed
        return payload

    def _payload_from_frame(self, index: int,
                            path: str) -> Dict[str, str]:
        """Rebuild a payload by MEASURING an already-captured frame.

        Only ever used for a frame that is on disk with no row: the
        capture happened, so the pixels are real -- and THAT is the
        assumption a security review objected to, because nothing checked
        it.  So the payload this builds is passed through
        :meth:`_verified_recovery_payload` before it is returned: the
        bytes are hashed and held to whatever attestation exists for the
        index, and `real_ts` still comes from the file's modification
        time, which is now recorded as a `recovery` attestation rather
        than as the capture instant it is not.  Every other field here is
        measured from the file or reported as unavailable -- the clock
        through ocr_clock.py, which is the same
        authority that reads it during a normal step, and `real_ts` from
        the capture's own modification time.  Nothing is guessed: a clock
        that will not read comes back empty, which is the honest value
        and the one timeline.py reconciles.
        """
        import datetime
        try:
            moment = datetime.datetime.fromtimestamp(
                os.stat(path).st_mtime, datetime.timezone.utc)
        except OSError as err:
            raise RecordError(
                "cannot measure %s in order to complete frame %d's "
                "row: %s" % (path, index, err)) from err
        payload: Dict[str, str] = {
            CAPTURE_MODE_KEY: CAPTURE_MODE_PRODUCTION,
            "FRAME_INDEX": str(index),
            "FRAME_NAME": manifest.FRAME_NAME_FORMAT % index,
            "FRAME_FILE": manifest.frame_file(index),
            "FRAME_PATH": path,
            "FRAME_GEOMETRY": "",
            "REAL_TS": manifest.utc_timestamp(moment),
            "CAPTURE_TOOL": "recovered",
            "LUMA_MEAN": "",
            "LUMA_STDDEV": "",
            "CLOCK_RECT": "",
            "CLOCK_RECT_FROM": "recovered",
            "CLOCK_SOURCE": "ocr_clock.py",
            "CLOCK_STATUS": "unreadable",
            "CLOCK": "",
            "TIME_PHRASE": "",
            "DATE": "",
            "DATE_STATUS": "unreadable",
            "OBSERVATIONS": self._observations,
            # Filled in by _verified_recovery_payload() below, which is
            # the one place a recovered frame's bytes are hashed: the
            # column is declared here so the payload this function
            # returns carries every key capture.sh's own contract does.
            "FRAME_SHA256": "",
        }
        try:
            reading = ocr_clock.read_clock(path)
        except ocr_clock.OcrClockError as err:
            _warn("frame %d's clock could not be re-read from %s (%s); "
                  "the row records it as unread, which is what it is"
                  % (index, path, err))
            return self._verified_recovery_payload(index, payload)
        # THE CANONICAL STATUS VOCABULARY, which capture.sh defines as
        # read | unreadable | fault | skipped.  This used to emit "exact"
        # and "coarse" -- words from ocr_clock.py's own classification --
        # so a recovered frame's telemetry row carried a status no other
        # row in the sidecar used and no consumer knew.  The DISTINCTION
        # those two words carried is not lost: an exact reading lands in
        # CLOCK, a coarse phrase lands in TIME_PHRASE, and that is
        # exactly how an ordinary capture reports the same difference.
        if reading.clock:
            payload["CLOCK"] = reading.clock
            payload["CLOCK_STATUS"] = "read"
        elif reading.phrase:
            payload["TIME_PHRASE"] = reading.phrase
            payload["CLOCK"] = reading.phrase
            payload["CLOCK_STATUS"] = "read"
        if reading.date:
            payload["DATE"] = reading.date
            payload["DATE_STATUS"] = "read"
        payload["CLOCK_RECT"] = reading.rect or ""
        return self._verified_recovery_payload(index, payload)

    def _sidecar_problems(self, last: int) -> List[str]:
        """Report a sidecar that does not cover the record.  Read-only.

        THE THIRD LEG OF THE IDENTITY.  One keystroke is one frame, one
        manifest row AND one attestation, and until this existed only
        the first two were ever compared: a sidecar append that failed
        after its manifest row was stored left that frame's immutable
        key and its sidebar DATE line missing FOREVER -- the journal
        entry for the step is stale by then, because the row it
        describes is on the device, so nothing replays it -- while
        `status` reported the record sound because it had never looked.
        An integrity check that cannot see the gap it is meant to catch
        is worse than no check, so the gap is reported here.

        It is REPORTED rather than repaired.  The missing attestation
        cannot be reconstructed honestly: `real_ts` and the clock could
        be re-measured from the capture, but the KEY could not -- the
        one place it was ever written down is the row that did not land
        -- and a backfilled row with a guessed key would be exactly the
        fabrication HR6 forbids.  A note in
        playthrough/TECHNICAL_NOTES.md is the remedy for a shortfall,
        the same way it is for every other correction to a captured
        record.

        A REPEATED index is deliberately NOT a problem.  The sidecar is
        append-only and timeline.py reads it with a last-row-wins rule
        precisely so that a re-captured frame means what it obviously
        means; treating a second row for one frame as a defect here
        would contradict the reader that consumes it.

        :param last: the last index the manifest holds; 0 for a record
            with no rows at all, which is the fresh-session case.
        """
        problems: List[str] = []
        try:
            rows = read_observations(self._observations, self._root)
        except RecordError as err:
            # Reported rather than raised, so one unreadable sidecar
            # cannot stop the caller from hearing about the rest of the
            # record -- the same treatment manifest.verify_manifest()
            # gives a manifest it cannot read.
            return [str(err)]
        covered = set()
        for number, row in enumerate(rows, start=1):
            index = row.get("frame")
            if isinstance(index, bool) or not isinstance(index, int):
                problems.append(
                    "row %d of %s records frame %r, which is not an "
                    "index, so that attestation cannot be matched to a "
                    "capture" % (number, self._observations, index))
                continue
            covered.add(index)
        missing = sorted(set(_indices_through(last)) - covered)
        if missing:
            problems.append(
                "%d recorded frame(s) have no telemetry row in %s (%s); "
                "the attestation carrying the key that was pressed and "
                "the sidebar date line is missing for each of them, so "
                "the record is incomplete even though the frames and "
                "the manifest agree"
                % (len(missing), self._observations,
                   _summarised(missing)))
        stray = sorted(index for index in covered
                       if index < manifest.MIN_FRAME_INDEX or
                       index > last)
        if stray:
            problems.append(
                "%s holds %d telemetry row(s) for frame(s) the manifest "
                "does not record (%s); the record runs 1..%d, so those "
                "attestations describe captures no row accounts for"
                % (self._observations, len(stray), _summarised(stray),
                   last))
        return problems

    def _digest_problems(self, last: int) -> List[str]:
        """Report a ledger that does not cover the record.  Read-only.

        THE FOURTH LEG OF THE SAME IDENTITY, and the one nothing used to
        compare.  One keystroke is one frame, one manifest row, one
        telemetry attestation AND one capture digest; the digest is what
        makes the other three mean something, because it is the only
        record that ties an index to the BYTES that were photographed.
        Until this existed a frame whose attestation append failed -- or
        whose step was interrupted between the telemetry row and the
        ledger -- was reported sound by `status` and by this module's own
        verification, and the gap first became visible when timeline
        publication refused the frame as unattested, long after the
        evidence that could have completed it had gone.

        It is REPORTED rather than repaired.  Recovery repairs the gap
        while the step journal is still there to say what was in flight
        (:meth:`_settle_capture_attestation`); once that journal is gone
        the honest strength of any digest measured here is `recovery`,
        and silently writing one would present a claim about what the
        bytes are as a claim about what was captured.

        A REPEATED index is deliberately not a problem: the ledger is
        append-only and a retry inside one step attests the same index
        twice, which is what `manifest.attested_digests` reads with a
        last-row-wins rule.

        :param last: the last index the manifest holds; 0 for a record
            with no rows at all.
        """
        problems: List[str] = []
        try:
            rows = manifest.read_frame_digests(self._digests, self._root)
        except manifest.ManifestError as err:
            # Reported rather than raised, for the same reason
            # _sidecar_problems reports an unreadable sidecar: one
            # unreadable evidence file must not stop a caller from
            # hearing about the rest of the record.
            return [str(err)]
        covered = {row.get("frame") for row in rows
                   if not isinstance(row.get("frame"), bool) and
                   isinstance(row.get("frame"), int)}
        missing = sorted(set(_indices_through(last)) - covered)
        if missing:
            problems.append(
                "%d recorded frame(s) have no capture digest in %s (%s); "
                "the attestation that ties each index to the bytes that "
                "were photographed is missing for them, so every later "
                "stage that verifies a frame against that ledger will "
                "refuse it"
                % (len(missing),
                   manifest.relative_to_repo(self._digests),
                   _summarised(missing)))
        stray = sorted(index for index in covered
                       if index < manifest.MIN_FRAME_INDEX or
                       index > last)
        if stray:
            problems.append(
                "%s holds %d capture digest(s) for frame(s) the manifest "
                "does not record (%s); the record runs 1..%d, so those "
                "attestations describe captures no row accounts for"
                % (manifest.relative_to_repo(self._digests), len(stray),
                   _summarised(stray), last))
        return problems

    def verify_record(self) -> Tuple[str, ...]:
        """Re-check the record against the frames.  Read-only.

        Exposed so a caller can assert the invariant between steps
        without opening a new session.  An empty result means the
        manifest satisfies its schema, every row's capture is on disk,
        no capture is unaccounted for, every recorded frame has its
        telemetry attestation AND every recorded frame has its capture
        digest -- see :meth:`_sidecar_problems` and
        :meth:`_digest_problems` for why those comparisons belong in the
        same answer as the first two.
        """
        if not os.path.isfile(self._manifest):
            problems = []
            on_disk = self._frames_on_disk()
            if on_disk:
                problems.append(
                    "%d capture(s) in %s with no manifest at %s"
                    % (len(on_disk), self._frames, self._manifest))
            # last=0: with no record at all, every telemetry row and
            # every attestation is one for a capture nothing accounts
            # for.
            problems.extend(self._sidecar_problems(0))
            problems.extend(self._digest_problems(0))
            return tuple(problems)
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
        problems.extend(self._sidecar_problems(last))
        problems.extend(self._digest_problems(last))
        return tuple(problems)

    # -- the retroactive observed-effect pass -----------------------

    def annotate_recorded_effects(
            self, frames: Optional[Sequence[int]] = None,
            amend: bool = False) -> Tuple[EffectAnnotation, ...]:
        """Measure recorded captures; with `amend`, record an amendment.

        WHY THIS ONLY EVER REPORTS.  The live observed-effect guard
        compares each capture with the one before it and appends
        `; nothing on the screen changed` to the action of a row whose
        capture is identical to its predecessor -- so that a row says
        what was intended AND what was observed.  It was written after a
        QA pass found rows narrating an effect their own capture
        contradicts, which means the frames taken BEFORE it exists have
        no such marker even where the pixels call for one.  This pass is
        how that residue is closed: with the same measurement, on the
        same evidence, rather than by hand.

        AND IT DOES NOT TOUCH THE RECORD.  An earlier version of this
        method rewrote the manifest row and its telemetry attestation in
        place, one after the other.  A security review named both halves
        of why that was wrong: a mechanism able to rewrite captured
        evidence makes every artifact derived from it deniable, and two
        sequential rewrites of two files leave a window in which a crash
        splits the record.  Both are gone.  What `amend` does now is
        append ONE row to playthrough/amendments.jsonl -- one artifact,
        one locked durable append, nothing to split -- stating the
        recorded action, the amended action, the measurement that
        established it and why the recorded text could not stand on its
        own.  manifest.resolve_rows() then applies it to the transcript
        and the caption cues, and only where the amendment's digest
        still matches the row it names.

        WHAT IT WILL AND WILL NOT MEASURE.  The verdict comes from
        :func:`classify_effect` with NO map geometry, so the only marker
        it can ever produce is MARKER_UNCHANGED, for a capture that does
        not differ from its predecessor by a single pixel.  The
        map-column verdict is deliberately out of reach: that
        measurement was never made for these frames, and a narration
        that is accurate must not acquire an amendment on a measurement
        taken long after the keystroke.  Only the action is ever
        amended here -- never the commentary, the clock, the timestamp
        or the frame.

        Read-only unless `amend` is true, so the measurement can be
        inspected before anything is recorded.

        :param frames: the indices to measure; every recorded frame from
            the second onward when None.  The first frame has no
            predecessor and is therefore EFFECT_FIRST, which measures
            nothing.
        :raises RecordError: for an index this record does not hold, or
            when an amendment cannot be appended; the record and the
            ledger are then left exactly as they stand.
        """
        if self._frame < manifest.MIN_FRAME_INDEX:
            return ()
        rows = {row["frame"]: row for row in manifest.read_rows(
            self._manifest, root=self._root)}
        digests = manifest.row_digests(self._manifest, root=self._root)
        recorded_amendments = list(manifest.read_amendments(
            self._amendments, self._root))
        already = {(one.get("frame"), one.get("field"))
                   for one in recorded_amendments}
        number = len(recorded_amendments)
        wanted = (list(_indices_through(self._frame)) if frames is None
                  else [manifest._validated_frame(one) for one in frames])
        results: List[EffectAnnotation] = []
        for index in wanted:
            if index not in rows:
                raise RecordError(
                    "%s records no frame %d, so there is nothing to "
                    "measure for it"
                    % (manifest.relative_to_repo(self._manifest), index))
            current = os.path.join(
                self._frames, manifest.FRAME_NAME_FORMAT % index)
            previous = (
                os.path.join(self._frames,
                             manifest.FRAME_NAME_FORMAT % (index - 1))
                if index - 1 >= manifest.MIN_FRAME_INDEX else None)
            for path in (previous, current):
                if path is not None and not os.path.isfile(path):
                    raise RecordError(
                        "%s is missing, so frame %d cannot be measured "
                        "against the capture before it"
                        % (manifest.relative_to_repo(path), index))
            effect = classify_effect(previous, current)
            recorded = rows[index]["action"]
            extended = annotate_action(recorded, effect)
            wrote = False
            if amend and extended != recorded:
                if (index, "action") in already:
                    LOG.info(
                        "frame %d already carries an action amendment; "
                        "one narration carries one correction, so "
                        "nothing was appended", index)
                else:
                    number += 1
                    try:
                        manifest.append_amendment(
                            self._amendments, number,
                            manifest.utc_timestamp(), index, "action",
                            digests[index], recorded, extended,
                            self._effect_basis(index, effect),
                            EFFECT_AMENDMENT_REASON,
                            require_durable=self._require_durable,
                            root=self._root)
                    except manifest.ManifestError as err:
                        raise RecordError(
                            "frame %d's measurement could not be "
                            "recorded as an amendment: %s.  The record "
                            "and the ledger are unchanged"
                            % (index, err)) from err
                    already.add((index, "action"))
                    wrote = True
                    LOG.info(
                        "frame %d: %s -- amendment %d records %r "
                        "against the row, which is unchanged",
                        index, effect.verdict, number,
                        EFFECT_MARKERS.get(effect.verdict))
            results.append(EffectAnnotation(
                frame=index, verdict=effect.verdict,
                screen_pixels=effect.screen_pixels,
                action=recorded, extended=extended,
                amended=wrote))
        return tuple(results)

    @staticmethod
    def _effect_basis(index: int, effect: "ObservedEffect") -> str:
        """State what the measurement established, in one sentence."""
        return (
            "session.py annotate measured this capture against frame "
            "%d: the verdict is %s%s, so the keystroke reached no "
            "screen it could alter.  The comparison is reproducible "
            "from the two committed captures."
            % (index - 1, effect.verdict,
               "" if effect.screen_pixels is None
               else " with %d changed pixel(s)" % effect.screen_pixels))

    # -- the window -------------------------------------------------

    @property
    def window(self) -> Optional[int]:
        """The window id last resolved, or None before the first step.

        A cached answer, not a trusted one: :meth:`step` re-verifies it
        against the class search before every keystroke.
        """
        return self._window

    @property
    def identity(self) -> Optional[WindowIdentity]:
        """The process behind the window, as last authenticated."""
        return self._identity

    def refresh_window(self) -> int:
        """Authenticate the game window again and remember it.

        CALLED BEFORE EVERY KEYSTROKE, and it re-establishes the window's
        IDENTITY rather than merely its existence: the process behind it
        must be this checkout's binary, running from the repository root,
        started with this session's --userdir, on this session's display,
        and it must be the only such window.  The class is a name any
        process can claim and a second real engine claims it honestly,
        so a keystroke is never sent on the strength of the name alone.

        The hint -- launch_game.sh's PLAYTHROUGH_WINDOW_ID, or the id
        authenticated for the last step -- is checked against the
        authenticated window rather than trusted, so a stale id is
        reported instead of keyed.

        :raises WindowError: when no window authenticates, when more than
            one does, or when the remembered one is no longer the one.
        """
        hint = self._window if self._window is not None else (
            self._window_hint)
        identity = authenticated_window(
            hint, self._tool_timeout, self._root)
        self._identity = identity
        self._window = identity.window
        return self._window

    # -- the integrity pre-flights, on every step -------------------

    def audit_bindings(self) -> str:
        """Prove no debug action is bound.  Cheap enough for every step.

        The result is cached against the keybindings file's identity --
        device, inode, size and modification time -- so a step costs one
        lstat while a file that CHANGED mid-session is read again.  An
        integrity check that only ran when somebody asked for it is
        evidence of nothing, which is why this is not optional.
        """
        path = keybindings_path(self._root)
        try:
            info = os.lstat(path)
            token: Tuple[object, ...] = (
                path, info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_mode)
        except FileNotFoundError:
            token = (path, None)
        except OSError as err:
            raise CheatGuard(
                "cannot inspect %s (%s), so whether a debug action is "
                "bound cannot be established" % (path, err)) from err
        if self._audit is not None and self._audit[0] == token:
            return str(self._audit[1])
        finding = assert_no_debug_bindings(path, self._root)
        self._audit = (token, finding)
        LOG.debug("%s", finding)
        return finding

    def _pin_session(self,
                     requested_world: Optional[str]) -> SaveProbe:
        """Pin create-versus-resume, and refuse a contradiction.

        MANDATORY, not optional: the hard rule is that an existing save
        is CONTINUED rather than replaced, and a rule nothing checks is a
        rule a driver can walk straight past.  The probe runs before the
        first keystroke, its answer is kept for the life of the session,
        and :meth:`_assert_save_pin` holds every later step against it.

        $PLAYTHROUGH_SESSION_MODE is honoured as an OPERATOR DECLARATION
        and must agree with what the save tree actually shows.  A
        disagreement is refused rather than resolved: a declared
        'resume' against an empty tree is precisely the mistake that
        creates a second survivor where one was to be continued.

        ONE disagreement is legitimate and is recorded rather than
        refused: a declared 'create' whose record already holds rows and
        whose tree now shows a save.  That is what a create run LOOKS
        like once the survivor exists -- the save is written during
        character creation, part-way through the very session that
        declared 'create' -- and refusing it would stop a correct run at
        its own halfway point.  An empty record makes it a refusal
        again, because then the save was somebody else's.

        THE RECORDED-DEATH REFUSAL IS SCOPED THE SAME WAY, and for the
        same reason.  :func:`probe_save_resume` refuses a live save
        belonging to a survivor the record shows dying, because loading
        such a tree would put a dead survivor back into play.  That is
        the right answer for a tree being LOADED and the wrong one for
        the run that is recording the death itself: the last-words
        keystrokes are captured while the live save is still on disk,
        since the engine only moves it in ``cleanup_at_end()`` after the
        death screen finishes.  A driver that invokes this module once
        per keystroke re-runs this pre-flight on every one of them, so
        the strict reading would refuse every frame after the first
        last-words keystroke and make a death ending -- a PERMITTED
        ending -- impossible to finish recording.  So the refusal is
        asked for only when the record is EMPTY, which is the case it
        exists for: a fresh run pointed at somebody else's dead tree.
        Once this record holds rows the death in it is this session's
        own, the save pin below still holds the world and survivor
        steady, and `session.py probe` keeps the strict reading for the
        operator-facing "should this tree be loaded" decision.
        """
        probe = probe_save_resume(
            None, requested_world, self._root,
            refuse_recorded_death=self._frame == 0)
        declared = os.environ.get(ENV_SESSION_MODE, "").strip()
        if declared and declared != probe.mode:
            continuing = bool(
                declared == SESSION_MODE_CREATE and
                probe.resume and
                self._frame > 0)
            if not continuing:
                evidence = "; ".join(probe.notes) or "No note."
                raise SessionError(
                    "$%s says '%s' but the save tree under %s says "
                    "'%s'.  %s  The declaration and the evidence must "
                    "agree before a key is sent: an existing save is "
                    "continued, never replaced"
                    % (ENV_SESSION_MODE, declared,
                       manifest.relative_to_repo(probe.save_dir),
                       probe.mode, evidence))
            LOG.info(
                "$%s declared '%s' and the survivor's save now exists "
                "in world '%s'; this is frame %d of that same session, "
                "so the save is this run's own",
                ENV_SESSION_MODE, declared, probe.world, self._frame)
        for note in probe.notes:
            LOG.info("%s", note)
        return probe

    def _assert_launch_state(self) -> str:
        """Hold the launcher's verified starting screen against the pin.

        THE COUPLING THAT WAS DOCUMENTED AND NEVER BUILT.  launch_game.sh
        publishes $PLAYTHROUGH_INITIAL_UI_STATE from what it verified
        after the captured launch came up, and its comment (:3220) says
        the value exists so that this module's refusals and the operator
        work "from the same declared state rather than from two
        assumptions".  Nothing here had ever read it.  A security review
        named that under route integrity, and this is the coupling: two
        independent readings of the same question -- the launcher's
        diagnostic capture of the screen, and this module's own probe of
        the save tree -- are required to AGREE before a key is sent.

        It can only refuse.  Nothing below is relaxed by any value this
        returns, including the one that says the launcher established
        nothing: the observed-phase refusals stand on their own evidence.
        """
        declared = os.environ.get(ENV_INITIAL_UI_STATE, "").strip()
        if declared == LAUNCH_STATE_UNDECLARED:
            LOG.info(
                "$%s is not set, so the launcher established no starting "
                "screen for this session; every refusal in this module "
                "stands on its own observed evidence regardless",
                ENV_INITIAL_UI_STATE)
            return LAUNCH_STATE_UNDECLARED
        if declared not in LAUNCH_UI_STATES:
            raise SessionError(
                "$%s says %r, which is not one of the states "
                "launch_game.sh publishes (%s).  A starting screen this "
                "module cannot reason about is not one it may act on, so "
                "the session stops here rather than guessing which of "
                "them was meant"
                % (ENV_INITIAL_UI_STATE, declared,
                   ", ".join(repr(state) for state in LAUNCH_UI_STATES)))
        if (declared == LAUNCH_STATE_LOAD_REQUIRED and
                not self._pin.resume):
            raise SessionError(
                "$%s says %r -- the launcher VERIFIED that a save exists "
                "and that the first captured keystrokes must load it -- "
                "but this session pinned '%s' from the save tree under "
                "%s.  The two readings of the same question disagree, "
                "and an existing save is continued rather than replaced, "
                "so nothing is sent until they agree"
                % (ENV_INITIAL_UI_STATE, declared, self._pin.mode,
                   manifest.relative_to_repo(self._pin.save_dir)))
        if declared == LAUNCH_STATE_CREATE_PERMITTED and self._pin.resume:
            # THE ONE DISAGREEMENT THAT IS LEGITIMATE, and it is the same
            # one _pin_session records rather than refuses: a create run
            # writes its survivor's save DURING character creation, so
            # from that frame onward the tree says 'resume' while the
            # launcher's statement about the screen it started from stays
            # true.  An EMPTY record makes it a contradiction again --
            # then the save was somebody else's.
            if self._frame > 0:
                LOG.info(
                    "$%s says %r and the save tree now says 'resume'; "
                    "this record already holds %d frame(s), so the "
                    "survivor's save is this create run's own, written "
                    "part-way through itself",
                    ENV_INITIAL_UI_STATE, declared, self._frame)
                return declared
            raise SessionError(
                "$%s says %r -- the launcher took a CREATE launch -- but "
                "this session's own probe of %s pinned 'resume' with an "
                "EMPTY record: %s.  A survivor that already exists is "
                "continued, never replaced; stop, and take the launch "
                "the save tree actually calls for"
                % (ENV_INITIAL_UI_STATE, declared,
                   manifest.relative_to_repo(self._pin.save_dir),
                   "; ".join(self._pin.notes) or "No note."))
        if declared == LAUNCH_STATE_UNVERIFIED:
            LOG.warning(
                "$%s says %r: the launcher's diagnostic capture of the "
                "starting screen could not be read, so nothing about the "
                "screen is established.  No refusal in this module is "
                "relaxed by that -- the UI phase is still observed from "
                "this record's own captures, and a resumed session still "
                "refuses every new-survivor keystroke while it is on a "
                "menu",
                ENV_INITIAL_UI_STATE, declared)
            return declared
        LOG.info(
            "$%s says %r and this session pinned '%s'; the launcher's "
            "verified screen and this module's probe of the save tree "
            "agree", ENV_INITIAL_UI_STATE, declared, self._pin.mode)
        return declared

    def _save_fingerprint(self) -> Dict[str, Tuple[str, ...]]:
        """Return each world's character set.  The pin's comparand.

        THE WORLD SCAN, NOT THE CREATE-VERSUS-RESUME DECISION, which is
        why the death refusal is switched off for this one call.  This
        runs on every step, and a session recording a legitimate death
        passes through precisely the state that refusal describes: the
        last-words keystroke is captured while the live save is still on
        disk, because the engine only moves it in ``cleanup_at_end()``
        after the death screen finishes.  Refusing here would make death
        -- a permitted ending -- impossible to record, and it would do so
        several hundred keystrokes into a session.  The pre-flight keeps
        the strict reading, which is where it belongs: it decides whether
        to LOAD such a tree, and this only counts what is in it.
        """
        probe = probe_save_resume(
            self._pin.save_dir, self._pin.world, self._root,
            refuse_recorded_death=False)
        return {world.name: world.characters for world in probe.worlds}

    # -- the resume lifecycle ---------------------------------------

    @property
    def ui_phase(self) -> str:
        """Which screen the engine is believed to be on: menu|in-world.

        OBSERVED, from the sidebar reading a captured frame of THIS
        record carries -- never declared by the driver, and never
        inferred from a file the engine wrote about an earlier session.
        See UI_PHASE_MENU for what counts as evidence and
        :meth:`_recorded_sidebar_frame` for where it is read back from.
        """
        return self._ui_phase

    @property
    def launch_state(self) -> str:
        """The launcher's verified starting screen, or "" if undeclared.

        Reported rather than merely checked, because the whole point of
        reading it (:meth:`_assert_launch_state`) is that the launcher,
        this module and the operator work from one state instead of
        three.
        """
        return self._launch_state

    @property
    def sidebar_frame(self) -> Optional[int]:
        """The frame whose photographed sidebar put this session in the
        world, or None while the record has not shown one.

        Exposed so `status` can report the evidence the phase rests on
        rather than only the conclusion: a guard whose release condition
        cannot be inspected is a guard nobody can check.
        """
        return self._sidebar_frame

    def _loaded_survivor(self) -> Optional[Tuple[str, str]]:
        """Return the (world, character) the engine says it loaded."""
        return read_lastworld(None, self._root)

    def _pinned_character_is_loaded(self) -> bool:
        """True when lastworld.json names THE survivor this run continues.

        Both halves are checked, because either alone would pass the
        wrong thing: the world, so that loading a different world's
        survivor is caught, and the character, decoded from the save
        filenames the probe found in that world, so that loading a
        SECOND survivor inside the right world is caught as well.
        """
        loaded = self._loaded_survivor()
        if loaded is None:
            return False
        world, character = loaded
        if self._pin.world and world != self._pin.world:
            return False
        names = {decoded_character_name(save)
                 for save in self._fingerprint.get(world, ())}
        names.discard(None)
        return character in names

    def _recorded_sidebar_frame(self) -> Optional[int]:
        """Return the first recorded frame whose capture showed a sidebar.

        THE PHASE HAS TO SURVIVE A PROCESS BOUNDARY, and this is the only
        honest way it can.  `step` sends one keystroke per process, so
        the phase that decides whether a new-survivor hotkey is refused
        has to be recovered from the record between invocations -- and
        the record's own statement about what was PHOTOGRAPHED is the
        telemetry sidecar's reading columns (SIDEBAR_READING_FIELDS),
        which append_observation() copies straight off the payload
        _settle_ui_phase() classifies as each frame arrives.  So the
        release condition read back here and the release condition
        applied live are one condition, expressed once.

        WHY lastworld.json IS NOT CONSULTED.  It is written by the engine
        when a character is loaded or saved, which means a resumed
        session finds it already naming the pinned world and character
        before this session has taken a single frame.  Deriving the phase
        from it released the refusal at frame 1 of every resumed session
        -- exactly where the guard has to hold -- and no reading of that
        file can say what any capture of this session showed.

        The earliest such frame is returned rather than the latest,
        because the transition is one-way: the sidebar is not drawn while
        look mode's examine panel covers the column, nor on the menus a
        relaunch mid-session passes through, and a survivor already in
        the world does not leave it because a panel was opened.

        TOLERANT IN ONE DIRECTION ONLY.  An absent sidecar, a torn or
        unreadable one, a row keyed to a frame this record does not hold
        and a row with no reading are each NO EVIDENCE, which leaves the
        phase at the menu -- the refusing side, where a missing
        photograph costs a refusal an operator can read rather than a
        keystroke that cannot be taken back.  The shortfall itself is not
        swallowed: :meth:`_sidecar_problems` reports a sidecar the record
        needs and does not have, and `status` prints it.

        READ INCREMENTALLY, because one process per keystroke used to
        mean one full parse of the whole sidecar per keystroke -- O(rows)
        each time and O(rows^2) over a session the requirements leave
        deliberately uncapped, measured at 87,571 row parses and 45.63
        MiB across the 419 frames already recorded.
        :func:`refresh_phase_index` answers the same question from a
        validated cache plus the bytes appended since it was written, so
        a step reads the one row it added rather than the whole file.

        THE ANSWER IS UNCHANGED, not merely similar.  The cache holds the
        earliest sidebar frame over the WHOLE sidecar and the limit is
        applied here, which is the same value the full scan produced: a
        global earliest at or below this record's last index IS the
        earliest at or below it, and one above it means no row at or
        below it carried a reading at all.
        """
        try:
            index = refresh_phase_index(self._observations, self._root)
        except RecordError as err:
            _warn_once(
                "phase-sidecar",
                "the telemetry sidecar could not be read (%s), so no "
                "captured frame can be shown to have carried a "
                "sidebar; this session is treated as being on a menu, "
                "where the new-survivor hotkeys of a resumed session "
                "stay refused.  `session.py status` reports what is "
                "wrong with the record" % err)
            return None
        if index.frame is None or index.frame > self._frame:
            return None
        return index.frame

    def _observed_ui_phase(self) -> str:
        """Classify the current screen from photographed evidence only.

        Sets :attr:`_sidebar_frame` to the frame that carried the
        evidence, so the conclusion and the evidence for it are reported
        together.
        """
        self._sidebar_frame = None
        if self._frame < manifest.MIN_FRAME_INDEX:
            return UI_PHASE_MENU
        frame = self._recorded_sidebar_frame()
        if frame is None:
            return UI_PHASE_MENU
        self._sidebar_frame = frame
        LOG.info(
            "frame %d of this record carries a sidebar reading, so the "
            "session is in the world from there", frame)
        return UI_PHASE_IN_WORLD

    def _classify_screen(self, frame: int) -> str:
        """Read the capture for `frame` and say which screen it shows.

        The reading is done with the engine's own font by
        ocr_clock.read_column_by_glyphs(), so a match is a decode of the
        photographed cells rather than a fuzzy OCR guess.  Four answers,
        and the distinction between the last two is what keeps the guard
        honest:

        * SCREEN_NEW_GAME_SUBMENU -- two or more of the submenu's own
          entry strings are on the screen.  The new-character door is
          open.
        * SCREEN_MAIN_MENU -- the main menu's entry row is there and the
          submenu is not.  This is every screen the resumed load route
          passes through.
        * SCREEN_OTHER -- text decoded, and it is neither of those.  A
          real screen that is not on the load route.
        * SCREEN_UNREADABLE -- nothing decoded at all: no capture yet, no
          Pillow or numpy, a frame that is not a rendered game screen.
          NO EVIDENCE, which is a different fact from "a screen that is
          not the main menu", and the caller treats it differently.

        Never raises: a classifier that could stop a session by failing
        to read a file would be a worse hazard than the one it guards
        against, and every failure mode here means the same thing --
        nothing was established.
        """
        path = os.path.join(self._frames,
                            manifest.FRAME_NAME_FORMAT % frame)
        if not os.path.isfile(path):
            return SCREEN_UNREADABLE
        try:
            width, height = ocr_clock.png_size(path)
            row_height = ocr_clock.DEFAULT_ROW_HEIGHT
            try:
                _rect, row_height = ocr_clock.resolve_rect()
            except ocr_clock.OcrClockError as err:
                # The options file is the authority for FONT_HEIGHT; its
                # documented default is the fallback, exactly as
                # ocr_clock's own row probe treats it.
                LOG.debug("row height fell back to %d px: %s",
                          row_height, err)
            band = min(height, MENU_BAND_ROWS * row_height)
            rect = sidebar_geometry.Rect(width, band, 0, height - band)
            text = ocr_clock.read_column_by_glyphs(path, rect, row_height)
        except (ocr_clock.OcrClockError, sidebar_geometry.GeometryError,
                OSError, ValueError) as err:
            LOG.info("frame %d could not be read for its screen: %s",
                     frame, err)
            return SCREEN_UNREADABLE
        if not text.strip():
            return SCREEN_UNREADABLE
        labels = [one for one in MENU_NEW_GAME_SUBMENU_LABELS
                  if one in text]
        if len(labels) >= MENU_SUBMENU_LABELS_REQUIRED:
            LOG.warning(
                "frame %d shows the NEW-GAME submenu: %s",
                frame, ", ".join(repr(one) for one in labels))
            return SCREEN_NEW_GAME_SUBMENU
        markers = [one for one in MENU_ENTRY_ROW_MARKERS if one in text]
        if len(markers) >= MENU_ENTRY_ROW_MARKERS_REQUIRED:
            return SCREEN_MAIN_MENU
        return SCREEN_OTHER

    def _observed_screen(self, frame: int) -> str:
        """Return :meth:`_classify_screen` for `frame`, read once.

        Cached per index because one step asks at most about one frame
        and a session may ask about the same one repeatedly; the record
        is append-only, so a frame's answer cannot change underneath a
        session that is holding the step lock.
        """
        if frame not in self._screens:
            self._screens[frame] = self._classify_screen(frame)
        return self._screens[frame]

    def _assert_route_allowed_by_screen(self, index: int, key: str,
                                        token: str) -> None:
        """Refuse a keystroke the PHOTOGRAPHED screen does not allow.

        The state-based half of "an existing save is continued, never
        replaced", and the half that does not depend on the caller
        describing its own intent truthfully.  It runs only while a
        session that must not create a survivor is at a menu, and only on
        the strength of what the last capture actually shows:

        * the new-game submenu is on screen -- the confirming keys and
          the keys that move deeper into it are refused.  Left/Right walk
          the top row away from [New Game] and Escape closes the submenu,
          so the load route and the way out both stay open.  This half
          does NOT ask what UI phase the record believes it is in: a
          frame carrying two of those five entries is the main menu
          whatever the phase says, and the phase is latched to
          `in-world` from the first sidebar frame onward, so a relaunch
          part-way through a record -- which the committed record itself
          contains -- is a menu the phase cannot see;
        * a screen decoded that is neither the main menu nor that submenu
          -- the confirming keys are refused while the record's phase is
          `menu`, because the resumed route runs through the main menu
          and nothing else, and a session confirming something on an
          unrecognised screen is not on that route.  It is scoped to the
          menu phase deliberately: in the world nearly every screen is
          "not the main menu" and Return is an ordinary command there;
        * the main menu without the submenu -- permitted, which is the
          world list and the character list the load route is made of;
        * nothing decoded at all -- permitted and logged.  No evidence is
          not evidence of a prohibited screen, and refusing here would
          strand the first keystroke of every resumed session, which by
          definition has photographed nothing yet.  What still stands in
          that state is every other refusal: the five hotkeys, the prose
          test, and the save pin.
        """
        if index <= manifest.MIN_FRAME_INDEX:
            # Nothing has been photographed by this record yet.
            return
        frame = index - 1
        screen = self._observed_screen(frame)
        if screen == SCREEN_UNREADABLE:
            LOG.info(
                "frame %d could not be read as a screen, so the route "
                "guard has nothing to hold '%s' against; every other "
                "refusal still applies", frame, key)
            return
        if screen == SCREEN_MAIN_MENU:
            return
        if screen == SCREEN_NEW_GAME_SUBMENU:
            if token not in (MENU_ACTIVATION_KEYS + MENU_DESCENT_KEYS):
                return
            raise CheatGuard(
                "'%s' is REFUSED for frame %d and has NOT been sent.  "
                "The capture for frame %d SHOWS THE NEW-GAME SUBMENU -- "
                "read off its own cells with the game's font, not "
                "inferred from anything this caller said -- and this "
                "session %s, so it may not confirm or move deeper into "
                "an entry that opens a new survivor: %s and %s all do.  "
                "The existing save is continued, never replaced.  Walk "
                "the top row away from [New Game] with Left or Right, "
                "or press Escape to close the submenu, and load %s "
                "through the game's own character list; those keys are "
                "not refused"
                % (key, index, frame, self._route_reason(),
                   MENU_CUSTOM_CHARACTER,
                   ", ".join(MENU_FORBIDDEN_ENTRIES),
                   self._pinned_survivor_phrase()))
        if self._ui_phase != UI_PHASE_MENU:
            return
        if token not in MENU_ACTIVATION_KEYS:
            return
        raise CheatGuard(
            "'%s' is REFUSED for frame %d and has NOT been sent.  The "
            "capture for frame %d does not show the main menu, and this "
            "session %s: the route it may take runs through the main "
            "menu's own [Load] entry, the world list and the character "
            "list, so a key that CONFIRMS whatever is highlighted on an "
            "unrecognised screen is refused before it is delivered.  "
            "Press Escape to come back to the main menu -- that is not "
            "refused -- and load %s from there.  Once a captured frame "
            "shows the sidebar this session is in the world and every "
            "key is available again"
            % (key, index, frame, self._route_reason(),
               self._pinned_survivor_phrase()))

    def _route_reason(self) -> str:
        """Say why this session may not open the character creator."""
        if self._pin.resume:
            return ("is RESUMING world '%s'" % self._pin.world)
        return ("already has the one survivor this run records "
                "(%s)" % self._pinned_survivor_phrase())

    def _pinned_survivor_phrase(self) -> str:
        """Name the survivor(s) the save tree holds, for a refusal."""
        names = sorted(
            name or "an undecodable save name"
            for world in self._fingerprint.values()
            for name in (decoded_character_name(save) for save in world))
        return ", ".join(names) or "the survivor already recorded"

    def _must_not_create_survivor(self) -> bool:
        """True when this session may not open a new-character door.

        Two states, and the second is why this is not simply
        `self._pin.resume`: a create run whose survivor already EXISTS is
        in exactly the same position as a resumed one -- the run records
        one survivor, that survivor is on disk, and a second would be a
        replacement.  The committed record's own mid-session relaunch is
        the case that made this concrete: the phase is latched to
        `in-world` from the first sidebar frame, so a relaunch that
        returns the engine to the menu is not covered by the phase, and
        the screen guard is what covers it.
        """
        if self._pin.resume:
            return True
        return any(self._fingerprint.values())

    def _assert_key_allowed_in_phase(self, index: int, key: str,
                                     action: str = "",
                                     commentary: str = "") -> None:
        """Refuse a new-survivor keystroke BEFORE it is delivered.

        THE PREVENTION THE SAVE-SET CHECK IS NOT.  _assert_save_pin()
        compares the save tree with what it looked like a keystroke ago,
        which detects a second survivor only AFTER the keystroke that
        created one has already been delivered and photographed -- and a
        character, once created, is in the world's save directory whether
        this run records it or not.  So in a resumed session the keys that
        open the creator are refused here, before send_key is reached, for
        as long as the engine is still on a menu.

        The hard rule is that an existing save is CONTINUED rather than
        replaced, and the refusal is what makes that a property of this
        module instead of an instruction in a docstring.

        AND THE HOTKEYS ARE NOT THE ONLY WAY IN.  Refusing five letters
        refuses five doors; it does not refuse the ROUTE.  The verified
        way to Custom Character -- MENU_CUSTOM_CHARACTER_ROUTE -- is
        Left/Right along the top row, Up/Down onto the row, then Return,
        and not one of those keys is in the set above, so a resumed
        session could have walked to the creator with the letter guard
        never firing once.  A security review asked for the launcher and
        this module to be coupled through a VERIFIED route rather than a
        letter list, so the second half of this refusal is keyed on the
        caller's own stated intent: while a resumed session is on a menu,
        a keystroke whose action or commentary says it is opening the
        custom sheet is refused whatever key it is.  The intent test
        alone refuses nothing -- Return confirms everything, and in the
        world it confirms it harmlessly -- which is why the observed
        phase is required with it.
        """
        if not self._pin.resume:
            return
        if self._ui_phase != UI_PHASE_MENU:
            return
        token = key.split(CHORD_SEPARATOR)[-1]
        if token not in MENU_NEW_SURVIVOR_HOTKEYS:
            if (CUSTOM_CHARACTER_MENTION_RE.search(action) or
                    CUSTOM_CHARACTER_MENTION_RE.search(commentary)):
                raise CheatGuard(
                    "'%s' is REFUSED for frame %d and has NOT been "
                    "sent.  It is not one of the five new-survivor "
                    "hotkeys, but it says it is opening %r and this "
                    "session is resuming world '%s' with the engine "
                    "still on a menu -- and the verified route to that "
                    "entry (%s) is built from exactly such keys, so "
                    "refusing only the letters would leave the route "
                    "itself open.  The existing save is continued, "
                    "never replaced: load the character already in "
                    "world '%s'.  Once a captured frame shows the "
                    "sidebar this session is in the world and every "
                    "key is available again"
                    % (key, index, MENU_CUSTOM_CHARACTER,
                       self._pin.world,
                       "; ".join(MENU_CUSTOM_CHARACTER_ROUTE),
                       self._pin.world))
            return
        raise CheatGuard(
            "'%s' is REFUSED for frame %d and has NOT been sent.  This "
            "session is resuming world '%s' and the engine is still on a "
            "menu, and '%s' is one of the five main-menu entries that "
            "open a new survivor -- %s and %s.  The existing save is "
            "continued, never replaced: load world '%s' and the "
            "character already in it (%s).  Once a captured frame shows "
            "the sidebar, this session is in the world and every key is "
            "available again"
            % (key, index, self._pin.world, token,
               MENU_CUSTOM_CHARACTER,
               ", ".join(MENU_FORBIDDEN_ENTRIES), self._pin.world,
               ", ".join(sorted(
                   name or "an undecodable save name"
                   for name in (
                       decoded_character_name(save)
                       for save in self._fingerprint.get(
                           self._pin.world or "", ()))))))

    def _settle_ui_phase(self, index: int,
                         payload: Mapping[str, str]) -> None:
        """Advance the UI phase from what the frame just taken shows.

        Called AFTER the row is committed, on the evidence of the capture
        itself: a sidebar reading means a survivor is in the world.  In a
        resumed session the transition is also the moment the engine's own
        lastworld.json has to name the pinned survivor -- if the sidebar
        has appeared and it does not, something other than the pinned
        character was loaded, and this session records exactly one
        survivor.

        The row this frame's reading went into is what a LATER process
        recovers the phase from (:meth:`_recorded_sidebar_frame`), so the
        transition made here and the transition read back there rest on
        the same capture rather than on two different sources.
        """
        if self._ui_phase == UI_PHASE_IN_WORLD:
            return
        readings = (payload.get("CLOCK"), payload.get("TIME_PHRASE"),
                    payload.get("DATE"))
        sidebar = any((one or "").strip() for one in readings)
        if not sidebar:
            return
        if self._pin.resume and not self._pinned_character_is_loaded():
            loaded = self._loaded_survivor()
            raise CheatGuard(
                "frame %d shows a sidebar, so a survivor is in the "
                "world -- but %s names %s, and this session is resuming "
                "world '%s'.  The existing save is the one that is "
                "continued; a different world or a different character "
                "is not this run's survivor"
                % (index,
                   manifest.relative_to_repo(lastworld_path(self._root)),
                   "no survivor at all" if loaded is None
                   else "'%s' in world '%s'" % (loaded[1], loaded[0]),
                   self._pin.world))
        self._ui_phase = UI_PHASE_IN_WORLD
        self._sidebar_frame = index
        loaded = self._loaded_survivor()
        LOG.info(
            "frame %d shows the sidebar, so the session is in the world "
            "from here%s", index,
            "" if loaded is None
            else " as '%s' of world '%s'" % (loaded[1], loaded[0]))

    def _death_cleanup_for_transition(
            self, before: Mapping[str, Tuple[str, ...]],
            after: Mapping[str, Tuple[str, ...]],
            disappeared: Sequence[str],
            lost: Mapping[str, Tuple[str, ...]],
            appeared: Sequence[str]) -> Optional[DeathCleanupEvidence]:
        """Return evidence for the one legitimate save disappearance.

        The candidate transition itself is deliberately narrow: exactly
        the survivor lastworld.json says was loaded vanished, no other
        world or character vanished, and no new survivor appeared on the
        same key.  Only then are the graveyard, memorial and manifest
        artifacts read.  A candidate with incomplete evidence raises;
        a transition that is plainly something else returns None for the
        ordinary save-pin refusal below.
        """
        if appeared:
            return None
        loaded = self._loaded_survivor()
        if loaded is None:
            return None
        world, character = loaded
        if self._pin.world and world != self._pin.world:
            return None
        save_stem = encoded_character_stem(character)
        if save_stem is None:
            return None
        live_save_name = save_stem + SAVE_EXTENSION
        if live_save_name not in before.get(world, ()):
            return None
        loss_pairs = {
            (name, one)
            for name, characters in lost.items()
            for one in characters
        }
        if loss_pairs != {(world, live_save_name)}:
            return None
        if set(disappeared) - {world}:
            return None
        if live_save_name in after.get(world, ()):
            return None
        evidence = assert_death_cleanup_evidence(
            world=world,
            character=character,
            expected_stem=save_stem,
            manifest_path=self._manifest,
            root=self._root,
        )
        LOG.info(
            "accepted the engine's death cleanup for %s / %s at frame "
            "%d: %s moved to the graveyard and the memorial pair and "
            "captured post-death record agree",
            evidence.world, evidence.character, evidence.death_frame,
            evidence.save_stem)
        return evidence

    def _assert_save_pin(self) -> None:
        """Refuse a step that would create, reset or delete a live save.

        Checked from the save tree itself rather than from what a
        keystroke was believed to mean, which is the only way to check it
        at all -- this module cannot know what any given key does, but it
        can know what the save tree looked like a keystroke ago:

        * a world that has DISAPPEARED means one was deleted or reset;
        * a character that has disappeared means one was deleted;
        * in RESUME mode a NEW character means a second survivor was
          created, which this run does not record;
        * in CREATE mode the one survivor may appear (0 -> 1) and no
          more, and only in one world.

        The exception is engine-authored DEATH cleanup.  CDDA moves the
        character files to graveyard/, writes the memorials and may reset
        the world; that transition is accepted only when those artifacts
        and the captured post-death rows all match the loaded survivor.
        A bare deletion still stops the session.
        """
        before = self._fingerprint
        after = self._save_fingerprint()
        disappeared = sorted(
            name for name in before if name not in after)
        lost = {
            name: tuple(sorted(
                set(characters) - set(after.get(name, ()))))
            for name, characters in before.items()
        }
        lost = {
            name: characters
            for name, characters in lost.items() if characters
        }
        appeared = sorted(
            "%s/%s" % (name, one)
            for name, characters in after.items()
            for one in sorted(set(characters) - set(
                before.get(name, ())))
        )
        if disappeared or lost:
            evidence = self._death_cleanup_for_transition(
                before, after, disappeared, lost, appeared)
            if evidence is not None:
                self._fingerprint = after
                return
            if disappeared:
                name = disappeared[0]
                raise CheatGuard(
                    "world '%s' is no longer under %s.  A world is not "
                    "deleted or reset during a recorded session unless "
                    "the engine's graveyard, memorial and captured "
                    "post-death record all evidence the pinned "
                    "survivor's death cleanup"
                    % (name, self._pin.save_dir))
            name = sorted(lost)[0]
            raise CheatGuard(
                "character save(s) %s vanished from world '%s'.  A "
                "survivor is not manually deleted during a recorded "
                "session; only fully evidenced engine death cleanup is "
                "accepted"
                % (", ".join(lost[name]), name))
        if not appeared:
            self._fingerprint = after
            return
        if self._pin.resume:
            raise CheatGuard(
                "character save(s) %s appeared while resuming world "
                "'%s'.  This run records exactly one survivor and it is "
                "the one that already existed; a second character is "
                "not created"
                % (", ".join(appeared), self._pin.world))
        total = sum(len(one) for one in after.values())
        if total > 1:
            raise CheatGuard(
                "%d character saves now exist under %s (%s appeared).  "
                "This run records exactly one survivor"
                % (total, self._pin.save_dir, ", ".join(appeared)))
        LOG.info("the survivor's save appeared: %s", ", ".join(appeared))
        self._fingerprint = after

    # -- the capture ------------------------------------------------

    def _prepare_window_for(self, index: int, key: str,
                            recovery: bool = False) -> int:
        """Find, authenticate and focus the engine.  Returns its id.

        SHARED BY THE ORDINARY STEP AND BY RECOVERY, which is the point:
        recovery used to photograph the root window without doing any of
        this, on the strength of a window id recorded by a process that
        had since died.  A screen is only evidence of what a keystroke
        did if the engine that received the keystroke is the thing on it,
        so the same three checks run either way -- the window is found by
        class, the process behind it is checked against this checkout's
        binary and userdir, and it is focused.

        :raises WindowError: naming what was NOT sent, in the ordinary
            case, so a caller knows the step can simply be retried; the
            recovery case says the frame was not photographed.
        """
        try:
            window = self.refresh_window()
            focus_window(window, self._tool_timeout)
            return window
        except SessionError as err:
            if recovery:
                raise WindowError(
                    "the keystroke '%s' for frame %d had been delivered, "
                    "but the engine window could not be re-found, "
                    "re-authenticated and focused, so NO frame was "
                    "photographed for it: %s.  The journal is left in "
                    "place, so the frame is captured at this same index "
                    "once the engine is reachable again -- what is "
                    "refused is photographing whatever else happens to "
                    "be on that display and filing it as this "
                    "keystroke's frame"
                    % (key, index, err)) from err
            raise WindowError(
                "the game window could not be prepared for frame %d, so "
                "'%s' was NOT sent: %s"
                % (index, key, err)) from err

    def _previous_capture_bytes(self, index: int) -> Optional[int]:
        """Return the size of the capture before this one, or None.

        ONE stat OF ONE FILE.  The directory is never listed: a listing
        here would be O(captures) on every keystroke, which is the shape
        of per-key cost this module already carries too much of, and the
        only frame this needs is the one whose name it can derive.
        """
        if index <= 1:
            return None
        path = os.path.join(self._frames, manifest.frame_file(index - 1))
        try:
            return int(os.stat(path).st_size)
        except OSError:
            return None

    def _assert_capture_room(self, index: int) -> None:
        """Refuse the step when there is not room to record it.

        BEFORE THE KEY IS SENT, and on EVERY key rather than
        periodically, because the whole check is two syscalls: one stat
        of the previous capture and one statvfs of the filesystem it
        lives on.  There is nothing here proportional to the length of
        the session.

        A disk that fills between the keystroke and the capture is the
        one failure mode that cannot be repaired afterwards -- the key
        has been acted on, the frame is truncated or absent, and a
        keystroke without its frame breaks the identity the record rests
        on.  So this is a refusal that leaves the session exactly where
        it was: free space and press the same key again.

        A MEASUREMENT THAT CANNOT BE TAKEN IS A REFUSAL, NOT A WARNING.
        This used to warn once and send the key anyway, on the reasoning
        that an unreadable statvfs is a fact about the host rather than
        evidence that the disk is full.  A review rejected that
        reasoning and it was right to: the key is IRREVERSIBLE -- it
        changes the game's state, and no later stage can un-press it --
        while the check exists precisely because a delivered key whose
        frame cannot be written breaks the identity the whole record
        rests on.  Sending it on an unproved assumption trades a
        recoverable refusal for an unrecoverable gap, which is the wrong
        direction for the one control standing between the two.  So room
        must be PROVED before delivery; if it cannot be measured, the
        step refuses and the session is exactly where it was.
        """
        where = manifest.relative_to_repo(self._frames)
        previous = self._previous_capture_bytes(index)
        reserve = capture_reserve(previous)
        try:
            available = free_bytes(self._frames)
        except OSError as err:
            raise CapacityError(
                "the free space where %s lives could not be read (%s), "
                "so there is NO PROOF that frame %d can be written -- "
                "and this check runs before the key is sent precisely "
                "because a delivered key whose frame cannot be written "
                "is the one failure no later stage can repair.  THE KEY "
                "HAS NOT BEEN SENT.  Fix the host so the filesystem "
                "under %s can be measured (statvfs is what fails here), "
                "then press the same key again.  There is no value of "
                "$%s that turns this into a warning: an unmeasurable "
                "disk is refused rather than assumed to be empty"
                % (where, err, index, where,
                   ENV_CAPTURE_RESERVE)) from err
        if available >= reserve:
            return
        raise CapacityError(
            "there is not room to record frame %d: %d byte(s) free "
            "where %s lives, against a reserve of %d and therefore "
            "%d byte(s) short.  The reserve is %d keystroke(s) of "
            "headroom over %s, plus %d for the sidecars, the journal "
            "and the save the engine rewrites.  THE KEY HAS NOT BEEN "
            "SENT, so nothing is lost: free space and press it again.  "
            "Refusing here is deliberate -- a disk that fills between "
            "the keystroke and the photograph leaves a delivered key "
            "with no frame, and no later stage can repair that.  Set "
            "$%s to name a different reserve if this host's figures "
            "are unusual; there is no value that switches the check off"
            % (index, available, where, reserve, reserve - available,
               CAPTURE_RESERVE_LOOKAHEAD,
               ("the previous capture's %d byte(s)" % previous
                if isinstance(previous, int)
                else "a %d-byte floor" % CAPTURE_RESERVE_PER_FRAME_FLOOR),
               CAPTURE_RESERVE_FLOOR, ENV_CAPTURE_RESERVE))

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

    def _journal_record(self, index: int, key: str, action: str,
                        commentary: str, phase: str,
                        attempts: int,
                        payload: Optional[Mapping[str, str]] = None,
                        ) -> Dict[str, object]:
        """Build the journal record for the step in flight."""
        record: Dict[str, object] = {
            "version": JOURNAL_VERSION,
            "phase": phase,
            "frame": index,
            "key": key,
            "action": action,
            "commentary": commentary,
            "capture_attempts": int(attempts),
            "manifest": manifest.relative_to_repo(self._manifest),
            "frames_dir": manifest.relative_to_repo(self._frames),
            "display": resolve_display(),
            "opened_at": manifest.utc_timestamp(),
        }
        if payload is not None:
            record["payload"] = {
                str(name): str(value)
                for name, value in payload.items()}
        return record

    def _resolve_map_geometry(self, payload: Mapping[str, str],
                              ) -> Optional[str]:
        """Return the map column's crop, resolving it once per session.

        The sidebar's own rectangle comes from configuration through
        ocr_clock.resolve_rect(), which is the same runtime computation
        the clock read uses, and the frame's extent comes from the
        capture's own FRAME_GEOMETRY rather than from a constant -- so a
        different sidebar preset or a different display moves this crop
        with it instead of silently comparing the wrong pixels.

        None means the column could not be resolved, and
        :func:`classify_effect` then reports EFFECT_CHANGED for any
        frame that moved rather than a finer verdict it did not measure.
        """
        if self._map_geometry_resolved:
            return self._map_geometry
        self._map_geometry_resolved = True
        geometry = payload.get("FRAME_GEOMETRY", "").strip()
        matched = re.match(r"\A(\d+)x(\d+)\Z", geometry)
        if not matched:
            _warn_once(
                "map-geometry",
                "capture.sh reported FRAME_GEOMETRY=%r, which is not "
                "WxH, so the map column cannot be told apart from the "
                "sidebar beside it; a keystroke that moved only a "
                "panel or a counter will be recorded as having changed "
                "the screen" % geometry)
            return None
        width, height = int(matched.group(1)), int(matched.group(2))
        try:
            rect, _row_height = ocr_clock.resolve_rect()
        except Exception as err:  # ocr_clock raises its own family
            _warn_once(
                "map-geometry",
                "the sidebar rectangle could not be computed (%s), so "
                "the map column cannot be told apart from the sidebar "
                "beside it" % err)
            return None
        self._map_geometry = map_column_geometry(rect, width, height)
        if self._map_geometry is None:
            _warn_once(
                "map-geometry",
                "the sidebar crop %s cannot be reconciled with a %dx%d "
                "capture, so the map column is not compared separately"
                % (rect, width, height))
        return self._map_geometry

    def _observe_effect(self, index: int,
                        payload: Mapping[str, str]) -> ObservedEffect:
        """Compare this capture with the one before it.  Never raises.

        The observation half of the row, and the reason a swallowed
        keystroke can no longer be written up as though it had landed.
        The predecessor is the capture at `index - 1`; when there is
        none -- the first frame of the very first session -- the verdict
        is EFFECT_FIRST, and when the file is missing it is
        EFFECT_UNKNOWN with a warning, because a resumed session whose
        earlier frames were never captured has nothing to compare.
        """
        if index <= 1:
            return ObservedEffect(EFFECT_FIRST)
        previous = os.path.join(
            self._frames, manifest.FRAME_NAME_FORMAT % (index - 1))
        current = os.path.join(
            self._frames, manifest.FRAME_NAME_FORMAT % index)
        if not os.path.isfile(previous):
            _warn("frame %d's predecessor is not at %s, so this row "
                  "records no observation of what the keystroke did"
                  % (index, previous))
            return ObservedEffect(EFFECT_UNKNOWN)
        if not os.path.isfile(current):
            _warn("frame %d is not at %s, so this row records no "
                  "observation of what the keystroke did"
                  % (index, current))
            return ObservedEffect(EFFECT_UNKNOWN)
        return classify_effect(
            previous, current,
            map_geometry=self._resolve_map_geometry(payload),
            timeout=self._tool_timeout)

    def _report_effect(self, index: int, effect: ObservedEffect,
                       action: str, commentary: str) -> None:
        """Warn about a verdict the row's own prose may contradict.

        Advisory by construction: the marker is already in the action
        text by the time this runs, and this only makes sure the
        operator READS it before choosing the next keystroke.  A claim
        of movement the measurement does not support is said twice, and
        more loudly, because that is the exact defect this guard was
        added for.
        """
        claims_movement = (movement_claim(action) or
                           movement_claim(commentary))
        marker = EFFECT_MARKERS.get(effect.verdict)
        if marker is not None:
            _warn("frame %d: %s.  The row now says so and its note is "
                  "unchanged; read the capture before writing the next "
                  "row" % (index, marker))
            if claims_movement:
                _warn("frame %d claims the survivor moved (%r) but %s.  "
                      "A row is the authoritative account of what ONE "
                      "keystroke did: say what the capture shows, not "
                      "what the key was aimed at"
                      % (index, action, marker))
            return
        pixels = effect.map_pixels
        if (claims_movement and pixels is not None and
                0 < pixels < MOVEMENT_ADVISORY_PIXELS):
            _warn("frame %d claims the survivor moved (%r), and the map "
                  "column did change -- but by only %d px, inside %s.  "
                  "A step in this record moves tens of thousands; a "
                  "panel drawn over the map moves this many.  Read the "
                  "capture and make sure the row describes the panel "
                  "rather than a step that did not happen"
                  % (index, action, pixels, effect.map_box or "no box"))

    @property
    def acknowledgments_path(self) -> str:
        """Where this session records its readings of the captures."""
        return self._acks

    @property
    def modals(self) -> Tuple[str, ...]:
        """The query boxes read off the most recent capture."""
        return self._modals

    def _frame_digest_of(self, index: int) -> str:
        """Return the attested sha256 of a captured frame, or ''.

        Read from the capture attestation ledger rather than recomputed,
        so an acknowledgment is bound to the same digest the capture was
        published under.  A frame with no attestation answers '' and the
        acknowledgment records that absence honestly instead of a digest
        taken from bytes nobody attested.
        """
        attested = self._attested_digest(index)
        if not isinstance(attested, dict):
            return ""
        # The ledger's own column name, which is `sha256` rather than
        # `frame_sha256`: manifest.DIGEST_FIELDS owns that schema and
        # this reads it as written instead of restating it.
        digest = attested.get("sha256")
        return digest if isinstance(digest, str) else ""

    def acknowledge(self, frame: int, observed: str,
                    expectation: Optional[str] = None
                    ) -> Dict[str, object]:
        """Record that a capture was read, and what it showed.

        The one way past a :class:`GuardHalt`, and the way every step
        after the first satisfies its precondition.  The capture must
        EXIST -- an acknowledgment of a frame that was never taken would
        be a reading of nothing -- and the reading itself must say
        something (:func:`validate_observed`).

        The frame's own observed verdict and any query box detected on it
        are recorded beside the reading, so the ledger shows what the
        machine measured next to what the operator said, and a
        disagreement between them is visible afterwards.

        :raises RecordError: when the capture does not exist.
        :raises ObservationRequired: when there is no usable reading.
        """
        index = validated_frame(frame)
        path = os.path.join(self._frames,
                            manifest.FRAME_NAME_FORMAT % index)
        if not os.path.isfile(path):
            raise RecordError(
                "there is no capture at %s, so there is nothing to "
                "acknowledge for frame %d.  An acknowledgment is a "
                "reading of a photograph, not a statement about one "
                "that was never taken"
                % (manifest.relative_to_repo(path), index))
        recorded = self._observation_verdict(index)
        row = acknowledgment_row(
            index, observed, recorded,
            modals=detect_modals(read_modal_text(path)),
            digest=self._frame_digest_of(index),
            expectation=expectation)
        appended = append_acknowledgment(
            self._acks, row, require_durable=self._require_durable,
            root=self._root)
        LOG.info("frame %d acknowledged: %s", index, row["observed"])
        return appended

    def _observation_halted(self, index: int) -> bool:
        """True when the sidecar records that this frame halted a step.

        Read back from the ledger rather than recomputed, so the answer
        is the one the halting step itself wrote: a later re-measurement
        could differ, and the question here is historical.
        """
        try:
            for row in read_observations(self._observations,
                                         root=self._root):
                if row.get("frame") == index:
                    return bool(row.get("halted"))
        except (RecordError, manifest.ManifestError, OSError,
                ValueError) as err:
            LOG.info("frame %d's halt state could not be read: %s",
                     index, err)
        return False

    def _observation_verdict(self, index: int) -> str:
        """Return the effect verdict the sidecar recorded for a frame.

        Read back rather than re-measured: the verdict in the ledger is
        the one the step wrote at capture time, and re-comparing the
        images here could answer differently if anything had touched
        them since -- which is precisely the sort of drift a ledger
        exists to make impossible.
        """
        try:
            for row in read_observations(self._observations,
                                         root=self._root):
                if row.get("frame") == index:
                    return verdict_of(row.get("effect"))
        except (RecordError, manifest.ManifestError, OSError,
                ValueError) as err:
            LOG.info("frame %d's recorded verdict could not be read: %s",
                     index, err)
        return EFFECT_UNKNOWN

    def _assert_previous_acknowledged(
            self, index: int, observed: Optional[str],
            expectation: Optional[str]) -> None:
        """Refuse the next key until the last capture has been read.

        BEFORE ANYTHING IS SENT, so a missing reading costs nothing but
        the call: supply it and press again.  This is the structural form
        of "observe -> decide in character -> act", and it is here rather
        than in a driver because a rule a driver can forget is a rule
        that was measurably forgotten -- frames 91-106 of the retired
        session were keyed into a modal nobody had looked at.

        The FIRST step of a session has no predecessor and needs no
        reading.  Every other step either carries one (`observed`) or
        finds one already in the ledger for that exact frame, and a
        reading recorded against a DIFFERENT digest for the same index
        does not count: that would be a reading of a capture that is no
        longer the one on disk.
        """
        previous = index - 1
        if previous < 1:
            return
        path = os.path.join(self._frames,
                            manifest.FRAME_NAME_FORMAT % previous)
        if not os.path.isfile(path):
            # Nothing to read.  A resumed session whose earlier frames
            # are not in this tree is already reported by the record
            # verification; this guard does not add a second refusal for
            # the same condition.
            return
        digest = self._frame_digest_of(previous)
        known = acknowledged_frames(self._acks, self._root)
        recorded = known.get(previous)
        if recorded is not None and (not digest or recorded == digest):
            return
        # A FRAME THAT HALTED THE SESSION NEEDS ITS OWN ACT.  For an
        # ordinary frame the reading may travel with the next key --
        # one call, and the reading is still recorded before anything is
        # sent.  For a frame the guard stopped on, the two must be
        # separate calls: combining "I have looked at the anomaly" with
        # "and here is the next key" in a single invocation is exactly
        # the shape of not having looked.
        if self._observation_halted(previous):
            raise ObservationRequired(
                "frame %d STOPPED the session -- its telemetry row "
                "records the halt -- and it has not been acknowledged "
                "since, so frame %d's keystroke is REFUSED and nothing "
                "was sent.  Read %s and record what it shows with "
                "`session.py ack --frame %d --observed '...'`, as a "
                "call of its own.  The reading may not travel with the "
                "next key here: an anomaly acknowledged in the same "
                "breath as the key that follows it has not been looked "
                "at" % (previous, index,
                        manifest.relative_to_repo(path), previous))
        if observed is None:
            raise ObservationRequired(
                "frame %d has not been read, so frame %d's keystroke is "
                "REFUSED and nothing was sent.  Look at %s -- which "
                "screen is up, what is selected, is a query box open -- "
                "then either pass --observed with what you saw or record "
                "it with `session.py ack --frame %d --observed '...'`.  "
                "This is the hard rule 'never blind-spam keys' as a "
                "precondition rather than as advice: the retired "
                "session's frames 91-106 were keyed into an unchanged "
                "modal exactly because nothing enforced it"
                % (previous, index, manifest.relative_to_repo(path),
                   previous))
        self.acknowledge(previous, observed, expectation)

    def _frame_reference(self, index: int) -> str:
        """The repository-relative path of a captured frame."""
        return manifest.relative_to_repo(
            os.path.join(self._frames,
                         manifest.FRAME_NAME_FORMAT % index))

    def _effect_halt(self, index: int, expect: str,
                     effect: object) -> Optional[str]:
        """Why this capture contradicts its declaration, or None.

        EFFECT_UNKNOWN contradicts EVERY declaration.  An unmeasurable
        pair is the absence of an observation, and the whole purpose of
        this guard is that an absent observation must not read like a
        satisfied one.
        """
        verdict = verdict_of(effect)
        if verdict in EXPECT_ACCEPTS.get(expect, ()):
            return None
        if verdict == EFFECT_UNKNOWN:
            detail = ("the two captures could not be compared, so what "
                      "the keystroke did was not observed at all")
        else:
            detail = "the capture is %r" % verdict
        return (
            "frame %d declared --expect %s and %s.  THE KEY WAS "
            "DELIVERED AND THE FRAME AND ROW ARE RECORDED; what stops "
            "here is the next keystroke.  Read %s: if the screen "
            "legitimately did not move, record that with `session.py "
            "ack --frame %d --observed '...'` and continue; if the key "
            "was swallowed by a box or a case-sensitive prompt, deal "
            "with that box before sending anything else.  A session "
            "that keys on past this is the defect this guard exists for"
            % (index, expect, detail, self._frame_reference(index),
               index))

    def _modal_halt(self, index: int, expect_modal: Optional[str],
                    modals: Sequence[str]) -> Optional[str]:
        """Why this capture's query box is wrong, or None.

        BOTH DIRECTIONS MATTER.  An UNDECLARED box means the operator's
        model of the screen is wrong and the next key would go into the
        box instead of the screen behind it -- the exact shape of the
        retired session's worst passage.  A DECLARED box that is absent
        means the model is wrong the other way, and a session that
        proceeds on it is answering a prompt nobody is asking.
        """
        present = tuple(modals)
        if expect_modal is None:
            if not present:
                return None
            return (
                "frame %d shows a query box nothing declared: %s.  THE "
                "KEY WAS DELIVERED AND THE FRAME AND ROW ARE RECORDED; "
                "what stops here is the next keystroke, because every "
                "one of these boxes EATS a key aimed at the screen "
                "behind it -- %s.  Read %s, acknowledge this frame with "
                "`session.py ack --frame %d --observed '...'`, and "
                "answer the box deliberately with --expect-modal %s on "
                "the next step"
                % (index, ", ".join(present),
                   modal_reason(present[0]) or "engine query_yn",
                   self._frame_reference(index), index, present[0]))
        if expect_modal in present:
            return None
        return (
            "frame %d declared the query box %r and the capture does "
            "not show it%s.  THE KEY WAS DELIVERED AND THE FRAME AND "
            "ROW ARE RECORDED; what stops here is the next keystroke, "
            "because a step about to answer a prompt that is not being "
            "asked will send its answer somewhere else"
            % (index, expect_modal,
               (" -- what it shows is %s" % ", ".join(present))
               if present else ""))

    def _halt_reason(self, index: int, expect: str, effect: object,
                     expect_modal: Optional[str],
                     modals: Sequence[str]) -> Optional[str]:
        """The first reason this capture stops the session, or None.

        The modal reading is consulted first because when both would
        fire they are usually the same event seen from two sides -- a
        swallowed key and an open box -- and the box is the more
        actionable half.
        """
        return (self._modal_halt(index, expect_modal, modals) or
                self._effect_halt(index, expect, effect))

    def _commit(self, index: int, key: str, action: str,
                commentary: str, payload: Mapping[str, str],
                attempts: int, recovered: bool,
                expect: str = EXPECT_EITHER,
                declared_modal: Optional[str] = None
                ) -> Dict[str, object]:
        """Append the row and its attestation, then clear the journal.

        The tail of the transaction, shared by an ordinary step and by
        recovery so the two cannot record a frame differently.  The
        manifest row goes first because it is THE record; the counter
        advances only once that row is on the device; the sidecar
        attestation -- which carries the immutable key -- follows; and the
        journal is cleared last, so an interruption anywhere in here
        leaves a state the next open can finish rather than one it has to
        interpret.

        THE OBSERVED-EFFECT GUARD RUNS HERE, before the row is written
        and in the one place both an ordinary step and a recovered one
        pass through, so a recovered frame carries the same observation
        an ordinary one would.
        """
        self._lock.assert_held()
        clock = clock_from_payload(payload)
        effect = self._observe_effect(index, payload)
        action = annotate_action(action, effect.verdict)
        self._report_effect(index, effect, action, commentary)
        try:
            row = manifest.append_row(
                self._manifest,
                index,
                manifest.frame_file(index),
                payload["REAL_TS"],
                clock,
                action,
                commentary,
                require_durable=self._require_durable,
                root=self._root,
            )
        except manifest.ManifestError as err:
            self._abort(
                "frame %d was captured but its row could not be "
                "appended to %s: %s.  The journal at %s still records "
                "the step, so the next session completes it rather than "
                "leaving the capture unaccounted for"
                % (index, self._manifest, err, self._journal))
            raise RecordError(self._aborted) from err

        # THE COUNTER ADVANCES HERE, and only once the row is on the
        # device.  The manifest is the authority for what was captured,
        # so a row that is stored is a frame that happened.
        self._frame = index

        observation = observation_row(
            index, payload, key=key, action=action,
            capture_attempts=attempts, recovered=recovered,
            effect=effect)
        # THE DECLARATION AND THE QUERY-BOX READING, recorded beside the
        # measurement they will be judged against.  They are computed
        # HERE rather than after the row so that the sidecar carries
        # them: a halt that left no trace in the record would be a
        # control whose firing could not be audited afterwards, and the
        # anomaly is also what the NEXT step reads to decide whether an
        # inline reading is enough or an explicit acknowledgment is
        # required.
        modals = detect_modals(read_modal_text(
            os.path.join(self._frames,
                         manifest.FRAME_NAME_FORMAT % index)))
        self._modals = tuple(modals)
        observation["expected"] = expect
        observation["expect_modal"] = declared_modal or ""
        observation["modals"] = list(modals)
        observation["halted"] = bool(
            self._halt_reason(index, expect, effect, declared_modal,
                              modals))
        try:
            append_observation(
                self._observations, observation,
                require_durable=self._require_durable,
                root=self._root)
        except SessionError as err:
            # The frame and its row are intact and the counter has
            # advanced, so the record is sound -- but this frame's
            # attestation and its sidebar DATE line are now missing, and
            # timeline.py needs the date to tell a crossing of midnight
            # from a clock that read backwards.  That is real evidence
            # lost, so it stops the session loudly instead of degrading
            # in silence.
            self._abort(
                "frame %d is captured and recorded, but its telemetry "
                "row could not be appended to %s: %s"
                % (index, self._observations, err))
            raise
        self._attest_capture(index, payload, recovered)
        clear_journal(self._journal)
        self._row = dict(row)
        self._observation = dict(observation)
        self._effect = effect
        self._verdict = effect.verdict
        return row

    def _attest_capture(self, index: int, payload: Mapping[str, str],
                        recovered: bool) -> Dict[str, object]:
        """Append this frame's capture digest to the ledger.

        THE THIRD APPEND OF THE TRANSACTION, and the one that makes the
        other two provable.  capture.sh hashes the PNG the instant it is
        published and reports FRAME_SHA256; assert_payload_matches() has
        already re-hashed the file and refused a mismatch; this records
        the digest where every later stage looks for it -- the timing,
        the transitions, the render and the commit each verify a frame's
        bytes against this ledger before using them.

        The attestation says HOW it was established: `capture` for an
        ordinary step, `recovery` for a frame whose payload was rebuilt
        by measuring an already-captured file.  A weaker claim recorded
        as the strong one would be worse than no claim at all.

        A failure here stops the session, for the same reason a missing
        telemetry row does: the frame and its row are on the device, and
        an unattested frame is exactly the state this ledger exists to
        prevent.
        """
        digest = str(payload.get("FRAME_SHA256", "")).strip()
        path = os.path.join(self._frames,
                            manifest.FRAME_NAME_FORMAT % index)
        try:
            size = os.path.getsize(path)
        except OSError as err:
            self._abort(
                "frame %d is captured and recorded, and then could not "
                "be measured for its attestation: %s" % (index, err))
            raise RecordError(self._aborted) from err
        try:
            return manifest.append_frame_digest(
                self._digests, index, manifest.frame_file(index),
                digest, size,
                (manifest.DIGEST_AT_RECOVERY if recovered
                 else manifest.DIGEST_AT_CAPTURE),
                manifest.utc_timestamp(),
                require_durable=self._require_durable,
                root=self._root)
        except manifest.ManifestError as err:
            self._abort(
                "frame %d is captured and recorded, but its capture "
                "digest could not be appended to %s: %s.  An "
                "unattested frame is the state that ledger exists to "
                "prevent, so the session stops here rather than "
                "carrying on with one"
                % (index, self._digests, err))
            raise RecordError(self._aborted) from err

    def step(self, key: str, action: Optional[str] = None,
             commentary: Optional[str] = None,
             note: Optional[str] = None,
             expect: str = EXPECT_CHANGED,
             observed: Optional[str] = None,
             expect_modal: Optional[str] = None) -> StepResult:
        """Send ONE keystroke and record ONE frame.  The whole step.

        THIS IS THE ONLY PLACE THE FRAME COUNTER MOVES, and it moves
        once per call, under the step lock, with the intent to send made
        durable BEFORE the key leaves.  In order:

          1. validate the key against the closed vocabulary, which
             refuses every chord that could reach a debug action or end
             the engine outside the game's own Save & Quit;
          2. derive this row's `action` from that validated key, so the
             record cannot name a key other than the one sent;
          3. prove no debug action is bound, that the save tree still
             matches the pinned create-versus-resume decision, and that
             there is room on the disk to record this frame;
          4. authenticate the game window against the process behind it;
          5. write the pre-send journal and force it to the device;
          6. send EXACTLY ONE keystroke;
          7. let capture.sh settle, photograph the root window and read
             the sidebar clock -- one frame, at this step's index;
          8. record the capture's payload in the journal, durably;
          9. append EXACTLY ONE manifest row, advance the counter,
             append the attestation, and clear the journal.

        Steps 5 and 8 are what make this recoverable.  A failure at any
        point after 6 leaves a journal entry the next session finishes at
        the SAME index -- so a keystroke can no longer end up delivered
        with no frame and no row, which is the one failure the first
        recorded session could not repair.

        One key per call, always.  There is no argument that takes
        several, and adding one would destroy the one-frame-per-key
        relation in a way nothing downstream could repair.

        :param key: one keystroke, as a keysym name or a single
            printable character; validated against a closed vocabulary.
        :param action: the full row text.  Optional, and CHECKED rather
            than trusted: it must be :func:`describe_key`'s output for
            this key, optionally followed by " -- " and the reason.  Pass
            `note` instead and let this derive it.
        :param commentary: the survivor's own first-person reason, in
            the voice playthrough/dossier.md establishes.  Engineering
            and meta observations belong in
            playthrough/TECHNICAL_NOTES.md, never here.
        :param note: the reason half of `action`, appended to the
            derived identity.  Mutually exclusive with `action`.
        :param expect: what this capture will show -- EXPECT_CHANGED
            (the default), EXPECT_UNCHANGED for a key that legitimately
            moves nothing on screen, or EXPECT_EITHER when the screen's
            response genuinely cannot be predicted.  A capture that
            contradicts the declaration halts the session AFTER
            recording the frame and its row.
        :param observed: the operator's own reading of the PREVIOUS
            capture.  Required for every step after the first unless
            that frame is already in the acknowledgment ledger, and
            recorded there -- durably -- before this key is delivered.
        :param expect_modal: the token of an engine query box this step
            is deliberately answering (see :data:`MODAL_PROMPTS`).  An
            undeclared box on the capture halts the session, and so does
            a declared one that is not there.
        :returns: a :class:`StepResult` carrying the frame path and the
            clock reading, so the caller reads what happened before
            choosing the next keystroke.
        The failures divide at the keystroke, because that is the one
        event in the step that cannot be taken back.

        BEFORE ANYTHING IS SENT -- the session stays usable and the step
        can simply be retried once the condition is fixed:

        :raises KeyRejected: for a value that is not one keystroke, or
            one this module refuses to send.
        :raises CheatGuard: when a debug action is bound or the save
            tree moved.
        :raises CapacityError: when there is not room to record this
            frame.  Nothing was sent, so the step is retried once space
            has been freed.
        :raises WindowError: when the window could not be resolved,
            authenticated or focused.  Nothing was sent and nothing was
            journalled.

        AFTER THE KEY HAS BEEN DELIVERED -- the session is CLOSED,
        because continuing would record later frames against a game
        state this module can no longer account for.  The journal is on
        the device, so the step itself is recoverable:

        :raises WindowError: when sending the key itself failed.  This
            one is indistinguishable from a delivered key by
            construction -- xdotool's failure says nothing about
            whether the X server acted -- so it is treated as
            delivered.
        :raises CaptureError: when the frame was not captured after the
            key was pressed.
        :raises RecordError: when the row could not be appended.
        """
        self._assert_usable()
        validated = validate_key(key)
        if expect not in EXPECTATIONS:
            raise RecordError(
                "%r is not a declaration this module knows.  Every step "
                "says what its capture will show, and the choices are: "
                "%s" % (expect, ", ".join(EXPECTATIONS)))
        declared_modal = (None if expect_modal is None
                          else validate_modal_token(expect_modal))
        if action is not None and note is not None:
            raise RecordError(
                "pass either the full action or the note it ends with, "
                "not both: the identity half is derived from the key")
        text = (build_action(validated, note) if action is None
                else assert_action_derived(validated, action))
        voice = _required_text(commentary, "commentary")
        # THE TWO HONESTY GATES, both BEFORE anything irreversible and
        # both refusals rather than advisories.  A sentence that is not
        # the survivor's voice, or that states a time or a date the
        # frames do not support, never becomes a row -- because a row is
        # evidence and evidence is not corrected afterwards.
        self._assert_voice(voice)
        self._assert_clock_honesty(voice)
        self._assert_menu_hotkey_permitted(validated, text, voice)

        # THE INTEGRITY PRE-FLIGHTS, on every step and before anything
        # irreversible.  All three are cheap, all three read committed
        # artifacts, and all three would be worthless if a driver could
        # skip them.
        self.audit_bindings()
        self._assert_save_pin()

        # The index this step owns.  ONE increment, ONE statement, and
        # the only one in this module: everything below -- the capture
        # filename, the payload check, the manifest row's `file` field
        # and the sidecar key -- is derived from this single value.
        self._lock.assert_held()
        index = validated_frame(self._frame + 1)
        attempts = 1

        # THE ROOM TO RECORD THIS STEP, still before anything is sent: a
        # disk that fills between the keystroke and the photograph
        # leaves a delivered key with no frame, which is the one failure
        # nothing downstream can repair.  Two syscalls, so it is taken
        # on every key rather than occasionally, and it takes the index
        # this step already owns rather than deriving it again.
        self._assert_capture_room(index)

        # AND THE PICTURE BEFORE THIS ONE MUST HAVE BEEN READ.  Also
        # before delivery, because a missing reading is a condition to
        # fix rather than damage to recover from: the reading is recorded
        # durably here, and only then is a key sent on the strength of
        # it.  This is the hard rule "never blind-spam keys" made
        # structural.
        self._assert_previous_acknowledged(index, observed, expect)

        # THE MODE-AWARE REFUSAL, before the window is even prepared: a
        # resumed session may not press a key that opens the character
        # creator while the engine is still on a menu -- neither one of
        # the five hotkeys nor a key of the verified route said to be
        # walking it.
        self._assert_key_allowed_in_phase(index, validated, text, voice)

        # AND THE SAME REFUSAL TAKEN OFF THE PHOTOGRAPH RATHER THAN OFF
        # THE CALLER'S WORDS, which is what makes it enforcement instead
        # of cooperation: the line above can be walked past with wording
        # that says nothing about the custom sheet, so the screen the
        # last capture SHOWS decides as well.  Also before delivery, and
        # it can only refuse.
        if self._must_not_create_survivor():
            self._assert_route_allowed_by_screen(
                index, validated,
                validated.split(CHORD_SEPARATOR)[-1])

        # Nothing has been sent and nothing has been journalled yet, so a
        # window that cannot be found or focused leaves the session
        # usable: it is a condition to fix and retry.
        window = self._prepare_window_for(index, validated)

        # THE PRE-SEND JOURNAL, phase `sending`.  Durable before the
        # keystroke, because after the keystroke it is too late to write
        # down that it happened -- and phrased as SENDING rather than as
        # an intent that recovery may read as delivery, because between
        # this line and the next the honest answer is "unknown".
        write_journal(
            self._journal,
            self._journal_record(index, validated, text, voice,
                                 JOURNAL_PHASE_SENDING, attempts))

        try:
            send_key(window, validated, self._tool_timeout)
        except SessionError as err:
            # The journal STAYS at `sending`.  xdotool's own failure says
            # nothing about whether the X server acted, so this is the
            # ambiguous case by construction: the next session halts on
            # it and asks somebody who can look at the game, rather than
            # this module deciding the key landed (which would invent a
            # frame) or that it did not (which would drop a real one).
            self._abort(
                "keystroke '%s' for frame %d could not be delivered: "
                "%s.  Whether it reached the game is UNKNOWN -- xdotool "
                "failing says nothing about whether the X server acted "
                "-- so the journal at %s is left ambiguous and the next "
                "session will halt on it.  Establish what happened from "
                "the game and run `\"$PLAYTHROUGH_PYTHON\" -B "
                "playthrough/tooling/session.py reconcile`"
                % (validated, index, err, self._journal))
            raise

        # DELIVERED.  xdotool returned 0, so the keystroke reached the X
        # server: the ambiguity is over and recovery may photograph this
        # index without inventing anything.  Durable before the capture
        # for the same reason the `sending` record was durable before the
        # send.
        write_journal(
            self._journal,
            self._journal_record(index, validated, text, voice,
                                 JOURNAL_PHASE_DELIVERED, attempts))

        try:
            payload = self._capture_frame(index)
            path = assert_payload_matches(index, payload, self._frames)
        except SessionError as err:
            self._abort(
                "frame %d was not captured after '%s' was pressed: %s.  "
                "The journal at %s records the keystroke, so the next "
                "session captures this index rather than leaving the "
                "keystroke undocumented"
                % (index, validated, err, self._journal))
            # The ABORT REASON is what is raised, not the bare cause:
            # it names the journal and the same-index recovery, which is
            # the one thing the operator needs to know and is what the
            # RecordError branch in _commit() already surfaces.  Only
            # the message is replaced -- the CLASS is preserved, because
            # this branch also sees a capture timeout (plain
            # SessionError) and a capturer that has gone missing
            # (ToolMissing), and forcing every one of them to
            # CaptureError would quietly change the exit status that
            # tells those failures apart.
            raise err.__class__(self._aborted) from err

        # The capture is committed to playthrough/frames/, so the
        # journal is advanced with the payload it reported.  From here a
        # crash needs no camera to finish the step.
        write_journal(
            self._journal,
            self._journal_record(index, validated, text, voice,
                                 JOURNAL_PHASE_CAPTURED, attempts,
                                 payload))

        row = self._commit(index, validated, text, voice, payload,
                           attempts, False, expect=expect,
                           declared_modal=declared_modal)

        # THE POST-KEY INTEGRITY CHECKS, on the same step rather than the
        # next one.  The save-set comparison used to run only BEFORE a
        # key, which meant a keystroke that created a second survivor was
        # detected one whole step late -- after another key had been sent
        # into a game state this module had already lost track of.  Both
        # run here, with the row already committed, because the keystroke
        # and the frame really happened and the record says so; what stops
        # is everything after them.
        try:
            self._assert_save_pin()
            self._settle_ui_phase(index, payload)
        except SessionError as err:
            self._abort(
                "frame %d is captured and recorded, and then the state "
                "of the save tree refused the step: %s" % (index, err))
            raise

        # THE ENFORCING GUARD, in the same place and for the same reason:
        # the frame and the row are on the device, so the record is
        # complete and honest, and what this refuses is the NEXT
        # keystroke.  The reason was computed inside _commit, where it
        # was also written into the telemetry row, so the halt and the
        # record cannot disagree about whether it fired.
        halt = self._halt_reason(index, expect, self._effect,
                                 declared_modal, self._modals)
        if halt is not None:
            self._abort(halt)
            raise GuardHalt(halt)

        # `action` is taken from the ROW rather than from `text`,
        # because the observed-effect guard may have appended its
        # marker while the row was being written and the caller must
        # see the text that was actually recorded.
        result = StepResult(
            frame=index,
            key=validated,
            action=str(row["action"]),
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
            effect=self._verdict,
            effect_detail=self._effect,
            row=dict(row),
            observation=dict(self._observation),
        )
        LOG.info("%s", result.describe())
        return result

    def _assert_menu_hotkey_permitted(self, key: str, action: str,
                                      commentary: str) -> None:
        """REFUSE a letter sent to open Custom Character.  Never send it.

        The exact mistake runtime testing found in the first recorded
        session: "u" was sent to open the custom sheet, and because the
        top row of the same menu declares "T<u|U>torial Game" with those
        very letters (src/main_menu.cpp:466) the top row took it -- the
        submenu folded away and the highlight came to rest on a
        FORBIDDEN entry, which then needed three Left presses to undo.

        THIS USED TO BE AN ADVISORY, AND A SECURITY REVIEW WAS RIGHT
        ABOUT IT.  The reasoning behind the warning was sound as far as it
        went -- "u" is also the game's own north-east step, so a blanket
        refusal would break ordinary play -- but the conclusion drawn from
        it was wrong: the code proved, from the engine's own declarations,
        that this keystroke lands on a forbidden entry, printed that
        proof, and then delivered the key anyway.  A control that
        establishes the violation and permits it is not a control.

        So it is a refusal now, and the three conditions that make the
        refusal both correct and safe are ALL required:

          * the key is one of the two colliding letters;
          * the caller's own action or commentary says it is meant for
            the custom sheet -- which is exactly the case that was
            wrong, and nothing else;
          * the observed UI phase is `menu`.  The phase is read from
            PHOTOGRAPHED evidence (a sidebar reading in the record), not
            asserted, so an in-world "u" -- the north-east step -- is
            never touched by this, whatever the commentary happens to
            say.

        Raised BEFORE the journal is written and BEFORE the key is
        delivered, so nothing happened and the session stays usable: the
        caller takes the verified route instead.
        """
        if key.split(CHORD_SEPARATOR)[-1] not in MENU_HOTKEY_COLLISION:
            return
        if not (CUSTOM_CHARACTER_MENTION_RE.search(action) or
                CUSTOM_CHARACTER_MENTION_RE.search(commentary)):
            return
        if self._ui_phase != UI_PHASE_MENU:
            return
        raise KeyRejected(
            "'%s' is REFUSED and has NOT been sent.  It is declared for "
            "%r (src/main_menu.cpp:476) AND for %r on the top row of the "
            "same menu (src/main_menu.cpp:466), and the top row wins: "
            "the submenu folds away and the highlight lands on the "
            "tutorial, a forbidden entry.  This keystroke says it is "
            "meant for the custom sheet and the engine is still on a "
            "menu, so sending it would take the wrong door.  Nothing "
            "happened; take the permitted door the verified way "
            "instead -- %s.  (An in-world '%s' is the north-east step "
            "and is never refused: the phase here is read from the "
            "sidebar in the record, not asserted.)"
            % (key, MENU_CUSTOM_CHARACTER, MENU_TUTORIAL_ENTRY,
               "; ".join(MENU_CUSTOM_CHARACTER_ROUTE), key))

    def reconcile(self, outcome: str) -> Tuple[str, ...]:
        """Resolve an ambiguous `sending` journal.  Returns what it did.

        THE OPERATOR'S ANSWER TO THE ONE QUESTION THIS MODULE CANNOT
        ANSWER ITSELF.  A run that ended between the pre-send journal and
        confirmed delivery leaves a keystroke whose fate is genuinely
        unknown; both possible answers produce a different record, and
        choosing one automatically is how evidence gets invented (see the
        JOURNAL_PHASE_* commentary).  So the session halts, somebody looks
        at the game, and says which it was:

        * ``delivered`` -- the key DID land.  The journal is promoted to
          that phase and the ordinary recovery path finishes the step:
          the engine is re-authenticated, the frame is captured at the
          SAME index, and the row is appended with `recovered: true`.
        * ``not-delivered`` -- the key did NOT land.  The journal is
          discarded, no frame is captured and no row is written, so the
          index stays free for the next `step`.

        This is deliberately NOT usable to resolve anything else: a
        journal in any other phase is left exactly as it is, because
        recovery already has an honest answer for it and an operator
        override would be a way past that answer.

        :raises RecordError: when there is nothing ambiguous to resolve,
            or when the declared outcome is not one of the two.
        """
        if outcome not in RECONCILE_OUTCOMES:
            raise RecordError(
                "an outcome is '%s' or '%s', got %r.  The two answers "
                "are the two things that can have happened to the key"
                % (RECONCILE_DELIVERED, RECONCILE_NOT_DELIVERED,
                   outcome))
        self._lock.assert_held()
        record = read_journal(self._journal)
        if record is None:
            raise RecordError(
                "there is no step journal at %s, so there is nothing to "
                "reconcile: no keystroke is in flight"
                % self._journal)
        checked = self._validated_journal(record)
        if str(checked["phase"]) != JOURNAL_PHASE_SENDING:
            raise RecordError(
                "the step journal %s is in phase '%s', which is not "
                "ambiguous: recovery completes it on its own evidence "
                "when the next session opens.  Only a '%s' journal is "
                "reconciled by hand, because only that one asks a "
                "question this module cannot answer"
                % (self._journal, checked["phase"],
                   JOURNAL_PHASE_SENDING))
        frame = int(checked["frame"])
        key = str(checked["key"])
        if outcome == RECONCILE_NOT_DELIVERED:
            clear_journal(self._journal)
            note = ("declared NOT delivered: '%s' never reached the game, "
                    "so frame %d has no capture and no row and the index "
                    "stays free for the next step" % (key, frame))
            LOG.warning("%s", note)
            self._recovered = self._recovered + (note,)
            return (note,)
        write_journal(
            self._journal,
            self._journal_record(
                frame, key, str(checked["action"]),
                str(checked["commentary"]), JOURNAL_PHASE_DELIVERED,
                int(checked["capture_attempts"]),
                checked["payload"]
                if isinstance(checked["payload"], dict) else None))
        notes = (("declared delivered: '%s' reached the game, so frame "
                  "%d is completed at the same index" % (key, frame)),)
        notes = notes + self._settle_journal()
        for note in notes:
            LOG.warning("%s", note)
        self._frame = self._recover_counter()
        self._recovered = self._recovered + notes
        return notes

    def _assert_voice(self, commentary: str) -> None:
        """Refuse a commentary that is not the survivor's own voice.

        A REFUSAL, BEFORE THE KEY IS SENT.  It used to be a warning, one
        per word per process, and the row was appended regardless -- so a
        stderr line during a four-hundred-row session was all that stood
        between an engineering observation and the committed transcript,
        which becomes a caption on the film.  The requirement is that
        meta and "gamey" remarks stay out of the in-character record and
        go to playthrough/TECHNICAL_NOTES.md instead, and nothing that
        can be walked past satisfies it.

        manifest.py owns the vocabulary and the message, so the gate here
        and the gate at publication cannot differ in strength.  Nothing
        is sent and nothing is journalled, so the step is simply retried
        with the sentence rewritten.
        """
        problem = manifest.meta_vocabulary_problem(
            commentary, "commentary")
        if problem is not None:
            raise RecordError(problem)

    def _assert_clock_honesty(self, commentary: str) -> None:
        """Refuse a stated time or date the frames contradict.

        THE GATE THE FALSE FRAME-308 STATEMENT WALKED PAST.  Its
        commentary reads "It is ten past eight in the morning on the
        twenty-eighth of May" on a frame captured at 08:05:36 on
        Thursday, May 20 -- both statements untrue, in a record whose
        first requirement is that nothing in it is fabricated, and
        invisible to every structural check because the row is internally
        consistent and the arithmetic is exact.

        The comparison is against the LAST READING THIS SESSION
        OBSERVED, which is what the driver had in front of them when the
        sentence was written and therefore the honest comparand: the
        commentary explains why this key is about to be pressed, so it
        belongs to the state before it.  manifest.py owns the parser and
        the tolerances (three minutes for an exact statement, a quarter
        of an hour for a hedged one); this only supplies the reading and
        refuses.

        Nothing is sent, so a refusal costs the call and nothing else.
        """
        clock, date_text = self._last_reading()
        problems = manifest.clock_honesty_problems(
            commentary, clock, date_text, "commentary")
        if problems:
            raise RecordError(
                "the commentary states something the frames do not "
                "support, so '%s' was NOT sent.  %s"
                % ("the next keystroke", "  ".join(problems)))

    def _last_reading(self) -> Tuple[Optional[str], Optional[str]]:
        """Return the last observed (clock, date), from the record.

        Taken from the telemetry sidecar, which carries both columns, and
        read from disk rather than remembered -- because the intended
        shape of a session is ONE PROCESS PER STEP, so the previous
        frame's reading was observed by a process that has already
        exited.  A session that has just recovered a step gets the
        recovered frame's reading, which is correct: that is the last
        thing anybody could have looked at.
        """
        if self._observation:
            return (_reading_or_none(self._observation, "ingame_clock"),
                    _reading_or_none(self._observation, "date"))
        last: Optional[Dict[str, object]] = None
        try:
            with open(self._observations, "r",
                      encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        row = json.loads(text)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        last = row
        except FileNotFoundError:
            return (None, None)
        except OSError as err:
            raise RecordError(
                "cannot read the telemetry sidecar %s: %s.  It carries "
                "the reading the commentary is held against, and a "
                "statement about the time is not accepted unchecked"
                % (self._observations, err)) from err
        if last is None:
            return (None, None)
        return (_reading_or_none(last, "ingame_clock"),
                _reading_or_none(last, "date"))


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
# A status of its own, because "there is no room" is answered by freeing
# space and pressing the same key again, which is a different action
# from anything the five above ask for -- and because a driver looping
# over keystrokes needs to tell it apart from a failed capture.
EXIT_CAPACITY = 6
# THE TWO HALVES OF THE OBSERVE-BEFORE-THE-NEXT-KEY GUARD.  7 means
# nothing was sent and the remedy is to look at the previous capture and
# say what it shows; 8 means the key WAS sent, the frame and row are
# recorded, and the capture contradicted what the step declared -- so the
# remedy is to read that frame, acknowledge it, and decide what to do
# about the screen it actually shows.  Distinct statuses because a driver
# must not retry a delivered key.
EXIT_OBSERVATION = 7
EXIT_GUARD = 8

_EPILOG = """\
the permitted door, and the four that are shut
  Custom Character                THE ONLY permitted new-game entry
  Preset Character                FORBIDDEN -- the template picker
  Random Character                FORBIDDEN
  Play Now!  (Default Scenario)   FORBIDDEN (two spaces after the !)
  Play Now!                       FORBIDDEN
  scenario                        missed / "Missed"
  first screen of a fresh userdir "Select your language", NOT the menu

  DO NOT press u or U for Custom Character.  The top row declares
  "T<u|U>torial Game" with the same two letters (src/main_menu.cpp:466)
  and the top row wins: the submenu folds away and the highlight lands
  on [Tutorial Game].  Take the entry the verified way instead --
  Left/Right along the top row to [New Game], READ the capture to see
  which submenu row carries the selection bar, Up/Down until it is on
  Custom Character, read again, then Return.  The opening position of
  that bar is not assumed: on the first capture of this record it sat
  on Preset Character.

no cheating, ever
  debug, debug_mode and debug_hour_timer ship UNBOUND in
  data/raw/keybindings.json, so no keystroke reaches them.  The five
  DEBUG_DIALOGUE_* toggles ship BOUND, to ctrl+c/d/t/y/r, so `step`
  refuses every ctrl chord outright -- along with alt, super and meta,
  which the game binds to nothing and which reach the window manager
  (alt+F4 closes the engine).  The keybindings audit runs before EVERY
  key, not only when `audit` is asked for, against the committed
  <userdir>/config/keybindings.json, which this module reads and never
  writes.  No spawning, no stat editing, no teleport, no god mode, no
  map reveal -- for any reason, including avoiding death.

one key, one frame, one row
  `step` sends exactly one keystroke.  Several keystrokes are several
  invocations, and therefore several frames and several rows.  Read the
  frame and the clock this prints before choosing the next key.  Pass
  the REASON with --note; the "press '<key>'" half of the row is derived
  from --key and cannot be overridden.

resuming instead of creating
  With a character save already under playthrough/userdir/save/, this
  session RESUMES it: load that world and that character, and never
  press u/U, p/P, r/R, d/D or o/O at the menu -- all five are refused
  before delivery while the engine is still on one.  The session is in
  the world once a captured frame shows the sidebar, and at that moment
  <userdir>/config/lastworld.json must name the pinned survivor.

an interrupted send
  `step` journals `sending` before the key leaves and `delivered` once
  xdotool returns 0.  A run that dies in between leaves the delivery
  UNKNOWN, and the next session halts rather than guessing.  Establish
  from the game which way it went and then, having sourced
  playthrough/tooling/env.sh for PLAYTHROUGH_PYTHON:
    SS='playthrough/tooling/session.py'
    # it DID land -- capture that index
    "$PLAYTHROUGH_PYTHON" -B "$SS" reconcile --outcome delivered
    # it did NOT -- record nothing
    "$PLAYTHROUGH_PYTHON" -B "$SS" reconcile --outcome not-delivered

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
        "--note", default=None, metavar="TEXT",
        help="what the keystroke was for, appended after \" -- \" to "
             "the derived \"press '<key>'\".  The key half is NEVER "
             "supplied by the caller: a row that could name a "
             "different key from the one delivered is not evidence")
    step.add_argument(
        "--commentary", required=True, metavar="TEXT",
        help="the survivor's own first-person reason for it")
    step.add_argument(
        "--window-id", default=None, metavar="ID",
        help="a decimal window id from launch_game.sh; the process "
             "behind it is authenticated before every keystroke")
    step.add_argument(
        "--expect", default=EXPECT_CHANGED, choices=list(EXPECTATIONS),
        help="what this step's capture will show.  'changed' (the "
             "default) is the ordinary case; 'unchanged' declares in "
             "advance that this key legitimately moves nothing on "
             "screen; 'either' is for a response that genuinely cannot "
             "be predicted.  A capture that CONTRADICTS the "
             "declaration records its frame and row and then HALTS the "
             "session, because a key that did not land is how a record "
             "comes to describe something that did not happen")
    step.add_argument(
        "--observed", default=None, metavar="TEXT",
        help="what YOU saw on the PREVIOUS capture -- which screen, "
             "what was selected, whether a box was open.  Required for "
             "every step after the first unless that frame is already "
             "acknowledged, recorded in "
             "playthrough/build/" + ACKNOWLEDGMENTS_NAME + " before "
             "this key is delivered, and refused if it is too short to "
             "describe a screen.  This is 'never blind-spam keys' as a "
             "precondition instead of as advice")
    step.add_argument(
        "--expect-modal", default=None, metavar="TOKEN",
        choices=list(MODAL_TOKENS),
        help="the engine query box this step is deliberately "
             "answering.  An UNDECLARED box on the capture halts the "
             "session -- every one of them eats a key aimed at the "
             "screen behind it -- and so does a declared one that is "
             "not there")

    ack = sub.add_parser(
        "ack",
        help="record that a capture was READ, and what it showed")
    ack.add_argument(
        "--frame", type=int, required=True, metavar="N",
        help="the captured frame being acknowledged")
    ack.add_argument(
        "--observed", required=True, metavar="TEXT",
        help="what the capture shows, in enough words to identify the "
             "screen; this is the durable record that it was looked at")

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

    reconcile = sub.add_parser(
        "reconcile",
        help="resolve an ambiguous journal after an interrupted send")
    reconcile.add_argument(
        "--outcome", required=True, choices=list(RECONCILE_OUTCOMES),
        help="what an operator ESTABLISHED from the game itself: "
             "'delivered' if the keystroke landed, so the frame is "
             "captured at the same index and the row appended; "
             "'not-delivered' if it did not, so the journal is "
             "discarded and nothing is recorded.  There is no default: "
             "this exists precisely because the answer cannot be "
             "inferred")

    sub.add_parser(
        "status", help="report the counter and verify the record")
    sub.add_parser(
        "journal",
        help=("report an outstanding step WITHOUT settling it -- the "
              "read-only query the acceptance gate asks"))
    annotate = sub.add_parser(
        "annotate",
        help=("measure recorded captures and report -- or with "
              "--amend record -- the observed-effect marker"))
    annotate.add_argument(
        "--frame", type=int, action="append", default=None,
        metavar="N", dest="frames",
        help=("the frame to measure against the capture before it; "
              "repeatable, and every recorded frame when omitted"))
    annotate.add_argument(
        "--amend", action="store_true",
        help=("append the measurement to playthrough/amendments.jsonl "
              "as an amendment keyed to the sha256 of the row it "
              "concerns.  THE RECORDED ROW IS NOT TOUCHED on any path: "
              "the ledger is a second append-only file, and "
              "manifest.resolve_rows() is what applies it to the "
              "transcript and the caption cues.  Without this the "
              "measurement is only reported"))
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
                  window_id: object = None,
                  settle_journal: bool = True) -> Session:
    """Build a Session from the parsed command line."""
    return Session(
        manifest_path=args.manifest,
        frames_dir=args.frames_dir,
        observations_path=args.observations,
        window_id=window_id,
        settle_journal=settle_journal,
    )


def _command_step(args: argparse.Namespace) -> int:
    """Send one keystroke, record one frame, report what it showed."""
    key = validate_key(args.key)
    with _open_session(args, args.window_id) as session:
        for note in session.recovered:
            sys.stderr.write("playthrough: recovered: %s\n" % note)
        result = session.step(
            key, commentary=args.commentary, note=args.note,
            expect=args.expect, observed=args.observed,
            expect_modal=args.expect_modal)
        _emit("FRAME_INDEX", result.frame)
        _emit("FRAME_FILE", result.file)
        _emit("FRAME_PATH", manifest.relative_to_repo(result.path))
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
        _emit("EXPECTED", args.expect)
        _emit("EFFECT", result.effect)
        _emit("MODALS", ",".join(session.modals))
        _emit("SESSION_MODE", session.pin.mode)
        _emit("SESSION_WORLD", session.pin.world)
        _emit("MANIFEST",
              manifest.relative_to_repo(session.manifest_path))
        _emit("OBSERVATIONS",
              manifest.relative_to_repo(session.observations_path))
        _emit("ACKNOWLEDGMENTS",
              manifest.relative_to_repo(session.acknowledgments_path))
    return EXIT_OK


def _command_ack(args: argparse.Namespace) -> int:
    """Record an operator's reading of one already-captured frame.

    THE ONE WAY PAST A HALT, and the reason the halt is safe to make
    fatal: an operator who has looked at the frame says so here, in a
    ledger that keeps the statement, and the session continues.  It
    opens WITHOUT settling the journal for the same reason `reconcile`
    does -- a session stopped by the guard may be holding one, and
    reading a picture is not the act that should resolve it.
    """
    with _open_session(args, None, settle_journal=False) as session:
        row = session.acknowledge(args.frame, args.observed)
        _emit("FRAME_INDEX", row["frame"])
        _emit("FRAME_FILE", row["file"])
        _emit("FRAME_SHA256", row["frame_sha256"])
        _emit("EFFECT", row["verdict"])
        _emit("MODALS", ",".join(str(one) for one in row["modals"]))
        _emit("OBSERVED", row["observed"])
        _emit("ACKNOWLEDGMENTS",
              manifest.relative_to_repo(session.acknowledgments_path))
    return EXIT_OK


def _command_reconcile(args: argparse.Namespace) -> int:
    """Resolve an ambiguous journal on an operator's declaration.

    Opened WITHOUT settling the journal, because an ambiguous journal is
    exactly what an ordinary open refuses to continue past -- and this
    command exists to resolve that state.
    """
    with _open_session(args, None, settle_journal=False) as opened:
        for note in opened.reconcile(args.outcome):
            sys.stderr.write("playthrough: reconciled: %s\n" % note)
        _emit("OUTCOME", args.outcome)
        _emit("FRAME_INDEX", opened.frame)
        _emit("MANIFEST",
              manifest.relative_to_repo(opened.manifest_path))
        _emit("OBSERVATIONS",
              manifest.relative_to_repo(opened.observations_path))
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
    _emit("PLAYTHROUGH_SAVE_DIR",
          manifest.relative_to_repo(probe.save_dir))
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
    """Authenticate the game window and report what it belongs to."""
    identity = authenticated_window(args.window_id)
    _emit("PLAYTHROUGH_WINDOW_ID", identity.window)
    _emit("PLAYTHROUGH_WINDOW_CLASS", window_class())
    _emit("PLAYTHROUGH_WINDOW_PID", identity.pid)
    _emit("PLAYTHROUGH_WINDOW_EXE",
          manifest.relative_to_repo(identity.executable))
    _emit("PLAYTHROUGH_WINDOW_CWD",
          manifest.relative_to_repo(identity.cwd))
    _emit("PLAYTHROUGH_WINDOW_USERDIR",
          manifest.relative_to_repo(identity.userdir))
    _emit("DISPLAY", identity.display)
    return EXIT_OK


def _command_audit(args: argparse.Namespace) -> int:
    """Prove the integrity conditions a session depends on."""
    finding = assert_no_debug_bindings(args.keybindings)
    _emit("DEBUG_BINDINGS", "none")
    _emit("DEBUG_ACTIONS_CHECKED", ",".join(
        DEBUG_ACTION_IDS + DEBUG_DIALOGUE_ACTION_IDS))
    _emit("DEBUG_ID_MARKER", DEBUG_ID_MARKER)
    _emit("REFUSED_CHORDS", ",".join(sorted(PROHIBITED_CHORDS)))
    _emit("REFUSED_MODIFIERS", ",".join(
        sorted(REFUSED_MODIFIER_KEYS)))
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
    """Report the counter and verify the record against the frames.

    Opening the session settles any journal a crashed step left behind,
    so `status` both reports the record and makes it whole.
    """
    with _open_session(args) as session:
        problems = session.verify_record()
        for note in session.recovered:
            sys.stderr.write("playthrough: recovered: %s\n" % note)
        _emit("FRAME_LAST", session.frame)
        _emit("SESSION_MODE", session.pin.mode)
        _emit("SESSION_WORLD", session.pin.world)
        # THE PHASE AND THE EVIDENCE FOR IT, together.  The phase decides
        # whether a resumed session's new-survivor hotkeys are refused,
        # so it is reported alongside the frame whose photographed
        # sidebar released it -- empty while no captured frame has shown
        # one, which is the state in which the refusal holds.
        _emit("UI_PHASE", session.ui_phase)
        _emit("UI_PHASE_FRAME", session.sidebar_frame)
        # And the launcher's own verified statement about the screen this
        # session began on, so the two are read side by side: the phase
        # above is what THIS record photographed, this is what
        # launch_game.sh established before the first keystroke.
        _emit("LAUNCH_UI_STATE", session.launch_state)
        _emit("RECOVERED", len(session.recovered))
        _emit("MANIFEST",
              manifest.relative_to_repo(session.manifest_path))
        _emit("FRAMES_DIR",
              manifest.relative_to_repo(session.frames_dir))
        _emit("OBSERVATIONS",
              manifest.relative_to_repo(session.observations_path))
        _emit("RECORD_PROBLEMS", len(problems))
        for problem in problems:
            sys.stderr.write("playthrough: %s\n" % problem)
    return EXIT_RECORD if problems else EXIT_OK


def _command_journal(args: argparse.Namespace) -> int:
    """Report an outstanding step, changing nothing.

    WHY THIS EXISTS SEPARATELY FROM `status`.  `status` opens a session,
    and opening a session SETTLES an outstanding journal -- that is
    deliberate and documented there, because an interrupted step must be
    completed before the record is verified.  But it makes `status`
    useless to an acceptance gate: the gate would REPAIR the very thing
    it came to judge, and a delivered keystroke that never became a frame
    would be resolved by the act of asking about it.  A review found
    exactly that gap on the other side of the same invariant -- a
    terminal keystroke was delivered, its capture was rejected, and the
    frame/row/line identity still read 305 == 305 == 305 because all
    three of those counts are written only AFTER a capture succeeds.  The
    outstanding journal was the only durable evidence that a 306th key
    had left, and nothing was looking at it.

    So this takes no lock, opens no session, recovers nothing and writes
    nothing: it derives the journal's path exactly as a session would and
    reads it.  A journal that exists but cannot be parsed still raises,
    because `read_journal` treats that as a fault rather than an absence
    -- an unreadable record of a keystroke that may have been delivered
    is the one thing that must not read as "no keystroke".
    """
    path = journal_path(getattr(args, "root", None))
    record = read_journal(path)
    _emit("JOURNAL", path)
    _emit("JOURNAL_PRESENT", record is not None)
    if record is None:
        _emit("JOURNAL_PHASE", "none")
        _emit("JOURNAL_FRAME", "")
        _emit("JOURNAL_VERSION", "")
        _emit("JOURNAL_KEY", "")
        return EXIT_OK
    _emit("JOURNAL_PHASE", record.get("phase", ""))
    _emit("JOURNAL_FRAME", record.get("frame", ""))
    _emit("JOURNAL_VERSION", record.get("version", ""))
    _emit("JOURNAL_KEY", record.get("key", ""))
    return EXIT_OK


def _command_annotate(args: argparse.Namespace) -> int:
    """Measure recorded captures for the observed-effect marker.

    The step lock is held for the whole pass.  Nothing is rewritten --
    the pass reads the record and, with --amend, appends to the
    amendment ledger -- but the measurement compares each capture with
    the one before it, and a concurrent `step` adding a capture and a
    row underneath that comparison would make the reading a statement
    about a record that no longer exists.
    """
    with _open_session(args) as session:
        results = session.annotate_recorded_effects(
            frames=args.frames, amend=args.amend)
    marked = [one for one in results if one.marked]
    for one in marked:
        sys.stderr.write(
            "playthrough: frame %d: %s (%s changed pixel(s)); the row "
            "still reads %r and a derivative %s read %r\n"
            % (one.frame, one.verdict,
               "unknown" if one.screen_pixels is None
               else one.screen_pixels,
               one.action,
               "now" if one.amended else "would",
               one.extended))
    unknown = [one.frame for one in results
               if one.verdict == EFFECT_UNKNOWN]
    _emit("EXAMINED", len(results))
    _emit("MARKED", len(marked))
    _emit("FRAMES", ",".join(str(one.frame) for one in marked))
    _emit("AMENDED", ",".join(str(one.frame) for one in results
                              if one.amended))
    _emit("LEDGER", manifest.relative_to_repo(
        default_amendments_path()))
    _emit("UNMEASURED", ",".join(str(index) for index in unknown))
    if unknown:
        sys.stderr.write(
            "playthrough: %d capture(s) could not be compared (%s), so "
            "no observation of what those keystrokes did was made; read "
            "them yourself rather than treating silence as a verdict\n"
            % (len(unknown), _summarised(unknown)))
    return EXIT_OK


_COMMANDS = {
    "step": _command_step,
    "ack": _command_ack,
    "annotate": _command_annotate,
    "reconcile": _command_reconcile,
    "probe": _command_probe,
    "window": _command_window,
    "audit": _command_audit,
    "status": _command_status,
    "journal": _command_journal,
}

_EXIT_FOR = (
    (CheatGuard, EXIT_CHEAT),
    (CapacityError, EXIT_CAPACITY),
    # BOTH HALVES OF THE OBSERVE-BEFORE-THE-NEXT-KEY GUARD GET THEIR OWN
    # STATUS, so a driver can tell "read the picture and say what it
    # shows" apart from "the picture is not what you said it would be".
    # They are listed before the shapes below because ObservationRequired
    # and GuardHalt are refusals about the OBSERVATION, and a caller that
    # confused either with a lost window or an unbelievable record would
    # retry the wrong thing.
    (ObservationRequired, EXIT_OBSERVATION),
    (GuardHalt, EXIT_GUARD),
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
    failed capture, an unbelievable record, a cheat guard tripping and a
    disk with no room left for the next frame, so a driver can tell "you
    asked for the wrong thing" apart from "free some space and press it
    again" apart from "the session is over".
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
