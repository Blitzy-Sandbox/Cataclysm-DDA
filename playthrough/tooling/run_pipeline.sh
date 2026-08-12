#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/run_pipeline.sh
#
# THE POST-SESSION SEQUENCER.  It runs the render stages in dependency
# order, reports what each one did, and stops at the first failure.  The
# work each stage performs belongs to the module that owns it; what lives
# here is the sequencing and the decisions that have to be made across
# stages -- the plan, the trust gate, the capacity reserve, the run
# receipt and the checkpoint's eligibility.
#
# BASH IS REQUIRED rather than optional: BASH_SOURCE locates this file,
# arrays carry every stage as an argument list instead of a string, and
# `local` scopes each helper.
#
# USAGE
#     playthrough/tooling/run_pipeline.sh
#     playthrough/tooling/run_pipeline.sh --from render
#     playthrough/tooling/run_pipeline.sh --only verify
#     playthrough/tooling/run_pipeline.sh --no-commit
#     playthrough/tooling/run_pipeline.sh --rebuild
#     playthrough/tooling/run_pipeline.sh --help
#
# ---------------------------------------------------------------------
# THE NINE STAGES, IN THE ONLY ORDER THEY CAN RUN IN
#
#   1 timeline      timeline.py            manifest.jsonl
#                                            -> timeline.json
#   2 transitions   make_transitions.py    timeline.json + frames/
#                                            -> build/transitions/*.png
#   3 render        render_movie.py        timeline.json + frames/
#                                          + build/transitions/
#                                            -> cata-play.mp4
#   4 srt           make_srt.py            timeline.json
#                                            -> transcript.srt + .md
#   5 captions      embed_captions.sh      cata-play.mp4 + transcript.srt
#                                            -> cata-play-cc.mp4
#   6 verify        verify_artifacts.sh --phase pre-commit
#                                          the artifacts -> the gate
#   7 commit        commit_artifacts.sh media
#                                          the derived artifacts -> the
#                                          commit
#   8 attest        verify_artifacts.sh --phase post-commit
#                                          the history -> the gate again
#   9 publish       commit_artifacts.sh attest
#                                          the report stage 8 wrote -> the
#                                          committed attestation
#
# The order is forced by real data dependencies rather than by taste:
# make_transitions.py reads the transition_after flags, so the timeline
# has to exist first; render_movie.py names the materialised transition
# images in the list it hands the encoder, so they must be on disk BEFORE
# it writes that list; embed_captions.sh needs both the film and the cue
# file; the gate's functional half runs BEFORE the checkpoint so nothing
# that fails it can reach the history; and the gate's history half runs
# AFTER it, because a commit is what makes its questions answerable at
# all.  make_srt.py reads only the timeline and could run any time after
# stage 1; it is kept at position 4 because that is the order the feature
# plan states.
#
# ---------------------------------------------------------------------
# WHY THE GATE IS TWO STAGES, AND THE COMMIT TWO CHECKPOINTS
#
# verify_artifacts.sh asks two kinds of question.  Most of its checks are
# FUNCTIONAL and can be answered as soon as the artifacts exist.  The
# rest are about the HISTORY -- is the save tracked, is every artifact
# class committed, is the tree clean, do the checkpoint trailers name one
# survivor -- and cannot be true before the commit, because the commit is
# what makes them true.  How many of those there are is NOT written here:
# the gate declares that count and its own help reads it, and a second
# copy in a comment is a copy that goes stale.
#
# So the gate is split by phase and appears twice: `verify` runs
# --phase pre-commit and guards the commit, `attest` runs
# --phase post-commit and reports what the commit published.  The
# commit is two checkpoints for the mirror-image reason: `media` publishes
# the derived artifacts, and `attest` then publishes the acceptance report
# stage 8 measured over them.  One commit could not do both honestly, as
# the report would have to cite a commit that did not exist yet.
#
# ---------------------------------------------------------------------
# THE GATE PRECEDES THE COMMIT, AND THAT IS NOT A DEFAULT
#
# There is no option here that runs commit_artifacts.sh without the gate
# ahead of it in the same invocation.  --no-commit drops the checkpoint
# and everything after it, which is the honest way to run the render half
# alone; --only commit is refused.
#
# ---------------------------------------------------------------------
# THREE THINGS ARE SETTLED BEFORE THE FIRST STAGE RUNS
#
# Every stage is expensive and an hour of encoding cannot be given back,
# so three questions whose answers already exist are asked FIRST:
#
#   1 WOULD THE CHECKPOINT BE TAKEN AT ALL?  This file's checkpoint is
#     `media`, which commits a RENDER -- and a render is about a session
#     whose save has already been published, so it needs a `final`
#     checkpoint for the survivor this userdir has loaded, reached from
#     that survivor's own `creation`.  That is a fact about the history
#     before anything is rendered.  commit_artifacts.sh answers it
#     read-only through `status`, this file reads the answer for the
#     checkpoint IT takes, and a plan that cannot reach it is refused now,
#     with --no-commit named as the way to run the render half
#     deliberately.  The lifecycle rule stays where it belongs: this file
#     reads one KEY=value line and holds no copy of it.
#
#   2 IS THERE ROOM?  The artifacts are full-resolution and nothing is
#     ever decimated to make them fit, so running out of space part way
#     through is a torn generation rather than a smaller one.  The reserve
#     is MEASURED from what is on disk and checked before the first stage
#     and again immediately before the checkpoint, because the producing
#     stages consume space in between.  A measurement that cannot be taken
#     is reported and does not block the run: each stage re-checks on its
#     own account, and this one exists to fail early.
#
#   3 IS ANY OF IT ALREADY DONE?  A run receipt records, per producing
#     stage, the identity of the INPUTS it was produced from and the
#     digest of the OUTPUTS it produced; a stage is skipped only when both
#     still hold, so a retry after a late failure does not re-encode a
#     film nothing has invalidated.  The receipt is CONTENT-ADDRESSED --
#     the record, the ledgers, the capture count, HEAD, the state of the
#     input paths in git, the pinned closure, the interpreter and every
#     stage script's own digest -- and never a modification time or a
#     size, either of which can move without the content moving and can
#     stay still while it does.  It lives in the runtime directory, never
#     in the working tree, so it cannot be committed.  The gate, the
#     checkpoint and the attestation are NEVER skipped, --only never skips
#     the stage it names, --rebuild ignores the receipt entirely, and once
#     any stage has run every later one runs too.
#
# The trust state is settled in the same place and for the same reason: a
# run whose host cannot be trusted to produce evidence is refused BEFORE
# the first stage, not at the fourth, because a control that fires after
# the artifact set has been rewritten is a report rather than a control.
#
# ---------------------------------------------------------------------
# WHAT THIS FILE DELIBERATELY DOES NOT DO
#
# It does not launch the game and it does not capture -- that is
# launch_game.sh, session.py and capture.sh, and it happens DURING the
# session rather than after it.  It takes no checkpoint of its own beyond
# the two named above: `integration` -- which commits .gitignore and
# .gitattributes, the two repository-wide rule files every other
# checkpoint refuses without -- along with `dossier`, `creation` and
# `final`, belong before or at the end of the session and are taken by
# hand, by running commit_artifacts.sh directly.  That is also why no flag
# here selects a checkpoint.
#
# ---------------------------------------------------------------------
# OUTPUT CONTRACT
#
# STDOUT IS A MACHINE CHANNEL: KEY=value lines only.  Each stage's own
# output passes through untouched, and this file's lines are prefixed
# PIPELINE_ so the two cannot be confused:
#
#     PIPELINE_PLAN          the stages this run intends, in order
#     PIPELINE_SKIPPED       the stages it was told to leave out
#     PIPELINE_CHECKPOINT    the checkpoint the commit stage takes
#     PIPELINE_LIFECYCLE     eligible | <the refusal token> | unread
#     PIPELINE_CAPACITY      bytes free : bytes reserved before the first
#                            stage, or unmeasured
#     PIPELINE_CAPACITY_CHECKPOINT
#                            the same, measured again immediately before
#                            the checkpoint.  Absent when none was reached
#     PIPELINE_RECEIPT       the receipt file's own name, or none
#     PIPELINE_FRESH         the stages the receipt proved already done
#     PIPELINE_STAGE_<NAME>  pass | fail | fresh, one per planned stage
#     PIPELINE_FAILED_STAGE  the stage that stopped the run
#     PIPELINE_STATUS        the exit status this run ends with
#     PIPELINE_ELAPSED       whole seconds from first stage to last
#     PIPELINE               pass | fail
#
# Banners, warnings and diagnostics go to STDERR through env.sh's helpers.
# A stage's own output is never captured or buffered: it appears as it is
# produced, because an operator reading a long render wants to see it
# move.
#
# ---------------------------------------------------------------------
# EXIT CODES
#     0  every stage in the plan passed
#     1  usage error -- an unknown option, an unknown stage name, or a
#        plan this file will not run
#     2  layout error -- this file cannot locate itself, this is not the
#        checkout it belongs to, a stage is missing, or env.sh refused to
#        load
#     3  another run of this sequencer holds the lock over this checkout
#     4  the planned checkpoint cannot be taken: the survivor this session
#        is about has no `creation` checkpoint to anchor to, or the record
#        has not grown since it.  Nothing was run.
#     5  not enough room to run this plan without risking a torn
#        generation.  Refused before the first stage, or before the
#        checkpoint if the producing stages consumed the margin.
#     6  this host was not in a state in which producing evidence is
#        honest -- see the trust state in env.sh
#     *  otherwise THE FAILING STAGE'S OWN EXIT STATUS, passed through
#        unchanged, because those codes carry diagnosis a code of this
#        file's own would throw away (embed_captions.sh 8 is a missing
#        prerequisite, commit_artifacts.sh 3 an unresolved identity).
#        PIPELINE_FAILED_STAGE names which stage it came from.
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
# Exit codes, named so the call sites read as intent.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_LAYOUT=2
readonly EX_BUSY=3
# THE THREE REFUSALS THAT ARE NEITHER A USAGE MISTAKE NOR A BROKEN LAYOUT. Each
# gets its own code because an operator has to be able to tell them apart
# without reading the message: nothing was wrong with the artifacts or the plan
# in any of the three cases.
readonly EX_INELIGIBLE=4
readonly EX_CAPACITY=5
readonly EX_TRUST=6

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment and the
# artifact layout.
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
# Two landmarks, checked here rather than left to surface later as an
# unexplained stage failure.
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
# pipeline, and it is set BEFORE env.sh is sourced because env.sh documents
# itself as sourced from there.
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

