#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/launch_game.sh
#
# The launcher for the playthrough capture pipeline: it establishes a
# verified starting state and reports what it verified.  Nothing here
# plays the game -- session.py sends the keystrokes and capture.sh
# photographs the result.  Five steps, each asserted rather than
# assumed:
#
#   1. BUILD ./cataclysm-tiles if absent, then prove from the binary's
#      own --version output that it is the SDL tiles build, never curses.
#   2. BRING UP the headless X surface -- Xvfb under SDL_VIDEODRIVER=x11
#      plus a window manager -- only if it is not already serving, and
#      assert the ROOT window is exactly 1920x1080 at depth 24, the
#      geometry capture.sh photographs.
#   3. RESOLVE the REQUIRED tileset, MSXotto+, installed already or
#      hydrated from a pre-placed pack whose provenance is verified
#      first.  Its absence FAILS THE RUN: one artwork contract, no
#      substitute of any kind.
#   4. PROBE for an existing save, so a run that finds a CHARACTER save
#      RESUMES it instead of replacing it.  A world with no character in
#      it has nothing to continue and is reused.
#   5. LAUNCH the game from the repository root in its own session
#      (setsid + nohup, so a signal to this shell's process group misses
#      it) and wait for a window whose OWNING PROCESS is confirmed to be
#      this checkout's binary -- found by class, accepted by identity.
#      A launch the session will be CAPTURED FROM must also pass
#      assert_capture_preconditions: a clean trust state, and the seeded
#      option contract VERIFIED through seed_options.py --verify-only,
#      because the existence of options.json says nothing about the clock
#      format, the artwork or the grid inside it.  The throwaway
#      calibration launch is exempt by design -- it captures nothing, and
#      the file it writes is verified before the capture launch that
#      follows it.
#
# SECURITY POSTURE (the parts that live here rather than in env.sh)
#   * A window is accepted only once window -> _NET_WM_PID ->
#     /proc/<pid>/exe resolves to the binary this script verified, and
#     two distinct engines are an error rather than a choice.  env.sh
#     owns the other half: the display is authenticated.
#   * Nothing is signalled on the strength of a pid alone.  Identity is
#     the pair (executable, start time) from /proc, re-checked before
#     SIGTERM and again before SIGKILL, which narrows the recycled-pid
#     window without closing it.
#   * Every number from the environment is validated before arithmetic
#     touches it (validate_tunables), because bash evaluates command
#     substitution inside arithmetic expansion.
#   * Logs, the build sentinel and pid files are created through env.sh's
#     checked helpers inside its private 0700 runtime root, so a symlink
#     at a predictable path is refused rather than written through.
#   * A tileset pack is ingested only after its ownership, its absence of
#     links and special files, and a sha256 manifest all check out.
#   * flock holds the concurrency: a build lock spans the
#     check-and-start of make, a session lock the save probe and the
#     engine start.
#
# PROCESS OWNERSHIP.  Nothing here reuses a window, or signals a pid,
# that it has not bound to THIS checkout -- same executable inode, this
# repository root as the working directory, exactly this `--userdir` in a
# NUL-delimited argv, and this DISPLAY.  A window of the right class that
# fails any of those belongs to another clone and is left alone.
#
# Every line on stdout is `KEY=value` and nothing else, because
# seed_options.py reads PLAYTHROUGH_TILESET_RESOLVED and session.py reads
# PLAYTHROUGH_WINDOW_ID, PLAYTHROUGH_SESSION_MODE and
# PLAYTHROUGH_INITIAL_UI_STATE with `grep '^KEY='`; logging and
# diagnostics go to stderr.  `launch_game.sh help` is the single
# definition of the subcommand list; the EX_* constants are the exit
# codes; each numeric tunable is range-checked by name in
# validate_tunables() before any subcommand acts on it, and the two path
# tunables must resolve inside $PLAYTHROUGH_RUNTIME_DIR because this
# script truncates and writes them.
#
# `launch` detaches the game so it survives this shell -- but not the
# container, nor a platform that reaps a whole process tree -- and
# nothing here restarts it.  `guard` is the subcommand for a caller that
# needs one process to own the instance for its lifetime.
# ---------------------------------------------------------------------

set -euo pipefail

# errtrace makes the ERR trap below fire inside functions too, which is
# what turns an unexpected failure into a reported line number instead
# of silence.  It is a strict addition to `set -euo pipefail` above,
# never a replacement for it.
set -o errtrace

# The handler is a function so that the trap string stays trivial; a
# multi-line single-quoted trap body would embed a literal backslash
# rather than continuing the line.
_lg_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "launch_game.sh failed at line ${2} (exit ${1})" >&2
}
trap '_lg_on_error "$?" "${LINENO}"' ERR

# ---------------------------------------------------------------------
# Locate this file, then the repository root, then load the one definition of
# the environment.
# ---------------------------------------------------------------------
_lg_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_lg_script_dir}" ]; then
    printf '%s\n' "launch_game.sh: FATAL: cannot resolve my own \
directory" >&2
    exit 2
fi

_lg_env_file="${_lg_script_dir}/env.sh"
if [ ! -f "${_lg_env_file}" ]; then
    printf '%s\n' "launch_game.sh: FATAL: missing \
${_lg_env_file}; the environment contract is defined there and is \
never redefined here" >&2
    exit 8
fi

# env.sh is the SINGLE definition of the headless contract -- DISPLAY,
# SDL_VIDEODRIVER (x11; the dummy video backend is banned), the audio and
# GL variables, XDG_RUNTIME_DIR at mode 0700 -- and of every artifact path
# and playthrough_* helper.  None of it is restated here.
#
# The `source=` directive lets `shellcheck -x` follow env.sh and
# type-check every helper used here.  SC1091 is suppressed only for a
# plain `shellcheck` run, which cannot follow a sourced file at all; the
# file's presence is asserted above.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_lg_env_file}"; then
    printf '%s\n' "launch_game.sh: FATAL: ${_lg_env_file} refused to \
load; fix the environment contract before launching anything" >&2
    exit 8
fi
unset _lg_script_dir _lg_env_file

# ---------------------------------------------------------------------
# WORKING DIRECTORY: the repository root, and nowhere else.
# ---------------------------------------------------------------------
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# Exit codes, named so that the call sites read as intent.  These are
# the script's documented contract; a caller may branch on them.
# ---------------------------------------------------------------------
readonly EX_OK=0
# Bad subcommand, or a tunable that is non-numeric, out of range, or names a
# scratch path outside the verified runtime directory -- or a trust bypass that
# an instance being captured may not run under (assert_capture_preconditions).
readonly EX_USAGE=1
# Not being run from inside a Cataclysm-DDA checkout, or the calibration
# launch produced no readable options.json.
readonly EX_LAYOUT=2
# The build failed, or did not finish inside its timeout.
readonly EX_BUILD=3
# The binary is not the SDL tiles build (no "+tiles"), or its --version
# probe had to be killed on a timeout.
readonly EX_NOT_TILES=4
# No usable X display at the contracted geometry.
readonly EX_DISPLAY=5
# The REQUIRED tileset is not installed and could not be hydrated from
# the pre-placed pack.
readonly EX_TILESET=6
# The game window never appeared, an instance could not be confirmed
# stopped, or two instances share one userdir.
readonly EX_WINDOW=7
# A prerequisite is missing: env.sh, make, a compiler, or a tool.
readonly EX_PREREQ=8
# A recorded session is in progress, so the requested action would end it
# outside the in-game Save & Quit. Distinct from EX_USAGE because nothing about
# the invocation was wrong: the state of the run is what refuses it.
readonly EX_RECORDED=9
# A save tree exists but MUST NOT be continued -- the append-only record shows
# its survivor died and the engine's own death cleanup never ran, so the
# character file is still live-shaped for somebody who is dead in the record.
readonly EX_NOT_RESUMABLE=10

# ---------------------------------------------------------------------
# Tunables.
# ---------------------------------------------------------------------

# The build contract: the sanctioned compiler, the major version its
# name has to carry, and the job cap this host's memory allows.
readonly SANCTIONED_COMPILER="g++-14"
readonly REQUIRED_COMPILER_MAJOR=14
readonly MAX_BUILD_JOBS=3

# Quarter-second ticks to wait for a process to disappear after SIGKILL before
# reporting it as still alive.
readonly SIGKILL_CONFIRM_TICKS=20

# The raw values, exactly as the environment gave them. Nothing below uses them
# until validate_tunables() -- called first from main(), once die() and every
# helper exist -- has checked and normalised each one in place.
BUILD_JOBS="${PLAYTHROUGH_BUILD_JOBS:-3}"
BUILD_TIMEOUT="${PLAYTHROUGH_BUILD_TIMEOUT:-5400}"
BUILD_LOG="${PLAYTHROUGH_BUILD_LOG:-\
${PLAYTHROUGH_LOG_DIR}/cata-build.log}"
# Deliberately NOT derived from BUILD_LOG: the log may be redirected by
# a caller, while these two are the build's CONTROL STATE -- the exit
# status a later run believes and the pid it waits on -- and they belong
# inside the verified runtime root either way.
BUILD_STATUS="${PLAYTHROUGH_RUN_DIR}/build.status"
BUILD_PIDFILE="${PLAYTHROUGH_RUN_DIR}/build.pid"
# The $0 given to the detached build's inner shell.  It is how a later
# run recognises a build of its own still in flight, so it can wait for
# that one instead of racing a second make against the same tree.
readonly BUILD_TAG="launch_game_build"
# The --version probe's own bound.
VERSION_TIMEOUT="${PLAYTHROUGH_VERSION_TIMEOUT-30}"
WINDOW_TIMEOUT="${PLAYTHROUGH_WINDOW_TIMEOUT-180}"
STOP_TIMEOUT="${PLAYTHROUGH_STOP_TIMEOUT-30}"
LIVENESS_SETTLE="${PLAYTHROUGH_LIVENESS_SETTLE-2}"
TILESET_PACK="${PLAYTHROUGH_TILESET_PACK:-/opt/cdda-gfx-cache}"
PIDFILE="${PLAYTHROUGH_GAME_PIDFILE:-\
${PLAYTHROUGH_RUN_DIR}/cata-play.pid}"
# The real path of PLAYTHROUGH_RUNTIME_DIR, resolved once by
# validate_tunables so every confinement comparison uses one string.
RUNTIME_REAL=""
# ---------------------------------------------------------------------
# Results. Functions here set globals rather than echoing values, because a `$(
# ... )` capture runs in a subshell where `exit` from the die() below would
# exit only that subshell and be swallowed.
# ---------------------------------------------------------------------
COMPILER_BIN=""
COMPILER_MAJOR=""
BUILD_RUNNING_PID=""
GAME_VERSION=""
GAME_VERSION_ALL=""
TILESET_LINKS_SKIPPED=0
TILESET_ID=""
TILESET_VIEW=""
TILESET_DIR=""
TILESET_ORIGIN=""
TILESET_NAMES=()
TILESET_VIEWS=()
TILESET_DIRS=()
SESSION_MODE=""
# The Python half of the contract: the Pillow release the resolved
# interpreter carries, and ocr_clock.py's own verdict on whether that
# interpreter can read a clock at all.  See read_interpreter_facts().
INTERPRETER_PILLOW=""
INTERPRETER_PREFLIGHT=""
SAVE_WORLD=""
SAVE_WORLD_COUNT=0
# The UI state a captured session must start from, and it is DECLARED here and
# VERIFIED below rather than assumed.
INITIAL_UI_STATE=""
SAVE_CHAR_COUNT=0
# Which canonical character-file form(s) the save tree holds: ".sav",
# ".sav.zzip", both, or empty when there is no character file at all.
SAVE_CHAR_FORMS=""
# The (executable, start time) pair of the instance this run is working
# with.  Every signal is checked against it first; see the PROCESS
# IDENTITY PRIMITIVES section.
GAME_IDENTITY=""
WINDOW_ID=""
WINDOW_GEOMETRY=""
WINDOW_WIDTH=""
WINDOW_HEIGHT=""
# The offsets, kept beside the size because the capture contract names
# all four and a geometry check that reads only two is not a check of the
# geometry.
WINDOW_X=""
WINDOW_Y=""
GAME_PID=""
# The pid find_game_window verified for the window it chose, declared
# here with the other results and set only by that function.
WINDOW_OWNED_PID=""
FOREIGN_WINDOWS_WARNED=0
LAUNCH_PHASE=""
FIRST_RUN=0
PROBE_DONE=0
HEADLESS_DONE=0

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

# emit KEY VALUE -- the machine-readable channel, and the only thing this
# script ever writes to stdout.
emit() {
    if playthrough_has_control "$2"; then
        die "${EX_LAYOUT}" "the value for $1 carries a control" \
            "character, so writing it would forge or corrupt a line" \
            "of the machine-readable record.  With every control byte" \
            "shown as <NN> it is:" \
            "$(playthrough_escape_controls "$2")"
    fi
    if [ "${#2}" -gt "${PLAYTHROUGH_MAX_RECORD_TOKEN}" ]; then
        die "${EX_LAYOUT}" "the value for $1 is ${#2} characters," \
            "past the ${PLAYTHROUGH_MAX_RECORD_TOKEN}-character" \
            "ceiling for one line of the machine-readable record"
    fi
    printf '%s=%s\n' "$1" "$2"
}

# tail_log PATH [LINES] -- show the end of a log on stderr before
# dying, so a failure carries its own evidence instead of asking the
# operator to go hunting for it.
tail_log() {
    local path="$1"
    local lines="${2:-40}"
    if [ ! -f "${path}" ]; then
        playthrough_warn "no log at ${path} to report"
        return 0
    fi
    playthrough_log "--- last ${lines} lines of ${path} ---"
    tail -n "${lines}" "${path}" >&2 || true
    playthrough_log "--- end of ${path} ---"
}

# ---------------------------------------------------------------------
# TUNABLE VALIDATION.
# Every tunable arrives as a string and is then used in arithmetic, as a
# `sleep` operand, as `make -j`'s argument, or as a path this script TRUNCATES.
# None of those fails cleanly on a bad value:
#
#   * `[ "${waited}" -ge "${ticks}" ]` with a non-numeric operand exits 2,
#     which is non-zero, so a bounded wait can lose its bound;
#   * `$(( timeout * 4 ))` on a non-numeric value yields 0, turning a
#     bounded poll into one that gives up on the first tick;
#   * `make -jabc`, `-j0` and `-j-1` all fail inside a detached build that
#     nobody is watching;
#   * a value carrying `$(...)` or backticks would be EVALUATED by
#     arithmetic expansion, which makes shape validation a security
#     property and not only a robustness one;
#   * a scratch path in world-writable /tmp is how a symlink redirects a
#     truncating write, so every one is confined to env.sh's verified
#     mode-0700 runtime directory.
#
# So a bad value is refused at startup with the name, the value and the
# accepted range rather than coerced.  Integer results are written back into
# the same globals, normalised to plain decimal; a path result comes back in
# a global rather than on stdout, because a `$( ... )` capture runs in a
# subshell where die()'s `exit` would end only that subshell.
#
# AN EXPLICITLY EMPTY VALUE IS THE ONE DELIBERATE EXCEPTION: the assignments
# use `${VAR:-default}`, so `VAR=` means the documented default.  env.sh
# judges CLONE_INDEX differently because an empty one coerced to 0 would
# route a clone onto another clone's display, whereas an empty job count
# collides with nothing.
# ---------------------------------------------------------------------

VALIDATED_PATH=""

# require_positive_int NAME VALUE MIN MAX -- a plain decimal integer in range,
# or die. No sign, no whitespace, no leading plus, nothing an arithmetic
# context could interpret as anything but a number.
require_positive_int() {
    local name="$1"
    local value="$2"
    local min="$3"
    local max="$4"
    case "${value}" in
        ''|*[!0-9]*)
            die "${EX_USAGE}" "${name}='${value}' is not a plain" \
                "decimal integer; it is used in arithmetic and as a" \
                "bound, where a non-numeric value evaluates to zero" \
                "and turns a bounded wait into an immediate timeout" \
                "that reports the wrong cause.  Give a whole number" \
                "between ${min} and ${max} with no sign and no unit" \
                "suffix."
            ;;
    esac
    # 10#: a value like 08 is decimal here, not a rejected octal
    # literal.  The shape check above has already guaranteed digits.
    if [ "$(( 10#${value} ))" -lt "${min}" ] ||
        [ "$(( 10#${value} ))" -gt "${max}" ]; then
        die "${EX_USAGE}" "${name}=${value} is out of range; it must" \
            "be between ${min} and ${max}"
    fi
    return 0
}

# require_positive_number NAME VALUE MAX -- a positive decimal, whole or
# fractional, in range.
require_positive_number() {
    local name="$1"
    local value="$2"
    local max="$3"
    case "${value}" in
        ''|*[!0-9.]*|.|*.*.*)
            die "${EX_USAGE}" "${name}='${value}' is not a plain" \
                "positive decimal number; it is passed to sleep and" \
                "used as a bound, so it must look like 2 or 0.5 and" \
                "must not exceed ${max}"
            ;;
    esac
    # Compare without bc: split on the decimal point and compare the
    # whole part, which is all the range check needs.
    local whole="${value%%.*}"
    whole="${whole:-0}"
    if [ "$(( 10#${whole} ))" -gt "${max}" ]; then
        die "${EX_USAGE}" "${name}=${value} is out of range; it must" \
            "not exceed ${max}"
    fi
    # Reject a value that is zero however it was spelled: 0, 0.0, .0
    # all mean "do not wait at all", which defeats every settle and
    # every bounded poll built on it.
    case "${value}" in
        0|0.|0.0|0.00|.0|.00|00)
            die "${EX_USAGE}" "${name}=${value} is zero; a zero" \
                "settle or timeout defeats the bounded waits built" \
                "on it.  Use the smallest value you actually want."
            ;;
    esac
    return 0
}

