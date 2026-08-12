#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/commit_artifacts.sh
#
# THE COMMIT LIFECYCLE, AS A CHECKED AND RE-RUNNABLE SEQUENCE.
#
# The playthrough requirement does not merely ask that the artifacts end
# up committed; it asks WHEN.  A single commit taken at the end satisfies
# "everything is committed" and still fails the requirement, because the
# history then cannot show that the dossier and the save existed before
# the session was played -- which is precisely the shape a fabricated
# session would have.  This file is that ordering, enforced.
#
# USAGE -- one subcommand, no default:
#
#     integration  commit .gitignore and .gitattributes, and nothing else
#     dossier      commit the survivor's dossier, BEFORE the first frame
#     creation     commit the survivor and the save they start from
#     final        commit the closed session: its last save and its record
#     media        commit the film, the transcripts and the timeline
#     attest       commit the acceptance report and the three-section
#                  report
#     status       report the lifecycle, changing nothing
#     scan         check the tree's provenance and content for secret
#                  material, changing nothing
#     help         the usage text, which is the single definition of this
#                  list
#
# THE SIX MUTATING STEPS ARE ORDERED AND EACH REFUSES TO RUN OUT OF TURN:
# integration -> dossier -> creation -> play the session -> final ->
# media -> attest.  `integration` comes first because the other steps
# refuse over a history without those two rule files, and it is
# idempotent.  `dossier` is its own commit because "written before the
# first gameplay frame" is checked as ANCESTRY between two commits, and
# one commit cannot precede itself.  `final` anchors to the `creation`
# checkpoint of THE SAME survivor.  The last three are three rather than
# one because a single commit could not be honest about them: the
# document that cites the commits carrying the film and the acceptance
# evidence would have had to exist before the commit that created any of
# them.  `attest` is also the only step that publishes the acceptance
# report into the tree -- the gate writes it to a scratch path outside the
# checkout, because a measurement that writes into the tree it measures
# invalidates its own finding that the tree is clean.
#
# WHAT IT STAGES, AND THE ONE EXCEPTION.  A SESSION checkpoint stages
# paths under playthrough/ and nothing else, by artifact class, and
# refuses any staged change OUTSIDE playthrough/ -- a commit publishes the
# whole index, not just this run's pathspecs.  The one exception is
# `integration`, which OWNS .gitignore and .gitattributes: it stages
# exactly those two paths and refuses any other.  Every other subcommand
# CHECKS both files -- in the working tree and as HEAD carries them -- and
# stages neither.
#
# IT NEVER WRITES GIT CONFIGURATION.  Not user.name, not user.email, not
# in any scope.  The identity is the platform's to supply, through its own
# configuration or through the standard GIT_AUTHOR_* / GIT_COMMITTER_*
# environment, and this file's responsibility is to ASSERT that one
# resolves before it commits: `git var GIT_AUTHOR_IDENT` fails with status
# 128 when none can be determined, so an unset identity is a refusal here
# rather than a commit attributed to a guess from /etc/passwd.  A
# repository-local pair that already matches is left as found and said so;
# one that DISAGREES is a refusal, not a rewrite.  The fix for a missing
# identity is to configure the platform.  (The container the render stages
# run in mounts this checkout, sets its own HOME and forwards no GIT_*, so
# supported_env.sh forwards the resolved pair as environment -- git's own
# mechanism, and it leaves nothing behind in the tree.  report_identity_
# scope reads which scope answered and says so without changing it.)
#
# WHAT IT REFUSES TO COMMIT OVER.  Each checkpoint is gated on the
# evidence it is supposed to be preserving, because a checkpoint that
# commits whatever happens to be on disk proves nothing about the run:
#
#   * an identity that does not resolve, or an author and committer who
#     are not the same person
#   * a repository that is not this checkout, a detached HEAD, or a
#     rebase / merge / cherry-pick / revert in progress
#   * staged changes outside playthrough/ (except `integration`'s own two)
#   * anything in the INDEX naming __pycache__, a *.pyc or a *.pyo once
#     staging is done -- checked against the index, not only the
#     filesystem, so a bytecode file written between the hygiene sweep and
#     the commit is still refused
#   * a save, manifest or capture that .gitignore would EXCLUDE, asked
#     with `git check-ignore --no-index` before anything is committed:
#     `git add` skips an ignored path and exits 0, so this is the only
#     honest way to learn the terminal negation has been lost
#   * machine-local files inside playthrough/ that the terminal
#     `!/playthrough/**` negation RE-INCLUDES -- __pycache__, *.pyc, an
#     ad-hoc test artifact, a retained or quarantined film
#   * at `creation`, a save tree that is not exactly one world holding
#     exactly one survivor; at `final`, neither that live shape nor a
#     graveyard save/log plus matching memorial pair and captured death
#     sequence for the loaded survivor
#   * a missing or empty dossier at either checkpoint, and at `final` one
#     git does not track -- the ordering is unprovable if the file never
#     reached a commit
#   * a manifest that does not verify against the frames, or a frame
#     count, row count and observation count that disagree
#   * an amendment whose sha256 no longer matches the manifest line it
#     corrects
#   * a missing capture attestation ledger, or a frame whose bytes no
#     longer hash to the digest attested for it -- the one substitution
#     every structural check above passes
#   * a keybindings file that binds any debug action
#   * for `final`: no `creation` checkpoint in the history, or a manifest
#     that has not grown since it
#
# WHAT IT DOES NOT DO.  No history rewriting, no amend, no force, no
# push, no branch change, no tag, no reset, no clean.  Every git call is
# an argument list; there is no eval and no unquoted glob.
#
# STAGING IS EXPLICIT, BY ARTIFACT CLASS, AND COMPLETE.  Every staging
# call is `add --` with named paths -- never -A, never a bare '.', never
# -f, never a shell-expanded glob -- and a pathspec add records deletions
# as well as additions.  Explicit enumeration has one failure mode, an
# omitted class, and it is closed: after staging, assert_tree_fully_staged
# proves the batches covered the whole tree, so any path under
# playthrough/ still carrying an unstaged or untracked change is a
# refusal that names it and says which list to add it to.
#
# THE CAPTURES ARE STREAMED, NEVER ACCUMULATED.  One capture per keystroke
# and an unbounded session length mean the capture population must never
# become a shell array: each path is read, judged and written out one at a
# time into a NUL-delimited pathspec file in the mode-0700 runtime
# directory, and git is given that file with `--pathspec-from-file`
# `--pathspec-file-nul` -- one `git add`, one index read, one index write,
# however long the session was.  On a git older than 2.25 the same file is
# replayed in bounded chunks.  Nothing proportional to the session is ever
# resident.
#
# STDOUT IS A MACHINE CONTRACT: KEY=value lines, nothing else, with all
# logging on stderr.  The keys:
#
#     CHECKPOINT   the subcommand that ran
#     COMMITTED    yes | no -- `no` with status 0 means the checkpoint was
#                  already taken and nothing had changed since, so an
#                  empty commit was not manufactured to make a re-run look
#                  eventful
#     COMMIT       the full hash of the commit made, empty when
#                  COMMITTED=no
#     AUTHOR       the identity the commit was made under
#     WORLD        the world directory the save lives in
#     CHARACTER    the survivor the engine records as loaded
#     FRAMES       captures on disk
#     ROWS         manifest rows
#     CREATION     the hash of the `creation` checkpoint, empty when there
#                  is not one yet
#
# `status` adds two triples, which answer "would this checkpoint be
# taken?" without taking it -- asked, above all, by a caller about to
# spend an hour producing what a checkpoint would carry.  One triple per
# checkpoint an automated caller takes, because they ask different
# questions:
#
#     CREATION_SURVIVOR  the survivor the NEWEST creation records
#     FINAL_ANCHOR       the creation checkpoint `final` would anchor to:
#                        the newest one recording THIS survivor, which may
#                        be older than the newest one.  Empty when none.
#     FINAL_ELIGIBLE     yes | no
#     FINAL_REASON       empty when eligible; otherwise one stable token
#                        -- no-survivor-loaded, no-record,
#                        no-creation-checkpoint,
#                        no-creation-for-this-survivor,
#                        anchor-carries-no-record, record-has-not-grown
#     MEDIA_ANCHOR       the `final` commit `media` would be about: the one
#                        that published THIS survivor's closed session
#     MEDIA_ELIGIBLE     yes | no
#     MEDIA_REASON       empty when eligible; otherwise no-final-published
#                        or the FINAL_REASON token that explains why no
#                        anchor could be resolved at all
#
# THE TRAILER IS THE LIFECYCLE'S MEMORY.  Each commit carries
# `Playthrough-Checkpoint: <name>` as a trailer, and `final` finds the
# `creation` commit by searching for it.  A message a human wrote is not a
# lifecycle record; a trailer is, and it survives rewording.
# ---------------------------------------------------------------------

set -euo pipefail

# errtrace propagates the ERR trap into functions, so an unexpected
# failure reports a line number instead of exiting silently.  A strict
# addition to `set -euo pipefail`, never a replacement.
set -o errtrace

# The handler is a function so the trap string stays trivial.  SC2317
# fires on every trap-invoked function -- ShellCheck does not model the
# trap as a call site -- and the suppression is scoped to this one
# handler, exactly as capture.sh and env.sh scope theirs.
# shellcheck disable=SC2317
_ca_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "commit_artifacts.sh failed at line ${2} (exit ${1})" >&2
}
trap '_ca_on_error "$?" "${LINENO}"' ERR

# THE ONE FILE THIS SCRIPT WRITES OUTSIDE THE INDEX, and it is removed on every
# exit path including a refusal.
_CA_PATHSPEC_FILE=""

# The removal cannot be allowed to fail loudly: this runs on EVERY exit
# path, including a refusal whose exit code is the message, and a
# diagnostic from the cleanup would be printed after it.  A pathspec file
# that outlives its run is harmless -- a unique name in a mode-0700
# directory -- so the failure is swallowed rather than reported.
# shellcheck disable=SC2317
_ca_cleanup() {
    if [ -n "${_CA_PATHSPEC_FILE}" ] &&
            [ -f "${_CA_PATHSPEC_FILE}" ]; then
        rm -f -- "${_CA_PATHSPEC_FILE}" 2>/dev/null || true
    fi
    # Releases only what this process took. A checkpoint the sequencer started
    # inherited the sequencer's hold and leaves it in place.
    if command -v playthrough_release_mutation_lock >/dev/null 2>&1; then
        playthrough_release_mutation_lock || true
    fi
}
trap _ca_cleanup EXIT

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment.
# ---------------------------------------------------------------------
_ca_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_ca_script_dir}" ]; then
    printf '%s\n' "commit_artifacts.sh: FATAL: cannot resolve my own \
directory" >&2
    exit 2
fi

_ca_env_file="${_ca_script_dir}/env.sh"
if [ ! -f "${_ca_env_file}" ]; then
    printf '%s\n' "commit_artifacts.sh: FATAL: missing \
${_ca_env_file}; the artifact layout is defined there and is never \
redefined here" >&2
    exit 8
fi

# env.sh is the single definition of every artifact path this file
# stages and of the helpers it logs through: playthrough_log,
# playthrough_warn, playthrough_require_tools, playthrough_rel.  None of
# it is restated here.
#
# The `source=` directive lets `shellcheck -x` follow env.sh; SC1091 is
# suppressed only for a plain `shellcheck` run, which cannot follow a
# sourced file at all and would report the resolved path as unreadable.
# The file's presence is asserted immediately above.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_ca_env_file}"; then
    printf '%s\n' "commit_artifacts.sh: FATAL: ${_ca_env_file} refused \
to load; fix the environment contract before committing anything" >&2
    exit 8
fi
unset _ca_script_dir _ca_env_file

# The working directory is the repository root, as it is for every stage
# of this pipeline.  The pathspecs below are repository-relative and are
# only correct from here.
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# Exit codes, named so the call sites read as intent.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_REPO=2
readonly EX_IDENTITY=3
readonly EX_SCOPE=4
readonly EX_EVIDENCE=5
readonly EX_LIFECYCLE=6
readonly EX_COMMIT=7
readonly EX_PREREQ=8

# ---------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------

# die CODE MESSAGE...
#   env.sh's playthrough_die RETURNS 1 so that a sourced consumer can
#   decide what to do; this file is an executable and a refusal here is
#   final, so it exits with a named code.
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

# emit KEY VALUE -- the machine-readable channel, and the only thing
# this script ever writes to stdout.
emit() {
    printf '%s=%s\n' "$1" "$2"
}

# rel PATH -- a repository-relative path for a message, so diagnostics
# read the same on every host.
rel() {
    playthrough_rel "$1"
}

# name_sample TOTAL NAME... -- the collected names, and how many were not
# collected.
name_sample() {
    local total="$1"
    shift
    if [ "$#" -eq 0 ]; then
        printf 'no names were collected'
        return 0
    fi
    printf '%s' "$*"
    if [ "${total}" -gt "$#" ]; then
        printf ' (and %d more)' "$((total - $#))"
    fi
    return 0
}

# ---------------------------------------------------------------------
# The toolchain. git is the subject; the rest is what the gates are made of.
# ---------------------------------------------------------------------
# awk reads HEAD's own ignore and attribute rules, and sha256sum derives the
# checkout-scoped lock name; both are named here rather than left to fail at
# their call site, so a host missing one is told about it in the same
# consolidated diagnosis as the rest.
if ! playthrough_require_tools git find wc sort grep tr awk \
        sha256sum cat; then
    die "${EX_PREREQ}" "the toolchain above is incomplete, so the" \
        "checkpoint gates cannot be performed.  A checkpoint whose" \
        "preconditions were not checked is not taken."
fi
readonly GIT="${PLAYTHROUGH_BIN_GIT}"
readonly FIND="${PLAYTHROUGH_BIN_FIND}"
readonly WC="${PLAYTHROUGH_BIN_WC}"
readonly SORT="${PLAYTHROUGH_BIN_SORT}"
readonly GREP="${PLAYTHROUGH_BIN_GREP}"
readonly TR="${PLAYTHROUGH_BIN_TR}"
readonly AWK="${PLAYTHROUGH_BIN_AWK}"
readonly CAT="${PLAYTHROUGH_BIN_CAT}"

# ---------------------------------------------------------------------
# NO MUTATING GIT COMMAND RUNS A HOOK.
# `git commit` executes pre-commit, prepare-commit-msg, commit-msg and
# post-commit from $GIT_DIR/hooks -- or from wherever core.hooksPath points --
# and every one of those is an ordinary executable file in a directory this
# pipeline does not own the contents of.
# ---------------------------------------------------------------------
HOOKS_VOID=""

# hooks_void -- print the path of an empty, private, verified directory.
hooks_void() {
    if [ -n "${HOOKS_VOID}" ]; then
        printf '%s' "${HOOKS_VOID}"
        return 0
    fi
    local path="${PLAYTHROUGH_RUNTIME_DIR}/hooks-void"
    if ! playthrough_secure_dir "${path}" 700 \
            "the empty hooks directory"; then
        die "${EX_PREREQ}" "the empty directory that keeps git hooks" \
            "from running could not be established at '${path}'." \
            "A commit is NOT taken with hooks enabled instead: a" \
            "hook runs with this step's privileges at the moment the" \
            "credential in .git/config is reachable."
    fi
    # ASSERTED EMPTY, not assumed empty.  `find -mindepth 1` prints the
    # first entry of any kind -- file, directory, link or socket -- so a
    # path that already held something is named rather than used.
    local intruder
    intruder="$("${FIND}" "${path}" -mindepth 1 -print -quit \
        2>/dev/null || true)"
    if [ -n "${intruder}" ]; then
        die "${EX_PREREQ}" "the directory nominated to hold no git" \
            "hooks (${path}) is not empty -- it contains" \
            "'${intruder}'.  It is refused rather than emptied: this" \
            "step does not delete files it did not create, and a" \
            "hooks directory with contents is a hooks directory."
    fi
    HOOKS_VOID="${path}"
    printf '%s' "${HOOKS_VOID}"
    return 0
}

# git_mutate ARG... -- run one git command that changes something, with
# hooks contained.  Exits with git's own status so every existing caller
# keeps its own diagnosis.
git_mutate() {
    "${GIT}" -c "core.hooksPath=$(hooks_void)" "$@"
}

# ---------------------------------------------------------------------
# A CREDENTIAL IN .git/config IS NOT READABLE BY ANYBODY ELSE.
# This checkout is provisioned with a push URL of the shape
# https://x-access-token:<secret>@host/..., which puts a live bearer token in a
# plain file.
# ---------------------------------------------------------------------
readonly CREDENTIAL_URL_RE='://[^/@[:space:]]*:[^/@[:space:]]*@'

assert_credential_containment() {
    local config="${GIT_DIR_PATH}/config"
    if [ ! -f "${config}" ]; then
        return 0
    fi
    if ! "${GREP}" -Eq -- "${CREDENTIAL_URL_RE}" "${config}" \
            2>/dev/null; then
        playthrough_log "this checkout's git configuration embeds no" \
            "credential in a remote URL, so there is nothing in it" \
            "for its file mode to expose"
        return 0
    fi
    local mode
    mode="$(playthrough_permission_bits "${config}")" || mode=""
    if [ -z "${mode}" ]; then
        die "${EX_REPO}" "this checkout's git configuration carries a" \
            "credential in a remote URL and its file mode could not" \
            "be read, so whether other accounts can read that" \
            "credential is unknown.  Nothing was committed."
    fi
    if [ $(( 8#${mode} & 8#077 )) -ne 0 ]; then
        die "${EX_REPO}" "this checkout's git configuration carries a" \
            "credential in a remote URL and is mode ${mode}, so" \
            "group or other can read it.  Every local account, every" \
            "child process and every git hook could recover that" \
            "token.  Run 'chmod 600 $(playthrough_rel "${config}")'" \
            "and take the checkpoint again; nothing was committed," \
            "because evidence produced in an environment where the" \
            "credential had already leaked is not evidence about a" \
            "controlled run."
    fi
    playthrough_log "this checkout's git configuration carries a" \
        "credential and is mode ${mode} -- readable only by its" \
        "owner.  Revoking or rotating that token is the platform's to" \
        "do, not this step's; the containment this step can assert is" \
        "the file mode, and it holds"
    return 0
}

# The two phase words of verify_artifacts.sh that a COMMITTABLE acceptance
# report may carry.
readonly GATE_HISTORY_PHASE="post-commit"
readonly GATE_EVERY_PHASE="all"
# THE TWO VERDICTS A REPORT MAY BE PUBLISHED UNDER, and why there are two
# rather than one.
readonly -a GATE_PUBLISHABLE_VERDICTS=(
    "pass"
    "pass-with-divergence"
)

# ---------------------------------------------------------------------
# The lifecycle vocabulary.
# ---------------------------------------------------------------------

# The trailer key and the FIVE checkpoint names. `final` searches the history
# for the `creation` trailer, so these strings are the lifecycle's entire
# persistent state -- there is no side file to fall out of step with the
# history it describes.
readonly TRAILER_KEY="Playthrough-Checkpoint"
readonly CHECKPOINT_DOSSIER="dossier"
readonly CHECKPOINT_CREATION="creation"
readonly CHECKPOINT_FINAL="final"
readonly CHECKPOINT_MEDIA="media"
readonly CHECKPOINT_ATTEST="attest"
# The fourth milestone, and the only one whose subject is not the
# session: the two repository-wide rule files the evidence depends on.
# See do_integration for why it exists and why it is separate.
readonly CHECKPOINT_INTEGRATION="integration"

# The subjects.  Written here rather than passed in, because a
# checkpoint whose message a caller chooses is a checkpoint whose
# meaning drifts between runs.
readonly SUBJECT_DOSSIER="Commit the survivor's dossier before the first \
frame of play"
readonly SUBJECT_CREATION="Commit the survivor's creation and the save \
it produced"
readonly SUBJECT_FINAL="Commit the closed session, its final save and \
its record"
readonly SUBJECT_MEDIA="Commit the film, the transcripts and the \
timeline derived from the record"
readonly SUBJECT_ATTEST="Commit the acceptance report and the final \
three-section report"
readonly SUBJECT_INTEGRATION="Commit the repository rules the \
playthrough evidence depends on"

# is_post_session_checkpoint NAME -- whether the session has already ended by
# the time this checkpoint runs.
is_post_session_checkpoint() {
    local name="$1"
    if [ "${name}" = "${CHECKPOINT_FINAL}" ] ||
       [ "${name}" = "${CHECKPOINT_MEDIA}" ] ||
       [ "${name}" = "${CHECKPOINT_ATTEST}" ]; then
        return 0
    fi
    return 1
}

# The lock this step takes, as a BASENAME: env.sh appends a digest of this
# checkout's root so that two runs over ONE working tree serialise and two runs
# over different ones do not.
readonly CHECKPOINT_LOCK_BASENAME="checkpoint"
readonly CHECKPOINT_LOCK_TIMEOUT_DEFAULT=120

# The one pathspec a SESSION checkpoint will ever read or write the index
# through.
readonly -a PATHSPECS=("playthrough")

# How many paths go into one `git add` invocation ON THE FALLBACK PATH.
readonly STAGE_BATCH_SIZE=256

# The name of capture number one, formatted from env.sh's own capture format
# rather than spelled out here, so this file cannot disagree with manifest.py
# or capture.sh about what a capture is called.
FIRST_CAPTURE_BASENAME=""
# shellcheck disable=SC2059
printf -v FIRST_CAPTURE_BASENAME -- "${PLAYTHROUGH_FRAME_FORMAT}" 1
if [ -z "${FIRST_CAPTURE_BASENAME}" ] ||
        [ "${FIRST_CAPTURE_BASENAME}" = "${PLAYTHROUGH_FRAME_FORMAT}" ]; \
        then
    die "${EX_PREREQ}" "PLAYTHROUGH_FRAME_FORMAT=" \
        "'${PLAYTHROUGH_FRAME_FORMAT}' did not expand; env.sh must" \
        "supply a printf format containing %05d.  Nothing was" \
        "committed."
fi
readonly FIRST_CAPTURE_BASENAME

# HOW MANY OFFENDING PATHS A REFUSAL NAMES.
# Every diagnostic in this file is about a population whose size is the
# session's: "nothing is staged" names one path per capture, and a refusal that
# holds one string per frame to print them all is the same unbounded list the
# staging path was just relieved of.
readonly DIAGNOSTIC_LIMIT=8

# How many lines of "what a checkpoint would stage" `status` prints.
readonly PREVIEW_LIMIT=20

# ---------------------------------------------------------------------
# THE IDENTITY GATE.
# `git var GIT_AUTHOR_IDENT` is git answering the question with the same
# resolution order it will use when it writes the commit: the GIT_AUTHOR_*
# environment first, then user.name / user.email from any configuration scope,
# then a derivation from the passwd entry -- and it exits 128 rather than
# derive one when it cannot get an email.
# ---------------------------------------------------------------------

# Set once, by resolve_identity, and deliberately NOT readonly: `status`
# resolves the same pair without dying, and a readonly that a reporting
# path may or may not have assigned is a variable the next assignment
# fails on for reasons unrelated to identity.
IDENT_AUTHOR=""
IDENT_COMMITTER=""

# ident_person IDENT -- the "Name <email>" prefix of a git ident string,
# which also carries a unix timestamp and a zone offset that change on
# every call and must not be compared.
ident_person() {
    local ident="$1"
    local head="${ident%>*}"
    printf '%s' "${head}>"
}

# ident_is_wellformed PERSON -- a non-empty display name, then an address in
# angle brackets carrying an '@' and no whitespace.
ident_is_wellformed() {
    local person="$1"
    local name="${person%% <*}"
    local rest="${person#*<}"
    local mail="${rest%>}"
    if [ -z "${person}" ] || [ "${person}" = "${name}" ]; then
        return 1
    fi
    case "${name}" in
        ''|*'<'*|*'>'*) return 1 ;;
    esac
    case "${mail}" in
        ''|*' '*|*'<'*|*'>'*) return 1 ;;
        *'@'*) ;;
        *) return 1 ;;
    esac
    return 0
}

