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
# HOW THE CONTAINER GETS AN IDENTITY WITHOUT ONE BEING WRITTEN
# The render and capture stages run inside the declared container, which
# mounts this checkout, sets its own HOME and forwards no GIT_* -- so an
# identity living only in the invoking user's ~/.gitconfig does not exist
# in there, and a checkpoint taken inside it used to exit 3.  This file
# answered that by writing `git config --local user.name` / `user.email`.
# It no longer does: the write contradicted the paragraph above it, this
# execution environment forbids running those commands at any scope, and
# writing the HOST-resolved pair bought no invariance that forwarding it
# does not.  supported_env.sh forwards the resolved GIT_AUTHOR_* /
# GIT_COMMITTER_* pair as environment instead, which is git's own
# mechanism for this and leaves nothing behind in the tree.  See
# report_identity_scope, which reads which scope answered and says so
# without changing it.
#
# STAGING IS EXPLICIT, BY ARTIFACT CLASS, AND BATCHED.  No blanket add
# appears anywhere in this file: every staging call is `add --` with
# named paths, never -A, never a bare '.', never -f, never a shell-
# expanded glob.  Each class -- the tooling, the narrative, the userdir,
# the captures, the record, the build intermediates, the films -- is
# named and staged on its own, and `git add --` without -A is enough
# because since git 2.0 a pathspec add records deletions as well as
# additions (measured on git 2.51: `git add -- <dir>` staged a D, an M
# and an A in one call).
#
# THE CAPTURES ARE STREAMED, NEVER ACCUMULATED.  One capture per
# keystroke and a deliberately unbounded session length mean the capture
# population is the one list in this file that must never become a shell
# array: it used to be read into one by `find -print0`, COPIED into a
# second inside the batcher, and only then handed to git in chunks of
# ${STAGE_BATCH_SIZE}.  The argv was bounded; the two arrays before it
# were not.  So a path is now read, judged and written out one at a time
# into a NUL-delimited PATHSPEC FILE in the mode-0700 runtime directory,
# and git is given that file with `--pathspec-from-file=<file>
# --pathspec-file-nul`: ONE `git add`, and therefore one index read and
# one index write, however long the session was.  On a git too old for
# that option (it arrived in 2.25) the same file is replayed in chunks of
# ${STAGE_BATCH_SIZE} into a bounded argv array, which is the previous
# behaviour minus the accumulation.  Nothing proportional to the session
# is ever resident.
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
# `status` adds six more, which together are the answer to "would this
# checkpoint be taken?" asked without taking it -- and asked, above all,
# by a caller that is about to spend an hour producing what a checkpoint
# would carry.  There is one triple per checkpoint an automated caller
# takes, because they ask different questions and a caller must read the
# triple for the checkpoint IT takes:
#
#     CREATION_SURVIVOR  the survivor the NEWEST creation records
#     FINAL_ANCHOR       the creation checkpoint `final` would actually
#                        anchor to: the newest one recording THIS
#                        survivor, which may be an older commit than the
#                        newest one.  Empty when there is none.
#     FINAL_ELIGIBLE     yes | no
#     FINAL_REASON       empty when eligible; otherwise one stable token
#                        -- no-survivor-loaded, no-record,
#                        no-creation-checkpoint,
#                        no-creation-for-this-survivor,
#                        anchor-carries-no-record, record-has-not-grown
#     MEDIA_ANCHOR       the `final` commit `media` would be about: the
#                        one that published THIS survivor's closed
#                        session.  Empty when there is none.
#     MEDIA_ELIGIBLE     yes | no
#     MEDIA_REASON       empty when eligible; otherwise no-final-published
#                        or whichever FINAL_REASON token explains why no
#                        anchor could be resolved at all
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

# THE ONE FILE THIS SCRIPT WRITES OUTSIDE THE INDEX, and it is removed on
# every exit path including a refusal.  It carries the NUL-delimited
# pathspecs one staging call is about -- see STAGING IS EXPLICIT below --
# and it lives in the mode-0700 runtime directory env.sh created, never in
# the working tree, because a stray file under playthrough/ would itself
# be an unstaged artifact the completeness sweep would refuse.
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
    # Releases only what this process took.  A checkpoint the sequencer
    # started inherited the sequencer's hold and leaves it in place.
    #
    # GUARDED ON THE HELPER'S EXISTENCE, because this trap is registered
    # ABOVE the line that sources env.sh -- deliberately, so that a
    # failure to find env.sh still cleans up -- and an unguarded call
    # would print "command not found" over the top of the FATAL line that
    # actually explains why the run stopped.
    if command -v playthrough_release_mutation_lock >/dev/null 2>&1; then
        playthrough_release_mutation_lock || true
    fi
}
trap _ca_cleanup EXIT

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
    # THE MESSAGE IS ESCAPED, because some of what reaches it is
    # chosen elsewhere -- a world name, a directory name, an
    # environment variable -- and a diagnostic that printed those
    # bytes raw would perform the injection it is reporting: a
    # newline forges a whole extra line of output, and ESC-[ or the
    # single-byte C1 CSI repaints the terminal of whoever is
    # reading the run.  playthrough_escape_controls is env.sh's,
    # sourced far above this definition.
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
#
# Every population this file diagnoses is the session's size, so the names
# in a refusal are a bounded sample while the count is exact.  Saying so
# explicitly is the point: "8 of 12,043" is a diagnosis, whereas eight
# names presented as if they were all of them is a misleading one.
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
# cat copies the measured acceptance report from the scratch path the
# gate wrote it to into the tree this step commits; it is the only write
# this file makes to a file's contents rather than to the index.
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
#
# `git commit` executes pre-commit, prepare-commit-msg, commit-msg and
# post-commit from $GIT_DIR/hooks -- or from wherever core.hooksPath
# points -- and every one of those is an ordinary executable file in a
# directory this pipeline does not own the contents of.  A review named
# the consequence precisely: a planted hook runs with this step's
# privileges at the exact moment the credential in .git/config is
# reachable, and it can read that credential, mutate the evidence
# between staging and commit, or open a network connection, while the
# commit still reports success.
#
# So every git invocation that CHANGES anything is run with
# `-c core.hooksPath=<an empty directory this step created>`, which is
# git's own documented way to say "there are no hooks".  Three
# properties make that a control rather than a gesture:
#
#   * the directory is created inside the VERIFIED private runtime root
#     (0700, owner-checked, never a symlink -- see env.sh's
#     playthrough_secure_dir), so nothing can plant an executable in it
#     between its creation and the commit;
#   * it is asserted EMPTY at the moment it is nominated, so an
#     inherited path that already held something is a refusal rather
#     than a silent execution;
#   * it is passed with -c on the command line, which outranks every
#     configuration file, so a core.hooksPath written into .git/config,
#     ~/.gitconfig or /etc/gitconfig cannot win it back.
#
# READING git is deliberately left alone: `git log`, `git rev-parse`,
# `git ls-files` and friends run no hooks, and routing them through the
# same wrapper would only make the failure surface larger.
#
# THE REPOSITORY'S OWN HOOKS ARE NOT DELETED OR DISABLED.  This checkout
# carries the stock git-lfs shims, they are legitimate, and other tools
# depend on them.  Containment here is per-invocation and leaves the
# repository exactly as it was found.
# ---------------------------------------------------------------------
HOOKS_VOID=""

# hooks_void -- print the path of an empty, private, verified directory.
#
# Memoised: the first call creates and proves it, later calls reuse the
# same path, and a failure to establish one is fatal rather than a
# silent fallback to the repository's hooks.
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
#
# This checkout is provisioned with a push URL of the shape
# https://x-access-token:<secret>@host/..., which puts a live bearer
# token in a plain file.  That is the platform's arrangement and not
# something this pipeline can change: `credential.helper` is set EMPTY
# and `credential.interactive` false here, so the URL is the only
# authentication path the repository has, and a step that stripped the
# credential out of it would break the very publication this evidence
# exists to reach.  Rotation is likewise the platform's to perform.
#
# WHAT IS IN THIS STEP'S POWER is the file's mode, and that is the half
# a review found open: a 0644 config hands the token to every local
# account, every child process and every hook.  So the mode is asserted
# before anything is committed, and a config that carries a credential
# while being readable by group or other is a REFUSAL -- committing
# under it would publish evidence produced in an environment where the
# credential had already leaked.  A config with no credential in it is
# held to no such rule, because there is nothing there to protect.
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

# The two phase words of verify_artifacts.sh that a COMMITTABLE
# acceptance report may carry.  Named here rather than spelled at the
# comparison, because a report from the artifacts-only phase measures
# nothing about the history and this step's whole subject is what the
# history now proves.
readonly GATE_HISTORY_PHASE="post-commit"
readonly GATE_EVERY_PHASE="all"
# THE TWO VERDICTS A REPORT MAY BE PUBLISHED UNDER, and why there are
# two rather than one.
#
# This used to demand the single token `pass`, which was right while the
# gate had only two verdicts to give.  It then grew a third:
# `pass-with-divergence`, emitted when nothing FAILED but some property
# the plan asks for is delivered differently and the gate says so in
# full -- what the plan requires, what was delivered instead, and why it
# stands.  A review had found the opposite handling of exactly one such
# property, a known and permanent divergence recorded as a PASS, and
# named the report that resulted as the defect.
#
# Refusing to publish `pass-with-divergence` would recreate that defect
# from the other side.  The only report the checkpoint could then commit
# would be one that called the divergence a pass, so the honest verdict
# would be unpublishable and the dishonest one required -- which is a
# strong incentive to go back to lying, expressed as a gate.
#
# `fail` remains unpublishable.  The distinction being drawn is between
# "a property was measured and did not hold" and "a property was
# measured, does not hold as WRITTEN, and the report says so out loud":
# the first is a defect in the artifacts, the second is a documented
# divergence, and only the first is a reason to withhold the evidence.
readonly -a GATE_PUBLISHABLE_VERDICTS=(
    "pass"
    "pass-with-divergence"
)

