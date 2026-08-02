#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/capture.sh
#
# ONE keystroke, ONE screenshot, ONE clock reading.
#
# This is the capture step of the playthrough pipeline's loop --
# observe, decide in character, act, capture, log.  A single invocation
# lets the frame settle, photographs the X ROOT window into
# playthrough/frames/frame_%05d.png, and reads the sidebar clock out of
# the pixels it has just written.  It captures one frame for one key
# and returns.  It never loops over keys and it never sends one:
# session.py owns the keystroke and the frame counter, this file owns
# the photograph.
#
# THE HELPER THIS FILE IMPLEMENTS
# The capture helper was specified as:
#
#     sleep 0.3   # let the frame settle
#     i=$(printf "%05d" "$FRAME_INDEX")
#     import -window root "playthrough/frames/frame_${i}.png"
#     CLOCK=$(convert "playthrough/frames/frame_${i}.png" \
#             -crop <sidebar region> png:- \
#             | tesseract stdin stdout | grep -Eo '<time/turn readout>')
#
# Every element of it survives below, in the same order.  Only the two
# placeholders are resolved, and both resolve from evidence in this
# repository rather than from guesswork:
#
#   <sidebar region>     -> 288x1072+1632+4 for the configuration this
#                           pipeline runs under, being the sidebar's
#                           "width": 36 cells [data/json/ui/
#                           sidebar.json:7, inside the custom_sidebar
#                           widget] times FONT_WIDTH 8, right-aligned
#                           because SIDEBAR_POSITION defaults to
#                           "right" [src/options.cpp, the sidb_opts
#                           group], over a window whose size is
#                           WindowWidth = TERMINAL_WIDTH * fontwidth *
#                           scaling_factor [src/sdltiles.cpp:595-596].
#                           That value is COMPUTED at run time by
#                           sidebar_geometry.py and appears as a
#                           literal here only in this comment and in
#                           one clearly labelled last-resort fallback.
#
#   <time/turn readout>  -> [0-9]{2}:[0-9]{2}:[0-9]{2}, the fixed-width
#                           form to_string_time_of_day() emits under
#                           24_HOUR=24h [src/calendar.cpp:649].  The
#                           other two branches would defeat it:
#                           "military" renders 0815.32
#                           [src/calendar.cpp:646] and the shipped
#                           "12h" default renders 8:15:32 AM with
#                           variable padding [src/calendar.cpp:
#                           657-661].  seed_options.py selects 24h for
#                           exactly this reason.
#
# The chain also gains the preprocessing the sketch omitted --
# `+repage -colorspace Gray -resize 200% -normalize` -- because 8x16
# terminal glyphs are illegible to tesseract at native size, and with
# it a real captured frame read back exactly 08:15:32.  Nothing is
# dropped and nothing is reordered.
#
# WHY THE ROOT WINDOW, DELIBERATELY
# `import -window root`, never the game window.  The X root is exactly
# 1920x1080 while the game window occupies 1920x1072 at +0+4 (240
# columns x 8 px by 67 rows x 16 px).  Photographing the root yields a
# true-resolution PNG with a thin four-pixel letterbox and needs NO
# rescaling -- and rescaling would soften precisely the 8x16 glyphs the
# clock read depends on.  Capturing the game window instead would
# produce a 1920x1072 frame that something downstream would have to
# resample back up.
#
# IMAGEMAGICK: import / convert / identify, NEVER the unified entry
# point.  The legacy commands exist on both the 6.x and 7.x branches,
# whereas the version-7 entry point does not exist on 6.x at all --
# where this pipeline is specified to run -- so code written against
# version-7 examples fails there with command-not-found.
#
# USAGE
#     FRAME_INDEX=<n> playthrough/tooling/capture.sh
#     playthrough/tooling/capture.sh --help
#
# THE INDEX IS AN INPUT, NEVER AN INVENTION
# FRAME_INDEX is the ONLY input and it is required.  session.py is the
# sole owner of the monotonic frame counter; this file receives an
# index and must never derive, default, guess or increment one.  It is
# deliberately not counted off the frames directory: that would be a
# second source of truth and a retry could silently renumber a frame.
#
# STDOUT IS A MACHINE CONTRACT
# Every line printed on stdout is KEY=value, one per line, and nothing
# else is ever written there; all logging, warnings and diagnostics go
# to stderr, which also keeps engineering observations out of the
# in-character record.  A caller reads a field with
#
#     out="$(FRAME_INDEX=42 playthrough/tooling/capture.sh)"
#     clock="$(printf '%s\n' "${out}" | sed -n 's/^CLOCK=//p')"
#
# The keys, always in this order:
#
#     FRAME_INDEX     the index exactly as validated
#     FRAME_NAME      frame_%05d.png
#     FRAME_FILE      playthrough/frames/frame_%05d.png -- repository
#                     relative, and byte-identical to manifest.py's
#                     `file` field, which is built from the same format
#     FRAME_PATH      the same frame, absolute
#     FRAME_BYTES     size on disk, so a truncated write is visible
#     FRAME_FORMAT    the image format identify reports (PNG)
#     FRAME_GEOMETRY  WxH as captured; asserted against the contract
#     REAL_TS         UTC instant of the grab, in the manifest's own
#                     real_ts form (canonical_real_ts() documents
#                     accepting exactly this `date` output)
#     CAPTURE_TOOL    import, or scrot when import is unavailable
#     LUMA_MEAN       grayscale mean of the frame
#     LUMA_STDDEV     grayscale standard deviation of the frame
#     CLOCK_RECT      the crop rectangle actually used
#     CLOCK_RECT_FROM computed | override | fallback
#     CLOCK_SOURCE    ocr_clock.py | inline | none
#     CLOCK_STATUS    read | unreadable | fault | skipped
#     CLOCK           the reading, VERBATIM, or empty when there was
#                     none.  Never interpolated, never carried forward
#                     from another frame, never guessed
#     TIME_PHRASE     the coarse phrase the sidebar showed instead of a
#                     clock, verbatim, or empty
#
# EXIT CODES
#     0  one frame captured and this invocation's output is complete
#     1  usage error -- a missing, malformed or out-of-range index
#     2  layout error -- not inside a checkout, or env.sh is missing
#     3  the capture failed, or produced something that is not a frame
#     4  the frame is blank -- the black-movie guard fired
#     5  no usable display at the contracted geometry, or a frame that
#        is not that geometry
#     6  the clock read hit a FAULT rather than an unreadable clock
#     7  refusing to overwrite an existing frame at this index
#     8  a prerequisite command is missing
#
# THE INVARIANT THIS FILE GUARANTEES
#     exit 0  <=>  exactly one NEW PNG in playthrough/frames/
# On any failure the frames directory is left exactly as it was found:
# a frame this invocation wrote is withdrawn to a diagnostic directory
# outside the working tree, and a pre-existing frame moved aside is put
# back.  session.py therefore cannot append a manifest row for a frame
# that does not exist, and the frames-count == manifest-line-count
# identity that verify_artifacts.sh asserts cannot be broken by a
# failed capture.  Derived imagery -- the transition frames -- belongs
# to playthrough/build/transitions/ and is never written here, which is
# what keeps that identity meaningful.
#
# TUNABLES -- all optional, all read from the environment
#     PLAYTHROUGH_CAPTURE_SETTLE     settle seconds
#                                    (default $PLAYTHROUGH_SETTLE_SECONDS)
#     PLAYTHROUGH_CAPTURE_CLOCK      on | off      (default on)
#     PLAYTHROUGH_CAPTURE_PHRASE     auto | off | always  (default auto:
#                                    read the coarse phrase only when
#                                    there was no clock to read)
#     PLAYTHROUGH_CAPTURE_STRICT_CLOCK  1 | 0      (default 1: a clock
#                                    FAULT is fatal, because the two
#                                    faults that actually happen -- an
#                                    off-contract 24_HOUR and an absent
#                                    OCR toolchain -- would poison every
#                                    later frame while every count
#                                    still tallied)
#     PLAYTHROUGH_CAPTURE_OVERWRITE  0 | 1         (default 0)
#     PLAYTHROUGH_CAPTURE_RECT       an explicit WxH+X+Y crop
#     PLAYTHROUGH_CAPTURE_REJECT_DIR where a withdrawn frame is kept
#     CLONE_INDEX                    read by env.sh; offsets the
#                                    display and every host-global
#                                    scratch path so parallel checkouts
#                                    cannot capture each other's screens
#
# THIS FILE MODIFIES NOTHING OUTSIDE playthrough/frames/.  It sends no
# keystroke, writes no manifest row, touches no save data, starts no
# server, makes no network call, and never runs a command through a
# shell string: every external call is an argument list, there is no
# eval, and there is no unquoted glob.
# ---------------------------------------------------------------------

