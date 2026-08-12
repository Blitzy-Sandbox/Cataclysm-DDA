#!/usr/bin/env python3
"""Materialise the cinematic transition into PNG frames.

Whenever a frame's raw in-game delta ran past the ten-second ceiling,
playthrough/timeline.py sets ``transition_after`` on it and charges one
second of VIDEO time between that frame's window and its successor's.
This module is what fills that second: a fade to black, a card reading
"…time passes…" set in the game's own Terminus face, and a fade back in,
composed with MoviePy and written out as ordinary PNG images.

    . playthrough/tooling/env.sh
    MT='playthrough/tooling/make_transitions.py'
    "$PLAYTHROUGH_PYTHON" -B "$MT"
    "$PLAYTHROUGH_PYTHON" -B "$MT" --timeline PATH

``env.sh`` exports ``PLAYTHROUGH_PYTHON``, the pinned CPython 3.12 that
carries MoviePy and Pillow -- the system ``python3`` carries neither --
and ``-B`` keeps a re-included ``__pycache__`` out of the tree.

WHY IMAGES RATHER THAN VIDEO SEGMENTS
The transition could have been spliced in as a rendered clip, and that
would have forced render_movie.py to concatenate a mixed list of images
and video, cutting and re-encoding at every join.  Materialising it as
images instead keeps the WHOLE movie one ffmpeg concat-demuxer pass over
image entries: no segment cutting, no mixed demuxer list, and no codec
or parameter mismatch to go wrong.  The timeline arithmetic stays
trivially consistent with it, because a transition is then simply more
image entries carrying their own ``duration`` lines.

It is also what makes MoviePy load-bearing rather than decorative.  It
does the fade mathematics and the text composition -- the two things
ffmpeg would need a filter graph for -- and ffmpeg remains the sole
encoder, which sidesteps MoviePy's documented slowness on a long
timeline.

TWELVE FRAMES PER GROUP, EXACTLY
``iter_frames(fps=12)`` over a 1.0 s segment yields twelve frames, and
that count is a contract rather than a detail.  verify_artifacts.sh
counts the groups on disk against the ``transition_after`` flags in the
timeline, and render_movie.py charges exactly TRANSITION seconds of
video per group when it walks the cue cursor.  A thirteenth frame or an
eleventh would desynchronise the captions from the picture, silently and
cumulatively -- correct at the start of the film and further out with
every transition.  So the segment length is read from the timeline
document rather than assumed, and a value other than 1.0 s is refused
instead of quietly producing the wrong number of frames.

CONCATENATION, NEVER COMPOSITION
MoviePy 2.x has a defect under which a cross-fade applied through its
compositing clip class does not render: the composition succeeds, the
frames come out, and the fade is simply absent.  Nothing fails, so
nothing reports it -- the only symptom is a hard cut where a fade was
asked for.  concatenate_videoclips renders the same effects correctly.
That is why this module composes by concatenation and why the
compositing class is not imported at all.  Note what this module does
NOT do about it: it counts its frames and checks their geometry, and a
hard cut would pass both, so nothing here establishes that a fade
rendered.  The pixel-level checks live elsewhere -- capture.sh measures
the grayscale mean and standard deviation of every frame it writes, and
the acceptance gate reads them again from frames pulled back out of the
finished film -- and the claim is left there rather than made here.

EVERY MOVIEPY EXAMPLE OLDER THAN v2 IS WRONG HERE
the v1 ``editor`` submodule no longer exists and the imports come from
``moviepy`` directly; every ``.set_*`` became ``.with_*``; effects are
classes applied through ``with_effects([...])`` rather than methods; and
because v2 replaced ImageMagick with Pillow, ``TextClip``'s ``font``
argument is a FILESYSTEM PATH to a font file.  That last point is why
data/font/Terminus.ttf is handed over directly and why no ImageMagick
font configuration is involved anywhere.

THE CARD IS SET IN THE GAME'S OWN TYPEFACE
data/font/Terminus.ttf is what the engine renders the session in, so the
only non-captured imagery in the film is typographically continuous with
the game rather than looking like an external overlay.  A missing font
file is a hard failure NAMING that path: silently falling back to a
system face would change the look of the film without saying so, and a
transition that does not match the frames around it advertises itself as
an overlay.  No other font is introduced.

THE TRANSITION IS A DECLARED DEVICE, NOT A CAPTURE
These twelve images are the ONLY frames in the movie that no keystroke
produced, and they are never presented as anything else.  They are not a
patch for a capture that went missing, no frame of them is a screenshot,
and none of them may ever be written into playthrough/frames/.

FRAME-DIRECTORY PURITY IS AN INTEGRITY CONSTRAINT
playthrough/frames/ holds exactly one PNG per keystroke and nothing
else, which is what makes the acceptance gate possible at all: the frame
count must equal the manifest's line count.  Mixing derived imagery in
would destroy that identity, so derived frames go to
playthrough/build/transitions/ and this module opens nothing under
playthrough/frames/ for writing.  Every FINAL PNG it produces is
confined to the transitions directory -- no command line flag can change
that, because the output prefix is validated to resolve inside a
directory named build/transitions and refused anywhere else.

Its RUNTIME STATE is a separate question, and the answer is not "the
same directory".  The generation lock lives in the pipeline's scratch
directory OUTSIDE the tree entirely, for the .gitignore reason
LOCK_NAME records.  The staging and retired directories a switch needs
are necessarily inside, because a rename has to stay within one
filesystem and one parent -- so they are dot-prefixed siblings under
playthrough/build/ (STAGING_PREFIX, RETIRED_PREFIX), removed on the way
out, and swept by a later run if a kill prevented that.

IDEMPOTENT AND DETERMINISTIC, BECAUSE THE ARTIFACTS ARE COMMITTED
A re-run composes a COMPLETE generation in a staging directory beside the
destination and switches it in by rename, under a lock, so a timeline
with fewer flags than the last run leaves no stale group behind, an
interrupted run publishes nothing at all, and two concurrent runs
serialise instead of deleting each other's frames.  The group count on
disk therefore always equals the current flag count.  Nothing random and
no timestamp enters an output: the same timeline over the same captures
produces the same bytes, which is what lets the movie be reproduced from
the committed inputs.

WHY EVERY FRAME IS NORMALISED BEFORE IT IS SAVED
``iter_frames`` returns MIXED dtypes -- ``uint8`` for the frames that
pass through untouched and ``float64`` for every frame the fade scaled
-- and ``PIL.Image.fromarray`` raises TypeError on a float64 array
rather than writing a slightly wrong PNG.  Measured on this host under
moviepy 2.2.1 and Pillow 11.3.0.  So each frame is clipped, rounded and
cast to 8-bit RGB explicitly; the alternative is a module that works for
the card and dies on the fade.

Only the declared dependencies are imported -- moviepy, Pillow and numpy
from playthrough/tooling/requirements.txt, the standard library, and the
sibling timeline module for the constants and the read contract it owns.
There is no subprocess, no shell and no network surface of any kind.
"""

import argparse
import errno
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time

try:
    # POSIX only; see decode_limits for what it is used for and
    # for the one limit that is deliberately NOT imposed.
    import resource
except ImportError:            # pragma: no cover - POSIX only
    resource = None            # type: ignore[assignment]

from typing import (Any, Dict, Iterable, List, Mapping, NamedTuple,
                    Optional, Sequence, Set, Tuple)

# Set BEFORE the third-party and sibling imports below.  env.sh exports
# PYTHONDONTWRITEBYTECODE=1, but this module is documented as runnable
# on its own, and a standalone `python3 playthrough/tooling/
# make_transitions.py` without that environment would compile the
# sibling to playthrough/tooling/__pycache__/ -- which .gitignore's
# terminal `!/playthrough/**` negation then makes COMMITTABLE.  A stray
# .pyc in a committed evidence tree is an artifact nobody authored.  The
# flag must precede the import it protects, because the interpreter
# consults it at compile time; every documented command also passes -B.
sys.dont_write_bytecode = True

# numpy and Pillow are hard runtime dependencies: numpy is the array
# representation every MoviePy frame arrives in, and Pillow both writes
# the PNGs and reads the captures' dimensions.  They are imported in a
# guarded breath so that their absence is reported as the missing
# requirements install it is, naming the file that declares them,
# instead of surfacing as a bare ImportError traceback.
try:
    import numpy as np
    NUMPY_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _numpy_import_error:  # pragma: no cover
    np = None  # type: ignore[assignment]
    NUMPY_IMPORT_ERROR = _numpy_import_error

try:
    from PIL import Image
    PILLOW_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _pillow_import_error:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    PILLOW_IMPORT_ERROR = _pillow_import_error

# MoviePy 2.x, imported from the package root.  The v1 `editor`
# submodule was removed in v2, and reaching for it is the single
# commonest way v1-era code fails here, so it is not attempted even as a
# fallback: a v1 install cannot compose this module's effects anyway,
# since vfx.FadeOut and with_effects do not exist there.
try:
    from moviepy import (ImageClip, TextClip, concatenate_videoclips,
                         vfx)
    MOVIEPY_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _moviepy_import_error:  # pragma: no cover
    ImageClip = None  # type: ignore[assignment]
    TextClip = None  # type: ignore[assignment]
    concatenate_videoclips = None  # type: ignore[assignment]
    vfx = None  # type: ignore[assignment]
    MOVIEPY_IMPORT_ERROR = _moviepy_import_error

# The sibling module, imported flat as the repository's own tools/ do.
# It owns FLOOR, CEIL and TRANSITION and the read contract for
# playthrough/timeline.json, and reusing them is what keeps this module
# from becoming a second opinion about either.
try:
    import timeline
except ImportError:  # pragma: no cover - flat sibling, as tools/ does
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import timeline


# ---------------------------------------------------------------------
# The composition, in numbers
#
# The three sub-clip lengths sum to the transition second, and that is
# asserted rather than trusted: FADE + CARD + FADE must equal the
# TRANSITION the timeline charged, or the group would occupy a different
# stretch of video than the cue cursor reserved for it.
# ---------------------------------------------------------------------

# Frames per second the segment is sampled at.  FPS * TRANSITION is the
# group size, so twelve frames over one second.
FPS = 12

# The fade at each end and the card between them.  0.4 + 0.2 + 0.4.
FADE_SECONDS = 0.4
CARD_SECONDS = 0.2

# The only transition length this module can materialise.  Read from the
# timeline document and checked against this, because twelve frames at
# twelve frames per second IS one second and nothing else.
EXPECTED_TRANSITION = 1.0

# The group size that follows from the two above.  Named so that the
# assertion reads as arithmetic instead of as a magic number.
FRAMES_PER_GROUP = int(round(FPS * EXPECTED_TRANSITION))

# The card's text, in-world and unadorned.  The ellipses are U+2026
# HORIZONTAL ELLIPSIS characters, not three full stops -- the same
# character the engine's own interface uses.  Nothing about the
# machinery appears on screen: no frame number, no duration, no elapsed
# game time.  The reader of the film is a survivor's audience, not an
# operator reading a progress bar.
CARD_TEXT = "…time passes…"

CARD_FONT_SIZE = 48
CARD_COLOR = "white"
CARD_BG_COLOR = "black"

# The captured resolution, and the resolution the encoder is told to
# write.  The X root is exactly 1920x1080 while the game WINDOW is
# 1920x1072 at +0+4 -- WindowWidth/WindowHeight are derived from the
# terminal grid and the font cell (src/sdltiles.cpp:595-596) under a
# FULLSCREEN default of "windowedbl" (src/options.cpp:2715-2724) -- and
# capture.sh photographs the root.  So a transition frame matches the
# ROOT, not the window: 1920x1080, with the same four-pixel letterbox
# the captures carry.
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

# ---------------------------------------------------------------------
# Paths.  Every one is joined from module-level literal components onto
# a directory that has already been validated, and a path arriving from
# the timeline, the environment or the command line is resolved and
# proved to be inside the tree it belongs to before it is opened.  That
# keeps this module clear of the unvalidated-path-join pattern the
# repository's CodeQL python leg gates on
# [.github/workflows/codeql-analysis.yml:35].
# ---------------------------------------------------------------------

# The game's own typeface.  Spelled as one repository-relative literal
# because that is what the requirement names, and split into components
# for joining so no separator assumption leaks into a path.
FONT_REL_PATH = "data/font/Terminus.ttf"
FONT_REL_PARTS = tuple(FONT_REL_PATH.split("/"))

# The two markers that prove a directory is this checkout, matching
# sidebar_geometry.repo_root()'s pair so that both modules agree on what
# a Cataclysm-DDA root is.
ROOT_MARKER_DIR_PARTS = ("data", "json", "ui")
ROOT_MARKER_FILE_PARTS = ("src", "path_info.cpp")

# Where the captures are read from and where the derived frames are
# written to.  They are different directories on purpose; see
# FRAME-DIRECTORY PURITY in the module docstring.
FRAMES_DIR_NAME = "frames"
FRAMES_REL_DIR = "playthrough/frames"
TRANSITIONS_REL_PARTS = ("build", "transitions")
TRANSITIONS_REL_DIR = "playthrough/build/transitions"

# The output name, and the prefix the group index is appended to.  The
# five-digit field is the frame the transition FOLLOWS and the two-digit
# field is the index within the group, so a lexical sort of the
# directory is also the chronological order -- which is what lets
# render_movie.py build a correct concat list by globbing.
TRANSITION_STEM_FORMAT = "trans_%05d"
TRANSITION_SUFFIX_FORMAT = "_%02d.png"
TRANSITION_NAME_FORMAT = TRANSITION_STEM_FORMAT + TRANSITION_SUFFIX_FORMAT

# Anything matching this in the transitions directory is a product of
# this module.  Anchored, so a file somebody else put there is reported
# rather than counted as a composed frame -- and, because a generation
# is published by renaming a whole directory into place, is never
# deleted through this pattern either.
TRANSITION_NAME_RE = re.compile(r"^trans_[0-9]{5}_[0-9]{2}\.png$")

# A looser shape used only to notice a stray file that WOULD be picked
# up by verify_artifacts.sh's `trans_*.png` glob without being a frame
# this module wrote.
TRANSITION_GLOB_PREFIX = "trans_"
PNG_SUFFIX = ".png"