# ---------------------------------------------------------------------
# The lifecycle vocabulary.
# ---------------------------------------------------------------------

# The trailer key and the FIVE checkpoint names.  `final` searches the
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
# So the dossier gets its own, earlier commit.  Five steps, in this
# order, and each refuses to run out of turn:
#
#     dossier    the survivor described, before a single frame exists
#     creation   the survivor and the save they start from
#     final      the closed session: the last save and the record
#     media      the artifacts DERIVED from that record
#     attest     the two reports, and what they can honestly cite
#
# WHY THE LAST THREE ARE THREE AND NOT ONE.  `final` used to carry all of
# it, and it demanded playthrough/REPORT.md before it would run -- so the
# document that must cite the commits carrying the film, the transcript
# and the acceptance evidence was required to exist BEFORE the commit
# that created any of them.  There is no order in which that can be
# satisfied honestly: either the report cites hashes that do not exist
# yet, or it cites an earlier session's.  A review found both.
#
# Split, each commit is about one thing and cites only what precedes it:
#
#   final    is taken the moment the session ends, immediately after the
#            in-game Save & Quit.  Its subject is the RECORD -- the save,
#            the captures, the manifest -- and it requires no report at
#            all, because nothing derived from the record exists yet.
#   media    is taken by run_pipeline.sh once the timeline, the
#            transitions, the film and the transcripts have been produced.
#            Its subject is everything DERIVED from the record, and it
#            can cite `final` because `final` is already in the history.
#   attest   is taken last.  Its subject is the acceptance report and
#            REPORT.md, and it is the ONLY step that publishes the
#            acceptance report into the tree: the measurement writes to a
#            scratch path outside the checkout and this step copies it in
#            and commits it in the same breath, so the tree is dirtied
#            and cleaned within one step that can be refused as a whole.
#            By the time it runs, every hash the report cites exists.
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

# is_post_session_checkpoint NAME -- whether the session has already
# ended by the time this checkpoint runs.
#
# `final`, `media` and `attest` all run after the survivor has saved and
# quit, so every question of the form "is the save in its finished state"
# has ONE answer across the three of them.  Before the split there was
# only `final`, and these comparisons were written against it by name --
# but each of those names meant "the session has ended", not "this
# particular commit".  Left literal, `media` would have demanded a LIVE
# character save from a session that ended in death, which `final` had
# just correctly recorded as the death shape.
is_post_session_checkpoint() {
    local name="$1"
    if [ "${name}" = "${CHECKPOINT_FINAL}" ] ||
       [ "${name}" = "${CHECKPOINT_MEDIA}" ] ||
       [ "${name}" = "${CHECKPOINT_ATTEST}" ]; then
        return 0
    fi
    return 1
}

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

# The one pathspec a SESSION checkpoint will ever read or write the index
# through.  Anything else in the repository is somebody else's change and
# is left exactly as found: a checkpoint that also carried an unrelated
# root-file edit would be a checkpoint about two things.
#
# .gitignore and .gitattributes are the deliberate exception, and they are
# not an exception to this array -- they have a milestone of their own
# (INTEGRATION_PATHS, do_integration) which stages exactly those two and
# refuses everything else, including everything under playthrough/.  The
# two sets are disjoint on purpose, so no commit this file takes is ever
# about both the session and the repository's rules.
readonly -a PATHSPECS=("playthrough")

# How many paths go into one `git add` invocation ON THE FALLBACK PATH.
# When git can read its pathspecs from a file the whole class goes in one
# call and this bound is not reached at all; on a git older than 2.25 the
# streamed pathspec file is replayed in chunks of this size, which keeps
# each argv far below any platform's limit while still being one call per
# 256 frames rather than one per frame.
readonly STAGE_BATCH_SIZE=256

# The name of capture number one, formatted from env.sh's own capture
# format rather than spelled out here, so this file cannot disagree with
# manifest.py or capture.sh about what a capture is called.  `printf -v`
# writes into the variable directly: a command substitution would be a
# subshell whose status `readonly` would mask (ShellCheck SC2155).
#
# SC2059 objects to a variable used as a printf format.  Here that is the
# entire point -- the format is env.sh's single definition, shared with
# manifest.py, and inlining a second copy of '%05d' is exactly the
# divergence this indirection exists to prevent -- and capture.sh carries
# the same suppression for the same reason.  The expansion is asserted
# immediately below, so a format that does not expand is a refusal rather
# than a filename spelled 'frame_%05d.png'.
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
#
# Every diagnostic in this file is about a population whose size is the
# session's: "nothing is staged" names one path per capture, and a
# refusal that holds one string per frame to print them all is the same
# unbounded list the staging path was just relieved of.  The COUNT is
# always exact and always reported; this bounds how many are named.
readonly DIAGNOSTIC_LIMIT=8

# How many lines of "what a checkpoint would stage" `status` prints.  The
# preview is a REPORT for an operator, and a report that is one line per
# capture is not one: the total is stated exactly and the first few are
# shown, so the answer is readable at any session length.
readonly PREVIEW_LIMIT=20

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
# WHERE THAT IDENTITY CAME FROM -- REPORTED, AND NEVER WRITTEN.
#
# This block used to WRITE the resolved pair into the checkout's own
# configuration with `git config --local user.name` / `user.email`, and
# the reason given was concrete: the render and capture stages run inside
# the declared container, which mounts this checkout, sets its own HOME
# and forwards no GIT_* at all -- so an identity living only in the
# invoking user's ~/.gitconfig does not exist in there, and a checkpoint
# taken in the one environment where rendering is legal exited 3.
#
# THREE THINGS WERE WRONG WITH THAT, and they compounded.
#
# It contradicted this file's own opening contract, which states in as
# many words that it never writes git configuration -- not user.name, not
# user.email, not in any scope.  A file that says "never" at the top and
# does it in the middle has one of the two wrong, and a reader trusts the
# top.
#
# The execution environment this evidence is produced in FORBIDS running
# `git config user.name` or `user.email` at any scope, and fixes the
# committer identity itself.  So the write was not a service the caller
# wanted; it was a prohibited act that happened to be load-bearing.
#
# And it did not even buy the invariance it was justified by.  The value
# written is the one the HOST resolved, so what lands in .git/config
# still depends on who ran this first -- exactly the variability the
# absence of --env was meant to prevent, only now persisted where the
# acceptance gate would read it back and report it as a property of the
# repository.  A review caught the consequence from the other end: the
# delivered acceptance report CLAIMED a repository-local identity that
# was not there at all.
#
# What replaces it: nothing is written, and the container is given the
# identity the ordinary way -- supported_env.sh forwards the resolved
# GIT_AUTHOR_* / GIT_COMMITTER_* pair as environment, which is the
# mechanism git documents for exactly this and which leaves no trace in
# the tree.  This file's responsibility is what its header always said it
# was: ASSERT that an identity resolves, then commit under it.
#
# What is kept is the READING.  Which scope answered is worth saying out
# loud, because "resolves" and "resolves from this checkout" are
# different facts and the second one is the one the plan asked for and
# the one this environment cannot supply.
# ---------------------------------------------------------------------

# local_config_value KEY -- the value from the repository's own config
# alone, empty when this checkout does not record one.  `--local`
# deliberately does not fall back to the account or the system: the
# question here is what THIS checkout says, not what git would resolve.
local_config_value() {
    "${GIT}" config --local --get "$1" 2>/dev/null || printf ''
}

# report_identity_scope -- say where the commit's identity came from.
#
# Read-only, and it never refuses: assert_identity has already established
# that git can name an author, which is the requirement.  This only
# records WHICH scope did so, so that a report written from this run's log
# can state the true position instead of assuming the narrower one.
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
    # THE CREDENTIAL GATE, here rather than at the commit, because the
    # question it asks -- "has this repository's token already been
    # exposed to every account on the host" -- is a property of the
    # environment the whole checkpoint is produced in and not of the
    # commit command.  GIT_DIR_PATH is resolved just above, which is why
    # this is its first possible call site.
    assert_credential_containment
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
# .gitignore AND .gitattributes ARE OUT OF SCOPE OF EVERY SESSION
# CHECKPOINT, AND HAVE A MILESTONE OF THEIR OWN.  The terminal
# `!/playthrough/**` negation and the `*.sav`/`*.mp4`/`*.zzip` binary
# attributes are load-bearing for this tree, and every checkpoint CHECKS
# both -- see assert_not_ignored and assert_committed_vcs_rules.  No
# session checkpoint commits either: they are repository-wide
# configuration and they do not belong inside a commit whose subject is
# a survivor's save.
#
# They did, however, need a committer.  Both files are MODIFIED by this
# feature, and a negation that was never committed loses the save data on
# the next fresh clone while every working-tree check still passes -- so
# `do_integration` commits exactly those two, before any artifact exists,
# and refuses to publish them in a state that would leave the save data
# ignored.
# ---------------------------------------------------------------------

