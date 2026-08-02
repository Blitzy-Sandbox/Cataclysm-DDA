#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/launch_game.sh
#
# The launcher for the Cataclysm-DDA playthrough capture and
# cinematography pipeline.  It does five things, in this order, and
# every one of them is asserted rather than assumed:
#
#   1. BUILD the SDL tiles binary if ./cataclysm-tiles is absent, then
#      prove from the binary's own --version output that it really is
#      the tiles build and not the curses build.
#   2. BRING UP the headless X surface -- Xvfb plus a window manager --
#      only if it is not already serving, and assert that the root
#      window is exactly 1920x1080 at depth 24.
#   3. RESOLVE the tileset: prefer MSXotto+ when it is installed, or
#      can be installed from a pre-placed pack, and otherwise fall
#      back to the ASCIITiles that ship with the checkout.
#   4. PROBE for an existing save, so that a run which finds one
#      resumes it instead of replacing it.
#   5. LAUNCH the game fully detached from the repository root and wait
#      for its window BY CLASS.
#
# Nothing here plays the game.  session.py sends the keystrokes and
# capture.sh photographs the result; this script only establishes a
# reproducible, verified starting state and reports what it verified.
#
# USAGE
#     playthrough/tooling/launch_game.sh [subcommand]
#
#     all       (default) steps 1 to 5 above, in order
#     build     build if needed, then assert the +tiles binary
#     headless  bring up and verify the X surface only
#     tileset   resolve -- installing if needed -- the tileset only
#     probe     report the resume-versus-create decision only
#     launch    launch and wait for the window only
#     status    report the current state, changing nothing
#     stop      diagnostic teardown of a game instance this pipeline
#               started; read the warning on that function first
#     help      this text
#
# STDOUT IS A MACHINE CONTRACT
#     Every line printed on stdout is `KEY=value`, one per line, and
#     nothing else is ever written there: all logging, progress and
#     diagnostics go to stderr.  seed_options.py consumes
#     PLAYTHROUGH_TILESET_RESOLVED and session.py consumes
#     PLAYTHROUGH_WINDOW_ID and PLAYTHROUGH_SESSION_MODE, so the
#     channel has to stay clean enough to read with `grep '^KEY='`.
#     `help` is the one exception and says so where it is printed.
#
# EXIT CODES
#     0  success
#     1  usage error
#     2  not being run from inside a Cataclysm-DDA checkout
#     3  the build failed, or did not finish inside its timeout
#     4  the binary is not the SDL tiles build (no "+tiles")
#     5  no usable X display at the contracted geometry
#     6  no usable tileset could be resolved
#     7  the game window never appeared
#     8  a prerequisite is missing (env.sh, make, a compiler, a tool)
#
# TUNABLES -- all optional, all read from the environment
#     PLAYTHROUGH_BUILD_JOBS      make parallelism        (default 3)
#     PLAYTHROUGH_COMPILER        C++ compiler        (default g++-14)
#     PLAYTHROUGH_BUILD_TIMEOUT   seconds              (default 5400)
#     PLAYTHROUGH_BUILD_LOG       build log path
#     PLAYTHROUGH_WINDOW_TIMEOUT  seconds               (default 180)
#     PLAYTHROUGH_STOP_TIMEOUT    seconds                (default 30)
#     PLAYTHROUGH_LIVENESS_SETTLE seconds                 (default 2)
#     PLAYTHROUGH_TILESET_PACK    pre-placed tileset pack directory
#     PLAYTHROUGH_GAME_PIDFILE    pid file path
#     CLONE_INDEX                 read by env.sh; offsets the display
#                                 and every host-global scratch path
#                                 so parallel checkouts cannot collide
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
# Locate this file, then the repository root, then load the one
# definition of the environment.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8-9, adjusted for this file's depth
# of two directories rather than one.  env.sh performs the same
# resolution and exports the result as PLAYTHROUGH_REPO_ROOT, which is
# what everything below uses; the local copy exists only to find
# env.sh itself.
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
# SDL_VIDEODRIVER (x11, and the dummy video backend is banned there and
# here), SDL_AUDIODRIVER, LIBGL_ALWAYS_SOFTWARE, XDG_RUNTIME_DIR at
# mode 0700, PYTHONDONTWRITEBYTECODE -- and of every artifact path.
# None of it is restated in this file.  Sourcing it also defines the
# playthrough_* helpers used throughout: playthrough_log,
# playthrough_warn, playthrough_require_tools, playthrough_headless_up,
# playthrough_assert_display and playthrough_mkdirs.
#
# The `source=` directive below lets `shellcheck -x` follow env.sh and
# type-check every helper and variable used here against it, which is
# the invocation worth running.  SC1091 is suppressed only for a plain
# `shellcheck` run, which cannot follow a sourced file at all and would
# otherwise report the resolved path as unreadable; the file's presence
# is already asserted above, so nothing is being hidden.
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
#
# This is a source-level requirement of the engine, not a preference:
#
#   * src/main.cpp:415-425 routes `--userdir <path>` to
#     PATH_INFO::init_user_dir( params[0] ) followed by
#     PATH_INFO::set_standard_filenames().
#   * src/path_info.cpp:105 `user_dir_value = as_norm_dir( dir );`
#     normalises but does NOT absolutise, so `./playthrough/userdir/`
#     resolves against the process working directory.
#   * src/path_info.cpp:144 `savedir_value = user_dir_value + "save/";`
#     therefore puts the save at playthrough/userdir/save/<World>/ --
#     inside the working tree, where git can track it.
#   * With an empty --basepath the asset roots are working-directory
#     relative too: :129 `datadir_value = "data/";`, :134
#     `gfxdir_value = prefix + "gfx/";`, :136 `langdir_value = prefix +
#     "lang/mo/";`.
#
# So the repository root is the only directory under which this
# checkout's own data/, gfx/ and lang/mo/ resolve AND the userdir lands
# somewhere committable.  Any other choice breaks both halves at once.
# ---------------------------------------------------------------------
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# Exit codes, named so that the call sites read as intent.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_LAYOUT=2
readonly EX_BUILD=3
readonly EX_NOT_TILES=4
readonly EX_DISPLAY=5
readonly EX_TILESET=6
readonly EX_WINDOW=7
readonly EX_PREREQ=8

# ---------------------------------------------------------------------
# Tunables.  Host-global scratch paths carry the same per-checkout
# suffix env.sh uses for its own logs, so two clones running at once
# cannot overwrite each other's diagnostics.
# ---------------------------------------------------------------------
if [ "${PLAYTHROUGH_CLONE_INDEX}" -eq 0 ]; then
    _lg_suffix=""
else
    _lg_suffix="${PLAYTHROUGH_CLONE_INDEX}"
fi

