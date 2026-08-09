#!/usr/bin/env python3
"""Read-only contract suite for the COMMITTED generated artifacts.

    python3 -B playthrough/tooling/test_artifacts.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT THIS SUITE IS FOR
Every other suite in this directory tests a PRODUCER: give it inputs,
watch what it writes.  This one tests the ARTIFACTS THAT SHIPPED --
playthrough/manifest.jsonl, playthrough/timeline.json,
playthrough/frames/**, the two transcripts and the engine-written
userdir -- as they exist in the repository right now.

That is a different question, and the requirements make it the more
important one.  The frames are the evidence; the manifest is the record
of which keystroke produced each of them; the timeline is the claim that
the film's pacing is the game's own clock.  A producer that is perfectly
tested still leaves those three able to disagree with each other -- a
frame withdrawn after its row was written, a timeline regenerated from a
manifest that has since changed, a hand-edited total -- and every count
downstream would still tally.  So the contract asserted here is
CROSS-ARTIFACT AGREEMENT and PROVENANCE:

* THE MANIFEST.  Exactly the six documented keys per row, IN ORDER, one
  row per frame, indices contiguous from 1, canonical `frame_%05d.png`
  names, every referenced frame present on disk, and no empty action or
  commentary -- read through manifest.py's own validator, which is the
  gate a write passes, so the committed record is held to exactly the
  standard the producer holds a new row to.
* THE TIMELINE, REGENERATED.  The committed document is rebuilt IN
  MEMORY from the committed manifest and its two sidecars and compared
  through the deterministic encoder.  Equal encodings are the claim
  worth making: this file was computed from this manifest by this code.
  A mutation test proves that comparison is load-bearing rather than
  vacuous.
* THE FRAMES.  A header-only scan of every captured file: contiguous
  names, nothing else in the directory, and 1920x1080 in every IHDR --
  the capture geometry read out of env.sh rather than written here as a
  literal.
* THE TRANSCRIPTS.  Cue count equal to the frame count, cue windows
  equal to the timeline's windows, the final cue ending exactly at the
  declared total, and every cue carrying its commentary ENTIRE -- the
  property the caption producer was corrected to hold.
* THE ENGINE-WRITTEN USERDIR.  One world and one survivor persistence
  generation -- either a resumable live save or the graveyard save,
  log and matching memorial pair produced by an evidenced death --
  tracked by git rather than swallowed by the `\\#*` ignore rule; the
  option values the pipeline depends on; and NO keybinding for any
  debug action.  That turns "no cheating" and the legitimate ending
  from claims into properties a stranger can check.

THIS SUITE MODIFIES NOTHING.  It opens no file for writing, invokes no
producer that publishes, and takes a size-and-mtime fingerprint of every
artifact it reads before the first test and re-checks it after the last
one, so an accidental write would fail the run rather than quietly
rewrite the evidence.  `TestTheSuiteTouchesNothing` also reads this
module's own source and refuses any writing call in it.

It imports only the standard library and this directory's own modules --
nothing from playthrough/tooling/requirements.txt -- so the artifacts
are auditable on a bare interpreter without provisioning a render
toolchain first.
"""

import ast
import json
import os
import re
import struct
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import make_srt                                        # noqa: E402
import make_transitions                                # noqa: E402
import manifest                                        # noqa: E402
import render_movie                                    # noqa: E402
import seed_options                                    # noqa: E402
import session                                         # noqa: E402
import timeline                                        # noqa: E402

sys.dont_write_bytecode = True

