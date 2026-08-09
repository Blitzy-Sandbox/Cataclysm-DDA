#!/bin/bash
# ---------------------------------------------------------------------
# playthrough/tooling/run_pipeline.sh
#
# THE POST-SESSION SEQUENCER.  It runs the render stages in dependency
# order, reports what each one did, stops at the first failure, and
# contains no logic of its own.
#
# BASH IS REQUIRED rather than optional: BASH_SOURCE locates this file,
# arrays carry every stage as an argument list instead of a string, and
# `local` scopes each helper.  The interpreter is spelled the way the
# two scripts this one takes its shape from spell it --
# build-scripts/clang-tidy-run.sh:1 and build-scripts/build.sh:1 -- and
# the way this folder's embed_captions.sh spells it.
#
# USAGE
#     playthrough/tooling/run_pipeline.sh
#     playthrough/tooling/run_pipeline.sh --from render
#     playthrough/tooling/run_pipeline.sh --only verify
#     playthrough/tooling/run_pipeline.sh --from verify
#     playthrough/tooling/run_pipeline.sh --no-commit
#     playthrough/tooling/run_pipeline.sh --help
#
# ---------------------------------------------------------------------
# THE STAGES, IN THE ONLY ORDER THEY CAN RUN IN
#
#   1 timeline      timeline.py           manifest.jsonl
#                                           -> timeline.json
#   2 transitions   make_transitions.py   timeline.json + frames/
#                                           -> build/transitions/*.png
#   3 render        render_movie.py       timeline.json + frames/
#                                         + build/transitions/
#                                           -> cata-play.mp4
#   4 srt           make_srt.py           timeline.json
#                                           -> transcript.srt + .md
#   5 captions      embed_captions.sh     cata-play.mp4 + transcript.srt
#                                           -> cata-play-cc.mp4
#   6 verify        verify_artifacts.sh --phase pre-commit
#                                         the artifacts -> the gate
#   7 commit        commit_artifacts.sh final
#                                         everything -> the commit
#   8 attest        verify_artifacts.sh --phase post-commit
#                                         the history -> the gate again
#
# The order is forced by real data dependencies, not by taste:
#
#   * make_transitions.py reads the transition_after flags, so the
#     timeline has to exist first;
#   * render_movie.py names the materialised transition images in the
#     list it hands the encoder, so they have to be on disk BEFORE it
#     writes that list -- a transition composed afterwards would be
#     referenced by nothing and the film would be paced without it;
#   * embed_captions.sh needs both the film and the cue file;
#   * the gate's functional half runs BEFORE commit_artifacts.sh, so
#     nothing that fails it can reach the history;
#   * the gate's history half runs AFTER it, because a commit is what
#     makes its questions answerable at all.
#
# make_srt.py reads only the timeline and could therefore run any time
# after stage 1.  It is kept at position 4 because that is the order the
# feature plan states, and there is nothing to gain from moving it.
#
# ---------------------------------------------------------------------
# WHY THE GATE IS TWO STAGES, AND WHAT THE ONE-STAGE VERSION DID
#
# verify_artifacts.sh asks two kinds of question.  Most of its checks are
# FUNCTIONAL and can be answered as soon as the artifacts exist.  Twelve
# are about the HISTORY -- is the character save tracked, is every
# artifact class committed, is the tree clean, do the checkpoint trailers
# name one survivor -- and those cannot be true before the commit,
# because the commit is what makes them true.
#
# Sequencing the whole gate once, ahead of the commit, therefore could
# not succeed.  Measured on a genuine post-session tree: the gate
# reported "9 of 108 checks FAILED", every one of them a tracking or
# clean-tree question, the sequence stopped at that stage, and the run
# ended with the commit stage UNATTEMPTED.  The default plan -- the one
# an operator reaches for -- could not reach the checkpoint at all, and
# the failure looked like a broken artifact rather than a stage in the
# wrong place.
#
# So the gate is split by phase and appears twice: `verify` runs
# --phase pre-commit and guards the commit, `attest` runs
# --phase post-commit and reports what the commit published.  Neither
# repeats the other's checks; together they are the whole gate.
#
# ---------------------------------------------------------------------
# THE GATE PRECEDES THE COMMIT, AND THAT IS NOT A DEFAULT
#
# There is no option here that runs commit_artifacts.sh without the
# pre-commit gate having passed in the same invocation.  A film that is
# entirely black, or a caption track that has drifted out of step with
# the pictures, is a run in which every count still tallies and only the
# gate says otherwise -- so an option that turned the gate off would
# defeat the whole acceptance model rather than merely loosen it.
# --no-commit exists (committing is a deliberate act, and an operator may
# want to take it by hand), and it drops the attestation with the
# checkpoint; the opposite of --no-commit does not exist.  Asking for the
# commit stage alone is refused, and so is asking for the attestation
# alone, both with the message naming --from verify.
#
# ---------------------------------------------------------------------
# WHAT THIS FILE DELIBERATELY DOES NOT DO
#
#   * IT DOES NOT LAUNCH THE GAME AND IT DOES NOT CAPTURE.  That is
#     launch_game.sh, session.py and capture.sh, and it happens DURING
#     the session, one keystroke at a time, with a person reading each
#     frame and deciding in character before the next key is sent.  This
#     file runs after the last capture, over evidence that already
#     exists.  Nothing here sends a keystroke.
#   * IT HOLDS NO STAGE'S LOGIC.  No duration bound, no encoder flag, no
#     caption codec, no cue arithmetic, no crop rectangle, no staging
#     list, no git plumbing.  Every one of those lives in the module
#     that owns it, so a change to any of them touches exactly one file
#     and cannot leave two disagreeing copies behind.
#   * IT DOES NOT RE-IMPLEMENT VERIFICATION.  It runs
#     verify_artifacts.sh and reads its exit status.
#   * IT WRITES NOTHING INTO THE WORKING TREE.  Not one artifact, not
#     one byte into playthrough/frames/ -- that directory holds exactly
#     one capture per keystroke, and the whole one-frame-per-keystroke
#     acceptance gate rests on its purity.  The only file this script
#     itself creates is its lock, which lives in the mode-0700 runtime
#     directory env.sh verifies, outside the checkout.
#   * IT PUBLISHES NOTHING AND REWRITES NO HISTORY.  commit_artifacts.sh
#     commits locally and stops; distribution is out of scope, and this
#     file adds no way to reach for it.
#   * IT FABRICATES NOTHING.  It produces no artifact of its own, so
#     there is nothing here that could retime a frame, invent a cue or
#     substitute a clock reading.  It only starts the modules that read
#     what the session recorded.
#
# ---------------------------------------------------------------------
# WHY env.sh IS SOURCED HERE, EXACTLY ONCE
#
# env.sh is the single definition of the headless contract and of every
# artifact path.  Sourcing it once at the head of the sequence puts that
# contract in force for all seven stages through the environment they
# inherit, rather than leaving each one to find it again:
#
#   * PYTHONDONTWRITEBYTECODE=1 [env.sh] is the one that MUST be
#     inherited.  .gitignore ignores __pycache__ and *.pyc everywhere
#     else in this repository, but the terminal `!/playthrough/**`
#     negation re-includes them inside this tree -- so a Python stage
#     run without that variable would manufacture committable bytecode
#     beside the tooling.  It is prevented at the source instead of
#     being re-excluded afterwards, because the negation has to stay the
#     last pattern in the file.  Each Python stage is additionally given
#     -B, which is the same instruction spelled on the command line;
#     the two together are what make the "no bytecode after a run"
#     check a property rather than a hope.
#   * The video driver is x11 and never the value that renders zero
#     pixels.  env.sh establishes that unconditionally and asserts it
#     again before it returns, so this file has no such variable of its
#     own to get wrong: there is deliberately not one line here that
#     sets it.
#   * PLAYTHROUGH_PYTHON is the interpreter env.sh resolved and
#     VERIFIED.  The Python stages are started through it rather than
#     through a name looked up on PATH, because the pinned closure the
#     render stages need lives in that interpreter and a PATH lookup on
#     a host with more than one Python finds whichever comes first.
#     capture.sh, commit_artifacts.sh and preflight_capture.sh all
#     spell it the same way.
#
# Sourcing env.sh can FAIL -- a malformed clone index, a runtime
# directory it cannot secure, a contract that does not carry x11 -- and
# a failure is fatal here rather than a warning, because every stage
# below would otherwise run under a contract nobody established.
#
# ---------------------------------------------------------------------
# THE CHECKPOINT THIS FILE TAKES
#
# commit_artifacts.sh requires a checkpoint and deliberately has no
# default: `creation` and `final` mean different things and taking the
# wrong one is not something a default can be right about.  This
# sequencer is post-session by definition, so the checkpoint it takes is
# `final`, spelled once as a constant below.  The `creation` checkpoint
# belongs BEFORE the session -- it commits the survivor and the save she
# starts from, at a point where no frame exists yet -- so it is taken by
# hand, by running commit_artifacts.sh directly.  That is also why no
# flag here selects a checkpoint: the argument surface stays small, and
# this file keeps no copy of a list that belongs to the module it calls.
#
# ---------------------------------------------------------------------
# OUTPUT CONTRACT
#
# STDOUT IS A MACHINE CHANNEL: KEY=value lines only, as every stage in
# this folder publishes.  Each stage's own KEY=value output passes
# through untouched, and this file's own lines are prefixed PIPELINE_ so
# the two cannot be confused:
#
#     PIPELINE_PLAN          the stages this run intends, in order
#     PIPELINE_SKIPPED       the stages it was told to leave out
#     PIPELINE_CHECKPOINT    the checkpoint the commit stage takes
#     PIPELINE_STAGE_<NAME>  pass | fail, one per stage attempted
#     PIPELINE_FAILED_STAGE  the stage that stopped the run
#     PIPELINE_STATUS        the exit status this run ends with
#     PIPELINE_ELAPSED       whole seconds from first stage to last
#     PIPELINE               pass | fail
#
# Banners, warnings and diagnostics go to STDERR through env.sh's
# helpers, so a caller can keep the two apart.  A stage's own output is
# never captured or buffered: it appears as it is produced, because an
# operator reading a long render wants to see it move.
#
# ---------------------------------------------------------------------
# EXIT CODES
#     0  every stage in the plan passed
#     1  usage error -- an unknown option, an unknown stage name, or a
#        plan this file will not run
#     2  layout error -- this file cannot locate itself, this is not the
#        checkout it belongs to, a stage is missing, or env.sh refused
#        to load
#     3  another run of this sequencer holds the lock over this checkout
#     *  otherwise THE FAILING STAGE'S OWN EXIT STATUS, passed through
#        unchanged, because those codes carry diagnosis that a code of
#        this file's own would throw away (embed_captions.sh 8 is a
#        missing prerequisite, commit_artifacts.sh 3 is an unresolved
#        identity, and so on).  PIPELINE_FAILED_STAGE names which stage
#        it came from.  supported_env.sh passes an inner status through
#        for the same reason.
# ---------------------------------------------------------------------

