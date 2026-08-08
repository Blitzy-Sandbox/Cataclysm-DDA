#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/preflight_capture.sh
#
# PROVE THAT THIS HOST CAN RECORD A SESSION -- before one is attempted.
#
# Every production stage of this pipeline refuses to run unless env.sh
# classifies the trust state as `trusted`: launch_game.sh will not bring
# up an instance to be captured, capture.sh will not keep a frame,
# render_movie.py will not encode and embed_captions.sh will not mux.
# The refusals are correct and this file does not touch them.  What it
# does is answer the question they raise -- WHERE, then, can a session be
# recorded? -- with a measurement instead of a hope, by running the real
# stages over a real engine and reporting which of them opened.
#
# It is written to be run either inside the declared environment
# (playthrough/tooling/environment/Dockerfile, entered through
# supported_env.sh) or directly on any host whose release env.sh's own
# support table accepts.  It takes no arguments and needs no
# configuration.
#
# THE COMMITTED RECORD IS NEVER TOUCHED.  Stages 7 to 11 need a record
# to write into, so they build a SCRATCH CHECKOUT under $TMPDIR -- the
# tooling copied, data/, gfx/, lang/ and src/ symlinked, the engine hard
# linked or copied, an empty playthrough/ tree -- and drive the pipeline
# there.  The real playthrough/frames, manifest, sidecars, save tree and
# media are inputs to nothing here and are asserted untouched at the end.
# The scratch record is a PROOF, not evidence: it is discarded, it is
# never committed, and no claim about the survivor's session is drawn
# from it.
#
# WHAT EACH STAGE ESTABLISHES
#
#   1  platform    env.sh's dated support table accepts this release,
#                  the trust state is `trusted`, and no trust bypass
#                  and no platform waiver is in force.  This is the
#                  stage that fails on an end-of-life host, and it is
#                  the reason the other ten cannot run there
#   2  toolchain   every tool env.sh requires is present, with the
#                  version of each recorded
#   3  python      the interpreter resolves, its pinned closure is
#                  consistent, all six declared libraries import, and
#                  ocr_clock.py's own dependency preflight passes
#   4  engine      the binary exists and reports +tiles, so the SDL
#                  tiles build is what would be photographed
#   5  display     an authenticated X server at the contracted geometry,
#                  through env.sh's own composite check
#   6  scratch     a checkout the proof can write in
#   7  launch      launch_game.sh brings the engine up IN the scratch
#                  checkout, which is the stage whose capture
#                  preconditions refuse under a bypass
#   8  capture     session.py delivers real keystrokes and capture.sh
#                  KEEPS the frames: production frames on disk, with a
#                  manifest row, a telemetry row and a digest
#                  attestation for each.  A kept frame is the thing a
#                  diagnostic host cannot produce
#   9  render      timeline.py, make_transitions.py and render_movie.py
#                  turn that record into an encoded film
#  10  captions    make_srt.py and embed_captions.sh put a selectable
#                  mov_text track on it
#  11  teardown    the instance is stopped, the scratch tree removed,
#                  and the committed record shown unchanged
#
# EXIT STATUS
#     0   every stage passed: a session can be recorded here
#     3   at least one stage failed; each failure is named on stderr as
#         it happens and counted in PREFLIGHT_FAILURES at the end
#     1   env.sh itself refused, or this checkout is not one -- the
#         status playthrough_die exits with, before any stage runs
#
# STDOUT IS A MACHINE CONTRACT: KEY=value lines only, in stage order.
# All logging, warnings and diagnosis go to stderr.
# ---------------------------------------------------------------------
set -o errexit
set -o nounset
set -o pipefail

readonly EX_OK=0
readonly EX_FAILED=3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

# env.sh resolves the repository root from its own location and refuses a
# root that does not look like this checkout, so it is sourced before
# anything else and its answer is used rather than a second guess.
# The `source=` directive lets `shellcheck -x` follow env.sh; the paired
# disable silences SC1091 for a run whose working directory makes the
# relative path unresolvable, which is a fact about the invocation and
# not about this file.  The siblings in this directory pair them the
# same way.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/env.sh"

readonly REPO_ROOT="${PLAYTHROUGH_REPO_ROOT}"

FAILURES=0
STAGE=0
SCRATCH_BASE=""
SCRATCH=""
WINDOW_ID=""
COMMITTED_BEFORE=""

note() {
    printf '%s=%s\n' "$1" "$2"
}

stage_begin() {
    STAGE=$((STAGE + 1))
    printf '\n' >&2
    playthrough_log "stage ${STAGE}/11: $1"
}

stage_failed() {
    FAILURES=$((FAILURES + 1))
    playthrough_warn "STAGE ${STAGE} FAILED: $*"
    note "PREFLIGHT_STAGE_${STAGE}" "fail"
    return 0
}

stage_passed() {
    note "PREFLIGHT_STAGE_${STAGE}" "pass"
    return 0
}