# WHICH PATHS THE MILESTONE IN PROGRESS MAY COMMIT.
#
# Three of the four milestones are about the session and commit
# playthrough/ and nothing else.  The fourth is about the two
# repository-wide rule files this tree depends on, and it commits exactly
# those two and nothing else -- including nothing under playthrough/.
# The mode is set ONCE by the milestone and read by in_scope, so "what
# may be committed" has one answer per run rather than one per call site.
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
# terminated.  -z is the only format that survives a path with a space, a
# quote or a newline in it; --diff-filter is deliberately absent so a
# staged deletion counts too.
#
# THE NUL SURVIVES ALL THE WAY TO THE REFUSAL, and that is a correctness
# requirement rather than tidiness.  This used to re-emit each offending
# path followed by a NEWLINE, and assert_scope then read those records
# line by line and skipped the empty ones -- so a staged path whose name
# is made only of newline characters became a run of empty lines, every
# one of them skipped, and the refusal saw nothing to refuse.  A file
# named "\n\n" is legal on every filesystem this pipeline runs on, and
# the consequence was that an out-of-scope path could be swept into a
# checkpoint by the one check written to prevent exactly that.
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
# pattern; and the six attribute rows must be committed, because
# `* text=auto` alone leaves the film, the save and the map archives to
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

# SIX ROWS, AND DELIBERATELY NOT A SEVENTH.  A `playthrough/userdir/**
# -whitespace` waiver used to sit here too, added so that `git diff
# --check` would stop reporting the blank line at the end of the two
# files the engine writes that way -- its debug log and the survivor's
# memorial diary.  A review removed it: the plan's file schema for
# .gitattributes permits EXACTLY these six additions and no seventh, and
# a rule nobody authorised is a change to repository-wide configuration
# made on this feature's own authority.
#
# The blank lines are still there and are still correct -- a memorial
# rewritten to please a whitespace linter is no longer the memorial the
# game wrote -- so what changed is only that they are REPORTED rather
# than suppressed.  Nothing in this pipeline or in the repository's CI
# fails on `git diff --check`; test_readme.py bounds the report to those
# two engine-written files by name, so a THIRD one appearing is a finding
# instead of being hidden by a waiver.

# ---------------------------------------------------------------------
# THE ATTRIBUTES AS GIT ACTUALLY APPLIES THEM, which is not the same
# question as whether the six rows are present.
#
# git applies the LAST matching pattern, exactly as it does for
# .gitignore -- so a row added AFTER `*.mp4 binary` that also matches an
# mp4 silently overrides it, and the row-by-row check above still passes
# because the row it wants is still there.  The consequence is not
# cosmetic: with the film left to `text`, `git add` runs end-of-line
# normalisation over an h264 stream and commits a corrupted container,
# and every count in this script still tallies.  The .gitignore half of
# this trap is already guarded -- the negation must be the LAST effective
# rule -- and this is the same guard for the other file.
#
# So git is ASKED, with `git check-attr`, about one representative path
# per row.  A witness path need not exist: check-attr is pattern
# matching, so `playthrough/cata-play.mp4` answers for the film whether
# or not it has been rendered yet.  `binary` is a macro for
# `-text -diff -merge`, so the property to require of a binary artifact
# is that `text` is UNSET, and of a text artifact that it is SET.
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
#
# `git check-attr` prints `<path>: <attribute>: <value>`, and the value is
# what is wanted; anything unreadable prints nothing, which the caller
# reports rather than treating as agreement.  SOURCE, when given, is a
# tree-ish read with --source so HEAD's own rules can be asked about
# instead of the working tree's.
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

# check_attr_supports_source -- whether this git can be asked about a
# tree-ish.  --source arrived in git 2.40; on anything older the working
# tree remains the only readable answer, and saying so is better than
# reporting a refusal an operator cannot act on.
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

# assert_attribute_semantics LABEL [SOURCE] -- refuse a ruleset whose
# effective attributes are not the ones this feature declares.
#
# Asked of the WORKING TREE at every checkpoint, because that is the
# ruleset the `git add` in this run will apply, and of HEAD wherever
# HEAD's rows are checked, because that is the ruleset a fresh clone
# gets.  Both are EX_PREREQ: the fix is an edit to .gitattributes, not
# anything about the session.
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
    # THE PATHS ARE LISTED FROM THE TABLE, not described in prose.  This
    # sentence used to name them by hand, and the moment a since-removed
    # whitespace waiver added two witnesses it reported "8 witness paths"
    # and then named six -- the same second-copy defect as a hard-coded
    # check total, so the list is derived even now that the two counts
    # happen to agree again.
    local witness="" listed=""
    for witness in "${ATTRIBUTE_WITNESSES[@]}"; do
        listed="${listed}${listed:+, }$(rel "${witness%%|*}")"
    done
    playthrough_log "git applies this feature's attributes to" \
        "${label}'s ${#ATTRIBUTE_WITNESSES[@]} witness paths --" \
        "${listed} -- so no later rule overrides them"
    return 0
}

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

# worktree_lines PATH -- the same normalisation as committed_lines,
# applied to the file ON DISK.  Empty when the path is not there.
#
# The integration milestone needs this and the committed reading cannot
# serve: that milestone exists precisely for the case where HEAD does NOT
# yet carry the rules, so asking HEAD about them would refuse the one
# situation the milestone is for.
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

# vcs_rule_problems READER -- every way the two rule files read through
# READER fail this feature, one problem per line, nothing when they hold.
#
# READER is the NAME of a function taking a path and printing that file's
# effective lines, so the identical requirement can be asserted against
# the working tree and against HEAD without two descriptions of it.
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
        # WHOLE-LINE MATCHING WITHOUT A PIPE.  This was `printf | grep
        # -Fqx`, and `grep -q` exits the instant it matches -- which can
        # close the pipe under a `printf` that has not finished writing,
        # making the PIPELINE's status 141 under `pipefail` and turning a
        # row that IS present into a reported problem.  Nothing here
        # needs a subprocess: the newline fences below are an exact
        # whole-line test, and they cannot be raced.
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
    # THE ROWS ARE THERE; WOULD GIT APPLY THEM?  A row that a later rule
    # overrides is present and inert, so HEAD is asked the effective
    # question too -- with --source, which is what makes it HEAD's answer
    # rather than the working tree's.
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
    # RUNTIME AND AUTH STATE, which is the same hazard one step worse.
    #
    # Everything above is merely not evidence.  These are diagnostics and
    # a CREDENTIAL: the X authority cookie whoever holds it can use to
    # read the screen being captured and inject keystrokes into the
    # session, the pid and ownership records, and the per-stage stderr
    # captures.  env.sh keeps them in a private runtime root outside the
    # working tree precisely so they cannot be staged -- and refuses a
    # nominated root inside the checkout -- but the terminal
    # `!/playthrough/**` negation means that if one ever does land here it
    # is committable, and a cookie in a commit cannot be un-published.
    "Xauthority"
    "*.pid"
    "x-ownership*"
    "capture-stage-*.err"
)

# TWO PATTERNS ARE DELIBERATELY ABSENT FROM THAT LIST, and this note is
# here because both look like obvious omissions and adding either would
# break the checkpoint outright.
#
#   *.lock  would match playthrough/tooling/requirements.lock, which is a
#           REQUIRED tracked artifact -- the hash-pinned install contract
#           for the six declared libraries.  Every checkpoint would be
#           refused.  Measured before it shipped: a `find` over the real
#           tree for the runtime patterns returned requirements.lock and
#           nothing else.  The runtime locks live in <runtime>/lock/ and
#           are covered by the containment refusal below, which is the
#           control that actually addresses them.
#   *.log   would match the engine's own `#<name>.log` character log and
#           config/debug.log, both of which are EVIDENCE and are
#           committed on purpose -- the debug log is what makes the
#           no-cheating claim auditable rather than asserted.  The
#           pipeline's own three logs are named individually where that
#           matters and otherwise live outside the tree.
#
# The lesson generalises: inside playthrough/ a name-based refusal is
# applied to a tree that mixes diagnostics with evidence, so a pattern
# has to be justified against BOTH.

# assert_runtime_root_is_outside -- the root cause, refused here too.
#
# env.sh already refuses a PLAYTHROUGH_RUNTIME_DIR inside the checkout,
# and this is not a duplicate of that check but the same rule applied at
# the one stage where breaking it does permanent damage.  Two reasons it
# belongs here as well:
#
#   * env.sh decides at SOURCE time, and a caller can export the variable
#     afterwards -- a value this script would then inherit and honour;
#   * a checkpoint is the only irreversible act in the pipeline.  A frame
#     written to the wrong place can be deleted; a credential committed to
#     a branch that has been published cannot be un-published, and the
#     honest remedy is to rotate the cookie and rewrite history.
#
# So the containment is asserted immediately before staging, against the
# value in force at that moment, and it covers both directions: a runtime
# root inside the repository, and one ABOVE the repository that contains
# it.  Reported with the remedy, because the fix is a one-line change to
# an environment variable and nothing about the tree needs repairing.
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
#
# The feature's deliverable is not only the film: it is the film PLUS the
# report that says what was recorded, who the survivor was and how the
# session ended.  Its shape is fixed rather than a matter of taste --
# EXACTLY three sections, in this order:
#
#     A) Screen Recording and Animation
#     B) Character Creation
#     C) Playing the Game
#
# and the reason to enforce it here is that nothing else did.  The report
# was named in env.sh as PLAYTHROUGH_REPORT and STAGED with the narrative
# class, and staging an absent path is deliberately not fatal --
# stage_batch skips it and says so -- so a `final` checkpoint could be
# taken, and pass every other gate, with no report in the tree at all.
# The omission would then be a line in a log nobody re-reads, and the
# published history would carry a film with nothing explaining it.
#
# So at `final` the report must exist, be non-empty, and carry those three
# section headings and no fourth.  A missing one, a renamed one, an extra
# one and a reordered set are each their own refusal, because each is a
# different mistake: a report with two sections is unfinished, one with
# four has grown a section the requirement does not have, and one with
# the sections in another order is not the document that was asked for.
#
# WHAT THIS DOES NOT DO.  It does not read the prose or judge whether a
# section says enough -- that is a reader's job and cannot be a shell
# script's.  It holds the STRUCTURE, which is the part that can be
# checked and the part whose absence is invisible.
#
# The other three checkpoints are untouched: `integration` and `dossier`
# run before the session, and `creation` runs before a single frame is
# rendered, so at none of them can a report about the finished recording
# honestly exist yet.
# ---------------------------------------------------------------------

