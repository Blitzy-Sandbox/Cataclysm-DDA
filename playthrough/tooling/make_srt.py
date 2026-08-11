#!/usr/bin/env python3
"""Write playthrough/transcript.srt and playthrough/transcript.md.

Both artifacts, from ONE read of playthrough/timeline.json, in one pass
over one derived list of cues.  The human-readable record and the
machine-readable cue file therefore cannot disagree: they are rendered
from the SAME Cue objects, so the Nth timestamp in the Markdown is
literally the same string as the Nth cue's start in the SubRip file
rather than a number that happens to match it.  The Markdown is never
parsed out of the SRT and the SRT is never parsed out of the Markdown,
because either would put a second source of truth back in.

NO TIMING ARITHMETIC HAPPENS HERE
cue_start and cue_end are READ from the timeline.  timeline.py walked
the video cursor once and charged each transition's seconds to it
BEFORE the following cue began, so the cue windows already include
transition time.  A caption generator that walked the frame durations
itself would emit cues that are right at the start of the film and
further out of step after every transition -- monotonic, plausible,
and wrong, which is the worst shape a defect can take.  So there is
no cursor in this module, nothing is accumulated, and the cue that
follows a transition starts a transition's worth of seconds after the
previous cue ends rather than where the frame durations alone would
put it.  format_srt_timecode is IMPORTED from timeline.py
rather than written a second time: one formatter, one implementation,
one set of tests (test_timeline.py holds it to 3661.5 s ->
01:01:01,500).

`duration` and `transition_after` are read too, but only as evidence to
check the cues against -- a window that does not last its frame's
duration, an unexplained gap between windows, or a flagged frame with
no gap after it are all reported rather than rendered.  The expected
gap comes from the document's own `transition` field, so no transition
constant is written down here either.

THE SUBRIP CONTRACT, which downstream code asserts literally
One cue per frame -- the cue count, the frame count and the Markdown
entry count are three numbers that must agree, and verify_artifacts.sh
compares them.  Sequence numbers from 1, contiguous.  Timecodes as
HH:MM:SS,mmm with a COMMA: this is SubRip, not WebVTT, and the arrow
is " --> " with one space each side.  Cue text of at most two lines of
about forty-two columns, wrapped at word boundaries and never through
the middle of a word.  Plain text: no override codes, no positioning,
no markup, because the track is muxed as mov_text and must stay a
clean, selectable English caption stream rather than anything burned
into the picture.  UTF-8 with LF endings and NO byte-order mark -- a
BOM would sit in front of the first cue's sequence number and stop it
matching.

ONE MEASURED FACT ABOUT COUNTING THE CUES AFTERWARDS, so nobody loses
time to it: MP4 timed text has to cover the container contiguously, so
the muxer PADS THE GAPS this transcript leaves for the transitions with
empty two-byte samples of its own.  Measured on the reference sequence,
a container muxed from seven cues carries NINE subtitle packets -- the
two extra ones occupying exactly 16.250-17.250 s and 27.250-28.250 s,
which are the two transitions.  So the cue count is `grep -c " --> "`
on this file, or the count of cues extracted back out of the container
(seven, deviating from the timeline by 0.000000 s), and it is NOT the
number of subtitle packets ffprobe reports.

THE MARKDOWN CONTRACT, which is checked just as literally
Every entry begins at column one with **HH:MM:SS,mmm** followed by the
survivor's own sentence.  EXACTLY ONE timestamp-shaped string per
entry and none anywhere else, so the header carries no example
timestamp and no entry carries a cue range.  The pattern that counts
them accepts a full stop as well as a comma, so neither form may
appear outside an entry stamp.  And every word THIS module contributes
-- the header, and nothing else -- has to survive the out-of-character
vocabulary gate that keeps engineering language out of the survivor's
voice; assert_in_character() holds the module to that before a byte is
written, so the gate cannot be tripped by an edit to a string constant
here.

THE SURVIVOR'S VOICE IS COPIED, NEVER EDITED
`commentary` is the in-character record.  It is written to the
Markdown verbatim -- not summarised, not rephrased, not annotated, and
never wrapped in engineering language.  The caption is the same
sentence wrapped at word boundaries to the cue geometry, which is a
presentational constraint of the caption format and the only
transformation this module performs.  Where a sentence genuinely will
not fit in CUE_MAX_LINES lines the transcript is REFUSED rather than
abridged: nothing here is shortened, elided or truncated, and the
remedy is a shorter sentence in the source commentary.

THE STAMPS ARE VIDEO TIME, AND ONLY VIDEO TIME
Neither artifact carries an in-game clock reading.  That is deliberate
rather than an omission: a reading the capture could not resolve is
carried forward from its neighbour and flagged `reconciled` in the
timeline, and printing it here would present a borrowed number in the
same confident form as a read one, with the flag left behind in a file
nobody reads beside it.  So the audit trail stays where it was
recorded, the transcript says only where the film has got to, and no
frame's cue is invented, merged or dropped because its clock was
unreadable -- it still gets exactly one cue, at the floor if that is
what its window came to.

Out-of-character wording inside a commentary is REFUSED, using
manifest.py's own vocabulary and message so the gate cannot be
stricter at write time than at publication time.  A commentary
carrying a timestamp-shaped string or " --> " is refused too, because
either would add a match to a downstream count while looking fine
locally.  So is a commentary that will not wrap into CUE_MAX_LINES
lines of the cue geometry: the caption is never shortened to fit, and
the remedy for all three is a shorter or cleaner sentence in the
source commentary, amended there and regenerated through the chain.

WHAT IS REFUSED OUTRIGHT
An empty frames array, a frame index that is not the position it sits
in, a cue that does not end after it starts, a cue that starts before
its predecessor ended, a first cue that does not start at zero, a
final cue that does not end where the timeline's own total says the
film ends, an empty commentary, and a cue that needs more than
CUE_MAX_LINES lines.  Nothing is repaired and nothing
is invented: one captured frame makes exactly one cue and one entry,
so a missing sentence is a hole in the record and is reported as one.
For the document form the sibling's own validate_timeline() is run as
well, so the invariant sum(durations) + sum(transitions) == total ==
final cue end is checked here too rather than assumed from the fact
that it was checked when the file was written.

USE
    . playthrough/tooling/env.sh
    MS='playthrough/tooling/make_srt.py'
    "$PLAYTHROUGH_PYTHON" -B "$MS"
    "$PLAYTHROUGH_PYTHON" -B "$MS" --dry-run
    "$PLAYTHROUGH_PYTHON" -B "$MS" --timeline PATH

    env.sh exports PLAYTHROUGH_PYTHON, the pinned CPython 3.12 this
    tooling is installed against, and -B keeps a re-included
    __pycache__ out of the tree -- this module imports a sibling, so an
    interpreter left free to write bytecode would leave one.

    import make_srt
    srt, markdown, cues = make_srt.build_transcripts(document)

Both files are validated, then built entirely in memory, then written.
Each INDIVIDUAL write is atomic -- a private temporary file in the
destination directory, fsynced, then os.replace()d over the artifact --
so a reader sees the whole old file or the whole new one.  The PAIR is
not: two replacements are two events, so the pair is JOURNALED and
RECOVERABLE instead.  An interruption between the two replacements can
leave mismatched generations on disk, and the journal is what makes
that state detectable and finishable rather than permanent -- see
publish_transcripts().  Every path is held inside the playthrough/ tree
derived from this module's own location, so neither artifact can be
redirected out of the record.

Nothing here varies from run to run: no timestamp, no host name, no
absolute path and no set iteration reaches either output, so the same
timeline always produces byte-identical files.  Standard library only,
plus the sibling timeline module -- nothing from
playthrough/tooling/requirements.txt -- so a transcript can be
regenerated and audited in any checkout without provisioning a render
toolchain.  There is no shell, no eval and no network surface of any
kind.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import textwrap
import unicodedata

from typing import (Any, Dict, List, NamedTuple, Optional, Sequence,
                    Tuple)

# Set BEFORE the sibling import below, which is the only import here
# that can write into the repository working tree.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1, but this module is documented as runnable
# on its own, and a standalone `python3 playthrough/tooling/make_srt.py`
# without that environment would compile the sibling to
# playthrough/tooling/__pycache__/ -- which .gitignore's terminal
# `!/playthrough/**` negation then makes COMMITTABLE.  A stray .pyc in
# a committed evidence tree is an artifact nobody authored.  The flag
# has to precede the import it protects, because the interpreter
# consults it at compile time; every documented command also passes -B.
sys.dont_write_bytecode = True

try:
    # The timecode formatter, the hardened reader, the artifact layout,
    # the containment root, the document validator and the comparison
    # tolerance all live in the sibling module.  Importing them is what
    # keeps the timecode, the tolerance and the rules about where an
    # artifact may live from existing twice and drifting apart.
    from timeline import (EPSILON, ArtifactLock, TimelineError,
                          approved_root, assert_timeline_document,
                          default_timeline_path, format_srt_timecode,
                          read_timeline, validate_timeline)
    # The generation facility: one journal and one manifest
    # implementation for the three producers that publish several
    # artifacts which only mean anything together.
    import timeline as timeline_module
    # AND THE TWO HONESTY GATES, from the module that owns them.  The
    # voice vocabulary and the clock-statement parser are imported rather
    # than restated so that a sentence which passes when the row is
    # written cannot fail when the transcript is published, or -- far
    # worse -- the other way round.  timeline.py already imports this
    # module, so it is not a new dependency of this stage.
    import manifest
except ImportError:
    # Imported from somewhere other than this directory: put the
    # tooling directory on the path and try once more.  A second
    # failure is a genuinely broken checkout and is allowed to raise.
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from timeline import (EPSILON, ArtifactLock, TimelineError,
                          approved_root, assert_timeline_document,
                          default_timeline_path, format_srt_timecode,
                          read_timeline, validate_timeline)
    import timeline as timeline_module
    import manifest


# The caption geometry.  Forty-two columns is the SubRip convention and
# roughly what a reader takes in at a glance, so it is where each cue's
# text is WRAPPED -- and wrapping is the only thing the width decides.
CUE_LINE_WIDTH = 42

# HOW MANY LINES A CUE MAY CARRY, AND WHY THIS IS A REFUSAL RATHER THAN
# A CUT OR AN ADVISORY.  The caption contract is at most two lines of
# about forty-two columns; a cue is displayed for as little as the 0.25 s
# floor, and six lines in a quarter of a second is not a transcript
# anybody reads.  Two defects have to be avoided at once here, and only
# one gate avoids both:
#
#   * SHORTENING THE CAPTION IS NOT THE ANSWER.  This module once capped
#     a cue at two lines and marked the cut with a bracketed elision:
#     168 of the 395 cues in the first re-recorded session ended in
#     "[...]", and many lost the survivor's actual reason for acting.
#     The requirement is that the timestamped transcript IS the embedded
#     caption track, so a track carrying two fifths of it abridged is not
#     that transcript, however honestly the abridgement was marked.
#   * AN ADVISORY IS NOT THE ANSWER EITHER.  Removing the cap and merely
#     REPORTING a long cue is what the review found in the shipped
#     artifact: 88 of 419 cues over two lines, one of them six lines
#     inside a 250 ms window, with a stderr note nobody had to act on.
#     A warning beside a written file is not a contract.
#
# So the geometry is enforced as a PUBLICATION-BLOCKING REFUSAL that
# names every offending entry, its frame and its line count, and nothing
# is ever shortened: the remedy is a shorter sentence in the source
# commentary -- amended at playthrough/manifest.jsonl with the amendment
# recorded in playthrough/TECHNICAL_NOTES.md, and every derived artifact
# regenerated in one pass -- never a cut in the caption.
CUE_MAX_LINES = 2

# The Markdown's only generated lines: a title carrying the survivor's
# name, then the sanctioned sentence about what the stamps measure.
#
# THE NAME IS READ FROM playthrough/dossier.md AND IS NEVER SPELLED
# HERE -- not in this constant, not in a comment, not as an example.
# It used to be a literal, under a comment claiming the title was
# "deliberately the same opening playthrough/dossier.md uses" -- and a
# runtime QA pass found that claim false in the shipped tree: the record
# had been re-captured with a different survivor, the dossier opened
# with that name, and the transcript still opened with the retired one.
# Every other layer of the record agreed with the dossier (the
# manifest's own sentences, the caption cues, the save file's base64
# name, the achievements file, lastworld.json); this one file, generated
# by this one constant, was the single dissenting voice, and the comment
# above it made the defect look intentional to a reviewer.  So
# test_make_srt.py greps this source for the shipped survivor's name and
# fails if it finds it: a name written here is a name that can go stale.
#
# A literal cannot be right for a record that can be re-captured, so the
# heading is DERIVED from the dossier's own first heading by
# markdown_header() and the derivation FAILS CLOSED: no dossier, no
# heading in it, or a heading that cannot pass the gates below means no
# transcript is written at all.  One survivor, one name, one place it is
# written down.
#
# Every word this module generates is held to BOTH gates before a byte
# is written -- including the derived title, because the name now comes
# from a file rather than from this source.  It must carry no
# timestamp-shaped string, since the gate counts every one of those and
# requires exactly one per entry (a stamp here would be counted as an
# entry that does not exist), and no out-of-character word: not just
# none of the concepts assert_in_character() refuses, but none of the
# bare substrings the blunter documented grep looks for either, which is
# why the title says what he did rather than naming anything about how
# the record was made.  And it is not embellished beyond the title, the
# name and the one line, because every word added here is another word
# that has to keep passing both gates forever.
MARKDOWN_TITLE_SUFFIX = " \u2014 what I did, and why"
MARKDOWN_TIMESTAMP_LINE = "Timestamps are cumulative video time."

# The survivor's name as playthrough/dossier.md writes it: the FIRST
# ATX level-one heading in the file, with its hashes and surrounding
# space removed.  Anchored to the start of a line so a `#` inside a
# sentence cannot be mistaken for a heading, and requiring at least one
# space after the hash so a hash run straight into the name -- which
# Markdown does not render as a heading either -- is not silently
# accepted.
DOSSIER_HEADING_RE = re.compile(r"^#[ \t]+(\S[^\n]*?)[ \t]*$",
                                re.MULTILINE)

# The longest a survivor's name may be.  A dossier whose first heading
# is a paragraph is a dossier this module has misread, and a title that
# long would not be a title; refusing it names the problem instead of
# publishing it.
MAX_SURVIVOR_NAME = 120

# The punctuation a person's name may contain, beside letters and the
# marks that accent them.
#
# A CONSERVATIVE GRAMMAR RATHER THAN AN ESCAPE.  A security review found
# the dossier's first heading written into playthrough/transcript.md
# unescaped, so a heading reading `# <img src=x onerror=...>` reached the
# Markdown verbatim and executes in any permissive renderer.  Escaping it
# was the other option and is the wrong one here: the escaped form still
# publishes the payload, as a title reading `&lt;img src=x onerror=...&gt;`,
# which is neither a name nor a refusal.  This artifact is evidence about
# a person, so a heading that is not a name is a mistake to report rather
# than a string to sanitise.
#
# Refusing everything else excludes the whole HTML and Markdown
# metacharacter set as a consequence rather than as a list to maintain:
# no `<`, `>`, `&`, `"`, backtick, `[`, `]`, `(`, `)`, `*`, `_`, `!`, `|`,
# `#`, `\` or `/` can appear, so neither a tag, an entity, a link, an
# image nor an emphasis run can be spelled.  Letters in any script are
# accepted -- refusing a name for being non-English would be parochial,
# not safe.
SURVIVOR_NAME_PUNCTUATION = frozenset(" '\u2019-\u2010\u2011.,")

# The SubRip cue separator, spelled once.  It is also what the
# cue-count gate greps for, which is why a commentary containing it is
# refused rather than rendered.
SRT_ARROW = " --> "

# The timestamp shape the Markdown gate counts.  A FULL STOP is
# accepted in place of the comma, exactly as the gate accepts it, so
# that neither form can slip into the file outside an entry stamp.
TIMESTAMP_RE = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}[,.][0-9]{3}")

# The Markdown entry shape, anchored at column one, as the gate anchors
# it.  Used to count what was generated rather than to trust that it
# was generated correctly.
MARKDOWN_ENTRY_RE = re.compile(
    r"(?m)^\*\*[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}\*\*")

# The SubRip cue line, anchored at both ends exactly as the sibling
# validation anchors it: two-digit hours even at zero, a comma before
# the milliseconds, and one space each side of the arrow.  Every line
# this module writes is measured against it before the file is written,
# so a malformed timecode is caught here rather than by a player
# silently dropping a cue.
TIMECODE_LINE_RE = re.compile(
    r"^[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}"
    r" --> [0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}$")

# THE OUT-OF-CHARACTER VOCABULARY LIVES IN manifest.py, and is imported
# rather than restated.  It used to be a second list here, and the two
# had already drifted: this one named "duration" and "imagemagick" while
# the other named "option", and NEITHER named the game, the engine, a
# source file, pathfinding, a move counter or cheating -- all six of
# which reached the committed record.  Two lists mean two answers to one
# question, and the question decides whether a sentence is publishable.
#
# It is held against every word THIS module generates (see
# assert_in_character) and, since the review, against the survivor's own
# as a REFUSAL rather than an advisory (see voice_problems).

# Styling and positioning codes.  mov_text is a minimal format and the
# track has to be a clean selectable caption stream, so an override
# code, an HTML tag or an ASS block reaching the cue text is refused
# rather than passed to the muxer.
STYLE_RE = re.compile(r"\{\\|</?(?:font|i|b|u|s)\b", re.IGNORECASE)

# Characters no single-line caption or Markdown entry may carry.  A
# line break would split one cue into two blocks and one entry into
# two lines; every other control character is invisible in the file and
# unpredictable in a player.
CONTROL_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

# The artifact layout, which env.sh is the single definition of:
# PLAYTHROUGH_TRANSCRIPT_SRT and PLAYTHROUGH_TRANSCRIPT_MD (env.sh:986
# and env.sh:987).  The relative names are the fallback for a module
# imported without that environment, as by a test.
ENV_SRT = "PLAYTHROUGH_TRANSCRIPT_SRT"
ENV_MARKDOWN = "PLAYTHROUGH_TRANSCRIPT_MD"
SRT_NAME = "transcript.srt"
MARKDOWN_NAME = "transcript.md"

# The survivor's own account of himself, which this module READS and
# never writes: it is the source of the name the transcript is titled
# with.  env.sh exports it as PLAYTHROUGH_DOSSIER (env.sh:1369), so the
# same file is meant by every stage that refers to it.
ENV_DOSSIER = "PLAYTHROUGH_DOSSIER"
DOSSIER_NAME = "dossier.md"

# LF whatever the platform, which is what the committed artifacts'
# `*.srt text` and `*.md text` attributes in .gitattributes expect.
NEWLINE = "\n"

# The staging names used while both artifacts are made durable before
# either is switched in.  Dot-prefixed so a killed run's leftovers are
# obvious, and removed in a finally either way -- which matters because
# .gitignore's terminal `!/playthrough/**` re-includes anything left
# beside the artifacts.
STAGING_PREFIX = ".transcript-"
STAGING_SUFFIX = ".tmp"

# The artifact pair this module publishes, for timeline.ArtifactLock.
# The lock lives in the pipeline's scratch directory OUTSIDE the tree,
# for the same .gitignore reason.
LOCK_NAME = "transcripts"

# The generation manifest this stage publishes beside its artifacts, and
# the directory it lives in.  playthrough/build/ holds every derived,
# committed intermediate -- the concat list, the telemetry sidecar, the
# transition frames -- so the provenance record for the transcripts
# belongs there too, next to the movie's own.
BUILD_DIR_NAME = "build"
GENERATION_MANIFEST_NAME = "transcript.json"


class TranscriptError(Exception):
    """The timeline cannot be turned into an honest transcript.

    Raised in place of writing either file, because a transcript that
    is wrong is worse than no transcript: the cues would be muxed as a
    caption track and read as the record of what happened, and a
    plausible-looking one is not questioned.
    """


class Cue(NamedTuple):
    """One captured frame's cue, in both of its rendered forms.

    `start` and `end` are the timecodes as they appear in the file --
    formatted once, from the timeline's own cue_start and cue_end, and
    shared by both outputs.  That is what makes the Nth stamp in the
    Markdown the same characters as the Nth cue's start in the SubRip
    file rather than a second formatting of the same number.

    `lines` is the caption, wrapped to the cue geometry; `commentary`
    is the survivor's sentence exactly as the timeline carries it, for
    the Markdown.  Immutable because a cue is a record of a frame that
    was captured.
    """

    index: int
    frame: int
    start: str
    end: str
    lines: Sequence[str]
    commentary: str


class Summary(NamedTuple):
    """The evidence a run prints instead of asserting success.

    Three counts that must agree -- one entry, one cue and one stamp
    per captured frame -- beside the two numbers whose equality is the
    timeline invariant's last term: where the final cue ends and what
    the timeline says the film totals.  `total_declared` records
    whether that second number came from the timeline itself or was
    simply read back off the last cue, so a run never reports an
    agreement it had nothing to compare against.
    """

    entry_count: int
    cue_count: int
    stamp_count: int
    final_cue_end: float
    total: float
    total_declared: bool

    @property
    def counts_agree(self) -> bool:
        """Return whether the three per-frame counts are equal."""
        return self.entry_count == self.cue_count == self.stamp_count

    @property
    def total_agrees(self) -> bool:
        """Return whether the final cue ends at the timeline total."""
        return abs(self.final_cue_end - self.total) <= EPSILON


# ---------------------------------------------------------------------
# Reading the timeline.  Everything below this line and above the
# filesystem section is PURE: it takes a document and returns text, so
# a transcript can be built and held to every one of its contracts
# without a file on disk and without writing anything.
# ---------------------------------------------------------------------


def timeline_entries(document: Any) -> List[Dict[str, Any]]:
    """Return the frames array of a timeline document.

    A BARE ARRAY IS REFUSED.  It used to be accepted on the reasoning
    that a caller holding the entries already is legitimate -- but
    validate_timeline() begins by requiring an OBJECT and returns
    immediately for anything else, so an array skipped every
    document-level invariant there is: the totals the entries are checked
    against, the constants the clamp was applied under, the declared
    final cue end that the last cue has to close on, and the manifest
    attestation naming the evidence any of it came from.

    That mattered more here than anywhere: this module writes the CUE
    TIMINGS, and a caption track computed from unvalidated numbers stays
    perfectly self-consistent while drifting away from the film
    render_movie.py encodes from the same document.  The two would look
    consistent and disagree.
    """
    if not isinstance(document, dict):
        raise TranscriptError(
            "the timeline is a %s, not an object with a frames array.  "
            "A bare array skips validate_timeline() entirely -- the "
            "totals, the clamp constants, the declared final cue end "
            "and the manifest attestation all go unchecked -- so it is "
            "refused rather than captioned from"
            % type(document).__name__)
    if "frames" not in document:
        raise TranscriptError(
            "the timeline carries no frames array; a transcript "
            "is one cue per captured frame and there is nothing "
            "here to write one from")
    entries = document["frames"]
    if not isinstance(entries, list):
        raise TranscriptError(
            "the frames are a %s; they are a JSON array, one object "
            "per captured frame" % type(entries).__name__)
    return entries


def transition_gap(document: Any) -> Optional[float]:
    """Return the video seconds a transition is charged, if declared.

    Read from the document's own `transition` field rather than written
    down here, so this module carries no transition constant of its own
    and cannot disagree with the one the cues were walked under.  None
    means the input did not declare it -- the bare-array form -- and
    the gap after a flagged frame is then only required to be positive
    rather than to be an exact length.
    """
    if not isinstance(document, dict):
        return None
    return _finite_number(document.get("transition"))


def declared_total(
    document: Any,
    entries: Sequence[Any],
) -> Tuple[float, bool]:
    """Return the film's total and whether the timeline declared it.

    The timeline carries `total` -- the cue cursor's final value -- and
    `final_cue_end`, computed by different routes so that comparing
    them checks something.  Either is an INDEPENDENT statement of where
    the film ends and is what the last cue is held against.  A bare
    array declares neither, and the total is then the last cue's end
    with nothing to compare it to; the flag says so rather than letting
    a run report an agreement it never tested.
    """
    if isinstance(document, dict):
        for key in ("total", "final_cue_end"):
            value = _finite_number(document.get(key))
            if value is not None:
                return value, True
    last = entries[-1] if entries else None
    if isinstance(last, dict):
        value = _finite_number(last.get("cue_end"))
        if value is not None:
            return value, False
    return 0.0, False


def _finite_number(value: Any) -> Optional[float]:
    """Return `value` as a finite float, or None if it is not one.

    Booleans are rejected on purpose: True is 1.0 to Python's
    arithmetic, and a cue boundary that arrived as a boolean is a
    defect in whatever produced it rather than a one-second offset.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def frame_index(entry: Dict[str, Any], position: int) -> int:
    """Return an entry's frame index, or its position if it has none.

    session.py owns the counter and every real entry carries it; an
    entry that does not is numbered by where it sits, which is what an
    index means.  This mirrors timeline.py's own rule so that a
    transcript and a timeline never number the same capture
    differently.
    """
    value = entry.get("frame")
    if isinstance(value, bool) or not isinstance(value, int):
        return position
    return value