# resolve_identity
#   Ask git, fill IDENT_AUTHOR and IDENT_COMMITTER, and return 1 rather than
#   dying when there is nothing to fill them with.  Splitting this out is what
#   lets `status` report a missing identity instead of refusing to describe the
#   repository because of it.
resolve_identity() {
    local author committer
    if ! author="$("${GIT}" var GIT_AUTHOR_IDENT 2>/dev/null)"; then
        author=""
    fi
    if ! committer="$("${GIT}" var GIT_COMMITTER_IDENT 2>/dev/null)"
    then
        committer=""
    fi
    if [ -z "${author}" ] || [ -z "${committer}" ]; then
        return 1
    fi
    IDENT_AUTHOR="$(ident_person "${author}")"
    IDENT_COMMITTER="$(ident_person "${committer}")"
    return 0
}

assert_identity() {
    if ! resolve_identity; then
        die "${EX_IDENTITY}" "git cannot determine who would be" \
            "making this commit: 'git var GIT_AUTHOR_IDENT' produced" \
            "nothing.  THIS SCRIPT WILL NOT INVENT AN IDENTITY -- it" \
            "persists the one git already resolves into this" \
            "repository's own configuration, and there is nothing here" \
            "to persist.  Supply it the way the platform supplies it:" \
            "its own git configuration, or the standard" \
            "GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL /" \
            "GIT_COMMITTER_NAME / GIT_COMMITTER_EMAIL environment." \
            "Nothing was staged and nothing was committed."
    fi
    if ! ident_is_wellformed "${IDENT_AUTHOR}"; then
        die "${EX_IDENTITY}" "the author identity git resolved," \
            "'${IDENT_AUTHOR}', is not a display name followed by an" \
            "address in angle brackets, so the commit would be" \
            "attributed to something unusable.  Nothing was committed."
    fi
    if ! ident_is_wellformed "${IDENT_COMMITTER}"; then
        die "${EX_IDENTITY}" "the committer identity git resolved," \
            "'${IDENT_COMMITTER}', is not a display name followed by" \
            "an address in angle brackets.  Nothing was committed."
    fi
    if [ "${IDENT_AUTHOR}" != "${IDENT_COMMITTER}" ]; then
        die "${EX_IDENTITY}" "the author would be" \
            "'${IDENT_AUTHOR}' and the committer" \
            "'${IDENT_COMMITTER}'.  These artifacts are evidence and" \
            "their history is part of the evidence, so a commit is" \
            "made by ONE identity acting as both -- a split" \
            "attribution is a question nobody can answer afterwards." \
            "Nothing was committed."
    fi
    playthrough_log "the commit would be authored and committed by" \
        "${IDENT_AUTHOR}"
    return 0
}

# ---------------------------------------------------------------------
# WHERE THAT IDENTITY CAME FROM -- REPORTED, AND NEVER WRITTEN.
# This block used to WRITE the resolved pair into the checkout's own
# configuration with `git config --local user.name` / `user.email`, and the
# reason given was concrete: the render and capture stages run inside the
# declared container, which mounts this checkout, sets its own HOME and
# forwards no GIT_* at all -- so an identity living only in the invoking user's
# ~/.gitconfig does not exist in there, and a checkpoint taken in the one
# environment where rendering is legal exited 3.
# ---------------------------------------------------------------------

# local_config_value KEY -- the value from the repository's own config alone,
# empty when this checkout does not record one.
local_config_value() {
    "${GIT}" config --local --get "$1" 2>/dev/null || printf ''
}

# report_identity_scope -- say where the commit's identity came from.
report_identity_scope() {
    local name mail local_name local_mail
    name="${IDENT_AUTHOR%% <*}"
    mail="${IDENT_AUTHOR#*<}"
    mail="${mail%>}"
    local_name="$(local_config_value user.name)"
    local_mail="$(local_config_value user.email)"
    if [ "${local_name}" = "${name}" ] &&
            [ "${local_mail}" = "${mail}" ]; then
        playthrough_log "the committer identity ${name} <${mail}> is" \
            "recorded by THIS checkout's own configuration, and it is" \
            "the identity this commit will carry"
        return 0
    fi
    if [ -n "${local_name}" ] || [ -n "${local_mail}" ]; then
        die "${EX_IDENTITY}" "this checkout's own configuration" \
            "records '${local_name}' <${local_mail}> while git resolves" \
            "this commit's author as ${name} <${mail}>.  The two are" \
            "the same fact written in two places and they disagree, so" \
            "the configuration describes somebody who did not make the" \
            "commit.  This step does not rewrite git configuration --" \
            "not in any scope -- so correct the repository-local pair" \
            "or remove it, and run this again.  Nothing was committed."
    fi
    playthrough_log "the committer identity ${name} <${mail}> resolves" \
        "from a BROADER scope than this checkout, which records none of" \
        "its own; this step asserts that one resolves and never writes" \
        "git configuration, so that is the identity the commit carries"
    return 0
}

# ---------------------------------------------------------------------
# THE REPOSITORY GATE.  The right repository, a real branch, real
# history, and no operation half-finished underneath us.
# ---------------------------------------------------------------------

GIT_DIR_PATH=""
BRANCH=""

assert_repository() {
    local top
    if ! top="$("${GIT}" rev-parse --show-toplevel 2>/dev/null)"; then
        die "${EX_REPO}" "$(rel "${PLAYTHROUGH_REPO_ROOT}") is not" \
            "inside a git working tree, so there is nothing to commit" \
            "to."
    fi
    if [ "${top}" != "${PLAYTHROUGH_REPO_ROOT}" ]; then
        die "${EX_REPO}" "git reports the working tree root as" \
            "'${top}' while env.sh resolved this checkout to" \
            "'${PLAYTHROUGH_REPO_ROOT}'.  Committing across that" \
            "disagreement would put the artifacts in a repository" \
            "other than the one they were produced in.  Nothing was" \
            "committed."
    fi
    if ! GIT_DIR_PATH="$("${GIT}" rev-parse --absolute-git-dir \
            2>/dev/null)"; then
        die "${EX_REPO}" "git could not report its own directory for" \
            "this checkout, so the in-progress-operation check cannot" \
            "be performed.  Nothing was committed."
    fi
    readonly GIT_DIR_PATH
    if ! "${GIT}" rev-parse --verify --quiet HEAD >/dev/null; then
        die "${EX_REPO}" "this repository has no commit yet.  The" \
            "checkpoint lifecycle records where the playthrough sits" \
            "in an existing history and does not found one."
    fi
    if ! BRANCH="$("${GIT}" symbolic-ref --quiet --short HEAD \
            2>/dev/null)" || [ -z "${BRANCH}" ]; then
        die "${EX_REPO}" "HEAD is detached.  A checkpoint commit made" \
            "here would belong to no branch and would be lost by the" \
            "next checkout, which for evidence is the same as not" \
            "having made it.  Check out the working branch first." \
            "Nothing was committed."
    fi
    readonly BRANCH
    # A half-finished operation owns the index.  Adding to it and
    # committing would either fail confusingly or, worse, conclude
    # somebody else's rebase step with this checkpoint's message.
    local marker
    for marker in rebase-merge rebase-apply MERGE_HEAD \
            CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG; do
        if [ -e "${GIT_DIR_PATH}/${marker}" ]; then
            die "${EX_REPO}" "a git operation is in progress" \
                "(${marker} exists), which owns the index this" \
                "checkpoint would have to stage into.  Finish or abort" \
                "it first.  Nothing was committed."
        fi
    done
    # THE CREDENTIAL GATE, here rather than at the commit, because the question
    # it asks -- "has this repository's token already been exposed to every
    # account on the host" -- is a property of the environment the whole
    # checkpoint is produced in and not of the commit command.
    assert_credential_containment
    playthrough_log "committing on branch ${BRANCH}"
    return 0
}

# ---------------------------------------------------------------------
# THE SCOPE GATE.
# A commit publishes the whole index, not the pathspecs this run added, so
# anything already staged outside playthrough/ would ride along inside a
# checkpoint that claims to be about the playthrough.
# ---------------------------------------------------------------------

# WHICH PATHS THE MILESTONE IN PROGRESS MAY COMMIT.
# Three of the four milestones are about the session and commit playthrough/
# and nothing else.
readonly SCOPE_SESSION="playthrough"
readonly SCOPE_VCS="vcs"
SCOPE_MODE="${SCOPE_SESSION}"

# in_scope PATH -- true when a repository-relative path is one this file
# is allowed to commit IN THE CURRENT MODE.
in_scope() {
    local path="$1"
    if [ "${SCOPE_MODE}" = "${SCOPE_VCS}" ]; then
        case "${path}" in
            .gitignore|.gitattributes) return 0 ;;
        esac
        return 1
    fi
    case "${path}" in
        playthrough|playthrough/*) return 0 ;;
    esac
    return 1
}

# staged_out_of_scope -- every staged path this file may not commit, NUL
# terminated. -z is the only format that survives a path with a space, a quote
# or a newline in it; --diff-filter is deliberately absent so a staged deletion
# counts too.
staged_out_of_scope() {
    local path
    while IFS= read -r -d '' path; do
        if ! in_scope "${path}"; then
            printf '%s\0' "${path}"
        fi
    done < <("${GIT}" diff --cached --name-only -z HEAD --)
    return 0
}

assert_scope() {
    local staged=() path rendered=()
    # -d '' on both sides: an empty record can only come from an empty
    # path, which git never emits, so nothing has to be skipped here and
    # nothing CAN be skipped by accident.
    while IFS= read -r -d '' path; do
        staged+=("${path}")
    done < <(staged_out_of_scope)
    if [ "${#staged[@]}" -gt 0 ]; then
        # %q per path, so a name carrying a newline, a tab or a quote
        # appears in the refusal as itself rather than as a hole in the
        # message -- the whole point of carrying the NUL this far.
        for path in "${staged[@]}"; do
            rendered+=("$(printf '%q' "${path}")")
        done
        if [ "${SCOPE_MODE}" = "${SCOPE_VCS}" ]; then
            die "${EX_SCOPE}" "the index already carries" \
                "${#staged[@]} change(s) that are neither .gitignore" \
                "nor .gitattributes: ${rendered[*]}.  A commit" \
                "publishes the whole index, so those would be swept" \
                "into a checkpoint that says it is about the two" \
                "repository rule files.  Unstage them ('git restore" \
                "--staged -- <path>') and take the session checkpoints" \
                "for anything under $(rel "${PLAYTHROUGH_DIR}")." \
                "Nothing was committed."
        fi
        die "${EX_SCOPE}" "the index already carries ${#staged[@]}" \
            "change(s) outside $(rel "${PLAYTHROUGH_DIR}"):" \
            "${rendered[*]}.  A commit publishes the whole index, so" \
            "those would be swept into a checkpoint that says it is" \
            "about the playthrough.  Unstage them ('git restore" \
            "--staged -- <path>') and commit them separately --" \
            ".gitignore and .gitattributes have their own milestone" \
            "('commit_artifacts.sh ${CHECKPOINT_INTEGRATION}') and are" \
            "never staged by a session checkpoint.  Nothing was" \
            "committed."
    fi
    return 0
}

report_foreign_worktree_changes() {
    local foreign=() vcs=() path status origin
    while IFS= read -r -d '' status; do
        path="${status:3}"
        case "${status}" in
            R*|C*)
                # Under -z a rename or copy emits its origin as a second field,
                # which must be consumed or it would be read as the next
                # entry's status.
                IFS= read -r -d '' origin || origin=""
                ;;
        esac
        if ! in_scope "${path}"; then
            foreign+=("${path}")
            case "${path}" in
                .gitignore|.gitattributes) vcs+=("${path}") ;;
            esac
        fi
    done < <("${GIT}" status --porcelain -z --untracked-files=all --)
    if [ -n "${origin:-}" ]; then
        playthrough_log "the working tree carries at least one" \
            "rename; its origin was read and discarded"
    fi
    if [ "${#foreign[@]}" -gt 0 ]; then
        playthrough_warn "leaving ${#foreign[@]} change(s) outside" \
            "this feature exactly as found (they are not staged and" \
            "the pathspecs cannot reach them): ${foreign[*]}"
    fi
    if [ "${#vcs[@]}" -gt 0 ]; then
        # Named separately because these two are the ones a reader will
        # expect a "commit everything" step to have taken: they are
        # repository-wide configuration this tree DEPENDS on, they are
        # checked here (assert_not_ignored) and committed elsewhere, and
        # silence about them would look like an oversight.
        playthrough_warn "${vcs[*]} carr(ies) uncommitted changes." \
            "A SESSION checkpoint never stages them: repository-wide" \
            "configuration belongs in its own commit, and this one is" \
            "about the survivor.  That commit is this script's own" \
            "'${CHECKPOINT_INTEGRATION}' milestone -- run" \
            "'commit_artifacts.sh ${CHECKPOINT_INTEGRATION}' first," \
            "which commits exactly those two files after checking that" \
            "the terminal '${IGNORE_NEGATION}' negation and the" \
            "attribute rows are what they have to be."
    fi
    return 0
}

# ---------------------------------------------------------------------
# THE COMMITTED RULES, WHICH ARE A DIFFERENT QUESTION FROM THE WORKING
# TREE'S.
#
# assert_not_ignored asks `git check-ignore` about the files on disk, which
# is exactly the right question for "will the next `git add` skip the save".
# It is the WRONG question for "will a fresh clone of this history still
# carry the save", which is the question a reader of the repository actually
# asks: a history whose terminal negation was only ever in somebody's
# working tree passes every check-ignore here and re-ignores the save data
# the moment anybody clones it.
#
# So HEAD's own copies are read.  The negation must be the LAST effective
# rule in the committed .gitignore, because git applies the last matching
# pattern; and the six attribute rows must be committed, because
# `* text=auto` alone leaves the film, the save and the map archives to
# content detection.  This is a REFUSAL rather than a warning: a checkpoint
# taken over a history that does not carry these rules is a checkpoint whose
# evidence a clone will not have.  The remedy is never "force the add" --
# `integration` commits those two files, and it is the only subcommand that
# may.
# ---------------------------------------------------------------------
readonly IGNORE_NEGATION="!/playthrough/**"
readonly -a REQUIRED_ATTRIBUTES=(
    "*.mp4 binary"
    "*.zzip binary"
    "*.sav binary"
    "*.gsav binary"
    "*.srt text"
    "*.jsonl text"
)

# SIX ROWS, AND DELIBERATELY NOT A SEVENTH. A `playthrough/userdir/**
# -whitespace` waiver used to sit here too, added so that `git diff --check`
# would stop reporting the blank line at the end of the two files the engine
# writes that way -- its debug log and the survivor's memorial diary.

# ---------------------------------------------------------------------
# THE ATTRIBUTES AS GIT ACTUALLY APPLIES THEM, which is not the same question
# as whether the six rows are present.
# ---------------------------------------------------------------------

# One witness per required row: PATH|ATTRIBUTE|VALUE.  The paths are the
# real artifact spellings this feature commits, so a rule scoped to a
# directory rather than to a suffix is measured the way it will apply.
readonly -a ATTRIBUTE_WITNESSES=(
    "playthrough/cata-play.mp4|text|unset"
    "playthrough/userdir/save/World/maps.zzip|text|unset"
    "playthrough/userdir/save/World/#character.sav|text|unset"
    "playthrough/userdir/save/World/master.gsav|text|unset"
    "playthrough/transcript.srt|text|set"
    "playthrough/manifest.jsonl|text|set"
)

# effective_attribute PATH ATTRIBUTE [SOURCE] -- what git would apply.
effective_attribute() {
    local path="$1" attribute="$2" source="${3-}"
    local line=""
    if [ -n "${source}" ]; then
        line="$("${GIT}" check-attr --source="${source}" \
            "${attribute}" -- "${path}" 2>/dev/null || printf '')"
    else
        line="$("${GIT}" check-attr "${attribute}" -- "${path}" \
            2>/dev/null || printf '')"
    fi
    # The path may itself contain ': ', so the VALUE is taken from the
    # end of the line rather than by splitting from the front.
    printf '%s' "${line##*: }"
}

# check_attr_supports_source -- whether this git can be asked about a tree-ish.
check_attr_supports_source() {
    "${GIT}" check-attr --source=HEAD text -- .gitattributes \
        >/dev/null 2>&1
}

# attribute_semantics_problems [SOURCE] -- one line per witness whose
# effective attribute is not what this feature requires.
attribute_semantics_problems() {
    local source="${1-}"
    local witness="" path="" attribute="" wanted="" actual=""
    for witness in "${ATTRIBUTE_WITNESSES[@]}"; do
        path="${witness%%|*}"
        attribute="${witness#*|}"
        attribute="${attribute%%|*}"
        wanted="${witness##*|}"
        actual="$(effective_attribute "${path}" "${attribute}" \
            "${source}")"
        if [ "${actual}" = "${wanted}" ]; then
            continue
        fi
        printf '%s\n' "git would apply '${attribute}: \
${actual:-unreadable}' to ${path}, not '${attribute}: ${wanted}' -- a \
later rule overrides the row this feature declares, and git applies the \
LAST matching pattern"
    done
    return 0
}

# assert_attribute_semantics LABEL [SOURCE] -- refuse a ruleset whose effective
# attributes are not the ones this feature declares.
assert_attribute_semantics() {
    local label="$1" source="${2-}"
    local -a problems=()
    local problem=""
    while IFS= read -r problem; do
        [ -n "${problem}" ] || continue
        problems+=("${problem}")
    done < <(attribute_semantics_problems "${source}")
    if [ "${#problems[@]}" -gt 0 ]; then
        die "${EX_PREREQ}" "${label}'s .gitattributes declares the" \
            "rows this feature needs but git would not apply them:" \
            "${problems[*]}.  git takes the LAST matching pattern, so a" \
            "rule added after this feature's rows silently replaces" \
            "them -- and with the film left to 'text', 'git add' runs" \
            "end-of-line normalisation over an h264 stream and commits" \
            "a container nothing can play, while every count here still" \
            "tallies.  Move this feature's rows after whatever" \
            "overrides them.  Nothing was committed."
    fi
    # THE PATHS ARE LISTED FROM THE TABLE, not described in prose.
    local witness="" listed=""
    for witness in "${ATTRIBUTE_WITNESSES[@]}"; do
        listed="${listed}${listed:+, }$(rel "${witness%%|*}")"
    done
    playthrough_log "git applies this feature's attributes to" \
        "${label}'s ${#ATTRIBUTE_WITNESSES[@]} witness paths --" \
        "${listed} -- so no later rule overrides them"
    return 0
}

# committed_lines PATH -- the file as HEAD carries it, with blank lines and
# comments dropped and surrounding whitespace collapsed, so a rule written with
# a tab is recognised as the rule it is.
committed_lines() {
    # SC2016: the single quotes are deliberate and required.  This is an
    # awk PROGRAM, and its '$' characters -- the end-of-line anchor and
    # $0 -- belong to awk; letting the shell expand them would rewrite
    # the program before awk ever saw it.
    # shellcheck disable=SC2016
    "${GIT}" show "HEAD:$1" 2>/dev/null |
        "${AWK}" '{ gsub(/^[ \t]+|[ \t]+$/, "");
                    gsub(/[ \t]+/, " ");
                    if ($0 != "" && $0 !~ /^#/) { print } }' ||
        printf ''
}

# worktree_lines PATH -- the same normalisation as committed_lines, applied to
# the file ON DISK. Empty when the path is not there.
worktree_lines() {
    [ -f "$1" ] || { printf ''; return 0; }
    # SC2016: the '$' characters belong to the awk program, exactly as in
    # committed_lines above.
    # shellcheck disable=SC2016
    "${AWK}" '{ gsub(/^[ \t]+|[ \t]+$/, "");
                gsub(/[ \t]+/, " ");
                if ($0 != "" && $0 !~ /^#/) { print } }' "$1" ||
        printf ''
}

# vcs_rule_problems READER -- every way the two rule files read through READER
# fail this feature, one problem per line, nothing when they hold.
vcs_rule_problems() {
    local reader="$1"
    local ignore_rules="" last="" attributes="" row=""
    ignore_rules="$("${reader}" ".gitignore")"
    if [ -z "${ignore_rules}" ]; then
        printf '%s\n' "there is no .gitignore with any effective rule \
in it, so the terminal '${IGNORE_NEGATION}' negation this tree depends \
on is missing entirely"
    else
        last="${ignore_rules##*$'\n'}"
        if [ "${last}" != "${IGNORE_NEGATION}" ]; then
            printf '%s\n' "the last effective rule in .gitignore is \
'${last}', not '${IGNORE_NEGATION}' -- git applies the LAST matching \
pattern, so anything after the negation re-excludes what it rescued"
        fi
    fi
    attributes="$("${reader}" ".gitattributes")"
    for row in "${REQUIRED_ATTRIBUTES[@]}"; do
        # WHOLE-LINE MATCHING WITHOUT A PIPE.
        case $'\n'"${attributes}"$'\n' in
            *$'\n'"${row}"$'\n'*) ;;
            *) printf '%s\n' ".gitattributes carries no '${row}' row" ;;
        esac
    done
    return 0
}

assert_committed_vcs_rules() {
    local ignore_rules="" last="" attributes="" row=""
    local -a missing=()
    ignore_rules="$(committed_lines ".gitignore")"
    if [ -z "${ignore_rules}" ]; then
        die "${EX_PREREQ}" "HEAD carries no .gitignore, so the" \
            "terminal '${IGNORE_NEGATION}' negation this tree depends" \
            "on is not in the history at all.  Commit .gitignore" \
            "first: without that negation a fresh clone re-ignores the" \
            "engine's own '#<name>.sav' and '*.log' files and the save" \
            "data is simply absent from it.  Nothing was committed."
    fi
    last="${ignore_rules##*$'\n'}"
    if [ "${last}" != "${IGNORE_NEGATION}" ]; then
        die "${EX_PREREQ}" "the last effective rule in HEAD's" \
            ".gitignore is '${last}', not '${IGNORE_NEGATION}'.  git" \
            "applies the LAST matching pattern, so anything after the" \
            "negation re-excludes what it rescued -- and a history" \
            "without it re-ignores the save data on every fresh clone" \
            "while every working-tree check here still passes.  Commit" \
            "a .gitignore whose final effective line is the negation," \
            "then take this checkpoint.  Nothing was committed."
    fi
    attributes="$(committed_lines ".gitattributes")"
    for row in "${REQUIRED_ATTRIBUTES[@]}"; do
        # Whole-line matching with no pipe in it; see vcs_rule_problems
        # for why `grep -q` on the far end of a pipe can report a row
        # that is present as missing.
        case $'\n'"${attributes}"$'\n' in
            *$'\n'"${row}"$'\n'*) ;;
            *) missing+=("${row}") ;;
        esac
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        die "${EX_PREREQ}" "HEAD's .gitattributes is missing" \
            "${#missing[@]} row(s) this feature depends on:" \
            "${missing[*]}.  The film, the save and the compressed map" \
            "archives are binary and the cue file and the record are" \
            "text; without those rows they are left to '* text=auto'," \
            "which is content detection rather than a declaration." \
            "Commit .gitattributes first.  Nothing was committed."
    fi
    # THE ROWS ARE THERE; WOULD GIT APPLY THEM?
    if check_attr_supports_source; then
        assert_attribute_semantics "HEAD" HEAD
    else
        playthrough_warn "this git cannot be asked what attributes a" \
            "tree-ish would apply ('git check-attr --source' arrived in" \
            "git 2.40), so HEAD's six rows were checked as rows and not" \
            "as effective attributes.  The working tree's effective" \
            "attributes are checked either way, and they are the ones" \
            "this run's 'git add' applies."
    fi
    playthrough_log "HEAD's own .gitignore ends with" \
        "'${IGNORE_NEGATION}' and its .gitattributes carries all" \
        "${#REQUIRED_ATTRIBUTES[@]} of this feature's rows, so a fresh" \
        "clone of this history keeps the save data and the binary" \
        "artifacts intact"
    return 0
}


# ---------------------------------------------------------------------
# THE HYGIENE GATE.
# .gitignore ends with a terminal `!/playthrough/**` negation, without which
# the engine's own `#<name>.sav` and `.log` files would be silently skipped by
# `git add`.
# ---------------------------------------------------------------------

# The names that must not be inside playthrough/ when a checkpoint is taken, as
# `find` predicates.
readonly -a HYGIENE_NAMES=(
    "__pycache__"
    "*.pyc"
    "*.pyo"
    "blitzy_adhoc_test_*"
    ".*.previous.mp4"
    ".*.rejected.mp4"
    "*.orig"
    "*.rej"
    # RUNTIME AND AUTH STATE, which is the same hazard one step worse.
    "Xauthority"
    "*.pid"
    "x-ownership*"
    "capture-stage-*.err"
)

# TWO PATTERNS ARE DELIBERATELY ABSENT FROM THAT LIST, and this note is here
# because both look like obvious omissions and adding either would break the
# checkpoint outright.

# assert_runtime_root_is_outside -- the root cause, refused here too.
assert_runtime_root_is_outside() {
    local runtime="${PLAYTHROUGH_RUNTIME_DIR:-}"
    if [ -z "${runtime}" ]; then
        return 0
    fi
    if playthrough_path_within "${PLAYTHROUGH_REPO_ROOT}" "${runtime}" ||
       playthrough_path_within "${runtime}" "${PLAYTHROUGH_REPO_ROOT}"
    then
        die "${EX_SCOPE}" "the pipeline runtime root" \
            "'$(rel "${runtime}")' is inside this checkout (or" \
            "contains it), and a checkpoint is about to stage" \
            "$(rel "${PLAYTHROUGH_DIR}").  That root holds the X" \
            "authority COOKIE, the pid and lock files and any withdrawn" \
            "frame, and .gitignore's terminal '!/playthrough/**'" \
            "negation re-includes everything under this tree -- so the" \
            "cookie would be committed, and a credential in a published" \
            "commit cannot be withdrawn, only rotated.  Unset" \
            "PLAYTHROUGH_RUNTIME_DIR to use the default beneath" \
            "\$XDG_RUNTIME_DIR, or nominate a directory outside the" \
            "repository, then run this again.  Nothing was committed."
    fi
    return 0
}

assert_no_machine_files() {
    assert_runtime_root_is_outside
    local -a predicates=()
    local name found=()
    local path
    for name in "${HYGIENE_NAMES[@]}"; do
        if [ "${#predicates[@]}" -gt 0 ]; then
            predicates+=("-o")
        fi
        predicates+=("-name" "${name}")
    done
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        found+=("$(rel "${path}")")
    done < <("${FIND}" "${PLAYTHROUGH_DIR}" \
        \( "${predicates[@]}" \) -print 2>/dev/null | "${SORT}")
    if [ "${#found[@]}" -gt 0 ]; then
        die "${EX_SCOPE}" "machine-local files are inside" \
            "$(rel "${PLAYTHROUGH_DIR}"), where .gitignore's terminal" \
            "'!/playthrough/**' negation RE-INCLUDES them, so a" \
            "checkpoint would commit them as though they were" \
            "evidence: ${found[*]}.  Remove them (test modules run" \
            "with 'python -B'; a quarantined film belongs OUTSIDE the" \
            "tree) and run this again.  Nothing was committed."
    fi
    return 0
}

# ---------------------------------------------------------------------
# THE PERSISTENCE GATE. At creation there is exactly one live world and one
# live survivor.
# ---------------------------------------------------------------------

# The engine's own spellings, from the headers rather than from memory.
readonly SAVE_EXTENSION=".sav"
readonly SAVE_EXTENSION_LOG=".log"
readonly SAVE_ZZIP_SUFFIX=".zzip"
readonly SAVE_MASTER="master.gsav"

# The two `find -name` predicates that between them match every form of
# a character save this platform writes.
readonly -a SAVE_FIND_PREDICATE=(
    "(" -name "#*${SAVE_EXTENSION}"
    -o -name "#*${SAVE_EXTENSION}${SAVE_ZZIP_SUFFIX}" ")"
)

# save_stem PATH -- a character save path with the optional .zzip
# suffix and then the save extension removed, so the sibling log can be
# named from either spelling.
save_stem() {
    local path="$1"
    path="${path%"${SAVE_ZZIP_SUFFIX}"}"
    printf '%s' "${path%"${SAVE_EXTENSION}"}"
}

# save_is_compressed PATH -- true for the zzip form.  The gate reads the
# plain form as JSON and cannot read the archive, and that difference is
# reported rather than glossed over.
save_is_compressed() {
    case "$1" in
        *"${SAVE_EXTENSION}${SAVE_ZZIP_SUFFIX}") return 0 ;;
    esac
    return 1
}

WORLD_NAME=""
CHARACTER_NAME=""
ENCODED_CHARACTER=""
SAVE_FILE=""
PERSISTENCE_KIND=""
declare -a REQUIRED_PERSISTENCE_FILES=()
LOADED_WORLD=""
LOADED_CHARACTER=""
LOADED_ENCODED=""

# The decoder.
readonly LASTWORLD_READER='
import base64
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    record = json.load(handle)
world = record.get("world_name") or ""
character = record.get("character_name") or ""
encoded = base64.b64encode(
    character.encode("utf-8"), altchars=b"+-").decode("ascii")
sys.stdout.write("%s\n%s\n%s\n" % (world, character, encoded))
'

readonly DEATH_EVIDENCE_READER='
import json
import sys


def fail(message):
    sys.stderr.write("playthrough: death evidence: %s\n" % message)
    raise SystemExit(1)


def load_object(path, label):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, ValueError) as error:
        fail("%s is unreadable as JSON: %s" % (label, error))
    if not isinstance(value, dict):
        fail("%s is not a JSON object" % label)
    return value


def names_avatar(value, character):
    if isinstance(value, dict):
        if value.get("avatar_name") == ["string", character]:
            return True
        return any(names_avatar(one, character)
                   for one in value.values())
    if isinstance(value, list):
        return any(names_avatar(one, character) for one in value)
    return False


(grave_path, grave_form, memorial_path, prose_path, manifest_path,
 character) = sys.argv[1:]
if grave_form == "plain":
    grave = load_object(grave_path, "the graveyard save")
    player = grave.get("player")
    if not isinstance(player, dict) or player.get("name") != character:
        fail("the graveyard save does not name %r as its player"
             % character)
    if grave.get("debug_mode") is not False:
        fail("the graveyard save does not record debug_mode=false")
else:
    # The .sav.zzip form is a zstd-framed archive that this reader cannot open,
    # so the two checks above were NOT performed.
    sys.stderr.write(
        "playthrough: death evidence: %s is the compressed save form, "
        "so its inner JSON was NOT inspected -- the memorial pair and "
        "the captured death sequence still decide\n" % grave_path)

memorial = load_object(memorial_path, "the JSON memorial")
entries = memorial.get("log")
messages = [
    str(one.get("message") or "")
    for one in entries
    if isinstance(one, dict)
] if isinstance(entries, list) else []
if "%s was killed." % character not in messages:
    fail("the JSON memorial does not say that %s was killed" % character)
if "Died" not in messages:
    fail("the JSON memorial has no terminal Died event")
if not names_avatar(memorial, character):
    fail("the memorial statistics do not name %s as avatar" % character)
last_words = ""
for message in messages:
    if message.startswith("Last words: "):
        last_words = message[len("Last words: "):]
        break

try:
    with open(prose_path, "r", encoding="utf-8") as handle:
        prose = handle.read()
except (OSError, UnicodeError) as error:
    fail("the text memorial is unreadable: %s" % error)
if "In memory of: %s" % character not in prose:
    fail("the text memorial names another survivor")
if " died on " not in prose:
    fail("the text memorial does not record the death date")

try:
    with open(manifest_path, "r", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
except (OSError, UnicodeError, ValueError) as error:
    fail("the manifest is unreadable: %s" % error)
last_words_frame = None
post_death_frame = None
words_recorded = not last_words
post_markers = (
    "post-death",
    "after death",
    "deathcam",
    "scores screen",
    "follower epilogue",
)
for row in rows:
    if not isinstance(row, dict):
        fail("the manifest contains a non-object row")
    frame = row.get("frame")
    action = str(row.get("action") or "")
    commentary = str(row.get("commentary") or "")
    lowered = action.lower()
    if last_words_frame is None and "last words" in lowered:
        if isinstance(frame, int):
            last_words_frame = frame
    elif (last_words_frame is not None and isinstance(frame, int)
          and frame > last_words_frame
          and any(marker in lowered for marker in post_markers)):
        post_death_frame = frame
    if last_words and last_words.lower() in (
            action + "\n" + commentary).lower():
        words_recorded = True
if last_words_frame is None or post_death_frame is None:
    fail("the manifest has no captured last-words screen followed by "
         "a captured post-death screen")
if not words_recorded:
    fail("the manifest never records the memorial last words %r"
         % last_words)
'

read_loaded_identity() {
    local lastworld="${PLAYTHROUGH_CONFIG_DIR}/lastworld.json"
    if [ ! -f "${lastworld}" ]; then
        die "${EX_EVIDENCE}" "the engine has written no" \
            "$(rel "${lastworld}"), so which world and survivor were" \
            "actually loaded is not recorded anywhere this gate can" \
            "read.  That file appears the moment a world is loaded;" \
            "its absence means the session under this userdir never" \
            "got that far.  Nothing was committed."
    fi
    local reading
    if ! reading="$("${PLAYTHROUGH_PYTHON}" -c "${LASTWORLD_READER}" \
            "${lastworld}" 2>/dev/null)"; then
        die "${EX_EVIDENCE}" "$(rel "${lastworld}") could not be" \
            "read as JSON, so the loaded world and survivor cannot be" \
            "held against the save on disk.  An unreadable check is a" \
            "refusal here, not a skipped one.  Nothing was committed."
    fi
    local -a fields=()
    # mapfile rather than a pipeline: three fields read in the shell
    # itself, so nothing depends on another external tool and a name
    # carrying an unexpected character cannot be re-split by a filter.
    mapfile -t fields <<<"${reading}"
    LOADED_WORLD="${fields[0]-}"
    LOADED_CHARACTER="${fields[1]-}"
    LOADED_ENCODED="${fields[2]-}"
    if [ -z "${LOADED_WORLD}" ] || [ -z "${LOADED_CHARACTER}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${lastworld}") names no world or" \
            "no character, so the session cannot be attributed to a" \
            "survivor.  Nothing was committed."
    fi
    return 0
}

assert_live_save() {
    local world_dir="$1"
    local -a saves=()
    local path
    WORLD_NAME="${world_dir##*/}"
    if [ ! -f "${world_dir}/${SAVE_MASTER}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${world_dir}") holds no" \
            "${SAVE_MASTER}, so the world has not been saved.  Save and" \
            "quit through the game's own menu first."
    fi
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        saves+=("${path}")
    done < <("${FIND}" "${world_dir}" -mindepth 1 -maxdepth 1 \
        -type f "${SAVE_FIND_PREDICATE[@]}" -print 2>/dev/null |
        "${SORT}")
    if [ "${#saves[@]}" -ne 1 ]; then
        die "${EX_EVIDENCE}" "${#saves[@]} character save(s) in" \
            "$(rel "${world_dir}") and the requirement is one unique" \
            "survivor: ${saves[*]:-none}.  Nothing was committed."
    fi
    SAVE_FILE="${saves[0]}"
    read_loaded_identity
    if [ "${LOADED_WORLD}" != "${WORLD_NAME}" ]; then
        die "${EX_EVIDENCE}" "the engine last loaded the world" \
            "'${LOADED_WORLD}' and the only save on disk is" \
            "'${WORLD_NAME}'.  The artifacts and the save would be" \
            "attributed to different worlds.  Nothing was committed."
    fi
    # Either spelling the engine may have written, and no preference
    # between them: the world's compression setting is the engine's
    # business, not this gate's.
    local expected="${world_dir}/#${LOADED_ENCODED}${SAVE_EXTENSION}"
    local expected_zzip="${expected}${SAVE_ZZIP_SUFFIX}"
    if [ "${expected}" != "${SAVE_FILE}" ] &&
       [ "${expected_zzip}" != "${SAVE_FILE}" ]; then
        die "${EX_EVIDENCE}" "the engine last loaded" \
            "'${LOADED_CHARACTER}', whose save file would be" \
            "$(rel "${expected}") or $(rel "${expected_zzip}"), and the" \
            "only save on disk is $(rel "${SAVE_FILE}").  A checkpoint" \
            "cannot say which survivor it is about, so it says nothing." \
            "Nothing was committed."
    fi
    CHARACTER_NAME="${LOADED_CHARACTER}"
    ENCODED_CHARACTER="${LOADED_ENCODED}"
    PERSISTENCE_KIND="live"
    REQUIRED_PERSISTENCE_FILES=(
        "${SAVE_FILE}"
        "${world_dir}/${SAVE_MASTER}"
    )
    return 0
}