# ---------------------------------------------------------------------
# THE GENERATION MANIFEST
#
# THE DEFECT IT EXISTS FOR.  A published group set had no provenance
# whatsoever.  render_movie.py accepted a group because twelve files with
# the right NAMES and the right PIXEL DIMENSIONS existed for each flagged
# index -- and a name and a size are not evidence.  Three failures walked
# straight through that:
#
#   * A group composed from a DIFFERENT timeline.  Frame 42 is flagged in
#     both, both runs write trans_00042_00..11.png, both sets are 1920 by
#     1080, and the film silently fades between two captures from a
#     session that is not the one being rendered.
#   * A group left behind for an index that is NO LONGER FLAGGED.  The
#     per-entry check only ever looked at the indices the current timeline
#     flags, so a stale group for an index the recomputed timeline dropped
#     was never even inspected -- while verify_artifacts.sh, which globs
#     the whole directory, counts it.
#   * A frame whose CONTENT changed after it was composed.  Same name,
#     same geometry, different pixels.
#
# So this module publishes a provenance record binding the groups to the
# timeline by that document's own digest, to the captures they were faded
# between by theirs, to the card's typeface, and to its own output bytes.
# render_movie.py REQUIRES it and checks the group index set GLOBALLY
# against the flags -- so an extra group is a refusal, not an omission.
#
# WHERE IT LIVES, AND WHY IT MOVED.  It was written INSIDE the group set,
# so that the same atomic rename published both.  Code review found that
# to break the transitions directory's own schema, which admits
# `trans_*.png` and nothing else: the acceptance gate globs that
# directory, the AAP lists only PNGs in it, and a tracked JSON file
# sitting among them is a surplus entry.  The record now lives beside the
# film's and the transcripts' own, at playthrough/build/transitions.json,
# and the directory holds nothing but transition frames.
#
# THE PAIR IS STILL PUBLISHED AS ONE GENERATION.  Two artifacts that only
# mean anything together must not be able to disagree, which is the whole
# reason the manifest was put inside the directory in the first place --
# so the move does not simply give that up.  The switch and the record
# are published under the generation JOURNAL timeline.py owns and
# make_srt.py already uses: the journal names both targets and their
# digests before the first rename, an interruption between them is
# reported by the next run and repaired by republishing, and render_movie
# refuses a group set whose record does not describe it.  Fail loud and
# recoverable, rather than silently mixed.
#
# The legacy in-directory name is recognised as this module's OWN litter,
# so a directory published by an older version is cleaned rather than
# carried across the switch.
#
# Deterministic by construction: no timestamp, no host name, no absolute
# path.  Two runs over one timeline produce byte-identical manifests, so a
# committed tree does not churn.
# ---------------------------------------------------------------------
GENERATION_MANIFEST_NAME = "transitions.json"
LEGACY_MANIFEST_NAME = "generation.json"

# The eight-byte PNG signature [RFC 2083 section 3.1].  Every image this
# module reads must begin with it, checked before any decoder is
# reached: Pillow identifies a format by CONTENT, so without this a
# crafted PSD, DDS or TIFF named .png would be parsed as that format.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# A hard ceiling on the pixels a capture may DECLARE, so a malformed or
# crafted header cannot ask for an unbounded allocation.  The root
# window these captures photograph is 1920x1080 = 2 073 600 pixels, so
# 64 megapixels is generous by a factor of thirty.
MAX_PIXELS = 64 * 1024 * 1024

# A hard ceiling on the BYTES one capture may occupy, asked before the
# file is read into memory at all.  read_verified_frame() reads the whole
# of a frame it has validated -- that is the point of it -- so a planted
# enormous file would otherwise be slurped in before anything looked at
# its header.  DELIBERATELY THE SAME VALUE ocr_clock.py uses, for the
# same reason the CPU cap below is, and asserted to be by
# test_make_transitions.py.
MAX_FRAME_BYTES = 64 * 1024 * 1024

# The CPU budget, in seconds, granted to one composition.
#
# DELIBERATELY THE SAME VALUE ocr_clock.py uses, and asserted to
# be by test_make_transitions.py.  The two modules each own their
# own decode door -- they are standalone scripts and neither
# imports the other -- so the caps are stated twice, and the
# agreement between them is a CHECKED property rather than a
# convention somebody has to remember.  A copied constant that
# nothing compares is a second definition waiting to drift.
DECODE_CPU_SECONDS = 30

# The sha256 of data/font/Terminus.ttf as this repository ships it.
#
# A FONT IS PARSED INPUT.  FreeType is a native parser reached through
# Pillow, and the face is named by a path joined onto a checkout root --
# so "the font we expect" is an ASSUMPTION until the bytes are hashed.
# An attacker who can place a file at data/font/Terminus.ttf gets the
# native parser, and the card is composed on every run.
#
# This is deliberately the same value as ocr_clock.GLYPH_FONT_SHA256 and
# is declared here rather than imported, because importing that module
# would make pytesseract a hard dependency of composing a transition
# (the same reason timeline.py restates its own field names).  The test
# suite asserts the two constants are equal, so they cannot drift.
FONT_SHA256 = (
    "e0d645677fa32557a16b3be8533c552c2939fd507d7b8515ead5d9cf494cb2a6")

# Read the font in blocks rather than whole.
DIGEST_BLOCK = 65536

# The group index is ZERO-BASED: for any capture N the timeline flags
# with transition_after, the group runs trans_NNNNN_00.png through
# trans_NNNNN_11.png -- so capture 1 yields trans_00001_00.png only if
# capture 1 is itself flagged.  A capture the timeline does not flag has
# no group and therefore no file at all, and that absence is correct:
# composing one to fill an apparent gap would put imagery in the film
# that no timeline entry asked for.  Zero-based is chosen once and
# applied everywhere, because the second field is an offset within the
# group rather than a count of anything.
FIRST_GROUP_INDEX = 0

# The frame index field is five digits wide, so the capture it names has
# to fit in it.  The bounds match manifest.py's own frame index range.
MIN_FRAME_INDEX = 1
MAX_FRAME_INDEX = 99999

# Environment variables, all exported by playthrough/tooling/env.sh,
# which is the single definition of the artifact layout.
ENV_REPO_ROOT = "PLAYTHROUGH_REPO_ROOT"
ENV_TRANSITIONS_DIR = "PLAYTHROUGH_TRANSITIONS_DIR"
ENV_TRANSITION_FORMAT = "PLAYTHROUGH_TRANSITION_FORMAT"
ENV_FRAMES_DIR = "PLAYTHROUGH_FRAMES_DIR"
ENV_SCREEN_WIDTH = "PLAYTHROUGH_SCREEN_WIDTH"
ENV_SCREEN_HEIGHT = "PLAYTHROUGH_SCREEN_HEIGHT"

# The timeline keys this module reads.  It needs four of the eighteen
# fields timeline.ENTRY_FIELDS declares, and naming them here keeps the
# dependency visible.
KEY_FRAMES = "frames"
KEY_FRAME = "frame"
KEY_FILE = "file"
KEY_TRANSITION_AFTER = "transition_after"
KEY_TRANSITION = "transition"

# Exit statuses.  0 is success, 1 is every refusal this module makes.
# argparse exits 2 on a command line error of its own accord.
EXIT_OK = 0
EXIT_FAILED = 1


class TransitionError(Exception):
    """The transition cannot be composed or written honestly.

    Raised in place of producing imagery that would misrepresent the
    session -- a group of the wrong length, a frame of the wrong size, a
    card in a font the game does not use, or a write aimed anywhere
    other than the transitions directory.  Every one of those would
    still yield a playable movie, which is exactly why each is an
    exception rather than a warning.
    """


def _warn(message: str) -> None:
    """Report a non-fatal problem on stderr and carry on.

    The prefix matches playthrough_warn() in
    playthrough/tooling/env.sh and the sibling modules' own reporting,
    so every stage of the pipeline is recognisable in one session log.
    """
    print("playthrough: WARNING: make_transitions.py: %s" % message,
          file=sys.stderr, flush=True)


class Group(NamedTuple):
    """One transition group, resolved and ready to compose.

    `frame` is the capture the transition FOLLOWS and names the output
    files.  `current` is the frame being faded out of and `successor`
    the frame being faded in to, both absolute and already proved to be
    captures inside playthrough/frames/.

    There is no self-successor state: a flagged FINAL entry has no frame
    to fade into, and plan_groups() REFUSES such a timeline rather than
    fabricating a fade from the last capture back into itself.
    """

    frame: int
    current: str
    successor: str


# ---------------------------------------------------------------------
# Dependency checks.  Each is asked at the point of first use and names
# the requirements file, because "ModuleNotFoundError: No module named
# 'moviepy'" tells an operator nothing about which environment to
# install into.
# ---------------------------------------------------------------------

def _require_numpy() -> None:
    """Refuse to continue without numpy, naming the declaration."""
    if NUMPY_IMPORT_ERROR is not None:
        raise TransitionError(
            "numpy is required to normalise a composed frame but could "
            "not be imported (%s).  Install the pipeline's declared "
            "dependencies: playthrough/tooling/requirements.txt pins "
            "numpy, and playthrough/tooling/requirements.lock is the "
            "hash-locked install contract."
            % NUMPY_IMPORT_ERROR)


def _require_pillow() -> None:
    """Refuse to continue without Pillow, naming the declaration."""
    if PILLOW_IMPORT_ERROR is not None:
        raise TransitionError(
            "Pillow is required to write a transition frame but could "
            "not be imported (%s).  Install the pipeline's declared "
            "dependencies: playthrough/tooling/requirements.txt pins "
            "pillow, and playthrough/tooling/requirements.lock is the "
            "hash-locked install contract."
            % PILLOW_IMPORT_ERROR)


def _require_moviepy() -> None:
    """Refuse to continue without MoviePy 2.x, naming the declaration.

    A v1 install fails here rather than later: the v1 `editor` submodule
    is gone in v2 and this module never reaches for it, so an ImportError
    of the package root is what a v1-only environment produces, and the
    diagnostic says which version is wanted.
    """
    if MOVIEPY_IMPORT_ERROR is not None:
        raise TransitionError(
            "MoviePy is required to compose the transition but could "
            "not be imported from the package root (%s).  This module "
            "needs MoviePy 2.x -- ImageClip, TextClip, "
            "concatenate_videoclips and vfx are imported from `moviepy` "
            "directly, because the v1 `editor` submodule was removed "
            "in v2.  "
            "playthrough/tooling/requirements.txt pins moviepy==2.2.1."
            % MOVIEPY_IMPORT_ERROR)
    for name in ("FadeIn", "FadeOut"):
        if not hasattr(vfx, name):
            raise TransitionError(
                "the installed MoviePy has no vfx.%s, so it is not the "
                "2.x release this module composes against.  Effects "
                "are classes applied through with_effects([...]) in v2; "
                "a v1 install offers fadein()/fadeout() methods "
                "instead and "
                "cannot produce this transition.  "
                "playthrough/tooling/requirements.txt pins "
                "moviepy==2.2.1." % name)


# ---------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------

def _join(base: str, parts: Sequence[str]) -> str:
    """Join literal path components onto a base directory."""
    return os.path.normpath(os.path.join(base, *parts))


def _module_dir() -> str:
    """Return the absolute directory holding this module."""
    return os.path.abspath(os.path.dirname(__file__))


def _playthrough_dir() -> str:
    """Return the absolute playthrough/ directory.

    Derived from this module's own location rather than from the working
    directory, exactly as manifest.py and timeline.py derive it, so the
    module is correct however it was invoked.
    """
    return os.path.dirname(_module_dir())


def _looks_like_checkout(candidate: str) -> bool:
    """True when `candidate` holds this repository's marker paths."""
    return (os.path.isdir(_join(candidate, ROOT_MARKER_DIR_PARTS)) and
            os.path.isfile(_join(candidate, ROOT_MARKER_FILE_PARTS)))


def repo_root(explicit: Optional[str] = None) -> str:
    """Return the absolute repository root, verified to be one.

    Resolution order, matching sidebar_geometry.repo_root():

    1. `explicit`, when a caller passes one;
    2. ``$PLAYTHROUGH_REPO_ROOT`` from playthrough/tooling/env.sh, so
       every stage of the pipeline agrees on the root;
    3. two directories above this file, which is the idiom
       tools/json_tools/util.py:13-16 uses.

    A NOMINATED ROOT THAT IS NOT A CHECKOUT IS FATAL, not skipped.
    Steps 1 and 2 are instructions: somebody said which checkout to
    read.  Falling through to this module's own would answer a question
    nobody asked -- and it would find a different data/font/Terminus.ttf
    or none at all, which is a card in the wrong typeface rather than an
    error anyone would notice.
    """
    nominated: List[Tuple[str, str]] = []
    if explicit:
        nominated.append(("the explicit root argument", explicit))
    from_env = os.environ.get(ENV_REPO_ROOT)
    if from_env and from_env.strip():
        nominated.append(("$" + ENV_REPO_ROOT, from_env))

    marker_dir = os.path.join(*ROOT_MARKER_DIR_PARTS)
    marker_file = os.path.join(*ROOT_MARKER_FILE_PARTS)
    for origin, candidate in nominated:
        resolved = os.path.abspath(os.path.normpath(candidate))
        if _looks_like_checkout(resolved):
            return resolved
        raise TransitionError(
            "%s names '%s' (resolved to '%s'), which is not a "
            "Cataclysm-DDA checkout: it has no %s directory or no %s "
            "file.  That root was asked for explicitly, so it is not "
            "silently replaced with this module's own -- which would "
            "set the card in a different %s."
            % (origin, candidate, resolved, marker_dir, marker_file,
               FONT_REL_PATH))

    derived = os.path.dirname(_playthrough_dir())
    if _looks_like_checkout(derived):
        return derived
    raise TransitionError(
        "cannot locate a Cataclysm-DDA checkout (no %s directory and "
        "no %s file); this module resolves to '%s' from its own "
        "location, and no root was nominated by an argument or $%s"
        % (marker_dir, marker_file, derived, ENV_REPO_ROOT))


def font_path(repo_root_dir: Optional[str] = None) -> str:
    """Return the game's Terminus face, proved to be readable.

    The path is joined from literal components onto a verified checkout
    root, so nothing user-supplied is concatenated into it.  Absence is
    a hard failure NAMING data/font/Terminus.ttf, because the documented
    alternative -- letting Pillow pick a default face -- would change
    the look of the film silently and make the transition read as an
    external overlay rather than as part of the game.
    """
    resolved = _join(repo_root(repo_root_dir), FONT_REL_PARTS)
    if not os.path.exists(resolved):
        raise TransitionError(
            "the transition card is set in the game's own typeface and "
            "%s is missing (looked for %s).  This is refused rather "
            "than falling back to a system font: the card would then "
            "no longer match the frames around it, and the only symptom "
            "would be a film that looks slightly wrong."
            % (FONT_REL_PATH, resolved))
    # lstat, not stat: a symlink at this path is refused rather than
    # followed, because what FreeType would then parse is whatever the
    # link points at and no check here would have seen it.
    try:
        info = os.lstat(resolved)
    except OSError as err:
        raise TransitionError(
            "%s cannot be inspected: %s" % (FONT_REL_PATH, err)) from err
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise TransitionError(
            "%s is not a regular file: %s.  A font is native parser "
            "input, so the file behind that name is refused unless it "
            "is the one this repository ships"
            % (FONT_REL_PATH, resolved))
    if not os.access(resolved, os.R_OK):
        raise TransitionError(
            "%s is not readable: %s" % (FONT_REL_PATH, resolved))
    observed = font_digest(resolved)
    if observed != FONT_SHA256:
        raise TransitionError(
            "%s has sha256 %s, but this pipeline is written against "
            "%s -- the data/font/Terminus.ttf this repository ships.  "
            "The face is parsed by FreeType through Pillow on every "
            "run, so one that is not the attested face is refused "
            "rather than parsed.  If the font was legitimately updated "
            "upstream, update FONT_SHA256 in this module deliberately "
            "and re-verify the card's appearance"
            % (FONT_REL_PATH, observed, FONT_SHA256))
    return resolved


