#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/capture.sh
#
# ONE keystroke, ONE screenshot, ONE clock reading.
#
# The capture step of the pipeline's loop -- observe, decide in
# character, act, capture, log.  A single invocation lets the frame
# settle, photographs the X ROOT window into
# playthrough/frames/frame_%05d.png, and reads the sidebar clock out of
# the pixels it has just written.  It never loops over keys and never
# sends one: session.py owns the keystroke and the frame counter, this
# file owns the photograph.
#
# USAGE
#     FRAME_INDEX=<n> playthrough/tooling/capture.sh
#     playthrough/tooling/capture.sh --help
#
# FRAME_INDEX is the ONLY input and it is required.  This file must never
# derive, default, guess or increment one, and deliberately does not
# count it off the frames directory: that would be a second source of
# truth, and a retry could silently renumber a frame.
#
# THE ROOT WINDOW, DELIBERATELY.  `import -window root`, never the game X
# window: the root is 1920x1080 while the grid the engine paints is
# 1920x1072 at +0+4 (all three rectangles are tabulated in env.sh under
# "Display, window and grid geometry"), so photographing the root yields
# a true-resolution PNG needing no rescaling -- and rescaling would
# soften exactly the 8x16 glyphs the clock read depends on.  ImageMagick
# is called only as `import`, `convert` and `identify`, the names that
# exist on both its 6.x and 7.x branches.
#
# THE CROP AND THE CLOCK.  The sidebar rectangle is COMPUTED at run time
# by sidebar_geometry.py -- never a literal here, except in one clearly
# labelled operator override -- and the reading is matched as
# [0-9]{2}:[0-9]{2}:[0-9]{2}, the fixed-width form
# to_string_time_of_day() emits under 24_HOUR=24h
# (src/calendar.cpp:649); the other two branches render 0815.32 and
# 8:15:32 AM and would defeat it.  Preprocessing is `+repage -colorspace
# Gray -resize 200% -normalize`, because those glyphs are illegible to
# tesseract at native size.  THE OCR MAY LEGITIMATELY RETURN NOTHING --
# no watch carried, the survivor underground, a genuine misread -- and an
# unreadable clock is reported as unreadable rather than guessed.
#
# STDOUT IS A MACHINE CONTRACT: one KEY=value per line and nothing else,
# with all logging and diagnostics on stderr.  The keys, in this order:
#
#     CAPTURE_MODE     production | diagnostic.  First, because it says
#                      whether the rest describes a frame that belongs to
#                      the record.  A caller must accept only production
#                      and cannot do otherwise by accident: diagnostic
#                      never exits 0
#     FRAME_INDEX      the index exactly as validated
#     FRAME_NAME       frame_%05d.png
#     FRAME_FILE       the repository-relative frame path, byte-identical
#                      to manifest.py's `file` field.  Empty in
#                      diagnostic mode, which leaves no frame in the tree
#     FRAME_PATH       the same frame, absolute; empty likewise
#     DIAGNOSTIC_PATH  where a withdrawn frame is kept, outside the tree;
#                      empty in production.  Emitted in BOTH modes: a key
#                      that sometimes disappears gets papered over with a
#                      default
#     FRAME_BYTES      size on disk, so a truncated write is visible
#     FRAME_FORMAT     the format identify reports (PNG)
#     FRAME_GEOMETRY   WxH as captured, asserted against the contract
#     REAL_TS          UTC instant of the grab, in the manifest's own form
#     CAPTURE_TOOL     import, or scrot when import is unavailable
#     LUMA_MEAN        grayscale mean of the frame
#     LUMA_STDDEV      grayscale standard deviation of the frame
#     CLOCK_RECT       the crop rectangle used, or empty when uncropped
#     CLOCK_RECT_FROM  computed | override | skipped; no fallback exists
#     CLOCK_SOURCE     ocr_clock.py | inline | none
#     CLOCK_STATUS     read | unreadable | fault | skipped
#     CLOCK            the reading, VERBATIM, or empty.  Never
#                      interpolated, carried forward or guessed
#     TIME_PHRASE      the coarse phrase shown instead of a clock, or empty
#     CLOCK_DATE       the sidebar date line, VERBATIM, or empty.  Read
#                      because a clock alone cannot tell a crossing of
#                      midnight from a misread going backwards, which is a
#                      decision timeline.py makes.  Never derived
#     DATE             the same line under the telemetry row's field name
#     DATE_STATUS      read | unreadable | fault | unavailable | skipped
#     DATE_AUDIT       yes | no | off -- whether this frame's date reached
#                      ocr_clock.py's audit.  `no` is not a failure, but
#                      timeline.py must then treat the date as UNKNOWN
#     OBSERVATIONS     the telemetry sidecar this row belongs in, or empty
#
# EXIT CODES
#     0  one frame captured and the whole output contract delivered
#     1  usage error -- a missing, malformed or out-of-range index, or a
#        production run that tried to relax one of the six safeguards
#     2  layout error -- not inside a checkout, or env.sh is missing
#     3  the capture failed, or produced something that is not a frame
#     4  the frame is blank -- the black-movie guard fired
#     5  no usable display at the contracted geometry, a frame that is
#        not that geometry, or a crop that could not be computed
#     6  the clock read hit a FAULT rather than an unreadable clock
#     7  refusing to overwrite an existing frame at this index
#     8  a prerequisite command is missing, or the date-audit directory
#        does not exist
#     9  a DIAGNOSTIC capture completed and was withdrawn out of the
#        working tree.  Non-zero by design: nothing was added to
#        playthrough/frames/, so it must not read as success
#
# THE NON-BLANK GATE.  Every frame is measured in grayscale and rejected
# unless mean > 0 AND std > 0.  A frame of zero pixels is the signature
# of SDL_VIDEODRIVER=dummy, under which the game runs, the keystrokes
# land, the PNG is written, ffmpeg encodes and every count matches --
# the only symptom being that the movie shows nothing.  The std term
# additionally rejects a uniform solid colour.
#
# THE INVARIANT THIS FILE GUARANTEES:
#     exit 0  <=>  exactly one NEW PNG in playthrough/frames/ AND this
#                  invocation's whole output contract delivered
# On any failure the frames directory is left exactly as it was found: a
# frame this invocation wrote is withdrawn outside the working tree, and a
# pre-existing frame moved aside is put back.  The frame is committed --
# KEPT=1 -- as the LAST statement before exit 0, behind every fallible
# step, and PIPE, INT, TERM and HUP are trapped as well, because a shell
# killed by a signal never reaches its EXIT trap.  So session.py can
# neither append a row for a frame that does not exist nor miss one that
# does, and the frames-count == manifest-line-count identity the gate
# asserts cannot be broken by a failed capture.  Derived imagery -- the
# transition frames -- belongs to playthrough/build/transitions/ and is
# never written here, which is what keeps that identity meaningful.  With
# PLAYTHROUGH_CAPTURE_OVERWRITE=1 the index already holds a frame, so
# `exit 0` means one frame written AT that index and an unchanged PNG
# count: for diagnosis, never a session, and it says so on stderr.
#
# EVERY EXTERNAL STAGE IS BOUNDED by timeout(1): the grab, identify, the
# luminance measurement, the crop computation and the OCR read all talk
# to an X server or an OCR engine, and either can stop answering without
# exiting.  An expiry is named as an expiry (timeout exits 124) rather
# than reported as the tool failing, and the EXIT trap still withdraws
# the frame.
#
# TUNABLES are optional and read from the environment, each declared with
# its default under "Tunables" below.  Every timeout is a whole number of
# seconds from 1 to 3600; 0 is refused because it would mean no limit.
#
# WHAT THIS FILE WRITES, EXHAUSTIVELY: exactly one PNG in
# playthrough/frames/; a withdrawn frame in the reject directory outside
# the tree when a capture fails; and a private scratch file for the
# inline reader's stderr inside env.sh's mode-0700 runtime directory,
# removed on exit.  The telemetry row is REPORTED rather than written --
# every field leaves on stdout and session.py persists it beside the
# manifest row, so one logical record is not appended by two processes --
# and the date audit is REQUESTED rather than written, ocr_clock.py
# owning that append under the canonical destination.  Nothing else: no
# keystroke, no manifest row, no save data, no server, no network call,
# no command through a shell string, no eval and no unquoted glob.
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