assert_death_persistence() {
    local world_dir="${1-}"
    read_loaded_identity
    WORLD_NAME="${LOADED_WORLD}"
    CHARACTER_NAME="${LOADED_CHARACTER}"
    ENCODED_CHARACTER="${LOADED_ENCODED}"
    if [ -n "${world_dir}" ] &&
       [ "${world_dir##*/}" != "${WORLD_NAME}" ]; then
        die "${EX_EVIDENCE}" "the engine last loaded the world" \
            "'${WORLD_NAME}' and the only post-death world directory is" \
            "'${world_dir##*/}'.  The death artifacts and engine record" \
            "would be attributed to different worlds.  Nothing was" \
            "committed."
    fi

    local graveyard="${PLAYTHROUGH_USERDIR}/graveyard"
    local -a grave_saves=()
    local path
    if [ -d "${graveyard}" ]; then
        while IFS= read -r path; do
            [ -n "${path}" ] || continue
            grave_saves+=("${path}")
        done < <("${FIND}" "${graveyard}" -mindepth 2 -maxdepth 2 \
            -type f "${SAVE_FIND_PREDICATE[@]}" -print 2>/dev/null |
            "${SORT}")
    fi
    local expected_name="#${ENCODED_CHARACTER}${SAVE_EXTENSION}"
    local expected_zzip="${expected_name}${SAVE_ZZIP_SUFFIX}"
    if [ "${#grave_saves[@]}" -ne 1 ] ||
       { [ "${grave_saves[0]##*/}" != "${expected_name}" ] &&
         [ "${grave_saves[0]##*/}" != "${expected_zzip}" ]; }; then
        die "${EX_EVIDENCE}" "the final checkpoint has no live survivor" \
            "and the graveyard holds ${#grave_saves[@]} character" \
            "save(s), not exactly the pinned survivor" \
            "${expected_name} (or ${expected_zzip}):" \
            "${grave_saves[*]:-none}.  A manual" \
            "deletion is not a death ending.  Nothing was committed."
    fi
    local grave_save="${grave_saves[0]}"
    local grave_log
    grave_log="$(save_stem "${grave_save}")${SAVE_EXTENSION_LOG}"
    if [ ! -f "${grave_log}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${grave_save}") has no" \
            "same-generation character log at $(rel "${grave_log}")." \
            "A copied save is not the engine's complete death cleanup." \
            "Nothing was committed."
    fi

    local memorial_dir="${PLAYTHROUGH_USERDIR}/memorial/${WORLD_NAME}"
    local -a memorial_json=() memorial_text=()
    if [ -d "${memorial_dir}" ]; then
        while IFS= read -r path; do
            [ -n "${path}" ] || continue
            local name="${path##*/}"
            case "${name}" in
                "${CHARACTER_NAME}"-*.json)
                    memorial_json+=("${path}")
                    ;;
                "${CHARACTER_NAME}"-*.txt)
                    memorial_text+=("${path}")
                    ;;
            esac
        done < <("${FIND}" "${memorial_dir}" -mindepth 1 -maxdepth 1 \
            -type f -print 2>/dev/null | "${SORT}")
    fi
    if [ "${#memorial_json[@]}" -ne 1 ] ||
       [ "${#memorial_text[@]}" -ne 1 ]; then
        die "${EX_EVIDENCE}" "the graveyard save exists, but" \
            "$(rel "${memorial_dir}") holds ${#memorial_json[@]} JSON" \
            "and ${#memorial_text[@]} text memorial(s) for" \
            "'${CHARACTER_NAME}'.  Death cleanup requires one matching" \
            "pair.  Nothing was committed."
    fi

    local grave_form="plain"
    if save_is_compressed "${grave_save}"; then
        grave_form="compressed"
    fi
    if ! "${PLAYTHROUGH_PYTHON}" -c "${DEATH_EVIDENCE_READER}" \
            "${grave_save}" "${grave_form}" "${memorial_json[0]}" \
            "${memorial_text[0]}" "${PLAYTHROUGH_MANIFEST}" \
            "${CHARACTER_NAME}"; then
        die "${EX_EVIDENCE}" "the death-generation artifacts above do" \
            "not jointly prove the pinned survivor's engine-authored" \
            "death cleanup.  Nothing was committed."
    fi
    SAVE_FILE="${grave_save}"
    PERSISTENCE_KIND="death"
    REQUIRED_PERSISTENCE_FILES=(
        "${grave_save}"
        "${grave_log}"
        "${memorial_json[0]}"
        "${memorial_text[0]}"
    )
    return 0
}

assert_save_tree() {
    local checkpoint="$1"
    local -a worlds=()
    local path
    if [ -d "${PLAYTHROUGH_SAVE_DIR}" ]; then
        while IFS= read -r path; do
            [ -n "${path}" ] || continue
            worlds+=("${path}")
        done < <("${FIND}" "${PLAYTHROUGH_SAVE_DIR}" -mindepth 1 \
            -maxdepth 1 -type d -print 2>/dev/null | "${SORT}")
    elif ! is_post_session_checkpoint "${checkpoint}"; then
        die "${EX_EVIDENCE}" "there is no save tree at" \
            "$(rel "${PLAYTHROUGH_SAVE_DIR}").  A checkpoint records a" \
            "save that exists; it does not promise one."
    fi
    if [ "${#worlds[@]}" -gt 1 ]; then
        die "${EX_EVIDENCE}" "the save tree holds" \
            "${#worlds[@]} world director(ies) and the session is one" \
            "world: ${worlds[*]}.  A second world means a second run" \
            "has written here, and which one the artifacts belong to is" \
            "then unanswerable.  Nothing was committed."
    fi

    if [ "${#worlds[@]}" -eq 1 ]; then
        local world_dir="${worlds[0]}"
        local live_count
        live_count="$("${FIND}" "${world_dir}" -mindepth 1 -maxdepth 1 \
            -type f "${SAVE_FIND_PREDICATE[@]}" -print 2>/dev/null |
            "${WC}" -l | "${TR}" -d ' ')"
        if [ "${live_count}" -gt 0 ]; then
            assert_live_save "${world_dir}"
        elif is_post_session_checkpoint "${checkpoint}"; then
            assert_death_persistence "${world_dir}"
        elif [ ! -f "${world_dir}/${SAVE_MASTER}" ]; then
            die "${EX_EVIDENCE}" "$(rel "${world_dir}") holds no" \
                "${SAVE_MASTER}, so the world has not been saved.  Save" \
                "and quit through the game's own menu first."
        else
            die "${EX_EVIDENCE}" "0 character save(s) in" \
                "$(rel "${world_dir}") and the requirement is one unique" \
                "survivor.  Nothing was committed."
        fi
    elif is_post_session_checkpoint "${checkpoint}"; then
        assert_death_persistence
    else
        die "${EX_EVIDENCE}" "the save tree holds 0 world director(ies)" \
            "and the session is one world.  Nothing was committed."
    fi

    readonly WORLD_NAME CHARACTER_NAME ENCODED_CHARACTER SAVE_FILE
    readonly PERSISTENCE_KIND
    readonly -a REQUIRED_PERSISTENCE_FILES
    if [ "${PERSISTENCE_KIND}" = "death" ]; then
        playthrough_log "the death persistence is ${WORLD_NAME} /" \
            "${CHARACTER_NAME}, at $(rel "${SAVE_FILE}") with one" \
            "matching memorial pair"
    else
        playthrough_log "the save is ${WORLD_NAME} /" \
            "${CHARACTER_NAME:-<unnamed>}, at $(rel "${SAVE_FILE}")"
    fi
    return 0
}


# ---------------------------------------------------------------------
# THE EVIDENCE GATE. One keystroke, one capture, one row, one observation --
# checked by counting all four, not by trusting that the session kept them in
# step.
# ---------------------------------------------------------------------

FRAME_COUNT=0
ROW_COUNT=0

count_matching() {
    local dir="$1" pattern="$2"
    if [ ! -d "${dir}" ]; then
        printf '0'
        return 0
    fi
    "${FIND}" "${dir}" -mindepth 1 -maxdepth 1 -type f \
        -name "${pattern}" -print 2>/dev/null |
        "${WC}" -l |
        "${TR}" -d ' '
}

assert_evidence() {
    if [ ! -s "${PLAYTHROUGH_MANIFEST}" ]; then
        die "${EX_EVIDENCE}" "there is no record at" \
            "$(rel "${PLAYTHROUGH_MANIFEST}").  A checkpoint commits a" \
            "session that was captured; there is nothing here to" \
            "commit."
    fi
    local manifest_script="${PLAYTHROUGH_TOOLING_DIR}/manifest.py"
    if [ ! -f "${manifest_script}" ]; then
        die "${EX_PREREQ}" "$(rel "${manifest_script}") is missing," \
            "so the record cannot be verified before it is committed." \
            "Nothing was committed."
    fi
    # The ledger first: `verify` below resolves it, so a broken binding
    # would otherwise be reported as a refusal of the record.
    assert_amendment_ledger
    # --require-frames is the whole point of delegating: it holds every
    # row against the capture it names.  Its stderr is the diagnosis and
    # is passed through unchanged.
    if ! "${PLAYTHROUGH_PYTHON}" -B "${manifest_script}" verify \
            --require-frames >&2; then
        die "${EX_EVIDENCE}" "manifest.py refused the record above." \
            "The problems it names are in the evidence itself -- a" \
            "voice or clock statement that does not survive its own" \
            "gate, a broken frame sequence, a missing capture -- and" \
            "the record is append-only, so they are fixed by" \
            "RE-RECORDING the session and never by editing what was" \
            "written.  Nothing was committed."
    fi
    ROW_COUNT="$("${PLAYTHROUGH_PYTHON}" -B "${manifest_script}" \
        count 2>/dev/null || printf '')"
    case "${ROW_COUNT}" in
        ''|*[!0-9]*)
            die "${EX_EVIDENCE}" "manifest.py could not count the" \
                "rows in $(rel "${PLAYTHROUGH_MANIFEST}"), so the" \
                "one-frame-per-keystroke invariant cannot be checked." \
                "Nothing was committed."
            ;;
    esac
    FRAME_COUNT="$(count_matching "${PLAYTHROUGH_FRAMES_DIR}" \
        'frame_*.png')"
    readonly ROW_COUNT FRAME_COUNT
    if [ "${FRAME_COUNT}" -ne "${ROW_COUNT}" ]; then
        die "${EX_EVIDENCE}" "${FRAME_COUNT} capture(s) in" \
            "$(rel "${PLAYTHROUGH_FRAMES_DIR}") against ${ROW_COUNT}" \
            "row(s) in $(rel "${PLAYTHROUGH_MANIFEST}").  One" \
            "keystroke is one capture is one row, so a capture with no" \
            "row is a frame nobody can account for and a row with no" \
            "capture is a claim with no photograph.  Nothing was" \
            "committed."
    fi
    if [ "${ROW_COUNT}" -lt 1 ]; then
        die "${EX_EVIDENCE}" "the record is empty.  Nothing was" \
            "committed."
    fi
    assert_observations_match
    assert_ledgers
    playthrough_log "${FRAME_COUNT} capture(s), ${ROW_COUNT} row(s)," \
        "the sidecar agrees, and every capture matches its attestation"
    return 0
}

