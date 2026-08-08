#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/supported_env.sh
#
# BUILD AND ENTER the declared capture environment: the supported release
# that playthrough/tooling/environment/Dockerfile describes.
#
# THE PROBLEM THIS SOLVES.  env.sh refuses to record a session on a
# release that is out of support, and the only way past that refusal --
# PLAYTHROUGH_ALLOW_EOL_PLATFORM -- is a registered TRUST BYPASS that
# moves the trust state to `diagnostic`.  Under `diagnostic`,
# launch_game.sh will not bring up an instance to be captured, capture.sh
# will not keep a frame, render_movie.py will not encode and
# embed_captions.sh will not mux.  On a host past its release's
# end-of-life date -- which is the host this work was done on -- that is
# every production stage refusing at once, and a code review named the
# consequence precisely: the environment in which the pipeline CAN run
# was undeclared and untracked, so neither a re-render nor a compliant
# re-capture could be performed anywhere.  The remedy is to declare it,
# in the repository, as something that can be built from scratch.
#
# WHAT THIS MOVES, AND WHAT IT DOES NOT.  It moves the WORKLOAD onto a
# supported release; it does not move the GATE.  Nothing here sets,
# forwards or weakens a trust bypass, and `run` goes further than not
# forwarding one: it CLEARS every name in env.sh's bypass registry inside
# the container, so a host operating under a waiver cannot leak one in
# through the environment, a compose file or a later edit to this file.
# The preflight then FAILS unless the trust state measured inside is
# `trusted` with no bypasses recorded -- which is the whole point, and is
# a property of the release, not of anything this script asserts.
#
#   build            build the image from the tracked Dockerfile
#   inventory        print what the built image actually contains
#   run CMD [ARG…]   run CMD inside it, with this checkout mounted
#   shell            an interactive shell inside it
#   preflight        prove the production path, by running
#                    playthrough/tooling/preflight_capture.sh inside it
#
# The proof itself lives in preflight_capture.sh, not here, because it is
# worth running directly on a supported host with no container at all.
# This file is only the driver that supplies such a host on demand.
#
# USAGE
#     playthrough/tooling/supported_env.sh build
#     playthrough/tooling/supported_env.sh preflight
#     playthrough/tooling/supported_env.sh run \
#         playthrough/tooling/launch_game.sh status
# ---------------------------------------------------------------------
set -o errexit
set -o nounset
set -o pipefail

readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_MISSING=2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
readonly REPO_ROOT
readonly ENVIRONMENT_DIR="${SCRIPT_DIR}/environment"
readonly IMAGE_TAG="${PLAYTHROUGH_SUPPORTED_IMAGE:-playthrough-capture:26.04}"
readonly INVENTORY_PATH="/opt/playthrough-image-inventory.txt"

# env.sh's registry, restated as a literal.
#
# It is NOT read from env.sh, and that is deliberate rather than lazy:
# sourcing env.sh on an end-of-life host is the refusal this script
# exists to route around, and doing it here would also import the host's
# own waiver into this process -- the one value that must not travel.
# The list is asserted against env.sh's by test_supported_env.py, so the
# copy cannot drift silently.
readonly TRUST_BYPASS_VARS="\
PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES \
PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X \
PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK \
PLAYTHROUGH_ALLOW_TILESET_FALLBACK \
PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW \
PLAYTHROUGH_ALLOW_ANY_COMPILER \
PLAYTHROUGH_ALLOW_EOL_PLATFORM"

log() {
    printf 'playthrough: %s\n' "$*" >&2
}

die() {
    local status="$1"
    shift
    printf 'playthrough: FATAL: %s\n' "$*" >&2
    exit "${status}"
}

