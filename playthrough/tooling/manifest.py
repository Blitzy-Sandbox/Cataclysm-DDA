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

A row carrying an unexpected key or missing a required one is refused
rather than written.  Durations, transition flags and caption cue windows
belong to playthrough/timeline.json, the single source of truth for
timing; recording them here as well would create the second source of
truth the pipeline exists to avoid.  Engineering and diagnostic
observations belong to playthrough/TECHNICAL_NOTES.md.

A RECORDED ROW IS NEVER EDITED, AND THIS MODULE HOLDS NO CODE THAT
COULD.  There is no rewrite, no read-modify-write, no truncate and no
"w" mode anywhere: the only write is :func:`append_row`, and the only
other writer is :func:`append_amendment`, which appends to a DIFFERENT
file.  A path that rebuilt the manifest through a temporary and renamed
it over the original would be a defect however carefully it was guarded,
because a mechanism that CAN rewrite captured evidence is the hazard.

CORRECTIONS ARE AMENDMENTS, IN THEIR OWN APPEND-ONLY LEDGER at
playthrough/amendments.jsonl, each keyed to the sha256 of the immutable
manifest line it corrects:

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
``source_sha256`` still matches the row on disk.  A digest that does not
match is a refusal, not a skip -- a stale amendment means the two records
disagree about history, and that is exactly the condition nothing
downstream may paper over.

``ingame_clock`` IS THE HONESTY FIELD.  ``display::time_string()``
(src/display.cpp:207-218) returns an exact time only when the survivor
has a watch; otherwise one of the coarse phrases from
``display::time_approx()`` (src/display.cpp:159-185), otherwise "???".
Under the seeded 24_HOUR=24h option an exact reading is fixed-width
"%02d:%02d:%02d" (src/calendar.cpp:638-663), which is what makes it
legible at all.  When the clock could not be read the value is None and
serialises as JSON null.  It is never interpolated, never carried forward
from the previous row and never guessed; reconciling an unreadable or
non-monotonic reading is timeline.py's job, downstream and visibly
flagged.  This module records what was seen.

THE WRITE CONTRACT.  A row is not reported as appended until it has been
written, flushed AND forced to the device; a failure anywhere on that
path raises ManifestError rather than being downgraded to a warning,
because the frame-count identity is checked against this file.
``real_ts`` is mandatory and taking it is deliberately the caller's act:
the instant a row is appended is not the instant the frame was captured,
and quietly recording one as the other is fabricated evidence.

THE COMMAND LINE IS READ-ONLY on purpose -- appending is available to
importers only, so session.py keeps sole ownership of the frame counter
and no shell caller can slip a row in beside it::

    . playthrough/tooling/env.sh
    MF='playthrough/tooling/manifest.py'
    "$PLAYTHROUGH_PYTHON" -B "$MF" verify --require-frames
    "$PLAYTHROUGH_PYTHON" -B "$MF" count
    "$PLAYTHROUGH_PYTHON" -B "$MF" amendments
    "$PLAYTHROUGH_PYTHON" -B "$MF" digests --require-frames

Where the record may live is not negotiable.  Every path this module
opens -- for reading as well as for appending -- must resolve inside the
playthrough/ directory derived from this module's OWN location, with no
symlinked component, and is opened with O_NOFOLLOW.  PLAYTHROUGH_MANIFEST,
PLAYTHROUGH_FRAMES_DIR and a --manifest argument are honoured within that
tree and refused outside it: a record an environment variable could
redirect to /etc/passwd, to a device node or to somebody else's checkout
would not be evidence of anything.  The append is serialised with an
exclusive fcntl advisory lock that is MANDATORY -- a lock that cannot be
taken refuses the write rather than proceeding unserialised -- so two
writers coming through this module cannot interleave a row, and a failed
append's rollback cannot remove bytes the other put there.  Being
advisory it says nothing about a reader that does not take it, which is
why the readers refuse an unparseable line instead of trusting the lock.

Standard library only -- nothing here needs
playthrough/tooling/requirements.txt.  fcntl makes this POSIX-only, which
matches the pipeline's Linux/X11 scope.  Paths follow
playthrough/tooling/env.sh, the single definition of the artifact layout,
whose PLAYTHROUGH_MANIFEST, PLAYTHROUGH_FRAMES_DIR and
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
import time


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

# THE STAGING PREFIX, WHICH NOW ONLY EVER GETS SWEPT.  THERE IS NO WRITER
# BEHIND IT ANY MORE, AND THAT IS THE POINT.
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

# playthrough/build/frame_digests.jsonl -- the capture attestation ledger,
# beside the telemetry sidecar it corroborates rather than beside the frames it
# describes.  WHY IT EXISTS.
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

# real_ts: the wall-clock instant of the capture, in UTC, to the millisecond,
# in one fixed form on every row so that the column sorts lexically as well as
# chronologically.  Production metadata only -- video pacing comes from the
# in-game clock, never from here.
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

# Bounds on the free-text fields, both about what happens to these strings
# AFTER this file: `action` and `commentary` are copied into
# playthrough/transcript.md and become the SRT cue text.  MAX_FIELD_LENGTH is a
# refusal and is set far above anything a person writes, so it catches machine
# output and runaway loops without ever arguing with legitimate prose.
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
# THE GATE REFUSES RATHER THAN WARNS, before the key is sent and before
# the transcript is published.  A warning on stderr during a session that
# produces four hundred rows is a warning nobody reads, and by the time
# anybody does the row is already evidence -- and evidence is not
# rewritten afterwards.
#
# WHY PATTERNS RATHER THAN SUBSTRINGS.  A substring is too blunt to
# refuse on: "frame" also matches "the frame of the door", which is the
# survivor's own words about a doorway.  Each entry below is therefore a
# regular expression written to match the META sense and not the in-world
# one, and the two hardest cases are called out where they are handled:
#
#   * `engine` matches `\bengines?\b` and `\bengine's\b`, which does NOT
#     match "engineer" or "engineering" -- the survivor of the recording
#     a survivor whose trade is engineering says so in their own words.
#     The bluntness that remains is deliberate: a survivor on foot has no
#     reason to name a motor, and "the engine" is how the software gets
#     talked about.
#   * `frame` matches only a frame with a NUMBER or a frame that is
#     counted or indexed.  A door frame is the survivor's own.
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
    # The interface, as an interface rather than as what the survivor
    # can see.
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
    # A row can name no software at all and still be out of character by
    # naming the input device or the screen furniture the survivor was
    # looking at (the first key tried, a cursor moving down a list, a tab,
    # the sex field, the trait page), by accounting for the survivor's own
    # body in the numbers the creator prices it in ("Stat money", "thirty
    # -eight points", "three points back"), or by naming an engine mode by
    # its interface name ("safe mode", "Scores").  None of that is a
    # survivor's sentence -- a survivor has a body, a trade and a list of
    # things wrong with them, not statistics.
    #
    # The same precision rule applies as above, and two cases are worth
    # calling out because the blunt reading would refuse honest prose:
    #
    #   * `keyboard` matches the DEVICE and named keys, not a key that
    #     opens something: "something with keys in it and a clear road"
    #     is a set of car keys and is the survivor's.
    #   * `character sheet` matches a point that is COUNTED or POOLED,
    #     not the idiom: "no point being coy" and "a nip point on the
    #     third floor" are the survivor's own prose and must stay.
    #
    # `tab`, `score` and `per cent` are blocked outright, ambiguity and
    # all, under the rule stated above: a survivor has no in-world tab,
    # says "dozens" rather than "scores", and a percentage is arithmetic
    # somebody else did about them.
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
# META_PATTERNS gate beside it, but for a different reason and with a different
# remedy: a row is the authoritative record of what one keystroke did and why,
# and every structural check -- the six-field schema, the 1..n identity, the
# frame-set equality -- passes straight over a field reading "placeholder".
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