# ---------------------------------------------------------------------
# THE TWO OUT-OF-BAND LEDGERS, CHECKED BEFORE ANYTHING IS STAGED.
# The manifest is append-only, so the two things it cannot itself carry live
# beside it and are verified here rather than at the moment a reader happens
# to look:
#
#   * amendments.jsonl -- a correction names the sha256 of the exact
#     manifest line it corrects.  If that line has changed the amendment no
#     longer describes it, and the resolution is REFUSED rather than applied
#     to whatever now occupies that row.
#   * build/frame_digests.jsonl -- every recorded frame's captured bytes.  A
#     capture is verified by re-hashing the PNG on disk, which is the only
#     check in this pipeline that a same-sized, non-blank, correctly named
#     REPLACEMENT image cannot pass; every structural check above -- the
#     count identity, the geometry, the luminance -- it passes easily.
#
# Both run before stage_artifacts(), so a mismatch stops the checkpoint while
# the previous commit is still the last word.
# ---------------------------------------------------------------------

# The amendment half, separately, because it runs BEFORE the record gate.
assert_amendment_ledger() {
    local manifest_script="${PLAYTHROUGH_TOOLING_DIR}/manifest.py"
    if [ ! -s "${PLAYTHROUGH_AMENDMENTS}" ]; then
        return 0
    fi
    if ! "${PLAYTHROUGH_PYTHON}" -B "${manifest_script}" \
            amendments >&2; then
        die "${EX_EVIDENCE}" "manifest.py refused the amendment" \
            "ledger above.  Every amendment names the sha256 of" \
            "the manifest line it corrects, so a complaint here" \
            "means a correction no longer matches the line it was" \
            "written against -- and the record is append-only, so" \
            "the answer is a NEW amendment against the line as it" \
            "actually stands, never an edit to either file." \
            "Nothing was committed."
    fi
    return 0
}

assert_ledgers() {
    local manifest_script="${PLAYTHROUGH_TOOLING_DIR}/manifest.py"
    assert_amendment_ledger
    if [ ! -s "${PLAYTHROUGH_FRAME_DIGESTS}" ]; then
        die "${EX_EVIDENCE}" "there is no capture attestation ledger" \
            "at $(rel "${PLAYTHROUGH_FRAME_DIGESTS}").  It holds the" \
            "sha256 of every frame as it was published, and without it" \
            "nothing distinguishes the pixels that were captured from" \
            "a same-sized image put in their place afterwards -- which" \
            "is the one substitution every other gate here passes." \
            "Nothing was committed."
    fi
    if ! "${PLAYTHROUGH_PYTHON}" -B "${manifest_script}" digests >&2; then
        die "${EX_EVIDENCE}" "manifest.py refused the captures above." \
            "A frame no longer hashes to the digest attested for it, or" \
            "a recorded frame has no attestation at all.  A frame is" \
            "evidence and evidence is not re-authored, so this is" \
            "resolved by restoring the captured bytes -- they are in" \
            "git history -- and never by re-attesting whatever is on" \
            "disk now.  Nothing was committed."
    fi
    return 0
}

assert_observations_match() {
    local sidecar="${PLAYTHROUGH_OBSERVATIONS}"
    if [ ! -f "${sidecar}" ]; then
        die "${EX_EVIDENCE}" "the observation sidecar" \
            "$(rel "${sidecar}") is missing.  It carries what was" \
            "actually READ off each capture, which is what makes the" \
            "manifest's clock column auditable rather than asserted," \
            "and session.py writes one row per frame.  Its absence" \
            "means the session's own record of what it saw is gone." \
            "Nothing was committed."
    fi
    local lines
    lines="$("${WC}" -l <"${sidecar}" | "${TR}" -d ' ')"
    case "${lines}" in
        ''|*[!0-9]*) lines="-1" ;;
    esac
    if [ "${lines}" -ne "${ROW_COUNT}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${sidecar}") holds ${lines}" \
            "row(s) against the manifest's ${ROW_COUNT}.  The two are" \
            "written by the same step for the same frame, so a" \
            "disagreement means one of them was not written and the" \
            "pairing between a reading and the row it justifies is" \
            "broken.  Nothing was committed."
    fi
    return 0
}

# ---------------------------------------------------------------------
# THE DOSSIER GATE.
# The survivor's first-person dossier is required to have been written BEFORE
# play and committed BEFORE the first gameplay frame, and that ordering is read
# straight out of the history: the dossier's first commit must be reachable
# from the commit carrying the first capture.
# ---------------------------------------------------------------------

assert_dossier() {
    local checkpoint="$1"
    local path="${PLAYTHROUGH_DOSSIER}"
    if [ ! -e "${path}" ]; then
        die "${EX_EVIDENCE}" "there is no survivor dossier at" \
            "$(rel "${path}").  It is the first-person account of who" \
            "this person was, written BEFORE the first keystroke, and" \
            "the '${CHECKPOINT_DOSSIER}' checkpoint is what puts it in" \
            "the history ahead of the first capture.  Write it, then" \
            "take that checkpoint.  Nothing was committed."
    fi
    if [ ! -s "${path}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${path}") is empty.  An empty" \
            "dossier is the same absence with a file in the way: the" \
            "requirement is a written backstory, not a placeholder." \
            "Nothing was committed."
    fi
    if is_post_session_checkpoint "${checkpoint}" &&
       ! "${GIT}" ls-files --error-unmatch -- "${path}" \
            >/dev/null 2>&1; then
        die "${EX_LIFECYCLE}" "$(rel "${path}") exists but git does" \
            "not track it, so no earlier commit can have carried it" \
            "and the dossier-before-the-first-frame ordering is" \
            "unprovable from this history.  That ordering is checked" \
            "with 'git log' over the file, so a dossier written later" \
            "reads exactly like one written after the fact.  Take" \
            "'commit_artifacts.sh ${CHECKPOINT_DOSSIER}' before the" \
            "session, not after it.  Nothing was committed."
    fi
    playthrough_log "the survivor's dossier is at $(rel "${path}")"
    return 0
}

# ---------------------------------------------------------------------
# THE FINAL REPORT GATE.
# The feature's deliverable is not only the film: it is the film PLUS the
# report that says what was recorded, who the survivor was and how the session
# ended.
# ---------------------------------------------------------------------

# The three headings, in order, as ATX level-two Markdown -- which is how the
# report writes them and how a reader's table of contents finds them.
readonly -a REPORT_SECTIONS=(
    "## A) Screen Recording and Animation"
    "## B) Character Creation"
    "## C) Playing the Game"
)

# report_sections -- every level-two heading of the report, in order, one
# per line, with surrounding whitespace collapsed so a heading written
# with a trailing space is recognised as the heading it is.
report_sections() {
    # SC2016: the '$' characters belong to the awk program -- the
    # end-of-line anchor and $0 -- exactly as in committed_lines above.
    # shellcheck disable=SC2016
    "${AWK}" '/^##[ \t]+[^#]/ {
        gsub(/^[ \t]+|[ \t]+$/, "");
        gsub(/[ \t]+/, " ");
        print
    }' "$1" 2>/dev/null || printf ''
}

# assert_report -- the mandated three-section report, demanded at the one
# checkpoint that can honestly carry it.
assert_report() {
    local checkpoint="$1"
    local path="${PLAYTHROUGH_REPORT}"
    local -a found=()
    local heading="" expected="" index=0
    if [ "${checkpoint}" != "${CHECKPOINT_ATTEST}" ]; then
        return 0
    fi
    if [ ! -e "${path}" ]; then
        die "${EX_EVIDENCE}" "there is no final report at" \
            "$(rel "${path}").  It is the document the recording is" \
            "delivered as -- what was captured, who the survivor was," \
            "how the session ended -- and its three sections are" \
            "'${REPORT_SECTIONS[0]#\#\# }'," \
            "'${REPORT_SECTIONS[1]#\#\# }' and" \
            "'${REPORT_SECTIONS[2]#\#\# }', in that order.  Write it," \
            "then take this checkpoint.  Nothing was committed."
    fi
    if [ ! -s "${path}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${path}") is empty, which is the" \
            "same absence with a file in the way.  Nothing was" \
            "committed."
    fi
    while IFS= read -r heading; do
        [ -n "${heading}" ] || continue
        found+=("${heading}")
    done < <(report_sections "${path}")
    if [ "${#found[@]}" -ne "${#REPORT_SECTIONS[@]}" ]; then
        die "${EX_EVIDENCE}" "$(rel "${path}") carries" \
            "${#found[@]} top-level section(s) --" \
            "${found[*]:-none} -- where the report has exactly" \
            "${#REPORT_SECTIONS[@]}: ${REPORT_SECTIONS[*]}.  A report" \
            "with fewer is unfinished; one with more has grown a" \
            "section the requirement does not have.  Nothing was" \
            "committed."
    fi
    for index in "${!REPORT_SECTIONS[@]}"; do
        expected="${REPORT_SECTIONS[${index}]}"
        if [ "${found[${index}]}" != "${expected}" ]; then
            die "${EX_EVIDENCE}" "$(rel "${path}") has" \
                "'${found[${index}]}' where section" \
                "$((index + 1)) must be '${expected}'.  The three" \
                "sections are fixed and so is their order:" \
                "${REPORT_SECTIONS[*]}.  Nothing was committed."
        fi
    done
    playthrough_log "the final report at $(rel "${path}") carries all" \
        "${#REPORT_SECTIONS[@]} of its sections, in order"
    return 0
}

# report_note FILE KEY -- one value from a report's machine block.
#
# verify_artifacts.sh closes every report with `KEY=value` lines, which
# exist so a caller can act on the verdict instead of parsing prose.  The
# LAST occurrence wins, because a report is appended to as it runs and the
# closing block is the authoritative one.
report_note() {
    local file="$1" key="$2" line="" value=""
    while IFS= read -r line; do
        case "${line}" in
            "${key}="*) value="${line#*=}" ;;
        esac
    done <"${file}"
    printf '%s' "${value}"
}

# assert_acceptance_report -- the measurement this checkpoint publishes,
# validated before a byte of it is copied into the tree.
assert_acceptance_report() {
    local checkpoint="$1"
    local source="${PLAYTHROUGH_ACCEPTANCE_SCRATCH}"
    local verdict="" measured="" phase="" head=""
    if [ "${checkpoint}" != "${CHECKPOINT_ATTEST}" ]; then
        return 0
    fi
    if [ ! -s "${source}" ]; then
        die "${EX_EVIDENCE}" "there is no acceptance report to publish" \
            "at ${source}.  It is written by" \
            "'verify_artifacts.sh --phase ${GATE_HISTORY_PHASE}" \
            "--report-to ${source}', which run_pipeline.sh runs" \
            "immediately after the '${CHECKPOINT_MEDIA}' checkpoint --" \
            "the gate does not write inside the tree it measures, so" \
            "this step is what puts the report in the history.  Run" \
            "the gate, then take this checkpoint.  Nothing was" \
            "committed."
    fi
    verdict="$(report_note "${source}" VERIFY)"
    local publishable="" candidate=""
    for candidate in "${GATE_PUBLISHABLE_VERDICTS[@]}"; do
        if [ "${verdict}" = "${candidate}" ]; then
            publishable="yes"
            break
        fi
    done
    if [ -z "${publishable}" ]; then
        die "${EX_EVIDENCE}" "the acceptance report at ${source}" \
            "records VERIFY=${verdict:-none}, so the artifacts did not" \
            "satisfy the gate.  Committing it would archive a failing" \
            "measurement as the evidence of a compliant run.  Fix what" \
            "the report reports, run the gate again, then take this" \
            "checkpoint.  Nothing was committed.  The verdicts that MAY" \
            "be published are ${GATE_PUBLISHABLE_VERDICTS[*]} --" \
            "'pass-with-divergence' is among them deliberately, because" \
            "a report that names a documented divergence honestly is" \
            "evidence and a report that calls one a pass is the defect."
    fi
    if [ "${verdict}" != "pass" ]; then
        local diverged=""
        diverged="$(report_note "${source}" VERIFY_DIVERGENCES)"
        playthrough_log "the acceptance report records" \
            "VERIFY=${verdict} with ${diverged:-an unstated number of}" \
            "divergence(s) from the plan, each printed in full in the" \
            "report itself; publishing it because a named divergence is" \
            "evidence, not a failure"
    fi
    phase="$(report_note "${source}" VERIFY_PHASE)"
    if [ "${phase}" != "${GATE_HISTORY_PHASE}" ] &&
            [ "${phase}" != "${GATE_EVERY_PHASE}" ]; then
        die "${EX_EVIDENCE}" "the acceptance report at ${source} was" \
            "produced by the '${phase:-unknown}' phase, which does not" \
            "measure the history.  The report this checkpoint commits" \
            "is the one that attests to what the commits now prove, so" \
            "it has to come from '${GATE_HISTORY_PHASE}' or" \
            "'${GATE_EVERY_PHASE}'.  Nothing was committed."
    fi
    measured="$(report_note "${source}" VERIFY_MEASURED_COMMIT)"
    head="$("${GIT}" rev-parse --short=10 HEAD 2>/dev/null || true)"
    if [ "${measured}" != "HEAD ${head}" ]; then
        die "${EX_LIFECYCLE}" "the acceptance report at ${source} says" \
            "it measured '${measured:-nothing}' while HEAD is now" \
            "${head:-nothing}.  A report is evidence about one tree," \
            "and committing this one would put a measurement of a" \
            "different tree into the history under this tree's name --" \
            "which is the defect this comparison exists to make" \
            "impossible.  Re-run the gate against HEAD and take this" \
            "checkpoint immediately afterwards, with no commit in" \
            "between.  Nothing was committed."
    fi
    playthrough_log "the acceptance report at ${source} passed the" \
        "'${phase}' phase over ${measured}, which is this HEAD"
    return 0
}

# publish_acceptance_report -- the one write this step makes into the tree.
publish_acceptance_report() {
    local source="${PLAYTHROUGH_ACCEPTANCE_SCRATCH}"
    local target="${PLAYTHROUGH_ACCEPTANCE_REPORT}"
    if ! "${CAT}" -- "${source}" >"${target}"; then
        die "${EX_EVIDENCE}" "the acceptance report could not be" \
            "copied from ${source} to $(rel "${target}").  Nothing was" \
            "committed."
    fi
    playthrough_log "published the acceptance report to" \
        "$(rel "${target}")"
    return 0
}

# ---------------------------------------------------------------------
# THE NOT-IGNORED GATE -- THE TRIPWIRE ON THE ONE FAILURE THAT REPORTS
# SUCCESS.
#
# `git add` SKIPS an ignored path and EXITS 0, so the failure this feature is
# most exposed to is silent by construction: delete the terminal
# `!/playthrough/**` negation and the engine's own `#<b64>.sav`,
# `#<b64>.log` and `config/debug.log` go back to being matched by `\#*`
# (.gitignore:131), unanchored `*.log` (.gitignore:31) and `debug.log`
# (.gitignore:79) -- and every count in this script still tallies while the
# save is not in the repository at all.
#
# `git check-ignore` is the honest question, and it has to be asked the hard
# way, because two of its forms answer something else:
#
#   1. WITHOUT --no-index it CONSULTS THE INDEX and calls any TRACKED path
#      not-ignored whatever the rules say.  It is therefore vacuous on a
#      re-run and wrong exactly when it matters, because on a fresh session
#      the file is not yet tracked and `git add` applies the patterns.
#   2. WITH -v it exits 0 whenever ANY pattern matched, INCLUDING the
#      negation.
#
# So the verdict is taken from `--no-index --quiet`, the one form whose exit
# status answers "is this ignored?", and the `-v` line is read only to NAME
# the offending rule in the refusal.  This runs BEFORE anything is staged, so
# a lost negation stops the checkpoint while the previous commit is still the
# last word.
# ---------------------------------------------------------------------

# first_capture -- one capture on disk, by name, or nothing.
first_capture() {
    local canonical="${PLAYTHROUGH_FRAMES_DIR}/${FIRST_CAPTURE_BASENAME}"
    local path first=""
    if [ -f "${canonical}" ]; then
        printf '%s' "${canonical}"
        return 0
    fi
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        first="${path}"
        break
    done < <("${FIND}" "${PLAYTHROUGH_FRAMES_DIR}" -mindepth 1 \
        -maxdepth 1 -type f -name 'frame_*.png' -print 2>/dev/null)
    if [ -z "${first}" ]; then
        return 1
    fi
    printf '%s' "${first}"
    return 0
}

# deciding_ignore_rule PATH -- the `source:line:pattern` git reports as the
# rule that decided, for the refusal message.
deciding_ignore_rule() {
    local verdict
    verdict="$("${GIT}" check-ignore --no-index -v -- "$1" \
        2>/dev/null || printf '')"
    verdict="${verdict%%$'\n'*}"
    printf '%s' "${verdict%%$'\t'*}"
}

assert_not_ignored() {
    local -a subjects=("${PLAYTHROUGH_MANIFEST}")
    subjects+=("${REQUIRED_PERSISTENCE_FILES[@]}")
    local capture=""
    if capture="$(first_capture)"; then
        subjects+=("${capture}")
    fi
    local path rule
    for path in "${subjects[@]}"; do
        [ -e "${path}" ] || continue
        # --quiet takes one pathname at a time, which is why this is a
        # loop and not one call.
        if "${GIT}" check-ignore --no-index --quiet -- "${path}"; then
            rule="$(deciding_ignore_rule "${path}")"
            die "${EX_SCOPE}" "$(rel "${path}") is IGNORED by" \
                "'${rule:-an exclude rule}'.  'git add' would skip it" \
                "and exit 0, so this checkpoint would report success" \
                "while leaving the evidence out of the repository --" \
                "the one failure in this feature that hides itself." \
                "The terminal '!/playthrough/**' negation must be the" \
                "LAST matching rule in .gitignore, and note that a" \
                "negation cannot rescue a file whose parent DIRECTORY" \
                "was excluded, so no directory-level ignore may cover" \
                "this tree.  Nothing was committed."
        fi
    done
    playthrough_log "the save, the record and the captures are all" \
        "outside .gitignore's reach: the terminal negation is still" \
        "the last matching rule"
    return 0
}

# ---------------------------------------------------------------------
# THE NO-CHEATING GATE.
# debug, debug_mode and debug_hour_timer ship with no `bindings` array
# (data/raw/keybindings.json:3398-3409, 3466-3471), so they are unreachable by
# any keystroke unless somebody deliberately binds them.
# ---------------------------------------------------------------------

readonly DEBUG_ACTION_PATTERN='"(debug|debug_mode|debug_hour_timer)"'

assert_no_debug_bindings() {
    local path="${PLAYTHROUGH_KEYBINDINGS_JSON}"
    if [ ! -f "${path}" ]; then
        playthrough_log "no $(rel "${path}"): the engine writes one" \
            "only when a binding is changed, so its absence is the" \
            "evidence that the shipped bindings -- in which every" \
            "debug action is unbound -- are the ones that were played"
        return 0
    fi
    if "${GREP}" -Eq -- "${DEBUG_ACTION_PATTERN}" "${path}"; then
        die "${EX_EVIDENCE}" "$(rel "${path}") mentions a debug" \
            "action.  Those ship unbound and the session is required to" \
            "have used none of them, so a keybinding file that names" \
            "one is either a bound cheat or an artifact nobody can" \
            "distinguish from one.  Nothing was committed."
    fi
    playthrough_log "$(rel "${path}") binds no debug action"
    return 0
}

# ---------------------------------------------------------------------
# THE LIFECYCLE GATE.  `final` is only meaningful AFTER a `creation`,
# and only if the session grew between them.
# ---------------------------------------------------------------------

CREATION_COMMIT=""

# creation_commit -- the newest commit on this branch carrying the creation
# trailer, or nothing.
creation_commit() {
    "${GIT}" log --max-count=1 --format=%H \
        --grep="^${TRAILER_KEY}: ${CHECKPOINT_CREATION}\$" HEAD -- \
        2>/dev/null || printf ''
}

# creation_commits -- EVERY creation checkpoint, newest first.
creation_commits() {
    "${GIT}" log --format=%H \
        --grep="^${TRAILER_KEY}: ${CHECKPOINT_CREATION}\$" HEAD -- \
        2>/dev/null || printf ''
}

# final_commits -- EVERY final checkpoint, newest first.
final_commits() {
    "${GIT}" log --format=%H \
        --grep="^${TRAILER_KEY}: ${CHECKPOINT_FINAL}\$" HEAD -- \
        2>/dev/null || printf ''
}

# ---------------------------------------------------------------------
# WHICH SURVIVOR A COMMIT IS ABOUT.
# The trailer says a commit is a checkpoint; it does not say WHOSE.
# ---------------------------------------------------------------------
readonly LASTWORLD_STDIN_READER='
import json
import sys

record = json.load(sys.stdin)
if not isinstance(record, dict):
    raise SystemExit(1)
world = record.get("world_name") or ""
character = record.get("character_name") or ""
if not world or not character:
    raise SystemExit(1)
sys.stdout.write("%s / %s" % (world, character))
'

# survivor_at COMMIT -- "<world> / <character>" as that commit's own tree
# records it, or nothing when the tree carries no readable record.
survivor_at() {
    local content=""
    content="$("${GIT}" show \
        "$1:playthrough/userdir/config/lastworld.json" 2>/dev/null ||
        printf '')"
    if [ -z "${content}" ]; then
        return 1
    fi
    printf '%s\n' "${content}" |
        "${PLAYTHROUGH_PYTHON}" -c "${LASTWORLD_STDIN_READER}" \
            2>/dev/null || return 1
}

# loaded_survivor -- the survivor THIS run is about, in the same spelling
# survivor_at returns, so the two are directly comparable.
loaded_survivor() {
    printf '%s / %s' "${LOADED_WORLD}" "${LOADED_CHARACTER}"
}

# creation_commit_for_survivor [SURVIVOR] -- the newest creation checkpoint
# whose own tree names that survivor, or nothing.
creation_commit_for_survivor() {
    local commit="" mine="${1-}"
    if [ -z "${mine}" ]; then
        mine="$(loaded_survivor)"
    fi
    while IFS= read -r commit; do
        [ -n "${commit}" ] || continue
        if [ "$(survivor_at "${commit}" || printf '')" = "${mine}" ]
        then
            printf '%s' "${commit}"
            return 0
        fi
    done < <(creation_commits)
    return 1
}

# manifest_rows_at COMMIT -- how many rows the record held in that commit's own
# tree, or nothing when the tree carries no readable record.
manifest_rows_at() {
    local rows=""
    rows="$("${GIT}" show "$1:playthrough/manifest.jsonl" \
        2>/dev/null | "${WC}" -l | "${TR}" -d ' ' || printf '')"
    case "${rows}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "${rows}"
    return 0
}