TOOLING = os.path.abspath(os.path.dirname(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
REPO_ROOT = os.path.dirname(PLAYTHROUGH)

# The artifacts, by the paths the producers publish them to.
MANIFEST = os.path.join(PLAYTHROUGH, "manifest.jsonl")
AMENDMENTS = os.path.join(PLAYTHROUGH, manifest.AMENDMENTS_NAME)
TIMELINE = os.path.join(PLAYTHROUGH, "timeline.json")
DIGESTS = os.path.join(PLAYTHROUGH, *manifest.DIGESTS_REL_PARTS)
FRAMES_DIR = os.path.join(PLAYTHROUGH, "frames")
TRANSCRIPT_SRT = os.path.join(PLAYTHROUGH, "transcript.srt")
TRANSCRIPT_MD = os.path.join(PLAYTHROUGH, "transcript.md")
USERDIR = os.path.join(PLAYTHROUGH, "userdir")
CONFIG_DIR = os.path.join(USERDIR, "config")
OPTIONS_JSON = os.path.join(CONFIG_DIR, "options.json")
BUILD_DIR = os.path.join(PLAYTHROUGH, "build")
CONCAT_LIST = os.path.join(BUILD_DIR, "concat.txt")
TRANSITIONS_DIR = os.path.join(BUILD_DIR, "transitions")
MOVIE_MANIFEST = os.path.join(BUILD_DIR, "movie.json")
TRANSCRIPT_MANIFEST = os.path.join(BUILD_DIR, "transcript.json")
MOVIE = os.path.join(PLAYTHROUGH, "cata-play.mp4")
CAPTIONED_MOVIE = os.path.join(PLAYTHROUGH, "cata-play-cc.mp4")

# The two ISO base media atoms whose ORDER decides whether a player can
# start on its first request: `moov` is the index, `mdat` is every byte
# of picture.  `-movflags +faststart` puts the index first, and a mux
# does not inherit it from its input -- a runtime QA pass found the
# captioned film shipped with `moov` last, costing every viewer a tail
# fetch before playback could begin.  Both films are held to it below.
MOOV_ATOM = b"moov"
MDAT_ATOM = b"mdat"
ATOM_HEADER_BYTES = 8
ATOM_LARGE_SIZE = 1
ATOM_LARGE_SIZE_BYTES = 8
MAX_TOP_LEVEL_ATOMS = 64

# The frame file name, from the producer rather than restated here.
FRAME_NAME_RE = re.compile(r"^frame_(\d{5})\.png$")

# PNG: an 8-byte signature, then a length and the type "IHDR", then the
# width and height as big-endian 32-bit integers.  Reading 24 bytes is
# the whole geometry check -- no decoder, no Pillow, no dependency.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_HEADER_BYTES = 24
PNG_IHDR_AT = slice(12, 16)
PNG_GEOMETRY_AT = slice(16, 24)

# A frame that is a valid PNG but holds nothing would still pass a
# header check, so a floor stands in for "this is a screenshot".  A
# 1920x1080 capture of real screen content is orders of magnitude
# above it; the number is a smoke test, not a measurement.
MIN_FRAME_BYTES = 1024

# The three engine option values this pipeline depends on, and where
# each expectation comes from.  seed_options.py owns them, so they are
# read from it rather than duplicated: a test that restated them would
# pass with the producer wrong.
OPTION_24_HOUR = seed_options.OPT_24_HOUR
OPTION_SOUND = seed_options.OPT_SOUND_ENABLED
OPTION_TILES = seed_options.OPT_TILES

# `git ls-files` proves an artifact is TRACKED, which for the save data
# is a requirement rather than hygiene: .gitignore's `\#*` rule matches
# CDDA's per-character files, so a `git add` that skipped them would
# report success and track nothing.
GIT = "git"


def _read_text(path):
    """Return a whole text file, with its descriptor closed again."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_bytes(path):
    """Return a whole file as bytes."""
    with open(path, "rb") as handle:
        return handle.read()


def _top_level_atoms(path):
    """Return [(type, offset, size)] for an MP4's top-level atoms.

    A bounded walk of the ISO base media container: four bytes of
    big-endian size, four bytes of type, and on to the next one.  Enough
    of the format to answer one question -- does the index come before
    the picture -- without a parser or a dependency, and with every
    degenerate case ending the walk rather than looping: size 1 means the
    real length is in the following 64 bits, size 0 means "to the end of
    the file", and anything smaller than a header is refused.
    """
    atoms = []
    with open(path, "rb") as handle:
        size_of = os.path.getsize(path)
        offset = 0
        while offset < size_of and len(atoms) < MAX_TOP_LEVEL_ATOMS:
            handle.seek(offset)
            header = handle.read(ATOM_HEADER_BYTES)
            if len(header) < ATOM_HEADER_BYTES:
                break
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8]
            if size == ATOM_LARGE_SIZE:
                extra = handle.read(ATOM_LARGE_SIZE_BYTES)
                if len(extra) < ATOM_LARGE_SIZE_BYTES:
                    break
                size = int.from_bytes(extra, "big")
            elif size == 0:
                size = size_of - offset
            atoms.append((kind, offset, size))
            if size < ATOM_HEADER_BYTES:
                break
            offset += size
    return atoms


def _fingerprint():
    """Size and mtime of every artifact this suite reads.

    The proof that a read-only suite stayed read-only.  Frames are
    included individually: one stat per captured frame is cheap, and a
    suite that fingerprinted only the directory would miss a rewrite
    that kept the file count.
    """
    prints = {}
    paths = [MANIFEST, TIMELINE, TRANSCRIPT_SRT, TRANSCRIPT_MD,
             CONCAT_LIST, MOVIE_MANIFEST, TRANSCRIPT_MANIFEST, MOVIE,
             os.path.join(BUILD_DIR, "observations.jsonl"),
             os.path.join(BUILD_DIR, "frame_dates.jsonl")]
    if os.path.isdir(TRANSITIONS_DIR):
        paths.extend(os.path.join(TRANSITIONS_DIR, name)
                     for name in os.listdir(TRANSITIONS_DIR))
    if os.path.isdir(FRAMES_DIR):
        paths.extend(os.path.join(FRAMES_DIR, name)
                     for name in os.listdir(FRAMES_DIR))
    if os.path.isdir(USERDIR):
        for base, _, names in os.walk(USERDIR):
            paths.extend(os.path.join(base, name) for name in names)
    for path in paths:
        try:
            info = os.stat(path)
        except OSError:
            prints[path] = None
            continue
        prints[path] = (info.st_size, info.st_mtime_ns)
    return prints


BASELINE = {}


def setUpModule():
    """Fingerprint the evidence before a single test reads it."""
    BASELINE.update(_fingerprint())


def tearDownModule():
    """Refuse to finish having changed any artifact.

    Raised rather than reported through an assertion method, because
    there is no test case to attach it to at this point -- and a run
    that mutated the evidence must fail loudly however it managed it.
    """
    after = _fingerprint()
    changed = sorted(path for path in set(BASELINE) | set(after)
                     if BASELINE.get(path) != after.get(path))
    if changed:
        raise AssertionError(
            "this suite is read-only and %d artifact(s) changed while "
            "it ran: %s" % (len(changed), ", ".join(changed[:10])))


class ArtifactFixture(unittest.TestCase):
    """The committed artifacts, loaded once for the whole class.

    Read in setUpClass rather than setUp: the manifest is 560 rows and
    the timeline regeneration walks all of them, so per-test reloading
    would turn a fast contract check into a slow one and tempt whoever
    came next into thinning it out.
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(MANIFEST):
            raise unittest.SkipTest(
                "no committed manifest at %s: this suite audits the "
                "artifacts a session produced, and there has been no "
                "session in this checkout" % MANIFEST)
        cls.rows = manifest.read_rows(MANIFEST)
        # THE RECORD AND THE PUBLISHED NARRATION ARE TWO THINGS.
        # manifest.jsonl is immutable evidence; a correction to a row's
        # action or commentary lives in playthrough/amendments.jsonl and
        # is applied by manifest.resolve_rows() when a derivative is
        # computed.  So the suite carries both: `rows` for every check
        # about the record, and `resolved` for every check about what a
        # derivative should say.
        cls.amendments = manifest.read_amendments(AMENDMENTS)
        cls.digests = manifest.read_frame_digests(DIGESTS)
        cls.resolved, cls.amended = manifest.resolve_rows(
            cls.rows, cls.amendments)
        cls.document = timeline.read_timeline(TIMELINE)
        cls.entries = cls.document["frames"]
        cls.frame_names = sorted(os.listdir(FRAMES_DIR))

    def frame_path(self, index):
        """Absolute path of one captured frame."""
        return os.path.join(FRAMES_DIR,
                            manifest.FRAME_NAME_FORMAT % index)


class TestTheManifestContract(ArtifactFixture):
    """One row per keystroke, in the six documented fields.

    The manifest is the only record of WHICH keystroke produced which
    frame.  A row that lost a field, or an index that skipped, breaks
    the 1:1 relation the whole capture requirement rests on -- and
    breaks it silently, because a shorter record still parses.
    """

    def test_the_record_is_not_empty(self):
        self.assertGreater(len(self.rows), 0)

    def test_every_row_carries_exactly_the_six_fields(self):
        for position, row in enumerate(self.rows, start=1):
            with self.subTest(row=position):
                self.assertEqual(tuple(row.keys()), manifest.FIELDS)

    def test_the_six_fields_are_the_documented_ones(self):
        # Spelled out here as well as read from the module: the schema
        # is the user's own, and a test that only compared the file to
        # the module would follow the module if it drifted.
        self.assertEqual(
            manifest.FIELDS,
            ("frame", "file", "real_ts", "ingame_clock", "action",
             "commentary"))

    def test_the_indices_start_at_one(self):
        self.assertEqual(self.rows[0]["frame"], 1)

    def test_the_indices_are_contiguous(self):
        self.assertEqual([row["frame"] for row in self.rows],
                         list(range(1, len(self.rows) + 1)))

    def test_every_file_field_is_the_canonical_name(self):
        for row in self.rows:
            with self.subTest(frame=row["frame"]):
                self.assertEqual(
                    row["file"],
                    manifest.FRAME_FILE_FORMAT % row["frame"])

    def test_every_referenced_frame_exists(self):
        for row in self.rows:
            with self.subTest(frame=row["frame"]):
                self.assertTrue(
                    os.path.isfile(self.frame_path(row["frame"])),
                    msg="%s is referenced by no file on disk"
                        % row["file"])

    def test_no_action_is_empty(self):
        for row in self.rows:
            with self.subTest(frame=row["frame"]):
                self.assertTrue(row["action"].strip())

    def test_no_commentary_is_empty(self):
        for row in self.rows:
            with self.subTest(frame=row["frame"]):
                self.assertTrue(row["commentary"].strip())

    def test_no_field_exceeds_the_length_ceiling(self):
        for row in self.rows:
            for key in ("action", "commentary"):
                with self.subTest(frame=row["frame"], field=key):
                    self.assertLessEqual(len(row[key]),
                                         manifest.MAX_FIELD_LENGTH)

    def test_every_timestamp_is_canonical(self):
        for row in self.rows:
            with self.subTest(frame=row["frame"]):
                self.assertEqual(
                    manifest.canonical_real_ts(row["real_ts"]),
                    row["real_ts"])

    def test_the_capture_clock_never_runs_backwards(self):
        # Wall-clock time, not the game's: the frames were captured in
        # order, so their real timestamps cannot decrease.
        stamps = [row["real_ts"] for row in self.rows]
        self.assertEqual(stamps, sorted(stamps))

    def test_every_clock_reading_is_classifiable(self):
        # An unrecognised reading would mean a value nobody can
        # interpret sitting in the evidence.
        for row in self.rows:
            with self.subTest(frame=row["frame"]):
                self.assertNotEqual(
                    manifest.classify_ingame_clock(row["ingame_clock"]),
                    manifest.CLOCK_UNRECOGNISED)

    def test_the_producer_validator_finds_no_problem(self):
        # The gate a WRITE passes, applied to the committed record: a
        # standard the producer holds one new row to, held to every row.
        #
        # IN TWO HALVES, BECAUSE THE RECORD AND THE PUBLISHED NARRATION
        # ARE TWO THINGS.  The structural half -- the six fields in
        # order, the index inside its range, the `file` that index
        # formats to, the canonical real_ts, the clock that is a reading
        # or null -- describes the capture and is held against the
        # RECORDED rows, which are immutable.  The voice gate and the
        # placeholder sentinels describe the two amendable narrations,
        # and a captured row is never edited to satisfy them: the remedy
        # is an amendment bound to that row's digest, so they are held
        # against the RESOLVED rows, which are what the transcript and
        # the caption track actually carry.  Both halves are the same
        # function, and nothing is skipped -- an unamended meta word is
        # still reported, because resolving leaves it where it was.
        self.assertEqual(
            manifest.row_problems(self.rows, narration=False), [])
        self.assertEqual(manifest.row_problems(self.resolved), [])

    def test_the_sequence_validator_finds_no_problem(self):
        self.assertEqual(manifest.sequence_problems(self.rows), [])

    def test_the_whole_manifest_verifies_against_the_frames(self):
        self.assertEqual(
            manifest.verify_manifest(MANIFEST, FRAMES_DIR), [])

    def test_the_file_is_one_json_object_per_line(self):
        for number, line in enumerate(
                _read_text(MANIFEST).splitlines(), start=1):
            with self.subTest(line=number):
                self.assertIsInstance(json.loads(line), dict)

    def test_the_line_count_is_the_row_count(self):
        self.assertEqual(len(_read_text(MANIFEST).splitlines()),
                         len(self.rows))

    def test_the_file_has_no_byte_order_mark(self):
        self.assertFalse(_read_bytes(MANIFEST).startswith(b"\xef\xbb\xbf"))

    def test_the_file_has_unix_line_endings(self):
        self.assertNotIn(b"\r", _read_bytes(MANIFEST))

    def test_the_file_ends_with_exactly_one_newline(self):
        raw = _read_bytes(MANIFEST)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))