def meta_gate_words(text: Any) -> List[str]:
    """Return the out-of-character CONCEPTS `text` carries.

    A thin pass-through to manifest.py's single implementation, kept as a
    name in this module because the header check and the tests read
    better for it -- not as a second vocabulary.
    """
    return manifest.find_meta_vocabulary(text)


def assert_in_character(text: str, label: str) -> None:
    """Refuse text THIS module generates if it carries meta language.

    Held against the header and against nothing else, because the
    header is the only sentence this module contributes to the
    in-character record.  It exists so that an edit to a string
    constant here can never be what trips the gate: the failure
    arrives at the moment of generation, naming the word, instead of
    arriving later as an unexplained hit in a grep over the artifact.
    """
    hits = meta_gate_words(text)
    if hits:
        raise TranscriptError(
            "%s carries out-of-character wording (%s): %r -- the "
            "record stays in the survivor's voice, and engineering "
            "observations belong in playthrough/TECHNICAL_NOTES.md"
            % (label, ", ".join(hits), text))
    stamps = TIMESTAMP_RE.findall(text)
    if stamps:
        raise TranscriptError(
            "%s carries a timestamp-shaped string (%s): %r -- exactly "
            "one such string may appear per entry and none anywhere "
            "else, so a stamp here would be counted as an entry that "
            "does not exist" % (label, ", ".join(stamps), text))


