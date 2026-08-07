#!/usr/bin/env python3
"""Append-only JSON Lines writer for playthrough/manifest.jsonl.

One JSON object per line, one line per captured frame, one captured
frame per keystroke.  The manifest is the record that the session
happened: every row ties one keystroke to the PNG it produced, to the
wall-clock instant of that capture, to the sidebar clock as it was
actually read from that PNG, and to the survivor's own reason for
acting.  That record is evidence, and evidence is not rewritten, so this
module only ever appends.

SCHEMA -- exactly six keys, in this order, on every row:

    frame         int       monotonic index from 1, supplied by the
                            caller; this module never generates it
    file          str       "playthrough/frames/frame_%05d.png" from
                            the index, matching what capture.sh wrote
    real_ts       str       UTC wall-clock instant of the capture, one
                            fixed sortable form on every row; supplied
                            by the caller, never defaulted here
    ingame_clock  str|None  the sidebar clock AS READ, or JSON null --
                            the ONLY nullable field in the schema
    action        str       the single keystroke plus enough plain
                            description to be unambiguous
    commentary    str       the survivor's first-person reason for it

Nothing else is permitted, and a row carrying an unexpected key or
missing a required one is refused rather than written.  Durations,
transition flags and caption cue windows belong to
playthrough/timeline.json, the single source of truth for timing;
recording them here as well would create the second source of truth the
pipeline exists to avoid.  Engineering and diagnostic observations
belong to playthrough/TECHNICAL_NOTES.md.

A RECORDED ROW IS NEVER EDITED, AND THIS MODULE HOLDS NO CODE THAT
COULD.  There is no rewrite, no read-modify-write, no truncate and no
"w" mode anywhere: the only write is :func:`append_row`, and the only
other writer is :func:`append_amendment`, which appends to a DIFFERENT
file.  A security review found the previous exception to that rule --
an ``extend_action`` path that rebuilt the whole manifest through a
temporary and renamed it over the original -- and it is gone rather
than hardened, because a mechanism that can rewrite captured evidence
is a defect however carefully it is guarded.

CORRECTIONS ARE AMENDMENTS, IN THEIR OWN APPEND-ONLY LEDGER.  When a
recorded row turns out to overstate what its own capture shows, or to
carry a word the in-character record may not carry, the correction is
appended to playthrough/amendments.jsonl as an AMENDMENT keyed to the
sha256 of the immutable manifest line it corrects:

    amendment      int   1..n, in the order amendments were made
    amended_ts     str   when the amendment was recorded, UTC
    frame          int   the recorded frame the amendment concerns
    field          str   "action" or "commentary" -- nothing else
    source_sha256  str   sha256 of the manifest LINE as recorded,
                         newline included; the binding to history
    recorded       str   the value as the session recorded it
    amended        str   the value a derivative should use instead
    basis          str   what established the amendment
    reason         str   why the recorded value could not stand

Both files are then evidence: the manifest says what was recorded, the
ledger says what was later established and on what basis, and
:func:`resolve_rows` applies an amendment to a derivative ONLY when its
``source_sha256`` still matches the row on disk.  A digest that does
not match is a refusal, not a skip -- a stale amendment means the two
records disagree about history, and that is exactly the condition
nothing downstream may paper over.

``ingame_clock`` IS THE HONESTY FIELD.  ``display::time_string()``
(src/display.cpp:207-218) returns an exact time only when the survivor
has a watch; otherwise one of the coarse phrases from
``display::time_approx()`` (src/display.cpp:159-185), otherwise "???".
Under the seeded 24_HOUR=24h option an exact reading is fixed-width
"%02d:%02d:%02d" (src/calendar.cpp:638-663), which is what makes it
legible at all.  When the clock could not be read the value is None and
serialises as JSON null.  It is never interpolated, never carried
forward from the previous row and never guessed; reconciling an
unreadable or non-monotonic reading is timeline.py's job, downstream and
visibly flagged.  This module records what was seen.

THE WRITE CONTRACT.  A row is not reported as appended until it has been
written, flushed AND forced to the device; a failure anywhere on that
path raises ManifestError rather than being downgraded to a warning,
because the frame-count identity is checked against this file.
``real_ts`` is mandatory and taking it is deliberately the caller's act:
this module will not stamp "now" on the caller's behalf, because the
instant a row is appended is not the instant the frame was captured, and
quietly recording one as the other is fabricated evidence.
:func:`append_row` documents the fields it takes and what it guarantees.

THE COMMAND LINE IS READ-ONLY on purpose -- appending is available to
importers only, so session.py keeps sole ownership of the frame counter
and no shell caller can slip a row in beside it:

    python3 playthrough/tooling/manifest.py verify --require-frames
    python3 playthrough/tooling/manifest.py count
    python3 playthrough/tooling/manifest.py amendments
    python3 playthrough/tooling/manifest.py digests --require-frames

The command line is read-only on purpose: appending is available to
importers only, so that session.py keeps sole ownership of the frame
counter and no shell caller can slip a row in beside it.

Where the record may live is not negotiable.  Every path this module
opens -- for reading as well as for appending -- must resolve inside
the playthrough/ directory derived from this module's OWN location,
with no symlinked component, and is opened with O_NOFOLLOW.
PLAYTHROUGH_MANIFEST, PLAYTHROUGH_FRAMES_DIR and a --manifest argument
are honoured within that tree and refused outside it: a record that an
environment variable could redirect to /etc/passwd, to a device node
or to somebody else's checkout would not be evidence of anything.  The
append itself is serialised with an exclusive fcntl advisory lock that
is MANDATORY -- a lock that cannot be taken refuses the write rather
than proceeding unserialised -- so two writers that both come through
this module cannot interleave a row, and a failed append's rollback
cannot remove bytes the other put there.  Being advisory, it says
nothing about a reader that does not take it, which is why the readers
refuse an unparseable line instead of trusting the lock.

Standard library only -- nothing here needs
playthrough/tooling/requirements.txt.  fcntl makes this POSIX-only,
which matches the pipeline's Linux/X11 scope.  Paths follow
playthrough/tooling/env.sh, the single definition of the artifact
layout, whose PLAYTHROUGH_MANIFEST, PLAYTHROUGH_FRAMES_DIR and
PLAYTHROUGH_FRAME_FORMAT exports are honoured when they are set.
"""

import argparse
import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys


# The schema, in the order rows are written.  Exactly these six keys,
# on every row, always.  The tuple is the authority: the writer, the
# reader and the verifier all derive their expectations from it.
FIELDS = (
    "frame",
    "file",
    "real_ts",
    "ingame_clock",
    "action",
    "commentary",
)

# THE STAGING PREFIX, WHICH NOW ONLY EVER GETS SWEPT.
#
# THERE IS NO WRITER BEHIND IT ANY MORE, AND THAT IS THE POINT.  A
# superseded version of this module could rewrite the record: it wrote
# the whole file to a sibling under this prefix and renamed it, so that
# a row recorded wrongly could be corrected in place.  Code review
# found that facility to be the defect rather than the fix -- a captured
# row is evidence, and 26 committed rows had been rewritten after the
# keystroke that produced them -- so every rewrite entry point, its
# planning and publication halves, and the staging opener were removed.
# What this module can do to playthrough/manifest.jsonl is append one
# validated row, and nothing else; a correction is a note in
# playthrough/TECHNICAL_NOTES.md, which is what the file's own contract
# has always said.
#
# The prefix survives for exactly one reason: sweep_staging() must still
# be able to remove a leftover that the retired writer -- or an
# interruption of it, before it was retired -- left on disk.  These
# siblings live inside playthrough/, which .gitignore re-includes
# wholesale with its terminal `!/playthrough/**` negation, so a survivor
# is an untracked file that `git add -A playthrough/` would commit into
# an evidence tree nobody authored it into.  The prefix matches both the
# deterministic name and the unique names earlier versions produced, so
# one sweep clears every generation of them.
STAGING_PREFIX = ".manifest-"
STAGING_SUFFIX = ".jsonl"
STAGING_OF = "the record"

# One capture per keystroke, indexed from 1.  The five-digit
# zero-padded field is what keeps a lexical sort of the frames
# identical to a numeric one, which is what makes the ffmpeg concat
# list trivially correct -- so an index that would widen the field is
# a real defect and is refused, not silently formatted.
MIN_FRAME_INDEX = 1
MAX_FRAME_INDEX = 99999

# The frame path recorded in the `file` field: repository-relative, so
# the manifest stays valid in any checkout, and built from one format
# shared with env.sh's PLAYTHROUGH_FRAME_FORMAT so that the capturer,
# this writer and the concat list agree byte for byte.
FRAMES_REL_DIR = "playthrough/frames"
FRAME_NAME_FORMAT = "frame_%05d.png"
FRAME_FILE_FORMAT = FRAMES_REL_DIR + "/" + FRAME_NAME_FORMAT

# The one name this module reads or appends to, defined once and used by
# both default_manifest_path() and the target validator below.  The
# record of a session lives at exactly <approved root>/manifest.jsonl
# and nowhere else: see _validated_manifest_target() for why the exact
# path, and not merely containment, is what is required.
MANIFEST_NAME = "manifest.jsonl"

# playthrough/amendments.jsonl -- the amendment ledger, beside the
# record it amends and never inside it.  A SEPARATE FILE is the whole
# point: the manifest keeps the bytes the session wrote, and every
# later correction is an append to this one, so no code path in this
# module has any reason to open the manifest for writing.
AMENDMENTS_NAME = "amendments.jsonl"

# The amendment schema, in the order rows are written.  As with FIELDS,
# this tuple is the authority for the writer, the reader and the
# verifier alike.
AMENDMENT_FIELDS = (
    "amendment",
    "amended_ts",
    "frame",
    "field",
    "source_sha256",
    "recorded",
    "amended",
    "basis",
    "reason",
)

# The only two fields an amendment may concern.  `frame`, `file` and
# `real_ts` are the row's identity and its capture, and `ingame_clock`
# is the reading itself -- amending any of them would be inventing
# evidence rather than correcting a narration, which is the one thing
# this ledger exists NOT to make possible.
AMENDABLE_FIELDS = ("action", "commentary")

# 64 lowercase hex digits, pinned as a shape so that a truncated,
# uppercase or algorithm-swapped digest is a reported problem rather
# than a comparison that silently never matches.
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# playthrough/build/frame_digests.jsonl -- the capture attestation
# ledger, beside the telemetry sidecar it corroborates rather than
# beside the frames it describes.
#
# WHY IT EXISTS.  A security review found that nothing in the record
# attested the BYTES of a captured frame: the sidecar carried the path,
# the geometry, the luminance and the clock, so a same-sized non-blank
# replacement file passed the whole chain, and the interrupted-step
# recovery went further and took a frame's modification time for the
# instant it was captured.  capture.sh now hashes each PNG the moment it
# is published and reports FRAME_SHA256; session.py appends it here, and
# every stage that consumes a frame verifies the bytes against this
# ledger before timing, transitioning, rendering or committing them.
DIGESTS_REL_PARTS = ("build", "frame_digests.jsonl")

DIGEST_FIELDS = (
    "frame",
    "file",
    "sha256",
    "bytes",
    # HOW STRONG THE CLAIM IS, in the row itself.  "capture" means the
    # digest was taken by capture.sh at the instant the frame was
    # published, which is the only attestation that establishes the
    # bytes ARE the captured bytes.  "recovery" means it was measured
    # from the file when an interrupted step was completed.  "commit"
    # means it was sealed after the fact from a committed blob, for a
    # session captured before this ledger existed -- a weaker claim,
    # stated as such rather than dressed up as the strong one.
    "attested",
    "attested_ts",
    # The git object the bytes were sealed from, and the commit that
    # published it, for an "attested": "commit" row.  Both null
    # otherwise.  They exist so that a post-hoc seal names the
    # independent, content-addressed evidence it rests on instead of
    # asserting a digest a reader cannot re-derive.
    "git_blob",
    "git_commit",
)

# The three values `attested` may take, strongest first.
DIGEST_AT_CAPTURE = "capture"
DIGEST_AT_RECOVERY = "recovery"
DIGEST_AT_COMMIT = "commit"
DIGEST_ATTESTATIONS = (DIGEST_AT_CAPTURE, DIGEST_AT_RECOVERY,
                       DIGEST_AT_COMMIT)

# A git object name: 40 hex digits for sha-1, 64 for sha-256 repositories.
GIT_OBJECT_RE = re.compile(r"\A[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")

# Frames are read in blocks when their digest is recomputed: a session
# is hundreds of 1920x1080 PNGs and verifying them must not depend on
# holding one in memory whole.
DIGEST_BLOCK = 65536

# real_ts: the wall-clock instant of the capture, in UTC, to the
# millisecond, in one fixed form on every row so that the column sorts
# lexically as well as chronologically.  Production metadata only --
# video pacing comes from the in-game clock, never from here.
#
# "ONE FIXED FORM" IS A RULE ABOUT THE FILE, AND IT IS CHECKED.  Any
# timezone-aware ISO-8601 spelling is accepted at the door and rewritten
# to this form by canonical_real_ts(), so nothing this module writes can
# break the property; row_field_problems() then reports a STORED value
# that is not in it, which is the only way one could arrive -- a hand
# edit or a foreign tool.  Both halves are needed: without the rewrite a
# legitimate timestamp would be refused, and without the check a
# mixed-format column would sort wrongly while every row in it read
# perfectly well on its own.
REAL_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
REAL_TS_SUFFIX = "Z"
REAL_TS_EXAMPLE = "2026-05-14T09:12:03.481Z"

# An exact reading under the seeded 24_HOUR=24h option: fixed-width
# "%02d:%02d:%02d" (src/calendar.cpp:649).
CLOCK_24H_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

# The RANGE half of that contract, which the shape alone does not carry.
# to_string_time_of_day formats the three fields from a time of day, so
# "24:00:00", "23:60:00" and "99:99:99" are all fixed-width and
# clock-shaped while saying something no clock in this game can show.
# ocr_clock.py enforces exactly these bounds on the reading side and
# DECLINES such a value rather than repairing it into a plausible time;
# the same numbers live here so that the writer cannot label a reading
# 'exact' that its sibling would have refused to emit at all.
CLOCK_MAX_HOUR = 23
CLOCK_MAX_MINUTE = 59
CLOCK_MAX_SECOND = 59

# Bounds on the free-text fields, both about what happens to these
# strings AFTER this file: `action` and `commentary` are copied into
# playthrough/transcript.md and become the SRT cue text.
#
# MAX_FIELD_LENGTH is a refusal and is set far above anything a person
# writes, so it catches machine output and runaway loops without ever
# arguing with legitimate prose.  CUE_ADVISORY_LENGTH is only an
# advisory, and its value comes from the other end of the pipeline: a
# cue occupies its frame's on-screen window, timeline.py caps that
# window at 10 s, and a few hundred characters is what a reader gets
# through in that time.
MAX_FIELD_LENGTH = 2000
CUE_ADVISORY_LENGTH = 400

# The two other shapes to_string_time_of_day can emit: "military"
# "%02d%02d.%02d" (src/calendar.cpp:646) and the 12h default
# "%d:%02d:%02d%sAM/PM" with variable padding (src/calendar.cpp:
# 657-661).  seed_options.py selects 24h precisely because these are
# hostile to a fixed-width read, so a reading in either shape is
# genuine but off-contract and is reported rather than refused.
CLOCK_MILITARY_RE = re.compile(r"^\d{4}\.\d{2}$")
CLOCK_12H_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2} ?[AP]M$")

# The coarse phrases display::time_approx() can return, verbatim and
# in source order (src/display.cpp:159-185), plus the value
# display::time_string() falls back to when the sky is not visible
# (src/display.cpp:216).  A reading that is one of these is a genuine
# observation of the frame, not a failure.
COARSE_TIME_PHRASES = (
    "Around midnight",
    "Around dawn",
    "Around dusk",
    "Dead of night",
    "Night",
    "Early morning",
    "Morning",
    "Around noon",
    "Afternoon",
    "Early evening",
    "Evening",
)
UNKNOWN_TIME_TEXT = "???"

# The classifications classify_ingame_clock() can return.  They exist
# so that timeline.py and verify_artifacts.sh can reason about a
# reading without re-deriving these regular expressions.
CLOCK_NULL = "null"
CLOCK_EXACT = "exact"
CLOCK_NONSTANDARD = "nonstandard"
CLOCK_COARSE = "coarse"
CLOCK_UNKNOWN = "unknown"
CLOCK_UNRECOGNISED = "unrecognised"

# ---------------------------------------------------------------------
# OUT-OF-CHARACTER VOCABULARY: A BLOCKING GATE, AND WHY IT HAD TO BECOME
# ONE.
#
# `commentary` is the survivor's own record.  It goes verbatim into
# playthrough/transcript.md and becomes a caption on the film, and the
# requirement is explicit that engineering and "gamey" observations stay
# out of it and live in playthrough/TECHNICAL_NOTES.md instead.
#
# This used to be a list of SUBSTRINGS checked ADVISORILY: a hit printed
# a warning and the row was appended anyway.  Both halves were wrong.
#
#   * The coverage was short.  It named neither "game", nor "engine",
#     nor a source file, nor pathfinding, nor a move counter, nor
#     cheating -- and every one of those reached the committed record.
#     One row explains that "the game itself is talking to me now",
#     names a C++ source file and a line number, and calls it "the
#     engine's own complaint about its own pathfinding"; another reports
#     that "my move counter went to zero"; two report what "the sidebar"
#     said; the last states "I did not cheat".
#   * Advisory was the wrong strength.  A warning on stderr during a
#     session that produces four hundred rows is a warning nobody reads,
#     and by the time anybody does the row is already evidence -- and
#     evidence is not rewritten afterwards.  So the gate now REFUSES,
#     before the key is sent and before the transcript is published.
#
# WHY PATTERNS RATHER THAN SUBSTRINGS.  The old bluntness is exactly
# what kept it advisory: "frame" matched the four rows that say "the
# frame of the door", which are the survivor's own words about a
# doorway, and refusing those would be wrong.  Each entry below is
# therefore a regular expression written to match the META sense and
# not the in-world one, and the two hardest cases are called out where
# they are handled:
#
#   * `engine` matches `\bengines?\b` and `\bengine's\b`, which does NOT
#     match "engineer" or "engineering" -- Delphine is a mechanical
#     engineer and says so in three rows.  The bluntness that remains is
#     deliberate: she has no reason to name a motor in this session, and
#     "the engine" is how the software gets talked about.
#   * `frame` matches only a frame with a NUMBER or a frame that is
#     counted or indexed.  A door frame is hers.
#
# A word that is genuinely ambiguous and cannot be told apart by pattern
# is BLOCKED rather than allowed, and the note beside it says so, because
# the cost of rephrasing one sentence is nothing and the cost of a meta
# remark in the record is a requirement.
# ---------------------------------------------------------------------