class TestTheTimelineContract(ArtifactFixture):
    """The pacing claim, and its provenance.

    timeline.json is the single source of truth both the render and the
    captions are built from, so a document that no longer follows from
    the manifest would desynchronise the film from its transcript while
    every count still tallied.
    """

    def test_the_document_carries_exactly_the_declared_fields(self):
        self.assertEqual(tuple(self.document.keys()),
                         timeline.DOCUMENT_FIELDS)

    def test_the_constants_are_the_requirement(self):
        self.assertEqual(self.document["floor"], 0.25)
        self.assertEqual(self.document["ceil"], 10.0)
        self.assertEqual(self.document["transition"], 1.0)

    def test_the_constants_are_the_producers(self):
        self.assertEqual(self.document["floor"], timeline.FLOOR)
        self.assertEqual(self.document["ceil"], timeline.CEIL)
        self.assertEqual(self.document["transition"],
                         timeline.TRANSITION)

    def test_the_version_is_declared(self):
        self.assertEqual(self.document["version"],
                         timeline.TIMELINE_VERSION)

    def test_there_is_one_entry_per_manifest_row(self):
        self.assertEqual(len(self.entries), len(self.rows))
        self.assertEqual(self.document["frame_count"], len(self.rows))

    def test_every_entry_carries_exactly_the_declared_fields(self):
        for entry in self.entries:
            with self.subTest(frame=entry["frame"]):
                self.assertEqual(tuple(entry.keys()),
                                 timeline.ENTRY_FIELDS)

    def test_every_entry_agrees_with_its_manifest_row(self):
        # Same order, nothing dropped, merged or reordered -- asserted
        # position by position rather than by counting.  The narration is
        # compared against the RESOLVED rows, because that is what a
        # derivative is computed from; the `amended` flag on each entry
        # is then held to the ledger itself below.
        for entry, row in zip(self.entries, self.resolved):
            with self.subTest(frame=row["frame"]):
                self.assertEqual(entry["frame"], row["frame"])
                self.assertEqual(entry["file"], row["file"])
                self.assertEqual(entry["action"], row["action"])
                self.assertEqual(entry["commentary"], row["commentary"])

    def test_every_amended_entry_is_marked_and_only_those(self):
        marked = tuple(entry["frame"] for entry in self.entries
                       if entry["amended"])
        self.assertEqual(marked, self.amended)

    def test_the_amendment_attestation_matches_the_ledger(self):
        attestation = self.document["amendments"]
        if not self.amendments:
            self.assertIsNone(attestation)
            return
        self.assertEqual(list(attestation),
                         list(timeline.AMENDMENT_ATTESTATION_FIELDS))
        self.assertEqual(attestation["rows"], len(self.amendments))
        self.assertEqual(attestation["applied"], len(self.amendments))
        self.assertEqual(attestation["sha256"],
                         timeline.file_digest(AMENDMENTS))
        self.assertEqual(
            timeline.amendment_attestation_problems(self.document), [])

    def test_the_capture_attestation_matches_the_ledger(self):
        """The document names the ledger its frames were verified from.

        THE DEFECT THIS TEST EXISTS FOR.  Until this attestation existed
        the timeline said nothing whatever about the PIXELS it paced, so a
        same-sized replacement frame passed every check in the chain.  The
        document now carries the ledger's own digest and row count, and
        capture_attestation_problems() re-hashes every frame against it.
        """
        attestation = self.document["captures"]
        self.assertIsNotNone(
            attestation,
            msg=("the committed timeline paces committed frames, so it "
                 "must name the ledger they were verified against"))
        self.assertEqual(list(attestation),
                         list(timeline.CAPTURE_ATTESTATION_FIELDS))
        self.assertEqual(attestation["sha256"],
                         timeline.file_digest(DIGESTS))
        self.assertEqual(attestation["rows"], len(self.digests))
        self.assertEqual(attestation["verified"],
                         self.document["frame_count"])
        self.assertEqual(
            timeline.capture_attestation_problems(self.document), [])

    def test_every_paced_frame_still_hashes_to_its_attestation(self):
        """The frames on disk are the frames that were captured."""
        self.assertEqual(
            manifest.verify_frame_digests(self.rows, self.digests), [])

    def test_an_unamended_entry_reads_exactly_as_recorded(self):
        by_frame = {row["frame"]: row for row in self.rows}
        for entry in self.entries:
            if entry["amended"]:
                continue
            with self.subTest(frame=entry["frame"]):
                row = by_frame[entry["frame"]]
                self.assertEqual(entry["action"], row["action"])
                self.assertEqual(entry["commentary"], row["commentary"])

    def test_every_duration_is_inside_the_clamp(self):
        for entry in self.entries:
            with self.subTest(frame=entry["frame"]):
                self.assertGreaterEqual(entry["duration"],
                                        timeline.FLOOR)
                self.assertLessEqual(entry["duration"], timeline.CEIL)

    def test_every_duration_is_its_clamped_delta(self):
        for entry in self.entries:
            with self.subTest(frame=entry["frame"]):
                self.assertEqual(
                    entry["duration"],
                    timeline.clamp_duration(entry["raw_delta"]))

    def test_a_zero_delta_frame_sits_on_the_floor(self):
        # Menu keystrokes consume no game time and are NOT dropped or
        # merged; they fall to the floor, which is the requirement.
        floored = [entry for entry in self.entries
                   if entry["raw_delta"] == 0.0]
        self.assertTrue(floored, msg="a real session has menu frames")
        for entry in floored:
            with self.subTest(frame=entry["frame"]):
                self.assertEqual(entry["duration"], timeline.FLOOR)

    def test_every_transition_flag_follows_the_ceiling(self):
        for entry in self.entries:
            with self.subTest(frame=entry["frame"]):
                self.assertEqual(entry["transition_after"],
                                 entry["raw_delta"] > timeline.CEIL)

    def test_the_transition_count_is_the_flag_count(self):
        flagged = [entry for entry in self.entries
                   if entry["transition_after"]]
        self.assertEqual(self.document["transition_count"],
                         len(flagged))

    def test_the_final_entry_is_not_flagged(self):
        # A flagged last frame has no successor to fade into, and
        # make_transitions.py refuses to plan one, so a document that
        # carried the flag there could never be rendered.
        self.assertFalse(self.entries[-1]["transition_after"])

    def test_the_reconciled_count_is_the_reconciled_entries(self):
        reconciled = [entry for entry in self.entries
                      if entry["reconciled"]]
        self.assertEqual(self.document["reconciled_count"],
                         len(reconciled))

    def test_every_reconciled_entry_says_why(self):
        for entry in self.entries:
            with self.subTest(frame=entry["frame"]):
                if entry["reconciled"]:
                    self.assertTrue(entry["reconciled_reason"])
                else:
                    self.assertIsNone(entry["reconciled_reason"])

    def test_the_date_counters_account_for_every_entry(self):
        total = sum(self.document[key] for key in (
            "date_confirmed_count", "date_corrected_count",
            "date_unverified_count", "date_conflict_count"))
        self.assertEqual(total, self.document["frame_count"])

    def test_no_date_reading_is_in_conflict(self):
        self.assertEqual(self.document["date_conflict_count"], 0)

    def test_the_first_cue_starts_at_zero(self):
        self.assertEqual(self.entries[0]["cue_start"], 0.0)

    def test_every_cue_window_is_its_duration(self):
        for entry in self.entries:
            with self.subTest(frame=entry["frame"]):
                self.assertAlmostEqual(
                    entry["cue_end"] - entry["cue_start"],
                    entry["duration"], places=3)

    def test_the_cues_recur_and_charge_the_transitions(self):
        # The inserted second is charged to VIDEO time, so the cue
        # after a transition starts a full second after the previous
        # one ended.  This is the arithmetic that keeps the captions
        # from drifting further out of step with every transition.
        for current, following in zip(self.entries, self.entries[1:]):
            with self.subTest(frame=current["frame"]):
                gap = (timeline.TRANSITION
                       if current["transition_after"] else 0.0)
                self.assertAlmostEqual(following["cue_start"],
                                       current["cue_end"] + gap,
                                       places=3)

    def test_the_duration_total_is_the_sum_of_the_durations(self):
        self.assertAlmostEqual(
            self.document["total_duration"],
            sum(entry["duration"] for entry in self.entries), places=3)

    def test_the_transition_total_is_the_flags_times_the_constant(self):
        self.assertAlmostEqual(
            self.document["total_transition"],
            self.document["transition_count"] * timeline.TRANSITION,
            places=3)

    def test_the_total_is_the_two_totals(self):
        self.assertAlmostEqual(
            self.document["total"],
            self.document["total_duration"] +
            self.document["total_transition"], places=3)

    def test_the_final_cue_end_is_the_total(self):
        # The invariant the whole caption track hangs on:
        # sum(durations) + sum(transitions) == total == final cue end.
        self.assertAlmostEqual(self.document["final_cue_end"],
                               self.document["total"], places=3)
        self.assertAlmostEqual(self.entries[-1]["cue_end"],
                               self.document["total"], places=3)

    def test_the_producer_validator_finds_no_problem(self):
        self.assertEqual(timeline.validate_timeline(self.document), [])

    def test_the_document_is_the_encoders_own_output(self):
        # Byte-for-byte what the encoder writes, which is how a hand
        # edit is caught even when the edited value is plausible.
        self.assertEqual(_read_text(TIMELINE),
                         timeline.encode_timeline(self.document))

    def test_the_document_regenerates_from_the_committed_manifest(self):
        # THE PROVENANCE CHECK.  Both sides pass through the same
        # deterministic encoder, so equal encodings say exactly this:
        # this file was computed from this manifest, and from the same
        # telemetry and date evidence, by this code.
        self.assertEqual(timeline.encode_timeline(self.document),
                         timeline.encode_timeline(self.regenerate()))

    def test_the_regeneration_comparison_is_load_bearing(self):
        # A provenance check that could not fail would be worse than
        # none, so one entry of a COPY is altered and the comparison
        # must notice.  Nothing on disk is touched.
        fresh = json.loads(json.dumps(self.regenerate()))
        fresh["frames"][0]["duration"] = 9.5
        self.assertNotEqual(timeline.encode_timeline(self.document),
                            timeline.encode_timeline(fresh))

    def regenerate(self):
        """Rebuild the timeline in memory.  Reads, never writes.

        The manifest ATTESTATION is recomputed alongside the entries,
        because it is part of the document the encoder writes: the
        stored path, sha256 and row count of the manifest this timeline
        was computed from.  Rebuilding without it would compare a
        document carrying provenance against one carrying none and
        report drift on a file that is correct.
        """
        rows = manifest.read_rows(MANIFEST)
        resolved, amended = manifest.resolve_rows(
            rows, manifest.read_amendments(AMENDMENTS))
        return timeline.build_timeline(
            resolved, timeline.load_observations(),
            timeline.date_lines_for_rows(rows),
            timeline.attest_manifest(MANIFEST),
            timeline.attest_amendments(
                AMENDMENTS, applied=len(self.amendments)),
            amended,
            # AND THE CAPTURE ATTESTATION, for the same reason as the
            # manifest's: it is part of the document the encoder writes.
            # It names the ledger the frames were re-hashed against and
            # how many of them were checked, and rebuilding without it
            # would compare a document carrying that provenance against
            # one carrying none.
            timeline.attest_captures(
                DIGESTS, verified=len(rows)))

    def test_the_file_has_no_byte_order_mark(self):
        self.assertFalse(_read_bytes(TIMELINE).startswith(
            b"\xef\xbb\xbf"))

    def test_the_file_has_unix_line_endings(self):
        self.assertNotIn(b"\r", _read_bytes(TIMELINE))


