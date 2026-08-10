#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/session.py.

session.py owns the one irreversible act in this pipeline.  A keystroke
cannot be un-pressed, so every guarantee the record makes about a
captured session is a guarantee about the order and the durability of
what this module does around that act -- and none of those guarantees
can be checked afterwards from the artifacts alone.  That is what this
suite is for.

    python3 playthrough/tooling/test_session.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED, AND WHY EACH ONE EXISTS

* THE CHORD POLICY.  `shift` is the only modifier that may be sent.
  data/raw/keybindings.json ships five DEBUG_DIALOGUE_* toggles ALREADY
  BOUND to ctrl chords -- ctrl+c, ctrl+d, ctrl+t, ctrl+y, ctrl+r -- so
  those need no user override to be reachable, and the game binds no
  action at all to alt, super or meta, which makes every such chord the
  window manager's (alt+F4 closes the engine).  A test asserts each is
  refused and that ordinary play is unaffected.

* THE DERIVED ACTION.  A row's `action` must name the key that was
  really sent.  The first recorded session contains a row reading
  `press 'X'` for a step that delivered `-`; it satisfied every schema
  check, so nothing downstream could tell.  build_action() and
  assert_action_derived() make that impossible, and the sidecar stores
  the validated key itself, so the prose can be checked against a
  machine value rather than believed.

* THE PRE-SEND JOURNAL AND SAME-INDEX RECOVERY.  The intent to press a
  key is durable BEFORE the key leaves.  The tests drive the three
  recovery states -- a stale entry, an interrupted step whose frame was
  captured, and an interrupted step whose frame was not -- and assert
  the record comes out complete at the SAME index, because the failure
  this replaces left a permanent gap: a delivered `Y` with no frame and
  no row.

* THE STEP LOCK.  Two processes must never both decide the next index is
  N.  A test proves a second session cannot open while the first holds
  the lock, and that the lock is released when the session closes.

* THE MANDATORY AUDITS.  The no-debug-binding audit and the
  create-versus-resume pin run on every step rather than when somebody
  remembers to ask, and a bound debug action is refused before a key is
  sent.

* SYMLINK REFUSAL IN THE SAVE TREE.  A link at save/<World>/ or at a
  character file would make the engine write this session's save outside
  the committed tree while every count still matched.

* REPOSITORY-RELATIVE REPORTING.  Machine summaries must not disclose
  where the checkout lives.

WHAT IS DELIBERATELY NOT ASSERTED
Nothing here runs the engine, opens an X display, or touches the real
playthrough/manifest.jsonl, playthrough/frames/ or the real userdir.
Every test works inside a temporary tree it owns, with the capturer
replaced by a stub script, and a final test asserts the committed
artifacts were untouched.  Standard library only.
"""

import argparse
import dataclasses
import hashlib
import inspect
import io
import json
import os
import subprocess
import re
import shutil
import stat

import sys
import types
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import manifest  # noqa: E402  (path set above, as the siblings do)
import ocr_clock  # noqa: E402
import session  # noqa: E402

FIXED_REAL_TS = "2026-08-03T19:14:42.507Z"

# A capturer stand-in.  It writes the PNG the real capture.sh would
# commit and prints the same payload contract, so the transaction can be
# exercised without an X server.  FRAME_INDEX is its only input, exactly
# as the real one documents.
#
# STUB_NO_SIDEBAR reproduces the OTHER thing a real capture routinely
# shows: a screen with no sidebar drawn on it.  The language prompt, the
# main menu, the load dialog, the loading art and the whole character
# creator have no sidebar, so a capture of any of them reads no clock, no
# time phrase and no date -- which is the state the resumed-session
# refusal has to hold in, and therefore a state the suite must be able
# to photograph.
STUB_CAPTURE = """#!/bin/sh
set -eu
index="${FRAME_INDEX}"
name="$(printf 'frame_%05d.png' "${index}")"
path="${STUB_FRAMES}/${name}"
if [ -n "${STUB_FAIL:-}" ]; then
    exit 4
fi
printf 'stub' > "${path}"
digest="$(sha256sum -- "${path}" | cut -d' ' -f1)"
if [ -n "${STUB_NO_SIDEBAR:-}" ]; then
    clock_status=unreadable
    clock=
    date_status=unreadable
    date_text=
else
    clock_status=exact
    clock=08:15:33
    date_status=read
    date_text="Spring, day 61"
fi
cat <<PAYLOAD
CAPTURE_MODE=production
FRAME_INDEX=${index}
FRAME_NAME=${name}
FRAME_FILE=playthrough/frames/${name}
FRAME_PATH=${path}
FRAME_SHA256=${digest}
FRAME_GEOMETRY=1920x1080
REAL_TS=__REAL_TS__
CAPTURE_TOOL=stub
LUMA_MEAN=0.27
LUMA_STDDEV=0.19
CLOCK_RECT=288x1072+1632+4
CLOCK_RECT_FROM=computed
CLOCK_SOURCE=stub
CLOCK_STATUS=${clock_status}
CLOCK=${clock}
TIME_PHRASE=
DATE=${date_text}
DATE_STATUS=${date_status}
OBSERVATIONS=${STUB_OBSERVATIONS}
PAYLOAD
""".replace("__REAL_TS__", FIXED_REAL_TS)


# The sha256 of the four bytes every stubbed capture writes.  A journal
# payload carries the digest capture.sh took at publication, and
# assert_payload_matches() re-hashes the file before a row exists, so a
# fixture that hand-builds a payload has to name the real digest of the
# real stub frame -- which is the point: a constant that did not match
# would be exactly the substitution the check exists to catch.
STUB_FRAME_SHA256 = hashlib.sha256(b"stub").hexdigest()


class SessionFixture(unittest.TestCase):
    """A temporary artifact tree with a stubbed capturer and window."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="cata_session_")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.root = os.path.join(self.directory, "playthrough")
        self.frames = os.path.join(self.root, "frames")
        self.build = os.path.join(self.root, "build")
        self.save = os.path.join(self.root, "userdir", "save")
        self.config = os.path.join(self.root, "userdir", "config")
        for path in (self.frames, self.build, self.save, self.config):
            os.makedirs(path)
        self.manifest = os.path.join(self.root, "manifest.jsonl")
        self.observations = os.path.join(
            self.build, "observations.jsonl")
        self.capture = os.path.join(self.directory, "capture.sh")
        with open(self.capture, "w", encoding="utf-8") as handle:
            handle.write(STUB_CAPTURE)
        os.chmod(self.capture, 0o755)
        self.runtime = os.path.join(self.directory, "runtime")
        os.makedirs(self.runtime, mode=0o700)
        self._environment()
        session.reset_advisories()

    def _environment(self):
        """Point every environment hook at this test's own tree.

        Every PLAYTHROUGH_* variable env.sh exports is cleared first, so
        the suite behaves identically inside a sourced shell and outside
        one: those exports name the COMMITTED artifact tree, and a test
        that picked one up would be checking the real record.
        """
        for name in sorted(os.environ):
            if name.startswith("PLAYTHROUGH_"):
                previous = os.environ.pop(name)
                self.addCleanup(self._restore, name, previous)
        for name, value in (
            (session.ENV_RUNTIME_DIR, self.runtime),
            ("STUB_FRAMES", self.frames),
            ("STUB_OBSERVATIONS", self.observations),
            (session.ENV_SESSION_MODE, ""),
            (session.ENV_RESUME_WORLD, ""),
            ("STUB_FAIL", ""),
            ("STUB_NO_SIDEBAR", ""),
        ):
            previous = os.environ.get(name)
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
            self.addCleanup(self._restore, name, previous)

    @staticmethod
    def _restore(name, previous):
        """Put one environment variable back as it was."""
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

    def open_session(self, **extra):
        """Open a Session against the temporary tree.

        THE TWO ARGUMENTS AN OPERATOR ALWAYS SUPPLIES ARE SUPPLIED HERE,
        so that a test about the journal or the counter does not have to
        restate them at every call.  `step()` refuses to deliver a key
        while the capture before it is unread (`observed`) and halts when
        a capture contradicts the step's own prediction (`expect`); both
        are production behaviour and neither is stubbed out.  What this
        does is answer them the way a driver does:

        * `observed` defaults to a reading of the stubbed capture, which
          is recorded in the real acknowledgment ledger by the real code
          path -- the tests for that ledger read it back;
        * `expect` defaults to EXPECT_EITHER because the stubbed
          capturer writes four fixed bytes rather than a PNG, so
          ImageMagick cannot compare two of them and the honest verdict
          is EFFECT_UNKNOWN.  A test that predicts an outcome passes
          `expect=` explicitly and gets the strict reading.

        Anything a caller passes wins, so the guard's own tests are
        written against the same entry point as everything else.
        """
        opened = session.Session(
            manifest_path=self.manifest,
            frames_dir=self.frames,
            observations_path=self.observations,
            capture_script=self.capture,
            window_id=None,
            root=self.root,
            **extra)
        self.addCleanup(opened.close)
        production_step = opened.step

        def step(key, *args, **keywords):
            """Call the real step with a driver's two declarations."""
            keywords.setdefault(
                "observed",
                "the stubbed capture before this one was read")
            keywords.setdefault("expect", session.EXPECT_EITHER)
            return production_step(key, *args, **keywords)

        opened.step = step
        return opened

    def stub_window(self, opened, window=4242):
        """Replace window resolution and delivery with recorders.

        The window and the keystroke are the two things this suite must
        NOT really do, so both are recorded instead.  Everything else --
        the journal, the lock, the capture, the manifest, the sidecar --
        is the production code path.
        """
        self.sent = []

        def record(identifier, key, timeout=None):
            """Stand in for send_key, recording what was asked for."""
            self.sent.append(key)
            return key

        opened.refresh_window = lambda: window
        original_focus = session.focus_window
        original_send = session.send_key
        session.focus_window = lambda identifier, timeout=None: window
        session.send_key = record
        self.addCleanup(
            setattr, session, "focus_window", original_focus)
        self.addCleanup(setattr, session, "send_key", original_send)

    def rows(self):
        """Return the manifest rows written so far."""
        if not os.path.isfile(self.manifest):
            return []
        with open(self.manifest, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def sidecar(self):
        """Return the telemetry rows written so far."""
        if not os.path.isfile(self.observations):
            return []
        with open(self.observations, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def journal(self, **overrides):
        """Write a COMPLETE journal record for this tree.

        Every field session.py validates on recovery is supplied, because
        the validation is part of the contract: a journal from another
        checkout, another manifest or another X display must not be
        completed against this one.  A test that needs one of them wrong
        overrides it deliberately.
        """
        record = {
            "version": session.JOURNAL_VERSION,
            "phase": session.JOURNAL_PHASE_DELIVERED,
            "frame": 1,
            "key": "j",
            "action": "press 'j'",
            "commentary": "South.",
            "capture_attempts": 1,
            "manifest": manifest.relative_to_repo(self.manifest),
            "frames_dir": manifest.relative_to_repo(self.frames),
            "display": session.resolve_display(),
            "opened_at": FIXED_REAL_TS,
        }
        record.update(overrides)
        for name in [key for key, value in record.items()
                     if value is None]:
            record.pop(name)
        session.write_journal(session.journal_path(self.root), record)
        return record

    def stub_window_module(self, window=4242):
        """Stub window resolution BEFORE a session is opened.

        Recovery re-authenticates and re-focuses the engine before it
        photographs anything, which happens inside Session.__init__ --
        so a recovery test has to replace the module-level helpers rather
        than the instance method stub_window() patches.
        """
        self.sent = []

        def record(identifier, key, timeout=None):
            self.sent.append(key)
            return key

        originals = {
            "authenticated_window": session.authenticated_window,
            "focus_window": session.focus_window,
            "send_key": session.send_key,
        }
        session.authenticated_window = (
            lambda prefer=None, timeout=None, root=None:
            session.WindowIdentity(
                window=window, pid=1, executable="stub", cwd="stub",
                userdir="stub", display=session.resolve_display()))
        session.focus_window = (
            lambda identifier, timeout=None: window)
        session.send_key = record
        for name, value in originals.items():
            self.addCleanup(setattr, session, name, value)
        return window

    def lastworld(self, world="Fern Creek", character="A"):
        """Write the record main_menu::load_game() writes on load.

        The engine writes <userdir>/config/lastworld.json the moment a
        character is loaded (src/main_menu.cpp:1080-1083), so a resumed
        session that has reached the world has one -- and session.py holds
        the pinned survivor against it.  The default character name is
        what "#QQ==" decodes to, which is the fixture world's own.
        """
        path = os.path.join(self.config, session.LASTWORLD_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"world_name": world,
                       "character_name": character}, handle)
        return path

    def world(self, name="Fern Creek", characters=("#QQ==",)):
        """Create a world directory that probe_save_resume believes."""
        directory = os.path.join(self.save, name)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, session.SAVE_MASTER_NAME),
                  "w", encoding="utf-8") as handle:
            handle.write("{}")
        for character in characters:
            with open(os.path.join(directory, character + ".sav"),
                      "w", encoding="utf-8") as handle:
                handle.write("{}")
        return directory

    def record_death_sequence(self, opened):
        """Record the last-words and post-death screens a death exposes."""
        opened.step(
            "Return",
            note="submit A's last words: keep moving",
            commentary="Leave it there: keep moving.")
        opened.step(
            "Escape",
            note="exit the post-death scores screen",
            commentary="Let it end.")

    def write_death_persistence(self, world="Fern Creek",
                                character="A", stem="#QQ=="):
        """Write the engine's graveyard and memorial death products."""
        generation = os.path.join(
            self.root, "userdir", session.GRAVEYARD_DIR_NAME,
            "2026-08-06T06-53-53")
        os.makedirs(generation, exist_ok=True)
        grave_save = os.path.join(
            generation, stem + session.SAVE_EXTENSION)
        with open(grave_save, "w", encoding="utf-8") as handle:
            json.dump({
                "debug_mode": False,
                "player": {"name": character},
            }, handle)
        with open(
                os.path.join(generation, stem + ".log"),
                "w", encoding="utf-8") as handle:
            handle.write("character log\n")

        memorial = os.path.join(
            self.root, "userdir", session.MEMORIAL_DIR_NAME, world)
        os.makedirs(memorial, exist_ok=True)
        base = os.path.join(
            memorial, "%s-2026-08-06-06-53-53" % character)
        with open(base + ".json", "w", encoding="utf-8") as handle:
            json.dump({
                "log": [
                    {"message": "%s was killed." % character},
                    {"message": "Last words: keep moving"},
                    {"message": "Died"},
                ],
                "stats": {
                    "data": {
                        "game_avatar_death": {
                            "event_counts": [[{
                                "avatar_name": [
                                    "string", character],
                            }, {"count": 1}]],
                        },
                    },
                },
            }, handle)
        with open(base + ".txt", "w", encoding="utf-8") as handle:
            handle.write(
                "In memory of: %s\nShe died on Year 1, May 20.\n"
                % character)
        return grave_save


class ChordPolicy(unittest.TestCase):
    """Finding 19: no chord may reach a debug action or the process."""

    def test_shift_is_the_only_modifier(self):
        self.assertEqual(set(session.MODIFIER_KEYS), {"shift"})
        self.assertEqual(
            set(session.REFUSED_MODIFIER_KEYS),
            {"ctrl", "alt", "super", "meta"})

    def test_default_bound_debug_chords_are_refused(self):
        for chord in session.PROHIBITED_DEBUG_CHORDS:
            for spelling in (chord, chord.upper(), chord.title()):
                with self.subTest(chord=spelling):
                    with self.assertRaises(session.KeyRejected):
                        session.validate_key(spelling)

    def test_window_and_process_chords_are_refused(self):
        for chord in ("alt+F4", "alt+Tab", "alt+space",
                      "ctrl+alt+Delete", "super+e", "meta+q",
                      "shift+alt+F4", "ctrl+u", "ctrl+v", "ctrl+s"):
            with self.subTest(chord=chord):
                with self.assertRaises(session.KeyRejected):
                    session.validate_key(chord)

    def test_the_keys_real_play_needs_still_pass(self):
        # Every chord the first recorded session actually used, plus the
        # bare keys that carry the rest of it.
        for key in ("shift+Tab", "shift+2", "shift+4", "shift+s",
                    "j", "k", "h", "l", "Y", "Return", "Escape",
                    "plus", "period", "KP_7", "F1"):
            with self.subTest(key=key):
                self.assertEqual(session.validate_key(key), key)

    def test_every_prohibited_chord_names_its_reason(self):
        for chord, reason in session.PROHIBITED_CHORDS.items():
            with self.subTest(chord=chord):
                self.assertTrue(reason.strip())
                self.assertEqual(chord, chord.lower())


class DerivedAction(unittest.TestCase):
    """Finding 12: a row cannot name a key other than the one sent."""

    def test_identity_is_derived_from_the_key(self):
        self.assertEqual(session.build_action("j"), "press 'j'")
        self.assertEqual(
            session.build_action("j", "step one tile south"),
            "press 'j' -- step one tile south")

    def test_the_row_116_defect_is_refused(self):
        # The real defect, verbatim: the row said 'X' and '-' was sent.
        with self.assertRaises(session.RecordError):
            session.assert_action_derived(
                "-", "press 'X' -- nothing; see note")

    def test_a_derived_action_is_accepted_either_shape(self):
        self.assertEqual(
            session.assert_action_derived("j", "press 'j'"),
            "press 'j'")
        self.assertEqual(
            session.assert_action_derived(
                "j", "press 'j' -- step south"),
            "press 'j' -- step south")

    def test_a_note_may_not_forge_a_second_identity(self):
        with self.assertRaises(session.RecordError):
            session.build_action("j", "press 'X' -- something else")
        with self.assertRaises(session.RecordError):
            session.build_action("j", "two\nlines")


class TheStep(SessionFixture):
    """The transaction: one key, one frame, one row, one attestation."""

    def test_a_step_records_all_four(self):
        opened = self.open_session()
        self.stub_window(opened)
        result = opened.step(
            "j", commentary="Shelves first.",
            note="step one tile south")
        self.assertEqual(self.sent, ["j"])
        self.assertEqual(result.frame, 1)
        self.assertEqual(result.action, "press 'j' -- step one tile "
                                        "south")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), list(manifest.FIELDS))
        self.assertEqual(rows[0]["action"], result.action)
        self.assertEqual(rows[0]["ingame_clock"], "08:15:33")
        self.assertTrue(os.path.isfile(
            os.path.join(self.frames, "frame_00001.png")))

    def test_the_sidecar_stores_the_immutable_key(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("shift+4", commentary="Sleep.", note="lie down")
        row = self.sidecar()[0]
        for field in session.ATTESTED_FIELDS:
            self.assertIn(field, row)
        self.assertEqual(row["key"], "shift+4")
        self.assertEqual(row["action"], "press 'shift+4' -- lie down")
        self.assertEqual(row["capture_attempts"], 1)
        self.assertIs(row["recovered"], False)

    def test_a_contradicting_action_sends_nothing(self):
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.RecordError):
            opened.step("-", action="press 'X' -- nothing",
                        commentary="No.")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.rows(), [])

    def test_a_refused_chord_sends_nothing(self):
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.KeyRejected):
            opened.step("ctrl+r", commentary="No.")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.rows(), [])

    def test_the_journal_is_cleared_once_the_row_is_durable(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)))