# The working directory is the repository root, as it is for every stage of
# this pipeline: --userdir is normalised but not absolutised
# [src/path_info.cpp:105] and the asset roots are working-directory relative
# [src/path_info.cpp:129-136], so the root is the only place under which this
# checkout's own data/ and gfx/ resolve AND the artifacts land inside the
# working tree.
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
# A diagnostic capture completed and was withdrawn.
readonly EX_DIAGNOSTIC=9

# ---------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------
readonly CLOCK_PATTERN='[0-9]{2}:[0-9]{2}:[0-9]{2}'

# The engine cannot render an hour past 23, a minute past 59 or a second past
# 59, so a match outside those bounds is not a clock.
readonly MAX_HOUR=23
readonly MAX_MINUTE=59
readonly MAX_SECOND=59

# manifest.py refuses an index that would widen the five-digit field
# (MIN_FRAME_INDEX / MAX_FRAME_INDEX), so this file refuses it too rather than
# formatting something the manifest will not accept.
readonly MIN_FRAME_INDEX=1
readonly MAX_FRAME_INDEX=99999

# ---------------------------------------------------------------------
# STAGE TIMEOUTS. Every external command here gets a ceiling.
# ---------------------------------------------------------------------
readonly TIMEOUT_EXPIRED=124
readonly DEFAULT_GRAB_TIMEOUT=60
readonly DEFAULT_IDENTIFY_TIMEOUT=30
readonly DEFAULT_LUMA_TIMEOUT=60
readonly DEFAULT_GEOMETRY_TIMEOUT=60
readonly DEFAULT_OCR_TIMEOUT=300

# TWO WORKED EXAMPLES OF THE CROP, AND NEITHER IS A FALLBACK.
# Both are recorded here as documentation and quoted in the diagnostics that
# explain why neither is substituted. THEY ARE NEVER USED AS A VALUE.
readonly EXAMPLE_RECT='288x1072+1632+4'
readonly EXAMPLE_RECT_LAYOUT='a 36-cell custom_sidebar'
readonly DEFAULT_LAYOUT_RECT='352x1072+1568+4'
readonly DEFAULT_LAYOUT_NAME='legacy_labels_sidebar (44 cells)'

# An ImageMagick geometry, and a bare non-negative decimal number as
# ImageMagick's fx: operators print one.
readonly GEOMETRY_RE='^[0-9]+x[0-9]+\+[0-9]+\+[0-9]+$'
readonly NUMBER_RE='^[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$'

# manifest.py's real_ts form: UTC, millisecond precision, "Z"-suffixed, e.g.
# 2026-05-14T09:12:03.481Z.
readonly REAL_TS_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}\.[0-9]{3}Z$'

readonly GEOMETRY_SCRIPT="${PLAYTHROUGH_TOOLING_DIR}/sidebar_geometry.py"
readonly OCR_SCRIPT="${PLAYTHROUGH_TOOLING_DIR}/ocr_clock.py"

# ---------------------------------------------------------------------
# Tunables, resolved once.
# ---------------------------------------------------------------------
SETTLE="${PLAYTHROUGH_CAPTURE_SETTLE:-${PLAYTHROUGH_SETTLE_SECONDS}}"
# on | off -- whether the clock is read at all.
CLOCK_MODE="${PLAYTHROUGH_CAPTURE_CLOCK:-on}"
# auto | off | always -- auto reads the coarse sidebar phrase only when
# there was no clock to read.
PHRASE_MODE="${PLAYTHROUGH_CAPTURE_PHRASE:-auto}"
# 1 | 0 -- 1 makes a clock FAULT fatal, because the two faults that
# actually happen (an off-contract 24_HOUR, an absent OCR toolchain)
# would poison every later frame while every count still tallied.
STRICT_CLOCK="${PLAYTHROUGH_CAPTURE_STRICT_CLOCK:-1}"
# 0 | 1 -- 1 recaptures an index that already holds a frame, so a
# success REPLACES rather than adds.  See THE RESERVATION IS ATOMIC.
OVERWRITE="${PLAYTHROUGH_CAPTURE_OVERWRITE:-0}"
# An explicit WxH+X+Y crop.  This is the ONLY way a fixed rectangle is
# ever used: an operator decision, recorded as CLOCK_RECT_FROM=override,
# never a silent fallback.
RECT_OVERRIDE="${PLAYTHROUGH_CAPTURE_RECT:-}"
# `${VAR-default}` rather than `${VAR:-default}` on the timeouts below: a
# variable that is set but EMPTY is an operator mistake, and defaulting it
# silently would hide the mistake behind a working run.
AUDIT_MODE="${PLAYTHROUGH_CAPTURE_AUDIT:-on}"
AUDIT_PATH="${PLAYTHROUGH_CAPTURE_AUDIT_PATH:-${PLAYTHROUGH_DATE_AUDIT}}"
GRAB_TIMEOUT="${PLAYTHROUGH_CAPTURE_GRAB_TIMEOUT-${DEFAULT_GRAB_TIMEOUT}}"
IDENTIFY_TIMEOUT="\
${PLAYTHROUGH_CAPTURE_IDENTIFY_TIMEOUT-${DEFAULT_IDENTIFY_TIMEOUT}}"
LUMA_TIMEOUT="${PLAYTHROUGH_CAPTURE_LUMA_TIMEOUT-${DEFAULT_LUMA_TIMEOUT}}"
GEOMETRY_TIMEOUT="\
${PLAYTHROUGH_CAPTURE_GEOMETRY_TIMEOUT-${DEFAULT_GEOMETRY_TIMEOUT}}"
OCR_TIMEOUT="${PLAYTHROUGH_CAPTURE_OCR_TIMEOUT-${DEFAULT_OCR_TIMEOUT}}"

# Set when ocr_clock.py's own dependency preflight fails and strict
# mode is off: the delegate is then skipped in favour of the inline
# reader, rather than being called once per field to fail twice.
OCR_PREFLIGHT_FAILED=0

# The telemetry sidecar this frame's row BELONGS IN, reported to the caller
# that appends it.
OBSERVATIONS="${PLAYTHROUGH_OBSERVATIONS}"

# THE MODE, and why one exists at all.
CAPTURE_MODE="${PLAYTHROUGH_CAPTURE_MODE:-production}"

# Withdrawn frames are kept OUTSIDE the working tree. Inside it they would be
# re-included by the terminal `!/playthrough/**` negation in .gitignore and
# could be committed as if they were session frames.
REJECT_DIR="${PLAYTHROUGH_CAPTURE_REJECT_DIR:-${PLAYTHROUGH_REJECT_DIR}}"

# EVERY file this script creates is private.
umask 077

# ---------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------
die() {
    local code="$1"
    shift
    # THE MESSAGE IS ESCAPED, because some of what reaches it is chosen
    # elsewhere -- a world name, a directory name, an environment variable --
    # and a diagnostic that printed those bytes raw would perform the injection
    # it is reporting: a newline forges a whole extra line of output, and ESC-[
    # or the single-byte C1 CSI repaints the terminal of whoever is reading the
    # run.
    printf 'playthrough: FATAL: %s\n' "$(playthrough_escape_controls "$*")" >&2
    exit "${code}"
}

# The machine-readable channel is assembled by `line KEY VALUE` and written in
# ONE printf at the very end of this file -- see OUTPUT, THEN THE LOG, THEN THE
# COMMIT POINT.

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

Writes exactly one playthrough/frames/frame_%05d.png -- the only path
inside the working tree it writes at all -- and REPORTS this frame's
telemetry row, the clock and the sidebar date line that timeline.py
cross-checks its rollover decisions against, for session.py to persist
to playthrough/build/observations.jsonl beside the manifest row it
already owns.  Prints KEY=value lines on stdout and everything else on
stderr.  See the header of this file for the full output contract, the
exit codes and the tunables.

The default mode is production, in which the 0.3s settle, the clock
read, fatal fault handling and the refusal to reuse an index are all
unconditional.  PLAYTHROUGH_CAPTURE_MODE=diagnostic relaxes them and in
exchange withdraws the frame out of the working tree and exits 9, so a
diagnostic capture can never be recorded as a session frame.
USAGE
}