# "press '<key>'", optionally followed by the separator and a reason.  The key
# itself is one or more non-quote characters -- which keysym names may be SENT
# is session.py's vocabulary and is validated there against the string that
# reaches xdotool; what is checked here is that the row names a keystroke at
# all.
_ACTION_SHAPE_RE = re.compile(
    r"\Apress '[^'\n]+'(?: -- (?! )(?:(?! -- ).)+)?\Z")


class ManifestError(Exception):
    """A row was refused, or a manifest on disk is malformed."""


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
    """Return the repository root, from this module's own location."""
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

    A RELATIVE INPUT IS ANCHORED TO THE CHECKOUT, NOT TO THE PROCESS
    WORKING DIRECTORY.  `repo_root()` is derived from this module's own
    location, so anchoring the other half of the comparison to the
    working directory made the answer depend on where the caller
    happened to stand: run from `playthrough/tooling/`, this function
    reported `playthrough/manifest.jsonl` as
    `playthrough/tooling/playthrough/manifest.jsonl` -- a path that does
    not exist -- and a test asserting the honest answer failed for a
    reason that had nothing to do with what it was measuring.  Every
    relative path this pipeline passes here is already spelled from the
    checkout root (README.md makes a repo-root working directory a
    source-level requirement), so joining it onto the root is what the
    caller meant in the first place.  An absolute input is resolved as
    given, which is unchanged.
    """
    if path is None:
        return ""
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    text = str(path)
    if not text:
        return ""
    base = repo_root()
    if os.path.isabs(text):
        resolved = os.path.realpath(text)
    else:
        resolved = os.path.realpath(os.path.join(base, text))
    if resolved == base:
        return "."
    if resolved.startswith(base + os.sep):
        return os.path.relpath(resolved, base)
    return "<outside the checkout>/" + os.path.basename(resolved)


def approved_root(root=None):
    """Return the only directory tree this module may read or write."""
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


# ---------------------------------------------------------------------
# THE MUTATION LOCK -- THE PYTHON HALF OF ONE CHECKOUT-WIDE LOCK
#
# env.sh owns the shell half and documents the whole design; this is the
# same lock, at the same path, so that a Python producer and a shell
# committer genuinely exclude each other.  It lives HERE rather than in
# session.py or timeline.py because both of those import this module and
# neither imports the other -- and two implementations of one lock is
# two locks.
#
# THE PATH HAS TO AGREE WITH THE SHELL'S TO THE BYTE, or the two halves
# lock different files and the exclusion is imaginary.  The shell builds
# it as $PLAYTHROUGH_LOCK_DIR/mutation-<d>.lock where <d> is the first
# eight hex digits of the sha256 of $PLAYTHROUGH_REPO_ROOT; the
# derivation below is the same expression with the same inputs, taking
# the checkout as the parent of the approved root -- which is what
# $PLAYTHROUGH_REPO_ROOT is, verified by measurement rather than assumed.
# Passing `root` gives a test its own lock for its own temporary tree,
# exactly as it gives it its own approved root.
#
# READING PLAYTHROUGH_LOCK_DIR FROM THE ENVIRONMENT IS DELIBERATE, and it
# is not the trust approved_root() refuses to place in a variable.  This
# is the RUNTIME directory -- scratch, locks, the cookie -- not the
# evidence tree; session.py and timeline.py already resolve their scratch
# the same way, for the same reason, and it is the only way a sourced
# pipeline and a bare invocation can agree on where the lock is.  A
# nominated directory is still verified before use.
# ---------------------------------------------------------------------

ENV_LOCK_DIR = "PLAYTHROUGH_LOCK_DIR"
ENV_RUNTIME_DIR = "PLAYTHROUGH_RUNTIME_DIR"
ENV_XDG_RUNTIME_DIR = "XDG_RUNTIME_DIR"
ENV_MUTATION_HELD = "PLAYTHROUGH_MUTATION_LOCK_HELD"
ENV_MUTATION_FD = "PLAYTHROUGH_MUTATION_LOCK_FD"

RUNTIME_DIR_NAME = "playthrough"
LOCK_DIR_NAME = "lock"
MUTATION_LOCK_BASENAME = "mutation"
MUTATION_SHARED = "shared"
MUTATION_EXCLUSIVE = "exclusive"

# Generous, because the other role legitimately holds it for minutes: a
# render, a long checkpoint, a gate reading every frame.  An unbounded
# wait would be a hang nobody could diagnose.
MUTATION_LOCK_TIMEOUT = 900.0
MUTATION_LOCK_POLL = 0.1


def _verified_runtime_dir(path, label):
    """Create `path` mode 0700 and refuse a link or a foreign owner.

    The same rule env.sh's playthrough_secure_dir applies: a directory
    another account can write to is a directory another account can plant
    a lock in, and a lock somebody else can plant is not a lock.
    """
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError as err:
        raise ManifestError(
            "cannot create %s at %s: %s" % (label, path, err)) from err
    try:
        info = os.lstat(path)
    except OSError as err:
        raise ManifestError(
            "cannot inspect %s at %s: %s" % (label, path, err)) from err
    if stat.S_ISLNK(info.st_mode):
        raise ManifestError(
            "%s at %s is a symbolic link; refused, because a link there "
            "redirects whatever is written through it" % (label, path))
    if not stat.S_ISDIR(info.st_mode):
        raise ManifestError(
            "%s at %s is not a directory" % (label, path))
    if info.st_uid != os.getuid():
        raise ManifestError(
            "%s at %s is owned by uid %d, not by uid %d"
            % (label, path, info.st_uid, os.getuid()))
    if info.st_mode & 0o022:
        try:
            os.chmod(path, info.st_mode & ~0o022)
        except OSError as err:
            raise ManifestError(
                "%s at %s is mode %04o, so another account can write "
                "into it, and it could not be tightened: %s"
                % (label, path, info.st_mode & 0o7777, err)) from err
    return path


def mutation_lock_dir():
    """Return the verified directory this checkout's locks live in."""
    nominated = os.environ.get(ENV_LOCK_DIR, "").strip()
    if nominated:
        return _verified_runtime_dir(nominated, "the pipeline lock "
                                                "directory")
    runtime = os.environ.get(ENV_RUNTIME_DIR, "").strip()
    if not runtime:
        xdg = os.environ.get(ENV_XDG_RUNTIME_DIR, "").strip()
        if xdg:
            runtime = os.path.join(xdg, RUNTIME_DIR_NAME)
        else:
            runtime = os.path.join(
                "/tmp", "%s-%d" % (RUNTIME_DIR_NAME, os.getuid()))
    _verified_runtime_dir(runtime, "the pipeline runtime directory")
    return _verified_runtime_dir(
        os.path.join(runtime, LOCK_DIR_NAME),
        "the pipeline lock directory")


def mutation_lock_path(root=None):
    """Return this checkout's mutation lock file."""
    checkout = os.path.dirname(approved_root(root))
    digest = hashlib.sha256(
        checkout.encode("utf-8")).hexdigest()[:8]
    return os.path.join(
        mutation_lock_dir(),
        "%s-%s.lock" % (MUTATION_LOCK_BASENAME, digest))