# ---------------------------------------------------------------------
# 1  THE PLATFORM AND THE TRUST STATE
#
# The classification is recomputed by playthrough_check_platform on every
# call and its exported variables are outputs only -- whatever a caller
# sets is discarded -- so reading them here is a measurement that cannot
# be forged by the environment this script was started in.
# ---------------------------------------------------------------------
stage_platform() {
    playthrough_check_platform || true
    playthrough_trust_refresh || true
    note PLATFORM "${PLAYTHROUGH_PLATFORM}"
    note PLATFORM_EOL "${PLAYTHROUGH_PLATFORM_EOL}"
    note PLATFORM_SUPPORTED "${PLAYTHROUGH_PLATFORM_SUPPORTED}"
    note PLATFORM_SOURCE "${PLAYTHROUGH_PLATFORM_SOURCE}"
    note PLATFORM_WAIVER "${PLAYTHROUGH_PLATFORM_WAIVER}"
    note TRUST_STATE "${PLAYTHROUGH_TRUST_STATE}"
    note TRUST_BYPASSES "${PLAYTHROUGH_TRUST_BYPASSES}"
    local ok=0
    if [ "${PLAYTHROUGH_PLATFORM_SUPPORTED}" != "yes" ]; then
        playthrough_warn "'${PLAYTHROUGH_PLATFORM}' is not a release" \
            "env.sh's support table accepts" \
            "(PLATFORM_SUPPORTED=${PLAYTHROUGH_PLATFORM_SUPPORTED})." \
            "This is the stage an out-of-support host fails, and no" \
            "later stage can pass here: build the declared" \
            "environment instead --" \
            "playthrough/tooling/supported_env.sh build -- and run" \
            "this preflight inside it with 'supported_env.sh" \
            "preflight'."
        ok=1
    fi
    if [ -n "${PLAYTHROUGH_TRUST_BYPASSES}" ]; then
        playthrough_warn "a trust bypass is in force" \
            "(${PLAYTHROUGH_TRUST_BYPASSES}), so every production" \
            "stage refuses by design.  A preflight run under a bypass" \
            "would prove nothing about a host that can record, which" \
            "is the only question this file asks: unset it and run on" \
            "a release that does not need it."
        ok=1
    fi
    if [ "${PLAYTHROUGH_TRUST_STATE}" != "trusted" ]; then
        playthrough_warn "the trust state is" \
            "'${PLAYTHROUGH_TRUST_STATE}', not 'trusted'." \
            "$(playthrough_trust_explain || true)"
        ok=1
    fi
    return "${ok}"
}

# ---------------------------------------------------------------------
# 2  THE TOOLCHAIN
#
# playthrough_require_tools with no arguments is env.sh's own list, so
# this cannot drift from what the pipeline actually calls.  The versions
# are recorded because "present" and "the version this was verified
# against" are different facts and a report that conflates them is the
# report that hides an upgrade.
# ---------------------------------------------------------------------
stage_toolchain() {
    playthrough_require_tools || return 1
    # The COMMAND names, not package names: probing a package name runs a
    # command that does not exist, and the first draft reported
    # bash's own "xvfb: command not found" -- which begins with this
    # script's path -- as Xvfb's version.  The key is uppercased because
    # this file's stdout contract is KEY=value with the key in capitals,
    # so the exact spelling of the tool travels in the VALUE.
    local tool key
    for tool in Xvfb openbox xdotool xauth convert identify ffmpeg \
                ffprobe tesseract; do
        key="TOOL_$(printf '%s' "${tool}" |
            tr '[:lower:]' '[:upper:]')"
        note "${key}" "${tool} $(tool_version "${tool}")"
    done
    return 0
}

# tool_version NAME -- one line naming NAME's version, or 'unknown'.
#
# The three spellings are tried in turn because this toolchain uses all
# three -- ffmpeg answers --version, xauth answers -V, xdpyinfo answers
# -version -- and Xvfb answers none of them, so a tool with no version
# flag at all falls through to the packaging system and then to an
# honest 'unknown'.  A line that is the tool's usage text rather than
# its version is rejected: it contains digits and would otherwise be
# reported as a version.
#
# Every probe reads /dev/null, so a tool that treats an unknown option
# as a request to read a script from stdin cannot stall this stage.
tool_version() {
    local name="$1"
    if ! command -v "${name}" >/dev/null 2>&1; then
        # Unreachable while playthrough_require_tools has just passed,
        # and answered anyway: running a name that is not a command
        # reports the SHELL's complaint, and a complaint that quotes a
        # path reads exactly like a version that is a path.
        printf 'ABSENT'
        return 0
    fi
    local flag line
    for flag in --version -V -version; do
        line="$("${name}" "${flag}" 2>&1 </dev/null | head -n 1 ||
            true)"
        case "${line}" in
            *[Uu]nrecognized*|*[Ii]nvalid*|*sage:*|*"not recognized"*)
                continue ;;
        esac
        case "${line}" in
            *[0-9]*) printf '%s' "${line}" | tr -d '\r' | cut -c1-90
                     return 0 ;;
        esac
    done
    if command -v dpkg-query >/dev/null 2>&1; then
        # Both spellings, because a command and its package differ in
        # case exactly where it matters here: the Xvfb binary ships in
        # the `xvfb` package, and Xvfb is the tool with no version flag.
        local candidate
        for candidate in "${name}" \
                "$(printf '%s' "${name}" | tr '[:upper:]' '[:lower:]')"
        do
            line="$(dpkg-query -W -f='${Version}' "${candidate}" \
                2>/dev/null || true)"
            if [ -n "${line}" ]; then
                printf '%s (package %s)' "${line}" "${candidate}"
                return 0
            fi
        done
    fi
    printf 'unknown'
}

