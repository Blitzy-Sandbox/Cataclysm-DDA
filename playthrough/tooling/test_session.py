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
import ocr_clock  # noqa: E402
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
    """

    def warnings(self):
        """Capture stderr while a step runs, and return it."""
        import io
        import contextlib
        stream = io.StringIO()
        return stream, contextlib.redirect_stderr(stream)

    def test_the_collision_is_reported_when_the_row_says_so(self):
        opened = self.open_session()
        self.stub_window(opened)
        stream, capture = self.warnings()
        with capture:
            opened.step("u", commentary="The custom sheet, not a dice "
                                        "roll.",
                        note="open the custom character entry")
        emitted = stream.getvalue()
        self.assertIn("main_menu.cpp:466", emitted)
        self.assertIn("T<u|U>torial Game", emitted)
        self.assertIn("walk the top row", emitted)
        # Advisory only: the key was still sent and the row recorded.
        self.assertEqual(self.sent, ["u"])
        self.assertEqual(len(self.rows()), 1)

    def test_ordinary_play_with_the_same_letter_is_silent(self):
        opened = self.open_session()
        self.stub_window(opened)
        stream, capture = self.warnings()
        with capture:
            opened.step("u", commentary="Past the chair, north-east.",
                        note="step north-east into the next room")
        self.assertNotIn("main_menu.cpp:466", stream.getvalue())
        self.assertEqual(self.sent, ["u"])

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
cat <<PAYLOAD
CAPTURE_MODE=production
FRAME_INDEX=${index}
FRAME_NAME=${name}
FRAME_FILE=playthrough/frames/${name}
FRAME_PATH=${path}
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
