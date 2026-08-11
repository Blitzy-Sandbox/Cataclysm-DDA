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
# Those three files are the only ones this stage will ever touch.  The
# positionals do NOT relocate them: each is resolved and must name the
# canonical artifact for its role, so a different spelling of the same
# file is accepted and a different file is refused (see WHICH FILES
# below).  They exist to let a caller state the paths explicitly and be
# told if it has them wrong.
#
# There is likewise no argument, and no environment variable, that can
# add a filter, re-encode the picture, burn text into it, drop the
# caption track's mapping, or change the caption codec or its language
# tag.  Those are the requirement, not a default.
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
# THREE FLAGS ARE ADDED TO THE SPECIFIED RECIPE, and each of them
# REMOVES a way for something unintended to travel into the artifact:
#
#   -map 0:v:0      Exactly the first input's first video stream and
#   -map 1:s:0      exactly the second input's first subtitle stream.
#                   The recipe relies on ffmpeg's DEFAULT selection,
#                   which picks the best stream of each type it finds --
#                   so a render that ever gained an audio, data or
#                   attachment stream would have it carried silently
#                   into a committed film.  This feature has no audio at
#                   all (SOUND_ENABLED=false, SDL_AUDIODRIVER=dummy), so
#                   anything of the kind is a fault to refuse rather
#                   than a stream to copy.  Naming both streams also
#                   makes the two `-map`s the only mapping in the
#                   command, which is what the assertions below hold it
#                   to; the stream census after the mux proves the
#                   result carries nothing else.
#
#   -map_metadata -1
#   -map_chapters -1
#                   Carry NO container metadata and NO chapters over
#                   from either input.  Without them ffmpeg copies the
#                   input's global tags, and the render's tags name the
#                   encoder and its version -- facts about the machine
#                   this ran on, travelling into an artifact that is
#                   committed to a public repository.  A whitelist of
#                   the tags the muxer legitimately writes for itself is
#                   enforced afterwards, and the chapter count is
#                   asserted to be zero.
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
# against the input's.  Burned-in text has to be encoded, so it changes
# the picture, and every one of the comparisons catches that -- but
# they are not equally strong, and the summary says which one was
# actually taken rather than letting a reader assume the best of them:
#
#   stream hash       a SHA-256 over the copied packets.  Equal hashes
#                     mean the picture is byte-identical.  This is the
#                     proof to want, and it is what this host takes.
#   duration + frames  the fallback where this ffmpeg was built without
#                     the streamhash muxer.  A re-encode that preserved
#                     both to the millisecond and the frame would pass
#                     it, which is why its absence is WARNED about
#                     rather than passed over silently.
#   neither            nothing is published.
#
# VIDEO_COPY_PROOF carries the answer, so "the picture was copied" is
# never a stronger claim than the measurement behind it.
#
# ---------------------------------------------------------------------
# WHAT THIS FILE READS AND WRITES
#
# Reads two files.  Writes exactly one path inside the working tree --
# the output container -- plus one dot-prefixed staging file beside it,
# and one scratch file under the pipeline's private runtime directory,
# outside the tree entirely.  The staging file is removed on every exit
# this script is able to run code on; a SIGKILL, a full disk or a
# permission fault can still leave it, which is why the start of a run
# removes a stale one rather than assuming there is none.  It touches no
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
#   * A failed run leaves nothing new in the working tree, because the
#     staging file is removed on the way out -- so the commit stage
#     cannot stage a truncated container that nobody authored.  A run
#     that is KILLED cannot run that cleanup, and the staging name is
#     then still there: dot-prefixed, never at the output path, and
#     removed by the next run before it writes.  What no interruption
#     can do is publish, because the output path is only ever reached
#     by a rename of a container that passed.
#   * A previously published, verified film is not destroyed by a
#     failed re-run.  It is replaced only by a film that passed.
#
# EVERY FALLIBLE CHECK HAPPENS BEFORE THE RENAME.  That is a correction,
# not a restatement: the byte-size comparison, both mandated probe
# readouts and the audio/data/attachment census all used to run AFTER the
# rename, against the published file, and each of them could exit
# non-zero.  So the canonical captioned MP4 -- a committed artifact -- was
# replaced first and interrogated second, and a failure left the
# unverified container in the working tree as the film while the previous
# one, which had passed every check, was already gone.
#
# After the rename there is now exactly ONE check, and it asks nothing
# about what the container holds: the sha256 of the published bytes
# against the sha256 of the bytes that were verified.  The previous film
# is copied aside first, so a mismatch RESTORES it and quarantines the
# file that failed rather than merely reporting the loss.
#
# ---------------------------------------------------------------------
# THE PROVENANCE GATE
#
# Length, cue count, codec and geometry can all agree between a film and
# a caption track that describe DIFFERENT sessions -- a re-record of the
# same opening, or a re-render of one session beside a transcript from
# another.  So before anything is muxed, this stage reads the generation
# manifests render_movie.py and make_srt.py publish beside their outputs,
# requires both to name the same playthrough/timeline.json BY THAT
# DOCUMENT'S OWN DIGEST, and requires each input to carry the digest its
# own manifest declares.  A missing manifest is a refusal: treating it as
# "nothing to check" would switch the gate off for exactly the older
# render it exists to catch.
#
# ---------------------------------------------------------------------
# THE EVIDENCE THIS SCRIPT PRINTS
#
# It does not claim the track is there; it shows the probe output that
# proves it, then exits on any assertion that fails.  The two mandated
# readouts are run verbatim against the container that is published and
# printed on stderr as they came back --
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
#     AUDIO_STREAMS        0, measured.  The film is silent by
#                          requirement, and the count is stated rather
#                          than left to be inferred from the absence
#                          of a complaint
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

# The container layout flag, spelled exactly as render_movie.py spells
# it (MOVFLAGS = "+faststart" there).  It puts the `moov` index in front
# of `mdat` so a player can start on its first request instead of
# fetching the tail first; see THE MUX below for the measurement that
# put it here.  That the flag TOOK EFFECT on the published container --
# rather than merely being asked for -- is asserted against the
# committed artifact by test_artifacts.py, which walks both films' top
# level atoms and requires `moov` before `mdat` in each.  It is checked
# there rather than here because the check has to read real container
# bytes, and this stage's own suite drives it against a stubbed ffmpeg.
readonly MOVFLAGS="+faststart"

# The container tags the published film may carry, and only these.
#
# WHY A WHITELIST RATHER THAN A CHECK FOR THE KNOWN BAD.  -map_metadata
# -1 drops what the inputs carried, but the MUXER still writes its own
# structural tags, and which ones it writes is a property of the ffmpeg
# build rather than of this script.  Measured on the input this pipeline
# produces, the inherited set was major_brand, minor_version,
# compatible_brands and encoder=Lavf61.7.100 -- so the encoder's name
# and version travelled into a committed artifact.  Enumerating what is
# ALLOWED means a tag a future ffmpeg starts adding is reported here
# instead of shipping unnoticed, which is the direction that stays
# correct as the tool changes.
#
# creation_time is deliberately NOT in this list.  A timestamp is a fact
# about the operator's clock rather than about the session, and it also
# makes the artifact non-reproducible: two identical renders would
# differ.
readonly ALLOWED_FORMAT_TAGS="major_brand minor_version \
compatible_brands encoder"

# The digest used to prove the picture came through the mux untouched.
# SHA-256, not MD5: MD5 is collision-broken and chosen-prefix collisions
# against it are cheap, so a matching MD5 was a statement about accident
# rather than about intent.  Named as a constant because the algorithm
# is REPORTED alongside every digest -- a bare hex string tells a later
# reader nothing about what produced it.
readonly STREAM_HASH_ALGORITHM="sha256"

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

# ---------------------------------------------------------------------
# HOW FAR THE CAPTION TRACK MAY DIFFER FROM THE PICTURE, IN EITHER
# DIRECTION
#
# THE DEFECT THIS REPLACES.  The comparison used to be one-sided: only a
# caption track running PAST the end of the picture was refused.  A track
# that ends EARLY was accepted, and that is the direction a stale cue file
# fails in -- an SRT left over from a shorter session muxes cleanly into a
# longer film, every count tallies because the cue count is checked
# against that same stale file, and the result is a committed artifact
# whose captions stop partway through and whose every cue after the first
# few describes a different session's keystrokes.
#
# So the bound is now on the ABSOLUTE difference.  The number comes from
# arithmetic the two upstream stages already document:
#
#   * the subtitle stream's duration is the last cue's end, and make_srt.py
#     writes that equal to the timeline total exactly;
#   * the video stream's duration is the container's, which render_movie.py
#     measures as the timeline total plus [0.02, 0.06] s -- the concat
#     demuxer's per-entry quantisation plus the repeated final entry's own
#     default packet.
#
# Measured on the committed artifacts: timeline total 301.000, video
# stream 301.040, subtitle stream 301.000 -- a difference of 0.040.
#
# The smallest staleness worth catching is a session one keystroke shorter,
# which differs by at least the timeline's 0.25 s floor.  0.12 s therefore
# sits between the largest honest quantisation (0.06) and the smallest
# possible staleness (0.25 - 0.06 = 0.19), which is the same reasoning and
# the same value as render_movie.py's own DURATION_TOLERANCE.
# ---------------------------------------------------------------------
readonly CAPTION_DURATION_TOLERANCE="0.12"

# ---------------------------------------------------------------------
# THE GENERATION MANIFESTS, and why this stage reads them
#
# THE DEFECT.  Holding the caption track against the length of the
# picture catches a track from a session of a DIFFERENT length.  It cannot
# catch one from a session of the SAME length -- and "same length" is not
# far-fetched: a re-record of the same scripted opening, or a re-render of
# one session with a transcript from another, produces two artifacts whose
# durations agree to the millisecond and whose contents describe different
# keystrokes.  Duration is a weak proxy for identity and a digest is not.
#
# So both producers publish a generation manifest naming the timeline they
# computed from BY THAT DOCUMENT'S OWN DIGEST, and this stage requires the
# two to name the same one, and requires the movie and the cue file on disk
# to carry the digests their own manifests declare.  That makes muxing a
# caption track from one session into a film from another arithmetically
# impossible rather than merely unlikely.
# ---------------------------------------------------------------------
readonly MOVIE_MANIFEST_NAME="movie.json"
readonly TRANSCRIPT_MANIFEST_NAME="transcript.json"