class JournalRecovery(SessionFixture):
    """Finding 1: an interrupted step leaves no gap and invents nothing.

    The three phases are the whole point.  `delivered` means the key
    reached the X server, so the frame may honestly be photographed at
    that index; `captured` means the frame is already on disk, so the row
    is completed from the payload; `sending` means DELIVERY IS UNKNOWN,
    and that one is halted on rather than resolved, because either answer
    would be a statement this module cannot support.
    """

    def test_a_delivered_key_with_no_frame_is_captured_at_that_index(
            self):
        # Exactly the committed defect: the key went in, the capture was
        # refused, and the session stopped with nothing recorded for it.
        self.stub_window_module()
        self.journal(phase=session.JOURNAL_PHASE_DELIVERED, frame=1,
                     key="Y",
                     action="press 'Y' -- confirm the character sheet",
                     commentary="Sign it and open the door.")
        opened = self.open_session()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["frame"], 1)
        self.assertEqual(
            rows[0]["action"],
            "press 'Y' -- confirm the character sheet")
        self.assertEqual(opened.frame, 1)
        self.assertTrue(opened.recovered)
        attested = self.sidecar()[0]
        self.assertEqual(attested["key"], "Y")
        self.assertIs(attested["recovered"], True)
        self.assertEqual(attested["capture_attempts"], 2)
        self.assertTrue(os.path.isfile(
            os.path.join(self.frames, "frame_00001.png")))
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)))

    def test_recovery_re_authenticates_before_it_photographs(self):
        """The engine is re-found, not assumed still there.

        Recovery used to photograph the root window immediately, on the
        strength of a window id from a process that had died -- so it
        could file whatever now occupied the display as the frame a
        keystroke produced.
        """
        self.journal(phase=session.JOURNAL_PHASE_DELIVERED, key="Y",
                     action="press 'Y'", commentary="Sign it.")
        asked = []
        original = session.authenticated_window
        session.authenticated_window = (
            lambda prefer=None, timeout=None, root=None: (
                asked.append(prefer) or session.WindowIdentity(
                    window=99, pid=1, executable="stub", cwd="stub",
                    userdir="stub",
                    display=session.resolve_display())))
        self.addCleanup(
            setattr, session, "authenticated_window", original)
        focused = []
        original_focus = session.focus_window
        session.focus_window = (
            lambda identifier, timeout=None: focused.append(identifier))
        self.addCleanup(
            setattr, session, "focus_window", original_focus)
        self.open_session()
        self.assertEqual(len(asked), 1)
        self.assertEqual(focused, [99])
        self.assertEqual(len(self.rows()), 1)

    def test_an_unreachable_engine_leaves_the_journal_alone(self):
        """A frame is not invented because the window went away."""
        self.journal(phase=session.JOURNAL_PHASE_DELIVERED, key="Y",
                     action="press 'Y'", commentary="Sign it.")
        original = session.authenticated_window

        def refuse(prefer=None, timeout=None, root=None):
            raise session.WindowError("no engine on the display")

        session.authenticated_window = refuse
        self.addCleanup(
            setattr, session, "authenticated_window", original)
        with self.assertRaises(session.WindowError):
            self.open_session()
        self.assertEqual(self.rows(), [])
        self.assertIsNotNone(
            session.read_journal(session.journal_path(self.root)))

    def test_an_ambiguous_send_halts_and_records_nothing(self):
        """`sending` is never resolved automatically.

        This is the fabrication the review found: a crash between the
        journal write and the key leaving produced a frame, a row and a
        first-person sentence for a keystroke that never happened.
        """
        self.stub_window_module()
        self.journal(phase=session.JOURNAL_PHASE_SENDING, key="Y",
                     action="press 'Y'", commentary="Sign it.")
        with self.assertRaises(session.RecordError) as caught:
            self.open_session()
        self.assertIn("AMBIGUOUS", str(caught.exception))
        self.assertIn("reconcile", str(caught.exception))
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.sidecar(), [])
        self.assertFalse(os.path.isfile(
            os.path.join(self.frames, "frame_00001.png")))
        self.assertIsNotNone(
            session.read_journal(session.journal_path(self.root)))

    def test_reconciling_as_delivered_completes_that_index(self):
        self.stub_window_module()
        self.journal(phase=session.JOURNAL_PHASE_SENDING, key="Y",
                     action="press 'Y'", commentary="Sign it.")
        opened = session.Session(
            manifest_path=self.manifest, frames_dir=self.frames,
            observations_path=self.observations,
            capture_script=self.capture, window_id=None,
            root=self.root, settle_journal=False)
        self.addCleanup(opened.close)
        notes = opened.reconcile(session.RECONCILE_DELIVERED)
        self.assertTrue(any("delivered" in note for note in notes))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "press 'Y'")
        self.assertEqual(opened.frame, 1)
        self.assertIs(self.sidecar()[0]["recovered"], True)
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)))

    def test_reconciling_as_not_delivered_records_nothing(self):
        self.stub_window_module()
        self.journal(phase=session.JOURNAL_PHASE_SENDING, key="Y",
                     action="press 'Y'", commentary="Sign it.")
        opened = session.Session(
            manifest_path=self.manifest, frames_dir=self.frames,
            observations_path=self.observations,
            capture_script=self.capture, window_id=None,
            root=self.root, settle_journal=False)
        self.addCleanup(opened.close)
        opened.reconcile(session.RECONCILE_NOT_DELIVERED)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.sidecar(), [])
        self.assertEqual(opened.frame, 0)
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)))

    def test_reconcile_refuses_a_phase_that_is_not_ambiguous(self):
        self.stub_window_module()
        opened = session.Session(
            manifest_path=self.manifest, frames_dir=self.frames,
            observations_path=self.observations,
            capture_script=self.capture, window_id=None,
            root=self.root, settle_journal=False)
        self.addCleanup(opened.close)
        self.journal(phase=session.JOURNAL_PHASE_DELIVERED)
        with self.assertRaises(session.RecordError):
            opened.reconcile(session.RECONCILE_DELIVERED)

    def test_a_captured_frame_completes_from_the_stored_payload(self):
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, key="Return",
            action="press 'Return'",
            commentary="English, same as every form.",
            payload={session.CAPTURE_MODE_KEY:
                     session.CAPTURE_MODE_PRODUCTION,
                     "FRAME_INDEX": "1",
                     "FRAME_NAME": "frame_00001.png",
                     "FRAME_FILE": "playthrough/frames/frame_00001.png",
                     "FRAME_PATH": os.path.join(
                         self.frames, "frame_00001.png"),
                     "FRAME_SHA256": STUB_FRAME_SHA256,
                     "REAL_TS": FIXED_REAL_TS,
                     "CLOCK": "08:00:00",
                     "CLOCK_STATUS": "read",
                     "DATE": "Spring, day 61"})
        opened = self.open_session()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["real_ts"], FIXED_REAL_TS)
        self.assertEqual(rows[0]["ingame_clock"], "08:00:00")
        self.assertEqual(opened.frame, 1)
        self.assertIs(self.sidecar()[0]["recovered"], True)

    def test_a_captured_payload_for_another_frame_is_refused(self):
        """The payload is re-checked against the capture on disk.

        It arrives from a file this session did not write and it decides
        the row's `file`, `real_ts` and clock, so an index that disagrees
        with the frame on disk must fail rather than become a row.
        """
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, key="Return",
            action="press 'Return'", commentary="English.",
            payload={session.CAPTURE_MODE_KEY:
                     session.CAPTURE_MODE_PRODUCTION,
                     "FRAME_INDEX": "7",
                     "FRAME_NAME": "frame_00007.png",
                     "FRAME_FILE": "playthrough/frames/frame_00007.png",
                     "FRAME_PATH": os.path.join(
                         self.frames, "frame_00007.png"),
                     "FRAME_SHA256": STUB_FRAME_SHA256,
                     "REAL_TS": FIXED_REAL_TS,
                     "CLOCK": "08:00:00",
                     "CLOCK_STATUS": "read"})
        with self.assertRaises(session.SessionError):
            self.open_session()
        self.assertEqual(self.rows(), [])

    def test_a_stale_entry_is_discarded_not_replayed(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        opened.close()
        self.journal(phase=session.JOURNAL_PHASE_DELIVERED, frame=1,
                     key="j", action="press 'j'", commentary="South.")
        again = self.open_session()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.sidecar()), 1)
        self.assertEqual(again.frame, 1)
        self.assertTrue(again.recovered)

    def test_a_stale_entry_repairs_a_missing_telemetry_row(self):
        """The sidecar is made whole before the journal is discarded.

        _commit() appends the manifest row, then the telemetry row, then
        clears the journal -- so an interruption between the two appends
        leaves a manifest row with no sidecar row, and discarding the
        journal without looking used to lose it for good.  That row
        carries the sidebar DATE line timeline.py reconciles a midnight
        crossing with.
        """
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        manifest.append_row(
            self.manifest, 1, "playthrough/frames/frame_00001.png",
            FIXED_REAL_TS, "08:00:00", "press 'j'", "South.",
            root=self.root)
        self.assertEqual(self.sidecar(), [])
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, frame=1, key="j",
            action="press 'j'", commentary="South.",
            payload={session.CAPTURE_MODE_KEY:
                     session.CAPTURE_MODE_PRODUCTION,
                     "FRAME_INDEX": "1",
                     "FRAME_NAME": "frame_00001.png",
                     "FRAME_FILE": "playthrough/frames/frame_00001.png",
                     "FRAME_PATH": os.path.join(
                         self.frames, "frame_00001.png"),
                     "FRAME_SHA256": STUB_FRAME_SHA256,
                     "REAL_TS": FIXED_REAL_TS,
                     "CLOCK": "08:00:00",
                     "CLOCK_STATUS": "read",
                     "DATE": "Spring, day 61"})
        opened = self.open_session()
        repaired = self.sidecar()
        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0]["frame"], 1)
        self.assertEqual(repaired[0]["date"], "Spring, day 61")
        self.assertEqual(repaired[0]["key"], "j")
        self.assertIs(repaired[0]["recovered"], True)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(opened.frame, 1)
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)))
        # AND THE THIRD RECORD, which this repair used to leave behind:
        # the manifest row and the telemetry row were made whole and the
        # journal discarded, so nothing would ever have attested the
        # bytes again.
        ledger = manifest.read_frame_digests(
            os.path.join(self.root, *manifest.DIGESTS_REL_PARTS),
            self.root)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["frame"], 1)
        self.assertEqual(ledger[0]["sha256"], STUB_FRAME_SHA256)

    def recorded_frame_without_its_attestation(self, digest=True):
        """Leave frame 1 recorded, attested in telemetry, unattested.

        Exactly the state an interruption between the telemetry append
        and the ledger append leaves: the frame is on disk, the manifest
        row is durable, the telemetry row is durable, the capture digest
        is missing and the step journal is still there to say so.
        """
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        payload = {
            session.CAPTURE_MODE_KEY: session.CAPTURE_MODE_PRODUCTION,
            "FRAME_INDEX": "1",
            "FRAME_NAME": "frame_00001.png",
            "FRAME_FILE": "playthrough/frames/frame_00001.png",
            "FRAME_PATH": os.path.join(self.frames, "frame_00001.png"),
            "REAL_TS": FIXED_REAL_TS,
            "CLOCK": "08:00:00",
            "CLOCK_STATUS": "read",
            "DATE": "Spring, day 61",
        }
        if digest:
            payload["FRAME_SHA256"] = STUB_FRAME_SHA256
        manifest.append_row(
            self.manifest, 1, "playthrough/frames/frame_00001.png",
            FIXED_REAL_TS, "08:00:00", "press 'j'", "South.",
            root=self.root)
        session.append_observation(
            self.observations,
            session.observation_row(1, payload, key="j",
                                    action="press 'j'"),
            root=self.root)
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, frame=1, key="j",
            action="press 'j'", commentary="South.", payload=payload)
        return payload

    def ledger_rows(self):
        """Every capture attestation in this tree's ledger."""
        path = os.path.join(self.root, *manifest.DIGESTS_REL_PARTS)
        if not os.path.isfile(path):
            return []
        return list(manifest.read_frame_digests(path, self.root))

    def test_a_stale_entry_repairs_a_missing_capture_digest(self):
        """THE SECOND POST-MANIFEST GAP, which nothing used to settle.

        _commit() appends the manifest row, then the telemetry row, then
        the capture digest, then clears the journal.  An interruption
        between the last two left a recorded frame with NO attestation
        -- and this recovery repaired only the telemetry row, saw it
        already present, and discarded the journal, so the digest was
        lost for good.  The session then carried on and the frame
        surfaced as unattested during timeline publication, hours later
        and with the journal long gone.
        """
        self.recorded_frame_without_its_attestation()
        self.assertEqual(self.ledger_rows(), [])
        opened = self.open_session()
        ledger = self.ledger_rows()
        self.assertEqual(len(ledger), 1, msg=ledger)
        self.assertEqual(ledger[0]["frame"], 1)
        self.assertEqual(ledger[0]["sha256"], STUB_FRAME_SHA256)
        self.assertEqual(
            ledger[0]["attested"], manifest.DIGEST_AT_CAPTURE,
            msg=("the journal carried the digest capture.sh published "
                 "when it renamed the PNG into place, and the file "
                 "still hashes to it, so the claim IS a capture-time "
                 "one"))
        self.assertEqual(
            len(self.sidecar()), 1,
            msg="the telemetry row that was already there is not doubled")
        self.assertEqual(opened.frame, 1)
        self.assertEqual(opened.verify_record(), ())
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)),
            msg=("the journal is discarded only once the row, the "
                 "telemetry and the attestation all cover the frame"))

    def test_a_repaired_digest_says_recovery_when_none_was_published(
            self):
        """A weaker claim is recorded as the weaker claim.

        With no publication digest to hold the file to, the digest can
        only be MEASURED now: that establishes what the bytes are, not
        that they are the bytes the keystroke produced, and recording it
        as `capture` would be the stronger claim than the evidence.
        """
        self.recorded_frame_without_its_attestation(digest=False)
        self.open_session()
        ledger = self.ledger_rows()
        self.assertEqual(len(ledger), 1, msg=ledger)
        self.assertEqual(ledger[0]["sha256"], STUB_FRAME_SHA256)
        self.assertEqual(
            ledger[0]["attested"], manifest.DIGEST_AT_RECOVERY)

    def test_a_substituted_frame_stops_the_digest_repair(self):
        """And leaves the journal, so the frame can be looked at."""
        self.recorded_frame_without_its_attestation()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("not the bytes that were captured")
        with self.assertRaises(session.RecordError) as caught:
            self.open_session()
        self.assertIn("not the bytes that were captured",
                      str(caught.exception))
        self.assertEqual(
            self.ledger_rows(), [],
            msg="nothing is attested about a substituted frame")
        self.assertTrue(
            os.path.isfile(session.journal_path(self.root)),
            msg="the journal survives an unrepaired gap")

    def test_a_record_missing_an_attestation_is_not_continued(self):
        """Counter recovery verifies the ledger, not only the rows.

        Once the journal is gone the gap cannot be repaired honestly, so
        the session that would carry on over it stops instead -- while
        the evidence is still on disk, rather than at publication time
        when it is not.
        """
        self.recorded_frame_without_its_attestation()
        os.unlink(session.journal_path(self.root))
        with self.assertRaises(session.RecordError) as caught:
            self.open_session()
        message = str(caught.exception)
        self.assertIn("no capture digest", message)
        self.assertIn("frame_digests.jsonl", message)

    def test_verify_record_reports_the_unattested_frame(self):
        """The same gap is visible to a read-only caller."""
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        path = os.path.join(self.root, *manifest.DIGESTS_REL_PARTS)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        problems = opened.verify_record()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("1 recorded frame(s) have no capture digest",
                      problems[0])

    def test_an_unbelievable_journal_stops_the_session(self):
        with open(session.journal_path(self.root), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(session.RecordError):
            self.open_session()

    def test_a_journal_ahead_of_the_record_is_refused(self):
        self.journal(phase=session.JOURNAL_PHASE_DELIVERED, frame=9)
        with self.assertRaises(session.RecordError):
            self.open_session()

    def test_an_older_journal_version_is_refused_not_reinterpreted(self):
        """Version 1's `intent` did not distinguish delivery.

        Deciding after the fact that an ambiguous record meant
        "delivered" is precisely how a keystroke that never happened
        acquires a frame and a sentence.
        """
        self.stub_window_module()
        self.journal(version=1, phase="intent", key="Y",
                     action="press 'Y'", commentary="Sign it.")
        with self.assertRaises(session.RecordError) as caught:
            self.open_session()
        self.assertIn("version", str(caught.exception))
        self.assertEqual(self.rows(), [])

    def test_a_journal_from_another_record_is_refused(self):
        self.stub_window_module()
        self.journal(manifest="playthrough/somebody-elses.jsonl")
        with self.assertRaises(session.RecordError):
            self.open_session()

    def test_a_journal_from_another_display_is_refused(self):
        self.stub_window_module()
        self.journal(display=":77")
        with self.assertRaises(session.RecordError):
            self.open_session()

    def test_an_uninterpretable_phase_is_refused(self):
        self.stub_window_module()
        self.journal(phase="halfway")
        with self.assertRaises(session.RecordError):
            self.open_session()

    def test_a_failed_capture_leaves_the_journal_for_the_next_open(self):
        opened = self.open_session()
        self.stub_window(opened)
        os.environ["STUB_FAIL"] = "1"
        with self.assertRaises(session.CaptureError):
            opened.step("Y", commentary="Sign it.")
        self.assertEqual(self.sent, ["Y"])
        self.assertEqual(self.rows(), [])
        record = session.read_journal(session.journal_path(self.root))
        self.assertIsNotNone(record)
        self.assertEqual(record["frame"], 1)
        self.assertEqual(record["key"], "Y")
        self.assertEqual(
            record["phase"], session.JOURNAL_PHASE_DELIVERED,
            msg=("xdotool returned 0, so the key DID reach the X "
                 "server: recovery may photograph this index"))
        opened.close()
        # And the next session finishes it at the same index.
        os.environ["STUB_FAIL"] = ""
        self.stub_window_module()
        again = self.open_session()
        self.assertEqual(again.frame, 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.sidecar()[0]["key"], "Y")

    def test_a_send_that_failed_leaves_the_journal_ambiguous(self):
        """xdotool failing says nothing about whether X acted."""
        opened = self.open_session()
        self.stub_window(opened)
        original = session.send_key

        def refuse(identifier, key, timeout=None):
            raise session.WindowError("xdotool exited 1")

        session.send_key = refuse
        self.addCleanup(setattr, session, "send_key", original)
        with self.assertRaises(session.WindowError):
            opened.step("Y", commentary="Sign it.")
        record = session.read_journal(session.journal_path(self.root))
        self.assertEqual(
            record["phase"], session.JOURNAL_PHASE_SENDING,
            msg="an unknown delivery stays unknown in the journal")
        self.assertEqual(self.rows(), [])


class TheKeystrokeArgv(unittest.TestCase):
    """What is actually handed to xdotool, argument by argument.

    THE MODIFIER BUG THIS PINS.  A key like 'Y' is not one X keystroke:
    xdotool implements it as shift down, y, shift up.  Through
    `key --window` -- synthetic events the server never reconciles
    against real key state -- that trailing shift-up can be lost, and the
    modifier then stays DOWN for the rest of the session.  Every plain
    key after it arrives as Shift+key, the game ignores them, xdotool
    still exits 0, and send_key still reports success.

    Measured on a real session: after one 'Y' confirmed a world, every
    subsequent Up, Down, Return and Tab was silently discarded.  The
    engine was alive and idle throughout -- main thread in
    hrtimer_nanosleep, focus and active window both correct -- and the
    screen digest did not move for ninety seconds.  Releasing the stuck
    modifiers and re-sending with --clearmodifiers moved it on the first
    key.

    That is the worst failure shape this pipeline has: a keystroke
    reported as delivered that the game never acted on, with a frame
    captured against it, so the row claims an action that never
    happened.  Hence a test on the argv rather than on the outcome.
    """

    def sent(self, key, window=4194313):
        seen = {}

        def fake_run(command, timeout, what, env=None, cwd=None):
            seen["argv"] = list(command)
            return subprocess.CompletedProcess(list(command), 0, "", "")

        original_run = session._run
        original_verified = session._verified
        session._run = fake_run
        session._verified = lambda name: "/usr/bin/" + name
        try:
            session.send_key(window, key)
        finally:
            session._run = original_run
            session._verified = original_verified
        return seen["argv"]

    def test_every_keystroke_clears_held_modifiers(self):
        argv = self.sent("Down")
        self.assertIn("--clearmodifiers", argv)
        self.assertIn("key", argv)

    def test_it_still_targets_the_authenticated_window(self):
        argv = self.sent("Down", window=4194313)
        self.assertIn("--window", argv)
        self.assertEqual(argv[argv.index("--window") + 1], "4194313")

    def test_the_key_is_the_last_argument_and_is_only_one(self):
        """One key, one argv slot -- more would hide behind one frame."""
        argv = self.sent("Return")
        self.assertEqual(argv[-1], "Return")

    def test_a_modified_key_keeps_its_own_modifier(self):
        """--clearmodifiers clears HELD ones, not requested ones."""
        argv = self.sent("shift+Tab")
        self.assertEqual(argv[-1], "shift+Tab")
        self.assertIn("--clearmodifiers", argv)


class TheStepLock(SessionFixture):
    """Finding 13: exactly one process may advance the counter."""

    def test_a_second_session_cannot_open_while_one_is_held(self):
        first = self.open_session()
        self.assertTrue(first._lock.held)
        with self.assertRaises(session.SessionError):
            self.open_session(lock_timeout=1)
        first.close()
        second = self.open_session(lock_timeout=1)
        self.assertTrue(second._lock.held)

    def test_closing_releases_the_lock(self):
        opened = self.open_session()
        opened.close()
        self.assertFalse(opened._lock.held)
        self.open_session(lock_timeout=1)

    def test_the_lock_lives_outside_the_working_tree(self):
        path = session.step_lock_path(self.root)
        self.assertFalse(path.startswith(self.root + os.sep))
        # No group or world access: another account must not be able to
        # plant a lock or a journal in this session's scratch directory.
        mode = stat.S_IMODE(os.lstat(os.path.dirname(path)).st_mode)
        self.assertEqual(mode & 0o077, 0, msg=oct(mode))

    def test_the_lock_is_per_checkout(self):
        mine = session.step_lock_path(self.root)
        other = os.path.join(self.directory, "second")
        os.makedirs(other)
        self.assertNotEqual(mine, session.step_lock_path(other))


class MandatoryAudits(SessionFixture):
    """Findings 2 and 3: the integrity checks are not optional."""

    def _bind_debug(self, identifier="debug"):
        path = os.path.join(self.config, "keybindings.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([{"id": identifier, "category": "DEBUG",
                        "bindings": [{"input_method": "keyboard_char",
                                      "key": "f"}]}], handle)
        return path

    def test_a_bound_debug_action_stops_the_step(self):
        opened = self.open_session()
        self.stub_window(opened)
        self._bind_debug()
        with self.assertRaises(session.CheatGuard):
            opened.step("j", commentary="South.")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.rows(), [])

    def test_every_debug_action_is_audited_not_only_three(self):
        for identifier in ("DEBUG_DIALOGUE_SHOW_ALL_RESPONSE",
                           "debug_hour_timer", "some_new_debug_thing"):
            with self.subTest(identifier=identifier):
                self.assertTrue(session.is_debug_action(identifier))
        self.assertFalse(session.is_debug_action("sleep"))

    def test_a_changed_keybindings_file_is_re_read(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        self._bind_debug("DEBUG_DIALOGUE_DL_EFFECT")
        with self.assertRaises(session.CheatGuard):
            opened.step("k", commentary="North.")

    def test_the_mode_is_pinned_and_a_declaration_must_agree(self):
        opened = self.open_session()
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_CREATE)
        opened.close()
        self.world()
        again = self.open_session()
        self.assertEqual(again.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(again.pin.world, "Fern Creek")
        again.close()
        os.environ[session.ENV_SESSION_MODE] = (
            session.SESSION_MODE_CREATE)
        with self.assertRaises(session.SessionError):
            self.open_session()

    def test_a_create_run_may_continue_once_its_survivor_exists(self):
        # A create run writes the save part-way through itself, so the
        # tree says 'resume' from that frame onward.  With rows already
        # recorded that is the same session, not somebody else's save.
        opened = self.open_session()
        self.stub_window(opened)
        # Return on the highlighted row, which is how the custom sheet is
        # actually opened -- see MenuHotkeyCollision for why the letter
        # itself is refused.
        opened.step("Return", commentary="Custom Character.")
        opened.close()
        self.world()
        os.environ[session.ENV_SESSION_MODE] = (
            session.SESSION_MODE_CREATE)
        again = self.open_session()
        self.assertEqual(again.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(again.frame, 1)

    def test_a_declared_resume_against_an_empty_tree_is_refused(self):
        os.environ[session.ENV_SESSION_MODE] = (
            session.SESSION_MODE_RESUME)
        with self.assertRaises(session.SessionError):
            self.open_session()

    def test_a_second_character_during_a_resume_is_refused(self):
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        self.world("Fern Creek", ("#QQ==", "#UkI="))
        with self.assertRaises(session.CheatGuard):
            opened.step("k", commentary="North.")

    def test_a_resumed_session_refuses_the_creator_before_sending(self):
        """The prevention the save-set comparison is not.

        Comparing the save tree with what it looked like a keystroke ago
        detects a second survivor only AFTER the key that created one has
        landed -- and a character, once created, is in that world's save
        directory whether this run records it or not.  So the five
        main-menu hotkeys that open a new survivor are refused before
        send_key is reached, for as long as the engine is on a menu.
        """
        self.world()
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        for key in session.MENU_NEW_SURVIVOR_HOTKEYS:
            with self.subTest(key=key):
                with self.assertRaises(session.CheatGuard):
                    opened.step(key, commentary="No.")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.rows(), [])

    def test_the_creator_refusal_is_scoped_to_a_resume(self):
        """This guard is scoped to a RESUME, not to the letter.

        A create run is allowed to open the character creator -- that is
        what it is for -- and this guard does not stand in its way.  The
        letter 'u' is nonetheless refused in both modes, by a SECOND and
        independent guard: it collides with the tutorial entry on the
        menu's top row (MenuHotkeyCollision).  Two guards, two reasons,
        and the distinction is worth asserting rather than assuming: the
        exception a create run meets is the collision, never this one.
        """
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_CREATE)
        with self.assertRaises(session.KeyRejected) as caught:
            opened.step("u", commentary="The custom sheet.")
        self.assertNotIsInstance(caught.exception, session.CheatGuard)
        self.assertIn("T<u|U>torial Game", str(caught.exception))
        self.assertEqual(self.sent, [])
        # And the permitted door, taken the verified way, opens.
        opened.step("Return", commentary="The custom sheet.")
        self.assertEqual(self.sent, ["Return"])

    def test_the_world_is_entered_only_on_the_sidebar_appearing(self):
        """The phase is observed from the pixels, never declared."""
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        # The stub capture reports a clock, which is the sidebar, which
        # is what a loaded character draws.
        opened.step("Return", commentary="Continue.")
        self.assertEqual(opened.ui_phase, session.UI_PHASE_IN_WORLD)
        # And from there the same letters are ordinary commands again.
        opened.step("r", commentary="Read the label on it.")
        self.assertEqual(self.sent, ["Return", "r"])

    def test_the_refusal_holds_while_no_capture_has_shown_a_sidebar(
            self):
        """Runtime QA finding: the refusal used to lapse at frame 2.

        The phase was recovered between processes from
        <userdir>/config/lastworld.json, which the engine had already
        written for the survivor this run continues -- so `_frame > 0`
        was the whole release condition and the guard released itself on
        the first captured frame, whatever that frame showed.  A QA pass
        drove exactly this: `u` refused at frame 0, two sidebar-free menu
        frames captured, then the same `u` ACCEPTED and delivered.

        The release condition is, and is only, a captured frame carrying
        a sidebar reading.  Here every capture is sidebar-free and
        lastworld.json names the pinned survivor, which is the state the
        defect passed and the fixed guard must refuse -- both inside the
        session that took the frames and in the next process, which is
        where a `step`-per-keystroke driver actually lives.
        """
        self.world()
        self.lastworld()
        os.environ["STUB_NO_SIDEBAR"] = "1"
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_RESUME)
        opened.step("1", commentary="English, like every form.")
        opened.step("Escape", commentary="Back out of that.")
        self.assertEqual(self.sent, ["1", "Escape"])
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(opened.sidebar_frame)
        for key in session.MENU_NEW_SURVIVOR_HOTKEYS:
            with self.subTest(key=key, process="same"):
                with self.assertRaises(session.CheatGuard):
                    opened.step(key, commentary="No.")
        opened.close()
        again = self.open_session()
        self.stub_window(again)
        self.assertEqual(again.frame, 2)
        self.assertEqual(again.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(again.sidebar_frame)
        for key in session.MENU_NEW_SURVIVOR_HOTKEYS:
            with self.subTest(key=key, process="next"):
                with self.assertRaises(session.CheatGuard):
                    again.step(key, commentary="Still no.")
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.rows()), 2)

    def test_the_phase_is_recovered_from_the_photograph_not_the_file(
            self):
        """A sidebar-free record leaves the phase at the menu.

        The two halves of the defect, asserted directly rather than
        through the refusal: lastworld.json naming the pinned survivor
        does not put a session in the world, and a captured frame whose
        sidebar was photographed does -- across a process boundary, which
        is the only place the recovery is used.
        """
        self.world()
        self.lastworld()
        os.environ["STUB_NO_SIDEBAR"] = "1"
        first = self.open_session()
        self.stub_window(first)
        first.step("Return", commentary="Open the load list.")
        first.close()
        blind = self.open_session()
        self.assertEqual(blind.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(blind.sidebar_frame)
        blind.close()
        # The load completes: this capture reads the sidebar the loaded
        # character draws, and THAT is what releases the phase.
        os.environ["STUB_NO_SIDEBAR"] = ""
        loading = self.open_session()
        self.stub_window(loading)
        loading.step("Return", commentary="Load her.")
        self.assertEqual(loading.ui_phase, session.UI_PHASE_IN_WORLD)
        self.assertEqual(loading.sidebar_frame, 2)
        loading.close()
        resumed = self.open_session()
        self.stub_window(resumed)
        self.assertEqual(resumed.ui_phase, session.UI_PHASE_IN_WORLD)
        self.assertEqual(resumed.sidebar_frame, 2)
        # And the letters are ordinary in-world commands again.
        resumed.step("r", commentary="Read the label on it.")
        self.assertEqual(self.sent, ["r"])

    def test_the_phase_release_survives_a_sidebar_free_frame_after_it(
            self):
        """Look mode and a mid-session relaunch do not re-lock the keys.

        The examine panel replaces the whole sidebar column and the menus
        a relaunch passes through have no sidebar at all, so the LAST
        capture is regularly sidebar-free in an ordinary session.  The
        transition is one-way: the earliest photographed sidebar is what
        the phase rests on.
        """
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Load her.")
        self.assertEqual(opened.ui_phase, session.UI_PHASE_IN_WORLD)
        os.environ["STUB_NO_SIDEBAR"] = "1"
        opened.step("x", commentary="Look at what is over there.")
        opened.close()
        later = self.open_session()
        self.stub_window(later)
        self.assertEqual(later.ui_phase, session.UI_PHASE_IN_WORLD)
        self.assertEqual(later.sidebar_frame, 1)

    def test_a_record_with_no_telemetry_leaves_the_phase_at_the_menu(
            self):
        """No attestation is no evidence, and refusing is the safe side.

        A sidecar that is missing, torn or keyed to frames this record
        does not hold cannot say what was photographed.  The phase stays
        at the menu -- one refusal an operator can read, rather than a
        keystroke that cannot be taken back -- and `status` reports the
        shortfall rather than the phase hiding it.
        """
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Load her.")
        self.assertEqual(opened.ui_phase, session.UI_PHASE_IN_WORLD)
        opened.close()
        os.remove(self.observations)
        without = self.open_session()
        self.stub_window(without)
        self.assertEqual(without.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(without.sidebar_frame)
        self.assertTrue(without.verify_record())
        with self.assertRaises(session.CheatGuard):
            without.step("u", commentary="No.")
        without.close()
        # A torn sidecar is the same answer, reached the same way.
        with open(self.observations, "w", encoding="utf-8") as handle:
            handle.write('{"frame": 1, "ingame_clock": "08:15:33"}\n')
            handle.write('{"frame": 2, "ingame_cl\n')
        torn = self.open_session()
        self.stub_window(torn)
        self.assertEqual(torn.ui_phase, session.UI_PHASE_MENU)
        with self.assertRaises(session.CheatGuard):
            torn.step("u", commentary="No.")

    def test_a_telemetry_row_for_an_unrecorded_frame_is_not_evidence(
            self):
        """A reading about a frame the manifest does not hold proves
        nothing about what this session photographed."""
        self.world()
        self.lastworld()
        os.environ["STUB_NO_SIDEBAR"] = "1"
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("1", commentary="English.")
        opened.close()
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "frame": 99999,
                "file": "playthrough/frames/frame_99999.png",
                "ingame_clock": "08:15:33",
                "time_phrase": "",
                "date": "Spring, day 61"}) + "\n")
        after = self.open_session()
        self.stub_window(after)
        self.assertEqual(after.frame, 1)
        self.assertEqual(after.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(after.sidebar_frame)
        with self.assertRaises(session.CheatGuard):
            after.step("u", commentary="No.")

    def test_a_coarse_time_phrase_alone_releases_the_phase(self):
        """A survivor without a watch still draws a sidebar.

        display::time_string() falls back to display::time_approx()'s
        phrase without a timepiece, so a session that has not found one
        photographs a sidebar carrying no clock at all.  Any one of the
        three readings is the sidebar.
        """
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        for name, payload in (
            ("clock", {"CLOCK": "08:15:33", "TIME_PHRASE": "",
                       "DATE": ""}),
            ("phrase", {"CLOCK": "", "TIME_PHRASE": "Around dawn",
                        "DATE": ""}),
            ("date", {"CLOCK": "", "TIME_PHRASE": "",
                      "DATE": "Spring, day 61"}),
        ):
            with self.subTest(reading=name):
                opened._ui_phase = session.UI_PHASE_MENU
                opened._sidebar_frame = None
                opened._settle_ui_phase(7, payload)
                self.assertEqual(opened.ui_phase,
                                 session.UI_PHASE_IN_WORLD)
                self.assertEqual(opened.sidebar_frame, 7)
        opened._ui_phase = session.UI_PHASE_MENU
        opened._sidebar_frame = None
        opened._settle_ui_phase(
            8, {"CLOCK": "", "TIME_PHRASE": "", "DATE": ""})
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(opened.sidebar_frame)

    def test_a_resume_that_reaches_the_world_as_somebody_else_stops(
            self):
        """lastworld.json is the engine's own statement of WHO.

        A sidebar means a survivor is in the world; this run records
        exactly one, and it is the one that already existed.
        """
        self.world()
        self.lastworld(character="Somebody Else")
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.CheatGuard):
            opened.step("Return", commentary="Continue.")
        # The keystroke and its frame really happened, so the record says
        # so; what stops is everything after them.
        self.assertEqual(self.sent, ["Return"])
        self.assertEqual(len(self.rows()), 1)
        self.assertIsNotNone(opened.aborted)

    def test_a_second_survivor_is_detected_on_the_same_step(self):
        """Not one step late.

        The save-set comparison used to run only before a key, so a
        keystroke that created a survivor was noticed after ANOTHER key
        had been sent into a game state this module had lost track of.
        """
        opened = self.open_session()
        self.stub_window(opened)
        original = session.send_key

        def create(identifier, key, timeout=None):
            """A keystroke that makes a second survivor appear."""
            self.sent.append(key)
            self.world("Fern Creek", ("#QQ==", "#UkI="))
            return key

        session.send_key = create
        self.addCleanup(setattr, session, "send_key", original)
        with self.assertRaises(session.CheatGuard):
            opened.step("Return", commentary="The custom sheet.")
        self.assertEqual(self.sent, ["Return"])
        self.assertEqual(
            len(self.rows()), 1,
            msg="the key was delivered, so the row records it")
        self.assertIsNotNone(opened.aborted)

    def test_the_decoded_character_name_is_the_engines_own(self):
        """#<b64>.sav decodes with the engine's own alphabet.

        Its 63rd character is '-' rather than '/'
        (src/catacharset.cpp:215), and the '#' is a marker rather than
        payload, so a plain b64decode would answer wrongly or raise.
        """
        self.assertEqual(
            session.decoded_character_name(
                "#RGVscGhpbmUgT3VlbGxldHRl.sav"),
            "Delphine Ouellette")
        self.assertEqual(
            session.decoded_character_name("#QQ==.sav.zzip"), "A")
        self.assertEqual(
            session.encoded_character_stem("Delphine Ouellette"),
            "#RGVscGhpbmUgT3VlbGxldHRl")
        self.assertEqual(session.encoded_character_stem("A"), "#QQ==")
        self.assertIsNone(session.decoded_character_name("not-a-save"))
        self.assertIsNone(session.decoded_character_name("#zz.sav"))

    def test_a_deleted_character_is_refused(self):
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        os.unlink(os.path.join(self.save, "Fern Creek", "#QQ==.sav"))
        with self.assertRaises(session.CheatGuard):
            opened.step("j", commentary="South.")

    def test_evidenced_engine_death_cleanup_is_accepted(self):
        """The engine may move the save and reset its world after death."""
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        self.record_death_sequence(opened)
        os.unlink(os.path.join(
            self.save, "Fern Creek", "#QQ==.sav"))
        os.unlink(os.path.join(
            self.save, "Fern Creek", session.SAVE_MASTER_NAME))
        grave_save = self.write_death_persistence()

        opened._assert_save_pin()

        self.assertTrue(os.path.isfile(grave_save))
        self.assertNotIn("Fern Creek", opened._fingerprint)
        # Once accepted, the now-empty live set remains stable.
        opened._assert_save_pin()

    def test_a_recorded_death_does_not_veto_its_own_session(self):
        """The run recording a death must be able to finish recording it.

        A runtime pass drove a real death and was refused at the keystroke
        AFTER the first last-words frame: the strict pre-flight saw a live
        character save for a survivor the record showed dying and declared
        the tree unresumable, which is the right answer for a tree being
        LOADED and the wrong one for the run photographing the death.  The
        engine only moves the save in cleanup_at_end(), after the death
        screen, so that state is unavoidable and every remaining frame of
        a permitted ending was unreachable.
        """
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        self.record_death_sequence(opened)
        before = len(list(io.open(self.manifest, encoding="utf-8")))

        # The tree is now EXACTLY what the strict pre-flight refuses.
        with self.assertRaisesRegex(session.SessionError, "NOT resumable"):
            session.probe_save_resume(self.save, None, self.root)

        # A driver that invokes this module once per keystroke re-runs the
        # pre-flight on every one of them, so it must not refuse here.
        # Closed first, because exactly one process may hold the step
        # lock -- which is also what a per-keystroke driver does.
        opened.close()
        again = self.open_session()
        self.stub_window(again)
        again.step("Escape", note="exit the post-death scores screen",
                   commentary="Let it end.")
        after = len(list(io.open(self.manifest, encoding="utf-8")))
        self.assertEqual(after, before + 1)

    def test_the_death_proof_honours_the_amendment_ledger(self):
        """A post-death screen named through the ledger is accepted.

        The amendment ledger is this pipeline's only sanctioned way to
        correct a narration, and the death proof reads exactly the field
        an amendment corrects.  Reading the RAW rows would reject a record
        whose screens had been named correctly through the ledger while
        accepting one whose original wording happened to contain a marker.
        """
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", note="submit A's last words: keep moving",
                    commentary="Leave it there: keep moving.")
        opened.step("Escape", note="shut it", commentary="Let it end.")
        os.unlink(os.path.join(self.save, "Fern Creek", "#QQ==.sav"))
        os.unlink(os.path.join(
            self.save, "Fern Creek", session.SAVE_MASTER_NAME))
        self.write_death_persistence()

        # The second row names no post-death screen, so the proof refuses.
        with self.assertRaisesRegex(
                session.CheatGuard, "captured last-words"):
            opened._assert_save_pin()

        rows = session.manifest.read_rows(self.manifest, self.root)
        digests = session.manifest.row_digests(self.manifest, self.root)
        target = rows[-1]
        session.manifest.append_amendment(
            os.path.join(self.root, session.manifest.AMENDMENTS_NAME),
            1, "2026-08-10T04:00:00.000Z", target["frame"], "action",
            digests[target["frame"]], target["action"],
            "press 'Escape' -- closed it, and the capture that followed "
            "shows the post-death scores screen",
            "the capture renders the engine's own scores window",
            "the row did not name the screen the capture shows",
            root=self.root)

        # Naming it through the ledger satisfies the same proof.
        opened._assert_save_pin()

    def test_death_files_without_a_captured_death_are_refused(self):
        """Grave files cannot be planted as a deletion bypass."""
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        os.unlink(os.path.join(
            self.save, "Fern Creek", "#QQ==.sav"))
        self.write_death_persistence()

        with self.assertRaisesRegex(
                session.CheatGuard, "captured last-words"):
            opened._assert_save_pin()

    def test_a_captured_death_without_engine_artifacts_is_refused(self):
        """Intent prose cannot excuse a manually deleted save."""
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        self.record_death_sequence(opened)
        os.unlink(os.path.join(
            self.save, "Fern Creek", "#QQ==.sav"))

        with self.assertRaisesRegex(session.CheatGuard, "graveyard"):
            opened._assert_save_pin()

    def test_the_survivor_may_appear_once_on_a_create_run(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Custom Character.")
        self.world()
        opened.step("Return", commentary="Sign it.")
        self.assertEqual(len(self.rows()), 2)


class TheRouteIsGuardedNotOnlyTheLetters(SessionFixture):
    """Finding 7: refusing five hotkeys does not refuse the route.

    MENU_NEW_SURVIVOR_HOTKEYS refuses five letters while a resumed
    session is on a menu.  The VERIFIED way to Custom Character --
    MENU_CUSTOM_CHARACTER_ROUTE -- is Left/Right along the top row,
    Up/Down onto the submenu row, then Return, and not one of those keys
    is in that set: a resumed session could have walked to the creator
    with the letter guard never firing once.  The review asked for the
    launcher and the session to be coupled through a verified route
    rather than a letter list, so the stated intent is refused too.
    """

    def resumed(self):
        """A session pinned to a resume, still on a menu."""
        self.world()
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        return opened

    def test_every_route_key_is_refused_by_its_stated_intent(self):
        opened = self.resumed()
        for key in ("Left", "Right", "Up", "Down", "Return"):
            with self.subTest(key=key):
                self.assertNotIn(key, session.MENU_NEW_SURVIVOR_HOTKEYS)
                with self.assertRaises(session.CheatGuard):
                    opened.step(
                        key,
                        note="move onto the custom character row",
                        commentary="Onto the custom sheet.")
        self.assertEqual(
            self.sent, [], msg="not one of them may be delivered")
        self.assertEqual(self.rows(), [])

    def test_the_refusal_names_the_route_it_is_closing(self):
        opened = self.resumed()
        with self.assertRaises(session.CheatGuard) as caught:
            opened.step("Return", note="open the custom character sheet",
                        commentary="Sign my own sheet.")
        message = str(caught.exception)
        self.assertIn("REFUSED", message)
        self.assertIn("NOT been sent", message)
        self.assertIn("Custom Character", message)
        self.assertIn("Up/Down", message)
        self.assertIn("Fern Creek", message)

    def test_an_ordinary_route_key_is_not_refused(self):
        """Silence about the creator is the whole difference.

        A resumed session navigates a menu to LOAD its character, and
        those keystrokes are the same keys.  Only a row that says it is
        opening the creator is turned away.
        """
        opened = self.resumed()
        # A menu keystroke photographs a menu: no sidebar, so the phase
        # stays where the record says it is.
        os.environ["STUB_NO_SIDEBAR"] = "1"
        opened.step("Down", note="move down onto the saved character",
                    commentary="Down to my own name on the list.")
        self.assertEqual(self.sent, ["Down"])
        self.assertEqual(len(self.rows()), 1)

    def test_a_create_run_may_walk_its_own_route(self):
        """The refusal is the resume rule, not a ban on the creator."""
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_CREATE)
        opened.step("Return", note="open the custom character sheet",
                    commentary="My own sheet, then.")
        self.assertEqual(self.sent, ["Return"])

    def test_in_the_world_the_same_words_are_not_refused(self):
        """The phase is required, and it is observed.

        Once a captured frame has shown the sidebar the creator is out of
        reach anyway, and a survivor may say what she likes.
        """
        self.world()
        self.lastworld()
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Continue.")
        self.assertEqual(opened.ui_phase, session.UI_PHASE_IN_WORLD)
        opened.step("Return", note="read the note through",
                    commentary="The custom sheet I drew is still in my "
                               "pocket.")
        self.assertEqual(self.sent, ["Return", "Return"])