# env.sh resolves the repository root from its own location, by the same idiom
# and from the same directory, so the two answers agree in every tree this file
# belongs to.
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

# The two checkpoints this sequencer takes.
#
# NOT `final`, EVEN THOUGH THIS SEQUENCER IS POST-SESSION.  `final` also
# demands the three-section report, a document whose subject is the film,
# the caption track and the commits carrying them -- so taking it here
# would mean citing commits the very checkpoint demanding it has not made
# yet, and the only hashes available to cite would be an earlier
# session's.
#
# The two steps that belong after a render are `media` for the derived
# artifacts and `attest` for the two reports, and those are the two this
# file takes.  `dossier`, `creation` and `final` are taken by hand --
# they are about the session, not about the render.
readonly PIPELINE_CHECKPOINT_NAME="media"
readonly PIPELINE_ATTESTATION_NAME="attest"

# The stage that must have passed in this invocation before the commit
# stage may run, and the stage it guards.  Named rather than open-coded
# so the rule below reads as the rule it is.
readonly GATE_STAGE="verify"
readonly COMMIT_STAGE="commit"
# The mux stage, named because the capacity model has to know that this
# is the one stage that needs room for a second copy of the film.
readonly CAPTION_STAGE="captions"
# The second gate run, after the checkpoint.  See WHY THE GATE RUNS TWICE
# in the header.
readonly ATTEST_STAGE="attest"
# The stage that COMMITS what that second run measured.
readonly PUBLISH_STAGE="publish"

# WHY THE GATE RUNS TWICE, AND WHAT EACH RUN IS FOR.
#
# Most of the gate's checks are FUNCTIONAL -- is the film watchable, do the
# captions line up with the frames, does every capture match its
# attestation -- and can be answered the moment the artifacts exist.  A
# minority are about the HISTORY, and cannot be answered before the commit
# because the commit is what makes them true.  Running the whole gate once
# ahead of the commit therefore FAILS BY CONSTRUCTION, leaving the commit
# stage unattempted.  So the functional half runs first and guards the
# commit, the history half runs after it and attests to what was published,
# and both are the same script with a --phase argument.  Neither count is
# copied here: the gate declares them and its own help reads them.
readonly GATE_PHASE_ARGUMENT="--phase"
# How the gate is told where to leave its report.  It writes nowhere by
# default, deliberately: publishing is a separate act taken by a step that
# can refuse a failing measurement.
readonly GATE_REPORT_ARGUMENT="--report-to"
readonly GATE_PRE_COMMIT_PHASE="pre-commit"
readonly GATE_POST_COMMIT_PHASE="post-commit"

# The lock this run holds over the checkout. Two sequencers over one checkout
# would interleave their writes into one set of artifacts -- one computing a
# timeline while the other encodes from it -- so the second waits and then
# stops rather than racing the first.
readonly PIPELINE_LOCK_BASENAME="pipeline"
readonly PIPELINE_LOCK_TIMEOUT_DEFAULT=60
# Resolved from the basename at lock time by playthrough_checkout_lock_name.
PIPELINE_LOCK_NAME=""
# The validated lock timeout, filled by assert_lock_timeout during the
# preflight and read by acquire_pipeline_lock.
PIPELINE_LOCK_TIMEOUT="${PIPELINE_LOCK_TIMEOUT_DEFAULT}"

# The field separator the shared dependency-closure checker joins its verdicts
# with.
readonly CLOSURE_SEPARATOR=$'\037'

# This run's private scratch directory, opened on demand and removed by the
# exit trap.
PIPELINE_SCRATCH=""

# ---------------------------------------------------------------------
# THE LIFECYCLE PROBE
# The subcommand of commit_artifacts.sh that answers "would the checkpoint this
# file takes be taken?" without taking it, and the three keys it answers with.
# ---------------------------------------------------------------------
readonly LIFECYCLE_PROBE_SUBCOMMAND="status"
readonly LIFECYCLE_KEY_ELIGIBLE="${PIPELINE_CHECKPOINT_NAME^^}_ELIGIBLE"
readonly LIFECYCLE_KEY_REASON="${PIPELINE_CHECKPOINT_NAME^^}_REASON"
readonly LIFECYCLE_KEY_ANCHOR="${PIPELINE_CHECKPOINT_NAME^^}_ANCHOR"
readonly LIFECYCLE_ELIGIBLE_VALUE="yes"

# ---------------------------------------------------------------------
# THE CAPACITY RESERVE
# A margin over and above every measured term, so a plan is not accepted with
# nothing but the exact bytes it needs: the engine's own userdir, git's index
# and pack writes and the encoder's temporary state all move during a run.
# ---------------------------------------------------------------------
readonly CAPACITY_MARGIN_BYTES=268435456
readonly BYTES_PER_MIB=1048576

# ---------------------------------------------------------------------
# THE RUN RECEIPT
# One line per producing stage, in the runtime directory and never in the
# working tree.
# ---------------------------------------------------------------------
readonly RECEIPT_FORMAT=1
readonly RECEIPT_BASENAME="receipt"
readonly RECEIPT_HEADER="# playthrough pipeline receipt"
# The field separator, spelled once and never written as a literal tab:
# a tab inside a parameter expansion is invisible in a diff and in a
# review, and no other file in this folder contains one.
readonly RECEIPT_SEPARATOR=$'\t'

# ---------------------------------------------------------------------
# THE STAGE REGISTRY
# One ordered list of stage names, and one map from each name to the script
# that owns it.
# ---------------------------------------------------------------------
readonly STAGE_ORDER=(
    timeline
    transitions
    render
    srt
    "${CAPTION_STAGE}"
    "${GATE_STAGE}"
    "${COMMIT_STAGE}"
    "${ATTEST_STAGE}"
    "${PUBLISH_STAGE}"
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
    [publish]="commit_artifacts.sh"
)

# ---------------------------------------------------------------------
# WHICH STAGES DERIVE EVIDENCE, AND WHY THE ANSWER IS DECLARED HERE
#
# Five of the NINE stages WRITE a delivered artifact: the timeline, the
# transition frames, the film, the transcript pair and the captioned film.
# FOUR do not -- the two gate runs read evidence and write nothing, and the
# two checkpoints publish what already exists.
#
# The classification is DECLARED rather than decided at each call site,
# because the trust state has to be judged over the WHOLE PLAN before the
# first stage runs.  Acting on it inside the producing stages instead would
# let a run on a relaxed host rewrite the timeline, the transition frames
# and both transcripts before meeting the refusal -- and a control that
# fires after the damage is a report, not a control.  A stage added to
# STAGE_ORDER without an entry here is a bash error at the point of use,
# which is the same protection STAGE_SCRIPT gives.
declare -rA STAGE_DERIVES_EVIDENCE=(
    [timeline]=1
    [transitions]=1
    [render]=1
    [srt]=1
    [captions]=1
    [verify]=0
    [commit]=0
    [attest]=0
    [publish]=0
)

# THE CHECKPOINT IS DELIBERATELY NOT GATED, and this is a decision the
# environment contract already made rather than a gap in this one.

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
    [publish]="the ${PIPELINE_ATTESTATION_NAME} checkpoint: commit the \
report that gate just measured"
)

# ---------------------------------------------------------------------
# State.  Declared here, at file scope, so that `set -u` reports a
# reference to something this file forgot to define rather than treating
# it as empty.
# ---------------------------------------------------------------------
PLAN=()
SKIPPED=()
FRESH=()
FROM_STAGE=""
ONLY_STAGE=""
NO_COMMIT=0
REBUILD=0
LOCK_HELD=0
MUTATION_LOCK_HELD=0
FAILED_STAGE=""

# The measurement toolchain, resolved once in the preflight.
MEASURED_READY=0
GIT=""
FIND=""
WC=""
SORT=""
MV=""
DF=""
DU=""
SHA256SUM=""

# The receipt: its path, the fingerprint this run computed, and whether
# it can be used at all.
RECEIPT_FILE=""
RECEIPT_FINGERPRINT=""
RECEIPT_READY=0
# Whether every stage so far was proved already done.  The moment one
# does work, no later stage may be called fresh: its inputs have just
# changed underneath it.
FRESH_PREFIX=1

