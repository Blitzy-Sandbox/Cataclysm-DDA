#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/seed_options.py.

This module edits a file the game engine owns, in place, and everything
downstream of it trusts the result.  Two of its failure modes are
silent, and both are fatal to the finished film:

* ``24_HOUR`` has three legal values, and ``"military"`` renders the
  sidebar clock as ``0815.32``.  The engine accepts it, the game runs,
  every frame captures -- and the pipeline's ``%02d:%02d:%02d`` regex
  matches nothing, so every reading goes null, every duration falls to
  the 0.25 s floor, and the movie's pacing is fiction.
* ``TILES`` names a tileset by the ``NAME:`` field of its
  ``tileset.txt``, never by its directory.  Writing ``ASCIITileset``
  where ``ASCIITiles`` belongs selects nothing.

And because it writes, it can destroy: a mistyped path, a wholesale
rewrite that discards the engine's own annotations, or a half-written
file the engine reads mid-save.  So the confinement, the preservation
and the atomicity are tested as carefully as the values are.

    python3 playthrough/tooling/test_seed_options.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED
* CONFINEMENT -- only ``options.json`` and ``worldoptions.json``, only
  when the file already exists, only when it parses as an engine-shaped
  option array.  A module that patches what the engine wrote must never
  be able to create a configuration document, because inventing one
  means inventing the ``info`` and ``default`` text the engine owns.
* PRESERVATION -- unknown options survive, member order survives, the
  engine's annotations survive, and the layout survives, so a seeded
  value is a one-line diff and a second run is byte-identical to the
  first.  Idempotency is asserted at the byte level, not by re-reading
  values.
* EVERY OCCURRENCE, AND THE LAST ONE WINS -- the engine walks the array
  calling setValue for each element, so a duplicated name means the
  later entry decides.  Patching all of them and READING the last is
  the only pair of behaviours that agree with the engine.
* ATOMICITY -- a failure before the rename leaves the original file
  exactly as it was, and leaves no temporary file behind.
* THE FORBIDDEN VALUE -- the ``military`` trap is named explicitly in
  both the post-write confirmation and the verification gate.
* THE CROSS-MODULE SEAM -- the terminal dimensions this module writes
  are the ones ``sidebar_geometry.py`` derives the OCR crop from, so
  the two are exercised together against one file.

Every test works inside a temporary checkout.  Nothing in the real
repository is read for its content, written, or created; the module's
own default paths are asserted to resolve there and then deliberately
not used.

Standard library only, plus the two sibling modules.
"""

import contextlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything
# written there.  This must precede the imports below to affect them.
sys.dont_write_bytecode = True

try:
    import seed_options
    import sidebar_geometry
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import seed_options
    import sidebar_geometry


# The values this pipeline requires, restated here so that a change to
# the module's constants has to be a deliberate change to the contract
# rather than a silent one both sides agree on.
WANTED = {
    "24_HOUR": "24h",
    "SOUND_ENABLED": "false",
    "USE_TILES": "true",
    "TERMINAL_X": "240",
    "TERMINAL_Y": "67",
    "CHARACTER_POINT_POOLS": "any",
    "WORLD_COMPRESSION2": "false",
    # The rest of the capture geometry.  The window is TERMINAL_*
    # multiplied by the FONT_* dimensions [src/sdltiles.cpp:595-596],
    # placed by FULLSCREEN [src/options.cpp:2715-2724], scaled by
    # SCALING_FACTOR/SCALING_MODE [src/options.cpp:2806-2825] and read
    # on the side SIDEBAR_POSITION chooses [src/options.cpp:2132-2136].
    # Each of these values is also the engine's own default, so seeding
    # them is an assertion rather than a change on a fresh file -- which
    # is the point: an operator or a later engine run can move any of
    # them, and the crop would then be computed for a window that is not
    # the one on screen.
    "FONT_WIDTH": "8",
    "FONT_HEIGHT": "16",
    "SIDEBAR_POSITION": "right",
    "FULLSCREEN": "windowedbl",
    "SCALING_MODE": "none",
    "SCALING_FACTOR": "1",
}

# The installed packs the fixture pretends to have.  Both ids come from
# a NAME: field that differs from the directory name, which is the
# distinction that makes a directory-name shortcut fail.
MSX_DIR = "MShockXotto+"
MSX_IDENT = "MshockXottoplus"
MSX_VIEW = "MSXotto+"
ASCII_DIR = "ASCIITileset"
ASCII_IDENT = "ASCIITiles"
ASCII_VIEW = "ASCII"

# Every environment variable the two modules read, cleared per test so
# that a suite run inside a sourced shell behaves as one run outside it.
ENVIRONMENT_KEYS = (
    "PLAYTHROUGH_REPO_ROOT",
    "PLAYTHROUGH_USERDIR",
    "PLAYTHROUGH_OPTIONS_JSON",
    "PLAYTHROUGH_SAVE_DIR",
    "PLAYTHROUGH_TERMINAL_X",
    "PLAYTHROUGH_TERMINAL_Y",
    "PLAYTHROUGH_FONT_WIDTH",
    "PLAYTHROUGH_FONT_HEIGHT",
    "PLAYTHROUGH_SCREEN_WIDTH",
    "PLAYTHROUGH_SCREEN_HEIGHT",
    "PLAYTHROUGH_TILESET",
    "PLAYTHROUGH_TILESET_ALIASES",
    "PLAYTHROUGH_TILESET_FALLBACK",
    "PLAYTHROUGH_ALLOW_TILESET_FALLBACK",
    "PLAYTHROUGH_TILESET_RESOLVED",
    "PLAYTHROUGH_SESSION_MODE",
    "PLAYTHROUGH_PANEL_OPTIONS_JSON",
    "PLAYTHROUGH_CONFIG_DIR",
    "PLAYTHROUGH_GAME_BIN",
    "PLAYTHROUGH_LOCK_DIR",
    "PLAYTHROUGH_RUNTIME_DIR",
    "PLAYTHROUGH_SEED_LOCK_TIMEOUT",
)

# Snapshot of the real options file, so the suite can prove it never
# touched the repository's own evidence.
_REAL_OPTIONS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "userdir",
    "config", "options.json")
_REAL_SNAPSHOT = None


def _snapshot(path):
    """Return the bytes at ``path``, or None when it does not exist."""
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


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


def _quiet(module):
    """Send one module's warnings nowhere for the whole suite."""
    module.LOG.addHandler(logging.NullHandler())
    module.LOG.propagate = False


def setUpModule():
    """Silence both modules' WARNING streams and snapshot the userdir.

    The warnings are how a substituted default stays visible to an
    operator, and they are asserted here through the ``notes`` list the
    same substitution appends to -- the checkable form of the same
    fact.  Letting them reach stderr as well would bury the runner's
    own output.
    """
    global _REAL_SNAPSHOT
    _REAL_SNAPSHOT = _snapshot(_REAL_OPTIONS)
    _quiet(seed_options)
    _quiet(sidebar_geometry)


def tearDownModule():
    """Prove the suite never wrote the repository's own options file."""
    assert _snapshot(_REAL_OPTIONS) == _REAL_SNAPSHOT, (
        "the suite modified %s, which is committed evidence of the "
        "captured run" % _REAL_OPTIONS)


