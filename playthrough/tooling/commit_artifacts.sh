#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/commit_artifacts.sh
#
# THE TWO MANDATED CHECKPOINTS, AND NOTHING ELSE.
#
# The playthrough requirement does not merely ask that the artifacts end
# up committed; it asks WHEN.  One commit immediately after the survivor
# is created, and a separate commit after the in-game ending has closed
# the session.  A sleep ending retains the live Save & Quit tree; a death
# ending moves the character into graveyard/, writes the memorials and
# may reset the world.  A single commit taken at the end satisfies
# "everything is committed" and still fails the requirement, because the
# history then cannot show that the save existed before the session was
# played -- which is precisely the shape a fabricated session would
# have.  This file is the checked, re-runnable form of that lifecycle.
#
# USAGE
#     playthrough/tooling/commit_artifacts.sh creation
#     playthrough/tooling/commit_artifacts.sh final
#     playthrough/tooling/commit_artifacts.sh status
#     playthrough/tooling/commit_artifacts.sh help
#
# IT NEVER WRITES GIT CONFIGURATION.  Not user.name, not user.email, not
# in any scope.  The identity a commit is made under is the platform's
# to supply -- through its own configuration or through the standard
# GIT_AUTHOR_* / GIT_COMMITTER_* environment -- and this file's whole
# responsibility is to ASSERT that one resolves before it commits
# anything.  `git var GIT_AUTHOR_IDENT` is the question git itself
# answers that with: it fails with status 128 when no identity can be
# determined, so an unset identity is a refusal here rather than a
# commit attributed to a guess derived from /etc/passwd.  This is the
# one place the distinction matters, so it is stated plainly: the fix
# for a missing identity is to configure the platform, never to have
# this script configure the repository.
#
# WHAT IT REFUSES TO COMMIT OVER
# Each checkpoint is gated on the evidence it is supposed to be
# preserving, because a checkpoint that commits whatever happens to be
# on disk proves nothing about the run:
#
#   * an identity that does not resolve, or an author and committer that
#     are not the same person
#   * a repository that is not this checkout, a detached HEAD, or a
#     rebase / merge / cherry-pick / revert in progress
#   * staged changes OUTSIDE playthrough/ -- those would be swept into
#     the checkpoint by the commit, since a commit publishes the whole
#     index and not just this run's pathspecs.  .gitignore and
#     .gitattributes belong to whoever edited them and are reported,
#     never staged here: this file's scope is the artifact tree
#   * anything in the INDEX that names __pycache__, a *.pyc or a *.pyo
#     once staging is done -- checked against the index itself and not
#     only against the filesystem, so a bytecode file written between
#     the hygiene sweep and the commit is still refused
#   * a save, manifest or capture that .gitignore would EXCLUDE, asked
#     with `git check-ignore --no-index` before anything is committed:
#     `git add` skips an ignored path and exits 0, so this is the only
#     honest way to learn that the terminal negation has been lost
#   * machine-local files inside playthrough/ that .gitignore's terminal
#     `!/playthrough/**` negation RE-INCLUDES: __pycache__, *.pyc, an
#     ad-hoc test artifact, or a retained/quarantined film left beside
#     the published one.  Everywhere else in the repository those are
#     ignored; inside this tree the negation makes them committable, so
#     they are refused rather than silently archived
#   * at `creation`, a save tree that is not exactly one world holding
#     exactly one survivor; at `final`, neither that live shape nor a
#     graveyard save/log plus matching memorial pair and captured death
#     sequence for the loaded survivor
#   * a missing or empty survivor dossier, at either checkpoint, and at
#     `final` one that git does not track -- the dossier is required to
#     be in the history AHEAD of the first capture, and that ordering is
#     unprovable if the file never reached a commit
#   * a manifest that does not verify against the frames, or a frame
#     count, row count and observation count that disagree
#   * an amendment whose sha256 no longer matches the manifest line it
#     corrects, so the record cannot be resolved against its own
#     corrections
#   * a missing capture attestation ledger, or a frame whose bytes no
#     longer hash to the digest attested for it -- the one substitution
#     every structural check above passes
#   * a keybindings file that binds any debug action
#   * for `final`: no `creation` checkpoint in the history, or a
#     manifest that has not grown since it -- both of which mean the
#     session was not recorded between the two commits
#
# WHAT IT DOES NOT DO
# No history rewriting, no amend, no force, no push, no branch change,
# no tag, no reset, and no clean.  It stages the artifact tree by
# artifact class and commits.  Every git call is an argument list; there
# is no eval, no `shell=True` equivalent, and no unquoted glob.
#
# THE ONE CONFIGURATION IT WRITES, AND THE FENCE AROUND IT
# `git config --local user.name` / `user.email`, and only when this
# repository does not already record them.  Never --global, never
# --system, never --worktree; the value written is exactly the one `git
# var` had already resolved, so the attribution of the commit is
# identical whether or not the write happened.  The reason it happens at
# all is that the render and capture stages run inside the declared
# container, which mounts this checkout, sets its own HOME and forwards
# no GIT_* -- so an identity living only in the invoking user's
# ~/.gitconfig does not exist in there.  See persist_identity_locally.
#
# STAGING IS EXPLICIT, BY ARTIFACT CLASS, AND BATCHED.  No blanket add
# appears anywhere in this file: every staging call is `add --` with
# named paths, never -A, never a bare '.', never -f, never a shell-
# expanded glob.  Each class -- the tooling, the narrative, the userdir,
# the captures, the record, the build intermediates, the films -- is
# named and staged on its own, and `git add --` without -A is enough
# because since git 2.0 a pathspec add records deletions as well as
# additions (measured on git 2.51: `git add -- <dir>` staged a D, an M
# and an A in one call).  The captures are additionally staged in
# BOUNDED CHUNKS of ${STAGE_BATCH_SIZE} paths, so a session of any
# length cannot approach the argument-list limit, and the chunk list is
# built by `find -print0` and read NUL-delimited rather than by letting
# a shell glob expand into thousands of words.
#
# EXPLICIT ENUMERATION HAS ONE FAILURE MODE, AND IT IS CLOSED HERE.  A
# named list can omit a class somebody adds later, which would quietly
# leave a new artifact uncommitted while every other check passed.  So
# after staging, and after assert_index_hygiene has had the first word,
# assert_tree_fully_staged proves the union of the
# batches covered the WHOLE tree: any path under playthrough/ still
# carrying an unstaged or untracked change is a refusal that names it
# and says which list to add it to.  Explicit AND complete, rather than
# explicit at the price of completeness.
#
# STDOUT IS A MACHINE CONTRACT.  KEY=value lines, one per line, nothing
# else; all logging, warnings and diagnostics go to stderr.  The keys:
#
#     CHECKPOINT   creation | final | status
#     COMMITTED    yes | no -- `no` with status 0 means the checkpoint
#                  was already taken and nothing had changed since, so
#                  an empty commit was not manufactured to make a
#                  re-run look eventful
#     COMMIT       the full hash of the commit this run made, empty when
#                  COMMITTED=no
#     AUTHOR       the identity the commit was made under
#     WORLD        the world directory the save lives in
#     CHARACTER    the survivor the engine records as loaded
#     FRAMES       captures on disk
#     ROWS         manifest rows
#     CREATION     the hash of the `creation` checkpoint, empty when
#                  there is not one yet
#
# THE TRAILER IS THE LIFECYCLE'S MEMORY.  Each commit carries
# `Playthrough-Checkpoint: <name>` as a trailer, and `final` finds the
# `creation` commit by searching for it.  A message a human wrote is not
# a lifecycle record; a trailer is, and it survives rewording.
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

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8, as capture.sh and launch_game.sh
# also adopt it.
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
    printf 'playthrough: FATAL: %s\n' "$*" >&2
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