BUILD_JOBS="${PLAYTHROUGH_BUILD_JOBS:-3}"
BUILD_TIMEOUT="${PLAYTHROUGH_BUILD_TIMEOUT:-5400}"
BUILD_LOG="${PLAYTHROUGH_BUILD_LOG:-/tmp/cata-build${_lg_suffix}.log}"
BUILD_STATUS="${BUILD_LOG}.status"
BUILD_PIDFILE="${BUILD_LOG}.pid"
# The $0 given to the detached build's inner shell.  It is how a later
# run recognises a build of its own still in flight, so it can wait for
# that one instead of racing a second make against the same tree.
readonly BUILD_TAG="launch_game_build"
WINDOW_TIMEOUT="${PLAYTHROUGH_WINDOW_TIMEOUT:-180}"
STOP_TIMEOUT="${PLAYTHROUGH_STOP_TIMEOUT:-30}"
LIVENESS_SETTLE="${PLAYTHROUGH_LIVENESS_SETTLE:-2}"
TILESET_PACK="${PLAYTHROUGH_TILESET_PACK:-/opt/cdda-gfx-cache}"
PIDFILE="${PLAYTHROUGH_GAME_PIDFILE:-/tmp/cata-play${_lg_suffix}.pid}"
unset _lg_suffix

# ---------------------------------------------------------------------
# Results.  Functions here set globals rather than echoing values,
# because a `$( ... )` capture runs in a subshell where `exit` from the
# die() below would exit only that subshell and be swallowed.  Globals
# keep every failure fatal to the whole script, which is the point.
# ---------------------------------------------------------------------
COMPILER_BIN=""
BUILD_RUNNING_PID=""
GAME_VERSION=""
GAME_VERSION_ALL=""
TILESET_ID=""
TILESET_VIEW=""
TILESET_DIR=""
TILESET_ORIGIN=""
TILESET_NAMES=()
TILESET_VIEWS=()
TILESET_DIRS=()
SESSION_MODE=""
SAVE_WORLD=""
SAVE_WORLD_COUNT=0
SAVE_CHAR_COUNT=0
WINDOW_ID=""
WINDOW_GEOMETRY=""
WINDOW_WIDTH=""
WINDOW_HEIGHT=""
GAME_PID=""
LAUNCH_PHASE=""
FIRST_RUN=0
PROBE_DONE=0
HEADLESS_DONE=0

# ---------------------------------------------------------------------
# Reporting.
#
# die() deliberately does not call env.sh's playthrough_die: that
# function RETURNS 1 by design, because env.sh is sourced and an `exit`
# there would kill an interactive caller's shell.  Here an exit with a
# specific, documented code is exactly what is wanted, so the message
# is printed directly in the same format.
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

# wait_for_file PATH TIMEOUT_SECONDS -- bounded poll, never a fixed
# sleep, so a fast host is not penalised and a slow one is not
# truncated.
wait_for_file() {
    local path="$1"
    local timeout="$2"
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
# STEP 0 -- prove we really are at the root of a Cataclysm-DDA
# checkout.
#
# Everything after this depends on relative paths resolving against the
# working directory (see WORKING DIRECTORY above), so the cheapest
# possible mistake -- being one directory off -- has to be caught here
# rather than surfacing later as an empty save or a black frame.
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
# Warn -- loudly, and by name -- if the build left anything that git
# would consider a change outside playthrough/.
#
# This is a warning rather than a fatal error on purpose: an operator
# with unrelated local edits should not be blocked from launching, and
# a false failure here would be worse than an unmissable message.  A
# clean build genuinely reports nothing, because every product of it is
# already ignored: cataclysm-tiles (.gitignore:75), /obj/
# (.gitignore:60), /src/version.h (.gitignore:63) and
# /lang/mo_built.stamp (.gitignore:148).  Tilesets installed under
# gfx/ are ignored by /gfx/* (.gitignore:52) too, which is why
# installing one needs no change to .gitignore and gets none.
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
#
# THE BINARY IS ABSENT FROM A FRESH CHECKOUT.  `.gitignore:75` is
# `*cataclysm-tiles`, so it is never committed and never arrives with a
# clone; this script builds it.  Do not "optimise" the probe away on
# the assumption that it is there.
# ---------------------------------------------------------------------

# resolve_compiler -- pick the C++ compiler, honouring an override.
#
# g++-14 is preferred because doc/c++/COMPILER_SUPPORT.md states the
# project aims to support GCC and clang "up to the newest stable
# versions" while keeping 9.3 as the floor, and the engine compiles
# against -std=c++17 (Makefile:533), so a modern GCC is squarely
# inside the supported range.  Plain g++ is accepted as a fallback so
# that a host without the versioned package still builds.
resolve_compiler() {
    local candidate
    if [ -n "${PLAYTHROUGH_COMPILER:-}" ]; then
        if ! command -v "${PLAYTHROUGH_COMPILER}" >/dev/null 2>&1; then
            playthrough_warn "PLAYTHROUGH_COMPILER" \
                "'${PLAYTHROUGH_COMPILER}' is not on PATH"
            return 1
        fi
        COMPILER_BIN="${PLAYTHROUGH_COMPILER}"
        return 0
    fi
    for candidate in g++-14 g++; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            COMPILER_BIN="${candidate}"
            return 0
        fi
    done
    return 1
}

# build_binary -- run the one sanctioned build command, detached.
#
# THE FLAGS, AND WHY EACH ONE IS LOAD-BEARING
#
#   SDL3=0     MANDATORY on every make invocation in this file.
#              Makefile:791-795 defaults SDL3=1 whenever TILES=1,
#              Makefile:800 then adds -DUSE_SDL3, and Makefile:811-816
#              raises a hard `$(error SDL3 >= 3.4.0 required for the
#              GPU shader path ...)` when pkg-config cannot satisfy
#              that version.  It is an error, not a warning: without
#              SDL3=0 the build does not degrade, it aborts.  The
#              fallback is the project's own documented one --
#              doc/c++/COMPILING.md:83 "SDL3=0 - use the SDL2 fallback
#              for tiles builds" and :232 for Debian/Ubuntu releases
#              that do not package a new enough SDL3.
#   RELEASE=1  Optimised build (Makefile:33).
#   TILES=1    The SDL tiles build (Makefile:35).  This is the whole
#              point: the curses build must never be substituted.
#   SOUND=1    Requires TILES (Makefile:37); the device itself is
#              muted at run time by SDL_AUDIODRIVER=dummy from env.sh
#              and by SOUND_ENABLED=false in the seeded options.
#   ASTYLE=0   Skip the source restyle (Makefile:88).  This tree's C++
#              is not touched, so there is nothing to style.
#   LINTJSON=0 Skip the JSON format check (Makefile:90).  No JSON in
#              this tree is touched either.
#   CCACHE=1   Reuse the compilation cache; Makefile:408-414 wires
#              ccache in front of the resolved compiler.
#   -j3        NOT -j$(nproc).  This host has far more CPUs than it
#              has memory per CPU, and a wide build is OOM-killed.
#              Three is the value that completes here.  Override with
#              PLAYTHROUGH_BUILD_JOBS on a roomier machine.
#   COMPILER=  The deterministic compiler knob: Makefile:400-410 sets
#              OS_COMPILER := $(COMPILER) when COMPILER is non-empty
#              and only falls back to $(CXX) otherwise, and :409 then
#              reassigns CXX itself.  CXX is exported as well, which
#              is the form the pipeline's own instructions use and
#              which the same lines honour; both name one compiler, so
#              they cannot disagree.
#
# FLAGS THAT MUST NEVER BE PASSED -- the mentions below are comments
# explaining a prohibition, never arguments:
#
#   TESTS=0          Explicitly forbidden.  Makefile:91-92 documents
#                    it; the test binary stays part of the build.
#   NATIVE=linux64   Must not be passed on ARM64 hosts.
#   USE_XDG_DIR=1    Both are opt-in at Makefile:1211-1222 and both
#   USE_HOME_DIR=1   are fatal here for a source-level reason:
#                    src/path_info.cpp:153-166 is
#                    `#if defined(USE_XDG_DIR) ... #else
#                    config_dir_value = user_dir_value + "config/";
#                    #endif`, so either flag moves config/ out of the
#                    userdir entirely.  options.json and
#                    keybindings.json would then never land under
#                    playthrough/userdir/config/, which would silently
#                    break option seeding and destroy the committed
#                    evidence that no debug action was ever bound.
#
# No file under src/ is edited to make this build succeed.  The one
# C++ change the SDL2 path is known to need -- the
# get_shared_variant_pass guard -- is already applied at both
# construction sites, src/pixel_minimap.cpp:283-287 and :475-479.

# build_in_progress -- true when a make THIS script started is still
# running over this object tree.
#
# This is what makes the build path idempotent, and it is not
# theoretical: two concurrent makes over one obj/ tree fight over the
# same .o files, and running six compilers on a host sized for three
# exhausts its memory.  A second run therefore waits for the first.
#
# The pid recorded is MAKE's, not the wrapper shell's, and that
# distinction was learned the hard way here: when an outer session is
# torn down the wrapper shell can die while make carries on, so a guard
# that watched the wrapper would declare the tree free while a build was
# still writing to it.  Identity is then confirmed two ways --
# /proc/<pid>/cmdline really is make, and /proc/<pid>/cwd really is this
# repository root -- so a make belonging to another checkout, or an
# unrelated process that inherited a recycled pid, can never be
# mistaken for ours.
build_in_progress() {
    BUILD_RUNNING_PID=""
    [ -f "${BUILD_PIDFILE}" ] || return 1
    local pid
    pid="$(head -n 1 "${BUILD_PIDFILE}" 2>/dev/null || true)"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ -r "/proc/${pid}/cmdline" ] || return 1
    local cmd
    cmd="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    case "${cmd}" in
        *make*) ;;
        *) return 1 ;;
    esac
    local cwd
    cwd="$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)"
    if [ "${cwd}" != "${PLAYTHROUGH_REPO_ROOT}" ]; then
        return 1
    fi
    BUILD_RUNNING_PID="${pid}"
    return 0
}

