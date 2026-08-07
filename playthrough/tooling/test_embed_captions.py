#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/embed_captions.sh.

embed_captions.sh takes the finished film and the transcript and
produces the ONE artifact the closed-caption requirement is judged on.
Everything it does is therefore load-bearing in a way an ordinary mux is
not, and this suite exists to hold six properties that a well-meaning
edit could each quietly undo:

    python3 playthrough/tooling/test_embed_captions.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED

* THE THREE FILES AND NOTHING ELSE -- the positionals may only CONFIRM
  playthrough/cata-play.mp4, playthrough/transcript.srt and
  playthrough/cata-play-cc.mp4.  A different spelling of the same file
  is accepted; a different file is refused, including one inside the
  working tree, including the base render itself, and including a
  symlinked component.  This is the property that stops an MP4 from
  being written over the manifest, the timeline or the save.
* THE RECIPE IS THE RECIPE -- the mandated flag groups are present, the
  two stream maps and the two metadata drops are present, the argument
  count is exact, and no filter, encoder or scale appears anywhere in
  the command.
* NOTHING TRAVELS IN -- a container that came back carrying an audio,
  data or attachment stream, a chapter, or a metadata tag outside the
  structural whitelist is refused rather than published.
* THE CAPTIONS FIT INSIDE THE PICTURE -- a cue track that outlasts the
  film is refused, and so is one whose duration ffprobe could not
  measure.  An unverifiable timing is a refusal, not a skipped check.
* EVERY EXTERNAL CALL IS BOUNDED -- each ffmpeg and ffprobe invocation
  runs under the stage ceiling, so one wedged probe cannot stop a
  sequential pipeline with no diagnosis.
* THE PICTURE IS PROVEN COPIED -- with SHA-256, with the algorithm
  recorded beside the digest, and a mismatch refuses.
* AND A REFUSAL PUBLISHES NOTHING -- every failure path above leaves the
  output path exactly as it was found and takes the staging file with
  it.

HOW A MUX IS TESTED WITHOUT ffmpeg
Every test runs the REAL embed_captions.sh inside a temporary SANDBOX
CHECKOUT carrying data/, src/path_info.cpp and copies of env.sh and
embed_captions.sh, so env.sh's BASH_SOURCE resolution points the whole
artifact layout at the sandbox and nothing can touch the committed
artifacts.  The sandbox lives under a PRIVATE base rather than under
/tmp, because env.sh verifies the ownership and writability of every
tool it resolves and of every directory above it; on this host /tmp is
mode 2777, so an ancestor walk fails there no matter what the sandbox
itself looks like.

The shell is started with `env -i` and a PATH holding only a
purpose-built tool directory: symlinks to the coreutils the script
genuinely needs, plus recording stubs for ffmpeg, ffprobe and timeout.
The ffprobe stub answers by QUESTION rather than by call order -- it
parses -select_streams and -show_entries and looks the answer up -- so a
test changes one measurement by naming it, and a reordering of the
script's probes does not silently invalidate the suite.  The timeout
stub records and then execs, which is how "every external call is
bounded" becomes an assertion: the number of timeout invocations must
equal the number of ffmpeg and ffprobe invocations.

Standard library only.  Nothing outside the temporary directory is
written.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))

# The exit codes embed_captions.sh documents in its header, taken from
# its own constants so a rename cannot make this suite pass by agreeing
# with itself.
EX_OK = 0
EX_USAGE = 1
EX_LAYOUT = 2
EX_INPUT = 3
EX_MUX = 4
EX_VERIFY = 5
EX_PREREQ = 8

# What a passing run measures.  The durations are the real artifacts'
# numbers, which is deliberate: the caption track genuinely ends 0.06s
# inside the picture, so the epsilon in the overrun test is being
# exercised against a real margin rather than an invented one.
VIDEO_DURATION = "337.560000"
SUBTITLE_DURATION = "337.500000"
CUES = 560
VIDEO_FRAMES = "693"

# The four tags the MP4 muxer writes for itself, which is exactly the
# whitelist embed_captions.sh allows.
STRUCTURAL_TAGS = ("major_brand=isom",
                   "minor_version=512",
                   "compatible_brands=isomiso2avc1mp41",
                   "encoder=Lavf61.7.100")

# A hex digest of the right shape, printed by the streamhash stub in the
# muxer's own `<index>,<type>,<ALGO>=<digest>` form.
DIGEST = "82d8e26462f1792fe7e50ad7cefb239163d13969a8d3d6947a0f8cd5" \
         "ffbad3f6"


def _interpreter():
    """The interpreter env.sh should be pointed at.

    env.sh warns when the resolved interpreter is not the CPython 3.12
    that requirements.lock pins its wheels for, and a suite that
    provoked that warning on every run would be teaching a reader to
    ignore it.  The provisioned environment is preferred and the
    system interpreter is the fallback -- embed_captions.sh calls no
    Python at all, so either serves; only the diagnostics differ.
    """
    provisioned = "/opt/playthrough-venv/bin/python"
    if os.path.isfile(provisioned):
        return provisioned
    return shutil.which("python3") or "python3"


INTERPRETER = _interpreter()

REAL_TOOLS = (
    "bash", "awk", "grep", "mkdir", "mv", "rm", "wc", "tail", "head",
    "dirname", "basename", "cat", "env", "chmod", "cp", "ls", "tr",
    "sed", "sort", "readlink", "printf", "touch", "python3", "date",
    # stat is how env.sh verifies the runtime directory; id answers for
    # the owner when $EUID is not exported; realpath and flock belong to
    # the confinement and locking machinery; mktemp reserves the scratch
    # cue file.  All coreutils or util-linux, and listed here because
    # this PATH is exhaustive.
    "stat", "id", "realpath", "flock", "cut", "sleep", "mktemp",
    # sha256sum is what the provenance gate compares a manifest's declared
    # digest against, and what the single post-rename check uses to prove
    # the published bytes are the bytes that were verified.  It is the
    # genuine tool rather than a stub throughout: a digest that a stub
    # could make agree would make the gate a formality.
    "sha256sum",
)


def _is_private(path):
    """True when PATH and every directory above it are trustworthy.

    The same rule env.sh's playthrough_verify_executable applies: every
    component is owned by root or by this user, and none of them is
    group- or world-writable, so nobody else can substitute a file
    between a check and the run that follows it.
    """
    euid = os.geteuid()
    current = os.path.abspath(path)
    while True:
        try:
            info = os.stat(current)
        except OSError:
            return False
        if info.st_uid not in (0, euid):
            return False
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
        parent = os.path.dirname(current)
        if parent == current:
            return True
        current = parent


def _sandbox_base():
    """Where this suite's sandboxes live, and why not the temp dir.

    env.sh resolves every external tool and then verifies it: owned by
    root or by this user, not group- or world-writable, and the same of
    every directory above it.  A sandbox whose bin/ fails that walk
    would make every test here exercise the prerequisite failure and
    assert nothing about the mux.  /tmp cannot serve on this host, which
    has it at mode 2777 -- world-writable with no sticky bit -- so the
    walk fails there regardless of the sandbox's own mode.  $HOME serves
    on an ordinary host and /run on a root one, and
    $PLAYTHROUGH_TEST_TMPDIR overrides both.  None available means this
    suite skips with that named as the remedy, rather than quietly
    testing something weaker.
    """
    candidates = []
    nominated = os.environ.get("PLAYTHROUGH_TEST_TMPDIR")
    if nominated:
        candidates.append(nominated)
    home = os.environ.get("HOME")
    if home:
        candidates.append(os.path.join(home, ".cache"))
        candidates.append(home)
    candidates.append("/run")
    for candidate in candidates:
        if not candidate or not os.path.isdir(candidate):
            continue
        if not os.access(candidate, os.W_OK):
            continue
        if _is_private(candidate):
            return candidate
    return None


SANDBOX_BASE = _sandbox_base()

NO_SANDBOX_BASE = (
    "no private directory to build a sandbox in: env.sh verifies the "
    "ownership and writability of every tool it resolves and of every "
    "directory above it, so a sandbox under a world-writable base "
    "would test the prerequisite failure instead of the mux.  Set "
    "$PLAYTHROUGH_TEST_TMPDIR to a directory owned by this user with "
    "no group or world write bit on it or on any of its parents.")