def font_digest(path: str) -> str:
    """Return the sha256 of a font file's exact bytes, in hex."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(DIGEST_BLOCK), b""):
                digest.update(block)
    except OSError as err:
        raise TransitionError(
            "cannot read %s to attest it: %s" % (path, err)) from err
    return digest.hexdigest()


def _approved_root(root: Optional[str] = None) -> str:
    """Return the only tree this module may read captures from or write.

    Delegated to timeline.approved_root() rather than reimplemented, so
    the renderer, the caption generator and this module cannot end up
    with three opinions about where an artifact is allowed to live.  It
    resolves to playthrough/ from the module's own location and NEVER
    from the environment; `root` is a call site's argument so a test can
    hold the same rules against a directory it owns.
    """
    try:
        return timeline.approved_root(root)
    except timeline.TimelineError as err:
        raise TransitionError(str(err)) from err


def _resolved(path: str) -> str:
    """Return `path` absolute and fully symlink-resolved."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def _within(path: str, root: str) -> bool:
    """Return True when `path` is `root` itself or lies beneath it.

    Both sides are expected to be fully resolved already, so a `..`
    segment or a symlink cannot smuggle a path past the test.  Spelled
    out here rather than borrowed from a sibling's internals, because a
    containment rule this module's integrity rests on should be readable
    in the module that rests on it.
    """
    return path == root or path.startswith(root + os.sep)


def _validated_directory(value: Any, label: str) -> str:
    """Return `value` as an absolute directory path, or raise.

    Shape only: a non-empty string or os.PathLike with no NUL byte.
    Containment is a separate question and is asked separately, because
    a well-formed path pointing somewhere it may not go needs a
    different diagnostic from a malformed one.
    """
    if value is None:
        raise TransitionError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise TransitionError(
            "%s must be a string path, got %s"
            % (label, type(value).__name__))
    if not value.strip():
        raise TransitionError("%s must not be empty" % label)
    if "\x00" in value:
        raise TransitionError(
            "%s must not contain a NUL byte" % label)
    return _resolved(value)


def frames_dir(root: Optional[str] = None) -> str:
    """Return the capture directory this module READS from.

    ``$PLAYTHROUGH_FRAMES_DIR`` from playthrough/tooling/env.sh wins so
    that a clone-indexed run and this module agree; otherwise the
    sibling `frames` directory of the approved root.  Either way the
    result is proved to be inside the approved root, because a capture
    read from outside the tree would put imagery in the film that the
    session's own evidence does not account for.
    """
    approved = _approved_root(root)
    from_env = os.environ.get(ENV_FRAMES_DIR)
    if from_env and from_env.strip():
        resolved = _validated_directory(
            from_env, "$" + ENV_FRAMES_DIR)
    else:
        resolved = _resolved(_join(approved, (FRAMES_DIR_NAME,)))
    if not _within(resolved, approved):
        raise TransitionError(
            "the capture directory must stay inside %s, but %s "
            "resolves to %s" % (approved, from_env, resolved))
    return resolved


def default_transitions_dir(root: Optional[str] = None) -> str:
    """Return the directory the derived frames are WRITTEN to.

    ``$PLAYTHROUGH_TRANSITIONS_DIR`` from playthrough/tooling/env.sh
    wins, and is then held to two rules that are not negotiable: it must
    resolve inside the approved root, and it must not resolve into the
    capture directory.  The second rule is the one that matters most --
    playthrough/frames/ holds exactly one PNG per keystroke, and a
    single derived frame landing there would break the frame-count
    equals manifest-line-count identity that the whole
    one-frame-per-keystroke gate rests on.  So the environment can move
    this directory around inside the tree, and cannot aim it at the
    captures.
    """
    approved = _approved_root(root)
    from_env = os.environ.get(ENV_TRANSITIONS_DIR)
    if from_env and from_env.strip():
        resolved = _validated_directory(
            from_env, "$" + ENV_TRANSITIONS_DIR)
        origin = "$" + ENV_TRANSITIONS_DIR
    else:
        resolved = _resolved(_join(approved, TRANSITIONS_REL_PARTS))
        origin = "the approved root"
    if not _within(resolved, approved):
        raise TransitionError(
            "%s names %s, which is outside %s; derived frames belong "
            "in %s inside the working tree, where they are committed "
            "with everything else"
            % (origin, resolved, approved, TRANSITIONS_REL_DIR))
    captures = frames_dir(root)
    if _within(resolved, captures):
        raise TransitionError(
            "%s names %s, which is inside the capture directory %s.  "
            "Refused: %s holds exactly one PNG per keystroke and "
            "nothing else, and a derived frame there would break the "
            "frame-count equals manifest-line-count identity the "
            "one-frame-per-keystroke gate rests on.  Derived frames go "
            "to %s."
            % (origin, resolved, captures, FRAMES_REL_DIR,
               TRANSITIONS_REL_DIR))
    return resolved


def _assert_output_directory(directory: str, root: str) -> None:
    """Refuse an output directory that is not a transitions directory.

    Three properties, each closing a different way a write could land
    somewhere it must not: the directory resolves inside the approved
    root, its trailing components are literally build/transitions, and
    it is not the capture directory or anything under it.  The middle
    check is deliberately about the NAME -- it is what makes "this
    module only ever writes into build/transitions" a property a reader
    can verify by inspection rather than a claim to be trusted.
    """
    if not _within(directory, root):
        raise TransitionError(
            "the output directory must stay inside %s, but it resolves "
            "to %s" % (root, directory))
    tail = os.path.join(*TRANSITIONS_REL_PARTS)
    # Two acceptable shapes, and only two: the published destination, and
    # a staging sibling BESIDE it that is only ever renamed onto it.  The
    # staging form has to be admitted by name here, because a generation
    # is composed complete before it is switched in (see
    # _publish_generation) -- and admitting it by name rather than by
    # relaxing the rule keeps "this module only ever writes into
    # build/transitions, or into something that becomes it" a property a
    # reader can verify by inspection.
    parent, leaf = os.path.split(directory)
    staged = bool(
        os.path.basename(parent) == TRANSITIONS_REL_PARTS[0] and
        leaf.startswith(STAGING_PREFIX))
    if not directory.endswith(os.sep + tail) and not staged:
        raise TransitionError(
            "the output directory must end with %s, but it resolves to "
            "%s.  Derived transition frames live in %s and nowhere "
            "else; nothing this module writes may land beside the "
            "captures." % (tail, directory, TRANSITIONS_REL_DIR))
    captures = _resolved(_join(root, (FRAMES_DIR_NAME,)))
    if _within(directory, captures):
        raise TransitionError(
            "the output directory %s is inside the capture directory "
            "%s, which holds exactly one PNG per keystroke and nothing "
            "else" % (directory, captures))


def validated_output_prefix(
    out_prefix: Any,
    root: Optional[str] = None,
) -> str:
    """Return an absolute output stem this module may write under.

    A prefix is a path stem, not a directory: `.../trans_00042` becomes
    `.../trans_00042_00.png` through `.../trans_00042_11.png`.  The stem
    is checked for shape and its DIRECTORY is checked by
    :func:`_assert_output_directory`, so the public composing entry
    point is held to the same containment rules as a whole run and
    cannot be used to slip a frame into playthrough/frames/.
    """
    resolved = _validated_directory(out_prefix, "the output prefix")
    if os.path.isdir(resolved):
        raise TransitionError(
            "the output prefix names a directory, not a file stem: %s.  "
            "A prefix has %s appended to it, so %s would be created "
            "inside itself."
            % (resolved, TRANSITION_SUFFIX_FORMAT, resolved))
    stem = os.path.basename(resolved)
    if not stem.startswith(TRANSITION_GLOB_PREFIX):
        raise TransitionError(
            "the output prefix must be named %s..., because "
            "verify_artifacts.sh and render_movie.py both find these "
            "frames by that name; got '%s'"
            % (TRANSITION_GLOB_PREFIX, stem))
    _assert_output_directory(
        os.path.dirname(resolved), _approved_root(root))
    return resolved


def _validated_image_path(
    value: Any,
    label: str,
    root: Optional[str] = None,
) -> str:
    """Return an absolute, readable PNG path, or raise.

    Shape, then form, then existence: a non-empty string or os.PathLike
    with no NUL byte, naming a .png, that is there and is a regular
    file.  A RELATIVE value is resolved against the CHECKOUT ROOT rather
    than the working directory, which is both what the timeline's own
    "playthrough/frames/frame_00001.png" means and what keeps this
    module correct however it was invoked.

    A missing frame is a hard failure and never a skipped group.  The
    frame it names is one the session actually took; if it is gone, the
    transition cannot honestly fade out of it, and composing something
    else in its place would be a fabrication.
    """
    if value is None:
        raise TransitionError("%s is required" % label)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise TransitionError(
            "%s must be text, got %s" % (label, type(value).__name__))
    if not value.strip():
        raise TransitionError("%s must not be empty" % label)
    if "\x00" in value:
        raise TransitionError("%s must not contain a NUL byte" % label)

    if os.path.isabs(value):
        resolved = _resolved(value)
    else:
        resolved = _resolved(
            os.path.join(os.path.dirname(_approved_root(root)), value))
    if not resolved.lower().endswith(PNG_SUFFIX):
        raise TransitionError(
            "%s does not name a %s: %s.  Capture writes one PNG per "
            "keystroke and this module reads nothing else"
            % (label, PNG_SUFFIX, resolved))
    if not os.path.exists(resolved):
        raise TransitionError(
            "%s names a frame that is not there: %s.  The transition "
            "fades out of a frame that was actually taken, so this is "
            "refused rather than composed from something else."
            % (label, resolved))
    if not os.path.isfile(resolved):
        raise TransitionError(
            "%s is not a regular file: %s" % (label, resolved))
    return resolved


def validated_capture_path(
    value: Any,
    label: str,
    root: Optional[str] = None,
    captures: Optional[str] = None,
) -> str:
    """Return an absolute capture path from playthrough/frames/.

    The value arrives from playthrough/timeline.json -- which is to say
    from outside this module -- so it is resolved and then PROVED to lie
    inside the capture directory rather than joined and opened.  An
    absolute path, a `..` segment and a symlink aiming out of the tree
    are all caught by testing the resolved form, which is what keeps a
    timeline-derived path from reaching open() unvalidated.
    """
    resolved = _validated_image_path(value, label, root)
    directory = captures if captures else frames_dir(root)
    if not _within(resolved, directory):
        raise TransitionError(
            "%s resolves to %s, which is outside the capture directory "
            "%s.  A frame in the film has to be a frame of this "
            "session." % (label, resolved, directory))
    return resolved


# ---------------------------------------------------------------------
# The timeline is the single source of truth, and this module is one of
# its three readers.  It takes four fields and computes nothing of its
# own: the flag says whether a transition is owed, and the segment
# length says how long it is.
# ---------------------------------------------------------------------

def timeline_entries(document: Any) -> List[Dict[str, Any]]:
    """Return the frames array of a timeline document.

    A BARE ARRAY IS REFUSED, and the reason is worth stating because
    accepting one used to look harmless.  timeline.validate_timeline()
    -- the canonical check on the clamp bounds, the transition rule, the
    contiguity of the cue windows and the manifest attestation -- begins
    by requiring an OBJECT and returns immediately for anything else.
    So a caller that handed this module a list of entries skipped every
    document-level invariant there is: there were no totals to check the
    entries against, no constants to prove the clamp under, and no
    provenance naming the evidence the durations came from.  A
    hand-written list of durations could then compose the film's
    transitions with nothing anywhere objecting.

    The object is required instead, so that the one validator applies.
    """
    if not isinstance(document, dict):
        raise TransitionError(
            "the timeline is a %s, not an object with a '%s' array.  A "
            "bare array skips timeline.validate_timeline() entirely -- "
            "the clamp bounds, the totals, the constants and the "
            "manifest attestation all go unchecked -- so it is refused "
            "rather than composed from"
            % (type(document).__name__, KEY_FRAMES))
    entries = document.get(KEY_FRAMES)
    if entries is None:
        raise TransitionError(
            "the timeline document has no '%s' array; "
            "timeline.DOCUMENT_FIELDS declares it and timeline.py "
            "always writes it" % KEY_FRAMES)
    if not isinstance(entries, list):
        raise TransitionError(
            "the timeline's '%s' must be an array, got %s"
            % (KEY_FRAMES, type(entries).__name__))
    rows: List[Dict[str, Any]] = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise TransitionError(
                "timeline entry %d is not an object, got %s"
                % (position, type(entry).__name__))
        rows.append(entry)
    return rows


def transition_seconds(document: Any) -> float:
    """Return the segment length the timeline charged, checked.

    The value is READ from the document rather than assumed, so the two
    stages cannot hold different opinions about how long a transition
    is -- and then it is checked against EXPECTED_TRANSITION, because
    FRAMES_PER_GROUP frames at FPS frames per second is that length and
    no other.  A mismatch means the timeline was computed under
    different constants than this module can materialise, which would
    put the picture and the captions permanently out of step, so it
    fails here rather than rendering.
    """
    if isinstance(document, dict) and KEY_TRANSITION in document:
        value = document[KEY_TRANSITION]
        origin = "the timeline's '%s'" % KEY_TRANSITION
    else:
        # A bare array carries no constants; timeline.py owns them.
        value = timeline.TRANSITION
        origin = "timeline.TRANSITION"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransitionError(
            "%s must be a number, got %s"
            % (origin, type(value).__name__))
    seconds = float(value)
    if seconds != EXPECTED_TRANSITION:
        raise TransitionError(
            "%s is %r, but this module materialises a %ss transition as "
            "%d frames at %d fps and can produce no other length.  "
            "render_movie.py charges %ss of video per group and "
            "make_srt.py walks the same cursor, so a different length "
            "would desynchronise the captions from the picture -- "
            "correct at the start of the film and further out with "
            "every transition."
            % (origin, value, EXPECTED_TRANSITION, FRAMES_PER_GROUP,
               FPS, EXPECTED_TRANSITION))
    if FADE_SECONDS * 2 + CARD_SECONDS != seconds:
        raise TransitionError(
            "the composition does not fill the transition: %s + %s + "
            "%s is not %s"
            % (FADE_SECONDS, CARD_SECONDS, FADE_SECONDS, seconds))
    return seconds


def _entry_frame_index(entry: Dict[str, Any], position: int) -> int:
    """Return an entry's capture index, checked against the name width.

    The index is what names the output files through a five-digit field,
    so a value that would not fit is refused rather than silently
    widened -- a six-digit name sorts differently and would reorder the
    concat list.
    """
    value = entry.get(KEY_FRAME, position)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TransitionError(
            "timeline entry %d has a non-integer '%s': %r"
            % (position, KEY_FRAME, value))
    if not MIN_FRAME_INDEX <= value <= MAX_FRAME_INDEX:
        raise TransitionError(
            "timeline entry %d has '%s' %d, outside %d..%d; the output "
            "name carries it in a five-digit field, and a wider index "
            "would sort out of order in the concat list"
            % (position, KEY_FRAME, value, MIN_FRAME_INDEX,
               MAX_FRAME_INDEX))
    return value