# ---------------------------------------------------------------------
# 3  THE PINNED PYTHON CLOSURE
#
# `pip check` answers consistency, the import probe answers presence, and
# ocr_clock.py --preflight answers the one contract capture.sh turns into
# a hard failure -- a Pillow older than the pin, which would otherwise
# report every frame of a session as unreadable while every count still
# tallied.
# ---------------------------------------------------------------------
stage_python() {
    note PYTHON "${PLAYTHROUGH_PYTHON}"
    note PYTHON_VERSION "${PLAYTHROUGH_PYTHON_VERSION-unknown}"
    local ok=0
    if ! "${PLAYTHROUGH_PYTHON}" -m pip check >/dev/null 2>&1; then
        playthrough_warn "pip reports a broken requirement in" \
            "${PLAYTHROUGH_PYTHON}; install" \
            "playthrough/tooling/requirements.lock into it"
        ok=1
    else
        note PIP_CHECK ok
    fi
    if "${PLAYTHROUGH_PYTHON}" -c '
import importlib
for name in ("moviepy", "PIL", "pytesseract", "numpy", "imageio",
             "imageio_ffmpeg"):
    importlib.import_module(name)
' >/dev/null 2>&1; then
        note PYTHON_IMPORTS ok
    else
        playthrough_warn "one of the six declared libraries does not" \
            "import in ${PLAYTHROUGH_PYTHON}"
        ok=1
    fi
    if "${PLAYTHROUGH_PYTHON}" \
            "${PLAYTHROUGH_TOOLING_DIR}/ocr_clock.py" --preflight \
            >/dev/null 2>&1; then
        note OCR_PREFLIGHT ok
    else
        playthrough_warn "ocr_clock.py --preflight fails, so" \
            "capture.sh would refuse every frame as a clock fault"
        ok=1
    fi
    return "${ok}"
}

# ---------------------------------------------------------------------
# 4  THE ENGINE
#
# The binary is never tracked, so a fresh checkout of a supported host
# has none and the honest answer is to say so and name the command that
# builds it -- which is why the declared environment carries a compiler.
# ---------------------------------------------------------------------
stage_engine() {
    # PLAYTHROUGH_GAME_BIN is ABSOLUTE (env.sh:1385 builds it from the
    # repository root), while PLAYTHROUGH_GAME_BIN_ARG carries the
    # relative form the engine is invoked with.  Prefixing the root onto
    # the absolute one is how this stage first reported a missing engine
    # that was sitting in front of it.
    if [ ! -e "${PLAYTHROUGH_GAME_BIN}" ]; then
        playthrough_warn "there is no engine at" \
            "$(playthrough_rel "${PLAYTHROUGH_GAME_BIN}").  It is a" \
            "build product and is never tracked; build it here with" \
            "'playthrough/tooling/launch_game.sh build'."
        return 1
    fi
    local version
    # --version prints the build line and the feature line SEPARATELY,
    # with a blank line between them, so the whole output is collapsed
    # onto one line: reading only the first would drop the '+tiles' this
    # stage exists to find.
    version="$("${PLAYTHROUGH_GAME_BIN}" --version 2>&1 </dev/null |
        tr '\n' ' ' | tr -s ' ' || true)"
    note ENGINE "$(playthrough_rel "${PLAYTHROUGH_GAME_BIN}")"
    note ENGINE_VERSION "${version}"
    case "${version}" in
        *+tiles*) ;;
        *)
            playthrough_warn "the engine does not" \
                "report '+tiles' ('${version}'): either it is the" \
                "curses build, which this pipeline may not use, or" \
                "its shared libraries are unsatisfied on this" \
                "release.  Rebuild it here."
            return 1
            ;;
    esac
    return 0
}

# ---------------------------------------------------------------------
# 5  THE DISPLAY
#
# playthrough_headless_up is the composite env.sh already uses: the
# platform, the video driver (never `dummy`, which renders no pixels and
# is the regression the luminance gate exists to catch), the X server,
# the window manager, access control, and the geometry.
# ---------------------------------------------------------------------
stage_display() {
    playthrough_headless_up || return 1
    note DISPLAY "${PLAYTHROUGH_DISPLAY}"
    note SCREEN "${PLAYTHROUGH_SCREEN}"
    note XAUTHORITY_ORIGIN "${PLAYTHROUGH_XAUTHORITY_ORIGIN-}"
    return 0
}