# The ffprobe stub's answer table.  Keyed by the question, so a test
# changes one measurement by name and the script may reorder its probes
# without invalidating anything here.
PROBE_DEFAULTS = {
    "STUB_V_STREAMS": "1",
    "STUB_A_STREAMS": "0",
    "STUB_D_STREAMS": "0",
    "STUB_T_STREAMS": "0",
    # The same census, asked of the input film before the mux and of
    # the published container after the rename.
    "STUB_IN_A_STREAMS": "0",
    "STUB_IN_D_STREAMS": "0",
    "STUB_IN_T_STREAMS": "0",
    "STUB_OUT_A_STREAMS": "0",
    "STUB_OUT_D_STREAMS": "0",
    "STUB_OUT_T_STREAMS": "0",
    "STUB_S_STREAMS": "1",
    "STUB_CHAPTERS": "0",
    "STUB_V_CODEC": "h264",
    "STUB_WIDTH": "1920",
    "STUB_HEIGHT": "1080",
    "STUB_V_DURATION": VIDEO_DURATION,
    "STUB_IN_V_DURATION": VIDEO_DURATION,
    "STUB_NB_FRAMES": VIDEO_FRAMES,
    "STUB_IN_NB_FRAMES": VIDEO_FRAMES,
    "STUB_S_INDEX": "1",
    "STUB_S_CODEC": "mov_text",
    "STUB_S_LANGUAGE": "eng",
    "STUB_S_DURATION": SUBTITLE_DURATION,
    "STUB_CONTAINER_DURATION": VIDEO_DURATION,
    "STUB_FORMAT_TAGS": " ".join(STRUCTURAL_TAGS),
    "STUB_HASH_IN": DIGEST,
    "STUB_HASH_OUT": DIGEST,
    "STUB_HASH_SHAPE": "keyed",
    "STUB_MUXERS": "1",
    "STUB_MUX_RC": "0",
    "STUB_MUX_BYTES": "8192",
    "STUB_ROUND_TRIP_CUES": str(CUES),
    "STUB_PROBE_RC": "0",
}


# The ffprobe stub.  It parses the question and looks the answer up, so
# the suite never depends on the order embed_captions.sh asks in.
FFPROBE_STUB = r"""
select=""
entries=""
target=""
chapters=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        -select_streams) select="$2"; shift 2 ;;
        -show_entries) entries="$2"; shift 2 ;;
        -show_chapters) chapters=1; shift ;;
        -i) target="$2"; shift 2 ;;
        *) shift ;;
    esac
done
if [ "${STUB_PROBE_RC:-0}" != "0" ]; then
    printf '%s\n' "stub ffprobe refusing on purpose" >&2
    exit "${STUB_PROBE_RC}"
fi
# THREE ROLES, told apart by the name.  The staging file is a dotfile
# sibling of the output, the published container is the -cc.mp4, and
# anything else is one of the two inputs.  The stream census is asked
# of all three at different points in the run -- the input before the
# mux, the staged container before the rename, the published one after
# it -- and each has to be answerable independently or a test cannot
# say WHICH of the three refused.
staged=0
published=0
case "${target##*/}" in
    .*) staged=1 ;;
    *-cc.mp4) published=1 ;;
esac
if [ "${staged}" = "1" ] &&
        [ "${STUB_STAGED_PROBE_RC:-0}" != "0" ]; then
    printf '%s\n' "stub ffprobe refusing the staged container" >&2
    exit "${STUB_STAGED_PROBE_RC}"
fi
repeat() {
    local count="$1" i=0
    while [ "${i}" -lt "${count}" ]; do
        printf '%s\n' "${i}"
        i=$((i + 1))
    done
}
# census STAGED INPUT PUBLISHED -- the count for whichever file is
# being asked about.
census() {
    if [ "${staged}" = "1" ]; then
        repeat "$1"
    elif [ "${published}" = "1" ]; then
        repeat "$3"
    else
        repeat "$2"
    fi
}
if [ "${chapters}" = "1" ]; then
    repeat "${STUB_CHAPTERS}"
    exit 0
fi
case "${entries}" in
    format=duration) printf '%s\n' "${STUB_CONTAINER_DURATION}" ;;
    format_tags)
        for tag in ${STUB_FORMAT_TAGS}; do
            printf 'TAG:%s\n' "${tag}"
        done
        ;;
    stream=index)
        case "${select}" in
            v) repeat "${STUB_V_STREAMS}" ;;
            a) census "${STUB_A_STREAMS}" \
                   "${STUB_IN_A_STREAMS}" \
                   "${STUB_OUT_A_STREAMS}" ;;
            d) census "${STUB_D_STREAMS}" \
                   "${STUB_IN_D_STREAMS}" \
                   "${STUB_OUT_D_STREAMS}" ;;
            t) census "${STUB_T_STREAMS}" \
                   "${STUB_IN_T_STREAMS}" \
                   "${STUB_OUT_T_STREAMS}" ;;
            s) repeat "${STUB_S_STREAMS}" ;;
            s:0) printf '%s\n' "${STUB_S_INDEX}" ;;
            *) printf '0\n' ;;
        esac
        ;;
    stream=codec_name)
        case "${select}" in
            s:0) printf '%s\n' "${STUB_S_CODEC}" ;;
            *) printf '%s\n' "${STUB_V_CODEC}" ;;
        esac
        ;;
    stream=width) printf '%s\n' "${STUB_WIDTH}" ;;
    stream=height) printf '%s\n' "${STUB_HEIGHT}" ;;
    stream=duration)
        case "${select}" in
            s:0) printf '%s\n' "${STUB_S_DURATION}" ;;
            *)
                if [ "${staged}" = "1" ]; then
                    printf '%s\n' "${STUB_V_DURATION}"
                else
                    printf '%s\n' "${STUB_IN_V_DURATION}"
                fi
                ;;
        esac
        ;;
    stream=nb_frames|stream=nb_read_packets)
        if [ "${staged}" = "1" ]; then
            printf '%s\n' "${STUB_NB_FRAMES}"
        else
            printf '%s\n' "${STUB_IN_NB_FRAMES}"
        fi
        ;;
    stream_tags=language) printf '%s\n' "${STUB_S_LANGUAGE}" ;;
    # The two published-file readouts, in the keyed form the acceptance
    # gate quotes verbatim.
    stream=index,codec_name:stream_tags=language)
        printf 'index=%s\n' "${STUB_S_INDEX}"
        printf 'codec_name=%s\n' "${STUB_S_CODEC}"
        printf 'TAG:language=%s\n' "${STUB_S_LANGUAGE}"
        ;;
    stream=codec_name,width,height)
        printf 'codec_name=%s\n' "${STUB_V_CODEC}"
        printf 'width=%s\n' "${STUB_WIDTH}"
        printf 'height=%s\n' "${STUB_HEIGHT}"
        ;;
    *) printf '\n' ;;
esac
exit 0
"""

# The ffmpeg stub.  Three shapes of invocation, told apart by the flags
# the script itself uses: the muxer list, the stream hash, the cue
# round-trip, and otherwise the mux.
FFMPEG_STUB = r"""
argv="$*"
case "${argv}" in
    *-muxers*)
        printf '%s\n' " E matroska  Matroska"
        if [ "${STUB_MUXERS:-1}" = "1" ]; then
            printf '%s\n' " E streamhash  Per-stream hash testing"
        fi
        exit 0
        ;;
    *-f\ streamhash*)
        which=IN
        for word in ${argv}; do
            case "${word##*/}" in
                .*) which=OUT ;;
            esac
        done
        if [ "${which}" = "OUT" ]; then
            value="${STUB_HASH_OUT}"
        else
            value="${STUB_HASH_IN}"
        fi
        case "${STUB_HASH_SHAPE:-keyed}" in
            keyed) printf '0,v,SHA256=%s\n' "${value}" ;;
            bare) printf '%s\n' "${value}" ;;
            empty) printf '\n' ;;
        esac
        exit 0
        ;;
    *-f\ srt*)
        target="${!#}"
        : >"${target}"
        i=1
        while [ "${i}" -le "${STUB_ROUND_TRIP_CUES}" ]; do
            printf '%s\n' "${i}" >>"${target}"
            printf '%s\n' "00:00:00,000 --> 00:00:00,250" >>"${target}"
            printf '%s\n\n' "a cue" >>"${target}"
            i=$((i + 1))
        done
        exit 0
        ;;
esac
target="${!#}"
if [ "${STUB_MUX_RC:-0}" != "0" ]; then
    printf '%s\n' "stub ffmpeg refusing the mux on purpose" >&2
    exit "${STUB_MUX_RC}"
fi
# %*s pads to a width, which is the cheapest way for bash alone to
# write a file of a chosen size; a width of zero writes nothing, which
# is how "ffmpeg reported success and wrote nothing" is arranged.
printf '%*s' "${STUB_MUX_BYTES}" '' >"${target}"
exit 0
"""


