#!/usr/bin/env bash
# ---------------------------------------------------------------------
# playthrough/tooling/capture.sh
#
# ONE keystroke, ONE screenshot, ONE clock reading.
#
# The capture step of the pipeline's loop -- observe, decide in
# character, act, capture, log.  A single invocation lets the frame
# settle, photographs the X ROOT window into
# playthrough/frames/frame_%05d.png, and reads the sidebar clock out of
# the pixels it has just written.  It never loops over keys and never
# sends one: session.py owns the keystroke and the frame counter, this
# file owns the photograph.
#
# USAGE
#     FRAME_INDEX=<n> playthrough/tooling/capture.sh
#     playthrough/tooling/capture.sh --help
#
# FRAME_INDEX is the ONLY input and it is required.  This file must
# never derive, default, guess or increment one, and deliberately does
# not count it off the frames directory: that would be a second source
# of truth, and a retry could silently renumber a frame.
#
# THE ROOT WINDOW, DELIBERATELY.  `import -window root`, never the game
# X window.  The root is 1920x1080 while the terminal render grid the
# engine paints is 1920x1072 at +0+4 (the three rectangles are tabulated
# in env.sh under "Display, window and grid geometry").  Photographing
# the root yields a true-resolution PNG needing NO rescaling, and
# rescaling would soften exactly the 8x16 glyphs the clock read depends
# on.  ImageMagick is called only as `import`, `convert` and `identify`:
# those names exist on both the 6.x and 7.x branches, so this file runs
# against either.
#
# THE CROP AND THE CLOCK.  The sidebar rectangle is COMPUTED at run time
# by sidebar_geometry.py -- it is never a literal here except in one
# clearly labelled operator override -- and the reading is matched as
# [0-9]{2}:[0-9]{2}:[0-9]{2}, the fixed-width form
# to_string_time_of_day() emits under 24_HOUR=24h
# (src/calendar.cpp:649).  The other two branches would defeat it:
# "military" renders 0815.32 and the shipped "12h" default renders
# 8:15:32 AM with variable padding.  Preprocessing is
# `+repage -colorspace Gray -resize 200% -normalize`, because 8x16
# terminal glyphs are illegible to tesseract at native size.
# THE OCR MAY LEGITIMATELY RETURN NOTHING -- no watch carried, the
# survivor underground, a genuine misread -- and an unreadable clock is
# reported as unreadable rather than guessed.
#
# STDOUT IS A MACHINE CONTRACT.  Every stdout line is KEY=value, one per
# line, and nothing else is written there; all logging, warnings and
# diagnostics go to stderr, which also keeps engineering observations
# out of the in-character record.  A caller reads a field with
#
#     out="$(FRAME_INDEX=42 playthrough/tooling/capture.sh)"
#     clock="$(printf '%s\n' "${out}" | sed -n 's/^CLOCK=//p')"
#
# The keys, always in this order:
#
#     CAPTURE_MODE     production | diagnostic.  The first key emitted,
#                      because it decides whether the rest describes a
#                      frame that belongs to the record.  A caller must
#                      accept ONLY production -- and cannot do otherwise
#                      by accident, since diagnostic never exits 0
#     FRAME_INDEX      the index exactly as validated
#     FRAME_NAME       frame_%05d.png
#     FRAME_FILE       playthrough/frames/frame_%05d.png -- repository
#                      relative, and byte-identical to manifest.py's
#                      `file` field, built from the same format.  EMPTY
#                      in diagnostic mode: the frame is withdrawn from
#                      the tree, so there is no such path
#     FRAME_PATH       the same frame, absolute.  Empty in diagnostic
#                      mode, for the same reason
#     DIAGNOSTIC_PATH  where a withdrawn frame is kept, outside the
#                      working tree.  Empty in production, where nothing
#                      is withdrawn -- emitted either way, because a key
#                      that sometimes disappears is a key a consumer
#                      papers over with a default
#     FRAME_BYTES      size on disk, so a truncated write is visible
#     FRAME_FORMAT     the format identify reports (PNG)
#     FRAME_GEOMETRY   WxH as captured, asserted against the contract
#     REAL_TS          UTC instant of the grab, in the manifest's own
#                      real_ts form (canonical_real_ts() documents
#                      accepting exactly this `date` output)
#     CAPTURE_TOOL     import, or scrot when import is unavailable
#     LUMA_MEAN        grayscale mean of the frame
#     LUMA_STDDEV      grayscale standard deviation of the frame
#     CLOCK_RECT       the crop rectangle actually used, or empty
#                      when no crop was applied to this frame
#     CLOCK_RECT_FROM  computed | override | skipped -- there is no
#                      fallback, and 'skipped' means the clock read was
#                      off, so nothing cropped the frame at all
#     CLOCK_SOURCE     ocr_clock.py | inline | none
#     CLOCK_STATUS     read | unreadable | fault | skipped
#     CLOCK            the reading, VERBATIM, or empty when there was
#                      none.  Never interpolated, never carried forward
#                      from another frame, never guessed
#     TIME_PHRASE      the coarse phrase the sidebar showed instead of a
#                      clock, verbatim, or empty
#     CLOCK_DATE       the sidebar date line, VERBATIM, or empty.  Read
#                      because timeline.py cross-checks its rollover and
#                      day-count decisions against it: a clock alone
#                      cannot tell a crossing of midnight from a misread
#                      going backwards, nor a 24-hour action from a
#                      zero-second one.  Never derived from the clock
#     DATE             the same line under the telemetry row's own field
#                      name, so a row built from this payload and this
#                      payload itself cannot drift
#     DATE_STATUS      read | unreadable | fault | unavailable | skipped
#     DATE_AUDIT       yes | no | off -- whether this frame's date
#                      evidence reached ocr_clock.py's audit.  "no" is
#                      not a failure, but timeline.py must then treat
#                      this frame's date as UNKNOWN, never as unchanged
#     OBSERVATIONS     the canonical telemetry sidecar this frame's row
#                      BELONGS IN -- env.sh's PLAYTHROUGH_OBSERVATIONS.
#                      This file does not append it: it reports the
#                      destination and the row's fields, and session.py
#                      persists them alongside the manifest row.  Empty
#                      when no row is owed, which is any capture no
#                      manifest will mention
#
# EXIT CODES
#     0  one frame captured and this invocation's output is complete
#     1  usage error -- a missing, malformed or out-of-range index, or a
#        production run that tried to relax one of the six safeguards
#        (the fifth being the date-audit destination and the sixth a
#        trusted environment: see THE MODE)
#     2  layout error -- not inside a checkout, or env.sh is missing
#     3  the capture failed, or produced something that is not a frame
#     4  the frame is blank -- the black-movie guard fired
#     5  no usable display at the contracted geometry, a frame that is
#        not that geometry, or a crop that could not be computed
#     6  the clock read hit a FAULT rather than an unreadable clock
#     7  refusing to overwrite an existing frame at this index
#     8  a prerequisite command is missing, or the date-audit directory
#        does not exist
#     9  a DIAGNOSTIC capture completed and was withdrawn out of the
#        working tree.  Non-zero by design: no frame was added to
#        playthrough/frames/, so this must not read as success
#
# THE NON-BLANK GATE.  Every frame is measured in grayscale and rejected
# unless mean > 0 AND std > 0.  A frame of zero pixels is the signature
# of SDL_VIDEODRIVER=dummy, under which the game runs, the keystrokes
# land, the PNG is written, ffmpeg encodes and every count matches --
# the only symptom being that the movie shows nothing.  The std term
# additionally rejects a uniform solid colour.
#
# THE INVARIANT THIS FILE GUARANTEES, AND THE RESERVATION IS ATOMIC.
#     exit 0  <=>  exactly one NEW PNG in playthrough/frames/
#                  AND this invocation's whole output contract was
#                  delivered
# Both halves matter.  That reading of the first half is the default
# production mode (PLAYTHROUGH_CAPTURE_OVERWRITE=0).  With overwrite
# enabled the index already holds a frame, so `exit 0` means one frame
# WRITTEN AT THAT INDEX and the PNG count is unchanged; that mode is for
# a diagnosis, never a session, and it announces itself on stderr.  On
# any failure in either mode the frames directory is left exactly as it
# was found: a frame this invocation wrote is withdrawn to a diagnostic
# directory outside the working tree, and a pre-existing frame moved
# aside is put back.  The frame is committed -- KEPT=1 -- as the LAST
# statement before exit 0, after the whole payload has been written and
# every fallible step is behind it, so a failure to deliver the contract
# withdraws the frame instead of leaving one nobody was told about; and
# because a shell killed by a signal never reaches its EXIT trap, PIPE,
# INT, TERM and HUP are trapped as well.  session.py cannot append a
# manifest row for a frame that does not exist, nor miss one that does,
# and the frames-count == manifest-line-count identity that
# verify_artifacts.sh asserts cannot be broken by a failed capture.
# Derived imagery -- the transition frames -- belongs to
# playthrough/build/transitions/ and is never written here, which is
# what keeps that identity meaningful.
#
# EVERY EXTERNAL STAGE IS BOUNDED by timeout(1) -- the grab, identify,
# the luminance measurement, the crop computation and the OCR read all
# talk to an X server or an OCR engine, and both can stop answering
# without exiting.  An expiry is named as an expiry (timeout exits 124)
# rather than reported as the tool failing, and the EXIT trap still
# withdraws the frame.
#
# THE MODE PRESERVES THE INVARIANT FROM THE OTHER SIDE.  A diagnostic
# capture can never exit 0 and leaves the frames directory exactly as
# it found it, so relaxing a safeguard cannot produce a frame that
# would be counted as part of the record.
#
# TUNABLES -- all optional, all read from the environment, each declared
# with its default and meaning under "Tunables" below.  Every timeout is
# a whole number of seconds from 1 to 3600; 0 is refused because it
# would mean no limit at all.  CLONE_INDEX is read by env.sh and offsets
# the display and every scratch path so parallel checkouts cannot
# capture each other's screens.
#
# WHAT THIS FILE WRITES, EXHAUSTIVELY
#   1. exactly one PNG in playthrough/frames/;
#   2. a withdrawn frame into the reject directory, outside the tree,
#      when a capture fails;
#   3. a private scratch file for the inline reader's stderr, inside the
#      mode-0700 per-clone runtime directory env.sh creates, removed on
#      exit.
# playthrough/frames/ is therefore the ONLY path inside the working tree
# this file writes, which is exactly the surface its contract assigns
# it.  The telemetry row is REPORTED, not written: every field of it
# leaves on stdout and session.py -- which already owns the frame
# counter and the manifest row -- persists it beside that row, so one
# logical record is no longer appended by two processes.  See THE
# TELEMETRY HANDOFF below.  The date audit is likewise REQUESTED rather
# than written here: ocr_clock.py owns that append (--audit) under the
# canonical destination and this file only reports whether the record
# was made.  Nothing else, anywhere.  It sends no keystroke, writes no
# manifest row, touches no save data, starts no server, makes no
# network call, and never runs a command through a shell string: every
# external call is an argument list, there is no eval, and there is no
# unquoted glob.
# ---------------------------------------------------------------------

set -euo pipefail

# errtrace propagates the ERR trap into functions, which turns an
# unexpected failure into a reported line number instead of silence.
# It is a strict addition to `set -euo pipefail`, never a replacement.
set -o errtrace

# The handler is a function so the trap string stays trivial; a
# multi-line single-quoted trap body would embed a literal backslash
# rather than continuing the line.
#
# SC2317 ("command appears to be unreachable") fires on every
# trap-invoked function in this file, because ShellCheck sees no direct
# call site: the caller is the trap, which it does not model.  The
# suppression is scoped to the three handlers that are genuinely reached
# only that way -- nothing else in this file is exempted -- and the same
# directive is used for the same reason in env.sh.
# shellcheck disable=SC2317
_cap_on_error() {
    printf 'playthrough: FATAL: %s\n' \
        "capture.sh failed at line ${2} (exit ${1})" >&2
}
trap '_cap_on_error "$?" "${LINENO}"' ERR

# ---------------------------------------------------------------------
# Locate this file, then load the one definition of the environment.
#
# The root-resolution idiom is the repository's own, from
# build-scripts/clang-tidy-run.sh:8, as launch_game.sh also adopts it.
# ---------------------------------------------------------------------
_cap_script_dir="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd
)"
if [ -z "${_cap_script_dir}" ]; then
    printf '%s\n' "capture.sh: FATAL: cannot resolve my own \
directory" >&2
    exit 2
fi

_cap_env_file="${_cap_script_dir}/env.sh"
if [ ! -f "${_cap_env_file}" ]; then
    printf '%s\n' "capture.sh: FATAL: missing ${_cap_env_file}; the \
headless contract and the artifact layout are defined there and are \
never redefined here" >&2
    exit 8
fi

# env.sh is the SINGLE definition of DISPLAY, SDL_VIDEODRIVER (x11 --
# and the dummy VIDEO backend is banned there and here), SDL_AUDIODRIVER,
# LIBGL_ALWAYS_SOFTWARE, XDG_RUNTIME_DIR and every artifact path.  None
# of it is restated in this file.  Sourcing it also defines the helpers
# used below: playthrough_log, playthrough_warn,
# playthrough_require_tools, playthrough_assert_video_driver and
# playthrough_assert_display.
#
# The `source=` directive lets `shellcheck -x` follow env.sh and check
# every helper and variable used here against it.  SC1091 is suppressed
# only for a plain `shellcheck` run, which cannot follow a sourced file
# at all and would otherwise report the resolved path as unreadable;
# the file's presence is asserted immediately above, so nothing is
# being hidden.
# shellcheck source=playthrough/tooling/env.sh
# shellcheck disable=SC1091
if ! . "${_cap_env_file}"; then
    printf '%s\n' "capture.sh: FATAL: ${_cap_env_file} refused to \
load; fix the environment contract before capturing anything" >&2
    exit 8
fi
unset _cap_script_dir _cap_env_file

# The working directory is the repository root, as it is for every
# stage of this pipeline: --userdir is normalised but not absolutised
# [src/path_info.cpp:105] and the asset roots are working-directory
# relative [src/path_info.cpp:129-136], so the root is the only place
# under which this checkout's own data/ and gfx/ resolve AND the
# artifacts land inside the working tree.  FRAME_FILE below is
# repository-relative and is only correct from here.
cd "${PLAYTHROUGH_REPO_ROOT}"

# ---------------------------------------------------------------------
# Exit codes, named so the call sites read as intent.
# ---------------------------------------------------------------------
readonly EX_OK=0
readonly EX_USAGE=1
readonly EX_LAYOUT=2
readonly EX_CAPTURE=3
readonly EX_BLANK=4
readonly EX_GEOMETRY=5
readonly EX_CLOCK_FAULT=6
readonly EX_EXISTS=7
readonly EX_PREREQ=8
# A diagnostic capture completed and was withdrawn.  Deliberately
# non-zero: the invariant this file guarantees is "exit 0 <=> exactly one
# new frame in playthrough/frames/", so a mode that produces no such
# frame must not be able to report success.
readonly EX_DIAGNOSTIC=9

# ---------------------------------------------------------------------
# Constants.
#
# CLOCK_PATTERN is the ONE definition of the readout in this file, and
# it is character-for-character ocr_clock.py's CLOCK_RE, so the
# delegated read and the fallback read cannot disagree about what a
# clock looks like.  It is deliberately unanchored: it is searched for
# inside OCR text that also holds the rest of the sidebar.
# ---------------------------------------------------------------------
readonly CLOCK_PATTERN='[0-9]{2}:[0-9]{2}:[0-9]{2}'