class TestTheFramesContract(ArtifactFixture):
    """One 1920x1080 capture per keystroke, and nothing else.

    A header-only scan: the point is completeness across all 560 files,
    which is what a spot check of frame_00001.png cannot establish.
    """

    def geometry_from_env(self):
        """The capture geometry, read from env.sh's single definition."""
        source = _read_text(os.path.join(TOOLING, "env.sh"))
        found = {}
        for key in ("WIDTH", "HEIGHT"):
            match = re.search(
                r"^export PLAYTHROUGH_SCREEN_%s=(\d+)$" % key,
                source, re.MULTILINE)
            self.assertIsNotNone(
                match, msg="env.sh no longer declares the %s" % key)
            found[key] = int(match.group(1))
        return found["WIDTH"], found["HEIGHT"]

    def header(self, name):
        """The first bytes of one frame."""
        with open(os.path.join(FRAMES_DIR, name), "rb") as handle:
            return handle.read(PNG_HEADER_BYTES)

    def test_the_directory_holds_only_frames(self):
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertIsNotNone(
                    FRAME_NAME_RE.match(name),
                    msg="%s is not a captured frame" % name)

    def test_the_directory_holds_no_derived_imagery(self):
        # Transition frames are MATERIALISED under build/transitions/,
        # deliberately outside this directory: mixing them in would
        # destroy the frame-count-equals-row-count identity that makes
        # an unpaired frame impossible to overlook.
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertFalse(name.startswith("trans_"))

    def test_the_directory_holds_no_subdirectory(self):
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertTrue(os.path.isfile(
                    os.path.join(FRAMES_DIR, name)))

    def test_the_frame_numbers_are_contiguous_from_one(self):
        numbers = [int(FRAME_NAME_RE.match(name).group(1))
                   for name in self.frame_names]
        self.assertEqual(numbers,
                         list(range(1, len(self.frame_names) + 1)))

    def test_the_counts_agree_across_all_three_artifacts(self):
        # Frames on disk, rows in the record and timeline entries must
        # agree exactly.  One keystroke, one frame, one row.
        self.assertEqual(len(self.frame_names), len(self.rows))
        self.assertEqual(len(self.frame_names), len(self.entries))
        self.assertEqual(len(self.frame_names),
                         self.document["frame_count"])

    def test_every_frame_is_a_png(self):
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertTrue(
                    self.header(name).startswith(PNG_SIGNATURE))

    def test_every_frame_declares_an_image_header(self):
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertEqual(self.header(name)[PNG_IHDR_AT],
                                 b"IHDR")

    def test_every_frame_is_the_capture_geometry(self):
        expected = self.geometry_from_env()
        for name in self.frame_names:
            with self.subTest(name=name):
                width, height = struct.unpack(
                    ">II", self.header(name)[PNG_GEOMETRY_AT])
                self.assertEqual((width, height), expected)

    def test_the_capture_geometry_is_the_x_root(self):
        # 1920x1080 is the root window this pipeline photographs; the
        # game window is 1920x1072 inside it, so a frame of that size
        # would mean the window was captured instead of the root.
        self.assertEqual(self.geometry_from_env(), (1920, 1080))

    def test_no_frame_is_empty(self):
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertGreater(
                    os.path.getsize(os.path.join(FRAMES_DIR, name)),
                    MIN_FRAME_BYTES)