# ffprobe's plain KEY=value form, and its bare-value form.  Parsed by
# key rather than by position, because ffprobe prints the fields in its
# own order and not in the order they were asked for.
readonly PROBE_KEYED="default=nw=1"
readonly PROBE_BARE="default=noprint_wrappers=1:nokey=1"

# What ffprobe prints for a field the container does not carry.
readonly PROBE_ABSENT="N/A"

# `timeout` reports this when it fires, which is how an expiry is told
# apart from the tool's own failure; 128+SIGKILL is what it reports when
# the grace period elapsed too and the child had to be killed.
readonly TIMEOUT_EXPIRED=124
readonly TIMEOUT_KILLED=137

# How long a child gets between TERM and KILL.  GNU timeout puts the
# command in a process group of its own and signals the group, so this is
# what makes the advertised ceiling hold against a tool that ignores TERM
# rather than being a request it can decline.
readonly KILL_GRACE=10

# ---------------------------------------------------------------------
# THE STAGE CEILING IS DERIVED FROM THE FILM, NOT FIXED
#
# Every external command here gets a ceiling, because a wedged ffmpeg
# would hang the pipeline sequencer indefinitely with nothing written and
# nothing reported -- the one failure mode worse than an error.
#
# IT CANNOT BE ONE NUMBER.  Three of the calls below read the whole video
# stream -- the mux, the stream hash and the cue extraction -- and the mux
# additionally RELOCATES the moov atom for `+faststart`, which is a second
# pass over the output.  Both costs are O(bytes), and the session length
# this pipeline is built for is deliberately unbounded, so a fixed number
# is either too small for a long film -- killing a healthy mux and
# reporting it as wedged, after which the pipeline has no captioned film
# at all -- or so large it is not a bound.  Measured on the committed
# 3.7 MB film the mux takes well under a second; a two-hour session at the
# same bitrate is gigabytes, and the fixed 900 s was chosen against
# neither.
#
# So the ceiling starts at the fixed value for the METADATA reads (a
# header probe is O(1) in the film's length) and is re-derived from the
# input film's own byte count and duration before the mux, which is the
# first call whose cost scales.  An explicit PLAYTHROUGH_CAPTION_TIMEOUT
# is honoured EXACTLY and never derived over: an operator who names a
# ceiling has named it.
# ---------------------------------------------------------------------
readonly DEFAULT_STAGE_TIMEOUT=900

# The derivation: a base for process start-up and container parsing, one
# second per this many bytes for each of the two passes a faststart mux
# makes over the film, and one second per this many seconds of film for
# the per-packet bookkeeping.  Both divisors are deliberately far below
# what any host achieves (this one copies at hundreds of MB/s), so an
# expiry means wedged rather than slow.
readonly MUX_BASE_SECONDS=300
readonly MUX_BYTES_PER_SECOND=1048576
readonly MUX_PASSES=2
readonly MUX_FILM_SECONDS_PER_SECOND=10

# No ceiling this file derives may exceed a day: a bound that large is
# already a diagnosis, and it keeps arithmetic on a byte count from
# producing something absurd.
readonly MUX_MAX_SECONDS=86400

# THE WATCHDOG.  The derived ceiling is the backstop; this is how a wedge
# is caught EARLY.  A mux that is working extends its own deadline by
# making progress -- the staging file grows, and while the moov atom is
# being relocated it stops growing but keeps being written, so the
# signature is size AND modification time.  A file that has done neither
# for this long has stalled, whatever its ceiling says.
#
# The stall window is overridable for the same reason the ceiling is: how
# long a legitimate quiet period can be depends on the host's storage, and
# a refusal nobody can reach in a test is a refusal nobody has read.
readonly WATCH_POLL_SECONDS=5
readonly DEFAULT_WATCH_STALL_SECONDS=120

if ! playthrough_validate_int \
        "${PLAYTHROUGH_CAPTION_STALL:-${DEFAULT_WATCH_STALL_SECONDS}}" \
        "PLAYTHROUGH_CAPTION_STALL" 1 86400; then
    exit "${EX_USAGE}"
fi
readonly WATCH_STALL_SECONDS="${PLAYTHROUGH_INT}"

# What the mux needs on the output filesystem beyond the artifacts
# themselves: room for the staging container (a stream copy, so about the
# size of the input), room for the retained copy of any film already
# published there (which is how a publication that cannot be confirmed is
# undone), and this margin for the filesystem's own overhead.
readonly MUX_SPACE_MARGIN=$((64 * 1024 * 1024))

if [ -n "${PLAYTHROUGH_CAPTION_TIMEOUT:-}" ]; then
    if ! playthrough_validate_int "${PLAYTHROUGH_CAPTION_TIMEOUT}" \
            "PLAYTHROUGH_CAPTION_TIMEOUT" 1 86400; then
        exit "${EX_USAGE}"
    fi
    CEILING_SOURCE="PLAYTHROUGH_CAPTION_TIMEOUT"
else
    if ! playthrough_validate_int "${DEFAULT_STAGE_TIMEOUT}" \
            "the default stage ceiling" 1 86400; then
        exit "${EX_USAGE}"
    fi
    CEILING_SOURCE="the metadata default, re-derived before the mux"
fi
# NEITHER IS readonly YET: the ceiling and the sentence that explains it
# are both re-derived once the film's size is known, and both are frozen
# there.  Whether an override was given IS fixed here -- an operator's
# number is never adjusted.
STAGE_TIMEOUT="${PLAYTHROUGH_INT}"
readonly CEILING_OVERRIDDEN="${PLAYTHROUGH_CAPTION_TIMEOUT:+yes}"

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
# rel PATH -- the repository-relative spelling, for reporting.
#
# DELEGATES to playthrough_rel() in env.sh, which is the single
# definition the whole pipeline uses.  This wrapper used to have its own
# copy, and the copy's fall-through branch printed an outside path AS
# GIVEN -- so a --output pointing at /home/someone/scratch/x.mp4 put
# that operator's home directory into the machine-readable summary and
# into every log line that named the file.  playthrough_rel reduces an
# outside path to its basename behind a marker instead, which is the
# same information a reader needs and none of the information they do
# not.  Kept as a name because this file calls it forty times.
rel() {
    playthrough_rel "${1-}"
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

Those three files are the ONLY ones this stage will read or write.  The
positionals are optional and are taken in that order; give the earlier
ones to reach a later one.  They exist to CONFIRM a path, not to change
it: each is resolved and must name the canonical artifact for its role,
so a different spelling of the same file is accepted and a different
file is refused.  Every artifact of this pipeline is committed evidence
with one place to live, and an MP4 written over the manifest, the
timeline, the transcript or the save would report success and destroy
the record.

The caption codec, its language tag and the stream copy of the picture
are likewise the requirement and cannot be altered from the command
line or the environment.

The output is written to a staging file, verified, and only then
renamed into place, so exit 0 means a container carrying a mov_text
track tagged eng is at the output path -- and a failed run leaves the
working tree exactly as it was found.

Prints KEY=value lines on stdout; the two verbatim ffprobe readouts,
warnings and diagnostics go to stderr.  See the header of this file for
the full output contract and the exit codes.

environment:
    PLAYTHROUGH_CAPTION_TIMEOUT       seconds allowed per external
                                      command.  Used EXACTLY when set;
                                      when it is not, the metadata reads
                                      get 900 and the whole-stream calls
                                      get a ceiling derived from the
                                      input film's own size and duration
    PLAYTHROUGH_CAPTION_STALL         seconds the mux may go without
                                      writing to its staging file before
                                      it is stopped early as stalled
                                      (default 120)
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

# NOT readonly yet.  The confinement gate below resolves each of these
# and, once it has proved the path names the one artifact its role is
# allowed to name, replaces it with env.sh's own spelling of that
# artifact -- so every line after the gate works on exactly the strings
# the no-argument run uses.  They are frozen there.

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
# sizes a file through a redirection rather than by argument, mv
# publishes the verified container, and readlink canonicalises the three
# paths for the confinement gate below -- a comparison of path STRINGS
# would be defeated by "playthrough/../playthrough/cata-play-cc.mp4",
# which is why the gate compares resolved paths instead.
# ---------------------------------------------------------------------
#
# sha256sum is the addition that makes the provenance check possible: the
# two generation manifests name their inputs by digest, and a digest has
# to be computed to be compared.  cp retains the previous generation
# beside the target so a publication that cannot be verified can be undone
# rather than merely reported.
#
# df and sleep are the additions the capacity reserve and the stall
# watchdog need: a mux that runs out of room mid-write leaves a truncated
# container, and a wedge is only detectable by looking at the staging file
# repeatedly rather than once.
if ! playthrough_require_tools ffmpeg ffprobe grep awk wc mv cp rm \
        sha256sum timeout readlink df sleep; then
    exit "${EX_PREREQ}"
fi

# THE PLATFORM, checked here for the same reason capture.sh checks it:
# ffmpeg parses a container in this stage, and on a release past its
# end-of-life date its known issues stay unfixed by definition however
# current `dpkg-query` looks.  A refusal by default, waived only through
# PLAYTHROUGH_ALLOW_EOL_PLATFORM=<reason>, whose reason is warned once
# and printed in the environment summary.  This stage used to be the one
# shell entry point that did NOT check -- an inconsistency, not a
# decision, since it sources the same env.sh the others do.
playthrough_check_platform || exit "${EX_PREREQ}"

# AND THE TRUST STATE, because this stage produces PRODUCTION MEDIA.
# The captioned film is the pipeline's final artifact and it is
# committed, so it is evidence in exactly the sense capture.sh's kept
# frame is -- and a security review was right that the platform waiver
# had to force the diagnostic state rather than merely be recorded.
# PLAYTHROUGH_ALLOW_EOL_PLATFORM is a registered trust bypass now, and
# under it (or any other) the mux refuses HERE, before ffmpeg is
# invoked, rather than producing a container nobody can attest to.
# Diagnosis of this stage is a matter of reading the refusal and fixing
# what the bypass was hiding; there is no captioned film worth having
# that was produced under a relaxed check.
playthrough_assert_trusted "the caption mux" || exit "${EX_PREREQ}"

readonly FFMPEG="${PLAYTHROUGH_BIN_FFMPEG}"
readonly FFPROBE="${PLAYTHROUGH_BIN_FFPROBE}"
readonly GREP="${PLAYTHROUGH_BIN_GREP}"
readonly AWK="${PLAYTHROUGH_BIN_AWK}"
readonly WC="${PLAYTHROUGH_BIN_WC}"
readonly MV="${PLAYTHROUGH_BIN_MV}"
readonly CP="${PLAYTHROUGH_BIN_CP}"
readonly RM="${PLAYTHROUGH_BIN_RM}"
readonly SHA256SUM="${PLAYTHROUGH_BIN_SHA256SUM}"
readonly TIMEOUT="${PLAYTHROUGH_BIN_TIMEOUT}"
readonly READLINK="${PLAYTHROUGH_BIN_READLINK}"
readonly DF="${PLAYTHROUGH_BIN_DF}"
readonly SLEEP="${PLAYTHROUGH_BIN_SLEEP}"

# file_digest FILE
#   The sha256 of a file's exact bytes, or empty on failure.  Bare hex,
#   with the filename coreutils appends stripped, so the value compares
#   directly against a manifest field.
file_digest() {
    local out
    out="$("${SHA256SUM}" -- "$1" 2>/dev/null)" || return 1
    out="${out%% *}"
    case "${out}" in
        [0-9a-f]*)
            if [ "${#out}" -eq 64 ]; then
                printf '%s\n' "${out}"
                return 0
            fi
            ;;
    esac
    return 1
}