# The engine cannot render an hour past 23, a minute past 59 or a
# second past 59, so a match outside those bounds is not a clock.  This
# is not pedantry: whole-column OCR of this sidebar has been measured
# returning 48:48:48 and 88:48:48 -- readings that match the pattern
# and are impossible.  They are DECLINED here, never repaired, because
# emitting one would be fabrication.
readonly MAX_HOUR=23
readonly MAX_MINUTE=59
readonly MAX_SECOND=59

# manifest.py refuses an index that would widen the five-digit field
# (MIN_FRAME_INDEX / MAX_FRAME_INDEX), so this file refuses it too
# rather than formatting something the manifest will not accept.  The
# 5-digit zero-padded field is what keeps a lexical sort of the frames
# identical to a numeric one, which is what makes the ffmpeg concat
# list trivially correct.
readonly MIN_FRAME_INDEX=1
readonly MAX_FRAME_INDEX=99999

# ---------------------------------------------------------------------
# STAGE TIMEOUTS.  Every external command here gets a ceiling.
#
# This runs once per keystroke inside a session loop, and every stage
# talks either to an X server or to an OCR engine -- both of which can
# stop answering without exiting.  A wedged `import` waiting on a
# display that has gone away, or a tesseract child that never returns,
# would hang the capture indefinitely: the game stays running, the
# session makes no further progress, nothing is written and no error is
# reported.  A hung tool is a fault to report, not a reason to wait
# forever, so each stage is bounded and an expiry is named as an expiry.
#
# The values are generous multiples of what the stages actually take --
# a root-window grab and a luminance measurement are sub-second, and a
# full row-wise OCR pass over the sidebar column is a few seconds -- so
# a timeout here always means something is wrong rather than slow.
# `timeout` exits 124 when it fires, which is how the expiry is told
# apart from the tool's own non-zero status.
# ---------------------------------------------------------------------
readonly TIMEOUT_EXPIRED=124
readonly DEFAULT_GRAB_TIMEOUT=60
readonly DEFAULT_IDENTIFY_TIMEOUT=30
readonly DEFAULT_LUMA_TIMEOUT=60
readonly DEFAULT_GEOMETRY_TIMEOUT=60
readonly DEFAULT_OCR_TIMEOUT=300

# TWO WORKED EXAMPLES OF THE CROP, AND NEITHER IS A FALLBACK.
#
# Both are recorded here as documentation and quoted in the diagnostics
# that explain why neither is substituted.  THEY ARE NEVER USED AS A
# VALUE.  There are two because the rectangle depends on which sidebar
# layout the engine is drawing, and a fresh userdir and a userdir that
# has selected another preset do not agree:
#
#   * a FRESH userdir renders the engine's constructor default,
#     legacy_labels_sidebar at 44 cells [src/panels.cpp:412-418;
#     data/json/ui/sidebar-legacy-labels.json], giving
#     352x1072+1568+4 -- that is the example describing a run against a
#     userdir with no config/panel_options.json, which is this
#     pipeline's own starting state;
#   * a userdir whose panel options select custom_sidebar renders 36
#     cells [data/json/ui/sidebar.json:7], giving 288x1072+1632+4.
#
# A single literal was previously carried here as a last-resort
# fallback, which was wrong twice over: it is correct for ONE layout
# only, and the moment it would be reached is precisely the moment
# nothing has confirmed which layout this run is drawing.  Twelve
# widgets across data/json/ui declare "style": "sidebar" at eight
# distinct widths (nine of the twelve files sit at the top level), so
# the wrong column is a real possibility, and cropping it reads as an
# unreadable clock rather than as an error: every duration falls to the
# 0.25 s floor while every count still tallies, and the movie is
# plausible and meaningless.  A crop that cannot be computed is
# therefore fatal (EX_GEOMETRY), and an operator who wants a fixed
# rectangle asks for one by name with PLAYTHROUGH_CAPTURE_RECT.
#
# The next constants are EXAMPLES of the geometry form
# PLAYTHROUGH_CAPTURE_RECT takes, quoted in the diagnostics below so an
# operator setting one has the shape in front of them.  Neither is a
# fallback: nothing substitutes them, and each is stated with its layout
# because the right rectangle depends on the sidebar preset in force
# (the engine default legacy_labels_sidebar at 44 cells
# [src/panels.cpp:412-418] computes to 352x1072+1568+4; the 36-cell
# custom_sidebar to 288x1072+1632+4).  sidebar_geometry.py resolves
# whichever this run needs, and a failure there is a stop.
readonly EXAMPLE_RECT='288x1072+1632+4'
readonly EXAMPLE_RECT_LAYOUT='a 36-cell custom_sidebar'
readonly DEFAULT_LAYOUT_RECT='352x1072+1568+4'
readonly DEFAULT_LAYOUT_NAME='legacy_labels_sidebar (44 cells)'

# An ImageMagick geometry, and a bare non-negative decimal number as
# ImageMagick's fx: operators print one.  The numeric guard matters:
# awk compares a non-numeric string against 0 as STRINGS, so "nan" > 0
# would be true and a blank frame could pass the luminance gate.
readonly GEOMETRY_RE='^[0-9]+x[0-9]+\+[0-9]+\+[0-9]+$'
readonly NUMBER_RE='^[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$'

# manifest.py's real_ts form: UTC, millisecond precision, "Z"-suffixed,
# e.g. 2026-05-14T09:12:03.481Z.  Asserted rather than assumed because
# %3N is a GNU date extension and a shell that lacks it leaves the
# format specifier in the output, which would be a fabricated instant.
readonly REAL_TS_RE='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}\.[0-9]{3}Z$'

readonly GEOMETRY_SCRIPT="${PLAYTHROUGH_TOOLING_DIR}/sidebar_geometry.py"
readonly OCR_SCRIPT="${PLAYTHROUGH_TOOLING_DIR}/ocr_clock.py"

# ---------------------------------------------------------------------
# Tunables, resolved once.
#
# The settle comes from env.sh so a single edit moves every stage.  DO
# NOT TRIM IT AS DEAD TIME: the game redraws asynchronously, and
# capturing before the redraw lands photographs the PREVIOUS frame,
# which shifts every clock reading by one keystroke and quietly
# mis-times the whole movie.
# ---------------------------------------------------------------------
SETTLE="${PLAYTHROUGH_CAPTURE_SETTLE:-${PLAYTHROUGH_SETTLE_SECONDS}}"
# on | off -- whether the clock is read at all.
CLOCK_MODE="${PLAYTHROUGH_CAPTURE_CLOCK:-on}"
# auto | off | always -- auto reads the coarse sidebar phrase only when
# there was no clock to read.
PHRASE_MODE="${PLAYTHROUGH_CAPTURE_PHRASE:-auto}"
# 1 | 0 -- 1 makes a clock FAULT fatal, because the two faults that
# actually happen (an off-contract 24_HOUR, an absent OCR toolchain)
# would poison every later frame while every count still tallied.
STRICT_CLOCK="${PLAYTHROUGH_CAPTURE_STRICT_CLOCK:-1}"
# 0 | 1 -- 1 recaptures an index that already holds a frame, so a
# success REPLACES rather than adds.  See THE RESERVATION IS ATOMIC.
OVERWRITE="${PLAYTHROUGH_CAPTURE_OVERWRITE:-0}"
# An explicit WxH+X+Y crop.  This is the ONLY way a fixed rectangle is
# ever used: an operator decision, recorded as CLOCK_RECT_FROM=override,
# never a silent fallback.
RECT_OVERRIDE="${PLAYTHROUGH_CAPTURE_RECT:-}"
# `${VAR-default}` rather than `${VAR:-default}` on the timeouts below:
# a variable that is set but EMPTY is an operator mistake, and
# defaulting it silently would hide the mistake behind a working run.
#
# on | off -- ask ocr_clock.py to append this frame's date evidence to
# the sidecar timeline.py reads, and where that sidecar lives.  The
# path is nominated here but written by the delegate, and a production
# capture accepts ONLY the canonical destination: see THE DATE AUDIT
# GOES WHERE timeline.py LOOKS.  A DIAGNOSTIC capture defaults this to
# `off` further down -- the mode is not known yet here -- because a
# withdrawn frame owes no row: see A DIAGNOSTIC CAPTURE OWES NO AUDIT
# ROW beside the validation.
AUDIT_MODE="${PLAYTHROUGH_CAPTURE_AUDIT:-on}"
AUDIT_PATH="${PLAYTHROUGH_CAPTURE_AUDIT_PATH:-${PLAYTHROUGH_DATE_AUDIT}}"
GRAB_TIMEOUT="${PLAYTHROUGH_CAPTURE_GRAB_TIMEOUT-${DEFAULT_GRAB_TIMEOUT}}"
IDENTIFY_TIMEOUT="\
${PLAYTHROUGH_CAPTURE_IDENTIFY_TIMEOUT-${DEFAULT_IDENTIFY_TIMEOUT}}"
LUMA_TIMEOUT="${PLAYTHROUGH_CAPTURE_LUMA_TIMEOUT-${DEFAULT_LUMA_TIMEOUT}}"
GEOMETRY_TIMEOUT="\
${PLAYTHROUGH_CAPTURE_GEOMETRY_TIMEOUT-${DEFAULT_GEOMETRY_TIMEOUT}}"
OCR_TIMEOUT="${PLAYTHROUGH_CAPTURE_OCR_TIMEOUT-${DEFAULT_OCR_TIMEOUT}}"

# Set when ocr_clock.py's own dependency preflight fails and strict
# mode is off: the delegate is then skipped in favour of the inline
# reader, rather than being called once per field to fail twice.
OCR_PREFLIGHT_FAILED=0

# The telemetry sidecar this frame's row BELONGS IN, reported to the
# caller that appends it.  This file does not write it -- see THE
# TELEMETRY HANDOFF below -- and there is deliberately NO override: the
# destination is env.sh's canonical path, which is where timeline.py
# looks, and a redirectable evidence path is a way to write a row
# nothing downstream will ever read (or to grow some other file).
OBSERVATIONS="${PLAYTHROUGH_OBSERVATIONS}"

# THE MODE, and why one exists at all.
#
# Six properties of this script are what make its output evidence
# rather than merely a picture: the full settle, an attempted clock
# read, a fault treated as fatal, an index that is never reused, a date
# audit that lands where timeline.py reads it, and a TRUSTED
# environment -- env.sh's PLAYTHROUGH_TRUST_STATE, which says whether
# any check that stands behind the frame has been relaxed.  All six had
# correct defaults and all six were reachable through the environment,
# which means a production run could be made to produce an apparently
# successful, non-compliant frame -- a stale screenshot with no
# reading, a replacement for a frame already counted, real date
# evidence filed where nothing reads it, or a photograph taken through
# a tool another account can rewrite -- with every downstream count
# still tallying.  Correct-by-default is not the same as enforced, and
# a guard that can be switched off is not a guard.
#
# So the six are now HARD-ENFORCED whenever this script is producing a
# frame for the record, and relaxing any of them requires
# PLAYTHROUGH_CAPTURE_MODE=diagnostic, which cannot produce one:
#
#   production  (default)  the six safeguards are unconditional; any
#                          attempt to relax one is a usage error naming
#                          this variable.  exit 0 means exactly one new
#                          frame is in playthrough/frames/.
#   diagnostic             the first four are tunable, the audit may be
#                          nominated elsewhere and a trust bypass is
#                          tolerated, and in exchange the
#                          captured PNG is WITHDRAWN out of the working
#                          tree before this script returns, FRAME_FILE
#                          and FRAME_PATH are emitted EMPTY, and the
#                          exit status is EX_DIAGNOSTIC -- never 0.  A
#                          caller that treats exit 0 as licence to
#                          append one manifest row therefore cannot
#                          accept a diagnostic capture, and there is no
#                          repository-relative path for it to record
#                          even if it tried.
CAPTURE_MODE="${PLAYTHROUGH_CAPTURE_MODE:-production}"

# Withdrawn frames are kept OUTSIDE the working tree.  Inside it they
# would be re-included by the terminal `!/playthrough/**` negation in
# .gitignore and could be committed as if they were session frames.
#
# They default into env.sh's PRIVATE RUNTIME ROOT rather than into
# /tmp/playthrough-rejected<index>, and that is a privacy fix rather
# than tidiness: a withdrawn frame is a full-resolution photograph of
# the session -- the survivor's screen, the whole display -- and the old
# location was a predictable name in a world-writable directory, holding
# world-readable files.  The runtime root is a 0700 directory this user
# owns, verified before use, and this script sets a private umask below
# so nothing it writes there is readable by anyone else either.
REJECT_DIR="${PLAYTHROUGH_CAPTURE_REJECT_DIR:-${PLAYTHROUGH_REJECT_DIR}}"

# EVERY file this script creates is private.
#
# The frames are committed to git, which records only the executable
# bit, so a private mode on disk costs the pipeline nothing -- while a
# world-readable withdrawn frame or temporary capture in a shared
# directory would leak the display to any local account.  Set once, here,
# so no individual creation site can forget it.
umask 077

# ---------------------------------------------------------------------
# Reporting.
#
# die() does not call env.sh's playthrough_die: that function RETURNS 1
# by design, because env.sh is sourced and an `exit` there would kill an
# interactive caller's shell.  Here an exit with a specific, documented
# code is exactly what is wanted, so the message is printed directly in
# the same format.  The EXIT trap installed below withdraws the frame.
# ---------------------------------------------------------------------
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

# The machine-readable channel is assembled by `line KEY VALUE` and
# written in ONE printf at the very end of this file -- see OUTPUT,
# THEN THE LOG, THEN THE COMMIT POINT.  There is deliberately no
# per-key writer: writing keys as they were computed is what allowed a
# half-delivered contract to sit beside a frame this script had already
# decided to keep.

usage() {
    # The one place this file writes prose to stdout, and only when
    # explicitly asked for help.
    cat <<'USAGE'
capture.sh -- one keystroke, one screenshot, one clock reading.

usage:
    FRAME_INDEX=<n> playthrough/tooling/capture.sh
    playthrough/tooling/capture.sh --help

FRAME_INDEX is required and must be a plain decimal integer from 1 to
99999 with no sign, no leading zero and no surrounding space.  It is
supplied by session.py, which owns the frame counter; this script never
derives one.

Writes exactly one playthrough/frames/frame_%05d.png -- the only path
inside the working tree it writes at all -- and REPORTS this frame's
telemetry row, the clock and the sidebar date line that timeline.py
cross-checks its rollover decisions against, for session.py to persist
to playthrough/build/observations.jsonl beside the manifest row it
already owns.  Prints KEY=value lines on stdout and everything else on
stderr.  See the header of this file for the full output contract, the
exit codes and the tunables.

The default mode is production, in which the 0.3s settle, the clock
read, fatal fault handling and the refusal to reuse an index are all
unconditional.  PLAYTHROUGH_CAPTURE_MODE=diagnostic relaxes them and in
exchange withdraws the frame out of the working tree and exits 9, so a
diagnostic capture can never be recorded as a session frame.
USAGE
}