# ---------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------
note() {
    printf '%s=%s\n' "$1" "$2"
}

# format_elapsed SECONDS
#   Whole seconds as something an operator reads at a glance.  The input
#   is always a difference of two readings of bash's own SECONDS, so no
#   value from the environment reaches this arithmetic -- which matters,
#   because bash resolves a command substitution inside $(( )) and an
#   unchecked number there is not a number.  A timeout that DOES come from
#   the environment goes through playthrough_validate_int instead.
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
#   The words separated by a single space, or "none" when there are none.  Used
#   for the two summary lines, so an empty list reads as an answer rather than
#   as a missing one.
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
# gate_check_total TABLE -- the number of checks the acceptance gate DECLARES
# for one phase, read out of the gate itself.
gate_check_total() {
    local table="$1"
    local script="${SCRIPT_DIR}/${STAGE_SCRIPT[${GATE_STAGE}]}"
    local want="readonly -a GROUP_CHECKS_${table}=("
    local line="" grab=0 total=0 value=""
    local -a fields=()
    if [ ! -r "${script}" ]; then
        printf '?'
        return 0
    fi
    while IFS= read -r line; do
        if [ "${grab}" -eq 1 ]; then
            read -r -a fields <<<"${line}"
            for value in "${fields[@]}"; do
                case "${value}" in
                    ''|*[!0-9]*) continue ;;
                esac
                total=$(( total + value ))
            done
            printf '%d' "${total}"
            return 0
        fi
        if [ "${line}" = "${want}" ]; then
            grab=1
        fi
    done <"${script}"
    printf '?'
    return 0
}


usage() {
    local every="" early="" late="" deferred=""
    every="$(gate_check_total ALL)"
    early="$(gate_check_total PRE_COMMIT)"
    late="$(gate_check_total POST_COMMIT)"
    deferred="?"
    case "${every}${early}" in
        *'?'*) ;;
        *) deferred="$(( every - early ))" ;;
    esac
    cat <<'USAGE'
run_pipeline.sh -- run the post-session render stages in dependency
order.  It sequences the modules that do the work and holds none of
their logic itself.

    playthrough/tooling/run_pipeline.sh [options]
USAGE
    printf '%s\n' ""
    printf '%s\n' "Stages, in order:"
    printf '    %-14s %s\n' \
        "timeline" "timeline.py           -> playthrough/timeline.json" \
        "transitions" "make_transitions.py   -> build/transitions/*.png" \
        "render" "render_movie.py       -> playthrough/cata-play.mp4" \
        "srt" "make_srt.py           -> transcript.srt + .md" \
        "captions" "embed_captions.sh     -> cata-play-cc.mp4" \
        "${GATE_STAGE}" "verify_artifacts.sh --phase \
${GATE_PRE_COMMIT_PHASE}" \
        "${COMMIT_STAGE}" "commit_artifacts.sh \
${PIPELINE_CHECKPOINT_NAME}" \
        "${ATTEST_STAGE}" "verify_artifacts.sh --phase \
${GATE_POST_COMMIT_PHASE} --report-to <outside the checkout>" \
        "${PUBLISH_STAGE}" "commit_artifacts.sh \
${PIPELINE_ATTESTATION_NAME}"
    printf '%s\n' ""
    printf '%s\n' "THE GATE RUNS TWICE, and the split is what makes \
the commit reachable."
    printf '%s\n' "Most of its checks are functional -- is the film \
watchable, do the"
    printf '%s\n' "captions line up with the frames -- and can be \
answered as soon as the"
    printf '%s\n' "artifacts exist.  ${deferred} are about the \
history: is the save tracked, is"
    printf '%s\n' "every class committed, is the tree clean.  Those \
cannot pass BEFORE the"
    printf '%s\n' "commit, because the commit is what makes them \
true.  So \`${GATE_STAGE}\` runs the"
    printf '%s\n' "functional half and guards the commit, and \
\`${ATTEST_STAGE}\` runs the history half"
    printf '%s\n' "afterwards and reports what was published.  The \
second run is the short"
    printf '%s\n' "one: ${early} checks before the commit and \
${late} after it, out of ${every} in all,"
    printf '%s\n' "so no artifact is re-measured after a commit that \
did not touch it."
    printf '%s\n' "These three totals are READ OUT OF THE GATE at help \
time rather than"
    printf '%s\n' "written down here, because a second copy of a \
number goes stale."
    printf '%s\n' ""
    printf '%s\n' "COMMIT, MEASURE, PUBLISH, AND THE TREE ENDS CLEAN."
    printf '%s\n' "The gate writes NOTHING into the tree it measures: \
a report written there"
    printf '%s\n' "would dirty the very file the run had just \
certified as committed, which"
    printf '%s\n' "is what it used to do.  So \`${ATTEST_STAGE}\` \
writes its report to a path"
    printf '%s\n' "outside the checkout and \`${PUBLISH_STAGE}\` \
commits it, refusing a report"
    printf '%s\n' "that failed, that measured no history, or that \
names a commit other than"
    printf '%s\n' "HEAD.  \`${PUBLISH_STAGE}\` will not run without \
\`${ATTEST_STAGE}\` in the same"
    printf '%s\n' "invocation, so a report an earlier run left behind \
cannot be committed."
    cat <<'USAGE'

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
  --rebuild     ignore the run receipt and run every planned stage, even
                one this run could prove was already done.  The receipt
                is still written, so the run after this one is fast again.
  --            end of options.  Nothing may follow it: this sequencer
                takes no positional arguments, so a `--` is only ever the
                end of the line.
  -h, --help    print this and exit.

--from and --only are mutually exclusive.  Repeating either one is
allowed and the LAST occurrence wins, which is what a shell alias with an
appended override does.
USAGE
    printf '%s\n' ""
    printf '%s\n' "A stage may be named by its short name above, by \
its script, or by that"
    printf '%s\n' "script without the extension: render, render_movie \
and render_movie.py"
    printf '%s\n' "are the same stage.  \`${ATTEST_STAGE}\` and \
\`${PUBLISH_STAGE}\` are the exceptions,"
    printf '%s\n' "reachable by their short names only: each is a \
second run of a script an"
    printf '%s\n' "earlier stage already owns -- verify_artifacts.sh \
names \`${GATE_STAGE}\` and"
    printf '%s\n' "commit_artifacts.sh names \`${COMMIT_STAGE}\` -- \
and one script name cannot"
    printf '%s\n' "resolve to two stages."
    printf '%s\n' ""
    printf '%s\n' "Three rules are enforced over the resolved plan \
rather than over the flags"
    printf '%s\n' "that produced it, so they keep holding if a flag is \
ever added:"
    printf '%s\n' "  * ${COMMIT_STAGE} will not run unless \
${GATE_STAGE} runs ahead of it in the same"
    printf '%s\n' "    invocation.  The gate is what stops a black \
film or a drifted caption"
    printf '%s\n' "    track from reaching the history."
    printf '%s\n' "  * ${ATTEST_STAGE} will not run without \
${COMMIT_STAGE} in the same invocation.  Every"
    printf '%s\n' "    check it adds asks whether the history records \
something, so on its"
    printf '%s\n' "    own it fails for reasons this run did not cause."
    printf '%s\n' "  * ${PUBLISH_STAGE} will not run without \
${ATTEST_STAGE} in the same invocation.  It"
    printf '%s\n' "    commits the report the attestation measured, so \
without it there is"
    printf '%s\n' "    either nothing to publish or a report from an \
earlier run over a"
    printf '%s\n' "    different tree."
    printf '%s\n' "Asking for any of the three alone is therefore \
refused."
    cat <<'USAGE'

THREE THINGS ARE SETTLED BEFORE THE FIRST STAGE RUNS, because each of
them was previously discovered after the expensive work:
  * WOULD THE CHECKPOINT BE TAKEN?  The checkpoint this file takes
    commits a render, and a render is about a session whose save has
    already been published -- so it needs a `final` checkpoint for the
    survivor this userdir has loaded, reached from that survivor's own
    `creation`.  commit_artifacts.sh answers that read-only through its
    own `status` subcommand, which reports one answer per checkpoint; this
    file reads the one for the checkpoint it takes.  A plan that cannot
    reach that checkpoint is refused here with exit 4, naming --no-commit
    as the way to run the render half deliberately.
  * IS THERE ROOM?  The reserve is measured from what is on disk -- the
    artifacts a producing stage rewrites, the staging copy the caption
    mux needs, the objects the checkpoint writes -- plus a fixed margin,
    and it is checked before the first stage and again before the
    checkpoint.  Too little room is exit 5, refused before anything is
    written; nothing is ever decimated to make a generation fit.  A
    measurement that cannot be taken is reported and does not block the
    run.
  * IS ANY OF IT ALREADY DONE?  A content-addressed receipt in the
    runtime directory -- never in the working tree -- records what each
    producing stage was made from and what it produced.  A stage is
    skipped only when both still hold and no earlier stage in this run
    did any work.  The gate, the checkpoint and the attestation are never
    skipped; --only never skips the stage it names; --rebuild ignores the
    receipt.

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
        publish)
            printf 'publish' ;;
        *)
            return 1 ;;
    esac
    return 0
}
# NOTE ON `attest` AND `publish`: they are the two stages with no script alias,
# and deliberately so.

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
#   error, so the plan may legitimately be empty here -- a case
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
#   exiting, so that a sourced consumer cannot have its shell killed by a
#   diagnostic; the exit is therefore taken here explicitly, and `|| true`
#   keeps errexit from ending the script on the report itself before the
#   intended status is chosen.
die() {
    local status="$1"
    shift
    playthrough_die "$@" || true
    exit "${status}"
}

