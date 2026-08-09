#!/usr/bin/env bash
# shellcheck shell=bash
#
# playthrough/tooling/verify_artifacts.sh -- THE ACCEPTANCE GATE for the
# Cataclysm-DDA playthrough capture and cinematography subsystem.
#
#     cd <repository root>
#     playthrough/tooling/verify_artifacts.sh
#     playthrough/tooling/verify_artifacts.sh --base <commit>
#
# Every acceptance criterion this feature has is a COMMAND or a
# CHECKABLE PROPERTY rather than an adjective, and this file is where
# those commands live.  It reads the committed artifacts -- the frames,
# the record, the timeline, the film, the caption track, the transcripts
# and the engine-written userdir -- and reports, one property at a time,
# whether each is what it is claimed to be.
#
# IT MODIFIES NOTHING INSIDE THE WORKING TREE.  Its only writes are into
# a private scratch directory under the mode-0700 runtime root env.sh
# created, and that directory is removed on exit.  Nothing it does can
# change the evidence it is measuring, which is the whole point: a gate
# that edits what it inspects proves nothing.
#
# ---------------------------------------------------------------------
# WHY IT EXISTS: THREE FAILURE MODES THAT ARE OTHERWISE SILENT
#
# Most of the ways this pipeline can go wrong announce themselves -- a
# missing tool, a crashed encode, an unparsable JSON row.  Three do not,
# and those three are the reason this file exists.  Each is turned into
# a loud, named failure below.
#
#   1. A SAVE THAT IS COMMITTED IN APPEARANCE ONLY.  Cataclysm-DDA
#      writes per-character save files whose names begin with '#'
#      (src/game_io.cpp:601-641), and .gitignore carries `\#*`
#      (.gitignore:131) plus an unanchored `*.log` (.gitignore:31) and
#      `debug.log` (.gitignore:79).  Without the terminal
#      `!/playthrough/**` negation, `git add` SKIPS the save and EXITS
#      SUCCESSFULLY.  Every count downstream still tallies; the save is
#      simply not there.  Answered by check group 7, which asserts both
#      `git ls-files` membership and `git check-ignore` non-membership
#      for every artifact class.
#
#   2. A FILM THAT IS ENTIRELY BLACK.  With SDL_VIDEODRIVER=dummy the
#      game runs, the captures succeed, the encode succeeds, the frame
#      count equals the row count, and the only symptom is that nothing
#      is visible.  Answered by check group 6, the luminance gate:
#      grayscale mean > 0 AND standard deviation > 0, on sampled
#      captures and on a frame extracted from the finished film.  Both
#      terms are load-bearing -- the mean catches a black frame, the
#      deviation additionally catches a uniform solid-colour one that a
#      mean-only test would pass.
#
#   3. CAPTIONS THAT DRIFT OUT OF SYNC.  A transition inserts real
#      seconds into video time.  A caption generator that walks frame
#      durations without charging those seconds to the cue cursor emits
#      cues that are correct at the start and increasingly wrong by the
#      end.  Answered by check groups 3 and 5, which assert the
#      invariant sum(durations) + sum(transitions) == total == final cue
#      end AND compare every cue window against the timeline's own.
#
# ---------------------------------------------------------------------
# THE REPORTING MODEL: RUN EVERY CHECK, THEN EXIT NON-ZERO
#
# This file runs under `set -euo pipefail`, under which a bare failing
# command aborts the script.  For a gate that is precisely the wrong
# behaviour: the operator would be told about the first broken property
# and left ignorant of the other sixty.  So no check is expressed as a
# bare command.  Every one records a verdict through record_pass,
# record_fail or record_info, the counters accumulate, and the exit
# status is decided ONCE at the end.
#
# There is no SKIP verdict, deliberately.  A gate that quietly skips
# half its checks is worse than no gate, so a tool this file needs and
# cannot find is a FAILURE of the gate rather than an excuse to stop
# measuring.  Every check below has a defined verdict on every host.
#
# EVERY VERDICT PRINTS ITS EVIDENCE.  A FAIL prints the observed value
# next to the expected one; a PASS prints the observed value too, so the
# report is a record of what was measured and not merely an assertion
# that somebody once measured it.
#
# ---------------------------------------------------------------------
# WHAT THE CHECK GROUPS COVER
#
#   1  the measuring environment  the tools, the interpreter, the trust
#                                 state, and that every artifact this
#                                 gate reads is present and readable
#   2  one frame per keystroke    frames == rows, contiguous indices,
#                                 the six-key record schema
#   3  the timeline               the 0.25 s floor, the 10 s ceiling,
#                                 the transition flag, the materialised
#                                 transition groups, the invariant
#   4  the container              h264 1920x1080, duration, no audio
#   5  the caption track          mov_text/eng, cue structure, cue
#                                 windows, not burned in, the
#                                 transcripts, the meta-language gate
#   6  the luminance gate         mean > 0 and std > 0
#   7  version control            the save is really tracked, nothing
#                                 is silently ignored, nothing is left
#                                 uncommitted, the commit order
#   8  no cheating                no debug keybinding, no debug-mode
#                                 activation in the engine's own log
#   9  the binary and hygiene     +tiles, scoped flake8, the timeline
#                                 test suite, the change surface
#
# ---------------------------------------------------------------------
# TWO HOST FACTS THAT SHAPE THE CODE
#
# IMAGEMAGICK IS CALLED THROUGH ITS CLASSIC ENTRY POINTS -- `convert`,
# `identify`, `compare`.  The unified `magick` entry point exists only
# on the version 7 branch, so code written against it fails outright on
# a version 6 host; the classic names work on both.  env.sh additionally
# documents that ImageMagick dispatches on argv[0], which is why the
# resolved PATH entry is invoked rather than its symlink target.
#
# THE SHELL CANNOT COMPARE FLOATING POINT.  `[ "0.27" -gt 0 ]` is not a
# working test -- it is an integer comparison against a string, and it
# fails at the syntax level.  Every threshold in this file goes through
# awk, with the values passed in via -v as data rather than pasted into
# the program text.
#
# ---------------------------------------------------------------------
# EXIT STATUS
#
#   0  every check passed
#   1  at least one check failed; the count is on the last line
#   2  usage error -- an unknown option or a malformed value
#   3  layout error -- this file cannot locate itself, or env.sh is
#      missing or refused to load
#
# Requires bash: BASH_SOURCE, arrays and `local` are all used.
# ---------------------------------------------------------------------

set -euo pipefail
set -o errtrace

# The ERR trap names the line, because a gate that dies without saying
# where is a gate nobody can repair.  It fires only on an unhandled
# failure: every deliberate check runs inside an `if` or an `||`, both
# of which errexit exempts.
_va_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "verify_artifacts.sh failed at line ${2} (exit ${1})" >&2
}
trap '_va_on_error "$?" "${LINENO}"' ERR

readonly EX_OK=0
readonly EX_FAILED=1
readonly EX_USAGE=2
readonly EX_LAYOUT=3

# ---------------------------------------------------------------------
# LOCATING THIS FILE, AND THE ENVIRONMENT CONTRACT
#
# The pattern is the repository's own -- build-scripts/clang-tidy-run.sh
# resolves its directory from BASH_SOURCE the same way -- and it is what
# keeps the gate correct no matter which directory it is invoked from.
# env.sh is then the SINGLE definition of every artifact path, the
# verified interpreter, the tool resolution and PYTHONDONTWRITEBYTECODE;
# none of it is restated here.
# ---------------------------------------------------------------------
_va_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_va_script_dir}" ]; then
    printf '%s\n' "verify_artifacts.sh: FATAL: cannot resolve my own \
directory, so I cannot find the environment contract" >&2
    exit "${EX_LAYOUT}"
fi

_va_env_file="${_va_script_dir}/env.sh"
if [ ! -f "${_va_env_file}" ]; then
    printf '%s\n' "verify_artifacts.sh: FATAL: missing \
${_va_env_file}; the artifact layout, the tool verification and the \
interpreter live there and are never redefined here" >&2
    exit "${EX_LAYOUT}"
fi

# The `source=` directive lets `shellcheck -x` follow env.sh and check
# this file against it; SC1091 silences the run without -x, where the
# file cannot be followed at all.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_va_env_file}"; then
    printf '%s\n' "verify_artifacts.sh: FATAL: ${_va_env_file} refused \
to load; fix the environment contract before measuring anything \
against it" >&2
    exit "${EX_LAYOUT}"
fi
unset _va_script_dir _va_env_file

# Every path this gate reads is repository-relative from here, which is
# also the working directory the engine itself requires.
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# WHAT THE ARTIFACTS ARE REQUIRED TO BE
#
# These are the expected values, named once.  Where a value also exists
# as a constant inside a sibling module it is CROSS-CHECKED against that
# module rather than merely restated -- check group 3 imports
# timeline.py, make_transitions.py and render_movie.py and fails if the
# producer's own constants have drifted from the numbers below.  That
# way a future edit to a producer cannot quietly move the goalposts this
# gate measures against.
# ---------------------------------------------------------------------
readonly VIDEO_CODEC_EXPECTED="h264"
readonly SUBTITLE_CODEC_EXPECTED="mov_text"
readonly SUBTITLE_LANGUAGE_EXPECTED="eng"

# The floor and the ceiling, in seconds of on-screen time per capture,
# and the length of one inserted transition unit.
readonly DURATION_FLOOR="0.25"
readonly DURATION_CEIL="10.0"
readonly TRANSITION_SECONDS="1.0"

# A transition is materialised as still images rather than spliced in as
# a second video segment, which is what keeps the film to a single
# encoder pass.  Twelve images at 12 fps make the 1.0 s unit.
readonly TRANSITION_FRAMES_PER_GROUP="12"

# How far the encoded container may sit from the timeline's declared
# total.  A variable-frame-rate encode does not land on the arithmetic
# total exactly; a SHORTFALL of a whole frame's worth or more is the
# signature of a concat list whose final `file` entry was not repeated,
# which was measured once as a 10.52 s container against an 11.75 s
# subtitle stream.  0.12 s is render_movie.py's own tolerance and is
# asserted against it in check group 3.
readonly CONTAINER_TOLERANCE="0.12"

# Cue and duration arithmetic is compared at the timeline's own rounding
# of three decimal places, so 0.0005 s of float representation noise is
# not reported as a discrepancy.
readonly ARITHMETIC_EPSILON="0.0005"

# The offset, in seconds, at which a frame is extracted from each film
# for the luminance and burned-in-caption checks.  One second is past
# the opening captures and inside ordinary play.
readonly EXTRACT_OFFSET="1"

# The calibration reading from a real rendered capture, quoted so the
# report carries the provenance of the threshold.  IT IS NOT A BOUND:
# the assertion is strictly `> 0` on both terms, because how bright a
# frame is depends on the tileset and on what the survivor was looking
# at, and a gate that demanded a magnitude would fail honest captures.
readonly LUMINANCE_REFERENCE="mean=0.270018 std=0.198145 \
(one real frame, quoted as provenance only)"

# How many captures the luminance gate samples: the first, the last, and
# an even spread between them.
#
# WHY THIS IS A SAMPLE AND NOT A SWEEP, STATED PLAINLY.  One grayscale
# reading costs about a fifth of a second, so reading all 326 committed
# captures takes between 80 and 110 seconds -- measured on this host.
# That is not "almost nothing", so the default reads a spread and the
# report always says HOW MANY of HOW MANY it read rather than implying it
# read them all.  `--samples all` reads every capture when the extra
# minute and a half is worth spending, and the exact, whole-set
# complement to this sampled reading is the digest agreement asserted in
# group 3: every capture's sha256 was verified when the timeline was
# computed, so a frame substituted at ANY index changes a digest the
# timeline itself declares.
readonly LUMINANCE_SAMPLES_DEFAULT="32"
readonly LUMINANCE_SAMPLES_ALL="all"

# The engine's own debug actions.  All three are declared in
# data/raw/keybindings.json WITHOUT a `bindings` array -- debug_mode at
# L3398-3403, debug ("Debug menu") at L3404-3409 and debug_hour_timer at
# L3466-3471 -- so they are unbound by default and unreachable by any
# keystroke unless somebody deliberately binds them.  The user
# keybindings file is a COMMITTED artifact, which is what turns "no
# cheating" from a claim into a property a stranger can check.
readonly DEBUG_ACTION_PATTERN='"(debug|debug_mode|debug_hour_timer)"'

# The engine writes its log beside the configuration it was launched
# with.  Both candidate locations are inspected, because which one is
# used has changed between builds and a gate that looked in only one
# would report "no debug activation" without having read anything.  An
# ARRAY, so no expansion has to be left unquoted to split it.
readonly -a DEBUG_LOG_RELATIVE_PATHS=("config/debug.log" "debug.log")

# The complete set of paths outside playthrough/ that this feature is
# allowed to have touched.  Anything else in the change surface is a
# finding: the engine, the content, the build system and CI are all
# consumed read-only.
readonly ALLOWED_FOREIGN_PATHS=".gitignore .gitattributes"

# The unit separator, used between the fields of one verdict line.  A
# NON-whitespace delimiter is required: bash's `read` collapses runs of
# a whitespace IFS character and drops leading and trailing ones, so a
# tab-separated protocol would silently lose an empty field.
readonly VERDICT_SEPARATOR=$'\037'

# ---------------------------------------------------------------------
# THE REPORT
#
# Verdicts go to stdout, because the report IS the product of this file
# and is what gets read, saved and quoted.  Environmental diagnostics go
# to stderr through env.sh's helpers, so a caller can keep the two
# apart.  The trailing VERIFY_* block is the machine-readable summary,
# in the same KEY=value shape the sibling stages publish.
# ---------------------------------------------------------------------
PASSES=0
FAILURES=0
INFOS=0
GROUP=0
SCRATCH=""
BASE_COMMIT=""
# The most recent grayscale reading, so a frame is measured once and the
# same numbers are reported that were judged.
LAST_LUMINANCE=""
LUMINANCE_SAMPLES="${LUMINANCE_SAMPLES_DEFAULT}"

# The tool paths, defaulted to the plain command names so that `set -u`
# cannot trip before check group 1 has resolved and verified them.  A
# tool that is genuinely absent makes the checks that use it FAIL, which
# is the intended behaviour -- the gate keeps measuring everything else.
FFPROBE="ffprobe"
FFMPEG="ffmpeg"
CONVERT="convert"
IDENTIFY="identify"
COMPARE="compare"
GIT="git"
AWK="awk"
GREP="grep"
PYTHON="${PLAYTHROUGH_PYTHON}"

# The linter as an ARRAY rather than a string, because one of the four
# ways it resolves is a multi-word `<python> -B -m flake8`; a string
# would have to be re-split at the call site, which is the shape of
# command construction this pipeline does not use.
FLAKE8_CMD=()

note() {
    printf '%s=%s\n' "$1" "$2"
}

# rel PATH -- the repository-relative spelling, delegated to env.sh so
# there is one implementation of it in the pipeline.
rel() {
    playthrough_rel "$1"
}

# die STATUS MESSAGE... -- for the handful of conditions under which
# there is nothing left to measure.  env.sh's playthrough_die RETURNS 1
# rather than exiting, because it is sourced and an exit there would
# kill an interactive shell; the exit is therefore taken here.
die() {
    local status="$1"
    shift
    playthrough_die "$@" || true
    exit "${status}"
}

group() {
    GROUP=$((GROUP + 1))
    printf '\n=== %d. %s ===\n' "${GROUP}" "$1"
}

record_pass() {
    PASSES=$((PASSES + 1))
    printf 'PASS  %s\n' "$1"
    if [ -n "${2-}" ]; then
        printf '      observed: %s\n' "$2"
    fi
}

record_fail() {
    FAILURES=$((FAILURES + 1))
    printf 'FAIL  %s\n' "$1"
    printf '      observed: %s\n' "${2:-<nothing>}"
    printf '      expected: %s\n' "${3:-<see the check name>}"
}

record_info() {
    INFOS=$((INFOS + 1))
    printf 'INFO  %s: %s\n' "$1" "${2:-<empty>}"
}

# record_warn -- something an operator should see that is not itself a
# verdict on the artifacts.  It does NOT affect the exit status: this
# gate's job is to judge the evidence, and a note about the host it was
# judged on is not evidence.
record_warn() {
    printf 'WARN  %s: %s\n' "$1" "${2:-<empty>}"
}