# manifest_digest FILE SECTION [BASENAME]
#   Read one sha256 out of a generation manifest.
#
#   READ WITH A REAL JSON PARSER, not scraped.  These manifests are the
#   evidence that two artifacts belong to one session, so a reader that
#   could mis-parse a nested object -- which every awk or grep approach
#   can, given a field named the same way at a different depth -- would
#   turn the provenance gate into a formality.  $PLAYTHROUGH_PYTHON is the
#   interpreter env.sh already resolved and verified, and it is
#   unconditionally present whenever this stage runs: the two producers
#   immediately upstream of it are Python.
#
#   The program is a fixed literal and the paths arrive as argv, never
#   interpolated into source -- the repository's CodeQL python leg gates on
#   exactly that [.github/workflows/codeql-analysis.yml:35].
#
#   With BASENAME, the digest is taken from the "outputs" list entry whose
#   path ends in that name; without it, from the named top-level object.
#   Prints nothing and returns non-zero when the value is absent or is not
#   a 64-character hex digest, so a caller cannot mistake "unreadable" for
#   "matches".
manifest_digest() {
    local file="$1" section="$2" basename="${3:-}" out
    out="$("${PLAYTHROUGH_PYTHON}" -c '
import json
import posixpath
import sys

path, section = sys.argv[1], sys.argv[2]
wanted = sys.argv[3] if len(sys.argv) > 3 else ""
with open(path, "r", encoding="utf-8") as handle:
    record = json.load(handle)
if not isinstance(record, dict):
    raise SystemExit(1)
if wanted:
    for entry in record.get("outputs") or []:
        if not isinstance(entry, dict):
            continue
        if posixpath.basename(str(entry.get("path", ""))) == wanted:
            print(entry.get("sha256", ""))
            raise SystemExit(0)
    raise SystemExit(1)
found = record.get(section)
if not isinstance(found, dict):
    raise SystemExit(1)
print(found.get("sha256", ""))
' "${file}" "${section}" ${basename:+"${basename}"} 2>/dev/null)" ||
        return 1
    out="${out//[[:space:]]/}"
    case "${out}" in
        [0-9a-f]*)
            if [ "${#out}" -eq 64 ]; then
                printf '%s\n' "${out}"
                return 0
            fi
            ;;
    esac
    return 1
}

# run_bounded LABEL COMMAND...
#   Run one external command under the stage ceiling, reporting an
#   expiry as an expiry.  stderr is deliberately NOT captured or
#   silenced anywhere in this file: when ffmpeg refuses something, its
#   own message is the most useful thing an operator can be shown, and
#   swallowing it to print a tidier one would cost the diagnosis.
#
#   TERM THEN KILL, over the child's own process group.  A plain
#   `timeout N` sends one TERM and then reports an expiry whether or not
#   the child acted on it, so a tool wedged inside its own signal
#   handling kept running while this stage said it had been stopped.
#   --kill-after is what makes the advertised ceiling a fact.
run_bounded() {
    local label="$1"
    shift
    local status=0
    "${TIMEOUT}" --kill-after="${KILL_GRACE}" --signal=TERM \
        "${STAGE_TIMEOUT}" "$@" || status="$?"
    if [ "${status}" -eq "${TIMEOUT_EXPIRED}" ] ||
            [ "${status}" -eq "${TIMEOUT_KILLED}" ]; then
        playthrough_warn "${label} did not finish within" \
            "${STAGE_TIMEOUT}s and was stopped (exit ${status}$(
                [ "${status}" -eq "${TIMEOUT_KILLED}" ] &&
                    printf ', after the %ss grace period' \
                        "${KILL_GRACE}"
                true
            )).  That ceiling is ${CEILING_SOURCE}.  Raise" \
            "PLAYTHROUGH_CAPTION_TIMEOUT if this film is genuinely" \
            "that long, and look for a wedged tool if it is not."
    fi
    return "${status}"
}

# progress_signature FILE
#   A value that changes whenever FILE is being written, and does not
#   change when it is not.
#
#   SIZE ALONE IS NOT ENOUGH, and that is the whole reason this is a
#   function rather than a `wc -c`.  A `+faststart` mux writes the
#   container, then RELOCATES the moov atom to the front, and the
#   relocation rewrites the file in place -- the size does not move while
#   the largest single piece of work in the stage is happening.  The
#   modification time does.  So the signature is both, and a mux that is
#   working cannot be mistaken for one that has stalled.
progress_signature() {
    local out=""
    out="$("${PLAYTHROUGH_UTIL_STAT}" -c '%s %Y' -- "$1" \
        2>/dev/null || printf 'absent')"
    printf '%s' "${out}"
}

# run_watched LABEL WATCH_FILE COMMAND...
#   Run the one command whose cost is the film, under the derived ceiling
#   AND under a stall watchdog.
#
#   THE CEILING IS THE BACKSTOP, NOT THE DETECTOR.  Derived from the
#   film's own size, it is necessarily generous: on a multi-gigabyte
#   session it is hours, and waiting hours to discover that ffmpeg wedged
#   in its first second is not a diagnosis.  So progress is watched, and a
#   file that has neither grown nor been touched for
#   ${WATCH_STALL_SECONDS}s is stopped early with TERM -- which ffmpeg
#   honours immediately -- while the derived ceiling and its --kill-after
#   remain in force underneath for the case where it does not.
#
#   A child that ignores the early TERM is REPORTED and left to that
#   ceiling rather than having its wrapper killed: SIGKILL to `timeout`
#   would orphan the ffmpeg underneath it, and an orphaned encoder still
#   writing into the staging file is strictly worse than one that is
#   stopped a few minutes later by its own bound.
#
#   Sets LAST_WATCH_OUTCOME to ok, stalled, expired or failed.
LAST_WATCH_OUTCOME="ok"

run_watched() {
    local label="$1"
    local watch="$2"
    shift 2
    local pid=0 status=0 previous="" signature="" quiet=0 asked=0
    LAST_WATCH_OUTCOME="ok"
    "${TIMEOUT}" --kill-after="${KILL_GRACE}" --signal=TERM \
        "${STAGE_TIMEOUT}" "$@" &
    pid=$!
    previous="$(progress_signature "${watch}")"
    while kill -0 "${pid}" 2>/dev/null; do
        "${SLEEP}" "${WATCH_POLL_SECONDS}"
        signature="$(progress_signature "${watch}")"
        if [ "${signature}" != "${previous}" ]; then
            previous="${signature}"
            quiet=0
            continue
        fi
        quiet=$((quiet + WATCH_POLL_SECONDS))
        if [ "${quiet}" -lt "${WATCH_STALL_SECONDS}" ]; then
            continue
        fi
        if [ "${asked}" -eq 0 ]; then
            playthrough_warn "${label} has not written to" \
                "$(rel "${watch}") for ${quiet}s, so it has stalled" \
                "rather than being slow.  Asking it to stop now" \
                "instead of waiting out its ${STAGE_TIMEOUT}s ceiling."
            kill -TERM "${pid}" 2>/dev/null || true
            asked=1
            quiet=0
            continue
        fi
        playthrough_warn "${label} did not stop when asked.  It is" \
            "left to its ${STAGE_TIMEOUT}s ceiling, which escalates to" \
            "KILL after ${KILL_GRACE}s; killing the wrapper here would" \
            "orphan the encoder instead of stopping it."
        break
    done
    wait "${pid}" || status="$?"
    if [ "${status}" -eq 0 ]; then
        return 0
    fi
    if [ "${asked}" -eq 1 ]; then
        LAST_WATCH_OUTCOME="stalled"
    elif [ "${status}" -eq "${TIMEOUT_EXPIRED}" ] ||
            [ "${status}" -eq "${TIMEOUT_KILLED}" ]; then
        LAST_WATCH_OUTCOME="expired"
        playthrough_warn "${label} did not finish within" \
            "${STAGE_TIMEOUT}s and was stopped (exit ${status}).  That" \
            "ceiling is ${CEILING_SOURCE}."
    else
        LAST_WATCH_OUTCOME="failed"
    fi
    return "${status}"
}