def _flag(entry: Dict[str, Any], position: int) -> bool:
    """Return an entry's transition flag, which must be a boolean.

    Not coerced with bool(): a string "false" is truthy in Python and
    would compose a group the timeline did not ask for, so a
    non-boolean is refused instead of interpreted.
    """
    value = entry.get(KEY_TRANSITION_AFTER, False)
    if not isinstance(value, bool):
        raise TransitionError(
            "timeline entry %d has a non-boolean '%s': %r.  The flag "
            "decides whether a second of video is spent, so it is not "
            "coerced" % (position, KEY_TRANSITION_AFTER, value))
    return value


def plan_groups(
    entries: Sequence[Dict[str, Any]],
    root: Optional[str] = None,
) -> List[Group]:
    """Resolve one Group per flagged entry, in timeline order.

    A transition sits BETWEEN a flagged frame and its successor, so each
    group needs both: `current` is faded out of and `successor` is faded
    in to.

    THE FLAGGED-LAST-ENTRY CASE IS REFUSED, and nothing is written.  In a
    well-formed timeline it cannot arise: timeline.raw_deltas() gives the
    final frame a raw delta of 0.0 because it has no successor to
    difference against, timeline.is_transition() is strictly greater than
    the ceiling, and timeline.validate_timeline() reports
    'final-frame-flagged' if the last entry carries the flag anyway.  So
    reaching it means the document is malformed, and this raises
    TransitionError naming that problem code.

    It is neither skipped nor honoured, because the only two ways to
    honour it are both dishonest.  Fading the last capture back into
    ITSELF is imagery of an event that did not happen, and the whole
    film's honesty rests on every frame being a photograph of something
    the survivor saw; emitting a short group or none would leave
    render_movie.py charging a second of video that the images do not
    fill.  The right repair is upstream -- recompute the timeline -- so
    the refusal points there rather than absorbing the anomaly here.
    """
    captures = frames_dir(root)
    groups: List[Group] = []
    total = len(entries)
    for position, entry in enumerate(entries, start=1):
        if not _flag(entry, position):
            continue
        index = _entry_frame_index(entry, position)
        current = validated_capture_path(
            entry.get(KEY_FILE),
            "the '%s' of timeline entry %d" % (KEY_FILE, position),
            root, captures)
        if position < total:
            successor_entry = entries[position]
            successor = validated_capture_path(
                successor_entry.get(KEY_FILE),
                "the '%s' of timeline entry %d"
                % (KEY_FILE, position + 1),
                root, captures)
            groups.append(Group(index, current, successor))
            continue
        # REFUSED BEFORE ANYTHING IS PLANNED, let alone written.  A
        # fade from the last capture back into itself is imagery of an
        # event that did not happen, and the whole film's honesty rests
        # on every frame being a photograph of something the survivor
        # saw.  timeline.py's own problem code is named so the operator
        # is sent to the document that has to be recomputed, not to
        # this module.
        raise TransitionError(
            "timeline entry %d is the LAST one and carries '%s', which "
            "timeline.py reports as 'final-frame-flagged': the final "
            "frame has no successor to transition into, so there is no "
            "honest transition to compose.  Nothing has been written.  "
            "Recompute the timeline with timeline.py rather than "
            "fabricating a fade from frame %d back into itself."
            % (position, KEY_TRANSITION_AFTER, index))
    return groups


# ---------------------------------------------------------------------
# The composition
#
# MoviePy 2.x throughout.  The v1 `editor` submodule does not exist,
# `.set_*` became `.with_*`, and effects are classes applied through
# with_effects([...]).  concatenate_videoclips is mandatory: a cross-fade
# applied through the compositing clip class does not render in v2, and
# it does not fail either -- the frames come out with a hard cut where
# the fade was asked for.
# ---------------------------------------------------------------------

def expected_size() -> Tuple[int, int]:
    """Return the (width, height) every frame in the film must have.

    1920x1080 is the captured resolution: the X root is exactly that
    while the game window is 1920x1072 at +0+4, and capture.sh
    photographs the root, so the captures carry a four-pixel letterbox
    and need no rescaling.  render_movie.py encodes at the same size.

    ``$PLAYTHROUGH_SCREEN_WIDTH`` and ``$PLAYTHROUGH_SCREEN_HEIGHT`` from
    playthrough/tooling/env.sh are honoured, because env.sh is the single
    definition of the layout and a run at another geometry must not be
    given transitions of the wrong size.  A resolved size other than
    1920x1080 is reported once, since the encoder's own -s flag is
    written for that value.
    """
    size: List[int] = []
    for name, default in ((ENV_SCREEN_WIDTH, FRAME_WIDTH),
                          (ENV_SCREEN_HEIGHT, FRAME_HEIGHT)):
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            size.append(default)
            continue
        text = raw.strip()
        if not text.isdigit():
            raise TransitionError(
                "$%s is '%s', which is not a plain positive integer; a "
                "frame size is refused before it reaches the "
                "composition rather than guessed at" % (name, raw))
        value = int(text)
        if value <= 0:
            raise TransitionError(
                "$%s is %d; a frame size must be positive"
                % (name, value))
        size.append(value)
    width, height = size[0], size[1]
    if (width, height) != (FRAME_WIDTH, FRAME_HEIGHT):
        _warn(
            "the environment asks for %dx%d frames, not the %dx%d the "
            "X root is captured at; the transitions will match the "
            "environment, so make sure render_movie.py encodes at the "
            "same size" % (width, height, FRAME_WIDTH, FRAME_HEIGHT))
    return width, height


def _assert_decodable_provenance(path: str) -> None:
    """Refuse to compose from a file anybody but this account can rewrite.

    The counterpart of ocr_clock.assert_decodable_provenance, which
    carries the full reasoning; the short version is that the pinned
    Pillow 11.3.0 has published advisories in native decoders, and the
    stated ground for accepting that risk is that this pipeline only ever
    decodes PNGs it captured itself.  A security review found the frames
    group- and world-writable, so that ground did not hold, and a mode
    set at creation is a fact about the past.  This checks it at the
    moment the bytes reach MoviePy.

    THE CHECK AND THE READ ARE ONE OPERATION NOW.  A later review found
    the other half of the race: these properties were read with `lstat`
    and the frame was then handed to MoviePy BY PATHNAME, which reopens
    it and hands it to Pillow -- so a concurrent writer with this
    account's uid could substitute another inode in between and the
    decoder would parse something nothing had validated (CWE-367).
    read_verified_frame() closes that by opening once with O_NOFOLLOW,
    asking `fstat` about the descriptor, and returning the bytes read
    through it; _verified_frame_array() decodes those bytes and the clip
    is built from the resulting array.  This function is the
    descriptor-less half, kept public for a caller that wants the
    question answered about a path it is not about to decode.

    :raises TransitionError: naming the property that failed.
    """
    descriptor = _open_frame_descriptor(path)
    try:
        _refuse_undecodable_stat(os.fstat(descriptor), path)
    finally:
        os.close(descriptor)


