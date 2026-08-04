#!/bin/bash
# ---------------------------------------------------------------------
# playthrough/tooling/embed_captions.sh
#
# BASH IS REQUIRED, not optional: BASH_SOURCE locates this file, arrays
# carry the mux command as an argument list rather than a string, and
# `local` scopes every helper.  The interpreter is spelled the way the
# two scripts this one takes its shape from spell it --
# build-scripts/clang-tidy-run.sh:1 and build-scripts/build.sh:1 -- and
# the way the repository spells it most often (18 of its shell scripts
# against 10 using the env form).  The siblings in this folder use
# `env bash`; the difference is deliberate rather than an oversight,
# and either form runs this file correctly wherever bash is at /bin.
#
# THE CAPTION MUX.  One film in, one cue file in, one film out that
# carries the survivor's transcript as a SELECTABLE closed-caption
# track.
#
# It muxes playthrough/transcript.srt into playthrough/cata-play.mp4 as
# a soft mov_text subtitle stream and writes
# playthrough/cata-play-cc.mp4.  The picture is STREAM-COPIED: not one
# byte of video is re-encoded, and no text is ever written into the
# pixels.
#
# USAGE
#     playthrough/tooling/embed_captions.sh
#     playthrough/tooling/embed_captions.sh IN.mp4 IN.srt OUT.mp4
#     playthrough/tooling/embed_captions.sh --help
#
# With no arguments the three paths come from env.sh, which is the one
# place the artifact layout is defined:
#
#     playthrough/cata-play.mp4     <- PLAYTHROUGH_MOVIE
#     playthrough/transcript.srt    <- PLAYTHROUGH_TRANSCRIPT_SRT
#     playthrough/cata-play-cc.mp4  <- PLAYTHROUGH_MOVIE_CC
#
# The positional overrides exist so an operator can mux a trial render
# without disturbing the committed artifacts.  They can change WHICH
# files are read and written and NOTHING ELSE: there is no argument, and
# no environment variable, that can add a filter, re-encode the picture,
# burn text into it, or change the caption codec or its language tag.
# Those are the requirement, not a default.
#
# ---------------------------------------------------------------------
# THE RECIPE, AND WHY EVERY PART OF IT IS THERE
#
#     ffmpeg -y -i <film> -i <cues> -c copy \
#            -c:s mov_text -metadata:s:s:0 language=eng <output>
#
# This is the command the requirement specifies, used as given.  Each
# flag is load-bearing:
#
#   -c copy         The picture is copied, packet for packet.  The film
#                   that was measured non-blank and correctly paced is
#                   the film that ships.  Re-encoding here would be a
#                   second lossy generation over evidence, and would
#                   also break the byte-identity check below.
#
#   -c:s mov_text   NOT OPTIONAL, AND NOT COSMETIC.  `-c copy` alone
#                   would try to copy the SubRip codec into MP4, which
#                   is not a legal MP4 subtitle codec, and the mux
#                   fails outright.  mov_text (3GPP timed text) is the
#                   only broadly supported subtitle codec inside MP4
#                   and it is what makes the track SOFT -- carried
#                   beside the picture and toggled by the player --
#                   rather than drawn into it.
#
#   -metadata:s:s:0 language=eng
#                   The ISO-639 three-letter code on the first
#                   subtitle stream, so a player lists the track as
#                   English.  English only: there is no translation
#                   track and no localisation in this feature.
#
#   -y              Overwrite, so re-running the stage is idempotent.
#                   It is applied to this script's own staging file
#                   (see THE STAGING FILE), never to a published
#                   artifact that has not yet been replaced by a
#                   verified one.
#
# No stream mapping is given, deliberately.  With one video input and
# one subtitle input, ffmpeg's default selection takes the video from
# the first and the single subtitle stream from the second, which is
# exactly the one-track case here; a hand-written mapping would add a
# way to drop the picture and buy nothing.
#
# ---------------------------------------------------------------------
# *** THE CAPTIONS ARE NEVER DRAWN INTO THE PICTURE ***
#
# The whole point of this pipeline is the captured pixels.  Text
# painted over them would obscure the very evidence the film exists to
# carry, and a caption that cannot be switched off is not a
# closed-caption track.
#
# So: this script builds NO filter graph and offers no way to ask for
# one.  There is no video-filter flag anywhere in it, no
# subtitle-burning filter, no text-drawing filter, and no video
# encoder -- the video disposition is `-c copy` and nothing else.  That
# is asserted after the mux by comparing the output's video stream
# against the input's, bit for bit: burned-in text or a re-encode would
# both change the copied packets and both fail the check.
#
# ---------------------------------------------------------------------
# WHAT THIS FILE READS AND WRITES
#
# Reads two files.  Writes exactly one path inside the working tree --
# the output container -- plus one staging file beside it that never
# survives this process, and one scratch file under the pipeline's
# private runtime directory, outside the tree entirely.  It touches no
# frame, no manifest, no timeline, no save data and no configuration.
# It starts no server, needs no display, makes no network call, and
# runs no command through a shell string: every external call is an
# argument list.  There is no dynamic-code construct anywhere in it and
# no unquoted glob.
#
# ---------------------------------------------------------------------
# THE STAGING FILE, AND WHY exit 0 MEANS SOMETHING
#
# ffmpeg writes to a sibling staging path, the whole verification runs
# against THAT file, and only a container that has passed every check
# is renamed into place.  The rename is within one directory, so it is
# atomic: a reader sees either the previous film or the new one, never
# a half-written one.
#
# Three consequences, all of them the point:
#
#   * exit 0 <=> a VERIFIED container exists at the output path.  A
#     container that ffmpeg called a success but that carries no
#     caption track can never be published: which streams reach the
#     output is a stream-selection decision, and a container missing
#     the track would satisfy any check that only asks whether the
#     file exists.  That is why the checks are here rather than left
#     to a later stage.
#   * A failed or interrupted run leaves NOTHING new in the working
#     tree.  The staging file is removed on the way out, so the commit
#     stage cannot stage a truncated container that nobody authored.
#   * A previously published, verified film is not destroyed by a
#     failed re-run.  It is replaced only by a film that passed.
#
# ---------------------------------------------------------------------
# THE EVIDENCE THIS SCRIPT PRINTS
#
# It does not claim the track is there; it shows the probe output that
# proves it, then exits on any assertion that fails.  The two mandated
# readouts are run verbatim against the published file and printed on
# stderr as they came back --
#
#     ffprobe -v error -select_streams s \
#       -show_entries stream=index,codec_name:stream_tags=language \
#       -of default=nw=1 <output>
#     ffprobe -v error -select_streams v \
#       -show_entries stream=codec_name,width,height \
#       -of default=nw=1 <output>
#
# -- and the first must report codec_name=mov_text with
# TAG:language=eng while the second must report h264 at 1920x1080.
#
# Everything printed on stdout is a KEY=value line, one per line, in a
# fixed order, so a caller can read a field without parsing prose:
#
#     out="$(playthrough/tooling/embed_captions.sh)"
#     path="$(printf '%s\n' "${out}" | sed -n 's/^OUTPUT_FILE=//p')"
#
# Diagnostics, warnings and the two verbatim probe readouts go to
# stderr, so the machine channel stays clean.  The keys, in order:
#
#     INPUT_MOVIE          the film that was read, repository-relative
#     INPUT_SRT            the cue file that was read
#     OUTPUT_FILE          the container that was written
#     OUTPUT_BYTES         its size on disk
#     VIDEO_CODEC          h264
#     VIDEO_WIDTH          1920
#     VIDEO_HEIGHT         1080
#     VIDEO_DURATION       seconds, from the output's video stream
#     VIDEO_FRAMES         frame count, from the output's video stream
#     VIDEO_COPY_PROOF     the strongest evidence that established
#                          that the picture was copied rather than
#                          re-encoded: stream-hash (byte-identical
#                          packets, the usual answer and the one to
#                          want) or, where this ffmpeg cannot hash a
#                          stream, duration+frames -- or duration or
#                          frames alone where the container carries
#                          only one of them
#     SUBTITLE_INDEX       the stream index the caption track occupies
#     SUBTITLE_CODEC       mov_text
#     SUBTITLE_LANGUAGE    eng
#     SUBTITLE_DURATION    seconds, from the output's subtitle stream
#     CUES_IN              cues in the source file
#     CUES_ROUND_TRIP      cues read back out of the container
#     CONTAINER_DURATION   the container's own duration
#
# ---------------------------------------------------------------------
# EXIT CODES
#     0  a verified captioned container is at the output path
#     1  usage error -- an unknown option, too many arguments, or a
#        path this script will not hand to ffmpeg
#     2  layout error -- this file cannot locate itself, or env.sh is
#        missing or refused to load
#     3  an input is missing, empty, or not the shape a cue file has,
#        or the output cannot be published where it was asked for.  Run
#        render_movie.py or make_srt.py first; the message says which
#     4  the mux itself failed or timed out, or another run of this
#        stage holds the lock
#     5  the command assembled was not the mandated recipe, or the
#        container was produced and does not carry what it must -- in
#        either case NOTHING was published
#     8  a prerequisite command is missing or is not trustworthy
#
# ---------------------------------------------------------------------
# COUNTING CUES: ONE MEASURED TRAP
#
# MP4 timed text has to cover the container contiguously, so the muxer
# PADS the gaps this transcript leaves for the cinematic transitions
# with empty samples of its own.  Measured against this script: three
# cues with one one-second gap between them go in, and ffprobe counts
# FOUR subtitle packets in the result.  make_srt.py records the same
# effect on its reference sequence -- seven cues in, nine packets out.
#
# So the packet count is NOT the cue count, and this script never
# treats it as one.  It reads the cues back OUT of the finished
# container with the SubRip encoder and counts those.  Measured against
# this script: three of three through that padded track, and 560 of 560
# for the real playthrough/transcript.srt -- cue text, cue numbering
# and cue timings all round-trip intact.
#
# ---------------------------------------------------------------------
# THE PRODUCERS THIS STAGE FOLLOWS
#
#   render_movie.py  writes playthrough/cata-play.mp4 -- H.264 in MP4,
#                    1920x1080, yuv420p, one variable-duration image
#                    entry per captured frame.  The MP4 container is
#                    required rather than incidental: mov_text is an
#                    MP4 feature.
#   make_srt.py      writes playthrough/transcript.srt -- SubRip, one
#                    cue per frame, sequence numbers from 1, timecodes
#                    HH:MM:SS,mmm with a comma, UTF-8 with LF endings
#                    and no byte-order mark, plain text with no
#                    override codes, positioning or markup, precisely
#                    so that it muxes cleanly as a caption track.
#
# Both are driven by playthrough/timeline.json, the single source of
# truth for pacing, so the cue windows already agree with the frame
# windows before this stage runs.  NOTHING IS RETIMED HERE.  This
# script adds no cue, drops none, shifts none and rewords none: the
# captions muxed are exactly the cues make_srt.py generated from
# exactly the frames that were captured.
#
# On the trust state: env.sh's bypass switches are asserted by the two
# stages that produce PRIMARY evidence -- launch_game.sh and
# capture.sh.  The derivation stages, this one included, do not repeat
# that gate; what they do instead is resolve every tool through
# playthrough_require_tools, which verifies ownership and writability
# of each binary it hands back and warns loudly when a bypass is in
# force.
# ---------------------------------------------------------------------