# ---------------------------------------------------------------------
# WHICH FILES.  The three canonical artifacts, and nothing else, ever.
#
# assert_path_shape above only rules out spellings ffmpeg would
# MISREAD -- a leading dash, a protocol-looking first component, a
# newline.  It says nothing about WHERE the path points, and that gap
# was the whole vulnerability: the three positionals were handed
# straight to ffmpeg, so
#
#     embed_captions.sh in.mp4 in.srt ../../../etc/somefile.mp4
#
# wrote an MP4 wherever the invoking user could write, and
#
#     embed_captions.sh playthrough/manifest.jsonl ...
#
# read the session's own evidence as a film.  Worse than either, an
# output of playthrough/cata-play.mp4 would have put the captioned copy
# where the base render lives -- and the base render is the measured,
# non-blank, byte-hashed evidence every later stage compares against.
# (The equal-input-and-output check below catches only the case where
# BOTH name it; it cannot catch an output that collides with a
# DIFFERENT artifact.)
#
# CONTAINMENT INSIDE THE CHECKOUT IS NOT ENOUGH, and this is the gap it
# leaves.  Everything this pipeline produces lives under playthrough/,
# so a rule that says only "inside the working tree" still accepts
# playthrough/manifest.jsonl, playthrough/timeline.json,
# playthrough/transcript.md, playthrough/dossier.md and everything the
# engine wrote under playthrough/userdir/.  A caption mux that lands on
# any of those reports success and destroys the record: the manifest
# every count is derived from, the timeline both producers read as the
# single source of truth, or the save itself.
#
# So the destinations are ENUMERATED rather than bounded.  This stage
# reads exactly playthrough/cata-play.mp4 and playthrough/transcript.srt
# and writes exactly playthrough/cata-play-cc.mp4, and the permitted set
# is built from the same env.sh variables the defaults above are built
# from, so the two cannot drift apart.
#
# The positionals therefore no longer RELOCATE anything; they can only
# CONFIRM the canonical artifact for their role.  That is the intended
# loss.  These are committed evidence with one place to live, and env.sh
# exports their paths so that every stage AGREES about where that place
# is -- not so that it can be moved.
#
# Two comparisons, because either alone is defeated:
#
#   the resolved path   ".", ".." and a symlinked ANCESTOR all spell the
#                       same file differently, so the match is on what
#                       readlink -m returns rather than on the string.
#                       A checkout reached through a symlinked parent
#                       still matches, which is why this is the outer
#                       test.
#   no symlinked        resolving both sides means a symlink INSIDE the
#   component           tree that points at the canonical artifact would
#                       compare equal and be followed.  Every component
#                       below the repository root is walked and refused
#                       if it is a link, because the invariant is that
#                       these artifacts are real files nobody has
#                       redirected -- and publication is a rename, which
#                       REPLACES a link rather than following it.
# ---------------------------------------------------------------------

# resolve_path PATH
#   The absolute, symlink-free spelling of PATH, whether or not its last
#   component exists yet -- the output does not exist on a first run.
#   Printed, never assigned globally, so each caller keeps its own.
resolve_path() {
    "${READLINK}" -m -- "$1"
}

# assert_canonical_artifact GIVEN CANONICAL LABEL
#   GIVEN must name CANONICAL and must reach it without a link.
assert_canonical_artifact() {
    local given="$1" canonical="$2" label="$3"
    local real_given real_canonical
    real_given="$(resolve_path "${given}")" || real_given=""
    real_canonical="$(resolve_path "${canonical}")" || real_canonical=""
    if [ -z "${real_given}" ] || [ -z "${real_canonical}" ]; then
        die "${EX_USAGE}" "the ${label} path '${given}' could not be" \
            "resolved, so it cannot be held against the artifact this" \
            "stage is allowed to use for that role."
    fi
    if [ "${real_given}" != "${real_canonical}" ]; then
        die "${EX_USAGE}" "the ${label} must be" \
            "$(rel "${canonical}") and '${given}' is not: it resolves" \
            "to '$(rel "${real_given}")'.  This stage reads" \
            "$(rel "${PLAYTHROUGH_MOVIE}") and" \
            "$(rel "${PLAYTHROUGH_TRANSCRIPT_SRT}") and writes" \
            "$(rel "${PLAYTHROUGH_MOVIE_CC}"), and nothing else." \
            "The three positionals exist to CONFIRM those paths, not" \
            "to move them: every other file under playthrough/ is" \
            "either the session's evidence -- the manifest, the" \
            "timeline, the transcript, the dossier, the save -- or a" \
            "capture, and an MP4 written over any of them would" \
            "report success and destroy the record."
    fi
    # The UNRESOLVED canonical spelling, deliberately.  This walk exists
    # to find links, and readlink has already followed them: handing it
    # real_canonical would give it a path with no links left in it and
    # it would pass everything.  The literal env.sh spelling always
    # begins with PLAYTHROUGH_REPO_ROOT as a string, which is what the
    # walk needs to find its starting point.
    if ! playthrough_assert_no_symlink "${canonical}" \
            "${PLAYTHROUGH_REPO_ROOT}" "the ${label}"; then
        exit "${EX_USAGE}"
    fi
}

assert_canonical_artifact "${INPUT_MOVIE}" "${PLAYTHROUGH_MOVIE}" \
    "input film"
assert_canonical_artifact "${INPUT_SRT}" \
    "${PLAYTHROUGH_TRANSCRIPT_SRT}" "cue file"
assert_canonical_artifact "${OUTPUT_MOVIE}" "${PLAYTHROUGH_MOVIE_CC}" \
    "output"

# Proved equivalent, so from here on the CANONICAL spelling is the one
# in play.  Rebinding rather than keeping the operator's spelling means
# there is exactly one code path below this line: an argumentless run
# and a run that named all three files behave identically, and nothing
# downstream has to wonder which it is looking at.  rel() also reports
# these against PLAYTHROUGH_REPO_ROOT verbatim, so the summary reads the
# same either way.
INPUT_MOVIE="${PLAYTHROUGH_MOVIE}"
INPUT_SRT="${PLAYTHROUGH_TRANSCRIPT_SRT}"
OUTPUT_MOVIE="${PLAYTHROUGH_MOVIE_CC}"
readonly INPUT_MOVIE INPUT_SRT OUTPUT_MOVIE

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

# Both operands are env.sh constants by the time this runs, so this
# cannot fire on anything an operator typed -- the confinement gate
# already refused that.  It is kept as a guard on env.sh itself: if
# PLAYTHROUGH_MOVIE and PLAYTHROUGH_MOVIE_CC were ever edited into the
# same path, the mux would read and write one file and the base render
# would be gone, and this says so instead.
if [ "${INPUT_MOVIE}" = "${OUTPUT_MOVIE}" ]; then
    die "${EX_USAGE}" "env.sh names the input film and the output as" \
        "the same path ($(rel "${INPUT_MOVIE}")).  ffmpeg cannot read" \
        "and write one file at once, and the base render is evidence:" \
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
# THE PROVENANCE.  Do these two files describe the same session?
#
# Asked BEFORE the mux, because the answer decides whether there is
# anything worth muxing, and a refusal here costs nothing at all.
#
# Every other check in this file compares the output against the INPUTS.
# That is the wrong axis for the failure that matters most: a caption
# track and a film can agree in length, in cue count, in geometry and in
# codec while describing two different sessions.  Only the digest of the
# document they were each computed from settles it, and each producer
# publishes exactly that.
#
# The manifests are required rather than optional.  Treating an absent one
# as "nothing to check" would mean the gate silently stopped applying the
# moment an older render left none behind -- and an older render is
# precisely the case it exists to catch.
# ---------------------------------------------------------------------
MOVIE_MANIFEST="${PLAYTHROUGH_BUILD_DIR}/${MOVIE_MANIFEST_NAME}"
TRANSCRIPT_MANIFEST="${PLAYTHROUGH_BUILD_DIR}/\
${TRANSCRIPT_MANIFEST_NAME}"
readonly MOVIE_MANIFEST TRANSCRIPT_MANIFEST

assert_manifest_present() {
    local path="$1" producer="$2"
    if [ -f "${path}" ] && [ -s "${path}" ]; then
        return 0
    fi
    die "${EX_INPUT}" "there is no generation manifest at" \
        "$(rel "${path}"), so the film and the caption track cannot be" \
        "proved to describe the same session.  Run ${producer}, which" \
        "publishes it beside its own output.  A missing manifest is a" \
        "REFUSAL rather than a check that quietly stops applying: an" \
        "older render is exactly the case this gate exists to catch."
}

assert_manifest_present "${MOVIE_MANIFEST}" \
    "playthrough/tooling/render_movie.py"
assert_manifest_present "${TRANSCRIPT_MANIFEST}" \
    "playthrough/tooling/make_srt.py"

MOVIE_TIMELINE_SHA="$(manifest_digest "${MOVIE_MANIFEST}" timeline)" ||
    die "${EX_INPUT}" "$(rel "${MOVIE_MANIFEST}") names no timeline" \
        "digest, so the film cannot be attributed to a document." \
        "Re-run render_movie.py."
SRT_TIMELINE_SHA="$(manifest_digest "${TRANSCRIPT_MANIFEST}" \
    timeline)" ||
    die "${EX_INPUT}" "$(rel "${TRANSCRIPT_MANIFEST}") names no" \
        "timeline digest, so the caption track cannot be attributed to" \
        "a document.  Re-run make_srt.py."
readonly MOVIE_TIMELINE_SHA SRT_TIMELINE_SHA

if [ "${MOVIE_TIMELINE_SHA}" != "${SRT_TIMELINE_SHA}" ]; then
    die "${EX_INPUT}" "THE FILM AND THE CAPTIONS COME FROM DIFFERENT" \
        "TIMELINES.  $(rel "${INPUT_MOVIE}") was paced by the document" \
        "whose digest is ${MOVIE_TIMELINE_SHA} and" \
        "$(rel "${INPUT_SRT}") was written from ${SRT_TIMELINE_SHA}." \
        "Two sessions of the same length agree on every count this" \
        "stage can otherwise measure, so the digests are the only" \
        "thing that settles it.  Re-run render_movie.py and" \
        "make_srt.py from one playthrough/timeline.json.  Nothing was" \
        "muxed."
