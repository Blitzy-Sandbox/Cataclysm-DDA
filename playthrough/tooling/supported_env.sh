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
# A status of its own for "this would end a recorded session outside the
# game's own exit".  It is not a usage error -- the command was spelled
# correctly -- and it is not a missing dependency; it is a refusal about
# the SESSION, and a driver has to be able to tell it apart from both.
readonly EX_LIFECYCLE=3

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
PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW \
PLAYTHROUGH_ALLOW_ANY_COMPILER \
PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY \
PLAYTHROUGH_ALLOW_EOL_PLATFORM"

# escape_controls TEXT -- TEXT with every control byte shown as <NN>.
#
# A LOCAL COPY OF env.sh's, and for the same reason the trust-bypass list
# above is one: this script deliberately does NOT source env.sh, because
# sourcing it on an end-of-life host is the refusal this script exists to
# route around.  So the helper is restated rather than imported.
#
# It matters here because what reaches these diagnostics comes from
# docker -- container ids, image names, labels, mount listings -- and a
# name carrying a newline forges a whole extra line of output, while ESC-[
# or the single-byte C1 CSI (0x9B) repaints the reader's terminal.  The
# byte ranges cover C0, DEL and the C1 block encoded as UTF-8, and leave
# legitimate non-ASCII alone.
# A local LC_ALL makes the walk bytewise whatever the caller's locale
# is -- see env.sh's copy for the measurement that made that necessary
# (in the C locale a character-wise walk silently DELETED the two-byte
# C1 sequence instead of escaping it).  test_supported_env.py asserts
# this copy and env.sh's produce identical output.
escape_controls() {
    local LC_ALL=C
    local out="" rest="${1-}" byte second
    case "${rest}" in
        *[$'\001'-$'\037']*|*$'\177'*) ;;
        *$'\302'[$'\200'-$'\237']*) ;;
        *) printf '%s' "${rest}" ; return 0 ;;
    esac
    while [ -n "${rest}" ]; do
        byte="${rest:0:1}"
        case "${byte}" in
            $'\302')
                second="${rest:1:1}"
                case "${second}" in
                    [$'\200'-$'\237'])
                        out+="$(printf '<%02X>' "'${second}")"
                        rest="${rest:2}"
                        continue
                        ;;
                esac
                ;;
            [$'\001'-$'\037']|$'\177')
                out+="$(printf '<%02X>' "'${byte}")"
                rest="${rest:1}"
                continue
                ;;
        esac
        out+="${byte}"
        rest="${rest:1}"
    done
    printf '%s' "${out}"
}

log() {
    printf 'playthrough: %s\n' "$(escape_controls "$*")" >&2
}

die() {
    local status="$1"
    shift
    printf 'playthrough: FATAL: %s\n' "$(escape_controls "$*")" >&2
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

# build_inputs_digest -- one sha256 over the TRACKED files the image is
# built from, in a fixed order.
#
# These are exactly the three files do_build stages into the build
# context and nothing else, so this digest changes if and only if the
# declared environment changes.  It is what turns "an image with the
# right tag" into "the image this checkout declares", and it is baked
# into the image as a label at build time so the comparison can be made
# later without the build context still existing.
#
# `sha256sum` is fed the files by name in a fixed order and its own
# output is hashed again, so the value depends on the CONTENTS and on
# the order, never on the paths -- which differ between checkouts.
build_inputs_digest() {
    { sha256sum < "${ENVIRONMENT_DIR}/Dockerfile"
      sha256sum < "${SCRIPT_DIR}/requirements.txt"
      sha256sum < "${SCRIPT_DIR}/requirements.lock"
    } | sha256sum | cut -c1-64
}

# resolve_image_id -- the immutable identity behind the tag.
#
# A TAG IS A MUTABLE POINTER AND MUST NEVER BE THE THING COMPARED.  A
# security review made the point exactly: `docker tag` can point
# playthrough-capture:26.04 at any image on the host, and this driver
# then mounts the checkout READ-WRITE into whatever it names.  So the tag
# is resolved to an image ID ONCE, and everything downstream -- the
# provenance check, the container it starts, the adoption check -- uses
# that ID.
#
# .Id is the digest of the image config, which is what identifies a
# LOCALLY BUILT image.  RepoDigests is deliberately not used: measured on
# this host, the built image reports `RepoDigests=[]`, because an image
# that was never pushed or pulled has no registry digest at all, and a
# check keyed on one would be vacuous exactly where it is needed.
resolve_image_id() {
    local id
    id="$(docker image inspect "${IMAGE_TAG}" \
        --format '{{.Id}}' 2>/dev/null || printf '')"
    case "${id}" in
        sha256:*) printf '%s' "${id}" ; return 0 ;;
    esac
    return 1
}