# The timeout stub.  It records and then execs, which is what makes
# "every external call is bounded" measurable: the recorded count of
# timeout invocations must equal the count of ffmpeg and ffprobe ones.
TIMEOUT_STUB = r"""
shift
exec "$@"
"""

SRT_BODY = "".join(
    "%d\n00:00:%02d,000 --> 00:00:%02d,250\na line of commentary\n\n"
    % (n, n % 60, n % 60) for n in range(1, CUES + 1))


class MuxFixture(unittest.TestCase):
    """A sandbox checkout, a stubbed toolchain, and one mux run."""

    def setUp(self):
        if SANDBOX_BASE is None:
            self.skipTest(NO_SANDBOX_BASE)
        self.root = tempfile.mkdtemp(prefix="blitzy_captions_",
                                     dir=SANDBOX_BASE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.checkout = os.path.join(self.root, "checkout")
        self.tooling = os.path.join(self.checkout, "playthrough",
                                    "tooling")
        os.makedirs(self.tooling)
        os.makedirs(os.path.join(self.checkout, "data"))
        os.makedirs(os.path.join(self.checkout, "src"))
        self.write(os.path.join(self.checkout, "src", "path_info.cpp"),
                   "// a marker, not the engine\n")
        for name in ("env.sh", "embed_captions.sh"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        self.script = os.path.join(self.tooling, "embed_captions.sh")
        os.chmod(self.script, 0o755)
        self.dir = os.path.join(self.checkout, "playthrough")
        os.makedirs(os.path.join(self.dir, "build"))
        self.movie = os.path.join(self.dir, "cata-play.mp4")
        self.srt = os.path.join(self.dir, "transcript.srt")
        self.output = os.path.join(self.dir, "cata-play-cc.mp4")
        # A film big enough to clear the size floor, and a cue file with
        # the real cue count so the round-trip comparison is meaningful.
        self.write(self.movie, "x" * 32768)
        self.write(self.srt, SRT_BODY)
        # The two generation manifests, with REAL digests of the two files
        # just written.  The provenance gate reads them before it muxes
        # anything, so a fixture without them exercises the refusal rather
        # than the mux -- and the digests are genuine because a fixture
        # that could make them agree without hashing would make the gate a
        # formality here and nowhere else.
        self.movie_manifest = os.path.join(self.dir, "build",
                                           "movie.json")
        self.transcript_manifest = os.path.join(self.dir, "build",
                                                "transcript.json")
        self.timeline_sha = "a" * 64
        self.publish_manifests()
        # The two names the publication step uses around the rename: the
        # previous film, copied aside so a failure can be undone, and the
        # quarantine a container whose publication could not be confirmed
        # is moved to.
        self.retained = os.path.join(self.dir, ".cata-play-cc.previous.mp4")
        self.quarantine = os.path.join(self.dir,
                                       ".cata-play-cc.rejected.mp4")
        self.stub_log = os.path.join(self.root, "stub.log")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        self.link_real_tools()
        self.stub("ffprobe", FFPROBE_STUB)
        self.stub("ffmpeg", FFMPEG_STUB)
        self.stub("timeout", TIMEOUT_STUB)

    # -- fixture plumbing --------------------------------------------

    def write(self, path, text, mode=None):
        """Write a file, creating its parent, and return the path.

        AN EXISTING SYMLINK IS REPLACED, NEVER WRITTEN THROUGH.  This
        fixture puts symlinks to real system tools on a private PATH and
        then overrides some of them with stubs; opening such a name for
        writing would follow the link and truncate the HOST's binary.
        """
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        if os.path.islink(path):
            os.unlink(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def digest_of(self, path):
        """Return the sha256 of a file's bytes, as the script reads it."""
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def publish_manifests(self, movie_timeline=None, srt_timeline=None,
                          movie_sha=None, srt_sha=None):
        """Write the two generation manifests the mux requires.

        Defaults describe the films and cues actually on disk under one
        timeline, which is the honest case.  Every argument exists so a
        test can break exactly one link of the provenance chain.
        """
        movie = {
            "version": 1,
            "stage": "movie",
            "timeline": {
                "path": "playthrough/timeline.json",
                "sha256": (self.timeline_sha if movie_timeline is None
                           else movie_timeline),
            },
            "concat_list": {"path": "playthrough/build/concat.txt",
                            "sha256": "c" * 64, "bytes": 1},
            "movie": {
                "path": "playthrough/cata-play.mp4",
                "sha256": (self.digest_of(self.movie) if movie_sha is None
                           else movie_sha),
                "bytes": os.path.getsize(self.movie),
            },
        }
        transcript = {
            "version": 1,
            "stage": "transcript",
            "timeline": {
                "path": "playthrough/timeline.json",
                "sha256": (self.timeline_sha if srt_timeline is None
                           else srt_timeline),
            },
            "outputs": [
                {"path": "playthrough/transcript.srt",
                 "sha256": (self.digest_of(self.srt) if srt_sha is None
                            else srt_sha),
                 "bytes": os.path.getsize(self.srt)},
                {"path": "playthrough/transcript.md",
                 "sha256": "d" * 64, "bytes": 2},
            ],
        }
        self.write(self.movie_manifest,
                   json.dumps(movie, indent=2, sort_keys=True) + "\n")
        self.write(self.transcript_manifest,
                   json.dumps(transcript, indent=2,
                              sort_keys=True) + "\n")

    def link_real_tools(self):
        """Symlink the genuine coreutils the script needs."""
        for tool in REAL_TOOLS:
            resolved = shutil.which(tool)
            link = os.path.join(self.bin, tool)
            if resolved and not os.path.exists(link):
                os.symlink(resolved, link)

    def stub(self, name, body):
        """Install a recording stub for one external command."""
        path = self.write(
            os.path.join(self.bin, name),
            "#!/bin/bash\n"
            'printf "%s\\t%s\\n" "' + name + '" "$*"'
            ' >>"${PLAYTHROUGH_STUB_LOG}"\n' + body,
            mode=0o755)
        resolved = os.path.realpath(path)
        if not resolved.startswith(os.path.realpath(self.root)):
            raise AssertionError(
                "%s resolved to %s, outside the sandbox: a stub must "
                "never be written through a symlink to a host tool"
                % (path, resolved))
        return path

    # -- running it --------------------------------------------------

    def supported_os_release(self):
        """Write, and name, an os-release the support table accepts.

        Ubuntu 24.04 LTS -- a real release, genuinely in support until
        2029-04 by env.sh's own dated table -- so the platform check
        passes because it PASSES, not because anything was relaxed.  The
        file lives in the sandbox, and env.sh honours the nomination only
        because this tree is not a git working tree.
        """
        path = os.path.join(self.root, "os-release")
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('ID=ubuntu\n'
                             'VERSION_ID="24.04"\n'
                             'PRETTY_NAME="Ubuntu 24.04.3 LTS"\n')
        return path

    def run_mux(self, args=(), **environment):
        """Run embed_captions.sh in the sandbox; report the result."""
        env = {
            "PATH": self.bin,
            "PLAYTHROUGH_STUB_LOG": self.stub_log,
            # THE PLATFORM GATE IS SATISFIED, NOT WAIVED -- AND THE
            # DIFFERENCE IS THE WHOLE POINT.  This fixture used to set
            # PLAYTHROUGH_ALLOW_EOL_PLATFORM with a reason, on the
            # grounds that the waiver was not a trust bypass.  A
            # security review was right that it had to become one: an
            # end-of-life release means the ImageMagick, ffmpeg and
            # Xorg/Xvfb packages that photograph, decode and encode
            # every frame receive no further security fixes, and
            # recording that in a summary does not stop the next command
            # from producing evidence under it.  It is registered now,
            # so it forces the diagnostic state and this suite's own
            # subject would refuse.
            #
            # So the sandbox NOMINATES its platform facts instead, which
            # relaxes nothing: playthrough_check_platform runs in full
            # against the nominated file and still refuses an
            # out-of-support or untabulated release.  env.sh honours a
            # nomination ONLY in a tree git does not track -- a verified
            # property, not a declared one -- and this sandbox is such a
            # tree, while a real checkout is not.  The gate and the
            # nomination both have their own coverage in test_env.py.
            "PLAYTHROUGH_OS_RELEASE": self.supported_os_release(),
            "PLAYTHROUGH_PYTHON": INTERPRETER,
            # A short ceiling, so a test that wedges something fails
            # fast rather than holding the suite for fifteen minutes.
            "PLAYTHROUGH_CAPTION_TIMEOUT": "60",
            "PLAYTHROUGH_CAPTION_LOCK_TIMEOUT": "10",
        }
        env.update(PROBE_DEFAULTS)
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        command = ["/usr/bin/env", "-i"]
        command.extend("%s=%s" % item for item in env.items())
        command.extend(["/bin/bash", "--noprofile", "--norc",
                        self.script])
        command.extend(args)
        result = subprocess.run(command, cwd=self.checkout,
                                capture_output=True, timeout=300)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def mux(self, args=(), **environment):
        """Run a mux that is expected to succeed."""
        status, out, err = self.run_mux(args, **environment)
        self.assertEqual(
            status, EX_OK,
            msg="the mux failed (%d):\n%s" % (status, err))
        return self.payload(out), err

    def refuse(self, code, args=(), **environment):
        """Run a mux that is expected to be refused, and prove it was.

        A REFUSAL HAS TO PUBLISH NOTHING.  Asserting that here rather
        than in each test is what makes it impossible to add a refusal
        test that forgets to check it.
        """
        before = self.published_bytes()
        status, out, err = self.run_mux(args, **environment)
        self.assertEqual(
            status, code,
            msg="expected exit %d, got %d:\n%s" % (code, status, err))
        self.assertEqual(
            before, self.published_bytes(),
            msg=("a refused mux changed the output path; nothing may "
                 "be published by a run that failed"))
        self.assertEqual(
            [], self.staging_files(),
            msg=("a refused mux left its staging file behind: %s"
                 % self.staging_files()))
        return err + out

    def corrupt_the_rename(self):
        """Make `mv` change the bytes it moves onto the output.

        THE ONLY WAY TO SIMULATE THE FAULT THE POST-RENAME CHECK EXISTS
        FOR, which is a filesystem that does not move bytes faithfully.
        Every other `mv` -- including the two the restore performs --
        delegates to the genuine tool, so what is being exercised is one
        corrupted publication and a real recovery around it.
        """
        real = shutil.which("mv")
        marker = os.path.join(self.root, "rename-corrupted")
        # ONCE ONLY, and the marker is what limits it: the restore itself
        # moves the retained copy back onto the same destination, so a stub
        # that corrupted every move onto the output would break the
        # recovery it is meant to exercise.
        self.stub("mv", (
            'for arg in "$@"; do :; done\n'
            'if [ "${arg}" = "%s" ] && [ ! -e "%s" ]; then\n'
            '    : >"%s"\n'
            '    %s "$@"\n'
            '    printf "corrupted by the fixture\\n" >"${arg}"\n'
            '    exit 0\n'
            'fi\n'
            'exec %s "$@"\n')
            % (self.output, marker, marker, real, real))

    def refuse_after_publish(self, code, args=(), **environment):
        """Run a mux refused AFTER the rename, and prove the recovery.

        THE CONTRACT THIS ASSERTS IS A CORRECTED ONE.  The script used to
        run the byte-size comparison, both verbatim readouts and the stream
        census after the rename and, on failure, "leave the file in place
        for inspection" -- which meant the unverified container became the
        published film while the previous one, which had passed every
        check, was already gone.

        Every question about what the container HOLDS is now answered
        before the rename.  The one check after it compares the published
        bytes against the bytes that were verified, and a mismatch RESTORES
        the previous film and QUARANTINES the file that failed.
        """
        status, out, err = self.run_mux(args, **environment)
        self.assertEqual(
            status, code,
            msg="expected exit %d, got %d:\n%s" % (code, status, err))
        self.assertTrue(
            os.path.exists(self.quarantine),
            msg=("a container whose publication could not be confirmed "
                 "is quarantined, not left as the published film"))
        self.assertFalse(
            os.path.exists(self.retained),
            msg="and the retained copy is not left behind as well")
        return err + out

    # -- reading the result ------------------------------------------

    @staticmethod
    def payload(text):
        """Parse the KEY=value summary from stdout."""
        parsed = {}
        for line in text.splitlines():
            name, _, value = line.partition("=")
            parsed[name] = value
        return parsed

    def published_bytes(self):
        """The output's size, or None when it does not exist."""
        try:
            return os.path.getsize(self.output)
        except OSError:
            return None

    def staging_files(self):
        """Every dotfile left in the artifact directory."""
        return sorted(name for name in os.listdir(self.dir)
                      if name.startswith("."))

    def stub_calls(self, name=None):
        """The recorded invocations, optionally of one tool."""
        try:
            with open(self.stub_log, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            return []
        calls = []
        for line in lines:
            tool, _, argv = line.partition("\t")
            if name is None or tool == name:
                calls.append(argv)
        return calls


class TestTheHappyPath(MuxFixture):
    """A run with nothing wrong with it, and what it reports."""

    def test_it_publishes_the_captioned_container(self):
        payload, _ = self.mux()
        self.assertEqual(payload["OUTPUT_FILE"],
                         "playthrough/cata-play-cc.mp4")
        self.assertTrue(os.path.isfile(self.output))

    def test_the_summary_names_the_caption_track(self):
        payload, _ = self.mux()
        self.assertEqual(payload["SUBTITLE_CODEC"], "mov_text")
        self.assertEqual(payload["SUBTITLE_LANGUAGE"], "eng")

    def test_the_summary_reports_repository_relative_paths(self):
        payload, _ = self.mux()
        for key in ("INPUT_MOVIE", "INPUT_SRT", "OUTPUT_FILE"):
            self.assertFalse(
                payload[key].startswith("/"),
                msg=("%s must be reported relative to the checkout, "
                     "because an absolute path discloses where this "
                     "checkout lives: %s" % (key, payload[key])))

    def test_every_cue_survives_the_round_trip(self):
        payload, _ = self.mux()
        self.assertEqual(payload["CUES_IN"], str(CUES))
        self.assertEqual(payload["CUES_ROUND_TRIP"], str(CUES))

    def test_no_staging_file_survives_a_success(self):
        self.mux()
        self.assertEqual([], self.staging_files())


class TestTheRecipe(MuxFixture):
    """The mux command is the specified one, and only that."""

    def mux_argv(self):
        """The recorded argv of the mux invocation itself."""
        for argv in self.stub_calls("ffmpeg"):
            if "-c:s mov_text" in argv:
                return argv
        raise AssertionError("no mux invocation was recorded: %s"
                             % self.stub_calls("ffmpeg"))

    def test_it_carries_the_three_mandated_flag_groups(self):
        self.mux()
        argv = self.mux_argv()
        for needle in ("-c copy", "-c:s mov_text",
                       "-metadata:s:s:0 language=eng"):
            self.assertIn(needle, argv)

    def test_it_names_exactly_one_video_and_one_subtitle_stream(self):
        self.mux()
        argv = self.mux_argv()
        self.assertIn("-map 0:v:0", argv)
        self.assertIn("-map 1:s:0", argv)

    def test_it_inherits_no_metadata_and_no_chapters(self):
        self.mux()
        argv = self.mux_argv()
        self.assertIn("-map_metadata -1", argv)
        self.assertIn("-map_chapters -1", argv)

    def test_nothing_touches_the_picture(self):
        """No filter, no encoder, no scale -- anywhere in the command.

        The picture is the evidence this whole pipeline exists to carry,
        and every one of these flags is a way to alter it.  A caption
        burned into the pixels would be `-vf subtitles=`; a second lossy
        generation would be `-c:v libx264`.  Neither may appear.
        """
        self.mux()
        argv = self.mux_argv()
        for forbidden in ("-vf", "-filter", "-filter_complex", "-af",
                          "-c:v", "-codec:v", "-vcodec", "-s ",
                          "subtitles=", "ass=", "drawtext"):
            self.assertNotIn(forbidden, argv,
                             msg="'%s' must never appear in the mux"
                                 % forbidden)

    def test_the_staging_file_is_the_last_argument(self):
        """So the output is positional and unmistakable."""
        self.mux()
        argv = self.mux_argv()
        last = argv.rsplit(" ", 1)[-1]
        self.assertTrue(os.path.basename(last).startswith("."),
                        msg="the mux must write a staging file: %s"
                            % last)


class TestTheConfinementGate(MuxFixture):
    """The three canonical artifacts, and nothing else, ever."""

    def test_the_defaults_are_the_canonical_artifacts(self):
        payload, _ = self.mux()
        self.assertEqual(payload["INPUT_MOVIE"],
                         "playthrough/cata-play.mp4")
        self.assertEqual(payload["INPUT_SRT"],
                         "playthrough/transcript.srt")
        self.assertEqual(payload["OUTPUT_FILE"],
                         "playthrough/cata-play-cc.mp4")

    def test_another_spelling_of_the_same_files_is_accepted(self):
        """A path is CONFIRMED, so ".." and "." are fine."""
        payload, _ = self.mux(args=(
            "./playthrough/tooling/../cata-play.mp4",
            "playthrough/build/../transcript.srt",
            os.path.join(self.checkout,
                         "playthrough/./cata-play-cc.mp4")))
        self.assertEqual(payload["OUTPUT_FILE"],
                         "playthrough/cata-play-cc.mp4")

    def test_the_canonical_spelling_is_what_gets_reported(self):
        """One code path below the gate, whatever was typed."""
        payload, _ = self.mux(args=(
            "./playthrough/tooling/../cata-play.mp4",
            "playthrough/build/../transcript.srt",
            "playthrough/cata-play-cc.mp4"))
        self.assertEqual(payload["INPUT_MOVIE"],
                         "playthrough/cata-play.mp4")
        self.assertEqual(payload["INPUT_SRT"],
                         "playthrough/transcript.srt")

    def test_an_output_outside_the_checkout_is_refused(self):
        outside = os.path.join(self.root, "elsewhere.mp4")
        message = self.refuse(EX_USAGE, args=(
            self.movie, self.srt, outside))
        self.assertIn("cata-play-cc.mp4", message)
        self.assertFalse(os.path.exists(outside))

    def test_an_output_over_the_base_render_is_refused(self):
        """The strongest case: it is the evidence everything else
        compares against, and the equal-paths check alone would not
        catch a DIFFERENT artifact being named."""
        before = os.path.getsize(self.movie)
        self.refuse(EX_USAGE, args=(self.movie, self.srt, self.movie))
        self.assertEqual(before, os.path.getsize(self.movie))

    def test_an_output_over_the_evidence_is_refused(self):
        for name in ("manifest.jsonl", "timeline.json",
                     "transcript.md", "dossier.md"):
            victim = os.path.join(self.dir, name)
            self.write(victim, "the session's own record\n")
            self.refuse(EX_USAGE,
                        args=(self.movie, self.srt, victim))
            with open(victim, encoding="utf-8") as handle:
                self.assertEqual("the session's own record\n",
                                 handle.read())

    def test_an_output_inside_the_userdir_is_refused(self):
        victim = os.path.join(self.dir, "userdir", "save", "x.mp4")
        self.refuse(EX_USAGE, args=(self.movie, self.srt, victim))
        self.assertFalse(os.path.exists(victim))

    def test_a_traversal_to_a_different_file_is_refused(self):
        """The resolved path is what is compared, so ".." cannot be
        used to reach something else."""
        self.refuse(EX_USAGE, args=(
            self.movie, self.srt,
            "playthrough/build/../userdir/x.mp4"))

    def test_the_input_film_may_not_be_another_artifact(self):
        victim = self.write(os.path.join(self.dir, "manifest.jsonl"),
                            "not a film\n")
        self.refuse(EX_USAGE, args=(victim, self.srt, self.output))

    def test_the_cue_file_may_not_be_another_artifact(self):
        victim = self.write(os.path.join(self.dir, "transcript.md"),
                            "not cues\n")
        self.refuse(EX_USAGE, args=(self.movie, victim, self.output))

    def test_a_symlinked_output_is_refused_not_followed(self):
        """Publication is a rename, which REPLACES a link rather than
        following it -- and resolving both sides would make a link that
        points at the canonical path compare equal."""
        target = os.path.join(self.root, "pointed-at.mp4")
        os.symlink(target, self.output)
        self.refuse(EX_USAGE)
        self.assertFalse(os.path.exists(target))
        self.assertTrue(os.path.islink(self.output))

    def test_a_symlinked_input_is_refused_not_followed(self):
        os.unlink(self.movie)
        real = self.write(os.path.join(self.root, "real.mp4"),
                          "x" * 32768)
        os.symlink(real, self.movie)
        self.refuse(EX_USAGE)

    def test_a_path_beginning_with_a_dash_is_refused(self):
        """ffmpeg has no end-of-options marker, so this would be read
        as a flag."""
        self.refuse(EX_USAGE, args=(
            "--", "-cata.mp4", self.srt, self.output))

    def test_a_fourth_positional_is_refused(self):
        self.refuse(EX_USAGE, args=(
            self.movie, self.srt, self.output, "extra.mp4"))


class TestTheStreamCensus(MuxFixture):
    """Nothing may travel into the container beside the two streams.

    The census is taken at three points and each is a different
    statement.  On the INPUT it says the film is the one this pipeline
    produced -- render_movie.py encodes one silent picture stream from
    still images, so anything else was written by something else.  On
    the STAGED container it says the mapping held.  On the PUBLISHED
    container it says the rename did not change what the file carries.
    """

    def test_an_inherited_audio_stream_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_A_STREAMS="1")
        self.assertIn("audio", message)

    def test_an_inherited_data_stream_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_D_STREAMS="1")
        self.assertIn("data", message)

    def test_an_inherited_attachment_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_T_STREAMS="2")
        self.assertIn("attachment", message)

    def test_an_input_film_carrying_audio_is_refused(self):
        """`-c copy` with an explicit mapping would publish this
        happily, and the picture's stream hash would match, because the
        hash proves the picture survived the mux and says nothing about
        where the picture came from."""
        message = self.refuse(EX_INPUT, STUB_IN_A_STREAMS="1")
        self.assertIn("audio", message)
        self.assertIn("cata-play.mp4", message)
        self.assertIn("render_movie.py", message)

    def test_an_input_film_carrying_a_data_stream_is_refused(self):
        message = self.refuse(EX_INPUT, STUB_IN_D_STREAMS="1")
        self.assertIn("data", message)

    def test_an_input_film_carrying_an_attachment_is_refused(self):
        message = self.refuse(EX_INPUT, STUB_IN_T_STREAMS="3")
        self.assertIn("attachment", message)

    def test_the_input_census_happens_before_the_mux(self):
        """A refusal about the input must cost nothing: no ffmpeg run,
        and no staging file left behind for nobody to look at."""
        self.refuse(EX_INPUT, STUB_IN_A_STREAMS="1")
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual([], self.staging_files())
        self.assertEqual([], self.stub_calls("ffmpeg"))

    def test_the_whole_census_happens_before_the_rename(self):
        """THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE.

        The audio/data/attachment census used to run TWICE -- once on the
        staged container and once on the published one -- and the second
        pass could exit non-zero with the canonical captioned MP4 already
        replaced.  So a fault it found left the unverified container in the
        working tree as the film while the previous one, which had passed
        every check, was already gone.

        There is exactly one census now, and it is on the staging file, so
        a container that fails it never reaches the output path at all.
        """
        for name, variable in (("audio", "STUB_A_STREAMS"),
                               ("data", "STUB_D_STREAMS"),
                               ("attachment", "STUB_T_STREAMS")):
            with self.subTest(stream=name):
                self.write(self.output, "the previous film\n")
                message = self.refuse(EX_VERIFY, **{variable: "1"})
                self.assertIn(name, message)
                with open(self.output, encoding="utf-8") as handle:
                    self.assertEqual(
                        "the previous film\n", handle.read(),
                        msg="and the previous film is untouched")

    def test_the_published_file_is_never_re_interrogated(self):
        """One check after the rename, and it asks about BYTES only.

        Re-asking what a container holds after publishing it is what made
        the previous ordering unsafe: every such question can fail, and by
        then the previous film is gone.  So the only thing measured after
        the rename is whether the filesystem moved the verified bytes
        faithfully -- and even that is now recoverable.
        """
        self.mux()
        published = os.path.realpath(self.output)
        after = [argv for argv in self.stub_calls("ffprobe")
                 if any(os.path.realpath(word) == published
                        for word in argv.split())]
        self.assertEqual(
            after, [],
            msg=("ffprobe was asked about the published container: %r"
                 % after))

    def test_the_summary_states_the_audio_count(self):
        """0, measured -- not inferred from the absence of a
        complaint."""
        payload, _ = self.mux()
        self.assertEqual(payload["AUDIO_STREAMS"], "0")

    def test_a_missing_picture_is_refused(self):
        self.refuse(EX_VERIFY, STUB_V_STREAMS="0")

    def test_a_second_video_stream_is_refused(self):
        self.refuse(EX_VERIFY, STUB_V_STREAMS="2")

    def test_a_wrong_caption_codec_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_S_CODEC="subrip")
        self.assertIn("mov_text", message)

    def test_a_missing_language_tag_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_S_LANGUAGE="")
        self.assertIn("eng", message)

    def test_a_changed_geometry_is_refused(self):
        self.refuse(EX_VERIFY, STUB_WIDTH="1280")

    def test_a_changed_codec_is_refused(self):
        self.refuse(EX_VERIFY, STUB_V_CODEC="hevc")