fi

# And each input must be the file its own manifest describes.  A manifest
# that agrees with another manifest says nothing if the bytes beside it
# have since been replaced.
assert_matches_manifest() {
    local file="$1" declared="$2" label="$3" producer="$4" found
    found="$(file_digest "${file}")" ||
        die "${EX_INPUT}" "could not hash the ${label}" \
            "$(rel "${file}"), so it cannot be held against its own" \
            "generation manifest"
    if [ "${found}" = "${declared}" ]; then
        return 0
    fi
    die "${EX_INPUT}" "the ${label} $(rel "${file}") carries" \
        "${found} and its generation manifest describes ${declared}." \
        "The file has been replaced since it was published, so the" \
        "manifest no longer attests to it and the provenance chain is" \
        "broken.  Re-run ${producer}.  Nothing was muxed."
}

_ec_declared="$(manifest_digest "${MOVIE_MANIFEST}" movie)" ||
    die "${EX_INPUT}" "$(rel "${MOVIE_MANIFEST}") names no digest for" \
        "the film it published.  Re-run render_movie.py."
assert_matches_manifest "${INPUT_MOVIE}" "${_ec_declared}" \
    "input film" "playthrough/tooling/render_movie.py"

_ec_declared="$(manifest_digest "${TRANSCRIPT_MANIFEST}" outputs \
    "${INPUT_SRT##*/}")" ||
    die "${EX_INPUT}" "$(rel "${TRANSCRIPT_MANIFEST}") names no" \
        "digest for ${INPUT_SRT##*/}.  Re-run make_srt.py."
assert_matches_manifest "${INPUT_SRT}" "${_ec_declared}" \
    "cue file" "playthrough/tooling/make_srt.py"
unset _ec_declared

playthrough_log "the film and the caption track are both attributed to" \
    "the timeline whose digest is ${MOVIE_TIMELINE_SHA}"

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

# AND JOIN THE CHECKOUT'S QUIESCENCE, as a producer: SHARED, because
# this stage may legitimately run beside another producer -- it has
# its own exclusive lock above for the one thing it must not share --
# but it must NOT run beside the gate that measures the film it is
# replacing, or the checkpoint that commits it.  A run started by
# run_pipeline.sh proves and inherits the sequencer's exclusive hold
# instead of blocking against it; see env.sh's mutation lock section.
if ! playthrough_acquire_mutation_lock shared "${LOCK_TIMEOUT}"; then
    die "${EX_MUX}" "the caption mux could not join THIS" \
        "checkout's quiescence: a gate or a checkpoint holds the" \
        "mutation lock exclusively, and publishing a new container" \
        "under one of those would leave it measuring or committing" \
        "a film that changed while it looked.  Nothing was written."
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
    playthrough_release_mutation_lock || true
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
# WHAT A PREVIOUS RUN'S PUBLICATION MAY HAVE LEFT.
#
# Two names, treated differently on purpose, and both matter because
# .gitignore's terminal `!/playthrough/**` negation re-includes everything
# under this tree -- so a leftover here is a file that would be COMMITTED.
#
#   the retained copy    machinery.  A run killed between the copy and the
#                        confirmation leaves it; the film it holds is
#                        already published at its own path, so the copy is
#                        redundant and is swept.
#   the quarantined file EVIDENCE.  It exists only because a publication
#                        was undone, which is a filesystem fault worth
#                        somebody's attention.  It is REPORTED and left
#                        alone -- deleting the only record of the fault
#                        would help nobody -- and the report says it must
#                        not be committed.
# ---------------------------------------------------------------------
_ec_retained_leftover="${OUTPUT_DIR}/\
.${OUTPUT_NAME%"${MOVIE_SUFFIX}"}.previous${MOVIE_SUFFIX}"
if [ -f "${_ec_retained_leftover}" ]; then
    playthrough_log "removing a retained copy left by an earlier run:" \
        "$(rel "${_ec_retained_leftover}")"
    "${RM}" -f -- "${_ec_retained_leftover}" || true
fi
unset _ec_retained_leftover

_ec_quarantine_leftover="${OUTPUT_DIR}/\
.${OUTPUT_NAME%"${MOVIE_SUFFIX}"}.rejected${MOVIE_SUFFIX}"
if [ -e "${_ec_quarantine_leftover}" ]; then
    playthrough_warn "an earlier run quarantined a container at" \
        "$(rel "${_ec_quarantine_leftover}") because publishing it" \
        "could not be confirmed.  It is left where it is, because it" \
        "is the only record of that fault -- but it is inside" \
        "playthrough/, which .gitignore re-includes, so move it out of" \
        "the tree before committing."
fi
unset _ec_quarantine_leftover

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
#
# EVERY ONE OF THEM IS BOUNDED.  These helpers used to invoke ffprobe
# directly, with no time limit, and there are more than a dozen calls
# between them.  A malformed or truncated container is enough for
# ffprobe to sit indefinitely trying to establish a stream, and this
# script is one stage of a sequential pipeline -- so a single wedged
# probe stopped the whole run with no diagnosis, after the mux had
# already produced a staging file nobody would ever look at.  They go
# through run_bounded now, which applies $PLAYTHROUGH_CAPTION_TIMEOUT,
# reports the stop by name, and leaves stderr alone so ffprobe's own
# complaint is still the thing an operator reads.
# ---------------------------------------------------------------------

# probe_one FILE STREAM_SPEC FIELD
#   One stream field, bare.  Prints the first line only, so a spec that
#   matched several streams cannot silently return two values.
probe_one() {
    local file="$1" spec="$2" field="$3" out
    out="$(run_bounded "the ${field} probe" \
        "${FFPROBE}" -v error -select_streams "${spec}" \
        -show_entries "stream=${field}" -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# probe_tag FILE STREAM_SPEC TAG
#   One stream metadata tag, bare.
probe_tag() {
    local file="$1" spec="$2" tag="$3" out
    out="$(run_bounded "the ${tag} tag probe" \
        "${FFPROBE}" -v error -select_streams "${spec}" \
        -show_entries "stream_tags=${tag}" -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# probe_container_duration FILE
probe_container_duration() {
    local file="$1" out
    out="$(run_bounded "the container duration probe" \
        "${FFPROBE}" -v error -show_entries format=duration \
        -of "${PROBE_BARE}" -i "${file}")" || return 1
    printf '%s' "${out%%$'\n'*}"
}

# count_streams FILE STREAM_SPEC
#   How many streams the spec matches.  One index line per stream, so
#   the answer is the line count -- and zero when nothing matched.
count_streams() {
    local file="$1" spec="$2" out count
    out="$(run_bounded "the ${spec} stream count" \
        "${FFPROBE}" -v error -select_streams "${spec}" \
        -show_entries stream=index -of "${PROBE_BARE}" \
        -i "${file}")" || return 1
    if [ -z "${out}" ]; then
        printf '0'
        return 0
    fi
    count="$(printf '%s\n' "${out}" | "${WC}" -l)"
    printf '%s' "${count//[[:space:]]/}"
}

# count_chapters FILE
#   How many chapters the container declares.  One id line per chapter,
#   so the answer is the line count, and zero when there are none.
count_chapters() {
    local file="$1" out count
    out="$(run_bounded "the chapter count" \
        "${FFPROBE}" -v error -show_chapters \
        -show_entries chapter=id -of "${PROBE_BARE}" \
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
#   A SHA-256 over the video stream's copied packets.  This is the
#   strongest available proof that the picture came through the mux
#   untouched: a re-encode changes every packet, and text drawn into
#   the picture would have to be encoded, so both fail it.  The stream
#   is copied rather than decoded, so this is a read of the file and
#   not a decode of the film.
#
#   SHA-256 RATHER THAN MD5.  MD5 is collision-broken, and chosen-prefix
#   collisions against it are cheap -- so "the two hashes match" was a
#   statement about accident rather than about intent.  The digest here
#   is the evidence that the committed film's picture is the picture
#   render_movie.py encoded, and evidence that an adversary can forge is
#   not evidence.  The algorithm is RECORDED beside the digest in the
#   log and in the machine-readable summary, so a later reader knows
#   what they are comparing rather than inferring it from the length.
#
#   The muxer prints one line per stream as `0,v,SHA256=<digest>` -- the
#   stream index, its type, then the algorithm and the value.  Only the
#   digest is returned: the prefix is identical on both sides by
#   construction (one `-map 0:v:0`, so always stream 0 of type v), it
#   names the algorithm a second time when the algorithm is already
#   recorded beside the value, and a reader comparing two digests should
#   be shown two digests.  The comparison is unweakened -- equal digests
#   over equal prefixes is equal lines.
video_stream_hash() {
    local file="$1" out line
    out="$(run_bounded "the video stream hash" \
        "${FFMPEG}" -v error -i "${file}" -map 0:v:0 -c copy \
        -f streamhash -hash "${STREAM_HASH_ALGORITHM}" -)" || return 1
    line="${out%%$'\n'*}"
    # Nothing after the last '=' means the muxer printed a shape this
    # does not understand, and an unrecognised shape is reported as
    # empty so the caller refuses rather than comparing two blanks.
    case "${line}" in
        *=*) printf '%s' "${line##*=}" ;;
        *) printf '%s' "" ;;
    esac
}

# ---------------------------------------------------------------------
# THE INPUT FILM CARRIES NOTHING BUT PICTURE.
#
# The mapping below names exactly one video stream and one caption
# stream, and the verification after the mux proves the container that
# came out carries nothing else -- so why ask the same question of the
# input first?
#
# Because the two questions have different answers.  The output check
# proves the MUX did not carry something through.  This one proves the
# FILM IS THE FILM THIS PIPELINE PRODUCED.  render_movie.py encodes one
# silent h264 stream from still images and nothing else; a
# playthrough/cata-play.mp4 sitting here with an audio track, a data
# stream or an attachment in it was written by something else, or over,
# and the captioned film is then a caption track muxed onto a picture
# whose provenance nothing in this repository accounts for.  `-c copy`
# and an explicit mapping would publish that quite happily, with the
# picture's stream hash matching perfectly, because the hash proves the
# picture survived the mux and says nothing about where the picture came
# from.
#
# So it is EX_INPUT and not EX_VERIFY: the refusal is about what was
# handed to this stage, it happens before ffmpeg is invoked at all
# rather than after a mux nobody will look at, and it names re-running
# the render as the remedy.
#
# It is also the first probe of the input, so it doubles as proof that
# ffprobe can read the film as a container at all.  The checks up to
# here have established that the path is a regular non-empty file with
# an .mp4 suffix -- which a text file renamed .mp4 also satisfies.
# ---------------------------------------------------------------------
for _ec_kind in a:audio d:data t:attachment; do
    _ec_spec="${_ec_kind%%:*}"
    _ec_name="${_ec_kind##*:}"
    _ec_extra="$(count_streams "${INPUT_MOVIE}" "${_ec_spec}")" ||
        die "${EX_INPUT}" "ffprobe could not count the" \
            "${_ec_name} streams of $(rel "${INPUT_MOVIE}").  The" \
            "file exists and is not empty, so either it is not a" \
            "container ffprobe can read or it is truncated." \
            "Re-run render_movie.py."
    if [ "${_ec_extra}" != "0" ]; then
        die "${EX_INPUT}" "$(rel "${INPUT_MOVIE}") carries" \
            "${_ec_extra} ${_ec_name} stream(s) and must carry none." \
            "render_movie.py encodes one silent picture stream from" \
            "still images, so this film was not produced by this" \
            "pipeline -- and captioning it would publish a picture" \
            "whose provenance nothing here accounts for. Nothing was" \
            "muxed.  Re-run render_movie.py."
    fi
done
unset _ec_kind _ec_spec _ec_name _ec_extra


# ---------------------------------------------------------------------
# THE MUX.
#
# An argument LIST, never a string and never a shell.  That is the
# repository's CodeQL python-leg discipline applied to its shell too
# [.github/workflows/codeql-analysis.yml:35], and it means a path
# containing a space, a quote or a semicolon cannot change what runs.
#
# Read this list against the requirement: overwrite, errors only, the
# film, the cues, take exactly one picture stream and exactly one
# caption stream, carry no inherited metadata and no chapters, copy the
# packets, override only the subtitle codec, tag the language, write the
# staging file.  There is nothing else in it -- no filter of any kind,
# no video encoder, no scaling, no frame rate, and no audio.  `-v error`
# is the only addition that is not a requirement, and it only silences
# progress chatter: ffmpeg's own errors still reach stderr, which is the
# whole reason nothing here captures or discards them.
#
# WHY THE FOUR ADDED FLAGS ARE NOT DECORATION.
#
# -map 0:v:0 -map 1:s:0.  Without any -map, ffmpeg applies its DEFAULT
# STREAM SELECTION: for each type it picks the "best" stream it can find
# across all inputs, and it carries types it was never asked about.  The
# inputs this pipeline produces happen to hold one video stream and one
# subtitle stream today, so the default happened to do the right thing
# -- but "happens to" is the whole problem.  A film that ever acquired a
# second video stream, an audio track, a data stream or an attachment
# would have it silently carried into a committed artifact, and the
# committed artifact is what a reader trusts to be exactly the captured
# picture plus the transcript.  Naming the two streams makes the
# container's contents a DECISION rather than an outcome, and the
# assertions below then prove the decision held.
#
# -map_metadata -1.  ffmpeg copies the first input's container metadata
# into the output by default, so every tag the encoder wrote travels
# into the published film: encoder name and version, creation time, and
# anything a future ffmpeg decides to add.  A creation timestamp in a
# committed artifact is a fact about the operator's clock, not about the
# session, and it also makes the artifact non-reproducible -- two
# identical renders would differ. Dropping it and then setting only the
# language tag means the container carries exactly what was chosen.
#
# -map_chapters -1.  Chapters are copied from the first input the same
# way.  render_movie.py writes none, so this is the case that costs
# nothing today and would otherwise be an unnoticed channel tomorrow.
#
# -movflags +faststart.  THE CAPTIONED FILM IS THE ONE A VIEWER
# STREAMS, so it has to carry the property the base render was given.
# render_movie.py encodes with `-movflags +faststart`, which relocates
# the `moov` atom -- the index a player needs before it can decode
# anything -- to the FRONT of the container, straight after `ftyp`.  A
# mux does not inherit that: `-c copy` writes a fresh container, and
# without this flag the MP4 muxer leaves `moov` where it naturally
# falls, which is at the END, after every byte of `mdat`.
#
# A runtime QA pass measured exactly that on the shipped artifact.  Atom
# walks: the base render read
# `ftyp@0(32) -> moov@32(3717) -> free@3749(8) -> mdat@3757(3745389)`,
# and the captioned film read
# `ftyp@0(32) -> free@32(8) -> mdat@40(3763357) -> moov@3763397(11141)`.
# Served over a Range-capable server, Chrome could start the base film
# from its first request, while the captioned film cost an extra tail
# fetch -- `Range: bytes=3735552-` -- before it could play at all.  That
# is a defect of the DISTRIBUTION artifact and it gets worse, not
# better, the larger a session is: every future viewer pays a round trip
# for an index that could have been in the first kilobyte.
#
# It is asserted below like every other mandated flag, so the property
# cannot be lost again by a quiet edit to this list.
# ---------------------------------------------------------------------
MUX_ARGS=(
    -y -v error
    -i "${INPUT_MOVIE}"
    -i "${INPUT_SRT}"
    -map 0:v:0
    -map 1:s:0
    -map_metadata -1
    -map_chapters -1
    -c copy
    -c:s "${SUBTITLE_CODEC}"
    "${SUBTITLE_METADATA_KEY}" "language=${SUBTITLE_LANGUAGE}"
    -movflags "${MOVFLAGS}"
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
readonly MUX_ARG_COUNT=24

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
# The confinement flags, asserted as literally as the mandated ones:
# each is the difference between a container whose contents were chosen
# and one whose contents were inherited.
assert_recipe_contains "-map 0:v:0"
assert_recipe_contains "-map 1:s:0"
assert_recipe_contains "-map_metadata -1"
assert_recipe_contains "-map_chapters -1"
# The streaming layout, asserted for the same reason: the captioned film
# is the distribution artifact, and a mux does not inherit the base
# render's front-loaded index.
assert_recipe_contains "-movflags ${MOVFLAGS}"

if [ "${#MUX_ARGS[@]}" -ne "${MUX_ARG_COUNT}" ]; then
    die "${EX_VERIFY}" "the mux command has ${#MUX_ARGS[@]}" \
        "arguments and must have exactly ${MUX_ARG_COUNT}.  Something" \
        "was added to it, and the one thing this stage must never add" \
        "is anything that touches the picture."
fi

# ---------------------------------------------------------------------
# THE CEILING, DERIVED FROM THIS FILM.
#
# Everything above this point read headers, whose cost does not scale with
# the session.  Everything below reads or writes the whole video stream,
# so the ceiling is re-derived here from the film's own size and duration
# -- see THE STAGE CEILING IS DERIVED FROM THE FILM above -- unless an
# operator named one, in which case theirs stands unchanged.
# ---------------------------------------------------------------------
INPUT_BYTES="$("${WC}" -c < "${INPUT_MOVIE}")"
INPUT_BYTES="${INPUT_BYTES//[[:space:]]/}"
readonly INPUT_BYTES

_ec_in_duration="$(probe_container_duration "${INPUT_MOVIE}")" ||
    _ec_in_duration=""
# Integer seconds: the shell has no floating point, and a ceiling does
# not need the fraction.  An unreadable duration contributes nothing
# rather than being guessed at.
_ec_in_seconds="${_ec_in_duration%%.*}"
case "${_ec_in_seconds}" in
    ''|*[!0-9]*) _ec_in_seconds=0 ;;
esac

if [ -z "${CEILING_OVERRIDDEN}" ]; then
    _ec_derived=$((MUX_BASE_SECONDS +
        MUX_PASSES * INPUT_BYTES / MUX_BYTES_PER_SECOND +
        _ec_in_seconds / MUX_FILM_SECONDS_PER_SECOND))
    if [ "${_ec_derived}" -gt "${MUX_MAX_SECONDS}" ]; then
        _ec_derived="${MUX_MAX_SECONDS}"
    fi
    STAGE_TIMEOUT="${_ec_derived}"
    CEILING_SOURCE="derived from ${INPUT_BYTES} byte(s) over \
${MUX_PASSES} pass(es) at ${MUX_BYTES_PER_SECOND} B/s plus \
${_ec_in_seconds}s of film at 1s per ${MUX_FILM_SECONDS_PER_SECOND}s, \
on a ${MUX_BASE_SECONDS}s base"
    unset _ec_derived
fi
readonly STAGE_TIMEOUT CEILING_SOURCE
playthrough_log "the ceiling for every whole-stream call below is" \
    "${STAGE_TIMEOUT}s -- ${CEILING_SOURCE}"
unset _ec_in_duration _ec_in_seconds

# ---------------------------------------------------------------------
# ROOM TO WRITE IT, ESTABLISHED BEFORE ANYTHING IS WRITTEN.
#
# A stream copy needs about the input's size for the staging container,
# and the publication step retains a copy of whatever film is already
# published there so that a publication which cannot be confirmed can be
# undone.  Both live on the OUTPUT filesystem, at the same time.
#
# A mux that runs out of room does not fail cleanly: ffmpeg writes until
# the write fails, and what it leaves is a truncated container -- which
# the verification below would reject, correctly, after having spent the
# whole cost of the mux to find out.  The arithmetic is available before
# any of it, so the refusal is available before any of it, and it names
# the figure that is missing rather than leaving an operator to work out
# why "No space left on device" appeared in an ffmpeg diagnostic.
# ---------------------------------------------------------------------
free_bytes() {
    local line="" last="" blocks=""
    local -a fields=()
    # -P is the POSIX output format, which guarantees ONE line per
    # filesystem -- without it a long device name wraps and the columns
    # move -- and -k fixes the block size at 1024 bytes so the arithmetic
    # does not depend on the host's BLOCKSIZE.  The last line is the data
    # line; its fourth field is the available space.  Read with the shell
    # rather than through awk, because the mount point is the LAST field
    # and may contain spaces while the four before it may not.
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        last="${line}"
    done < <("${DF}" -Pk -- "$1" 2>/dev/null)
    if [ -z "${last}" ]; then
        return 1
    fi
    read -r -a fields <<<"${last}"
    blocks="${fields[3]-}"
    case "${blocks}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "$((blocks * 1024))"
}

assert_mux_capacity() {
    local published=0 needed=0 free=""
    if [ -f "${OUTPUT_MOVIE}" ]; then
        published="$("${WC}" -c < "${OUTPUT_MOVIE}")"
        published="${published//[[:space:]]/}"
        case "${published}" in
            ''|*[!0-9]*) published=0 ;;
        esac
    fi
    needed=$((INPUT_BYTES + published + MUX_SPACE_MARGIN))
    if ! free="$(free_bytes "${OUTPUT_DIR}")"; then
        playthrough_warn "the free space on" \
            "$(rel "${OUTPUT_DIR}")'s filesystem could not be read," \
            "so the ${needed}-byte reserve this mux needs was not" \
            "checked.  The mux proceeds; a truncated container would" \
            "be caught by the verification below rather than here."
        return 0
    fi
    if [ "${free}" -lt "${needed}" ]; then
        die "${EX_MUX}" "there is not enough room to mux:" \
            "$(rel "${OUTPUT_DIR}") has ${free} byte(s) free and this" \
            "run needs ${needed} -- ${INPUT_BYTES} for the staging" \
            "container (a stream copy is about the size of its input)," \
            "${published} for the retained copy of the film already" \
            "published there, and ${MUX_SPACE_MARGIN} of margin.  Free" \
            "that much and run this again; nothing was written."
    fi
    playthrough_log "room to work: ${free} byte(s) free against a" \
        "${needed}-byte reserve (${INPUT_BYTES} staging + ${published}" \
        "retained + ${MUX_SPACE_MARGIN} margin)"
    return 0
}

assert_mux_capacity

playthrough_log "muxing $(rel "${INPUT_SRT}") (${CUES_IN} cues) into" \
    "$(rel "${INPUT_MOVIE}") as a selectable ${SUBTITLE_CODEC} track"

_ec_mux_status=0
# WATCHED, not merely bounded: this is the one call whose cost is the
# film, so a stall in it is caught by the staging file going quiet rather
# than by waiting out a ceiling that scales with the session.
run_watched "the caption mux" "${STAGING_FILE}" \
    "${FFMPEG}" "${MUX_ARGS[@]}" || _ec_mux_status="$?"

if [ "${_ec_mux_status}" -ne 0 ]; then
    case "${LAST_WATCH_OUTCOME}" in
        stalled)
            die "${EX_MUX}" "the caption mux stalled and was stopped" \
                "(exit ${_ec_mux_status}): it stopped writing to" \
                "$(rel "${STAGING_FILE}") for" \
                "${WATCH_STALL_SECONDS}s.  Nothing was published."
            ;;
        expired)
            die "${EX_MUX}" "the caption mux did not finish within" \
                "${STAGE_TIMEOUT}s and was stopped (exit" \
                "${_ec_mux_status}).  That ceiling is" \
                "${CEILING_SOURCE}.  Nothing was published."
            ;;
    esac
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