build_binary() {
    playthrough_require_tools make ||
        die "${EX_PREREQ}" "make is required to build the tiles" \
            "binary and is not on PATH"
    resolve_compiler ||
        die "${EX_PREREQ}" "no C++ compiler found; install g++-14" \
            "(preferred) or g++, or set PLAYTHROUGH_COMPILER"

    if build_in_progress; then
        playthrough_log "a build started by this script is still" \
            "running (pid ${BUILD_RUNNING_PID}); waiting for that" \
            "one rather than racing a second make over the same" \
            "object tree.  Log: ${BUILD_LOG}"
    else
        playthrough_log "building ./cataclysm-tiles with" \
            "${COMPILER_BIN}, -j${BUILD_JOBS}, SDL2 fallback" \
            "(SDL3=0); log: ${BUILD_LOG}"
        playthrough_log "a cold build takes roughly 25 minutes on" \
            "this class of host; progress is reported every 30s"

        rm -f -- "${BUILD_STATUS}" "${BUILD_PIDFILE}"
        : >"${BUILD_LOG}"

        # Detached with setsid so the build is not killed when the
        # calling shell's process group is signalled -- a real failure
        # mode: a make run here has been terminated by Interrupt,
        # neither OOM nor a compile error, purely because an outer call
        # timed out.
        #
        # The exit status is written to a sentinel file by the inner
        # shell rather than collected with `wait`, because setsid may
        # fork, in which case `wait` would report setsid's status and
        # not make's.  The inner shell receives the command as separate
        # arguments and runs it with "$@": there is no eval and no
        # string interpolation of a command line anywhere in this file.
        #
        # The inner shell backgrounds make and records ITS pid, then
        # waits for it, so build_in_progress above watches the process
        # that actually owns the object tree.
        #
        # SC2016 is suppressed deliberately: $1, $2, $@, $!, $? inside
        # the single-quoted body MUST reach the inner shell unexpanded
        # -- they are that shell's own parameters, its child's pid and
        # its child's exit status.  Double quotes would expand them
        # here, in the wrong shell, and would break exactly the status
        # capture this exists for.
        # shellcheck disable=SC2016
        setsid nohup bash -c '
            status_file="$1"
            pid_file="$2"
            shift 2
            "$@" &
            child=$!
            printf "%s\n" "${child}" >"${pid_file}"
            wait "${child}"
            printf "%s\n" "$?" >"${status_file}"
        ' "${BUILD_TAG}" "${BUILD_STATUS}" "${BUILD_PIDFILE}" \
            env "CXX=${COMPILER_BIN}" make "-j${BUILD_JOBS}" \
            RELEASE=1 TILES=1 SOUND=1 SDL3=0 ASTYLE=0 LINTJSON=0 \
            CCACHE=1 "COMPILER=${COMPILER_BIN}" \
            >>"${BUILD_LOG}" 2>&1 </dev/null &
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
#
# Measured output on this build, which is why it is flattened rather
# than read line by line:
#
#     Cataclysm Dark Days Ahead: b8bf5491a2
#     <blank>
#     +tiles, +sound
#     <blank>
#     data dir: data/
#     user dir: ./
#
# The version and the feature markers are on DIFFERENT lines, so
# taking only the first line would throw away the "+tiles" marker --
# the one string that constitutes the proof.  GAME_VERSION_ALL is
# therefore the whole output flattened to a single line and is what the
# marker test runs against, while GAME_VERSION is that same line with
# the resolved-directory tail trimmed off: identity and evidence, no
# noise.  Trimming degrades safely -- if the tail's wording ever
# changes, GAME_VERSION simply keeps a little more text and never loses
# the marker.
#
# --version is answered while the command line is still being parsed,
# before any window is created, so this needs no display.  stderr is
# folded in because a diagnostic must not be allowed to hide the
# banner, and each substitution is wrapped so that a non-zero exit
# cannot trip `set -o pipefail`.
read_game_version() {
    GAME_VERSION=""
    GAME_VERSION_ALL=""
    [ -x "${PLAYTHROUGH_GAME_BIN}" ] || return 1
    local raw
    raw="$( { "${PLAYTHROUGH_GAME_BIN}" --version 2>&1 || true; } )"
    GAME_VERSION_ALL="$(printf '%s\n' "${raw}" |
        tr '\n' ' ' |
        sed 's/[[:space:]]\{1,\}/ /g; s/^ //; s/ $//')"
    GAME_VERSION="$(printf '%s' "${GAME_VERSION_ALL}" |
        sed 's/ data dir:.*$//')"
    if [ -z "${GAME_VERSION}" ]; then
        GAME_VERSION="${GAME_VERSION_ALL}"
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