# ---------------------------------------------------------------------
# THE VERDICT CHANNEL
#
# The arithmetic-heavy checks are written in Python, because JSON,
# floating point and set comparison are what Python is for and because
# the sibling producers' own constants can be imported and cross-checked
# rather than restated.  Each program emits one verdict per line:
#
#     KIND <US> NAME <US> OBSERVED <US> EXPECTED
#
# and this function turns those lines into counted, formatted report
# entries.  It is fed by REDIRECTION from a file rather than by a pipe,
# and that is a correctness requirement rather than a style choice: the
# right-hand side of a pipe runs in a subshell, so every counter this
# function incremented would be discarded when it returned.
# ---------------------------------------------------------------------
consume_verdicts() {
    # Initialised rather than merely declared: under `set -u` a `local`
    # with no value is an unset variable, and the loop's own guard reads
    # ${kind} before the first successful read.
    local kind="" name="" observed="" expected=""
    while IFS="${VERDICT_SEPARATOR}" \
            read -r kind name observed expected || [ -n "${kind}" ]; do
        case "${kind}" in
            '') continue ;;
            PASS) record_pass "${name}" "${observed}" ;;
            FAIL) record_fail "${name}" "${observed}" "${expected}" ;;
            INFO) record_info "${name}" "${observed}" ;;
            WARN) record_warn "${name}" "${observed}" ;;
            *)
                record_fail "the verdict channel is well formed" \
                    "an unparsable line beginning '${kind}'" \
                    "PASS, FAIL, INFO or WARN and separated fields"
                ;;
        esac
    done
}


# emit_checker LABEL
#   Materialise one Python checker from this file's heredoc into SCRATCH.
#   The programs live in the scratch directory rather than in the working
#   tree so that running the gate cannot add an untracked file to the
#   evidence -- which check group 7 would then, correctly, report.
emit_checker() {
    cat >"${SCRATCH}/$1.py"
}

# run_checker LABEL [arg ...]
#   Run one materialised checker, collect its verdicts and fold them into
#   the report.  A crash is itself a FAILURE of the gate -- reported with
#   the tail of its stderr so the cause is visible -- and any verdicts it
#   managed to emit before dying are still counted, so a partial run
#   reports what it did establish rather than nothing at all.
#
#   -B is passed on top of env.sh's PYTHONDONTWRITEBYTECODE=1 because
#   this gate asserts that no stray bytecode exists under playthrough/,
#   and a gate that creates the condition it forbids is worthless.
run_checker() {
    local label="$1"
    shift
    local script="${SCRATCH}/${label}.py"
    local out="${SCRATCH}/${label}.verdicts"
    local err="${SCRATCH}/${label}.stderr"
    : >"${out}"
    if ! "${PYTHON}" -B "${script}" "$@" >"${out}" 2>"${err}"; then
        local detail=""
        detail="$(tail -n 3 "${err}" 2>/dev/null | tr '\n' ' ' || true)"
        record_fail "the ${label} checks completed" \
            "the checker exited non-zero: ${detail:-<no diagnostic>}" \
            "a clean run emitting one verdict per property"
    fi
    consume_verdicts <"${out}"
}

# fact KEY [DEFAULT]
#   Read one value out of the facts file a checker left behind, so a
#   number the shell needs -- the timeline total, the capture count -- is
#   the SAME number the checker measured rather than a second, possibly
#   divergent, reading of the same file.
fact() {
    local key="$1"
    local fallback="${2-}"
    local value=""
    if [ -f "${SCRATCH}/facts" ]; then
        value="$(sed -n "s/^${key}=//p" "${SCRATCH}/facts" \
            2>/dev/null | head -n 1 || true)"
    fi
    if [ -z "${value}" ]; then
        printf '%s' "${fallback}"
        return 0
    fi
    printf '%s' "${value}"
}

# floats_close A B EPSILON -- |A - B| <= EPSILON.
#
# THE SHELL CANNOT COMPARE FLOATING POINT.  `[ "0.27" -gt 0 ]` applies an
# integer operator to a string and fails at the syntax level rather than
# returning a wrong answer, so awk does every comparison in this file --
# as a fixed program with the values handed in through -v, never with a
# value interpolated into the program text.
floats_close() {
    "${AWK}" -v a="$1" -v b="$2" -v eps="$3" 'BEGIN {
        d = a - b
        if (d < 0) { d = -d }
        exit (d <= eps) ? 0 : 1
    }'
}

# is_number VALUE -- a bare decimal, and not ffprobe's "N/A".
is_number() {
    case "${1-}" in
        ''|'N/A'|'n/a') return 1 ;;
        *[!0-9.]*) return 1 ;;
        *) return 0 ;;
    esac
}

# probe_field FILE SELECTOR ENTRIES
#   One ffprobe read in KEY=value form, with the failure surfaced as an
#   empty string rather than as an abort, so a missing stream is a
#   verdict instead of the end of the run.
probe_field() {
    "${FFPROBE}" -v error -select_streams "$2" \
        -show_entries "$3" -of default=nw=1 -i "$1" 2>/dev/null || true
}

# probe_value FILE SELECTOR ENTRY -- the bare first value, or "".
probe_value() {
    "${FFPROBE}" -v error -select_streams "$2" -show_entries "$3" \
        -of default=noprint_wrappers=1:nokey=1 -i "$1" 2>/dev/null |
        head -n 1 || true
}

# probe_format FILE ENTRY -- a container-level value, such as duration.
probe_format() {
    "${FFPROBE}" -v error -show_entries "format=$2" \
        -of default=noprint_wrappers=1:nokey=1 -i "$1" 2>/dev/null |
        head -n 1 || true
}

# luminance PNG -- "mean std" over the grayscale conversion, or "" when
# the file cannot be read.  The mean catches a fully black frame, which
# is what SDL_VIDEODRIVER=dummy produces; the standard deviation
# additionally catches a uniform solid-colour frame, which a mean-only
# test would pass.
luminance() {
    "${CONVERT}" "$1" -colorspace Gray \
        -format '%[fx:mean] %[fx:standard_deviation]' info: \
        2>/dev/null || true
}

# ---------------------------------------------------------------------
# USAGE
# ---------------------------------------------------------------------
usage() {
    cat <<'USAGE'
verify_artifacts.sh -- the acceptance gate for the playthrough capture
subsystem.  Reads the committed artifacts, reports one verdict per
property, and exits non-zero if any property does not hold.

    playthrough/tooling/verify_artifacts.sh [options]

Options:
  --base COMMIT     the commit the change surface is measured from.
                    Defaults to the parent of the first commit that
                    touched playthrough/, which is the point this
                    feature began.
  --samples N       how many captures the luminance gate samples
                    (minimum 2 -- the first and the last; default 32).
  --samples all     read every capture instead of a spread.  Exact, and
                    about a minute and a half slower on a full session.
  -h, --help        print this and exit.

Environment:
  PLAYTHROUGH_VERIFY_BASE     the default for --base.
  PLAYTHROUGH_VERIFY_SAMPLES  the default for --samples.
  PLAYTHROUGH_FLAKE8          the flake8 to lint with, when it is not
                              on PATH and not importable as a module.

Exit status: 0 all checks passed, 1 a check failed, 2 usage, 3 layout.
USAGE
}

parse_arguments() {
    local base="${PLAYTHROUGH_VERIFY_BASE:-}"
    local samples="${PLAYTHROUGH_VERIFY_SAMPLES:-\
${LUMINANCE_SAMPLES_DEFAULT}}"
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --base)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--base needs a commit"
                fi
                base="$2"
                shift 2
                ;;
            --base=*)
                base="${1#--base=}"
                shift
                ;;
            --samples)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--samples needs a count"
                fi
                samples="$2"
                shift 2
                ;;
            --samples=*)
                samples="${1#--samples=}"
                shift
                ;;
            -h|--help)
                usage
                exit "${EX_OK}"
                ;;
            *)
                usage >&2
                die "${EX_USAGE}" "unrecognised argument '$1'"
                ;;
        esac
    done

    # `all` is carried through as a word and resolved against the real
    # capture count later, once that count is known.
    if [ "${samples}" = "${LUMINANCE_SAMPLES_ALL}" ]; then
        LUMINANCE_SAMPLES="${LUMINANCE_SAMPLES_ALL}"
        BASE_COMMIT="${base}"
        return 0
    fi
    # Validated through env.sh's helper rather than by arithmetic on the
    # raw string: bash evaluates command substitution inside $(( )), so
    # an unvalidated number from the environment is code execution and
    # not a number.
    if ! playthrough_validate_int "${samples}" \
            "the luminance sample count" 2 100000; then
        die "${EX_USAGE}" "--samples must be 'all' or an integer of 2" \
            "or more"
    fi
    LUMINANCE_SAMPLES="${PLAYTHROUGH_INT}"
    BASE_COMMIT="${base}"
}

# default_base_commit
#   The parent of the earliest commit that touched playthrough/, which
#   is exactly "the tree as it was before this feature existed" and
#   therefore the right thing to diff a change surface against.
#
#   `tail -1` rather than `git log --reverse | head -1`: head closing
#   the pipe early raises SIGPIPE in git, which pipefail would turn into
#   a failure of the whole assignment.
default_base_commit() {
    local first="" parent=""
    first="$("${GIT}" log --format='%H' -- playthrough 2>/dev/null |
        tail -n 1 || true)"
    if [ -z "${first}" ]; then
        return 1
    fi
    parent="$("${GIT}" rev-parse --verify --quiet "${first}^" \
        2>/dev/null || true)"
    if [ -z "${parent}" ]; then
        return 1
    fi
    printf '%s' "${parent}"
}

# ---------------------------------------------------------------------
# SCRATCH
#
# Confined to the mode-0700 runtime root env.sh created and verified,
# never to a predictable path in a world-writable /tmp, and removed on
# every exit path.  The recursive removal is bounded to the directory
# mktemp just made, which is the only shape of `rm -rf` this pipeline
# permits.
# ---------------------------------------------------------------------
# SC2317: ShellCheck cannot see that a trap handler is called, so the
# body reads as dead code to it.  env.sh carries the same suppression for
# the same reason.
# shellcheck disable=SC2317
_va_cleanup() {
    if [ -n "${SCRATCH}" ] && [ -d "${SCRATCH}" ]; then
        rm -rf -- "${SCRATCH}"
    fi
}
trap _va_cleanup EXIT

open_scratch() {
    local base="${PLAYTHROUGH_RUNTIME_DIR}"
    if [ ! -d "${base}" ]; then
        die "${EX_LAYOUT}" "the runtime directory '$(rel "${base}")'" \
            "does not exist; env.sh creates and verifies it at mode" \
            "0700, so re-source playthrough/tooling/env.sh"
    fi
    SCRATCH="$(mktemp -d "${base}/verify.XXXXXX")"
    if [ -z "${SCRATCH}" ] || [ ! -d "${SCRATCH}" ]; then
        die "${EX_LAYOUT}" "cannot create a scratch directory under" \
            "'$(rel "${base}")'"
    fi
    chmod 700 "${SCRATCH}"
}


# ---------------------------------------------------------------------
# 1  THE MEASURING ENVIRONMENT
#
# A gate has to establish that it can measure before it reports what it
# measured.  A missing tool is a FAILURE of the gate and not a reason to
# stop: the remaining groups still run, and the ones that needed the
# absent tool fail individually and say so.
# ---------------------------------------------------------------------
resolve_tools() {
    local -a wanted=(
        ffprobe ffmpeg convert identify compare git awk grep sed
    )
    if playthrough_require_tools "${wanted[@]}"; then
        record_pass "every command this gate needs is present and \
verified" "${wanted[*]}"
    else
        record_fail "every command this gate needs is present and \
verified" \
            "playthrough_require_tools refused; the reason for each is \
on stderr" \
            "ffprobe, ffmpeg, convert, identify, compare, git, awk, \
grep and sed -- apt: ffmpeg, imagemagick, git, coreutils, grep, sed, \
mawk -- each owned by this user and not group- or world-writable"
    fi
    # Whatever was resolved is used; whatever was not falls back to the
    # bare name so that `set -u` cannot trip and the individual checks
    # fail on their own terms.
    FFPROBE="${PLAYTHROUGH_BIN_FFPROBE:-ffprobe}"
    FFMPEG="${PLAYTHROUGH_BIN_FFMPEG:-ffmpeg}"
    CONVERT="${PLAYTHROUGH_BIN_CONVERT:-convert}"
    IDENTIFY="${PLAYTHROUGH_BIN_IDENTIFY:-identify}"
    COMPARE="${PLAYTHROUGH_BIN_COMPARE:-compare}"
    GIT="${PLAYTHROUGH_BIN_GIT:-git}"
    AWK="${PLAYTHROUGH_BIN_AWK:-awk}"
    GREP="${PLAYTHROUGH_BIN_GREP:-grep}"
}

# THE IMAGEMAGICK ENTRY POINT.  `convert`, `identify` and `compare` are
# the classic names and exist on both the version 6 and the version 7
# branches; the unified `magick` name exists only on 7, so anything
# written against it dies with command-not-found on a 6 host.  This gate
# calls the classic names and NEVER `magick`, and records which branch it
# is talking to so a reader of the report knows.
check_imagemagick() {
    local version=""
    version="$("${CONVERT}" --version 2>/dev/null |
        head -n 1 || true)"
    if [ -z "${version}" ]; then
        record_fail "ImageMagick answers through its classic entry \
points" \
            "'${CONVERT}' produced no version banner" \
            "convert, identify and compare callable (apt: imagemagick)"
        return 0
    fi
    record_pass "ImageMagick answers through its classic entry points \
(convert, identify, compare -- never the version-7-only 'magick')" \
        "${version}"
}

check_interpreter() {
    local version=""
    version="$("${PYTHON}" -B -c \
        'import sys; print(sys.version.split()[0])' 2>/dev/null || true)"
    if [ -z "${version}" ]; then
        record_fail "the verified interpreter runs" \
            "'${PYTHON}' would not report its version" \
            "the interpreter env.sh resolved, able to execute"
        return 0
    fi
    record_pass "the verified interpreter runs" \
        "${version} at $(rel "${PYTHON}")"
}

# THE LINTER, RESOLVED IN FOUR STEPS.  The repository's own contract is a
# bare `flake8` (Makefile:1648-1649), so that is preferred; an explicit
# override wins over everything, and an importable module is accepted
# because a virtual environment often installs it that way.  If none of
# the four resolves, the lint check FAILS rather than being skipped, and
# says what to do about it.
resolve_flake8() {
    local version=""
    # The override is TRIED, not trusted: a PLAYTHROUGH_FLAKE8 that will
    # not run is reported as an unresolved linter rather than producing a
    # lint "finding" that is really a shell error, which is what an
    # unvalidated override was measured to do (exit 127, "No such file").
    if [ -n "${PLAYTHROUGH_FLAKE8:-}" ] &&
            "${PLAYTHROUGH_FLAKE8}" --version >/dev/null 2>&1; then
        FLAKE8_CMD=("${PLAYTHROUGH_FLAKE8}")
    elif [ -n "${PLAYTHROUGH_FLAKE8:-}" ]; then
        FLAKE8_CMD=()
        record_info "the linter" \
            "PLAYTHROUGH_FLAKE8='${PLAYTHROUGH_FLAKE8}' would not run, \
so the lint check in group 9 reports it as unresolved"
        return 0
    elif command -v flake8 >/dev/null 2>&1; then
        FLAKE8_CMD=("$(command -v flake8)")
    elif "${PYTHON}" -B -m flake8 --version >/dev/null 2>&1; then
        FLAKE8_CMD=("${PYTHON}" -B -m flake8)
    elif command -v python3 >/dev/null 2>&1 &&
            python3 -B -m flake8 --version >/dev/null 2>&1; then
        FLAKE8_CMD=(python3 -B -m flake8)
    else
        FLAKE8_CMD=()
        record_info "the linter" \
            "not resolved -- the lint check in group 9 reports it"
        return 0
    fi
    version="$("${FLAKE8_CMD[@]}" --version 2>/dev/null |
        tr '\n' ' ' || true)"
    record_info "the linter" \
        "${FLAKE8_CMD[*]} -- ${version:-version unavailable}"
}

# THE TRUST STATE.  env.sh registers every diagnostic escape hatch and
# moves the state to "diagnostic" when any of them is set.  It matters
# here for a specific reason: a measurement taken with a binary this
# pipeline could not vouch for is a weaker measurement, and a gate that
# did not say so would be overstating its own result.
check_trust_state() {
    if playthrough_trust_refresh; then
        record_pass "the environment doing the measuring is trusted" \
            "PLAYTHROUGH_TRUST_STATE=${PLAYTHROUGH_TRUST_STATE}"
        return 0
    fi
    playthrough_trust_explain || true
    record_fail "the environment doing the measuring is trusted" \
        "PLAYTHROUGH_TRUST_STATE=${PLAYTHROUGH_TRUST_STATE:-unknown} \
(${PLAYTHROUGH_TRUST_BYPASSES:-a check could not be performed})" \
        "trusted -- no diagnostic bypass set, so every tool and path \
this gate reads through was verified"
}