require_docker() {
    command -v docker >/dev/null 2>&1 ||
        die "${EX_MISSING}" "docker is not on PATH, so the declared \
environment cannot be built or entered here.  It is declared in \
playthrough/tooling/environment/Dockerfile and needs no feature of \
docker in particular: build it with any OCI builder, or skip the \
container altogether and run playthrough/tooling/preflight_capture.sh \
directly on a host that meets BOTH conditions -- a release env.sh's \
support table accepts (Ubuntu 26.04 LTS, Ubuntu 24.04 LTS, Debian 13 or \
Debian 12) AND an SDL2 runtime of at least 2.32, which is what carries \
keyboard input into the engine's ImGui screens.  Ubuntu 24.04's SDL \
2.30.0 passes the support table and still cannot drive the character \
creator, so it is not a capture host; see the base-image note in \
playthrough/tooling/environment/Dockerfile."
    docker info >/dev/null 2>&1 ||
        die "${EX_MISSING}" "docker is installed but its daemon is not \
reachable, so the image cannot be built or run.  Start the daemon, or \
run preflight_capture.sh directly on a supported release."
}

image_exists() {
    docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1
}

require_image() {
    image_exists ||
        die "${EX_MISSING}" "the image ${IMAGE_TAG} has not been built. \
Run 'playthrough/tooling/supported_env.sh build' first; it takes the \
Dockerfile in playthrough/tooling/environment and needs network access \
for apt and pip."
}

# build -- build the image from the TRACKED Dockerfile.
#
# The build context is playthrough/tooling/environment, which holds the
# Dockerfile and nothing else; the two requirements files it needs are
# copied in beside it for the build and removed afterwards.  A context of
# the whole checkout would send the frames, the media and the save tree
# to the daemon for no reason, and a context of playthrough/tooling would
# send every script -- and then invalidate the image's cached layers on
# every edit to any of them.
do_build() {
    require_docker
    [ -f "${ENVIRONMENT_DIR}/Dockerfile" ] ||
        die "${EX_MISSING}" "there is no \
playthrough/tooling/environment/Dockerfile in this checkout, so the \
declared environment cannot be built"
    local context
    context="$(mktemp -d "${TMPDIR:-/tmp}/playthrough-ctx-XXXXXX")"
    # shellcheck disable=SC2064
    trap "rm -rf -- '${context}'" EXIT
    cp "${ENVIRONMENT_DIR}/Dockerfile" "${context}/" ||
        die "${EX_MISSING}" "cannot stage the Dockerfile"
    cp "${SCRIPT_DIR}/requirements.txt" \
       "${SCRIPT_DIR}/requirements.lock" "${context}/" ||
        die "${EX_MISSING}" "cannot stage requirements.txt and \
requirements.lock, which the image installs the pipeline's pinned \
closure from"
    log "building ${IMAGE_TAG} from \
playthrough/tooling/environment/Dockerfile"
    docker build --tag "${IMAGE_TAG}" "${context}"
    log "built ${IMAGE_TAG}; 'supported_env.sh inventory' lists what \
it contains"
}

do_inventory() {
    require_docker
    require_image
    docker run --rm "${IMAGE_TAG}" cat "${INVENTORY_PATH}"
}

# docker_run TTY_FLAGS… -- the common invocation.
#
# The checkout is mounted at its OWN absolute path, so every
# repository-relative path in the pipeline resolves identically inside
# and outside and a diagnostic quoting a path means the same file to
# both.  /dev/shm is raised because SDL and the X server share memory
# through it and docker's 64 MB default is not enough for a 1920x1080
# surface plus the tile atlases.  The container is given the host's own
# uid so that every file it writes into the mounted checkout belongs to
# whoever will commit it -- root-owned artifacts in a working tree are a
# repair job, not an artifact.
docker_run() {
    local -a extra=()
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
        extra+=("$1")
        shift
    done
    if [ "$#" -gt 0 ]; then
        shift
    fi
    local -a cleared=()
    local name
    for name in ${TRUST_BYPASS_VARS}; do
        cleared+=(--env "${name}=")
    done
    docker run --rm \
        --volume "${REPO_ROOT}:${REPO_ROOT}" \
        --workdir "${REPO_ROOT}" \
        --shm-size=1g \
        --user "$(id -u):$(id -g)" \
        --env "HOME=/tmp/playthrough-home" \
        --env "TMPDIR=/tmp" \
        "${cleared[@]}" \
        "${extra[@]}" \
        "${IMAGE_TAG}" \
        "$@"
}