def _mutation_mode(mode):
    """Return `mode` as one of the two words, or refuse it."""
    if mode not in (MUTATION_SHARED, MUTATION_EXCLUSIVE):
        raise ManifestError(
            "%r is not a mutation lock mode; producers take it %r and "
            "the verifier and the committer take it %r"
            % (mode, MUTATION_SHARED, MUTATION_EXCLUSIVE))
    return mode


def _mutation_satisfies(want, have):
    """True when a hold in mode `have` covers a request for `want`.

    Exclusive covers both; shared covers only shared.  The asymmetry is
    the point: a stage that needs the tree to itself must not proceed on
    a shared hold, because a producer may be writing beside it.
    """
    if have == MUTATION_EXCLUSIVE:
        return True
    return want == MUTATION_SHARED


def mutation_lock_inherited(mode, root=None):
    """Return True when a verified ancestor already holds this lock."""
    want = _mutation_mode(mode)
    have = os.environ.get(ENV_MUTATION_HELD, "").strip()
    if not have:
        return False
    if have not in (MUTATION_SHARED, MUTATION_EXCLUSIVE):
        raise ManifestError(
            "%s is %r, which is not a lock mode.  It is set by the "
            "stage that takes the mutation lock and read by every stage "
            "that stage starts; a value nothing produced means the "
            "environment was edited, so this stage refuses rather than "
            "deciding for itself whether the tree is quiescent"
            % (ENV_MUTATION_HELD, have))
    if not _mutation_satisfies(want, have):
        raise ManifestError(
            "this stage needs the mutation lock %sly and an ancestor "
            "holds it %sly.  A shared hold does not make the tree "
            "quiescent -- another producer may be writing under it right "
            "now -- and upgrading in place deadlocks when two holders "
            "upgrade at once" % (want, have))
    raw = os.environ.get(ENV_MUTATION_FD, "").strip()
    if not raw.isdigit():
        raise ManifestError(
            "an ancestor claims to hold the mutation lock %sly but %s "
            "is %r, so there is no descriptor to check the claim against"
            % (have, ENV_MUTATION_FD, raw))
    path = mutation_lock_path(root)
    try:
        link = os.readlink("/proc/self/fd/%s" % raw)
    except OSError:
        link = ""
    if link != path:
        raise ManifestError(
            "an ancestor claims to hold the mutation lock on descriptor "
            "%s, but that descriptor is %s rather than %s.  An "
            "inherited descriptor is the only evidence a child has that "
            "its parent holds the lock, and this one is not it"
            % (raw, link or "not open", path))
    if not _mutation_is_held(path):
        raise ManifestError(
            "an ancestor claims to hold the mutation lock at %s, but "
            "the kernel says nothing holds it.  The claim is stale or "
            "false; either way this stage will not proceed as though "
            "the tree were quiescent" % path)
    return True


def _mutation_is_held(path):
    """True when some process holds `path`, asked on a fresh handle."""
    try:
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC,
            0o600)
    except OSError:
        return False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


class MutationLock:
    """This checkout's quiescence, taken as a context manager."""

    def __init__(self, mode=MUTATION_SHARED, root=None,
                 timeout=MUTATION_LOCK_TIMEOUT):
        self.mode = _mutation_mode(mode)
        self.timeout = float(timeout)
        self._root = root
        self._path = None
        self._descriptor = None
        self._inherited = False

    @property
    def path(self):
        """The lock file, once resolved."""
        return self._path

    @property
    def inherited(self):
        """True when an ancestor's hold was proved and reused."""
        return self._inherited

    @property
    def held(self):
        """True while this object is inside its critical section."""
        return self._descriptor is not None or self._inherited

    def acquire(self):
        """Take the lock, or prove an ancestor already holds one."""
        if self.held:
            return self
        if mutation_lock_inherited(self.mode, self._root):
            self._inherited = True
            self._path = mutation_lock_path(self._root)
            return self
        self._path = mutation_lock_path(self._root)
        try:
            descriptor = os.open(
                self._path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600)
        except OSError as err:
            raise ManifestError(
                "cannot open the mutation lock %s: %s"
                % (self._path, err)) from err
        operation = (fcntl.LOCK_SH if self.mode == MUTATION_SHARED
                     else fcntl.LOCK_EX)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
                self._descriptor = descriptor
                return self
            except OSError as err:
                if err.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(descriptor)
                    raise ManifestError(
                        "could not lock %s: %s"
                        % (self._path, err)) from err
            if time.monotonic() >= deadline:
                os.close(descriptor)
                raise ManifestError(
                    "another stage has held this checkout's mutation "
                    "lock %s against a %s acquisition for more than "
                    "%.0fs.  Producers hold it shared and the gate and "
                    "the checkpoint hold it exclusive, so this is a "
                    "stage of the other kind still running over the "
                    "same working tree -- wait for it rather than "
                    "working beside it"
                    % (self._path, self.mode, self.timeout))
            time.sleep(MUTATION_LOCK_POLL)

    def release(self):
        """Drop the lock, if this object took it. Idempotent."""
        self._inherited = False
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, kind, value, trace):
        self.release()
        return False


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
    """Refuse `resolved` if it or a component below `root` is a link."""
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
    """Return the manifest this pipeline writes and reads."""
    from_env = os.environ.get("PLAYTHROUGH_MANIFEST")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), MANIFEST_NAME)


def default_frames_dir():
    """Return the directory holding one PNG per keystroke."""
    from_env = os.environ.get("PLAYTHROUGH_FRAMES_DIR")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), "frames")


def _validated_path(value, label):
    """Return `value` as an absolute file path, or raise."""
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
    """Return an absolute manifest path that is safe to append to."""
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
    """Warn once if env.sh's frame format has drifted from ours."""
    from_env = os.environ.get("PLAYTHROUGH_FRAME_FORMAT")
    if from_env and from_env != FRAME_NAME_FORMAT:
        _warn_once(
            "frame-format",
            "PLAYTHROUGH_FRAME_FORMAT is %r but this writer records "
            "%r; the capturer and the manifest have to agree byte "
            "for byte" % (from_env, FRAME_NAME_FORMAT))


def _reject_line_breaks(value, label):
    """Raise if `value` spans more than one line."""
    if "\n" in value or "\r" in value:
        raise ManifestError(
            "%s must be a single line: one row is one JSON object on "
            "one line" % label)


def _reject_control_characters(value, label):
    """Raise if `value` carries a control character."""
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
    """Raise if `value` is far longer than anything observed can be."""
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
    """True when `value` is a time an in-game clock could display."""
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
    """Return the clock reading exactly as it was read, or None."""
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
    """Return the out-of-character CONCEPTS `text` carries, in order."""
    if not isinstance(text, str):
        return []
    return [name for name, expression in _META_RES
            if expression.search(text)]


def meta_vocabulary_problem(text, label="commentary"):
    """Return the refusal for an out-of-character `text`, or None."""
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
        "why the survivor acted.  The text was: %r"
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