# ---------------------------------------------------------------------
# 6  THE SCRATCH CHECKOUT
#
# The tooling is COPIED rather than symlinked because env.sh derives the
# repository root from its own location: a symlinked script would resolve
# back to the committed tree, which is the one tree this must not write
# to.  The read-only inputs are symlinked because they are large and
# unchanged.  The engine is hard linked when the filesystem allows and
# copied otherwise, because playthrough_verify_executable judges the
# ancestors of the path it resolves to and a link into $TMPDIR keeps that
# answer the same as the real checkout's.
# ---------------------------------------------------------------------
stage_scratch() {
    SCRATCH_BASE="$(mktemp -d "${TMPDIR:-/tmp}/playthrough-pre-XXXXXX")"
    SCRATCH="${SCRATCH_BASE}/checkout"
    mkdir -p "${SCRATCH}/playthrough/tooling" || return 1
    # EXACTLY the entries launch_game.sh's assert_repo_root demands --
    # data, gfx, lang, src/path_info.cpp and Makefile -- because a
    # scratch checkout missing any of them is refused as "not the root of
    # a Cataclysm-DDA checkout", which is the refusal that first stopped
    # this stage.  Every one is a read-only input here, so a symlink to
    # the real checkout's copy is both correct and cheap; nothing in the
    # pipeline writes to any of them.
    local name
    for name in data gfx lang src Makefile; do
        [ -e "${REPO_ROOT}/${name}" ] || {
            playthrough_warn "the checkout has no ${name}, which" \
                "launch_game.sh requires at the root before it will" \
                "launch anything"
            return 1
        }
        if [ "${name}" = "gfx" ]; then
            # gfx/ IS COPIED, NOT LINKED, and the reason is a check
            # working exactly as designed.  launch_game.sh canonicalises
            # the installed tileset and refuses one that resolves outside
            # the checkout -- artwork under gfx/ is git-ignored, so the
            # tracked provenance anchor is the only statement of which
            # bytes may be rendered, and a symlink could point the whole
            # directory anywhere after the anchor was consulted.  A
            # symlinked gfx/ canonicalises to the REAL checkout and is
            # rightly refused, so the scratch tree gets its own copy.
            # It is 8 MB.
            cp -pR "${REPO_ROOT}/${name}" "${SCRATCH}/${name}" ||
                return 1
        else
            ln -s "${REPO_ROOT}/${name}" "${SCRATCH}/${name}" ||
                return 1
        fi
    done
    # THE WHOLE TOOLING DIRECTORY, not a list of extensions.  A list is
    # a second place to keep in step with the first, and it was already
    # wrong once: it copied *.sh, *.py, *.txt and *.lock, which silently
    # left out tileset_provenance.json -- the tracked anchor that says
    # which bytes the git-ignored artwork under gfx/ must be -- so
    # launch_game.sh refused to render against artwork it could not
    # verify.  It was right to refuse; the omission was the defect.
    cp -pR "${PLAYTHROUGH_TOOLING_DIR}/." \
        "${SCRATCH}/playthrough/tooling/" || return 1
    # The engine's own file name, taken from the argument form the
    # engine is launched with rather than assumed, so the scratch
    # checkout carries it at exactly the path launch_game.sh looks for.
    local engine_name="${PLAYTHROUGH_GAME_BIN_ARG#./}"
    local engine="${PLAYTHROUGH_GAME_BIN}"
    if ! ln "${engine}" "${SCRATCH}/${engine_name}" 2>/dev/null; then
        cp -p "${engine}" "${SCRATCH}/${engine_name}" || return 1
    fi
    note SCRATCH_CHECKOUT "${SCRATCH}"
    note SCRATCH_ENGINE_BYTES "$(wc -c <"${SCRATCH}/${engine_name}")"
    return 0
}

# scratch_run CMD... -- run CMD in the scratch checkout.
#
# The environment is reset to the scratch root so that every
# repository-relative default inside the pipeline -- the frames
# directory, the manifest, the sidecars, the userdir -- resolves there
# and not in the committed tree.  PLAYTHROUGH_REPO_ROOT is unset rather
# than repointed: each script re-derives it from its own location, and a
# stale value in the environment is exactly the way a stage would write
# into the wrong tree.
scratch_run() {
    (
        cd "${SCRATCH}" || exit 1
        # AN ALLOWLIST, NOT A DENYLIST, and it was a denylist first.
        #
        # Every PLAYTHROUGH_* variable this shell exports describes THE
        # REAL CHECKOUT, and each script re-derives its own from its own
        # location -- so any one of them left in the environment is a
        # chance for the scratch run to be told about the wrong tree.
        # Naming the ones to drop meant keeping that list in step with
        # env.sh forever, and it was already incomplete: the first draft
        # missed PLAYTHROUGH_GAME_BIN, so session.py authenticated the
        # window against the REAL checkout's engine, found the scratch
        # engine behind it, and correctly refused to send a key to a
        # process it could not identify as its own.  The refusal was
        # right; the leak was the defect.
        #
        # So everything with the prefix goes, except the two that name
        # the interpreter -- they point into /opt, belong to no checkout,
        # and re-resolving them would find a different interpreter.
        local name
        for name in ${!PLAYTHROUGH_@}; do
            case "${name}" in
                PLAYTHROUGH_PYTHON|PLAYTHROUGH_VENV) continue ;;
            esac
            unset "${name}"
        done
        exec "$@"
    )
}

