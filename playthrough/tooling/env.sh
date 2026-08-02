#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2317
#
# Both directives above are deliberate and are the only suppressions
# in this file.  `shell=bash` states the dialect explicitly, because
# this file is analysed as a sourced library rather than run.  SC2317
# ("command appears to be unreachable") fires on the
# `return 1 2>/dev/null || exit 1` bail idiom used below, which
# ShellCheck cannot model: `return` succeeds when a file is sourced
# and fails when it is executed, so exactly one arm runs in either
# case and neither is dead code.
# ---------------------------------------------------------------------
# playthrough/tooling/env.sh
#
# The SINGLE definition of the headless render environment, and of the
# artifact layout, for the Cataclysm-DDA playthrough capture and
# cinematography pipeline.  Every other script and module under
# playthrough/tooling/ sources this file instead of setting these
# values itself, so the launcher, the capturer, the session driver and
# the render stages cannot drift apart over the display, the video
# driver, or a single path.
#
# SOURCE IT -- DO NOT EXECUTE IT -- AND SOURCE IT FROM THE REPOSITORY
# ROOT:
#
#     cd <repository root>
#     . playthrough/tooling/env.sh
#
# Sourcing from the repository root is a source-level requirement of
# the game engine, not a style preference.  See "WORKING DIRECTORY"
# below for the citations.
#
# Running this file directly (bash playthrough/tooling/env.sh) is
# harmless and prints the resolved contract for inspection, but it
# exports nothing into your shell: a child process cannot mutate its
# parent's environment.
#
# Sourcing twice is harmless.  Every assignment is absolute and
# recomputed from scratch, nothing is ever appended to -- PATH is
# deliberately never touched, so it cannot grow on re-source -- and no
# process is started as a side effect of sourcing.
#
# Requires bash.  BASH_SOURCE is used to locate the file, which is how
# it stays correct no matter which directory a caller sources it from.
# ---------------------------------------------------------------------
# WHY THIS FILE DOES NOT `set -euo pipefail`  (deliberate -- please do
# not "fix" it)
#
# Shell options set at the top level of a *sourced* file are imposed
# on the CALLING shell and stay there after the source returns.  A
# pipeline stage that sourced this file would silently inherit
# errexit, nounset and pipefail and change behaviour; an interactive
# shell would start exiting on the next failed command.  Every other
# *.sh in this folder is executed rather than sourced and sets those
# options itself.  This file is the one deliberate exception.  Where
# an option is genuinely needed here it is set inside a function,
# which scopes it to that function -- the same technique
# build-scripts/build.sh uses in run_test().
# ---------------------------------------------------------------------

# bash is required: BASH_SOURCE, arrays and `local` are all used below.
# `return` succeeds only in a sourced file, so the `||` arm covers the
# executed case.  This bail idiom has to stay at file scope: a `return`
# inside a function would only leave the function, not the file.
if [ -z "${BASH_VERSION-}" ]; then
    printf '%s\n' "playthrough/tooling/env.sh: bash is required." >&2
    return 1 2>/dev/null || exit 1
fi

# Sourced or executed?  Only used to decide whether to print the
# summary at the end; sourcing must stay silent so it cannot pollute a
# consumer's stdout.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    _playthrough_executed=1
else
    _playthrough_executed=0
fi

# ---------------------------------------------------------------------
# Small reporting helpers, defined first so everything below can use
# them.  playthrough_die returns 1 rather than calling exit: this file
# is sourced, and `exit` from a sourced file would kill the caller's
# shell, including an interactive one.  Consumers run with
# `set -euo pipefail`, so a non-zero return aborts them anyway.
# ---------------------------------------------------------------------
playthrough_log() {
    printf 'playthrough: %s\n' "$*" >&2
}

playthrough_warn() {
    printf 'playthrough: WARNING: %s\n' "$*" >&2
}

playthrough_die() {
    printf 'playthrough: FATAL: %s\n' "$*" >&2
    return 1
}