# "it is", "it's", "it is now", "the clock reads/says/shows", "the time is",
# "today is", "the date is".  Present tense, first person or instrument: the
# forms in which a person states the case rather than recalling, planning or
# measuring one.
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
    """Return seconds since midnight for a 12- or 24-hour statement."""
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

    ONLY AN ASSERTION OF THE PRESENT IS RETURNED -- a time introduced by
    "it is", "it's", "the clock reads" or "the time is", and beginning
    within ASSERTION_TIME_WINDOW characters of it.  A time merely
    mentioned is NOT returned: see the note above _ASSERTION_RE for the
    42 honest sentences that taught this restriction, and for what covers
    that ground instead.
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
    """Return each (day, month) `text` ASSERTS. Read-only.

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
    """Return (day, month) read out of a sidebar date line, or None."""
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
    :param clock: the reading the sentence's author had in front of them -- the
        previous frame's, since the commentary explains why the next key is
        about to be pressed.
    :param date_text: the sidebar date line for the same frame.
    :param label: what a message calls the field.
    :param check_dates: False says THE CALLER HOLDS NO DATE EVIDENCE AT ALL,
        which is different in kind from a date line that could not be read.
    :param also_clock: a SECOND observed reading the statement may agree with
        instead -- the frame the caption is displayed over, which the auditing
        callers have and the writing caller does not, because at write time the
        key has not been sent yet.
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
                "is not recorded as though they could.  The text was: %r"
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
    """Return the placeholder markers in `text`, sorted."""
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
    """Report every way these two fields fail to be a record."""
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


# ---------------------------------------------------------------------
# RAW MARKUP, WHICH IS A PUBLICATION HAZARD RATHER THAN A STYLE RULE
#
# Every string in these two fields is copied VERBATIM into
# playthrough/transcript.md, and Markdown passes raw HTML straight
# through to whatever renders it.  Applying the guard that knows this --
# make_srt.assert_no_raw_markup -- to the transcript's generated HEADING
# alone lets a commentary reading `<img src=x onerror=...>` reach the
# committed document, because the narrower caption gate looks for
# styling tags and override codes and `img` is not a styling tag.
#
# So the rule lives HERE, beside the other content rules, and is applied
# at the two moments text ENTERS the record -- build_row() and
# build_amendment() -- as well as at publication.  Refused rather than
# escaped, deliberately: these artifacts are evidence, and a title or a
# sentence carrying markup is a fault to report rather than a string to
# clean.  The same reasoning is written out at
# make_srt.SURVIVOR_NAME_PUNCTUATION for the survivor's name.
#
# DELIBERATELY NARROW, and not a general sanitiser: an angle bracket, an
# ampersand, or an `onsomething=` attribute.  A keystroke description and
# a survivor's sentence have no legitimate use for any of the three --
# measured over the delivered record, which carries none of them in any
# of its 307 rows or 202 amendments -- so each one means something has
# gone wrong upstream rather than that a document needs cleaning.
#
# THE READER IS NOT GIVEN THIS RULE, for the reason action_shape_problem
# gives above: a reader that refuses is a reader that turns a foreign row
# into an unreadable manifest instead of a reported one.  The writer
# refuses, the publisher refuses, and row_field_problems() goes on being
# able to READ anything and say what is wrong with it.
RAW_MARKUP_CHARACTERS = (
    ("<", "an angle bracket, which opens an HTML tag"),
    (">", "an angle bracket, which closes an HTML tag"),
    ("&", "an ampersand, which opens an HTML entity"),
)

# An HTML event-handler attribute -- `onerror=`, `onload=` -- which
# executes in a permissive renderer even where the tag itself was
# stripped.  Held separately from the characters above so a payload that
# arrives without brackets is still refused.
EVENT_HANDLER_RE = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)


def raw_markup_problem(value, label="commentary"):
    """Report text that a renderer would EXECUTE rather than show.

    :returns: the problem, or None when the text is safe to publish.
    """
    if not isinstance(value, str):
        return None
    for needle, why in RAW_MARKUP_CHARACTERS:
        if needle in value:
            return (
                "%s carries %s (%r): %r.  This string is copied "
                "verbatim into playthrough/transcript.md, and Markdown "
                "passes raw HTML to the renderer, so it is refused "
                "rather than escaped -- the transcript is evidence, and "
                "a sentence carrying markup is a fault to report rather "
                "than a string to clean.  Say it in words"
                % (label, why, needle, value))
    if EVENT_HANDLER_RE.search(value):
        return (
            "%s carries an HTML event-handler attribute, which would "
            "execute in a permissive renderer: %r" % (label, value))
    return None


# The words a narration is measured in: letters, digits and the
# apostrophe that holds a contraction together.  The same expression the
# acceptance gate counts with, so the writer and the gate cannot
# disagree about what a word is.
NARRATION_WORD_RE = re.compile(r"[0-9a-z']+")


def narration_words(value):
    """Return the comparable words of one narration, lowercased."""
    if not isinstance(value, str):
        return []
    return NARRATION_WORD_RE.findall(value.lower())


def narration_substance_problem(value, label="commentary"):
    """Report a commentary that names a keystroke instead of a reason.

    :returns: the problem, or None.
    """
    words = narration_words(value)
    if len(words) > 1:
        return None
    return (
        "%s is %r, which is one word.  A row says WHY the survivor "
        "pressed the key, and a single word names the keystroke instead "
        "of accounting for it -- the letter typed into a search box, or "
        "the number entered in a box, is already recorded in the "
        "action.  Write the reason for the run this keystroke belongs "
        "to, in the survivor's own voice" % (label, value))


def _validated_commentary(value):
    """Return the survivor's own words, or refuse them."""
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
    # THE VOICE GATE, AND IT REFUSES.  Warning and appending the row
    # anyway would leave a stderr line, in a session hundreds of rows
    # long, deciding whether an engineering observation reaches the
    # committed transcript and the film's caption track.
    problem = meta_vocabulary_problem(text, "commentary")
    if problem is not None:
        raise ManifestError(problem)
    # THE OTHER TWO CONTENT GATES ARE APPLIED IN build_row() rather than
    # here, and the reason is the message a caller gets: markup and a
    # one-word label are reported ALONGSIDE the placeholder and shape
    # findings, in one refusal that names the frame, instead of the first
    # of them hiding the rest.  See raw_markup_problem and
    # narration_substance_problem above for the rules themselves.
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
    """Return `moment` in the manifest's fixed real_ts form."""
    if moment is None:
        moment = datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(moment, datetime.datetime):
        raise ManifestError(
            "utc_timestamp takes a datetime or None, got %s"
            % type(moment).__name__)
    return _format_moment(moment)


