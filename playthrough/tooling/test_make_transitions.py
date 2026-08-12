#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/make_transitions.py.

    python3 -B playthrough/tooling/test_make_transitions.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

The -B keeps __pycache__ out of playthrough/tooling/, which .gitignore's
terminal `!/playthrough/**` negation would otherwise make committable;
this module sets sys.dont_write_bytecode for the same reason.

WHY THIS MODULE IS WORTH A SUITE
These twelve images per group are the ONLY frames in the film that no
keystroke produced.  Everything about them is therefore load-bearing in a
way that is invisible in the finished movie:

* THE COUNT.  render_movie.py charges exactly one second of video per
  flagged entry and make_srt.py walks the same cursor, so a group of
  eleven or thirteen frames desynchronises the captions from the picture
  -- correct at the start of the film and further out with every
  transition after it.  Nothing about the output looks wrong.
* THE NAMES.  render_movie.py builds the concat list from
  trans_%05d_%02d.png and a verifier counts groups by that glob, so a
  differently spelled name is a group that silently does not exist.
* THE DIRECTORY.  playthrough/frames/ holds one PNG per keystroke and
  nothing else; that identity is what proves one capture per key press,
  and derived imagery mixed into it would destroy the proof rather than
  break it visibly.
* THE MALFORMED DOCUMENT.  A timeline that flags its own last entry is
  asking for a transition after the end of the session.  There is
  nothing to fade into, so the run is refused -- composing a frame
  fading back into itself would invent a second of film out of a
  document already known to be wrong, and would make the gate that
  compares groups to flags pass by construction.

WHAT IS ASSERTED, AND HOW
Six areas: the MoviePy 2 API this module is written against (asserted
from its own source, so a v1-era edit is caught without an install of
v1), the planning of groups from a timeline, the composition of one
group, the reconciliation that keeps the directory describing the
current timeline, the whole run, and the command line's exit status.

Everything runs in a temporary directory handed in as the approved root
-- the call-site-only `root=` argument, which is the one supported way to
point these rules at a tree a test owns.  Captures are written by Pillow
at a small geometry declared through env.sh's own
$PLAYTHROUGH_SCREEN_WIDTH/HEIGHT, because that is the module's own
documented way to work at another size and it makes a real composition
affordable in a test; ONE test composes a real 1920x1080 group from two
committed captures, so the production geometry is exercised too rather
than only described.  The card's typeface is the game's own
data/font/Terminus.ttf, read from the checkout, because a fallback font
would not be the film's typeface.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
REPO_ROOT = os.path.dirname(PLAYTHROUGH)
if TOOLING not in sys.path:
    sys.path.insert(0, TOOLING)

import make_transitions as mt  # noqa: E402  (path set above)
import manifest  # noqa: E402  (path set above)
import timeline  # noqa: E402  (path set above)

try:
    import numpy as np
    from PIL import Image
except ImportError as error:  # pragma: no cover - declared dependency
    raise SystemExit(
        "this suite needs the pipeline's own declared dependencies "
        "(playthrough/tooling/requirements.txt): %s" % error)

# A small canvas, declared the way env.sh declares one, so that a real
# composition -- real MoviePy, real fades, real Pillow writes -- costs
# milliseconds instead of seconds.  The geometry is not what these tests
# are about; the count, the names and the containment are.
SMALL = (320, 240)

# Two committed captures, used by the one test that composes at the
# production geometry.
#
# THEY ARE A REAL FLAGGED PAIR, not an arbitrary two.  Entry 296 of the
# committed playthrough/timeline.json carries transition_after, so 296
# and 297 are exactly the two captures a transition group is composed
# between in the recorded session -- which is what makes this test a
# rehearsal of the production path rather than a composition of two
# unrelated pictures that happen to be the right size.
#
# A NAME THAT IS NOT IN THE RECORDING TURNS THIS TEST OFF SILENTLY.  The
# guard below skips when the files are absent, which is right for a
# checkout without the artifacts and wrong the moment the names go
# stale: the skip then hides the only test that runs real MoviePy at
# 1920x1080.  If the session is ever re-recorded, re-derive these two
# from the new timeline's first flagged entry.
REAL_FRAMES = (
    os.path.join(PLAYTHROUGH, "frames", "frame_00296.png"),
    os.path.join(PLAYTHROUGH, "frames", "frame_00297.png"),
)


def _read(path, mode="r"):
    """Return a whole file, with its descriptor closed again.

    Spelled out rather than open(...).read(), which leaves the reader for
    the garbage collector and makes a suite run under -W error noisy
    about its own fixtures.
    """
    if "b" in mode:
        with open(path, mode) as handle:
            return handle.read()
    with open(path, mode, encoding="utf-8") as handle:
        return handle.read()


SOURCE = _read(os.path.join(TOOLING, "make_transitions.py"))


def _remove_tree(path):
    """Remove a temporary tree, tolerating a partial one."""
    shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def _environment(**values):
    """Set environment variables for a block, then restore them.

    A value of None UNSETS the variable.  These variables are the frame
    geometry and the artifact layout: one left pointing at a temporary
    directory would silently redirect every test after it.
    """
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


