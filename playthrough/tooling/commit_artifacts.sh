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
#   * staged changes OUTSIDE .gitignore, .gitattributes and playthrough/
#     -- those would be swept into the checkpoint by the commit, since a
#     commit publishes the whole index and not just this run's pathspecs
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
#   * a manifest that does not verify against the frames, or a frame
#     count, row count and observation count that disagree
#   * a keybindings file that binds any debug action
#   * for `final`: no `creation` checkpoint in the history, or a
#     manifest that has not grown since it -- both of which mean the
#     session was not recorded between the two commits
#
# WHAT IT DOES NOT DO
# No history rewriting, no amend, no force, no push, no branch change,
# no tag, no reset, no clean, and no `git config`.  It stages three
# pathspecs and commits.  Every git call is an argument list; there is
# no eval, no `shell=True` equivalent, and no unquoted glob.
#
# STAGING IS BY PATHSPEC, WHICH IS THE BATCHING.  `git add -A --
# .gitignore .gitattributes playthrough` hands git three arguments and
# lets git walk the tree, so several hundred frames never become several
# hundred argv entries and the argument-list limit is not approached at
# any session length.  Expanding the glob in the shell first would be
# the version of "batching" that has a limit to respect.
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
if ! playthrough_require_tools git find wc sort grep tr; then
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

# ---------------------------------------------------------------------
# The lifecycle vocabulary.
# ---------------------------------------------------------------------

# The trailer key and the two checkpoint names.  `final` searches the
# history for the `creation` trailer, so these three strings are the
# lifecycle's entire persistent state -- there is no side file to fall
# out of step with the history it describes.
readonly TRAILER_KEY="Playthrough-Checkpoint"
readonly CHECKPOINT_CREATION="creation"
readonly CHECKPOINT_FINAL="final"

# The subjects.  Written here rather than passed in, because a
# checkpoint whose message a caller chooses is a checkpoint whose
# meaning drifts between runs.
readonly SUBJECT_CREATION="Commit the survivor's creation and the save \
it produced"
readonly SUBJECT_FINAL="Commit the closed session, its final save and \
its artifacts"

# The three pathspecs this file will ever stage.  Anything else in the
# repository is somebody else's change and is left exactly as found.
readonly -a PATHSPECS=(".gitignore" ".gitattributes" "playthrough")

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
            "nothing.  THIS SCRIPT WILL NOT SET user.name OR" \
            "user.email, in any scope -- the identity a commit is made" \
            "under belongs to the platform, and a script that" \
            "configures it around a missing one hides the very thing" \
            "that needs fixing.  Supply it the way the platform" \
            "supplies it: its own git configuration, or the standard" \
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
# so anything already staged outside this feature's three pathspecs
# would ride along inside a checkpoint that claims to be about the
# playthrough.  That is refused.  Unstaged and untracked changes
# outside them cannot ride along -- `git add` is given pathspecs and
# cannot reach past them -- so those are reported and left alone.
# ---------------------------------------------------------------------