# validate_scratch_path NAME VALUE -- sets VALIDATED_PATH.
validate_scratch_path() {
    local name="$1"
    local value="$2"
    local dir base resolved
    if [ -z "${value}" ]; then
        die "${EX_USAGE}" "${name} is empty; scratch state belongs in" \
            "${PLAYTHROUGH_RUNTIME_DIR}"
    fi
    dir="$(dirname -- "${value}")"
    base="$(basename -- "${value}")"
    case "${base}" in
        ''|'.'|'..'|*/*)
            die "${EX_USAGE}" "${name}='${value}' does not name a" \
                "file"
            ;;
    esac
    # The `if` form rather than `cd && pwd || true`: an unreadable
    # directory must leave `resolved` empty and be reported below, not
    # abort the script through errexit with no message at all.
    resolved="$(
        if cd "${dir}" >/dev/null 2>&1; then
            pwd -P
        fi
    )"
    if [ -z "${resolved}" ]; then
        die "${EX_USAGE}" "${name}='${value}' is inside a directory" \
            "that does not exist; scratch state belongs in" \
            "${PLAYTHROUGH_RUNTIME_DIR}"
    fi
    # AT OR BELOW the runtime root, not a direct child of it.
    case "${resolved}" in
        "${RUNTIME_REAL}"|"${RUNTIME_REAL}/"*) ;;
        *)
            die "${EX_USAGE}" "${name}='${value}' resolves into" \
                "'${resolved}', outside the verified mode-0700" \
                "runtime directory '${RUNTIME_REAL}'.  This script" \
                "truncates and writes that file, so it will not" \
                "follow a path it cannot vouch for.  Keep it in the" \
                "runtime directory, or move the whole directory with" \
                "CLONE_INDEX."
            ;;
    esac
    VALIDATED_PATH="${resolved}/${base}"
    return 0
}

# validate_tunables -- run every check, in one place, before any subcommand
# does anything.
validate_tunables() {
    RUNTIME_REAL="$(
        if cd "${PLAYTHROUGH_RUNTIME_DIR}" >/dev/null 2>&1; then
            pwd -P
        fi
    )"
    if [ -z "${RUNTIME_REAL}" ]; then
        die "${EX_LAYOUT}" "PLAYTHROUGH_RUNTIME_DIR" \
            "'${PLAYTHROUGH_RUNTIME_DIR}' is not a directory." \
            "env.sh creates and verifies it at mode 0700, so" \
            "re-source playthrough/tooling/env.sh."
    fi

    require_positive_int PLAYTHROUGH_BUILD_JOBS "${BUILD_JOBS}" 1 1024
    BUILD_JOBS=$(( 10#${BUILD_JOBS} ))
    require_positive_int PLAYTHROUGH_BUILD_TIMEOUT \
        "${BUILD_TIMEOUT}" 1 86400
    BUILD_TIMEOUT=$(( 10#${BUILD_TIMEOUT} ))
    require_positive_int PLAYTHROUGH_VERSION_TIMEOUT \
        "${VERSION_TIMEOUT}" 1 600
    VERSION_TIMEOUT=$(( 10#${VERSION_TIMEOUT} ))
    require_positive_int PLAYTHROUGH_WINDOW_TIMEOUT \
        "${WINDOW_TIMEOUT}" 1 3600
    WINDOW_TIMEOUT=$(( 10#${WINDOW_TIMEOUT} ))
    require_positive_int PLAYTHROUGH_STOP_TIMEOUT \
        "${STOP_TIMEOUT}" 1 3600
    STOP_TIMEOUT=$(( 10#${STOP_TIMEOUT} ))
    # A fraction is legitimate here and nowhere else: this value is a
    # `sleep` operand, and 0.5 is a reasonable settle.
    require_positive_number PLAYTHROUGH_LIVENESS_SETTLE \
        "${LIVENESS_SETTLE}" 3600

    validate_scratch_path PLAYTHROUGH_BUILD_LOG "${BUILD_LOG}"
    BUILD_LOG="${VALIDATED_PATH}"
    # NOT re-derived from BUILD_LOG.  The log may be redirected by a
    # caller; the build's control state stays inside the verified
    # runtime root, so each is confined on its own account.
    validate_scratch_path PLAYTHROUGH_RUN_DIR "${BUILD_STATUS}"
    BUILD_STATUS="${VALIDATED_PATH}"
    validate_scratch_path PLAYTHROUGH_RUN_DIR "${BUILD_PIDFILE}"
    BUILD_PIDFILE="${VALIDATED_PATH}"
    validate_scratch_path PLAYTHROUGH_GAME_PIDFILE "${PIDFILE}"
    PIDFILE="${VALIDATED_PATH}"

    clamp_build_jobs
    return 0
}

# clamp_build_jobs -- hold make's parallelism to MAX_BUILD_JOBS.
clamp_build_jobs() {
    if [ "$(( 10#${BUILD_JOBS} ))" -le "${MAX_BUILD_JOBS}" ]; then
        return 0
    fi
    playthrough_warn "PLAYTHROUGH_BUILD_JOBS=${BUILD_JOBS} exceeds" \
        "the ${MAX_BUILD_JOBS}-job cap this pipeline builds under" \
        "and is being reduced to ${MAX_BUILD_JOBS}.  The cap is a" \
        "memory limit, not a CPU one: a wider build over this" \
        "object tree is OOM-killed, which surfaces as 'Killed'" \
        "rather than as a compile error and is far harder to read."
    BUILD_JOBS="${MAX_BUILD_JOBS}"
    return 0
}

# wait_for_file PATH TIMEOUT_SECONDS -- bounded poll, never a fixed sleep, so a
# fast host is not penalised and a slow one is not truncated. The timeout is
# validated for the same reason as the tunables above: it reaches arithmetic.
wait_for_file() {
    local path="$1"
    playthrough_validate_int "$2" "wait_for_file timeout" 1 172800 ||
        die "${EX_USAGE}" "wait_for_file was given an unusable timeout"
    local timeout="${PLAYTHROUGH_INT}"
    local ticks=$(( timeout * 4 ))
    local waited=0
    while [ ! -f "${path}" ]; do
        if [ "${waited}" -ge "${ticks}" ]; then
            return 1
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done
    return 0
}

# ---------------------------------------------------------------------
# PROCESS IDENTITY PRIMITIVES
# A pid is not an identity. Pids are recycled, /proc/<pid>/cmdline is argv and
# therefore whatever the process chose to put there, and the window-manager
# path below hands us a pid claimed by an X client.
# ---------------------------------------------------------------------

# proc_exe PID -- the resolved path of the running binary, or nothing.
proc_exe() {
    local pid="${1-}"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    local exe
    exe="$(readlink -f -- "/proc/${pid}/exe" 2>/dev/null || true)"
    [ -n "${exe}" ] || return 1
    printf '%s\n' "${exe}"
}

# proc_start_time PID -- field 22 of /proc/<pid>/stat.
proc_start_time() {
    local pid="${1-}"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    local stat rest value
    stat="$(cat "/proc/${pid}/stat" 2>/dev/null || true)"
    [ -n "${stat}" ] || return 1
    rest="${stat##*') '}"
    [ "${rest}" != "${stat}" ] || return 1
    value="$(printf '%s\n' "${rest}" | awk '{ print $20 }')"
    case "${value}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s\n' "${value}"
}

# proc_identity PID -- "<exe>|<start time>", or nothing when the process
# cannot be identified.  This string is what gets compared; it is opaque
# on purpose so no caller starts interpreting half of it.
proc_identity() {
    local pid="${1-}"
    local exe start
    exe="$(proc_exe "${pid}")" || return 1
    start="$(proc_start_time "${pid}")" || return 1
    printf '%s|%s\n' "${exe}" "${start}"
}

# pid_has_identity PID IDENTITY -- true only when that pid is still the
# very process the identity was taken from.  Called immediately before
# every signal.
pid_has_identity() {
    local pid="${1-}"
    local want="${2-}"
    [ -n "${want}" ] || return 1
    local now
    now="$(proc_identity "${pid}")" || return 1
    [ "${now}" = "${want}" ]
}

# ---------------------------------------------------------------------
# STEP 0 -- prove we really are at the root of a Cataclysm-DDA checkout.
# ---------------------------------------------------------------------
assert_repo_root() {
    local missing=()
    local entry
    # data/ and gfx/ are what the engine resolves relative to the
    # working directory; Makefile is what the build needs;
    # src/path_info.cpp is the file every path claim above cites.
    for entry in data gfx lang src/path_info.cpp Makefile; do
        if [ ! -e "./${entry}" ]; then
            missing+=("${entry}")
        fi
    done
    if [ "${#missing[@]}" -ne 0 ]; then
        die "${EX_LAYOUT}" "'$(pwd)' is not the root of a" \
            "Cataclysm-DDA checkout: missing ${missing[*]}." \
            "The game must be launched from the repository root or" \
            "its own data/, gfx/ and lang/mo/ will not resolve and" \
            "the userdir will not land inside the working tree."
    fi
    return 0
}

# ---------------------------------------------------------------------
# Warn -- loudly, and by name -- if the build left anything that git would
# consider a change outside playthrough/.
# ---------------------------------------------------------------------
warn_if_tree_dirty() {
    if ! command -v git >/dev/null 2>&1; then
        return 0
    fi
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        return 0
    fi
    local line unexpected=()
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        # Porcelain v1 is "XY path"; the path starts at column 4.
        case "${line:3}" in
            playthrough/*) ;;
            *) unexpected+=("${line}") ;;
        esac
    done < <(git status --porcelain 2>/dev/null || true)
    if [ "${#unexpected[@]}" -ne 0 ]; then
        playthrough_warn "git sees changes outside playthrough/;" \
            "this pipeline authors nothing there, so review them:"
        for line in "${unexpected[@]}"; do
            playthrough_warn "  ${line}"
        done
    fi
    return 0
}

# ---------------------------------------------------------------------
# STEP 1 -- the binary.
# ---------------------------------------------------------------------

# compiler_major BIN -- the major version the compiler reports about itself, or
# the empty string.
compiler_major() {
    local bin="$1"
    local reported
    reported="$("${bin}" -dumpversion 2>/dev/null || true)"
    reported="${reported%%.*}"
    case "${reported}" in
        ''|*[!0-9]*) printf '%s' "" ;;
        *) printf '%s' "${reported}" ;;
    esac
}

# resolve_compiler -- resolve the C++ compiler and prove BOTH of the
# things that have to be true about something this script runs over the
# whole source tree: that it is the SANCTIONED version, because the
# Makefile builds with -Werror and a newer compiler's new warnings are
# build failures, and that the binary itself is trustworthy.  The two are
# independent questions and each is asked separately.
resolve_compiler() {
    local candidate="" major="" var=""
    if [ -n "${PLAYTHROUGH_COMPILER:-}" ]; then
        if ! playthrough_resolve_tool "${PLAYTHROUGH_COMPILER}"; then
            playthrough_warn "PLAYTHROUGH_COMPILER" \
                "'${PLAYTHROUGH_COMPILER}' is not on PATH, or was" \
                "rejected as untrustworthy (see above)"
            return 1
        fi
        var="$(playthrough_tool_var "${PLAYTHROUGH_COMPILER}")"
        candidate="${!var}"
    elif playthrough_resolve_tool "${SANCTIONED_COMPILER}"; then
        var="$(playthrough_tool_var "${SANCTIONED_COMPILER}")"
        candidate="${!var}"
    else
        playthrough_warn "${SANCTIONED_COMPILER} is not on PATH, or" \
            "was rejected as untrustworthy (see above)." \
            "It is the compiler this tree is known to build clean" \
            "under, and an unversioned g++ is NOT accepted in its" \
            "place: this host's g++ is a newer GCC whose extra" \
            "-Werror diagnostics fail in engine source that this" \
            "pipeline must not edit.  Install it with:" \
            "apt-get install -y g++-14"
        return 1
    fi

    major="$(compiler_major "${candidate}")"
    if [ -z "${major}" ]; then
        playthrough_warn "'${candidate}' did not report a usable" \
            "version from -dumpversion, so it cannot be verified as" \
            "the sanctioned compiler"
        if [ "${PLAYTHROUGH_ALLOW_ANY_COMPILER:-0}" != "1" ]; then
            return 1
        fi
    elif [ "${major}" -ne "${REQUIRED_COMPILER_MAJOR}" ]; then
        if [ "${PLAYTHROUGH_ALLOW_ANY_COMPILER:-0}" != "1" ]; then
            playthrough_warn "'${candidate}' is major version" \
                "${major}, but this tree builds clean under" \
                "${REQUIRED_COMPILER_MAJOR} and is compiled with" \
                "-Werror.  Refusing rather than spending a" \
                "25-minute build to fail in engine source that" \
                "must not be edited.  Install ${SANCTIONED_COMPILER}" \
                "(apt-get install -y g++-14), or set" \
                "PLAYTHROUGH_ALLOW_ANY_COMPILER=1 if you have" \
                "verified this compiler builds this tree."
            return 1
        fi
        playthrough_warn "proceeding with '${candidate}' (major" \
            "${major}) instead of ${REQUIRED_COMPILER_MAJOR} because" \
            "PLAYTHROUGH_ALLOW_ANY_COMPILER=1; a -Werror failure in" \
            "engine source is the expected outcome if it is not" \
            "actually supported"
    fi

    COMPILER_BIN="${candidate}"
    COMPILER_MAJOR="${major}"
    return 0
}

# build_binary -- run the one sanctioned build command, detached.

# THE FLAGS, AND WHY EACH ONE IS LOAD-BEARING
#
#   SDL3=0     MANDATORY on every make invocation here.  Makefile:791-795
#              defaults SDL3=1 whenever TILES=1 and Makefile:811-816 then
#              raises a hard `$(error SDL3 >= 3.4.0 required ...)` when
#              pkg-config cannot satisfy it, so without SDL3=0 the build
#              ABORTS rather than degrading.  The SDL2 fallback is the
#              project's own documented one (doc/c++/COMPILING.md:83, :232).
#   RELEASE=1  Optimised build (Makefile:33).
#   TILES=1    The SDL tiles build (Makefile:35).  The curses build must
#              never be substituted.
#   SOUND=1    Requires TILES (Makefile:37); muted at run time by
#              SDL_AUDIODRIVER=dummy and SOUND_ENABLED=false.
#   ASTYLE=0   Skip the source restyle (Makefile:88); no C++ is touched.
#   LINTJSON=0 Skip the JSON format check (Makefile:90); no JSON either.
#   CCACHE=1   Reuse the compilation cache (Makefile:408-414).
#   -j<n>      NOT -j$(nproc).  The job count is PLAYTHROUGH_BUILD_JOBS
#              validated and then capped by MAX_BUILD_JOBS, because a build
#              wider than the host's memory can carry is OOM-killed rather
#              than merely slow.  The environment can lower it; only
#              MAX_BUILD_JOBS raises the ceiling.
#   COMPILER=  Makefile:400-410 sets OS_COMPILER := $(COMPILER) when it is
#              non-empty and reassigns CXX from it, so naming both cannot
#              produce two different compilers.
#
# FLAGS THAT MUST NEVER BE PASSED -- the mentions here are comments
# explaining a prohibition, never arguments:
#
#   TESTS=0          Explicitly forbidden (Makefile:91-92); the test binary
#                    stays part of the build.
#   NATIVE=linux64   Must not be passed on ARM64 hosts.
#   USE_XDG_DIR=1    Fatal, for a source-level reason:
#                    src/path_info.cpp:152-166 makes this the one flag that
#                    moves config/ out of the userdir to
#                    $XDG_CONFIG_HOME/cataclysm-dda/, so options.json and
#                    keybindings.json would never land under
#                    playthrough/userdir/config/ and option seeding would
#                    silently break.
#   USE_HOME_DIR=1   Fatal for a DIFFERENT reason: it selects the DEFAULT
#                    user directory (src/main.cpp:684 calls
#                    `init_user_dir( "" )`, resolving to
#                    $HOME/.cataclysm-dda/, src/path_info.cpp:99-102).  This
#                    pipeline always passes `--userdir` explicitly so the
#                    default is never consulted, which is exactly why the
#                    flag is refused rather than tolerated: such a build is
#                    one forgotten --userdir away from writing the save
#                    outside the working tree.  Makefile:1211-1222 also
#                    makes the two flags mutually exclusive.
#
# No file under src/ is edited to make this build succeed.  The one C++
# change the SDL2 path is known to need -- the get_shared_variant_pass guard
# -- is already applied at both construction sites,
# src/pixel_minimap.cpp:283-287 and :475-479.
#
# build_in_progress -- true when a make THIS script started is still running
# over this object tree.
build_in_progress() {
    BUILD_RUNNING_PID=""
    [ -f "${BUILD_PIDFILE}" ] || return 1
    local record pid want
    record="$(head -n 1 "${BUILD_PIDFILE}" 2>/dev/null || true)"
    pid="${record%% *}"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    # The recorded start time, when the file carries one.  A pidfile from
    # an older run without it still works: the exe and cwd checks below
    # remain, and the next build rewrites the file in the current form.
    want=""
    if [ "${record}" != "${pid}" ]; then
        want="${record#* }"
        case "${want}" in
            ''|*[!0-9]*) want="" ;;
        esac
    fi
    local exe start
    exe="$(proc_exe "${pid}")" || return 1
    case "${exe##*/}" in
        make|*make) ;;
        *) return 1 ;;
    esac
    if [ -n "${want}" ]; then
        start="$(proc_start_time "${pid}")" || return 1
        if [ "${start}" != "${want}" ]; then
            playthrough_warn "pid ${pid} in ${BUILD_PIDFILE} has been" \
                "recycled (start time ${start}, recorded" \
                "${want}); it is NOT this pipeline's build"
            return 1
        fi
    fi
    local cwd
    cwd="$(readlink -f -- "/proc/${pid}/cwd" 2>/dev/null || true)"
    if [ "${cwd}" != "${PLAYTHROUGH_REPO_ROOT}" ]; then
        return 1
    fi
    BUILD_RUNNING_PID="${pid}"
    return 0
}

# assert_build_capabilities -- prove the LIBRARIES are there, not just the
# commands.
assert_build_capabilities() {
    playthrough_require_tools pkg-config ||
        die "${EX_PREREQ}" "pkg-config is what the Makefile asks the" \
            "host about SDL and FreeType with, so a build cannot even" \
            "be configured without it."
    local -a missing=()
    local module package
    # One pkg-config module per line, with the Debian/Ubuntu package
    # that provides its .pc file.
    while read -r module package; do
        [ -n "${module}" ] || continue
        if ! "${PLAYTHROUGH_BIN_PKG_CONFIG}" --exists "${module}" \
                >/dev/null 2>&1; then
            missing+=("${module} (apt: ${package})")
        fi
    done <<'MODULES'
sdl2 libsdl2-dev
SDL2_ttf libsdl2-ttf-dev
SDL2_image libsdl2-image-dev
SDL2_mixer libsdl2-mixer-dev
freetype2 libfreetype-dev
zlib zlib1g-dev
ncursesw libncurses-dev
MODULES
    if ! command -v msgfmt >/dev/null 2>&1; then
        missing+=("msgfmt (apt: gettext)")
    fi
    if [ "${#missing[@]}" -ne 0 ]; then
        die "${EX_PREREQ}" "the build cannot start: this host has the" \
            "build COMMANDS but not the development libraries the" \
            "tiles build links against.  Missing: ${missing[*]}." \
            "The complete, separated inventories -- host build," \
            "capture runtime and the supported container -- are in" \
            "playthrough/tooling/requirements.txt.  Nothing has been" \
            "changed."
    fi
    playthrough_log "build capabilities present: sdl2" \
        "$("${PLAYTHROUGH_BIN_PKG_CONFIG}" --modversion sdl2 \
            2>/dev/null || printf 'unknown'), SDL2_ttf, SDL2_image," \
        "SDL2_mixer, freetype2" \
        "$("${PLAYTHROUGH_BIN_PKG_CONFIG}" --modversion freetype2 \
            2>/dev/null || printf 'unknown'), zlib, ncursesw and" \
        "msgfmt"
    return 0
}