# SDL_VIDEODRIVER is asserted even though this gate renders nothing,
# because `dummy` is the cause of the black-film failure mode and a
# report that did not state the driver would leave the reader unable to
# tell a real measurement from a vacuous one.
check_video_driver() {
    if [ "${SDL_VIDEODRIVER:-}" = "x11" ]; then
        record_pass "the video driver contract is x11 and not dummy" \
            "SDL_VIDEODRIVER=${SDL_VIDEODRIVER}"
        return 0
    fi
    record_fail "the video driver contract is x11 and not dummy" \
        "SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-<unset>}" \
        "x11 -- dummy renders zero pixels, which yields a black film \
while every count still tallies"
}

# The platform verdict is INFORMATION here, not a verdict on the
# artifacts.  playthrough_check_platform refuses on an end-of-life
# release, which is right for a stage that RECORDS evidence and wrong for
# one that only reads it -- auditing a committed tree on whatever host is
# to hand is legitimate.  Its diagnosis is suppressed and its finding
# reported, exactly as playthrough_env_summary does.
report_platform() {
    playthrough_check_platform >/dev/null 2>&1 || true
    record_info "the host this gate ran on" \
        "${PLAYTHROUGH_PLATFORM:-unknown} \
(supported=${PLAYTHROUGH_PLATFORM_SUPPORTED:-unchecked}, \
eol=${PLAYTHROUGH_PLATFORM_EOL:-unknown})"
    if [ "${PLAYTHROUGH_PLATFORM_SUPPORTED:-}" = "no" ]; then
        record_warn "the host this gate ran on" \
            "this release is past end of life; that does not change \
what the committed artifacts are, but a session must not be RECORDED \
here -- see playthrough/tooling/supported_env.sh"
    fi
}

# Presence is established once, before anything tries to parse or probe,
# so that a missing film is reported as a missing film rather than as
# nine confusing failures in the groups that would have read it.
check_artifacts_present() {
    local -a missing=()
    local -a present=()
    local entry="" path="" kind=""
    local -a inventory=(
        "d:${PLAYTHROUGH_FRAMES_DIR}"
        "d:${PLAYTHROUGH_TRANSITIONS_DIR}"
        "d:${PLAYTHROUGH_SAVE_DIR}"
        "f:${PLAYTHROUGH_MANIFEST}"
        "f:${PLAYTHROUGH_TIMELINE}"
        "f:${PLAYTHROUGH_CONCAT_LIST}"
        "f:${PLAYTHROUGH_MOVIE}"
        "f:${PLAYTHROUGH_MOVIE_CC}"
        "f:${PLAYTHROUGH_TRANSCRIPT_SRT}"
        "f:${PLAYTHROUGH_TRANSCRIPT_MD}"
        "f:${PLAYTHROUGH_DOSSIER}"
        "f:${PLAYTHROUGH_REQUIREMENTS}"
    )
    for entry in "${inventory[@]}"; do
        kind="${entry%%:*}"
        path="${entry#*:}"
        if [ "${kind}" = "d" ]; then
            if [ -d "${path}" ] && [ -r "${path}" ]; then
                present+=("$(rel "${path}")")
            else
                missing+=("$(rel "${path}")")
            fi
        elif [ -f "${path}" ] && [ -r "${path}" ]; then
            present+=("$(rel "${path}")")
        else
            missing+=("$(rel "${path}")")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_pass "every artifact this gate reads is present and \
readable" "${#present[@]} paths, all of them readable"
        return 0
    fi
    record_fail "every artifact this gate reads is present and \
readable" \
        "absent or unreadable: ${missing[*]}" \
        "all 12 artifact paths named in env.sh -- the render stages \
(timeline.py, make_transitions.py, render_movie.py, make_srt.py, \
embed_captions.sh) produce the generated ones"
}

group_environment() {
    group "the measuring environment"
    resolve_tools
    check_imagemagick
    check_interpreter
    resolve_flake8
    check_trust_state
    check_video_driver
    report_platform
    check_artifacts_present
}