def _open_frame_descriptor(path: str) -> int:
    """Open `path` for reading without following a final symlink.

    O_NOFOLLOW makes "this is not a symlink" a property of the open
    itself rather than of a preceding stat.  O_NONBLOCK is there because
    this is the call that would otherwise block forever on a fifo planted
    under a capture's name; the descriptor is checked for being a regular
    file immediately afterwards.

    :raises TransitionError: naming what the open refused.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags)
    except OSError as err:
        if err.errno in (errno.ELOOP, errno.EMLINK):
            raise TransitionError(
                "%s is a symbolic link, so the name checked and the "
                "bytes decoded are two separate decisions"
                % path) from err
        raise TransitionError(
            "%s could not be examined before composing: %s"
            % (path, err)) from err


def _refuse_undecodable_stat(info: "os.stat_result", path: str) -> None:
    """Refuse a stat result that is not a capture this account wrote.

    :raises TransitionError: naming the property that failed.
    """
    if stat.S_ISLNK(info.st_mode):              # pragma: no cover
        raise TransitionError(
            "%s is a symbolic link, so the name checked and the bytes "
            "decoded are two separate decisions" % path)
    if not stat.S_ISREG(info.st_mode):
        raise TransitionError(
            "%s is not a regular file (mode %#o), so reading it is an "
            "operation on something other than a capture"
            % (path, info.st_mode))
    if info.st_uid != os.geteuid():
        raise TransitionError(
            "%s is owned by uid %d and this process runs as uid %d, so "
            "its owner rather than this pipeline decides what the "
            "decoder parses" % (path, info.st_uid, os.geteuid()))
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise TransitionError(
            "%s is mode %04o, which is writable beyond its owner, so "
            "its contents can be replaced between the capture that "
            "wrote it and this composition"
            % (path, stat.S_IMODE(info.st_mode)))


def read_verified_frame(path: str) -> bytes:
    """Return a capture's bytes, validated as they were read.

    One open, one fstat, one read, in that order, so every property the
    provenance rule asks is asked of the descriptor the bytes came out
    of.  The counterpart of ocr_clock.read_verified_frame, which carries
    the full reasoning.

    The size is bounded twice -- against what `fstat` reported and
    against what was actually read -- because a file being appended to
    while it is read passes the first and not the second.

    :raises TransitionError: naming the property that failed.
    """
    descriptor = _open_frame_descriptor(path)
    try:
        info = os.fstat(descriptor)
        _refuse_undecodable_stat(info, path)
        if info.st_size > MAX_FRAME_BYTES:
            raise TransitionError(
                "%s is %d bytes and the ceiling is %d.  A 1920x1080 "
                "capture is under two hundred kilobytes, so a file this "
                "large is not one and is refused before it is read into "
                "memory" % (path, info.st_size, MAX_FRAME_BYTES))
        chunks: List[bytes] = []
        total = 0
        while True:
            try:
                block = os.read(descriptor, 1024 * 1024)
            except OSError as err:
                raise TransitionError(
                    "%s could not be read: %s" % (path, err)) from err
            if not block:
                break
            total += len(block)
            if total > MAX_FRAME_BYTES:
                raise TransitionError(
                    "%s grew past the %d-byte ceiling while it was being "
                    "read, so it is being written to and is not a "
                    "finished capture" % (path, MAX_FRAME_BYTES))
            chunks.append(block)
    finally:
        os.close(descriptor)
    return b"".join(chunks)


class decode_limits(object):
    """Bound one composition in CPU time, and forbid a core dump.

    The counterpart of ocr_clock.decode_limits, and identical in
    behaviour -- see that class for the full reasoning, including the
    measurement that made RLIMIT_AS the wrong instrument here (numpy
    reserves 2.5 GiB of address space at import, so a ceiling tight
    enough to bound a decode refuses the import, and one loose enough to
    import bounds nothing; verified by lowering it to 300 MiB after
    import and watching a full decode still succeed).

    RLIMIT_CORE is 0 so a native decoder that segfaults on a malformed
    PNG writes no core file containing the decoded frames.  RLIMIT_CPU is
    the time already used plus DECODE_CPU_SECONDS, because the limit is
    cumulative over the process rather than per call.  Both are restored
    on exit, including when the body raises.
    """

    def __init__(self) -> None:
        self._saved: List[Tuple[int, Tuple[int, int]]] = []

    def __enter__(self) -> "decode_limits":
        if resource is None:            # pragma: no cover - POSIX only
            return self
        used = 0.0
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            used = usage.ru_utime + usage.ru_stime
        except (OSError, ValueError):        # pragma: no cover
            used = 0.0
        targets = [
            ("RLIMIT_CORE", 0),
            ("RLIMIT_CPU", int(used) + DECODE_CPU_SECONDS),
        ]
        for name, wanted in targets:
            limit = getattr(resource, name, None)
            if limit is None:           # pragma: no cover - POSIX only
                continue
            try:
                soft, hard = resource.getrlimit(limit)
            except (OSError, ValueError):    # pragma: no cover
                continue
            # A limit is never RAISED and the hard limit is never
            # touched: an environment that already bounds this process
            # more tightly has made a decision this must not undo.
            target = wanted if hard == resource.RLIM_INFINITY \
                else min(wanted, hard)
            if soft != resource.RLIM_INFINITY and soft <= target:
                continue
            try:
                resource.setrlimit(limit, (target, hard))
            except (OSError, ValueError):    # pragma: no cover
                continue
            self._saved.append((limit, (soft, hard)))
        return self

    def __exit__(self, *_exc: object) -> bool:
        if resource is not None:
            for limit, original in reversed(self._saved):
                try:
                    resource.setrlimit(limit, original)
                except (OSError, ValueError):   # pragma: no cover
                    pass
        self._saved = []
        return False


def _image_size_of(data: bytes, path: str) -> Tuple[int, int]:
    """Return the (width, height) a PNG's own IHDR chunk declares.

    The bytes-shaped half of :func:`_image_size`, so a frame that has
    already been read through a verified descriptor is measured from
    those bytes rather than by opening its name a second time.  Pure
    Python throughout: no native decoder sees this.

    :raises TransitionError: for anything that is not a PNG whose first
        chunk is a well-formed IHDR of a plausible size.
    """
    signature = PNG_MAGIC
    if data[:len(signature)] != signature:
        raise TransitionError(
            "%s does not begin with the PNG signature (it begins %r).  "
            "Every frame this module composes from is a PNG written by "
            "capture.sh; a file carrying another format's content is "
            "refused rather than handed to whichever native decoder it "
            "would reach" % (path, data[:len(signature)]))
    body = data[len(signature):len(signature) + 16]
    if len(body) < 16 or body[4:8] != b"IHDR":
        raise TransitionError(
            "%s does not open with an IHDR chunk, so it is not a PNG "
            "this pipeline wrote" % path)
    width = int.from_bytes(body[8:12], "big")
    height = int.from_bytes(body[12:16], "big")
    if width <= 0 or height <= 0:
        raise TransitionError(
            "%s declares a %dx%d image" % (path, width, height))
    if width * height > MAX_PIXELS:
        raise TransitionError(
            "%s declares %dx%d = %d pixels, past the %d-pixel ceiling"
            % (path, width, height, width * height, MAX_PIXELS))
    return width, height


def _verified_frame_array(path: str, size: Tuple[int, int]) -> Any:
    """Return one capture as an RGB array, read and decoded once.

    THE WHOLE OF THE FIX FOR THE DECODE RACE, in one function: the bytes
    are read through a validated descriptor, the geometry is taken from
    those same bytes, and the decode is Pillow restricted to the PNG
    plugin over an in-memory buffer -- so no pathname is handed to a
    native decoder at any point and nothing can be substituted between
    the check and the parse.

    The array is what the clip is built from.  MoviePy's ImageClip
    accepts either a filename or an array and hands a filename to Pillow
    itself, which would reopen the path and undo the guarantee; an array
    cannot be reopened.

    :raises TransitionError: naming what failed, from the read, the
        geometry check or the decode.
    """
    _require_numpy()
    _require_pillow()
    data = read_verified_frame(path)
    actual = _image_size_of(data, path)
    if actual != size:
        raise TransitionError(
            "%s is %dx%d, but the film is cut at %dx%d.  A transition "
            "frame has to match the captures exactly: the encoder is "
            "told one size, and a mismatched frame would either be "
            "rescaled or break the concat pass."
            % (path, actual[0], actual[1], size[0], size[1]))
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with decode_limits():
            with Image.open(io.BytesIO(data), formats=["PNG"]) as opened:
                return np.asarray(opened.convert("RGB"))
    except Image.DecompressionBombError as err:
        raise TransitionError(
            "%s declares more than %d pixels: %s"
            % (path, MAX_PIXELS, err)) from err
    except (OSError, ValueError) as err:
        raise TransitionError(
            "%s is not a decodable PNG: %s" % (path, err)) from err
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def _image_size(path: str) -> Tuple[int, int]:
    """Return a PNG's (width, height) without decoding its pixels.

    Read from the IHDR chunk in pure Python.  Pillow identifies a file
    by its CONTENT and ships a plugin per format, so ``Image.open`` on a
    path called frame_00001.png would hand a crafted PSD, DDS, TIFF or
    FLI to that format's native parser -- which is where Pillow's
    memory-corruption advisories live, and this pipeline is pinned to
    11.3.0 because moviepy 2.2.1 declares ``pillow<12.0``.  The
    commonest question asked of a capture is "is it 1920x1080?", and
    answering it from 24 bytes of header means no decoder runs at all.
    """
    signature = PNG_MAGIC
    try:
        with open(path, "rb") as handle:
            header = handle.read(len(signature) + 16)
    except OSError as err:
        raise TransitionError(
            "%s could not be read: %s" % (path, err)) from err
    if header[:len(signature)] != signature:
        raise TransitionError(
            "%s does not begin with the PNG signature (it begins %r).  "
            "Every frame this module composes from is a PNG written by "
            "capture.sh; a file carrying another format's content is "
            "refused rather than handed to whichever native decoder it "
            "would reach" % (path, header[:len(signature)]))
    body = header[len(signature):]
    if len(body) < 16 or body[4:8] != b"IHDR":
        raise TransitionError(
            "%s does not open with an IHDR chunk, so it is not a PNG "
            "this pipeline wrote" % path)
    width = int.from_bytes(body[8:12], "big")
    height = int.from_bytes(body[12:16], "big")
    if width <= 0 or height <= 0:
        raise TransitionError(
            "%s declares a %dx%d image" % (path, width, height))
    if width * height > MAX_PIXELS:
        raise TransitionError(
            "%s declares %dx%d = %d pixels, past the %d-pixel ceiling"
            % (path, width, height, width * height, MAX_PIXELS))
    return width, height


def _assert_capture_size(path: str, size: Tuple[int, int]) -> None:
    """Refuse a capture that is not the size the film is cut at.

    concatenate_videoclips takes its geometry from the first clip, so a
    mis-sized capture would either produce a group that does not match
    the frames around it or fail deep inside the composition with a
    diagnostic about array shapes.  Checked here, where the message can
    name the file.
    """
    actual = _image_size(path)
    if actual != size:
        raise TransitionError(
            "%s is %dx%d, but the film is cut at %dx%d.  A transition "
            "frame has to match the captures exactly: the encoder is "
            "told one size, and a mismatched frame would either be "
            "rescaled or break the concat pass."
            % (path, actual[0], actual[1], size[0], size[1]))


def title_card(
    font: str,
    size: Tuple[int, int],
    duration: float = CARD_SECONDS,
) -> Any:
    """Return the "…time passes…" card, set in the game's own face.

    MoviePy 2 replaced ImageMagick with Pillow, so `font` is a
    filesystem path to a font file and no ImageMagick configuration is
    involved.  The card is white on black at the full frame size, so it
    is the fade's destination rather than an overlay on top of one.
    """
    _require_moviepy()
    try:
        card = TextClip(
            font=font,
            text=CARD_TEXT,
            font_size=CARD_FONT_SIZE,
            color=CARD_COLOR,
            bg_color=CARD_BG_COLOR,
            size=size,
        )
    except (OSError, ValueError) as err:
        raise TransitionError(
            "the title card could not be composed with %s: %s"
            % (font, err)) from err
    return card.with_duration(duration)


def _frame_to_rgb8(frame: Any, ordinal: int) -> Any:
    """Return one composed frame as an 8-bit RGB array.

    THIS CONVERSION IS NOT COSMETIC.  iter_frames returns MIXED dtypes:
    uint8 for the frames that pass through untouched, and float64 for
    every frame the fade scaled.  PIL.Image.fromarray raises TypeError
    on a float64 array rather than writing a slightly wrong PNG, so a
    module that skipped this step would work for the card and die on the
    fade.  Measured under moviepy 2.2.1 with Pillow 11.3.0.

    Rounding is np.rint rather than a truncating cast, so a fade step
    that lands on 158.6 is written as 159 and not 158; it is
    deterministic, which is what keeps a re-run byte-identical.
    """
    _require_numpy()
    array = np.asarray(frame)
    if array.ndim != 3:
        raise TransitionError(
            "composed frame %d has %d dimensions, expected 3 (height, "
            "width, channels)" % (ordinal, array.ndim))
    channels = int(array.shape[2])
    if channels == 4:
        # An alpha channel would make the written PNGs inconsistent with
        # each other and with the captures.  Dropping a channel is
        # lossless for the opaque imagery this pipeline composes, and it
        # is reported so it is never a silent conversion.
        _warn(
            "composed frame %d carries an alpha channel; it is dropped "
            "so every written frame is 8-bit RGB like the captures"
            % ordinal)
        array = array[:, :, :3]
    elif channels != 3:
        raise TransitionError(
            "composed frame %d has %d channels, expected 3 (RGB)"
            % (ordinal, channels))
    if array.dtype != np.uint8:
        array = np.clip(
            np.rint(array.astype(np.float64)), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(array)


def _write_png(array: Any, path: str) -> None:
    """Write one 8-bit RGB PNG, refusing to follow a link.

    O_NOFOLLOW is the point of opening by descriptor: the output name is
    predictable, and a symlink planted there would otherwise redirect
    the write -- plausibly onto a capture or onto the movie -- while the
    write itself reported success.  O_TRUNC is what makes a re-run
    overwrite in place rather than append.
    """
    _require_pillow()
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o644)
    except OSError as err:
        raise TransitionError(
            "could not open %s for writing: %s" % (path, err)) from err
    try:
        with os.fdopen(descriptor, "wb") as handle:
            Image.fromarray(array).save(handle, format="PNG")
    except OSError as err:
        raise TransitionError(
            "could not write %s: %s" % (path, err)) from err


def _assert_written(path: str, size: Tuple[int, int]) -> None:
    """Re-read a written frame and refuse a wrong size.

    Asserted from the file rather than from the array it came from,
    because that is the artifact render_movie.py will encode and
    verify_artifacts.sh will measure.
    """
    actual = _image_size(path)
    if actual != size:
        raise TransitionError(
            "%s was written at %dx%d but the film is cut at %dx%d"
            % (path, actual[0], actual[1], size[0], size[1]))


def _assert_name_format() -> None:
    """Refuse to write if env.sh and this module name files differently.

    playthrough/tooling/env.sh is the single definition of the artifact
    layout and exports ``$PLAYTHROUGH_TRANSITION_FORMAT`` so that the
    writer, the concat list and the verifier agree byte for byte.  The
    format is not simply adopted from the environment, because these
    names are a contract with render_movie.py and verify_artifacts.sh
    rather than a preference; instead the two are held to being the
    SAME, so they cannot drift apart without somebody being told.
    """
    declared = os.environ.get(ENV_TRANSITION_FORMAT)
    if declared and declared.strip() and \
            declared.strip() != TRANSITION_NAME_FORMAT:
        raise TransitionError(
            "$%s is '%s' but this module writes '%s'.  These names are "
            "a contract: render_movie.py builds the concat list from "
            "them and verify_artifacts.sh counts groups by them, so the "
            "environment and the writer are held to the same format "
            "rather than one silently overriding the other.  Fix "
            "playthrough/tooling/env.sh or this module so they agree."
            % (ENV_TRANSITION_FORMAT, declared.strip(),
               TRANSITION_NAME_FORMAT))


def group_frame_paths(out_prefix: str) -> List[str]:
    """Return the paths one group occupies, in order.

    The index is zero-based, so for any capture N the timeline flags
    with transition_after the group runs trans_NNNNN_00.png through
    trans_NNNNN_11.png; capture 1 yields trans_00001_00.png only if
    capture 1 is itself flagged, and an unflagged capture has no group
    and no file.  Zero-based is chosen once and applied everywhere,
    because the second field is an offset within the group rather than
    a count of anything.
    """
    _assert_name_format()
    return [out_prefix + TRANSITION_SUFFIX_FORMAT % ordinal
            for ordinal in range(
                FIRST_GROUP_INDEX, FIRST_GROUP_INDEX + FRAMES_PER_GROUP)]


def compose_transition_group(
    current: str,
    successor: str,
    out_prefix: str,
    font: Optional[str] = None,
    size: Optional[Tuple[int, int]] = None,
    root: Optional[str] = None,
    repo_root_dir: Optional[str] = None,
) -> List[str]:
    """Compose one transition and write it out as PNG frames.

    This is the whole cinematic unit: a fade out of `current`, the
    "…time passes…" card, and a fade in to `successor`.  It is the
    single implementation -- :func:`make_transitions` drives it once per
    flagged entry, and run_pipeline.sh reaches this module rather than
    reimplementing the composition.

    :param current: the capture being faded OUT of.
    :param successor: the capture being faded IN to.
    :param out_prefix: the output stem, e.g. ``.../trans_00042``;
        ``_00.png`` through ``_11.png`` are appended.  Validated to
        resolve inside a build/transitions directory within the approved
        root, so no caller can aim a frame at playthrough/frames/.
    :param font: the typeface for the card; defaults to the game's own
        data/font/Terminus.ttf.
    :param size: the frame size; defaults to :func:`expected_size`.
    :param root: the artifact tree the output prefix and the source
        captures must resolve inside; defaults to the pipeline's
        playthrough/ directory.  A test passes its own; nothing in the
        environment can move it.
    :param repo_root_dir: the checkout the card's typeface is resolved
        against, since data/font/Terminus.ttf is the game's own font and
        lives outside playthrough/; defaults to the checkout this module
        sits in.
    :returns: the paths written, in order.
    :raises TransitionError: for a missing font, a missing or mis-sized
        capture, an output prefix pointing anywhere it may not, a group
        of the wrong length, or a frame written at the wrong size.
    """
    _require_moviepy()
    _require_numpy()
    _require_pillow()

    prefix = validated_output_prefix(out_prefix, root)
    face = font if font else font_path(repo_root_dir)
    geometry = size if size else expected_size()

    # The inputs are checked for shape, existence and size but NOT for
    # containment inside playthrough/frames/.  Containment is a property
    # of the paths the TIMELINE supplies, and plan_groups() enforces it
    # there, at the point where untrusted input enters; this entry point
    # exists so a caller with two frames in hand can compose from them.
    # The direction that matters for integrity is the write, and that is
    # contained unconditionally by validated_output_prefix() above.
    source = _validated_image_path(
        current, "the frame being faded out of", root)
    target = _validated_image_path(
        successor, "the frame being faded in to", root)
    # ONE READ EACH, VALIDATED AS IT IS READ, AND NO PATHNAME REACHES A
    # DECODER.  This used to be four separate reads of two names -- an
    # IHDR read for the geometry, an lstat for the provenance, and then
    # MoviePy reopening each path and handing it to Pillow -- and a
    # review named the consequence: with a same-uid writer able to
    # replace the inode in between, the bytes that were parsed were not
    # the bytes that were checked (CWE-367).  _verified_frame_array does
    # the read, the geometry check and the format-restricted decode
    # through one descriptor and returns an array, which cannot be
    # reopened by anybody.
    source_frame = _verified_frame_array(source, geometry)
    target_frame = _verified_frame_array(target, geometry)

    paths = group_frame_paths(prefix)
    clips: List[Any] = []
    segment = None
    staged_frames: List[Tuple[str, str]] = []
    try:
        # The composition, exactly as the plan fixes it.  Effects are
        # v2 classes handed to with_effects([...]); CONCATENATED rather
        # than composited, because a cross-fade applied through the
        # compositing clip class renders WITHOUT the fade and reports
        # nothing at all.
        with decode_limits():
            clips = [
                ImageClip(source_frame).with_duration(FADE_SECONDS)
                .with_effects([vfx.FadeOut(FADE_SECONDS)]),
                title_card(face, geometry, CARD_SECONDS),
                ImageClip(target_frame).with_duration(FADE_SECONDS)
                .with_effects([vfx.FadeIn(FADE_SECONDS)]),
            ]
            segment = concatenate_videoclips(clips)
            if segment.size is not None and \
                    tuple(int(value) for value in segment.size) != geometry:
                raise TransitionError(
                    "the composed segment is %sx%s but the film is cut at "
                    "%dx%d"
                    % (segment.size[0], segment.size[1], geometry[0],
                       geometry[1]))
            # STREAMED, NEVER MATERIALISED.  list(iter_frames(...)) holds
            # all twelve 1920x1080 arrays at once, and the faded ones come
            # back as float64, so the raw arrays alone reach roughly 570
            # MiB before the clips, the card buffers and the Pillow objects
            # on top -- measured at 553.9 MiB peak RSS for one group
            # against 223.0 MiB streaming.  Each frame is converted and
            # written as it is produced and only the COUNT is kept, so the
            # exact-twelve assertion below still refuses a short segment AND
            # a long one while one frame is resident at a time.
            written = 0
            for ordinal, frame in enumerate(segment.iter_frames(fps=FPS)):
                if ordinal >= FRAMES_PER_GROUP:
                    # Keep consuming so the reported count is the true one,
                    # but write nothing past the plan.
                    written += 1
                    continue
                staged_frame = paths[ordinal] + STAGED_FRAME_SUFFIX
                _write_png(_frame_to_rgb8(frame, ordinal), staged_frame)
                _assert_written(staged_frame, geometry)
                staged_frames.append((staged_frame, paths[ordinal]))
                written += 1
    except TransitionError:
        _discard_staged_frames(staged_frames)
        raise
    except (OSError, ValueError, TypeError) as err:
        _discard_staged_frames(staged_frames)
        raise TransitionError(
            "the transition between %s and %s could not be composed: %s"
            % (source, target, err)) from err
    finally:
        for clip in clips + ([segment] if segment is not None else []):
            close = getattr(clip, "close", None)
            if callable(close):
                try:
                    close()
                except (OSError, AttributeError):  # pragma: no cover
                    # Releasing a reader must never mask the real
                    # failure that brought us here.
                    pass

    # ASSERTED AFTER THE ITERATION, so a generator that stopped short
    # and one that ran long are both refused, each naming the true count.
    if written != FRAMES_PER_GROUP:
        _discard_staged_frames(staged_frames)
        raise TransitionError(
            "the composed segment yielded %d frame(s) at %d fps, not "
            "the %d a %ss transition must be.  verify_artifacts.sh "
            "counts groups against the timeline's flags and "
            "render_movie.py charges exactly %ss of video per group, so "
            "a different count would desynchronise the captions."
            % (written, FPS, FRAMES_PER_GROUP, EXPECTED_TRANSITION,
               EXPECTED_TRANSITION))
    # COMPLETE AND COUNTED, so the group may be published.
    for staged_frame, final in staged_frames:
        try:
            os.replace(staged_frame, final)
        except OSError as err:
            _discard_staged_frames(staged_frames)
            raise TransitionError(
                "could not publish %s as %s: %s"
                % (staged_frame, final, err)) from err
    return paths


def _discard_staged_frames(staged: Sequence[Tuple[str, str]]) -> None:
    """Remove a part-built group's staged frames.  Never raises.

    A refusal must leave the directory as it found it, so the frames
    this attempt wrote are withdrawn and any previous group of the same
    name is left untouched.
    """
    for staged_frame, _ in staged:
        try:
            os.unlink(staged_frame)
        except OSError:
            pass


# ---------------------------------------------------------------------
# Idempotency
#
# The transition frames are COMMITTED artifacts, so a re-run has to
# leave the directory describing the current timeline and nothing else.
# A previous run with more flags in it would otherwise leave groups
# behind that no flag accounts for, and verify_artifacts.sh asserts
# exactly that identity: as many groups on disk as flags in the
# timeline.
# ---------------------------------------------------------------------

def _ensure_directory(directory: str) -> None:
    """Create the output directory, refusing a non-directory in its place."""
    if os.path.islink(directory):
        raise TransitionError(
            "the output directory is a symbolic link: %s.  This module "
            "writes files, it does not follow links to them."
            % directory)
    if os.path.exists(directory) and not os.path.isdir(directory):
        raise TransitionError(
            "%s exists and is not a directory" % directory)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as err:
        raise TransitionError(
            "could not create %s: %s" % (directory, err)) from err


# ---------------------------------------------------------------------
# The staged generation
#
# WHY THE DIRECTORY IS REPLACED RATHER THAN EDITED.  Composing in place
# did two destructive things before it had produced anything: it
# unlinked every frame the new timeline did not account for, and then
# O_TRUNCated each surviving name as it wrote.  So an interruption
# anywhere in the middle -- a full disk, a signal, a MoviePy failure on
# group nine of eleven -- left the directory holding some frames from
# this timeline, some from the last one, and some truncated to zero
# bytes.  Every one of them matches `trans_*.png`, so verify_artifacts.sh
# counts them, and a film assembled from that directory splices a
# transition that was never composed for it.
#
# Worse, two runs at once interleaved: both reconciled against their own
# expectations, so each deleted the other's frames while writing its
# own, and the directory ended up describing neither timeline.
#
# So a generation is now built COMPLETE AND VERIFIED in a staging
# directory beside the destination, under an exclusive lock that makes
# concurrent runs wait rather than interleave, and only then switched in.
# The switch is two renames within one directory, so the window in which
# the destination does not exist is a pair of adjacent metadata
# operations rather than the whole composition; and because a rename
# either happens or does not, no partial generation is ever visible.
# ---------------------------------------------------------------------

STAGING_PREFIX = ".transitions-staging-"

# The suffix a frame carries while it is being composed.  Each streamed
# frame is written here and renamed into place only once the whole group
# has been produced and counted, so a segment that yields the wrong
# number of frames -- or a device that fails half way -- publishes
# NOTHING and leaves any previous group of the same name intact.  That
# is what lets the frames be streamed one at a time (which is why the
# composition needs ~223 MiB rather than ~554 MiB) without giving up
# all-or-nothing publication.
STAGED_FRAME_SUFFIX = ".composing"
RETIRED_PREFIX = ".transitions-retired-"

# The artifact this module publishes, for timeline.ArtifactLock.  The
# lock lives in the pipeline's scratch directory OUTSIDE the tree,
# because .gitignore's terminal `!/playthrough/**` would otherwise
# re-include a lock file as though it were a session's evidence.
LOCK_NAME = "transitions"


def _publish_generation(staging: str, directory: str) -> None:
    """Switch a verified staging directory in for the destination.

    Two renames inside one parent: the live directory is retired to a
    unique name, the staging directory takes its place, and the retired
    one is then removed.  A rename either happens or does not, so no
    reader ever sees a half-composed generation -- and if the second
    rename fails, the first is undone so the previous generation is
    restored rather than lost.
    """
    parent = os.path.dirname(directory)
    retired = None
    if os.path.exists(directory):
        retired = os.path.join(
            parent, "%s%d-%d" % (RETIRED_PREFIX, os.getpid(),
                                 time.time_ns()))
        try:
            os.rename(directory, retired)
        except OSError as err:
            raise TransitionError(
                "could not retire the previous transitions directory "
                "%s: %s" % (directory, err)) from err
    try:
        os.rename(staging, directory)
    except OSError as err:
        if retired is not None:
            # Put the previous generation back: a failed switch must
            # leave the directory as it was, not absent.
            try:
                os.rename(retired, directory)
            except OSError:  # pragma: no cover - defensive
                raise TransitionError(
                    "the transitions directory %s could not be "
                    "published (%s) AND the previous generation could "
                    "not be restored from %s; it is still there and can "
                    "be renamed back by hand"
                    % (directory, err, retired)) from err
        raise TransitionError(
            "could not publish the composed transitions into %s: %s"
            % (directory, err)) from err
    timeline.fsync_directory(parent)
    if retired is not None:
        _remove_tree(retired)


def _remove_tree(directory: str) -> None:
    """Delete a directory this module created, and only its own files.

    Never recurses and never follows a link: the only entries a retired
    generation can hold are the regular files this module wrote, so
    anything else is left behind along with the directory rather than
    removed blindly.
    """
    try:
        names = os.listdir(directory)
    except OSError as err:
        _warn("could not read %s to remove it: %s" % (directory, err))
        return
    for name in names:
        target = os.path.join(directory, name)
        if os.path.islink(target) or not os.path.isfile(target):
            _warn(
                "%s is not a regular file, so the retired generation "
                "%s is left in place rather than removed blindly"
                % (target, directory))
            return
        try:
            os.unlink(target)
        except OSError as err:
            _warn("could not remove %s: %s" % (target, err))
            return
    try:
        os.rmdir(directory)
    except OSError as err:
        _warn("could not remove the retired directory %s: %s"
              % (directory, err))


# ---------------------------------------------------------------------
# The generation manifest: written here, read by render_movie.py.
#
# The SCHEMA LIVES IN THIS MODULE, next to the producer, and the renderer
# validates through generation_manifest_problems() rather than reading the
# fields itself.  A second, laxer copy of these rules in the consumer is
# exactly how a provenance check becomes decorative.
# ---------------------------------------------------------------------

def generation_manifest_path(directory: str) -> str:
    """Return the provenance path for a transitions directory.

    BESIDE the directory, not inside it: playthrough/build/ holds every
    derived committed intermediate -- the concat list, the film's
    generation manifest, the transcripts' -- and the transitions
    directory itself admits `trans_*.png` and nothing else.  Taking the
    directory as the argument keeps every caller, this module's and
    render_movie.py's, asking the one question it actually has an answer
    to: where is the record for THIS group set.
    """
    parent = os.path.dirname(os.path.normpath(directory))
    if not parent:
        parent = os.curdir
    return os.path.join(parent, GENERATION_MANIFEST_NAME)


def build_generation_manifest(
    groups: Sequence[Group],
    timeline_path: str,
    geometry: Tuple[int, int],
    face: str,
    staged_by_frame: Mapping[int, Sequence[str]],
) -> Dict[str, Any]:
    """Return the provenance record for one composed generation.

    Pure apart from reading the bytes it hashes.  Binds four things the
    renderer cannot otherwise check: the TIMELINE these groups were
    computed from, by that document's own digest; the two CAPTURES each
    group was faded between, by theirs; the card's TYPEFACE; and this
    run's own OUTPUT bytes.
    """
    width, height = geometry
    record: Dict[str, Any] = {
        "version": timeline.GENERATION_VERSION,
        "stage": LOCK_NAME,
        "timeline": {
            "path": relative_to_repo(timeline_path),
            "sha256": timeline.file_digest(timeline_path),
        },
        "font": {
            "path": relative_to_repo(face),
            "sha256": font_digest(face),
        },
        "geometry": {"width": width, "height": height},
        "frames_per_group": FRAMES_PER_GROUP,
        "transition_seconds": EXPECTED_TRANSITION,
        "groups": [],
    }
    for group in groups:
        outputs = []
        for path in staged_by_frame[group.frame]:
            outputs.append({
                "name": os.path.basename(path),
                "sha256": timeline.file_digest(path),
                "bytes": os.path.getsize(path),
            })
        record["groups"].append({
            "frame": group.frame,
            "sources": [
                {"path": relative_to_repo(group.current),
                 "sha256": timeline.file_digest(group.current)},
                {"path": relative_to_repo(group.successor),
                 "sha256": timeline.file_digest(group.successor)},
            ],
            "outputs": outputs,
        })
    return record


def generation_manifest_text(record: Mapping[str, Any]) -> str:
    """Render the manifest deterministically."""
    return json.dumps(dict(record), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


def read_generation_manifest(directory: str) -> Dict[str, Any]:
    """Return the provenance record published for `directory`.

    Read from beside the group set, at
    playthrough/build/transitions.json, because the directory itself
    admits `trans_*.png` and nothing else.

    :raises TransitionError: when it is absent, unreadable or not a
        record.  ABSENCE IS A FAULT, not a default: a group set without
        provenance is a group set nobody can attribute to a timeline, and
        accepting one is the defect this manifest exists to close.  An
        interrupted publication can leave exactly that state, which is
        why the generation journal reports it and a re-run repairs it.
    """
    path = generation_manifest_path(directory)
    if os.path.islink(path):
        raise TransitionError(
            "%s is a symbolic link; the provenance of a generation is "
            "not read through one" % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise TransitionError(
            "there is no %s beside %s, so the transition frames in it "
            "cannot be attributed to any timeline.  Run "
            "make_transitions.py against the timeline being rendered: "
            "twelve files with the right names and the right pixel "
            "dimensions are not evidence that they were composed from "
            "this session's captures."
            % (GENERATION_MANIFEST_NAME, directory)) from None
    except OSError as err:
        raise TransitionError(
            "cannot read %s: %s" % (path, err)) from err
    try:
        record = json.loads(text)
    except ValueError as err:
        raise TransitionError(
            "%s is not valid JSON (%s), so the generation on disk cannot "
            "be attributed.  Recompose it." % (path, err)) from err
    if not isinstance(record, dict):
        raise TransitionError(
            "%s holds a %s, not a record" % (path, type(record).__name__))
    return record


def _manifest_group_outputs(
    entry: Any,
    problems: List[str],
) -> Optional[Tuple[int, List[Dict[str, Any]]]]:
    """Return (frame, outputs) for one manifest group, or None."""
    if not isinstance(entry, dict):
        problems.append(
            "the generation manifest holds a %s where a group record "
            "belongs" % type(entry).__name__)
        return None
    frame = entry.get("frame")
    if isinstance(frame, bool) or not isinstance(frame, int):
        problems.append(
            "a group in the generation manifest has no integer frame "
            "index: %r" % (frame,))
        return None
    outputs = entry.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        problems.append(
            "the group for frame %d names no outputs" % frame)
        return None
    return (frame, outputs)


def generation_manifest_problems(
    directory: str,
    timeline_path: str,
    flagged: Iterable[int],
) -> List[str]:
    """Report every way a published group set fails its provenance.

    THE GLOBAL CHECK.  `flagged` is EVERY frame index the timeline being
    rendered carries ``transition_after`` on, and the group set on disk
    must be exactly that -- so a stale group left behind for an index the
    recomputed timeline no longer flags is a REFUSAL rather than something
    nobody looks at.  The per-entry check that preceded this one could
    only ever inspect the indices the current timeline flags, which is
    precisely why an extra group was invisible to it while
    verify_artifacts.sh, which globs the whole directory, counted it.

    Read-only.  An empty list means the frames in `directory` were
    composed by this module, from this timeline, out of these captures,
    and still carry the bytes it wrote.
    """
    problems: List[str] = []
    try:
        record = read_generation_manifest(directory)
    except TransitionError as err:
        return [str(err)]
    if record.get("version") != timeline.GENERATION_VERSION:
        return ["the provenance record for %s is version %r, which this "
                "module cannot interpret; recompose the transitions"
                % (directory, record.get("version"))]
    if record.get("stage") != LOCK_NAME:
        problems.append(
            "the provenance record for %s was written by stage %r, not "
            "%r" % (directory, record.get("stage"), LOCK_NAME))
    problems.extend(_timeline_provenance_problems(record, timeline_path))
    problems.extend(_geometry_provenance_problems(record))
    wanted = sorted({int(one) for one in flagged})
    entries = record.get("groups")
    if not isinstance(entries, list):
        problems.append(
            "the provenance record for %s names no groups" % directory)
        return problems
    seen: List[int] = []
    for entry in entries:
        resolved = _manifest_group_outputs(entry, problems)
        if resolved is None:
            continue
        frame, outputs = resolved
        seen.append(frame)
        problems.extend(
            _group_output_problems(directory, frame, outputs))
    problems.extend(_group_set_problems(directory, sorted(seen), wanted))
    return problems


def _timeline_provenance_problems(
    record: Mapping[str, Any],
    timeline_path: str,
) -> List[str]:
    """Report a group set composed from a different timeline."""
    stated = record.get("timeline")
    if not isinstance(stated, dict):
        return ["the generation manifest names no timeline, so its "
                "groups cannot be attributed to the document being "
                "rendered"]
    declared = stated.get("sha256")
    if not isinstance(declared, str) or not declared:
        return ["the generation manifest names no timeline digest"]
    try:
        observed = timeline.file_digest(timeline_path)
    except (timeline.TimelineError, OSError) as err:
        return ["the timeline %s could not be hashed to check the "
                "transitions against it: %s" % (timeline_path, err)]
    if declared == observed:
        return []
    return ["the transition frames were composed from a timeline whose "
            "digest is %s, but the timeline being rendered is %s.  The "
            "group indices and the geometry would match anyway -- a "
            "flagged frame 42 is trans_00042_* in every session -- so "
            "the film would fade between captures from a session that is "
            "not this one.  Run make_transitions.py against this "
            "timeline." % (declared[:16], observed[:16])]


def _geometry_provenance_problems(
    record: Mapping[str, Any],
) -> List[str]:
    """Report a generation composed under different constants."""
    problems = []
    geometry = record.get("geometry")
    width, height = expected_size()
    if not isinstance(geometry, dict) or \
            geometry.get("width") != width or \
            geometry.get("height") != height:
        problems.append(
            "the generation manifest declares geometry %r, and this film "
            "is %dx%d" % (geometry, width, height))
    if record.get("frames_per_group") != FRAMES_PER_GROUP:
        problems.append(
            "the generation manifest declares %r frames per group, and "
            "this module composes %d"
            % (record.get("frames_per_group"), FRAMES_PER_GROUP))
    return problems


def _group_output_problems(
    directory: str,
    frame: int,
    outputs: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Report a group whose files are not the ones that were composed."""
    problems: List[str] = []
    expected = [os.path.basename(path) for path in
                group_frame_paths(TRANSITION_STEM_FORMAT % frame)]
    named = [one.get("name") for one in outputs
             if isinstance(one, dict)]
    if named != expected:
        problems.append(
            "the generation manifest's group for frame %d names %r, and "
            "a group is %r" % (frame, named, expected))
        return problems
    for declared in outputs:
        name = declared.get("name")
        path = os.path.join(directory, str(name))
        digest = declared.get("sha256")
        size = declared.get("bytes")
        if os.path.islink(path) or not os.path.isfile(path):
            problems.append(
                "%s is named by the generation manifest and is not a "
                "regular file on disk" % path)
            continue
        if not isinstance(digest, str) or not digest:
            problems.append("%s is named with no digest" % path)
            continue
        try:
            observed = timeline.file_digest(path)
            observed_size = os.path.getsize(path)
        except (timeline.TimelineError, OSError) as err:
            problems.append("%s could not be hashed: %s" % (path, err))
            continue
        if observed != digest:
            problems.append(
                "%s carries %s but was composed as %s: same name, same "
                "geometry, different pixels.  The film would encode "
                "imagery this generation did not produce."
                % (path, observed[:16], digest[:16]))
        elif isinstance(size, int) and not isinstance(size, bool) \
                and observed_size != size:
            problems.append(
                "%s is %d bytes and the generation manifest declares %d"
                % (path, observed_size, size))
    return problems


