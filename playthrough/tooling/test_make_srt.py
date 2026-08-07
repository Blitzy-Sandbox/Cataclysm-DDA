#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/make_srt.py.

    python3 -B playthrough/tooling/test_make_srt.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

The first form is an acceptance gate in its own right, which is why
unittest.main() is wired up at the bottom.  The -B on the second is not
decoration: the discovery loader compiles the modules it imports, and
.gitignore's terminal `!/playthrough/**` negation -- the one that makes
the save data trackable at all -- re-includes any __pycache__ that lands
under playthrough/tooling/.  env.sh exports PYTHONDONTWRITEBYTECODE=1
for the pipeline; -B is the same thing for a hand-run.

WHY THIS MODULE IS WORTH A SUITE
make_srt.py writes the two artifacts a reader is most likely to trust
without checking: a caption track that a player shows over the picture,
and a transcript that reads as the record of what happened.  Both are
generated, both look plausible when they are wrong, and the way they go
wrong is arithmetic that drifts -- captions that are correct at the
start of the film and further out of step with every transition after
it.  So the properties asserted here are the ones that cannot be seen
by looking at the output: that the cue times were READ rather than
walked, that the two files agree number for number, and that the three
counts which prove one keystroke made one capture made one cue are one
number and not three.

WHAT IS ASSERTED, AND WHY THESE PROPERTIES
Eight areas.

* THE INPUT CONTRACT -- the document form and the bare-array form are
  both accepted, and every shape that would make a dishonest
  transcript is refused with the whole list of reasons rather than the
  first: an index out of step with its position, a window that closes
  before it opens, overlapping windows, a film that does not start at
  zero, a window that does not last its frame's on-screen seconds, a
  gap nothing was charged for, a charged transition with no gap after
  it, and a missing sentence.  A hole in the record is reported as a
  hole, never filled in.

* THE SUBRIP CONTRACT, literally -- one cue per captured frame,
  sequence numbers from 1, a timing line matching
  HH:MM:SS,mmm --> HH:MM:SS,mmm with a COMMA and single spaces, at
  most two plain short lines of text, a blank line between cues, one
  trailing newline, no styling and no byte-order mark.  Sibling
  validation asserts these properties of the file, so they are held
  here at the point they are produced.

* THE MARKDOWN CONTRACT, just as literally -- every entry anchored at
  column one, EXACTLY ONE timestamp-shaped string per entry and none
  anywhere else (the pattern accepts a full stop as well as a comma,
  so the test uses the same one), a header that carries neither, a
  uniform shape with nothing invented between entries, and no
  machine-readable block appended.

* THE OUT-OF-CHARACTER GATE -- every word the module GENERATES is held
  to the same vocabulary gate the artifact is grepped with downstream,
  and the survivor's own words are asserted to come through verbatim.
  One test reads every hit of that gate in a rendered transcript and
  requires each to belong to a sentence the session wrote, which is
  what stops a future edit to a header or a label from being what
  fails a gate nobody was looking at.

* THE TWO FILES AGREE -- the Nth timestamp in the Markdown is the same
  characters as the Nth cue's start in the SubRip file, for every N.
  That single assertion is what the one-pass design exists to make
  true, and it would fail immediately if either output were ever
  derived from the other or from a second walk of the timeline.

* THE CAPTION IS THE ONLY THING TRANSFORMED -- a sentence too long for
  two short lines is shortened in the CAPTION at a word boundary, and
  the Markdown still carries the whole of it.  No word is ever broken
  through, which is asserted against a word longer than the line.

* THE FILE CONTRACT AND THE EXIT STATUS -- both artifacts appear in one
  run, twice over identical bytes, and neither appears at all after a
  --dry-run or a refusal.  A run_pipeline.sh stage reads nothing but
  the exit status, so an exit status that is wrong is a whole stage
  that appears to have worked.  Paths outside the artifact tree,
  symlinked targets and one path standing in for both are refused.

* THE MODULE'S OWN PROMISES, structurally -- there is one
  implementation of the timecode and it is timeline.py's, there is no
  cursor walk and no transition constant in this module, and nothing
  outside the standard library and the sibling timeline module is
  imported.  A promise a test cannot see is a promise that quietly
  stops being true, so these are read off the source with ast rather
  than trusted.

NO REAL ARTIFACT IS EVER WRITTEN.  Nothing here touches
playthrough/transcript.srt, playthrough/transcript.md,
playthrough/manifest.jsonl or playthrough/timeline.json: those are the
delivered record of a captured session, and a suite that wrote to the
record it exists to protect would be worse than no suite at all.  The
pure functions are exercised in memory; every test that needs files on
disk works in a temporary directory it creates, passes in as the
approved root, and removes again, with all three of
PLAYTHROUGH_TIMELINE, PLAYTHROUGH_TRANSCRIPT_SRT and
PLAYTHROUGH_TRANSCRIPT_MD redirected there for its duration and
restored afterwards -- and one test asserts the real artifacts were
untouched by the run, as the belt to that braces.  Run this suite with
env.sh sourced and without it; both must be green.