build_binary() {
    # PREFLIGHT EVERY EXTERNAL COMMAND FIRST, before a log is truncated, a
    # pidfile is removed or a child is spawned.
    playthrough_require_tools make ccache setsid nohup tr readlink \
        tail head ||
        die "${EX_PREREQ}" "the build cannot start: the tools above" \
            "are missing.  Install them and retry; nothing has been" \
            "changed."
    assert_build_capabilities
    resolve_compiler ||
        die "${EX_PREREQ}" "no usable C++ compiler: this tree builds" \
            "with ${SANCTIONED_COMPILER} (major" \
            "${REQUIRED_COMPILER_MAJOR}).  Install it with" \
            "'apt-get install -y g++-14', or point" \
            "PLAYTHROUGH_COMPILER at an equivalent GCC 14."

    # THE BUILD LOCK spans the check AND the start, which is the whole point:
    # "no build is running, so start one" is two operations, and two
    # invocations that interleave between them put two makes on one object tree
    # -- where they fight over the same .o files and, on a host sized for three
    # compilers, exhaust its memory.
    playthrough_acquire_lock build "${BUILD_TIMEOUT}" ||
        die "${EX_BUILD}" "could not take the build lock; another" \
            "build over this checkout is still running"

    if build_in_progress; then
        playthrough_log "a build started by this script is still" \
            "running (pid ${BUILD_RUNNING_PID}); waiting for that" \
            "one rather than racing a second make over the same" \
            "object tree.  Log: ${BUILD_LOG}"
    else
        playthrough_log "building ./cataclysm-tiles with" \
            "${COMPILER_BIN} (major ${COMPILER_MAJOR:-unverified})," \
            "-j${BUILD_JOBS}, SDL2 fallback" \
            "(SDL3=0); log: ${BUILD_LOG}"
        playthrough_log "a cold build takes roughly 25 minutes on" \
            "this class of host; progress is reported every 30s"

        # The sentinel, the pid file and the log are created through env.sh's
        # checked helpers rather than by `rm -f` plus `>`: all three names are
        # predictable, the log's is caller-supplied, and a symlink at any of
        # them would otherwise be followed -- writing this build's output over
        # whatever it pointed at.
        playthrough_secure_file "${BUILD_STATUS}" ||
            die "${EX_BUILD}" "cannot prepare ${BUILD_STATUS}"
        playthrough_secure_truncate "${BUILD_PIDFILE}" ||
            die "${EX_BUILD}" "cannot prepare ${BUILD_PIDFILE}"
        playthrough_secure_truncate "${BUILD_LOG}" ||
            die "${EX_BUILD}" "cannot prepare ${BUILD_LOG}"
        # The sentinel is validated and then REMOVED, because its existence is
        # the signal the wait loop below watches for.
        rm -f -- "${BUILD_STATUS}"

        # Detached with setsid so the build escapes the caller's process group
        # and controlling terminal, and is not killed when that group is
        # signalled -- a make run here has been terminated by Interrupt for
        # exactly that reason.
        playthrough_child_close_fd ||
            die "${EX_BUILD}" "cannot prepare to detach the build"
        # shellcheck disable=SC2016
        setsid nohup bash -c '
            status_file="$1"
            pid_file="$2"
            shift 2
            "$@" &
            child=$!
            start=""
            if read -r -a stat_fields \
                    <"/proc/${child}/stat" 2>/dev/null; then
                start="${stat_fields[21]-}"
            fi
            case "${start}" in
                ""|*[!0-9]*) start="" ;;
            esac
            printf "%s %s\n" "${child}" "${start}" >"${pid_file}"
            wait "${child}"
            printf "%s\n" "$?" >"${status_file}"
        ' "${BUILD_TAG}" "${BUILD_STATUS}" "${BUILD_PIDFILE}" \
            env "CXX=${COMPILER_BIN}" make "-j${BUILD_JOBS}" \
            RELEASE=1 TILES=1 SOUND=1 SDL3=0 ASTYLE=0 LINTJSON=0 \
            CCACHE=1 "COMPILER=${COMPILER_BIN}" \
            >>"${BUILD_LOG}" 2>&1 </dev/null \
            {PLAYTHROUGH_CHILD_CLOSE_FD}>&- \
            {PLAYTHROUGH_CHILD_CLOSE_FD2}>&- &
        # disown completes the AAP's detachment idiom (`setsid nohup ... <
        # /dev/null & disown`): it drops the job from this shell's job table so
        # that the shell exiting cannot deliver SIGHUP to it.
        disown || true
        playthrough_child_close_done

        # PROVE the build actually started rather than assuming the spawn
        # worked.
        if ! wait_for_file "${BUILD_PIDFILE}" 30; then
            if [ -f "${BUILD_STATUS}" ]; then
                playthrough_log "the build finished before it" \
                    "recorded a pid, which means it failed" \
                    "immediately; its status is reported below"
            else
                tail_log "${BUILD_LOG}"
                die "${EX_BUILD}" "the build was spawned but" \
                    "recorded no pid within 30s and produced no" \
                    "exit status, so it never really started." \
                    "Its log is ${BUILD_LOG}."
            fi
        fi
    fi

    local waited=0
    local interval=5
    local last=""
    while [ ! -f "${BUILD_STATUS}" ]; do
        if [ "${waited}" -ge "${BUILD_TIMEOUT}" ]; then
            tail_log "${BUILD_LOG}"
            die "${EX_BUILD}" "the build did not finish within" \
                "${BUILD_TIMEOUT}s.  Raise" \
                "PLAYTHROUGH_BUILD_TIMEOUT if the host is simply" \
                "slow, or lower PLAYTHROUGH_BUILD_JOBS if it ran" \
                "out of memory."
        fi
        sleep "${interval}"
        waited=$(( waited + interval ))
        if [ $(( waited % 30 )) -eq 0 ]; then
            last="$(tail -n 1 "${BUILD_LOG}" 2>/dev/null || true)"
            playthrough_log "build running, ${waited}s elapsed |" \
                "${last}"
        fi
    done

    local status
    status="$(cat "${BUILD_STATUS}" 2>/dev/null || true)"
    case "${status}" in
        ''|*[!0-9]*)
            tail_log "${BUILD_LOG}"
            die "${EX_BUILD}" "the build wrote an unreadable exit" \
                "status ('${status}') to ${BUILD_STATUS}"
            ;;
    esac
    if [ "${status}" -ne 0 ]; then
        tail_log "${BUILD_LOG}"
        die "${EX_BUILD}" "make exited ${status} after" \
            "${waited}s; see ${BUILD_LOG}"
    fi
    playthrough_log "build finished in ${waited}s"
    # Clear the sentinels only on success.  After a timeout they are
    # left in place on purpose, so that the next run recognises the
    # still-running build and waits for it.
    rm -f -- "${BUILD_STATUS}" "${BUILD_PIDFILE}"
    warn_if_tree_dirty
    return 0
}

# read_game_version -- ask the binary what it is.
GAME_VERSION_RC=0
read_game_version() {
    GAME_VERSION=""
    GAME_VERSION_ALL=""
    GAME_VERSION_RC=0
    [ -x "${PLAYTHROUGH_GAME_BIN}" ] || return 1
    local raw
    if raw="$(
            timeout -- "${VERSION_TIMEOUT}" \
                "${PLAYTHROUGH_GAME_BIN}" --version 2>&1
         )"; then
        GAME_VERSION_RC=0
    else
        GAME_VERSION_RC=$?
    fi
    GAME_VERSION_ALL="$(printf '%s\n' "${raw}" |
        tr '\n' ' ' |
        sed 's/[[:space:]]\{1,\}/ /g; s/^ //; s/ $//')"
    GAME_VERSION="$(printf '%s' "${GAME_VERSION_ALL}" |
        sed 's/ data dir:.*$//')"
    if [ -z "${GAME_VERSION}" ]; then
        GAME_VERSION="${GAME_VERSION_ALL}"
    fi
    # A timeout is never a successful read, even if the binary managed
    # to print a banner before it stalled: the process had to be killed,
    # so nothing about it can be reported as verified.
    if [ "${GAME_VERSION_RC}" -eq 124 ]; then
        return 1
    fi
    [ -n "${GAME_VERSION_ALL}" ]
}

# game_is_tiles -- true when the binary self-reports the tiles build.
game_is_tiles() {
    case "${GAME_VERSION_ALL}" in
        *'+tiles'*) return 0 ;;
    esac
    return 1
}

# read_interpreter_facts -- describe the PYTHON half of the contract.
read_interpreter_facts() {
    INTERPRETER_PILLOW=""
    INTERPRETER_PREFLIGHT="unknown"
    if [ -z "${PLAYTHROUGH_PYTHON}" ] || [ ! -x "${PLAYTHROUGH_PYTHON}" ]
    then
        INTERPRETER_PREFLIGHT="no-interpreter"
        return 1
    fi
    INTERPRETER_PILLOW="$(
        timeout -- "${VERSION_TIMEOUT}" "${PLAYTHROUGH_PYTHON}" -B -c \
            'import PIL
print(PIL.__version__)' 2>/dev/null
    )" || INTERPRETER_PILLOW=""
    INTERPRETER_PILLOW="${INTERPRETER_PILLOW%%$'\n'*}"
    local ocr="${PLAYTHROUGH_TOOLING_DIR}/ocr_clock.py"
    if [ ! -f "${ocr}" ]; then
        INTERPRETER_PREFLIGHT="no-ocr-module"
        return 1
    fi
    # --preflight imports every dependency and checks the Pillow pin without
    # reading a frame: 0 when the interpreter can do the work, 2 when it
    # cannot.
    local detail rc=0
    detail="$(
        timeout -- "${VERSION_TIMEOUT}" "${PLAYTHROUGH_PYTHON}" -B \
            "${ocr}" --preflight 2>&1
    )" || rc=$?
    if [ "${rc}" -eq 0 ]; then
        INTERPRETER_PREFLIGHT="ok"
        return 0
    fi
    INTERPRETER_PREFLIGHT="failed"
    playthrough_warn "the resolved interpreter" \
        "${PLAYTHROUGH_PYTHON} cannot read a sidebar clock" \
        "(ocr_clock.py --preflight exit ${rc}):" \
        "${detail:-<no diagnosis>}"
    return 1
}

# THIS CHECK IS ABOUT THE BINARY.  THE TILESET IS A SEPARATE, EQUALLY
# MANDATORY REQUIREMENT: a build rendering through the SDL tiles path
# satisfies the tiles-versus-curses rule whatever artwork is selected, which
# is why it cannot stand in for the artwork requirement.  MSXotto+
# (TILES=MshockXottoplus) is required and resolve_tileset() fails closed --
# there is no ASCIITiles path at all, so that function has exactly two
# outcomes.
#
# assert_tiles_binary -- the tiles-versus-curses proof.
assert_tiles_binary() {
    if [ ! -f "${PLAYTHROUGH_GAME_BIN}" ]; then
        die "${EX_PREREQ}" "no binary at ${PLAYTHROUGH_GAME_BIN}" \
            "even after building; expected the Makefile's" \
            "TILESTARGET (Makefile:154,160) at the repository root"
    fi
    if [ ! -x "${PLAYTHROUGH_GAME_BIN}" ]; then
        die "${EX_PREREQ}" "${PLAYTHROUGH_GAME_BIN} is not" \
            "executable"
    fi

    # --version is handled while the command line is still being parsed, before
    # any window is created, so this probe needs no display.
    if ! read_game_version; then
        # A hang and a failure are different faults with different
        # remedies, so they are reported differently rather than as one
        # vague "could not verify".
        if [ "${GAME_VERSION_RC}" -eq 124 ]; then
            die "${EX_NOT_TILES}" "${PLAYTHROUGH_GAME_BIN} --version" \
                "did not answer within ${VERSION_TIMEOUT}s and was" \
                "terminated, so this binary cannot be verified as the" \
                "SDL tiles build.  --version is answered while the" \
                "command line is still being parsed, so a healthy" \
                "binary replies immediately: a stall means the binary" \
                "itself is wrong (a partial or mismatched link, say)." \
                "Rebuild it, or raise PLAYTHROUGH_VERSION_TIMEOUT if" \
                "this host is genuinely that slow."
        fi
        die "${EX_NOT_TILES}" "${PLAYTHROUGH_GAME_BIN} --version" \
            "printed nothing (exit ${GAME_VERSION_RC}); it cannot be" \
            "verified as the SDL tiles build"
    fi
    if ! game_is_tiles; then
        die "${EX_NOT_TILES}" "${PLAYTHROUGH_GAME_BIN}" \
            "reports '${GAME_VERSION}', which does not contain" \
            "'+tiles'.  The SDL tiles build must be played and the" \
            "curses build is never an acceptable substitute." \
            "Rebuild with TILES=1 SOUND=1 SDL3=0."
    fi
    playthrough_log "tiles build confirmed: ${GAME_VERSION}"
    return 0
}

# ensure_binary -- probe, build only if needed, then always verify.
ensure_binary() {
    assert_repo_root
    if [ -x "${PLAYTHROUGH_GAME_BIN}" ]; then
        playthrough_log "reusing the existing binary at" \
            "${PLAYTHROUGH_GAME_BIN}"
    else
        playthrough_log "no binary at ${PLAYTHROUGH_GAME_BIN}" \
            "(.gitignore:75 keeps it out of the repository, so a" \
            "fresh checkout never has one) -- building it"
        build_binary
    fi
    assert_tiles_binary
    emit PLAYTHROUGH_GAME_BIN \
        "$(playthrough_rel "${PLAYTHROUGH_GAME_BIN}")"
    emit PLAYTHROUGH_GAME_VERSION "${GAME_VERSION}"
    return 0
}

# ---------------------------------------------------------------------
# STEP 2 -- the headless surface.
# ---------------------------------------------------------------------
ensure_headless() {
    if [ "${HEADLESS_DONE}" -eq 1 ]; then
        return 0
    fi
    playthrough_require_tools Xvfb openbox xdpyinfo xprop xdotool ||
        die "${EX_PREREQ}" "the headless surface needs Xvfb," \
            "openbox, xdpyinfo, xprop and xdotool; install the" \
            "apt packages listed in" \
            "${PLAYTHROUGH_REQUIREMENTS}"
    if ! playthrough_headless_up; then
        tail_log "${PLAYTHROUGH_XVFB_LOG}" 20
        die "${EX_DISPLAY}" "could not bring up a verified" \
            "${PLAYTHROUGH_SCREEN} X surface on" \
            "${PLAYTHROUGH_DISPLAY}"
    fi
    HEADLESS_DONE=1
    playthrough_log "display ${PLAYTHROUGH_DISPLAY} verified at" \
        "${PLAYTHROUGH_SCREEN}"
    emit PLAYTHROUGH_DISPLAY "${PLAYTHROUGH_DISPLAY}"
    emit PLAYTHROUGH_SCREEN "${PLAYTHROUGH_SCREEN}"
    return 0
}

# ---------------------------------------------------------------------
# STEP 3 -- the tileset. REQUIRED, hydrated if absent, never substituted.
# ---------------------------------------------------------------------

# NO FALLBACK.
#
# The requirement names ONE pack.  Which one, and why it outranks the
# checkout's own artwork, is recorded once as a resolution record in
# playthrough/README.md ("Which artwork the requirement means"); every
# consumer -- this launcher, seed_options, capture.sh and the acceptance
# gate -- enforces that single contract without restating the reasoning.
#
# The losing side is not carried as a switch either: a feature whose
# requirement names one tileset should not ship two artwork branches, and
# failing closed is the safer half, because a run that quietly fell back to
# the checkout's ASCIITiles would still produce a full-length movie of a
# genuine SDL tiles session with every count tallying, the only symptom
# being ASCII art in the finished film.  PLAYTHROUGH_TILESET is therefore a
# DIAGNOSTIC OVERRIDE rather than a production option: naming anything other
# than MSXotto+ leaves the artwork requirement unmet, so it must be stated
# by name, and it is then validated as strictly as the required pack.
#
# A tileset's identity comes from the NAME: field of its tileset.txt, not
# from its directory name -- src/options.cpp:1213-1227 reads NAME: as the
# option value and VIEW: only as the menu label, so gfx/ASCIITileset
# declares the id ASCIITiles while gfx/MShockXotto+ declares
# MshockXottoplus with the view MSXotto+.  Every lookup scans those fields,
# accepts a match on either, and additionally tries the alias spellings
# env.sh lists in PLAYTHROUGH_TILESET_ALIASES.  No directory name is ever
# guessed.  Installing a tileset writes into gfx/, which produces no tracked
# change because /gfx/* is ignored at .gitignore:52; that file is not
# edited.
#
# tileset_field CONF FIELD -- read one field out of a tileset.txt.
# FIELD is validated against the two names this file ever asks for, so
# nothing outside the script can influence the expression.
tileset_field() {
    local conf="$1"
    local field="$2"
    case "${field}" in
        NAME|VIEW) ;;
        *) return 1 ;;
    esac
    [ -f "${conf}" ] || return 1
    # Trailing CR is stripped for packs authored on Windows, and
    # trailing blanks because the engine trims the value too.
    sed -n "s/^[[:space:]]*${field}:[[:space:]]*//p" "${conf}" |
        head -n 1 |
        tr -d '\r' |
        sed 's/[[:space:]]*$//'
}