# ---------------------------------------------------------------------
# WORKING DIRECTORY: why every command in this pipeline runs from the
# repository root
#
# This is enforced by the engine's own path handling, not by taste:
#
#   * --userdir is normalised but NOT absolutised --
#     src/path_info.cpp:105 `user_dir_value = as_norm_dir( dir );` --
#     so `--userdir ./playthrough/userdir/` resolves against the
#     process working directory.
#   * With an empty --basepath the asset roots are likewise working
#     directory relative: src/path_info.cpp:129
#     `datadir_value = "data/";`, :134 `gfxdir_value = prefix +
#     "gfx/";`, :136 `langdir_value = prefix + "lang/mo/";`.
#
# The repository root is therefore the ONLY working directory under
# which this checkout's own data/, gfx/ and lang/mo/ resolve AND the
# userdir lands inside the working tree where git can track it.  Any
# other choice breaks both halves at once -- which is why the paths
# below are resolved absolutely from BASH_SOURCE and exported, so no
# sibling has to guess.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8-9, adjusted for this file's depth
# of two directories rather than one.
# ---------------------------------------------------------------------
_playthrough_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_playthrough_script_dir}" ]; then
    playthrough_die "cannot resolve the directory of env.sh"
    return 1 2>/dev/null || exit 1
fi

_playthrough_repo_root="$(
    cd "${_playthrough_script_dir}/../.." >/dev/null 2>&1 && pwd
)"
if [ -z "${_playthrough_repo_root}" ]; then
    playthrough_die "cannot resolve the repository root from" \
        "${_playthrough_script_dir}"
    return 1 2>/dev/null || exit 1
fi

# Fail loudly if this file has been copied somewhere that is not a
# Cataclysm-DDA checkout.  Every stage below is meaningless without
# the engine's data tree, and a wrong root would otherwise surface
# much later as an unexplained black frame or an empty save.
if [ ! -d "${_playthrough_repo_root}/data" ] ||
   [ ! -f "${_playthrough_repo_root}/src/path_info.cpp" ]; then
    playthrough_die "'${_playthrough_repo_root}' is not a" \
        "Cataclysm-DDA checkout (no data/ or src/path_info.cpp)"
    return 1 2>/dev/null || exit 1
fi