set -euo pipefail

# errtrace propagates the ERR trap into functions, so an unexpected
# failure reports its line number instead of vanishing.  A strict
# addition to `set -euo pipefail`, never a replacement for it.
set -o errtrace

# The handler is a function so the trap string stays trivial.
#
# SC2317 fires because ShellCheck does not model a trap as a call site,
# so the body reads as unreachable to it.  env.sh, embed_captions.sh and
# commit_artifacts.sh carry the same directive for the same reason.
#
# A STAGE'S OWN FAILURE DOES NOT COME THROUGH HERE.  Each stage is run
# as the left operand of a `||`, which bash exempts from the ERR trap,
# and its status is read there deliberately.  So a line number reported
# by this handler is always a fault in THIS file rather than in a stage,
# which is exactly what makes it worth printing.
# shellcheck disable=SC2317
_rp_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "run_pipeline.sh failed at line ${2} (exit ${1})" >&2
}
trap '_rp_on_error "$?" "${LINENO}"' ERR

# ---------------------------------------------------------------------
# Exit codes, named so the call sites read as intent.  Declared before
# anything else can fail, because the first two failures this file can
# suffer -- not finding itself, and not finding env.sh -- happen before
# any other definition exists.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_LAYOUT=2
readonly EX_BUSY=3

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment and
# the artifact layout.
#
# The resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8, as capture.sh, launch_game.sh,
# embed_captions.sh and preflight_capture.sh all adopt it.  Deriving
# every path from BASH_SOURCE is what keeps this file correct no matter
# which directory it is invoked from, and it is why no stage is ever
# named as a bare word that PATH could resolve to something else.
# ---------------------------------------------------------------------
SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${SCRIPT_DIR}" ]; then
    printf '%s\n' "run_pipeline.sh: FATAL: cannot resolve my own \
directory" >&2
    exit "${EX_LAYOUT}"