# ---------------------------------------------------------------------
# 2  ONE FRAME PER KEYSTROKE
#
# The headline invariant of the whole subsystem: exactly one capture per
# keystroke, exactly one record row per capture.  It is asserted as an
# IDENTITY between two independently produced counts, which is what makes
# an unpaired frame impossible to overlook -- and it is the reason the
# derived transition images live in playthrough/build/transitions/ and
# never in playthrough/frames/, because mixing them in would destroy the
# very count this check rests on.
#
# The six-key schema comes from manifest.py's own FIELDS tuple and the
# canonical filename from its own frame_file(), so the committed record
# is held to exactly the contract its producer enforces on a new row
# rather than to a second description of it written here.
# ---------------------------------------------------------------------
emit_record_checker() {
    emit_checker record <<'PY'
"""Assert the capture/record pairing over the committed artifacts."""

import json
import os
import re
import sys

SEP = "\x1f"
FRAME_RE = re.compile(r"^frame_([0-9]{5})\.png$")


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def summarise(items, limit=6):
    """A bounded, readable rendering of a list of findings."""
    shown = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += ", ... (%d more)" % (len(items) - limit)
    return shown


def main(argv):
    manifest_path, frames_dir, tooling_dir, facts_path = argv[1:5]
    sys.path.insert(0, tooling_dir)
    import manifest as mf

    facts = open(facts_path, "a", encoding="utf-8")

    # --- the record ---------------------------------------------------
    with open(manifest_path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    rows = []
    unparsable = []
    key_order = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            unparsable.append("line %d is blank" % number)
            continue
        try:
            pairs = json.loads(line, object_pairs_hook=lambda kv: kv)
        except ValueError as err:
            unparsable.append("line %d: %s" % (number, err))
            continue
        if not isinstance(pairs, list):
            unparsable.append("line %d is not a JSON object" % number)
            continue
        key_order.append(tuple(k for k, _ in pairs))
        rows.append((number, dict(pairs)))

    if unparsable:
        bad("the record parses as one JSON object per line",
            summarise(unparsable),
            "%d lines, each a JSON object" % len(lines))
    else:
        ok("the record parses as one JSON object per line",
           "%d rows" % len(rows))

    # EXACTLY the six documented keys, IN ORDER, and no extras.  The
    # tuple is manifest.py's own, so this cannot drift from the producer.
    wanted = tuple(mf.FIELDS)
    wrong_keys = [rows[i][0] for i, order in enumerate(key_order)
                  if order != wanted]
    if wrong_keys:
        bad("every row carries exactly the six documented keys, in "
            "order, and no others",
            "rows with a different key set or order: %s"
            % summarise(wrong_keys),
            "%s" % ", ".join(wanted))
    else:
        ok("every row carries exactly the six documented keys, in "
           "order, and no others", ", ".join(wanted))

    empty = []
    for number, row in rows:
        for field in ("action", "commentary"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                empty.append("row %d %s" % (number, field))
    if empty:
        bad("every row records what was pressed and why",
            summarise(empty),
            "a non-empty action and a non-empty commentary on all "
            "%d rows" % len(rows))
    else:
        ok("every row records what was pressed and why",
           "%d actions and %d commentaries, none empty"
           % (len(rows), len(rows)))

    numbers = [row.get("frame") for _, row in rows]
    expected_numbers = list(range(1, len(rows) + 1))
    if numbers != expected_numbers:
        first_bad = next(
            (i + 1 for i, (a, b) in
             enumerate(zip(numbers, expected_numbers)) if a != b),
            min(len(numbers), len(expected_numbers)) + 1)
        bad("the record's frame numbers are 1-based and contiguous",
            "first divergence at position %d (%r)"
            % (first_bad, numbers[first_bad - 1:first_bad]),
            "1 .. %d with no gap and no repeat" % len(rows))
    else:
        ok("the record's frame numbers are 1-based and contiguous",
           "1 .. %d" % len(rows) if rows else "no rows")

    # Each row must name ITS OWN frame, formatted from its own index by
    # the producer's own formatter.
    mislabelled = []
    for _, row in rows:
        try:
            canonical = mf.frame_file(row.get("frame"))
        except Exception as err:                     # noqa: BLE001
            mislabelled.append("frame %r: %s" % (row.get("frame"), err))
            continue
        if row.get("file") != canonical:
            mislabelled.append("%r != %s" % (row.get("file"), canonical))
    if mislabelled:
        bad("every row names its own capture canonically",
            summarise(mislabelled),
            "playthrough/frames/frame_%05d.png formatted from the row's "
            "own frame number")
    else:
        ok("every row names its own capture canonically",
           "%d rows match %s" % (len(rows), mf.FRAME_FILE_FORMAT))

    return finish(rows, len(lines), frames_dir, facts)


def finish(rows, line_count, frames_dir, facts):
    """The disk half: what is in frames/, and does it pair with rows."""
    try:
        entries = sorted(os.listdir(frames_dir))
    except OSError as err:
        bad("the captures directory is readable", str(err),
            "a readable directory of captures")
        entries = []

    captures = [e for e in entries if FRAME_RE.match(e)]
    strays = [e for e in entries if not FRAME_RE.match(e)]

    if strays:
        bad("the captures directory holds captures and nothing else",
            summarise(strays),
            "only frame_NNNNN.png -- derived transition images belong "
            "in playthrough/build/transitions/, never here")
    else:
        ok("the captures directory holds captures and nothing else",
           "%d files, every one a frame_NNNNN.png" % len(captures))

    # THE IDENTITY.  Two counts produced by different code paths at
    # different times; they must agree exactly.
    #
    # It is asserted against the RAW LINE COUNT as well as against the
    # parsed row count, because `wc -l < manifest.jsonl` is the number
    # the requirement names and an unparsable line would otherwise be
    # excluded from the comparison it is most likely to have broken.
    if len(captures) == len(rows) == line_count:
        ok("the capture count equals the record's row count -- one "
           "frame per keystroke",
           "%d captures == %d rows == %d lines"
           % (len(captures), len(rows), line_count))
    else:
        bad("the capture count equals the record's row count -- one "
            "frame per keystroke",
            "%d captures, %d parsed rows, %d lines in the record"
            % (len(captures), len(rows), line_count),
            "all three equal; a capture without a row, or a row "
            "without a capture, means a keystroke was not recorded or "
            "a frame was not taken")

    indices = sorted(int(FRAME_RE.match(e).group(1)) for e in captures)
    if indices == list(range(1, len(indices) + 1)):
        ok("capture indices are contiguous from 00001",
           "00001 .. %05d" % len(indices) if indices else "none")
    else:
        gaps = [n for n in range(1, (max(indices) if indices else 0) + 1)
                if n not in set(indices)]
        bad("capture indices are contiguous from 00001",
            "highest %s, count %d, missing %s"
            % (max(indices) if indices else 0, len(indices),
               summarise(gaps)),
            "1 .. N with no gaps, so no capture was withdrawn after "
            "its row was written")

    present = set(captures)
    orphans = [row.get("file") for _, row in rows
               if os.path.basename(str(row.get("file"))) not in present]
    if orphans:
        bad("every capture the record names exists on disk",
            summarise(orphans),
            "all %d referenced files present" % len(rows))
    else:
        ok("every capture the record names exists on disk",
           "%d referenced files, all present" % len(rows))

    # --- HONESTY, REPORTED AS INFORMATION ----------------------------
    # A null clock or a coarse phrase is what the survivor could ACTUALLY
    # read at that moment, and recording it verbatim is the requirement
    # being met rather than broken.  Counting it as an error here would
    # create pressure to guess, which is the one thing forbidden
    # outright.  So it is reported, with the count, and never failed.
    kinds = {}
    for _, row in rows:
        value = row.get("ingame_clock")
        if value is None:
            kinds["not readable (null)"] = \
                kinds.get("not readable (null)", 0) + 1
        elif isinstance(value, str) and CLOCK_RE.match(value):
            kinds["exact"] = kinds.get("exact", 0) + 1
        else:
            kinds["verbatim coarse phrase"] = \
                kinds.get("verbatim coarse phrase", 0) + 1
    tally = ", ".join("%s: %d" % (k, kinds[k]) for k in sorted(kinds))
    info("clock readings in the record, by kind (an unreadable clock is "
         "honesty, not a fault)", tally or "no rows")

    facts.write("manifest_rows=%d\n" % len(rows))
    facts.write("manifest_lines=%d\n" % line_count)
    facts.write("capture_count=%d\n" % len(captures))
    facts.close()
    return 0


CLOCK_RE = re.compile(r"^[0-9]{2}:[0-9]{2}:[0-9]{2}$")

if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_record() {
    group "one frame per keystroke"
    run_checker record \
        "${PLAYTHROUGH_MANIFEST}" \
        "${PLAYTHROUGH_FRAMES_DIR}" \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "${SCRATCH}/facts"
}


# ---------------------------------------------------------------------
# 3  THE TIMELINE -- THE FLOOR, THE CEILING AND THE INVARIANT
#
# The claim the film makes is that its pacing is the game's own clock.
# This group is where that claim is checked, one arithmetic property at a
# time.
#
# THE FLOOR IS NOT AN OPTIMISATION OPPORTUNITY.  A menu keystroke
# consumes no game time at all, and such a frame is held at 0.25 s
# rather than merged, dropped or "optimised away"; an entry count below
# the capture count is therefore a failure even though the film would
# look identical.
#
# THE CEILING IS STRICT.  A raw delta of exactly 10.0 s is NOT a
# transition; only a delta GREATER than the ceiling is.  Both directions
# of that correspondence are asserted, because a flag without a delta and
# a delta without a flag are different bugs with the same symptom -- the
# film and the cues drifting apart by exactly one second, once.
#
# THE PRODUCERS' OWN CONSTANTS ARE CROSS-CHECKED.  timeline.py,
# make_transitions.py and render_movie.py are imported and their
# constants compared against the values this gate measures with, so a
# future edit to a producer cannot quietly move the goalposts.
# ---------------------------------------------------------------------
emit_timeline_checker() {
    emit_checker timeline <<'PY'
"""Assert the timeline's clamp, flags, cue windows and invariant."""

import hashlib
import json
import os
import re
import sys

SEP = "\x1f"
TRANS_RE = re.compile(r"^trans_([0-9]{5})_([0-9]{2})\.png$")


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def summarise(items, limit=6):
    shown = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += ", ... (%d more)" % (len(items) - limit)
    return shown


def near(a, b, eps):
    return abs(float(a) - float(b)) <= eps


def clamp(value, low, high):
    return min(max(value, low), high)


def load_entries(document):
    """The object form, with the bare-array form accepted defensively.

    timeline.py writes an object carrying the declared totals alongside
    its `frames` array.  A bare array is still understood -- it is what a
    hand-reduced or older document looks like -- so that this gate can
    report on one rather than refuse to read it.
    """
    if isinstance(document, dict):
        entries = document.get("frames")
        if isinstance(entries, list):
            return entries, document, "object with a frames array"
        return [], document, "object with no frames array"
    if isinstance(document, list):
        return document, {}, "bare array (no declared totals)"
    return [], {}, "neither an object nor an array"


def check_constants(tooling_dir, floor, ceil, trans, per_group, tol,
                    eps):
    """The producers' own constants, against the gate's expectations."""
    sys.path.insert(0, tooling_dir)
    problems = []
    observed = []
    try:
        import timeline as tl
        observed.append("timeline.py FLOOR=%s CEIL=%s TRANSITION=%s"
                        % (tl.FLOOR, tl.CEIL, tl.TRANSITION))
        for label, got, want in (("FLOOR", tl.FLOOR, floor),
                                 ("CEIL", tl.CEIL, ceil),
                                 ("TRANSITION", tl.TRANSITION, trans)):
            if not near(got, want, eps):
                problems.append("timeline.%s is %s, gate expects %s"
                                % (label, got, want))
    except Exception as err:                          # noqa: BLE001
        problems.append("timeline.py could not be imported: %s" % err)
    try:
        import make_transitions as mt
        observed.append("make_transitions.py FRAMES_PER_GROUP=%s"
                        % mt.FRAMES_PER_GROUP)
        if int(mt.FRAMES_PER_GROUP) != int(per_group):
            problems.append(
                "make_transitions.FRAMES_PER_GROUP is %s, gate expects "
                "%s" % (mt.FRAMES_PER_GROUP, per_group))
    except Exception as err:                          # noqa: BLE001
        problems.append("make_transitions.py could not be imported: %s"
                        % err)
    try:
        import render_movie as rm
        observed.append("render_movie.py DURATION_TOLERANCE=%s"
                        % rm.DURATION_TOLERANCE)
        if not near(rm.DURATION_TOLERANCE, tol, eps):
            problems.append(
                "render_movie.DURATION_TOLERANCE is %s, gate expects %s"
                % (rm.DURATION_TOLERANCE, tol))
    except Exception as err:                          # noqa: BLE001
        problems.append("render_movie.py could not be imported: %s"
                        % err)
    if problems:
        bad("the producers' own constants are the ones this gate "
            "measures against", summarise(problems),
            "FLOOR=%s CEIL=%s TRANSITION=%s FRAMES_PER_GROUP=%s "
            "DURATION_TOLERANCE=%s" % (floor, ceil, trans, per_group,
                                       tol))
    else:
        ok("the producers' own constants are the ones this gate "
           "measures against", "; ".join(observed))


def file_digest(path):
    """A streamed sha256, so a large capture is not held in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_capture_digests(document):
    """Every committed capture, against the digest taken when it was
    captured.

    The sidecar is not named here: its path comes out of the timeline
    document itself, which is the artifact that declares having verified
    it.  So this check follows the timeline's own pointer rather than
    assuming a layout.
    """
    block = document.get("captures")
    if not isinstance(block, dict) or not block.get("path"):
        info("every committed capture still hashes to the digest taken "
             "when it was captured",
             "the timeline declares no capture-digest sidecar, so the "
             "captures cannot be checked against one")
        return
    path = block["path"]
    if not os.path.exists(path):
        bad("every committed capture still hashes to the digest taken "
            "when it was captured", "%s is not there" % path,
            "the sidecar the timeline says it verified")
        return
    recorded = {}
    malformed = []
    with open(path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as err:
                malformed.append("line %d: %s" % (number, err))
                continue
            name = row.get("file")
            digest = row.get("sha256")
            if not name or not digest:
                malformed.append("line %d names %r with digest %r"
                                 % (number, name, digest))
                continue
            recorded[name] = (digest, row.get("bytes"))
    problems = list(malformed)
    checked = 0
    for name in sorted(recorded):
        digest, size = recorded[name]
        if not os.path.exists(name):
            problems.append("%s is recorded but absent" % name)
            continue
        actual = file_digest(name)
        checked += 1
        if actual != digest:
            problems.append("%s hashes to %s, recorded as %s"
                            % (name, actual[:16], str(digest)[:16]))
            continue
        if size is not None and os.path.getsize(name) != int(size):
            problems.append("%s is %d bytes, recorded as %s"
                            % (name, os.path.getsize(name), size))
    if problems:
        bad("every committed capture still hashes to the digest taken "
            "when it was captured", summarise(problems),
            "%d captures unchanged since capture -- a substituted, "
            "blanked or re-encoded frame fails here whatever its index"
            % len(recorded))
    else:
        ok("every committed capture still hashes to the digest taken "
           "when it was captured",
           "%d captures re-hashed and unchanged, byte counts included"
           % checked)


def check_provenance(document, entries):
    """The timeline was computed from the artifacts it names.

    A timeline is only a claim about a capture set, and the claim is
    falsifiable: it records the path, the sha256 and the row count of the
    record it read, of the amendment ledger it applied, and of the
    per-capture digest sidecar it verified.  Recomputing those hashes
    turns "this file was computed from this record by this code" from a
    story into a checkable fact -- a timeline regenerated from a record
    that has since changed, or a record edited after the timeline was
    written, cannot survive it.

    It is also the EXACT, WHOLE-SET complement to the sampled luminance
    reading in group 6: the digest sidecar covers every capture, so a
    frame substituted at any index breaks a hash the timeline declares,
    whether or not that index happened to be sampled.
    """
    sidecars = [key for key in ("manifest", "amendments", "captures")
                if isinstance(document.get(key), dict)]
    if not sidecars:
        info("the timeline names the artifacts it was computed from",
             "this document declares no sidecars, so its provenance "
             "cannot be checked")
        return
    problems = []
    observed = []
    for key in sidecars:
        block = document[key]
        path = block.get("path")
        declared = block.get("sha256")
        if not path or not declared:
            problems.append("%s declares path=%r sha256=%r"
                            % (key, path, declared))
            continue
        if not os.path.exists(path):
            problems.append("%s names %s, which is not there"
                            % (key, path))
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != declared:
            problems.append(
                "%s: %s hashes to %s, the timeline declares %s"
                % (key, path, actual[:16], str(declared)[:16]))
            continue
        observed.append("%s %s (%s)" % (key, actual[:12], path))
    if problems:
        bad("the timeline names the artifacts it was computed from, and "
            "they still hash to what it recorded", summarise(problems),
            "every declared sha256 reproduced from the file on disk")
    else:
        ok("the timeline names the artifacts it was computed from, and "
           "they still hash to what it recorded", "; ".join(observed))

    # THE WHOLE-SET CHECK, AND IT IS FREE.  Re-hashing all 326 committed
    # captures takes about fifty milliseconds, so every one of them is
    # compared against the digest recorded at the moment it was captured.
    # This is what makes the sampled luminance reading in group 6
    # sufficient rather than merely indicative: a frame replaced at any
    # index -- blank, duplicated, re-encoded, cropped -- fails here even
    # when that index was not among the sampled ones.
    check_capture_digests(document)

    # The digest sidecar's own arithmetic: one verified digest per
    # capture, and as many as there are entries.
    captures = document.get("captures")
    if isinstance(captures, dict):
        rows = captures.get("rows")
        verified = captures.get("verified")
        counted = (rows is not None and verified is not None and
                   int(rows) == int(verified) == len(entries))
        if counted:
            ok("every capture's digest was verified when the timeline "
               "was computed",
               "%d of %d verified, one per entry"
               % (int(verified), int(rows)))
        else:
            bad("every capture's digest was verified when the timeline "
                "was computed",
                "rows=%r verified=%r against %d entries"
                % (rows, verified, len(entries)),
                "all three equal -- an unverified capture is a frame "
                "whose provenance was never established")


def check_declared(document, entries, floor, ceil, trans, rows, eps):
    """The document's own declared numbers, against its own entries."""
    declared_floor = document.get("floor")
    declared_ceil = document.get("ceil")
    declared_trans = document.get("transition")
    problems = []
    if declared_floor is not None and not near(declared_floor, floor,
                                               eps):
        problems.append("floor=%s" % declared_floor)
    if declared_ceil is not None and not near(declared_ceil, ceil, eps):
        problems.append("ceil=%s" % declared_ceil)
    if declared_trans is not None and not near(declared_trans, trans,
                                               eps):
        problems.append("transition=%s" % declared_trans)
    if problems:
        bad("the timeline declares the contracted floor, ceiling and "
            "transition length", ", ".join(problems),
            "floor=%s ceil=%s transition=%s" % (floor, ceil, trans))
    else:
        ok("the timeline declares the contracted floor, ceiling and "
           "transition length",
           "floor=%s ceil=%s transition=%s"
           % (declared_floor, declared_ceil, declared_trans))

    declared_count = document.get("frame_count")
    if declared_count is not None and int(declared_count) != len(
            entries):
        bad("the timeline's declared entry count matches its entries",
            "frame_count=%s against %d entries"
            % (declared_count, len(entries)),
            "equal -- a declared total that outran its own array is a "
            "hand-edited document")
    else:
        ok("the timeline's declared entry count matches its entries",
           "%d entries" % len(entries))

    if rows is None:
        return
    if len(entries) == rows:
        ok("the timeline has one entry per recorded keystroke -- no "
           "zero-delta frame was dropped or merged",
           "%d entries == %d record rows" % (len(entries), rows))
    else:
        bad("the timeline has one entry per recorded keystroke -- no "
            "zero-delta frame was dropped or merged",
            "%d entries against %d record rows" % (len(entries), rows),
            "equal counts; a frame that consumed no game time is held "
            "at the floor, never optimised away")


def check_clamp(entries, floor, ceil, eps):
    """The floor, the ceiling, and that each duration IS the clamp."""
    out_of_range = []
    not_clamped = []
    negative = []
    for entry in entries:
        number = entry.get("frame")
        duration = entry.get("duration")
        raw = entry.get("raw_delta")
        if not isinstance(duration, (int, float)):
            out_of_range.append("frame %s duration=%r"
                                % (number, duration))
            continue
        if duration < floor - eps or duration > ceil + eps:
            out_of_range.append("frame %s duration=%s"
                                % (number, duration))
        if isinstance(raw, (int, float)):
            if raw < -eps:
                negative.append("frame %s raw_delta=%s" % (number, raw))
            wanted = round(clamp(float(raw), floor, ceil), 3)
            if not near(duration, wanted, eps):
                not_clamped.append(
                    "frame %s duration=%s but clamp(%s)=%s"
                    % (number, duration, raw, wanted))
        else:
            not_clamped.append("frame %s raw_delta=%r" % (number, raw))

    if out_of_range:
        bad("every on-screen duration is inside the floor and the "
            "ceiling", summarise(out_of_range),
            "%s <= duration <= %s on all %d entries"
            % (floor, ceil, len(entries)))
    else:
        ok("every on-screen duration is inside the floor and the "
           "ceiling",
           "%d entries, all within %s .. %s s"
           % (len(entries), floor, ceil))

    if not_clamped:
        bad("every duration is exactly the clamped clock delta",
            summarise(not_clamped),
            "duration == min(max(raw_delta, %s), %s) rounded to 3 dp"
            % (floor, ceil))
    else:
        ok("every duration is exactly the clamped clock delta",
           "%d entries; the sidebar clock is the only source of pacing"
           % len(entries))

    if negative:
        bad("no clock delta runs backwards", summarise(negative),
            "raw_delta >= 0 everywhere -- the midnight rollover guard "
            "turns 23:59:58 -> 00:00:04 into +6 s, not -86394 s")
    else:
        ok("no clock delta runs backwards",
           "%d deltas, none negative" % len(entries))


def check_flags(entries, ceil, document):
    """transition_after <=> raw_delta > ceiling, in both directions."""
    flagged_without = []
    over_without_flag = []
    at_ceiling_flagged = []
    flagged = []
    for entry in entries:
        number = entry.get("frame")
        raw = entry.get("raw_delta")
        flag = bool(entry.get("transition_after"))
        if flag:
            flagged.append(number)
        if not isinstance(raw, (int, float)):
            continue
        if flag and not float(raw) > ceil:
            flagged_without.append("frame %s raw_delta=%s"
                                   % (number, raw))
            if float(raw) == ceil:
                at_ceiling_flagged.append("frame %s" % number)
        if float(raw) > ceil and not flag:
            over_without_flag.append("frame %s raw_delta=%s"
                                     % (number, raw))

    problems = flagged_without + over_without_flag
    if problems:
        detail = summarise(problems)
        if at_ceiling_flagged:
            detail += " (exactly at the ceiling: %s)" % summarise(
                at_ceiling_flagged)
        bad("a transition is flagged exactly where the clock delta "
            "exceeded the ceiling", detail,
            "transition_after is true if and only if raw_delta > %s "
            "STRICTLY -- a delta of exactly %s is not a transition"
            % (ceil, ceil))
    else:
        ok("a transition is flagged exactly where the clock delta "
           "exceeded the ceiling",
           "%d flagged of %d entries%s"
           % (len(flagged), len(entries),
              ": frame(s) " + summarise(flagged) if flagged else ""))

    declared = document.get("transition_count")
    if declared is not None and int(declared) != len(flagged):
        bad("the timeline's declared transition count matches its flags",
            "transition_count=%s against %d flags"
            % (declared, len(flagged)),
            "equal counts")
    elif declared is not None:
        ok("the timeline's declared transition count matches its flags",
           "transition_count=%s" % declared)
    return flagged


def check_cues(entries, trans, eps):
    """Every cue window, walked as the film will actually play.

    A cue occupies [cue_start, cue_end) with cue_end - cue_start equal to
    the frame's on-screen duration; the next cue begins where this one
    ended, PLUS the inserted transition second when one was flagged.
    That last clause is the whole of silent failure mode 3: a generator
    that walks durations without charging the insertion produces cues
    that are right at the start and increasingly wrong by the end.
    """
    window_problems = []
    walk_problems = []
    cursor = 0.0
    for entry in entries:
        number = entry.get("frame")
        duration = entry.get("duration")
        start = entry.get("cue_start")
        end = entry.get("cue_end")
        if not all(isinstance(v, (int, float))
                   for v in (duration, start, end)):
            window_problems.append("frame %s has a non-numeric window"
                                   % number)
            continue
        if not near(end - start, duration, eps):
            window_problems.append(
                "frame %s window %s..%s spans %s but duration is %s"
                % (number, start, end, round(end - start, 3), duration))
        if not near(start, cursor, eps):
            walk_problems.append(
                "frame %s starts at %s, the walk reached %s"
                % (number, start, round(cursor, 3)))
        cursor = start + duration
        if entry.get("transition_after"):
            cursor += trans
    if window_problems:
        bad("every cue window is exactly as long as its frame is on "
            "screen", summarise(window_problems),
            "cue_end - cue_start == duration on all %d entries"
            % len(entries))
    else:
        ok("every cue window is exactly as long as its frame is on "
           "screen", "%d windows" % len(entries))
    if walk_problems:
        bad("the cue cursor is charged for every inserted transition "
            "second", summarise(walk_problems),
            "each cue begins where the previous ended, plus %s s "
            "wherever a transition was inserted" % trans)
    else:
        ok("the cue cursor is charged for every inserted transition "
           "second",
           "walked %d cues to %.3f s with no drift"
           % (len(entries), cursor))
    return round(cursor, 3)


def check_invariant(entries, document, flagged, trans, walked, eps):
    """sum(durations) + sum(transitions) == total == final cue end."""
    sum_durations = round(sum(float(e.get("duration") or 0.0)
                              for e in entries), 3)
    sum_transitions = round(len(flagged) * float(trans), 3)
    computed = round(sum_durations + sum_transitions, 3)

    declared_duration = document.get("total_duration")
    declared_transition = document.get("total_transition")
    declared_total = document.get("total")
    declared_cue_end = document.get("final_cue_end")
    if entries:
        last_cue_end = entries[-1].get("cue_end")
    else:
        last_cue_end = 0.0

    parts = []
    if declared_duration is not None and not near(declared_duration,
                                                  sum_durations, eps):
        parts.append("total_duration=%s but the durations sum to %s"
                     % (declared_duration, sum_durations))
    if declared_transition is not None and not near(
            declared_transition, sum_transitions, eps):
        parts.append("total_transition=%s but %d flags x %s = %s"
                     % (declared_transition, len(flagged), trans,
                        sum_transitions))
    if declared_total is not None and not near(declared_total, computed,
                                               eps):
        parts.append("total=%s but %s + %s = %s"
                     % (declared_total, sum_durations, sum_transitions,
                        computed))
    if declared_cue_end is not None and not near(declared_cue_end,
                                                 computed, eps):
        parts.append("final_cue_end=%s but the computed total is %s"
                     % (declared_cue_end, computed))
    if not near(last_cue_end, computed, eps):
        parts.append("the last entry ends at %s, not %s"
                     % (last_cue_end, computed))
    if not near(walked, computed, eps):
        parts.append("the independent cue walk reached %s, not %s"
                     % (walked, computed))

    if parts:
        bad("the timeline invariant holds: sum(durations) + "
            "sum(transitions) == total == final cue end",
            summarise(parts, 8),
            "%s + %s == %s, and the last cue ends there"
            % (sum_durations, sum_transitions, computed))
    else:
        ok("the timeline invariant holds: sum(durations) + "
           "sum(transitions) == total == final cue end",
           "%.3f + %.3f = %.3f s, and the final cue ends at %.3f s"
           % (sum_durations, sum_transitions, computed,
              float(last_cue_end)))
    return computed


def check_transitions(transitions_dir, flagged, per_group):
    """The materialised transition images, against the flags.

    Group count must equal flag count and each group must hold exactly
    `per_group` images with contiguous ordinals.  Anything else
    desynchronises the film from the cues by exactly the error, once per
    transition -- and it is not detectable by watching either artifact
    alone.
    """
    try:
        entries = sorted(os.listdir(transitions_dir))
    except OSError as err:
        bad("the transition images directory is readable", str(err),
            "a readable directory beside the captures, never inside "
            "them")
        return 0
    images = [e for e in entries if TRANS_RE.match(e)]
    strays = [e for e in entries if not TRANS_RE.match(e)]
    groups = {}
    for name in images:
        match = TRANS_RE.match(name)
        groups.setdefault(int(match.group(1)), []).append(
            int(match.group(2)))

    if strays:
        bad("the transition directory holds transition images and "
            "nothing else", summarise(strays),
            "only trans_NNNNN_MM.png")
    else:
        ok("the transition directory holds transition images and "
           "nothing else", "%d images in %d group(s)"
           % (len(images), len(groups)))

    flagged_set = sorted(int(f) for f in flagged if f is not None)
    if sorted(groups) == flagged_set:
        ok("one materialised transition group per flagged frame",
           "group(s) for frame(s) %s" % (summarise(flagged_set) or
                                         "none"))
    else:
        bad("one materialised transition group per flagged frame",
            "groups for %s against flags for %s"
            % (summarise(sorted(groups)) or "none",
               summarise(flagged_set) or "none"),
            "identical sets -- a group without a flag is orphaned "
            "footage, a flag without a group is a missing second")

    wrong = []
    for number in sorted(groups):
        ordinals = sorted(groups[number])
        if ordinals != list(range(per_group)):
            wrong.append("frame %s has %d image(s) %s"
                         % (number, len(ordinals), summarise(ordinals)))
    if wrong:
        bad("each transition group holds its full complement of images",
            summarise(wrong),
            "exactly %d images per group, ordinals 00 .. %02d"
            % (per_group, per_group - 1))
    else:
        ok("each transition group holds its full complement of images",
           "%d group(s) x %d images" % (len(groups), per_group))
    return len(groups)


def main(argv):
    (timeline_path, transitions_dir, tooling_dir, facts_path,
     floor, ceil, trans, per_group, tolerance, epsilon) = argv[1:11]
    floor = float(floor)
    ceil = float(ceil)
    trans = float(trans)
    per_group = int(per_group)
    tolerance = float(tolerance)
    epsilon = float(epsilon)

    rows = None
    if os.path.exists(facts_path):
        with open(facts_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("manifest_rows="):
                    rows = int(line.split("=", 1)[1].strip())

    check_constants(tooling_dir, floor, ceil, trans, per_group,
                    tolerance, epsilon)

    try:
        with open(timeline_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as err:
        bad("the timeline parses as JSON", str(err),
            "a JSON object carrying a frames array")
        return 0

    entries, document, shape = load_entries(document)
    if not entries:
        bad("the timeline carries per-frame entries", shape,
            "an object with a non-empty frames array, or a bare array")
        return 0
    ok("the timeline parses and carries per-frame entries",
       "%s, %d entries" % (shape, len(entries)))

    check_provenance(document, entries)
    check_declared(document, entries, floor, ceil, trans, rows, epsilon)
    check_clamp(entries, floor, ceil, epsilon)
    flagged = check_flags(entries, ceil, document)
    walked = check_cues(entries, trans, epsilon)
    total = check_invariant(entries, document, flagged, trans, walked,
                            epsilon)
    groups = check_transitions(transitions_dir, flagged, per_group)

    reconciled = sum(1 for e in entries if e.get("reconciled"))
    info("clock readings reconciled against the previous frame rather "
         "than guessed", "%d of %d entries" % (reconciled, len(entries)))
    flagged_detail = ", ".join(
        "frame %s raw_delta=%ss held at %ss"
        % (e.get("frame"), e.get("raw_delta"), e.get("duration"))
        for e in entries if e.get("transition_after"))
    info("where the ceiling engaged",
         flagged_detail or "nowhere -- no delta exceeded the ceiling")

    with open(facts_path, "a", encoding="utf-8") as handle:
        handle.write("timeline_entries=%d\n" % len(entries))
        handle.write("timeline_total=%.3f\n" % total)
        handle.write("transition_flags=%d\n" % len(flagged))
        handle.write("transition_groups=%d\n" % groups)
        handle.write("transition_images=%d\n" % (groups * per_group))
        handle.write("expected_images=%d\n"
                     % (len(entries) + groups * per_group))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_timeline() {
    group "the timeline: the floor, the ceiling and the invariant"
    run_checker timeline \
        "${PLAYTHROUGH_TIMELINE}" \
        "${PLAYTHROUGH_TRANSITIONS_DIR}" \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "${SCRATCH}/facts" \
        "${DURATION_FLOOR}" \
        "${DURATION_CEIL}" \
        "${TRANSITION_SECONDS}" \
        "${TRANSITION_FRAMES_PER_GROUP}" \
        "${CONTAINER_TOLERANCE}" \
        "${ARITHMETIC_EPSILON}"
}


# ---------------------------------------------------------------------
# 4  THE CONTAINER
#
# 1920x1080 and not 1920x1072.  The game's window is 1072 pixels tall --
# 67 rows of a 16-pixel font (src/sdltiles.cpp:595-596), windowed
# borderless by default (src/options.cpp:2715-2724) -- but what is
# photographed is the X ROOT, which is exactly 1920x1080.  A film at 1072
# would mean the window was captured instead, and the four-pixel
# letterbox is the visible sign that the root was.
#
# The duration is compared against the timeline's own total.  A SHORTFALL
# is the signature of a concat list whose final `file` entry was not
# repeated after its `duration` line, which was measured once as a
# 10.52 s container against an 11.75 s subtitle stream: the film simply
# stops before its captions do.
# ---------------------------------------------------------------------
check_container_streams() {
    local file="$1"
    local label="$2"
    local codec="" width="" height="" pix=""
    codec="$(probe_value "${file}" v:0 stream=codec_name)"
    width="$(probe_value "${file}" v:0 stream=width)"
    height="$(probe_value "${file}" v:0 stream=height)"
    pix="$(probe_value "${file}" v:0 stream=pix_fmt)"

    if [ "${codec}" = "${VIDEO_CODEC_EXPECTED}" ]; then
        record_pass "${label} carries a ${VIDEO_CODEC_EXPECTED} video \
stream" "codec_name=${codec}"
    else
        record_fail "${label} carries a ${VIDEO_CODEC_EXPECTED} video \
stream" "codec_name=${codec:-<no video stream>}" \
            "${VIDEO_CODEC_EXPECTED}"
    fi

    if [ "${width}" = "${PLAYTHROUGH_SCREEN_WIDTH}" ] &&
            [ "${height}" = "${PLAYTHROUGH_SCREEN_HEIGHT}" ]; then
        record_pass "${label} is at the X root's own resolution" \
            "${width}x${height}"
    else
        record_fail "${label} is at the X root's own resolution" \
            "${width:-?}x${height:-?}" \
            "${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT} \
-- 1920x1072 would mean the game window was photographed instead of \
the root"
    fi

    if [ "${pix}" = "yuv420p" ]; then
        record_pass "${label} uses the broadly playable pixel format" \
            "pix_fmt=${pix}"
    else
        record_fail "${label} uses the broadly playable pixel format" \
            "pix_fmt=${pix:-<unknown>}" \
            "yuv420p -- anything else is unplayable in a large share \
of players"
    fi
}

check_container_duration() {
    local total="" duration="" delta=""
    total="$(fact timeline_total)"
    duration="$(probe_format "${PLAYTHROUGH_MOVIE}" duration)"
    if ! is_number "${total}"; then
        record_fail "the film is as long as the timeline says" \
            "the timeline total could not be established" \
            "a numeric total from playthrough/timeline.json"
        return 0
    fi
    if ! is_number "${duration}"; then
        record_fail "the film is as long as the timeline says" \
            "ffprobe reported duration=${duration:-<nothing>}" \
            "a numeric container duration"
        return 0
    fi
    delta="$("${AWK}" -v a="${duration}" -v b="${total}" \
        'BEGIN { d = a - b; printf "%.3f", d }')"
    if floats_close "${duration}" "${total}" \
            "${CONTAINER_TOLERANCE}"; then
        record_pass "the film is as long as the timeline says" \
            "container ${duration}s against timeline ${total}s \
(delta ${delta}s, tolerance ${CONTAINER_TOLERANCE}s)"
        return 0
    fi
    record_fail "the film is as long as the timeline says" \
        "container ${duration}s against timeline ${total}s (delta \
${delta}s)" \
        "within ${CONTAINER_TOLERANCE}s -- a shortfall means the concat \
list did not repeat its final 'file' entry, so the last duration never \
took effect"
}

# "No audio stream" is only worth asserting about a container ffprobe can
# actually read.  A file it cannot parse reports no audio too, and
# accepting that as a pass would be the kind of vacuous verdict this gate
# exists to prevent -- so an unreadable container fails HERE as well,
# rather than being silently credited with an absence.
check_no_audio() {
    local file="" label="" streams="" video=""
    for file in "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"; do
        label="$(rel "${file}")"
        video="$(probe_value "${file}" v:0 stream=codec_name)"
        if [ -z "${video}" ]; then
            record_fail "${label} carries no audio stream" \
                "the container has no readable video stream either, so \
the absence of audio proves nothing about it" \
                "a readable container with a video stream and no audio \
stream"
            continue
        fi
        streams="$(probe_field "${file}" a 'stream=index' |
            "${GREP}" -c '^index=' || true)"
        if [ "${streams:-0}" = "0" ]; then
            record_pass "${label} carries no audio stream" \
                "no audio: the session was muted \
(SOUND_ENABLED=false, SDL_AUDIODRIVER=dummy) and nothing was narrated"
        else
            record_fail "${label} carries no audio stream" \
                "${streams} audio stream(s)" \
                "none -- this film has no music, no effects and no \
narration"
        fi
    done
}

# THE FRAME COUNT, UNDER VARIABLE FRAME RATE.  The concat demuxer is fed
# one entry per still image -- every capture plus every materialised
# transition image -- and its final `file` entry is deliberately repeated
# so the last duration takes effect, which yields that one extra encoded
# frame.  So the count is the image inventory, or the inventory plus one,
# and nothing else.
check_frame_count() {
    local expected="" observed=""
    expected="$(fact expected_images)"
    observed="$(probe_value "${PLAYTHROUGH_MOVIE}" v:0 \
        stream=nb_frames)"
    if ! is_number "${observed}"; then
        observed="$("${FFPROBE}" -v error -select_streams v:0 \
            -count_packets -show_entries stream=nb_read_packets \
            -of default=noprint_wrappers=1:nokey=1 \
            -i "${PLAYTHROUGH_MOVIE}" 2>/dev/null | head -n 1 || true)"
    fi
    if ! is_number "${expected}" || ! is_number "${observed}"; then
        record_fail "the film holds one encoded frame per still it was \
built from" \
            "expected=${expected:-?} observed=${observed:-?}" \
            "both counts readable"
        return 0
    fi
    if [ "${observed}" -eq "${expected}" ] ||
            [ "${observed}" -eq "$((expected + 1))" ]; then
        record_pass "the film holds one encoded frame per still it was \
built from" \
            "${observed} encoded frames from $(fact timeline_entries) \
captures + $(fact transition_images) transition images"
        return 0
    fi
    record_fail "the film holds one encoded frame per still it was \
built from" \
        "${observed} encoded frames against ${expected} stills" \
        "${expected} or ${expected} + 1 (the repeated final concat \
entry); a lower count means captures were dropped from the render"
}

group_container() {
    group "the container"
    check_container_streams "${PLAYTHROUGH_MOVIE}" \
        "$(rel "${PLAYTHROUGH_MOVIE}")"
    check_container_duration
    check_frame_count
    check_no_audio
    record_info "the films on disk" \
        "$(rel "${PLAYTHROUGH_MOVIE}") \
$(wc -c <"${PLAYTHROUGH_MOVIE}" 2>/dev/null || echo '?') bytes, \
$(rel "${PLAYTHROUGH_MOVIE_CC}") \
$(wc -c <"${PLAYTHROUGH_MOVIE_CC}" 2>/dev/null || echo '?') bytes"
}


# ---------------------------------------------------------------------
# 5  THE CAPTION TRACK AND THE TRANSCRIPTS
#
# The captions must be a SELECTABLE track and not pixels.  mov_text is
# the only subtitle codec broadly supported inside MP4, and the proof
# that it was muxed rather than drawn is pixel-level: the same instant
# extracted from the captioned film and from the plain one must differ in
# ZERO pixels.  If the text had been burned in, that comparison would
# count every glyph.
# ---------------------------------------------------------------------
check_subtitle_stream() {
    local readout="" codec="" language="" streams=""
    readout="$(probe_field "${PLAYTHROUGH_MOVIE_CC}" s \
        'stream=index,codec_name:stream_tags=language')"
    streams="$(printf '%s\n' "${readout}" |
        "${GREP}" -c '^index=' || true)"
    codec="$(printf '%s\n' "${readout}" |
        sed -n 's/^codec_name=//p' | head -n 1 || true)"
    language="$(printf '%s\n' "${readout}" |
        sed -n 's/^TAG:language=//p' | head -n 1 || true)"

    if [ "${streams}" = "1" ]; then
        record_pass "the captioned film carries exactly one subtitle \
stream" "${streams} subtitle stream"
    else
        record_fail "the captioned film carries exactly one subtitle \
stream" "${streams:-0} subtitle stream(s)" \
            "exactly 1 -- one English track for one session"
    fi

    if [ "${codec}" = "${SUBTITLE_CODEC_EXPECTED}" ]; then
        record_pass "the captions are a soft, player-selectable track" \
            "codec_name=${codec}"
    else
        record_fail "the captions are a soft, player-selectable track" \
            "codec_name=${codec:-<no subtitle stream>}" \
            "${SUBTITLE_CODEC_EXPECTED} -- the only subtitle codec \
broadly supported inside MP4"
    fi

    if [ "${language}" = "${SUBTITLE_LANGUAGE_EXPECTED}" ]; then
        record_pass "the caption track declares its language" \
            "TAG:language=${language}"
    else
        record_fail "the caption track declares its language" \
            "TAG:language=${language:-<unset>}" \
            "${SUBTITLE_LANGUAGE_EXPECTED} (an ISO-639 three-letter \
code), so a player can offer it by name"
    fi
}

# THE MUX MUST NOT HAVE RE-ENCODED THE PICTURE.  `-c copy` copies the
# video packets; if the captioned film's video stream differs in codec or
# geometry, something re-encoded it and the picture is no longer the one
# that was verified.
check_captioned_video_survived() {
    check_container_streams "${PLAYTHROUGH_MOVIE_CC}" \
        "$(rel "${PLAYTHROUGH_MOVIE_CC}")"
}

# THE BURNED-IN TEST.  Extract the same timestamp from both films and
# require zero differing pixels.  `compare` exits non-zero when the
# images differ, so its status is captured deliberately rather than
# allowed to abort the run, and the metric it prints on stderr is the
# evidence either way.
check_captions_not_burned_in() {
    local plain="${SCRATCH}/plain.png"
    local captioned="${SCRATCH}/captioned.png"
    local metric="" status=0
    if ! "${FFMPEG}" -nostdin -y -v error -ss "${EXTRACT_OFFSET}" \
            -i "${PLAYTHROUGH_MOVIE}" -frames:v 1 "${plain}" \
            >/dev/null 2>&1; then
        record_fail "the captions are not burned into the picture" \
            "could not extract a frame from \
$(rel "${PLAYTHROUGH_MOVIE}") at ${EXTRACT_OFFSET}s" \
            "one decodable frame from each film"
        return 0
    fi
    if ! "${FFMPEG}" -nostdin -y -v error -ss "${EXTRACT_OFFSET}" \
            -i "${PLAYTHROUGH_MOVIE_CC}" -frames:v 1 "${captioned}" \
            >/dev/null 2>&1; then
        record_fail "the captions are not burned into the picture" \
            "could not extract a frame from \
$(rel "${PLAYTHROUGH_MOVIE_CC}") at ${EXTRACT_OFFSET}s" \
            "one decodable frame from each film"
        return 0
    fi
    set +e
    metric="$("${COMPARE}" -metric AE "${captioned}" "${plain}" \
        null: 2>&1)"
    status=$?
    set -e
    metric="${metric%% *}"
    if [ "${status}" -eq 0 ] && [ "${metric}" = "0" ]; then
        record_pass "the captions are not burned into the picture" \
            "0 differing pixels at ${EXTRACT_OFFSET}s between \
$(rel "${PLAYTHROUGH_MOVIE_CC}") and $(rel "${PLAYTHROUGH_MOVIE}")"
        return 0
    fi
    record_fail "the captions are not burned into the picture" \
        "compare reported ${metric:-<no metric>} differing pixel(s) \
(exit ${status})" \
        "0 -- identical pixels, because the text is a muxed track and \
not paint on the frame"
}

emit_caption_checker() {
    emit_checker caption <<'PY'
"""Assert the cue file, the readable transcript and their agreement."""

import json
import os
import re
import sys

SEP = "\x1f"
ARROW = " --> "
TIMECODE_RE = re.compile(
    r"^([0-9]{2}):([0-9]{2}):([0-9]{2}),([0-9]{3})"
    r" --> ([0-9]{2}):([0-9]{2}):([0-9]{2}),([0-9]{3})$")
STAMP_RE = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}[,.][0-9]{3}")
ENTRY_RE = re.compile(
    r"(?m)^\*\*([0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3})\*\*")

# The literal vocabulary the requirement names, applied as an ADVISORY.
# It is deliberately NOT the failing gate: measured against the committed
# record it matches "a man of many options" and "past the frame" -- a
# door frame, which is the survivor's own word for it -- so using it to
# fail would manufacture findings out of ordinary English.  The failing
# gate is manifest.py's curated vocabulary, which distinguishes those
# cases by pattern; this list is still run, and every hit is reported, so
# nothing is hidden by that choice.
ADVISORY_PATTERN = re.compile(
    r"frame|screenshot|capture|ocr|tesseract|imagemagick|ffmpeg"
    r"|moviepy|manifest|timeline|duration|keystroke|xdotool|pipeline"
    r"|tileset|sidebar|option|commit|git |debug|requirement"
    r"|R1[0-3]|R[1-9]\b", re.IGNORECASE)


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def summarise(items, limit=6):
    shown = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += ", ... (%d more)" % (len(items) - limit)
    return shown


def near(a, b, eps):
    return abs(float(a) - float(b)) <= eps


def seconds(hours, minutes, secs, millis):
    return (int(hours) * 3600 + int(minutes) * 60 +
            int(secs) + int(millis) / 1000.0)


def parse_cues(text):
    """Blocks of the cue file, as (number, start, end, lines)."""
    cues = []
    problems = []
    blocks = re.split(r"\n[ \t]*\n", text.strip("\n"))
    for position, block in enumerate(blocks, 1):
        lines = block.split("\n")
        if len(lines) < 3:
            problems.append("block %d has %d line(s), not a sequence "
                            "number, a timecode and text"
                            % (position, len(lines)))
            continue
        number, timecode = lines[0].strip(), lines[1]
        match = TIMECODE_RE.match(timecode)
        if not match:
            problems.append("block %d timecode %r" % (position,
                                                      timecode))
            continue
        if not number.isdigit():
            problems.append("block %d sequence %r" % (position, number))
            continue
        start = seconds(*match.groups()[0:4])
        end = seconds(*match.groups()[4:8])
        cues.append((int(number), start, end, lines[2:]))
    return cues, problems


def check_cue_file(path, entries, eps):
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        bad("the cue file carries no byte-order mark",
            "the file begins with a UTF-8 BOM",
            "no BOM -- a leading BOM makes the first sequence number "
            "unparsable to strict players")
    else:
        ok("the cue file carries no byte-order mark", "%d bytes"
           % len(raw))
    text = raw.decode("utf-8")

    cues, problems = parse_cues(text)
    arrows = text.count(ARROW)
    if problems:
        bad("every cue is a well formed SubRip block",
            summarise(problems),
            "a sequence number, an HH:MM:SS,mmm --> HH:MM:SS,mmm "
            "timecode with COMMA decimal separators, and text")
    else:
        ok("every cue is a well formed SubRip block",
           "%d cues, %d arrows" % (len(cues), arrows))

    numbers = [c[0] for c in cues]
    if numbers == list(range(1, len(cues) + 1)):
        ok("cue sequence numbers are contiguous from 1",
           "1 .. %d" % len(cues) if cues else "no cues")
    else:
        bad("cue sequence numbers are contiguous from 1",
            "first divergence near %s" % summarise(
                [n for i, n in enumerate(numbers) if n != i + 1]),
            "1 .. %d" % len(cues))

    empty = [c[0] for c in cues
             if not any(line.strip() for line in c[3])]
    if empty:
        bad("every cue carries text", summarise(empty),
            "non-empty text in all %d cues" % len(cues))
    else:
        ok("every cue carries text", "%d cues" % len(cues))

    ordering = []
    previous_end = None
    for number, start, end, _ in cues:
        if not end > start:
            ordering.append("cue %d ends at %.3f, at or before its "
                            "start %.3f" % (number, end, start))
        if previous_end is not None and start < previous_end - eps:
            ordering.append("cue %d starts at %.3f, before cue %d "
                            "ended at %.3f"
                            % (number, start, number - 1, previous_end))
        previous_end = end
    if ordering:
        bad("cue windows advance and never overlap", summarise(ordering),
            "end > start for every cue, and each start at or after the "
            "previous end")
    else:
        ok("cue windows advance and never overlap", "%d cues" % len(cues))

    if entries is not None:
        if len(cues) == len(entries):
            ok("the cue count equals the capture count -- one caption "
               "per keystroke",
               "%d cues == %d captures" % (len(cues), len(entries)))
        else:
            bad("the cue count equals the capture count -- one caption "
                "per keystroke",
                "%d cues against %d captures"
                % (len(cues), len(entries)),
                "equal counts")
        drift = []
        for (number, start, end, _), entry in zip(cues, entries):
            if not near(start, entry["cue_start"], eps) or \
                    not near(end, entry["cue_end"], eps):
                drift.append(
                    "cue %d is %.3f..%.3f, the timeline says %.3f..%.3f"
                    % (number, start, end, entry["cue_start"],
                       entry["cue_end"]))
        if drift:
            bad("every cue window is the timeline's own window",
                summarise(drift),
                "identical to the single computed timeline both the "
                "film and the captions were built from")
        else:
            ok("every cue window is the timeline's own window",
               "%d windows agree to within %s s" % (len(cues), eps))
    return cues


def check_final_cue(cues, total, eps):
    if not cues:
        bad("the last cue ends exactly where the timeline ends",
            "there are no cues", "a final cue ending at %s s" % total)
        return
    end = cues[-1][2]
    if near(end, total, eps):
        ok("the last cue ends exactly where the timeline ends",
           "%.3f s" % end)
    else:
        bad("the last cue ends exactly where the timeline ends",
            "the last cue ends at %.3f s, the timeline total is %s s"
            % (end, total),
            "equal -- captions that outrun or fall short of the film "
            "are drifting, and the drift grows through the session")


def check_markdown(path, cues, entries, tooling_dir, eps):
    """The readable record: one stamped entry per capture, in voice."""
    with open(path, "rb") as raw_handle:
        raw = raw_handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        bad("the readable record carries no byte-order mark",
            "the file begins with a UTF-8 BOM", "no BOM")
    text = raw.decode("utf-8")

    stamps = ENTRY_RE.findall(text)
    all_stamps = STAMP_RE.findall(text)
    if entries is not None:
        if len(stamps) == len(entries):
            ok("the readable record has one stamped entry per capture",
               "%d entries == %d captures" % (len(stamps), len(entries)))
        else:
            bad("the readable record has one stamped entry per capture",
                "%d entries against %d captures"
                % (len(stamps), len(entries)),
                "equal counts")
    if len(all_stamps) == len(stamps):
        ok("every timestamp in the readable record opens an entry",
           "%d stamps, %d entries" % (len(all_stamps), len(stamps)))
    else:
        bad("every timestamp in the readable record opens an entry",
            "%d timestamps but %d entries" % (len(all_stamps),
                                              len(stamps)),
            "one stamp per entry and none anywhere else, so the file "
            "cannot be read as claiming a time it does not index")

    if cues:
        drift = []
        for position, (stamp, cue) in enumerate(zip(stamps, cues), 1):
            match = STAMP_RE.match(stamp)
            if not match:
                drift.append("entry %d stamp %r" % (position, stamp))
                continue
            parts = re.split(r"[:,]", stamp)
            value = seconds(parts[0], parts[1], parts[2], parts[3])
            if not near(value, cue[1], eps):
                drift.append("entry %d is stamped %s, cue %d begins at "
                             "%.3f" % (position, stamp, cue[0], cue[1]))
        if drift:
            bad("the readable record's timestamps are the cue starts",
                summarise(drift),
                "identical -- both are generated from the one computed "
                "timeline in a single pass")
        else:
            ok("the readable record's timestamps are the cue starts",
               "%d stamps agree with %d cue starts"
               % (len(stamps), len(cues)))

    # THE IN-CHARACTER GATE.  Engineering and "gamey" language belongs in
    # playthrough/TECHNICAL_NOTES.md; the record the survivor keeps is
    # his own voice.  The failing gate is manifest.py's curated
    # vocabulary, which is written to tell a door frame from a numbered
    # one; the literal advisory list is reported beside it.
    sys.path.insert(0, tooling_dir)
    try:
        import manifest as mf
    except Exception as err:                          # noqa: BLE001
        bad("the readable record is free of meta and engineering "
            "language", "manifest.py could not be imported: %s" % err,
            "the curated vocabulary applied to every entry")
        return
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        found = mf.find_meta_vocabulary(line)
        if found:
            hits.append("line %d: %s" % (number, ", ".join(found)))
    if hits:
        bad("the readable record is free of meta and engineering "
            "language", summarise(hits),
            "no hit from manifest.META_VOCABULARY -- move the "
            "observation to playthrough/TECHNICAL_NOTES.md and rewrite "
            "the sentence in the survivor's own words")
    else:
        ok("the readable record is free of meta and engineering "
           "language",
           "%d lines checked against %d curated concepts"
           % (len(text.splitlines()), len(mf.META_VOCABULARY)))

    advisory = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in ADVISORY_PATTERN.finditer(line):
            advisory.append("line %d %r" % (number, match.group(0)))
    # Reported without a verdict attached, deliberately.  Saying these
    # hits ARE ordinary English would be a claim about text this run has
    # not read; the curated check above is the verdict, and this line
    # exists so that the literal list's hits are visible rather than
    # hidden by that choice.
    info("the literal meta word list, applied as an advisory (the "
         "curated check above is the verdict)",
         ("%d hit(s) to read in context: %s"
          % (len(advisory), summarise(advisory)))
         if advisory else "no hits")


def main(argv):
    (srt_path, markdown_path, timeline_path, tooling_dir,
     epsilon) = argv[1:6]
    eps = float(epsilon)

    entries = None
    total = None
    try:
        with open(timeline_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        if isinstance(document, dict):
            entries = document.get("frames")
            total = document.get("total")
        elif isinstance(document, list):
            entries = document
        if entries and total is None:
            total = entries[-1].get("cue_end")
    except (OSError, ValueError) as err:
        info("the timeline was not available to compare against",
             str(err))

    cues = []
    if os.path.exists(srt_path):
        cues = check_cue_file(srt_path, entries, eps)
        if total is not None:
            check_final_cue(cues, total, eps)
    else:
        bad("the cue file exists", srt_path, "playthrough/transcript.srt")

    if os.path.exists(markdown_path):
        check_markdown(markdown_path, cues, entries, tooling_dir, eps)
    else:
        bad("the readable record exists", markdown_path,
            "playthrough/transcript.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_captions() {
    group "the caption track and the transcripts"
    check_subtitle_stream
    check_captioned_video_survived
    check_captions_not_burned_in
    run_checker caption \
        "${PLAYTHROUGH_TRANSCRIPT_SRT}" \
        "${PLAYTHROUGH_TRANSCRIPT_MD}" \
        "${PLAYTHROUGH_TIMELINE}" \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "${ARITHMETIC_EPSILON}"
}


# ---------------------------------------------------------------------
# 6  THE LUMINANCE GATE
#
# The guard against SDL_VIDEODRIVER=dummy, and the reason a black film
# cannot pass unnoticed.  BOTH TERMS ARE LOAD-BEARING:
#
#   * mean > 0 catches a fully black frame, which is exactly what the
#     dummy driver produces -- the game runs, the captures succeed, the
#     encode succeeds, every count tallies, and nothing is visible.
#   * std > 0 additionally catches a uniform solid-colour frame, which a
#     mean-only test would happily pass.
#
# The threshold is strictly `> 0` and never a magnitude.  How bright a
# capture is depends on the tileset and on what the survivor was looking
# at; a gate that demanded a particular mean would fail honest captures
# of a dark cellar.  The calibration reading is reported as provenance so
# a reader knows where the number in the plan came from.
#
# The comparison goes through awk.  `[ "0.27" -gt 0 ]` is not a working
# test in any shell -- it is an integer operator applied to a string, and
# it fails at the syntax level rather than returning a wrong answer.
# ---------------------------------------------------------------------
sample_indices() {
    local count="$1"
    local how_many="$2"
    "${AWK}" -v n="${count}" -v s="${how_many}" 'BEGIN {
        if (n <= 0) { exit }
        if (s > n) { s = n }
        if (s < 1) { s = 1 }
        if (n == 1 || s == 1) { print 1; exit }
        for (i = 0; i < s; i++) {
            print 1 + int(i * (n - 1) / (s - 1) + 0.5)
        }
    }' | sort -n -u
}

check_one_frame_luminance() {
    local path="$1"
    local label="$2"
    local reading="" mean="" std="" geometry=""
    LAST_LUMINANCE=""
    if [ ! -f "${path}" ]; then
        record_fail "${label} is a real, non-blank image" \
            "no such file: $(rel "${path}")" "a readable PNG"
        return 1
    fi
    reading="$(luminance "${path}")"
    mean="${reading%% *}"
    std="${reading##* }"
    if [ -z "${reading}" ] || ! is_number "${mean}" ||
            ! is_number "${std}"; then
        record_fail "${label} is a real, non-blank image" \
            "could not measure grayscale statistics (read \
'${reading}')" \
            "a mean and a standard deviation from convert"
        return 1
    fi
    LAST_LUMINANCE="${reading}"
    if ! "${AWK}" -v m="${mean}" -v s="${std}" \
            'BEGIN { exit !(m > 0 && s > 0) }'; then
        geometry="$("${IDENTIFY}" -format '%wx%h' "${path}" \
            2>/dev/null || true)"
        record_fail "${label} is a real, non-blank image" \
            "mean=${mean} std=${std} at ${geometry:-unknown geometry}" \
            "mean > 0 AND std > 0 -- mean=0 std=0 is the \
SDL_VIDEODRIVER=dummy signature, and std=0 alone is a uniform \
solid-colour frame"
        return 1
    fi
    return 0
}

check_frame_geometry() {
    local path="$1"
    local geometry=""
    geometry="$("${IDENTIFY}" -format '%wx%h' "${path}" \
        2>/dev/null || true)"
    if [ "${geometry}" = \
"${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}" ]; then
        return 0
    fi
    printf '%s' "${geometry:-unreadable}"
    return 1
}

# capture_path INDEX -- the canonical path of one capture.
#
# The name is built from env.sh's PLAYTHROUGH_FRAME_FORMAT, which is the
# same format capture.sh writes with and manifest.py records; a second
# hard-coded '%05d' here is exactly the divergence that indirection
# exists to prevent.  SC2059 objects to a variable used as a printf
# format, which is the point, and the expansion is asserted rather than
# assumed.
capture_path() {
    local name=""
    # shellcheck disable=SC2059
    name="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}" "$1")"
    if [ "${name}" = "${PLAYTHROUGH_FRAME_FORMAT}" ]; then
        return 1
    fi
    printf '%s' "${PLAYTHROUGH_FRAMES_DIR}/${name}"
}

check_sampled_captures() {
    local count="" index="" path="" failures=0 checked=0
    local -a bad_geometry=()
    local geometry="" sample_count=""
    count="$(fact capture_count)"
    if ! is_number "${count}" || [ "${count}" -eq 0 ]; then
        record_fail "sampled captures are real, non-blank images" \
            "no capture count was established" \
            "a non-zero capture count from group 2"
        return 0
    fi
    sample_count="${LUMINANCE_SAMPLES}"
    if [ "${sample_count}" = "${LUMINANCE_SAMPLES_ALL}" ]; then
        sample_count="${count}"
    fi
    while read -r index; do
        [ -n "${index}" ] || continue
        if ! path="$(capture_path "${index}")"; then
            record_fail "sampled captures are real, non-blank images" \
                "PLAYTHROUGH_FRAME_FORMAT='${PLAYTHROUGH_FRAME_FORMAT}' \
did not expand" "a printf format containing %05d"
            return 0
        fi
        checked=$((checked + 1))
        if ! check_one_frame_luminance "${path}" \
                "capture $(printf '%05d' "${index}")"; then
            failures=$((failures + 1))
            continue
        fi
        if ! geometry="$(check_frame_geometry "${path}")"; then
            bad_geometry+=("$(printf '%05d' "${index}")=${geometry}")
        fi
    done < <(sample_indices "${count}" "${sample_count}")

    if [ "${failures}" -eq 0 ]; then
        record_pass "sampled captures are real, non-blank images" \
            "${checked} of ${count} captures read (the first, the last \
and an even spread between; '--samples all' reads every one); each has \
mean > 0 and std > 0"
    fi
    if [ "${#bad_geometry[@]}" -eq 0 ]; then
        record_pass "sampled captures are at the X root's resolution" \
            "${checked} captures at \
${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}"
    else
        record_fail "sampled captures are at the X root's resolution" \
            "${bad_geometry[*]}" \
            "${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT} \
on every capture"
    fi
}

# The film is measured independently of its sources, because a black
# FILM is a distinct fault from a black capture: a wrong pixel format, a
# mis-built concat list or a re-encode could blank the picture after the
# captures were verified.
check_film_luminance() {
    local file="" label="" extracted=""
    for file in "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"; do
        label="$(rel "${file}")"
        extracted="${SCRATCH}/luminance-$(basename "${file}").png"
        if ! "${FFMPEG}" -nostdin -y -v error -ss "${EXTRACT_OFFSET}" \
                -i "${file}" -frames:v 1 "${extracted}" \
                >/dev/null 2>&1; then
            record_fail "a frame taken out of ${label} is not blank" \
                "no frame could be decoded at ${EXTRACT_OFFSET}s" \
                "one decodable frame"
            continue
        fi
        if check_one_frame_luminance "${extracted}" \
                "a frame taken out of ${label}"; then
            record_pass "a frame taken out of ${label} is not blank" \
                "at ${EXTRACT_OFFSET}s, mean and std: ${LAST_LUMINANCE}"
        fi
    done
}

group_luminance() {
    group "the luminance gate -- proof the pixels are real"
    record_info "the calibration reading behind this threshold" \
        "${LUMINANCE_REFERENCE}"
    check_sampled_captures
    check_film_luminance
}


# ---------------------------------------------------------------------
# 7  VERSION CONTROL -- THE "COMMITTED IN APPEARANCE ONLY" GUARD
#
# This is the group that exists because `git add` reports success while
# skipping an ignored file.  Cataclysm-DDA names its per-character save
# files with a leading '#' (src/game_io.cpp:601-641), .gitignore carries
# `\#*` at line 131, an unanchored `*.log` at line 31 and `debug.log` at
# line 79, and without the terminal `!/playthrough/**` negation the save
# is silently absent from every commit while every other count still
# tallies.  So membership is asserted TWICE, from both directions: the
# file is in `git ls-files`, AND `git check-ignore` denies knowing it.
#
# TWO SHAPES OF CHARACTER SAVE ARE BOTH CORRECT.  With world compression
# enabled -- WORLD_COMPRESSION2 defaults to true -- the write is
# `playerfile + SAVE_EXTENSION + zzip_suffix`, i.e. `#<b64>.sav.zzip`
# (src/game_io.cpp:601-641, src/worldfactory.h:25); without it, the plain
# `#<b64>.sav`.  Either satisfies this gate.  Demanding only the plain
# form would manufacture a failure on a default world.
#
# `.shortcuts` IS NEVER REQUIRED.  SAVE_EXTENSION_SHORTCUTS exists at
# src/path_info.h:17, but the only write of it is inside
# `#if defined(__ANDROID__)` (src/game_io.cpp:629-634): it is an Android
# file and will never appear on a Linux host.  A gate that required it
# would fail every correct run.
# ---------------------------------------------------------------------
git_tracked() {
    "${GIT}" ls-files -- "$@" 2>/dev/null || true
}

git_tracked_count() {
    git_tracked "$@" | "${GREP}" -c . || true
}

check_git_worktree() {
    local top=""
    top="$("${GIT}" rev-parse --show-toplevel 2>/dev/null || true)"
    if [ "${top}" = "${PLAYTHROUGH_REPO_ROOT}" ]; then
        record_pass "the artifacts live in the working tree of a git \
repository" "$(rel "${top}")"
        return 0
    fi
    record_fail "the artifacts live in the working tree of a git \
repository" \
        "git reports '${top:-nothing}' while env.sh resolved this \
checkout to '$(rel "${PLAYTHROUGH_REPO_ROOT}")'" \
        "the same directory -- every check below reads git from here"
}

# character_save_paths -- the TRACKED character save files, in either
# accepted shape.  Printed one per line; empty when there are none.
character_save_paths() {
    git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -E '/#[^/]*\.sav(\.zzip)?$' || true
}

# saves_on_disk PATTERN -- matching files that EXIST, whatever git thinks
# of them, printed one absolute path per line.
#
# This is deliberately independent of the index, and the reason is the
# failure mode itself: if the save is not tracked, a list built from `git
# ls-files` is empty, and a check-ignore run over that empty list would
# examine nothing and report success.  The two halves of the guard have
# to be measured from two different places or they collapse into one.
# `find -name` rather than a glob built from a variable: the pattern is
# then an argument rather than something the shell has to be trusted not
# to split, and the depth bounds keep the search to save/<World>/<file>.
saves_on_disk() {
    find "${PLAYTHROUGH_SAVE_DIR}" -mindepth 2 -maxdepth 2 -type f \
        -name "$1" -print 2>/dev/null || true
}

check_save_tracked() {
    local masters="" saves="" worldoptions=""
    masters="$(git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -c '/master\.gsav$' || true)"
    if [ "${masters:-0}" -ge 1 ]; then
        record_pass "the world's own save file is tracked by git" \
            "${masters} master.gsav (SAVE_MASTER, src/path_info.h:11)"
    else
        record_fail "the world's own save file is tracked by git" \
            "no master.gsav under $(rel "${PLAYTHROUGH_SAVE_DIR}") is \
tracked" \
            "at least one -- without it there is no world to resume"
    fi

    saves="$(character_save_paths | "${GREP}" -c . || true)"
    if [ "${saves:-0}" -ge 1 ]; then
        record_pass "the survivor's own save file is tracked by git" \
            "${saves} file(s) matching #<base64>.sav or \
#<base64>.sav.zzip -- both shapes are correct, the compressed one being \
the default"
    else
        record_fail "the survivor's own save file is tracked by git" \
            "no #<base64>.sav or #<base64>.sav.zzip is tracked" \
            "at least one; if none is tracked, .gitignore's \\#* rule \
(line 131) swallowed it and 'git add' said nothing"
    fi

    worldoptions="$(git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -c '/worldoptions\.json$' || true)"
    if [ "${worldoptions:-0}" -ge 1 ]; then
        record_pass "the world's option overrides are tracked by git" \
            "${worldoptions} worldoptions.json"
    else
        record_fail "the world's option overrides are tracked by git" \
            "no worldoptions.json is tracked" \
            "at least one, so the world can be reproduced"
    fi
}

# ---------------------------------------------------------------------
# check-ignore IS THE PROOF THAT NOTHING IS SILENTLY EXCLUDED -- AND IT
# HAS TO BE RUN THE HARD WAY, OR IT PROVES NOTHING AT ALL.
#
# Two traps, both measured on this checkout:
#
#   1. WITHOUT --no-index, `git check-ignore` CONSULTS THE INDEX and
#      reports any TRACKED path as not-ignored, whatever .gitignore says.
#      Measured: with the terminal negation deleted, a tracked character
#      save still came back "not ignored" -- so the naive form of this
#      check passes even when the rule that saves the file has been
#      removed.  It is vacuous exactly when it matters, because on a
#      fresh session the file is NOT yet tracked and `git add` will
#      apply the patterns, not the index.
#   2. WITH --no-index, check-ignore exits ZERO whenever ANY pattern
#      matches -- INCLUDING A NEGATION.  Measured: the same path exits 0
#      both ways, printing `.gitignore:275:!/playthrough/**` when the
#      negation is present and `.gitignore:131:\#*` when it is not.  So
#      the exit status cannot answer the question either.
#
# The pattern that DECIDED is what answers it: -v prints it, and a
# pattern beginning with '!' means re-included.  So the verdict here is
# read off the pattern, and the only outcomes accepted are "no pattern
# matched" and "the deciding pattern was a negation".
# ---------------------------------------------------------------------
deciding_ignore_pattern() {
    "${GIT}" check-ignore -v --no-index -- "$1" 2>/dev/null |
        head -n 1 |
        sed -e 's/\t.*$//' -e 's/^[^:]*:[0-9]*://' || true
}

check_nothing_ignored() {
    local -a paths=()
    local path="" candidate=""
    paths+=("${PLAYTHROUGH_MANIFEST}" "${PLAYTHROUGH_TIMELINE}"
        "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"
        "${PLAYTHROUGH_TRANSCRIPT_SRT}" "${PLAYTHROUGH_TRANSCRIPT_MD}"
        "${PLAYTHROUGH_DOSSIER}" "${PLAYTHROUGH_REQUIREMENTS}"
        "${PLAYTHROUGH_CONCAT_LIST}")
    if candidate="$(capture_path 1)"; then
        paths+=("${candidate}")
    fi
    # The save-side paths come off the FILESYSTEM, never out of the
    # index -- see saves_on_disk for why that independence is the whole
    # point of this check.
    local pattern=""
    for pattern in '#*.sav' '#*.sav.zzip' '*.log' 'master.gsav' \
            'worldoptions.json'; do
        while IFS= read -r path; do
            [ -n "${path}" ] || continue
            paths+=("${path}")
        done < <(saves_on_disk "${pattern}")
    done
    for path in "${PLAYTHROUGH_CONFIG_DIR}/debug.log" \
            "${PLAYTHROUGH_USERDIR}/debug.log"; do
        if [ -f "${path}" ]; then
            paths+=("${path}")
        fi
    done

    local -a ignored=()
    local decided="" negations=0 unmatched=0
    for path in "${paths[@]}"; do
        decided="$(deciding_ignore_pattern "${path}")"
        if [ -z "${decided}" ]; then
            unmatched=$((unmatched + 1))
        elif [ "${decided#!}" != "${decided}" ]; then
            negations=$((negations + 1))
        else
            ignored+=("$(rel "${path}") <- ${decided}")
        fi
    done
    if [ "${#ignored[@]}" -eq 0 ]; then
        record_pass "git's ignore rules exclude none of the artifact \
classes" \
            "${#paths[@]} representative paths -- a character save, \
master.gsav, worldoptions.json, an engine log, a capture, both films, \
the cue file, the readable record, the record, the timeline, the concat \
list, the dossier and the requirements -- of which ${negations} are \
re-included by a negation and ${unmatched} match no rule at all"
        return 0
    fi
    record_fail "git's ignore rules exclude none of the artifact \
classes" \
        "excluded, with the deciding pattern: ${ignored[*]}" \
        "no path decided by a non-negated rule -- .gitignore's terminal \
'!/playthrough/**' must be the LAST matching pattern, and remember it \
cannot re-include anything whose parent DIRECTORY was excluded, because \
git never descends into an excluded directory to evaluate negations \
inside it"
}

check_every_class_tracked() {
    local -a missing=()
    local entry="" label="" path="" count=""
    local -a inventory=(
        "the captures:${PLAYTHROUGH_FRAMES_DIR}"
        "the transition images:${PLAYTHROUGH_TRANSITIONS_DIR}"
        "the film:${PLAYTHROUGH_MOVIE}"
        "the captioned film:${PLAYTHROUGH_MOVIE_CC}"
        "the cue file:${PLAYTHROUGH_TRANSCRIPT_SRT}"
        "the readable record:${PLAYTHROUGH_TRANSCRIPT_MD}"
        "the record:${PLAYTHROUGH_MANIFEST}"
        "the timeline:${PLAYTHROUGH_TIMELINE}"
        "the dossier:${PLAYTHROUGH_DOSSIER}"
        "the requirements:${PLAYTHROUGH_REQUIREMENTS}"
        "the engine's configuration:${PLAYTHROUGH_CONFIG_DIR}"
    )
    for entry in "${inventory[@]}"; do
        label="${entry%%:*}"
        path="${entry#*:}"
        count="$(git_tracked_count "${path}")"
        if [ "${count:-0}" -eq 0 ]; then
            missing+=("${label} ($(rel "${path}"))")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_pass "every artifact class is tracked by git" \
            "${#inventory[@]} classes, each with at least one tracked \
file"
        return 0
    fi
    record_fail "every artifact class is tracked by git" \
        "untracked class(es): ${missing[*]}" \
        "all ${#inventory[@]} classes tracked -- save data, captures, \
film, transcripts and the requirements are all committed"
}

# THE DECIMATION CHECK.  If the tracked capture count is lower than the
# count on disk, frames were sampled, deduplicated or partly added.  That
# is a failure and not an optimisation: repository size never outranks
# completeness here.
check_tracked_frame_count() {
    local tracked="" ondisk=""
    tracked="$(git_tracked_count "${PLAYTHROUGH_FRAMES_DIR}")"
    ondisk="$(fact capture_count)"
    if ! is_number "${ondisk}"; then
        record_fail "every capture on disk is tracked by git" \
            "the on-disk capture count was not established" \
            "a count from group 2"
        return 0
    fi
    if [ "${tracked:-0}" -eq "${ondisk}" ]; then
        record_pass "every capture on disk is tracked by git" \
            "${tracked} tracked == ${ondisk} on disk"
        return 0
    fi
    record_fail "every capture on disk is tracked by git" \
        "${tracked:-0} tracked against ${ondisk} on disk" \
        "equal counts -- no decimation, no sampling, no deduplication \
and no partial 'git add'"
}

check_nothing_uncommitted() {
    local dirty="" count=""
    dirty="$("${GIT}" status --porcelain -uall -- \
        "${PLAYTHROUGH_DIR}" 2>/dev/null || true)"
    count="$(printf '%s' "${dirty}" | "${GREP}" -c . || true)"
    if [ "${count:-0}" -eq 0 ]; then
        record_pass "nothing under playthrough/ is left uncommitted" \
            "git status --porcelain is empty"
        return 0
    fi
    record_fail "nothing under playthrough/ is left uncommitted" \
        "${count} path(s): $(printf '%s' "${dirty}" | head -n 6 |
            tr '\n' ';')" \
        "an empty porcelain -- every artifact staged and committed"
}