# ---------------------------------------------------------------------
# Display and runtime directory
#
# The canonical contract is DISPLAY=:99 on an X server started as
# `Xvfb :99 -screen 0 1920x1080x24`, with openbox as a minimal window
# manager so that focus and keyboard delivery behave (xdotool key
# delivery is unreliable on a bare X server with no WM).
#
# CLONE_INDEX offsets the display and the runtime directory so that
# two checkouts on one host cannot fight over a single X server or
# capture each other's windows.  It is normalised with 10# so that a
# zero-padded value such as "000" is read as decimal zero rather than
# as octal, and index 0 -- unset, "0" and "000" alike -- yields
# exactly DISPLAY=:99 and XDG_RUNTIME_DIR=/tmp/xdg, the canonical
# single-checkout contract.
# ---------------------------------------------------------------------
_playthrough_index_raw="${CLONE_INDEX:-0}"
case "${_playthrough_index_raw}" in
    *[^0-9]*|"")
        playthrough_warn "CLONE_INDEX='${_playthrough_index_raw}' is" \
            "not a non-negative integer; using 0"
        _playthrough_index=0
        ;;
    *)
        _playthrough_index=$(( 10#${_playthrough_index_raw} ))
        ;;
esac

export PLAYTHROUGH_CLONE_INDEX="${_playthrough_index}"
export PLAYTHROUGH_DISPLAY_NUM=$(( 99 + _playthrough_index ))
export PLAYTHROUGH_DISPLAY=":${PLAYTHROUGH_DISPLAY_NUM}"
export DISPLAY="${PLAYTHROUGH_DISPLAY}"

# A suffix for host-global scratch paths, empty at index 0 so the
# canonical run uses the plain names.
if [ "${_playthrough_index}" -eq 0 ]; then
    _playthrough_suffix=""
else
    _playthrough_suffix="${_playthrough_index}"
fi

# XDG_RUNTIME_DIR must exist at mode 0700 before it is exported: SDL,
# Mesa and dbus all refuse or warn on a world-readable runtime
# directory, and a missing one produces a confusing SDL init failure.
_playthrough_runtime_dir="/tmp/xdg${_playthrough_suffix}"
if ! mkdir -p "${_playthrough_runtime_dir}"; then
    playthrough_die "cannot create ${_playthrough_runtime_dir}"
    return 1 2>/dev/null || exit 1
fi
if ! chmod 700 "${_playthrough_runtime_dir}"; then
    playthrough_die "cannot chmod 0700 ${_playthrough_runtime_dir}"
    return 1 2>/dev/null || exit 1
fi
export XDG_RUNTIME_DIR="${_playthrough_runtime_dir}"

# ---------------------------------------------------------------------
# THE RENDERING CONTRACT -- READ THIS BEFORE TOUCHING EITHER DRIVER
#
# Two variables below take a value spelled "dummy" and only ONE of
# them ever may:
#
#   SDL_AUDIODRIVER=dummy    CORRECT and required.  A headless host
#                            has no audio device, and the game is run
#                            with SOUND_ENABLED=false, so the null
#                            audio backend is exactly right.  Without
#                            it SDL_mixer spends the session retrying
#                            a device that will never appear.
#
#   SDL_VIDEODRIVER=dummy    CATASTROPHIC, and BANNED everywhere in
#                            this tree including as any script's
#                            default.  The dummy video backend
#                            renders zero pixels.  The game still
#                            runs, every keystroke still lands,
#                            `import -window root` still writes a
#                            PNG, ffmpeg still encodes, and every
#                            acceptance count still matches -- the
#                            only symptom is that the finished movie
#                            shows nothing at all.  It is the one
#                            completely silent failure mode of this
#                            pipeline, and the closest thing to
#                            accidental fabrication it can suffer.
#
# SDL_VIDEODRIVER is therefore exported UNCONDITIONALLY.  It is
# deliberately NOT written as "${SDL_VIDEODRIVER:-x11}": that is a
# default, and a caller who already had dummy in their environment
# would silently win.  This file overwrites it instead, and then
# asserts the result.
#
# Calibration measured on this host with
#     convert <png> -colorspace Gray \
#         -format "%[fx:mean] %[fx:standard_deviation]" info:
#     real rendered frame     mean=0.270018   std=0.198145
#     dummy video driver      mean=0          std=0
#     uniform solid colour    mean>0          std=0
# verify_artifacts.sh asserts mean > 0 AND std > 0 as the backstop.
# This file is the primary defence.
# ---------------------------------------------------------------------
export SDL_VIDEODRIVER=x11
export SDL_AUDIODRIVER=dummy

# No GPU exists on a headless host, so force the software rasteriser
# (llvmpipe).  Without this, GL initialisation can fail outright or
# fall back inconsistently between launches.
export LIBGL_ALWAYS_SOFTWARE=1

# ---------------------------------------------------------------------
# PYTHONDONTWRITEBYTECODE=1 is load-bearing, not hygiene
#
# .gitignore:161 is `__pycache__` and :162 is `*.pyc`, both
# unanchored.  git applies the LAST matching pattern, and the terminal
# negation block ends with `!/playthrough/**` (.gitignore:268), which
# therefore RE-INCLUDES playthrough/tooling/__pycache__/*.pyc.
# Verified in this checkout: `git check-ignore -v` on a real .pyc
# under playthrough/tooling/ answers with the negation line, and
# `git add --dry-run` prints `add '...cpython-312.pyc'`.
#
# That negation has to stay last for the save data to be tracked at
# all, so a re-exclusion cannot simply be appended after it.
# Bytecode is prevented at source instead.  commit_artifacts.sh is the
# second line of defence: it stages the artifact classes explicitly
# rather than blanket-adding the tree.
#
# For the same reason a virtualenv must NEVER be created underneath
# playthrough/ -- the negation would re-include every byte of it.
# Keep interpreters out of tree; see PLAYTHROUGH_PYTHON below.
# ---------------------------------------------------------------------
export PYTHONDONTWRITEBYTECODE=1

# Line-buffer Python's stdout/stderr so that a long capture session
# reports progress as it happens instead of at exit.
export PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------
# Artifact layout -- one authoritative definition for every sibling
#
# Absolute paths, so a consumer is correct even if it is invoked from
# elsewhere; plus the two repository-root-relative forms that are
# passed to the game on the command line, which MUST stay relative
# for the reasons given under WORKING DIRECTORY above.
# ---------------------------------------------------------------------
export PLAYTHROUGH_REPO_ROOT="${_playthrough_repo_root}"
export PLAYTHROUGH_DIR="${_playthrough_repo_root}/playthrough"
export PLAYTHROUGH_TOOLING_DIR="${PLAYTHROUGH_DIR}/tooling"
export PLAYTHROUGH_FRAMES_DIR="${PLAYTHROUGH_DIR}/frames"
export PLAYTHROUGH_BUILD_DIR="${PLAYTHROUGH_DIR}/build"
export PLAYTHROUGH_TRANSITIONS_DIR="${PLAYTHROUGH_BUILD_DIR}/transitions"
export PLAYTHROUGH_USERDIR="${PLAYTHROUGH_DIR}/userdir"

# Engine-managed subtrees of the userdir.  src/path_info.cpp:144
# `savedir_value = user_dir_value + "save/";`, :164
# `config_dir_value = user_dir_value + "config/";`, :167
# `options_value = config_dir_value + "options.json";`.  The user
# keybinding overrides live beside them (src/path_info.cpp:400-402)
# and are committed as auditable evidence that no debug action was
# ever bound.
export PLAYTHROUGH_SAVE_DIR="${PLAYTHROUGH_USERDIR}/save"
export PLAYTHROUGH_CONFIG_DIR="${PLAYTHROUGH_USERDIR}/config"
export PLAYTHROUGH_OPTIONS_JSON="${PLAYTHROUGH_CONFIG_DIR}/options.json"
_playthrough_kbjson="${PLAYTHROUGH_CONFIG_DIR}/keybindings.json"
export PLAYTHROUGH_KEYBINDINGS_JSON="${_playthrough_kbjson}"

# Data and media artifacts.
export PLAYTHROUGH_MANIFEST="${PLAYTHROUGH_DIR}/manifest.jsonl"
export PLAYTHROUGH_TIMELINE="${PLAYTHROUGH_DIR}/timeline.json"
export PLAYTHROUGH_CONCAT_LIST="${PLAYTHROUGH_BUILD_DIR}/concat.txt"
export PLAYTHROUGH_MOVIE="${PLAYTHROUGH_DIR}/cata-play.mp4"
export PLAYTHROUGH_MOVIE_CC="${PLAYTHROUGH_DIR}/cata-play-cc.mp4"
export PLAYTHROUGH_TRANSCRIPT_MD="${PLAYTHROUGH_DIR}/transcript.md"
export PLAYTHROUGH_TRANSCRIPT_SRT="${PLAYTHROUGH_DIR}/transcript.srt"
export PLAYTHROUGH_DOSSIER="${PLAYTHROUGH_DIR}/dossier.md"
export PLAYTHROUGH_TECH_NOTES="${PLAYTHROUGH_DIR}/TECHNICAL_NOTES.md"
export PLAYTHROUGH_REQUIREMENTS="${PLAYTHROUGH_TOOLING_DIR}/requirements.txt"

# One printf format for the capture filename, so the capturer, the
# manifest writer and the concat list agree byte for byte.  Use it as
#     name="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}" "${index}")"
# The 5-digit zero-padded field keeps a lexical sort identical to a
# numeric one, which is what makes the concat list trivially correct.
export PLAYTHROUGH_FRAME_FORMAT='frame_%05d.png'
export PLAYTHROUGH_TRANSITION_FORMAT='trans_%05d_%02d.png'

# The game, and the exact command-line forms it is launched with.
# Both stay repository-root relative on purpose (see WORKING
# DIRECTORY): the trailing slash on the userdir matches
# as_norm_dir()'s own normalisation at src/path_info.cpp:105.
export PLAYTHROUGH_GAME_BIN="${_playthrough_repo_root}/cataclysm-tiles"
export PLAYTHROUGH_GAME_BIN_ARG="./cataclysm-tiles"
export PLAYTHROUGH_USERDIR_ARG="./playthrough/userdir/"

# Host-global scratch logs, suffixed per checkout so parallel clones
# do not overwrite each other's diagnostics.  These are outside the
# working tree deliberately: they are diagnostics, not artifacts, and
# `!/playthrough/**` would otherwise make them committable.
export PLAYTHROUGH_GAME_LOG="/tmp/cata-play${_playthrough_suffix}.log"
export PLAYTHROUGH_XVFB_LOG="/tmp/xvfb${_playthrough_suffix}.log"
export PLAYTHROUGH_WM_LOG="/tmp/openbox${_playthrough_suffix}.log"

# ---------------------------------------------------------------------
# Display, window and grid geometry
#
# The X root is exactly 1920x1080 while the game window occupies
# 1920x1072 at +0+4 (240 columns x 8 px by 67 rows x 16 px, derived
# per src/sdltiles.cpp:595-596 with FULLSCREEN defaulting to windowed
# borderless).  Capture therefore targets the ROOT window: it yields a
# true-resolution PNG with a 4-pixel letterbox and needs no rescaling,
# and rescaling would soften exactly the 8x16 glyphs the clock OCR
# depends on.
#
# The window is found by CLASS.  `xdotool search --name 'Cataclysm'`
# returns nothing for this window even though xwininfo -root
# -children lists it; `xdotool search --class cataclysm-tiles` works.
#
# Note also that xdotool has NO --display option: it resolves the
# display from the environment before it even parses the subcommand.
# Both halves were measured on this host -- with DISPLAY unset it
# fails "Can't open display: (null)" no matter what --display says,
# and with DISPLAY set it rejects the flag outright with "search:
# unrecognized option '--display'".  Exporting DISPLAY above is
# therefore what makes every xdotool call in the pipeline work; a
# per-command flag is not an available alternative.
# ---------------------------------------------------------------------
export PLAYTHROUGH_SCREEN_WIDTH=1920
export PLAYTHROUGH_SCREEN_HEIGHT=1080
export PLAYTHROUGH_SCREEN_DEPTH=24
export PLAYTHROUGH_SCREEN="1920x1080x24"
export PLAYTHROUGH_WINDOW_CLASS="cataclysm-tiles"

# Terminal grid and font cell, used to seed options.json and to
# compute the sidebar OCR crop rather than hard-coding a rectangle.
# 36 cells is the default sidebar width from
# data/json/ui/sidebar.json (custom_sidebar.width); ten alternative
# presets ship in data/json/ui/, which is why the crop is computed.
export PLAYTHROUGH_TERMINAL_X=240
export PLAYTHROUGH_TERMINAL_Y=67
export PLAYTHROUGH_FONT_WIDTH=8
export PLAYTHROUGH_FONT_HEIGHT=16
export PLAYTHROUGH_SIDEBAR_CELLS=36

# The tileset option value, i.e. the NAME: field of the installed
# tileset.txt rather than its display VIEW: name.  MshockXottoplus is
# "MSXotto+".  ASCIITiles ships with the checkout and is the fallback
# if the extra tilesets have not been installed under gfx/.
export PLAYTHROUGH_TILESET="MshockXottoplus"
export PLAYTHROUGH_TILESET_FALLBACK="ASCIITiles"

# Seconds to let a frame settle after a keystroke before capturing.
# The game redraws asynchronously; capturing too early photographs the
# previous frame and silently shifts every clock reading by one step.
export PLAYTHROUGH_SETTLE_SECONDS="0.3"

# ---------------------------------------------------------------------
# The Python interpreter
#
# Resolved here so that every sibling runs the same one, and searched
# out of tree only -- a virtualenv inside playthrough/ would be
# re-included by `!/playthrough/**` and committed.  Honour an explicit
# PLAYTHROUGH_PYTHON first, then PLAYTHROUGH_VENV, then the
# provisioned location, then whatever python3 is on PATH.  Install
# playthrough/tooling/requirements.txt into whichever one is chosen.
# ---------------------------------------------------------------------
if [ -n "${PLAYTHROUGH_PYTHON:-}" ] &&
   [ -x "${PLAYTHROUGH_PYTHON}" ]; then
    _playthrough_python="${PLAYTHROUGH_PYTHON}"
elif [ -n "${PLAYTHROUGH_VENV:-}" ] &&
     [ -x "${PLAYTHROUGH_VENV}/bin/python" ]; then
    _playthrough_python="${PLAYTHROUGH_VENV}/bin/python"
elif [ -x "/opt/playthrough-venv/bin/python" ]; then
    _playthrough_python="/opt/playthrough-venv/bin/python"
else
    _playthrough_python="$(command -v python3 2>/dev/null || true)"
    if [ -z "${_playthrough_python}" ]; then
        playthrough_warn "no python3 found on PATH; the render" \
            "stages will not run until one is available"
        _playthrough_python="python3"
    fi
fi
export PLAYTHROUGH_PYTHON="${_playthrough_python}"

# ---------------------------------------------------------------------
# Helper functions
#
# None of these runs at source time.  Sourcing this file must never
# start a server, launch the game or write into the working tree; the
# launcher calls what it needs, explicitly.
# ---------------------------------------------------------------------

# playthrough_assert_video_driver
#   The guard that keeps the black-movie failure mode impossible.
#   Call it from any stage that is about to render or capture.
playthrough_assert_video_driver() {
    if [ "${SDL_VIDEODRIVER:-}" != "x11" ]; then
        playthrough_die "SDL_VIDEODRIVER is" \
            "'${SDL_VIDEODRIVER:-<unset>}', not 'x11'." \
            "The dummy backend renders zero pixels and produces a" \
            "movie that is entirely black while every count still" \
            "matches.  Re-source playthrough/tooling/env.sh and do" \
            "not override it."
        return 1
    fi
    return 0
}

# playthrough_require_tools [tool ...]
#   Assert that external commands exist, reporting ALL that are
#   missing rather than dying on the first.  With no arguments it
#   checks the whole pipeline's toolchain.
playthrough_require_tools() {
    local tools=("$@")
    local missing=()
    local tool
    if [ "${#tools[@]}" -eq 0 ]; then
        tools=(
            Xvfb openbox xdpyinfo xwininfo xprop xdotool
            import convert identify ffmpeg ffprobe tesseract
        )
    fi
    for tool in "${tools[@]}"; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            missing+=("${tool}")
        fi
    done
    if [ "${#missing[@]}" -ne 0 ]; then
        playthrough_die "missing required command(s):" \
            "${missing[*]}.  See the apt list in" \
            "playthrough/tooling/requirements.txt."
        return 1
    fi
    return 0
}

# playthrough_display_ready
#   True when an X server is answering on the contracted display.
playthrough_display_ready() {
    xdpyinfo -display "${PLAYTHROUGH_DISPLAY}" >/dev/null 2>&1
}

# playthrough_wait_for_display [timeout_seconds]
#   Poll until the display answers.  Default timeout 30 s.
playthrough_wait_for_display() {
    local timeout="${1:-30}"
    local deadline=$(( timeout * 4 ))
    local waited=0
    while [ "${waited}" -lt "${deadline}" ]; do
        if playthrough_display_ready; then
            return 0
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done
    playthrough_die "no X server answering on" \
        "${PLAYTHROUGH_DISPLAY} after ${timeout}s (log:" \
        "${PLAYTHROUGH_XVFB_LOG})"
    return 1
}

# playthrough_start_xvfb
#   Start the headless X server ONLY if the display is not already
#   answering, so an externally managed server -- a container sidecar,
#   say -- is left alone.  Detached with setsid so it outlives the
#   shell that started it.
playthrough_start_xvfb() {
    if playthrough_display_ready; then
        return 0
    fi
    playthrough_require_tools Xvfb || return 1
    mkdir -p /tmp/.X11-unix 2>/dev/null || true
    playthrough_log "starting Xvfb on ${PLAYTHROUGH_DISPLAY} at" \
        "${PLAYTHROUGH_SCREEN}"
    setsid nohup Xvfb "${PLAYTHROUGH_DISPLAY}" \
        -screen 0 "${PLAYTHROUGH_SCREEN}" -nolisten tcp \
        >"${PLAYTHROUGH_XVFB_LOG}" 2>&1 </dev/null &
    playthrough_wait_for_display 30
}

# playthrough_wm_ready
#   True when a window manager owns the contracted display.
playthrough_wm_ready() {
    xprop -root -display "${PLAYTHROUGH_DISPLAY}" \
        _NET_SUPPORTING_WM_CHECK 2>/dev/null |
        grep -q 'window id'
}

# playthrough_start_wm
#   Start openbox only if no window manager is present.  A bare X
#   server has no focus model, and xdotool key delivery to an
#   unfocused window is unreliable, so the WM is load-bearing for
#   one-keystroke-per-frame capture rather than cosmetic.
playthrough_start_wm() {
    if playthrough_wm_ready; then
        return 0
    fi
    playthrough_require_tools openbox xprop || return 1
    playthrough_log "starting openbox on ${PLAYTHROUGH_DISPLAY}"
    setsid nohup env DISPLAY="${PLAYTHROUGH_DISPLAY}" openbox \
        >"${PLAYTHROUGH_WM_LOG}" 2>&1 </dev/null &
    local waited=0
    while [ "${waited}" -lt 40 ]; do
        if playthrough_wm_ready; then
            return 0
        fi
        sleep 0.25
        waited=$(( waited + 1 ))
    done
    playthrough_die "openbox did not take ownership of" \
        "${PLAYTHROUGH_DISPLAY} (log: ${PLAYTHROUGH_WM_LOG})"
    return 1
}

# playthrough_assert_display
#   Assert the root window really is the contracted geometry and
#   depth.  Capture targets the root, so a wrong size here would
#   silently produce a movie at the wrong resolution.
playthrough_assert_display() {
    playthrough_display_ready || {
        playthrough_die "no X server on ${PLAYTHROUGH_DISPLAY}"
        return 1
    }
    local info dims depth want
    info="$(xdpyinfo -display "${PLAYTHROUGH_DISPLAY}" 2>/dev/null)"
    dims="$(printf '%s\n' "${info}" |
        awk '/dimensions:/ { print $2; exit }')"
    depth="$(printf '%s\n' "${info}" |
        awk '/depth of root window:/ { print $5; exit }')"
    want="${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}"
    if [ "${dims}" != "${want}" ]; then
        playthrough_die "root window is '${dims}', expected" \
            "'${want}' on ${PLAYTHROUGH_DISPLAY}"
        return 1
    fi
    if [ "${depth}" != "${PLAYTHROUGH_SCREEN_DEPTH}" ]; then
        playthrough_die "root depth is '${depth}', expected" \
            "'${PLAYTHROUGH_SCREEN_DEPTH}'"
        return 1
    fi
    return 0
}