# ---------------------------------------------------------------------
# The toolchain.  git is the subject; the rest is what the gates are
# made of.  playthrough_require_tools reports every missing tool at
# once, names the package that ships it, and verifies ownership and
# writability of each one and of every directory above it, so the paths
# below are checked paths rather than another PATH search.
# ---------------------------------------------------------------------
# awk reads HEAD's own ignore and attribute rules, and sha256sum derives
# the checkout-scoped lock name; both are named here rather than left to
# fail at their call site, so a host missing one is told about it in the
# same consolidated diagnosis as the rest.
if ! playthrough_require_tools git find wc sort grep tr awk \
        sha256sum; then
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

# ---------------------------------------------------------------------
# The lifecycle vocabulary.
# ---------------------------------------------------------------------

# The trailer key and the THREE checkpoint names.  `final` searches the
# history for the `creation` trailer, so these strings are the
# lifecycle's entire persistent state -- there is no side file to fall
# out of step with the history it describes.
#
# WHY `dossier` IS A CHECKPOINT OF ITS OWN, AND NOT A TIDINESS
# PREFERENCE.  The requirement is that the survivor is described BEFORE
# play, and the way that is checked is `git log` over
# playthrough/dossier.md against `git log` over the first capture: the
# dossier's introducing commit must be a STRICT ANCESTOR of the first
# frame's.  `creation` stages the narrative class and the captures in one
# commit, so when both arrive together their introducing commit is the
# SAME commit -- and an ordering assertion over one commit can never
# hold, however the history is read.  Measured: a documented lifecycle of
# `creation` then `final` left the ordering permanently unprovable.
#
# So the dossier gets its own, earlier commit.  Three steps, in this
# order, and each refuses to run out of turn:
#
#     dossier    the survivor described, before a single frame exists
#     creation   the survivor and the save she starts from
#     final      the closed session and its artifacts
readonly TRAILER_KEY="Playthrough-Checkpoint"
readonly CHECKPOINT_DOSSIER="dossier"
readonly CHECKPOINT_CREATION="creation"
readonly CHECKPOINT_FINAL="final"

# The subjects.  Written here rather than passed in, because a
# checkpoint whose message a caller chooses is a checkpoint whose
# meaning drifts between runs.
readonly SUBJECT_DOSSIER="Commit the survivor's dossier before the first \
frame of play"
readonly SUBJECT_CREATION="Commit the survivor's creation and the save \
it produced"
readonly SUBJECT_FINAL="Commit the closed session, its final save and \
its artifacts"

# The lock this step takes, as a BASENAME: env.sh appends a digest of
# this checkout's root so that two runs over ONE working tree serialise
# and two runs over different ones do not.  The three mutating
# subcommands take it; `status` does not, because it only reads.
#
# The wait is overridable because how long a checkpoint takes depends on
# how many captures it stages, and because a refusal nobody can reach in
# a test is a refusal nobody has read.  It is validated as an integer
# through env.sh's helper rather than used raw: bash evaluates command
# substitution inside $(( )), so an unchecked number from the environment
# is code execution and not a number.
readonly CHECKPOINT_LOCK_BASENAME="checkpoint"
readonly CHECKPOINT_LOCK_TIMEOUT_DEFAULT=120

# The one pathspec this file will ever read or write the index through.
# Anything else in the repository -- including .gitignore and
# .gitattributes, whose terminal negation and binary attributes this
# tree depends on -- is somebody else's change and is left exactly as
# found.  A checkpoint that also carried an unrelated root-file edit
# would be a checkpoint about two things.
readonly -a PATHSPECS=("playthrough")

# How many paths go into one `git add` invocation.  The captures are the
# only class big enough to matter and 256 keeps each argv far below any
# platform's limit while still being one call per 256 frames rather than
# one per frame.
readonly STAGE_BATCH_SIZE=256

# ---------------------------------------------------------------------
# THE IDENTITY GATE.
#
# `git var GIT_AUTHOR_IDENT` is git answering the question with the
# same resolution order it will use when it writes the commit: the
# GIT_AUTHOR_* environment first, then user.name / user.email from any
# configuration scope, then a derivation from the passwd entry -- and
# it exits 128 rather than derive one when it cannot get an email.
# Asking git is therefore strictly better than reading configuration
# ourselves: it cannot disagree with the commit that follows it.
#
# The author AND the committer are both required, and required to be the
# same person.  A commit whose committer is somebody other than its
# author is not what "authored and committed as" describes, and the
# difference is invisible in `git log` without a format string.
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

# ident_is_wellformed PERSON -- a non-empty display name, then an
# address in angle brackets carrying an '@' and no whitespace.  This is
# not an attempt to validate an email; it is a check that git resolved a
# real identity rather than something empty or truncated.
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
#   Ask git, fill IDENT_AUTHOR and IDENT_COMMITTER, and return 1 rather
#   than dying when there is nothing to fill them with.  Splitting this
#   out is what lets `status` report a missing identity instead of
#   refusing to describe the repository because of it.
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
# PERSISTING THAT IDENTITY INTO THIS REPOSITORY, AND ONLY THIS ONE.
#
# The identity a commit is made under must not merely be RESOLVABLE
# somewhere; it has to be recorded in the repository that carries the
# evidence.  The reason is concrete rather than tidy: this pipeline's
# render and capture stages run inside the declared container, which
# mounts the checkout and sets HOME=/tmp/playthrough-home and forwards no
# GIT_* variables at all.  An identity that lives only in the invoking
# user's ~/.gitconfig therefore DOES NOT EXIST in there -- measured, as
# `git var GIT_AUTHOR_IDENT` failing and this step exiting 3 inside the
# only environment where the later stages may legally run.  Written into
# the repository's own config it travels with the mounted tree, because
# it lives in the working tree's .git rather than in a home directory.
#
# THREE PROPERTIES MAKE THIS SAFE, AND EACH IS A DELIBERATE LIMIT:
#
#   1. THE VALUE IS NEVER CHOSEN HERE.  What is written is exactly what
#      `git var` already resolved a moment earlier, so the author and
#      committer of the commit that follows are identical whether or not
#      this function ran.  It cannot re-attribute a commit; it can only
#      make an existing attribution durable.
#   2. THE SCOPE IS `--local` AND NOTHING ELSE.  Never --global, never
#      --system, never --worktree.  A tool that reaches into a user's
#      home directory to fix its own environment is a tool nobody can
#      run twice safely.
#   3. AN EXISTING LOCAL PAIR IS LEFT ALONE.  If this repository already
#      says who commits here, that answer wins and this function only
#      reports it.  Only a MISSING half is filled in.
# ---------------------------------------------------------------------

# local_config_value KEY -- the value from the repository's own config
# file only, ignoring every other scope.  Empty when unset.
local_config_value() {
    "${GIT}" config --local --get "$1" 2>/dev/null || printf ''
}

persist_identity_locally() {
    local name mail existing_name existing_mail
    # IDENT_AUTHOR is "Name <mail>" and has already been validated by
    # ident_is_wellformed, so these two expansions cannot come back
    # empty or unbalanced.
    name="${IDENT_AUTHOR%% <*}"
    mail="${IDENT_AUTHOR#*<}"
    mail="${mail%>}"
    existing_name="$(local_config_value user.name)"
    existing_mail="$(local_config_value user.email)"
    if [ -n "${existing_name}" ] && [ -n "${existing_mail}" ]; then
        playthrough_log "this repository already records its own" \
            "committer identity (${existing_name} <${existing_mail}>);" \
            "leaving it exactly as found"
        return 0
    fi
    if [ -z "${existing_name}" ] &&
            ! "${GIT}" config --local user.name "${name}"; then
        die "${EX_IDENTITY}" "user.name could not be written into" \
            "this repository's own configuration.  The identity has to" \
            "live in the repository so it survives into the container," \
            "which mounts this checkout and carries no GIT_*" \
            "environment of its own; and a configuration that cannot" \
            "be written is a repository the commit itself would fail" \
            "in a moment later.  Nothing was committed."
    fi
    if [ -z "${existing_mail}" ] &&
            ! "${GIT}" config --local user.email "${mail}"; then
        die "${EX_IDENTITY}" "user.email could not be written into" \
            "this repository's own configuration.  Nothing was" \
            "committed."
    fi
    playthrough_log "recorded ${name} <${mail}> as this REPOSITORY's" \
        "committer identity (git config --local, never --global and" \
        "never --system) -- the same identity git already resolved, so" \
        "the attribution of the commit is unchanged and now travels" \
        "with the checkout into the container"
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
    playthrough_log "committing on branch ${BRANCH}"
    return 0
}