def canonical_real_ts(value):
    """Normalise a supplied real_ts to the one fixed form.

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
    """Return `row` as a dict of exactly FIELDS, in declared order."""
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
    """Validate one row and return it, without touching the disk."""
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
    # AND THE TWO PUBLICATION GATES, over BOTH narrations.  Every string
    # in these two fields is copied verbatim into
    # playthrough/transcript.md and quoted in the reports, so markup is
    # refused in either; a one-word label is refused in the commentary,
    # which is the field that has to say why.  Both are collected rather
    # than raised, so one refusal names every problem with the row.
    for label, value in (("frame %d action" % index, row["action"]),
                         ("frame %d commentary" % index,
                          row["commentary"])):
        markup = raw_markup_problem(value, label)
        if markup is not None:
            problems.append(markup)
    substance = narration_substance_problem(
        row["commentary"], "frame %d commentary" % index)
    if substance is not None:
        problems.append(substance)
    if problems:
        raise ManifestError("  ".join(problems))
    return _ordered_row(row)


def encode_row(row):
    """Return the exact line this module writes for `row`."""
    ordered = _ordered_row(row)
    return json.dumps(ordered, ensure_ascii=False) + "\n"


def _fsync(descriptor, path, frame, require_durable):
    """Force a written row to the device, or fail loudly.

    THIS STEP DELIBERATELY DOES NOT ROLL THE ROW BACK, unlike the write
    itself.  By the time it runs the line is complete and valid JSON on
    disk; what is in doubt is only whether it survives a power loss.
    Truncating it away would turn an uncertainty into a certain loss --
    deleting the record of a frame that exists -- so the row stays and
    the uncertainty is reported for what it is.

    Reduced durability remains available, but only as an explicit
    caller decision: `require_durable=False` restores the warn-once
    behaviour for a caller who genuinely accepts it, such as a scratch
    manifest on a filesystem that cannot fsync at all.  The default is
    the safe one, and the opt-in has to be typed out.
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

    THIS IS WHAT KEEPS A HANDLED FAILURE FROM COSTING MORE THAN ITS OWN
    ROW, and it is the opposite of rewriting history rather than an
    exception to it.  The only bytes it can remove are the ones the
    append that just failed had started to write: `committed` was read
    from the file BEFORE that write, under the same lock, so truncating
    to it restores the file to exactly the state every already-recorded
    row left it in.  No recorded row is altered, no row is dropped, and
    the failure is still raised.

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
    """Refuse to append onto a line that was never finished."""
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
    """Write one encoded row, entirely or not at all."""
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

    THE LOCK IS ADVISORY, so that guarantee reaches exactly as far as
    the processes that cooperate with it.  Every writer in this pipeline
    goes through this function, which is what makes it hold here; a
    READER that does not take the lock is unaffected by it and can read
    the file mid-append.  That is why the readers do not rely on the
    lock: verify_manifest() refuses a line it cannot parse, and
    timeline.py refuses the document rather than working around it.

    THE LOCK IS MANDATORY AND THIS FAILS CLOSED.  Warning and
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

    Two writers appending at the same instant is not hypothetical: the
    capture loop runs unattended, and a second stage or a re-run can
    overlap it.  O_APPEND keeps each write at the end of the file, but
    the lock is what makes "measure the end, write, fsync, and on
    failure truncate back" one indivisible step AS SEEN BY ANOTHER
    PROCESS THAT ALSO TAKES IT -- so two rows cannot interleave and a
    rollback cannot remove bytes another writer put there after this one
    measured the end.

    :raises ManifestError: when the lock cannot be taken. Nothing has been
        measured, written or truncated at that point.
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

    A row is not reported as appended until it has been written,
    flushed AND forced to the device.  Every failure up to and including
    the fsync -- the open, the lock, the boundary check, the write, the
    fsync -- raises ManifestError; none is downgraded to a warning,
    because a caller that is told the row was recorded will not go back
    and check.  `require_durable=False` is the one documented exception,
    and it weakens only the fsync step: see _fsync().

    `manifest_path` is explicit rather than defaulted so that a test,
    a dry run and the real session cannot be confused for one another;
    default_manifest_path() supplies the pipeline's own value.  It is
    validated against the approved root before anything is opened, so
    a path outside playthrough/ -- or one reached through a symlink --
    is refused rather than appended to.  `root` relocates that approved
    tree for a test that owns a temporary directory; see
    approved_root().
    """
    path = _validated_manifest_path(manifest_path, root)
    row = build_row(frame, file, real_ts, ingame_clock, action,
                    commentary)
    line = encode_row(row)
    # Append mode, one line, then closed.  The file is never opened for writing
    # any other way: not truncated, not seeked, not re-sorted, not
    # deduplicated, not compacted, not retro-edited.
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
        # Closing releases the lock as well.  A close that fails cannot hide a
        # row this function claimed to have stored -- the write and the fsync
        # above both already raise, and the fsync ran first -- so it is not
        # promoted to a failure that would contradict a row already on disk.
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
    """Append a row supplied as a mapping of the six fields."""
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
    """Return the staging siblings in `directory`, sorted. Read-only."""
    try:
        names = os.listdir(directory)
    except OSError:
        return ()
    return tuple(sorted(
        name for name in names
        if name.startswith(prefix) and name.endswith(suffix) and
        len(name) > len(prefix) + len(suffix)))


def sweep_staging(directory, prefix, suffix, label):
    """Remove staging siblings left behind under the private prefix.

    WHY THIS OUTLIVES ANY WRITER.  This module rewrites nothing: the
    record is append-only and it has no rewrite entry point.  A sibling
    temporary under the private prefix can still be sitting on disk,
    because a writer that renamed one into place and then met an
    UNHANDLED interruption -- SIGKILL, the power going -- left it where
    no handled path could unlink it.  These
    siblings live inside playthrough/, which .gitignore re-includes
    wholesale with its terminal `!/playthrough/**` negation, so a
    survivor is an untracked file that `git add -A playthrough/` would
    commit into an evidence tree nobody authored it into.

    WHAT IT WILL NOT DELETE.  Only a REGULAR file, never a symbolic link
    (which could point anywhere), never a directory, and only one owned
    by this account.  Anything else is reported and LEFT, because
    removing a file this module did not write is not reconciliation.
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
# Rewriting the manifest in place would answer it, and must not: a
# mechanism that can rewrite captured evidence is a defect, because it
# makes every later artifact deniable.  There is no such path here; this
# ledger is the answer instead.
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
    """Return the amendment ledger's path."""
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
    """Return the sha256 of one manifest LINE, newline included."""
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
    # THE PUBLICATION RULE REACHES THE LEDGER TOO, on both sides of the
    # correction.  `amended` is what every derivative publishes, so it
    # plainly has to pass; `recorded` has to pass as well, because it is
    # a QUOTATION of a manifest row and the writer refuses markup there,
    # so a `recorded` value carrying any would be a claim about a row
    # that cannot exist -- and without this the ledger could introduce
    # exactly the markup the row writer refuses.
    for name in ("recorded", "amended"):
        problem = raw_markup_problem(
            row[name],
            "the %s %s for frame %d" % (name, row["field"], row["frame"]))
        if problem:
            raise ManifestError(problem)
    if row["field"] == "commentary":
        problem = meta_vocabulary_problem(row["amended"])
        if problem:
            raise ManifestError(
                "the amended commentary for frame %d is not in the "
                "survivor's voice: %s" % (row["frame"], problem))
        # AND IT MUST BE A REASON.  An amendment that replaces a
        # one-word label with another one-word label is the defect
        # restated, not corrected.
        problem = narration_substance_problem(
            row["amended"],
            "the amended commentary for frame %d" % row["frame"])
        if problem:
            raise ManifestError(problem)
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
    """Return a list of problems with the ledger. Read-only, pure."""
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
    """Apply the ledger to a copy of the rows. Pure."""
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
    """Validate one attestation row and return it in key order. Pure."""
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
    """Return the ledger's rows, in the order they were written."""
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
    """Check the frames on disk against their attestations."""
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


