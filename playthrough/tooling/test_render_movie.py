#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/render_movie.py.

    python3 -B playthrough/tooling/test_render_movie.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

The -B keeps __pycache__ out of playthrough/tooling/, which .gitignore's
terminal `!/playthrough/**` negation would otherwise make committable;
this module sets sys.dont_write_bytecode for the same reason.

WHY THIS MODULE IS WORTH A SUITE
The concat list is the instruction sheet for the film, and every way of
getting it wrong produces a container that plays:

* A DROPPED TERMINAL REPEAT.  The concat demuxer ignores the last
  `duration` unless the final `file` entry is repeated, so the container
  comes up short by that frame's window -- measured at 10.52 s against
  an 11.75 s subtitle stream for the same timeline.  Nothing else
  changes: the frames are all there, every count matches, and every
  caption past the shortfall points beyond the end of the film.
* A TRANSITION SPLIT THAT DOES NOT SUM.  The timeline charges exactly
  one second of video per flagged frame.  A group whose twelve durations
  add up to 0.999996 s drifts the picture away from the cues by 4 us
  every time the ceiling engages, always in the same direction.
* A PATH SPELLED AGAINST THE WRONG DIRECTORY.  A relative entry means
  whatever the working directory says it means, so a list that is
  correct in the repository root is a list of missing files anywhere
  else -- and the two spellings this module keeps (relative in the
  committed artifact, absolute for the encoder) are what makes the
  committed list both readable and unambiguous.
* AN OUTPUT FLAG THAT MUST NOT BE THERE.  `-r` alongside `-fps_mode
  vfr` makes ffmpeg abort, and any `-vf` at all would burn the captions
  into the picture, which is forbidden -- the track is a selectable
  mov_text stream muxed by embed_captions.sh.

So the properties asserted here are arithmetic and textual: the exact
ordered durations, the exact lines, the exact argv, and the exact
refusals.  Nothing is asserted about "a movie being produced", because
that is the one thing every one of these defects still does.

HOW A RENDERER IS TESTED WITHOUT ENCODING A FILM
Two seams.  render_movie._run is the module's only gateway to another
process, and a recording double stands in for it -- so `encode()` builds
its transient list, streams it, counts its lines and hands over an argv
that is then asserted, without libx264 ever starting.  verified_tool()
resolves through env.sh's own $PLAYTHROUGH_BIN_<NAME>, so the double is
pointed at a real executable file inside the fixture and no ffmpeg is
required on the host.  Everything between those seams is the production
code: the plan, the list, the counts, the mapping, the probe parsing,
the verification and the staging.

Captures and transition frames are ordinary small PNGs written by
Pillow, because this module only ever stats them; the one thing it reads
from an image is nothing at all.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import stat
import tempfile
import unittest

from decimal import Decimal

sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
if TOOLING not in sys.path:
    sys.path.insert(0, TOOLING)

import make_transitions as mt  # noqa: E402  (path set above)
import manifest  # noqa: E402  (path set above)
import render_movie as rm  # noqa: E402  (path set above)
import timeline  # noqa: E402  (path set above)

# The twelve durations one transition second must come out as: eleven
# base slices and the exact remainder a twelfth of a second cannot
# express.  Spelled out rather than computed, because a test that
# computed them the way the module does would pass with the module
# wrong.
EXPECTED_SHARES = ["0.083333"] * 11 + ["0.083337"]

SOURCE_NAME = "render_movie.py"

# The card's typeface, named in the group set's generation manifest so the
# provenance covers every input the imagery was composed from.  Resolved
# from this checkout, which is where make_transitions.py reads it.
_FONT_PATH = os.path.join(os.path.dirname(TOOLING), os.pardir,
                          "data", "font", "Terminus.ttf")


def _read(path, mode="r"):
    """Return a whole file, with its descriptor closed again."""
    if "b" in mode:
        with open(path, mode) as handle:
            return handle.read()
    with open(path, mode, encoding="utf-8") as handle:
        return handle.read()


SOURCE = _read(os.path.join(TOOLING, SOURCE_NAME))


def _remove_tree(path):
    """Remove a temporary tree, tolerating a partial one."""
    shutil.rmtree(path, ignore_errors=True)


def _trusted_tool_dir():
    """Return a private directory whose whole ancestry is trusted.

    verified_tool() walks every directory on the way to the binary and
    refuses one that is group- or world-writable or owned by another
    account.  A stub therefore cannot live under /tmp (mode 1777).  This
    creates one under a root-owned, 0755 base -- the same shape as
    /usr/bin -- and falls back to skipping the trust-dependent tests if
    no such base is available on the host.
    """
    for base in ("/opt", "/usr/local/lib", "/var/lib"):
        try:
            entry = os.lstat(base)
        except OSError:
            continue
        if entry.st_uid not in (0, os.getuid()):
            continue
        if entry.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            continue
        try:
            directory = tempfile.mkdtemp(dir=base, prefix="blitzy_bin_")
        except OSError:
            continue
        os.chmod(directory, 0o755)
        return directory
    raise unittest.SkipTest(
        "no root-owned, non-world-writable base directory is available "
        "to hold a stub the tool-trust check will accept")


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


class FakeProcesses(object):
    """A recording double for render_movie._run.

    Answers the encode by creating the output file the module then
    measures, and the probe with a JSON document a test chooses, while
    remembering every argv -- which is what turns "there is no -vf in
    the command" into an assertion rather than a comment.
    """

    def __init__(self):
        self.calls = []
        self.lists = []
        self.encode_status = 0
        self.encode_bytes = rm.MIN_OUTPUT_BYTES * 2
        self.probe_document = None
        self.probe_status = 0
        self.probe_text = None

    def __call__(self, command, cwd, label,
                 timeout=rm.ENCODE_TIMEOUT, check=True):
        command = list(command)
        self.calls.append({"argv": command, "cwd": cwd,
                           "label": label, "timeout": timeout})
        if os.path.basename(command[0]).startswith("ffprobe"):
            return self.probe(command)
        return self.encode(command)

    # -- the two answers ----------------------------------------------

    def encode(self, command):
        """Pretend to encode: record the list, write the output."""
        list_path = command[command.index("-i") + 1]
        self.lists.append(_read(list_path))
        if self.encode_status != 0:
            raise rm.RenderError("the ffmpeg encode exited 1")
        with open(command[-1], "wb") as handle:
            handle.write(b"\x00" * self.encode_bytes)
        return ""

    def probe(self, command):
        """Answer ffprobe with the document this test chose.

        A packet count is supplied unless the test chose one, derived
        from the concat list the encode was given -- one coded picture
        per `file` entry, which is what the demuxer really produces, the
        repeated final entry included.  Without it every verification
        would trip the "neither a packet count nor nb_frames" refusal
        that exists to catch a dropped or duplicated image.
        """
        if self.probe_status != 0:
            raise rm.RenderError("ffprobe exited 1")
        if self.probe_text is not None:
            return self.probe_text
        document = (self.probe_document if self.probe_document is not None
                    else default_probe())
        self._supply_packets(document)
        return json.dumps(document)

    def _supply_packets(self, document):
        """Fill in nb_read_packets from the list the encode was handed."""
        if not self.lists:
            return
        counted = len([line for line in self.lists[-1].splitlines()
                       if line.startswith(rm.CONCAT_FILE_PREFIX)])
        for stream in document.get("streams", []):
            if stream.get("codec_type") != rm.CODEC_TYPE_VIDEO:
                continue
            stream.setdefault("nb_read_packets", str(counted))

    # -- reading it back ----------------------------------------------

    def argv_of(self, tool):
        """Return every recorded argv for one tool, in order."""
        return [call["argv"] for call in self.calls
                if os.path.basename(call["argv"][0]).startswith(tool)]


def default_probe(duration=None, width=1920, height=1080,
                  codec=rm.CODEC_NAME_H264, audio=0, video=1,
                  packets=None):
    """Return an ffprobe document describing a plausible render.

    `nb_read_packets` is the demuxed picture count the verification
    compares with the plan.  Under -fps_mode vfr the header's nb_frames
    is routinely "N/A", which is exactly why the probe asks for
    -count_packets, so the double answers the same way a real ffprobe
    does: a useless header count beside a real packet count.
    """
    streams = []
    for _ in range(video):
        stream = {
            "codec_type": rm.CODEC_TYPE_VIDEO,
            "codec_name": codec,
            "width": width,
            "height": height,
            "nb_frames": "N/A",
        }
        if packets is not None:
            stream["nb_read_packets"] = str(packets)
        streams.append(stream)
    for _ in range(audio):
        streams.append({"codec_type": rm.CODEC_TYPE_AUDIO,
                        "codec_name": "aac"})
    container = {}
    if duration is not None:
        container["duration"] = duration
    return {"format": container, "streams": streams}