# in_scope PATH -- true when a repository-relative path is one this file
# is allowed to commit.
in_scope() {
    local path="$1"
    case "${path}" in
        .gitignore|.gitattributes) return 0 ;;
        playthrough|playthrough/*) return 0 ;;
    esac
    return 1
}

assert_scope() {
    local staged=() path
    # -z is the only format that survives a path with a space, a quote
    # or a newline in it; --diff-filter is deliberately absent so a
    # staged deletion counts too.
    while IFS= read -r -d '' path; do
        if ! in_scope "${path}"; then
            staged+=("${path}")
        fi
    done < <("${GIT}" diff --cached --name-only -z HEAD --)
    if [ "${#staged[@]}" -gt 0 ]; then
        die "${EX_SCOPE}" "the index already carries changes outside" \
            "this feature: ${staged[*]}.  A commit publishes the whole" \
            "index, so those would be swept into a checkpoint that" \
            "says it is about the playthrough.  Unstage them" \
            "('git restore --staged -- <path>') and run this again." \
            "Nothing was committed."
    fi
    return 0
}

report_foreign_worktree_changes() {
    local foreign=() path status origin
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
# ---------------------------------------------------------------------

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


grave_path, memorial_path, prose_path, manifest_path, character = (
    sys.argv[1:])
grave = load_object(grave_path, "the graveyard save")
player = grave.get("player")
if not isinstance(player, dict) or player.get("name") != character:
    fail("the graveyard save does not name %r as its player" % character)
if grave.get("debug_mode") is not False:
    fail("the graveyard save does not record debug_mode=false")

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
    if [ ! -f "${world_dir}/master.gsav" ]; then
        die "${EX_EVIDENCE}" "$(rel "${world_dir}") holds no" \
            "master.gsav, so the world has not been saved.  Save and" \
            "quit through the game's own menu first."
    fi
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        saves+=("${path}")
    done < <("${FIND}" "${world_dir}" -mindepth 1 -maxdepth 1 \
        -type f -name '#*.sav' -print 2>/dev/null | "${SORT}")
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
    local expected="${world_dir}/#${LOADED_ENCODED}.sav"
    if [ "${expected}" != "${SAVE_FILE}" ]; then
        die "${EX_EVIDENCE}" "the engine last loaded" \
            "'${LOADED_CHARACTER}', whose save file would be" \
            "$(rel "${expected}"), and the only save on disk is" \
            "$(rel "${SAVE_FILE}").  A checkpoint cannot say which" \
            "survivor it is about, so it says nothing.  Nothing was" \
            "committed."
    fi
    CHARACTER_NAME="${LOADED_CHARACTER}"
    ENCODED_CHARACTER="${LOADED_ENCODED}"
    PERSISTENCE_KIND="live"
    REQUIRED_PERSISTENCE_FILES=(
        "${SAVE_FILE}"
        "${world_dir}/master.gsav"
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
            -type f -name '#*.sav' -print 2>/dev/null | "${SORT}")
    fi
    local expected_name="#${ENCODED_CHARACTER}.sav"
    if [ "${#grave_saves[@]}" -ne 1 ] ||
       [ "${grave_saves[0]##*/}" != "${expected_name}" ]; then
        die "${EX_EVIDENCE}" "the final checkpoint has no live survivor" \
            "and the graveyard holds ${#grave_saves[@]} character" \
            "save(s), not exactly the pinned survivor" \
            "${expected_name}: ${grave_saves[*]:-none}.  A manual" \
            "deletion is not a death ending.  Nothing was committed."
    fi
    local grave_save="${grave_saves[0]}"
    local grave_log="${grave_save%.sav}.log"
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

    if ! "${PLAYTHROUGH_PYTHON}" -c "${DEATH_EVIDENCE_READER}" \
            "${grave_save}" "${memorial_json[0]}" \
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
            -type f -name '#*.sav' -print 2>/dev/null |
            "${WC}" -l | "${TR}" -d ' ')"
        if [ "${live_count}" -gt 0 ]; then
            assert_live_save "${world_dir}"
        elif [ "${checkpoint}" = "${CHECKPOINT_FINAL}" ]; then
            assert_death_persistence "${world_dir}"
        elif [ ! -f "${world_dir}/master.gsav" ]; then
            die "${EX_EVIDENCE}" "$(rel "${world_dir}") holds no" \
                "master.gsav, so the world has not been saved.  Save" \
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
    playthrough_log "${FRAME_COUNT} capture(s), ${ROW_COUNT} row(s)," \
        "and the sidecar agrees"
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

assert_creation_checkpoint() {
    CREATION_COMMIT="$(creation_commit)"
    readonly CREATION_COMMIT
    if [ -z "${CREATION_COMMIT}" ]; then
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
    playthrough_log "the session grew from ${before} to ${ROW_COUNT}" \
        "row(s) since ${CREATION_COMMIT:0:10}"
    return 0
}


# ---------------------------------------------------------------------
# STAGING AND COMMITTING.
# ---------------------------------------------------------------------

# stage_artifacts -- add the three pathspecs, deletions included.
#
# -A so that a file the engine removed between checkpoints is recorded
# as removed rather than left behind in the index as a ghost.
stage_artifacts() {
    if ! "${GIT}" add -A -- "${PATHSPECS[@]}"; then
        die "${EX_COMMIT}" "git could not stage" \
            "${PATHSPECS[*]}.  Nothing was committed."
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
    local ignore=0
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
            .gitignore|.gitattributes) ignore=1 ;;
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
    [ "${ignore}" -eq 1 ] && classes+=("version-control attributes")
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