check_no_bytecode() {
    local name="${1:-no interpreter bytecode has been left under \
playthrough/}"
    local -a found=()
    local path=""
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        found+=("$(rel "${path}")")
    done < <(find "${PLAYTHROUGH_DIR}" \
        \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) \
        -print 2>/dev/null || true)
    local tracked=""
    tracked="$(git_tracked "${PLAYTHROUGH_DIR}" |
        "${GREP}" -E '(__pycache__|\.pyc$|\.pyo$)' | head -n 3 || true)"
    if [ "${#found[@]}" -eq 0 ] && [ -z "${tracked}" ]; then
        record_pass "${name}" \
            "no __pycache__, .pyc or .pyo on disk or in the index"
        return 0
    fi
    record_fail "${name}" \
        "on disk: ${found[*]:-none}; tracked: ${tracked:-none}" \
        "none -- env.sh exports PYTHONDONTWRITEBYTECODE=1 and every \
interpreter call adds -B, and the .gitignore negation deliberately adds \
no re-exclusion, so a stray file here WOULD become trackable"
}

# THE COMMIT ORDER.  Ancestry, not dates: a timestamp can be anything,
# whereas "this commit is reachable from that one" is a fact about the
# graph.  The dossier had to exist before the first gameplay frame, so its
# earliest commit must be a STRICT ancestor of the first capture's.
first_commit_for() {
    "${GIT}" log --format='%H' -- "$1" 2>/dev/null | tail -n 1 || true
}