# assert_image_provenance -- the image was built from THIS checkout.
#
# The tag says what somebody called it; the label says what it was built
# from. Without this, `supported_env.sh run` will happily execute an
# arbitrary toolchain that carries the expected tag, with the checkout
# mounted read-write -- which is the finding, stated as a capability.
assert_image_provenance() {
    local id="$1"
    local stamped expected
    expected="$(build_inputs_digest)"
    stamped="$(docker image inspect "${id}" \
        --format "{{index .Config.Labels \"${LABEL_BUILD}\"}}" \
        2>/dev/null || printf '')"
    if [ -z "${stamped}" ] || [ "${stamped}" = "<no value>" ]; then
        die "${EX_MISSING}" "the image ${IMAGE_TAG} (${id}) carries no \
${LABEL_BUILD} label, so it cannot say which Dockerfile and which \
requirements files it was built from.  Images built before that label \
existed are indistinguishable from an arbitrary image wearing this \
tag, and this driver mounts the checkout read-write into what it \
starts, so it is REFUSED rather than trusted.  Rebuild it: \
'playthrough/tooling/supported_env.sh build'."
    fi
    if [ "${stamped}" != "${expected}" ]; then
        die "${EX_MISSING}" "the image ${IMAGE_TAG} (${id}) was built \
from build inputs digesting ${stamped}, and this checkout's \
Dockerfile, requirements.txt and requirements.lock digest to \
${expected}.  The declared environment and the built one are not the \
same thing, so the image is REFUSED: a session proved against one \
environment and recorded in another is not proved at all.  Rebuild it: \
'playthrough/tooling/supported_env.sh build'."
    fi
    return 0
}

# The build context this process created, and the handler that removes
# it.  Declared at file scope so `set -u` reports a missing definition
# rather than treating it as empty, and so the EXIT trap can be a bare
# FUNCTION NAME -- see the note at its assignment in do_build.
BUILD_CONTEXT=""

cleanup_build_context() {
    if [ -n "${BUILD_CONTEXT}" ]; then
        rm -rf -- "${BUILD_CONTEXT}"
        BUILD_CONTEXT=""
    fi
    return 0
}

# require_image -- the image exists, is resolved to an immutable id, and
# was built from this checkout.
#
# IMAGE_ID is published for every caller, so nothing downstream has to
# re-resolve the tag -- re-resolving it would reintroduce the window
# this exists to close, where the tag moves between the check and the
# use.
IMAGE_ID=""
require_image() {
    image_exists ||
        die "${EX_MISSING}" "the image ${IMAGE_TAG} has not been built. \
Run 'playthrough/tooling/supported_env.sh build' first; it takes the \
Dockerfile in playthrough/tooling/environment and needs network access \
for apt and pip."
    IMAGE_ID="$(resolve_image_id)" ||
        die "${EX_MISSING}" "the image ${IMAGE_TAG} exists but docker \
reports no image id for it, so there is no immutable identity to run \
and nothing this driver is willing to mount the checkout into."
    assert_image_provenance "${IMAGE_ID}"
    return 0
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
    # THE TRAP IS A FUNCTION NAME AND THE PATH IS DATA.  It used to be
    # `trap "rm -rf -- '${context}'" EXIT`, which INTERPOLATES a
    # $TMPDIR-derived path into a string bash later EXECUTES -- CWE-78.
    # A security review demonstrated it: a $TMPDIR carrying a single
    # quote and a command substitution executed an injected marker when
    # the trap fired, and `rm -rf` was the command holding it.  The fix
    # is not better quoting; it is to stop composing executable text at
    # all.  BUILD_CONTEXT is a variable the fixed handler reads, so no
    # part of any path is ever parsed as shell.
    BUILD_CONTEXT="${context}"
    trap cleanup_build_context EXIT
    cp "${ENVIRONMENT_DIR}/Dockerfile" "${context}/" ||
        die "${EX_MISSING}" "cannot stage the Dockerfile"
    cp "${SCRIPT_DIR}/requirements.txt" \
       "${SCRIPT_DIR}/requirements.lock" "${context}/" ||
        die "${EX_MISSING}" "cannot stage requirements.txt and \
requirements.lock, which the image installs the pipeline's pinned \
closure from"
    local stamp
    stamp="$(build_inputs_digest)"
    log "building ${IMAGE_TAG} from \
playthrough/tooling/environment/Dockerfile; build inputs digest \
${stamp}"
    # THE LABEL IS THE IMAGE SAYING WHAT IT WAS BUILT FROM.  It is
    # written once, here, at the only moment the answer is known for
    # certain, and it is what assert_image_provenance compares later
    # against the tracked files themselves.
    docker build --tag "${IMAGE_TAG}" \
        --label "${LABEL_BUILD}=${stamp}" "${context}"
    local built
    built="$(resolve_image_id)" || built="<unresolved>"
    log "built ${IMAGE_TAG} as ${built}; 'supported_env.sh inventory' \
lists what it contains"
}

do_inventory() {
    require_docker
    require_image
    # BY ID, because require_image resolved and vouched for that
    # id; the tag could have moved since.
    docker run --rm "${IMAGE_ID}" cat "${INVENTORY_PATH}"
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
#
# HOW THE COMMITTER IDENTITY REACHES INSIDE, and why it is not forwarded.
#
# HOME is pointed at a scratch directory in the image and no GIT_* variable
# is passed, both deliberately: an identity carried in this process's
# environment would make the attribution of a commit depend on who invoked
# the container, which is exactly the thing that should not vary.  The
# consequence, measured, is that the invoking user's ~/.gitconfig DOES NOT
# EXIST in here -- so a `git var GIT_AUTHOR_IDENT` that resolved on the
# host resolves to nothing inside, the gate's identity check reported
# "user.name='' user.email=''", and a checkpoint taken in the only
# environment where rendering is legal exited 3.
#
# The identity therefore travels as GIT_AUTHOR_* / GIT_COMMITTER_*, which
# forward_commit_identity below adds from `git var GIT_AUTHOR_IDENT` on the
# host.  It used to travel IN THE REPOSITORY instead -- commit_artifacts.sh
# wrote the resolved pair into the checkout's own configuration with `git
# config --local` -- and that is retired for three reasons given in full
# beside report_identity_scope in that file: it contradicted the same
# file's stated contract never to write git configuration, this execution
# environment forbids running those commands at any scope, and the value
# written was the HOST's resolution anyway, so it bought persistence and
# not the invariance it was justified by.  These four variables are
# therefore the ONE exception to "no GIT_* is passed", they carry exactly
# what a commit would have carried on the host, and they leave nothing
# behind in the mounted tree.
# THE ONE CONTRACT every way into the image uses.  `run`, `shell`,
# `preflight` and a hosted session all take these arguments from here, so
# none of them can quietly differ from the environment the others proved.
# BUILT ON DEMAND, never at file scope.  `id` is a command, and running
# it while this file is merely being sourced -- for `help`, for a usage
# error, for a test that only reads the text -- makes those paths depend
# on a PATH they have no business needing.  Measured: declaring this as a
# top-level array broke two tests whose sandbox PATH carries no `id`.
CONTRACT_ARGS=()
contract_args() {
    CONTRACT_ARGS=(
        --volume "${REPO_ROOT}:${REPO_ROOT}"
        --workdir "${REPO_ROOT}"
        --shm-size=1g
        --user "$(id -u):$(id -g)"
        --env "HOME=/tmp/playthrough-home"
        --env "TMPDIR=/tmp"
    )
    forward_commit_identity
}

# forward_commit_identity -- give the container an author, in the
# environment, because nothing writes one into the tree any more.
#
# commit_artifacts.sh used to record the resolved pair with `git config
# --local` so that it travelled in the mounted checkout.  It no longer
# does: its own opening contract says it never writes git configuration,
# and the environment this evidence is produced in forbids running those
# commands at any scope.  So the identity travels the way git documents,
# as GIT_AUTHOR_* / GIT_COMMITTER_*, and leaves nothing behind.
#
# WHY THIS IS NOT THE VARIABILITY THE ABSENCE OF --env WAS AVOIDING.  The
# concern was that an identity carried in the invoker's environment makes
# a commit's attribution depend on who started the container.  Writing the
# HOST-resolved pair into .git/config had precisely the same property --
# what landed there was whatever the first host to run it resolved -- so
# the write bought persistence, not invariance.  Forwarding the same
# resolved pair is therefore no weaker, and one fact fewer is stored.
#
# `git var GIT_AUTHOR_IDENT` is asked rather than `git config --get`,
# because it is the answer git will actually stamp: it resolves the
# environment, then the repository, then the account, then the system.
# Nothing is forwarded when it cannot answer -- an empty --env would
# override a working identity inside the image with nothing, turning a
# resolvable author into an unresolvable one.
forward_commit_identity() {
    local ident="" name="" mail=""
    ident="$(git var GIT_AUTHOR_IDENT 2>/dev/null || true)"
    if [ -z "${ident}" ]; then
        return 0
    fi
    # "Name <mail> <unixtime> <tz>" -- drop the time and the zone by
    # cutting at the last "> ", then take the two halves.
    ident="${ident%> *}>"
    name="${ident%% <*}"
    mail="${ident#*<}"
    mail="${mail%>}"
    if [ -z "${name}" ] || [ -z "${mail}" ]; then
        return 0
    fi
    CONTRACT_ARGS+=(
        --env "GIT_AUTHOR_NAME=${name}"
        --env "GIT_AUTHOR_EMAIL=${mail}"
        --env "GIT_COMMITTER_NAME=${name}"
        --env "GIT_COMMITTER_EMAIL=${mail}"
    )
}

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
    contract_args
    docker run --rm \
        "${CONTRACT_ARGS[@]}" \
        "${cleared[@]}" \
        "${extra[@]}" \
        "${IMAGE_ID}" \
        "$@"
}

# ---------------------------------------------------------------------
# A HOSTED SESSION
#
# WHY THIS EXISTS.  The X server inside the container lives exactly as
# long as the process tree that started it, so a `run` per keystroke
# would photograph a different display each time.  A single `run` for the
# whole session is not the answer either: the pipeline's invariant is ONE
# KEYSTROKE PER session.py INVOCATION, and the loop between invocations
# is observe the frame, decide in character, act -- a pre-scripted run
# would be the blind key-spamming the record is required not to be.
#
# So a session gets a container that OUTLIVES the individual command.
# PID 1 is a sleep, the display is started once and reparented to it, and
# every keystroke is an `exec` onto that same live display.  Proven: the
# X server and the window manager are still serving :99 in an exec issued
# after the one that started them.
#
# IT IS NOT A SECOND CONTRACT.  The mounts, workdir, user, shm size, HOME,
# TMPDIR and cleared trust bypasses are the ones docker_run already uses,
# taken from one array -- a session hosted under a weaker contract than
# `preflight` proved would mean the path was proved on one environment
# and the record taken on another.
#
# HOW A SESSION IS IDENTIFIED, AND WHY IT IS NOT BY NAME.
#
# It used to be: the name carried $CLONE_INDEX verbatim when set and a
# cksum of the checkout path otherwise, and the container was found with
# `docker ps --filter "name=^<name>$"`.  A security review found two
# defects in that, and both were live on the host it was found on --
# there was a container from a SIBLING clone up at the time.
#
#   * THE FILTER IS A REGULAR EXPRESSION (CWE-20).  docker's `name`
#     filter matches a regex, so an unvalidated CLONE_INDEX is
#     unvalidated regex: `CLONE_INDEX='.*'` composes
#     `name=^playthrough-session-.*$`, which matches ANY session --
#     including another clone's -- and `exec`, `down` and `session` then
#     act on it.  `head -n 1` made the choice silent.
#   * A NAME IS NOT AN IDENTITY.  Two checkouts can produce the same
#     cksum, a stale container can hold a name this checkout wants, and
#     nothing about a name proves the container mounts THIS tree, runs
#     the image the preflight proved, or belongs to this user.
#
# So identity is now three things, and all three are checked:
#
#   1. CLONE_INDEX is VALIDATED as an integer 0..99 before it reaches
#      anything -- the same range env.sh accepts.
#   2. Containers are LABELLED with a sha256 digest of the canonical
#      checkout path plus the clone index, and are selected by exact
#      label equality (`--filter label=k=v` is not a regex match), never
#      by name.  The name still exists, because a human reading
#      `docker ps` deserves one, but nothing is selected by it.
#   3. The match is INSPECTED before it is used: exactly one container,
#      running the expected image, carrying a bind mount whose source and
#      destination are both this checkout, and running as this user.
#      Anything else is refused with a diagnosis rather than adopted.
# ---------------------------------------------------------------------
readonly LABEL_CHECKOUT="playthrough.checkout"
readonly LABEL_CLONE="playthrough.clone"
readonly LABEL_ROLE="playthrough.role"
readonly ROLE_SESSION="capture-session"
# The IMAGE's own label, written by do_build and read by
# assert_image_provenance.  It is the only one of these that describes
# the image rather than a container.
readonly LABEL_BUILD="playthrough.build"

# THE VALIDATED CLONE INDEX, resolved ONCE in the current shell.
#
# WHY IT IS A GLOBAL AND NOT A FUNCTION THAT VALIDATES ON EVERY CALL.
# `die` calls `exit`, and `exit` inside `$( ... )` ends the SUBSHELL --
# the caller carries on with an empty string.  Measured while writing
# this: `CLONE_INDEX=100 supported_env.sh session` exited 0 and reported
# no session, because every validation lived inside a command
# substitution.  So the check runs at the top of main(), in the shell
# that has to die, and everything below reads the resolved value.
CLONE_INDEX_RESOLVED=""

# resolve_clone_index -- validate $CLONE_INDEX or refuse the run.
#
# The default is 0 rather than "unset", because a session is identified
# by (checkout, clone) and a missing index is the first clone.  Leading
# zeros are accepted and normalised through $((10#...)) so that `07` and
# `7` name one session rather than two.
resolve_clone_index() {
    local raw="${CLONE_INDEX:-0}"
    case "${raw}" in
        '')
            raw=0
            ;;
        *[!0-9]*)
            die "${EX_USAGE}" "CLONE_INDEX='${raw}' is not a number. \
It selects and labels this checkout's session container, and a value \
that is not a plain integer 0-99 is refused rather than interpreted: \
docker's own name filter is a REGULAR EXPRESSION, so an unvalidated \
value there can match another clone's session and this driver would \
then exec into -- or stop -- somebody else's recording."
            ;;
    esac
    if [ "$((10#${raw}))" -gt 99 ]; then
        die "${EX_USAGE}" "CLONE_INDEX='${raw}' is above 99, which is \
the highest index this pipeline allocates (env.sh accepts the same \
range).  Refused rather than truncated."
    fi
    CLONE_INDEX_RESOLVED="$((10#${raw}))"
    return 0
}