# ---------------------------------------------------------------------
# Verification.  entry_problems() is TOTAL: it never raises, whatever
# it is handed, and returns every problem it found rather than the
# first.  An operator fixing a hand-edited timeline should see the
# whole list, and a test asserting one check should not have its
# assertion masked by an earlier one aborting the pass.
# ---------------------------------------------------------------------


def entry_problems(
    entries: Any,
    gap: Optional[float] = None,
) -> List[str]:
    """Return every reason `entries` cannot become a transcript.

    An empty list means one cue per entry can be written honestly: the
    indices run 1..n, every window opens before it closes, the windows
    run forward without overlapping, the first opens the film at zero,
    each lasts exactly as long as its frame is on screen, a gap between
    two windows is present when and only when a transition was charged
    for it, and every entry carries a sentence in the survivor's voice
    that a caption can be made from.

    `gap` is the video seconds a transition is charged, from
    :func:`transition_gap`.  When it is known the gap after a flagged
    frame must be exactly that long; when it is not, it must merely be
    positive.
    """
    if not isinstance(entries, list):
        return ["the frames are a %s, not an array"
                % type(entries).__name__]
    if not entries:
        return ["the timeline records no frames at all; a transcript "
                "is one cue per captured frame, and there is no "
                "honest transcript of nothing"]
    problems: List[str] = []
    previous_end: Optional[float] = None
    previous_flag: Optional[bool] = None
    previous_position = 0
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(
                "entry %d is a %s; every frame is a JSON object"
                % (position, type(entry).__name__))
            # Nothing to compare the next window against, so the three
            # carried values move together rather than leaving a stale
            # position paired with a cleared boundary.
            previous_end = None
            previous_flag = None
            previous_position = position
            continue
        problems.extend(_index_problems(entry, position))
        problems.extend(_commentary_problems(entry, position))
        start = _finite_number(entry.get("cue_start"))
        end = _finite_number(entry.get("cue_end"))
        problems.extend(_window_problems(entry, position, start, end))
        flag = entry.get("transition_after")
        if flag is not None and not isinstance(flag, bool):
            problems.append(
                "entry %d records %r as its transition flag; it is "
                "true or false" % (position, flag))
            flag = None
        problems.extend(_gap_problems(
            position, start, previous_position, previous_end,
            previous_flag, gap))
        previous_end = end
        previous_flag = flag
        previous_position = position
    opening = entries[0]
    first = (_finite_number(opening.get("cue_start"))
             if isinstance(opening, dict) else None)
    if first is not None and abs(first) > EPSILON:
        problems.append(
            "the first cue opens at %rs; the film starts at zero, and "
            "a caption track that starts late is out of step with the "
            "picture for its whole length" % first)
    return problems


def _index_problems(entry: Dict[str, Any], position: int) -> List[str]:
    """Report a frame index that is not the position it sits in."""
    value = entry.get("frame")
    if value is None:
        return []
    if isinstance(value, bool) or not isinstance(value, int):
        return ["entry %d records a %s as its frame index; the index "
                "is an integer from 1"
                % (position, type(value).__name__)]
    if value != position:
        return ["entry %d records frame %d; one capture per keystroke "
                "numbers the frames 1..n, so a transcript cannot pair "
                "them with cues while the two disagree"
                % (position, value)]
    return []


def _window_problems(
    entry: Dict[str, Any],
    position: int,
    start: Optional[float],
    end: Optional[float],
) -> List[str]:
    """Report a cue window that cannot be shown as it stands.

    A boundary that is not a finite number, a window that closes before
    it opens, and -- where the entry declares its on-screen seconds -- a
    window that does not last exactly as long as the picture it belongs
    to.  That last one is the check that catches a cue rewritten by
    hand: the caption would be shown for a different length of time
    than the frame it describes.
    """
    problems: List[str] = []
    if start is None:
        problems.append(
            "entry %d records %r as its cue start; a cue boundary is "
            "a finite number of seconds"
            % (position, entry.get("cue_start")))
    elif start < 0.0:
        problems.append(
            "entry %d opens at %rs; video time does not run before "
            "zero" % (position, start))
    if end is None:
        problems.append(
            "entry %d records %r as its cue end; a cue boundary is a "
            "finite number of seconds"
            % (position, entry.get("cue_end")))
    if start is None or end is None:
        return problems
    if end <= start:
        problems.append(
            "entry %d opens at %rs and closes at %rs; a cue has to "
            "end after it starts, or no player will show it"
            % (position, start, end))
        return problems
    if entry.get("duration") is None:
        return problems
    on_screen = _finite_number(entry["duration"])
    if on_screen is None:
        problems.append(
            "entry %d records %r as its on-screen seconds; they are a "
            "finite number" % (position, entry["duration"]))
    elif abs((end - start) - on_screen) > EPSILON:
        problems.append(
            "entry %d is on screen for %rs but its cue spans %rs; the "
            "caption is shown for exactly as long as the picture it "
            "belongs to" % (position, on_screen, end - start))
    return problems