# ---------------------------------------------------------------------
# 7  THE LAUNCH
#
# `all` is build (the binary is already there, so this proves it),
# headless, tileset (the REQUIRED MSXotto+ pack, verified against its
# tracked anchor), probe and launch.  Its capture preconditions are one
# of the four gates a bypass closes, so reaching a window id here is the
# proof that this gate opened.
# ---------------------------------------------------------------------
stage_launch() {
    # THE FIRST LAUNCH OF A FRESH USERDIR IS A CALIBRATION LAUNCH, and
    # launch_game.sh says so itself: with no
    # playthrough/userdir/config/options.json the engine has never
    # written its config tree, so it opens a 640x384 window on a "Select
    # your language" prompt, the launcher takes the instance down again
    # and prints "NEXT: seed the option values ... then run this script
    # again to take the launch that is captured."  A scratch checkout is
    # a fresh userdir by construction, so this stage performs the whole
    # documented sequence -- calibrate, seed, launch -- rather than
    # reporting the calibration launch's empty window id as a failure.
    if ! launch_once calibration; then
        return 1
    fi
    if [ -z "${WINDOW_ID}" ]; then
        local options="${SCRATCH}/playthrough/userdir/config/\
options.json"
        if [ ! -f "${options}" ]; then
            playthrough_warn "the calibration launch produced no" \
                "window id AND no options file, so the engine never" \
                "wrote its configuration; its log follows"
            tail -n 30 "${SCRATCH_BASE}/launch-calibration.err" >&2 ||
                true
            return 1
        fi
        note LAUNCH_CALIBRATED yes
        if ! scratch_run "${PLAYTHROUGH_PYTHON}" \
                "${SCRATCH}/playthrough/tooling/seed_options.py" \
                >"${SCRATCH_BASE}/seed.out" \
                2>"${SCRATCH_BASE}/seed.err"; then
            playthrough_warn "seed_options.py failed against the" \
                "config tree the calibration launch wrote; its" \
                "diagnosis follows"
            tail -n 25 "${SCRATCH_BASE}/seed.err" >&2 || true
            return 1
        fi
        note LAUNCH_OPTIONS_SEEDED yes
        if ! launch_once captured; then
            return 1
        fi
    fi
    if [ -z "${WINDOW_ID}" ]; then
        # The launcher's own log matters MORE here than on a non-zero
        # exit: a stage that exits zero and produces nothing is the case
        # an operator has no other way to explain.  Showing it only on
        # failure is what made this look like a silent refusal.
        playthrough_warn "launch_game.sh exited 0 but reported no" \
            "window id even after the options were seeded, so there is" \
            "no instance for a capture to photograph; its own log" \
            "follows"
        tail -n 30 "${SCRATCH_BASE}/launch-captured.err" >&2 || true
        return 1
    fi
    return 0
}

# launch_once LABEL -- one `launch_game.sh all`, its keys read back.
#
# Sets WINDOW_ID (empty when the launcher took the instance down again,
# which is what a calibration launch does) and notes the geometry and the
# UI state the launcher VERIFIED -- not one it was told.  Returns
# non-zero only when the launcher itself failed.
launch_once() {
    local label="$1"
    # The key prefix is UPPERCASED because this file's stdout contract is
    # KEY=value with the key in capitals, and a lowercased label smuggled
    # LAUNCH_calibration_WINDOW_ID past it.
    local prefix
    prefix="LAUNCH_$(printf '%s' "${label}" |
        tr '[:lower:]' '[:upper:]')"
    local log="${SCRATCH_BASE}/launch-${label}.err"
    local out=""
    if ! out="$(scratch_run bash \
            "${SCRATCH}/playthrough/tooling/launch_game.sh" all \
            2>"${log}")"; then
        playthrough_warn "launch_game.sh all failed on the ${label}" \
            "launch in the scratch checkout; its diagnosis follows"
        tail -n 30 "${log}" >&2 || true
        return 1
    fi
    WINDOW_ID="$(printf '%s\n' "${out}" |
        sed -n 's/^PLAYTHROUGH_WINDOW_ID=//p' | tail -n 1)"
    note "${prefix}_WINDOW_ID" "${WINDOW_ID}"
    note "${prefix}_WINDOW_GEOMETRY" \
        "$(printf '%s\n' "${out}" |
            sed -n 's/^PLAYTHROUGH_WINDOW_GEOMETRY=//p' | tail -n 1)"
    note "${prefix}_UI_STATE" \
        "$(printf '%s\n' "${out}" |
            sed -n 's/^PLAYTHROUGH_INITIAL_UI_STATE=//p' | tail -n 1)"
    # THE ARTWORK, ON THE RECORD.  The tileset is part of what a
    # capture-capable environment has to contain, and launch_game.sh
    # verifies the installed pack against the tracked provenance anchor
    # before it will render anything -- so the verdict belongs in this
    # file's own machine contract rather than only in the launcher's log,
    # where a caller would have to go looking for it.
    local key
    # PLAYTHROUGH_TILESET_REQUIRED_PRESENT is deliberately NOT among
    # these: `all` does not emit it (only `status` does), so it would be
    # a permanently empty key -- and a key that is always empty is one a
    # consumer learns to ignore.  ORIGIN=required-installed already says
    # the required pack is the one installed and verified.
    for key in TILESET_RESOLVED TILESET_VIEW TILESET_ORIGIN; do
        note "${prefix}_${key}" \
            "$(printf '%s\n' "${out}" |
                sed -n "s/^PLAYTHROUGH_${key}=//p" | tail -n 1)"
    done
    return 0
}