class SeedFixture(unittest.TestCase):
    """A temporary checkout with a game-written options file in it."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_seed_")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "data", "json", "ui"))
        os.makedirs(os.path.join(self.root, "src"))
        with open(os.path.join(self.root, "src", "path_info.cpp"), "w",
                  encoding="utf-8") as handle:
            handle.write("// a marker, not the engine\n")
        self.config = os.path.join(
            self.root, "playthrough", "userdir", "config")
        os.makedirs(self.config)
        self.saves = os.path.join(
            self.root, "playthrough", "userdir", "save")
        self.options_json = os.path.join(self.config, "options.json")
        self.gfx = os.path.join(self.root, "gfx")
        self.write_sidebar_widgets()
        cleared = {name: None for name in ENVIRONMENT_KEYS}
        self.env = _environment(**cleared)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    # -- fixture writers ---------------------------------------------

    def entry(self, name, value, **extra):
        """One option entry in the engine's own member order."""
        entry = {
            "info": "what %s does" % name,
            "default": value,
            "name": name,
            "value": value,
        }
        entry.update(extra)
        return entry

    def engine_entries(self, overrides=None, extra=()):
        """Every seeded option plus some the pipeline ignores.

        THE SEEDED SET IS FOURTEEN, not the eight it once was.  The
        window a session is captured from is TERMINAL_* multiplied by
        the FONT_* dimensions [src/sdltiles.cpp:595-596], placed
        according to FULLSCREEN, scaled by SCALING_FACTOR/SCALING_MODE
        and read on the side SIDEBAR_POSITION chooses -- so all six of
        those decide the crop the clock comes out of, and a review found
        them seeded nowhere and verified nowhere.  The original eight
        start from the WRONG value here, which keeps the change count
        unambiguous; the six new ones start from the engine's own
        default, which is what a genuine first-launch file holds.
        """
        values = {
            "24_HOUR": "12h",
            "SOUND_ENABLED": "true",
            # A user who ran the curses build, or turned tiles off,
            # leaves this false -- and TILES is gated on it, so the
            # seeded tileset would be inert.  Starting from the wrong
            # value on all of them keeps the change count unambiguous.
            "USE_TILES": "false",
            "TILES": "UltimateCataclysm",
            "TERMINAL_X": "80",
            "TERMINAL_Y": "24",
            "CHARACTER_POINT_POOLS": "story_teller",
            "WORLD_COMPRESSION2": "true",
            # These six start at the ENGINE'S OWN DEFAULTS, which are
            # also the values the pipeline wants: that is what a real
            # first-launch options file holds, and the crop-seam tests
            # below derive the first-launch window from exactly these
            # numbers.  Their seeding and verification is proved from a
            # deliberately wrong file in TestTheRenderGeometryOptions.
            "FONT_WIDTH": "8",
            "FONT_HEIGHT": "16",
            "SIDEBAR_POSITION": "right",
            "FULLSCREEN": "windowedbl",
            "SCALING_MODE": "none",
            "SCALING_FACTOR": "1",
        }
        if overrides:
            values.update(overrides)
        entries = [self.entry(name, value)
                   for name, value in values.items()]
        # Options this module must leave completely alone.
        entries.insert(1, self.entry("FONT_SIZE", "16"))
        entries.append(self.entry("PIXEL_MINIMAP", "true"))
        entries.append(self.entry("AUTOSAVE", "true"))
        entries.extend(extra)
        return entries

    def write_options(self, overrides=None, extra=(), pretty=True,
                      path=None, entries=None):
        """Write an engine-shaped options file and return its path."""
        target = path or self.options_json
        if entries is None:
            entries = self.engine_entries(overrides, extra)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(seed_options.serialize_entries(entries,
                                                        pretty))
        return target

    def write_sidebar_widgets(self, layout_id=None, clock=True,
                              width=44):
        """Write a minimal, resolvable widget tree for the crop check.

        verify() no longer compares the active layout's NAME against one
        id; it RESOLVES that layout to a crop and asks whether the layout
        draws a clock.  Both need a widget tree, so the fixture ships the
        smallest one the engine's own shape allows: a `style: sidebar`
        layout of the given width, one row inside it, and -- unless a
        test is deliberately building a clock-less preset -- a text
        widget rendering `time_text`.
        """
        identifier = layout_id or sidebar_geometry.DEFAULT_LAYOUT_ID
        widgets = [
            {"type": "widget", "id": identifier, "style": "sidebar",
             "width": width, "widgets": ["fixture_time_row"]},
            {"type": "widget", "id": "fixture_time_row",
             "style": "layout", "widgets": ["fixture_clock"]},
        ]
        if clock:
            widgets.append(
                {"type": "widget", "id": "fixture_clock",
                 "style": "text", "var": "time_text", "label": "Time"})
        else:
            widgets.append(
                {"type": "widget", "id": "fixture_clock",
                 "style": "text", "var": "compass_text",
                 "label": "Compass"})
        path = os.path.join(self.root, "data", "json", "ui",
                            "sidebar.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(widgets, handle)
        return path

    def write_raw(self, path, text):
        """Write literal text, for the cases that must be refused."""
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def write_tileset(self, directory, ident, view=None, base=None):
        """Write one pack's tileset.txt and return its directory."""
        holder = os.path.join(base or self.gfx, directory)
        os.makedirs(holder, exist_ok=True)
        lines = ["# comment first, as the shipped packs do",
                 "",
                 "NAME: %s" % ident]
        if view is not None:
            lines.append("VIEW: %s" % view)
        lines.append("JSON: tile_config.json")
        self.write_raw(os.path.join(holder, "tileset.txt"),
                       "\n".join(lines) + "\n")
        return holder

    def write_both_tilesets(self):
        """Install the two packs the pipeline knows about."""
        self.write_tileset(MSX_DIR, MSX_IDENT, MSX_VIEW)
        self.write_tileset(ASCII_DIR, ASCII_IDENT, ASCII_VIEW)

    def write_world(self, name, pools="any", occurrences=None):
        """Write one save/<World>/worldoptions.json."""
        holder = os.path.join(self.saves, name)
        os.makedirs(holder, exist_ok=True)
        if occurrences is None:
            occurrences = [pools]
        entries = [self.entry("CHARACTER_POINT_POOLS", value)
                   for value in occurrences]
        entries.insert(0, self.entry("CITY_SIZE", "8"))
        path = os.path.join(holder, "worldoptions.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(seed_options.serialize_entries(entries, True))
        return path

    # -- convenience -------------------------------------------------

    def bytes_at(self, path=None):
        """The exact bytes of a file, for byte-level assertions."""
        with open(path or self.options_json, "rb") as handle:
            return handle.read()

    def values(self, path=None):
        """Every option's stored value, including unseeded ones."""
        entries, _ = seed_options.load_entries(
            path or self.options_json)
        return {str(entry["name"]): str(entry["value"])
                for entry in entries}

    def patch(self, **overrides):
        """Patch the fixture's options file."""
        arguments = {"path": self.options_json, "root": self.root}
        arguments.update(overrides)
        return seed_options.patch(**arguments)

    def verify(self, **overrides):
        """Verify the fixture's options file."""
        arguments = {"path": self.options_json, "root": self.root}
        arguments.update(overrides)
        return seed_options.verify(**arguments)


class TestTheWritableTargets(SeedFixture):
    """This module writes two filenames, and only if they exist."""

    def test_the_game_written_options_file_is_a_target(self):
        self.write_options()
        self.assertEqual(
            seed_options._validated_target(self.options_json,
                                           self.root),
            self.options_json)

    def test_a_world_options_file_is_a_target(self):
        path = self.write_world("Sunnyside")
        self.assertEqual(
            seed_options._validated_target(path, self.root), path)

    def test_any_other_basename_is_refused(self):
        for name in ("keybindings.json", "sidebar.json", "Makefile",
                     "options.json.bak", "OPTIONS.JSON",
                     "path_info.cpp"):
            with self.subTest(name=name):
                path = self.write_raw(
                    os.path.join(self.config, name), "[]")
                with self.assertRaises(seed_options.SeedError) as bad:
                    seed_options._validated_target(path, self.root)
                self.assertIn("only ever writes", str(bad.exception))

    def test_a_target_that_does_not_exist_yet_is_refused(self):
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options._validated_target(self.options_json, self.root)
        message = str(bad.exception)
        self.assertIn("launch_game.sh", message)
        self.assertIn(
            "never creates one", message,
            msg=("creating the file would mean inventing the info and "
                 "default text the engine owns for every option"))

    def test_a_directory_is_not_a_target(self):
        os.makedirs(os.path.join(self.config, "options.json"))
        with self.assertRaises(seed_options.SeedError):
            seed_options._validated_target(
                os.path.join(self.config, "options.json"), self.root)

    def test_a_relative_path_is_resolved_before_it_is_checked(self):
        self.write_options()
        sneaky = os.path.join(
            self.config, "..", "config", ".", "options.json")
        self.assertEqual(
            seed_options._validated_target(sneaky, self.root),
            self.options_json,
            msg=("the basename check must see the normalised path, or "
                 "a traversal could dress up another file as one of "
                 "the two writable names"))

    def test_the_default_target_is_the_engine_s_own_location(self):
        self.assertEqual(
            seed_options.options_json_path(self.root),
            self.options_json,
            msg=("config_dir_value = user_dir_value + 'config/' and "
                 "options_value = config_dir_value + 'options.json'"))
        # env.sh's export may CONFIRM the location -- which is what
        # keeps one run agreeing with itself across every stage -- but
        # it can no longer MOVE it.  An unexpected value in this
        # variable would otherwise redirect every subsequent write, and
        # this module rewrites the file it opens.
        with _environment(PLAYTHROUGH_OPTIONS_JSON=self.options_json):
            self.assertEqual(
                seed_options.options_json_path(self.root),
                self.options_json,
                msg="the environment agreeing with the derived "
                    "location is the ordinary case and is honoured")
        with _environment(PLAYTHROUGH_OPTIONS_JSON="/tmp/elsewhere.js"):
            with self.assertRaises(seed_options.SeedError) as bad:
                seed_options.options_json_path(self.root)
        self.assertIn("outside", str(bad.exception))


class TestTheEngineDocument(SeedFixture):
    """The file is read and rewritten in the engine's own shape."""

    def test_an_engine_written_file_round_trips_byte_for_byte(self):
        self.write_options()
        original = self.bytes_at()
        entries, pretty = seed_options.load_entries(self.options_json)
        self.assertTrue(pretty)
        self.assertEqual(
            seed_options.serialize_entries(entries, pretty).encode(
                "utf-8"),
            original,
            msg=("reading and rewriting without changing anything must "
                 "be a no-op at the byte level, or every seeded value "
                 "arrives buried in a whole-file reformat"))

    def test_member_order_and_unknown_members_survive(self):
        entries = [self.entry("24_HOUR", "12h", extra_member="kept")]
        text = seed_options.serialize_entries(entries, True)
        loaded, _ = seed_options.load_entries(
            self.write_raw(self.options_json, text))
        self.assertEqual(
            list(loaded[0]),
            ["info", "default", "name", "value", "extra_member"],
            msg=("options_manager::serialize writes info, default, "
                 "name, value in that order, and a member this module "
                 "does not understand is still the engine's"))

    def test_the_pretty_and_compact_layouts_are_distinguished(self):
        entries = [self.entry("24_HOUR", "24h")]
        pretty = seed_options.serialize_entries(entries, True)
        compact = seed_options.serialize_entries(entries, False)
        self.assertTrue(pretty.startswith("[\n  { "))
        self.assertFalse(
            pretty.endswith("\n"),
            msg=("JsonOut writes no trailing newline, so adding one "
                 "would show up as a diff on every run"))
        self.assertEqual(
            compact,
            '[{"info":"what 24_HOUR does","default":"24h",'
            '"name":"24_HOUR","value":"24h"}]',
            msg=("WORLD::save_world_options uses the compact writer, "
                 "so a world file must be rewritten compactly"))
        for text, expected in ((pretty, True), (compact, False)):
            with self.subTest(pretty=expected):
                _, detected = seed_options.load_entries(
                    self.write_raw(self.options_json, text))
                self.assertIs(detected, expected)

    def test_an_empty_array_has_the_engine_s_own_spelling(self):
        self.assertEqual(seed_options.serialize_entries([], True),
                         "[\n]")
        self.assertEqual(seed_options.serialize_entries([], False),
                         "[]")

    def test_the_string_encoder_is_the_engine_s_not_json_dumps(self):
        self.assertEqual(
            seed_options._json_string("a/b"), '"a/b"',
            msg="JsonOut leaves the solidus unescaped")
        self.assertEqual(
            seed_options._json_string("a\x0bb"), '"a\\u000Bb"',
            msg=("the engine emits uppercase hex, where json.dumps "
                 "emits lowercase: %r"
                 % json.dumps("a\x0bb")))
        self.assertEqual(
            seed_options._json_string("caf\u00e9"), '"caf\u00e9"',
            msg=("characters at or above 0x20 are emitted raw, which "
                 "is what lets a UTF-8 tileset name survive"))
        for char, escape in ((chr(8), "\\b"), (chr(12), "\\f"),
                             ("\n", "\\n"), ("\r", "\\r"),
                             ("\t", "\\t"), ('"', '\\"'),
                             ("\\", "\\\\")):
            with self.subTest(char=repr(char)):
                self.assertEqual(
                    seed_options._json_string(char),
                    '"%s"' % escape)

    def test_a_member_the_engine_never_writes_still_round_trips(self):
        self.assertEqual(seed_options._json_member_value(7), "7")
        self.assertEqual(
            seed_options._json_member_value(["a", 1]), '["a",1]')
        self.assertEqual(
            seed_options._json_member_value("caf\u00e9"),
            '"caf\u00e9"')

    def test_a_document_that_cannot_be_believed_is_refused(self):
        cases = (
            ("{not json", "text that is not JSON", "not valid JSON"),
            ('{"24_HOUR": "24h"}', "a name-to-value mapping",
             "JSON array"),
            ("[3]", "an entry that is not an object", "expected an "
             "object"),
            ('[{"name": "24_HOUR"}]', "an entry with no value",
             "lacks 'value'"),
            ('[{"value": "24h"}]', "an entry with no name",
             "lacks 'name'"),
            ('[{"name": 5, "value": "24h"}]', "a non-string name",
             "non-string"),
            ('[{"name": "24_HOUR", "value": 24}]',
             "a non-string value", "non-string"),
        )
        for text, why, expected in cases:
            with self.subTest(case=why):
                self.write_raw(self.options_json, text)
                with self.assertRaises(seed_options.SeedError,
                                       msg=why) as bad:
                    seed_options.load_entries(self.options_json)
                self.assertIn(expected, str(bad.exception))

    def test_an_unreadable_document_is_refused(self):
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options.load_entries(
                os.path.join(self.config, "absent.json"))
        self.assertIn("cannot read", str(bad.exception))


class TestWritingAtomically(SeedFixture):
    """The engine may read this file at any moment."""

    def test_the_content_lands_with_unix_newlines(self):
        path = os.path.join(self.config, "options.json")
        seed_options.write_atomic(path, "[\n  { }\n]")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"[\n  { }\n]")

    def test_no_temporary_file_is_left_behind(self):
        self.write_both_tilesets()
        self.write_options()
        self.patch()
        self.assertEqual(
            sorted(os.listdir(self.config)), ["options.json"],
            msg="a .tmp sibling would be committed with the userdir")

    def test_a_failure_before_the_rename_leaves_the_original(self):
        self.write_options()
        original = self.bytes_at()
        real_replace = os.replace

        def refuse(source, target):
            raise OSError(28, "No space left on device")

        os.replace = refuse
        self.addCleanup(setattr, os, "replace", real_replace)
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options.write_atomic(self.options_json, "[\n]")
        os.replace = real_replace
        self.assertIn("cannot write", str(bad.exception))
        self.assertEqual(
            self.bytes_at(), original,
            msg=("the engine has to be able to read this file at any "
                 "moment, so a failed write must not truncate it"))
        self.assertEqual(
            sorted(os.listdir(self.config)), ["options.json"],
            msg="and the temporary file is cleaned up")

    def test_a_write_into_a_missing_directory_is_refused(self):
        with self.assertRaises(seed_options.SeedError):
            seed_options.write_atomic(
                os.path.join(self.root, "nope", "options.json"), "[]")


class TestDiscoveringTilesets(SeedFixture):
    """An id comes from the NAME: field, never from a directory name."""

    def test_the_name_field_is_the_id_and_the_directory_is_not(self):
        directory = self.write_tileset(MSX_DIR, MSX_IDENT, MSX_VIEW)
        found = seed_options.discover_tilesets(self.root)
        self.assertEqual([item.ident for item in found], [MSX_IDENT])
        self.assertEqual(found[0].view, MSX_VIEW)
        self.assertEqual(found[0].directory, directory)
        self.assertNotEqual(
            found[0].ident, MSX_DIR,
            msg=("gfx/ASCIITileset declares NAME: ASCIITiles, so "
                 "writing the directory name into TILES would select "
                 "nothing"))

    def test_the_view_field_ends_the_scan(self):
        self.write_raw(
            os.path.join(self.gfx, "Pack", "tileset.txt"),
            "NAME: First\nVIEW: Shown\nNAME: Second\n")
        found = seed_options.discover_tilesets(self.root)
        self.assertEqual(
            [item.ident for item in found], ["First"],
            msg=("build_resource_list breaks out of the loop on VIEW, "
                 "so a later NAME is never read"))

    def test_comments_and_blank_lines_are_skipped(self):
        self.write_raw(
            os.path.join(self.gfx, "Pack", "tileset.txt"),
            "\n#NAME: Commented\n\n   \nNAME: Real\n")
        self.assertEqual(
            [item.ident
             for item in seed_options.discover_tilesets(self.root)],
            ["Real"])

    def test_a_pack_with_no_name_field_is_not_a_tileset(self):
        self.write_raw(
            os.path.join(self.gfx, "Pack", "tileset.txt"),
            "VIEW: Nameless\nJSON: tile_config.json\n")
        self.assertEqual(seed_options.discover_tilesets(self.root), [])

    def test_a_pack_with_no_view_field_falls_back_to_its_id(self):
        self.write_tileset("Plain", "PlainId")
        found = seed_options.discover_tilesets(self.root)
        self.assertEqual(found[0].view, "")
        self.assertEqual(
            str(found[0]), "PlainId",
            msg="the engine shows the id when VIEW is absent")

    def test_the_userdir_pack_wins_a_duplicate_id(self):
        user_gfx = os.path.join(
            self.root, "playthrough", "userdir", "gfx")
        first = self.write_tileset("Installed", MSX_IDENT, MSX_VIEW,
                                   base=user_gfx)
        self.write_tileset("Bundled", MSX_IDENT, "Other")
        found = seed_options.discover_tilesets(self.root)
        self.assertEqual(len(found), 1)
        self.assertEqual(
            found[0].directory, first,
            msg=("the engine searches user_gfx() before gfxdir() and "
                 "search_resource keeps the first definition"))

    def test_the_search_is_depth_limited(self):
        self.write_raw(
            os.path.join(self.gfx, "a", "b", "c", "d", "tileset.txt"),
            "NAME: TooDeep\n")
        self.write_tileset("Shallow", "Shallow")
        self.assertEqual(
            [item.ident
             for item in seed_options.discover_tilesets(self.root)],
            ["Shallow"],
            msg=("three levels covers every layout that exists, and "
                 "keeps a mis-pointed root from walking the "
                 "filesystem"))

    def test_the_result_is_sorted_by_id(self):
        self.write_tileset("Zed", "Zulu")
        self.write_tileset("Alpha", "Alfa")
        self.assertEqual(
            [item.ident
             for item in seed_options.discover_tilesets(self.root)],
            ["Alfa", "Zulu"])

    def test_no_gfx_tree_at_all_is_an_empty_list_not_an_error(self):
        self.assertEqual(
            seed_options.discover_tilesets(self.root), [],
            msg=("resolve_tileset is the function that has to fail, "
                 "because it knows what was being looked for"))


class TestResolvingTheTileset(SeedFixture):
    """A TILES value is only ever an id that is genuinely installed."""

    def test_a_request_is_honoured_by_id_or_by_display_name(self):
        self.write_both_tilesets()
        for wanted in (MSX_IDENT, MSX_VIEW):
            with self.subTest(wanted=wanted):
                choice = seed_options.resolve_tileset(
                    root=self.root, requested=wanted)
                self.assertEqual(choice.ident, MSX_IDENT)
                self.assertEqual(choice.origin, "requested")

    def test_a_request_that_is_not_installed_is_refused(self):
        self.write_both_tilesets()
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options.resolve_tileset(root=self.root,
                                         requested="UltimateCataclysm")
        message = str(bad.exception)
        self.assertIn("is not installed", message)
        self.assertIn(
            MSX_IDENT, message,
            msg="the installed ids are named, so the fix is obvious")

    def test_the_launcher_s_own_export_is_treated_as_a_hint(self):
        self.write_both_tilesets()
        with _environment(PLAYTHROUGH_TILESET_RESOLVED=MSX_VIEW):
            choice = seed_options.resolve_tileset(root=self.root)
        self.assertEqual(choice.origin, "requested")
        self.assertEqual(choice.ident, MSX_IDENT)

    def test_a_hint_the_launcher_got_wrong_does_not_win(self):
        self.write_tileset(ASCII_DIR, ASCII_IDENT, ASCII_VIEW)
        with _environment(PLAYTHROUGH_TILESET_RESOLVED=MSX_IDENT):
            with self.assertRaises(seed_options.SeedError):
                seed_options.resolve_tileset(root=self.root)

    def test_the_required_pack_is_found_by_every_name_it_goes_by(self):
        for view in seed_options.TILESET_REQUIRED_ALIASES:
            with self.subTest(alias=view):
                self.setUp()
                self.write_tileset("Pack", "SomeOtherId", view)
                self.write_tileset(ASCII_DIR, ASCII_IDENT)
                choice = seed_options.resolve_tileset(root=self.root)
                self.assertEqual(choice.origin, "required")
                self.assertEqual(choice.ident, "SomeOtherId")

    def test_the_checkout_s_own_pack_is_not_a_fallback(self):
        # THERE IS NO FALLBACK, deliberately.  A run that quietly used
        # the checkout's own ASCIITiles would render a plausible film
        # while failing the requirement to configure MSXotto+, and the
        # only symptom would be the artwork -- so an absent required
        # pack is a refusal, not a substitution.
        self.write_tileset(ASCII_DIR, ASCII_IDENT, ASCII_VIEW)
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options.resolve_tileset(root=self.root)
        message = str(bad.exception)
        self.assertIn("is not installed", message)
        self.assertIn(
            ASCII_IDENT, message,
            msg=("what IS installed is named, so the operator can see "
                 "that the substitution was available and declined"))

    def test_nothing_installed_is_a_hard_failure(self):
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options.resolve_tileset(root=self.root)
        message = str(bad.exception)
        self.assertIn("is not installed", message)
        self.assertIn("(none)", message)
        self.assertIn(
            "never from the directory name", message,
            msg="the message says how ids are actually formed")

    def test_matching_is_literal_equality_and_not_a_pattern(self):
        self.write_tileset("Pack", "MSXotto+", "MSXotto+")
        self.assertIsNone(
            seed_options._match_tileset(
                seed_options.discover_tilesets(self.root),
                "MSXotto."),
            msg=("real ids contain characters such as '+' that a "
                 "regular expression would misread"))
        self.assertIsNotNone(
            seed_options._match_tileset(
                seed_options.discover_tilesets(self.root),
                "MSXotto+"))

    def test_the_required_name_comes_from_env_sh(self):
        self.write_tileset("Pack", "HouseStyle", "House Style")
        with _environment(PLAYTHROUGH_TILESET="House Style"):
            self.assertEqual(
                seed_options.resolve_tileset(root=self.root).origin,
                "required")
        # And NAMING a substitute authorises nothing.  $..._FALLBACK
        # says WHICH tileset a fallback would use; it does not say that
        # one may be used, so on its own it changes nothing and the
        # absent required pack is still a refusal.
        with _environment(PLAYTHROUGH_TILESET="Absent",
                          PLAYTHROUGH_TILESET_FALLBACK="HouseStyle"):
            with self.assertRaises(seed_options.SeedError) as bad:
                seed_options.resolve_tileset(root=self.root)
        self.assertIn("--allow-tileset-fallback", str(bad.exception))

    def test_every_spelling_of_the_pack_resolves_to_it(self):
        """The pack is spelled differently in three places at once.

        The ``NAME:`` id, the ``VIEW:`` label and the directory the
        upstream repository ships are all different strings, and the
        alias list in env.sh is the ONE place that records them -- so
        matching on any one of them finds the same installed pack
        rather than reporting it absent.
        """
        self.write_tileset(MSX_DIR, MSX_IDENT, MSX_VIEW)
        for spelling in (MSX_IDENT, MSX_VIEW, "MShockXotto+"):
            with self.subTest(spelling=spelling):
                with _environment(PLAYTHROUGH_TILESET=spelling):
                    choice = seed_options.resolve_tileset(root=self.root)
                self.assertEqual(choice.origin, "required")
                self.assertEqual(choice.ident, MSX_IDENT)

    def test_the_substitute_has_to_be_asked_for_by_name(self):
        """The one sanctioned way to record another tileset.

        It exists so that somebody debugging the pipeline on a host with
        no pack can still bring the game up, and it announces itself:
        ``origin`` becomes ``fallback`` and the reason says so, which is
        what keeps a diagnostic run from being mistaken for a compliant
        one.
        """
        self.write_tileset(ASCII_DIR, ASCII_IDENT, ASCII_VIEW)
        with _environment(PLAYTHROUGH_TILESET="Absent",
                          PLAYTHROUGH_TILESET_FALLBACK=ASCII_IDENT,
                          PLAYTHROUGH_ALLOW_TILESET_FALLBACK="1"):
            choice = seed_options.resolve_tileset(root=self.root)
        self.assertEqual(choice.origin, "fallback")
        self.assertEqual(choice.ident, ASCII_IDENT)
        self.assertIn("DIAGNOSTIC", choice.reason)
        # The argument is equivalent to the variable, and either way it
        # is off unless it is supplied.
        with _environment(PLAYTHROUGH_TILESET="Absent",
                          PLAYTHROUGH_TILESET_FALLBACK=ASCII_IDENT):
            self.assertEqual(
                seed_options.resolve_tileset(
                    root=self.root, allow_fallback=True).origin,
                "fallback")
            with self.assertRaises(seed_options.SeedError):
                seed_options.resolve_tileset(
                    root=self.root, allow_fallback=False)

    def test_an_allowed_fallback_is_recorded_in_the_report(self):
        """A deviation reaches the notes, not just the log.

        ``playthrough/TECHNICAL_NOTES.md`` quotes the report, so a run
        that did not use the required pack has to say so somewhere the
        write-up will actually pick it up.
        """
        self.write_tileset(ASCII_DIR, ASCII_IDENT, ASCII_VIEW)
        self.write_options()
        with _environment(PLAYTHROUGH_TILESET="Absent",
                          PLAYTHROUGH_TILESET_FALLBACK=ASCII_IDENT,
                          PLAYTHROUGH_ALLOW_TILESET_FALLBACK="1"):
            report = seed_options.patch(root=self.root)
        self.assertEqual(report.tileset.origin, "fallback")
        self.assertTrue(
            any("fallback" in note for note in report.notes),
            msg=f"notes were {report.notes!r}")
        self.assertEqual(self.values()["TILES"], ASCII_IDENT)


class TestPatchingTheFile(SeedFixture):
    """Every required value, and nothing else, in place."""

    def setUp(self):
        super().setUp()
        self.write_both_tilesets()

    def test_every_required_value_is_written(self):
        self.write_options()
        report = self.patch()
        self.assertTrue(report.written)
        stored = self.values()
        for name, value in WANTED.items():
            with self.subTest(option=name):
                self.assertEqual(stored[name], value)
        self.assertEqual(
            stored["TILES"], MSX_IDENT,
            msg="and the tileset that is actually installed")

    def test_the_clock_is_not_a_parameter_of_this_module(self):
        self.write_options()
        self.patch()
        self.assertEqual(self.values()["24_HOUR"], "24h")
        self.assertNotIn(
            "clock_format",
            seed_options.patch.__code__.co_varnames,
            msg=("offering the knob would offer 'military' with it -- "
                 "the one legal value that silently destroys every "
                 "duration in the finished movie"))

    def test_options_the_pipeline_does_not_own_are_untouched(self):
        self.write_options()
        before = self.values()
        self.patch()
        after = self.values()
        for name in ("FONT_SIZE", "PIXEL_MINIMAP", "AUTOSAVE"):
            with self.subTest(option=name):
                self.assertEqual(after[name], before[name])

    def test_the_engine_s_own_annotations_survive(self):
        self.write_options()
        self.patch()
        entries, _ = seed_options.load_entries(self.options_json)
        clock = [entry for entry in entries
                 if entry["name"] == "24_HOUR"][0]
        self.assertEqual(list(clock),
                         ["info", "default", "name", "value"])
        self.assertEqual(
            clock["default"], "12h",
            msg=("only the value member is touched; the engine's "
                 "default annotation is evidence in its own right -- "
                 "the TILES entry's default text is a live inventory "
                 "of what is installed"))

    def test_the_seeded_value_is_a_one_line_diff(self):
        self.write_options()
        before = self.bytes_at().decode("utf-8").splitlines()
        self.patch()
        after = self.bytes_at().decode("utf-8").splitlines()
        self.assertEqual(len(before), len(after))
        differing = [index for index, (old, new)
                     in enumerate(zip(before, after)) if old != new]
        self.assertEqual(
            len(differing), 8,
            msg=("one line per seeded option and no reformatting: %r"
                 % differing))

    def test_a_second_run_is_byte_identical_and_writes_nothing(self):
        self.write_options()
        self.patch()
        first = self.bytes_at()
        report = self.patch()
        self.assertFalse(
            report.written,
            msg="nothing to change means nothing is written")
        self.assertEqual(report.changes, [])
        self.assertEqual(
            sorted(report.already),
            sorted(list(WANTED) + ["TILES"]),
            msg="and every option is reported as already correct")
        self.assertEqual(
            self.bytes_at(), first,
            msg=("byte-level idempotency is the check that catches a "
                 "layout drift a value comparison would miss"))

    def test_every_occurrence_of_a_duplicated_option_is_patched(self):
        entries = self.engine_entries()
        entries.append(self.entry("24_HOUR", "12h"))
        self.write_options(entries=entries)
        report = self.patch()
        stored, _ = seed_options.load_entries(self.options_json)
        clocks = [str(entry["value"]) for entry in stored
                  if entry["name"] == "24_HOUR"]
        self.assertEqual(
            clocks, ["24h", "24h"],
            msg=("options_manager::deserialize applies the array in "
                 "order, so a later duplicate would win on load"))
        self.assertTrue(
            any("appears 2 times" in note for note in report.notes),
            msg="and the duplicate is reported: %r" % report.notes)

    def test_an_option_the_engine_should_have_written_is_not_invented(self):
        entries = [entry for entry in self.engine_entries()
                   if entry["name"] != "SOUND_ENABLED"]
        self.write_options(entries=entries)
        before = self.bytes_at()
        with self.assertRaises(seed_options.SeedError) as bad:
            self.patch()
        self.assertIn("will not invent an entry", str(bad.exception))
        self.assertEqual(
            self.bytes_at(), before,
            msg="and the file is left exactly as it was")

    def test_an_unresolvable_tileset_leaves_the_file_untouched(self):
        shutil.rmtree(self.gfx)
        self.write_options()
        before = self.bytes_at()
        with self.assertRaises(seed_options.SeedError):
            self.patch()
        self.assertEqual(
            self.bytes_at(), before,
            msg=("the tileset is resolved before anything is mutated, "
                 "precisely so that this is true"))

    def test_tileset_resolution_can_be_declined_entirely(self):
        self.write_options()
        report = self.patch(resolve_tiles=False)
        self.assertIsNone(report.tileset)
        self.assertEqual(
            self.values()["TILES"], "UltimateCataclysm",
            msg=("--no-tileset leaves TILES exactly as the engine "
                 "wrote it, for patching a copy away from a gfx tree"))

    def test_declining_resolution_while_requesting_one_is_refused(self):
        self.write_options()
        with self.assertRaises(seed_options.SeedError) as bad:
            self.patch(resolve_tiles=False, tileset=MSX_IDENT)
        self.assertIn("drop one of the two", str(bad.exception))

    def test_a_dry_run_computes_everything_and_writes_nothing(self):
        self.write_options()
        before = self.bytes_at()
        report = self.patch(dry_run=True)
        self.assertFalse(report.written)
        self.assertEqual(len(report.changes), 8)
        self.assertEqual(self.bytes_at(), before)
        self.assertTrue(
            any("dry run" in note for note in report.notes))

    def test_the_terminal_dimensions_are_range_checked(self):
        self.write_options()
        for kwargs in ({"terminal_x": 79}, {"terminal_x": 961},
                       {"terminal_y": 23}, {"terminal_y": 271}):
            with self.subTest(**kwargs):
                with self.assertRaises(seed_options.SeedError):
                    self.patch(**kwargs)
        report = self.patch(terminal_x=960, terminal_y=270)
        self.assertTrue(report.written)
        self.assertEqual(self.values()["TERMINAL_X"], "960")

    def test_a_pool_setting_that_is_not_point_buy_is_warned_about(self):
        self.write_options()
        report = self.patch(point_pools="story_teller")
        self.assertEqual(self.values()["CHARACTER_POINT_POOLS"],
                         "story_teller")
        self.assertTrue(
            any("does NOT enable point-buy" in note
                for note in report.notes),
            msg=("the creator's pool tab is read-only for it, and the "
                 "run is meant to go through the point-buy creator"))

    def test_a_pool_setting_the_engine_would_reject_is_refused(self):
        self.write_options()
        with self.assertRaises(seed_options.SeedError):
            self.patch(point_pools="freeform")

    def test_world_compression_is_settable_both_ways(self):
        self.write_options()
        self.patch(world_compression=True)
        self.assertEqual(self.values()["WORLD_COMPRESSION2"], "true")
        self.patch(world_compression=False)
        self.assertEqual(self.values()["WORLD_COMPRESSION2"], "false")

    def test_a_compact_file_is_rewritten_compactly(self):
        self.write_options(pretty=False)
        self.patch()
        text = self.bytes_at().decode("utf-8")
        self.assertTrue(text.startswith('[{"'))
        self.assertNotIn(
            "\n", text,
            msg="the layout the file used is the layout it keeps")

    def test_an_unknown_worlds_mode_is_refused(self):
        self.write_options()
        with self.assertRaises(seed_options.SeedError) as bad:
            self.patch(worlds="rewrite")
        self.assertIn("unknown worlds mode", str(bad.exception))

    def test_the_report_explains_itself(self):
        self.write_options()
        text = self.patch().describe()
        for expected in ("seed_options report", "options file",
                         "tileset origin", "changed", "why:",
                         "24_HOUR"):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)