# ---------------------------------------------------------------------
# ARGUMENTS
# Both spellings of each option are accepted -- `--from render` and
# `--from=render` -- because the siblings in this folder accept both and an
# operator should not have to remember which one this file wanted.
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
            --rebuild)
                REBUILD=1
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
# One contiguous run of STAGE_ORDER, or exactly one stage of it.
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

    # --no-commit drops the checkpoint AND the attestation that follows it.
    if [ "${NO_COMMIT}" -eq 1 ]; then
        for name in "${PLAN[@]}"; do
            if [ "${name}" = "${COMMIT_STAGE}" ] ||
               [ "${name}" = "${ATTEST_STAGE}" ] ||
               [ "${name}" = "${PUBLISH_STAGE}" ]; then
                SKIPPED+=("${name}")
            else
                kept+=("${name}")
            fi
        done
        PLAN=("${kept[@]}")
    fi

    # THE TWO RULES THIS FILE ENFORCES ON ITS OWN BEHALF, both asserted over
    # the RESOLVED plan rather than over the flags that produced it, so they
    # keep holding if another flag is ever added.
    if plan_contains "${COMMIT_STAGE}" &&
       ! plan_contains "${GATE_STAGE}"; then
        die "${EX_USAGE}" "the ${COMMIT_STAGE} stage will not run" \
            "unless the ${GATE_STAGE} stage runs ahead of it in the" \
            "same invocation: the gate is what stops an unwatchable" \
            "film or a drifted caption track from reaching the" \
            "history.  Use --from ${GATE_STAGE} to take the" \
            "checkpoint behind its gate."
    fi

    # SECOND, and the mirror of it: the attestation reads what the checkpoint
    # published, so on its own it is a report about somebody else's commit.
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

    # THIRD: the publication commits what the attestation MEASURED, so it
    # cannot run without it. This is the rule that closes the sequence.
    if plan_contains "${PUBLISH_STAGE}" &&
       ! plan_contains "${ATTEST_STAGE}"; then
        die "${EX_USAGE}" "the ${PUBLISH_STAGE} stage commits the" \
            "report the ${ATTEST_STAGE} stage measures, so it will not" \
            "run without it in the same invocation: the report is" \
            "written to a path outside the checkout and published from" \
            "there, and publishing one an earlier run left behind would" \
            "commit a measurement of a different tree.  Use --from" \
            "${GATE_STAGE} to run the gate, the checkpoint, the" \
            "attestation and the publication together."
    fi

    if [ "${#PLAN[@]}" -eq 0 ]; then
        die "${EX_USAGE}" "that combination of options leaves no" \
            "stage to run."
    fi
}

# ---------------------------------------------------------------------
# PREFLIGHT
# Everything the plan needs is proved present before the first stage starts, so
# a missing module is one message now rather than a failure part way through a
# render.
# ---------------------------------------------------------------------
stage_script_path() {
    printf '%s/%s' "${SCRIPT_DIR}" "${STAGE_SCRIPT[$1]}"
}

# open_pipeline_scratch
#   Create this run's private scratch directory and leave it in
#   PIPELINE_SCRATCH.  Returns non-zero if it cannot.
open_pipeline_scratch() {
    if [ -n "${PIPELINE_SCRATCH}" ] && [ -d "${PIPELINE_SCRATCH}" ]; then
        return 0
    fi
    local dir=""
    dir="$(mktemp -d "${PLAYTHROUGH_RUNTIME_DIR}/pipeline-XXXXXX" \
        2>/dev/null)" || return 1
    playthrough_secure_dir "${dir}" 700 \
        "the sequencer's scratch directory" || return 1
    PIPELINE_SCRATCH="${dir}"
    return 0
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
# THE MEASUREMENT TOOLCHAIN
# The capacity model and the run receipt both need external tools, and NEITHER
# OF THEM IS ALLOWED TO STOP A RENDER.
# ---------------------------------------------------------------------
resolve_measurement_tools() {
    if ! playthrough_require_tools git find wc sort mv df du \
            sha256sum 2>/dev/null; then
        MEASURED_READY=0
        playthrough_warn "the tools that measure free space and" \
            "fingerprint this run are incomplete, so this run will" \
            "neither check capacity beforehand nor skip a stage it" \
            "could have proved was already done.  Every stage still" \
            "runs and every stage still checks its own preconditions;" \
            "install git, findutils and coreutils to get the early" \
            "refusals back."
        return 1
    fi
    GIT="${PLAYTHROUGH_BIN_GIT}"
    FIND="${PLAYTHROUGH_BIN_FIND}"
    WC="${PLAYTHROUGH_BIN_WC}"
    SORT="${PLAYTHROUGH_BIN_SORT}"
    MV="${PLAYTHROUGH_BIN_MV}"
    DF="${PLAYTHROUGH_BIN_DF}"
    DU="${PLAYTHROUGH_BIN_DU}"
    SHA256SUM="${PLAYTHROUGH_BIN_SHA256SUM}"
    MEASURED_READY=1
    return 0
}

# ---------------------------------------------------------------------
# THE DEPENDENCY CLOSURE
# assert_interpreter above establishes that a Python EXISTS and can be
# executed.
assert_dependency_closure() {
    plan_needs_interpreter || return 0
    # NOT `$(open_pipeline_scratch)`: it assigns PIPELINE_SCRATCH in this
    # shell, and a command substitution would put that assignment in a subshell
    # where the exit trap can never see it.
    open_pipeline_scratch ||
        die "${EX_LAYOUT}" "cannot open a private scratch directory" \
            "under '$(playthrough_rel "${PLAYTHROUGH_RUNTIME_DIR}")'" \
            "to measure the dependency closure in."
    local program="${PIPELINE_SCRATCH}/closure.py"
    local out="${PIPELINE_SCRATCH}/closure.out"
    local err="${PIPELINE_SCRATCH}/closure.err"
    if ! playthrough_write_closure_checker "${program}"; then
        die "${EX_LAYOUT}" "the shared dependency-closure checker" \
            "could not be written, so the closure cannot be" \
            "measured.  It is defined in" \
            "playthrough/tooling/env.sh and materialised here; a" \
            "closure that was not measured is not a closure that" \
            "passed, so this run stops rather than assuming it."
    fi
    local status=0
    "${PLAYTHROUGH_PYTHON}" -B "${program}" \
        "${CLOSURE_SEPARATOR}" \
        "${PLAYTHROUGH_REQUIREMENTS}" \
        "${PLAYTHROUGH_REQUIREMENTS_LOCK}" \
        >"${out}" 2>"${err}" || status=$?
    # A CRASH IS NOT A FAILING VERDICT: output on stderr, or no output at
    # all, means the checker did not get to judge, which is reported as
    # its own fault rather than as the closure being wrong.
    if [ -s "${err}" ] || [ ! -s "${out}" ]; then
        local detail=""
        detail="$(tail -n 3 "${err}" 2>/dev/null | tr '\n' ' ' ||
            true)"
        die "${EX_LAYOUT}" "the dependency closure could not be" \
            "measured: ${detail:-<no diagnostic and no verdicts>}." \
            "This is the checker failing to run rather than the" \
            "closure being wrong, so the fault is in the interpreter" \
            "or the declaration files rather than in the installed" \
            "libraries."
    fi
    local failed=()
    local kind="" name="" observed="" expected=""
    while IFS="${CLOSURE_SEPARATOR}" \
            read -r kind name observed expected; do
        case "${kind}" in
            FAIL)
                failed+=("${name}: ${observed} (needed: ${expected})")
                ;;
            INFO)
                note PIPELINE_CLOSURE "${observed}"
                ;;
        esac
    done <"${out}"
    if [ "${#failed[@]}" -ne 0 ] || [ "${status}" -ne 0 ]; then
        local why=""
        if [ "${#failed[@]}" -ne 0 ]; then
            why="$(printf '%s; ' "${failed[@]}")"
            why="${why%; }"
        else
            why="the checker exited ${status} without naming a \
failing property"
        fi
        note PIPELINE_CLOSURE_FAILED "${#failed[@]}"
        die "${EX_LAYOUT}" "the Python dependency closure is not the" \
            "one this pipeline was reviewed against, so no stage" \
            "runs: ${why}.  Install" \
            "playthrough/tooling/requirements.lock into the" \
            "interpreter env.sh resolved" \
            "('${PLAYTHROUGH_PYTHON}') with --require-hashes, rather" \
            "than installing something that merely imports: the" \
            "exact pins are what keep a later release from changing" \
            "the rendered film while every other gate still passes."
    fi
    return 0
}