# ---------------------------------------------------------------------
# 8  A REAL PRODUCTION CAPTURE, THROUGH session.py
#
# Not `capture.sh` alone: session.py is what owns the keystroke and the
# counter, and driving it is what proves the invariant the whole record
# rests on -- one keystroke, one KEPT frame, one manifest row, one
# telemetry row, one digest attestation.  Two steps, because one frame
# cannot show that the counter advances.
#
# The two keys are deliberately inert: Escape withdraws from whatever
# screen the launch opened on, and a preflight that pressed something
# consequential would be a preflight nobody could run twice.
#
# THE COMMENTARY IS IN THE SURVIVOR'S VOICE BECAUSE manifest.py REFUSES
# ANYTHING ELSE, and it is right to: a row's commentary goes verbatim
# into playthrough/transcript.md and becomes a caption on the film, so
# the gate rejects engineering vocabulary before the row exists rather
# than after.  The first draft of this stage said "a preflight keystroke"
# and was refused for the word "keystroke".  The sentence used here is
# deliberately neutral -- it claims nothing about a session that did not
# happen -- and SHORT, because make_srt.py refuses a cue that does not
# fit two lines of 42 columns and the second draft was three lines long.
# Both refusals are the pipeline holding this file to the same standard
# as the record, which is the point.  The rows live in the scratch
# checkout, which is removed in stage 11 and is never committed: nothing
# here writes to the real record, and stage 11 proves that rather than
# promising it.
# ---------------------------------------------------------------------
stage_capture() {
    local step
    for step in 1 2; do
        if ! scratch_run "${PLAYTHROUGH_PYTHON}" \
                "${SCRATCH}/playthrough/tooling/session.py" \
                step --key Escape \
                --note "hold still and look before choosing" \
                --commentary "I hold still and look before I choose." \
                --window-id "${WINDOW_ID}" \
                >"${SCRATCH_BASE}/step${step}.out" \
                2>"${SCRATCH_BASE}/step${step}.err"; then
            playthrough_warn "session.py step ${step} failed; its" \
                "diagnosis follows"
            tail -n 25 "${SCRATCH_BASE}/step${step}.err" >&2 || true
            return 1
        fi
    done
    local frames rows telemetry digests
    frames="$(find "${SCRATCH}/playthrough/frames" -name 'frame_*.png' \
        -type f 2>/dev/null | wc -l)"
    rows="$(wc -l <"${SCRATCH}/playthrough/manifest.jsonl" 2>/dev/null ||
        printf '0')"
    telemetry="$(wc -l \
        <"${SCRATCH}/playthrough/build/observations.jsonl" \
        2>/dev/null || printf '0')"
    digests="$(wc -l \
        <"${SCRATCH}/playthrough/build/frame_digests.jsonl" \
        2>/dev/null || printf '0')"
    note CAPTURE_FRAMES "${frames}"
    note CAPTURE_MANIFEST_ROWS "${rows}"
    note CAPTURE_TELEMETRY_ROWS "${telemetry}"
    note CAPTURE_DIGEST_ROWS "${digests}"
    if [ "${frames}" -ne 2 ] || [ "${rows}" -ne 2 ] ||
       [ "${telemetry}" -ne 2 ] || [ "${digests}" -ne 2 ]; then
        playthrough_warn "two keystrokes must leave exactly two kept" \
            "frames, two manifest rows, two telemetry rows and two" \
            "digest attestations; this host produced" \
            "${frames}/${rows}/${telemetry}/${digests}"
        return 1
    fi
    local first="${SCRATCH}/playthrough/frames/frame_00001.png"
    note CAPTURE_GEOMETRY "$("${PLAYTHROUGH_BIN_IDENTIFY}" \
        -format '%wx%h' "${first}")"
    note CAPTURE_LUMA "$("${PLAYTHROUGH_BIN_CONVERT}" "${first}" \
        -colorspace Gray \
        -format '%[fx:mean] %[fx:standard_deviation]' info:)"
    # The record's own verifier, over the record this stage just built.
    if ! scratch_run "${PLAYTHROUGH_PYTHON}" \
            "${SCRATCH}/playthrough/tooling/manifest.py" verify \
            >/dev/null 2>&1; then
        playthrough_warn "manifest.py verify rejects the record this" \
            "capture produced"
        return 1
    fi
    note CAPTURE_RECORD_VERIFIED yes
    return 0
}