# ---------------------------------------------------------------------
# The frames-directory guarantee.
# ---------------------------------------------------------------------
GRABBED=0
KEPT=0
BACKUP=""
FRAME_PATH=""
# The exclusive temporary file the grab writes to before it is renamed
# into place.  Emptied on publish, so the trap only ever withdraws one
# that is genuinely still unpublished.
CAPTURE_TMP=""

# Files one rejected capture out of the frames directory.  Reached only
# from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
file_rejected() {
    local src="$1" name="$2" target
    # A zero-byte file is the reservation placeholder, or a grab that
    # wrote nothing: there is no image to inspect, so it is released
    # rather than filed as though it were evidence.
    if [ ! -s "${src}" ]; then
        rm -f -- "${src}" 2>/dev/null || true
        return 0
    fi
    # Keep the rejected capture: it is the evidence of whatever went wrong.
    target="${REJECT_DIR}/${name}"
    if playthrough_secure_dir "${REJECT_DIR}" 700 2>/dev/null &&
       mv -f -- "${src}" "${target}" 2>/dev/null; then
        chmod 600 -- "${target}" 2>/dev/null || true
        playthrough_warn "withdrew ${src} from the frames directory" \
            "and kept it at ${target} for inspection"
    else
        rm -f -- "${src}" 2>/dev/null || true
        playthrough_warn "withdrew and discarded ${src};" \
            "${REJECT_DIR} could not be written"
    fi
}

# Where a delegated stage's stderr is kept while it runs, so that a failure can
# be DIAGNOSED instead of merely reported.
STAGE_ERR="${PLAYTHROUGH_RUNTIME_DIR}/capture-stage-$$.err"
# A generous excerpt that still cannot bury the session log: tesseract
# can emit a page of warnings per frame.
readonly STAGE_ERR_BYTES=2000

# stage_stderr -- a bounded, single-line excerpt of the last stage's stderr, or
# the empty string.
stage_stderr() {
    [ -s "${STAGE_ERR}" ] || return 0
    tr -d '\000' <"${STAGE_ERR}" 2>/dev/null |
        grep -v '^[[:space:]]*$' |
        head -c "${STAGE_ERR_BYTES}" |
        tr '\n' ' ' || true
}

# Reached only from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
withdraw() {
    # Everything this invocation put in the frames directory leaves it,
    # published or not.
    if [ -n "${CAPTURE_TMP}" ] && [ -e "${CAPTURE_TMP}" ]; then
        file_rejected "${CAPTURE_TMP}" \
            "${FRAME_NAME:-rejected-capture.png}"
    fi
    CAPTURE_TMP=""
    if [ "${GRABBED}" -eq 1 ] && [ -e "${FRAME_PATH}" ]; then
        file_rejected "${FRAME_PATH}" "$(basename "${FRAME_PATH}")"
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
    # The scratch stderr file is this invocation's alone and carries
    # nothing that is not already in the warning it produced.
    rm -f "${STAGE_ERR}" 2>/dev/null || true
}
trap '_cap_on_exit "$?"' EXIT

# A KILLING SIGNAL MUST WITHDRAW THE FRAME TOO, and the EXIT trap alone
# does not achieve that: a shell terminated BY a signal never reaches
# its EXIT trap, so without these handlers a frame would be left behind
# by exactly the case F02 is about -- session.py reading this output
# through a pipe and going away, whereupon the next `emit` takes SIGPIPE
# and this process dies mid-contract.  Measured before this trap
# existed: the PNG survived in playthrough/frames/ with no manifest row
# to describe it, which is the orphan the 1:1 invariant cannot tolerate.
#
# Each handler converts the signal into an ordinary non-zero exit, which
# then runs the EXIT trap and withdraws the frame through the one code
# path that knows how.  The conventional 128+N status is preserved so a
# caller can still tell WHICH signal ended the capture.
#
# Reached only from a trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
_cap_on_signal() {
    local name="$1" status="$2"
    # stderr, never stdout: stdout is the stream that just broke.
    playthrough_warn "capture of ${FRAME_FILE:-the frame} was ended by" \
        "SIG${name}; withdrawing it so no frame is left that no" \
        "manifest row describes"
    exit "${status}"
}
trap '_cap_on_signal PIPE 141' PIPE
trap '_cap_on_signal INT 130' INT
trap '_cap_on_signal TERM 143' TERM
trap '_cap_on_signal HUP 129' HUP

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
# Validate the index STRICTLY. It is not defaulted, not derived and not
# coerced.
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
case "${CAPTURE_MODE}" in
    production|diagnostic) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_MODE=\
'${CAPTURE_MODE}' is neither 'production' nor 'diagnostic'" ;;
esac
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