class TestConfirmingTheWrite(SeedFixture):
    """A change that did not take effect is never reported as one."""

    def test_a_value_that_did_not_land_is_a_hard_failure(self):
        self.write_options({"24_HOUR": "12h"})
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options._confirm_written(
                self.options_json, [("24_HOUR", "24h")],
                root=self.root)
        self.assertIn("did not take effect", str(bad.exception))

    def test_the_military_trap_is_named_when_it_is_at_fault(self):
        self.write_options({"24_HOUR": "military"})
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options._confirm_written(
                self.options_json, [("24_HOUR", "24h")],
                root=self.root)
        message = str(bad.exception)
        self.assertIn("0815.32", message)
        self.assertIn(
            "clock regex cannot match", message,
            msg=("naming the consequence is what stops somebody "
                 "'fixing' this by relaxing the regex"))

    def test_a_write_that_did_land_confirms_silently(self):
        self.write_options({"24_HOUR": "24h"})
        self.assertIsNone(
            seed_options._confirm_written(
                self.options_json, [("24_HOUR", "24h")],
                root=self.root))


class TestTheWorldOptions(SeedFixture):
    """A world already on disk is reported, not reshaped."""

    def setUp(self):
        super().setUp()
        self.write_both_tilesets()
        self.write_options()

    def test_no_world_yet_means_the_global_default_is_enough(self):
        report = self.patch()
        self.assertTrue(
            any("no world exists yet" in note
                for note in report.notes),
            msg=("a world captures the global world defaults when it "
                 "is created, so seeding options.json is sufficient"))

    def test_an_existing_world_is_left_untouched_by_default(self):
        path = self.write_world("Sunnyside", "any")
        before = self.bytes_at(path)
        report = self.patch()
        self.assertEqual(
            self.bytes_at(path), before,
            msg="a run that finds a save resumes it, not reshapes it")
        self.assertEqual(report.world_changes, [])
        self.assertTrue(
            any("left untouched" in note for note in report.notes))

    def test_an_empty_world_without_point_buy_is_patched(self):
        """A world with nobody in it is where this survivor is created.

        THE DEFECT THIS PINS.  `auto` used to leave such a world at
        'story_teller' with a warning, on the reasoning that an existing
        world is a save to resume.  A world holding NO character save is
        not: this session creates its survivor inside it, and the world's
        own worldoptions.json is what the creator obeys
        [src/worldfactory.cpp:2021-2035] -- so the pool tab could be
        read-only while the global option said otherwise and every check
        passed.
        """
        world = self.write_world("Grimly", "story_teller")
        report = self.patch()
        self.assertTrue(
            any("holds no character save" in note
                for note in report.notes),
            msg=repr(report.notes))
        self.assertEqual(
            seed_options.effective_point_pools(world), "any",
            msg="the world the survivor will be created in is patched")

    def test_a_world_with_a_survivor_in_it_is_left_alone(self):
        """An existing survivor's rules are not rewritten behind them."""
        world = self.write_world("Occupied", "story_teller")
        with open(os.path.join(os.path.dirname(world), "#QQ==.sav"),
                  "w", encoding="utf-8") as handle:
            handle.write("{}")
        report = self.patch()
        self.assertTrue(
            any("character save(s), so its rules" in note
                for note in report.notes),
            msg=repr(report.notes))
        self.assertEqual(
            seed_options.effective_point_pools(world), "story_teller",
            msg="a resumed world is continued, never reshaped")

    def test_a_resumed_run_does_not_patch_an_empty_world(self):
        """`resume` means resume: nothing is rewritten under it."""
        world = self.write_world("Emptied", "story_teller")
        with _environment(PLAYTHROUGH_SESSION_MODE="resume"):
            report = self.patch()
        self.assertEqual(
            seed_options.effective_point_pools(world), "story_teller",
            msg=repr(report.notes))

    def test_a_resumed_session_says_so_in_the_note(self):
        self.write_world("Sunnyside", "any")
        with _environment(PLAYTHROUGH_SESSION_MODE="resume"):
            report = self.patch()
        self.assertTrue(
            any("PLAYTHROUGH_SESSION_MODE=resume" in note
                for note in report.notes),
            msg=repr(report.notes))

    def test_the_effective_world_value_is_the_last_occurrence(self):
        # A duplicated entry could produce exactly the wrong answer in
        # either direction, so both directions are pinned.
        self.write_world("Late", occurrences=["story_teller", "any"])
        report = self.patch()
        self.assertFalse(
            any("read-only" in note for note in report.notes),
            msg=("the effective value is 'any', so warning about a "
                 "read-only pool tab would be spurious: %r"
                 % report.notes))
        self.assertTrue(
            any("the effective value is the last one" in note
                for note in report.notes))

    def test_a_trailing_duplicate_that_disables_point_buy_warns(self):
        self.write_world("Early", occurrences=["any", "story_teller"])
        report = self.patch()
        self.assertTrue(
            any("read-only" in note for note in report.notes),
            msg=("reading the first occurrence would report the value "
                 "the engine discards: %r" % report.notes))

    def test_a_world_can_be_patched_on_explicit_request(self):
        path = self.write_world("Grimly", "story_teller")
        report = self.patch(worlds="patch")
        self.assertEqual(len(report.world_changes), 1)
        self.assertEqual(report.world_changes[0].after, "any")
        entries, _ = seed_options.load_entries(path)
        pools = [str(entry["value"]) for entry in entries
                 if entry["name"] == "CHARACTER_POINT_POOLS"]
        self.assertEqual(pools, ["any"])

    def _survivor(self, world, name="#RGVscGhpbmU=", suffix=".sav"):
        """Write a character save into an existing world directory."""
        target = os.path.join(self.saves, world, name + suffix)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{}")
        return target

    def test_a_world_with_a_survivor_may_not_be_patched(self):
        # The hard rule: an existing save is CONTINUED, never reshaped.
        # Rewriting the point pool would change the rules the character
        # was created under, behind the back of a resumed session.
        path = self.write_world("Grimly", "story_teller")
        self._survivor("Grimly")
        before = self.bytes_at(path)
        with self.assertRaises(seed_options.SeedError) as bad:
            self.patch(worlds="patch")
        self.assertIn("character save", str(bad.exception))
        self.assertEqual(self.bytes_at(path), before)

    def test_a_compressed_survivor_counts_too(self):
        # WORLD_COMPRESSION2 defaults to true, so counting only "*.sav"
        # would report an empty world and patch a real survivor's rules.
        path = self.write_world("Grimly", "story_teller")
        self._survivor("Grimly", suffix=".sav.zzip")
        before = self.bytes_at(path)
        with self.assertRaises(seed_options.SeedError):
            self.patch(worlds="patch")
        self.assertEqual(self.bytes_at(path), before)

    def test_both_forms_of_one_survivor_count_once(self):
        self.write_world("Grimly", "story_teller")
        self._survivor("Grimly")
        self._survivor("Grimly", suffix=".sav.zzip")
        self.assertEqual(
            seed_options.character_saves_in(
                os.path.join(self.saves, "Grimly")),
            ["#RGVscGhpbmU=.sav"])

    def test_a_symlinked_survivor_is_refused_not_counted(self):
        self.write_world("Grimly", "story_teller")
        outside = os.path.join(self.root, "somebody-elses.sav")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.symlink(
            outside, os.path.join(self.saves, "Grimly", "#QQ==.sav"))
        with self.assertRaises(seed_options.SeedError) as bad:
            seed_options.character_saves_in(
                os.path.join(self.saves, "Grimly"))
        self.assertIn("symbolic link", str(bad.exception))

    def test_a_resumed_session_may_not_patch_a_world_at_all(self):
        # Even an empty world: the declaration alone is enough, because
        # a resumed session does not reshape what it resumed.
        path = self.write_world("Grimly", "story_teller")
        before = self.bytes_at(path)
        with _environment(PLAYTHROUGH_SESSION_MODE="resume"):
            with self.assertRaises(seed_options.SeedError) as bad:
                self.patch(worlds="patch")
        self.assertIn("resume", str(bad.exception))
        self.assertEqual(self.bytes_at(path), before)

    def test_an_interrupted_creation_may_still_be_patched(self):
        # A world with NO character save is the case the mode exists
        # for, and it must keep working.
        path = self.write_world("Halfway", "story_teller")
        report = self.patch(worlds="patch")
        self.assertEqual(len(report.world_changes), 1)
        entries, _ = seed_options.load_entries(path)
        pools = [str(entry["value"]) for entry in entries
                 if entry["name"] == "CHARACTER_POINT_POOLS"]
        self.assertEqual(pools, ["any"])

    def test_patching_a_world_that_has_no_such_option_is_refused(self):
        holder = os.path.join(self.saves, "Bare")
        os.makedirs(holder)
        self.write_raw(
            os.path.join(holder, "worldoptions.json"),
            seed_options.serialize_entries(
                [self.entry("CITY_SIZE", "8")], True))
        with self.assertRaises(seed_options.SeedError) as bad:
            self.patch(worlds="patch")
        self.assertIn("cannot take effect", str(bad.exception))

    def test_a_dry_run_does_not_write_a_world_either(self):
        path = self.write_world("Grimly", "story_teller")
        before = self.bytes_at(path)
        report = self.patch(worlds="patch", dry_run=True)
        self.assertEqual(self.bytes_at(path), before)
        self.assertTrue(
            any("would change" in note for note in report.notes))

    def test_worlds_can_be_ignored_entirely(self):
        self.write_world("Grimly", "story_teller")
        report = self.patch(worlds="skip")
        self.assertTrue(
            any("--worlds skip" in note for note in report.notes))
        self.assertFalse(
            any("read-only" in note for note in report.notes))

    def test_every_world_is_found_in_a_stable_order(self):
        self.write_world("Bravo")
        self.write_world("Alpha")
        self.assertEqual(
            [os.path.basename(os.path.dirname(path))
             for path in seed_options.world_options_paths(self.root)],
            ["Alpha", "Bravo"])