set -euo pipefail

# errtrace propagates the ERR trap into functions, so an unexpected
# failure reports its line number instead of vanishing.  A strict
# addition to `set -euo pipefail`, never a replacement for it.
set -o errtrace

# The handler is a function so the trap string stays trivial.
#
# SC2317 fires on every trap-invoked function here because ShellCheck
# does not model the trap as a call site.  The suppression is scoped to
# the two handlers that are genuinely only reached that way; env.sh and
# capture.sh carry the same directive for the same reason.
# shellcheck disable=SC2317
_ec_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "embed_captions.sh failed at line ${2} (exit ${1})" >&2
}
trap '_ec_on_error "$?" "${LINENO}"' ERR

# ---------------------------------------------------------------------
# Exit codes, named so the call sites read as intent.  Declared before
# anything else can fail, because the first two failures this file can
# suffer -- not finding itself, and not finding env.sh -- happen before
# any other definition exists.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_LAYOUT=2
readonly EX_INPUT=3
readonly EX_MUX=4
readonly EX_VERIFY=5
readonly EX_PREREQ=8

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment
# and the artifact layout.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8, as capture.sh and launch_game.sh
# also adopt it.
# ---------------------------------------------------------------------
_ec_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_ec_script_dir}" ]; then
    printf '%s\n' "embed_captions.sh: FATAL: cannot resolve my own \
directory" >&2
    exit "${EX_LAYOUT}"
fi

_ec_env_file="${_ec_script_dir}/env.sh"
if [ ! -f "${_ec_env_file}" ]; then
    printf '%s\n' "embed_captions.sh: FATAL: missing ${_ec_env_file}; \
the artifact layout and the tool verification live there and are never \
redefined here" >&2
    exit "${EX_LAYOUT}"
fi

# env.sh is the SINGLE definition of the artifact paths, the runtime
# directory, the screen geometry and the headless contract, and it
# defines the helpers used below: playthrough_log, playthrough_warn,
# playthrough_require_tools, playthrough_validate_int,
# playthrough_acquire_lock and playthrough_release_lock.  None of it is
# restated in this file.  This stage needs no display, but sourcing the
# one contract is what keeps any of these values from existing twice.
#
# The `source=` directive lets `shellcheck -x` follow env.sh and check
# every helper and variable used here against it.  SC1091 is suppressed
# only for a plain `shellcheck` run, which cannot follow a sourced file
# and would report the resolved path as unreadable; the file's presence
# is asserted immediately above, so nothing is hidden.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_ec_env_file}"; then
    printf '%s\n' "embed_captions.sh: FATAL: ${_ec_env_file} refused \
to load; fix the environment contract before muxing anything" >&2
    exit "${EX_LAYOUT}"
fi
unset _ec_script_dir _ec_env_file

# The working directory is the repository root, as it is for every
# stage of this pipeline: the asset roots and the userdir are resolved
# relative to the process working directory by the engine
# [src/path_info.cpp:105,129-136], and the paths this script reports are
# repository-relative, which is only correct from here.
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# THE CONTRACT, spelled as constants.
#
# Every one of these is a requirement rather than a preference, so each
# appears exactly once and is asserted rather than assumed.
# ---------------------------------------------------------------------

# The caption codec.  The only broadly supported subtitle codec inside
# MP4, and the reason the track is selectable instead of painted on.
readonly SUBTITLE_CODEC="mov_text"

# The ISO-639 code the track is tagged with, and the metadata key that
# carries it.  English only.
readonly SUBTITLE_LANGUAGE="eng"
readonly SUBTITLE_METADATA_KEY="-metadata:s:s:0"

# What ffprobe must report for the copied picture.  h264 is the codec
# name for the stream render_movie.py produced; the geometry is the X
# root this pipeline captures, straight from env.sh so the number is
# not written down twice.
readonly VIDEO_CODEC_EXPECTED="h264"
readonly VIDEO_WIDTH_EXPECTED="${PLAYTHROUGH_SCREEN_WIDTH}"
readonly VIDEO_HEIGHT_EXPECTED="${PLAYTHROUGH_SCREEN_HEIGHT}"

# The container extension both inputs and the output must carry.  Not
# pedantry: the muxer is chosen by extension, and mov_text exists only
# in MP4.
readonly MOVIE_SUFFIX=".mp4"

# The cue separator, exactly as make_srt.py writes it -- one space on
# each side of the arrow.  Counting cues means counting these.
readonly CUE_ARROW=" --> "

# The first line of a SubRip file: the first cue's sequence number.
readonly FIRST_CUE_NUMBER="1"

# A container smaller than this is a header and nothing else.  The
# smallest honest film here is one 1920x1080 keyframe of real screen
# content, which measures tens of kilobytes, so four kilobytes sits
# comfortably below anything legitimate and above a truncated write.
# The value is render_movie.py's MIN_OUTPUT_BYTES, deliberately.
readonly MIN_OUTPUT_BYTES=4096