# ---------------------------------------------------------------------
# WHAT EACH PRODUCING STAGE LEAVES BEHIND
# stage_outputs NAME
#   One path per line, from env.sh's exported layout and from nowhere
#   else -- so this is the artifact LAYOUT, which env.sh owns and every
#   stage shares, not a copy of any stage's logic.  A directory stands for
#   its contents.
#
#   RETURNS 1 FOR THE STAGES THAT PRODUCE NO ARTIFACT.  The gate runs, the
#   checkpoint and the attestation answer questions about a moment in time;
#   there is nothing they could be proved to have already done, and this is
#   the single place that fact is expressed.  Everything downstream reads a
#   non-zero status here as "never fresh".
# ---------------------------------------------------------------------
stage_outputs() {
    case "$1" in
        timeline)
            printf '%s\n' "${PLAYTHROUGH_TIMELINE}"
            ;;
        transitions)
            printf '%s\n' "${PLAYTHROUGH_TRANSITIONS_DIR}"
            ;;
        render)
            printf '%s\n' "${PLAYTHROUGH_MOVIE}" \
                "${PLAYTHROUGH_CONCAT_LIST}"
            ;;
        srt)
            printf '%s\n' "${PLAYTHROUGH_TRANSCRIPT_SRT}" \
                "${PLAYTHROUGH_TRANSCRIPT_MD}"
            ;;
        captions)
            printf '%s\n' "${PLAYTHROUGH_MOVIE_CC}"
            ;;
        *)
            return 1
            ;;
    esac
    return 0
}

# ---------------------------------------------------------------------
# MEASURING
# Every number these three return comes from a tool and is therefore CHECKED
# BEFORE IT REACHES ARITHMETIC: bash resolves a command substitution inside $((
# )), so an unchecked value there is an instruction rather than a number.
# ---------------------------------------------------------------------

# disk_free_kib PATH -- kibibytes available on the filesystem holding PATH, or
# nothing.
disk_free_kib() {
    local line="" last=""
    local -a fields=()
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        last="${line}"
    done < <("${DF}" -Pk -- "$1" 2>/dev/null)
    if [ -z "${last}" ]; then
        return 1
    fi
    read -r -a fields <<<"${last}"
    if [ "${#fields[@]}" -lt 4 ]; then
        return 1
    fi
    case "${fields[3]}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "${fields[3]}"
}

# tree_kib PATH -- kibibytes PATH occupies, 0 when it does not exist,
# nothing when the measurement failed.  A file and a directory are both
# answered, which is why the callers do not have to know which they hold.
tree_kib() {
    local out="" leading=""
    if [ ! -e "$1" ]; then
        printf '0'
        return 0
    fi
    out="$("${DU}" -sk -- "$1" 2>/dev/null || printf '')"
    if [ -z "${out}" ]; then
        return 1
    fi
    leading="${out%%[!0-9]*}"
    case "${leading}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "${leading}"
}

# mebibytes BYTES -- whole mebibytes, for a figure a human reads. The byte
# count is reported alongside it every time, so nothing depends on this
# rounding.
mebibytes() {
    case "${1-}" in
        ''|*[!0-9]*)
            printf 'an unmeasured number of'
            return 0
            ;;
    esac
    printf '%s' "$(( $1 / BYTES_PER_MIB ))"
}

# ---------------------------------------------------------------------
# THE CAPACITY MODEL
# THE ARTIFACTS ARE FULL-RESOLUTION AND NOTHING IS EVER DROPPED TO MAKE THEM
# FIT, so running out of room part way through a stage does not produce a
# smaller generation -- it produces a torn one, and the operator finds out from
# a truncated film or a half-written cue file.
# ---------------------------------------------------------------------

# capacity_ok WHEN
#   WHEN is `plan` (before the first stage, every term) or `checkpoint`
#   (immediately before the commit, when the producing stages are done and
#   only the history term is still ahead).  Reports its own refusal in full
#   and returns 1; the caller decides what to do about it.
capacity_ok() {
    local when="$1"
    local free_kib="" term="" path=""
    local reserve=0 rewrite=0 staging=0 history=0 free=0
    local name="" key="PIPELINE_CAPACITY"
    # Neither of the two moments is a value from anywhere but this file,
    # so a third one is a fault here rather than a term to leave out
    # quietly -- which is what an unrecognised word would otherwise do.
    case "${when}" in
        plan) ;;
        # The two moments report under two keys, so a caller building a
        # dictionary from this channel does not have one overwrite the
        # other: the first says whether the plan fits, the second whether
        # the checkpoint still does once the films are on the disk.
        checkpoint) key="PIPELINE_CAPACITY_CHECKPOINT" ;;
        *)
            die "${EX_LAYOUT}" "'${when}' is not a moment this file" \
                "measures capacity at, which is a fault in this file" \
                "rather than in the plan"
            ;;
    esac
    if [ "${MEASURED_READY}" -ne 1 ]; then
        note "${key}" "unmeasured"
        return 0
    fi
    if ! free_kib="$(disk_free_kib "${REPO_ROOT}")"; then
        note "${key}" "unmeasured"
        playthrough_warn "the free space on the filesystem holding" \
            "this checkout could not be read, so this run does not" \
            "know whether there is room for it.  Every stage still" \
            "checks its own preconditions."
        return 0
    fi
    free=$(( free_kib * 1024 ))

    if [ "${when}" = "plan" ]; then
        for name in "${PLAN[@]}"; do
            while IFS= read -r path; do
                if ! term="$(tree_kib "${path}")"; then
                    continue
                fi
                rewrite=$(( rewrite + term * 1024 ))
            done < <(stage_outputs "${name}" || printf '')
        done
        if plan_contains "${CAPTION_STAGE}"; then
            if term="$(tree_kib "${PLAYTHROUGH_MOVIE}")"; then
                staging=$(( term * 1024 ))
            fi
        fi
    fi
    if plan_contains "${COMMIT_STAGE}"; then
        if term="$(tree_kib "${PLAYTHROUGH_DIR}")"; then
            history=$(( term * 1024 ))
        fi
    fi
    reserve=$(( rewrite + staging + history + CAPACITY_MARGIN_BYTES ))
    note "${key}" "${free}:${reserve}"
    if [ "${free}" -ge "${reserve}" ]; then
        playthrough_log "room to work: ${free} byte(s) free" \
            "($(mebibytes "${free}") MiB) against a ${reserve}-byte" \
            "reserve ($(mebibytes "${reserve}") MiB: ${rewrite}" \
            "rewrite + ${staging} staging + ${history} history +" \
            "${CAPACITY_MARGIN_BYTES} margin)"
        return 0
    fi
    playthrough_die "there is not room to run this plan: ${free}" \
        "byte(s) free ($(mebibytes "${free}") MiB) against a reserve" \
        "of ${reserve} ($(mebibytes "${reserve}") MiB) --" \
        "${rewrite} for the artifacts these stages rewrite," \
        "${staging} for the staging copy the caption mux needs," \
        "${history} for the objects the checkpoint writes, and" \
        "${CAPACITY_MARGIN_BYTES} of margin.  Free" \
        "$(( reserve - free )) more byte(s)" \
        "($(mebibytes "$(( reserve - free ))" ) MiB) and run this" \
        "again.  NOTHING IS DROPPED TO MAKE A GENERATION FIT, so this" \
        "is refused now rather than torn later." || true
    return 1
}

# assert_capacity WHEN -- the same check, taken as a refusal.
assert_capacity() {
    capacity_ok "$1" || exit "${EX_CAPACITY}"
}

# ---------------------------------------------------------------------
# THE LIFECYCLE PREFLIGHT
# The checkpoint this file takes commits a RENDER, and a render is about a
# session whose save has already been published -- so it requires a `final`
# checkpoint for the survivor this userdir has loaded, reached from that
# survivor's own `creation` rather than from the trailer alone.
# ---------------------------------------------------------------------
LIFECYCLE_ELIGIBLE=""
LIFECYCLE_REASON=""
LIFECYCLE_ANCHOR=""

probe_lifecycle() {
    local script="" line="" key="" value=""
    local -a probe=()
    script="$(stage_script_path "${COMMIT_STAGE}")"
    if [ -x "${script}" ]; then
        probe=( "${script}" )
    else
        probe=( "${BASH}" "${script}" )
    fi
    probe+=( "${LIFECYCLE_PROBE_SUBCOMMAND}" )
    LIFECYCLE_ELIGIBLE=""
    LIFECYCLE_REASON=""
    LIFECYCLE_ANCHOR=""
    while IFS= read -r line; do
        key="${line%%=*}"
        value="${line#*=}"
        case "${key}" in
            "${LIFECYCLE_KEY_ELIGIBLE}")
                LIFECYCLE_ELIGIBLE="${value}" ;;
            "${LIFECYCLE_KEY_REASON}")
                LIFECYCLE_REASON="${value}" ;;
            "${LIFECYCLE_KEY_ANCHOR}")
                LIFECYCLE_ANCHOR="${value}" ;;
        esac
    done < <("${probe[@]}")
    if [ -z "${LIFECYCLE_ELIGIBLE}" ]; then
        return 1
    fi
    return 0
}