# ---------------------------------------------------------------------
# The frames-directory guarantee.
#
# GRABBED becomes 1 the instant a PNG this invocation wrote is in place,
# and KEPT becomes 1 only once the frame has passed every check and is
# ours to keep.  The EXIT trap withdraws anything grabbed but not kept,
# and restores anything that was moved aside, so a non-zero exit always
# leaves playthrough/frames/ exactly as it was found.
#
# That is what makes the invariant at the top of this file structural
# rather than merely intended -- `exit 0 <=> exactly one new frame` in
# production mode, and exactly one frame written at the requested index
# when overwrite mode was asked for -- and it is why session.py can
# treat a successful return as licence to append exactly one manifest
# row.
# ---------------------------------------------------------------------
GRABBED=0
KEPT=0
BACKUP=""
FRAME_PATH=""
# The exclusive temporary file the grab writes to before it is renamed
# into place.  Emptied on publish, so the trap only ever withdraws one
# that is genuinely still unpublished.
CAPTURE_TMP=""

# Files one rejected capture out of the frames directory.  Reached only
# from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
file_rejected() {
    local src="$1" name="$2" target
    # A zero-byte file is the reservation placeholder, or a grab that
    # wrote nothing: there is no image to inspect, so it is released
    # rather than filed as though it were evidence.
    if [ ! -s "${src}" ]; then
        rm -f -- "${src}" 2>/dev/null || true
        return 0
    fi
    # Keep the rejected capture: it is the evidence of whatever went
    # wrong.  Outside the working tree, so it can never be mistaken for
    # -- or committed as -- a session frame, and inside the private 0700
    # runtime root, because a rejected capture is still a photograph of
    # the whole session screen and is nobody else's business.
    target="${REJECT_DIR}/${name}"
    if playthrough_secure_dir "${REJECT_DIR}" 700 2>/dev/null &&
       mv -f -- "${src}" "${target}" 2>/dev/null; then
        chmod 600 -- "${target}" 2>/dev/null || true
        playthrough_warn "withdrew ${src} from the frames directory" \
            "and kept it at ${target} for inspection"
    else
        rm -f -- "${src}" 2>/dev/null || true
        playthrough_warn "withdrew and discarded ${src};" \
            "${REJECT_DIR} could not be written"
    fi
}

# Where a delegated stage's stderr is kept while it runs, so that a
# failure can be DIAGNOSED instead of merely reported.  It lives in the
# private per-clone runtime directory that env.sh creates at mode 0700
# with an ownership check -- NOT in the working tree, which this file
# does not write to outside playthrough/frames/, and not at a
# predictable shared /tmp path.  $$ keeps two concurrent captures apart.
#
# A FILE, not `2>&1`, and that is the whole point: these stages print
# their VALUE on stdout and their warnings on stderr, and merging the
# two would feed a warning to whatever parses the value.  Both stages
# here legitimately warn on a successful run -- sidebar_geometry.py
# announces every configuration value it had to default -- so the
# streams stay separate and the warnings are relayed afterwards.
STAGE_ERR="${PLAYTHROUGH_RUNTIME_DIR}/capture-stage-$$.err"
# A generous excerpt that still cannot bury the session log: tesseract
# can emit a page of warnings per frame.
readonly STAGE_ERR_BYTES=2000

# stage_stderr -- a bounded, single-line excerpt of the last stage's
# stderr, or the empty string.  NUL bytes are dropped because a stage
# that fails mid-PNG can emit them, blank lines are dropped because they
# carry nothing, and newlines become spaces so one warning stays one
# line in the session log.
stage_stderr() {
    [ -s "${STAGE_ERR}" ] || return 0
    tr -d '\000' <"${STAGE_ERR}" 2>/dev/null |
        grep -v '^[[:space:]]*$' |
        head -c "${STAGE_ERR_BYTES}" |
        tr '\n' ' ' || true
}

# Reached only from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
withdraw() {
    # Everything this invocation put in the frames directory leaves it,
    # published or not.  The unpublished temporary capture goes FIRST, so
    # that a failure while filing the published frame cannot leave the
    # temporary one behind -- and it is KEPT under the frame's own name
    # rather than discarded, because the checks that reject a capture
    # before it is published (wrong format, wrong geometry, a blank
    # screen) are precisely the ones whose evidence has to be looked at.
    if [ -n "${CAPTURE_TMP}" ] && [ -e "${CAPTURE_TMP}" ]; then
        file_rejected "${CAPTURE_TMP}" \
            "${FRAME_NAME:-rejected-capture.png}"
    fi
    CAPTURE_TMP=""
    if [ "${GRABBED}" -eq 1 ] && [ -e "${FRAME_PATH}" ]; then
        file_rejected "${FRAME_PATH}" "$(basename "${FRAME_PATH}")"
    fi
    GRABBED=0
    if [ -n "${BACKUP}" ] && [ -e "${BACKUP}" ]; then
        if mv -f "${BACKUP}" "${FRAME_PATH}" 2>/dev/null; then
            playthrough_warn "restored the frame that was already at" \
                "${FRAME_PATH}"
        else
            playthrough_warn "could not restore ${BACKUP} to" \
                "${FRAME_PATH}; the earlier frame is still at" \
                "${BACKUP}"
        fi
    fi
    BACKUP=""
}

# Reached only from the EXIT trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
_cap_on_exit() {
    if [ "$1" -ne 0 ] && [ "${KEPT}" -eq 0 ]; then
        withdraw
    fi
    # The scratch stderr file is this invocation's alone and carries
    # nothing that is not already in the warning it produced.
    rm -f "${STAGE_ERR}" 2>/dev/null || true
}
trap '_cap_on_exit "$?"' EXIT

# A KILLING SIGNAL MUST WITHDRAW THE FRAME TOO, and the EXIT trap alone
# does not achieve that: a shell terminated BY a signal never reaches
# its EXIT trap, so without these handlers a frame would be left behind
# by exactly the case F02 is about -- session.py reading this output
# through a pipe and going away, whereupon the next `emit` takes SIGPIPE
# and this process dies mid-contract.  Measured before this trap
# existed: the PNG survived in playthrough/frames/ with no manifest row
# to describe it, which is the orphan the 1:1 invariant cannot tolerate.
#
# Each handler converts the signal into an ordinary non-zero exit, which
# then runs the EXIT trap and withdraws the frame through the one code
# path that knows how.  The conventional 128+N status is preserved so a
# caller can still tell WHICH signal ended the capture.
#
# Reached only from a trap; see the SC2317 note at the top.
# shellcheck disable=SC2317
_cap_on_signal() {
    local name="$1" status="$2"
    # stderr, never stdout: stdout is the stream that just broke.
    playthrough_warn "capture of ${FRAME_FILE:-the frame} was ended by" \
        "SIG${name}; withdrawing it so no frame is left that no" \
        "manifest row describes"
    exit "${status}"
}
trap '_cap_on_signal PIPE 141' PIPE
trap '_cap_on_signal INT 130' INT
trap '_cap_on_signal TERM 143' TERM
trap '_cap_on_signal HUP 129' HUP

# ---------------------------------------------------------------------
# Arguments.  There is exactly one input -- FRAME_INDEX in the
# environment -- so the only accepted argument is a request for help.
# Anything else is a usage error rather than something to interpret.
# ---------------------------------------------------------------------
if [ "$#" -gt 0 ]; then
    case "$1" in
        -h|--help|help)
            usage
            exit "${EX_OK}"
            ;;
        *)
            printf 'playthrough: FATAL: %s\n' \
                "capture.sh takes no arguments; the frame index is \
passed as FRAME_INDEX in the environment.  Got: $*" >&2
            usage >&2
            exit "${EX_USAGE}"
            ;;
    esac
fi

# ---------------------------------------------------------------------
# Validate the index STRICTLY.  It is not defaulted, not derived and
# not coerced.
#
# The pattern is ^[1-9][0-9]*$, and excluding a leading zero is
# load-bearing rather than fussy: bash's printf parses a zero-prefixed
# argument as OCTAL.  Measured on this host, `printf '%05d' 010` prints
# 00008 -- frame 10 would be filed as frame 8, overwriting it -- and
# `printf '%05d' 09` fails outright with "invalid octal number".  Both
# outcomes corrupt the one-frame-per-keystroke identity, and the second
# would do it noisily while the first would do it in silence.
# ---------------------------------------------------------------------
if [ -z "${FRAME_INDEX:-}" ]; then
    printf 'playthrough: FATAL: %s\n' \
        "FRAME_INDEX is not set.  session.py owns the frame counter \
and passes the index in; this script never invents one." >&2
    exit "${EX_USAGE}"
fi

# A single anchored regular expression, so nothing can slip past on a
# glob subtlety: no sign, no leading zero, no space, no digit group
# separator, no trailing character of any kind.
if ! [[ "${FRAME_INDEX}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'playthrough: FATAL: %s\n' \
        "FRAME_INDEX='${FRAME_INDEX}' is not a plain positive decimal \
integer.  A sign, a leading zero, whitespace or any other character is \
refused: bash printf reads '010' as octal 8 and would file frame 10 \
over frame 8, silently." >&2
    exit "${EX_USAGE}"
fi

if [ "${FRAME_INDEX}" -lt "${MIN_FRAME_INDEX}" ] ||
   [ "${FRAME_INDEX}" -gt "${MAX_FRAME_INDEX}" ]; then
    printf 'playthrough: FATAL: %s\n' \
        "FRAME_INDEX=${FRAME_INDEX} is outside ${MIN_FRAME_INDEX}..\
${MAX_FRAME_INDEX}.  manifest.py refuses an index that would widen the \
five-digit field, and a wider field would break the lexical sort the \
concat list depends on." >&2
    exit "${EX_USAGE}"
fi

# ---------------------------------------------------------------------
# The one canonical filename.
#
# PLAYTHROUGH_FRAME_FORMAT is env.sh's 'frame_%05d.png' and is the same
# format manifest.py builds its `file` field from, so the capture, the
# manifest row and the concat list agree byte for byte.  `printf --`
# guards against a format that begins with a dash.
#
# SC2059 objects to a variable used as a printf format.  Here that is
# the entire point: the format is env.sh's single definition, shared
# with manifest.py, and inlining a second copy of '%05d' is exactly the
# divergence this indirection exists to prevent.  The expansion is
# asserted immediately below.
# ---------------------------------------------------------------------
# shellcheck disable=SC2059
FRAME_NAME="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}" "${FRAME_INDEX}")"
FRAME_PATH="${PLAYTHROUGH_FRAMES_DIR}/${FRAME_NAME}"
FRAME_FILE="playthrough/frames/${FRAME_NAME}"

if [ "${FRAME_NAME}" = "${PLAYTHROUGH_FRAME_FORMAT}" ]; then
    die "${EX_LAYOUT}" "PLAYTHROUGH_FRAME_FORMAT=\
'${PLAYTHROUGH_FRAME_FORMAT}' did not expand; env.sh must supply a \
printf format containing %05d"
fi

# ---------------------------------------------------------------------
# Validate the tunables.  A typo must not silently disable a guard --
# PLAYTHROUGH_CAPTURE_CLOCK=of would otherwise read as "not off".
# ---------------------------------------------------------------------
case "${CAPTURE_MODE}" in
    production|diagnostic) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_MODE=\
'${CAPTURE_MODE}' is neither 'production' nor 'diagnostic'" ;;
esac
case "${CLOCK_MODE}" in
    on|off) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_CLOCK=\
'${CLOCK_MODE}' is neither 'on' nor 'off'" ;;
esac
case "${PHRASE_MODE}" in
    auto|off|always) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_PHRASE=\
'${PHRASE_MODE}' is not one of auto, off, always" ;;
esac
case "${STRICT_CLOCK}" in
    0|1) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=\
'${STRICT_CLOCK}' is neither 0 nor 1" ;;
esac
case "${OVERWRITE}" in
    0|1) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_OVERWRITE=\
'${OVERWRITE}' is neither 0 nor 1" ;;
esac
if ! [[ "${SETTLE}" =~ ${NUMBER_RE} ]]; then
    die "${EX_USAGE}" "the settle is '${SETTLE}', which is not a \
non-negative number of seconds; env.sh supplies \
PLAYTHROUGH_SETTLE_SECONDS and PLAYTHROUGH_CAPTURE_SETTLE overrides it"
fi
if [ -n "${RECT_OVERRIDE}" ] &&
   ! [[ "${RECT_OVERRIDE}" =~ ${GEOMETRY_RE} ]]; then
    die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_RECT=\
'${RECT_OVERRIDE}' is not an ImageMagick WxH+X+Y geometry"
fi

# Every stage ceiling is validated before any of them is used, because
# these values reach `timeout` directly: a non-numeric one would make
# timeout itself fail with a usage error on every single frame, and a
# zero would mean "no limit at all", quietly restoring the unbounded
# behaviour the ceilings exist to remove.
_cap_check_timeout() {
    local name="$1" value="$2"
    if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
        die "${EX_USAGE}" "${name}='${value}' is not a plain decimal \
number of seconds"
    fi
    # 10# forces base ten so a padded 060 is sixty, not octal.
    if [ "$((10#${value}))" -lt 1 ] ||
       [ "$((10#${value}))" -gt 3600 ]; then
        die "${EX_USAGE}" "${name}='${value}' is outside the supported \
range of 1 to 3600 seconds; 0 would mean no limit at all, which is the \
unbounded wait these ceilings exist to prevent"
    fi
}
# A DIAGNOSTIC CAPTURE OWES NO AUDIT ROW, and must not leave one.
#
# THE DEFECT THIS CLOSES.  A diagnostic capture is withdrawn out of the
# working tree and emits no repository-relative path precisely so that it
# can never be mistaken for a frame of the record -- but the date audit
# was resolved before the mode was even read, so the withdrawn frame
# still appended a row to the sidecar timeline.py reads.  A runtime QA
# pass found three of them in the committed playthrough/build/
# frame_dates.jsonl, each keyed to the reserved index 99999 and each
# naming playthrough/frames/frame_99999.png -- a file that does not exist
# and never did.  They assert nothing (every value is null) and
# timeline.py ignores them, keying its date decisions off the manifest's
# own rows, so nothing downstream was wrong; a committed audit sidecar
# holding records about files that do not exist is still a traceability
# claim nobody should have to explain.
#
# So the audit is FORCED off for a diagnostic capture, and asking for
# one is refused rather than honoured.
#
# THE SECOND DEFECT, AND THE REASON THE DEFAULT WAS NOT ENOUGH.  A
# later security review found that this only DEFAULTED the audit off:
# PLAYTHROUGH_CAPTURE_AUDIT=on was still permitted in diagnostic mode,
# and the canonical-destination check below sat inside the
# production-only block.  So a diagnostic capture could append
# audit-shaped JSON to any regular file under playthrough/ -- the
# manifest, a transcript, a save, a PNG, an MP4 -- while its own frame
# was withdrawn out of the working tree, leaving a written line and no
# photograph to account for it.  The report's own reproduction was
#
#     PLAYTHROUGH_CAPTURE_MODE=diagnostic \
#     PLAYTHROUGH_CAPTURE_AUDIT=on \
#     PLAYTHROUGH_CAPTURE_AUDIT_PATH=playthrough/manifest.jsonl \
#     FRAME_INDEX=99999 playthrough/tooling/capture.sh
#
# The row was never lost information anyway: the reading is in this
# invocation's own payload, which is what a caller asks a diagnostic
# capture for, and DATE_AUDIT=off says plainly that nothing was
# appended.  A diagnostic capture that could write evidence is a
# contradiction in terms, so ASKING FOR an audit is refused here and the
# canonical-destination check has moved OUT of the production-only
# block, where it applies whenever the audit is on at all.
#
# THE THIRD DEFECT, AND WHY "off" IS ACCEPTED RATHER THAN REFUSED.  The
# refusal above was written against the PRESENCE of the variable, at any
# value -- and "off" is not a request for an audit, it is agreement with
# the value this mode forces two lines below.  Refusing it broke the one
# caller in the pipeline: launch_game.sh's verify_resume_ui_state()
# invokes this script with PLAYTHROUGH_CAPTURE_MODE=diagnostic and
# PLAYTHROUGH_CAPTURE_AUDIT=off, stating at its own call site that the
# probe owes no audit row so that the probe cannot acquire one by a
# change of default here.  That invocation exited EX_USAGE instead of
# EX_DIAGNOSTIC, the launcher read the unexpected status as "the screen
# could not be read", and every resumed launch recorded
# INITIAL_UI_STATE=unverified -- so the mandatory proof that a resumed
# launch reached the expected load UI was structurally disabled, by two
# scripts disagreeing about one variable.  A code review found it.
#
# So the two halves of the contract are separated, and this is now ONE
# diagnostic API both scripts hold to:
#
#   * PLAYTHROUGH_CAPTURE_AUDIT=off      -- accepted.  It cannot enable
#     anything: it names the value this mode forces anyway, and saying
#     it at a call site documents the intent where the reader is.
#   * PLAYTHROUGH_CAPTURE_AUDIT=on       -- refused.  That is the
#     request the two defects above were about.
#   * PLAYTHROUGH_CAPTURE_AUDIT_PATH=... -- refused at ANY value,
#     including alongside "off": naming a destination is asking for a
#     row to be written to it, and a diagnostic capture writes none.
#   * anything else                      -- refused by the on|off case
#     below, which every mode shares.
if [ "${CAPTURE_MODE}" = "diagnostic" ]; then
    if [ "${PLAYTHROUGH_CAPTURE_AUDIT:-off}" != "off" ] ||
       [ -n "${PLAYTHROUGH_CAPTURE_AUDIT_PATH:-}" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT\
${PLAYTHROUGH_CAPTURE_AUDIT:+=\"${PLAYTHROUGH_CAPTURE_AUDIT}\"}\
${PLAYTHROUGH_CAPTURE_AUDIT_PATH:+ / PLAYTHROUGH_CAPTURE_AUDIT_PATH=\"\
${PLAYTHROUGH_CAPTURE_AUDIT_PATH}\"} cannot be used with \
PLAYTHROUGH_CAPTURE_MODE=diagnostic.  A diagnostic frame is withdrawn \
out of the working tree precisely so that it is not evidence, and a \
capture that writes an audit row while its own photograph is withdrawn \
leaves a record with nothing to account for it.  The reading is in this \
invocation's payload; the sidecar is written only by a capture that \
keeps its frame.  Only PLAYTHROUGH_CAPTURE_AUDIT=off is accepted here, \
and it is accepted because it asks for exactly what this mode does \
anyway."
    fi
    AUDIT_MODE="off"
fi
case "${AUDIT_MODE}" in
    on|off) ;;
    *) die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT=\