# --- nothing else at all ----------------------------------------------
#
# THE MAPPING IS A DECISION; THESE ARE THE PROOF IT HELD.  The mux names
# exactly two streams, so a container that came out carrying a third of
# any type means either the mapping did not apply or an input held
# something this pipeline never produced.  Either way a committed
# artifact would carry a stream nobody chose, and the artifact's whole
# value is that a reader can trust it to be the captured picture plus
# the transcript and nothing besides.
#
# Audio is the case worth naming: the film is silent by requirement --
# SOUND_ENABLED is false and SDL_AUDIODRIVER is dummy, so there is no
# audio anywhere in the pipeline -- and a container that acquired an
# audio stream would be carrying something whose provenance nothing in
# this repository could account for.
for _ec_kind in a:audio d:data t:attachment; do
    _ec_spec="${_ec_kind%%:*}"
    _ec_name="${_ec_kind##*:}"
    _ec_extra="$(count_streams "${STAGING_FILE}" "${_ec_spec}")" ||
        die "${EX_VERIFY}" "ffprobe could not count the" \
            "${_ec_name} streams of the muxed container"
    if [ "${_ec_extra}" != "0" ]; then
        die "${EX_VERIFY}" "the muxed container carries" \
            "${_ec_extra} ${_ec_name} stream(s) and must carry none." \
            "The mux maps exactly one video stream and one caption" \
            "stream, so anything else came from an input this" \
            "pipeline did not produce.  Nothing was published."
    fi
    if [ "${_ec_spec}" = "a" ]; then
        # Kept for the summary.  A caller reading AUDIO_STREAMS=0 is
        # reading a measurement of the published container, not this
        # script's opinion of it -- and the film is silent by
        # requirement, so the measurement is worth stating rather
        # than leaving to be inferred from the absence of a complaint.
        AUDIO_STREAMS="${_ec_extra}"
    fi