set -euo pipefail

# errtrace propagates the ERR trap into functions, which turns an
# unexpected failure into a reported line number instead of silence.
# It is a strict addition to `set -euo pipefail`, never a replacement.
set -o errtrace

# The handler is a function so the trap string stays trivial; a
# multi-line single-quoted trap body would embed a literal backslash
# rather than continuing the line.
#
# SC2317 ("command appears to be unreachable") fires on every
# trap-invoked function in this file, because ShellCheck sees no direct
# call site: the caller is the trap, which it does not model.  The
# suppression is scoped to the three handlers that are genuinely reached
# only that way -- nothing else in this file is exempted -- and the same
# directive is used for the same reason in env.sh.
# shellcheck disable=SC2317
_cap_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "capture.sh failed at line ${2} (exit ${1})" >&2
}
trap '_cap_on_error "$?" "${LINENO}"' ERR

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8, as launch_game.sh also adopts it.
# ---------------------------------------------------------------------
_cap_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_cap_script_dir}" ]; then
    printf '%s\n' "capture.sh: FATAL: cannot resolve my own \
directory" >&2
    exit 2
fi

_cap_env_file="${_cap_script_dir}/env.sh"
if [ ! -f "${_cap_env_file}" ]; then
    printf '%s\n' "capture.sh: FATAL: missing ${_cap_env_file}; the \
headless contract and the artifact layout are defined there and are \
never redefined here" >&2
    exit 8
fi

# env.sh is the SINGLE definition of DISPLAY, SDL_VIDEODRIVER (x11 --
# and the dummy VIDEO backend is banned there and here), SDL_AUDIODRIVER,
# LIBGL_ALWAYS_SOFTWARE, XDG_RUNTIME_DIR and every artifact path.  None
# of it is restated in this file.  Sourcing it also defines the helpers
# used below: playthrough_log, playthrough_warn,
# playthrough_require_tools, playthrough_assert_video_driver and
# playthrough_assert_display.
#
# The `source=` directive lets `shellcheck -x` follow env.sh and check
# every helper and variable used here against it.  SC1091 is suppressed
# only for a plain `shellcheck` run, which cannot follow a sourced file
# at all and would otherwise report the resolved path as unreadable;
# the file's presence is asserted immediately above, so nothing is
# being hidden.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_cap_env_file}"; then
    printf '%s\n' "capture.sh: FATAL: ${_cap_env_file} refused to \
load; fix the environment contract before capturing anything" >&2
    exit 8
fi
unset _cap_script_dir _cap_env_file

# The working directory is the repository root, as it is for every
# stage of this pipeline: --userdir is normalised but not absolutised
# [src/path_info.cpp:105] and the asset roots are working-directory
# relative [src/path_info.cpp:129-136], so the root is the only place
# under which this checkout's own data/ and gfx/ resolve AND the
# artifacts land inside the working tree.  FRAME_FILE below is
# repository-relative and is only correct from here.
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# Exit codes, named so the call sites read as intent.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_LAYOUT=2
readonly EX_CAPTURE=3
readonly EX_BLANK=4
readonly EX_GEOMETRY=5
readonly EX_CLOCK_FAULT=6
readonly EX_EXISTS=7
readonly EX_PREREQ=8

# ---------------------------------------------------------------------
# Constants.
#
# CLOCK_PATTERN is the ONE definition of the readout in this file, and
# it is character-for-character ocr_clock.py's CLOCK_RE, so the
# delegated read and the fallback read cannot disagree about what a
# clock looks like.  It is deliberately unanchored: it is searched for
# inside OCR text that also holds the rest of the sidebar.
# ---------------------------------------------------------------------
readonly CLOCK_PATTERN='[0-9]{2}:[0-9]{2}:[0-9]{2}'

# The engine cannot render an hour past 23, a minute past 59 or a
# second past 59, so a match outside those bounds is not a clock.  This
# is not pedantry: whole-column OCR of this sidebar has been measured
# returning 48:48:48 and 88:48:48 -- readings that match the pattern
# and are impossible.  They are DECLINED here, never repaired, because
# emitting one would be fabrication.
readonly MAX_HOUR=23
readonly MAX_MINUTE=59
readonly MAX_SECOND=59