def _gap_problems(
    position: int,
    start: Optional[float],
    previous_position: int,
    previous_end: Optional[float],
    previous_flag: Optional[bool],
    gap: Optional[float],
) -> List[str]:
    """Report cues that overlap, or a gap nothing was charged for.

    This is where caption drift would show up.  A gap in video time
    exists only because a transition was inserted, so a gap after an
    unflagged frame means seconds appeared from nowhere, and a flagged
    frame with no gap after it means the transition seconds were never
    charged to the cursor -- the exact defect that puts the captions
    increasingly ahead of the picture as the film goes on.
    """
    if start is None or previous_end is None:
        return []
    measured = start - previous_end
    if measured < -EPSILON:
        return ["entry %d opens at %rs but entry %d had not closed "
                "until %rs; cues cannot overlap"
                % (position, start, previous_position, previous_end)]
    if previous_flag is None:
        return []
    if not previous_flag:
        if abs(measured) > EPSILON:
            return ["entry %d opens %rs after entry %d closed, but "
                    "entry %d is not flagged for a transition, so "
                    "nothing was charged for that gap"
                    % (position, measured, previous_position,
                       previous_position)]
        return []
    if gap is None:
        if measured <= EPSILON:
            return ["entry %d is flagged for a transition but entry "
                    "%d opens the instant it closed; the transition "
                    "seconds were never charged to video time"
                    % (previous_position, position)]
        return []
    if abs(measured - gap) > EPSILON:
        return ["entry %d is flagged for a transition of %rs but "
                "entry %d opens %rs after it closed; the captions and "
                "the picture would not agree from here on"
                % (previous_position, gap, position, measured)]
    return []


def _commentary_problems(
    entry: Dict[str, Any],
    position: int,
) -> List[str]:
    """Report a sentence that cannot honestly become a cue.

    An absent or blank one is a hole in the record, not something to
    fill in: one keystroke made one capture, and the reason for it is
    either written down or it is not.  A line break or a control
    character would split one cue into two blocks.  A timestamp-shaped
    string or a cue arrow would each add a match to a count the
    artifacts are checked by, so both are refused here where the
    message can name the entry, rather than surfacing later as an
    arithmetic mismatch in a gate.  Styling and positioning codes are
    refused because the track is a plain selectable caption stream.
    """
    value = entry.get("commentary")
    if value is None:
        return ["entry %d carries no commentary; every captured frame "
                "records why the survivor acted, and an empty caption "
                "is not a record of anything" % position]
    if not isinstance(value, str):
        return ["entry %d records a %s as its commentary; it is text"
                % (position, type(value).__name__)]
    if not value.strip():
        return ["entry %d carries a blank commentary; every captured "
                "frame records why the survivor acted" % position]
    problems: List[str] = []
    if CONTROL_RE.search(value):
        problems.append(
            "entry %d's commentary carries a line break or a control "
            "character; one captured frame is one cue of one "
            "sentence" % position)
    stamps = TIMESTAMP_RE.findall(value)
    if stamps:
        problems.append(
            "entry %d's commentary carries a timestamp-shaped string "
            "(%s); one such string appears per entry and it is the "
            "entry's own, so this would be counted as an extra entry "
            "-- please say the time another way"
            % (position, ", ".join(stamps)))
    if SRT_ARROW in value:
        problems.append(
            "entry %d's commentary carries %r, which is the cue "
            "separator the cue count is measured with; please say it "
            "another way" % (position, SRT_ARROW))
    if STYLE_RE.search(value):
        problems.append(
            "entry %d's commentary carries markup or an override "
            "code; the caption track is plain selectable text and is "
            "never styled or positioned" % position)
    return problems


def document_problems(
    document: Any,
    entries: Sequence[Any],
) -> List[str]:
    """Return the document-level reasons a transcript is not honest.

    Two checks the entries alone cannot make.  The first is the
    sibling's OWN validator, run here rather than trusted from the fact
    that it ran when the file was written: it holds the document to the
    clamp bounds, the strictly-greater transition rule and the
    invariant sum(durations) + sum(transitions) == total == final cue
    end, so a hand-edited timeline is caught before its numbers become
    a caption track.  The second is the one the caption file is
    ultimately judged by -- the last cue must close exactly where the
    timeline says the film ends, because that single equality is what
    keeps the container and the subtitle stream the same length.

    A bare array declares neither a document nor a total, so only the
    entry-level checks apply to it and this returns nothing.
    """
    problems: List[str] = []
    if isinstance(document, dict):
        problems.extend(validate_timeline(document))
    total, was_declared = declared_total(document, entries)
    if not was_declared:
        return problems
    last = entries[-1] if entries else None
    closes = (_finite_number(last.get("cue_end"))
              if isinstance(last, dict) else None)
    if closes is not None and abs(closes - total) > EPSILON:
        problems.append(
            "the last cue closes at %rs but the timeline totals %rs; "
            "the caption track and the container have to end together"
            % (closes, total))
    return problems


# ---------------------------------------------------------------------
# The caption.  Fitting the sentence to two short lines is the ONLY
# transformation this module performs on the survivor's words, and it
# is presentational: playthrough/transcript.md keeps the whole
# sentence, whatever the caption had room for.
# ---------------------------------------------------------------------


def wrap_cue_text(
    text: str,
    width: int = CUE_LINE_WIDTH,
) -> List[str]:
    """Return `text` wrapped to `width`, WHOLE.  Nothing is dropped.

    Wrapped at word boundaries only: neither long words nor hyphens are
    broken through, so a caption never shows half a word.  A single word
    longer than the width therefore overruns it rather than being cut,
    which is the right trade for a format whose width is a readability
    convention and not a hard limit.

    THE SENTENCE IS NEVER SHORTENED HERE.  This used to cap the result at
    two lines and mark the cut with a bracketed elision, which left two
    fifths of the first re-recorded session's captions carrying less than
    the survivor said -- and the requirement is that the timestamped
    transcript IS the caption track.  So this function returns whatever
    lines the sentence needs, the words are the survivor's own, in order,
    and every one of them is in the result.

    The geometry is still a contract, and it is held one level up: a
    sentence that needs more than CUE_MAX_LINES lines is REFUSED by
    :func:`caption_length_problems`, which names the entry, its frame and
    its line count so the source commentary can be written shorter.  A
    refusal upstream and no truncation downstream is the only combination
    that satisfies both halves of the requirement.
    """
    if not isinstance(text, str):
        raise TranscriptError(
            "a caption is made from text, got %s" % type(text).__name__)
    # Runs of whitespace collapse to single spaces so that the measured
    # width is the width a player will show.  The manifest already
    # refuses line breaks and control characters in a commentary, so on
    # real input this only ever tidies a double space.
    collapsed = " ".join(text.split())
    if not collapsed:
        raise TranscriptError(
            "a caption cannot be made from blank text; every captured "
            "frame records why the survivor acted")
    if width < 1:
        raise TranscriptError(
            "a caption needs a line of at least one column, got %d"
            % width)
    return textwrap.wrap(collapsed, width=width,
                         break_long_words=False,
                         break_on_hyphens=False)


# ---------------------------------------------------------------------
# The single pass.  build_cues() formats each timecode ONCE, and both
# renderers below read those same strings, so the Nth stamp in the
# Markdown is the same characters as the Nth cue's start in the SubRip
# file by construction rather than by coincidence.
# ---------------------------------------------------------------------


def _timecode(value: Any, position: int, key: str) -> str:
    """Return one cue boundary as a SubRip timecode.

    The formatter is timeline.py's, so the captions, the film and the
    tests share one implementation of the timecode; its complaint is
    re-raised as this module's error so a caller has one exception type
    to catch.
    """
    try:
        return format_srt_timecode(value)
    except TimelineError as err:
        raise TranscriptError(
            "entry %d's %s cannot be written as a timecode: %s"
            % (position, key, err)) from err


def build_cues(entries: Any, gap: Optional[float] = None) -> List[Cue]:
    """Return one cue per entry, in order.  Nothing is dropped.

    The entries are held to :func:`entry_problems` first and refused
    whole rather than in part: a transcript missing one frame's cue
    would still look like a transcript, so there is no partial
    success here.
    """
    problems = entry_problems(entries, gap)
    if problems:
        raise TranscriptError(
            "refusing to write a transcript from frames that fail "
            "their own checks: %s" % "; ".join(problems))
    cues = []
    for position, entry in enumerate(entries, start=1):
        commentary = entry["commentary"]
        lines = tuple(wrap_cue_text(commentary))
        cues.append(Cue(
            index=position,
            frame=frame_index(entry, position),
            start=_timecode(entry["cue_start"], position, "cue start"),
            end=_timecode(entry["cue_end"], position, "cue end"),
            lines=lines,
            commentary=commentary,
        ))
    return cues


def render_srt(cues: Sequence[Cue]) -> str:
    """Return the exact text playthrough/transcript.srt holds.

    SubRip, to the letter: a sequence number from 1, a timecode line
    measured against TIMECODE_LINE_RE before it is accepted, one or two
    lines of plain text, a blank line between cues, and a single
    trailing newline after the last cue's text with no empty block
    behind it.  UTF-8 without a byte-order mark, which
    :func:`write_text` guarantees -- a mark would sit in front of cue
    one's sequence number and stop it being read as one.

    THE LINE COUNT IS REFUSED HERE, NOT REPAIRED HERE, and the
    distinction is the whole of the caption contract.  A cue of more
    than CUE_MAX_LINES lines raises, so no code path -- not
    :func:`build_transcripts`, not a caller assembling cues itself --
    can put an unreadable caption into the file; and nothing in this
    function shortens, elides or truncates a sentence to make it fit,
    because capping a cue and marking the cut left 168 of 395 captions
    carrying less than the survivor said.  The remedy for a refusal is
    a shorter sentence in the source commentary, regenerated through the
    whole chain in one pass.
    """
    if not cues:
        raise TranscriptError(
            "there are no cues to write; a caption track with no cues "
            "is not a transcript of anything")
    blocks = []
    for position, cue in enumerate(cues, start=1):
        if cue.index != position:
            raise TranscriptError(
                "cue %d is numbered %d; SubRip sequence numbers run "
                "from 1 without a gap" % (position, cue.index))
        if not cue.lines:
            raise TranscriptError(
                "cue %d has no text; every captured frame records why "
                "the survivor acted" % position)
        if len(cue.lines) > CUE_MAX_LINES:
            raise TranscriptError(
                "cue %d wraps to %d lines of %d columns; a cue carries "
                "at most %d.  The sentence is not cut to fit: shorten "
                "it in the source commentary and regenerate"
                % (position, len(cue.lines), CUE_LINE_WIDTH,
                   CUE_MAX_LINES))

        timing = cue.start + SRT_ARROW + cue.end
        if not TIMECODE_LINE_RE.match(timing):
            raise TranscriptError(
                "cue %d's timing line is %r; SubRip wants "
                "HH:MM:SS,mmm --> HH:MM:SS,mmm with a comma"
                % (position, timing))
        for line in cue.lines:
            if STYLE_RE.search(line) or CONTROL_RE.search(line):
                raise TranscriptError(
                    "cue %d's text carries markup, an override code "
                    "or a control character: %r" % (position, line))
        blocks.append("\n".join([str(cue.index), timing] +
                                list(cue.lines)))
    return "\n\n".join(blocks) + "\n"