done
unset _ec_kind _ec_spec _ec_name _ec_extra
readonly AUDIO_STREAMS

# --- and only the tags that were chosen -------------------------------
#
# -map_metadata -1 says nothing is inherited; this says nothing arrived
# that was not either structural or asked for.
_ec_tag_lines="$(run_bounded "the container tag readout" \
    "${FFPROBE}" -v error -show_entries format_tags \
    -of "${PROBE_KEYED}" -i "${STAGING_FILE}")" ||
    die "${EX_VERIFY}" "ffprobe could not read the container tags of" \
        "the muxed container"
while IFS= read -r _ec_tag_line; do
    case "${_ec_tag_line}" in
        TAG:*) ;;
        *) continue ;;
    esac
    _ec_tag_name="${_ec_tag_line#TAG:}"
    _ec_tag_name="${_ec_tag_name%%=*}"
    case " ${ALLOWED_FORMAT_TAGS} " in
        *" ${_ec_tag_name} "*) continue ;;
    esac
    die "${EX_VERIFY}" "the muxed container carries the metadata tag" \
        "'${_ec_tag_name}', which is not one of the structural tags" \
        "this stage allows (${ALLOWED_FORMAT_TAGS}).  Container" \
        "metadata is dropped with -map_metadata -1 and only the" \
        "caption language is set, so a tag arriving here is either" \
        "inherited despite that flag or newly written by this ffmpeg" \
        "-- and a committed artifact carries only what was chosen." \
        "Nothing was published."
done <<EOF
${_ec_tag_lines}
EOF
unset _ec_tag_lines _ec_tag_line _ec_tag_name

# --- and no chapters --------------------------------------------------
#
# -map_chapters -1 says none are carried; this says none arrived.
_ec_chapters="$(count_chapters "${STAGING_FILE}")" ||
    die "${EX_VERIFY}" "ffprobe could not count the chapters of the" \
        "muxed container"
if [ "${_ec_chapters}" != "0" ]; then
    die "${EX_VERIFY}" "the muxed container declares" \
        "${_ec_chapters} chapter(s) and must declare none." \
        "render_movie.py writes no chapters, so these were inherited" \
        "from an input despite -map_chapters -1.  Nothing was" \
        "published."
fi
unset _ec_chapters

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
#   the stream hash   SHA-256 over the video stream's packets.  Equal
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
if run_bounded "the muxer list" \
        "${FFMPEG}" -hide_banner -muxers 2>/dev/null |
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
        "$(rel "${INPUT_MOVIE}")" \
        "(${STREAM_HASH_ALGORITHM}:${_ec_hash_out})"
    VIDEO_COPY_PROOF="stream-hash-${STREAM_HASH_ALGORITHM}"
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

# --- the captions cover the picture, in BOTH directions ---------------
#
# The cue file is written from the same timeline the film is paced by, so
# its last cue ends where the picture ends -- give or take the concat
# demuxer's quantisation, which is what CAPTION_DURATION_TOLERANCE is
# sized for.  A disagreement is an upstream drift between the timeline and
# the render rather than a fault in this mux.  IT IS STILL A REFUSAL.
#
# Warning and publishing anyway was tried, on the reasoning that
# misattributing an upstream drift to this stage would send an operator to
# the wrong file.  The message can say where the fault is without the film
# shipping: a published container whose captions do not cover its picture
# is a broken artifact whichever stage broke it, and it is COMMITTED -- so
# warning and publishing means the defect reaches the repository with a
# note about it in a log nobody re-reads.
#
# *** THE COMPARISON IS ABSOLUTE, AND THAT IS THE FIX ***  It used to
# refuse only a track running PAST the end of the picture.  A track that
# ends EARLY was published, and early is the direction a STALE cue file
# fails in: an SRT left over from a shorter session muxes cleanly into a
# longer film, the cue-count check passes because it is checked against
# that same stale file, and the artifact ships with captions that stop
# partway through and that describe another session's keystrokes
# throughout.  Both directions are now bounded, and each gets its own
# message because the diagnosis differs.
#
# AND AN UNMEASURABLE DURATION IS ALSO A REFUSAL.  The comparison used to
# be skipped when either value was not a number, which is precisely the
# case where nothing is known: ffprobe printing N/A for the subtitle
# stream's duration means the check did not run, and a skipped check that
# leaves no trace is indistinguishable from a check that passed.
if ! is_number "${SUBTITLE_DURATION}"; then
    die "${EX_VERIFY}" "ffprobe could not measure the caption" \
        "track's duration in the muxed container (it reported" \
        "'${SUBTITLE_DURATION}'), so the cues cannot be held against" \
        "the length of the picture.  A container whose caption timing" \
        "cannot be verified is refused rather than published" \
        "unverified.  Nothing was published."