# How far the output's video stream duration may differ from the
# input's.  A stream copy reproduces the sample durations exactly, so
# the honest answer is zero; a millisecond of slack absorbs the
# hundredth-of-a-second formatting ffprobe prints and nothing more.  A
# re-encode or a burned-in overlay would miss by far more than this,
# and the stream-hash check below catches both regardless.
readonly DURATION_EPSILON="0.001"

# ffprobe's plain KEY=value form, and its bare-value form.  Parsed by
# key rather than by position, because ffprobe prints the fields in its
# own order and not in the order they were asked for.
readonly PROBE_KEYED="default=nw=1"
readonly PROBE_BARE="default=noprint_wrappers=1:nokey=1"

# What ffprobe prints for a field the container does not carry.
readonly PROBE_ABSENT="N/A"

# `timeout` reports this when it fires, which is how an expiry is told
# apart from the tool's own failure.
readonly TIMEOUT_EXPIRED=124

# ---------------------------------------------------------------------
# STAGE TIMEOUT.  Every external command here gets a ceiling.
#
# Three of the calls below read the whole video stream: the mux, the
# stream hash and the cue extraction.  A wedged ffmpeg would otherwise
# hang the pipeline sequencer indefinitely with nothing written and
# nothing reported, which is the one failure mode worse than an error.
# The default is a generous multiple of what a stream copy of a
# feature-length capture takes, so an expiry here always means
# something is wrong rather than slow.
# ---------------------------------------------------------------------
readonly DEFAULT_STAGE_TIMEOUT=900

if ! playthrough_validate_int \
        "${PLAYTHROUGH_CAPTION_TIMEOUT:-${DEFAULT_STAGE_TIMEOUT}}" \
        "PLAYTHROUGH_CAPTION_TIMEOUT" 1 86400; then
    exit "${EX_USAGE}"
fi
readonly STAGE_TIMEOUT="${PLAYTHROUGH_INT}"

# How long to wait for another run of this stage to finish before
# giving up.  Two muxes writing one output would race over the same
# staging file, so they are serialised rather than allowed to
# interleave.
readonly DEFAULT_LOCK_TIMEOUT=60

if ! playthrough_validate_int \
        "${PLAYTHROUGH_CAPTION_LOCK_TIMEOUT:-${DEFAULT_LOCK_TIMEOUT}}" \
        "PLAYTHROUGH_CAPTION_LOCK_TIMEOUT" 0 86400; then
    exit "${EX_USAGE}"
fi
readonly LOCK_TIMEOUT="${PLAYTHROUGH_INT}"

# ---------------------------------------------------------------------
# Reporting.  Prose goes to stderr; stdout carries KEY=value only.
# ---------------------------------------------------------------------

# die CODE MESSAGE...
#   Report and stop.  The message always names the offending path or
#   value, because a refusal that does not say what to fix is only half
#   a diagnosis.
die() {
    local code="$1"
    shift
    playthrough_die "embed_captions.sh: $*" || true
    exit "${code}"
}

# note KEY VALUE
#   One field of the machine-readable summary.
note() {
    printf '%s=%s\n' "$1" "$2"
}