# clone_index -- the resolved index.  Safe inside a substitution.
clone_index() {
    printf '%s' "${CLONE_INDEX_RESOLVED}"
}

# checkout_digest -- a stable, collision-resistant name for this tree.
#
# sha256 of the canonical absolute path, truncated to 16 hex characters:
# long enough that two checkouts on one host will not collide, short
# enough to read in `docker ps`.  cksum was the previous choice and is a
# 32-bit CRC -- fine against typos, not against two trees.
checkout_digest() {
    printf '%s' "${REPO_ROOT}" | sha256sum | cut -c1-16
}

session_name() {
    printf 'playthrough-session-%s-%s\n' \
        "$(checkout_digest)" "$(clone_index)"
}

# session_label_filters -- the exact-match filters that identify us.
SESSION_FILTERS=()
session_label_filters() {
    SESSION_FILTERS=(
        --filter "label=${LABEL_ROLE}=${ROLE_SESSION}"
        --filter "label=${LABEL_CHECKOUT}=$(checkout_digest)"
        --filter "label=${LABEL_CLONE}=$(clone_index)"
    )
}

# session_ids -- every running container carrying this session's labels.
session_ids() {
    session_label_filters
    docker ps --quiet "${SESSION_FILTERS[@]}" 2>/dev/null || true
}