class TestReadingTheStoredValues(SeedFixture):
    """Observation only: nothing asserted, nothing written."""

    def test_only_the_seeded_options_are_reported(self):
        self.write_options()
        observed = seed_options.read_values(
            self.options_json, root=self.root)
        self.assertEqual(set(observed),
                         set(seed_options.SEEDED_OPTIONS))
        self.assertNotIn(
            "AUTOSAVE", observed,
            msg="reporting options the pipeline does not own would "
                "invite editing them")

    def test_an_absent_option_is_absent_rather_than_defaulted(self):
        entries = [entry for entry in self.engine_entries()
                   if entry["name"] != "TILES"]
        self.write_options(entries=entries)
        self.assertNotIn(
            "TILES",
            seed_options.read_values(self.options_json, root=self.root),
            msg=("the engine's compiled default is not what the file "
                 "says, and claiming it would be a fabrication"))

    def test_a_duplicated_option_reports_the_value_the_engine_uses(self):
        entries = self.engine_entries()
        entries.append(self.entry("24_HOUR", "military"))
        self.write_options(entries=entries)
        self.assertEqual(
            seed_options.read_values(self.options_json,
                                     root=self.root)["24_HOUR"],
            "military",
            msg=("the engine applies the array in order, so the last "
                 "occurrence is the one it runs with"))