META_PATTERNS = (
    # The software, and the fact that any of this is software.
    ("game", r"\bgames?\b|\bgame's\b|\bgameplay\b|\bgamey\b"),
    ("engine", r"\bengines?\b|\bengine's\b"),
    ("source file", r"\bsource[- ]files?\b|\.cpp\b|\.json\b"),
    ("pathfinding", r"\bpath[- ]?find(?:ing|er|s)?\b"),
    ("debug", r"\bdebug\w*\b"),
    ("cheat", r"\bcheat(?:s|ed|ing|er)?\b|\bgod mode\b"),
    # The interface, as an interface rather than as what she can see.
    ("sidebar", r"\bside[- ]?bars?\b|\bstatus panel\b|\bhud\b"),
    ("move counter", r"\bmoves?[- ]counter\b|\bturns?[- ]counter\b"
                     r"|\bmove points?\b|\bturn counter\b"),
    ("option", r"\boptions?\.json\b|\bthe options? (?:menu|screen|"
               r"file|tab)\b|\bworld options?\b"),
    ("tileset", r"\btile[- ]?sets?\b"),
    # This pipeline, by any of its names.
    ("frame index", r"\bframes?[ _-]?\d+\b|\bframe[ _-](?:number|"
                    r"index|count)\b|\bframe_\d"),
    ("screenshot", r"\bscreen[- ]?shots?\b|\bscreen[- ]?grabs?\b"),
    ("capture", r"\bcaptur\w+\b"),
    ("ocr", r"\bocr\b|\btesseract\b"),
    ("render", r"\bffmpeg\b|\bffprobe\b|\bmoviepy\b|\blibx264\b"
               r"|\bmp4\b|\bcodecs?\b|\bsubtitles?\b|\bcaptions?\b"),
    ("manifest", r"\bmanifests?\b"),
    ("timeline", r"\btimelines?\b"),
    ("keystroke", r"\bkey[- ]?strokes?\b|\bkey[- ]?press(?:es)?\b"),
    ("xdotool", r"\bxdotool\b|\bxvfb\b|\bx11\b|\bsdl\b|\bimagemagick\b"),
    ("pipeline", r"\bpipelines?\b|\bsubprocess\b"),
    ("commit", r"\bcommit(?:s|ted|ting)?\b|\bgit\b|\brepositor(?:y|"
               r"ies)\b"),
    ("requirement", r"\bR1[0-3]\b|\bR[1-9]\b"),
    # THE INTERFACE AS FURNITURE, AND THE CHARACTER SHEET AS ARITHMETIC.
    # This block is the second thing a review found in the committed
    # transcript, and it was invisible to every pattern above: the rows
    # named the input device and the screen furniture she was looking at
    # ("the first key I tried", the cursor moving down a list, a tab, the
    # sex field, the trait page), and they accounted for her own body in
    # the numbers the creator prices it in ("Stat money", "thirty-eight
    # points", "thirty-five per cent off what I can carry", "three
    # points back"), and they named two engine modes by their interface
    # names ("safe mode", "Scores").  None of that is a survivor's
    # sentence -- she has a body, a trade and a list of things wrong with
    # her, not statistics -- so the concepts belong here beside the rest.
    #
    # The same precision rule applies as above, and two cases are worth
    # calling out because the blunt reading would refuse honest prose:
    #
    #   * `keyboard` matches the DEVICE and named keys, not a key that
    #     opens something: "something with keys in it and a clear road"
    #     is a set of car keys and is hers.
    #   * `character sheet` matches a point that is COUNTED or POOLED,
    #     not the idiom: "no point being coy" and "a nip point on the
    #     third floor" are both in the record and both stay.
    #
    # `tab`, `score` and `per cent` are blocked outright, ambiguity and
    # all, under the rule stated above: she has no in-world tab, she says
    # "dozens" rather than "scores", and a percentage is arithmetic
    # somebody else did about her.
    ("cursor", r"\bcursors?\b|\bhighlight(?:ed)?\s+(?:bar|row|line)\b"),
    ("keyboard", r"\bkey[- ]?boards?\b|\bhot[- ]?keys?\b"
                 r"|\barrow keys?\b|\bkeys?\s+(?:list|bindings?|map)\b"
                 r"|\bthe\s+(?:escape|return|enter|tab|space|shift"
                 r"|control|alt|plus|minus|up|down|left|right"
                 r"|apostrophe|at[- ]sign)\s+keys?\b"
                 r"|\bkeys?\s+I\s+(?:tried|pressed|sent|used|thought)"
                 r"\b"),
    ("form control", r"\btabs?\b"
                     r"|\b(?:text|input|entry|name|age|sex)\s+fields?\b"
                     r"|\bthe fields?\b|\bcheck[- ]?box(?:es)?\b"
                     r"|\bdrop[- ]?downs?\b|\bmain menu\b"
                     r"|\bmenu (?:entry|entries|item|items|option"
                     r"|options)\b"),
    ("character sheet",
     r"\bstats?\b|\bstatistics?\b|\bthe traits?\b|\bperks?\b"
     r"|\b(?:trait|traits|skill|skills|stat|stats|attribute"
     r"|attributes|profession|scenario|background)\s+(?:page|pages"
     r"|tab|tabs|screen|list|pool|budget)\b"
     r"|\bskill\s+(?:level|levels|points?)\b"
     r"|\bpoints?\s+(?:pool|pools|budget|left|back|spent|earned"
     r"|remaining)\b"
     r"|\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten"
     r"|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen"
     r"|eighteen|nineteen|twenty|thirty|forty|fifty)\s+points?\b"
     r"|\bpoint[- ]bu(?:y|ild)\b"),
    ("percentage", r"\bper\s?cents?\b|\bpercentages?\b|%"),
    ("game mode", r"\bsafe[- ]?mode\b|\brun[- ]mode\b|\bmove[- ]mode\b"
                  r"|\bscores?\b|\bscore[- ]?boards?\b"),
)

# The compiled table, kept in the declared order so a report reads the
# same way every time.  Names are what a refusal quotes: a concept, not
# a regular expression, because the operator has to rewrite a sentence
# and not debug a pattern.
_META_RES = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in META_PATTERNS)

# Retained because it is the shape a reader of a diagnostic expects and
# because the concept names ARE the vocabulary; every consumer reads it
# through find_meta_vocabulary() rather than matching it itself.
META_VOCABULARY = tuple(name for name, _ in META_PATTERNS)

# ---------------------------------------------------------------------
# THE CLOCK-HONESTY GATE
#
# The defect this exists for is the worst kind the record can carry,
# because every structural check passed straight over it.  Frame 308 of
# the first re-recorded session was captured at 08:05:36 on Thursday,
# May 20 -- the clock and the date line the sidebar actually showed, read
# by ocr_clock.py, stored in the row and copied into the timeline -- and
# its commentary says, in the survivor's own voice: "It is ten past eight
# in the morning on the twenty-eighth of May."  Neither statement is
# true.  The row is internally consistent, the counts all tally, the
# timeline arithmetic is exact, and the film ships a false statement of
# fact in a record whose first requirement is that nothing in it is
# fabricated.
#
# The root cause is a workflow hole rather than a bad datum: the
# commentary is written by whoever is driving the session, from memory,
# and NOTHING held it against the reading on the frame.  So this holds
# it.  Any time of day or calendar date the commentary STATES is parsed
# out and compared with what was actually observed:
#
#   * before the key is sent, against the last reading the driver had in
#     front of them (which is what they were writing from);
#   * at publication, against the reading of that frame itself.
#
# WHAT IS PARSED, AND THE TOLERANCE.  People do not read clocks to the
# second, so an exact match would be absurd.  Two tolerances:
#
#   * an UNHEDGED statement -- "It is ten past eight", "eight o'clock",
#     "20:15" -- must be within TIME_TOLERANCE of the reading.  Three
#     minutes is close enough for how anybody speaks and tight enough
#     that the five-minute misstatement above is caught;
#   * a HEDGED statement -- "around eight", "just gone five", "nearly
#     nine" -- claims less precision and is allowed
#     HEDGED_TIME_TOLERANCE, a quarter of an hour.
#
# A DATE is not approximate at all: the twenty-eighth is not the
# twentieth, so a stated day or month must match the sidebar's date line
# exactly.
#
# AND A PRECISE STATEMENT NEEDS SOMETHING TO CHECK IT AGAINST.  Stating
# a time to the minute on a frame whose clock could not be read is
# refused outright: the survivor is carrying a watch, so an unreadable
# clock means the sidebar was not visible on that screen, and a number
# nobody could see is the definition of invented.  A hedged phrase is
# still allowed there, because "some time after dark" is an honest thing
# to say when no clock is in view.
# ---------------------------------------------------------------------

TIME_TOLERANCE = 180.0
HEDGED_TIME_TOLERANCE = 900.0

# Words that turn a stated time into an approximation.  Matched
# immediately before the time expression, which is where English puts
# them.
TIME_HEDGES = (
    "about", "around", "roughly", "approximately", "nearly", "almost",
    "getting on for", "coming up on", "sometime", "some time", "gone",
    "just gone", "past", "or so", "thereabouts", "somewhere near",
    "close to", "not far off", "the back of",
)

# The spelled-out numbers a person uses for a time of day.  One to
# twelve for the hour, plus the minute words English actually says.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "twentyfive": 25, "twenty-five": 25, "thirty": 30,
    "forty": 40, "forty-five": 45, "fifty": 50,
}

# "in the morning" / "in the afternoon" / "in the evening" / "at night",
# and the bare am/pm forms, which decide which half of the day a
# twelve-hour statement means.
#
# IN TWO CLASSES, AND THE DISTINCTION IS LOAD-BEARING.  Both classes were
# once tested with a bare substring `in`, and both ways that was wrong:
#
#   * "am" matched inside "game", "camp", "same" and "flame", which
#     resolved "Half past eight and the game asked me" to the morning and
#     refused a TRUE statement made at 20:30;
#   * even matched as a whole word, "am" is the commonest verb in the
#     language -- " and I am not starting anything" resolved "ten past
#     five" to 05:10 and refused a true statement made at 17:06.
#
# So a PHRASE ("in the morning") may appear anywhere in the short tail
# after the time, while a SUFFIX ("am", "pm") is only a meridiem where a
# meridiem can go: immediately after the number.
_MERIDIEM_MORNING = ("in the morning", "this morning")
_MERIDIEM_AFTERNOON = (
    "in the afternoon", "this afternoon", "in the evening",
    "this evening", "at night", "tonight", "at dusk",
)
_MERIDIEM_MORNING_SUFFIX = ("am", "a.m.")
_MERIDIEM_AFTERNOON_SUFFIX = ("pm", "p.m.")


def _meridiem_expression(markers, anchored=False):
    """Compile a word-boundary alternation over meridiem markers.

    `anchored` requires the marker at the very start of the tail, which is
    the only position in which a bare "am" or "pm" is a meridiem rather
    than a verb or a stray token.
    """
    alternation = "|".join(
        re.escape(one).replace(r"\ ", r"\s+")
        for one in sorted(markers, key=len, reverse=True))
    if anchored:
        return re.compile(r"\A[\s,.]{0,2}(?:%s)(?![a-z])" % alternation,
                          re.IGNORECASE)
    return re.compile(r"(?<![a-z])(?:%s)(?![a-z])" % alternation,
                      re.IGNORECASE)


_MERIDIEM_MORNING_RE = _meridiem_expression(_MERIDIEM_MORNING)
_MERIDIEM_AFTERNOON_RE = _meridiem_expression(_MERIDIEM_AFTERNOON)
_MERIDIEM_MORNING_SUFFIX_RE = _meridiem_expression(
    _MERIDIEM_MORNING_SUFFIX, anchored=True)
_MERIDIEM_AFTERNOON_SUFFIX_RE = _meridiem_expression(
    _MERIDIEM_AFTERNOON_SUFFIX, anchored=True)

# The month names the sidebar's date line uses (src/display.cpp:193-205
# renders the calendar month, which under the default SHOW_MONTHS is a
# real month name), and the ordinal day words a person writes.
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    # The game's seasons appear in the same line when SHOW_MONTHS is
    # false, so a statement naming one is checked the same way.
    "spring", "summer", "autumn", "winter",
)

_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "twenty-first": 21, "twenty-second": 22,
    "twenty-third": 23, "twenty-fourth": 24, "twenty-fifth": 25,
    "twenty-sixth": 26, "twenty-seventh": 27, "twenty-eighth": 28,
    "twenty-ninth": 29, "thirtieth": 30, "thirty-first": 31,
}

# Markers saying a field was never filled in.  A refusal, like the
# META_PATTERNS gate beside it, but for a different reason and with a
# different remedy: a row is the authoritative record of what one
# keystroke did and why, and every structural check -- the six-field
# schema, the 1..n identity, the frame-set equality -- passes straight
# over a field reading "placeholder".  A meta remark says the wrong sort
# of thing; a sentinel says nothing at all.
PLACEHOLDER_WORDS = (
    "placeholder", "todo", "fixme", "tbd", "xxx", "wip",
)

# Phrases whose presence in an `action` says the field does not describe
# the keystroke: an action that defers to a note elsewhere is not a
# record of what was pressed, it is a promise that the record is
# somewhere else.
UNRECORDED_ACTION_PHRASES = (
    "see note", "see technical_notes", "unknown key", "unknown action",
    "not recorded", "see below", "see above",
)

_SENTINEL_WORD_RE = re.compile(
    r"\b(?:%s)\b" % "|".join(PLACEHOLDER_WORDS), re.IGNORECASE)

# The separator between the derived identity of a keystroke and the
# operator's note about why it was pressed.  session.py owns the
# derivation (session.build_action) and this is the same string, named
# here because this module is the one that writes the field and
# therefore the one that has to be able to recognise its shape.  A
# module-level constant rather than an import: manifest.py is imported
# BY session.py and deliberately imports nothing of it back.
ACTION_SEPARATOR = " -- "

# "press '<key>'", optionally followed by the separator and a reason.
# The key itself is one or more non-quote characters -- which keysym
# names may be SENT is session.py's vocabulary and is validated there
# against the string that reaches xdotool; what is checked here is that
# the row names a keystroke at all.  The note may say anything except
# nothing, and may not carry the separator a second time, which is what
# keeps the identity half unambiguous to session.assert_action_derived.
_ACTION_SHAPE_RE = re.compile(
    r"\Apress '[^'\n]+'(?: -- (?! )(?:(?! -- ).)+)?\Z")


class ManifestError(Exception):
    """A row was refused, or a manifest on disk is malformed.

    Raised in place of writing, so that a bad row never reaches the
    file: a manifest that is wrong is worse than a session that stops,
    because the count identity between the frames directory and this
    file is what proves one capture per keystroke.
    """


# Keys of the warnings already emitted in this process, so that an
# advisory about a standing condition is reported once instead of once
# per row.  Mutated only through _warn_once().
_WARNED = set()


def _warn(message):
    """Report a non-fatal problem on stderr and carry on.

    The prefix matches playthrough_warn() in
    playthrough/tooling/env.sh, so that every stage of the pipeline
    reports in one recognisable form in the session log.
    """
    print("playthrough: WARNING: manifest.py: %s" % message,
          file=sys.stderr, flush=True)


def _warn_once(key, message):
    """Warn about `key` the first time it is seen in this process."""
    if key in _WARNED:
        return
    _WARNED.add(key)
    _warn(message)


def _module_dir():
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _playthrough_dir():
    """Return the absolute playthrough/ directory.

    Derived from this module's own location rather than from the
    working directory, so a helper is correct even when it is invoked
    from somewhere other than the repository root.
    """
    return os.path.dirname(_module_dir())


def repo_root():
    """Return the repository root, from this module's own location.

    playthrough/tooling -> playthrough -> the checkout.  Derived rather
    than read from the environment for the same reason approved_root()
    is: a path a variable could move is not a path anything may be
    reported relative to.
    """
    return os.path.realpath(os.path.dirname(_playthrough_dir()))


def relative_to_repo(path):
    """Return `path` spelled relative to the repository root.

    THE ONLY FORM A MACHINE SUMMARY REPORTS.  An absolute path discloses
    the checkout's location on the host -- and these summaries are
    written into logs that are kept, quoted into reports and read by
    people who have no business knowing where somebody else's clone
    lives.  Every artifact this pipeline touches is inside the checkout,
    so the relative form is complete as well as smaller: it is what a
    reader would type.

    A path that genuinely lies outside the checkout is returned as its
    basename with a marker rather than as a traversal, because "../.."
    still discloses depth and an outside path is a fault to notice, not
    a location to publish.
    """
    if path is None:
        return ""
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    text = str(path)
    if not text:
        return ""
    base = repo_root()
    resolved = os.path.realpath(os.path.abspath(text))
    if resolved == base:
        return "."
    if resolved.startswith(base + os.sep):
        return os.path.relpath(resolved, base)
    return "<outside the checkout>/" + os.path.basename(resolved)


def approved_root(root=None):
    """Return the only directory tree this module may read or write.

    Derived from this module's own location and NEVER from the
    environment.  That is the whole point: PLAYTHROUGH_MANIFEST, a
    --manifest argument and a caller's typo are all untrusted input,
    and a record of what was captured is not evidence if any of them
    can move it somewhere else on the host.  playthrough/ is the root
    because every artifact of this pipeline lives beneath it.

    `root` exists so that a test can point exactly the same rules at a
    temporary directory it owns, which is the only supported way to
    relocate the tree -- it is an explicit argument at the call site,
    not something an environment variable can reach.
    """
    if root is None:
        return os.path.realpath(_playthrough_dir())
    if isinstance(root, os.PathLike):
        root = os.fspath(root)
    if not isinstance(root, str):
        raise ManifestError(
            "the approved root must be a string path, got %s"
            % type(root).__name__)
    if not root.strip():
        raise ManifestError("the approved root must not be empty")
    if "\x00" in root:
        raise ManifestError(
            "the approved root must not contain a NUL byte")
    resolved = os.path.realpath(root)
    if not os.path.isdir(resolved):
        raise ManifestError("no approved root at %s" % resolved)
    return resolved


def _within(path, root):
    """Return True when `path` is `root` itself or lies beneath it."""
    return path == root or path.startswith(root + os.sep)


def _assert_within_root(resolved, label, root=None):
    """Refuse a path that does not resolve inside the approved root.

    The FULLY RESOLVED form is what is tested, so `../` sequences and
    a symlink pointing out of the tree are both caught: /etc/passwd,
    /dev/anything and a sibling checkout are refused rather than
    written.  This is the check that makes it safe to accept a path
    from the environment or the command line at all.

    Returns the approved root, so a caller can pass it straight to
    _assert_no_symlink() without deriving it twice.
    """
    approved = approved_root(root)
    canonical = os.path.realpath(resolved)
    if not _within(canonical, approved):
        raise ManifestError(
            "%s must stay inside %s, but %s resolves to %s"
            % (label, approved, resolved, canonical))
    return approved


def _assert_no_symlink(resolved, root, label):
    """Refuse `resolved` if it or a component below `root` is a link.

    Containment alone is not enough.  A link INSIDE the tree still
    points somewhere else inside the tree, so one planted link could
    redirect every appended row into another artifact -- the frames
    directory, the timeline, the movie -- and the append would look
    entirely successful.  The final component is checked first because
    that is the case that is well defined however the path was
    spelled; the walk then covers every directory between the root and
    the file.
    """
    if os.path.islink(resolved):
        raise ManifestError(
            "%s is a symbolic link: %s.  This module writes files, it "
            "does not follow links to them." % (label, resolved))
    if not _within(resolved, root):
        # The path reaches the tree through a symlinked ancestor ABOVE
        # the root -- a checkout under a linked directory, say.
        # _assert_within_root() has already proved the destination is
        # inside the tree, and components above the root are not this
        # module's business, so there is nothing further to walk.
        return
    current = root
    for part in os.path.relpath(resolved, root).split(os.sep):
        if part in ("", os.curdir):
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ManifestError(
                "%s has a symlinked component at %s; a link there "
                "could redirect the record inside %s"
                % (label, current, root))


def _open_nofollow(path, flags, mode=0o600):
    """Open `path` without following it if it is a symlink.

    O_NOFOLLOW makes the kernel refuse the final component when it is
    a link, which closes the window between the check above and this
    open: a link planted in between fails the syscall instead of being
    followed.  The mode matters only when the file is created, and it
    is private because a manifest row records what the survivor's
    screen showed; git records only the executable bit, so nothing
    about the committed artifact changes.
    """
    try:
        return os.open(path, flags, mode)
    except OSError as err:
        if err.errno in (errno.ELOOP, errno.EMLINK):
            raise ManifestError(
                "the manifest path is a symbolic link: %s.  Refusing "
                "to follow it." % path) from err
        raise ManifestError(
            "could not open the manifest %s: %s" % (path, err)) from err


def default_manifest_path():
    """Return the manifest this pipeline writes and reads.

    Honours PLAYTHROUGH_MANIFEST from playthrough/tooling/env.sh when
    it is set, because that file is the single definition of the
    artifact layout, and otherwise falls back to
    <repository>/playthrough/manifest.jsonl derived from this module's
    location -- so the module is still correct when nothing has been
    sourced, as when it is imported by an ad-hoc test.
    """
    from_env = os.environ.get("PLAYTHROUGH_MANIFEST")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), MANIFEST_NAME)