# inspect_field ID GO_TEMPLATE -- one field of one container, or empty.
inspect_field() {
    docker inspect --format "$2" "$1" 2>/dev/null || printf ''
}

# assert_session_container ID -- refuse a container that is not ours.
#
# The labels got us here; this proves the thing behind them is the
# environment `preflight` was run against.  Each property is checked
# separately so the refusal can say WHICH one failed -- "not ours" with
# no reason is a diagnosis nobody can act on.
assert_session_container() {
    local id="$1"
    local image mounted user expected_user
    # THE IMAGE ID, NOT THE IMAGE NAME.  This compared
    # `{{.Config.Image}}` -- the TAG TEXT the container was started with
    # -- against IMAGE_TAG, and a security review was right that this
    # proves nothing: `docker tag playthrough-capture:26.04 <anything>`
    # makes an arbitrary toolchain answer to that name, and an adopted
    # container then has the checkout mounted read-write.  `.Image` is
    # the resolved image ID the container is ACTUALLY running, and
    # IMAGE_ID is what require_image resolved and proved the provenance
    # of, so the two together say "the same image, and one we vouched
    # for" rather than "a matching string".
    image="$(inspect_field "${id}" '{{.Image}}')"
    if [ "${image}" != "${IMAGE_ID}" ]; then
        die "${EX_MISSING}" "the container ${id} carries this \
checkout's session labels but runs image ${image:-<unreadable>} where \
this driver runs ${IMAGE_ID} for ${IMAGE_TAG}.  It is REFUSED rather \
than adopted: the supported environment is the one the preflight \
proved, and a session hosted in a different image is a session proved \
on one environment and recorded on another.  Note that the tag is not \
what is compared -- retagging cannot make a different image acceptable \
here.  Remove that container, or point \$PLAYTHROUGH_SUPPORTED_IMAGE at \
the image it runs if that is what you intend."
    fi
    # THE TEMPLATE IS TRIVIAL AND THE COMPARISON IS BASH, deliberately.
    # It used to be one `{{if and (eq .Source "…") (eq .Destination
    # "…")}}` template wrapped across two lines -- and inside SINGLE
    # quotes a backslash-newline is LITERAL, not a line continuation, so
    # the template docker received carried a real backslash and a real
    # newline in the middle of it.  docker exited 64 with `template
    # parsing error: unexpected "\\" in operand`, inspect_field swallowed
    # that into an empty string, and the check below therefore refused
    # EVERY container -- including the one `up` had just created and
    # labelled correctly.  Fail-closed, but it made a hosted session
    # impossible to reach.
    #
    # So docker is asked only to LIST the mounts, which needs no
    # continuation and cannot be mis-parsed, and the matching is done
    # here.  `grep -F -x` is a fixed-string whole-line match, so a path
    # containing regex metacharacters compares as itself.
    mounted="$(inspect_field "${id}" \
        '{{range .Mounts}}{{println .Source .Destination}}{{end}}')"
    if printf '%s\n' "${mounted}" |
            grep -Fxq -- "${REPO_ROOT} ${REPO_ROOT}"; then
        mounted="yes"
    else
        mounted="no"
    fi
    if [ "${mounted}" != "yes" ]; then
        die "${EX_MISSING}" "the container ${id} carries this \
checkout's session labels but has no bind mount of ${REPO_ROOT} at its \
own path.  It is REFUSED: every repository-relative path in this \
pipeline resolves identically inside and outside only because that \
mount is there, and a container mounting a DIFFERENT tree would record \
this session's frames into somebody else's checkout."
    fi
    user="$(inspect_field "${id}" '{{.Config.User}}')"
    expected_user="$(id -u):$(id -g)"
    if [ "${user}" != "${expected_user}" ]; then
        die "${EX_MISSING}" "the container ${id} runs as '${user}' \
where this driver runs as '${expected_user}'.  It is REFUSED: files it \
writes into the mounted checkout would belong to another account, and \
an artifact tree that has to be chowned before it can be committed is a \
repair job rather than evidence."
    fi
    return 0
}