# Every stage ceiling is validated before any of them is used, because
# these values reach `timeout` directly: a non-numeric one would make
# timeout itself fail with a usage error on every single frame, and a
# zero would mean "no limit at all", quietly restoring the unbounded
# behaviour the ceilings exist to remove.
_cap_check_timeout() {
    local name="$1" value="$2"
    if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
        die "${EX_USAGE}" "${name}='${value}' is not a plain decimal \
number of seconds"
    fi
    # 10# forces base ten so a padded 060 is sixty, not octal.
    if [ "$((10#${value}))" -lt 1 ] ||
       [ "$((10#${value}))" -gt 3600 ]; then
        die "${EX_USAGE}" "${name}='${value}' is outside the supported \
range of 1 to 3600 seconds; 0 would mean no limit at all, which is the \
unbounded wait these ceilings exist to prevent"
    fi
}
# A DIAGNOSTIC CAPTURE OWES NO AUDIT ROW, and must not leave one.
if [ "${CAPTURE_MODE}" = "diagnostic" ]; then
    if [ "${PLAYTHROUGH_CAPTURE_AUDIT:-off}" != "off" ] ||
       [ -n "${PLAYTHROUGH_CAPTURE_AUDIT_PATH:-}" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT\
${PLAYTHROUGH_CAPTURE_AUDIT:+=\"${PLAYTHROUGH_CAPTURE_AUDIT}\"}\
${PLAYTHROUGH_CAPTURE_AUDIT_PATH:+ / PLAYTHROUGH_CAPTURE_AUDIT_PATH=\"\
${PLAYTHROUGH_CAPTURE_AUDIT_PATH}\"} cannot be used with \
PLAYTHROUGH_CAPTURE_MODE=diagnostic.  A diagnostic frame is withdrawn \
out of the working tree precisely so that it is not evidence, and a \
capture that writes an audit row while its own photograph is withdrawn \
leaves a record with nothing to account for it.  The reading is in this \
invocation's payload; the sidecar is written only by a capture that \
keeps its frame.  Only PLAYTHROUGH_CAPTURE_AUDIT=off is accepted here, \
and it is accepted because it asks for exactly what this mode does \
anyway."
    fi
    AUDIT_MODE="off"
fi
case "${AUDIT_MODE}" in
    on|off) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT=\
'${AUDIT_MODE}' is neither on nor off" ;;
esac
if [ "${AUDIT_MODE}" = "on" ]; then
    if [ -z "${AUDIT_PATH}" ]; then
        die "${EX_USAGE}" "the date-audit sidecar path is empty; env.sh \
exports PLAYTHROUGH_DATE_AUDIT and PLAYTHROUGH_CAPTURE_AUDIT_PATH \
overrides it"
    fi
    # THE DATE AUDIT GOES WHERE timeline.py LOOKS, IN EVERY MODE.
    if [ "${AUDIT_PATH}" != "${PLAYTHROUGH_DATE_AUDIT}" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT_PATH=\
'${AUDIT_PATH}' is not the sidecar timeline.py reads \
(${PLAYTHROUGH_DATE_AUDIT}), and no other destination is accepted.  \
Every artifact of this pipeline is inside playthrough/, so a contained \
path is not a safe one: a line of audit-shaped JSON appended to the \
manifest, a transcript, a save or a frame would be evidence nobody \
wrote.  A frame's date evidence recorded anywhere else is also evidence \
nothing consults -- the rollover guard then treats this frame's date as \
UNKNOWN while every count still tallies."
    fi
fi

_cap_check_timeout PLAYTHROUGH_CAPTURE_GRAB_TIMEOUT "${GRAB_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_IDENTIFY_TIMEOUT \
    "${IDENTIFY_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_LUMA_TIMEOUT "${LUMA_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_GEOMETRY_TIMEOUT \
    "${GEOMETRY_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_OCR_TIMEOUT "${OCR_TIMEOUT}"

# `timeout` is what bounds every stage, so its absence is a missing
# prerequisite rather than something to work around: carrying on without
# it would silently restore the unbounded waits.
if ! command -v timeout >/dev/null 2>&1; then
    die "${EX_PREREQ}" "timeout(1) is not installed, so no capture \
stage could be bounded; it ships with GNU coreutils"
fi

# The audit directory is checked BEFORE anything is captured, so a missing one
# costs no frame.
if [ "${AUDIT_MODE}" = "on" ]; then
    _cap_audit_dir="$(dirname "${AUDIT_PATH}")"
    if [ ! -d "${_cap_audit_dir}" ]; then
        die "${EX_PREREQ}" "the date-audit directory \
${_cap_audit_dir} does not exist, so this frame's date evidence could \
not be recorded.  Run playthrough_mkdirs (playthrough/tooling/env.sh) \
first, or set PLAYTHROUGH_CAPTURE_AUDIT=off to capture without the \
evidence timeline.py uses to tell a rollover from a misread clock."
    fi
    unset _cap_audit_dir
fi

# Assembled once, expanded as an array so an empty audit configuration
# contributes no argument at all rather than an empty string that ocr_clock.py
# would have to reject.
AUDIT_ARGS=()
if [ "${AUDIT_MODE}" = "on" ]; then
    AUDIT_ARGS=(--audit "${AUDIT_PATH}" --audit-frame "${FRAME_INDEX}")
fi

# ---------------------------------------------------------------------
# HARD-ENFORCE THE SIX SAFEGUARDS ON THE PRODUCTION PATH.
# Each refusal names the property, the consequence of relaxing it, and the one
# mode in which it is legal.
# ---------------------------------------------------------------------
if [ "${CAPTURE_MODE}" = "production" ]; then
    if ! awk -v got="${SETTLE}" -v want="${PLAYTHROUGH_SETTLE_SECONDS}" \
            'BEGIN { exit !(got + 0 >= want + 0) }'; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_SETTLE=${SETTLE} is \
shorter than the contracted ${PLAYTHROUGH_SETTLE_SECONDS}s settle.  \
The game redraws asynchronously: grabbing early photographs the screen \
as it was BEFORE the key landed, so every clock reading would be one \
keystroke stale and the whole film mis-timed -- while every count still \
tallied.  A LONGER settle is accepted; a shorter one needs \
PLAYTHROUGH_CAPTURE_MODE=diagnostic, which cannot produce a frame for \
the record."
    fi
    if [ "${CLOCK_MODE}" != "on" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_CLOCK=\
'${CLOCK_MODE}' cannot be used for a frame that is kept.  Each frame's \
on-screen duration IS the sidebar clock delta between it and its \
successor, so a frame captured with the clock read switched off has no \
duration to derive and would silently fall to the floor.  Use \
PLAYTHROUGH_CAPTURE_MODE=diagnostic to look at a frame without reading \
it."
    fi
    if [ "${STRICT_CLOCK}" -ne 1 ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=\
${STRICT_CLOCK} cannot be used for a frame that is kept.  A FAULT is \
not an unreadable clock: the faults that actually happen -- an \
off-contract 24_HOUR option, a missing OCR toolchain -- are standing \
misconfigurations that would report EVERY later frame as unreadable \
and collapse every duration onto the floor.  Fix the fault and \
recapture, or investigate with \
PLAYTHROUGH_CAPTURE_MODE=diagnostic."
    fi
    if [ "${OVERWRITE}" -ne 0 ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_OVERWRITE=1 cannot be \
used for a frame that is kept.  A frame already at this index means \
the counter repeated, and replacing it moves the original OUT of the \
working tree -- so a keystroke that was photographed and committed \
would silently lose its frame while the counts still matched.  Take \
the next index, or investigate with \
PLAYTHROUGH_CAPTURE_MODE=diagnostic."
    fi
    # THE DATE AUDIT IS MANDATORY for a frame that is kept.
    if [ "${AUDIT_MODE}" != "on" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT=off cannot be used \
for a frame that is kept.  The sidebar DATE line is what tells a clock \
that went backwards apart from a genuine crossing of midnight, and it \
is recorded nowhere else -- so a frame with no audit row leaves \
timeline.py to infer a day it never observed.  Look at a frame without \
recording one with PLAYTHROUGH_CAPTURE_MODE=diagnostic."
    fi
    # AND THE TRUST STATE, which is the fifth thing that decides whether this
    # frame is evidence.
    if ! playthrough_assert_trusted \
            "to capture a frame for the record"; then
        die "${EX_USAGE}" "the trust state is \
'${PLAYTHROUGH_TRUST_STATE}' (${PLAYTHROUGH_TRUST_BYPASSES}), so this \
capture would not be evidence.  Unset the override(s) listed above, or \
look at the frame with PLAYTHROUGH_CAPTURE_MODE=diagnostic, which \
withdraws it out of the working tree and exits ${EX_DIAGNOSTIC}."
    fi
fi

# ---------------------------------------------------------------------
# Preflight.
# ---------------------------------------------------------------------
# EVERY external command is resolved through env.sh, which verifies it before
# handing back the path, and this script then invokes THAT path.
if playthrough_resolve_tool import; then
    CAPTURE_TOOL="import"
    CAPTURE_BIN="${PLAYTHROUGH_BIN_IMPORT}"
elif playthrough_resolve_tool scrot; then
    CAPTURE_TOOL="scrot"
    CAPTURE_BIN="${PLAYTHROUGH_BIN_SCROT}"
    playthrough_warn "ImageMagick's import is not installed; falling" \
        "back to scrot.  Both grab the X root window, so the frame is" \
        "equivalent, but import is the contracted capturer."
else
    die "${EX_PREREQ}" "no usable screen capturer: neither \
ImageMagick's import nor scrot is installed and verifiable.  See the \
apt list in playthrough/tooling/requirements.txt, and any rejection \
reported above."
fi

# Every non-builtin this file actually runs, asserted before anything is
# created.
playthrough_require_tools \
    convert identify xdpyinfo date awk grep mkdir mv rm sha256sum ||
    exit "${EX_PREREQ}"

# tesseract is needed by BOTH clock-read paths, so its absence is a
# prerequisite failure rather than an unreadable clock.
if [ "${CLOCK_MODE}" = "on" ]; then
    playthrough_require_tools tesseract || exit "${EX_PREREQ}"
fi

# Preflight the OCR delegate's own dependencies once, before the grab.
if [ "${CLOCK_MODE}" = "on" ] && [ -f "${OCR_SCRIPT}" ] &&
   command -v "${PLAYTHROUGH_PYTHON}" >/dev/null 2>&1; then
    if ! "${PLAYTHROUGH_PYTHON}" "${OCR_SCRIPT}" --preflight; then
        if [ "${STRICT_CLOCK}" -eq 1 ]; then
            die "${EX_CLOCK_FAULT}" "ocr_clock.py cannot run: a \
dependency did not import, or the interpreter's Pillow is older than \
the pin (see the diagnosis above).  This is a FAULT, not an unreadable \
clock, and it would otherwise report EVERY frame of the session as \
unreadable while every count still tallied.  Install \
playthrough/tooling/requirements.lock into ${PLAYTHROUGH_PYTHON}, or \
set PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0 to capture with the weaker \
inline reader instead."
        fi
        playthrough_warn "ocr_clock.py's dependency contract is not" \
            "satisfied and PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0, so the" \
            "clock is read with the inline convert|tesseract|grep chain"
        OCR_PREFLIGHT_FAILED=1
    fi
fi
# The platform this is photographing on: ImageMagick and the Xorg stack both
# parse untrusted-shaped input, so an out-of-support host is refused by name
# here rather than discovered later.
playthrough_check_platform || exit "${EX_PREREQ}"

# The cheap, loud guard against the one completely silent failure mode of this
# pipeline: the dummy VIDEO backend renders zero pixels, so the game runs, the
# keystrokes land, this script writes a PNG, ffmpeg encodes, every count
# tallies -- and the movie shows nothing.
playthrough_assert_video_driver || exit "${EX_LAYOUT}"

# THE DISPLAY MUST BE CLOSED BEFORE ANYTHING IS PHOTOGRAPHED.
# An X server with no access control hands every local account the same screen
# this script is about to photograph -- and the same keyboard the session is
# being driven with.
playthrough_assert_x_access_control || exit "${EX_GEOMETRY}"

# The root window must be the contracted geometry BEFORE the grab, so a
# wrong-sized display is reported as such instead of surfacing later as
# a mysteriously wrong-resolution movie.
playthrough_assert_display || exit "${EX_GEOMETRY}"

# ---------------------------------------------------------------------
# Prepare the destination.
# ---------------------------------------------------------------------
if ! mkdir -p "${PLAYTHROUGH_FRAMES_DIR}"; then
    die "${EX_CAPTURE}" "cannot create ${PLAYTHROUGH_FRAMES_DIR}"
fi

# AND NOBODY ELSE MAY WRITE INTO IT.
playthrough_deny_foreign_write "${PLAYTHROUGH_FRAMES_DIR}" \
    "the frames directory" || exit "${EX_CAPTURE}"

# THE DESTINATION IS PROVED, NOT ASSUMED.
# Both checks matter for a different reason:
#
#   * containment plus no symlinked component means a planted link at
#     playthrough/ or playthrough/frames/ cannot send this capture -- a
#     photograph of the whole screen -- somewhere outside the working tree,
#     where nothing downstream would look for it and nothing would notice
#     it had gone;
#   * the frame path itself must not already be a symlink, dangling or
#     otherwise, because `import` would follow it and write through.
#
# The frames directory is also where the count identity that
# verify_artifacts.sh asserts lives, so it has to be a real directory
# holding real files and nothing else.
playthrough_assert_inside "${PLAYTHROUGH_FRAMES_DIR}" \
    "${PLAYTHROUGH_REPO_ROOT}" "frames directory" ||
    exit "${EX_LAYOUT}"
playthrough_assert_no_symlink "${PLAYTHROUGH_FRAMES_DIR}" \
    "${PLAYTHROUGH_REPO_ROOT}" "frames directory" ||
    exit "${EX_LAYOUT}"
if [ -L "${FRAME_PATH}" ]; then
    die "${EX_LAYOUT}" "${FRAME_FILE} is a symbolic link.  A frame is \
a file this pipeline writes, never a link it follows: writing through \
it would put a full-screen capture wherever the link pointed."
fi

# RESERVE THE INDEX ATOMICALLY.
# The old form -- test whether the frame exists, then let the capturer create
# it -- is two operations, and two captures racing for the same index could
# both pass the test and both write.
if ! ( set -o noclobber; : >"${FRAME_PATH}" ) 2>/dev/null; then
    # noclobber refuses for two reasons with opposite remedies, so they are
    # told apart before anything is reported. A path that exists is a taken
    # index and the answer is the next one.
    if [ ! -e "${FRAME_PATH}" ]; then
        die "${EX_CAPTURE}" "cannot create ${FRAME_PATH}, and nothing \
is there to be in the way -- so this is not a repeated index and the \
next index would fail identically.  The frames directory itself \
refused the write: it may be immutable (chattr +i), not writable by \
this user, or on a filesystem that is read-only or full.  Check \
${PLAYTHROUGH_FRAMES_DIR} and the filesystem holding it."
    fi
    if [ "${OVERWRITE}" -ne 1 ]; then
        die "${EX_EXISTS}" "${FRAME_PATH} already exists, or another \
capture holds this index.  A repeated index means the frame counter \
went backwards, which would break the one-frame-per-keystroke \
identity.  Take the next index.  Recapturing one deliberately is a \
DIAGNOSTIC action (PLAYTHROUGH_CAPTURE_MODE=diagnostic with \
PLAYTHROUGH_CAPTURE_OVERWRITE=1): the existing frame is moved aside, \
the new capture is withdrawn, and the original is put back."
    fi
    _cap_backup="${REJECT_DIR}/superseded-${FRAME_NAME}"
    if playthrough_secure_dir "${REJECT_DIR}" 700 2>/dev/null &&
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
    # Re-reserve the index now that the earlier frame is out of the way,
    # so the exclusive-ownership property holds on the recapture path too.
    if ! ( set -o noclobber; : >"${FRAME_PATH}" ) 2>/dev/null; then
        die "${EX_EXISTS}" "${FRAME_PATH} reappeared while it was \
being moved aside; another capture is using this index"
    fi
fi
# From here on the placeholder is ours, so it is withdrawn on failure
# exactly like a captured frame would be.
GRABBED=1

# ---------------------------------------------------------------------
# THE SETTLE. 0.3 seconds, from env.sh.
# ---------------------------------------------------------------------
sleep "${SETTLE}"

# The wall-clock instant of the grab, in the manifest's own real_ts form: UTC,
# millisecond precision, "Z"-suffixed.
REAL_TS="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
if ! [[ "${REAL_TS}" =~ ${REAL_TS_RE} ]]; then
    # %3N is a GNU date extension.
    REAL_TS="$(date -u +%Y-%m-%dT%H:%M:%S).000Z"
    playthrough_warn "this date(1) has no %3N, so real_ts carries" \
        "second resolution with a zero millisecond field"
fi

# ---------------------------------------------------------------------
# THE GRAB. The X ROOT window, exactly once, into a temporary file.
# ---------------------------------------------------------------------
if ! CAPTURE_TMP="$(mktemp --suffix=.png \
        "${PLAYTHROUGH_FRAMES_DIR}/.${FRAME_NAME}.XXXXXX" 2>/dev/null)"; then
    die "${EX_CAPTURE}" "cannot create a temporary file for \
${FRAME_FILE} in ${PLAYTHROUGH_FRAMES_DIR}"
fi
case "${CAPTURE_TOOL}" in
    import)
        # The contracted form.
        _cap_rc=0
        timeout "${GRAB_TIMEOUT}" \
            "${CAPTURE_BIN}" -window root "png:${CAPTURE_TMP}" ||
            _cap_rc=$?
        if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
            die "${EX_CAPTURE}" "import -window root did not finish \
within ${GRAB_TIMEOUT}s for ${FRAME_FILE} on DISPLAY=${DISPLAY} and \
was stopped; an X server that has stopped answering hangs the grab \
rather than failing it"
        elif [ "${_cap_rc}" -ne 0 ]; then
            die "${EX_CAPTURE}" "import -window root failed (exit \
${_cap_rc}) for ${FRAME_FILE} on DISPLAY=${DISPLAY}"
        fi
        ;;
    scrot)
        # scrot grabs the whole screen -- the root window -- when it is given
        # neither -u nor -s, so the frame is equivalent.
        _cap_rc=0
        timeout "${GRAB_TIMEOUT}" \
            "${CAPTURE_BIN}" -o "${CAPTURE_TMP}" || _cap_rc=$?
        if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
            die "${EX_CAPTURE}" "scrot did not finish within \
${GRAB_TIMEOUT}s for ${FRAME_FILE} on DISPLAY=${DISPLAY} and was \
stopped"
        elif [ "${_cap_rc}" -ne 0 ]; then
            die "${EX_CAPTURE}" "scrot failed (exit ${_cap_rc}) for \
${FRAME_FILE} on DISPLAY=${DISPLAY}"
        fi
        ;;
    *)
        # Unreachable today -- the preflight sets CAPTURE_TOOL to exactly one
        # of the two names above -- and present anyway, because a case that
        # falls through silently would raise GRABBED, capture nothing, and then
        # be reported by the next block as "wrote no file", which names the
        # symptom instead of the cause.
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
if [ ! -f "${CAPTURE_TMP}" ]; then
    die "${EX_CAPTURE}" "${CAPTURE_TOOL} reported success but wrote no \
file for ${FRAME_FILE}"
fi

FRAME_BYTES="$(wc -c <"${CAPTURE_TMP}")"
if [ "${FRAME_BYTES}" -le 0 ]; then
    die "${EX_CAPTURE}" "the capture of ${FRAME_FILE} is empty; \
${CAPTURE_TOOL} wrote a zero-byte file"
fi

# identify reports the format and the size in one call.
_cap_rc=0
_cap_identify="$(
    timeout "${IDENTIFY_TIMEOUT}" \
        "${PLAYTHROUGH_BIN_IDENTIFY}" -format '%m %wx%h\n' \
            "${CAPTURE_TMP}" 2>&1
 )" || _cap_rc=$?
if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
    die "${EX_CAPTURE}" "identify did not finish within \
${IDENTIFY_TIMEOUT}s on the capture of ${FRAME_FILE} and was stopped"
elif [ "${_cap_rc}" -ne 0 ]; then
    die "${EX_CAPTURE}" "identify could not read the capture of \
${FRAME_FILE} as an image (exit ${_cap_rc}): ${_cap_identify}"
fi
_cap_identify="${_cap_identify%%$'\n'*}"
FRAME_FORMAT="${_cap_identify%% *}"
FRAME_GEOMETRY="${_cap_identify##* }"
unset _cap_identify

if [ "${FRAME_FORMAT}" != "PNG" ]; then
    die "${EX_CAPTURE}" "the capture of ${FRAME_FILE} is a \
${FRAME_FORMAT}, not a PNG; the pipeline reads and encodes PNG frames \
only"
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
# This is the guard against the pipeline's one silent catastrophe.
# ---------------------------------------------------------------------
_cap_rc=0
_cap_luma="$(
    timeout "${LUMA_TIMEOUT}" \
        "${PLAYTHROUGH_BIN_CONVERT}" "${CAPTURE_TMP}" -colorspace Gray \
            -format '%[fx:mean] %[fx:standard_deviation]' info: 2>&1
 )" || _cap_rc=$?
if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
    die "${EX_CAPTURE}" "the luminance measurement did not finish \
within ${LUMA_TIMEOUT}s on ${FRAME_PATH} and was stopped; the non-blank \
gate cannot be skipped, so the frame is withdrawn rather than kept \
unchecked"
elif [ "${_cap_rc}" -ne 0 ]; then
    die "${EX_CAPTURE}" "convert could not measure the luminance of \
${FRAME_PATH} (exit ${_cap_rc}): ${_cap_luma}"
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
# PUBLISH. One atomic rename over the reservation.
# ---------------------------------------------------------------------
if ! mv -f -- "${CAPTURE_TMP}" "${FRAME_PATH}"; then
    die "${EX_CAPTURE}" "cannot publish the verified capture to \
${FRAME_FILE}"
fi
CAPTURE_TMP=""
if ! chmod 600 -- "${FRAME_PATH}"; then
    die "${EX_CAPTURE}" "cannot set the mode of ${FRAME_FILE}"
fi

# ---------------------------------------------------------------------
# THE CAPTURE DIGEST, taken here and nowhere else.
# ---------------------------------------------------------------------
FRAME_SHA256=""
_cap_rc=0
_cap_digest="$(
    timeout "${IDENTIFY_TIMEOUT}" \
        "${PLAYTHROUGH_BIN_SHA256SUM}" -- "${FRAME_PATH}" 2>&1
)" || _cap_rc=$?
if [ "${_cap_rc}" -ne 0 ]; then
    die "${EX_CAPTURE}" "cannot hash ${FRAME_FILE} (exit ${_cap_rc}): \
$(printf '%s' "${_cap_digest}" | head -c 200 | tr '\n' '|').  A frame \
whose bytes are not attested at the moment they are published is not \
evidence of anything later, so it is withdrawn rather than recorded."
fi
FRAME_SHA256="${_cap_digest%% *}"
if ! [[ "${FRAME_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
    die "${EX_CAPTURE}" "the digest of ${FRAME_FILE} came back as \
'${FRAME_SHA256}', which is not 64 lowercase hex digits"
fi

# BINDING THE DATE ROW TO THE PIXELS.
# The audit row records what the sidebar's DATE line said, and that is the
# evidence timeline.py reconciles a backwards clock against -- so a row
# attributed to the wrong pixels can move a whole day of game time.
if [ "${AUDIT_MODE}" = "on" ]; then
    AUDIT_ARGS+=(--audit-sha256 "${FRAME_SHA256}")
fi

# ---------------------------------------------------------------------
# THE CROP RECTANGLE. Computed, never hard-coded.
# ---------------------------------------------------------------------
# AND A COMPUTATION THAT FAILS IS FATAL -- IT DOES NOT FALL BACK.
# Substituting either documented example when the computation cannot be run is
# the one response that cannot be right here, because each is correct for ONE
# layout only and nothing has checked which layout this run is drawing -- the
# check is precisely what just failed.
# ---------------------------------------------------------------------
CLOCK_RECT=""
CLOCK_RECT_FROM=""
if [ "${CLOCK_MODE}" = "off" ]; then
    # No crop is resolved because none will be applied: with the clock read
    # off, nothing crops this frame at all.
    CLOCK_RECT_FROM="skipped"
    playthrough_log "the clock read is off, so no sidebar crop is" \
        "resolved for ${FRAME_FILE} and none is reported"
elif [ -n "${RECT_OVERRIDE}" ]; then
    CLOCK_RECT="${RECT_OVERRIDE}"
    CLOCK_RECT_FROM="override"
    playthrough_warn "using the EXPLICIT crop override" \
        "PLAYTHROUGH_CAPTURE_RECT=${CLOCK_RECT} instead of computing" \
        "it from this run's configuration; the reading is only as" \
        "right as that rectangle"
else
    if [ ! -f "${GEOMETRY_SCRIPT}" ]; then
        die "${EX_GEOMETRY}" "missing ${GEOMETRY_SCRIPT}, which is \
where the sidebar crop is computed.  A fixed rectangle is NOT \
substituted for it, because the right one depends on the sidebar \
layout in force: \
${DEFAULT_LAYOUT_RECT} for the engine default \
${DEFAULT_LAYOUT_NAME}, ${EXAMPLE_RECT} for ${EXAMPLE_RECT_LAYOUT}, \
and a different width again for each of the other presets that ship in \
data/json/ui.  Cropping the wrong column reads as an unreadable clock \
rather than as an error, so every duration would fall to the floor \
while every count still tallied.  Restore the script, or set \
PLAYTHROUGH_CAPTURE_RECT explicitly to accept a fixed rectangle \
(the form is ${EXAMPLE_RECT})."
    fi
    _cap_rc=0
    # stdout carries the geometry and NOTHING else, which is why stderr
    # goes to the scratch file rather than into this capture: every
    # value sidebar_geometry.py had to default is announced on stderr,
    # and on a fresh userdir there are several.  They are relayed below.
    _cap_rect="$(
        timeout "${GEOMETRY_TIMEOUT}" \
            "${PLAYTHROUGH_PYTHON}" -B "${GEOMETRY_SCRIPT}" \
            2>"${STAGE_ERR}"
     )" || _cap_rc=$?
    _cap_detail="$(stage_stderr)"
    if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
        die "${EX_GEOMETRY}" "sidebar_geometry.py did not finish \
within ${GEOMETRY_TIMEOUT}s and was stopped, so the sidebar crop for \
${FRAME_FILE} is unknown.  stderr: ${_cap_detail:-<none>}"
    elif [ "${_cap_rc}" -ne 0 ]; then
        die "${EX_GEOMETRY}" "sidebar_geometry.py could not compute \
the sidebar crop for ${FRAME_FILE} (exit ${_cap_rc}): \
${_cap_detail:-<no diagnostic>}.  A fixed rectangle is NOT substituted \
for it -- each sidebar preset needs its own (${DEFAULT_LAYOUT_RECT} for \
the engine default ${DEFAULT_LAYOUT_NAME}, ${EXAMPLE_RECT} for \
${EXAMPLE_RECT_LAYOUT}), and this run's configuration is exactly what \
could not be read.  Fix the configuration, or set \
PLAYTHROUGH_CAPTURE_RECT explicitly to accept a fixed rectangle (the \
form is ${EXAMPLE_RECT})."
    fi
    # Relayed even on success: a crop computed from defaulted values is
    # still a crop derived from a configuration nobody confirmed, and
    # that is worth seeing in the session log.
    if [ -n "${_cap_detail}" ]; then
        playthrough_warn "sidebar_geometry.py reported:" \
            "${_cap_detail}"
    fi
    CLOCK_RECT="${_cap_rect%%$'\n'*}"
    CLOCK_RECT_FROM="computed"
    unset _cap_rect _cap_detail
fi

if [ "${CLOCK_RECT_FROM}" != "skipped" ] &&
   ! [[ "${CLOCK_RECT}" =~ ${GEOMETRY_RE} ]]; then
    die "${EX_CLOCK_FAULT}" "the sidebar crop resolved to \
'${CLOCK_RECT}', which is not an ImageMagick WxH+X+Y geometry"
fi

# ---------------------------------------------------------------------
# THE CLOCK READ. An assist that is allowed to fail, and never allowed to
# invent.
# ---------------------------------------------------------------------
CLOCK=""
CLOCK_STATUS=""
CLOCK_SOURCE="none"
TIME_PHRASE=""
CLOCK_DATE=""
OCR_RC=0
OCR_OUT=""
# READER_RC is THE status of the reader that actually ran.
READER_RC=0
INLINE_RC=0
# Whether this frame's date evidence actually reached the sidecar: "yes", "no",
# or "off" when auditing was not asked for.
AUDIT_RECORDED="no"
if [ "${AUDIT_MODE}" != "on" ]; then
    AUDIT_RECORDED="off"
fi

# The sidebar DATE line, and why this file reports it at all.
DATE_TEXT=""
DATE_STATUS="skipped"

# ocr_readings -- one delegate call for ALL THREE readings, and the date
# evidence persisted in the same breath.
ocr_readings() {
    local line key value
    OCR_OUT=""
    OCR_RC=0
    CLOCK=""
    TIME_PHRASE=""
    CLOCK_DATE=""
    if OCR_OUT="$(
            timeout "${OCR_TIMEOUT}" \
                "${PLAYTHROUGH_PYTHON}" -B "${OCR_SCRIPT}" \
                --kv \
                --strict-path \
                --cross-check \
                --frames-dir "${PLAYTHROUGH_FRAMES_DIR}" \
                --rect "${CLOCK_RECT}" \
                "${AUDIT_ARGS[@]}" \
                "${FRAME_PATH}"
         )"; then
        OCR_RC=0
    else
        OCR_RC=$?
    fi
    # Parsed even on a non-zero exit: 1 means "read, nothing there",
    # and the empty values it prints are the honest answer.  Only a
    # fault (2 and above) prints nothing to parse.
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        key="${line%%=*}"
        value="${line#*=}"
        case "${key}" in
            CLOCK) CLOCK="${value}" ;;
            TIME_PHRASE) TIME_PHRASE="${value}" ;;
            CLOCK_DATE) CLOCK_DATE="${value}" ;;
            *)
                playthrough_warn "ignoring unrecognised reading" \
                    "'${key}' from ${OCR_SCRIPT} for ${FRAME_FILE}"
                ;;
        esac
    done <<<"${OCR_OUT}"
    return 0
}