class TestTheRenderGeometryOptions(SeedFixture):
    """The six values that decide the window, not just the grid.

    A review found the seeded set covering TERMINAL_X and TERMINAL_Y --
    the GRID -- while the WINDOW that grid becomes, and therefore the
    rectangle the sidebar clock is cropped out of, also depends on the
    font cell size, the fullscreen mode, the scaling pair and which side
    the sidebar is on.  Every one of them could be wrong with all eight
    original values right, and nothing would have said so.
    """

    GEOMETRY = ("FONT_WIDTH", "FONT_HEIGHT", "SIDEBAR_POSITION",
                "FULLSCREEN", "SCALING_MODE", "SCALING_FACTOR")
    WRONG = {
        "FONT_WIDTH": "12",
        "FONT_HEIGHT": "24",
        "SIDEBAR_POSITION": "left",
        "FULLSCREEN": "maximized",
        "SCALING_MODE": "linear",
        "SCALING_FACTOR": "2",
    }

    def setUp(self):
        super().setUp()
        self.write_both_tilesets()

    def test_every_geometry_option_is_in_the_seeded_set(self):
        for name in self.GEOMETRY:
            with self.subTest(option=name):
                self.assertIn(name, seed_options.SEEDED_OPTIONS)

    def test_a_wrong_geometry_file_is_corrected_in_one_pass(self):
        self.write_options(self.WRONG)
        report = self.patch()
        changed = {change.name for change in report.changes}
        for name in self.GEOMETRY:
            with self.subTest(option=name):
                self.assertIn(name, changed)
        stored = self.values()
        for name in self.GEOMETRY:
            with self.subTest(option=name):
                self.assertEqual(stored[name], WANTED[name])

    def test_every_wrong_geometry_value_is_reported_together(self):
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        values.update(self.WRONG)
        self.write_options(values)
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        message = str(bad.exception)
        for name in self.GEOMETRY:
            with self.subTest(option=name):
                self.assertIn(name, message)

    def test_each_geometry_reason_cites_the_engine(self):
        for name in self.GEOMETRY:
            with self.subTest(option=name):
                self.assertIn("src/", seed_options.REASONS[name])

    def test_the_default_sidebar_layout_verifies(self):
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        self.write_options(values)
        observed = self.verify()
        self.assertEqual(observed["SIDEBAR_POSITION"], "right")

    def test_another_resolvable_clock_bearing_layout_verifies(self):
        """A persisted alternate preset is not a misconfiguration.

        THE DEFECT THIS PINS.  verify() used to require the layout id to
        be DEFAULT_LAYOUT_ID and refused every other persisted preset --
        although sidebar_geometry resolves any of the shipped ones to its
        own width and computes the crop from that.  An existing save that
        had persisted one of them could not be continued at all.  What is
        required is that the layout RESOLVE to a crop and DRAW THE CLOCK,
        and this is the case that proves the first requirement no longer
        rejects a name.
        """
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        self.write_options(values)
        self.write_sidebar_widgets(layout_id="an_alternate_preset",
                                   width=36)
        panels = os.path.join(self.config, "panel_options.json")
        with open(panels, "w", encoding="utf-8") as handle:
            json.dump([{"current_layout_id": "an_alternate_preset",
                        "layouts": []}], handle)
        observed = self.verify()
        self.assertEqual(observed["SIDEBAR_POSITION"], "right")

    def test_a_layout_that_draws_no_clock_is_refused(self):
        """A valid crop over a column with no time in it is useless.

        The clock is the sole authority for every duration in the film,
        so a layout that resolves perfectly and simply does not show the
        time would send every duration to the 0.25 s floor and make the
        pacing fiction.  That is what is checked, instead of a name.
        """
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        self.write_options(values)
        self.write_sidebar_widgets(clock=False)
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        self.assertIn("draws no clock", str(bad.exception))
        self.assertIn("time_text", str(bad.exception))

    def test_a_layout_whose_crop_cannot_be_computed_is_refused(self):
        """An unresolvable layout is refused by computation, not by id."""
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        self.write_options(values)
        os.unlink(os.path.join(self.root, "data", "json", "ui",
                               "sidebar.json"))
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        self.assertIn("does not resolve to a crop", str(bad.exception))

    def test_the_clock_variables_agree_with_the_geometry_module(self):
        """Two lists of the same two engine variables must not drift."""
        self.assertEqual(tuple(seed_options.CLOCK_VARS),
                         tuple(sidebar_geometry.CLOCK_WIDGET_VARS))

    def test_an_unreadable_layout_file_is_a_failure_not_a_default(self):
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        self.write_options(values)
        panels = os.path.join(self.config, "panel_options.json")
        with open(panels, "w", encoding="utf-8") as handle:
            handle.write("{ not json at all\n")
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        self.assertIn("sidebar layout", str(bad.exception))