# rel PATH
#   PATH spelled relative to the repository root when it lies inside
#   it, so the summary reads as playthrough/cata-play-cc.mp4 rather
#   than as an absolute path nobody can compare against the
#   requirement.  Anything outside the checkout is reported as given.
rel() {
    local path="$1"
    case "${path}" in
        "${PLAYTHROUGH_REPO_ROOT}"/*)
            printf '%s' "${path#"${PLAYTHROUGH_REPO_ROOT}"/}"
            ;;
        *) printf '%s' "${path}" ;;
    esac
}

usage() {
    # The one place this file writes prose to stdout, and only when
    # asked for help.
    cat <<'USAGE'
embed_captions.sh -- mux the transcript into the film as a SELECTABLE
mov_text closed-caption track.  The picture is stream-copied; nothing
is ever drawn into the pixels.

usage:
    playthrough/tooling/embed_captions.sh
    playthrough/tooling/embed_captions.sh IN.mp4 IN.srt OUT.mp4
    playthrough/tooling/embed_captions.sh --help

With no arguments the paths are env.sh's:

    playthrough/cata-play.mp4  +  playthrough/transcript.srt
        ->  playthrough/cata-play-cc.mp4

All three positionals are optional and are taken in that order; give
the earlier ones to reach a later one.  They change only WHICH files
are read and written.  The caption codec, its language tag and the
stream copy of the picture are the requirement and cannot be altered
from the command line or the environment.

The output is written to a staging file, verified, and only then
renamed into place, so exit 0 means a container carrying a mov_text
track tagged eng is at the output path -- and a failed run leaves the
working tree exactly as it was found.

Prints KEY=value lines on stdout; the two verbatim ffprobe readouts,
warnings and diagnostics go to stderr.  See the header of this file for
the full output contract and the exit codes.

environment:
    PLAYTHROUGH_CAPTION_TIMEOUT       seconds allowed per external
                                      command (default 900)
    PLAYTHROUGH_CAPTION_LOCK_TIMEOUT  seconds to wait for a concurrent
                                      run of this stage (default 60)
USAGE
}

# ---------------------------------------------------------------------
# Argument parsing.
#
# Options are recognised only before the positionals, and the only
# option is --help: there is deliberately nothing to switch on.  An
# unrecognised argument is refused rather than ignored, because an
# ignored flag is an operator who believes something happened that did
# not.
# ---------------------------------------------------------------------
INPUT_MOVIE=""
INPUT_SRT=""
OUTPUT_MOVIE=""

_ec_positional=0
# One option exists, so this loop takes at most one turn today.  It is
# written as a loop rather than as a test on $1 because that is the
# shape that stays correct if a second option is ever added, and
# because it is where `--` is honoured -- the only way to name a file
# that genuinely begins with a dash.
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit "${EX_OK}"
            ;;
        --)
            shift
            break
            ;;
        -*)
            printf '%s\n' "embed_captions.sh: unknown option '$1'" >&2
            usage >&2
            exit "${EX_USAGE}"
            ;;
        *)
            break
            ;;
    esac
done

for _ec_arg in "$@"; do
    # Arithmetic on a counter this script initialised to zero itself.
    # env.sh's warning about arithmetic expansion applies to values
    # that came from the environment, where the substitution inside an
    # expansion would be executed rather than counted; every value the
    # environment supplies to this file goes through
    # playthrough_validate_int first.
    _ec_positional=$((_ec_positional + 1))
    case "${_ec_positional}" in
        1) INPUT_MOVIE="${_ec_arg}" ;;
        2) INPUT_SRT="${_ec_arg}" ;;
        3) OUTPUT_MOVIE="${_ec_arg}" ;;
        *)
            printf '%s\n' "embed_captions.sh: too many arguments \
(expected at most three: IN.mp4 IN.srt OUT.mp4), starting at \
'${_ec_arg}'" >&2
            exit "${EX_USAGE}"
            ;;
    esac
done
unset _ec_arg _ec_positional

# The defaults are env.sh's exported paths, which ARE
# playthrough/cata-play.mp4, playthrough/transcript.srt and
# playthrough/cata-play-cc.mp4 -- absolute here so that nothing depends
# on a caller's working directory, and reported relative below.
INPUT_MOVIE="${INPUT_MOVIE:-${PLAYTHROUGH_MOVIE}}"
INPUT_SRT="${INPUT_SRT:-${PLAYTHROUGH_TRANSCRIPT_SRT}}"
OUTPUT_MOVIE="${OUTPUT_MOVIE:-${PLAYTHROUGH_MOVIE_CC}}"
readonly INPUT_MOVIE INPUT_SRT OUTPUT_MOVIE

# ---------------------------------------------------------------------
# Path shape, checked before anything is handed to ffmpeg.
#
# ffmpeg has no end-of-options marker, so a path that begins with a
# dash would be read as a flag, and a path whose first component
# contains a colon would be read as a protocol -- "C:/x" and
# "http:/x" alike.  Both are refused here with an explanation, rather
# than producing an ffmpeg error about something the operator never
# asked for.  An input path can be passed as an option value with -i,
# but an output path is positional and has no such shelter, so all
# three are held to the same rule.
# ---------------------------------------------------------------------
assert_path_shape() {
    local path="$1" label="$2"
    if [ -z "${path}" ]; then
        die "${EX_USAGE}" "the ${label} path is empty"
    fi
    case "${path}" in
        -*)
            die "${EX_USAGE}" "the ${label} path '${path}' begins" \
                "with '-', which ffmpeg would read as an option." \
                "If an option was meant, it has to come before the" \
                "paths; if a file really is named this way, pass it" \
                "as './${path}' or as an absolute path."
            ;;
    esac
    # A colon anywhere before the first slash makes the leading text
    # look like a protocol specifier to ffmpeg.
    case "${path%%/*}" in
        *:*)
            die "${EX_USAGE}" "the ${label} path '${path}' has a" \
                "colon in its first component, which ffmpeg would" \
                "read as a protocol rather than a file name.  Pass" \
                "it as './${path}' or as an absolute path."
            ;;
    esac
    case "${path}" in
        *$'\n'*)
            die "${EX_USAGE}" "the ${label} path contains a newline;" \
                "refused, because the machine-readable summary is one" \
                "field per line"
            ;;
    esac
}

assert_path_shape "${INPUT_MOVIE}" "input film"
assert_path_shape "${INPUT_SRT}" "cue file"
assert_path_shape "${OUTPUT_MOVIE}" "output"

# ---------------------------------------------------------------------
# PREREQUISITES.
#
# playthrough_require_tools reports every missing tool at once with the
# package that ships it, and hands back a VERIFIED absolute path in
# PLAYTHROUGH_BIN_<NAME> for each one that passes -- ownership and
# writability checked on the binary and on every directory above it.
# Those paths are what get invoked below, rather than a bare name
# re-searched on PATH at the point of use.
#
# ffmpeg muxes and extracts, ffprobe measures, grep counts cues, awk
# compares two decimal durations (the shell has no floating point), wc
# sizes a file through a redirection rather than by argument, and mv
# publishes the verified container.
# ---------------------------------------------------------------------
if ! playthrough_require_tools ffmpeg ffprobe grep awk wc mv rm \
        timeout; then
    exit "${EX_PREREQ}"
fi

readonly FFMPEG="${PLAYTHROUGH_BIN_FFMPEG}"
readonly FFPROBE="${PLAYTHROUGH_BIN_FFPROBE}"
readonly GREP="${PLAYTHROUGH_BIN_GREP}"
readonly AWK="${PLAYTHROUGH_BIN_AWK}"
readonly WC="${PLAYTHROUGH_BIN_WC}"
readonly MV="${PLAYTHROUGH_BIN_MV}"
readonly RM="${PLAYTHROUGH_BIN_RM}"
readonly TIMEOUT="${PLAYTHROUGH_BIN_TIMEOUT}"

# run_bounded LABEL COMMAND...
#   Run one external command under the stage ceiling, reporting an
#   expiry as an expiry.  stderr is deliberately NOT captured or
#   silenced anywhere in this file: when ffmpeg refuses something, its
#   own message is the most useful thing an operator can be shown, and
#   swallowing it to print a tidier one would cost the diagnosis.
run_bounded() {
    local label="$1"
    shift
    local status=0
    "${TIMEOUT}" "${STAGE_TIMEOUT}" "$@" || status="$?"
    if [ "${status}" -eq "${TIMEOUT_EXPIRED}" ]; then
        playthrough_warn "${label} did not finish within" \
            "${STAGE_TIMEOUT}s and was stopped.  Raise" \
            "PLAYTHROUGH_CAPTION_TIMEOUT if this film is genuinely" \
            "that long, and look for a wedged tool if it is not."
    fi
    return "${status}"
}

# ---------------------------------------------------------------------
# THE INPUTS.  Both must exist, both must be non-empty, and the cue
# file must actually look like SubRip before anything is muxed.
#
# The alternative is worse than an error: ffmpeg will happily produce a
# container from an empty cue file, exit 0, and leave a film whose
# caption track carries nothing.  That passes a file-exists check and
# fails the requirement.
# ---------------------------------------------------------------------

# assert_readable_file PATH LABEL PRODUCER
#   Present, a regular file, non-empty and readable -- named, with the
#   stage that was meant to have produced it.
assert_readable_file() {
    local path="$1" label="$2" producer="$3"
    if [ ! -e "${path}" ]; then
        die "${EX_INPUT}" "the ${label} is missing:" \
            "$(rel "${path}").  Run ${producer} first."
    fi
    if [ -d "${path}" ]; then
        die "${EX_INPUT}" "the ${label} $(rel "${path}") is a" \
            "directory, not a file"
    fi
    if [ ! -f "${path}" ]; then
        die "${EX_INPUT}" "the ${label} $(rel "${path}") is not a" \
            "regular file"
    fi
    if [ ! -r "${path}" ]; then
        die "${EX_INPUT}" "the ${label} $(rel "${path}") is not" \
            "readable"
    fi
    if [ ! -s "${path}" ]; then
        die "${EX_INPUT}" "the ${label} $(rel "${path}") is empty." \
            "Run ${producer} first; an empty input would mux into a" \
            "container that looks finished and carries nothing."
    fi
}

assert_readable_file "${INPUT_MOVIE}" "input film" \
    "playthrough/tooling/render_movie.py"
assert_readable_file "${INPUT_SRT}" "cue file" \
    "playthrough/tooling/make_srt.py"

# The extension decides the muxer, and mov_text exists only in MP4, so
# an input or an output that is not .mp4 is refused here rather than
# discovered as a puzzling ffmpeg failure later.
assert_mp4_suffix() {
    local path="$1" label="$2"
    case "${path}" in
        *"${MOVIE_SUFFIX}") return 0 ;;
    esac
    die "${EX_USAGE}" "the ${label} $(rel "${path}") must name a" \
        "${MOVIE_SUFFIX} file: the container format is chosen by" \
        "extension and the ${SUBTITLE_CODEC} caption track is an MP4" \
        "feature."
}

assert_mp4_suffix "${INPUT_MOVIE}" "input film"
assert_mp4_suffix "${OUTPUT_MOVIE}" "output"

if [ "${INPUT_MOVIE}" = "${OUTPUT_MOVIE}" ]; then
    die "${EX_USAGE}" "the input film and the output are the same" \
        "path ($(rel "${INPUT_MOVIE}")).  ffmpeg cannot read and" \
        "write one file at once, and the base render is evidence:" \
        "it is never overwritten by its own captioned copy."
fi

# ---------------------------------------------------------------------
# THE CUE FILE'S SHAPE.
#
# Two checks, both of which catch a real and otherwise silent failure:
#
#   * The first line must be the first cue's sequence number.  A
#     byte-order mark sits in front of it and stops it matching --
#     which is exactly why make_srt.py writes UTF-8 WITHOUT one -- and
#     a truncated or half-written file fails here too.
#   * There must be at least one cue.  A file of prose with no timing
#     line would otherwise mux into an empty caption track.
# ---------------------------------------------------------------------
_ec_first_line=""
# `read` returns non-zero at end of file without a trailing newline,
# which is not a fault here: the line it read is still in the variable.
read -r _ec_first_line < "${INPUT_SRT}" || true

# Tolerate a CRLF cue file -- SubRip permits it and ffmpeg reads it --
# while still reporting it, because make_srt.py writes LF and a change
# of line ending in a committed artifact is worth knowing about.
if [ "${_ec_first_line}" != "${_ec_first_line%$'\r'}" ]; then
    playthrough_warn "$(rel "${INPUT_SRT}") has CRLF line endings;" \
        "make_srt.py writes LF.  The mux is unaffected, but a" \
        "committed cue file should not have changed line ending."
    _ec_first_line="${_ec_first_line%$'\r'}"
fi

if [ "${_ec_first_line}" != "${FIRST_CUE_NUMBER}" ]; then
    die "${EX_INPUT}" "$(rel "${INPUT_SRT}") does not begin with the" \
        "first cue's sequence number: expected a line reading" \
        "'${FIRST_CUE_NUMBER}', found '${_ec_first_line}'.  A" \
        "byte-order mark in front of it, or a truncated write, both" \
        "look like this.  Re-run make_srt.py."
fi
unset _ec_first_line

# grep exits 1 on no match, which is a legitimate answer here rather
# than an error, so the status is absorbed and the COUNT is what gets
# judged.
CUES_IN="$("${GREP}" -c -- "${CUE_ARROW}" "${INPUT_SRT}" || true)"
CUES_IN="${CUES_IN:-0}"
if ! playthrough_validate_int "${CUES_IN}" \
        "the cue count of $(rel "${INPUT_SRT}")" 0 1000000; then
    exit "${EX_INPUT}"
fi
readonly CUES_IN="${PLAYTHROUGH_INT}"

if [ "${CUES_IN}" -eq 0 ]; then
    die "${EX_INPUT}" "$(rel "${INPUT_SRT}") contains no cue: not one" \
        "'${CUE_ARROW}' timing line.  Muxing it would produce a" \
        "container with an empty caption track, which passes a" \
        "file-exists check and fails the requirement.  Re-run" \
        "make_srt.py."
fi

# ---------------------------------------------------------------------
# WHERE THE OUTPUT GOES.
#
# The parent directory must already exist: this stage publishes into a
# layout the pipeline owns, and quietly creating a directory tree
# because a path was mistyped would hide the mistake.
# ---------------------------------------------------------------------
# Split with parameter expansion rather than dirname/basename: the
# output path has already been proved to end in the container suffix,
# so there is no trailing slash to normalise, and two fewer external
# commands is two fewer things to verify before use.
if [ "${OUTPUT_MOVIE}" = "${OUTPUT_MOVIE#*/}" ]; then
    OUTPUT_DIR="."