# ---------------------------------------------------------------------
# THE SCOPE GATE.
#
# A commit publishes the whole index, not the pathspecs this run added,
# so anything already staged outside playthrough/ would ride along
# inside a checkpoint that claims to be about the playthrough.  That is
# refused.  Unstaged and untracked changes outside it cannot ride along
# -- `git add` is given pathspecs and cannot reach past them -- so those
# are reported and left alone.
#
# .gitignore AND .gitattributes ARE DELIBERATELY OUT OF SCOPE.  The
# terminal `!/playthrough/**` negation and the `*.sav`/`*.mp4`/`*.zzip`
# binary attributes are load-bearing for this tree, and this file CHECKS
# both -- see assert_not_ignored -- but it does not commit either.  They
# are repository-wide configuration, they are edited by whoever owns
# that decision, and they belong in their own commit rather than inside
# a checkpoint whose subject is a survivor's save.
# ---------------------------------------------------------------------

# in_scope PATH -- true when a repository-relative path is one this file
# is allowed to commit.
in_scope() {
    local path="$1"
    case "${path}" in
        playthrough|playthrough/*) return 0 ;;
    esac
    return 1
}

# staged_out_of_scope -- every staged path this file may not commit, one
# per line.  -z is the only format that survives a path with a space, a
# quote or a newline in it; --diff-filter is deliberately absent so a
# staged deletion counts too.
staged_out_of_scope() {
    local path
    while IFS= read -r -d '' path; do
        if ! in_scope "${path}"; then
            printf '%s\n' "${path}"
        fi
    done < <("${GIT}" diff --cached --name-only -z HEAD --)
    return 0
}

assert_scope() {
    local staged=() path
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        staged+=("${path}")
    done < <(staged_out_of_scope)
    if [ "${#staged[@]}" -gt 0 ]; then
        die "${EX_SCOPE}" "the index already carries changes outside" \
            "$(rel "${PLAYTHROUGH_DIR}"): ${staged[*]}.  A commit" \
            "publishes the whole index, so those would be swept into a" \
            "checkpoint that says it is about the playthrough." \
            "Unstage them ('git restore --staged -- <path>') and commit" \
            "them separately -- .gitignore and .gitattributes in" \
            "particular are repository-wide configuration and are never" \
            "staged by this script.  Nothing was committed."
    fi
    return 0
}

report_foreign_worktree_changes() {
    local foreign=() vcs=() path status origin
    while IFS= read -r -d '' status; do
        path="${status:3}"
        case "${status}" in
            R*|C*)
                # Under -z a rename or copy emits its origin as a
                # second field, which must be consumed or it would be
                # read as the next entry's status.  The origin itself is
                # not reported: the destination is the path a reader
                # needs, and both are in scope or neither is.
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
            "This script checks that the terminal '!/playthrough/**'" \
            "negation still rescues the save data, and never commits" \
            "the file that carries it -- repository-wide configuration" \
            "belongs in its own commit.  Commit it separately."
    fi
    return 0
}

# ---------------------------------------------------------------------
# THE COMMITTED RULES, WHICH ARE A DIFFERENT QUESTION FROM THE WORKING
# TREE'S.
#
# assert_not_ignored asks `git check-ignore` about the files on disk,
# which is exactly the right question for "will the next `git add` skip
# the save".  It is the WRONG question for "will a fresh clone of this
# history still carry the save", and that second question is the one a
# reader of the repository actually asks.  A history whose terminal
# negation was only ever in somebody's working tree passes every
# check-ignore in this file and re-ignores the save data the moment
# anybody clones it.
#
# So HEAD's own copies are read.  The negation must be the LAST effective
# rule in the committed .gitignore, because git applies the last matching
# pattern; and the six attribute rows must be committed, because `* 
# text=auto` alone leaves the film, the save and the map archives to
# content detection.  This is a REFUSAL rather than a warning: a
# checkpoint taken over a history that does not carry these rules is a
# checkpoint whose evidence a clone will not have.
#
# The remedy is never "force the add".  .gitignore and .gitattributes are
# repository-wide configuration this script deliberately does not commit,
# so the fix is to commit them separately, first -- which is what
# report_foreign_worktree_changes above says when they are merely dirty.
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

# committed_lines PATH -- the file as HEAD carries it, with blank lines
# and comments dropped and surrounding whitespace collapsed, so a rule
# written with a tab is recognised as the rule it is.  Empty when HEAD
# does not carry the path at all.
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
        if ! printf '%s\n' "${attributes}" |
                "${GREP}" -Fqx -- "${row}"; then
            missing+=("${row}")
        fi
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
    playthrough_log "HEAD's own .gitignore ends with" \
        "'${IGNORE_NEGATION}' and its .gitattributes carries all" \
        "${#REQUIRED_ATTRIBUTES[@]} of this feature's rows, so a fresh" \
        "clone of this history keeps the save data and the binary" \
        "artifacts intact"
    return 0
}


# ---------------------------------------------------------------------
# THE HYGIENE GATE.
#
# .gitignore ends with a terminal `!/playthrough/**` negation, without
# which the engine's own `#<name>.sav` and `.log` files would be
# silently skipped by `git add`.  The negation is load-bearing and it
# has a consequence that is easy to forget: inside this one tree, the
# repository's ignores DO NOT APPLY.  __pycache__ is committable here.
# So is a *.pyc, an ad-hoc test file, and the retained or quarantined
# film embed_captions.sh leaves beside the published one.  None of them
# is evidence, and a checkpoint that archives them has to be undone by
# hand, so they are refused before anything is staged.
# ---------------------------------------------------------------------

# The names that must not be inside playthrough/ when a checkpoint is
# taken, as `find` predicates.  Each is derived from something that
# genuinely appears there: bytecode from running a test module without
# -B, an ad-hoc validation file, and the two names the caption mux uses
# around its atomic publication.
readonly -a HYGIENE_NAMES=(
    "__pycache__"
    "*.pyc"
    "*.pyo"
    "blitzy_adhoc_test_*"
    ".*.previous.mp4"
    ".*.rejected.mp4"
    "*.orig"
    "*.rej"
)

assert_no_machine_files() {
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
# THE PERSISTENCE GATE.  At creation there is exactly one live world and
# one live survivor.  At final there is either that same live shape
# (sleep + Save & Quit) OR the engine's death shape: the character save
# and log moved into graveyard/, one matching JSON/text memorial pair,
# and a captured last-words/post-death sequence in the manifest.
#
# `<userdir>/config/lastworld.json` is written by the engine when a
# world is loaded and carries the world name and the DECODED character
# name.  The save file carries the same name base64-encoded with '+' and
# '-' as the last two alphabet characters (src/catacharset.cpp:215), so
# the two can be held against each other -- which is what makes "this
# persistence belongs to the survivor the session was about" a checkable
# property rather than an assurance.  A missing live save with no full
# death generation is still a refusal.
#
# BOTH SPELLINGS OF THE CHARACTER SAVE ARE ACCEPTED.  game::save_player_
# data writes `playerfile + SAVE_EXTENSION + zzip_suffix` when the world
# has compression enabled and the plain `playerfile + SAVE_EXTENSION`
# when it does not (src/game_io.cpp:601-641, `zzip_suffix = ".zzip"` at
# src/worldfactory.h:25), and WORLD_COMPRESSION2 defaults to true.  So
# `#<b64>.sav` and `#<b64>.sav.zzip` are both the real name of a real
# save and neither form may be the one this gate insists on.  The
# character log is written through write_to_file either way and is
# therefore always plain.
#
# `.shortcuts` IS NEVER REQUIRED, ANYWHERE HERE.  SAVE_EXTENSION_
# SHORTCUTS exists (src/path_info.h:17) but its write sits inside
# `#if defined(__ANDROID__)` in game::save_player_data, so it is never
# produced on this host.  A gate that asked for it would refuse every
# legitimate Linux session.  This comment is the only mention of it in
# this file, on purpose.
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

# The decoder.  A fixed program with the path in argv, never
# interpolated into the source: an unvalidated path joined into a
# program string is exactly the pattern the repository's CodeQL python
# analysis exists to catch, and the rule holds for a program this file
# generates as much as for one it ships.
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
    # The .sav.zzip form is a zstd-framed archive that this reader
    # cannot open, so the two checks above were NOT performed.  That is
    # said out loud rather than reported as a pass; the memorial pair
    # and the captured death sequence below are unaffected and still
    # decide the outcome.
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
    elif [ "${checkpoint}" != "${CHECKPOINT_FINAL}" ]; then
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
        elif [ "${checkpoint}" = "${CHECKPOINT_FINAL}" ]; then
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
    elif [ "${checkpoint}" = "${CHECKPOINT_FINAL}" ]; then
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
# THE EVIDENCE GATE.  One keystroke, one capture, one row, one
# observation -- checked by counting all four, not by trusting that the
# session kept them in step.
#
# manifest.py owns the schema and the 1..n sequence and already knows how
# to prove every row's capture exists, so that check is DELEGATED to it
# rather than reimplemented here in a second, divergent form.  What this
# adds is the other direction: an EXTRA capture that no row accounts for
# would pass manifest.py's check and still break the invariant.
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
#
# The manifest is append-only, so the two things it cannot itself carry
# live beside it and are verified here rather than at the moment a
# reader happens to look:
#
#   * amendments.jsonl -- a correction names the sha256 of the exact
#     manifest line it corrects.  If that line has changed, the
#     amendment no longer describes it, and the resolution is REFUSED
#     rather than applied to whatever now occupies that row.  Committing
#     an unresolvable pair would publish a record whose own corrections
#     cannot be applied to it.
#
#   * build/frame_digests.jsonl -- every recorded frame's captured bytes.
#     A capture is verified by re-hashing the PNG on disk, which is the
#     only check in this pipeline that a same-sized, non-blank, correctly
#     named replacement image cannot pass.  Every structural check above
#     -- the count identity, the geometry, the luminance -- it passes
#     easily.
#
# Both run before stage_artifacts(), so a mismatch stops the checkpoint
# while the previous commit is still the last word.
# ---------------------------------------------------------------------

# The amendment half, separately, because it runs BEFORE the record gate.
# manifest.py's own `verify` resolves the ledger so that it can hold the
# published narration to the voice gate, which means a broken binding
# surfaces there too -- as "the record was refused", which is not the
# advice an operator needs.  Asking the ledger first keeps the specific
# diagnosis, and the specific remedy, in front of the general one.
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
#
# The survivor's first-person dossier is required to have been written
# BEFORE play and committed BEFORE the first gameplay frame, and that
# ordering is read straight out of the history: the dossier's first
# commit must be reachable from the commit carrying the first capture.
# The `creation` checkpoint is the commit that establishes it, so at
# `creation` a dossier that is missing -- or present but empty, which is
# the same absence with a file in the way -- is a refusal.
#
# `final` inherits the property from the history rather than re-deciding
# it, but it checks two things anyway: that the dossier is still there,
# because a deletion between the checkpoints would erase the evidence
# the ordering rests on, and that it is TRACKED, because a dossier that
# reached the working tree without ever reaching a commit would leave
# the ordering unprovable no matter what the file says.
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
    if [ "${checkpoint}" = "${CHECKPOINT_FINAL}" ] &&
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
# THE NOT-IGNORED GATE -- THE TRIPWIRE ON THE ONE FAILURE THAT REPORTS
# SUCCESS.
#
# `git add` SKIPS an ignored path and EXITS 0.  So the failure this
# whole feature is most exposed to is silent by construction: delete the
# terminal `!/playthrough/**` negation and the engine's own
# `#<b64>.sav`, `#<b64>.log` and `config/debug.log` go back to being
# matched by `\#*` (.gitignore:131), unanchored `*.log` (.gitignore:31)
# and `debug.log` (.gitignore:79) -- and every count in this script
# still tallies while the save is not in the repository at all.
#
# `git check-ignore` is the honest question, and it has to be asked the
# hard way (both traps measured on this checkout):
#
#   1. WITHOUT --no-index it CONSULTS THE INDEX and calls any TRACKED
#      path not-ignored whatever the rules say.  It is therefore vacuous
#      on a re-run and wrong exactly when it matters, because on a fresh
#      session the file is not yet tracked and `git add` applies the
#      patterns, not the index.
#   2. WITH -v it exits 0 whenever ANY pattern matched, INCLUDING the
#      negation -- printing `.gitignore:275:!/playthrough/**` when the
#      negation is present and `.gitignore:131:\#*` when it is not.
#
# So the verdict is taken from `--no-index --quiet`, which is the one
# form whose exit status answers "is this ignored?" (measured: 1 for the
# character save, 0 for obj/), and the `-v` line is read only to NAME
# the offending rule in the refusal.  This runs BEFORE anything is
# staged, so a lost negation stops the checkpoint while the previous
# commit is still the last word.
# ---------------------------------------------------------------------

# first_capture -- the lowest-numbered capture on disk, or nothing.  One
# frame is enough to prove the frames directory is not excluded, and
# asking about one keeps this gate O(1) in session length.
first_capture() {
    local path first=""
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        first="${path}"
        break
    done < <("${FIND}" "${PLAYTHROUGH_FRAMES_DIR}" -mindepth 1 \
        -maxdepth 1 -type f -name 'frame_*.png' -print 2>/dev/null |
        "${SORT}")
    if [ -z "${first}" ]; then
        return 1
    fi
    printf '%s' "${first}"
    return 0
}

# deciding_ignore_rule PATH -- the `source:line:pattern` git reports as
# the rule that decided, for the refusal message.  Read with the shell
# rather than through another tool, so this gate needs nothing beyond
# the toolchain already verified above.
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
#
# debug, debug_mode and debug_hour_timer ship with no `bindings` array
# (data/raw/keybindings.json:3398-3409, 3466-3471), so they are
# unreachable by any keystroke unless somebody deliberately binds them.
# User overrides live at <userdir>/config/keybindings.json, which is a
# COMMITTED artifact -- so this turns "no cheating" from an assurance
# into a property of a file a reader can check for themselves.  The
# engine writes that file only when a binding is changed; its absence is
# therefore the strongest form of the evidence, not a gap in it.
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

# creation_commit -- the newest commit on this branch carrying the
# creation trailer, or nothing.  git's --grep anchors ^ and $ at line
# boundaries within the message, so the trailer is matched as a whole
# line and a mention of it in prose is not.
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

# ---------------------------------------------------------------------
# WHICH SURVIVOR A COMMIT IS ABOUT.
#
# The trailer says a commit is a checkpoint; it does not say WHOSE.  That
# gap is not theoretical: a `final` checkpoint was accepted whose
# anchoring `creation` recorded a DIFFERENT survivor entirely, because
# the only lifecycle assertion was that the record had grown -- and a
# record re-recorded from scratch for a new survivor has "grown" by that
# measure too.  The history that leaves behind is one whose two lifecycle
# commits describe somebody whose files are no longer in the tree.
#
# The engine itself writes the answer.  config/lastworld.json names the
# world and character last loaded, it is a committed artifact, and so it
# can be read out of any commit's tree.  A fixed program on stdin, with
# no interpolation, so nothing a world or character name contains can
# reach the interpreter.
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

# creation_commit_for_survivor -- the newest creation checkpoint whose
# own tree names the survivor this run is about, or nothing.
#
# This is what makes the anchor SURVIVOR-SPECIFIC rather than merely
# newest, and it fixes the cause as well as the symptom: because
# do_creation refuses a second creation only when one exists FOR THIS
# SURVIVOR, a genuinely new survivor can now take a creation checkpoint
# of her own instead of being blocked by a previous recording's.
creation_commit_for_survivor() {
    local commit="" mine=""
    mine="$(loaded_survivor)"
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
                "playing her session.  Nothing was committed."
        fi
        die "${EX_LIFECYCLE}" "there is no '${CHECKPOINT_CREATION}'" \
            "checkpoint in this branch's history, so a" \
            "'${CHECKPOINT_FINAL}' one would be the single bundled" \
            "commit the requirement exists to rule out.  Take" \
            "'${CHECKPOINT_CREATION}' immediately after the survivor" \
            "is created, play the session, then take this one." \
            "Nothing was committed."
    fi
    local before
    before="$("${GIT}" show \
        "${CREATION_COMMIT}:playthrough/manifest.jsonl" 2>/dev/null |
        "${WC}" -l | "${TR}" -d ' ' || printf '')"
    case "${before}" in
        ''|*[!0-9]*)
            die "${EX_LIFECYCLE}" "the" \
                "'${CHECKPOINT_CREATION}' checkpoint" \
                "${CREATION_COMMIT} carries no readable manifest, so" \
                "there is nothing to measure this session's progress" \
                "against.  Nothing was committed."
            ;;
    esac
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

# stageable PATH -- true when `git add` can be given this path: it
# exists on disk, or it is tracked and therefore has a REMOVAL to
# record.  A pathspec matching neither is a hard `git add` error, and a
# checkpoint must not fall over because an optional artifact has not
# been written yet -- playthrough/README.md before somebody writes it, a
# graveyard before a death, an amendment ledger in a session that needed
# no corrections.
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

# stage_batch LABEL PATH... -- stage one artifact class in bounded
# chunks.
#
# `git add --` with NO -A, NO -f and NO shell glob.  Since git 2.0 a
# pathspec add records deletions as well as additions and modifications,
# so -A would add nothing here except the appearance of a blanket add
# (measured on git 2.51: `git add -- <dir>` staged a D, an M and an A in
# one call).  -f is refused on principle: if a path needed forcing, the
# .gitignore negation is wrong and that is a bug to fix in .gitignore,
# not to paper over here.
stage_batch() {
    local label="$1"
    shift
    local -a present=() chunk=() absent=()
    local path
    for path in "$@"; do
        if stageable "${path}"; then
            present+=("${path}")
        else
            absent+=("$(rel "${path}")")
        fi
    done
    # WHICH NAMED PATHS WERE NOT THERE, SAID OUT LOUD.  stageable()
    # skipping an absent path is deliberate -- a checkpoint must not fall
    # over because an optional artifact has not been written -- but the
    # skip used to be entirely silent, so a MANDATED artifact that had
    # never been written (playthrough/README.md was exactly this) was
    # omitted from every commit with nothing in the log to show it.
    # Reported rather than refused, because which of these classes are
    # optional is a judgement this function is the wrong place to make;
    # what it can do is make the omission visible.
    if [ "${#absent[@]}" -gt 0 ]; then
        playthrough_log "not staging ${#absent[@]} named path(s) in" \
            "the ${label} because they are neither on disk nor" \
            "tracked: ${absent[*]}"
    fi
    if [ "${#present[@]}" -eq 0 ]; then
        playthrough_log "no ${label} to stage"
        return 0
    fi
    for path in "${present[@]}"; do
        chunk+=("${path}")
        if [ "${#chunk[@]}" -ge "${STAGE_BATCH_SIZE}" ]; then
            if ! "${GIT}" add -- "${chunk[@]}"; then
                die "${EX_COMMIT}" "git could not stage the ${label}." \
                    "This run committed nothing."
            fi
            chunk=()
        fi
    done
    if [ "${#chunk[@]}" -gt 0 ]; then
        if ! "${GIT}" add -- "${chunk[@]}"; then
            die "${EX_COMMIT}" "git could not stage the ${label}." \
                "This run committed nothing."
        fi
    fi
    playthrough_log "staged the ${label}: ${#present[@]} path(s)"
    return 0
}

# stage_captures -- the one class big enough to need real batching.
#
# The list is built by `find -print0` and read NUL-delimited, because a
# shell glob over several thousand frames is exactly the "batching" that
# has an argument-list limit to respect.  A capture that git tracks and
# the filesystem no longer has is added to the list too, so a removal is
# recorded as a removal instead of being left in the index as a ghost --
# not that any capture may ever be removed: no decimation, no sampling,
# no deduplication.  The point is that if one ever went missing, the
# checkpoint would show it rather than hide it.
stage_captures() {
    local -a captures=()
    local path
    while IFS= read -r -d '' path; do
        captures+=("${path}")
    done < <("${FIND}" "${PLAYTHROUGH_FRAMES_DIR}" -mindepth 1 \
        -maxdepth 1 -type f -name 'frame_*.png' -print0 2>/dev/null)
    while IFS= read -r -d '' path; do
        [ -n "${path}" ] || continue
        if [ ! -e "${path}" ]; then
            captures+=("${path}")
        fi
    done < <("${GIT}" ls-files -z -- "${PLAYTHROUGH_FRAMES_DIR}" \
        2>/dev/null)
    if [ "${#captures[@]}" -eq 0 ]; then
        playthrough_log "no captures to stage"
        return 0
    fi
    stage_batch "captured frames" "${captures[@]}"
    return 0
}

# stage_artifacts -- every artifact class, named, one batch each.
#
# THE ORDER IS THE FEATURE'S OWN ORDER, and the list is exhaustive over
# playthrough/ by design; assert_tree_fully_staged immediately below
# proves that exhaustiveness instead of assuming it.
stage_artifacts() {
    # 1. The authored tooling, including requirements.txt -- the
    #    dependency declaration the requirement wants kept out of the
    #    game's source tree.
    stage_batch "pipeline tooling" "${PLAYTHROUGH_TOOLING_DIR}"
    # 2. The narrative record: the dossier written before play, the
    #    transcript, the engineering notes, the feature readme.
    stage_batch "narrative and documentation" \
        "${PLAYTHROUGH_DOSSIER}" \
        "${PLAYTHROUGH_DIR}/README.md" \
        "${PLAYTHROUGH_TECH_NOTES}" \
        "${PLAYTHROUGH_TRANSCRIPT_MD}" \
        "${PLAYTHROUGH_TRANSCRIPT_SRT}"
    # 3. The engine's own tree -- save, config, achievements, memorial,
    #    graveyard, templates, cache.  Authored by the game, committed
    #    here, never edited by this pipeline.
    stage_batch "engine save and configuration" "${PLAYTHROUGH_USERDIR}"
    # 4. The captures.
    stage_captures
    # 5. The record and its ledgers.
    stage_batch "record and timeline" \
        "${PLAYTHROUGH_MANIFEST}" \
        "${PLAYTHROUGH_TIMELINE}" \
        "${PLAYTHROUGH_AMENDMENTS}"
    # 6. The render intermediates, which include the observation
    #    sidecar, the capture attestations and the concat list.
    stage_batch "build intermediates" "${PLAYTHROUGH_BUILD_DIR}"
    # 7. The films.
    stage_batch "assembled film" \
        "${PLAYTHROUGH_MOVIE}" \
        "${PLAYTHROUGH_MOVIE_CC}"
    # Hygiene before completeness, so the SPECIFIC diagnosis -- this is
    # bytecode, this is outside the feature -- reaches the operator
    # ahead of the general one, which would otherwise report the same
    # path as merely "not staged".
    assert_index_hygiene
    assert_tree_fully_staged
    return 0
}

# assert_tree_fully_staged -- the completeness half of explicit staging.
#
# A named list of classes can omit one somebody adds later, and the
# omission would be silent: every other check would pass while a new
# artifact sat uncommitted.  So the index is held against the tree.
# Under --porcelain -z each entry is XY<space>path; Y is the WORKTREE
# column, so anything other than a space there is an unstaged change and
# '??' is an untracked file.  Either means a batch above did not reach
# it.
#
# --ignored=matching IS PART OF THE SWEEP, and it closes the last silent
# gap in the whole staging path.  A directory pathspec add SKIPS an
# ignored file without complaining (an explicit file pathspec errors, and
# that difference is why the captures are staged by name), and an ignored
# file is invisible to a plain porcelain status -- so a rule that landed
# AFTER the terminal negation and re-excluded one path inside this tree
# would otherwise be committed around in perfect silence.  Asking for the
# ignored entries turns that into its own refusal.
assert_tree_fully_staged() {
    local -a pending=() ignored=()
    local entry xy path origin=""
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
            ignored+=("${path}")
        elif [ "${xy}" = "??" ] || [ "${xy:1:1}" != " " ]; then
            pending+=("${path}")
        fi
    done < <("${GIT}" status --porcelain -z --untracked-files=all \
        --ignored=matching -- "${PATHSPECS[@]}")
    if [ "${#ignored[@]}" -gt 0 ]; then
        die "${EX_SCOPE}" "${#ignored[@]} path(s) inside" \
            "$(rel "${PLAYTHROUGH_DIR}") are IGNORED by git and would" \
            "be committed around in silence: ${ignored[*]}.  Nothing in" \
            "this tree may be excluded -- the terminal" \
            "'!/playthrough/**' negation exists to make sure of it, and" \
            "a rule placed AFTER it re-excludes whatever it matches." \
            "Fix .gitignore so the negation is the last matching rule." \
            "Nothing was committed."
    fi
    if [ "${#pending[@]}" -gt 0 ]; then
        die "${EX_COMMIT}" "${#pending[@]} path(s) under" \
            "$(rel "${PLAYTHROUGH_DIR}") are still not staged after" \
            "every artifact class was staged: ${pending[*]}." \
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
#
# assert_no_machine_files already refuses a checkpoint while bytecode is
# on disk, and this asks the complementary question: whatever is about
# to be published, is any of it a machine artifact or outside this
# feature?  It catches what the filesystem sweep cannot -- a *.pyc
# written between that sweep and this moment, or a path an interrupted
# earlier run left in the index -- and it is the check that has to pass
# for `git commit` to be reached.
assert_index_hygiene() {
    local -a bytecode=() outside=()
    local path
    while IFS= read -r -d '' path; do
        if ! in_scope "${path}"; then
            outside+=("${path}")
            continue
        fi
        case "${path}" in
            *__pycache__*|*.pyc|*.pyo) bytecode+=("${path}") ;;
        esac
    done < <("${GIT}" diff --cached --name-only -z HEAD --)
    if [ "${#bytecode[@]}" -gt 0 ]; then
        die "${EX_SCOPE}" "the index carries interpreter bytecode:" \
            "${bytecode[*]}.  Inside this one tree .gitignore's" \
            "terminal '!/playthrough/**' negation RE-INCLUDES" \
            "__pycache__ and *.pyc, so bytecode is committable here" \
            "and nothing but this check stops it being archived as" \
            "though it were evidence.  Remove it (test modules run" \
            "with 'python -B', and env.sh exports" \
            "PYTHONDONTWRITEBYTECODE=1) and run this again.  Nothing" \
            "was committed."
    fi
    if [ "${#outside[@]}" -gt 0 ]; then
        die "${EX_SCOPE}" "the index carries ${#outside[@]} path(s)" \
            "outside $(rel "${PLAYTHROUGH_DIR}"): ${outside[*]}.  A" \
            "commit publishes the whole index, so a checkpoint about" \
            "the playthrough would carry them.  Unstage them and" \
            "commit them separately.  Nothing was committed."
    fi
    return 0
}

# staged_paths -- the repository-relative paths currently staged against
# HEAD, one per line.
staged_paths() {
    "${GIT}" diff --cached --name-only HEAD -- "${PATHSPECS[@]}" \
        2>/dev/null || printf ''
}

# staged_classes -- one line per artifact class present in the index,
# for the commit body.
#
# The body is generated from what was ACTUALLY staged rather than
# written from a template, so a checkpoint cannot claim to carry
# something that is not in it.  That is the same rule the transcript is
# held to, applied to the commit message.
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

# commit_checkpoint NAME SUBJECT
#   Take the commit, or report that there was nothing to take.
#
#   AN EMPTY COMMIT IS NEVER MANUFACTURED.  A re-run over an unchanged
#   tree exits 0 having done nothing, which is what makes this step safe
#   to repeat: the alternative -- an empty commit per invocation -- would
#   fill the history with checkpoints that record no change and make the
#   trailer search ambiguous.
COMMITTED="no"
COMMIT_HASH=""

commit_checkpoint() {
    local name="$1" subject="$2"
    local -a body=()
    local class
    if [ -z "$(staged_paths)" ]; then
        playthrough_warn "nothing to commit for the '${name}'" \
            "checkpoint: every path this step stages is already" \
            "recorded at HEAD.  No empty commit was manufactured."
        COMMITTED="no"
        COMMIT_HASH=""
        return 0
    fi
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
    message+=("-m" "${TRAILER_KEY}: ${name}")
    if ! "${GIT}" commit --quiet "${message[@]}"; then
        die "${EX_COMMIT}" "git refused the '${name}' checkpoint" \
            "commit.  The index is left staged so the failure can be" \
            "inspected; nothing was rewritten."
    fi
    if ! COMMIT_HASH="$("${GIT}" rev-parse HEAD 2>/dev/null)"; then
        die "${EX_COMMIT}" "the '${name}' checkpoint commit was made" \
            "but its hash could not be read back, so it cannot be" \
            "verified."
    fi
    COMMITTED="yes"
    playthrough_log "committed the '${name}' checkpoint as" \
        "${COMMIT_HASH}"
    return 0
}

# ---------------------------------------------------------------------
# VERIFYING WHAT WAS PUBLISHED.  Every claim this file makes about the
# commit it just took is read back out of git rather than assumed from
# the fact that the commit command succeeded.
# ---------------------------------------------------------------------

# verify_attribution_and_trailer NAME -- the two properties EVERY
# checkpoint has, whatever else it carries.  Shared, so the dossier
# commit is held to the same attribution rule as the other two rather
# than to a looser one written beside it.
verify_attribution_and_trailer() {
    local name="$1"
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
    if ! printf '%s' "${message}" |
            "${GREP}" -Fqx -- "${TRAILER_KEY}: ${name}"; then
        die "${EX_COMMIT}" "the commit does not carry the" \
            "'${TRAILER_KEY}: ${name}' trailer, so the lifecycle" \
            "cannot find it again.  The commit exists; its place in" \
            "the lifecycle does not."
    fi
    return 0
}

# ---------------------------------------------------------------------
# WHAT THE `final` CHECKPOINT MUST HAVE RECORDED, AND WHY THIS IS HERE
# RATHER THAN ONLY IN THE GATE.
#
# The acceptance gate reads the finished history and asserts, among other
# things, that at least two commits touch the userdir and that the
# dossier's introducing commit precedes the first capture's.  This step
# used to assert NEITHER, so it could certify a checkpoint the gate would
# then reject -- and the operator would learn about it one stage later,
# from a different tool, with the commit already taken.  A committer whose
# self-verification is weaker than the gate that follows it is a committer
# that hands over work it knows nothing about.
#
# So both properties are checked HERE too, immediately after the commit
# and before this step claims success.
# ---------------------------------------------------------------------

# commit_touched COMMIT PATHSPEC -- the paths that commit recorded under
# PATHSPEC, or nothing.  diff-tree against the first parent, which is
# what "this commit changed" means for a linear history.
commit_touched() {
    "${GIT}" diff-tree --no-commit-id --name-only -r "$1" -- "$2" \
        2>/dev/null || printf ''
}

# introducing_commit PATH -- the oldest commit that touched PATH.
introducing_commit() {
    "${GIT}" log --format=%H -- "$1" 2>/dev/null |
        "${TR}" -d '\r' | tail -n 1 || printf ''
}

# assert_staged_records_the_save -- the same property as
# assert_final_recorded_the_save, asserted BEFORE the commit instead of
# after it.
#
# Both exist deliberately.  The post-commit form is the certification
# that matches the acceptance gate; on its own, though, it can only
# report a bad commit that has already been taken, which leaves the
# operator to undo history this script is otherwise careful never to
# touch.  Read off the INDEX the answer is available a moment earlier,
# while refusing still costs nothing.
#
# It fires only when a commit is actually going to be made.  A `final`
# re-run over an unchanged tree stages nothing, commit_checkpoint makes
# no empty commit, and there is no claim to check.
assert_staged_records_the_save() {
    if [ -z "$(staged_paths)" ]; then
        return 0
    fi
    # Named for the userdir rather than "staged": staged_out_of_scope
    # already uses `staged` as a local ARRAY, and shellcheck reads one
    # name used both ways across this file as SC2178/SC2128.
    local staged_save=""
    staged_save="$("${GIT}" diff --cached --name-only HEAD -- \
        "${PLAYTHROUGH_USERDIR}" 2>/dev/null || printf '')"
    if [ -n "${staged_save}" ]; then
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
        "take this checkpoint.  NOTHING WAS COMMITTED; the index is" \
        "left staged so what would have been recorded can be inspected" \
        "with 'git diff --cached', and nothing was rewritten."
}

assert_final_recorded_the_save() {
    local touched=""
    touched="$(commit_touched HEAD "${PLAYTHROUGH_USERDIR}")"
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
            "take this checkpoint."
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
    dossier="$(introducing_commit "${PLAYTHROUGH_DOSSIER}")"
    if ! capture="$(first_capture)"; then
        return 0
    fi
    frame="$(introducing_commit "${capture}")"
    if [ -z "${dossier}" ] || [ -z "${frame}" ]; then
        die "${EX_COMMIT}" "the dossier's introducing commit is" \
            "'${dossier:-none}' and the first capture's is" \
            "'${frame:-none}', so the ordering the requirement asks" \
            "for cannot be read out of this history at all."
    fi
    if [ "${dossier}" = "${frame}" ]; then
        die "${EX_COMMIT}" "${dossier:0:10} introduced BOTH" \
            "$(rel "${PLAYTHROUGH_DOSSIER}") and $(rel "${capture}")," \
            "so 'the dossier was written before the first gameplay" \
            "frame' is unprovable from this history -- one commit" \
            "cannot precede itself.  Commit the dossier on its own" \
            "first ('commit_artifacts.sh ${CHECKPOINT_DOSSIER}'), then" \
            "'${CHECKPOINT_CREATION}', then this one."
    fi
    if ! "${GIT}" merge-base --is-ancestor "${dossier}" "${frame}" \
            2>/dev/null; then
        die "${EX_COMMIT}" "${dossier:0:10} introduced the dossier and" \
            "${frame:0:10} introduced the first capture, and" \
            "${dossier:0:10} is not an ancestor of it.  The" \
            "requirement is an ORDER, and on separate branches neither" \
            "commit precedes the other."
    fi
    playthrough_log "the dossier's introducing commit" \
        "${dossier:0:10} is a strict ancestor of the first capture's" \
        "${frame:0:10}, so the before-play ordering is provable from" \
        "this history"
    return 0
}

verify_commit() {
    local name="$1"
    verify_attribution_and_trailer "${name}"
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
    # The two properties the acceptance gate will look for next, asserted
    # here so this step cannot certify what that one rejects.
    if [ "${name}" = "${CHECKPOINT_FINAL}" ]; then
        assert_final_recorded_the_save
        assert_dossier_precedes_captures
    fi
    playthrough_log "the checkpoint is verified: attribution," \
        "trailer, a clean tree and every artifact class tracked"
    return 0
}

# verify_dossier_commit -- the narrower verification the FIRST commit of
# the lifecycle can actually satisfy.
#
# It deliberately does NOT assert a clean tree or the tracked artifact
# classes, and the reason is the point of the commit: at this moment the
# session has not been played, so the captures, the record, the timeline
# and the films do not exist and the rest of playthrough/ is legitimately
# uncommitted.  Demanding the `final` checkpoint's conditions here would
# make the first step of the lifecycle impossible to take, which is the
# shape of the defect this whole subcommand exists to remove.
verify_dossier_commit() {
    verify_attribution_and_trailer "${CHECKPOINT_DOSSIER}"
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

# assert_tracked_at_head -- prove the four artifact classes the
# requirement names are in the index, by asking git rather than by
# looking at the filesystem.  This is the check that would have caught
# the .gitignore trap: without the terminal negation, `git add` skips
# the character save and reports success, so the only way to know it is
# tracked is to ask for it by name.
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
#
# `creation` and `final` run the SAME gates in the same order, and differ
# only in the lifecycle assertions `final` adds.  Keeping that gate list
# identical is deliberate: a checkpoint with a weaker gate is a
# checkpoint somebody takes when the other one refuses.
#
# `dossier` is the exception, and deliberately so rather than by
# oversight: it is taken BEFORE the session is played, when there is no
# manifest, no capture, no timeline and no film, so the finished-session
# evidence gates would refuse a perfectly correct dossier commit.  Its
# own gate set is spelled out at do_dossier, and it is narrower in
# exactly one direction -- it asserts everything that can be true this
# early, plus one thing the other two cannot: that no capture is tracked
# yet.
# ---------------------------------------------------------------------

run_common_gates() {
    local checkpoint="$1"
    assert_identity
    assert_repository
    # After the repository is the one we expect, and before anything is
    # staged: record the resolved identity in THIS repository's own
    # configuration, so the attribution survives into the container that
    # mounts this checkout and carries no GIT_* of its own.
    persist_identity_locally
    assert_scope
    report_foreign_worktree_changes
    assert_committed_vcs_rules
    assert_no_machine_files
    assert_save_tree "${checkpoint}"
    assert_evidence
    assert_dossier "${checkpoint}"
    # After the save and the record are known, and before anything is
    # staged: the paths this checkpoint exists to preserve must not be
    # ones `git add` would silently skip.
    assert_not_ignored
    assert_no_debug_bindings
    return 0
}

# ---------------------------------------------------------------------
# THE DOSSIER CHECKPOINT -- the first of the three, and the one that
# makes the other two provable.
#
# Its gate set is deliberately its own rather than run_common_gates:
# at this moment the session has NOT been played, so there is no
# manifest, no capture, no timeline and no film, and every evidence gate
# written for a finished session would refuse a perfectly correct dossier
# commit.  What IS asserted is everything that can be true this early --
# the identity, the repository, the scope, the committed ignore rules --
# plus the two properties specific to this step: the dossier exists and
# is not empty, and NO CAPTURE IS TRACKED YET.
#
# That last one is the whole point.  "Before the first gameplay frame" is
# a statement about ORDER, and the only moment at which this commit can
# establish it is before any frame is in the history.  Taken afterwards it
# would be a commit of the same file that proves nothing, so it is
# refused rather than allowed to look like it worked.
# ---------------------------------------------------------------------
# tracked_capture_count -- how many captures git has in the index.
#
# `wc -l` rather than `grep -c .`, and the difference is not cosmetic:
# `grep -c .` on empty input PRINTS "0" and EXITS 1, so a `|| printf 0`
# fallback fires as well and the substitution comes back as two lines.
# Emitted into the KEY=value block that made a stray bare "0" line of its
# own and broke the contract stdout is held to.  wc -l always exits 0 and
# always prints exactly one number, which is why the rest of this file
# already counts that way.
tracked_capture_count() {
    "${GIT}" ls-files -- "${PLAYTHROUGH_FRAMES_DIR}" 2>/dev/null |
        "${WC}" -l | "${TR}" -d ' '
}

do_dossier() {
    assert_identity
    assert_repository
    persist_identity_locally
    assert_scope
    report_foreign_worktree_changes
    assert_committed_vcs_rules
    assert_no_machine_files
    # Existence and substance only: the tracked-at-HEAD half of
    # assert_dossier is what THIS commit is about to establish.
    assert_dossier "${CHECKPOINT_DOSSIER}"
    local tracked=0
    tracked="$(tracked_capture_count)"
    if [ "${tracked}" -gt 0 ]; then
        die "${EX_LIFECYCLE}" "${tracked} capture(s) are already" \
            "tracked, so a '${CHECKPOINT_DOSSIER}' checkpoint taken" \
            "now could not put the dossier ahead of the first gameplay" \
            "frame -- and putting it ahead of them is the only thing" \
            "this checkpoint does.  It belongs immediately after the" \
            "dossier is written and before the session is played." \
            "Nothing was committed."
    fi
    if "${GIT}" ls-files --error-unmatch -- "${PLAYTHROUGH_DOSSIER}" \
            >/dev/null 2>&1 &&
            [ -z "$(commit_touched HEAD "${PLAYTHROUGH_DOSSIER}")" ] &&
            [ -z "$("${GIT}" status --porcelain -- \
                "${PLAYTHROUGH_DOSSIER}" 2>/dev/null)" ]; then
        playthrough_log "$(rel "${PLAYTHROUGH_DOSSIER}") is already" \
            "tracked and unchanged, and no capture is tracked yet, so" \
            "the ordering this checkpoint establishes is already in" \
            "the history"
    fi
    # ONE path, by name.  A dossier commit that also swept up the tooling
    # or the notes would be the bundled commit this step exists to split.
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
    # THE DOSSIER MUST ALREADY BE IN THE HISTORY.  This checkpoint stages
    # the captures, so if the dossier arrived in the same commit the two
    # would share an introducing commit and the before-play ordering
    # would be permanently unprovable -- which is exactly what happened
    # while the narrative class and the captures were staged together.
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
    # A `creation` checkpoint taken when one already exists FOR THIS
    # SURVIVOR is either a re-run over an unchanged tree -- which
    # commit_checkpoint handles by doing nothing -- or a second creation
    # for one survivor, which would make the trailer search ambiguous for
    # every later `final`.
    #
    # SURVIVOR-SCOPED, and that is the fix rather than a nicety: the
    # unscoped form refused a NEW survivor's creation checkpoint whenever
    # ANY previous recording had one, which is precisely why a
    # re-recorded session ended up with no checkpoint of its own and the
    # history's lifecycle commits described somebody else.
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

# staged_paths_preview -- what a checkpoint WOULD add, without touching
# the index.  --dry-run makes `git add` report and change nothing, which
# is the only honest way to ask this question before deciding whether
# staging is allowed at all.  The lines are git's own "add '<path>'"
# form rather than bare paths; every caller here treats them as a report,
# not as a path list.
#
# One pathspec, no -A, and only a REPORT: this is the one place a whole
# subtree is named in a single `git add`, and it is the place where doing
# so cannot change anything.
staged_paths_preview() {
    "${GIT}" add --dry-run -- "${PATHSPECS[@]}" 2>/dev/null ||
        printf ''
}

# has_pending_changes -- true when a checkpoint would record anything.
#
# BOTH halves are needed.  --dry-run answers for the WORKING TREE and
# says nothing about work a previous interrupted run already staged;
# diff --cached answers for the INDEX and says nothing about a file that
# has not been added yet.  Asking only one of them would let a second
# creation checkpoint through on the other one's blind spot.
has_pending_changes() {
    if [ -n "$(staged_paths_preview)" ]; then
        return 0
    fi
    if [ -n "$(staged_paths)" ]; then
        return 0
    fi
    return 1
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
    local pending creation
    pending="$(staged_paths_preview)"
    creation="$(creation_commit)"
    if [ -n "${pending}" ]; then
        playthrough_log "a checkpoint would stage:"
        printf '%s\n' "${pending}" >&2
    else
        playthrough_log "a checkpoint would stage nothing; every path" \
            "is already recorded at HEAD"
    fi
    if [ -n "${creation}" ]; then
        playthrough_log "the '${CHECKPOINT_CREATION}' checkpoint is" \
            "${creation}"
    else
        playthrough_log "there is no '${CHECKPOINT_CREATION}'" \
            "checkpoint yet, so '${CHECKPOINT_FINAL}' would refuse"
    fi
    # The evidence gates report here instead of dying, because `status`
    # exists to be run when something is wrong.
    local world="" character="" rows="" frames=""
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
    # WHOSE creation checkpoint that is, which is a different question
    # from whether one exists.  A `final` anchors to the creation of THE
    # SURVIVOR IT IS ABOUT, so a history whose newest creation names
    # somebody else is a history in which `final` will refuse -- and an
    # operator running `status` to find out why deserves to be told that
    # here rather than from the refusal.
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
                "playing her session."
        fi
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
        printf '  %-9s %s\n' \
            "dossier" "commit the survivor's dossier alone, BEFORE the \
first frame" \
            "creation" "commit the survivor and the save she starts \
from" \
            "final" "commit the closed session and its artifacts" \
            "status" "report the lifecycle, changing nothing" \
            "help" "this text"
        printf '%s\n' ""
        printf '%s\n' "THE THREE MUTATING STEPS ARE ORDERED AND EACH \
REFUSES TO RUN OUT OF TURN:"
        printf '%s\n' "  dossier -> creation -> play the session -> \
final."
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
        printf '%s\n' "It stages playthrough/ and nothing else, by \
artifact class, in bounded"
        printf '%s\n' "batches -- never a blanket add, never -A, never \
-f, never a shell glob."
        printf '%s\n' ".gitignore and .gitattributes are CHECKED here \
-- in the working tree AND"
        printf '%s\n' "as HEAD carries them -- and committed elsewhere."
        printf '%s\n' "It records the identity git already resolves in \
THIS repository's own"
        printf '%s\n' "configuration (git config --local, never \
--global and never --system), so"
        printf '%s\n' "the attribution travels with the checkout into \
the container.  It never"
        printf '%s\n' "invents an identity, never rewrites history and \
never pushes."
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
# take_checkpoint_lock -- serialise the MUTATING subcommands against
# another run over the same working tree.
#
# Two checkpoints running at once share one index and one HEAD, and the
# loser of that race did not merely fail: it reported "Nothing was
# committed" while the other process was committing, which is a
# diagnosis that describes the wrong repository state.  The lock removes
# the race, and its name carries a digest of this checkout so a run over a
# DIFFERENT tree is not serialised against this one -- a bare name would
# block two runs that share nothing, because the lock directory is derived
# from CLONE_INDEX rather than from the working tree.
#
# `status` deliberately does NOT take it: it only reads, and a read that
# blocks behind a commit is a reporting tool that stops working exactly
# when an operator needs it.
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
    # THE SCOPE IS NAMED BY THE DIGEST, NOT BY THE PATH.  Every message
    # this script emits goes through playthrough_redact, which rewrites
    # the repository root to '.' so host paths stay out of the logs -- so
    # "the checkout at ${PLAYTHROUGH_REPO_ROOT}" renders as "the checkout
    # at .", which tells an operator nothing.  The digest already in the
    # lock name IS the scope, and quoting it says which lock to look for
    # and simultaneously why a different tree does not contend for it.
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
        status)
            do_status
            ;;
        '')
            usage 2
            die "${EX_USAGE}" "which checkpoint?  There is no default:" \
                "the three commits mean different things, they are" \
                "taken at three different moments of the session, and" \
                "choosing the wrong one is not something a default can" \
                "be right about."
            ;;
        *)
            usage 2
            die "${EX_USAGE}" "unknown subcommand '${subcommand}'"
            ;;
    esac
    return "${EX_OK}"
}

main "$@"