class TheRouteIsGuardedByThePhotograph(SessionFixture):
    """The route enforced from the SCREEN, not from the caller's words.

    A code review demonstrated that the two guards above are only as
    good as the caller's honesty: they refuse five letters and refuse
    prose that mentions the custom sheet, so ordinary truthful-looking
    wording -- "move selection", "activate selected item" -- walks the
    verified MENU_CUSTOM_CHARACTER_ROUTE into the creator with neither
    of them firing, and the save pin only notices afterwards, once a
    second survivor exists and the prohibited route has already been
    taken and photographed.

    So the refusal reads the last capture with the engine's own font.
    The fixtures here are the COMMITTED frames -- genuine photographs of
    this build's menus, not drawings of them -- because a guard that
    claims to read screens should be tested against screens.
    """

    #: <repo>/playthrough/frames, beside this test's own directory.
    RECORD_FRAMES = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frames")

    #: Classification -> committed frame index, filled in on first use.
    #:
    #: THE FIXTURES ARE CHOSEN BY WHAT THEY SHOW, NOT BY THEIR INDEX,
    #: and that is a correction rather than a preference.  They used to
    #: be three literals -- frame 2 for the submenu, 195 for the resumed
    #: launch's own menu, 300 for a screen inside the world -- which was
    #: true of the capture set they were written against and silently
    #: false of the next one.  When the session was re-recorded, index 2
    #: became a world-creation dialog and 195 became a screen from inside
    #: the world, so thirteen tests began asserting the guard's behaviour
    #: on screens that were not the ones they named, and the failures
    #: read as defects in the guard.  A fixture that identifies itself by
    #: position in an artifact that can legitimately be replaced is not a
    #: fixture; it is a coincidence.  These scan the committed record for
    #: a frame that actually classifies as the wanted screen, and skip
    #: with a precise reason when the record contains none.
    _by_screen = {}

    def classify_committed(self, index):
        """Return session's own classification of a committed frame.

        The real method is used rather than a copy of its rules, so a
        change to the classifier moves the fixtures with it.  It needs
        only the frames directory, so it is called unbound against a
        stand-in that supplies one.
        """
        stand_in = types.SimpleNamespace(_frames=self.RECORD_FRAMES)
        return session.Session._classify_screen(stand_in, index)

    def committed_frame_showing(self, screen):
        """Return the first committed frame that shows `screen`.

        Skips when the record has no example.  That is a real outcome
        rather than a hedge: the re-recorded session opens with the
        new-game submenu already on, and it never takes the load route,
        so it contains no capture of the main menu WITHOUT the submenu.
        A test that needs one has nothing to photograph, and saying so
        is better than passing on a frame that shows something else.
        """
        if screen in self._by_screen:
            found = self._by_screen[screen]
        else:
            found = None
            for index in self.committed_indices():
                if self.classify_committed(index) == screen:
                    found = index
                    break
            type(self)._by_screen[screen] = found
        if found is None:
            self.skipTest(
                "the committed record contains no capture that "
                "classifies as %r, so this test has no screen to read"
                % screen)
        return found

    def committed_indices(self):
        """Return the committed frame indices, lowest first."""
        if not os.path.isdir(self.RECORD_FRAMES):
            self.skipTest("this checkout has no committed frames")
        found = []
        pattern = re.compile(r"\Aframe_(\d{5})\.png\Z")
        for name in os.listdir(self.RECORD_FRAMES):
            match = pattern.match(name)
            if match is not None:
                found.append(int(match.group(1)))
        if not found:
            self.skipTest("this checkout has no committed frames")
        return sorted(found)

    def committed_world_frame(self):
        """Return a committed frame taken from INSIDE the world.

        Selected by evidence rather than by classification: the first
        manifest row whose `ingame_clock` is a real reading is, by
        definition, a frame with the survivor's sidebar on it.
        """
        record = os.path.join(os.path.dirname(self.RECORD_FRAMES),
                              "manifest.jsonl")
        # Skipped rather than raised, which is what every sibling
        # selector here does: a checkout between a retirement and its
        # re-record carries no manifest at all, and a fixture that
        # demanded one would report the absence of evidence as a defect
        # in the code under test.
        if not os.path.isfile(record):
            self.skipTest("this checkout has no committed manifest")
        rows = manifest.read_rows(record)
        for row in rows:
            if (row.get("ingame_clock") or "").strip():
                return int(row["frame"])
        self.skipTest("no committed row carries a sidebar clock, so the "
                      "record has no frame from inside the world")

    def committed_frame(self, index):
        """Return a committed capture's path, or skip the test."""
        path = os.path.join(self.RECORD_FRAMES,
                            manifest.FRAME_NAME_FORMAT % index)
        if not os.path.isfile(path):
            self.skipTest("committed frame %d is not in this checkout"
                          % index)
        return path

    def record_one_menu_frame(self, source):
        """Record frame 1 AS a committed capture of a menu screen.

        The whole record is built by hand rather than through the stub
        capturer, because the point of the fixture is the PIXELS: the
        stub writes four bytes, and four bytes decode to no screen at
        all.  Manifest row, telemetry row (sidebar-free, so the phase
        stays at the menu) and capture digest are all written, which is
        the state an ordinary step leaves.
        """
        self.world()
        planted = os.path.join(self.frames, manifest.FRAME_NAME_FORMAT % 1)
        shutil.copyfile(self.committed_frame(source), planted)
        digest = manifest.file_digest(planted, "frame")
        manifest.append_row(
            self.manifest, 1, manifest.frame_file(1), FIXED_REAL_TS,
            None, "press '1' -- choose English at the language prompt",
            "One language, one form to fill in.", root=self.root)
        session.append_observation(
            self.observations,
            session.observation_row(
                1,
                {"FRAME_INDEX": "1",
                 "FRAME_FILE": manifest.frame_file(1),
                 "FRAME_SHA256": digest,
                 "REAL_TS": FIXED_REAL_TS,
                 "CLOCK": "", "CLOCK_STATUS": "unreadable",
                 "TIME_PHRASE": "", "DATE": "",
                 "DATE_STATUS": "unreadable"},
                key="1", action="press '1' -- choose English at the "
                                "language prompt"),
            root=self.root)
        manifest.append_frame_digest(
            os.path.join(self.root, *manifest.DIGESTS_REL_PARTS),
            1, manifest.frame_file(1), digest,
            os.path.getsize(planted), manifest.DIGEST_AT_CAPTURE,
            manifest.utc_timestamp(), root=self.root)
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        self.assertEqual(opened.frame, 1)
        os.environ["STUB_NO_SIDEBAR"] = "1"
        return opened

    # -- what the classifier reads off real captures -----------------

    def test_the_committed_submenu_frame_is_read_as_the_submenu(self):
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(
                session.SCREEN_NEW_GAME_SUBMENU))
        self.assertEqual(opened._observed_screen(1),
                         session.SCREEN_NEW_GAME_SUBMENU)

    def test_the_committed_load_menu_frame_is_read_as_the_main_menu(
            self):
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(session.SCREEN_MAIN_MENU))
        self.assertEqual(
            opened._observed_screen(1), session.SCREEN_MAIN_MENU,
            msg=("the resumed launch's own screen must classify as the "
                 "route, or the guard would refuse the load itself"))

    def test_a_screen_from_inside_the_world_is_neither(self):
        opened = self.record_one_menu_frame(self.committed_world_frame())
        self.assertEqual(opened._observed_screen(1),
                         session.SCREEN_OTHER)

    def test_a_frame_that_decodes_to_nothing_is_unreadable(self):
        """No evidence is reported as no evidence.

        The stub capturer's four bytes are not a rendered screen, and
        neither is a missing file.  Both must come back UNREADABLE
        rather than as "not the main menu", because the guard treats the
        two differently and conflating them would refuse the first
        keystroke of every resumed session.
        """
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(session.SCREEN_MAIN_MENU))
        with open(os.path.join(self.frames,
                               manifest.FRAME_NAME_FORMAT % 1),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        opened._screens.clear()
        self.assertEqual(opened._observed_screen(1),
                         session.SCREEN_UNREADABLE)
        self.assertEqual(opened._observed_screen(7),
                         session.SCREEN_UNREADABLE)

    # -- what the guard does with it ---------------------------------

    def test_generic_prose_cannot_walk_the_route_to_the_creator(self):
        """THE DEFECT, exactly as the review reproduced it.

        Nothing in these rows mentions the custom sheet and not one of
        these keys is a new-survivor hotkey, so both earlier guards pass
        them.  The photograph does not: it shows the five new-character
        entries, and on that screen a key that confirms or moves deeper
        is refused before delivery.
        """
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(
                session.SCREEN_NEW_GAME_SUBMENU))
        for key, note in (("Return", "activate selected item"),
                          ("KP_Enter", "confirm the highlighted row"),
                          ("space", "select the current entry"),
                          ("Down", "move selection"),
                          ("Up", "move selection"),
                          ("End", "jump to the last entry")):
            with self.subTest(key=key):
                self.assertNotIn(
                    key, session.MENU_NEW_SURVIVOR_HOTKEYS)
                self.assertIsNone(
                    session.CUSTOM_CHARACTER_MENTION_RE.search(note))
                with self.assertRaises(session.CheatGuard) as caught:
                    opened.step(key, note=note,
                                commentary="Get on with it.")
                self.assertIn("SHOWS THE NEW-GAME SUBMENU",
                              str(caught.exception))
        self.assertEqual(
            self.sent, [],
            msg="not one of them may reach the engine")
        self.assertEqual(
            len(self.rows()), 1,
            msg="and no row is written about a keystroke never sent")

    def test_the_way_out_of_that_screen_stays_open(self):
        """A guard that stranded the session would be a worse defect.

        Left and Right walk the top row away from [New Game]; Escape
        closes the submenu.  The load route needs exactly those, so they
        are not refused on that screen.
        """
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(
                session.SCREEN_NEW_GAME_SUBMENU))
        for key in ("Right", "Left", "Escape"):
            with self.subTest(key=key):
                opened.step(key, note="walk the top row",
                            commentary="Past that, to the list with my "
                                       "own name on it.")
        self.assertEqual(self.sent, ["Right", "Left", "Escape"])

    def test_the_load_route_itself_is_not_refused(self):
        """Return on the resumed launch's own menu is the load."""
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(session.SCREEN_MAIN_MENU))
        opened.step("Return", note="open the selected world",
                    commentary="Fern Creek. Where I left off.")
        self.assertEqual(self.sent, ["Return"])

    def test_the_load_route_is_permitted_on_a_main_menu_reading(self):
        """The same property, held without a photograph of one.

        The test above is the one worth having, because it reads real
        pixels -- but it can only run where the committed record happens
        to contain a capture of the main menu WITHOUT the new-game
        submenu, and the re-recorded session contains none: its menu
        opened with the submenu already on and it never took the load
        route.  Left at that, the guard's PERMITTING branch would have no
        coverage at all, and that branch is the one whose regression
        strands a legitimate resume instead of merely allowing a
        forbidden key.

        So this asserts the guard rather than the classifier, and says
        so: the reading is supplied directly, and what is under test is
        what the guard DOES with a main-menu reading.  It is deliberately
        the weaker of the two tests and deliberately not a substitute for
        it -- if a future record carries a main-menu capture, the one
        above starts running again on its own.
        """
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(
                session.SCREEN_NEW_GAME_SUBMENU))
        # The submenu reading is what the photograph gives; on it, a
        # confirm is refused.  That half is asserted here too, so the
        # override below cannot be mistaken for the guard being off.
        with self.assertRaises(session.CheatGuard):
            opened.step("Return", note="open the selected world",
                        commentary="Fern Creek. Where I left off.")
        self.assertEqual(self.sent, [])
        opened._screens[1] = session.SCREEN_MAIN_MENU
        opened.step("Return", note="open the selected world",
                    commentary="Fern Creek. Where I left off.")
        self.assertEqual(
            self.sent, ["Return"],
            msg="on a main-menu reading the load route must be sent")

    def test_confirming_on_an_unrecognised_menu_screen_is_refused(self):
        """The route runs through the main menu and nothing else."""
        opened = self.record_one_menu_frame(self.committed_world_frame())
        with self.assertRaises(session.CheatGuard) as caught:
            opened.step("Return", note="activate selected item",
                        commentary="Whatever this is.")
        self.assertIn("does not show the main menu",
                      str(caught.exception))
        self.assertEqual(self.sent, [])

    def test_an_unreadable_screen_refuses_nothing_by_itself(self):
        """No evidence relaxes nothing and refuses nothing.

        The other guards still stand -- this asserts both halves, so a
        future change cannot quietly turn "could not read" into either
        permission or a wall.
        """
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(session.SCREEN_MAIN_MENU))
        with open(os.path.join(self.frames,
                               manifest.FRAME_NAME_FORMAT % 1),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        opened._screens.clear()
        opened.step("Return", note="open the selected world",
                    commentary="Fern Creek.")
        self.assertEqual(self.sent, ["Return"])
        with self.assertRaises(session.CheatGuard):
            opened.step("u", commentary="No.")

    def test_a_create_run_with_its_survivor_is_guarded_too(self):
        """The rule is "one survivor", not "resume mode".

        A create run whose survivor already exists is in the same
        position as a resumed one, and the UI phase cannot see it: the
        phase latches to in-world at the first sidebar frame, so a
        relaunch part-way through a record -- which the committed record
        contains -- returns the engine to a menu the phase still calls
        the world.  The submenu half of this guard does not consult the
        phase for exactly that reason.
        """
        opened = self.record_one_menu_frame(
            self.committed_frame_showing(
                session.SCREEN_NEW_GAME_SUBMENU))
        opened._pin = dataclasses.replace(
            opened._pin, mode=session.SESSION_MODE_CREATE)
        self.assertFalse(opened._pin.resume)
        self.assertTrue(
            opened._must_not_create_survivor(),
            msg="the survivor's save is on disk, so a second is a "
                "replacement whatever mode this is")
        opened._ui_phase = session.UI_PHASE_IN_WORLD
        with self.assertRaises(session.CheatGuard):
            opened.step("Return", note="activate selected item",
                        commentary="Get on with it.")
        self.assertEqual(self.sent, [])


class TheLauncherStateCoupling(SessionFixture):
    """Finding 7: the coupling launch_game.sh documented and lacked.

    launch_game.sh publishes the starting screen it VERIFIED as
    $PLAYTHROUGH_INITIAL_UI_STATE and says in its own comment (:3220)
    that the value exists so this module's refusals and the operator work
    from one declared state.  Nothing here had ever read it.  It is read
    now, it can only refuse, and it relaxes nothing.
    """

    def declare(self, state):
        """Publish a launcher state for this test only."""
        previous = os.environ.get(session.ENV_INITIAL_UI_STATE)
        os.environ[session.ENV_INITIAL_UI_STATE] = state
        self.addCleanup(self._restore, session.ENV_INITIAL_UI_STATE,
                        previous)

    def test_the_vocabulary_is_the_launchers_own(self):
        self.assertEqual(
            session.LAUNCH_UI_STATES,
            ("main-menu-load-required", "main-menu-create-permitted",
             "unverified"))
        script = os.path.join(
            os.path.dirname(os.path.abspath(session.__file__)),
            "launch_game.sh")
        with open(script, "r", encoding="utf-8") as handle:
            text = handle.read()
        for state in session.LAUNCH_UI_STATES:
            with self.subTest(state=state):
                self.assertIn('"%s"' % state, text)

    def test_an_undeclared_state_opens_normally(self):
        """A session driven without the launcher is legitimate."""
        opened = self.open_session()
        self.assertEqual(opened.launch_state,
                         session.LAUNCH_STATE_UNDECLARED)

    def test_a_state_outside_the_vocabulary_is_refused(self):
        self.declare("main-menu")
        with self.assertRaises(session.SessionError) as caught:
            self.open_session()
        self.assertIn("cannot reason about", str(caught.exception))

    def test_a_verified_load_against_a_create_pin_is_refused(self):
        """Two readings of one question, and they disagree."""
        self.declare(session.LAUNCH_STATE_LOAD_REQUIRED)
        with self.assertRaises(session.SessionError) as caught:
            self.open_session()
        message = str(caught.exception)
        self.assertIn("main-menu-load-required", message)
        self.assertIn("create", message)

    def test_a_create_launch_against_a_resume_pin_is_refused(self):
        self.world()
        self.declare(session.LAUNCH_STATE_CREATE_PERMITTED)
        with self.assertRaises(session.SessionError) as caught:
            self.open_session()
        self.assertIn("never replaced", str(caught.exception))

    def test_a_create_run_part_way_through_itself_is_not_refused(self):
        """The save appears DURING creation, and that is not a clash.

        _pin_session records the same disagreement rather than refusing
        it, for the same reason: a create run writes its survivor's save
        part-way through itself, so from that frame on the tree says
        'resume' while the launcher's statement stays true.  Refusing it
        would stop a correct run at its own halfway point.
        """
        self.declare(session.LAUNCH_STATE_CREATE_PERMITTED)
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Sign it.")
        opened.close()
        self.world()
        again = self.open_session()
        self.assertEqual(again.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(again.frame, 1)
        self.assertEqual(again.launch_state,
                         session.LAUNCH_STATE_CREATE_PERMITTED)

    def test_each_state_opens_against_the_pin_it_agrees_with(self):
        self.declare(session.LAUNCH_STATE_CREATE_PERMITTED)
        opened = self.open_session()
        self.assertEqual(opened.launch_state,
                         session.LAUNCH_STATE_CREATE_PERMITTED)
        opened.close()
        self.world()
        self.declare(session.LAUNCH_STATE_LOAD_REQUIRED)
        again = self.open_session()
        self.assertEqual(again.pin.mode, session.SESSION_MODE_RESUME)
        self.assertEqual(again.launch_state,
                         session.LAUNCH_STATE_LOAD_REQUIRED)

    def test_an_unverified_probe_relaxes_nothing(self):
        """The launcher established nothing; the refusals still stand."""
        self.world()
        self.declare(session.LAUNCH_STATE_UNVERIFIED)
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.launch_state,
                         session.LAUNCH_STATE_UNVERIFIED)
        for key in session.MENU_NEW_SURVIVOR_HOTKEYS:
            with self.subTest(key=key):
                with self.assertRaises(session.CheatGuard):
                    opened.step(key, commentary="No.")
        self.assertEqual(self.sent, [])

    def test_the_state_reaches_the_status_payload(self):
        """Reported, not merely checked: one state for three readers."""
        self.declare(session.LAUNCH_STATE_CREATE_PERMITTED)
        opened = self.open_session()
        self.assertEqual(opened.launch_state,
                         session.LAUNCH_STATE_CREATE_PERMITTED)
        opened.close()
        source = os.path.abspath(session.__file__)
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('_emit("LAUNCH_UI_STATE", session.launch_state)',
                      text)


class ADeathIsNotResumable(SessionFixture):
    """M-18: a live-shaped save for a dead survivor is refused.

    The state this covers is the one a signalled process leaves, and it
    is the reason save shape cannot decide resumability.  CDDA writes the
    character file during play and only moves it to the graveyard in
    ``cleanup_at_end()``, which runs AFTER the death screen -- so a
    session that ended inside that screen leaves a fully live-shaped save
    for a survivor the record shows dying.  It was measured on this
    checkout: the committed save reads as a living character while the
    manifest records last words and neither graveyard/ nor memorial/
    exists, and `probe` answered `resume`.
    """

    def write_record(self, *rows):
        """Write a manifest holding exactly the rows given."""
        with open(self.manifest, "w", encoding="utf-8") as handle:
            for index, (action, commentary) in enumerate(rows, start=1):
                handle.write(json.dumps({
                    "frame": index,
                    "file": "playthrough/frames/frame_%05d.png" % index,
                    "real_ts": "2026-08-09T00:00:0%d+00:00" % (index % 10),
                    "ingame_clock": "08:0%d:00" % (index % 10),
                    "action": action,
                    "commentary": commentary,
                }) + "\n")

    def a_recorded_death(self):
        """A tree whose record shows a death and whose save survived."""
        self.world("Fern Creek", ("#QQ==",))
        self.lastworld("Fern Creek", "A")
        self.write_record(
            ("press 'j' -- walk south", "South."),
            ("press 'O' -- begin my last words", "O."),
        )

    def probe(self):
        return session.probe_save_resume(self.save, None, self.root)

    def test_a_live_save_for_a_dead_survivor_is_refused(self):
        self.a_recorded_death()
        with self.assertRaises(session.SessionError) as refused:
            self.probe()
        said = str(refused.exception)
        self.assertIn("NOT resumable", said)
        self.assertIn("Fern Creek", said)

    def test_the_refusal_names_the_survivor_and_the_frame(self):
        """A refusal that cannot be acted on is only an obstruction."""
        self.a_recorded_death()
        with self.assertRaises(session.SessionError) as refused:
            self.probe()
        said = str(refused.exception)
        self.assertIn("'A'", said)
        self.assertIn("frame 2", said)
        # The three ways out, so the operator is not left guessing.
        for way in ("retire this userdir", "complete the engine's own "
                    "cleanup", session.ENV_RESUME_WORLD):
            with self.subTest(way=way):
                self.assertIn(way, said)

    def test_it_does_not_silently_become_a_create(self):
        """The dangerous half: CREATE beside the dead survivor's save.

        Making the world non-resumable removes it from the resumable
        list, and the CREATE branch would then report "make a new
        character" on a tree that still holds the dead one's save and
        world -- starting a second survivor in the same world directory,
        which the continue-an-existing-save rule forbids outright.  So
        the refusal has to come BEFORE that branch, and this is the test
        that would catch it moving.
        """
        self.a_recorded_death()
        with self.assertRaises(session.SessionError):
            self.probe()

    def test_a_living_survivor_is_still_resumable(self):
        """The fix must not refuse an ordinary interrupted session."""
        self.world("Fern Creek", ("#QQ==",))
        self.lastworld("Fern Creek", "A")
        self.write_record(
            ("press 'j' -- walk south", "South."),
            ("press '5' -- wait a while", "Rest."),
        )
        probe = self.probe()
        self.assertTrue(probe.resume)
        self.assertEqual(probe.world, "Fern Creek")

    def test_a_first_run_with_no_record_at_all_still_creates(self):
        """No manifest is 'no death recorded', not 'unreadable'."""
        probe = self.probe()
        self.assertFalse(probe.resume)
        self.assertEqual(probe.mode, session.SESSION_MODE_CREATE)

    def test_a_completed_cleanup_leaves_no_live_save_to_refuse(self):
        """The legitimate ending: the engine moved the save itself.

        Cleanup having run is reported as a note rather than a refusal,
        because there is nothing left to load -- which is exactly the
        difference between an ending and an interruption.
        """
        self.world("Fern Creek", ())
        self.lastworld("Fern Creek", "A")
        self.write_record(
            ("press 'O' -- begin my last words", "O."),
            ("press 'Escape' -- exit the post-death scores screen",
             "Let it end."),
        )
        self.write_death_persistence()
        probe = self.probe()
        self.assertFalse(probe.resume)
        self.assertTrue(any("recorded a death" in one
                            for one in probe.notes))

    def test_an_unattributable_death_disqualifies_no_world(self):
        """Without lastworld.json the death belongs to no world.

        Charging it to a world anyway would refuse a tree that may have
        nothing to do with it, so it is reported and resumability is
        decided on the saves alone.
        """
        self.world("Fern Creek", ("#QQ==",))
        self.write_record(
            ("press 'O' -- begin my last words", "O."),
        )
        probe = self.probe()
        self.assertTrue(probe.resume)
        self.assertTrue(any("cannot be attributed" in one
                            for one in probe.notes))

    def test_the_evidence_travels_with_the_decision(self):
        """A consumer must be able to see WHY a world was excluded."""
        self.world("Fern Creek", ())
        self.lastworld("Fern Creek", "A")
        self.write_record(
            ("press 'O' -- begin my last words", "O."),
        )
        payload = self.probe().as_dict()
        world = payload["worlds"][0]
        self.assertEqual(world["death_recorded_at"], 1)
        self.assertFalse(world["cleanup_complete"])
        self.assertTrue(world["death_pending"])
        self.assertFalse(world["resumable"])

    def test_an_absent_record_is_answered_and_a_broken_one_refused(self):
        """Absence and corruption are not the same answer.

        THE DEFECT THIS PINS.  Both used to answer "the record shows no
        death", so a tree whose record authority was unparsable read
        exactly like a first run -- and a live-shaped save from BEFORE a
        death could then be offered for resuming, which is reloading past
        a death and is forbidden by name.  A first run genuinely has no
        manifest, so that keeps answering None; a manifest that EXISTS
        and cannot be read as evidence refuses, because the question then
        has no trustworthy answer.
        """
        if os.path.exists(self.manifest):
            os.unlink(self.manifest)
        self.assertIsNone(
            session.observed_death_frame(root=self.root),
            msg="a first run has no record and no death to report")
        with open(self.manifest, "w", encoding="utf-8") as handle:
            handle.write("this is not json at all\n")
        with self.assertRaises(session.RecordError) as caught:
            session.observed_death_frame(root=self.root)
        self.assertIn("cannot be read as evidence", str(caught.exception))

    def test_a_broken_record_stops_the_resume_probe(self):
        """The refusal has to reach the decision, not just the reader.

        probe_save_resume is where "continue or create" is decided, and
        the point of failing closed in the reader is that this caller
        does not get an answer it should not trust.
        """
        self.world("Fern Creek", characters=("#QQ==",))
        with open(self.manifest, "w", encoding="utf-8") as handle:
            handle.write("{not json\n")
        with self.assertRaises(session.SessionError):
            session.probe_save_resume(root=self.root)

    def test_an_amended_death_narration_is_still_observed(self):
        """The ledger is the sanctioned way to correct a narration.

        A row whose death screen was NAMED correctly through the
        amendment ledger has to be visible to this observation, or the
        proof and the observation would disagree about the same tree.
        """
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", note="type a letter",
                    commentary="Say it plainly.")
        rows = self.rows()
        recorded = rows[0]["action"]
        manifest_module = session.manifest
        digests = manifest_module.row_digests(self.manifest, self.root)
        manifest_module.append_amendment(
            os.path.join(self.root, manifest_module.AMENDMENTS_NAME),
            1, "2026-08-10T04:00:00.000Z", 1, "action",
            digests[1], recorded,
            "press 'Return' -- submit my last words",
            "the capture renders the engine's own last-words prompt",
            "the row did not name the screen the capture shows",
            root=self.root)
        self.assertEqual(
            session.observed_death_frame(root=self.root), 1,
            msg="an amendment that names the death screen is evidence")

    def test_both_readers_share_one_definition_of_a_death(self):
        """The proof and the observation must not drift apart."""
        self.assertIn(session.DEATH_LAST_WORDS_MARKER,
                      "press 'O' -- begin my last words")
        self.assertIn("post-death", session.DEATH_POST_MARKERS)

    def test_the_world_scan_is_available_without_the_refusal(self):
        """A live session recording its own death must not be refused.

        THE REGRESSION THIS FIX NEARLY INTRODUCED, pinned here because it
        is not obvious from either side.  Session._save_fingerprint calls
        this probe on EVERY step, and a session recording a legitimate
        death passes through exactly the refused state: the last-words
        keystroke is captured while the live save is still on disk,
        because the engine only moves it in cleanup_at_end() after the
        death screen finishes.  With the refusal unconditional, pressing
        the last-words key made every subsequent step raise -- so death,
        a PERMITTED ending, became impossible to record, several hundred
        keystrokes into a session.  Two of the mandatory-audit tests
        caught it; this one says why, next to the fix.
        """
        self.a_recorded_death()
        probe = session.probe_save_resume(
            self.save, None, self.root, refuse_recorded_death=False)
        # The scan still reports everything, including the evidence.
        self.assertEqual(len(probe.worlds), 1)
        self.assertEqual(probe.worlds[0].characters, ("#QQ==.sav",))
        self.assertEqual(probe.worlds[0].death_recorded_at, 2)
        # And the strict reading is still the default.
        with self.assertRaises(session.SessionError):
            session.probe_save_resume(self.save, None, self.root)