fi
if ! is_number "${OUT_VIDEO_DURATION}"; then
    die "${EX_VERIFY}" "ffprobe could not measure the video stream's" \
        "duration in the muxed container (it reported" \
        "'${OUT_VIDEO_DURATION}'), so the cues cannot be held against" \
        "the length of the picture.  Nothing was published."
fi
if float_exceeds "${SUBTITLE_DURATION}" "${OUT_VIDEO_DURATION}" \
        "${CAPTION_DURATION_TOLERANCE}"; then
    die "${EX_VERIFY}" "THE CAPTIONS OUTLAST THE PICTURE.  The" \
        "caption track runs to ${SUBTITLE_DURATION}s but the picture" \
        "ends at ${OUT_VIDEO_DURATION}s, so the last cues fall past" \
        "the end of the film -- more than the" \
        "${CAPTION_DURATION_TOLERANCE}s the concat demuxer's" \
        "quantisation accounts for.  The mux is faithful to" \
        "$(rel "${INPUT_SRT}"), so the disagreement is upstream:" \
        "re-run render_movie.py and make_srt.py from the same" \
        "playthrough/timeline.json, which is the single source both" \
        "read.  Nothing was published, so" \
        "$(rel "${OUTPUT_MOVIE}") is whatever it was before this run."
fi
if float_exceeds "${OUT_VIDEO_DURATION}" "${SUBTITLE_DURATION}" \
        "${CAPTION_DURATION_TOLERANCE}"; then
    die "${EX_VERIFY}" "THE CAPTIONS END SHORT OF THE PICTURE.  The" \
        "caption track stops at ${SUBTITLE_DURATION}s and the picture" \
        "runs to ${OUT_VIDEO_DURATION}s, so the film ends on a" \
        "stretch no cue covers" \
        "-- a gap larger than the ${CAPTION_DURATION_TOLERANCE}s of" \
        "quantisation that separates an honest pair.  This is the" \
        "direction a STALE cue file fails in: an SRT from a shorter" \
        "session muxes cleanly into a longer film and every count" \
        "still tallies, because the cue count is checked against that" \
        "same file.  Re-run make_srt.py from the timeline" \
        "render_movie.py paced this film by.  Nothing was published."
fi

CONTAINER_DURATION="$(probe_container_duration "${STAGING_FILE}")"
readonly CONTAINER_DURATION

# ---------------------------------------------------------------------
# THE EVIDENCE, MEASURED BEFORE ANYTHING IS PUBLISHED
#
# THE DEFECT THIS ORDERING FIXES.  These two probe readouts, the stream
# census beneath them and the byte-size comparison all used to run AFTER
# the rename, against the published file, and each of them could `die`.
# So the canonical captioned MP4 -- a committed artifact -- was replaced
# first and interrogated second, and a failure left the unverified
# container sitting in the working tree as the film while the previous
# one, which had passed every check, was already gone.  "The file is left
# in place for inspection" was the stated policy, and what it meant in
# practice was that a broken artifact became the published one.
#
# Every fallible measurement therefore happens HERE, on the staging file.
# The rename below is preceded by a copy of the previous generation and
# followed by ONE cheap, infallible-by-construction check: the digest of
# the published bytes against the digest of the bytes that were measured.
# Printing the staged readouts as the evidence is sound precisely because
# of that check -- the published file is proved to be the same bytes.
# ---------------------------------------------------------------------
SUBTITLE_READOUT="$(run_bounded "the caption stream readout" \
    "${FFPROBE}" -v error -select_streams s \
    -show_entries stream=index,codec_name:stream_tags=language \
    -of "${PROBE_KEYED}" -i "${STAGING_FILE}")"
VIDEO_READOUT="$(run_bounded "the video stream readout" \
    "${FFPROBE}" -v error -select_streams v \
    -show_entries stream=codec_name,width,height \
    -of "${PROBE_KEYED}" -i "${STAGING_FILE}")"
readonly SUBTITLE_READOUT VIDEO_READOUT

assert_readout_contains() {
    local readout="$1" needle="$2" what="$3"
    case "${readout}" in
        *"${needle}"*) return 0 ;;
    esac
    die "${EX_VERIFY}" "the muxed container does not report ${what}:" \
        "'${needle}' is absent from the ffprobe readout.  Nothing was" \
        "published, so $(rel "${OUTPUT_MOVIE}") is whatever it was" \
        "before this run."
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

# The digest of what is about to be published, taken while the bytes are
# still reachable under a name this stage controls.  It is the whole basis
# of the identity check after the rename, and it cannot be taken
# afterwards: by then the only file to hash is the one whose identity is
# in question.
STAGED_SHA="$(file_digest "${STAGING_FILE}")" ||
    die "${EX_VERIFY}" "could not hash the verified container, so its" \
        "publication could not be confirmed afterwards.  Nothing was" \
        "published."
readonly STAGED_SHA

# ---------------------------------------------------------------------
# PUBLISH.  A rename inside one directory, so a reader sees either the
# previous film or this one -- with the previous one retained beside it
# until this one is confirmed.
#
# The retained copy is what turns "the file is left in place for
# inspection" into an actual recovery.  It is a plain copy rather than a
# rename, so the previous film stays readable at its published path right
# up to the moment it is replaced, and it is removed only once the new
# bytes are confirmed.
# ---------------------------------------------------------------------
RETAINED_FILE="${OUTPUT_DIR}/.${OUTPUT_NAME%"${MOVIE_SUFFIX}"}\
.previous${MOVIE_SUFFIX}"
QUARANTINE_FILE="${OUTPUT_DIR}/.${OUTPUT_NAME%"${MOVIE_SUFFIX}"}\
.rejected${MOVIE_SUFFIX}"
readonly RETAINED_FILE QUARANTINE_FILE

if [ -e "${RETAINED_FILE}" ]; then
    "${RM}" -f -- "${RETAINED_FILE}" || true
fi
_ec_retained=0
if [ -f "${OUTPUT_MOVIE}" ]; then
    if "${CP}" -p -- "${OUTPUT_MOVIE}" "${RETAINED_FILE}"; then
        _ec_retained=1
    else
        die "${EX_VERIFY}" "could not retain the previous" \
            "$(rel "${OUTPUT_MOVIE}") before replacing it.  A" \
            "publication that cannot be undone is not attempted:" \
            "nothing was published."
    fi
fi

# restore_previous REASON...
#   Put the previous film back, quarantine the file that failed, and die.
#   Called only after the rename, and only when the published bytes are
#   not the bytes that were verified.
restore_previous() {
    local restored="no previous film to restore"
    if [ -e "${OUTPUT_MOVIE}" ]; then
        "${MV}" -f -- "${OUTPUT_MOVIE}" "${QUARANTINE_FILE}" || true
    fi
    if [ "${_ec_retained}" -eq 1 ] && [ -f "${RETAINED_FILE}" ]; then
        if "${MV}" -f -- "${RETAINED_FILE}" "${OUTPUT_MOVIE}"; then
            restored="the previous film has been restored"
        else
            restored="the previous film is at \
$(rel "${RETAINED_FILE}") and could NOT be moved back"
        fi
    fi
    die "${EX_VERIFY}" "$@" "The rejected container is quarantined at" \
        "$(rel "${QUARANTINE_FILE}") and ${restored}."
}

if ! "${MV}" -f -- "${STAGING_FILE}" "${OUTPUT_MOVIE}"; then
    if [ "${_ec_retained}" -eq 1 ]; then
        "${RM}" -f -- "${RETAINED_FILE}" || true
    fi
    die "${EX_VERIFY}" "could not publish the verified container to" \
        "$(rel "${OUTPUT_MOVIE}").  The previous film is untouched."
fi

# THE ONE CHECK AFTER THE RENAME, and it is a byte-identity check rather
# than a re-interrogation.  Every question about what the container HOLDS
# was answered above, on the bytes this digest names; all that remains is
# whether the filesystem moved those bytes faithfully.  A mismatch here is
# a fault below this mux, and it is now RECOVERABLE.
_ec_published_sha="$(file_digest "${OUTPUT_MOVIE}")" ||
    restore_previous "the container published as" \
        "$(rel "${OUTPUT_MOVIE}") could not be hashed, so it cannot be" \
        "confirmed to be the file that passed verification."
if [ "${_ec_published_sha}" != "${STAGED_SHA}" ]; then
    restore_previous "$(rel "${OUTPUT_MOVIE}") carries" \
        "${_ec_published_sha} and the container that passed every" \
        "check was ${STAGED_SHA}.  A rename that changes a file's" \
        "bytes is a fault in the filesystem and not in this mux, but" \
        "the artifact is committed, so an unverified film does not" \
        "stay published."
fi
unset _ec_published_sha

# The previous generation has served its purpose.
if [ "${_ec_retained}" -eq 1 ]; then
    "${RM}" -f -- "${RETAINED_FILE}" || true
fi
unset _ec_retained

# NOBODY ELSE MAY REWRITE THE FILM.  ffmpeg creates the staging container
# under whatever umask this process inherited, and a security review
# measured the consequence on the delivered tree: the captioned film was
# published at mode 0666, so any local account could have replaced the
# one artifact this stage exists to produce -- after every check on it
# had passed.  The mode is therefore asserted here, on the PUBLISHED
# path, rather than left to the environment.  Read access is untouched:
# this file is committed to a git repository and is meant to be read.
playthrough_deny_foreign_write "${OUTPUT_MOVIE}" \
    "the captioned film" || exit "${EX_VERIFY}"

{
    printf '%s\n' "--- ffprobe, caption stream(s) of \
$(rel "${OUTPUT_MOVIE}") ---"
    printf '%s\n' "${SUBTITLE_READOUT}"
    printf '%s\n' "--- ffprobe, video stream(s) of \
$(rel "${OUTPUT_MOVIE}") ---"
    printf '%s\n' "${VIDEO_READOUT}"
} >&2

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
note AUDIO_STREAMS "${AUDIO_STREAMS}"
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