# scan_installed_tilesets -- inventory gfx/ into the three parallel arrays. The
# glob's variable part is quoted and only the pattern itself is bare; a
# directory with no tileset.txt is skipped rather than assumed.
scan_installed_tilesets() {
    TILESET_NAMES=()
    TILESET_VIEWS=()
    TILESET_DIRS=()
    TILESET_LINKS_SKIPPED=0
    local dir conf name view
    for dir in "${PLAYTHROUGH_REPO_ROOT}/gfx"/*/; do
        [ -d "${dir}" ] || continue
        if [ -L "${dir%/}" ]; then
            playthrough_warn "gfx/$(basename "${dir%/}") is a" \
                "symbolic link, so it is not an installed tileset of" \
                "this checkout: artwork reached through a link can be" \
                "replaced without anything under gfx/ changing.  It is" \
                "skipped rather than followed."
            TILESET_LINKS_SKIPPED=$(( TILESET_LINKS_SKIPPED + 1 ))
            continue
        fi
        conf="${dir}tileset.txt"
        [ -f "${conf}" ] || continue
        if [ -L "${conf}" ]; then
            playthrough_warn "gfx/$(basename "${dir%/}")/tileset.txt" \
                "is a symbolic link, so the id it declares is read" \
                "from somewhere this checkout cannot account for; the" \
                "directory is skipped."
            TILESET_LINKS_SKIPPED=$(( TILESET_LINKS_SKIPPED + 1 ))
            continue
        fi
        name="$(tileset_field "${conf}" NAME || true)"
        [ -n "${name}" ] || continue
        view="$(tileset_field "${conf}" VIEW || true)"
        TILESET_NAMES+=("${name}")
        TILESET_VIEWS+=("${view}")
        TILESET_DIRS+=("${dir%/}")
    done
    return 0
}

# find_installed_tileset WANTED -- match on NAME or VIEW, exactly. Comparison
# is a literal string test, never a pattern: real ids contain characters such
# as '+' that a regular expression would mis-read.
find_installed_tileset() {
    local wanted="$1"
    local total="${#TILESET_NAMES[@]}"
    local i=0
    while [ "${i}" -lt "${total}" ]; do
        if [ "${TILESET_NAMES[i]}" = "${wanted}" ] ||
           [ "${TILESET_VIEWS[i]}" = "${wanted}" ]; then
            TILESET_ID="${TILESET_NAMES[i]}"
            TILESET_VIEW="${TILESET_VIEWS[i]}"
            TILESET_DIR="${TILESET_DIRS[i]}"
            return 0
        fi
        i=$(( i + 1 ))
    done
    return 1
}

# verify_pack_provenance DIR -- decide whether a pre-placed tileset may be
# ingested at all.
verify_pack_provenance() {
    local dir="${1%/}"
    local entry perm owner
    entry="$(readlink -f -- "${dir}" 2>/dev/null || true)"
    if [ -z "${entry}" ] || [ ! -d "${entry}" ]; then
        playthrough_warn "the tileset pack '${dir}' is not a" \
            "directory"
        return 1
    fi
    local declared="${PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK:-0}"
    local complaint=""
    while : ; do
        perm="$(stat -c '%a' -- "${entry}" 2>/dev/null || true)"
        owner="$(stat -c '%u' -- "${entry}" 2>/dev/null || true)"
        if [ -z "${perm}" ] || [ -z "${owner}" ]; then
            playthrough_warn "cannot stat '${entry}' while checking" \
                "the tileset pack"
            return 1
        fi
        if [ "${owner}" != "0" ] &&
           [ "${owner}" != "${PLAYTHROUGH_UID}" ]; then
            complaint="the tileset pack path '${entry}' is owned by \
uid ${owner}, which is neither root nor uid ${PLAYTHROUGH_UID}"
        elif [ $(( 8#${perm} & 8#022 )) -ne 0 ]; then
            complaint="the tileset pack path '${entry}' is mode \
${perm}, i.e. group- or world-writable, so its contents can be \
replaced between this check and the copy"
        fi
        if [ -n "${complaint}" ]; then
            if [ "${declared}" != "1" ]; then
                playthrough_warn "${complaint}; refusing to ingest" \
                    "artwork from it.  Stage the pack somewhere only" \
                    "root or this account can write, install the" \
                    "tileset under gfx/ by hand, or set" \
                    "PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK=1 to" \
                    "accept this host's layout deliberately.  The" \
                    "sha256 manifest is still required either way."
                return 1
            fi
            playthrough_warn "${complaint}.  Ingesting it anyway" \
                "because PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK=1;" \
                "the pack's own integrity is still verified below, but" \
                "the host cannot vouch for who staged it."
            break
        fi
        [ "${entry}" = "/" ] && break
        entry="${entry%/*}"
        [ -n "${entry}" ] || entry="/"
    done

    local offender
    offender="$(find "${dir}" \( -type l -o \! -type d -a \! -type f \) \
        -print -quit 2>/dev/null || true)"
    if [ -n "${offender}" ]; then
        playthrough_warn "the tileset pack '${dir}' contains" \
            "'${offender}', which is a symbolic link or a special" \
            "file.  An artwork pack is directories and regular files" \
            "only; a link inside it would resolve somewhere else once" \
            "it was copied under gfx/, so the pack is refused rather" \
            "than filtered."
        return 1
    fi

    local sums="${PLAYTHROUGH_TILESET_SHA256SUMS:-${dir}/SHA256SUMS}"
    if [ ! -f "${sums}" ]; then
        playthrough_warn "the tileset pack '${dir}' carries no" \
            "sha256 manifest (looked for '${sums}').  Unverified" \
            "artwork is not installed into the tree the game loads:" \
            "generate one with" \
            "\`cd '${dir}' && find . -type f \\! -name SHA256SUMS" \
            "-exec sha256sum {} + > SHA256SUMS\`, review it, and" \
            "re-run.  Or install the tileset under gfx/ by hand," \
            "which is what a provisioned host already does."
        return 1
    fi
    if ! playthrough_require_tools sha256sum; then
        return 1
    fi
    playthrough_log "verifying '${sums}' before ingesting" \
        "'${dir}'"
    if ! ( cd "${dir}" && sha256sum --quiet --check \
            "$(basename "${sums}")" >/dev/null 2>&1 ); then
        playthrough_warn "sha256 verification of the tileset pack" \
            "'${dir}' FAILED against '${sums}'; nothing is copied." \
            "Re-provision the pack rather than installing it anyway."
        return 1
    fi
    return 0
}

# install_tileset_from_pack WANTED -- copy one tileset out of the pre-placed
# pack, after proving where it came from.
install_tileset_from_pack() {
    local wanted="$1"
    if [ ! -d "${TILESET_PACK}" ]; then
        playthrough_log "no pre-placed tileset pack at" \
            "'${TILESET_PACK}'; nothing to install from"
        return 1
    fi
    local dir conf name view base dest tmp alias matched leftover
    for dir in "${TILESET_PACK}"/*/; do
        [ -d "${dir}" ] || continue
        conf="${dir}tileset.txt"
        [ -f "${conf}" ] || continue
        name="$(tileset_field "${conf}" NAME || true)"
        view="$(tileset_field "${conf}" VIEW || true)"
        # The same alias spellings find_required_tileset accepts, so a
        # pack that declares the id under one of its other names is
        # still recognised here rather than reported as absent.
        matched=0
        if [ "${name}" = "${wanted}" ] ||
           [ "${view}" = "${wanted}" ]; then
            matched=1
        else
            for alias in ${PLAYTHROUGH_TILESET_ALIASES}; do
                if [ "${name}" = "${alias}" ] ||
                   [ "${view}" = "${alias}" ]; then
                    matched=1
                    break
                fi
            done
        fi
        if [ "${matched}" -ne 1 ]; then
            continue
        fi
        base="$(basename "${dir%/}")"
        dest="${PLAYTHROUGH_REPO_ROOT}/gfx/${base}"
        if [ -e "${dest}" ]; then
            playthrough_log "gfx/${base} already exists; leaving" \
                "it exactly as it is"
            return 0
        fi
        verify_pack_provenance "${dir}" || return 1
        # Copy aside and rename, so an interrupted copy can never leave a
        # half-populated tileset that later scans would treat as installed.
        if ! tmp="$(mktemp -d \
                "${PLAYTHROUGH_REPO_ROOT}/gfx/.${base}.partial.XXXXXX" \
                2>/dev/null)"; then
            playthrough_warn "cannot create a staging directory" \
                "under gfx/ for '${name}'"
            return 1
        fi
        playthrough_log "installing tileset '${name}' from" \
            "${dir} into gfx/${base}"
        # cp -a into the staging directory, then RE-CHECK the copy for links
        # and special files before it is published: the source was verified,
        # and this confirms that what actually landed matches what was
        # verified.
        local copy_err=""
        if copy_err="$(
            cp -a "${dir%/}/." "${tmp}/" 2>&1 1>/dev/null
        )"; then
            leftover="$(find "${tmp}" \
                \( -type l -o \! -type d -a \! -type f \) \
                -print -quit 2>/dev/null || true)"
            if [ -z "${leftover}" ] && mv -- "${tmp}" "${dest}"; then
                chmod 755 -- "${dest}" 2>/dev/null || true
                return 0
            fi
            if [ -n "${leftover}" ]; then
                playthrough_warn "the staged copy of '${name}'" \
                    "contains '${leftover}', a link or special file;" \
                    "discarding it instead of publishing it"
            fi
        fi
        playthrough_warn "could not install tileset '${name}' from" \
            "'${dir%/}' into '${dest}'"
        if [ -n "${copy_err}" ]; then
            playthrough_warn "cp reported: $(
                printf '%s' "${copy_err}" |
                    head -c 500 |
                    tr '\n' '|'
            )"
        elif [ -z "${leftover}" ]; then
            playthrough_warn "cp reported nothing on stderr, so the" \
                "rename to '${dest}' is what failed"
        fi
        # Remove only the staging directory this call created, named in
        # full and confirmed to be the intended path first.
        case "${tmp}" in
            "${PLAYTHROUGH_REPO_ROOT}/gfx/."*.partial.*)
                rm -rf -- "${tmp}"
                ;;
        esac
        return 1
    done
    playthrough_log "'${wanted}' is not present in" \
        "${TILESET_PACK} either"
    return 1
}

# report_installed_tilesets -- put the real inventory on stderr, so a
# failure to resolve is diagnosable without a second command.
report_installed_tilesets() {
    local total="${#TILESET_NAMES[@]}"
    local i=0
    if [ "${total}" -eq 0 ]; then
        playthrough_warn "gfx/ contains no tileset.txt at all"
        return 0
    fi
    playthrough_log "installed tilesets (id | view | directory):"
    while [ "${i}" -lt "${total}" ]; do
        playthrough_log "  ${TILESET_NAMES[i]} |" \
            "${TILESET_VIEWS[i]} |" \
            "gfx/$(basename "${TILESET_DIRS[i]}")"
        i=$(( i + 1 ))
    done
    return 0
}

# find_required_tileset -- match the required tileset by id, by view label, or
# by any of its documented alias spellings.
find_required_tileset() {
    local wanted="$1"
    local alias
    if find_installed_tileset "${wanted}"; then
        return 0
    fi
    for alias in ${PLAYTHROUGH_TILESET_ALIASES}; do
        if [ "${alias}" = "${wanted}" ]; then
            continue
        fi
        if find_installed_tileset "${alias}"; then
            playthrough_log "matched the required tileset on the" \
                "alias '${alias}' (id '${TILESET_ID}')"
            return 0
        fi
    done
    return 1
}

# verify_tileset_provenance -- prove WHICH BYTES the artwork is, from a tracked
# anchor outside it, before the tileset is used.
verify_tileset_provenance() {
    local dir="$1"
    local ident="$2"
    local view="$3"
    local checker="${PLAYTHROUGH_TOOLING_DIR}/tileset_provenance.py"
    if [ ! -f "${checker}" ]; then
        die "${EX_PREREQ}" "no ${checker}, so the artwork under" \
            "'${dir}' cannot be verified against the tracked" \
            "provenance anchor.  gfx/ is git-ignored, so that anchor" \
            "is the only statement of which bytes the tileset must" \
            "be; restore it before launching."
    fi
    if [ -z "${PLAYTHROUGH_PYTHON}" ] || \
       [ ! -x "${PLAYTHROUGH_PYTHON}" ]; then
        die "${EX_PREREQ}" "the interpreter" \
            "'${PLAYTHROUGH_PYTHON:-<unset>}' is not executable, so" \
            "the tileset provenance check cannot run.  It is not" \
            "skipped: unverified artwork decides what every frame of" \
            "the film looks like."
    fi
    local observed=""
    if ! observed="$(
        "${PLAYTHROUGH_PYTHON}" -B "${checker}" \
            --root "${PLAYTHROUGH_REPO_ROOT}" verify \
            --directory "${dir}" --id "${ident}" --view "${view}" \
            2>&1 1>/dev/null
    )"; then
        playthrough_warn "${observed}"
        die "${EX_TILESET}" "the installed tileset '${ident}' does" \
            "NOT match the tracked provenance anchor" \
            "'$(playthrough_rel \
                "${PLAYTHROUGH_TOOLING_DIR}/tileset_provenance.json")'" \
            "(details above).  The artwork every frame is rendered in" \
            "is git-ignored, so this anchor is the only thing that" \
            "says which bytes it may be, and a run that renders" \
            "unverified artwork produces a film nobody can attest to." \
            "Re-provision the tileset from the anchored upstream" \
            "commit, or -- if the artwork legitimately changed --" \
            "regenerate the anchor with" \
            "'${PLAYTHROUGH_PYTHON} ${checker} generate' and commit it" \
            "as a reviewed change."
    fi
    playthrough_log "tileset provenance VERIFIED against the tracked" \
        "anchor: $(
            "${PLAYTHROUGH_PYTHON}" -B "${checker}" \
                --root "${PLAYTHROUGH_REPO_ROOT}" show 2>/dev/null |
                tr '\n' ' '
        )"
    return 0
}

resolve_tileset() {
    assert_repo_root
    local required="${PLAYTHROUGH_TILESET}"
    # ONE TILESET, ONE BRANCH.  There is no substitute named here and no
    # variable that could authorise one: see the resolution record in
    # playthrough/README.md ("Which artwork the requirement means").
    scan_installed_tilesets
    if find_required_tileset "${required}"; then
        TILESET_ORIGIN="required-installed"
    else
        playthrough_log "the required tileset '${required}' is not" \
            "installed under gfx/; hydrating it from the pre-placed" \
            "pack at '${TILESET_PACK}'"
        install_tileset_from_pack "${required}" || true
        scan_installed_tilesets
        if find_required_tileset "${required}"; then
            TILESET_ORIGIN="required-from-pack"
        else
            report_installed_tilesets
            if [ "${TILESET_LINKS_SKIPPED}" -gt 0 ]; then
                # THE PRECISE DIAGNOSIS, not the symptom.
                die "${EX_TILESET}" "the required tileset" \
                    "'${required}' is not installed under gfx/ AS A" \
                    "DIRECTORY OF THIS CHECKOUT:" \
                    "${TILESET_LINKS_SKIPPED} entr(y|ies) under gfx/" \
                    "are symbolic links and were skipped rather than" \
                    "followed (named above).  Artwork reached through" \
                    "a link can be replaced without anything under" \
                    "gfx/ changing, and gfx/ is git-ignored, so a link" \
                    "there is outside everything this repository can" \
                    "attest to.  Install the tileset as a real" \
                    "directory -- gfx/ is git-ignored at" \
                    ".gitignore:52, so nothing tracked changes -- and" \
                    "make sure it matches" \
                    "playthrough/tooling/tileset_provenance.json."
            fi
            # FAIL CLOSED: an absent MSXotto+ stops the run rather than
            # producing a compliant-looking movie in the wrong artwork.
            die "${EX_TILESET}" "the required tileset '${required}'" \
                "is not installed under gfx/ and could not be" \
                "hydrated from '${TILESET_PACK}'.  It is REQUIRED:" \
                "the run must render MSXotto+.  Provision the pack" \
                "(a composed copy of the MShockXotto+ set from" \
                "https://github.com/I-am-Erk/CDDA-Tilesets, built" \
                "with the repository's own tools/gfx_tools/" \
                "compose.py) at PLAYTHROUGH_TILESET_PACK, or install" \
                "it under gfx/ by hand -- gfx/ is git-ignored at" \
                ".gitignore:52, so either changes nothing tracked." \
                "There is no substitute and no switch that would" \
                "accept one: an ASCII capture looks like a perfectly" \
                "good frame, so a run that quietly came up on other" \
                "artwork would fail the requirement invisibly."
        fi
    fi

    playthrough_log "tileset resolved: id='${TILESET_ID}'" \
        "view='${TILESET_VIEW}' origin=${TILESET_ORIGIN}"
    # AND PROVEN, before a single consumer hears about it. Resolution answers
    # "which directory declares the required id"; this answers "and are those
    # the bytes it is supposed to be".
    verify_tileset_provenance "${TILESET_DIR}" "${TILESET_ID}" \
        "${TILESET_VIEW}"
    # The id is the value seed_options.py writes to the TILES option,
    # which is why it is the NAME: field and not the VIEW: label.
    emit PLAYTHROUGH_TILESET_RESOLVED "${TILESET_ID}"
    emit PLAYTHROUGH_TILESET_VIEW "${TILESET_VIEW}"
    emit PLAYTHROUGH_TILESET_DIR \
        "$(playthrough_rel "${TILESET_DIR}")"
    emit PLAYTHROUGH_TILESET_ORIGIN "${TILESET_ORIGIN}"
    return 0
}

# ---------------------------------------------------------------------
# STEP 4 -- the save-resume pre-flight probe.
# ---------------------------------------------------------------------

# WHAT COUNTS AS A CHARACTER SAVE -- BOTH FORMS, AND WHY THAT MATTERS.
# src/game_io.cpp:601-621 writes `playerfile + SAVE_EXTENSION` when the world
# stores plainly and `playerfile + SAVE_EXTENSION + zzip_suffix` when it
# compresses -- `#<b64>.sav` versus `#<b64>.sav.zzip`, with zzip_suffix =
# ".zzip" at src/worldfactory.h:24-25.  WORLD_COMPRESSION2 defaults to TRUE
# (src/options.cpp:1816-1819), so a world this pipeline did not seed itself
# carries the compressed form.  Scanning only `*.sav` would report an
# existing survivor as absent, resolve to "create" and OVERWRITE the save
# that must be continued.  Both forms are scanned, and both forms of one
# character count once: the `.zzip` suffix is stripped and each distinct
# base name counted a single time.
#
# WHAT MAKES A WORLD RESUMABLE is a character save and nothing less.
# master.gsav proves a WORLD exists, not that anybody lives in it -- the
# engine writes the world as soon as it is created, so a run interrupted
# during character creation leaves a world with an empty character list.
# Such a world is reported, excluded, and correctly used to create a
# character.
#
# AMBIGUITY IS REFUSED, NOT GUESSED.  Glob order is locale- and
# filesystem-dependent, so taking the first world could continue a different
# survivor between runs of the same command.  With more than one resumable
# world the probe FAILS and asks for PLAYTHROUGH_RESUME_WORLD -- deliberately
# not named PLAYTHROUGH_SAVE_WORLD, which is an OUTPUT of this probe, so a
# caller who eval'd this script's stdout cannot turn last run's report into
# this run's silent input.
#
# count_character_saves DIR -- how many character saves one world holds,
# counting the plain and the compressed form.
assert_real_save_dir() {
    local path="$1" label="${2:-directory}"
    if [ -L "${path}" ]; then
        die "${EX_LAYOUT}" \
            "${label} '$(playthrough_rel "${path}")' is a" \
            "symbolic link.  The save must live inside the" \
            "committed working" \
            "tree: the engine writes through that name, so a link" \
            "would put this session's save somewhere no commit can" \
            "reach while every count still matched.  Remove it" \
            "deliberately, having established what it points at."
    fi
    [ -d "${path}" ] || return 1
    local canonical parent
    canonical="$(readlink -f -- "${path}" 2>/dev/null || true)"
    parent="$(readlink -f -- "$(dirname -- "${path%/}")" 2>/dev/null ||
        true)"
    if [ -z "${canonical}" ] || [ -z "${parent}" ] ||
       [ "${canonical}" != "${parent}/$(basename -- "${path%/}")" ]; then
        die "${EX_LAYOUT}" \
            "${label} '$(playthrough_rel "${path}")' resolves" \
            "to '${canonical:-nothing}', which is not inside" \
            "'$(playthrough_rel "${parent}")'.  A save directory" \
            "that" \
            "canonicalises elsewhere is not inside the committed tree," \
            "whatever its name says."
    fi
    return 0
}

# assert_real_save_file PATH LABEL
#   True when PATH is a regular file reached without a symlink.  Absent
#   is an ordinary answer and returns 1; a LINK is a refusal, for the
#   reasons above.
assert_real_save_file() {
    local path="$1" label="${2:-file}"
    if [ -L "${path}" ]; then
        die "${EX_LAYOUT}" \
            "${label} '$(playthrough_rel "${path}")' is a" \
            "symbolic link.  A save file must be a real file inside" \
            "playthrough/userdir/: the engine writes the save through" \
            "that name, so a link takes it outside the committed tree."
    fi
    [ -f "${path}" ] || return 1
    return 0
}

count_character_saves() {
    local dir="$1"
    local found=0 entry base seen=" "
    for entry in "${dir}"'#'*.sav "${dir}"'#'*.sav.zzip; do
        assert_real_save_file "${entry}" "the character save" ||
            continue
        # `#<b64>.sav.zzip` and `#<b64>.sav` are the SAME character, so the
        # plain name is what is counted: a two-glob sum would report two
        # survivors where there is one, and the count is what the ambiguity
        # warning below is measured against.
        base="$(basename "${entry}")"
        base="${base%.zzip}"
        case "${seen}" in
            *" ${base} "*) continue ;;
        esac
        seen="${seen}${base} "
        found=$(( found + 1 ))
    done
    printf '%s' "${found}"
}

# character_save_forms DIR -- which canonical form(s) one world stores its
# characters in: "", ".sav", ".sav.zzip", or ".sav,.sav.zzip".
character_save_forms() {
    local dir="$1"
    local entry plain=0 compressed=0 forms=""
    for entry in "${dir}"'#'*.sav.zzip; do
        if assert_real_save_file "${entry}" "the character save"; then
            compressed=1
            break
        fi
    done
    for entry in "${dir}"'#'*.sav; do
        if assert_real_save_file "${entry}" "the character save"; then
            plain=1
            break
        fi
    done
    if [ "${plain}" -eq 1 ]; then
        forms=".sav"
    fi
    if [ "${compressed}" -eq 1 ]; then
        forms="${forms}${forms:+,}.sav.zzip"
    fi
    printf '%s' "${forms}"
}