class TestVerifying(SeedFixture):
    """The acceptance gate, one failure class at a time."""

    def setUp(self):
        super().setUp()
        self.write_both_tilesets()

    def seeded(self, overrides=None):
        """Write a file that already holds every seeded value."""
        values = dict(WANTED)
        values["TILES"] = MSX_IDENT
        if overrides:
            values.update(overrides)
        return self.write_options(values)

    def test_a_correctly_seeded_file_verifies(self):
        self.seeded()
        observed = self.verify()
        self.assertEqual(observed["24_HOUR"], "24h")
        self.assertEqual(observed["TILES"], MSX_IDENT)

    def test_the_military_clock_is_named_as_legal_and_fatal(self):
        self.seeded({"24_HOUR": "military"})
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        message = str(bad.exception)
        self.assertIn("0815.32", message)
        self.assertIn(
            "pacing would be fiction", message,
            msg=("the failure has to explain why a legal value is "
                 "fatal, or somebody will set it back"))

    def test_each_wrong_value_is_reported(self):
        cases = (
            ({"24_HOUR": "12h"}, "expected '24h'"),
            ({"SOUND_ENABLED": "true"}, "SOUND_ENABLED"),
            ({"USE_TILES": "false"}, "TILES is inert without it"),
            ({"WORLD_COMPRESSION2": "true"}, "WORLD_COMPRESSION2"),
            ({"TERMINAL_X": "80"}, "TERMINAL_X"),
            ({"TERMINAL_Y": "24"}, "TERMINAL_Y"),
            ({"CHARACTER_POINT_POOLS": "multi_pool"},
             "CHARACTER_POINT_POOLS"),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                self.seeded(overrides)
                with self.assertRaises(seed_options.SeedError) as bad:
                    self.verify()
                self.assertIn(expected, str(bad.exception))

    def test_every_seeded_option_is_reported_when_it_is_absent(self):
        # One subtest per name in SEEDED_OPTIONS, so the absence branch
        # is exercised for each of the eight rather than for one of
        # them with the rest assumed to follow.
        for name in seed_options.SEEDED_OPTIONS:
            with self.subTest(option=name):
                entries = [entry for entry in self.engine_entries()
                           if entry["name"] != name]
                self.write_options(entries=entries)
                with self.assertRaises(seed_options.SeedError) as bad:
                    self.verify()
                self.assertIn("%s is absent" % name,
                              str(bad.exception))

    def test_a_pool_value_that_disables_point_buy_is_reported(self):
        self.seeded({"CHARACTER_POINT_POOLS": "story_teller"})
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify(point_pools="story_teller")
        self.assertIn(
            "which disables point-buy", str(bad.exception),
            msg=("asking for it explicitly still fails the gate, "
                 "because the run must go through the point-buy "
                 "creator"))

    def test_a_terminal_value_outside_the_engine_s_range_is_reported(self):
        self.seeded({"TERMINAL_X": "1000"})
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify(terminal_x=1000)
        self.assertIn("outside the engine's range",
                      str(bad.exception))

    def test_a_terminal_value_that_is_not_a_number_is_reported(self):
        self.seeded({"TERMINAL_X": "wide"})
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify(terminal_x="wide")
        self.assertIn("not an integer", str(bad.exception))

    def test_a_tileset_that_is_not_installed_is_reported(self):
        self.seeded({"TILES": "UltimateCataclysm"})
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        self.assertIn("is not installed", str(bad.exception))

    def test_the_installed_check_can_be_waived_off_the_host(self):
        self.seeded({"TILES": "UltimateCataclysm"})
        observed = self.verify(require_installed=False)
        self.assertEqual(
            observed["TILES"], "UltimateCataclysm",
            msg="for verifying a copy of the file away from a gfx "
                "tree")

    def test_an_explicit_tileset_must_match_exactly(self):
        self.seeded()
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify(tileset=ASCII_IDENT)
        self.assertIn("expected 'ASCIITiles'", str(bad.exception))

    def test_every_problem_is_reported_in_one_run(self):
        self.seeded({"24_HOUR": "12h", "SOUND_ENABLED": "true",
                     "TERMINAL_X": "80"})
        with self.assertRaises(seed_options.SeedError) as bad:
            self.verify()
        bullets = str(bad.exception).count("\n  - ")
        self.assertEqual(
            bullets, 3,
            msg=("one run reports all of them rather than one at a "
                 "time, so a misconfiguration is fixed in one pass"))


class TestTheCommandLine(SeedFixture):
    """stdout is KEY=value lines; every diagnostic goes to stderr."""

    def setUp(self):
        super().setUp()
        self.write_both_tilesets()
        self.write_options()
        self.addCleanup(self.reset_log)

    def reset_log(self):
        """Undo the CLI's handler installation."""
        for handler in list(seed_options.LOG.handlers):
            seed_options.LOG.removeHandler(handler)
        seed_options.LOG.addHandler(logging.NullHandler())
        seed_options.LOG.propagate = False

    def run_main(self, *argv):
        """Call main(argv) and return (status, stdout, stderr)."""
        out = io.StringIO()
        err = io.StringIO()
        base = ["--options-json", self.options_json,
                "--repo-root", self.root]
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            status = seed_options.main(base + list(argv))
        return status, out.getvalue(), err.getvalue()

    def test_stdout_carries_only_key_value_lines(self):
        status, out, _ = self.run_main()
        self.assertEqual(status, 0)
        for line in out.splitlines():
            with self.subTest(line=line):
                self.assertRegex(line, r"^[A-Z0-9_]+=.*$")
        keys = [line.split("=", 1)[0] for line in out.splitlines()]
        for expected in ("PLAYTHROUGH_OPTIONS_JSON",
                         "PLAYTHROUGH_OPTIONS_WRITTEN",
                         "PLAYTHROUGH_OPTIONS_CHANGED",
                         "PLAYTHROUGH_WORLD_OPTIONS_CHANGED",
                         "PLAYTHROUGH_TILESET_SEEDED",
                         "PLAYTHROUGH_TILESET_SEEDED_VIEW",
                         "PLAYTHROUGH_TILESET_SEEDED_ORIGIN",
                         "PLAYTHROUGH_SEEDED_24_HOUR",
                         "PLAYTHROUGH_SEEDED_TILES",
                         "PLAYTHROUGH_SEEDED_TERMINAL_X",
                         "PLAYTHROUGH_SEEDED_TERMINAL_Y"):
            with self.subTest(key=expected):
                self.assertIn(expected, keys)

    def test_the_emitted_values_are_the_ones_on_disk(self):
        _, out, _ = self.run_main()
        emitted = dict(line.split("=", 1)
                       for line in out.splitlines())
        self.assertEqual(emitted["PLAYTHROUGH_SEEDED_24_HOUR"], "24h")
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_SEEDED"],
                         MSX_IDENT)
        self.assertEqual(emitted["PLAYTHROUGH_TILESET_SEEDED_VIEW"],
                         MSX_VIEW)
        self.assertEqual(emitted["PLAYTHROUGH_OPTIONS_WRITTEN"], "1")
        self.assertEqual(emitted["PLAYTHROUGH_OPTIONS_CHANGED"], "8")

    def test_a_second_run_reports_that_it_wrote_nothing(self):
        self.run_main()
        _, out, _ = self.run_main()
        emitted = dict(line.split("=", 1)
                       for line in out.splitlines())
        self.assertEqual(emitted["PLAYTHROUGH_OPTIONS_WRITTEN"], "0")
        self.assertEqual(emitted["PLAYTHROUGH_OPTIONS_CHANGED"], "0")

    def test_verify_only_writes_nothing_and_still_reports(self):
        self.run_main()
        before = self.bytes_at()
        status, out, _ = self.run_main("--verify-only")
        self.assertEqual(status, 0)
        self.assertEqual(self.bytes_at(), before)
        self.assertIn("PLAYTHROUGH_SEEDED_24_HOUR=24h", out)

    def test_verify_only_fails_loudly_on_an_unseeded_file(self):
        status, out, err = self.run_main("--verify-only")
        self.assertEqual(status, 1)
        self.assertEqual(
            out, "",
            msg="a caller reading stdout must not see half an answer")
        self.assertIn("does not hold the seeded values", err)

    def test_a_dry_run_reports_the_file_as_it_actually_is(self):
        before = self.bytes_at()
        status, out, _ = self.run_main("--dry-run")
        self.assertEqual(status, 0)
        self.assertEqual(self.bytes_at(), before)
        emitted = dict(line.split("=", 1)
                       for line in out.splitlines())
        self.assertEqual(
            emitted["PLAYTHROUGH_SEEDED_24_HOUR"], "12h",
            msg=("a dry run must not assert values it deliberately "
                 "did not write"))
        self.assertEqual(emitted["PLAYTHROUGH_OPTIONS_CHANGED"], "8")

    def test_explain_writes_the_report_to_stderr(self):
        status, out, err = self.run_main("--explain")
        self.assertEqual(status, 0)
        self.assertIn("seed_options report", err)
        self.assertNotIn("seed_options report", out)

    def test_verify_only_and_dry_run_together_are_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_main("--verify-only", "--dry-run")
        self.assertEqual(caught.exception.code, 2)

    def test_the_pool_choices_exclude_the_one_that_kills_point_buy(self):
        parser = seed_options.build_parser()
        for action in parser._actions:
            if action.dest == "point_pools":
                self.assertEqual(
                    list(action.choices),
                    list(seed_options.POINT_POOLS_POINT_BUY))
                self.assertNotIn("story_teller", action.choices)
                break
        else:  # pragma: no cover - the option exists
            self.fail("--point-pools must exist")

    def test_an_unknown_switch_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_main("--force")
        self.assertEqual(caught.exception.code, 2)

    def test_the_defaults_are_the_pipeline_s_values(self):
        args = seed_options.build_parser().parse_args([])
        self.assertEqual(args.terminal_x, 240)
        self.assertEqual(args.terminal_y, 67)
        self.assertEqual(args.point_pools, "any")
        self.assertFalse(args.world_compression)
        self.assertEqual(args.worlds, "auto")
        self.assertFalse(args.verify_only)
        self.assertFalse(args.dry_run)

    def test_a_failure_exits_one_rather_than_raising(self):
        os.unlink(self.options_json)
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertIn("no options file at", err)

    def test_there_is_no_command_line_way_to_skip_the_tileset(self):
        """``--no-tileset`` was a production bypass, and it is gone.

        It dropped TILES out of the plan -- eight decided values became
        seven -- and it turned off the verifier's installed-tileset
        check, so a run could report complete success with the wrong
        artwork left in place.  Every other gate still passed, which is
        what made it worse than no check at all.
        """
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_main("--no-tileset")
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(
            "resolve_tiles",
            seed_options.build_parser().parse_args([]).__dict__,
            msg="no argparse dest may reach the relaxed behaviour")

    def test_the_capability_survives_as_a_call_site_parameter(self):
        """A caller holding these rules against a copy may still skip.

        ``patch(resolve_tiles=False)`` is for a host with no ``gfx/``
        tree at all.  It is reachable from Python and from nowhere else,
        which is the whole distinction: a pipeline stage runs a command
        line, and no command line can produce it.
        """
        report = seed_options.patch(root=self.root, resolve_tiles=False)
        self.assertIsNone(report.tileset)
        self.assertEqual(self.values()["TILES"], "UltimateCataclysm")
        self.assertNotIn(
            "TILES", [change.name for change in report.changes])