'${AUDIT_MODE}' is neither on nor off" ;;
esac
if [ "${AUDIT_MODE}" = "on" ]; then
    if [ -z "${AUDIT_PATH}" ]; then
        die "${EX_USAGE}" "the date-audit sidecar path is empty; env.sh \
exports PLAYTHROUGH_DATE_AUDIT and PLAYTHROUGH_CAPTURE_AUDIT_PATH \
overrides it"
    fi
    # THE DATE AUDIT GOES WHERE timeline.py LOOKS, IN EVERY MODE.
    #
    # This check used to live in the production-only block below, which
    # made "which file does this append to" a question only a production
    # capture had to answer -- and the audit is the one destination a
    # capture nominates, so that was the whole gap.  Every artifact of
    # this pipeline lives under playthrough/, so a merely CONTAINED path
    # is not a safe one: the manifest, both transcripts, a save file, a
    # frame and both MP4s are all contained.  ocr_clock.py refuses
    # anything but the canonical sidecar too, and this refusal is the
    # earlier of the two -- before the display is touched and before any
    # file exists.
    if [ "${AUDIT_PATH}" != "${PLAYTHROUGH_DATE_AUDIT}" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT_PATH=\
'${AUDIT_PATH}' is not the sidecar timeline.py reads \
(${PLAYTHROUGH_DATE_AUDIT}), and no other destination is accepted.  \
Every artifact of this pipeline is inside playthrough/, so a contained \
path is not a safe one: a line of audit-shaped JSON appended to the \
manifest, a transcript, a save or a frame would be evidence nobody \
wrote.  A frame's date evidence recorded anywhere else is also evidence \
nothing consults -- the rollover guard then treats this frame's date as \
UNKNOWN while every count still tallies."
    fi
fi

_cap_check_timeout PLAYTHROUGH_CAPTURE_GRAB_TIMEOUT "${GRAB_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_IDENTIFY_TIMEOUT \
    "${IDENTIFY_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_LUMA_TIMEOUT "${LUMA_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_GEOMETRY_TIMEOUT \
    "${GEOMETRY_TIMEOUT}"
_cap_check_timeout PLAYTHROUGH_CAPTURE_OCR_TIMEOUT "${OCR_TIMEOUT}"

# `timeout` is what bounds every stage, so its absence is a missing
# prerequisite rather than something to work around: carrying on without
# it would silently restore the unbounded waits.
if ! command -v timeout >/dev/null 2>&1; then
    die "${EX_PREREQ}" "timeout(1) is not installed, so no capture \
stage could be bounded; it ships with GNU coreutils"
fi

# The audit directory is checked BEFORE anything is captured, so a
# missing one costs no frame.  It is not created here: this file writes
# only into playthrough/frames/, and directory creation belongs to
# playthrough_mkdirs in env.sh.  Nor is auditing quietly switched off,
# because the date is the only evidence that tells a midnight rollover
# from a misread clock, and losing it silently is how a 22-hour day gets
# invented downstream.
if [ "${AUDIT_MODE}" = "on" ]; then
    _cap_audit_dir="$(dirname "${AUDIT_PATH}")"
    if [ ! -d "${_cap_audit_dir}" ]; then
        die "${EX_PREREQ}" "the date-audit directory \
${_cap_audit_dir} does not exist, so this frame's date evidence could \
not be recorded.  Run playthrough_mkdirs (playthrough/tooling/env.sh) \
first, or set PLAYTHROUGH_CAPTURE_AUDIT=off to capture without the \
evidence timeline.py uses to tell a rollover from a misread clock."
    fi
    unset _cap_audit_dir
fi

# Assembled once, expanded as an array so an empty audit configuration
# contributes no argument at all rather than an empty string that
# ocr_clock.py would have to reject.
#
# --audit-sha256 is appended LATER, beside the digest itself, because the
# frame does not exist yet at this point: see BINDING THE DATE ROW TO THE
# PIXELS below.  A row that named no digest would leave the consumer
# unable to tell a reading of this frame from a reading of whatever file
# later occupied the index.
AUDIT_ARGS=()
if [ "${AUDIT_MODE}" = "on" ]; then
    AUDIT_ARGS=(--audit "${AUDIT_PATH}" --audit-frame "${FRAME_INDEX}")
fi

# ---------------------------------------------------------------------
# HARD-ENFORCE THE SIX SAFEGUARDS ON THE PRODUCTION PATH.
#
# Each refusal names the property, the consequence of relaxing it, and
# the one mode in which it is legal.  Refusing here -- before the
# display is touched and before any file is created -- means a
# misconfigured production run produces nothing at all rather than a
# frame that looks like every other frame and is not evidence.
#
# A settle LONGER than the contract is allowed: waiting more cannot
# photograph a screen that has not finished redrawing.  A shorter one
# can, and does, which is why only the lower bound is enforced.  The
# comparison is done with awk because the settle is a decimal and the
# shell has no floating-point test.
# ---------------------------------------------------------------------
if [ "${CAPTURE_MODE}" = "production" ]; then
    if ! awk -v got="${SETTLE}" -v want="${PLAYTHROUGH_SETTLE_SECONDS}" \
            'BEGIN { exit !(got + 0 >= want + 0) }'; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_SETTLE=${SETTLE} is \
shorter than the contracted ${PLAYTHROUGH_SETTLE_SECONDS}s settle.  \
The game redraws asynchronously: grabbing early photographs the screen \
as it was BEFORE the key landed, so every clock reading would be one \
keystroke stale and the whole film mis-timed -- while every count still \
tallied.  A LONGER settle is accepted; a shorter one needs \
PLAYTHROUGH_CAPTURE_MODE=diagnostic, which cannot produce a frame for \
the record."
    fi
    if [ "${CLOCK_MODE}" != "on" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_CLOCK=\
'${CLOCK_MODE}' cannot be used for a frame that is kept.  Each frame's \
on-screen duration IS the sidebar clock delta between it and its \
successor, so a frame captured with the clock read switched off has no \
duration to derive and would silently fall to the floor.  Use \
PLAYTHROUGH_CAPTURE_MODE=diagnostic to look at a frame without reading \
it."
    fi
    if [ "${STRICT_CLOCK}" -ne 1 ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=\
${STRICT_CLOCK} cannot be used for a frame that is kept.  A FAULT is \
not an unreadable clock: the faults that actually happen -- an \
off-contract 24_HOUR option, a missing OCR toolchain -- are standing \
misconfigurations that would report EVERY later frame as unreadable \
and collapse every duration onto the floor.  Fix the fault and \
recapture, or investigate with \
PLAYTHROUGH_CAPTURE_MODE=diagnostic."
    fi
    if [ "${OVERWRITE}" -ne 0 ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_OVERWRITE=1 cannot be \
used for a frame that is kept.  A frame already at this index means \
the counter repeated, and replacing it moves the original OUT of the \
working tree -- so a keystroke that was photographed and committed \
would silently lose its frame while the counts still matched.  Take \
the next index, or investigate with \
PLAYTHROUGH_CAPTURE_MODE=diagnostic."
    fi
    # THE DATE AUDIT IS MANDATORY for a frame that is kept.  WHERE it
    # goes is settled unconditionally further up -- see THE DATE AUDIT
    # GOES WHERE timeline.py LOOKS, IN EVERY MODE -- because that was the
    # gap: the destination check used to live here, so only a production
    # capture had to answer for the one path a capture nominates.  What
    # remains here is the other half of the same property: a frame that
    # joins the record must actually HAVE date evidence recorded for it,
    # or the rollover guard has nothing to reconcile a backwards clock
    # against and would have to infer a day it never observed.
    if [ "${AUDIT_MODE}" != "on" ]; then
        die "${EX_USAGE}" "PLAYTHROUGH_CAPTURE_AUDIT=off cannot be used \
for a frame that is kept.  The sidebar DATE line is what tells a clock \
that went backwards apart from a genuine crossing of midnight, and it \
is recorded nowhere else -- so a frame with no audit row leaves \
timeline.py to infer a day it never observed.  Look at a frame without \
recording one with PLAYTHROUGH_CAPTURE_MODE=diagnostic."
    fi
    # AND THE TRUST STATE, which is the fifth thing that decides whether
    # this frame is evidence.  env.sh's diagnostic escape hatches -- an
    # unverifiable tool, an unauthenticated display, a pack from an
    # untrustworthy path, artwork other than the required MSXotto+, an
    # older Pillow, an unsanctioned compiler -- were each enforced by a
    # warning saying not to record a session, which left the decision to
    # whoever read stderr.  A frame captured through a tool another
    # account can replace, off a display any account can inject
    # keystrokes into, is not evidence of anything, however sound every
    # other check was.  So the state refuses here, before the display is
    # touched and before any file exists, and diagnosis moves to the
    # mode whose frame is withdrawn out of the working tree.
    if ! playthrough_assert_trusted \
            "to capture a frame for the record"; then
        die "${EX_USAGE}" "the trust state is \
'${PLAYTHROUGH_TRUST_STATE}' (${PLAYTHROUGH_TRUST_BYPASSES}), so this \
capture would not be evidence.  Unset the override(s) listed above, or \
look at the frame with PLAYTHROUGH_CAPTURE_MODE=diagnostic, which \
withdraws it out of the working tree and exits ${EX_DIAGNOSTIC}."
    fi
fi

# ---------------------------------------------------------------------
# Preflight.
#
# The capturer is `import -window root`; scrot is the documented
# fallback and is used only when import is absent.  Both photograph the
# whole root window, which is the point.
# ---------------------------------------------------------------------
# EVERY external command is resolved through env.sh, which verifies it
# before handing back the path, and this script then invokes THAT path.
# Finding a command on PATH is not the same as trusting it: PATH is
# mutable, this runs unattended, and what these tools produce is the
# evidence the whole pipeline rests on -- so the binary and every
# directory above it are checked for third-party ownership and for
# group- or world-writability first.  A tool that fails the check is
# treated exactly like a missing one.
if playthrough_resolve_tool import; then
    CAPTURE_TOOL="import"
    CAPTURE_BIN="${PLAYTHROUGH_BIN_IMPORT}"
elif playthrough_resolve_tool scrot; then
    CAPTURE_TOOL="scrot"
    CAPTURE_BIN="${PLAYTHROUGH_BIN_SCROT}"
    playthrough_warn "ImageMagick's import is not installed; falling" \
        "back to scrot.  Both grab the X root window, so the frame is" \
        "equivalent, but import is the contracted capturer."
else
    die "${EX_PREREQ}" "no usable screen capturer: neither \
ImageMagick's import nor scrot is installed and verifiable.  See the \
apt list in playthrough/tooling/requirements.txt, and any rejection \
reported above."
fi

# Every non-builtin this file actually runs, asserted before anything
# is created.  The list is exhaustive on purpose: a command discovered
# missing halfway through has already written a log line, possibly a
# pidfile, and -- worst of all -- possibly a frame, and an absent tool
# that surfaces as some later symptom is a diagnosis nobody can make
# from the message they are shown.
#
#   convert, identify  identify proves the frame is a PNG at the
#                      contracted geometry and convert measures its
#                      luminance, the guard against a silently black
#                      session.  Both are unconditional.
#   xdpyinfo           playthrough_assert_display below asks it whether
#                      the root window is the contracted geometry.
#                      Requiring it HERE is what stops "x11-utils is
#                      not installed" from being reported as "there is
#                      no X server on :99" -- two different faults that
#                      wore the same message before.
#   date, awk, grep    the real_ts stamp, the luminance comparison and
#                      the pattern match respectively.
#   mkdir, mv, rm      the frames directory and the withdrawal path.
#   sha256sum          the capture digest, taken the instant the frame is
#                      published.  It is required rather than optional
#                      because an unattested frame is precisely the
#                      state the digest exists to close: every later
#                      stage would have to assume that the pixels on
#                      disk are the pixels this capture took.
playthrough_require_tools \
    convert identify xdpyinfo date awk grep mkdir mv rm sha256sum ||
    exit "${EX_PREREQ}"

# tesseract is needed by BOTH clock-read paths, so its absence is a
# prerequisite failure rather than an unreadable clock.
if [ "${CLOCK_MODE}" = "on" ]; then
    playthrough_require_tools tesseract || exit "${EX_PREREQ}"
fi

# Preflight the OCR delegate's own dependencies once, before the grab.
# ocr_clock.py's exit codes distinguish a frame that held no clock (1)
# from a fault (2), and a missing Python dependency must not be reported
# as the former: an unreadable clock is an honest reading, a broken
# dependency is a prerequisite failure that would silently collapse
# every duration to the 0.25 s floor for a whole session.  `--preflight`
# checks the imports and the pinned Pillow without reading anything.
if [ "${CLOCK_MODE}" = "on" ] && [ -f "${OCR_SCRIPT}" ] &&
   command -v "${PLAYTHROUGH_PYTHON}" >/dev/null 2>&1; then
    if ! "${PLAYTHROUGH_PYTHON}" "${OCR_SCRIPT}" --preflight; then
        if [ "${STRICT_CLOCK}" -eq 1 ]; then
            die "${EX_CLOCK_FAULT}" "ocr_clock.py cannot run: a \
dependency did not import, or the interpreter's Pillow is older than \
the pin (see the diagnosis above).  This is a FAULT, not an unreadable \
clock, and it would otherwise report EVERY frame of the session as \
unreadable while every count still tallied.  Install \
playthrough/tooling/requirements.lock into ${PLAYTHROUGH_PYTHON}, or \
set PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0 to capture with the weaker \
inline reader instead."
        fi
        playthrough_warn "ocr_clock.py's dependency contract is not" \
            "satisfied and PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0, so the" \
            "clock is read with the inline convert|tesseract|grep chain"
        OCR_PREFLIGHT_FAILED=1
    fi
fi
# The platform this is photographing on: ImageMagick and the Xorg stack
# both parse untrusted-shaped input, so an out-of-support host is
# refused by name here rather than discovered later.  IT IS A REFUSAL BY
# DEFAULT, for both "past its end-of-life date" and "not in the support
# table at all" -- it used to be a warning with the hard failure opt-in,
# which is a safeguard that is off.  A host that is the only one
# available is accepted through PLAYTHROUGH_ALLOW_EOL_PLATFORM=<reason>,
# whose reason is warned once and printed in the environment summary, so
# a session captured under it says so in its own contract.
playthrough_check_platform || exit "${EX_PREREQ}"

# The cheap, loud guard against the one completely silent failure mode
# of this pipeline: the dummy VIDEO backend renders zero pixels, so the
# game runs, the keystrokes land, this script writes a PNG, ffmpeg
# encodes, every count tallies -- and the movie shows nothing.  env.sh
# asserts this at source time as well; asserting it again here costs one
# string comparison and documents the dependency at the point of use.
playthrough_assert_video_driver || exit "${EX_LAYOUT}"

# THE DISPLAY MUST BE CLOSED BEFORE ANYTHING IS PHOTOGRAPHED.
#
# An X server with no access control hands every local account the same
# screen this script is about to photograph -- and the same keyboard the
# session is being driven with.  Either half destroys the value of the
# result: pixels another process could have painted are not evidence of
# what the survivor did, and keystrokes another process could have sent
# break the one-keystroke-per-frame invariant while every count still
# tallies.  env.sh starts Xvfb with -auth and a fresh cookie; this is the
# assertion that the server actually in front of us enforces it, made
# BEFORE the first grab rather than trusted.
playthrough_assert_x_access_control || exit "${EX_GEOMETRY}"

# The root window must be the contracted geometry BEFORE the grab, so a
# wrong-sized display is reported as such instead of surfacing later as
# a mysteriously wrong-resolution movie.
playthrough_assert_display || exit "${EX_GEOMETRY}"

# ---------------------------------------------------------------------
# Prepare the destination.  Only playthrough/frames/ is created: the
# build and transition directories belong to other stages, and
# env.sh's playthrough_mkdirs is deliberately NOT used here, because
# this file's blast radius is one directory.
# ---------------------------------------------------------------------
if ! mkdir -p "${PLAYTHROUGH_FRAMES_DIR}"; then
    die "${EX_CAPTURE}" "cannot create ${PLAYTHROUGH_FRAMES_DIR}"
fi

# AND NOBODY ELSE MAY WRITE INTO IT.  `mkdir -p` on a directory that
# already exists is a no-op, so a frames directory created earlier under a
# permissive umask keeps its mode forever -- which a security review
# measured on the delivered tree as 2777, world-writable, holding the
# whole capture set.  Whoever can write a directory can replace or delete
# any file in it, so that is substitutable evidence however careful this
# file is with the frames themselves.  Repaired and announced here, on
# every capture, because this is the one stage that runs three hundred
# times and is therefore the one that would notice.
playthrough_deny_foreign_write "${PLAYTHROUGH_FRAMES_DIR}" \
    "the frames directory" || exit "${EX_CAPTURE}"

# THE DESTINATION IS PROVED, NOT ASSUMED.
#
# Both checks matter for a different reason:
#
#   * containment plus no symlinked component means a planted link at
#     playthrough/ or playthrough/frames/ cannot send this capture --
#     a photograph of the whole screen -- somewhere outside the working
#     tree, where nothing downstream would look for it and nothing would
#     notice it had gone;
#   * the frame path itself must not already be a symlink, dangling or
#     otherwise, because `import` would follow it and write through.
#
# The frames directory is also where the count identity that
# verify_artifacts.sh asserts lives, so it has to be a real directory
# holding real files and nothing else.
playthrough_assert_inside "${PLAYTHROUGH_FRAMES_DIR}" \
    "${PLAYTHROUGH_REPO_ROOT}" "frames directory" ||
    exit "${EX_LAYOUT}"
playthrough_assert_no_symlink "${PLAYTHROUGH_FRAMES_DIR}" \
    "${PLAYTHROUGH_REPO_ROOT}" "frames directory" ||
    exit "${EX_LAYOUT}"
if [ -L "${FRAME_PATH}" ]; then
    die "${EX_LAYOUT}" "${FRAME_FILE} is a symbolic link.  A frame is \
a file this pipeline writes, never a link it follows: writing through \
it would put a full-screen capture wherever the link pointed."
fi

# RESERVE THE INDEX ATOMICALLY.
#
# The old form -- test whether the frame exists, then let the capturer
# create it -- is two operations, and two captures racing for the same
# index could both pass the test and both write.  `set -o noclobber`
# turns the creation into a single O_EXCL open, so exactly one caller can
# ever own an index and the loser is told so.  The reservation is a
# zero-byte placeholder; the real capture goes to a temporary file and
# replaces it with one atomic rename, so no partially written PNG is ever
# visible at a frame path.
#
# Refusing to clobber is a guard on the 1:1 invariant, not politeness: a
# frame already sitting at this index means the counter has repeated, and
# overwriting would leave the frames count one short of the keystroke
# count with nothing to show that it happened.
if ! ( set -o noclobber; : >"${FRAME_PATH}" ) 2>/dev/null; then
    # noclobber refuses for two reasons with opposite remedies, so they
    # are told apart before anything is reported.  A path that exists is
    # a taken index and the answer is the next one.  A path that does
    # not exist means the creation itself was refused -- an unwritable
    # frames directory, a full or read-only filesystem -- where the next
    # index would fail identically, so that is a capture failure
    # (EX_CAPTURE) rather than a collision.
    if [ ! -e "${FRAME_PATH}" ]; then
        die "${EX_CAPTURE}" "cannot create ${FRAME_PATH}, and nothing \
is there to be in the way -- so this is not a repeated index and the \
next index would fail identically.  The frames directory itself \
refused the write: it may be immutable (chattr +i), not writable by \
this user, or on a filesystem that is read-only or full.  Check \
${PLAYTHROUGH_FRAMES_DIR} and the filesystem holding it."
    fi
    if [ "${OVERWRITE}" -ne 1 ]; then
        die "${EX_EXISTS}" "${FRAME_PATH} already exists, or another \
capture holds this index.  A repeated index means the frame counter \
went backwards, which would break the one-frame-per-keystroke \
identity.  Take the next index.  Recapturing one deliberately is a \
DIAGNOSTIC action (PLAYTHROUGH_CAPTURE_MODE=diagnostic with \
PLAYTHROUGH_CAPTURE_OVERWRITE=1): the existing frame is moved aside, \
the new capture is withdrawn, and the original is put back."
    fi
    _cap_backup="${REJECT_DIR}/superseded-${FRAME_NAME}"
    if playthrough_secure_dir "${REJECT_DIR}" 700 2>/dev/null &&
       mv -f "${FRAME_PATH}" "${_cap_backup}" 2>/dev/null; then
        BACKUP="${_cap_backup}"
        playthrough_warn "recapturing ${FRAME_FILE}; the earlier frame" \
            "was moved to ${BACKUP} and is restored if this capture" \
            "does not succeed"
    else
        die "${EX_CAPTURE}" "cannot move the existing ${FRAME_PATH} \
aside into ${REJECT_DIR}; refusing to overwrite it in place"
    fi
    unset _cap_backup
    # Re-reserve the index now that the earlier frame is out of the way,
    # so the exclusive-ownership property holds on the recapture path too.
    if ! ( set -o noclobber; : >"${FRAME_PATH}" ) 2>/dev/null; then
        die "${EX_EXISTS}" "${FRAME_PATH} reappeared while it was \
being moved aside; another capture is using this index"
    fi
fi
# From here on the placeholder is ours, so it is withdrawn on failure
# exactly like a captured frame would be.
GRABBED=1

# ---------------------------------------------------------------------
# THE SETTLE.  0.3 seconds, from env.sh.
#
# DO NOT REMOVE THIS AND DO NOT SHORTEN IT AS DEAD TIME.  The game
# redraws asynchronously after a keystroke; grabbing too early
# photographs the screen as it was BEFORE the key landed.  The frame
# would still be a real screenshot and every count would still tally,
# so nothing would fail -- every clock reading would simply be one
# keystroke stale, and the whole film would be mis-timed by one step.
# ---------------------------------------------------------------------
sleep "${SETTLE}"

# The wall-clock instant of the grab, in the manifest's own real_ts
# form: UTC, millisecond precision, "Z"-suffixed.  manifest.py's
# canonical_real_ts() documents accepting exactly this `date` output, so
# session.py can pass it straight through and the row records when the
# shutter actually opened rather than when the row was written.
REAL_TS="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)"
if ! [[ "${REAL_TS}" =~ ${REAL_TS_RE} ]]; then
    # %3N is a GNU date extension.  Where it is unavailable it is left
    # in the output verbatim, which would be a fabricated timestamp, so
    # the second-resolution form is used and the millisecond field is
    # honestly zero.
    REAL_TS="$(date -u +%Y-%m-%dT%H:%M:%S).000Z"
    playthrough_warn "this date(1) has no %3N, so real_ts carries" \
        "second resolution with a zero millisecond field"
fi

# ---------------------------------------------------------------------
# THE GRAB.  The X ROOT window, exactly once, into a temporary file.
#
# The capture does NOT go straight to the frame path.  It goes to an
# exclusive temporary file in the same directory and is renamed over the
# reservation once it has passed every check, so:
#
#   * nothing downstream can ever observe a half-written PNG at a frame
#     path -- rename within a directory is atomic;
#   * a capturer that exits non-zero having already created its output
#     leaves the rubbish in the temporary file, not in the frames
#     directory;
#   * the index stays reserved throughout, so a concurrent capture of
#     the same index still cannot slip in behind this one.
#
# GRABBED is already 1 from the reservation above, so the EXIT trap knows
# about both the placeholder and the temporary file.
# ---------------------------------------------------------------------
if ! CAPTURE_TMP="$(mktemp --suffix=.png \
        "${PLAYTHROUGH_FRAMES_DIR}/.${FRAME_NAME}.XXXXXX" 2>/dev/null)"; then
    die "${EX_CAPTURE}" "cannot create a temporary file for \
${FRAME_FILE} in ${PLAYTHROUGH_FRAMES_DIR}"
fi
case "${CAPTURE_TOOL}" in
    import)
        # The contracted form.  `-window root` is the whole point: the
        # root is exactly 1920x1080 while the terminal render grid
        # inside it is 1920x1072 at +0+4, so this needs no rescaling and
        # nothing softens the 8x16 glyphs the clock read depends on.
        # The binary is the one env.sh verified, invoked by the path it
        # resolved rather than re-searched on PATH here, and the grab is
        # BOUNDED: an X server that has stopped answering hangs it
        # rather than failing it.
        _cap_rc=0
        timeout "${GRAB_TIMEOUT}" \
            "${CAPTURE_BIN}" -window root "png:${CAPTURE_TMP}" ||
            _cap_rc=$?
        if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
            die "${EX_CAPTURE}" "import -window root did not finish \
within ${GRAB_TIMEOUT}s for ${FRAME_FILE} on DISPLAY=${DISPLAY} and \
was stopped; an X server that has stopped answering hangs the grab \
rather than failing it"
        elif [ "${_cap_rc}" -ne 0 ]; then
            die "${EX_CAPTURE}" "import -window root failed (exit \
${_cap_rc}) for ${FRAME_FILE} on DISPLAY=${DISPLAY}"
        fi
        ;;
    scrot)
        # scrot grabs the whole screen -- the root window -- when it is
        # given neither -u nor -s, so the frame is equivalent.  -o
        # permits the existing (empty) temporary file as the target, and
        # the grab is bounded for the same reason as import's.
        _cap_rc=0
        timeout "${GRAB_TIMEOUT}" \
            "${CAPTURE_BIN}" -o "${CAPTURE_TMP}" || _cap_rc=$?
        if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
            die "${EX_CAPTURE}" "scrot did not finish within \
${GRAB_TIMEOUT}s for ${FRAME_FILE} on DISPLAY=${DISPLAY} and was \
stopped"
        elif [ "${_cap_rc}" -ne 0 ]; then
            die "${EX_CAPTURE}" "scrot failed (exit ${_cap_rc}) for \
${FRAME_FILE} on DISPLAY=${DISPLAY}"
        fi
        ;;
    *)
        # Unreachable today -- the preflight sets CAPTURE_TOOL to
        # exactly one of the two names above -- and present anyway,
        # because a case that falls through silently would raise
        # GRABBED, capture nothing, and then be reported by the next
        # block as "wrote no file", which names the symptom instead of
        # the cause.  Failing here names the cause.
        die "${EX_PREREQ}" "no capturer is implemented for \
CAPTURE_TOOL='${CAPTURE_TOOL}'; the supported values are import and \
scrot"
        ;;
esac

# ---------------------------------------------------------------------
# Prove the file on disk really is one frame of the contracted shape.
# A capturer that exits 0 having written nothing, or a truncated write,
# must not be reported as a successful capture.
# ---------------------------------------------------------------------
if [ ! -f "${CAPTURE_TMP}" ]; then
    die "${EX_CAPTURE}" "${CAPTURE_TOOL} reported success but wrote no \
file for ${FRAME_FILE}"
fi

FRAME_BYTES="$(wc -c <"${CAPTURE_TMP}")"
if [ "${FRAME_BYTES}" -le 0 ]; then
    die "${EX_CAPTURE}" "the capture of ${FRAME_FILE} is empty; \
${CAPTURE_TOOL} wrote a zero-byte file"
fi

# identify reports the format and the size in one call.  Multi-frame
# output is impossible for a screen grab, but the first line is taken
# explicitly rather than assumed, and without a pipe, so that pipefail
# cannot turn a SIGPIPE into a spurious capture failure.
_cap_rc=0
_cap_identify="$(
    timeout "${IDENTIFY_TIMEOUT}" \
        "${PLAYTHROUGH_BIN_IDENTIFY}" -format '%m %wx%h\n' \
            "${CAPTURE_TMP}" 2>&1
 )" || _cap_rc=$?
if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
    die "${EX_CAPTURE}" "identify did not finish within \
${IDENTIFY_TIMEOUT}s on the capture of ${FRAME_FILE} and was stopped"
elif [ "${_cap_rc}" -ne 0 ]; then
    die "${EX_CAPTURE}" "identify could not read the capture of \
${FRAME_FILE} as an image (exit ${_cap_rc}): ${_cap_identify}"
fi
_cap_identify="${_cap_identify%%$'\n'*}"
FRAME_FORMAT="${_cap_identify%% *}"
FRAME_GEOMETRY="${_cap_identify##* }"
unset _cap_identify

if [ "${FRAME_FORMAT}" != "PNG" ]; then
    die "${EX_CAPTURE}" "the capture of ${FRAME_FILE} is a \
${FRAME_FORMAT}, not a PNG; the pipeline reads and encodes PNG frames \
only"
fi

_cap_want_geometry="\
${PLAYTHROUGH_SCREEN_WIDTH}x${PLAYTHROUGH_SCREEN_HEIGHT}"
if [ "${FRAME_GEOMETRY}" != "${_cap_want_geometry}" ]; then
    die "${EX_GEOMETRY}" "${FRAME_FILE} is ${FRAME_GEOMETRY}, not the \
contracted ${_cap_want_geometry}.  Capture targets the X root \
deliberately so that no rescaling is needed; a different size means \
either the display is wrong or something other than the root was \
photographed."
fi
unset _cap_want_geometry

# ---------------------------------------------------------------------
# THE NON-BLANK GATE.
#
# This is the guard against the pipeline's one silent catastrophe.  With
# the dummy video backend the game runs, the keystrokes land, this file
# writes a PNG of exactly the right size, ffmpeg encodes it and every
# acceptance count matches -- and the movie is black from end to end.
#
# Calibration, measured with this exact command:
#     real rendered frame     mean=0.270018   std=0.198145
#     dummy video backend     mean=0          std=0
#     uniform solid colour    mean>0          std=0
# The mean term catches a black frame; the standard-deviation term also
# catches a flat solid one, which a mean test alone would pass.  This
# fires at frame one instead of after the whole session, and it fails
# LOUDLY rather than warning.
# ---------------------------------------------------------------------
_cap_rc=0
_cap_luma="$(
    timeout "${LUMA_TIMEOUT}" \
        "${PLAYTHROUGH_BIN_CONVERT}" "${CAPTURE_TMP}" -colorspace Gray \
            -format '%[fx:mean] %[fx:standard_deviation]' info: 2>&1
 )" || _cap_rc=$?