# The three headings, in order, as ATX level-two Markdown -- which is how
# the report writes them and how a reader's table of contents finds them.
# Level three subsections are deliberately not counted: the report has
# many, and they are its internal structure rather than its shape.
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
#
# THIS USED TO BE ASKED AT `final`, AND THAT WAS UNSATISFIABLE.  The
# report's own subject is what the session produced -- the film, its
# codec and duration, the caption track, the commits proving each artifact
# class is committed -- so it cites hashes from the commits that carry
# them.  Demanding it at `final`, which is taken the instant the session
# ends and before a single derived artifact exists, required the document
# to cite commits that had not been made.  A review found the predictable
# result: the delivered report cited an EARLIER session's commits, because
# those were the only ones available when the rule forced it to be
# written.
#
# It is demanded at `attest` instead, which runs after `final` and after
# `media`, so everything it cites is already in the history.
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
#
# WHY THE REPORT IS NOT SIMPLY WRITTEN WHERE IT BELONGS.  It used to be:
# verify_artifacts.sh wrote playthrough/acceptance-report.txt on a passing
# run and deleted it on a failing one, from inside the very tree it was
# measuring, after the checks that assert that tree is clean and fully
# committed.  A review measured the result -- a full-phase run taken after
# the final checkpoint left the tree dirty in the one file it had just
# certified as committed.  A measurement that publishes itself invalidates
# its own last finding.
#
# So the gate writes to a scratch path outside the checkout and THIS step
# publishes, which puts three questions between the measurement and the
# commit that a self-publishing gate could not ask itself:
#
#   is there a report at all,
#   did it PASS -- a failing measurement is not evidence of compliance
#   and committing one would archive a red verdict as though it were
#   green,
#   and is it about THIS tree.
#
# The third is the one that matters most and is the easiest to lose.  The
# report names the commit it measured in its own machine block, so a
# report generated, left while further commits landed, and only then
# committed is detectable here instead of being taken on trust.  A review
# found exactly that shape: a committed report citing a HEAD and a check
# total that had both moved on, every number in it correctly derived and
# the citation false anyway.  A report measured over a DIRTY tree is
# refused for the same reason -- it is provisional by construction, and
# the gate says so in that line rather than leaving it to be inferred.
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
#
# Deliberately NOT in the gate set: the gates are reads, and a read that
# writes is a gate an operator cannot run to find out where they stand.
# It happens after every refusal has had its chance and immediately before
# staging, so the file it creates is dirtied and committed inside a single
# step that either completes or has changed nothing anybody has to undo.
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

# first_capture -- one capture on disk, by name, or nothing.
#
# ONE FRAME IS ENOUGH: this gate asks whether the frames directory is
# excluded by an ignore rule, and any capture answers it.  So the FIRST
# one is named rather than searched for.  manifest.py formats a capture as
# frame_%05d.png from a 1-based index, so frame 1 is exactly
# ${FIRST_CAPTURE_BASENAME} and a single stat answers the question.
#
# It used to `find` the whole directory and pipe it through `sort`, which
# is O(N log N) in the session length AND cannot emit its first line until
# it has consumed every one of them -- `sort` buffers by definition -- for
# a question with an O(1) answer.
#
# The scan remains as a FALLBACK for a tree whose frame 1 is absent, and
# it takes whatever name comes first rather than the lowest: when the
# canonical name is gone, "any capture" is still the question, and an
# unsorted walk that stops at the first name it is given costs one
# directory read.
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