def _group_set_problems(
    directory: str,
    seen: Sequence[int],
    wanted: Sequence[int],
) -> List[str]:
    """Report the group index set not being exactly the flagged set."""
    if list(seen) == list(wanted):
        return []
    extra = sorted(set(seen) - set(wanted))
    missing = sorted(set(wanted) - set(seen))
    problems = []
    if extra:
        problems.append(
            "%s holds a transition group for frame(s) %s, which the "
            "timeline being rendered does not flag.  A stale group is "
            "counted by verify_artifacts.sh, which globs this directory, "
            "so it is refused here rather than left to be found there.  "
            "Recompose the transitions against this timeline."
            % (directory, ", ".join(str(one) for one in extra)))
    if missing:
        problems.append(
            "%s holds no transition group for flagged frame(s) %s.  The "
            "timeline has already charged video time to each of them, so "
            "the film would be short of imagery for it."
            % (directory, ", ".join(str(one) for one in missing)))
    if not extra and not missing:
        problems.append(
            "%s names its groups in the order %r, and the timeline flags "
            "%r" % (directory, list(seen), list(wanted)))
    return problems


def _publish_generation_manifest(directory: str, text: str) -> str:
    """Replace the provenance record beside `directory`.  Returns it.

    Staged as a dot-prefixed sibling in the same directory and renamed,
    so a reader sees the whole previous record or the whole new one, and
    both the file and its parent are fsynced -- a rename is not durable
    until the directory entry is.

    Published AFTER the switch and under the generation journal, so the
    one ordering an interruption can leave behind is a group set whose
    record is stale, which render_movie.py refuses by digest and the next
    run repairs.  The reverse order would leave a record describing
    frames that are not there, which reads like a complete generation.

    THE SIBLING IS REMOVED ON EVERY PRE-PUBLICATION FAILURE, and it used
    not to be.  A short os.write or a failing fsync raised, the `finally`
    closed the descriptor, and `.transitions.json.publishing` was left
    sitting in playthrough/build/ -- inside the tree .gitignore
    re-includes wholesale, and outside the transitions directory that
    _own_litter() sweeps, so nothing would ever clear it and a later
    `git add -A playthrough/` would commit a half-written provenance
    record nobody authored.  Only the rename's own failure path unlinked
    it.  A code review found it; the whole sequence is wrapped now, and
    publish_transitions() sweeps a stale sibling at the start of a run
    as well, so an interruption no process survived is cleared too.

    A SHORT WRITE IS RETRIED RATHER THAN REPORTED.  os.write may write
    fewer bytes than it was given without anything being wrong, so the
    old check turned an ordinary partial write into a failed generation.
    It loops until the buffer is on the descriptor, and only a write
    that makes no progress at all is an error.
    """
    target = generation_manifest_path(directory)
    parent = os.path.dirname(target) or os.curdir
    staged = staged_manifest_path(directory)
    data = text.encode("utf-8")
    try:
        descriptor = os.open(
            staged,
            os.O_CREAT | os.O_WRONLY | os.O_TRUNC |
            os.O_CLOEXEC | os.O_NOFOLLOW, 0o644)
    except OSError as err:
        _discard_staged_manifest(staged)
        raise TransitionError(
            "could not stage the provenance record at %s: %s"
            % (staged, err)) from err
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise TransitionError(
                    "only %d of %d bytes of the generation manifest "
                    "reached %s" % (offset, len(data), staged))
            offset += written
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        _discard_staged_manifest(staged)
        raise
    else:
        os.close(descriptor)
    try:
        os.replace(staged, target)
    except OSError as err:
        _discard_staged_manifest(staged)
        raise TransitionError(
            "could not publish the provenance record to %s: %s"
            % (target, err)) from err
    timeline.fsync_directory(parent)
    return target