# manifest.py refuses an index that would widen the five-digit field
# (MIN_FRAME_INDEX / MAX_FRAME_INDEX), so this file refuses it too
# rather than formatting something the manifest will not accept.  The
# 5-digit zero-padded field is what keeps a lexical sort of the frames
# identical to a numeric one, which is what makes the ffmpeg concat
# list trivially correct.
readonly MIN_FRAME_INDEX=1
readonly MAX_FRAME_INDEX=99999

# The crop rectangle for the contracted configuration, used ONLY if
# sidebar_geometry.py cannot be run at all, and announced loudly on
# stderr when it is.  It is a clearly labelled last resort and never
# the primary path: the rectangle is computed, because nine
# sidebar*.json presets ship in data/json/ui/ at eight distinct widths
# and a hard-coded rectangle would crop the wrong column SILENTLY the
# moment the layout changed.  Cropping the wrong column cannot
# fabricate a reading -- the pattern simply stops matching -- so the
# worst case here is an honest "unreadable", never a wrong clock.
readonly FALLBACK_RECT='288x1072+1632+4'

# An ImageMagick geometry, and a bare non-negative decimal number as
# ImageMagick's fx: operators print one.  The numeric guard matters:
# awk compares a non-numeric string against 0 as STRINGS, so "nan" > 0
# would be true and a blank frame could pass the luminance gate.
readonly GEOMETRY_RE='^[0-9]+x[0-9]+\+[0-9]+\+[0-9]+$'
readonly NUMBER_RE='^[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$'

# manifest.py's real_ts form: UTC, millisecond precision, "Z"-suffixed,
# e.g. 2026-05-14T09:12:03.481Z.  Asserted rather than assumed because
# %3N is a GNU date extension and a shell that lacks it leaves the
# format specifier in the output, which would be a fabricated instant.
readonly REAL_TS_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}\.[0-9]{3}Z$'

# Delegates.  Both live beside this file; neither is duplicated here.
readonly GEOMETRY_SCRIPT="${PLAYTHROUGH_TOOLING_DIR}/sidebar_geometry.py"
readonly OCR_SCRIPT="${PLAYTHROUGH_TOOLING_DIR}/ocr_clock.py"

# ---------------------------------------------------------------------
# Tunables, resolved once.
#
# The settle comes from env.sh so a single edit moves every stage.  DO
# NOT TRIM IT AS DEAD TIME: the game redraws asynchronously, and
# capturing before the redraw lands photographs the PREVIOUS frame,
# which shifts every clock reading by one keystroke and quietly
# mis-times the whole movie.
# ---------------------------------------------------------------------
SETTLE="${PLAYTHROUGH_CAPTURE_SETTLE:-${PLAYTHROUGH_SETTLE_SECONDS}}"
CLOCK_MODE="${PLAYTHROUGH_CAPTURE_CLOCK:-on}"
PHRASE_MODE="${PLAYTHROUGH_CAPTURE_PHRASE:-auto}"
STRICT_CLOCK="${PLAYTHROUGH_CAPTURE_STRICT_CLOCK:-1}"
OVERWRITE="${PLAYTHROUGH_CAPTURE_OVERWRITE:-0}"
RECT_OVERRIDE="${PLAYTHROUGH_CAPTURE_RECT:-}"

if [ "${PLAYTHROUGH_CLONE_INDEX}" -eq 0 ]; then
    _cap_suffix=""
else
    _cap_suffix="${PLAYTHROUGH_CLONE_INDEX}"
fi
# Withdrawn frames are kept OUTSIDE the working tree.  Inside it they
# would be re-included by the terminal `!/playthrough/**` negation in
# .gitignore and could be committed as if they were session frames.
_cap_reject="${TMPDIR:-/tmp}/playthrough-rejected${_cap_suffix}"
REJECT_DIR="${PLAYTHROUGH_CAPTURE_REJECT_DIR:-${_cap_reject}}"
unset _cap_suffix _cap_reject

# ---------------------------------------------------------------------
# Reporting.
#
# die() does not call env.sh's playthrough_die: that function RETURNS 1
# by design, because env.sh is sourced and an `exit` there would kill an
# interactive caller's shell.  Here an exit with a specific, documented
# code is exactly what is wanted, so the message is printed directly in
# the same format.  The EXIT trap installed below withdraws the frame.
# ---------------------------------------------------------------------
die() {
    local code="$1"
    shift
    printf 'playthrough: FATAL: %s\n' "$*" >&2
    exit "${code}"
}

# emit KEY VALUE -- the machine-readable channel, and the only thing
# this script ever writes to stdout.
emit() {
    printf '%s=%s\n' "$1" "$2"
}

usage() {
    # The one place this file writes prose to stdout, and only when
    # explicitly asked for help.
    cat <<'USAGE'
capture.sh -- one keystroke, one screenshot, one clock reading.

usage:
    FRAME_INDEX=<n> playthrough/tooling/capture.sh
    playthrough/tooling/capture.sh --help

FRAME_INDEX is required and must be a plain decimal integer from 1 to
99999 with no sign, no leading zero and no surrounding space.  It is
supplied by session.py, which owns the frame counter; this script never
derives one.

Writes exactly one playthrough/frames/frame_%05d.png, prints KEY=value
lines on stdout and everything else on stderr.  See the header of this
file for the full output contract, the exit codes and the tunables.
USAGE
}

# ---------------------------------------------------------------------
# The frames-directory guarantee.
#
# GRABBED becomes 1 the instant a PNG this invocation wrote is in place,
# and KEPT becomes 1 only once the frame has passed every check and is
# ours to keep.  The EXIT trap withdraws anything grabbed but not kept,
# and restores anything that was moved aside, so a non-zero exit always
# leaves playthrough/frames/ exactly as it was found.
#
# That is what makes `exit 0 <=> exactly one new frame` structural
# rather than merely intended, and it is why session.py can treat a
# successful return as licence to append exactly one manifest row.
# ---------------------------------------------------------------------
GRABBED=0
KEPT=0
BACKUP=""
FRAME_PATH=""