# resolve_session_id -- set SESSION_ID to THE container, or to nothing.
#
# Exactly one, or a refusal.  Two containers carrying one session's
# labels is an ambiguity no default can be right about: picking either
# one (which `head -n 1` did) means a keystroke could land on a display
# nobody is photographing.
#
# IT SETS A GLOBAL RATHER THAN PRINTING, for the same reason
# resolve_clone_index does: its refusals call `die`, and a `die` inside
# `$( ... )` would kill only the subshell and hand the caller an empty
# string -- which reads exactly like "no session is up".
SESSION_ID=""
resolve_session_id() {
    local -a found=()
    local line
    SESSION_ID=""
    while IFS= read -r line; do
        [ -z "${line}" ] || found+=("${line}")
    done < <(session_ids)
    if [ "${#found[@]}" -eq 0 ]; then
        return 0
    fi
    if [ "${#found[@]}" -gt 1 ]; then
        die "${EX_MISSING}" "${#found[@]} containers carry this \
checkout's session labels (${found[*]}), and this driver will not \
choose between them: a keystroke sent to the wrong one lands on a \
display nothing is photographing, and the frames would be of the other \
session.  Stop the ones that are not yours -- 'docker stop <id>' -- and \
run this again."
    fi
    # THE IDENTITY IS RESOLVED HERE, ONCE, RATHER THAN AT EVERY CALLER.
    # assert_session_container compares the container against IMAGE_ID,
    # and three of the five paths that reach this function -- the
    # teardown and the two exec paths -- did not call require_image
    # first, so IMAGE_ID was empty and the comparison refused every
    # container against nothing.  Measured, as a `down` that could not
    # adopt the session it had just started.
    #
    # Requiring it on the teardown path too is deliberate rather than
    # incidental: refusing to stop a container this driver cannot PROVE
    # is its own is the same property as refusing to exec into one.
    [ -n "${IMAGE_ID}" ] || require_image
    assert_session_container "${found[0]}"
    SESSION_ID="${found[0]}"
    return 0
}