else
    OUTPUT_DIR="${OUTPUT_MOVIE%/*}"
    # A path such as /cata.mp4 leaves an empty prefix, which is the
    # root directory rather than the current one.
    OUTPUT_DIR="${OUTPUT_DIR:-/}"
fi
OUTPUT_NAME="${OUTPUT_MOVIE##*/}"
readonly OUTPUT_DIR OUTPUT_NAME
if [ ! -d "${OUTPUT_DIR}" ]; then
    die "${EX_INPUT}" "the output directory $(rel "${OUTPUT_DIR}")" \
        "does not exist.  This stage publishes into an existing" \
        "layout rather than creating one."
fi
if [ ! -w "${OUTPUT_DIR}" ]; then
    die "${EX_INPUT}" "the output directory $(rel "${OUTPUT_DIR}")" \
        "is not writable"
fi
if [ -e "${OUTPUT_MOVIE}" ] && [ ! -f "${OUTPUT_MOVIE}" ]; then
    die "${EX_INPUT}" "the output path $(rel "${OUTPUT_MOVIE}")" \
        "exists and is not a regular file"
fi

# ---------------------------------------------------------------------
# SERIALISE.  Two runs of this stage over one checkout would race over
# the staging file and could publish a container assembled from two
# muxes.  The lock lives outside the working tree, is held by an open
# descriptor, and is released by the kernel even if this shell dies.
# ---------------------------------------------------------------------
if ! playthrough_acquire_lock captions "${LOCK_TIMEOUT}"; then
    exit "${EX_MUX}"
fi

# ---------------------------------------------------------------------
# THE STAGING FILE and the scratch cue file.
#
# The staging file is a sibling of the output, so the publish is a
# rename within one directory and therefore atomic.  Its name is
# deterministic rather than random: a run killed outright cannot run
# its own cleanup, and a fixed name means the NEXT run removes the
# leftover instead of accumulating one per attempt.  The lock above is
# what makes a fixed name safe.
#
# IT KEEPS THE CONTAINER SUFFIX, and that is not cosmetic: ffmpeg
# chooses the muxer from the extension, and a staging name ending in
# anything else fails with "Unable to choose an output format" --
# measured, before this was named the way it is.  Naming the format on
# the command line instead would mean adding an argument to a recipe
# that is a requirement, so the file is named to suit the recipe rather
# than the other way round.
#
# The scratch cue file goes under the pipeline's private runtime
# directory -- 0700, verified by env.sh, outside the working tree --
# because it is a diagnostic intermediate and the terminal
# `!/playthrough/**` negation in .gitignore would otherwise make it
# committable.
# ---------------------------------------------------------------------
STAGING_FILE="${OUTPUT_DIR}/.${OUTPUT_NAME%"${MOVIE_SUFFIX}"}\
.staging${MOVIE_SUFFIX}"
readonly STAGING_FILE
ROUND_TRIP_SRT="${PLAYTHROUGH_RUNTIME_DIR}/captions-round-trip.$$.srt"
readonly ROUND_TRIP_SRT

# Reached only from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
_ec_cleanup() {
    # `|| true` throughout: this runs while an exit status is already
    # being carried out, and a failure to tidy must not replace the
    # status that explains what actually went wrong.
    if [ -n "${STAGING_FILE}" ] && [ -e "${STAGING_FILE}" ]; then
        "${RM}" -f -- "${STAGING_FILE}" || true
    fi
    if [ -n "${ROUND_TRIP_SRT}" ] && [ -e "${ROUND_TRIP_SRT}" ]; then
        "${RM}" -f -- "${ROUND_TRIP_SRT}" || true
    fi
    # The descriptor is passed explicitly rather than left to the
    # helper's default, so nothing here depends on this script's own
    # positional parameters reaching it.
    playthrough_release_lock "${PLAYTHROUGH_LOCK_FD:-}" || true
}
trap _ec_cleanup EXIT

if [ -e "${STAGING_FILE}" ]; then
    if [ -d "${STAGING_FILE}" ]; then
        die "${EX_INPUT}" "the staging path" \
            "$(rel "${STAGING_FILE}") is a directory; remove it"
    fi
    playthrough_log "removing a staging file left by an earlier run:" \
        "$(rel "${STAGING_FILE}")"
    "${RM}" -f -- "${STAGING_FILE}"
fi

# ---------------------------------------------------------------------
# THE MUX.
#
# An argument LIST, never a string and never a shell.  That is the
# repository's CodeQL python-leg discipline applied to its shell too
# [.github/workflows/codeql-analysis.yml:35], and it means a path
# containing a space, a quote or a semicolon cannot change what runs.
#
# Read this list against the requirement: overwrite, errors only, the
# film, the cues, copy every stream, override only the subtitle codec,
# tag the language, write the staging file.  There is nothing else in
# it -- no filter of any kind, no video encoder, no scaling, no frame
# rate, no metadata beyond the language tag, and no audio, because
# neither input has any.  `-v error` is the only addition to the
# recipe, and it only silences progress chatter: ffmpeg's own errors
# still reach stderr, which is the whole reason nothing here captures
# or discards them.
# ---------------------------------------------------------------------
MUX_ARGS=(
    -y -v error
    -i "${INPUT_MOVIE}"
    -i "${INPUT_SRT}"
    -c copy
    -c:s "${SUBTITLE_CODEC}"
    "${SUBTITLE_METADATA_KEY}" "language=${SUBTITLE_LANGUAGE}"
    "${STAGING_FILE}"
)
readonly MUX_ARGS

# ---------------------------------------------------------------------
# THE COMMAND IS CHECKED AGAINST THE REQUIREMENT BEFORE IT RUNS.
#
# The recipe is not a default this file may drift away from, so the
# argument list assembled above is held to it rather than trusted:
#
#   * the three mandated flag groups must be present, and they are
#     matched as the literal text they have to be -- so a change to any
#     constant that spelled one of them differently would be caught
#     here instead of producing a container that fails verification
#     twenty seconds later;
#   * the element count must be exactly this, which is what makes
#     "there is nothing else in this command" a CHECKED FACT rather
#     than a promise in a comment.  A filter, an encoder, a scale or a
#     mapping could not be added without changing it.
# ---------------------------------------------------------------------
readonly MUX_ARG_COUNT=14

assert_recipe_contains() {
    local needle="$1"
    case " ${MUX_ARGS[*]} " in
        *" ${needle} "*) return 0 ;;
    esac
    die "${EX_VERIFY}" "the mux command does not carry '${needle}'," \
        "which the requirement specifies.  Refusing to run a recipe" \
        "that is not the one this feature was accepted on."
}

assert_recipe_contains "-c copy"
assert_recipe_contains "-c:s mov_text"
assert_recipe_contains "-metadata:s:s:0 language=eng"

if [ "${#MUX_ARGS[@]}" -ne "${MUX_ARG_COUNT}" ]; then
    die "${EX_VERIFY}" "the mux command has ${#MUX_ARGS[@]}" \
        "arguments and must have exactly ${MUX_ARG_COUNT}.  Something" \
        "was added to it, and the one thing this stage must never add" \
        "is anything that touches the picture."