def default_frames_dir():
    """Return the directory holding one PNG per keystroke.

    Honours PLAYTHROUGH_FRAMES_DIR for the same reason
    default_manifest_path() honours PLAYTHROUGH_MANIFEST.  Derived
    transition images live under playthrough/build/transitions/ and
    never here: the count identity between this directory and the
    manifest is only meaningful while the directory stays pure.
    """
    from_env = os.environ.get("PLAYTHROUGH_FRAMES_DIR")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), "frames")


def _validated_path(value, label):
    """Return `value` as an absolute file path, or raise.

    Every filesystem entry point in this module runs through here, so
    that no unvalidated path is ever handed to open() or os.path.join:
    the value must be a non-empty string or os.PathLike, must not
    carry a NUL byte, and must not name a directory.
    """
    if value is None:
        raise ManifestError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise ManifestError("%s must not be empty" % label)
    if "\x00" in value:
        raise ManifestError("%s must not contain a NUL byte" % label)
    resolved = os.path.abspath(value)
    if os.path.isdir(resolved):
        raise ManifestError(
            "%s names a directory, not a file: %s" % (label, resolved))
    return resolved


def _validated_manifest_target(value, root=None):
    """Return an absolute manifest path this module may touch.

    The shared half of reading and appending, so neither entry point
    can be the lenient one.  Four conditions must hold:

    1. the path resolves inside the approved root (playthrough/,
       derived from this module's location) -- so /etc/passwd, a device
       node and a sibling checkout are refused rather than opened;
    2. it is not reached through a symlinked component, and is not
       itself a link;
    3. it is the EXACT canonical manifest -- ``<approved
       root>/manifest.jsonl`` -- and not merely some path inside the
       tree;
    4. it does not name anything other than a regular file.

    CONDITION 3 IS THE ONE WORTH EXPLAINING.  Containment alone is not
    enough, because everything this pipeline produces lives inside
    playthrough/: with only conditions 1 and 2, a
    ``PLAYTHROUGH_MANIFEST`` or ``--manifest`` naming
    ``playthrough/timeline.json``, or a frame, or the movie, would be
    accepted and APPENDED TO -- JSON Lines rows would be written onto
    the end of another artifact, every write would report success, and
    the artifact would be silently corrupted while the manifest that was
    supposed to record the session did not exist at all.  The record of
    a captured session has exactly one place to live, so that is what
    is required, compared after resolution so a checkout reached through
    a symlinked ancestor still matches.

    The ONLY way to work at another location is the explicit
    call-site-only `root` argument, which relocates the whole approved
    tree for a caller that owns it -- a test in a temporary directory.
    Neither the environment nor the command line can reach it, and even
    then the file must still be named manifest.jsonl directly under that
    root, so the rule being exercised is the production rule rather than
    a weaker one.
    """
    resolved = _validated_path(value, "manifest path")
    approved = _assert_within_root(resolved, "the manifest path", root)
    _assert_no_symlink(resolved, approved, "the manifest path")
    canonical = os.path.join(approved, MANIFEST_NAME)
    if os.path.realpath(resolved) != canonical:
        raise ManifestError(
            "the manifest is %s and nothing else, but %s was given.  "
            "A record of a captured session is not written anywhere "
            "else in the tree: appending rows onto another artifact "
            "would corrupt it and would report success."
            % (canonical, resolved))
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ManifestError(
            "the manifest path is not a regular file: %s" % resolved)
    return resolved


def _validated_manifest_path(value, root=None):
    """Return an absolute manifest path that is safe to append to.

    The parent directory must already exist.  Creating it here would
    let a mistyped path quietly grow a second manifest somewhere else
    in the tree, and directory creation is playthrough_mkdirs()' job
    in playthrough/tooling/env.sh, not this module's.
    """
    resolved = _validated_manifest_target(value, root)
    parent = os.path.dirname(resolved)
    if not os.path.isdir(parent):
        raise ManifestError(
            "the directory for the manifest does not exist: %s"
            % parent)
    return resolved


def assert_appendable(manifest_path=None, root=None):
    """Apply the append-time manifest rules WITHOUT writing anything.

    PUBLIC, and it exists for one caller with one need: session.py has
    to hold itself to this module's rule about WHERE the manifest lives
    BEFORE it does something irreversible, not when it comes to append.
    A keystroke cannot be un-pressed, so a condition that is one
    hundred per cent decidable from the path alone -- the name, the
    containment, the symlink-freedom, the existence of the directory --
    must be decided while the game is still untouched.

    Returns the resolved path, so the caller can keep the same value it
    was checked against rather than deriving it a second time.  Raises
    ManifestError with exactly the diagnostic append_row() would have
    raised later, because this delegates to the same private validator
    rather than restating it: a second, kinder copy of the rule here
    would let a path pass this check and fail that one, which is the
    very ordering defect this function was added to remove.

    Nothing is created, opened, truncated or written.  Whether the file
    can actually be APPENDED to -- a permission, an immutable flag, a
    read-only filesystem -- is a property of the file and the device
    rather than of the path, and session.py pre-flights that separately
    for both of its append targets.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    return _validated_manifest_path(manifest_path, root)


def _validated_directory(value, label, root=None):
    """Return `value` as an absolute directory that exists.

    Held to the approved root as well, because the directory this
    resolves to is the one counted against the manifest: a frames
    directory pointed somewhere else -- by PLAYTHROUGH_FRAMES_DIR, a
    --frames-dir argument or a symlink -- would make the
    one-frame-per-row identity a statement about the wrong pixels.
    """
    if value is None:
        raise ManifestError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise ManifestError("%s must not be empty" % label)
    if "\x00" in value:
        raise ManifestError("%s must not contain a NUL byte" % label)
    resolved = os.path.abspath(value)
    approved = _assert_within_root(resolved, "the %s" % label, root)
    _assert_no_symlink(resolved, approved, "the %s" % label)
    if not os.path.isdir(resolved):
        raise ManifestError("no %s at %s" % (label, resolved))
    return resolved


def _validated_frame(frame):
    """Return the caller's frame index, or raise.

    The index is supplied by session.py, which owns the counter for
    the whole session; this module validates it and never generates,
    increments or repairs it.
    """
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise ManifestError(
            "frame must be an int supplied by the caller, got %s"
            % type(frame).__name__)
    if frame < MIN_FRAME_INDEX:
        raise ManifestError(
            "frame must be >= %d, got %d" % (MIN_FRAME_INDEX, frame))
    if frame > MAX_FRAME_INDEX:
        raise ManifestError(
            "frame %d exceeds %d, which would widen the %s field and "
            "stop a lexical sort of the frames matching a numeric one"
            % (frame, MAX_FRAME_INDEX, FRAME_NAME_FORMAT))
    return frame


def frame_file(frame):
    """Return the repository-relative capture path for `frame`.

    The one place the `file` field's value comes from, so the capturer
    and the manifest cannot disagree about a filename.
    """
    return FRAME_FILE_FORMAT % _validated_frame(frame)


def _check_frame_format_contract():
    """Warn once if env.sh's frame format has drifted from ours.

    env.sh defines PLAYTHROUGH_FRAME_FORMAT so that the capturer, this
    writer and the concat list agree byte for byte.  A drift there
    would break the count identity silently, which is exactly the
    class of failure this pipeline refuses to have.
    """
    from_env = os.environ.get("PLAYTHROUGH_FRAME_FORMAT")
    if from_env and from_env != FRAME_NAME_FORMAT:
        _warn_once(
            "frame-format",
            "PLAYTHROUGH_FRAME_FORMAT is %r but this writer records "
            "%r; the capturer and the manifest have to agree byte "
            "for byte" % (from_env, FRAME_NAME_FORMAT))


def _reject_line_breaks(value, label):
    """Raise if `value` spans more than one line.

    A row is one JSON object on one line.  json.dumps would escape an
    embedded newline rather than break the file, but a multi-line
    keystroke description or clock reading is not a thing that was
    observed, so it is refused at the door.
    """
    if "\n" in value or "\r" in value:
        raise ManifestError(
            "%s must be a single line: one row is one JSON object on "
            "one line" % label)


def _reject_control_characters(value, label):
    """Raise if `value` carries a control character.

    The line-break check above catches the two controls that would
    change this file's shape; this catches the rest, and it exists
    because the manifest is not the end of the road for these strings.
    `action` and `commentary` are copied into playthrough/transcript.md
    and into the SRT cue text, and JSON is perfectly happy to carry a
    NUL as "\\u0000" through both -- so a value that survives the
    manifest intact can still corrupt a caption file, a terminal that
    prints it, or the ffmpeg mux that reads it.

    There is no legitimate source for one either: these fields are a
    keystroke and a sentence a person wrote, neither of which contains
    a NUL, a backspace or an escape.  A value that does is a program
    error or pasted machine output, and both are worth stopping at the
    door rather than embedding in the evidence.
    """
    for char in value:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            raise ManifestError(
                "%s carries the control character U+%04X, which is not "
                "something a keystroke or a sentence contains: these "
                "strings are copied verbatim into "
                "playthrough/transcript.md and the SRT cue text, so a "
                "control character here corrupts a later artifact "
                "rather than this one.  Record the reading or the "
                "reason in plain text" % (label, code))


def _reject_runaway_length(value, label):
    """Raise if `value` is far longer than anything observed can be.

    A generous ceiling rather than a style rule: 2000 characters is
    already several paragraphs, and one keystroke's description or one
    survivor's reason is a sentence.  A value this long is a stuck loop
    or a pasted log, and it would land in an SRT cue that no player
    could read and that no frame is on screen long enough to show.

    Deliberately far above anything a person writes, so it can never
    refuse legitimate prose -- the readability advisory below is what
    speaks to length that is merely long.
    """
    if len(value) > MAX_FIELD_LENGTH:
        raise ManifestError(
            "%s is %d characters, and the limit is %d.  A row describes "
            "ONE keystroke and the reason for it; a value this long is "
            "machine output or a runaway loop, and it becomes an SRT "
            "cue no frame is on screen long enough to display"
            % (label, len(value), MAX_FIELD_LENGTH))


def _validated_text(value, label):
    """Return a required, single-line, non-blank string field."""
    if value is None:
        raise ManifestError(
            "%s is required and must not be None" % label)
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a string, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise ManifestError(
            "%s must not be empty: every row documents a real "
            "keystroke and a real reason for it" % label)
    _reject_line_breaks(value, label)
    _reject_control_characters(value, label)
    _reject_runaway_length(value, label)
    return value


def _validated_file(value, frame):
    """Return the frame path, which must be the canonical one.

    Equality with frame_file() is the guard that keeps one row tied to
    one keystroke capture: a row can never point at a derived
    transition image, at a rescaled copy, or at another row's PNG.
    """
    if not isinstance(value, str):
        raise ManifestError(
            "file must be a string, got %s" % type(value).__name__)
    _reject_line_breaks(value, "file")
    expected = FRAME_FILE_FORMAT % frame
    if value != expected:
        raise ManifestError(
            "file must be %r for frame %d, got %r: one row documents "
            "one keystroke capture, never a derived image"
            % (expected, frame, value))
    _check_frame_format_contract()
    return value


def is_possible_clock(value):
    """True when `value` is a time an in-game clock could display.

    SHAPE AND RANGE, because the shape alone admits "24:00:00".  Named
    to match ocr_clock.py's helper of the same name, which applies the
    identical rule when it decides whether an OCR reading may be
    believed, so the two modules cannot drift into disagreeing about
    what a credible clock looks like.

    This is a question, not a repair: a caller that gets False records
    the value it was given, verbatim, and says so.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not CLOCK_24H_RE.match(text):
        return False
    hour, minute, second = (int(part) for part in text.split(":"))
    return (hour <= CLOCK_MAX_HOUR and
            minute <= CLOCK_MAX_MINUTE and
            second <= CLOCK_MAX_SECOND)


def classify_ingame_clock(value):
    """Describe a clock reading without altering it.

    Returns CLOCK_NULL for None, CLOCK_EXACT for the contracted
    fixed-width 24h form, CLOCK_NONSTANDARD for a genuine clock in the
    military or 12h shape, CLOCK_COARSE for one of the phrases a
    survivor without a watch sees, CLOCK_UNKNOWN for "???", and
    CLOCK_UNRECOGNISED for anything else -- which is information, not
    grounds for discarding the reading.

    A fixed-width value that is out of range -- "24:00:00",
    "23:60:00" -- is CLOCK_UNRECOGNISED rather than CLOCK_EXACT.  The
    label is the point: 'exact' is what timeline.py, verify_artifacts.sh
    and the report read as "a clock that can be believed", and a
    self-contradictory row (`"ingame_clock": "24:00:00", "clock_kind":
    "exact"`) misdescribes the evidence even when nothing downstream
    trusts the label.  The reading itself is still recorded exactly as
    it was given; only the description of it is honest.
    """
    if value is None:
        return CLOCK_NULL
    if not isinstance(value, str):
        raise ManifestError(
            "a clock reading is a string or None, got %s"
            % type(value).__name__)
    text = value.strip()
    if CLOCK_24H_RE.match(text):
        if is_possible_clock(text):
            return CLOCK_EXACT
        return CLOCK_UNRECOGNISED
    if CLOCK_MILITARY_RE.match(text) or CLOCK_12H_RE.match(text):
        return CLOCK_NONSTANDARD
    if text in COARSE_TIME_PHRASES:
        return CLOCK_COARSE
    if text == UNKNOWN_TIME_TEXT:
        return CLOCK_UNKNOWN
    return CLOCK_UNRECOGNISED


def _validated_ingame_clock(value):
    """Return the clock reading exactly as it was read, or None.

    None is a success, not a defect: it is how a clock that could not
    be read is recorded, and it serialises as JSON null.  No default
    is ever substituted, no neighbouring row is ever consulted, and an
    unrecognised reading is kept verbatim with a warning rather than
    refused -- refusing it would pressure the caller into inventing a
    value, which is the one thing that must never happen here.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(
            "ingame_clock must be a string or None, got %s"
            % type(value).__name__)
    if not value.strip():
        raise ManifestError(
            "ingame_clock must not be blank: pass None when the clock "
            "could not be read, which records JSON null")
    _reject_line_breaks(value, "ingame_clock")
    kind = classify_ingame_clock(value)
    if kind == CLOCK_UNRECOGNISED and CLOCK_24H_RE.match(value.strip()):
        # Clock-shaped but impossible.  Called out separately because
        # the cause is different and so is the remedy: ocr_clock.py
        # declines such a value outright, so one that reaches this
        # writer came from a hand transcription of the frame and the
        # frame is what should be re-read.
        _warn(
            "ingame_clock %r is fixed-width but states a time no "
            "in-game clock can show (hour <= %d, minute and second "
            "<= %d); recorded verbatim and NOT repaired into a "
            "plausible time, and left for timeline.py to reconcile.  "
            "ocr_clock.py declines such a reading, so re-read the "
            "frame rather than trusting this value"
            % (value, CLOCK_MAX_HOUR, CLOCK_MAX_SECOND))
    elif kind == CLOCK_UNRECOGNISED:
        _warn(
            "ingame_clock %r matches no known form; recorded verbatim "
            "and left for timeline.py to reconcile" % value)
    elif kind == CLOCK_NONSTANDARD:
        _warn_once(
            "clock-format",
            "ingame_clock %r is a clock but not the fixed-width 24h "
            "form; seed_options.py sets 24_HOUR=24h so that every "
            "reading is fixed width" % value)
    return value


def find_meta_vocabulary(text):
    """Return the out-of-character CONCEPTS `text` carries, in order.

    THE ONE IMPLEMENTATION.  session.py refuses a commentary before the
    key is sent and make_srt.py refuses one before the transcript is
    published, and both ask this -- so the gate cannot be stricter in one
    place than another, and a sentence that passes at write time cannot
    fail at publication time.

    Each concept is matched by a pattern written for the meta sense
    (see META_PATTERNS): "engineer" is not "engine", and the frame of a
    door is not frame 308.
    """
    if not isinstance(text, str):
        return []
    return [name for name, expression in _META_RES
            if expression.search(text)]


def meta_vocabulary_problem(text, label="commentary"):
    """Return the refusal for an out-of-character `text`, or None.

    One message, used by every consumer, naming the concepts found and
    where the observation belongs instead.  Returning None rather than
    raising keeps it usable both as a validator (raise) and as a reporter
    (collect into a problem list).
    """
    hits = find_meta_vocabulary(text)
    if not hits:
        return None
    return (
        "%s reads as an engineering observation rather than the "
        "survivor's own voice: it carries %s.  This is REFUSED rather "
        "than warned about, because the sentence goes verbatim into "
        "playthrough/transcript.md and becomes a caption on the film, "
        "and a record that has already been written is not rewritten "
        "afterwards.  Meta and 'gamey' remarks belong in "
        "playthrough/TECHNICAL_NOTES.md; say what the survivor saw and "
        "why she acted.  The text was: %r"
        % (label, ", ".join(hits), text))


# The three shapes a stated time of day takes, most specific first.  Each
# leaves the hedge (if any) in group "hedge" so the tolerance can be
# chosen from the same match that produced the time.
_HEDGE_ALTERNATION = "|".join(
    re.escape(one) for one in sorted(TIME_HEDGES, key=len, reverse=True))
_NUMBER_ALTERNATION = "|".join(
    re.escape(one) for one in sorted(_NUMBER_WORDS, key=len,
                                     reverse=True))

# "20:15", "20:15:30", "8:15" -- digits, which are unambiguous.
_TIME_DIGITS_RE = re.compile(
    r"(?P<hedge>(?:%s)\s+)?\b(?P<hour>\d{1,2}):(?P<minute>\d{2})"
    r"(?::\d{2})?\b" % _HEDGE_ALTERNATION, re.IGNORECASE)

# "ten past eight", "quarter past eight", "half past eight",
# "six minutes past eight", "twenty to nine", "five to five".
_TIME_RELATIVE_RE = re.compile(
    r"(?P<hedge>(?:%s)\s+)?\b(?P<offset>%s|quarter|half)"
    r"(?:\s+minutes?)?\s+"
    r"(?P<direction>past|to|before|after)\s+(?P<hour>%s|\d{1,2})\b"
    % (_HEDGE_ALTERNATION, _NUMBER_ALTERNATION, _NUMBER_ALTERNATION),
    re.IGNORECASE)

# "eight o'clock", "eight in the morning", "five in the afternoon",
# "eleven o'clock and five minutes".
_TIME_HOUR_RE = re.compile(
    r"(?P<hedge>(?:%s)\s+)?\b(?P<hour>%s|\d{1,2})\s*"
    r"(?P<tail>o'clock|o clock|in the morning|in the afternoon|"
    r"in the evening|at night|am|pm|a\.m\.|p\.m\.)"
    r"(?:\s+and\s+(?P<extra>%s|\d{1,2})\s+minutes?)?"
    % (_HEDGE_ALTERNATION, _NUMBER_ALTERNATION, _NUMBER_ALTERNATION),
    re.IGNORECASE)

# "the twenty-eighth of May", "the 28th of May", "May 28", "May the 28th".
_DATE_OF_RE = re.compile(
    r"\b(?:the\s+)?(?P<day>%s|\d{1,2})(?:st|nd|rd|th)?\s+of\s+"
    r"(?P<month>%s)\b"
    % ("|".join(re.escape(one) for one in sorted(
        _ORDINAL_WORDS, key=len, reverse=True)),
       "|".join(_MONTH_NAMES)), re.IGNORECASE)
_DATE_MONTH_FIRST_RE = re.compile(
    r"\b(?P<month>%s)\s+(?:the\s+)?(?P<day>%s|\d{1,2})(?:st|nd|rd|th)?"
    r"\b"
    % ("|".join(_MONTH_NAMES),
       "|".join(re.escape(one) for one in sorted(
           _ORDINAL_WORDS, key=len, reverse=True))), re.IGNORECASE)

# ---------------------------------------------------------------------
# WHAT THE GATE ADJUDICATES, AND WHY IT IS ONLY THIS
#
# It adjudicates a time or a date that the sentence ASSERTS IS THE CASE
# NOW.  Nothing else -- and that restriction is what makes the gate sound
# rather than merely strict.
#
# The unrestricted version of this check was run against the 395 rows of
# the first re-recorded session and reported 43 problems, of which ONE
# was the real defect.  The other 42 were honest English:
#
#   * reminiscence -- "I was the one they phoned at three in the
#     morning", four rows of it during character creation, about a life
#     twenty years before the Cataclysm;
#   * generalisation -- "layers are the whole argument at four in the
#     morning when the house is the same temperature as the yard";
#   * retrospect -- "the blanket still folded back exactly where I left
#     it at half past eight", "that lamp has been burning since eight
#     o'clock";
#   * intention -- "three hours puts me at ten past eight";
#   * a span -- "eleven to five in the afternoon".
#
# None of those states what time it is.  Refusing them would make the
# record unwritable in a human voice, and a gate that cries wolf 42 times
# out of 43 is a gate somebody switches off -- which is exactly the
# failure the advisory voice check already demonstrated.  So the scope is
# narrow ON PURPOSE, and the module is explicit about the consequence: a
# time MENTIONED without asserting the present is not adjudicated.  What
# covers that ground instead is the discipline the pipeline enforces
# structurally -- the sentence is written while looking at the frame, the
# reading of that frame is committed in the row beside it, and both are
# published -- rather than a check that would have to guess at tense.
# ---------------------------------------------------------------------

# "it is", "it's", "it is now", "the clock reads/says/shows", "the time
# is", "today is", "the date is".  Present tense, first person or
# instrument: the forms in which a person states the case rather than
# recalling, planning or measuring one.  Deliberately excludes "it has
# been", "it was", "since", "until" and "at", which are the four ways
# every false positive above got in.
_ASSERTION_RE = re.compile(
    r"(?<![a-z])(?:it\s+is\s+now|it\s+is|it's|the\s+clock\s+"
    r"(?:reads|says|shows|said)|the\s+time\s+is|the\s+time\s+reads|"
    r"today\s+is|the\s+date\s+is|the\s+day\s+is)(?![a-z])",
    re.IGNORECASE)

# How far past the assertion the statement may begin.  Short enough that
# "It is cold, and I remember being phoned at three in the morning" is
# not read as a statement of the current time, and long enough that "It
# is ten past eight in the morning" is.
ASSERTION_TIME_WINDOW = 16

# The same, for a date, measured from the end of the time the assertion
# carried (or from the assertion itself when it carried none) so that
# "It is ten past eight in the morning on the twenty-eighth of May"
# reaches its date clause.
ASSERTION_DATE_WINDOW = 24


def _word_number(value):
    """Return an integer for a digit string or a number word, or None."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in _NUMBER_WORDS:
        return _NUMBER_WORDS[text]
    if text in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[text]
    if text == "quarter":
        return 15
    if text == "half":
        return 30
    return None