assert_lifecycle_eligible() {
    plan_contains "${COMMIT_STAGE}" || return 0
    playthrough_log "asking $(playthrough_rel \
        "$(stage_script_path "${COMMIT_STAGE}")")" \
        "${LIFECYCLE_PROBE_SUBCOMMAND}, which changes nothing," \
        "whether the '${PIPELINE_CHECKPOINT_NAME}' checkpoint could be" \
        "taken at all; its own report follows"
    if ! probe_lifecycle; then
        note PIPELINE_LIFECYCLE "unread"
        playthrough_warn "that answer could not be read, so this run" \
            "does not know in advance whether the checkpoint can be" \
            "taken.  It proceeds: the checkpoint stage is the" \
            "authority on its own lifecycle either way."
        return 0
    fi
    if [ "${LIFECYCLE_ELIGIBLE}" = "${LIFECYCLE_ELIGIBLE_VALUE}" ]; then
        note PIPELINE_LIFECYCLE "eligible"
        playthrough_log "the '${PIPELINE_CHECKPOINT_NAME}'" \
            "checkpoint would anchor to" \
            "${LIFECYCLE_ANCHOR:0:10}, so this plan can reach it"
        return 0
    fi
    note PIPELINE_LIFECYCLE "${LIFECYCLE_REASON:-ineligible}"
    die "${EX_INELIGIBLE}" "the '${PIPELINE_CHECKPOINT_NAME}'" \
        "checkpoint CANNOT be taken over this tree" \
        "(${LIFECYCLE_REASON:-no reason given}), and its reason is" \
        "above.  That is settled before anything is rendered, so no" \
        "stage is run: this plan would otherwise spend the timeline," \
        "the transitions, the encode, the transcripts, the caption mux" \
        "and the whole functional gate to be refused at the" \
        "checkpoint.  Fix the lifecycle -- take the anchoring" \
        "checkpoint for THIS survivor, which the report above names --" \
        "or pass --no-commit to run the render half deliberately and" \
        "take the checkpoint by hand afterwards."
}

# ---------------------------------------------------------------------
# THE RUN RECEIPT
# WHAT PROBLEM IT SOLVES.
# ---------------------------------------------------------------------

# file_digest PATH -- the sha256 of a file, or the word `absent` when there is
# none and `unreadable` when there is one that cannot be read.
file_digest() {
    local out=""
    if [ ! -f "$1" ]; then
        printf 'absent'
        return 0
    fi
    out="$("${SHA256SUM}" -- "$1" 2>/dev/null || printf '')"
    if [ -z "${out}" ]; then
        printf 'unreadable'
        return 0
    fi
    printf '%s' "${out%% *}"
}

# input_paths -- the paths whose git state the fingerprint covers, one per
# line.
input_paths() {
    printf '%s\n' \
        "${PLAYTHROUGH_FRAMES_DIR}" \
        "${PLAYTHROUGH_MANIFEST}" \
        "${PLAYTHROUGH_AMENDMENTS}" \
        "${PLAYTHROUGH_USERDIR}"
}

# input_git_state -- a digest of git's own answer about those paths.
# One streamed pass, nothing held: on an unbounded session this is one
# line per capture and the digest is taken as they go past.
input_git_state() {
    local -a paths=()
    local path=""
    while IFS= read -r path; do
        paths+=("${path}")
    done < <(input_paths)
    local out=""
    out="$("${GIT}" status --porcelain --untracked-files=all -- \
        "${paths[@]}" 2>/dev/null | "${SHA256SUM}" || printf '')"
    if [ -z "${out}" ]; then
        printf 'unreadable'
        return 0
    fi
    printf '%s' "${out%% *}"
}

# capture_count -- how many captures are on disk. A count rather than a digest
# of them: the capture ledger already binds their CONTENT, and this is the
# cheap half that notices a frame arriving or leaving.
capture_count() {
    local total=""
    total="$("${FIND}" "${PLAYTHROUGH_FRAMES_DIR}" -maxdepth 1 \
        -type f -name '*.png' 2>/dev/null | "${WC}" -l || printf '')"
    total="${total// /}"
    case "${total}" in
        ''|*[!0-9]*) printf 'unreadable' ;;
        *) printf '%s' "${total}" ;;
    esac
}

# input_fingerprint -- the identity of everything a producing stage reads, as
# one digest.
input_fingerprint() {
    local out="" name=""
    out="$(
        {
            printf 'format\t%s\n' "${RECEIPT_FORMAT}"
            printf 'head\t%s\n' "$("${GIT}" rev-parse HEAD \
                2>/dev/null || printf 'none')"
            printf 'inputs\t%s\n' "$(input_git_state)"
            printf 'captures\t%s\n' "$(capture_count)"
            printf 'record\t%s\n' \
                "$(file_digest "${PLAYTHROUGH_MANIFEST}")"
            printf 'amendments\t%s\n' \
                "$(file_digest "${PLAYTHROUGH_AMENDMENTS}")"
            printf 'ledger\t%s\n' \
                "$(file_digest "${PLAYTHROUGH_FRAME_DIGESTS}")"
            printf 'closure\t%s\n' \
                "$(file_digest "${PLAYTHROUGH_REQUIREMENTS}")"
            printf 'interpreter\t%s\n' "${PLAYTHROUGH_PYTHON}"
            printf 'trust\t%s\n' \
                "${PLAYTHROUGH_TRUST_STATE:-unknown}"
            for name in "${STAGE_ORDER[@]}"; do
                printf 'stage:%s\t%s\n' "${name}" \
                    "$(file_digest "$(stage_script_path "${name}")")"
            done
        } | "${SHA256SUM}" || printf ''
    )"
    if [ -z "${out}" ]; then
        return 1
    fi
    printf '%s' "${out%% *}"
}

# outputs_digest NAME -- one digest over everything that stage produced, or
# nothing at all when any declared output is missing (which is itself the
# answer: a stage whose output has gone has not been done).
outputs_digest() {
    local name="$1" path="" out=""
    stage_outputs "${name}" >/dev/null || return 1
    while IFS= read -r path; do
        if [ ! -e "${path}" ]; then
            return 1
        fi
    done < <(stage_outputs "${name}")
    out="$(
        {
            while IFS= read -r path; do
                if [ -d "${path}" ]; then
                    "${FIND}" "${path}" -type f \
                        -exec "${SHA256SUM}" -- {} +
                else
                    "${SHA256SUM}" -- "${path}"
                fi
            done < <(stage_outputs "${name}")
        } | "${SORT}" | "${SHA256SUM}" || printf ''
    )"
    if [ -z "${out}" ]; then
        return 1
    fi
    printf '%s' "${out%% *}"
}

# open_receipt -- resolve the receipt for this checkout and compute this run's
# fingerprint. Sets RECEIPT_READY, which every other receipt helper reads, so a
# host that cannot support one simply runs every stage.
open_receipt() {
    local name=""
    RECEIPT_READY=0
    if [ "${MEASURED_READY}" -ne 1 ]; then
        note PIPELINE_RECEIPT "none"
        return 1
    fi
    if ! name="$(playthrough_checkout_lock_name \
            "${RECEIPT_BASENAME}")"; then
        note PIPELINE_RECEIPT "none"
        playthrough_warn "the receipt name for this checkout could" \
            "not be derived, so no stage will be skipped."
        return 1
    fi
    RECEIPT_FILE="${PLAYTHROUGH_RUN_DIR}/${name}"
    if [ ! -d "${PLAYTHROUGH_RUN_DIR}" ] ||
       [ ! -w "${PLAYTHROUGH_RUN_DIR}" ]; then
        note PIPELINE_RECEIPT "none"
        playthrough_warn "${PLAYTHROUGH_RUN_DIR} is not a writable" \
            "directory, so this run cannot record what it did and no" \
            "stage will be skipped."
        return 1
    fi
    if ! RECEIPT_FINGERPRINT="$(input_fingerprint)"; then
        note PIPELINE_RECEIPT "none"
        playthrough_warn "this run's inputs could not be" \
            "fingerprinted, so no stage will be skipped."
        return 1
    fi
    RECEIPT_READY=1
    note PIPELINE_RECEIPT "${name}"
    # The path is passed WHOLE rather than through playthrough_rel:
    # env.sh's redaction rewrites the runtime directory to <runtime>,
    # which locates the file, where playthrough_rel would reduce an
    # outside path to its basename and say only that it is outside.
    playthrough_log "run receipt ${RECEIPT_FILE}, inputs" \
        "${RECEIPT_FINGERPRINT:0:12}"
    return 0
}

# receipt_entry NAME -- the recorded output digest for that stage IF the
# recorded input fingerprint is this run's, else nothing.
receipt_entry() {
    local name="$1" line="" field_stage="" field_inputs="" rest=""
    if [ "${RECEIPT_READY}" -ne 1 ] || [ ! -f "${RECEIPT_FILE}" ]; then
        return 1
    fi
    while IFS= read -r line; do
        case "${line}" in
            '#'*|'') continue ;;
        esac
        field_stage="${line%%"${RECEIPT_SEPARATOR}"*}"
        [ "${field_stage}" = "${name}" ] || continue
        rest="${line#*"${RECEIPT_SEPARATOR}"}"
        field_inputs="${rest%%"${RECEIPT_SEPARATOR}"*}"
        [ "${field_inputs}" = "${RECEIPT_FINGERPRINT}" ] || return 1
        printf '%s' "${rest#*"${RECEIPT_SEPARATOR}"}"
        return 0
    done <"${RECEIPT_FILE}"
    return 1
}

