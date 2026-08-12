#!/usr/bin/env bash
# shellcheck shell=bash
#
# playthrough/tooling/verify_artifacts.sh -- THE ACCEPTANCE GATE for the
# Cataclysm-DDA playthrough capture and cinematography subsystem.
#
#     cd <repository root>
#     playthrough/tooling/verify_artifacts.sh
#     playthrough/tooling/verify_artifacts.sh --base <commit>
#     playthrough/tooling/verify_artifacts.sh --phase pre-commit
#     playthrough/tooling/verify_artifacts.sh --phase post-commit
#
# Every acceptance criterion this feature has is a COMMAND or a
# CHECKABLE PROPERTY rather than an adjective, and this file is where
# those commands live.  It reads the committed artifacts -- the frames,
# the record, the timeline, the film, the caption track, the transcripts
# and the engine-written userdir -- and reports, one property at a time,
# whether each is what it is claimed to be.
#
# IT MODIFIES NOTHING INSIDE THE WORKING TREE.  Its only writes are into
# a private scratch directory under the mode-0700 runtime root env.sh
# created, and that directory is removed on exit.  Nothing it does can
# change the evidence it is measuring, which is the whole point: a gate
# that edits what it inspects proves nothing.
#
# ---------------------------------------------------------------------
# WHY IT EXISTS: THREE FAILURE MODES THAT ARE OTHERWISE SILENT
#
# Most of the ways this pipeline can go wrong announce themselves -- a
# missing tool, a crashed encode, an unparsable JSON row.  Three do not,
# and those three are the reason this file exists.  Each is turned into
# a loud, named failure below.
#
#   1. A SAVE THAT IS COMMITTED IN APPEARANCE ONLY.  Cataclysm-DDA
#      writes per-character save files whose names begin with '#'
#      (src/game_io.cpp:601-641), and .gitignore carries `\#*`
#      (.gitignore:131) plus an unanchored `*.log` (.gitignore:31) and
#      `debug.log` (.gitignore:79).  Without the terminal
#      `!/playthrough/**` negation, `git add` SKIPS the save and EXITS
#      SUCCESSFULLY.  Every count downstream still tallies; the save is
#      simply not there.  Answered by check group 7, which asserts both
#      `git ls-files` membership and `git check-ignore` non-membership
#      for every artifact class.
#
#   2. A FILM THAT IS ENTIRELY BLACK.  With SDL_VIDEODRIVER=dummy the
#      game runs, the captures succeed, the encode succeeds, the frame
#      count equals the row count, and the only symptom is that nothing
#      is visible.  Answered by check group 6, the luminance gate:
#      grayscale mean > 0 AND standard deviation > 0, on sampled
#      captures and on a frame extracted from the finished film.  Both
#      terms are load-bearing -- the mean catches a black frame, the
#      deviation additionally catches a uniform solid-colour one that a
#      mean-only test would pass.
#
#   3. CAPTIONS THAT DRIFT OUT OF SYNC.  A transition inserts real
#      seconds into video time.  A caption generator that walks frame
#      durations without charging those seconds to the cue cursor emits
#      cues that are correct at the start and increasingly wrong by the
#      end.  Answered by check groups 3 and 5, which assert the
#      invariant sum(durations) + sum(transitions) == total == final cue
#      end AND compare every cue window against the timeline's own.
#
# ---------------------------------------------------------------------
# THE REPORTING MODEL: RUN EVERY CHECK, THEN EXIT NON-ZERO
#
# This file runs under `set -euo pipefail`, under which a bare failing
# command aborts the script.  For a gate that is precisely the wrong
# behaviour: the operator would be told about the first broken property
# and left ignorant of the other sixty.  So no check is expressed as a
# bare command.  Every one records a verdict through record_pass,
# record_fail or record_info, the counters accumulate, and the exit
# status is decided ONCE at the end.
#
# There is no SKIP verdict, deliberately.  A gate that quietly skips
# half its checks is worse than no gate, so a tool this file needs and
# cannot find is a FAILURE of the gate rather than an excuse to stop
# measuring.  Every check below has a defined verdict on every host.
#
# ---------------------------------------------------------------------
# THE TWO PHASES, AND WHY A SINGLE-PHASE GATE COULD NEVER PASS
#
# FIFTEEN of the properties below are properties OF THE COMMIT: the
# save is tracked, every artifact class is tracked, the tracked capture
# count equals the on-disk one, nothing under playthrough/ is left
# uncommitted, the checkpoints are ordered and are about the survivor in
# the tree, the committed .gitignore still carries the negation, the
# change surface since the base commit is only this feature.  NONE OF
# THEM CAN HOLD BEFORE THE COMMIT THAT MAKES THEM TRUE.  They are
# enumerated one by one beside GROUP_CHECKS_ALL below.
#
# Every other property -- the record, the timeline, the container, the
# caption track, the luminance, the absence of cheating, the artwork,
# the lint -- is a property OF THE ARTIFACTS, and holds the instant the
# render finishes, with nothing committed at all.
#
# Run as one undivided gate ahead of a commit, those fifteen fail on
# any tree that is not already fully committed, and a sequencer that
# puts the gate before the checkpoint can therefore never reach the
# checkpoint.  That is not a hypothetical: it was measured, on a genuine
# post-session tree, as nine failures out of a hundred and eight, every
# one of them a tracking, history or clean-tree property.
#
# So the gate has PHASES, and the workflow is
#
#     --phase pre-commit    the artifacts are what they claim to be
#            commit         commit_artifacts.sh takes the checkpoint
#     --phase post-commit   ...and the history now says so
#
#   pre-commit    every property of the ARTIFACTS.  The fifteen
#                 commit-shaped ones are deferred, and the deferral is
#                 REPORTED as an informational note naming them, so a
#                 shorter report explains its own length instead of
#                 reading exactly as green as a complete one.
#   post-commit   THE HISTORY, AND WHAT IT TAKES TO MEASURE IT: the
#                 measuring environment, the version-control group, the
#                 change surface, and the inventory of the report.
#                 Nothing else.
#   all           EVERYTHING, and THE DEFAULT, so an operator auditing a
#                 committed tree runs this file with no arguments and
#                 gets the whole gate.
#
# WHY post-commit IS NOT "EVERYTHING" ANY MORE, which it used to be.
#
# The two phases were designed as complementary halves and one of them
# was not a half: `post-commit` ran every check `pre-commit` had just
# run, minutes earlier, over artifacts NOTHING had touched in between --
# the commit changes the history, not the bytes on disk.  So a default
# sequencer run performed the eighty-nine artifact checks twice: two
# whole-set digest sweeps, two decodes of each film, two lint runs, two
# runs of the timeline suite.  At the session lengths this pipeline is
# built for that is the expensive half of the gate, paid twice, for an
# answer that cannot have changed.
#
# `post-commit` is therefore what its name says: the properties that
# became answerable BECAUSE of the commit, plus group 1, which is what
# establishes that this run can measure at all.  `all` remains the
# explicit full audit -- it is the right thing to run when the question
# is "is this committed tree what it claims to be" rather than "did the
# checkpoint publish what the gate had just passed", and it is what an
# operator gets by default.
#
# The declared check count is per phase (see EXPECTED_CHECKS below), so
# no phase can quietly return a short report.
#
# EVERY VERDICT PRINTS ITS EVIDENCE.  A FAIL prints the observed value
# next to the expected one; a PASS prints the observed value too, so the
# report is a record of what was measured and not merely an assertion
# that somebody once measured it.
#
# ---------------------------------------------------------------------
# WHAT THE CHECK GROUPS COVER
#
#   1  the measuring environment  the tools, the interpreter, the trust
#                                 state, and that every artifact this
#                                 gate reads is present and readable
#   2  one frame per keystroke    frames == rows, contiguous indices,
#                                 the six-key record schema, the
#                                 acknowledgment ledger and the
#                                 hash-chained evidence anchor
#   3  the timeline               the 0.25 s floor, the 10 s ceiling,
#                                 the transition flag, the materialised
#                                 transition groups, the invariant
#   4  the container              h264 1920x1080, duration, no audio
#   5  the caption track          mov_text/eng, cue structure, cue
#                                 windows, not burned in, the
#                                 transcripts, the meta-language gate
#   6  the luminance gate         mean > 0 and std > 0
#   7  version control            the save is really tracked, nothing
#                                 is silently ignored, nothing is left
#                                 uncommitted, the commit order, the
#                                 committed ignore rules, and the
#                                 lifecycle checkpoints
#   8  no cheating                no debug keybinding, no debug-mode
#                                 activation in the engine's own log
#   9  the binary and hygiene     +tiles, scoped flake8, the timeline
#                                 test suite, the change surface
#
# ---------------------------------------------------------------------
# TWO HOST FACTS THAT SHAPE THE CODE
#
# IMAGEMAGICK IS CALLED THROUGH ITS CLASSIC ENTRY POINTS -- `convert`,
# `identify`, `compare`.  The unified `magick` entry point exists only
# on the version 7 branch, so code written against it fails outright on
# a version 6 host; the classic names work on both.  env.sh additionally
# documents that ImageMagick dispatches on argv[0], which is why the
# resolved PATH entry is invoked rather than its symlink target.
#
# THE SHELL CANNOT COMPARE FLOATING POINT.  `[ "0.27" -gt 0 ]` is not a
# working test -- it is an integer comparison against a string, and it
# fails at the syntax level.  Every threshold in this file goes through
# awk, with the values passed in via -v as data rather than pasted into
# the program text.
#
# ---------------------------------------------------------------------
# EXIT STATUS
#
#   0  every check passed
#   1  at least one check failed; the count is on the last line
#   2  usage error -- an unknown option or a malformed value
#   3  layout error -- this file cannot locate itself, or env.sh is
#      missing or refused to load
#   4  busy -- another stage is mutating this checkout, so there is
#      no fixed tree to measure.  Distinct from 3 because nothing
#      is wrong: the same command succeeds once that stage finishes
#
# Requires bash: BASH_SOURCE, arrays and `local` are all used.
# ---------------------------------------------------------------------

set -euo pipefail
set -o errtrace

# The ERR trap names the line, because a gate that dies without saying
# where is a gate nobody can repair.  It fires only on an unhandled
# failure: every deliberate check runs inside an `if` or an `||`, both
# of which errexit exempts.
#
# SC2317 is disabled for exactly this function and no other: ShellCheck
# cannot see a call site because the only one is the `trap` below, and
# leaving the diagnostic in place would make the DEFAULT invocation of
# `shellcheck verify_artifacts.sh` exit non-zero -- which is how a real
# finding in this file gets lost in the noise of an expected one.
# shellcheck disable=SC2317
_va_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "verify_artifacts.sh failed at line ${2} (exit ${1})" >&2
}
trap '_va_on_error "$?" "${LINENO}"' ERR

readonly EX_OK=0
readonly EX_FAILED=1
readonly EX_USAGE=2
readonly EX_LAYOUT=3
readonly EX_BUSY=4

# ---------------------------------------------------------------------
# LOCATING THIS FILE, AND THE ENVIRONMENT CONTRACT
#
# The pattern is the repository's own -- build-scripts/clang-tidy-run.sh
# resolves its directory from BASH_SOURCE the same way -- and it is what
# keeps the gate correct no matter which directory it is invoked from.
# env.sh is then the SINGLE definition of every artifact path, the
# verified interpreter, the tool resolution and PYTHONDONTWRITEBYTECODE;
# none of it is restated here.
# ---------------------------------------------------------------------
# The one place no resolved tool can be used, because this is what finds
# the file that resolves them: bash's own parameter expansion does the
# job that `dirname` would, so the bootstrap invokes NO external command
# at all rather than one it has not verified.
_va_script_dir="$(
    cd "${BASH_SOURCE[0]%/*}" >/dev/null 2>&1 && pwd
)"
if [ -z "${_va_script_dir}" ]; then
    printf '%s\n' "verify_artifacts.sh: FATAL: cannot resolve my own \
directory, so I cannot find the environment contract" >&2
    exit "${EX_LAYOUT}"
fi

# WHAT THE CALLER'S ENVIRONMENT SAID, READ BEFORE env.sh OVERWRITES IT.
# env.sh exports SDL_VIDEODRIVER=x11 unconditionally and deliberately, so
# after sourcing it there is nothing left to observe: a check that read
# the value afterwards would be reporting what this file had just set,
# one line earlier, and would pass whatever the caller intended.  The
# inherited value is captured here so the report can say what it actually
# was.
_VA_INHERITED_VIDEODRIVER="${SDL_VIDEODRIVER:-}"
readonly _VA_INHERITED_VIDEODRIVER

_va_env_file="${_va_script_dir}/env.sh"
if [ ! -f "${_va_env_file}" ]; then
    printf '%s\n' "verify_artifacts.sh: FATAL: missing \
${_va_env_file}; the artifact layout, the tool verification and the \
interpreter live there and are never redefined here" >&2
    exit "${EX_LAYOUT}"
fi

# The `source=` directive lets `shellcheck -x` follow env.sh and check
# this file against it; SC1091 silences the run without -x, where the
# file cannot be followed at all.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_va_env_file}"; then
    printf '%s\n' "verify_artifacts.sh: FATAL: ${_va_env_file} refused \
to load; fix the environment contract before measuring anything \
against it" >&2
    exit "${EX_LAYOUT}"
fi
unset _va_script_dir _va_env_file

# Every path this gate reads is repository-relative from here, which is
# also the working directory the engine itself requires.
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# WHAT THE ARTIFACTS ARE REQUIRED TO BE
#
# These are the expected values, named once.  Where a value also exists
# as a constant inside a sibling module it is CROSS-CHECKED against that
# module rather than merely restated -- check group 3 imports
# timeline.py, make_transitions.py and render_movie.py and fails if the
# producer's own constants have drifted from the numbers below.  That
# way a future edit to a producer cannot quietly move the goalposts this
# gate measures against.
# ---------------------------------------------------------------------
readonly VIDEO_CODEC_EXPECTED="h264"
readonly SUBTITLE_CODEC_EXPECTED="mov_text"
readonly SUBTITLE_LANGUAGE_EXPECTED="eng"

# The floor and the ceiling, in seconds of on-screen time per capture,
# and the length of one inserted transition unit.
readonly DURATION_FLOOR="0.25"
readonly DURATION_CEIL="10.0"
readonly TRANSITION_SECONDS="1.0"

# A transition is materialised as still images rather than spliced in as
# a second video segment, which is what keeps the film to a single
# encoder pass.  Twelve images at 12 fps make the 1.0 s unit.
readonly TRANSITION_FRAMES_PER_GROUP="12"

# How far the encoded container may sit from the timeline's declared
# total.  A variable-frame-rate encode does not land on the arithmetic
# total exactly; a SHORTFALL of a whole frame's worth or more is the
# signature of a concat list whose final `file` entry was not repeated,
# which was measured once as a 10.52 s container against an 11.75 s
# subtitle stream.  0.12 s is render_movie.py's own tolerance and is
# asserted against it in check group 3.
readonly CONTAINER_TOLERANCE="0.12"

# Cue and duration arithmetic is compared at the timeline's own rounding
# of three decimal places, so 0.0005 s of float representation noise is
# not reported as a discrepancy.
readonly ARITHMETIC_EPSILON="0.0005"

# The offset, in seconds, at which a frame is extracted from each film
# for the luminance and burned-in-caption checks.  One second is past
# the opening captures and inside ordinary play.
readonly EXTRACT_OFFSET="1"

# AND THE FRACTIONS OF THE FILM SAMPLED ALONGSIDE IT.  One fixed offset
# near the start was measured to be a real blind spot: a film truncated to
# a third of its length still decoded perfectly at 1 s, so both the
# non-blank reading and the burned-in comparison passed while two thirds
# of the pictures were gone.  These fractions of the timeline total put a
# reading in the middle and one near the end as well.
#
# ANY OFFSET THAT LANDS INSIDE A TRANSITION IS MOVED PAST IT.  A fade or a
# "…time passes…" card is legitimately near black, so a reading taken
# there says nothing about whether the session rendered; the windows come
# from the timeline itself (group 3 publishes them) rather than from an
# assumption about where they are.
readonly EXTRACT_FRACTIONS="0.10 0.50 0.95"

# The calibration reading from a real rendered capture, quoted so the
# report carries the provenance of the threshold.  IT IS NOT A BOUND:
# the assertion is strictly `> 0` on both terms, because how bright a
# frame is depends on the tileset and on what the survivor was looking
# at, and a gate that demanded a magnitude would fail honest captures.
readonly LUMINANCE_REFERENCE="mean=0.270018 std=0.198145 \
(one real frame, quoted as provenance only)"

# HOW MANY CAPTURES THE LUMINANCE GATE DECODES: A DELIBERATE SPREAD.
#
# THE PIXELS OF EVERY FRAME ARE STILL ACCOUNTED FOR, by two witnesses
# that do not need this gate to decode a raster to speak:
#
#   * THE CONTEMPORANEOUS READING.  capture.sh measures the grayscale
#     mean and standard deviation of each frame at the moment it takes
#     it, refuses to publish a blank one, and commits the reading in
#     playthrough/build/observations.jsonl beside that frame's sha256.
#     check_recorded_luminance below reads EVERY one of those rows, on
#     every run, at every session length -- so "no frame was blank when
#     it was captured" is asserted over the whole population.
#   * THE DIGEST SWEEP.  Group 3 holds every committed capture to the
#     digest taken when it was captured, so a frame SUBSTITUTED after the
#     fact -- blanked, re-encoded, swapped -- fails there whatever its
#     index, again over the whole population.
#
# What a CURRENT-PIXEL decode adds on top of those two is one narrow
# case: a frame that was already blank when it was captured AND whose
# digest AND whose recorded reading were all three re-declared to match
# it.  That case is worth sampling for, and it is not worth decoding an
# unbounded number of full-resolution rasters for on every run: the
# session length is deliberately unbounded, one decode is about 0.14 s in
# chunks of 16, and an exhaustive default therefore turns into hours of
# I/O on a long session -- for a reading two whole-population witnesses
# have already answered.  Measured here: 326 frames decoded in 45 s of
# an 89 s gate.
#
# So the default is a SPREAD, always including the first and the last
# capture, and `--samples all` is the exhaustive audit -- the reading to
# take when the question is precisely "were the pixels re-declared", and
# the one an operator auditing a stranger's tree should take at least
# once.  The verdict always says how many of how many it read, so a
# sampled reading can never be mistaken for a complete one.
#
# The reading itself stays as cheap as it was made: one ImageMagick
# invocation per CHUNK of images, each reporting geometry and both
# statistics for every image in the chunk, and ONE awk program over the
# collected readings instead of one process per frame.  Measured on this
# host: 0.235 s per frame one at a time against 0.138 s in chunks of 16,
# and the separate `identify` call for geometry disappears entirely
# because %w and %h come back in the same line.
readonly LUMINANCE_SAMPLES_DEFAULT="64"
readonly LUMINANCE_SAMPLES_ALL="all"

# How many images one ImageMagick invocation measures.  ImageMagick holds
# a chunk in memory at once, so this trades memory for process starts: 16
# 1920x1080 rasters is a couple of hundred megabytes at most, and 21
# invocations instead of 326 is where the saving comes from.
readonly LUMINANCE_CHUNK="16"

# ---------------------------------------------------------------------
# EVERY MEASURING CHILD IS TIME-BOUNDED, AND THE BOUND IS DERIVED
#
# A gate holds the pipeline's lock while it runs.  A wedged ffmpeg, a
# hung ffprobe against a truncated container, an ImageMagick that will
# not return on a corrupt raster, a linter waiting on a filesystem: any
# one of them stops the gate for ever with no verdict and no diagnosis,
# which is the one outcome worse than a failure.  So every child that
# MEASURES something runs under `timeout` -- every ffprobe, ffmpeg,
# convert, identify and compare call, every Python checker, the linter,
# the timeline suite, and every interpreter probe -- and every bound is
# TERM followed by KILL over the child's PROCESS GROUP: GNU timeout puts
# the command in a group of its own and signals the group, so a tool that
# spawns a helper cannot outlive the ceiling by hiding behind it, and
# --kill-after guarantees the advertised ceiling against a child that
# ignores TERM.
#
# WHAT IS DELIBERATELY NOT WRAPPED, STATED PLAINLY.  The git plumbing
# this gate reads history with, and the shell's own text utilities (wc,
# sed, awk, grep, sort, sha256sum), are not individually bounded.  Their
# cost is a query against the local object store or one pass over a
# scratch file, with no size term this file could derive a ceiling from,
# and wrapping several dozen of them would buy nothing the class above
# does not already cover -- the audit spends its time in media decode and
# in whole-population readers, and those are bounded.  The residual is
# real and is recorded here rather than papered over: a wedged object
# store can still stall this gate, and no ceiling inside it would help,
# because the sequencer that owns the lock is the only thing that can
# time out a whole stage.
#
# THE CEILINGS ARE DERIVED FROM THE WORK, NOT GUESSED.  A session length
# is deliberately unbounded, so a fixed number is either too small for a
# long film -- killing a healthy decode and reporting it as wedged -- or
# so large it is no bound at all.  A film's ceiling therefore comes from
# its own byte count at a deliberately pessimistic floor throughput, and
# a checker's from the size of the population it reads.  Each verdict
# that expires says which ceiling it hit and what it was derived from.
readonly BOUND_KILL_GRACE="10"

# A metadata read: one ffprobe, one `identify`, one `convert … info:`.
# Bounded by the container header or a single raster, so it does not
# scale with the session at all.
readonly BOUND_PROBE_SECONDS="120"

# One ImageMagick invocation over LUMINANCE_CHUNK rasters.
readonly BOUND_CHUNK_SECONDS="600"

# A whole-film pass -- the decode, the frame count, a frame extraction.
# base + bytes / throughput floor, where the floor is deliberately far
# below what any real host achieves (this one decodes about 90 MB/s), so
# an expiry means wedged rather than slow.
readonly BOUND_FILM_BASE_SECONDS="300"
readonly BOUND_FILM_BYTES_PER_SECOND="1048576"

# A Python checker over the whole artifact set.  The digest sweep is the
# part that scales, at roughly the disk's read rate; the divisor is per
# capture and, again, pessimistic.
readonly BOUND_CHECKER_BASE_SECONDS="600"
readonly BOUND_CHECKER_CAPTURES_PER_SECOND="20"

# The linter over playthrough/, and the timeline's own suite.  Neither
# scales with the session: both read the tooling directory.
readonly BOUND_LINT_SECONDS="1800"
readonly BOUND_SUITE_SECONDS="3600"

# No ceiling this file derives may exceed a day.  A bound that large is
# already a diagnosis rather than a limit, and it keeps arithmetic on a
# byte count from producing something absurd.
readonly BOUND_MAX_SECONDS="86400"

# HOW MANY OFFENDING ITEMS ONE VERDICT NAMES.
#
# A verdict is reached on the FACT of a failure, and the first example
# establishes it: what the rest add is length -- in the report, and in the
# shell array the report was assembled from.  The failure this gate exists
# for is a WHOLE capture set coming back blank, so "one entry per capture"
# is the realistic shape of an unbounded diagnostic here.  The count is
# always reported in full; this bounds how many are named.
readonly DIAGNOSTIC_LIMIT="8"

# `timeout` reports this when it fires, which is how an expiry is told
# apart from the tool's own failure; 128+SIGKILL is what it reports when
# the grace period elapsed too.
readonly BOUND_EXPIRED="124"
readonly BOUND_KILLED="137"

# ---------------------------------------------------------------------
# THE SCRATCH GENERATION, AND WHY STALE ONES ARE SWEPT
#
# This gate works in a private directory under the mode-0700 runtime root
# and removes it on every exit path.  "Every exit path" is not every END:
# SIGKILL, an OOM kill and a pod eviction all leave the directory behind,
# and because the name is unique per run, the leftovers ACCUMULATE -- one
# generation per killed audit, each holding the extracted frames and
# per-film logs of a run nobody can read any more.  Measured shapes are
# tens of megabytes each.
#
# So a run sweeps before it works.  A generation is removed only when its
# owner is provably gone -- the pid it recorded is not a live process --
# or, for a generation from a version that recorded no owner, when it is
# older than the bound below.  A generation whose owner is alive is never
# touched, which is what keeps two concurrent audits safe.
readonly SCRATCH_PREFIX="verify."
readonly SCRATCH_OWNER_FILE="owner.pid"
readonly SCRATCH_STALE_SECONDS="21600"

# The engine's own debug actions.  All three are declared in
# data/raw/keybindings.json WITHOUT a `bindings` array -- debug_mode at
# L3398-3403, debug ("Debug menu") at L3404-3409 and debug_hour_timer at
# L3466-3471 -- so they are unbound by default and unreachable by any
# keystroke unless somebody deliberately binds them.  The user
# keybindings file is a COMMITTED artifact, which is what turns "no
# cheating" from a claim into a property a stranger can check.
readonly DEBUG_ACTION_PATTERN='"(debug|debug_mode|debug_hour_timer)"'

# THE SAME QUESTION ASKED OF THE RECORD ITSELF.
#
# The keybindings file and the engine log prove nothing was BOUND and
# nothing was ACTIVATED, which leaves the most direct evidence there is
# unexamined: the record of what was actually pressed, and the transcript
# written from it.  A session that opened the debug menu and spawned a
# rifle would say so in its own action column -- the requirement is that
# no decision was made that way at all, so the words are worth reading.
#
# THE LEXICON IS DELIBERATELY NARROW.  Every term is either an engine
# action id (debug, debug_mode, debug_hour_timer, the wish* family behind
# the debug menu's spawn screens) or an unambiguous name for a cheat
# (god mode, noclip, teleport, revealing the map, editing stats).  Bare
# "wish" is excluded on purpose: it is ordinary English, and the honest
# transcript of this session already contains it ("That is the whole
# wish."), so including it would manufacture a finding out of prose.
# Measured across all five committed record files at this checkpoint:
# zero hits.
#
# WRITTEN IN DOUBLE QUOTES, and that is not cosmetic.  A backslash before
# a newline continues the line only inside double quotes; inside single
# quotes it is a literal backslash followed by a literal newline, which
# grep reads as several patterns of which one ends in a trailing
# backslash -- an invalid expression that grep rejects, leaving the
# check to find nothing and report success.  That is precisely the
# vacuous verdict this gate exists to prevent, and it was caught here by
# running the mutation the check was written for.
readonly CHEAT_VOCABULARY_PATTERN="debug|god[ _-]?mode|no[ _-]?clip|teleport|wish(item|monster|mutate|skill|proficiency)|spawn|cheat|reveal (the |whole )*map|map reveal|edit (my |the )*(stat|skill|proficienc)|set (my |the )*(stat|skill|proficienc)"

# The engine writes its log beside the configuration it was launched
# with.  Both candidate locations are inspected, because which one is
# used has changed between builds and a gate that looked in only one
# would report "no debug activation" without having read anything.  An
# ARRAY, so no expansion has to be left unquoted to split it.
readonly -a DEBUG_LOG_RELATIVE_PATHS=("config/debug.log" "debug.log")

# ---------------------------------------------------------------------
# THE REQUIRED ARTWORK
#
# The tileset is a REQUIREMENT and not a preference: the feature is
# specified to install the CDDA-Tilesets pack and to configure MSXotto+.
# It needs its own assertions because none of the other groups can see
# it.  `+tiles` in the binary's banner says the SDL tiles PATH was
# compiled in, not which artwork was drawn through it; every count, every
# duration, every cue and even the luminance gate are satisfied exactly
# as well by an ASCII-rendered session -- which is exactly why no code
# path in this pipeline can select other artwork any more: the diagnostic
# ASCIITiles fallback and the trust bypass that reached it are both gone,
# so there is one contract and these assertions measure whether it held.
# Four are made here, from four independent directions -- the installed
# pack, the committed option values, the engine's own log, and the pixels
# of the captures themselves.
#
# The engine's log line is the strongest of the four, because it is
# CAPTURE-TIME evidence written by the game rather than a statement about
# the host doing the auditing: cata_tiles::do_tile_loading_report logs
# "Loaded tileset: <id>" (src/cata_tiles.cpp:5183) once the artwork has
# actually been loaded, and playthrough/userdir/config/debug.log is a
# committed artifact.
readonly TILESET_LOADED_PREFIX="Loaded tileset:"

# THE PIXEL ASSERTION, AND WHERE ITS NUMBER COMES FROM.  An options file
# can be edited after the fact and an installed pack can be swapped, so
# the last assertion is made against the captures: how many DISTINCT
# COLOURS a rendered frame holds separates sprite artwork from glyphs
# decisively.  Measured on this checkout: the entire ASCII tileset holds
# 38 unique colours (gfx/ASCIITileset/ASCIITiles.png) and its fallback
# glyph sheet 18, while MSXotto+'s sheet holds 170,808
# (gfx/MShockXotto+/tiles.png).  A text render is bounded by the game's
# 16-colour palette over 16 backgrounds -- 256 combinations at the
# absolute most, and far fewer in practice because the shipped font is a
# bitmap face with no anti-aliasing.  The committed captures measure up
# to 2352 on a map frame.  512 therefore sits an order of magnitude above
# anything ASCII can produce and a factor of four below what this session
# actually produced.
#
# IT IS A MAXIMUM OVER SAMPLED IN-GAME CAPTURES, NOT A PER-FRAME FLOOR.
# A legitimate frame can be almost colourless -- a full-screen menu over
# the map, a night scene, the closing dialogue -- so demanding depth of
# every frame would fail an honest session.  One frame that could only
# have been drawn from sprite artwork is what this proves.
readonly TILE_COLOUR_FLOOR="512"
readonly TILE_COLOUR_REFERENCE="ASCII artwork holds 38 unique colours \
in total (gfx/ASCIITileset/ASCIITiles.png) against 170808 in \
gfx/MShockXotto+/tiles.png"

# How many in-game captures the colour-depth reading samples.  One
# reading costs about half a second, and the assertion is a maximum, so a
# spread of eight is both sufficient and cheap.
readonly TILE_COLOUR_SAMPLES="8"

# The complete set of paths outside playthrough/ that this feature is
# allowed to have touched.  Anything else in the change surface is a
# finding: the engine, the content, the build system and CI are all
# consumed read-only.
readonly ALLOWED_FOREIGN_PATHS=".gitignore .gitattributes"

# ---------------------------------------------------------------------
# THE TWO REPOSITORY-WIDE RULES THIS FEATURE DEPENDS ON, AND WHY THEIR
# *COMMITTED* CONTENT IS WHAT GETS CHECKED
#
# `git check-ignore` answers for the WORKING TREE, which is the right
# question for "will the next `git add` skip the save".  It is the wrong
# question for "will a fresh clone of this history still carry the
# save", and that second question is the one a reader of the repository
# actually asks.  A history whose terminal negation was never committed
# passes every working-tree check and re-ignores the save data the
# moment somebody clones it -- measured, and reported as a finding.
#
# So the committed content is read out of HEAD directly.  The negation
# must be the LAST effective rule in the committed file, because git
# applies the last matching pattern and the file says so itself; and the
# six attribute rows must be present, because `* text=auto` alone would
# leave the film, the save and the archives to content detection.
readonly IGNORE_NEGATION="!/playthrough/**"
readonly -a REQUIRED_ATTRIBUTES=(
    "*.mp4 binary"
    "*.zzip binary"
    "*.sav binary"
    "*.gsav binary"
    "*.srt text"
    "*.jsonl text"
)

# The trailer commit_artifacts.sh writes, and the two checkpoint names
# whose ordering the lifecycle is made of.  Spelled here as the strings
# they are, because this gate READS a history somebody else wrote and
# must not import the committer's code to do it.
readonly CHECKPOINT_TRAILER_KEY="Playthrough-Checkpoint"

# The trailer that carries the evidence anchor's chain head, for the same
# reason and read the same way.  A commit object's name is a hash of its
# own content, so a head published here cannot be edited without
# rewriting history -- which is the whole of what makes the anchor an
# INDEPENDENT domain rather than one more mutable file beside the
# evidence.
readonly ANCHOR_TRAILER_KEY="Playthrough-Evidence-Anchor"
readonly CHECKPOINT_CREATION_NAME="creation"
readonly CHECKPOINT_FINAL_NAME="final"

# The third checkpoint the anchor is asked about.  `creation` and `final`
# are the two the plan mandates (R1); `media` is the one that first
# publishes the rendered film and its transcripts, so it is the earliest
# commit at which the anchor has a complete evidence tree to seal.  Named
# here because the anchor gate must be able to ASK EACH REQUIRED
# CHECKPOINT for a trailer of its own rather than accept the newest one
# anywhere in the history.
readonly CHECKPOINT_MEDIA_NAME="media"

# The engine's record of which world and survivor were last loaded, read
# out of a commit rather than off disk.  A fixed program with no
# interpolation, fed on stdin, so nothing a path or a name contains can
# reach the interpreter -- the same rule the sibling stages follow.
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

# The unit separator, used between the fields of one verdict line.  A
# NON-whitespace delimiter is required: bash's `read` collapses runs of
# a whitespace IFS character and drops leading and trailing ones, so a
# tab-separated protocol would silently lose an empty field.
# The WORLD_END the world was played under, read out of a
# worldoptions.json on stdin.  The file is a LIST of option records
# (src/worldfactory.cpp writes one object per override), so the value is
# found by name rather than by key.  Exit 1 when the option is absent,
# which is itself the answer: an absent override means the engine
# default, and this reader is only consulted where the difference
# between "reset", "delete" and everything else decides a verdict.
readonly WORLDOPTIONS_STDIN_READER='
import json
import sys

record = json.load(sys.stdin)
if not isinstance(record, list):
    raise SystemExit(1)
for entry in record:
    if not isinstance(entry, dict):
        continue
    if entry.get("name") != "WORLD_END":
        continue
    value = entry.get("value") or ""
    if not value:
        raise SystemExit(1)
    sys.stdout.write("%s" % value)
    raise SystemExit(0)
raise SystemExit(1)
'

readonly VERDICT_SEPARATOR=$'\037'

# ---------------------------------------------------------------------
# HOW MANY CHECKS THIS FILE IS SUPPOSED TO PERFORM
#
# A report that gets SHORTER reads exactly as green as a complete one:
# "93 of 93 checks passed" and "91 of 91 checks passed" are
# indistinguishable to a reader who does not already know the number, and
# a check that cannot be performed is the most dangerous kind of missing
# check.  So the count is DECLARED here, asserted at the end of the run,
# and printed in the summary and in the machine block.
#
# THE COUNT IS PER GROUP AND IT IS EXACT, and both halves of that are a
# fix.  A review found this declared as ONE total, asserted with "at
# least" -- and that guard cannot do the job it exists for.  Several
# checks report one verdict per offending item, so a broken artifact set
# genuinely produces more verdicts than the declaration; but with one
# global "at least", three extra per-frame failures in the luminance
# group SILENTLY PAY FOR three checks that never ran in the record group,
# and the report still says every declared check is present.  The
# masking is not hypothetical: it is arithmetic.
#
# So the declaration is per group, the comparison is per group, and it is
# an EQUALITY on the number of DISTINCT check names -- which is the
# measure per-item repetition cannot inflate, because a check reporting
# eleven times about eleven frames reports one name.  An extra name in
# group 6 can no longer settle a debt in group 2, and a name that is not
# in the declared inventory at all is now reported instead of welcomed.
#
# The derivation, group by group, on a complete artifact set -- with the
# COMMIT-SHAPED verdicts counted separately, because they are the ones
# the pre-commit phase defers:
#
#                                        all   pre   post
#    1  the measuring environment         14    14    14
#    2  one frame per keystroke           20    20     -
#    3  the timeline                      19    19     -
#    4  the container and its inputs      20    20     -
#    5  the caption track                 20    20     -
#    6  the luminance gate                 5     5     -
#    7  version control                   20     6    20
#    8  no cheating                        3     3     -
#    9  the binary, artwork and hygiene    12    11     2
#   10  the inventory of this report        1     1     1
#                                        ----  ----  ----
#                                         134   119    37
#
# The post-commit column is group 1 (a gate reports what it can measure
# before it reports what it measured), the whole of group 7, group 9's
# change-surface check and its closing bytecode sweep, and the inventory.
# The artifact groups are absent because the commit did not touch the
# artifacts; `--phase all` is how they are re-measured deliberately.
#
# The FIFTEEN the pre-commit phase defers, each named by the property
# it reports, are:
#
#   group 7   the world's own save file is tracked
#             the survivor's own save file is tracked
#             the world's option overrides are tracked
#             every artifact class is tracked
#             every capture on disk is tracked
#             nothing under playthrough/ is left uncommitted
#             the save was committed at both mandated points
#             the dossier's first commit precedes the first capture's
#             the committed .gitignore still rescues the save data
#             the committed .gitattributes carries this feature's rows
#             each checkpoint anchors to its own survivor's creation
#             the lifecycle checkpoints are about the survivor in the
#             tree
#             the recording in the tree has a checkpoint pair of its own
#             the evidence anchor's head is published in the history
#   group 9   the change surface is only the two ignore files and
#             playthrough/
#
# The table is maintained with the checks: adding one without adding it
# here makes this assertion fail, which is the intended direction of that
# mistake.
readonly -a GROUP_CHECKS_ALL=(
    0 14 20 19 20 20 5 20 3 12 1
)
readonly -a GROUP_CHECKS_PRE_COMMIT=(
    0 14 20 19 20 20 5 6 3 11 1
)
# The third phase, and the reason it is a THIRD count rather than a
# synonym for `all`: `post-commit` used to resolve to the whole audit, so
# the sequencer paid for every artifact check twice on any run that
# reached its checkpoint.  The artifacts are not what a commit changed,
# so post-commit asks the environment it measures with, the whole of
# version control, group 9's change surface and bytecode sweep, and the
# inventory -- and `--phase all` remains how the artifacts are
# re-measured deliberately.
readonly -a GROUP_CHECKS_POST_COMMIT=(
    0 14 0 0 0 0 0 20 0 2 1
)
# The names, for a discrepancy that can say WHICH group is short rather
# than only that the total is.  Index 0 is unused so that the index is
# the group number a reader sees in the report.
readonly -a GROUP_NAMES=(
    ""
    "the measuring environment"
    "one frame per keystroke"
    "the timeline"
    "the container and its inputs"
    "the caption track"
    "the luminance gate"
    "version control"
    "no cheating"
    "the binary, artwork and hygiene"
    "the inventory of this report"
)
readonly GROUP_COUNT=10

# The totals are SUMMED FROM THE TABLE rather than written down beside
# it.  A hand-maintained total is a second place for the truth to live,
# and the first thing that happens to it is that somebody updates one and
# not the other.
# Pure arithmetic: this runs at file scope, before any external command
# has been resolved and verified, so `seq` is not available to it and
# would not be used if it were.
_expected_all=0
_expected_pre_commit=0
_expected_post_commit=0
for ((_group_index = 1; _group_index <= GROUP_COUNT; _group_index++)); do
    _expected_all=$((_expected_all + \
        GROUP_CHECKS_ALL[_group_index]))
    _expected_pre_commit=$((_expected_pre_commit + \
        GROUP_CHECKS_PRE_COMMIT[_group_index]))
    _expected_post_commit=$((_expected_post_commit + \
        GROUP_CHECKS_POST_COMMIT[_group_index]))
done
readonly EXPECTED_CHECKS_ALL="${_expected_all}"
readonly EXPECTED_CHECKS_PRE_COMMIT="${_expected_pre_commit}"
readonly EXPECTED_CHECKS_POST_COMMIT="${_expected_post_commit}"
unset _expected_all _expected_pre_commit _expected_post_commit
unset _group_index

# WHERE THE DURABLE REPORT LANDS -- AND WHY THAT IS NO LONGER THIS
# FILE'S BUSINESS.
#
# It used to be a constant here, `acceptance-report.txt`, and this gate
# wrote the report to playthrough/<that> on a passing run and deleted it
# on a failing one.  Both were writes INSIDE the tree being measured, both
# happened after the checks that assert that tree is clean and fully
# committed, and a review found the consequence: a full-phase run taken
# after the final checkpoint left the tree dirty in the very file it had
# just certified as committed.
#
# A measurement does not publish itself.  This gate now writes only where
# a caller names with --report-to, always outside the checkout, and
# COMMITTING the report is a separate deliberate act -- the attestation
# checkpoint, which reads what this gate measured and can refuse to
# publish a failing one.  The artifact's own name therefore lives with
# the stage that produces it rather than with the stage that is judged
# by it.

# ---------------------------------------------------------------------
# THE PHASES, as the three words the option accepts.  Each measures a
# different set: `pre-commit` the artifacts, `post-commit` the history,
# and `all` both -- see WHY post-commit IS NOT "EVERYTHING" ANY MORE at
# the head of this file.  A report says which phase produced it, so a
# saved transcript can always be placed.
# ---------------------------------------------------------------------
readonly PHASE_ALL="all"
readonly PHASE_PRE_COMMIT="pre-commit"
readonly PHASE_POST_COMMIT="post-commit"
readonly PHASE_DEFAULT="${PHASE_ALL}"

# ---------------------------------------------------------------------
# THE REPORT
#
# Verdicts go to stdout, because the report IS the product of this file
# and is what gets read, saved and quoted.  Environmental diagnostics go
# to stderr through env.sh's helpers, so a caller can keep the two
# apart.  The trailing VERIFY_* block is the machine-readable summary,
# in the same KEY=value shape the sibling stages publish.
# ---------------------------------------------------------------------
PASSES=0
FAILURES=0
INFOS=0
# Verdicts that are neither: the delivered code departs from what
# the plan requires, knowingly, and the departure cannot be closed
# from inside this pipeline.  See record_divergence.
DIVERGENCES=0
GROUP=0
SCRATCH=""
BASE_COMMIT=""
# The most recent grayscale reading, so a frame is measured once and the
# same numbers are reported that were judged.
LAST_LUMINANCE=""
LUMINANCE_SAMPLES="${LUMINANCE_SAMPLES_DEFAULT}"
# The phase this run measures, and the count it therefore declares.
# Both are set once by parse_arguments and read everywhere else.
PHASE="${PHASE_DEFAULT}"
EXPECTED_CHECKS="${EXPECTED_CHECKS_ALL}"

# The tool paths, defaulted to the plain command names so that `set -u`
# cannot trip before they have been resolved and verified.  A tool that
# is genuinely absent makes the checks that use it FAIL, which is the
# intended behaviour -- the gate keeps measuring everything else.
#
# EVERY EXTERNAL COMMAND THIS FILE INVOKES HAS ONE OF THESE, AND
# NOTHING ELSE DOES.  That is a fix rather than tidiness.  A review found
# the inventory covering nine commands while the gate also ran head,
# tail, tr, sort, wc, cat, rm, mktemp, chmod, find, basename and cut --
# and invoked even the CHECKED `sed` by bare name, so the verified path
# was resolved and then not used.  A gate that says "every command this
# gate needs is present and verified" has to mean all of them, and has to
# call the thing it verified: PATH is not this process's to trust, and a
# bare name re-searches it at every call.
#
# The set is kept EXACT in both directions.  `dirname` and `touch` are
# not here because nothing invokes them -- the bootstrap that used to
# call dirname now takes the directory with ${BASH_SOURCE[0]%/*}, which
# needs no command at all -- and a declared tool the gate never runs is
# the same drift in the opposite direction: it would make an operator
# install something to satisfy a check that proves nothing.  ShellCheck
# enforces this half automatically: an unused variable here is SC2034.
FFPROBE="ffprobe"
FFMPEG="ffmpeg"
CONVERT="convert"
IDENTIFY="identify"
COMPARE="compare"
GIT="git"
AWK="awk"
GREP="grep"
SED="sed"
HEAD="head"
TAIL="tail"
TR="tr"
SORT="sort"
WC="wc"
CAT="cat"
RM="rm"
MKTEMP="mktemp"
CHMOD="chmod"
FIND="find"
BASENAME="basename"
CUT="cut"
TIMEOUT="timeout"
PYTHON="${PLAYTHROUGH_PYTHON}"

# The commands above, in the order they are reported, so the resolution
# and the inventory verdict cannot drift apart.
readonly REQUIRED_COMMANDS="ffprobe ffmpeg convert identify compare \
git awk grep sed head tail tr sort wc cat rm mktemp chmod find \
basename cut timeout"

# What the pre-scratch resolution found, reported as a verdict in group 1
# rather than at the moment it happened: the resolution has to precede
# the scratch directory (mktemp and chmod build it), and the report has
# not started printing that early.
TOOLS_RESOLVED=0
TOOLS_DETAIL=""

# The durable copy of this report.  Empty until open_scratch has made
# somewhere private to write it; every line of the report is appended to
# it as it is printed, and report_publication_target decides whether a
# copy is left at the destination the caller named.
REPORT_FILE=""

# WHERE THE CALLER ASKED FOR THE REPORT, or nothing.  Set only by
# --report-to (or $PLAYTHROUGH_VERIFY_REPORT_TO), always OUTSIDE the
# working tree, and validated in parse_arguments before any check runs --
# a destination that would be refused is refused before the measurement
# is paid for rather than after it.
REPORT_DESTINATION=""

# The linter as an ARRAY rather than a string, because one of the four
# ways it resolves is a multi-word `<python> -B -m flake8`; a string
# would have to be re-split at the call site, which is the shape of
# command construction this pipeline does not use.
FLAKE8_CMD=()
# Every linter candidate that was REFUSED, so a rejection is reported
# rather than silently falling through to the next candidate.
FLAKE8_REJECTED=""

# say FORMAT [ARG...] -- one piece of the report, to stdout AND to the
# durable copy.
#
# WHY THE REPORT IS CAPTURED AS IT IS PRINTED.  A review found the gate
# streaming its verdicts and then deleting its scratch directory, leaving
# no durable record that the ffprobe readings, the luminance statistics,
# the git status, the checkpoint ids and the no-cheat searches were ever
# made -- so "the artifacts were verified" rested on a terminal somebody
# had closed.  Capturing here rather than teeing the whole process keeps
# the counters in THIS shell (a pipeline would put them in a subshell and
# lose every one) and needs no race with a background writer.
#
# The format string is always a literal from this file, so passing it
# through is safe; SC2059 is disabled for exactly that reason.
say() {
    local format="$1"
    shift
    local line=""
    # TRAILING WHITESPACE IS TRIMMED HERE, AT THE ONE POINT EVERY LINE OF
    # THE REPORT PASSES THROUGH.
    #
    # Many verdicts quote a tool's own output with its newlines collapsed
    # to spaces -- `--version` banners especially -- which leaves a
    # trailing space on the line.  That is invisible on a terminal and
    # very visible in the COMMITTED report: `git diff --check` reported
    # playthrough/acceptance-report.txt for trailing whitespace on three
    # lines, one of them the linter's own version banner.  Trimming at
    # each call site would mean trimming at every future one too, and the
    # one that forgot would be the one that shipped.
    #
    # Every format string in this file ends in \n, and the command
    # substitution strips that trailing newline, so exactly one is added
    # back.  A multi-line verdict keeps its interior newlines and loses
    # only whitespace at its very end, which is the intent.
    # shellcheck disable=SC2059
    line="$(printf "${format}" "$@")"
    line="${line%"${line##*[![:space:]]}"}"
    printf '%s\n' "${line}"
    if [ -n "${REPORT_FILE}" ]; then
        printf '%s\n' "${line}" >>"${REPORT_FILE}"
    fi
}

note() {
    say '%s=%s\n' "$1" "$2"
}

# rel PATH -- the repository-relative spelling, delegated to env.sh so
# there is one implementation of it in the pipeline.
rel() {
    playthrough_rel "$1"
}

# die STATUS MESSAGE... -- for the handful of conditions under which
# there is nothing left to measure.  env.sh's playthrough_die RETURNS 1
# rather than exiting, because it is sourced and an exit there would
# kill an interactive shell; the exit is therefore taken here.
die() {
    local status="$1"
    shift
    playthrough_die "$@" || true
    exit "${status}"
}

# group NUMBER NAME -- open a group under its OWN number.
#
# THE NUMBER IS THE GROUP'S IDENTITY, NOT ITS POSITION IN THIS RUN.  It
# used to be a running counter, which is the same thing only while every
# group runs: under `--phase post-commit` four groups report, and the
# counter numbered version control 2 and hygiene 3.  Every verdict is
# filed under that number by register_check and the inventory reads the
# files back, so the post-commit phase compared version control's
# seventeen verdicts against group 2's declaration and reported both as
# wrong while each had performed exactly what it declared.  Numbering
# each group for itself also means a post-commit report and a full one
# name the same group by the same number, which is what makes the two
# comparable.
group() {
    GROUP="$1"
    say '\n=== %d. %s ===\n' "${GROUP}" "$2"
}

# register_check NAME -- record that this check reported, in this group.
#
# The inventory assertion in group 10 counts DISTINCT names per group, so
# every verdict that IS a check on the artifacts writes its name here.
# INFO and WARN deliberately do not: they are notes rather than
# judgements, and counting them would make the declared inventory a
# count of report lines instead of a count of checks.
#
# Before the scratch directory exists there is nowhere to write, and
# nothing reports that early -- group 1 opens after open_scratch.  The
# guard is there so that a future caller which does cannot fail on a
# redirection.
register_check() {
    [ -n "${SCRATCH}" ] && [ -d "${SCRATCH}" ] || return 0
    printf '%s\n' "$1" >>"${SCRATCH}/checks-${GROUP}.seen"
}

record_pass() {
    PASSES=$((PASSES + 1))
    register_check "$1"
    say 'PASS  %s\n' "$1"
    if [ -n "${2-}" ]; then
        say '      observed: %s\n' "$2"
    fi
}

record_fail() {
    FAILURES=$((FAILURES + 1))
    register_check "$1"
    say 'FAIL  %s\n' "$1"
    say '      observed: %s\n' "${2:-<nothing>}"
    say '      expected: %s\n' "${3:-<see the check name>}"
}

# record_divergence NAME OBSERVED REQUIRED WHY
#   The delivered code knowingly departs from what the plan requires,
#   and the departure cannot be closed from inside this pipeline.
#
#   WHY THIS IS ITS OWN VERDICT RATHER THAN A PASS OR A FAIL.  A review
#   found this gate reporting a KNOWN divergence from the plan as PASS,
#   with the reason written honestly in the observed text beside it -- so
#   the prose was truthful and the verdict was not, and the acceptance
#   report and REPORT.md then inherited "PASS" and dropped the prose.
#   That is the defect: not the divergence, which is documented and
#   forced, but a report that reads as compliance.
#
#   It is not a FAIL either, and that distinction is deliberate rather
#   than lenient.  A failure says "this is wrong and fixing it is the
#   work"; this says "this is not what the plan asked for, here is what
#   was delivered instead, and here is why the difference cannot be
#   closed here".  Collapsing the two would either hide a real failure
#   among permanent divergences or make the gate permanently red for
#   something no run of it can change.
#
#   IT DOES NOT AFFECT THE EXIT STATUS, and that is the one judgement
#   worth arguing with.  This gate runs before the commit stage, so a
#   non-zero exit for an environment-imposed and permanent divergence
#   would block every checkpoint for good rather than reporting anything.
#   Instead the run is impossible to MISREAD: the verdict line becomes
#   VERIFY=pass-with-divergence, the count is published as
#   VERIFY_DIVERGENCES, and the summary sentence stops claiming the
#   artifacts are what they claim to be.
#
#   It DOES register as a check, because it is a judgement about the
#   artifacts and the declared inventory must continue to account for it.
record_divergence() {
    DIVERGENCES=$((DIVERGENCES + 1))
    register_check "$1"
    say 'DIVERGENCE  %s\n' "$1"
    say '      observed: %s\n' "${2:-<nothing>}"
    say '      the plan requires: %s\n' "${3:-<see the check name>}"
    say '      why it stands: %s\n' "${4:-<unexplained>}"
}

record_info() {
    INFOS=$((INFOS + 1))
    say 'INFO  %s: %s\n' "$1" "${2:-<empty>}"
}

# record_warn -- something an operator should see that is not itself a
# verdict on the artifacts.  It does NOT affect the exit status: this
# gate's job is to judge the evidence, and a note about the host it was
# judged on is not evidence.
record_warn() {
    say 'WARN  %s: %s\n' "$1" "${2:-<empty>}"
}

# tracking_phase
#   Whether THIS run measures the commit-shaped properties: the ones
#   that are about the history rather than about the artifacts, and that
#   therefore cannot hold until the checkpoint has been taken.
#
#   One predicate, called at each of the two group call sites, rather
#   than an `if` inside each of the fifteen checks: a check that decides
#   for itself whether to run is a check that can be talked out of
#   running, and this way the classification is visible in one place
#   beside the group it belongs to.
tracking_phase() {
    [ "${PHASE}" != "${PHASE_PRE_COMMIT}" ]
}

# artifact_phase
#   Whether THIS run measures the artifact-shaped properties: the record,
#   the timeline, the container, the caption track, the luminance, the
#   absence of cheating, the artwork and the lint.  True for `pre-commit`
#   and for `all`; FALSE for `post-commit`, because a commit changes the
#   history and not the bytes, so re-measuring them minutes after the
#   pre-commit phase did is work with no question behind it.
#
#   The complement of tracking_phase in intent rather than in logic --
#   `all` is both -- and, like it, one predicate at the group call sites
#   rather than an `if` inside each of the eighty-nine artifact
#   checks.
artifact_phase() {
    [ "${PHASE}" != "${PHASE_POST_COMMIT}" ]
}

# ---------------------------------------------------------------------
# THE VERDICT CHANNEL
#
# The arithmetic-heavy checks are written in Python, because JSON,
# floating point and set comparison are what Python is for and because
# the sibling producers' own constants can be imported and cross-checked
# rather than restated.  Each program emits one verdict per line:
#
#     KIND <US> NAME <US> OBSERVED <US> EXPECTED
#
# and this function turns those lines into counted, formatted report
# entries.  It is fed by REDIRECTION from a file rather than by a pipe,
# and that is a correctness requirement rather than a style choice: the
# right-hand side of a pipe runs in a subshell, so every counter this
# function incremented would be discarded when it returned.
# ---------------------------------------------------------------------
consume_verdicts() {
    # Initialised rather than merely declared: under `set -u` a `local`
    # with no value is an unset variable, and the loop's own guard reads
    # ${kind} before the first successful read.
    local kind="" name="" observed="" expected=""
    while IFS="${VERDICT_SEPARATOR}" \
            read -r kind name observed expected || [ -n "${kind}" ]; do
        case "${kind}" in
            '') continue ;;
            PASS) record_pass "${name}" "${observed}" ;;
            FAIL) record_fail "${name}" "${observed}" "${expected}" ;;
            INFO) record_info "${name}" "${observed}" ;;
            WARN) record_warn "${name}" "${observed}" ;;
            *)
                record_fail "the verdict channel is well formed" \
                    "an unparsable line beginning '${kind}'" \
                    "PASS, FAIL, INFO or WARN and separated fields"
                ;;
        esac
    done
}


# emit_checker LABEL
#   Materialise one Python checker from this file's heredoc into SCRATCH.
#   The programs live in the scratch directory rather than in the working
#   tree so that running the gate cannot add an untracked file to the
#   evidence -- which check group 7 would then, correctly, report.
emit_checker() {
    "${CAT}" >"${SCRATCH}/$1.py"
}

# run_checker LABEL [arg ...]
#   Run one materialised checker, collect its verdicts and fold them into
#   the report.  A crash is itself a FAILURE of the gate -- reported with
#   the tail of its stderr so the cause is visible -- and any verdicts it
#   managed to emit before dying are still counted, so a partial run
#   reports what it did establish rather than nothing at all.
#
#   -B is passed on top of env.sh's PYTHONDONTWRITEBYTECODE=1 because
#   this gate asserts that no stray bytecode exists under playthrough/,
#   and a gate that creates the condition it forbids is worthless.
run_checker() {
    local label="$1"
    shift
    local script="${SCRATCH}/${label}.py"
    local out="${SCRATCH}/${label}.verdicts"
    local err="${SCRATCH}/${label}.stderr"
    local ceiling="" status=0 detail=""
    ceiling="$(checker_bound)"
    : >"${out}"
    # THE CEILING IS DERIVED FROM THE POPULATION, and an expiry is
    # reported as an expiry: a checker that hangs on a corrupt artifact
    # would otherwise hold this gate -- and the pipeline's lock -- for
    # ever, with no verdict at all.  Its stderr goes to a FILE and is
    # quoted from there in bounded form, because a checker that prints a
    # line per frame would otherwise put the whole session into one
    # shell variable to explain one failure.
    bounded "${ceiling}" "${PYTHON}" -B "${script}" "$@" \
        >"${out}" 2>"${err}" || status=$?
    if [ "${status}" -ne 0 ]; then
        detail="$(excerpt "${err}" 3)"
        if bound_expired "${status}"; then
            record_fail "the ${label} checks completed" \
                "the checker did not finish within ${ceiling}s and was \
stopped (exit ${status}): ${detail:-<no diagnostic>}" \
                "a clean run inside the ceiling derived from this \
artifact set -- an expiry here means a checker is wedged rather than \
slow, because the ceiling scales with the capture count"
        else
            record_fail "the ${label} checks completed" \
                "the checker exited non-zero: ${detail:-<no \
diagnostic>}" \
                "a clean run emitting one verdict per property"
        fi
    fi
    consume_verdicts <"${out}"
}

# fact KEY [DEFAULT]
#   Read one value out of the facts file a checker left behind, so a
#   number the shell needs -- the timeline total, the capture count -- is
#   the SAME number the checker measured rather than a second, possibly
#   divergent, reading of the same file.
fact() {
    local key="$1"
    local fallback="${2-}"
    local value=""
    if [ -f "${SCRATCH}/facts" ]; then
        value="$("${SED}" -n "s/^${key}=//p" "${SCRATCH}/facts" \
            2>/dev/null | "${HEAD}" -n 1 || true)"
    fi
    if [ -z "${value}" ]; then
        printf '%s' "${fallback}"
        return 0
    fi
    printf '%s' "${value}"
}

# floats_close A B EPSILON -- |A - B| <= EPSILON.
#
# THE SHELL CANNOT COMPARE FLOATING POINT.  `[ "0.27" -gt 0 ]` applies an
# integer operator to a string and fails at the syntax level rather than
# returning a wrong answer, so awk does every comparison in this file --
# as a fixed program with the values handed in through -v, never with a
# value interpolated into the program text.
floats_close() {
    "${AWK}" -v a="$1" -v b="$2" -v eps="$3" 'BEGIN {
        d = a - b
        if (d < 0) { d = -d }
        exit (d <= eps) ? 0 : 1
    }'
}

# TWO VALIDATORS, BECAUSE TWO DIFFERENT THINGS ARE BEING VALIDATED.
#
# There used to be one, accepting the character class [0-9.] and nothing
# else, and it was wrong in both directions at once.  ImageMagick prints
# its statistics with %g, which switches to SCIENTIFIC NOTATION for a
# very dark frame: a real capture measuring mean=7.56475e-09
# std=5.44662e-06 -- both strictly greater than zero, both perfectly
# comparable -- was rejected as "could not measure grayscale statistics"
# and reported as a failure, so an honest near-black capture failed while
# the numeric comparison never ran.  In the other direction, a value
# containing '.' passed and then reached `[ "${a}" -eq "${b}" ]`, which
# is an INTEGER comparison and errors at the syntax level on a decimal.
#
# So: is_real is what awk can compare, and is_count is what the shell can.
# Neither accepts ffprobe's "N/A", which is how ffprobe spells "I do not
# know" and must never be mistaken for a measurement.

# is_count VALUE -- a non-negative integer, safe for `-eq` and `-gt`.
is_count() {
    case "${1-}" in
        ''|'N/A'|'n/a') return 1 ;;
        *[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# is_real VALUE -- an optionally signed decimal, with an optional
# exponent, and therefore exactly the set of readings awk can compare.
# A bash regex rather than a case glob: an exponent is not expressible as
# a glob without accepting things that are not numbers, and bash is
# already a requirement of this file (BASH_SOURCE, arrays and `local`).
is_real() {
    case "${1-}" in
        ''|'N/A'|'n/a') return 1 ;;
    esac
    [[ "${1}" =~ ^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$ ]]
}

# ---------------------------------------------------------------------
# BOUNDED EXECUTION
#
# bounded SECONDS COMMAND...
#   Run one external command under a ceiling, TERM then KILL, over the
#   command's own process group.  Every child this gate starts goes
#   through here; see EVERY CHILD THIS GATE STARTS IS TIME-BOUNDED above
#   for why, and note that the status is returned UNCHANGED -- an expiry
#   is 124, a kill after the grace period 137, and each call site decides
#   what to say about it.
#
#   `timeout` is invoked by the path playthrough_require_tools verified,
#   exactly as every other tool here is.
# ---------------------------------------------------------------------
bounded() {
    local seconds="$1"
    shift
    "${TIMEOUT}" --kill-after="${BOUND_KILL_GRACE}" --signal=TERM \
        "${seconds}" "$@"
}

# bound_expired STATUS -- whether a bounded call was stopped by its
# ceiling rather than by the tool's own refusal.
bound_expired() {
    [ "${1:-0}" = "${BOUND_EXPIRED}" ] || [ "${1:-0}" = "${BOUND_KILLED}" ]
}

# file_bytes PATH -- the size in bytes, or 0.  `wc -c` on a redirection
# rather than `stat`, so no second tool has to be resolved and a missing
# file is 0 instead of a diagnostic.  `wc` is invoked by the path
# playthrough_require_tools verified, as every tool in this file is.
file_bytes() {
    local bytes=""
    bytes="$("${WC}" -c <"$1" 2>/dev/null || printf '0')"
    bytes="${bytes//[^0-9]/}"
    printf '%s' "${bytes:-0}"
}

# film_bound FILE -- the ceiling for one whole-film pass over FILE,
# derived from its byte count at the pessimistic throughput floor.
film_bound() {
    local seconds=0
    seconds=$(( BOUND_FILM_BASE_SECONDS +
        $(file_bytes "$1") / BOUND_FILM_BYTES_PER_SECOND ))
    if [ "${seconds}" -gt "${BOUND_MAX_SECONDS}" ]; then
        seconds="${BOUND_MAX_SECONDS}"
    fi
    printf '%s' "${seconds}"
}

# checker_bound -- the ceiling for one Python checker, derived from the
# population it reads.  The capture count comes from the facts file once
# group 2 has published it, and from the record's line count before that
# -- one `wc -l`, so the first checker is bounded too without walking a
# directory or holding one name in memory.
checker_bound() {
    local count="" seconds=0
    count="$(fact capture_count)"
    if ! is_count "${count}"; then
        count="$("${WC}" -l <"${PLAYTHROUGH_MANIFEST}" 2>/dev/null ||
            printf '0')"
        count="${count//[^0-9]/}"
    fi
    seconds=$(( BOUND_CHECKER_BASE_SECONDS +
        ${count:-0} / BOUND_CHECKER_CAPTURES_PER_SECOND ))
    if [ "${seconds}" -gt "${BOUND_MAX_SECONDS}" ]; then
        seconds="${BOUND_MAX_SECONDS}"
    fi
    printf '%s' "${seconds}"
}

# count_lines FILE -- how many non-empty lines FILE holds, as a number.
#
# `grep -c` EXITS NON-ZERO WHEN IT COUNTS ZERO, which is the trap this
# exists to close: `$(grep -c . "$f" || printf 0)` captures grep's own
# "0" AND the fallback's, and the two-line result then breaks the integer
# test it was written for -- observed as a lint verdict reading "0
# finding(s)" and failing anyway.  The status is discarded and the output
# is reduced to digits.
count_lines() {
    local count=""
    count="$("${GREP}" -c . "$1" 2>/dev/null || true)"
    count="${count//[^0-9]/}"
    printf '%s' "${count:-0}"
}

# excerpt FILE [LINES] -- the first few lines of a captured stream, on
# one line, for a verdict's observed value.  A diagnostic is READ FROM A
# FILE and bounded here rather than captured whole into a variable: a
# tool that prints one line per frame would otherwise put the entire
# session into the report, and into memory, to explain one failure.
excerpt() {
    local file="$1"
    local lines="${2:-4}"
    if [ ! -s "${file}" ]; then
        printf ''
        return 0
    fi
    "${HEAD}" -n "${lines}" "${file}" 2>/dev/null |
        "${TR}" '\n' ';' || true
}

# THE HELPERS THAT SHELL OUT, AND WHY THEY KEEP THEIR STDERR
#
# Each of these turns a failure into an empty string, which is right: a
# missing stream has to be a VERDICT rather than the end of the run.  What
# was wrong -- and a review said so -- is that the tool's own explanation
# went to /dev/null with it, so the report read "observed: <nothing>" for
# a file that is missing, a file that is not a container, a codec that is
# not built in and a permission error alike.  The reason exists; it was
# being thrown away.
#
# So every one of them writes its stderr into a file inside the private
# scratch directory, and the failing checks append a bounded tail of it to
# what they observed -- bounded so a diagnostic cannot become the report.
# Scratch is 0700 inside the runtime root, so a path or a filename in a
# tool message stays as private as every other diagnostic this pipeline
# writes.
#
# THE REASON IS KEPT IN THE FILE AND NOT IN A VARIABLE, and that is a
# correctness requirement rather than a preference.  Every one of these
# helpers is called inside `$( )`, which is a SUBSHELL: a variable it
# assigned would be discarded the instant the substitution closed, and
# the caller would read an empty reason for every failure -- the exact
# silence this fix exists to end, reintroduced one layer down.  The file
# is written by the subshell to the filesystem, so it survives; and
# because `2>` TRUNCATES at redirection time, the file always holds
# precisely the stderr of the most recent invocation for that tool,
# emptied automatically by the next one that succeeds.
# ---------------------------------------------------------------------

# tool_error_file LABEL -- where a helper's stderr goes.  Before scratch
# exists there is nowhere private to put it, so the answer is /dev/null
# and no reason is available; every helper below runs after open_scratch
# in practice.
tool_error_file() {
    if [ -z "${SCRATCH}" ] || [ ! -d "${SCRATCH}" ]; then
        printf '%s' "/dev/null"
        return 0
    fi
    printf '%s' "${SCRATCH}/tool-$1.err"
}

# because TOOL -- " (TOOL said: <reason>)" when TOOL's last invocation
# explained itself, and NOTHING AT ALL when it did not, so a verdict
# never carries an empty parenthesis.
#
# Two lines and 200 characters at the most.  ffmpeg in particular will
# print a banner and a hundred lines of build configuration given the
# chance; a verdict that scrolls is a verdict nobody reads, and this gate
# reports what was observed next to what was required on one line each.
#
# CALL IT IMMEDIATELY AFTER THE PROBE IT EXPLAINS.  Several checks read
# four fields from one file before reporting on any of them, and all four
# share the one ffprobe error file, so a `because` deferred to verdict
# time would attribute the fourth probe's complaint to the first.  The
# convention is `x="$(probe_value ...)"; x_said="$(because ffprobe)"`,
# which snapshots the reason while it is still the right one.
because() {
    local tool="${1:-the tool}"
    local path="" reason=""
    path="$(tool_error_file "${tool}")"
    [ -f "${path}" ] || return 0
    reason="$("${TAIL}" -n 2 -- "${path}" 2>/dev/null |
        "${TR}" '\n\t' '  ' | "${CUT}" -c 1-200 || true)"
    # Trailing whitespace from the newline translation.
    reason="${reason%"${reason##*[![:space:]]}"}"
    [ -n "${reason}" ] || return 0
    printf ' (%s said: %s)' "${tool}" "${reason}"
}

# probe_field FILE SELECTOR ENTRIES
#   One ffprobe read in KEY=value form, with the failure surfaced as an
#   empty string rather than as an abort, so a missing stream is a
#   verdict instead of the end of the run.
probe_field() {
    local err
    err="$(tool_error_file ffprobe)"
    bounded "${BOUND_PROBE_SECONDS}" \
        "${FFPROBE}" -v error -select_streams "$2" \
        -show_entries "$3" -of default=nw=1 -i "$1" 2>"${err}" || true
}

# probe_value FILE SELECTOR ENTRY -- the bare first value, or "".
probe_value() {
    local err
    err="$(tool_error_file ffprobe)"
    bounded "${BOUND_PROBE_SECONDS}" \
        "${FFPROBE}" -v error -select_streams "$2" -show_entries "$3" \
        -of default=noprint_wrappers=1:nokey=1 -i "$1" 2>"${err}" |
        "${HEAD}" -n 1 || true
}

# probe_format FILE ENTRY -- a container-level value, such as duration.
probe_format() {
    local err
    err="$(tool_error_file ffprobe)"
    bounded "${BOUND_PROBE_SECONDS}" \
        "${FFPROBE}" -v error -show_entries "format=$2" \
        -of default=noprint_wrappers=1:nokey=1 -i "$1" 2>"${err}" |
        "${HEAD}" -n 1 || true
}

# luminance PNG -- "mean std" over the grayscale conversion, or "" when
# the file cannot be read.  The mean catches a fully black frame, which
# is what SDL_VIDEODRIVER=dummy produces; the standard deviation
# additionally catches a uniform solid-colour frame, which a mean-only
# test would pass.
luminance() {
    local err
    err="$(tool_error_file convert)"
    bounded "${BOUND_PROBE_SECONDS}" \
        "${CONVERT}" "$1" -colorspace Gray \
        -format '%[fx:mean] %[fx:standard_deviation]' info: \
        2>"${err}" || true
}

# geometry PNG -- "WxH", or "" when the file cannot be read.
geometry() {
    local err
    err="$(tool_error_file identify)"
    bounded "${BOUND_PROBE_SECONDS}" \
        "${IDENTIFY}" -format '%wx%h' "$1" 2>"${err}" || true
}

# ---------------------------------------------------------------------
# ONE DECODE PER FILM, AND ONE EXTRACTION PER OFFSET
#
# Four properties of a film need the pictures rather than the header:
# that every packet decodes, how many frames come out, that the container
# does not declare more than it can produce, and that the captioned
# film's pixels are identical to the plain one's.  Each used to walk the
# stream for itself, so the base film was read three times and the
# captioned film twice on every run, and the same two offsets were
# extracted twice from each of them.
#
# A decode is O(film), the film is O(session), and the session is
# deliberately unbounded -- so the passes are made ONCE and cached in the
# scratch generation, which exists for exactly the length of this run.
# Freshness needs no reasoning about staleness: the cache cannot outlive
# the artifacts it describes.
#
# film_decode_pass FILE
#   Decode FILE from end to end, once, and leave the outcome in
#   FILM_PASS_STATUS, FILM_PASS_FRAMES, FILM_PASS_CEILING and
#   FILM_PASS_LOG.  -xerror makes a corrupt NAL unit, a partial packet or
#   a missing picture a failure rather than a warning nobody sees, and
#   -progress makes the same pass report how many frames it decoded --
#   which is the number `ffprobe -count_frames` used to be run twice
#   more to obtain.  Measured on this session: 0.9 s for the pass against
#   1.8 s for each of the two counts it replaces.
# ---------------------------------------------------------------------
FILM_PASS_STATUS=""
FILM_PASS_FRAMES=""
FILM_PASS_CEILING=""
FILM_PASS_LOG=""

film_decode_pass() {
    local file="$1"
    local name="" state="" progress="" ceiling="" status=0 frames=""
    name="$("${BASENAME}" "${file}")"
    state="${SCRATCH}/decode-${name}.state"
    FILM_PASS_LOG="${SCRATCH}/decode-${name}.log"
    progress="${SCRATCH}/decode-${name}.progress"
    if [ ! -f "${state}" ]; then
        ceiling="$(film_bound "${file}")"
        : >"${progress}"
        bounded "${ceiling}" "${FFMPEG}" -nostdin -v error -xerror \
            -i "${file}" -progress "${progress}" -f null - \
            >/dev/null 2>"${FILM_PASS_LOG}" || status=$?
        # The LAST frame= line the encoder wrote, which is the count at
        # the end of the stream.  An expired or wedged pass leaves
        # whatever it had reached, and the reading is reported as
        # unusable rather than as a count, because a partial count that
        # happened to match would be the worst possible outcome.
        frames="$("${SED}" -n 's/^frame=[[:space:]]*//p' \
            "${progress}" 2>/dev/null | "${TAIL}" -n 1 || true)"
        frames="${frames//[^0-9]/}"
        if [ "${status}" -ne 0 ]; then
            frames=""
        fi
        printf '%s %s %s\n' "${status}" "${frames:-none}" \
            "${ceiling}" >"${state}"
    fi
    FILM_PASS_STATUS=""
    FILM_PASS_FRAMES=""
    FILM_PASS_CEILING=""
    read -r FILM_PASS_STATUS FILM_PASS_FRAMES FILM_PASS_CEILING \
        <"${state}" || true
    if [ "${FILM_PASS_FRAMES}" = "none" ]; then
        FILM_PASS_FRAMES=""
    fi
}

# extracted_frame FILE OFFSET
#   The path of one frame taken OFFSET seconds into FILE, extracted once
#   per (film, offset) and reused.  Returns 1 when nothing could be
#   decoded there, which is itself a verdict at the call site: a film
#   that stops early cannot answer for its later seconds.
extracted_frame() {
    local file="$1"
    local offset="$2"
    local name="" path="" marker="" ceiling=""
    name="$("${BASENAME}" "${file}")"
    path="${SCRATCH}/frame-${name}-${offset}.png"
    marker="${path}.failed"
    if [ -s "${path}" ]; then
        printf '%s' "${path}"
        return 0
    fi
    if [ -f "${marker}" ]; then
        return 1
    fi
    ceiling="$(film_bound "${file}")"
    if ! bounded "${ceiling}" "${FFMPEG}" -nostdin -y -v error \
            -ss "${offset}" -i "${file}" -frames:v 1 "${path}" \
            >/dev/null 2>&1 || [ ! -s "${path}" ]; then
        : >"${marker}"
        return 1
    fi
    printf '%s' "${path}"
    return 0
}

# ---------------------------------------------------------------------
# USAGE
# ---------------------------------------------------------------------
usage() {
    "${CAT}" <<'USAGE'
verify_artifacts.sh -- the acceptance gate for the playthrough capture
subsystem.  Reads the committed artifacts, reports one verdict per
property, and exits non-zero if any property does not hold.

    playthrough/tooling/verify_artifacts.sh [options]

Options:
  --phase PHASE     which properties to measure.  One of:
                      all           everything, artifacts and history.
                                    THE DEFAULT, and the full audit.
                      pre-commit    every property of the ARTIFACTS,
                                    deferring the fifteen that are
                                    properties of the COMMIT and
                                    cannot hold before it is taken.
                                    This is the phase that runs AHEAD
                                    of commit_artifacts.sh.
                      post-commit   THE HISTORY: the properties the
                                    commit made answerable, plus the
                                    measuring environment they are
                                    read with.  This is the phase that
                                    runs AFTER it, and it does NOT
                                    re-measure the artifacts -- a
                                    commit changes the history, not
                                    the bytes.  Run `all` when the
                                    question is the whole tree.
                    --pre-commit and --post-commit are accepted as
                    shorthands.  The declared check count is per phase,
                    so none of them can return a short report unnoticed.
  --base COMMIT     the commit the change surface is measured from.
                    Defaults to the parent of the first commit that
                    touched playthrough/, which is the point this
                    feature began.
  --samples N       DECODE the pixels of a spread of N captures in the
                    luminance gate, always including the first and the
                    last (minimum 2).  THE DEFAULT IS 64.  The verdict
                    always says how many of how many it read, so a
                    sampled reading cannot be mistaken for a complete
                    one.
  --samples all     decode every capture.  The exhaustive audit, and the
                    reading to take when the question is whether a
                    frame's digest AND the capture stage's own recorded
                    reading were both re-declared to hide a blank frame
                    -- every other blank-frame case is caught by those
                    two whole-population witnesses.  About forty seconds
                    per three hundred captures, so it scales with the
                    session.
  --report-to PATH  also write the report to PATH.  It must lie OUTSIDE
                    this checkout, and its parent directory must already
                    exist: this gate creates nothing and writes nothing
                    into the tree it measures.  Without it the report
                    exists only on this stream.  PUBLISHING the report as
                    a committed artifact is the attestation checkpoint's
                    act, not this measurement's -- a gate that wrote into
                    playthrough/ would dirty a file it had just certified
                    as committed, which is what it used to do.
  -h, --help        print this and exit.

Environment:
  PLAYTHROUGH_VERIFY_BASE     the default for --base.
  PLAYTHROUGH_VERIFY_SAMPLES  the default for --samples.
  PLAYTHROUGH_VERIFY_PHASE    the default for --phase.
  PLAYTHROUGH_VERIFY_REPORT_TO
                              the default for --report-to.
  PLAYTHROUGH_FLAKE8          the flake8 to lint with, when it is not
                              on PATH and not importable as a module.
                              NOT forwarded into the container by
                              supported_env.sh, so inside the image the
                              linter must be on PATH or importable
                              there.

Notes:
  This gate READS committed evidence and writes nothing into the working
  tree, so it is safe to run on any host.  Do NOT set the diagnostic
  bypasses when running it: a capture-time bypass (an unverified
  executable, an unauthenticated X server, an unverified or substituted
  tileset pack, an unpinned Pillow, an unsanctioned compiler) is a
  FAILURE here, because evidence produced under a relaxed check is not
  evidence.  PLAYTHROUGH_ALLOW_EOL_PLATFORM is the exception: it says
  something about the host doing the reading rather than about the
  session that was recorded, so it is reported as a warning and does not
  fail the run.

Exit status: 0 all checks passed, 1 a check failed, 2 usage, 3 layout.
USAGE
}

# resolve_report_destination PATH
#   PATH as an absolute path, with its parent resolved through the
#   filesystem, or a non-zero status when that parent does not exist.
#
#   The PARENT is resolved rather than the path itself, because the
#   report does not exist yet: `cd` into the directory that will hold it
#   and ask where that actually is.  Resolving it is what makes the
#   inside-the-tree test meaningful -- a relative path, a symlink or a
#   trail of `..` would otherwise walk into the checkout while looking
#   like somewhere else.  Nothing is created here; a caller who names a
#   directory that does not exist is told so rather than having one made
#   for them by a gate that promises to write nothing.
#   The split is parameter expansion rather than `dirname`/`basename`
#   because this file RESOLVES AND VERIFIES every external command it
#   uses, and adding one to that machinery to cut a string in half would
#   be a dependency bought for nothing.
resolve_report_destination() {
    local given="$1" parent="" leaf=""
    case "${given}" in
        */) return 1 ;;
        */*)
            parent="${given%/*}"
            leaf="${given##*/}"
            [ -n "${parent}" ] || parent="/"
            ;;
        *)
            parent="."
            leaf="${given}"
            ;;
    esac
    [ -n "${leaf}" ] || return 1
    parent="$(cd -- "${parent}" 2>/dev/null && pwd -P)" || return 1
    case "${parent}" in
        */) printf '%s%s' "${parent}" "${leaf}" ;;
        *) printf '%s/%s' "${parent}" "${leaf}" ;;
    esac
}

parse_arguments() {
    local base="${PLAYTHROUGH_VERIFY_BASE:-}"
    local samples="${PLAYTHROUGH_VERIFY_SAMPLES:-\
${LUMINANCE_SAMPLES_DEFAULT}}"
    local phase="${PLAYTHROUGH_VERIFY_PHASE:-${PHASE_DEFAULT}}"
    local report_to="${PLAYTHROUGH_VERIFY_REPORT_TO:-}"
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --phase)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--phase needs one of" \
                        "${PHASE_ALL}, ${PHASE_PRE_COMMIT} or" \
                        "${PHASE_POST_COMMIT}"
                fi
                phase="$2"
                shift 2
                ;;
            --phase=*)
                phase="${1#--phase=}"
                shift
                ;;
            --pre-commit)
                phase="${PHASE_PRE_COMMIT}"
                shift
                ;;
            --post-commit)
                phase="${PHASE_POST_COMMIT}"
                shift
                ;;
            --base)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--base needs a commit"
                fi
                base="$2"
                shift 2
                ;;
            --base=*)
                base="${1#--base=}"
                shift
                ;;
            --samples)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--samples needs a count"
                fi
                samples="$2"
                shift 2
                ;;
            --samples=*)
                samples="${1#--samples=}"
                shift
                ;;
            --report-to)
                if [ "$#" -lt 2 ]; then
                    usage >&2
                    die "${EX_USAGE}" "--report-to needs a path"
                fi
                report_to="$2"
                shift 2
                ;;
            --report-to=*)
                report_to="${1#--report-to=}"
                shift
                ;;
            -h|--help)
                usage
                exit "${EX_OK}"
                ;;
            *)
                usage >&2
                die "${EX_USAGE}" "unrecognised argument '$1'"
                ;;
        esac
    done

    # The phase is resolved against literal alternatives, and an
    # unrecognised one is REFUSED rather than defaulted: a typo that
    # silently produced the full gate would be reported as the phase
    # that was asked for, and a report about the wrong phase is worse
    # than no report.
    case "${phase}" in
        "${PHASE_ALL}")
            PHASE="${phase}"
            EXPECTED_CHECKS="${EXPECTED_CHECKS_ALL}"
            ;;
        "${PHASE_PRE_COMMIT}")
            PHASE="${phase}"
            EXPECTED_CHECKS="${EXPECTED_CHECKS_PRE_COMMIT}"
            ;;
        "${PHASE_POST_COMMIT}")
            PHASE="${phase}"
            EXPECTED_CHECKS="${EXPECTED_CHECKS_POST_COMMIT}"
            ;;
        *)
            usage >&2
            die "${EX_USAGE}" "'${phase}' is not a phase of this" \
                "gate.  The phases are ${PHASE_ALL}," \
                "${PHASE_PRE_COMMIT} and ${PHASE_POST_COMMIT}."
            ;;
    esac

    # WHERE THE REPORT MAY BE WRITTEN, AND WHERE IT MAY NOT.
    #
    # This gate is a MEASUREMENT, and a measurement that edits the thing
    # it measures is not one.  It used to write the report to
    # playthrough/acceptance-report.txt on a passing run and DELETE that
    # file on a failing one -- both inside the working tree, and both
    # after the checks that assert the tree is clean and fully
    # committed.  A review named the consequence: a `--phase all` run
    # taken after the final checkpoint left the tree dirty in a file the
    # gate had just certified as committed, and a failing run silently
    # removed a tracked artifact.  It also made the promise in this
    # file's own usage text -- "writes nothing into the working tree" --
    # untrue.
    #
    # So the destination is now the CALLER'S, named explicitly, and it
    # must lie OUTSIDE the working tree.  Publishing the report as a
    # committed artifact is a separate, deliberate act performed by the
    # attestation checkpoint, which commits what this gate measured
    # rather than having the measurement commit itself.
    if [ -n "${report_to}" ]; then
        local resolved="" inside=""
        resolved="$(resolve_report_destination "${report_to}")" ||
            die "${EX_USAGE}" "--report-to '${report_to}' cannot be" \
                "resolved: its parent directory must already exist," \
                "because this gate creates nothing."
        case "${resolved}" in
            "${PLAYTHROUGH_REPO_ROOT}"/*|"${PLAYTHROUGH_REPO_ROOT}")
                inside="yes" ;;
        esac
        if [ -n "${inside}" ]; then
            die "${EX_USAGE}" "--report-to '${report_to}' resolves to" \
                "${resolved}, which is INSIDE the working tree." \
                "This gate writes nothing into the tree it measures --" \
                "a report written there would dirty a file the run had" \
                "just certified as committed, and on a failing run the" \
                "previous one used to be deleted outright.  Name a" \
                "path outside the checkout; committing the report is" \
                "the attestation checkpoint's job, not the" \
                "measurement's."
        fi
        REPORT_DESTINATION="${resolved}"
    fi

    # `all` is carried through as a word and resolved against the real
    # capture count later, once that count is known.
    if [ "${samples}" = "${LUMINANCE_SAMPLES_ALL}" ]; then
        LUMINANCE_SAMPLES="${LUMINANCE_SAMPLES_ALL}"
        BASE_COMMIT="${base}"
        return 0
    fi
    # Validated through env.sh's helper rather than by arithmetic on the
    # raw string: bash evaluates command substitution inside $(( )), so
    # an unvalidated number from the environment is code execution and
    # not a number.
    if ! playthrough_validate_int "${samples}" \
            "the luminance sample count" 2 100000; then
        die "${EX_USAGE}" "--samples must be 'all' or an integer of 2" \
            "or more"
    fi
    LUMINANCE_SAMPLES="${PLAYTHROUGH_INT}"
    BASE_COMMIT="${base}"
}

# default_base_commit
#   The parent of the earliest commit that touched playthrough/, which
#   is exactly "the tree as it was before this feature existed" and
#   therefore the right thing to diff a change surface against.
#
#   `tail -1` rather than `git log --reverse | head -1`: head closing
#   the pipe early raises SIGPIPE in git, which pipefail would turn into
#   a failure of the whole assignment.
default_base_commit() {
    local first="" parent=""
    first="$("${GIT}" log --format='%H' -- playthrough 2>/dev/null |
        "${TAIL}" -n 1 || true)"
    if [ -z "${first}" ]; then
        return 1
    fi
    parent="$("${GIT}" rev-parse --verify --quiet "${first}^" \
        2>/dev/null || true)"
    if [ -z "${parent}" ]; then
        return 1
    fi
    printf '%s' "${parent}"
}

# ---------------------------------------------------------------------
# SCRATCH
#
# Confined to the mode-0700 runtime root env.sh created and verified,
# never to a predictable path in a world-writable /tmp, and removed on
# every exit path.  The recursive removal is bounded to the directory
# mktemp just made, which is the only shape of `rm -rf` this pipeline
# permits.
# ---------------------------------------------------------------------
# SC2317: ShellCheck cannot see that a trap handler is called, so the
# body reads as dead code to it.  env.sh carries the same suppression for
# the same reason.
# shellcheck disable=SC2317
_va_cleanup() {
    if [ -n "${SCRATCH}" ] && [ -d "${SCRATCH}" ]; then
        "${RM}" -rf -- "${SCRATCH}"
    fi
    # Releases ONLY if this process took it; a run started by the
    # sequencer inherited the sequencer's hold and must leave it
    # exactly where it found it.
    playthrough_release_mutation_lock || true
}
trap _va_cleanup EXIT

# take_mutation_lock -- measure a tree that is standing still.
#
# A GATE THAT PASSES SAYS NOTHING IF THE TREE MOVED WHILE IT WAS READING.
# Every group here reads the artifacts in sequence -- the frame count,
# then the manifest, then the timeline, then the films -- and a producer
# appending a frame between the first and the second turns a real
# disagreement into a pass, or a real pass into a disagreement, with no
# way afterwards to tell which happened.  Worse, the verdict this gate
# prints is what the checkpoint that follows it relies on: a `verify`
# that passed and a `commit` that ran are only evidence together if
# nothing changed in between.
#
# So the lock is taken EXCLUSIVELY, which excludes every shared producer,
# and it is held for the whole run through the EXIT trap.  A run started
# by run_pipeline.sh finds the sequencer's own exclusive hold already in
# place, proves it, and inherits it -- so the gate and the checkpoint the
# sequencer runs after it sit inside ONE window rather than two.
take_mutation_lock() {
    playthrough_acquire_mutation_lock exclusive ||
        die "${EX_BUSY}" "this gate could not take THIS checkout's" \
            "mutation lock exclusively, so the tree it would measure is" \
            "being written to while it reads.  A verdict taken over a" \
            "moving tree is not a measurement of anything, so no checks" \
            "were run and nothing was reported.  Wait for the session" \
            "step, producer or checkpoint that holds it and run this" \
            "again."
}

open_scratch() {
    local base="${PLAYTHROUGH_RUNTIME_DIR}"
    if [ ! -d "${base}" ]; then
        die "${EX_LAYOUT}" "the runtime directory '$(rel "${base}")'" \
            "does not exist; env.sh creates and verifies it at mode" \
            "0700, so re-source playthrough/tooling/env.sh"
    fi
    SCRATCH="$("${MKTEMP}" -d "${base}/${SCRATCH_PREFIX}XXXXXX")"
    if [ -z "${SCRATCH}" ] || [ ! -d "${SCRATCH}" ]; then
        die "${EX_LAYOUT}" "cannot create a scratch directory under" \
            "'$(rel "${base}")'"
    fi
    "${CHMOD}" 700 "${SCRATCH}"
    # THE OWNER, RECORDED INSIDE THE GENERATION.  It is what lets the
    # next run tell a generation whose audit is still working from one
    # whose audit was killed; see THE SCRATCH GENERATION above.
    # THE PID AND ITS START TIME, because a pid alone is not an identity:
    # Linux recycles them, so "the pid this file names is alive" and "the
    # process this file named is alive" are different claims, and the
    # sweep below acts on the answer by removing a directory.  The pair
    # is unique for the life of a boot.  A start time the kernel will not
    # report leaves the pid on its own, which is exactly the older
    # format's behaviour and is judged the same way.
    printf '%s %s\n' "$$" \
        "$(playthrough_proc_start_time "$$" || printf '')" \
        >"${SCRATCH}/${SCRATCH_OWNER_FILE}"
    sweep_stale_scratch "${base}"
    # THE DURABLE COPY STARTS HERE, one line behind stdout, so that every
    # verdict printed from this point on is also written down.  It is
    # assembled in the private scratch directory, where a half-written or
    # abandoned report cannot be mistaken for evidence, and copied out at
    # the end to the path the CALLER named with `--report-to` -- outside
    # the checkout, on every run, whatever the verdict.  Publishing it
    # inside the tree this gate measures is not a measurement's act; the
    # attestation checkpoint does that, and refuses a failing one.
    REPORT_FILE="${SCRATCH}/acceptance-report.md"
    : >"${REPORT_FILE}" || REPORT_FILE=""
    if [ -n "${REPORT_FILE}" ]; then
        "${CHMOD}" 600 "${REPORT_FILE}"
    fi
}

# owner_is_alive PID -- whether that process still exists.  Both tests
# are needed: `kill -0` answers "does it exist AND may I signal it",
# which is false for a live process belonging to somebody else, and
# /proc answers existence alone.  A generation is only ever removed when
# BOTH say it is gone, because the cost of being wrong in that direction
# is another audit's working directory.
owner_is_alive() {
    local pid="$1" recorded="${2-}" current=""
    if ! kill -0 "${pid}" 2>/dev/null && [ ! -d "/proc/${pid}" ]; then
        return 1
    fi
    # A RECORDED START TIME TURNS "a pid" INTO "that process".  Without
    # it, a recycled pid makes a killed audit's generation look live and
    # it is kept for ever; with it, the generation is correctly swept.
    # The check only ever moves the verdict in that direction: an
    # unreadable or absent start time falls back to existence alone,
    # which keeps the directory, and keeping somebody else's working
    # directory is the safe way to be wrong here.
    if [ -n "${recorded}" ]; then
        current="$(playthrough_proc_start_time "${pid}" || printf '')"
        if [ -n "${current}" ] && [ "${current}" != "${recorded}" ]; then
            return 1
        fi
    fi
    return 0
}

# scratch_is_stale DIR -- whether a generation with no live owner may be
# removed.  A generation that recorded no owner at all comes from a
# version of this file that did not write one, so it is judged by age.
scratch_is_stale() {
    local dir="$1"
    local owner="${dir}/${SCRATCH_OWNER_FILE}"
    local pid="" started="" modified="" now="${EPOCHSECONDS:-}"
    if [ -f "${owner}" ]; then
        # One line, "PID [STARTTIME]".  The second field is absent in the
        # format an older version of this file wrote, and a generation
        # from one of those is judged exactly as it was then.
        IFS=' ' read -r pid started <"${owner}" 2>/dev/null || pid=""
        case "${pid}" in
            ''|*[!0-9]*) pid="" ;;
        esac
        case "${started}" in
            ''|*[!0-9]*) started="" ;;
        esac
        if [ -n "${pid}" ]; then
            if owner_is_alive "${pid}" "${started}"; then
                return 1
            fi
            return 0
        fi
    fi
    # No usable owner.  Age is the only remaining evidence, and without a
    # clock the generation is LEFT ALONE: removing somebody else's
    # working directory on a guess is worse than leaving a stale one.
    if [ -z "${now}" ]; then
        return 1
    fi
    modified="$("${PLAYTHROUGH_UTIL_STAT:-stat}" -c '%Y' -- "${dir}" \
        2>/dev/null || printf '')"
    case "${modified}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ "$(( now - modified ))" -ge "${SCRATCH_STALE_SECONDS}" ]
}

# sweep_stale_scratch BASE -- remove the generations of audits that were
# killed outright.  Bounded to the mode-0700 runtime directory env.sh
# created and verified, matched on this file's own prefix, never
# following a symlink, and never touching this run's own generation:
# those four together are what make `rm -rf` acceptable here at all.
sweep_stale_scratch() {
    local base="$1"
    local dir="" removed=0
    for dir in "${base}/${SCRATCH_PREFIX}"*; do
        [ -d "${dir}" ] || continue
        [ ! -L "${dir}" ] || continue
        [ "${dir}" != "${SCRATCH}" ] || continue
        if scratch_is_stale "${dir}"; then
            "${RM}" -rf -- "${dir}" || continue
            removed=$(( removed + 1 ))
        fi
    done
    if [ "${removed}" -gt 0 ]; then
        playthrough_log "swept ${removed} scratch generation(s) left" \
            "behind by audits that were killed outright; a generation" \
            "whose owner is still running is never touched"
    fi
}

# publish_report
#   Write the captured report to its durable path in the working tree.
#
#   WHY THIS EXISTS.  A review found the gate streaming every verdict it
#   measured to stdout and then deleting its scratch directory on exit,
#   so the
#   acceptance evidence -- the ffprobe readings, the grayscale
#   statistics, the checkpoint ids, the no-cheat searches -- survived
#   only in whatever terminal happened to be attached.  Section 0.9 of
#   the plan is a set of gates whose satisfaction is meant to be
#   demonstrable rather than asserted, and a verdict nobody can re-read
#   is an assertion.  This publishes the report AS A TRACKED ARTIFACT so
#   that "the artifacts were verified" is itself a committed fact.
#
#   ONLY A PASSING RUN PUBLISHES.  A failing report is genuinely useful,
#   but it belongs on the operator's terminal and in the exit status, not
#   committed to the tree as though it were acceptance evidence -- and
#   leaving the PREVIOUS passing report in place while the tree is broken
#   would be worse still, so a failing run REMOVES a stale one rather
#   than letting it vouch for artifacts it never measured.
#   NOTHING HERE COUNTS A VERDICT.  publish_report runs after the totals
#   have been printed, so a record_info at this point would increment a
#   number the report has already stated and make the report disagree
#   with its own arithmetic.  Its lines are emitted with a REPORT prefix,
#   which reads as what it is: an act, not a measurement.
publish_report() {
    local target="" lines=""
    if [ -z "${REPORT_FILE}" ] || [ ! -f "${REPORT_FILE}" ]; then
        return 0
    fi
    target="$(report_publication_target)"
    if [ -z "${target}" ]; then
        printf 'REPORT  %s\n' "kept nowhere but this stream: pass \
'--report-to PATH' (outside the checkout) for a copy on disk.  \
Publishing it as a committed artifact is the attestation checkpoint's \
act, not this measurement's"
        return 0
    fi
    if ! "${CAT}" -- "${REPORT_FILE}" >"${target}" 2>/dev/null; then
        printf 'REPORT  could not be written to %s\n' "${target}"
        return 0
    fi
    # NOBODY ELSE MAY REWRITE THE REPORT.  The redirection above creates
    # the file under whatever umask this gate inherited, and a security
    # review measured the delivered acceptance report at mode 0666 -- an
    # audit record any local account could edit after it was signed off.
    # Read access is left alone: the report is committed and is meant to
    # be read.  A failure to tighten it is reported and does not fail the
    # run, because the verdict on the ARTIFACTS has already been printed
    # and a note about this file is not evidence about them.
    playthrough_deny_foreign_write "${target}" \
        "the published acceptance report" ||
        printf 'REPORT  %s\n' "could not be made unwritable by other \
accounts at ${target}; see the reason above"
    lines="$("${WC}" -l <"${target}" | "${TR}" -d ' ')"
    # THE OUTCOME IS NAMED BESIDE THE PATH, because this file is written
    # whether the run passed or failed.  It used to be written only on a
    # pass, which made its mere existence a verdict -- and a verdict
    # carried by a file's existence is one that a stale copy can tell.
    # The report states its own result in its VERIFY line, and the
    # attestation checkpoint is what refuses to commit a failing one.
    printf 'REPORT  %s\n' "${target} -- ${lines} lines, the verdict set \
this run measured (VERIFY $(if [ "${FAILURES}" -ne 0 ]; then \
printf 'fail'; elif [ "${DIVERGENCES}" -ne 0 ]; then \
printf 'pass-with-divergence'; else printf 'pass'; fi), phase \
'${PHASE}')"
}

# report_publication_target
#   The path this run will leave a copy of the report at, or nothing.
#
#   ONE PREDICATE, READ TWICE: by summarise_run, so the machine block
#   names the file and the file therefore contains its own path, and by
#   publish_report, which performs the copy.  Two independent conditions
#   would be a way for the report to name a file that was never written.
#
#   IT IS THE CALLER'S PATH AND NOTHING ELSE.  It used to be
#   playthrough/acceptance-report.txt unconditionally -- inside the tree
#   this gate measures, written after the checks that assert that tree is
#   clean and fully committed, and DELETED on a failing run.  Neither
#   direction belongs to a measurement: see the note in parse_arguments.
#   There is no phase condition on it either, because a phase decides
#   what was measured and the report says which phase that was; a caller
#   who asks for the report of a pre-commit run is entitled to it.
#
#   IT CANNOT FAIL, AND THAT IS THE POINT.  "Nowhere" is the ordinary
#   answer -- no `--report-to` is the default -- so it is reported the way
#   this function reports every answer: on stdout, as the empty string.
#   It used to say "nowhere" by RETURNING 1, and both callers capture it
#   in a command substitution under `set -e`.  One exempted the status
#   with `|| true` and the other did not, so a run that passed all 108 of
#   its checks printed `VERIFY=pass` and then died at the assignment in
#   publish_report -- the ERR trap naming a line in the one function whose
#   entire job is to be harmless.  A gate that reports a pass and exits 1
#   is worse than one that fails honestly, because the exit status is what
#   run_pipeline.sh reads: the sequencer refused to go on to the commit
#   while the report it was refusing said every artifact was sound.
#
#   The empty string carries the whole answer, so the status carries none
#   and no caller needs to remember to exempt it.  test_verify_artifacts.py
#   pins the absence of a failing return AND drives publish_report with no
#   destination under this file's own shell options, because the source
#   assertion alone could not prove the branch survives errexit.
report_publication_target() {
    if [ -z "${REPORT_FILE}" ] || [ ! -f "${REPORT_FILE}" ]; then
        return 0
    fi
    if [ -z "${REPORT_DESTINATION}" ]; then
        return 0
    fi
    printf '%s' "${REPORT_DESTINATION}"
}

# MEASURED_COMMIT -- resolved once, by main(), before the header is
# written.  The header states it in prose and the closing notes repeat it
# machine-readably; reading it twice would let those two disagree, and a
# report whose prose and whose notes named different trees would be
# worse than either of them alone.
MEASURED_COMMIT=""


# measured_commit -- WHICH TREE this report is about.
#
# Deliberately a commit and not a clock.  The durable report is a
# committed artifact, so anything in it that changes without the
# artifacts changing is churn in the history that carries no
# information.  A commit id is stable for a given tree, and it says
# something a timestamp cannot: exactly which evidence was read.
#
# AND IT MUST NOT CLAIM MORE THAN THAT.  A commit id describes the
# measurement only for as long as the working tree still IS that commit.
# Run this gate over modified sources -- the normal state while the gate
# itself is being repaired, and the normal state of a pre-commit run,
# whose entire purpose is to measure artifacts that are not committed
# yet -- and a bare `HEAD abc123` asserts that the evidence came out of
# a commit which does not contain it.
#
# That is the defect this was repaired for, and the repair is worth
# stating precisely because the arithmetic was never the problem: the
# committed report cited a HEAD and a check total that were both
# correctly DERIVED at the moment it ran, and both false by the time it
# was read, because nothing in it tied the numbers to the tree they came
# from.  A derived number is not the same thing as a true citation.
#
# So divergence is stated instead of assumed away.  The scope is
# playthrough/, matching check_nothing_uncommitted, because that one
# directory holds both the artifacts this gate reads AND the code doing
# the reading -- a modification to either means the report is not about
# the commit alone.  A clean tree, which is the state the closed
# lifecycle commits in, reads exactly as it did before, so the durable
# artifact never churns.
measured_commit() {
    local head="" dirty=""
    head="$("${GIT}" rev-parse --short=10 HEAD 2>/dev/null || true)"
    if [ -z "${head}" ]; then
        printf 'a tree with no commits yet'
        return 0
    fi
    dirty="$("${GIT}" status --porcelain -uall -- \
        "${PLAYTHROUGH_DIR}" 2>/dev/null | "${GREP}" -c . || true)"
    if [ "${dirty:-0}" -ne 0 ]; then
        printf 'HEAD %s plus %s uncommitted path(s) under %s' \
            "${head}" "${dirty}" "$(rel "${PLAYTHROUGH_DIR}")"
        return 0
    fi
    printf 'HEAD %s' "${head}"
}


# ---------------------------------------------------------------------
# 1  THE MEASURING ENVIRONMENT
#
# A gate has to establish that it can measure before it reports what it
# measured.  A missing tool is a FAILURE of the gate and not a reason to
# stop: the remaining groups still run, and the ones that needed the
# absent tool fail individually and say so.
# ---------------------------------------------------------------------
# resolve_tools -- resolve and verify EVERY external command, before the
# scratch directory exists.
#
# It runs first in main(), ahead of open_scratch, because open_scratch is
# itself built out of mktemp and chmod: resolving after it would leave two
# of the gate's own tools unverified and invoked by bare name, which is
# precisely the gap a review found.  Nothing is printed here -- the report
# has not started -- so the outcome is kept and reported as a verdict by
# check_tool_inventory in group 1.
resolve_tools() {
    local -a wanted=()
    read -r -a wanted <<<"${REQUIRED_COMMANDS}"
    if playthrough_require_tools "${wanted[@]}"; then
        TOOLS_RESOLVED=1
        TOOLS_DETAIL="${wanted[*]}"
    else
        TOOLS_RESOLVED=0
        TOOLS_DETAIL="playthrough_require_tools refused; the reason for \
each is on stderr"
    fi
    # Whatever was resolved is used; whatever was not falls back to the
    # bare name so that `set -u` cannot trip and the individual checks
    # fail on their own terms.
    FFPROBE="${PLAYTHROUGH_BIN_FFPROBE:-ffprobe}"
    FFMPEG="${PLAYTHROUGH_BIN_FFMPEG:-ffmpeg}"
    CONVERT="${PLAYTHROUGH_BIN_CONVERT:-convert}"
    IDENTIFY="${PLAYTHROUGH_BIN_IDENTIFY:-identify}"
    COMPARE="${PLAYTHROUGH_BIN_COMPARE:-compare}"
    GIT="${PLAYTHROUGH_BIN_GIT:-git}"
    AWK="${PLAYTHROUGH_BIN_AWK:-awk}"
    GREP="${PLAYTHROUGH_BIN_GREP:-grep}"
    SED="${PLAYTHROUGH_BIN_SED:-sed}"
    HEAD="${PLAYTHROUGH_BIN_HEAD:-head}"
    TAIL="${PLAYTHROUGH_BIN_TAIL:-tail}"
    TR="${PLAYTHROUGH_BIN_TR:-tr}"
    SORT="${PLAYTHROUGH_BIN_SORT:-sort}"
    WC="${PLAYTHROUGH_BIN_WC:-wc}"
    CAT="${PLAYTHROUGH_BIN_CAT:-cat}"
    RM="${PLAYTHROUGH_BIN_RM:-rm}"
    MKTEMP="${PLAYTHROUGH_BIN_MKTEMP:-mktemp}"
    CHMOD="${PLAYTHROUGH_BIN_CHMOD:-chmod}"
    FIND="${PLAYTHROUGH_BIN_FIND:-find}"
    BASENAME="${PLAYTHROUGH_BIN_BASENAME:-basename}"
    CUT="${PLAYTHROUGH_BIN_CUT:-cut}"
    TIMEOUT="${PLAYTHROUGH_BIN_TIMEOUT:-timeout}"
}

# check_tool_inventory -- the verdict on the resolution main() already
# performed.  Reported in group 1, where a reader looks for it.
check_tool_inventory() {
    if [ "${TOOLS_RESOLVED}" -eq 1 ]; then
        record_pass "every command this gate invokes is present, \
verified and called by its resolved path" "${TOOLS_DETAIL}"
        return 0
    fi
    record_fail "every command this gate invokes is present, verified \
and called by its resolved path" \
        "${TOOLS_DETAIL}" \
        "${REQUIRED_COMMANDS} -- apt: ffmpeg, imagemagick, git, \
coreutils, findutils, grep, sed, mawk -- each owned by this user or \
root and not group- or world-writable, resolved BEFORE the scratch \
directory is opened because mktemp and chmod are what open it"
}

# THE IMAGEMAGICK ENTRY POINT.  `convert`, `identify` and `compare` are
# the classic names and exist on both the version 6 and the version 7
# branches; the unified `magick` name exists only on 7, so anything
# written against it dies with command-not-found on a 6 host.  This gate
# calls the classic names and NEVER `magick`, and records which branch it
# is talking to so a reader of the report knows.
check_imagemagick() {
    local version=""
    version="$(bounded "${BOUND_PROBE_SECONDS}" "${CONVERT}" --version \
        2>"$(tool_error_file convert)" | "${HEAD}" -n 1 || true)"
    if [ -z "${version}" ]; then
        record_fail "ImageMagick answers through its classic entry \
points" \
            "'${CONVERT}' produced no version banner$(because convert)" \
            "convert, identify and compare callable (apt: imagemagick)"
        return 0
    fi
    record_pass "ImageMagick answers through its classic entry points \
(convert, identify, compare -- never the version-7-only 'magick')" \
        "${version}"
}

check_interpreter() {
    local version=""
    version="$(bounded "${BOUND_PROBE_SECONDS}" "${PYTHON}" -B -c \
        'import sys; print(sys.version.split()[0])' 2>/dev/null || true)"
    if [ -z "${version}" ]; then
        record_fail "the verified interpreter runs" \
            "'${PYTHON}' would not report its version" \
            "the interpreter env.sh resolved, able to execute"
        return 0
    fi
    record_pass "the verified interpreter runs" \
        "${version} at $(rel "${PYTHON}")"
}

# THE DEPENDENCY CLOSURE, MEASURED RATHER THAN ASSUMED.
#
# The check above establishes that an interpreter runs, which a review
# rightly said is not the closure: it says nothing about whether any of
# the six declared libraries is installed, at what version, or whether
# the graph beneath them is intact.  Section 0.9.1's R9 gate is that the
# requirements file "resolves cleanly", and the exact `==` pins exist so
# that a release cannot silently change the rendered film while every
# gate still reports green -- which is precisely what an unmeasured
# closure allows.
#
# The program is env.sh's, not this file's, because run_pipeline.sh must
# refuse to produce artifacts under a broken closure and two
# implementations of one assertion is how they come to disagree.  Here it
# is consumed as five verdicts and one inventory note, through the same
# channel as every other Python checker.
check_dependency_closure() {
    local script="${SCRATCH}/closure.py"
    if ! playthrough_write_closure_checker "${script}"; then
        # ONE FAILURE PER DECLARED VERDICT, so a gate that cannot run
        # this checker reports the same eight properties as unmeasured
        # rather than reporting seven fewer checks than it declares.
        #
        # THESE NAMES MUST MATCH THE CHECKER'S OWN, BYTE FOR BYTE.  They
        # are the fallback for a checker that could not be written, so
        # they stand in for verdicts that would otherwise be absent; a
        # name that drifted would report a property nothing measures
        # under a name nothing else uses.  test_verify_artifacts.py
        # asserts the correspondence.
        local name=""
        for name in \
            "the interpreter is the CPython \
${PLAYTHROUGH_PYTHON_ABI} the lock was built for" \
            "the declaration and the lock pin the same versions" \
            "every declared library is installed at its declared \
version" \
            "every declared library imports" \
            "every installed distribution has its own requirements \
met" \
            "the render stack still forces the Pillow pin it is held \
at" \
            "nothing is installed that requirements.lock does not \
name" \
            "nothing runs at interpreter startup that was not \
allowed"; do
            record_fail "${name}" \
                "the shared closure checker could not be written to \
the scratch directory, so nothing about the closure was measured" \
                "a writable scratch directory under the runtime root"
        done
        return 0
    fi
    # NOT run_checker, and for one specific reason: this program EXITS
    # NON-ZERO when a closure verdict failed, because run_pipeline.sh
    # needs that status to refuse the run.  run_checker reads any
    # non-zero exit as a crash of the checker, which would add a spurious
    # "the closure checks completed" failure on top of every genuine
    # closure failure.  So a crash is distinguished by its own evidence
    # instead: a traceback on stderr, or no verdicts at all.
    local out="${SCRATCH}/closure.verdicts"
    local err="${SCRATCH}/closure.stderr"
    local detail=""
    : >"${out}"
    : >"${err}"
    # BOUNDED like every other interpreter child.  The status is
    # deliberately discarded rather than inspected -- see above for why a
    # non-zero exit is a closure verdict rather than a crash -- so an
    # expiry surfaces as the "no verdicts at all" condition below, which
    # is the honest reading of a closure that could not be measured.
    bounded "$(checker_bound)" "${PYTHON}" -B "${script}" \
        "${VERDICT_SEPARATOR}" \
        "${PLAYTHROUGH_REQUIREMENTS}" \
        "${PLAYTHROUGH_REQUIREMENTS_LOCK}" \
        >"${out}" 2>"${err}" || true
    if [ -s "${err}" ] || [ ! -s "${out}" ]; then
        detail="$("${TAIL}" -n 3 "${err}" 2>/dev/null |
            "${TR}" '\n' ' ' || true)"
        record_fail "the dependency closure was measurable" \
            "the shared closure checker did not complete: \
${detail:-<no diagnostic and no verdicts>}" \
            "a clean run emitting one verdict per closure property"
    fi
    consume_verdicts <"${out}"
}

# THE LINTER, RESOLVED IN FOUR STEPS.  The repository's own contract is a
# bare `flake8` (Makefile:1648-1649), so that is preferred; an explicit
# override wins over everything, and an importable module is accepted
# because a virtual environment often installs it that way.  If none of
# the four resolves, the lint check FAILS rather than being skipped, and
# says what to do about it.
#
# INSIDE THE DECLARED CONTAINER, ONLY THE FIRST THREE STEPS CAN FIRE, AND
# ONE OF THEM MUST.  supported_env.sh's docker_run passes exactly HOME,
# TMPDIR, the cleared trust-bypass names and the image's own environment;
# PLAYTHROUGH_FLAKE8 IS NOT AMONG THEM, so exporting it on the host has
# no effect on a `supported_env.sh run` of this gate.  The linter has to
# be discoverable from INSIDE the image -- on its PATH, or importable by
# the interpreter env.sh resolves there.  That is why the image installs
# flake8 into its own environment and exposes it on PATH, which is the
# same shape this host uses (/usr/local/bin/flake8 -> a dedicated venv),
# and why an image without it makes the lint check FAIL rather than
# quietly not run.
# NOTHING IS EXECUTED BEFORE IT IS VERIFIED, INCLUDING THE PROBE.
#
# A review found this resolver accepting PLAYTHROUGH_FLAKE8 on the
# strength of a successful `--version`, which is not a check but the
# first execution: by the time the exit status came back, an arbitrary
# path taken from the environment had already run as this user, and it
# would run again over every file under playthrough/ with its findings
# read as the repository's lint verdict.  Ownership and writability are
# the properties that matter and they are knowable WITHOUT running
# anything, so they are established first, through env.sh's own
# verifier -- the same one the twenty-three commands in group 1 pass
# through, so the linter is no longer the single tool held to a weaker
# standard than `cut`.
#
# EACH CANDIDATE IS REDUCED TO THE EXECUTABLE IT WOULD ACTUALLY RUN
# before that verifier sees it.  For the two module forms the executable
# is the INTERPRETER -- `flake8` is then an importable module inside it,
# reachable only by an account that could already rewrite the
# interpreter's own library -- so the interpreter is what gets verified.
# A candidate that fails is REFUSED AND NAMED rather than silently
# skipped: an operator who exported an override is told their override
# was rejected and why, instead of reading a report that quietly linted
# with something else.
verify_flake8_candidate() {
    local path="$1"
    local label="$2"
    if playthrough_verify_executable "${path}" "${label}"; then
        return 0
    fi
    FLAKE8_REJECTED="${FLAKE8_REJECTED}${FLAKE8_REJECTED:+; }\
${label} '${path}' failed executable verification (ownership or \
writability -- see stderr)"
    return 1
}

resolve_flake8() {
    local version="" candidate=""
    FLAKE8_REJECTED=""
    # The override is verified BEFORE it is probed, and a probe failure
    # after a clean verification is reported as a linter that will not
    # run rather than as a lint finding -- which is what an unvalidated
    # override was measured to produce (exit 127, "No such file").
    if [ -n "${PLAYTHROUGH_FLAKE8:-}" ]; then
        if verify_flake8_candidate "${PLAYTHROUGH_FLAKE8}" \
                "PLAYTHROUGH_FLAKE8" &&
                bounded "${BOUND_PROBE_SECONDS}" \
                "${PLAYTHROUGH_FLAKE8}" --version \
                >/dev/null 2>&1; then
            FLAKE8_CMD=("${PLAYTHROUGH_FLAKE8}")
        else
            FLAKE8_CMD=()
            record_info "the linter" \
                "PLAYTHROUGH_FLAKE8='${PLAYTHROUGH_FLAKE8}' was not \
accepted (${FLAKE8_REJECTED:-it would not run}), so the lint check in \
group 9 reports the linter as unresolved. An override is not a way \
round verification: point it at an executable this account owns, under \
directories no other account can write"
            return 0
        fi
    elif candidate="$(command -v flake8 2>/dev/null)" &&
            [ "${candidate#/}" != "${candidate}" ] &&
            verify_flake8_candidate "${candidate}" "flake8" &&
            bounded "${BOUND_PROBE_SECONDS}" \
            "${candidate}" --version >/dev/null 2>&1; then
        FLAKE8_CMD=("${candidate}")
    elif verify_flake8_candidate "${PYTHON}" \
            "the verified interpreter" &&
            bounded "${BOUND_PROBE_SECONDS}" \
            "${PYTHON}" -B -m flake8 --version \
            >/dev/null 2>&1; then
        FLAKE8_CMD=("${PYTHON}" -B -m flake8)
    elif candidate="$(command -v python3 2>/dev/null)" &&
            [ "${candidate#/}" != "${candidate}" ] &&
            verify_flake8_candidate "${candidate}" "python3" &&
            bounded "${BOUND_PROBE_SECONDS}" \
            "${candidate}" -B -m flake8 --version \
            >/dev/null 2>&1; then
        FLAKE8_CMD=("${candidate}" -B -m flake8)
    else
        FLAKE8_CMD=()
        record_info "the linter" \
            "not resolved${FLAKE8_REJECTED:+ (${FLAKE8_REJECTED})} -- \
the lint check in group 9 reports it"
        return 0
    fi
    version="$(bounded "${BOUND_PROBE_SECONDS}" "${FLAKE8_CMD[@]}" \
        --version 2>/dev/null | "${TR}" '\n' ' ' || true)"
    record_info "the linter" \
        "${FLAKE8_CMD[*]} -- ${version:-version unavailable}\
${FLAKE8_REJECTED:+ (after refusing: ${FLAKE8_REJECTED})}"
}

# THE TRUST STATE, SPLIT BY WHAT EACH BYPASS ACTUALLY ENDANGERS.
#
# env.sh registers every diagnostic escape hatch and moves the state to
# "diagnostic" when any of them is set.  For a stage that RECORDS
# evidence, any of them is disqualifying -- launch_game.sh and capture.sh
# refuse outright, and they are right to.  This stage only READS
# committed evidence, and the bypasses do not all mean the same thing
# here:
#
#   * A CAPTURE-TIME bypass says the evidence itself may be tainted: an
#     unverified interpreter or tool decided the readings, an
#     unauthenticated X server let another account type into the session,
#     the artwork came from somewhere this host cannot vouch for, or the
#     run may have rendered a tileset other than the required one.  Those
#     remain FAILURES, because they bear on what is being judged.
#
#   * A PLATFORM bypass says the host doing the reading is past its
#     security support date.  That is worth saying out loud and it
#     changes nothing about the bytes in the tree -- report_platform
#     below already treats the same condition as information for exactly
#     this reason, since "auditing a committed tree on whatever host is
#     to hand is legitimate".  Failing the run on it would report a
#     defect in a correct artifact set, which is the one thing an
#     acceptance gate must never do; and the project's own setup guidance
#     tells operators to export that waiver for host-side stages, so the
#     old behaviour turned following the instructions into a failure.
#
# An inability to VERIFY (PLAYTHROUGH_TRUST_UNVERIFIED) stays a failure
# too: a check that could not run is not a check that passed.
readonly PLATFORM_CLASS_BYPASSES="PLAYTHROUGH_ALLOW_EOL_PLATFORM"

check_trust_state() {
    local name="" active="" evidential="" platform=""
    if playthrough_trust_refresh; then
        record_pass "the environment doing the measuring is trusted" \
            "PLAYTHROUGH_TRUST_STATE=${PLAYTHROUGH_TRUST_STATE}"
        return 0
    fi
    active="${PLAYTHROUGH_TRUST_BYPASSES:-}"
    for name in ${active}; do
        case " ${PLATFORM_CLASS_BYPASSES} " in
            *" ${name} "*)
                platform="${platform}${platform:+ }${name}"
                ;;
            *)
                evidential="${evidential}${evidential:+ }${name}"
                ;;
        esac
    done
    if [ -z "${evidential}" ] &&
            [ -z "${PLAYTHROUGH_TRUST_UNVERIFIED:-}" ]; then
        record_warn "the environment doing the measuring" \
            "${platform} is set, which says this HOST is past its \
security support date and nothing about the committed artifacts; this \
gate reads evidence and writes nothing, so it is reported rather than \
failed.  A capture-time bypass would fail here instead"
        record_pass "the environment doing the measuring is trusted" \
            "no capture-time bypass is set; the only relaxation in \
force (${platform}) bears on the host doing the reading, not on the \
evidence being read"
        return 0
    fi
    playthrough_trust_explain || true
    record_fail "the environment doing the measuring is trusted" \
        "PLAYTHROUGH_TRUST_STATE=${PLAYTHROUGH_TRUST_STATE:-unknown} \
(${evidential:-${active}}\
${PLAYTHROUGH_TRUST_UNVERIFIED:+; ${PLAYTHROUGH_TRUST_UNVERIFIED}})" \
        "no capture-time bypass set and nothing left unverified -- an \
unverified tool or interpreter decides every reading in the film, an \
unauthenticated X server lets another account type into the session, \
and an unverified or substituted tileset pack changes the artwork the \
whole film is rendered in.  Evidence produced or measured under a \
relaxed check is not evidence"
}

# THE VIDEO DRIVER, AND WHOSE IT IS.
#
# This verdict is about THE PROCESS DOING THE MEASURING and says nothing
# about the session that was recorded -- and it now says so in its own
# name, because the earlier wording ("the video driver contract is x11
# and not dummy") read as a statement about the recording and could never
# fail: env.sh exports SDL_VIDEODRIVER=x11 unconditionally, so the check
# was reading back a value this file had set a few lines earlier.  Running
# the gate with SDL_VIDEODRIVER=dummy in the caller's environment
# produced a serene pass.
#
# What is asserted is therefore the real property: that the environment
# contract IS in force in this process, which fails if env.sh is edited
# or replaced by something that does not establish it.  The caller's
# inherited value is reported beside it, and warned about when it was
# `dummy`, since an operator whose shell is set that way is one step away
# from recording a black film.
#
# WHAT DOES JUDGE THE RECORDING is elsewhere and is named here so a
# reader knows where to look: group 6 reads the grayscale statistics of
# every committed capture and of frames decoded out of both films, and
# group 9 reads the tileset the engine logged loading at capture time.
# Those are measurements of the evidence; this is a statement about the
# audit.
check_video_driver() {
    local inherited="${_VA_INHERITED_VIDEODRIVER:-<unset>}"
    if [ "${_VA_INHERITED_VIDEODRIVER:-}" = "dummy" ]; then
        record_warn "the video driver in the caller's environment" \
            "SDL_VIDEODRIVER=dummy was inherited by this process.  It \
has no bearing on the committed artifacts -- env.sh overrides it with \
x11 and this gate renders nothing -- but a capture run started from \
this shell would photograph zero pixels, so the value is worth seeing"
    fi
    if [ "${SDL_VIDEODRIVER:-}" = "x11" ]; then
        record_pass "this audit process runs under the x11 video driver \
contract, never dummy (a statement about the audit, not about the \
recorded session)" \
            "SDL_VIDEODRIVER=${SDL_VIDEODRIVER} in force here, \
inherited as ${inherited}; whether the RECORDED session rendered real \
pixels is measured in group 6 from the captures and the films \
themselves, and the artwork it rendered in group 9 from the engine's own \
log"
        return 0
    fi
    record_fail "this audit process runs under the x11 video driver \
contract, never dummy (a statement about the audit, not about the \
recorded session)" \
        "SDL_VIDEODRIVER=${SDL_VIDEODRIVER:-<unset>} after sourcing \
env.sh (inherited as ${inherited})" \
        "x11 -- env.sh establishes this contract unconditionally, so \
anything else here means the environment contract was not established \
and every tool resolution and path in this run is suspect"
}

# The platform verdict is INFORMATION here, not a verdict on the
# artifacts.  playthrough_check_platform refuses on an end-of-life
# release, which is right for a stage that RECORDS evidence and wrong for
# one that only reads it -- auditing a committed tree on whatever host is
# to hand is legitimate.  Its diagnosis is suppressed and its finding
# reported, exactly as playthrough_env_summary does.
report_platform() {
    playthrough_check_platform >/dev/null 2>&1 || true
    record_info "the host this gate ran on" \
        "${PLAYTHROUGH_PLATFORM:-unknown} \
(supported=${PLAYTHROUGH_PLATFORM_SUPPORTED:-unchecked}, \
eol=${PLAYTHROUGH_PLATFORM_EOL:-unknown})"
    if [ "${PLAYTHROUGH_PLATFORM_SUPPORTED:-}" = "no" ]; then
        record_warn "the host this gate ran on" \
            "this release is past end of life; that does not change \
what the committed artifacts are, but a session must not be RECORDED \
here -- see playthrough/tooling/supported_env.sh"
    fi
}

# Presence is established once, before anything tries to parse or probe,
# so that a missing film is reported as a missing film rather than as
# nine confusing failures in the groups that would have read it.
check_artifacts_present() {
    local -a missing=()
    local -a present=()
    local entry="" path="" kind=""
    local -a inventory=(
        "d:${PLAYTHROUGH_FRAMES_DIR}"
        "d:${PLAYTHROUGH_TRANSITIONS_DIR}"
        "d:${PLAYTHROUGH_SAVE_DIR}"
        "f:${PLAYTHROUGH_MANIFEST}"
        "f:${PLAYTHROUGH_TIMELINE}"
        "f:${PLAYTHROUGH_CONCAT_LIST}"
        "f:${PLAYTHROUGH_MOVIE}"
        "f:${PLAYTHROUGH_MOVIE_CC}"
        "f:${PLAYTHROUGH_TRANSCRIPT_SRT}"
        "f:${PLAYTHROUGH_TRANSCRIPT_MD}"
        "f:${PLAYTHROUGH_DOSSIER}"
        "f:${PLAYTHROUGH_REQUIREMENTS}"
    )
    for entry in "${inventory[@]}"; do
        kind="${entry%%:*}"
        path="${entry#*:}"
        if [ "${kind}" = "d" ]; then
            if [ -d "${path}" ] && [ -r "${path}" ]; then
                present+=("$(rel "${path}")")
            else
                missing+=("$(rel "${path}")")
            fi
        elif [ -f "${path}" ] && [ -r "${path}" ]; then
            present+=("$(rel "${path}")")
        else
            missing+=("$(rel "${path}")")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_pass "every artifact this gate reads is present and \
readable" "${#present[@]} paths, all of them readable"
        return 0
    fi
    record_fail "every artifact this gate reads is present and \
readable" \
        "absent or unreadable: ${missing[*]}" \
        "all 12 artifact paths named in env.sh -- the render stages \
(timeline.py, make_transitions.py, render_movie.py, make_srt.py, \
embed_captions.sh) produce the generated ones"
}

group_environment() {
    group 1 "the measuring environment"
    check_tool_inventory
    check_imagemagick
    check_interpreter
    check_dependency_closure
    resolve_flake8
    check_trust_state
    check_video_driver
    report_platform
    check_artifacts_present
}


# ---------------------------------------------------------------------
# 2  ONE FRAME PER KEYSTROKE
#
# The headline invariant of the whole subsystem: exactly one capture per
# keystroke, exactly one record row per capture.  It is asserted as an
# IDENTITY between two independently produced counts, which is what makes
# an unpaired frame impossible to overlook -- and it is the reason the
# derived transition images live in playthrough/build/transitions/ and
# never in playthrough/frames/, because mixing them in would destroy the
# very count this check rests on.
#
# The six-key schema comes from manifest.py's own FIELDS tuple and the
# canonical filename from its own frame_file(), so the committed record
# is held to exactly the contract its producer enforces on a new row
# rather than to a second description of it written here.
# ---------------------------------------------------------------------
emit_record_checker() {
    emit_checker record <<'PY'
"""Assert the capture/record pairing over the committed artifacts."""

import datetime
import json
import os
import re
import sys

SEP = "\x1f"
FRAME_RE = re.compile(r"^frame_([0-9]{5})\.png$")

# The bounds the real-time span is judged against.  Internal on purpose:
# see check_timestamps for why the auditing host's clock is not consulted.
MAX_SESSION_SECONDS = 30 * 86400
EARLIEST_LABEL = "2020-01-01T00:00:00Z"
EARLIEST_PLAUSIBLE = datetime.datetime(
    2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()

# How long after its row a capture may be attested.  The digest is taken
# immediately after the frame is written, so this is generous by design:
# the widest gap in the committed session is about 25 s.
ATTESTATION_WINDOW_SECONDS = 300


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def summarise(items, limit=6):
    """A bounded, readable rendering of a list of findings."""
    shown = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += ", ... (%d more)" % (len(items) - limit)
    return shown


# HOW MANY FINDINGS ONE VERDICT COLLECTS.
#
# The record is one row per keystroke and the session length is
# deliberately unbounded, so a record broken at every row -- a schema
# change, a regenerated file, a whole session re-recorded -- would
# otherwise put one diagnostic string per keystroke into memory to
# explain a failure whose first example already explains it.
PROBLEM_LIMIT = 200


def note_problem(problems, text, limit=PROBLEM_LIMIT):
    """Collect a finding, bounded.

    Past the limit a single line records that collection stopped, so a
    verdict never claims to be exhaustive when it is not.
    """
    if len(problems) < limit:
        problems.append(text)
        return
    if len(problems) == limit:
        problems.append("... further findings were not collected; the "
                        "%d above are the ones this verdict carries"
                        % limit)


class RowIndex(object):
    """The one compact projection of the record this checker keeps.

    THE RECORD IS STREAMED, one line at a time, and no row survives the
    iteration that read it -- see main() for why.  Two later checks
    nevertheless ask questions ACROSS rows: the timeline's copy of each
    row must agree with the row (real_ts and the clock reading), and the
    capture-digest sidecar's attestation must sit just after its row's
    instant.  Both are keyed by frame number.

    So exactly three values per row are kept -- the parsed instant, the
    timestamp as written, and the clock reading -- and nothing else.  A
    row of the record is about a kilobyte of interpreter objects; an
    entry here is a tuple of two short strings and a float, which is what
    makes "one entry per keystroke" affordable at a session length nobody
    has bounded.  The row's action and commentary, which are the bulk of
    it, are read, judged and dropped as they stream past.
    """

    __slots__ = ("moments", "order")

    def __init__(self):
        self.moments = {}
        self.order = []

    def add(self, frame, line_number, moment, written, clock):
        self.moments[frame] = (moment, written, clock)
        self.order.append((frame, line_number))

    def __len__(self):
        return len(self.order)

    def instant(self, frame):
        entry = self.moments.get(frame)
        return None if entry is None else entry[0]

    def written(self, frame):
        entry = self.moments.get(frame)
        return None if entry is None else entry[1]

    def clock(self, frame):
        entry = self.moments.get(frame)
        return None if entry is None else entry[2]

    def has(self, frame):
        return frame in self.moments


def main(argv):
    (manifest_path, frames_dir, tooling_dir, facts_path, timeline_path,
     digests_path, in_game_path) = argv[1:8]
    sys.path.insert(0, tooling_dir)
    import manifest as mf

    facts = open(facts_path, "a", encoding="utf-8")

    # --- the record, STREAMED -----------------------------------------
    #
    # It used to be read whole -- read().splitlines() -- and then held
    # twice over: the raw lines, and a parsed dict per row.  One row per
    # keystroke at ~1 kB of interpreter objects means a hundred thousand
    # keystrokes is hundreds of megabytes resident on a host with under
    # four gigabytes, for a walk that never looks backwards.
    #
    # So every property below is decided as its row arrives: the counters
    # accumulate, the findings are bounded, and the only thing that
    # outlives a row is the three-value projection in RowIndex that two
    # cross-artifact checks genuinely need.
    wanted = tuple(mf.FIELDS)
    line_count = 0
    rows = 0
    unparsable = []
    wrong_keys = []
    empty = []
    mislabelled = []
    numbering = []
    index = RowIndex()
    stamps_unparsable = []
    backwards = []
    previous_instant = None
    previous_written = None
    oldest = None
    newest = None
    usable_stamps = 0
    clock_kinds = {}
    # WHICH CAPTURES SHOW THE GAME BEING PLAYED, WRITTEN AS A FILE.
    #
    # A frame whose sidebar clock was legible is a frame of the play
    # screen rather than of a menu, a loading screen or the character
    # creator, and group 9's colour-depth reading needs exactly that
    # distinction: an ASCII session's menus and a tiles session's menus
    # look alike, and only the map is drawn from the tileset.
    #
    # It used to be published as a fact -- one KEY=value line holding a
    # comma-separated list of every in-game frame -- which the shell then
    # read into a variable and piped twice.  One index per keystroke in a
    # single line is a fact whose length is the session's, and a value of
    # that shape is one argument away from MAX_ARG_STRLEN.  One index per
    # LINE in the scratch generation is bounded by the disk and is
    # sampled by line number without any of it being held.
    in_game = open(in_game_path, "w", encoding="utf-8")
    referenced = 0
    with open(manifest_path, "r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line_count = number
            line = raw.rstrip("\n")
            if not line.strip():
                note_problem(unparsable, "line %d is blank" % number)
                continue
            try:
                pairs = json.loads(line, object_pairs_hook=lambda kv: kv)
            except ValueError as err:
                note_problem(unparsable, "line %d: %s" % (number, err))
                continue
            if not isinstance(pairs, list):
                note_problem(unparsable,
                             "line %d is not a JSON object" % number)
                continue
            if tuple(k for k, _ in pairs) != wanted:
                note_problem(wrong_keys, str(number))
            row = dict(pairs)
            rows += 1
            for field in ("action", "commentary"):
                value = row.get(field)
                if not isinstance(value, str) or not value.strip():
                    note_problem(empty, "row %d %s" % (number, field))
            frame = row.get("frame")
            if frame != rows:
                note_problem(numbering, "position %d carries %r"
                             % (rows, frame))
            try:
                canonical = mf.frame_file(frame)
            except Exception as err:                 # noqa: BLE001
                canonical = None
                note_problem(mislabelled, "frame %r: %s" % (frame, err))
            if canonical is not None and row.get("file") != canonical:
                note_problem(mislabelled, "%r != %s"
                             % (row.get("file"), canonical))
            if row.get("file"):
                referenced += 1
            # --- when it was taken ---------------------------------
            written = row.get("real_ts")
            moment = parse_instant(written)
            if moment is None:
                note_problem(stamps_unparsable,
                             "row %d: %r" % (number, written))
            else:
                usable_stamps += 1
                if previous_instant is not None and \
                        moment < previous_instant:
                    note_problem(backwards,
                                 "row %d is %s, after %s"
                                 % (number, written, previous_written))
                previous_instant = moment
                previous_written = written
                if oldest is None or moment < oldest[0]:
                    oldest = (moment, number, written)
                if newest is None or moment > newest[0]:
                    newest = (moment, number, written)
            index.add(frame, number, moment, written,
                      row.get("ingame_clock"))
            # --- the clock reading, as honesty ----------------------
            value = row.get("ingame_clock")
            if value is None:
                kind = "not readable (null)"
            elif isinstance(value, str) and CLOCK_RE.match(value):
                kind = "exact"
                if isinstance(frame, int):
                    in_game.write("%d\n" % frame)
            else:
                kind = "verbatim coarse phrase"
            clock_kinds[kind] = clock_kinds.get(kind, 0) + 1
    in_game.close()

    if unparsable:
        bad("the record parses as one JSON object per line",
            summarise(unparsable),
            "%d lines, each a JSON object" % line_count)
    else:
        ok("the record parses as one JSON object per line",
           "%d rows" % rows)

    # EXACTLY the six documented keys, IN ORDER, and no extras.  The
    # tuple is manifest.py's own, so this cannot drift from the producer.
    if wrong_keys:
        bad("every row carries exactly the six documented keys, in "
            "order, and no others",
            "rows with a different key set or order: %s"
            % summarise(wrong_keys),
            "%s" % ", ".join(wanted))
    else:
        ok("every row carries exactly the six documented keys, in "
           "order, and no others", ", ".join(wanted))

    # NON-EMPTINESS, NAMED AS NON-EMPTINESS.  This verdict used to be
    # called "every row records what was pressed and why", which read as
    # a verdict on the narration -- and it is not one: "Swing." against
    # the action `press '2' -- swing` is non-empty and explains nothing.
    # The rationale contract is the check below; this one is the floor
    # beneath it and now says only what it measures.  The offending rows
    # are collected by the streaming walk above, one row at a time, so
    # nothing is held to answer it.
    if empty:
        bad("every row carries an action and a sentence about it",
            summarise(empty),
            "a non-empty action and a non-empty commentary on all "
            "%d rows" % rows)
    else:
        ok("every row carries an action and a sentence about it",
           "%d actions and %d commentaries, none empty" % (rows, rows))

    check_rationale(manifest_path, timeline_path)

    if numbering:
        bad("the record's frame numbers are 1-based and contiguous",
            "first divergence at %s" % summarise(numbering),
            "1 .. %d with no gap and no repeat" % rows)
    else:
        ok("the record's frame numbers are 1-based and contiguous",
           "1 .. %d" % rows if rows else "no rows")

    # Each row must name ITS OWN frame, formatted from its own index by
    # the producer's own formatter.
    if mislabelled:
        bad("every row names its own capture canonically",
            summarise(mislabelled),
            "playthrough/frames/frame_%05d.png formatted from the row's "
            "own frame number")
    else:
        ok("every row names its own capture canonically",
           "%d rows match %s" % (rows, mf.FRAME_FILE_FORMAT))

    check_timestamps(index, rows, stamps_unparsable, backwards,
                     usable_stamps, oldest, newest, timeline_path,
                     digests_path)

    return finish(index, rows, line_count, referenced, clock_kinds,
                  frames_dir, facts)


# ---------------------------------------------------------------------
# THE RATIONALE CONTRACT
#
# The requirement is that every entry says WHY the survivor pressed the
# key, and "why" is not a property a program can read out of a sentence.
# What a program CAN do is falsify the ways a sentence fails to be one,
# and the review that raised this found the exact failures by hand:
# "Swing." beside `press '2' -- swing`, and "Again." repeated down a run
# of eleven keystrokes.  Both were reported as satisfying the
# requirement, because the only thing measured was that the string was
# not empty.
#
# THE SUBJECT IS THE ENTRY'S WHOLE NARRATION -- the action's own note AND
# the commentary -- and that is a correction made by measurement rather
# than a relaxation.  The contract was first written against a record
# whose action notes were mechanical (`press '2' -- swing`), so
# "commentary that adds no word its action does not carry" was a fair
# proxy for "commentary that explains nothing".  Measured against a
# record whose notes are themselves written in the survivor's voice --
# `press 'Up' -- north one step, there is a back door in this wall`
# beside "North one step.  There is a back door in this wall." -- the
# same proxy reports 37 entries that plainly do give a reason, because
# the reason is in both fields rather than split across them.  A gate
# that manufactures findings against a correct record is the one thing an
# acceptance gate must never do, so the properties are asserted over the
# union of the two fields, which is what the reader of the record gets.
#
# WHAT IS A FAILURE, and what is REPORTED for a human to judge:
#
#   FAIL  the narration carries no word beyond the key that was pressed
#         -- an entry that names the keystroke and nothing else accounts
#         for nothing, whichever field it is written in;
#   FAIL  the narration does not close as a sentence;
#   FAIL  the COMMENTARY is a single word ("Swing.", "West.", "M.").
#
#   WARN  the commentary repeats a sentence used within the previous
#         three entries.
#
# THE SINGLE-WORD CLASS IS A FAILURE, and it was not always.  It was a
# WARN, on the argument that a program cannot tell a one-word reason from
# a one-word placeholder -- "West." on the eighth step west being the
# survivor's whole thought.  A review measured the delivered record and
# settled the argument the other way: 44 of 307 entries carry a
# single-word commentary, 42 of them the character that had just been
# typed into a search box, and not one of them explains why.  R7 asks for
# per-action first-person commentary explaining WHY, and the commentary
# is what becomes the caption cue and the transcript entry -- so a
# one-word commentary is a one-word cue whatever its action note says,
# and a gate that merely counted them let the record ship with them.  A
# reason short enough to be one word can be written in two.
#
# ITS SUBJECT IS THE COMMENTARY ALONE, while the key-only property's
# subject stays the UNION of the note and the commentary.  That is not an
# inconsistency, it is the difference between the two questions: "does
# this entry account for anything at all" is answered by everything the
# reader of the RECORD gets, and "is this cue a label" is answered by the
# field that is published as the cue.  Measured on the delivered record
# the union framing is what removed 37 false findings against entries
# whose reason is written in both fields, and the commentary-only
# word count reports exactly the 44 the review named and nothing else.
#
# THERE IS NO EXEMPTION FOR A TRANSCRIBED KEYSTROKE.  There used to be:
# a commentary that was just the character pressed was counted as its own
# "transcription" class, on the argument that the reason for a spelling
# run belongs to the entry that opens it.  The review found that this
# exempted 42 of the 44 offenders -- the exemption was doing the work of
# hiding the finding.  A run of keystrokes that spells a word still gets
# one cue per keystroke on the film, and each of those cues is a
# published sentence that has to say something.
#
# WHAT IS STILL ONLY REPORTED is the repeat class, and for the reason the
# single-word class no longer qualifies for: a sentence that covers a run
# of keystrokes is a real way to narrate a run, and whether the third
# repetition is padding or emphasis is a judgement.  It is named with
# every frame number, and the count is published in the acceptance report
# and stated in playthrough/REPORT.md and TECHNICAL_NOTES.md, which is
# what makes it disclosed rather than hidden.
#
# THE SUBJECT IS THE EFFECTIVE NARRATION.  The record is append-only, so
# a sentence corrected after the fact is corrected in
# playthrough/amendments.jsonl and applied by manifest.resolve_rows();
# the timeline carries the result.  Judging the raw rows would report a
# ledger-corrected entry as still broken, so the timeline's narration is
# used when it is readable and the raw record only when it is not.
#
# IT IS STREAMED, like every other population this checker walks.  The
# narration arrives one entry at a time -- from the timeline through its
# producer's own event reader, or from the record line by line -- and the
# only things that outlive an entry are the three-sentence window the
# repeat property needs and the five thinnest entries the closing note
# names.
RATIONALE_WORD_RE = re.compile(r"[0-9a-z']+")
RATIONALE_SENTENCE_END = (".", "!", "?", "\u2026", '"', ")")
RATIONALE_WINDOW = 3
RATIONALE_THINNEST = 5
RATIONALE_KEY_RE = re.compile(r"^press '([^']+)'")


def rationale_words(text):
    """The comparable words of one sentence, lowercased."""
    return RATIONALE_WORD_RE.findall(text.lower())


def action_note(action):
    """The survivor's own note out of the action, without the key."""
    return action.split(" -- ", 1)[1] if " -- " in action else ""


def pressed_key(action):
    """The key the action names, or "" when it names none."""
    match = RATIONALE_KEY_RE.match(action)
    return match.group(1) if match else ""


def timeline_narration(timeline_path):
    """A streaming iterator over the timeline's narration, or None.

    None means the effective narration could not be read at all -- an
    unimportable producer, an unreadable document, an empty one -- and
    the caller then judges the raw record and says so.  The first entry
    is pulled here so that "unreadable" is decided before any verdict is
    formed from a half-walk.
    """
    try:
        import timeline as tl
        iterator = tl.iter_timeline_frames(timeline_path)
        first = next(iterator, None)
    except Exception:                                 # noqa: BLE001
        return None
    if first is None:
        return None

    def walk(entry=first):
        while entry is not None:
            if isinstance(entry, dict):
                yield (entry.get("frame"),
                       entry.get("action") or "",
                       entry.get("commentary") or "")
            try:
                entry = next(iterator)
            except StopIteration:
                entry = None
            except Exception:                         # noqa: BLE001
                entry = None
    return walk()


def record_narration(manifest_path):
    """A streaming iterator over the record's own narration."""
    with open(manifest_path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            yield (row.get("frame"), row.get("action") or "",
                   row.get("commentary") or "")


def check_rationale(manifest_path, timeline_path):
    """Every entry is a sentence of its own about its own keystroke."""
    narration = timeline_narration(timeline_path)
    if narration is None:
        narration = record_narration(manifest_path)
        subject = ("the record as written -- the timeline was not "
                   "readable, so no ledger correction could be applied")
    else:
        subject = ("the effective narration: the record with "
                   "playthrough/amendments.jsonl applied")

    offences = []
    repeats = []
    recent = []
    thinnest = []
    measured = 0
    labels = 0
    for index, action, commentary in narration:
        if not isinstance(action, str) or not isinstance(commentary, str):
            continue
        if not commentary.strip():
            continue
        measured += 1
        note = action_note(action)
        key = pressed_key(action)
        # The union of the two fields, which is what a reader gets.
        words = rationale_words(commentary) + rationale_words(note)
        distinct = set(words)
        beyond_key = distinct - set(rationale_words(key))
        normalised = " ".join(rationale_words(commentary))
        # BOUNDED: the five thinnest entries are kept, not all of them.
        thinnest.append((len(distinct), index, commentary))
        thinnest.sort()
        del thinnest[RATIONALE_THINNEST:]
        if not beyond_key:
            note_problem(
                offences,
                "frame %s says %r against the note %r, which is the key "
                "and nothing else" % (index, commentary, note))
        elif not commentary.rstrip().endswith(RATIONALE_SENTENCE_END):
            note_problem(
                offences,
                "frame %s says %r, which does not close as a sentence"
                % (index, commentary))
        elif len(rationale_words(commentary)) < 2:
            # THE COMMENTARY ALONE, and a total rather than a distinct
            # count: the same rule manifest.narration_substance_problem
            # applies where the row is written, so the writer's door and
            # the reader's gate cannot disagree about what a label is.
            labels += 1
            note_problem(
                offences,
                "frame %s says %r, which is one word -- a cue that names "
                "the keystroke instead of accounting for it"
                % (index, commentary))
        elif normalised and normalised in recent:
            note_problem(repeats, "frame %s: %r" % (index, commentary))
        recent.append(normalised)
        if len(recent) > RATIONALE_WINDOW:
            recent.pop(0)

    if offences:
        bad("no entry is only the key that produced it",
            "%s%s" % (summarise(offences),
                      (" -- %d of them a single-word commentary"
                       % labels) if labels else ""),
            "every entry a closed sentence, carrying at least one word "
            "beyond the key pressed in its note or its commentary, and "
            "carrying more than one word in the commentary itself -- the "
            "commentary is the published cue.  Correct an entry through "
            "playthrough/amendments.jsonl, which is appended to rather "
            "than editing the record")
    else:
        ok("no entry is only the key that produced it",
           "%d entr(ies) measured against %s: each closes as a sentence, "
           "each carries at least one word beyond its own keystroke, and "
           "no commentary is a single word.  This is the falsifiable half "
           "of the requirement; that what the entry adds is a REASON is "
           "not machine-decidable and is not claimed here"
           % (measured, subject))

    # THE REPEAT CLASS, COUNTED AND NAMED RATHER THAN FAILED.  See the
    # header above for why this one alone is still a WARN: a sentence
    # that covers a run of keystrokes is a real way to narrate a run.
    if repeats:
        verdict("WARN",
                "entries repeating the sentence before them",
                "%d entr(ies) repeating a sentence used within the "
                "previous %d: %s -- R7 asks for commentary explaining "
                "WHY, and these are the entries a reader has to judge "
                "for themselves.  The shortfall is stated in "
                "playthrough/REPORT.md and "
                "playthrough/TECHNICAL_NOTES.md rather than left here"
                % (len(repeats), RATIONALE_WINDOW, summarise(repeats)))

    # The thinnest entries, named so a reader can judge the half no
    # program can.  Reported without a verdict attached on purpose: three
    # words can be a complete reason and thirty can be padding.
    info("the thinnest entries in the record, for a reader to judge",
         "; ".join("frame %s %r" % (index, text)
                   for _, index, text in thinnest)
         if thinnest else "no entries")


def check_timestamps(index, rows, unparsable, backwards, usable,
                     oldest, newest, timeline_path, digests_path):
    """When each capture was taken, asserted rather than assumed.

    real_ts is one of the six mandated fields and it exists for exactly
    one reason: so a frame is traceable to the MOMENT it was taken.  It
    used to be carried through the schema check and then never read,
    which meant a fabricated or reordered timestamp -- a row moved, a
    value invented, an epoch pasted in -- was invisible to this gate
    while every count still tallied.  Four properties are asserted, and
    they are deliberately independent of each other:

      1. every value is a real instant, and the record never goes
         BACKWARDS.  A session is recorded forwards in time; a row whose
         timestamp precedes its predecessor's is either a fabrication or
         a reordering, and both are failures of the same requirement.
      2. the span is one plausible session, judged WITHOUT reference to
         the clock of whatever host is auditing.  Comparing evidence
         against the auditing host's clock would make a skewed or
         travelled clock into a failure of the artifacts, which it is
         not; the bounds are therefore internal (a positive span, no
         longer than a month) plus a floor no run of this pipeline can
         predate.
      3. the timeline's own copy of each timestamp is the record's.  The
         timeline is derived from the record, so a divergence means one
         of the two was edited after the other was computed.  Only the
         timestamp and the clock are compared: action and commentary
         legitimately differ where the amendment ledger corrected them.
      4. the capture-digest sidecar's attestation is at or after the row
         that recorded it, and within minutes of it.  attested_ts is
         written when the frame's bytes are hashed, which happens just
         after the keystroke that produced it, so this is a second,
         independently produced witness to the same instant.
    """
    # THE VALUES WERE JUDGED AS THEY STREAMED PAST.  main() parsed each
    # instant once, compared it with its predecessor, and kept the
    # extremes; what arrives here are the findings and the four numbers
    # those comparisons produced.  Nothing is re-derived, and no list of
    # one entry per keystroke is held to derive it from.
    if unparsable or backwards:
        bad("every row records when its capture was taken, and the "
            "record never goes backwards",
            summarise(unparsable + backwards),
            "%d ISO-8601 instants in non-decreasing order -- real_ts is "
            "what makes a frame traceable to the moment it was taken"
            % rows)
    else:
        ok("every row records when its capture was taken, and the "
           "record never goes backwards",
           "%d instants from %s to %s, none out of order"
           % (usable, oldest[2] if oldest else "-",
              newest[2] if newest else "-"))

    if usable >= 2 and oldest is not None and newest is not None:
        # MIN AND MAX, not first and last.  The ordering check above
        # already reads them in sequence; measuring the WIDTH from the
        # extremes means a single out-of-window value is caught here on
        # its own terms even when it sits in the middle of the record.
        span = newest[0] - oldest[0]
        problems = []
        if span <= 0:
            problems.append("the span is %.3f s" % span)
        if span > MAX_SESSION_SECONDS:
            problems.append("the widest span is %.1f days, between row "
                            "%d (%s) and row %d (%s)"
                            % (span / 86400.0, oldest[1], oldest[2],
                               newest[1], newest[2]))
        if oldest[0] < EARLIEST_PLAUSIBLE:
            problems.append("row %d claims %s, which predates this "
                            "pipeline" % (oldest[1], oldest[2]))
        if problems:
            bad("the record's real-time span is one plausible session",
                ", ".join(problems),
                "a positive span no longer than %d days, beginning no "
                "earlier than %s -- judged against the record itself "
                "rather than against this host's clock, because a "
                "skewed clock here is not a fault in the evidence"
                % (MAX_SESSION_SECONDS // 86400, EARLIEST_LABEL))
        else:
            ok("the record's real-time span is one plausible session",
               "%.3f h from the first capture to the last"
               % (span / 3600.0))
    else:
        bad("the record's real-time span is one plausible session",
            "%d usable timestamp(s)" % usable,
            "at least two, so a span exists to judge")

    check_timeline_timestamps(index, timeline_path)
    check_attestations(index, digests_path)


def parse_instant(value):
    """Seconds since the epoch for an ISO-8601 instant, or None.

    The pipeline writes UTC with a trailing 'Z', which
    datetime.fromisoformat did not accept before Python 3.11, so the
    suffix is normalised before parsing rather than assuming the
    interpreter is new enough.  A naive value is read as UTC, which is
    what the producers write.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.timestamp()


def check_timeline_timestamps(index, timeline_path):
    """The timeline's copy of each row, against the row itself.

    STREAMED, AND COMPARED INCREMENTALLY.  The timeline document used to
    be loaded whole here -- a second complete population beside the
    record's own -- and the "in the record and not in the timeline" list
    was then built with a set comprehension INSIDE the loop condition, so
    the set of every timeline frame was rebuilt once per record row: an
    O(N**2) walk that at a hundred thousand keystrokes is ten billion
    comparisons for a diagnosis nobody had asked for yet.

    Now the entries arrive one at a time from the producer's own event
    reader, each is compared against its row as it arrives, and the
    frames seen are counted into ONE set built once -- so the missing
    side is a single set difference rather than a nested scan.
    """
    try:
        import timeline as tl
    except Exception as err:                          # noqa: BLE001
        bad("the timeline's per-frame timestamps are the record's own",
            "timeline.py could not be imported: %s" % err,
            "the producer's own reader, so the reader of these bytes "
            "cannot drift from the writer of them")
        return
    problems = []
    compared = 0
    entries = 0
    seen = set()
    try:
        for entry in tl.iter_timeline_frames(timeline_path):
            entries += 1
            if not isinstance(entry, dict):
                note_problem(problems, "an entry that is not an object")
                continue
            frame = entry.get("frame")
            seen.add(frame)
            if not index.has(frame):
                note_problem(problems,
                             "frame %r is in the timeline and not in "
                             "the record" % frame)
                continue
            compared += 1
            if entry.get("real_ts") != index.written(frame):
                note_problem(problems,
                             "frame %r real_ts: the timeline says %r, "
                             "the record says %r"
                             % (frame, entry.get("real_ts"),
                                index.written(frame)))
            if entry.get("ingame_clock") != index.clock(frame):
                note_problem(problems,
                             "frame %r ingame_clock: the timeline says "
                             "%r, the record says %r"
                             % (frame, entry.get("ingame_clock"),
                                index.clock(frame)))
    except Exception as err:                          # noqa: BLE001
        bad("the timeline's per-frame timestamps are the record's own",
            str(err), "a readable timeline to compare against")
        return
    if not entries:
        bad("the timeline's per-frame timestamps are the record's own",
            "the timeline carries no frames array",
            "one entry per row, each naming the same instant")
        return
    for frame in sorted(index.moments.keys() - seen,
                        key=lambda f: (f is None, f)):
        note_problem(problems, "frame %r is in the record and not in "
                               "the timeline" % frame)
    if problems:
        bad("the timeline's per-frame timestamps are the record's own",
            summarise(problems),
            "%d entries agreeing with their rows on real_ts and on the "
            "clock reading -- action and commentary may differ, because "
            "the amendment ledger corrects those in the timeline while "
            "the record stays immutable" % entries)
        return
    ok("the timeline's per-frame timestamps are the record's own",
       "%d entries agree with their rows on real_ts and on the clock "
       "reading" % compared)


def check_attestations(index, digests_path):
    """The digest sidecar's own attestation, against the record.

    STREAMED AND COMPARED IN ONE PASS.  The sidecar used to be parsed
    into a dict of every attestation first, and the record's own list of
    every instant was then walked against it -- two complete populations
    resident to compare them pairwise.  Each row is judged as it arrives
    against the projection the record walk kept, and the frames attested
    are counted into one set so the unattested side is a set difference.
    """
    if not os.path.exists(digests_path):
        bad("each capture was hashed just after the row that recorded "
            "it", "%s is not there" % digests_path,
            "the capture-digest sidecar, whose attested_ts is the second "
            "witness to when each frame was taken")
        return
    problems = []
    attested = set()
    compared = 0
    widest = 0.0
    try:
        with open(digests_path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as err:
                    note_problem(problems, "line %d: %s" % (number, err))
                    continue
                written = row.get("attested_ts")
                moment = parse_instant(written)
                if moment is None:
                    note_problem(problems, "line %d attests %r"
                                 % (number, written))
                    continue
                frame = row.get("frame")
                attested.add(frame)
                recorded = index.instant(frame)
                if recorded is None:
                    # An attestation for a frame the record does not
                    # carry a usable instant for is not a comparison this
                    # check can make; the record's own verdict above
                    # reports the unparsable value.
                    continue
                compared += 1
                delta = moment - recorded
                if delta < 0:
                    note_problem(problems,
                                 "frame %r was attested %s, BEFORE its "
                                 "row's %s"
                                 % (frame, written, index.written(frame)))
                elif delta > ATTESTATION_WINDOW_SECONDS:
                    note_problem(problems,
                                 "frame %r was attested %.1f s after "
                                 "its row" % (frame, delta))
                elif delta > widest:
                    widest = delta
    except OSError as err:
        bad("each capture was hashed just after the row that recorded "
            "it", str(err), "a readable capture-digest sidecar")
        return
    for frame in sorted(index.moments.keys() - attested,
                        key=lambda f: (f is None, f)):
        if index.instant(frame) is None:
            continue
        note_problem(problems, "frame %r has no attestation" % frame)
    if problems:
        bad("each capture was hashed just after the row that recorded "
            "it", summarise(problems),
            "an attestation at or after every row's real_ts and within "
            "%d s of it (row %d onwards) -- an attestation before the "
            "row, or hours after it, means one of the two was written "
            "from something other than the session"
            % (ATTESTATION_WINDOW_SECONDS,
               index.order[0][1] if index.order else 0))
        return
    ok("each capture was hashed just after the row that recorded it",
       "%d attestations, every one at or after its row and within "
       "%.1f s of it" % (compared, widest))


def finish(index, rows, line_count, referenced, clock_kinds, frames_dir,
           facts):
    """The disk half: what is in frames/, and does it pair with rows.

    The directory is walked ONCE, with os.scandir, and nothing
    proportional to the session survives that walk except the set of
    indices the contiguity and orphan checks are made of -- integers
    rather than the names they came from, which is a fraction of the
    footprint and exactly what those two questions need.
    """
    strays = []
    indices = set()
    captures = 0
    highest = 0
    try:
        with os.scandir(frames_dir) as listing:
            for item in listing:
                match = FRAME_RE.match(item.name)
                if match is None:
                    note_problem(strays, item.name)
                    continue
                captures += 1
                number = int(match.group(1))
                indices.add(number)
                if number > highest:
                    highest = number
    except OSError as err:
        bad("the captures directory is readable", str(err),
            "a readable directory of captures")

    if strays:
        bad("the captures directory holds captures and nothing else",
            summarise(strays),
            "only frame_NNNNN.png -- derived transition images belong "
            "in playthrough/build/transitions/, never here")
    else:
        ok("the captures directory holds captures and nothing else",
           "%d files, every one a frame_NNNNN.png" % captures)

    # THE IDENTITY.  Two counts produced by different code paths at
    # different times; they must agree exactly.
    #
    # It is asserted against the RAW LINE COUNT as well as against the
    # parsed row count, because `"${WC}" -l < manifest.jsonl` is the number
    # the requirement names and an unparsable line would otherwise be
    # excluded from the comparison it is most likely to have broken.
    if captures == rows == line_count:
        ok("the capture count equals the record's row count -- one "
           "frame per keystroke",
           "%d captures == %d rows == %d lines"
           % (captures, rows, line_count))
    else:
        bad("the capture count equals the record's row count -- one "
            "frame per keystroke",
            "%d captures, %d parsed rows, %d lines in the record"
            % (captures, rows, line_count),
            "all three equal; a capture without a row, or a row "
            "without a capture, means a keystroke was not recorded or "
            "a frame was not taken")

    if captures == highest and len(indices) == captures:
        ok("capture indices are contiguous from 00001",
           "00001 .. %05d" % captures if captures else "none")
    else:
        # ONE SET, ONE LINEAR SCAN, AND A BOUNDED LIST.  The gap
        # diagnosis used to rebuild the set of every present index for
        # EVERY candidate index -- `if n not in set(indices)` inside the
        # comprehension -- which is O(N**2): at a hundred thousand
        # captures, five billion membership tests to describe a failure
        # the first missing index already describes.  The set is the one
        # built by the walk above, and the scan stops collecting once the
        # verdict has enough to be useful.
        gaps = []
        for number in range(1, highest + 1):
            if number not in indices:
                note_problem(gaps, number)
        bad("capture indices are contiguous from 00001",
            "highest %d, count %d, missing %s"
            % (highest, captures, summarise(gaps)),
            "1 .. N with no gaps, so no capture was withdrawn after "
            "its row was written")

    # EVERY CAPTURE THE RECORD NAMES, AGAINST THE INDICES ON DISK.  The
    # record's own canonical-name check above has already established
    # that a row names frame_%05d.png formatted from its own number, so
    # the pairing question here is whether that number is on disk -- an
    # integer comparison against the set the walk produced, rather than a
    # second list of every basename the record mentions.
    orphans = []
    for frame, _ in index.order:
        if isinstance(frame, int) and frame not in indices:
            note_problem(orphans, "frame_%05d.png" % frame)
    if orphans:
        bad("every capture the record names exists on disk",
            summarise(orphans),
            "all %d referenced files present" % referenced)
    else:
        ok("every capture the record names exists on disk",
           "%d referenced files, all present" % referenced)

    # --- HONESTY, REPORTED AS INFORMATION ----------------------------
    # A null clock or a coarse phrase is what the survivor could ACTUALLY
    # read at that moment, and recording it verbatim is the requirement
    # being met rather than broken.  Counting it as an error here would
    # create pressure to guess, which is the one thing forbidden
    # outright.  So it is reported, with the count, and never failed.
    #
    # The tally was accumulated as the record streamed past; the frames
    # whose clock was legible were written straight to the in-game list
    # file at the same time.
    tally = ", ".join("%s: %d" % (k, clock_kinds[k])
                      for k in sorted(clock_kinds))
    info("clock readings in the record, by kind (an unreadable clock is "
         "honesty, not a fault)", tally or "no rows")

    facts.write("manifest_rows=%d\n" % rows)
    facts.write("manifest_lines=%d\n" % line_count)
    facts.write("capture_count=%d\n" % captures)
    facts.close()
    return 0


CLOCK_RE = re.compile(r"^[0-9]{2}:[0-9]{2}:[0-9]{2}$")

if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

# check_no_outstanding_step -- no keystroke was delivered without a frame.
#
# THE COUNT IDENTITY CANNOT SEE THIS, AND THAT IS WHY THIS CHECK EXISTS.
# Group 2's headline verdict compares captures with record rows and record
# lines, and all THREE of those numbers are written only after a capture
# has succeeded.  So a keystroke that was delivered and whose capture was
# then rejected leaves every one of them untouched: the identity reads
# `305 == 305 == 305` and passes, while 306 keys had actually left for the
# game.  That is not hypothetical -- a review found precisely it in the
# superseded recording, where a terminal keystroke at a main-menu
# "Really quit?" ended the application, the capture that followed was
# black and was correctly refused, and the gate reported a clean identity
# over a record that was one keystroke short.
#
# The ONLY durable evidence of such a keystroke is session.py's step
# journal, which is written before the key leaves and cleared only once
# the row is committed.  An outstanding journal in ANY phase means a step
# is unfinished: `sending` means delivery is unknown, `delivered` means
# the key reached the X server with no frame recorded for it, and
# `captured` means the frame exists but its row does not.  None of the
# three is a finished record, so the gate requires no journal at all.
#
# IT IS ASKED THROUGH `session.py journal`, NOT `session.py status`.
# `status` opens a session, and opening a session SETTLES an outstanding
# journal by design -- so asking `status` would REPAIR the very thing this
# check came to find, and the evidence would disappear into the act of
# looking for it.  `journal` takes no lock, opens no session and writes
# nothing; it derives the path exactly as a session would and reads it,
# which also keeps that derivation in one place rather than restating it
# here in shell.
check_no_outstanding_step() {
    local payload="" outstanding="" phase="" frame="" key=""
    payload="$(bounded "${BOUND_PROBE_SECONDS}" \
        "${PYTHON}" -B "${PLAYTHROUGH_TOOLING_DIR}/session.py" journal \
        2>"$(tool_error_file session)" || true)"
    if [ -z "${payload}" ]; then
        record_fail "no keystroke is outstanding -- every key that was \
delivered became a frame and a row" \
            "session.py journal reported nothing$(because session)" \
            "a JOURNAL_PRESENT reading; without one the gate cannot \
tell a finished record from one missing its last keystroke, which is \
the failure this check exists to catch"
        return 0
    fi
    outstanding="$(printf '%s\n' "${payload}" |
        "${SED}" -n 's/^JOURNAL_PRESENT=//p' | "${HEAD}" -n 1)"
    phase="$(printf '%s\n' "${payload}" |
        "${SED}" -n 's/^JOURNAL_PHASE=//p' | "${HEAD}" -n 1)"
    frame="$(printf '%s\n' "${payload}" |
        "${SED}" -n 's/^JOURNAL_FRAME=//p' | "${HEAD}" -n 1)"
    key="$(printf '%s\n' "${payload}" |
        "${SED}" -n 's/^JOURNAL_KEY=//p' | "${HEAD}" -n 1)"
    if [ "${outstanding}" = "no" ]; then
        record_pass "no keystroke is outstanding -- every key that was \
delivered became a frame and a row" \
            "no step journal; every delivered keystroke was carried \
through to a capture and a row"
        return 0
    fi
    record_fail "no keystroke is outstanding -- every key that was \
delivered became a frame and a row" \
        "a step journal is outstanding: phase='${phase}' frame='${frame}' \
key='${key}'" \
        "no journal at all.  A keystroke left for the game and its row \
was never written, so the capture/row/line identity is measuring a \
record that is one keystroke short of the session that was played.  \
Resolve it deliberately -- 'session.py status' completes a 'delivered' \
or 'captured' step, and 'session.py reconcile --outcome …' is the only \
way past a 'sending' one, because whether that key landed cannot be \
inferred"
}

# check_ending_is_save_and_quit -- R11's exit, read off the record.
#
# R11 IS FROZEN AND IT NAMES A PATH, NOT AN OUTCOME.  The session ends by
# realistic sleep or by death, and then "the survivor exits through the
# in-game Save & Quit path -- immediately after waking if the ending was
# sleep".  A review found that requirement discharged by REINTERPRETATION
# instead: the survivor died, the engine's own death cleanup ran, the
# operator quit from the MAIN MENU, and the record described that
# sequence as the in-game Save & Quit.  It is not.  The engine's death
# cleanup is something that happens TO a world; Save & Quit is a
# deliberate act by a living survivor.
#
# WHAT THE ENGINE ACTUALLY REQUIRES, and therefore what this reads for.
# `data/raw/keybindings.json:3298` declares action id `save`, named
# "Save and quit", bound to keyboard_char 'S' in DEFAULTMODE.
# `src/handle_action.cpp:3030-3040` takes ACTION_SAVE through
# `query_yn("Save and quit?")` to `save()` and `uquit = QUIT_SAVED`,
# which returns to the MAIN MENU WITH THE APPLICATION STILL ALIVE.  So
# the compliant ending is two keystrokes, 'S' then the confirmation, and
# -- this is the part that matters for R2 -- the second one is
# CAPTURABLE, because the process is still running to be photographed
# afterwards.  That is not incidental: the same review found a terminal
# keystroke at a main-menu "Really quit?" ending the application, so the
# capture that followed was black and correctly refused, leaving 306 keys
# against 305 frames.  An ending that can be photographed is the fix to
# both findings at once.
#
# A DEATH ENDING DOES NOT SATISFY THIS, DELIBERATELY.  The AAP permits
# death as an ending CONDITION, and group 7 still accepts the world the
# engine cleared afterwards as proof that R1's save was committed -- that
# is a different question, honestly answered there.  But nothing in a
# death cleanup is the exit R11 names, so it cannot pass here; the two
# questions are kept apart precisely because conflating them is the
# defect being fixed.
#
# THE KEY IS READ FROM THE OBSERVATIONS SIDECAR because the manifest's
# six-field schema is the one the prompt fixed and does not carry the
# keystroke; playthrough/build/observations.jsonl records `key` per
# capture, one row per frame.
check_ending_is_save_and_quit() {
    local path="${PLAYTHROUGH_OBSERVATIONS}"
    local outcome="" ceiling="" status=0
    if [ ! -f "${path}" ]; then
        record_fail "the session ended through the in-game Save & Quit \
path, and its last keystroke was capturable" \
            "$(rel "${path}") is not there, so the keystrokes that \
ended the session cannot be read" \
            "the capturer's own committed observations, one row per \
capture, carrying the key that produced it"
        return 0
    fi
    ceiling="$(checker_bound)"
    # STREAMED, KEEPING ONLY A SHORT TAIL.  The question is about the end
    # of the record, so this holds the last few rows and nothing else --
    # the file has one row per capture and a session has no fixed length.
    outcome="$(bounded "${ceiling}" "${PYTHON}" -B -c '
import json
import re
import sys

TAIL = 6
SAVE_KEY = re.compile(r"^(S|shift\+s)$")
CONFIRM_KEY = re.compile(r"^[Yy]$")

path = sys.argv[1]
tail = []
rows = 0
with open(path, "r", encoding="utf-8") as handle:
    for line in handle:
        if not line.strip():
            continue
        rows += 1
        try:
            row = json.loads(line)
        except ValueError:
            row = {}
        tail.append((row.get("frame"), row.get("key"),
                     row.get("action")))
        if len(tail) > TAIL:
            tail.pop(0)

if rows < 2:
    print("FAIL the record holds %d row(s); an ending is two "
          "keystrokes" % rows)
    raise SystemExit(0)

trail = ", ".join("frame %s: %r" % (frame, key)
                 for frame, key, _ in tail)
confirm_frame, confirm_key, confirm_action = tail[-1]
save_frame, save_key, save_action = tail[-2]
if not SAVE_KEY.match(str(save_key or "")):
    print("FAIL the second-to-last keystroke is %r, not the \x27S\x27 "
          "that opens Save & Quit -- the tail reads %s"
          % (save_key, trail))
    raise SystemExit(0)
if not CONFIRM_KEY.match(str(confirm_key or "")):
    print("FAIL the last keystroke is %r, not the confirmation of "
          "\x22Save and quit?\x22 -- the tail reads %s"
          % (confirm_key, trail))
    raise SystemExit(0)
print("PASS frame %s delivered %r (%s) and frame %s confirmed with %r "
      "(%s), which is ACTION_SAVE answered yes -- the engine returned "
      "to the main menu with the process alive, so the final frame is a "
      "real capture"
      % (save_frame, save_key, save_action, confirm_frame, confirm_key,
         confirm_action))
' "${path}" 2>&1)" || status=$?
    if bound_expired "${status}"; then
        record_fail "the session ended through the in-game Save & Quit \
path, and its last keystroke was capturable" \
            "the reading of $(rel "${path}") did not finish within \
${ceiling}s and was stopped" \
            "a sidecar this gate can read within a ceiling derived from \
the capture count"
        return 0
    fi
    case "${outcome}" in
        PASS*)
            record_pass "the session ended through the in-game Save & \
Quit path, and its last keystroke was capturable" "${outcome#PASS }"
            ;;
        FAIL*)
            record_fail "the session ended through the in-game Save & \
Quit path, and its last keystroke was capturable" \
                "${outcome#FAIL }" \
                "the record's last two keystrokes being 'S' (DEFAULTMODE \
\`save\`, \"Save and quit\", data/raw/keybindings.json:3298) and its \
confirmation, which takes the engine to QUIT_SAVED and back to the main \
menu with the process still alive (src/handle_action.cpp:3030-3040).  A \
death cleanup followed by a main-menu quit is NOT that path, and quitting \
the application with the last keystroke leaves that keystroke with no \
frame"
            ;;
        *)
            record_fail "the session ended through the in-game Save & \
Quit path, and its last keystroke was capturable" \
                "the reading could not be taken: ${outcome:-<nothing>}" \
                "a readable observations sidecar"
            ;;
    esac
}

# ---------------------------------------------------------------------
# THE EVIDENCE AUTHENTICITY CHECKS
#
# Everything else in this group asks whether the record is INTERNALLY
# consistent.  These four ask the question that consistency cannot
# answer: whether any of it was changed after the fact.
#
# A review put the gap precisely -- "every attestation is mutable with
# its evidence" -- and found two live consequences of nothing looking:
# frame 298 had been read TWICE with neither row saying it replaced the
# other (and a dict keyed by frame index silently kept whichever came
# last), while frame 307, the final capture of the session, had no
# acknowledgment at all.  Both were invisible to a gate that reported
# VERIFY=pass.
#
# So: two checks on the acknowledgment ledger, and two on the hash chain
# that seals the evidence from outside itself.  The chain's own head is
# published as a commit trailer, and THAT comparison is a property of the
# commit, so it lives in group 7 with the rest of the history.
# ---------------------------------------------------------------------
emit_evidence_checker() {
    emit_checker evidence <<'PY'
"""Assert the acknowledgment ledger and the evidence anchor."""

import sys

SEP = "\x1f"


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def summarise(items, limit=4):
    shown = "; ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += "; ... (%d more)" % (len(items) - limit)
    return shown


RECONCILED = ("the acknowledgment ledger is reconciled -- a second "
              "reading of a frame names the one it replaces")
COVERED = ("every capture has a standing acknowledgment, the final "
           "frame included")
CHAIN = "the evidence anchor is a sound hash chain"
SEALED = ("every sealed artifact still hashes to its seal, as sha256 "
          "AND as git's own blob name")


def check_ledger(session, manifest, acks_path, captures):
    """The two acknowledgment properties."""
    try:
        rows = session.read_acknowledgments(acks_path)
    except Exception as err:                          # noqa: BLE001
        bad(RECONCILED, "the ledger could not be read: %s" % err,
            "a readable append-only acknowledgment ledger")
        bad(COVERED, "the ledger could not be read: %s" % err,
            "one standing reading per capture")
        return
    problems = session.acknowledgment_problems(rows)
    if problems:
        bad(RECONCILED, summarise(problems),
            "every frame read more than once carrying, in its LAST "
            "row's `supersedes`, the acknowledged_at of every earlier "
            "row for that frame.  The ledger is append-only, so a "
            "correction is an appended row that names what it corrects "
            "-- a duplicate with no declared relationship leaves two "
            "readings of one frame and nothing to say which stands")
    else:
        standing = session.effective_acknowledgments(rows)
        superseded = len(rows) - len(standing)
        ok(RECONCILED,
           "%d row(s) resolving to %d standing reading(s); %d earlier "
           "reading(s) explicitly superseded"
           % (len(rows), len(standing), superseded))

    standing = session.effective_acknowledgments(rows)
    if captures is None:
        bad(COVERED, "the capture count was not available to compare "
                     "against", "a capture count from group 2")
        return
    missing = [index for index in range(1, captures + 1)
               if index not in standing]
    if missing:
        # THE LAST FRAME IS NAMED SEPARATELY.  It is the one an
        # acknowledgment discipline that travels with the NEXT keystroke
        # structurally cannot cover -- there is no next key -- which is
        # exactly why frame 307 was missing and why this check exists.
        tail = (" -- including the FINAL capture %d, which no "
                "acknowledgment travelling with a following keystroke "
                "could ever cover, because there is no following "
                "keystroke" % captures) if captures in missing else ""
        bad(COVERED,
            "%d capture(s) have no standing reading: %s%s"
            % (len(missing), summarise(missing, 8), tail),
            "one standing acknowledgment for each of the %d captures.  "
            "Record the missing one with `session.py ack --frame N "
            "--observed '...'` after actually looking at the frame"
            % captures)
        return
    ok(COVERED,
       "all %d captures carry a standing reading, frame %d included"
       % (captures, captures))


def check_anchor(manifest, anchor_path):
    """The two hash-chain properties."""
    try:
        rows = manifest.read_anchor_rows(anchor_path)
    except Exception as err:                          # noqa: BLE001
        bad(CHAIN, "the anchor could not be read: %s" % err,
            "a readable append-only evidence anchor")
        bad(SEALED, "the anchor could not be read: %s" % err,
            "every sealed artifact held to its seal")
        return
    if not rows:
        bad(CHAIN,
            "there is no evidence anchor, so nothing vouches for the "
            "evidence from outside itself",
            "a chained seal over the record, the ledgers, the timeline, "
            "the transcripts and the films -- written by "
            "`commit_artifacts.sh` at each checkpoint")
        bad(SEALED, "there is no evidence anchor to hold anything to",
            "one seal row per evidence artifact")
        return
    problems = manifest.anchor_chain_problems(rows)
    if problems:
        bad(CHAIN, summarise(problems),
            "%d row(s) whose seq is contiguous, whose prev_chain is the "
            "row before it, and whose chain is the sha256 of its own "
            "fields -- a break here means a row was altered, removed or "
            "reordered after it was sealed" % len(rows))
    else:
        head = manifest.anchor_head(rows)
        sealed = sorted({row.get("path") for row in rows})
        ok(CHAIN,
           "%d row(s) over %d artifact(s), chained and re-derived; head "
           "%s" % (len(rows), len(sealed), head[:16]))

    # The artifacts themselves, against the newest seal for each.
    #
    # DRIFT IS FAILED HERE; COVERAGE IS REPORTED, NOT FAILED -- and that
    # is an ordering fact rather than leniency.  The committer seals at
    # each checkpoint, and the pipeline REGENERATES the timeline, the
    # transition inputs, the film and the transcript pair after the last
    # session checkpoint and before this gate runs.  So on a legitimate
    # first run those artifacts exist and are not yet sealed, and failing
    # on that would make the gate refuse every honest pipeline.  What
    # closes the gap is group 7 at post-commit: an artifact produced
    # after the last checkpoint leaves the tree dirty, which `nothing
    # under playthrough/ is left uncommitted` reports, and the checkpoint
    # that commits it seals it and publishes the new head in its own
    # trailer.  An artifact that IS sealed and no longer matches its seal
    # is failed here, unconditionally.
    try:
        broken = manifest.verify_anchor(anchor_path, require_all=False)
        pending = manifest.unsealed_artifacts(anchor_path, rows=rows)
    except Exception as err:                          # noqa: BLE001
        bad(SEALED, "the seal could not be checked: %s" % err,
            "every sealed artifact re-hashed and unchanged")
        return
    structural = set(manifest.anchor_chain_problems(rows))
    broken = [problem for problem in broken if problem not in structural]
    if broken:
        bad(SEALED, summarise(broken),
            "every sealed artifact unchanged since it was sealed.  The "
            "sha256 and git's own blob name are computed by different "
            "code over the same bytes, so a disagreement in either is a "
            "post-hoc edit rather than a rounding difference")
        return
    paths = sorted({row.get("path") for row in rows})
    ok(SEALED,
       "%d artifact(s) re-hashed and unchanged: %s%s"
       % (len(paths), ", ".join(paths[:6]) +
          (", ..." if len(paths) > 6 else ""),
          ("; %d awaiting the next checkpoint's seal (%s)"
           % (len(pending), summarise(list(pending), 4)))
          if pending else "; none awaiting a seal"))


def main(argv):
    tooling_dir, acks_path, anchor_path, captures_text = argv[1:5]
    sys.path.insert(0, tooling_dir)
    try:
        import manifest
        import session
    except Exception as err:                          # noqa: BLE001
        for name in (RECONCILED, COVERED, CHAIN, SEALED):
            bad(name, "the producing modules could not be imported: %s"
                % err,
                "session.py and manifest.py beside this gate, which own "
                "the ledger and the anchor")
        return 0
    try:
        captures = int(captures_text)
    except (TypeError, ValueError):
        captures = None
    check_ledger(session, manifest, acks_path or None, captures)
    check_anchor(manifest, anchor_path or None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_record() {
    group 2 "one frame per keystroke"
    check_no_outstanding_step
    check_ending_is_save_and_quit
    run_checker record \
        "${PLAYTHROUGH_MANIFEST}" \
        "${PLAYTHROUGH_FRAMES_DIR}" \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "${SCRATCH}/facts" \
        "$(rel "${PLAYTHROUGH_TIMELINE}")" \
        "$(rel "${PLAYTHROUGH_FRAME_DIGESTS}")" \
        "$(in_game_file)"
    # AFTER the record checker, because it reads the capture count that
    # checker publishes as a fact -- "every capture is acknowledged" is a
    # comparison against a number, and deriving that number twice is how
    # two checks come to disagree about the same session.
    run_checker evidence \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "$(rel "${PLAYTHROUGH_ACKNOWLEDGMENTS}")" \
        "$(rel "${PLAYTHROUGH_EVIDENCE_ANCHOR}")" \
        "$(fact capture_count)"
}


# ---------------------------------------------------------------------
# 3  THE TIMELINE -- THE FLOOR, THE CEILING AND THE INVARIANT
#
# The claim the film makes is that its pacing is the game's own clock.
# This group is where that claim is checked, one arithmetic property at a
# time.
#
# THE FLOOR IS NOT AN OPTIMISATION OPPORTUNITY.  A menu keystroke
# consumes no game time at all, and such a frame is held at 0.25 s
# rather than merged, dropped or "optimised away"; an entry count below
# the capture count is therefore a failure even though the film would
# look identical.
#
# THE CEILING IS STRICT.  A raw delta of exactly 10.0 s is NOT a
# transition; only a delta GREATER than the ceiling is.  Both directions
# of that correspondence are asserted, because a flag without a delta and
# a delta without a flag are different bugs with the same symptom -- the
# film and the cues drifting apart by exactly one second, once.
#
# THE PRODUCERS' OWN CONSTANTS ARE CROSS-CHECKED.  timeline.py,
# make_transitions.py and render_movie.py are imported and their
# constants compared against the values this gate measures with, so a
# future edit to a producer cannot quietly move the goalposts.
# ---------------------------------------------------------------------
emit_timeline_checker() {
    emit_checker timeline <<'PY'
"""Assert the timeline's clamp, flags, cue windows and invariant."""

import hashlib
import json
import os
import re
import sys

SEP = "\x1f"
TRANS_RE = re.compile(r"^trans_([0-9]{5})_([0-9]{2})\.png$")


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def summarise(items, limit=6):
    shown = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += ", ... (%d more)" % (len(items) - limit)
    return shown


# HOW MANY FINDINGS ONE VERDICT COLLECTS.
#
# One entry per keystroke and one transition group per night slept
# through, so a document broken throughout -- a regenerated timeline, a
# clamp changed under it -- would otherwise put one diagnostic string per
# entry into memory to explain a failure whose first example already
# explains it.
PROBLEM_LIMIT = 200


def note_problem(problems, text, limit=PROBLEM_LIMIT):
    """Collect a finding, bounded; past the limit, say so once."""
    if len(problems) < limit:
        problems.append(text)
        return
    if len(problems) == limit:
        problems.append("... further findings were not collected; the "
                        "%d above are the ones this verdict carries"
                        % limit)


def near(a, b, eps):
    return abs(float(a) - float(b)) <= eps


def clamp(value, low, high):
    return min(max(value, low), high)


def illustrate(items, total, limit=6):
    """A few examples out of an exactly known total.

    summarise() derives "and N more" from the length of the list it is
    given, which is right for a list that holds everything and WRONG for a
    bounded one: six examples out of a thousand flags would read as "and
    two more".  Where the count is known exactly and the examples are
    deliberately few, the count comes from the counter and the examples
    are named as examples.
    """
    shown = ", ".join(str(i) for i in items[:limit])
    if total > len(items[:limit]):
        shown += ", ... (%d more)" % (total - len(items[:limit]))
    return shown


def entries_and_shape(header, path, tl):
    """The entry SOURCE and a description of the document's shape.

    timeline.py writes an object carrying its declared totals alongside a
    `frames` array, and that shape is STREAMED: the array is walked one
    entry at a time by the producer's own event reader, so a walk costs
    one entry rather than the session.  json.load() of a document with one
    entry per keystroke is roughly a kilobyte of interpreter objects per
    entry -- hundreds of megabytes at the session lengths this pipeline
    is built for, on a host with under four gigabytes and an encoder to
    run.

    A bare array is still understood -- it is what a hand-reduced or an
    older document looks like -- and it is the one shape that is held
    whole, because the header reader returns it whole.  That is
    acceptable precisely because this pipeline never writes one: the
    document whose length is unbounded is the object form, and the object
    form is the one that streams.
    """
    if isinstance(header, dict):
        if isinstance(header.get("frames"), list):
            return (tl.iter_timeline_frames(path), header,
                    "object with a frames array")
        return iter(()), header, "object with no frames array"
    if isinstance(header, list):
        return iter(header), {}, "bare array (no declared totals)"
    return iter(()), {}, "neither an object nor an array"


class Walk:
    """Everything ONE pass over the entries produces.

    The entries are walked once, and what survives the walk is counters,
    two running sums, the flagged frame numbers -- one per FLAG, which is
    what the exact set comparison against the materialised transition
    groups needs -- and bounded lists of examples.  Nothing here is
    proportional to the number of entries.
    """

    __slots__ = ("count", "flag_count", "reconciled", "sum_durations",
                 "cursor", "last_cue_end", "flagged", "out_of_range",
                 "not_clamped", "negative", "window_problems",
                 "walk_problems", "flagged_without", "over_without_flag",
                 "at_ceiling", "ceiling_detail")

    def __init__(self):
        self.count = 0
        self.flag_count = 0
        self.reconciled = 0
        self.sum_durations = 0.0
        self.cursor = 0.0
        self.last_cue_end = 0.0
        self.flagged = []
        self.out_of_range = []
        self.not_clamped = []
        self.negative = []
        self.window_problems = []
        self.walk_problems = []
        self.flagged_without = []
        self.over_without_flag = []
        self.at_ceiling = []
        self.ceiling_detail = []


def walk_entries(entries, floor, ceil, trans, eps, windows_path):
    """Judge every arithmetic property of every entry in one pass.

    The clamp, the flags, the cue windows, the cursor walk and the
    duration sum were five separate walks over a list held in memory.
    They are one walk over a stream here, and the transition windows the
    pixel probes need are written out as they are met rather than
    collected and joined afterwards.

    WHERE THE CARDS ARE, IN VIDEO TIME.  A transition occupies the second
    immediately after the flagged frame's cue window, and the probes in
    groups 4, 5 and 6 need to know: a frame extracted from inside a fade
    or a title card is a legitimate near-black image, so an offset that
    lands there tells the luminance gate nothing about the session.  One
    window per LINE, never one fact -- a fact becomes an `awk -v`
    argument, and an argument is bounded by MAX_ARG_STRLEN (131,072 bytes
    on Linux) however much room argv has, which is about ten thousand
    windows.  A session long enough to sleep through ten thousand nights
    is the session this pipeline is built for, and past that ceiling the
    gate died with E2BIG instead of reporting anything at all.
    """
    walk = Walk()
    with open(windows_path, "w", encoding="utf-8") as windows:
        for entry in entries:
            walk.count += 1
            number = entry.get("frame")
            duration = entry.get("duration")
            raw = entry.get("raw_delta")
            flag = bool(entry.get("transition_after"))
            if entry.get("reconciled"):
                walk.reconciled += 1

            # --- the clamp, the ceiling and the direction of time ----
            if not isinstance(duration, (int, float)):
                note_problem(walk.out_of_range,
                             "frame %s duration=%r" % (number, duration))
            else:
                # Summed here, over NUMERIC durations only: the invariant
                # used to sum `float(e.get("duration") or 0.0)` over every
                # entry, which raises on a non-numeric one and loses every
                # verdict this checker had left to emit.
                walk.sum_durations += float(duration)
                if duration < floor - eps or duration > ceil + eps:
                    note_problem(walk.out_of_range,
                                 "frame %s duration=%s"
                                 % (number, duration))
                if isinstance(raw, (int, float)):
                    if raw < -eps:
                        note_problem(walk.negative,
                                     "frame %s raw_delta=%s"
                                     % (number, raw))
                    wanted = round(clamp(float(raw), floor, ceil), 3)
                    if not near(duration, wanted, eps):
                        note_problem(
                            walk.not_clamped,
                            "frame %s duration=%s but clamp(%s)=%s"
                            % (number, duration, raw, wanted))
                else:
                    note_problem(walk.not_clamped,
                                 "frame %s raw_delta=%r" % (number, raw))

            # --- the flag, in both directions -----------------------
            if flag:
                walk.flag_count += 1
                if number is not None:
                    walk.flagged.append(number)
                # A handful of examples, and no cap message: the exact
                # count is reported from the counter, so illustrate()
                # names how many were not shown.
                if len(walk.ceiling_detail) < 6:
                    walk.ceiling_detail.append(
                        "frame %s raw_delta=%ss held at %ss"
                        % (number, raw, duration))
            if isinstance(raw, (int, float)):
                if flag and not float(raw) > ceil:
                    note_problem(walk.flagged_without,
                                 "frame %s raw_delta=%s" % (number, raw))
                    if float(raw) == ceil:
                        note_problem(walk.at_ceiling,
                                     "frame %s" % number)
                if float(raw) > ceil and not flag:
                    note_problem(walk.over_without_flag,
                                 "frame %s raw_delta=%s" % (number, raw))

            # --- the cue window, and the cursor it must sit on ------
            start = entry.get("cue_start")
            end = entry.get("cue_end")
            if not all(isinstance(v, (int, float))
                       for v in (duration, start, end)):
                note_problem(walk.window_problems,
                             "frame %s has a non-numeric window" % number)
                continue
            walk.last_cue_end = float(end)
            if not near(end - start, duration, eps):
                note_problem(
                    walk.window_problems,
                    "frame %s window %s..%s spans %s but duration is %s"
                    % (number, start, end, round(end - start, 3),
                       duration))
            if not near(start, walk.cursor, eps):
                note_problem(walk.walk_problems,
                             "frame %s starts at %s, the walk reached %s"
                             % (number, start, round(walk.cursor, 3)))
            walk.cursor = start + duration
            if flag:
                walk.cursor += trans
                windows.write("%.3f-%.3f\n" % (float(end),
                                               float(end) + trans))
    walk.sum_durations = round(walk.sum_durations, 3)
    return walk


def check_constants(tooling_dir, floor, ceil, trans, per_group, tol,
                    eps):
    """The producers' own constants, against the gate's expectations."""
    sys.path.insert(0, tooling_dir)
    problems = []
    observed = []
    try:
        import timeline as tl
        observed.append("timeline.py FLOOR=%s CEIL=%s TRANSITION=%s"
                        % (tl.FLOOR, tl.CEIL, tl.TRANSITION))
        for label, got, want in (("FLOOR", tl.FLOOR, floor),
                                 ("CEIL", tl.CEIL, ceil),
                                 ("TRANSITION", tl.TRANSITION, trans)):
            if not near(got, want, eps):
                problems.append("timeline.%s is %s, gate expects %s"
                                % (label, got, want))
    except Exception as err:                          # noqa: BLE001
        problems.append("timeline.py could not be imported: %s" % err)
    try:
        import make_transitions as mt
        observed.append("make_transitions.py FRAMES_PER_GROUP=%s"
                        % mt.FRAMES_PER_GROUP)
        if int(mt.FRAMES_PER_GROUP) != int(per_group):
            problems.append(
                "make_transitions.FRAMES_PER_GROUP is %s, gate expects "
                "%s" % (mt.FRAMES_PER_GROUP, per_group))
    except Exception as err:                          # noqa: BLE001
        problems.append("make_transitions.py could not be imported: %s"
                        % err)
    try:
        import render_movie as rm
        observed.append("render_movie.py DURATION_TOLERANCE=%s"
                        % rm.DURATION_TOLERANCE)
        if not near(rm.DURATION_TOLERANCE, tol, eps):
            problems.append(
                "render_movie.DURATION_TOLERANCE is %s, gate expects %s"
                % (rm.DURATION_TOLERANCE, tol))
    except Exception as err:                          # noqa: BLE001
        problems.append("render_movie.py could not be imported: %s"
                        % err)
    if problems:
        bad("the producers' own constants are the ones this gate "
            "measures against", summarise(problems),
            "FLOOR=%s CEIL=%s TRANSITION=%s FRAMES_PER_GROUP=%s "
            "DURATION_TOLERANCE=%s" % (floor, ceil, trans, per_group,
                                       tol))
    else:
        ok("the producers' own constants are the ones this gate "
           "measures against", "; ".join(observed))


def file_digest(path):
    """A streamed sha256, so a large capture is not held in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_capture_digests(document, inventory_path):
    """Every committed capture, against the digest taken when it was
    captured.

    The sidecar is not named here: its path comes out of the timeline
    document itself, which is the artifact that declares having verified
    it.  So this check follows the timeline's own pointer rather than
    assuming a layout.

    IT IS STREAMED, AND IT PUBLISHES WHAT IT HASHED.  The sidecar is read
    one row at a time and each capture is verified as its row arrives, so
    nothing proportional to the session is held: the whole sidecar used to
    be parsed into a dict of digests first, and every capture was then
    hashed a SECOND time by group 4 for its own question.  Each digest
    taken here is appended to the shared inventory (see digest_inventory
    in the gate), which is what makes group 4's sweep free.
    """
    block = document.get("captures")
    if not isinstance(block, dict) or not block.get("path"):
        # A FAILURE, NOT A NOTE.  This used to report an INFO, which
        # meant the strongest integrity assertion in the gate -- the
        # whole-set digest sweep -- could be REMOVED by editing the very
        # artifact under inspection: deleting the `captures` block turned
        # the sweep into a note and made a second check vanish
        # altogether, and the report still read "all checks passed".  An
        # assertion that the artifact can switch off is not an assertion.
        bad("every committed capture still hashes to the digest taken "
            "when it was captured",
            "the timeline declares no capture-digest sidecar, so no "
            "capture can be checked against one",
            "a `captures` block naming the sidecar timeline.py wrote and "
            "verified -- without it the whole-set integrity of the "
            "captures is unestablished, and a missing declaration is "
            "indistinguishable from a removed one")
        return
    path = block["path"]
    if not os.path.exists(path):
        bad("every committed capture still hashes to the digest taken "
            "when it was captured", "%s is not there" % path,
            "the sidecar the timeline says it verified")
        return
    problems = []
    recorded_rows = 0
    checked = 0
    with open(path, "r", encoding="utf-8") as handle, \
            open(inventory_path, "a", encoding="utf-8") as inventory:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as err:
                note_problem(problems, "line %d: %s" % (number, err))
                continue
            name = row.get("file")
            digest = row.get("sha256")
            if not name or not digest:
                note_problem(problems,
                             "line %d names %r with digest %r"
                             % (number, name, digest))
                continue
            recorded_rows += 1
            if not os.path.exists(name):
                note_problem(problems, "%s is recorded but absent"
                             % name)
                continue
            actual = file_digest(name)
            size_now = os.path.getsize(name)
            checked += 1
            if actual != digest:
                note_problem(problems, "%s hashes to %s, recorded as %s"
                             % (name, actual[:16], str(digest)[:16]))
                continue
            size = row.get("bytes")
            if size is not None and size_now != int(size):
                note_problem(problems, "%s is %d bytes, recorded as %s"
                             % (name, size_now, size))
                continue
            # ONLY A CAPTURE THAT PASSED is published to the inventory:
            # group 4 reads it as "this image was held to its recorded
            # digest and matched", so an entry for a frame that failed
            # here would let that check credit a mismatch.
            inventory.write("%s\t%d\t%s\n" % (actual, size_now, name))
    if problems:
        bad("every committed capture still hashes to the digest taken "
            "when it was captured", summarise(problems),
            "%d captures unchanged since capture -- a substituted, "
            "blanked or re-encoded frame fails here whatever its index"
            % recorded_rows)
    else:
        ok("every committed capture still hashes to the digest taken "
           "when it was captured",
           "%d captures re-hashed and unchanged, byte counts included"
           % checked)


def check_provenance(document, count, inventory_path):
    """The timeline was computed from the artifacts it names.

    A timeline is only a claim about a capture set, and the claim is
    falsifiable: it records the path, the sha256 and the row count of the
    record it read, of the amendment ledger it applied, and of the
    per-capture digest sidecar it verified.  Recomputing those hashes
    turns "this file was computed from this record by this code" from a
    story into a checkable fact -- a timeline regenerated from a record
    that has since changed, or a record edited after the timeline was
    written, cannot survive it.

    It is also the EXACT, WHOLE-SET complement to the sampled luminance
    reading in group 6: the digest sidecar covers every capture, so a
    frame substituted at any index breaks a hash the timeline declares,
    whether or not that index happened to be sampled.
    """
    # EVERY EXPECTED BLOCK, NOT WHICHEVER ONES ARE THERE.  This used to
    # build the list of keys the document happened to carry and then
    # report success naming all three, so a timeline that declared one
    # sidecar -- or a regenerated one that quietly dropped the amendment
    # ledger it applied -- passed a check whose own message said the
    # ledger had been verified.  A missing block is now the strongest
    # problem of the three, because the others are at least falsifiable.
    expected_sidecars = ("manifest", "amendments", "captures")
    # THE VERDICT BELOW IS EMITTED ON EVERY INPUT, including a document
    # that declares nothing at all.  An early return here is what let a
    # shrinking report read as a passing one.
    problems = []
    observed = []
    for key in expected_sidecars:
        block = document.get(key)
        if not isinstance(block, dict):
            problems.append(
                "%s declares no attestation block at all (it is %s), so "
                "there is nothing to recompute"
                % (key, type(block).__name__))
            continue
        path = block.get("path")
        declared = block.get("sha256")
        rows = block.get("rows")
        if not path or not declared:
            problems.append("%s declares path=%r sha256=%r"
                            % (key, path, declared))
            continue
        if not os.path.exists(path):
            problems.append("%s names %s, which is not there"
                            % (key, path))
            continue
        digest = hashlib.sha256()
        counted = 0
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != declared:
            problems.append(
                "%s: %s hashes to %s, the timeline declares %s"
                % (key, path, actual[:16], str(declared)[:16]))
            continue
        # THE ROW COUNT IS PART OF THE CLAIM.  Each block states how many
        # rows the stage read out of that file, and a digest alone cannot
        # tell a reader whether the count beside it is the file's own: a
        # transposed or stale `rows` would sail past a digest check while
        # every downstream total was computed from a different number.
        # The file has just been proven byte-for-byte, so counting its
        # rows here is a measurement of the very bytes that were hashed.
        with open(path, "rb") as handle:
            for line in handle:
                if line.strip():
                    counted += 1
        if isinstance(rows, bool) or not isinstance(rows, int):
            problems.append("%s declares rows=%r, which is not a count"
                            % (key, rows))
            continue
        if rows != counted:
            problems.append(
                "%s: %s holds %d row(s), the timeline declares %d"
                % (key, path, counted, rows))
            continue
        observed.append("%s %s, %d row(s) (%s)"
                        % (key, actual[:12], counted, path))
    if problems:
        bad("the timeline names the artifacts it was computed from, and "
            "they still hash to what it recorded", summarise(problems),
            "all three of the `manifest`, `amendments` and `captures` "
            "blocks timeline.py writes, each present, each declared "
            "sha256 reproduced from the file on disk, and each declared "
            "row count equal to that file's own")
    else:
        ok("the timeline names the artifacts it was computed from, and "
           "they still hash to what it recorded", "; ".join(observed))

    # THE WHOLE-SET CHECK, AND IT IS TAKEN ONCE.  Every committed capture
    # is compared against the digest recorded at the moment it was
    # captured, which is what makes the sampled luminance reading in
    # group 6 sufficient rather than merely indicative: a frame replaced
    # at any index -- blank, duplicated, re-encoded, cropped -- fails here
    # even when that index was not among the sampled ones.
    #
    # The digests it takes are published to the shared inventory, so the
    # group 4 sweep that used to hash the same population a second time
    # reads them instead.  One pass over the pixel evidence per run.
    check_capture_digests(document, inventory_path)

    # The digest sidecar's own arithmetic: one verified digest per
    # capture, and as many as there are entries.
    #
    # UNCONDITIONAL, so the verdict cannot disappear.  It used to be
    # nested inside `if isinstance(captures, dict)`, so a timeline with
    # no `captures` block emitted NO verdict at all and the report simply
    # got one check shorter -- and "82 of 82 passed" reads exactly as
    # green as "84 of 84 passed".  Every check in this file has a defined
    # verdict on every input, and an absent declaration is one of the
    # inputs.
    captures = document.get("captures")
    rows = captures.get("rows") if isinstance(captures, dict) else None
    verified = captures.get("verified") \
        if isinstance(captures, dict) else None
    counted = (rows is not None and verified is not None and
               int(rows) == int(verified) == count)
    if counted:
        ok("every capture's digest was verified when the timeline "
           "was computed",
           "%d of %d verified, one per entry"
           % (int(verified), int(rows)))
    else:
        bad("every capture's digest was verified when the timeline "
            "was computed",
            "rows=%r verified=%r against %d entries"
            % (rows, verified, count),
            "all three equal -- an unverified capture is a frame "
            "whose provenance was never established")


def declared_number(document, key):
    """One declared constant, or the reason it cannot be read.

    Returns (value, problem); exactly one of the two is None.

    A MISSING KEY IS A PROBLEM, not a pass.  `bool` is excluded before
    the numeric test because `True == 1` in Python, so a document
    declaring `"floor": true` would otherwise compare equal to a floor of
    1.0; and a string is excluded because "0.25" is not a number the
    arithmetic in this file could use even where it reads like one.  The
    same idiom guards the attestation blocks' `rows` above.
    """
    if key not in document:
        return (None, "%s is absent" % key)
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return (None, "%s=%r is not a number" % (key, value))
    return (value, None)


def check_declared(document, count, floor, ceil, trans, rows, eps):
    """The document's own declared numbers, against its own entries.

    PRESENCE IS PART OF THE CLAIM.  Each of these comparisons used to be
    guarded by `if declared is not None`, so a timeline that declared no
    floor, no ceiling, no transition length and no total passed all of
    them -- and reported `floor=None ceil=None transition=None` as the
    evidence of having passed.  That is the failure mode this file's own
    doctrine names elsewhere: every check has a defined verdict on every
    input, and an ABSENT DECLARATION IS ONE OF THE INPUTS.  It matters
    here more than most, because these four numbers are the contract the
    rest of the timeline is judged against -- a document that simply
    omits them cannot be checked against anything, and silently reading
    that as compliance is how a hand-written timeline would pass.
    """
    problems = []
    reported = []
    for key, expected in (("floor", floor), ("ceil", ceil),
                          ("transition", trans)):
        value, problem = declared_number(document, key)
        if problem is not None:
            problems.append(problem)
        elif not near(value, expected, eps):
            problems.append("%s=%s" % (key, value))
        else:
            reported.append("%s=%s" % (key, value))
    if problems:
        bad("the timeline declares the contracted floor, ceiling and "
            "transition length", ", ".join(problems),
            "floor=%s ceil=%s transition=%s, each present and numeric"
            % (floor, ceil, trans))
    else:
        ok("the timeline declares the contracted floor, ceiling and "
           "transition length", " ".join(reported))

    declared_count, problem = declared_number(document, "frame_count")
    if problem is not None:
        bad("the timeline's declared entry count matches its entries",
            problem,
            "frame_count present and equal to the %d entries -- a "
            "document that declares no total cannot be compared with "
            "one" % count)
    elif isinstance(declared_count, float) and \
            declared_count != int(declared_count):
        bad("the timeline's declared entry count matches its entries",
            "frame_count=%r is not a whole number" % declared_count,
            "a count of entries is an integer")
    elif int(declared_count) != count:
        bad("the timeline's declared entry count matches its entries",
            "frame_count=%s against %d entries"
            % (declared_count, count),
            "equal -- a declared total that outran its own array is a "
            "hand-edited document")
    else:
        ok("the timeline's declared entry count matches its entries",
           "%d entries" % count)

    # AND THIS VERDICT DOES NOT DISAPPEAR EITHER.  It used to `return`
    # when the record's row count was unavailable, which left group 3 one
    # NAME short; the per-group equality does catch that, but it reports
    # "the timeline is short of a check" rather than the actual cause.
    # Saying which input was missing is the more useful failure.
    if rows is None:
        bad("the timeline has one entry per recorded keystroke -- no "
            "zero-delta frame was dropped or merged",
            "the record's row count was not available to compare with",
            "a readable manifest_rows fact; without it this identity "
            "cannot be measured at all")
    elif count == rows:
        ok("the timeline has one entry per recorded keystroke -- no "
           "zero-delta frame was dropped or merged",
           "%d entries == %d record rows" % (count, rows))
    else:
        bad("the timeline has one entry per recorded keystroke -- no "
            "zero-delta frame was dropped or merged",
            "%d entries against %d record rows" % (count, rows),
            "equal counts; a frame that consumed no game time is held "
            "at the floor, never optimised away")


def check_clamp(walk, floor, ceil):
    """The floor, the ceiling, and that each duration IS the clamp.

    Reported from the single walk above, which judged each entry as it
    arrived; the three lists are bounded examples, and the counts are
    exact.
    """
    if walk.out_of_range:
        bad("every on-screen duration is inside the floor and the "
            "ceiling", summarise(walk.out_of_range),
            "%s <= duration <= %s on all %d entries"
            % (floor, ceil, walk.count))
    else:
        ok("every on-screen duration is inside the floor and the "
           "ceiling",
           "%d entries, all within %s .. %s s"
           % (walk.count, floor, ceil))

    if walk.not_clamped:
        bad("every duration is exactly the clamped clock delta",
            summarise(walk.not_clamped),
            "duration == min(max(raw_delta, %s), %s) rounded to 3 dp"
            % (floor, ceil))
    else:
        ok("every duration is exactly the clamped clock delta",
           "%d entries; the sidebar clock is the only source of pacing"
           % walk.count)

    if walk.negative:
        bad("no clock delta runs backwards", summarise(walk.negative),
            "raw_delta >= 0 everywhere -- the midnight rollover guard "
            "turns 23:59:58 -> 00:00:04 into +6 s, not -86394 s")
    else:
        ok("no clock delta runs backwards",
           "%d deltas, none negative" % walk.count)


def check_flags(walk, ceil, document):
    """transition_after <=> raw_delta > ceiling, in both directions."""
    problems = walk.flagged_without + walk.over_without_flag
    if problems:
        detail = summarise(problems)
        if walk.at_ceiling:
            detail += " (exactly at the ceiling: %s)" % summarise(
                walk.at_ceiling)
        bad("a transition is flagged exactly where the clock delta "
            "exceeded the ceiling", detail,
            "transition_after is true if and only if raw_delta > %s "
            "STRICTLY -- a delta of exactly %s is not a transition"
            % (ceil, ceil))
    else:
        ok("a transition is flagged exactly where the clock delta "
           "exceeded the ceiling",
           "%d flagged of %d entries%s"
           % (walk.flag_count, walk.count,
              ": frame(s) " + summarise(walk.flagged)
              if walk.flagged else ""))

    declared = document.get("transition_count")
    if declared is not None and int(declared) != walk.flag_count:
        bad("the timeline's declared transition count matches its flags",
            "transition_count=%s against %d flags"
            % (declared, walk.flag_count),
            "equal counts")
    elif declared is not None:
        ok("the timeline's declared transition count matches its flags",
           "transition_count=%s" % declared)


def check_cues(walk, trans):
    """Every cue window, walked as the film will actually play.

    A cue occupies [cue_start, cue_end) with cue_end - cue_start equal to
    the frame's on-screen duration; the next cue begins where this one
    ended, PLUS the inserted transition second when one was flagged.
    That last clause is the whole of silent failure mode 3: a generator
    that walks durations without charging the insertion produces cues
    that are right at the start and increasingly wrong by the end.

    The cursor was walked in the single pass above -- the same pass that
    read the durations and the flags, because it is the same walk.
    """
    if walk.window_problems:
        bad("every cue window is exactly as long as its frame is on "
            "screen", summarise(walk.window_problems),
            "cue_end - cue_start == duration on all %d entries"
            % walk.count)
    else:
        ok("every cue window is exactly as long as its frame is on "
           "screen", "%d windows" % walk.count)
    if walk.walk_problems:
        bad("the cue cursor is charged for every inserted transition "
            "second", summarise(walk.walk_problems),
            "each cue begins where the previous ended, plus %s s "
            "wherever a transition was inserted" % trans)
    else:
        ok("the cue cursor is charged for every inserted transition "
           "second",
           "walked %d cues to %.3f s with no drift"
           % (walk.count, walk.cursor))
    return round(walk.cursor, 3)


def check_invariant(walk, document, trans, walked, eps):
    """sum(durations) + sum(transitions) == total == final cue end.

    Both sums were accumulated by the walk: the durations as they were
    clamped-checked, the transitions as they were flagged.
    """
    sum_durations = walk.sum_durations
    sum_transitions = round(walk.flag_count * float(trans), 3)
    computed = round(sum_durations + sum_transitions, 3)

    declared_duration = document.get("total_duration")
    declared_transition = document.get("total_transition")
    declared_total = document.get("total")
    declared_cue_end = document.get("final_cue_end")
    last_cue_end = walk.last_cue_end

    parts = []
    if declared_duration is not None and not near(declared_duration,
                                                  sum_durations, eps):
        parts.append("total_duration=%s but the durations sum to %s"
                     % (declared_duration, sum_durations))
    if declared_transition is not None and not near(
            declared_transition, sum_transitions, eps):
        parts.append("total_transition=%s but %d flags x %s = %s"
                     % (declared_transition, walk.flag_count, trans,
                        sum_transitions))
    if declared_total is not None and not near(declared_total, computed,
                                               eps):
        parts.append("total=%s but %s + %s = %s"
                     % (declared_total, sum_durations, sum_transitions,
                        computed))
    if declared_cue_end is not None and not near(declared_cue_end,
                                                 computed, eps):
        parts.append("final_cue_end=%s but the computed total is %s"
                     % (declared_cue_end, computed))
    if not near(last_cue_end, computed, eps):
        parts.append("the last entry ends at %s, not %s"
                     % (last_cue_end, computed))
    if not near(walked, computed, eps):
        parts.append("the independent cue walk reached %s, not %s"
                     % (walked, computed))

    if parts:
        bad("the timeline invariant holds: sum(durations) + "
            "sum(transitions) == total == final cue end",
            summarise(parts, 8),
            "%s + %s == %s, and the last cue ends there"
            % (sum_durations, sum_transitions, computed))
    else:
        ok("the timeline invariant holds: sum(durations) + "
           "sum(transitions) == total == final cue end",
           "%.3f + %.3f = %.3f s, and the final cue ends at %.3f s"
           % (sum_durations, sum_transitions, computed,
              float(last_cue_end)))
    return computed


def check_transitions(transitions_dir, flagged, per_group):
    """The materialised transition images, against the flags.

    Group count must equal flag count and each group must hold exactly
    `per_group` images with contiguous ordinals.  Anything else
    desynchronises the film from the cues by exactly the error, once per
    transition -- and it is not detectable by watching either artifact
    alone.
    """
    try:
        entries = sorted(os.listdir(transitions_dir))
    except OSError as err:
        bad("the transition images directory is readable", str(err),
            "a readable directory beside the captures, never inside "
            "them")
        return 0
    images = [e for e in entries if TRANS_RE.match(e)]
    strays = [e for e in entries if not TRANS_RE.match(e)]
    groups = {}
    for name in images:
        match = TRANS_RE.match(name)
        groups.setdefault(int(match.group(1)), []).append(
            int(match.group(2)))

    if strays:
        bad("the transition directory holds transition images and "
            "nothing else", summarise(strays),
            "only trans_NNNNN_MM.png")
    else:
        ok("the transition directory holds transition images and "
           "nothing else", "%d images in %d group(s)"
           % (len(images), len(groups)))

    flagged_set = sorted(int(f) for f in flagged if f is not None)
    if sorted(groups) == flagged_set:
        ok("one materialised transition group per flagged frame",
           "group(s) for frame(s) %s" % (summarise(flagged_set) or
                                         "none"))
    else:
        bad("one materialised transition group per flagged frame",
            "groups for %s against flags for %s"
            % (summarise(sorted(groups)) or "none",
               summarise(flagged_set) or "none"),
            "identical sets -- a group without a flag is orphaned "
            "footage, a flag without a group is a missing second")

    wrong = []
    for number in sorted(groups):
        ordinals = sorted(groups[number])
        if ordinals != list(range(per_group)):
            wrong.append("frame %s has %d image(s) %s"
                         % (number, len(ordinals), summarise(ordinals)))
    if wrong:
        bad("each transition group holds its full complement of images",
            summarise(wrong),
            "exactly %d images per group, ordinals 00 .. %02d"
            % (per_group, per_group - 1))
    else:
        ok("each transition group holds its full complement of images",
           "%d group(s) x %d images" % (len(groups), per_group))
    return len(groups)


def main(argv):
    (timeline_path, transitions_dir, tooling_dir, facts_path,
     windows_path, digests_index, floor, ceil, trans, per_group,
     tolerance, epsilon) = argv[1:13]
    floor = float(floor)
    ceil = float(ceil)
    trans = float(trans)
    per_group = int(per_group)
    tolerance = float(tolerance)
    epsilon = float(epsilon)

    rows = None
    if os.path.exists(facts_path):
        with open(facts_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("manifest_rows="):
                    rows = int(line.split("=", 1)[1].strip())

    check_constants(tooling_dir, floor, ceil, trans, per_group,
                    tolerance, epsilon)

    # THE DOCUMENT, READ IN TWO PARTS AND HELD IN NEITHER.  The header is
    # everything except the entries -- the provenance blocks, the declared
    # constants, the declared totals -- and the entries are an event
    # stream from the producer's own reader.  Both come from timeline.py,
    # so the reader of these bytes cannot drift from the writer of them.
    sys.path.insert(0, tooling_dir)
    # EMPTIED FIRST, ON EVERY PATH.  The window list is what the pixel
    # probes in groups 4, 5 and 6 compute their offsets from, and a list
    # left over from anything but this walk would send them into a fade.
    # The scratch generation is per-run so there is nothing to inherit
    # today, but the guarantee is made here rather than assumed.
    with open(windows_path, "w", encoding="utf-8"):
        pass
    try:
        import timeline as tl
        header = tl.read_timeline_header(timeline_path)
    except Exception as err:                              # noqa: BLE001
        bad("the timeline parses as JSON", str(err),
            "a JSON object carrying a frames array")
        return 0

    entries, document, shape = entries_and_shape(header, timeline_path,
                                                 tl)
    try:
        walk = walk_entries(entries, floor, ceil, trans, epsilon,
                            windows_path)
    except Exception as err:                              # noqa: BLE001
        # A malformed entry is a document that does not parse, and it is
        # reported as exactly that.  The window list is emptied again
        # because a PARTIAL one -- written up to the bad entry -- would
        # send the pixel probes to offsets computed from half a timeline.
        with open(windows_path, "w", encoding="utf-8"):
            pass
        bad("the timeline parses as JSON", str(err),
            "a JSON object carrying a frames array")
        return 0

    if not walk.count:
        bad("the timeline carries per-frame entries", shape,
            "an object with a non-empty frames array, or a bare array")
        return 0
    ok("the timeline parses and carries per-frame entries",
       "%s, %d entries" % (shape, walk.count))

    check_provenance(document, walk.count, digests_index)
    check_declared(document, walk.count, floor, ceil, trans, rows,
                   epsilon)
    check_clamp(walk, floor, ceil)
    check_flags(walk, ceil, document)
    walked = check_cues(walk, trans)
    total = check_invariant(walk, document, trans, walked, epsilon)
    groups = check_transitions(transitions_dir, walk.flagged, per_group)

    info("clock readings reconciled against the previous frame rather "
         "than guessed",
         "%d of %d entries" % (walk.reconciled, walk.count))
    # WHERE THE CEILING ENGAGED, BOUNDED.  Every flagged frame used to be
    # joined into this one line, so a session that slept through a
    # thousand nights put a thousand clauses into one verdict -- and into
    # one shell variable on the way to the report.  The count is the fact;
    # a handful of examples is the illustration.
    info("where the ceiling engaged",
         ("%d place(s): %s"
          % (walk.flag_count,
             illustrate(walk.ceiling_detail, walk.flag_count)))
         if walk.flag_count else
         "nowhere -- no delta exceeded the ceiling")

    with open(facts_path, "a", encoding="utf-8") as handle:
        handle.write("timeline_entries=%d\n" % walk.count)
        handle.write("timeline_total=%.3f\n" % total)
        handle.write("transition_flags=%d\n" % walk.flag_count)
        handle.write("transition_groups=%d\n" % groups)
        handle.write("transition_images=%d\n" % (groups * per_group))
        handle.write("expected_images=%d\n"
                     % (walk.count + groups * per_group))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_timeline() {
    group 3 "the timeline: the floor, the ceiling and the invariant"
    run_checker timeline \
        "${PLAYTHROUGH_TIMELINE}" \
        "${PLAYTHROUGH_TRANSITIONS_DIR}" \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "${SCRATCH}/facts" \
        "$(windows_file)" \
        "$(digest_inventory)" \
        "${DURATION_FLOOR}" \
        "${DURATION_CEIL}" \
        "${TRANSITION_SECONDS}" \
        "${TRANSITION_FRAMES_PER_GROUP}" \
        "${CONTAINER_TOLERANCE}" \
        "${ARITHMETIC_EPSILON}"
}


# ---------------------------------------------------------------------
# 4  THE CONTAINER
#
# 1920x1080 and not 1920x1072.  The game's window is 1072 pixels tall --
# 67 rows of a 16-pixel font (src/sdltiles.cpp:595-596), windowed
# borderless by default (src/options.cpp:2715-2724) -- but what is
# photographed is the X ROOT, which is exactly 1920x1080.  A film at 1072
# would mean the window was captured instead, and the four-pixel
# letterbox is the visible sign that the root was.
#
# The duration is compared against the timeline's own total.  A SHORTFALL
# is the signature of a concat list whose final `file` entry was not
# repeated after its `duration` line, which was measured once as a
# 10.52 s container against an 11.75 s subtitle stream: the film simply
# stops before its captions do.
# ---------------------------------------------------------------------
check_container_streams() {
    local file="$1"
    local label="$2"
    local codec="" width="" height="" pix=""
    local codec_said="" size_said="" pix_said=""
    codec="$(probe_value "${file}" v:0 stream=codec_name)"
    codec_said="$(because ffprobe)"
    width="$(probe_value "${file}" v:0 stream=width)"
    height="$(probe_value "${file}" v:0 stream=height)"
    size_said="$(because ffprobe)"
    pix="$(probe_value "${file}" v:0 stream=pix_fmt)"
    pix_said="$(because ffprobe)"

    if [ "${codec}" = "${VIDEO_CODEC_EXPECTED}" ]; then
        record_pass "${label} carries a ${VIDEO_CODEC_EXPECTED} video \
stream" "codec_name=${codec}"
    else
        record_fail "${label} carries a ${VIDEO_CODEC_EXPECTED} video \
stream" "codec_name=${codec:-<no video stream>}${codec_said}" \
            "${VIDEO_CODEC_EXPECTED}"
    fi

    if [ "${width}" = "${PLAYTHROUGH_SCREEN_WIDTH}" ] &&
            [ "${height}" = "${PLAYTHROUGH_SCREEN_HEIGHT}" ]; then
        record_pass "${label} is at the X root's own resolution" \
            "${width}x${height}"
    else
        record_fail "${label} is at the X root's own resolution" \
            "${width:-?}x${height:-?}${size_said}" \
            "${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT} \
-- 1920x1072 would mean the game window was photographed instead of \
the root"
    fi

    if [ "${pix}" = "yuv420p" ]; then
        record_pass "${label} uses the broadly playable pixel format" \
            "pix_fmt=${pix}"
    else
        record_fail "${label} uses the broadly playable pixel format" \
            "pix_fmt=${pix:-<unknown>}${pix_said}" \
            "yuv420p -- anything else is unplayable in a large share \
of players"
    fi
}

check_container_duration() {
    local total="" duration="" delta="" said=""
    total="$(fact timeline_total)"
    duration="$(probe_format "${PLAYTHROUGH_MOVIE}" duration)"
    said="$(because ffprobe)"
    if ! is_real "${total}"; then
        record_fail "the film is as long as the timeline says" \
            "the timeline total could not be established" \
            "a numeric total from playthrough/timeline.json"
        return 0
    fi
    if ! is_real "${duration}"; then
        record_fail "the film is as long as the timeline says" \
            "ffprobe reported duration=${duration:-<nothing>}${said}" \
            "a numeric container duration"
        return 0
    fi
    delta="$("${AWK}" -v a="${duration}" -v b="${total}" \
        'BEGIN { d = a - b; printf "%.3f", d }')"
    if floats_close "${duration}" "${total}" \
            "${CONTAINER_TOLERANCE}"; then
        record_pass "the film is as long as the timeline says" \
            "container ${duration}s against timeline ${total}s \
(delta ${delta}s, tolerance ${CONTAINER_TOLERANCE}s)"
        return 0
    fi
    record_fail "the film is as long as the timeline says" \
        "container ${duration}s against timeline ${total}s (delta \
${delta}s)" \
        "within ${CONTAINER_TOLERANCE}s -- a shortfall means the concat \
list did not repeat its final 'file' entry, so the last duration never \
took effect"
}

# "No audio stream" is only worth asserting about a container ffprobe can
# actually read.  A file it cannot parse reports no audio too, and
# accepting that as a pass would be the kind of vacuous verdict this gate
# exists to prevent -- so an unreadable container fails HERE as well,
# rather than being silently credited with an absence.
check_no_audio() {
    local file="" label="" streams="" video="" said=""
    for file in "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"; do
        label="$(rel "${file}")"
        video="$(probe_value "${file}" v:0 stream=codec_name)"
        said="$(because ffprobe)"
        if [ -z "${video}" ]; then
            record_fail "${label} carries no audio stream" \
                "the container has no readable video stream either, so \
the absence of audio proves nothing about it${said}" \
                "a readable container with a video stream and no audio \
stream"
            continue
        fi
        streams="$(probe_field "${file}" a 'stream=index' |
            "${GREP}" -c '^index=' || true)"
        if [ "${streams:-0}" = "0" ]; then
            record_pass "${label} carries no audio stream" \
                "no audio: the session was muted \
(SOUND_ENABLED=false, SDL_AUDIODRIVER=dummy) and nothing was narrated"
        else
            record_fail "${label} carries no audio stream" \
                "${streams} audio stream(s)" \
                "none -- this film has no music, no effects and no \
narration"
        fi
    done
}

# THE FRAME COUNT, UNDER VARIABLE FRAME RATE.  The concat demuxer is fed
# one entry per still image -- every capture plus every materialised
# transition image -- and its final `file` entry is deliberately repeated
# so the last duration takes effect, which yields that one extra encoded
# frame.  So the count is the image inventory, or the inventory plus one,
# and nothing else.
# decoded_frames FILE -- how many pictures actually come out of it.
#
# A DECODE, not a header read: the header of a file cut to a third of its
# length still declares the full count.  The number comes from the ONE
# end-to-end pass film_decode_pass makes over each film (see ONE DECODE
# PER FILM above), so asking for it a second or third time costs nothing;
# it used to be a separate `ffprobe -count_frames` walk per question.
decoded_frames() {
    film_decode_pass "$1"
    printf '%s' "${FILM_PASS_FRAMES}"
}

check_frame_count() {
    local expected="" observed="" said=""
    expected="$(fact expected_images)"
    observed="$(decoded_frames "${PLAYTHROUGH_MOVIE}")"
    said="$(because ffprobe)"
    if ! is_count "${observed}"; then
        # THE FALLBACK IS A HEADER-FREE PACKET WALK, and it is reached
        # only when the decode pass could not report a count at all -- a
        # wedged decode, a container the decoder refuses.  It is bounded
        # like every other child here.
        observed="$(bounded "$(film_bound "${PLAYTHROUGH_MOVIE}")" \
            "${FFPROBE}" -v error -select_streams v:0 \
            -count_packets -show_entries stream=nb_read_packets \
            -of default=noprint_wrappers=1:nokey=1 \
            -i "${PLAYTHROUGH_MOVIE}" \
            2>"$(tool_error_file ffprobe)" | "${HEAD}" -n 1 || true)"
        said="$(because ffprobe)"
    fi
    if ! is_count "${expected}" || ! is_count "${observed}"; then
        record_fail "the film holds one encoded frame per still it was \
built from" \
            "expected=${expected:-?} observed=${observed:-?}${said}" \
            "both counts readable"
        return 0
    fi
    if [ "${observed}" -eq "${expected}" ] ||
            [ "${observed}" -eq "$((expected + 1))" ]; then
        record_pass "the film holds one encoded frame per still it was \
built from" \
            "${observed} frames DECODED out of it, from \
$(fact timeline_entries) captures + $(fact transition_images) \
transition images"
        return 0
    fi
    record_fail "the film holds one encoded frame per still it was \
built from" \
        "${observed} frames decoded against ${expected} stills" \
        "${expected} or ${expected} + 1 (the repeated final concat \
entry); a lower count means captures were dropped from the render, or \
the file is truncated and the pictures past the cut cannot be decoded"
}

# THE CONTAINER'S OWN CLAIM, AGAINST WHAT COMES OUT OF IT.
#
# nb_frames lives in the moov atom, which -movflags +faststart puts at the
# FRONT of the file; a film truncated to a third of its length still
# declares every frame it once had.  So the header is read and the stream
# is decoded, and the two must agree.  A container that declares no
# nb_frames at all is NOT a failure -- that is ordinary under variable
# frame rate, which is how this film is encoded -- and the honest reading
# is reported instead.
check_declared_frames_agree() {
    local file="" label="" declared="" decoded="" said=""
    for file in "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"; do
        label="$(rel "${file}")"
        declared="$(probe_value "${file}" v:0 stream=nb_frames)"
        decoded="$(decoded_frames "${file}")"
        said="$(because ffprobe)"
        if ! is_count "${decoded}"; then
            record_fail "${label} decodes as many frames as it declares" \
                "no frame could be decoded out of it (declared \
${declared:-N/A})${said}" \
                "a decodable video stream"
            continue
        fi
        if ! is_count "${declared}"; then
            record_pass "${label} decodes as many frames as it declares" \
                "the container declares no nb_frames, which is ordinary \
under variable frame rate, so the decoded count ${decoded} is the only \
reading and it is the one used"
            continue
        fi
        if [ "${declared}" -eq "${decoded}" ]; then
            record_pass "${label} decodes as many frames as it declares" \
                "${decoded} decoded == ${declared} declared"
            continue
        fi
        record_fail "${label} decodes as many frames as it declares" \
            "${decoded} decoded against ${declared} declared" \
            "equal counts -- nb_frames comes from the moov atom at the \
front of the file and survives truncation, so a shortfall here is data \
that is gone"
    done
}

# THE WHOLE FILM, DECODED.  Every packet through the decoder with
# -xerror, so a corrupt NAL unit, a partial final packet or a missing
# picture is a failure rather than a warning nobody sees.
#
# THE PASS ITSELF IS SHARED with the two frame-count checks above: it is
# made once per film by film_decode_pass and read here from the scratch
# generation, which is what keeps a gate over an unbounded film to one
# decode of it rather than three.  Measured cost on this session: 0.9 s
# for the base film's single pass, against 4.5 s for the three walks it
# replaces.
check_film_decodes() {
    local file="" label="" detail=""
    for file in "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"; do
        label="$(rel "${file}")"
        film_decode_pass "${file}"
        if [ "${FILM_PASS_STATUS}" = "0" ] &&
                [ ! -s "${FILM_PASS_LOG}" ]; then
            record_pass "${label} decodes from end to end" \
                "every packet through the decoder with -xerror, \
${FILM_PASS_FRAMES:-no} frame(s) decoded, no diagnostic on stderr"
            continue
        fi
        detail="$(excerpt "${FILM_PASS_LOG}" 2)"
        if bound_expired "${FILM_PASS_STATUS}"; then
            record_fail "${label} decodes from end to end" \
                "the decode did not finish within \
${FILM_PASS_CEILING}s and was stopped (exit ${FILM_PASS_STATUS}): \
${detail:-<no diagnostic>}" \
                "a clean decode inside the ceiling derived from this \
film's own byte count -- the floor throughput that ceiling assumes is \
far below what any host achieves, so an expiry means the decoder is \
wedged rather than that the film is long"
            continue
        fi
        record_fail "${label} decodes from end to end" \
            "ffmpeg exited ${FILM_PASS_STATUS} and reported: \
${detail:-<no diagnostic>}" \
            "a clean decode -- the container's metadata is read from the \
moov atom and cannot see missing picture data, so the pictures \
themselves are decoded here"
    done
}

# ---------------------------------------------------------------------
# THE RENDER INPUTS
#
# The container facts above are read from the film's own metadata, and
# metadata is not the film.  Two whole classes of fault live in that gap:
#
#   * THE LIST THE ENCODER WAS GIVEN.  playthrough/build/concat.txt is
#     what paces the film -- one `file` line and one `duration` line per
#     still, and the final `file` line repeated so the last duration
#     takes effect.  A list whose durations were rewritten, or whose
#     repeated final entry was tidied away, produces a film that no
#     longer matches the captions; and because the film is built BEFORE
#     this gate runs, its metadata satisfies every duration check
#     regardless of what the list says.  Measured: a list summing to
#     212.5 s beside a timeline of 219.5 s passed every check this gate
#     used to make.
#
#   * THE FILM'S OWN BYTES.  `-movflags +faststart` places the moov atom
#     at the FRONT of the file, so codec, resolution, pixel format,
#     duration and nb_frames all survive gross data loss: a film
#     truncated to a third of its length still reports 1920x1080 h264,
#     219.56 s and 339 frames.  The render stage already declares the
#     film's sha256 and byte count in build/movie.json, so holding the
#     file to that declaration costs nothing and closes the gap.
#
# The list is checked by RE-DERIVING it from the committed timeline with
# render_movie.py's own planner and comparing byte-for-byte, which is
# stronger than any list of properties: the list is a pure function of
# the timeline, so anything that differs is a film built from inputs the
# timeline does not describe.
# ---------------------------------------------------------------------
emit_render_checker() {
    emit_checker render <<'PY'
"""Assert the render inputs and the film's declared identity."""

import hashlib
import io
import json
import os
import sys

SEP = "\x1f"


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def summarise(items, limit=5):
    shown = "; ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += "; ... (%d more)" % (len(items) - limit)
    return shown


# HOW MANY FINDINGS ONE VERDICT COLLECTS.  The concat list is two lines
# per still and the stills are one per keystroke, so a list that
# disagrees with the timeline everywhere would otherwise put one
# diagnostic per keystroke into memory to explain it.
PROBLEM_LIMIT = 200


def note_problem(problems, text, limit=PROBLEM_LIMIT):
    """Collect a finding, bounded; past the limit, say so once."""
    if len(problems) < limit:
        problems.append(text)
        return
    if len(problems) == limit:
        problems.append("... further findings were not collected; the "
                        "%d above are the ones this verdict carries"
                        % limit)


def digest(path):
    """A streamed sha256, so a film is not held in memory."""
    accumulator = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            accumulator.update(chunk)
    return accumulator.hexdigest()


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_list_lines(path, prefix, suffix, duration_prefix):
    """The committed list as (kind, value, line number), STREAMED.

    Parsed with the WRITER'S OWN prefixes, imported from render_movie,
    so the reader of these bytes cannot drift from the writer of them.
    Anything that is neither a file line nor a duration line is yielded
    as a stray, because a concat list with a comment or a blank line in
    it is not the list the writer produces.

    The list is two lines per still image and the still images are one
    per keystroke plus one per transition frame, so its length is the
    session's.  It used to be read into one string and split into a list
    of every entry; now the file is walked once and nothing but the entry
    in hand survives.
    """
    with open(path, "r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.rstrip("\n")
            if line.startswith(prefix) and line.endswith(suffix):
                yield ("file", line[len(prefix):-len(suffix)], number)
            elif line.startswith(duration_prefix):
                yield ("duration",
                       line[len(duration_prefix):].strip(), number)
            elif line.strip():
                yield ("stray", line[:60], number)


def iter_expected(frames, seconds, per_group):
    """The (path, duration) sequence this timeline implies, STREAMED.

    Derived from the timeline entries and the transition arithmetic
    rather than from render_movie's planner, on purpose: the planner's
    own output is compared byte-for-byte in the first check, and a
    SECOND, independent derivation is what makes the structural verdicts
    below meaningful when the planner cannot run at all.

    `frames` is itself an iterator over the timeline's entries, so the
    implied sequence is produced as it is consumed and neither the
    entries nor the sequence is ever a resident list.
    """
    share = seconds / float(per_group) if per_group else 0.0
    for entry in frames:
        index = entry.get("frame")
        yield ("../frames/%s" % os.path.basename(
            str(entry.get("file", ""))), entry.get("duration"))
        if not entry.get("transition_after"):
            continue
        for ordinal in range(per_group):
            yield ("transitions/trans_%05d_%02d.png"
                   % (index, ordinal), share)


def check_planned(rm, document, timeline_path, concat_path):
    """The committed list against the producer's own re-derivation.

    THE COMMITTED BYTES ARE STREAMED past the re-derived text rather than
    read into a second copy of it.  The list is two lines per still and
    the stills are one per keystroke, so at the session lengths this
    pipeline is built for it is tens of megabytes; the comparison used to
    hold the committed copy, the re-derived copy, and then a split list of
    each copy's lines to describe a difference.  The re-derived text is
    the planner's own return value and is unavoidable here -- it is what
    the committed bytes are being held to -- but nothing else is.
    """
    try:
        plan = rm.plan_render(document, None, timeline_path)
        rewritten = rm.format_concat_list(plan)
    except Exception as err:                          # noqa: BLE001
        bad("the concat list is exactly the list this timeline plans",
            "the render stage's own planner refuses this timeline: %s"
            % err,
            "a plan -- render_movie.plan_render() resolves every capture "
            "and every transition group before an encode, so a timeline "
            "it refuses could not have produced the committed list")
        return None
    differences, committed_bytes = compare_streamed(
        concat_path, rewritten)
    if not differences:
        ok("the concat list is exactly the list this timeline plans",
           "%d bytes reproduced byte-for-byte by "
           "render_movie.plan_render() and format_concat_list() from "
           "%s" % (committed_bytes, timeline_path))
        return plan
    bad("the concat list is exactly the list this timeline plans",
        "the committed list differs from the re-derived one: %s"
        % summarise(differences),
        "identical text -- the list is a pure function of the timeline, "
        "so any difference means the film was encoded from inputs the "
        "timeline does not describe")
    return plan


def compare_streamed(path, wanted, limit=3):
    """(bounded differences, committed byte count) for one file.

    The file is read line by line beside the planned text's own lines, so
    a difference is found where it is rather than by diffing two whole
    documents, and at most `limit` of them are described.
    """
    differences = []
    committed_bytes = 0
    planned = io.StringIO(wanted)
    number = 0
    with open(path, "r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            committed_bytes += len(raw.encode("utf-8"))
            expected = planned.readline()
            if raw == expected:
                continue
            if not expected:
                differences.append("line %d is %r, and the plan ends at "
                                   "line %d" % (number, raw.rstrip("\n"),
                                                number - 1))
                break
            if len(differences) < limit:
                differences.append("line %d is %r, planned %r"
                                   % (number, raw.rstrip("\n"),
                                      expected.rstrip("\n")))
    remaining = planned.readline()
    if remaining:
        differences.append("the committed list ends at line %d and the "
                           "plan continues with %r"
                           % (number, remaining.rstrip("\n")))
    return differences, committed_bytes


def walk_list(concat_path, rm, frames, seconds, per_group, eps):
    """One pass over the committed list beside the sequence it implies.

    EVERYTHING THE THREE STRUCTURAL VERDICTS NEED, MEASURED ONCE.  The
    list was previously parsed into a list of every entry, the timeline
    into a list of every implied entry, and those two into a third list of
    pairs -- three populations of the session's length to answer three
    questions about their agreement.  Here the two streams are consumed in
    lockstep, each pair is compared as it arrives, and what survives the
    walk is a handful of counters plus bounded findings.

    Returns a dict of what the verdicts below report on.
    """
    problems = []
    strays = []
    pairs = 0
    measured = 0.0
    timed = 0
    last_timed = None
    pending = None
    files = 0
    durations = 0
    wanted = iter_expected(frames, seconds, per_group)
    expected_count = 0

    def compare(name, duration):
        """One committed (image, duration) against the implied one."""
        nonlocal pairs, measured, timed, last_timed, expected_count
        pairs += 1
        try:
            want_name, want_duration = next(wanted)
            expected_count += 1
        except StopIteration:
            note_problem(problems,
                         "entry %d names %r and the timeline implies no "
                         "entry there" % (pairs, name))
            return
        if name != want_name:
            note_problem(problems,
                         "entry %d names %r, the timeline implies %r"
                         % (pairs, name, want_name))
            return
        if duration is None:
            note_problem(problems, "entry %d (%s) has no duration line"
                         % (pairs, name))
            return
        try:
            value = float(duration)
        except (TypeError, ValueError):
            note_problem(problems,
                         "entry %d (%s) has the unreadable duration %r"
                         % (pairs, name, duration))
            return
        measured += value
        timed += 1
        last_timed = name
        try:
            if abs(value - float(want_duration)) > eps:
                note_problem(problems,
                             "entry %d (%s) is %s s, the timeline says "
                             "%s s" % (pairs, name, duration,
                                       want_duration))
        except (TypeError, ValueError):
            note_problem(problems,
                         "entry %d (%s) is %s s and the timeline implies "
                         "%r" % (pairs, name, duration, want_duration))

    for kind, value, number in iter_list_lines(
            concat_path, rm.CONCAT_FILE_PREFIX, rm.CONCAT_FILE_SUFFIX,
            rm.CONCAT_DURATION_PREFIX):
        if kind == "stray":
            note_problem(strays, "line %d: %r" % (number, value))
            continue
        if kind == "duration":
            durations += 1
            if pending is None:
                note_problem(problems,
                             "a duration line with no image before it "
                             "at line %d" % number)
                continue
            compare(pending, value)
            pending = None
            continue
        files += 1
        if pending is not None:
            # A file line with no duration after it, and another file
            # line following: the entry is real and its duration is
            # missing, which compare() reports.
            compare(pending, None)
        pending = value
    # The final entry is the repeat and carries no duration of its own;
    # it is judged by check_repeat, so it is not compared here.
    repeated = pending
    for _ in wanted:
        expected_count += 1
    return {
        "problems": problems,
        "strays": strays,
        "pairs": pairs,
        "expected": expected_count,
        "sum": measured,
        "timed": timed,
        "last_timed": last_timed,
        "repeated": repeated,
        "files": files,
        "durations": durations,
    }


def check_structure(walk):
    """One image, one duration, in timeline order."""
    if walk["problems"] or walk["pairs"] != walk["expected"]:
        problems = list(walk["problems"])
        if walk["pairs"] != walk["expected"]:
            note_problem(problems,
                         "%d image entries against %d the timeline "
                         "implies" % (walk["pairs"], walk["expected"]))
        bad("the concat list carries one image and one duration per "
            "capture and per transition image, in timeline order",
            summarise(problems),
            "%d pairs in frame order, each flagged capture followed by "
            "its transition group" % walk["expected"])
    else:
        ok("the concat list carries one image and one duration per "
           "capture and per transition image, in timeline order",
           "%d image/duration pairs, every path and every duration the "
           "timeline's own" % walk["pairs"])


def check_repeat(walk):
    """The repeated final entry, without which the film comes up short.

    THE RELATION IS THE PRODUCER'S OWN: exactly one more `file` line than
    `duration` lines, because every entry contributes both and the final
    entry contributes one extra file line.  render_movie.concat_counts()
    asserts it on the text it wrote; this asserts it on the committed
    bytes from the counts the streaming walk above took with the
    producer's own prefixes, rather than reading the whole list into a
    string to hand to that function.
    """
    files = walk["files"]
    durations = walk["durations"]
    if walk["repeated"] is None or not walk["pairs"]:
        bad("the concat list repeats its final entry, so the last "
            "duration takes effect",
            "the list ends with a duration line rather than a repeated "
            "image (%d file, %d duration)" % (files, durations),
            "the final `file` line written once more with no duration "
            "after it -- without it the last duration never takes "
            "effect and the container is short by exactly that entry, "
            "measured once as a 10.52 s film against an 11.75 s "
            "subtitle stream")
        return
    if files != durations + 1:
        bad("the concat list repeats its final entry, so the last "
            "duration takes effect",
            "%d file line(s) against %d duration line(s)"
            % (files, durations),
            "exactly one more file line than duration lines, which is "
            "render_movie.concat_counts()'s own relation: every entry "
            "contributes both and the repeated final entry contributes "
            "the extra file line")
        return
    if walk["repeated"] != walk["last_timed"]:
        bad("the concat list repeats its final entry, so the last "
            "duration takes effect",
            "the list ends by repeating %r, but its last timed entry is "
            "%r" % (walk["repeated"], walk["last_timed"]),
            "the same image repeated, so ffmpeg holds the last frame "
            "for the duration written above it")
        return
    ok("the concat list repeats its final entry, so the last duration "
       "takes effect",
       "%d file lines against %d duration lines; the repeat is %s"
       % (files, durations, walk["repeated"]))


def check_sum(walk, total, eps):
    """The durations the encoder was given, against the timeline."""
    measured = walk["sum"]
    if total is None:
        bad("the concat list's durations sum to the timeline's own "
            "total", "%.6f s in the list, and the timeline declares no "
            "total" % measured,
            "a declared total to compare against")
        return
    if abs(measured - float(total)) <= eps:
        ok("the concat list's durations sum to the timeline's own total",
           "%.6f s over %d entries against the timeline's %.3f s"
           % (measured, walk["timed"], float(total)))
        return
    bad("the concat list's durations sum to the timeline's own total",
        "%.6f s over %d entries against the timeline's %.3f s (%+.6f s)"
        % (measured, walk["timed"], float(total), measured - float(total)),
        "equal within %g s -- the list is what paces the film, so a list "
        "that sums to something else produces a film the captions do not "
        "fit" % eps)


class Digests(object):
    """The digests this run has already taken, and the ones it takes.

    GROUP 3 HASHED EVERY CAPTURE ALREADY.  It swept the whole committed
    capture set against build/frame_digests.jsonl and appended each digest
    it verified to the shared inventory, so the question this checker asks
    of a capture -- "is this image the one that was recorded" -- has been
    answered for every one of them.  Reading that answer instead of
    hashing the population a second time is the difference between one
    pass over the pixel evidence per run and two; at the session lengths
    this pipeline is built for the second pass is tens of gigabytes of
    reading for a result already on disk.

    The inventory is loaded as a SET OF PATHS rather than a map of
    digests: what is needed here is membership -- was this image held to
    its recorded digest and did it match -- and a set of names is a
    fraction of the footprint of a map of hex strings.

    Anything NOT in it is hashed here, once, and memoised: the
    materialised transition images are the real case, and they were
    hashed twice over by the two checks below before this existed.  The
    memo is bounded by the transition population rather than by the
    session.  The capture sidecar is read only if a capture turns up
    outside the inventory at all, which is what keeps this checker
    correct when it is run without group 3 having run first.
    """

    def __init__(self, inventory_path, sidecar_path):
        self.inventory_path = inventory_path
        self.sidecar_path = sidecar_path
        self.verified = set()
        self.taken = {}
        self.sidecar = None
        self.reused = 0
        self.hashed = 0
        if inventory_path and os.path.exists(inventory_path):
            with open(inventory_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    fields = line.rstrip("\n").split("\t", 2)
                    if len(fields) == 3:
                        self.verified.add(os.path.normpath(fields[2]))

    def already_verified(self, path):
        """Whether group 3 held this exact file to its recorded digest."""
        if os.path.normpath(path) in self.verified:
            self.reused += 1
            return True
        return False

    def of(self, path):
        """This file's sha256, computed at most once per run."""
        key = os.path.normpath(path)
        if key not in self.taken:
            self.taken[key] = digest(path)
            self.hashed += 1
        return self.taken[key]

    def recorded_for(self, path):
        """What the capture sidecar recorded for a capture, or None.

        Read lazily, and only when a capture is named that the inventory
        does not carry -- a checker run on its own, or a list naming a
        frame the sweep never saw.
        """
        if self.sidecar is None:
            self.sidecar = load_capture_digests(self.sidecar_path)
        return self.sidecar.get(os.path.normpath(path))


def load_capture_digests(path):
    recorded = {}
    if not path or not os.path.exists(path):
        return recorded
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("file") and row.get("sha256"):
                recorded[os.path.normpath(row["file"])] = (
                    row["sha256"], row.get("bytes"))
    return recorded


def load_transition_digests(document, directory):
    recorded = {}
    groups = document.get("groups") if isinstance(document, dict) else []
    for group in groups or []:
        for output in group.get("outputs", []) or []:
            name = output.get("name")
            if not name or not output.get("sha256"):
                continue
            recorded[os.path.normpath(os.path.join(directory, name))] = (
                output["sha256"], output.get("bytes"))
    return recorded


def check_named_images(names, base, digests, transitions):
    """Every image the encoder was pointed at, as it was recorded.

    `names` is an ITERABLE of the list's image names in list order, walked
    once: the whole (path, duration) population used to be materialised
    into a second list here on top of the one the caller already held.

    A capture the group 3 sweep already held to its recorded digest is
    credited from the shared inventory rather than hashed again -- see
    Digests above for why that halves the reading this gate does over an
    unbounded capture set. A transition image is hashed here, once,
    through the same memo the provenance check below uses.
    """
    problems = []
    checked = 0
    seen = set()
    for name in names:
        path = os.path.normpath(os.path.join(base, name))
        if path in seen:
            continue
        seen.add(path)
        if not os.path.exists(path):
            note_problem(problems,
                         "%s is named by the list and is not there"
                         % name)
            continue
        if digests.already_verified(path):
            checked += 1
            continue
        recorded = transitions.get(path)
        if recorded is None:
            recorded = digests.recorded_for(path)
        if recorded is None:
            note_problem(problems, "%s is named by the list and by no "
                                   "digest sidecar" % name)
            continue
        actual = digests.of(path)
        checked += 1
        if actual != recorded[0]:
            note_problem(problems, "%s hashes to %s, recorded as %s"
                         % (name, actual[:16], str(recorded[0])[:16]))
        elif recorded[1] is not None and \
                os.path.getsize(path) != int(recorded[1]):
            note_problem(problems, "%s is %d bytes, recorded as %s"
                         % (name, os.path.getsize(path), recorded[1]))
    if problems:
        bad("every image the concat list names is present and still "
            "hashes to its recorded digest", summarise(problems),
            "%d images, each present and unchanged since it was "
            "recorded" % len(seen))
        return
    ok("every image the concat list names is present and still hashes "
       "to its recorded digest",
       "%d distinct images held to a recorded digest -- %d reused from "
       "the sweep in group 3 (captures against "
       "build/frame_digests.jsonl), %d hashed here (transition frames "
       "against build/transitions.json)"
       % (checked, digests.reused, digests.hashed))


def check_transition_provenance(document, directory, transitions,
                                flagged, per_group, digests):
    """The materialised transitions, against their own manifest.
    The digest of each image comes from the shared memo, so an
    image the concat-list sweep above already hashed is not hashed
    a second time here: the two checks ask different questions of
    the same bytes.


    AN EMPTY GROUP LIST IS A VALID READING, NOT A MISSING FILE, and
    conflating the two failed an honest session.  A session in which no
    single keystroke moved the clock past the ceiling flags no
    transition, so make_transitions publishes a manifest whose `groups`
    is `[]` and composes nothing -- and this check used to read that
    empty list as "no transition manifest could be read", so the one
    outcome the ceiling is allowed to have would have failed the gate.

    The two states are now distinguished by the KEY rather than by its
    truthiness: a document that is not a mapping, or carries no `groups`
    key at all, is a manifest that could not be read; a document whose
    `groups` is an empty list is a reading, and it is held to the matching
    claim -- zero flags and zero images on disk.
    """
    if not isinstance(document, dict) or "groups" not in document or \
            not isinstance(document["groups"], list):
        bad("every materialised transition image is the one "
            "make_transitions composed",
            "no transition manifest could be read beside %s" % directory,
            "build/transitions.json, which records the sha256 and byte "
            "count of every image the transition stage composed")
        return
    if not document["groups"]:
        # The empty reading, held to its own claim.  Anything on disk
        # here is an image nothing composed at this timeline, and any
        # flag is a transition the film owes the viewer, so both are
        # failures -- but an empty manifest for an empty flag set with
        # an empty directory is exactly right and says so.
        stray = sorted(
            name for name in (os.listdir(directory)
                              if os.path.isdir(directory) else [])
            if not name.startswith("."))
        if flagged or stray or transitions:
            bad("every materialised transition image is the one "
                "make_transitions composed",
                "the manifest declares no group at all, against %d "
                "flagged frame(s) %s and %d file(s) in %s"
                % (len(flagged), sorted(flagged) or "none", len(stray),
                   directory),
                "a group for every flagged frame, or -- when nothing "
                "was flagged -- no group, no recorded image and an "
                "empty transition directory")
            return
        ok("every materialised transition image is the one "
           "make_transitions composed",
           "no frame's clock delta passed the ceiling, so the manifest "
           "declares no group, records no image, and %s holds none"
           % directory)
        return
    problems = []
    for path, recorded in sorted(transitions.items()):
        if not os.path.exists(path):
            note_problem(problems, "%s is recorded and absent"
                         % os.path.basename(path))
            continue
        if digests.of(path) != recorded[0]:
            note_problem(problems, "%s is not the image that was "
                                   "composed" % os.path.basename(path))
        elif recorded[1] is not None and \
                os.path.getsize(path) != int(recorded[1]):
            note_problem(problems, "%s is %d bytes, recorded as %s"
                         % (os.path.basename(path),
                            os.path.getsize(path), recorded[1]))
    declared = [group.get("frame") for group in document["groups"]]
    if sorted(n for n in declared if n is not None) != sorted(flagged):
        note_problem(problems, "the manifest declares groups for %s "
                               "against flags for %s"
                     % (summarise(sorted(n for n in declared
                                         if n is not None)) or "none",
                        summarise(sorted(flagged)) or "none"))
    if len(transitions) != len(flagged) * per_group:
        note_problem(problems, "%d recorded images against %d flags x %d"
                     % (len(transitions), len(flagged), per_group))
    if problems:
        bad("every materialised transition image is the one "
            "make_transitions composed", summarise(problems),
            "%d images (%d group(s) x %d), each hashing to what the "
            "transition stage recorded"
            % (len(flagged) * per_group, len(flagged), per_group))
        return
    ok("every materialised transition image is the one make_transitions "
       "composed",
       "%d image(s) in %d group(s) re-hashed and unchanged, composed "
       "from %s" % (len(transitions), len(flagged),
                    document.get("font", {}).get("path", "the game's "
                                                 "own font")))


def check_declared_file(label, path, block, what):
    """One artifact against the digest its producer declared for it."""
    if not isinstance(block, dict) or not block.get("sha256"):
        bad(label, "%s declares no sha256 for %s" % (what, path),
            "a declared digest -- the render stage writes one precisely "
            "so the bytes can be held to it later")
        return False
    if not os.path.exists(path):
        bad(label, "%s is not there" % path, "the file %s describes"
            % what)
        return False
    actual = digest(path)
    size = os.path.getsize(path)
    declared_size = block.get("bytes")
    if actual != block["sha256"]:
        bad(label,
            "%s hashes to %s (%d bytes), %s declares %s (%s bytes)"
            % (path, actual[:16], size, what,
               str(block["sha256"])[:16], declared_size),
            "the digest %s recorded when it produced the file -- a "
            "truncated, re-encoded or replaced file cannot survive "
            "this, and container metadata alone cannot see it because "
            "-movflags +faststart puts the moov atom at the front where "
            "gross data loss leaves it intact" % what)
        return False
    if declared_size is not None and size != int(declared_size):
        bad(label, "%s is %d bytes, %s declares %s"
            % (path, size, what, declared_size),
            "the byte count %s recorded" % what)
        return False
    ok(label, "%s: %d bytes hashing to %s, exactly as %s declares"
       % (path, size, actual[:16], what))
    return True


def check_manifest_describes(manifest, manifest_path, timeline_path,
                             entry_count, flagged, width, height, total,
                             eps):
    """The render manifest, against the timeline it claims to describe."""
    problems = []
    block = manifest.get("timeline")
    if not isinstance(block, dict) or not block.get("sha256"):
        note_problem(problems, "it declares no timeline digest")
    elif digest(timeline_path) != block["sha256"]:
        note_problem(problems,
                     "it was written for a timeline hashing to %s, and "
                     "%s hashes to %s"
                     % (str(block["sha256"])[:16], timeline_path,
                        digest(timeline_path)[:16]))
    for key, measured in (("capture_count", entry_count),
                          ("group_count", len(flagged)),
                          ("width", width), ("height", height)):
        value = manifest.get(key)
        if value is None:
            note_problem(problems, "it declares no %s" % key)
        elif int(value) != int(measured):
            note_problem(problems, "it declares %s=%s against %s "
                                   "measured" % (key, value, measured))
    declared_total = manifest.get("expected_total")
    if declared_total is None:
        note_problem(problems, "it declares no expected_total")
    elif total is not None and \
            abs(float(declared_total) - float(total)) > eps:
        note_problem(problems, "it declares expected_total=%s against "
                               "the timeline's %s"
                     % (declared_total, total))
    if problems:
        bad("the render manifest describes this timeline and this "
            "capture set", summarise(problems),
            "%s naming the committed timeline's digest, %d captures, %d "
            "transition group(s) and %dx%d"
            % (manifest_path, entry_count, len(flagged), width, height))
        return
    ok("the render manifest describes this timeline and this capture "
       "set",
       "%s: timeline %s, %d captures, %d group(s), %.3f s, %dx%d"
       % (manifest_path, digest(timeline_path)[:12], entry_count,
          len(flagged), float(declared_total), width, height))


def main(argv):
    (tooling_dir, timeline_path, concat_path, movie_path,
     transitions_dir, digests_path, inventory_path,
     epsilon) = argv[1:9]
    eps = float(epsilon)
    sys.path.insert(0, tooling_dir)
    import make_transitions as mt
    import render_movie as rm
    import timeline as tl

    # THE DOCUMENT'S HEADER, WITHOUT ITS ENTRIES.  Everything this checker
    # needs from the document itself -- the declared total, the provenance
    # blocks, the transition length -- is in the header; the entries are
    # walked twice below, each time as an event stream from the producer's
    # own reader.  Reading the whole document three times over, once per
    # question, was hundreds of megabytes of dicts at the session lengths
    # this pipeline is built for.
    document = tl.read_timeline_header(timeline_path)
    total = document.get("total") if isinstance(document, dict) else None
    per_group = int(mt.FRAMES_PER_GROUP)
    # The transition length is READ FROM THE DOCUMENT through the
    # transition stage's own accessor, which additionally holds it to
    # EXPECTED_TRANSITION; a length this pipeline cannot materialise is
    # therefore refused rather than measured against.
    try:
        seconds = float(mt.transition_seconds(document))
    except Exception:                                 # noqa: BLE001
        seconds = float(mt.EXPECTED_TRANSITION)

    # THE PLANNER STILL SEES THE WHOLE DOCUMENT, and it has to: it plans
    # every entry, and the plan is what the committed list is held to.
    # That copy is render_movie's own, taken and released here.
    check_planned(rm, tl.read_timeline(timeline_path), timeline_path,
                  concat_path)

    walk = walk_list(concat_path, rm,
                     tl.iter_timeline_frames(timeline_path), seconds,
                     per_group, eps)
    check_structure(walk)
    if walk["strays"]:
        bad("the concat list repeats its final entry, so the last "
            "duration takes effect",
            "the list carries lines that are neither an image nor a "
            "duration: %s" % summarise(walk["strays"]),
            "only `file` and `duration` lines, as render_movie writes "
            "them")
    else:
        check_repeat(walk)
    check_sum(walk, total, eps)

    entry_count = 0
    flagged = []
    for entry in tl.iter_timeline_frames(timeline_path):
        entry_count += 1
        if entry.get("transition_after"):
            flagged.append(entry.get("frame"))

    base = os.path.dirname(os.path.normpath(concat_path)) or os.curdir
    digests = Digests(inventory_path, digests_path)
    transitions_manifest_path = mt.generation_manifest_path(
        transitions_dir)
    try:
        transitions_manifest = read_json(transitions_manifest_path)
    except (OSError, ValueError):
        transitions_manifest = {}
    transitions = load_transition_digests(transitions_manifest,
                                          transitions_dir)
    check_named_images(iter_list_names(concat_path, rm), base, digests,
                       transitions)
    check_transition_provenance(transitions_manifest, transitions_dir,
                                transitions, flagged, per_group,
                                digests)

    manifest_path = rm.generation_manifest_path(None)
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as err:
        for label in ("the concat list is the one the render stage "
                      "declared",
                      "the film is the one the render stage declared",
                      "the render manifest describes this timeline and "
                      "this capture set"):
            bad(label, "%s could not be read: %s"
                % (relative(manifest_path), err),
                "build/movie.json, which the render stage writes to bind "
                "the film to the list and the timeline it came from")
        return 0
    manifest_rel = relative(manifest_path)
    check_declared_file("the concat list is the one the render stage "
                        "declared", concat_path,
                        manifest.get("concat_list"), manifest_rel)
    check_declared_file("the film is the one the render stage declared",
                        movie_path, manifest.get("movie"), manifest_rel)
    check_manifest_describes(manifest, manifest_rel, timeline_path,
                             entry_count, flagged,
                             int(manifest.get("width") or 0),
                             int(manifest.get("height") or 0), total,
                             eps)
    return 0


def iter_list_names(concat_path, rm):
    """Every image name the committed list carries, in list order.

    A second walk of the list rather than a retained copy of it: the list
    is a text file and re-reading it is bounded by the disk, while holding
    its entries is bounded by the session.
    """
    for kind, value, _ in iter_list_lines(
            concat_path, rm.CONCAT_FILE_PREFIX, rm.CONCAT_FILE_SUFFIX,
            rm.CONCAT_DURATION_PREFIX):
        if kind == "file":
            yield value


def relative(path):
    """The repository-relative spelling of an absolute path."""
    root = os.getcwd() + os.sep
    if path.startswith(root):
        return path[len(root):]
    return path


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_container() {
    group 4 "the container and the inputs it was built from"
    check_container_streams "${PLAYTHROUGH_MOVIE}" \
        "$(rel "${PLAYTHROUGH_MOVIE}")"
    check_container_duration
    check_frame_count
    check_no_audio
    check_declared_frames_agree
    check_film_decodes
    run_checker render \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "$(rel "${PLAYTHROUGH_TIMELINE}")" \
        "$(rel "${PLAYTHROUGH_CONCAT_LIST}")" \
        "$(rel "${PLAYTHROUGH_MOVIE}")" \
        "$(rel "${PLAYTHROUGH_TRANSITIONS_DIR}")" \
        "$(rel "${PLAYTHROUGH_FRAME_DIGESTS}")" \
        "$(digest_inventory)" \
        "${ARITHMETIC_EPSILON}"
    record_info "the films on disk" \
        "$(rel "${PLAYTHROUGH_MOVIE}") \
$("${WC}" -c <"${PLAYTHROUGH_MOVIE}" 2>/dev/null || echo '?') bytes, \
$(rel "${PLAYTHROUGH_MOVIE_CC}") \
$("${WC}" -c <"${PLAYTHROUGH_MOVIE_CC}" 2>/dev/null || echo '?') bytes"
}


# ---------------------------------------------------------------------
# 5  THE CAPTION TRACK AND THE TRANSCRIPTS
#
# The captions must be a SELECTABLE track and not pixels.  mov_text is
# the only subtitle codec broadly supported inside MP4, and the proof
# that it was muxed rather than drawn is pixel-level: the same instant
# extracted from the captioned film and from the plain one must differ in
# ZERO pixels.  If the text had been burned in, that comparison would
# count every glyph.
# ---------------------------------------------------------------------
check_subtitle_stream() {
    local readout="" codec="" language="" streams="" said=""
    readout="$(probe_field "${PLAYTHROUGH_MOVIE_CC}" s \
        'stream=index,codec_name:stream_tags=language')"
    said="$(because ffprobe)"
    streams="$(printf '%s\n' "${readout}" |
        "${GREP}" -c '^index=' || true)"
    codec="$(printf '%s\n' "${readout}" |
        "${SED}" -n 's/^codec_name=//p' | "${HEAD}" -n 1 || true)"
    language="$(printf '%s\n' "${readout}" |
        "${SED}" -n 's/^TAG:language=//p' | "${HEAD}" -n 1 || true)"

    if [ "${streams}" = "1" ]; then
        record_pass "the captioned film carries exactly one subtitle \
stream" "${streams} subtitle stream"
    else
        record_fail "the captioned film carries exactly one subtitle \
stream" "${streams:-0} subtitle stream(s)${said}" \
            "exactly 1 -- one English track for one session"
    fi

    if [ "${codec}" = "${SUBTITLE_CODEC_EXPECTED}" ]; then
        record_pass "the captions are a soft, player-selectable track" \
            "codec_name=${codec}"
    else
        record_fail "the captions are a soft, player-selectable track" \
            "codec_name=${codec:-<no subtitle stream>}${said}" \
            "${SUBTITLE_CODEC_EXPECTED} -- the only subtitle codec \
broadly supported inside MP4"
    fi

    if [ "${language}" = "${SUBTITLE_LANGUAGE_EXPECTED}" ]; then
        record_pass "the caption track declares its language" \
            "TAG:language=${language}"
    else
        record_fail "the caption track declares its language" \
            "TAG:language=${language:-<unset>}" \
            "${SUBTITLE_LANGUAGE_EXPECTED} (an ISO-639 three-letter \
code), so a player can offer it by name"
    fi
}

# THE MUX MUST NOT HAVE RE-ENCODED THE PICTURE.  `-c copy` copies the
# video packets; if the captioned film's video stream differs in codec or
# geometry, something re-encoded it and the picture is no longer the one
# that was verified.
check_captioned_video_survived() {
    check_container_streams "${PLAYTHROUGH_MOVIE_CC}" \
        "$(rel "${PLAYTHROUGH_MOVIE_CC}")"
}

# THE BURNED-IN TEST.  Extract the same timestamp from both films and
# require zero differing pixels.  `compare` exits non-zero when the
# images differ, so its status is captured deliberately rather than
# allowed to abort the run, and the metric it prints on stderr is the
# evidence either way.
check_captions_not_burned_in() {
    local plain="" captioned="" metric="" status=0 offset=""
    local compared=0
    local -a offsets=()
    local -a problems=()
    while read -r offset; do
        [ -n "${offset}" ] || continue
        offsets+=("${offset}")
    done <"$(offsets_file)"
    for offset in "${offsets[@]}"; do
        # ONE EXTRACTION PER (FILM, OFFSET), shared with the luminance
        # gate: both checks read the same instant out of both films, and
        # extracting it twice was two seeks and two decodes for one
        # picture.  See ONE DECODE PER FILM above.
        if ! plain="$(extracted_frame "${PLAYTHROUGH_MOVIE}" \
                "${offset}")"; then
            problems+=("no frame could be decoded out of \
$(rel "${PLAYTHROUGH_MOVIE}") at ${offset}s$(because ffmpeg)")
            continue
        fi
        if ! captioned="$(extracted_frame "${PLAYTHROUGH_MOVIE_CC}" \
                "${offset}")"; then
            problems+=("no frame could be decoded out of \
$(rel "${PLAYTHROUGH_MOVIE_CC}") at ${offset}s$(because ffmpeg)")
            continue
        fi
        # `compare` exits non-zero when the images differ, which is a
        # RESULT and not an error, so it runs as the condition of an `if`:
        # inside one, a non-zero status is a value the shell was asked
        # for, and neither errexit nor the ERR trap fires.  Capturing the
        # status with `$?` after a bare call used to print a spurious
        # FATAL line naming this file, twice, whenever the tool was
        # absent.
        status=0
        if metric="$(bounded "${BOUND_PROBE_SECONDS}" \
                "${COMPARE}" -metric AE "${captioned}" "${plain}" \
                null: 2>&1)"; then
            status=0
        else
            status=$?
        fi
        metric="${metric%% *}"
        # The metric is VALIDATED before it is quoted.  When `compare`
        # cannot be executed at all, what comes back on this channel is
        # the shell's own diagnostic, and printing that as a pixel count
        # produced the unreadable "compare reported
        # playthrough/tooling/verify_artifacts.sh: differing pixel(s)".
        if ! is_count "${metric}"; then
            problems+=("compare could not be executed at ${offset}s \
(exit ${status}); it printed no pixel count")
            continue
        fi
        compared=$((compared + 1))
        if [ "${status}" -ne 0 ] || [ "${metric}" != "0" ]; then
            problems+=("${metric} differing pixel(s) at ${offset}s")
        fi
    done
    if [ "${#problems[@]}" -eq 0 ] && [ "${compared}" -gt 0 ]; then
        record_pass "the captions are not burned into the picture" \
            "0 differing pixels at each of ${offsets[*]}s between \
$(rel "${PLAYTHROUGH_MOVIE_CC}") and $(rel "${PLAYTHROUGH_MOVIE}")"
        return 0
    fi
    record_fail "the captions are not burned into the picture" \
        "${problems[*]:-nothing could be compared}" \
        "0 differing pixels at every offset -- identical pixels, \
because the text is a muxed track and not paint on the frame"
}

emit_caption_checker() {
    emit_checker caption <<'PY'
"""Assert the cue file, the readable transcript and their agreement."""

import json
import os
import re
import sys

SEP = "\x1f"
ARROW = " --> "
TIMECODE_RE = re.compile(
    r"^([0-9]{2}):([0-9]{2}):([0-9]{2}),([0-9]{3})"
    r" --> ([0-9]{2}):([0-9]{2}):([0-9]{2}),([0-9]{3})$")
STAMP_RE = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}[,.][0-9]{3}")
ENTRY_RE = re.compile(
    r"(?m)^\*\*([0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3})\*\*")
# The same entry, captured WITH its sentence.  Anchored at both ends and
# non-greedy about nothing: a Markdown entry is one line, because
# manifest.py refuses a line break inside a commentary, so an entry that
# spans two lines is itself a finding rather than something to stitch
# back together.
ENTRY_BODY_RE = re.compile(
    r"(?m)^\*\*([0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3})\*\* (.+)$")

# The literal vocabulary the requirement names, applied as an ADVISORY.
# It is deliberately NOT the failing gate: measured against the committed
# record it matches "a man of many options" and "past the frame" -- a
# door frame, which is the survivor's own word for it -- so using it to
# fail would manufacture findings out of ordinary English.  The failing
# gate is manifest.py's curated vocabulary, which distinguishes those
# cases by pattern; this list is still run, and every hit is reported, so
# nothing is hidden by that choice.
ADVISORY_PATTERN = re.compile(
    r"frame|screenshot|capture|ocr|tesseract|imagemagick|ffmpeg"
    r"|moviepy|manifest|timeline|duration|keystroke|xdotool|pipeline"
    r"|tileset|sidebar|option|commit|git |debug|requirement"
    r"|R1[0-3]|R[1-9]\b", re.IGNORECASE)


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def summarise(items, limit=6):
    shown = ", ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += ", ... (%d more)" % (len(items) - limit)
    return shown


# HOW MANY FINDINGS ONE VERDICT COLLECTS.
#
# A broken artifact set can be broken at every index -- a whole capture
# set re-encoded, a sidecar regenerated against the wrong tree -- and a
# collector with no ceiling then holds one string per frame to explain a
# failure whose FIRST example already explains it.  The verdict shows six
# and says how many more; this is the bound on how many are kept at all.
PROBLEM_LIMIT = 200


def note_problem(problems, text, limit=PROBLEM_LIMIT):
    """Collect a finding, bounded.

    Past the limit a single line records that collection stopped, so the
    verdict never claims to be exhaustive when it is not.  A verdict is
    reached on the FACT of a failure, which the first finding establishes;
    what the rest would add is length.
    """
    if len(problems) < limit:
        problems.append(text)
        return
    if len(problems) == limit:
        problems.append("... further findings were not collected; the "
                        "%d above are the ones this verdict carries"
                        % limit)


def near(a, b, eps):
    return abs(float(a) - float(b)) <= eps


def seconds(hours, minutes, secs, millis):
    return (int(hours) * 3600 + int(minutes) * 60 +
            int(secs) + int(millis) / 1000.0)


def iter_cue_blocks(handle):
    """The cue file's blocks, one at a time, from an open text handle.

    A SubRip block is lines up to a blank line, so the file is walked and
    each block is yielded as it closes.  The whole file used to be read
    into one string and split on blank lines into a list of every block:
    one cue per keystroke, so at the session lengths this pipeline is
    built for that is the transcript twice over in memory before a single
    cue has been judged.
    """
    lines = []
    for raw in handle:
        line = raw.rstrip("\n")
        if line.strip():
            lines.append(line)
            continue
        if lines:
            yield lines
            lines = []
    if lines:
        yield lines


def parse_cue(lines, position, problems):
    """One block as (number, start, end, text lines), or None."""
    if len(lines) < 3:
        note_problem(problems,
                     "block %d has %d line(s), not a sequence number, a "
                     "timecode and text" % (position, len(lines)))
        return None
    number, timecode = lines[0].strip(), lines[1]
    match = TIMECODE_RE.match(timecode)
    if not match:
        note_problem(problems, "block %d timecode %r"
                     % (position, timecode))
        return None
    if not number.isdigit():
        note_problem(problems, "block %d sequence %r"
                     % (position, number))
        return None
    return (int(number), seconds(*match.groups()[0:4]),
            seconds(*match.groups()[4:8]), lines[2:])


def check_cue_file(path, frames, eps, index_path):
    """The cue file, walked once beside the timeline it came from.

    Five properties are decided in that one walk -- the blocks are well
    formed, the sequence numbers are contiguous, every cue carries text,
    the windows advance without overlapping, and each window is the
    timeline's own -- and the cue starts are written to a scratch index as
    they are read, so the readable record can be held to them later
    without either file being resident.

    Returns (cue count, last cue end).
    """
    with open(path, "rb") as handle:
        head = handle.read(3)
    if head.startswith(b"\xef\xbb\xbf"):
        bad("the cue file carries no byte-order mark",
            "the file begins with a UTF-8 BOM",
            "no BOM -- a leading BOM makes the first sequence number "
            "unparsable to strict players")
    else:
        ok("the cue file carries no byte-order mark", "%d bytes"
           % os.path.getsize(path))

    malformed = []
    numbering = []
    empty = []
    ordering = []
    drift = []
    cues = 0
    arrows = 0
    frame_count = 0
    previous_end = None
    last_end = None
    exhausted = False
    with open(path, "r", encoding="utf-8") as handle, \
            open(index_path, "w", encoding="utf-8") as index:
        for position, block in enumerate(iter_cue_blocks(handle), 1):
            arrows += sum(1 for line in block if ARROW in line)
            cue = parse_cue(block, position, malformed)
            if cue is None:
                continue
            number, start, end, text = cue
            cues += 1
            if number != cues:
                note_problem(numbering, str(number))
            if not any(line.strip() for line in text):
                note_problem(empty, str(number))
            if not end > start:
                note_problem(ordering,
                             "cue %d ends at %.3f, at or before its "
                             "start %.3f" % (number, end, start))
            if previous_end is not None and start < previous_end - eps:
                note_problem(ordering,
                             "cue %d starts at %.3f, before cue %d "
                             "ended at %.3f"
                             % (number, start, number - 1, previous_end))
            previous_end = end
            last_end = end
            entry = None
            if frames is not None and not exhausted:
                try:
                    entry = next(frames)
                except StopIteration:
                    exhausted = True
                    entry = None
            if entry is not None:
                frame_count += 1
                if not near(start, entry["cue_start"], eps) or \
                        not near(end, entry["cue_end"], eps):
                    note_problem(drift,
                                 "cue %d is %.3f..%.3f, the timeline "
                                 "says %.3f..%.3f"
                                 % (number, start, end,
                                    entry["cue_start"],
                                    entry["cue_end"]))
            # ONE INDEX RECORD PER CUE, WRITTEN AS IT IS READ.  The
            # readable record is held to three properties of this cue
            # later -- its start, its text, and the sentence the timeline
            # says the entry carries -- and all three are known here, in
            # the one walk that has the cue and its timeline entry in
            # hand at the same moment.  Writing them down is what lets
            # check_markdown make the comparison without either file, or
            # the timeline, being resident: it reads one line back per
            # entry.  It used to be the start alone, and the sentence
            # comparison was consequently written against a whole-file
            # read that no longer exists.
            index.write(json.dumps(
                {"start": start,
                 "text": [line for line in text if line.strip()],
                 "commentary": (entry.get("commentary")
                                if entry is not None else None)},
                ensure_ascii=False) + "\n")
    if frames is not None:
        for _ in frames:
            frame_count += 1

    if malformed:
        bad("every cue is a well formed SubRip block",
            summarise(malformed),
            "a sequence number, an HH:MM:SS,mmm --> HH:MM:SS,mmm "
            "timecode with COMMA decimal separators, and text")
    else:
        ok("every cue is a well formed SubRip block",
           "%d cues, %d arrows" % (cues, arrows))

    if numbering:
        bad("cue sequence numbers are contiguous from 1",
            "first divergence near %s" % summarise(numbering),
            "1 .. %d" % cues)
    else:
        ok("cue sequence numbers are contiguous from 1",
           "1 .. %d" % cues if cues else "no cues")

    if empty:
        bad("every cue carries text", summarise(empty),
            "non-empty text in all %d cues" % cues)
    else:
        ok("every cue carries text", "%d cues" % cues)

    if ordering:
        bad("cue windows advance and never overlap", summarise(ordering),
            "end > start for every cue, and each start at or after the "
            "previous end")
    else:
        ok("cue windows advance and never overlap", "%d cues" % cues)

    if frames is not None:
        if cues == frame_count:
            ok("the cue count equals the capture count -- one caption "
               "per keystroke",
               "%d cues == %d captures" % (cues, frame_count))
        else:
            bad("the cue count equals the capture count -- one caption "
                "per keystroke",
                "%d cues against %d captures" % (cues, frame_count),
                "equal counts")
        if drift:
            bad("every cue window is the timeline's own window",
                summarise(drift),
                "identical to the single computed timeline both the "
                "film and the captions were built from")
        else:
            ok("every cue window is the timeline's own window",
               "%d windows agree to within %s s" % (cues, eps))
    return cues, last_end


def check_final_cue(cues, last_end, total, eps):
    if not cues or last_end is None:
        bad("the last cue ends exactly where the timeline ends",
            "there are no cues", "a final cue ending at %s s" % total)
        return
    if near(last_end, total, eps):
        ok("the last cue ends exactly where the timeline ends",
           "%.3f s" % last_end)
    else:
        bad("the last cue ends exactly where the timeline ends",
            "the last cue ends at %.3f s, the timeline total is %s s"
            % (last_end, total),
            "equal -- captions that outrun or fall short of the film "
            "are drifting, and the drift grows through the session")


def check_markdown(path, index_path, cues, frame_count, tooling_dir,
                   eps):
    """The readable record: one stamped entry per capture, in voice.

    WALKED ONCE, LINE BY LINE, beside the cue-start index the SRT walk
    wrote.  The file used to be read whole and then split into lines
    FOUR separate times -- once for the curated vocabulary, once for the
    advisory list, and twice more for the two stamp counts -- so a
    transcript of an unbounded session was resident five times over.
    Every property below is decided as its line arrives, and the stamp
    comparison reads one line of the index per entry.
    """
    with open(path, "rb") as raw_handle:
        head = raw_handle.read(3)
    if head.startswith(b"\xef\xbb\xbf"):
        bad("the readable record carries no byte-order mark",
            "the file begins with a UTF-8 BOM", "no BOM")

    # THE SENTENCES THEMSELVES, and not only the times in front of them.
    #
    # Everything else here measures the readable record's TIMESTAMPS: one
    # per entry, in the cue starts, none anywhere else.  None of that
    # reads a single word of what the survivor said, so the two
    # transcripts could have agreed perfectly about when each entry began
    # and disagreed completely about what it was -- a Markdown file
    # regenerated from a different record, or a caption track re-wrapped
    # from an older one, and the drift would be invisible to a check that
    # counts stamps.
    #
    # The transformation is documented and it is exactly one step: the
    # Markdown carries the sentence WHOLE, and the cue carries the same
    # sentence with its whitespace collapsed and wrapped at
    # make_srt.CUE_LINE_WIDTH.  So the comparison is made in both
    # directions against the one computed timeline -- the Markdown body
    # against the timeline's commentary verbatim, the cue text against
    # that body re-wrapped by the producer's OWN function, imported
    # rather than reimplemented here so the two cannot drift apart.
    #
    # IT IS DECIDED PER ENTRY, as the entry arrives, against the one
    # index record the cue walk wrote for it.  The comparison was first
    # written against a whole-file read of both transcripts and a
    # resident timeline; on an unbounded session that is three complete
    # populations in memory to answer a question about one sentence at a
    # time.
    sentence_problems = []
    wrapper = None
    width = None
    sys.path.insert(0, tooling_dir)
    try:
        import make_srt as ms
        wrapper = ms.wrap_cue_text
        width = ms.CUE_LINE_WIDTH
    except Exception as err:                          # noqa: BLE001
        note_problem(
            sentence_problems,
            "make_srt.py could not be imported (%s), so the cue text "
            "could not be compared through the producer's own wrapper"
            % err)

    # THE IN-CHARACTER GATE.  Engineering and "gamey" language belongs in
    # playthrough/TECHNICAL_NOTES.md; the record the survivor keeps is
    # their own voice.  The failing gate is manifest.py's curated
    # vocabulary, which is written to tell a door frame from a numbered
    # one; the literal advisory list is reported beside it.
    sys.path.insert(0, tooling_dir)
    try:
        import manifest as mf
    except Exception as err:                          # noqa: BLE001
        bad("the readable record is free of meta and engineering "
            "language", "manifest.py could not be imported: %s" % err,
            "the curated vocabulary applied to every entry")
        return

    entries = 0
    all_stamps = 0
    lines_read = 0
    hits = []
    advisory = []
    drift = []
    index = None
    if cues:
        index = open(index_path, "r", encoding="utf-8")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for number, raw in enumerate(handle, 1):
                line = raw.rstrip("\n")
                lines_read = number
                all_stamps += len(STAMP_RE.findall(line))
                found = mf.find_meta_vocabulary(line)
                if found:
                    note_problem(hits, "line %d: %s"
                                 % (number, ", ".join(found)))
                for match in ADVISORY_PATTERN.finditer(line):
                    note_problem(advisory, "line %d %r"
                                 % (number, match.group(0)))
                match = ENTRY_RE.match(line)
                if match is None:
                    continue
                entries += 1
                body = None
                with_body = ENTRY_BODY_RE.match(line)
                if with_body is None:
                    note_problem(
                        sentence_problems,
                        "entry %d is a stamp with no sentence after it"
                        % entries)
                else:
                    body = with_body.group(2)
                if index is None:
                    continue
                record = index.readline()
                if not record.strip():
                    note_problem(drift,
                                 "entry %d is stamped %s and the cue "
                                 "file has no cue there"
                                 % (entries, match.group(1)))
                    continue
                try:
                    cue_record = json.loads(record)
                except ValueError as err:
                    note_problem(sentence_problems,
                                 "the cue index record for entry %d "
                                 "could not be read: %s" % (entries, err))
                    continue
                start = cue_record.get("start")
                stamp = match.group(1)
                parts = re.split(r"[:,]", stamp)
                value = seconds(parts[0], parts[1], parts[2], parts[3])
                if start is None or not near(value, float(start), eps):
                    note_problem(drift,
                                 "entry %d is stamped %s, cue %d begins "
                                 "at %s"
                                 % (entries, stamp, entries, start))
                if body is None:
                    continue
                declared = cue_record.get("commentary")
                if isinstance(declared, str) and body != declared:
                    note_problem(sentence_problems,
                                 "entry %d reads %r, the timeline "
                                 "records %r" % (entries, body, declared))
                    continue
                if wrapper is None:
                    continue
                recorded = cue_record.get("text") or []
                try:
                    expected = wrapper(body, width)
                except Exception as err:               # noqa: BLE001
                    note_problem(sentence_problems,
                                 "entry %d could not be wrapped: %s"
                                 % (entries, err))
                    continue
                if recorded != expected:
                    note_problem(sentence_problems,
                                 "cue %d carries %r, the entry wraps to "
                                 "%r" % (entries, recorded, expected))
    finally:
        if index is not None:
            index.close()

    if frame_count is not None:
        if entries == frame_count:
            ok("the readable record has one stamped entry per capture",
               "%d entries == %d captures" % (entries, frame_count))
        else:
            bad("the readable record has one stamped entry per capture",
                "%d entries against %d captures"
                % (entries, frame_count),
                "equal counts")
    if all_stamps == entries:
        ok("every timestamp in the readable record opens an entry",
           "%d stamps, %d entries" % (all_stamps, entries))
    else:
        bad("every timestamp in the readable record opens an entry",
            "%d timestamps but %d entries" % (all_stamps, entries),
            "one stamp per entry and none anywhere else, so the file "
            "cannot be read as claiming a time it does not index")

    if cues:
        if sentence_problems:
            bad("the readable record's sentences are the caption track's",
                summarise(sentence_problems),
                "every Markdown entry the timeline's own commentary "
                "verbatim, and every cue that same sentence wrapped by "
                "make_srt.wrap_cue_text at %s columns -- both files are "
                "generated from the one timeline in a single pass, so a "
                "difference means one of them is from another record"
                % (width if width is not None else "the producer's"))
        else:
            ok("the readable record's sentences are the caption track's",
               "%d entr(ies) equal to the timeline's commentary word for "
               "word, and %d cue(s) equal to those sentences wrapped at "
               "%s columns" % (entries, cues, width))
        if drift:
            bad("the readable record's timestamps are the cue starts",
                summarise(drift),
                "identical -- both are generated from the one computed "
                "timeline in a single pass")
        else:
            ok("the readable record's timestamps are the cue starts",
               "%d stamps agree with %d cue starts" % (entries, cues))

    if hits:
        bad("the readable record is free of meta and engineering "
            "language", summarise(hits),
            "no hit from manifest.META_VOCABULARY -- move the "
            "observation to playthrough/TECHNICAL_NOTES.md and rewrite "
            "the sentence in the survivor's own words")
    else:
        ok("the readable record is free of meta and engineering "
           "language",
           "%d lines checked against %d curated concepts"
           % (lines_read, len(mf.META_VOCABULARY)))

    # Reported without a verdict attached, deliberately.  Saying these
    # hits ARE ordinary English would be a claim about text this run has
    # not read; the curated check above is the verdict, and this line
    # exists so that the literal list's hits are visible rather than
    # hidden by that choice.
    info("the literal meta word list, applied as an advisory (the "
         "curated check above is the verdict)",
         ("%d hit(s) to read in context: %s"
          % (len(advisory), summarise(advisory)))
         if advisory else "no hits")


def main(argv):
    (srt_path, markdown_path, timeline_path, tooling_dir, index_path,
     epsilon) = argv[1:7]
    eps = float(epsilon)

    # THE TIMELINE IS STREAMED, and only its header is parsed.  This
    # checker walks the entries in order beside the cue file; it never
    # looks backwards, so holding one entry per keystroke was a cost with
    # nothing bought for it.
    sys.path.insert(0, tooling_dir)
    frames = None
    total = None
    try:
        import timeline as tl
        document = tl.read_timeline_header(timeline_path)
        if isinstance(document, dict):
            total = document.get("total")
        frames = tl.iter_timeline_frames(timeline_path)
        if total is None:
            # A document with no declared total -- the bare-array form.
            # Its last entry's cue_end is the total, found in a pass that
            # keeps one entry rather than all of them.
            for entry in tl.iter_timeline_frames(timeline_path):
                total = entry.get("cue_end")
    except Exception as err:                          # noqa: BLE001
        info("the timeline was not available to compare against",
             str(err))
        frames = None

    cues = 0
    frame_count = None
    if os.path.exists(srt_path):
        if frames is not None:
            counter = CountingFrames(frames)
            cues, last_end = check_cue_file(srt_path, counter, eps,
                                            index_path)
            frame_count = counter.count
        else:
            cues, last_end = check_cue_file(srt_path, None, eps,
                                            index_path)
        if total is not None:
            check_final_cue(cues, last_end, total, eps)
    else:
        bad("the cue file exists", srt_path, "playthrough/transcript.srt")

    if os.path.exists(markdown_path):
        check_markdown(markdown_path, index_path, cues, frame_count,
                       tooling_dir, eps)
    else:
        bad("the readable record exists", markdown_path,
            "playthrough/transcript.md")
    return 0


class CountingFrames(object):
    """An iterator that remembers how many entries it has yielded.

    The cue walk needs the capture count as well as the entries, and the
    entries arrive as a stream: counting them where they are consumed is
    what keeps the count honest without a second pass or a resident list.
    """

    __slots__ = ("_frames", "count")

    def __init__(self, frames):
        self._frames = iter(frames)
        self.count = 0

    def __iter__(self):
        return self

    def __next__(self):
        entry = next(self._frames)
        self.count += 1
        return entry


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

group_captions() {
    group 5 "the caption track and the transcripts"
    check_subtitle_stream
    check_captioned_video_survived
    check_captions_not_burned_in
    run_checker caption \
        "${PLAYTHROUGH_TRANSCRIPT_SRT}" \
        "${PLAYTHROUGH_TRANSCRIPT_MD}" \
        "${PLAYTHROUGH_TIMELINE}" \
        "${PLAYTHROUGH_TOOLING_DIR}" \
        "${SCRATCH}/cue-starts" \
        "${ARITHMETIC_EPSILON}"
}


# ---------------------------------------------------------------------
# 6  THE LUMINANCE GATE
#
# The guard against SDL_VIDEODRIVER=dummy, and the reason a black film
# cannot pass unnoticed.  BOTH TERMS ARE LOAD-BEARING:
#
#   * mean > 0 catches a fully black frame, which is exactly what the
#     dummy driver produces -- the game runs, the captures succeed, the
#     encode succeeds, every count tallies, and nothing is visible.
#   * std > 0 additionally catches a uniform solid-colour frame, which a
#     mean-only test would happily pass.
#
# The threshold is strictly `> 0` and never a magnitude.  How bright a
# capture is depends on the tileset and on what the survivor was looking
# at; a gate that demanded a particular mean would fail honest captures
# of a dark cellar.  The calibration reading is reported as provenance so
# a reader knows where the number in the plan came from.
#
# The comparison goes through awk.  `[ "0.27" -gt 0 ]` is not a working
# test in any shell -- it is an integer operator applied to a string, and
# it fails at the syntax level rather than returning a wrong answer.
# ---------------------------------------------------------------------
sample_indices() {
    local count="$1"
    local how_many="$2"
    "${AWK}" -v n="${count}" -v s="${how_many}" 'BEGIN {
        if (n <= 0) { exit }
        if (s > n) { s = n }
        if (s < 1) { s = 1 }
        if (n == 1 || s == 1) { print 1; exit }
        for (i = 0; i < s; i++) {
            print 1 + int(i * (n - 1) / (s - 1) + 0.5)
        }
    }' | "${SORT}" -n -u
}

# sample_file HOW_MANY FILE -- an even spread of at most HOW_MANY lines
# of FILE, always including the first and the last.
#
# The companion to sample_indices, for the case where the population is a
# LIST rather than a range: group 9 measures colour depth on the in-game
# captures group 2 published, and those are not 1..N.
#
# TWO PASSES OVER THE FILE, HOLDING NOTHING.  The first counts the lines
# and the second prints the wanted ones by line number.  It used to read
# the population from stdin, which meant holding EVERY line in awk's own
# memory to be able to index it at the end -- one entry per in-game
# keystroke, for a reading that wants eight of them.  A second pass over
# a file costs a re-read; holding the population costs the session.
sample_file() {
    local how_many="$1"
    local file="$2"
    local total=""
    total="$(count_lines "${file}")"
    if [ "${total}" -eq 0 ]; then
        return 0
    fi
    "${AWK}" -v s="${how_many}" -v seen="${total}" '
        BEGIN {
            if (s > seen) { s = seen }
            if (s < 1) { s = 1 }
            if (seen == 1 || s == 1) { wanted[1] = 1 }
            else {
                for (i = 0; i < s; i++) {
                    wanted[1 + int(i * (seen - 1) / (s - 1) + 0.5)] = 1
                }
            }
        }
        NF {
            position++
            if (position in wanted) { print }
        }' "${file}"
}

# extract_offsets -- the seconds at which the films are sampled.
#
# The historical 1 s reading comes first so the report stays comparable
# with earlier runs, then each fraction of the timeline total.  An offset
# inside a transition window is moved to just past that window, every
# offset is held below the end of the film, and the result is sorted and
# de-duplicated.  All of it in awk, because it is floating-point
# arithmetic and the shell cannot do that.
#
# THE TRANSITION WINDOWS ARRIVE AS A FILE, NOT AS AN ARGUMENT.  Group 3
# publishes one window per line in the scratch generation, and this
# program reads that file.  They used to be joined into a single
# space-separated `awk -v` value, which is an argument on an exec line and
# therefore bounded by MAX_ARG_STRLEN -- 131,072 bytes on Linux, however
# much room the whole argv has.  At about 13 bytes a window that ceiling
# is roughly ten thousand transitions, and a session long enough to sleep
# through ten thousand nights is exactly the session this pipeline exists
# to allow.  Past it the gate would have died with E2BIG rather than
# reporting anything at all.
extract_offsets() {
    local total="" windows=""
    total="$(fact timeline_total)"
    windows="$(windows_file)"
    if ! is_real "${total}"; then
        printf '%s\n' "${EXTRACT_OFFSET}"
        return 0
    fi
    # SC2016 objects to the single quotes around the awk program, which
    # are deliberate: AWK expands $1 and the array subscripts below, and
    # the shell must not.  Every shell-side value the program needs is
    # handed over through the -v assignments on this same command, so
    # nothing is lost by the quoting -- double-quoting it would let the
    # shell eat the field references before awk ever saw them.
    # shellcheck disable=SC2016
    "${AWK}" -v total="${total}" -v first="${EXTRACT_OFFSET}" \
        -v fractions="${EXTRACT_FRACTIONS}" '
    # One window per line, "<start>-<stop>", read as data.
    NF {
        split($1, edge, "-")
        n++
        start[n] = edge[1] + 0
        stop[n] = edge[2] + 0
    }
    END {
        limit = total - 0.25
        if (limit < 0) { limit = 0 }
        count = split(fractions, f, " ")
        candidates[1] = first + 0
        for (i = 1; i <= count; i++) {
            candidates[i + 1] = total * f[i]
        }
        for (i = 1; i <= count + 1; i++) {
            value = candidates[i]
            moved = 1
            passes = 0
            while (moved && passes < 8) {
                moved = 0
                for (j = 1; j <= n; j++) {
                    if (value >= start[j] - 0.05 && value <= stop[j]) {
                        value = stop[j] + 0.15
                        moved = 1
                    }
                }
                passes++
            }
            if (value > limit) { value = limit }
            if (value < 0) { value = 0 }
            printf "%.3f\n", value
        }
    }' "${windows}" | "${SORT}" -n -u
}

# windows_file -- the path of the transition-window list group 3 wrote,
# or of an empty stand-in when group 3 has not run.  Named here so the
# awk program above always has a file to read: awk with no input file
# would wait on stdin.
windows_file() {
    local path="${SCRATCH}/transition-windows"
    if [ ! -f "${path}" ]; then
        : >"${path}"
    fi
    printf '%s' "${path}"
}

# in_game_file -- the path of the in-game capture list group 2 wrote, one
# index per line.  Group 9's colour-depth reading samples it; see WHICH
# CAPTURES SHOW THE GAME BEING PLAYED in the record checker for why it is
# a file rather than a fact.
in_game_file() {
    local path="${SCRATCH}/in-game-frames"
    if [ ! -f "${path}" ]; then
        : >"${path}"
    fi
    printf '%s' "${path}"
}

# offsets_file -- the sampled offsets, computed once and reused.  Both
# the burned-in comparison and the film-luminance reading walk them, and
# a second computation would mean a second reading of the window list for
# an answer that cannot have changed inside one run.
offsets_file() {
    local path="${SCRATCH}/extract-offsets"
    if [ ! -s "${path}" ]; then
        extract_offsets >"${path}"
    fi
    printf '%s' "${path}"
}

# ---------------------------------------------------------------------
# digest_inventory -- the one place a file's sha256 is recorded per run.
#
# Two checkers hold committed images to the digests their producers took:
# group 3 sweeps every capture against build/frame_digests.jsonl, and
# group 4 holds every image the concat list names, plus every materialised
# transition, against build/transitions.json.  Between them they used to
# hash every capture TWICE and every transition image TWICE -- four whole
# passes over the pixel evidence, at the disk's read rate, on a session
# whose length is deliberately unbounded.  Measured shape at 100k frames:
# tens of gigabytes read twice over for one answer.
#
# So a digest is taken ONCE and appended here as
#
#     <sha256> <TAB> <bytes> <TAB> <path>
#
# by whichever checker reaches the file first, and the others read it
# instead of hashing again.  The file lives in the scratch generation, so
# it cannot outlive the artifacts it describes and there is no staleness
# to reason about; the byte count travels with the digest so an entry can
# be held to the file it claims to be about.
digest_inventory() {
    local path="${SCRATCH}/digest-inventory"
    if [ ! -f "${path}" ]; then
        : >"${path}"
    fi
    printf '%s' "${path}"
}

check_one_frame_luminance() {
    local path="$1"
    local label="$2"
    local reading="" mean="" std="" geometry_reading=""
    LAST_LUMINANCE=""
    if [ ! -f "${path}" ]; then
        record_fail "${label} is a real, non-blank image" \
            "no such file: $(rel "${path}")" "a readable PNG"
        return 1
    fi
    reading="$(luminance "${path}")"
    mean="${reading%% *}"
    std="${reading##* }"
    if [ -z "${reading}" ] || ! is_real "${mean}" ||
            ! is_real "${std}"; then
        record_fail "${label} is a real, non-blank image" \
            "could not measure grayscale statistics (read \
'${reading}')$(because convert)" \
            "a mean and a standard deviation from convert"
        return 1
    fi
    LAST_LUMINANCE="${reading}"
    # THE GEOMETRY IS MEASURED HERE, on the frame already being read.
    # check_frame_geometry existed with no caller at all -- ShellCheck
    # reported it as unreachable and a review asked for it to be
    # integrated or removed -- and this is the check it belongs to: a
    # capture that is not the full X root is not the frame the crop
    # geometry, the clock region and every duration were computed for,
    # and it is exactly as invisible as a black one.
    if ! geometry_reading="$(check_frame_geometry "${path}")"; then
        record_fail "${label} is at the X root's own resolution" \
            "${geometry_reading}$(because identify)" \
            "${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT} \
-- capture.sh photographs the root with 'import -window root' and the \
film is encoded at that size, so a frame of any other size was produced \
some other way and the sidebar crop does not describe it"
        return 1
    fi
    if ! "${AWK}" -v m="${mean}" -v s="${std}" \
            'BEGIN { exit !(m > 0 && s > 0) }'; then
        reading="$(geometry "${path}")"
        record_fail "${label} is a real, non-blank image" \
            "mean=${mean} std=${std} at ${reading:-unknown geometry}" \
            "mean > 0 AND std > 0 -- mean=0 std=0 is the \
SDL_VIDEODRIVER=dummy signature, and std=0 alone is a uniform \
solid-colour frame"
        return 1
    fi
    return 0
}

# check_frame_geometry PATH -- nothing, and 0, when the capture is at the
# X root's own resolution; the reading it took, and 1, when it is not.
#
# THIS HELPER USED TO BE UNREACHABLE.  It sat here with no caller at all,
# which shellcheck reported as SC2317, and the answer was to WIRE IT IN
# rather than delete it: the frame it belongs to is the one
# check_one_frame_luminance is already reading, and a capture that is not
# the full X root is not the frame the sidebar crop, the clock region and
# every duration were computed for -- exactly as invisible as a black
# one.  The bulk rule still lives in check_sampled_captures, where ONE
# awk program compares every sampled reading against
# PLAYTHROUGH_SCREEN_WIDTH x PLAYTHROUGH_SCREEN_HEIGHT; this is the
# single-frame form of the same question, and it asks it through the
# shared, time-bounded `geometry` helper so there is one reader of
# `identify` rather than two.
check_frame_geometry() {
    local path="$1"
    local reading=""
    reading="$(geometry "${path}")"
    if [ "${reading}" = \
"${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}" ]; then
        return 0
    fi
    printf '%s' "${reading:-unreadable}"
    return 1
}

# capture_path INDEX -- the canonical path of one capture.
#
# The name is built from env.sh's PLAYTHROUGH_FRAME_FORMAT, which is the
# same format capture.sh writes with and manifest.py records; a second
# hard-coded '%05d' here is exactly the divergence that indirection
# exists to prevent.  SC2059 objects to a variable used as a printf
# format, which is the point, and the expansion is asserted rather than
# assumed.
capture_path() {
    local name=""
    # shellcheck disable=SC2059
    name="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}" "$1")"
    if [ "${name}" = "${PLAYTHROUGH_FRAME_FORMAT}" ]; then
        return 1
    fi
    printf '%s' "${PLAYTHROUGH_FRAMES_DIR}/${name}"
}

# measure_captures LIST_FILE OUTPUT
#   Read geometry and grayscale statistics for every path in LIST_FILE,
#   in chunks, writing "path width height mean std" per line.
#
#   A CHUNK THAT FAILS IS RE-READ ONE FILE AT A TIME, so a single
#   unreadable capture costs its own reading rather than the fifteen
#   beside it: ImageMagick abandons the whole invocation when one input
#   will not open, and a chunked reading that silently lost fifteen frames
#   would be exactly the vacuous verdict this gate exists to prevent.
measure_captures() {
    local list="$1"
    local output="$2"
    local -a chunk=()
    local path=""
    : >"${output}"
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        chunk+=("${path}")
        if [ "${#chunk[@]}" -lt "${LUMINANCE_CHUNK}" ]; then
            continue
        fi
        measure_chunk "${output}" "${chunk[@]}"
        chunk=()
    done <"${list}"
    if [ "${#chunk[@]}" -gt 0 ]; then
        measure_chunk "${output}" "${chunk[@]}"
    fi
}

# measure_chunk OUTPUT PATH...
#   One invocation for the whole chunk, falling back to one per file when
#   the chunk does not come back with exactly one line per image.
measure_chunk() {
    local output="$1"
    shift
    local -a paths=("$@")
    local produced="" lines=0 path="" reading="" err=""
    err="$(tool_error_file convert)"
    produced="$(bounded "${BOUND_CHUNK_SECONDS}" \
        "${CONVERT}" "${paths[@]}" -colorspace Gray \
        -format '%d/%f %w %h %[fx:mean] %[fx:standard_deviation]\n' \
        info: 2>"${err}" || true)"
    lines="$(printf '%s\n' "${produced}" | "${GREP}" -c . || true)"
    if [ -n "${produced}" ] && [ "${lines}" -eq "${#paths[@]}" ]; then
        printf '%s\n' "${produced}" >>"${output}"
        return 0
    fi
    for path in "${paths[@]}"; do
        reading="$(luminance "${path}")"
        if [ -z "${reading}" ]; then
            printf '%s ? ? ? ?\n' "${path}" >>"${output}"
            continue
        fi
        printf '%s %s %s\n' "${path}" \
            "$(bounded "${BOUND_PROBE_SECONDS}" \
                "${IDENTIFY}" -format '%w %h' "${path}" \
                2>"$(tool_error_file identify)" || printf '? ?')" \
            "${reading}" >>"${output}"
    done
}

check_sampled_captures() {
    local count="" index="" path="" sample_count="" summary="" kind=""
    local detail="" checked=0
    local list="${SCRATCH}/captures.list"
    local readings="${SCRATCH}/captures.readings"
    local -a blank=()
    local -a unreadable=()
    local -a bad_geometry=()
    local blank_count=0 unreadable_count=0 geometry_count=0
    count="$(fact capture_count)"
    if ! is_count "${count}" || [ "${count}" -eq 0 ]; then
        record_fail "every capture is a real, non-blank image" \
            "no capture count was established" \
            "a non-zero capture count from group 2"
        record_fail "every capture is at the X root's resolution" \
            "no capture count was established" \
            "a non-zero capture count from group 2"
        return 0
    fi
    sample_count="${LUMINANCE_SAMPLES}"
    if [ "${sample_count}" = "${LUMINANCE_SAMPLES_ALL}" ]; then
        sample_count="${count}"
    fi
    : >"${list}"
    while read -r index; do
        [ -n "${index}" ] || continue
        if ! path="$(capture_path "${index}")"; then
            record_fail "every capture is a real, non-blank image" \
                "PLAYTHROUGH_FRAME_FORMAT='${PLAYTHROUGH_FRAME_FORMAT}' \
did not expand" "a printf format containing %05d"
            record_fail "every capture is at the X root's resolution" \
                "no capture path could be built" \
                "a printf format containing %05d"
            return 0
        fi
        # The REPOSITORY-RELATIVE spelling, because these paths are
        # printed in the report when a frame fails: the gate has already
        # chdir'd to the repository root, so they open identically, and
        # nothing in the report ever names a directory outside the
        # checkout.
        printf '%s\n' "$(rel "${path}")" >>"${list}"
    done < <(sample_indices "${count}" "${sample_count}")

    measure_captures "${list}" "${readings}"

    # ONE awk PROGRAM OVER EVERY READING, rather than one process per
    # frame.  The shell cannot compare floating point at all, and
    # ImageMagick reports a very dark frame in scientific notation --
    # 3.78e-09 is a real number strictly greater than zero -- so the
    # comparison is done where both facts are handled natively.  A
    # reading that is not a number at all is reported as unreadable and
    # never silently treated as zero.
    #
    # SC2016 is disabled for this one command: every `$1`, `$4` and `$5`
    # in the single-quoted program is an awk FIELD, and the two shell
    # values the program needs are passed in properly with -v.  Scoped
    # here rather than file-wide so a real unexpanded variable elsewhere
    # still fails the default lint.
    # shellcheck disable=SC2016
    summary="$("${AWK}" -v expw="${PLAYTHROUGH_SCREEN_WIDTH}" \
        -v exph="${PLAYTHROUGH_SCREEN_HEIGHT}" '
        function numeric(value) {
            return value ~ \
"^[+-]?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?$"
        }
        NF >= 5 {
            seen++
            if (!numeric($4) || !numeric($5)) {
                printf "UNREADABLE %s %s %s\n", $1, $4, $5
                next
            }
            if (!($4 > 0 && $5 > 0)) {
                printf "BLANK %s mean=%s std=%s\n", $1, $4, $5
            }
            if ($2 != expw || $3 != exph) {
                printf "GEOMETRY %s %sx%s\n", $1, $2, $3
            }
        }
        END { printf "COUNT %d\n", seen }' "${readings}")"
    # THE DIAGNOSTIC LISTS ARE BOUNDED.  A whole capture set that came
    # back blank -- the SDL_VIDEODRIVER=dummy signature, which is the
    # failure this gate exists for -- would otherwise put one entry per
    # capture into three shell arrays and then into one report line.  The
    # verdict is reached on the FACT that a frame was blank; the count
    # says how many, and a handful of indices says where to look.
    while IFS= read -r detail; do
        kind="${detail%% *}"
        case "${kind}" in
            BLANK)
                blank_count=$((blank_count + 1))
                if [ "${#blank[@]}" -lt "${DIAGNOSTIC_LIMIT}" ]; then
                    blank+=("${detail#BLANK }")
                fi
                ;;
            UNREADABLE)
                unreadable_count=$((unreadable_count + 1))
                if [ "${#unreadable[@]}" -lt \
                        "${DIAGNOSTIC_LIMIT}" ]; then
                    unreadable+=("${detail#UNREADABLE }")
                fi
                ;;
            GEOMETRY)
                geometry_count=$((geometry_count + 1))
                if [ "${#bad_geometry[@]}" -lt \
                        "${DIAGNOSTIC_LIMIT}" ]; then
                    bad_geometry+=("${detail#GEOMETRY }")
                fi
                ;;
            COUNT) checked="${detail#COUNT }" ;;
        esac
    done <<EOF
${summary}
EOF

    local scope=""
    if [ "${LUMINANCE_SAMPLES}" = "${LUMINANCE_SAMPLES_ALL}" ]; then
        scope="every one of the ${count} committed captures"
    else
        scope="${checked} of ${count} captures (an even spread \
including the first and the last; --samples all decodes every one, and \
the capture stage's own reading below covers all ${count})"
    fi
    if [ "${blank_count}" -eq 0 ] && [ "${unreadable_count}" -eq 0 ] &&
            [ "${checked}" -eq "$(count_lines "${list}")" ]; then
        record_pass "every capture is a real, non-blank image" \
            "${scope} read: each has mean > 0 and std > 0"
    else
        record_fail "every capture is a real, non-blank image" \
            "${checked} read of $(count_lines "${list}") \
requested; blank: ${blank_count} \
(${blank[*]:-none}); unreadable: ${unreadable_count} \
(${unreadable[*]:-none})$(because convert)" \
            "mean > 0 AND std > 0 on every capture read -- mean=0 std=0 \
is the SDL_VIDEODRIVER=dummy signature, and std=0 alone is a uniform \
solid-colour frame"
    fi
    if [ "${geometry_count}" -eq 0 ]; then
        record_pass "every capture is at the X root's resolution" \
            "${checked} captures at \
${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}"
    else
        record_fail "every capture is at the X root's resolution" \
            "${geometry_count} at another size (${bad_geometry[*]})" \
            "${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT} \
on every capture -- a smaller frame means the game window was \
photographed instead of the root"
    fi
}

# WHAT THE CAPTURE STAGE ITSELF MEASURED, AT THE MOMENT IT MEASURED IT.
#
# The sweep above reads the pixels as they are NOW.  This reads what
# capture.sh recorded for each frame as it was taken -- committed in
# playthrough/build/observations.jsonl, one row per capture, carrying the
# frame's sha256 alongside the grayscale mean and standard deviation the
# capturer measured before it accepted the frame.  Two independent
# witnesses to the same property, one contemporaneous and one current,
# and the row is bound to the bytes by its own digest so a row cannot be
# about some other frame.
check_recorded_luminance() {
    local path="${PLAYTHROUGH_OBSERVATIONS}"
    local outcome="" ceiling="" status=0
    if [ ! -f "${path}" ]; then
        record_fail "the capture stage recorded a non-blank reading for \
every frame as it was taken" \
            "$(rel "${path}") is not there" \
            "the capturer's own committed observations, one row per \
capture with the mean and standard deviation it measured at the time"
        return 0
    fi
    ceiling="$(checker_bound)"
    # BOUNDED, AND READ A ROW AT A TIME.  The sidecar carries one row per
    # capture, so this child scales with the session exactly as the
    # checkers in the groups above do: it streams the file, and the only
    # thing it accumulates per row is the frame number the distinct-count
    # is proved from.  The diagnostic list is capped, because "every row
    # was already blank" is the realistic shape of a failure here and an
    # unbounded list would hold one string per capture to print five.
    outcome="$(bounded "${ceiling}" "${PYTHON}" -B -c '
import json
import sys

PROBLEM_LIMIT = 200

path, count = sys.argv[1], int(sys.argv[2])
rows = 0
problems = []
suppressed = 0
frames = set()


def note(text):
    global suppressed
    if len(problems) < PROBLEM_LIMIT:
        problems.append(text)
    else:
        suppressed += 1


with open(path, "r", encoding="utf-8") as handle:
    for number, line in enumerate(handle, 1):
        if not line.strip():
            continue
        rows += 1
        try:
            row = json.loads(line)
        except ValueError as err:
            note("line %d: %s" % (number, err))
            continue
        frames.add(row.get("frame"))
        try:
            mean = float(row.get("luma_mean"))
            std = float(row.get("luma_stddev"))
        except (TypeError, ValueError):
            note("frame %s recorded %r/%r"
                 % (row.get("frame"), row.get("luma_mean"),
                    row.get("luma_stddev")))
            continue
        if not (mean > 0 and std > 0):
            note("frame %s was already mean=%s std=%s when "
                 "it was captured" % (row.get("frame"), mean, std))
if rows != count or len(frames) != count:
    problems.append("%d row(s) covering %d frame(s) against %d captures"
                    % (rows, len(frames), count))
if problems:
    more = ""
    if suppressed:
        more = " (+%d more not named)" % suppressed
    print("FAIL %s%s" % ("; ".join(problems[:5]), more))
else:
    print("PASS %d rows, every one recording mean > 0 and std > 0" % rows)
' "${path}" "$(fact capture_count 0)" 2>&1)" || status=$?
    if bound_expired "${status}"; then
        record_fail "the capture stage recorded a non-blank reading for \
every frame as it was taken" \
            "the reading of $(rel "${path}") did not finish within \
${ceiling}s and was stopped" \
            "a sidecar this gate can read within a ceiling derived from \
the capture count"
        return 0
    fi
    case "${outcome}" in
        PASS*)
            record_pass "the capture stage recorded a non-blank reading \
for every frame as it was taken" \
                "$(rel "${path}"): ${outcome#PASS }"
            ;;
        FAIL*)
            record_fail "the capture stage recorded a non-blank reading \
for every frame as it was taken" \
                "${outcome#FAIL }" \
                "a row per capture, each recording a mean and a standard \
deviation greater than zero -- a frame that was ALREADY blank when it \
was taken has an honest digest, so the capturer's own contemporaneous \
reading is the witness to that"
            ;;
        *)
            record_fail "the capture stage recorded a non-blank reading \
for every frame as it was taken" \
                "the reading could not be taken: ${outcome:-<nothing>}" \
                "a readable observations sidecar"
            ;;
    esac
}

# The film is measured independently of its sources, because a black
# FILM is a distinct fault from a black capture: a wrong pixel format, a
# mis-built concat list or a re-encode could blank the picture after the
# captures were verified.
check_film_luminance() {
    local file="" label="" extracted="" offset="" readings="" reading=""
    local failures=0 taken=0
    local -a offsets=()
    while read -r offset; do
        [ -n "${offset}" ] || continue
        offsets+=("${offset}")
    done <"$(offsets_file)"
    for file in "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"; do
        label="$(rel "${file}")"
        failures=0
        taken=0
        readings=""
        for offset in "${offsets[@]}"; do
            # THE SAME EXTRACTION THE BURNED-IN COMPARISON USED.  Both
            # checks read the same instant out of the same two films, and
            # extracting it twice was two seeks and two decodes for one
            # picture; see ONE DECODE PER FILM above.
            if ! extracted="$(extracted_frame "${file}" \
                    "${offset}")"; then
                record_fail "frames taken out of ${label} are not \
blank" \
                    "no frame could be decoded at ${offset}s\
$(because ffmpeg)" \
                    "one decodable frame at each of ${offsets[*]}s -- a \
film that stops early cannot answer for its later seconds"
                failures=$((failures + 1))
                continue
            fi
            taken=$((taken + 1))
            if ! check_one_frame_luminance "${extracted}" \
                    "the frame ${offset}s into ${label}"; then
                failures=$((failures + 1))
                continue
            fi
            reading="${LAST_LUMINANCE}"
            readings="${readings}${readings:+; }${offset}s: ${reading}"
        done
        if [ "${failures}" -eq 0 ] && [ "${taken}" -gt 0 ]; then
            record_pass "frames taken out of ${label} are not blank" \
                "${taken} reading(s) across the film -- ${readings}"
        fi
    done
}

group_luminance() {
    group 6 "the luminance gate -- proof the pixels are real"
    record_info "the calibration reading behind this threshold" \
        "${LUMINANCE_REFERENCE}"
    check_sampled_captures
    check_recorded_luminance
    check_film_luminance
}


# ---------------------------------------------------------------------
# 7  VERSION CONTROL -- THE "COMMITTED IN APPEARANCE ONLY" GUARD
#
# This is the group that exists because `git add` reports success while
# skipping an ignored file.  Cataclysm-DDA names its per-character save
# files with a leading '#' (src/game_io.cpp:601-641), .gitignore carries
# `\#*` at line 131, an unanchored `*.log` at line 31 and `debug.log` at
# line 79, and without the terminal `!/playthrough/**` negation the save
# is silently absent from every commit while every other count still
# tallies.  So membership is asserted TWICE, from both directions: the
# file is in `git ls-files`, AND `git check-ignore` denies knowing it.
#
# TWO SHAPES OF CHARACTER SAVE ARE BOTH CORRECT.  With world compression
# enabled -- WORLD_COMPRESSION2 defaults to true -- the write is
# `playerfile + SAVE_EXTENSION + zzip_suffix`, i.e. `#<b64>.sav.zzip`
# (src/game_io.cpp:601-641, src/worldfactory.h:25); without it, the plain
# `#<b64>.sav`.  Either satisfies this gate.  Demanding only the plain
# form would manufacture a failure on a default world.
#
# `.shortcuts` IS NEVER REQUIRED.  SAVE_EXTENSION_SHORTCUTS exists at
# src/path_info.h:17, but the only write of it is inside
# `#if defined(__ANDROID__)` (src/game_io.cpp:629-634): it is an Android
# file and will never appear on a Linux host.  A gate that required it
# would fail every correct run.
#
# AND A DEATH ENDING LEAVES NO LIVE WORLD BEHIND AT ALL, WHICH IS THE
# ENGINE'S OWN DOING AND NOT A LOST ARTIFACT.  Death is a sanctioned
# ending, and when the survivor who died was the world's only character
# `turn_handler::cleanup_at_end()` (src/do_turn.cpp:111-207) does two
# things that this group has to know about:
#
#   1. `move_save_to_graveyard()` (src/game_io.cpp:247-275) RENAMES every
#      `save/<World>/#<b64>.*` file into
#      `<userdir>/graveyard/<timestamp>/`.  The survivor's save is
#      relocated, not deleted -- and the leading '#' moves with it, so
#      the graveyard copy is subject to .gitignore's `\#*` rule exactly
#      as the live one was.  Tracking it proves the same property.
#   2. `characters.empty()` is then true, and WORLD_END decides what
#      happens to the world.  Its engine DEFAULT is "reset"
#      (src/options.cpp:2836-2841), which calls
#      `delete_world(name, false)` (src/worldfactory.cpp:2458-2496) --
#      documented there as "Clear out everything except options and mods
#      and compression dictionaries".  `isForbidden()`
#      (src/worldfactory.cpp:2449-2456) spares only worldoptions.json,
#      mods.json and *.dict, so master.gsav, the maps, the overmaps and
#      the live character files are all removed.
#
# So on a death-ended world, `master.gsav` is ABSENT BY DESIGN and a gate
# that demanded one in the index would fail every correct death ending.
# The proof that R1 was honoured is then in HISTORY, which is what R1
# asks for anyway -- a commit after character creation and another after
# the ending.  This group therefore accepts the death shape only when all
# three of its parts are present: a commit reachable from HEAD that
# carries a master.gsav, a tracked relocated save in the graveyard, and a
# WORLD_END of "reset" or "delete" in the tracked worldoptions.json.
#
# THAT THIRD REQUIREMENT IS WHAT KEEPS THE CHECK STRONG.  The failure
# this whole group exists to catch is the silent one: `git add` skipping
# an ignored save and exiting 0.  In that failure NO commit carries a
# master.gsav and NO graveyard save is tracked, so the death shape is not
# available to it and the verdict is still FAIL.
# ---------------------------------------------------------------------
git_tracked() {
    "${GIT}" ls-files -- "$@" 2>/dev/null || true
}

git_tracked_count() {
    git_tracked "$@" | "${GREP}" -c . || true
}

check_git_worktree() {
    local top=""
    top="$("${GIT}" rev-parse --show-toplevel 2>/dev/null || true)"
    if [ "${top}" = "${PLAYTHROUGH_REPO_ROOT}" ]; then
        record_pass "the artifacts live in the working tree of a git \
repository" "$(rel "${top}")"
        return 0
    fi
    record_fail "the artifacts live in the working tree of a git \
repository" \
        "git reports '${top:-nothing}' while env.sh resolved this \
checkout to '$(rel "${PLAYTHROUGH_REPO_ROOT}")'" \
        "the same directory -- every check below reads git from here"
}

# WHETHER THIS CHECKOUT'S GIT CREDENTIAL IS READABLE BY ANYBODY ELSE.
#
# A review found a live bearer token in this checkout's own
# .git/config -- a push URL of the shape
# https://x-access-token:<secret>@host/... -- in a file that was mode
# 0644.  Two halves of that, and only one is anybody's to fix here.
#
# The token's PRESENCE is the platform's arrangement.  `credential.helper`
# is set empty in this checkout and `credential.interactive` is false, so
# the URL is the repository's only authentication path; removing the
# credential from it would break publication outright, and revoking or
# rotating the token is the platform's act and not this pipeline's.  So
# this gate does not demand that it be gone.
#
# The token's REACH is a file mode, and that is measurable and fixable.
# A group- or world-readable config hands the token to every local
# account, every child process and every git hook, so this FAILS on one.
# The check is deliberately conditional on a credential actually being
# present: a config with nothing secret in it has nothing for its mode to
# expose, and failing it would be noise that trains a reader to ignore
# the line that matters.
#
# commit_artifacts.sh asserts the same property before it commits, so
# this is the audit of a control rather than the only place it is
# applied.
check_git_config_credential_mode() {
    local name="git's own configuration does not expose this \
checkout's credential to other accounts"
    local dir="" config="" mode=""
    dir="$("${GIT}" rev-parse --absolute-git-dir 2>/dev/null || true)"
    if [ -z "${dir}" ] || [ ! -d "${dir}" ]; then
        record_fail "${name}" \
            "git could not report its own directory, so its \
configuration file could not be located" \
            "a readable git directory -- whether a credential is \
exposed cannot be answered without one"
        return 0
    fi
    config="${dir}/config"
    if [ ! -f "${config}" ]; then
        record_pass "${name}" \
            "this checkout has no $(rel "${config}") at all, so it \
holds no credential"
        return 0
    fi
    mode="$(playthrough_permission_bits "${config}")" || mode=""
    if ! "${GREP}" -Eq -- '://[^/@[:space:]]*:[^/@[:space:]]*@' \
            "${config}" 2>/dev/null; then
        record_pass "${name}" \
            "$(rel "${config}") embeds no credential in a remote URL \
(mode ${mode:-unreadable}), so there is nothing in it for its mode to \
expose"
        return 0
    fi
    if [ -z "${mode}" ]; then
        record_fail "${name}" \
            "$(rel "${config}") carries a credential in a remote URL \
and its mode could not be read" \
            "a readable mode -- an unmeasurable one is not the same \
fact as a safe one"
        return 0
    fi
    if [ $(( 8#${mode} & 8#077 )) -ne 0 ]; then
        record_fail "${name}" \
            "$(rel "${config}") carries a credential in a remote URL \
and is mode ${mode}, so group or other can read it" \
            "owner-only (600).  The credential itself is the \
platform's to rotate and cannot be removed from the URL -- \
credential.helper is empty here, so that URL is the only \
authentication this repository has -- but its file mode is this \
checkout's to hold shut"
        return 0
    fi
    record_pass "${name}" \
        "$(rel "${config}") carries a credential and is mode ${mode} \
-- readable only by its owner.  Rotating that token is the platform's \
act, not this pipeline's; the reach of it is what is measured here"
}

# character_save_paths -- the TRACKED character save files, in either
# accepted shape.  Printed one per line; empty when there are none.
character_save_paths() {
    git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -E '/#[^/]*\.sav(\.zzip)?$' || true
}

# saves_on_disk PATTERN -- matching files that EXIST, whatever git thinks
# of them, printed one absolute path per line.
#
# This is deliberately independent of the index, and the reason is the
# failure mode itself: if the save is not tracked, a list built from `git
# ls-files` is empty, and a check-ignore run over that empty list would
# examine nothing and report success.  The two halves of the guard have
# to be measured from two different places or they collapse into one.
# `find -name` rather than a glob built from a variable: the pattern is
# then an argument rather than something the shell has to be trusted not
# to split, and the depth bounds keep the search to save/<World>/<file>.
saves_on_disk() {
    "${FIND}" "${PLAYTHROUGH_SAVE_DIR}" -mindepth 2 -maxdepth 2 -type f \
        -name "$1" -print 2>/dev/null || true
}

# Where a death puts the survivor's save.  graveyarddir_path() is
# `user_dir / "graveyard"` (src/path_info.cpp:300-302) and
# move_save_to_graveyard writes one `<timestamp>` directory beneath it
# per death (src/game_io.cpp:247-275), so the saves sit exactly two
# levels down -- the same depth the live ones sit at under save/.
readonly PLAYTHROUGH_GRAVEYARD_DIR="${PLAYTHROUGH_USERDIR}/graveyard"

# graveyard_save_paths -- the TRACKED character save files a death
# relocated, in either accepted shape.  One per line; empty when none.
graveyard_save_paths() {
    git_tracked "${PLAYTHROUGH_GRAVEYARD_DIR}" |
        "${GREP}" -E '/#[^/]*\.sav(\.zzip)?$' || true
}

# graveyard_saves_on_disk -- the same files as they EXIST, whatever git
# thinks of them, for the same reason saves_on_disk is measured off the
# filesystem: a list built from the index is empty precisely when the
# save was never added, and a check over an empty list reports success.
graveyard_saves_on_disk() {
    "${FIND}" "${PLAYTHROUGH_GRAVEYARD_DIR}" -mindepth 2 -maxdepth 2 \
        -type f -name '#*.sav' -print 2>/dev/null || true
}

# world_end_value -- the WORLD_END this world was played under, read out
# of the COMMITTED worldoptions.json.  Committed rather than on-disk
# because it is being used as evidence: the file a stranger can read is
# the one in the commit.  Nothing is printed when it cannot be read, and
# the caller treats that as "no death shape available".
world_end_value() {
    local path=""
    path="$(git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -m 1 '/worldoptions\.json$' || true)"
    if [ -z "${path}" ]; then
        return 1
    fi
    "${GIT}" show "HEAD:${path}" 2>/dev/null |
        bounded "${BOUND_PROBE_SECONDS}" \
            "${PYTHON}" -B -c "${WORLDOPTIONS_STDIN_READER}" \
            2>/dev/null || return 1
}

# WHY A HISTORICAL master.gsav MUST BE THIS SURVIVOR'S, AND NOT MERELY
# SOMEBODY'S.
#
# This used to answer "the newest commit reachable from HEAD whose tree
# carries a master.gsav", and check_save_tracked accepted that as proof
# that a death-cleared world's save HAD been committed.  A review found
# the hole: the branch carries the checkpoints of EVERY survivor ever
# recorded on it, so a commit belonging to a PREVIOUS survivor -- a world
# that was played, saved, committed and then abandoned generations ago --
# satisfied the claim for the current one.  The evidence and the session
# it vouched for need never have had anything to do with each other, and
# a companion finding caught exactly that in prose: commits from a
# retired survivor's era cited as proof of the current survivor's
# ordering.
#
# So a carrier is now bound to THIS SURVIVOR'S GENERATION, by two
# independent facts that the history already carries:
#
#   1. IT IS AT OR AFTER THIS SURVIVOR'S CREATION.  checkpoint_anchor
#      resolves the newest `creation` checkpoint reachable from HEAD --
#      the one the committer itself anchors to -- and the candidate must
#      have that commit as an ancestor.  A previous survivor's commit
#      sits BEFORE the current creation and is refused by construction.
#      `--is-ancestor X X` is true, so the creation commit may be its own
#      carrier, which is right: creation is the first point at which a
#      save exists to commit.
#   2. IT IS ABOUT THE SAME SURVIVOR.  survivor_at reads
#      config/lastworld.json out of the candidate's own tree and it must
#      name the same world and character HEAD names.  This is the check
#      that still holds if the branch were ever rebased or grafted such
#      that the ancestry alone stopped being discriminating.
#
# FAILING CLOSED IS THE DIRECTION.  When there is no creation checkpoint
# to anchor to, or HEAD's own survivor cannot be read, no candidate is
# accepted -- an unbindable claim is not a weaker claim, it is no claim.
# The reason is published in HISTORY_MASTER_REASON so the verdict can say
# WHICH of the three things was wrong rather than only that nothing was
# found; "no commit carries one" and "one exists but belongs to somebody
# else" are very different diagnoses.
#
# `rev-list HEAD -- <dir>` lists only the commits where that directory
# CHANGED, so this walks the checkpoints rather than the whole history,
# and the tree is then read directly instead of being inferred from the
# diff: a commit that DELETED the file also "touches" it, and only the
# tree can tell the two apart.
#
# IT SETS GLOBALS RATHER THAN PRINTING, and that is not a style choice.
# The caller used to read it as `carrier="$(history_master_commit)"` --
# a COMMAND SUBSTITUTION, which is a subshell, so a reason assigned
# inside it never reached the verdict that needed it.  Measured while
# writing this: the diagnosis came out as the caller's fallback text
# every time.  Both answers therefore come back in variables the caller
# can actually read.
HISTORY_MASTER_REASON=""
HISTORY_MASTER_COMMIT=""
resolve_history_master_commit() {
    local rel_dir="" commit="" anchor="" survivor="" candidate=""
    local carried=0 foreign=0
    HISTORY_MASTER_REASON=""
    HISTORY_MASTER_COMMIT=""
    rel_dir="$(rel "${PLAYTHROUGH_SAVE_DIR}")"
    anchor="$(checkpoint_anchor HEAD)"
    if [ -z "${anchor}" ]; then
        HISTORY_MASTER_REASON="no '${CHECKPOINT_CREATION_NAME}' \
checkpoint is reachable from HEAD, so no commit can be bound to this \
survivor's generation and none is accepted as evidence for it"
        return 0
    fi
    survivor="$(survivor_at HEAD || true)"
    if [ -z "${survivor}" ]; then
        HISTORY_MASTER_REASON="HEAD carries no readable \
playthrough/userdir/config/lastworld.json, so which survivor the tree \
is about cannot be established and no historical commit is accepted on \
its behalf"
        return 0
    fi
    while IFS= read -r commit; do
        [ -n "${commit}" ] || continue
        "${GIT}" ls-tree -r --name-only "${commit}" -- "${rel_dir}" \
            2>/dev/null | "${GREP}" -q '/master\.gsav$' || continue
        carried=$((carried + 1))
        "${GIT}" merge-base --is-ancestor "${anchor}" "${commit}" \
            2>/dev/null || { foreign=$((foreign + 1)); continue; }
        candidate="$(survivor_at "${commit}" || true)"
        if [ "${candidate}" != "${survivor}" ]; then
            foreign=$((foreign + 1))
            continue
        fi
        HISTORY_MASTER_COMMIT="${commit}"
        return 0
    done < <("${GIT}" rev-list HEAD -- "${rel_dir}" 2>/dev/null || true)
    if [ "${carried}" -eq 0 ]; then
        HISTORY_MASTER_REASON="no commit reachable from HEAD carries a \
master.gsav under ${rel_dir} either, which is exactly what a save git \
never added looks like"
    else
        HISTORY_MASTER_REASON="${carried} commit(s) reachable from HEAD \
carry a master.gsav under ${rel_dir}, but ${foreign} of them are NOT \
this survivor's: a carrier has to be at or after this session's \
'${CHECKPOINT_CREATION_NAME}' checkpoint (${anchor:0:10}) and name the \
same survivor HEAD does (${survivor}).  A previous survivor's save does \
not vouch for this one"
    fi
    return 0
}

check_save_tracked() {
    local masters="" saves="" worldoptions=""
    local buried="" world_end="" carrier=""
    masters="$(git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -c '/master\.gsav$' || true)"
    buried="$(graveyard_save_paths | "${GREP}" -c . || true)"
    if [ "${masters:-0}" -ge 1 ]; then
        record_pass "the world's own save file is tracked by git" \
            "${masters} master.gsav (SAVE_MASTER, src/path_info.h:11)"
    else
        world_end="$(world_end_value || true)"
        resolve_history_master_commit
        carrier="${HISTORY_MASTER_COMMIT}"
        if [ -n "${carrier}" ] && [ "${buried:-0}" -ge 1 ] &&
                { [ "${world_end}" = "reset" ] ||
                    [ "${world_end}" = "delete" ]; }; then
            record_pass "the world's own save file is tracked by git" \
                "no LIVE master.gsav, and correctly so: this survivor \
died, and the committed worldoptions.json records \
WORLD_END='${world_end}' -- the engine's own default \
(src/options.cpp:2836-2841) -- so cleanup_at_end cleared the world \
(src/do_turn.cpp:190-196, src/worldfactory.cpp:2458-2496).  It WAS \
committed: commit ${carrier} carries a master.gsav under \
$(rel "${PLAYTHROUGH_SAVE_DIR}").  And the survivor's save was \
relocated rather than lost -- ${buried} tracked file(s) under \
$(rel "${PLAYTHROUGH_GRAVEYARD_DIR}")"
        else
            local unaccounted=""
            if [ -z "${carrier}" ]; then
                # resolve_history_master_commit's own reason, which
                # distinguishes "nothing carries one" from "one exists
                # and belongs to a previous survivor" -- two very
                # different diagnoses that a bare absence used to report
                # identically.
                unaccounted="${HISTORY_MASTER_REASON:-no commit \
reachable from HEAD carries one either}"
            fi
            if [ "${buried:-0}" -lt 1 ]; then
                unaccounted="${unaccounted}${unaccounted:+; }no \
relocated survivor save is tracked under \
$(rel "${PLAYTHROUGH_GRAVEYARD_DIR}"), so no death cleanup accounts \
for the absence"
            fi
            if [ "${world_end}" != "reset" ] &&
                    [ "${world_end}" != "delete" ]; then
                unaccounted="${unaccounted}${unaccounted:+; }the \
committed worldoptions.json records WORLD_END=\
'"'"'${world_end:-unreadable}'"'"', which does not clear a world"
            fi
            record_fail "the world's own save file is tracked by git" \
                "no master.gsav under $(rel "${PLAYTHROUGH_SAVE_DIR}") \
is tracked, and nothing accounts for it: ${unaccounted}" \
                "either a tracked master.gsav, or -- for a world the \
engine cleared after a death -- all three of a commit that carries one, \
a tracked relocated save in the graveyard, and WORLD_END=reset or \
delete in the committed worldoptions.json"
        fi
    fi

    saves="$(character_save_paths | "${GREP}" -c . || true)"
    if [ "${saves:-0}" -ge 1 ]; then
        record_pass "the survivor's own save file is tracked by git" \
            "${saves} file(s) matching #<base64>.sav or \
#<base64>.sav.zzip under $(rel "${PLAYTHROUGH_SAVE_DIR}") -- both \
shapes are correct, the compressed one being the default"
    elif [ "${buried:-0}" -ge 1 ]; then
        record_pass "the survivor's own save file is tracked by git" \
            "${buried} file(s) matching #<base64>.sav or \
#<base64>.sav.zzip under $(rel "${PLAYTHROUGH_GRAVEYARD_DIR}"), where \
move_save_to_graveyard RENAMED them when this survivor died \
(src/game_io.cpp:247-275).  The leading '#' moved with the file, so the \
graveyard path is subject to .gitignore's \\#* rule (line 131) exactly \
as the live one was, and tracking it proves the same property"
    else
        record_fail "the survivor's own save file is tracked by git" \
            "no #<base64>.sav or #<base64>.sav.zzip is tracked under \
either $(rel "${PLAYTHROUGH_SAVE_DIR}") or \
$(rel "${PLAYTHROUGH_GRAVEYARD_DIR}")" \
            "at least one, in either place; if none is tracked, \
.gitignore's \\#* rule (line 131) swallowed it and 'git add' said \
nothing"
    fi

    worldoptions="$(git_tracked "${PLAYTHROUGH_SAVE_DIR}" |
        "${GREP}" -c '/worldoptions\.json$' || true)"
    if [ "${worldoptions:-0}" -ge 1 ]; then
        record_pass "the world's option overrides are tracked by git" \
            "${worldoptions} worldoptions.json"
    else
        record_fail "the world's option overrides are tracked by git" \
            "no worldoptions.json is tracked" \
            "at least one, so the world can be reproduced"
    fi
}

# ---------------------------------------------------------------------
# check-ignore IS THE PROOF THAT NOTHING IS SILENTLY EXCLUDED -- AND IT
# HAS TO BE RUN THE HARD WAY, OR IT PROVES NOTHING AT ALL.
#
# Two traps, both measured on this checkout:
#
#   1. WITHOUT --no-index, `git check-ignore` CONSULTS THE INDEX and
#      reports any TRACKED path as not-ignored, whatever .gitignore says.
#      Measured: with the terminal negation deleted, a tracked character
#      save still came back "not ignored" -- so the naive form of this
#      check passes even when the rule that saves the file has been
#      removed.  It is vacuous exactly when it matters, because on a
#      fresh session the file is NOT yet tracked and `git add` will
#      apply the patterns, not the index.
#   2. WITH --no-index, check-ignore exits ZERO whenever ANY pattern
#      matches -- INCLUDING A NEGATION.  Measured: the same path exits 0
#      both ways, printing `.gitignore:275:!/playthrough/**` when the
#      negation is present and `.gitignore:131:\#*` when it is not.  So
#      the exit status cannot answer the question either.
#
# The pattern that DECIDED is what answers it: -v prints it, and a
# pattern beginning with '!' means re-included.  So the verdict here is
# read off the pattern, and the only outcomes accepted are "no pattern
# matched" and "the deciding pattern was a negation".
# ---------------------------------------------------------------------
deciding_ignore_pattern() {
    "${GIT}" check-ignore -v --no-index -- "$1" 2>/dev/null |
        "${HEAD}" -n 1 |
        "${SED}" -e 's/\t.*$//' -e 's/^[^:]*:[0-9]*://' || true
}

check_nothing_ignored() {
    local -a paths=()
    local path="" candidate=""
    paths+=("${PLAYTHROUGH_MANIFEST}" "${PLAYTHROUGH_TIMELINE}"
        "${PLAYTHROUGH_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}"
        "${PLAYTHROUGH_TRANSCRIPT_SRT}" "${PLAYTHROUGH_TRANSCRIPT_MD}"
        "${PLAYTHROUGH_DOSSIER}" "${PLAYTHROUGH_REQUIREMENTS}"
        "${PLAYTHROUGH_CONCAT_LIST}")
    if candidate="$(capture_path 1)"; then
        paths+=("${candidate}")
    fi
    # The save-side paths come off the FILESYSTEM, never out of the
    # index -- see saves_on_disk for why that independence is the whole
    # point of this check.
    local pattern=""
    for pattern in '#*.sav' '#*.sav.zzip' '*.log' 'master.gsav' \
            'worldoptions.json'; do
        while IFS= read -r path; do
            [ -n "${path}" ] || continue
            paths+=("${path}")
        done < <(saves_on_disk "${pattern}")
    done
    # A death moves the character save into the graveyard, where its
    # name still begins with '#'.  It is the file `\#*` would swallow on
    # a death-ended session, so it belongs in this sample whenever it
    # exists.
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        paths+=("${path}")
    done < <(graveyard_saves_on_disk)
    for path in "${PLAYTHROUGH_CONFIG_DIR}/debug.log" \
            "${PLAYTHROUGH_USERDIR}/debug.log"; do
        if [ -f "${path}" ]; then
            paths+=("${path}")
        fi
    done

    local -a ignored=()
    local decided="" negations=0 unmatched=0
    for path in "${paths[@]}"; do
        decided="$(deciding_ignore_pattern "${path}")"
        if [ -z "${decided}" ]; then
            unmatched=$((unmatched + 1))
        elif [ "${decided#!}" != "${decided}" ]; then
            negations=$((negations + 1))
        else
            ignored+=("$(rel "${path}") <- ${decided}")
        fi
    done
    if [ "${#ignored[@]}" -eq 0 ]; then
        record_pass "git's ignore rules exclude none of the artifact \
classes" \
            "${#paths[@]} representative paths -- a character save \
live or buried, master.gsav, worldoptions.json, an engine log, a \
capture, both films, the cue file, the readable record, the record, the \
timeline, the concat list, the dossier and the requirements -- of which \
${negations} are re-included by a negation and ${unmatched} match no \
rule at all"
        return 0
    fi
    record_fail "git's ignore rules exclude none of the artifact \
classes" \
        "excluded, with the deciding pattern: ${ignored[*]}" \
        "no path decided by a non-negated rule -- .gitignore's terminal \
'!/playthrough/**' must be the LAST matching pattern, and remember it \
cannot re-include anything whose parent DIRECTORY was excluded, because \
git never descends into an excluded directory to evaluate negations \
inside it"
}

check_every_class_tracked() {
    local -a missing=()
    local entry="" label="" path="" count=""
    local -a inventory=(
        "the captures:${PLAYTHROUGH_FRAMES_DIR}"
        "the transition images:${PLAYTHROUGH_TRANSITIONS_DIR}"
        "the film:${PLAYTHROUGH_MOVIE}"
        "the captioned film:${PLAYTHROUGH_MOVIE_CC}"
        "the cue file:${PLAYTHROUGH_TRANSCRIPT_SRT}"
        "the readable record:${PLAYTHROUGH_TRANSCRIPT_MD}"
        "the record:${PLAYTHROUGH_MANIFEST}"
        "the timeline:${PLAYTHROUGH_TIMELINE}"
        "the dossier:${PLAYTHROUGH_DOSSIER}"
        "the requirements:${PLAYTHROUGH_REQUIREMENTS}"
        "the engine's configuration:${PLAYTHROUGH_CONFIG_DIR}"
    )
    for entry in "${inventory[@]}"; do
        label="${entry%%:*}"
        path="${entry#*:}"
        count="$(git_tracked_count "${path}")"
        if [ "${count:-0}" -eq 0 ]; then
            missing+=("${label} ($(rel "${path}"))")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_pass "every artifact class is tracked by git" \
            "${#inventory[@]} classes, each with at least one tracked \
file"
        return 0
    fi
    record_fail "every artifact class is tracked by git" \
        "untracked class(es): ${missing[*]}" \
        "all ${#inventory[@]} classes tracked -- save data, captures, \
film, transcripts and the requirements are all committed"
}

# THE DECIMATION CHECK.  If the tracked capture count is lower than the
# count on disk, frames were sampled, deduplicated or partly added.  That
# is a failure and not an optimisation: repository size never outranks
# completeness here.
check_tracked_frame_count() {
    local tracked="" ondisk=""
    tracked="$(git_tracked_count "${PLAYTHROUGH_FRAMES_DIR}")"
    # GROUP 2'S COUNT WHEN THERE IS ONE, AND THIS GROUP'S OWN OTHERWISE.
    # The post-commit phase measures the history without re-measuring the
    # artifacts, so group 2 has not run and no fact has been published --
    # and this check must not fail for the absence of a number it can
    # take for itself.  Counting the record's lines is one process and no
    # resident list, and group 2 asserts elsewhere that that number is
    # the capture count.
    ondisk="$(fact capture_count)"
    if ! is_count "${ondisk}"; then
        ondisk="$(count_lines "${PLAYTHROUGH_MANIFEST}")"
    fi
    if ! is_count "${ondisk}" || [ "${ondisk}" -eq 0 ]; then
        record_fail "every capture on disk is tracked by git" \
            "the on-disk capture count could not be established, from \
group 2 or from $(rel "${PLAYTHROUGH_MANIFEST}")" \
            "a capture count to compare the tracked count against"
        return 0
    fi
    if [ "${tracked:-0}" -eq "${ondisk}" ]; then
        record_pass "every capture on disk is tracked by git" \
            "${tracked} tracked == ${ondisk} on disk"
        return 0
    fi
    record_fail "every capture on disk is tracked by git" \
        "${tracked:-0} tracked against ${ondisk} on disk" \
        "equal counts -- no decimation, no sampling, no deduplication \
and no partial 'git add'"
}

check_nothing_uncommitted() {
    local dirty="" count=""
    dirty="$("${GIT}" status --porcelain -uall -- \
        "${PLAYTHROUGH_DIR}" 2>/dev/null || true)"
    count="$(printf '%s' "${dirty}" | "${GREP}" -c . || true)"
    if [ "${count:-0}" -eq 0 ]; then
        record_pass "nothing under playthrough/ is left uncommitted" \
            "git status --porcelain is empty"
        return 0
    fi
    record_fail "nothing under playthrough/ is left uncommitted" \
        "${count} path(s): $(printf '%s' "${dirty}" | "${HEAD}" -n 6 |
            "${TR}" '\n' ';')" \
        "an empty porcelain -- every artifact staged and committed"
}

check_no_bytecode() {
    local name="${1:-no interpreter bytecode has been left under \
playthrough/}"
    local -a found=()
    local path=""
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        found+=("$(rel "${path}")")
    done < <("${FIND}" "${PLAYTHROUGH_DIR}" \
        \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' \) \
        -print 2>/dev/null || true)
    local tracked=""
    tracked="$(git_tracked "${PLAYTHROUGH_DIR}" |
        "${GREP}" -E '(__pycache__|\.pyc$|\.pyo$)' | "${HEAD}" -n 3 || true)"
    if [ "${#found[@]}" -eq 0 ] && [ -z "${tracked}" ]; then
        record_pass "${name}" \
            "no __pycache__, .pyc or .pyo on disk or in the index"
        return 0
    fi
    record_fail "${name}" \
        "on disk: ${found[*]:-none}; tracked: ${tracked:-none}" \
        "none -- env.sh exports PYTHONDONTWRITEBYTECODE=1 and every \
interpreter call adds -B, and the .gitignore negation deliberately adds \
no re-exclusion, so a stray file here WOULD become trackable"
}

# WHAT EACH PATH IS, AND WHAT IT CARRIES.
#
# The committer refuses both of these before it stages anything, and that
# is the right place for a control whose job is to stop a bad commit from
# being taken.  It is not sufficient on its own, for a reason this very
# remediation demonstrates: NOT EVERY COMMIT IN THIS HISTORY IS TAKEN BY
# commit_artifacts.sh.  A tooling change is committed with ordinary git,
# and a checkpoint's gates say nothing about a commit that never ran them.
#
# So the gate asks the same questions of the tree it is measuring,
# independently of who committed it -- and asks them BY RUNNING THE
# COMMITTER'S OWN read-only `scan`, rather than by restating eleven
# regular expressions and a reviewed baseline here.  Two copies of a rule
# set are two things to keep in step, and they answer differently the
# first time one of them is updated.  `scan` takes no lock (it is a
# reporter, like `status`), so it cannot deadlock against the exclusive
# hold this gate is running under.
#
# What it establishes, in one property because the diagnosis names which
# half of it failed:
#
#   * a hard link into this tree publishes bytes that live somewhere else
#     and is an ordinary regular file to every other test here;
#   * a symlink is invisible to a `find -type f` sweep entirely;
#   * a file owned by another account was put here by somebody else;
#   * another filesystem mounted inside the tree is a whole tree of
#     content nobody in this pipeline produced;
#   * and an innocuously named file holding a credential satisfies every
#     structural question either of those asks.
#
# It is artifact-shaped, so the pre-commit phase answers it; a commit does
# not change what a path is or what it contains, and `--phase all` is how
# it is re-measured deliberately.
check_staging_soundness() {
    local name="every artifact is a single-linked regular file this \
account owns, carrying no secret material"
    local committer="${PLAYTHROUGH_TOOLING_DIR}/commit_artifacts.sh"
    local output="" status=0
    if [ ! -x "${committer}" ]; then
        record_fail "${name}" \
            "$(rel "${committer}"), which owns the provenance rules and \
the reviewed secret baseline, is not beside this gate or is not \
executable" \
            "the committer present, so that ONE rule set answers this \
question wherever it is asked"
        return 0
    fi
    set +e
    output="$(bounded "${BOUND_SUITE_SECONDS}" "/bin/bash" --noprofile \
        --norc "${committer}" scan 2>&1)"
    status=$?
    set -e
    # THE LAST LINE ONLY, and that is about the committed report rather
    # than about brevity.  `scan` re-asserts the repository first, so its
    # output opens with the branch name and the git-configuration
    # containment note -- both true, neither an answer to THIS question,
    # and the branch name in particular would make a committed acceptance
    # report differ between branches while measuring an identical tree.
    # The conclusion is the last line either way: the soundness statement
    # when it holds, the refusal's own diagnosis when it does not.
    output="$(printf '%s\n' "${output}" | "${SED}" -e '/^[[:space:]]*$/d' \
        -e 's/^playthrough: //' -e 's/^FATAL: //' | "${TAIL}" -n 1)"
    if [ "${status}" -eq 0 ]; then
        record_pass "${name}" "${output:-the committer reported nothing}"
        return 0
    fi
    record_fail "${name}" "exit ${status}: ${output:-<no diagnosis>}" \
        "directories and single-linked regular files only, all owned by \
this account and all on the checkout's own filesystem, and no path \
carrying credential material outside the committer's reviewed baseline.  \
The engine names its own files and this gate does not second-guess those \
names -- but WHAT a path is, and what it holds, has to hold regardless of \
what it is called"
}

# NOBODY BUT THE OWNER MAY WRITE TO THE EVIDENCE.
#
# A security review measured the delivered tree and found FIFTEEN
# directories at mode 2777 and a hundred and fifty-one files at 0666 --
# the survivor's save and its log, the engine's options and keybindings,
# the captioned film and the acceptance report among them.  Every one of
# those was rewritable, and every one of those directories was a place
# any local account could delete a frame from and put another in its
# place.  Nothing in the pipeline said so, because nothing looked.
#
# THE PROPERTY IS WRITE, NOT READ, and that distinction is the whole
# reason this is a fair check rather than an unachievable one.  This tree
# is committed to a git repository and is meant to be read; making it
# owner-only would protect nothing that is not about to be published.
# What may never be true of evidence is that somebody else can change it.
#
# The producers enforce it as they go -- playthrough_mkdirs on the
# artifact directories, capture.sh on the frames directory, launch_game.sh
# via the engine's umask, embed_captions.sh on the captioned film,
# publish_report on the report -- and this is the sweep that proves they
# all did, over every path rather than over the ones somebody remembered.
check_no_foreign_write() {
    local name="nothing under playthrough/ is writable by any account \
but its owner"
    local -a offenders=()
    local path="" total=0
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        total=$((total + 1))
        if [ "${#offenders[@]}" -lt 5 ]; then
            offenders+=("$(rel "${path}") ($(
                playthrough_permission_bits "${path}" || printf '?'))")
        fi
    done < <("${FIND}" "${PLAYTHROUGH_DIR}" \
        \( -type f -o -type d \) -perm /022 -print 2>/dev/null || true)
    if [ "${total}" -eq 0 ]; then
        record_pass "${name}" \
            "every file and directory under $(rel "${PLAYTHROUGH_DIR}") \
withholds write access from group and other"
        return 0
    fi
    record_fail "${name}" \
        "${total} path(s) grant write access to group or other, \
including ${offenders[*]}" \
        "none.  A frame, a save or a film another account can rewrite is \
substitutable, so it is not evidence about this session -- run 'chmod -R \
go-w $(rel "${PLAYTHROUGH_DIR}")' and find out which producer left it \
open"
}

# THE COMMIT ORDER.  Ancestry, not dates: a timestamp can be anything,
# whereas "this commit is reachable from that one" is a fact about the
# graph.  The dossier had to exist before the first gameplay frame, so its
# earliest commit must be a STRICT ancestor of the first capture's.
#
# BOTH VERDICTS BELOW SAY WHAT WAS MEASURED, and that is a correction
# rather than a flourish.  The first used to read "at least one after the
# survivor was created and one after the session was saved and quit",
# which a COUNT OF COMMITS cannot establish: two commits that both
# happened after the session ended satisfy the count exactly as well.
# Which commit is which is established by the checkpoint trailers, in
# check_lifecycle_checkpoints, and this verdict now says so instead of
# claiming it.  The second used to be titled as though it had read the
# dossier's prose; what it reads is the first commit that introduced each
# path and the ancestry between them, so that is what it reports.
first_commit_for() {
    "${GIT}" log --format='%H' -- "$1" 2>/dev/null | "${TAIL}" -n 1 || true
}

check_commit_order() {
    local userdir_commits="" dossier="" frame="" capture=""
    userdir_commits="$("${GIT}" log --format='%H' -- \
        "${PLAYTHROUGH_USERDIR}" 2>/dev/null | "${GREP}" -c . || true)"
    if [ "${userdir_commits:-0}" -ge 2 ]; then
        record_pass "the save was committed at both mandated points" \
            "${userdir_commits} commit(s) touch \
$(rel "${PLAYTHROUGH_USERDIR}"), which is at least the two the \
requirement names.  This reading is a COUNT: which of them followed \
character creation and which followed the in-game Save and Quit is \
established by the checkpoint trailers, and is asserted separately by \
'each checkpoint anchors to its own survivor's creation'"
    else
        record_fail "the save was committed at both mandated points" \
            "${userdir_commits:-0} commit(s) touch \
$(rel "${PLAYTHROUGH_USERDIR}")" \
            "at least 2 -- one after character creation, one after the \
in-game Save and Quit"
    fi

    dossier="$(first_commit_for "${PLAYTHROUGH_DOSSIER}")"
    if ! capture="$(capture_path 1)"; then
        capture=""
    fi
    if [ -n "${capture}" ]; then
        frame="$(first_commit_for "${capture}")"
    fi
    if [ -z "${dossier}" ] || [ -z "${frame}" ]; then
        record_fail "the dossier's first commit precedes the first \
capture's" \
            "$(rel "${PLAYTHROUGH_DOSSIER}") was introduced by \
'${dossier:-no commit at all}' and \
$(rel "${capture:-${PLAYTHROUGH_FRAMES_DIR}}") by \
'${frame:-no commit at all}'" \
            "a commit for each -- the ordering cannot be read off a \
history that carries only one of them"
        return 0
    fi
    if [ "${dossier}" = "${frame}" ]; then
        record_fail "the dossier's first commit precedes the first \
capture's" \
            "${dossier:0:10} introduced BOTH \
$(rel "${PLAYTHROUGH_DOSSIER}") and $(rel "${capture}")" \
            "two different commits, the dossier's the earlier of them: \
the survivor is described BEFORE play rather than alongside it, so the \
dossier is committed on its own first (commit_artifacts.sh dossier) and \
the creation checkpoint follows it"
        return 0
    fi
    if "${GIT}" merge-base --is-ancestor "${dossier}" "${frame}" \
            2>/dev/null; then
        record_pass "the dossier's first commit precedes the first \
capture's" \
            "$(rel "${PLAYTHROUGH_DOSSIER}") was introduced by \
${dossier:0:10}, $(rel "${capture}") by ${frame:0:10}, and \
${dossier:0:10} is a strict ancestor of ${frame:0:10} -- measured as \
reachability in the commit graph rather than from either commit's date, \
which can say anything"
        return 0
    fi
    record_fail "the dossier's first commit precedes the first \
capture's" \
        "${dossier:0:10} introduced $(rel "${PLAYTHROUGH_DOSSIER}") and \
${frame:0:10} introduced $(rel "${capture}"), and ${dossier:0:10} is \
NOT an ancestor of ${frame:0:10}" \
        "the dossier's introducing commit reachable from the first \
capture's -- on separate branches neither precedes the other, and the \
requirement is an order rather than a coexistence"
}

# WHICH IDENTITY WILL SIGN THESE ARTIFACTS, AND WHETHER THE HISTORY
# AGREES WITH IT.
#
# THIS CHECK ASKED AN IMPOSSIBLE QUESTION AND SO COULD NEVER PASS.  It
# required a REPOSITORY-LOCAL pair, read with `git config --local --get`,
# on the authority of the plan's section 0.3.1 ("set the repository-local
# git identity") and section 0.10.2 ("the git identity is set
# repository-locally", under least privilege).  The reasoning was sound
# as far as it went: an identity held in the account is one a container,
# a different account or a fresh checkout of this branch does not have.
#
# But the environment this record is produced in FORBIDS CREATING ONE.
# It fixes the committer identity itself and prohibits running
# `git config user.name` or `user.email` at any scope, so the only way to
# satisfy the check would have been to violate that prohibition.
# Measured here: `git config --local --get user.name` exits 1, while
# `git var GIT_AUTHOR_IDENT` resolves `Blitzy Agent
# <agent@blitzy.com>` -- and every commit touching playthrough/ is
# authored by exactly that.  So the gate reported a FAILURE about the one
# property it was not allowed to fix, and a review separately found the
# acceptance report and REPORT.md claiming a repository-local identity
# that was never there: the check's impossibility and the documents'
# false claim are the same defect seen from two sides.
#
# So this now measures the strongest property that is BOTH required and
# achievable, and it measures it authoritatively:
#
#   * an identity RESOLVES for committing at all, read through `git var
#     GIT_AUTHOR_IDENT`, which is what git will actually stamp -- the
#     environment, then this repository, then the account, then the
#     system.  Without one, no checkpoint can be taken and the save
#     data, captures and film cannot become the committed evidence R1
#     and R3 require, so this half is a genuine failure.
#   * it AGREES with the author of the newest commit that touched
#     playthrough/.  This was always the load-bearing half: a
#     configuration that disagrees with the history describes a
#     different machine.  Before the first such commit there is nothing
#     to compare with, and that is stated rather than silently skipped.
#
# WHERE the pair came from is reported either way, and when it is not
# repository-local the verdict SAYS SO and names the divergence rather
# than hiding it -- an honest "this differs from the plan, here is why"
# is the point of the exercise, and it is recorded in
# playthrough/TECHNICAL_NOTES.md as well.

# The host directive that displaces the plan's repository-local
# requirement, QUOTED WORD FOR WORD so a reader can weigh the two
# instructions against each other without taking this file's paraphrase
# of either.  A review asked for exactly this: a divergence that
# summarises the rule it obeyed instead of citing it is asking to be
# believed.  The backticks the directive is written with are ESCAPED
# rather than single-quoted: a single-quoted string cannot be continued
# across lines -- the backslash and the newline would both survive into
# the value -- so the quotation is assembled in double quotes, where a
# `\`` is a backtick and not a command substitution.
readonly IDENTITY_DIRECTIVE="All git commits must be authored and \
committed as \`Blitzy Agent <agent@blitzy.com>\`. Never run \
\`git config user.name\`/\`user.email\`, and never override the \
author/committer identity."

# record_identity_divergence OBSERVED
#   The one divergence this check can record, written once.  It was
#   written twice -- once for the no-commits-yet branch and once for the
#   agreeing branch -- and two copies of a citation is two places for it
#   to drift from the directive it quotes.
record_identity_divergence() {
    record_divergence "git has an identity to commit these artifacts \
under, and the history agrees with it" "$1" \
        "a repository-local pair -- 'git config --local user.name' and \
'user.email' set in this checkout's own .git/config, per the plan's \
sections 0.3.1 and 0.10.2" \
        "the execution environment this record was produced in FIXES \
the committer identity itself and PROHIBITS creating that pair.  Its \
directive, verbatim: \"${IDENTITY_DIRECTIVE}\"  Setting a \
repository-local pair means running one of the two commands that \
sentence forbids, so satisfying the plan here would have been a \
violation rather than a compliance -- and the two instructions cannot \
both be obeyed, which is a requirement-level conflict for a human to \
settle rather than something a run of this gate can close.  The \
property the plan wanted the pair FOR does hold and is measured above: \
an identity resolves, and it is the one the history was committed \
under.  What does not hold is where it is configured.  This is reported \
as a divergence rather than a pass because a report that reads as \
compliance is the defect; it is recorded in \
playthrough/TECHNICAL_NOTES.md as well"
}

check_git_identity() {
    local ident="" configured="" committed=""
    local local_name="" local_email="" scope="" caveat=""
    local observed_new="" observed_ok=""
    local_name="$("${GIT}" config --local --get user.name \
        2>/dev/null || true)"
    local_email="$("${GIT}" config --local --get user.email \
        2>/dev/null || true)"
    # THE AUTHORITATIVE ANSWER, not one scope of it.  `git var
    # GIT_AUTHOR_IDENT` is what git will actually stamp on a commit: it
    # resolves the GIT_AUTHOR_* environment, then this repository, then
    # the account, then the system, and fails outright when none of them
    # yields a usable pair.  Reading one scope with `git config --local`
    # answers a different question, and the wrong one for "can these
    # artifacts be committed, and by whom".
    ident="$("${GIT}" var GIT_AUTHOR_IDENT 2>/dev/null || true)"
    if [ -n "${ident}" ]; then
        # "Name <email> <unixtime> <tz>" -- drop the time and the zone
        # by cutting at the last "> ", then put the bracket back.
        configured="${ident%> *}>"
    fi
    local repository_local="no"
    if [ -n "${local_name}" ] && [ -n "${local_email}" ]; then
        scope="this checkout's own .git/config"
        repository_local="yes"
    elif [ -n "${configured}" ]; then
        scope="a broader scope than this checkout"
        caveat=".  It is NOT repository-local: 'git config --local \
--get user.name' answers nothing here"
    fi
    if [ -z "${configured}" ]; then
        record_fail "git has an identity to commit these artifacts \
under, and the history agrees with it" \
            "no identity resolves at any scope: 'git var \
GIT_AUTHOR_IDENT' answered nothing" \
            "a name and an email git can stamp on a commit.  Without \
one no checkpoint can be taken at all, so the save data, the captures \
and the film cannot become the committed evidence R1 and R3 require"
        return 0
    fi
    committed="$("${GIT}" log --max-count=1 --format='%an <%ae>' \
        HEAD -- "${PLAYTHROUGH_DIR}" 2>/dev/null || true)"
    if [ -z "${committed}" ]; then
        observed_new="${configured}, resolved from ${scope}; no \
commit has touched $(rel "${PLAYTHROUGH_DIR}") yet, so there is no \
committed identity to compare it against${caveat}"
        if [ "${repository_local}" = "yes" ]; then
            record_pass "git has an identity to commit these artifacts \
under, and the history agrees with it" "${observed_new}"
        else
            record_identity_divergence "${observed_new}"
        fi
        return 0
    fi
    # BEING RESOLVABLE IS NOT THE WHOLE REQUIREMENT.  An identity that
    # disagrees with the one the evidence was actually committed under
    # describes a machine rather than this history, so the resolved pair
    # is compared against the author of the newest commit that touched
    # playthrough/.  This is the half of the old check that was always
    # the load-bearing one, and it is kept exactly.
    if [ "${configured}" = "${committed}" ]; then
        observed_ok="${configured}, resolved from ${scope}, and \
the newest commit touching $(rel "${PLAYTHROUGH_DIR}") is authored by \
the same identity${caveat}"
        if [ "${repository_local}" = "yes" ]; then
            record_pass "git has an identity to commit these artifacts \
under, and the history agrees with it" "${observed_ok}"
        else
            record_identity_divergence "${observed_ok}"
        fi
        return 0
    fi
    record_fail "git has an identity to commit these artifacts under, \
and the history agrees with it" \
        "git would author as ${configured} while the newest commit \
touching $(rel "${PLAYTHROUGH_DIR}") is authored by ${committed}" \
        "the same identity in both -- the evidence and the resolved \
configuration have to agree about who committed it, or the \
configuration is describing a different machine than the history does"
}

# ---------------------------------------------------------------------
# THE COMMITTED IGNORE RULES.
#
# committed_file PATH -- the contents of one path as HEAD carries it, or
# nothing when HEAD does not carry it at all.
committed_file() {
    "${GIT}" show "HEAD:$1" 2>/dev/null || true
}

# last_effective_rule -- the last line of a .gitignore that git would
# actually apply: blank lines and comments are neither patterns nor
# matches, so they cannot be the deciding rule and are stripped.
last_effective_rule() {
    "${GREP}" -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' |
        "${TAIL}" -n 1 || true
}

check_committed_ignore_negation() {
    local content="" last=""
    content="$(committed_file ".gitignore")"
    if [ -z "${content}" ]; then
        record_fail "the committed .gitignore still rescues the save \
data" \
            "HEAD carries no .gitignore at all" \
            "a committed .gitignore ending in '${IGNORE_NEGATION}'"
        return 0
    fi
    last="$(printf '%s\n' "${content}" | last_effective_rule)"
    if [ "${last}" = "${IGNORE_NEGATION}" ]; then
        record_pass "the committed .gitignore still rescues the save \
data" \
            "its last effective rule is '${last}', so a fresh clone of \
this history re-includes the engine's own '#<name>.sav' and '*.log' \
files instead of ignoring them"
        return 0
    fi
    record_fail "the committed .gitignore still rescues the save data" \
        "the last effective rule in HEAD's .gitignore is '${last}'" \
        "'${IGNORE_NEGATION}' -- git applies the LAST matching \
pattern, so anything after the negation re-excludes what it rescued, \
and a history without it re-ignores the save data on every fresh clone \
while every working-tree check still passes"
}

check_committed_attributes() {
    local content="" row=""
    local -a missing=()
    content="$(committed_file ".gitattributes")"
    if [ -z "${content}" ]; then
        record_fail "the committed .gitattributes carries this \
feature's rows" \
            "HEAD carries no .gitattributes at all" \
            "${#REQUIRED_ATTRIBUTES[@]} rows: \
${REQUIRED_ATTRIBUTES[*]}"
        return 0
    fi
    for row in "${REQUIRED_ATTRIBUTES[@]}"; do
        # THE WHOLE LINE, LITERALLY.  A substring match would accept
        # '*.mp4 binary' inside a comment about it, and a pattern match
        # would read the '*' as a glob.  The awk pass trims the ends and
        # collapses runs of whitespace, so a row written with a tab or
        # an extra space is recognised as the row it is.
        if ! printf '%s\n' "${content}" |
                "${AWK}" '{ gsub(/^[ \t]+|[ \t]+$/, "");
                            gsub(/[ \t]+/, " "); print }' |
                "${GREP}" -Fqx -- "${row}"; then
            missing+=("${row}")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        record_pass "the committed .gitattributes carries this \
feature's rows" \
            "${#REQUIRED_ATTRIBUTES[@]} rows present: \
${REQUIRED_ATTRIBUTES[*]}"
        return 0
    fi
    record_fail "the committed .gitattributes carries this feature's \
rows" \
        "${#missing[@]} missing: ${missing[*]}" \
        "all ${#REQUIRED_ATTRIBUTES[@]} -- the file's own rationale is \
to normalise explicitly rather than rely on detection, and without \
these rows the film, the save and the map archives are left to '* \
text=auto'"
}

check_committed_vcs_rules() {
    check_committed_ignore_negation
    check_committed_attributes
}

# ---------------------------------------------------------------------
# THE LIFECYCLE CHECKPOINTS, AND THE ONE INCONSISTENCY A ROW COUNT
# CANNOT SEE
#
# commit_artifacts.sh marks two commits with a trailer: the `creation`
# checkpoint, taken when the survivor exists and no frame does, and the
# `final` one, taken after the session is saved and closed.  The
# committer anchors `final` to the newest `creation` in the history.
#
# Anchoring by trailer alone is not enough, and the gap is not
# theoretical: a `final` checkpoint whose anchor records a DIFFERENT
# survivor was accepted, because the only lifecycle assertion was that
# the record had grown -- and a record re-recorded from scratch for a
# new survivor has "grown" by that measure too.  The result is a history
# whose two lifecycle commits describe somebody whose files are no
# longer in the tree.
#
# INTERNAL CONSISTENCY IS NECESSARY AND IS NOT SUFFICIENT, and a review
# found exactly that gap here.  For every `final` checkpoint, the
# survivor its own tree names must be the survivor its anchoring
# `creation` names -- true of an honest lifecycle, false in the
# cross-survivor case, and a property of the graph rather than of a
# count.  But it says nothing about WHICH recording the pair is about.  A
# history holding one internally consistent pair for a survivor who has
# since been superseded satisfied it completely, and the divergence
# between that pair and the evidence actually in the tree was reported as
# a WARNING -- which does not affect the exit status.  So the gate passed
# on a tree whose committed frames, manifest, film and save belonged to
# somebody with no checkpoint pair at all, and R1's "committed at both
# mandated points" was reported as satisfied by two commits about
# somebody else's session.
#
# So there are TWO checks here, and both of them FAIL rather than warn:
#
#   1. EVERY `final` is internally consistent with its anchor -- the same
#      survivor, and the anchor a strict ancestor of it.  Ancestry is
#      asserted explicitly rather than inferred from `git log`'s
#      reachability, and `anchor != final` with it, because a creation
#      checkpoint that IS its own final is not a lifecycle: the two
#      commits exist to bracket a session, and one commit brackets
#      nothing.
#
#   2. THE NEWEST PAIR IS ABOUT THE SURVIVOR IN THE TREE.  HEAD's own
#      lastworld.json names the world and character whose evidence is
#      committed; the newest `final` and the newest `creation` must both
#      name that same world and character.  This is the check that makes
#      "the save was committed at both mandated points" a statement about
#      THIS session, and it is the one a superseded pair now fails.
# ---------------------------------------------------------------------

# checkpoint_commits NAME -- every commit carrying the trailer, newest
# first.  The anchors are the same '^KEY: name$' form the committer
# writes, so the two cannot disagree about what a checkpoint is.
checkpoint_commits() {
    "${GIT}" log --format='%H' \
        --grep="^${CHECKPOINT_TRAILER_KEY}: $1\$" HEAD -- \
        2>/dev/null || true
}

# checkpoint_anchor COMMIT -- the newest `creation` checkpoint reachable
# from COMMIT, which is the one the committer would have anchored to.
checkpoint_anchor() {
    "${GIT}" log --max-count=1 --format='%H' \
        --grep="^${CHECKPOINT_TRAILER_KEY}: \
${CHECKPOINT_CREATION_NAME}\$" "$1" -- 2>/dev/null || true
}

# survivor_at COMMIT -- "<world> / <character>" as that commit's tree
# records it, or nothing when the tree carries no readable record.
survivor_at() {
    local content=""
    content="$("${GIT}" show \
        "$1:playthrough/userdir/config/lastworld.json" 2>/dev/null ||
        true)"
    if [ -z "${content}" ]; then
        return 1
    fi
    printf '%s\n' "${content}" |
        bounded "${BOUND_PROBE_SECONDS}" \
            "${PYTHON}" -B -c "${LASTWORLD_STDIN_READER}" 2>/dev/null ||
        return 1
}

# The facts BOTH checkpoint checks are about, read once.  They are state
# rather than arguments because each check is called directly from
# group_version_control under the phase predicate: a check that another
# check calls is a check whose gating is invisible at the call site, and
# this file's rule is that the classification stays visible beside the
# group it belongs to.
LIFECYCLE_HEAD_SURVIVOR=""
LIFECYCLE_NEWEST_FINAL=""
LIFECYCLE_NEWEST_CREATION=""

check_lifecycle_checkpoints() {
    local -a finals=() creations=() mismatched=()
    local commit="" anchor="" mine="" theirs="" head_survivor=""
    mapfile -t finals < <(checkpoint_commits \
        "${CHECKPOINT_FINAL_NAME}")
    mapfile -t creations < <(checkpoint_commits \
        "${CHECKPOINT_CREATION_NAME}")
    if ! head_survivor="$(survivor_at HEAD)"; then
        head_survivor=""
    fi
    LIFECYCLE_HEAD_SURVIVOR="${head_survivor}"
    LIFECYCLE_NEWEST_FINAL="${finals[0]-}"
    LIFECYCLE_NEWEST_CREATION="${creations[0]-}"

    if [ "${#creations[@]}" -eq 0 ] || [ "${#finals[@]}" -eq 0 ]; then
        record_fail "each checkpoint anchors to its own survivor's \
creation" \
            "${#creations[@]} '${CHECKPOINT_CREATION_NAME}' and \
${#finals[@]} '${CHECKPOINT_FINAL_NAME}' checkpoint(s) carry the \
'${CHECKPOINT_TRAILER_KEY}' trailer" \
            "at least one of each -- the lifecycle is two commits, one \
taken when the survivor exists and no frame does, one after the \
session was saved and closed"
        return 0
    fi

    for commit in "${finals[@]}"; do
        [ -n "${commit}" ] || continue
        anchor="$(checkpoint_anchor "${commit}")"
        if [ -z "${anchor}" ]; then
            mismatched+=("${commit:0:10} has no \
'${CHECKPOINT_CREATION_NAME}' checkpoint among its ancestors")
            continue
        fi
        # A LIFECYCLE IS TWO COMMITS, AND THE FIRST STRICTLY PRECEDES THE
        # SECOND.  `git log --grep <commit>` already walks only ancestors,
        # so reachability is implied -- but implied is not asserted, and
        # the one case reachability does NOT exclude is the anchor being
        # the final itself, which would mean a session bracketed by a
        # single commit taken before it started.
        if [ "${anchor}" = "${commit}" ]; then
            mismatched+=("${commit:0:10} is its own \
'${CHECKPOINT_CREATION_NAME}' anchor, so one commit stands for both \
ends of the session")
            continue
        fi
        if ! "${GIT}" merge-base --is-ancestor "${anchor}" "${commit}" \
                2>/dev/null; then
            mismatched+=("${anchor:0:10} is not an ancestor of \
${commit:0:10}, so the creation it claims to anchor to is not in its \
history")
            continue
        fi
        if ! mine="$(survivor_at "${commit}")"; then
            mismatched+=("${commit:0:10} names no survivor its own \
tree can be read for")
            continue
        fi
        if ! theirs="$(survivor_at "${anchor}")"; then
            mismatched+=("${anchor:0:10}, the anchor of \
${commit:0:10}, names no survivor its own tree can be read for")
            continue
        fi
        record_info "the '${CHECKPOINT_FINAL_NAME}' checkpoint \
${commit:0:10}" \
            "records ${mine}, anchored to \
'${CHECKPOINT_CREATION_NAME}' ${anchor:0:10} which records ${theirs}"
        if [ "${mine}" != "${theirs}" ]; then
            mismatched+=("${commit:0:10} records '${mine}' while its \
anchor ${anchor:0:10} records '${theirs}'")
        fi
    done

    if [ "${#mismatched[@]}" -eq 0 ]; then
        record_pass "each checkpoint anchors to its own survivor's \
creation" \
            "${#finals[@]} '${CHECKPOINT_FINAL_NAME}' checkpoint(s), \
each anchored to a '${CHECKPOINT_CREATION_NAME}' checkpoint recording \
the same world and survivor"
    else
        record_fail "each checkpoint anchors to its own survivor's \
creation" \
            "${#mismatched[@]}: ${mismatched[*]}" \
            "every '${CHECKPOINT_FINAL_NAME}' checkpoint anchored to \
the creation of the survivor it is about -- a record re-recorded from \
scratch has 'grown' by row count too, so the row count cannot tell the \
two apart"
    fi

}

# check_checkpoints_are_this_session
#   The check that binds the history to the tree.  A divergence here used
#   to be a WARNING, which does not affect the exit status -- so a gate
#   reporting "the save was committed at both mandated points" could be
#   describing a session whose files are no longer in the checkout.  R1
#   asks for the save of THIS survivor to be committed after creation and
#   again after Save & Quit; a pair about somebody else does not satisfy
#   it, however self-consistent it is, and the answer to that is a
#   failure.
check_checkpoints_are_this_session() {
    local head_survivor="${LIFECYCLE_HEAD_SURVIVOR}"
    local newest_final="${LIFECYCLE_NEWEST_FINAL}"
    local newest_creation="${LIFECYCLE_NEWEST_CREATION}"
    local name="the lifecycle checkpoints are about the survivor in the \
tree"
    local final_survivor="" creation_survivor=""
    local -a wrong=()

    # NO PAIR IS ITS OWN ANSWER, and it is answered here rather than by
    # the sibling check reporting on this one's behalf.  Each check
    # answers for itself, so each can be called from the group under the
    # phase predicate and neither depends on the other having run.
    if [ -z "${newest_final}" ] || [ -z "${newest_creation}" ]; then
        record_fail "${name}" \
            "there is no checkpoint pair to be about anybody -- the \
newest '${CHECKPOINT_CREATION_NAME}' is \
'${newest_creation:-<none>}' and the newest \
'${CHECKPOINT_FINAL_NAME}' is '${newest_final:-<none>}'" \
            "one '${CHECKPOINT_CREATION_NAME}' and one \
'${CHECKPOINT_FINAL_NAME}' checkpoint, both recording the survivor HEAD \
carries"
        return 0
    fi

    # AN UNREADABLE HEAD IS A FAILURE, not a reason to skip.  Without
    # knowing which survivor the tree is about, the whole property is
    # unmeasurable -- and an unmeasurable property reported as a pass is
    # the vacuous verdict this gate exists to prevent.
    if [ -z "${head_survivor}" ]; then
        record_fail "${name}" \
            "HEAD carries no readable \
playthrough/userdir/config/lastworld.json, so which survivor the \
committed evidence is about cannot be established" \
            "a committed lastworld.json naming the world and character \
-- the engine writes it on load and on quit, and it is what binds the \
frames, the film and the save to one session"
        return 0
    fi
    record_info "the survivor whose evidence HEAD carries" \
        "${head_survivor}"

    if ! final_survivor="$(survivor_at "${newest_final}")"; then
        wrong+=("the newest '${CHECKPOINT_FINAL_NAME}' checkpoint \
${newest_final:0:10} names no survivor its own tree can be read for")
    elif [ "${final_survivor}" != "${head_survivor}" ]; then
        wrong+=("the newest '${CHECKPOINT_FINAL_NAME}' checkpoint \
${newest_final:0:10} records '${final_survivor}'")
    fi
    if ! creation_survivor="$(survivor_at "${newest_creation}")"; then
        wrong+=("the newest '${CHECKPOINT_CREATION_NAME}' checkpoint \
${newest_creation:0:10} names no survivor its own tree can be read for")
    elif [ "${creation_survivor}" != "${head_survivor}" ]; then
        wrong+=("the newest '${CHECKPOINT_CREATION_NAME}' checkpoint \
${newest_creation:0:10} records '${creation_survivor}'")
    fi
    # THE PAIR MUST BE A PAIR.  Both being about the right survivor is
    # still not a lifecycle unless the creation precedes the final, so the
    # same ancestry the loop above asserts per final is asserted for the
    # two commits this session is actually judged on.
    if [ "${#wrong[@]}" -eq 0 ]; then
        if [ "${newest_creation}" = "${newest_final}" ]; then
            wrong+=("${newest_final:0:10} carries both trailers, so one \
commit stands for both ends of the session")
        elif ! "${GIT}" merge-base --is-ancestor "${newest_creation}" \
                "${newest_final}" 2>/dev/null; then
            wrong+=("${newest_creation:0:10} is not an ancestor of \
${newest_final:0:10}, so the two are not the two ends of one session")
        fi
    fi

    if [ "${#wrong[@]}" -eq 0 ]; then
        record_pass "${name}" \
            "both newest checkpoints record ${head_survivor}, the \
survivor HEAD carries: '${CHECKPOINT_CREATION_NAME}' \
${newest_creation:0:10} then '${CHECKPOINT_FINAL_NAME}' \
${newest_final:0:10}"
        return 0
    fi
    record_fail "${name}" \
        "HEAD carries ${head_survivor}, but ${wrong[*]}" \
        "the newest '${CHECKPOINT_CREATION_NAME}' and \
'${CHECKPOINT_FINAL_NAME}' checkpoints both recording \
${head_survivor}, creation first -- a self-consistent pair about a \
SUPERSEDED recording leaves the evidence in the tree with no checkpoint \
of its own, and R1 asks for THIS survivor's save to be committed after \
creation and again after Save & Quit"
}

# The second half of the lifecycle, and the one a superseded pair used to
# satisfy: the recording IN THE TREE must have been checkpointed itself.
#
# Both halves are required and neither implies the other.  A history can
# carry a self-consistent pair for a retired survivor (which is what
# HEAD's history carries today) and a history could carry a `final`
# checkpoint for the current survivor anchored to somebody else's
# `creation`.  The first is caught here, the second above.
check_head_generation_checkpoints() {
    local -a finals=()
    local commit="" anchor="" mine="" theirs=""
    local head_survivor="" matched="" anchored="" other=""
    if ! head_survivor="$(survivor_at HEAD)"; then
        record_fail "the recording in the tree has a checkpoint pair \
of its own" \
            "HEAD carries no readable \
playthrough/userdir/config/lastworld.json, so the survivor whose \
evidence is in the tree cannot be named at all" \
            "the engine's own record of the world and character the \
committed save belongs to, so that the checkpoints can be matched \
against it"
        return 0
    fi
    mapfile -t finals < <(checkpoint_commits \
        "${CHECKPOINT_FINAL_NAME}")
    for commit in "${finals[@]}"; do
        [ -n "${commit}" ] || continue
        if ! mine="$(survivor_at "${commit}")"; then
            continue
        fi
        if [ "${mine}" != "${head_survivor}" ]; then
            other="${other}${other:+, }${commit:0:10} (${mine})"
            continue
        fi
        matched="${commit}"
        anchor="$(checkpoint_anchor "${commit}")"
        [ -n "${anchor}" ] || continue
        if ! theirs="$(survivor_at "${anchor}")"; then
            continue
        fi
        if [ "${theirs}" = "${head_survivor}" ]; then
            anchored="${anchor}"
            break
        fi
    done

    if [ -n "${matched}" ] && [ -n "${anchored}" ]; then
        record_pass "the recording in the tree has a checkpoint pair \
of its own" \
            "${head_survivor}: '${CHECKPOINT_FINAL_NAME}' \
${matched:0:10} anchored to '${CHECKPOINT_CREATION_NAME}' \
${anchored:0:10}, both recording that survivor"
        return 0
    fi
    if [ -n "${matched}" ]; then
        record_fail "the recording in the tree has a checkpoint pair \
of its own" \
            "HEAD carries ${head_survivor} and \
'${CHECKPOINT_FINAL_NAME}' ${matched:0:10} records that survivor, but \
no '${CHECKPOINT_CREATION_NAME}' checkpoint among its ancestors records \
that survivor" \
            "a '${CHECKPOINT_CREATION_NAME}' checkpoint for the same \
survivor before the '${CHECKPOINT_FINAL_NAME}' one -- without it the \
save was published once and 'committed after creation and again after \
the session closed' is not what the history says"
        return 0
    fi
    local observed=""
    observed="HEAD carries ${head_survivor} and no \
'${CHECKPOINT_FINAL_NAME}' checkpoint records that survivor"
    if [ -n "${other}" ]; then
        observed="${observed}; the '${CHECKPOINT_FINAL_NAME}' \
checkpoint(s) in this history are ${other}"
    fi
    record_fail "the recording in the tree has a checkpoint pair of \
its own" \
        "${observed}" \
        "a '${CHECKPOINT_CREATION_NAME}' and a \
'${CHECKPOINT_FINAL_NAME}' checkpoint for the survivor whose evidence \
is in the tree.  A pair belonging to a superseded recording is not \
evidence about this one: re-record the session through \
commit_artifacts.sh's ${CHECKPOINT_CREATION_NAME}-then-\
${CHECKPOINT_FINAL_NAME} sequence, or publish the retirement of this \
evidence, because a bundled single commit cannot prove the order the \
requirement is about"
}

# check_evidence_anchor_trailer -- the chain head, in the history.
#
# THE HALF OF THE ANCHOR THAT MAKES IT INDEPENDENT.  Group 2 proves the
# chain is internally sound and that every sealed artifact still matches
# its seal.  Both of those read files that sit in the same tree as the
# evidence, so an attacker who rewrites an artifact and then rewrites the
# ledger to match satisfies them -- the chain would be recomputed from
# the forged rows and agree with itself.
#
# What that attacker cannot recompute is a COMMIT.  A commit object's
# name is a hash of its own content, including its message, so the head
# published in this trailer is fixed the moment the checkpoint is taken:
# changing it changes the commit id and every id after it, which is a
# rewrite of published history rather than an edit of a file.  So the
# comparison here -- the head the ledger ends on against the head the
# newest checkpoint commit declared -- is the one that cannot be
# satisfied by editing the working tree.
#
# A COMMIT WITH NO TRAILER IS A FAILURE, not an exemption.  The trailer
# is written by commit_artifacts.sh at every checkpoint; a checkpoint
# without one is either an older commit from before the anchor existed --
# in which case the current head has never been published and the anchor
# proves nothing about this history -- or a checkpoint taken by something
# other than the committer.  Both are worth reporting rather than
# passing.
#
# AND IT IS ASKED OF EACH CHECKPOINT, NOT OF THE HISTORY AS A WHOLE.  A
# review found this check taking the NEWEST commit carrying a trailer
# anywhere in the history and comparing that one against the ledger --
# which passes on a history where the trailer arrived long after the
# lifecycle checkpoints it is supposed to bind.  That is exactly this
# history: the delivered `creation`, `final` and `media` commits carry no
# trailer, because the anchor mechanism was built after them, and every
# anchor row is a retrospective seal.  A retrospective seal is a true
# statement about the bytes and NOT a contemporaneous witness to when
# they were made, so the two are now told apart:
#
#   FAIL        no commit publishes the head, or the head it publishes is
#               not the one the ledger ends on;
#   DIVERGENCE  the head is published, but one or more REQUIRED
#               lifecycle checkpoints carry no trailer of their own --
#               each is NAMED, with the honest reason it cannot be
#               repaired: history is not rewritten here (no rewriting,
#               no force-push), so a checkpoint taken before the
#               mechanism existed can never acquire a contemporaneous
#               one;
#   PASS        the head is published and every required checkpoint
#               carries its own trailer.
#
# WHAT WOULD CLOSE THE DIVERGENCE, stated so nobody mistakes the seal for
# more than it is: a re-recording taken through the hardened committer,
# whose creation/final/media commits each carry their own trailer, and the
# head published in an EXTERNAL immutable attestation -- a transparency
# log or a signature held outside this repository.  Neither is available
# to an offline pipeline that must not rewrite published history, so the
# gap is reported at every run rather than smoothed over.

# commit_anchor_trailer COMMIT -- the anchor head COMMIT declares, if any.
commit_anchor_trailer() {
    "${GIT}" log --max-count=1 --format='%B' "$1" 2>/dev/null |
        "${SED}" -n "s/^${ANCHOR_TRAILER_KEY}: //p" |
        "${HEAD}" -n 1 || true
}

# unanchored_checkpoints -- every required lifecycle checkpoint reachable
# from HEAD that publishes no anchor head of its own, as
# "<short> (<milestone>)" entries.  The names are bounded like every other
# population this gate reports.
unanchored_checkpoints() {
    local milestone commit
    for milestone in "${CHECKPOINT_CREATION_NAME}" \
        "${CHECKPOINT_FINAL_NAME}" "${CHECKPOINT_MEDIA_NAME}"; do
        while IFS= read -r commit; do
            [ -n "${commit}" ] || continue
            if [ -z "$(commit_anchor_trailer "${commit}")" ]; then
                printf '%s (%s)\n' "${commit:0:10}" "${milestone}"
            fi
        done < <(checkpoint_commits "${milestone}")
    done
}

check_evidence_anchor_trailer() {
    local name="the evidence anchor's head is published in the history"
    local commit="" declared="" head="" subject="" line=""
    local -a unanchored=()
    head="$(bounded "${BOUND_PROBE_SECONDS}" "${PYTHON}" -B -c '
import sys

sys.path.insert(0, sys.argv[1])
import manifest

print(manifest.anchor_head(manifest.read_anchor_rows(
    sys.argv[2] or None)))
' "${PLAYTHROUGH_TOOLING_DIR}" \
        "$(rel "${PLAYTHROUGH_EVIDENCE_ANCHOR}")" \
        2>"$(tool_error_file anchor)" | "${HEAD}" -n 1 || true)"
    if [ -z "${head}" ]; then
        record_fail "${name}" \
            "the evidence anchor has no chain head to compare\
$(because anchor)" \
            "a sealed evidence tree -- commit_artifacts.sh seals the \
artifacts and publishes the head at each checkpoint"
        return 0
    fi
    commit="$("${GIT}" log --max-count=1 --format='%H' \
        --grep="^${ANCHOR_TRAILER_KEY}: " HEAD -- 2>/dev/null || true)"
    if [ -z "${commit}" ]; then
        record_fail "${name}" \
            "the anchor ends on ${head:0:16} and no commit reachable \
from HEAD carries a '${ANCHOR_TRAILER_KEY}:' trailer" \
            "the newest checkpoint publishing the head, so that \
rewriting an artifact would also require rewriting history.  A ledger \
whose head appears nowhere in the history is one more mutable file \
beside the evidence"
        return 0
    fi
    declared="$(commit_anchor_trailer "${commit}")"
    subject="$("${GIT}" log --max-count=1 --format='%h %s' "${commit}" \
        2>/dev/null || true)"
    if [ "${declared}" != "${head}" ]; then
        record_fail "${name}" \
            "the anchor ends on ${head:0:16} and the newest commit \
carrying the trailer (${subject}) declares ${declared:0:16}" \
            "the same value.  A newer head than the history publishes \
means the evidence was sealed again WITHOUT a checkpoint -- take one so \
the head is fixed in a commit object -- and a head the history does not \
recognise at all means the ledger was rewritten after it was published"
        return 0
    fi
    # THE HEAD IS PUBLISHED.  Now ask each REQUIRED checkpoint whether it
    # publishes one of its own, because "somewhere in the history" is a
    # weaker claim than the one this gate's name makes.
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        unanchored+=("${line}")
    done < <(unanchored_checkpoints)
    if [ "${#unanchored[@]}" -eq 0 ]; then
        record_pass "${name}" \
            "commit ${subject} declares ${ANCHOR_TRAILER_KEY}: \
${declared:0:16}, which is the head the anchor ends on, and every \
'${CHECKPOINT_CREATION_NAME}', '${CHECKPOINT_FINAL_NAME}' and \
'${CHECKPOINT_MEDIA_NAME}' checkpoint publishes a head of its own"
        return 0
    fi
    record_divergence "${name}" \
        "commit ${subject} declares ${ANCHOR_TRAILER_KEY}: \
${declared:0:16}, which is the head the anchor ends on, but \
${#unanchored[@]} required checkpoint(s) publish no head of their own: \
${unanchored[*]}" \
        "a trailer on EACH required checkpoint, so that the seal is \
contemporaneous with the commit it seals rather than a later statement \
about it, and the head additionally retained OUTSIDE this repository \
(a transparency log or a detached signature) so that rewriting the \
history could not also rewrite its own witness" \
        "those checkpoints were taken BEFORE the anchor mechanism \
existed, and this pipeline does not rewrite published history -- no \
rewriting and no force-push (AAP 0.10.2, least privilege over the \
repository) -- so a commit object that already exists can never acquire \
a contemporaneous trailer.  The seal that IS present is a true statement \
about the artifact bytes and NOT a witness to when they were made; \
closing the gap needs a re-recording taken through the hardened \
committer, and the external retention needs a network service this \
offline pipeline does not have"
}

group_version_control() {
    group 7 "version control -- the save is really committed"
    check_git_worktree
    check_git_config_credential_mode
    check_git_identity
    check_nothing_ignored
    check_no_bytecode
    check_no_foreign_write
    if tracking_phase; then
        check_save_tracked
        check_every_class_tracked
        check_tracked_frame_count
        check_nothing_uncommitted
        check_commit_order
        check_committed_vcs_rules
        check_lifecycle_checkpoints
        check_checkpoints_are_this_session
        check_head_generation_checkpoints
        check_evidence_anchor_trailer
    else
        # The number is DERIVED from the declared table rather than
        # spelled out in prose, because a spelled-out one is a second
        # place for the truth to live and it went stale the moment a
        # twelfth deferred check was added.
        #
        # IT IS THE PHASE'S DEFERRAL, NOT THIS GROUP'S.  It was
        # GROUP_CHECKS_ALL[7] - GROUP_CHECKS_PRE_COMMIT[7], which is 13:
        # every deferred check but one lives in this group, and the
        # fourteenth is group 9's change surface.  The sentence around it
        # says "properties of the COMMIT ... deferred to the post-commit
        # phase", which is a claim about the PHASE, so a group-scoped
        # count made the report say 13 where this file's own usage text
        # and section 7 documentation both say "the fourteen" -- two
        # numbers for one quantity, which is the defect the derivation
        # was introduced to prevent, merely moved.  Summed across the
        # groups it is one number, and the enumeration below closes with
        # the change surface so that the count and the list agree.
        record_info "$((EXPECTED_CHECKS_ALL - \
EXPECTED_CHECKS_PRE_COMMIT)) properties of the COMMIT are deferred to \
the ${PHASE_POST_COMMIT} phase" \
            "the save, the artifact classes and the captures being \
tracked; nothing being left uncommitted; the commit order; the \
committed ignore rules; the checkpoint anchors; whether the \
checkpoints are about the survivor in the tree; whether the evidence \
anchor's head is published in the history; and, from group 9, \
the change surface -- none of them can hold before the checkpoint \
that makes them true, and this phase runs ahead of it"
    fi
}


# ---------------------------------------------------------------------
# 8  NO CHEATING, AS A CHECKABLE PROPERTY
#
# This is where a claim of good faith stops resting on the word of
# whoever played the session and becomes a property of a committed file
# that a stranger can verify.
#
# All three of the engine's debug actions -- `debug_mode` ("Toggle debug
# mode"), `debug` ("Debug menu") and `debug_hour_timer` -- are declared in
# data/raw/keybindings.json WITHOUT a `bindings` array, at lines
# 3398-3403, 3404-3409 and 3466-3471.  Unbound by default means
# unreachable by any keystroke: to use them at all somebody would have to
# bind one, and a user binding is written to
# <userdir>/config/keybindings.json (src/path_info.cpp:400-402), which is
# a COMMITTED artifact.  So the absence of that file, or its silence about
# those three ids, is independent evidence.
#
# The engine's own log is read as well, because it is the other place a
# debug session would leave a mark, and it is committed too.
# ---------------------------------------------------------------------
check_no_debug_binding() {
    local path="${PLAYTHROUGH_KEYBINDINGS_JSON}"
    local hits=""
    if [ ! -f "${path}" ]; then
        record_pass "no keybinding exists for any debug action" \
            "$(rel "${path}") does not exist, so nothing was ever \
bound; the engine ships debug, debug_mode and debug_hour_timer with no \
bindings array, which leaves them unreachable"
        return 0
    fi
    hits="$("${GREP}" -nE "${DEBUG_ACTION_PATTERN}" "${path}" \
        2>/dev/null || true)"
    if [ -z "${hits}" ]; then
        record_pass "no keybinding exists for any debug action" \
            "$(rel "${path}") exists and names none of debug, \
debug_mode or debug_hour_timer"
        return 0
    fi
    record_fail "no keybinding exists for any debug action" \
        "$(rel "${path}"): $(printf '%s' "${hits}" | "${HEAD}" -n 4 |
            "${TR}" '\n' ';')" \
        "no mention of \"debug\", \"debug_mode\" or \
\"debug_hour_timer\" -- binding one is the only way to reach the debug \
menu, and this file is committed precisely so that can be checked"
}

check_no_debug_activation() {
    local relative="" path="" hits="" inspected=0
    local -a findings=()
    for relative in "${DEBUG_LOG_RELATIVE_PATHS[@]}"; do
        path="${PLAYTHROUGH_USERDIR}/${relative}"
        [ -f "${path}" ] || continue
        inspected=$((inspected + 1))
        hits="$("${GREP}" -inE 'debug mode|debug menu' "${path}" \
            2>/dev/null || true)"
        if [ -n "${hits}" ]; then
            findings+=("$(rel "${path}"): $(printf '%s' "${hits}" |
                "${HEAD}" -n 2 | "${TR}" '\n' ';')")
        fi
    done
    if [ "${inspected}" -eq 0 ]; then
        record_pass "the engine's own log records no debug-mode \
activation" \
            "the engine wrote no log at \
$(rel "${PLAYTHROUGH_USERDIR}")/{config/debug.log,debug.log}, so there \
is nothing in one to find"
        return 0
    fi
    if [ "${#findings[@]}" -eq 0 ]; then
        record_pass "the engine's own log records no debug-mode \
activation" \
            "${inspected} log(s) read, no mention of debug mode or the \
debug menu"
        return 0
    fi
    record_fail "the engine's own log records no debug-mode \
activation" "${findings[*]}" \
        "no such line -- no debug mode, no debug menu, no spawning, no \
stat editing, no teleport, no map reveal, not even to avoid death"
}

# THE RECORD, READ FOR WHAT IT SAYS HAPPENED.
#
# The two checks above examine what was POSSIBLE (nothing was bound) and
# what the engine LOGGED (nothing was activated).  This one reads the
# account of what was done: the immutable record, the amendment ledger
# that corrects it, the timeline computed from both, and the two
# transcripts written from the timeline.  All five are committed, so a
# stranger can repeat this check; and because the record is the direct
# evidence of which keys were pressed and why, a debug action named in it
# is the plainest possible failure of the no-cheating requirement.
check_no_cheat_vocabulary() {
    local path="" hits="" inspected=0
    local -a findings=()
    local -a scanned=()
    for path in "${PLAYTHROUGH_MANIFEST}" "${PLAYTHROUGH_AMENDMENTS}" \
            "${PLAYTHROUGH_TIMELINE}" "${PLAYTHROUGH_TRANSCRIPT_MD}" \
            "${PLAYTHROUGH_TRANSCRIPT_SRT}"; do
        [ -f "${path}" ] || continue
        inspected=$((inspected + 1))
        scanned+=("$(rel "${path}")")
        hits="$("${GREP}" -inE "${CHEAT_VOCABULARY_PATTERN}" \
            "${path}" 2>/dev/null | "${CUT}" -c 1-120 || true)"
        if [ -n "${hits}" ]; then
            findings+=("$(rel "${path}"): $(printf '%s' "${hits}" |
                "${HEAD}" -n 3 | "${TR}" '\n' ';')")
        fi
    done
    if [ "${inspected}" -eq 0 ]; then
        record_fail "the record itself names no debug or cheat action" \
            "none of the record, the amendment ledger, the timeline or \
the transcripts could be read" \
            "at least the record and the timeline present, so the \
account of what was pressed is actually examined"
        return 0
    fi
    if [ "${#findings[@]}" -eq 0 ]; then
        record_pass "the record itself names no debug or cheat action" \
            "${inspected} committed file(s) read -- ${scanned[*]} -- \
none of them naming a debug action, a spawn, a teleport, god mode, \
noclip, a map reveal or a stat edit"
        return 0
    fi
    record_fail "the record itself names no debug or cheat action" \
        "${findings[*]}" \
        "no match for the cheat lexicon in the committed record or the \
transcripts -- the account of what was pressed is the most direct \
evidence there is, and a debug action named in it is the requirement \
being broken rather than merely risked"
}

group_no_cheating() {
    group 8 "no cheating, as a checkable property"
    check_no_debug_binding
    check_no_debug_activation
    check_no_cheat_vocabulary
}

# ---------------------------------------------------------------------
# 9  THE BINARY, THE REQUIRED ARTWORK AND REPOSITORY HYGIENE
#
# The tiles-and-never-curses rule is discharged from the binary's own
# mouth: `--version` prints the build's feature list, and `+tiles` in it
# is the proof.  That rule is about the BINARY: a build linked against
# SDL2 and rendering through the SDL tiles path satisfies it whichever
# tileset is selected.
#
# WHICH ARTWORK WAS DRAWN IS A SEPARATE REQUIREMENT, AND IT IS ASSERTED
# SEPARATELY.  Installing the CDDA-Tilesets pack and configuring MSXotto+
# is required outright, and nothing else in this gate can see it -- a
# session rendered in ASCIITiles satisfies every count, every duration,
# every cue and the luminance gate identically.  So four independent
# assertions follow the binary check: the installed pack is the one the
# TRACKED anchor describes, the COMMITTED option values select it, the
# ENGINE'S OWN LOG records having loaded it, and the CAPTURES THEMSELVES
# carry colour depth that only sprite artwork can produce.  The third and
# fourth are capture-time evidence: they describe the session that was
# recorded rather than the host that is auditing it.
#
# flake8 IS SCOPED TO playthrough/ AND MUST BE.  A global exit code of
# zero is not achievable at HEAD: measured here, flake8 7.3.0 reports four
# pre-existing F824 findings under tools/ -- two at
# tools/generate_changelog.py:689, one at :550 and one at
# tools/json_tools/util.py:378 -- none of which is this feature's, and
# asserting a global zero would report a failure that belongs to somebody
# else.  `.flake8` is deliberately NOT given a `playthrough` exclude
# either: the new code satisfies the repository's existing 79-column
# contract rather than being exempted from it, and that too is asserted.
# ---------------------------------------------------------------------
check_binary_is_tiles() {
    local banner=""
    if [ ! -x "${PLAYTHROUGH_GAME_BIN}" ]; then
        record_fail "the binary that was played is the SDL tiles \
build" \
            "$(rel "${PLAYTHROUGH_GAME_BIN}") is absent or not \
executable" \
            "a built ./cataclysm-tiles reporting '+tiles'; the binary is \
git-ignored (.gitignore:75), so build it with \
playthrough/tooling/launch_game.sh, which owns the build"
        return 0
    fi
    banner="$("${PLAYTHROUGH_GAME_BIN}" --version 2>&1 |
        "${TR}" '\n' ' ' || true)"
    case "${banner}" in
        *"+tiles"*)
            record_pass "the binary that was played is the SDL tiles \
build" "${banner}"
            ;;
        *)
            record_fail "the binary that was played is the SDL tiles \
build" "${banner:-<no version banner>}" \
                "a banner containing '+tiles' -- the curses build is \
never an acceptable substitute"
            ;;
    esac
}

# THE INSTALLED PACK AND THE COMMITTED CONFIGURATION.
#
# Written in Python because both readings belong to modules that already
# exist: tileset_provenance.py owns the TRACKED anchor and reads a
# tileset.txt exactly the way launch_game.sh and the engine do, so the
# id this gate judges is the id those two resolve.  A second, local
# re-implementation of either reading is the divergence the indirection
# exists to prevent.
#
# THE BYTE-LEVEL TREE COMPARISON IS REPORTED, NOT FAILED, AND THE REASON
# IS PRECISE.  gfx/ is git-ignored (.gitignore:52), so the artwork is
# host state rather than committed evidence: a pack legitimately
# re-composed on the auditing host by tools/gfx_tools/compose.py differs
# from the anchored bytes in its generated files while being the same
# artwork from the same upstream commit.  The anchor's job is to gate the
# RECORDING -- launch_game.sh verifies the complete tree against it
# before every launch and refuses -- so failing a read-only audit on it
# would be judging the host instead of the evidence.  What IS failed here
# is identity: the pack that is installed must be the tileset the anchor
# describes, and the committed options must select it.
emit_tileset_checker() {
    emit_checker tileset <<'PY'
"""Assert the required tileset: installed, anchored and configured."""

import json
import os
import sys

SEP = "\x1f"


def verdict(kind, name, observed="", expected=""):
    fields = [kind, name, str(observed), str(expected)]
    print(SEP.join(f.replace(SEP, " ").replace("\n", " ")
                   for f in fields))


def ok(name, observed=""):
    verdict("PASS", name, observed)


def bad(name, observed, expected):
    verdict("FAIL", name, observed, expected)


def info(name, observed):
    verdict("INFO", name, observed)


def warn(name, observed):
    verdict("WARN", name, observed)


def summarise(items, limit=4):
    shown = "; ".join(str(i) for i in items[:limit])
    if len(items) > limit:
        shown += "; ... (%d more)" % (len(items) - limit)
    return shown


def option_values(path, wanted):
    """The named options out of the engine's own options.json.

    The engine writes an ARRAY of objects carrying `name` and `value`
    (src/options.cpp serialises each option that way), so the shape is
    read rather than assumed and a document of another shape is reported
    instead of silently yielding nothing.
    """
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, list):
        raise ValueError(
            "%s is a %s, not the array of option objects the engine "
            "writes" % (path, type(document).__name__))
    found = {}
    for entry in document:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name in wanted:
            found[name] = entry.get("value")
    return found


def load(provenance):
    """The tracked anchor, or a failure verdict and nothing."""
    try:
        return provenance.load_anchor(provenance.anchor_path(None))
    except Exception as err:                          # noqa: BLE001
        bad("the required tileset is installed and is the one the "
            "tracked anchor describes", str(err),
            "playthrough/tooling/tileset_provenance.json readable -- it "
            "is the tracked statement of which artwork is permitted, "
            "because gfx/ is git-ignored (.gitignore:52)")
        return None


def check_installed(provenance, anchor, directory, required, aliases):
    """The pack on disk, against the tracked anchor's identity."""
    declared = anchor.get("tileset", {})
    problems = []
    if not os.path.isdir(directory):
        bad("the required tileset is installed and is the one the "
            "tracked anchor describes",
            "%s is not a directory, so the required artwork is not "
            "installed at all" % (directory or "<no directory>"),
            "the pack the anchor describes (%s, id %r) installed -- "
            "playthrough/tooling/launch_game.sh hydrates it and refuses "
            "to launch without it"
            % (declared.get("directory"), declared.get("id")))
        return False
    name = view = None
    try:
        name = provenance.tileset_field(directory, "NAME")
        view = provenance.tileset_field(directory, "VIEW")
    except Exception as err:                          # noqa: BLE001
        problems.append("tileset.txt could not be read: %s" % err)
    if name is None:
        problems.append("%s/tileset.txt declares no NAME: line"
                        % directory)
    elif name != declared.get("id"):
        problems.append("the installed pack declares NAME: %r, the "
                        "anchor describes %r"
                        % (name, declared.get("id")))
    elif required and name != required and name not in aliases:
        problems.append("the installed pack declares NAME: %r, which is "
                        "not the required %r" % (name, required))
    if view is not None and declared.get("view") and \
            view != declared.get("view"):
        problems.append("the installed pack declares VIEW: %r, the "
                        "anchor describes %r"
                        % (view, declared.get("view")))
    if problems:
        bad("the required tileset is installed and is the one the "
            "tracked anchor describes", summarise(problems),
            "NAME: %r and VIEW: %r at %s -- the id is what the engine "
            "reads as the TILES option value (src/options.cpp:1213-1227)"
            % (declared.get("id"), declared.get("view"),
               declared.get("directory")))
        return False
    ok("the required tileset is installed and is the one the tracked "
       "anchor describes",
       "%s declares NAME: %s / VIEW: %s, which is the tileset the "
       "tracked anchor names (upstream %s at %s)"
       % (directory, name, view,
          anchor.get("upstream", {}).get("repo", "?"),
          str(anchor.get("upstream", {}).get("commit", "?"))[:12]))
    return True


def report_anchor_bytes(provenance, anchor, directory, name, view):
    """The anchor's byte-level comparison, as information."""
    if anchor is None or not directory or not os.path.isdir(directory):
        return
    try:
        rows = provenance.scan_tree(directory, None)
        problems = provenance.compare(anchor, rows, name, view,
                                      directory)
    except Exception as err:                          # noqa: BLE001
        warn("the installed artwork against the tracked anchor's bytes",
             "the comparison could not be performed: %s" % err)
        return
    if not problems:
        info("the installed artwork against the tracked anchor's bytes",
             "all %d file(s) and the tree digest match the anchor"
             % anchor.get("file_count", len(rows)))
        return
    warn("the installed artwork against the tracked anchor's bytes",
         "%d difference(s) on THIS host, which is host state and not "
         "committed evidence because gfx/ is git-ignored: %s.  "
         "launch_game.sh verifies this tree against the anchor before "
         "every launch, so a RECORDING cannot be made under a "
         "mismatched pack; re-hydrate it with launch_game.sh or "
         "regenerate the anchor with tileset_provenance.py generate if "
         "the artwork legitimately changed"
         % (len(problems), summarise(problems, 3)))


def check_configured(options_path, required, aliases):
    """The committed option values, which are what the engine obeyed."""
    try:
        values = option_values(options_path, ("TILES", "USE_TILES"))
    except (OSError, ValueError) as err:
        bad("the committed configuration selects the required tileset",
            str(err),
            "a readable %s carrying TILES and USE_TILES" % options_path)
        return
    tiles = values.get("TILES")
    use_tiles = values.get("USE_TILES")
    problems = []
    if tiles is None:
        problems.append("TILES is absent")
    elif tiles not in aliases and tiles != required:
        problems.append("TILES=%r" % tiles)
    if str(use_tiles).lower() != "true":
        problems.append("USE_TILES=%r" % use_tiles)
    if problems:
        bad("the committed configuration selects the required tileset",
            ", ".join(problems),
            "TILES one of {%s} and USE_TILES=true in %s -- this file is "
            "committed, so which artwork the session was configured for "
            "is a checkable property rather than a claim"
            % (", ".join(sorted(aliases)) or required, options_path))
        return
    ok("the committed configuration selects the required tileset",
       "%s carries TILES=%s and USE_TILES=%s"
       % (options_path, tiles, use_tiles))


def main(argv):
    tooling_dir, options_path, required, alias_text = argv[1:5]
    sys.path.insert(0, tooling_dir)
    try:
        import tileset_provenance as provenance
    except Exception as err:                          # noqa: BLE001
        bad("the required tileset is installed and is the one the "
            "tracked anchor describes",
            "tileset_provenance.py could not be imported: %s" % err,
            "the provenance module beside this gate, which owns the "
            "anchor and reads a tileset.txt the way the engine does")
        bad("the committed configuration selects the required tileset",
            "not measured, because the provenance module would not "
            "import", "both readings performed")
        return 0
    aliases = set(alias_text.split())
    if required:
        aliases.add(required)
    # THE ANCHOR NAMES THE DIRECTORY, and deliberately nothing else does.
    # env.sh states that the anchor's location is not a tunable; the
    # install location is the anchor's own `tileset.directory`, and
    # provenance.compare() holds the pack to it, so the gate reads it
    # from there rather than accepting one from its caller.
    anchor = load(provenance)
    if anchor is None:
        bad("the committed configuration selects the required tileset",
            "not measured, because the tracked anchor would not load",
            "both readings performed")
        return 0
    directory = anchor.get("tileset", {}).get("directory", "")
    check_installed(provenance, anchor, directory, required, aliases)
    name = view = None
    if directory and os.path.isdir(directory):
        try:
            name = provenance.tileset_field(directory, "NAME")
            view = provenance.tileset_field(directory, "VIEW")
        except Exception:                             # noqa: BLE001
            name = view = None
    report_anchor_bytes(provenance, anchor, directory, name, view)
    check_configured(options_path, required, aliases)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
}

# THE ENGINE'S OWN WORD ON WHICH ARTWORK IT LOADED.  This is the only
# assertion in the gate about the tileset that describes the RECORDED
# SESSION rather than the auditing host: cata_tiles logs
# "Loaded tileset: <id>" after the artwork is loaded
# (src/cata_tiles.cpp:5183), the log is written into the userdir, and the
# userdir is committed.
check_tileset_in_engine_log() {
    local relative="" path="" hits="" inspected=0 loaded=""
    local -a seen=()
    for relative in "${DEBUG_LOG_RELATIVE_PATHS[@]}"; do
        path="${PLAYTHROUGH_USERDIR}/${relative}"
        [ -f "${path}" ] || continue
        inspected=$((inspected + 1))
        hits="$("${GREP}" -F "${TILESET_LOADED_PREFIX}" "${path}" \
            2>/dev/null || true)"
        [ -n "${hits}" ] || continue
        while IFS= read -r loaded; do
            [ -n "${loaded}" ] || continue
            seen+=("${loaded##*"${TILESET_LOADED_PREFIX}" }")
        done <<EOF
${hits}
EOF
    done
    if [ "${inspected}" -eq 0 ]; then
        record_fail "the engine's own log records loading the required \
tileset" \
            "no engine log at \
$(rel "${PLAYTHROUGH_USERDIR}")/{config/debug.log,debug.log}" \
            "a committed engine log carrying \
'${TILESET_LOADED_PREFIX} ${PLAYTHROUGH_TILESET}' -- it is the game's \
own statement of which artwork it drew"
        return 0
    fi
    local entry=""
    for entry in "${seen[@]}"; do
        if [ "${entry}" = "${PLAYTHROUGH_TILESET}" ]; then
            record_pass "the engine's own log records loading the \
required tileset" \
                "$(rel "${PLAYTHROUGH_USERDIR}"): \
${TILESET_LOADED_PREFIX} ${entry} -- written by the engine at capture \
time, so it describes the recorded session and not this audit"
            return 0
        fi
    done
    record_fail "the engine's own log records loading the required \
tileset" \
        "${#seen[@]} tileset(s) loaded: ${seen[*]:-none}" \
        "'${TILESET_LOADED_PREFIX} ${PLAYTHROUGH_TILESET}' among them \
-- a session rendered in other artwork does not satisfy the requirement"
}

# THE PIXELS.  Unique-colour depth on a spread of IN-GAME captures, which
# is the one assertion here that no amount of editing configuration or
# swapping packs after the fact can satisfy.
check_tiles_are_visible() {
    local list="" count=0 index="" path="" colours=""
    local best=0 best_frame="" measured=0
    local -a unreadable=()
    # THE POPULATION IS A FILE, one in-game capture index per line, and it
    # is sampled by line number rather than read into a shell variable:
    # see WHICH CAPTURES SHOW THE GAME BEING PLAYED in the record checker.
    list="$(in_game_file)"
    count="$(count_lines "${list}")"
    if [ "${count}" -eq 0 ]; then
        record_fail "the captures were rendered from sprite artwork and \
not from glyphs" \
            "group 2 published no in-game captures, so there is no \
gameplay frame to measure" \
            "at least one capture whose sidebar clock was legible -- \
those are the frames on which the map, and therefore the tileset, is \
drawn"
        return 0
    fi
    while read -r index; do
        [ -n "${index}" ] || continue
        if ! path="$(capture_path "${index}")"; then
            continue
        fi
        colours="$(bounded "${BOUND_PROBE_SECONDS}" \
            "${IDENTIFY}" -format '%k' "${path}" \
            2>"$(tool_error_file identify)" || true)"
        if ! is_count "${colours}"; then
            unreadable+=("$(printf '%05d' "${index}")")
            continue
        fi
        measured=$((measured + 1))
        if [ "${colours}" -gt "${best}" ]; then
            best="${colours}"
            best_frame="$(printf '%05d' "${index}")"
        fi
    done < <(sample_file "${TILE_COLOUR_SAMPLES}" "${list}")
    if [ "${measured}" -eq 0 ]; then
        record_fail "the captures were rendered from sprite artwork and \
not from glyphs" \
            "no colour reading could be taken (unreadable: \
${unreadable[*]:-none})$(because identify)" \
            "at least one readable capture -- 'identify -format %k' \
counts the distinct colours in a frame"
        return 0
    fi
    if [ "${best}" -ge "${TILE_COLOUR_FLOOR}" ]; then
        record_pass "the captures were rendered from sprite artwork and \
not from glyphs" \
            "capture ${best_frame} holds ${best} distinct colours \
(${measured} of ${count} in-game captures read, threshold \
${TILE_COLOUR_FLOOR}; ${TILE_COLOUR_REFERENCE})"
        return 0
    fi
    record_fail "the captures were rendered from sprite artwork and not \
from glyphs" \
        "the richest of ${measured} in-game captures read holds only \
${best} distinct colours (capture ${best_frame:-none})" \
        "at least ${TILE_COLOUR_FLOOR} on one of them -- \
${TILE_COLOUR_REFERENCE}, so a glyph-rendered session cannot reach this \
threshold and a tiles-rendered one clears it by an order of magnitude"
}

check_lint_scoped() {
    local output="" status=0 count=""
    if [ "${#FLAKE8_CMD[@]}" -eq 0 ]; then
        record_fail "the new Python satisfies the repository's own \
lint contract" \
            "no flake8 could be resolved" \
            "flake8 on PATH, importable by the interpreter env.sh \
resolved, or named by PLAYTHROUGH_FLAKE8 -- the check is not skippable, \
because a lint gate that silently does not run is not a gate.  Running \
this gate INSIDE the declared container leaves only the first two of \
those: supported_env.sh forwards HOME, TMPDIR and the cleared \
trust-bypass names and nothing else, so a host-side PLAYTHROUGH_FLAKE8 \
never arrives and the linter must be installed in the image"
        return 0
    fi
    # THE OUTPUT GOES TO A FILE, and the ceiling is real.  A linter is
    # not session-length work -- it reads the tooling directory -- but it
    # is a child of this gate, and a child with no bound can hold the
    # pipeline's lock for ever.  Its findings are counted from the file
    # and quoted from it in bounded form rather than captured whole into
    # a shell variable.
    local log="${SCRATCH}/flake8.log"
    set +e
    bounded "${BOUND_LINT_SECONDS}" "${FLAKE8_CMD[@]}" playthrough/ \
        >"${log}" 2>&1
    status=$?
    set -e
    count="$(count_lines "${log}")"
    if [ "${status}" -eq 0 ] && [ "${count:-0}" -eq 0 ]; then
        record_pass "the new Python satisfies the repository's own \
lint contract" \
            "flake8 playthrough/ reports nothing, under .flake8's own \
configuration and its default 79-column limit"
        return 0
    fi
    if bound_expired "${status}"; then
        record_fail "the new Python satisfies the repository's own \
lint contract" \
            "flake8 did not finish within ${BOUND_LINT_SECONDS}s and \
was stopped (exit ${status})" \
            "a completed lint run -- the linter reads the tooling \
directory, which does not grow with the session, so an expiry here \
means it is wedged"
        return 0
    fi
    output="$(excerpt "${log}" 4)"
    record_fail "the new Python satisfies the repository's own lint \
contract" \
        "${count:-0} finding(s), exit ${status}: ${output}" \
        "zero findings under playthrough/ -- scoped deliberately, \
because HEAD already carries pre-existing F824 findings under tools/ \
that are not this feature's"
}

check_flake8_not_weakened() {
    local hits=""
    if [ ! -f ".flake8" ]; then
        record_fail "the shared lint configuration was not weakened" \
            "there is no .flake8 in this checkout" \
            "the repository's .flake8, unmodified"
        return 0
    fi
    hits="$("${GREP}" -n 'playthrough' .flake8 2>/dev/null || true)"
    if [ -z "${hits}" ]; then
        record_pass "the shared lint configuration was not weakened" \
            ".flake8 names playthrough nowhere, so the new code passes \
the existing gate rather than being excluded from it"
        return 0
    fi
    record_fail "the shared lint configuration was not weakened" \
        "${hits}" \
        "no 'playthrough' token in .flake8 -- relaxing shared \
configuration to accommodate new code is the wrong trade"
}

check_timeline_tests() {
    local suite="${PLAYTHROUGH_TOOLING_DIR}/test_timeline.py"
    local output="" status=0 summary=""
    if [ ! -f "${suite}" ]; then
        record_fail "the timeline's own test suite passes" \
            "$(rel "${suite}") is absent" \
            "the regression suite that covers the clamp, the rollover \
guard, the cue arithmetic and the timecode formatter"
        return 0
    fi
    # AS WITH THE LINTER: bounded, and read back from a file.  A suite
    # that hangs -- a test waiting on a lock, a fixture waiting on a
    # descriptor -- would otherwise hold this gate open indefinitely.
    local log="${SCRATCH}/test_timeline.log"
    set +e
    bounded "${BOUND_SUITE_SECONDS}" "${PYTHON}" -B "${suite}" \
        >"${log}" 2>&1
    status=$?
    set -e
    # THE ELAPSED TIME IS STRIPPED, and that is about the durable report
    # rather than about tidiness.  unittest prints "Ran 361 tests in
    # 2.675s", and that number changes on every run -- so leaving it in
    # would make a committed acceptance report differ from one run to the
    # next while measuring an identical tree, which is churn in the
    # history carrying no information, and would make a second verify
    # before a commit fail its own "nothing left uncommitted" check on a
    # file this gate had just rewritten.  How many tests ran and whether
    # they passed is the evidence; how many seconds they took is not.
    # Read from the LOG FILE rather than from a captured variable, so a
    # suite that prints a line per test cannot put its whole output into
    # this shell's memory to produce one summary line.
    summary="$("${GREP}" -E '^(Ran |OK|FAILED)' "${log}" 2>/dev/null |
        "${SED}" -E 's/ in [0-9]+\.[0-9]+s$//' |
        "${TR}" '\n' ' ' || true)"
    if [ "${status}" -eq 0 ]; then
        record_pass "the timeline's own test suite passes" \
            "${summary:-exit 0}"
        return 0
    fi
    if bound_expired "${status}"; then
        record_fail "the timeline's own test suite passes" \
            "the suite did not finish within ${BOUND_SUITE_SECONDS}s \
and was stopped (exit ${status}): ${summary:-<no summary line>}" \
            "exit 0 inside the ceiling -- the suite is arithmetic over \
fixtures it writes itself and does not grow with the session, so an \
expiry means it is wedged"
        return 0
    fi
    record_fail "the timeline's own test suite passes" \
        "exit ${status}: ${summary:-$(excerpt "${log}" 3)}" \
        "exit 0 -- the deterministic half of this feature is the half \
that can be unit tested, so it is"
}

# THE CHANGE SURFACE.  The engine, its tests, its content, its build
# system and its CI are consumed read-only; the only pre-existing tracked
# files this feature is allowed to have touched are .gitignore and
# .gitattributes, and both changes are additive appends.
check_change_surface() {
    local base="${BASE_COMMIT}"
    local changed="" allowed=""
    if [ -z "${base}" ]; then
        base="$(default_base_commit || true)"
    fi
    if [ -z "${base}" ] ||
            ! "${GIT}" rev-parse --verify --quiet "${base}" \
                >/dev/null 2>&1; then
        record_fail "the change surface is only the two ignore files \
and playthrough/" \
            "no usable base commit (tried '${base:-none}')" \
            "a reachable commit -- pass --base <commit> to name one"
        return 0
    fi
    record_info "the base commit the change surface is measured from" \
        "$("${GIT}" log -1 --format='%h %s' "${base}" 2>/dev/null ||
            printf '%s' "${base}")"
    changed="$("${GIT}" diff --name-only "${base}..HEAD" \
        2>/dev/null || true)"
    allowed=" ${ALLOWED_FOREIGN_PATHS} "
    local path=""
    local -a foreign_paths=()
    while IFS= read -r path; do
        [ -n "${path}" ] || continue
        case "${path}" in
            playthrough/*) continue ;;
        esac
        case "${allowed}" in
            *" ${path} "*) continue ;;
        esac
        foreign_paths+=("${path}")
    done <<EOF
${changed}
EOF
    if [ "${#foreign_paths[@]}" -eq 0 ]; then
        record_pass "the change surface is only the two ignore files \
and playthrough/" \
            "$(printf '%s' "${changed}" | "${GREP}" -c . || true) \
changed \
path(s) since ${base:0:10}, all of them under playthrough/ or one of: \
${ALLOWED_FOREIGN_PATHS}"
        return 0
    fi
    # Bounded, because an ill-chosen base can put a thousand upstream
    # paths in this list, and a finding nobody can read is a finding
    # nobody acts on.  The count is the number that matters; the first
    # few name the kind of thing that leaked in.
    local total="${#foreign_paths[@]}"
    local shown="${foreign_paths[*]:0:8}"
    if [ "${total}" -gt 8 ]; then
        shown="${shown} ... (and $((total - 8)) more)"
    fi
    record_fail "the change surface is only the two ignore files and \
playthrough/" "${total} path(s) outside the allowance: ${shown}" \
        "nothing outside playthrough/ except ${ALLOWED_FOREIGN_PATHS} \
-- src/, tests/, data/, gfx/, the build system and .github/ are read \
only for this feature"
}

# check_security_controls
#   Every security control this tooling relies on is present, and the
#   report says which ones they are.
#
#   WHY A CHECK AND NOT A PARAGRAPH.  A review found the acceptance
#   report and REPORT.md recording a known plan divergence as a pass AND
#   "omitting security controls" -- the two halves of one problem, which
#   is that the report described the run in terms of counts and said
#   nothing about what was actually being enforced.  A reader could not
#   tell a run with these controls from a run without them.
#
#   So the controls are INVENTORIED HERE, by asserting each one is still
#   in the code, and the names are printed in the observed text -- which
#   means playthrough/acceptance-report.txt carries the list as evidence
#   rather than as a claim somebody maintains by hand.  A control that is
#   removed or renamed fails this check instead of quietly disappearing
#   from the report.
#
#   Each entry is `label|file|marker`.  The marker is the smallest thing
#   whose absence means the control is gone -- a function name or a
#   verdict name -- not a fragment of prose, which could be reworded
#   without weakening anything.
readonly SECURITY_CONTROLS="\
credential containment: the git config carrying the push token is \
owner-only|commit_artifacts.sh|assert_credential_containment
git runs no hook on a mutating command|commit_artifacts.sh|hooks_void
the published commit tree is bound to the validated \
index|commit_artifacts.sh|assert_commit_tree_matches_index
staging provenance: owner, regular file, single link, same \
device|commit_artifacts.sh|assert_staging_provenance
a secret and credential scan over every path before it is \
staged|commit_artifacts.sh|assert_no_secret_material
the runtime anchor refuses a group- or world-writable non-sticky \
ancestor|env.sh|playthrough_check_path_ancestry
artifacts are created owner-only and foreign writability is \
refused|env.sh|playthrough_deny_foreign_write
the inherited environment is sanitised before any child \
runs|env.sh|playthrough_sanitize_environment
one checkout-wide mutation lock, shared for producers and exclusive \
for the committer|env.sh|playthrough_acquire_lock
the X server is identified by process identity, socket and cookie \
digest|env.sh|playthrough_pid_identity
a fresh X authority cookie per server generation|env.sh|\
playthrough_ensure_xauth
values chosen outside this pipeline are held to a record-token \
grammar|env.sh|playthrough_assert_record_token
every diagnostic escapes control bytes|env.sh|\
playthrough_escape_controls
the evidence ledgers are hash-chained and anchored to git blob \
names|manifest.py|seal_artifacts
journal writes are verified and durability failures \
propagate|session.py|_write_durably
the machine-readable payload cannot be forged by a chosen \
value|session.py|_CONTROL_RE
the decoder is entered only on an owner-only regular \
file|ocr_clock.py|assert_decodable_provenance
the decode runs under resource limits with core dumps \
forbidden|ocr_clock.py|decode_limits
the composer checks provenance before MoviePy decodes|make_transitions.py|\
_assert_decodable_provenance
the survivor name is held to a conservative grammar rather than \
escaped|make_srt.py|assert_survivor_name_grammar
the container is identified by image id and build-inputs \
digest|supported_env.sh|assert_image_provenance"

check_security_controls() {
    local missing=() present=() line label file marker source
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        label="${line%%|*}"
        file="${line#*|}"
        marker="${file#*|}"
        file="${file%%|*}"
        source="${PLAYTHROUGH_TOOLING_DIR}/${file}"
        if [ ! -f "${source}" ]; then
            missing+=("${label} (${file} is absent)")
        elif ! "${GREP}" -q -- "${marker}" "${source}"; then
            missing+=("${label} (${file} no longer defines ${marker})")
        else
            present+=("${label}")
        fi
    done <<EOF
${SECURITY_CONTROLS}
EOF
    if [ "${#missing[@]}" -gt 0 ]; then
        record_fail "every security control this record relies on is \
present, and this report names them" \
            "$(printf '%s; ' "${missing[@]}")" \
            "each control still in the file that implements it -- a \
control removed silently would leave this report describing \
protections the delivered code no longer has"
        return 0
    fi
    record_pass "every security control this record relies on is \
present, and this report names them" \
        "${#present[@]} control(s): $(printf '%s; ' "${present[@]}")"
}

group_hygiene() {
    group 9 "the binary, the required artwork and repository hygiene"
    # THE ARTIFACT-SHAPED HALF OF THIS GROUP.  The binary, the artwork,
    # the pixels of the captures, the linter and the timeline suite are
    # all properties of the tree as it stands, answered by the
    # pre-commit phase; the commit does not touch any of them, so the
    # post-commit phase does not re-run them.  `all` does.
    if artifact_phase; then
        check_binary_is_tiles
        # The options file is handed over in its REPOSITORY-RELATIVE
        # spelling: the gate has already chdir'd to the repository root,
        # so it opens identically, and every path this report prints
        # stays relative to the checkout rather than naming somebody's
        # home directory.
        run_checker tileset \
            "${PLAYTHROUGH_TOOLING_DIR}" \
            "$(rel "${PLAYTHROUGH_OPTIONS_JSON}")" \
            "${PLAYTHROUGH_TILESET}" \
            "${PLAYTHROUGH_TILESET_ALIASES}"
        check_tileset_in_engine_log
        check_tiles_are_visible
        check_lint_scoped
        check_flake8_not_weakened
        check_timeline_tests
        check_staging_soundness
        check_security_controls
    fi
    # The change surface is measured from a base commit to HEAD, so it
    # is a property of the COMMIT: before the checkpoint, the artifacts
    # this feature added are not in HEAD to be measured, and on a tree
    # where nothing has been committed yet there is no base commit to
    # measure from either.
    if tracking_phase; then
        check_change_surface
    fi
    # Re-read for bytecode AFTER the suite ran, so the claim is that this
    # gate itself left no trace and not merely that none was there before.
    check_no_bytecode "this gate itself left no interpreter bytecode \
behind"
}


# ---------------------------------------------------------------------
# 10  THE INVENTORY OF THIS REPORT
#
# The last check, and the only one whose subject is the report itself.
# Everything above measures the artifacts; this measures whether they
# were all measured.  It exists because the failure it catches is
# invisible without it: a checker that died halfway, a check that
# returned early, or an assertion an edited artifact managed to remove
# leaves a report that is shorter and just as green.
# ---------------------------------------------------------------------
# distinct_checks_in GROUP -- how many different check names that group
# reported.  Distinct, not total, so a check that legitimately reports
# once per offending item counts once.
distinct_checks_in() {
    local file="${SCRATCH}/checks-$1.seen"
    [ -f "${file}" ] || { printf '0'; return 0; }
    "${SORT}" -u -- "${file}" | "${GREP}" -c . || printf '0'
}

# repeated_checks_in GROUP -- the names that reported more than once,
# with their counts, so per-item repetition is visible in the report
# instead of merely tolerated by it.
repeated_checks_in() {
    local file="${SCRATCH}/checks-$1.seen"
    [ -f "${file}" ] || return 0
    # SC2016: `$0` is awk's whole-line variable and must NOT be expanded
    # by the shell, which is exactly why the program is single-quoted.
    # shellcheck disable=SC2016
    "${SORT}" -- "${file}" | "${AWK}" '
        { count[$0]++ }
        END {
            for (name in count) {
                if (count[name] > 1) {
                    printf "%s (x%d)\n", name, count[name]
                }
            }
        }' | "${SORT}" | "${TR}" '\n' ';' || true
}

check_check_inventory() {
    local name="this report contains every check this gate declares"
    local index=0 declared=0 seen_count=0 repeats=""
    local total=0 expected=0
    local -a short=()
    local -a over=()
    local -a repeated=()
    # THIS VERDICT COUNTS ITSELF IN.  It is group 10's only check and it
    # has not registered yet, so group 10's declared 1 is compared
    # against a seen count of 0 + this one.
    for ((index = 1; index <= GROUP_COUNT; index++)); do
        # THREE PHASES, THREE TABLES, CHOSEN BY THE PHASE ITSELF.  This
        # used to select on tracking_phase(), which is true for `all` AND
        # for `post-commit` because it means "this phase measures the
        # history" -- so the post-commit phase compared its own 31
        # verdicts against the whole audit's 122 and reported every
        # artifact group as SHORT while performing exactly what it
        # declared.  The counts are per phase, so the choice is too.
        case "${PHASE}" in
            "${PHASE_PRE_COMMIT}")
                declared="${GROUP_CHECKS_PRE_COMMIT[index]}" ;;
            "${PHASE_POST_COMMIT}")
                declared="${GROUP_CHECKS_POST_COMMIT[index]}" ;;
            *)
                declared="${GROUP_CHECKS_ALL[index]}" ;;
        esac
        seen_count="$(distinct_checks_in "${index}")"
        if [ "${index}" -eq "${GROUP_COUNT}" ]; then
            seen_count=$((seen_count + 1))
        fi
        total=$((total + seen_count))
        expected=$((expected + declared))
        if [ "${seen_count}" -lt "${declared}" ]; then
            short+=("${index} ${GROUP_NAMES[index]}: \
${seen_count} of \
${declared}")
        elif [ "${seen_count}" -gt "${declared}" ]; then
            over+=("${index} ${GROUP_NAMES[index]}: ${seen_count} against \
${declared} declared")
        fi
        repeats="$(repeated_checks_in "${index}")"
        if [ -n "${repeats}" ]; then
            repeated+=("group ${index}: ${repeats}")
        fi
    done
    # Per-item repetition is REPORTED, not counted as drift: it is the
    # legitimate shape of a broken artifact set, and a reader is better
    # off seeing which check spoke more than once than not.
    if [ "${#repeated[@]}" -ne 0 ]; then
        record_info "checks that reported more than once" \
            "${repeated[*]}"
    fi
    if [ "${#short[@]}" -eq 0 ] && [ "${#over[@]}" -eq 0 ]; then
        record_pass "${name}" \
            "${total} distinct checks against ${expected} declared for \
the '${PHASE}' phase, group by group -- every group exactly its declared \
count"
        return 0
    fi
    record_fail "${name}" \
        "${total} distinct of ${expected} declared\
${short[*]:+; SHORT -- group ${short[*]}}\
${over[*]:+; UNDECLARED -- group ${over[*]}}" \
        "each of the ${GROUP_COUNT} groups reporting exactly its \
declared number of DISTINCT checks for the '${PHASE}' phase. A short \
group means a check could not be performed, and a check that silently \
does not run is worse than no check. A long group means this gate \
performed a check its own declaration does not list, so the table beside \
GROUP_CHECKS_ALL in this file is out of date -- and the reason the \
comparison is per group and exact is that one global 'at least' let \
extra verdicts in one group pay for missing checks in another"
}

group_inventory() {
    group 10 "the inventory of this report"
    check_check_inventory
}


# ---------------------------------------------------------------------
# THE SUMMARY
#
# One human line, then the machine block.  Nothing here decides the exit
# status: that is taken once, at file scope, after every group has run,
# which is what makes "run every check" true rather than aspirational.
#
# The message is assembled into a variable and printed with a '%s'
# format.  A multi-line printf FORMAT would need a backslash before each
# newline, and a backslash inside a single-quoted format is a literal
# backslash rather than a line continuation -- it would print in the
# report.
# ---------------------------------------------------------------------
summarise_run() {
    # A divergence IS a performed check -- it registered a name
    # in the inventory -- so it is counted in the total; it is
    # just neither a pass nor a failure.
    local total=$((PASSES + FAILURES + DIVERGENCES))
    local message=""
    say '\n'
    # The declared inventory is printed on the summary line as well as
    # asserted above, because "93 of 93" tells a reader nothing about
    # whether 93 was the number to expect.
    local counted="${total} performed, ${EXPECTED_CHECKS} declared"
    if [ "${total}" -eq "${EXPECTED_CHECKS}" ]; then
        counted="${total} of ${EXPECTED_CHECKS} declared"
    fi
    counted="${counted} for the '${PHASE}' phase"
    if [ "${FAILURES}" -eq 0 ] && [ "${DIVERGENCES}" -eq 0 ]; then
        message="SUMMARY  ${PASSES} of ${total} checks passed "
        message="${message}(${counted}), ${INFOS} informational "
        message="${message}note(s); the committed artifacts are what "
        message="${message}they claim to be."
    elif [ "${FAILURES}" -eq 0 ]; then
        # NOTHING FAILED AND THE RUN STILL DOES NOT CLAIM COMPLIANCE.
        # The sentence a reader takes away has to say so: this used to
        # end "the committed artifacts are what they claim to be" while
        # a known departure from the plan sat above it reported as PASS.
        message="SUMMARY  ${PASSES} of ${total} checks passed with "
        message="${message}${DIVERGENCES} DIVERGENCE(S) from the plan "
        message="${message}(${counted}), ${INFOS} informational "
        message="${message}note(s).  Nothing FAILED, but the run does "
        message="${message}not claim full compliance: each divergence "
        message="${message}above prints what the plan requires, what "
        message="${message}was delivered instead, and why it stands."
    else
        message="SUMMARY  ${FAILURES} of ${total} checks FAILED "
        message="${message}(${PASSES} passed, ${DIVERGENCES} "
        message="${message}divergence(s), ${counted}, ${INFOS} "
        message="${message}informational note(s)).  Each failure above "
        message="${message}prints what was observed next to what was "
        message="${message}required."
    fi
    say '%s\n' "${message}"
    note VERIFY_PHASE "${PHASE}"
    # THE TREE, MACHINE-READABLY.  The header says this in prose, which
    # a human reads and no caller can act on.  A checkpoint that
    # publishes this report has to be able to prove the report is about
    # the commit it is being committed onto -- otherwise a report
    # generated, left to sit while more commits landed, and then
    # committed is stale in exactly the way that was found here, and
    # only a human comparing two strings by eye would notice.
    note VERIFY_MEASURED_COMMIT "${MEASURED_COMMIT}"
    note VERIFY_CHECKS "${total}"
    note VERIFY_EXPECTED_CHECKS "${EXPECTED_CHECKS}"
    note VERIFY_PASSES "${PASSES}"
    note VERIFY_FAILURES "${FAILURES}"
    note VERIFY_DIVERGENCES "${DIVERGENCES}"
    note VERIFY_INFOS "${INFOS}"
    note VERIFY_CAPTURES "$(fact capture_count '?')"
    note VERIFY_ROWS "$(fact manifest_rows '?')"
    note VERIFY_TIMELINE_TOTAL "$(fact timeline_total '?')"
    note VERIFY_TRANSITIONS "$(fact transition_groups '?')"
    local report_target=""
    # No `|| true`: report_publication_target cannot fail, by design and
    # by test.  An exemption here would read as though it could, and the
    # other call site's MISSING exemption is what once killed a passing
    # run -- so the rule is the function's, not each caller's.
    report_target="$(report_publication_target)"
    if [ -n "${report_target}" ]; then
        note VERIFY_REPORT "$(rel "${report_target}")"
    else
        note VERIFY_REPORT none
    fi
    # THE ONE TOKEN EVERY CALLER READS.  A third value rather than
    # folding a divergence into `pass`: a review found this gate
    # publishing VERIFY=pass while a known departure from the plan sat
    # in the report above it, and the acceptance report and REPORT.md
    # then inherited the word `pass` without the prose that qualified it.
    # A caller that only understands pass/fail treats
    # `pass-with-divergence` as neither, which is the correct default for
    # something it has no rule for.
    if [ "${FAILURES}" -ne 0 ]; then
        note VERIFY fail
    elif [ "${DIVERGENCES}" -ne 0 ]; then
        note VERIFY pass-with-divergence
    else
        note VERIFY pass
    fi
}

main() {
    parse_arguments "$@"
    # EVERY EXTERNAL COMMAND FIRST.  open_scratch is made of mktemp and
    # chmod, so resolving after it would leave the gate's own tools
    # unverified; the verdict on this is reported by check_tool_inventory
    # in group 1, where the report has begun.
    resolve_tools
    take_mutation_lock
    open_scratch
    : >"${SCRATCH}/facts"
    emit_record_checker
    emit_evidence_checker
    emit_timeline_checker
    emit_caption_checker
    emit_render_checker
    emit_tileset_checker

    say '%s\n' "verify_artifacts.sh -- the acceptance gate for the \
playthrough capture subsystem"
    say '%s\n' "reading the committed artifacts under \
$(rel "${PLAYTHROUGH_DIR}")/ at the repository root"
    MEASURED_COMMIT="$(measured_commit)"
    say '%s\n' "measuring the tree at ${MEASURED_COMMIT}"
    # THE PHASE IS THE FIRST THING THE REPORT SAYS.  A pre-commit report
    # is legitimately shorter than a post-commit one, and a reader who
    # was not told which phase produced it cannot tell a deferred check
    # from a missing one.
    if ! tracking_phase; then
        printf '%s\n' "phase '${PHASE}': every property of the \
ARTIFACTS; the properties of the COMMIT are deferred to the \
'${PHASE_POST_COMMIT}' phase, which runs after the checkpoint \
(${EXPECTED_CHECKS} checks declared)"
    elif ! artifact_phase; then
        printf '%s\n' "phase '${PHASE}': the properties of the \
HISTORY, and the environment they are measured with; the properties of \
the ARTIFACTS were answered by the '${PHASE_PRE_COMMIT}' phase before \
the checkpoint and the commit did not touch them -- run '${PHASE_ALL}' \
to measure everything (${EXPECTED_CHECKS} checks declared)"
    else
        printf '%s\n' "phase '${PHASE}': every property, the \
artifacts and the history alike (${EXPECTED_CHECKS} checks declared)"
    fi

    group_environment
    if artifact_phase; then
        group_record
        group_timeline
        group_container
        group_captions
        group_luminance
    fi
    group_version_control
    if artifact_phase; then
        group_no_cheating
    fi
    group_hygiene
    group_inventory

    summarise_run
    # LAST, so the durable copy carries the summary and the machine
    # block it is summarised by.  publish_report reports its own outcome
    # to stdout WITHOUT counting a verdict: the totals have already been
    # printed, and a note that increments them after the fact would make
    # the report disagree with its own arithmetic.
    publish_report
    return "${EX_OK}"
}

# main always returns success; the verdict on the ARTIFACTS is the
# failure counter, and it is turned into an exit status exactly once,
# here, after every group has been given its chance to report.  `exit`
# at file scope also keeps the ERR trap out of it: a non-zero `return`
# from main would fire the trap and print a spurious FATAL line about a
# gate that worked perfectly.
main "$@"

if [ "${FAILURES}" -ne 0 ]; then
    exit "${EX_FAILED}"
fi
exit "${EX_OK}"