do_up() {
    require_docker
    require_image
    resolve_session_id
    local existing="${SESSION_ID}"
    if [ -n "${existing}" ]; then
        log "the session container $(session_name) is" \
            "already up (${existing}); leaving it exactly as found"
        printf 'SESSION_CONTAINER=%s\n' "${existing}"
        printf 'SESSION_NAME=%s\n' "$(session_name)"
        return 0
    fi
    local -a cleared=()
    local name
    for name in ${TRUST_BYPASS_VARS}; do
        cleared+=(--env "${name}=")
    done
    local id
    contract_args
    # `sleep infinity` is PID 1 so the container outlives every exec; the
    # display started inside it reparents to this process.
    #
    # THE LABELS ARE THE IDENTITY and are written here, once.  Selection
    # is by exact label equality afterwards, never by the name -- see
    # HOW A SESSION IS IDENTIFIED above.
    if ! id="$(docker run --detach --rm \
            --name "$(session_name)" \
            --label "${LABEL_ROLE}=${ROLE_SESSION}" \
            --label "${LABEL_CHECKOUT}=$(checkout_digest)" \
            --label "${LABEL_CLONE}=$(clone_index)" \
            "${CONTRACT_ARGS[@]}" \
            "${cleared[@]}" \
            "${IMAGE_ID}" \
            sleep infinity)"; then
        die "${EX_MISSING}" "the session container could not be" \
            "started; docker's own diagnosis is above."
    fi
    log "session container $(session_name) is up" \
        "(${id:0:12}); bring the display up with" \
        "'supported_env.sh exec', and take it down with" \
        "'supported_env.sh down' when the session is closed"
    printf 'SESSION_CONTAINER=%s\n' "${id}"
    printf 'SESSION_NAME=%s\n' "$(session_name)"
    return 0
}

do_exec() {
    require_docker
    [ "$#" -gt 0 ] ||
        die "${EX_USAGE}" "exec needs a command to run in the session"
    resolve_session_id
    local id="${SESSION_ID}"
    [ -n "${id}" ] ||
        die "${EX_MISSING}" "no session container is up for this" \
            "checkout; start one with 'supported_env.sh up'.  It is" \
            "not started implicitly: a session that came up in the" \
            "middle of a keystroke would be a different display from" \
            "the one the frames before it were photographed on."
    local -a cleared=()
    local name
    for name in ${TRUST_BYPASS_VARS}; do
        cleared+=(--env "${name}=")
    done
    docker exec \
        --workdir "${REPO_ROOT}" \
        --env "HOME=/tmp/playthrough-home" \
        --env "TMPDIR=/tmp" \
        "${cleared[@]}" \
        "${id}" \
        "$@"
}