# playthrough_headless_up
#   Bring the whole headless surface up idempotently and verify it:
#   X server, window manager, geometry, video driver.  This is what
#   launch_game.sh calls before it launches anything.
playthrough_headless_up() {
    playthrough_assert_video_driver || return 1
    playthrough_start_xvfb || return 1
    playthrough_start_wm || return 1
    playthrough_assert_display || return 1
    return 0
}

# playthrough_mkdirs
#   Create the artifact directories.  Called explicitly, never at
#   source time: sourcing this file must not write into the tree.
playthrough_mkdirs() {
    mkdir -p \
        "${PLAYTHROUGH_FRAMES_DIR}" \
        "${PLAYTHROUGH_BUILD_DIR}" \
        "${PLAYTHROUGH_TRANSITIONS_DIR}" \
        "${PLAYTHROUGH_USERDIR}"
}

# playthrough_python [args ...]
#   Run the resolved interpreter, so no sibling has to rediscover it.
playthrough_python() {
    "${PLAYTHROUGH_PYTHON}" "$@"
}

# playthrough_env_summary
#   Print the resolved contract on stdout.  Used by the direct
#   execution path below and worth logging at the head of a session,
#   because it is the record of what the capture actually ran under.
playthrough_env_summary() {
    printf '%s\n' "playthrough environment contract"
    printf '  %-26s %s\n' \
        "DISPLAY" "${DISPLAY}" \
        "SDL_VIDEODRIVER" "${SDL_VIDEODRIVER}" \
        "SDL_AUDIODRIVER" "${SDL_AUDIODRIVER}" \
        "LIBGL_ALWAYS_SOFTWARE" "${LIBGL_ALWAYS_SOFTWARE}" \
        "XDG_RUNTIME_DIR" "${XDG_RUNTIME_DIR}" \
        "PYTHONDONTWRITEBYTECODE" "${PYTHONDONTWRITEBYTECODE}" \
        "PLAYTHROUGH_CLONE_INDEX" "${PLAYTHROUGH_CLONE_INDEX}" \
        "PLAYTHROUGH_SCREEN" "${PLAYTHROUGH_SCREEN}" \
        "PLAYTHROUGH_WINDOW_CLASS" "${PLAYTHROUGH_WINDOW_CLASS}" \
        "PLAYTHROUGH_TILESET" "${PLAYTHROUGH_TILESET}" \
        "PLAYTHROUGH_REPO_ROOT" "${PLAYTHROUGH_REPO_ROOT}" \
        "PLAYTHROUGH_DIR" "${PLAYTHROUGH_DIR}" \
        "PLAYTHROUGH_FRAMES_DIR" "${PLAYTHROUGH_FRAMES_DIR}" \
        "PLAYTHROUGH_BUILD_DIR" "${PLAYTHROUGH_BUILD_DIR}" \
        "PLAYTHROUGH_TRANSITIONS_DIR" \
        "${PLAYTHROUGH_TRANSITIONS_DIR}" \
        "PLAYTHROUGH_USERDIR" "${PLAYTHROUGH_USERDIR}" \
        "PLAYTHROUGH_USERDIR_ARG" "${PLAYTHROUGH_USERDIR_ARG}" \
        "PLAYTHROUGH_MANIFEST" "${PLAYTHROUGH_MANIFEST}" \
        "PLAYTHROUGH_TIMELINE" "${PLAYTHROUGH_TIMELINE}" \
        "PLAYTHROUGH_MOVIE" "${PLAYTHROUGH_MOVIE}" \
        "PLAYTHROUGH_MOVIE_CC" "${PLAYTHROUGH_MOVIE_CC}" \
        "PLAYTHROUGH_PYTHON" "${PLAYTHROUGH_PYTHON}"
}

# ---------------------------------------------------------------------
# Final guard, then done.
#
# The assertion is repeated here at source time so that a contract
# which somehow does not carry x11 can never leave this file quietly.
# Fail loudly, never silently -- the whole point of banning the dummy
# video backend is that its symptom is invisibility.
# ---------------------------------------------------------------------
if ! playthrough_assert_video_driver; then
    return 1 2>/dev/null || exit 1
fi

if [ "${_playthrough_executed}" = "1" ]; then
    playthrough_env_summary
fi

# Leave no scratch names behind in the caller's shell.  Only the
# exported PLAYTHROUGH_* set, the six environment variables and the
# helper functions are part of this file's contract.
unset _playthrough_executed _playthrough_script_dir
unset _playthrough_repo_root _playthrough_index _playthrough_index_raw
unset _playthrough_suffix _playthrough_runtime_dir _playthrough_python
unset _playthrough_kbjson