def markdown_counts(text: str) -> Tuple[int, int]:
    """Return a Markdown body's entry count and timestamp count.

    Measured with the same two patterns the artifact is checked by, so
    what this module reports is what a reader grepping the file will
    find.  The two numbers must be equal -- one stamp per entry and
    none anywhere else -- and both must equal the frame count.
    """
    return (len(MARKDOWN_ENTRY_RE.findall(text)),
            len(TIMESTAMP_RE.findall(text)))


def render_markdown(cues: Sequence[Cue],
                    header: Optional[str] = None) -> str:
    """Return the exact text playthrough/transcript.md holds.

    One line per captured frame, uniform: the cue's start in bold at
    column one, a space, and the survivor's sentence exactly as it was
    written.  Nothing else is added -- no headings between entries, no
    bullets, no table, no images, no links, and no machine-readable
    block at the end, because playthrough/timeline.json is the machine
    artifact and this is the human one.

    The only sentence this module contributes is the header, and it is
    held to the out-of-character gate and to the timestamp count before
    it is used.  The rendered body is then MEASURED rather than
    trusted: exactly one timestamp-shaped string per entry, and an
    entry for every cue.

    `header` is the two generated lines, which name the survivor of THIS
    record.  It is derived from playthrough/dossier.md by
    :func:`markdown_header` when the caller does not supply it, so the
    person a reader meets in the title is the person the dossier
    introduces -- never a name spelled in this source.  A supplied
    header is held to exactly the same gates as a derived one.
    """
    if not cues:
        raise TranscriptError(
            "there are no entries to write; a transcript with no "
            "entries is not a record of anything")
    heading = markdown_header() if header is None else header
    assert_in_character(heading, "the transcript header")
    # BOTH PATHS, because only one of them derives the name.  A supplied
    # header never passes through read_survivor_name, so the name grammar
    # there does not see it -- and this function's own docstring promises
    # that "a supplied header is held to exactly the same gates as a
    # derived one".  This is the gate that makes that true.
    assert_no_raw_markup(heading, "the transcript header")
    entries = ["**%s** %s" % (cue.start, cue.commentary)
               for cue in cues]
    text = "%s\n\n%s\n" % (heading, "\n\n".join(entries))
    counted, stamps = markdown_counts(text)
    if counted != len(cues):
        raise TranscriptError(
            "the transcript rendered %d entr(ies) for %d cue(s); one "
            "captured frame makes exactly one entry"
            % (counted, len(cues)))
    if stamps != len(cues):
        raise TranscriptError(
            "the transcript carries %d timestamp-shaped string(s) for "
            "%d entr(ies); exactly one appears per entry and none "
            "anywhere else" % (stamps, len(cues)))
    return text


def build_transcripts(
    document: Any,
    header: Optional[str] = None,
) -> Tuple[str, str, List[Cue]]:
    """Return the SubRip text, the Markdown text and the cues.

    The whole of this module's work, in the order it has to happen:
    take the frames from ONE document, hold the document and its frames
    to every check, derive the cues ONCE, and render both bodies from
    those same cues.  Neither output is derived from the other and the
    input is read once, so the human record and the machine cues cannot
    disagree about a single number.

    Returns the cues as well because the caller prints the evidence: it
    is the same list both bodies were rendered from, not a second walk
    over the timeline.

    `header` is the Markdown's two generated lines; when it is None the
    title is derived from playthrough/dossier.md, so the survivor named
    in the transcript is the survivor the dossier introduces.
    """
    entries = timeline_entries(document)
    problems = document_problems(document, entries)
    if problems:
        raise TranscriptError(
            "refusing to write a transcript from a timeline that "
            "fails its own checks: %s" % "; ".join(problems))
    cues = build_cues(entries, transition_gap(document))
    # THE CAPTION GEOMETRY, held before either body is rendered so that
    # EVERY offending entry is named in one message rather than the
    # first one aborting the pass.  render_srt() refuses the same cue
    # on its own account; this is the report an operator fixes from.
    overlong = caption_length_problems(cues)
    if overlong:
        raise TranscriptError(
            "refusing to write a transcript whose captions do not fit "
            "the cue geometry: %s" % "; ".join(overlong))
    return render_srt(cues), render_markdown(cues, header), cues


def summarise(
    document: Any,
    entries: Sequence[Any],
    cues: Sequence[Cue],
    markdown: str,
) -> Summary:
    """Return the counts and totals a run reports as its evidence.

    Every number is measured from what was actually produced -- the
    stamps are counted in the rendered Markdown, not assumed from the
    cue list -- so the summary is evidence rather than an assertion
    that the module did what it meant to.
    """
    total, was_declared = declared_total(document, entries)
    last = entries[-1] if entries else None
    closes = (_finite_number(last.get("cue_end"))
              if isinstance(last, dict) else None)
    return Summary(
        entry_count=len(entries),
        cue_count=len(cues),
        stamp_count=markdown_counts(markdown)[1],
        final_cue_end=closes if closes is not None else 0.0,
        total=total,
        total_declared=was_declared,
    )


def summary_line(summary: Summary, destination: str) -> str:
    """Return the one line a successful run prints."""
    if summary.total_declared:
        against = ("the timeline's own total of %s s"
                   % format(summary.total, ".3f"))
    else:
        against = ("%s s, which the frames alone gave nothing to "
                   "check it against" % format(summary.total, ".3f"))
    return ("transcript ok: %d entr(ies), %d cue(s), %d stamp(s), "
            "last cue closes at %s = %s -> %s"
            % (summary.entry_count, summary.cue_count,
               summary.stamp_count,
               _timecode(summary.final_cue_end, summary.entry_count,
                         "final cue end"),
               against, destination))


def summary_problems(summary: Summary) -> List[str]:
    """Return the reasons a run's own evidence does not add up.

    The three counts have to be one number -- one captured frame, one
    cue, one entry -- and the last cue has to close where the timeline
    says the film ends.  Checked after both bodies exist, from what was
    actually rendered, because that is the point at which a mismatch
    still costs nothing and after which it becomes a caption track that
    drifts.
    """
    problems = []
    if not summary.counts_agree:
        problems.append(
            "%d frame(s) produced %d cue(s) and %d transcript "
            "entr(ies); one captured frame makes exactly one of each"
            % (summary.entry_count, summary.cue_count,
               summary.stamp_count))
    if summary.total_declared and not summary.total_agrees:
        problems.append(
            "the last cue closes at %rs but the timeline totals %rs; "
            "the captions and the container have to end together"
            % (summary.final_cue_end, summary.total))
    return problems


def voice_problems(cues: Sequence[Cue]) -> List[str]:
    """Refuse out-of-character wording in the survivor's own words.

    A PUBLICATION-BLOCKING GATE, and it used to be an advisory that
    printed a line and wrote the file anyway.  Two things were wrong with
    that.  The vocabulary was short -- it named neither the game, nor the
    engine, nor a source file, nor pathfinding, nor a move counter, nor
    cheating, and every one of those reached the committed transcript --
    and a warning is not a gate: the requirement that engineering and
    "gamey" remarks stay out of the in-character record cannot be
    satisfied by a stderr line beside a written file.

    The vocabulary and the message come from manifest.py, which is the
    module that also refuses the sentence at write time.  One
    implementation, so the two cannot disagree.

    WHAT A HIT MEANS, stated exactly, because the wrong answer was
    written here once.  It used to say the session had to be RE-RECORDED,
    on the grounds that the sentence was already in an append-only
    record.  That is not the remedy and cannot be: `commentary` is
    AUTHORED prose, not an observation, and the observations -- the frame,
    its file, its capture time, its clock reading and the keystroke that
    produced it -- are what the append-only rule protects.  So the
    sentence is corrected AT SOURCE in playthrough/manifest.jsonl, with
    the amendment and the unchanged observational digest recorded in
    playthrough/TECHNICAL_NOTES.md, and every derived artifact is
    regenerated in one pass.  What is never done is editing this file's
    output by hand, which would put the caption track out of step with
    the record it is supposed to be.
    """
    problems = []
    for cue in cues:
        problem = manifest.meta_vocabulary_problem(
            cue.commentary, "entry %d commentary" % cue.index)
        if problem is not None:
            problems.append(
                "%s  Correct it at source in "
                "playthrough/manifest.jsonl, record the amendment in "
                "playthrough/TECHNICAL_NOTES.md, and regenerate the "
                "whole chain; this file is never edited by hand."
                % problem)
    return problems


def honesty_problems(cues: Sequence[Cue],
                     entries: Sequence[Dict[str, Any]]) -> List[str]:
    """Refuse a stated time or date the captured frames contradict.

    THE PUBLICATION HALF OF THE GATE THE FALSE FRAME-308 STATEMENT WALKED
    PAST: its commentary reads "It is ten past eight in the morning on the
    twenty-eighth of May" against timing fields of 08:05:36 and
    "Thursday, May 20", and every structural check passed over it because
    the row is internally consistent.

    EACH ENTRY IS JUDGED AGAINST THE READING ITS AUTHOR HAD IN FRONT OF
    THEM -- the PREVIOUS entry's clock and date -- AND against its own,
    accepting agreement with either.  The commentary is the reason the
    survivor pressed that key, so it belongs to the moment before it, and
    judging "five past eight, so I am going to lie down" against the clock
    a nine-hour sleep produced would refuse an honest sentence; equally,
    the frame this cue is DISPLAYED OVER carries its own reading, and a
    sentence that agrees with what the viewer can see is not a
    fabrication.  Both readings were observed and both are committed, so
    either is honest evidence.  The first entry has nothing before it and
    is judged against its own reading alone.

    manifest.py owns the parser and the tolerances, for the same reason
    the voice gate does.
    """
    problems = []
    previous_clock = None
    previous_date = None
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        commentary = entry.get("commentary")
        clock = entry.get("ingame_clock")
        date_text = entry.get("ingame_date")
        against_clock = (clock if previous_clock is None
                         else previous_clock)
        against_date = (date_text if previous_date is None
                        else previous_date)
        problems.extend(manifest.clock_honesty_problems(
            commentary, against_clock, against_date,
            "entry %d commentary" % (position + 1),
            also_clock=clock, also_date=date_text))
        previous_clock = clock
        if date_text:
            previous_date = date_text
    return problems


def overlong_entries(cues: Sequence[Cue]) -> List[int]:
    """Return the entries whose caption exceeds the cue geometry."""
    return [cue.index for cue in cues
            if len(cue.lines) > CUE_MAX_LINES]