class TestTheTranscriptContract(ArtifactFixture):
    """The captions, against the timeline they were paced by.

    The transcript is the requirement's other half: one entry per frame,
    in the survivor's own voice, timed in VIDEO seconds so a player's
    subtitle track lands on the frame it describes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srt = _read_text(TRANSCRIPT_SRT)
        cls.markdown = _read_text(TRANSCRIPT_MD)
        cls.cues = make_srt.build_cues(
            cls.entries, make_srt.transition_gap(cls.document))

    def timings(self):
        """Every timing line of the committed cue file, in order."""
        return [line for line in self.srt.splitlines()
                if make_srt.SRT_ARROW in line]

    def numbers(self):
        """Every cue number of the committed cue file, in order."""
        found = []
        blocks = self.srt.split("\n\n")
        for block in blocks:
            head = block.strip().splitlines()
            if head:
                found.append(head[0])
        return found

    def test_there_is_one_cue_per_frame(self):
        self.assertEqual(len(self.timings()), len(self.entries))

    def test_the_cue_numbers_are_contiguous_from_one(self):
        self.assertEqual(self.numbers(),
                         [str(number) for number
                          in range(1, len(self.entries) + 1)])

    def test_every_cue_window_is_the_timelines_window(self):
        for entry, timing in zip(self.entries, self.timings()):
            with self.subTest(frame=entry["frame"]):
                expected = (
                    timeline.format_srt_timecode(entry["cue_start"]) +
                    make_srt.SRT_ARROW +
                    timeline.format_srt_timecode(entry["cue_end"]))
                self.assertEqual(timing, expected)

    def test_the_final_cue_ends_at_the_declared_total(self):
        self.assertTrue(self.timings()[-1].endswith(
            timeline.format_srt_timecode(self.document["total"])))

    def test_the_cue_file_has_no_byte_order_mark(self):
        self.assertFalse(_read_bytes(TRANSCRIPT_SRT).startswith(
            b"\xef\xbb\xbf"))

    def test_the_cue_file_has_unix_line_endings(self):
        # A CRLF cue file muxes, but make_srt.py writes LF and the mux
        # warns about a committed artifact whose line ending changed.
        self.assertNotIn(b"\r", _read_bytes(TRANSCRIPT_SRT))

    def test_no_cue_line_carries_trailing_whitespace(self):
        for number, line in enumerate(self.srt.splitlines(), start=1):
            with self.subTest(line=number):
                self.assertEqual(line, line.rstrip())

    def test_every_cue_line_is_wrapped_to_the_caption_width(self):
        # THE CUE CONTRACT: at most CUE_MAX_LINES lines of about
        # forty-two columns.  The width keeps a line inside the picture;
        # the line count keeps a cue readable inside a window that can be
        # as short as the 0.25 s floor.
        for cue in self.cues:
            with self.subTest(frame=cue.frame):
                self.assertGreaterEqual(len(cue.lines), 1)
                self.assertLessEqual(len(cue.lines),
                                     make_srt.CUE_MAX_LINES)
                for line in cue.lines:
                    self.assertLessEqual(len(line),
                                         make_srt.CUE_LINE_WIDTH)

    def test_every_cue_carries_the_whole_sentence(self):
        # TWO REAL DEFECTS MEET HERE, and the committed record has to be
        # clear of both.  A caption used to be TRUNCATED to two lines
        # with an elision mark, which cut the REASON off the end of every
        # long sentence -- and the reason is the requirement: a viewer
        # with the caption track selected is the audience for the
        # in-character record, and "...so I go at first light" was
        # exactly the clause that got dropped.  Then the cap was removed
        # outright and a long cue merely advised about, which shipped 88
        # cues of three to six lines, one of them inside a 250 ms window.
        # So: every cue is the sentence word for word (nothing is cut),
        # AND the sentence was written short enough to fit the geometry
        # (the previous test), which is a property of the SOURCE
        # commentary rather than of any transformation here.
        for cue in self.cues:
            with self.subTest(frame=cue.frame):
                self.assertEqual(
                    " ".join(cue.lines).split(), cue.commentary.split(),
                    msg="the cue is the sentence, word for word")
        self.assertEqual(
            make_srt.CUE_MAX_LINES, 2,
            msg="the caption contract is at most two lines")
        self.assertFalse(
            hasattr(make_srt, "CUE_ELISION"),
            msg=("and there is no elision mark left to reintroduce the "
                 "truncation: a cue that will not fit is refused at "
                 "generation, never shortened"))

    def test_the_markdown_carries_every_sentence_entire(self):
        # Where the reason for an action always is, whatever its caption
        # had room for: the last clause of a long sentence -- "...so I
        # go at first light" -- is readable here in every case.
        for cue in self.cues:
            with self.subTest(frame=cue.frame):
                self.assertIn(cue.commentary, self.markdown)

    def test_the_markdown_has_one_stamp_per_entry(self):
        stamps, entries = make_srt.markdown_counts(self.markdown)
        self.assertEqual(stamps, len(self.entries))
        self.assertEqual(entries, len(self.entries))

    def test_the_markdown_explains_its_timestamps(self):
        self.assertIn(make_srt.markdown_header(), self.markdown)

    def test_the_transcript_is_titled_with_this_records_survivor(self):
        """The committed title names the survivor of THIS session.

        A runtime QA pass found the shipped transcript titled with a
        retired survivor's name: the record had been re-captured, the
        dossier introduced somebody else, and every other layer -- the
        manifest's own sentences, the caption cues, the save file's
        base64 name, the achievements file, lastworld.json -- agreed
        with the dossier while this one heading did not.  The title is
        derived now, and this holds the ARTIFACT to it rather than the
        derivation: the first line of the committed transcript must be
        the name the committed dossier gives, spelled the same way.
        """
        dossier = os.path.join(PLAYTHROUGH, "dossier.md")
        self.assertTrue(os.path.isfile(dossier),
                        msg="the survivor's own account of himself is "
                            "what the transcript is titled from")
        name = make_srt.read_survivor_name(dossier)
        self.assertEqual(
            self.markdown.splitlines()[0],
            "# %s%s" % (name, make_srt.MARKDOWN_TITLE_SUFFIX))
        # And nobody else is introduced anywhere in the two artifacts'
        # generated lines: the header is the only text either file
        # carries that the survivor did not write.
        self.assertIn(name, self.markdown.splitlines()[0])

    def test_both_transcripts_regenerate_from_the_timeline(self):
        # One generation, two files: the human-readable record and the
        # machine-readable cues cannot disagree because they are the
        # same numbers by construction.
        srt, markdown, _ = make_srt.build_transcripts(self.document)
        self.assertEqual(srt, self.srt)
        self.assertEqual(markdown, self.markdown)

    def test_the_transcripts_pass_their_own_validator(self):
        self.assertEqual(
            make_srt.document_problems(self.document, self.entries), [])

    def test_the_entries_pass_the_caption_validator(self):
        # The gate the caption producer applies before it will render a
        # cue at all: the indices run 1..n, every window opens before it
        # closes and runs forward without overlapping, the first opens
        # the film at zero, each lasts exactly as long as its frame is
        # on screen, a gap is present when and only when a transition
        # was charged for it, and every entry carries a sentence in the
        # survivor's voice that a caption can be made from.
        self.assertEqual(
            make_srt.entry_problems(
                self.entries, make_srt.transition_gap(self.document)),
            [])


class TestTheRenderContract(ArtifactFixture):
    """The concat list, the movie and the provenance binding them.

    THE THREE DEFECTS THIS CLASS EXISTS FOR ARE REAL ONES, and each was
    invisible to every other artifact check:

      * The concat list was published BEFORE the encode, so a failed or
        interrupted render left a NEW list beside an OLD movie -- two
        internally valid files describing different sessions, with nothing
        on disk recording that they disagreed.
      * The transition group set had NO PROVENANCE at all: the renderer
        accepted a group because twelve files with the right names and the
        right pixel dimensions existed, and the same twelve names exist at
        the same geometry in every session that flags a given frame.
      * Durations were written stripped of trailing zeros, so the list
        spelled the clamp bounds "0.25" and "10.0" while timeline.json,
        this suite and the report all spell them 0.250 and 10.000.

    So the committed artifacts are now audited for the provenance that
    makes them attributable, not merely for being well formed.
    """

    def setUp(self):
        if not os.path.isfile(CONCAT_LIST):
            self.skipTest("no rendered generation in this checkout")

    def flagged_frames(self):
        """Return every frame index the timeline flags, in order."""
        return [entry["frame"] for entry in self.entries
                if entry.get("transition_after")]

    def test_the_list_has_one_more_file_line_than_durations(self):
        files, durations = render_movie.concat_counts(
            _read_text(CONCAT_LIST))
        self.assertEqual(
            files, durations + 1,
            msg=("the final file line is repeated with no duration; "
                 "without it the last image's duration does not take "
                 "effect and the container truncates"))

    def test_the_list_regenerates_from_the_committed_timeline(self):
        plan = render_movie.plan_render(self.document, None, TIMELINE)
        self.assertEqual(render_movie.format_concat_list(plan),
                         _read_text(CONCAT_LIST))

    def test_a_captured_duration_is_written_at_millisecond_width(self):
        widths = set()
        for line in _read_text(CONCAT_LIST).splitlines():
            if not line.startswith("duration "):
                continue
            widths.add(len(line.split(".", 1)[1]))
        self.assertEqual(
            widths - {render_movie.DURATION_DECIMALS},
            {render_movie.CAPTURE_DECIMALS} if widths else set(),
            msg=("every duration is written at the resolution it was "
                 "computed at -- three decimals for a clamped frame, six "
                 "for a transition share -- and none is stripped"))

    def test_the_clamp_bounds_are_spelled_as_the_timeline_spells_them(self):
        text = _read_text(CONCAT_LIST)
        durations = [entry["duration"] for entry in self.entries]
        if any(abs(one - timeline.FLOOR) < 1e-9 for one in durations):
            self.assertIn("duration 0.250", text)
        if any(abs(one - timeline.CEIL) < 1e-9 for one in durations):
            self.assertIn("duration 10.000", text)

    def test_the_movie_manifest_binds_the_film_to_this_timeline(self):
        if not os.path.isfile(MOVIE_MANIFEST):
            self.skipTest("no movie generation manifest in this checkout")
        record = json.loads(_read_text(MOVIE_MANIFEST))
        self.assertEqual(record["version"], timeline.GENERATION_VERSION)
        self.assertEqual(record["stage"], render_movie.LOCK_NAME)
        self.assertEqual(record["timeline"]["sha256"],
                         timeline.file_digest(TIMELINE))
        self.assertEqual(record["concat_list"]["sha256"],
                         timeline.file_digest(CONCAT_LIST))
        self.assertEqual(record["movie"]["sha256"],
                         timeline.file_digest(MOVIE))
        self.assertEqual(record["capture_count"], len(self.entries))
        self.assertEqual(record["group_count"],
                         len(self.flagged_frames()))

    def test_the_transition_groups_are_attributed_to_this_timeline(self):
        flagged = self.flagged_frames()
        if not flagged:
            self.skipTest("the ceiling never engaged in this session")
        self.assertEqual(
            make_transitions.generation_manifest_problems(
                TRANSITIONS_DIR, TIMELINE, flagged),
            [], msg=("the group set must be attributable to the timeline "
                     "being rendered, group index for group index"))

    def assert_moov_precedes_mdat(self, path):
        """Hold one film to the streaming layout, or say why not."""
        atoms = _top_level_atoms(path)
        kinds = [kind for kind, _, _ in atoms]
        self.assertIn(MOOV_ATOM, kinds,
                      msg="%s carries no moov atom at the top level: %s"
                          % (os.path.basename(path), kinds))
        self.assertIn(MDAT_ATOM, kinds,
                      msg="%s carries no mdat atom at the top level: %s"
                          % (os.path.basename(path), kinds))
        self.assertLess(
            kinds.index(MOOV_ATOM), kinds.index(MDAT_ATOM),
            msg=("%s writes moov AFTER mdat (%s), so a player must "
                 "fetch the tail of the file before it can start.  "
                 "-movflags +faststart is what puts the index first, "
                 "and a mux does not inherit it from its input"
                 % (os.path.basename(path),
                    " ".join("%s@%d(%d)" % (kind.decode("latin-1"),
                                            offset, size)
                             for kind, offset, size in atoms))))

    def test_the_film_is_written_for_streaming(self):
        self.assert_moov_precedes_mdat(MOVIE)

    def test_the_captioned_film_is_written_for_streaming_too(self):
        """The captioned film is the one a viewer actually streams.

        A runtime QA pass measured the shipped pair and found the base
        render front-loaded (`ftyp moov free mdat`) while the captioned
        film was not (`ftyp free mdat moov`): the mux had written a fresh
        container without `-movflags +faststart`, so Chrome needed an
        extra `Range: bytes=3735552-` tail request before it could play
        the distribution artifact at all.  Asserted here, against the
        committed bytes, because this is where a lost flag shows up.
        """
        if not os.path.isfile(CAPTIONED_MOVIE):
            self.skipTest("no captioned film in this checkout")
        self.assert_moov_precedes_mdat(CAPTIONED_MOVIE)

    def test_the_two_generation_manifests_name_the_same_timeline(self):
        for path in (MOVIE_MANIFEST, TRANSCRIPT_MANIFEST):
            if not os.path.isfile(path):
                self.skipTest("no %s in this checkout"
                              % os.path.basename(path))
        movie = json.loads(_read_text(MOVIE_MANIFEST))
        transcript = json.loads(_read_text(TRANSCRIPT_MANIFEST))
        self.assertEqual(
            movie["timeline"]["sha256"],
            transcript["timeline"]["sha256"],
            msg=("the film and the caption track must be paced by ONE "
                 "document, or a player sees cues from another session"))

    def test_no_generation_manifest_carries_a_host_path(self):
        for path in (MOVIE_MANIFEST, TRANSCRIPT_MANIFEST,
                     make_transitions.generation_manifest_path(
                         TRANSITIONS_DIR)):
            if not os.path.isfile(path):
                continue
            with self.subTest(manifest=os.path.basename(path)):
                text = _read_text(path)
                self.assertNotIn(REPO_ROOT, text)
                self.assertNotIn("timestamp", text)

    def test_no_staging_file_survived_into_the_committed_tree(self):
        # .gitignore re-includes everything under playthrough/, so a
        # staging file that outlived its process would be committed as
        # though it were the artifact.
        for directory in (BUILD_DIR, PLAYTHROUGH):
            for name in sorted(os.listdir(directory)):
                with self.subTest(name=name):
                    self.assertFalse(
                        render_movie.is_staging_name(name),
                        msg="%s is a staging leftover" % name)


class TestTheUserdirContract(ArtifactFixture):
    """The engine-written save, and the claims it makes checkable.

    This tree is not authored -- the game creates and owns it -- but it
    is COMMITTED, which is what lets a stranger verify the persistence
    is real, the survivor is one, the ending is legitimate, and no debug
    action was ever bound.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not os.path.isdir(USERDIR):
            raise unittest.SkipTest(
                "no engine-written userdir at %s yet" % USERDIR)
        cls.probe = session.probe_save_resume()
        cls.death = None
        loaded = session.read_lastworld(root=PLAYTHROUGH)
        if not cls.probe.worlds and loaded is not None:
            world, character = loaded
            cls.death = session.assert_death_cleanup_evidence(
                world,
                character,
                manifest_path=MANIFEST,
                root=PLAYTHROUGH,
            )
        cls.world_paths = tuple(
            os.path.join(cls.probe.save_dir, name)
            for name in sorted(os.listdir(cls.probe.save_dir))
            if os.path.isdir(os.path.join(cls.probe.save_dir, name)) and
            not os.path.islink(
                os.path.join(cls.probe.save_dir, name))
        )

    def test_the_save_lives_inside_the_working_tree(self):
        # The whole point of --userdir ./playthrough/userdir/: the save
        # is evidence, and evidence that lives outside the repository
        # cannot be committed with the frames it belongs to.
        self.assertTrue(self.probe.save_dir.startswith(
            os.path.realpath(PLAYTHROUGH) + os.sep))

    def test_there_is_exactly_one_world(self):
        self.assertEqual(len(self.world_paths), 1)

    def test_the_world_holds_exactly_one_character(self):
        # One survivor, one continuous session.  A legitimate death
        # moves that one save into the sole graveyard generation.
        if self.death is not None:
            self.assertEqual(
                os.path.basename(self.death.grave_save),
                self.death.save_stem + session.SAVE_EXTENSION)
            return
        self.assertEqual(len(self.probe.worlds), 1)
        self.assertEqual(len(self.probe.worlds[0].characters), 1)

    def test_the_world_carries_its_own_options(self):
        self.assertEqual(len(self.world_paths), 1)
        self.assertTrue(os.path.isfile(os.path.join(
            self.world_paths[0], session.WORLD_OPTIONS_NAME)))

    def test_the_persistence_matches_the_legitimate_ending(self):
        # The hard rule is that an existing save is CONTINUED rather
        # than replaced.  The only valid non-resumable final shape is
        # the engine-authored death generation proved against the
        # append-only record and both memorials.
        if self.death is not None:
            self.assertGreater(self.death.death_frame, 0)
            self.assertFalse(self.probe.resume)
            return
        self.assertEqual(len(self.probe.worlds), 1)
        self.assertTrue(self.probe.worlds[0].resumable)
        self.assertTrue(self.probe.resume)

    def test_the_engine_state_for_the_ending_is_present(self):
        if self.death is not None:
            for path in (
                    self.death.grave_save,
                    self.death.grave_log,
                    self.death.memorial_json,
                    self.death.memorial_text):
                with self.subTest(path=path):
                    self.assertTrue(os.path.isfile(path))
            return
        self.assertEqual(len(self.probe.worlds), 1)
        self.assertTrue(os.path.isfile(os.path.join(
            self.probe.worlds[0].path, session.SAVE_MASTER_NAME)))

    def test_no_debug_action_is_bound(self):
        # The no-cheating guarantee, discharged against a committed
        # artifact rather than resting on anybody's word: debug,
        # debug_mode and debug_hour_timer ship with no bindings array,
        # and the only place a binding could live is the user override
        # in this userdir.
        sentence = session.assert_no_debug_bindings()
        for action in session.DEBUG_ACTION_IDS:
            self.assertIn(action, sentence)

    def test_the_clock_is_the_fixed_width_form(self):
        # 24_HOUR=24h renders the sidebar clock as "%02d:%02d:%02d",
        # which is what makes the OCR regex deterministic; the 12h
        # default is variable-width with an AM/PM suffix.
        self.assertEqual(self.option(OPTION_24_HOUR),
                         seed_options.CLOCK_FORMAT_WANTED)

    def test_the_sound_is_disabled(self):
        # Matching SDL_AUDIODRIVER=dummy: the game must not contend for
        # an audio device this host does not have.
        self.assertEqual(self.option(OPTION_SOUND),
                         seed_options.BOOL_FALSE)

    def test_the_tileset_is_the_required_one(self):
        self.assertEqual(self.option(OPTION_TILES),
                         seed_options.TILESET_REQUIRED)

    def test_the_terminal_is_the_captured_grid(self):
        self.assertEqual(self.option(seed_options.OPT_TERMINAL_X),
                         str(seed_options.TERMINAL_X_WANTED))
        self.assertEqual(self.option(seed_options.OPT_TERMINAL_Y),
                         str(seed_options.TERMINAL_Y_WANTED))

    def test_the_point_pool_allows_the_point_buy_creator(self):
        # R10 is a POINT-BUY creation, which the creator offers only
        # under a pool that has points to spend.
        self.assertIn(self.option(seed_options.OPT_POINT_POOLS),
                      seed_options.POINT_POOLS_POINT_BUY)

    def option(self, name):
        """One value out of the engine-written options file."""
        for item in json.loads(_read_text(OPTIONS_JSON)):
            if isinstance(item, dict) and item.get("name") == name:
                return item.get("value")
        self.fail("%s is absent from %s" % (name, OPTIONS_JSON))