# possible_clock HH:MM:SS -- true when the engine could have rendered it.
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
INLINE_OUT=""
inline_clock() {
    local text="" matches="" candidate="" rc=0 detail=""
    INLINE_OUT=""
    # Both stages' stderr is kept, not discarded.
    : >"${STAGE_ERR}"
    # `cmd || rc=$?`, NOT `if ! cmd; then rc=$?`: inside the body of an `if !`
    # the special parameter holds the status of the NEGATION, which is always
    # 0.
    text="$(
        timeout "${OCR_TIMEOUT}" \
            "${PLAYTHROUGH_BIN_CONVERT}" "${FRAME_PATH}" \
                -crop "${CLOCK_RECT}" +repage \
                -colorspace Gray -resize 200% -normalize png:- \
                2>"${STAGE_ERR}" |
            timeout "${OCR_TIMEOUT}" \
                "${PLAYTHROUGH_BIN_TESSERACT}" stdin stdout \
                    2>>"${STAGE_ERR}"
     )" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        detail="$(stage_stderr)"
        if [ "${rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
            playthrough_warn "the inline convert|tesseract chain did" \
                "not finish within ${OCR_TIMEOUT}s on ${FRAME_FILE}" \
                "and was stopped; reporting no reading rather than" \
                "guessing.  stderr: ${detail:-<none>}"
        else
            playthrough_warn "the inline convert|tesseract chain" \
                "failed (exit ${rc}) reading the clock from" \
                "${FRAME_FILE} at crop ${CLOCK_RECT}; reporting no" \
                "reading rather than guessing.  stderr:" \
                "${detail:-<none>}"
        fi
        return 2
    fi
    # `|| true` is required, not lazy: no match is an EXPECTED outcome -- most
    # menu keystrokes photograph a screen with no clock on it -- and errexit
    # would otherwise turn an honest absence into a script failure.
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
elif [ "${OCR_PREFLIGHT_FAILED}" -eq 0 ] && [ -f "${OCR_SCRIPT}" ] &&
     [ -x "${PLAYTHROUGH_PYTHON}" ]; then
    # env.sh has already VERIFIED this interpreter -- ownership and writability
    # of the binary and of every directory above it -- and refused to finish
    # sourcing if it did not pass.
    CLOCK_SOURCE="ocr_clock.py"
    ocr_readings
    READER_RC="${OCR_RC}"
    # ocr_clock.py writes the audit record before it prints anything, so
    # a clean read (0) or an honest "nothing there" (1) both mean the
    # record reached the DATE AUDIT; a fault means it did not.
    if [ "${AUDIT_MODE}" = "on" ] && [ "${READER_RC}" -le 1 ]; then
        AUDIT_RECORDED="yes"
    fi
    case "${READER_RC}" in
        0)
            CLOCK_STATUS="read"
            ;;
        1)
            # Read, and there was no clock on this screen -- which is
            # what most menu keystrokes photograph.  A phrase or a date
            # may still have come back, and both are kept.
            CLOCK=""
            CLOCK_STATUS="unreadable"
            ;;
        "${TIMEOUT_EXPIRED}")
            CLOCK_STATUS="fault"
            CLOCK=""
            playthrough_warn "${OCR_SCRIPT} did not finish within" \
                "${OCR_TIMEOUT}s on ${FRAME_FILE} and was stopped"
            ;;
        *)
            # A FAULT CARRIES NO READING.
            CLOCK_STATUS="fault"
            CLOCK=""
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
    READER_RC="${INLINE_RC}"
    case "${READER_RC}" in
        0)
            CLOCK="${INLINE_OUT}"
            CLOCK_STATUS="read"
            ;;
        1)
            CLOCK_STATUS="unreadable"
            ;;
        *)
            CLOCK_STATUS="fault"
            CLOCK=""
            ;;
    esac
    # The inline chain reads a clock and nothing else: the date and the coarse
    # phrase are recognised by ocr_clock.py's own patterns, and duplicating
    # them here is exactly the divergence delegation exists to prevent.
    playthrough_warn "the inline reader performs no date extraction," \
        "so no date is reported for ${FRAME_FILE} and DATE_STATUS is" \
        "'unavailable' rather than 'unreadable': nothing looked"
    # And when the audit WAS asked for, the consequence downstream is
    # named too -- timeline.py must treat a frame with no record as
    # UNKNOWN, never as a day that did not turn.
    if [ "${AUDIT_MODE}" = "on" ]; then
        playthrough_warn "no date evidence was recorded for" \
            "${FRAME_FILE}, so timeline.py has no date for this frame" \
            "and must reconcile rather than assume the day did not" \
            "turn"
    fi