# assert_tiles_binary -- the tiles-versus-curses proof.
#
# The rule is that the SDL tiles binary is played and the curses build
# is never accepted as a substitute, and the binary settles it from its
# own mouth: a tiles build reports "+tiles" (and, with SOUND=1,
# "+sound") in its --version output.  Nothing else is trusted here --
# not the file name, not the presence of gfx/, not the flags we think
# we passed.  Note that the rule is about the BINARY, not the artwork:
# a build linked against SDL2 and rendering through the SDL tiles path
# satisfies it even when the selected tileset is ASCIITiles.
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

    # --version is handled while the command line is still being
    # parsed, before any window is created, so this probe needs no
    # display.  stderr is folded in because a diagnostic must not be
    # allowed to hide the version string, and the pipeline is wrapped
    # so that a non-zero exit cannot trip `set -o pipefail`.
    if ! read_game_version; then
        die "${EX_NOT_TILES}" "${PLAYTHROUGH_GAME_BIN}" \
            "--version printed nothing; it cannot be verified as" \
            "the SDL tiles build"
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
    emit PLAYTHROUGH_GAME_BIN "${PLAYTHROUGH_GAME_BIN}"
    emit PLAYTHROUGH_GAME_VERSION "${GAME_VERSION}"
    return 0
}

# ---------------------------------------------------------------------
# STEP 2 -- the headless surface.
#
# The work is delegated to env.sh, which owns it: playthrough_headless_up
# asserts SDL_VIDEODRIVER is x11 (the dummy video backend renders zero
# pixels and would silently produce an entirely black movie, so it is
# banned there and never named as a value here), starts Xvfb at
# 1920x1080x24 ONLY IF the display is not already answering, starts
# openbox ONLY IF no window manager owns the display, and then asserts
# the root window really is 1920x1080 at depth 24 via xdpyinfo.
#
# Delegating is what makes the whole pipeline idempotent and what lets
# an externally managed X server -- a container sidecar, say -- be
# reused rather than fought with: the start functions are no-ops when
# the display already answers.  The window manager is load-bearing, not
# cosmetic: a bare X server has no focus model and xdotool key delivery
# to an unfocused window is unreliable, which would break the strict
# one-keystroke-per-frame invariant the capture depends on.
#
# The geometry is asserted rather than assumed because capture targets
# the X ROOT window: the root is exactly 1920x1080 while the game
# window occupies 1920x1072 at +0+4 (240 columns x 8 px by 67 rows x
# 16 px, derived per src/sdltiles.cpp:595-596 with FULLSCREEN
# defaulting to windowed borderless, src/options.cpp:2715-2724).
# Photographing the root yields a true-resolution PNG with a 4-pixel
# letterbox and needs no rescaling -- and rescaling would soften
# exactly the 8x16 glyphs the sidebar clock OCR has to read.
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
# STEP 3 -- the tileset, resolved as preference with fallback.
#
# The requirement set contains a genuine tension: one part asks for the
# CDDA-Tilesets pack with MSXotto+ selected, another specifies the
# ASCIITiles that ship with the checkout.  Both are satisfied by
# preferring MSXotto+ when it is available and falling back to
# ASCIITiles when it is not, and by REPORTING which one was actually
# used so the choice is recorded rather than assumed.  Either outcome
# satisfies the tiles-binary rule, which is about the binary reporting
# "+tiles" and not about the artwork pack.
#
# A tileset's identity comes from the NAME: field of its tileset.txt,
# not from its directory name -- src/options.cpp:1213-1227 reads NAME:
# as the option value and VIEW: only as the label shown in the menu, so
# the directory gfx/ASCIITileset declares the id ASCIITiles and
# gfx/MShockXotto+ declares MshockXottoplus with the view MSXotto+.
# Every lookup below therefore scans those fields and accepts a match
# on either, and no directory name is ever guessed.
#
# Installing a tileset writes into gfx/, which is deliberate and
# produces no tracked change at all: /gfx/* is ignored at
# .gitignore:52 with only four negations at :53-56, so an installed
# pack is invisible to git.  .gitignore is NOT edited to change that.
#
# The source is a PRE-PLACED pack directory, by default
# /opt/cdda-gfx-cache -- the operator's provisioned copy of
# https://github.com/I-am-Erk/CDDA-Tilesets.  This script never fetches
# anything: the pipeline opens no network connection, a download has no
# place on the critical path of a re-run, and a missing pack is a
# fallback rather than a failure.
# ---------------------------------------------------------------------

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