def caption_length_problems(cues: Sequence[Cue]) -> List[str]:
    """Refuse a caption that does not fit the cue geometry.

    A PUBLICATION-BLOCKING GATE, and it used to be an advisory that
    printed one summary line and wrote the files anyway.  That is how 88
    of 419 shipped cues came to carry three, four, five and six lines,
    one of them inside a 250 ms window: the contract says at most
    CUE_MAX_LINES lines of about CUE_LINE_WIDTH columns, and a contract
    reported on stderr is not enforced.

    ONE PROBLEM PER OFFENDING CUE, naming the entry, the frame it
    describes and how many lines it needs, because the operator has to
    rewrite that sentence and a bounded sample would hide most of the
    work.  Nothing is shortened to satisfy this: the remedy is a shorter
    sentence in the source commentary, amended at
    playthrough/manifest.jsonl and regenerated through every derived
    artifact in one pass.
    """
    problems = []
    for cue in cues:
        if len(cue.lines) <= CUE_MAX_LINES:
            continue
        problems.append(
            "entry %d (frame %d) needs %d lines of %d columns; a cue "
            "carries at most %d, and this one is on screen for its "
            "frame's own window.  Shorten the sentence in the source "
            "commentary and regenerate -- the caption is never cut to "
            "fit.  The text was: %r"
            % (cue.index, cue.frame, len(cue.lines), CUE_LINE_WIDTH,
               CUE_MAX_LINES, cue.commentary))
    return problems


# ---------------------------------------------------------------------
# Filesystem.  Both artifacts must land inside the playthrough/ tree
# derived from THIS MODULE'S own location: they are the record of a
# captured session, and a caption file written somewhere else would be
# muxed into the film as though it were the record.  Nothing here uses
# a shell, an eval or a path it has not validated, so the new tooling
# adds no alert to the repository's CodeQL gate, and there is no
# network surface of any kind.
# ---------------------------------------------------------------------


def _warn(message: str) -> None:
    """Report a non-fatal problem on stderr and carry on.

    The prefix matches playthrough_warn() in
    playthrough/tooling/env.sh and the sibling modules' own reporting,
    so every stage of the pipeline is recognisable in one session log.
    """
    print("playthrough: WARNING: make_srt.py: %s" % message,
          file=sys.stderr, flush=True)


def _module_dir() -> str:
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _playthrough_dir() -> str:
    """Return the absolute playthrough/ directory.

    Derived from this module's own location rather than from the
    working directory, exactly as timeline.py and manifest.py derive
    it, so a helper is correct even when it is invoked from somewhere
    else.
    """
    return os.path.dirname(_module_dir())


def _default_path(variable: str, name: str) -> str:
    """Return an artifact path from env.sh, or the layout default.

    env.sh is the single definition of where the artifacts live, so it
    is honoured first; the fallback keeps the module correct when
    nothing has been sourced, as when it is imported by a test.
    """
    from_env = os.environ.get(variable)
    if from_env and from_env.strip():
        return os.path.abspath(from_env)
    return os.path.join(_playthrough_dir(), name)


def default_srt_path() -> str:
    """Return the caption file this module writes."""
    return _default_path(ENV_SRT, SRT_NAME)


def default_markdown_path() -> str:
    """Return the transcript this module writes."""
    return _default_path(ENV_MARKDOWN, MARKDOWN_NAME)


def default_dossier_path(root: Optional[str] = None) -> str:
    """Return the dossier this module reads the survivor's name from.

    `root` is a call site's argument and nothing else, exactly as it is
    on validated_output_path(): it relocates the approved tree for a
    test that owns a temporary directory, and no environment variable
    reaches it.  Without one the layout is env.sh's PLAYTHROUGH_DOSSIER,
    falling back to the module's own playthrough/dossier.md.
    """
    if root is None:
        return _default_path(ENV_DOSSIER, DOSSIER_NAME)
    try:
        approved = approved_root(root)
    except TimelineError as err:
        raise TranscriptError(str(err)) from err
    return os.path.join(approved, DOSSIER_NAME)


def read_survivor_name(dossier_path: Optional[str] = None,
                       root: Optional[str] = None) -> str:
    """Return the survivor's name as the dossier's first heading gives it.

    THE ONE PLACE THE NAME IS ESTABLISHED.  playthrough/dossier.md is
    the survivor's own account of themselves, written before the first
    keystroke, and its first level-one heading is that name -- so it is
    the name every other layer of the record agrees with, and the name
    this module's title has to carry.  Reading it here rather than
    spelling it in a constant is what makes "one survivor, one name"
    true of a record that can be re-captured.

    FAILS CLOSED, IN EVERY DIRECTION.  A missing dossier, a dossier that
    is not a regular file, one this module cannot read, one with no
    level-one heading, or a heading long enough to be a paragraph rather
    than a name each raise TranscriptError instead of yielding a
    fallback: a transcript titled with a guess is exactly the defect
    this derivation exists to make impossible.  The dossier is READ and
    never written, and it is held to the same containment and
    no-symlink rules as this stage's own destinations.
    """
    path = (default_dossier_path(root) if dossier_path is None
            else dossier_path)
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if not isinstance(path, str) or not path.strip():
        raise TranscriptError(
            "the dossier path must be a non-empty string, got %r"
            % (path,))
    if "\x00" in path:
        raise TranscriptError(
            "the dossier path must not contain a NUL byte")
    resolved = os.path.abspath(path)
    try:
        approved = approved_root(root)
    except TimelineError as err:
        raise TranscriptError(str(err)) from err
    canonical = os.path.realpath(resolved)
    if not _within(canonical, approved):
        raise TranscriptError(
            "the dossier must stay inside %s, but %s resolves to %s"
            % (approved, resolved, canonical))
    _refuse_symlink(resolved, approved, "the dossier")
    if not os.path.isfile(resolved):
        raise TranscriptError(
            "%s does not exist or is not a regular file, so the "
            "survivor this record belongs to cannot be established.  "
            "The transcript is titled with the name the dossier gives "
            "and with no other, so nothing is written"
            % relative_to_repo(resolved))
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as err:
        raise TranscriptError(
            "%s could not be read (%s), so the survivor's name cannot "
            "be established and nothing is written"
            % (relative_to_repo(resolved), err)) from err
    match = DOSSIER_HEADING_RE.search(text)
    if match is None:
        raise TranscriptError(
            "%s carries no level-one heading, so it names nobody this "
            "transcript could be titled with.  The dossier's first "
            "heading is the survivor's name" % relative_to_repo(resolved))
    name = " ".join(match.group(1).split())
    if not name:
        raise TranscriptError(
            "%s opens with an empty level-one heading"
            % relative_to_repo(resolved))
    if len(name) > MAX_SURVIVOR_NAME:
        raise TranscriptError(
            "%s opens with a %d-character heading, which is a paragraph "
            "rather than a name (the ceiling is %d); nothing is written "
            "from a heading this module has evidently misread"
            % (relative_to_repo(resolved), len(name), MAX_SURVIVOR_NAME))
    if CONTROL_RE.search(name):
        raise TranscriptError(
            "%s opens with a heading carrying a control character"
            % relative_to_repo(resolved))
    assert_survivor_name_grammar(name, relative_to_repo(resolved))
    return name


def assert_no_raw_markup(text: str, label: str) -> None:
    """Refuse text that could be rendered as HTML rather than read.

    The header is written into a Markdown document, and Markdown passes
    raw HTML straight through to the renderer.  read_survivor_name's
    grammar already makes a derived header safe by construction, but a
    header can also be SUPPLIED, and that path derives nothing -- so the
    two are held to the same standard here.

    Deliberately narrow: an angle bracket, an ampersand, or an
    `onsomething=` attribute.  It is not a general HTML sanitiser and does
    not try to be -- the header is two generated lines, and anything in it
    resembling a tag means something has gone wrong upstream rather than
    that a document needs cleaning.

    :raises TranscriptError: naming what was found.
    """
    for needle, why in (
            ("<", "an angle bracket, which opens an HTML tag"),
            (">", "an angle bracket, which closes an HTML tag"),
            ("&", "an ampersand, which opens an HTML entity"),
    ):
        if needle in text:
            raise TranscriptError(
                "%s contains %s (%r).  The header is written into "
                "Markdown, which passes raw HTML to the renderer, so it "
                "is refused rather than escaped: this artifact is "
                "evidence, and a title carrying markup is a fault to "
                "report rather than a string to clean"
                % (label, why, needle))
    if re.search(r"\bon[a-z]+\s*=", text, re.IGNORECASE):
        raise TranscriptError(
            "%s contains an HTML event-handler attribute, which would "
            "execute in a permissive renderer" % label)


def assert_survivor_name_grammar(name: str, source: str) -> None:
    """Refuse a survivor name that is not shaped like one.

    Letters and the combining marks that accent them, plus the small
    punctuation set a person's name uses -- space, apostrophe (straight or
    typographic), hyphen, period, comma.  Everything else is refused,
    naming the character and its codepoint.

    This is what keeps raw markup out of playthrough/transcript.md.  The
    name is written into a Markdown heading, and a heading reading
    `<img src=x onerror=...>` executes in a permissive renderer -- so the
    grammar, not an escape, is the control: see
    SURVIVOR_NAME_PUNCTUATION for why publishing an escaped payload would
    be the wrong answer for an evidence artifact.

    Digits are refused as well.  Nothing needs them -- a regnal suffix is
    spelled in letters -- and excluding them closes numeric character
    references without a second rule.

    :raises TranscriptError: naming the first character that fails.
    """
    for position, char in enumerate(name, start=1):
        if char in SURVIVOR_NAME_PUNCTUATION:
            continue
        category = unicodedata.category(char)
        # L* is every letter; M* is every combining mark, which is how an
        # accent is spelled when it is not precomposed.
        if category[0] in ("L", "M"):
            continue
        raise TranscriptError(
            "%s opens with a heading that is not shaped like a name: "
            "character %d is %r (U+%04X, Unicode category %s), and a "
            "survivor's name may contain only letters, the marks that "
            "accent them, and the punctuation %r.  The heading is the "
            "name this transcript is titled with and is written into "
            "Markdown, so a heading carrying markup is refused rather "
            "than escaped -- an escaped payload is still published, and "
            "would be neither a name nor a refusal"
            % (source, position, char, ord(char), category,
               "".join(sorted(SURVIVOR_NAME_PUNCTUATION))))


def markdown_header(dossier_path: Optional[str] = None,
                    root: Optional[str] = None) -> str:
    """Return the transcript's two generated lines.

    The title names the survivor playthrough/dossier.md introduces, so a
    reader arriving at either artifact meets the same person under the
    same heading -- a property that is now derived rather than asserted.
    Both lines are held to the out-of-character gate and to the
    no-timestamp rule here, at the moment they are built, so a dossier
    heading carrying an engineering word or a timestamp-shaped string is
    refused with the word named instead of reaching the artifact.
    """
    name = read_survivor_name(dossier_path, root)
    header = "# %s%s\n\n%s" % (name, MARKDOWN_TITLE_SUFFIX,
                               MARKDOWN_TIMESTAMP_LINE)
    assert_in_character(header, "the transcript header")
    return header