# recheck_save_resume
#   Re-run the probe from scratch and refuse a save tree that MOVED.
recheck_save_resume() {
    local was_mode="${SESSION_MODE}" was_world="${SAVE_WORLD}"
    local was_worlds="${SAVE_WORLD_COUNT}" was_chars="${SAVE_CHAR_COUNT}"
    PROBE_DONE=0
    probe_save_resume
    if [ "${SESSION_MODE}" != "${was_mode}" ] ||
       [ "${SAVE_WORLD}" != "${was_world}" ] ||
       [ "${SAVE_WORLD_COUNT}" != "${was_worlds}" ] ||
       [ "${SAVE_CHAR_COUNT}" != "${was_chars}" ]; then
        die "${EX_LAYOUT}" "the save tree under" \
            "$(playthrough_rel "${PLAYTHROUGH_SAVE_DIR}") changed" \
            "between the resume decision and the launch: it read" \
            "'${was_mode}' / world '${was_world:-none}' /" \
            "${was_worlds} world(s) / ${was_chars} character(s) and" \
            "now reads '${SESSION_MODE}' / world" \
            "'${SAVE_WORLD:-none}' / ${SAVE_WORLD_COUNT} world(s) /" \
            "${SAVE_CHAR_COUNT} character(s).  An existing save is" \
            "continued, never replaced, so a decision that is no" \
            "longer true is not acted on.  Nothing was launched."
    fi
    return 0
}

# assert_resume_not_superseded WORLD -- refuse a save the RECORD has already
# finished with.
assert_resume_not_superseded() {
    local world="$1"
    local prober="${PLAYTHROUGH_TOOLING_DIR}/session.py"
    local refusal="" status=0
    if [ ! -f "${prober}" ]; then
        die "${EX_PREREQ}" "no ${prober}, so whether the existing" \
            "save may be continued cannot be established.  It is" \
            "not assumed: a save whose survivor has died is still" \
            "live-shaped on disk, so continuing it on a guess would" \
            "put a dead survivor back into play."
    fi
    if [ -z "${PLAYTHROUGH_PYTHON}" ] ||
       [ ! -x "${PLAYTHROUGH_PYTHON}" ]; then
        die "${EX_PREREQ}" "the interpreter" \
            "'${PLAYTHROUGH_PYTHON:-<unset>}' is not executable, so" \
            "whether the existing save may be continued cannot be" \
            "established, and it is not assumed for the reason" \
            "above."
    fi
    local -a probe=(
        "${PLAYTHROUGH_PYTHON}" -B "${prober}" probe
        --save-dir "${PLAYTHROUGH_SAVE_DIR}"
    )
    if [ -n "${world}" ]; then
        probe+=(--world "${world}")
    fi
    # stdout is session.py's KEY=value channel and is discarded here --
    # this script emits its own -- while stderr carries the refusal and
    # is forwarded verbatim, because that message names the three ways
    # forward and choosing between them is the operator's call.
    if refusal="$("${probe[@]}" 2>&1 1>/dev/null)"; then
        playthrough_log "the append-only record agrees this save may" \
            "be continued: session.py reports world" \
            "'${world:-the only resumable one}' resumable"
        return 0
    else
        status=$?
    fi
    if [ -n "${refusal}" ]; then
        # session.py stamps its own 'playthrough: FATAL: ' prefix, so that
        # prefix is dropped before forwarding: otherwise the line reads
        # "WARNING: ...
        playthrough_warn "session.py reports:" \
            "${refusal#playthrough: FATAL: }"
    fi
    if [ "${status}" -eq 2 ]; then
        die "${EX_NOT_RESUMABLE}" "the existing save MUST NOT be" \
            "continued: the append-only record shows this world's" \
            "survivor died, and the save on disk is inconsistent" \
            "with that ending, so continuing it would put a dead" \
            "survivor back into play with nothing on disk to show" \
            "it.  Which inconsistency it is, and the ways forward," \
            "are named in session.py's refusal above; this script" \
            "will not choose between them, because each one either" \
            "discards or publishes evidence."
    fi
    die "${EX_PREREQ}" "session.py could not establish whether the" \
        "existing save may be continued (exit ${status}).  The" \
        "resume decision is refused rather than guessed."
}