class SaveTreeConfinement(SessionFixture):
    """Finding 28: no descendant of the save tree may be a link."""

    def test_a_symlinked_world_is_refused(self):
        outside = os.path.join(self.directory, "elsewhere")
        os.makedirs(outside)
        with open(os.path.join(outside, session.SAVE_MASTER_NAME),
                  "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.symlink(outside, os.path.join(self.save, "Linked World"))
        with self.assertRaises(session.SessionError):
            session.probe_save_resume(self.save, None, self.root)

    def test_a_symlinked_character_save_is_refused(self):
        directory = self.world("Fern Creek", ())
        target = os.path.join(self.directory, "somebody-elses.sav")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{}")
        os.symlink(target, os.path.join(directory, "#QQ==.sav"))
        with self.assertRaises(session.SessionError):
            session.probe_save_resume(self.save, None, self.root)

    def test_a_symlinked_save_root_is_refused(self):
        shutil.rmtree(self.save)
        outside = os.path.join(self.directory, "outside-save")
        os.makedirs(outside)
        os.symlink(outside, self.save)
        with self.assertRaises(session.SessionError):
            session.probe_save_resume(self.save, None, self.root)

    def test_a_real_world_is_still_found(self):
        self.world()
        probe = session.probe_save_resume(self.save, None, self.root)
        self.assertTrue(probe.resume)
        self.assertEqual(probe.character_count, 1)


class OpenTimePreflights(SessionFixture):
    """What is decidable before the keystroke is decided at open.

    Two QA findings, one shape.  A manifest by another name and an
    append target that cannot be appended to are both settled by the
    filesystem alone, and both used to be discovered only when a row
    was written -- after a key had been delivered and a frame captured
    for it.  The keystroke is the one act this pipeline cannot take
    back, so spending one on a condition that was already true is a
    defect in ORDERING, and these tests hold the order.
    """

    def unopenable(self, **extra):
        """Assert opening refuses, and report the diagnostic."""
        arguments = {
            "manifest_path": self.manifest,
            "frames_dir": self.frames,
            "observations_path": self.observations,
            "capture_script": self.capture,
            "window_id": None,
            "root": self.root,
        }
        arguments.update(extra)
        with self.assertRaises(session.RecordError) as refused:
            session.Session(**arguments)
        return str(refused.exception)

    def test_a_manifest_by_another_name_is_refused_at_open(self):
        # The exact reproduction: a path INSIDE the tree, which
        # containment alone accepts, that is not the record.
        other = os.path.join(self.build, "other.jsonl")
        reason = self.unopenable(manifest_path=other)
        self.assertIn("manifest.jsonl", reason)
        self.assertIn("NOTHING HAS BEEN SENT", reason)
        self.assertEqual(os.listdir(self.frames), [])
        self.assertEqual(self.rows(), [])
        self.assertFalse(os.path.exists(other))

    def test_the_environment_cannot_smuggle_another_name_in(self):
        # $PLAYTHROUGH_MANIFEST is where such a value really comes from,
        # so the default branch must be held to the same rule.
        other = os.path.join(self.build, "other.jsonl")
        os.environ["PLAYTHROUGH_MANIFEST"] = other
        self.addCleanup(os.environ.pop, "PLAYTHROUGH_MANIFEST", None)
        with self.assertRaises(session.RecordError) as refused:
            session.Session(
                frames_dir=self.frames,
                observations_path=self.observations,
                capture_script=self.capture,
                window_id=None,
                root=self.root)
        self.assertIn("manifest.jsonl", str(refused.exception))

    def test_an_unappendable_sidecar_is_refused_before_the_key(self):
        # A directory in the sidecar's place is the portable stand-in
        # for the reported fault (chattr +i): the append fails at the
        # open, which is the only thing this module can act on.
        os.rmdir(self.build)
        os.makedirs(self.observations)
        sent = []
        original = session.send_key
        session.send_key = lambda window, key, timeout=None: sent.append(
            key)
        self.addCleanup(setattr, session, "send_key", original)
        reason = self.unopenable()
        self.assertIn("the telemetry sidecar", reason)
        self.assertIn("nothing has been sent", reason)
        self.assertEqual(sent, [])
        self.assertEqual(os.listdir(self.frames), [])
        self.assertEqual(self.rows(), [])

    def test_the_preflight_creates_no_record(self):
        # It must not manufacture the very file it is checking: an empty
        # manifest.jsonl is itself a problem every reader reports.
        opened = self.open_session()
        self.assertFalse(os.path.isfile(self.manifest))
        self.assertFalse(os.path.isfile(self.observations))
        self.assertEqual(opened.frame, 0)

    def test_an_existing_target_is_left_byte_for_byte(self):
        with open(self.observations, "w", encoding="utf-8") as handle:
            handle.write('{"frame": 1}\n')
        before = os.stat(self.observations)
        session.assert_append_target(
            self.observations, "the telemetry sidecar")
        after = os.stat(self.observations)
        self.assertEqual(before.st_size, after.st_size)
        with open(self.observations, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"frame": 1}\n')

    def test_a_directory_in_the_file_s_place_is_refused(self):
        target = os.path.join(self.build, "as_a_directory.jsonl")
        os.makedirs(target)
        with self.assertRaises(session.RecordError) as refused:
            session.assert_append_target(target, "the sidecar")
        self.assertIn("cannot be appended to", str(refused.exception))

    def test_an_absent_target_needs_a_directory_that_exists(self):
        missing = os.path.join(self.build, "gone", "sidecar.jsonl")
        with self.assertRaises(session.RecordError) as refused:
            session.assert_append_target(missing, "the sidecar")
        self.assertIn("is not", str(refused.exception))
        self.assertFalse(os.path.exists(os.path.dirname(missing)))
        # ... unless the caller is the one that creates it, which is
        # what append_observation() itself does for the sidecar.
        self.assertEqual(
            session.assert_append_target(
                missing, "the sidecar", create_parent=True),
            missing)
        self.assertTrue(os.path.isdir(os.path.dirname(missing)))
        self.assertFalse(os.path.exists(missing))


class TheAttestationIsPartOfTheRecord(SessionFixture):
    """A sidecar that falls behind the manifest is REPORTED.

    The reported failure: three steps whose telemetry append failed
    after their manifest rows were durable left the record eleven rows
    long and the sidecar eight, and `status` still said the record was
    sound -- because verify_record() had only ever compared the
    manifest with the frames.  The attestation is the only place the
    key that was pressed and the sidebar date line were written down,
    so a gap there is evidence lost and has to be visible.
    """

    def three_steps(self):
        """Record three ordinary steps and return the session."""
        opened = self.open_session()
        self.stub_window(opened)
        for key, reason in (("j", "south"), ("k", "north"),
                            ("h", "west")):
            opened.step(key, note=reason, commentary="Moving on.")
        return opened

    def keep_first_sidecar_row(self):
        """Leave one attestation, as a failed append would have."""
        with open(self.observations, "r", encoding="utf-8") as handle:
            first = handle.readlines()[0]
        with open(self.observations, "w", encoding="utf-8") as handle:
            handle.write(first)

    def test_a_complete_record_reports_nothing(self):
        opened = self.three_steps()
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(len(self.sidecar()), 3)
        self.assertEqual(opened.verify_record(), ())

    def test_a_shortfall_names_every_frame_it_lost(self):
        opened = self.three_steps()
        self.keep_first_sidecar_row()
        problems = opened.verify_record()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("2 recorded frame(s) have no telemetry row",
                      problems[0])
        self.assertIn("2, 3", problems[0])
        self.assertIn("observations.jsonl", problems[0])

    def test_the_frames_and_the_manifest_still_agree(self):
        # The primary record is intact in this state, which is exactly
        # why the old check reported nothing: the shortfall is a THIRD
        # comparison, not a restatement of the first two.
        self.three_steps()
        self.keep_first_sidecar_row()
        self.assertEqual(
            manifest.verify_manifest(
                self.manifest, self.frames, require_frames=True,
                root=self.root),
            [])

    def test_an_attestation_for_an_unrecorded_frame_is_reported(self):
        opened = self.three_steps()
        session.append_observation(
            self.observations, {"frame": 9, "key": "j"},
            require_durable=False, root=self.root)
        problems = opened.verify_record()
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("the manifest does not record", problems[0])
        self.assertIn("9", problems[0])

    def test_a_repeated_index_is_not_a_problem(self):
        # Deliberate: the sidecar is append-only and timeline.py reads
        # it with a last-row-wins rule so that a re-captured frame means
        # what it obviously means.  Calling that a defect here would
        # contradict the reader that consumes the file.
        opened = self.three_steps()
        row = dict(self.sidecar()[0])
        session.append_observation(
            self.observations, row, require_durable=False,
            root=self.root)
        self.assertEqual(opened.verify_record(), ())

    def test_a_torn_line_is_reported_rather_than_skipped(self):
        opened = self.three_steps()
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write('{"frame": 4, "key": "j"')
        problems = opened.verify_record()
        self.assertTrue(
            any("is not JSON" in problem for problem in problems),
            msg=problems)
        self.assertTrue(any("line 4" in problem for problem in problems),
                        msg=problems)

    def test_a_row_without_an_index_is_reported(self):
        opened = self.three_steps()
        session.append_observation(
            self.observations, {"file": "playthrough/frames/x.png"},
            require_durable=False, root=self.root)
        problems = opened.verify_record()
        self.assertTrue(
            any("which is not an index" in problem
                for problem in problems), msg=problems)

    def test_telemetry_with_no_manifest_at_all_is_reported(self):
        opened = self.open_session()
        session.append_observation(
            self.observations, {"frame": 1, "key": "j"},
            require_durable=False, root=self.root)
        problems = opened.verify_record()
        self.assertTrue(
            any("the manifest does not record" in problem
                for problem in problems), msg=problems)

    def test_the_reader_returns_the_rows_as_written(self):
        self.three_steps()
        rows = session.read_observations(self.observations, self.root)
        self.assertEqual([row["frame"] for row in rows], [1, 2, 3])
        self.assertEqual([row["key"] for row in rows], ["j", "k", "h"])

    def test_an_absent_sidecar_reads_as_no_rows(self):
        self.assertEqual(
            session.read_observations(self.observations, self.root), ())


class TheCaptureDigestIsSealedByTheStep(SessionFixture):
    """One step seals one frame's bytes, and refuses if it cannot.

    THE DEFECT THIS CLASS EXISTS FOR.  A security review observed that
    the step recorded a frame's geometry, its byte length and its
    luminance and never its CONTENT, and that the recovery path trusted
    the pixels it found on disk plus an mtime any writer can set.  So a
    same-sized, non-blank replacement PNG became a manifest row, a
    caption and a frame of the film with nothing objecting.

    The digest now travels twice: in the telemetry row for the frame it
    describes, and in the append-only ledger every later stage verifies
    against.  Both are written by the step that took the photograph, so
    neither can be produced afterwards for a frame nobody captured.
    """

    def ledger_path(self):
        """Where this tree's attestation ledger lives."""
        return os.path.join(self.root, *manifest.DIGESTS_REL_PARTS)

    def ledger(self):
        """Every attestation written so far."""
        if not os.path.isfile(self.ledger_path()):
            return []
        return manifest.read_frame_digests(self.ledger_path(), self.root)

    def one_step(self, key="j"):
        """Take one ordinary step and return the session."""
        opened = self.open_session()
        self.stub_window(opened)
        opened.step(key, commentary="Moving on.")
        return opened

    def test_the_telemetry_row_carries_the_digest(self):
        self.one_step()
        row = self.sidecar()[0]
        self.assertEqual(row["frame_sha256"], STUB_FRAME_SHA256)

    def test_the_declared_telemetry_schema_names_the_digest(self):
        """The column is part of the contract, not an extra.

        capture.sh reports it and this module persists it, so the mapping
        between the two is what proves the handoff is lossless.
        """
        self.assertIn(
            ("frame_sha256", "FRAME_SHA256"),
            session.OBSERVATION_FIELDS)

    def test_one_step_appends_one_attestation(self):
        self.one_step()
        ledger = self.ledger()
        self.assertEqual(len(ledger), 1)
        row = ledger[0]
        self.assertEqual(row["frame"], 1)
        self.assertEqual(row["sha256"], STUB_FRAME_SHA256)
        self.assertEqual(row["bytes"], len(b"stub"))
        self.assertEqual(
            row["attested"], manifest.DIGEST_AT_CAPTURE,
            msg=("an ordinary step establishes the digest at "
                 "publication, which is the strongest claim available"))
        self.assertIsNone(row["git_blob"])
        self.assertIsNone(row["git_commit"])

    def test_every_step_seals_its_own_frame(self):
        opened = self.open_session()
        self.stub_window(opened)
        for key in ("j", "k", "h"):
            opened.step(key, commentary="Moving on.")
        self.assertEqual([row["frame"] for row in self.ledger()],
                         [1, 2, 3])
        self.assertEqual(
            manifest.verify_frame_digests(
                self.rows(), self.ledger(), frames_dir=self.frames,
                root=self.root), [],
            msg="and the frames on disk match what was sealed")

    def test_a_substituted_frame_is_caught_by_the_ledger(self):
        """THE SUBSTITUTION EVERY STRUCTURAL CHECK PASSES."""
        self.one_step()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("nots")
        problems = manifest.verify_frame_digests(
            self.rows(), self.ledger(), frames_dir=self.frames,
            root=self.root)
        self.assertEqual(len(problems), 1, msg=problems)
        self.assertIn("not the bytes that were captured", problems[0])

    def test_a_payload_digest_that_does_not_match_the_file_refuses(self):
        """The digest is RE-MEASURED before a row exists.

        capture.sh's reading arrives in a payload, and a payload is a
        report.  Re-hashing the published file here is what makes the
        attestation an observation of that file rather than a claim about
        it -- and a mismatch means the frame changed between the two,
        which is precisely the event the digest was added to detect.
        """
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, frame=1, key="j",
            action="press 'j'", commentary="South.",
            payload={session.CAPTURE_MODE_KEY:
                     session.CAPTURE_MODE_PRODUCTION,
                     "FRAME_INDEX": "1",
                     "FRAME_NAME": "frame_00001.png",
                     "FRAME_FILE": "playthrough/frames/frame_00001.png",
                     "FRAME_PATH": os.path.join(
                         self.frames, "frame_00001.png"),
                     "FRAME_SHA256": "0" * 64,
                     "REAL_TS": FIXED_REAL_TS,
                     "CLOCK": "08:00:00",
                     "CLOCK_STATUS": "read",
                     "DATE": "Spring, day 61"})
        with self.assertRaises(session.SessionError) as caught:
            self.open_session()
        self.assertIn("sha256", str(caught.exception).lower())
        self.assertEqual(
            self.rows(), [],
            msg="no row is appended for a frame whose bytes moved")

    def test_a_payload_with_no_digest_refuses(self):
        """An absent digest is refused, not defaulted."""
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, frame=1, key="j",
            action="press 'j'", commentary="South.",
            payload={session.CAPTURE_MODE_KEY:
                     session.CAPTURE_MODE_PRODUCTION,
                     "FRAME_INDEX": "1",
                     "FRAME_NAME": "frame_00001.png",
                     "FRAME_FILE": "playthrough/frames/frame_00001.png",
                     "FRAME_PATH": os.path.join(
                         self.frames, "frame_00001.png"),
                     "REAL_TS": FIXED_REAL_TS,
                     "CLOCK": "08:00:00",
                     "CLOCK_STATUS": "read",
                     "DATE": "Spring, day 61"})
        with self.assertRaises(session.SessionError) as caught:
            self.open_session()
        self.assertIn("not a sha256", str(caught.exception))
        self.assertEqual(self.rows(), [])

    def test_a_recovered_frame_is_attested_as_a_recovery(self):
        """A weaker claim is recorded as the weaker claim.

        The frame was measured from a file after the fact rather than
        hashed at the instant of publication, and a ledger that dressed
        that up as `capture` would be worse than one that said nothing.
        """
        self.stub_window_module()
        with open(os.path.join(self.frames, "frame_00001.png"),
                  "w", encoding="utf-8") as handle:
            handle.write("stub")
        self.journal(
            phase=session.JOURNAL_PHASE_CAPTURED, frame=1, key="j",
            action="press 'j'", commentary="South.",
            payload={session.CAPTURE_MODE_KEY:
                     session.CAPTURE_MODE_PRODUCTION,
                     "FRAME_INDEX": "1",
                     "FRAME_NAME": "frame_00001.png",
                     "FRAME_FILE": "playthrough/frames/frame_00001.png",
                     "FRAME_PATH": os.path.join(
                         self.frames, "frame_00001.png"),
                     "FRAME_SHA256": STUB_FRAME_SHA256,
                     "REAL_TS": FIXED_REAL_TS,
                     "CLOCK": "08:00:00",
                     "CLOCK_STATUS": "read",
                     "DATE": "Spring, day 61"})
        self.open_session()
        ledger = self.ledger()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["attested"],
                         manifest.DIGEST_AT_RECOVERY)
        self.assertEqual(ledger[0]["sha256"], STUB_FRAME_SHA256)

    def test_the_ledger_is_never_rewritten_by_the_step(self):
        """Every attestation written stays written, byte for byte."""
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", commentary="South.")
        with open(self.ledger_path(), "rb") as handle:
            before = handle.read()
        opened.step("k", commentary="North.")
        with open(self.ledger_path(), "rb") as handle:
            after = handle.read()
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))