def _stated_seconds(hour, minute, tail):
    """Return seconds since midnight for a 12- or 24-hour statement.

    A twelve-hour statement is ambiguous by nature, so BOTH readings are
    returned and the comparison accepts whichever is closer -- that is the
    honest treatment: "five in the afternoon" is 17:00, but a bare "five"
    could be either, and refusing a sentence for the ambiguity of English
    would catch nothing real.
    """
    if hour is None or not 0 <= hour <= 23:
        return ()
    minute = 0 if minute is None else minute
    if not 0 <= minute <= 59:
        return ()
    text = tail or ""
    base = hour % 12
    morning = base * 3600 + minute * 60
    afternoon = (base + 12) * 3600 + minute * 60
    if (_MERIDIEM_AFTERNOON_RE.search(text) or
            _MERIDIEM_AFTERNOON_SUFFIX_RE.search(text)):
        return (afternoon,)
    if (_MERIDIEM_MORNING_RE.search(text) or
            _MERIDIEM_MORNING_SUFFIX_RE.search(text)):
        return (morning,)
    if hour >= 13:
        return (hour * 3600 + minute * 60,)
    return (morning, afternoon)


def _time_from_digits(match, text):
    """Return (candidates, hedged) for a digit reading, or None."""
    hour = _word_number(match.group("hour"))
    minute = _word_number(match.group("minute"))
    if hour is None or hour > 23:
        return None
    tail = text[match.end():match.end() + 20]
    explicit = hour >= 13 or match.group("hour").startswith("0")
    if explicit:
        candidates = (hour * 3600 + (minute or 0) * 60,)
    else:
        candidates = _stated_seconds(hour, minute, tail)
    if not candidates:
        return None
    return (candidates, bool(match.group("hedge")))


def _time_from_relative(match, text):
    """Return (candidates, hedged) for "ten past eight", or None."""
    offset = _word_number(match.group("offset"))
    hour = _word_number(match.group("hour"))
    if offset is None or hour is None:
        return None
    direction = match.group("direction").lower()
    if direction in ("to", "before"):
        hour = (hour - 1) % 24
        minute = 60 - offset
    else:
        minute = offset
    if minute == 60:
        minute = 0
        hour = (hour + 1) % 24
    candidates = _stated_seconds(
        hour, minute, text[match.end():match.end() + 20])
    if not candidates:
        return None
    return (candidates, bool(match.group("hedge")))


def _time_from_hour(match, _text):
    """Return (candidates, hedged) for "eight o'clock", or None."""
    hour = _word_number(match.group("hour"))
    if hour is None:
        return None
    minute = _word_number(match.group("extra")) or 0
    if not 0 <= minute <= 59:
        minute = 0
    candidates = _stated_seconds(hour, minute, match.group("tail"))
    if not candidates:
        return None
    return (candidates, bool(match.group("hedge")))


_TIME_SHAPES = (
    (_TIME_DIGITS_RE, _time_from_digits),
    (_TIME_RELATIVE_RE, _time_from_relative),
    (_TIME_HOUR_RE, _time_from_hour),
)


def _earliest_time_in(window):
    """Return (offset, end, reading) for the first time in `window`.

    All three shapes are tried and the one that begins earliest wins, so
    the statement adjudicated is the one the assertion actually
    introduced rather than whichever pattern happened to be tried first.
    """
    best = None
    for expression, reader in _TIME_SHAPES:
        match = expression.search(window)
        while match is not None:
            reading = reader(match, window)
            if reading is not None:
                if best is None or match.start() < best[0]:
                    best = (match.start(), match.end(), reading)
                break
            match = expression.search(window, match.start() + 1)
    return best


def _earliest_date_in(window):
    """Return (offset, (day, month)) for the first date in `window`."""
    best = None
    for expression in (_DATE_OF_RE, _DATE_MONTH_FIRST_RE):
        for match in expression.finditer(window):
            day = _word_number(match.group("day"))
            if day is not None and not 1 <= day <= 31:
                continue
            if best is None or match.start() < best[0]:
                best = (match.start(), (day, match.group("month").lower()))
            break
    return best