class TestTheMetadataConfinement(MuxFixture):
    """Only the structural tags the muxer writes for itself."""

    def test_the_four_structural_tags_are_allowed(self):
        self.mux()

    def test_an_inherited_creation_time_is_refused(self):
        """A fact about the operator's clock, and it would make the
        artifact non-reproducible."""
        message = self.refuse(
            EX_VERIFY,
            STUB_FORMAT_TAGS=" ".join(
                STRUCTURAL_TAGS + ("creation_time=2026-08-04T00:00:00",
                                   )))
        self.assertIn("creation_time", message)

    def test_an_inherited_comment_is_refused(self):
        message = self.refuse(
            EX_VERIFY,
            STUB_FORMAT_TAGS=" ".join(
                STRUCTURAL_TAGS + ("comment=whatever",)))
        self.assertIn("comment", message)

    def test_a_declared_chapter_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_CHAPTERS="1")
        self.assertIn("chapter", message)

    def test_several_chapters_are_refused(self):
        self.refuse(EX_VERIFY, STUB_CHAPTERS="3")


class TestTheCaptionTiming(MuxFixture):
    """The cues must fit inside the picture, and be MEASURABLE."""

    def test_captions_ending_inside_the_picture_are_accepted(self):
        payload, _ = self.mux()
        self.assertEqual(payload["SUBTITLE_DURATION"],
                         SUBTITLE_DURATION)
        self.assertEqual(payload["VIDEO_DURATION"], VIDEO_DURATION)

    def test_captions_outlasting_the_picture_are_refused(self):
        """This used to WARN and publish anyway.  A committed container
        whose last cues point past the end of the picture is a broken
        artifact whichever stage broke it."""
        message = self.refuse(EX_VERIFY, STUB_S_DURATION="400.000000")
        self.assertIn("OUTLAST", message)
        self.assertIn("400.000000", message)
        self.assertIn(VIDEO_DURATION, message)

    def test_the_refusal_names_the_upstream_stages(self):
        message = self.refuse(EX_VERIFY, STUB_S_DURATION="400.000000")
        self.assertIn("render_movie.py", message)
        self.assertIn("make_srt.py", message)
        self.assertIn("timeline.json", message)

    def test_a_caption_duration_within_the_epsilon_is_accepted(self):
        """Equal durations, and a hair over, are not an overrun."""
        self.mux(STUB_S_DURATION=VIDEO_DURATION)

    def test_an_unmeasurable_caption_duration_is_refused(self):
        """A SKIPPED check that leaves no trace is indistinguishable
        from a check that passed, so it is a refusal instead."""
        message = self.refuse(EX_VERIFY, STUB_S_DURATION="N/A")
        self.assertIn("could not measure", message)

    def test_an_empty_caption_duration_is_refused(self):
        self.refuse(EX_VERIFY, STUB_S_DURATION="")

    def test_an_unmeasurable_video_duration_is_refused(self):
        """The video duration reaches the overrun comparison too, so it
        has to be measurable for the same reason -- and the picture-copy
        proof falls back to the stream hash, which is why this run gets
        as far as the timing check at all."""
        message = self.refuse(EX_VERIFY, STUB_V_DURATION="N/A",
                              STUB_IN_V_DURATION="N/A")
        self.assertIn("could not measure", message)

    def test_captions_ending_short_of_the_picture_are_refused(self):
        """THE DEFECT THIS TEST EXISTS FOR IS A REAL ONE.

        The comparison was one-sided: only a caption track running PAST
        the end of the picture was refused.  A track that ends EARLY was
        published, and early is the direction a STALE cue file fails in --
        an SRT left over from a shorter session muxes cleanly into a
        longer film, the cue-count check passes because it is checked
        against that same stale file, and the artifact ships with captions
        that stop partway through and that describe another session's
        keystrokes throughout.
        """
        message = self.refuse(EX_VERIFY, STUB_S_DURATION="120.000000")
        self.assertIn("END SHORT", message)
        self.assertIn("120.000000", message)
        self.assertIn(VIDEO_DURATION, message)
        self.assertIn("STALE", message)
        self.assertIn("make_srt.py", message)

    def test_the_bound_is_absolute_and_sized_for_quantisation(self):
        """Both directions, one number, and it is not arbitrary.

        The subtitle stream's duration is the last cue's end, which
        make_srt.py writes equal to the timeline total exactly; the video
        stream's is the container's, which render_movie.py measures as the
        total plus 0.02 to 0.06 s of concat-demuxer quantisation.  The
        smallest staleness worth catching is a session one keystroke
        shorter, which differs by at least the 0.25 s floor -- so the bound
        sits between 0.06 and 0.19, and 0.12 is what render_movie.py uses
        for the same comparison for the same reason.
        """
        # Inside the bound in each direction: accepted.
        self.mux(STUB_S_DURATION="337.450000")
        self.mux(STUB_S_DURATION="337.670000")
        # Outside it in each direction: refused.
        self.refuse(EX_VERIFY, STUB_S_DURATION="337.400000")
        self.refuse(EX_VERIFY, STUB_S_DURATION="337.700000")

    def test_a_stale_cue_file_from_one_shorter_session_is_caught(self):
        """The realistic case, not a contrived one.

        One keystroke fewer is the smallest honest difference between two
        sessions, and the timeline's floor makes that at least 0.25 s.
        """
        short = "%.6f" % (float(VIDEO_DURATION) - 0.25)
        message = self.refuse(EX_VERIFY, STUB_S_DURATION=short)
        self.assertIn("END SHORT", message)