Standard library only, plus the sibling modules under test -- nothing
from playthrough/tooling/requirements.txt -- so the contracts are
auditable on a bare interpreter in any checkout without provisioning a
render toolchain first.  Nothing is added to tests/ either, because
tests/CMakeLists.txt globs tests/*.cpp into the Catch2 C++ binary.
"""

import ast
import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

# Before the sibling imports, for the reason in the module docstring: a
# stray .pyc under playthrough/tooling/ is re-included by .gitignore's
# terminal negation and would be committable.
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import make_srt                                        # noqa: E402
import manifest                                        # noqa: E402
import timeline                                        # noqa: E402


# The reference sequence of the specification -- a zero-delta menu
# keystroke, a one-second step, a five-second step, a five-minute wait
# that engages the ceiling, a night's sleep that engages it again, and a
# crossing of midnight -- with the date evidence that makes the crossing
# a crossing rather than a misread.  Its numbers are the ones quoted in
# the plan: 32.500 s of frames plus 2.000 s of transitions is 34.500 s,
# and the cue after the first transition starts at 17.250 s.
REFERENCE_CLOCKS = ("08:15:32", "08:15:32", "08:15:33", "08:15:38",
                    "08:20:38", "23:59:58", "00:00:04")
REFERENCE_DATES = ("Spring, day 1",) * 6 + ("Spring, day 2",)
REFERENCE_TOTAL = 34.5
FIRST_CUE_AFTER_A_TRANSITION = "00:00:17,250"

# Seven sentences in the survivor's voice, one per reading.  Short
# enough to caption whole, so that a test about wrapping is the only
# test that exercises wrapping.  Deliberately free of the vocabulary
# the transcript gate greps for, so that a hit in a rendered transcript
# is always something the module added.
REFERENCE_WORDS = (
    "I came to on a stranger's floor.",
    "I hold still and listen before I move.",
    "I check the watch my father wore.",
    "I take the boarded window, not the door.",
    "I sit against the radiator until my hands stop shaking.",
    "I lie down while the light is gone.",
    "I wake stiff and hungry, and glad to wake at all.",
)

# One sentence longer than two lines of the cue geometry, for the tests
# that hold the caption's shortening against the Markdown's fidelity.
A_LONG_SENTENCE = (
    "I keep the boarded window between me and the street because the "
    "last time I trusted a door in this town it opened onto something "
    "that used to be a neighbour of mine.")

FIXED_REAL_TS = "2026-01-01T00:00:00.000+0000"

# The SubRip timing line, anchored at both ends.  Spelled out here
# rather than imported, on purpose: a test that reused the module's own
# pattern would pass with that pattern wrong.
TIMING_LINE_RE = re.compile(
    r"^[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}"
    r" --> [0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}$")

# The three patterns a sibling greps the artifacts with, spelled as the
# specification spells them, for the same reason.
MARKDOWN_ENTRY_RE = re.compile(
    r"(?m)^\*\*[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}\*\*")
MARKDOWN_STAMP_RE = re.compile(
    r"([0-9]{2}):([0-9]{2}):([0-9]{2})[,.]([0-9]{3})")
# The out-of-character gate, spelled here as the SPECIFICATION spells it
# rather than imported, for the same reason as the two above: a test that
# reused the module's own table would pass with that table wrong.  These
# are the meta senses -- "engine" but not "engineer", a numbered frame but
# not the frame of a door -- because that precision is what let the gate
# become a refusal instead of an advisory.
META_GATE_RE = re.compile(
    r"\bgames?\b|\bengines?\b|\bsource[- ]files?\b|\bpath-?finding\b|"
    r"\bdebug\w*\b|\bcheat(?:s|ed|ing)?\b|\bside-?bars?\b|"
    r"\bmoves?[- ]counter\b|\btile-?sets?\b|\bframes?[ _-]?\d+\b|"
    r"\bscreen-?shots?\b|\bcaptur\w+\b|\bocr\b|\btesseract\b|"
    r"\bffmpeg\b|\bmoviepy\b|\bmp4\b|\bmanifests?\b|\btimelines?\b|"
    r"\bkey-?strokes?\b|\bxdotool\b|\bpipelines?\b|"
    r"\bcommit(?:s|ted|ting)?\b|\bgit\b|\brepositor(?:y|ies)\b|"
    r"\boptions?\.json\b|\bR1[0-3]\b|\bR[1-9]\b", re.IGNORECASE)
STYLING_RE = re.compile(r"\{\\an|<font|<i>|<b>|</i>|</b>")

# The artifact paths a test redirects.  All three, not two: a class that
# redirected only the outputs would still resolve the timeline from
# whatever env.sh exported, land outside the temporary root it
# nominated, and be refused by the containment guard -- a failure with
# nothing to do with the code under test, and one that arrives only for
# whoever sourced the pipeline's own environment first.
REDIRECTED = ("PLAYTHROUGH_TIMELINE", "PLAYTHROUGH_TRANSCRIPT_SRT",
              "PLAYTHROUGH_TRANSCRIPT_MD")


# ---------------------------------------------------------------------
# Helpers.  Deliberately tiny and deliberately pure: they build inputs
# in memory and read nothing from the environment, so every test that
# uses them is reproducible on any machine.
# ---------------------------------------------------------------------


def make_rows(clocks=REFERENCE_CLOCKS, words=REFERENCE_WORDS):
    """Return one manifest-shaped row per reading, indexed from 1."""
    return [{"frame": index,
             "file": "frames/frame_%05d.png" % index,
             "real_ts": FIXED_REAL_TS,
             "ingame_clock": clock,
             "action": "step",
             "commentary": word}
            for index, (clock, word)
            in enumerate(zip(clocks, words), start=1)]


def build(clocks=REFERENCE_CLOCKS, words=REFERENCE_WORDS,
          dates=REFERENCE_DATES):
    """Return a real timeline document for the given readings.

    Built by timeline.py rather than written out by hand, so the input
    to every test is the artifact the pipeline actually produces and
    not a fixture that has drifted from it.
    """
    return timeline.build_timeline(
        make_rows(clocks, words), dates=list(dates))


def minimal(**changes):
    """Return a two-frame BARE ARRAY, with the last entry altered.

    The defensive input form: entries in memory with no document around
    them.  Small enough that a test naming one defect introduces
    exactly that defect.
    """
    entries = [
        {"frame": 1, "cue_start": 0.0, "cue_end": 0.25,
         "duration": 0.25, "transition_after": False,
         "action": "step", "commentary": "I open my eyes."},
        {"frame": 2, "cue_start": 0.25, "cue_end": 1.25,
         "duration": 1.0, "transition_after": False,
         "action": "step", "commentary": "I get to my feet."},
    ]
    entries[-1].update(changes)
    return entries


def blocks_of(srt):
    """Return one list of lines per cue of a SubRip body."""
    return [block.split("\n")
            for block in srt.rstrip("\n").split("\n\n")]


def cue_starts(srt):
    """Return every cue's start timecode, in order."""
    return [lines[1].split(" --> ")[0] for lines in blocks_of(srt)]


def markdown_stamps(markdown):
    """Return every timestamp-shaped string, in order, as written."""
    return ["%s:%s:%s,%s" % groups
            for groups in MARKDOWN_STAMP_RE.findall(markdown)]


def seconds_of(timecode):
    """Return a SubRip timecode as a float number of seconds."""
    clock, milliseconds = timecode.split(",")
    hours, minutes, whole = (int(part) for part in clock.split(":"))
    return (hours * 3600 + minutes * 60 + whole +
            int(milliseconds) / 1000.0)


def read_bytes(path):
    """Return a file's bytes, exactly as they were written."""
    with open(path, "rb") as handle:
        return handle.read()


@contextlib.contextmanager
def workspace():
    """Yield a temporary root with all three artifact paths redirected.

    The directory is created, nominated as the approved root by the
    caller, and removed again; the variables are restored afterwards
    because they are the pipeline's own artifact layout, and a test that
    left one pointing at a temporary directory would silently redirect
    every test after it.
    """
    root = os.path.realpath(tempfile.mkdtemp(prefix="cata_make_srt_"))
    values = {
        "PLAYTHROUGH_TIMELINE": os.path.join(root, "timeline.json"),
        "PLAYTHROUGH_TRANSCRIPT_SRT": os.path.join(root,
                                                   "transcript.srt"),
        "PLAYTHROUGH_TRANSCRIPT_MD": os.path.join(root,
                                                  "transcript.md"),
    }
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield root
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(root, ignore_errors=True)


def seed_timeline(root, document=None):
    """Write a timeline AND the manifest it attests to.  Returns its path.

    The manifest is seeded too, and the timeline is attested to it,
    because the command line now refuses a document that cannot prove
    what it was computed from -- the gate that catches a stale timeline
    left beside a re-recorded session.  A fixture that seeded only the
    timeline would be asserting that a document of unknown provenance
    can be captioned, which is exactly the state the gate refuses.
    """
    document = build() if document is None else document
    manifest_path = os.path.join(root, "manifest.jsonl")
    frames = document.get("frames", [])
    with open(manifest_path, "w", encoding="utf-8",
              newline="\n") as handle:
        for row in make_rows(REFERENCE_CLOCKS[:len(frames)],
                             REFERENCE_WORDS[:len(frames)]):
            handle.write(json.dumps(row) + "\n")
    document = dict(document)
    document["manifest"] = timeline.attest_manifest(manifest_path, root)
    path = os.path.join(root, "timeline.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(timeline.encode_timeline(document))
    return path


def module_source():
    """Return make_srt.py's own source text, read once, read-only."""
    with open(make_srt.__file__, "r", encoding="utf-8") as handle:
        return handle.read()


def suite_source():
    """Return this suite's own source text, read once, read-only."""
    with open(os.path.abspath(__file__), "r",
              encoding="utf-8") as handle:
        return handle.read()


def delivered_state():
    """Return the state of the delivered artifacts, whatever it is.

    Absence, size and modification time for each of the four files this
    suite must never touch.  Comparing the same reading before and
    after a run proves the suite left the record alone, and it is a
    proof that keeps working once a real session has produced them --
    unlike asserting that they do not exist.
    """
    directory = os.path.dirname(
        os.path.dirname(os.path.abspath(make_srt.__file__)))
    state = {}
    for name in ("transcript.srt", "transcript.md", "timeline.json",
                 "manifest.jsonl"):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            info = os.stat(path)
            state[name] = (info.st_size, info.st_mtime_ns)
        else:
            state[name] = None
    return state


class TestTheInputContract(unittest.TestCase):
    """What is accepted, and what is refused instead of rendered."""

    def test_the_document_form_is_accepted(self):
        srt, markdown, cues = make_srt.build_transcripts(build())
        self.assertEqual(len(cues), len(REFERENCE_CLOCKS))
        self.assertEqual(srt.count(" --> "), len(REFERENCE_CLOCKS))
        self.assertEqual(len(MARKDOWN_ENTRY_RE.findall(markdown)),
                         len(REFERENCE_CLOCKS))

    def test_the_bare_array_form_is_refused(self):
        # THIS ASSERTED THE OPPOSITE ONCE.  A bare array was accepted on
        # the reasoning that a caller holding the entries already is
        # legitimate -- but validate_timeline() begins by requiring an
        # OBJECT and returns immediately for anything else, so an array
        # skipped every document-level invariant: the totals the entries
        # are checked against, the constants the clamp was applied under,
        # the declared final cue end the last cue must close on, and the
        # provenance naming the evidence any of it came from.  This
        # module writes the CUE TIMINGS, so a track computed from
        # unvalidated numbers stays self-consistent while drifting away
        # from the film render_movie.py encodes from the same document.
        with self.assertRaises(make_srt.TranscriptError) as caught:
            make_srt.build_transcripts(minimal())
        self.assertIn("bare array", str(caught.exception))

    def test_a_partial_document_is_refused_and_says_what_is_missing(
            self):
        # Wrapping the entries in a bare {"frames": ...} is not enough
        # either, and the refusal has to be USEFUL about why: the
        # document-level fields are what the entries are checked
        # against, so their absence is named one by one rather than
        # reported as a generic rejection.
        with self.assertRaises(make_srt.TranscriptError) as caught:
            make_srt.build_transcripts({"frames": minimal()})
        message = str(caught.exception)
        for expected in ("manifest", "total", "final_cue_end", "floor"):
            with self.subTest(field=expected):
                self.assertIn(expected, message)

    def test_a_real_document_over_the_same_entries_renders(self):
        # And the entries themselves were never the problem: a complete
        # document built by timeline.py over real readings renders.
        srt, markdown, cues = make_srt.build_transcripts(build())
        self.assertEqual(len(cues), len(REFERENCE_CLOCKS))
        self.assertEqual(srt.count(" --> "), len(REFERENCE_CLOCKS))
        self.assertEqual(len(MARKDOWN_ENTRY_RE.findall(markdown)),
                         len(REFERENCE_CLOCKS))

    def test_a_document_carrying_no_frames_is_refused(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.build_transcripts({"total": REFERENCE_TOTAL})

    def test_frames_that_are_not_an_array_are_refused(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.build_transcripts({"frames": "nope"})
        self.assertTrue(make_srt.entry_problems("nope"))

    def test_an_entry_that_is_not_an_object_is_refused(self):
        self.assertTrue(make_srt.entry_problems([minimal()[0], 7]))

    def test_no_frames_at_all_is_refused(self):
        self.assertTrue(make_srt.entry_problems([]))
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.build_cues([])

    def test_a_frame_index_out_of_step_is_refused(self):
        problems = make_srt.entry_problems(minimal(frame=7))
        self.assertTrue(any("frame 7" in text for text in problems),
                        msg="the index and the position must agree")

    def test_an_absent_index_is_taken_from_the_position(self):
        entries = minimal()
        del entries[1]["frame"]
        self.assertEqual(make_srt.entry_problems(entries), [])
        self.assertEqual(make_srt.frame_index(entries[1], 2), 2)

    def test_a_cue_that_does_not_advance_is_refused(self):
        problems = make_srt.entry_problems(minimal(cue_end=0.25))
        self.assertTrue(any("end after it starts" in text
                            for text in problems))

    def test_overlapping_cues_are_refused(self):
        problems = make_srt.entry_problems(minimal(cue_start=0.1))
        self.assertTrue(any("cannot overlap" in text
                            for text in problems))

    def test_a_film_that_does_not_start_at_zero_is_refused(self):
        entries = minimal()
        entries[0]["cue_start"] = 0.5
        entries[0]["cue_end"] = 0.75
        entries[1]["cue_start"] = 0.75
        entries[1]["cue_end"] = 1.75
        problems = make_srt.entry_problems(entries)
        self.assertTrue(any("starts at zero" in text
                            for text in problems))

    def test_a_window_that_is_not_the_frames_own_is_refused(self):
        problems = make_srt.entry_problems(minimal(duration=9.0))
        self.assertTrue(any("on screen for" in text
                            for text in problems))

    def test_a_gap_nothing_was_charged_for_is_refused(self):
        entries = minimal()
        entries[1]["cue_start"] = 1.25
        entries[1]["cue_end"] = 2.25
        problems = make_srt.entry_problems(entries)
        self.assertTrue(any("nothing was charged" in text
                            for text in problems),
                        msg="video seconds cannot appear from nowhere")

    def test_a_transition_that_was_never_charged_is_refused(self):
        entries = minimal()
        entries[0]["transition_after"] = True
        problems = make_srt.entry_problems(entries)
        self.assertTrue(any("never charged" in text
                            for text in problems),
                        msg="this is the drift the shared timeline "
                            "exists to prevent")

    def test_a_gap_of_the_wrong_length_is_refused(self):
        entries = minimal()
        entries[0]["transition_after"] = True
        entries[1]["cue_start"] = 2.25
        entries[1]["cue_end"] = 3.25
        problems = make_srt.entry_problems(entries, gap=1.0)
        self.assertTrue(any("would not agree" in text
                            for text in problems))

    def test_a_gap_of_the_declared_length_is_accepted(self):
        entries = minimal()
        entries[0]["transition_after"] = True
        entries[1]["cue_start"] = 1.25
        entries[1]["cue_end"] = 2.25
        self.assertEqual(make_srt.entry_problems(entries, gap=1.0), [])

    def test_the_declared_gap_comes_from_the_document(self):
        document = build()
        self.assertEqual(make_srt.transition_gap(document),
                         document["transition"])
        self.assertIsNone(make_srt.transition_gap(minimal()))

    def test_a_boundary_that_is_not_a_number_is_refused(self):
        for value in ("0.5", True, None, float("nan"), float("inf"),
                      -0.25, [], {}):
            with self.subTest(value=repr(value)):
                self.assertTrue(
                    make_srt.entry_problems(minimal(cue_start=value)))

    def test_a_missing_or_blank_sentence_is_refused(self):
        for value in (None, "", "   ", 7, ["I wake."]):
            with self.subTest(value=repr(value)):
                self.assertTrue(
                    make_srt.entry_problems(minimal(commentary=value)),
                    msg="a hole in the record is reported, not filled")

    def test_every_problem_is_reported_not_just_the_first(self):
        problems = make_srt.entry_problems(
            minimal(frame=9, cue_end=0.25, commentary=""))
        self.assertGreaterEqual(len(problems), 3)

    def test_the_document_is_held_to_the_siblings_validator(self):
        document = build()
        document["total"] = document["total"] + 5.0
        self.assertTrue(make_srt.document_problems(
            document, document["frames"]))
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.build_transcripts(document)

    def test_a_last_cue_that_misses_the_total_is_refused(self):
        frames = build()["frames"]
        problems = make_srt.document_problems({"total": 99.0}, frames)
        self.assertTrue(any("totals" in text for text in problems))

    def test_a_bare_array_declares_no_document_to_check(self):
        entries = minimal()
        self.assertEqual(
            make_srt.document_problems(entries, entries), [])
        self.assertEqual(make_srt.declared_total(entries, entries),
                         (1.25, False))


class TestTheSubRipContract(unittest.TestCase):
    """Every property sibling validation asserts of transcript.srt."""

    def setUp(self):
        self.document = build()
        self.srt, self.markdown, self.cues = (
            make_srt.build_transcripts(self.document))
        self.blocks = blocks_of(self.srt)

    def test_one_cue_per_captured_frame(self):
        self.assertEqual(len(self.blocks), len(REFERENCE_CLOCKS))
        self.assertEqual(self.srt.count(" --> "),
                         self.document["frame_count"])

    def test_sequence_numbers_run_from_one_without_a_gap(self):
        self.assertEqual(self.srt.split("\n")[0], "1")
        for number, lines in enumerate(self.blocks, start=1):
            self.assertEqual(lines[0], str(number))

    def test_every_timing_line_is_subrip_with_a_comma(self):
        for lines in self.blocks:
            self.assertRegex(lines[1], TIMING_LINE_RE)
            self.assertNotIn(".", lines[1])

    def test_cues_run_forward_without_overlapping(self):
        previous = None
        for lines in self.blocks:
            start, end = lines[1].split(" --> ")
            self.assertGreater(seconds_of(end), seconds_of(start))
            if previous is not None:
                self.assertGreaterEqual(seconds_of(start), previous)
            previous = seconds_of(end)

    def test_the_transition_second_is_already_charged(self):
        self.assertEqual(cue_starts(self.srt)[4],
                         FIRST_CUE_AFTER_A_TRANSITION,
                         msg="the cue after a transition starts a "
                             "second later, or the captions drift")

    def test_cue_text_is_short_plain_lines_of_whole_words(self):
        for lines in self.blocks:
            text = lines[2:]
            self.assertGreaterEqual(len(text), 1)
            for line in text:
                self.assertTrue(line.strip())
                # A word longer than the geometry overruns rather than
                # being cut, so the bound is per-word and not per-line.
                for word in line.split():
                    self.assertLessEqual(
                        len(word),
                        max(make_srt.CUE_LINE_WIDTH, len(word)))

    def test_nothing_is_styled_or_positioned(self):
        self.assertIsNone(STYLING_RE.search(self.srt))

    def test_one_blank_line_between_cues_and_none_at_the_end(self):
        self.assertTrue(self.srt.endswith("\n"))
        self.assertFalse(self.srt.endswith("\n\n"))
        self.assertNotIn("\n\n\n", self.srt)

    def test_the_final_cue_closes_at_the_timeline_total(self):
        end = self.blocks[-1][1].split(" --> ")[1]
        self.assertEqual(end, timeline.format_srt_timecode(
            self.document["total"]))
        self.assertAlmostEqual(seconds_of(end), REFERENCE_TOTAL,
                               places=3)

    def test_a_cue_list_out_of_order_is_refused(self):
        cues = list(self.cues)
        cues[0] = cues[0]._replace(index=4)
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.render_srt(cues)

    def test_a_cue_of_many_lines_is_accepted(self):
        """mov_text carries multi-line cues, so the sentence is whole."""
        cues = [self.cues[0]._replace(lines=("a", "b", "c", "d", "e"))]
        rendered = make_srt.render_srt(cues)
        for line in ("a", "b", "c", "d", "e"):
            self.assertIn("\n%s" % line, rendered)

    def test_a_cue_with_no_text_is_refused(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.render_srt([self.cues[0]._replace(lines=())])

    def test_a_malformed_timecode_is_refused(self):
        broken = self.cues[0]._replace(start="00:00:00.000")
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.render_srt([broken])

    def test_no_cues_at_all_is_refused(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.render_srt([])


class TestTheMarkdownContract(unittest.TestCase):
    """The four literal constraints on transcript.md."""

    def setUp(self):
        self.document = build()
        self.srt, self.markdown, self.cues = (
            make_srt.build_transcripts(self.document))
        self.entries = [line for line in self.markdown.split("\n")
                        if line.startswith("**")]

    def test_every_entry_begins_at_column_one(self):
        self.assertEqual(len(MARKDOWN_ENTRY_RE.findall(self.markdown)),
                         len(REFERENCE_CLOCKS))
        self.assertEqual(len(self.entries), len(REFERENCE_CLOCKS))
        for line in self.markdown.split("\n"):
            if "**" in line:
                self.assertTrue(line.startswith("**"),
                                msg="no bullet, heading or indent")

    def test_exactly_one_stamp_per_entry_and_none_elsewhere(self):
        self.assertEqual(len(MARKDOWN_STAMP_RE.findall(self.markdown)),
                         len(MARKDOWN_ENTRY_RE.findall(self.markdown)))

    def test_the_header_carries_no_stamp_and_no_meta_word(self):
        # The header is now the two sanctioned lines rather than one:
        # a title carrying the survivor's name, then the statement of
        # what the stamps measure.  It is taken as everything BEFORE
        # the first entry so that the assertion keeps holding the whole
        # of whatever the header becomes, instead of only its first
        # line -- a second header line that nothing looked at is
        # exactly how a meta word would get in.
        header = self.markdown.split("\n\n**")[0]
        self.assertEqual(
            header,
            "# Delphine Ouellette \u2014 what I did, and why\n"
            "\n"
            "Timestamps are cumulative video time.")
        self.assertEqual(MARKDOWN_STAMP_RE.findall(header), [])
        self.assertIsNone(META_GATE_RE.search(header))
        # The name in the title is the name in the entries.  A header
        # that introduced somebody else would still pass every count.
        self.assertIn("Delphine", header)

    def test_no_cue_range_is_emitted(self):
        self.assertNotIn(" --> ", self.markdown)

    def test_the_shape_is_uniform(self):
        for line in self.entries:
            self.assertRegex(
                line,
                r"^\*\*[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}\*\* \S")

    def test_nothing_machine_readable_is_appended(self):
        self.assertTrue(
            self.markdown.rstrip("\n").split("\n")[-1].startswith("**"))
        for token in ("{", "}", "[", "|", "```"):
            self.assertNotIn(token, self.markdown)

    def test_the_only_heading_is_the_title_on_the_first_line(self):
        """`#` is sanctioned for the title and nowhere else.

        This used to be one more token in the blanket assertion above,
        which was a PROXY for "no invented structure" and became too
        blunt the moment the header grew a real title.  The thing that
        actually matters is unchanged and is now stated directly: the
        transcript is a record, not an essay, so no heading may be
        interleaved between entries or appended after them.  One title
        at the very top is the whole of the structure.
        """
        lines = self.markdown.split("\n")
        self.assertTrue(lines[0].startswith("# "))
        self.assertEqual(self.markdown.count("#"), 1)
        for line in lines[1:]:
            self.assertFalse(line.lstrip().startswith("#"),
                             msg="no heading between or after entries")

    def test_the_survivors_sentences_come_through_verbatim(self):
        for word in REFERENCE_WORDS:
            self.assertIn(word, self.markdown)

    def test_the_file_ends_with_exactly_one_newline(self):
        self.assertTrue(self.markdown.endswith("\n"))
        self.assertFalse(self.markdown.endswith("\n\n"))

    def test_a_rendered_body_is_measured_not_trusted(self):
        counted, stamps = make_srt.markdown_counts(self.markdown)
        self.assertEqual(counted, len(self.cues))
        self.assertEqual(stamps, len(self.cues))

    def test_no_entries_at_all_is_refused(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.render_markdown([])


class TestTheOutOfCharacterGate(unittest.TestCase):
    """Meta language stays out of the record; the voice stays in it."""

    def test_every_hit_in_a_transcript_belongs_to_the_survivor(self):
        srt, markdown, cues = make_srt.build_transcripts(build())
        for match in META_GATE_RE.finditer(markdown):
            with self.subTest(hit=match.group(0)):
                self.assertTrue(
                    any(match.group(0).lower() in word.lower()
                        for word in REFERENCE_WORDS),
                    msg="this module generated a word the gate greps "
                        "for")

    def test_the_generated_words_are_the_header_and_nothing_else(self):
        srt, markdown, cues = make_srt.build_transcripts(build())
        generated = markdown
        for cue in cues:
            generated = generated.replace(cue.commentary, "")
        self.assertIsNone(META_GATE_RE.search(generated))
        self.assertEqual(len(MARKDOWN_STAMP_RE.findall(generated)),
                         len(cues))

    def test_the_module_refuses_to_generate_a_meta_word(self):
        for text in ("frame index", "the timeline", "the game",
                     "git status", "options.json", "R2 satisfied"):
            with self.subTest(text=text):
                with self.assertRaises(make_srt.TranscriptError):
                    make_srt.assert_in_character(text, "a header")

    def test_the_module_refuses_to_generate_a_stamp(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.assert_in_character("as of 00:00:00,000", "hdr")
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.assert_in_character("as of 00:00:00.000", "hdr")

    def test_the_sanctioned_header_passes_its_own_gate(self):
        make_srt.assert_in_character(make_srt.MARKDOWN_HEADER,
                                     "the header")

    def test_meta_wording_in_the_survivors_words_blocks_publication(
            self):
        """A REFUSAL now, and the remedy is upstream of this file.

        It used to be an advisory: the line was printed and the
        transcript written, so a stderr message decided whether an
        engineering observation reached the film's caption track.
        """
        words = ("I check the sidebar for the move counter.",) + \
            REFERENCE_WORDS[1:]
        document = build(words=words)
        srt, markdown, cues = make_srt.build_transcripts(document)
        problems = make_srt.voice_problems(cues)
        self.assertEqual(len(problems), 1)
        self.assertIn("sidebar", problems[0])
        self.assertIn("move counter", problems[0])
        self.assertIn("re-recorded", problems[0])
        self.assertIn(words[0], markdown,
                      msg="nothing is rewritten; publication is refused")

    def test_the_survivors_own_words_are_not_false_positives(self):
        """The precision that let the advisory become a refusal."""
        for sentence in (
                "Mechanical engineer, twenty-two years.",
                "I stand in the frame of the door and look out.",
                "My father's watch, and a phone with a lamp in it."):
            with self.subTest(sentence=sentence):
                self.assertEqual(make_srt.meta_gate_words(sentence), [])

    def test_a_false_statement_of_time_blocks_publication(self):
        """The frame-308 defect, at the publication gate.

        Its commentary states a time and a date the frame's own timing
        fields contradict, and every structural check passed over it.
        """
        words = ("It is ten past eight on the twenty-eighth of May.",) \
            + REFERENCE_WORDS[1:]
        document = build(words=words)
        for entry in document["frames"]:
            entry["ingame_clock"] = "08:05:36"
            entry["ingame_date"] = "Thursday, May 20"
        srt, markdown, cues = make_srt.build_transcripts(document)
        problems = make_srt.honesty_problems(
            cues, make_srt.timeline_entries(document))
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("08:05:36" in one for one in problems))
        self.assertTrue(any("twentieth" in one for one in problems))

    def test_a_true_statement_of_time_publishes(self):
        words = ("Five past eight, and I have no water.",) \
            + REFERENCE_WORDS[1:]
        document = build(words=words)
        for entry in document["frames"]:
            entry["ingame_clock"] = "08:05:36"
            entry["ingame_date"] = "Thursday, May 20"
        srt, markdown, cues = make_srt.build_transcripts(document)
        self.assertEqual(
            make_srt.honesty_problems(
                cues, make_srt.timeline_entries(document)), [])

    def test_a_clean_record_reports_nothing(self):
        srt, markdown, cues = make_srt.build_transcripts(build())
        self.assertEqual(make_srt.commentary_advisories(cues), [])

    def test_the_gate_matches_the_meta_sense_and_not_the_other(self):
        self.assertEqual(make_srt.meta_gate_words("a framework"), [])
        self.assertEqual(make_srt.meta_gate_words("optional"), [])
        self.assertEqual(make_srt.meta_gate_words("legitimate work"), [])
        self.assertEqual(make_srt.meta_gate_words("frame 308"),
                         ["frame index"])
        self.assertEqual(make_srt.meta_gate_words("the engine's own"),
                         ["engine"])

    def test_the_vocabulary_has_exactly_one_implementation(self):
        """Two lists meant two answers to one question.

        The second list here named "duration" and "imagemagick" while
        manifest.py's named "option", and neither named the game, the
        engine, a source file, pathfinding, a move counter or cheating.
        """
        self.assertIs(make_srt.meta_gate_words("x") is None, False)
        for sentence in ("the game", "the engine's own pathfinding",
                         "my move counter", "I did not cheat"):
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    make_srt.meta_gate_words(sentence),
                    manifest.find_meta_vocabulary(sentence))


class TestTheTwoArtifactsAgree(unittest.TestCase):
    """The property the one-pass design exists to guarantee."""

    def test_the_nth_stamp_is_the_nth_cue_start(self):
        srt, markdown, cues = make_srt.build_transcripts(build())
        self.assertEqual(markdown_stamps(markdown), cue_starts(srt))
        self.assertEqual(markdown_stamps(markdown),
                         [cue.start for cue in cues])

    def test_the_three_counts_are_one_number(self):
        document = build()
        srt, markdown, cues = make_srt.build_transcripts(document)
        summary = make_srt.summarise(document, document["frames"],
                                     cues, markdown)
        self.assertTrue(summary.counts_agree)
        self.assertEqual(summary.entry_count, len(REFERENCE_CLOCKS))
        self.assertEqual(make_srt.summary_problems(summary), [])

    def test_the_last_cue_closes_where_the_film_ends(self):
        document = build()
        srt, markdown, cues = make_srt.build_transcripts(document)
        summary = make_srt.summarise(document, document["frames"],
                                     cues, markdown)
        self.assertTrue(summary.total_declared)
        self.assertTrue(summary.total_agrees)
        self.assertAlmostEqual(summary.final_cue_end, REFERENCE_TOTAL,
                               places=3)

    def test_counts_out_of_step_are_reported(self):
        summary = make_srt.Summary(7, 7, 6, REFERENCE_TOTAL,
                                   REFERENCE_TOTAL, True)
        self.assertFalse(summary.counts_agree)
        self.assertTrue(make_srt.summary_problems(summary))

    def test_a_total_out_of_step_is_reported(self):
        summary = make_srt.Summary(7, 7, 7, REFERENCE_TOTAL,
                                   REFERENCE_TOTAL + 1.0, True)
        self.assertFalse(summary.total_agrees)
        self.assertTrue(make_srt.summary_problems(summary))

    def test_an_undeclared_total_is_not_reported_as_agreeing(self):
        summary = make_srt.Summary(2, 2, 2, 1.25, 1.25, False)
        self.assertEqual(make_srt.summary_problems(summary), [])
        self.assertIn("nothing to check it against",
                      make_srt.summary_line(summary, "-"))

    def test_the_summary_names_the_numbers_it_measured(self):
        document = build()
        srt, markdown, cues = make_srt.build_transcripts(document)
        summary = make_srt.summarise(document, document["frames"],
                                     cues, markdown)
        line = make_srt.summary_line(summary, "somewhere")
        self.assertIn("7 entr(ies), 7 cue(s), 7 stamp(s)", line)
        self.assertIn("00:00:34,500", line)
        self.assertIn("34.500", line)
        self.assertIn("somewhere", line)


class TestTheCaptionIsTheOnlyTransformation(unittest.TestCase):
    """Wrapping is the ONLY transformation, and it drops nothing.

    The module used to cap a caption at two lines and mark the cut with a
    bracketed elision; 168 of the 395 cues in the first re-recorded
    session ended that way, and many lost the survivor's actual reason
    for acting.  The requirement is that the timestamped transcript IS the
    caption track, so these tests hold the cue to the whole sentence.
    """

    def test_a_long_sentence_reaches_the_caption_entire(self):
        words = (A_LONG_SENTENCE,) + REFERENCE_WORDS[1:]
        srt, markdown, cues = make_srt.build_transcripts(
            build(words=words))
        self.assertGreater(len(cues[0].lines), 2,
                           msg="this sentence needs more than two lines")
        joined = " ".join(cues[0].lines)
        self.assertEqual(joined, " ".join(A_LONG_SENTENCE.split()),
                         msg="every word, in order, in the cue itself")
        self.assertNotIn("[...]", srt)
        self.assertIn(A_LONG_SENTENCE, markdown,
                      msg="the record keeps the whole sentence")

    def test_a_long_caption_is_reported_but_not_cut(self):
        long_enough = " ".join(["one two three four five"] * 12)
        words = (long_enough,) + REFERENCE_WORDS[1:]
        srt, markdown, cues = make_srt.build_transcripts(
            build(words=words))
        advisories = make_srt.length_advisories(cues)
        self.assertEqual(len(advisories), 1)
        self.assertIn("nothing is shortened", advisories[0])
        self.assertIn(long_enough, srt.replace("\n", " "))

    def test_no_word_is_ever_broken_through(self):
        long_word = "supercalifragilisticexpialidocious" * 2
        self.assertGreater(len(long_word), make_srt.CUE_LINE_WIDTH)
        sentence = "I say %s twice." % long_word
        lines = make_srt.wrap_cue_text(sentence)
        # The word overruns the line rather than being cut through, and
        # it is still the whole word when it does.
        self.assertIn(long_word, "\n".join(lines))
        for line in lines:
            for word in line.split():
                self.assertIn(word, sentence)

    def test_a_word_longer_than_the_line_keeps_its_own_line(self):
        long_word = "supercalifragilisticexpialidocious" * 2
        lines = make_srt.wrap_cue_text("%s alone." % long_word)
        self.assertEqual(lines[0], long_word)

    def test_a_sentence_that_fits_is_left_alone(self):
        self.assertEqual(make_srt.wrap_cue_text("I wait here."),
                         ["I wait here."])

    def test_a_line_is_filled_to_the_geometry(self):
        exact = "x" * make_srt.CUE_LINE_WIDTH
        self.assertEqual(make_srt.wrap_cue_text(exact), [exact])

    def test_whitespace_is_normalised_for_the_caption(self):
        self.assertEqual(make_srt.wrap_cue_text("I  wait   here."),
                         ["I wait here."])

    def test_blank_text_makes_no_caption(self):
        for value in ("", "   ", "\t"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(make_srt.TranscriptError):
                    make_srt.wrap_cue_text(value)

    def test_a_caption_needs_room_to_exist(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.wrap_cue_text("I wait.", width=0)

    def test_text_is_required(self):
        with self.assertRaises(make_srt.TranscriptError):
            make_srt.wrap_cue_text(None)


class TestRefusalsThatProtectADownstreamCount(unittest.TestCase):
    """Two refusals that exist because a gate counts, and two more."""

    def test_a_timestamp_shaped_sentence_is_refused(self):
        problems = make_srt.entry_problems(minimal(
            commentary="I waited until 00:00:04,250 by my watch."))
        self.assertTrue(any("timestamp-shaped" in text
                            for text in problems),
                        msg="it would be counted as an extra entry")

    def test_a_full_stop_form_is_refused_too(self):
        problems = make_srt.entry_problems(minimal(
            commentary="I waited until 00:00:04.250 by my watch."))
        self.assertTrue(any("timestamp-shaped" in text
                            for text in problems))

    def test_a_plain_clock_reading_is_left_alone(self):
        self.assertEqual(make_srt.entry_problems(minimal(
            commentary="It was 08:15:32 when I woke.")), [])

    def test_a_cue_arrow_is_refused(self):
        problems = make_srt.entry_problems(minimal(
            commentary="I went north --> then east."))
        self.assertTrue(any("cue separator" in text
                            for text in problems),
                        msg="it would be counted as an extra cue")

    def test_a_line_break_is_refused(self):
        for value in ("I wake.\nI wait.", "I wake.\r\nI wait.",
                      "I wake.\x07"):
            with self.subTest(value=repr(value)):
                problems = make_srt.entry_problems(
                    minimal(commentary=value))
                self.assertTrue(any("line break" in text
                                    for text in problems))

    def test_markup_and_override_codes_are_refused(self):
        for value in ("I wait <i>quietly</i>.", "{\\an8}I wait.",
                      "I wait <font color=red>here</font>."):
            with self.subTest(value=repr(value)):
                problems = make_srt.entry_problems(
                    minimal(commentary=value))
                self.assertTrue(any("markup" in text
                                    for text in problems))


class TestWritingBothArtifacts(unittest.TestCase):
    """The file contract and the exit status a stage reads."""

    def test_both_artifacts_appear_in_one_run(self):
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(make_srt.main([], root=root), 0)
            for name in ("transcript.srt", "transcript.md"):
                self.assertTrue(
                    os.path.isfile(os.path.join(root, name)), name)

    def test_the_output_is_utf8_lf_and_carries_no_mark(self):
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(make_srt.main(["-q"], root=root), 0)
            for name in ("transcript.srt", "transcript.md"):
                data = read_bytes(os.path.join(root, name))
                self.assertNotIn(b"\r", data)
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"),
                                 msg="a mark breaks cue one")
                data.decode("utf-8")
                self.assertTrue(data.endswith(b"\n"))
                self.assertFalse(data.endswith(b"\n\n"))

    def test_the_same_timeline_always_gives_the_same_bytes(self):
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(make_srt.main(["-q"], root=root), 0)
            first = [read_bytes(os.path.join(root, name))
                     for name in ("transcript.srt", "transcript.md")]
            self.assertEqual(make_srt.main(["-q"], root=root), 0)
            second = [read_bytes(os.path.join(root, name))
                      for name in ("transcript.srt", "transcript.md")]
            self.assertEqual(first, second)

    def test_a_dry_run_writes_nothing(self):
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(
                make_srt.main(["--dry-run", "-q"], root=root), 0)
            for name in ("transcript.srt", "transcript.md"):
                self.assertFalse(
                    os.path.exists(os.path.join(root, name)), name)

    def test_named_paths_are_honoured_when_they_name_the_artifacts(self):
        # THIS ASSERTED SOMETHING WIDER ONCE.  Any path inside the tree
        # used to be accepted, which meant --md playthrough/dossier.md
        # would have written a transcript over the survivor's own
        # backstory, and --srt playthrough/manifest.jsonl over the record
        # every count in the report derives from.  Containment was never
        # the protection it looked like: everything this pipeline
        # produces lives inside the tree.  The two destinations are
        # enumerated now, so naming them explicitly still works and
        # naming anything else does not.
        with workspace() as root:
            seed_timeline(root)
            srt = os.path.join(root, "transcript.srt")
            markdown = os.path.join(root, "transcript.md")
            self.assertEqual(make_srt.main(
                ["--srt", srt, "--md", markdown, "-q"], root=root), 0)
            self.assertTrue(os.path.isfile(srt))
            self.assertTrue(os.path.isfile(markdown))

    def test_another_path_inside_the_tree_is_refused(self):
        with workspace() as root:
            seed_timeline(root)
            for name in ("named.srt", "dossier.md",
                         "TECHNICAL_NOTES.md", "manifest.jsonl",
                         "cata-play.mp4"):
                with self.subTest(name=name):
                    with self.assertRaises(make_srt.TranscriptError):
                        make_srt.validated_output_path(
                            os.path.join(root, name),
                            "the transcript path", root)

    def test_the_refusal_names_the_two_destinations(self):
        with workspace() as root:
            with self.assertRaises(make_srt.TranscriptError) as caught:
                make_srt.validated_output_path(
                    os.path.join(root, "dossier.md"),
                    "the transcript path", root)
            message = str(caught.exception)
            self.assertIn("transcript.srt", message)
            self.assertIn("transcript.md", message)

    def test_a_path_outside_the_tree_is_refused(self):
        with workspace() as root:
            outside = os.path.join(os.path.dirname(root), "away.srt")
            with self.assertRaises(make_srt.TranscriptError):
                make_srt.validated_output_path(
                    outside, "the caption path", root)

    def test_a_symlinked_target_is_refused(self):
        with workspace() as root:
            target = os.path.join(root, "transcript.srt")
            os.symlink(os.path.join(root, "elsewhere"), target)
            with self.assertRaises(make_srt.TranscriptError):
                make_srt.validated_output_path(
                    target, "the caption path", root)

    def test_a_path_of_the_wrong_shape_is_refused(self):
        with workspace() as root:
            for value in (None, "", "   ", 7, root):
                with self.subTest(value=repr(value)):
                    with self.assertRaises(make_srt.TranscriptError):
                        make_srt.validated_output_path(
                            value, "the caption path", root)

    def test_one_path_for_both_artifacts_is_refused(self):
        with workspace() as root:
            same = os.path.join(root, "both.txt")
            with self.assertRaises(make_srt.TranscriptError):
                make_srt.write_transcripts("a\n", "b\n", same, same,
                                           root)

    def test_the_pair_is_published_as_one_recoverable_generation(self):
        """The journal and the manifest the docstring used to claim.

        Two atomic renames are not one atomic pair: an interruption
        between them left a caption file describing this timeline beside a
        Markdown transcript describing the previous one, permanently and
        with nothing recording that they disagreed.
        """
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(make_srt.main([], root=root), 0)
            # The journal is cleared once both files are verified.
            self.assertIsNone(timeline.read_generation_journal(
                make_srt.LOCK_NAME, root))
            # And the manifest binds both digests to the timeline's.
            with open(
                    make_srt.generation_manifest_path(root),
                    encoding="utf-8") as handle:
                record = json.load(handle)
            self.assertEqual(record["stage"], "transcripts")
            self.assertEqual(
                record["timeline"]["sha256"],
                timeline.file_digest(
                    os.path.join(root, "timeline.json")))
            published = {one["path"].rsplit("/", 1)[-1]: one["sha256"]
                         for one in record["outputs"]}
            for name in ("transcript.srt", "transcript.md"):
                self.assertEqual(
                    published[name],
                    timeline.file_digest(os.path.join(root, name)),
                    msg="the manifest attests the bytes on disk")

    def test_an_interrupted_pair_is_detected_and_repaired(self):
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(make_srt.main([], root=root), 0)
            srt = os.path.join(root, "transcript.srt")
            # A mixed generation: one file from another run, and the
            # journal that says a publication was in flight.
            with open(srt, "w", encoding="utf-8") as handle:
                handle.write("1\n00:00:00,000 --> 00:00:01,000\nstale\n")
            timeline.write_generation_journal(
                make_srt.LOCK_NAME,
                {"version": timeline.GENERATION_VERSION,
                 "stage": make_srt.LOCK_NAME,
                 "timeline": "playthrough/timeline.json",
                 "targets": [{"path": srt, "sha256": "0" * 64}]},
                root)
            problems = timeline.generation_journal_problems(
                make_srt.LOCK_NAME, root)
            self.assertEqual(len(problems), 1)
            self.assertIn("MIXED", problems[0])
            # Re-running republishes both from the one timeline, which is
            # the repair, and clears the journal.
            self.assertEqual(make_srt.main([], root=root), 0)
            self.assertIsNone(timeline.read_generation_journal(
                make_srt.LOCK_NAME, root))
            with open(srt, encoding="utf-8") as handle:
                self.assertNotIn("stale", handle.read())

    def test_a_refused_timeline_exits_non_zero_and_writes_nothing(self):
        with workspace() as root:
            document = build()
            document["frames"][2]["commentary"] = ""
            seed_timeline(root, document)
            self.assertEqual(make_srt.main([], root=root), 1)
            self.assertFalse(os.path.exists(
                os.path.join(root, "transcript.srt")))
            self.assertFalse(os.path.exists(
                os.path.join(root, "transcript.md")))

    def test_a_missing_timeline_exits_non_zero(self):
        with workspace() as root:
            self.assertEqual(make_srt.main([], root=root), 1)

    def test_a_timeline_that_is_not_json_exits_non_zero(self):
        with workspace() as root:
            path = os.path.join(root, "timeline.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not json")
            self.assertEqual(make_srt.main([], root=root), 1)

    def test_the_artifact_layout_comes_from_the_environment(self):
        with workspace() as root:
            self.assertEqual(make_srt.default_srt_path(),
                             os.path.join(root, "transcript.srt"))
            self.assertEqual(make_srt.default_markdown_path(),
                             os.path.join(root, "transcript.md"))

    def test_the_layout_falls_back_to_the_modules_own_location(self):
        previous = {name: os.environ.pop(name, None)
                    for name in REDIRECTED}
        try:
            expected = os.path.join(
                os.path.dirname(os.path.dirname(
                    os.path.abspath(make_srt.__file__))),
                "transcript.srt")
            self.assertEqual(make_srt.default_srt_path(), expected)
        finally:
            for name, value in previous.items():
                if value is not None:
                    os.environ[name] = value

    def test_the_delivered_artifacts_were_never_touched(self):
        before = delivered_state()
        with workspace() as root:
            seed_timeline(root)
            self.assertEqual(make_srt.main(["-q"], root=root), 0)
        self.assertEqual(before, delivered_state(),
                         msg="a run inside a workspace must leave the "
                             "delivered record exactly as it was")


class TestTheModuleKeepsItsPromises(unittest.TestCase):
    """Promises a test cannot see are promises that quietly lapse."""

    def test_the_timecode_has_exactly_one_implementation(self):
        source = module_source()
        self.assertIn("from timeline import", source)
        self.assertNotIn("%02d:%02d:%02d", source)
        self.assertIs(make_srt.format_srt_timecode,
                      timeline.format_srt_timecode)

    def test_there_is_no_cursor_walk_and_no_transition_constant(self):
        body = "\n".join(line for line in module_source().split("\n")
                         if not line.strip().startswith("#"))
        self.assertNotIn("+=", body)
        self.assertIsNone(re.search(r"^TRANSITION\s*=", body,
                                    re.MULTILINE))
        self.assertFalse(hasattr(make_srt, "TRANSITION"))

    def test_the_cue_times_are_read_from_the_timeline(self):
        document = build()
        srt, markdown, cues = make_srt.build_transcripts(document)
        for entry, cue in zip(document["frames"], cues):
            self.assertEqual(
                cue.start,
                timeline.format_srt_timecode(entry["cue_start"]))
            self.assertEqual(
                cue.end, timeline.format_srt_timecode(entry["cue_end"]))

    def test_nothing_outside_the_standard_library_is_imported(self):
        # `manifest` joins the list because the voice vocabulary and
        # the clock-statement parser have ONE implementation, in the
        # module that also refuses a row at write time; timeline.py
        # already imports it, so it is not a new dependency.
        allowed = ("argparse", "hashlib", "json", "math", "os", "re",
                   "sys", "tempfile", "textwrap", "typing", "timeline",
                   "manifest")
        for node in ast.walk(ast.parse(module_source())):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0],
                              allowed)

    def test_there_is_no_shell_no_eval_and_no_network(self):
        source = module_source()
        for forbidden in ("subprocess", "shell=True", "eval(",
                          "exec(", "socket", "urllib", "requests"):
            self.assertNotIn(forbidden, source)

    def test_bytecode_is_refused_before_the_sibling_import(self):
        self.assertTrue(sys.dont_write_bytecode)
        source = module_source()
        self.assertLess(source.index("sys.dont_write_bytecode = True"),
                        source.index("from timeline import"))

    def test_no_flag_can_change_what_the_captions_are(self):
        source = module_source()
        for forbidden in ("WEBVTT", "webvtt", "--burn", "hardsub",
                          "-vf subtitles", "force_style"):
            self.assertNotIn(forbidden, source)
        options = [action.option_strings
                   for action in make_srt.build_parser()._actions]
        self.assertEqual(
            sorted(flat for pair in options for flat in pair),
            sorted(["-h", "--help", "--timeline", "--srt", "--md",
                    "-n", "--dry-run", "-q", "--quiet"]))


class TestTheSuiteIsHermetic(unittest.TestCase):
    """A suite that wrote to the record would be worse than none."""

    def test_every_class_that_runs_the_command_line_redirects(self):
        tree = ast.parse(suite_source())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            body = ast.dump(node)
            if "'main'" not in body:
                continue
            self.assertIn("workspace", body,
                          msg="%s calls the command line and so must "
                              "work inside workspace()" % node.name)

    def test_the_environment_is_restored_afterwards(self):
        before = {name: os.environ.get(name) for name in REDIRECTED}
        with workspace() as root:
            self.assertTrue(os.path.isdir(root))
        after = {name: os.environ.get(name) for name in REDIRECTED}
        self.assertEqual(before, after)

    def test_a_workspace_is_removed_again(self):
        with workspace() as root:
            path = root
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