if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
    die "${EX_CAPTURE}" "the luminance measurement did not finish \
within ${LUMA_TIMEOUT}s on ${FRAME_PATH} and was stopped; the non-blank \
gate cannot be skipped, so the frame is withdrawn rather than kept \
unchecked"
elif [ "${_cap_rc}" -ne 0 ]; then
    die "${EX_CAPTURE}" "convert could not measure the luminance of \
${FRAME_PATH} (exit ${_cap_rc}): ${_cap_luma}"
fi
_cap_luma="${_cap_luma%%$'\n'*}"
LUMA_MEAN="${_cap_luma%% *}"
LUMA_STDDEV="${_cap_luma##* }"
unset _cap_luma

# Both values must be numbers before they are compared.  awk compares a
# non-numeric string against 0 as STRINGS, so an unparsed value such as
# "nan" would satisfy `> 0` and a blank frame would pass the gate.
if ! [[ "${LUMA_MEAN}" =~ ${NUMBER_RE} ]] ||
   ! [[ "${LUMA_STDDEV}" =~ ${NUMBER_RE} ]]; then
    die "${EX_CAPTURE}" "the luminance of ${FRAME_FILE} did not \
measure as numbers (mean='${LUMA_MEAN}' stddev='${LUMA_STDDEV}'), so \
the non-blank gate cannot be evaluated and the frame is not accepted"
fi