class TestTheProvenanceGate(MuxFixture):
    """Do the film and the caption track describe the same session?

    THE DEFECT THIS CLASS EXISTS FOR.  Every other check in this stage
    compares the output against the INPUTS, and that is the wrong axis for
    the failure that matters most: a film and a caption track can agree in
    length, in cue count, in codec and in geometry while describing two
    different sessions.  A re-record of the same scripted opening, or a
    re-render of one session beside a transcript from another, produces
    exactly that.  Only the digest of the document each was computed from
    settles it, and both producers publish precisely that.
    """

    def test_a_matching_pair_is_muxed(self):
        payload, err = self.mux()
        self.assertIn(self.timeline_sha, err)
        self.assertIn("both attributed to", err)
        self.assertTrue(payload["OUTPUT_FILE"].endswith("cata-play-cc.mp4"))

    def test_two_different_timelines_are_refused_before_the_mux(self):
        self.publish_manifests(srt_timeline="b" * 64)
        message = self.refuse(EX_INPUT)
        self.assertIn("DIFFERENT", message)
        self.assertIn(self.timeline_sha, message)
        self.assertIn("b" * 64, message)
        self.assertEqual(
            [], self.stub_calls("ffmpeg"),
            msg="a refusal here costs nothing: nothing was muxed")
        self.assertFalse(os.path.exists(self.output))

    def test_a_replaced_film_no_longer_matches_its_manifest(self):
        """A manifest that agrees with another manifest says nothing if
        the bytes beside it have since been replaced."""
        self.write(self.movie, "y" * 32768)
        message = self.refuse(EX_INPUT)
        self.assertIn("has been replaced", message)
        self.assertIn("render_movie.py", message)
        self.assertEqual([], self.stub_calls("ffmpeg"))

    def test_a_replaced_cue_file_no_longer_matches_its_manifest(self):
        self.write(self.srt, SRT_BODY + "\n")
        message = self.refuse(EX_INPUT)
        self.assertIn("has been replaced", message)
        self.assertIn("make_srt.py", message)

    def test_an_absent_manifest_is_a_refusal_not_a_skip(self):
        """Treating it as "nothing to check" would switch the gate off
        for exactly the older render it exists to catch."""
        for path, producer in ((self.movie_manifest, "render_movie.py"),
                               (self.transcript_manifest,
                                "make_srt.py")):
            with self.subTest(manifest=os.path.basename(path)):
                self.publish_manifests()
                os.unlink(path)
                message = self.refuse(EX_INPUT)
                self.assertIn("no generation manifest", message)
                self.assertIn("REFUSAL", message)
                self.assertIn(producer, message)

    def test_an_empty_manifest_is_a_refusal(self):
        self.write(self.movie_manifest, "")
        self.refuse(EX_INPUT)

    def test_a_manifest_that_will_not_parse_is_a_refusal(self):
        self.write(self.movie_manifest, "{not json\n")
        message = self.refuse(EX_INPUT)
        self.assertIn("timeline digest", message)

    def test_a_manifest_naming_no_digest_is_a_refusal(self):
        self.write(self.movie_manifest,
                   json.dumps({"version": 1, "stage": "movie"}) + "\n")
        message = self.refuse(EX_INPUT)
        self.assertIn("names no timeline digest", message)

    def test_a_manifest_naming_no_digest_for_the_cue_file_is_refused(self):
        self.write(self.transcript_manifest, json.dumps({
            "version": 1, "stage": "transcript",
            "timeline": {"path": "playthrough/timeline.json",
                         "sha256": self.timeline_sha},
            "outputs": [{"path": "playthrough/transcript.md",
                         "sha256": "d" * 64, "bytes": 2}],
        }, indent=2, sort_keys=True) + "\n")
        message = self.refuse(EX_INPUT)
        self.assertIn("transcript.srt", message)

    def test_a_digest_that_is_not_a_digest_is_a_refusal(self):
        """Fail closed: "unreadable" must not be mistaken for
        "matches"."""
        for value in ("", "not-a-digest", "A" * 64, "a" * 63):
            with self.subTest(sha=value):
                self.publish_manifests(movie_timeline=value)
                self.refuse(EX_INPUT)