check_commit_order() {
    local userdir_commits="" dossier="" frame="" capture=""
    userdir_commits="$("${GIT}" log --format='%H' -- \
        "${PLAYTHROUGH_USERDIR}" 2>/dev/null | "${GREP}" -c . || true)"
    if [ "${userdir_commits:-0}" -ge 2 ]; then
        record_pass "the save was committed at both mandated points" \
            "${userdir_commits} commits touch \
$(rel "${PLAYTHROUGH_USERDIR}") -- at least one after the survivor was \
created and one after the session was saved and quit"
    else
        record_fail "the save was committed at both mandated points" \
            "${userdir_commits:-0} commit(s) touch \
$(rel "${PLAYTHROUGH_USERDIR}")" \
            "at least 2 -- one after character creation, one after the \
in-game Save and Quit"
    fi

    dossier="$(first_commit_for "${PLAYTHROUGH_DOSSIER}")"
    if ! capture="$(capture_path 1)"; then
        capture=""
    fi
    if [ -n "${capture}" ]; then
        frame="$(first_commit_for "${capture}")"
    fi
    if [ -z "${dossier}" ] || [ -z "${frame}" ]; then
        record_fail "the dossier was written before the first \
gameplay frame" \
            "dossier commit '${dossier:-none}', first capture commit \
'${frame:-none}'" \
            "both present in history"
        return 0
    fi
    if [ "${dossier}" = "${frame}" ]; then
        record_fail "the dossier was written before the first \
gameplay frame" \
            "both were introduced by the same commit \
${dossier:0:10}" \
            "the dossier in an EARLIER commit -- it is the survivor \
described before play, not alongside it"
        return 0
    fi
    if "${GIT}" merge-base --is-ancestor "${dossier}" "${frame}" \
            2>/dev/null; then
        record_pass "the dossier was written before the first \
gameplay frame" \
            "${dossier:0:10} is an ancestor of ${frame:0:10}"
        return 0
    fi
    record_fail "the dossier was written before the first gameplay \
frame" \
        "${dossier:0:10} is not an ancestor of ${frame:0:10}" \
        "the dossier's first commit reachable from the first capture's"
}