# Reached only from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
withdraw() {
    local target
    if [ "${GRABBED}" -eq 1 ] && [ -e "${FRAME_PATH}" ]; then
        # Keep the rejected frame: it is the evidence of whatever went
        # wrong.  Outside the working tree, so it can never be
        # mistaken for -- or committed as -- a session frame.
        target="${REJECT_DIR}/$(basename "${FRAME_PATH}")"
        if mkdir -p "${REJECT_DIR}" 2>/dev/null &&
           mv -f "${FRAME_PATH}" "${target}" 2>/dev/null; then
            playthrough_warn "withdrew ${FRAME_PATH} from the frames" \
                "directory and kept it at ${target} for inspection"
        else
            rm -f "${FRAME_PATH}" 2>/dev/null || true
            playthrough_warn "withdrew and discarded ${FRAME_PATH};" \
                "${REJECT_DIR} could not be written"
        fi
    fi
    GRABBED=0
    if [ -n "${BACKUP}" ] && [ -e "${BACKUP}" ]; then
        if mv -f "${BACKUP}" "${FRAME_PATH}" 2>/dev/null; then
            playthrough_warn "restored the frame that was already at" \
                "${FRAME_PATH}"
        else
            playthrough_warn "could not restore ${BACKUP} to" \
                "${FRAME_PATH}; the earlier frame is still at" \
                "${BACKUP}"
        fi
    fi
    BACKUP=""
}

# Reached only from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
_cap_on_exit() {
    if [ "$1" -ne 0 ] && [ "${KEPT}" -eq 0 ]; then
        withdraw
    fi
}
trap '_cap_on_exit "$?"' EXIT

# ---------------------------------------------------------------------
# Arguments.  There is exactly one input -- FRAME_INDEX in the
# environment -- so the only accepted argument is a request for help.
# Anything else is a usage error rather than something to interpret.
# ---------------------------------------------------------------------
if [ "$#" -gt 0 ]; then
    case "$1" in
        -h|--help|help)
            usage
            exit "${EX_OK}"
            ;;
        *)
            printf 'playthrough: FATAL: %s\n' \
                "capture.sh takes no arguments; the frame index is \
passed as FRAME_INDEX in the environment.  Got: $*" >&2
            usage >&2
            exit "${EX_USAGE}"
            ;;
    esac
fi

# ---------------------------------------------------------------------
# Validate the index STRICTLY.  It is not defaulted, not derived and
# not coerced.
#
# The pattern is ^[1-9][0-9]*$, and excluding a leading zero is
# load-bearing rather than fussy: bash's printf parses a zero-prefixed
# argument as OCTAL.  Measured on this host, `printf '%05d' 010` prints
# 00008 -- frame 10 would be filed as frame 8, overwriting it -- and
# `printf '%05d' 09` fails outright with "invalid octal number".  Both
# outcomes corrupt the one-frame-per-keystroke identity, and the second
# would do it noisily while the first would do it in silence.
# ---------------------------------------------------------------------
if [ -z "${FRAME_INDEX:-}" ]; then
    printf 'playthrough: FATAL: %s\n' \
        "FRAME_INDEX is not set.  session.py owns the frame counter \
and passes the index in; this script never invents one." >&2
    exit "${EX_USAGE}"
fi

# A single anchored regular expression, so nothing can slip past on a
# glob subtlety: no sign, no leading zero, no space, no digit group
# separator, no trailing character of any kind.
if ! [[ "${FRAME_INDEX}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'playthrough: FATAL: %s\n' \
        "FRAME_INDEX='${FRAME_INDEX}' is not a plain positive decimal \
integer.  A sign, a leading zero, whitespace or any other character is \
refused: bash printf reads '010' as octal 8 and would file frame 10 \
over frame 8, silently." >&2
    exit "${EX_USAGE}"
fi

if [ "${FRAME_INDEX}" -lt "${MIN_FRAME_INDEX}" ] ||
   [ "${FRAME_INDEX}" -gt "${MAX_FRAME_INDEX}" ]; then
    printf 'playthrough: FATAL: %s\n' \
        "FRAME_INDEX=${FRAME_INDEX} is outside ${MIN_FRAME_INDEX}..\
${MAX_FRAME_INDEX}.  manifest.py refuses an index that would widen the \
five-digit field, and a wider field would break the lexical sort the \
concat list depends on." >&2
    exit "${EX_USAGE}"
fi

# ---------------------------------------------------------------------
# The one canonical filename.
#
# PLAYTHROUGH_FRAME_FORMAT is env.sh's 'frame_%05d.png' and is the same
# format manifest.py builds its `file` field from, so the capture, the
# manifest row and the concat list agree byte for byte.  `printf --`
# guards against a format that begins with a dash.
#
# SC2059 objects to a variable used as a printf format.  Here that is
# the entire point: the format is env.sh's single definition, shared
# with manifest.py, and inlining a second copy of '%05d' is exactly the
# divergence this indirection exists to prevent.  The expansion is
# asserted immediately below.
# ---------------------------------------------------------------------
# shellcheck disable=SC2059
FRAME_NAME="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}" "${FRAME_INDEX}")"
FRAME_PATH="${PLAYTHROUGH_FRAMES_DIR}/${FRAME_NAME}"
FRAME_FILE="playthrough/frames/${FRAME_NAME}"

if [ "${FRAME_NAME}" = "${PLAYTHROUGH_FRAME_FORMAT}" ]; then
    die "${EX_LAYOUT}" "PLAYTHROUGH_FRAME_FORMAT=\
'${PLAYTHROUGH_FRAME_FORMAT}' did not expand; env.sh must supply a \
printf format containing %05d"
fi

# ---------------------------------------------------------------------
# Validate the tunables.  A typo must not silently disable a guard --
# PLAYTHROUGH_CAPTURE_CLOCK=of would otherwise read as "not off".
# ---------------------------------------------------------------------
case "${CLOCK_MODE}" in
    on|off) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_CLOCK=\
'${CLOCK_MODE}' is neither 'on' nor 'off'" ;;
esac
case "${PHRASE_MODE}" in
    auto|off|always) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_PHRASE=\
'${PHRASE_MODE}' is not one of auto, off, always" ;;
esac
case "${STRICT_CLOCK}" in
    0|1) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=\
'${STRICT_CLOCK}' is neither 0 nor 1" ;;
esac
case "${OVERWRITE}" in
    0|1) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_OVERWRITE=\
'${OVERWRITE}' is neither 0 nor 1" ;;
esac
if ! [[ "${SETTLE}" =~ ${NUMBER_RE} ]]; then
    die "${EX_USAGE}" "the settle is '${SETTLE}', which is not a \
non-negative number of seconds; env.sh supplies \
PLAYTHROUGH_SETTLE_SECONDS and PLAYTHROUGH_CAPTURE_SETTLE overrides it"
fi
if [ -n "${RECT_OVERRIDE}" ] &&
   ! [[ "${RECT_OVERRIDE}" =~ ${GEOMETRY_RE} ]]; then
    die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_RECT=\