class RenderFixture(unittest.TestCase):
    """A temporary artifact tree, a fake toolchain, one plan."""

    def setUp(self):
        self.checkout = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_render_"))
        self.addCleanup(_remove_tree, self.checkout)
        # The approved root stands in for playthrough/, so the parent
        # stands in for the checkout root -- which is what a concat entry
        # is spelled relative to, exactly as in production.
        self.root = os.path.join(self.checkout, "playthrough")
        self.frames = os.path.join(self.root, "frames")
        self.transitions = os.path.join(self.root, "build",
                                        "transitions")
        os.makedirs(self.frames)
        os.makedirs(self.transitions)
        self.concat = os.path.join(self.root, "build", "concat.txt")
        self.movie = os.path.join(self.root, "cata-play.mp4")
        self.timeline_path = os.path.join(self.root, "timeline.json")
        # A real executable file for verified_tool() to resolve to; _run
        # is doubled, so it is never started.  It exits non-zero on
        # purpose, so a test that somehow ran it would fail loudly.
        #
        # NOT UNDER /tmp.  verified_tool() refuses a binary reached
        # through any group- or world-writable directory, because write
        # access to a directory is the right to replace what is in it and
        # every frame of the film passes through this binary.  /tmp is
        # mode 1777, so a stub there is correctly refused -- which means
        # the fixture has to put its stubs somewhere with the same
        # ancestry a real installation has.
        self.bin = _trusted_tool_dir()
        self.addCleanup(_remove_tree, self.bin)
        self.tools = {}
        for name in (rm.FFMPEG, rm.FFPROBE):
            path = os.path.join(self.bin, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/bash\nexit 98\n")
            os.chmod(path, 0o755)
            self.tools[name] = path
        self.processes = FakeProcesses()
        self.enter(_patched(rm, _run=self.processes))
        # THE FRAMES AND TRANSITIONS DIRECTORIES HAVE TO BE CLEARED
        # HERE TOO, and leaving them out was a real failure rather than
        # an oversight worth tidying.  plan_render() resolves both
        # through make_transitions.frames_dir() and
        # make_transitions.default_transitions_dir(), and BOTH let
        # $PLAYTHROUGH_FRAMES_DIR / $PLAYTHROUGH_TRANSITIONS_DIR win
        # over the sibling-of-root derivation so that a clone-indexed
        # run and the modules agree.  env.sh exports all of them
        # pointing at the real checkout -- so after `source
        # playthrough/tooling/env.sh`, which is how every other script
        # in this pipeline is invoked, those variables outranked this
        # fixture's temporary root and the containment guard correctly
        # refused a capture directory outside it.  Fifty-four tests
        # failed for a reason that had nothing to do with what they
        # assert.  Cleared, the suite is hermetic: it passes whether or
        # not the caller sourced env.sh first, which is the only way its
        # verdict means anything.  Matches test_make_transitions.py,
        # which clears the same set for the same reason.
        self.enter(_environment(
            PLAYTHROUGH_BIN_FFMPEG=self.tools[rm.FFMPEG],
            PLAYTHROUGH_BIN_FFPROBE=self.tools[rm.FFPROBE],
            PLAYTHROUGH_CONCAT_LIST=None,
            PLAYTHROUGH_MOVIE=None,
            PLAYTHROUGH_TIMELINE=None,
            PLAYTHROUGH_SCREEN_WIDTH=None,
            PLAYTHROUGH_SCREEN_HEIGHT=None,
            PLAYTHROUGH_ENCODE_TIMEOUT=None,
            PLAYTHROUGH_PROBE_TIMEOUT=None,
            PLAYTHROUGH_FRAMES_DIR=None,
            PLAYTHROUGH_TRANSITIONS_DIR=None,
            PLAYTHROUGH_TRANSITION_FORMAT=None,
            PLAYTHROUGH_REPO_ROOT=None))

    def enter(self, manager):
        """Enter a context manager for the length of one test."""
        value = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return value

    # -- fixtures -----------------------------------------------------

    def png_bytes(self, colour=b""):
        """Return a PNG header declaring the film's own geometry.

        The renderer reads every planned image's IHDR and REFUSES one
        that is not the size the film is cut at, because the encoder's
        -s flag would otherwise rescale a bad capture silently.  So a
        stub has to carry a real header: the signature, the IHDR chunk
        length and type, and the two dimensions.  Nothing decodes these
        bytes, so the pixel data is not needed.

        `colour` appends bytes AFTER the header, which is how a test
        produces a second image of the same geometry and a DIFFERENT
        digest -- the substitution the attestation ledger exists to
        catch.
        """
        width, height = mt.expected_size()
        return (b"\x89PNG\r\n\x1a\n" +
                (13).to_bytes(4, "big") + b"IHDR" +
                width.to_bytes(4, "big") + height.to_bytes(4, "big") +
                colour)

    def capture(self, index):
        """Create one capture, SEAL IT, and return its absolute path.

        The seal is part of taking a capture, not a step a fixture may
        skip: the renderer verifies every frame it is about to pace
        against the attestation ledger, so a fixture that wrote pixels
        without attesting them would be exercising a refusal rather than
        the render.
        """
        path = os.path.join(self.frames, "frame_%05d.png" % index)
        payload = self.png_bytes()
        with open(path, "wb") as handle:
            handle.write(payload)
        manifest.append_frame_digest(
            os.path.join(self.root, *manifest.DIGESTS_REL_PARTS),
            index, "playthrough/frames/frame_%05d.png" % index,
            hashlib.sha256(payload).hexdigest(), len(payload),
            manifest.DIGEST_AT_CAPTURE,
            "2026-08-03T17:56:%02d.400Z" % (index % 60),
            root=self.root)
        return path

    def attest_frames(self, count):
        """Describe the ledger the fixture's captures were sealed into."""
        return timeline.attest_captures(
            os.path.join(self.root, *manifest.DIGESTS_REL_PARTS),
            self.root, verified=count)

    def group(self, index, count=None):
        """Create one whole transition group on disk."""
        total = mt.FRAMES_PER_GROUP if count is None else count
        paths = []
        for ordinal in range(total):
            path = os.path.join(
                self.transitions,
                mt.TRANSITION_NAME_FORMAT % (index, ordinal))
            with open(path, "wb") as handle:
                handle.write(self.png_bytes())
            paths.append(path)
        return paths

    def attribute(self, frames):
        """Publish a generation manifest for the groups on disk.

        make_transitions.py writes this INSIDE the group set, binding the
        groups to the timeline they were composed from, and the renderer
        REQUIRES it: twelve files with the right names and the right pixel
        dimensions are not evidence that they came from this session.  The
        fixture therefore produces a well-formed generation rather than a
        bare directory of PNGs, so what the tests exercise is the
        production contract.
        """
        groups = [
            mt.Group(index,
                     os.path.join(self.frames, "frame_%05d.png" % index),
                     os.path.join(self.frames,
                                  "frame_%05d.png" % (index + 1)))
            for index in sorted(frames)]
        staged = {
            group.frame: [
                os.path.join(self.transitions,
                             mt.TRANSITION_NAME_FORMAT % (group.frame,
                                                          ordinal))
                for ordinal in range(mt.FRAMES_PER_GROUP)]
            for group in groups}
        record = mt.build_generation_manifest(
            groups, self.timeline_path, mt.expected_size(),
            _FONT_PATH, staged)
        with open(mt.generation_manifest_path(self.transitions), "w",
                  encoding="utf-8") as handle:
            handle.write(mt.generation_manifest_text(record))
        return record

    def attest(self, count):
        """Write a manifest of `count` rows and describe it.

        Returns the attestation the timeline document carries: the
        repository-relative path, the sha256 of the file's exact bytes,
        and the row count.
        """
        path = os.path.join(self.root, "manifest.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for index in range(1, count + 1):
                handle.write(manifest.encode_row(manifest.build_row(
                    frame=index,
                    file="playthrough/frames/frame_%05d.png" % index,
                    real_ts="2026-08-03T17:56:%02d.400Z" % (index % 60),
                    ingame_clock="08:15:%02d" % (index % 60),
                    action="press '%d'" % (index % 10),
                    commentary="I take one step and look again.")))
        return timeline.attest_manifest(path, self.root)

    def document(self, durations, flags=(), **overrides):
        """Return a timeline document over `durations`, with cues.

        The cue windows are walked exactly as timeline.py walks them --
        each frame's window then the transition second where one is
        charged -- so the document satisfies the invariant the renderer
        re-checks rather than merely carrying plausible numbers.  A
        FLAGGED entry is given the ceiling as its duration and a raw
        delta above it, because that is the only shape a flagged entry
        can honestly have: the flag means the raw delta ran past the
        ceiling, so the clamp gave the frame exactly CEIL seconds.  The
        FINAL entry is given the floor for the same kind of reason: it
        has no successor to difference against, so its raw delta is 0.0
        and the floor is the window the clamp gives it.
        """
        flagged = set(flags)
        entries = []
        cursor = Decimal("0")
        count = len(durations)
        durations = [timeline.FLOOR if position == count
                     else timeline.CEIL if position in flagged
                     else duration
                     for position, duration
                     in enumerate(durations, start=1)]
        for position, duration in enumerate(durations, start=1):
            length = Decimal(str(duration))
            clock = "08:15:%02d" % (position % 60)
            entries.append({
                "frame": position,
                "file": "playthrough/frames/frame_%05d.png" % position,
                "real_ts": "2026-08-03T17:56:%02d.400Z" % (
                    position % 60),
                "ingame_clock": clock,
                "clock_kind": "clock",
                "clock_seconds": 8 * 3600 + 15 * 60 + position % 60,
                "reconciled": False,
                "reconciled_reason": "",
                "ingame_date": "Spring, day 61",
                "date_kind": "date",
                "date_agreement": "confirmed",
                # The final frame has no successor to difference
                # against, so timeline.py records 0.0 for it and the
                # floor gives it its window.
                "raw_delta": (0.0 if position == len(durations)
                              else 20.0 if position in flagged
                              else float(length)),
                "duration": float(length),
                "transition_after": position in flagged,
                "cue_start": float(cursor),
                "cue_end": float(cursor + length),
                "action": "press '%d'" % (position % 10),
                "commentary": "I take one step and look again.",
                # No amendment ledger in this fixture, so no entry's
                # narration came through one.  The field is not optional:
                # a derivative has to be able to say, per frame, whether
                # the text above is what the record says or what a
                # digest-bound correction says instead.
                "amended": False,
            })
            cursor += length
            if position in flagged:
                cursor += Decimal(str(timeline.TRANSITION))
        body = {
            "version": 1,
            "floor": timeline.FLOOR,
            "ceil": timeline.CEIL,
            "transition": timeline.TRANSITION,
            "frame_count": len(durations),
            "transition_count": len(flagged),
            "reconciled_count": 0,
            "date_confirmed_count": len(durations),
            "date_corrected_count": 0,
            "date_unverified_count": 0,
            "date_conflict_count": 0,
            "total_duration": float(sum(
                Decimal(str(one)) for one in durations)),
            "total_transition": float(
                len(flagged) * Decimal(str(timeline.TRANSITION))),
            "total": float(cursor),
            "final_cue_end": float(cursor),
            # THE PROVENANCE THE RENDERER REQUIRES.  A document with no
            # manifest attestation is refused outright: there would be
            # nothing to prove it was computed from the evidence on this
            # disk, which is the one failure no internal invariant can
            # see, because a stale document is perfectly self-consistent.
            # So the fixture writes the manifest its entries describe and
            # attests it, exactly as timeline.py does when it writes the
            # real document.
            "manifest": self.attest(count),
            # The ordinary case: no corrections were recorded, so there
            # is no ledger to attest.  A document that carried amended
            # narration with no attestation is refused by
            # timeline.amendment_attestation_problems().
            "amendments": None,
            # THE ORDERED SET, BOUND.  The renderer re-hashes every frame
            # it is about to pace against this ledger, so a document that
            # attested none while a ledger existed beside it -- or one
            # whose ledger no longer matches the pixels -- is refused
            # before a byte is encoded.
            "captures": self.attest_frames(len(durations)),
            "frames": entries,
        }
        body.update(overrides)
        return body

    def scene(self, durations=(0.25, 1.0, 5.0, 0.25), flags=()):
        """Create the captures, the timeline and the groups.

        The timeline FILE is written here because a group set is
        attributed to a document by that document's digest, so the
        provenance the renderer checks cannot be produced before the
        timeline exists on disk.  A test that re-writes the same document
        afterwards produces the same bytes and therefore the same digest.
        """
        for index in range(1, len(durations) + 1):
            self.capture(index)
        document = self.document(durations, flags)
        if flags:
            self.write_timeline(document)
            for index in flags:
                self.group(index)
            self.attribute(flags)
        return document

    def write_timeline(self, document):
        """Write a document to the fixture's timeline path."""
        with open(self.timeline_path, "w", encoding="utf-8") as handle:
            handle.write(timeline.encode_timeline(document))
        return self.timeline_path

    # -- running it ---------------------------------------------------

    def plan(self, document):
        """Plan a render inside the fixture's tree."""
        return rm.plan_render(document, self.root, self.timeline_path)

    def main(self, argv):
        """Run the real command line, returning (status, out, err)."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                status = rm.main(argv, root=self.root)
        return status, out.getvalue(), err.getvalue()

    def relative(self, *parts):
        """Return a committed-list entry for a path under playthrough.

        Spelled relative to the CONCAT LIST'S OWN DIRECTORY
        (playthrough/build/), because that is the base ffmpeg's concat
        demuxer resolves an entry against -- so a capture reads
        `../frames/...` and a transition frame `transitions/...`.
        """
        return os.path.relpath("/".join(parts), "build").replace(
            os.sep, "/")


class TestTheTransitionSplit(RenderFixture):
    """One second of video, divided twelve ways, exactly."""

    def test_the_ordered_durations_are_eleven_base_and_a_remainder(self):
        shares = rm.transition_durations(timeline.TRANSITION)
        self.assertEqual([rm.format_duration(one) for one in shares],
                         EXPECTED_SHARES)

    def test_the_split_sums_to_the_second_it_was_charged(self):
        shares = rm.transition_durations(timeline.TRANSITION)
        total = sum(Decimal(rm.format_duration(one)) for one in shares)
        self.assertEqual(total, Decimal("1.000000"))

    def test_the_remainder_is_charged_once_at_the_end(self):
        shares = [rm.format_duration(one)
                  for one in rm.transition_durations(1.0)]
        self.assertEqual(len(set(shares[:-1])), 1)
        self.assertGreater(Decimal(shares[-1]), Decimal(shares[0]))

    def test_the_arithmetic_is_decimal_and_not_binary(self):
        self.assertIn("from decimal import Decimal", SOURCE)
        self.assertIn("Decimal(str(number))", SOURCE)

    def test_a_split_that_divides_exactly_has_no_remainder(self):
        for count, expected in ((5, ["0.200000"] * 5),
                                (4, ["0.250000"] * 4),
                                (1, ["1.000000"])):
            shares = rm.transition_durations(1.0, count)
            self.assertEqual(
                [rm.format_duration(one) for one in shares], expected)

    def test_a_group_size_that_is_not_a_whole_number_is_refused(self):
        for count in (0, -1, 12.0, True):
            with self.assertRaises(rm.RenderError):
                rm.transition_durations(1.0, count)

    def test_a_length_that_is_not_finite_and_positive_is_refused(self):
        for seconds in (0.0, -1.0, float("nan"), float("inf"), "x"):
            with self.assertRaises(rm.RenderError):
                rm.transition_durations(seconds)

    def test_a_length_too_small_to_split_is_refused(self):
        with self.assertRaises(rm.RenderError) as caught:
            rm.transition_durations(0.000001, 12)
        self.assertIn("microsecond", str(caught.exception))

    def test_the_group_size_defaults_to_the_composer_s_own(self):
        self.assertEqual(len(rm.transition_durations(1.0)),
                         mt.FRAMES_PER_GROUP)

    def test_a_share_is_written_at_the_width_it_is_computed_at(self):
        """Microsecond width, fixed, never stripped.

        THE DEFECT THIS REPLACES.  Durations used to be stripped of
        trailing fractional zeros, so a captured frame's 0.25 s came out
        as "0.25" and the ceiling as "10.0".  ffmpeg parses those
        identically, but the committed concat list is EVIDENCE, and as
        evidence it disagreed with every other artifact describing the
        same numbers: timeline.json writes durations at three decimals and
        the acceptance gate reads the clamp bounds as 0.250 and 10.000.
        """
        self.assertEqual(rm.format_duration(0.25), "0.250000")
        self.assertEqual(rm.format_duration(10.0), "10.000000")
        self.assertEqual(rm.format_duration(100.0), "100.000000")
        self.assertEqual(rm.format_duration(0.083333), "0.083333")
        self.assertEqual(rm.format_duration(0.083337), "0.083337")

    def test_a_capture_is_written_at_millisecond_width(self):
        """The resolution timeline.py rounds a clamped duration to.

        The two widths are not decoration: the width SAYS which kind of
        duration a line carries, and each is the resolution its number
        was actually computed at.
        """
        self.assertEqual(rm.format_capture_duration(0.25), "0.250")
        self.assertEqual(rm.format_capture_duration(10.0), "10.000")
        self.assertEqual(rm.format_capture_duration(1.0), "1.000")
        self.assertEqual(rm.format_capture_duration(1.5), "1.500")
        self.assertEqual(rm.CAPTURE_DECIMALS, 3)
        self.assertEqual(rm.DURATION_DECIMALS, 6)

    def test_the_width_is_chosen_from_the_entry_kind(self):
        capture = rm.ConcatEntry(
            "/a/frame_00001.png", "../frames/frame_00001.png", 0.25,
            rm.KIND_CAPTURE, 1, rm.NO_ORDINAL)
        share = rm.ConcatEntry(
            "/a/trans_00001_00.png", "transitions/trans_00001_00.png",
            0.25, rm.KIND_TRANSITION, 1, 0)
        self.assertEqual(rm.format_entry_duration(capture), "0.250")
        self.assertEqual(rm.format_entry_duration(share), "0.250000")
        unknown = capture._replace(kind="something else")
        with self.assertRaises(rm.RenderError):
            rm.format_entry_duration(unknown)

    def test_a_duration_that_is_not_a_finite_number_is_refused(self):
        for value in ("x", None, float("nan"), float("inf"), -0.5):
            with self.assertRaises(rm.RenderError):
                rm.format_duration(value)
            with self.assertRaises(rm.RenderError):
                rm.format_capture_duration(value)


class TestPlanningTheRender(RenderFixture):
    """Every input is resolved and checked before a byte is written."""

    def test_a_plan_carries_one_entry_per_capture(self):
        plan = self.plan(self.scene())
        self.assertEqual(plan.capture_count, 4)
        self.assertEqual(plan.group_count, 0)
        self.assertEqual(len(plan.entries), 4)
        self.assertEqual([entry.kind for entry in plan.entries],
                         [rm.KIND_CAPTURE] * 4)

    def test_each_source_appears_exactly_once(self):
        plan = self.plan(self.scene(flags=(2,)))
        paths = [entry.path for entry in plan.entries]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(len(paths), 4 + mt.FRAMES_PER_GROUP)

    def test_a_group_is_interleaved_after_its_flagged_capture(self):
        plan = self.plan(self.scene(flags=(2,)))
        kinds = [entry.kind for entry in plan.entries]
        self.assertEqual(
            kinds,
            [rm.KIND_CAPTURE, rm.KIND_CAPTURE] +
            [rm.KIND_TRANSITION] * mt.FRAMES_PER_GROUP +
            [rm.KIND_CAPTURE, rm.KIND_CAPTURE])
        for entry in plan.entries:
            if entry.kind == rm.KIND_TRANSITION:
                self.assertEqual(entry.frame, 2)

    def test_the_group_ordinals_run_from_zero_in_order(self):
        plan = self.plan(self.scene((0.25, 1.0, 0.25), flags=(1,)))
        ordinals = [entry.ordinal for entry in plan.entries
                    if entry.kind == rm.KIND_TRANSITION]
        self.assertEqual(ordinals, list(range(mt.FRAMES_PER_GROUP)))

    def test_the_entries_are_spelled_relative_to_the_list(self):
        # RELATIVE TO THE LIST FILE, not to the checkout root: ffmpeg
        # resolves a concat entry against the directory the list is in,
        # so a capture is reached by climbing out of build/ and a
        # transition frame is reached from inside it.  Measured: a list
        # in playthrough/build/ carrying `playthrough/frames/...` makes
        # ffmpeg open playthrough/build/playthrough/frames/... and fail.
        plan = self.plan(self.scene((0.25, 1.0, 0.25), flags=(1,)))
        self.assertEqual(plan.entries[0].relative,
                         "../frames/frame_00001.png")
        self.assertEqual(plan.entries[1].relative,
                         "transitions/trans_00001_00.png")
        for entry in plan.entries:
            self.assertFalse(os.path.isabs(entry.relative))

    def test_the_expected_total_is_the_sum_of_the_windows(self):
        document = self.scene()
        plan = self.plan(document)
        self.assertAlmostEqual(plan.expected_total, 6.5, places=6)
        self.assertAlmostEqual(plan.declared_total, document["total"],
                               places=6)

    def test_a_transition_adds_its_second_to_the_total(self):
        # A flagged frame is clamped to the ceiling, so this is
        # 0.25 + 10.0 + 5.0 + 0.25 of frames plus one second of
        # transition.
        document = self.scene(flags=(2,))
        plan = self.plan(document)
        self.assertAlmostEqual(plan.expected_total, 16.5, places=6)
        self.assertAlmostEqual(plan.declared_total, document["total"],
                               places=6)
        self.assertEqual(plan.group_count, 1)

    def test_the_geometry_is_the_capture_geometry(self):
        plan = self.plan(self.scene())
        self.assertEqual((plan.width, plan.height),
                         (mt.FRAME_WIDTH, mt.FRAME_HEIGHT))

    def test_a_timeline_with_no_frames_is_refused(self):
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(self.document([]))
        self.assertIn("no frames", str(caught.exception))

    def test_a_missing_capture_aborts_and_is_never_skipped(self):
        """The ATTESTATION gate reaches it first, and names it.

        Skipping the frame would preserve every appearance of success and
        break the one-frame-per-keystroke invariant, so what matters is
        that the render stops and says which capture is gone.  Since the
        frames are sealed, the refusal now comes from the digest ledger
        rather than from the path check below it -- an earlier and
        stronger objection to the same defect.
        """
        document = self.scene()
        os.unlink(os.path.join(self.frames, "frame_00002.png"))
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(document)
        message = str(caught.exception)
        self.assertIn("frame_00002.png", message)
        self.assertIn("frame 2 is attested but", message)

    def test_a_substituted_capture_aborts_the_render(self):
        """THE DEFECT THIS TEST EXISTS FOR.

        A same-sized, non-blank replacement PNG at the right name passes
        the existence check, the geometry check and the count identity.
        Only the digest disagrees, so this is the one gate that stops it
        -- and it stops it before a byte is encoded, while the previous
        film and its concat list are still consistent with each other.
        """
        document = self.scene()
        path = os.path.join(self.frames, "frame_00002.png")
        with open(path, "wb") as handle:
            handle.write(self.png_bytes(colour=b"\x40\x40\x40"))
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(document)
        message = str(caught.exception)
        self.assertIn("frame 2 is attested as sha256", message)
        self.assertIn("not the bytes that were captured", message)

    def test_an_unsealed_capture_aborts_the_render(self):
        """A frame the ledger never sealed is not paced.

        A document whose ledger is short by one row describes a session
        in which one keystroke's pixels were never attested; rendering it
        would put an unverifiable frame on screen among verified ones,
        indistinguishable afterwards.
        """
        durations = (0.25, 1.0, 5.0, 0.25, 0.25)
        for index in range(1, len(durations)):
            self.capture(index)
        path = os.path.join(self.frames,
                            "frame_%05d.png" % len(durations))
        with open(path, "wb") as handle:
            handle.write(self.png_bytes())
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(self.document(durations))
        self.assertIn("frame 5 is recorded but its bytes are not "
                      "attested", str(caught.exception))

    def test_a_missing_group_is_refused(self):
        document = self.scene(flags=(2,))
        for name in os.listdir(self.transitions):
            os.unlink(os.path.join(self.transitions, name))
        with self.assertRaises(rm.RenderError):
            self.plan(document)

    def test_a_group_set_with_no_provenance_is_refused(self):
        """A NAME AND A SIZE ARE NOT EVIDENCE.

        THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE.  A group used to be
        accepted because twelve files with the right names and the right
        pixel dimensions existed -- and the same twelve names exist in
        EVERY session that flags frame 2, at the same geometry.  So a group
        composed from a different timeline was indistinguishable from the
        right one, and the film would fade between captures the survivor
        never saw in this session.
        """
        document = self.scene(flags=(2,))
        os.unlink(mt.generation_manifest_path(self.transitions))
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(document)
        message = str(caught.exception)
        self.assertIn("cannot be attributed", message)
        self.assertIn("transitions.json", message)

    def test_a_group_set_from_another_timeline_is_refused(self):
        document = self.scene(flags=(2,))
        path = mt.generation_manifest_path(self.transitions)
        record = json.loads(_read(path))
        record["timeline"]["sha256"] = "0" * 64
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(mt.generation_manifest_text(record))
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(document)
        self.assertIn("composed from a timeline whose digest",
                      str(caught.exception))

    def test_a_stale_group_for_an_unflagged_index_is_refused(self):
        """THE GLOBAL CHECK, and the reason it has to be global.

        The per-entry check could only ever inspect the indices the
        CURRENT timeline flags, so a group left behind for an index a
        recomputed timeline no longer flags was never even looked at --
        while verify_artifacts.sh, which globs the whole directory, counts
        it.
        """
        self.scene(flags=(2,))
        unflagged = self.document((0.25, 1.0, 5.0, 0.25))
        self.write_timeline(unflagged)
        # The groups on disk are still attributed to the FLAGGED document,
        # so re-attribute them to this one: the only difference left is
        # that the timeline no longer asks for them.
        self.attribute((2,))
        problems = mt.generation_manifest_problems(
            self.transitions, self.timeline_path, [])
        self.assertTrue(
            any("does not flag" in one for one in problems),
            msg=repr(problems))
        self.assertTrue(
            any("verify_artifacts.sh" in one for one in problems),
            msg="and the message says who else would count it")

    def test_a_group_frame_whose_pixels_changed_is_refused(self):
        document = self.scene(flags=(2,))
        victim = os.path.join(self.transitions, "trans_00002_00.png")
        with open(victim, "ab") as handle:
            handle.write(b"\x00")
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(document)
        self.assertIn("different pixels", str(caught.exception))

    def test_an_unflagged_timeline_needs_no_group_provenance(self):
        """There is no group set to attribute, so none is demanded.

        The directory may legitimately not exist at all in a session where
        the ceiling never engaged.
        """
        document = self.scene()
        shutil.rmtree(self.transitions, ignore_errors=True)
        plan = self.plan(document)
        self.assertEqual(plan.group_count, 0)

    def test_a_short_group_is_refused(self):
        for index in (1, 2, 3):
            self.capture(index)
        self.group(1, count=mt.FRAMES_PER_GROUP - 1)
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(self.document([0.25, 1.0, 0.25], flags=(1,)))
        self.assertIn(str(mt.FRAMES_PER_GROUP), str(caught.exception))

    def test_an_extra_frame_in_a_group_is_refused(self):
        for index in (1, 2, 3):
            self.capture(index)
        self.group(1)
        with open(os.path.join(self.transitions,
                               "trans_00001_12.png"), "wb") as handle:
            handle.write(self.png_bytes())
        with self.assertRaises(rm.RenderError):
            self.plan(self.document([0.25, 1.0, 0.25], flags=(1,)))

    def test_a_document_failing_its_own_invariant_is_refused(self):
        document = self.scene()
        document["frames"][1]["cue_end"] = 99.0
        with self.assertRaises(rm.RenderError) as caught:
            self.plan(document)
        self.assertIn("fails its own checks", str(caught.exception))

    def test_a_declared_total_that_disagrees_is_refused(self):
        document = self.scene()
        document["total"] = 99.0
        with self.assertRaises(rm.RenderError):
            self.plan(document)

    def test_a_frame_count_that_disagrees_is_refused(self):
        document = self.scene()
        document["frame_count"] = 9
        with self.assertRaises(rm.RenderError):
            self.plan(document)

    def test_a_transition_count_that_disagrees_is_refused(self):
        document = self.scene((0.25, 1.0, 0.25), flags=(1,))
        document["transition_count"] = 2
        with self.assertRaises(rm.RenderError):
            self.plan(document)

    def test_a_duration_outside_the_clamp_is_refused(self):
        for duration in (0.1, 10.5):
            document = self.scene((1.0, duration, 0.25))
            with self.assertRaises(rm.RenderError):
                self.plan(document)

    def test_a_capture_outside_the_frames_directory_is_refused(self):
        document = self.scene((0.25, 1.0, 0.25))
        document["frames"][0]["file"] = self.relative(
            "build", "transitions", "trans_00001_00.png")
        self.group(1)
        with self.assertRaises(rm.RenderError):
            self.plan(document)


class TestTheConcatList(RenderFixture):
    """The instruction sheet, line for line."""

    def test_the_list_is_a_file_and_a_duration_per_entry(self):
        plan = self.plan(self.scene((0.25, 1.0, 0.25)))
        self.assertEqual(
            rm.format_concat_list(plan).splitlines(),
            ["file '%s'" % self.relative("frames", "frame_00001.png"),
             "duration 0.250",
             "file '%s'" % self.relative("frames", "frame_00002.png"),
             "duration 1.000",
             "file '%s'" % self.relative("frames", "frame_00003.png"),
             "duration 0.250",
             # *** THE REPEATED FINAL ENTRY, with no duration after it.
             "file '%s'" % self.relative("frames", "frame_00003.png")])

    def test_a_group_contributes_its_twelve_exact_durations(self):
        plan = self.plan(self.scene((0.25, 1.0, 0.25), flags=(1,)))
        lines = rm.format_concat_list(plan).splitlines()
        self.assertEqual(
            lines[2:2 + 2 * mt.FRAMES_PER_GROUP],
            [line for ordinal, share in enumerate(EXPECTED_SHARES)
             for line in ("file '%s'" % self.relative(
                 "build", "transitions",
                 "trans_00001_%02d.png" % ordinal),
                 "duration %s" % share)])

    def test_the_group_durations_sum_to_the_charged_second(self):
        plan = self.plan(self.scene((0.25, 1.0, 0.25), flags=(1,)))
        shares = [Decimal(line.split(" ", 1)[1])
                  for entry, line in zip(
                      plan.entries,
                      rm.format_concat_list(plan).splitlines()[1::2])
                  if entry.kind == rm.KIND_TRANSITION]
        self.assertEqual(len(shares), mt.FRAMES_PER_GROUP)
        self.assertEqual(sum(shares), Decimal("1.000000"))

    def test_the_list_ends_with_a_newline_and_no_blank_line(self):
        text = rm.format_concat_list(self.plan(self.scene()))
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_the_file_lines_are_one_more_than_the_durations(self):
        plan = self.plan(self.scene(flags=(2,)))
        text = rm.format_concat_list(plan)
        files, durations = rm.concat_counts(text)
        self.assertEqual(durations, len(plan.entries))
        self.assertEqual(files, durations + 1)

    def test_dropping_the_terminal_repeat_is_caught_on_the_bytes(self):
        # THE MUTATION.  The container symptom of a missing repeat is a
        # length nobody would question in isolation, so it is caught
        # structurally instead.
        plan = self.plan(self.scene())
        text = rm.format_concat_list(plan)
        mutated = "\n".join(text.splitlines()[:-1]) + "\n"
        with self.assertRaises(rm.RenderError) as caught:
            rm.concat_counts(mutated)
        message = str(caught.exception)
        self.assertIn("one more file line", message)
        self.assertIn("truncates", message)

    def test_a_second_repeat_is_caught_too(self):
        plan = self.plan(self.scene())
        text = rm.format_concat_list(plan) + \
            "file '%s'\n" % self.relative("frames", "frame_00004.png")
        with self.assertRaises(rm.RenderError):
            rm.concat_counts(text)

    def test_a_line_that_is_neither_kind_is_refused(self):
        for line in ("# a comment", "stream", "", "outpoint 1.0"):
            with self.assertRaises(rm.RenderError):
                rm.concat_counts("file 'a.png'\nduration 1.0\n%s\n"
                                 % line)

    def test_an_empty_plan_writes_nothing(self):
        plan = self.plan(self.scene())._replace(entries=[])
        with self.assertRaises(rm.RenderError):
            rm.format_concat_list(plan)

    def test_the_committed_list_is_read_back_and_compared(self):
        plan = self.plan(self.scene())
        path, text = rm.write_concat_list(plan, self.concat, self.root)
        self.assertEqual(path, self.concat)
        self.assertEqual(_read(self.concat), text)
        self.assertEqual(text, rm.format_concat_list(plan))

    def test_the_build_directory_is_created_if_absent(self):
        plan = self.plan(self.scene())
        shutil.rmtree(os.path.dirname(self.concat))
        rm.write_concat_list(plan, self.concat, self.root)
        self.assertTrue(os.path.isfile(self.concat))

    def test_a_list_outside_the_tree_is_refused(self):
        plan = self.plan(self.scene())
        for target in ("/tmp/concat.txt",
                       os.path.join(self.checkout, "concat.txt")):
            with self.assertRaises(rm.RenderError):
                rm.write_concat_list(plan, target, self.root)

    def test_a_short_write_is_caught_by_the_read_back(self):
        plan = self.plan(self.scene())
        real_write = rm.write_text

        def truncating(path, text):
            return real_write(path, text[:-8])

        with _patched(rm, write_text=truncating):
            with self.assertRaises(rm.RenderError) as caught:
                rm.write_concat_list(plan, self.concat, self.root)
        self.assertIn("is not what was written", str(caught.exception))

    def test_the_committed_list_resolves_to_the_plan(self):
        # THERE IS NO SECOND LIST.  The committed entries are spelled
        # relative to the list's own directory, which is the base ffmpeg
        # resolves them against, so the committed artifact IS the
        # encoder's input.  Resolving it back from its own bytes must
        # reproduce the plan's paths plus the repeated final entry.
        plan = self.plan(self.scene(flags=(2,)))
        text = rm.format_concat_list(plan)
        resolved = rm.resolved_committed_entries(
            text, os.path.dirname(self.concat),
            [self.frames, self.transitions])
        expected = [entry.path for entry in plan.entries]
        self.assertEqual(resolved, expected + [expected[-1]])
        self.assertEqual(
            rm.verify_committed_list(
                text, os.path.dirname(self.concat),
                [self.frames, self.transitions], plan),
            resolved)

    def test_an_entry_the_plan_does_not_know_is_refused(self):
        plan = self.plan(self.scene())
        with self.assertRaises(rm.RenderError):
            rm.verify_committed_list(
                "file '../frames/frame_09999.png'\n",
                os.path.dirname(self.concat),
                [self.frames, self.transitions], plan)

    def test_an_unclosed_entry_is_refused(self):
        with self.assertRaises(rm.RenderError):
            rm.resolved_committed_entries(
                "file 'unterminated\n", os.path.dirname(self.concat),
                [self.frames, self.transitions])


class TestTheEncodeCommand(RenderFixture):
    """One pass, one process, one argument list -- and no filter."""

    def test_the_argument_list_is_exactly_this(self):
        self.assertEqual(
            rm.encode_command("/usr/bin/ffmpeg", "/tmp/list.txt",
                              "/tmp/out.mp4", 1920, 1080),
            ["/usr/bin/ffmpeg", "-y", "-v", "error",
             "-f", "concat", "-safe", "0", "-i", "/tmp/list.txt",
             "-fps_mode", "vfr", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-crf", "20", "-bf", "0",
             "-s", "1920x1080", "-movflags", "+faststart",
             "/tmp/out.mp4"])

    def test_there_is_no_output_frame_rate_argument(self):
        # ffmpeg aborts outright when -r accompanies a non-constant
        # -fps_mode, so this is a refusal of the encoder's own.
        command = rm.encode_command("ffmpeg", "l", "o", 1920, 1080)
        self.assertNotIn("-r", command)
        self.assertIn("-fps_mode", command)
        self.assertEqual(command[command.index("-fps_mode") + 1],
                         "vfr")

    def test_there_is_no_filter_of_any_kind(self):
        command = rm.encode_command("ffmpeg", "l", "o", 1920, 1080)
        for forbidden in ("-vf", "-filter:v", "-filter_complex", "-af",
                          "-lavfi", "subtitles", "-map"):
            self.assertNotIn(forbidden, command)

    def test_the_module_never_names_a_subtitle_filter(self):
        for forbidden in ("-vf", "subtitles=", "ass=", "hardsub"):
            self.assertNotIn(forbidden, SOURCE)

    def test_the_geometry_is_the_plan_s_own(self):
        command = rm.encode_command("ffmpeg", "l", "o", 640, 480)
        self.assertEqual(command[command.index("-s") + 1], "640x480")

    def test_the_encode_runs_from_the_render_root(self):
        plan = self.plan(self.scene())
        text = rm.format_concat_list(plan)
        rm.write_concat_list(plan, self.concat, self.root)
        staged = os.path.join(self.root, "staged.mp4")
        rm.encode(plan, text, staged, self.root)
        call = self.processes.calls[-1]
        self.assertEqual(call["cwd"], rm.render_root(self.root))
        self.assertEqual(os.path.basename(call["argv"][0]), rm.FFMPEG)
        self.assertEqual(call["argv"][-1], staged)

    def test_the_list_handed_to_ffmpeg_is_the_committed_one(self):
        # The whole point of the list-relative spelling: the artifact
        # committed as the film's input IS the input.  Anyone who checks
        # the repository out can re-run this encode from it.
        plan = self.plan(self.scene(flags=(2,)))
        text = rm.format_concat_list(plan)
        rm.write_concat_list(plan, self.concat, self.root)
        rm.encode(plan, text, os.path.join(self.root, "staged.mp4"),
                  self.root)
        argv = self.processes.calls[-1]["argv"]
        self.assertEqual(argv[argv.index("-i") + 1],
                         rm.default_concat_path(self.root))
        written = self.processes.lists[-1]
        files = [line for line in written.splitlines()
                 if line.startswith(rm.CONCAT_FILE_PREFIX)]
        durations = [line for line in written.splitlines()
                     if line.startswith(rm.CONCAT_DURATION_PREFIX)]
        self.assertEqual(len(files), len(plan.entries) + 1)
        self.assertEqual(len(durations), len(plan.entries))
        for line in files:
            self.assertFalse(line.startswith("file '/"),
                             msg="entries stay list-relative")

    def test_a_committed_list_that_lost_a_line_is_not_encoded(self):
        plan = self.plan(self.scene())
        text = rm.format_concat_list(plan)
        mutated = "\n".join(text.splitlines()[:-1]) + "\n"
        with self.assertRaises(rm.RenderError) as caught:
            rm.encode(plan, mutated,
                      os.path.join(self.root, "staged.mp4"), self.root)
        self.assertIn("not the one on disk", str(caught.exception))
        self.assertEqual(self.processes.argv_of(rm.FFMPEG), [])

    def test_an_encode_that_produced_nothing_is_refused(self):
        plan = self.plan(self.scene())
        text = rm.format_concat_list(plan)
        with _patched(rm, _run=lambda *args, **kwargs: ""):
            with self.assertRaises(rm.RenderError) as caught:
                rm.encode(plan, text,
                          os.path.join(self.root, "staged.mp4"),
                          self.root)
        self.assertIn("is not there", str(caught.exception))

    def test_the_tool_comes_from_the_environment_when_named(self):
        self.assertEqual(rm.verified_tool(rm.FFMPEG),
                         self.tools[rm.FFMPEG])

    def test_a_tool_that_is_not_executable_is_refused(self):
        os.chmod(self.tools[rm.FFMPEG], 0o644)
        with self.assertRaises(rm.RenderError) as caught:
            rm.verified_tool(rm.FFMPEG)
        self.assertIn("not an executable", str(caught.exception))

    def test_a_missing_tool_names_its_package(self):
        with _environment(PLAYTHROUGH_BIN_FFMPEG=None, PATH=""):
            with self.assertRaises(rm.RenderError) as caught:
                rm.verified_tool(rm.FFMPEG)
        self.assertIn("requirements.txt", str(caught.exception))


class TestMeasuringTheContainer(RenderFixture):
    """Evidence over assertion: the file is measured, not trusted."""

    def probe(self, path, **document):
        """Measure `path` with a chosen ffprobe answer."""
        self.processes.probe_document = default_probe(**document)
        return rm.probe_output(path, self.root)

    def movie_file(self, size=None):
        """Create a file big enough to be a plausible container."""
        with open(self.movie, "wb") as handle:
            handle.write(b"\x00" * (rm.MIN_OUTPUT_BYTES * 2
                                    if size is None else size))
        return self.movie

    def test_the_probe_command_is_exactly_this(self):
        self.assertEqual(
            rm.probe_command("/usr/bin/ffprobe", "/tmp/out.mp4"),
            ["/usr/bin/ffprobe", "-v", "error", "-count_packets",
             "-show_format", "-show_streams", "-of", "json",
             "/tmp/out.mp4"])

    def test_one_probe_answers_every_question(self):
        self.movie_file()
        self.probe(self.movie, duration="6.500000")
        self.assertEqual(len(self.processes.argv_of(rm.FFPROBE)), 1)

    def test_the_measurements_are_read_from_the_answer(self):
        self.movie_file()
        probe = self.probe(self.movie, duration="6.500000")
        self.assertAlmostEqual(probe.duration, 6.5, places=6)
        self.assertEqual(probe.video_streams, 1)
        self.assertEqual(probe.audio_streams, 0)
        self.assertEqual(probe.codec_name, rm.CODEC_NAME_H264)
        self.assertEqual((probe.width, probe.height), (1920, 1080))
        self.assertEqual(probe.size, os.path.getsize(self.movie))

    def test_a_duration_ffprobe_could_not_determine_stays_missing(self):
        # "N/A" must not become a zero that then compares against the
        # timeline as a catastrophic shortfall and hides the real cause.
        self.movie_file()
        self.processes.probe_document = default_probe()
        probe = rm.probe_output(self.movie, self.root)
        self.assertIsNone(probe.duration)
        self.processes.probe_document = default_probe(duration="N/A")
        self.assertIsNone(
            rm.probe_output(self.movie, self.root).duration)

    def test_a_variable_frame_rate_frame_count_is_tolerated(self):
        # nb_frames is "N/A" under VFR, which is not an error.
        self.movie_file()
        probe = self.probe(self.movie, duration="6.5")
        self.assertEqual(probe.video_streams, 1)

    def test_a_movie_that_is_not_there_is_refused(self):
        with self.assertRaises(rm.RenderError):
            rm.probe_output(os.path.join(self.root, "nothing.mp4"),
                            self.root)

    def test_a_container_header_is_not_a_film(self):
        self.movie_file(size=rm.MIN_OUTPUT_BYTES - 1)
        with self.assertRaises(rm.RenderError) as caught:
            self.probe(self.movie, duration="6.5")
        self.assertIn("not a film", str(caught.exception))

    def test_an_answer_that_is_not_json_is_refused(self):
        self.movie_file()
        self.processes.probe_text = "not json at all"
        with self.assertRaises(rm.RenderError) as caught:
            rm.probe_output(self.movie, self.root)
        self.assertIn("did not return JSON", str(caught.exception))

    def test_a_clean_container_reports_no_problems(self):
        plan = self.plan(self.scene())
        self.movie_file()
        # One coded picture per entry, plus the repeated final
        # entry the demuxer also emits.
        probe = self.probe(self.movie, duration="6.500000",
                           packets=len(plan.entries) + 1)
        self.assertEqual(rm.verify_problems(plan, probe), [])

    def test_a_short_container_is_reported_with_both_numbers(self):
        plan = self.plan(self.scene())
        self.movie_file()
        # One coded picture per entry, plus the repeated final
        # entry the demuxer also emits.
        probe = self.probe(self.movie, duration="6.250000",
                           packets=len(plan.entries) + 1)
        problems = rm.verify_problems(plan, probe)
        self.assertEqual(len(problems), 1)
        self.assertIn("6.250", problems[0])
        self.assertIn("6.500", problems[0])
        self.assertIn("repeated final entry", problems[0])

    def test_a_container_within_tolerance_passes(self):
        plan = self.plan(self.scene())
        self.movie_file()
        # One coded picture per entry, plus the repeated final
        # entry the demuxer also emits.
        probe = self.probe(self.movie, duration="6.55",
                           packets=len(plan.entries) + 1)
        self.assertEqual(rm.verify_problems(plan, probe), [])

    def test_a_second_video_stream_is_reported(self):
        plan = self.plan(self.scene())
        self.movie_file()
        probe = self.probe(self.movie, duration="6.5", video=2)
        self.assertTrue(any("video stream" in one
                            for one in rm.verify_problems(plan, probe)))

    def test_an_audio_stream_is_reported(self):
        plan = self.plan(self.scene())
        self.movie_file()
        probe = self.probe(self.movie, duration="6.5", audio=1)
        self.assertTrue(any("audio stream" in one
                            for one in rm.verify_problems(plan, probe)))

    def test_another_codec_is_reported(self):
        plan = self.plan(self.scene())
        self.movie_file()
        probe = self.probe(self.movie, duration="6.5", codec="vp9")
        self.assertTrue(any("codec" in one
                            for one in rm.verify_problems(plan, probe)))

    def test_a_rescaled_picture_is_reported(self):
        plan = self.plan(self.scene())
        self.movie_file()
        probe = self.probe(self.movie, duration="6.5",
                           width=1280, height=720)
        problems = rm.verify_problems(plan, probe)
        self.assertTrue(any("rescaled" in one for one in problems))

    def test_an_unknown_duration_is_reported_and_stops_there(self):
        plan = self.plan(self.scene())
        self.movie_file()
        self.processes.probe_document = default_probe()
        probe = rm.probe_output(self.movie, self.root)
        problems = rm.verify_problems(plan, probe)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not determine", problems[0])


class TestStagingAndPublication(RenderFixture):
    """The canonical movie changes once, at the end, and only if sound."""

    def test_the_staging_name_is_a_hidden_sibling(self):
        staged = rm.staging_path(self.movie)
        self.assertEqual(os.path.dirname(staged),
                         os.path.dirname(self.movie))
        self.assertTrue(os.path.basename(staged).startswith("."))
        self.assertTrue(staged.endswith(rm.MOVIE_SUFFIX))

    def test_an_abandoned_staging_encode_is_swept(self):
        staged = rm.staging_path(self.movie)
        with open(staged, "wb") as handle:
            handle.write(b"an earlier run was stopped")
        self.assertEqual(rm.clear_stale_staging(self.movie), [staged])
        self.assertFalse(os.path.exists(staged))

    def test_publication_is_a_rename_inside_one_directory(self):
        staged = rm.staging_path(self.movie)
        with open(staged, "wb") as handle:
            handle.write(b"the film")
        self.assertEqual(rm.publish(staged, self.movie),
                         self.movie)
        self.assertEqual(_read(self.movie, "rb"), b"the film")
        self.assertFalse(os.path.exists(staged))

    def test_a_discarded_staging_file_leaves_no_trace(self):
        staged = rm.staging_path(self.movie)
        with open(staged, "wb") as handle:
            handle.write(b"rejected")
        rm.clear_stale_staging(self.movie)
        self.assertFalse(os.path.exists(staged))
        rm.clear_stale_staging(self.movie)

    def test_the_list_is_staged_in_its_own_target_directory(self):
        """LOAD-BEARING, not tidiness.

        Every `file` entry is spelled relative to the LIST's directory,
        because that is what ffmpeg's concat demuxer resolves it against.
        Staged anywhere else, those entries would resolve somewhere else
        or not at all -- so the encoder would have to be handed a
        different list from the one committed, which is the defect this
        module already fixed once.
        """
        plan = self.plan(self.scene())
        target, staging, text = rm.stage_concat_list(
            plan, self.concat, self.root)
        self.addCleanup(lambda: os.path.exists(staging) and
                        os.unlink(staging))
        self.assertEqual(target, self.concat)
        self.assertEqual(os.path.dirname(staging),
                         os.path.dirname(self.concat))
        self.assertTrue(rm.is_staging_name(os.path.basename(staging)))
        self.assertEqual(_read(staging), text)
        self.assertFalse(
            os.path.exists(self.concat),
            msg="staging publishes nothing on its own")

    def test_a_staged_list_a_killed_run_left_behind_is_swept(self):
        plan = self.plan(self.scene())
        _, staging, _ = rm.stage_concat_list(plan, self.concat, self.root)
        self.assertEqual(rm.clear_stale_staging(self.concat), [staging])
        self.assertFalse(os.path.exists(staging))

    def test_publishing_the_list_is_a_rename(self):
        plan = self.plan(self.scene())
        target, staging, text = rm.stage_concat_list(
            plan, self.concat, self.root)
        self.assertEqual(rm.publish_concat_list(staging, target), target)
        self.assertEqual(_read(target), text)
        self.assertFalse(os.path.exists(staging))

    def test_the_manifest_lives_beside_the_list_it_describes(self):
        self.assertEqual(
            rm.generation_manifest_path(self.root),
            os.path.join(self.root, "build", "movie.json"),
            msg=("under the APPROVED root, not the render root -- the two "
                 "are one directory apart and confusing them puts the "
                 "manifest outside the committed tree"))


class TestTheTrustGate(RenderFixture):
    """Finding 5: the film is committed, so the encode is gated.

    An end-of-life release leaves the ImageMagick, ffmpeg and Xorg/Xvfb
    packages that photograph, decode and encode every frame without
    further security fixes, and the platform waiver used not to force the
    diagnostic trust state -- so capture and mux stayed "eligible as
    trusted production evidence".  The waiver is a registered bypass now,
    and this module refuses the encode under it.

    THE ANSWER COMES FROM env.sh.  Reading an exported
    PLAYTHROUGH_TRUST_STATE would be a control a caller defeats by
    exporting the word "trusted", and recomputing it here would put a
    second, drifting implementation of it in the tree.
    """

    def publishable(self, script=True):
        """Make the fixture's checkout look like a git working tree."""
        os.makedirs(os.path.join(self.checkout, ".git"))
        tooling = os.path.join(self.checkout, "playthrough", "tooling")
        if not os.path.isdir(tooling):
            os.makedirs(tooling)
        target = os.path.join(tooling, "env.sh")
        if script:
            shutil.copyfile(
                os.path.join(os.path.dirname(os.path.abspath(rm.__file__)),
                             "env.sh"),
                target)
        return target

    def stub_env(self, body):
        """Install a stand-in env.sh with a chosen verdict."""
        target = self.publishable(script=False)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(body)
        return target

    def test_a_temporary_root_is_not_gated(self):
        """It cannot be committed, so it is not evidence.

        Which is what every other test in this suite relies on, and the
        reason the discriminator is a property of the tree rather than a
        claim a caller makes.
        """
        self.assertIsNone(rm._publishable_root(self.root))
        self.assertIsNone(rm.assert_trusted_render(self.root))

    def test_a_git_working_tree_is_gated(self):
        self.stub_env(
            'playthrough_check_platform() { return 0; }\n'
            'playthrough_assert_trusted() { return 0; }\n')
        self.assertEqual(rm._publishable_root(self.root), self.checkout)
        self.assertEqual(rm.assert_trusted_render(self.root),
                         self.checkout)

    def test_a_diagnostic_trust_state_refuses_the_encode(self):
        self.stub_env(
            'playthrough_check_platform() { return 0; }\n'
            'playthrough_assert_trusted() {\n'
            '    echo "FATAL: refusing $1 while the trust state is '
            'diagnostic (PLAYTHROUGH_ALLOW_EOL_PLATFORM)" >&2\n'
            '    return 1\n'
            '}\n')
        with self.assertRaises(rm.RenderError) as caught:
            rm.assert_trusted_render(self.root)
        message = str(caught.exception)
        self.assertIn("REFUSING to encode the film", message)
        self.assertIn("trust state is diagnostic", message)
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM", message)
        self.assertIn(rm.TRUST_CONTEXT, message)

    def test_an_out_of_support_platform_refuses_the_encode(self):
        """Two questions, and neither implies the other.

        An unwaived end-of-life host is "trusted" until something calls
        the platform check, so the delegate asks both -- in
        embed_captions.sh's own order.
        """
        self.stub_env(
            'playthrough_check_platform() {\n'
            '    echo "FATAL: refusing to run because it reached end of '
            'life" >&2\n'
            '    return 1\n'
            '}\n'
            'playthrough_assert_trusted() { return 0; }\n')
        with self.assertRaises(rm.RenderError) as caught:
            rm.assert_trusted_render(self.root)
        message = str(caught.exception)
        self.assertIn("REFUSING to encode the film on this platform",
                      message)
        self.assertIn("end of life", message)

    def test_a_missing_env_sh_is_a_refusal_not_a_skip(self):
        self.publishable(script=False)
        with self.assertRaises(rm.RenderError) as caught:
            rm.assert_trusted_render(self.root)
        message = str(caught.exception)
        self.assertIn("playthrough/tooling/env.sh", message)
        self.assertIn("not skipped", message)

    def test_an_unsourceable_env_sh_is_a_refusal(self):
        # `return`, not `exit`: a sourced file that exits takes the whole
        # subshell with it, which is a different branch.  A non-zero
        # RETURN is what a real env.sh refusal looks like.
        self.stub_env(
            'echo "this file cannot be sourced" >&2\nreturn 3\n')
        with self.assertRaises(rm.RenderError) as caught:
            rm.assert_trusted_render(self.root)
        self.assertIn("could not be sourced", str(caught.exception))

    def test_the_delegate_asks_the_platform_first(self):
        """The program text is the contract, so it is asserted."""
        self.assertLess(
            rm.TRUST_PROGRAM.index("playthrough_check_platform"),
            rm.TRUST_PROGRAM.index("playthrough_assert_trusted"))
        self.assertIn('. "$1"', rm.TRUST_PROGRAM)
        self.assertNotIn("PLAYTHROUGH_TRUST_STATE", rm.TRUST_PROGRAM)

    def test_the_module_never_reads_the_trust_state_variable(self):
        """A control defeated by exporting a word is not a control.

        The names may be MENTIONED -- the comments explain the delegation
        -- but no line may both name one and consult the environment.
        """
        with open(os.path.abspath(rm.__file__), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        offenders = [
            number for number, line in enumerate(lines, start=1)
            if "PLAYTHROUGH_TRUST" in line and
            ("environ" in line or "getenv" in line)]
        self.assertEqual(
            offenders, [],
            msg="the trust state is asked for, never read")

    def test_the_gate_precedes_the_lock_and_the_plan(self):
        """Refused before a byte is encoded, and before the lock."""
        with open(os.path.abspath(rm.__file__), encoding="utf-8") as fh:
            source = fh.read()
        gate = source.index("assert_trusted_render(root)\n"
                            "        with ArtifactLock")
        self.assertGreater(gate, 0)


class TestTheCommandLine(RenderFixture):
    """The status run_pipeline.sh reads, and what it leaves behind."""

    def setUp(self):
        super(TestTheCommandLine, self).setUp()
        self.arguments = ["--timeline", self.timeline_path,
                          "--concat-list", self.concat,
                          "--output", self.movie]

    def prepare(self, durations=(0.25, 1.0, 5.0, 0.25), flags=(),
                duration="6.500000"):
        """Seed a timeline and the probe answer for it."""
        document = self.scene(durations, flags)
        self.write_timeline(document)
        self.processes.probe_document = default_probe(
            duration=duration)
        return document

    def test_concat_only_writes_the_list_and_no_movie(self):
        self.prepare()
        status, out, err = self.main(self.arguments + ["--concat-only"])
        self.assertEqual(status, rm.EXIT_OK)
        self.assertTrue(os.path.isfile(self.concat))
        self.assertFalse(os.path.exists(self.movie))
        self.assertEqual(self.processes.calls, [])
        self.assertIn("concat", out)

    def test_a_whole_run_publishes_the_movie_and_reports_both(self):
        self.prepare()
        status, out, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_OK, msg=err)
        self.assertTrue(os.path.isfile(self.movie))
        self.assertIn("6.500", out)
        self.assertEqual(len(self.processes.argv_of(rm.FFMPEG)), 1)
        self.assertEqual(len(self.processes.argv_of(rm.FFPROBE)), 1)

    def test_the_published_movie_is_the_encode_that_was_measured(self):
        self.prepare()
        self.main(self.arguments)
        self.assertEqual(os.path.getsize(self.movie),
                         self.processes.encode_bytes)
        self.assertEqual(rm.clear_stale_staging(self.movie), [])

    def test_a_container_that_does_not_match_is_not_published(self):
        self.prepare(duration="4.000000")
        with open(self.movie, "wb") as handle:
            handle.write(b"the previous film")
        status, out, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertEqual(_read(self.movie, "rb"), b"the previous film")
        self.assertIn("problem(s) found", err)
        self.assertEqual(rm.clear_stale_staging(self.movie), [])

    def test_a_failed_render_publishes_NEITHER_file(self):
        """THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE.

        The concat list used to be written and published BEFORE the lock
        was taken and before a byte was encoded, so a failed or
        interrupted encode left a NEW list beside an OLD movie -- each
        file internally valid, the list describing a film that was never
        made, and nothing on disk recording that they disagreed.
        `ffprobe` on the movie and a read of the list then gave two
        different answers about the same session, both looking
        authoritative.
        """
        self.prepare(duration="4.000000")
        with open(self.concat, "w", encoding="utf-8") as handle:
            handle.write("file 'the previous list'\n")
        with open(self.movie, "wb") as handle:
            handle.write(b"the previous film")
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertEqual(_read(self.concat), "file 'the previous list'\n")
        self.assertEqual(_read(self.movie, "rb"), b"the previous film")
        self.assertIn("NEITHER", err)
        self.assertEqual(rm.clear_stale_staging(self.movie), [])
        self.assertEqual(rm.clear_stale_staging(self.concat), [])
        self.assertFalse(
            os.path.exists(rm.generation_manifest_path(self.root)),
            msg="and no manifest attests to a film that was not made")
        self.assertFalse(
            os.path.exists(timeline.generation_journal_path(
                rm.LOCK_NAME, self.root)),
            msg="nor a journal, because no switch was attempted")

    def test_the_encoder_is_handed_the_staged_list(self):
        """So the encoder's bytes and the committed bytes are one file.

        The staged list sits in the published list's own directory, so
        every entry resolves identically, and the publish step MOVES those
        bytes rather than rewriting them.  That is what lets the encode
        happen before the list is published without the two ever
        disagreeing.
        """
        self.prepare()
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_OK, msg=err)
        argv = self.processes.argv_of(rm.FFMPEG)[0]
        handed = argv[argv.index("-i") + 1]
        self.assertTrue(
            rm.is_staging_name(os.path.basename(handed)),
            msg="the encoder read the staged list: %r" % handed)
        self.assertEqual(os.path.dirname(handed),
                         os.path.dirname(self.concat))
        self.assertFalse(os.path.exists(handed),
                         msg="which was then renamed into place")

    def test_a_successful_render_publishes_one_attested_generation(self):
        self.prepare(duration="16.500000", flags=(2,))
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_OK, msg=err)
        record = json.loads(
            _read(rm.generation_manifest_path(self.root)))
        self.assertEqual(record["version"], timeline.GENERATION_VERSION)
        self.assertEqual(record["stage"], rm.LOCK_NAME)
        self.assertEqual(record["concat_list"]["sha256"],
                         timeline.file_digest(self.concat))
        self.assertEqual(record["movie"]["sha256"],
                         timeline.file_digest(self.movie))
        self.assertEqual(record["timeline"]["sha256"],
                         timeline.file_digest(self.timeline_path))
        self.assertEqual(record["group_count"], 1)
        self.assertEqual(record["capture_count"], 4)
        self.assertFalse(
            os.path.exists(timeline.generation_journal_path(
                rm.LOCK_NAME, self.root)),
            msg="the journal is cleared once both files are verified")

    def test_the_manifest_carries_no_host_detail_and_no_timestamp(self):
        self.prepare()
        self.main(self.arguments)
        text = _read(rm.generation_manifest_path(self.root))
        self.assertNotIn(self.checkout, text)
        self.assertNotIn("/tmp", text)
        record = json.loads(text)
        for section in ("timeline", "concat_list", "movie"):
            self.assertFalse(
                os.path.isabs(record[section]["path"]),
                msg="%s is repository-relative" % section)
        self.assertNotIn("timestamp", record)
        # Deterministic: a second run over the same timeline produces the
        # same bytes, so a committed tree does not churn on every render.
        self.main(self.arguments)
        self.assertEqual(
            _read(rm.generation_manifest_path(self.root)), text)

    def test_an_interrupted_previous_publication_is_reported(self):
        self.prepare()
        timeline.write_generation_journal(rm.LOCK_NAME, {
            "version": timeline.GENERATION_VERSION,
            "stage": rm.LOCK_NAME,
            "targets": [{"path": os.path.abspath(self.movie),
                         "sha256": "0" * 64}],
        }, self.root)
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_OK, msg=err)
        self.assertIn("interrupted", err)
        self.assertFalse(
            os.path.exists(timeline.generation_journal_path(
                rm.LOCK_NAME, self.root)),
            msg="and this run repaired it by republishing both")

    def test_a_failed_encode_leaves_the_previous_film(self):
        self.prepare()
        with open(self.movie, "wb") as handle:
            handle.write(b"the previous film")
        self.processes.encode_status = 1
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertEqual(_read(self.movie, "rb"), b"the previous film")
        self.assertEqual(rm.clear_stale_staging(self.movie), [])

    def test_a_missing_capture_exits_one_before_encoding(self):
        self.prepare()
        os.unlink(os.path.join(self.frames, "frame_00002.png"))
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertIn("render_movie.py:", err)
        self.assertEqual(self.processes.calls, [])
        self.assertFalse(os.path.exists(self.movie))

    def test_a_missing_timeline_exits_one(self):
        status, _, err = self.main(self.arguments)
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertIn("render_movie.py:", err)

    def test_an_output_outside_the_tree_exits_one(self):
        self.prepare()
        status, _, err = self.main(
            ["--timeline", self.timeline_path,
             "--concat-list", self.concat,
             "--output", "/tmp/cata-play.mp4"])
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertFalse(os.path.exists("/tmp/cata-play.mp4"))

    def test_an_output_that_is_not_an_mp4_exits_one(self):
        self.prepare()
        status, _, _ = self.main(
            ["--timeline", self.timeline_path,
             "--concat-list", self.concat,
             "--output", os.path.join(self.root, "cata-play.mkv")])
        self.assertEqual(status, rm.EXIT_FAILED)

    def test_quiet_prints_nothing_on_success(self):
        self.prepare()
        status, out, _ = self.main(self.arguments + ["-q"])
        self.assertEqual(status, rm.EXIT_OK)
        self.assertEqual(out, "")

    def test_a_failure_prints_the_numbers_even_when_quiet(self):
        self.prepare(duration="4.000000")
        status, out, err = self.main(self.arguments + ["-q"])
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertIn("4.000", out)
        self.assertIn("6.500", out)

    def test_a_negative_tolerance_is_refused(self):
        self.prepare()
        status, _, err = self.main(
            self.arguments + ["--tolerance", "-1"])
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertIn("non-negative", err)

    def test_a_tolerance_past_the_ceiling_is_refused(self):
        # HARD-CAPPED, not advised against.  The duration comparison is
        # the only check that can catch a truncated container -- every
        # count still matches and only the length is wrong -- so a
        # caller must not be able to widen it until it cannot fail.
        self.prepare()
        status, _, err = self.main(
            self.arguments + ["--tolerance", "5"])
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertIn("REFUSED", err)
        self.assertIn("ceiling", err)

    def test_the_timeline_is_read_through_the_siblings_reader(self):
        self.prepare()
        status, _, err = self.main(
            ["--timeline", "/etc/hostname",
             "--concat-list", self.concat, "--output", self.movie])
        self.assertEqual(status, rm.EXIT_FAILED)
        self.assertIn("render_movie.py:", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