fi

# Whatever produced it, a reading leaves this file only if it is genuinely the
# contracted shape AND genuinely possible.
if [ "${CLOCK_STATUS}" = "read" ]; then
    if ! [[ "${CLOCK}" =~ ^${CLOCK_PATTERN}$ ]] ||
       ! possible_clock "${CLOCK}"; then
        die "${EX_CLOCK_FAULT}" "${CLOCK_SOURCE} returned \
'${CLOCK}' for ${FRAME_FILE}, which is not a possible \
HH:MM:SS reading.  Refusing to emit it: a reading that cannot be true \
is not reported as a clock."
    fi
fi

# A FAULT is not an unreadable clock.
if [ "${CLOCK_STATUS}" = "fault" ]; then
    if [ "${STRICT_CLOCK}" -eq 1 ]; then
        die "${EX_CLOCK_FAULT}" "the clock read faulted on \
${FRAME_FILE} (${CLOCK_SOURCE} exit ${READER_RC}).  This is a fault, \
not an unreadable clock: fix it -- seed_options.py sets 24_HOUR=24h -- \
and recapture.  Carrying on with the fault recorded is a DIAGNOSTIC \
action (PLAYTHROUGH_CAPTURE_MODE=diagnostic with \
PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0), and such a capture is withdrawn \
rather than kept: a frame whose clock could not be read has no \
duration to derive."
    fi
    # STRICT_CLOCK=0 IS DIAGNOSTIC-ONLY, so this is not a frame being kept: the
    # fault is RETAINED in the payload (CLOCK_STATUS=fault, no reading) for
    # whoever is diagnosing it, and the PNG is withdrawn out of the working
    # tree at the commit point below, which exits EX_DIAGNOSTIC.
    playthrough_warn "the clock read faulted on ${FRAME_FILE} and" \
        "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0, so the fault is recorded" \
        "as CLOCK_STATUS=fault with no reading and this DIAGNOSTIC" \
        "capture continues; the frame itself is withdrawn to" \
        "${REJECT_DIR} rather than added to" \
        "${PLAYTHROUGH_FRAMES_DIR}"