fi
readonly SCRIPT_DIR

SCRIPT_REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." >/dev/null 2>&1 && pwd)"
if [ -z "${SCRIPT_REPO_ROOT}" ]; then
    printf '%s\n' "run_pipeline.sh: FATAL: cannot resolve the \
repository root from ${SCRIPT_DIR}" >&2
    exit "${EX_LAYOUT}"
fi
readonly SCRIPT_REPO_ROOT

# ---------------------------------------------------------------------
# ASSERT THIS IS THE CHECKOUT, BEFORE ANYTHING RUNS
#
# Two landmarks, checked here rather than left to surface later as an
# unexplained stage failure.  env.sh makes its own check -- it refuses a
# root with no data/ and no src/path_info.cpp -- and these two are
# additional rather than a restatement: the Makefile is the build system
# every stage's inputs were produced by, and the sidebar widget is the
# file the clock geometry is derived from, so a tree missing either is
# not a tree this pipeline can be run over.
# ---------------------------------------------------------------------
for _rp_landmark in "Makefile" "data/json/ui/sidebar.json"; do
    if [ ! -e "${SCRIPT_REPO_ROOT}/${_rp_landmark}" ]; then
        printf '%s\n' "run_pipeline.sh: FATAL: \
${SCRIPT_REPO_ROOT} has no ${_rp_landmark}, so it is not the \
Cataclysm-DDA checkout this pipeline belongs to" >&2
        exit "${EX_LAYOUT}"
    fi
done
unset _rp_landmark

if [ ! -d "${SCRIPT_DIR}" ] || [ ! -r "${SCRIPT_DIR}" ]; then
    printf '%s\n' "run_pipeline.sh: FATAL: ${SCRIPT_DIR} is not a \
readable directory" >&2
    exit "${EX_LAYOUT}"
fi

_rp_env_file="${SCRIPT_DIR}/env.sh"
if [ ! -f "${_rp_env_file}" ]; then
    printf '%s\n' "run_pipeline.sh: FATAL: missing ${_rp_env_file}; \
the headless contract and the artifact layout live there and are never \
redefined here" >&2
    exit "${EX_LAYOUT}"
fi

# The working directory is the repository root for every stage of this
# pipeline, and it is set BEFORE env.sh is sourced because env.sh
# documents itself as sourced from there.  The requirement is the
# engine's rather than a preference: the asset roots and the userdir are
# resolved against the process working directory
# [src/path_info.cpp:105,127-137], and every path these stages report is
# repository-relative, which is only correct from here.
cd "${SCRIPT_REPO_ROOT}"

# env.sh defines the helpers used below -- playthrough_log,
# playthrough_warn, playthrough_die, playthrough_rel,
# playthrough_validate_int, playthrough_acquire_lock and
# playthrough_release_lock -- and exports the contract every stage
# inherits.  None of it is restated in this file.
#
# The `source=` directive lets `shellcheck -x` follow env.sh and check
# every helper and variable used here against it.  SC1091 is suppressed
# only for a plain `shellcheck` run, which cannot follow a sourced file
# and would report the resolved path as unreadable; the file's presence
# is asserted immediately above, so nothing is hidden.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_rp_env_file}"; then
    printf '%s\n' "run_pipeline.sh: FATAL: ${_rp_env_file} refused to \
load; fix the environment contract before rendering anything" >&2
    exit "${EX_LAYOUT}"
fi
unset _rp_env_file

# env.sh resolves the repository root from its own location, by the same
# idiom and from the same directory, so the two answers agree in every
# tree this file belongs to.  They are compared rather than assumed
# equal because a disagreement would mean the folder had been split
# across two locations, and the stages -- which take env.sh's answer --
# would then be reading a different checkout from the one asserted
# above.  That is a fault to stop on, not one to average out.
if [ "${PLAYTHROUGH_REPO_ROOT}" != "${SCRIPT_REPO_ROOT}" ]; then
    playthrough_die "env.sh resolved this checkout to" \
        "'${PLAYTHROUGH_REPO_ROOT}' while this file resolved it to" \
        "'${SCRIPT_REPO_ROOT}'.  One of the two is not where it" \
        "belongs, so no stage is run." || true
    exit "${EX_LAYOUT}"
fi
readonly REPO_ROOT="${PLAYTHROUGH_REPO_ROOT}"

if [ ! -d "${REPO_ROOT}/playthrough/tooling" ]; then
    playthrough_die "there is no playthrough/tooling under" \
        "'${REPO_ROOT}', so there are no stages to sequence" || true
    exit "${EX_LAYOUT}"
fi

# ---------------------------------------------------------------------
# THE CONTRACT, spelled as constants.  Each appears exactly once.
# ---------------------------------------------------------------------

# The checkpoint the commit stage takes.  See THE CHECKPOINT THIS FILE
# TAKES in the header: this sequencer is post-session, so `final` is the
# only checkpoint it can be right about, and `creation` is taken by hand
# before the session starts.
readonly PIPELINE_CHECKPOINT_NAME="final"

# The stage that must have passed in this invocation before the commit
# stage may run, and the stage it guards.  Named rather than open-coded
# so the rule below reads as the rule it is.
readonly GATE_STAGE="verify"
readonly COMMIT_STAGE="commit"
# The second gate run, after the checkpoint.  See WHY THE GATE RUNS TWICE
# in the header.
readonly ATTEST_STAGE="attest"