class TheCaptureFailureDiagnostic(SessionFixture):
    """A failure after the keystroke says how it is recovered.

    The abort reason names the journal and the same-index recovery.  It
    used to be stored and never printed, because the step re-raised the
    capturer's own message instead -- so the operator was told the frame
    was lost and not told it would be captured at the same index on the
    next invocation.
    """

    def test_the_capture_failure_names_the_journal(self):
        opened = self.open_session()
        self.stub_window(opened)
        os.environ["STUB_FAIL"] = "1"
        with self.assertRaises(session.CaptureError) as failed:
            opened.step("j", note="west along the fence",
                        commentary="West.")
        reason = str(failed.exception)
        self.assertIn(session.journal_path(self.root), reason)
        self.assertIn("captures this index", reason)
        self.assertEqual(reason, opened.aborted)
        # The capturer's own diagnostic is not lost: it is the chained
        # cause, so nothing about why the frame failed is thrown away.
        self.assertIn("capture.sh exited 4",
                      str(failed.exception.__cause__))

    def test_the_exception_class_is_preserved(self):
        # The branch also sees a capture that timed out (plain
        # SessionError) and a capturer that has gone missing
        # (ToolMissing), and the exit status tells those apart -- so the
        # message is replaced and the class is not.
        opened = self.open_session()
        self.stub_window(opened)

        def missing(index):
            """Stand in for a capturer that cannot be run."""
            raise session.ToolMissing("the capturer is gone")

        opened._capture_frame = missing
        with self.assertRaises(session.ToolMissing) as failed:
            opened.step("j", note="west", commentary="West.")
        self.assertIn("captures this index", str(failed.exception))
        self.assertEqual(
            session._status_for(failed.exception), session.EXIT_USAGE)


class RelativeReporting(unittest.TestCase):
    """Finding 18: a summary discloses no host path."""

    def test_a_tracked_artifact_is_reported_relative(self):
        self.assertEqual(
            manifest.relative_to_repo("playthrough/manifest.jsonl"),
            os.path.join("playthrough", "manifest.jsonl"))

    def test_an_outside_path_discloses_no_location(self):
        reported = manifest.relative_to_repo("/etc/hostname")
        self.assertNotIn("/etc", reported)
        self.assertTrue(reported.endswith("hostname"))

    def test_the_step_payload_carries_no_absolute_path(self):
        # The command line's own contract, read off the source of truth
        # rather than by running a session: every path it emits goes
        # through relative_to_repo().
        source = os.path.join(
            os.path.dirname(os.path.abspath(session.__file__)),
            "session.py")
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        for emitted in ('_emit("MANIFEST"', '_emit("FRAME_PATH"',
                        '_emit("OBSERVATIONS"', '_emit("FRAMES_DIR"'):
            start = text.find(emitted)
            self.assertNotEqual(start, -1, msg=emitted)
            window = text[start:start + 160]
            self.assertIn("relative_to_repo", window, msg=emitted)