'${RECT_OVERRIDE}' is not an ImageMagick WxH+X+Y geometry"
fi

# ---------------------------------------------------------------------
# Preflight.
#
# The capturer is `import -window root`; scrot is the documented
# fallback and is used only when import is absent.  Both photograph the
# whole root window, which is the point.
# ---------------------------------------------------------------------
if command -v import >/dev/null 2>&1; then
    CAPTURE_TOOL="import"
elif command -v scrot >/dev/null 2>&1; then
    CAPTURE_TOOL="scrot"
    playthrough_warn "ImageMagick's import is not installed; falling" \
        "back to scrot.  Both grab the X root window, so the frame is" \
        "equivalent, but import is the contracted capturer."
else
    die "${EX_PREREQ}" "no screen capturer: neither ImageMagick's \
import nor scrot is installed.  See the apt list in \
playthrough/tooling/requirements.txt."
fi

# convert and identify are needed unconditionally: identify proves the
# frame is a PNG at the contracted geometry and convert measures its
# luminance, which is the guard against a silently black session.
playthrough_require_tools convert identify || exit "${EX_PREREQ}"

# tesseract is needed by BOTH clock-read paths, so its absence is a
# prerequisite failure rather than an unreadable clock.
if [ "${CLOCK_MODE}" = "on" ]; then
    playthrough_require_tools tesseract || exit "${EX_PREREQ}"
fi

# The cheap, loud guard against the one completely silent failure mode
# of this pipeline: the dummy VIDEO backend renders zero pixels, so the
# game runs, the keystrokes land, this script writes a PNG, ffmpeg
# encodes, every count tallies -- and the movie shows nothing.  env.sh
# asserts this at source time as well; asserting it again here costs one
# string comparison and documents the dependency at the point of use.
playthrough_assert_video_driver || exit "${EX_LAYOUT}"

# The root window must be the contracted geometry BEFORE the grab, so a
# wrong-sized display is reported as such instead of surfacing later as
# a mysteriously wrong-resolution movie.
playthrough_assert_display || exit "${EX_GEOMETRY}"

# ---------------------------------------------------------------------
# Prepare the destination.  Only playthrough/frames/ is created: the
# build and transition directories belong to other stages, and
# env.sh's playthrough_mkdirs is deliberately NOT used here, because
# this file's blast radius is one directory.
# ---------------------------------------------------------------------
if ! mkdir -p "${PLAYTHROUGH_FRAMES_DIR}"; then
    die "${EX_CAPTURE}" "cannot create ${PLAYTHROUGH_FRAMES_DIR}"
fi

# Refusing to clobber is a guard on the 1:1 invariant, not politeness:
# a frame already sitting at this index means the counter has repeated,
# and overwriting would leave the frames count one short of the
# keystroke count with nothing to show that it happened.
if [ -e "${FRAME_PATH}" ]; then
    if [ "${OVERWRITE}" -ne 1 ]; then
        die "${EX_EXISTS}" "${FRAME_PATH} already exists.  A repeated \
index means the frame counter went backwards, which would break the \
one-frame-per-keystroke identity.  Set \
PLAYTHROUGH_CAPTURE_OVERWRITE=1 only if you mean to recapture this \
index deliberately."
    fi
    _cap_backup="${REJECT_DIR}/superseded-${FRAME_NAME}"
    if mkdir -p "${REJECT_DIR}" 2>/dev/null &&
       mv -f "${FRAME_PATH}" "${_cap_backup}" 2>/dev/null; then
        BACKUP="${_cap_backup}"
        playthrough_warn "recapturing ${FRAME_FILE}; the earlier frame" \
            "was moved to ${BACKUP} and is restored if this capture" \
            "does not succeed"
    else
        die "${EX_CAPTURE}" "cannot move the existing ${FRAME_PATH} \
aside into ${REJECT_DIR}; refusing to overwrite it in place"
    fi
    unset _cap_backup
fi

# ---------------------------------------------------------------------
# THE SETTLE.  0.3 seconds, from env.sh.
#
# DO NOT REMOVE THIS AND DO NOT SHORTEN IT AS DEAD TIME.  The game
# redraws asynchronously after a keystroke; grabbing too early
# photographs the screen as it was BEFORE the key landed.  The frame
# would still be a real screenshot and every count would still tally,
# so nothing would fail -- every clock reading would simply be one
# keystroke stale, and the whole film would be mis-timed by one step.
# ---------------------------------------------------------------------
sleep "${SETTLE}"

# The wall-clock instant of the grab, in the manifest's own real_ts
# form: UTC, millisecond precision, "Z"-suffixed.  manifest.py's
# canonical_real_ts() documents accepting exactly this `date` output, so
# session.py can pass it straight through and the row records when the
# shutter actually opened rather than when the row was written.
REAL_TS="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
if ! [[ "${REAL_TS}" =~ ${REAL_TS_RE} ]]; then
    # %3N is a GNU date extension.  Where it is unavailable it is left
    # in the output verbatim, which would be a fabricated timestamp, so
    # the second-resolution form is used and the millisecond field is
    # honestly zero.
    REAL_TS="$(date -u +%Y-%m-%dT%H:%M:%S).000Z"
    playthrough_warn "this date(1) has no %3N, so real_ts carries" \
        "second resolution with a zero millisecond field"
fi

# ---------------------------------------------------------------------
# THE GRAB.  The X ROOT window, exactly once.
#
# GRABBED is raised BEFORE the capturer runs, not after: a capturer that
# creates the file and then fails would otherwise leave a partial PNG
# behind in the frames directory, and the EXIT trap has to know about it.
# ---------------------------------------------------------------------
GRABBED=1
case "${CAPTURE_TOOL}" in
    import)
        # The contracted form.  `-window root` is the whole point: the
        # root is exactly 1920x1080 while the game window is 1920x1072
        # at +0+4, so this needs no rescaling and nothing softens the
        # 8x16 glyphs the clock read depends on.
        if ! import -window root "${FRAME_PATH}"; then
            die "${EX_CAPTURE}" "import -window root failed for \
${FRAME_FILE} on DISPLAY=${DISPLAY}"
        fi
        ;;
    scrot)
        # scrot grabs the whole screen -- the root window -- when it is
        # given neither -u nor -s, so the frame is equivalent.
        if ! scrot "${FRAME_PATH}"; then
            die "${EX_CAPTURE}" "scrot failed for ${FRAME_FILE} on \
DISPLAY=${DISPLAY}"
        fi
        ;;
    *)
        # Unreachable today -- the preflight sets CAPTURE_TOOL to
        # exactly one of the two names above -- and present anyway,
        # because a case that falls through silently would raise
        # GRABBED, capture nothing, and then be reported by the next
        # block as "wrote no file", which names the symptom instead of
        # the cause.  Failing here names the cause.
        die "${EX_PREREQ}" "no capturer is implemented for \
CAPTURE_TOOL='${CAPTURE_TOOL}'; the supported values are import and \
scrot"
        ;;