# session_engine_is_alive ID -- is a game process still running inside?
#
# The one question that decides whether taking this container down would
# end a RECORDED SESSION outside the game's own exit.  Asked of the
# container rather than of the record, because the record cannot say
# whether the engine is still up -- and it is the live engine that a
# `docker stop` would kill.
#
# A probe that cannot be run answers "alive", which is the fail-closed
# direction: an unanswerable question about a session in progress must
# not read as "there is no session".
#
# WHY IT MATCHES THE PROCESS NAME AND EXCLUDES ZOMBIES.  Two defects were
# measured in this container, and both made the probe answer "alive"
# forever -- which would have made `down` refuse every time and taught
# whoever ran it to reach for --abandon by reflex, defeating the guard
# this function exists to be.
#
#   * `pgrep -f "cataclysm-tiles --userdir"` MATCHED ITS OWN WRAPPER.
#     `-f` matches the whole command line, and the `sh -c` carrying the
#     pattern has the pattern in ITS command line.  Measured in a
#     container with no engine at all: the probe printed `alive`, and
#     `pgrep -af` named the shell -- `2408 sh -c pgrep -af
#     "cataclysm-tiles --userdir"`.  So the match is on `comm`, the
#     process NAME, which for this probe's own processes is `ps`, `awk`
#     or `sh` and cannot collide.  (`cataclysm-tiles` is exactly 15
#     characters and so survives Linux's TASK_COMM_LEN truncation
#     whole; a longer binary name would need a prefix match here.)
#   * A DEFUNCT ENGINE IS NOT A RUNNING ENGINE.  PID 1 in a session
#     container is `sleep infinity`, which never calls wait(), so every
#     engine that exits leaves a permanent ZOMBIE behind it -- measured:
#     `1855 cataclysm-tiles [cataclysm-tiles] <defunct>` was still
#     listed long after the process was killed.  A name match alone
#     would therefore report a session in progress for the whole life of
#     any container that had ever launched the game once.  States
#     containing `Z` are excluded for that reason.
#
# Matching the name rather than the `--userdir` argument is also slightly
# BROADER than the old pattern, which is the fail-closed direction: in a
# container dedicated to one session, any live `cataclysm-tiles` is that
# session's engine.
session_engine_is_alive() {
    local id="$1" answer=""
    answer="$(docker exec "${id}" sh -c \
        'ps -eo stat=,comm= | awk '\''$2 == "cataclysm-tiles" &&
             $1 !~ /Z/ { alive = 1 }
             END { exit alive ? 0 : 1 }'\'' >/dev/null 2>&1 &&
             printf alive || printf gone' 2>/dev/null || printf '')"
    case "${answer}" in
        gone) return 1 ;;
        alive) return 0 ;;
        *)
            log "WARNING: the session container ${id} could not be" \
                "asked whether the engine is still running; treating" \
                "it as RUNNING, which is the direction that protects" \
                "a session in progress"
            return 0
            ;;
    esac
}

# do_down [--abandon REASON] -- stop and remove this checkout's session.
#
# THE LIFECYCLE GUARD, which a review required and which the previous
# version of this function actively undermined: it warned in prose, then
# ran `docker stop ... || true` and printed "session container removed"
# whether or not anything had been removed.  Both halves were wrong.
#
#   * A LIVE ENGINE IS A SESSION IN PROGRESS.  A recorded session must
#     end INSIDE the game -- realistic sleep or death, then the in-game
#     Save & Quit -- because that is the only exit that writes the save.
#     Killing the container instead leaves save/<World>/ with no
#     character file and the acceptance gate then refuses the whole run.
#     So this refuses while the engine is up, and the refusal has to be
#     overridden EXPLICITLY, with a reason that goes into the log.
#   * A SUPPRESSED FAILURE IS A LIE.  `|| true` plus an unconditional
#     success message meant a container that refused to stop was reported
#     as removed, and the next `up` then found it still there.  The stop
#     is now checked, and the container is confirmed GONE afterwards.
do_down() {
    require_docker
    local abandon=0 reason=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --abandon)
                shift
                reason="${1-}"
                abandon=1
                ;;
            --abandon=*)
                reason="${1#--abandon=}"
                abandon=1
                ;;
            *)
                die "${EX_USAGE}" "unknown argument '$1' for down; it \
takes only --abandon 'why', which ends a session outside the game's own \
exit"
                ;;
        esac
        shift || true
    done
    if [ "${abandon}" -eq 1 ] && [ -z "${reason}" ]; then
        die "${EX_USAGE}" "--abandon needs a reason.  Ending a \
recorded session outside the game's own Save & Quit is a decision, and \
a decision with no stated reason is indistinguishable from an accident."
    fi
    resolve_session_id
    local id="${SESSION_ID}"
    if [ -z "${id}" ]; then
        log "no session container is up for this checkout," \
            "so there is nothing to take down"
        return 0
    fi
    if session_engine_is_alive "${id}"; then
        if [ "${abandon}" -ne 1 ]; then
            die "${EX_LIFECYCLE}" "REFUSING to take the session \
container down: the engine is STILL RUNNING inside it, so this would \
end a recorded session outside the game's own exit.  A session ends \
INSIDE the game -- realistic sleep or death, then the in-game Save & \
Quit -- because that is the only exit that writes the character file \
the acceptance gate requires; a container stopped underneath it leaves \
save/<World>/ with no survivor in it and nothing downstream can repair \
that.  Finish the session, then run this again.  If the instance is \
genuinely stuck and there is no session worth saving, say so \
explicitly: 'supported_env.sh down --abandon \"<why>\"'.  Nothing was \
stopped."
        fi
        log "WARNING: ABANDONING a session whose engine is still" \
            "running, on an explicit instruction.  Reason:" \
            "${reason}.  Whatever the survivor had not saved is gone."
    else
        log "no engine is running inside the session container, so" \
            "taking it down ends no recorded session"
    fi
    log "stopping the session container ${id} ($(session_name))"
    # `--timeout`, not `--time`: the latter is deprecated and docker 29
    # prints "Flag --time has been deprecated" on every teardown.  A
    # driver that emits a deprecation warning on its normal path trains
    # whoever reads the log to ignore its output.
    if ! docker stop --timeout 10 "${id}"; then
        die "${EX_MISSING}" "docker refused to stop the session \
container ${id}; its own diagnosis is above.  The container is STILL \
UP -- this is reported rather than swallowed, because a driver that \
announced a removal it did not perform is how the next 'up' comes to \
find a container it did not expect."
    fi
    local remaining
    remaining="$(session_ids | wc -l | tr -d ' ')"
    if [ "${remaining}" != "0" ]; then
        die "${EX_MISSING}" "docker reported the stop as successful \
and ${remaining} container(s) carrying this checkout's session labels \
are still running.  The removal is NOT reported as done: inspect \
'docker ps' before starting another session."
    fi
    log "session container stopped and removed"
    return 0
}