def staged_manifest_path(directory: str) -> str:
    """Where the provenance record is staged before it is renamed.

    Named so that the writer, the failure paths and the stale-sibling
    sweep cannot spell it three different ways.
    """
    target = generation_manifest_path(directory)
    parent = os.path.dirname(target) or os.curdir
    return os.path.join(
        parent, ".%s.publishing" % GENERATION_MANIFEST_NAME)


def _discard_staged_manifest(path: str) -> None:
    """Remove a staged provenance record.  Best effort, never raises.

    Called on every path that leaves the staging file unpublished.  It
    must not mask the failure that brought it here, so an unlink that
    itself fails is reported and swallowed rather than raised: the
    original exception is the one an operator needs.

    ONLY A PLAIN FILE IS REMOVED, which is the same rule
    :func:`_sweep_staged_manifest` applies and for the same reason.  This
    module stages a regular file at that name; anything else there was
    put there by something else, and a module that refuses to WRITE
    through a planted symlink must not quietly DELETE one either.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as err:
        _warn("could not inspect the staged provenance record %s (%s); "
              "it may be left in the tree" % (path, err))
        return
    if not stat.S_ISREG(info.st_mode):
        _warn("%s is not a regular file, so it is left exactly as it "
              "is; this module stages a plain file there and removes "
              "nothing else" % path)
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as err:
        _warn("the staged provenance record %s could not be removed "
              "(%s); it is not a published artifact and must not be "
              "committed -- delete it before staging playthrough/"
              % (path, err))


def _sweep_staged_manifest(directory: str) -> None:
    """Clear a provenance sibling an earlier run left behind.

    THE HALF NO FAILURE PATH CAN COVER.  A run killed outright -- SIGKILL,
    the power going -- runs no handler at all, so the sibling survives
    with nobody to remove it.  It is swept at the START of a generation
    instead, under the same lock, where the file is unambiguously stale:
    this run is about to write its own.

    Only a plain file is removed, and never a symlink or a directory: the
    name is inside the committed tree, and following a link planted there
    would be exactly the write outside the tree every other path in this
    module refuses.
    """
    staged = staged_manifest_path(directory)
    try:
        info = os.lstat(staged)
    except FileNotFoundError:
        return
    except OSError as err:
        _warn("could not inspect %s (%s); a stale staged provenance "
              "record may be left in the tree" % (staged, err))
        return
    if not stat.S_ISREG(info.st_mode):
        _warn("%s exists and is not a regular file, so it is left "
              "exactly as it is; this module stages a plain file there "
              "and will not remove anything else" % staged)
        return
    _warn("a previous run left the staged provenance record %s behind "
          "(%d byte(s)); it was never published, so it is removed before "
          "this generation writes its own" % (staged, info.st_size))
    _discard_staged_manifest(staged)


def _assert_published_manifest(directory: str, text: str) -> None:
    """Confirm the published record holds exactly `text`.

    The rename is atomic with respect to a reader, which is not the same
    as verified: the file is read back and compared with the bytes that
    were staged before the journal is cleared, so the journal only ever
    disappears once the tree demonstrably holds this generation.
    """
    target = generation_manifest_path(directory)
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    found = timeline.file_digest(target)
    if found != expected:
        raise TransitionError(
            "%s was published but now carries %s rather than the %s "
            "that was staged; the generation journal is left in place so "
            "the next run finishes this publication"
            % (relative_to_repo(target), found[:16], expected[:16]))


class Result(NamedTuple):
    """What one run of :func:`make_transitions` did.

    `flagged` is how many entries asked for a transition, `groups` how
    many were composed, and `written` every path written in order.
    `flagged` and `groups` are equal on every run that RETURNS, because
    each flag composes exactly one group and the one flag that cannot --
    the malformed final-frame case -- makes plan_groups() raise
    TransitionError before anything is planned rather than composing a
    fade from the last capture back into itself.  Both are reported so
    the operator sees the identity rather than being told about it.
    """

    flagged: int
    groups: int
    written: List[str]
    removed: List[str]
    directory: str


def make_transitions(
    timeline_path: Optional[str] = None,
    transitions_dir: Optional[str] = None,
    root: Optional[str] = None,
    repo_root_dir: Optional[str] = None,
) -> Result:
    """Compose every transition the timeline asks for.

    Reads playthrough/timeline.json through timeline.read_timeline(), so
    the containment and no-symlink rules that protect the single source
    of truth apply to this reader too, composes one group per
    ``transition_after`` flag, and leaves the transitions directory
    holding exactly those groups and nothing else.

    :param timeline_path: an alternate timeline; defaults to
        ``$PLAYTHROUGH_TIMELINE`` or playthrough/timeline.json.
    :param transitions_dir: an alternate output directory, which must
        still resolve to a build/transitions inside the approved root --
        no argument can aim this module at playthrough/frames/.
    :param root: the approved artifact root; a call site's argument only,
        so a test can hold these rules against a tree it owns.
    :param repo_root_dir: the checkout the card's typeface is read from.
    :raises TransitionError: for anything that would produce imagery
        misrepresenting the session.
    """
    _require_moviepy()
    _require_numpy()
    _require_pillow()

    try:
        document = timeline.read_timeline(timeline_path, root)
    except timeline.TimelineError as err:
        raise TransitionError(
            "the timeline could not be read: %s" % err) from err
    except OSError as err:  # pragma: no cover - defensive
        raise TransitionError(
            "the timeline could not be read: %s" % err) from err

    # THE CANONICAL GATE, before a single pixel is composed.  An object,
    # zero validate_timeline() problems, and a manifest attestation that
    # matches the manifest on disk -- so this module cannot pace a film's
    # transitions from a document that fails its own invariants or that
    # describes a different session's evidence.
    try:
        timeline.assert_timeline_document(document, root)
    except timeline.TimelineError as err:
        raise TransitionError(str(err)) from err

    entries = timeline_entries(document)
    transition_seconds(document)
    geometry = expected_size()
    face = font_path(repo_root_dir)
    groups = plan_groups(entries, root)
    # The document this generation is attributed to, resolved the same way
    # read_timeline() resolved it so the digest names the file that was
    # actually read.
    source = (timeline.default_timeline_path() if timeline_path is None
              else timeline_path)

    directory = (transitions_dir if transitions_dir
                 else default_transitions_dir(root))
    directory = _validated_directory(directory, "the output directory")
    _assert_output_directory(directory, _approved_root(root))
    parent = os.path.dirname(directory)
    _ensure_directory(parent)
    _assert_replaceable(directory)

    names: List[str] = []
    for group in groups:
        names.extend(
            os.path.basename(candidate) for candidate in
            group_frame_paths(TRANSITION_STEM_FORMAT % group.frame))
    if len(set(names)) != len(names):
        raise TransitionError(
            "two flagged entries share a frame index, so their groups "
            "would overwrite each other.  Frame indices run 1..n and "
            "`manifest.py verify` reports a duplicate; the timeline "
            "should be recomputed.")

    # Everything from here to the switch happens with the lock held, so
    # a concurrent run waits for a whole generation rather than
    # interleaving with half of one.
    with timeline.ArtifactLock(LOCK_NAME, root):
        # AN INTERRUPTED PREVIOUS PUBLICATION IS REPORTED BEFORE THIS ONE
        # STARTS.  It is not an error -- this run is about to replace the
        # group set and its record with a consistent pair, which is
        # exactly the repair -- but it must not pass in silence, because
        # a mixed generation may already have been read by the renderer.
        for problem in timeline.generation_journal_problems(
                LOCK_NAME, root):
            _warn("a previous transition publication was interrupted: "
                  "%s.  This run republishes both the group set and its "
                  "provenance from the same timeline, which repairs it"
                  % problem)
        # WHAT IS THERE NOW IS INSPECTED BEFORE IT IS REPLACED.  The
        # switch below is atomic, which is what makes publication safe,
        # but atomicity alone would quietly absorb two things it must
        # not: a file matching the acceptance gate's `trans_*.png` glob
        # that this module could never have written, and a file nobody
        # wrote here at all.
        _assert_no_foreign_transition_frames(directory)
        # AND THE ONE PIECE OF LITTER THAT IS NOT IN THAT DIRECTORY.
        # _own_litter() sweeps the transitions directory; the provenance
        # record is staged BESIDE it, in playthrough/build/, so a run
        # killed between opening that file and renaming it leaves a
        # sibling no sweep covered and no failure handler ran for.  It is
        # cleared here, under this lock, where it is unambiguously stale.
        _sweep_staged_manifest(directory)
        keep = _foreign_entries(directory)
        before = _glob_names(directory)
        removed = _previous_generation(directory) + _own_litter(directory)
        staging = tempfile.mkdtemp(dir=parent, prefix=STAGING_PREFIX)
        try:
            os.chmod(staging, 0o755)
            staged: List[str] = []
            staged_by_frame: Dict[int, List[str]] = {}
            for group in groups:
                composed = compose_transition_group(
                    group.current, group.successor,
                    os.path.join(staging,
                                 TRANSITION_STEM_FORMAT % group.frame),
                    face, geometry, root, repo_root_dir)
                staged_by_frame[group.frame] = list(composed)
                staged.extend(composed)
            _assert_generation_complete(staging, staged, names)
            # THE PROVENANCE, BUILT FROM THE STAGED BYTES -- which are the
            # bytes about to be published, because the switch is a rename
            # and moves them rather than rewriting them.  It is published
            # BESIDE the directory, not inside it, so the group set holds
            # nothing but `trans_*.png`; the two are held together by the
            # journal written below rather than by sharing one rename.
            manifest_text = generation_manifest_text(
                build_generation_manifest(
                    groups, source, geometry, face, staged_by_frame))
            # THE JOURNAL, WRITTEN AND FSYNCED BEFORE THE FIRST RENAME.
            # It names both halves of this generation and the digest the
            # record must end up carrying, so an interruption between the
            # two renames is a state the next run can NAME and repair
            # instead of a directory nobody can attribute.  Absolute
            # paths deliberately: it lives in the scratch directory
            # outside the tree, it is machinery rather than committed
            # evidence, and recovery must find the exact files this run
            # meant.
            timeline.write_generation_journal(LOCK_NAME, {
                "version": timeline.GENERATION_VERSION,
                "stage": LOCK_NAME,
                "timeline": os.path.abspath(source),
                "directory": os.path.abspath(directory),
                "frames": sorted(names),
                "targets": [{
                    "path": os.path.abspath(
                        generation_manifest_path(directory)),
                    "sha256": hashlib.sha256(
                        manifest_text.encode("utf-8")).hexdigest(),
                }],
            }, root)
            # THE LAST LOOK BEFORE THE SWITCH.  The published directory
            # is re-listed and compared with what it held when the run
            # started, because the switch REPLACES it: a frame that
            # appeared while the generation was being composed would
            # otherwise be destroyed without anyone being told, and
            # destroying a file this module did not write is not
            # reconciliation.  Refusing here leaves it on disk.
            _assert_nothing_appeared(directory, before)
            # Carried across the switch, because replacing the directory
            # must not destroy a file this module never owned.
            _carry_foreign_entries(keep, staging)
            timeline.fsync_directory(staging)
            _publish_generation(staging, directory)
            # THE SECOND HALF OF THE SAME GENERATION.  The journal above
            # already names it and its digest, so an interruption here
            # leaves a group set whose record is stale -- which
            # render_movie.py refuses by digest and the next run repairs
            # -- rather than a record describing frames that are not
            # there, which would read like a complete generation.
            _publish_generation_manifest(directory, manifest_text)
        except BaseException:
            # A failed generation takes its staging directory with it and
            # leaves the published one exactly as it was.
            shutil.rmtree(staging, ignore_errors=True)
            raise
        # THE CLOSING INVENTORY, re-listing the PUBLISHED directory after
        # the switch: a frame that appeared while the generation was
        # being composed is not in the staging area and would otherwise
        # reach the acceptance gate, which globs this directory.
        _assert_published_generation(directory, names)
        _assert_published_manifest(directory, manifest_text)
        # Cleared LAST, and only once both halves are on disk carrying
        # the bytes the journal named.
        timeline.clear_generation_journal(LOCK_NAME, root)

    written = [os.path.join(directory, name) for name in
               (os.path.basename(candidate) for candidate in staged)]
    return Result(len(groups), len(groups), written, removed, directory)


def _glob_matches(name: str) -> bool:
    """True when the acceptance gate's `trans_*.png` glob matches."""
    return (name.startswith(TRANSITION_GLOB_PREFIX) and
            name.endswith(PNG_SUFFIX))