# ---------------------------------------------------------------------
# 9  THE RENDER
#
# timeline.py computes the durations, make_transitions.py materialises
# whatever the ceiling asks for (nothing, on a two-frame record) and
# render_movie.py encodes.  assert_trusted_render is the third of the
# four gates a bypass closes, and an encoded container is the proof it
# opened.
# ---------------------------------------------------------------------
stage_render() {
    local tool
    for tool in timeline.py make_transitions.py render_movie.py; do
        if ! scratch_run "${PLAYTHROUGH_PYTHON}" \
                "${SCRATCH}/playthrough/tooling/${tool}" \
                >"${SCRATCH_BASE}/${tool}.out" \
                2>"${SCRATCH_BASE}/${tool}.err"; then
            playthrough_warn "${tool} failed in the scratch checkout;" \
                "its diagnosis follows"
            tail -n 25 "${SCRATCH_BASE}/${tool}.err" >&2 || true
            return 1
        fi
    done
    local movie="${SCRATCH}/playthrough/cata-play.mp4"
    [ -s "${movie}" ] || {
        playthrough_warn "render_movie.py reported success but wrote" \
            "no film"
        return 1
    }
    note RENDER_MOVIE_BYTES "$(wc -c <"${movie}")"
    note RENDER_VIDEO "$("${PLAYTHROUGH_BIN_FFPROBE}" -v error \
        -select_streams v:0 \
        -show_entries stream=codec_name,width,height \
        -of csv=p=0 "${movie}")"
    return 0
}

# ---------------------------------------------------------------------
# 10  THE CAPTIONS
#
# make_srt.py renders the cue file from the same timeline the film was
# encoded from, and embed_captions.sh muxes it.  That mux is the fourth
# gate, and a mov_text stream tagged eng is the proof it opened.
# ---------------------------------------------------------------------
stage_captions() {
    if ! scratch_run "${PLAYTHROUGH_PYTHON}" \
            "${SCRATCH}/playthrough/tooling/make_srt.py" \
            >"${SCRATCH_BASE}/make_srt.out" \
            2>"${SCRATCH_BASE}/make_srt.err"; then
        playthrough_warn "make_srt.py failed; its diagnosis follows"
        tail -n 25 "${SCRATCH_BASE}/make_srt.err" >&2 || true
        return 1
    fi
    if ! scratch_run bash \
            "${SCRATCH}/playthrough/tooling/embed_captions.sh" \
            >"${SCRATCH_BASE}/embed.out" \
            2>"${SCRATCH_BASE}/embed.err"; then
        playthrough_warn "embed_captions.sh failed; its diagnosis" \
            "follows"
        tail -n 25 "${SCRATCH_BASE}/embed.err" >&2 || true
        return 1
    fi
    local captioned="${SCRATCH}/playthrough/cata-play-cc.mp4"
    [ -s "${captioned}" ] || {
        playthrough_warn "embed_captions.sh reported success but" \
            "wrote no captioned film"
        return 1
    }
    note CAPTION_MOVIE_BYTES "$(wc -c <"${captioned}")"
    note CAPTION_STREAM "$("${PLAYTHROUGH_BIN_FFPROBE}" -v error \
        -select_streams s -show_entries \
        stream=codec_name:stream_tags=language -of csv=p=0 \
        "${captioned}" | head -n 1)"
    return 0
}

# ---------------------------------------------------------------------
# 11  TEARDOWN
#
# The instance is stopped through launch_game.sh's own `stop`, which is
# documented as terminating a CALIBRATION instance without saving --
# exactly what a preflight instance is.  Then the committed record is
# shown to be what it was before this ran.
# ---------------------------------------------------------------------
stage_teardown() {
    if [ -n "${SCRATCH}" ] && [ -d "${SCRATCH}" ]; then
        scratch_run bash \
            "${SCRATCH}/playthrough/tooling/launch_game.sh" stop \
            >/dev/null 2>&1 || true
    fi
    local after=""
    if [ -n "${COMMITTED_BEFORE}" ]; then
        after="$(committed_state)"
        note COMMITTED_RECORD_BEFORE "${COMMITTED_BEFORE}"
        note COMMITTED_RECORD_AFTER "${after}"
        if [ "${after}" != "${COMMITTED_BEFORE}" ]; then
            playthrough_warn "THE COMMITTED RECORD CHANGED while this" \
                "preflight ran: '${COMMITTED_BEFORE}' before," \
                "'${after}' after.  Every stage writes into a scratch" \
                "checkout precisely so that this cannot happen;" \
                "inspect 'git status playthrough/' before anything" \
                "else."
            return 1
        fi
    fi
    if [ -n "${SCRATCH_BASE}" ] && [ -d "${SCRATCH_BASE}" ]; then
        case "${SCRATCH_BASE}" in
            "${TMPDIR:-/tmp}"/playthrough-pre-*)
                rm -rf -- "${SCRATCH_BASE}"
                note SCRATCH_REMOVED yes
                ;;
            *)
                playthrough_warn "refusing to remove" \
                    "'${SCRATCH_BASE}': it is not a path this run" \
                    "created"
                ;;
        esac
    fi
    return 0
}