class MenuHotkeyCollision(SessionFixture):
    """The permitted door may not be taken by its own letter.

    src/main_menu.cpp declares "C<u|U>stom Character" in the new-game
    submenu (:476) and "T<u|U>torial Game" on the top row (:466) -- the
    same two letters -- and runtime testing showed the top row wins: the
    submenu folds away and the highlight comes to rest on the tutorial.

    THE DEFECT THIS CLASS EXISTS FOR, IN ITS SECOND FORM.  This used to be
    an ADVISORY: the code proved from the engine's own declarations that
    the keystroke lands on a forbidden entry, printed that proof, and then
    delivered the key anyway.  A security review named it exactly -- a
    control that establishes a violation and permits it is not a control
    -- so it is a refusal now, raised before the journal and before
    delivery.  The tests below hold BOTH halves: the refusal, and the fact
    that ordinary in-world play with the same letter is untouched.
    """

    def in_world(self, opened):
        """Put the session's observed phase in the world.

        The phase is normally reached by photographing a sidebar; a step
        that only needs to be in-world sets it directly, which is what
        the recovery path does when it reads a sidebar row back out of the
        record.
        """
        opened._ui_phase = session.UI_PHASE_IN_WORLD

    def test_the_letter_is_refused_when_the_row_says_it_is_that_door(
            self):
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.KeyRejected) as caught:
            opened.step("u", commentary="The custom sheet, not a dice "
                                        "roll.",
                        note="open the custom character entry")
        message = str(caught.exception)
        self.assertIn("REFUSED", message)
        self.assertIn("main_menu.cpp:466", message)
        self.assertIn("T<u|U>torial Game", message)
        self.assertIn("walk the top row", message)
        self.assertEqual(
            self.sent, [],
            msg="the key must not be delivered")
        self.assertEqual(
            self.rows(), [],
            msg="and no row may exist for a keystroke that never landed")
        self.assertEqual(self.sidecar(), [])
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)),
            msg=("the refusal precedes the pre-send journal, so there is "
                 "nothing for a later run to recover"))
        self.assertEqual(
            opened.frame, 0,
            msg="and the frame counter did not move")

    def test_the_session_stays_usable_after_the_refusal(self):
        """Nothing happened, so the next keystroke is an ordinary one."""
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.KeyRejected):
            opened.step("U", commentary="Open the custom creator.",
                        note="open the custom character entry")
        opened.step("Right", commentary="Right along the top row.",
                    note="move right along the top row")
        self.assertEqual(self.sent, ["Right"])
        self.assertEqual(len(self.rows()), 1)

    def test_ordinary_play_with_the_same_letter_is_untouched(self):
        """An in-world "u" is the north-east step and always allowed."""
        opened = self.open_session()
        self.stub_window(opened)
        self.in_world(opened)
        opened.step("u", commentary="Past the chair, north-east.",
                    note="step north-east into the next room")
        self.assertEqual(self.sent, ["u"])
        self.assertEqual(len(self.rows()), 1)

    def test_even_odd_commentary_in_the_world_is_not_refused(self):
        """The phase is the load-bearing condition, not the wording.

        A survivor may legitimately narrate the words "custom character"
        while in the world -- reading a note, remembering the creator --
        and refusing a movement key over a sentence would be exactly the
        over-reach the phase test prevents.
        """
        opened = self.open_session()
        self.stub_window(opened)
        self.in_world(opened)
        opened.step("u", commentary="I think of the custom character I "
                                    "sketched, and step north-east.",
                    note="step north-east into the next room")
        self.assertEqual(self.sent, ["u"])

    def test_the_letter_is_allowed_at_a_menu_when_it_is_not_that_door(
            self):
        """The wording is the second condition, and it is required.

        A colliding letter pressed at a menu for some other reason -- and
        said to be for some other reason -- is not this defect, and the
        refusal does not reach it.
        """
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("u", commentary="Up one line in the option list.",
                    note="move up one line in the list")
        self.assertEqual(self.sent, ["u"])

    def test_both_letters_are_refused(self):
        for key in session.MENU_HOTKEY_COLLISION:
            with self.subTest(key=key):
                self.setUp()
                opened = self.open_session()
                self.stub_window(opened)
                with self.assertRaises(session.KeyRejected):
                    opened.step(
                        key, commentary="Open the custom sheet now.",
                        note="open the custom character entry")
                self.assertEqual(self.sent, [])

    def test_no_advisory_function_survives_in_the_module(self):
        """Asserted against the module, so it cannot be reintroduced.

        The old name is the name of the defect: an advisory here is the
        thing the review objected to.
        """
        self.assertFalse(
            hasattr(session.Session, "_advise_on_menu_hotkey"),
            msg=("the advisory was REPLACED by a refusal, not kept "
                 "beside it"))
        self.assertTrue(
            hasattr(session.Session, "_assert_menu_hotkey_permitted"))

    def test_the_verified_route_is_stated_and_letter_free(self):
        route = " ".join(session.MENU_CUSTOM_CHARACTER_ROUTE).lower()
        for expected in ("left/right", "up/down", "read the capture",
                         "return"):
            self.assertIn(expected, route)
        self.assertEqual(session.MENU_HOTKEY_COLLISION, ("u", "U"))
        self.assertEqual(session.MENU_TUTORIAL_ENTRY,
                         "T<u|U>torial Game")


class ObservedEffectHelpers(unittest.TestCase):
    """The guard's pure parts, which decide what a row may claim.

    Runtime testing of the first recorded session found rows written
    from the keystroke that was INTENDED rather than from what the
    capture afterwards showed -- typing that never reached the field
    because a Yes/No question had the screen, steps that never happened
    because the map did not move.  These assertions hold the marker
    convention that makes such a row say so.
    """

    def test_the_marker_is_appended_and_the_note_survives(self):
        self.assertEqual(
            session.annotate_action(
                "press 'e' -- aimed at the world name",
                session.EFFECT_UNCHANGED),
            "press 'e' -- aimed at the world name; "
            "nothing on the screen changed")
        self.assertEqual(
            session.annotate_action(
                "press 'k' -- try to step north",
                session.EFFECT_OUTSIDE_MAP),
            "press 'k' -- try to step north; "
            "nothing in the map column changed")

    def test_a_bare_identity_gains_a_note_rather_than_a_semicolon(self):
        annotated = session.annotate_action(
            "press 'k'", session.EFFECT_UNCHANGED)
        self.assertEqual(
            annotated,
            "press 'k' -- nothing on the screen changed")
        # It must still be a derived action for the key it names.
        self.assertEqual(
            session.assert_action_derived("k", annotated), annotated)

    def test_the_marker_is_added_at_most_once(self):
        once = session.annotate_action(
            "press 'e' -- x", session.EFFECT_UNCHANGED)
        twice = session.annotate_action(once, session.EFFECT_UNCHANGED)
        self.assertEqual(once, twice)

    def test_the_verdicts_that_annotate_nothing(self):
        for verdict in (session.EFFECT_CHANGED, session.EFFECT_FIRST,
                        session.EFFECT_UNKNOWN, "nonsense", None):
            with self.subTest(verdict=verdict):
                self.assertEqual(
                    session.annotate_action("press 'j' -- south",
                                            verdict),
                    "press 'j' -- south")

    def test_a_verdict_is_read_from_an_effect_or_a_string(self):
        self.assertEqual(
            session.verdict_of(session.ObservedEffect(
                session.EFFECT_OUTSIDE_MAP)),
            session.EFFECT_OUTSIDE_MAP)
        self.assertEqual(
            session.verdict_of(session.EFFECT_UNCHANGED),
            session.EFFECT_UNCHANGED)
        self.assertEqual(session.verdict_of("typo"),
                         session.EFFECT_UNKNOWN)

    def test_the_map_column_is_the_side_the_sidebar_is_not_on(self):
        # The measured layout of this record: a 352 px sidebar at
        # x=1568 inside a 1920x1080 root.
        self.assertEqual(
            session.map_column_geometry(_FakeRect(1568, 352),
                                        1920, 1080),
            "1568x1080+0+0")
        # A left-hand sidebar leaves the map on the right.
        self.assertEqual(
            session.map_column_geometry(_FakeRect(0, 352), 1920, 1080),
            "1568x1080+352+0")
        # Nonsense is refused rather than guessed.
        for rect in (_FakeRect(1568, 500), _FakeRect(-1, 352),
                     _FakeRect(0, 1920)):
            with self.subTest(rect=(rect.x, rect.width)):
                self.assertIsNone(
                    session.map_column_geometry(rect, 1920, 1080))
        self.assertIsNone(
            session.map_column_geometry(object(), 1920, 1080))

    def test_movement_wording_is_recognised(self):
        for text in ("press 'k' -- step north again",
                     "press 'h' -- keep going west",
                     "I walked one, onto a chair"):
            with self.subTest(text=text):
                self.assertTrue(session.movement_claim(text))
        for text in ("press 'Return' -- open the box", None, 42):
            with self.subTest(text=text):
                self.assertFalse(session.movement_claim(text))

    def test_the_sidecar_records_the_verdict_and_its_numbers(self):
        payload = {
            "FRAME_INDEX": "7",
            "FRAME_FILE": "playthrough/frames/frame_00007.png",
            "REAL_TS": FIXED_REAL_TS,
        }
        row = session.observation_row(
            7, payload, key="e", action="press 'e' -- x",
            effect=session.ObservedEffect(
                session.EFFECT_OUTSIDE_MAP, screen_pixels=138,
                map_pixels=0, map_box=None))
        self.assertEqual(row["effect"], session.EFFECT_OUTSIDE_MAP)
        self.assertEqual(row["screen_diff_px"], 138)
        self.assertEqual(row["map_diff_px"], 0)
        self.assertNotIn("map_diff_box", row)
        plain = session.observation_row(
            7, payload, key="e", action="press 'e' -- x",
            effect=session.EFFECT_FIRST)
        self.assertEqual(plain["effect"], session.EFFECT_FIRST)
        with self.assertRaises(session.RecordError):
            session.observation_row(
                7, payload, key="e", action="press 'e' -- x",
                effect="whatever")


class _FakeRect(object):
    """The two fields the map-column computation reads off a rect."""

    def __init__(self, x, width):
        self.x = x
        self.width = width

    def __str__(self):
        return "%dx?+%d+?" % (self.width, self.x)