fi

playthrough_log "muxing $(rel "${INPUT_SRT}") (${CUES_IN} cues) into" \
    "$(rel "${INPUT_MOVIE}") as a selectable ${SUBTITLE_CODEC} track"

_ec_mux_status=0
run_bounded "the caption mux" "${FFMPEG}" "${MUX_ARGS[@]}" ||
    _ec_mux_status="$?"

if [ "${_ec_mux_status}" -ne 0 ]; then
    die "${EX_MUX}" "ffmpeg exited ${_ec_mux_status} muxing" \
        "$(rel "${INPUT_SRT}") into $(rel "${INPUT_MOVIE}").  Its own" \
        "message is above.  Nothing was published."
fi
unset _ec_mux_status

if [ ! -s "${STAGING_FILE}" ]; then
    die "${EX_MUX}" "ffmpeg reported success but wrote nothing to" \
        "$(rel "${STAGING_FILE}")"
fi

# ---------------------------------------------------------------------
# PROBING.  Small helpers so that every measurement below reads as the
# question it is asking.
#
# Fields are read ONE AT A TIME in ffprobe's bare form, because the
# keyed form prints fields in ffprobe's own order rather than the order
# they were requested in -- parsing that by position is a defect
# waiting for a version bump.  Input files are passed with -i so that
# not even a path this script has already refused could be read as an
# option.
# ---------------------------------------------------------------------

# probe_one FILE STREAM_SPEC FIELD
#   One stream field, bare.  Prints the first line only, so a spec that
#   matched several streams cannot silently return two values.
probe_one() {
    local file="$1" spec="$2" field="$3" out
    out="$("${FFPROBE}" -v error -select_streams "${spec}" \
        -show_entries "stream=${field}" -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# probe_tag FILE STREAM_SPEC TAG
#   One stream metadata tag, bare.
probe_tag() {
    local file="$1" spec="$2" tag="$3" out
    out="$("${FFPROBE}" -v error -select_streams "${spec}" \
        -show_entries "stream_tags=${tag}" -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# probe_container_duration FILE
probe_container_duration() {
    local file="$1" out
    out="$("${FFPROBE}" -v error -show_entries format=duration \
        -of "${PROBE_BARE}" -i "${file}")" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# count_streams FILE STREAM_SPEC
#   How many streams the spec matches.  One index line per stream, so
#   the answer is the line count -- and zero when nothing matched.
count_streams() {
    local file="$1" spec="$2" out count
    out="$("${FFPROBE}" -v error -select_streams "${spec}" \
        -show_entries stream=index -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    if [ -z "${out}" ]; then
        printf '0'
        return 0
    fi
    count="$(printf '%s\n' "${out}" | "${WC}" -l)"
    printf '%s' "${count//[[:space:]]/}"
}

# is_number VALUE
#   True for a decimal ffprobe actually measured, false for an absent
#   field.  The float comparisons below must never be handed 'N/A':
#   awk would read it as zero and quietly report a match.
is_number() {
    case "${1-}" in
        ''|"${PROBE_ABSENT}") return 1 ;;
        *[!0-9.]*) return 1 ;;
        *) return 0 ;;
    esac
}

# floats_close A B EPSILON
#   |A - B| <= EPSILON.  The shell has no floating point, so awk does
#   the arithmetic -- as a program with the values passed in through -v,
#   never as a string with the values pasted into it.
floats_close() {
    "${AWK}" -v a="$1" -v b="$2" -v eps="$3" 'BEGIN {
        d = a - b
        if (d < 0) { d = -d }
        exit (d <= eps) ? 0 : 1
    }'
}

# float_exceeds A B MARGIN
#   A > B + MARGIN.
float_exceeds() {
    "${AWK}" -v a="$1" -v b="$2" -v margin="$3" 'BEGIN {
        exit (a > b + margin) ? 0 : 1
    }'
}

# video_frames FILE
#   The video stream's frame count.  MP4 carries it in the header; the
#   packet count is the fallback for a container that does not, and it
#   is bounded because it demuxes the whole stream.
video_frames() {
    local file="$1" value
    value="$(probe_one "${file}" v:0 nb_frames)" || return 1
    if is_number "${value}"; then
        printf '%s' "${value}"
        return 0
    fi
    value="$(run_bounded "the video packet count" \
        "${FFPROBE}" -v error -select_streams v:0 -count_packets \
        -show_entries stream=nb_read_packets -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    printf '%s' "${value%%$'\n'*}"
}