# WHY THE GATE RUNS TWICE, AND WHAT EACH RUN IS FOR.
#
# The acceptance gate asks two different kinds of question.  Most of its
# checks are FUNCTIONAL -- is the film watchable, do the captions line up
# with the frames, does every capture match its attestation -- and those
# can be answered the moment the artifacts exist.  Twelve of them are
# about the HISTORY: is the save tracked, is every artifact class
# committed, is the tree clean, do the checkpoint trailers name one
# survivor.  Those cannot be answered before the commit, because the
# commit is what makes them true.
#
# Running the whole gate once, ahead of the commit, therefore FAILED BY
# CONSTRUCTION: measured as "9 of 108 checks FAILED" on a genuine
# post-session tree, which stopped the sequence and left the commit stage
# unattempted -- so the one plan an operator would reach for could never
# reach the checkpoint at all.
#
# So the functional half runs first and guards the commit, and the
# history half runs after it and attests to what was published.  Both are
# the same script with a --phase argument; neither duplicates the other.
readonly GATE_PHASE_ARGUMENT="--phase"
readonly GATE_PRE_COMMIT_PHASE="pre-commit"
readonly GATE_POST_COMMIT_PHASE="post-commit"

# The lock this run holds over the checkout.  Two sequencers over one
# checkout would interleave their writes into one set of artifacts --
# one computing a timeline while the other encodes from it -- so the
# second waits and then stops rather than racing the first.
#
# THE NAME CARRIES A DIGEST OF THIS CHECKOUT, and that is a fix rather
# than a flourish.  A bare name is a name in PLAYTHROUGH_LOCK_DIR, which
# hangs off PLAYTHROUGH_RUNTIME_DIR and is derived from CLONE_INDEX -- so
# two clones started without CLONE_INDEX share one lock directory and one
# lock, and a run over a completely different working tree blocked this
# one while the diagnosis claimed the lock was "over this checkout".
# Keying it on the repository root makes the claim true.  The basename is
# this file's own: the stages take `captions`, `session` and `build`.
readonly PIPELINE_LOCK_BASENAME="pipeline"
readonly PIPELINE_LOCK_TIMEOUT_DEFAULT=60
# Resolved from the basename at lock time by playthrough_checkout_lock_name.
PIPELINE_LOCK_NAME=""

# ---------------------------------------------------------------------
# THE STAGE REGISTRY
#
# One ordered list of stage names, and one map from each name to the
# script that owns it.  Two structures rather than four parallel arrays,
# because a parallel array is a list that can fall out of step with its
# neighbour; here a name with no script is a bash error at the point of
# use rather than a stage quietly not run.  The kind of invocation is
# DERIVED from the file suffix instead of being declared, so there is no
# third thing to keep in step either.
#
# THE ORDER OF THIS LIST IS THE PIPELINE.  Nothing else decides it.
# ---------------------------------------------------------------------
readonly STAGE_ORDER=(
    timeline
    transitions
    render
    srt
    captions
    "${GATE_STAGE}"
    "${COMMIT_STAGE}"
    "${ATTEST_STAGE}"
)

declare -rA STAGE_SCRIPT=(
    [timeline]="timeline.py"
    [transitions]="make_transitions.py"
    [render]="render_movie.py"
    [srt]="make_srt.py"
    [captions]="embed_captions.sh"
    [verify]="verify_artifacts.sh"
    [commit]="commit_artifacts.sh"
    [attest]="verify_artifacts.sh"
)

# What each stage is for, in one clause, so the banner tells an operator
# what is happening rather than only which file is running.
declare -rA STAGE_LABEL=(
    [timeline]="time every capture from the record"
    [transitions]="compose the transitions the ceiling asks for"
    [render]="encode the film"
    [srt]="write the cue file and the readable transcript"
    [captions]="mux the captions as a selectable track"
    [verify]="the acceptance gate over every artifact, \
${GATE_PRE_COMMIT_PHASE}"
    [commit]="the ${PIPELINE_CHECKPOINT_NAME} checkpoint"
    [attest]="the acceptance gate again, ${GATE_POST_COMMIT_PHASE}: what \
the history now proves"
)

# ---------------------------------------------------------------------
# State.  Declared here, at file scope, so that `set -u` reports a
# reference to something this file forgot to define rather than treating
# it as empty.
# ---------------------------------------------------------------------
PLAN=()
SKIPPED=()
FROM_STAGE=""
ONLY_STAGE=""
NO_COMMIT=0
LOCK_HELD=0
FAILED_STAGE=""

# ---------------------------------------------------------------------
# Reporting.
#
# note writes the machine channel on stdout; everything a human reads
# goes to stderr through env.sh's helpers, which redact host paths.
# ---------------------------------------------------------------------
note() {
    printf '%s=%s\n' "$1" "$2"
}

# format_elapsed SECONDS
#   Whole seconds as something an operator reads at a glance.  The input
#   is always a difference of two readings of bash's own SECONDS, so no
#   value from the environment reaches this arithmetic -- which matters,
#   because bash resolves a command substitution inside $(( )) and an
#   unchecked number there is not a number.  A timeout that DOES come
#   from the environment goes through playthrough_validate_int instead.
format_elapsed() {
    local total="$1"
    local hours=$(( total / 3600 ))
    local minutes=$(( (total % 3600) / 60 ))
    local seconds=$(( total % 60 ))
    if [ "${hours}" -gt 0 ]; then
        printf '%dh %dm %ds' "${hours}" "${minutes}" "${seconds}"
    elif [ "${minutes}" -gt 0 ]; then
        printf '%dm %ds' "${minutes}" "${seconds}"
    else
        printf '%ds' "${seconds}"
    fi
}

# join_words WORD ...
#   The words separated by a single space, or "none" when there are
#   none.  Used for the two summary lines, so an empty list reads as an
#   answer rather than as a missing one.
join_words() {
    if [ "$#" -eq 0 ]; then
        printf 'none'
        return 0
    fi
    printf '%s' "$*"
}