class TestThePublicationIsRecoverable(MuxFixture):
    """The canonical film is replaced once, and only by verified bytes.

    THE DEFECT THIS CLASS EXISTS FOR IS A REAL ONE.  The byte-size
    comparison, both mandated probe readouts and the audio/data/attachment
    census all used to run AFTER the rename, against the published file,
    and each could exit non-zero.  So the committed captioned MP4 was
    replaced first and interrogated second, and a failure left the
    unverified container in the working tree as the film while the previous
    one -- which had passed every check -- was already gone.  The stated
    policy, "the file is left in place for inspection", meant in practice
    that a broken artifact became the published one.
    """

    def test_a_clean_run_leaves_no_retained_or_quarantined_file(self):
        self.write(self.output, "the previous film\n")
        self.mux()
        self.assertFalse(os.path.exists(self.retained))
        self.assertFalse(os.path.exists(self.quarantine))
        self.assertEqual([], self.staging_files())

    def test_a_corrupted_rename_restores_the_previous_film(self):
        self.write(self.output, "the previous film\n")
        self.corrupt_the_rename()
        message = self.refuse_after_publish(EX_VERIFY)
        self.assertIn("carries", message)
        self.assertIn("restored", message)
        with open(self.output, encoding="utf-8") as handle:
            self.assertEqual("the previous film\n", handle.read(),
                             msg="the film that passed is back in place")
        with open(self.quarantine, encoding="utf-8") as handle:
            self.assertEqual("corrupted by the fixture\n", handle.read(),
                             msg="and the one that failed is quarantined")

    def test_a_corrupted_first_publication_has_nothing_to_restore(self):
        """There is no previous film, so the message says so rather than
        claiming a restore that did not happen."""
        self.corrupt_the_rename()
        message = self.refuse_after_publish(EX_VERIFY)
        self.assertIn("no previous film to restore", message)
        self.assertFalse(os.path.exists(self.output))

    def test_a_retained_copy_left_by_a_killed_run_is_swept(self):
        self.write(self.retained, "a killed run left this\n")
        self.mux()
        self.assertFalse(os.path.exists(self.retained))

    def test_a_quarantined_file_is_reported_and_left_alone(self):
        """It is the only record of a filesystem fault, so it is not
        deleted -- and it is inside a tree .gitignore re-includes, so the
        warning says it must not be committed."""
        self.write(self.quarantine, "an earlier fault\n")
        _, err = self.mux()
        self.assertIn("quarantined", err)
        self.assertIn("before committing", err)
        with open(self.quarantine, encoding="utf-8") as handle:
            self.assertEqual("an earlier fault\n", handle.read())

    def test_the_size_floor_is_checked_before_the_rename(self):
        self.write(self.output, "the previous film\n")
        message = self.refuse(EX_VERIFY, STUB_MUX_BYTES="16")
        self.assertIn("header, not a film", message)
        with open(self.output, encoding="utf-8") as handle:
            self.assertEqual("the previous film\n", handle.read())