if ! awk -v m="${LUMA_MEAN}" -v s="${LUMA_STDDEV}" \
        'BEGIN { exit (m > 0 && s > 0) ? 0 : 1 }'; then
    die "${EX_BLANK}" "${FRAME_FILE} is blank: grayscale \
mean=${LUMA_MEAN} stddev=${LUMA_STDDEV}, and a real rendered frame \
measures mean=0.270018 stddev=0.198145.  mean=0 with stddev=0 is the \
signature of the dummy video backend rendering zero pixels; stddev=0 \
alone is a uniform solid screen.  Nothing further is captured until \
the display genuinely renders."
fi

# ---------------------------------------------------------------------
# PUBLISH.  One atomic rename over the reservation.
#
# Everything above ran against the temporary file, so this is the first
# moment a frame exists at its canonical path -- and it exists complete,
# verified as a 1920x1080 PNG and proved non-blank, or not at all.  A
# rename within one directory cannot be observed half-done, so no reader
# downstream (the OCR read below included) can ever see a partial frame.
# ---------------------------------------------------------------------
if ! mv -f -- "${CAPTURE_TMP}" "${FRAME_PATH}"; then
    die "${EX_CAPTURE}" "cannot publish the verified capture to \
${FRAME_FILE}"
fi
CAPTURE_TMP=""
if ! chmod 600 -- "${FRAME_PATH}"; then
    die "${EX_CAPTURE}" "cannot set the mode of ${FRAME_FILE}"
fi

# ---------------------------------------------------------------------
# THE CAPTURE DIGEST, taken here and nowhere else.
#
# WHAT WAS MISSING AND WHY IT MATTERED.  This invocation reported the
# path, the byte count, the geometry, the luminance and the clock -- and
# no digest of the bytes it had just published.  A security review named
# the consequence: every later stage, the timeline that paces the film
# and the movie that shows it, assumed that the pixels sitting at
# frame_NNNNN.png were the pixels this capture took, and nothing in the
# record could establish it.  A same-sized, non-blank replacement passed
# the whole chain, and the recovery path went further still -- it
# re-measured an on-disk frame and took its MODIFICATION TIME for the
# capture instant.
#
# So the digest is taken IMMEDIATELY after the atomic rename, before the
# OCR read and before anything else touches the file, and it travels on
# the payload as FRAME_SHA256.  session.py copies it into the telemetry
# sidecar row and into the append-only digest ledger, and every stage
# that consumes a frame -- timing, transitions, render, commit, recovery
# -- verifies the bytes against it first.
#
# A DIGEST THAT CANNOT BE TAKEN IS A FAILED CAPTURE, not a blank column.
# An unattested frame is exactly the state this closes, so the frame is
# withdrawn rather than published without one.
# ---------------------------------------------------------------------
FRAME_SHA256=""
_cap_rc=0
_cap_digest="$(
    timeout "${IDENTIFY_TIMEOUT}" \
        "${PLAYTHROUGH_BIN_SHA256SUM}" -- "${FRAME_PATH}" 2>&1
)" || _cap_rc=$?
if [ "${_cap_rc}" -ne 0 ]; then
    die "${EX_CAPTURE}" "cannot hash ${FRAME_FILE} (exit ${_cap_rc}): \
$(printf '%s' "${_cap_digest}" | head -c 200 | tr '\n' '|').  A frame \
whose bytes are not attested at the moment they are published is not \
evidence of anything later, so it is withdrawn rather than recorded."
fi
FRAME_SHA256="${_cap_digest%% *}"
if ! [[ "${FRAME_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
    die "${EX_CAPTURE}" "the digest of ${FRAME_FILE} came back as \
'${FRAME_SHA256}', which is not 64 lowercase hex digits"
fi

# BINDING THE DATE ROW TO THE PIXELS.
#
# The audit row records what the sidebar's DATE line said, and that is
# the evidence timeline.py reconciles a backwards clock against -- so a
# row attributed to the wrong pixels can move a whole day of game time.
# Until the digest existed nothing connected the two: a row keyed on
# frame 42 was a claim about "whatever frame 42 is", and a withdrawn
# capture or a re-photographed index left a reading of one screen
# describing another.  The digest taken two lines above is passed to the
# delegate so the row it writes names the frame it actually read.
if [ "${AUDIT_MODE}" = "on" ]; then
    AUDIT_ARGS+=(--audit-sha256 "${FRAME_SHA256}")
fi

# ---------------------------------------------------------------------
# THE CROP RECTANGLE.  Computed, never hard-coded.
#
# sidebar_geometry.py derives it as
#     width  = sidebar_width_cells * FONT_WIDTH  * SCALING_FACTOR
#     height = TERMINAL_Y          * FONT_HEIGHT * SCALING_FACTOR
#     x      = window.x + window.width - width   (SIDEBAR_POSITION right)
# from the game's own widget JSON and the game-written options.json,
# and prints nothing but the geometry on stdout.  Which widget it reads
# is decided by the ACTIVE layout, taken from the game-written
# <userdir>/config/panel_options.json and falling back to the engine's
# own constructor default [src/panels.cpp:412-418, :492-503], so the
# rectangle differs between userdirs: it evaluates to 352x1072+1568+4
# on a fresh userdir, whose default layout is legacy_labels_sidebar at
# 44 cells, and to 288x1072+1632+4 on a userdir whose panel options
# select the 36-cell custom_sidebar.  The first is the one this
# pipeline starts from; NEITHER is assumed, and both appear here as
# expected results and on no code path.
#
# Computing it matters because the sidebar is one of many presets.
# Counted in this checkout: nine files match data/json/ui/sidebar*.json
# at the top level and twelve match across the whole tree -- the
# spacebar/, structured/ and zenfs/ bundles add three -- and those
# twelve files declare twelve widgets with "style": "sidebar" at EIGHT
# distinct widths: 32, 36, 43, 44, 48, 58, 62 and 66 cells.  (The
# recursive count is the one the width census is taken over; nine is
# only the top-level file count.)  A hard-coded rectangle would crop the
# wrong column the moment the layout changed, and it would do so
# silently -- nothing crashes, the pattern simply stops matching, every
# reading goes empty, every duration collapses to the floor, and the
# finished movie looks plausible while meaning nothing.
#
# It also returns the WHOLE sidebar column, never a fixed band: the
# clock is drawn by the time_desc_label widget bound to time_text
# [data/json/ui/time.json:2-8] at whatever row the ACTIVE layout's
# widgets array puts it, so its y cannot be known from configuration.
# The clock is located BY PATTERN inside the OCR text.
# ---------------------------------------------------------------------
#
# AND A COMPUTATION THAT FAILS IS FATAL -- IT DOES NOT FALL BACK.
#
# Substituting either documented example when the computation cannot be
# run is the one response that cannot be right here, because each is
# correct for ONE layout only and nothing has checked which layout this
# run is drawing -- the check is precisely what just failed.
# The wrong column then reads as an unreadable clock rather than as an
# error, so every duration collapses to the 0.25 s floor and the
# finished movie is plausible and meaningless: the exact silent
# catastrophe the computation exists to prevent, reintroduced by the
# fallback meant to be safe.  So a failure to compute stops the capture
# with EX_GEOMETRY, and the frame is withdrawn by the EXIT trap.
#
# An operator who genuinely wants a fixed rectangle -- diagnosing a
# frame from another configuration, say -- asks for one explicitly with
# PLAYTHROUGH_CAPTURE_RECT, which is recorded as CLOCK_RECT_FROM=
# override so the choice is visible in the session record rather than
# inferred from a warning nobody read.
# ---------------------------------------------------------------------
CLOCK_RECT=""
CLOCK_RECT_FROM=""
if [ "${CLOCK_MODE}" = "off" ]; then
    # No crop is resolved because none will be applied: with the clock
    # read off, nothing crops this frame at all.  Reporting a rectangle
    # here would claim a crop that was never used, and REQUIRING one
    # would fail a capture over a reading it was told not to take.
    CLOCK_RECT_FROM="skipped"
    playthrough_log "the clock read is off, so no sidebar crop is" \
        "resolved for ${FRAME_FILE} and none is reported"
elif [ -n "${RECT_OVERRIDE}" ]; then
    CLOCK_RECT="${RECT_OVERRIDE}"
    CLOCK_RECT_FROM="override"
    playthrough_warn "using the EXPLICIT crop override" \
        "PLAYTHROUGH_CAPTURE_RECT=${CLOCK_RECT} instead of computing" \
        "it from this run's configuration; the reading is only as" \
        "right as that rectangle"
else
    if [ ! -f "${GEOMETRY_SCRIPT}" ]; then
        die "${EX_GEOMETRY}" "missing ${GEOMETRY_SCRIPT}, which is \
where the sidebar crop is computed.  A fixed rectangle is NOT \
substituted for it, because the right one depends on the sidebar \
layout in force: \
${DEFAULT_LAYOUT_RECT} for the engine default \
${DEFAULT_LAYOUT_NAME}, ${EXAMPLE_RECT} for ${EXAMPLE_RECT_LAYOUT}, \
and a different width again for each of the other presets that ship in \
data/json/ui.  Cropping the wrong column reads as an unreadable clock \
rather than as an error, so every duration would fall to the floor \
while every count still tallied.  Restore the script, or set \
PLAYTHROUGH_CAPTURE_RECT explicitly to accept a fixed rectangle \
(the form is ${EXAMPLE_RECT})."
    fi
    _cap_rc=0
    # stdout carries the geometry and NOTHING else, which is why stderr
    # goes to the scratch file rather than into this capture: every
    # value sidebar_geometry.py had to default is announced on stderr,
    # and on a fresh userdir there are several.  They are relayed below.
    _cap_rect="$(
        timeout "${GEOMETRY_TIMEOUT}" \
            "${PLAYTHROUGH_PYTHON}" -B "${GEOMETRY_SCRIPT}" \
            2>"${STAGE_ERR}"
     )" || _cap_rc=$?
    _cap_detail="$(stage_stderr)"
    if [ "${_cap_rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
        die "${EX_GEOMETRY}" "sidebar_geometry.py did not finish \
within ${GEOMETRY_TIMEOUT}s and was stopped, so the sidebar crop for \
${FRAME_FILE} is unknown.  stderr: ${_cap_detail:-<none>}"
    elif [ "${_cap_rc}" -ne 0 ]; then
        die "${EX_GEOMETRY}" "sidebar_geometry.py could not compute \
the sidebar crop for ${FRAME_FILE} (exit ${_cap_rc}): \
${_cap_detail:-<no diagnostic>}.  A fixed rectangle is NOT substituted \
for it -- each sidebar preset needs its own (${DEFAULT_LAYOUT_RECT} for \
the engine default ${DEFAULT_LAYOUT_NAME}, ${EXAMPLE_RECT} for \
${EXAMPLE_RECT_LAYOUT}), and this run's configuration is exactly what \
could not be read.  Fix the configuration, or set \
PLAYTHROUGH_CAPTURE_RECT explicitly to accept a fixed rectangle (the \
form is ${EXAMPLE_RECT})."
    fi
    # Relayed even on success: a crop computed from defaulted values is
    # still a crop derived from a configuration nobody confirmed, and
    # that is worth seeing in the session log.
    if [ -n "${_cap_detail}" ]; then
        playthrough_warn "sidebar_geometry.py reported:" \
            "${_cap_detail}"
    fi
    CLOCK_RECT="${_cap_rect%%$'\n'*}"
    CLOCK_RECT_FROM="computed"
    unset _cap_rect _cap_detail
fi

if [ "${CLOCK_RECT_FROM}" != "skipped" ] &&
   ! [[ "${CLOCK_RECT}" =~ ${GEOMETRY_RE} ]]; then
    die "${EX_CLOCK_FAULT}" "the sidebar crop resolved to \
'${CLOCK_RECT}', which is not an ImageMagick WxH+X+Y geometry"
fi

# ---------------------------------------------------------------------
# THE CLOCK READ.  An assist that is allowed to fail, and never allowed
# to invent.
#
# The reading of the frame is authoritative; OCR is the assist.  A
# genuine HH:MM:SS is emitted verbatim.  Anything else emits NOTHING --
# never 00:00:00, never the previous frame's value, never an
# interpolation, never a repair of a partial match.  Reconciling a
# missing or non-monotonic reading is timeline.py's job, downstream and
# visibly, against the previous frame; this file is stateless and holds
# no reading from one invocation to the next, so it cannot silently
# continue a sequence even if it wanted to.
#
# What the engine can legitimately put there [src/display.cpp:207-218]:
# an exact time only when the survivor has a watch; otherwise a coarse
# phrase from display::time_approx() -- "Around dawn", "Dead of night"
# and the rest -- or "???".  Those are REAL READINGS, not failures, and
# they surface verbatim in TIME_PHRASE rather than being discarded.
# ---------------------------------------------------------------------
CLOCK=""
CLOCK_STATUS=""
CLOCK_SOURCE="none"
TIME_PHRASE=""
CLOCK_DATE=""
OCR_RC=0
OCR_OUT=""
# READER_RC is THE status of the reader that actually ran.  Two readers
# report into two variables -- OCR_RC for the delegate, INLINE_RC for
# the inline chain -- and a diagnostic that quotes the wrong one prints
# a reassuring 0 for a frame that faulted, which is worse than printing
# nothing.  Whichever branch runs sets this one, and the diagnostics
# read only this one.
READER_RC=0
INLINE_RC=0
# Whether this frame's date evidence actually reached the sidecar:
# "yes", "no", or "off" when auditing was not asked for.  Reported on
# stdout so the session record says which frames timeline.py will have
# date evidence for, rather than leaving it to be inferred from a
# warning.  "no" is not a failure -- an inline read cannot produce a
# record -- but it IS something timeline.py must treat as unknown.
AUDIT_RECORDED="no"
if [ "${AUDIT_MODE}" != "on" ]; then
    AUDIT_RECORDED="off"
fi

# The sidebar DATE line, and why this file reports it at all.
#
# display::date_string (src/display.cpp:194-205) renders either
# "<Weekday>, <Month> <day>" or "<Season>, day <N>" one row from the
# clock.  timeline.py needs it because a clock alone cannot tell a
# crossing of midnight from a misread going backwards: 08:00:00
# followed by 07:59:00 is indistinguishable from a real wrap unless
# something says whether the DAY changed.  It also cannot tell a
# 24-hour action from a zero-second one, because the time of day comes
# back the same.
#
# The manifest schema is exactly six fields and does not change, so the
# date leaves this file on stdout -- for session.py to persist to the
# telemetry sidecar -- and reaches ocr_clock.py's own date audit
# through the delegate call below instead.  It is reported
# VERBATIM or not at all -- never converted into a time, never inferred
# from the clock.  DATE_TEXT and DATE_STATUS below are derived from the
# single OCR pass ocr_readings performs; nothing re-reads the frame.
DATE_TEXT=""
DATE_STATUS="skipped"

# ocr_readings -- one delegate call for ALL THREE readings, and the date
# evidence persisted in the same breath.
#
# Delegation is preferred over a second implementation precisely so the
# two cannot disagree about the crop or the pattern: the rectangle
# computed above is passed in, and ocr_clock.py's own CLOCK_RE is
# character-for-character CLOCK_PATTERN here.  --strict-path is what an
# automated caller is documented to pass, so a frame from outside the
# capture directory is refused rather than warned about.
#
# Results come back in globals because a `$( ... )` capture of a
# function runs in a subshell, where the exit status of the delegate --
# 0 read, 1 unreadable, 2 fault -- is exactly what must not be lost.
#
# --kv returns CLOCK=, TIME_PHRASE= and CLOCK_DATE= from a SINGLE OCR
# pass, which matters for more than speed: three separate passes could
# disagree about the same pixels, and then nothing could say which
# reading the frame actually showed.
#
# --audit is what closes the date-evidence gap.  timeline.py has to tell
# a midnight rollover from a misread clock, and from the clock alone it
# cannot: 08:00:00 followed by 06:00:00 is either a 22-hour day or a bad
# digit, and assuming rollover invents 22 hours nobody played.  The
# sidebar draws the date on its own line [src/display.cpp:193-205], so
# THAT is the evidence, and ocr_clock.py appends one record per frame to
# $PLAYTHROUGH_DATE_AUDIT for timeline.py to read back.
#
# ocr_clock.py owns that write deliberately: THIS FILE MODIFIES NOTHING
# OUTSIDE playthrough/frames/, so it asks for the record rather than
# writing one, and the sidecar lives beside the build products instead
# of in the manifest -- whose schema is exactly six fields, and a
# seventh would create the second source of truth for timing that the
# whole pipeline is built to avoid.
#
# The values are parsed with `IFS='=' read`, never eval: they are OCR
# text off a game screen, and text is not code.  A trailing empty value
# is the honest form of "not read".
# ocr_readings -- read the sidebar of the frame just captured.
#
# --cross-check IS NOT OPTIONAL HERE.  Without it the readers stop at
# the first one that produces a possible time, so a misread by the pass
# that happens to run first is never contradicted and becomes the
# permanent record of that frame.  With it every reader runs, and a
# disagreement that no exact glyph match can settle makes ocr_clock.py
# report the clock as UNREADABLE -- the safe direction, because an
# absent reading is reconciled against the previous frame by timeline.py
# and shows in the manifest as null, whereas a wrong one is undetectable
# and silently becomes a wrong duration, a wrong caption and a wrong
# line in the transcript.
#
# It costs OCR calls on frames that would otherwise have stopped early:
# measured on this host, about 22 s per frame against 0.4 s when the
# glyph pass answered alone.  That is the intended trade.  This runs
# once per keystroke, the evidence it writes is committed and cannot be
# re-derived later, and the read has 300 s before it times out.
ocr_readings() {
    local line key value
    OCR_OUT=""
    OCR_RC=0
    CLOCK=""
    TIME_PHRASE=""
    CLOCK_DATE=""
    if OCR_OUT="$(
            timeout "${OCR_TIMEOUT}" \
                "${PLAYTHROUGH_PYTHON}" -B "${OCR_SCRIPT}" \
                --kv \
                --strict-path \
                --cross-check \
                --frames-dir "${PLAYTHROUGH_FRAMES_DIR}" \
                --rect "${CLOCK_RECT}" \
                "${AUDIT_ARGS[@]}" \
                "${FRAME_PATH}"
         )"; then
        OCR_RC=0
    else
        OCR_RC=$?
    fi
    # Parsed even on a non-zero exit: 1 means "read, nothing there",
    # and the empty values it prints are the honest answer.  Only a
    # fault (2 and above) prints nothing to parse.
    while IFS= read -r line; do
        [ -n "${line}" ] || continue
        key="${line%%=*}"
        value="${line#*=}"
        case "${key}" in
            CLOCK) CLOCK="${value}" ;;
            TIME_PHRASE) TIME_PHRASE="${value}" ;;
            CLOCK_DATE) CLOCK_DATE="${value}" ;;
            *)
                playthrough_warn "ignoring unrecognised reading" \
                    "'${key}' from ${OCR_SCRIPT} for ${FRAME_FILE}"
                ;;
        esac
    done <<<"${OCR_OUT}"
    return 0
}