fi

# ---------------------------------------------------------------------
# THE TELEMETRY HANDOFF -- REPORTED HERE, PERSISTED BY THE ORCHESTRATOR
# Every per-frame observation this invocation made -- the clock, the coarse
# phrase, the sidebar DATE line, the crop they were read from, the luminance,
# the geometry, the capture tool and the instant of the grab -- leaves through
# the machine payload below, and NOTHING is appended to the telemetry sidecar
# from here.
# ---------------------------------------------------------------------


# The coarse phrase and the date come back from the SAME read as the clock, so
# there is nothing left to fetch here -- one OCR pass per frame, and three
# readings that therefore cannot disagree about the same pixels.
if [ "${PHRASE_MODE}" = "off" ] ||
   { [ "${PHRASE_MODE}" = "auto" ] &&
     [ "${CLOCK_STATUS}" = "read" ]; }; then
    TIME_PHRASE=""
fi

# ---------------------------------------------------------------------
# The date's status, derived from the read that already happened.
# ---------------------------------------------------------------------
if [ "${CLOCK_MODE}" != "on" ]; then
    DATE_STATUS="skipped"
elif [ "${CLOCK_SOURCE}" != "ocr_clock.py" ]; then
    DATE_STATUS="unavailable"
elif [ -n "${CLOCK_DATE}" ]; then
    DATE_TEXT="${CLOCK_DATE}"
    DATE_STATUS="read"
