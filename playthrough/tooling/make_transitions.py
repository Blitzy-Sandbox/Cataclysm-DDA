#!/usr/bin/env python3
"""Materialise the cinematic transition into PNG frames.

Whenever a frame's raw in-game delta ran past the ten-second ceiling,
playthrough/timeline.py sets ``transition_after`` on it and charges one
second of VIDEO time between that frame's window and its successor's.
This module is what fills that second: a fade to black, a card reading
"…time passes…" set in the game's own Terminus face, and a fade back in,
composed with MoviePy and written out as ordinary PNG images.

    python3 -B playthrough/tooling/make_transitions.py
    python3 -B playthrough/tooling/make_transitions.py --timeline PATH

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
That is why this module composes by concatenation, why the compositing
class is not imported at all, and why verification MEASURES the
luminance across a written group instead of trusting that the call did
what it was told.

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
playthrough/frames/ for writing.  It reads captures from there and
writes nowhere but the transitions directory -- no command line flag can
change that, because the output prefix is validated to resolve inside a
directory named build/transitions and refused anywhere else.

IDEMPOTENT AND DETERMINISTIC, BECAUSE THE ARTIFACTS ARE COMMITTED
A re-run overwrites the same paths and reconciles the directory first,
so a timeline with fewer flags than the last run leaves no stale group
behind and the group count on disk always equals the current flag count.
Nothing random and no timestamp enters an output: the same timeline over
the same captures produces the same bytes, which is what lets the movie
be reproduced from the committed inputs.

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
import os
import re
import sys

from typing import (Any, Dict, Iterable, List, NamedTuple, Optional,
                    Sequence, Tuple)

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
# this module and is therefore ours to reconcile.  Anchored, so a file
# somebody else put there is left alone and reported rather than
# deleted.
TRANSITION_NAME_RE = re.compile(r"^trans_[0-9]{5}_[0-9]{2}\.png$")

# A looser shape used only to notice a stray file that WOULD be picked
# up by verify_artifacts.sh's `trans_*.png` glob without being a frame
# this module wrote.
TRANSITION_GLOB_PREFIX = "trans_"
PNG_SUFFIX = ".png"

# The group index is ZERO-BASED: the first frame of the group after
# capture 1 is trans_00001_00.png.  Chosen once and applied everywhere,
# because the second field is an offset within the group rather than a
# count of anything.
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
    captures inside playthrough/frames/.  `self_successor` records that
    the flagged entry had no successor in the timeline and is fading
    back into itself -- see :func:`plan_groups` for why that is
    possible at all and why it is honoured rather than skipped.
    """

    frame: int
    current: str
    successor: str
    self_successor: bool


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
    if not os.path.isfile(resolved):
        raise TransitionError(
            "%s is not a regular file: %s" % (FONT_REL_PATH, resolved))
    if not os.access(resolved, os.R_OK):
        raise TransitionError(
            "%s is not readable: %s" % (FONT_REL_PATH, resolved))
    return resolved


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
    if not directory.endswith(os.sep + tail):
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

    The artifact is an object carrying the constants and totals
    alongside its `frames` array; a bare array is accepted too, because
    a caller holding just the entries in hand is a legitimate way to
    drive this module from a test, and refusing it would buy nothing.
    """
    if isinstance(document, dict):
        entries = document.get(KEY_FRAMES)
        if entries is None:
            raise TransitionError(
                "the timeline document has no '%s' array; "
                "timeline.DOCUMENT_FIELDS declares it and timeline.py "
                "always writes it" % KEY_FRAMES)
    else:
        entries = document
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

    THE FLAGGED-LAST-ENTRY CASE, DECIDED DELIBERATELY.  In a well-formed
    timeline it cannot arise: timeline.raw_deltas() gives the final frame
    a raw delta of 0.0 because it has no successor to difference
    against, timeline.is_transition() is strictly greater than the
    ceiling, and timeline.validate_timeline() reports
    'final-frame-flagged' if the last entry carries the flag anyway.  So
    reaching it means the document is malformed.

    It is honoured rather than skipped, and the frame fades back into
    ITSELF.  Two reasons.  First, the group count on disk then equals the
    flag count in the timeline unconditionally, which is exactly the
    identity verify_artifacts.sh asserts -- skipping would make that gate
    fail on a document this module had silently decided to disagree with.
    Second, a full group is the only alternative to a short one: eleven
    frames, or none, would leave render_movie.py charging a second of
    video that the images do not fill.  The anomaly is REPORTED on
    stderr, naming timeline.py's own problem code, so it is visible
    rather than absorbed.
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
            groups.append(Group(index, current, successor, False))
            continue
        _warn(
            "timeline entry %d is the last one and carries '%s'; "
            "timeline.py reports that as 'final-frame-flagged' because "
            "the final frame has no successor to transition into.  The "
            "group is still composed IN FULL, fading frame %d back into "
            "itself, so that the %d frames on disk still match the flag "
            "and nothing downstream is short of imagery.  The timeline "
            "is malformed and should be recomputed."
            % (position, KEY_TRANSITION_AFTER, index, FRAMES_PER_GROUP))
        groups.append(Group(index, current, current, True))
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


def _image_size(path: str) -> Tuple[int, int]:
    """Return a PNG's (width, height) without decoding its pixels."""
    _require_pillow()
    try:
        with Image.open(path) as handle:
            return int(handle.width), int(handle.height)
    except OSError as err:
        raise TransitionError(
            "%s could not be read as an image: %s" % (path, err)) from err


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

    The index is zero-based, so the first frame of the group following
    capture 1 is trans_00001_00.png -- chosen once and applied
    everywhere, because the second field is an offset within the group
    rather than a count of anything.
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
    _assert_capture_size(source, geometry)
    _assert_capture_size(target, geometry)

    paths = group_frame_paths(prefix)
    clips: List[Any] = []
    segment = None
    try:
        # The composition, exactly as the plan fixes it.  Effects are
        # v2 classes handed to with_effects([...]); CONCATENATED rather
        # than composited, because a cross-fade applied through the
        # compositing clip class renders WITHOUT the fade and reports
        # nothing at all.
        clips = [
            ImageClip(source).with_duration(FADE_SECONDS)
            .with_effects([vfx.FadeOut(FADE_SECONDS)]),
            title_card(face, geometry, CARD_SECONDS),
            ImageClip(target).with_duration(FADE_SECONDS)
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
        frames = list(segment.iter_frames(fps=FPS))
    except TransitionError:
        raise
    except (OSError, ValueError, TypeError) as err:
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

    if len(frames) != FRAMES_PER_GROUP:
        raise TransitionError(
            "the composed segment yielded %d frame(s) at %d fps, not "
            "the %d a %ss transition must be.  verify_artifacts.sh "
            "counts groups against the timeline's flags and "
            "render_movie.py charges exactly %ss of video per group, so "
            "a different count would desynchronise the captions."
            % (len(frames), FPS, FRAMES_PER_GROUP, EXPECTED_TRANSITION,
               EXPECTED_TRANSITION))

    for ordinal, (frame, path) in enumerate(zip(frames, paths)):
        _write_png(_frame_to_rgb8(frame, ordinal), path)
        _assert_written(path, geometry)
    return paths


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


def reconcile_transitions_dir(
    directory: str,
    expected: Iterable[str],
) -> List[str]:
    """Remove transition frames the current timeline does not account for.

    Only names this module writes are touched -- `trans_*.png` -- and
    only regular files: a symlink or a subdirectory is reported and left
    alone rather than followed or removed, because deleting through a
    link is how a reconciliation turns into a loss.  Anything else
    somebody put in the directory is left alone too, and a file matching
    the glob that this module did not write is named on stderr, since
    verify_artifacts.sh's own `trans_*.png` glob would otherwise count it
    as a frame.

    :returns: the paths removed, sorted, so the caller can report them.
    """
    keep = {os.path.basename(path) for path in expected}
    removed: List[str] = []
    try:
        names = sorted(os.listdir(directory))
    except OSError as err:
        raise TransitionError(
            "could not read %s: %s" % (directory, err)) from err
    for name in names:
        if name in keep:
            continue
        if not (name.startswith(TRANSITION_GLOB_PREFIX) and
                name.endswith(PNG_SUFFIX)):
            continue
        path = os.path.join(directory, name)
        if os.path.islink(path) or not os.path.isfile(path):
            _warn(
                "%s matches the transition glob but is not a regular "
                "file; it is left in place, and verify_artifacts.sh "
                "will count it" % path)
            continue
        if not TRANSITION_NAME_RE.match(name):
            _warn(
                "%s matches the transition glob but not the %s this "
                "module writes; it is left in place, and "
                "verify_artifacts.sh will count it"
                % (path, TRANSITION_NAME_FORMAT))
            continue
        try:
            os.unlink(path)
        except OSError as err:
            raise TransitionError(
                "could not remove the stale transition frame %s: %s.  "
                "It belongs to a previous run and would be counted "
                "against this timeline's flags."
                % (path, err)) from err
        removed.append(path)
    return removed


class Result(NamedTuple):
    """What one run of :func:`make_transitions` did.

    `flagged` is how many entries asked for a transition, `groups` how
    many were composed, and `written` every path written in order.
    `flagged` and `groups` are equal by construction -- every flag is
    honoured, including the malformed final-frame case -- and both are
    reported so the operator sees the identity rather than being told
    about it.
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

    entries = timeline_entries(document)
    transition_seconds(document)
    geometry = expected_size()
    face = font_path(repo_root_dir)
    groups = plan_groups(entries, root)

    directory = (transitions_dir if transitions_dir
                 else default_transitions_dir(root))
    directory = _validated_directory(directory, "the output directory")
    _assert_output_directory(directory, _approved_root(root))
    _ensure_directory(directory)

    prefixes = [os.path.join(directory,
                             TRANSITION_STEM_FORMAT % group.frame)
                for group in groups]
    expected: List[str] = []
    for prefix in prefixes:
        expected.extend(group_frame_paths(prefix))
    if len(set(expected)) != len(expected):
        raise TransitionError(
            "two flagged entries share a frame index, so their groups "
            "would overwrite each other.  Frame indices run 1..n and "
            "`manifest.py verify` reports a duplicate; the timeline "
            "should be recomputed.")

    removed = reconcile_transitions_dir(directory, expected)
    written: List[str] = []
    for group, prefix in zip(groups, prefixes):
        written.extend(compose_transition_group(
            group.current, group.successor, prefix, face, geometry,
            root, repo_root_dir))

    if written != expected:
        raise TransitionError(
            "the frames written do not match the frames planned: %d "
            "written, %d planned" % (len(written), len(expected)))
    on_disk = sorted(
        name for name in os.listdir(directory)
        if TRANSITION_NAME_RE.match(name))
    if on_disk != sorted(os.path.basename(path) for path in expected):
        raise TransitionError(
            "%s holds %d transition frame(s) after the run but the "
            "timeline accounts for %d.  verify_artifacts.sh asserts "
            "that the groups on disk match the flags, so the mismatch "
            "is refused here." % (directory, len(on_disk), len(expected)))
    return Result(len(groups), len(groups), written, removed, directory)


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
               (", %d stale file(s) removed" % len(result.removed))
               if result.removed else "",
               result.directory))


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