# ---------------------------------------------------------------------
# THE EVIDENCE ANCHOR: A HASH CHAIN, AND A NAME GIT CAN RE-DERIVE
#
# Everything above this line is SELF-ATTESTATION.  The record says what
# was pressed, the digest ledger says what each frame hashed to, the
# amendment ledger says what was corrected -- and every one of those
# files sits in the same directory as the evidence it vouches for, under
# the same permissions, writable by whatever wrote them.  A review put
# it exactly: "every attestation is mutable with its evidence".  Edit a
# frame and its digest row together and nothing above notices; edit the
# record and recompute the timeline and every arithmetic check still
# passes.  Same-domain attestation cannot answer "was this changed after
# the fact", because the answer would have to come from the thing being
# asked about.
#
# So this section adds a SECOND, INDEPENDENT domain, and it does it
# without inventing a trust root of its own:
#
#   1. A HASH CHAIN.  Each row seals one artifact and carries the
#      previous row's chain hash, so the rows are ordered by
#      construction and no row can be removed, reordered or altered
#      without breaking every chain value after it.  Appending a
#      plausible row is not enough either: the head has to match what
#      the history says it was.
#
#   2. THE GIT BLOB NAME, BESIDE THE SHA256.  Git is content-addressed:
#      the name of a blob IS a hash of its bytes, computed by a program
#      nobody here wrote, and `git hash-object <path>` re-derives it on
#      any host.  Recording it turns "trust this ledger's sha256" into
#      "compare these bytes against git's own name for them".  It is
#      computed in pure Python here -- sha1 over `blob <len>\0<bytes>`,
#      git's documented object format -- so sealing needs no subprocess
#      and works before anything has been added to the index.  Verified
#      against `git hash-object` on this checkout's own record, timeline,
#      acknowledgment ledger and film: identical on all four.
#
#   3. THE CHAIN HEAD IN A COMMIT MESSAGE.  commit_artifacts.sh writes
#      the head as a `Playthrough-Evidence-Anchor:` trailer at each
#      checkpoint.  A commit object's name is a hash of its own content,
#      so the trailer cannot be edited without rewriting history and
#      changing every commit id after it.  THAT is what makes the anchor
#      independent: an attacker who rewrites an artifact must also
#      rewrite this ledger, and then also rewrite published history.
#
# WHY SEALING THE DIGEST LEDGER SEALS ALL 307 FRAMES.  The frames are
# not sealed one by one -- build/frame_digests.jsonl already holds a
# sha256 per frame, and that file is sealed here.  So a substituted
# frame breaks its digest row, and repairing the digest row breaks the
# ledger's own seal, and repairing the seal breaks the chain and the
# committed trailer.  One row covers the whole capture set, transitively,
# which is why the set below is small enough to read.
#
# THE sha1 HERE IS A NAME, NOT A SECURITY CLAIM, and it is spelled with
# `usedforsecurity=False` so that intent is in the code rather than in a
# comment somebody has to find.  The integrity claim in every row is the
# sha256 beside it; the blob name exists so a reader can put a second,
# independently written implementation of hashing against the same bytes.
# ---------------------------------------------------------------------
ANCHOR_REL_PARTS = ("build", "evidence_anchor.jsonl")

ANCHOR_VERSION = 1

ANCHOR_FIELDS = (
    "version",
    # The row's position in the chain, 1-based and contiguous.  A gap is
    # a removed row, which the chain would also reveal -- both are
    # checked, because a reader is better served by "row 4 is missing"
    # than by "the chain broke somewhere".
    "seq",
    "sealed_at",
    # Which act sealed it: a checkpoint name, or "remediation" for a row
    # added while repairing the evidence rather than while producing it.
    # Bounded and lowercase so it can be written into a commit trailer
    # and a report without escaping.
    "sealed_by",
    # The artifact, spelled relative to the approved tree -- so
    # "build/frame_digests.jsonl", not an absolute path and not a
    # repository-relative one.  RELATIVE TO THE TREE RATHER THAN TO THE
    # REPOSITORY, and that is a correction rather than a preference.
    "path",
    "sha256",
    "bytes",
    # Git's own name for these exact bytes; `git hash-object <path>`
    # prints it.
    "git_blob",
    # The previous row's `chain`, or "" for the first row.
    "prev_chain",
    # sha256 over prev_chain, a newline, and this row's other fields in
    # the order above, serialised compactly.  See anchor_chain_hash.
    "chain",
)

# The evidence this anchor seals, in a fixed order so that two runs over an
# unchanged tree produce the same chain.  Repository-relative parts rather than
# absolute paths, so the set is meaningful in any checkout.
ANCHOR_SEALED = (
    ("manifest.jsonl",),
    ("amendments.jsonl",),
    ("timeline.json",),
    ("build", "frame_digests.jsonl"),
    ("build", "observations.jsonl"),
    ("build", "frame_dates.jsonl"),
    ("build", "acknowledgments.jsonl"),
    ("build", "concat.txt"),
    ("build", "transitions.json"),
    ("build", "movie.json"),
    ("transcript.srt",),
    ("transcript.md",),
    ("cata-play.mp4",),
    ("cata-play-cc.mp4",),
    ("dossier.md",),
)

# Who may be recorded as having sealed a row.  A bounded lowercase token,
# because it is written into a commit trailer and quoted in reports.
ANCHOR_SEALED_BY_RE = re.compile(r"\A[a-z][a-z0-9-]{0,31}\Z")

# The label for a row appended while repairing evidence rather than while
# producing it.  Named here so the one honest use of it is spelled the
# same everywhere.
ANCHOR_REMEDIATION = "remediation"