esac

# ---------------------------------------------------------------------
# Prove the file on disk really is one frame of the contracted shape.
# A capturer that exits 0 having written nothing, or a truncated write,
# must not be reported as a successful capture.
# ---------------------------------------------------------------------
if [ ! -f "${FRAME_PATH}" ]; then
    die "${EX_CAPTURE}" "${CAPTURE_TOOL} reported success but wrote no \
file at ${FRAME_PATH}"
fi

FRAME_BYTES="$(wc -c <"${FRAME_PATH}")"
if [ "${FRAME_BYTES}" -le 0 ]; then
    die "${EX_CAPTURE}" "${FRAME_PATH} is empty; ${CAPTURE_TOOL} wrote \
a zero-byte file"
fi

# identify reports the format and the size in one call.  Multi-frame
# output is impossible for a screen grab, but the first line is taken
# explicitly rather than assumed, and without a pipe, so that pipefail
# cannot turn a SIGPIPE into a spurious capture failure.
if ! _cap_identify="$(
        identify -format '%m %wx%h\n' "${FRAME_PATH}" 2>&1
     )"; then
    die "${EX_CAPTURE}" "identify could not read ${FRAME_PATH} as an \
image: ${_cap_identify}"
fi
_cap_identify="${_cap_identify%%$'\n'*}"
FRAME_FORMAT="${_cap_identify%% *}"
FRAME_GEOMETRY="${_cap_identify##* }"
unset _cap_identify

if [ "${FRAME_FORMAT}" != "PNG" ]; then
    die "${EX_CAPTURE}" "${FRAME_PATH} is a ${FRAME_FORMAT}, not a \
PNG; the pipeline reads and encodes PNG frames only"
fi

_cap_want_geometry="\
${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}"
if [ "${FRAME_GEOMETRY}" != "${_cap_want_geometry}" ]; then
    die "${EX_GEOMETRY}" "${FRAME_FILE} is ${FRAME_GEOMETRY}, not the \
contracted ${_cap_want_geometry}.  Capture targets the X root \
deliberately so that no rescaling is needed; a different size means \
either the display is wrong or something other than the root was \
photographed."
fi
unset _cap_want_geometry

# ---------------------------------------------------------------------
# THE NON-BLANK GATE.
#
# This is the guard against the pipeline's one silent catastrophe.  With
# the dummy video backend the game runs, the keystrokes land, this file
# writes a PNG of exactly the right size, ffmpeg encodes it and every
# acceptance count matches -- and the movie is black from end to end.
#
# Calibration, measured with this exact command:
#     real rendered frame     mean=0.270018   std=0.198145
#     dummy video backend     mean=0          std=0
#     uniform solid colour    mean>0          std=0
# The mean term catches a black frame; the standard-deviation term also
# catches a flat solid one, which a mean test alone would pass.  This
# fires at frame one instead of after the whole session, and it fails
# LOUDLY rather than warning.
# ---------------------------------------------------------------------
if ! _cap_luma="$(
        convert "${FRAME_PATH}" -colorspace Gray \
            -format '%[fx:mean] %[fx:standard_deviation]' info: 2>&1
     )"; then
    die "${EX_CAPTURE}" "convert could not measure the luminance of \
${FRAME_PATH}: ${_cap_luma}"
fi
_cap_luma="${_cap_luma%%$'\n'*}"
LUMA_MEAN="${_cap_luma%% *}"
LUMA_STDDEV="${_cap_luma##* }"
unset _cap_luma

# Both values must be numbers before they are compared.  awk compares a
# non-numeric string against 0 as STRINGS, so an unparsed value such as
# "nan" would satisfy `> 0` and a blank frame would pass the gate.
if ! [[ "${LUMA_MEAN}" =~ ${NUMBER_RE} ]] ||
   ! [[ "${LUMA_STDDEV}" =~ ${NUMBER_RE} ]]; then
    die "${EX_CAPTURE}" "the luminance of ${FRAME_FILE} did not \
measure as numbers (mean='${LUMA_MEAN}' stddev='${LUMA_STDDEV}'), so \
the non-blank gate cannot be evaluated and the frame is not accepted"
fi

if ! awk -v m="${LUMA_MEAN}" -v s="${LUMA_STDDEV}" \
        'BEGIN { exit (m > 0 && s > 0) ? 0 : 1 }'; then
    die "${EX_BLANK}" "${FRAME_FILE} is blank: grayscale \
mean=${LUMA_MEAN} stddev=${LUMA_STDDEV}, and a real rendered frame \
measures mean=0.270018 stddev=0.198145.  mean=0 with stddev=0 is the \
signature of the dummy video backend rendering zero pixels; stddev=0 \
alone is a uniform solid screen.  Nothing further is captured until \
the display genuinely renders."
fi

# ---------------------------------------------------------------------
# THE CROP RECTANGLE.  Computed, never hard-coded.
#
# sidebar_geometry.py derives it as
#     width  = sidebar_width_cells * FONT_WIDTH  * SCALING_FACTOR
#     height = TERMINAL_Y          * FONT_HEIGHT * SCALING_FACTOR
#     x      = window.x + window.width - width   (SIDEBAR_POSITION right)
# from data/json/ui/sidebar.json and the game-written options.json, and
# prints nothing but the geometry on stdout.  It evaluates to
# 288x1072+1632+4 for the configuration this pipeline runs under.
#
# Computing it matters because nine sidebar*.json presets ship in
# data/json/ui/ at eight distinct widths: a hard-coded rectangle would
# crop the wrong column the moment the layout changed, and it would do
# so silently -- nothing crashes, the pattern simply stops matching,
# every reading goes empty, every duration collapses to the floor, and
# the finished movie looks plausible while meaning nothing.
#
# It also returns the WHOLE sidebar column, never a fixed band: the
# clock is drawn by the time_desc_label widget bound to time_text
# [data/json/ui/time.json:2-8] at whatever row the enclosing
# custom_sidebar widgets array puts it, so its y cannot be known from
# configuration.  The clock is located BY PATTERN inside the OCR text.
# ---------------------------------------------------------------------
CLOCK_RECT=""
CLOCK_RECT_FROM=""
if [ -n "${RECT_OVERRIDE}" ]; then
    CLOCK_RECT="${RECT_OVERRIDE}"
    CLOCK_RECT_FROM="override"