def _refuse_symlink(resolved: str, root: str, label: str) -> None:
    """Refuse `resolved` if it or a component below `root` is a link.

    Containment alone is not enough: a link inside the tree still
    points at something else inside the tree, and one planted link
    could make a write land on the manifest, a captured image or the
    film while the write itself reported success.
    """
    if os.path.islink(resolved):
        raise TranscriptError(
            "%s is a symbolic link: %s.  This module writes files, it "
            "does not follow links to them." % (label, resolved))
    if not _within(resolved, root):
        # Reached through a symlinked ancestor ABOVE the root -- a
        # checkout under a linked directory.  Containment is already
        # proved, and components above the root are not ours to police.
        return
    current = root
    for part in os.path.relpath(resolved, root).split(os.sep):
        if part in ("", os.curdir):
            continue
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise TranscriptError(
                "%s has a symlinked component at %s; a link there "
                "could redirect the transcript inside %s"
                % (label, current, root))


def _within(path: str, root: str) -> bool:
    """Return whether `path` is `root` itself or lies beneath it."""
    return path == root or path.startswith(root + os.sep)


def validated_output_path(
    value: Any,
    label: str,
    root: Optional[str] = None,
) -> str:
    """Return an absolute path this module may write, or raise.

    Shape first -- a non-empty string or os.PathLike with no NUL byte,
    naming a file rather than a directory -- then canonical containment
    inside the approved root, then no symbolic link on the path or on
    any component below that root, then no existing non-regular file
    where the artifact goes.  A FIFO, a device node, /etc/anything and
    a path outside playthrough/ are all refused here rather than
    opened.

    `root` is a call site's argument and nothing else: no environment
    variable reaches it.  It exists so that a test can hold these
    rules against a temporary directory it owns instead of writing
    into the committed record of a session.
    """
    if value is None:
        raise TranscriptError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise TranscriptError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise TranscriptError("%s must not be empty" % label)
    if "\x00" in value:
        raise TranscriptError("%s must not contain a NUL byte" % label)
    resolved = os.path.abspath(value)
    if os.path.isdir(resolved):
        raise TranscriptError(
            "%s names a directory, not a file: %s" % (label, resolved))
    try:
        approved = approved_root(root)
    except TimelineError as err:
        raise TranscriptError(str(err)) from err
    canonical = os.path.realpath(resolved)
    if not _within(canonical, approved):
        raise TranscriptError(
            "%s must stay inside %s, but %s resolves to %s"
            % (label, approved, resolved, canonical))
    _refuse_symlink(resolved, approved, label)
    if os.path.exists(resolved) and not os.path.isfile(resolved):
        raise TranscriptError(
            "%s is not a regular file: %s" % (label, resolved))
    _assert_canonical_destination(canonical, resolved, label, approved)
    return resolved


def _assert_canonical_destination(
    canonical: str,
    resolved: str,
    label: str,
    approved: str,
) -> None:
    """Refuse anything but this stage's two exact destinations.

    CONTAINMENT IS NOT ENOUGH, and this is the gap it leaves.  Every
    artifact of this pipeline lives under playthrough/, so a rule that
    only says "inside the approved root" still accepts
    playthrough/manifest.jsonl, playthrough/timeline.json,
    playthrough/dossier.md, playthrough/cata-play.mp4 and anything under
    playthrough/userdir/.  A --srt or --markdown -- or a
    $PLAYTHROUGH_SRT -- naming one of those would write a caption file
    over the session's own evidence: the manifest every count derives
    from, the timeline both this module and render_movie.py read as the
    single source of truth, the survivor's dossier, or the engine's save.
    The write reports success, and the loss surfaces much later as an
    unrelated stage failing to parse something.

    Note that a Markdown destination is the sharpest case of all, because
    playthrough/ holds four other .md files -- dossier.md,
    TECHNICAL_NOTES.md and README.md among them -- so a suffix check
    alone would happily overwrite the survivor's own backstory.

    So the destinations are ENUMERATED rather than merely bounded, from
    the same SRT_NAME and MARKDOWN_NAME constants the defaults are built
    from, so the two cannot drift apart.  $PLAYTHROUGH_SRT and
    $PLAYTHROUGH_MARKDOWN consequently no longer relocate these
    artifacts: they are committed evidence with one place to live, and
    env.sh exports them so every stage AGREES where that is -- not so it
    can be moved.
    """
    permitted = {
        os.path.realpath(os.path.join(approved, SRT_NAME)): SRT_NAME,
        os.path.realpath(os.path.join(approved, MARKDOWN_NAME)):
            MARKDOWN_NAME,
    }
    if canonical in permitted:
        return
    raise TranscriptError(
        "%s resolves to %s, which is not one of this stage's two "
        "destinations.  It writes playthrough/%s and playthrough/%s and "
        "nothing else: every other path under playthrough/ is either a "
        "session's evidence -- the manifest, the timeline, the "
        "survivor's dossier, the save -- or a capture, and a transcript "
        "written over any of them would report success and destroy the "
        "record." % (label, resolved, SRT_NAME, MARKDOWN_NAME))


def _sync_directory(parent: str) -> None:
    """Force a rename in `parent` to the device, tolerating refusal.

    os.replace() is atomic with respect to a reader, but the directory
    entry it creates is not durable until the directory itself is
    synced.  A filesystem that refuses to sync a directory is reported
    rather than allowed to end the run: the data itself is already
    fsynced.
    """
    try:
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as err:
        _warn("could not open %s to sync the rename (%s)"
              % (parent, err))
        return
    try:
        os.fsync(descriptor)
    except OSError as err:
        _warn("could not sync %s after the rename (%s)"
              % (parent, err))
    finally:
        os.close(descriptor)