# possible_clock HH:MM:SS -- true when the engine could have rendered it.
#
# 48:48:48 and 88:48:48 both match the pattern and have both been
# measured coming out of whole-column OCR of this very sidebar.  They
# are impossible: the engine cannot render hour 48.  Such a reading is
# DECLINED -- no digit is substituted, nothing is reconstructed -- so
# that a misread becomes an honest absence instead of a plausible lie.
# 10# forces base ten, because 08 would otherwise be read as octal.
#
# This is a PREDICATE: its non-zero return is data, not an error, so it
# is meant to be called in a condition where errexit steps aside.  It
# runs no external command and therefore has no failure of its own that
# such a call could mask.
possible_clock() {
    local candidate="$1" hour minute second rest
    hour="${candidate%%:*}"
    rest="${candidate#*:}"
    minute="${rest%%:*}"
    second="${rest##*:}"
    [ "$((10#${hour}))" -le "${MAX_HOUR}" ] &&
    [ "$((10#${minute}))" -le "${MAX_MINUTE}" ] &&
    [ "$((10#${second}))" -le "${MAX_SECOND}" ]
}

# inline_clock -- the specified chain, run directly.
#
# This is the capture helper's own pipeline, preserved verbatim apart
# from the mandated preprocessing, and it is the LAST RESORT: it runs
# only when ocr_clock.py or the interpreter is unavailable, and it says
# so on stderr when it does.  It reads the column in one pass, which is
# measurably weaker than ocr_clock.py's row-wise pass -- hence the
# possibility gate above, which is what keeps a weaker reader honest
# instead of merely quieter.
#
# Returns 0 with INLINE_OUT set, 1 for an unreadable clock, 2 for a
# fault in the image or OCR stage.  Those three codes are data, so the
# call site captures them deliberately rather than letting errexit act
# on them; every command inside that could genuinely fail is checked
# here, so nothing is masked by being called in a condition.
INLINE_OUT=""
inline_clock() {
    local text="" matches="" candidate="" rc=0 detail=""
    INLINE_OUT=""
    # Both stages' stderr is kept, not discarded.  "the chain failed" on
    # its own names no cause: the diagnosis is in what convert or
    # tesseract said -- an unreadable PNG, a crop outside the image, a
    # missing tessdata -- and without it the operator is left guessing
    # at a failure that will repeat on every frame.  It goes to a
    # private scratch file rather than into the pipe, because merging it
    # into stdout would corrupt the very text being read for a clock.
    #
    # The excerpt is BOUNDED: tesseract can be voluble, and a page of
    # warnings per frame would bury the session log it is meant to
    # inform.  Both binaries are the ones env.sh verified and resolved.
    : >"${STAGE_ERR}"
    # `cmd || rc=$?`, NOT `if ! cmd; then rc=$?`: inside the body of an
    # `if !` the special parameter holds the status of the NEGATION,
    # which is always 0.  Written that way the reported code would be a
    # constant zero and the expiry check below could never match, so the
    # status is taken from the command itself.
    text="$(
        timeout "${OCR_TIMEOUT}" \
            "${PLAYTHROUGH_BIN_CONVERT}" "${FRAME_PATH}" \
                -crop "${CLOCK_RECT}" +repage \
                -colorspace Gray -resize 200% -normalize png:- \
                2>"${STAGE_ERR}" |
            timeout "${OCR_TIMEOUT}" \
                "${PLAYTHROUGH_BIN_TESSERACT}" stdin stdout \
                    2>>"${STAGE_ERR}"
     )" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        detail="$(stage_stderr)"
        if [ "${rc}" -eq "${TIMEOUT_EXPIRED}" ]; then
            playthrough_warn "the inline convert|tesseract chain did" \
                "not finish within ${OCR_TIMEOUT}s on ${FRAME_FILE}" \
                "and was stopped; reporting no reading rather than" \
                "guessing.  stderr: ${detail:-<none>}"
        else
            playthrough_warn "the inline convert|tesseract chain" \
                "failed (exit ${rc}) reading the clock from" \
                "${FRAME_FILE} at crop ${CLOCK_RECT}; reporting no" \
                "reading rather than guessing.  stderr:" \
                "${detail:-<none>}"
        fi
        return 2
    fi
    # `|| true` is required, not lazy: no match is an EXPECTED outcome
    # -- most menu keystrokes photograph a screen with no clock on it --
    # and errexit would otherwise turn an honest absence into a script
    # failure.
    matches="$(printf '%s\n' "${text}" |
        grep -Eo "${CLOCK_PATTERN}" || true)"
    if [ -z "${matches}" ]; then
        return 1
    fi
    # First possible match in reading order wins, which is the same rule
    # ocr_clock.py fixes, so the same PNG always reads the same way.
    while IFS= read -r candidate; do
        [ -n "${candidate}" ] || continue
        if possible_clock "${candidate}"; then
            INLINE_OUT="${candidate}"
            return 0
        fi
        playthrough_warn "declining '${candidate}' from" \
            "${FRAME_FILE}: the engine cannot render it, so it is a" \
            "misread and is not repaired"
    done <<<"${matches}"
    return 1
}

if [ "${CLOCK_MODE}" = "off" ]; then
    CLOCK_STATUS="skipped"
elif [ "${OCR_PREFLIGHT_FAILED}" -eq 0 ] && [ -f "${OCR_SCRIPT}" ] &&
     [ -x "${PLAYTHROUGH_PYTHON}" ]; then
    # env.sh has already VERIFIED this interpreter -- ownership and
    # writability of the binary and of every directory above it -- and
    # refused to finish sourcing if it did not pass.  So the test here is
    # only whether it is present and executable; `command -v` is
    # deliberately not used, because it would search PATH again and could
    # answer with something other than the interpreter that was checked.
    CLOCK_SOURCE="ocr_clock.py"
    ocr_readings
    READER_RC="${OCR_RC}"
    # ocr_clock.py writes the audit record before it prints anything, so
    # a clean read (0) or an honest "nothing there" (1) both mean the
    # record reached the DATE AUDIT; a fault means it did not.
    if [ "${AUDIT_MODE}" = "on" ] && [ "${READER_RC}" -le 1 ]; then
        AUDIT_RECORDED="yes"
    fi
    case "${READER_RC}" in
        0)
            CLOCK_STATUS="read"
            ;;
        1)
            # Read, and there was no clock on this screen -- which is
            # what most menu keystrokes photograph.  A phrase or a date
            # may still have come back, and both are kept.
            CLOCK=""
            CLOCK_STATUS="unreadable"
            ;;
        "${TIMEOUT_EXPIRED}")
            CLOCK_STATUS="fault"
            CLOCK=""
            playthrough_warn "${OCR_SCRIPT} did not finish within" \
                "${OCR_TIMEOUT}s on ${FRAME_FILE} and was stopped"
            ;;
        *)
            # A FAULT CARRIES NO READING.  ocr_clock.py prints nothing
            # on a fault, so this is normally already empty -- but the
            # emptiness is asserted here rather than inherited, because
            # a reading kept beside CLOCK_STATUS=fault is a value the
            # manifest would record and timeline.py would difference,
            # produced by a read this file just declared unreliable.
            CLOCK_STATUS="fault"
            CLOCK=""
            ;;
    esac