def stated_times(text):
    """Return each time of day `text` ASSERTS, as (seconds, hedged).

    `seconds` is a tuple of the candidate readings (two for an ambiguous
    twelve-hour statement, one otherwise) and `hedged` says whether the
    sentence claimed precision.

    ONLY AN ASSERTION OF THE PRESENT IS RETURNED -- a time introduced by
    "it is", "it's", "the clock reads" or "the time is", and beginning
    within ASSERTION_TIME_WINDOW characters of it.  A time merely
    mentioned is NOT returned: see the note above _ASSERTION_RE for the
    42 honest sentences that taught this restriction, and for what covers
    that ground instead.

    Read-only, and conservative twice over: only the three shapes above
    are recognised, so an unrecognised way of saying a time is not
    checked rather than guessed at.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    found = []
    for anchor in _ASSERTION_RE.finditer(text):
        window = text[anchor.end():
                      anchor.end() + ASSERTION_TIME_WINDOW + 64]
        reading = _earliest_time_in(window)
        if reading is None or reading[0] > ASSERTION_TIME_WINDOW:
            continue
        found.append(reading[2])
    return found


def stated_dates(text):
    """Return each (day, month) `text` ASSERTS.  Read-only.

    `day` may be None for a statement that names only a month.  The month
    is a lower-cased string and the day an integer, which is what
    observed_date_parts() returns for the sidebar's own line, so the
    comparison is between like and like.

    ONLY AN ASSERTION OF THE PRESENT is returned, on the same principle
    as stated_times() -- reached either directly ("it is the twentieth of
    May", "today is May 20") or across the time the assertion carried
    ("it is ten past eight in the morning on the twenty-eighth of May"),
    which is the shape the false frame-308 statement took.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    found = []
    for anchor in _ASSERTION_RE.finditer(text):
        reach = (ASSERTION_TIME_WINDOW + ASSERTION_DATE_WINDOW + 96)
        window = text[anchor.end():anchor.end() + reach]
        reading = _earliest_time_in(window)
        start = 0
        if reading is not None and reading[0] <= ASSERTION_TIME_WINDOW:
            start = reading[1]
        stated = _earliest_date_in(window[start:])
        if stated is None or stated[0] > ASSERTION_DATE_WINDOW:
            continue
        found.append(stated[1])
    return found


def observed_date_parts(date_text):
    """Return (day, month) read out of a sidebar date line, or None.

    The line is the engine's own -- "Thursday, May 20" under the default
    SHOW_MONTHS, or a season and a day number when it is off
    (src/display.cpp:193-205) -- and this reads whichever it is without
    interpreting anything else.  None means the line said nothing this
    can compare, which is treated as "cannot check" and never as
    agreement.
    """
    if not isinstance(date_text, str) or not date_text.strip():
        return None
    lowered = date_text.lower()
    month = None
    for name in _MONTH_NAMES:
        if re.search(r"\b%s\b" % name, lowered):
            month = name
            break
    day = None
    digits = re.search(r"\b(\d{1,2})\b", lowered)
    if digits:
        day = int(digits.group(1))
    if month is None and day is None:
        return None
    return (day, month)


def clock_seconds_of_day(clock):
    """Return seconds since midnight for an exact HH:MM:SS reading.

    None for anything that is not one -- a coarse phrase, "???", an
    empty reading -- because those are readings that cannot be compared
    with a stated time rather than readings that disagree with one.
    """
    if not isinstance(clock, str):
        return None
    text = clock.strip()
    if not CLOCK_24H_RE.match(text):
        return None
    hour, minute, second = (int(part) for part in text.split(":"))
    if hour > CLOCK_MAX_HOUR or minute > CLOCK_MAX_MINUTE:
        return None
    if second > CLOCK_MAX_SECOND:
        return None
    return hour * 3600 + minute * 60 + second


def _observed_clocks(*readings):
    """Return the distinct comparable readings among `readings`."""
    seen = []
    for reading in readings:
        seconds = clock_seconds_of_day(reading)
        if seconds is not None and (seconds, reading) not in seen:
            seen.append((seconds, reading))
    return seen


def clock_honesty_problems(commentary, clock, date_text,
                           label="commentary", check_dates=True,
                           also_clock=None, also_date=None):
    """Report every time or date `commentary` states that is not so.

    THE GATE THE FALSE FRAME-308 STATEMENT WALKED PAST.  Returns a list
    of problems; empty means every time and date the sentence ASSERTS
    agrees with a reading that was actually observed, or that it asserts
    none.  What counts as an assertion is deliberately narrow, and the
    note above _ASSERTION_RE says why at length.

    :param commentary: the survivor's own words.
    :param clock: the reading the sentence's author had in front of them
        -- the previous frame's, since the commentary explains why the
        next key is about to be pressed.
    :param date_text: the sidebar date line for the same frame.
    :param label: what a message calls the field.
    :param check_dates: False says THE CALLER HOLDS NO DATE EVIDENCE AT
        ALL, which is different in kind from a date line that could not
        be read.  The manifest schema carries no date column, so a
        standalone audit of that file has no channel through which a date
        could have been observed and leaves date statements
        unadjudicated; the write-time gate and the publication gate both
        do have one (the telemetry sidecar and the timeline's
        `ingame_date`), so for them a missing line means the survivor
        could not see a date, and stating one is refused.
    :param also_clock: a SECOND observed reading the statement may agree
        with instead -- the frame the caption is displayed over, which the
        auditing callers have and the writing caller does not, because at
        write time the key has not been sent yet.  Both readings are
        observed and both are committed, so agreeing with either is
        honest; the asymmetry only ever makes the WRITE-time gate the
        stricter of the two, which is the safe direction and the better
        discipline (say what the frame shows, not what it is about to).
    :param also_date: the same, for the date line.
    """
    problems = []
    if not isinstance(commentary, str) or not commentary.strip():
        return problems
    observed = _observed_clocks(clock, also_clock)
    for candidates, hedged in stated_times(commentary):
        tolerance = HEDGED_TIME_TOLERANCE if hedged else TIME_TOLERANCE
        if not observed:
            if hedged:
                continue
            problems.append(
                "%s states a time of day, but the clock on the frame it "
                "belongs to was %s.  A precise time on a frame whose "
                "sidebar could not be read is a number nobody could "
                "see: say what the survivor could actually tell (a "
                "hedged phrase is fine -- \"some time after dark\"), or "
                "read the clock off the frame.  The text was: %r"
                % (label, "not read at all" if not (clock or "").strip()
                   else "the coarse reading %r" % clock, commentary))
            continue
        best, against = min(
            ((abs(candidate - seconds), reading)
             for candidate in candidates for seconds, reading in observed),
            key=lambda pair: pair[0])
        if best <= tolerance:
            continue
        problems.append(
            "%s states %s, but the clock on that frame read %s -- %s "
            "out, past the %s allowed for %s statement.  The reading of "
            "the frame is authoritative; nothing in this record is "
            "written from memory.  The text was: %r"
            % (label,
               " or ".join(_format_seconds(one) for one in candidates),
               against, _format_seconds(int(best)),
               _format_seconds(int(tolerance)),
               "a hedged" if hedged else "an exact",
               commentary))
    if not check_dates:
        return problems
    observed_date = observed_date_parts(date_text)
    alternate_date = observed_date_parts(also_date)
    for day, month in stated_dates(commentary):
        if observed_date is None and alternate_date is None:
            problems.append(
                "%s states a calendar date, but the sidebar's date line "
                "was not read on that frame, so there is nothing to "
                "check it against.  A date the survivor could not see "
                "is not recorded as though she could.  The text was: %r"
                % (label, commentary))
            continue
        # Agreeing with EITHER observed line is honest, on the same
        # footing as a time: both were read off a captured frame and both
        # are committed.  The message names the line that came closest.
        candidates = [(observed_date, date_text),
                      (alternate_date, also_date)]
        best = None
        for parts, line in candidates:
            if parts is None:
                continue
            seen_day, seen_month = parts
            month_wrong = bool(
                month is not None and seen_month is not None and
                month != seen_month)
            day_wrong = bool(
                day is not None and seen_day is not None and
                day != seen_day)
            score = int(month_wrong) + int(day_wrong)
            if best is None or score < best[0]:
                best = (score, month_wrong, day_wrong, line)
        if best is None or best[0] == 0:
            continue
        _, month_wrong, day_wrong, line = best
        if month_wrong:
            problems.append(
                "%s states the month as %r, but the sidebar's date line "
                "on that frame read %r.  A date is not approximate.  "
                "The text was: %r"
                % (label, month, line, commentary))
        if day_wrong:
            problems.append(
                "%s states the day of the month as %d, but the "
                "sidebar's date line on that frame read %r.  A date is "
                "not approximate: the twenty-eighth is not the "
                "twentieth.  The text was: %r"
                % (label, day, line, commentary))
    return problems


def _format_seconds(total):
    """Render seconds since midnight, or a duration, as HH:MM:SS."""
    total = int(total)
    return "%02d:%02d:%02d" % (total // 3600, (total % 3600) // 60,
                               total % 60)


def find_placeholder_words(text):
    """Return the placeholder markers in `text`, sorted.

    Whole-word and case-insensitive, so ordinary prose is not caught.
    Like :func:`find_meta_vocabulary` a hit is a refusal, and the two are
    kept separate because the remedy differs: a sentinel means the field
    was never filled in and has to be written, while a meta remark is a
    real observation recorded in the wrong place.
    """
    if not isinstance(text, str):
        return []
    return sorted({match.group(0).lower()
                   for match in _SENTINEL_WORD_RE.finditer(text)})


def find_unrecorded_action_phrases(text):
    """Return the phrases saying an `action` records no keystroke.

    Case-insensitive substring matching, because these are phrases
    rather than words.  An action that defers to a note elsewhere, or
    names an unknown key, is not a record of what was pressed.
    """
    if not isinstance(text, str):
        return []
    lowered = text.lower()
    return sorted({phrase for phrase in UNRECORDED_ACTION_PHRASES
                   if phrase in lowered})


def action_shape_problem(action, label):
    """Report an `action` that does not name one keystroke, or None.

    THE SHAPE THE RECORD IS WRITTEN IN, ENFORCED WHERE IT IS WRITTEN.
    session.py derives the identity half of every action from the
    validated string that reaches xdotool -- `press '<key>'`, optionally
    followed by ' -- ' and the operator's reason -- precisely so that a
    row cannot name a key that was not sent.  This writer accepted any
    non-empty text, though, so the guarantee lived entirely in the
    caller: a runtime QA pass recorded that as a defence-in-depth gap,
    unreachable through `session.py step` and open to anything else that
    imports this module.

    The check is deliberately about SHAPE and not about vocabulary.  Which
    keysym names may be sent is session.py's question, and duplicating its
    table here would give the pipeline two answers to it; that a row names
    a keystroke at all is this module's, because this module is what
    writes the row.

    Kept separate from :func:`sentinel_problems` and applied by
    :func:`build_row` alone, not by the READER: the committed record is
    419 rows of exactly this shape, and a reader that refused anything
    else would turn a foreign row into an unreadable manifest rather than
    a reported one.
    """
    if not isinstance(action, str):
        return None
    text = action.strip()
    if _ACTION_SHAPE_RE.match(text):
        return None
    return (
        "%s action is %r, which does not name a keystroke.  A row's "
        "action is written as \"press '<key>'\", optionally followed by "
        "%r and the reason it was pressed, because the identity half is "
        "derived from the key that was actually delivered and is what "
        "makes the row evidence rather than a description"
        % (label, action, ACTION_SEPARATOR))


def sentinel_problems(action, commentary, label):
    """Report every way these two fields fail to be a record.

    `label` prefixes each message -- "row 116" from the reader,
    "action" from the writer -- so the same rule reads correctly
    wherever it is applied.  Pure: nothing is read, repaired or
    rewritten.

    An empty list means both fields say something.  It does NOT mean
    either is TRUE: no code can check an action against the pixels of
    the frame it describes, which is why a field admitting it does not
    describe the keystroke has to be refused here.
    """
    problems = []
    for name, value in (("action", action),
                        ("commentary", commentary)):
        hits = find_placeholder_words(value)
        if hits:
            problems.append(
                "%s %s carries the placeholder marker(s) %s: %r.  A "
                "manifest row is the authoritative record of what one "
                "keystroke did and why; a field marked as not yet "
                "filled in is not a record of anything, and every "
                "structural check would still pass over it.  Write "
                "what was actually pressed and the survivor's actual "
                "reason, from contemporaneous evidence -- never "
                "invented"
                % (label, name, ", ".join(repr(one) for one in hits),
                   value))
    deferrals = find_unrecorded_action_phrases(action)
    if deferrals:
        problems.append(
            "%s action defers the record elsewhere (%s): %r.  This is "
            "the one field nothing downstream can check against the "
            "pixels, so an action that says it does not describe the "
            "keystroke is refused here.  "
            "playthrough/TECHNICAL_NOTES.md is where the ENGINEERING "
            "account of a mistake goes; the row itself still has to "
            "say what was pressed"
            % (label, ", ".join(repr(one) for one in deferrals),
               action))
    return problems


def _validated_commentary(value):
    """Return the survivor's own words, or refuse them.

    Length that is merely long is advised about and recorded as given;
    an out-of-character sentence is REFUSED, because it would go verbatim
    into the transcript and onto the film as a caption.
    """
    text = _validated_text(value, "commentary")
    if len(text) > CUE_ADVISORY_LENGTH:
        # Advisory, not a refusal: this is about a caption being
        # readable, and where that line falls is a judgement the writer
        # of the sentence gets to make.  The number comes from the other
        # end of the pipeline -- a cue occupies its frame's on-screen
        # window, which timeline.py caps at 10 s, and a comfortable
        # reading rate over 10 s is a few hundred characters.
        _warn(
            "commentary is %d characters, which is more than a reader "
            "can take in while its frame is on screen (a frame's window "
            "is at most 10 s, and this becomes one SRT cue): %r -- "
            "recorded as given, but consider saying it in a sentence"
            % (len(text), text[:80] + "..."))
    # THE VOICE GATE, AND IT REFUSES.  It used to warn and append the
    # row anyway, which meant a stderr line during a four-hundred-row
    # session decided whether an engineering observation reached the
    # committed transcript and the film's caption track.  By the time
    # anybody read that line the row was evidence, and evidence is not
    # rewritten afterwards -- so the refusal happens here, before the
    # row exists.  See META_PATTERNS for why the patterns are precise
    # rather than blunt: this has to be able to refuse "the engine's own
    # pathfinding" without refusing "mechanical engineer".
    problem = meta_vocabulary_problem(text, "commentary")
    if problem is not None:
        raise ManifestError(problem)
    return text


def _format_moment(moment):
    """Render an aware datetime in the fixed real_ts form."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ManifestError(
            "real_ts must carry a timezone so the column is sortable "
            "across hosts; use utc_timestamp()")
    in_utc = moment.astimezone(datetime.timezone.utc)
    return "%s.%03d%s" % (in_utc.strftime(REAL_TS_FORMAT),
                          in_utc.microsecond // 1000,
                          REAL_TS_SUFFIX)


def utc_timestamp(moment=None):
    """Return `moment` in the manifest's fixed real_ts form.

    UTC, millisecond precision, "Z"-suffixed -- for example
    "2026-05-14T09:12:03.481Z".  One form on every row, so the column
    sorts lexically as well as chronologically.  Called with no
    argument it stamps the current instant, which is what session.py
    does at the moment it captures a frame.
    """
    if moment is None:
        moment = datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(moment, datetime.datetime):
        raise ManifestError(
            "utc_timestamp takes a datetime or None, got %s"
            % type(moment).__name__)
    return _format_moment(moment)


def canonical_real_ts(value):
    """Normalise a supplied real_ts to the one fixed form.

    Accepts the canonical string itself, which round-trips byte for
    byte; any other timezone-aware ISO-8601 string, including the
    "Z"-suffixed output of `date -u +%Y-%m-%dT%H:%M:%S.%3NZ`; or an
    aware datetime.  A value with no timezone is refused rather than
    assumed to be UTC, because a timestamp with no zone is not
    sortable across hosts and guessing one would be an invention.

    WHAT IS ACCEPTED IS WIDER THAN WHAT IS STORED, deliberately, and the
    difference is worth being precise about.  This is lenient on the way
    IN -- another spelling of the same instant is a real timestamp and
    rewriting it into the column's form is the right thing to do with it
    -- so every value this module WRITES is the canonical form, and the
    normalisation is disclosed once by build_row().  The record itself
    is held to the narrow rule: row_field_problems() reports a stored
    real_ts that is not byte-identical to its canonical rendering,
    because a mixed-format column parses perfectly row by row while a
    lexical sort of it silently stops being a chronological one.

    None IS REFUSED.  `ingame_clock` is the only nullable field in this
    schema, and it is nullable precisely so that an unreadable clock
    can be reported as unread.  real_ts is the opposite kind of value:
    it is a fact the caller holds and this module does not.  Stamping
    "now" for a caller who passed nothing would silently record the
    instant the ROW WAS APPENDED as though it were the instant the
    FRAME WAS CAPTURED -- two different times, separated by the settle,
    the screenshot, the crop and the OCR pass -- and it would do so
    most convincingly on the rows where the caller had simply forgotten
    to measure.  That is fabricated evidence, which HR6 forbids
    outright.  So the timestamp must be passed in, and taking it stays
    a deliberate caller action: utc_timestamp() called at the capture.
    """
    if value is None:
        raise ManifestError(
            "real_ts is required and must not be None; it records when "
            "the capture actually happened, which this module cannot "
            "know and will not invent.  ingame_clock is the only "
            "nullable field.  Call utc_timestamp() at the moment the "
            "frame is captured and pass the result, or pass the "
            "capture's own timestamp (the canonical form is %s)"
            % REAL_TS_EXAMPLE)
    if isinstance(value, datetime.datetime):
        return _format_moment(value)
    if not isinstance(value, str):
        raise ManifestError(
            "real_ts must be an ISO-8601 string or an aware datetime, "
            "got %s" % type(value).__name__)
    text = value.strip()
    if not text:
        raise ManifestError(
            "real_ts must not be empty; it records when the capture "
            "actually happened")
    candidate = text
    if candidate[-1:] in ("Z", "z"):
        # datetime.fromisoformat only accepts a "Z" suffix on Python
        # 3.11 and newer.  Rewriting it to an explicit offset keeps
        # this module correct on every interpreter the repository's
        # tooling may be run under.
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except ValueError as err:
        raise ManifestError(
            "real_ts %r is not ISO-8601 (%s); the canonical form is "
            "%s" % (value, err, REAL_TS_EXAMPLE)) from err
    return _format_moment(parsed)


def _ordered_row(row):
    """Return `row` as a dict of exactly FIELDS, in declared order.

    Refuses a row that is missing a required key or carries an
    unexpected one -- and says which, because a silent extra key is
    how a second source of truth for timing would get in.  A mapping
    whose insertion order differs is reordered rather than refused:
    the schema fixes the order on disk, which this controls.
    """
    if not isinstance(row, dict):
        raise ManifestError(
            "a row must be a dict of the six manifest fields, got %s"
            % type(row).__name__)
    missing = [name for name in FIELDS if name not in row]
    extra = [name for name in row if name not in FIELDS]
    if missing or extra:
        raise ManifestError(
            "a row carries exactly these keys, in this order: %s.  "
            "Missing: %s.  Unexpected: %s.  Durations, transition "
            "flags and cue windows belong to "
            "playthrough/timeline.json; diagnostics belong to "
            "playthrough/TECHNICAL_NOTES.md"
            % (", ".join(FIELDS), missing or "none", extra or "none"))
    return {name: row[name] for name in FIELDS}


def build_row(frame, file, real_ts, ingame_clock, action, commentary):
    """Validate one row and return it, without touching the disk.

    Every field is checked here, so a caller can validate before it
    commits to writing, and so append_row() has exactly one validation
    path.

    `ingame_clock` may be None; NOTHING ELSE MAY BE, and that is
    enforced rather than merely documented.  In particular `real_ts` is
    mandatory: see canonical_real_ts() for why a defaulted timestamp
    would be fabricated evidence rather than a convenience.
    """
    index = _validated_frame(frame)
    stamped = canonical_real_ts(real_ts)
    # A NORMALISATION IS DISCLOSED, not performed quietly.  capture.sh
    # stamps the canonical form and hands it straight through, so this
    # is silent for every row of a real session; a value that had to be
    # rewritten means the timestamp came from somewhere else, and the
    # operator should hear that once rather than discover it by finding
    # a column that sorts wrongly.  Advisory rather than a refusal,
    # because the value itself is a real instant and rewriting it into
    # the column's one form is exactly the right thing to do with it.
    if isinstance(real_ts, str) and real_ts.strip() != stamped:
        _warn_once(
            "real-ts-normalised",
            "real_ts %r was rewritten to %r, the one form this column "
            "is written in; the instant is unchanged.  capture.sh "
            "already stamps that form, so a value needing this came "
            "from somewhere else" % (real_ts, stamped))
    row = {
        "frame": index,
        "file": _validated_file(file, index),
        "real_ts": stamped,
        "ingame_clock": _validated_ingame_clock(ingame_clock),
        "action": _validated_text(action, "action"),
        "commentary": _validated_commentary(commentary),
    }
    # REFUSED AT THE WRITER TOO, not only by the reader.  A row that
    # cannot be written is a row that never has to be corrected, and
    # the caller is a live session that still knows what it pressed and
    # why.
    problems = sentinel_problems(
        row["action"], row["commentary"], "frame %d" % index)
    # AND THE SHAPE OF THE ACTION, which only the writer checks: see
    # action_shape_problem() for why the reader deliberately does not.
    shape = action_shape_problem(row["action"], "frame %d" % index)
    if shape is not None:
        problems.append(shape)
    if problems:
        raise ManifestError("  ".join(problems))
    return _ordered_row(row)


def encode_row(row):
    """Return the exact line this module writes for `row`.

    One self-contained JSON object, keys in the declared order,
    non-ASCII written as itself rather than escaped -- the convention
    the repository's own tooling follows -- and terminated by a single
    LF.  No indentation, no wrapping array, no trailing comma.
    """
    ordered = _ordered_row(row)
    return json.dumps(ordered, ensure_ascii=False) + "\n"


def _fsync(descriptor, path, frame, require_durable):
    """Force a written row to the device, or fail loudly.

    A crash mid-session must not lose the row for a frame that already
    exists on disk, which is the whole reason this call is here.  So a
    refusal is NOT tolerated by default.  flush() has handed the bytes
    to the operating system by this point, but "the kernel has them" is
    not the same claim as "they survive a power loss", and reporting
    success for the weaker claim would mean the manifest -- the
    session's evidence, and the file the frame-count identity is
    checked against -- could silently be missing rows for frames that
    exist.  A row this module cannot prove it stored is therefore
    raised as ManifestError rather than warned about and passed over.

    Reduced durability remains available, but only as an explicit
    caller decision: `require_durable=False` restores the warn-once
    behaviour for a caller who genuinely accepts it, such as a scratch
    manifest on a filesystem that cannot fsync at all.  The default is
    the safe one, and the opt-in has to be typed out.

    THIS STEP DELIBERATELY DOES NOT ROLL THE ROW BACK, unlike the write
    itself.  By the time it runs the line is complete and valid JSON on
    disk; what is in doubt is only whether it survives a power loss.
    Truncating it away would turn an uncertainty into a certain loss --
    deleting the record of a frame that exists -- so the row stays and
    the uncertainty is reported for what it is.
    """
    try:
        os.fsync(descriptor)
    except OSError as err:
        if require_durable:
            raise ManifestError(
                "could not force frame %s's row to the device (%s).  "
                "The line was written to %s and handed to the "
                "operating system, but its DURABILITY IS UNPROVEN, so "
                "the row may not survive a crash -- and the manifest "
                "is the session's evidence.  Re-read the file to "
                "establish what it now contains rather than assuming "
                "either outcome.  Pass require_durable=False only if "
                "reduced durability is genuinely acceptable here"
                % (frame, err, path)) from err
        _warn_once(
            "fsync",
            "could not fsync the manifest (%s); rows are flushed but "
            "not forced to the device -- the caller explicitly "
            "approved this reduced durability" % err)


def _roll_back(descriptor, committed, path, frame, cause):
    """Undo a failed append and return the error to raise.

    The caller writes `raise _roll_back(...)`, so that the rollback and
    the failure are one statement and neither can be forgotten.

    THIS IS WHAT KEEPS A HANDLED FAILURE FROM COSTING MORE THAN ITS OWN
    ROW, and it is the opposite of rewriting history rather than an
    exception to it.  The only bytes it can remove are the ones the
    append that just failed had started to write: `committed` was read
    from the file BEFORE that write, under the same lock, so truncating
    to it restores the file to exactly the state every already-recorded
    row left it in.  No recorded row is altered, no row is dropped, and
    the failure is still raised.

    It covers the failures this process lives to handle -- a short
    write, ENOSPC, an EIO -- and nothing else.  A process killed
    outright never reaches it; see _assert_row_boundary(), which is what
    refuses the torn row it leaves behind.

    Without it a write that stops half way -- ENOSPC on a long session
    is the realistic case, because one PNG per keystroke fills a disk
    long before a session ends -- leaves a partial line with no newline,
    and a partial line is not JSON.  The manifest then cannot be read
    at all: timeline.py, the render, the captions and every acceptance
    gate that counts rows are blocked behind a file only a human hand
    edit can repair.  An append-only evidence record exists precisely so
    that a resource failure costs the failing row and nothing else.

    A truncate that itself fails is reported alongside the original
    cause rather than hidden behind it: the operator then knows the file
    needs inspecting, which is strictly better than being told only
    about the disk.

    THE OUTCOME IS REPORTED, NOT ASSUMED.  The restoration claim is made
    only when the truncate actually succeeded.  A message that says the
    file was left exactly as it was AND that it may end mid-row
    contradicts itself, and an operator reading the reassuring half
    first has been told the record is intact when nothing established
    that.  So the two cases are separate sentences: restored and
    readable, or integrity UNKNOWN and inspection mandatory.
    """
    try:
        os.ftruncate(descriptor, committed)
    except OSError as err:
        outcome = (
            "  The ROLLBACK TO %d bytes ALSO FAILED (%s), so the state "
            "of the file is UNKNOWN: it may still end mid-row.  Nothing "
            "here established that the record is intact, so INSPECT IT "
            "before appending again -- run 'python "
            "playthrough/tooling/manifest.py verify' to see whether the "
            "last line is a complete row." % (committed, err))
    else:
        outcome = (
            "  The file was left exactly as it was before this row (%d "
            "bytes), so it is still readable and the frame this row "
            "describes is the one to re-record." % (committed,))
    return ManifestError(
        "could not append frame %s's row to %s (%s); the manifest is "
        "the session's evidence, so a write this module cannot complete "
        "is reported rather than passed over.%s"
        % (frame, path, cause, outcome))


def _assert_row_boundary(descriptor, committed, path, frame):
    """Refuse to append onto a line that was never finished.

    _roll_back() removes a torn row whenever this process survives to
    run it, which covers the failure that motivated it.  It cannot cover
    a process that is killed outright -- SIGKILL, a power loss, an OOM
    kill -- part way through the write, and then the file ends mid-row
    with no newline.  Appending after that would join two half-rows into
    one line that is neither, quietly turning a recoverable tear into a
    corrupt record that reads as a single malformed row.

    So the boundary is checked before every append, at the cost of one
    byte read: a non-empty manifest must end with the LF that terminated
    its last complete row.  It is refused rather than repaired, because
    the missing piece is a row about a frame that exists, and deciding
    what it said is not this module's business -- verify_manifest()
    reports which line is malformed, the frame it describes is still on
    disk, and the correction is the operator's to make deliberately.
    """
    if committed <= 0:
        return
    try:
        tail = os.pread(descriptor, 1, committed - 1)
    except OSError as err:
        raise ManifestError(
            "could not read the last byte of the manifest %s (%s), so "
            "frame %s's row was not appended: a row must never be "
            "joined onto an unfinished one, and that cannot be ruled "
            "out without this check" % (path, err, frame)) from err
    if tail != b"\n":
        raise ManifestError(
            "%s ends mid-row -- its last %d bytes are not terminated by "
            "a newline -- so frame %s's row was NOT appended onto it.  "
            "A manifest ends with a complete row or it ends with a tear "
            "from a process that was killed mid-write, and appending "
            "would fuse the two into one line that is neither.  Run "
            "'python playthrough/tooling/manifest.py verify' to see the "
            "line, and repair the record deliberately: the frame that "
            "row describes is still in playthrough/frames/"
            % (path, committed, frame))


def _append_whole_row(descriptor, payload, committed, path, frame):
    """Write one encoded row, entirely or not at all.

    One `os.write` of the complete line, unbuffered, on a descriptor
    opened O_APPEND and held under the exclusive lock: there is no
    userspace buffer that could flush a fragment later, and the kernel
    places the bytes at the end of the file whatever another writer is
    doing.  A refusal and a short write are handled identically --
    rolled back to `committed` -- because a row that is 90% written is
    exactly as unreadable as one that raised.

    A short write is looped rather than assumed away only after the
    rollback question is settled: os.write may legitimately return
    fewer bytes, so the remainder is written until it is all there, and
    a step that makes no progress is treated as a failure rather than
    spun on.
    """
    total = len(payload)
    written = 0
    while written < total:
        try:
            count = os.write(descriptor, payload[written:])
        except OSError as err:
            raise _roll_back(
                descriptor, committed, path, frame, err) from err
        if count <= 0:
            raise _roll_back(
                descriptor, committed, path, frame,
                "the write stopped after %d of %d bytes and made no "
                "further progress" % (written, total))
        written += count


def _lock_exclusively(descriptor, path):
    """Take an exclusive advisory lock over the open manifest.

    Two writers appending at the same instant is not hypothetical: the
    capture loop runs unattended, and a second stage or a re-run can
    overlap it.  O_APPEND keeps each write at the end of the file, but
    the lock is what makes "measure the end, write, fsync, and on
    failure truncate back" one indivisible step AS SEEN BY ANOTHER
    PROCESS THAT ALSO TAKES IT -- so two rows cannot interleave and a
    rollback cannot remove bytes another writer put there after this one
    measured the end.

    THE LOCK IS ADVISORY, so that guarantee reaches exactly as far as
    the processes that cooperate with it.  Every writer in this pipeline
    goes through this function, which is what makes it hold here; a
    READER that does not take the lock is unaffected by it and can read
    the file mid-append.  That is why the readers do not rely on the
    lock: verify_manifest() refuses a line it cannot parse, and
    timeline.py refuses the document rather than working around it.

    THE LOCK IS MANDATORY AND THIS FAILS CLOSED.  It used to warn and
    carry on, which was wrong for one specific and unrecoverable
    reason: the append that follows measures the end of the file and,
    on failure, truncates BACK to that offset.  Without the lock those
    two operations are not one step, so a concurrent writer's COMPLETE
    row -- somebody else's evidence -- can be appended between the
    measurement and the truncation and then destroyed by this process's
    rollback.  A step that cannot be serialised is therefore refused
    before anything is measured, which costs a session that stops and
    can be resumed instead of a record that lost a row nobody will
    notice is gone.

    The lock is released when the descriptor closes, which the caller's
    `finally` guarantees on every path including an exception.

    :raises ManifestError: when the lock cannot be taken.  Nothing has
        been measured, written or truncated at that point.
    """
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as err:
        raise ManifestError(
            "could not take an exclusive lock on the manifest %s (%s), "
            "so nothing was written.  The append measures the end of "
            "the file and truncates back to it if it fails; without "
            "the lock those are two operations, and a concurrent "
            "writer's complete row could be appended in between and "
            "then removed by this process's rollback.  A row of "
            "captured evidence is not something to risk on a "
            "filesystem that will not serialise writers -- run one "
            "session at a time on a filesystem that supports flock"
            % (path, err)) from err


def append_row(manifest_path, frame, file, real_ts, ingame_clock,
               action, commentary, require_durable=True, root=None):
    """Validate one row and append it to the manifest.

    The only writer in this module, and the only writer of this file.
    Returns the row exactly as written, so the caller can log or
    assert on it.  Raises ManifestError and writes nothing at all if
    any field is wrong -- there is no partial row.

    A row is not reported as appended until it has been written,
    flushed AND forced to the device.  Every failure up to and including
    the fsync -- the open, the lock, the boundary check, the write, the
    fsync -- raises ManifestError; none is downgraded to a warning,
    because a caller that is told the row was recorded will not go back
    and check.  `require_durable=False` is the one documented exception,
    and it weakens only the fsync step: see _fsync().

    The CLOSE is the one step after that, and it is warned rather than
    raised, deliberately: by then the row is on the device, so raising
    would tell the caller the row was not recorded when it was.  It is
    still reported once.

    `manifest_path` is explicit rather than defaulted so that a test,
    a dry run and the real session cannot be confused for one another;
    default_manifest_path() supplies the pipeline's own value.  It is
    validated against the approved root before anything is opened, so
    a path outside playthrough/ -- or one reached through a symlink --
    is refused rather than appended to.  `root` relocates that approved
    tree for a test that owns a temporary directory; see
    approved_root().

    What this does NOT do is police the index sequence, deliberately.
    Checking that an index follows the last one written would mean
    reading the whole file on every append -- quadratic over a session,
    and a writer that behaves differently depending on what is already
    on disk.  Instead a repeated or skipped index is recorded honestly
    and reported loudly afterwards by verify_manifest(), which is also
    what the acceptance gate runs.  The counter stays session.py's.
    """
    path = _validated_manifest_path(manifest_path, root)
    row = build_row(frame, file, real_ts, ingame_clock, action,
                    commentary)
    line = encode_row(row)
    # Append mode, one line, then closed.  The file is never opened
    # for writing any other way: not truncated, not seeked, not
    # re-sorted, not deduplicated, not compacted, not retro-edited.
    # If something was recorded wrongly the correction is a note in
    # playthrough/TECHNICAL_NOTES.md, not an edit to this history.
    # newline="\n" pins LF whatever the platform, which is what the
    # `*.jsonl text` attribute expects of the committed file.
    #
    # The descriptor is opened with O_NOFOLLOW rather than by name, so
    # a symlink planted between the validation above and this line is
    # refused by the kernel instead of followed, and the whole append
    # is serialised against other writers by the lock below.
    #
    # A HANDLED WRITE FAILURE COSTS ITS OWN ROW AND NOTHING ELSE.  The
    # row is written by os.write directly, not through a buffered
    # stream: a stream can flush a fragment of a line when the disk
    # fills, and a fragment is not JSON, which makes the whole manifest
    # unreadable and blocks every stage that counts its rows.  It is one
    # call for the whole line whenever the kernel takes the whole line,
    # and _append_whole_row() loops for the remainder when it does not,
    # because os.write is allowed to return short.
    # The end of the file is measured first, under the lock, so a write
    # that cannot complete is truncated straight back to it -- see
    # _append_whole_row() and _roll_back().  Nothing else in this module
    # ever seeks or truncates, and a rollback can only ever remove bytes
    # the failing append itself had begun to write.
    #
    # That is as far as the guarantee goes, and it is deliberately not
    # called atomic: an UNHANDLED interruption -- SIGKILL, an OOM kill,
    # the power going -- can stop the write with no chance to undo it,
    # and the file then ends mid-row.  _assert_row_boundary() below
    # refuses to append onto that, and verify_manifest() reports it, so
    # the tear is caught rather than assumed away.
    #
    # Every step is guarded so that an OSError from any of them becomes
    # a ManifestError: the caller already catches that for every
    # validation failure, and a write or durability failure deserves
    # the same visibility rather than surfacing as a different
    # exception type from a different layer.  The ManifestError raised
    # by _fsync() is not an OSError, so it passes through untouched.
    # O_RDWR rather than O_WRONLY for exactly one reason: the boundary
    # check below reads the file's last byte, and pread needs a readable
    # descriptor.  It buys no other freedom -- O_APPEND still forces
    # every write to the end of the file, the reads are positional and
    # never move the write offset, and this remains the only descriptor
    # in the module that can write at all.
    payload = line.encode("utf-8")
    descriptor = _open_nofollow(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW)
    try:
        _lock_exclusively(descriptor, path)
        try:
            committed = os.lseek(descriptor, 0, os.SEEK_END)
        except OSError as err:
            raise ManifestError(
                "could not measure the end of the manifest %s (%s), so "
                "frame %s's row was not written: without that offset a "
                "failed append could not be undone, and a half-written "
                "row would make the whole record unreadable"
                % (path, err, row["frame"])) from err
        _assert_row_boundary(descriptor, committed, path, row["frame"])
        _append_whole_row(
            descriptor, payload, committed, path, row["frame"])
        _fsync(descriptor, path, row["frame"], require_durable)
    finally:
        # Closing releases the lock as well.  A close that fails cannot
        # hide a row this function claimed to have stored -- the write
        # and the fsync above both already raise, and the fsync ran
        # first -- so it is not promoted to a failure that would
        # contradict a row already on disk.  It is still reported once,
        # because a descriptor the operating system would not close is a
        # fact about the host and not something to swallow.
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "close",
                "could not close the manifest %s after appending (%s); "
                "the row itself was written and forced to the device "
                "before this point, so the record is intact" %
                (path, err))
    return row


def append_record(manifest_path, row, require_durable=True, root=None):
    """Append a row supplied as a mapping of the six fields.

    A convenience for a caller that already holds a dict; it shares
    append_row()'s validation exactly -- including the path checks, the
    lock and the durability guarantee -- so neither entry point can be
    the lenient one.
    """
    ordered = _ordered_row(row)
    return append_row(
        manifest_path,
        ordered["frame"],
        ordered["file"],
        ordered["real_ts"],
        ordered["ingame_clock"],
        ordered["action"],
        ordered["commentary"],
        require_durable=require_durable,
        root=root,
    )


def staging_candidates(directory, prefix, suffix):
    """Return the staging siblings in `directory`, sorted.  Read-only.

    Names only, and only ones that genuinely carry the private prefix
    AND the suffix, so nothing an operator or the engine put there can
    be mistaken for one.  A directory that cannot be listed yields
    nothing: this exists to clean up, and failing to clean up is not a
    reason to refuse to write.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return ()
    return tuple(sorted(
        name for name in names
        if name.startswith(prefix) and name.endswith(suffix) and
        len(name) > len(prefix) + len(suffix)))


def sweep_staging(directory, prefix, suffix, label):
    """Remove staging siblings a retired rewrite left behind.

    WHY THIS OUTLIVED THE WRITER IT SERVED.  This module can no longer
    rewrite anything: the record is append-only and every rewrite entry
    point was removed.  A sibling temporary under the private prefix can
    still be sitting on disk, though, because the retired writer renamed
    one into place and an UNHANDLED interruption -- SIGKILL, the power
    going -- left it behind where no handled path could unlink it.  These
    siblings live inside playthrough/, which .gitignore re-includes
    wholesale with its terminal `!/playthrough/**` negation, so a
    survivor is an untracked file that `git add -A playthrough/` would
    commit into an evidence tree nobody authored it into.

    It is therefore swept whenever a session opens, which is the moment
    that can still heal the tree now that nothing writes one: no later
    rewrite is ever going to run and clear it.

    WHAT IT WILL NOT DELETE.  Only a REGULAR file, never a symbolic link
    (which could point anywhere), never a directory, and only one owned
    by this account.  Anything else is reported and LEFT, because
    removing a file this module did not write is not reconciliation.

    session.py sweeps its telemetry sidecar's staging siblings through
    this same function, because both files sit in the re-included tree
    and have exactly one failure mode between them.

    Returns the names removed, so a caller can report them.
    """
    removed = []
    for name in staging_candidates(directory, prefix, suffix):
        candidate = os.path.join(directory, name)
        try:
            info = os.lstat(candidate)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            _warn_once(
                "staging-not-regular",
                "%s is not a regular file, so it is left alone even "
                "though it carries the private staging prefix %r used "
                "for %s; look at it, because nothing this pipeline "
                "writes belongs there"
                % (relative_to_repo(candidate), prefix, label))
            continue
        if info.st_uid != os.getuid():
            _warn_once(
                "staging-foreign-owner",
                "%s is owned by uid %d rather than by uid %d, so it is "
                "left alone even though it carries the private staging "
                "prefix %r used for %s"
                % (relative_to_repo(candidate), info.st_uid,
                   os.getuid(), prefix, label))
            continue
        try:
            os.unlink(candidate)
        except OSError as err:
            _warn_once(
                "staging-unlink",
                "%s could not be removed (%s); it is a leftover from an "
                "interrupted rewrite of %s and it must not be committed"
                % (relative_to_repo(candidate), err, label))
            continue
        removed.append(name)
        _warn(
            "%s was left behind by an interrupted rewrite of %s and has "
            "been removed; the file it was staging is unchanged"
            % (relative_to_repo(candidate), label))
    return tuple(removed)


# ---------------------------------------------------------------------
# The amendment ledger
#
# WHY THIS EXISTS AT ALL.  A row can be wrong in exactly one way that
# an append cannot fix and a prose note cannot either: its narration can
# claim an effect that its own capture contradicts, or carry a word the
# in-character record may not carry, while its keystroke, its frame and
# its clock reading are all genuine.  A derivative -- the transcript,
# the caption track -- then repeats the wrong sentence however carefully
# the evidence was gathered.
#
# The previous answer to that was a path that rewrote the manifest in
# place.  A security review named it correctly: a mechanism that can
# rewrite captured evidence is a defect, because it makes every later
# artifact deniable.  It has been deleted, and this ledger replaces it.
#
# WHAT AN AMENDMENT IS.  A row in a SECOND append-only file, bound to
# the manifest line it concerns by that line's sha256.  It states the
# recorded value, the amended value, what established the amendment and
# why the recorded value could not stand.  Nothing in the manifest
# moves.  Both files are committed, so a reader can see the record, the
# correction, and the exact binding between them.
#
# WHAT IT DELIBERATELY CANNOT DO.  It cannot touch `frame`, `file`,
# `real_ts` or `ingame_clock` (AMENDABLE_FIELDS is two names long), so a
# clock reading, a timestamp or a frame path can never be amended -- an
# amendment corrects a narration, and rewriting a reading would be
# fabricating evidence.  It cannot apply to a row whose bytes have moved
# since the amendment was written: resolve_rows() REFUSES on a digest
# mismatch rather than skipping it, because a stale amendment means the
# two records disagree about history.
# ---------------------------------------------------------------------

def default_amendments_path():
    """Return the amendment ledger's path.

    Honours PLAYTHROUGH_AMENDMENTS for the same reason
    default_manifest_path() honours PLAYTHROUGH_MANIFEST -- env.sh is
    the single definition of the artifact layout -- and the value is
    then held to exactly the same containment rules.
    """
    from_env = os.environ.get("PLAYTHROUGH_AMENDMENTS")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), AMENDMENTS_NAME)