elif [ -f "${GEOMETRY_SCRIPT}" ]; then
    if _cap_rect="$("${PLAYTHROUGH_PYTHON}" "${GEOMETRY_SCRIPT}")"; then
        CLOCK_RECT="${_cap_rect%%$'\n'*}"
        CLOCK_RECT_FROM="computed"
    else
        playthrough_warn "${GEOMETRY_SCRIPT} could not compute the" \
            "sidebar crop; falling back to the documented rectangle" \
            "for the contracted configuration"
    fi
    unset _cap_rect
else
    playthrough_warn "missing ${GEOMETRY_SCRIPT}, which is where the" \
        "sidebar crop is computed"
fi

if [ -z "${CLOCK_RECT}" ]; then
    # LABELLED LAST RESORT.  This literal is the value the computation
    # yields for the contracted configuration and it is used only when
    # the computation cannot be run at all.  It cannot fabricate a
    # reading: a wrong column matches nothing, which reports an honest
    # "unreadable" rather than a wrong clock.
    CLOCK_RECT="${FALLBACK_RECT}"
    CLOCK_RECT_FROM="fallback"
    playthrough_warn "using the LAST-RESORT crop ${FALLBACK_RECT};" \
        "this is the computed value for the contracted 240x67 grid" \
        "with a 36-cell right-hand sidebar and is not derived from" \
        "this run's configuration"
fi

if ! [[ "${CLOCK_RECT}" =~ ${GEOMETRY_RE} ]]; then
    die "${EX_CLOCK_FAULT}" "the sidebar crop resolved to \
'${CLOCK_RECT}', which is not an ImageMagick WxH+X+Y geometry"
fi

# ---------------------------------------------------------------------
# THE CLOCK READ.  An assist that is allowed to fail, and never allowed
# to invent.
#
# The reading of the frame is authoritative; OCR is the assist.  A
# genuine HH:MM:SS is emitted verbatim.  Anything else emits NOTHING --
# never 00:00:00, never the previous frame's value, never an
# interpolation, never a repair of a partial match.  Reconciling a
# missing or non-monotonic reading is timeline.py's job, downstream and
# visibly, against the previous frame; this file is stateless and holds
# no reading from one invocation to the next, so it cannot silently
# continue a sequence even if it wanted to.
#
# What the engine can legitimately put there [src/display.cpp:207-219]:
# an exact time only when the survivor has a watch; otherwise a coarse
# phrase from display::time_approx() -- "Around dawn", "Dead of night"
# and the rest -- or "???".  Those are REAL READINGS, not failures, and
# they surface verbatim in TIME_PHRASE rather than being discarded.
# ---------------------------------------------------------------------
CLOCK=""
CLOCK_STATUS=""
CLOCK_SOURCE="none"
TIME_PHRASE=""
OCR_RC=0
OCR_OUT=""

# ocr_field FIELD -- delegate one reading to ocr_clock.py.
#
# Delegation is preferred over a second implementation precisely so the
# two cannot disagree about the crop or the pattern: the rectangle
# computed above is passed in, and ocr_clock.py's own CLOCK_RE is
# character-for-character CLOCK_PATTERN here.  --strict-path is what an
# automated caller is documented to pass, so a frame from outside the
# capture directory is refused rather than warned about.
#
# Results come back in globals because a `$( ... )` capture of a
# function runs in a subshell, where the exit status of the delegate --
# 0 read, 1 unreadable, 2 fault -- is exactly what must not be lost.
ocr_field() {
    OCR_OUT=""
    OCR_RC=0
    if OCR_OUT="$(
            "${PLAYTHROUGH_PYTHON}" "${OCR_SCRIPT}" \
                --strict-path \
                --frames-dir "${PLAYTHROUGH_FRAMES_DIR}" \
                --rect "${CLOCK_RECT}" \
                --field "$1" \
                "${FRAME_PATH}"
         )"; then
        OCR_RC=0
    else
        OCR_RC=$?
    fi
    OCR_OUT="${OCR_OUT%%$'\n'*}"
    return 0
}

# possible_clock HH:MM:SS -- true when the engine could have rendered it.
#
# 48:48:48 and 88:48:48 both match the pattern and have both been
# measured coming out of whole-column OCR of this very sidebar.  They
# are impossible: the engine cannot render hour 48.  Such a reading is
# DECLINED -- no digit is substituted, nothing is reconstructed -- so
# that a misread becomes an honest absence instead of a plausible lie.
# 10# forces base ten, because 08 would otherwise be read as octal.
#
# This is a PREDICATE: its non-zero return is data, not an error, so it
# is meant to be called in a condition where errexit steps aside.  It
# runs no external command and therefore has no failure of its own that
# such a call could mask.
possible_clock() {
    local candidate="$1" hour minute second rest
    hour="${candidate%%:*}"
    rest="${candidate#*:}"
    minute="${rest%%:*}"
    second="${rest##*:}"
    [ "$((10#${hour}))" -le "${MAX_HOUR}" ] &&
    [ "$((10#${minute}))" -le "${MAX_MINUTE}" ] &&
    [ "$((10#${second}))" -le "${MAX_SECOND}" ]
}

# inline_clock -- the specified chain, run directly.
#
# This is the capture helper's own pipeline, preserved verbatim apart
# from the mandated preprocessing, and it is the LAST RESORT: it runs
# only when ocr_clock.py or the interpreter is unavailable, and it says
# so on stderr when it does.  It reads the column in one pass, which is
# measurably weaker than ocr_clock.py's row-wise pass -- hence the
# possibility gate above, which is what keeps a weaker reader honest
# instead of merely quieter.
#
# Returns 0 with INLINE_OUT set, 1 for an unreadable clock, 2 for a
# fault in the image or OCR stage.  Those three codes are data, so the
# call site captures them deliberately rather than letting errexit act
# on them; every command inside that could genuinely fail is checked
# here, so nothing is masked by being called in a condition.
INLINE_OUT=""
inline_clock() {
    local text="" matches="" candidate=""
    INLINE_OUT=""
    if ! text="$(
            convert "${FRAME_PATH}" -crop "${CLOCK_RECT}" +repage \
                -colorspace Gray -resize 200% -normalize png:- |
                tesseract stdin stdout 2>/dev/null
         )"; then
        playthrough_warn "the inline convert|tesseract chain failed on" \
            "${FRAME_FILE}; reporting no reading rather than guessing"
        return 2
    fi
    # `|| true` is required, not lazy: no match is an EXPECTED outcome
    # -- most menu keystrokes photograph a screen with no clock on it --
    # and errexit would otherwise turn an honest absence into a script
    # failure.
    matches="$(printf '%s\n' "${text}" |
        grep -Eo "${CLOCK_PATTERN}" || true)"
    if [ -z "${matches}" ]; then
        return 1
    fi
    # First possible match in reading order wins, which is the same rule
    # ocr_clock.py fixes, so the same PNG always reads the same way.
    while IFS= read -r candidate; do
        [ -n "${candidate}" ] || continue
        if possible_clock "${candidate}"; then
            INLINE_OUT="${candidate}"
            return 0
        fi
        playthrough_warn "declining '${candidate}' from" \
            "${FRAME_FILE}: the engine cannot render it, so it is a" \
            "misread and is not repaired"
    done <<<"${matches}"
    return 1
}