class TestTheCropSeamWithSidebarGeometry(SeedFixture):
    """The terminal this module writes is the crop's own arithmetic.

    These two modules never call each other, and that is exactly why
    the seam needs a test: seed_options decides TERMINAL_X and
    TERMINAL_Y, sidebar_geometry derives the OCR rectangle from them,
    and a disagreement between the two produces a crop that is
    perfectly well-formed and points at the wrong pixels.
    """

    def setUp(self):
        super().setUp()
        self.write_both_tilesets()
        self.write_options()
        self.ui = os.path.join(self.root, "data", "json", "ui")
        with open(os.path.join(self.ui, "sidebar.json"), "w",
                  encoding="utf-8") as handle:
            json.dump([{"id": "legacy_labels_sidebar",
                        "style": "sidebar", "width": 44}], handle)

    def crop(self):
        """The crop derived from the fixture's own options file."""
        return sidebar_geometry.compute_sidebar_geometry(
            repo_root_dir=self.root,
            options_json=self.options_json,
            panel_options_json=os.path.join(
                self.config, "panel_options.json"),
            screen_width=1920, screen_height=1080)

    def test_before_seeding_the_crop_is_the_first_launch_window(self):
        self.assertEqual(
            self.crop().geometry, "352x384+928+348",
            msg=("a fresh options file holds the engine's own 80x24 "
                 "first-launch terminal, which is a 640x384 window "
                 "centred in the root -- not the capture geometry"))

    def test_after_seeding_the_crop_is_the_capture_rectangle(self):
        self.patch()
        result = self.crop()
        self.assertEqual(
            result.geometry, "352x1072+1568+4",
            msg=("240x8 by 67x16 is 1920x1072 at the 4 px letterbox, "
                 "and 44 cells x 8 px is a 352 px sidebar"))
        self.assertEqual(result.terminal_x, 240)
        self.assertEqual(result.terminal_y, 67)

    def test_a_different_seeded_terminal_moves_the_crop_with_it(self):
        self.patch(terminal_x=160, terminal_y=50)
        result = self.crop()
        self.assertEqual(
            result.geometry, "352x800+1248+140",
            msg=("the coupling is real, and it is the WINDOW the "
                 "sidebar is aligned to, not the root: 160x8 = 1280 "
                 "wide and 50x16 = 800 tall, centred at +320+140, so "
                 "a 352 px sidebar on its right edge starts at "
                 "320 + 1280 - 352 = 1248"))

    def test_the_seeded_clock_is_the_format_the_crop_is_read_for(self):
        self.patch()
        self.assertEqual(
            seed_options.read_values(self.options_json,
                                     root=self.root)["24_HOUR"],
            "24h",
            msg=("a fixed-width %02d:%02d:%02d reading is the only "
                 "thing the OCR regex over this rectangle can match"))