def _validated_amendments_target(value, root=None):
    """Return an absolute ledger path this module may touch.

    The same four conditions as _validated_manifest_target(), against
    the ledger's own canonical name: inside the approved root, no
    symlinked component, EXACTLY <approved root>/amendments.jsonl, and a
    regular file.  Condition three matters here for the identical
    reason: every artifact of this pipeline lives inside playthrough/,
    so containment alone would let an environment variable point the
    ledger's appends at the manifest, at a frame or at the movie.
    """
    resolved = _validated_path(value, "amendment ledger path")
    approved = _assert_within_root(
        resolved, "the amendment ledger path", root)
    _assert_no_symlink(resolved, approved, "the amendment ledger path")
    canonical = os.path.join(approved, AMENDMENTS_NAME)
    if os.path.realpath(resolved) != canonical:
        raise ManifestError(
            "the amendment ledger is %s and nothing else, but %s was "
            "given.  Appending amendment rows onto another artifact "
            "would corrupt it and would report success."
            % (canonical, resolved))
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ManifestError(
            "the amendment ledger path is not a regular file: %s"
            % resolved)
    return resolved


def _validated_amendments_path(value, root=None):
    """Return a ledger path that is safe to append to."""
    resolved = _validated_amendments_target(value, root)
    parent = os.path.dirname(resolved)
    if not os.path.isdir(parent):
        raise ManifestError(
            "the directory for the amendment ledger does not exist: %s"
            % parent)
    return resolved


def line_digest(line):
    """Return the sha256 of one manifest LINE, newline included.

    THE LINE, NOT THE PARSED ROW, and that is the whole point: the
    binding is to the bytes on disk, so a digest cannot match a row that
    was re-encoded, re-ordered or re-spaced.  A row is accepted here too
    and is encoded through encode_row() first, which is the same
    function append_row() writes with -- so the digest of a row equals
    the digest of the line that row was written as.
    """
    if isinstance(line, dict):
        line = encode_row(line)
    if isinstance(line, bytes):
        payload = line
    elif isinstance(line, str):
        payload = line.encode("utf-8")
    else:
        raise ManifestError(
            "a digest is taken over a manifest line or row, got %s"
            % type(line).__name__)
    return hashlib.sha256(payload).hexdigest()


def row_digests(manifest_path=None, root=None):
    """Return {frame index: line digest} for the manifest on disk.

    Read-only, and it reads the FILE rather than re-encoding rows, so
    the digests are of the bytes a reviewer can hash for themselves.
    """
    path = _validated_manifest_target(
        default_manifest_path() if manifest_path is None
        else manifest_path, root)
    if not os.path.isfile(path):
        raise ManifestError("no manifest at %s" % path)
    digests = {}
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8",
                       newline="") as handle:
            descriptor = None
            for number, raw in enumerate(handle, start=1):
                row = _decode_line(raw, number, path)
                digests[row["frame"]] = line_digest(raw)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return digests


def _validated_amendment_field(value):
    """Return an amendable field name, or raise."""
    if not isinstance(value, str) or value not in AMENDABLE_FIELDS:
        raise ManifestError(
            "an amendment may concern %s and nothing else, got %r.  "
            "The frame, its file, its capture timestamp and its clock "
            "reading are the evidence itself: amending one of those "
            "would be inventing a reading rather than correcting a "
            "narration"
            % (" or ".join(AMENDABLE_FIELDS), value))
    return value


def _validated_digest(value, label):
    """Return a lowercase 64-hex sha256, or raise."""
    if not isinstance(value, str):
        raise ManifestError(
            "%s must be a sha256 hex digest, got %s"
            % (label, type(value).__name__))
    text = value.strip()
    if not SHA256_RE.match(text):
        raise ManifestError(
            "%s must be 64 lowercase hex digits (a sha256), got %r"
            % (label, value))
    return text


def build_amendment(number, amended_ts, frame, field, source_sha256,
                    recorded, amended, basis, reason):
    """Validate one amendment and return it in canonical key order.

    Pure: it writes nothing, so a caller can inspect exactly what would
    be appended.  Every field is held to the same rules the manifest's
    own text fields are held to -- no line breaks, no control
    characters, no runaway length -- and three more that are specific to
    an amendment:

    * `field` must be one of AMENDABLE_FIELDS;
    * `amended` must DIFFER from `recorded`, because an amendment that
      changes nothing is noise in a ledger that has to be read;
    * `basis` and `reason` are MANDATORY and non-empty.  An amendment
      without a stated basis is an assertion, and the whole reason this
      ledger exists rather than an edit is that an assertion is not
      evidence.
    """
    if isinstance(number, bool) or not isinstance(number, int):
        raise ManifestError(
            "the amendment number must be an integer, got %s"
            % type(number).__name__)
    if number < 1:
        raise ManifestError(
            "the amendment number is 1 or greater, got %d" % number)
    row = {
        "amendment": number,
        "amended_ts": canonical_real_ts(amended_ts),
        "frame": _validated_frame(frame),
        "field": _validated_amendment_field(field),
        "source_sha256": _validated_digest(source_sha256,
                                           "source_sha256"),
        "recorded": _validated_text(recorded, "recorded"),
        "amended": _validated_text(amended, "amended"),
        "basis": _validated_text(basis, "basis"),
        "reason": _validated_text(reason, "reason"),
    }
    if row["recorded"] == row["amended"]:
        raise ManifestError(
            "the amendment for frame %d's %s does not change it; an "
            "amendment that says nothing does not belong in a ledger a "
            "reviewer has to read"
            % (row["frame"], row["field"]))
    if row["field"] == "commentary":
        problem = meta_vocabulary_problem(row["amended"])
        if problem:
            raise ManifestError(
                "the amended commentary for frame %d is not in the "
                "survivor's voice: %s" % (row["frame"], problem))
    else:
        problem = action_shape_problem(row["amended"], "amended")
        if problem:
            raise ManifestError(
                "the amended action for frame %d is not the derived "
                "shape: %s" % (row["frame"], problem))
    return {name: row[name] for name in AMENDMENT_FIELDS}


def encode_amendment(row):
    """Return one amendment as the exact line to be written."""
    ordered = {name: row[name] for name in AMENDMENT_FIELDS}
    return json.dumps(ordered, ensure_ascii=False) + "\n"


def append_amendment(amendments_path, number, amended_ts, frame, field,
                     source_sha256, recorded, amended, basis, reason,
                     require_durable=True, root=None):
    """Validate one amendment and APPEND it to the ledger.

    THE SECOND AND LAST WRITER IN THIS MODULE, and it goes through
    exactly the machinery append_row() goes through -- the same
    O_NOFOLLOW open, the same MANDATORY exclusive flock, the same
    end-of-file measurement, the same whole-line write, the same
    rollback of a partial line and the same fsync before the row is
    reported as stored.  That is deliberate and it is the point: a
    correction is evidence too, so it is not allowed to be written by a
    lazier path than the record it corrects.

    Returns the amendment exactly as written.  Raises ManifestError and
    writes nothing at all on any refusal -- there is no partial row.
    """
    path = _validated_amendments_path(
        default_amendments_path() if amendments_path is None
        else amendments_path, root)
    row = build_amendment(number, amended_ts, frame, field,
                          source_sha256, recorded, amended, basis,
                          reason)
    payload = encode_amendment(row).encode("utf-8")
    descriptor = _open_nofollow(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW)
    try:
        _lock_exclusively(descriptor, path)
        try:
            committed = os.lseek(descriptor, 0, os.SEEK_END)
        except OSError as err:
            raise ManifestError(
                "could not measure the end of the amendment ledger %s "
                "(%s), so amendment %s was not written"
                % (path, err, row["amendment"])) from err
        _assert_row_boundary(descriptor, committed, path,
                             row["amendment"])
        _append_whole_row(descriptor, payload, committed, path,
                          row["amendment"])
        _fsync(descriptor, path, row["amendment"], require_durable)
    finally:
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "amendment-close",
                "could not close the amendment ledger %s after "
                "appending (%s); the row itself was written and forced "
                "to the device before this point, so the ledger is "
                "intact" % (path, err))
    return row


def read_amendments(amendments_path=None, root=None):
    """Return the ledger's rows, in the order they were written.

    An ABSENT ledger yields an empty tuple rather than an error: a
    session with nothing to amend legitimately has none, and that is
    the ordinary case rather than a fault.
    """
    path = _validated_amendments_target(
        default_amendments_path() if amendments_path is None
        else amendments_path, root)
    if not os.path.isfile(path):
        return ()
    rows = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8",
                       newline="") as handle:
            descriptor = None
            for number, raw in enumerate(handle, start=1):
                text = raw.rstrip("\n")
                if text.endswith("\r"):
                    raise ManifestError(
                        "%s line %d ends CRLF; the ledger is LF only"
                        % (path, number))
                if not text.strip():
                    raise ManifestError(
                        "%s line %d is blank; the ledger is one JSON "
                        "object per line with no blank lines"
                        % (path, number))
                try:
                    row = json.loads(text)
                except ValueError as err:
                    raise ManifestError(
                        "%s line %d is not JSON: %s"
                        % (path, number, err)) from err
                if not isinstance(row, dict):
                    raise ManifestError(
                        "%s line %d is a %s, not a JSON object"
                        % (path, number, type(row).__name__))
                rows.append(row)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return tuple(rows)