probe_save_resume() {
    if [ "${PROBE_DONE}" -eq 1 ]; then
        return 0
    fi
    SESSION_MODE="create"
    SAVE_WORLD=""
    SAVE_WORLD_COUNT=0
    SAVE_CHAR_COUNT=0
    SAVE_CHAR_FORMS=""

    local dir world chars forms
    local resumable=()
    local characterless=()
    local requested="${PLAYTHROUGH_RESUME_WORLD:-}"

    if assert_real_save_dir "${PLAYTHROUGH_SAVE_DIR}" \
            "the save directory"; then
        for dir in "${PLAYTHROUGH_SAVE_DIR}"/*/; do
            assert_real_save_dir "${dir}" "the world directory" ||
                continue
            world="$(basename "${dir%/}")"
            # THE NAME IS SOMEBODY ELSE'S CHOICE, so it is checked before it is
            # used. This is a directory name under the save tree: the engine
            # writes it from what the player typed, and any local account able
            # to create a directory there writes whatever it likes.
            if ! playthrough_assert_record_token "${world}" \
                    "the world directory name" 2>/dev/null; then
                playthrough_warn "a directory under the save tree has" \
                    "a name that cannot be written as one line of the" \
                    "record, so it is NOT treated as a world:" \
                    "$(playthrough_escape_controls "${world}")"
                continue
            fi
            if ! assert_real_save_file "${dir}master.gsav" \
                    "the world save"; then
                playthrough_warn "save/${world} has no" \
                    "master.gsav; not treating it as a world"
                continue
            fi
            SAVE_WORLD_COUNT=$(( SAVE_WORLD_COUNT + 1 ))
            chars="$(count_character_saves "${dir}")"
            SAVE_CHAR_COUNT=$(( SAVE_CHAR_COUNT + chars ))
            if [ "${chars}" -gt 0 ]; then
                resumable+=("${world}")
                playthrough_log "save/${world}: ${chars} character" \
                    "save(s) -- resumable"
            else
                characterless+=("${world}")
            fi
            # Which canonical form(s) this world stores characters in,
            # accumulated across every world so the emitted fact describes the
            # save TREE rather than the last directory scanned.
            forms="$(character_save_forms "${dir}")"
            case "${SAVE_CHAR_FORMS}" in
                ".sav,.sav.zzip") ;;
                "") SAVE_CHAR_FORMS="${forms}" ;;
                *)
                    if [ -n "${forms}" ] &&
                       [ "${forms}" != "${SAVE_CHAR_FORMS}" ]; then
                        SAVE_CHAR_FORMS=".sav,.sav.zzip"
                    fi
                    ;;
            esac
        done
    fi

    for world in "${characterless[@]+"${characterless[@]}"}"; do
        playthrough_warn "save/${world} is a world with NO character" \
            "save (neither #*.sav nor #*.sav.zzip).  A world is" \
            "written as soon as it is created, so this is most" \
            "likely a run interrupted during character creation." \
            "It is not resumable -- loading it would open an empty" \
            "character list -- so it is excluded from the resume" \
            "decision."
    done

    local count="${#resumable[@]}"
    if [ "${count}" -eq 0 ]; then
        playthrough_log "CREATE: no character save under" \
            "${PLAYTHROUGH_SAVE_DIR}, so this session creates a" \
            "character through the custom point-buy creator"
    else
        SESSION_MODE="resume"
        if [ -n "${requested}" ]; then
            local match=""
            for world in "${resumable[@]}"; do
                if [ "${world}" = "${requested}" ]; then
                    match="${world}"
                    break
                fi
            done
            if [ -z "${match}" ]; then
                die "${EX_LAYOUT}" \
                    "PLAYTHROUGH_RESUME_WORLD='${requested}' is not" \
                    "a resumable world.  The worlds holding at" \
                    "least one character save are:" \
                    "${resumable[*]}."
            fi
            SAVE_WORLD="${match}"
            playthrough_log "resuming world '${SAVE_WORLD}', chosen" \
                "explicitly by PLAYTHROUGH_RESUME_WORLD"
        elif [ "${count}" -eq 1 ]; then
            SAVE_WORLD="${resumable[0]}"
        else
            die "${EX_LAYOUT}" "${count} worlds hold character" \
                "saves (${resumable[*]}), so which save to continue" \
                "is ambiguous.  This is refused rather than guessed:" \
                "directory order is locale- and" \
                "filesystem-dependent, so a guess could continue a" \
                "different survivor on the next run of the same" \
                "command.  Set PLAYTHROUGH_RESUME_WORLD to the one" \
                "you mean."
        fi
        # THE RECORD GETS A VETO, before the instruction below is printed.
        assert_resume_not_superseded "${SAVE_WORLD}"
        playthrough_log "RESUME: ${SAVE_WORLD_COUNT} world(s) and" \
            "${SAVE_CHAR_COUNT} character save(s)" \
            "(${SAVE_CHAR_FORMS:-no character file yet}) exist under" \
            "${PLAYTHROUGH_SAVE_DIR}.  The existing save MUST be" \
            "continued -- load world '${SAVE_WORLD}' and do not" \
            "create a new character."
        # A WARNING rather than a refusal, and the asymmetry with the
        # multiple-world case above is deliberate: which WORLD to open is a
        # decision this script has to make and must not guess, whereas which
        # survivor to load happens inside the game's own character list, where
        # the operator sees the names.
        if [ "${SAVE_CHAR_COUNT}" -gt 1 ]; then
            playthrough_warn "${SAVE_CHAR_COUNT} distinct character" \
                "saves are present, and this run records exactly one" \
                "survivor; confirm which one is being continued" \
                "before loading, and do not create another"
        fi
    fi

    PROBE_DONE=1
    emit PLAYTHROUGH_SESSION_MODE "${SESSION_MODE}"
    emit PLAYTHROUGH_SAVE_WORLD "${SAVE_WORLD}"
    emit PLAYTHROUGH_SAVE_WORLD_COUNT "${SAVE_WORLD_COUNT}"
    emit PLAYTHROUGH_SAVE_CHAR_COUNT "${SAVE_CHAR_COUNT}"
    emit PLAYTHROUGH_SAVE_RESUMABLE_COUNT "${count}"
    # Which canonical form(s) the character files are stored in, so the
    # fact is recorded rather than assumed from the seeded option: a
    # comma-separated list of ".sav", ".sav.zzip", or both, and empty
    # when no character file exists yet.
    emit PLAYTHROUGH_SAVE_CHAR_FORMS "${SAVE_CHAR_FORMS}"
    return 0
}

# ---------------------------------------------------------------------
# Window and process primitives.
# ---------------------------------------------------------------------

# WINDOW TARGETING IS BY CLASS, AND ONLY BY CLASS.
#   * `xdotool search --class cataclysm-tiles` finds this window.
#   * `xdotool search --name 'Cataclysm'` returns EMPTY for it, even though
#     `xwininfo -root -children` lists it with the title "Cataclysm: Dark
#     Days Ahead - <hash>".  Name matching is not an available alternative.
#   * Scraping a window id out of xwininfo with a loose hexadecimal pattern
#     is actively unsafe: the geometry substring xwininfo prints for the
#     window ("1920x1080" on this surface) mis-matches such patterns.
# xdotool takes the display from the environment -- it has no --display
# option -- which is why env.sh exports DISPLAY and every call below simply
# inherits it.
#
# game_window_ids -- every matching window id, newest last.  `|| true`
# is required because xdotool search exits non-zero when nothing
# matches, which is an ordinary answer and not an error.
game_window_ids() {
    xdotool search --class "${PLAYTHROUGH_WINDOW_CLASS}" \
        2>/dev/null || true
}

# find_game_window -- set WINDOW_ID, WINDOW_OWNED_PID, GAME_PID and
# GAME_IDENTITY to the ONE window whose owning process is confirmed to be
# this checkout's game, or fail.  Every candidate is resolved window ->
# _NET_WM_PID -> /proc and put through pid_is_game, and the count decides:
# none is a failure the caller answers by waiting or launching, one is
# accepted whatever the search order was, and more than one is refused
# outright -- two instances of this checkout against one userdir is a
# state no correct run produces, both would be writing the same save, and
# choosing between them would be guessing.  A candidate whose pid cannot
# be confirmed is discarded, never accepted.
find_game_window() {
    WINDOW_ID=""
    WINDOW_OWNED_PID=""
    local id pid
    local ours=() our_pids=() our_identities=() strangers=()
    while IFS= read -r id; do
        [ -n "${id}" ] || continue
        pid="$(xdotool getwindowpid "${id}" 2>/dev/null || true)"
        case "${pid}" in
            ''|*[!0-9]*)
                strangers+=("${id} (no readable owning pid)")
                continue
                ;;
        esac
        # pid_is_game sets GAME_IDENTITY as its last act, so the pair is
        # captured HERE, next to the pid it belongs to, rather than left
        # to whichever call happened to run last.
        if pid_is_game "${pid}"; then
            ours+=("${id}")
            case " ${our_pids[*]-} " in
                *" ${pid} "*) ;;
                *)
                    our_pids+=("${pid}")
                    our_identities+=("${GAME_IDENTITY}")
                    ;;
            esac
        else
            strangers+=("${id} (pid ${pid})")
        fi
    done < <(game_window_ids)

    if [ "${#our_pids[@]}" -gt 1 ]; then
        die "${EX_WINDOW}" "${#our_pids[@]} separate instances of" \
            "this checkout's game are running on" \
            "${PLAYTHROUGH_DISPLAY} (pids ${our_pids[*]}), all" \
            "pointed at ${PLAYTHROUGH_USERDIR_ARG}.  Refusing to" \
            "guess which one to drive: they would both be writing" \
            "to the same save, and keystrokes sent to the wrong one" \
            "would be captured as if they were this session.  Stop" \
            "the instance you do not want -- 'launch_game.sh stop'" \
            "handles one -- then retry."
    fi

    if [ "${#ours[@]}" -eq 0 ]; then
        GAME_IDENTITY=""
        # Reported ONCE per run.  find_game_window is called from a
        # bounded poll, so warning on every tick would bury the launch
        # log under the same sentence a hundred times over.
        if [ "${#strangers[@]}" -ne 0 ] &&
           [ "${FOREIGN_WINDOWS_WARNED}" -eq 0 ]; then
            FOREIGN_WINDOWS_WARNED=1
            playthrough_warn "${#strangers[@]} window(s) of class" \
                "'${PLAYTHROUGH_WINDOW_CLASS}' are on" \
                "${PLAYTHROUGH_DISPLAY} but none belongs to this" \
                "checkout, so none of them is usable here:" \
                "${strangers[*]}"
        fi
        return 1
    fi

    # One verified instance.  When it owns several windows they are all
    # the same process, so any of them addresses it; the last is taken
    # for continuity with the search order.
    WINDOW_ID="${ours[${#ours[@]} - 1]}"
    WINDOW_OWNED_PID="${our_pids[0]}"
    GAME_PID="${our_pids[0]}"
    GAME_IDENTITY="${our_identities[0]}"
    return 0
}

# wait_for_game_window TIMEOUT_SECONDS -- bounded poll with progress.
wait_for_game_window() {
    playthrough_validate_int "${1-}" "window timeout" 1 3600 ||
        die "${EX_USAGE}" "wait_for_game_window was given an" \
            "unusable timeout"
    local timeout="${PLAYTHROUGH_INT}"
    local ticks=$(( timeout * 4 ))
    local waited=0
    while [ "${waited}" -lt "${ticks}" ]; do
        if find_game_window; then
            return 0
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
        if [ $(( waited % 40 )) -eq 0 ]; then
            playthrough_log "waiting for a window of class" \
                "'${PLAYTHROUGH_WINDOW_CLASS}' on" \
                "${PLAYTHROUGH_DISPLAY}: $(( waited / 4 ))s"
        fi
    done
    return 1
}

# read_window_geometry -- WIDTHxHEIGHT+X+Y for WINDOW_ID.
read_window_geometry() {
    WINDOW_GEOMETRY=""
    WINDOW_WIDTH=""
    WINDOW_HEIGHT=""
    [ -n "${WINDOW_ID}" ] || return 1
    local raw w h x y
    raw="$(xdotool getwindowgeometry --shell "${WINDOW_ID}" \
        2>/dev/null || true)"
    [ -n "${raw}" ] || return 1
    w="$(printf '%s\n' "${raw}" | sed -n 's/^WIDTH=//p' | head -n 1)"
    h="$(printf '%s\n' "${raw}" | sed -n 's/^HEIGHT=//p' | head -n 1)"
    x="$(printf '%s\n' "${raw}" | sed -n 's/^X=//p' | head -n 1)"
    y="$(printf '%s\n' "${raw}" | sed -n 's/^Y=//p' | head -n 1)"
    case "${w}" in ''|*[!0-9]*) return 1 ;; esac
    case "${h}" in ''|*[!0-9]*) return 1 ;; esac
    # THE OFFSETS ARE VALIDATED TOO, not merely defaulted.
    case "${x}" in ''|*[!0-9-]*) return 1 ;; esac
    case "${y}" in ''|*[!0-9-]*) return 1 ;; esac
    WINDOW_WIDTH="${w}"
    WINDOW_HEIGHT="${h}"
    WINDOW_X="${x}"
    WINDOW_Y="${y}"
    WINDOW_GEOMETRY="${w}x${h}+${x}+${y}"
    return 0
}

# settle_window_geometry -- re-resolve the window and wait for its geometry to
# STOP CHANGING, before anything asserts on it.
#
# FULLSCREEN=windowedbl IS APPLIED AFTER AN INITIALLY DECORATED WINDOW.
# The engine creates an ordinary decorated, resizable window at the grid
# size and only then applies SDL's fullscreen_desktop
# [src/sdltiles.cpp:612-616], which SDL implements by DESTROYING that
# window and creating a replacement.  So for a moment a launch has two
# window ids and two geometries, and the first is not the one the session
# is captured from.  Measured on this surface, in order:
#
#   window 4194306   1920x1072+1+22   the decorated original -- openbox's
#                                     1px border and 22px titlebar
#   window 4194313   1920x1080+0+0    the replacement, borderless, given
#                                     the whole root
#
# Reading the geometry once, as soon as a window appears, would therefore
# assert on values the engine has already left, and a perfectly good
# launch would refuse itself with `window is 1920x1072+1+22, and a
# capture launch requires exactly ...`.  Wait for the borderless
# replacement before targeting it.
#
# TWO CONSECUTIVE IDENTICAL READS, not a fixed sleep: a sleep long enough
# to be safe on a loaded host is dead time on every launch, and a short
# one is a race.  The ID is re-resolved on every attempt because the
# window being measured may already have been destroyed.
settle_window_geometry() {
    local previous="" attempt=0
    # Twenty attempts at a quarter second is five seconds, which is an
    # order of magnitude more than the transition measured here and still
    # bounded.
    while [ "${attempt}" -lt 20 ]; do
        attempt=$(( attempt + 1 ))
        # The ID first: the window being measured may already be gone.
        find_game_window || true
        if ! read_window_geometry || [ -z "${WINDOW_GEOMETRY}" ]; then
            sleep 0.25
            continue
        fi
        if [ -n "${previous}" ] &&
            [ "${WINDOW_GEOMETRY}" = "${previous}" ]; then
            if [ "${attempt}" -gt 2 ]; then
                playthrough_log "window geometry settled at" \
                    "${WINDOW_GEOMETRY} (window ${WINDOW_ID}, after" \
                    "${attempt} reads)"
            fi
            return 0
        fi
        previous="${WINDOW_GEOMETRY}"
        sleep 0.25
    done
    playthrough_warn "the window geometry was still changing after" \
        "${attempt} reads; the last one was" \
        "${WINDOW_GEOMETRY:-unreadable} on window" \
        "${WINDOW_ID:-none}.  What follows judges that reading."
    return 0
}

# pid_is_game PID -- true only when that pid is THIS checkout's game, launched
# by this pipeline, on this display.
pid_is_game() {
    local pid="$1"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    local proc="/proc/${pid}"
    [ -d "${proc}" ] || return 1

    # 1. The executable, resolved through /proc/<pid>/exe.  readlink -f
    #    on our own path too, so a symlinked checkout compares equal.
    local exe want_exe
    exe="$(readlink -f "${proc}/exe" 2>/dev/null || true)"
    want_exe="$(readlink -f "${PLAYTHROUGH_GAME_BIN}" 2>/dev/null ||
        true)"
    if [ -z "${exe}" ] || [ -z "${want_exe}" ] ||
       [ "${exe}" != "${want_exe}" ]; then
        return 1
    fi

    # 2. The working directory: this checkout's root and no other.
    local cwd want_cwd
    cwd="$(readlink -f "${proc}/cwd" 2>/dev/null || true)"
    want_cwd="$(readlink -f "${PLAYTHROUGH_REPO_ROOT}" 2>/dev/null ||
        true)"
    if [ -z "${cwd}" ] || [ -z "${want_cwd}" ] ||
       [ "${cwd}" != "${want_cwd}" ]; then
        return 1
    fi

    # 3. The argument vector, read NUL-delimited.  `--userdir` must be
    #    present AND the argument after it must name OUR userdir.
    [ -r "${proc}/cmdline" ] || return 1
    local arg seen_flag=0 userdir_ok=0
    while IFS= read -r -d '' arg || [ -n "${arg}" ]; do
        if [ "${seen_flag}" -eq 1 ]; then
            case "${arg}" in
                "${PLAYTHROUGH_USERDIR_ARG}"|\
                "${PLAYTHROUGH_USERDIR_ARG%/}"|\
                "${PLAYTHROUGH_USERDIR}"|"${PLAYTHROUGH_USERDIR}/")
                    userdir_ok=1
                    ;;
            esac
            seen_flag=0
            continue
        fi
        if [ "${arg}" = "--userdir" ]; then
            seen_flag=1
        fi
    done <"${proc}/cmdline"
    if [ "${userdir_ok}" -ne 1 ]; then
        return 1
    fi

    # 4. The display.  environ is readable only for our own processes,
    #    which is itself part of the answer: a game we did not start as
    #    this user is not ours to signal.
    [ -r "${proc}/environ" ] || return 1
    local env_display=""
    while IFS= read -r -d '' arg; do
        case "${arg}" in
            DISPLAY=*) env_display="${arg#DISPLAY=}" ;;
        esac
    done <"${proc}/environ"
    if [ "${env_display}" != "${PLAYTHROUGH_DISPLAY}" ]; then
        return 1
    fi

    # 5. THE IDENTITY PAIR, recorded rather than merely confirmed.
    #    Everything above establishes that this pid IS the game NOW.
    #    Nothing above survives the pid being recycled between this
    #    check and a later SIGTERM, and a recycled pid is exactly the
    local identity
    identity="$(proc_identity "${pid}")" || return 1
    [ -n "${identity}" ] || return 1
    GAME_IDENTITY="${identity}"
    return 0
}

# pid_is_our_game PID -- the same question as pid_is_game, under the name the
# rest of this file asks it by.
pid_is_our_game() {
    pid_is_game "${1-}"
}

# read_game_pid [SPAWN_PID] -- the game's pid, from the window first.
read_game_pid() {
    local fallback="${1:-}"
    GAME_PID=""
    # find_game_window already verified this pid against the window it
    # chose, so prefer it and do not re-derive it.
    if [ -n "${WINDOW_OWNED_PID}" ] &&
       pid_is_game "${WINDOW_OWNED_PID}"; then
        GAME_PID="${WINDOW_OWNED_PID}"
        return 0
    fi
    if [ -n "${WINDOW_ID}" ]; then
        local from_window
        from_window="$(xdotool getwindowpid "${WINDOW_ID}" \
            2>/dev/null || true)"
        if pid_is_our_game "${from_window}"; then
            GAME_PID="${from_window}"
            return 0
        fi
    fi
    if pid_is_our_game "${fallback}"; then
        GAME_PID="${fallback}"
        return 0
    fi
    if [ -f "${PIDFILE}" ]; then
        # The file holds "PID START_TIME"; take the pid and let
        # pid_is_game re-derive the rest, so a truncated or hand-edited
        # line cannot smuggle anything past the identity check.
        local record from_file
        record="$(head -n 1 "${PIDFILE}" 2>/dev/null || true)"
        from_file="${record%% *}"
        if pid_is_game "${from_file}"; then
            GAME_PID="${from_file}"
            return 0
        fi
    fi
    GAME_PID=""
    GAME_IDENTITY=""
    return 1
}

# stop_instance PID TIMEOUT -- ask one confirmed game process to exit, and
# PROVE that it did. write_game_pidfile PID -- record the pid AND its start
# time.
write_game_pidfile() {
    local pid="${1-}"
    local start
    playthrough_secure_truncate "${PIDFILE}" || return 1
    start="$(proc_start_time "${pid}" 2>/dev/null || true)"
    printf '%s %s\n' "${pid}" "${start}" >"${PIDFILE}"
    return 0
}

# TERMINATION IS CONFIRMED, NEVER ASSUMED:
#
#   * an undeliverable SIGTERM is reported rather than discarded -- EPERM
#     (not our process) and ESRCH (already gone) are different facts;
#   * SIGKILL is followed by a BOUNDED WAIT, because a process in an
#     uninterruptible kernel sleep survives it for as long as that lasts;
#   * the pid file is removed ONLY on confirmed death, since it is the
#     record a caller needs to finish the job;
#   * the return status distinguishes the outcomes, so a caller stops
#     instead of letting seed_options.py rewrite options.json underneath a
#     live engine that would write its in-memory copy back at exit.
#
# stop_instance PID TIMEOUT -- ask one confirmed game process to exit.
stop_instance() {
    local pid="$1"
    playthrough_validate_int "${2:-30}" "stop timeout" 1 3600 ||
        return 1
    local timeout="${PLAYTHROUGH_INT}"
    if ! pid_is_game "${pid}"; then
        playthrough_warn "pid '${pid}' is not this checkout's" \
            "cataclysm-tiles process (checked against" \
            "${PLAYTHROUGH_GAME_BIN}, this working directory and" \
            "--userdir ${PLAYTHROUGH_USERDIR_ARG}); refusing to" \
            "signal it"
        return 1
    fi
    # The identity captured at the moment the pid was confirmed.
    local identity="${GAME_IDENTITY}"
    local ticks=$(( timeout * 4 ))
    local waited=0
    playthrough_log "sending SIGTERM to game pid ${pid}"
    # The pid was confirmed above; it is confirmed AGAIN here, because a
    # process can exit between the check and the kill and the number can
    # then be held by something entirely unrelated.
    if ! pid_has_identity "${pid}" "${identity}"; then
        playthrough_log "pid ${pid} had already exited before" \
            "SIGTERM was delivered; nothing was signalled"
        rm -f -- "${PIDFILE}"
        return 0
    fi
    if ! kill -TERM "${pid}" 2>/dev/null; then
        if pid_has_identity "${pid}" "${identity}"; then
            playthrough_warn "SIGTERM to pid ${pid} was refused but" \
                "the process is still the one identified, so it is" \
                "not ours to signal; leaving ${PIDFILE} in place as" \
                "evidence"
            return 1
        fi
        playthrough_log "pid ${pid} had already exited before" \
            "SIGTERM was delivered"
        rm -f -- "${PIDFILE}"
        return 0
    fi

    local killed=0
    # The wait is on the IDENTITY, not on `kill -0`: a recycled pid
    # answers kill -0 perfectly well, and waiting on it would report a
    # stranger's process as the game refusing to die.
    while pid_has_identity "${pid}" "${identity}"; do
        if [ "${waited}" -ge "${ticks}" ]; then
            playthrough_warn "pid ${pid} ignored SIGTERM for" \
                "${timeout}s; sending SIGKILL"
            # Re-checked once more: SIGKILL is unconditional for
            # whatever receives it, so it must not be sent on the
            # strength of a check made ${timeout} seconds ago.
            if ! pid_has_identity "${pid}" "${identity}"; then
                break
            fi
            if ! kill -KILL "${pid}" 2>/dev/null &&
               pid_has_identity "${pid}" "${identity}"; then
                playthrough_warn "could not send SIGKILL to pid" \
                    "${pid}; it has NOT been stopped"
                return 1
            fi
            killed=1
            break
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done

    if [ "${killed}" -eq 1 ]; then
        # A bounded confirmation window after SIGKILL.  Short, because
        # SIGKILL is not negotiable except against an uninterruptible
        # wait, and that is precisely the case worth reporting.
        local confirm=0
        while pid_has_identity "${pid}" "${identity}"; do
            if [ "${confirm}" -ge "${SIGKILL_CONFIRM_TICKS}" ]; then
                playthrough_warn "pid ${pid} is STILL ALIVE" \
                    "$(( SIGKILL_CONFIRM_TICKS / 4 ))s after" \
                    "SIGKILL, which normally means it is blocked in" \
                    "an uninterruptible kernel wait.  ${PIDFILE} is" \
                    "being kept so the pid is not lost.  Do not" \
                    "seed options or launch another instance until" \
                    "this process is gone."
                return 1
            fi
            sleep 0.25
            confirm=$(( confirm + 1 ))
        done
    fi

    # Confirmed dead: the identity no longer matches, so the process
    # that was identified is gone -- whether or not the NUMBER has since
    # been handed to something else.
    rm -f -- "${PIDFILE}"
    playthrough_log "game pid ${pid} has exited"
    return 0
}

# ---------------------------------------------------------------------
# STEP 5 -- the launch.
# ---------------------------------------------------------------------

# THE NEW GAME LIST HAS FIVE ENTRIES, AND ONLY THE FIRST IS PERMITTED.
# Quoted from src/main_menu.cpp:476-482 with hotkey markup stripped and
# spacing preserved:
#
#     "Custom Character"                <- the only permitted path (R10)
#     "Preset Character"                <- the character-template picker
#     "Random Character"
#     "Play Now!  (Default Scenario)"   <- TWO spaces after the "!"
#     "Play Now!"
#
# The last two appear only when map sharing is off, which it is here.  The
# SOURCE is the authority rather than the OCR, because the row under the
# cursor is drawn highlighted and reads back empty, and that label's two
# spaces collapse to one.
#
# AND THE PERMITTED ENTRY'S OWN HOTKEY TAKES THE WRONG DOOR.  The top row
# declares "T<u|U>torial Game" (src/main_menu.cpp:466) with the same "u" and
# "U" the submenu declares for "C<u|U>stom Character" (:476), and the top row
# wins: the submenu folds away and the highlight lands on the tutorial.  So
# the entry is taken by walking the top row with Left/Right to [New Game],
# READING the capture to see which submenu row carries the selection bar --
# its opening position is not guaranteed -- moving with Up/Down onto "Custom
# Character", and only then pressing Return.  session.py's
# MENU_CUSTOM_CHARACTER_ROUTE is that sequence.
#
# AND IT IS A REFUSAL, NOT A WARNING: a control that establishes a violation
# and then permits it is not a control.  session.py raises KeyRejected before
# the journal and before delivery -- so nothing happened and the session
# stays usable -- whenever all three of these hold: the key is "u" or "U",
# the caller's own action or commentary says it is meant for the custom
# sheet, and the observed UI phase is `menu`.  The phase is READ from the
# sidebar in the record rather than asserted, so an in-world "u" (the
# north-east step) is never refused.
#
# FIRST LAUNCH MAY ALSO NOT BE FULL SIZE.  The requested window size derives
# from TERMINAL_WIDTH * fontwidth by TERMINAL_HEIGHT * fontheight
# (src/sdltiles.cpp:595-596), and the compiled defaults TERMINAL_X 80 /
# TERMINAL_Y 24 (src/options.cpp:2408-2416) ask for a 640x384 window until
# screen-derived values exist in options.json.  Windowed-borderless can
# instead come up full size and have the engine recompute the render grid
# from the window it got (src/sdltiles.cpp:669-675).  Both outcomes are
# handled -- the small case by check_capture_geometry -- and neither is
# assumed, because it is the window manager's decision.
#
# So the FIRST launch is treated as THROWAWAY CALIBRATION: the game runs
# only long enough for the engine to create config/options.json, then stops,
# so that seed_options.py can patch that file without a running instance
# overwriting the patch on exit.  The NEXT launch is the one that is
# captured.  Calibration is skipped when a save already exists, so a
# resumable session is never interrupted for it -- and assert_seeded_options
# then proves the patch on the capture path regardless, because a file that
# exists is not a file that is right.
#
# launch_instance -- start one detached game process and wait for its
# window.  Sets WINDOW_ID, WINDOW_GEOMETRY and GAME_PID.
launch_instance() {
    assert_repo_root
    # Create frames/, build/, transitions/ and the userdir. env.sh owns these
    # paths; the engine creates save/ and config/ underneath the userdir
    # itself.
    playthrough_mkdirs ||
        die "${EX_LAYOUT}" "the artifact directories could not be" \
            "created inside the checkout; see the reason above"

    # The userdir is checked once more, by name, immediately before the engine
    # is pointed at it.
    playthrough_assert_inside "${PLAYTHROUGH_USERDIR}" \
        "${PLAYTHROUGH_REPO_ROOT}" "userdir" ||
        die "${EX_LAYOUT}" "refusing to launch with a userdir that" \
            "does not resolve inside the checkout"
    playthrough_assert_no_symlink "${PLAYTHROUGH_USERDIR}" \
        "${PLAYTHROUGH_REPO_ROOT}" "userdir" ||
        die "${EX_LAYOUT}" "refusing to launch with a symlinked" \
            "userdir component"

    # Both scratch files go through env.sh's guards rather than a bare
    # redirection: each path is predictable, this script truncates
    # both, and a symlink left at either name would send that write
    # somewhere else entirely.
    playthrough_secure_truncate "${PLAYTHROUGH_GAME_LOG}" ||
        die "${EX_LAYOUT}" "cannot prepare the game log" \
            "${PLAYTHROUGH_GAME_LOG}"
    playthrough_secure_file "${PIDFILE}" "the game pid file" ||
        die "${EX_LAYOUT}" "cannot prepare the pid file ${PIDFILE}"

    playthrough_log "launching" \
        "${PLAYTHROUGH_GAME_BIN_ARG} --userdir" \
        "${PLAYTHROUGH_USERDIR_ARG} from $(pwd) on" \
        "${PLAYTHROUGH_DISPLAY}; log: ${PLAYTHROUGH_GAME_LOG}"

    # THE DETACHMENT IDIOM, IN FULL: `setsid nohup ... </dev/null &`
    # followed by `disown`, so a signal to this shell's process group
    # misses the engine and no exit-time cleanup here can reach it.
    recheck_save_resume
    playthrough_child_close_fd ||
        die "${EX_LAYOUT}" "cannot prepare to detach the engine"
    # THE ENGINE'S OWN umask, SET HERE AND NOWHERE ELSE.
    # The engine creates the whole userdir tree itself -- save/, config/,
    # achievements/, templates/, cache/ -- and it does so with the ordinary
    # 0777/0666 creation modes, which means the umask it INHERITS decides who
    # may write to the survivor's save file.
    local previous_umask=""
    previous_umask="$(umask)"
    umask 022
    setsid nohup "${PLAYTHROUGH_GAME_BIN_ARG}" \
        --userdir "${PLAYTHROUGH_USERDIR_ARG}" \
        >>"${PLAYTHROUGH_GAME_LOG}" 2>&1 </dev/null \
        {PLAYTHROUGH_CHILD_CLOSE_FD}>&- \
        {PLAYTHROUGH_CHILD_CLOSE_FD2}>&- &
    local spawned="$!"
    umask "${previous_umask}"
    disown || true
    playthrough_child_close_done
    write_game_pidfile "${spawned}" ||
        die "${EX_LAYOUT}" "cannot record the game pid in ${PIDFILE}"

    if ! wait_for_game_window "${WINDOW_TIMEOUT}"; then
        tail_log "${PLAYTHROUGH_GAME_LOG}"
        # THE PROCESS IS ACCOUNTED FOR BEFORE THIS FAILS: an engine
        # that started but drew no window is stopped here, so it cannot
        # hold the userdir or overwrite a later options.json.
        local orphan_note="no game process could be identified"
        if read_game_pid "${spawned}"; then
            playthrough_log "no window appeared, but game pid" \
                "${GAME_PID} is running; stopping it before" \
                "reporting the timeout, so it cannot hold the" \
                "userdir or overwrite a later options.json"
            if stop_instance "${GAME_PID}" "${STOP_TIMEOUT}"; then
                orphan_note="the spawned process (pid ${GAME_PID}) \
was stopped and its exit verified"
            else
                orphan_note="the spawned process (pid ${GAME_PID}) \
could NOT be stopped and is still present -- stop it before capturing \
anything"
            fi
        else
            # Nothing to signal: the process is already gone, which is
            # itself the explanation for the missing window.
            rm -f -- "${PIDFILE}"
            orphan_note="the spawned process is already gone, so the \
engine started and exited before it could create a window"
        fi
        die "${EX_WINDOW}" "no window of class" \
            "'${PLAYTHROUGH_WINDOW_CLASS}' appeared on" \
            "${PLAYTHROUGH_DISPLAY} within ${WINDOW_TIMEOUT}s;" \
            "${orphan_note}.  Check the log above; note that" \
            "searching by window NAME would not find this window even" \
            "when it is there, and that a window whose owning process" \
            "is not this checkout's binary is deliberately not" \
            "accepted."
    fi

    if read_game_pid "${spawned}"; then
        write_game_pidfile "${GAME_PID}" || true
    else
        playthrough_warn "the window exists but its pid could not" \
            "be confirmed; leaving ${PIDFILE} at the spawn pid"
    fi

    if ! read_window_geometry; then
        playthrough_warn "could not read the geometry of window" \
            "${WINDOW_ID}"
    fi
    playthrough_log "window ${WINDOW_ID} is up at" \
        "${WINDOW_GEOMETRY:-unknown} (pid ${GAME_PID:-unknown})"

    assert_instance_alive
    return 0
}

# assert_instance_alive -- after a settle, re-confirm that the instance which
# produced the window is STILL running.
assert_instance_alive() {
    # Snapshot the pid AND the identity before the settle, because the
    # comparison afterwards has to be against the process that produced
    # the window and not merely against that pid number: an engine that
    # dies during data loading frees its pid, and something else on a
    # busy host can hold it by the time this check runs.
    local pid="${GAME_PID}"
    local identity="${GAME_IDENTITY}"
    sleep "${LIVENESS_SETTLE}"

    if [ -n "${pid}" ] && ! pid_has_identity "${pid}" "${identity}"; then
        tail_log "${PLAYTHROUGH_GAME_LOG}"
        rm -f -- "${PIDFILE}"
        die "${EX_WINDOW}" "the game process (pid ${pid}) was" \
            "gone ${LIVENESS_SETTLE}s after its window appeared:" \
            "the engine started and then exited, most likely while" \
            "loading data. See the log above."
    fi

    # IS OUR WINDOW STILL THERE? Asked as a WINDOW question only.
    local id still_listed=0
    if [ -n "${WINDOW_ID}" ]; then
        while IFS= read -r id; do
            if [ "${id}" = "${WINDOW_ID}" ]; then
                still_listed=1
                break
            fi
        done < <(game_window_ids)
    fi

    # A window that is genuinely no longer listed earns the fuller look: SDL
    # can replace its window, so the id may have changed rather than gone, and
    # find_game_window is what establishes that the replacement is still ours.
    if [ "${still_listed}" -eq 0 ] && ! find_game_window; then
        tail_log "${PLAYTHROUGH_GAME_LOG}"
        # The window is gone but the PROCESS may not be, and the same rule
        # applies here as at the window timeout: account for it before failing,
        # or it keeps the userdir and overwrites any later options.json on its
        # way out while nothing is left to find it.
        local vanish_note="its process is gone too"
        if pid_is_game "${GAME_PID}"; then
            if stop_instance "${GAME_PID}" "${STOP_TIMEOUT}"; then
                vanish_note="its process (pid ${GAME_PID}) was still \
running and has been stopped"
            else
                vanish_note="its process (pid ${GAME_PID}) is still \
running and could NOT be stopped"
            fi
        else
            rm -f -- "${PIDFILE}"
        fi
        die "${EX_WINDOW}" "the window of class" \
            "'${PLAYTHROUGH_WINDOW_CLASS}' vanished within" \
            "${LIVENESS_SETTLE}s of appearing on" \
            "${PLAYTHROUGH_DISPLAY}; ${vanish_note}. See the log" \
            "above."
    fi

    playthrough_log "instance still alive after" \
        "${LIVENESS_SETTLE}s (window ${WINDOW_ID}, pid" \
        "${GAME_PID:-unknown})"
    return 0
}

# emit_launch_facts -- the machine-readable half of a launch.
# verify_resume_ui_state -- prove a resumed session starts at a menu, and
# declare the ONE transaction it has to perform first.
verify_resume_ui_state() {
    local payload status clock phrase date_text
    INITIAL_UI_STATE="main-menu-load-required"
    # The highest permitted index, deliberately: a diagnostic capture is
    # withdrawn out of the tree and owed no row, and no session will ever reach
    # 99999, so this probe cannot collide with a real frame. AND NO DATE-AUDIT
    # ROW.
    payload="$(
        PLAYTHROUGH_CAPTURE_MODE=diagnostic \
        PLAYTHROUGH_CAPTURE_AUDIT=off \
        FRAME_INDEX=99999 \
        "${PLAYTHROUGH_DIR}/tooling/capture.sh" 2>/dev/null
    )" && status=0 || status=$?
    if [ "${status}" -eq "${EX_USAGE}" ]; then
        # AN INVOCATION THIS SCRIPT GOT WRONG IS NOT AN UNREADABLE SCREEN.
        die "${EX_USAGE}" "the diagnostic capture that checks the" \
            "starting screen REFUSED this script's own invocation" \
            "(exit ${EX_USAGE}: bad usage).  That is not a screen that" \
            "could not be read -- it is capture.sh and launch_game.sh" \
            "disagreeing about the diagnostic contract, and the resume" \
            "proof would be silently missing if this were reported as" \
            "'unverified'.  Run the invocation by hand to see the" \
            "refusal: PLAYTHROUGH_CAPTURE_MODE=diagnostic" \
            "PLAYTHROUGH_CAPTURE_AUDIT=off FRAME_INDEX=99999" \
            "playthrough/tooling/capture.sh"
    fi
    if [ "${status}" -ne 9 ]; then
        playthrough_warn "the diagnostic capture that checks the" \
            "starting screen exited ${status} rather than 9, so what" \
            "the engine is showing could not be read.  The resume" \
            "state is recorded as unverified; session.py still refuses" \
            "every new-survivor hotkey while it is on a menu."
        INITIAL_UI_STATE="unverified"
        return 0
    fi
    clock="$(printf '%s\n' "${payload}" |
        sed -n 's/^CLOCK=//p' | head -n 1)"
    phrase="$(printf '%s\n' "${payload}" |
        sed -n 's/^TIME_PHRASE=//p' | head -n 1)"
    date_text="$(printf '%s\n' "${payload}" |
        sed -n 's/^DATE=//p' | head -n 1)"
    if [ -n "${clock}${phrase}${date_text}" ]; then
        die "${EX_LAYOUT}" "the launch this session would be captured" \
            "from is ALREADY IN THE WORLD: the sidebar reads" \
            "clock='${clock}' phrase='${phrase}' date='${date_text}'." \
            "A resumed session has to begin at the main menu and load" \
            "world '${SAVE_WORLD}' through the game's own character" \
            "list, so that the load is itself captured, one frame per" \
            "keystroke.  Stop the engine (the 'stop' subcommand) and" \
            "run this again."
    fi
    playthrough_log "RESUME UI STATE verified: the engine is at a menu" \
        "(no sidebar reading), ${SAVE_CHAR_COUNT} character save(s)" \
        "exist in world '${SAVE_WORLD}', and the first captured" \
        "keystrokes must LOAD that character.  None of the five" \
        "new-survivor menu entries may be pressed: session.py refuses" \
        "u/U, p/P, r/R, d/D and o/O until a captured frame shows the" \
        "sidebar."
    return 0
}

emit_launch_facts() {
    emit PLAYTHROUGH_LAUNCH_PHASE "${LAUNCH_PHASE}"
    emit PLAYTHROUGH_INITIAL_UI_STATE "${INITIAL_UI_STATE}"
    emit PLAYTHROUGH_FIRST_RUN "${FIRST_RUN}"
    emit PLAYTHROUGH_WINDOW_ID "${WINDOW_ID}"
    emit PLAYTHROUGH_WINDOW_CLASS "${PLAYTHROUGH_WINDOW_CLASS}"
    emit PLAYTHROUGH_WINDOW_GEOMETRY "${WINDOW_GEOMETRY}"
    emit PLAYTHROUGH_GAME_PID "${GAME_PID}"
    emit PLAYTHROUGH_GAME_LOG \
        "$(playthrough_rel "${PLAYTHROUGH_GAME_LOG}")"
    emit PLAYTHROUGH_GAME_PIDFILE \
        "$(playthrough_rel "${PIDFILE}")"
    return 0
}

# check_capture_geometry -- confirm the capture surface, exactly, before a
# session is photographed from it.
check_capture_geometry() {
    local mode="${1:-strict}"
    local want_w=$(( PLAYTHROUGH_TERMINAL_X * PLAYTHROUGH_FONT_WIDTH ))
    local want_h=$(( PLAYTHROUGH_TERMINAL_Y * PLAYTHROUGH_FONT_HEIGHT ))
    local want="${want_w}x${want_h}"
    local want_y=$(( ( PLAYTHROUGH_SCREEN_HEIGHT - want_h ) / 2 ))

    if [ -z "${WINDOW_WIDTH}" ] || [ -z "${WINDOW_HEIGHT}" ]; then
        if [ "${mode}" = "strict" ]; then
            die "${EX_WINDOW}" "the game window's geometry could not" \
                "be read, so it is not known whether the capture" \
                "surface is usable.  This session would be" \
                "photographed without ever having verified what is" \
                "on screen, and an unreadable sidebar makes every" \
                "frame duration in the film come from an unreadable" \
                "clock.  Expected at least the ${want} grid implied" \
                "by TERMINAL_X ${PLAYTHROUGH_TERMINAL_X} /" \
                "TERMINAL_Y ${PLAYTHROUGH_TERMINAL_Y}.  Window id" \
                "was '${WINDOW_ID:-none}'."
        fi
        playthrough_warn "window geometry is unknown, so it could" \
            "not be compared with the ${want} grid implied by" \
            "TERMINAL_X ${PLAYTHROUGH_TERMINAL_X} /" \
            "TERMINAL_Y ${PLAYTHROUGH_TERMINAL_Y}"
        return 0
    fi

    if [ "${WINDOW_WIDTH}" -lt "${want_w}" ] ||
        [ "${WINDOW_HEIGHT}" -lt "${want_h}" ]; then
        if [ "${mode}" = "strict" ]; then
            die "${EX_WINDOW}" "window is ${WINDOW_GEOMETRY}," \
                "SMALLER than the ${want} grid implied by TERMINAL_X" \
                "${PLAYTHROUGH_TERMINAL_X} / TERMINAL_Y" \
                "${PLAYTHROUGH_TERMINAL_Y}, so this session must NOT" \
                "be captured from it: the frames would be mostly" \
                "black and the sidebar crop would miss the clock" \
                "entirely.  A 640x384 window means" \
                "${PLAYTHROUGH_OPTIONS_JSON} still holds the" \
                "compiled defaults TERMINAL_X 80 and TERMINAL_Y 24" \
                "(src/options.cpp:2408-2416).  Seed the options" \
                "file, stop this instance, and relaunch."
        fi
        playthrough_warn "window is ${WINDOW_GEOMETRY}, SMALLER than" \
            "the ${want} grid implied by TERMINAL_X" \
            "${PLAYTHROUGH_TERMINAL_X} / TERMINAL_Y" \
            "${PLAYTHROUGH_TERMINAL_Y}. A 640x384 window means" \
            "options.json still holds the compiled defaults" \
            "TERMINAL_X 80 and TERMINAL_Y 24" \
            "(src/options.cpp:2408-2416): seed the options file," \
            "then relaunch, before capturing anything."
        return 0
    fi

    # THE EXACT CONTRACT, for a launch a session is captured from: all
    # four numbers, because the sidebar crop, the clock region and every
    # duration in the film are computed from them.  width = TERMINAL_X *
    # FONT_WIDTH (240 * 8 = 1920), height = TERMINAL_Y * FONT_HEIGHT
    # (67 * 16 = 1072), x = 0 because the grid is painted from the left
    # edge, and y = (SCREEN_HEIGHT - height) / 2, the letterbox a
    # borderless window is centred in ((1080 - 1072) / 2 = 4).  The
    # advisory mode keeps the lower-bound behaviour, because its callers
    # are diagnosing rather than capturing.
    local centred_y="${want_y}"
    local geometry_a="${want}+0+${centred_y}"
    local geometry_b="${PLAYTHROUGH_SCREEN_WIDTH}x"
    geometry_b="${geometry_b}${PLAYTHROUGH_SCREEN_HEIGHT}+0+0"
    local matched=""
    if [ "${WINDOW_WIDTH}" = "${want_w}" ] &&
        [ "${WINDOW_HEIGHT}" = "${want_h}" ] &&
        [ "${WINDOW_X}" = "0" ] &&
        [ "${WINDOW_Y}" = "${centred_y}" ]; then
        matched="A (the grid, centred by the window manager)"
    elif [ "${WINDOW_WIDTH}" = "${PLAYTHROUGH_SCREEN_WIDTH}" ] &&
        [ "${WINDOW_HEIGHT}" = "${PLAYTHROUGH_SCREEN_HEIGHT}" ] &&
        [ "${WINDOW_X}" = "0" ] &&
        [ "${WINDOW_Y}" = "0" ]; then
        matched="B (borderless, given the whole root)"
    fi

    local -a wrong=()
    if [ -z "${matched}" ]; then
        # Named per number against BOTH candidates, so the refusal says
        # which number is wrong rather than printing geometry strings and
        # leaving the reader to diff them.
        [ "${WINDOW_X}" = "0" ] ||
            wrong+=("x offset ${WINDOW_X} (want 0 in either case)")
        [ "${WINDOW_WIDTH}" = "${want_w}" ] ||
            [ "${WINDOW_WIDTH}" = "${PLAYTHROUGH_SCREEN_WIDTH}" ] ||
            wrong+=("width ${WINDOW_WIDTH} (want ${want_w} for A or"
                    "${PLAYTHROUGH_SCREEN_WIDTH} for B)")
        [ "${WINDOW_HEIGHT}" = "${want_h}" ] ||
            [ "${WINDOW_HEIGHT}" = "${PLAYTHROUGH_SCREEN_HEIGHT}" ] ||
            wrong+=("height ${WINDOW_HEIGHT} (want ${want_h} for A or"
                    "${PLAYTHROUGH_SCREEN_HEIGHT} for B)")
        [ "${WINDOW_Y}" = "${centred_y}" ] || [ "${WINDOW_Y}" = "0" ] ||
            wrong+=("y offset ${WINDOW_Y} (want ${centred_y} for A or 0"
                    "for B)")
        if [ "${#wrong[@]}" -eq 0 ]; then
            wrong+=("the four numbers are individually plausible but"
                    "do not form either accepted geometry")
        fi
    fi

    if [ "${mode}" = "strict" ] && [ -z "${matched}" ]; then
        die "${EX_WINDOW}" "window is ${WINDOW_GEOMETRY}, and a" \
            "capture launch requires exactly ${geometry_a} (the grid," \
            "centred) or ${geometry_b} (borderless, the whole root)." \
            "Wrong: ${wrong[*]}." \
            "That geometry is the capture contract rather than a" \
            "preference: the width and height are the" \
            "${PLAYTHROUGH_TERMINAL_X}x${PLAYTHROUGH_TERMINAL_Y} grid" \
            "at ${PLAYTHROUGH_FONT_WIDTH}x${PLAYTHROUGH_FONT_HEIGHT}" \
            "cells (src/sdltiles.cpp:595-596), and the engine blits" \
            "that grid at the window's TOP-LEFT -- so the sidebar" \
            "crop, the clock region and therefore every duration in" \
            "the film are computed from all four numbers.  A window at" \
            "another size or offset paints the grid somewhere the crop" \
            "was not computed for.  Check" \
            "TERMINAL_X/TERMINAL_Y, FONT_WIDTH/FONT_HEIGHT," \
            "FULLSCREEN and SCALING_FACTOR in" \
            "${PLAYTHROUGH_OPTIONS_JSON} (seed_options.py writes and" \
            "verifies all six), confirm the window manager is the" \
            "openbox this pipeline starts, then stop this instance and" \
            "relaunch."
    fi

    if [ -n "${matched}" ]; then
        playthrough_log "window geometry ${WINDOW_GEOMETRY} matches" \
            "the capture contract exactly -- case ${matched}; the" \
            "${PLAYTHROUGH_TERMINAL_X}x${PLAYTHROUGH_TERMINAL_Y} grid" \
            "begins at the window's top-left, so the sidebar crop's y" \
            "is ${WINDOW_Y}"
    else
        playthrough_warn "window geometry ${WINDOW_GEOMETRY} covers" \
            "the ${want} grid but is neither ${geometry_a} nor" \
            "${geometry_b}; this is tolerated only because the mode is" \
            "advisory, and a capture launch would refuse it"
    fi
    return 0
}

# assert_capture_preconditions -- what must hold before an instance the session
# will be CAPTURED FROM is started or accepted.
assert_capture_preconditions() {
    if ! playthrough_assert_trusted \
            "to bring up the instance this session is captured from"; then
        die "${EX_USAGE}" "refusing the capture launch while the" \
            "trust state is '${PLAYTHROUGH_TRUST_STATE}'; the active" \
            "override(s) and what each one endangers are listed above."
    fi
    assert_seeded_options
}

# THE GRID IS NOT THE WINDOW, WHICH IS WHY THE VERIFIED LIST IS LONG.  The
# window those TERMINAL_* numbers become -- and therefore the rectangle the
# clock is cropped out of -- also depends on FONT_WIDTH and FONT_HEIGHT (the
# grid is TERMINAL_* times the FONT_* dimensions, src/sdltiles.cpp:595-596),
# on FULLSCREEN (which decides whether the window manager sizes the window
# at all, src/options.cpp:2715-2724), on SCALING_FACTOR and SCALING_MODE
# (which scale and resample it, src/options.cpp:2806-2825), on
# SIDEBAR_POSITION (which side the clock is on, src/options.cpp:2132-2136)
# and on the active sidebar layout in panel_options.json (which decides the
# column's width in cells, src/panels.cpp:412-418).  seed_options.py writes
# and verifies all fourteen values plus the layout and reports every
# mismatch in one failure, so this call covers the whole contract rather
# than half of it.
#
# A seed that failed halfway, was never run, ran against a different
# userdir, or was overwritten by an engine exiting afterwards leaves a file
# that exists and is WRONG while every downstream count still tallies -- a
# 12h clock in particular reads as one long series of unreadable clocks,
# collapsing every duration onto the 0.25 s floor.  So the contract is
# VERIFIED here by the module that owns it, through the interpreter env.sh
# verified.  Its stdout is captured rather than passed through, because this
# script's stdout is its own KEY=value contract and the observed values
# belong in the log.
#
# assert_seeded_options -- prove the option contract, never assume it.
assert_seeded_options() {
    local seeder="${PLAYTHROUGH_TOOLING_DIR}/seed_options.py"
    if [ ! -f "${seeder}" ]; then
        die "${EX_PREREQ}" "no ${seeder}, so the option values this" \
            "capture depends on cannot be verified.  It is part of" \
            "this pipeline: restore it before launching."
    fi
    if [ ! -f "${PLAYTHROUGH_OPTIONS_JSON}" ]; then
        die "${EX_LAYOUT}" "no ${PLAYTHROUGH_OPTIONS_JSON}, so" \
            "nothing has seeded the option values this capture" \
            "depends on.  Take the calibration launch first (it is" \
            "what makes the engine write that file), then run" \
            "'${PLAYTHROUGH_PYTHON} ${seeder}'."
    fi
    local observed=""
    local report="${PLAYTHROUGH_RUNTIME_DIR}/seed-verify.$$.err"
    if observed="$("${PLAYTHROUGH_PYTHON}" -B "${seeder}" \
            --verify-only \
            --options-json "${PLAYTHROUGH_OPTIONS_JSON}" \
            --repo-root "${PLAYTHROUGH_REPO_ROOT}" \
            --tileset "${TILESET_ID:-${PLAYTHROUGH_TILESET}}" \
            --terminal-x "${PLAYTHROUGH_TERMINAL_X}" \
            --terminal-y "${PLAYTHROUGH_TERMINAL_Y}" \
            2>"${report}")"; then
        # The observed values are the record of what this launch ran
        # under, so they are logged rather than discarded.
        local line
        while IFS= read -r line; do
            [ -n "${line}" ] || continue
            playthrough_log "verified ${line}"
        done <<<"${observed}"
        emit PLAYTHROUGH_OPTIONS_VERIFIED 1
        rm -f "${report}" 2>/dev/null || true
        return 0
    fi
    emit PLAYTHROUGH_OPTIONS_VERIFIED 0
    tail_log "${report}" 20
    rm -f "${report}" 2>/dev/null || true
    die "${EX_LAYOUT}" "${PLAYTHROUGH_OPTIONS_JSON} does not hold the" \
        "values this capture depends on -- the mismatches are listed" \
        "above.  Seed them with '${PLAYTHROUGH_PYTHON} ${seeder}'" \
        "while no engine is running (a live one rewrites the file when" \
        "it exits) and launch again.  Capturing a session against an" \
        "off-contract options file wastes the whole session: a 12h" \
        "clock alone makes every duration fall to the floor while" \
        "every count still tallies."
}

launch_game() {
    ensure_headless

    # THE SESSION LOCK covers the save probe, the reuse decision and the
    # process start as ONE operation: each of those steps reads state the next
    # one changes, so two interleaving invocations give two engines on one
    # userdir -- and the userdir is the save.
    playthrough_acquire_lock session "${WINDOW_TIMEOUT}" ||
        die "${EX_WINDOW}" "could not take the session lock; another" \
            "launch over this checkout is in flight"

    # AND THE CHECKOUT'S MUTATION LOCK, SHARED, for exactly the span this
    # function occupies.
    playthrough_acquire_mutation_lock shared "${WINDOW_TIMEOUT}" ||
        die "${EX_WINDOW}" "could not join THIS checkout's quiescence:" \
            "a gate or a checkpoint holds the mutation lock" \
            "exclusively, and starting the engine under one of those" \
            "would have it writing into the userdir while that stage" \
            "measured or committed it.  No engine was started."

    probe_save_resume

    FIRST_RUN=0
    if [ ! -f "${PLAYTHROUGH_OPTIONS_JSON}" ]; then
        FIRST_RUN=1
    fi

    # Idempotency: a game already on this display is reused, never
    # duplicated.  Two instances sharing one userdir would corrupt the
    # save and make the window search ambiguous.
    if find_game_window; then
        LAUNCH_PHASE="reused"
        # A REUSED INSTANCE IS AN INSTANCE THAT WILL BE CAPTURED, so the
        # capture preconditions are checked before anything is reported
        # about it -- accepting it is what this branch does.
        assert_capture_preconditions
        read_game_pid || true
        read_window_geometry || true
        playthrough_log "a window of class" \
            "'${PLAYTHROUGH_WINDOW_CLASS}' is already up on" \
            "${PLAYTHROUGH_DISPLAY} (id ${WINDOW_ID}, pid" \
            "${GAME_PID:-unknown}) and belongs to this checkout;" \
            "reusing it rather than starting a second instance"
        # find_game_window proved it is ours; nothing yet has proved it is
        # still responsive or big enough to capture, and no launch in this run
        # would have checked.
        assert_instance_alive
        settle_window_geometry
        check_capture_geometry strict
        emit_launch_facts
        return 0
    fi

    if [ "${FIRST_RUN}" -eq 1 ] && [ "${SESSION_MODE}" = "create" ]; then
        LAUNCH_PHASE="calibration"
        playthrough_log "CALIBRATION LAUNCH: no" \
            "${PLAYTHROUGH_OPTIONS_JSON} yet, so this launch is" \
            "throwaway -- it exists only so the engine writes the" \
            "config tree.  Expect a 640x384 window on a 'Select" \
            "your language' prompt."
        launch_instance
        if wait_for_file "${PLAYTHROUGH_OPTIONS_JSON}" 60; then
            playthrough_log "the engine created" \
                "${PLAYTHROUGH_OPTIONS_JSON}"
        else
            playthrough_log "${PLAYTHROUGH_OPTIONS_JSON} has not" \
                "appeared yet; the engine may only write it on exit," \
                "so the instance is stopped next and the file" \
                "re-checked afterwards"
        fi
        # THE CALIBRATION INSTANCE MUST BE GONE BEFORE OPTIONS ARE SEEDED, so a
        # failure to stop it is fatal rather than tolerated.
        local calibration_stopped=0
        if read_game_pid; then
            if stop_instance "${GAME_PID}" "${STOP_TIMEOUT}"; then
                calibration_stopped=1
            fi
        elif ! find_game_window; then
            # No identifiable process AND no window of ours: the
            # instance has genuinely gone, which is the state we want.
            calibration_stopped=1
            playthrough_log "the calibration instance has already" \
                "exited"
        else
            playthrough_warn "a window of this checkout's game is" \
                "still on ${PLAYTHROUGH_DISPLAY} but its pid could" \
                "not be confirmed, so the calibration instance" \
                "cannot be established as stopped"
        fi

        if [ "${calibration_stopped}" -ne 1 ]; then
            tail_log "${PLAYTHROUGH_GAME_LOG}"
            die "${EX_WINDOW}" "the calibration instance could not be" \
                "confirmed stopped.  It is still holding" \
                "${PLAYTHROUGH_USERDIR_ARG}, so anything seeded into" \
                "${PLAYTHROUGH_OPTIONS_JSON} now would be overwritten" \
                "when it eventually exits -- and a run captured under" \
                "the 12h default clock reads as one long series of" \
                "unreadable clocks while every count still tallies." \
                "Stop it (the 'stop' subcommand) and run this again."
        fi

        if [ ! -f "${PLAYTHROUGH_OPTIONS_JSON}" ] &&
           wait_for_file "${PLAYTHROUGH_OPTIONS_JSON}" 30; then
            playthrough_log "${PLAYTHROUGH_OPTIONS_JSON} was" \
                "written on exit"
        fi
        if [ ! -r "${PLAYTHROUGH_OPTIONS_JSON}" ]; then
            tail_log "${PLAYTHROUGH_GAME_LOG}"
            die "${EX_LAYOUT}" "the calibration launch produced no" \
                "readable ${PLAYTHROUGH_OPTIONS_JSON}, so there is" \
                "nothing for seed_options.py to patch -- it patches" \
                "the file the engine wrote and deliberately never" \
                "creates one.  The game log is above; a data-load" \
                "failure or a wrong --userdir is the usual cause."
        fi

        WINDOW_ID=""
        WINDOW_OWNED_PID=""
        WINDOW_GEOMETRY=""
        GAME_PID=""
        GAME_IDENTITY=""
        emit PLAYTHROUGH_CALIBRATION_OPTIONS \
            "$(playthrough_rel "${PLAYTHROUGH_OPTIONS_JSON}")"
        emit_launch_facts
        playthrough_log "NEXT: seed the option values" \
            "(24_HOUR=24h, SOUND_ENABLED=false," \
            "TILES=${TILESET_ID:-${PLAYTHROUGH_TILESET}}," \
            "TERMINAL_X=${PLAYTHROUGH_TERMINAL_X}," \
            "TERMINAL_Y=${PLAYTHROUGH_TERMINAL_Y}) into" \
            "${PLAYTHROUGH_OPTIONS_JSON}, then run this script" \
            "again to take the launch that is captured."
        return 0
    fi

    LAUNCH_PHASE="capture"
    assert_capture_preconditions
    if [ "${SESSION_MODE}" = "resume" ]; then
        playthrough_log "CAPTURE LAUNCH (resume): load world" \
            "'${SAVE_WORLD}' and continue the existing character;" \
            "do not create a new one"
    else
        playthrough_log "CAPTURE LAUNCH: create the survivor" \
            "through the custom point-buy creator"
        INITIAL_UI_STATE="main-menu-create-permitted"
    fi
    launch_instance
    settle_window_geometry
    check_capture_geometry strict
    # THE RESUME CONTRACT, established and verified AFTER the window is
    # up and its geometry confirmed -- the diagnostic capture below reads
    # the sidebar region of that window, so it needs both.
    if [ "${SESSION_MODE}" = "resume" ]; then
        verify_resume_ui_state
    fi
    emit_launch_facts
    return 0
}

# ---------------------------------------------------------------------
# Reporting and teardown subcommands.
# ---------------------------------------------------------------------

# report_status -- describe the current state and change nothing.
report_status() {
    assert_repo_root

    if read_game_version; then
        emit PLAYTHROUGH_GAME_BIN \
        "$(playthrough_rel "${PLAYTHROUGH_GAME_BIN}")"
        emit PLAYTHROUGH_GAME_VERSION "${GAME_VERSION}"
        if game_is_tiles; then
            emit PLAYTHROUGH_GAME_IS_TILES 1
        else
            emit PLAYTHROUGH_GAME_IS_TILES 0
            playthrough_warn "the binary does not report '+tiles'"
        fi
    else
        emit PLAYTHROUGH_GAME_BIN ""
        emit PLAYTHROUGH_GAME_IS_TILES 0
        playthrough_log "no binary yet; run the 'build' subcommand"
    fi

    # The interpreter is reported whatever its verdict, because "which
    # Python would have run" is a fact about this checkout that an
    # operator needs before a session and cannot otherwise see.
    read_interpreter_facts || true
    emit PLAYTHROUGH_PYTHON "${PLAYTHROUGH_PYTHON}"
    emit PLAYTHROUGH_PYTHON_PILLOW "${INTERPRETER_PILLOW}"
    emit PLAYTHROUGH_PYTHON_PREFLIGHT "${INTERPRETER_PREFLIGHT}"

    emit PLAYTHROUGH_DISPLAY "${PLAYTHROUGH_DISPLAY}"
    if playthrough_display_ready; then
        emit PLAYTHROUGH_DISPLAY_READY 1
        if playthrough_assert_display >/dev/null 2>&1; then
            emit PLAYTHROUGH_DISPLAY_GEOMETRY_OK 1
        else
            emit PLAYTHROUGH_DISPLAY_GEOMETRY_OK 0
            playthrough_warn "the display is up but is not" \
                "${PLAYTHROUGH_SCREEN}"
        fi
    else
        emit PLAYTHROUGH_DISPLAY_READY 0
        emit PLAYTHROUGH_DISPLAY_GEOMETRY_OK 0
    fi

    scan_installed_tilesets
    report_installed_tilesets
    emit PLAYTHROUGH_TILESET_INSTALLED_COUNT "${#TILESET_NAMES[@]}"
    # Reported, never resolved: `status` changes nothing, so a required
    # tileset that is absent is stated as absent here rather than
    # hydrated.  `tileset` or `all` is what installs it.
    if find_required_tileset "${PLAYTHROUGH_TILESET}"; then
        emit PLAYTHROUGH_TILESET_REQUIRED_PRESENT 1
    else
        emit PLAYTHROUGH_TILESET_REQUIRED_PRESENT 0
        playthrough_warn "the required tileset" \
            "'${PLAYTHROUGH_TILESET}' is not installed under gfx/;" \
            "run the 'tileset' subcommand to hydrate it from" \
            "'${TILESET_PACK}'"
    fi

    probe_save_resume

    if find_game_window; then
        read_game_pid || true
        read_window_geometry || true
        emit PLAYTHROUGH_GAME_RUNNING 1
    else
        WINDOW_ID=""
        WINDOW_OWNED_PID=""
        WINDOW_GEOMETRY=""
        GAME_PID=""
        GAME_IDENTITY=""
        emit PLAYTHROUGH_GAME_RUNNING 0
    fi
    LAUNCH_PHASE="status"
    emit_launch_facts
    return 0
}

# capture_evidence -- describe the recorded evidence this run has already
# produced, or print nothing when there is none.
capture_evidence() {
    local frames=0 rows=0 frame
    for frame in "${PLAYTHROUGH_FRAMES_DIR}"/frame_*.png; do
        [ -f "${frame}" ] || continue
        frames=$(( frames + 1 ))
    done
    if [ -s "${PLAYTHROUGH_MANIFEST}" ]; then
        rows="$(wc -l <"${PLAYTHROUGH_MANIFEST}" 2>/dev/null || \
            echo 0)"
        case "${rows}" in
            ''|*[!0-9]*) rows=0 ;;
        esac
    fi
    if [ "${frames}" -eq 0 ] && [ "${rows}" -eq 0 ]; then
        return 0
    fi
    printf '%s' "${frames} captured frame(s) and ${rows} manifest row(s)"
    return 0
}

# assert_stoppable -- refuse to signal anything once a run is recorded.
assert_stoppable() {
    local evidence
    evidence="$(capture_evidence)"
    if [ -z "${evidence}" ]; then
        return 0
    fi
    die "${EX_RECORDED}" "refusing to stop the game: this checkout" \
        "already holds ${evidence}, so a RECORDED session is in" \
        "progress.  A recorded session must end inside the game --" \
        "realistic sleep or death, then Save & Quit -- because that" \
        "is the only exit that writes the save.  Signalling the" \
        "process instead leaves save/<World>/ with no character" \
        "file, and the acceptance gate that requires a tracked" \
        "#<b64>.sav then refuses the whole run.  'stop' is for a" \
        "calibration or stuck instance from before the first frame" \
        "was captured."
}

# stop_game -- the operator-facing teardown, calibration instances only.
stop_game() {
    if ! find_game_window; then
        if [ -f "${PIDFILE}" ]; then
            local record stale
            record="$(head -n 1 "${PIDFILE}" 2>/dev/null || true)"
            stale="${record%% *}"
            if pid_is_game "${stale}"; then
                assert_stoppable
                playthrough_warn "no window found, but pid" \
                    "${stale} is still a game process of this" \
                    "checkout; stopping it"
                if ! stop_instance "${stale}" "${STOP_TIMEOUT}"; then
                    emit PLAYTHROUGH_GAME_RUNNING 1
                    die "${EX_WINDOW}" "pid ${stale} could not be" \
                        "stopped; it is still alive and ${PIDFILE}" \
                        "has been kept so the pid is not lost"
                fi
                emit PLAYTHROUGH_GAME_RUNNING 0
                return 0
            fi
            # The pid file names something that is not our game: the
            # instance it referred to is gone.  Removing it here is the
            # one safe case, because nothing is being signalled.
            playthrough_log "removing the stale pid file ${PIDFILE};" \
                "pid '${stale}' is not this checkout's game"
            rm -f -- "${PIDFILE}"
        fi
        playthrough_log "no game instance of this checkout is" \
            "running on ${PLAYTHROUGH_DISPLAY}; nothing to stop"
        emit PLAYTHROUGH_GAME_RUNNING 0
        return 0
    fi

    assert_stoppable
    playthrough_warn "stopping the game WITHOUT saving." \
        "A recorded session must instead end in-game with Save &" \
        "Quit, which is the only exit that writes the save." \
        "Nothing has been captured yet, so this is a calibration" \
        "or stuck instance."
    if ! read_game_pid; then
        # A window of ours with no resolvable pid is an unknown state,
        # and an unknown state is reported as still running: claiming
        # otherwise would be the fabrication this file exists to avoid.
        emit PLAYTHROUGH_GAME_RUNNING 1
        die "${EX_WINDOW}" "window ${WINDOW_ID} exists but no" \
            "confirmed game pid could be found, so nothing was" \
            "signalled and the instance is still running.  Nothing" \
            "here signals a process it has not confirmed."
    fi
    if ! stop_instance "${GAME_PID}" "${STOP_TIMEOUT}"; then
        emit PLAYTHROUGH_GAME_RUNNING 1
        die "${EX_WINDOW}" "game pid ${GAME_PID} could not be" \
            "confirmed stopped; it is still holding" \
            "${PLAYTHROUGH_USERDIR_ARG}, so do not seed options or" \
            "capture until it is gone"
    fi

    # Demonstrate the disappearance rather than assume it: the process
    # is gone AND no window of ours remains.
    if find_game_window; then
        emit PLAYTHROUGH_GAME_RUNNING 1
        die "${EX_WINDOW}" "game pid ${GAME_PID} exited but a window" \
            "of class '${PLAYTHROUGH_WINDOW_CLASS}' belonging to this" \
            "checkout is still on ${PLAYTHROUGH_DISPLAY} (id" \
            "${WINDOW_ID}, pid ${WINDOW_OWNED_PID}); another instance" \
            "is running"
    fi
    playthrough_log "the game instance is gone: no process and no" \
        "window of this checkout remain on ${PLAYTHROUGH_DISPLAY}"
    emit PLAYTHROUGH_GAME_RUNNING 0
    return 0
}

# guard_game -- hold the pipeline's state open from ONE FOREGROUND PROCESS, for
# an orchestrator that needs durability by design.

# assert_guardable -- refuse to watch a pid that was never confirmed.
assert_guardable() {
    if [ -z "${GAME_PID}" ]; then
        die "${EX_WINDOW}" "the instance is up but its pid was never" \
            "confirmed, so there is nothing to guard.  Nothing here" \
            "watches a process it has not identified."
    fi
    return 0
}

guard_game() {
    ensure_binary
    ensure_headless
    resolve_tileset
    probe_save_resume
    launch_game

    assert_guardable

    playthrough_log "GUARDING pid ${GAME_PID} in the foreground." \
        "This process now lives exactly as long as the game does;" \
        "keep it running for as long as you need the instance, and" \
        "end the session in-game with Save & Quit rather than by" \
        "signalling either process."
    emit PLAYTHROUGH_GUARD_PID "$$"

    while pid_is_our_game "${GAME_PID}"; do
        sleep "${LIVENESS_SETTLE}"
    done

    playthrough_log "guarded pid ${GAME_PID} has exited; the log is" \
        "${PLAYTHROUGH_GAME_LOG}"
    emit PLAYTHROUGH_GAME_RUNNING 0
    return 0
}

# usage -- printed on stdout for an explicit request and on stderr for
# a usage error.  This is the one thing that is not KEY=value, and it
# is only ever reached when the caller asked for prose.
usage() {
    local out="${1:-1}"
    {
        printf '%s\n' "usage: playthrough/tooling/launch_game.sh \
[subcommand]"
        printf '%s\n' ""
        printf '  %-10s %s\n' \
            "all" "build, headless, tileset, probe, launch (default)" \
            "build" "build if absent and prove the +tiles binary" \
            "headless" "bring up and verify the X surface" \
            "tileset" "install and verify the REQUIRED tileset" \
            "probe" "report the resume-versus-create decision" \
            "launch" "launch detached and wait for the window" \
            "guard" "as 'all', then stay in the foreground for as \
long as the game lives" \
            "status" "report current state, changing nothing" \
            "stop" "terminate a CALIBRATION instance, no save" \
            "help" "this text"
        printf '%s\n' ""
        printf '%s\n' "stdout carries KEY=value lines only; all \
logging goes to stderr."
        printf '%s\n' ""
        printf '%s\n' "'launch' detaches the game: it survives this \
shell, but not the"
        printf '%s\n' "container or a platform that reaps the process \
tree.  Use 'guard'"
        printf '%s\n' "when something must own the instance for its \
whole lifetime."
    } >&"${out}"
    return 0
}

# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------
main() {
    local subcommand="${1:-all}"
    if [ "$#" -gt 1 ]; then
        usage 2
        die "${EX_USAGE}" "exactly one subcommand is accepted, got:" \
            "$*"
    fi

    # `help` is answered before anything is validated, so that a
    # malformed tunable cannot stop an operator from reading the usage
    # that explains what the tunables are.
    case "${subcommand}" in
        help|-h|--help)
            usage 1
            return "${EX_OK}"
            ;;
    esac

    # Everything else runs only once every tunable has been validated
    # and normalised: the values are used in arithmetic, as sleep
    # operands and as loop bounds, so no path below may reach an
    # expansion with an unvalidated value in it.
    validate_tunables

    case "${subcommand}" in
        all)
            ensure_binary
            ensure_headless
            resolve_tileset
            probe_save_resume
            launch_game
            ;;
        guard)
            guard_game
            ;;
        build)
            ensure_binary
            ;;
        headless|env|display)
            ensure_headless
            ;;
        tileset|tilesets)
            resolve_tileset
            ;;
        probe|resume)
            assert_repo_root
            probe_save_resume
            ;;
        launch)
            ensure_binary
            resolve_tileset
            launch_game
            ;;
        status)
            report_status
            ;;
        stop)
            assert_repo_root
            stop_game
            ;;
        *)
            usage 2
            die "${EX_USAGE}" "unknown subcommand" \
                "'${subcommand}'"
            ;;
    esac
    return "${EX_OK}"
}

main "$@"