def _png(path, width, height, pixels):
    """Write a minimal 8-bit RGB PNG.  Standard library only.

    `pixels` is called with (x, y) and returns an (r, g, b) triple, so a
    test can draw exactly the region it wants to differ.
    """
    import struct
    import zlib

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        for x in range(width):
            raw.extend(pixels(x, y))

    def chunk(kind, payload):
        body = kind + payload
        crc = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return struct.pack(">I", len(payload)) + body + crc

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(chunk(b"IHDR", struct.pack(
            ">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        handle.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        handle.write(chunk(b"IEND", b""))
    return path


class ObservedEffectMeasurement(unittest.TestCase):
    """The guard against real image files, through the real tool.

    Nothing here runs the engine or opens a display: the captures are
    written by the helper above, and `convert` -- which capture.sh
    already requires -- does the measuring.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="cata_effect_")
        self.addCleanup(shutil.rmtree, self.directory, True)
        session.reset_advisories()
        try:
            session._verified(session.CONVERT)
        except session.ToolMissing as err:  # pragma: no cover
            self.skipTest("convert is unavailable: %s" % err)

    def frame(self, name, mark=None):
        """Write a 40x20 capture, optionally marking one pixel."""
        def pixels(x, y):
            if mark is not None and (x, y) == mark:
                return (255, 255, 255)
            return (0, 0, 0)
        return _png(os.path.join(self.directory, name), 40, 20, pixels)

    def test_identical_captures_are_unchanged(self):
        first = self.frame("a.png")
        second = self.frame("b.png")
        effect = session.classify_effect(
            first, second, map_geometry="20x20+0+0")
        self.assertEqual(effect.verdict, session.EFFECT_UNCHANGED)
        self.assertEqual(effect.screen_pixels, 0)

    def test_a_change_outside_the_map_column_is_named_as_such(self):
        first = self.frame("a.png")
        second = self.frame("b.png", mark=(30, 5))
        effect = session.classify_effect(
            first, second, map_geometry="20x20+0+0")
        self.assertEqual(effect.verdict, session.EFFECT_OUTSIDE_MAP)
        self.assertEqual(effect.screen_pixels, 1)
        self.assertEqual(effect.map_pixels, 0)

    def test_a_change_inside_the_map_column_is_a_change(self):
        first = self.frame("a.png")
        second = self.frame("b.png", mark=(4, 6))
        effect = session.classify_effect(
            first, second, map_geometry="20x20+0+0")
        self.assertEqual(effect.verdict, session.EFFECT_CHANGED)
        self.assertEqual(effect.map_pixels, 1)
        self.assertEqual(effect.map_box, "1x1+4+6")

    def test_no_predecessor_is_reported_rather_than_judged(self):
        effect = session.classify_effect(None, self.frame("a.png"))
        self.assertEqual(effect.verdict, session.EFFECT_FIRST)
        self.assertIsNone(effect.screen_pixels)

    def test_an_unmeasurable_pair_is_unknown_not_changed(self):
        broken = os.path.join(self.directory, "broken.png")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("not a png")
        effect = session.classify_effect(broken, self.frame("a.png"))
        self.assertEqual(effect.verdict, session.EFFECT_UNKNOWN)

    def test_a_measurement_counts_pixels_not_bytes(self):
        first = self.frame("a.png")
        second = self.frame("b.png", mark=(1, 1))
        pixels, box = session.measure_difference(first, second)
        self.assertEqual(pixels, 1)
        self.assertEqual(box, "1x1+1+1")
        pixels, box = session.measure_difference(first, first)
        self.assertEqual(pixels, 0)
        self.assertIsNone(box)

    def test_a_region_measurement_measures_THAT_region(self):
        """The region's own count and box, not the whole screen's.

        Nothing asserted this, and the omission let a refactor return the
        whole-screen count from a call that named a region -- undetected,
        because the two coincide whenever every changed pixel happens to
        fall inside the crop.  Here they cannot coincide: one changed
        pixel is inside the region and two are outside it.
        """
        first = self.frame("a.png")
        second = self.frame("b.png", mark=(4, 6))
        _png(second, 40, 20,
             lambda x, y: (255, 255, 255)
             if (x, y) in ((4, 6), (30, 5), (31, 5)) else (0, 0, 0))
        whole, whole_box = session.measure_difference(first, second)
        self.assertEqual(whole, 3)
        self.assertEqual(whole_box, "28x2+4+5")
        region, region_box = session.measure_difference(
            first, second, geometry="20x20+0+0")
        self.assertEqual(region, 1)
        self.assertEqual(region_box, "1x1+4+6")

    def test_one_decode_measures_what_two_decodes_measured(self):
        """The screen and the region together, value for value."""
        first = self.frame("a.png")
        second = self.frame("b.png")
        _png(second, 40, 20,
             lambda x, y: (255, 255, 255)
             if (x, y) in ((4, 6), (5, 7), (30, 5)) else (0, 0, 0))
        geometry = "20x20+0+0"
        whole, _whole_box = session.measure_difference(first, second)
        region, region_box = session.measure_difference(
            first, second, geometry=geometry)
        self.assertEqual(
            session.measure_difference_pair(first, second, geometry),
            (whole, region, region_box))

    def test_one_pair_costs_one_convert(self):
        """Two decodes of the same two captures bought nothing."""
        first = self.frame("a.png")
        second = self.frame("b.png", mark=(4, 6))
        processes = []
        original = session._run

        def counting(command, timeout, what, env=None, cwd=None):
            if command and os.path.basename(command[0]) == "convert":
                processes.append(what)
            return original(command, timeout, what, env, cwd)

        session._run = counting
        self.addCleanup(setattr, session, "_run", original)
        effect = session.classify_effect(
            first, second, map_geometry="20x20+0+0")
        self.assertEqual(effect.verdict, session.EFFECT_CHANGED)
        self.assertEqual(effect.screen_pixels, 1)
        self.assertEqual(effect.map_pixels, 1)
        self.assertEqual(effect.map_box, "1x1+4+6")
        self.assertEqual(len(processes), 1)

    def test_an_unusable_crop_still_reports_the_screen(self):
        """Degradation is unchanged: one extra process, on failure only.

        A crop larger than the frame cannot be measured, and the screen's
        own verdict must survive that -- it was measured in the same
        graph, but the graph failed, so the simpler question is asked
        again on its own.
        """
        first = self.frame("a.png")
        second = self.frame("b.png", mark=(4, 6))
        processes = []
        original = session._run

        def counting(command, timeout, what, env=None, cwd=None):
            if command and os.path.basename(command[0]) == "convert":
                processes.append(what)
            return original(command, timeout, what, env, cwd)

        session._run = counting
        self.addCleanup(setattr, session, "_run", original)
        effect = session.classify_effect(
            first, second, map_geometry="not-a-geometry")
        self.assertEqual(effect.verdict, session.EFFECT_CHANGED)
        self.assertEqual(effect.screen_pixels, 1)
        self.assertIsNone(effect.map_pixels)
        self.assertEqual(len(processes), 2)

    def test_an_unusable_crop_over_identical_captures_is_unchanged(self):
        first = self.frame("a.png")
        second = self.frame("b.png")
        effect = session.classify_effect(
            first, second, map_geometry="not-a-geometry")
        self.assertEqual(effect.verdict, session.EFFECT_UNCHANGED)
        self.assertEqual(effect.screen_pixels, 0)
        self.assertEqual(effect.map_pixels, 0)

    def test_a_broken_capture_with_a_crop_is_still_unknown(self):
        broken = os.path.join(self.directory, "broken.png")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("not a png")
        effect = session.classify_effect(
            broken, self.frame("a.png"), map_geometry="20x20+0+0")
        self.assertEqual(effect.verdict, session.EFFECT_UNKNOWN)
        self.assertIsNone(effect.screen_pixels)

    def test_a_measurement_of_no_region_at_all_is_refused(self):
        first = self.frame("a.png")
        with self.assertRaises(session.CaptureError):
            session._difference_command(first, first, ())

    def test_a_million_changed_pixels_is_still_a_count(self):
        """The scene-transition case, which used to be UNMEASURABLE.

        An FX result is printed with six significant digits by default,
        so a count of 1,027,832 came back as `1.02783e+06` -- not a
        count -- and every pair differing by a million pixels or more was
        reported as unmeasurable.  A whole-screen change is exactly what
        a scene transition is, so the verdict was unavailable for the
        most visually significant steps of a session.  Found while
        running the retroactive pass over the committed record; the frame
        here is deliberately larger than a megapixel for that reason.
        """
        def dark(x, y):
            return (0, 0, 0)

        def lit(x, y):
            # Inset on every side, because -trim takes its border colour
            # from the corner pixel: a difference reaching the corner has
            # no border to remove and the box comes back degenerate.  The
            # COUNT is what this test is about; the inset keeps the box
            # meaningful alongside it.
            inside = 50 <= x < 1150 and 10 <= y < 990
            return (255, 255, 255) if inside else (0, 0, 0)

        first = _png(os.path.join(self.directory, "wide-a.png"),
                     1200, 1000, dark)
        second = _png(os.path.join(self.directory, "wide-b.png"),
                      1200, 1000, lit)
        count, box = session.measure_difference(first, second)
        self.assertEqual(count, 1100 * 980)
        self.assertGreater(count, 1000000)
        self.assertEqual(box, "1100x980+50+10")
        effect = session.classify_effect(first, second)
        self.assertEqual(effect.verdict, session.EFFECT_CHANGED)
        self.assertEqual(effect.screen_pixels, 1100 * 980)


class ObservedEffectInTheStep(SessionFixture):
    """A swallowed keystroke cannot be written up as though it landed."""

    STUB = """#!/bin/sh
set -eu
index="${FRAME_INDEX}"
name="$(printf 'frame_%05d.png' "${index}")"
path="${STUB_FRAMES}/${name}"
source="${STUB_PNG_DEFAULT}"
eval "override=\\${STUB_PNG_${index}:-}"
if [ -n "${override}" ]; then
    source="${override}"
fi
cp "${source}" "${path}"
digest="$(sha256sum -- "${path}" | cut -d' ' -f1)"
cat <<PAYLOAD
CAPTURE_MODE=production
FRAME_INDEX=${index}
FRAME_NAME=${name}
FRAME_FILE=playthrough/frames/${name}
FRAME_PATH=${path}
FRAME_SHA256=${digest}
FRAME_GEOMETRY=40x20
REAL_TS=__REAL_TS__
CAPTURE_TOOL=stub
LUMA_MEAN=0.27
LUMA_STDDEV=0.19
CLOCK_RECT=8x20+32+0
CLOCK_RECT_FROM=given
CLOCK_SOURCE=stub
CLOCK_STATUS=exact
CLOCK=08:15:33
TIME_PHRASE=
DATE=Spring, day 61
DATE_STATUS=read
OBSERVATIONS=${STUB_OBSERVATIONS}
PAYLOAD
""".replace("__REAL_TS__", FIXED_REAL_TS)

    def setUp(self):
        super(ObservedEffectInTheStep, self).setUp()
        try:
            session._verified(session.CONVERT)
        except session.ToolMissing as err:  # pragma: no cover
            self.skipTest("convert is unavailable: %s" % err)
        with open(self.capture, "w", encoding="utf-8") as handle:
            handle.write(self.STUB)
        os.chmod(self.capture, 0o755)
        self.blank = self.png("blank.png")
        self.set_env("STUB_PNG_DEFAULT", self.blank)
        # The sidebar crop the guard resolves the map column from.  It
        # is substituted rather than computed because the real
        # computation resolves the COMMITTED layout -- 44 cells, 352 px
        # at x=1568 in a 1920x1080 root -- which cannot be reconciled
        # with a 40x20 stand-in capture, and writing 1920x1080 captures
        # here would test PNG compression rather than the guard.  The
        # substitution keeps the same shape: a narrow column at the
        # right-hand edge, so the map column is everything left of it.
        original = ocr_clock.resolve_rect
        self.addCleanup(
            setattr, ocr_clock, "resolve_rect", original)
        ocr_clock.resolve_rect = lambda *args, **kwargs: (
            _FakeRect(32, 8), 16)

    def set_env(self, name, value):
        previous = os.environ.get(name)
        os.environ[name] = value
        self.addCleanup(self._restore, name, previous)

    def png(self, name, mark=None):
        path = os.path.join(self.directory, name)

        def pixels(x, y):
            if mark is not None and (x, y) == mark:
                return (255, 255, 255)
            return (0, 0, 0)
        return _png(path, 40, 20, pixels)

    def test_an_identical_capture_makes_the_row_say_so(self):
        opened = self.open_session()
        self.stub_window(opened)
        first = opened.step("F", commentary="Fern Creek.",
                            note="the first letter of the name")
        self.assertEqual(first.effect, session.EFFECT_FIRST)
        self.assertNotIn(session.MARKER_UNCHANGED, first.action)
        second = opened.step(
            "e", commentary="Keep spelling.",
            note="aimed at the world name")
        self.assertEqual(second.effect, session.EFFECT_UNCHANGED)
        self.assertTrue(
            second.action.endswith("; " + session.MARKER_UNCHANGED),
            second.action)
        rows = self.rows()
        self.assertEqual(rows[1]["action"], second.action)
        self.assertEqual(self.sidecar()[1]["effect"],
                         session.EFFECT_UNCHANGED)
        self.assertEqual(self.sidecar()[1]["screen_diff_px"], 0)
        self.assertFalse(second.screen_moved)

    def test_a_change_beside_the_map_makes_the_row_say_so(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("k", commentary="North.", note="step north")
        self.set_env("STUB_PNG_2", self.png("counter.png", mark=(36, 3)))
        second = opened.step(
            "k", commentary="Two steps.", note="step north again")
        self.assertEqual(second.effect, session.EFFECT_OUTSIDE_MAP)
        self.assertTrue(
            second.action.endswith("; " + session.MARKER_OUTSIDE_MAP),
            second.action)
        sidecar = self.sidecar()[1]
        self.assertEqual(sidecar["map_diff_px"], 0)
        self.assertEqual(sidecar["screen_diff_px"], 1)
        self.assertTrue(second.screen_moved)

    def test_a_real_change_leaves_the_row_alone(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("k", commentary="North.", note="step north")
        self.set_env("STUB_PNG_2", self.png("moved.png", mark=(5, 9)))
        second = opened.step(
            "k", commentary="And again.", note="step north again")
        self.assertEqual(second.effect, session.EFFECT_CHANGED)
        self.assertEqual(second.action,
                         "press 'k' -- step north again")
        self.assertEqual(self.sidecar()[1]["map_diff_px"], 1)


class TheRetroactiveEffectPass(SessionFixture):
    """Runtime QA finding: rows written before the guard existed.

    The observed-effect guard compares each capture with the one before
    it and appends `; nothing on the screen changed` when they are
    identical.  It was written AFTER a QA pass found rows narrating an
    effect their own capture contradicts, so the frames taken before it
    exists carry no marker even where the pixels call for one.

    THE PASS THAT CLOSES THAT RESIDUE MAY NOT TOUCH THE RECORD.  A
    security review found the earlier version rewriting the manifest row
    and its telemetry attestation in place, one after the other, and
    named both defects: a mechanism able to rewrite captured evidence
    makes every derivative deniable, and two sequential rewrites leave a
    window in which a crash splits the record.  So the measurement is
    reported, and with --amend it is APPENDED to
    playthrough/amendments.jsonl -- one artifact, one locked durable
    append -- while the row and the sidecar stay byte for byte as the
    session wrote them.  These tests are what keep it that way.
    """

    def setUp(self):
        super(TheRetroactiveEffectPass, self).setUp()
        try:
            session._verified(session.CONVERT)
        except session.ToolMissing as err:  # pragma: no cover
            self.skipTest("convert is unavailable: %s" % err)

    def paint(self, index, mark=None):
        """Overwrite one recorded capture with a real 40x20 PNG."""
        def pixels(x, y):
            if mark is not None and (x, y) == mark:
                return (255, 255, 255)
            return (0, 0, 0)
        return _png(
            os.path.join(self.frames,
                         manifest.FRAME_NAME_FORMAT % index),
            40, 20, pixels)

    def record(self, count):
        """Record `count` steps, then give each one a real capture."""
        opened = self.open_session()
        self.stub_window(opened)
        for index in range(1, count + 1):
            opened.step("j", note="step south past the counter",
                        commentary="South, along the aisle.")
            self.assertEqual(len(self.rows()), index)
        return opened

    def ledger(self):
        """Return the amendment rows written so far."""
        path = os.path.join(self.root, manifest.AMENDMENTS_NAME)
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_a_swallowed_keystroke_is_marked_from_its_own_pixels(self):
        opened = self.record(3)
        self.paint(1)
        self.paint(2, mark=(5, 5))
        self.paint(3, mark=(5, 5))     # identical to frame 2
        reported = opened.annotate_recorded_effects()
        self.assertEqual([one.frame for one in reported], [1, 2, 3])
        self.assertEqual(reported[0].verdict, session.EFFECT_FIRST)
        self.assertEqual(reported[1].verdict, session.EFFECT_CHANGED)
        self.assertEqual(reported[2].verdict, session.EFFECT_UNCHANGED)
        self.assertEqual(reported[2].screen_pixels, 0)
        self.assertTrue(reported[2].marked)
        self.assertFalse(reported[2].amended)
        # Reported only: nothing is written anywhere without --amend.
        self.assertNotIn(session.MARKER_UNCHANGED,
                         self.rows()[2]["action"])
        self.assertEqual(self.ledger(), [])

    def test_the_pass_leaves_both_evidence_files_byte_identical(self):
        """Code review finding: 26 captured rows had been rewritten.

        The measurement is worth making and worth reading.  Writing it
        into a captured row is not: it changed what the record said about
        keystrokes already pressed, and the change reached the timeline,
        the transcripts, the subtitles and the film.  So the pass reports
        and the files do not move -- proved here by bytes rather than by
        reading the fields back.
        """
        opened = self.record(3)
        for index in (1, 2, 3):
            self.paint(index, mark=(5, 5))
        before_record = _bytes_of(self.manifest)
        before_sidecar = _bytes_of(self.observations)
        reported = opened.annotate_recorded_effects()
        self.assertEqual(
            [one.marked for one in reported], [False, True, True])
        self.assertEqual(_bytes_of(self.manifest), before_record)
        self.assertEqual(_bytes_of(self.observations), before_sidecar)

    def test_running_it_twice_still_changes_nothing(self):
        opened = self.record(2)
        self.paint(1, mark=(5, 5))
        self.paint(2, mark=(5, 5))
        before = _bytes_of(self.manifest)
        first = opened.annotate_recorded_effects()
        second = opened.annotate_recorded_effects()
        self.assertEqual([one.extended for one in first],
                         [one.extended for one in second])
        self.assertEqual(_bytes_of(self.manifest), before)

    def test_no_rewrite_surface_survives_on_either_file(self):
        """A re-introduction would be a one-function change.

        Both halves were removed together, because correcting one file
        and not the other would trade a narration defect for a
        reconciliation defect -- and correcting both was two renames that
        could not be the single transaction they claimed to be.
        """
        for name in ("extend_observation_action",
                     "extend_observation_actions",
                     "plan_observation_extensions",
                     "publish_observation_extensions",
                     "ObservationExtensionPlan",
                     "_rewrite_observations"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(session, name))
        for name in ("extend_action", "extend_actions",
                     "plan_action_extensions",
                     "publish_action_extensions", "_rewrite_rows"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(manifest, name))

    def test_the_measurement_takes_no_apply_argument(self):
        opened = self.record(1)
        self.paint(1)
        with self.assertRaises(TypeError):
            opened.annotate_recorded_effects(apply=True)

    def test_amending_appends_a_ledger_row_and_leaves_the_record(self):
        opened = self.record(2)
        self.paint(1, mark=(5, 5))
        self.paint(2, mark=(5, 5))
        before = self.rows()
        sidecar = self.sidecar()
        amended = opened.annotate_recorded_effects(amend=True)
        self.assertTrue(amended[1].amended)
        # THE RECORD DID NOT MOVE -- neither file, not one field.
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.sidecar(), sidecar)
        # And the correction is in the ledger, bound to the row's bytes.
        ledger = self.ledger()
        self.assertEqual(len(ledger), 1)
        row = ledger[0]
        self.assertEqual(list(row), list(manifest.AMENDMENT_FIELDS))
        self.assertEqual(row["amendment"], 1)
        self.assertEqual(row["frame"], 2)
        self.assertEqual(row["field"], "action")
        self.assertEqual(row["recorded"], before[1]["action"])
        self.assertEqual(
            row["amended"],
            before[1]["action"] + session.MARKER_SEPARATOR +
            session.MARKER_UNCHANGED)
        digests = manifest.row_digests(self.manifest, root=self.root)
        self.assertEqual(row["source_sha256"], digests[2])
        self.assertIn("0 changed pixel(s)", row["basis"])
        self.assertTrue(row["reason"])

    def test_the_ledger_resolves_onto_a_derivative_and_verifies(self):
        opened = self.record(2)
        self.paint(1, mark=(5, 5))
        self.paint(2, mark=(5, 5))
        opened.annotate_recorded_effects(amend=True)
        rows = manifest.read_rows(self.manifest, root=self.root)
        ledger = manifest.read_amendments(
            os.path.join(self.root, manifest.AMENDMENTS_NAME),
            self.root)
        resolved, touched = manifest.resolve_rows(rows, ledger)
        self.assertEqual(touched, (2,))
        self.assertIn(session.MARKER_UNCHANGED, resolved[1]["action"])
        self.assertNotIn(session.MARKER_UNCHANGED, rows[1]["action"])
        self.assertEqual(
            manifest.verify_amendments(
                os.path.join(self.root, manifest.AMENDMENTS_NAME),
                self.manifest, root=self.root),
            [])

    def test_one_narration_carries_one_amendment(self):
        opened = self.record(2)
        self.paint(1, mark=(5, 5))
        self.paint(2, mark=(5, 5))
        opened.annotate_recorded_effects(amend=True)
        opened.annotate_recorded_effects(amend=True)
        self.assertEqual(len(self.ledger()), 1)

    def test_a_changed_capture_is_never_amended(self):
        opened = self.record(2)
        self.paint(1)
        self.paint(2, mark=(7, 7))
        reported = opened.annotate_recorded_effects(amend=True)
        self.assertEqual(reported[1].verdict, session.EFFECT_CHANGED)
        self.assertFalse(reported[1].marked)
        self.assertEqual(self.ledger(), [])

    def test_the_map_column_verdict_is_out_of_reach_of_this_pass(self):
        """A measurement the record never made is never even reported.

        `outside-map` needs the sidebar crop of the session that took the
        frame.  This pass measures the whole screen, so the only marker
        it can produce is the one about the whole screen -- which is why
        a row whose narration is accurate never acquires an amendment
        here on a measurement taken long after the keystroke.
        """
        opened = self.record(2)
        self.paint(1)
        self.paint(2, mark=(35, 5))
        reported = opened.annotate_recorded_effects(amend=True)
        self.assertEqual(reported[1].verdict, session.EFFECT_CHANGED)
        self.assertEqual(self.ledger(), [])

    def test_only_the_frames_asked_for_are_measured(self):
        opened = self.record(3)
        self.paint(1)
        self.paint(2, mark=(5, 5))
        self.paint(3, mark=(5, 5))
        reported = opened.annotate_recorded_effects(frames=[3])
        self.assertEqual([one.frame for one in reported], [3])
        self.assertEqual(reported[0].verdict, session.EFFECT_UNCHANGED)

    def test_a_frame_the_record_does_not_hold_is_refused(self):
        opened = self.record(1)
        self.paint(1)
        with self.assertRaises(session.RecordError):
            opened.annotate_recorded_effects(frames=[7])

    def test_a_missing_capture_stops_the_pass_rather_than_guessing(self):
        opened = self.record(2)
        self.paint(1)
        os.remove(os.path.join(self.frames,
                               manifest.FRAME_NAME_FORMAT % 2))
        with self.assertRaises(session.RecordError):
            opened.annotate_recorded_effects(frames=[2])

    def test_an_unmeasurable_pair_marks_nothing_and_says_so(self):
        opened = self.record(2)
        self.paint(1)
        broken = os.path.join(
            self.frames, manifest.FRAME_NAME_FORMAT % 2)
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("not a png")
        reported = opened.annotate_recorded_effects(amend=True)
        self.assertEqual(reported[1].verdict, session.EFFECT_UNKNOWN)
        self.assertFalse(reported[1].marked)
        self.assertEqual(self.ledger(), [])

    def test_no_writer_remains_that_could_edit_a_recorded_row(self):
        """The deleted rewriters are gone, not merely unused.

        F2 was a mechanism, not an incident: while a function that can
        rewrite captured evidence exists, some caller eventually calls
        it.  So the absence is asserted rather than assumed, in both
        modules and in both directions.
        """
        for name in ("extend_action", "_rewrite_rows"):
            with self.subTest(module="manifest", function=name):
                self.assertFalse(hasattr(manifest, name))
        for name in ("extend_observation_action",
                     "_rewrite_observations"):
            with self.subTest(module="session", function=name):
                self.assertFalse(hasattr(session, name))

    def frame_names(self):
        """Every capture on disk, sorted."""
        return sorted(name for name in os.listdir(self.frames)
                      if name.endswith(".png"))


class TheStatusPayload(SessionFixture):
    """`status` reports the guard's state and the evidence for it.

    A refusal condition nobody can inspect is a refusal condition nobody
    can check, and the runtime QA pass that found the resume guard
    releasing early had to read the guard's own stderr to establish which
    phase it believed it was in.  So the phase and the frame whose
    photographed sidebar released it are part of the machine payload.
    """

    def _status(self):
        """Run `status` against this fixture's tree, returning stdout."""
        opened = self.open_session()
        original = session._open_session
        session._open_session = (
            lambda args, *rest, **named: opened)
        self.addCleanup(setattr, session, "_open_session", original)
        arguments = argparse.Namespace(
            manifest=self.manifest, frames_dir=self.frames,
            observations=self.observations)
        captured = io.StringIO()
        stdout = sys.stdout
        sys.stdout = captured
        try:
            status = session._command_status(arguments)
        finally:
            sys.stdout = stdout
        payload = dict(
            line.split("=", 1)
            for line in captured.getvalue().splitlines() if "=" in line)
        return status, payload

    def test_a_record_with_no_photographed_sidebar_reports_the_menu(
            self):
        os.environ["STUB_NO_SIDEBAR"] = "1"
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("1", commentary="English.")
        opened.close()
        status, payload = self._status()
        self.assertEqual(status, session.EXIT_OK)
        self.assertEqual(payload["FRAME_LAST"], "1")
        self.assertEqual(payload["UI_PHASE"], session.UI_PHASE_MENU)
        self.assertEqual(payload["UI_PHASE_FRAME"], "")

    def test_the_frame_that_released_the_phase_is_named(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Load her.")
        opened.close()
        status, payload = self._status()
        self.assertEqual(status, session.EXIT_OK)
        self.assertEqual(payload["UI_PHASE"], session.UI_PHASE_IN_WORLD)
        self.assertEqual(payload["UI_PHASE_FRAME"], "1")


def _bytes_of(path):
    """Return a file's bytes, so "unchanged" can mean byte for byte."""
    with open(path, "rb") as handle:
        return handle.read()


class SidecarStagingSiblings(SessionFixture):
    """Performance QA finding: hard-kill leftovers in a tracked tree.

    The retired rewrite of the telemetry sidecar wrote a sibling and
    renamed it, so an unhandled interruption left that sibling inside
    playthrough/build/ -- and .gitignore re-includes the whole tree with
    its terminal negation, which makes a leftover an untracked file
    `git add -A playthrough/` would commit into an evidence tree nobody
    authored it into.  Unique temporary names let them accumulate without
    bound, and nothing swept the prefix afterwards.

    Code review then removed the writer altogether: the sidecar is
    append-only, like the record it corroborates.  The sweep is kept
    because a survivor of that writer is still committable, and opening a
    session is now the ONLY thing that will ever clear one.
    """

    def staging(self, name=".observations-staging.jsonl"):
        """Return a path beside the sidecar."""
        return os.path.join(self.build, name)

    def plant(self, *names):
        """Create staging leftovers as an interrupted rewrite would."""
        for name in names:
            with open(self.staging(name), "w",
                      encoding="utf-8") as handle:
                handle.write('{"frame": 1}\n')

    def candidates(self):
        """Return the staging siblings that remain."""
        return manifest.staging_candidates(
            self.build, session.OBSERVATIONS_STAGING_PREFIX,
            session.OBSERVATIONS_STAGING_SUFFIX)

    def test_the_staging_prefix_is_private_and_distinct(self):
        self.assertTrue(
            session.OBSERVATIONS_STAGING_PREFIX.startswith("."))
        self.assertEqual(session.OBSERVATIONS_STAGING_SUFFIX, ".jsonl")
        self.assertNotEqual(session.OBSERVATIONS_STAGING_PREFIX,
                            manifest.STAGING_PREFIX)

    def test_nothing_in_the_tooling_writes_a_staging_sibling(self):
        """The sweep outlived the writer, which is why it is kept.

        Code review removed both evidence rewrites, so no code path can
        create one of these siblings any more.  The sweep stays because a
        survivor of the retired writer is still an untracked file inside
        the re-included tree -- and opening a session is now the only
        thing that will ever clear it.
        """
        self.assertFalse(hasattr(session, "_rewrite_observations"))
        self.assertFalse(hasattr(manifest, "_rewrite_rows"))
        self.assertFalse(hasattr(manifest, "open_staging"))
        self.assertTrue(callable(session.sweep_observation_staging))

    def test_opening_a_session_sweeps_both_evidence_files(self):
        """The tree heals itself even though no rewrite is coming."""
        self.plant(".observations-staging.jsonl",
                   ".observations-abc123.jsonl",
                   ".observations-def456.jsonl")
        for name in (".manifest-staging.jsonl", ".manifest-abc123.jsonl"):
            with open(os.path.join(self.root, name), "w",
                      encoding="utf-8") as handle:
                handle.write('{"frame": 1}\n')
        self.assertEqual(len(self.candidates()), 3)
        self.open_session().close()
        self.assertEqual(self.candidates(), ())
        self.assertEqual(
            manifest.staging_candidates(
                self.root, manifest.STAGING_PREFIX,
                manifest.STAGING_SUFFIX),
            ())

    def test_a_symlink_at_a_staging_name_is_left_not_followed(self):
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", note="step south", commentary="South.")
        opened.close()
        before = _bytes_of(self.observations)
        elsewhere = os.path.join(self.build, "elsewhere.jsonl")
        with open(elsewhere, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        os.symlink(elsewhere, self.staging())
        session.sweep_observation_staging(self.observations)
        self.assertTrue(os.path.islink(self.staging()))
        self.assertEqual(_bytes_of(self.observations), before)
        self.assertEqual(_bytes_of(elsewhere), b"{}\n")

    def test_the_sidecar_only_ever_grows(self):
        """Append-only, proved by bytes across a second step."""
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("j", note="step south", commentary="South.")
        first = _bytes_of(self.observations)
        opened.step("k", note="step north", commentary="Back north.")
        opened.close()
        second = _bytes_of(self.observations)
        self.assertTrue(second.startswith(first))
        self.assertGreater(len(second), len(first))


class ThePhaseIndex(SessionFixture):
    """Performance QA finding: the phase cost a full sidecar read a step.

    `step` is one process per keystroke, so the UI phase is recovered
    from the telemetry sidecar on every invocation.  Recovering it by
    parsing the WHOLE sidecar cost O(rows) per step and O(rows^2) over a
    session the requirements deliberately leave uncapped -- 87,571 row
    parses and 45.63 MiB of reads across the 419 frames already
    recorded, with nothing bounding either number.  The cache beside the
    step lock answers the same question from the bytes appended since it
    was written.

    These tests are about the two properties that make that legitimate:
    THE ANSWER IS IDENTICAL to the full scan, and THE SIDECAR STAYS
    AUTHORITATIVE -- a cache that cannot be validated against the row it
    cites is discarded, never believed and never repaired.
    """

    def sidebar_row(self, frame, reading="08:15:32"):
        """Append one attestation, with or without a sidebar reading."""
        row = {"frame": frame,
               "file": manifest.frame_file(frame),
               "real_ts": manifest.utc_timestamp(),
               "ingame_clock": reading,
               "time_phrase": "", "date": "",
               "key": "j", "action": "press 'j' -- step south"}
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def full_scan(self, limit):
        """The pre-fix computation, kept here as the comparand."""
        showed = []
        for row in session.read_observations(
                self.observations, self.root):
            index = row.get("frame")
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            if index < manifest.MIN_FRAME_INDEX or index > limit:
                continue
            if any(session._reading_or_none(row, name) is not None
                   for name in session.SIDEBAR_READING_FIELDS):
                showed.append(index)
        return min(showed) if showed else None

    def indexed(self):
        """Refresh the cache and return the frame it names."""
        return session.refresh_phase_index(
            self.observations, self.root).frame

    def test_the_cache_lives_outside_the_working_tree(self):
        """It is machinery, not evidence, and must not be committable."""
        path = session.phase_index_path(self.root)
        self.assertTrue(os.path.isabs(path))
        self.assertFalse(
            path.startswith(manifest.approved_root(self.root) + os.sep))
        self.assertEqual(
            os.path.dirname(path),
            os.path.dirname(session.step_lock_path(self.root)))

    def test_the_answer_matches_a_full_scan_at_every_length(self):
        """Row by row, exactly as a session appends them."""
        readings = [None, None, "08:15:32", None, "08:15:40",
                    "Around dawn", None]
        for number, reading in enumerate(readings, start=1):
            self.sidebar_row(number, "" if reading is None else reading)
            index = session.refresh_phase_index(
                self.observations, self.root)
            mine = (None if index.frame is None or index.frame > number
                    else index.frame)
            with self.subTest(rows=number):
                self.assertEqual(mine, self.full_scan(number))
        self.assertEqual(self.indexed(), 3)

    def test_a_later_reading_never_displaces_an_earlier_one(self):
        """The earliest frame, because the transition is one-way."""
        self.sidebar_row(1, "08:15:32")
        self.assertEqual(self.indexed(), 1)
        self.sidebar_row(2, "08:15:40")
        self.assertEqual(self.indexed(), 1)

    def test_only_the_appended_bytes_are_read_again(self):
        for number in range(1, 5):
            self.sidebar_row(number, "")
        session.refresh_phase_index(self.observations, self.root)
        consumed = []
        original = session._phase_index_lines

        def counting(descriptor, cursor, path):
            lines, settled = original(descriptor, cursor, path)
            consumed.append(sum(len(line) for _at, line in lines))
            return lines, settled

        session._phase_index_lines = counting
        self.addCleanup(
            setattr, session, "_phase_index_lines", original)
        row = self.sidebar_row(5, "08:15:32")
        self.assertEqual(self.indexed(), 5)
        self.assertEqual(
            consumed,
            [len(json.dumps(row, ensure_ascii=False) + "\n")])

    def test_a_cache_citing_a_changed_row_is_discarded(self):
        """The sidecar is the record; the cache only ever summarises it.

        The cited row is replaced with one that carries NO reading, in
        place and at the same length, so nothing but the citation's own
        bytes can reveal it.  The cache must be rebuilt rather than
        believed.
        """
        self.sidebar_row(1, "08:15:32")
        self.sidebar_row(2, "08:15:40")
        self.assertEqual(self.indexed(), 1)
        rows = session.read_observations(self.observations, self.root)
        replaced = dict(rows[0])
        replaced["ingame_clock"] = ""
        # WRITTEN BY THE TEST, NOT BY THE TOOLING.  No code path in this
        # pipeline can rewrite the sidecar any more; the tampering being
        # simulated here is a foreign hand or a corrupted file, which is
        # precisely what the cache has to survive.
        self.replace_sidecar([replaced, dict(rows[1])])
        self.assertEqual(self.indexed(), 2)
        self.assertEqual(self.indexed(), self.full_scan(2))

    def test_a_truncated_sidecar_rebuilds_the_cache(self):
        for number in range(1, 4):
            self.sidebar_row(number, "08:15:3%d" % number)
        self.assertEqual(self.indexed(), 1)
        rows = session.read_observations(self.observations, self.root)
        self.replace_sidecar([dict(rows[2])])
        self.assertEqual(self.indexed(), 3)

    def replace_sidecar(self, rows):
        """Overwrite the sidecar from the TEST, never via the tooling.

        The tooling is append-only and carries no writer that could do
        this; a sidecar that has changed underneath the cache is a
        foreign edit or a damaged file, and the cache is validated
        against the row it cites for exactly that reason.
        """
        with open(self.observations, "w", encoding="utf-8",
                  newline="\n") as handle:
            for row in rows:
                handle.write(
                    json.dumps(dict(row), ensure_ascii=False) + "\n")

    def test_a_corrupt_cache_costs_a_read_and_nothing_else(self):
        self.sidebar_row(1, "08:15:32")
        self.assertEqual(self.indexed(), 1)
        with open(session.phase_index_path(self.root), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json at all")
        self.assertEqual(self.indexed(), 1)
        self.assertIsNotNone(
            session.read_phase_index(
                session.phase_index_path(self.root),
                manifest.relative_to_repo(self.observations)))

    def test_a_cache_from_another_sidecar_is_refused(self):
        self.sidebar_row(1, "08:15:32")
        self.assertEqual(self.indexed(), 1)
        path = session.phase_index_path(self.root)
        with open(path, "r", encoding="utf-8") as handle:
            record = json.load(handle)
        for name, value in (("sidecar", "playthrough/build/other.jsonl"),
                            ("version", session.PHASE_INDEX_VERSION + 1)):
            with self.subTest(field=name):
                spoiled = dict(record)
                spoiled[name] = value
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(spoiled, handle)
                self.assertIsNone(
                    session.read_phase_index(
                        path,
                        manifest.relative_to_repo(self.observations)))
                self.assertEqual(self.indexed(), 1)

    def test_a_torn_line_still_stops_the_recovery(self):
        """The faster path is not the more forgiving one."""
        self.sidebar_row(1, "08:15:32")
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write('{"frame": 2, "ingame_cl')
        with self.assertRaises(session.RecordError):
            session.refresh_phase_index(self.observations, self.root)
        with self.assertRaises(session.RecordError):
            session.read_observations(self.observations, self.root)

    def test_a_torn_line_is_not_recorded_as_consumed(self):
        """Its bytes are read again once its newline has landed."""
        self.sidebar_row(1, "")
        session.refresh_phase_index(self.observations, self.root)
        settled = session.read_phase_index(
            session.phase_index_path(self.root),
            manifest.relative_to_repo(self.observations)).cursor
        row = {"frame": 2, "file": manifest.frame_file(2),
               "real_ts": manifest.utc_timestamp(),
               "ingame_clock": "08:15:40", "time_phrase": "",
               "date": "", "key": "j", "action": "press 'j'"}
        line = json.dumps(row, ensure_ascii=False)
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write(line)
        self.assertEqual(self.indexed(), 2)
        self.assertEqual(
            session.read_phase_index(
                session.phase_index_path(self.root),
                manifest.relative_to_repo(self.observations)).cursor,
            settled)
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write("\n")
        self.assertEqual(self.indexed(), 2)

    def test_an_absent_sidecar_is_no_evidence(self):
        self.assertIsNone(self.indexed())
        self.assertEqual(
            session.refresh_phase_index(self.observations, self.root),
            session.PhaseIndex())

    def test_a_row_beyond_the_record_does_not_release_the_phase(self):
        """A stray attestation cannot put a session in the world."""
        self.sidebar_row(9, "08:15:32")
        opened = self.open_session()
        self.addCleanup(opened.close)
        self.assertEqual(opened.ui_phase, session.UI_PHASE_MENU)
        self.assertIsNone(opened.sidebar_frame)
        self.assertEqual(self.indexed(), 9)

    def test_a_bool_is_not_an_index(self):
        with open(self.observations, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"frame": True, "ingame_clock": "08:15:32"}) + "\n")
        self.assertIsNone(self.indexed())
        self.assertIsNone(self.full_scan(9))

    def test_the_step_path_recovers_the_phase_through_the_cache(self):
        """End to end: the phase a second process refuses or permits."""
        opened = self.open_session()
        self.stub_window(opened)
        opened.step("Return", commentary="Load her.")
        opened.close()
        again = self.open_session()
        self.addCleanup(again.close)
        self.assertEqual(again.ui_phase, session.UI_PHASE_IN_WORLD)
        self.assertEqual(again.sidebar_frame, 1)
        self.assertEqual(self.indexed(), 1)


class TheRoomForTheNextFrame(SessionFixture):
    """A full disk must be refused BEFORE the keystroke, not after.

    A session is unbounded and every capture is kept at full resolution,
    so the frames directory only ever grows.  Nothing checked the disk at
    all, and the failure that leaves is the worst shape one can take: the
    key has been delivered and cannot be un-pressed, the capture is
    truncated or missing, and a keystroke with no frame breaks the
    identity the whole record rests on for a reason no later stage can
    repair.

    The reserve is exercised through $PLAYTHROUGH_CAPTURE_RESERVE, which
    is also the only way an operator can name one -- so these tests use
    the same door a person would.
    """

    def reserve(self, value):
        """Name the reserve for this test, and put it back afterwards."""
        previous = os.environ.get(session.ENV_CAPTURE_RESERVE)
        os.environ[session.ENV_CAPTURE_RESERVE] = str(value)
        self.addCleanup(self._restore, session.ENV_CAPTURE_RESERVE,
                        previous)

    def measured(self, answer):
        """Stand in for the disk measurement.

        The host this suite runs on has terabytes free, so the only
        honest way to exercise the decision is to substitute the
        measurement -- exactly as the window and the keystroke are
        substituted.  `answer` is a number of bytes, or an exception
        instance to raise.
        """
        original = session.free_bytes

        def report(path):
            if isinstance(answer, BaseException):
                raise answer
            return answer

        session.free_bytes = report
        self.addCleanup(setattr, session, "free_bytes", original)

    def test_a_step_with_no_room_sends_nothing(self):
        """The whole point: refused before the irreversible act."""
        self.measured(1024)
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.CapacityError):
            opened.step("j", commentary="Shelves first.",
                        note="step one tile south")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.rows(), [])
        self.assertEqual(opened.frame, 0)
        self.assertFalse(os.path.isfile(
            os.path.join(self.frames, "frame_00001.png")))
        self.assertFalse(
            os.path.isfile(session.journal_path(self.root)))

    def test_the_refusal_names_the_figures_and_the_remedy(self):
        self.measured(1024)
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.CapacityError) as failed:
            opened.step("j", commentary="South.")
        message = str(failed.exception)
        self.assertIn("THE KEY HAS NOT BEEN SENT", message)
        self.assertIn("1024 byte(s) free", message)
        self.assertIn(str(session.capture_reserve(None)), message)
        self.assertIn("short", message)
        self.assertIn(session.ENV_CAPTURE_RESERVE, message)
        # The path is reported relative to the checkout, as every other
        # machine-readable path in this module is.
        self.assertNotIn(self.directory, message)

    def test_a_step_with_room_is_not_refused(self):
        """The positive control: room means nothing changes."""
        self.measured(session.capture_reserve(None))
        opened = self.open_session()
        self.stub_window(opened)
        result = opened.step("j", commentary="South.")
        self.assertEqual(result.frame, 1)
        self.assertEqual(self.sent, ["j"])

    def test_an_unmeasurable_disk_refuses_before_the_key(self):
        """Room must be PROVED, not assumed, before an irreversible key.

        THE DEFECT THIS PINS.  A statvfs that cannot be read used to warn
        and send the key anyway, on the reasoning that an unreadable
        measurement is a fact about the host rather than evidence of a
        full disk.  The trade is the wrong way round: the keystroke
        cannot be un-pressed, while the refusal costs nothing but the
        call, and this check exists precisely because a delivered key
        whose frame cannot be written breaks the identity the record
        rests on.  So an unmeasurable disk is refused, and -- the half
        that matters most -- NOTHING IS SENT.
        """
        self.measured(OSError("no answer"))
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.CapacityError) as caught:
            opened.step("j", commentary="South.")
        self.assertIn("NO PROOF", str(caught.exception))
        self.assertIn("THE KEY HAS NOT BEEN SENT",
                      str(caught.exception))
        self.assertEqual(self.sent, [],
                         msg="the keystroke must not have been sent")
        self.assertEqual(self.rows(), [],
                         msg="and nothing may have been recorded")

    def test_the_named_reserve_is_used_exactly(self):
        """An operator's figure is honoured, not adjusted."""
        self.reserve(12345)
        self.assertEqual(session.capture_reserve(None), 12345)
        self.assertEqual(session.capture_reserve(99999999), 12345)

    def test_the_reserve_is_calibrated_from_the_previous_capture(self):
        """A constant would be wrong for every session but one."""
        lookahead = session.CAPTURE_RESERVE_LOOKAHEAD
        extra = session.CAPTURE_RESERVE_FLOOR
        floor = (session.CAPTURE_RESERVE_PER_FRAME_FLOOR *
                 lookahead + extra)
        self.assertEqual(session.capture_reserve(None), floor)
        self.assertEqual(session.capture_reserve(1), floor)
        big = session.CAPTURE_RESERVE_PER_FRAME_FLOOR * 20
        self.assertEqual(session.capture_reserve(big),
                         big * lookahead + extra)

    def test_the_previous_capture_is_one_stat_not_a_listing(self):
        """A per-key directory walk is O(captures) per keystroke.

        This module already carries too much of that shape, so the
        calibration reads ONE file whose name it can derive.  Asserted
        against the source, because the cost is the point and a listing
        added later would still pass every behavioural test here.
        """
        source = inspect.getsource(session.Session._previous_capture_bytes)
        self.assertIn("os.stat(", source)
        for walked in ("listdir", "scandir", "glob", "iglob",
                       "_frames_on_disk"):
            with self.subTest(walked=walked):
                self.assertNotIn(walked, source)

    def test_the_measurement_is_the_available_figure(self):
        """f_bavail, not f_bfree.

        The difference is the filesystem's own reserved blocks: f_bfree
        counts space an unprivileged writer may not actually have.  The
        statvfs answer is substituted rather than compared against a
        second live reading, because the real figure moves between two
        calls on a host anything else is running on -- which is what a
        first version of this test discovered, by failing on a 4096-byte
        drift.
        """
        class Answer(object):
            f_bavail = 1000
            f_bfree = 9999
            f_frsize = 4096

        original = os.statvfs
        os.statvfs = lambda path: Answer()
        self.addCleanup(setattr, os, "statvfs", original)
        self.assertEqual(session.free_bytes(self.frames), 1000 * 4096)

    def test_an_unreadable_reserve_is_refused_not_defaulted(self):
        """Defaulting it would hide the mistake behind a full disk."""
        for value in ("", "  ", "abc", "-1", "12.5", "0x10",
                      "$(id)", "1; rm -rf /",
                      str(session.MAX_CAPTURE_RESERVE + 1)):
            with self.subTest(value=value):
                self.reserve(value)
                with self.assertRaises(session.CapacityError):
                    session.capture_reserve(None)

    def test_there_is_no_value_that_switches_the_check_off(self):
        """A session on a nearly full disk is one that should stop."""
        self.reserve(0)
        with self.assertRaises(session.CapacityError) as failed:
            session.capture_reserve(None)
        self.assertIn("switches the reserve off", str(failed.exception))

    def test_the_status_distinguishes_a_full_disk(self):
        """A driver has to tell "free space" from "the session is over"."""
        self.assertEqual(
            session._status_for(session.CapacityError("full")),
            session.EXIT_CAPACITY)
        for other in (session.KeyRejected("k"), session.WindowError("w"),
                      session.CaptureError("c"), session.RecordError("r"),
                      session.CheatGuard("g")):
            with self.subTest(other=type(other).__name__):
                self.assertNotEqual(session._status_for(other),
                                    session.EXIT_CAPACITY)

    def test_the_check_happens_before_the_window_is_prepared(self):
        """Order matters: nothing may be reached that could send a key."""
        source = inspect.getsource(session.Session.step)
        room = source.index("_assert_capture_room")
        for later in ("_prepare_window_for", "write_journal",
                      "_capture_frame"):
            with self.subTest(later=later):
                self.assertLess(room, source.index(later))