def amendment_problems(amendments, digests=None):
    """Return a list of problems with the ledger.  Read-only, pure.

    An empty list means every row carries the nine fields in the
    declared order with values of the right shape, the amendment
    numbers run 1..n without a gap or a repeat, no (frame, field) pair
    is amended twice, and -- when `digests` is supplied, as
    :func:`row_digests` returns it -- every row's `source_sha256`
    matches the manifest line it names.

    A repeated (frame, field) is a PROBLEM rather than a
    last-one-wins rule on purpose: two amendments of one narration are
    two claims about the same sentence, and choosing between them
    automatically is how a record stops meaning anything.
    """
    problems = []
    seen_numbers = {}
    seen_pairs = {}
    for position, row in enumerate(amendments, start=1):
        if not isinstance(row, dict):
            problems.append(
                "amendment row %d is a %s, not an object"
                % (position, type(row).__name__))
            continue
        missing = [name for name in AMENDMENT_FIELDS if name not in row]
        if missing:
            problems.append(
                "amendment row %d omits %s"
                % (position, ", ".join(missing)))
        extra = [name for name in row if name not in AMENDMENT_FIELDS]
        if extra:
            problems.append(
                "amendment row %d carries unexpected field(s) %s"
                % (position, ", ".join(sorted(extra))))
        if missing or extra:
            continue
        if list(row) != list(AMENDMENT_FIELDS):
            problems.append(
                "amendment row %d writes its fields in the order %s, "
                "not the declared %s"
                % (position, ", ".join(row), ", ".join(AMENDMENT_FIELDS)))
        try:
            rebuilt = build_amendment(
                row["amendment"], row["amended_ts"], row["frame"],
                row["field"], row["source_sha256"], row["recorded"],
                row["amended"], row["basis"], row["reason"])
        except ManifestError as err:
            problems.append("amendment row %d: %s" % (position, err))
            continue
        for name in AMENDMENT_FIELDS:
            if rebuilt[name] != row[name]:
                problems.append(
                    "amendment row %d records %s as %r, which is not "
                    "its canonical form %r"
                    % (position, name, row[name], rebuilt[name]))
        number = row["amendment"]
        if number in seen_numbers:
            problems.append(
                "amendment %d appears on rows %d and %d; the numbers "
                "are the order corrections were made and are not "
                "reused" % (number, seen_numbers[number], position))
        else:
            seen_numbers[number] = position
        if number != position:
            problems.append(
                "amendment row %d is numbered %d; the ledger is "
                "append-only, so the numbers run 1..n in the order "
                "they were written" % (position, number))
        pair = (row["frame"], row["field"])
        if pair in seen_pairs:
            problems.append(
                "frame %d's %s is amended by rows %d and %d; one "
                "narration carries one correction, and two claims "
                "about the same sentence are resolved by a human "
                "rather than by the last line to be written"
                % (pair[0], pair[1], seen_pairs[pair], position))
        else:
            seen_pairs[pair] = position
        if digests is None:
            continue
        if row["frame"] not in digests:
            problems.append(
                "amendment row %d amends frame %d, which the manifest "
                "does not record" % (position, row["frame"]))
        elif digests[row["frame"]] != row["source_sha256"]:
            problems.append(
                "amendment row %d binds frame %d to source_sha256 %s, "
                "but that row's line hashes to %s: the ledger and the "
                "record disagree about what was written"
                % (position, row["frame"], row["source_sha256"],
                   digests[row["frame"]]))
    return problems


def resolve_rows(rows, amendments, digests=None):
    """Apply the ledger to a copy of the rows.  Pure.

    Returns ``(resolved, amended)`` -- the rows a DERIVATIVE should be
    computed from, and the tuple of frame indices an amendment reached,
    in ascending order.  The input rows are not modified and neither is
    any file: this is the one function the transcript, the caption cues
    and the timeline all pass through, so it is deliberately pure and
    deliberately strict.

    FAIL CLOSED, EVERY TIME.  An amendment is applied only when its
    `source_sha256` matches the digest of the row as it stands and its
    `recorded` value matches that row's current text.  Anything else --
    a frame the rows do not carry, a digest that has moved, a
    `recorded` value that does not match, a second amendment of the
    same narration -- raises ManifestError.  A skip would be worse than
    a refusal here: the derivative would come out looking correct while
    the ledger and the record disagreed about history.

    `digests` is the {frame: line digest} mapping :func:`row_digests`
    reads off the file.  When it is omitted the digests are computed
    from the rows through encode_row(), which is the same encoding
    append_row() wrote them with.
    """
    materialised = [dict(row) for row in rows]
    by_frame = {}
    for position, row in enumerate(materialised, start=1):
        index = row.get("frame")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ManifestError(
                "row %d records %r as its frame index, so an amendment "
                "cannot be bound to it" % (position, index))
        if index in by_frame:
            raise ManifestError(
                "frame %d appears on rows %d and %d; an ambiguous "
                "index is reported by verify_manifest() and resolved "
                "before any amendment is applied to it"
                % (index, by_frame[index] + 1, position))
        by_frame[index] = position - 1
    if digests is None:
        digests = {row["frame"]: line_digest(encode_row(row))
                   for row in materialised}
    applied = []
    for position, row in enumerate(amendments, start=1):
        missing = [name for name in AMENDMENT_FIELDS if name not in row]
        if missing:
            raise ManifestError(
                "amendment row %d omits %s, so it cannot be applied"
                % (position, ", ".join(missing)))
        index = row["frame"]
        field = _validated_amendment_field(row["field"])
        if index not in by_frame:
            raise ManifestError(
                "amendment %s amends frame %s, which these rows do not "
                "carry" % (row["amendment"], index))
        if index in [one for one, name in applied if name == field]:
            raise ManifestError(
                "frame %d's %s carries more than one amendment; that "
                "is resolved by a human, not by the last line to be "
                "written" % (index, field))
        target = materialised[by_frame[index]]
        recorded = digests.get(index)
        if recorded != row["source_sha256"]:
            raise ManifestError(
                "amendment %s binds frame %d to source_sha256 %s, but "
                "that row hashes to %s.  The ledger and the record "
                "disagree about what was written, and nothing is "
                "derived from a record in that state"
                % (row["amendment"], index, row["source_sha256"],
                   recorded))
        if target.get(field) != row["recorded"]:
            raise ManifestError(
                "amendment %s quotes frame %d's %s as %r, but the row "
                "reads %r"
                % (row["amendment"], index, field, row["recorded"],
                   target.get(field)))
        target[field] = row["amended"]
        applied.append((index, field))
    return materialised, tuple(sorted({one for one, _ in applied}))


# ---------------------------------------------------------------------
# The capture attestation ledger
#
# One row per published frame, appended by session.py from the digest
# capture.sh took at the moment of publication.  See DIGEST_FIELDS for
# the schema and why `attested` is part of it rather than implied.
#
# THE LEDGER IS APPEND-ONLY LIKE EVERYTHING ELSE HERE, and for the same
# reason: it is the statement that makes a frame's bytes evidence, so a
# path that could rewrite it would be a path that could re-attest
# substituted pixels.  A frame captured twice at the same index -- a
# retry inside one step -- legitimately produces two rows, and
# verify_frame_digests() takes the LAST row for an index because that is
# the capture that is on disk, while reporting that it happened.
# ---------------------------------------------------------------------

def default_digests_path():
    """Return the capture attestation ledger's path.

    Honours PLAYTHROUGH_FRAME_DIGESTS for the same reason the other
    defaults honour their exports; the value is then held to the same
    containment rules.
    """
    from_env = os.environ.get("PLAYTHROUGH_FRAME_DIGESTS")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), *DIGESTS_REL_PARTS)


def _validated_digests_target(value, root=None):
    """Return an absolute ledger path this module may touch.

    Contained in the approved root, no symlinked component, EXACTLY
    <approved root>/build/frame_digests.jsonl, and a regular file -- the
    same four conditions the manifest and the amendment ledger are held
    to, and condition three for the same reason: containment alone would
    let an export point these appends at another artifact.
    """
    resolved = _validated_path(value, "frame digest ledger path")
    approved = _assert_within_root(
        resolved, "the frame digest ledger path", root)
    _assert_no_symlink(resolved, approved,
                       "the frame digest ledger path")
    canonical = os.path.join(approved, *DIGESTS_REL_PARTS)
    if os.path.realpath(resolved) != canonical:
        raise ManifestError(
            "the frame digest ledger is %s and nothing else, but %s "
            "was given.  Appending attestation rows onto another "
            "artifact would corrupt it and would report success."
            % (canonical, resolved))
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ManifestError(
            "the frame digest ledger path is not a regular file: %s"
            % resolved)
    return resolved


def file_digest(path, label="file"):
    """Return the sha256 of a file's exact bytes, in hex.

    Read in blocks and opened with O_NOFOLLOW: a frame is megabytes and
    a link where a capture belongs is a read somewhere else.
    """
    resolved = _validated_path(path, "%s path" % label)
    digest = hashlib.sha256()
    descriptor = _open_nofollow(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            while True:
                block = handle.read(DIGEST_BLOCK)
                if not block:
                    break
                digest.update(block)
    except OSError as err:
        raise ManifestError(
            "could not hash %s: %s" % (resolved, err)) from err
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return digest.hexdigest()


def _validated_attestation(value):
    """Return one of DIGEST_ATTESTATIONS, or raise."""
    if not isinstance(value, str) or value not in DIGEST_ATTESTATIONS:
        raise ManifestError(
            "a capture attestation is %s, got %r.  How the digest was "
            "established is part of the claim: a digest sealed from a "
            "commit is weaker evidence than one taken as the frame was "
            "published, and recording them alike would hide that"
            % (" or ".join(DIGEST_ATTESTATIONS), value))
    return value


def _validated_git_object(value, label):
    """Return a git object name, or None, or raise."""
    if value is None:
        return None
    if not isinstance(value, str) or not GIT_OBJECT_RE.match(value):
        raise ManifestError(
            "%s must be a git object name (40 or 64 hex digits) or "
            "null, got %r" % (label, value))
    return value


def build_digest_row(frame, file, sha256, byte_count, attested,
                     attested_ts, git_blob=None, git_commit=None):
    """Validate one attestation row and return it in key order.  Pure.

    A "commit" attestation MUST name the blob and the commit it was
    sealed from: a post-hoc seal that named nothing would be an
    assertion, and the whole point of recording the weaker claim is that
    a reader can re-derive it.  A "capture" or "recovery" attestation
    must name neither, because it was taken from the running pipeline and
    a git object would be an invention.
    """
    index = _validated_frame(frame)
    row = {
        "frame": index,
        "file": _validated_file(file, index),
        "sha256": _validated_digest(sha256, "sha256"),
        "bytes": byte_count,
        "attested": _validated_attestation(attested),
        "attested_ts": canonical_real_ts(attested_ts),
        "git_blob": _validated_git_object(git_blob, "git_blob"),
        "git_commit": _validated_git_object(git_commit, "git_commit"),
    }
    if isinstance(row["bytes"], bool) or \
            not isinstance(row["bytes"], int):
        raise ManifestError(
            "the byte count for frame %d is %r, not an integer"
            % (index, byte_count))
    if row["bytes"] <= 0:
        raise ManifestError(
            "the byte count for frame %d is %d; a published frame is "
            "not empty" % (index, row["bytes"]))
    if row["attested"] == DIGEST_AT_COMMIT:
        if not row["git_blob"] or not row["git_commit"]:
            raise ManifestError(
                "frame %d's digest is attested from a commit, so it "
                "must name the blob and the commit it was sealed from; "
                "a post-hoc seal that names nothing is an assertion "
                "rather than evidence a reader can re-derive" % index)
    elif row["git_blob"] or row["git_commit"]:
        raise ManifestError(
            "frame %d's digest is attested at %s, which is taken from "
            "the running pipeline, so it may not name a git object"
            % (index, row["attested"]))
    return {name: row[name] for name in DIGEST_FIELDS}


def encode_digest_row(row):
    """Return one attestation as the exact line to be written."""
    ordered = {name: row[name] for name in DIGEST_FIELDS}
    return json.dumps(ordered, ensure_ascii=False) + "\n"


def append_frame_digest(digests_path, frame, file, sha256, byte_count,
                        attested, attested_ts, git_blob=None,
                        git_commit=None, require_durable=True,
                        root=None):
    """Validate one attestation and APPEND it to the ledger.

    The third and last writer in this module, and it goes through the
    same machinery as the other two: O_NOFOLLOW, a MANDATORY exclusive
    flock, the end-of-file measurement, one whole-line write with
    rollback, and an fsync before the row is reported as stored.
    """
    path = _validated_digests_target(
        default_digests_path() if digests_path is None
        else digests_path, root)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise ManifestError(
            "the directory for the frame digest ledger does not "
            "exist: %s" % parent)
    row = build_digest_row(frame, file, sha256, byte_count, attested,
                           attested_ts, git_blob, git_commit)
    payload = encode_digest_row(row).encode("utf-8")
    descriptor = _open_nofollow(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW)
    try:
        _lock_exclusively(descriptor, path)
        try:
            committed = os.lseek(descriptor, 0, os.SEEK_END)
        except OSError as err:
            raise ManifestError(
                "could not measure the end of the frame digest ledger "
                "%s (%s), so frame %d's attestation was not written"
                % (path, err, row["frame"])) from err
        _assert_row_boundary(descriptor, committed, path, row["frame"])
        _append_whole_row(descriptor, payload, committed, path,
                          row["frame"])
        _fsync(descriptor, path, row["frame"], require_durable)
    finally:
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "digest-close",
                "could not close the frame digest ledger %s after "
                "appending (%s); the row itself was written and forced "
                "to the device before this point" % (path, err))
    return row


def read_frame_digests(digests_path=None, root=None):
    """Return the ledger's rows, in the order they were written.

    An absent ledger yields an empty tuple: a session captured before
    the ledger existed legitimately has none, and the CONSUMERS are
    where that is treated as a missing attestation rather than as
    permission to proceed.
    """
    path = _validated_digests_target(
        default_digests_path() if digests_path is None
        else digests_path, root)
    if not os.path.isfile(path):
        return ()
    rows = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8",
                       newline="") as handle:
            descriptor = None
            for number, raw in enumerate(handle, start=1):
                rows.append(_decode_line(raw, number, path))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return tuple(rows)


def attested_digests(rows):
    """Return {frame: last attestation row} from ledger rows.  Pure.

    THE LAST ROW FOR AN INDEX WINS, because a retry inside one step
    captures the same index twice and the last capture is the one on
    disk.  verify_frame_digests() reports the repeat; this function is
    what a consumer asks "what should frame N hash to".
    """
    latest = {}
    for row in rows:
        index = row.get("frame")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        latest[index] = row
    return latest


def digest_row_problems(rows):
    """Return a list of problems with the ledger's rows.  Pure."""
    problems = []
    seen = {}
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(
                "digest row %d is a %s, not an object"
                % (position, type(row).__name__))
            continue
        missing = [name for name in DIGEST_FIELDS if name not in row]
        extra = [name for name in row if name not in DIGEST_FIELDS]
        if missing:
            problems.append("digest row %d omits %s"
                            % (position, ", ".join(missing)))
        if extra:
            problems.append(
                "digest row %d carries unexpected field(s) %s"
                % (position, ", ".join(sorted(extra))))
        if missing or extra:
            continue
        if list(row) != list(DIGEST_FIELDS):
            problems.append(
                "digest row %d writes its fields in the order %s, not "
                "the declared %s"
                % (position, ", ".join(row), ", ".join(DIGEST_FIELDS)))
        try:
            rebuilt = build_digest_row(
                row["frame"], row["file"], row["sha256"], row["bytes"],
                row["attested"], row["attested_ts"], row["git_blob"],
                row["git_commit"])
        except ManifestError as err:
            problems.append("digest row %d: %s" % (position, err))
            continue
        for name in DIGEST_FIELDS:
            if rebuilt[name] != row[name]:
                problems.append(
                    "digest row %d records %s as %r, which is not its "
                    "canonical form %r"
                    % (position, name, row[name], rebuilt[name]))
        index = row["frame"]
        if index in seen:
            problems.append(
                "frame %d is attested by rows %d and %d; a retry at one "
                "index legitimately produces two, and the LAST is the "
                "capture on disk -- reported so that a repeat is never "
                "silent" % (index, seen[index], position))
        seen[index] = position
    return problems


def verify_frame_digests(rows, digests=None, frames_dir=None,
                         digests_path=None, root=None,
                         require_all=True):
    """Check the frames on disk against their attestations.

    `rows` are the manifest rows -- the ledger is keyed off the RECORD,
    so an attestation for a frame no row mentions is reported and a row
    with no attestation is reported too.  Returns a list of problems;
    an empty list means every recorded frame exists, hashes to the
    digest attested for it, and is the size that attestation names.

    `require_all` False downgrades "this frame has no attestation" from
    a problem to silence, for the one honest case that exists: a session
    captured before this ledger did.  It is never the default, and the
    consumers that must not proceed without attestation leave it True.
    """
    if digests is None:
        digests = read_frame_digests(digests_path, root)
    if frames_dir is None:
        # A NOMINATED ROOT OUTRANKS THE EXPORT, exactly as it does for
        # every other default in this module.  Reading
        # PLAYTHROUGH_FRAMES_DIR here would send a confined caller --
        # a test, or a verifier pointed at a tree it owns -- to hash the
        # REAL session's frames against the ledger it was handed, which
        # is both wrong and a way to touch evidence from a run that was
        # meant to reach nothing.
        frames_dir = (default_frames_dir() if root is None
                      else os.path.join(approved_root(root), "frames"))
    directory = _validated_directory(
        frames_dir, "frames directory", root)
    problems = digest_row_problems(digests)
    latest = attested_digests(digests)
    recorded = set()
    for row in rows:
        index = row.get("frame")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        recorded.add(index)
        path = os.path.join(directory, FRAME_NAME_FORMAT % index)
        attestation = latest.get(index)
        if attestation is None:
            if require_all:
                problems.append(
                    "frame %d is recorded but its bytes are not "
                    "attested: nothing establishes that %s holds the "
                    "pixels that were captured"
                    % (index, FRAME_FILE_FORMAT % index))
            continue
        if not os.path.isfile(path):
            problems.append(
                "frame %d is attested but %s is missing"
                % (index, FRAME_FILE_FORMAT % index))
            continue
        try:
            observed = file_digest(path, "frame")
            size = os.path.getsize(path)
        except (ManifestError, OSError) as err:
            problems.append(
                "frame %d could not be verified against its "
                "attestation: %s" % (index, err))
            continue
        if observed != attestation.get("sha256"):
            problems.append(
                "frame %d is attested as sha256 %s but %s now hashes "
                "to %s: these are not the bytes that were captured"
                % (index, attestation.get("sha256"),
                   FRAME_FILE_FORMAT % index, observed))
        elif size != attestation.get("bytes"):
            problems.append(
                "frame %d is attested as %r byte(s) but %s holds %d"
                % (index, attestation.get("bytes"),
                   FRAME_FILE_FORMAT % index, size))
    for index in sorted(set(latest) - recorded):
        problems.append(
            "the digest ledger attests frame %d, which the record does "
            "not carry" % index)
    return problems


def _decode_line(raw, number, path):
    """Parse one manifest line, or raise with its line number."""
    text = raw.rstrip("\n")
    if text.endswith("\r"):
        raise ManifestError(
            "%s line %d ends CRLF; the manifest is LF only"
            % (path, number))
    if not text.strip():
        raise ManifestError(
            "%s line %d is blank; every line is exactly one row"
            % (path, number))
    try:
        row = json.loads(text)
    except ValueError as err:
        raise ManifestError(
            "%s line %d is not JSON: %s" % (path, number, err)) from err
    if not isinstance(row, dict):
        raise ManifestError(
            "%s line %d is not a JSON object; the manifest is JSON "
            "Lines, not a wrapping array" % (path, number))
    return row


def read_rows(manifest_path=None, root=None):
    """Return every row on disk, in file order.  Read-only.

    Opened for reading only, and the returned dicts are copies, so no
    caller of this module can rewrite the record through it.  Key
    order is preserved as it appears on disk, which is what lets
    verify_manifest() check the declared order of the file itself.

    The path is held to the same approved-root, no-symlink and
    O_NOFOLLOW rules as the append path.  Reading is not harmless: a
    redirected read would report somebody else's file as this
    session's record, and every count and duration downstream would be
    computed from it.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_manifest_target(manifest_path, root)
    if not os.path.isfile(path):
        raise ManifestError("no manifest at %s" % path)
    rows = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        handle = os.fdopen(descriptor, "r", encoding="utf-8", newline="")
    except OSError as err:
        os.close(descriptor)
        raise ManifestError(
            "could not read the manifest %s: %s" % (path, err)) from err
    with handle:
        for number, raw in enumerate(handle, start=1):
            rows.append(_decode_line(raw, number, path))
    return rows


def count_rows(manifest_path=None, root=None):
    """Return the number of rows on disk.  Read-only.

    The count that must equal the number of PNGs in the frames
    directory -- one keystroke, one capture, one row.
    """
    return len(read_rows(manifest_path, root))


def last_recorded_frame(manifest_path=None, root=None):
    """Return the last frame index recorded, or 0 if there is none.

    An observation for the resume branch, not a generator: session.py
    owns the frame counter and this module never increments anything.
    A manifest that does not exist yet answers 0, which is how a fresh
    session is distinguished from a resumed one.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_manifest_target(manifest_path, root)
    if not os.path.isfile(path):
        return 0
    rows = read_rows(path, root)
    if not rows:
        return 0
    last = rows[-1].get("frame")
    if isinstance(last, bool) or not isinstance(last, int):
        raise ManifestError(
            "the last row of %s carries a non-integer frame: %r"
            % (path, last))
    return last