check_git_identity() {
    local name="" email=""
    name="$("${GIT}" config user.name 2>/dev/null || true)"
    email="$("${GIT}" config user.email 2>/dev/null || true)"
    if [ -n "${name}" ] && [ -n "${email}" ]; then
        record_pass "git has an identity to commit these artifacts \
under" "${name} <${email}>"
        return 0
    fi
    record_fail "git has an identity to commit these artifacts under" \
        "user.name='${name}' user.email='${email}'" \
        "both set -- without them every commit of the evidence fails \
outright"
}

group_version_control() {
    group "version control -- the save is really committed"
    check_git_worktree
    check_git_identity
    check_save_tracked
    check_nothing_ignored
    check_every_class_tracked
    check_tracked_frame_count
    check_nothing_uncommitted
    check_no_bytecode
    check_commit_order
}


# ---------------------------------------------------------------------
# 8  NO CHEATING, AS A CHECKABLE PROPERTY
#
# This is where a claim of good faith stops resting on the word of
# whoever played the session and becomes a property of a committed file
# that a stranger can verify.
#
# All three of the engine's debug actions -- `debug_mode` ("Toggle debug
# mode"), `debug` ("Debug menu") and `debug_hour_timer` -- are declared in
# data/raw/keybindings.json WITHOUT a `bindings` array, at lines
# 3398-3403, 3404-3409 and 3466-3471.  Unbound by default means
# unreachable by any keystroke: to use them at all somebody would have to
# bind one, and a user binding is written to
# <userdir>/config/keybindings.json (src/path_info.cpp:400-402), which is
# a COMMITTED artifact.  So the absence of that file, or its silence about
# those three ids, is independent evidence.
#
# The engine's own log is read as well, because it is the other place a
# debug session would leave a mark, and it is committed too.
# ---------------------------------------------------------------------
check_no_debug_binding() {
    local path="${PLAYTHROUGH_KEYBINDINGS_JSON}"
    local hits=""
    if [ ! -f "${path}" ]; then
        record_pass "no keybinding exists for any debug action" \
            "$(rel "${path}") does not exist, so nothing was ever \
bound; the engine ships debug, debug_mode and debug_hour_timer with no \
bindings array, which leaves them unreachable"
        return 0
    fi
    hits="$("${GREP}" -nE "${DEBUG_ACTION_PATTERN}" "${path}" \
        2>/dev/null || true)"
    if [ -z "${hits}" ]; then
        record_pass "no keybinding exists for any debug action" \
            "$(rel "${path}") exists and names none of debug, \
debug_mode or debug_hour_timer"
        return 0
    fi
    record_fail "no keybinding exists for any debug action" \
        "$(rel "${path}"): $(printf '%s' "${hits}" | head -n 4 |
            tr '\n' ';')" \
        "no mention of \"debug\", \"debug_mode\" or \
\"debug_hour_timer\" -- binding one is the only way to reach the debug \
menu, and this file is committed precisely so that can be checked"
}