# scan_installed_tilesets -- inventory gfx/ into the three parallel
# arrays.  The glob's variable part is quoted and only the pattern
# itself is bare; a directory with no tileset.txt is skipped rather
# than assumed.
scan_installed_tilesets() {
    TILESET_NAMES=()
    TILESET_VIEWS=()
    TILESET_DIRS=()
    local dir conf name view
    for dir in "${PLAYTHROUGH_REPO_ROOT}/gfx"/*/; do
        [ -d "${dir}" ] || continue
        conf="${dir}tileset.txt"
        [ -f "${conf}" ] || continue
        name="$(tileset_field "${conf}" NAME || true)"
        [ -n "${name}" ] || continue
        view="$(tileset_field "${conf}" VIEW || true)"
        TILESET_NAMES+=("${name}")
        TILESET_VIEWS+=("${view}")
        TILESET_DIRS+=("${dir%/}")
    done
    return 0
}

# find_installed_tileset WANTED -- match on NAME or VIEW, exactly.
# Comparison is a literal string test, never a pattern: real ids
# contain characters such as '+' that a regular expression would
# mis-read.
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

# install_tileset_from_pack WANTED -- copy one tileset out of the
# pre-placed pack.  Bounded (one directory, one copy), explicit, and
# non-fatal: every failure path returns 1 so the caller can fall back,
# because falling back is a correct outcome and not an error.
install_tileset_from_pack() {
    local wanted="$1"
    if [ ! -d "${TILESET_PACK}" ]; then
        playthrough_log "no pre-placed tileset pack at" \
            "'${TILESET_PACK}'; nothing to install from"
        return 1
    fi
    local dir conf name view base dest tmp
    for dir in "${TILESET_PACK}"/*/; do
        [ -d "${dir}" ] || continue
        conf="${dir}tileset.txt"
        [ -f "${conf}" ] || continue
        name="$(tileset_field "${conf}" NAME || true)"
        view="$(tileset_field "${conf}" VIEW || true)"
        if [ "${name}" != "${wanted}" ] &&
           [ "${view}" != "${wanted}" ]; then
            continue
        fi
        base="$(basename "${dir%/}")"
        dest="${PLAYTHROUGH_REPO_ROOT}/gfx/${base}"
        if [ -e "${dest}" ]; then
            playthrough_log "gfx/${base} already exists; leaving" \
                "it exactly as it is"
            return 0
        fi
        # Copy aside and rename, so an interrupted copy can never
        # leave a half-populated tileset that later scans would treat
        # as installed.
        tmp="${PLAYTHROUGH_REPO_ROOT}/gfx/.${base}.partial.$$"
        playthrough_log "installing tileset '${name}' from" \
            "${dir} into gfx/${base}"
        if cp -a "${dir%/}" "${tmp}" 2>/dev/null &&
           mv -- "${tmp}" "${dest}"; then
            return 0
        fi
        playthrough_warn "could not install '${name}' into gfx/;" \
            "continuing with whatever is already installed"
        # Remove only the partial directory this call created, named
        # in full and confirmed to be the intended path first.
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

resolve_tileset() {
    assert_repo_root
    local preferred="${PLAYTHROUGH_TILESET}"
    local fallback="${PLAYTHROUGH_TILESET_FALLBACK}"

    scan_installed_tilesets
    if find_installed_tileset "${preferred}"; then
        TILESET_ORIGIN="preferred-installed"
    else
        playthrough_log "preferred tileset '${preferred}' is not" \
            "installed under gfx/; trying the pre-placed pack"
        if install_tileset_from_pack "${preferred}"; then
            scan_installed_tilesets
        fi
        if find_installed_tileset "${preferred}"; then
            TILESET_ORIGIN="preferred-from-pack"
        elif find_installed_tileset "${fallback}"; then
            TILESET_ORIGIN="fallback"
            playthrough_warn "'${preferred}' is unavailable;" \
                "falling back to '${TILESET_ID}', which ships with" \
                "the checkout.  This is a correct outcome, and the" \
                "movie is still a genuine SDL tiles capture --" \
                "record it in playthrough/TECHNICAL_NOTES.md."
        else
            report_installed_tilesets
            die "${EX_TILESET}" "neither the preferred tileset" \
                "'${preferred}' nor the fallback '${fallback}' is" \
                "installed under gfx/, and neither could be" \
                "installed from '${TILESET_PACK}'.  The game cannot" \
                "render tiles without one."
        fi
    fi

    playthrough_log "tileset resolved: id='${TILESET_ID}'" \
        "view='${TILESET_VIEW}' origin=${TILESET_ORIGIN}"
    # The id is the value seed_options.py writes to the TILES option,
    # which is why it is the NAME: field and not the VIEW: label.
    emit PLAYTHROUGH_TILESET_RESOLVED "${TILESET_ID}"
    emit PLAYTHROUGH_TILESET_VIEW "${TILESET_VIEW}"
    emit PLAYTHROUGH_TILESET_DIR "${TILESET_DIR}"
    emit PLAYTHROUGH_TILESET_ORIGIN "${TILESET_ORIGIN}"
    return 0
}

# ---------------------------------------------------------------------
# STEP 4 -- the save-resume pre-flight probe.
#
# The rule is that the survivor is unique AND that an existing save is
# CONTINUED rather than replaced.  This probe is what makes the second
# half real: it inspects playthrough/userdir/save/*/ BEFORE anything
# could create a character, and it reports create-versus-resume so that
# session.py drives "Load" instead of "New Game" when a world is
# already there.
#
# A fresh checkout has no playthrough/, no userdir and no save/, so on a
# first run this reports "create".  The resume branch is implemented in
# full regardless -- a branch that is only correct when it never runs is
# not correct.
#
# The layout probed is the engine's own: src/path_info.cpp:144
# `savedir_value = user_dir_value + "save/";`, with each world a
# directory containing master.gsav (src/path_info.h SAVE_MASTER) and
# one `#<base64-of-character-name>.sav` per character
# (SAVE_EXTENSION, written by src/game_io.cpp save_player_data).
# master.gsav is the marker for a real world, because a bare directory
# proves nothing.
# ---------------------------------------------------------------------
probe_save_resume() {
    if [ "${PROBE_DONE}" -eq 1 ]; then
        return 0
    fi
    SESSION_MODE="create"
    SAVE_WORLD=""
    SAVE_WORLD_COUNT=0
    SAVE_CHAR_COUNT=0

    local dir world save
    if [ -d "${PLAYTHROUGH_SAVE_DIR}" ]; then
        for dir in "${PLAYTHROUGH_SAVE_DIR}"/*/; do
            [ -d "${dir}" ] || continue
            world="$(basename "${dir%/}")"
            if [ ! -f "${dir}master.gsav" ]; then
                playthrough_warn "save/${world} has no" \
                    "master.gsav; not treating it as a world"
                continue
            fi
            SAVE_WORLD_COUNT=$(( SAVE_WORLD_COUNT + 1 ))
            if [ -z "${SAVE_WORLD}" ]; then
                SAVE_WORLD="${world}"
            fi
            for save in "${dir}"*.sav; do
                [ -f "${save}" ] || continue
                SAVE_CHAR_COUNT=$(( SAVE_CHAR_COUNT + 1 ))
            done
        done
    fi

    if [ "${SAVE_WORLD_COUNT}" -gt 0 ]; then
        SESSION_MODE="resume"
        playthrough_log "RESUME: ${SAVE_WORLD_COUNT} world(s) and" \
            "${SAVE_CHAR_COUNT} character save(s) already exist" \
            "under ${PLAYTHROUGH_SAVE_DIR}.  The existing save MUST" \
            "be continued -- load world '${SAVE_WORLD}' and do not" \
            "create a new character."
        if [ "${SAVE_WORLD_COUNT}" -gt 1 ]; then
            playthrough_warn "more than one world is present;" \
                "'${SAVE_WORLD}' is the first in directory order," \
                "so confirm it is the intended one before loading"
        fi
    else
        playthrough_log "CREATE: no save under" \
            "${PLAYTHROUGH_SAVE_DIR}, so this session creates a" \
            "character through the custom point-buy creator"
    fi

    PROBE_DONE=1
    emit PLAYTHROUGH_SESSION_MODE "${SESSION_MODE}"
    emit PLAYTHROUGH_SAVE_WORLD "${SAVE_WORLD}"
    emit PLAYTHROUGH_SAVE_WORLD_COUNT "${SAVE_WORLD_COUNT}"
    emit PLAYTHROUGH_SAVE_CHAR_COUNT "${SAVE_CHAR_COUNT}"
    return 0
}

# ---------------------------------------------------------------------
# Window and process primitives.
#
# WINDOW TARGETING IS BY CLASS, AND ONLY BY CLASS.
#   * `xdotool search --class cataclysm-tiles` finds this window.
#   * `xdotool search --name 'Cataclysm'` returns EMPTY for it, even
#     though `xwininfo -root -children` lists it with the title
#     "Cataclysm: Dark Days Ahead - <hash>".  Name matching is not an
#     available alternative here.
#   * Scraping a window id out of xwininfo with a loose hexadecimal
#     pattern is actively unsafe: the "1920x1072" geometry substring
#     mis-matches such patterns.
# xdotool takes the display from the environment -- it has no --display
# option -- which is why env.sh exports DISPLAY and every call below
# simply inherits it.
# ---------------------------------------------------------------------

# game_window_ids -- every matching window id, newest last.  `|| true`
# is required because xdotool search exits non-zero when nothing
# matches, which is an ordinary answer and not an error.
game_window_ids() {
    xdotool search --class "${PLAYTHROUGH_WINDOW_CLASS}" \
        2>/dev/null || true
}

# find_game_window -- set WINDOW_ID to the newest match, or fail.
find_game_window() {
    WINDOW_ID="$(game_window_ids | tail -n 1)"
    [ -n "${WINDOW_ID}" ]
}

# wait_for_game_window TIMEOUT_SECONDS -- bounded poll with progress.
wait_for_game_window() {
    local timeout="$1"
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
#
# `xdotool getwindowgeometry --shell` emits assignable lines, and they
# are PARSED rather than eval'd on purpose: this file contains no eval,
# and sourcing another program's stdout would be exactly the pattern
# the project's static analysis exists to catch.
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
    WINDOW_WIDTH="${w}"
    WINDOW_HEIGHT="${h}"
    WINDOW_GEOMETRY="${w}x${h}+${x:-0}+${y:-0}"
    return 0
}

# pid_is_game PID -- true only when that pid really is a
# cataclysm-tiles process.
#
# This guard exists so that nothing in this file can ever signal a
# process it merely believes is the game.  Pattern-based process
# killing -- pkill, killall, `ps | grep | xargs kill` -- is never used
# anywhere here: this host also runs the tooling that invokes this
# script, and a pattern that matched it would end the run.  Only a
# numeric pid, obtained from the window we found or from the pid file
# this script itself wrote, is ever signalled, and only after
# /proc/<pid>/cmdline confirms what it is.
pid_is_game() {
    local pid="$1"
    case "${pid}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ -r "/proc/${pid}/cmdline" ] || return 1
    local cmd
    cmd="$(tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true)"
    case "${cmd}" in
        *cataclysm-tiles*) return 0 ;;
    esac
    return 1
}

# read_game_pid -- the game's pid, from the window first.
#
# _NET_WM_PID is set by SDL, so the window is the authoritative source;
# the recorded spawn pid is only a fallback, because `setsid` may fork
# and leave the shell holding the wrong pid.
read_game_pid() {
    local fallback="${1:-}"
    GAME_PID=""
    if [ -n "${WINDOW_ID}" ]; then
        local from_window
        from_window="$(xdotool getwindowpid "${WINDOW_ID}" \
            2>/dev/null || true)"
        if pid_is_game "${from_window}"; then
            GAME_PID="${from_window}"
            return 0
        fi
    fi
    if pid_is_game "${fallback}"; then
        GAME_PID="${fallback}"
        return 0
    fi
    if [ -f "${PIDFILE}" ]; then
        local from_file
        from_file="$(head -n 1 "${PIDFILE}" 2>/dev/null || true)"
        if pid_is_game "${from_file}"; then
            GAME_PID="${from_file}"
            return 0
        fi
    fi
    return 1
}

# stop_instance PID TIMEOUT -- ask one confirmed game process to exit.
#
# SIGTERM first, then SIGKILL only if it is ignored.  This is a
# diagnostic and calibration facility; it is NEVER how a captured
# session ends.  A captured session ends inside the game, through Save
# & Quit, which is the only exit that writes the save.
stop_instance() {
    local pid="$1"
    local timeout="${2:-30}"
    if ! pid_is_game "${pid}"; then
        playthrough_warn "pid '${pid}' is not a cataclysm-tiles" \
            "process; refusing to signal it"
        return 1
    fi
    local ticks=$(( timeout * 4 ))
    local waited=0
    playthrough_log "sending SIGTERM to game pid ${pid}"
    kill -TERM "${pid}" 2>/dev/null || true
    while kill -0 "${pid}" 2>/dev/null; do
        if [ "${waited}" -ge "${ticks}" ]; then
            playthrough_warn "pid ${pid} ignored SIGTERM for" \
                "${timeout}s; sending SIGKILL"
            kill -KILL "${pid}" 2>/dev/null || true
            break
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done
    rm -f -- "${PIDFILE}"
    playthrough_log "game pid ${pid} has exited"
    return 0
}

# ---------------------------------------------------------------------
# STEP 5 -- the launch.
#
# The command is exactly:
#
#     ./cataclysm-tiles --userdir ./playthrough/userdir/
#
# with both paths left RELATIVE and the working directory set to the
# repository root, for the source-level reasons given under WORKING
# DIRECTORY at the top of this file.  It is fully detached -- setsid,
# nohup, stdin from /dev/null -- so that the game survives the shell
# that started it and cannot be taken down with that shell's process
# group.
#
# FIRST LAUNCH IS NOT THE MAIN MENU.
# A fresh userdir opens on a "Select your language" prompt, not the main
# menu.  Verified by OCR of a real capture on this host: the first frame
# reads "Select your language" with "1 English" beneath it, and a single
# Return advances to the title screen whose menu offers "Custom
# Character", "Random Character", "Play Now! (Default Scenario)" and
# "Play Now!".  Anything that assumes the main menu is on screen at
# launch is therefore wrong.
#
# FIRST LAUNCH MAY ALSO NOT BE FULL SIZE.
# Window size derives from TERMINAL_WIDTH * fontwidth by
# TERMINAL_HEIGHT * fontheight (src/sdltiles.cpp:595-596), and the
# compiled defaults are TERMINAL_X 80 / TERMINAL_Y 24
# (src/options.cpp:2408-2416), which imply a 640x384 window until
# screen-derived values exist in options.json.  Measured on THIS host,
# that shortfall did not occur: the engine wrote TERMINAL_X 240 and
# TERMINAL_Y 67 during the very first launch and the window came up
# 1920x1080+0+0 immediately.  Both outcomes are handled -- the small
# case is caught by check_capture_geometry, the large case is accepted
# -- and neither is assumed, because it depends on what the engine can
# discover about the display.
#
# This script handles that explicitly by treating the first launch as
# THROWAWAY CALIBRATION: it starts the game only long enough for the
# engine to create config/options.json, then stops it, so that
# seed_options.py can patch that file (24_HOUR, SOUND_ENABLED, TILES,
# TERMINAL_X, TERMINAL_Y) without a running instance overwriting the
# patch on exit.  The NEXT launch is the one that is captured, and it
# is the one that comes up at full size on the main menu.  Calibration
# is skipped when a save already exists, so a resumable session is
# never interrupted for it.
# ---------------------------------------------------------------------

# launch_instance -- start one detached game process and wait for its
# window.  Sets WINDOW_ID, WINDOW_GEOMETRY and GAME_PID.
launch_instance() {
    assert_repo_root
    # Create frames/, build/, transitions/ and the userdir. env.sh owns
    # these paths; the engine creates save/ and config/ underneath the
    # userdir itself.
    playthrough_mkdirs

    : >"${PLAYTHROUGH_GAME_LOG}"
    playthrough_log "launching" \
        "${PLAYTHROUGH_GAME_BIN_ARG} --userdir" \
        "${PLAYTHROUGH_USERDIR_ARG} from $(pwd) on" \
        "${PLAYTHROUGH_DISPLAY}; log: ${PLAYTHROUGH_GAME_LOG}"

    setsid nohup "${PLAYTHROUGH_GAME_BIN_ARG}" \
        --userdir "${PLAYTHROUGH_USERDIR_ARG}" \
        >"${PLAYTHROUGH_GAME_LOG}" 2>&1 </dev/null &
    local spawned="$!"
    printf '%s\n' "${spawned}" >"${PIDFILE}"

    if ! wait_for_game_window "${WINDOW_TIMEOUT}"; then
        tail_log "${PLAYTHROUGH_GAME_LOG}"
        rm -f -- "${PIDFILE}"
        die "${EX_WINDOW}" "no window of class" \
            "'${PLAYTHROUGH_WINDOW_CLASS}' appeared on" \
            "${PLAYTHROUGH_DISPLAY} within ${WINDOW_TIMEOUT}s." \
            "Check the log above; note that searching by window" \
            "NAME would not find this window even when it is there."
    fi

    if read_game_pid "${spawned}"; then
        printf '%s\n' "${GAME_PID}" >"${PIDFILE}"
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

# assert_instance_alive -- after a settle, re-confirm that the instance
# which produced the window is STILL running.
#
# Why a second check is not redundant: a window appearing proves only
# that SDL created a surface.  The engine loads and validates the whole
# JSON content tree AFTER that point, so a data-load abort, a missing
# tileset asset, or a font failure can kill the process while its window
# id still resolves for a moment.  Reporting such a launch as successful
# would be the worst possible outcome for this pipeline: session.py
# would send keystroke after keystroke into a dead process, capture.sh
# would dutifully photograph an unchanging screen, and every frame would
# be identical -- a failure that produces a full-length, entirely
# static, entirely worthless movie instead of an error.  Since the whole
# premise is one DELIVERED keystroke per frame, a dead engine has to
# fail here and loudly, never be handed downstream.
assert_instance_alive() {
    sleep "${LIVENESS_SETTLE}"

    if [ -n "${GAME_PID}" ] && ! pid_is_game "${GAME_PID}"; then
        tail_log "${PLAYTHROUGH_GAME_LOG}"
        rm -f -- "${PIDFILE}"
        die "${EX_WINDOW}" "the game process (pid ${GAME_PID}) was" \
            "gone ${LIVENESS_SETTLE}s after its window appeared:" \
            "the engine started and then exited, most likely while" \
            "loading data. See the log above."
    fi

    if ! find_game_window; then
        tail_log "${PLAYTHROUGH_GAME_LOG}"
        rm -f -- "${PIDFILE}"
        die "${EX_WINDOW}" "the window of class" \
            "'${PLAYTHROUGH_WINDOW_CLASS}' vanished within" \
            "${LIVENESS_SETTLE}s of appearing on" \
            "${PLAYTHROUGH_DISPLAY}. See the log above."
    fi

    playthrough_log "instance still alive after" \
        "${LIVENESS_SETTLE}s (window ${WINDOW_ID}, pid" \
        "${GAME_PID:-unknown})"
    return 0
}

# emit_launch_facts -- the machine-readable half of a launch.
emit_launch_facts() {
    emit PLAYTHROUGH_LAUNCH_PHASE "${LAUNCH_PHASE}"
    emit PLAYTHROUGH_FIRST_RUN "${FIRST_RUN}"
    emit PLAYTHROUGH_WINDOW_ID "${WINDOW_ID}"
    emit PLAYTHROUGH_WINDOW_CLASS "${PLAYTHROUGH_WINDOW_CLASS}"
    emit PLAYTHROUGH_WINDOW_GEOMETRY "${WINDOW_GEOMETRY}"
    emit PLAYTHROUGH_GAME_PID "${GAME_PID}"
    emit PLAYTHROUGH_GAME_LOG "${PLAYTHROUGH_GAME_LOG}"
    emit PLAYTHROUGH_GAME_PIDFILE "${PIDFILE}"
    return 0
}

# check_capture_geometry -- confirm the window is big enough for the
# grid the terminal dimensions imply, and shout only on a shortfall.
#
# The test is "at least as large as", NOT "exactly equal to", and the
# distinction is load-bearing rather than lenient:
#
#   * The geometry that MUST hold is the X ROOT's 1920x1080, which
#     ensure_headless already asserted, because capture targets the
#     root (import -window root) and never the game window.  The
#     window's own size therefore only matters insofar as it decides
#     how much of that root the game actually paints.
#   * WindowWidth/Height derive from TERMINAL_WIDTH * fontwidth and
#     TERMINAL_HEIGHT * fontheight (src/sdltiles.cpp:595-596), so the
#     seeded 240x67 grid at 8x16 implies 1920x1072.
#   * FULLSCREEN defaults to "windowedbl" -- windowed BORDERLESS
#     (src/options.cpp:2715-2724) -- and a borderless window is what a
#     window manager is entitled to size to the whole screen.  Measured
#     on this host: the window comes up 1920x1080+0+0 against a
#     1920x1072 grid, i.e. 8px TALLER than the grid.  That is a
#     correct, indeed ideal, capture state -- the root carries no
#     letterbox at all -- so an equality test would fire a warning on
#     every healthy run and train an operator to ignore it.
#   * A window materially SMALLER than the grid is the real defect: it
#     means options.json still holds the compiled defaults TERMINAL_X
#     80 and TERMINAL_Y 24 (src/options.cpp:2408-2416), i.e. a 640x384
#     window adrift in a 1920x1080 root, and capturing that wastes the
#     session.  That is what this check exists to catch.
#
# It stays a warning rather than a failure because the authoritative
# geometry has already been asserted and because the calibration launch
# legitimately runs before the options file is seeded.
check_capture_geometry() {
    local want_w=$(( PLAYTHROUGH_TERMINAL_X * PLAYTHROUGH_FONT_WIDTH ))
    local want_h=$(( PLAYTHROUGH_TERMINAL_Y * PLAYTHROUGH_FONT_HEIGHT ))
    local want="${want_w}x${want_h}"

    if [ -z "${WINDOW_WIDTH}" ] || [ -z "${WINDOW_HEIGHT}" ]; then
        playthrough_warn "window geometry is unknown, so it could" \
            "not be compared with the ${want} grid implied by" \
            "TERMINAL_X ${PLAYTHROUGH_TERMINAL_X} /" \
            "TERMINAL_Y ${PLAYTHROUGH_TERMINAL_Y}"
        return 0
    fi

    if [ "${WINDOW_WIDTH}" -lt "${want_w}" ] ||
        [ "${WINDOW_HEIGHT}" -lt "${want_h}" ]; then
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

    if [ "${WINDOW_WIDTH}" -eq "${want_w}" ] &&
        [ "${WINDOW_HEIGHT}" -eq "${want_h}" ]; then
        playthrough_log "window geometry ${WINDOW_GEOMETRY} matches" \
            "the ${PLAYTHROUGH_TERMINAL_X}x${PLAYTHROUGH_TERMINAL_Y}" \
            "grid exactly (${want})"
    else
        playthrough_log "window geometry ${WINDOW_GEOMETRY} covers" \
            "the ${want} grid (a borderless window may be sized to" \
            "the whole root by the window manager); capture targets" \
            "the ${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}" \
            "root either way"
    fi
    return 0
}

launch_game() {
    ensure_headless
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
        read_game_pid || true
        read_window_geometry || true
        playthrough_log "a window of class" \
            "'${PLAYTHROUGH_WINDOW_CLASS}' is already up on" \
            "${PLAYTHROUGH_DISPLAY} (id ${WINDOW_ID}); reusing it" \
            "rather than starting a second instance"
        check_capture_geometry
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
            playthrough_warn "${PLAYTHROUGH_OPTIONS_JSON} did not" \
                "appear within 60s; the options file may only be" \
                "written when the game exits"
        fi
        if read_game_pid; then
            stop_instance "${GAME_PID}" "${STOP_TIMEOUT}" || true
        else
            playthrough_warn "could not identify the calibration" \
                "instance to stop it; stop it before seeding" \
                "options or the seed will be overwritten on exit"
        fi
        if [ ! -f "${PLAYTHROUGH_OPTIONS_JSON}" ] &&
           wait_for_file "${PLAYTHROUGH_OPTIONS_JSON}" 30; then
            playthrough_log "${PLAYTHROUGH_OPTIONS_JSON} was" \
                "written on exit"
        fi
        WINDOW_ID=""
        WINDOW_GEOMETRY=""
        GAME_PID=""
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
    if [ "${SESSION_MODE}" = "resume" ]; then
        playthrough_log "CAPTURE LAUNCH (resume): load world" \
            "'${SAVE_WORLD}' and continue the existing character;" \
            "do not create a new one"
    else
        playthrough_log "CAPTURE LAUNCH: create the survivor" \
            "through the custom point-buy creator"
    fi
    launch_instance
    check_capture_geometry
    emit_launch_facts
    return 0
}

# ---------------------------------------------------------------------
# Reporting and teardown subcommands.
# ---------------------------------------------------------------------

# report_status -- describe the current state and change nothing.
#
# It reports only what it can actually observe.  Anything it cannot
# read is reported as unknown or absent; nothing here is inferred, and
# no value is invented to fill a gap.
report_status() {
    assert_repo_root

    if read_game_version; then
        emit PLAYTHROUGH_GAME_BIN "${PLAYTHROUGH_GAME_BIN}"
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
    if find_installed_tileset "${PLAYTHROUGH_TILESET}"; then
        emit PLAYTHROUGH_TILESET_PREFERRED_PRESENT 1
    else
        emit PLAYTHROUGH_TILESET_PREFERRED_PRESENT 0
    fi

    probe_save_resume

    if find_game_window; then
        read_game_pid || true
        read_window_geometry || true
        emit PLAYTHROUGH_GAME_RUNNING 1
    else
        WINDOW_ID=""
        WINDOW_GEOMETRY=""
        GAME_PID=""
        emit PLAYTHROUGH_GAME_RUNNING 0
    fi
    LAUNCH_PHASE="status"
    emit_launch_facts
    return 0
}

# stop_game -- the operator-facing teardown.
#
# WARNING, AND IT IS NOT A FORMALITY: this terminates the process. It
# does NOT save.  A captured session must end inside the game, by
# realistic sleep or by death, followed by the in-game Save & Quit --
# that is the only exit that writes the save, and it is the only ending
# this pipeline's requirements accept.  Use this to clear a stuck or
# calibration instance, never to end a session that is being recorded.
stop_game() {
    if ! find_game_window; then
        if [ -f "${PIDFILE}" ]; then
            local stale
            stale="$(head -n 1 "${PIDFILE}" 2>/dev/null || true)"
            if pid_is_game "${stale}"; then
                playthrough_warn "no window found, but pid" \
                    "${stale} is still a game process; stopping it"
                stop_instance "${stale}" "${STOP_TIMEOUT}" || true
                return 0
            fi
            rm -f -- "${PIDFILE}"
        fi
        playthrough_log "no game instance is running on" \
            "${PLAYTHROUGH_DISPLAY}; nothing to stop"
        emit PLAYTHROUGH_GAME_RUNNING 0
        return 0
    fi
    playthrough_warn "stopping the game WITHOUT saving." \
        "A recorded session must instead end in-game with Save &" \
        "Quit, which is the only exit that writes the save."
    if read_game_pid; then
        stop_instance "${GAME_PID}" "${STOP_TIMEOUT}" || true
    else
        playthrough_warn "the window exists but no confirmed game" \
            "pid could be found, so nothing was signalled"
    fi
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
            "tileset" "resolve, installing if needed, the tileset" \
            "probe" "report the resume-versus-create decision" \
            "launch" "launch detached and wait for the window" \
            "status" "report current state, changing nothing" \
            "stop" "terminate a game instance WITHOUT saving" \
            "help" "this text"
        printf '%s\n' ""
        printf '%s\n' "stdout carries KEY=value lines only; all \
logging goes to stderr."
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

    case "${subcommand}" in
        all)
            ensure_binary
            ensure_headless
            resolve_tileset
            probe_save_resume
            launch_game
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
        help|-h|--help)
            usage 1
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