do_session_status() {
    require_docker
    resolve_session_id
    local id="${SESSION_ID}"
    printf 'SESSION_NAME=%s\n' "$(session_name)"
    printf 'SESSION_CHECKOUT=%s\n' "$(checkout_digest)"
    printf 'SESSION_CLONE=%s\n' "$(clone_index)"
    printf 'SESSION_CONTAINER=%s\n' "${id}"
    if [ -z "${id}" ]; then
        printf 'SESSION_UP=no\n'
        printf 'SESSION_ENGINE=none\n'
        return 0
    fi
    printf 'SESSION_UP=yes\n'
    printf 'SESSION_DISPLAY=%s\n' \
        "$(docker exec "${id}" bash -c \
            'pgrep -a Xvfb >/dev/null 2>&1 && echo serving || echo down' \
            2>/dev/null)"
    # WHETHER A SESSION IS IN PROGRESS, reported because it is what
    # decides whether `down` will refuse -- an operator should be able to
    # see that before they try it rather than after.
    if session_engine_is_alive "${id}"; then
        printf 'SESSION_ENGINE=running\n'
    else
        printf 'SESSION_ENGINE=none\n'
    fi
    return 0
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
        printf '  %-22s %s\n' \
            "build" "build the declared capture image" \
            "inventory" "print what the built image contains" \
            "run CMD [ARG…]" "run CMD inside it, this checkout mounted" \
            "shell" "an interactive shell inside it" \
            "preflight" "prove the production path inside it" \
            "up" "start a session container that outlives a command" \
            "exec CMD [ARG…]" "run CMD in the session container" \
            "down [--abandon WHY]" "stop and remove the session" \
            "session" "report the session, and whether it is in use"
        printf '\n'
        printf '%s\n' "THE HOSTED-SESSION LIFECYCLE, in order:"
        printf '%s\n' "  up -> exec launch_game.sh headless -> exec \
seed_options.py -> exec"
        printf '%s\n' "  launch_game.sh launch -> one exec per \
session.py step -> the in-game"
        printf '%s\n' "  Save & Quit -> exec commit_artifacts.sh -> \
down.  The X server lives"
        printf '%s\n' "  in the container, so every keystroke of one \
session must be an exec"
        printf '%s\n' "  into the SAME container; playthrough/README.md \
carries the full walk-through."
        printf '\n'
        printf '%s\n' "A session is identified by LABELS -- the \
checkout's path digest and"
        printf '%s\n' "CLONE_INDEX (0-99) -- never by container name, \
and the match is inspected"
        printf '%s\n' "for image, mount and user before it is used, so \
a sibling clone's or a"
        printf '%s\n' "stale container is refused rather than adopted."
        printf '%s\n' "'down' REFUSES while the engine is still \
running: a recorded session ends"
        printf '%s\n' "inside the game, and --abandon 'why' is the \
explicit way to end one outside it."
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
    # BEFORE ANY DISPATCH, in the shell that can actually exit: a
    # malformed CLONE_INDEX is refused here rather than inside a command
    # substitution, where `exit` would end only the subshell.
    resolve_clone_index
    case "${subcommand}" in
        build) do_build ;;
        inventory) do_inventory ;;
        run) do_run "$@" ;;
        shell) do_shell ;;
        preflight) do_preflight ;;
        up) do_up ;;
        exec) do_exec "$@" ;;
        down) do_down "$@" ;;
        session) do_session_status ;;
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