class CommittedArtifactsUntouched(unittest.TestCase):
    """This suite writes nothing into the captured record."""

    def test_the_real_artifacts_are_not_written(self):
        root = manifest.approved_root()
        watched = (os.path.join(root, "manifest.jsonl"),
                   os.path.join(root, "frames"),
                   os.path.join(root, "timeline.json"),
                   os.path.join(root, "userdir"))
        before = []
        for path in watched:
            before.append((path, os.path.exists(path),
                           _fingerprint(path)))
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(
                session.step_lock_path(directory).startswith("/"))
        for path, existed, mark in before:
            with self.subTest(path=path):
                self.assertEqual(os.path.exists(path), existed)
                self.assertEqual(_fingerprint(path), mark)


class TheObserveBeforeTheNextKeyGuard(SessionFixture):
    """The enforcing half of the observed-effect guard.

    Every test here pins a property a code review found MISSING: the
    guard measured and warned, and the retired session's frames 91-106
    show two key sequences delivered into an unchanged abandon-creation
    modal while those warnings were on stderr the whole time.  A control
    that only speaks is a report, so these are the refusals.
    """

    def declared(self, verdict, **extra):
        """Make the effect comparison answer one chosen verdict."""
        original = session.classify_effect
        session.classify_effect = (
            lambda previous, current, **keywords:
            session.ObservedEffect(verdict, **extra))
        self.addCleanup(
            setattr, session, "classify_effect", original)

    def modal(self, text):
        """Make the central-band reading answer one chosen string."""
        original = session.read_modal_text
        session.read_modal_text = lambda path: text
        self.addCleanup(
            setattr, session, "read_modal_text", original)

    def ledger(self):
        """Return the acknowledgment rows written so far."""
        path = os.path.join(self.build, session.ACKNOWLEDGMENTS_NAME)
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def first_step(self, opened):
        """Take the one step that needs no previous reading."""
        return opened.step("j", commentary="South, into the hallway.")

    def test_the_first_key_needs_no_reading(self):
        """There is no capture before the first one to read."""
        opened = self.open_session()
        self.stub_window(opened)
        result = session.Session.step(
            opened, "j", commentary="South.", expect=session.EXPECT_EITHER)
        self.assertEqual(result.frame, 1)
        self.assertEqual(self.ledger(), [])

    def test_a_second_key_is_refused_until_the_first_is_read(self):
        """Observe, decide, act -- as a precondition, not as advice."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        with self.assertRaises(session.ObservationRequired) as caught:
            session.Session.step(
                opened, "k", commentary="North.",
                expect=session.EXPECT_EITHER)
        self.assertIn("has not been read", str(caught.exception))
        self.assertEqual(
            self.sent, ["j"],
            msg="the second keystroke must not have been sent")
        self.assertEqual(len(self.rows()), 1)

    def test_the_reading_is_recorded_before_the_key_is_delivered(self):
        """A reading that only survives a successful send proves less.

        The acknowledgment is the evidence that the picture was looked at
        BEFORE the key went out, so it has to be on the device by then --
        which is what this shows by breaking the send and finding the
        ledger row already written.
        """
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)

        def refuse(identifier, key, timeout=None):
            raise session.WindowError("the window went away")

        session.send_key = refuse
        with self.assertRaises(session.WindowError):
            session.Session.step(
                opened, "k", commentary="North.",
                observed="frame 1 shows the hallway, nothing selected",
                expect=session.EXPECT_EITHER)
        rows = self.ledger()
        self.assertEqual([row["frame"] for row in rows], [1])
        self.assertEqual(rows[0]["observed"],
                         "frame 1 shows the hallway, nothing selected")
        self.assertEqual(rows[0]["frame_sha256"], STUB_FRAME_SHA256,
                         msg="the reading binds the frame's own digest")

    def test_a_perfunctory_reading_is_refused(self):
        """A ledger of "ok" would record the mechanism, not the sight."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        with self.assertRaises(session.ObservationRequired):
            session.Session.step(
                opened, "k", commentary="North.", observed="ok",
                expect=session.EXPECT_EITHER)
        self.assertEqual(self.sent, ["j"])

    def test_a_capture_that_contradicts_the_prediction_halts(self):
        """And the frame and its row are kept, because both happened."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        self.declared(session.EFFECT_UNCHANGED, screen_pixels=0,
                      map_pixels=0)
        with self.assertRaises(session.GuardHalt) as caught:
            session.Session.step(
                opened, "k", commentary="North.",
                observed="frame 1 shows the hallway, nothing selected",
                expect=session.EXPECT_CHANGED)
        self.assertIn("declared --expect changed", str(caught.exception))
        self.assertEqual(len(self.rows()), 2,
                         msg="the row is evidence and is kept")
        self.assertEqual(len(os.listdir(self.frames)), 2)
        self.assertTrue(self.sidecar()[1]["halted"])
        self.assertEqual(self.sidecar()[1]["expected"], "changed")

    def test_a_declared_unchanged_capture_is_permitted(self):
        """Some keys legitimately move nothing, and may say so first."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        self.declared(session.EFFECT_UNCHANGED, screen_pixels=0,
                      map_pixels=0)
        result = session.Session.step(
            opened, "space", commentary="A space in an empty field.",
            observed="frame 1 shows the name field, cursor at the end",
            expect=session.EXPECT_UNCHANGED)
        self.assertEqual(result.frame, 2)
        self.assertFalse(self.sidecar()[1]["halted"])

    def test_an_unmeasured_comparison_halts_a_prediction(self):
        """An absent observation must not read as a satisfied one."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        with self.assertRaises(session.GuardHalt) as caught:
            session.Session.step(
                opened, "k", commentary="North.",
                observed="frame 1 shows the hallway, nothing selected",
                expect=session.EXPECT_CHANGED)
        self.assertIn("not observed at all", str(caught.exception))

    def test_an_unmeasured_comparison_is_allowed_under_either(self):
        """A step that predicted nothing has nothing to contradict."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        result = session.Session.step(
            opened, "k", commentary="North.",
            observed="frame 1 shows the hallway, nothing selected",
            expect=session.EXPECT_EITHER)
        self.assertEqual(result.frame, 2)
        self.assertEqual(self.sidecar()[1]["effect"], "unknown")

    def test_an_undeclared_query_box_halts_the_session(self):
        """The exact shape of frames 91-106: a modal eating the keys."""
        self.modal("Return to main menu? (Case Sensitive)")
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.GuardHalt) as caught:
            session.Session.step(
                opened, "slash", commentary="Open the filter.",
                expect=session.EXPECT_EITHER)
        self.assertIn("return-to-main-menu", str(caught.exception))
        self.assertEqual(
            self.sidecar()[0]["modals"], ["return-to-main-menu"],
            msg="the box is recorded, not only reported")
        self.assertTrue(self.sidecar()[0]["halted"])

    def test_a_declared_query_box_is_permitted(self):
        """Answering a prompt deliberately is the ordinary case."""
        self.modal("Save and quit?")
        opened = self.open_session()
        self.stub_window(opened)
        result = session.Session.step(
            opened, "S", commentary="Sleep is over; put it away.",
            expect=session.EXPECT_EITHER,
            expect_modal="save-and-quit")
        self.assertEqual(result.frame, 1)
        self.assertEqual(self.sidecar()[0]["expect_modal"],
                         "save-and-quit")

    def test_a_declared_box_that_is_not_there_halts(self):
        """A wrong model of the screen is wrong in both directions."""
        self.modal("nothing of the sort")
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.GuardHalt) as caught:
            session.Session.step(
                opened, "Y", commentary="Yes.",
                expect=session.EXPECT_EITHER,
                expect_modal="save-and-quit")
        self.assertIn("does not show it", str(caught.exception))

    def test_an_unknown_modal_token_is_refused_before_the_key(self):
        """A declaration nothing can match would never be satisfied."""
        opened = self.open_session()
        self.stub_window(opened)
        with self.assertRaises(session.RecordError):
            session.Session.step(
                opened, "Y", commentary="Yes.",
                expect_modal="no-such-box")
        self.assertEqual(self.sent, [])

    def test_a_halted_frame_needs_an_acknowledgment_of_its_own(self):
        """Reading an anomaly and keying past it cannot be one act."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        self.declared(session.EFFECT_UNCHANGED, screen_pixels=0,
                      map_pixels=0)
        with self.assertRaises(session.GuardHalt):
            session.Session.step(
                opened, "k", commentary="North.",
                observed="frame 1 shows the hallway, nothing selected",
                expect=session.EXPECT_CHANGED)
        opened.close()
        second = self.open_session()
        self.stub_window(second, window=4243)
        with self.assertRaises(session.ObservationRequired) as caught:
            session.Session.step(
                second, "l", commentary="East.",
                observed="frame 2 did not move; the filter is closed",
                expect=session.EXPECT_EITHER)
        self.assertIn("STOPPED the session", str(caught.exception))
        self.assertEqual(self.sent, [])
        second.acknowledge(
            2, "frame 2 shows the same screen as frame 1; nothing moved")
        result = session.Session.step(
            second, "l", commentary="East.",
            expect=session.EXPECT_EITHER)
        self.assertEqual(result.frame, 3)
        self.assertEqual(self.sent, ["l"])

    def test_an_acknowledgment_of_a_frame_that_was_never_taken(self):
        """A reading of nothing is not a reading."""
        opened = self.open_session()
        with self.assertRaises(session.RecordError):
            opened.acknowledge(7, "a screen nobody photographed")

    def test_the_ledger_is_append_only(self):
        """A second reading is added, never a first one rewritten."""
        opened = self.open_session()
        self.stub_window(opened)
        self.first_step(opened)
        opened.acknowledge(1, "the hallway, seen once")
        opened.acknowledge(1, "the hallway, looked at again")
        rows = self.ledger()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["observed"] for row in rows],
                         ["the hallway, seen once",
                          "the hallway, looked at again"])

    def test_an_unreadable_ledger_refuses_rather_than_reads_empty(self):
        """"Unknown" and "unacknowledged" must not arrive as one answer."""
        path = os.path.join(self.build, session.ACKNOWLEDGMENTS_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json\n")
        with self.assertRaises(session.RecordError):
            session.read_acknowledgments(path, self.root)

    def test_the_modal_table_is_matched_whitespace_insensitively(self):
        """tesseract does not preserve the engine's double spaces."""
        self.assertEqual(
            session.detect_modals("This  will kill your character."),
            ("kill-your-character",))
        self.assertEqual(session.detect_modals("Really   quit ?"), ())
        self.assertEqual(session.detect_modals(None), ())

    def test_every_declared_box_names_its_source(self):
        """A prompt quoted from memory is not evidence."""
        for token, prompt, why in session.MODAL_PROMPTS:
            with self.subTest(token=token):
                self.assertTrue(prompt.strip())
                self.assertIn("src/", why)
                self.assertEqual(session.modal_reason(token), why)

    def test_the_band_is_computed_from_the_capture(self):
        """A hard-coded rectangle would read the wrong pixels."""
        rect = session.modal_band(1920, 1080)
        self.assertEqual(rect.width, 1920)
        self.assertEqual(rect.y, int(1080 * session.MODAL_BAND_TOP))
        self.assertGreater(rect.height, 0)
        self.assertLessEqual(rect.y + rect.height, 1080)
        smaller = session.modal_band(640, 384)
        self.assertEqual(smaller.width, 640)
        self.assertLessEqual(smaller.y + smaller.height, 384)

    def test_an_unreadable_band_is_no_modal_rather_than_a_failure(self):
        """A guard that could end a session by failing to read is worse."""
        self.assertEqual(
            session.read_modal_text(
                os.path.join(self.frames, "frame_99999.png")), "")


def _fingerprint(path):
    """Return a cheap signature of a path, or None when absent."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISDIR(info.st_mode):
        return len(os.listdir(path))
    return info.st_size


if __name__ == "__main__":
    # Wired up so that `python3 playthrough/tooling/test_session.py`
    # runs the suite and exits non-zero on any failure, which is how the
    # acceptance gate invokes it.
    unittest.main(verbosity=2)