def _shape_problems(path):
    """Report defects in the file's byte shape.  Read-only.

    Opened through the same O_NOFOLLOW descriptor discipline as every
    other read here, so the bytes checked are the bytes of the file
    that was validated and not of something a link points at.
    """
    problems = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        handle = os.fdopen(descriptor, "rb")
    except OSError as err:
        os.close(descriptor)
        raise ManifestError(
            "could not read the manifest %s: %s" % (path, err)) from err
    with handle:
        data = handle.read()
    if not data:
        return ["%s is empty" % path]
    if not data.endswith(b"\n"):
        problems.append("%s does not end with a newline" % path)
    if data.endswith(b"\n\n"):
        problems.append("%s ends with a blank line" % path)
    if b"\r" in data:
        problems.append(
            "%s contains a carriage return; the manifest is LF only"
            % path)
    return problems


def row_field_problems(row, number, narration=True):
    """Report every schema defect in ONE row.  Read-only.

    PUBLIC AND AUTHORITATIVE.  This function -- not a paraphrase of it
    -- is what decides whether a single manifest row is well formed.
    timeline.py gates its whole computation on these rows, and a
    second, weaker copy of these checks living there would mean the
    pipeline had two disagreeing definitions of a valid row, with the
    looser one deciding what gets rendered.  The schema is defined
    here, next to the writer that enforces it, so the reader and the
    writer cannot drift apart.

    THE PAIR, AND WHY IT IS A PAIR.  This function and
    sequence_problems() below are the two halves of the schema: one row
    in isolation, and the 1..n identity across rows.  row_problems() is
    the CANONICAL GATE that applies both to a whole manifest, and it is
    what every other stage calls; these two exist separately so that a
    caller holding one row -- the writer, on its way to appending it --
    can check exactly what it holds without inventing its own rules.
    Nothing outside this module should need to call them directly.

    `number` is the 1-based line number, used only in the messages.
    Nothing is modified, and a returned empty list means this row
    satisfies the six-field schema.

    `narration` decides whether the two checks on the AMENDABLE fields
    -- the voice gate on `commentary` and the placeholder sentinels on
    both narrations -- are applied here.  It defaults to true, so every
    existing caller is held to the whole schema.  It is false in exactly
    one place: timeline.py gates the RECORDED rows without it and then
    applies the full gate to the rows manifest.resolve_rows() returns.
    That is not a relaxation, it is where the check belongs.  A recorded
    narration cannot be edited -- that is the whole of the amendment
    ledger's reason for existing -- so refusing the record for one would
    leave a session with no honest way forward, while the sentence that
    actually reaches the transcript and the caption track is the
    RESOLVED one, which is still refused if it carries a meta word.
    Everything this argument suppresses is checked one step later, on
    the text a reader will actually see.
    """
    problems = []
    if list(row) != list(FIELDS):
        return [
            "row %d carries keys %s; expected exactly %s in that "
            "order" % (number, list(row), list(FIELDS))]
    frame = row["frame"]
    if isinstance(frame, bool) or not isinstance(frame, int):
        problems.append(
            "row %d frame is not an integer: %r" % (number, frame))
    elif frame < MIN_FRAME_INDEX or frame > MAX_FRAME_INDEX:
        problems.append(
            "row %d frame is out of range: %d" % (number, frame))
    elif row["file"] != FRAME_FILE_FORMAT % frame:
        problems.append(
            "row %d file is %r; expected %r"
            % (number, row["file"], FRAME_FILE_FORMAT % frame))
    for name in ("real_ts", "action", "commentary"):
        value = row[name]
        if not isinstance(value, str) or not value.strip():
            problems.append(
                "row %d %s is empty or not a string: %r"
                % (number, name, value))
    real_ts = row["real_ts"]
    if isinstance(real_ts, str) and real_ts.strip():
        try:
            canonical = canonical_real_ts(real_ts)
        except ManifestError as err:
            problems.append(
                "row %d real_ts is malformed: %s" % (number, err))
        else:
            # THE STORED FORM, not merely a parsable one.  The writer
            # normalises whatever it is handed (see canonical_real_ts),
            # so every row THIS module wrote is already canonical and
            # this costs a well-formed record nothing.  What it catches
            # is a row that reached the file another way -- a hand
            # edit, a foreign tool -- in one of the other ISO-8601
            # spellings of the same instant: '...T06:53:55Z' without
            # the milliseconds, a space instead of the 'T', an offset
            # other than 'Z'.  Each of those parses perfectly and each
            # of them destroys the one property the column is FOR: with
            # a single form, a lexical sort of real_ts is a
            # chronological sort, which is what makes "the timestamps
            # never go backwards" a one-line check over the record
            # rather than a parse of every row.  Mixed forms sort
            # wrongly while every value in them is individually
            # correct, so the defect is invisible in any single row and
            # has to be caught here.
            if canonical != real_ts:
                problems.append(
                    "row %d real_ts is %r, which is not the one form "
                    "this column is written in (%r is the same instant "
                    "in it); a lexical sort of the column is only a "
                    "chronological sort while every row shares one "
                    "form" % (number, real_ts, canonical))
    clock = row["ingame_clock"]
    if clock is not None:
        if not isinstance(clock, str) or not clock.strip():
            problems.append(
                "row %d ingame_clock is neither a reading nor null: "
                "%r" % (number, clock))
    # A HARD PROBLEM, not an advisory.  The patterns are precise enough
    # to be one now (META_PATTERNS), and the requirement that meta and
    # "gamey" remarks stay out of the in-character record is not
    # satisfied by a warning nobody reads: a row that carries one is
    # reported by every gate that reads this file, including the
    # committed-artifact suite.
    if narration:
        voice = meta_vocabulary_problem(row["commentary"],
                                        "row %d commentary" % number)
        if voice is not None:
            problems.append(voice)
    # A HARD PROBLEM, like the voice gate above and for a different
    # reason.  See the PLACEHOLDER sentinels beside META_PATTERNS for why
    # the two stay separate: a field marked as not yet filled in is not a
    # record of anything, and every other check here passes straight
    # over it.
    if narration:
        problems.extend(sentinel_problems(
            row["action"], row["commentary"], "row %d" % number))
    return problems


def sequence_problems(rows):
    """Report gaps, repeats and reorderings.  Read-only.

    PUBLIC AND AUTHORITATIVE, for the same reason as row_problems():
    the 1..n identity is what makes one keystroke, one frame and one row
    the same statement, and it is checked here so that every stage
    checks it the same way.
    """
    problems = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            # Already reported as a malformed row; skipping it here
            # keeps every later position honest, because renumbering
            # around it would blame the wrong row for the gap.
            continue
        frame = row.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            continue
        if frame != position:
            problems.append(
                "row %d records frame %d; the indices run 1..n with "
                "no gap, no repeat and no reordering"
                % (position, frame))
    return problems


def row_problems(rows, allow_index_gaps=False, narration=True):
    """Report every schema defect in a sequence of rows.  Pure.

    THE canonical in-memory gate for manifest rows: it applies
    row_field_problems() to every row and sequence_problems() across
    them, which are the only implementations of those rules anywhere in
    the pipeline.  What it holds a manifest to is exactly the six
    declared fields in
    the declared order, an integer index inside the recorded range
    whose `file` is the capture path this module formats from that
    index, a real_ts in the one fixed sortable form, non-empty text
    where text is required, and an `ingame_clock` that is either a
    reading or JSON null.

    Both consumers hold their rows to THIS function.
    verify_manifest() applies it to the file on disk, and timeline.py
    applies it to the rows it is about to pace a film from -- before it
    writes a timeline AND before it attests to one already written --
    so the same defect is reported in the same words wherever it is
    found.  A second, laxer copy of these rules is precisely how a
    manifest error becomes a timeline that quietly filled it in: one
    such copy existed and accepted a row whose `file` named a
    different capture than its `frame`, and a real_ts that was not a
    timestamp at all.

    `allow_index_gaps` suppresses only the 1..n sequence check -- the
    single problem an operator may knowingly accept.  `narration` is
    passed to row_field_problems(), where it is documented: with it
    false the two checks on the amendable narrations are left to the
    caller to apply to the RESOLVED rows, which is what timeline.py
    does, and no other caller passes it.  Every other defect is
    reported unconditionally, and verify_manifest() never passes the
    flag, so `manifest.py verify` reports a gap whatever anybody else
    chose to tolerate.

    Nothing is read from disk, nothing is repaired and nothing is
    rewritten -- the caller decides what a problem means, which for
    this pipeline means refusing to build evidence on top of it.
    """
    problems = []
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(
                "row %d is a %s, not an object"
                % (position, type(row).__name__))
            continue
        problems.extend(row_field_problems(row, position, narration))
    if not allow_index_gaps:
        problems.extend(sequence_problems(rows))
    return problems


def _frame_problems(rows, frames_dir, root=None):
    """Report rows whose capture is missing on disk.  Read-only."""
    problems = []
    directory = _validated_directory(
        frames_dir, "frames directory", root)
    for row in rows:
        frame = row.get("frame")
        if isinstance(frame, bool) or not isinstance(frame, int):
            continue
        # The basename is rebuilt from this module's own format rather
        # than joined from the row's text, so nothing unvalidated ever
        # reaches the filesystem.
        candidate = os.path.join(directory, FRAME_NAME_FORMAT % frame)
        if not os.path.isfile(candidate):
            problems.append(
                "no capture on disk for frame %d: %s"
                % (frame, candidate))
    return problems


def honesty_problems(rows, dates=None):
    """Report every stated time or date the record contradicts.

    THE COMMITTED-RECORD HALF OF THE CLOCK-HONESTY GATE.  session.py
    refuses a sentence before the key is sent; this holds the FILE to the
    same rule afterwards, so a manifest that was assembled some other way
    -- an older session, a hand edit, a run whose gate was bypassed -- is
    still audited by every stage that reads it.

    EACH ROW IS JUDGED AGAINST THE READING ITS AUTHOR HAD IN FRONT OF
    THEM, which is the PREVIOUS row's clock rather than its own.  That is
    not a convenience: `commentary` is the reason the survivor pressed the
    key, so it belongs to the moment BEFORE the key, and the clock on the
    row's own frame is the reading AFTER whatever time that action
    consumed.  Judging "five past eight, so I am going to lie down"
    against the clock that a nine-hour sleep produced would refuse an
    honest sentence.  The first row has nothing before it and is judged
    against its own reading.

    :param rows: the manifest rows, in order.
    :param dates: optional {frame: sidebar date line}, as the telemetry
        sidecar records it.  The manifest schema carries no date column,
        so without this there is no channel through which a date could
        have been observed and date statements are left unadjudicated --
        NOT treated as unreadable, which would refuse every honest
        sentence that names the day.  Supply it and each date statement is
        held to the line beside it.
    """
    problems = []
    check_dates = isinstance(dates, dict) and bool(dates)
    previous_clock = None
    previous_date = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        frame = row.get("frame")
        commentary = row.get("commentary")
        clock = row.get("ingame_clock")
        date_text = None
        if isinstance(dates, dict) and isinstance(frame, int):
            date_text = dates.get(frame)
        against_clock = (clock if previous_clock is None
                         else previous_clock)
        against_date = (date_text if previous_date is None
                        else previous_date)
        problems.extend(clock_honesty_problems(
            commentary, against_clock, against_date,
            "row %s commentary" % frame, check_dates=check_dates,
            also_clock=clock, also_date=date_text))
        previous_clock = clock
        if date_text:
            previous_date = date_text
    return problems


def verify_manifest(manifest_path=None, frames_dir=None,
                    require_frames=False, root=None):
    """Return a list of problems with the manifest.  Read-only.

    An empty list means the file satisfies the schema, the byte shape,
    the one-row-per-frame invariant, the voice gate and the clock-honesty
    gate.  The schema half is row_problems(), the shared gate timeline.py
    holds its rows to as well, and honesty_problems() holds each row's
    stated times and dates to the readings recorded beside them; this
    function adds the checks that need the FILE -- its byte shape, and
    with `require_frames` the existence of the capture each row names --
    rather than restating the row rules.  Nothing is repaired, reordered
    or rewritten: a problem is reported so that a human can decide, which
    for this file means an amendment in playthrough/amendments.jsonl
    rather than an edit here.

    WHERE THE TWO NARRATION GATES ARE APPLIED, and why it is not here on
    the recorded text.  A recorded row is never edited, so the only
    honest remedy for a meta word or a placeholder sentinel in one is an
    amendment -- and the sentence a reader actually meets, in
    playthrough/transcript.md and on the caption track, is the RESOLVED
    one.  So the recorded rows are held to the structural schema, the
    resolved rows are held to the whole of it, and a defect with no
    amendment behind it is still reported because resolving leaves it
    exactly where it was.  With no ledger the two sets are the same rows
    and this is indistinguishable from checking them once.
    """
    if manifest_path is None:
        manifest_path = default_manifest_path()
    path = _validated_manifest_target(manifest_path, root)
    if not os.path.isfile(path):
        return ["no manifest at %s" % path]
    try:
        rows = read_rows(path, root)
    except ManifestError as err:
        return [str(err)]
    problems = _shape_problems(path)
    problems.extend(row_problems(rows, narration=False))
    resolved = rows
    # The ledger beside THIS manifest, named the way timeline.py names
    # it: derived from the approved root when one is given, so a
    # sandboxed caller checks its own ledger and not the repository's.
    ledger = (default_amendments_path() if root is None else
              os.path.join(approved_root(root), AMENDMENTS_NAME))
    ledger_problems = verify_amendments(ledger, path, root)
    if ledger_problems:
        problems.extend(ledger_problems)
    else:
        try:
            resolved, _ = resolve_rows(
                rows, read_amendments(ledger, root))
        except ManifestError as err:
            problems.append(
                "the amendment ledger does not apply to this record: "
                "%s" % err)
            resolved = rows
    problems.extend(row_problems(resolved))
    problems.extend(honesty_problems(resolved))
    if require_frames:
        if frames_dir is None:
            frames_dir = default_frames_dir()
        problems.extend(_frame_problems(rows, frames_dir, root))
    _check_frame_format_contract()
    return problems


def verify_amendments(amendments_path=None, manifest_path=None,
                      root=None):
    """Return a list of problems with the amendment ledger.  Read-only.

    An empty list means the ledger is either absent -- the ordinary
    case for a session with nothing to amend -- or that every row
    satisfies the nine-field schema in its declared order, the
    numbering runs 1..n, no narration is amended twice, every amended
    value would itself be a valid field, and every `source_sha256`
    matches the sha256 of the manifest line it names.

    The digest half is the reason this is a verifier rather than a
    schema check: it is what turns "the ledger claims to correct this
    row" into "the ledger corrects THIS row, byte for byte".
    """
    ledger = _validated_amendments_target(
        default_amendments_path() if amendments_path is None
        else amendments_path, root)
    if not os.path.isfile(ledger):
        return []
    try:
        amendments = read_amendments(ledger, root)
    except ManifestError as err:
        return [str(err)]
    try:
        digests = row_digests(manifest_path, root)
        rows = read_rows(manifest_path, root)
    except ManifestError as err:
        return ["the amendment ledger cannot be checked against the "
                "record: %s" % err]
    problems = amendment_problems(amendments, digests)
    if problems:
        return problems
    # AND THE AMENDED RECORD IS HELD TO THE RULES THE RECORDED ONE IS.
    # An amendment reaches the transcript and the caption track, so an
    # amended sentence that stated a time the frames do not support, or
    # an amended action that lost its derived shape, would be exactly
    # the fabrication this ledger exists to make impossible.  The gates
    # are therefore re-run over the RESOLVED rows rather than trusted to
    # the shape checks above.
    try:
        resolved, _ = resolve_rows(rows, amendments, digests)
    except ManifestError as err:
        return ["the amendment ledger cannot be applied: %s" % err]
    problems.extend(row_problems(resolved))
    problems.extend(honesty_problems(resolved))
    return problems


def _build_parser():
    """Return the read-only command line parser."""
    parser = argparse.ArgumentParser(
        prog="manifest.py",
        description=(
            "Inspect playthrough/manifest.jsonl.  Appending is "
            "available to importers only, so that session.py keeps "
            "sole ownership of the frame counter."))
    parser.add_argument(
        "--manifest", default=None, metavar="PATH",
        help=("the manifest to read; defaults to PLAYTHROUGH_MANIFEST "
              "or <repository>/playthrough/manifest.jsonl.  It must "
              "resolve to exactly that file: the record of a session "
              "has one location, and any other path -- including "
              "another artifact inside playthrough/ -- is refused"))
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify",
        help=("check the six-field schema, the byte shape and the "
              "1..n frame sequence"))
    verify.add_argument(
        "--frames-dir", default=None, metavar="DIR",
        help=("the captures to check against; defaults to "
              "PLAYTHROUGH_FRAMES_DIR or "
              "<repository>/playthrough/frames"))
    verify.add_argument(
        "--require-frames", action="store_true",
        help="also require the capture named by every row to exist")
    commands.add_parser(
        "count", help="print the number of rows on stdout")
    amendments = commands.add_parser(
        "amendments",
        help=("check the amendment ledger's schema, its numbering and "
              "the digest binding every row to the line it amends"))
    amendments.add_argument(
        "--ledger", default=None, metavar="PATH",
        help=("the amendment ledger to read; defaults to "
              "PLAYTHROUGH_AMENDMENTS or "
              "<repository>/playthrough/amendments.jsonl"))
    digests = commands.add_parser(
        "digests",
        help=("check every recorded frame against the sha256 the "
              "capture attestation ledger holds for it"))
    digests.add_argument(
        "--ledger", default=None, metavar="PATH",
        help=("the capture attestation ledger to read; defaults to "
              "PLAYTHROUGH_FRAME_DIGESTS or "
              "<repository>/playthrough/build/frame_digests.jsonl"))
    digests.add_argument(
        "--frames-dir", default=None, metavar="DIR",
        help=("the captures to hash; defaults to "
              "PLAYTHROUGH_FRAMES_DIR or "
              "<repository>/playthrough/frames"))
    digests.add_argument(
        "--allow-unattested", action="store_true",
        help=("do not report a recorded frame that has no attestation "
              "at all.  For a session captured before the ledger "
              "existed; never for one that must be trusted"))
    return parser


def main(argv=None, root=None):
    """Run the read-only command line and return an exit status.

    `root` is call-site only, exactly as it is on every function above:
    it relocates the approved tree for a caller that owns a temporary
    directory, and neither the environment nor the command line can
    reach it.  The rules a relocated run is held to are the production
    rules, unchanged.
    """
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "count":
            print(count_rows(args.manifest, root))
            return 0
        if args.command == "amendments":
            problems = verify_amendments(
                args.ledger, args.manifest, root=root)
            total = 0 if problems else len(
                read_amendments(args.ledger, root))
            for problem in problems:
                print("manifest.py: %s" % problem, file=sys.stderr)
            if problems:
                print("manifest.py: %d problem(s) found"
                      % len(problems), file=sys.stderr)
                return 1
            print("amendments ok: %d amendment(s)" % total)
            return 0
        if args.command == "digests":
            rows = read_rows(args.manifest, root)
            ledger = read_frame_digests(args.ledger, root)
            problems = verify_frame_digests(
                rows, ledger, frames_dir=args.frames_dir, root=root,
                require_all=not args.allow_unattested)
            for problem in problems:
                print("manifest.py: %s" % problem, file=sys.stderr)
            if problems:
                print("manifest.py: %d problem(s) found"
                      % len(problems), file=sys.stderr)
                return 1
            print("digests ok: %d frame(s) attested, %d row(s)"
                  % (len(attested_digests(ledger)), len(ledger)))
            return 0
        problems = verify_manifest(
            args.manifest,
            frames_dir=args.frames_dir,
            require_frames=args.require_frames,
            root=root)
        total = count_rows(args.manifest, root) if not problems else 0
    except ManifestError as err:
        print("manifest.py: %s" % err, file=sys.stderr)
        return 1
    for problem in problems:
        print("manifest.py: %s" % problem, file=sys.stderr)
    if problems:
        print("manifest.py: %d problem(s) found" % len(problems),
              file=sys.stderr)
        return 1
    print("manifest ok: %d row(s)" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