# ---------------------------------------------------------------------
# USAGE
# ---------------------------------------------------------------------
usage() {
    cat <<'USAGE'
run_pipeline.sh -- run the post-session render stages in dependency
order.  It sequences the modules that do the work and holds none of
their logic itself.

    playthrough/tooling/run_pipeline.sh [options]

Stages, in order:
    timeline       timeline.py           -> playthrough/timeline.json
    transitions    make_transitions.py   -> build/transitions/*.png
    render         render_movie.py       -> playthrough/cata-play.mp4
    srt            make_srt.py           -> transcript.srt + .md
    captions       embed_captions.sh     -> cata-play-cc.mp4
    verify         verify_artifacts.sh --phase pre-commit
    commit         commit_artifacts.sh final
    attest         verify_artifacts.sh --phase post-commit

THE GATE RUNS TWICE, and the split is what makes the commit reachable.
Most of its checks are functional -- is the film watchable, do the
captions line up with the frames -- and can be answered as soon as the
artifacts exist.  Twelve are about the history: is the save tracked, is
every class committed, is the tree clean.  Those cannot pass BEFORE the
commit, because the commit is what makes them true.  So `verify` runs the
functional half and guards the commit, and `attest` runs the history half
afterwards and reports what was published.

Options:
  --from NAME   start at that stage and run every later one, so a
                failed late stage can be retried without re-rendering.
  --from=NAME   the same thing, written as one argument.
  --only NAME   run that stage and no other.
  --only=NAME   the same thing, written as one argument.
  --no-commit   run every stage up to and including the pre-commit gate,
                and stop there -- the checkpoint AND the attestation are
                both dropped, because with no commit there is nothing for
                the attestation to read.  Committing is a deliberate act,
                and this is how an operator takes it by hand afterwards.
  --            end of options.  Nothing may follow it: this sequencer
                takes no positional arguments, so a `--` is only ever the
                end of the line.
  -h, --help    print this and exit.

--from and --only are mutually exclusive.  Repeating either one is
allowed and the LAST occurrence wins, which is what a shell alias with an
appended override does.

A stage may be named by its short name above, by its script, or by that
script without the extension: render, render_movie and render_movie.py
are the same stage.  `attest` is the exception, reachable by its short
name only -- verify_artifacts.sh already names the `verify` stage, and one
script cannot resolve to two stages.

Two rules are enforced over the resolved plan rather than over the flags
that produced it, so they keep holding if a flag is ever added:
  * commit will not run unless verify runs ahead of it in the same
    invocation.  The gate is what stops a black film or a drifted caption
    track from reaching the history.
  * attest will not run without commit in the same invocation.  Every
    check it adds asks whether the history records something, so on its
    own it fails for reasons this run did not cause.
Asking for either of them alone is therefore refused.

The game is neither launched nor keyed here: this file is post-session
and reads only what the session already recorded.  Capturing is
launch_game.sh, session.py and capture.sh, one keystroke at a time.

THIS FILE'S OWN stdout lines are KEY=value only, each prefixed PIPELINE_,
and its banners and diagnostics go to stderr.  A stage's output is NOT
captured or filtered -- a long render should be watchable while it runs --
so the stream you see is this file's PIPELINE_ lines interleaved with
whatever each stage writes, including that stage's own KEY=value lines.
Read PIPELINE_ to parse this file; read a stage's own prefix to parse it.

environment:
    PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT  seconds to wait for another run
                                       of this sequencer over THIS
                                       checkout (default 60)
USAGE
}

# ---------------------------------------------------------------------
# STAGE NAMES
#
# resolve_stage_name NAME
#   Print the canonical short name for whatever an operator typed, or
#   fail.  A case statement over literal alternatives: the input never
#   becomes part of a command, an index or an expression, so there is
#   nothing here for a crafted argument to reach.
# ---------------------------------------------------------------------
resolve_stage_name() {
    case "${1-}" in
        timeline|timeline.py)
            printf 'timeline' ;;
        transitions|make_transitions|make_transitions.py)
            printf 'transitions' ;;
        render|render_movie|render_movie.py)
            printf 'render' ;;
        srt|make_srt|make_srt.py)
            printf 'srt' ;;
        captions|embed_captions|embed_captions.sh)
            printf 'captions' ;;
        verify|verify_artifacts|verify_artifacts.sh)
            printf 'verify' ;;
        commit|commit_artifacts|commit_artifacts.sh)
            printf 'commit' ;;
        attest)
            printf 'attest' ;;
        *)
            return 1 ;;
    esac
    return 0
}
# NOTE ON `attest`: it is the ONLY stage with no script alias, and
# deliberately so.  `verify_artifacts.sh` and `verify_artifacts` already
# resolve to the `verify` stage, and one script name cannot resolve to two
# stages -- so the second run of that script is reachable by its own short
# name alone.  Its phase argument is what distinguishes the two.

# stage_index NAME
#   The position of a canonical name in STAGE_ORDER.
stage_index() {
    local wanted="$1"
    local index=0
    local name=""
    for name in "${STAGE_ORDER[@]}"; do
        if [ "${name}" = "${wanted}" ]; then
            printf '%s' "${index}"
            return 0
        fi
        index=$(( index + 1 ))
    done
    return 1
}

# plan_contains NAME
#   Whether the resolved plan holds that stage.  bash 4.4 and later
#   expand an empty array under `set -u` to no words rather than to an
#   error, so the plan may legitimately be empty here -- which is a case
#   resolve_plan refuses immediately afterwards.
plan_contains() {
    local wanted="$1"
    local name=""
    for name in "${PLAN[@]}"; do
        if [ "${name}" = "${wanted}" ]; then
            return 0
        fi
    done
    return 1
}


# die STATUS MESSAGE ...
#   Report and stop.  env.sh's playthrough_die RETURNS 1 rather than
#   exiting, so that a sourced consumer cannot have its shell killed by
#   a diagnostic; the exit is therefore taken here explicitly, and `||
#   true` keeps errexit from ending the script on the report itself
#   before the intended status is chosen.  verify_artifacts.sh,
#   commit_artifacts.sh and supported_env.sh all spell it this way.
die() {
    local status="$1"
    shift
    playthrough_die "$@" || true
    exit "${status}"
}

# ---------------------------------------------------------------------
# ARGUMENTS
#
# Both spellings of each option are accepted -- `--from render` and
# `--from=render` -- because the siblings in this folder accept both and
# an operator should not have to remember which one this file wanted.
# An unrecognised argument is REFUSED rather than ignored: an ignored
# flag is an operator who believes something happened that did not.
# ---------------------------------------------------------------------
parse_arguments() {
    local resolved=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --from)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--from needs a stage name"
                fi
                FROM_STAGE="$2"
                shift 2
                ;;
            --from=*)
                FROM_STAGE="${1#--from=}"
                shift
                ;;
            --only)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--only needs a stage name"
                fi
                ONLY_STAGE="$2"
                shift 2
                ;;
            --only=*)
                ONLY_STAGE="${1#--only=}"
                shift
                ;;
            --no-commit)
                NO_COMMIT=1
                shift
                ;;
            -h|--help)
                usage
                exit "${EX_OK}"
                ;;
            --)
                shift
                break
                ;;
            -*)
                usage >&2
                die "${EX_USAGE}" "unknown option '$1'"
                ;;
            *)
                usage >&2
                die "${EX_USAGE}" "unexpected argument '$1'.  Every" \
                    "input this sequencer has is the checkout it runs" \
                    "in and the stages it is told to run."
                ;;
        esac
    done
    if [ "$#" -gt 0 ]; then
        usage >&2
        die "${EX_USAGE}" "unexpected argument '$1'"
    fi

    # The names are resolved HERE, before any plan is built, so a
    # mistyped stage is a refusal at the first opportunity rather than a
    # run that turns out to have done nothing.
    if [ -n "${FROM_STAGE}" ]; then
        resolved="$(resolve_stage_name "${FROM_STAGE}")" ||
            die "${EX_USAGE}" "--from names no stage of this" \
                "pipeline: '${FROM_STAGE}'.  The stages are" \
                "${STAGE_ORDER[*]}."
        FROM_STAGE="${resolved}"
    fi
    if [ -n "${ONLY_STAGE}" ]; then
        resolved="$(resolve_stage_name "${ONLY_STAGE}")" ||
            die "${EX_USAGE}" "--only names no stage of this" \
                "pipeline: '${ONLY_STAGE}'.  The stages are" \
                "${STAGE_ORDER[*]}."
        ONLY_STAGE="${resolved}"
    fi
}

# ---------------------------------------------------------------------
# THE PLAN
#
# One contiguous run of STAGE_ORDER, or exactly one stage of it.  The
# two rules at the end are the ones that matter, and they are asserted
# over the RESOLVED plan rather than over the flags that produced it, so
# they keep holding if another flag is ever added.
# ---------------------------------------------------------------------
resolve_plan() {
    local name=""
    local start=0
    local index=0
    local -a kept=()

    if [ -n "${ONLY_STAGE}" ] && [ -n "${FROM_STAGE}" ]; then
        usage >&2
        die "${EX_USAGE}" "--from and --only describe two different" \
            "plans; give one or the other."
    fi

    PLAN=()
    SKIPPED=()

    if [ -n "${ONLY_STAGE}" ]; then
        for name in "${STAGE_ORDER[@]}"; do
            if [ "${name}" = "${ONLY_STAGE}" ]; then
                PLAN+=("${name}")
            else
                SKIPPED+=("${name}")
            fi
        done
    else
        if [ -n "${FROM_STAGE}" ]; then
            start="$(stage_index "${FROM_STAGE}")" ||
                die "${EX_USAGE}" "'${FROM_STAGE}' is not in the" \
                    "stage order, which is a fault in this file" \
                    "rather than in the argument"
        fi
        for name in "${STAGE_ORDER[@]}"; do
            if [ "${index}" -ge "${start}" ]; then
                PLAN+=("${name}")
            else
                SKIPPED+=("${name}")
            fi
            index=$(( index + 1 ))
        done
    fi

    # --no-commit drops the checkpoint AND the attestation that follows
    # it.  Not committing means the history does not change, and the
    # attestation asks only questions about the history -- so running it
    # here would report a failure the operator deliberately asked for.
    if [ "${NO_COMMIT}" -eq 1 ]; then
        for name in "${PLAN[@]}"; do
            if [ "${name}" = "${COMMIT_STAGE}" ] ||
               [ "${name}" = "${ATTEST_STAGE}" ]; then
                SKIPPED+=("${name}")
            else
                kept+=("${name}")
            fi
        done
        PLAN=("${kept[@]}")
    fi

    # THE TWO RULES THIS FILE ENFORCES ON ITS OWN BEHALF, both asserted
    # over the RESOLVED plan rather than over the flags that produced it,
    # so they keep holding if another flag is ever added.
    #
    # FIRST: the gate has to have passed in THIS invocation before the
    # checkpoint is taken, so a plan that reaches the commit stage
    # without the gate ahead of it is refused rather than quietly
    # completed.
    if plan_contains "${COMMIT_STAGE}" &&
       ! plan_contains "${GATE_STAGE}"; then
        die "${EX_USAGE}" "the ${COMMIT_STAGE} stage will not run" \
            "unless the ${GATE_STAGE} stage runs ahead of it in the" \
            "same invocation: the gate is what stops an unwatchable" \
            "film or a drifted caption track from reaching the" \
            "history.  Use --from ${GATE_STAGE} to take the" \
            "checkpoint behind its gate."
    fi

    # SECOND, and the mirror of it: the attestation reads what the
    # checkpoint published, so on its own it is a report about somebody
    # else's commit.  Its twelve checks are exactly the ones that cannot
    # pass before a commit, which is why asking for it alone would fail
    # for a reason that has nothing to do with this run.
    if plan_contains "${ATTEST_STAGE}" &&
       ! plan_contains "${COMMIT_STAGE}"; then
        die "${EX_USAGE}" "the ${ATTEST_STAGE} stage attests to what" \
            "the ${COMMIT_STAGE} stage published, so it will not run" \
            "without it in the same invocation: every check it adds" \
            "asks whether the history records something, and before a" \
            "commit the answer is no for reasons this run did not" \
            "cause.  Use --from ${GATE_STAGE} to run the gate, the" \
            "checkpoint and the attestation together."
    fi

    if [ "${#PLAN[@]}" -eq 0 ]; then
        die "${EX_USAGE}" "that combination of options leaves no" \
            "stage to run."
    fi
}

# ---------------------------------------------------------------------
# PREFLIGHT
#
# Everything the plan needs is proved present before the first stage
# starts, so a missing module is one message now rather than a failure
# part way through a render.
# ---------------------------------------------------------------------
stage_script_path() {
    printf '%s/%s' "${SCRIPT_DIR}" "${STAGE_SCRIPT[$1]}"
}

assert_stage_scripts() {
    local name=""
    local script=""
    local -a missing=()
    for name in "${PLAN[@]}"; do
        script="$(stage_script_path "${name}")"
        if [ ! -f "${script}" ] || [ ! -r "${script}" ]; then
            missing+=("$(playthrough_rel "${script}")")
        fi
    done
    if [ "${#missing[@]}" -ne 0 ]; then
        die "${EX_LAYOUT}" "missing or unreadable stage(s):" \
            "${missing[*]}.  Every stage of this pipeline lives" \
            "beside this file, and none of them is optional."
    fi
}

plan_needs_interpreter() {
    local name=""
    for name in "${PLAN[@]}"; do
        case "${STAGE_SCRIPT[${name}]}" in
            *.py) return 0 ;;
        esac
    done
    return 1
}

assert_interpreter() {
    plan_needs_interpreter || return 0
    if [ -z "${PLAYTHROUGH_PYTHON:-}" ] ||
       [ ! -x "${PLAYTHROUGH_PYTHON}" ]; then
        die "${EX_LAYOUT}" "'${PLAYTHROUGH_PYTHON:-<unset>}' is not" \
            "an executable interpreter, so the Python stages cannot" \
            "run.  It is the one env.sh resolved and verified;" \
            "install the pinned closure from" \
            "playthrough/tooling/requirements.lock into it rather" \
            "than reaching for another Python."
    fi
}

# ---------------------------------------------------------------------
# THE LOCK
#
# Held for the whole sequence and released however this run ends.  The
# timeout is the only number this file takes from the environment, so it
# goes through env.sh's validator rather than into arithmetic: bash
# resolves a command substitution inside $(( )), which makes an
# unchecked value there an instruction rather than a number.
# ---------------------------------------------------------------------
acquire_pipeline_lock() {
    local timeout="${PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT:-\
${PIPELINE_LOCK_TIMEOUT_DEFAULT}}"
    # playthrough_validate_int reports its own refusal in full, so this
    # adds the remedy rather than repeating the diagnosis.
    playthrough_validate_int "${timeout}" \
        "PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT" 0 86400 ||
        die "${EX_USAGE}" "set" \
            "PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT to a whole number of" \
            "seconds, or leave it unset for" \
            "${PIPELINE_LOCK_TIMEOUT_DEFAULT}."
    # The name is derived from the repository root, so it identifies THIS
    # working tree rather than this clone index.  Derived here rather than
    # at file scope because it needs a tool, and a tool that is missing
    # should be reported beside the other preflight failures.
    if ! PIPELINE_LOCK_NAME="$(playthrough_checkout_lock_name \
            "${PIPELINE_LOCK_BASENAME}")"; then
        die "${EX_LAYOUT}" "the lock name for this checkout could not" \
            "be derived, so two runs of this sequencer over one" \
            "working tree could not be kept apart."
    fi
    readonly PIPELINE_LOCK_NAME
    if ! playthrough_acquire_lock \
            "${PIPELINE_LOCK_NAME}" "${PLAYTHROUGH_INT}"; then
        # THE DIGEST IS THE SCOPE, and it is quoted instead of the path
        # because every message here goes through env.sh's redaction,
        # which rewrites the repository root to '.' to keep host paths out
        # of the logs -- so "over the checkout at ${REPO_ROOT}" would
        # render as "over the checkout at .", which names nothing.  The
        # digest in the lock name says which lock to look for and why a
        # different tree does not contend for it.
        die "${EX_BUSY}" "another run of this sequencer holds the" \
            "'${PIPELINE_LOCK_NAME}' lock, whose digest is derived" \
            "from THIS working tree's path.  Two of them would write" \
            "one set of artifacts between them, so this one stops" \
            "rather than racing it; a run over a different checkout" \
            "takes a different lock and is not serialised against" \
            "this one."
    fi
    LOCK_HELD=1
}

# SC2317: reached only through the EXIT trap, which ShellCheck does not
# model as a call site.
# shellcheck disable=SC2317
_rp_on_exit() {
    if [ "${LOCK_HELD}" -eq 1 ]; then
        LOCK_HELD=0
        # The descriptor is named rather than left to the helper's
        # default, exactly as embed_captions.sh:1445 names it, and the
        # release cannot be allowed to change the status this run is
        # ending with -- the reason for it has already been reported.
        playthrough_release_lock "${PLAYTHROUGH_LOCK_FD:-}" || true
    fi
}


# ---------------------------------------------------------------------
# RUNNING A STAGE
#
# build_stage_command NAME
#   Fill STAGE_COMMAND with the argument list for one stage.  AN ARRAY,
#   never a string that a shell would have to take apart again: nothing
#   here is assembled out of text, so there is no quoting for a path to
#   slip through and nothing for an interpreter to re-read.
#
#   A .py stage is started through the interpreter env.sh resolved and
#   verified, with -B on top of the inherited PYTHONDONTWRITEBYTECODE=1
#   so that neither instruction alone is load-bearing.  A .sh stage is
#   its own executable and is started by absolute path.
#
#   The fallback for a shell stage whose executable bit has been lost --
#   an archive expanded without modes, a file copied by something that
#   does not keep them -- is to start it through ${BASH}, which is the
#   absolute path of the interpreter already running this file.  It is
#   announced rather than silent, because a stage whose mode has gone is
#   a tree somebody should repair.
# ---------------------------------------------------------------------
STAGE_COMMAND=()

build_stage_command() {
    local name="$1"
    local script=""
    script="$(stage_script_path "${name}")"
    STAGE_COMMAND=()
    case "${script}" in
        *.py)
            STAGE_COMMAND=( "${PLAYTHROUGH_PYTHON}" -B "${script}" )
            ;;
        *.sh)
            if [ -x "${script}" ]; then
                STAGE_COMMAND=( "${script}" )
            else
                playthrough_warn "$(playthrough_rel "${script}") is" \
                    "not executable, so it is being started through" \
                    "${BASH} instead.  Restore its mode with" \
                    "'chmod +x' -- git records it, so a checkout" \
                    "should not have lost it."
                STAGE_COMMAND=( "${BASH}" "${script}" )
            fi
            ;;
        *)
            die "${EX_LAYOUT}" "the '${name}' stage names" \
                "'${script}', which is neither a Python module nor a" \
                "shell script, so this file does not know how to" \
                "start it"
            ;;
    esac
    # THE THREE STAGES THAT TAKE AN ARGUMENT.  Each argument is a
    # constant declared once at the head of this file -- never anything
    # derived from an operator's input -- so there is nothing here for a
    # crafted argument to reach.
    #
    # commit: the checkpoint named at THE CHECKPOINT THIS FILE TAKES.
    # commit_artifacts.sh deliberately has no default, because its
    # checkpoints mean different things.
    #
    # verify and attest: the two halves of the gate.  Passing the phase
    # explicitly on BOTH, rather than letting the first one take the
    # script's own default, is what makes the pairing legible here and
    # keeps this file correct if that default ever changes.
    case "${name}" in
        "${COMMIT_STAGE}")
            STAGE_COMMAND+=( "${PIPELINE_CHECKPOINT_NAME}" )
            ;;
        "${GATE_STAGE}")
            STAGE_COMMAND+=( "${GATE_PHASE_ARGUMENT}"
                             "${GATE_PRE_COMMIT_PHASE}" )
            ;;
        "${ATTEST_STAGE}")
            STAGE_COMMAND+=( "${GATE_PHASE_ARGUMENT}"
                             "${GATE_POST_COMMIT_PHASE}" )
            ;;
    esac
}

# run_stage NAME NUMBER TOTAL
#   Announce it, run it, report what it did, and return its status.
#
#   THE STAGE'S STATUS IS READ FROM A `||`, which bash exempts from the
#   ERR trap, so a stage that fails is reported by the banner here
#   rather than by the trap -- and errexit does not end this file before
#   the summary has been written.  A stage's own stdout and stderr are
#   NOT captured: a long render should be watchable while it runs, and
#   an operator reading this transcript needs the stage's own KEY=value
#   lines in place.
run_stage() {
    local name="$1"
    local number="$2"
    local total="$3"
    local started="${SECONDS}"
    local status=0
    local elapsed=0

    build_stage_command "${name}"
    if [ "${#STAGE_COMMAND[@]}" -eq 0 ]; then
        die "${EX_LAYOUT}" "no command was assembled for the" \
            "'${name}' stage"
    fi

    printf '\n' >&2
    playthrough_log "stage ${number}/${total} ${name}:" \
        "${STAGE_LABEL[${name}]} -- $(playthrough_rel \
            "$(stage_script_path "${name}")")"

    "${STAGE_COMMAND[@]}" || status=$?
    elapsed=$(( SECONDS - started ))

    if [ "${status}" -ne 0 ]; then
        note "PIPELINE_STAGE_${name^^}" "fail"
        playthrough_warn "STAGE ${number}/${total} ${name} FAILED" \
            "with exit ${status} after $(format_elapsed "${elapsed}");" \
            "its own diagnosis is above.  Nothing after it is run."
        return "${status}"
    fi
    note "PIPELINE_STAGE_${name^^}" "pass"
    playthrough_log "stage ${number}/${total} ${name}: done in" \
        "$(format_elapsed "${elapsed}")"
    return 0
}

# report_unattempted FAILED_INDEX
#   Name the stages the plan still held when it stopped.  An operator
#   who has just read a failure needs to know that nothing later ran --
#   above all that no checkpoint was taken -- and saying so is cheaper
#   than leaving them to work it out from the stage numbers.
report_unattempted() {
    local failed_index="$1"
    local index=0
    local -a remaining=()
    for index in "${!PLAN[@]}"; do
        if [ "${index}" -gt "${failed_index}" ]; then
            remaining+=("${PLAN[${index}]}")
        fi
    done
    if [ "${#remaining[@]}" -eq 0 ]; then
        return 0
    fi
    note PIPELINE_UNATTEMPTED "${remaining[*]}"
    playthrough_warn "not attempted: ${remaining[*]}"
}

# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
main() {
    local started_at="${SECONDS}"
    local total=0
    local number=0
    local index=0
    local status=0
    local name=""

    parse_arguments "$@"
    resolve_plan
    assert_stage_scripts
    assert_interpreter

    # The trap is registered before the lock is taken, so the lock is
    # released however this run ends -- including a refusal from a stage
    # and an interrupt from the terminal.
    trap '_rp_on_exit' EXIT
    acquire_pipeline_lock

    total="${#PLAN[@]}"
    note PIPELINE_PLAN "$(join_words "${PLAN[@]}")"
    note PIPELINE_SKIPPED "$(join_words "${SKIPPED[@]}")"
    note PIPELINE_CHECKPOINT "$(
        if plan_contains "${COMMIT_STAGE}"; then
            printf '%s' "${PIPELINE_CHECKPOINT_NAME}"
        else
            printf 'none'
        fi
    )"
    playthrough_log "${total} stage(s) to run: ${PLAN[*]}"
    # The trust state is REPORTED, never acted on.  Each stage that
    # produces evidence recomputes it and refuses on its own account --
    # the render and the caption mux both do -- and a sequencer that
    # second-guessed them would be a second, drifting copy of a control
    # that belongs to them.  It is logged because a refusal several
    # minutes into a run is much easier to understand when the state
    # that caused it was printed at the start.
    playthrough_log "interpreter" \
        "${PLAYTHROUGH_PYTHON}; trust state" \
        "${PLAYTHROUGH_TRUST_STATE:-<unknown>}"

    for index in "${!PLAN[@]}"; do
        name="${PLAN[${index}]}"
        number=$(( index + 1 ))
        status=0
        run_stage "${name}" "${number}" "${total}" || status=$?
        if [ "${status}" -ne 0 ]; then
            FAILED_STAGE="${name}"
            report_unattempted "${index}"
            break
        fi
    done

    printf '\n' >&2
    note PIPELINE_ELAPSED "$(( SECONDS - started_at ))"
    if [ "${status}" -ne 0 ]; then
        note PIPELINE_FAILED_STAGE "${FAILED_STAGE}"
        note PIPELINE_STATUS "${status}"
        note PIPELINE "fail"
        playthrough_warn "the pipeline stopped at the" \
            "'${FAILED_STAGE}' stage with exit ${status}, after" \
            "$(format_elapsed "$(( SECONDS - started_at ))")." \
            "No later stage ran, so no checkpoint was taken and the" \
            "artifact set on disk is whatever the stages before it" \
            "left."
        return "${status}"
    fi
    note PIPELINE_STATUS "0"
    note PIPELINE "pass"
    playthrough_log "every stage in the plan passed" \
        "(${PLAN[*]}) in" \
        "$(format_elapsed "$(( SECONDS - started_at ))")"
    return "${EX_OK}"
}

# main's status is taken from a `||` and then exited with, rather than
# being left to errexit: the ERR trap would otherwise report a line
# number for a stage failure that has already been explained in full,
# which reads as a fault in this file when it is not one.
_rp_status=0
main "$@" || _rp_status=$?
exit "${_rp_status}"