# video_stream_hash FILE
#   An MD5 over the video stream's copied packets.  This is the
#   strongest available proof that the picture came through the mux
#   untouched: a re-encode changes every packet, and text drawn into
#   the picture would have to be encoded, so both fail it.  The stream
#   is copied rather than decoded, so this is a read of the file and
#   not a decode of the film.
video_stream_hash() {
    local file="$1" out
    out="$(run_bounded "the video stream hash" \
        "${FFMPEG}" -v error -i "${file}" -map 0:v:0 -c copy \
        -f streamhash -hash md5 -)" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# ---------------------------------------------------------------------
# VERIFICATION.  Nothing is published until every one of these passes.
#
# The checks run against the STAGING file, so a container that fails
# one is never renamed into place.  An operator who wants to look at a
# rejected mux will not find it in the working tree -- and that is the
# point: an unverified container beside a verified one is worse than no
# container at all.
# ---------------------------------------------------------------------

OUTPUT_BYTES="$("${WC}" -c < "${STAGING_FILE}")"
OUTPUT_BYTES="${OUTPUT_BYTES//[[:space:]]/}"
readonly OUTPUT_BYTES
if [ "${OUTPUT_BYTES}" -lt "${MIN_OUTPUT_BYTES}" ]; then
    die "${EX_VERIFY}" "the muxed container is only" \
        "${OUTPUT_BYTES} bytes, below the ${MIN_OUTPUT_BYTES}-byte" \
        "floor that a single 1920x1080 keyframe of real screen" \
        "content already clears.  That is a header, not a film."
fi

# --- the picture ------------------------------------------------------
#
# Exactly one video stream, the codec the acceptance gate names, at the
# geometry this pipeline captures.  A missing or second video stream
# would mean the default stream selection did something other than what
# is documented.
_ec_video_streams="$(count_streams "${STAGING_FILE}" v)" ||
    die "${EX_VERIFY}" "ffprobe could not read the streams of the" \
        "muxed container"
if [ "${_ec_video_streams}" != "1" ]; then
    die "${EX_VERIFY}" "the muxed container carries" \
        "${_ec_video_streams} video streams; exactly one is" \
        "required.  The picture must survive the mux and nothing may" \
        "be added beside it."
fi
unset _ec_video_streams

VIDEO_CODEC="$(probe_one "${STAGING_FILE}" v:0 codec_name)"
VIDEO_WIDTH="$(probe_one "${STAGING_FILE}" v:0 width)"
VIDEO_HEIGHT="$(probe_one "${STAGING_FILE}" v:0 height)"
readonly VIDEO_CODEC VIDEO_WIDTH VIDEO_HEIGHT

if [ "${VIDEO_CODEC}" != "${VIDEO_CODEC_EXPECTED}" ]; then
    die "${EX_VERIFY}" "the muxed container's video codec is" \
        "'${VIDEO_CODEC}', not '${VIDEO_CODEC_EXPECTED}'.  The" \
        "picture was supposed to be copied, so the codec cannot have" \
        "changed."
fi
if [ "${VIDEO_WIDTH}" != "${VIDEO_WIDTH_EXPECTED}" ] ||
        [ "${VIDEO_HEIGHT}" != "${VIDEO_HEIGHT_EXPECTED}" ]; then
    die "${EX_VERIFY}" "the muxed container is" \
        "${VIDEO_WIDTH}x${VIDEO_HEIGHT}, not" \
        "${VIDEO_WIDTH_EXPECTED}x${VIDEO_HEIGHT_EXPECTED}.  The" \
        "capture resolution is the X root this pipeline photographs" \
        "and a copied stream cannot be a different size."
fi

# --- the caption track ------------------------------------------------
#
# THIS IS THE CHECK THE WHOLE REQUIREMENT RESTS ON.  ffmpeg can exit 0
# having produced a container whose subtitle stream was dropped by
# stream selection, and a file-exists check would call that a success.
_ec_subtitle_streams="$(count_streams "${STAGING_FILE}" s)" ||
    die "${EX_VERIFY}" "ffprobe could not read the subtitle streams" \
        "of the muxed container"
if [ "${_ec_subtitle_streams}" = "0" ]; then
    die "${EX_VERIFY}" "the muxed container carries NO subtitle" \
        "stream.  ffmpeg reported success, so this would have passed" \
        "any check that only asked whether the file exists.  The" \
        "captions are the requirement; nothing was published."
fi
if [ "${_ec_subtitle_streams}" != "1" ]; then
    die "${EX_VERIFY}" "the muxed container carries" \
        "${_ec_subtitle_streams} subtitle streams; exactly one is" \
        "required.  The track is English only."
fi
unset _ec_subtitle_streams

SUBTITLE_INDEX="$(probe_one "${STAGING_FILE}" s:0 index)"
SUBTITLE_CODEC_FOUND="$(probe_one "${STAGING_FILE}" s:0 codec_name)"
SUBTITLE_LANGUAGE_FOUND="$(probe_tag "${STAGING_FILE}" s:0 language)"
SUBTITLE_DURATION="$(probe_one "${STAGING_FILE}" s:0 duration)"
readonly SUBTITLE_INDEX SUBTITLE_CODEC_FOUND SUBTITLE_LANGUAGE_FOUND
readonly SUBTITLE_DURATION

if [ "${SUBTITLE_CODEC_FOUND}" != "${SUBTITLE_CODEC}" ]; then
    die "${EX_VERIFY}" "the caption track's codec is" \
        "'${SUBTITLE_CODEC_FOUND}', not '${SUBTITLE_CODEC}'." \
        "${SUBTITLE_CODEC} is the only broadly supported subtitle" \
        "codec inside MP4 and the one that makes the track" \
        "selectable rather than part of the picture."
fi
if [ "${SUBTITLE_LANGUAGE_FOUND}" != "${SUBTITLE_LANGUAGE}" ]; then
    die "${EX_VERIFY}" "the caption track's language tag is" \
        "'${SUBTITLE_LANGUAGE_FOUND}', not '${SUBTITLE_LANGUAGE}'." \
        "Without the ISO-639 code a player cannot list the track as" \
        "English."
fi

# --- the picture came through UNTOUCHED -------------------------------
#
# Three independent measurements, and at least one of them must be
# available or the copy cannot be called proven.  Their point is not
# redundancy for its own sake: a re-encode and text drawn into the
# picture are the two ways this stage could quietly ruin the evidence,
# and each of these catches both.
#
#   the stream hash   MD5 over the video stream's packets.  Equal
#                     hashes mean the picture is byte-for-byte the
#                     render that was measured non-blank.  The
#                     strongest proof and the one to prefer.
#   the duration      a copy reproduces the sample durations exactly.
#   the frame count   and it reproduces the sample count exactly.
IN_VIDEO_DURATION="$(probe_one "${INPUT_MOVIE}" v:0 duration)"
OUT_VIDEO_DURATION="$(probe_one "${STAGING_FILE}" v:0 duration)"
IN_VIDEO_FRAMES="$(video_frames "${INPUT_MOVIE}")"
OUT_VIDEO_FRAMES="$(video_frames "${STAGING_FILE}")"
readonly IN_VIDEO_DURATION OUT_VIDEO_DURATION
readonly IN_VIDEO_FRAMES OUT_VIDEO_FRAMES

VIDEO_COPY_PROOF=""

# The streamhash muxer is old and universal, but it is a build option
# rather than a guarantee, so its absence is reported and the weaker
# proofs stand.  Availability is probed from the muxer list, because
# `ffmpeg -h muxer=<name>` exits 0 for a name that does not exist.
if "${FFMPEG}" -hide_banner -muxers 2>/dev/null |
        "${GREP}" -qE '(^|[[:space:]])streamhash([[:space:]]|$)'; then
    _ec_hash_in="$(video_stream_hash "${INPUT_MOVIE}")" ||
        die "${EX_VERIFY}" "could not hash the video stream of" \
            "$(rel "${INPUT_MOVIE}")"
    _ec_hash_out="$(video_stream_hash "${STAGING_FILE}")" ||
        die "${EX_VERIFY}" "could not hash the video stream of the" \
            "muxed container"
    if [ -z "${_ec_hash_in}" ] || [ -z "${_ec_hash_out}" ]; then
        die "${EX_VERIFY}" "the video stream hash came back empty," \
            "so the stream copy cannot be confirmed"
    fi
    if [ "${_ec_hash_in}" != "${_ec_hash_out}" ]; then
        die "${EX_VERIFY}" "THE PICTURE CHANGED.  The video stream" \
            "hash of $(rel "${INPUT_MOVIE}") is '${_ec_hash_in}' and" \
            "the muxed container's is '${_ec_hash_out}'.  A caption" \
            "mux copies the picture; a different hash means it was" \
            "re-encoded or something was drawn into it, and either" \
            "destroys the evidence this film exists to carry." \
            "Nothing was published."
    fi
    playthrough_log "the video stream is byte-identical to" \
        "$(rel "${INPUT_MOVIE}") (${_ec_hash_out})"
    VIDEO_COPY_PROOF="stream-hash"
    unset _ec_hash_in _ec_hash_out
else
    playthrough_warn "this ffmpeg has no streamhash muxer, so the" \
        "byte-identity of the copied picture could not be measured;" \
        "the duration and frame-count comparisons below stand in its" \
        "place"
fi

_ec_duration_checked=0
if is_number "${IN_VIDEO_DURATION}" &&
        is_number "${OUT_VIDEO_DURATION}"; then
    if ! floats_close "${IN_VIDEO_DURATION}" "${OUT_VIDEO_DURATION}" \
            "${DURATION_EPSILON}"; then
        die "${EX_VERIFY}" "the video stream lasts" \
            "${OUT_VIDEO_DURATION}s in the muxed container but" \
            "${IN_VIDEO_DURATION}s in $(rel "${INPUT_MOVIE}").  A" \
            "stream copy reproduces the sample durations exactly, so" \
            "a difference means the picture was re-encoded.  Nothing" \
            "was published."
    fi
    _ec_duration_checked=1
fi

_ec_frames_checked=0
if is_number "${IN_VIDEO_FRAMES}" && is_number "${OUT_VIDEO_FRAMES}"; then
    if [ "${IN_VIDEO_FRAMES}" != "${OUT_VIDEO_FRAMES}" ]; then
        die "${EX_VERIFY}" "the muxed container holds" \
            "${OUT_VIDEO_FRAMES} video frames and" \
            "$(rel "${INPUT_MOVIE}") holds ${IN_VIDEO_FRAMES}.  A" \
            "stream copy reproduces the sample count exactly." \
            "Nothing was published."
    fi
    _ec_frames_checked=1
fi

if [ -z "${VIDEO_COPY_PROOF}" ]; then
    if [ "${_ec_duration_checked}" -eq 1 ] &&
            [ "${_ec_frames_checked}" -eq 1 ]; then
        VIDEO_COPY_PROOF="duration+frames"
    elif [ "${_ec_duration_checked}" -eq 1 ]; then
        VIDEO_COPY_PROOF="duration"
    elif [ "${_ec_frames_checked}" -eq 1 ]; then
        VIDEO_COPY_PROOF="frames"
    else
        die "${EX_VERIFY}" "none of the three measurements that show" \
            "the picture was copied rather than re-encoded could be" \
            "taken: no stream hash, no video stream duration and no" \
            "frame count.  An unverifiable film is not published."
    fi
fi
readonly VIDEO_COPY_PROOF
unset _ec_duration_checked _ec_frames_checked

# --- the cues survived ------------------------------------------------
#
# Read the captions back OUT of the container and count them.
#
# *** DO NOT COUNT SUBTITLE PACKETS INSTEAD ***  MP4 timed text has to
# cover the container contiguously, so the muxer pads the gaps this
# transcript leaves for the cinematic transitions with empty samples of
# its own.  Measured here: three cues with one gap between them come
# back as FOUR packets.  Counting packets would report a caption track
# that had gained cues nobody wrote.  The round trip counts CUES, and
# it also proves the track is readable rather than merely present.
if ! run_bounded "the cue round-trip" \
        "${FFMPEG}" -y -v error -i "${STAGING_FILE}" \
        -map 0:s:0 -c:s srt -f srt "${ROUND_TRIP_SRT}"; then
    die "${EX_VERIFY}" "the caption track could not be read back out" \
        "of the muxed container.  A track that cannot be extracted" \
        "cannot be displayed either.  Nothing was published."
fi

CUES_ROUND_TRIP="$("${GREP}" -c -- "${CUE_ARROW}" \
    "${ROUND_TRIP_SRT}" || true)"
CUES_ROUND_TRIP="${CUES_ROUND_TRIP:-0}"
readonly CUES_ROUND_TRIP

if [ "${CUES_ROUND_TRIP}" != "${CUES_IN}" ]; then
    die "${EX_VERIFY}" "${CUES_IN} cues went in and" \
        "${CUES_ROUND_TRIP} came back out of the caption track." \
        "Every cue in $(rel "${INPUT_SRT}") is one captured frame's" \
        "commentary, so a caption track with a different number of" \
        "them is not this transcript.  Nothing was published."
fi

# The cue file is written from the same timeline the film is paced by,
# so its last cue should end inside the picture.  A track that runs
# past the end is an upstream disagreement between the timeline and the
# render rather than a fault in this mux, so it is reported loudly with
# both numbers and the film is still published -- misattributing an
# upstream drift to this stage would send an operator to the wrong
# file.  verify_artifacts.sh is where the container is held against the
# timeline total.
if is_number "${SUBTITLE_DURATION}" &&
        is_number "${OUT_VIDEO_DURATION}"; then
    if float_exceeds "${SUBTITLE_DURATION}" "${OUT_VIDEO_DURATION}" \
            "${DURATION_EPSILON}"; then
        playthrough_warn "the caption track runs to" \
            "${SUBTITLE_DURATION}s but the picture ends at" \
            "${OUT_VIDEO_DURATION}s, so the last cues fall past the" \
            "end of the film.  The mux is faithful to" \
            "$(rel "${INPUT_SRT}"); the disagreement is between the" \
            "timeline and the render, so re-run render_movie.py and" \
            "make_srt.py from the same playthrough/timeline.json."
    fi
fi

CONTAINER_DURATION="$(probe_container_duration "${STAGING_FILE}")"
readonly CONTAINER_DURATION

# ---------------------------------------------------------------------
# PUBLISH.  A rename inside one directory, so a reader sees either the
# previous film or this one.
# ---------------------------------------------------------------------
if ! "${MV}" -f -- "${STAGING_FILE}" "${OUTPUT_MOVIE}"; then
    die "${EX_VERIFY}" "could not publish the verified container to" \
        "$(rel "${OUTPUT_MOVIE}")"
fi

_ec_published_bytes="$("${WC}" -c < "${OUTPUT_MOVIE}")"
_ec_published_bytes="${_ec_published_bytes//[[:space:]]/}"
if [ "${_ec_published_bytes}" != "${OUTPUT_BYTES}" ]; then
    die "${EX_VERIFY}" "$(rel "${OUTPUT_MOVIE}") is" \
        "${_ec_published_bytes} bytes but the container that passed" \
        "verification was ${OUTPUT_BYTES}.  The published file is" \
        "left in place for inspection rather than deleted, because a" \
        "rename that changes a file's size is a fault in the" \
        "filesystem and not in this mux."
fi
unset _ec_published_bytes

# ---------------------------------------------------------------------
# THE EVIDENCE.  The two probe readouts the acceptance gate names, run
# verbatim against the PUBLISHED file and printed as they came back --
# so what is shown describes the artifact that shipped, not a claim
# about it.  They are re-asserted afterwards, which is what turns the
# rename above from an assumption into a checked step.
# ---------------------------------------------------------------------
SUBTITLE_READOUT="$("${FFPROBE}" -v error -select_streams s \
    -show_entries stream=index,codec_name:stream_tags=language \
    -of "${PROBE_KEYED}" -i "${OUTPUT_MOVIE}")"
VIDEO_READOUT="$("${FFPROBE}" -v error -select_streams v \
    -show_entries stream=codec_name,width,height \
    -of "${PROBE_KEYED}" -i "${OUTPUT_MOVIE}")"
readonly SUBTITLE_READOUT VIDEO_READOUT

{
    printf '%s\n' "--- ffprobe, caption stream(s) of \
$(rel "${OUTPUT_MOVIE}") ---"
    printf '%s\n' "${SUBTITLE_READOUT}"
    printf '%s\n' "--- ffprobe, video stream(s) of \
$(rel "${OUTPUT_MOVIE}") ---"
    printf '%s\n' "${VIDEO_READOUT}"
} >&2

assert_readout_contains() {
    local readout="$1" needle="$2" what="$3"
    case "${readout}" in
        *"${needle}"*) return 0 ;;
    esac
    die "${EX_VERIFY}" "the published $(rel "${OUTPUT_MOVIE}") does" \
        "not report ${what}: '${needle}' is absent from the ffprobe" \
        "readout above, although the container that was verified" \
        "before the rename did report it.  The file is left in place" \
        "for inspection rather than deleted: a rename that changes" \
        "what a container carries is a fault below this mux, and" \
        "deleting the evidence of it would help nobody."
}