# record_receipt NAME -- write down what this stage was made from and what it
# produced.
record_receipt() {
    local name="$1" digest="" line="" field_stage=""
    local temporary=""
    if [ "${RECEIPT_READY}" -ne 1 ]; then
        return 0
    fi
    if ! digest="$(outputs_digest "${name}")"; then
        return 0
    fi
    temporary="${RECEIPT_FILE}.new"
    {
        printf '%s %s\n' "${RECEIPT_HEADER}" "${RECEIPT_FORMAT}"
        if [ -f "${RECEIPT_FILE}" ]; then
            while IFS= read -r line; do
                case "${line}" in
                    '#'*|'') continue ;;
                esac
                field_stage="${line%%"${RECEIPT_SEPARATOR}"*}"
                [ "${field_stage}" != "${name}" ] || continue
                printf '%s\n' "${line}"
            done <"${RECEIPT_FILE}"
        fi
        printf '%s\t%s\t%s\n' "${name}" "${RECEIPT_FINGERPRINT}" \
            "${digest}"
    } >"${temporary}" || {
        playthrough_warn "this run could not record what the" \
            "'${name}' stage produced, so the next one will repeat it."
        return 0
    }
    "${MV}" -f -- "${temporary}" "${RECEIPT_FILE}" || {
        playthrough_warn "the receipt could not be replaced, so the" \
            "next run will repeat this one's work."
        return 0
    }
    return 0
}

# resolve_omitted_producer_freshness -- a plan that starts partway through
# the producing stages may not SKIP anything.
#
# THIS IS THE HOLE IN FRESH_PREFIX'S REASONING, and it is worth spelling
# out because that reasoning is otherwise sound.  Freshness collapses at the
# first stage that does any work, so in a FULL plan a skipped encode implies
# a skipped timeline, which implies the timeline's bytes are the ones the
# encode was built from.  That does not hold for `--from render`: the
# timeline and transition stages are then neither run nor skipped but
# ABSENT, so nothing collapses FRESH_PREFIX and nothing looks at them.  A
# timeline.json edited since the receipt was written is invisible -- the
# input fingerprint covers the pipeline's INPUTS, not its intermediates, and
# the film's own digest still matches the receipt -- so `render` would be
# declared fresh and skipped, and the film that survives would be one built
# from a timeline that no longer exists.
#
# THE REMEDY IS TO STOP SKIPPING, NOT TO REFUSE.  Refusing the plan would
# defeat the point of `--only` and `--from`, and on any tree without a
# receipt -- a fresh clone, a first run -- there is nothing to vouch for the
# earlier stages with, so every such invocation would be refused.  The
# hazard was never that the stage RUNS; it is that it is SKIPPED while
# something upstream has moved.  So freshness is switched off for the whole
# plan, every stage in it does its work, and what comes out is consistent
# with the intermediates as they actually are.  A demonstrably stale
# predecessor is REPORTED as well, because the acceptance gate is what
# refuses to publish an inconsistent set: this file sequences, the gate
# judges.
resolve_omitted_producer_freshness() {
    local name="" recorded="" current="" first=-1 index=0
    local -a omitted=() stale=()
    for name in "${PLAN[@]}"; do
        if [ "${STAGE_DERIVES_EVIDENCE[${name}]}" = "1" ]; then
            first="$(stage_index "${name}")"
            break
        fi
    done
    # No producing stage in the plan, or it begins at the first one:
    # nothing was jumped over and FRESH_PREFIX's reasoning holds.
    if [ "${first}" -le 0 ]; then
        return 0
    fi
    for name in "${STAGE_ORDER[@]}"; do
        if [ "${index}" -ge "${first}" ]; then
            break
        fi
        index=$(( index + 1 ))
        [ "${STAGE_DERIVES_EVIDENCE[${name}]}" = "1" ] || continue
        if plan_contains "${name}"; then
            continue
        fi
        omitted+=("${name}")
        [ "${RECEIPT_READY}" -eq 1 ] || continue
        # An empty entry is itself an answer: receipt_entry returns
        # nothing unless the fingerprint it was recorded under is this
        # run's, so "no entry" means the inputs have moved since that
        # stage last ran -- or that it has never run here at all.
        recorded="$(receipt_entry "${name}")" || recorded=""
        [ -n "${recorded}" ] || continue
        current="$(outputs_digest "${name}")" || current=""
        if [ "${current}" != "${recorded}" ]; then
            stale+=("${name}")
        fi
    done
    if [ "${#omitted[@]}" -eq 0 ]; then
        return 0
    fi
    FRESH_PREFIX=0
    playthrough_log "this plan starts after" \
        "$(join_words "${omitted[@]}"), so no stage will be skipped as" \
        "fresh: the input fingerprint covers this pipeline's inputs and" \
        "not its intermediates, and freshness is only sound when every" \
        "earlier producing stage was either run or skipped in the same" \
        "plan.  Every stage in this plan will do its work."
    if [ "${#stale[@]}" -gt 0 ]; then
        playthrough_warn "the output of" \
            "$(join_words "${stale[@]}") no longer matches what the" \
            "receipt recorded for it, so it has been changed since that" \
            "stage last ran.  This plan does not re-run it, so what the" \
            "stages below produce will describe the intermediate as it" \
            "is NOW -- which may not be what the artifacts this plan" \
            "does not touch were built from.  The acceptance gate" \
            "compares the timeline against the film and the cue file" \
            "and will refuse an inconsistent set; run without" \
            "--from/--only to rebuild the whole chain."
    fi
    return 0
}

# stage_is_fresh NAME -- whether this run may skip that stage.  Every reason
# NOT to is checked before the expensive half: the output digest is computed
# only once the recorded input fingerprint has matched, so the film is hashed
# only when the answer is about to be "skip it" -- and hashing a film to
# avoid re-encoding it is a trade worth making in only that direction.
#
# THE INTERMEDIATE ARTIFACTS ARE DELIBERATELY NOT IN THE FINGERPRINT.  The
# encoder reads the timeline and the transition images, which are outputs of
# earlier stages rather than inputs to the pipeline; including them would
# change the fingerprint the moment stage 1 ran, so nothing after it could
# ever be found fresh.  FRESH_PREFIX is what makes leaving them out sound,
# subject to the caveat above.
stage_is_fresh() {
    local name="$1" recorded="" current=""
    if [ "${RECEIPT_READY}" -ne 1 ] || [ "${REBUILD}" -eq 1 ]; then
        return 1
    fi
    if [ "${FRESH_PREFIX}" -ne 1 ]; then
        return 1
    fi
    if [ -n "${ONLY_STAGE}" ]; then
        return 1
    fi
    recorded="$(receipt_entry "${name}")" || return 1
    [ -n "${recorded}" ] || return 1
    current="$(outputs_digest "${name}")" || return 1
    [ "${current}" = "${recorded}" ] || return 1
    return 0
}

# ---------------------------------------------------------------------
# THE TRUST GATE
# The whole plan is judged here, before the first stage, and the refusal is
# what the classification beside STAGE_DERIVES_EVIDENCE exists for.
assert_trusted_plan() {
    local name=""
    local -a deriving=()
    for name in "${PLAN[@]}"; do
        if [ "${STAGE_DERIVES_EVIDENCE[${name}]}" = "1" ]; then
            deriving+=("${name}")
        fi
    done
    if [ "${#deriving[@]}" -eq 0 ]; then
        note PIPELINE_TRUST_GATE "exempt"
        playthrough_log "this plan derives no artifact (${PLAN[*]})," \
            "so the trust state is reported rather than enforced:" \
            "reading a tree and publishing what is already in it are" \
            "what an operator needs most when a host is imperfect"
        return 0
    fi
    # Recomputed here rather than read from the environment, because a
    # caller can export a bypass after env.sh was sourced -- and because
    # a memoised trust verdict is a statement about the past.
    if playthrough_trust_refresh; then
        note PIPELINE_TRUST_GATE "trusted"
        return 0
    fi
    note PIPELINE_TRUST_GATE "refused"
    note PIPELINE_TRUST_STATE "${PLAYTHROUGH_TRUST_STATE:-unknown}"
    playthrough_trust_explain || true
    die "${EX_TRUST}" "refusing to run this plan: ${#deriving[@]} of" \
        "its ${#PLAN[@]} stage(s) DERIVE a delivered artifact" \
        "(${deriving[*]}) and the trust state is" \
        "'${PLAYTHROUGH_TRUST_STATE:-unknown}'.  Each reason is above." \
        "The refusal is here, before the first stage, rather than" \
        "inside the render: the stages ahead of it rewrite the" \
        "timeline, the transition frames and both transcripts, so a" \
        "later refusal would leave the artifact set already rewritten" \
        "under the very conditions being rejected.  Unset the" \
        "variable(s) named above and fix what each was hiding, or run" \
        "a plan that only reads and publishes -- '--only verify' and" \
        "'--only commit' are always permitted."
}

# ---------------------------------------------------------------------
# THE LOCK
# Held for the whole sequence and released however this run ends.
# ---------------------------------------------------------------------
# assert_lock_timeout -- validate the one number this file takes from the
#   environment, and leave it in PIPELINE_LOCK_TIMEOUT.
assert_lock_timeout() {
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
    PIPELINE_LOCK_TIMEOUT="${PLAYTHROUGH_INT}"
    # THE MUTATION LOCK'S TIMEOUT IS VALIDATED HERE TOO, and for the same
    # reason: playthrough_acquire_mutation_lock would refuse a malformed one,
    # but this file would then have to report that refusal as EX_BUSY --
    # telling an operator who mistyped a number that somebody else is holding
    # the checkout.
    playthrough_validate_int \
        "${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT:-\
${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT_DEFAULT}}" \
        "PLAYTHROUGH_MUTATION_LOCK_TIMEOUT" 0 86400 ||
        die "${EX_USAGE}" "set" \
            "PLAYTHROUGH_MUTATION_LOCK_TIMEOUT to a whole number of" \
            "seconds, or leave it unset for" \
            "${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT_DEFAULT}."
    return 0
}