do_run() {
    require_docker
    require_image
    [ "$#" -gt 0 ] ||
        die "${EX_USAGE}" "run needs a command to run inside the image"
    docker_run -- "$@"
}

do_shell() {
    require_docker
    require_image
    docker_run --interactive --tty -- bash
}

# tree_state -- what git makes of playthrough/, as one comparable line.
#
# git is asked CONDITIONALLY: this driver is usable against an export as
# well as a clone, and piping a failing `git status` into `wc` under
# `set -o pipefail` would fail the assignment and, under errexit, end the
# run with a message about the working tree rather than about docker.
# When there is no work tree to consult, that is reported as itself --
# the comparison then proves nothing, and saying so is better than a
# comparison of two empty strings that always agrees.
tree_state() {
    if command -v git >/dev/null 2>&1 &&
       git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree \
           >/dev/null 2>&1; then
        printf 'dirty=%s' "$(git -C "${REPO_ROOT}" status --porcelain \
            playthrough/ | wc -l)"
    else
        printf 'not-a-git-tree'
    fi
}

# preflight -- prove the production path inside the declared environment.
#
# The proof is preflight_capture.sh, unchanged and unassisted: this
# subcommand's only contribution is the supported release it runs on.
# The working tree is fingerprinted on both sides of the run as well,
# because the preflight's own promise -- that it writes only into a
# scratch checkout -- is worth checking from outside the thing making it.
do_preflight() {
    require_docker
    require_image
    local before after
    before="$(tree_state)"
    log "playthrough/ is '${before}' before the preflight; it must be \
the same after"
    local status=0
    docker_run -- bash \
        "${REPO_ROOT}/playthrough/tooling/preflight_capture.sh" ||
        status=$?
    after="$(tree_state)"
    if [ "${after}" != "${before}" ]; then
        die "${EX_MISSING}" "the preflight changed the working tree: \
playthrough/ was '${before}' before it and '${after}' after.  It \
captures into a scratch checkout precisely so that it cannot touch the \
committed record; inspect 'git status playthrough/' before doing \
anything else."
    fi
    if [ "${status}" -ne 0 ]; then
        die "${status}" "the preflight failed inside ${IMAGE_TAG} \
(exit ${status}); the stage that failed is named above.  The committed \
record was not touched."
    fi
    log "PREFLIGHT PASSED inside ${IMAGE_TAG}, and the committed record \
is unchanged"
}

usage() {
    local out="${1:-1}"
    {
        printf '%s\n' "usage: playthrough/tooling/supported_env.sh \
<subcommand> [argument ...]"
        printf '\n'
        printf '  %-16s %s\n' \
            "build" "build the declared capture image" \
            "inventory" "print what the built image contains" \
            "run CMD [ARG…]" "run CMD inside it, this checkout mounted" \
            "shell" "an interactive shell inside it" \
            "preflight" "prove the production path inside it"
        printf '\n'
        printf '%s\n' "The environment is declared in \
playthrough/tooling/environment/Dockerfile."
        printf '%s\n' "Nothing here relaxes a trust gate: every \
registered trust bypass is"
        printf '%s\n' "cleared inside the container, and preflight \
fails unless the trust state"
        printf '%s\n' "measured there is 'trusted' with none in force."
    } >&"${out}"
}

main() {
    local subcommand="${1-}"
    if [ "$#" -gt 0 ]; then
        shift
    fi
    case "${subcommand}" in
        build) do_build ;;
        inventory) do_inventory ;;
        run) do_run "$@" ;;
        shell) do_shell ;;
        preflight) do_preflight ;;
        help|--help|-h) usage 1 ;;
        "")
            usage 2
            die "${EX_USAGE}" "a subcommand is required"
            ;;
        *)
            usage 2
            die "${EX_USAGE}" "unknown subcommand '${subcommand}'"
            ;;
    esac
    return "${EX_OK}"
}

main "$@"