# final_commits -- EVERY final checkpoint, newest first.
final_commits() {
    "${GIT}" log --format=%H \
        --grep="^${TRAILER_KEY}: ${CHECKPOINT_FINAL}\$" HEAD -- \
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

# creation_commit_for_survivor [SURVIVOR] -- the newest creation
# checkpoint whose own tree names that survivor, or nothing.
#
# This is what makes the anchor SURVIVOR-SPECIFIC rather than merely
# newest, and it fixes the cause as well as the symptom: because
# do_creation refuses a second creation only when one exists FOR THIS
# SURVIVOR, a genuinely new survivor can now take a creation checkpoint
# of their own instead of being blocked by a previous recording's.
#
# THE SURVIVOR IS AN ARGUMENT, defaulting to the one this run loaded, so
# that `status` can ask the same question about a survivor it read for
# itself without the evidence gates having run.  One implementation
# answers it for both, which is the point: `status` used to compare
# against the NEWEST creation instead, and reported "'final' would
# REFUSE" for a session whose own anchor was simply an older commit.
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

# manifest_rows_at COMMIT -- how many rows the record held in that
# commit's own tree, or nothing when the tree carries no readable
# record.  Streamed through wc rather than captured, so the size of the
# record does not decide whether this can be asked.
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

# git_supports_pathspec_file -- whether `git add` will read its pathspecs
# from a NUL-delimited file (the option pair arrived in git 2.25).
#
# PROBED, NOT ASSUMED FROM A VERSION STRING, and probed with an EMPTY list
# so the probe cannot stage anything: a git that knows the options exits 0
# having added nothing, and one that does not exits non-zero with "unknown
# option".  --dry-run is belt and braces on top of that.  The answer is
# cached for the run.
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
#
# One call when git can read the file, and the file replayed in chunks of
# ${STAGE_BATCH_SIZE} when it cannot.  Either way the shell holds at most
# one chunk, and the one-call path means one index read and one index
# write for a whole artifact class -- which is the cost that actually
# scales, because the index is the size of the repository and not of the
# batch.
#
# `git add` with NO -A, NO -f and NO shell glob, on both paths.  Since git
# 2.0 a pathspec add records deletions as well as additions and
# modifications, so -A would add nothing here except the appearance of a
# blanket add (measured on git 2.51, and again through the pathspec file:
# an M and a D staged from one NUL-delimited list).  -f is refused on
# principle: if a path needed forcing, the .gitignore negation is wrong
# and that is a bug to fix in .gitignore, not to paper over here.
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

# stage_stream LABEL -- stage one artifact class from a NUL-delimited
# stream of paths on stdin.
#
# THE ONE STAGING IMPLEMENTATION in this file, so the named classes and
# the capture population are staged by the same code and cannot drift
# apart.  A path is read, judged by stageable() and written into the
# pathspec file one at a time; what survives the loop is two counters and
# a BOUNDED sample of the names that were skipped.
#
# It must be fed by REDIRECTION rather than by a pipe, because a pipeline
# would run it in a subshell where die() could only exit that subshell --
# and a staging failure has to end the run.
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
    # WHICH NAMED PATHS WERE NOT THERE, SAID OUT LOUD.  stageable()
    # skipping an absent path is deliberate -- a checkpoint must not fall
    # over because an optional artifact has not been written -- but the
    # skip used to be entirely silent, so a MANDATED artifact that had
    # never been written (playthrough/README.md was exactly this) was
    # omitted from every commit with nothing in the log to show it.
    # Reported rather than refused, because which of these classes are
    # optional is a judgement this function is the wrong place to make;
    # what it can do is make the omission visible.  The count is exact;
    # the names are the first ${DIAGNOSTIC_LIMIT} of them.
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
#
# A thin adapter onto stage_stream: the named classes are a handful of
# paths each, so naming them as arguments is the readable form, and the
# staging itself is the streamed one.
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
#
# Two sources.  The filesystem, walked by `find -print0` because a shell
# glob over several thousand frames is exactly the argument list this
# design exists to avoid; and the INDEX, so a capture git tracks and the
# filesystem no longer has is named too and its removal is recorded as a
# removal instead of being left in the index as a ghost.  Not that any
# capture may ever be removed -- no decimation, no sampling, no
# deduplication -- but if one ever went missing the checkpoint would show
# it rather than hide it.
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
#
# THREE OF THE CLASSES USED TO BE WHOLE DIRECTORIES.  `git add --
# playthrough/tooling`, `-- playthrough/userdir` and `-- playthrough/build`
# staged whatever those trees happened to contain, and the only thing
# standing between an accident and a commit was HYGIENE_NAMES -- a
# DENYLIST of the shapes somebody had already been bitten by: bytecode, an
# ad-hoc test file, a quarantined film, the X authority cookie, a pid.
#
# A denylist answers "is this one of the bad things I know about".  The
# question a checkpoint has to answer is "is this evidence", and those are
# not the same question: every artifact a future stage invents, every
# scratch file a debugging session leaves behind, every new cache the
# engine starts writing is admitted by default and committed in silence.
# .gitignore's terminal `!/playthrough/**` negation makes that worse
# rather than better, because it re-includes everything under this tree --
# so "it would have been ignored" is not a fallback that exists here.
#
# So the direction is inverted.  Every file under playthrough/ is
# classified before anything is staged, an unclassified path is a REFUSAL
# naming it, and staging then works from the classification rather than
# from a subtree.  The denylist is kept as well: it fires earlier and says
# "this is a credential" where this would only say "this is not evidence",
# and the specific diagnosis is worth more to an operator than the general
# one.
#
# THE ENGINE'S TREE IS CLASSIFIED BY POSITION, NOT BY FILENAME, and that
# is deliberate rather than lazy.  The engine writes shapes this pipeline
# does not choose and cannot enumerate -- `#<b64>.sav`, `.ano.json`,
# `.pt`, `.seen.0.-1`, `.zones.json`, a `.mm1` DIRECTORY, `10.5.0.mmr`
# memory regions, `<name>-<serial>.json.-4651329699267.fb` caches -- and a
# per-filename allowlist over somebody else's output would refuse a
# perfectly correct checkpoint the first time a new engine version wrote a
# new one.  What IS pinned is where the engine may write: the eleven
# subtrees it creates under the userdir.  A file appearing anywhere else
# under playthrough/userdir/ is not the engine being itself, it is
# something else having landed there.
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
#
# A GLOBAL RATHER THAN A PRINTED VALUE.  Every path under playthrough/ is
# classified at least twice -- once by the refusal sweep and once by the
# staging that follows it -- and on a played session that is several
# thousand calls.  Printing the answer would mean a `$( )` fork per call.
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
#
# The filesystem, plus anything the INDEX still carries that the
# filesystem no longer has, so a removal is recorded as a removal instead
# of being left in the index as a ghost.  Both streams are NUL-terminated
# because a played session is thousands of paths and this design exists to
# avoid ever holding them as one argument list.
# EVERY PATH IT EMITS IS ABSOLUTE, and that normalisation is not
# cosmetic.  `find` prints paths beginning with the directory it was
# given, which is absolute; `git ls-files` prints them relative to the
# REPOSITORY ROOT.  The callers classify by stripping the playthrough/
# prefix, and a relative path survives that strip unchanged -- so the
# index half arrived at the classifier still spelled
# `playthrough/REPORT.md` and was reported as belonging to no artifact
# class.  Measured: five checkpoint tests refused with EX_SCOPE over
# perfectly ordinary evidence.  The older capture_pathspecs tolerated the
# same mixture only because it never stripped anything.
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
#
# The classification above answers "is this evidence" by POSITION, and
# for the engine's own tree that is the only answer available: the engine
# writes `#<b64>.sav`, `.seen.0.-1`, `.mm1` directories and
# `<name>-<serial>.json.-4651329699267.fb` caches, so a per-filename
# allowlist over somebody else's output would refuse a correct checkpoint
# the first time a new engine version wrote a new shape.
#
# A review found what position alone cannot see.  `playthrough_files`
# enumerates with `find -type f`, and `-type f` is true of a HARD LINK to
# a file anywhere else on the same filesystem -- so a second link to
# something outside this tree, dropped into a directory the engine owns,
# is classified as engine state by position and `git add` commits its
# whole content.  The same sweep cannot see a symlink at all (`-type f`
# is false of one), so a symlink is an unclassified path that the
# classification refusal never gets to refuse.  And nothing anywhere
# looked at the CONTENT: an innocuously named file holding a credential
# passes every structural question this script asks.
#
# So two properties are established before anything is staged, and both
# are asked of the whole tree rather than of a list somebody maintains:
#
#   1. PROVENANCE -- every entry is a directory or a regular file, owned
#      by this account, with exactly one link, on the same filesystem as
#      the checkout.  Anything else is refused by what it IS, which is a
#      question the engine's freedom to name its own files does not
#      affect.
#   2. CONTENT -- no path about to be committed carries secret material.
#
# Neither replaces the classification; both run beside it.
# ---------------------------------------------------------------------

# assert_staging_provenance -- the tree is what it appears to be.
#
# ONE `find` FOR THE WHOLE TREE, printing four facts per entry, because
# the realistic shape of this tree is ten thousand captures and one
# `stat` per path would be ten thousand forks.  The fields are the entry
# type, the owning uid, the link count and the device number; GNU find
# prints all four, and the device is compared against the checkout's own
# so a filesystem grafted in under this tree is refused rather than
# followed.
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

# The secret scanner, as data so the interpreter is handed a fixed
# program.  It reads NUL-separated paths on stdin and prints one
# TAB-separated finding per line: relative path, rule name, and the
# sha256 of the matched text.  The text itself never leaves the program.
#
# IT LOOKS FOR SECRET VALUES, NOT SECRET VOCABULARY, and that distinction
# was measured rather than assumed.  A first version of this scan was run
# over the real tree and reported twelve findings, every one of them a
# false positive on THIS FEATURE'S OWN DOCUMENTATION of the hazard: the
# string `MIT-MAGIC-COOKIE-1` appears nine times as the name of an X
# authentication protocol, in prose and in `xauth` arguments, and
# `https://x-access-token:<secret>@` appears as a redacted placeholder
# inside the credential-containment refusal itself.  A scan that refuses
# a checkpoint because the tree explains how credentials are contained is
# a scan nobody can leave switched on.
#
# So: the cookie rule requires the protocol name followed by its
# thirty-two hex digits (a bare 32-hex rule would fire on every MD5 sum
# in the notes, of which there are several); the URL rule ignores a
# password that is bracketed, shell-expanded, starred or literally the
# word "secret"; and the remaining rules are vendor token shapes and
# private-key armour, which have no innocent reading.
#
# Verified in both directions on real data.  Over the delivered tree,
# exactly one finding remains and it is baselined below.  Over a planted
# tree of twelve files under the engine's own subtrees, all eight
# credentials were caught -- including one in a file called
# `cache/innocuous.json`, which is the review's stated vector -- while
# the protocol name in prose, an MD5 sum and the redacted placeholder
# were correctly passed over.
#
# EVERY BYTE OF EVERY FILE, WHICH IS NOT WHAT IT USED TO DO.  A review
# found the two blind spots in this scan and named them precisely: it read
# only the first 262 144 bytes of a file, and it abandoned any file whose
# first bytes carried a NUL -- while the caller reported "a scan over
# every path".  Both were affordability decisions, and both were places to
# hide a credential in a tree that commits 307 captures, two films and an
# engine's entire save directory.  A secret in the 300th kilobyte of a
# save file, or nine bytes after a PNG header, was published with the
# scan reporting that it had found nothing.
#
# So the file is STREAMED in 1 MiB chunks with an 8 KiB overlap carried
# between them, which is what keeps a match that straddles a boundary
# findable, and nothing is skipped for being binary.  Findings are
# deduplicated per file by (rule, digest) -- the same granularity the
# reviewed baseline is keyed at -- so the overlap cannot report one
# occurrence twice.
#
# WHAT CHANGES FOR BINARY CONTENT, AND WHY IT IS NOT SIMPLY THE SAME
# RULES.  Compressed and encoded bytes are effectively random, and a
# random stream of 110 MB contains `://` about a dozen times by
# arithmetic alone -- so the url-credential expression, whose middle is
# `[^/\s@]+`, would eventually match noise and refuse a checkpoint for a
# credential nobody wrote.  A credential embedded in a binary file is
# nevertheless still PRINTABLE ASCII, so that is the constraint applied
# there: within a NUL-bearing chunk a match counts only when every
# character of it is printable ASCII and it is at least twelve characters
# long.  Fifteen consecutive printable ASCII bytes occur in random data
# with probability about 1e-7 per position, which is the difference
# between a control somebody can leave switched on and one they cannot.
readonly SECRET_SCANNER='
import hashlib
import os
import re
import sys

PLACEHOLDER = re.compile(
    r"\A(?:<[^>]*>|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\**|x+|X+"
    r"|REDACTED|redacted|TOKEN|token|PASSWORD|password|secret|SECRET)\Z")

# EVERY REPETITION IS BOUNDED, and that is a performance property with
# teeth rather than tidiness.  The url-credential expression began
# [a-zA-Z][a-zA-Z0-9+.-]*:// -- and over a long run of letters that is
# QUADRATIC: at each position the class consumes the whole run, fails to
# find the "://", and backtracks a character at a time.  Measured while
# this scan was being extended to whole files -- a planted 400 KB run of a
# single letter did not finish in five minutes, and the tree this scans
# holds a 20 MB film and 134 save files.  The old 262 144-byte window hid
# the shape rather than fixing it.  A URI scheme is a handful of
# characters and a credential is not kilobytes long, so the ceilings
# below are far above anything real and turn every rule linear.
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
    # A CHARACTER CLASS FOR ONE LETTER, and it is load-bearing rather
    # than decorative: written as a plain literal, this pattern MATCHES
    # ITSELF, and the scan then reports the scanner as carrying a key.
    # Measured exactly that way before this was changed.  The class is
    # equivalent to the letter for matching and is not the letter for
    # searching, which is the whole difference.
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

# The read size, and the overlap carried between reads.  A match cannot
# be longer than the overlap and be found across a boundary, and the
# longest thing any rule above can match is a URL or an armour line --
# tens of characters, not thousands.  8 KiB is therefore generous and
# bounds the memory the scan holds to CHUNK + OVERLAP per file however
# large the file is.
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
                # CLASSIFIED PER CHUNK, not per file.  A NUL says these
                # bytes are not text, and it says it about the region it
                # is in: a save file whose header is binary and whose
                # body is JSON gets the full text rules over the body.
                binary = b"\0" in block
                text = carry + block.decode("utf-8", "replace")
                carry = text[-OVERLAP:] if len(text) > OVERLAP else text
                for rule, expression in COMPILED:
                    for found in expression.finditer(text):
                        if not reportable(rule, found, binary):
                            continue
                        matched = found.group(0)
                        # THE VALUE NEVER LEAVES THIS PROGRAM.  What is
                        # reported is a sha256 of the matched text, which
                        # is enough to compare against a reviewed
                        # baseline and useless to anybody reading a log,
                        # a terminal or a CI transcript.  It also keeps
                        # the baseline itself free of credential-shaped
                        # strings -- a baseline that quoted the value it
                        # excuses would be one more copy of the value.
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

# The findings that are reviewed and accounted for, as
# <path>|<rule>|<sha256 of the matched text>.  An entry pins all three,
# so a NEW occurrence -- even in the same file, even under the same rule
# -- is refused rather than covered by its neighbour.
#
# BY DIGEST RATHER THAN BY VALUE, for the same reason the refusal does
# not print the match: a baseline that quoted the credential it excuses
# would be one more copy of that credential, sitting in a tracked file.
# It would also match its own rule and make the scanner report itself,
# which is not hypothetical -- it was measured before this was changed.
#
# There is exactly one entry, and it is a test fixture:
# test_commit_artifacts.py constructs a remote URL in the shape the
# credential-containment refusal exists to catch, in order to drive that
# refusal.  A scanner that could not see it could not be trusted to see
# the real thing either, so it is accounted for rather than excluded.
# The value it names authenticates nothing.
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
            # THE RULE AND THE PATH, NOT THE VALUE.  Those are what an
            # operator needs in order to go and look; echoing the value
            # into a log, a terminal and a CI transcript would publish
            # the very thing this refusal exists to keep out of the
            # history.  The scanner never emitted it in the first place,
            # so there is nothing here that could leak it by accident.
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

# assert_staging_is_sound -- both questions, in the order whose failure
# is cheaper to diagnose.
#
# Provenance first: "this is a hard link to somewhere else" explains
# itself, where a secret finding on the same file would only say the
# content is wrong without saying why the file is there at all.
assert_staging_is_sound() {
    assert_staging_provenance
    assert_no_secret_material
    return 0
}

# assert_every_path_is_classified -- the refusal that replaces the
# denylist's blind spot.
#
# It runs BEFORE anything is staged, so an unrecognised path costs a
# refusal rather than a commit somebody has to undo by hand.  The count is
# exact and the names are bounded, for the same reason every other sweep
# here bounds them: the realistic shape of this failure on a played
# session is one entry per capture, and eight names identify the class as
# well as ten thousand would.
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

# assert_no_ignored_paths -- nothing in this tree is excluded, asked
# before a single `git add`.
#
# WHY IT MOVED IN FRONT OF STAGING.  The completeness sweep already asked
# this at the END, and while the three big classes were staged as
# DIRECTORY pathspecs that was the only place it could be asked: a
# directory add SKIPS an ignored file and exits 0, so the file quietly
# survived to be counted afterwards.  Naming every path explicitly
# changed that -- an explicit pathspec for an ignored path makes `git add`
# ERROR -- and the error arrives as git's own diagnosis, which says
# nothing about the terminal negation, nothing about directory-level
# ignores, and nothing about why this tree in particular may not have an
# excluded file in it.  Measured: an ignored userdir/config/lastworld.json
# went from a precise EX_SCOPE refusal to a bare EX_COMMIT.
#
# So it is asked here, with the diagnosis intact, before anything is
# staged.  The sweep at the end is kept as the backstop.
#
# ONE `check-ignore` FOR THE WHOLE TREE.  --stdin -z reads the paths as
# they stream and prints only those that are excluded, so this is one
# process rather than one per path; it exits 1 when nothing is ignored,
# which is the ordinary case and not an error.
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
#
# THE ORDER IS THE FEATURE'S OWN ORDER, and the list is exhaustive over
# playthrough/ by design; assert_tree_fully_staged immediately below
# proves that exhaustiveness instead of assuming it.
stage_artifacts() {
    # 0. Three refusals before a single `git add`, in order of how
    #    SPECIFIC their diagnosis is.
    #
    #    Hygiene first, because "this is interpreter bytecode" and "this
    #    is the X authority cookie" tell an operator what to do, where
    #    "this belongs to no artifact class" only tells them something is
    #    wrong.  It examines the INDEX, which this run has not touched
    #    yet -- it used to run after staging, and moving it forward is
    #    safe precisely because the classification below now bounds what
    #    staging can add, so a *.pyc this run could stage no longer
    #    exists as a possibility.
    #
    #    Then the ignore sweep, then the classification.  A subtree
    #    pathspec used to make the classification unnecessary by making
    #    it unanswerable -- it staged whatever was there.
    assert_index_hygiene
    assert_no_ignored_paths
    #    Then WHAT each path is and WHAT IT CONTAINS, before the
    #    classification asks where it lives.  A hard link into this tree
    #    is classified as engine state by position and would be committed
    #    whole; a symlink is invisible to the classification sweep
    #    entirely; and an innocuously named credential satisfies every
    #    structural question either of them asks.  See
    #    assert_staging_is_sound.
    assert_staging_is_sound
    assert_every_path_is_classified
    # 1. The authored tooling, including requirements.txt -- the
    #    dependency declaration the requirement wants kept out of the
    #    game's source tree.  BY NAME, not by directory: `git add --
    #    playthrough/tooling` staged anything that had landed in there.
    stage_class "tooling" "pipeline tooling"
    # 2. The narrative record: the dossier written before play, the
    #    transcript, the engineering notes, the feature readme, and the
    #    three-section report the feature is required to deliver.
    #    The report is named here for the same reason README.md is --
    #    the class list is exhaustive over playthrough/ by design, and
    #    assert_tree_fully_staged below refuses a checkpoint that leaves
    #    any path in the tree unstaged, so a mandated document missing
    #    from this list would stop the checkpoint rather than slip
    #    through it.  It is named ONCE, through env.sh's
    #    PLAYTHROUGH_REPORT: the mandated three-section account is one
    #    document, and a second copy of it under another name is two
    #    answers to a question that has one.
    #    The acceptance report is named here for a reason a review
    #    found: it was published into the tree by the gate AFTER the
    #    final checkpoint and appeared in NO class list, so the one
    #    document proving the artifacts were measured was the one
    #    document no checkpoint staged.  It is now written by the
    #    `attest` step immediately before this staging runs, and named
    #    here so the class list stays exhaustive over playthrough/.
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
    #
    #    MOSTLY THE GAME'S, AND THE CONFIGURATION IS PARTLY OURS.  This
    #    used to read "never edited by this pipeline", which was not true
    #    and mattered: seed_options.py patches
    #    <userdir>/config/options.json IN PLACE, key by key, to set the
    #    values the capture depends on -- 24_HOUR=24h so the sidebar clock
    #    is the fixed-width form the OCR regex needs, SOUND_ENABLED=false
    #    to match SDL_AUDIODRIVER=dummy, the tileset id, and the terminal
    #    and font geometry the crop is computed from.  A reader who
    #    believed the whole subtree was engine-authored would have no
    #    reason to look for those edits, and they are exactly the edits
    #    that decide what every frame looks like and how it is read.
    #
    #    The honest division: the SAVE is the engine's alone and is never
    #    touched here; the CONFIG is engine-created and then patched in
    #    place by the pipeline; everything else under the userdir is the
    #    engine's.  Nothing in the tree is rewritten by THIS script,
    #    which only stages what it finds -- and that narrower claim is
    #    the one worth making, because it is the one an operator is
    #    relying on when they read a checkpoint.
    #    Classified by POSITION -- the eleven subtrees the engine
    #    creates -- because the engine's filenames are its own and a
    #    per-name allowlist over them would refuse a correct checkpoint
    #    the first time it wrote a shape nobody had enumerated.
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
    # Completeness last.  Hygiene, the ignore sweep and the
    # classification all ran before anything was staged, so what is left
    # to establish is only that every classified path actually reached
    # the index.
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
# THE DIAGNOSTIC IS BOUNDED, THE COUNT IS NOT.  The failure this refusal
# describes is "a class nobody enumerated", and the realistic shape of it
# on a played session is one entry per capture -- so the entries are
# COUNTED as they stream past and only the first ${DIAGNOSTIC_LIMIT} names
# are kept.  The count in the message is exact either way, which is what
# an operator needs first; the names are what they need next, and eight of
# them identify the class as well as ten thousand would.
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
#
# assert_no_machine_files already refuses a checkpoint while bytecode is
# on disk, and this asks the complementary question: whatever is about
# to be published, is any of it a machine artifact or outside this
# feature?  It catches what the filesystem sweep cannot -- a *.pyc
# written between that sweep and this moment, or a path an interrupted
# earlier run left in the index -- and it is the check that has to pass
# for `git commit` to be reached.
#
# THE SWEEP IS STREAMED AND THE DIAGNOSTICS ARE BOUNDED.  The index it
# reads is the whole checkpoint -- one entry per capture -- so the entries
# are judged as they arrive and each refusal keeps an exact count and the
# first ${DIAGNOSTIC_LIMIT} names.
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

# staged_paths -- the repository-relative paths currently staged against
# HEAD, one per line.  Consumed by STREAMING it (`while read`), never by
# capturing it: the list is one line per capture on a checkpoint that
# stages the session.
staged_paths() {
    "${GIT}" diff --cached --name-only HEAD -- "${PATHSPECS[@]}" \
        2>/dev/null || printf ''
}

# anything_staged -- whether the index differs from HEAD under this
# feature's pathspec.  Git's own boolean: --quiet exits 1 when there IS a
# difference and 0 when there is none, and prints nothing either way.
#
# It replaces `[ -z "$(staged_paths)" ]`, which materialised one line per
# staged path -- every capture in the session -- to answer yes or no.
anything_staged() {
    if "${GIT}" diff --cached --quiet HEAD -- "${PATHSPECS[@]}" \
            2>/dev/null; then
        return 1
    fi
    return 0
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

# ---------------------------------------------------------------------
# SEALING THE EVIDENCE, AND PUBLISHING THE SEAL'S HEAD
#
# A review found that every attestation in this tree was mutable with the
# evidence it attested to: the digest ledger vouches for the frames, and
# an attacker who rewrites a frame rewrites its digest row in the same
# breath.  Recomputing the ledger from the forged frames agrees with
# itself, so no amount of internal consistency can answer the question.
#
# The answer has to come from outside the tree, and a commit is the only
# thing here that qualifies.  A commit object's name is a hash of its own
# content INCLUDING its message, so a value written into a commit message
# is fixed the moment the checkpoint is taken -- changing it changes the
# commit id and every id descending from it, which is a rewrite of
# published history rather than an edit of a file.
#
# So each checkpoint does two things beyond committing:
#
#   1. SEALS the evidence -- appends one chained row per artifact to
#      playthrough/build/evidence_anchor.jsonl, each row carrying the
#      artifact's sha256, its byte count, GIT'S OWN blob name for it, and
#      the previous row's chain hash.  The chain is append-only for the
#      same reason every other ledger here is.
#   2. PUBLISHES the chain's head as a trailer beside the checkpoint's
#      own, so the ledger cannot be rewritten without also rewriting the
#      history that names its head.
#
# THE ORDER IS LOAD-BEARING.  The seal is taken before the index is read
# for assert_commit_tree_matches_index, and the ledger is staged into the
# SAME commit that publishes its head -- so the commit contains both the
# seal and the claim about it, and the two cannot be separated afterwards.
#
# SEALING IS TRANSITIVE, which is why fifteen rows cover ten thousand
# frames.  build/frame_digests.jsonl carries a digest for every capture,
# so sealing that one file seals them all: substituting a frame breaks its
# digest row, repairing the digest row breaks the seal over the ledger,
# and repairing the seal breaks the chain and the head this commit
# published.
#
# A checkpoint that stages nothing seals nothing, and that is correct
# rather than a gap: an unchanged tree is already covered by the seal the
# previous checkpoint took.
readonly ANCHOR_TRAILER_KEY="Playthrough-Evidence-Anchor"

# The sealer, kept as data so the interpreter is handed a fixed program
# rather than an assembled one.  It reports three facts on stdout in
# KEY=value form: the head to publish, how many rows it added, and which
# artifacts do not exist yet -- the last so an early checkpoint can say
# what it could not seal instead of being silent about it.
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
#
#   FAIL-CLOSED.  A checkpoint whose seal could not be taken is not
#   committed at all: publishing evidence without the one artifact that
#   vouches for it from outside would leave the history asserting
#   something no later run could check.
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
    # The ledger belongs in the commit that publishes its head.  It is a
    # `build` path, so classify_path already accounts for it and
    # assert_tree_fully_staged would refuse the checkpoint if this add
    # were missing -- which is the intended direction of that mistake.
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
    # BOTH TRAILERS IN ONE PARAGRAPH so git reads them as a trailer
    # block: a blank line between them would make the second one body
    # text, and `git log --grep` would still find it while `git
    # interpret-trailers` would not.
    message+=("-m" "${TRAILER_KEY}: ${name}
${ANCHOR_TRAILER_KEY}: ${ANCHOR_HEAD}")
    # THE INDEX AS IT STANDS, READ BEFORE THE COMMIT.  Compared against
    # the tree the commit actually produced immediately afterwards, so
    # the window a review identified -- something mutating between the
    # validation and the publication -- cannot pass unnoticed even if it
    # somehow slipped past the quiescence lock.
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
#
# Every gate in this file runs against the index, and the commit is a
# separate operation afterwards.  A review put the gap plainly: mutation
# can occur after validation and staging and before the commit, and
# `git commit` reporting success says nothing about WHICH bytes it
# published -- only that it published the index it found, whatever that
# had become.
#
# The quiescence lock (see THE MUTATION LOCK) is the primary control and
# closes that window by excluding every producer.  This is the check
# that the window stayed closed, and the two are not redundant: a lock
# proves nobody else was allowed in, and this proves nobody got in.
#
# The comparison is on object names, not on file contents, so it is
# exact and cheap: `git ls-files --stage` names the blob for every index
# entry, `git ls-tree -r HEAD` names the blob for every entry of the
# published tree, and for the paths this checkpoint stages the two must
# agree object-for-object.  A path whose blob differs was rewritten
# between the two operations; a path that vanished from the tree was
# unstaged behind this step's back.
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

# verify_attribution_and_trailer NAME [ANCHOR_HEAD] -- the properties
# EVERY checkpoint has, whatever else it carries.  Shared, so the dossier
# commit is held to the same attribution rule as the other two rather
# than to a looser one written beside it.
#
# ANCHOR_HEAD is optional because one milestone legitimately has none:
# `integration` commits the two repository-wide rule files and touches no
# evidence, so it seals nothing and publishes nothing.  Every checkpoint
# that DID seal passes the head it sealed to, and gets it read back out of
# the commit -- because "the trailer was in the argv we handed git" is not
# the same claim as "the trailer is in the published history", and it is
# the second one the acceptance gate will make.
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

# ---------------------------------------------------------------------
# THE COMMIT THAT PUT THE CURRENT CONTENT THERE, WHICH IS NOT THE SAME
# AS THE COMMIT THAT FIRST CREATED THE PATH
#
# There used to be an `introducing_commit()` here -- `git log --format=%H
# -- PATH | tail -n 1`, the OLDEST commit that touched a path -- and the
# dossier ordering was asserted from it.  It is deleted rather than kept
# beside its replacement, because a helper that answers the wrong
# question is one call away from being used again.
#
# "When did this PATH first appear" is the wrong question for a tree that
# has been re-recorded.  The
# paths are reused across recordings -- playthrough/dossier.md and
# playthrough/frames/frame_00001.png exist in every generation -- so on a
# tree whose evidence has been replaced, the ordering check was reading
# commits belonging to a RETIRED survivor and reporting the ordering as
# proven for the current one.  Measured on this history: the dossier's
# oldest commit is from the first recording and the first capture's from
# the second, the ancestry holds between them, and neither commit has
# anything to do with the survivor whose files are in the tree.
#
# generation_commit() answers the question that matters: which commit put
# the content HEAD CARRIES NOW into the tree.  It is the NEWEST commit
# that changed the path, because any later commit touching it would have
# changed it again -- so this is exactly the commit that produced the
# current blob, and the ordering asserted from it is an ordering about
# the current recording.
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
#
# The save assertion below reads the requirement as "a commit after
# character creation AND a commit after the session closed", and refuses
# a `final` that carries no save because such a commit is the second of
# those two in name only.  That reasoning holds for the checkpoint that
# IS the second of the two.  It does not hold for a LATER one.
#
# The render cannot exist until the session is over: the film, the
# captioned film, the transcripts and the timeline are all computed from
# the finished record.  An operator who closes the session, checkpoints
# the save the engine just rewrote, and only then renders, has done
# exactly what the requirement asks -- and is then left holding a set of
# artifacts the requirement separately asks to be committed, with no
# userdir change to accompany them.  Refusing that commit would make the
# film uncommittable by the tool that exists to commit it.
#
# So the assertion accepts a `final` with no save when a PREVIOUS `final`
# of THIS SESSION already published one.
#
# "THIS SESSION" IS DECIDED BY ANCESTRY, AND THE REASON IS NOT
# THEORETICAL.  Retiring a superseded recording deletes files; it does
# not rewrite history, so that recording's own `final` checkpoint is
# still reachable from HEAD.  A carve-out phrased as "some reachable
# final carried a save" would therefore be satisfied by somebody else's
# session, and an operator who forgot to save and quit would sail
# through.  A retired session's final is NOT a descendant of this
# survivor's creation anchor, and that is exactly the discriminator --
# strictly, since a commit is not its own descendant.
# ---------------------------------------------------------------------
#
# THE ANCHOR IS A PARAMETER, defaulting to the one a checkpoint resolved.
# A checkpoint has already loaded CREATION_COMMIT by the time it asks; the
# read-only `status` subcommand has not, because it answers about a
# checkpoint it is not taking -- it resolves the anchor itself and passes
# it in.  One implementation answers both, so the preflight cannot drift
# from the refusal it is predicting.
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
#
# BOTH QUESTIONS ARE ASKED AS BOOLEANS.  "Is anything staged" and "is any
# of it under the userdir" were each answered by capturing a list of every
# staged path -- one line per capture, and a second list for the save --
# to test whether it was empty.  git answers both with --quiet and prints
# nothing at all.
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
    # The two properties the acceptance gate will look for next, asserted
    # here so this step cannot certify what that one rejects.
    #
    # ASKED AT ALL THREE POST-SESSION CHECKPOINTS, not only at `final`.
    # Both are reads of the HISTORY rather than of this one commit, so
    # they stay true once true, and re-asking them costs nothing while
    # catching a `media` or `attest` commit taken on a history that has
    # since lost the save or the dossier ordering.
    # assert_final_recorded_the_save already carries the case this needs:
    # when HEAD itself touched no save path it looks for an earlier
    # published `final` descending from this survivor's creation anchor,
    # which is exactly the shape a media-only or report-only commit has.
    if is_post_session_checkpoint "${name}"; then
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
    # staged: say which scope named the author.  A READ, not a write --
    # this step no longer records the pair into the checkout's own
    # configuration, and the note above report_identity_scope carries the
    # three reasons why.  The container gets the identity forwarded as
    # GIT_AUTHOR_* / GIT_COMMITTER_* by supported_env.sh instead.
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
    # The deliverable's own document, at the one checkpoint that
    # publishes a finished recording.  Beside the dossier because the two
    # are the same kind of requirement -- a written artifact whose
    # absence every other check would tolerate.
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

# ---------------------------------------------------------------------
# HAS THE SESSION BEGUN?
#
# Every trace a started session leaves, wherever it leaves it: a capture
# on the disk, a capture in the index, a row in the record, or a line in
# either sidecar the capture stage appends as it goes.  Any one of them is
# proof that play began, and the dossier checkpoint exists precisely to
# come BEFORE that moment.
#
# Read from the disk AND from the index, because the two answer different
# questions and only their union answers this one: the index answers "was
# it published", the filesystem answers "did it happen".
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
#
# The three session checkpoints REFUSE to run over a history whose
# .gitignore does not end in the terminal '!/playthrough/**' negation,
# and they are right to: without it a fresh clone re-ignores the engine's
# own '#<name>.sav' and '*.log' files and the save data is simply absent.
# But refusing was the whole of it -- the remedy was "commit them
# yourself, elsewhere, by hand", which left the one change this feature
# cannot work without outside the only tool that knows what it has to
# say.  A committer that owns the evidence and disowns the two rules the
# evidence depends on is a committer with a hole in it exactly where the
# silent failure lives.
#
# So this milestone owns them, and owns nothing else:
#
#   * the scope is EXACTLY .gitignore and .gitattributes.  Not
#     playthrough/, not a third root file, not a directory.  The index is
#     refused if it carries anything else, the two paths are added by
#     name, and the staged set is read back and required to be those two.
#   * the CONTENT is asserted BEFORE the commit, from the working tree,
#     because committing a .gitignore that does not end in the negation
#     would publish the silent failure rather than fix it.
#   * it is IDEMPOTENT.  When both files are already committed and
#     unmodified there is nothing to do, and it says so and exits zero
#     rather than manufacturing an empty commit.
#   * it is checked AFTER the commit through the same read-back the
#     session checkpoints use: HEAD must now carry both rules.
#
# It carries no survivor and no keystroke count in its message, because
# it is not about a session -- it is the one commit in this pipeline that
# would be identical whichever survivor was recorded.
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
    #
    # This used to count only the captures git already carries, which
    # asks whether the evidence was COMMITTED rather than whether it
    # EXISTS.  On the ordinary post-session tree -- captures written, the
    # record appended, nothing committed yet -- the count was zero and
    # the refusal did not fire, so a dossier commit taken there would
    # claim to precede a session that had already been played and whose
    # frames were sitting on the disk beside it.  The requirement is
    # about the ORDER OF EVENTS, so what is measured is whether the
    # session has left any trace at all, wherever that trace is.
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
    # ONE path, by name.  A dossier commit that also swept up the tooling
    # or the notes would be the bundled commit this step exists to split.
    #
    # THE SOUNDNESS QUESTIONS ARE STILL ASKED OF THE WHOLE TREE, even
    # though only one path is staged: this checkpoint also seals the
    # evidence, and a tree carrying a hard link or a planted credential
    # is not one whose dossier should be sealed and published as the
    # thing that came before play.
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

# do_media -- the artifacts DERIVED from the closed record.
#
# It is `final` minus the save and plus the film: the same gates, the same
# exhaustive staging, and one extra lifecycle question -- has the session
# actually been closed and published?  A media commit on a history with no
# `final` in it would be a film of a session whose record was never
# committed, so the ordering is asserted rather than assumed.
#
# assert_final_recorded_the_save, reached through verify_commit, is what
# makes this legal: when HEAD itself touches nothing under the userdir it
# looks for an earlier published `final` descending from this survivor's
# creation anchor.  A media-only commit is exactly that shape.
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

# do_attest -- the two reports, and the only step that publishes the
# acceptance report into the tree.
#
# The order inside it is the whole point of the split.  Every gate runs
# first, including the three questions asked of the measurement itself;
# only then is the report copied in; and the commit follows immediately,
# so the file this step creates is dirtied and committed within one step
# that either completes or leaves nothing for anybody to undo.  The gate
# that measured it wrote outside the checkout and touched none of this.
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

# assert_published_final NAME -- the session was closed and committed
# before anything derived from it is.
#
# `media` and `attest` are both ABOUT the finished session, so a history
# without a `final` in it cannot support either: the film would describe a
# record that was never published, and the report would cite a commit that
# does not exist.  published_final_for_this_session answers it against
# this survivor's creation anchor rather than against the trailer alone,
# so a previous survivor's `final` does not satisfy it.
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
#
# EVERY CALLER STREAMS IT.  The output is one line per path a checkpoint
# would add, which on a first checkpoint of a played session is one line
# per capture; the two questions asked of it -- "is there anything?" and
# "show me some of it" -- are both answered without it being held.
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
#
# BOTH halves are needed.  --dry-run answers for the WORKING TREE and
# says nothing about work a previous interrupted run already staged;
# diff --cached answers for the INDEX and says nothing about a file that
# has not been added yet.  Asking only one of them would let a second
# creation checkpoint through on the other one's blind spot.
#
# Each half is now a BOOLEAN rather than a captured population: one line
# of the preview, and git's own --quiet exit status for the index.
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
#
# The exact total and the first ${PREVIEW_LIMIT} lines, in ONE pass over
# the preview: `status` used to capture the whole thing into a variable
# and print all of it, which is one line per capture both in memory and on
# the operator's terminal.  A count they can read plus a sample they can
# scan is the report; the whole list is what `git status` is for.
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
#
# `final` refuses unless a `creation` checkpoint exists FOR THIS
# SURVIVOR and the record has grown since it.  Both halves are settled
# facts about the history and the record before any rendering starts --
# so a caller that is about to spend an hour producing the artifacts a
# checkpoint would carry can be told NOW that the checkpoint will not be
# taken.  run_pipeline.sh reads exactly this, before its first stage,
# for exactly that reason: the sequence used to discover the refusal at
# stage seven, after every expensive stage had already run.
#
# It is a REPORT, not a gate: this function refuses nothing, changes
# nothing, and answers with the same two predicates
# assert_creation_checkpoint enforces -- creation_commit_for_survivor
# and manifest_rows_at -- so there is one implementation and the report
# cannot drift from the refusal it predicts.
#
# FINAL_REASON is a stable token rather than prose, because a caller
# branches on it; the prose that explains it goes to stderr as usual.
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
#
# WHY THIS EXISTS AS A SUBCOMMAND.  The acceptance gate asks the same two
# questions of the tree it measures, and it has to: not every commit in
# this history is taken by this script -- a tooling change is committed
# with ordinary git, and this script's gates say nothing about a commit
# that never ran them.  Restating eleven regular expressions and a
# reviewed baseline inside the gate would be two copies of one rule set,
# which answer differently the first time either is updated.  So the gate
# runs this.
#
# READ-ONLY, AND IT TAKES NO LOCK, like `status` beside it.  That is not
# tidiness: the gate holds this checkout's mutation lock EXCLUSIVELY while
# it measures, so a subcommand that acquired it would deadlock against
# its own caller.  Nothing here writes, stages or commits, so there is
# nothing for a lock to protect.
#
# It refuses on the first failure rather than reporting both, because the
# two are not independent -- a hard link into the tree is a reason to stop
# looking at content and go and find out how it got there.
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
    # The evidence gates report here instead of dying, because `status`
    # exists to be run when something is wrong.
    # ROWS IS A COUNT IN EVERY STATE, INCLUDING NONE.  It used to be
    # left EMPTY when there was no manifest, while FRAMES beside it
    # reported 0 -- so on a tree between a retirement and its re-record
    # the two fields disagreed about the same empty record, and a reader
    # comparing them (this page documents exactly that comparison) had to
    # know that one absence is spelled `0` and the other is spelled
    # nothing.  An empty record has zero rows.
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
                "playing their session."
        fi
    fi
    # THE ANSWER A CALLER BRANCHES ON, computed with the same two
    # predicates the refusal uses, and reported whether or not the
    # newest creation happens to be the anchor.  The warning above is
    # about the NEWEST checkpoint; this is about the one `final` would
    # actually anchor to, which may be an older commit entirely.
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
    # AND WOULD '${CHECKPOINT_MEDIA}' BE TAKEN?  A DIFFERENT QUESTION,
    # and the one an automated caller actually needs.
    #
    # run_pipeline.sh takes '${CHECKPOINT_MEDIA}', not
    # '${CHECKPOINT_FINAL}': the film, the transcripts and the timeline
    # are what a render produces, and the session's own save was
    # published by hand when the session closed.  '${CHECKPOINT_MEDIA}'
    # therefore asserts something '${CHECKPOINT_FINAL}' does not -- that
    # a '${CHECKPOINT_FINAL}' for THIS survivor is already in the
    # history -- and a preflight that reported only FINAL_ELIGIBLE would
    # answer 'yes' for a session whose save has not been committed yet
    # and let the caller spend the whole render to be refused at the
    # checkpoint.  That is the exact failure the preflight exists to
    # prevent, so the question is answered here too, with the same
    # predicate the refusal uses.
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
    # AND THE CHECKOUT'S MUTATION LOCK, EXCLUSIVELY.  The lock above
    # keeps two checkpoints apart, which was never the whole problem: a
    # session step appending a frame, or a producer republishing the
    # movie, could land between the gate that passed and the commit that
    # publishes -- and the commit would then carry a tree no gate ever
    # saw, with every individual lock correctly held throughout because
    # no two holders were ever the same stage.  Taken here, once, for
    # every MUTATING subcommand, so the staging sweep, the validation and
    # the commit all sit inside one window.  `status` does not reach this
    # function, and must not: a read that blocks behind a producer is a
    # reporting tool that stops working exactly when it is needed.
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