class TestTheBoundedCalls(MuxFixture):
    """Every external call runs under the stage ceiling."""

    def test_every_ffmpeg_and_ffprobe_call_is_bounded(self):
        """One wedged probe used to stop the whole sequential pipeline
        with no diagnosis, after a staging file had already been made.
        """
        self.mux()
        media = len(self.stub_calls("ffmpeg")) + \
            len(self.stub_calls("ffprobe"))
        bounded = len(self.stub_calls("timeout"))
        self.assertGreater(media, 10,
                           msg="the run made suspiciously few calls")
        self.assertEqual(
            media, bounded,
            msg=("%d media calls but %d were bounded; every ffmpeg and "
                 "ffprobe invocation must go through the runner"
                 % (media, bounded)))

    def test_the_ceiling_is_the_configured_one(self):
        self.mux(PLAYTHROUGH_CAPTION_TIMEOUT="77")
        for argv in self.stub_calls("timeout"):
            self.assertTrue(
                argv.startswith("77 "),
                msg="a call was bounded by something else: %s" % argv)

    def test_a_nonsense_ceiling_is_refused(self):
        status, _, err = self.run_mux(
            PLAYTHROUGH_CAPTION_TIMEOUT="not-a-number")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("PLAYTHROUGH_CAPTION_TIMEOUT", err)