def _git(*arguments):
    """Run one read-only git command, or return None if it cannot."""
    try:
        result = subprocess.run(
            [GIT, "-C", REPO_ROOT] + list(arguments),
            capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result


class TestTheArtifactsAreTracked(ArtifactFixture):
    """Everything is committed -- proved, not assumed.

    This is the one requirement whose failure is INVISIBLE.  .gitignore
    carries `\\#*`, which matches CDDA's per-character save files, plus
    an unanchored `*.log`; without the terminal `!/playthrough/**`
    negation a `git add` skips them, exits 0, and reports success while
    tracking nothing at all.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        inside = _git("rev-parse", "--is-inside-work-tree")
        if inside is None or inside.returncode != 0:
            raise unittest.SkipTest(
                "not a readable git work tree, so tracking cannot be "
                "checked here")
        cls.probe = session.probe_save_resume()
        cls.death = None
        loaded = session.read_lastworld(root=PLAYTHROUGH)
        if not cls.probe.worlds and loaded is not None:
            world, character = loaded
            cls.death = session.assert_death_cleanup_evidence(
                world,
                character,
                manifest_path=MANIFEST,
                root=PLAYTHROUGH,
            )

    def assert_tracked(self, path):
        """Fail unless git has this exact path in the index."""
        result = _git("ls-files", "--error-unmatch", "--", path)
        self.assertEqual(
            result.returncode, 0,
            msg="%s is not tracked: %s"
                % (path, result.stderr.decode("utf-8", "replace")))

    def test_the_manifest_is_tracked(self):
        self.assert_tracked(MANIFEST)

    def test_the_timeline_is_tracked(self):
        self.assert_tracked(TIMELINE)

    def test_both_transcripts_are_tracked(self):
        self.assert_tracked(TRANSCRIPT_SRT)
        self.assert_tracked(TRANSCRIPT_MD)

    def test_every_frame_is_tracked(self):
        # Not a sample: the requirement is every frame, and the whole
        # point of checking is the one that was missed.
        listed = _git("ls-files", "--", FRAMES_DIR)
        tracked = set(listed.stdout.decode("utf-8").split())
        for name in self.frame_names:
            with self.subTest(name=name):
                self.assertIn("playthrough/frames/" + name, tracked)

    def test_the_character_save_is_tracked(self):
        if not os.path.isdir(USERDIR):
            self.skipTest("no engine-written userdir yet")
        if self.death is not None:
            for path in (
                    self.death.grave_save,
                    self.death.grave_log,
                    self.death.memorial_json,
                    self.death.memorial_text):
                with self.subTest(path=path):
                    self.assert_tracked(path)
            return
        for world in self.probe.worlds:
            for character in world.characters:
                with self.subTest(character=character):
                    self.assert_tracked(
                        os.path.join(world.path, character))

    def test_the_engine_written_options_are_tracked(self):
        if not os.path.isfile(OPTIONS_JSON):
            self.skipTest("no engine-written options file yet")
        self.assert_tracked(OPTIONS_JSON)

    def test_the_requirements_file_is_tracked(self):
        self.assert_tracked(os.path.join(TOOLING, "requirements.txt"))

    def test_the_negation_that_makes_this_possible_is_in_place(self):
        # Named explicitly, because a directory-level ignore added over
        # this tree later would silently break every assertion above:
        # git never descends into an excluded directory to evaluate a
        # negation inside it.
        self.assertIn("!/playthrough/**",
                      _read_text(os.path.join(REPO_ROOT, ".gitignore")))

    def test_the_negation_is_the_LAST_pattern_in_the_file(self):
        # git applies the LAST matching pattern, so a pattern added
        # after the negation re-excludes part of this tree -- and a
        # `git add` would then skip it, exit 0, and report success
        # while tracking nothing.  That failure is invisible in the
        # artifacts themselves, which is why it is asserted here
        # rather than left to a reader of the file.
        #
        # Bytecode, the one thing that plausibly wants re-excluding, is
        # kept out at source instead: env.sh exports
        # PYTHONDONTWRITEBYTECODE=1, every module that imports a
        # sibling sets sys.dont_write_bytecode before doing so, and
        # every documented command passes -B.
        text = _read_text(os.path.join(REPO_ROOT, ".gitignore"))
        patterns = [line for line in text.splitlines()
                    if line.strip() and not line.startswith("#")]
        self.assertEqual(
            patterns[-1], "!/playthrough/**",
            msg="the last pattern in .gitignore is %r; the playthrough "
                "negation has to be last or part of this tree is "
                "silently re-excluded" % patterns[-1])


class TestTheSuiteTouchesNothing(unittest.TestCase):
    """This suite is evidence-handling, so it proves its own restraint.

    A contract test that rewrote the artifact it was checking would
    turn every assertion below it into a tautology, so the restraint is
    asserted rather than intended -- once from this module's source, and
    once from the fingerprint taken before the first test ran.
    """

    def source(self):
        """This module's own text."""
        return _read_text(os.path.abspath(__file__))

    def test_nothing_has_changed_so_far(self):
        after = _fingerprint()
        changed = sorted(path for path in set(BASELINE) | set(after)
                         if BASELINE.get(path) != after.get(path))
        self.assertEqual(changed, [])

    def test_the_fingerprint_covers_the_artifacts(self):
        for path in (MANIFEST, TIMELINE, TRANSCRIPT_SRT,
                     TRANSCRIPT_MD):
            with self.subTest(path=path):
                self.assertIsNotNone(BASELINE.get(path))

    def test_the_fingerprint_covers_every_frame(self):
        for name in os.listdir(FRAMES_DIR):
            with self.subTest(name=name):
                self.assertIsNotNone(
                    BASELINE.get(os.path.join(FRAMES_DIR, name)))

    def test_the_fingerprint_would_notice_a_change(self):
        # The guard is only worth having if it can fire, so a change is
        # simulated in the BASELINE COPY rather than on disk.
        tampered = dict(BASELINE)
        tampered[MANIFEST] = (0, 0)
        self.assertNotEqual(tampered.get(MANIFEST),
                            _fingerprint().get(MANIFEST))

    def test_this_module_opens_nothing_for_writing(self):
        for number, line in enumerate(self.source().splitlines(),
                                      start=1):
            with self.subTest(line=number):
                self.assertNotRegex(line, r"open\([^)]*[\"'][wxa]")

    def called_names(self):
        """Every function name this module actually calls.

        Walked from the AST rather than grepped for, and deliberately:
        a substring scan for "os.remove(" finds the list of forbidden
        names in the test that looks for them, which is how a
        self-referential check fails for no reason at all.  Attribute
        calls are reduced to their final name, so `os.remove` and
        `shutil.rmtree` are both caught however they were imported.
        """
        names = set()
        for node in ast.walk(ast.parse(self.source())):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Attribute):
                names.add(function.attr)
            elif isinstance(function, ast.Name):
                names.add(function.id)
        return names

    def test_this_module_calls_nothing_that_writes(self):
        forbidden = {
            "write", "writelines", "truncate", "flush", "fsync",
            "remove", "unlink", "rename", "replace", "rmtree",
            "makedirs", "mkdir", "chmod", "chown", "symlink", "link",
            "move", "copy", "copy2", "copyfile", "copytree", "utime",
            "write_timeline", "append_row", "append_record",
            "write_transcripts", "publish",
        }
        self.assertEqual(sorted(self.called_names() & forbidden), [])

    def test_this_module_runs_no_producer_command_line(self):
        # A producer's main() would WRITE, and it is reached by a name
        # this module does import -- so the dotted path is what has to
        # be checked.  unittest.main is this file's own entry point and
        # is the only main() a read-only suite may call.
        calls = set()
        for node in ast.walk(ast.parse(self.source())):
            if isinstance(node, ast.Call):
                calls.add(ast.unparse(node.func))
        for name in sorted(calls):
            if name.endswith(".main") or name == "main":
                with self.subTest(call=name):
                    self.assertEqual(name, "unittest.main")

    def test_this_module_runs_no_git_command_that_writes(self):
        # `git ls-files` and `git rev-parse` only read the index.
        source = self.source()
        for token in ("\"add\"", "\"commit\"", "\"checkout\"",
                      "\"reset\"", "\"clean\""):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