class TestTheSuiteTouchesNoEvidence(SeedFixture):
    """The captured run's own artifacts are never written by a test."""

    def test_the_repository_options_file_is_untouched(self):
        self.assertEqual(
            _snapshot(_REAL_OPTIONS), _REAL_SNAPSHOT,
            msg=("every test works inside a temporary checkout; the "
                 "committed userdir is evidence, not a fixture"))

    def test_the_default_paths_point_into_the_repository(self):
        real_root = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", ".."))
        self.assertEqual(
            seed_options.options_json_path(),
            os.path.join(real_root, "playthrough", "userdir",
                         "config", "options.json"),
            msg=("the default is asserted and then deliberately not "
                 "used, which is the only way to know the fixture "
                 "paths were doing the work"))


class TestTheWriteIsExclusive(SeedFixture):
    """A seed that a live engine would undo is not a seed.

    The engine holds its options IN MEMORY and writes them back when it
    exits, so a value written underneath a running instance is silently
    overwritten afterwards -- and the run that wrote it has already
    reported success.  That failure is invisible at the time and costs a
    whole captured session, so the write refuses while an authenticated
    engine is using this userdir, and it holds the SAME lock name
    launch_game.sh takes so a launch cannot interleave with it.
    """

    def setUp(self):
        super().setUp()
        self.write_options()
        self.write_both_tilesets()
        self.runtime = os.path.join(self.root, "runtime")
        os.makedirs(self.runtime, mode=0o700)

    def _engine(self):
        """Start a stand-in engine with this checkout's own argv.

        A copy of /bin/sh at <root>/cataclysm-tiles, started from the
        root with --userdir, so /proc reports exactly what the real
        engine would: the same executable path, the same working
        directory and the same userdir argument.  Nothing about the check
        is stubbed.  `sh -c CMD ARG...` keeps the extra arguments as
        positional parameters instead of rejecting them, which is what
        lets the real command line be reproduced verbatim.
        """
        binary = os.path.join(self.root, "cataclysm-tiles")
        shutil.copy2("/bin/sh", binary)
        child = subprocess.Popen(
            [binary, "-c", "sleep 30",
             "--userdir", "./playthrough/userdir/"],
            cwd=self.root, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        # Wait for /proc to show the exec, not the fork.
        for _ in range(200):
            if seed_options.live_engine_pids(self.root):
                return child
            time.sleep(0.01)
        self.fail("the stand-in engine never became visible in /proc")

    def test_a_live_engine_refuses_the_write(self):
        before = self.bytes_at(self.options_json)
        self._engine()
        with _environment(PLAYTHROUGH_RUNTIME_DIR=self.runtime):
            with self.assertRaises(seed_options.SeedError) as bad:
                self.patch()
        self.assertIn("running against", str(bad.exception))
        self.assertEqual(self.bytes_at(self.options_json), before)

    def test_another_userdir_s_engine_does_not_block_the_write(self):
        # The check is the userdir, not the binary's name: an engine
        # playing something else is not this session's.
        binary = os.path.join(self.root, "cataclysm-tiles")
        shutil.copy2("/bin/sh", binary)
        child = subprocess.Popen(
            [binary, "-c", "sleep 30", "--userdir", "/tmp"],
            cwd=self.root, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        time.sleep(0.2)
        self.assertEqual(seed_options.live_engine_pids(self.root), [])
        with _environment(PLAYTHROUGH_RUNTIME_DIR=self.runtime):
            self.patch()
        self.assertEqual(
            self.values()["24_HOUR"], seed_options.CLOCK_FORMAT_WANTED)

    def test_a_held_session_lock_blocks_the_write(self):
        with _environment(PLAYTHROUGH_RUNTIME_DIR=self.runtime,
                          PLAYTHROUGH_SEED_LOCK_TIMEOUT="1"):
            path = seed_options.session_lock_path(self.root)
            holder = seed_options.SessionLock(path, 5)
            holder.acquire()
            self.addCleanup(holder.release)
            before = self.bytes_at(self.options_json)
            with self.assertRaises(seed_options.SeedError) as bad:
                self.patch()
            self.assertIn("session lock", str(bad.exception))
            self.assertEqual(
                self.bytes_at(self.options_json), before)
            holder.release()
            self.patch()
        self.assertEqual(
            self.values()["24_HOUR"], seed_options.CLOCK_FORMAT_WANTED)

    def test_the_lock_is_shared_with_the_launcher_by_name(self):
        with _environment(PLAYTHROUGH_LOCK_DIR=self.runtime):
            self.assertEqual(
                seed_options.session_lock_path(self.root),
                os.path.join(self.runtime, "session.lock"))

    def test_a_clean_write_records_that_no_engine_was_running(self):
        with _environment(PLAYTHROUGH_RUNTIME_DIR=self.runtime):
            report = self.patch()
        self.assertTrue(
            any("no engine is running" in note
                for note in report.notes),
            msg=repr(report.notes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
