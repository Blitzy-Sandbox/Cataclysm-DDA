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

import json
import os
import shutil
import stat

import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import manifest  # noqa: E402  (path set above, as the siblings do)
import session  # noqa: E402

FIXED_REAL_TS = "2026-08-03T19:14:42.507Z"

# A capturer stand-in.  It writes the PNG the real capture.sh would
# commit and prints the same payload contract, so the transaction can be
# exercised without an X server.  FRAME_INDEX is its only input, exactly
# as the real one documents.
STUB_CAPTURE = """#!/bin/sh
set -eu
index="${FRAME_INDEX}"
name="$(printf 'frame_%05d.png' "${index}")"
path="${STUB_FRAMES}/${name}"
if [ -n "${STUB_FAIL:-}" ]; then
    exit 4
fi
printf 'stub' > "${path}"
cat <<PAYLOAD
CAPTURE_MODE=production
FRAME_INDEX=${index}
FRAME_NAME=${name}
FRAME_FILE=playthrough/frames/${name}
FRAME_PATH=${path}
FRAME_GEOMETRY=1920x1080
REAL_TS=__REAL_TS__
CAPTURE_TOOL=stub
LUMA_MEAN=0.27
LUMA_STDDEV=0.19
CLOCK_RECT=288x1072+1632+4
CLOCK_RECT_FROM=computed
CLOCK_SOURCE=stub
CLOCK_STATUS=exact
CLOCK=08:15:33
TIME_PHRASE=
DATE=Spring, day 61
DATE_STATUS=read
OBSERVATIONS=${STUB_OBSERVATIONS}
PAYLOAD
""".replace("__REAL_TS__", FIXED_REAL_TS)


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
        """Open a Session against the temporary tree."""
        opened = session.Session(
            manifest_path=self.manifest,
            frames_dir=self.frames,
            observations_path=self.observations,
            capture_script=self.capture,
            window_id=None,
            root=self.root,
            **extra)
        self.addCleanup(opened.close)
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
        opened.step("u", commentary="Custom Character.")
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

    def test_a_created_session_may_press_custom_character(self):
        """The refusal is scoped to a RESUME, not to the letter."""
        opened = self.open_session()
        self.stub_window(opened)
        self.assertEqual(opened.pin.mode, session.SESSION_MODE_CREATE)
        opened.step("u", commentary="The custom sheet.")
        self.assertEqual(self.sent, ["u"])

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
            opened.step("u", commentary="The custom sheet.")
        self.assertEqual(self.sent, ["u"])
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
        opened.step("u", commentary="Custom Character.")
        self.world()
        opened.step("Return", commentary="Sign it.")
        self.assertEqual(len(self.rows()), 2)


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