# acquire_mutation_lock -- hold the CHECKOUT quiescent for this whole run.
acquire_mutation_lock() {
    playthrough_acquire_mutation_lock exclusive \
        "${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT:-\
${PLAYTHROUGH_MUTATION_LOCK_TIMEOUT_DEFAULT}}" ||
        die "${EX_BUSY}" "this sequencer could not take THIS" \
            "checkout's mutation lock exclusively, so it cannot" \
            "promise that nothing changed between the gate that" \
            "passes and the checkpoint that commits.  A session step," \
            "a producer, a standalone gate or a standalone checkpoint" \
            "is still running over the same working tree; wait for it" \
            "rather than rendering beside it."
    MUTATION_LOCK_HELD=1
}

acquire_pipeline_lock() {
    # The name is derived from the repository root, so it identifies THIS
    # working tree rather than this clone index.
    if ! PIPELINE_LOCK_NAME="$(playthrough_checkout_lock_name \
            "${PIPELINE_LOCK_BASENAME}")"; then
        die "${EX_LAYOUT}" "the lock name for this checkout could not" \
            "be derived, so two runs of this sequencer over one" \
            "working tree could not be kept apart."
    fi
    readonly PIPELINE_LOCK_NAME
    if ! playthrough_acquire_lock \
            "${PIPELINE_LOCK_NAME}" "${PIPELINE_LOCK_TIMEOUT}"; then
        # THE DIGEST IS THE SCOPE, and it is quoted instead of the path because
        # every message here goes through env.sh's redaction, which rewrites
        # the repository root to '.' to keep host paths out of the logs -- so
        # "over the checkout at ${REPO_ROOT}" would render as "over the
        # checkout at .", which names nothing.
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
    if [ "${MUTATION_LOCK_HELD}" -eq 1 ]; then
        MUTATION_LOCK_HELD=0
        # Released through its own helper, which releases ONLY when
        # this shell was the one that took it: a run that inherited
        # an ancestor's hold must leave that ancestor holding it.
        playthrough_release_mutation_lock || true
    fi
    # The scratch directory goes whatever way this run ended, including a
    # refusal from the closure gate, which is the one path that creates it and
    # then dies.
    case "${PIPELINE_SCRATCH}" in
        "${PLAYTHROUGH_RUNTIME_DIR}"/pipeline-*)
            rm -rf -- "${PIPELINE_SCRATCH}" 2>/dev/null || true
            PIPELINE_SCRATCH=""
            ;;
    esac
}


# ---------------------------------------------------------------------
# RUNNING A STAGE
# build_stage_command NAME
#   Fill STAGE_COMMAND with the argument list for one stage.  AN ARRAY,
#   never a string that a shell would have to take apart again: nothing
#   here is assembled out of text, so there is no quoting for a path to
#   slip through and nothing for an interpreter to re-read.
#
#   A .py stage is started through the interpreter env.sh resolved and
#   verified, with -B on top of the inherited PYTHONDONTWRITEBYTECODE=1 so
#   that neither instruction alone is load-bearing.  A .sh stage is its own
#   executable and is started by absolute path.  The fallback for a shell
#   stage whose executable bit has been lost is to start it through
#   ${BASH}, the absolute path of the interpreter already running this
#   file, and it is ANNOUNCED rather than silent: a stage whose mode has
#   gone is a tree somebody should repair.
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
    # THE THREE STAGES THAT TAKE AN ARGUMENT. Each argument is a constant
    # declared once at the head of this file -- never anything derived from an
    # operator's input -- so there is nothing here for a crafted argument to
    # reach.
    case "${name}" in
        "${COMMIT_STAGE}")
            STAGE_COMMAND+=( "${PIPELINE_CHECKPOINT_NAME}" )
            ;;
        "${PUBLISH_STAGE}")
            STAGE_COMMAND+=( "${PIPELINE_ATTESTATION_NAME}" )
            ;;
        "${GATE_STAGE}")
            STAGE_COMMAND+=( "${GATE_PHASE_ARGUMENT}"
                             "${GATE_PRE_COMMIT_PHASE}" )
            ;;
        "${ATTEST_STAGE}")
            # AND WHERE THE REPORT GOES: a scratch path outside the
            # checkout, because a gate that writes into the tree it
            # measures invalidates its own clean-tree finding.
            STAGE_COMMAND+=( "${GATE_PHASE_ARGUMENT}"
                             "${GATE_POST_COMMIT_PHASE}"
                             "${GATE_REPORT_ARGUMENT}"
                             "${PLAYTHROUGH_ACCEPTANCE_SCRATCH}" )
            ;;
    esac
}

# run_stage NAME NUMBER TOTAL
#   Announce it, run it, report what it did, and return its status.
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
    # USAGE FIRST: a malformed option is the caller's mistake and is
    # reported before this run touches a lock or a stage.
    assert_lock_timeout

    # The trap is registered before the lock is taken, so the lock is released
    # however this run ends -- including a refusal from a gate or a stage, and
    # an interrupt from the terminal.
    trap '_rp_on_exit' EXIT
    acquire_pipeline_lock
    acquire_mutation_lock

    # BOTH GATES RUN AFTER THE LOCK AND BEFORE THE FIRST STAGE.
    # THE POSITION IS EXACT AND IT WAS ARRIVED AT BY GETTING IT WRONG.
    assert_dependency_closure
    assert_trusted_plan

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
    # THE TRUST STATE HAS ALREADY BEEN ENFORCED BY THE TIME THIS PRINTS,
    # by assert_trusted_plan above.  Logging it here and leaving the
    # refusal to each stage would let three producing stages rewrite the
    # artifact set under exactly the relaxed conditions the control exists
    # to reject before any of them met it.
    playthrough_log "interpreter" \
        "${PLAYTHROUGH_PYTHON}; trust state" \
        "${PLAYTHROUGH_TRUST_STATE:-<unknown>}"

    # THE THREE QUESTIONS THAT ARE ALREADY ANSWERABLE, in the order that costs
    # least to be refused by. The lifecycle probe reads the history; the
    # capacity model measures the disk; the receipt fingerprints the inputs.
    resolve_measurement_tools || true
    assert_lifecycle_eligible
    assert_capacity "plan"
    open_receipt || true
    # AFTER the receipt, because what it decides is decided FROM the
    # receipt: a plan that jumps over a producing stage may not skip
    # anything, because the reasoning that makes skipping sound does not
    # hold across a stage that is absent rather than skipped.
    resolve_omitted_producer_freshness

    for index in "${!PLAN[@]}"; do
        name="${PLAN[${index}]}"
        number=$(( index + 1 ))
        status=0
        if stage_is_fresh "${name}"; then
            FRESH+=("${name}")
            note "PIPELINE_STAGE_${name^^}" "fresh"
            playthrough_log "stage ${number}/${total} ${name}:" \
                "ALREADY DONE -- this run's inputs are the ones it was" \
                "produced from and its output is unchanged, so it is" \
                "skipped.  Pass --rebuild to run it anyway."
            continue
        fi
        # THE SECOND CAPACITY CHECK, taken here rather than in the preflight
        # because the producing stages have spent the disk in between: the film
        # that did not exist when this run started is on it now, and the
        # checkpoint is about to write an object for every artifact.
        if [ "${name}" = "${COMMIT_STAGE}" ] &&
           ! capacity_ok "checkpoint"; then
            status="${EX_CAPACITY}"
            FAILED_STAGE="${name}"
            report_unattempted "${index}"
            break
        fi
        run_stage "${name}" "${number}" "${total}" || status=$?
        if [ "${status}" -ne 0 ]; then
            FAILED_STAGE="${name}"
            report_unattempted "${index}"
            break
        fi
        # A stage has now done work, so nothing after it can be called
        # already done: its inputs moved when this one wrote its output.
        FRESH_PREFIX=0
        record_receipt "${name}"
    done

    printf '\n' >&2
    # Emitted after the loop, because which stages were already done is
    # something this run learns as it goes rather than something it
    # decides up front.
    note PIPELINE_FRESH "$(join_words "${FRESH[@]}")"
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
    if [ "${#FRESH[@]}" -ne 0 ]; then
        playthrough_log "every stage in the plan is now done" \
            "(${PLAN[*]}) in" \
            "$(format_elapsed "$(( SECONDS - started_at ))")," \
            "of which ${#FRESH[@]} were already done and were" \
            "skipped: ${FRESH[*]}"
    else
        playthrough_log "every stage in the plan passed" \
            "(${PLAN[*]}) in" \
            "$(format_elapsed "$(( SECONDS - started_at ))")"
    fi
    return "${EX_OK}"
}

# main's status is taken from a `||` and then exited with, rather than
# being left to errexit: the ERR trap would otherwise report a line
# number for a stage failure that has already been explained in full,
# which reads as a fault in this file when it is not one.
_rp_status=0
main "$@" || _rp_status=$?
exit "${_rp_status}"