def git_blob_name(path, label="artifact"):
    """Return git's own object name for a file's exact bytes."""
    resolved = _validated_path(path, "%s path" % label)
    digest = hashlib.sha1(usedforsecurity=False)
    try:
        size = os.path.getsize(resolved)
    except OSError as err:
        raise ManifestError(
            "could not measure %s to name it as git would: %s"
            % (resolved, err)) from err
    digest.update(b"blob %d\0" % size)
    descriptor = _open_nofollow(resolved, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            read = 0
            while True:
                block = handle.read(DIGEST_BLOCK)
                if not block:
                    break
                read += len(block)
                digest.update(block)
    except OSError as err:
        raise ManifestError(
            "could not read %s to name it as git would: %s"
            % (resolved, err)) from err
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if read != size:
        # THE HEADER COMMITS TO A LENGTH, so a file that changed size
        # while it was being read would produce a name for bytes that
        # never existed together.  Refused rather than published.
        raise ManifestError(
            "%s was %d byte(s) when it was measured and %d when it was "
            "read, so no single set of bytes can be named: seal it "
            "again once whatever is writing to it has finished"
            % (resolved, size, read))
    return digest.hexdigest()


def anchor_chain_hash(prev_chain, row):
    """Return the chain hash for `row` following `prev_chain`."""
    if not isinstance(prev_chain, str):
        raise ManifestError(
            "the previous chain value is text or empty, got %r"
            % (prev_chain,))
    ordered = {}
    for name in ANCHOR_FIELDS:
        if name == "chain":
            continue
        if name not in row:
            raise ManifestError(
                "an anchor row cannot be chained without its %r field"
                % name)
        ordered[name] = row[name]
    payload = json.dumps(ordered, ensure_ascii=False,
                         separators=(",", ":"))
    return hashlib.sha256(
        ("%s\n%s" % (prev_chain, payload)).encode("utf-8")).hexdigest()


def _validated_seq(value):
    """Return a 1-based chain position, or raise."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(
            "an anchor row's position in the chain is an integer, got "
            "%r" % (value,))
    if value < 1:
        raise ManifestError(
            "an anchor row's position in the chain starts at 1, got %d"
            % value)
    return value


def _validated_sealed_by(value):
    """Return the sealing act's name, or raise."""
    if not isinstance(value, str) or not ANCHOR_SEALED_BY_RE.match(
            value):
        raise ManifestError(
            "an anchor row records WHICH act sealed it as a short "
            "lowercase token (%s), got %r.  It is written into a commit "
            "trailer, so anything else could reshape the message it "
            "lands in" % (ANCHOR_SEALED_BY_RE.pattern, value))
    return value


def _validated_sealed_path(value):
    """Return an approved-root-relative artifact path, or raise.

    A pure SHAPE check, because build_anchor_row is pure: relative, no
    parent traversal, no empty component, and printable.  Resolving a
    real path to this spelling is seal_artifacts' job, where the root is
    known.
    """
    if not isinstance(value, str) or not value:
        raise ManifestError(
            "a sealed artifact's path is a non-empty string, got %r"
            % (value,))
    if value.startswith("/") or value.startswith("\\"):
        raise ManifestError(
            "a sealed artifact's path is relative to the approved tree, "
            "so it may not begin at the filesystem root: %r" % value)
    parts = value.split("/")
    for part in parts:
        if not part or part in (".", ".."):
            raise ManifestError(
                "a sealed artifact's path may not contain an empty or "
                "traversing component: %r" % value)
    if any(character < " " or character == "\x7f" for character in
           value):
        raise ManifestError(
            "a sealed artifact's path carries a control character, "
            "which cannot appear in an artifact of this pipeline: %r"
            % value)
    return value


def _validated_sealed_bytes(value, label):
    """Return a positive byte count, or raise.

    Zero is refused as well as negative: a sealed artifact of no bytes is
    a file that was truncated between being produced and being sealed,
    and sealing it would publish that state as though it were evidence.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(
            "%s is %r, not an integer" % (label, value))
    if value <= 0:
        raise ManifestError(
            "%s is %d; a sealed artifact is not empty" % (label, value))
    return value


def _validated_chain_value(value, label, allow_empty=False):
    """Return a sha256 chain value, or raise."""
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not SHA256_RE.match(value):
        raise ManifestError(
            "%s is a 64-character sha256 in lower-case hex%s, got %r"
            % (label, " or empty" if allow_empty else "", value))
    return value


def build_anchor_row(seq, sealed_by, path, sha256, byte_count, git_blob,
                     prev_chain, sealed_at=None):
    """Build one sealed-artifact row, chain value included. Pure."""
    row = {
        "version": ANCHOR_VERSION,
        "seq": _validated_seq(seq),
        "sealed_at": canonical_real_ts(
            sealed_at if sealed_at else utc_timestamp()),
        "sealed_by": _validated_sealed_by(sealed_by),
        "path": _validated_sealed_path(path),
        "sha256": _validated_digest(sha256, "a sealed artifact's "
                                            "sha256"),
        "bytes": _validated_sealed_bytes(
            byte_count, "a sealed artifact's byte count"),
        "git_blob": _validated_git_object(
            git_blob, "a sealed artifact's git blob name"),
        "prev_chain": _validated_chain_value(
            prev_chain, "the previous chain value", allow_empty=True),
    }
    if row["git_blob"] is None:
        raise ManifestError(
            "a sealed artifact must carry git's own name for its bytes: "
            "it is the independently computed half of the claim, and a "
            "row without it asks a reader to trust this module's sha256 "
            "alone")
    row["chain"] = anchor_chain_hash(row["prev_chain"], row)
    return row


def encode_anchor_row(row):
    """Return one anchor row as the exact line to be written."""
    ordered = {name: row[name] for name in ANCHOR_FIELDS}
    return json.dumps(ordered, ensure_ascii=False) + "\n"


def default_anchor_path():
    """Return the evidence anchor ledger's path.

    Honours PLAYTHROUGH_EVIDENCE_ANCHOR for the same reason the other
    defaults honour their exports; the value is then held to the same
    containment rules.
    """
    from_env = os.environ.get("PLAYTHROUGH_EVIDENCE_ANCHOR")
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), *ANCHOR_REL_PARTS)


def _anchor_default(root=None):
    """Return the anchor's default path, honouring a relocated root."""
    if root is not None:
        return os.path.join(approved_root(root), *ANCHOR_REL_PARTS)
    return default_anchor_path()


def _validated_anchor_target(value, root=None):
    """Return an absolute anchor path this module may touch.

    The same four conditions the other ledgers are held to: contained in
    the approved root, no symlinked component, EXACTLY
    <approved root>/build/evidence_anchor.jsonl, and a regular file.
    """
    resolved = _validated_path(value, "evidence anchor path")
    approved = _assert_within_root(
        resolved, "the evidence anchor path", root)
    _assert_no_symlink(resolved, approved, "the evidence anchor path")
    canonical = os.path.join(approved, *ANCHOR_REL_PARTS)
    if os.path.realpath(resolved) != canonical:
        raise ManifestError(
            "the evidence anchor is %s and nothing else, but %s was "
            "given.  Appending seal rows onto another artifact would "
            "corrupt it and would report success."
            % (canonical, resolved))
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise ManifestError(
            "the evidence anchor path is not a regular file: %s"
            % resolved)
    return resolved


def read_anchor_rows(anchor_path=None, root=None):
    """Return the anchor's rows, in the order they were written."""
    path = _validated_anchor_target(
        _anchor_default(root) if anchor_path is None else anchor_path,
        root)
    if not os.path.isfile(path):
        return ()
    rows = []
    descriptor = _open_nofollow(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8",
                       newline="") as handle:
            descriptor = None
            for number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                rows.append(_decode_line(raw, number, path))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return tuple(rows)


def anchor_head(rows):
    """Return the chain head of `rows`, or "" for an empty chain.

    The head is what a commit trailer publishes and what the gate
    compares against, so it has exactly one definition and this is it.
    """
    if not rows:
        return ""
    last = rows[-1]
    value = last.get("chain") if isinstance(last, dict) else None
    return value if isinstance(value, str) else ""


def anchor_chain_problems(rows):
    """Return every way `rows` fails to be a well formed chain."""
    problems = []
    previous = ""
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(
                "anchor row %d is a %s, not an object"
                % (position, type(row).__name__))
            previous = ""
            continue
        missing = [name for name in ANCHOR_FIELDS if name not in row]
        if missing:
            problems.append(
                "anchor row %d is missing %s"
                % (position, ", ".join(missing)))
            previous = ""
            continue
        extra = sorted(set(row) - set(ANCHOR_FIELDS))
        if extra:
            problems.append(
                "anchor row %d carries %s, which the schema does not "
                "declare" % (position, ", ".join(extra)))
        if row["seq"] != position:
            problems.append(
                "anchor row %d records seq=%r, so a row has been "
                "removed, reordered or inserted"
                % (position, row["seq"]))
        if row["prev_chain"] != previous:
            problems.append(
                "anchor row %d follows %r but the row before it ends "
                "%r, so the chain is broken here"
                % (position, _short(row["prev_chain"]),
                   _short(previous)))
        try:
            expected = anchor_chain_hash(row["prev_chain"], row)
        except ManifestError as err:
            problems.append(
                "anchor row %d cannot be re-chained: %s"
                % (position, err))
            previous = ""
            continue
        if row["chain"] != expected:
            problems.append(
                "anchor row %d declares chain %r but its own fields "
                "hash to %r, so the row was altered after it was sealed"
                % (position, _short(row["chain"]), _short(expected)))
        previous = row["chain"]
    return problems


def _short(value):
    """Return a chain value abbreviated for a diagnostic."""
    if not isinstance(value, str) or not value:
        return "<empty>"
    return value[:16]


def _tree_relative(path, base):
    """Return `path` spelled relative to the approved tree `base`.

    Forward slashes, and a refusal rather than a traversal for anything
    outside the tree: the anchor's `path` column is meaningful only as a
    location inside the evidence tree, and "../.." would be neither
    meaningful nor safe to resolve later.
    """
    resolved = os.path.normpath(os.path.abspath(path))
    root = os.path.normpath(base)
    if resolved == root or not resolved.startswith(root + os.sep):
        raise ManifestError(
            "%s is not inside the evidence tree %s, so it cannot be "
            "sealed by an anchor whose paths are relative to that tree"
            % (resolved, root))
    return resolved[len(root) + 1:].replace(os.sep, "/")


def sealed_artifact_paths(root=None):
    """Return the absolute path of every artifact the anchor seals.

    In ANCHOR_SEALED's order, whether or not each exists: the caller
    decides what an absent artifact means, and the gate is where that
    judgement lives.
    """
    base = approved_root(root)
    return tuple(os.path.join(base, *parts) for parts in ANCHOR_SEALED)


def seal_artifacts(sealed_by, paths=None, anchor_path=None,
                   require_durable=True, root=None):
    """Append one chained row per artifact and return (rows, absent)."""
    target = _validated_anchor_target(
        _anchor_default(root) if anchor_path is None else anchor_path,
        root)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise ManifestError(
            "the directory for the evidence anchor does not exist: %s"
            % parent)
    base = approved_root(root)
    candidates = (sealed_artifact_paths(root) if paths is None
                  else tuple(paths))
    existing = read_anchor_rows(target, root)
    problems = anchor_chain_problems(existing)
    if problems:
        raise ManifestError(
            "the evidence anchor already on disk is not a sound chain, "
            "so nothing was added to it: %s" % problems[0])
    chain = anchor_head(existing)
    seq = len(existing)
    written = []
    absent = []
    for candidate in candidates:
        relative = _tree_relative(candidate, base)
        if not os.path.isfile(candidate):
            absent.append(relative)
            continue
        seq += 1
        row = build_anchor_row(
            seq, sealed_by, relative,
            file_digest(candidate, "sealed artifact"),
            os.path.getsize(candidate),
            git_blob_name(candidate, "sealed artifact"), chain)
        _append_anchor_row(target, row, require_durable)
        chain = row["chain"]
        written.append(row)
    return (tuple(written), tuple(absent))


def _append_anchor_row(path, row, require_durable=True):
    """Append one validated anchor row under the module's discipline.

    O_NOFOLLOW, a mandatory exclusive flock, the end-of-file
    measurement, one whole-line write with rollback, and an fsync before
    the row is reported as stored -- the same machinery the record and
    the digest ledger use, for the same reason.
    """
    payload = encode_anchor_row(row).encode("utf-8")
    descriptor = _open_nofollow(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW)
    try:
        _lock_exclusively(descriptor, path)
        try:
            committed = os.lseek(descriptor, 0, os.SEEK_END)
        except OSError as err:
            raise ManifestError(
                "could not measure the end of the evidence anchor %s "
                "(%s), so the seal of %s was not written"
                % (path, err, row["path"])) from err
        _assert_row_boundary(descriptor, committed, path, row["seq"])
        _append_whole_row(descriptor, payload, committed, path,
                          row["seq"])
        _fsync(descriptor, path, row["seq"], require_durable)
    finally:
        try:
            os.close(descriptor)
        except OSError as err:
            _warn_once(
                "anchor-close",
                "could not close the evidence anchor %s after appending "
                "(%s); the row itself was written and forced to the "
                "device before this point" % (path, err))
    return row


def verify_anchor(anchor_path=None, root=None, require_all=True):
    """Hold every sealed artifact to the seal, and return the problems.

    Three questions, kept apart so a failure names its own cause:
      * is the chain itself sound (anchor_chain_problems);
      * does each sealed artifact STILL hash to what its newest row
        says, both as sha256 and as git's own blob name;
      * is every artifact in ANCHOR_SEALED that exists on disk actually
        sealed, so a file cannot escape the anchor by being left out of
        it.
    """
    rows = read_anchor_rows(anchor_path, root)
    problems = list(anchor_chain_problems(rows))
    if not rows:
        return (["the evidence anchor is empty or absent, so nothing "
                 "vouches for the evidence from outside itself"]
                if require_all else [])
    newest = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            newest[row["path"]] = row
    base = approved_root(root)
    for relative, row in sorted(newest.items()):
        # The row stores a path relative to the approved tree, so it
        # is resolved against that tree and then held to it -- a row
        # naming something outside is a finding, not something to read.
        try:
            _validated_sealed_path(relative)
        except ManifestError as err:
            problems.append(
                "anchor row %s names %r, which is not a path inside "
                "the approved tree: %s"
                % (row.get("seq"), relative, err))
            continue
        absolute = os.path.normpath(
            os.path.join(base, *relative.split("/")))
        if absolute != base and not absolute.startswith(base + os.sep):
            problems.append(
                "the anchor seals %r, which is not under the approved "
                "tree" % relative)
            continue
        if not os.path.isfile(absolute):
            problems.append(
                "%s is sealed by anchor row %s and is not on disk"
                % (relative, row.get("seq")))
            continue
        size = os.path.getsize(absolute)
        actual = file_digest(absolute, "sealed artifact")
        if actual != row.get("sha256"):
            problems.append(
                "%s hashes to %s and the anchor sealed %s, so it "
                "changed after it was sealed"
                % (relative, _short(actual),
                   _short(row.get("sha256"))))
            continue
        if size != row.get("bytes"):
            problems.append(
                "%s is %d byte(s) and the anchor sealed %r"
                % (relative, size, row.get("bytes")))
            continue
        blob = git_blob_name(absolute, "sealed artifact")
        if blob != row.get("git_blob"):
            problems.append(
                "%s is git object %s and the anchor sealed %s -- the "
                "sha256 matched, so this is the independent half of the "
                "claim disagreeing"
                % (relative, _short(blob),
                   _short(row.get("git_blob"))))
    if require_all:
        for relative in unsealed_artifacts(anchor_path, root, rows):
            problems.append(
                "%s exists and no anchor row seals it, so it is "
                "outside the chain" % relative)
    return problems


def unsealed_artifacts(anchor_path=None, root=None, rows=None):
    """Return the artifacts that exist on disk and carry no seal."""
    if rows is None:
        rows = read_anchor_rows(anchor_path, root)
    sealed = {row["path"] for row in rows
              if isinstance(row, dict) and isinstance(row.get("path"),
                                                      str)}
    base = approved_root(root)
    pending = []
    for absolute in sealed_artifact_paths(root):
        if not os.path.isfile(absolute):
            continue
        relative = _tree_relative(absolute, base)
        if relative not in sealed:
            pending.append(relative)
    return tuple(pending)


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
    """Return every row on disk, in file order. Read-only.

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
    """Return the last frame index recorded, or 0 if there is none."""
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
    """Report every schema defect in ONE row. Read-only."""
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
            # normalises whatever it is handed (see canonical_real_ts), so
            # every row THIS module wrote is already canonical and this costs a
            # well-formed record nothing.
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
    """Report gaps, repeats and reorderings. Read-only."""
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
    """Report every schema defect in a sequence of rows. Pure."""
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

    :param rows: the manifest rows, in order. :param dates: optional {frame:
        sidebar date line}, as the telemetry sidecar records it.
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
    """Return a list of problems with the manifest. Read-only.

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
    """Return a list of problems with the amendment ledger. Read-only."""
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
    """Run the read-only command line and return an exit status."""
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