# committed_state -- a one-line fingerprint of the committed record.
#
# The frame count, the row counts and git's own opinion of the tree, so
# that a stage which wrote into the wrong checkout is visible as a
# changed fingerprint rather than having to be noticed.
committed_state() {
    local frames rows dirty
    frames="$(find "${REPO_ROOT}/playthrough/frames" -name 'frame_*.png' \
        -type f 2>/dev/null | wc -l)"
    rows="$(wc -l <"${REPO_ROOT}/playthrough/manifest.jsonl" \
        2>/dev/null || printf '0')"
    # git IS ASKED CONDITIONALLY, because this file is documented as
    # runnable directly on any supported host and such a host may hold an
    # export rather than a clone.  Piping a failing `git status` into
    # `wc` under `set -o pipefail` fails the assignment and, under
    # errexit, ends the whole preflight -- so the absence of a work tree
    # is REPORTED as what it is and the frame and row counts still carry
    # the comparison.
    if command -v git >/dev/null 2>&1 &&
       git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree \
           >/dev/null 2>&1; then
        dirty="$(git -C "${REPO_ROOT}" status --porcelain playthrough/ |
            wc -l)"
    else
        dirty="not-a-git-tree"
    fi
    printf 'frames=%s rows=%s dirty=%s' \
        "${frames}" "${rows}" "${dirty}"
}

run_stage() {
    local name="$1"
    local fn="$2"
    stage_begin "${name}"
    if "${fn}"; then
        stage_passed
    else
        stage_failed "${name}"
    fi
    return 0
}

main() {
    # playthrough_die REPORTS and returns 1 rather than exiting, so the
    # exit is taken here explicitly instead of resting on errexit
    # noticing the status of a `||` list.
    if [ ! -d "${REPO_ROOT}/playthrough/tooling" ]; then
        playthrough_die "there is no playthrough/tooling under" \
            "'${REPO_ROOT}', so this is not the checkout whose" \
            "production path this file can prove" || true
        exit 1
    fi
    COMMITTED_BEFORE="$(committed_state)"
    note PREFLIGHT_HOST "$(uname -sr)"
    note PREFLIGHT_REPO_ROOT "${REPO_ROOT}"

    run_stage "the platform and the trust state" stage_platform
    # Nothing below stage 1 can pass while the trust state is not
    # `trusted`, and running them anyway would report ten failures for
    # one cause.  The refusal is the finding; it is reported once.
    if [ "${FAILURES}" -eq 0 ]; then
        run_stage "the toolchain env.sh requires" stage_toolchain
        run_stage "the pinned Python closure" stage_python
        run_stage "the engine" stage_engine
        run_stage "an authenticated headless display" stage_display
    else
        playthrough_warn "stages 2 to 11 were NOT attempted: they all" \
            "depend on the trust state stage 1 measured"
    fi
    if [ "${FAILURES}" -eq 0 ]; then
        run_stage "a scratch checkout to prove into" stage_scratch
    fi
    if [ "${FAILURES}" -eq 0 ]; then
        run_stage "the engine, launched" stage_launch
    fi
    if [ "${FAILURES}" -eq 0 ]; then
        run_stage "a real production capture" stage_capture
    fi
    if [ "${FAILURES}" -eq 0 ]; then
        run_stage "the render" stage_render
    fi
    if [ "${FAILURES}" -eq 0 ]; then
        run_stage "the captions" stage_captions
    fi
    # Teardown runs whatever happened above: an instance left running and
    # a scratch tree left behind are this file's mess to clear.
    # stage_begin takes the next number, so the counter is set to the
    # one BEFORE this stage rather than to this stage's own.
    STAGE=10
    stage_begin "teardown and the committed record"
    if stage_teardown; then
        stage_passed
    else
        stage_failed "teardown"
    fi

    note PREFLIGHT_FAILURES "${FAILURES}"
    if [ "${FAILURES}" -ne 0 ]; then
        note PREFLIGHT "fail"
        playthrough_warn "${FAILURES} stage(s) failed: a session" \
            "CANNOT be recorded on this host as it stands"
        return "${EX_FAILED}"
    fi
    note PREFLIGHT "pass"
    playthrough_log "every stage passed on" \
        "${PLAYTHROUGH_PLATFORM}: this host can record a session," \
        "render it and mux its captions"
    return "${EX_OK}"
}

main "$@"