if [ "${CLOCK_MODE}" = "off" ]; then
    CLOCK_STATUS="skipped"
elif [ -f "${OCR_SCRIPT}" ] &&
     command -v "${PLAYTHROUGH_PYTHON}" >/dev/null 2>&1; then
    CLOCK_SOURCE="ocr_clock.py"
    ocr_field clock
    case "${OCR_RC}" in
        0)
            CLOCK="${OCR_OUT}"
            CLOCK_STATUS="read"
            ;;
        1)
            CLOCK_STATUS="unreadable"
            ;;
        *)
            CLOCK_STATUS="fault"
            ;;
    esac
else
    CLOCK_SOURCE="inline"
    playthrough_warn "ocr_clock.py or ${PLAYTHROUGH_PYTHON} is" \
        "unavailable; reading the clock with the inline" \
        "convert|tesseract|grep chain, which is the documented last" \
        "resort and a weaker reader than the module"
    INLINE_RC=0
    if inline_clock; then
        INLINE_RC=0
    else
        INLINE_RC=$?
    fi
    case "${INLINE_RC}" in
        0)
            CLOCK="${INLINE_OUT}"
            CLOCK_STATUS="read"
            ;;
        1)
            CLOCK_STATUS="unreadable"
            ;;
        *)
            CLOCK_STATUS="fault"
            ;;
    esac
fi

# Whatever produced it, a reading leaves this file only if it is
# genuinely the contracted shape AND genuinely possible.  Re-checking a
# delegated value costs one pattern match and makes this file's honesty
# self-contained rather than inherited.
if [ "${CLOCK_STATUS}" = "read" ]; then
    if ! [[ "${CLOCK}" =~ ^${CLOCK_PATTERN}$ ]] ||
       ! possible_clock "${CLOCK}"; then
        die "${EX_CLOCK_FAULT}" "${CLOCK_SOURCE} returned \
'${CLOCK}' for ${FRAME_FILE}, which is not a possible \
HH:MM:SS reading.  Refusing to emit it: a reading that cannot be true \
is not reported as a clock."
    fi
fi

# A FAULT is not an unreadable clock.  The faults that actually happen
# -- an off-contract 24_HOUR option, a missing OCR toolchain, a frame
# outside the capture directory -- are standing misconfigurations that
# would report EVERY later frame as unreadable, collapsing every
# duration to the floor while every count still tallied.  That is the
# failure mode this pipeline exists to make loud, so it is fatal by
# default.
if [ "${CLOCK_STATUS}" = "fault" ]; then
    if [ "${STRICT_CLOCK}" -eq 1 ]; then
        die "${EX_CLOCK_FAULT}" "the clock read faulted on \
${FRAME_FILE} (${CLOCK_SOURCE} exit ${OCR_RC:-2}).  This is a fault, \
not an unreadable clock: fix it -- seed_options.py sets 24_HOUR=24h -- \
and recapture.  Set PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0 to carry on \
with the fault recorded instead."
    fi
    playthrough_warn "the clock read faulted on ${FRAME_FILE} and" \
        "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0, so the frame is kept with" \
        "CLOCK_STATUS=fault and no reading"
fi

# The coarse phrase, read only when it is the reading that matters:
# without a watch the sidebar shows a phrase INSTEAD of a clock, so
# 'auto' asks for it exactly when there was no clock to read.  It is
# reported verbatim; it is never converted into a time.
if [ "${PHRASE_MODE}" != "off" ] &&
   [ "${CLOCK_SOURCE}" = "ocr_clock.py" ] &&
   { [ "${PHRASE_MODE}" = "always" ] ||
     [ "${CLOCK_STATUS}" = "unreadable" ]; }; then
    ocr_field phrase
    if [ "${OCR_RC}" -eq 0 ]; then
        TIME_PHRASE="${OCR_OUT}"
    fi
fi

# ---------------------------------------------------------------------
# The frame has passed every check, so it is ours to keep: the EXIT trap
# will no longer withdraw it, and a superseded frame moved aside stays
# aside.  Nothing below this line can fail in a way that would leave an
# unaccounted frame in the capture directory.
# ---------------------------------------------------------------------
KEPT=1
BACKUP=""

emit FRAME_INDEX "${FRAME_INDEX}"
emit FRAME_NAME "${FRAME_NAME}"
emit FRAME_FILE "${FRAME_FILE}"
emit FRAME_PATH "${FRAME_PATH}"
emit FRAME_BYTES "${FRAME_BYTES}"
emit FRAME_FORMAT "${FRAME_FORMAT}"
emit FRAME_GEOMETRY "${FRAME_GEOMETRY}"
emit REAL_TS "${REAL_TS}"
emit CAPTURE_TOOL "${CAPTURE_TOOL}"
emit LUMA_MEAN "${LUMA_MEAN}"
emit LUMA_STDDEV "${LUMA_STDDEV}"
emit CLOCK_RECT "${CLOCK_RECT}"
emit CLOCK_RECT_FROM "${CLOCK_RECT_FROM}"
emit CLOCK_SOURCE "${CLOCK_SOURCE}"
emit CLOCK_STATUS "${CLOCK_STATUS}"
emit CLOCK "${CLOCK}"
emit TIME_PHRASE "${TIME_PHRASE}"

playthrough_log "captured ${FRAME_FILE} (${FRAME_GEOMETRY}," \
    "${FRAME_BYTES} bytes) clock=${CLOCK:-<none>}" \
    "status=${CLOCK_STATUS}"

exit "${EX_OK}"