def write_text(path: str, text: str) -> str:
    """Write `text` to `path` atomically.  Returns the path written.

    UTF-8 with newline="\\n", so the file has LF endings whatever the
    platform and never a byte-order mark: a mark would sit in front of
    the first cue's sequence number and stop it being read as one.

    THE REPLACEMENT IS ATOMIC.  Opening the destination "w" truncates
    it first, so an interruption between the truncation and the last
    byte -- a full disk, a signal, a crash -- would destroy a
    transcript that was complete and leave half of one in its place,
    which is worse than a stale one because the stale one is at least
    internally consistent.  So the text goes to a temporary file in the
    SAME directory, is flushed and fsynced so the bytes are durable,
    and is then moved into place with os.replace(), which either fully
    succeeds or leaves the previous file untouched.  A failed attempt
    removes its temporary file rather than leaving litter beside the
    artifact.
    """
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise TranscriptError(
            "the directory for %s does not exist: %s" % (path, parent))
    descriptor, temporary = tempfile.mkstemp(
        dir=parent, prefix=".transcript-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8",
                       newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates at 0600; both artifacts are committed and
        # read by the caption muxer and by people, so they carry the
        # ordinary file mode a plain open() would have produced.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except OSError:
        # The destination is untouched at this point, so removing the
        # temporary file restores the directory exactly as it was.
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    _sync_directory(parent)
    return path


def write_transcripts(
    srt_text: str,
    markdown_text: str,
    srt_path: Optional[str] = None,
    markdown_path: Optional[str] = None,
    root: Optional[str] = None,
    timeline_path: Optional[str] = None,
) -> Tuple[str, str]:
    """Write both artifacts as ONE RECOVERABLE generation.

    Returns the two paths.

    THE PAIR IS PUBLISHED TOGETHER OR NOT AT ALL, and where that cannot
    be guaranteed it is at least RECOVERABLE.  Both texts are complete
    before this is called, both paths are validated before either file is
    opened, and each individual write is atomic -- but two atomic renames
    are not one atomic pair.  The SRT lands first, so between the two
    os.replace() calls the caption file describes this timeline while the
    Markdown transcript still describes the previous one; and a process
    killed between them used to leave that mismatch on disk permanently,
    with each file internally valid and nothing recording that they
    disagreed.  The module's own docstring claimed a journal made this
    "detectable and finishable".  There was no journal.  There is now.

    Four things close it, in this order:

      * an EXCLUSIVE LOCK -- the same lock the other producers take, in
        the scratch directory outside the tree -- so a concurrent run
        waits for the whole pair rather than interleaving with half of it;
      * both texts are STAGED AND FSYNCED before either is switched in,
        so by the time the first rename happens the second cannot fail
        for any reason a filesystem reports: the bytes are already on the
        device and only two metadata operations remain;
      * a GENERATION JOURNAL, written durably before the first rename,
        naming both targets and the digest each is about to carry.  Its
        presence at startup proves a publication was interrupted and its
        contents say exactly which file should hold what, so the state is
        detectable and this stage -- which is deterministic for a given
        timeline -- finishes it by simply publishing again;
      * a GENERATION MANIFEST at playthrough/build/transcript.json,
        committed beside the artifacts, binding both digests to the
        digest of the timeline they were computed from.  That is what
        lets embed_captions.sh refuse a stale caption file against a
        freshly rendered movie: the two manifests must name the same
        timeline.

    Both records are published before the journal is cleared, and every
    published digest is re-read and checked first.  A publication that
    cannot be verified leaves the journal in place.
    """  # noqa: D401
    srt_target = validated_output_path(
        default_srt_path() if srt_path is None else srt_path,
        "the caption path", root)
    markdown_target = validated_output_path(
        default_markdown_path() if markdown_path is None
        else markdown_path,
        "the transcript path", root)
    if srt_target == markdown_target:
        raise TranscriptError(
            "both artifacts would be written to %s; the captions and "
            "the transcript are two files" % srt_target)
    source = (default_timeline_path() if timeline_path is None
              else timeline_path)
    with ArtifactLock(LOCK_NAME, root):
        # AN INTERRUPTED PREVIOUS RUN IS REPORTED BEFORE THIS ONE
        # PUBLISHES.  It is not an error -- this run is about to replace
        # both files with a consistent pair, which is exactly the repair
        # -- but it must not pass in silence, because a mixed generation
        # may already have been read by a later stage.
        for problem in timeline_module.generation_journal_problems(
                LOCK_NAME, root):
            _warn("a previous transcript publication was interrupted: "
                  "%s.  This run republishes both files from the same "
                  "timeline, which repairs it" % problem)
        staged = []
        try:
            for target, text in ((srt_target, srt_text),
                                 (markdown_target, markdown_text)):
                staged.append((stage_text(target, text), target))
            # ABSOLUTE PATHS IN THE JOURNAL, deliberately: it lives in
            # the private scratch directory outside the tree, it is
            # machinery rather than committed evidence, and recovery has
            # to be able to find the exact file it named without
            # re-deriving a repository root that may not be the one this
            # run had.  The committed MANIFEST is the opposite case and
            # carries repository-relative paths.
            journal = {
                "version": timeline_module.GENERATION_VERSION,
                "stage": LOCK_NAME,
                "timeline": os.path.abspath(source),
                "targets": [
                    {"path": os.path.abspath(target),
                     "sha256": _digest_of_text(text)}
                    for target, text in ((srt_target, srt_text),
                                         (markdown_target,
                                          markdown_text))],
            }
            timeline_module.write_generation_journal(
                LOCK_NAME, journal, root)
            for temporary, target in staged:
                _publish_staged(temporary, target)
            _assert_published(srt_target, srt_text)
            _assert_published(markdown_target, markdown_text)
            write_generation_manifest(
                srt_target, srt_text, markdown_target, markdown_text,
                source, root)
            timeline_module.clear_generation_journal(LOCK_NAME, root)
        finally:
            for temporary, _ in staged:
                if os.path.exists(temporary):
                    try:
                        os.unlink(temporary)
                    except OSError as err:  # pragma: no cover
                        _warn("could not remove the staging file %s (%s)"
                              % (temporary, err))
    return srt_target, markdown_target


def _digest_of_text(text: str) -> str:
    """Return the sha256 of exactly the bytes that will be written."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_published(target: str, text: str) -> None:
    """Confirm `target` now holds exactly `text`.  Raises if not.

    The rename is atomic with respect to a reader, which is not the same
    as being verified: this re-reads the published file and compares its
    digest with the bytes that were staged, so the journal is only
    cleared once the tree demonstrably holds this generation.
    """
    expected = _digest_of_text(text)
    found = timeline_module.file_digest(target)
    if found != expected:
        raise TranscriptError(
            "%s was published but now carries %s rather than the %s "
            "that was staged and verified.  The generation journal is "
            "left in place, so the next run finishes this publication"
            % (relative_to_repo(target), found[:16], expected[:16]))


def generation_manifest_path(root: Optional[str] = None) -> str:
    """Return playthrough/build/transcript.json."""
    return os.path.join(approved_root(root), BUILD_DIR_NAME,
                        GENERATION_MANIFEST_NAME)


def write_generation_manifest(srt_target: str, srt_text: str,
                              markdown_target: str,
                              markdown_text: str,
                              timeline_path: str,
                              root: Optional[str] = None) -> str:
    """Write playthrough/build/transcript.json.  Returns the path.

    THE PROVENANCE THE MUX READS.  It names the timeline these transcripts
    were computed from -- by that document's own digest, not by its path,
    which any two runs share -- and the digest of each file this run
    published.  embed_captions.sh holds the caption file it is about to
    mux against this, and holds this against the movie's own manifest, so
    a caption track from one session cannot be muxed into a film from
    another.  Deterministic: no timestamp, no host, no absolute path.
    """
    target = generation_manifest_path(root)
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as err:
            raise TranscriptError(
                "cannot create %s for the generation manifest: %s"
                % (parent, err)) from err
    record = {
        "version": timeline_module.GENERATION_VERSION,
        "stage": LOCK_NAME,
        "timeline": {
            "path": relative_to_repo(timeline_path),
            "sha256": timeline_module.file_digest(timeline_path),
        },
        "outputs": [
            {"path": relative_to_repo(srt_target),
             "sha256": _digest_of_text(srt_text),
             "bytes": len(srt_text.encode("utf-8"))},
            {"path": relative_to_repo(markdown_target),
             "sha256": _digest_of_text(markdown_text),
             "bytes": len(markdown_text.encode("utf-8"))},
        ],
    }
    text = json.dumps(record, ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"
    temporary = stage_text(target, text)
    _publish_staged(temporary, target)
    return target


def stage_text(target: str, text: str) -> str:
    """Write `text` beside `target` and force it to the device.

    Returns the staging path.  The bytes are durable when this returns,
    which is what lets both artifacts be switched in afterwards with
    nothing left that can fail.
    """
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise TranscriptError(
            "the directory for %s does not exist: %s" % (target, parent))
    descriptor, temporary = tempfile.mkstemp(
        dir=parent, prefix=STAGING_PREFIX, suffix=STAGING_SUFFIX)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8",
                       newline=NEWLINE) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates at 0600; both artifacts are committed and read
        # by players and by people, so they carry the ordinary mode a
        # plain open() would have produced.
        os.chmod(temporary, 0o644)
    except OSError as err:
        try:
            os.unlink(temporary)
        except OSError:  # pragma: no cover - defensive
            pass
        raise TranscriptError(
            "could not stage %s: %s" % (target, err)) from err
    return temporary


def _publish_staged(temporary: str, target: str) -> None:
    """Switch one staged file in for its destination."""
    try:
        os.replace(temporary, target)
    except OSError as err:
        raise TranscriptError(
            "could not publish %s: %s" % (target, err)) from err
    _sync_directory(os.path.dirname(target))


# ---------------------------------------------------------------------
# The command line.  Three paths and two switches, and deliberately
# nothing else: there is no flag that turns the captions into WebVTT,
# no flag that styles or positions them, and no flag that burns them
# into the picture.  The track is a selectable mov_text stream, which
# is a requirement and not a default to be overridden.
# ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(
        prog="make_srt.py",
        description=(
            "Write playthrough/transcript.srt and "
            "playthrough/transcript.md from playthrough/timeline.json "
            "in one pass, so the timestamped in-character record and "
            "the caption cues are the same numbers.  Each cue occupies "
            "its frame's own window in video time, read from the "
            "timeline rather than recomputed, and the captions are "
            "muxed as a selectable track -- never burned into the "
            "picture."))
    parser.add_argument(
        "--timeline", default=None, metavar="PATH",
        help=("the timeline to read; defaults to PLAYTHROUGH_TIMELINE "
              "or <repository>/playthrough/timeline.json"))
    parser.add_argument(
        "--srt", default=None, metavar="PATH",
        help=("the caption file to write; defaults to "
              "PLAYTHROUGH_TRANSCRIPT_SRT or "
              "<repository>/playthrough/transcript.srt"))
    parser.add_argument(
        "--md", default=None, metavar="PATH",
        help=("the transcript to write; defaults to "
              "PLAYTHROUGH_TRANSCRIPT_MD or "
              "<repository>/playthrough/transcript.md"))
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help=("build and check both artifacts and report the counts "
              "without writing either, leaving the committed record "
              "untouched"))
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress the summary line on success")
    return parser


def relative_to_repo(path: str) -> str:
    """Express a path relative to the checkout, for reporting.

    The summary is a machine-readable line that lands in run logs and in
    the report, and an absolute path there discloses the filesystem
    layout of the host -- the home directory, the operator's name, the
    build root -- to every reader of an artifact that says nothing about
    them otherwise.  Repository-relative is exactly the information the
    reader needs and none of the information they do not.
    """
    try:
        checkout = os.path.dirname(approved_root())
    except TimelineError:  # pragma: no cover - defensive
        return os.path.basename(path)
    resolved = os.path.abspath(path)
    if resolved == checkout:
        return "."
    prefix = checkout + os.sep
    if resolved.startswith(prefix):
        return resolved[len(prefix):].replace(os.sep, "/")
    return "<outside the checkout>/%s" % os.path.basename(resolved)


def _report(problems: Sequence[str]) -> None:
    """Print every problem on stderr, one per line."""
    for problem in problems:
        print("make_srt.py: %s" % problem, file=sys.stderr)


def main(
    argv: Optional[Sequence[str]] = None,
    root: Optional[str] = None,
) -> int:
    """Run the command line and return an exit status.

    Zero only when both artifacts were built, every check passed, and
    -- unless --dry-run was given -- both were written.  A run_pipeline
    stage reads nothing but this status, so an exit status that is
    wrong is a whole stage that appears to have worked.

    `root` is a call site's argument and nothing else: argparse never
    produces it, no environment variable reaches it, and the shell
    entry point below never passes one.  It exists so that a test can
    hold the REAL command line against a temporary directory it owns,
    instead of either testing a paraphrase of it or writing into the
    committed artifact tree, which is the captured evidence of a
    session and is not a test fixture.
    """
    args = build_parser().parse_args(argv)
    try:
        source = (default_timeline_path() if args.timeline is None
                  else args.timeline)
        # ONE read.  Through the sibling's own hardened reader, so the
        # document this module renders is the document the renderer
        # reads, held to the same containment and no-symlink rules and
        # opened with O_NOFOLLOW.
        document = read_timeline(source, root)
        # THE CANONICAL GATE, before a single cue is computed.  An
        # object, zero validate_timeline() problems, and a manifest
        # attestation that matches the manifest on disk -- so the cue
        # timings cannot be computed from a document that fails its own
        # invariants or that describes a different session's evidence.
        # The last one is what catches a stale timeline beside a
        # re-recorded manifest, which is the failure no internal
        # invariant can see: a stale document is self-consistent.
        assert_timeline_document(document, root, label="timeline")
        # THE SURVIVOR'S NAME, read from their own dossier before
        # body is rendered.  It is derived rather than spelled here so
        # that the transcript cannot outlive the survivor it names: a
        # re-captured record ships a new dossier, and the title follows
        # it.  A dossier that is missing, unreadable or headingless is a
        # refusal, reported through this function's own error path.
        header = markdown_header(root=root)
        srt_text, markdown_text, cues = build_transcripts(document, header)
        entries = timeline_entries(document)
        summary = summarise(document, entries, cues, markdown_text)

        problems = summary_problems(summary)
        # THE THREE GATES, held BEFORE anything is written and counted
        # among the problems rather than warned about beside them: a
        # transcript that carries an engineering observation, that states
        # something the frames contradict, or whose captions do not fit
        # the cue geometry is not publishable, and the remedy for all
        # three is upstream of this file.  The geometry gate is repeated
        # here rather than left to build_transcripts() alone so that a
        # caller reading main() sees every condition publication depends
        # on in one list.
        problems.extend(voice_problems(cues))
        problems.extend(honesty_problems(cues, entries))
        problems.extend(caption_length_problems(cues))
        if problems:
            _report(problems)
            print("make_srt.py: %d problem(s) found" % len(problems),
                  file=sys.stderr)
            return 1
        if args.dry_run:
            destination = "nothing written"
        else:
            written = write_transcripts(
                srt_text, markdown_text, args.srt, args.md, root,
                timeline_path=source)
            destination = ", ".join(
                relative_to_repo(target) for target in written)
        if not args.quiet:
            print(summary_line(summary, destination))
    except TranscriptError as err:
        print("make_srt.py: %s" % err, file=sys.stderr)
        return 1
    except TimelineError as err:
        print("make_srt.py: %s" % err, file=sys.stderr)
        return 1
    except OSError as err:
        print("make_srt.py: %s" % err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