assert_readout_contains "${SUBTITLE_READOUT}" \
    "codec_name=${SUBTITLE_CODEC}" "a ${SUBTITLE_CODEC} caption track"
assert_readout_contains "${SUBTITLE_READOUT}" \
    "TAG:language=${SUBTITLE_LANGUAGE}" \
    "the ${SUBTITLE_LANGUAGE} language tag"
assert_readout_contains "${VIDEO_READOUT}" \
    "codec_name=${VIDEO_CODEC_EXPECTED}" "an unchanged video codec"
assert_readout_contains "${VIDEO_READOUT}" \
    "width=${VIDEO_WIDTH_EXPECTED}" "the capture width"
assert_readout_contains "${VIDEO_READOUT}" \
    "height=${VIDEO_HEIGHT_EXPECTED}" "the capture height"

# ---------------------------------------------------------------------
# THE SUMMARY.  KEY=value, one per line, in the order the header
# documents, and nothing else on stdout.
# ---------------------------------------------------------------------
note INPUT_MOVIE "$(rel "${INPUT_MOVIE}")"
note INPUT_SRT "$(rel "${INPUT_SRT}")"
note OUTPUT_FILE "$(rel "${OUTPUT_MOVIE}")"
note OUTPUT_BYTES "${OUTPUT_BYTES}"
note VIDEO_CODEC "${VIDEO_CODEC}"
note VIDEO_WIDTH "${VIDEO_WIDTH}"
note VIDEO_HEIGHT "${VIDEO_HEIGHT}"
note VIDEO_DURATION "${OUT_VIDEO_DURATION}"
note VIDEO_FRAMES "${OUT_VIDEO_FRAMES}"
note VIDEO_COPY_PROOF "${VIDEO_COPY_PROOF}"
note SUBTITLE_INDEX "${SUBTITLE_INDEX}"
note SUBTITLE_CODEC "${SUBTITLE_CODEC_FOUND}"
note SUBTITLE_LANGUAGE "${SUBTITLE_LANGUAGE_FOUND}"
note SUBTITLE_DURATION "${SUBTITLE_DURATION}"
note CUES_IN "${CUES_IN}"
note CUES_ROUND_TRIP "${CUES_ROUND_TRIP}"
note CONTAINER_DURATION "${CONTAINER_DURATION}"

playthrough_log "wrote $(rel "${OUTPUT_MOVIE}") --" \
    "${OUTPUT_BYTES} bytes, ${VIDEO_CODEC}" \
    "${VIDEO_WIDTH}x${VIDEO_HEIGHT} copied intact" \
    "(${VIDEO_COPY_PROOF}), with ${CUES_ROUND_TRIP} cues on a" \
    "selectable ${SUBTITLE_CODEC_FOUND} track tagged" \
    "${SUBTITLE_LANGUAGE_FOUND}"

exit "${EX_OK}"