check_no_debug_activation() {
    local relative="" path="" hits="" inspected=0
    local -a findings=()
    for relative in "${DEBUG_LOG_RELATIVE_PATHS[@]}"; do
        path="${PLAYTHROUGH_USERDIR}/${relative}"
        [ -f "${path}" ] || continue
        inspected=$((inspected + 1))
        hits="$("${GREP}" -inE 'debug mode|debug menu' "${path}" \
            2>/dev/null || true)"
        if [ -n "${hits}" ]; then
            findings+=("$(rel "${path}"): $(printf '%s' "${hits}" |
                head -n 2 | tr '\n' ';')")
        fi
    done
    if [ "${inspected}" -eq 0 ]; then
        record_pass "the engine's own log records no debug-mode \
activation" \
            "the engine wrote no log at \
$(rel "${PLAYTHROUGH_USERDIR}")/{config/debug.log,debug.log}, so there \
is nothing in one to find"
        return 0
    fi
    if [ "${#findings[@]}" -eq 0 ]; then
        record_pass "the engine's own log records no debug-mode \
activation" \
            "${inspected} log(s) read, no mention of debug mode or the \
debug menu"
        return 0
    fi
    record_fail "the engine's own log records no debug-mode \
activation" "${findings[*]}" \
        "no such line -- no debug mode, no debug menu, no spawning, no \
stat editing, no teleport, no map reveal, not even to avoid death"
}

group_no_cheating() {
    group "no cheating, as a checkable property"
    check_no_debug_binding
    check_no_debug_activation
}

# ---------------------------------------------------------------------
# 9  THE BINARY AND REPOSITORY HYGIENE
#
# The tiles-and-never-curses rule is discharged from the binary's own
# mouth: `--version` prints the build's feature list, and `+tiles` in it
# is the proof.  The rule is about the BINARY and not the artwork: a build
# linked against SDL2 and rendering through the SDL tiles path satisfies
# it whichever tileset is selected.
#
# flake8 IS SCOPED TO playthrough/ AND MUST BE.  A global exit code of
# zero is not achievable at HEAD: measured here, flake8 7.3.0 reports four
# pre-existing F824 findings under tools/ -- two at
# tools/generate_changelog.py:689, one at :550 and one at
# tools/json_tools/util.py:378 -- none of which is this feature's, and
# asserting a global zero would report a failure that belongs to somebody
# else.  `.flake8` is deliberately NOT given a `playthrough` exclude
# either: the new code satisfies the repository's existing 79-column
# contract rather than being exempted from it, and that too is asserted.
# ---------------------------------------------------------------------
check_binary_is_tiles() {
    local banner=""
    if [ ! -x "${PLAYTHROUGH_GAME_BIN}" ]; then
        record_fail "the binary that was played is the SDL tiles \
build" \
            "$(rel "${PLAYTHROUGH_GAME_BIN}") is absent or not \
executable" \
            "a built ./cataclysm-tiles reporting '+tiles'; the binary is \
git-ignored (.gitignore:75), so build it with \
playthrough/tooling/launch_game.sh, which owns the build"
        return 0
    fi
    banner="$("${PLAYTHROUGH_GAME_BIN}" --version 2>&1 |
        tr '\n' ' ' || true)"
    case "${banner}" in
        *"+tiles"*)
            record_pass "the binary that was played is the SDL tiles \
build" "${banner}"
            ;;
        *)
            record_fail "the binary that was played is the SDL tiles \
build" "${banner:-<no version banner>}" \
                "a banner containing '+tiles' -- the curses build is \
never an acceptable substitute"
            ;;
    esac
}

check_lint_scoped() {
    local output="" status=0 count=""
    if [ "${#FLAKE8_CMD[@]}" -eq 0 ]; then
        record_fail "the new Python satisfies the repository's own \
lint contract" \
            "no flake8 could be resolved" \
            "flake8 on PATH, importable as a module, or named by \
PLAYTHROUGH_FLAKE8 -- the check is not skippable, because a lint gate \
that silently does not run is not a gate"
        return 0
    fi
    set +e
    output="$("${FLAKE8_CMD[@]}" playthrough/ 2>&1)"
    status=$?
    set -e
    count="$(printf '%s' "${output}" | "${GREP}" -c . || true)"
    if [ "${status}" -eq 0 ] && [ "${count:-0}" -eq 0 ]; then
        record_pass "the new Python satisfies the repository's own \
lint contract" \
            "flake8 playthrough/ reports nothing, under .flake8's own \
configuration and its default 79-column limit"
        return 0
    fi
    record_fail "the new Python satisfies the repository's own lint \
contract" \
        "${count:-0} finding(s), exit ${status}: $(printf '%s' \
"${output}" | head -n 4 | tr '\n' ';')" \
        "zero findings under playthrough/ -- scoped deliberately, \
because HEAD already carries pre-existing F824 findings under tools/ \
that are not this feature's"
}

check_flake8_not_weakened() {
    local hits=""
    if [ ! -f ".flake8" ]; then
        record_fail "the shared lint configuration was not weakened" \
            "there is no .flake8 in this checkout" \
            "the repository's .flake8, unmodified"
        return 0
    fi
    hits="$("${GREP}" -n 'playthrough' .flake8 2>/dev/null || true)"
    if [ -z "${hits}" ]; then
        record_pass "the shared lint configuration was not weakened" \
            ".flake8 names playthrough nowhere, so the new code passes \
the existing gate rather than being excluded from it"
        return 0
    fi
    record_fail "the shared lint configuration was not weakened" \
        "${hits}" \
        "no 'playthrough' token in .flake8 -- relaxing shared \
configuration to accommodate new code is the wrong trade"
}

check_timeline_tests() {
    local suite="${PLAYTHROUGH_TOOLING_DIR}/test_timeline.py"
    local output="" status=0 summary=""
    if [ ! -f "${suite}" ]; then
        record_fail "the timeline's own test suite passes" \
            "$(rel "${suite}") is absent" \
            "the regression suite that covers the clamp, the rollover \
guard, the cue arithmetic and the timecode formatter"
        return 0
    fi
    set +e
    output="$("${PYTHON}" -B "${suite}" 2>&1)"
    status=$?
    set -e
    summary="$(printf '%s' "${output}" |
        "${GREP}" -E '^(Ran |OK|FAILED)' | tr '\n' ' ' || true)"
    if [ "${status}" -eq 0 ]; then
        record_pass "the timeline's own test suite passes" \
            "${summary:-exit 0}"
        return 0
    fi
    record_fail "the timeline's own test suite passes" \
        "exit ${status}: ${summary:-$(printf '%s' "${output}" |
            tail -n 3 | tr '\n' ';')}" \
        "exit 0 -- the deterministic half of this feature is the half \
that can be unit tested, so it is"
}

# THE CHANGE SURFACE.  The engine, its tests, its content, its build
# system and its CI are consumed read-only; the only pre-existing tracked
# files this feature is allowed to have touched are .gitignore and
# .gitattributes, and both changes are additive appends.
check_change_surface() {
    local base="${BASE_COMMIT}"
    local changed="" allowed=""
    if [ -z "${base}" ]; then
        base="$(default_base_commit || true)"
    fi
    if [ -z "${base}" ] ||
            ! "${GIT}" rev-parse --verify --quiet "${base}" \
                >/dev/null 2>&1; then
        record_fail "the change surface is only the two ignore files \
and playthrough/" \
            "no usable base commit (tried '${base:-none}')" \
            "a reachable commit -- pass --base <commit> to name one"
        return 0
    fi
    record_info "the base commit the change surface is measured from" \
        "$("${GIT}" log -1 --format='%h %s' "${base}" 2>/dev/null ||
            printf '%s' "${base}")"
    changed="$("${GIT}" diff --name-only "${base}..HEAD" \
        2>/dev/null || true)"
    allowed=" ${ALLOWED_FOREIGN_PATHS} "
    local path=""
    local -a foreign_paths=()
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        case "${path}" in
            playthrough/*) continue ;;
        esac
        case "${allowed}" in
            *" ${path} "*) continue ;;
        esac
        foreign_paths+=("${path}")
    done <<EOF
${changed}
EOF
    if [ "${#foreign_paths[@]}" -eq 0 ]; then
        record_pass "the change surface is only the two ignore files \
and playthrough/" \
            "$(printf '%s' "${changed}" | "${GREP}" -c . || true) \
changed \
path(s) since ${base:0:10}, all of them under playthrough/ or one of: \
${ALLOWED_FOREIGN_PATHS}"
        return 0
    fi
    # Bounded, because an ill-chosen base can put a thousand upstream
    # paths in this list, and a finding nobody can read is a finding
    # nobody acts on.  The count is the number that matters; the first
    # few name the kind of thing that leaked in.
    local total="${#foreign_paths[@]}"
    local shown="${foreign_paths[*]:0:8}"
    if [ "${total}" -gt 8 ]; then
        shown="${shown} ... (and $((total - 8)) more)"
    fi
    record_fail "the change surface is only the two ignore files and \
playthrough/" "${total} path(s) outside the allowance: ${shown}" \
        "nothing outside playthrough/ except ${ALLOWED_FOREIGN_PATHS} \
-- src/, tests/, data/, gfx/, the build system and .github/ are read \
only for this feature"
}

group_hygiene() {
    group "the binary and repository hygiene"
    check_binary_is_tiles
    check_lint_scoped
    check_flake8_not_weakened
    check_timeline_tests
    check_change_surface
    # Re-read for bytecode AFTER the suite ran, so the claim is that this
    # gate itself left no trace and not merely that none was there before.
    check_no_bytecode "this gate itself left no interpreter bytecode \
behind"
}


# ---------------------------------------------------------------------
# THE SUMMARY
#
# One human line, then the machine block.  Nothing here decides the exit
# status: that is taken once, at file scope, after every group has run,
# which is what makes "run every check" true rather than aspirational.
#
# The message is assembled into a variable and printed with a '%s'
# format.  A multi-line printf FORMAT would need a backslash before each
# newline, and a backslash inside a single-quoted format is a literal
# backslash rather than a line continuation -- it would print in the
# report.
# ---------------------------------------------------------------------
summarise_run() {
    local total=$((PASSES + FAILURES))
    local message=""
    printf '\n'
    if [ "${FAILURES}" -eq 0 ]; then
        message="SUMMARY  ${PASSES} of ${total} checks passed, "
        message="${message}${INFOS} informational note(s); the "
        message="${message}committed artifacts are what they claim "
        message="${message}to be."
    else
        message="SUMMARY  ${FAILURES} of ${total} checks FAILED "
        message="${message}(${PASSES} passed, ${INFOS} informational "
        message="${message}note(s)).  Each failure above prints what "
        message="${message}was observed next to what was required."
    fi
    printf '%s\n' "${message}"
    note VERIFY_CHECKS "${total}"
    note VERIFY_PASSES "${PASSES}"
    note VERIFY_FAILURES "${FAILURES}"
    note VERIFY_INFOS "${INFOS}"
    note VERIFY_CAPTURES "$(fact capture_count '?')"
    note VERIFY_ROWS "$(fact manifest_rows '?')"
    note VERIFY_TIMELINE_TOTAL "$(fact timeline_total '?')"
    note VERIFY_TRANSITIONS "$(fact transition_groups '?')"
    if [ "${FAILURES}" -eq 0 ]; then
        note VERIFY pass
    else
        note VERIFY fail
    fi
}

main() {
    parse_arguments "$@"
    open_scratch
    : >"${SCRATCH}/facts"
    emit_record_checker
    emit_timeline_checker
    emit_caption_checker

    printf '%s\n' "verify_artifacts.sh -- the acceptance gate for the \
playthrough capture subsystem"
    printf '%s\n' "reading the committed artifacts under \
$(rel "${PLAYTHROUGH_DIR}")/ at the repository root"

    group_environment
    group_record
    group_timeline
    group_container
    group_captions
    group_luminance
    group_version_control
    group_no_cheating
    group_hygiene

    summarise_run
    return "${EX_OK}"
}

# main always returns success; the verdict on the ARTIFACTS is the
# failure counter, and it is turned into an exit status exactly once,
# here, after every group has been given its chance to report.  `exit`
# at file scope also keeps the ERR trap out of it: a non-zero `return`
# from main would fire the trap and print a spurious FATAL line about a
# gate that worked perfectly.
main "$@"

if [ "${FAILURES}" -ne 0 ]; then
    exit "${EX_FAILED}"
fi
exit "${EX_OK}"