@contextlib.contextmanager
def _patched(module, **attributes):
    """Swap module attributes for a block, then restore them."""
    previous = {name: getattr(module, name) for name in attributes}
    try:
        for name, value in attributes.items():
            setattr(module, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(module, name, value)


class FakeSegment(object):
    """A composed segment that yields exactly the frames it was given.

    Stands in for the concatenated clip so that a segment of the WRONG
    LENGTH -- the one failure this module exists to refuse and the one
    MoviePy would never produce on purpose -- can be arranged at all.
    """

    def __init__(self, frames, size):
        self.frames = list(frames)
        self.size = size
        self.closed = False

    def iter_frames(self, fps=None):
        """Yield the frames one at a time, as MoviePy does."""
        for frame in self.frames:
            yield frame

    def close(self):
        """Release the clip, as MoviePy's own clips do."""
        self.closed = True


class TransitionFixture(unittest.TestCase):
    """A temporary artifact tree with captures in it, and no more."""

    def setUp(self):
        self.root = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_transitions_"))
        self.addCleanup(_remove_tree, self.root)
        # The timeline names its captures RELATIVE TO THE CHECKOUT ROOT
        # -- "playthrough/frames/frame_00001.png" in the committed
        # artifact -- and the module resolves them against the parent of
        # the approved root.  The fixture therefore spells its own `file`
        # fields the same way, so the resolution being exercised is the
        # production one rather than an absolute short cut.
        self.rel_frames = "%s/frames" % os.path.basename(self.root)
        self.frames = os.path.join(self.root, "frames")
        self.transitions = os.path.join(self.root, "build",
                                        "transitions")
        os.makedirs(self.frames)
        os.makedirs(self.transitions)
        self.timeline_path = os.path.join(self.root, "timeline.json")
        self.enter(_environment(
            PLAYTHROUGH_SCREEN_WIDTH=str(SMALL[0]),
            PLAYTHROUGH_SCREEN_HEIGHT=str(SMALL[1]),
            PLAYTHROUGH_TRANSITIONS_DIR=None,
            PLAYTHROUGH_TRANSITION_FORMAT=None,
            PLAYTHROUGH_FRAMES_DIR=None,
            PLAYTHROUGH_TIMELINE=None,
            PLAYTHROUGH_REPO_ROOT=None))

    def enter(self, manager):
        """Enter a context manager for the length of one test."""
        value = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return value

    # -- fixtures -----------------------------------------------------

    def capture(self, index, size=SMALL, colour=None):
        """Write one capture and return its absolute path."""
        path = os.path.join(self.frames,
                            "frame_%05d.png" % index)
        shade = colour if colour is not None else (
            (index * 17) % 256, (index * 29) % 256, 64)
        Image.new("RGB", size, shade).save(path)
        return path

    def captures(self, count, size=SMALL):
        """Write `count` captures, indexed from 1."""
        return [self.capture(index, size)
                for index in range(1, count + 1)]

    def entries(self, count, flagged=()):
        """Return `count` timeline entries, flagging those named."""
        rows = []
        for index in range(1, count + 1):
            rows.append({
                "frame": index,
                "file": "%s/frame_%05d.png" % (self.rel_frames, index),
                "transition_after": index in flagged,
            })
        return rows

    def write_manifest(self, count, flagged=()):
        """Write a manifest matching `count` entries, and return it.

        assert_timeline_document() -- the one gate every producer of a
        rendered artifact passes -- requires the document to carry a
        manifest attestation that MATCHES THE MANIFEST ON DISK, which is
        what catches a stale timeline beside a re-recorded session.  So
        the fixture writes the evidence the document claims to describe
        rather than a document that claims nothing.

        THE CLOCKS ARE WHAT MAKE A FLAG HONEST.  `transition_after` is
        not a field a fixture may simply assert: the validator requires
        it to be exactly `raw_delta > CEIL`.  So a frame that must carry
        a transition is given a successor whose sidebar clock is five
        minutes later, and every other step advances one second.  The
        flags then FALL OUT of the evidence, which is the same way the
        committed timeline got its own.
        """
        path = os.path.join(self.root, "manifest.jsonl")
        moment = 8 * 3600
        with open(path, "w", encoding="utf-8") as handle:
            for index in range(1, count + 1):
                handle.write(manifest.encode_row(manifest.build_row(
                    frame=index,
                    file="playthrough/frames/frame_%05d.png" % index,
                    real_ts="2026-05-20T08:00:%02dZ" % (index % 60),
                    ingame_clock="%02d:%02d:%02d" % (
                        moment // 3600 % 24, moment // 60 % 60,
                        moment % 60),
                    action="press '5' -- wait",
                    commentary="Waiting, because there is nothing "
                               "else worth doing yet.")))
                moment += 300 if index in flagged else 1
        return path

    def document(self, count, flagged=(), **overrides):
        """Return a timeline document over `count` entries.

        Built through timeline.build_timeline() from a manifest this
        fixture writes, so the totals, the counts, the cue windows and
        the transition flags are the producer's own arithmetic and the
        attestation matches the evidence on disk.  Anything a test wants
        to break is then applied through `overrides`, which is the
        point: the shape has to be VALID before a mutation of it means
        anything.
        """
        path = self.write_manifest(count, flagged)
        rows = manifest.read_rows(path, root=self.root)
        body = timeline.build_timeline(
            rows, None, None,
            timeline.attest_manifest(path, self.root))
        # The captures are named relative to the parent of the approved
        # root, which is this fixture's own temporary directory, so the
        # resolution being exercised is the production one.
        for entry in body["frames"]:
            entry["file"] = "%s/frame_%05d.png" % (self.rel_frames,
                                                   entry["frame"])
        # A FLAGGED FINAL ENTRY CANNOT FALL OUT OF THE EVIDENCE, because
        # the last frame has no successor to difference against, so its
        # raw delta is zero by definition.  A test that needs that
        # malformed document therefore has to say so explicitly, and
        # asking for it here is what makes the refusal reachable.  Every
        # other requested flag is already True from the clocks, so this
        # is a no-op for them.
        for entry in body["frames"]:
            if entry["frame"] in flagged:
                entry["transition_after"] = True
        body["transition_count"] = len(
            [one for one in body["frames"] if one["transition_after"]])
        body.update(overrides)
        return body

    def write_timeline(self, count, flagged=(), **overrides):
        """Write a timeline document and return its path."""
        with open(self.timeline_path, "w", encoding="utf-8") as handle:
            json.dump(self.document(count, flagged, **overrides),
                      handle)
        return self.timeline_path

    # -- running it ---------------------------------------------------

    def quietly(self, call, *args, **kwargs):
        """Run `call`, returning (result, stderr text).

        expected_size() reports a non-production geometry every time it
        resolves one, which is correct of it and noise here, so the
        advisory is captured and returned for the tests that assert on
        it.
        """
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            result = call(*args, **kwargs)
        return result, stream.getvalue()

    def compose(self, current, successor, index=1, **overrides):
        """Compose one group at `index`, returning the paths written."""
        arguments = {
            "out_prefix": os.path.join(
                self.transitions,
                mt.TRANSITION_STEM_FORMAT % index),
            "font": None,
            "size": None,
            "root": self.root,
            "repo_root_dir": REPO_ROOT,
        }
        arguments.update(overrides)
        written, _ = self.quietly(
            mt.compose_transition_group, current, successor,
            **arguments)
        return written

    def run_make(self, **overrides):
        """Run the whole module against the fixture's tree."""
        arguments = {
            "timeline_path": self.timeline_path,
            "transitions_dir": self.transitions,
            "root": self.root,
            "repo_root_dir": REPO_ROOT,
        }
        arguments.update(overrides)
        result, _ = self.quietly(mt.make_transitions, **arguments)
        return result

    def main(self, argv):
        """Run the real command line, returning (status, out, err)."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                status = mt.main(argv, root=self.root)
        return status, out.getvalue(), err.getvalue()

    # -- reading the tree ---------------------------------------------

    def written_names(self):
        """Return the transition frames on disk, sorted."""
        return sorted(name for name in os.listdir(self.transitions)
                      if name.endswith(".png"))

    def all_names(self):
        """Return everything in the transitions directory, sorted."""
        return sorted(os.listdir(self.transitions))

    def frame_names(self):
        """Return the capture directory's contents, sorted."""
        return sorted(os.listdir(self.frames))

    def size_of(self, path):
        """Return one written PNG's (size, mode)."""
        with Image.open(path) as handle:
            return (handle.width, handle.height), handle.mode


class TestTheMoviePyTwoContract(TransitionFixture):
    """The module is written against MoviePy 2, provably.

    Asserted from the module's own SOURCE as well as from the installed
    package, because the failure mode of a v1-era edit is not an
    ImportError: `CompositeVideoClip` composes without error and simply
    omits the fade, so the only symptom is a hard cut in the film.
    """

    def test_the_v1_editor_submodule_is_never_imported(self):
        self.assertNotIn("moviepy.editor", SOURCE)
        self.assertNotIn("from moviepy import editor", SOURCE)

    def test_the_compositing_class_is_not_imported_or_used(self):
        self.assertNotIn("CompositeVideoClip", SOURCE)
        self.assertFalse(hasattr(mt, "CompositeVideoClip"))

    def test_the_v1_setters_are_not_used(self):
        for setter in (".set_duration(", ".set_start(", ".set_pos(",
                       ".set_position(", ".set_fps("):
            self.assertNotIn(setter, SOURCE)
        self.assertIn(".with_duration(", SOURCE)

    def test_the_effects_are_v2_classes_through_with_effects(self):
        self.assertIn("with_effects([vfx.FadeOut(", SOURCE)
        self.assertIn("with_effects([vfx.FadeIn(", SOURCE)
        for legacy in (".fadein(", ".fadeout("):
            self.assertNotIn(legacy, SOURCE)

    def test_the_segment_is_concatenated_not_composited(self):
        self.assertIn("concatenate_videoclips(clips)", SOURCE)

    def test_the_installed_moviepy_offers_the_v2_effects(self):
        self.assertTrue(hasattr(mt.vfx, "FadeIn"))
        self.assertTrue(hasattr(mt.vfx, "FadeOut"))
        mt._require_moviepy()

    def test_an_installed_v1_is_reported_as_the_wrong_release(self):
        class WithoutEffects(object):
            """A v1-shaped vfx module: no FadeIn, no FadeOut."""

        with _patched(mt, vfx=WithoutEffects()):
            with self.assertRaises(mt.TransitionError) as caught:
                mt._require_moviepy()
        message = str(caught.exception)
        self.assertIn("2.x", message)
        self.assertIn("requirements.txt", message)

    def test_a_missing_dependency_names_the_requirements_file(self):
        for name, check in (
                ("NUMPY_IMPORT_ERROR", mt._require_numpy),
                ("PILLOW_IMPORT_ERROR", mt._require_pillow),
                ("MOVIEPY_IMPORT_ERROR", mt._require_moviepy)):
            with _patched(mt, **{name: ImportError("not installed")}):
                with self.assertRaises(mt.TransitionError) as caught:
                    check()
            self.assertIn("requirements.txt", str(caught.exception))

    def test_the_composition_fills_the_transition_second(self):
        self.assertEqual(
            mt.FADE_SECONDS * 2 + mt.CARD_SECONDS,
            mt.EXPECTED_TRANSITION)
        self.assertEqual(mt.FRAMES_PER_GROUP,
                         int(round(mt.FPS * mt.EXPECTED_TRANSITION)))
        self.assertEqual(mt.FRAMES_PER_GROUP, 12)

    def test_the_transition_length_comes_from_the_timeline(self):
        self.assertEqual(mt.EXPECTED_TRANSITION, timeline.TRANSITION)


class TestPlanningTheGroups(TransitionFixture):
    """One group per flag, between the flagged frame and its successor."""

    def plan(self, entries):
        """Plan the groups for `entries` inside the fixture's tree."""
        planned, _ = self.quietly(mt.plan_groups, entries, self.root)
        return planned

    def test_a_timeline_with_no_flags_plans_nothing(self):
        self.captures(3)
        self.assertEqual(self.plan(self.entries(3)), [])

    def test_one_flag_plans_one_group(self):
        self.captures(3)
        planned = self.plan(self.entries(3, flagged={2}))
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0].frame, 2)

    def test_the_group_sits_between_the_frame_and_its_successor(self):
        self.captures(3)
        group = self.plan(self.entries(3, flagged={2}))[0]
        self.assertEqual(os.path.basename(group.current),
                         "frame_00002.png")
        self.assertEqual(os.path.basename(group.successor),
                         "frame_00003.png")
        self.assertNotEqual(group.current, group.successor)

    def test_several_flags_plan_in_timeline_order(self):
        self.captures(5)
        planned = self.plan(self.entries(5, flagged={1, 3, 4}))
        self.assertEqual([group.frame for group in planned], [1, 3, 4])

    def test_a_flagged_final_entry_is_refused(self):
        # The malformed document.  A transition sits BETWEEN a frame and
        # the one after it, and this one asks for a second of film after
        # the end of the session.
        self.captures(2)
        with self.assertRaises(mt.TransitionError) as caught:
            self.plan(self.entries(2, flagged={2}))
        message = str(caught.exception)
        self.assertIn("final-frame-flagged", message)
        self.assertIn("no successor", message)
        self.assertIn("timeline.py", message)

    def test_a_flagged_final_entry_writes_nothing(self):
        self.captures(2)
        self.write_timeline(2, flagged={2})
        with self.assertRaises(mt.TransitionError):
            self.run_make()
        self.assertEqual(self.all_names(), [])
        self.assertEqual(self.frame_names(),
                         ["frame_00001.png", "frame_00002.png"])

    def test_the_documentation_describes_the_refusal_it_implements(self):
        """A docstring that contradicts the code is a defect.

        THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE.  plan_groups() and
        Result both documented a flagged final entry as being HONOURED by
        fading the last capture back into itself -- with two stated
        reasons -- while the code twenty lines below raised
        TransitionError.  A reader debugging a refused run was sent
        looking for a self-fade that has never existed, and a reader
        maintaining it would have "fixed" the code to match the prose.
        """
        for text in (mt.plan_groups.__doc__, mt.Result.__doc__,
                     mt.Group.__doc__):
            with self.subTest(doc=text.splitlines()[0]):
                self.assertNotIn("honoured rather than skipped", text)
                self.assertNotIn("fades back into", text)
                self.assertNotIn("every flag is honoured", text)
        self.assertIn("REFUSED", mt.plan_groups.__doc__)
        self.assertIn("TransitionError", mt.plan_groups.__doc__)
        self.assertIn("raise", mt.Result.__doc__)

    def test_a_flagged_final_entry_is_refused_before_earlier_ones(self):
        # Not "the earlier groups are composed and then it stops": the
        # planning is complete before any imagery exists, so a malformed
        # document costs nothing and leaves nothing behind.
        self.captures(3)
        self.write_timeline(3, flagged={1, 3})
        with self.assertRaises(mt.TransitionError):
            self.run_make()
        self.assertEqual(self.all_names(), [])

    def test_the_only_flagged_entry_of_one_is_refused(self):
        self.captures(1)
        with self.assertRaises(mt.TransitionError):
            self.plan(self.entries(1, flagged={1}))

    def test_a_group_carries_exactly_the_frame_and_its_two_paths(self):
        # No self-fade field: the case it recorded is refused now, and a
        # field nothing can set is a field that misleads a reader.
        self.assertEqual(mt.Group._fields,
                         ("frame", "current", "successor"))

    def test_a_non_boolean_flag_is_refused_not_interpreted(self):
        self.captures(2)
        entries = self.entries(2)
        entries[0]["transition_after"] = "false"
        with self.assertRaises(mt.TransitionError) as caught:
            self.plan(entries)
        self.assertIn("not coerced", str(caught.exception))

    def test_an_absent_flag_means_no_transition(self):
        self.captures(2)
        entries = self.entries(2)
        for entry in entries:
            del entry["transition_after"]
        self.assertEqual(self.plan(entries), [])

    def test_a_non_integer_frame_index_is_refused(self):
        self.captures(2)
        entries = self.entries(2, flagged={1})
        entries[0]["frame"] = "2"
        with self.assertRaises(mt.TransitionError):
            self.plan(entries)

    def test_an_index_too_wide_for_the_name_is_refused(self):
        self.captures(2)
        entries = self.entries(2, flagged={1})
        entries[0]["frame"] = mt.MAX_FRAME_INDEX + 1
        with self.assertRaises(mt.TransitionError) as caught:
            self.plan(entries)
        self.assertIn("five-digit", str(caught.exception))

    def test_a_capture_that_is_not_there_is_refused(self):
        self.captures(1)
        with self.assertRaises(mt.TransitionError):
            self.plan(self.entries(2, flagged={1}))

    def test_a_capture_outside_the_frames_directory_is_refused(self):
        self.captures(2)
        entries = self.entries(2, flagged={1})
        Image.new("RGB", SMALL, (1, 2, 3)).save(
            os.path.join(self.transitions, "x.png"))
        entries[0]["file"] = "%s/build/transitions/x.png" % (
            os.path.basename(self.root),)
        with self.assertRaises(mt.TransitionError):
            self.plan(entries)

    def test_an_entry_that_is_not_an_object_is_refused(self):
        with self.assertRaises(mt.TransitionError):
            mt.timeline_entries([["not", "an", "object"]])

    def test_a_document_with_no_frames_array_is_refused(self):
        with self.assertRaises(mt.TransitionError) as caught:
            mt.timeline_entries({"transition": 1.0})
        self.assertIn("frames", str(caught.exception))

    def test_a_bare_array_of_entries_is_refused(self):
        # A BARE ARRAY CARRIES NO PROVENANCE.  It skips
        # validate_timeline() entirely -- the clamp bounds, the totals,
        # the constants and the manifest attestation all go unchecked --
        # so a hand-edited list of durations could pace the film with
        # nothing objecting.  It is refused rather than composed from.
        self.captures(2)
        entries = self.entries(2, flagged={1})
        with self.assertRaises(mt.TransitionError) as caught:
            mt.timeline_entries(entries)
        self.assertIn("not an object", str(caught.exception))

    def test_a_transition_of_another_length_is_refused(self):
        with self.assertRaises(mt.TransitionError) as caught:
            mt.transition_seconds({"transition": 2.0})
        self.assertIn("desynchronise", str(caught.exception))

    def test_a_transition_that_is_not_a_number_is_refused(self):
        with self.assertRaises(mt.TransitionError):
            mt.transition_seconds({"transition": "1.0"})