assert_creation_checkpoint() {
    local newest="" theirs=""
    if ! CREATION_COMMIT="$(creation_commit_for_survivor)"; then
        CREATION_COMMIT=""
    fi
    readonly CREATION_COMMIT
    if [ -z "${CREATION_COMMIT}" ]; then
        newest="$(creation_commit)"
        if [ -n "${newest}" ]; then
            theirs="$(survivor_at "${newest}" ||
                printf 'a survivor its own tree does not record')"
            die "${EX_LIFECYCLE}" "the newest" \
                "'${CHECKPOINT_CREATION}' checkpoint" \
                "${newest:0:10} records ${theirs}, and this session is" \
                "$(loaded_survivor).  Anchoring this" \
                "'${CHECKPOINT_FINAL}' to it would produce a history" \
                "whose two lifecycle commits describe somebody whose" \
                "files are not in the tree -- and a row count cannot" \
                "tell the two apart, because a record re-recorded from" \
                "scratch has 'grown' too.  Take" \
                "'${CHECKPOINT_CREATION}' for THIS survivor before" \
                "playing their session.  Nothing was committed."
        fi
        die "${EX_LIFECYCLE}" "there is no '${CHECKPOINT_CREATION}'" \
            "checkpoint in this branch's history, so a" \
            "'${CHECKPOINT_FINAL}' one would be the single bundled" \
            "commit the requirement exists to rule out.  Take" \
            "'${CHECKPOINT_CREATION}' immediately after the survivor" \
            "is created, play the session, then take this one." \
            "Nothing was committed."
    fi
    local before=""
    if ! before="$(manifest_rows_at "${CREATION_COMMIT}")"; then
        die "${EX_LIFECYCLE}" "the" \
            "'${CHECKPOINT_CREATION}' checkpoint" \
            "${CREATION_COMMIT} carries no readable manifest, so" \
            "there is nothing to measure this session's progress" \
            "against.  Nothing was committed."
    fi
    if [ "${ROW_COUNT}" -le "${before}" ]; then
        die "${EX_LIFECYCLE}" "the record held ${before} row(s) at" \
            "the '${CHECKPOINT_CREATION}' checkpoint and holds" \
            "${ROW_COUNT} now, so nothing was played between the two" \
            "commits.  The second checkpoint exists to show the" \
            "session happening between them; it is not taken over an" \
            "unchanged record.  Nothing was committed."
    fi
    playthrough_log "anchored to the '${CHECKPOINT_CREATION}'" \
        "checkpoint ${CREATION_COMMIT:0:10}, which records" \
        "$(survivor_at "${CREATION_COMMIT}" || printf 'no survivor')" \
        "-- the same survivor as this session -- and the record grew" \
        "from ${before} to ${ROW_COUNT} row(s) between the two"
    return 0
}


# ---------------------------------------------------------------------
# STAGING AND COMMITTING.
# ---------------------------------------------------------------------

# stageable PATH -- true when `git add` can be given this path: it exists on
# disk, or it is tracked and therefore has a REMOVAL to record.
stageable() {
    local path="$1"
    if [ -e "${path}" ]; then
        return 0
    fi
    if [ -n "$("${GIT}" ls-files -- "${path}" 2>/dev/null)" ]; then
        return 0
    fi
    return 1
}

# git_supports_pathspec_file -- whether `git add` will read its pathspecs from
# a NUL-delimited file (the option pair arrived in git 2.25).
PATHSPEC_FILE_SUPPORTED=""
git_supports_pathspec_file() {
    if [ -z "${PATHSPEC_FILE_SUPPORTED}" ]; then
        if "${GIT}" add --pathspec-from-file=/dev/null \
                --pathspec-file-nul --dry-run >/dev/null 2>&1; then
            PATHSPEC_FILE_SUPPORTED="yes"
        else
            PATHSPEC_FILE_SUPPORTED="no"
        fi
    fi
    [ "${PATHSPEC_FILE_SUPPORTED}" = "yes" ]
}

# open_pathspec_file -- a fresh, empty, NUL-delimited pathspec file in the
# runtime directory, reused for each staging call and removed on exit.
open_pathspec_file() {
    if [ ! -d "${PLAYTHROUGH_RUNTIME_DIR}" ]; then
        die "${EX_PREREQ}" "the runtime directory" \
            "'$(rel "${PLAYTHROUGH_RUNTIME_DIR}")' does not exist;" \
            "env.sh creates and verifies it at mode 0700, so" \
            "re-source playthrough/tooling/env.sh.  Nothing was" \
            "committed."
    fi
    if [ -z "${_CA_PATHSPEC_FILE}" ]; then
        if ! _CA_PATHSPEC_FILE="$(mktemp \
                "${PLAYTHROUGH_RUNTIME_DIR}/commit.pathspec.XXXXXX")"; \
                then
            die "${EX_PREREQ}" "cannot create a pathspec file under" \
                "'$(rel "${PLAYTHROUGH_RUNTIME_DIR}")'.  Nothing was" \
                "committed."
        fi
        chmod 600 "${_CA_PATHSPEC_FILE}"
    fi
    : >"${_CA_PATHSPEC_FILE}"
}

# add_from_pathspec_file LABEL -- hand git the streamed pathspec file.
add_from_pathspec_file() {
    local label="$1"
    local path
    local -a chunk=()
    if git_supports_pathspec_file; then
        if ! "${GIT}" add \
                --pathspec-from-file="${_CA_PATHSPEC_FILE}" \
                --pathspec-file-nul; then
            die "${EX_COMMIT}" "git could not stage the ${label}." \
                "This run committed nothing."
        fi
        return 0
    fi
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        chunk+=("${path}")
        if [ "${#chunk[@]}" -ge "${STAGE_BATCH_SIZE}" ]; then
            if ! "${GIT}" add -- "${chunk[@]}"; then
                die "${EX_COMMIT}" "git could not stage the ${label}." \
                    "This run committed nothing."
            fi
            chunk=()
        fi
    done <"${_CA_PATHSPEC_FILE}"
    if [ "${#chunk[@]}" -gt 0 ]; then
        if ! "${GIT}" add -- "${chunk[@]}"; then
            die "${EX_COMMIT}" "git could not stage the ${label}." \
                "This run committed nothing."
        fi
    fi
    return 0
}