verify_commit() {
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
    local leftover
    leftover="$("${GIT}" status --porcelain -- "${PATHSPECS[@]}" \
        2>/dev/null || printf '')"
    if [ -n "${leftover}" ]; then
        die "${EX_COMMIT}" "these paths are still uncommitted after" \
            "the checkpoint: ${leftover}.  Everything under" \
            "$(rel "${PLAYTHROUGH_DIR}") is evidence and a checkpoint" \
            "that left some of it behind has not done its job."
    fi
    assert_tracked_at_head
    playthrough_log "the checkpoint is verified: attribution," \
        "trailer, a clean tree and every artifact class tracked"
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
# The two checkpoints run the SAME gates in the same order, and differ
# only in the lifecycle assertion `final` adds.  Keeping the gate list
# identical is deliberate: a checkpoint with a weaker gate is a
# checkpoint somebody takes when the other one refuses.
# ---------------------------------------------------------------------

run_common_gates() {
    local checkpoint="$1"
    assert_identity
    assert_repository
    assert_scope
    report_foreign_worktree_changes
    assert_no_machine_files
    assert_save_tree "${checkpoint}"
    assert_evidence
    assert_no_debug_bindings
    return 0
}

do_creation() {
    run_common_gates "${CHECKPOINT_CREATION}"
    # A `creation` checkpoint taken when one already exists is either a
    # re-run over an unchanged tree -- which commit_checkpoint handles by
    # doing nothing -- or a second creation in one history, which would
    # make the trailer search ambiguous for every later `final`.
    local existing
    existing="$(creation_commit)"
    if [ -n "${existing}" ] && has_pending_changes; then
        die "${EX_LIFECYCLE}" "a '${CHECKPOINT_CREATION}' checkpoint" \
            "already exists (${existing}) and there are further" \
            "changes to record.  A second creation checkpoint would" \
            "make '${TRAILER_KEY}: ${CHECKPOINT_CREATION}' match two" \
            "commits and the lifecycle would no longer name a single" \
            "moment.  Those changes belong to the" \
            "'${CHECKPOINT_FINAL}' checkpoint or to an ordinary" \
            "commit.  Nothing was committed."
    fi
    stage_artifacts
    commit_checkpoint "${CHECKPOINT_CREATION}" "${SUBJECT_CREATION}"
    if [ "${COMMITTED}" = "yes" ]; then
        verify_commit "${CHECKPOINT_CREATION}"
    fi
    report "${CHECKPOINT_CREATION}" "$(creation_commit)"
    return 0
}

do_final() {
    run_common_gates "${CHECKPOINT_FINAL}"
    assert_creation_checkpoint
    stage_artifacts
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
staged_paths_preview() {
    "${GIT}" add -A --dry-run -- "${PATHSPECS[@]}" 2>/dev/null ||
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
            "both checkpoints would refuse.  Configure the platform's" \
            "identity; this script will not write user.name or" \
            "user.email into the repository."
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
    emit "CHECKPOINT" "status"
    emit "COMMITTED" "no"
    emit "COMMIT" ""
    emit "AUTHOR" "${IDENT_AUTHOR}"
    emit "WORLD" "${world}"
    emit "CHARACTER" "${character}"
    emit "FRAMES" "${frames}"
    emit "ROWS" "${rows}"
    emit "CREATION" "${creation}"
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
            "creation" "commit the survivor and the save she starts \
from" \
            "final" "commit the closed session and its artifacts" \
            "status" "report the lifecycle, changing nothing" \
            "help" "this text"
        printf '%s\n' ""
        printf '%s\n' "It stages .gitignore, .gitattributes and \
playthrough/ and nothing"
        printf '%s\n' "else.  It never writes git configuration, never \
rewrites history,"
        printf '%s\n' "and never pushes.  An identity that does not \
resolve is a refusal:"
        printf '%s\n' "configure the platform, not the repository."
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
        "${CHECKPOINT_CREATION}")
            do_creation
            ;;
        "${CHECKPOINT_FINAL}")
            do_final
            ;;
        status)
            do_status
            ;;
        '')
            usage 2
            die "${EX_USAGE}" "which checkpoint?  There is no default:" \
                "the two commits mean different things and taking the" \
                "wrong one is not something a default can be right" \
                "about."
            ;;
        *)
            usage 2
            die "${EX_USAGE}" "unknown subcommand '${subcommand}'"
            ;;
    esac
    return "${EX_OK}"
}

main "$@"