class TestComposingOneGroup(TransitionFixture):
    """Twelve frames, named and sized exactly, or nothing at all."""

    def test_a_group_is_twelve_frames(self):
        first, second = self.captures(2)
        written = self.compose(first, second)
        self.assertEqual(len(written), mt.FRAMES_PER_GROUP)
        self.assertEqual(len(self.written_names()),
                         mt.FRAMES_PER_GROUP)

    def test_the_frames_are_named_00_through_11(self):
        first, second = self.captures(2)
        self.compose(first, second, index=42)
        self.assertEqual(
            self.written_names(),
            ["trans_00042_%02d.png" % ordinal
             for ordinal in range(mt.FRAMES_PER_GROUP)])

    def test_the_returned_paths_are_in_group_order(self):
        first, second = self.captures(2)
        written = self.compose(first, second, index=7)
        self.assertEqual(
            written,
            mt.group_frame_paths(os.path.join(
                self.transitions, mt.TRANSITION_STEM_FORMAT % 7)))

    def test_every_frame_is_eight_bit_rgb_at_the_declared_size(self):
        first, second = self.captures(2)
        for path in self.compose(first, second):
            self.assertEqual(self.size_of(path), (SMALL, "RGB"))

    def test_the_group_is_a_fade_a_card_and_a_fade(self):
        # Measured, not assumed: the group starts on the picture, passes
        # through black in the middle and ends on the successor.  A hard
        # cut -- the symptom of the compositing defect this module avoids
        # -- would leave the middle as bright as the ends.
        first = self.capture(1, colour=(255, 255, 255))
        second = self.capture(2, colour=(255, 255, 255))
        written = self.compose(first, second)
        luminance = [self.mean_luma(path) for path in written]
        self.assertGreater(luminance[0], 200.0)
        self.assertGreater(luminance[-1], 200.0)
        self.assertLess(min(luminance), 10.0)
        self.assertLess(luminance[mt.FRAMES_PER_GROUP // 2], 60.0)

    def mean_luma(self, path):
        """Return one written frame's mean grayscale luminance."""
        with Image.open(path) as handle:
            return float(np.asarray(handle.convert("L")).mean())

    def test_the_card_carries_ink(self):
        # Both captures are black, so the ONLY thing in the whole group
        # that can be bright is the "…time passes…" card's own text.
        first = self.capture(1, colour=(0, 0, 0))
        second = self.capture(2, colour=(0, 0, 0))
        written = self.compose(first, second)
        brightest = [path for path in written
                     if self.max_luma(path) > 128]
        self.assertTrue(
            brightest,
            msg="no frame of the group carries the card's text")
        for path in brightest:
            with Image.open(path) as handle:
                array = np.asarray(handle.convert("L"))
            self.assertGreater(float(array.std()), 0.0)
            self.assertLess(float(array.mean()), 60.0)

    def max_luma(self, path):
        """Return one written frame's brightest grayscale pixel."""
        with Image.open(path) as handle:
            return int(np.asarray(handle.convert("L")).max())

    def test_a_real_group_at_the_capture_geometry(self):
        # ONE test at 1920x1080, from two committed captures, so the
        # production geometry is exercised and not merely described.
        for source in REAL_FRAMES:
            if not os.path.isfile(source):
                self.skipTest("the committed captures are not present")
        for index, source in enumerate(REAL_FRAMES, start=1):
            shutil.copyfile(
                source,
                os.path.join(self.frames, "frame_%05d.png" % index))
        with _environment(PLAYTHROUGH_SCREEN_WIDTH=None,
                          PLAYTHROUGH_SCREEN_HEIGHT=None):
            self.assertEqual(mt.expected_size(),
                             (mt.FRAME_WIDTH, mt.FRAME_HEIGHT))
            written = self.compose(
                os.path.join(self.frames, "frame_00001.png"),
                os.path.join(self.frames, "frame_00002.png"))
        self.assertEqual(len(written), mt.FRAMES_PER_GROUP)
        for path in written:
            self.assertEqual(
                self.size_of(path),
                ((mt.FRAME_WIDTH, mt.FRAME_HEIGHT), "RGB"))

    # -- the refusals -------------------------------------------------

    def test_a_capture_of_the_wrong_size_is_refused(self):
        first = self.capture(1)
        second = self.capture(2, size=(SMALL[0], SMALL[1] - 8))
        with self.assertRaises(mt.TransitionError) as caught:
            self.compose(first, second)
        self.assertIn("the film is cut at", str(caught.exception))
        self.assertEqual(self.all_names(), [])

    def test_a_capture_that_is_not_there_is_refused(self):
        first = self.capture(1)
        with self.assertRaises(mt.TransitionError):
            self.compose(first, os.path.join(self.frames, "gone.png"))
        self.assertEqual(self.all_names(), [])

    def test_a_capture_that_is_not_an_image_is_refused(self):
        first = self.capture(1)
        second = os.path.join(self.frames, "frame_00002.png")
        with open(second, "wb") as handle:
            handle.write(b"not a png at all")
        with self.assertRaises(mt.TransitionError):
            self.compose(first, second)
        self.assertEqual(self.all_names(), [])

    def test_a_missing_font_is_refused_by_its_path(self):
        first, second = self.captures(2)
        with self.assertRaises(mt.TransitionError) as caught:
            self.compose(first, second,
                         repo_root_dir=self.root)
        self.assertIn(mt.FONT_REL_PATH, str(caught.exception))
        self.assertEqual(self.all_names(), [])

    def test_a_prefix_outside_the_transitions_directory_is_refused(self):
        first, second = self.captures(2)
        for prefix in (os.path.join(self.frames, "trans_00001"),
                       os.path.join(self.root, "trans_00001"),
                       "/tmp/trans_00001"):
            with self.assertRaises(mt.TransitionError):
                self.compose(first, second, out_prefix=prefix)
        self.assertEqual(self.frame_names(),
                         ["frame_00001.png", "frame_00002.png"])

    def test_a_prefix_not_named_trans_is_refused(self):
        first, second = self.captures(2)
        with self.assertRaises(mt.TransitionError) as caught:
            self.compose(first, second,
                         out_prefix=os.path.join(self.transitions,
                                                 "frame_00001"))
        self.assertIn("trans_", str(caught.exception))

    def test_a_prefix_that_is_a_directory_is_refused(self):
        first, second = self.captures(2)
        prefix = os.path.join(self.transitions, "trans_00001")
        os.mkdir(prefix)
        with self.assertRaises(mt.TransitionError):
            self.compose(first, second, out_prefix=prefix)

    def test_a_short_segment_is_refused_and_publishes_nothing(self):
        first, second = self.captures(2)
        frames = [np.zeros((SMALL[1], SMALL[0], 3), dtype=np.uint8)
                  for _ in range(mt.FRAMES_PER_GROUP - 1)]
        with _patched(mt, concatenate_videoclips=lambda clips:
                      FakeSegment(frames, SMALL)):
            with self.assertRaises(mt.TransitionError) as caught:
                self.compose(first, second)
        message = str(caught.exception)
        self.assertIn("11 frame(s)", message)
        self.assertIn("desynchronise", message)
        self.assertEqual(self.all_names(), [])

    def test_a_long_segment_is_refused_and_publishes_nothing(self):
        first, second = self.captures(2)
        frames = [np.zeros((SMALL[1], SMALL[0], 3), dtype=np.uint8)
                  for _ in range(mt.FRAMES_PER_GROUP + 2)]
        with _patched(mt, concatenate_videoclips=lambda clips:
                      FakeSegment(frames, SMALL)):
            with self.assertRaises(mt.TransitionError) as caught:
                self.compose(first, second)
        self.assertIn("14 frame(s)", str(caught.exception))
        self.assertEqual(self.all_names(), [])

    def test_a_segment_of_the_wrong_size_is_refused(self):
        first, second = self.captures(2)
        frames = [np.zeros((8, 8, 3), dtype=np.uint8)]
        with _patched(mt, concatenate_videoclips=lambda clips:
                      FakeSegment(frames, (8, 8))):
            with self.assertRaises(mt.TransitionError) as caught:
                self.compose(first, second)
        self.assertIn("composed segment", str(caught.exception))
        self.assertEqual(self.all_names(), [])

    def test_no_staging_file_survives_a_refusal(self):
        first, second = self.captures(2)
        frames = [np.zeros((SMALL[1], SMALL[0], 3), dtype=np.uint8)
                  for _ in range(mt.FRAMES_PER_GROUP - 1)]
        with _patched(mt, concatenate_videoclips=lambda clips:
                      FakeSegment(frames, SMALL)):
            with self.assertRaises(mt.TransitionError):
                self.compose(first, second)
        self.assertEqual(
            [name for name in self.all_names()
             if name.startswith(mt.STAGING_PREFIX)], [])

    def test_a_previous_group_survives_a_failed_recompose(self):
        # The group is published as a GENERATION: a failure leaves the
        # previous twelve frames exactly as they were rather than a
        # mixture of two runs.
        first, second = self.captures(2)
        written = self.compose(first, second, index=3)
        before = {path: _read(path, "rb") for path in written}
        frames = [np.zeros((SMALL[1], SMALL[0], 3), dtype=np.uint8)]
        with _patched(mt, concatenate_videoclips=lambda clips:
                      FakeSegment(frames, SMALL)):
            with self.assertRaises(mt.TransitionError):
                self.compose(first, second, index=3)
        for path, data in before.items():
            self.assertEqual(_read(path, "rb"), data)

    # -- the frame normalisation --------------------------------------

    def test_a_float_frame_is_rounded_rather_than_truncated(self):
        array = np.full((2, 2, 3), 158.6, dtype=np.float64)
        converted = mt._frame_to_rgb8(array, 0)
        self.assertEqual(converted.dtype, np.uint8)
        self.assertEqual(int(converted[0, 0, 0]), 159)

    def test_a_float_frame_is_clipped_into_range(self):
        array = np.array([[[-4.0, 300.0, 12.4]]], dtype=np.float64)
        converted = mt._frame_to_rgb8(array, 0)
        self.assertEqual(list(converted[0, 0]), [0, 255, 12])

    def test_an_alpha_channel_is_dropped_and_reported(self):
        array = np.zeros((2, 2, 4), dtype=np.uint8)
        converted, warned = self.quietly(mt._frame_to_rgb8, array, 3)
        self.assertEqual(converted.shape, (2, 2, 3))
        self.assertIn("alpha channel", warned)

    def test_a_frame_of_the_wrong_shape_is_refused(self):
        with self.assertRaises(mt.TransitionError):
            mt._frame_to_rgb8(np.zeros((2, 2), dtype=np.uint8), 0)
        with self.assertRaises(mt.TransitionError):
            mt._frame_to_rgb8(np.zeros((2, 2, 2), dtype=np.uint8), 0)

    # -- the name format is a contract --------------------------------

    def test_a_disagreeing_name_format_is_refused(self):
        with _environment(
                PLAYTHROUGH_TRANSITION_FORMAT="trans_%05d-%02d.png"):
            with self.assertRaises(mt.TransitionError) as caught:
                mt.group_frame_paths(
                    os.path.join(self.transitions, "trans_00001"))
        self.assertIn("contract", str(caught.exception))

    def test_the_agreeing_name_format_is_accepted(self):
        with _environment(
                PLAYTHROUGH_TRANSITION_FORMAT=mt.TRANSITION_NAME_FORMAT):
            paths = mt.group_frame_paths(
                os.path.join(self.transitions, "trans_00001"))
        self.assertEqual(len(paths), mt.FRAMES_PER_GROUP)

    def test_every_written_name_matches_the_verifier_s_glob(self):
        first, second = self.captures(2)
        for path in self.compose(first, second, index=9):
            self.assertTrue(
                mt.TRANSITION_NAME_RE.match(os.path.basename(path)))


class TestTheGenerationManifest(TransitionFixture):
    """The provenance published BESIDE the group set.

    THE DEFECT IT EXISTS FOR IS A REAL ONE.  render_movie.py accepted a
    group because twelve files with the right NAMES and the right PIXEL
    DIMENSIONS existed for each flagged index -- and the same twelve names
    exist at the same geometry in every session that flags frame 2.  So a
    group composed from a different timeline, a group left behind for an
    index that is no longer flagged, and a frame whose pixels changed under
    its own name were all indistinguishable from the right thing.

    IT USED TO LIVE INSIDE THE DIRECTORY, so that one rename published
    both halves.  Code review found that to break the directory's own
    schema -- `trans_*.png` and nothing else -- so it moved to
    playthrough/build/transitions.json beside the film's and the
    transcripts' records, and the pair is held together by the generation
    journal instead.  Both properties are tested here: the record says
    what it always said, and the directory is pure.
    """

    def manifest_record(self):
        """Return the published provenance record."""
        return json.loads(_read(
            mt.generation_manifest_path(self.transitions)))

    def test_a_run_publishes_its_provenance_beside_the_group_set(self):
        self.captures(4)
        self.write_timeline(4, flagged={1, 3})
        self.run_make()
        published = mt.generation_manifest_path(self.transitions)
        self.assertEqual(
            published,
            os.path.join(os.path.dirname(self.transitions),
                         "transitions.json"))
        self.assertTrue(os.path.isfile(published))
        self.assertNotIn(mt.GENERATION_MANIFEST_NAME, self.all_names())
        record = self.manifest_record()
        self.assertEqual(record["version"], timeline.GENERATION_VERSION)
        self.assertEqual(record["stage"], mt.LOCK_NAME)
        self.assertEqual([one["frame"] for one in record["groups"]],
                         [1, 3])
        self.assertEqual(record["frames_per_group"],
                         mt.FRAMES_PER_GROUP)
        self.assertEqual(record["transition_seconds"],
                         mt.EXPECTED_TRANSITION)

    def test_it_binds_the_groups_to_the_timeline_and_the_captures(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        record = self.manifest_record()
        self.assertEqual(record["timeline"]["sha256"],
                         timeline.file_digest(self.timeline_path))
        sources = record["groups"][0]["sources"]
        self.assertEqual(len(sources), 2)
        self.assertEqual(
            sources[0]["sha256"],
            timeline.file_digest(os.path.join(self.frames,
                                              "frame_00002.png")))
        self.assertEqual(
            sources[1]["sha256"],
            timeline.file_digest(os.path.join(self.frames,
                                              "frame_00003.png")))
        self.assertEqual(
            record["font"]["sha256"],
            mt.font_digest(mt.font_path(REPO_ROOT)),
            msg=("the card's typeface is parsed input too, so it is part "
                 "of what the imagery is attributed to"))

    def test_every_output_is_named_with_the_bytes_that_were_written(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        outputs = self.manifest_record()["groups"][0]["outputs"]
        self.assertEqual(len(outputs), mt.FRAMES_PER_GROUP)
        for declared in outputs:
            path = os.path.join(self.transitions, declared["name"])
            with self.subTest(name=declared["name"]):
                self.assertEqual(declared["sha256"],
                                 timeline.file_digest(path))
                self.assertEqual(declared["bytes"],
                                 os.path.getsize(path))

    def test_a_published_generation_validates_against_its_timeline(self):
        self.captures(4)
        self.write_timeline(4, flagged={1, 3})
        self.run_make()
        self.assertEqual(
            mt.generation_manifest_problems(
                self.transitions, self.timeline_path, [1, 3]),
            [])

    def test_it_is_replaced_whenever_the_group_set_is(self):
        """The record always describes the generation on disk.

        The two are published as one journalled generation rather than by
        one rename, so this is the property that matters: after any run,
        the record on disk describes the frames on disk, and a stale one
        from the previous flag set cannot survive.
        """
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        self.assertEqual(
            [one["frame"] for one in self.manifest_record()["groups"]],
            [2])
        self.write_timeline(3, flagged={1})
        self.run_make()
        self.assertEqual(
            [one["frame"] for one in self.manifest_record()["groups"]],
            [1], msg="the record describes the CURRENT generation")
        self.assertEqual(
            mt.generation_manifest_problems(
                self.transitions, self.timeline_path, [1]), [])
        self.assertEqual(self.all_names(), self.written_names())

    def test_it_carries_no_host_detail_and_no_timestamp(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        text = _read(mt.generation_manifest_path(self.transitions))
        self.assertNotIn("timestamp", text)
        record = json.loads(text)
        for section in (record["timeline"], record["font"]):
            self.assertFalse(os.path.isabs(section["path"]))

    def test_a_re_run_produces_the_same_manifest_bytes(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        first = _read(mt.generation_manifest_path(self.transitions))
        self.run_make()
        self.assertEqual(
            _read(mt.generation_manifest_path(self.transitions)), first,
            msg=("deterministic, or a committed tree churns on every "
                 "render"))

    def test_an_absent_manifest_is_a_fault_and_not_a_default(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        os.unlink(mt.generation_manifest_path(self.transitions))
        with self.assertRaises(mt.TransitionError):
            mt.read_generation_manifest(self.transitions)
        problems = mt.generation_manifest_problems(
            self.transitions, self.timeline_path, [2])
        self.assertTrue(
            any("cannot be attributed to any timeline" in one
                for one in problems), msg=repr(problems))

    def test_a_manifest_that_will_not_parse_is_a_fault(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        path = mt.generation_manifest_path(self.transitions)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertTrue(mt.generation_manifest_problems(
            self.transitions, self.timeline_path, [2]))

    def test_a_manifest_from_another_schema_version_is_refused(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        path = mt.generation_manifest_path(self.transitions)
        record = json.loads(_read(path))
        record["version"] = timeline.GENERATION_VERSION + 1
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(mt.generation_manifest_text(record))
        problems = mt.generation_manifest_problems(
            self.transitions, self.timeline_path, [2])
        self.assertTrue(
            any("cannot interpret" in one for one in problems),
            msg=repr(problems))

    def test_the_manifest_is_not_counted_as_a_transition_frame(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        result = self.run_make()
        self.assertEqual(len(result.written), mt.FRAMES_PER_GROUP)
        self.assertEqual(len(self.written_names()), mt.FRAMES_PER_GROUP)
        self.assertNotIn(mt.GENERATION_MANIFEST_NAME,
                         self.written_names(),
                         msg=("verify_artifacts.sh globs trans_*.png, so "
                              "the manifest must not be inside that glob"))

    def test_the_published_directory_holds_only_transition_frames(self):
        """Code review finding: one surplus entry in a PNG-only folder.

        The frozen schema for this directory admits `trans_*.png` and
        nothing else, the AAP lists only PNGs in it, and the acceptance
        gate globs it.  A tracked JSON file among the frames was a
        surplus entry however useful its contents.
        """
        self.captures(4)
        self.write_timeline(4, flagged={1, 3})
        self.run_make()
        names = self.all_names()
        self.assertEqual(names, self.written_names())
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(mt.TRANSITION_NAME_RE.match(name))

    def test_a_legacy_in_directory_record_is_swept_not_carried(self):
        """A directory published by an older version is cleaned.

        The retired name is this module's OWN litter, so the switch
        removes it.  Carrying it -- which is what happens to a file this
        module never wrote -- would leave the directory impure for ever.
        """
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        legacy = os.path.join(self.transitions, mt.LEGACY_MANIFEST_NAME)
        with open(legacy, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        self.run_make()
        self.assertFalse(os.path.exists(legacy))
        self.assertEqual(self.all_names(), self.written_names())

    def test_an_interrupted_publication_is_reported_and_repaired(self):
        """The two halves are one generation, journalled.

        Publishing the record outside the directory means two renames.
        The journal names both before the first one, so a run killed
        between them leaves a state the NEXT run reports and repairs
        rather than a group set nobody can attribute.
        """
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        published = mt.generation_manifest_path(self.transitions)
        text = _read(published)
        timeline.write_generation_journal(mt.LOCK_NAME, {
            "version": timeline.GENERATION_VERSION,
            "stage": mt.LOCK_NAME,
            "timeline": os.path.abspath(self.timeline_path),
            "directory": os.path.abspath(self.transitions),
            "frames": self.written_names(),
            "targets": [{"path": os.path.abspath(published),
                         "sha256": "0" * 64}],
        }, self.root)
        _result, noise = self.quietly(
            mt.make_transitions,
            timeline_path=self.timeline_path,
            transitions_dir=self.transitions,
            root=self.root, repo_root_dir=REPO_ROOT)
        self.assertIn("interrupted", noise)
        self.assertEqual(_read(published), text)
        self.assertIsNone(
            timeline.read_generation_journal(mt.LOCK_NAME, self.root),
            msg="a completed publication clears its own journal")

    # -- the staged sibling, and every way it can be left behind ------

    def staged(self):
        """Where the provenance record is staged before its rename."""
        return mt.staged_manifest_path(self.transitions)

    def test_the_staged_sibling_is_gone_after_an_ordinary_run(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        self.run_make()
        self.assertFalse(
            os.path.exists(self.staged()),
            msg="the rename consumes it; nothing else may remain")

    def test_a_short_write_leaves_no_sibling_behind(self):
        """THE DEFECT: a raise between open and rename left the file.

        `.transitions.json.publishing` lives in playthrough/build/, which
        .gitignore re-includes wholesale and which the transitions
        directory's own litter sweep does not cover -- so the sibling
        would sit there until a `git add -A playthrough/` committed a
        half-written provenance record nobody authored.
        """
        original = os.write

        def stall(descriptor, data):
            """Write nothing, as a full device would."""
            return 0

        os.write = stall
        self.addCleanup(setattr, os, "write", original)
        with self.assertRaises(mt.TransitionError):
            mt._publish_generation_manifest(self.transitions, "{}\n")
        os.write = original
        self.assertFalse(
            os.path.exists(self.staged()),
            msg="a write that made no progress must clean up after "
                "itself")

    def test_a_failing_fsync_leaves_no_sibling_behind(self):
        original = os.fsync

        def refuse(descriptor):
            raise OSError(5, "I/O error")

        os.fsync = refuse
        self.addCleanup(setattr, os, "fsync", original)
        with self.assertRaises(OSError):
            mt._publish_generation_manifest(self.transitions, "{}\n")
        os.fsync = original
        self.assertFalse(os.path.exists(self.staged()))

    def test_a_failing_rename_leaves_no_sibling_behind(self):
        original = os.replace

        def refuse(source, target):
            raise OSError(13, "permission denied")

        os.replace = refuse
        self.addCleanup(setattr, os, "replace", original)
        with self.assertRaises(mt.TransitionError):
            mt._publish_generation_manifest(self.transitions, "{}\n")
        os.replace = original
        self.assertFalse(os.path.exists(self.staged()))

    def test_a_whole_buffer_larger_than_one_write_still_publishes(self):
        """A short write is ordinary, not a failure.

        The old check treated any os.write that returned fewer bytes than
        it was given as a failed generation, which is wrong: a partial
        write is normal and the buffer is simply written again.
        """
        original = os.write

        def dribble(descriptor, data):
            """Write one byte at a time, as a slow pipe would."""
            return original(descriptor, data[:1])

        os.write = dribble
        self.addCleanup(setattr, os, "write", original)
        text = json.dumps({"version": timeline.GENERATION_VERSION}) + "\n"
        published = mt._publish_generation_manifest(
            self.transitions, text)
        os.write = original
        self.assertEqual(_read(published), text)
        self.assertFalse(os.path.exists(self.staged()))

    def test_a_stale_sibling_is_swept_at_the_start_of_a_run(self):
        """The half no failure handler can cover.

        A run killed outright runs no handler at all, so the sibling
        survives with nobody to remove it.  The next generation clears
        it under the same lock, where it is unambiguously stale, and says
        so rather than removing a file in silence.
        """
        self.captures(3)
        self.write_timeline(3, flagged={2})
        with open(self.staged(), "w", encoding="utf-8") as handle:
            handle.write('{"half": "written"')
        _result, noise = self.quietly(
            mt.make_transitions,
            timeline_path=self.timeline_path,
            transitions_dir=self.transitions,
            root=self.root, repo_root_dir=REPO_ROOT)
        self.assertIn("staged provenance record", noise)
        self.assertFalse(os.path.exists(self.staged()))
        self.assertTrue(os.path.isfile(
            mt.generation_manifest_path(self.transitions)))

    def test_a_sibling_that_is_not_a_plain_file_stops_the_run(self):
        """It stages a plain file, and removes or writes nothing else.

        The name is inside the committed tree, so a symlink planted there
        must be neither followed nor deleted: O_NOFOLLOW refuses the
        write, the sweep refuses the removal, and the generation fails
        with the planted link and its target both exactly as they were.
        A module that will not write through a link must not quietly
        delete one either.
        """
        elsewhere = os.path.join(self.root, "not-a-target")
        with open(elsewhere, "w", encoding="utf-8") as handle:
            handle.write("do not touch me\n")
        os.symlink(elsewhere, self.staged())
        self.captures(3)
        self.write_timeline(3, flagged={2})
        with self.assertRaises(mt.TransitionError) as caught:
            self.quietly(
                mt.make_transitions,
                timeline_path=self.timeline_path,
                transitions_dir=self.transitions,
                root=self.root, repo_root_dir=REPO_ROOT)
        self.assertIn("could not stage the provenance record",
                      str(caught.exception))
        self.assertTrue(os.path.islink(self.staged()))
        self.assertEqual(_read(elsewhere), "do not touch me\n")


class TestTheDirectoryDescribesTheTimeline(TransitionFixture):
    """A re-run leaves the current timeline's groups and nothing else."""

    def test_a_stale_group_is_removed(self):
        self.captures(3)
        self.write_timeline(3, flagged={1, 2})
        self.run_make()
        self.assertEqual(len(self.written_names()),
                         2 * mt.FRAMES_PER_GROUP)
        self.write_timeline(3, flagged={2})
        result = self.run_make()
        self.assertEqual(result.groups, 1)
        self.assertEqual(len(self.written_names()),
                         mt.FRAMES_PER_GROUP)
        # THE CONTRACT IS WHAT SURVIVES, not how many files the
        # reconciliation touched: the generation is published by
        # switching the whole directory, so a count of removals is a
        # property of that strategy rather than of the result.  What
        # matters is that the stale group is gone and the directory
        # describes the current timeline exactly.
        self.assertGreaterEqual(len(result.removed), mt.FRAMES_PER_GROUP)
        for name in self.written_names():
            self.assertTrue(name.startswith("trans_00002_"))
        self.assertEqual(
            sorted(self.written_names()),
            sorted(os.path.basename(one) for one in
                   mt.group_frame_paths(
                       os.path.join(self.transitions, "trans_00002"))))

    def test_a_re_run_is_idempotent_byte_for_byte(self):
        # The artifacts are committed, so the same timeline over the same
        # captures has to produce the same bytes -- otherwise every re-run
        # is a diff nobody authored.
        self.captures(3)
        self.write_timeline(3, flagged={2})
        first = self.run_make()
        before = {path: _read(path, "rb")
                  for path in first.written}
        second = self.run_make()
        self.assertEqual(second.written, first.written)
        for path, data in before.items():
            self.assertEqual(_read(path, "rb"), data)

    def test_an_abandoned_staging_file_is_swept(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        litter = os.path.join(self.transitions,
                              mt.STAGING_PREFIX + "00002_00.png")
        with open(litter, "wb") as handle:
            handle.write(b"a run that was killed")
        result = self.run_make()
        self.assertIn(litter, result.removed)
        self.assertFalse(os.path.exists(litter))

    def test_a_file_nobody_else_wrote_is_left_alone(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        keepsake = os.path.join(self.transitions, "notes.txt")
        with open(keepsake, "w", encoding="utf-8") as handle:
            handle.write("not a transition frame\n")
        self.run_make()
        self.assertTrue(os.path.isfile(keepsake))

    def test_a_frame_matching_the_glob_but_not_the_format_is_refused(
            self):
        # REFUSED, not warned about: the acceptance gate globs
        # `trans_*.png`, so this file WOULD be counted as a transition
        # frame, and a run that returned success beside it would hand the
        # gate a directory it will reject.  It is not deleted either --
        # removing a file this module did not write is not
        # reconciliation -- so the run stops and names it.
        self.captures(3)
        self.write_timeline(3, flagged={2})
        odd = os.path.join(self.transitions, "trans_2_0.png")
        Image.new("RGB", SMALL, (1, 2, 3)).save(odd)
        with self.assertRaises(mt.TransitionError) as caught:
            mt.make_transitions(self.timeline_path, self.transitions,
                                self.root, REPO_ROOT)
        message = str(caught.exception)
        self.assertIn("trans_2_0.png", message)
        self.assertIn(mt.TRANSITION_NAME_FORMAT, message)
        self.assertTrue(os.path.isfile(odd))

    def test_a_file_matching_no_glob_at_all_is_still_left_alone(self):
        # The line between "not mine to delete" and "not my business":
        # a name outside the acceptance glob is counted by nothing, so
        # it neither stops the run nor gets removed.
        self.captures(3)
        self.write_timeline(3, flagged={2})
        keepsake = os.path.join(self.transitions, "notes-trans.png")
        Image.new("RGB", SMALL, (4, 5, 6)).save(keepsake)
        result = self.run_make()
        self.assertEqual(result.groups, 1)
        self.assertTrue(os.path.isfile(keepsake))
        self.assertNotIn(keepsake, result.removed)

    def test_a_symlinked_frame_is_refused_and_not_followed(self):
        self.captures(3)
        target = os.path.join(self.root, "outside.png")
        Image.new("RGB", SMALL, (9, 9, 9)).save(target)
        link = os.path.join(self.transitions, "trans_00099_00.png")
        os.symlink(target, link)
        with self.assertRaises(mt.TransitionError) as caught:
            mt._assert_no_foreign_transition_frames(self.transitions)
        self.assertIn("not a regular file", str(caught.exception))
        # Not followed, not removed, and the target is untouched.
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.isfile(target))

    def test_a_directory_named_like_a_frame_is_refused(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        intruder = os.path.join(self.transitions, "trans_00099_00.png")
        os.mkdir(intruder)
        with self.assertRaises(mt.TransitionError) as caught:
            mt.make_transitions(self.timeline_path, self.transitions,
                                self.root, REPO_ROOT)
        self.assertIn("not a regular file", str(caught.exception))
        self.assertTrue(os.path.isdir(intruder))

    def test_a_frame_that_appears_mid_run_is_caught_at_the_end(self):
        # The closing inventory re-lists the COMPLETE glob after the
        # groups are written, so an entry that was not there when the
        # directory was reconciled is still refused rather than handed
        # to the gate.
        self.captures(3)
        self.write_timeline(3, flagged={2})
        original = mt.compose_transition_group
        intruder = os.path.join(self.transitions, "trans_00007_00.png")

        def compose_then_litter(*args, **kwargs):
            written = original(*args, **kwargs)
            Image.new("RGB", SMALL, (7, 7, 7)).save(intruder)
            return written

        with _patched(mt, compose_transition_group=compose_then_litter):
            with self.assertRaises(mt.TransitionError) as caught:
                mt.make_transitions(
                    self.timeline_path, self.transitions, self.root,
                    REPO_ROOT)
        message = str(caught.exception)
        self.assertIn("trans_00007_00.png", message)
        self.assertIn("unaccounted for", message)
        self.assertTrue(os.path.isfile(intruder))

    def test_inspecting_a_directory_that_is_not_there_is_a_no_op(self):
        # The run CREATES its output directory (see
        # test_the_output_directory_is_created_when_absent), so there is
        # nothing to refuse: an absent directory holds no foreign frame.
        mt._assert_no_foreign_transition_frames(
            os.path.join(self.root, "nowhere"))
        self.assertEqual(
            mt._foreign_entries(os.path.join(self.root, "nowhere")), [])


class TestTheWholeRun(TransitionFixture):
    """What one run of the module leaves on disk, and where."""

    def test_a_run_reports_the_identity_it_maintained(self):
        self.captures(4)
        self.write_timeline(4, flagged={1, 3})
        result = self.run_make()
        self.assertEqual(result.flagged, 2)
        self.assertEqual(result.groups, 2)
        self.assertEqual(len(result.written),
                         2 * mt.FRAMES_PER_GROUP)
        self.assertEqual(result.directory, self.transitions)

    def test_the_groups_on_disk_equal_the_flags_in_the_timeline(self):
        self.captures(6)
        self.write_timeline(6, flagged={2, 4, 5})
        self.run_make()
        stems = sorted({name[:len("trans_00002")]
                        for name in self.written_names()})
        self.assertEqual(stems,
                         ["trans_00002", "trans_00004", "trans_00005"])

    def test_a_timeline_with_no_flags_writes_nothing(self):
        self.captures(3)
        self.write_timeline(3)
        result = self.run_make()
        self.assertEqual(result.flagged, 0)
        self.assertEqual(result.written, [])
        self.assertEqual(self.written_names(), [])

    def test_nothing_is_ever_written_under_the_frames_directory(self):
        # THE INTEGRITY CONSTRAINT.  playthrough/frames/ holds one PNG
        # per keystroke; a derived frame in there would destroy the count
        # identity that proves it.
        before = self.captures(3)
        self.write_timeline(3, flagged={1, 2})
        self.run_make()
        self.assertEqual(self.frame_names(),
                         [os.path.basename(path) for path in before])

    def test_the_output_directory_cannot_be_aimed_at_frames(self):
        self.captures(3)
        self.write_timeline(3, flagged={1})
        for directory in (self.frames, self.root,
                          os.path.join(self.root, "build"), "/tmp"):
            with self.assertRaises(mt.TransitionError):
                self.run_make(transitions_dir=directory)
        self.assertEqual(self.frame_names(),
                         ["frame_00001.png", "frame_00002.png",
                          "frame_00003.png"])

    def test_two_flags_sharing_an_index_are_refused(self):
        self.captures(3)
        document = self.document(3, flagged={1, 2})
        document["frames"][1]["frame"] = 1
        with open(self.timeline_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        with self.assertRaises(mt.TransitionError) as caught:
            self.run_make()
        # The CONTRACT is that a repeated index is refused.  The shared
        # timeline gate now catches it before the group planner reaches
        # it, and names the 1..n identity it breaks.
        self.assertIn("no repeat", str(caught.exception))

    def test_a_timeline_that_is_not_there_is_refused(self):
        with self.assertRaises(mt.TransitionError) as caught:
            self.run_make(
                timeline_path=os.path.join(self.root, "nowhere.json"))
        self.assertIn("timeline", str(caught.exception))

    def test_a_timeline_outside_the_tree_is_refused(self):
        with self.assertRaises(mt.TransitionError):
            self.run_make(timeline_path="/etc/hostname")

    def test_a_timeline_that_is_not_json_is_refused(self):
        with open(self.timeline_path, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        with self.assertRaises(mt.TransitionError):
            self.run_make()

    def test_the_output_directory_is_created_when_absent(self):
        self.captures(2)
        self.write_timeline(2, flagged={1})
        _remove_tree(self.transitions)
        self.assertFalse(os.path.isdir(self.transitions))
        result = self.run_make()
        self.assertEqual(len(result.written), mt.FRAMES_PER_GROUP)

    def test_a_non_directory_in_the_output_path_is_refused(self):
        self.captures(2)
        self.write_timeline(2, flagged={1})
        _remove_tree(self.transitions)
        with open(self.transitions, "w", encoding="utf-8") as handle:
            handle.write("in the way\n")
        with self.assertRaises(mt.TransitionError):
            self.run_make()


class TestTheComposerEntersTheDecoderUnderConditions(TransitionFixture):
    """This module composes from frames it must first be able to trust.

    The decode here is MoviePy's, which is Pillow's, which is the pinned
    11.3.0 -- the same native decoders and the same advisories that
    ocr_clock.py guards against, reached by a different route.  A
    security review found the captured frames group- and world-writable,
    so "we only ever decode what we captured" was an argument rather than
    a property.  Both modules now check it at their own door.
    """

    def test_an_owner_only_pair_composes(self):
        """The control must not refuse the ordinary case."""
        self.captures(3)
        self.write_timeline(3, flagged={2})
        status, out, _ = self.main(
            ["--timeline", self.timeline_path,
             "--transitions-dir", self.transitions,
             "--repo-root", REPO_ROOT])
        self.assertEqual(status, mt.EXIT_OK, msg=out)

    def refusal(self, arrange):
        """Arrange a bad frame, run, and return the diagnosis."""
        paths = self.captures(3)
        self.write_timeline(3, flagged={2})
        arrange(paths)
        status, _out, err = self.main(
            ["--timeline", self.timeline_path,
             "--transitions-dir", self.transitions,
             "--repo-root", REPO_ROOT])
        self.assertNotEqual(status, mt.EXIT_OK,
                            msg="the group composed from a frame that "
                                "should have been refused")
        return err

    def test_a_world_writable_frame_is_refused(self):
        """The exact condition the review measured, at this door."""
        err = self.refusal(lambda paths: os.chmod(paths[1], 0o666))
        self.assertIn("writable beyond its owner", err)

    def test_a_group_writable_frame_is_refused(self):
        err = self.refusal(lambda paths: os.chmod(paths[1], 0o660))
        self.assertIn("writable beyond its owner", err)

    def test_a_symlink_is_judged_by_what_it_points_AT(self):
        """Where this module differs from ocr_clock, and why it is right.

        This module resolves every input path before it validates it, so
        by the time the provenance check runs it holds the real file
        rather than the link -- which means the link itself is never what
        gets judged.  That is the correct behaviour and not a gap: the
        bytes the decoder will parse are the target's bytes, so the
        target's owner and mode are the facts that matter.

        Proved by pointing a frame at a world-writable file and watching
        the refusal name the TARGET.  A test asserting "symbolic link"
        here would have been asserting something untrue -- and did, until
        this measured what actually happens.
        """
        def swap(paths):
            target = paths[2]
            os.chmod(target, 0o666)
            os.unlink(paths[1])
            os.symlink(target, paths[1])
        err = self.refusal(swap)
        self.assertIn("writable beyond its owner", err)
        self.assertIn("frame_00003.png", err)

    def test_a_frame_replaced_by_a_fifo_is_refused(self):
        def swap(paths):
            os.unlink(paths[1])
            os.mkfifo(paths[1], 0o600)
        self.assertIn("not a regular file", self.refusal(swap))

    @unittest.skipIf(mt.resource is None, "needs POSIX resource limits")
    def test_the_limits_hold_over_the_whole_lazy_decode(self):
        """Where the guard has to reach, and why it is easy to get wrong.

        MoviePy is LAZY: constructing an ImageClip decodes nothing, and
        the pixels are produced during ``iter_frames``.  A guard wrapped
        around the construction alone would have looked right and covered
        none of the decoding, so the block extends over the iteration
        too.  This asserts the shape structurally, because the runtime
        symptom of getting it wrong is nothing at all.
        """
        source = os.path.join(TOOLING, "make_transitions.py")
        with io.open(source, encoding="utf-8") as handle:
            lines = handle.readlines()
        opened = None
        for number, line in enumerate(lines):
            if line.strip() == "with decode_limits():":
                opened = number
        self.assertIsNotNone(opened, "the guard is gone")
        indent = len(lines[opened]) - len(lines[opened].lstrip())
        body = []
        for line in lines[opened + 1:]:
            if not line.strip():
                continue
            if len(line) - len(line.lstrip()) <= indent:
                break
            body.append(line)
        text = "".join(body)
        # The clips are built from the ARRAYS the verified read produced,
        # which is what keeps a pathname away from the decoder; the guard
        # still has to cover the lazy part, so the names are the array
        # variables rather than the paths.
        self.assertIn("ImageClip(source_frame)", text)
        self.assertIn("concatenate_videoclips(clips)", text)
        self.assertIn("iter_frames(fps=FPS)", text)

    def test_no_clip_and_no_decoder_is_handed_a_pathname(self):
        """The check-to-use race, asserted structurally.

        A review found the provenance rule applied with `lstat` while the
        frame was handed to MoviePy BY NAME, which reopens it and hands it
        to Pillow -- so the bytes parsed were not the bytes checked.  An
        `ImageClip(<a path>)` or an `Image.open(<a path>)` anywhere in
        this module would be that defect returning, so both are asserted
        against rather than left to a comment.
        """
        source = os.path.join(TOOLING, "make_transitions.py")
        with io.open(source, encoding="utf-8") as handle:
            lines = handle.readlines()
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            with self.subTest(line=number):
                if "Image.open(" in line:
                    self.assertIn("Image.open(io.BytesIO(", line)
                if "ImageClip(" in line and "def " not in line:
                    self.assertNotIn("ImageClip(source)", line)
                    self.assertNotIn("ImageClip(target)", line)

    def test_the_verified_read_returns_the_bytes_it_validated(self):
        """One open, one fstat, one read, and the bytes are the file's."""
        paths = self.captures(1)
        with io.open(paths[0], "rb") as handle:
            expected = handle.read()
        self.assertEqual(mt.read_verified_frame(paths[0]), expected)

    def test_a_frame_past_the_byte_ceiling_is_refused_unread(self):
        paths = self.captures(2)
        with io.open(paths[1], "wb") as handle:
            handle.write(mt.PNG_MAGIC)
            handle.truncate(mt.MAX_FRAME_BYTES + 1)
        os.chmod(paths[1], 0o600)
        with self.assertRaises(mt.TransitionError) as caught:
            mt.read_verified_frame(paths[1])
        self.assertIn("ceiling", str(caught.exception))

    @unittest.skipIf(mt.resource is None, "needs POSIX resource limits")
    def test_a_core_dump_is_forbidden_and_cpu_bounded(self):
        with mt.decode_limits():
            core, _ = mt.resource.getrlimit(mt.resource.RLIMIT_CORE)
            cpu, _ = mt.resource.getrlimit(mt.resource.RLIMIT_CPU)
        self.assertEqual(core, 0)
        self.assertNotEqual(cpu, mt.resource.RLIM_INFINITY)

    @unittest.skipIf(mt.resource is None, "needs POSIX resource limits")
    def test_the_limits_are_restored_even_when_the_body_raises(self):
        before = mt.resource.getrlimit(mt.resource.RLIMIT_CORE)
        with self.assertRaises(ValueError):
            with mt.decode_limits():
                raise ValueError("the composition failed")
        self.assertEqual(mt.resource.getrlimit(mt.resource.RLIMIT_CORE),
                         before)

    @unittest.skipIf(mt.resource is None, "needs POSIX resource limits")
    def test_a_tighter_existing_limit_is_left_alone(self):
        original = mt.resource.getrlimit(mt.resource.RLIMIT_CPU)
        self.addCleanup(mt.resource.setrlimit, mt.resource.RLIMIT_CPU,
                        original)
        mt.resource.setrlimit(mt.resource.RLIMIT_CPU, (5, original[1]))
        with mt.decode_limits():
            soft, _ = mt.resource.getrlimit(mt.resource.RLIMIT_CPU)
        self.assertEqual(soft, 5)

    def test_this_module_and_the_ocr_module_agree_on_their_caps(self):
        """The duplication, converted into a checked property.

        These two modules are standalone scripts and neither imports the
        other, so each states the decode caps itself.  A copied constant
        that nothing compares is a second definition waiting to drift --
        the same shape of defect as a test fixture that copies a
        production record format and is correct only until the format
        moves.  So the agreement is asserted rather than assumed.
        """
        import ocr_clock
        self.assertEqual(mt.MAX_PIXELS, ocr_clock.MAX_PIXELS)
        self.assertEqual(mt.DECODE_CPU_SECONDS,
                         ocr_clock.DECODE_CPU_SECONDS)
        self.assertEqual(mt.PNG_MAGIC, ocr_clock.PNG_MAGIC)

    def test_neither_module_bounds_the_address_space(self):
        """Recorded so it is not helpfully added back.

        numpy reserves roughly 2.5 GiB of virtual address space at import,
        so an RLIMIT_AS tight enough to bound a decode refuses the import
        and one loose enough to import bounds nothing -- verified by
        lowering it to 300 MiB after import and watching a full 1920x1080
        decode still succeed.  See ocr_clock.decode_limits.
        """
        for module in (mt, __import__("ocr_clock")):
            source = os.path.join(TOOLING, module.__name__ + ".py")
            with io.open(source, encoding="utf-8") as handle:
                body = handle.read()
            with self.subTest(module=module.__name__):
                self.assertNotIn("setrlimit(resource.RLIMIT_AS", body)
                self.assertNotIn('"RLIMIT_AS"', body)


class TestTheCommandLine(TransitionFixture):
    """The status run_pipeline.sh reads, and the summary it prints."""

    def test_a_successful_run_exits_zero_with_a_summary(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        status, out, _ = self.main(
            ["--timeline", self.timeline_path,
             "--transitions-dir", self.transitions,
             "--repo-root", REPO_ROOT])
        self.assertEqual(status, mt.EXIT_OK)
        self.assertIn("transitions ok", out)
        self.assertIn("1 group(s)", out)
        self.assertIn("12 frame(s)", out)

    def test_quiet_prints_nothing_on_success(self):
        self.captures(3)
        self.write_timeline(3, flagged={2})
        status, out, _ = self.main(
            ["--timeline", self.timeline_path,
             "--transitions-dir", self.transitions,
             "--repo-root", REPO_ROOT, "--quiet"])
        self.assertEqual(status, mt.EXIT_OK)
        self.assertEqual(out, "")

    def test_a_refusal_exits_one_and_says_why(self):
        self.captures(2)
        self.write_timeline(2, flagged={2})
        status, out, err = self.main(
            ["--timeline", self.timeline_path,
             "--transitions-dir", self.transitions,
             "--repo-root", REPO_ROOT])
        self.assertEqual(status, mt.EXIT_FAILED)
        self.assertEqual(out, "")
        # The CONTRACT is that it exits one, writes nothing and SAYS WHY.
        # The shared timeline gate reports the offending flag per entry
        # before the document-level 'final-frame-flagged' code is
        # reached, so the reason named is the flag itself.
        self.assertIn("transition_after", err)
        self.assertEqual(self.all_names(), [])

    def test_a_missing_timeline_exits_one(self):
        status, _, err = self.main(
            ["--timeline", os.path.join(self.root, "nowhere.json"),
             "--transitions-dir", self.transitions,
             "--repo-root", REPO_ROOT])
        self.assertEqual(status, mt.EXIT_FAILED)
        self.assertIn("make_transitions.py:", err)

    def test_the_output_directory_argument_is_still_contained(self):
        self.captures(2)
        self.write_timeline(2, flagged={1})
        status, _, err = self.main(
            ["--timeline", self.timeline_path,
             "--transitions-dir", self.frames,
             "--repo-root", REPO_ROOT])
        self.assertEqual(status, mt.EXIT_FAILED)
        self.assertIn("make_transitions.py:", err)
        self.assertEqual(self.frame_names(),
                         ["frame_00001.png", "frame_00002.png"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