class TestThePictureIsProvenCopied(MuxFixture):
    """SHA-256, with the algorithm recorded beside the digest."""

    def test_the_hash_is_taken_with_sha256(self):
        self.mux()
        hashes = [argv for argv in self.stub_calls("ffmpeg")
                  if "streamhash" in argv]
        self.assertEqual(2, len(hashes),
                         msg="both files must be hashed: %s" % hashes)
        for argv in hashes:
            self.assertIn("-hash sha256", argv)
            self.assertNotIn("-hash md5", argv)

    def test_the_proof_records_the_algorithm(self):
        payload, err = self.mux()
        self.assertEqual(payload["VIDEO_COPY_PROOF"],
                         "stream-hash-sha256")
        self.assertIn("sha256:%s" % DIGEST, err)

    def test_a_changed_picture_is_refused(self):
        message = self.refuse(EX_VERIFY, STUB_HASH_OUT="0" * 64)
        self.assertIn("THE PICTURE CHANGED", message)

    def test_an_unreadable_hash_line_is_refused(self):
        """An unrecognised shape is reported as empty so the caller
        refuses, rather than comparing two blanks and calling them
        equal."""
        self.refuse(EX_VERIFY, STUB_HASH_SHAPE="empty")

    def test_without_streamhash_the_weaker_proofs_stand(self):
        payload, err = self.mux(STUB_MUXERS="0")
        self.assertEqual(payload["VIDEO_COPY_PROOF"],
                         "duration+frames")
        self.assertIn("streamhash", err)

    def test_with_no_proof_at_all_nothing_is_published(self):
        self.refuse(EX_VERIFY, STUB_MUXERS="0", STUB_V_DURATION="N/A",
                    STUB_IN_V_DURATION="N/A", STUB_NB_FRAMES="N/A",
                    STUB_IN_NB_FRAMES="N/A")

    def test_a_changed_frame_count_is_refused(self):
        self.refuse(EX_VERIFY, STUB_MUXERS="0",
                    STUB_NB_FRAMES="692")


class TestTheInputs(MuxFixture):
    """Both must be there, and the cue file must really be SubRip."""

    def test_a_missing_film_is_refused(self):
        os.unlink(self.movie)
        message = self.refuse(EX_INPUT)
        self.assertIn("render_movie.py", message)

    def test_a_missing_cue_file_is_refused(self):
        os.unlink(self.srt)
        message = self.refuse(EX_INPUT)
        self.assertIn("make_srt.py", message)

    def test_an_empty_cue_file_is_refused(self):
        """It would mux into a container that looks finished and
        carries nothing."""
        self.write(self.srt, "")
        self.refuse(EX_INPUT)

    def test_a_byte_order_mark_is_refused(self):
        """make_srt.py writes UTF-8 WITHOUT one, and a BOM stops the
        first cue's number from being read."""
        self.write(self.srt, "\ufeff" + SRT_BODY)
        self.refuse(EX_INPUT)

    def test_a_cue_file_with_no_timing_line_is_refused(self):
        self.write(self.srt, "1\njust prose, no timing\n")
        self.refuse(EX_INPUT)

    def test_a_directory_where_the_film_should_be_is_refused(self):
        os.unlink(self.movie)
        os.makedirs(self.movie)
        self.refuse(EX_INPUT)


class TestTheMux(MuxFixture):
    """What happens when ffmpeg itself fails."""

    def test_a_failing_mux_publishes_nothing(self):
        message = self.refuse(EX_MUX, STUB_MUX_RC="1")
        self.assertIn("Nothing was published", message)

    def test_a_mux_that_writes_nothing_is_refused(self):
        self.refuse(EX_MUX, STUB_MUX_BYTES="0")

    def test_a_container_below_the_size_floor_is_refused(self):
        """A header is not a film."""
        message = self.refuse(EX_VERIFY, STUB_MUX_BYTES="512")
        self.assertIn("not a film", message)

    def test_a_failing_probe_of_the_input_is_refused(self):
        """The first probe of the run reads the input film's stream
        census, so a probe that cannot answer at all is refused there --
        as an INPUT fault, because a file this stage was handed that
        ffprobe cannot read as a container is not a verification
        failure of anything this stage produced."""
        message = self.refuse(EX_INPUT, STUB_PROBE_RC="1")
        self.assertIn("cata-play.mp4", message)

    def test_a_failing_probe_of_the_muxed_container_is_refused(self):
        """And when the input reads cleanly but the container this
        stage just wrote cannot be measured, nothing is published."""
        self.refuse(EX_VERIFY, STUB_STAGED_PROBE_RC="1")

    def test_a_lost_cue_is_refused(self):
        """Every cue is one captured frame's commentary, so a caption
        track with a different number of them is not this transcript."""
        message = self.refuse(EX_VERIFY,
                              STUB_ROUND_TRIP_CUES=str(CUES - 1))
        self.assertIn(str(CUES), message)

    def test_a_gained_cue_is_refused(self):
        self.refuse(EX_VERIFY, STUB_ROUND_TRIP_CUES=str(CUES + 1))


class TestTheTrustGate(MuxFixture):
    """Finding 5: the captioned film is the pipeline's final artifact.

    It is committed, so it is evidence in exactly the sense a kept frame
    is -- and the end-of-life platform waiver used not to force the
    diagnostic trust state, which left "capture and mux ... eligible as
    trusted production evidence despite known-unpatched parser/X risks".
    The waiver is a registered bypass now and the mux refuses under it,
    before ffmpeg is invoked.
    """

    def test_a_declared_bypass_refuses_the_mux(self):
        for name in ("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                     "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X",
                     "PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW"):
            with self.subTest(bypass=name):
                status, _, err = self.run_mux(**{name: "a reason"})
                self.assertEqual(status, EX_PREREQ)
                self.assertIn("refusing the caption mux", err)
                self.assertIn("trust state is diagnostic", err)
                self.assertIn(name, err)
                self.assertFalse(
                    os.path.isfile(self.output),
                    msg="nothing is produced under a relaxed check")

    def test_the_refusal_names_what_the_bypass_endangers(self):
        _, _, err = self.run_mux(
            PLAYTHROUGH_ALLOW_EOL_PLATFORM="an out-of-support host")
        self.assertIn("no further security fixes", err)
        self.assertIn("encode every frame", err)

    def test_the_gate_precedes_the_ffmpeg_invocation(self):
        """Refused before the tool runs, not after it has written."""
        self.run_mux(PLAYTHROUGH_ALLOW_EOL_PLATFORM="a reason")
        self.assertEqual(
            self.stub_calls("ffmpeg"), [],
            msg="ffmpeg is never reached")

    def test_an_untrusted_run_is_still_diagnosable(self):
        """The refusal explains what to do, so it is not a dead end."""
        _, _, err = self.run_mux(
            PLAYTHROUGH_ALLOW_EOL_PLATFORM="a reason")
        self.assertIn("unset the variable(s) above", err)

    def test_the_ordinary_run_is_unaffected(self):
        status, _, _ = self.run_mux()
        self.assertEqual(status, 0)
        self.assertTrue(os.path.isfile(self.output))


class TestTheHelpAndUsage(MuxFixture):
    """The one place this file writes prose to stdout."""

    def test_help_exits_zero_and_publishes_nothing(self):
        status, out, _ = self.run_mux(args=("--help",))
        self.assertEqual(status, EX_OK)
        self.assertIn("mov_text", out)
        self.assertIsNone(self.published_bytes())

    def test_the_help_states_the_three_files_are_the_only_ones(self):
        _, out, _ = self.run_mux(args=("--help",))
        self.assertIn("cata-play.mp4", out)
        self.assertIn("transcript.srt", out)
        self.assertIn("cata-play-cc.mp4", out)
        self.assertIn("CONFIRM", out)

    def test_an_unknown_option_is_refused_not_ignored(self):
        status, _, err = self.run_mux(args=("--burn-in",))
        self.assertEqual(status, EX_USAGE)
        self.assertIn("--burn-in", err)


class TestTheSuiteTouchesNothingReal(MuxFixture):
    """The sandbox is where everything happened."""

    def test_the_committed_artifacts_were_never_the_subject(self):
        payload, _ = self.mux()
        self.assertTrue(os.path.isfile(self.output))
        for argv in self.stub_calls():
            self.assertNotIn(TOOLING, argv,
                             msg=("a call reached the real tooling "
                                  "directory: %s" % argv))

    def test_the_output_landed_in_the_sandbox(self):
        self.mux()
        self.assertTrue(
            os.path.realpath(self.output).startswith(
                os.path.realpath(self.root)),
            msg=("env.sh resolves every path from its own location, "
                 "which is what makes a sandbox test possible"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