def _glob_names(directory: str) -> Set[str]:
    """The `trans_*.png` names this directory holds right now."""
    try:
        return {name for name in os.listdir(directory)
                if _glob_matches(name)}
    except OSError:
        return set()


def _assert_nothing_appeared(directory: str, before: Set[str]) -> None:
    """Refuse a transition frame that arrived during the run.

    Raised BEFORE the switch, so the published directory -- and the file
    that appeared in it -- are left exactly as they are.  The
    acceptance gate globs this directory, and a frame the timeline does
    not account for is one it will count, so it is reported rather than
    silently replaced.
    """
    appeared = sorted(_glob_names(directory) - before)
    if not appeared:
        return
    raise TransitionError(
        "%s appeared in %s while this run was composing, so it is "
        "unaccounted for by the timeline.  Publishing would have "
        "replaced the directory and destroyed it without saying so, and "
        "the acceptance gate globs `%s*%s` here, so the run is refused "
        "instead.  Nothing was published and the file is still on disk: "
        "move it aside and run again."
        % (", ".join(appeared), directory, TRANSITION_GLOB_PREFIX,
           PNG_SUFFIX))


def _assert_no_foreign_transition_frames(directory: str) -> None:
    """Refuse a `trans_*.png` this module could not have written.

    REFUSED, NOT DELETED, and not absorbed by the switch either.
    verify_artifacts.sh globs `trans_*.png` in this directory, so such a
    file WOULD be counted as a transition frame; a run that published
    over it and reported success would hand the gate a directory it
    rejects.  Deleting it is not this module's business -- removing a
    file it did not write is not reconciliation -- so the run stops and
    names it.
    """
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        return
    except OSError as err:
        raise TransitionError(
            "could not read the transitions directory %s: %s"
            % (directory, err)) from err
    for name in names:
        if not _glob_matches(name):
            continue
        target = os.path.join(directory, name)
        if os.path.islink(target) or not os.path.isfile(target):
            raise TransitionError(
                "%s matches the acceptance gate's transition glob but "
                "is not a regular file; it is refused rather than "
                "published over" % target)
        if not TRANSITION_NAME_RE.match(name):
            raise TransitionError(
                "%s matches the acceptance gate's `%s*%s` glob but not "
                "the `%s` name this module writes, so the gate would "
                "count it as a transition frame this timeline does not "
                "account for.  It is refused rather than published "
                "over, and it is not deleted: removing a file this "
                "module did not write is not reconciliation.  Move it "
                "aside and run again."
                % (target, TRANSITION_GLOB_PREFIX, PNG_SUFFIX,
                   TRANSITION_STEM_FORMAT + TRANSITION_SUFFIX_FORMAT))


def _foreign_entries(directory: str) -> List[str]:
    """Name the regular files here that this module does not own.

    Anything outside the `trans_*.png` glob -- a note left by hand, for
    instance.  Collected so the atomic switch can carry it across
    instead of destroying it.
    """
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    keep = []
    for name in names:
        if _glob_matches(name) or _is_own_litter(name):
            continue
        target = os.path.join(directory, name)
        if os.path.islink(target) or not os.path.isfile(target):
            continue
        keep.append(target)
    return keep


def _is_own_litter(name: str) -> bool:
    """True for a half-built or superseded file THIS module left behind.

    A run killed mid-composition can leave a staging frame beside the
    published ones, and a directory published by an older version of this
    module carries that version's in-directory provenance record.  Both
    are this module's own, so both are swept rather than carried across
    the switch -- which is the opposite of how a file this module never
    wrote is treated.  Carrying the legacy record would keep a
    non-`trans_*.png` entry in a directory whose schema admits none.
    """
    return (name.startswith(STAGING_PREFIX) or
            name.endswith(STAGED_FRAME_SUFFIX) or
            name == LEGACY_MANIFEST_NAME)


def _own_litter(directory: str) -> List[str]:
    """Name this module's abandoned staging files in `directory`."""
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    return [os.path.join(directory, name) for name in names
            if _is_own_litter(name) and
            os.path.isfile(os.path.join(directory, name)) and
            not os.path.islink(os.path.join(directory, name))]


def _carry_foreign_entries(paths: Iterable[str], staging: str) -> None:
    """Copy files this module does not own into the new generation."""
    for source in paths:
        destination = os.path.join(staging, os.path.basename(source))
        try:
            shutil.copy2(source, destination)
        except OSError as err:
            raise TransitionError(
                "could not carry %s into the new generation: %s.  "
                "Publishing would have destroyed a file this module "
                "did not write." % (source, err)) from err


def _assert_published_generation(
    directory: str,
    expected_names: Iterable[str],
) -> None:
    """Prove the PUBLISHED directory is exactly the planned generation.

    Re-listed after the switch, because the staged check cannot see a
    file that appeared in the published directory while the generation
    was being composed -- and the acceptance gate globs the published
    directory, not the staging one.
    """
    wanted = sorted(expected_names)
    try:
        on_disk = sorted(name for name in os.listdir(directory)
                         if _glob_matches(name))
    except OSError as err:
        raise TransitionError(
            "could not re-read the published transitions directory %s: "
            "%s" % (directory, err)) from err
    if on_disk != wanted:
        extra = sorted(set(on_disk) - set(wanted))
        missing = sorted(set(wanted) - set(on_disk))
        raise TransitionError(
            "the published transitions directory %s does not match the "
            "timeline: %d file(s) match the acceptance gate's glob and "
            "the timeline accounts for %d%s%s.  The gate counts the "
            "groups on disk against the flags, so the difference is "
            "reported rather than left for it to find."
            % (directory, len(on_disk), len(wanted),
               "; unexpected: " + ", ".join(extra) if extra else "",
               "; missing: " + ", ".join(missing) if missing else ""))


def _assert_replaceable(directory: str) -> None:
    """Refuse a destination that cannot be swapped out safely."""
    if os.path.islink(directory):
        raise TransitionError(
            "the output directory is a symbolic link: %s.  This module "
            "publishes a directory by renaming one into place, so a "
            "link here would be replaced rather than followed -- and a "
            "link is not something this pipeline ever writes."
            % directory)
    if os.path.exists(directory) and not os.path.isdir(directory):
        raise TransitionError(
            "%s exists and is not a directory" % directory)


def _previous_generation(directory: str) -> List[str]:
    """Name the transition frames the published directory holds now.

    Reported as `removed` so the run still says what it replaced.
    Nothing is unlinked here: the whole directory is retired by the
    switch, which is what makes the replacement atomic instead of a
    sequence of deletions that can be interrupted half way.
    """
    if not os.path.isdir(directory):
        return []
    try:
        names = sorted(os.listdir(directory))
    except OSError as err:
        raise TransitionError(
            "could not read %s: %s" % (directory, err)) from err
    return [os.path.join(directory, name) for name in names
            if TRANSITION_NAME_RE.match(name) or _is_own_litter(name)]


def _assert_generation_complete(
    staging: str,
    staged: Iterable[str],
    expected_names: Iterable[str],
) -> None:
    """Prove the staging directory is exactly the planned generation.

    Checked BEFORE the switch, so an incomplete or over-full generation
    is never published.  Three things must line up: what was written,
    what was planned, and what is actually on disk.
    """
    wanted = sorted(expected_names)
    written = sorted(os.path.basename(path) for path in staged)
    if written != wanted:
        raise TransitionError(
            "the frames composed do not match the frames planned: %d "
            "composed, %d planned" % (len(written), len(wanted)))
    try:
        on_disk = sorted(name for name in os.listdir(staging)
                         if TRANSITION_NAME_RE.match(name))
        every = sorted(os.listdir(staging))
    except OSError as err:
        raise TransitionError(
            "could not read the staged generation %s: %s"
            % (staging, err)) from err
    if on_disk != wanted:
        raise TransitionError(
            "the staged generation holds %d transition frame(s) but the "
            "timeline accounts for %d.  verify_artifacts.sh asserts "
            "that the groups on disk match the flags, so the mismatch "
            "is refused before it is published."
            % (len(on_disk), len(wanted)))
    unaccounted = sorted(set(every) - set(on_disk))
    if unaccounted:
        raise TransitionError(
            "the staged generation holds %s, which this module did not "
            "compose; it is refused rather than published"
            % ", ".join(unaccounted))


# ---------------------------------------------------------------------
# Command line.  A bare invocation does the pipeline's job -- read the
# timeline, compose every flagged transition, leave the directory
# describing that timeline -- so run_pipeline.sh needs no arguments to
# get the right behaviour, and every deviation has to be asked for.
# ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    parser = argparse.ArgumentParser(
        prog="make_transitions.py",
        description=(
            "Materialise the cinematic transition as PNG frames: a "
            "%ss fade to black, a %ss \"%s\" card set in the game's own "
            "%s, and a %ss fade in, composed once for every timeline "
            "entry flagged transition_after and written to %s as %d "
            "frames per group.  Writing images rather than video "
            "segments is what lets render_movie.py encode the whole "
            "film in a single ffmpeg concat pass."
            % (FADE_SECONDS, CARD_SECONDS, CARD_TEXT, FONT_REL_PATH,
               FADE_SECONDS, TRANSITIONS_REL_DIR, FRAMES_PER_GROUP)))
    parser.add_argument(
        "--timeline", default=None, metavar="PATH",
        help=("the timeline to read; defaults to $%s or "
              "<repository>/playthrough/timeline.json"
              % "PLAYTHROUGH_TIMELINE"))
    parser.add_argument(
        "--transitions-dir", default=None, metavar="PATH",
        help=("where to write the frames; defaults to $%s or "
              "<repository>/%s.  It must still resolve to a "
              "build/transitions directory inside playthrough/: no "
              "argument can aim this module at playthrough/frames/, "
              "which holds exactly one PNG per keystroke and nothing "
              "else" % (ENV_TRANSITIONS_DIR, TRANSITIONS_REL_DIR)))
    parser.add_argument(
        "--repo-root", default=None, metavar="PATH",
        help=("the checkout the card's typeface is read from; defaults "
              "to $%s or two directories above this file"
              % ENV_REPO_ROOT))
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress the summary line on success")
    return parser


def relative_to_repo(path: str) -> str:
    """Express a path relative to the checkout, for reporting.

    The summary is a machine-readable line that ends up in run logs and
    in the report, and an absolute path there discloses the filesystem
    layout of the host -- the home directory, the operator's name, the
    build root -- to every reader of an artifact that says nothing about
    them otherwise.  Repository-relative is the same information the
    reader actually needs and none of the information they do not.

    A path outside the checkout is reduced to its basename behind a
    marker, so the line stays honest about the file being elsewhere
    without naming where.
    """
    try:
        checkout = repo_root()
    except TransitionError:  # pragma: no cover - defensive
        return os.path.basename(path)
    resolved = os.path.abspath(path)
    if resolved == checkout:
        return "."
    prefix = checkout + os.sep
    if resolved.startswith(prefix):
        return resolved[len(prefix):].replace(os.sep, "/")
    return "<outside the checkout>/%s" % os.path.basename(resolved)


def _summarise(result: Result) -> str:
    """Return the one-line summary printed on success.

    Both counts are printed even though they are equal by construction,
    because the operator's job at this stage is to see that the groups
    match the flags -- and a summary that only reported one of them
    would be asking to be trusted about the other.
    """
    return ("transitions ok: %d flagged entry(ies), %d group(s), %d "
            "frame(s) each, %d file(s) written%s -> %s"
            % (result.flagged, result.groups, FRAMES_PER_GROUP,
               len(result.written),
               (", %d file(s) replaced" % len(result.removed))
               if result.removed else "",
               relative_to_repo(result.directory)))


def main(
    argv: Optional[Sequence[str]] = None,
    root: Optional[str] = None,
) -> int:
    """Run the command line and return an exit status.

    `root` is a call site's argument and nothing else: argparse never
    produces it, no environment variable reaches it, and the shell entry
    point below never passes one.  It exists so a test can hold the real
    command line -- this function, its refusals and its exit status --
    against a temporary tree it owns, instead of writing into the
    committed artifact tree, which is a session's evidence and not a
    fixture.

    :returns: 0 on success, 1 for any refusal.  argparse exits 2 on a
        command line error of its own accord.
    """
    args = build_parser().parse_args(argv)
    try:
        result = make_transitions(
            timeline_path=args.timeline,
            transitions_dir=args.transitions_dir,
            root=root,
            repo_root_dir=args.repo_root)
    except TransitionError as err:
        print("make_transitions.py: %s" % err, file=sys.stderr)
        return EXIT_FAILED
    except OSError as err:
        print("make_transitions.py: %s" % err, file=sys.stderr)
        return EXIT_FAILED
    if not args.quiet:
        print(_summarise(result))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