# stage_stream LABEL -- stage one artifact class from a NUL-delimited stream of
# paths on stdin.
stage_stream() {
    local label="$1"
    local path present=0 unstageable=0
    local -a absent=()
    open_pathspec_file
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        if stageable "${path}"; then
            printf '%s\0' "${path}" >>"${_CA_PATHSPEC_FILE}"
            present=$((present + 1))
        else
            unstageable=$((unstageable + 1))
            if [ "${#absent[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
                absent+=("$(rel "${path}")")
            fi
        fi
    done
    # WHICH NAMED PATHS WERE NOT THERE, SAID OUT LOUD.
    if [ "${unstageable}" -gt 0 ]; then
        local more=""
        if [ "${unstageable}" -gt "${#absent[@]}" ]; then
            more=" (and $((unstageable - ${#absent[@]})) more)"
        fi
        playthrough_log "not staging ${unstageable} named path(s) in" \
            "the ${label} because they are neither on disk nor" \
            "tracked: ${absent[*]}${more}"
    fi
    if [ "${present}" -eq 0 ]; then
        playthrough_log "no ${label} to stage"
        return 0
    fi
    add_from_pathspec_file "${label}"
    playthrough_log "staged the ${label}: ${present} path(s)"
    return 0
}

# stage_batch LABEL PATH... -- one named artifact class.
stage_batch() {
    local label="$1"
    shift
    if [ "$#" -eq 0 ]; then
        playthrough_log "no ${label} to stage"
        return 0
    fi
    stage_stream "${label}" < <(printf '%s\0' "$@")
    return 0
}

# capture_pathspecs -- every capture the checkpoint must record, one
# NUL-terminated path at a time and never a list.
capture_pathspecs() {
    local path
    "${FIND}" "${PLAYTHROUGH_FRAMES_DIR}" -mindepth 1 -maxdepth 1 \
        -type f -name 'frame_*.png' -print0 2>/dev/null || true
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        if [ ! -e "${path}" ]; then
            printf '%s\0' "${path}"
        fi
    done < <("${GIT}" ls-files -z -- "${PLAYTHROUGH_FRAMES_DIR}" \
        2>/dev/null)
}

# stage_captures -- the one class whose size is the session's.
stage_captures() {
    stage_stream "captured frames" < <(capture_pathspecs)
    return 0
}

# ---------------------------------------------------------------------
# WHAT MAY BE COMMITTED, AS AN ALLOWLIST.
# ---------------------------------------------------------------------

# The authored tooling, by exact basename.  The test modules are a schema
# rather than twenty-one literals; everything else is named.
readonly -a AUTHORED_TOOLING=(
    "capture.sh"
    "commit_artifacts.sh"
    "embed_captions.sh"
    "env.sh"
    "launch_game.sh"
    "make_srt.py"
    "make_transitions.py"
    "manifest.py"
    "ocr_clock.py"
    "preflight_capture.sh"
    "render_movie.py"
    "requirements.lock"
    "requirements.txt"
    "run_pipeline.sh"
    "seed_options.py"
    "session.py"
    "sidebar_geometry.py"
    "supported_env.sh"
    "tileset_provenance.json"
    "tileset_provenance.py"
    "timeline.py"
    "verify_artifacts.sh"
)

# The engine's own subtrees under the userdir.  Read off the tree the
# engine actually produced rather than from documentation.
readonly -a ENGINE_SUBTREES=(
    "achievements"
    "cache"
    "config"
    "font"
    "gfx"
    "graveyard"
    "memorial"
    "mods"
    "save"
    "sound"
    "templates"
)

# classify_path REL -- set PATH_CLASS to the class REL belongs to.
PATH_CLASS=""
classify_path() {
    local rel="$1" name="" candidate=""
    PATH_CLASS=""
    case "${rel}" in
        README.md|REPORT.md|TECHNICAL_NOTES.md|dossier.md)
            PATH_CLASS="narrative" ; return 0 ;;
        transcript.md|transcript.srt|acceptance-report.txt)
            PATH_CLASS="narrative" ; return 0 ;;
        manifest.jsonl|timeline.json|amendments.jsonl)
            PATH_CLASS="record" ; return 0 ;;
        cata-play.mp4|cata-play-cc.mp4)
            PATH_CLASS="film" ; return 0 ;;
        frames/frame_[0-9][0-9][0-9][0-9][0-9].png)
            PATH_CLASS="capture" ; return 0 ;;
        build/transitions/trans_[0-9][0-9][0-9][0-9][0-9]_[0-9][0-9].png)
            PATH_CLASS="build" ; return 0 ;;
        build/concat.txt|build/movie.json|build/transitions.json)
            PATH_CLASS="build" ; return 0 ;;
        build/transcript.json|build/observations.jsonl)
            PATH_CLASS="build" ; return 0 ;;
        build/frame_digests.jsonl|build/frame_dates.jsonl)
            PATH_CLASS="build" ; return 0 ;;
        build/acknowledgments.jsonl|build/evidence_anchor.jsonl)
            PATH_CLASS="build" ; return 0 ;;
        tooling/environment/Dockerfile)
            PATH_CLASS="tooling" ; return 0 ;;
        tooling/test_*.py)
            PATH_CLASS="tooling" ; return 0 ;;
    esac
    case "${rel}" in
        tooling/*)
            name="${rel#tooling/}"
            # One level only: an authored tooling file is a file in that
            # directory, and a nested path that is not the Dockerfile
            # above has no reason to be there.
            case "${name}" in
                */*) return 1 ;;
            esac
            for candidate in "${AUTHORED_TOOLING[@]}"; do
                if [ "${name}" = "${candidate}" ]; then
                    PATH_CLASS="tooling"
                    return 0
                fi
            done
            return 1
            ;;
        userdir/*)
            name="${rel#userdir/}"
            for candidate in "${ENGINE_SUBTREES[@]}"; do
                case "${name}" in
                    "${candidate}"/*)
                        PATH_CLASS="userdir"
                        return 0
                        ;;
                esac
            done
            return 1
            ;;
    esac
    return 1
}

# playthrough_files -- every path a checkpoint has to account for.
playthrough_files() {
    local path
    "${FIND}" "${PLAYTHROUGH_DIR}" -type f -print0 2>/dev/null || true
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        case "${path}" in
            /*) ;;
            *) path="${PLAYTHROUGH_REPO_ROOT}/${path}" ;;
        esac
        if [ ! -e "${path}" ]; then
            printf '%s\0' "${path}"
        fi
    done < <("${GIT}" ls-files -z -- "${PLAYTHROUGH_DIR}" 2>/dev/null)
}

# ---------------------------------------------------------------------
# WHAT A PATH IS, AS OPPOSED TO WHERE IT IS.
# The classification above answers "is this evidence" by POSITION, and for the
# engine's own tree that is the only answer available: the engine writes
# `#<b64>.sav`, `.seen.0.-1`, `.mm1` directories and
# `<name>-<serial>.json.-4651329699267.fb` caches, so a per-filename allowlist
# over somebody else's output would refuse a correct checkpoint the first time
# a new engine version wrote a new shape.
# ---------------------------------------------------------------------

# assert_staging_provenance -- the tree is what it appears to be.
assert_staging_provenance() {
    local kind uid links device path
    local expected_uid expected_device
    local wrong=0
    local -a named=()
    expected_uid="$(id -u)"
    # THE SAME TOOL THAT READS THE TREE READS THE REFERENCE, so the two
    # device numbers are produced by one implementation and cannot
    # disagree over their spelling -- and `find` is already a required
    # tool, where `stat` would be a new dependency for one field.
    expected_device="$("${FIND}" "${PLAYTHROUGH_REPO_ROOT}" -maxdepth 0 \
        -printf '%D\n' 2>/dev/null || true)"
    if [ -z "${expected_device}" ]; then
        die "${EX_REPO}" "the checkout's own filesystem could not be" \
            "identified, so a path grafted in from another one cannot" \
            "be told apart from an ordinary file.  Nothing was" \
            "committed."
    fi
    while IFS=' ' read -r kind uid links device path; do
        [ -n "${path}" ] || continue
        local why=""
        case "${kind}" in
            d) ;;
            f)
                if [ "${links}" != "1" ]; then
                    # CWE-59.  A second link means these bytes are also
                    # reachable under another name, and the other name is
                    # the one whose content would be published.
                    why="has ${links} hard links, so its content is \
also reachable outside this tree"
                fi
                ;;
            l) why="is a symbolic link, which the classification sweep \
cannot see and git would commit as a pointer" ;;
            *) why="is not a regular file or a directory (find reports \
type '${kind}')" ;;
        esac
        if [ -z "${why}" ] && [ "${uid}" != "${expected_uid}" ]; then
            why="is owned by uid ${uid} and this run is uid \
${expected_uid}, so it was placed here by somebody else"
        fi
        if [ -z "${why}" ] && [ "${device}" != "${expected_device}" ]; then
            why="is on device ${device} and the checkout is on \
${expected_device}, so another filesystem is mounted inside this tree"
        fi
        [ -n "${why}" ] || continue
        wrong=$((wrong + 1))
        if [ "${#named[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
            named+=("$(rel "${path}") ${why}")
        fi
    done < <("${FIND}" "${PLAYTHROUGH_DIR}" \
        -printf '%y %U %n %D %p\n' 2>/dev/null || true)
    if [ "${wrong}" -gt 0 ]; then
        local more=""
        if [ "${wrong}" -gt "${#named[@]}" ]; then
            more=" (and $((wrong - ${#named[@]})) more)"
        fi
        die "${EX_SCOPE}" "${wrong} path(s) under" \
            "$(rel "${PLAYTHROUGH_DIR}") are not what a captured" \
            "session's evidence looks like: ${named[*]}${more}." \
            "The engine names its own files and this script does not" \
            "second-guess those names -- but WHAT a path is has to" \
            "hold regardless of what it is called, because" \
            ".gitignore's terminal '!/playthrough/**' negation means" \
            "anything here is committable and a commit cannot be" \
            "un-published.  Nothing was committed."
    fi
    playthrough_log "every path under $(rel "${PLAYTHROUGH_DIR}") is a" \
        "directory or a single-linked regular file, owned by uid" \
        "${expected_uid}, on the checkout's own filesystem"
    return 0
}

# The secret scanner, as data so the interpreter is handed a fixed program. It
# reads NUL-separated paths on stdin and prints one TAB-separated finding per
# line: relative path, rule name, and the sha256 of the matched text. The text
# itself never leaves the program.
readonly SECRET_SCANNER='
import hashlib
import os
import re
import sys

PLACEHOLDER = re.compile(
    r"\A(?:<[^>]*>|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\**|x+|X+"
    r"|REDACTED|redacted|TOKEN|token|PASSWORD|password|secret|SECRET)\Z")

# EVERY REPETITION IS BOUNDED, and that is a performance property with teeth
# rather than tidiness.
RULES = (
    ("url-credential",
     r"[a-zA-Z][a-zA-Z0-9+.-]{0,31}://[^/\s:@]{1,256}:"
     r"([^/\s@]{1,256})@"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{16,255}"),
    ("github-pat", r"github_pat_[A-Za-z0-9_]{20,255}"),
    ("aws-access-key", r"AKIA[0-9A-Z]{16}"),
    ("google-api-key", r"AIza[0-9A-Za-z_-]{35}"),
    ("slack-token", r"xox[baprs]-[A-Za-z0-9-]{10,255}"),
    ("private-key", r"-----BEGIN [A-Z0-9 ]{0,64}PRIVATE KEY"),
    # A CHARACTER CLASS FOR ONE LETTER, and it is load-bearing rather than
    # decorative: written as a plain literal, this pattern MATCHES ITSELF, and
    # the scan then reports the scanner as carrying a key.
    ("putty-key", r"P[u]TTY-User-Key-File-"),
    ("x-magic-cookie", r"MIT-MAGIC-COOKIE-1\W{0,8}[0-9a-f]{32}"),
    ("http-basic",
     r"[Aa]uthorization:[ \t]{0,8}Basic[ \t]{1,8}"
     r"[A-Za-z0-9+/=]{16,512}"),
    ("http-bearer",
     r"[Aa]uthorization:[ \t]{0,8}Bearer[ \t]{1,8}"
     r"[A-Za-z0-9._~+/-]{20,512}"),
)
COMPILED = tuple((name, re.compile(pattern, re.MULTILINE))
                 for name, pattern in RULES)

# The read size, and the overlap carried between reads.
CHUNK = 1048576
OVERLAP = 8192

# What counts as a match inside NUL-bearing (binary) content: printable
# ASCII throughout, and long enough that random bytes do not produce it.
PRINTABLE = frozenset(chr(code) for code in range(0x20, 0x7F))
MIN_BINARY = 12
root = sys.argv[1]


def reportable(rule, found, binary):
    """Whether one match is worth reporting, given where it was found.

    THE MATCH OBJECT, NOT ITS TEXT.  An earlier draft re-searched the
    chunk here to reach the password group, which was both quadratic over
    a chunk with many matches and WRONG -- it inspected the first match
    in the chunk rather than this one.
    """
    if rule == "url-credential" and PLACEHOLDER.match(found.group(1)):
        return False
    if not binary:
        return True
    text = found.group(0)
    if len(text) < MIN_BINARY:
        return False
    return all(char in PRINTABLE for char in text)


for path in sys.stdin.buffer.read().split(b"\0"):
    if not path:
        continue
    name = os.fsdecode(path)
    relative = os.path.relpath(name, root)
    seen = set()
    carry = ""
    try:
        with open(name, "rb") as handle:
            while True:
                block = handle.read(CHUNK)
                if not block:
                    break
                # CLASSIFIED PER CHUNK, not per file.
                binary = b"\0" in block
                text = carry + block.decode("utf-8", "replace")
                carry = text[-OVERLAP:] if len(text) > OVERLAP else text
                for rule, expression in COMPILED:
                    for found in expression.finditer(text):
                        if not reportable(rule, found, binary):
                            continue
                        matched = found.group(0)
                        # THE VALUE NEVER LEAVES THIS PROGRAM.
                        digest = hashlib.sha256(
                            matched.encode("utf-8")).hexdigest()
                        # DEDUPLICATED PER FILE at exactly the baseline
                        # granularity, so the 8 KiB overlap cannot report
                        # one occurrence as two.
                        if (rule, digest) in seen:
                            continue
                        seen.add((rule, digest))
                        print("%s\t%s\t%s" % (relative, rule, digest))
    except OSError as err:
        sys.stderr.write("could not read %s: %s\n" % (name, err))
        raise SystemExit(2)
'

# The findings that are reviewed and accounted for, as <path>|<rule>|<sha256 of
# the matched text>. An entry pins all three, so a NEW occurrence -- even in
# the same file, even under the same rule -- is refused rather than covered by
# its neighbour.
readonly -a SECRET_BASELINE=(
    "playthrough/tooling/test_commit_artifacts.py|url-credential|\
04d64837b370e0f16f95903626e4d1a5f69dcb6c53689fd90a695f9ed5c9175e"
)

# assert_no_secret_material -- the content question, before staging.
assert_no_secret_material() {
    local relative rule digest entry known
    local unaccounted=0 accounted=0
    local -a named=()
    local scan="" status=0
    set +e
    scan="$("${FIND}" "${PLAYTHROUGH_DIR}" -type f -print0 2>/dev/null |
        "${PLAYTHROUGH_PYTHON}" -B -c "${SECRET_SCANNER}" \
            "${PLAYTHROUGH_REPO_ROOT}" 2>&1)"
    status=$?
    set -e
    if [ "${status}" -ne 0 ]; then
        die "${EX_SCOPE}" "the secret scan over" \
            "$(rel "${PLAYTHROUGH_DIR}") could not be completed" \
            "(exit ${status}): ${scan:-<no diagnosis>}.  A checkpoint" \
            "is not taken over a tree nobody could read, because the" \
            "whole point of the scan is that a published credential" \
            "cannot be un-published.  Nothing was committed."
    fi
    while IFS=$'\t' read -r relative rule digest; do
        [ -n "${relative}" ] || continue
        known="no"
        for entry in "${SECRET_BASELINE[@]}"; do
            if [ "${relative}|${rule}|${digest}" = "${entry}" ]; then
                known="yes"
                break
            fi
        done
        if [ "${known}" = "yes" ]; then
            accounted=$((accounted + 1))
            continue
        fi
        unaccounted=$((unaccounted + 1))
        if [ "${#named[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
            # THE RULE AND THE PATH, NOT THE VALUE.
            named+=("$(printf '%s (%s)' "${relative}" "${rule}")")
        fi
    done <<< "${scan}"
    if [ "${unaccounted}" -gt 0 ]; then
        local more=""
        if [ "${unaccounted}" -gt "${#named[@]}" ]; then
            more=" (and $((unaccounted - ${#named[@]})) more)"
        fi
        die "${EX_SCOPE}" "${unaccounted} path(s) under" \
            "$(rel "${PLAYTHROUGH_DIR}") carry secret material:" \
            "${named[*]}${more}.  The values are deliberately NOT" \
            "printed and were never read out of the scanner." \
            "Remove the credential, rotate whatever it" \
            "authenticates, and take the checkpoint again -- a secret" \
            "that reaches a commit cannot be withdrawn from the" \
            "history by deleting the file afterwards.  If the match is" \
            "genuinely not a credential, add it to SECRET_BASELINE in" \
            "this script with the reason.  Nothing was committed."
    fi
    playthrough_log "the secret scan found nothing unaccounted for" \
        "under $(rel "${PLAYTHROUGH_DIR}") -- every byte of every file," \
        "text and binary alike (${accounted} reviewed finding(s) in the" \
        "baseline)"
    return 0
}

# assert_staging_is_sound -- both questions, in the order whose failure is
# cheaper to diagnose.
assert_staging_is_sound() {
    assert_staging_provenance
    assert_no_secret_material
    return 0
}

# assert_every_path_is_classified -- the refusal that replaces the denylist's
# blind spot.
assert_every_path_is_classified() {
    local path rel unknown=0
    local -a named=()
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        rel="${path#"${PLAYTHROUGH_DIR}/"}"
        if classify_path "${rel}"; then
            continue
        fi
        unknown=$((unknown + 1))
        if [ "${#named[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
            named+=("${rel}")
        fi
    done < <(playthrough_files)
    if [ "${unknown}" -gt 0 ]; then
        local more=""
        if [ "${unknown}" -gt "${#named[@]}" ]; then
            more=" (and $((unknown - ${#named[@]})) more)"
        fi
        die "${EX_SCOPE}" "${unknown} path(s) under" \
            "$(rel "${PLAYTHROUGH_DIR}") belong to no artifact class:" \
            "${named[*]}${more}.  A checkpoint stages what it can name," \
            "and .gitignore's terminal '!/playthrough/**' negation means" \
            "anything left here IS committable -- so an unrecognised" \
            "path is refused rather than admitted by default.  Either it" \
            "is evidence, in which case add it to classify_path in" \
            "this script -- beside stage_artifacts -- so every later run" \
            "stages it deliberately, or" \
            "it is not, in which case it does not belong in this tree." \
            "Nothing was committed."
    fi
    return 0
}

# assert_no_ignored_paths -- nothing in this tree is excluded, asked before a
# single `git add`.
assert_no_ignored_paths() {
    local path count=0
    local -a named=()
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        count=$((count + 1))
        if [ "${#named[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
            named+=("$(rel "${path}")")
        fi
    done < <(playthrough_files |
        "${GIT}" check-ignore --no-index -z --stdin 2>/dev/null || true)
    if [ "${count}" -gt 0 ]; then
        die "${EX_SCOPE}" "${count} path(s) under" \
            "$(rel "${PLAYTHROUGH_DIR}") are IGNORED by git and would" \
            "be committed around in silence:" \
            "$(name_sample "${count}" "${named[@]}")." \
            "Nothing in" \
            "this tree may be excluded -- the terminal" \
            "'!/playthrough/**' negation exists to make sure of it, and" \
            "a rule placed AFTER it re-excludes whatever it matches." \
            "Fix .gitignore so the negation is the last matching rule." \
            "Nothing was committed."
    fi
    return 0
}

# stage_class CLASS LABEL -- every path of one class, and nothing else.
stage_class() {
    local class="$1" label="$2"
    stage_stream "${label}" < <(class_pathspecs "${class}")
    return 0
}

class_pathspecs() {
    local class="$1" path rel
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        rel="${path#"${PLAYTHROUGH_DIR}/"}"
        if classify_path "${rel}" && [ "${PATH_CLASS}" = "${class}" ]; then
            printf '%s\0' "${path}"
        fi
    done < <(playthrough_files)
}

# stage_artifacts -- every artifact class, named, one batch each.
stage_artifacts() {
    # 0. Three refusals before a single `git add`, in order of how
    #    SPECIFIC their diagnosis is.
    assert_index_hygiene
    assert_no_ignored_paths
    # Then WHAT each path is and WHAT IT CONTAINS, before the classification
    # asks where it lives.
    assert_staging_is_sound
    assert_every_path_is_classified
    # 1. The authored tooling, including requirements.txt -- the
    #    dependency declaration the requirement wants kept out of the
    #    game's source tree.  BY NAME, not by directory: `git add --
    stage_class "tooling" "pipeline tooling"
    # 2. The narrative record: the dossier written before play, the
    #    transcript, the engineering notes, the feature readme, and the
    #    three-section report the feature is required to deliver.
    #    The report is named here for the same reason README.md is --
    stage_batch "narrative and documentation" \
        "${PLAYTHROUGH_DOSSIER}" \
        "${PLAYTHROUGH_DIR}/README.md" \
        "${PLAYTHROUGH_TECH_NOTES}" \
        "${PLAYTHROUGH_REPORT}" \
        "${PLAYTHROUGH_ACCEPTANCE_REPORT}" \
        "${PLAYTHROUGH_TRANSCRIPT_MD}" \
        "${PLAYTHROUGH_TRANSCRIPT_SRT}"
    # 3. The engine's own tree -- save, config, achievements, memorial,
    #    graveyard, templates, cache.
    stage_class "userdir" "engine save and configuration"
    # 4. The captures.
    stage_captures
    # 5. The record and its ledgers.  Named here AND classified above:
    #    the names are what gets staged, the classification is what makes
    #    "did we miss one" answerable.
    stage_batch "record and timeline" \
        "${PLAYTHROUGH_MANIFEST}" \
        "${PLAYTHROUGH_TIMELINE}" \
        "${PLAYTHROUGH_AMENDMENTS}"
    # 6. The render intermediates, which include the observation
    #    sidecar, the capture attestations and the concat list.
    stage_class "build" "build intermediates"
    # 7. The films.
    stage_batch "assembled film" \
        "${PLAYTHROUGH_MOVIE}" \
        "${PLAYTHROUGH_MOVIE_CC}"
    # Completeness last. Hygiene, the ignore sweep and the classification all
    # ran before anything was staged, so what is left to establish is only that
    # every classified path actually reached the index.
    assert_tree_fully_staged
    return 0
}

# assert_tree_fully_staged -- the completeness half of explicit staging.
assert_tree_fully_staged() {
    local -a pending=() ignored=()
    local entry xy path origin=""
    local pending_count=0 ignored_count=0
    while IFS= read -r -d '' entry; do
        xy="${entry:0:2}"
        path="${entry:3}"
        case "${xy}" in
            R*|C*)
                # A rename or copy emits its origin as a second
                # NUL-terminated field, which must be consumed or it
                # would be read as the next entry's status.
                IFS= read -r -d '' origin || origin=""
                ;;
        esac
        if [ "${xy}" = "!!" ]; then
            ignored_count=$((ignored_count + 1))
            if [ "${#ignored[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
                ignored+=("${path}")
            fi
        elif [ "${xy}" = "??" ] || [ "${xy:1:1}" != " " ]; then
            pending_count=$((pending_count + 1))
            if [ "${#pending[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
                pending+=("${path}")
            fi
        fi
    done < <("${GIT}" status --porcelain -z --untracked-files=all \
        --ignored=matching -- "${PATHSPECS[@]}")
    if [ "${ignored_count}" -gt 0 ]; then
        die "${EX_SCOPE}" "${ignored_count} path(s) inside" \
            "$(rel "${PLAYTHROUGH_DIR}") are IGNORED by git and would" \
            "be committed around in silence:" \
            "$(name_sample "${ignored_count}" "${ignored[@]}")." \
            "Nothing in" \
            "this tree may be excluded -- the terminal" \
            "'!/playthrough/**' negation exists to make sure of it, and" \
            "a rule placed AFTER it re-excludes whatever it matches." \
            "Fix .gitignore so the negation is the last matching rule." \
            "Nothing was committed."
    fi
    if [ "${pending_count}" -gt 0 ]; then
        die "${EX_COMMIT}" "${pending_count} path(s) under" \
            "$(rel "${PLAYTHROUGH_DIR}") are still not staged after" \
            "every artifact class was staged:" \
            "$(name_sample "${pending_count}" "${pending[@]}")." \
            "Everything in this tree is evidence and everything is" \
            "committed, so this is not skipped quietly: either the" \
            "path belongs to a new artifact class that must be added" \
            "to stage_artifacts, or it does not belong in the tree at" \
            "all.  Nothing was committed."
    fi
    return 0
}

# assert_index_hygiene -- the last look, at the INDEX rather than at the
# filesystem.
assert_index_hygiene() {
    local -a bytecode=() outside=()
    local path
    local bytecode_count=0 outside_count=0
    while IFS= read -r -d '' path; do
        if ! in_scope "${path}"; then
            outside_count=$((outside_count + 1))
            if [ "${#outside[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
                outside+=("${path}")
            fi
            continue
        fi
        case "${path}" in
            *__pycache__*|*.pyc|*.pyo)
                bytecode_count=$((bytecode_count + 1))
                if [ "${#bytecode[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
                    bytecode+=("${path}")
                fi
                ;;
        esac
    done < <("${GIT}" diff --cached --name-only -z HEAD --)
    if [ "${bytecode_count}" -gt 0 ]; then
        die "${EX_SCOPE}" "the index carries interpreter bytecode:" \
            "$(name_sample "${bytecode_count}" "${bytecode[@]}")." \
            "Inside this one tree .gitignore's" \
            "terminal '!/playthrough/**' negation RE-INCLUDES" \
            "__pycache__ and *.pyc, so bytecode is committable here" \
            "and nothing but this check stops it being archived as" \
            "though it were evidence.  Remove it (test modules run" \
            "with 'python -B', and env.sh exports" \
            "PYTHONDONTWRITEBYTECODE=1) and run this again.  Nothing" \
            "was committed."
    fi
    if [ "${outside_count}" -gt 0 ]; then
        die "${EX_SCOPE}" "the index carries ${outside_count} path(s)" \
            "outside $(rel "${PLAYTHROUGH_DIR}"):" \
            "$(name_sample "${outside_count}" "${outside[@]}").  A" \
            "commit publishes the whole index, so a checkpoint about" \
            "the playthrough would carry them.  Unstage them and" \
            "commit them separately.  Nothing was committed."
    fi
    return 0
}

# staged_paths -- the repository-relative paths currently staged against HEAD,
# one per line. Consumed by STREAMING it (`while read`), never by capturing it:
# the list is one line per capture on a checkpoint that stages the session.
staged_paths() {
    "${GIT}" diff --cached --name-only HEAD -- "${PATHSPECS[@]}" \
        2>/dev/null || printf ''
}

# anything_staged -- whether the index differs from HEAD under this feature's
# pathspec. Git's own boolean: --quiet exits 1 when there IS a difference and 0
# when there is none, and prints nothing either way.
anything_staged() {
    if "${GIT}" diff --cached --quiet HEAD -- "${PATHSPECS[@]}" \
            2>/dev/null; then
        return 1
    fi
    return 0
}

# staged_classes -- one line per artifact class present in the index, for the
# commit body.
staged_classes() {
    local path
    local -a classes=()
    local save=0 frames=0 record=0 media=0 text=0 tooling=0 config=0
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        case "${path}" in
            playthrough/userdir/save/*|\
playthrough/userdir/graveyard/*|playthrough/userdir/memorial/*)
                save=1
                ;;
            playthrough/userdir/config/*) config=1 ;;
            playthrough/userdir/*) config=1 ;;
            playthrough/frames/*) frames=1 ;;
            playthrough/manifest.jsonl|playthrough/timeline.json|\
playthrough/build/*) record=1 ;;
            playthrough/*.mp4) media=1 ;;
            playthrough/transcript.*|playthrough/*.md) text=1 ;;
            playthrough/tooling/*) tooling=1 ;;
        esac
    done < <(staged_paths)
    # A false test here is deliberate flow control, not an error: in an
    # AND-OR list the leading command is exempt from `set -e`, which is
    # why eight of these can stand in a row without a guard.
    [ "${save}" -eq 1 ] && classes+=("save data")
    [ "${config}" -eq 1 ] && classes+=("game configuration and engine \
state")
    [ "${frames}" -eq 1 ] && classes+=("captured frames")
    [ "${record}" -eq 1 ] && classes+=("manifest and timeline")
    [ "${media}" -eq 1 ] && classes+=("assembled film")
    [ "${text}" -eq 1 ] && classes+=("transcript and notes")
    [ "${tooling}" -eq 1 ] && classes+=("pipeline tooling")
    if [ "${#classes[@]}" -eq 0 ]; then
        return 0
    fi
    printf '%s\n' "${classes[@]}"
    return 0
}

# ---------------------------------------------------------------------
# SEALING THE EVIDENCE, AND PUBLISHING THE SEAL'S HEAD
# An attestation stored beside the evidence it attests to is mutable with
# it: the digest ledger vouches for the frames, so whoever rewrites a frame
# rewrites its digest row in the same breath.  The seal therefore lives in
# a commit trailer, which is outside every file it covers.
readonly ANCHOR_TRAILER_KEY="Playthrough-Evidence-Anchor"

# The sealer, kept as data so the interpreter is handed a fixed program rather
# than an assembled one.
readonly ANCHOR_SEALER='
import sys

sys.path.insert(0, sys.argv[1])
import manifest

written, absent = manifest.seal_artifacts(sys.argv[2])
rows = manifest.read_anchor_rows()
problems = manifest.anchor_chain_problems(rows)
if problems:
    sys.stderr.write("the chain is unsound after sealing: %s\n"
                     % problems[0])
    raise SystemExit(1)
head = manifest.anchor_head(rows)
if not head:
    sys.stderr.write("sealing produced no chain head\n")
    raise SystemExit(1)
print("HEAD=%s" % head)
print("ADDED=%d" % len(written))
print("TOTAL=%d" % len(rows))
print("ABSENT=%s" % ",".join(absent))
'

ANCHOR_HEAD=""

# seal_evidence NAME
#   Seal every artifact that exists, stage the ledger, and leave the
#   chain's head in ANCHOR_HEAD for the trailer.
seal_evidence() {
    local name="$1"
    local reading="" line="" added="" total="" unsealed=""
    ANCHOR_HEAD=""
    if ! reading="$("${PLAYTHROUGH_PYTHON}" -B -c "${ANCHOR_SEALER}" \
            "${PLAYTHROUGH_TOOLING_DIR}" "${name}" 2>&1)"; then
        die "${EX_COMMIT}" "the evidence could not be sealed for the" \
            "'${name}' checkpoint, so nothing was committed:" \
            "${reading:-<no diagnosis>}"
    fi
    while IFS= read -r line; do
        case "${line}" in
            HEAD=*) ANCHOR_HEAD="${line#HEAD=}" ;;
            ADDED=*) added="${line#ADDED=}" ;;
            TOTAL=*) total="${line#TOTAL=}" ;;
            ABSENT=*) unsealed="${line#ABSENT=}" ;;
        esac
    done <<< "${reading}"
    if [ -z "${ANCHOR_HEAD}" ]; then
        die "${EX_COMMIT}" "the evidence was sealed for the '${name}'" \
            "checkpoint but the chain head could not be read back, so" \
            "there is nothing to publish and nothing was committed."
    fi
    # The ledger belongs in the commit that publishes its head.
    if ! git_mutate add -- "$(rel "${PLAYTHROUGH_EVIDENCE_ANCHOR}")"
    then
        die "${EX_COMMIT}" "git refused to stage the evidence anchor" \
            "for the '${name}' checkpoint.  Nothing was committed."
    fi
    if [ -n "${unsealed}" ]; then
        playthrough_log "sealed the evidence for '${name}':" \
            "${added} row(s) added, ${total} in the chain, head" \
            "${ANCHOR_HEAD:0:16}.  Not yet on disk and so not sealed:" \
            "${unsealed//,/, }"
    else
        playthrough_log "sealed the evidence for '${name}':" \
            "${added} row(s) added, ${total} in the chain, head" \
            "${ANCHOR_HEAD:0:16}; every sealed artifact was present"
    fi
    return 0
}

# commit_checkpoint NAME SUBJECT
#   Take the commit, or report that there was nothing to take.
COMMITTED="no"
COMMIT_HASH=""

commit_checkpoint() {
    local name="$1" subject="$2"
    local -a body=()
    local class
    if ! anything_staged; then
        playthrough_warn "nothing to commit for the '${name}'" \
            "checkpoint: every path this step stages is already" \
            "recorded at HEAD.  No empty commit was manufactured."
        COMMITTED="no"
        COMMIT_HASH=""
        return 0
    fi
    # SEALED BEFORE THE MESSAGE IS BUILT, because the message publishes
    # the seal's head, and STAGED before staged_classes is read, so the
    # body describes an index that already includes the ledger.
    seal_evidence "${name}"
    while IFS= read -r class; do
        [ -n "${class}" ] || continue
        body+=("- ${class}")
    done < <(staged_classes)
    local -a message=("-m" "${subject}")
    if [ "${#body[@]}" -gt 0 ]; then
        # One -m per paragraph; git joins them with a blank line, so the
        # body reads as a list without this file assembling newlines.
        message+=("-m" "$(printf '%s\n' "${body[@]}")")
    fi
    message+=("-m" "${WORLD_NAME} / ${CHARACTER_NAME}, \
${ROW_COUNT} keystroke(s) captured.")
    # BOTH TRAILERS IN ONE PARAGRAPH so git reads them as a trailer block: a
    # blank line between them would make the second one body text, and `git log
    # --grep` would still find it while `git interpret-trailers` would not.
    message+=("-m" "${TRAILER_KEY}: ${name}
${ANCHOR_TRAILER_KEY}: ${ANCHOR_HEAD}")
    # THE INDEX AS IT STANDS, READ BEFORE THE COMMIT.
    local staged_before
    staged_before="$(index_blobs)"
    if ! git_mutate commit --quiet "${message[@]}"; then
        die "${EX_COMMIT}" "git refused the '${name}' checkpoint" \
            "commit.  The index is left staged so the failure can be" \
            "inspected; nothing was rewritten."
    fi
    if ! COMMIT_HASH="$("${GIT}" rev-parse HEAD 2>/dev/null)"; then
        die "${EX_COMMIT}" "the '${name}' checkpoint commit was made" \
            "but its hash could not be read back, so it cannot be" \
            "verified."
    fi
    assert_commit_tree_matches_index "${name}" "${staged_before}"
    COMMITTED="yes"
    playthrough_log "committed the '${name}' checkpoint as" \
        "${COMMIT_HASH}"
    return 0
}

# ---------------------------------------------------------------------
# BINDING THE STAGED BLOBS TO THE COMMIT THAT PUBLISHED THEM.
# Every gate in this file runs against the index, and the commit is a separate
# operation afterwards.
# ---------------------------------------------------------------------

# index_blobs -- "<mode> <object> <path>" for every index entry under
# this checkpoint's pathspecs, in a stable order.
index_blobs() {
    # SC2016: the single quotes are deliberate and required.  This is an
    # awk PROGRAM, and its '$' field references belong to awk; letting
    # the shell expand them would rewrite the program before awk saw it.
    # shellcheck disable=SC2016
    "${GIT}" ls-files --stage -- "${PATHSPECS[@]}" 2>/dev/null |
        "${AWK}" '{ mode = $1; object = $2; $1 = ""; $2 = ""; $3 = "";
                    sub(/^[ \t]+/, "");
                    printf "%s %s %s\n", mode, object, $0 }' |
        "${SORT}"
}

# tree_blobs COMMIT -- the same shape, read out of a published tree.
tree_blobs() {
    # SC2016: the single quotes are deliberate and required.  This is an
    # awk PROGRAM, and its '$' field references belong to awk; letting
    # the shell expand them would rewrite the program before awk saw it.
    # shellcheck disable=SC2016
    "${GIT}" ls-tree -r --full-tree "$1" -- "${PATHSPECS[@]}" \
        2>/dev/null |
        "${AWK}" '{ mode = $1; object = $3; $1 = ""; $2 = ""; $3 = "";
                    sub(/^[ \t]+/, "");
                    printf "%s %s %s\n", mode, object, $0 }' |
        "${SORT}"
}

assert_commit_tree_matches_index() {
    local name="$1" before="$2"
    local after
    after="$(tree_blobs "${COMMIT_HASH}")"
    if [ "${before}" = "${after}" ]; then
        local count
        count="$(printf '%s\n' "${before}" | "${GREP}" -c . || true)"
        playthrough_log "the '${name}' checkpoint published exactly" \
            "the ${count:-0} object(s) that were staged when it was" \
            "validated -- compared blob by blob against" \
            "${COMMIT_HASH}, not assumed from the commit's exit status"
        return 0
    fi
    # The FIRST disagreement is named, because a reader needs a path to
    # start from and the whole listing can be hundreds of lines.
    local differing=""
    # SC2016: the single quotes are deliberate and required.  This is an
    # awk PROGRAM, and its '$' field references belong to awk; letting
    # the shell expand them would rewrite the program before awk saw it.
    # shellcheck disable=SC2016
    differing="$(printf '%s\n' "${before}" "${after}" | "${SORT}" |
        "${AWK}" '{ seen[$0]++ } END { for (row in seen)
            if (seen[row] == 1) { print row; exit } }' || true)"
    die "${EX_COMMIT}" "the '${name}' checkpoint commit" \
        "${COMMIT_HASH} does not publish the objects that were" \
        "staged when its gates ran.  The first disagreement is" \
        "'${differing:-<none reported>}'.  Something changed the" \
        "index or the working tree between the validation and the" \
        "commit, so what was checked and what was published are not" \
        "the same bytes.  The commit EXISTS -- it is not rewritten" \
        "here, because rewriting history to hide a race is worse than" \
        "reporting it -- and it must be inspected before it is" \
        "trusted as evidence."
}

# ---------------------------------------------------------------------
# VERIFYING WHAT WAS PUBLISHED.  Every claim this file makes about the
# commit it just took is read back out of git rather than assumed from
# the fact that the commit command succeeded.
# ---------------------------------------------------------------------

# verify_attribution_and_trailer NAME [ANCHOR_HEAD] -- the properties EVERY
# checkpoint has, whatever else it carries. Shared, so the dossier commit is
# held to the same attribution rule as the other two rather than to a looser
# one written beside it.
verify_attribution_and_trailer() {
    local name="$1" anchor="${2:-}"
    local author committer message
    author="$("${GIT}" log -1 --format='%an <%ae>' HEAD)"
    committer="$("${GIT}" log -1 --format='%cn <%ce>' HEAD)"
    if [ "${author}" != "${IDENT_AUTHOR}" ] ||
       [ "${committer}" != "${IDENT_COMMITTER}" ]; then
        die "${EX_COMMIT}" "the commit was recorded as authored by" \
            "'${author}' and committed by '${committer}', and the" \
            "identity asserted before it was made was" \
            "'${IDENT_AUTHOR}'.  The history is part of this" \
            "evidence, so an attribution nobody predicted is a" \
            "failure and not a detail."
    fi
    message="$("${GIT}" log -1 --format=%B HEAD)"
    # A WHOLE LINE, matched without a pipe: the trailer has to be its own
    # line -- a body that merely mentions the words is not a trailer --
    # and `grep -q` behind a pipe can be raced into reporting a trailer
    # that is present as absent.  See vcs_rule_problems.
    case $'\n'"${message}"$'\n' in
        *$'\n'"${TRAILER_KEY}: ${name}"$'\n'*) ;;
        *)
            die "${EX_COMMIT}" "the commit does not carry the" \
                "'${TRAILER_KEY}: ${name}' trailer, so the lifecycle" \
                "cannot find it again.  The commit exists; its place" \
                "in the lifecycle does not."
            ;;
    esac
    if [ -n "${anchor}" ]; then
        case $'\n'"${message}"$'\n' in
            *$'\n'"${ANCHOR_TRAILER_KEY}: ${anchor}"$'\n'*) ;;
            *)
                die "${EX_COMMIT}" "the commit does not carry" \
                    "'${ANCHOR_TRAILER_KEY}: ${anchor:0:16}...', so the" \
                    "evidence anchor's head was sealed into the tree" \
                    "and never published into the history.  A ledger" \
                    "whose head appears nowhere in the history is one" \
                    "more mutable file beside the evidence it is" \
                    "supposed to vouch for."
                ;;
        esac
    fi
    return 0
}

# ---------------------------------------------------------------------
# WHAT THE `final` CHECKPOINT MUST HAVE RECORDED, AND WHY THIS IS HERE RATHER
# THAN ONLY IN THE GATE.
# ---------------------------------------------------------------------

# commit_touched COMMIT PATHSPEC -- the paths that commit recorded under
# PATHSPEC, or nothing.  diff-tree against the first parent, which is
# what "this commit changed" means for a linear history.
commit_touched() {
    "${GIT}" diff-tree --no-commit-id --name-only -r "$1" -- "$2" \
        2>/dev/null || printf ''
}

# generation_commit() answers the question that matters: which commit put
# the content HEAD CARRIES NOW into the tree.  It is the NEWEST commit
# that changed the path -- any later commit touching it would have changed
# it again -- so it is exactly the commit that produced the current blob,
# and an ordering asserted from it is an ordering about the current
# recording rather than about the first one ever published.
generation_commit() {
    "${GIT}" log --max-count=1 --format=%H HEAD -- "$1" 2>/dev/null |
        "${TR}" -d '\r' || printf ''
}

# tracked_at_head PATH -- true when HEAD carries that exact path.
tracked_at_head() {
    "${GIT}" rev-parse --verify --quiet "HEAD:$1" >/dev/null 2>&1
}

# ---------------------------------------------------------------------
# THE ONE CASE WHERE A `final` CHECKPOINT LEGITIMATELY CARRIES NO SAVE.
# The save assertion below reads the requirement as "a commit after character
# creation AND a commit after the session closed", and refuses a `final` that
# carries no save because such a commit is the second of those two in name
# only.
# ---------------------------------------------------------------------
# THE ANCHOR IS A PARAMETER, defaulting to the one a checkpoint resolved.
published_final_for_this_session() {
    local anchor="${1:-${CREATION_COMMIT}}"
    local commit=""
    if [ -z "${anchor}" ]; then
        return 1
    fi
    while IFS= read -r commit; do
        [ -n "${commit}" ] || continue
        [ "${commit}" != "${anchor}" ] || continue
        "${GIT}" merge-base --is-ancestor "${anchor}" \
            "${commit}" 2>/dev/null || continue
        if [ -n "$(commit_touched "${commit}" \
                "${PLAYTHROUGH_USERDIR}")" ]; then
            printf '%s' "${commit}"
            return 0
        fi
    done < <(final_commits)
    return 1
}

# render_completion_note COMMIT -- what to say when the carve-out
# applies.  One phrasing, used by both assertions, because two copies of
# an explanation drift.
render_completion_note() {
    playthrough_log "this '${CHECKPOINT_FINAL}' checkpoint records no" \
        "change under $(rel "${PLAYTHROUGH_USERDIR}"), and it does not" \
        "need to: ${1:0:10} already published this session's save, and" \
        "this commit carries the render -- the film, the transcripts" \
        "and the timeline -- which cannot exist until the session is" \
        "over and which the requirement separately asks to be committed"
}

# assert_staged_records_the_save -- the same property as
# assert_final_recorded_the_save, asserted BEFORE the commit instead of after
# it.
assert_staged_records_the_save() {
    if ! anything_staged; then
        return 0
    fi
    if ! "${GIT}" diff --cached --quiet HEAD -- \
            "${PLAYTHROUGH_USERDIR}" 2>/dev/null; then
        return 0
    fi
    local published=""
    if published="$(published_final_for_this_session)"; then
        render_completion_note "${published}"
        return 0
    fi
    die "${EX_LIFECYCLE}" "this '${CHECKPOINT_FINAL}' checkpoint would" \
        "record changes, but none of them is under" \
        "$(rel "${PLAYTHROUGH_USERDIR}").  This checkpoint exists to" \
        "publish the save the survivor left behind after the in-game" \
        "Save and Quit, and the requirement is read as a commit after" \
        "character creation AND a commit after the session closed -- so" \
        "a final commit carrying no save is the second of those two in" \
        "name only, and the acceptance gate rejects it.  Save and quit" \
        "inside the game first, so the engine rewrites the save, then" \
        "take this checkpoint.  (A later '${CHECKPOINT_FINAL}' that" \
        "carries only the render is allowed, but only once an earlier" \
        "one descending from this survivor's creation anchor has" \
        "published the save -- and none has.)  NOTHING WAS COMMITTED;" \
        "the index is left staged so what would have been recorded can" \
        "be inspected with 'git diff --cached', and nothing was" \
        "rewritten."
}

assert_final_recorded_the_save() {
    local touched="" published=""
    touched="$(commit_touched HEAD "${PLAYTHROUGH_USERDIR}")"
    if [ -z "${touched}" ] &&
            published="$(published_final_for_this_session)"; then
        render_completion_note "${published}"
        return 0
    fi
    if [ -z "${touched}" ]; then
        die "${EX_COMMIT}" "the '${CHECKPOINT_FINAL}' checkpoint" \
            "${COMMIT_HASH:0:10} records no change anywhere under" \
            "$(rel "${PLAYTHROUGH_USERDIR}").  This checkpoint exists" \
            "to publish the save the survivor left behind after the" \
            "in-game Save and Quit, and the requirement is read as a" \
            "commit after creation AND a commit after the session" \
            "closed -- a final commit that carries no save is the" \
            "second of those two in name only.  Save and quit inside" \
            "the game first, so the engine rewrites the save, then" \
            "take this checkpoint.  (A later checkpoint carrying only" \
            "the render is allowed once an earlier one descending from" \
            "this survivor's creation anchor has published the save --" \
            "and none has.)"
    fi
    local recorded=0
    # Same reason as tracked_capture_count: one number, always, whatever
    # the input looked like.
    recorded="$(printf '%s\n' "${touched}" | "${GREP}" -c .)" ||
        recorded=0
    playthrough_log "the checkpoint records ${recorded} path(s) under" \
        "$(rel "${PLAYTHROUGH_USERDIR}")"
    return 0
}

assert_dossier_precedes_captures() {
    local dossier="" capture="" frame=""
    if ! capture="$(first_capture)"; then
        return 0
    fi
    # BOUND TO THIS GENERATION, not to the first time either path
    # existed.  See generation_commit for the measurement this replaces
    # and why the old one could be satisfied by a retired recording.
    if ! tracked_at_head "$(rel "${PLAYTHROUGH_DOSSIER}")" ||
            ! tracked_at_head "$(rel "${capture}")"; then
        die "${EX_COMMIT}" "HEAD does not carry both" \
            "$(rel "${PLAYTHROUGH_DOSSIER}") and $(rel "${capture}")," \
            "so which commit put the CURRENT content of each there" \
            "cannot be read, and the ordering the requirement asks for" \
            "is about the current content.  Take" \
            "'commit_artifacts.sh ${CHECKPOINT_DOSSIER}' and then" \
            "'${CHECKPOINT_CREATION}' in that order."
    fi
    dossier="$(generation_commit "$(rel "${PLAYTHROUGH_DOSSIER}")")"
    frame="$(generation_commit "$(rel "${capture}")")"
    if [ -z "${dossier}" ] || [ -z "${frame}" ]; then
        die "${EX_COMMIT}" "the commit that put the current dossier in" \
            "the tree is '${dossier:-none}' and the one that put the" \
            "current first capture there is '${frame:-none}', so the" \
            "ordering the requirement asks for cannot be read out of" \
            "this history at all."
    fi
    if [ "${dossier}" = "${frame}" ]; then
        die "${EX_COMMIT}" "${dossier:0:10} put BOTH the current" \
            "$(rel "${PLAYTHROUGH_DOSSIER}") and the current" \
            "$(rel "${capture}") into the tree, so 'the dossier was" \
            "written before the first gameplay frame' is unprovable" \
            "from this history -- one commit cannot precede itself." \
            "A recording published in a single bundled commit cannot" \
            "acquire that ordering afterwards: commit the dossier on" \
            "its own first ('commit_artifacts.sh" \
            "${CHECKPOINT_DOSSIER}'), then '${CHECKPOINT_CREATION}'," \
            "then this one."
    fi
    if ! "${GIT}" merge-base --is-ancestor "${dossier}" "${frame}" \
            2>/dev/null; then
        die "${EX_COMMIT}" "${dossier:0:10} put the current dossier in" \
            "the tree and ${frame:0:10} put the current first capture" \
            "there, and ${dossier:0:10} is not an ancestor of it.  The" \
            "requirement is an ORDER: on separate branches neither" \
            "commit precedes the other, and a dossier REWRITTEN after" \
            "the session was captured is a dossier whose current words" \
            "were not committed before play."
    fi
    playthrough_log "the commit that put the current dossier in the" \
        "tree (${dossier:0:10}) is a strict ancestor of the one that" \
        "put the current first capture there (${frame:0:10}), so the" \
        "before-play ordering is provable for THIS recording rather" \
        "than for whichever generation first used these paths"
    return 0
}

verify_commit() {
    local name="$1"
    verify_attribution_and_trailer "${name}" "${ANCHOR_HEAD}"
    local leftover
    # The same flags the pre-commit sweep uses, so "clean" means the
    # same thing on both sides of the commit: every untracked file
    # listed individually, and an ignored path inside the tree counted
    # as the problem it is rather than hidden by default.
    leftover="$("${GIT}" status --porcelain --untracked-files=all \
        --ignored=matching -- "${PATHSPECS[@]}" 2>/dev/null ||
        printf '')"
    if [ -n "${leftover}" ]; then
        die "${EX_COMMIT}" "these paths are still uncommitted after" \
            "the checkpoint: ${leftover}.  Everything under" \
            "$(rel "${PLAYTHROUGH_DIR}") is evidence and a checkpoint" \
            "that left some of it behind has not done its job."
    fi
    assert_tracked_at_head
    # The two properties the acceptance gate will look for next, asserted here
    # so this step cannot certify what that one rejects.
    if is_post_session_checkpoint "${name}"; then
        assert_final_recorded_the_save
        assert_dossier_precedes_captures
    fi
    playthrough_log "the checkpoint is verified: attribution," \
        "trailer, a clean tree and every artifact class tracked"
    return 0
}

# verify_dossier_commit -- the narrower verification the FIRST commit of the
# lifecycle can actually satisfy.
verify_dossier_commit() {
    verify_attribution_and_trailer "${CHECKPOINT_DOSSIER}" \
        "${ANCHOR_HEAD}"
    if ! "${GIT}" ls-files --error-unmatch -- \
            "${PLAYTHROUGH_DOSSIER}" >/dev/null 2>&1; then
        die "${EX_COMMIT}" "the commit was taken but git still does" \
            "not track $(rel "${PLAYTHROUGH_DOSSIER}").  That is the" \
            "one thing this checkpoint exists to publish."
    fi
    local touched=""
    touched="$(commit_touched HEAD "${PLAYTHROUGH_DOSSIER}")"
    if [ -z "${touched}" ]; then
        die "${EX_COMMIT}" "the '${CHECKPOINT_DOSSIER}' checkpoint" \
            "${COMMIT_HASH:0:10} records no change to" \
            "$(rel "${PLAYTHROUGH_DOSSIER}"), so it is not the commit" \
            "that introduced the dossier and the ordering it exists to" \
            "establish is not established by it."
    fi
    playthrough_log "the '${CHECKPOINT_DOSSIER}' checkpoint is" \
        "verified: attribution, trailer, and the dossier now tracked" \
        "at HEAD ahead of any capture"
    return 0
}

# assert_tracked_at_head -- prove the four artifact classes the requirement
# names are in the index, by asking git rather than by looking at the
# filesystem.
assert_tracked_at_head() {
    local -a required=("${PLAYTHROUGH_MANIFEST}")
    required+=("${REQUIRED_PERSISTENCE_FILES[@]}")
    local path
    for path in "${required[@]}"; do
        if ! "${GIT}" ls-files --error-unmatch -- "${path}" \
                >/dev/null 2>&1; then
            die "${EX_COMMIT}" "$(rel "${path}") is NOT tracked after" \
                "the checkpoint.  This is the failure that hides" \
                "itself: .gitignore matches the engine's own" \
                "'#<name>.sav' and '*.log' names, and without the" \
                "terminal '!/playthrough/**' negation 'git add' skips" \
                "them and exits 0.  Check that negation is still the" \
                "last matching rule."
        fi
    done
    local tracked_frames
    tracked_frames="$("${GIT}" ls-files -- \
        "${PLAYTHROUGH_FRAMES_DIR}" 2>/dev/null |
        "${WC}" -l | "${TR}" -d ' ')"
    case "${tracked_frames}" in
        ''|*[!0-9]*) tracked_frames="-1" ;;
    esac
    # REPORTED, not merely compared.  A number a reader can see beside
    # the other one is how decimation or a partial add becomes obvious
    # instead of being something this script promises did not happen.
    playthrough_log "captures: ${tracked_frames} tracked by git," \
        "${FRAME_COUNT} on disk"
    if [ "${tracked_frames}" -ne "${FRAME_COUNT}" ]; then
        die "${EX_COMMIT}" "${tracked_frames} frame(s) are tracked" \
            "and ${FRAME_COUNT} are on disk.  Every capture is" \
            "committed -- no decimation, no sampling, no" \
            "deduplication -- so a difference here is a frame that" \
            "exists in the session and not in the repository."
    fi
    return 0
}


# ---------------------------------------------------------------------
# THE SUBCOMMANDS.
# `creation` and `final` run the SAME gates in the same order, and differ only
# in the lifecycle assertions `final` adds.
# ---------------------------------------------------------------------

run_common_gates() {
    local checkpoint="$1"
    assert_identity
    assert_repository
    # After the repository is the one we expect, and before anything is staged:
    # say which scope named the author.
    report_identity_scope
    assert_scope
    report_foreign_worktree_changes
    assert_committed_vcs_rules
    # HEAD's rules are a clone's; the WORKING TREE's are the ones the
    # `git add` in this run applies, so the effective attributes are
    # asked of both.
    assert_attribute_semantics "the working tree"
    assert_no_machine_files
    assert_save_tree "${checkpoint}"
    assert_evidence
    assert_dossier "${checkpoint}"
    # The deliverable's own document, at the one checkpoint that publishes a
    # finished recording.
    assert_report "${checkpoint}"
    # And the measurement that report is written from: present, passing,
    # about the history, and about THIS tree.  Both are no-ops except at
    # the one checkpoint each belongs to.
    assert_acceptance_report "${checkpoint}"
    # After the save and the record are known, and before anything is
    # staged: the paths this checkpoint exists to preserve must not be
    # ones `git add` would silently skip.
    assert_not_ignored
    assert_no_debug_bindings
    return 0
}

# ---------------------------------------------------------------------
# THE DOSSIER CHECKPOINT -- the first of the three, and the one that makes the
# other two provable.
# ---------------------------------------------------------------------
# tracked_capture_count -- how many captures git has in the index.
tracked_capture_count() {
    "${GIT}" ls-files -- "${PLAYTHROUGH_FRAMES_DIR}" 2>/dev/null |
        "${WC}" -l | "${TR}" -d ' '
}

# ---------------------------------------------------------------------
# HAS THE SESSION BEGUN?
# Every trace a started session leaves, wherever it leaves it: a capture on the
# disk, a capture in the index, a row in the record, or a line in either
# sidecar the capture stage appends as it goes.
disk_capture_count() {
    "${FIND}" "${PLAYTHROUGH_FRAMES_DIR}" -mindepth 1 -maxdepth 1 \
        -type f -name 'frame_*.png' -print 2>/dev/null |
        "${WC}" -l | "${TR}" -d ' '
}

# nonblank_line_count PATH -- rows in a JSONL sidecar, 0 when absent.
nonblank_line_count() {
    [ -f "$1" ] || { printf '0'; return 0; }
    "${GREP}" -c . -- "$1" 2>/dev/null || printf '0'
}

assert_play_has_not_begun() {
    local -a evidence=()
    local count=""
    count="$(disk_capture_count)"
    if [ "${count:-0}" -gt 0 ]; then
        evidence+=("${count} capture(s) on disk in \
$(rel "${PLAYTHROUGH_FRAMES_DIR}")")
    fi
    count="$(tracked_capture_count)"
    if [ "${count:-0}" -gt 0 ]; then
        evidence+=("${count} capture(s) already tracked by git")
    fi
    count="$(nonblank_line_count "${PLAYTHROUGH_MANIFEST}")"
    if [ "${count:-0}" -gt 0 ]; then
        evidence+=("${count} row(s) in $(rel "${PLAYTHROUGH_MANIFEST}")")
    fi
    count="$(nonblank_line_count "${PLAYTHROUGH_OBSERVATIONS}")"
    if [ "${count:-0}" -gt 0 ]; then
        evidence+=("${count} row(s) in \
$(rel "${PLAYTHROUGH_OBSERVATIONS}"), which the capture stage appends \
as each frame is taken")
    fi
    count="$(nonblank_line_count "${PLAYTHROUGH_FRAME_DIGESTS}")"
    if [ "${count:-0}" -gt 0 ]; then
        evidence+=("${count} row(s) in \
$(rel "${PLAYTHROUGH_FRAME_DIGESTS}")")
    fi
    if [ "${#evidence[@]}" -eq 0 ]; then
        return 0
    fi
    die "${EX_LIFECYCLE}" "the session has already left evidence" \
        "behind -- ${evidence[*]} -- so a '${CHECKPOINT_DOSSIER}'" \
        "checkpoint taken now could not put the dossier ahead of the" \
        "first gameplay frame, and putting it ahead of them is the only" \
        "thing this checkpoint does.  It belongs immediately after the" \
        "dossier is written and before the first keystroke of the" \
        "session.  If this evidence is a superseded recording, retire" \
        "it in its own commit first; if it is the current one, its" \
        "dossier ordering cannot be established after the fact and the" \
        "session has to be re-recorded.  Nothing was committed."
}

# ---------------------------------------------------------------------
# THE REPOSITORY-INTEGRATION MILESTONE
# The three session checkpoints REFUSE to run over a history whose .gitignore
# does not end in the terminal '!/playthrough/**' negation, and they are right
# to: without it a fresh clone re-ignores the engine's own '#<name>.sav' and
# '*.log' files and the save data is simply absent.
readonly -a INTEGRATION_PATHS=(".gitignore" ".gitattributes")

assert_worktree_vcs_rules() {
    local -a problems=()
    local problem=""
    while IFS= read -r problem; do
        [ -n "${problem}" ] || continue
        problems+=("${problem}")
    done < <(vcs_rule_problems worktree_lines)
    if [ "${#problems[@]}" -eq 0 ]; then
        playthrough_log "the working tree's .gitignore ends in" \
            "'${IGNORE_NEGATION}' and its .gitattributes carries all" \
            "${#REQUIRED_ATTRIBUTES[@]} rows this feature depends on," \
            "so committing them publishes rules that are already right"
        # The rows are present; this asks whether git would apply them,
        # which is the property publishing them is FOR.
        assert_attribute_semantics "the working tree"
        return 0
    fi
    die "${EX_PREREQ}" "the working tree's own rule files are not yet" \
        "what this feature depends on -- ${problems[*]}.  This" \
        "milestone commits those two files, so it will not publish them" \
        "in a state that leaves the save data ignored on the next fresh" \
        "clone.  Fix the files first, then take this milestone." \
        "Nothing was committed."
}

# integration_staged_paths -- the staged paths, NUL terminated, restricted
# to the two this milestone owns.
integration_staged_paths() {
    "${GIT}" diff --cached --name-only -z HEAD -- \
        "${INTEGRATION_PATHS[@]}" 2>/dev/null || printf ''
}

do_integration() {
    SCOPE_MODE="${SCOPE_VCS}"
    assert_identity
    assert_repository
    report_identity_scope
    # In this mode assert_scope refuses anything staged that is NOT one
    # of the two files -- including anything under playthrough/, which
    # belongs to the session checkpoints.
    assert_scope
    assert_no_machine_files
    assert_worktree_vcs_rules

    local -a staged=()
    local path=""
    if ! "${GIT}" add -- "${INTEGRATION_PATHS[@]}"; then
        die "${EX_COMMIT}" "git refused to stage" \
            "${INTEGRATION_PATHS[*]}.  Nothing was committed."
    fi
    while IFS= read -r -d '' path; do
        staged+=("${path}")
    done < <(integration_staged_paths)
    # READ BACK AND HELD TO THE SAME SCOPE.  `git add` was given two
    # names, so this cannot ordinarily differ -- and that is exactly why
    # it is cheap to assert rather than assume.
    for path in "${staged[@]}"; do
        if ! in_scope "${path}"; then
            die "${EX_SCOPE}" "staging left" \
                "$(printf '%q' "${path}") in the index, which is" \
                "neither .gitignore nor .gitattributes.  Nothing was" \
                "committed."
        fi
    done
    assert_scope

    if [ "${#staged[@]}" -eq 0 ]; then
        playthrough_log "HEAD already carries .gitignore and" \
            ".gitattributes exactly as the working tree has them, so" \
            "there is nothing for the" \
            "'${CHECKPOINT_INTEGRATION}' milestone to commit.  No" \
            "empty commit was manufactured."
        COMMITTED="no"
        COMMIT_HASH=""
        assert_committed_vcs_rules
        report "${CHECKPOINT_INTEGRATION}" ""
        return 0
    fi

    local -a message=("-m" "${SUBJECT_INTEGRATION}")
    message+=("-m" "$(printf -- '- %s\n' "${staged[@]}")")
    message+=("-m" "${TRAILER_KEY}: ${CHECKPOINT_INTEGRATION}")
    if ! git_mutate commit --quiet "${message[@]}"; then
        die "${EX_COMMIT}" "git refused the" \
            "'${CHECKPOINT_INTEGRATION}' milestone commit.  The index" \
            "is left staged so the failure can be inspected; nothing" \
            "was rewritten."
    fi
    if ! COMMIT_HASH="$("${GIT}" rev-parse HEAD 2>/dev/null)"; then
        die "${EX_COMMIT}" "the '${CHECKPOINT_INTEGRATION}' milestone" \
            "commit was made but its hash could not be read back, so" \
            "it cannot be verified."
    fi
    COMMITTED="yes"
    playthrough_log "committed the '${CHECKPOINT_INTEGRATION}'" \
        "milestone as ${COMMIT_HASH} (${staged[*]})"
    verify_attribution_and_trailer "${CHECKPOINT_INTEGRATION}"
    # The point of the commit, asserted from the history it just made
    # rather than from the fact that the commit succeeded.
    assert_committed_vcs_rules
    report "${CHECKPOINT_INTEGRATION}" ""
    return 0
}

do_dossier() {
    assert_identity
    assert_repository
    report_identity_scope
    assert_scope
    report_foreign_worktree_changes
    assert_committed_vcs_rules
    # HEAD's rules are a clone's; the WORKING TREE's are the ones the
    # `git add` in this run applies, so the effective attributes are
    # asked of both.
    assert_attribute_semantics "the working tree"
    assert_no_machine_files
    # Existence and substance only: the tracked-at-HEAD half of
    # assert_dossier is what THIS commit is about to establish.
    assert_dossier "${CHECKPOINT_DOSSIER}"
    # PLAY MUST NOT HAVE BEGUN, AND "TRACKED" IS THE WRONG QUESTION.
    # This used to count only the captures git already carries, which asks
    # whether the evidence was COMMITTED rather than whether it EXISTS.
    assert_play_has_not_begun
    if "${GIT}" ls-files --error-unmatch -- "${PLAYTHROUGH_DOSSIER}" \
            >/dev/null 2>&1 &&
            [ -z "$(commit_touched HEAD "${PLAYTHROUGH_DOSSIER}")" ] &&
            [ -z "$("${GIT}" status --porcelain -- \
                "${PLAYTHROUGH_DOSSIER}" 2>/dev/null)" ]; then
        playthrough_log "$(rel "${PLAYTHROUGH_DOSSIER}") is already" \
            "tracked and unchanged, and the session has left no trace" \
            "on disk or in the history, so the ordering this" \
            "checkpoint establishes is already in the history"
    fi
    # ONE path, by name. A dossier commit that also swept up the tooling or the
    # notes would be the bundled commit this step exists to split.
    assert_staging_is_sound
    stage_batch "the survivor's dossier" "${PLAYTHROUGH_DOSSIER}"
    commit_checkpoint "${CHECKPOINT_DOSSIER}" "${SUBJECT_DOSSIER}"
    if [ "${COMMITTED}" = "yes" ]; then
        verify_dossier_commit
    fi
    report "${CHECKPOINT_DOSSIER}" ""
    return 0
}

do_creation() {
    run_common_gates "${CHECKPOINT_CREATION}"
    # THE DOSSIER MUST ALREADY BE IN THE HISTORY.
    if ! "${GIT}" ls-files --error-unmatch -- \
            "${PLAYTHROUGH_DOSSIER}" >/dev/null 2>&1; then
        die "${EX_LIFECYCLE}" "$(rel "${PLAYTHROUGH_DOSSIER}") is not" \
            "tracked yet, and this checkpoint stages the captures --" \
            "so the dossier and the first frame would arrive in ONE" \
            "commit and 'the dossier was written before the first" \
            "gameplay frame' could never be read out of the history," \
            "because one commit cannot precede itself.  Take" \
            "'commit_artifacts.sh ${CHECKPOINT_DOSSIER}' first, which" \
            "commits it alone.  Nothing was committed."
    fi
    # A `creation` checkpoint taken when one already exists FOR THIS SURVIVOR
    # is either a re-run over an unchanged tree -- which commit_checkpoint
    # handles by doing nothing -- or a second creation for one survivor, which
    # would make the trailer search ambiguous for every later `final`.
    local existing=""
    if existing="$(creation_commit_for_survivor)"; then
        if has_pending_changes; then
            die "${EX_LIFECYCLE}" "a '${CHECKPOINT_CREATION}'" \
                "checkpoint for $(loaded_survivor) already exists" \
                "(${existing}) and there are further changes to" \
                "record.  A second creation checkpoint for one" \
                "survivor would make" \
                "'${TRAILER_KEY}: ${CHECKPOINT_CREATION}' match two" \
                "commits about the same person and the lifecycle would" \
                "no longer name a single moment.  Those changes belong" \
                "to the '${CHECKPOINT_FINAL}' checkpoint or to an" \
                "ordinary commit.  Nothing was committed."
        fi
    else
        existing=""
    fi
    stage_artifacts
    commit_checkpoint "${CHECKPOINT_CREATION}" "${SUBJECT_CREATION}"
    if [ "${COMMITTED}" = "yes" ]; then
        verify_commit "${CHECKPOINT_CREATION}"
    fi
    report "${CHECKPOINT_CREATION}" \
        "$(creation_commit_for_survivor || printf '')"
    return 0
}

do_final() {
    run_common_gates "${CHECKPOINT_FINAL}"
    assert_creation_checkpoint
    stage_artifacts
    # After staging and before committing: what this commit WOULD record
    # has to include the save, and refusing here costs nothing where
    # refusing afterwards would leave the bad commit behind.
    assert_staged_records_the_save
    commit_checkpoint "${CHECKPOINT_FINAL}" "${SUBJECT_FINAL}"
    if [ "${COMMITTED}" = "yes" ]; then
        verify_commit "${CHECKPOINT_FINAL}"
    fi
    report "${CHECKPOINT_FINAL}" "${CREATION_COMMIT}"
    return 0
}

# do_media -- the artifacts DERIVED from the closed record.
do_media() {
    run_common_gates "${CHECKPOINT_MEDIA}"
    assert_creation_checkpoint
    assert_published_final "${CHECKPOINT_MEDIA}"
    stage_artifacts
    commit_checkpoint "${CHECKPOINT_MEDIA}" "${SUBJECT_MEDIA}"
    if [ "${COMMITTED}" = "yes" ]; then
        verify_commit "${CHECKPOINT_MEDIA}"
    fi
    report "${CHECKPOINT_MEDIA}" "${CREATION_COMMIT}"
    return 0
}

# do_attest -- the two reports, and the only step that publishes the acceptance
# report into the tree.
do_attest() {
    run_common_gates "${CHECKPOINT_ATTEST}"
    assert_creation_checkpoint
    assert_published_final "${CHECKPOINT_ATTEST}"
    publish_acceptance_report
    stage_artifacts
    commit_checkpoint "${CHECKPOINT_ATTEST}" "${SUBJECT_ATTEST}"
    if [ "${COMMITTED}" = "yes" ]; then
        verify_commit "${CHECKPOINT_ATTEST}"
    fi
    report "${CHECKPOINT_ATTEST}" "${CREATION_COMMIT}"
    return 0
}

# assert_published_final NAME -- the session was closed and committed before
# anything derived from it is.
assert_published_final() {
    local checkpoint="$1" published=""
    if published="$(published_final_for_this_session)"; then
        playthrough_log "the '${CHECKPOINT_FINAL}' checkpoint" \
            "${published:0:10} already published this survivor's" \
            "closed session, so '${checkpoint}' has a record to be" \
            "about"
        return 0
    fi
    die "${EX_LIFECYCLE}" "there is no '${CHECKPOINT_FINAL}'" \
        "checkpoint for this survivor in the history, so" \
        "'${checkpoint}' has nothing to be about: it would commit" \
        "artifacts derived from a record that was never published, and" \
        "the report would cite commits that do not exist.  End the" \
        "session through the in-game Save & Quit, take" \
        "'commit_artifacts.sh ${CHECKPOINT_FINAL}', then come back to" \
        "'${checkpoint}'.  Nothing was committed."
}

# staged_paths_preview -- what a checkpoint WOULD add, without touching the
# index. --dry-run makes `git add` report and change nothing, which is the only
# honest way to ask this question before deciding whether staging is allowed at
# all.
staged_paths_preview() {
    "${GIT}" add --dry-run -- "${PATHSPECS[@]}" 2>/dev/null ||
        printf ''
}

# anything_to_add -- whether the working tree would give a checkpoint
# anything, read from the FIRST line of the preview and no further.
anything_to_add() {
    local first=""
    while IFS= read -r first; do
        [ -n "${first}" ] || continue
        return 0
    done < <(staged_paths_preview)
    return 1
}

# has_pending_changes -- true when a checkpoint would record anything.
has_pending_changes() {
    if anything_to_add; then
        return 0
    fi
    if anything_staged; then
        return 0
    fi
    return 1
}

# report_pending_preview -- what a checkpoint would stage, bounded.
report_pending_preview() {
    local line total=0
    local -a shown=()
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        total=$((total + 1))
        if [ "${#shown[@]}" -lt "${PREVIEW_LIMIT}" ]; then
            shown+=("${line}")
        fi
    done < <(staged_paths_preview)
    if [ "${total}" -eq 0 ]; then
        playthrough_log "a checkpoint would stage nothing; every path" \
            "is already recorded at HEAD"
        return 0
    fi
    if [ "${total}" -gt "${#shown[@]}" ]; then
        playthrough_log "a checkpoint would stage ${total} path(s);" \
            "the first ${#shown[@]} are:"
    else
        playthrough_log "a checkpoint would stage ${total} path(s):"
    fi
    printf '%s\n' "${shown[@]}" >&2
    return 0
}

# ---------------------------------------------------------------------
# THE LIFECYCLE ELIGIBILITY ANSWER, ASKED WITHOUT COMMITTING ANYTHING.
# `final` refuses unless a `creation` checkpoint exists FOR THIS SURVIVOR and
# the record has grown since it.
# ---------------------------------------------------------------------
FINAL_ANCHOR=""
FINAL_ELIGIBLE="no"
FINAL_REASON=""

# assess_final_eligibility WORLD CHARACTER ROWS
#   Set the three variables above.  Every argument may be empty, which
#   is itself an answer: a session whose survivor cannot be read is one
#   whose checkpoint would refuse for that reason first.
assess_final_eligibility() {
    local world="$1" character="$2" rows="$3"
    local before=""
    FINAL_ANCHOR=""
    FINAL_ELIGIBLE="no"
    FINAL_REASON=""
    if [ -z "${world}" ] || [ -z "${character}" ]; then
        FINAL_REASON="no-survivor-loaded"
        return 0
    fi
    case "${rows}" in
        ''|*[!0-9]*)
            FINAL_REASON="no-record"
            return 0
            ;;
    esac
    if ! FINAL_ANCHOR="$(creation_commit_for_survivor \
            "${world} / ${character}")"; then
        FINAL_ANCHOR=""
        if [ -z "$(creation_commit)" ]; then
            FINAL_REASON="no-creation-checkpoint"
        else
            FINAL_REASON="no-creation-for-this-survivor"
        fi
        return 0
    fi
    if ! before="$(manifest_rows_at "${FINAL_ANCHOR}")"; then
        FINAL_REASON="anchor-carries-no-record"
        return 0
    fi
    if [ "${rows}" -le "${before}" ]; then
        FINAL_REASON="record-has-not-grown"
        return 0
    fi
    FINAL_ELIGIBLE="yes"
    return 0
}

# do_scan -- the two soundness questions, on their own.
do_scan() {
    assert_repository
    assert_staging_is_sound
    playthrough_log "the tree is sound to stage: provenance and content" \
        "both hold"
    return "${EX_OK}"
}

do_status() {
    # Read-only by construction, and it REPORTS what a checkpoint would
    # refuse rather than refusing itself -- an operator runs `status`
    # precisely when something is wrong, so a missing identity has to be
    # describable here instead of ending the call.
    if ! resolve_identity; then
        playthrough_warn "git cannot determine an author identity, so" \
            "every checkpoint would refuse.  Supply it the way the" \
            "platform supplies it -- its own git configuration or the" \
            "GIT_AUTHOR_* environment; a checkpoint records the" \
            "identity it resolves into this repository's own" \
            "configuration, but it will not invent one."
    fi
    assert_repository
    local creation
    report_pending_preview
    creation="$(creation_commit)"
    if [ -n "${creation}" ]; then
        playthrough_log "the '${CHECKPOINT_CREATION}' checkpoint is" \
            "${creation}"
    else
        playthrough_log "there is no '${CHECKPOINT_CREATION}'" \
            "checkpoint yet, so '${CHECKPOINT_FINAL}' would refuse"
    fi
    # The evidence gates report here instead of dying, because `status` exists
    # to be run when something is wrong. ROWS IS A COUNT IN EVERY STATE,
    # INCLUDING NONE.
    local world="" character="" rows="0" frames=""
    if [ -f "${PLAYTHROUGH_MANIFEST}" ]; then
        rows="$("${WC}" -l <"${PLAYTHROUGH_MANIFEST}" |
            "${TR}" -d ' ')"
    fi
    frames="$(count_matching "${PLAYTHROUGH_FRAMES_DIR}" \
        'frame_*.png')"
    local lastworld="${PLAYTHROUGH_CONFIG_DIR}/lastworld.json"
    if [ -f "${lastworld}" ]; then
        local reading=""
        if reading="$("${PLAYTHROUGH_PYTHON}" -c \
                "${LASTWORLD_READER}" "${lastworld}" 2>/dev/null)"; then
            local -a fields=()
            mapfile -t fields <<<"${reading}"
            world="${fields[0]-}"
            character="${fields[1]-}"
        fi
    fi
    # WHOSE creation checkpoint that is, which is a different question from
    # whether one exists.
    local anchor_survivor=""
    if [ -n "${creation}" ] && [ -n "${world}" ] &&
            [ -n "${character}" ]; then
        anchor_survivor="$(survivor_at "${creation}" || printf '')"
        if [ -z "${anchor_survivor}" ]; then
            playthrough_log "the '${CHECKPOINT_CREATION}' checkpoint" \
                "${creation:0:10} records no survivor its own tree can" \
                "be read for"
        elif [ "${anchor_survivor}" = "${world} / ${character}" ]; then
            playthrough_log "that checkpoint records" \
                "${anchor_survivor}, which is this session's own" \
                "survivor, so '${CHECKPOINT_FINAL}' would anchor to it"
        else
            playthrough_warn "that checkpoint records" \
                "${anchor_survivor} while this userdir has" \
                "${world} / ${character} loaded, so" \
                "'${CHECKPOINT_FINAL}' would REFUSE: it anchors to the" \
                "creation of the survivor it is about, and a row count" \
                "cannot tell two survivors apart.  Take" \
                "'${CHECKPOINT_DOSSIER}' and then" \
                "'${CHECKPOINT_CREATION}' for this survivor before" \
                "playing their session."
        fi
    fi
    # THE ANSWER A CALLER BRANCHES ON, computed with the same two predicates
    # the refusal uses, and reported whether or not the newest creation happens
    # to be the anchor.
    assess_final_eligibility "${world}" "${character}" "${rows}"
    if [ "${FINAL_ELIGIBLE}" = "yes" ]; then
        playthrough_log "'${CHECKPOINT_FINAL}' is eligible: it would" \
            "anchor to ${FINAL_ANCHOR:0:10}, which records this" \
            "session's own survivor, and the record has grown since it"
    else
        playthrough_warn "'${CHECKPOINT_FINAL}' would REFUSE" \
            "(${FINAL_REASON}).  It anchors to the" \
            "'${CHECKPOINT_CREATION}' checkpoint of the survivor it is" \
            "about, and the record has to have grown between the two."
    fi
    # AND WOULD '${CHECKPOINT_MEDIA}' BE TAKEN? A DIFFERENT QUESTION, and the
    # one an automated caller actually needs.
    local media_eligible="no" media_reason="" media_anchor=""
    if [ -z "${FINAL_ANCHOR}" ]; then
        # No anchor, so ancestry cannot be asked at all.  The reason
        # FINAL already computed is the honest one to repeat.
        media_reason="${FINAL_REASON:-no-creation-for-this-survivor}"
    elif media_anchor="$(published_final_for_this_session \
            "${FINAL_ANCHOR}")"; then
        media_eligible="yes"
    else
        media_anchor=""
        media_reason="no-final-published"
    fi
    if [ "${media_eligible}" = "yes" ]; then
        playthrough_log "'${CHECKPOINT_MEDIA}' is eligible:" \
            "'${CHECKPOINT_FINAL}' ${media_anchor:0:10} already" \
            "published this survivor's closed session, so the render" \
            "has a record to be about"
    else
        playthrough_warn "'${CHECKPOINT_MEDIA}' would REFUSE" \
            "(${media_reason}).  It commits what a render produced," \
            "and a render describes a session whose save has already" \
            "been published: end the session through the in-game Save" \
            "& Quit and take '${CHECKPOINT_FINAL}' first."
    fi
    emit "CHECKPOINT" "status"
    emit "COMMITTED" "no"
    emit "COMMIT" ""
    emit "AUTHOR" "${IDENT_AUTHOR}"
    emit "WORLD" "${world}"
    emit "CHARACTER" "${character}"
    emit "FRAMES" "${frames}"
    emit "ROWS" "${rows}"
    emit "CREATION" "${creation}"
    emit "CREATION_SURVIVOR" "${anchor_survivor}"
    emit "TRACKED_CAPTURES" "$(tracked_capture_count)"
    emit "FINAL_ELIGIBLE" "${FINAL_ELIGIBLE}"
    emit "FINAL_ANCHOR" "${FINAL_ANCHOR}"
    emit "FINAL_REASON" "${FINAL_REASON}"
    emit "MEDIA_ELIGIBLE" "${media_eligible}"
    emit "MEDIA_ANCHOR" "${media_anchor}"
    emit "MEDIA_REASON" "${media_reason}"
    return 0
}

# report NAME CREATION -- the machine-readable summary, emitted once at
# the end of a checkpoint so a caller reads one block rather than
# scraping the log.
report() {
    emit "CHECKPOINT" "$1"
    emit "COMMITTED" "${COMMITTED}"
    emit "COMMIT" "${COMMIT_HASH}"
    emit "AUTHOR" "${IDENT_AUTHOR}"
    emit "WORLD" "${WORLD_NAME}"
    emit "CHARACTER" "${CHARACTER_NAME}"
    emit "FRAMES" "${FRAME_COUNT}"
    emit "ROWS" "${ROW_COUNT}"
    emit "CREATION" "${2}"
    return 0
}

# ---------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------
usage() {
    local out="${1:-1}"
    {
        printf '%s\n' "usage: \
playthrough/tooling/commit_artifacts.sh <checkpoint>"
        printf '%s\n' ""
        printf '  %-11s %s\n' \
            "integration" "commit .gitignore and .gitattributes, and \
nothing else" \
            "dossier" "commit the survivor's dossier alone, BEFORE the \
first frame" \
            "creation" "commit the survivor and the save they start \
from" \
            "final" "commit the closed session: its last save and its \
record" \
            "media" "commit the film, the transcripts and the timeline \
derived from it" \
            "attest" "commit the acceptance report and the \
three-section report" \
            "status" "report the lifecycle, changing nothing" \
            "scan" "check the tree's provenance and content for \
secret material, changing nothing" \
            "help" "this text"
        printf '%s\n' ""
        printf '%s\n' "THE SIX MUTATING STEPS ARE ORDERED AND EACH \
REFUSES TO RUN OUT OF TURN:"
        printf '%s\n' "  integration -> dossier -> creation -> play \
the session -> final -> media"
        printf '%s\n' "  -> attest."
        printf '%s\n' "The last three are three because ONE of them \
could not be honest.  'final'"
        printf '%s\n' "used to carry the record, the film and the \
report together, and it demanded"
        printf '%s\n' "playthrough/REPORT.md before it would run -- so \
the document that cites the"
        printf '%s\n' "commits carrying the film and the acceptance \
evidence had to exist BEFORE"
        printf '%s\n' "the commit that created any of them.  Split, \
each commit cites only what"
        printf '%s\n' "already precedes it: 'final' the moment the \
session closes, 'media' once"
        printf '%s\n' "run_pipeline.sh has produced the derived \
artifacts, 'attest' last of all."
        printf '%s\n' "'attest' is also the ONLY step that publishes \
the acceptance report into"
        printf '%s\n' "the tree.  The gate that measures it writes to \
a scratch path OUTSIDE the"
        printf '%s\n' "checkout, because a measurement that writes \
into the tree it measures"
        printf '%s\n' "invalidates its own finding that the tree is \
clean; this step copies that"
        printf '%s\n' "report in and commits it in one act, and \
refuses it unless it passed, came"
        printf '%s\n' "from a phase that measures the history, and \
says it measured THIS HEAD."
        printf '%s\n' "'integration' is the one milestone that is not \
about a session: it commits"
        printf '%s\n' "the two repository-wide rule files the evidence \
depends on -- the terminal"
        printf '%s\n' "'!/playthrough/**' negation and the six binary \
and text attribute rows --"
        printf '%s\n' "and nothing else.  The other three refuse over a \
history without them,"
        printf '%s\n' "so it comes first; it is idempotent, so running \
it again commits nothing."
        printf '%s\n' "The dossier is its own commit because 'written \
before the first gameplay"
        printf '%s\n' "frame' is checked as ANCESTRY between two \
commits, and one commit cannot"
        printf '%s\n' "precede itself -- so 'creation' refuses until \
the dossier is tracked."
        printf '%s\n' "'final' anchors to the 'creation' checkpoint of \
THE SAME survivor and"
        printf '%s\n' "refuses across a survivor change, which a row \
count cannot detect."
        printf '%s\n' ""
        printf '%s\n' "A SESSION checkpoint stages playthrough/ and \
nothing else, by artifact"
        printf '%s\n' "class, in bounded batches -- never a blanket \
add, never -A, never -f, never"
        printf '%s\n' "a shell glob.  .gitignore and .gitattributes are \
CHECKED by all of them --"
        printf '%s\n' "in the working tree AND as HEAD carries them -- \
and are committed by the"
        printf '%s\n' "'integration' milestone, which stages those two \
paths and refuses any other."
        printf '%s\n' "IT NEVER WRITES GIT CONFIGURATION, in any \
scope.  It asserts that an"
        printf '%s\n' "identity RESOLVES -- 'git var \
GIT_AUTHOR_IDENT', which is the pair git will"
        printf '%s\n' "actually stamp -- reports which scope answered, \
and commits under it.  It"
        printf '%s\n' "used to record the pair with 'git config \
--local' so the attribution would"
        printf '%s\n' "travel into the container that mounts this \
checkout; supported_env.sh now"
        printf '%s\n' "forwards GIT_AUTHOR_* / GIT_COMMITTER_* \
instead, which is git's own"
        printf '%s\n' "mechanism and leaves nothing behind in the \
tree.  A repository-local pair"
        printf '%s\n' "that already matches is left as found and said \
so; one that DISAGREES with"
        printf '%s\n' "the resolved identity is a refusal, not a \
rewrite -- which of the two is"
        printf '%s\n' "wrong is the operator's call, not this script's."
        printf '%s\n' "It never invents an identity, never rewrites \
history and never pushes."
        printf '%s\n' "A mutating step takes a lock scoped to this \
checkout, so two runs over one"
        printf '%s\n' "working tree serialise and two runs over \
different ones do not."
        printf '%s\n' ""
        printf '%s\n' "Environment:"
        printf '  %s\n' \
            "PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT  seconds to wait for \
that lock (default \
${CHECKPOINT_LOCK_TIMEOUT_DEFAULT})"
        printf '%s\n' ""
        printf '%s\n' "stdout carries KEY=value lines only; all \
logging goes to stderr."
    } >&"${out}"
    return 0
}

# ---------------------------------------------------------------------
# main
# ---------------------------------------------------------------------
# take_checkpoint_lock -- serialise the MUTATING subcommands against another
# run over the same working tree.
take_checkpoint_lock() {
    local name="" timeout=""
    if ! playthrough_validate_int \
            "${PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT:-\
${CHECKPOINT_LOCK_TIMEOUT_DEFAULT}}" \
            "the checkpoint lock timeout" 0 86400; then
        die "${EX_USAGE}" "PLAYTHROUGH_CHECKPOINT_LOCK_TIMEOUT must be" \
            "a whole number of seconds from 0 to 86400.  Nothing was" \
            "committed."
    fi
    timeout="${PLAYTHROUGH_INT}"
    if ! name="$(playthrough_checkout_lock_name \
            "${CHECKPOINT_LOCK_BASENAME}")"; then
        die "${EX_PREREQ}" "the checkpoint lock name for this" \
            "checkout could not be derived, so two concurrent" \
            "checkpoints could not be kept apart.  Nothing was" \
            "committed."
    fi
    # THE SCOPE IS NAMED BY THE DIGEST, NOT BY THE PATH.
    if ! playthrough_acquire_lock "${name}" "${timeout}"; then
        die "${EX_PREREQ}" "another checkpoint is already running over" \
            "THIS checkout -- the lock is '${name}', whose digest is" \
            "derived from this working tree's path -- and it did not" \
            "finish within ${timeout}s.  Two checkpoints share one" \
            "index and one HEAD, so this run stops rather than racing" \
            "it: THIS RUN COMMITTED NOTHING, and whether the other one" \
            "committed is its own to report -- do not read this as a" \
            "statement about the repository."
    fi
    playthrough_log "holding the '${name}' lock for up to ${timeout}s;" \
        "the digest in that name is derived from THIS checkout's path," \
        "so a checkpoint running over a different working tree is not" \
        "serialised against this one"
    # AND THE CHECKOUT'S MUTATION LOCK, EXCLUSIVELY.
    if ! playthrough_acquire_mutation_lock exclusive "${timeout}"; then
        die "${EX_PREREQ}" "this checkpoint could not take THIS" \
            "checkout's mutation lock exclusively within ${timeout}s," \
            "so it cannot promise that the tree it would commit is the" \
            "tree the gate measured.  A session step, a producer or a" \
            "standalone gate is still running over the same working" \
            "tree.  NOTHING WAS COMMITTED; wait for that stage and run" \
            "this again."
    fi
    return 0
}

main() {
    local subcommand="${1-}"
    if [ "$#" -gt 1 ]; then
        usage 2
        die "${EX_USAGE}" "one subcommand, no options.  Every input" \
            "this step has is the repository it is run in."
    fi
    case "${subcommand}" in
        help|-h|--help)
            usage 1
            return "${EX_OK}"
            ;;
        "${CHECKPOINT_INTEGRATION}")
            take_checkpoint_lock
            do_integration
            ;;
        "${CHECKPOINT_DOSSIER}")
            take_checkpoint_lock
            do_dossier
            ;;
        "${CHECKPOINT_CREATION}")
            take_checkpoint_lock
            do_creation
            ;;
        "${CHECKPOINT_FINAL}")
            take_checkpoint_lock
            do_final
            ;;
        "${CHECKPOINT_MEDIA}")
            take_checkpoint_lock
            do_media
            ;;
        "${CHECKPOINT_ATTEST}")
            take_checkpoint_lock
            do_attest
            ;;
        status)
            do_status
            ;;
        scan)
            do_scan
            ;;
        '')
            usage 2
            die "${EX_USAGE}" "which checkpoint?  There is no" \
                "default: the commits mean different things, they are" \
                "taken at different moments of the session, and" \
                "choosing the wrong one is not something a default can" \
                "be right about.  In order:" \
                "${CHECKPOINT_DOSSIER}, ${CHECKPOINT_CREATION}," \
                "${CHECKPOINT_FINAL}, ${CHECKPOINT_MEDIA}," \
                "${CHECKPOINT_ATTEST}."
            ;;
        *)
            usage 2
            die "${EX_USAGE}" "unknown subcommand '${subcommand}'"
            ;;
    esac
    return "${EX_OK}"
}

main "$@"