elif [ "${CLOCK_STATUS}" = "fault" ]; then
    DATE_STATUS="fault"
else
    DATE_STATUS="unreadable"
fi

# ---------------------------------------------------------------------
# OUTPUT, THEN THE LOG, THEN -- LAST OF ALL -- THE COMMIT POINT.
# The order below is the whole of this file's atomicity guarantee, and it is
# deliberate to the line.
# ---------------------------------------------------------------------

# Build the complete payload first.  `line KEY VALUE` appends to it
# rather than writing, so a partially-written contract is impossible:
# either every key reaches stdout or none of them does.
PAYLOAD=""
line() {
    PAYLOAD="${PAYLOAD}$1=$2
"
}

# The mode comes first because it decides what the rest of the payload
# describes.
line CAPTURE_MODE "${CAPTURE_MODE}"
line FRAME_INDEX "${FRAME_INDEX}"
line FRAME_NAME "${FRAME_NAME}"
if [ "${CAPTURE_MODE}" = "production" ]; then
    line FRAME_FILE "${FRAME_FILE}"
    line FRAME_PATH "${FRAME_PATH}"
    line DIAGNOSTIC_PATH ""
else
    line FRAME_FILE ""
    line FRAME_PATH ""
    line DIAGNOSTIC_PATH "${REJECT_DIR}/${FRAME_NAME}"
fi
line FRAME_BYTES "${FRAME_BYTES}"
# The sha256 of the bytes that were published, taken immediately after the
# atomic rename.
if [ "${CAPTURE_MODE}" = "production" ]; then
    line FRAME_SHA256 "${FRAME_SHA256}"
else
    line FRAME_SHA256 ""
fi
line FRAME_FORMAT "${FRAME_FORMAT}"
line FRAME_GEOMETRY "${FRAME_GEOMETRY}"
line REAL_TS "${REAL_TS}"
line CAPTURE_TOOL "${CAPTURE_TOOL}"
line LUMA_MEAN "${LUMA_MEAN}"
line LUMA_STDDEV "${LUMA_STDDEV}"
line CLOCK_RECT "${CLOCK_RECT}"
line CLOCK_RECT_FROM "${CLOCK_RECT_FROM}"
line CLOCK_SOURCE "${CLOCK_SOURCE}"
line CLOCK_STATUS "${CLOCK_STATUS}"
line CLOCK "${CLOCK}"
line TIME_PHRASE "${TIME_PHRASE}"
line CLOCK_DATE "${CLOCK_DATE}"
line DATE "${DATE_TEXT}"
line DATE_STATUS "${DATE_STATUS}"
line DATE_AUDIT "${AUDIT_RECORDED}"
if [ "${CAPTURE_MODE}" = "production" ]; then
    line OBSERVATIONS "${OBSERVATIONS}"
else
    # A withdrawn frame is owed no row at all, so no destination is named for
    # one.
    line OBSERVATIONS ""
fi

# One write.  A failure here is fatal and the frame is withdrawn: the
# caller must never be left believing a frame is unreported when it is
# on disk, or reported when it is not.
if ! printf '%s' "${PAYLOAD}"; then
    die "${EX_CAPTURE}" "the output contract could not be written to \
stdout for ${FRAME_FILE}; the frame is withdrawn so that no frame \
exists without a caller that knows about it"
fi

# ---------------------------------------------------------------------
# THE LAST FALLIBLE STATEMENT, and it is deliberately BEFORE the commit point
# rather than after it.
# ---------------------------------------------------------------------
if [ "${CAPTURE_MODE}" = "production" ]; then
    playthrough_log "captured ${FRAME_FILE} (${FRAME_GEOMETRY}," \
        "${FRAME_BYTES} bytes) clock=${CLOCK:-<none>}" \
        "status=${CLOCK_STATUS} date=${DATE_TEXT:-<none>}"
fi

# ---------------------------------------------------------------------
# THE COMMIT POINT. The frame has passed every check and this invocation's
# whole contract has been delivered, so the frame is ours to keep: the EXIT
# trap will no longer withdraw it, and a superseded frame moved aside stays
# aside.
# ---------------------------------------------------------------------
if [ "${CAPTURE_MODE}" = "production" ]; then
    KEPT=1
    BACKUP=""
    exit "${EX_OK}"
fi

playthrough_warn "DIAGNOSTIC capture of index ${FRAME_INDEX}" \
    "(${FRAME_GEOMETRY}, ${FRAME_BYTES} bytes)" \
    "clock=${CLOCK:-<none>} status=${CLOCK_STATUS}.  The frame is" \
    "being withdrawn to ${REJECT_DIR}/${FRAME_NAME}; no frame was" \
    "added to ${PLAYTHROUGH_FRAMES_DIR}, no telemetry row is owed or" \
    "reported, and this invocation exits ${EX_DIAGNOSTIC} so it" \
    "cannot be mistaken for a capture that belongs to the record."
exit "${EX_DIAGNOSTIC}"