else
    CLOCK_SOURCE="inline"
    playthrough_warn "ocr_clock.py or ${PLAYTHROUGH_PYTHON} is" \
        "unavailable; reading the clock with the inline" \
        "convert|tesseract|grep chain, which is the documented last" \
        "resort and a weaker reader than the module"
    INLINE_RC=0
    if inline_clock; then
        INLINE_RC=0
    else
        INLINE_RC=$?
    fi
    READER_RC="${INLINE_RC}"
    case "${READER_RC}" in
        0)
            CLOCK="${INLINE_OUT}"
            CLOCK_STATUS="read"
            ;;
        1)
            CLOCK_STATUS="unreadable"
            ;;
        *)
            CLOCK_STATUS="fault"
            CLOCK=""
            ;;
    esac
    # The inline chain reads a clock and nothing else: the date and the
    # coarse phrase are recognised by ocr_clock.py's own patterns, and
    # duplicating them here is exactly the divergence delegation exists
    # to prevent.  So it is said out loud, unconditionally, that this
    # frame carries no date -- the statement is about the reader's
    # capability and is true whether or not the audit was asked for.
    playthrough_warn "the inline reader performs no date extraction," \
        "so no date is reported for ${FRAME_FILE} and DATE_STATUS is" \
        "'unavailable' rather than 'unreadable': nothing looked"
    # And when the audit WAS asked for, the consequence downstream is
    # named too -- timeline.py must treat a frame with no record as
    # UNKNOWN, never as a day that did not turn.
    if [ "${AUDIT_MODE}" = "on" ]; then
        playthrough_warn "no date evidence was recorded for" \
            "${FRAME_FILE}, so timeline.py has no date for this frame" \
            "and must reconcile rather than assume the day did not" \
            "turn"
    fi
fi

# Whatever produced it, a reading leaves this file only if it is
# genuinely the contracted shape AND genuinely possible.  Re-checking a
# delegated value costs one pattern match and makes this file's honesty
# self-contained rather than inherited.
if [ "${CLOCK_STATUS}" = "read" ]; then
    if ! [[ "${CLOCK}" =~ ^${CLOCK_PATTERN}$ ]] ||
       ! possible_clock "${CLOCK}"; then
        die "${EX_CLOCK_FAULT}" "${CLOCK_SOURCE} returned \
'${CLOCK}' for ${FRAME_FILE}, which is not a possible \
HH:MM:SS reading.  Refusing to emit it: a reading that cannot be true \
is not reported as a clock."
    fi
fi

# A FAULT is not an unreadable clock.  The faults that actually happen
# -- an off-contract 24_HOUR option, a missing OCR toolchain, a frame
# outside the capture directory -- are standing misconfigurations that
# would report EVERY later frame as unreadable, collapsing every
# duration to the floor while every count still tallied.  That is the
# failure mode this pipeline exists to make loud, so it is fatal by
# default.
if [ "${CLOCK_STATUS}" = "fault" ]; then
    if [ "${STRICT_CLOCK}" -eq 1 ]; then
        die "${EX_CLOCK_FAULT}" "the clock read faulted on \
${FRAME_FILE} (${CLOCK_SOURCE} exit ${READER_RC}).  This is a fault, \
not an unreadable clock: fix it -- seed_options.py sets 24_HOUR=24h -- \
and recapture.  Carrying on with the fault recorded is a DIAGNOSTIC \
action (PLAYTHROUGH_CAPTURE_MODE=diagnostic with \
PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0), and such a capture is withdrawn \
rather than kept: a frame whose clock could not be read has no \
duration to derive."
    fi
    # STRICT_CLOCK=0 IS DIAGNOSTIC-ONLY, so this is not a frame being
    # kept: the fault is RETAINED in the payload (CLOCK_STATUS=fault,
    # no reading) for whoever is diagnosing it, and the PNG is withdrawn
    # out of the working tree at the commit point below, which exits
    # EX_DIAGNOSTIC.  Saying "kept" here would describe an outcome this
    # mode cannot produce -- a frame with no readable clock has no
    # duration to derive, so it can never join the record.
    playthrough_warn "the clock read faulted on ${FRAME_FILE} and" \
        "PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0, so the fault is recorded" \
        "as CLOCK_STATUS=fault with no reading and this DIAGNOSTIC" \
        "capture continues; the frame itself is withdrawn to" \
        "${REJECT_DIR} rather than added to" \
        "${PLAYTHROUGH_FRAMES_DIR}"
fi

# ---------------------------------------------------------------------
# THE TELEMETRY HANDOFF -- REPORTED HERE, PERSISTED BY THE ORCHESTRATOR
#
# Every per-frame observation this invocation made -- the clock, the
# coarse phrase, the sidebar DATE line, the crop they were read from,
# the luminance, the geometry, the capture tool and the instant of the
# grab -- leaves through the machine payload below, and NOTHING is
# appended to the telemetry sidecar from here.
#
# THAT IS A WRITE-SURFACE DECISION, not a convenience.  This file's
# contract is exactly one PNG in playthrough/frames/ per keystroke;
# session.py owns the frame counter, the manifest row and the sidecar
# that accompanies it.  Appending the sidecar here split ONE logical
# transaction -- publish the frame, record the row -- across two
# processes with no coordinator, and gave this script a second,
# redirectable destination inside the working tree: a path settable from
# the environment, appended to through a plain open(), with no
# O_NOFOLLOW, no lock and no fsync, plus a no-interpreter fallback that
# wrote one JSON record through six separate redirections and could
# therefore interleave or leave a permanent half-row.  None of that is
# fixable while the writer is here, because the orchestrator has to
# append the manifest row for the same frame anyway: one owner, one
# append, one atomic decision.
#
# The evidence is not weakened by moving it.  Every field the sidecar
# row carried is in the payload below under its own key (DATE is the
# row's own spelling of CLOCK_DATE, reported beside it so a reader can
# see the derivation), and the DATE AUDIT is untouched: ocr_clock.py
# still appends it as it reads, through a hardened
# O_APPEND|O_CREAT|O_NOFOLLOW descriptor with an fsync, so the date
# evidence timeline.py cross-checks against is persisted by the module
# that produced it whatever the orchestrator does.  OBSERVATIONS names
# the canonical destination -- env.sh's PLAYTHROUGH_OBSERVATIONS, with
# no override -- so the caller appends where timeline.py will look.
# ---------------------------------------------------------------------


# The coarse phrase and the date come back from the SAME read as the
# clock, so there is nothing left to fetch here -- one OCR pass per
# frame, and three readings that therefore cannot disagree about the
# same pixels.  What remains is the discard: 'auto' means the phrase is
# the reading that matters only when there was no clock, because without
# a watch the sidebar shows a phrase INSTEAD of a time
# [src/display.cpp:207-218].  With a clock in hand a phrase is noise, so
# it is dropped from the output rather than reported beside a time it
# does not qualify.  Nothing is ever converted between the two.
#
# The date is NOT subject to that rule: it is evidence for the rollover
# guard whether or not the clock was read, so it is always reported.
if [ "${PHRASE_MODE}" = "off" ] ||
   { [ "${PHRASE_MODE}" = "auto" ] &&
     [ "${CLOCK_STATUS}" = "read" ]; }; then
    TIME_PHRASE=""
fi

# ---------------------------------------------------------------------
# The date's status, derived from the read that already happened.
#
# An unreadable date is ORDINARY -- the menu and character-creation
# frames have no sidebar at all -- so it is recorded as such and is
# never fatal.  A FAULT is already fatal above under
# PLAYTHROUGH_CAPTURE_STRICT_CLOCK, and is recorded here rather than
# re-raised.  The inline chain has no date extraction at all, and that
# is stated as 'unavailable' rather than passed off as 'unreadable':
# timeline.py must treat a frame with no date as UNKNOWN, never as a day
# that did not turn.  Nothing is ever inferred -- no date is derived
# from the clock, from the previous frame, or from the wall clock.
# ---------------------------------------------------------------------
if [ "${CLOCK_MODE}" != "on" ]; then
    DATE_STATUS="skipped"
elif [ "${CLOCK_SOURCE}" != "ocr_clock.py" ]; then
    DATE_STATUS="unavailable"
elif [ -n "${CLOCK_DATE}" ]; then
    DATE_TEXT="${CLOCK_DATE}"
    DATE_STATUS="read"
elif [ "${CLOCK_STATUS}" = "fault" ]; then
    DATE_STATUS="fault"
else
    DATE_STATUS="unreadable"
fi

# ---------------------------------------------------------------------
# OUTPUT, THEN THE LOG, THEN -- LAST OF ALL -- THE COMMIT POINT.
#
# The order below is the whole of this file's atomicity guarantee, and
# it is deliberate to the line.
#
# `exit 0` means "there is exactly one new frame AND this invocation's
# output is complete", because session.py reads that as licence to
# append exactly one manifest row.  Setting KEPT=1 before the output
# was produced broke the second half of that promise: if a write to
# stdout failed -- a closed pipe, a full disk -- this script exited
# non-zero while the EXIT trap, seeing KEPT=1, left the frame in place.
# The caller then had no row for a frame that existed, and the
# frames-count == manifest-line-count identity that verify_artifacts.sh
# asserts was already broken before the session had properly begun.
#
# So: the payload is assembled in ONE buffer, written with ONE printf,
# and only then is the frame committed.  A failure anywhere before the
# commit point withdraws the frame, which is the honest outcome -- the
# caller sees a non-zero status, discards whatever it read, and no
# frame is left unaccounted for.  A signal is covered too: a shell
# killed by SIGPIPE never reaches its EXIT trap, so the PIPE, INT, TERM
# and HUP traps installed above withdraw the frame themselves.
# ---------------------------------------------------------------------

# Build the complete payload first.  `line KEY VALUE` appends to it
# rather than writing, so a partially-written contract is impossible:
# either every key reaches stdout or none of them does.
PAYLOAD=""
line() {
    PAYLOAD="${PAYLOAD}$1=$2
"
}

# The mode comes first because it decides what the rest of the payload
# describes.  In diagnostic mode FRAME_FILE and FRAME_PATH are EMPTY --
# the frame is about to leave the working tree, so there is no such path
# to report -- and DIAGNOSTIC_PATH says where it went instead.  Both keys
# are always present: a key that sometimes disappears is a key a
# consumer papers over with a default.
line CAPTURE_MODE "${CAPTURE_MODE}"
line FRAME_INDEX "${FRAME_INDEX}"
line FRAME_NAME "${FRAME_NAME}"
if [ "${CAPTURE_MODE}" = "production" ]; then
    line FRAME_FILE "${FRAME_FILE}"
    line FRAME_PATH "${FRAME_PATH}"
    line DIAGNOSTIC_PATH ""
else
    line FRAME_FILE ""
    line FRAME_PATH ""
    line DIAGNOSTIC_PATH "${REJECT_DIR}/${FRAME_NAME}"
fi
line FRAME_BYTES "${FRAME_BYTES}"
# The sha256 of the bytes that were published, taken immediately after
# the atomic rename.  EMPTY IN DIAGNOSTIC MODE, exactly as FRAME_FILE is
# and for the same reason: that frame is about to leave the working tree,
# so a digest of it would attest a file no record may mention.  The key
# is always present, because a key that sometimes disappears is a key a
# consumer papers over with a default.
if [ "${CAPTURE_MODE}" = "production" ]; then
    line FRAME_SHA256 "${FRAME_SHA256}"
else
    line FRAME_SHA256 ""
fi
line FRAME_FORMAT "${FRAME_FORMAT}"
line FRAME_GEOMETRY "${FRAME_GEOMETRY}"
line REAL_TS "${REAL_TS}"
line CAPTURE_TOOL "${CAPTURE_TOOL}"
line LUMA_MEAN "${LUMA_MEAN}"
line LUMA_STDDEV "${LUMA_STDDEV}"
line CLOCK_RECT "${CLOCK_RECT}"
line CLOCK_RECT_FROM "${CLOCK_RECT_FROM}"
line CLOCK_SOURCE "${CLOCK_SOURCE}"
line CLOCK_STATUS "${CLOCK_STATUS}"
line CLOCK "${CLOCK}"
line TIME_PHRASE "${TIME_PHRASE}"
line CLOCK_DATE "${CLOCK_DATE}"
line DATE "${DATE_TEXT}"
line DATE_STATUS "${DATE_STATUS}"
line DATE_AUDIT "${AUDIT_RECORDED}"
if [ "${CAPTURE_MODE}" = "production" ]; then
    line OBSERVATIONS "${OBSERVATIONS}"
else
    # A withdrawn frame is owed no row at all, so no destination is
    # named for one.  A telemetry row for a frame no manifest will ever
    # mention is an orphan record, and the sidecar's whole value to
    # timeline.py is that it lines up with the rows one for one.
    line OBSERVATIONS ""
fi

# One write.  A failure here is fatal and the frame is withdrawn: the
# caller must never be left believing a frame is unreported when it is
# on disk, or reported when it is not.
if ! printf '%s' "${PAYLOAD}"; then
    die "${EX_CAPTURE}" "the output contract could not be written to \
stdout for ${FRAME_FILE}; the frame is withdrawn so that no frame \
exists without a caller that knows about it"
fi

# ---------------------------------------------------------------------
# THE LAST FALLIBLE STATEMENT, and it is deliberately BEFORE the commit
# point rather than after it.
#
# This log line is the human-readable record of the capture, and writing
# it can fail: stderr may be closed, full, or a pipe whose reader has
# gone -- in which case, under `set -e` or a PIPE trap, this script ends
# non-zero.  While it sat after KEPT=1 that was exactly the orphan the
# 1:1 invariant cannot tolerate: the EXIT trap saw a frame it had been
# told to keep, left the PNG in playthrough/frames/, and the caller --
# seeing a non-zero status -- correctly declined to append a manifest
# row for it.  One frame, no row, and every later count off by one.
#
# So everything that can fail happens here, while the frame is still
# withdrawable, and the commit below is nothing but assignments.
# ---------------------------------------------------------------------
if [ "${CAPTURE_MODE}" = "production" ]; then
    playthrough_log "captured ${FRAME_FILE} (${FRAME_GEOMETRY}," \
        "${FRAME_BYTES} bytes) clock=${CLOCK:-<none>}" \
        "status=${CLOCK_STATUS} date=${DATE_TEXT:-<none>}"
fi

# ---------------------------------------------------------------------
# THE COMMIT POINT.  The frame has passed every check and this
# invocation's whole contract has been delivered, so the frame is ours
# to keep: the EXIT trap will no longer withdraw it, and a superseded
# frame moved aside stays aside.
#
# THESE THREE STATEMENTS ARE CONSECUTIVE, and that is the whole of the
# guarantee: two assignments and an exit.  No command runs between the
# commit and the exit, so nothing after the commit can fail -- there is
# no code path that leaves a kept frame behind a non-zero status.
#
# DIAGNOSTIC: the frame is NOT ours to keep, and KEPT deliberately stays
# 0.  The script exits EX_DIAGNOSTIC, which sends the EXIT trap down the
# same withdrawal path a failure takes: the PNG is moved out of the
# working tree into the private 0700 reject directory under its own
# name, so it can be looked at and can never be committed as a session
# frame or counted against the manifest.  Combined with an empty
# FRAME_FILE and a non-zero status, a diagnostic capture is structurally
# unusable as evidence -- which is what makes the relaxed safeguards
# above safe to offer at all.
# ---------------------------------------------------------------------
if [ "${CAPTURE_MODE}" = "production" ]; then
    KEPT=1
    BACKUP=""
    exit "${EX_OK}"
fi

playthrough_warn "DIAGNOSTIC capture of index ${FRAME_INDEX}" \
    "(${FRAME_GEOMETRY}, ${FRAME_BYTES} bytes)" \
    "clock=${CLOCK:-<none>} status=${CLOCK_STATUS}.  The frame is" \
    "being withdrawn to ${REJECT_DIR}/${FRAME_NAME}; no frame was" \
    "added to ${PLAYTHROUGH_FRAMES_DIR}, no telemetry row is owed or" \
    "reported, and this invocation exits ${EX_DIAGNOSTIC} so it" \
    "cannot be mistaken for a capture that belongs to the record."
exit "${EX_DIAGNOSTIC}"
