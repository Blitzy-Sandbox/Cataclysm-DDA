#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/capture.sh.

capture.sh carries the pipeline's single structural promise:

    exit 0  <=>  exactly one new frame exists, and this invocation's
                 whole output contract was delivered

session.py reads a zero status as licence to append exactly one
manifest row, and verify_artifacts.sh later asserts that the frame count
equals the manifest line count.  So every way of exiting non-zero has to
leave playthrough/frames/ EXACTLY as it was found -- and every way of
exiting zero has to leave precisely one new PNG behind.  That is what
this suite tests, one failure mode at a time.

    python3 playthrough/tooling/test_capture.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

HOW A CAPTURE SCRIPT IS TESTED WITHOUT A GAME OR AN X SERVER
Every test runs the REAL capture.sh inside a temporary SANDBOX CHECKOUT
-- a directory carrying data/, src/path_info.cpp and copies of env.sh
and capture.sh, so env.sh's BASH_SOURCE resolution points the whole
artifact layout at the sandbox and nothing can touch the committed
frames.  That sandbox lives under a PRIVATE base rather than under /tmp
(see _sandbox_base): capture.sh refuses a production capture while any
trust bypass is set, so the harness has to SATISFY the ownership and
access-control checks rather than declare them away -- otherwise every
test here would exercise the diagnostic path and assert nothing about
the enforced one.  The shell is started with `env -i` and a PATH holding ONLY a
purpose-built tool directory: symlinks to the coreutils the script
genuinely needs, plus recording stubs for import, scrot, convert,
identify, tesseract, xdpyinfo and sleep.  Each stub appends its argv to
a log, which is how "exactly one root-window grab" and "the settle was
honoured" become assertions rather than hopes.  PLAYTHROUGH_PYTHON
points at a dispatching stub that answers ocr_clock.py's --preflight and
--field calls with a status this suite chooses, and hands `-c` through to
the real interpreter so env.sh's own interpreter-version probe answers
truthfully.

WHAT IS ASSERTED
* ONE FRAME PER KEYSTROKE -- exit 0 leaves exactly one PNG; every one of
  the eight documented failure codes leaves the directory untouched, and
  a superseded frame is restored byte-for-byte.
* THE INDEX IS NEVER GUESSED -- a leading zero is refused because bash
  printf reads 010 as octal 8 and would file frame 10 over frame 8, in
  silence.
* THE BLANK GATE -- mean > 0 AND stddev > 0, with both values proved
  numeric first, because awk compares a non-numeric string against 0 as
  strings and "nan" would pass.
* THE THREE OCR STATUSES -- 0 read, 1 unreadable, 2 FAULT, kept apart,
  with a fault fatal by default because it would otherwise report every
  frame of the session as honestly unreadable.
* NOTHING IS INVENTED -- an impossible or malformed reading from the
  delegate is refused rather than emitted, and no reading is carried
  between invocations.
* THE COMMIT POINT IS LAST -- the payload is written, the human-readable
  log line is taken, and only THEN is the frame kept, so nothing that
  can fail runs after the decision to keep it.
* THE WRITE SURFACE IS THE FRAME AND NOTHING ELSE -- the telemetry row
  is REPORTED on the payload for session.py to persist beside the
  manifest row it already owns; this script appends nothing, and the
  destination it names cannot be redirected from the environment.
* A RELAXED CHECK CANNOT BECOME EVIDENCE -- every trust bypass in
  env.sh's registry refuses a production capture outright, before the
  display is touched, and the diagnostic mode that tolerates one
  withdraws its frame out of the working tree.

Standard library only.  Nothing outside the temporary directory is
written: the reject directory is redirected into it, and the only path
inside the sandbox checkout a capture writes is its own frame.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything
# written there.
sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
REPO_ROOT = os.path.dirname(PLAYTHROUGH)


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

    THE SANDBOX HAS TO BE TRUSTWORTHY, because capture.sh now refuses a
    production capture while any of env.sh's trust bypasses is set --
    and that refusal is the point: a frame taken through a tool another
    account can replace is not evidence.  A suite that declared those
    bypasses to make itself work would be testing the relaxed path and
    asserting nothing about the enforced one.

    So the sandbox goes somewhere private.  /tmp cannot be it: this host
    has it at mode 2777, world-writable with no sticky bit, so every
    ancestor walk fails there no matter what the sandbox itself looks
    like.  $HOME serves on an ordinary host and /run on a root one, and
    $PLAYTHROUGH_TEST_TMPDIR overrides both for anywhere else.  None
    available means the suite skips with that named as the remedy,
    rather than quietly testing something weaker.
    """
    candidates = []
    nominated = os.environ.get("PLAYTHROUGH_TEST_TMPDIR")
    if nominated:
        candidates.append(nominated)
    home = os.environ.get("HOME")
    if home:
        candidates.append(
            os.path.join(home, ".cache", "playthrough-tooling-tests"))
    if os.geteuid() == 0:
        candidates.append("/run/playthrough-tooling-tests")
    for candidate in candidates:
        try:
            os.makedirs(candidate, mode=0o700, exist_ok=True)
        except OSError:
            continue
        if _is_private(candidate):
            return candidate
    return None


SANDBOX_BASE = _sandbox_base()
NO_SANDBOX_BASE = (
    "no private directory is available for the sandbox: set "
    "PLAYTHROUGH_TEST_TMPDIR to one that only root or this user can "
    "write, with no group- or world-writable directory above it")

# The documented exit codes, named as capture.sh names them.
EX_OK = 0
EX_USAGE = 1
EX_LAYOUT = 2
EX_CAPTURE = 3
EX_BLANK = 4
EX_GEOMETRY = 5
EX_CLOCK_FAULT = 6
EX_EXISTS = 7
EX_PREREQ = 8
# A DIAGNOSTIC capture completed and was WITHDRAWN out of the working
# tree.  Non-zero by design: no frame was added to playthrough/frames/,
# so it must not read as success.  It is the status every relaxed
# safeguard below arrives at, because the two are the same decision --
# a frame captured under a relaxed safeguard is not a frame for the
# record, and capture.sh will not let it become one.
EX_DIAGNOSTIC = 9

# The measured calibration values env.sh and capture.sh both cite.
REAL_LUMA = "0.270018 0.198145"
DUMMY_LUMA = "0 0"
FLAT_LUMA = "0.5 0"

CLOCK = "13:45:27"
IMPOSSIBLE_CLOCK = "88:15:32"
PHRASE = "Around dawn"
DATE_LINE = "Thursday, Mar 8"
# The crop the geometry stub answers with.  It is the rectangle a FRESH
# userdir really produces -- the engine's constructor default layout is
# legacy_labels_sidebar at 44 cells [src/panels.cpp:412-418], not
# custom_sidebar's 36 -- so the harness's example is the one a first
# session computes.
CROP = "352x1072+1568+4"
# The rectangle capture.sh quotes in its geometry diagnostics as an
# EXAMPLE of the form PLAYTHROUGH_CAPTURE_RECT takes.  It is not a
# fallback and nothing substitutes it; it belongs to a 36-cell
# custom_sidebar, while the engine's own default layout is the 44-cell
# legacy_labels_sidebar below.  Both are named in the diagnostics, with
# their layouts, so that neither can quietly become "the documented"
# one, and both are asserted below.
EXAMPLE_CROP = "288x1072+1632+4"
DEFAULT_LAYOUT_CROP = "352x1072+1568+4"

# The twenty-two keys the payload must carry, in order.  CLOCK_DATE is
# the date exactly as the delegate read it and DATE is the value this
# file stands behind, which is why both are reported: the second is
# derived from the first and a reader can see the derivation rather
# than take it on trust.  DATE_AUDIT says whether the date evidence
# reached the date audit timeline.py cross-checks its rollover guard
# against, because a frame whose evidence was lost must be treated as
# UNKNOWN and never as a day that did not turn.
# CAPTURE_MODE comes first because it decides what the rest of the
# payload describes, and DIAGNOSTIC_PATH sits beside FRAME_PATH because
# exactly one of the two is populated.  Both are emitted in EVERY mode:
# a key that sometimes disappears is a key a consumer papers over with a
# default.
PAYLOAD_KEYS = (
    "CAPTURE_MODE",
    "FRAME_INDEX", "FRAME_NAME", "FRAME_FILE", "FRAME_PATH",
    "DIAGNOSTIC_PATH",
    "FRAME_BYTES", "FRAME_FORMAT", "FRAME_GEOMETRY", "REAL_TS",
    "CAPTURE_TOOL", "LUMA_MEAN", "LUMA_STDDEV", "CLOCK_RECT",
    "CLOCK_RECT_FROM", "CLOCK_SOURCE", "CLOCK_STATUS", "CLOCK",
    "TIME_PHRASE", "CLOCK_DATE", "DATE", "DATE_STATUS", "DATE_AUDIT",
    "OBSERVATIONS",
)

# The fifteen fields the telemetry row must carry, each mapped to the
# payload key that DELIVERS it.
#
# capture.sh no longer appends that row: it reports every field and
# session.py -- which already owns the frame counter and the manifest
# row for the same frame -- persists it.  This mapping is what proves
# the evidence was not weakened by the move: if a field the row needs
# had no key to arrive on, the handoff would be lossy, and the test
# below would say so.
OBSERVATION_FIELDS = {
    "frame": "FRAME_INDEX",
    "file": "FRAME_FILE",
    "real_ts": "REAL_TS",
    "ingame_clock": "CLOCK",
    "clock_status": "CLOCK_STATUS",
    "clock_source": "CLOCK_SOURCE",
    "clock_rect": "CLOCK_RECT",
    "clock_rect_from": "CLOCK_RECT_FROM",
    "time_phrase": "TIME_PHRASE",
    "date": "DATE",
    "date_status": "DATE_STATUS",
    "frame_geometry": "FRAME_GEOMETRY",
    "luma_mean": "LUMA_MEAN",
    "luma_stddev": "LUMA_STDDEV",
    "capture_tool": "CAPTURE_TOOL",
}

# The coreutils the script really runs.  Nothing else is on PATH, so a
# tool this suite does not list is genuinely absent -- which is how the
# no-capturer case is reached on a host where ImageMagick is installed.
REAL_TOOLS = (
    "bash", "date", "awk", "grep", "mkdir", "mv", "rm", "wc", "tail",
    "head", "dirname", "basename", "cat", "env", "chmod", "cp", "ls",
    "tr", "sed", "sort", "readlink", "printf", "touch", "python3",
    # timeout bounds every capture stage and its absence is a
    # prerequisite failure; stat is how env.sh verifies that the
    # runtime directory is a mode-0700 directory this user owns; id
    # answers for the owner when $EUID is not exported; realpath and
    # flock belong to the same confinement machinery.  All five are
    # coreutils and util-linux, so the pipeline is entitled to them --
    # they are listed here because this PATH is exhaustive.
    "stat", "timeout", "id", "realpath", "flock", "cut", "sleep",
    # mktemp reserves the temporary file the frame is written to before
    # it is renamed into place, so an interrupted grab can never leave a
    # half-written PNG at a frame path.  Also coreutils.
    "mktemp",
)


class CaptureFixture(unittest.TestCase):
    """A sandbox checkout, a stubbed toolchain, and one capture run."""

    def setUp(self):
        if SANDBOX_BASE is None:
            self.skipTest(NO_SANDBOX_BASE)
        self.root = tempfile.mkdtemp(prefix="blitzy_capture_",
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
        for name in ("env.sh", "capture.sh"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        os.chmod(os.path.join(self.tooling, "capture.sh"), 0o755)
        # capture.sh only tests these for existence; the interpreter
        # stub answers for them.
        for name in ("ocr_clock.py", "sidebar_geometry.py"):
            self.write(os.path.join(self.tooling, name),
                       "# answered by the interpreter stub\n")
        self.frames = os.path.join(self.checkout, "playthrough",
                                   "frames")
        # playthrough_mkdirs owns directory creation and runs before
        # any capture does, so the sandbox starts in the state a real
        # session is in: capture.sh writes frames and refuses to
        # capture a frame whose date evidence it could not record.
        self.build = os.path.join(self.checkout, "playthrough",
                                  "build")
        os.makedirs(self.build)
        self.audit = os.path.join(self.build, "frame_dates.jsonl")
        self.reject = os.path.join(self.root, "rejected")
        # Where env.sh puts the telemetry sidecar for THIS sandbox, and
        # therefore the destination capture.sh must NAME on its payload.
        # It is deliberately never created by the fixture: capture.sh
        # reports this path and appends nothing to it, so its absence
        # after a successful capture is itself an assertion.
        self.observations = os.path.join(
            self.build, "observations.jsonl")
        self.stub_log = os.path.join(self.root, "stub.log")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        self.link_real_tools()
        self.write_stubs()
        self.python_stub = self.write_python_stub()

    # -- fixture plumbing --------------------------------------------

    def write(self, path, text, mode=None):
        """Write a file, creating its parent, and return the path.

        AN EXISTING SYMLINK IS REPLACED, NEVER WRITTEN THROUGH.  This
        fixture puts symlinks to real system tools on a private PATH and
        then overrides some of them with stubs; opening such a name for
        writing would follow the link and truncate the HOST's binary.
        Removing the link first keeps every write inside the sandbox.
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
        self.assert_inside_sandbox(path)
        return path

    def assert_inside_sandbox(self, path):
        """Refuse to have written anything outside the sandbox."""
        resolved = os.path.realpath(path)
        if not resolved.startswith(os.path.realpath(self.root)):
            raise AssertionError(
                "%s resolved to %s, outside the sandbox: a stub must "
                "never be written through a symlink to a host tool"
                % (path, resolved))

    def write_stubs(self):
        """Every external tool capture.sh calls, stubbed."""
        # The `png:` prefix is stripped exactly as ImageMagick strips
        # it: capture.sh writes `png:<path>` so that the OUTPUT FORMAT
        # is stated rather than guessed from the filename, and so that a
        # path beginning with '-' cannot be read as an option.  A stub
        # that took the argument literally would be testing a contract
        # the real tool does not have.
        self.stub("import", (
            ': "${STUB_IMPORT_RC:=0}"\n'
            'target="${!#}"\n'
            'target="${target#png:}"\n'
            'if [ "${STUB_IMPORT_WRITE:-1}" = "1" ]; then\n'
            '    printf "%s" "${STUB_PNG-\\x89PNG fake frame}"'
            ' >"${target}"\n'
            "else\n"
            # capture.sh reserves the temporary file with mktemp before
            # the grab, so "wrote nothing" has to mean the capturer
            # REMOVED it -- otherwise the zero-byte placeholder would be
            # what is found and the two faults would wear one message.
            '    rm -f -- "${target}"\n'
            "fi\n"
            'exit "${STUB_IMPORT_RC}"\n'))
        self.stub("scrot", (
            ': "${STUB_SCROT_RC:=0}"\n'
            'target="${!#}"\n'
            'target="${target#png:}"\n'
            'printf "%s" "${STUB_PNG-\\x89PNG fake frame}"'
            ' >"${target}"\n'
            'exit "${STUB_SCROT_RC}"\n'))
        self.stub("identify", (
            'printf "%s\\n" "${STUB_IDENTIFY:-PNG 1920x1080}"\n'
            'exit "${STUB_IDENTIFY_RC:-0}"\n'))
        self.stub("convert", (
            'case "$*" in\n'
            "    *info:*)\n"
            '        printf "%s\\n" "${STUB_LUMA-' + REAL_LUMA + '}"\n'
            '        exit "${STUB_CONVERT_RC:-0}"\n'
            "        ;;\n"
            "esac\n"
            'printf "%s" "fake-strip"\n'
            'exit "${STUB_CROP_RC:-0}"\n'))
        # DRAIN STDIN FIRST, as the real tesseract does.  The inline
        # chain is `convert ... png:- | tesseract stdin stdout`, so a
        # stub that exits without reading leaves convert writing into a
        # closed pipe: convert dies of SIGPIPE, pipefail propagates
        # that, and the read is reported as a FAULT instead of a
        # reading -- intermittently, depending on which side wins the
        # race.  Consuming the input makes the stub faithful and the
        # outcome deterministic.
        self.stub("tesseract", (
            'case "$1" in\n'
            "    stdin) cat >/dev/null 2>&1 || true ;;\n"
            "esac\n"
            'printf "%s\\n" "${STUB_TESSERACT:-}"\n'
            'exit "${STUB_TESSERACT_RC:-0}"\n'))
        # A COOKIELESS CLIENT IS REFUSED, as a real authenticated server
        # refuses one.  env.sh proves access control NEGATIVELY -- it
        # runs xdpyinfo with an empty authority file and requires that
        # to FAIL -- so a stub that answered every caller would report
        # this sandbox's display as open to every local account, which
        # is not what is being tested here.  STUB_XDPYINFO_OPEN=1 makes
        # it answer anyway, for the test that asserts the refusal.
        self.stub("xdpyinfo", (
            'if [ "${STUB_XDPYINFO_OPEN:-0}" != "1" ]; then\n'
            '    case "${XAUTHORITY:-}" in\n'
            '        ""|/dev/null) exit 1 ;;\n'
            "    esac\n"
            "fi\n"
            'if [ "${STUB_XDPYINFO_RC:-0}" != "0" ]; then\n'
            '    exit "${STUB_XDPYINFO_RC}"\n'
            "fi\n"
            'printf "dimensions:    %s pixels\\n"'
            ' "${STUB_DIMENSIONS:-1920x1080}"\n'
            'printf "depth of root window:    %s planes\\n"'
            ' "${STUB_DEPTH:-24}"\n'))
        # Recording the settle rather than serving it: a real sleep
        # would make every test 0.3 s slower and prove nothing extra.
        self.stub("sleep", "exit 0\n")

    def write_python_stub(self):
        """An interpreter stub that answers for ocr_clock.py.

        `-c` is handed to the real interpreter, so write_observation
        still produces genuine JSON through python's own encoder; every
        other invocation is a delegate call this suite decides the
        answer to.
        """
        real = shutil.which("python3") or sys.executable
        return self.write(
            os.path.join(self.root, "python-stub"),
            "#!/bin/bash\n"
            'printf "python\\t%s\\n" "$*"'
            ' >>"${PLAYTHROUGH_STUB_LOG}"\n'
            'case "$1" in\n'
            "    -c)\n"
            '        exec "' + real + '" "$@"\n'
            "        ;;\n"
            "esac\n"
            'case "$*" in\n'
            "    *--preflight*)\n"
            '        if [ "${STUB_PREFLIGHT_RC:-0}" != "0" ]; then\n'
            '            printf "%s\\n" "stub: a dependency is'
            ' missing" >&2\n'
            "        fi\n"
            '        exit "${STUB_PREFLIGHT_RC:-0}"\n'
            "        ;;\n"
            "    *sidebar_geometry.py*)\n"
            '        printf "%s\\n" "${STUB_GEOMETRY:-' + CROP + '}"\n'
            '        exit "${STUB_GEOMETRY_RC:-0}"\n'
            "        ;;\n"
            # ONE OCR pass answers all three readings, which is why
            # capture.sh asks with --kv rather than three --field
            # calls: three passes over the same pixels could disagree,
            # and then nothing could say what the frame actually
            # showed.  The exit status is ocr_clock.py's contract and
            # is decided by the CLOCK alone -- `readable` is "a
            # possible clock was read" -- so a phrase or a date can
            # still come back alongside a status of 1.
            "    *--kv*)\n"
            "        _audit=\"\"\n"
            "        _audit_frame=\"\"\n"
            '        while [ "$#" -gt 0 ]; do\n'
            '            case "$1" in\n'
            '                --audit) _audit="$2"; shift 2 ;;\n'
            "                --audit-frame)\n"
            '                    _audit_frame="$2"; shift 2 ;;\n'
            "                *) shift ;;\n"
            "            esac\n"
            "        done\n"
            # The delegate owns the date-evidence write, and it takes
            # it BEFORE anything reaches stdout, so the stub does the
            # same: a record that could not be appended is a fault
            # with no reading, never a reading whose evidence was lost.
            # A FAULT PRINTS NOTHING.  ocr_clock.py's contract is that
            # stdout carries the reading and nothing else, so a fault
            # is a diagnosis on stderr and an empty stdout -- never a
            # value the caller could bank beside a status that says the
            # read cannot be trusted.
            '        if [ "${STUB_CLOCK_RC:-0}" -ge 2 ]; then\n'
            '            printf "%s\\n" "stub: a fault" >&2\n'
            '            exit "${STUB_CLOCK_RC}"\n'
            "        fi\n"
            '        if [ -n "${_audit}" ]; then\n'
            "            if ! printf"
            " '{\"frame\":%s,\"clock\":\"%s\",\"date\":\"%s\"}\\n'"
            ' "${_audit_frame:-0}" "${STUB_CLOCK:-}"'
            ' "${STUB_DATE:-}" >>"${_audit}"; then\n'
            "                exit 2\n"
            "            fi\n"
            "        fi\n"
            '        printf "CLOCK=%s\\n" "${STUB_CLOCK:-}"\n'
            '        printf "TIME_PHRASE=%s\\n" "${STUB_PHRASE:-}"\n'
            '        printf "CLOCK_DATE=%s\\n" "${STUB_DATE:-}"\n'
            '        exit "${STUB_CLOCK_RC:-0}"\n'
            "        ;;\n"
            "    *--field?clock*)\n"
            '        printf "%s\\n" "${STUB_CLOCK:-}"\n'
            '        exit "${STUB_CLOCK_RC:-0}"\n'
            "        ;;\n"
            "    *--field?phrase*)\n"
            '        printf "%s\\n" "${STUB_PHRASE:-}"\n'
            '        exit "${STUB_PHRASE_RC:-1}"\n'
            "        ;;\n"
            "    *--field?date*)\n"
            '        printf "%s\\n" "${STUB_DATE:-}"\n'
            '        exit "${STUB_DATE_RC:-1}"\n'
            "        ;;\n"
            "esac\n"
            "exit 0\n",
            mode=0o755)

    # -- running it --------------------------------------------------

    def run_capture(self, index="1", args=(), stderr_to=None,
                    **environment):
        """Run capture.sh in the sandbox and report the result.

        stderr_to names a file the diagnostics are sent to instead of
        being captured, which is how a script whose stderr FAILS mid-run
        is exercised: /dev/full accepts a descriptor and refuses every
        write.
        """
        env = {
            "PATH": self.bin,
            "PLAYTHROUGH_STUB_LOG": self.stub_log,
            # THE PLATFORM GATE IS SATISFIED, NOT SWITCHED OFF.
            # playthrough_check_platform REFUSES an out-of-support or
            # untabulated release by default, and the host this suite
            # runs on may well be one -- so without a waiver every test
            # here would exercise the prerequisite refusal and assert
            # nothing about the subject.  The waiver takes a REASON,
            # which is what makes declaring it in a fixture honest: it
            # says why, in the same words a run on this host would.  It
            # is not a trust bypass, so the enforced production path is
            # unaffected, and the gate itself has its own tests in
            # test_env.py.
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM":
                "test fixture; the platform gate has its own coverage "
                "in test_env.py",
            "PLAYTHROUGH_PYTHON": self.python_stub,
            "PLAYTHROUGH_CAPTURE_REJECT_DIR": self.reject,
            # THE TELEMETRY DESTINATION IS NOT NOMINATED HERE.  There is
            # no override left to set: env.sh derives the canonical path
            # inside this sandbox and capture.sh reports that, which is
            # what a test below proves by trying to redirect it.
            "STUB_CLOCK": CLOCK,
            "STUB_CLOCK_RC": "0",
            # NO TRUST BYPASS IS DECLARED HERE, DELIBERATELY.
            #
            # capture.sh refuses a production capture while any of them
            # is set, so a fixture that declared one would only ever
            # exercise the diagnostic path and would assert nothing
            # about the enforced one.  Instead the sandbox is built to
            # PASS the real checks: it lives under a private base (see
            # _sandbox_base), so every stub under <base>/bin verifies,
            # and the xdpyinfo stub refuses a cookieless client exactly
            # as an authenticated server does.  Each refusal still has
            # its own test, which arranges the untrustworthy condition
            # on purpose rather than switching the check off.
        }
        if index is not None:
            env["FRAME_INDEX"] = str(index)
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        script = os.path.join(self.tooling, "capture.sh")
        command = ["/usr/bin/env", "-i"]
        command.extend("%s=%s" % item for item in env.items())
        command.extend(["/bin/bash", "--noprofile", "--norc", script])
        command.extend(args)
        if stderr_to is None:
            result = subprocess.run(
                command, cwd=self.checkout, capture_output=True,
                timeout=180)
            return (result.returncode,
                    result.stdout.decode("utf-8", "replace"),
                    result.stderr.decode("utf-8", "replace"))
        with open(stderr_to, "wb", 0) as sink:
            result = subprocess.run(
                command, cwd=self.checkout, stdout=subprocess.PIPE,
                stderr=sink, timeout=180)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"), "")

    def capture(self, index="1", **environment):
        """Run a capture that is expected to succeed."""
        status, out, err = self.run_capture(index, **environment)
        self.assertEqual(
            status, EX_OK,
            msg="capture failed (%d):\n%s" % (status, err))
        return self.payload(out), err

    def run_diagnostic(self, index="1", args=(), **environment):
        """Run capture.sh in DIAGNOSTIC mode and report the result.

        Every one of the four production safeguards -- the settle floor,
        the clock read, strict-fault handling and overwrite -- is HARD in
        production, so a test that relaxes one has to say which mode it
        is in.  It is a declaration rather than a workaround: a capture
        that relaxed a safeguard is not a capture for the record, and
        this mode is the only place capture.sh will perform one.
        """
        environment.setdefault("PLAYTHROUGH_CAPTURE_MODE", "diagnostic")
        return self.run_capture(index, args=args, **environment)

    def diagnostic(self, index="1", **environment):
        """Run a diagnostic capture that is expected to complete.

        Completion here means EX_DIAGNOSTIC, not success: the payload is
        produced, the frame is withdrawn to the reject directory, and no
        telemetry row is appended.  Asserting the status inside the
        helper is what stops a test from silently accepting a production
        capture where it meant a diagnostic one.
        """
        status, out, err = self.run_diagnostic(index, **environment)
        self.assertEqual(
            status, EX_DIAGNOSTIC,
            msg="diagnostic capture ended %d:\n%s" % (status, err))
        payload = self.payload(out)
        self.assertEqual(payload["CAPTURE_MODE"], "diagnostic")
        self.assertEqual(
            payload["FRAME_FILE"], "",
            msg="a withdrawn frame has no path in the working tree")
        return payload, err

    # -- reading the result ------------------------------------------

    def payload(self, text):
        """Parse the KEY=value payload from stdout."""
        parsed = {}
        for line in text.splitlines():
            name, _, value = line.partition("=")
            parsed[name] = value
        return parsed

    def tree(self):
        """Every path under the sandbox checkout, checkout-relative."""
        found = []
        for holder, directories, files in os.walk(self.checkout):
            for name in directories + files:
                found.append(os.path.relpath(
                    os.path.join(holder, name), self.checkout))
        return sorted(found)

    def frame_files(self):
        """Every file in the sandbox frames directory, sorted."""
        if not os.path.isdir(self.frames):
            return []
        return sorted(os.listdir(self.frames))

    @staticmethod
    def set_immutable(path, wanted):
        """Set or clear the immutable attribute; report whether it took.

        A directory mode is no use for "this cannot be written to" when
        the suite may run as uid 0, since root ignores it.  chattr is
        the honest expression of that condition, and a filesystem that
        does not support it is reported rather than worked around.
        """
        flag = "+i" if wanted else "-i"
        try:
            result = subprocess.run(
                ["chattr", flag, path], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def rejected(self):
        """Every withdrawn file, sorted."""
        if not os.path.isdir(self.reject):
            return []
        return sorted(os.listdir(self.reject))

    def audit_rows(self):
        """Every DATE AUDIT record, decoded.

        This is the one evidence file a capture still causes to grow,
        and ocr_clock.py -- not capture.sh -- appends it, through a
        hardened O_APPEND|O_CREAT|O_NOFOLLOW descriptor of its own.  The
        interpreter stub stands in for that write, so what these rows
        prove here is that the delegate was ASKED, with this frame's
        index, for the destination capture.sh nominated.
        """
        if not os.path.isfile(self.audit):
            return []
        with open(self.audit, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle
                    if line.strip()]

    def calls(self, name):
        """Every recorded invocation of one stub, as argument text."""
        if not os.path.isfile(self.stub_log):
            return []
        found = []
        with open(self.stub_log, encoding="utf-8") as handle:
            for line in handle:
                tool, _, arguments = line.rstrip("\n").partition("\t")
                if tool == name:
                    found.append(arguments)
        return found


class TestTheHappyPath(CaptureFixture):
    """One keystroke, one screenshot, one clock reading."""

    def test_a_successful_capture_leaves_exactly_one_frame(self):
        payload, _ = self.capture("1")
        self.assertEqual(
            self.frame_files(), ["frame_00001.png"],
            msg=("exit 0 means exactly one new frame, because "
                 "session.py reads it as licence to append exactly "
                 "one manifest row"))
        self.assertEqual(payload["FRAME_NAME"], "frame_00001.png")
        self.assertEqual(payload["FRAME_FILE"],
                         "playthrough/frames/frame_00001.png")
        self.assertEqual(self.rejected(), [])

    def test_the_index_is_zero_padded_to_five_digits(self):
        payload, _ = self.capture("42")
        self.assertEqual(payload["FRAME_NAME"], "frame_00042.png")
        self.assertEqual(self.frame_files(), ["frame_00042.png"])

    def test_the_payload_carries_every_key_in_order(self):
        _, _ = self.capture("1")
        status, out, _ = self.run_capture("2")
        self.assertEqual(status, EX_OK)
        names = [line.partition("=")[0] for line in out.splitlines()]
        self.assertEqual(
            names, list(PAYLOAD_KEYS),
            msg=("the payload is assembled in one buffer and written "
                 "with one printf, so a partially delivered contract "
                 "is impossible"))

    def test_stdout_carries_nothing_but_the_payload(self):
        status, out, _ = self.run_capture("1")
        self.assertEqual(status, EX_OK)
        for line in out.splitlines():
            with self.subTest(line=line):
                self.assertRegex(line, r"^[A-Z_]+=")

    def test_the_reading_and_its_evidence_reach_the_payload(self):
        payload, _ = self.capture(
            "1", STUB_DATE=DATE_LINE, STUB_DATE_RC="0")
        self.assertEqual(payload["CLOCK"], CLOCK)
        self.assertEqual(payload["CLOCK_STATUS"], "read")
        self.assertEqual(payload["CLOCK_SOURCE"], "ocr_clock.py")
        self.assertEqual(payload["DATE"], DATE_LINE)
        self.assertEqual(payload["DATE_STATUS"], "read")
        self.assertEqual(payload["FRAME_FORMAT"], "PNG")
        self.assertEqual(payload["FRAME_GEOMETRY"], "1920x1080")
        self.assertEqual(payload["CAPTURE_TOOL"], "import")
        self.assertEqual(payload["LUMA_MEAN"], "0.270018")
        self.assertEqual(payload["LUMA_STDDEV"], "0.198145")
        self.assertRegex(
            payload["REAL_TS"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_the_timestamp_is_the_instant_of_the_grab(self):
        # date(1) is replaced with a deterministic one, so the value in
        # the payload can be compared exactly rather than by shape.
        # manifest.py's canonical_real_ts() accepts precisely this
        # form, which is why the row can record when the shutter
        # opened rather than when the row was written.
        self.stub("date", 'printf "2026-03-08T08:15:32.250Z\\n"\n')
        payload, _ = self.capture("1")
        self.assertEqual(payload["REAL_TS"],
                         "2026-03-08T08:15:32.250Z")
        stamps = [call for call in self.calls("date")
                  if "%3N" in call or "%H" in call]
        self.assertEqual(
            stamps, ["-u +%Y-%m-%dT%H:%M:%S.%3NZ"],
            msg=("one UTC millisecond-precision reading, taken once. "
                 "env.sh's platform check reads a plain date of its "
                 "own to compare against its end-of-life table, which "
                 "is a different question and not a second stamp"))

    def test_a_date_without_millisecond_support_is_not_faked(self):
        # %3N is a GNU extension; where it is unavailable it survives
        # in the output verbatim, and emitting that would be a
        # fabricated timestamp.  The fallback carries second
        # resolution and an honestly zero millisecond field.
        self.stub("date", (
            'case "$*" in\n'
            "    *%3N*)\n"
            "        printf '%s\\n' '2026-03-08T08:15:32.%3NZ'\n"
            "        ;;\n"
            "    *)\n"
            "        printf '%s\\n' '2026-03-08T08:15:32'\n"
            "        ;;\n"
            "esac\n"))
        payload, err = self.capture("1")
        self.assertEqual(payload["REAL_TS"],
                         "2026-03-08T08:15:32.000Z")
        self.assertIn("no %3N", err)

    def test_exactly_one_root_window_grab_is_taken(self):
        self.capture("1")
        grabs = self.calls("import")
        self.assertEqual(
            len(grabs), 1,
            msg="one keystroke is one screenshot, not two")
        self.assertIn(
            "-window root", grabs[0],
            msg=("the root is exactly 1920x1080 while the game window "
                 "is 1920x1072 at +0+4, so grabbing the root needs no "
                 "rescaling and nothing softens the 8x16 glyphs the "
                 "clock read depends on"))

    def test_the_frame_settles_before_the_grab(self):
        self.capture("1")
        self.assertEqual(
            self.calls("sleep"), ["0.3"],
            msg=("the game redraws asynchronously; grabbing early "
                 "photographs the screen as it was BEFORE the key "
                 "landed and mis-times the whole film by one step"))

    def test_a_shorter_settle_cannot_produce_a_kept_frame(self):
        """The fourth safeguard, and the silent failure it prevents.

        The game redraws asynchronously, so grabbing early photographs
        the screen as it was BEFORE the key landed -- every clock
        reading one keystroke stale and the whole film mis-timed, while
        every count still tallied.  A LONGER settle is fine; a shorter
        one is diagnostic-only.
        """
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_CAPTURE_SETTLE="0.01")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("shorter than the contracted", err)
        self.assertIn("PLAYTHROUGH_CAPTURE_MODE=diagnostic", err)
        self.assertEqual(self.frame_files(), [])
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_SETTLE="0.01")
        self.assertEqual(payload["CAPTURE_MODE"], "diagnostic")

    def test_a_diagnostic_capture_is_owed_no_telemetry_row(self):
        """No frame in the record means no row about one.

        The sidecar's whole value to timeline.py is that it lines up
        with the manifest rows one for one, so a row describing a frame
        no manifest will ever mention would be an orphan in it.  A
        withdrawn frame is therefore owed no row, and the payload says
        so by naming no destination for one.
        """
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_CLOCK="off")
        self.assertEqual(
            payload["OBSERVATIONS"], "",
            msg="there is no destination to name when no row is owed")
        self.assertFalse(
            os.path.exists(self.observations),
            msg="and nothing was appended anywhere")
        self.assertEqual(self.frame_files(), [])

    def test_the_settle_is_overridable_for_a_faster_host(self):
        self.capture("1", PLAYTHROUGH_CAPTURE_SETTLE="0.5")
        self.assertEqual(self.calls("sleep"), ["0.5"])

    def test_the_crop_is_computed_not_hard_coded(self):
        payload, _ = self.capture("1")
        self.assertEqual(payload["CLOCK_RECT"], CROP)
        self.assertEqual(payload["CLOCK_RECT_FROM"], "computed")
        self.assertTrue(
            any("sidebar_geometry.py" in call
                for call in self.calls("python")),
            msg="the rectangle comes from the geometry module")

    def test_a_second_capture_appends_rather_than_replaces(self):
        first, _ = self.capture("1")
        second, _ = self.capture("2")
        self.assertEqual(self.frame_files(),
                         ["frame_00001.png", "frame_00002.png"])
        self.assertEqual(
            [first["FRAME_INDEX"], second["FRAME_INDEX"]], ["1", "2"],
            msg="each invocation reports the index it was given")
        self.assertEqual(
            [row["frame"] for row in self.audit_rows()], [1, 2],
            msg=("and each frame's date evidence is recorded under its "
                 "own index rather than over the previous one"))

    def test_help_is_the_only_argument_and_writes_no_frame(self):
        status, out, _ = self.run_capture("1", args=("--help",))
        self.assertEqual(status, EX_OK)
        self.assertIn("one keystroke, one screenshot", out)
        self.assertEqual(self.frame_files(), [])

    def test_any_other_argument_is_a_usage_error(self):
        status, _, err = self.run_capture("1", args=("42",))
        self.assertEqual(status, EX_USAGE)
        self.assertIn("takes no arguments", err)
        self.assertEqual(self.frame_files(), [])


class TestTheFrameIndex(CaptureFixture):
    """Never defaulted, never derived, never coerced."""

    def test_an_absent_index_is_refused(self):
        status, _, err = self.run_capture(index=None)
        self.assertEqual(status, EX_USAGE)
        self.assertIn("session.py owns the frame counter", err)
        self.assertEqual(self.frame_files(), [])

    def test_a_leading_zero_is_refused_because_printf_reads_octal(self):
        for value in ("010", "09", "0", "00001"):
            with self.subTest(index=value):
                status, _, err = self.run_capture(value)
                self.assertEqual(
                    status, EX_USAGE,
                    msg=("bash printf reads '010' as octal 8 and would "
                         "file frame 10 over frame 8, silently"))
                self.assertIn("octal", err)
                self.assertEqual(self.frame_files(), [])

    def test_anything_that_is_not_a_plain_integer_is_refused(self):
        for value in ("-1", "+1", "1.5", " 1", "1 ", "1a", "abc", "1e3",
                      "1,000", ""):
            with self.subTest(index=repr(value)):
                status, _, err = self.run_capture(value)
                self.assertEqual(status, EX_USAGE)
                self.assertEqual(self.frame_files(), [])

    def test_the_bounds_are_the_manifest_s_own(self):
        status, _, err = self.run_capture("100000")
        self.assertEqual(status, EX_USAGE)
        self.assertIn(
            "five-digit field", err,
            msg=("manifest.py refuses an index that would widen the "
                 "field, and a wider field breaks the lexical sort "
                 "the concat list depends on"))
        self.assertEqual(self.frame_files(), [])

    def test_the_last_usable_index_is_accepted(self):
        payload, _ = self.capture("99999")
        self.assertEqual(payload["FRAME_NAME"], "frame_99999.png")


class TestTheTunables(CaptureFixture):
    """A typo must not silently disable a guard."""

    def test_a_misspelled_clock_mode_is_refused(self):
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_CAPTURE_CLOCK="of")
        self.assertEqual(
            status, EX_USAGE,
            msg="'of' would otherwise read as 'not off'")
        self.assertEqual(self.frame_files(), [])

    def test_every_tunable_is_validated(self):
        cases = (
            {"PLAYTHROUGH_CAPTURE_PHRASE": "sometimes"},
            {"PLAYTHROUGH_CAPTURE_STRICT_CLOCK": "2"},
            {"PLAYTHROUGH_CAPTURE_OVERWRITE": "yes"},
            {"PLAYTHROUGH_CAPTURE_SETTLE": "soon"},
            {"PLAYTHROUGH_CAPTURE_SETTLE": "-1"},
            {"PLAYTHROUGH_CAPTURE_RECT": "288x1072"},
        )
        for environment in cases:
            with self.subTest(**environment):
                status, _, _ = self.run_capture("1", **environment)
                self.assertEqual(status, EX_USAGE)
                self.assertEqual(self.frame_files(), [])

    def test_the_clock_read_can_be_turned_off_entirely(self):
        """A diagnostic look at a frame, without reading it.

        Each frame's on-screen duration IS the clock delta to its
        successor, so a frame captured with the read switched off has no
        duration to derive -- which is why this is diagnostic-only.
        """
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_CLOCK="off")
        self.assertEqual(payload["CLOCK_STATUS"], "skipped")
        self.assertEqual(payload["CLOCK"], "")
        self.assertEqual(payload["DATE_STATUS"], "skipped")
        self.assertEqual(
            self.calls("tesseract"), [],
            msg="and then tesseract is never called")

    def test_an_explicit_crop_is_honoured_and_labelled(self):
        payload, _ = self.capture(
            "1", PLAYTHROUGH_CAPTURE_RECT="352x1072+1568+4")
        self.assertEqual(payload["CLOCK_RECT"], "352x1072+1568+4")
        self.assertEqual(payload["CLOCK_RECT_FROM"], "override")


class TestThePrerequisites(CaptureFixture):
    """A missing tool is a prerequisite failure, before anything runs."""

    def test_an_unverifiable_toolchain_is_refused_by_default(self):
        """A tool another account can replace is not run.

        The sandbox is private, so the condition is arranged rather than
        inherited: the sandbox root is made world-writable, which is
        precisely the state in which another account can substitute the
        interpreter or a tool between env.sh's check and the run that
        follows.  The tool that crops the sidebar decides every clock
        reading in the film, so a recorded session must not run one it
        cannot vouch for.
        """
        os.chmod(self.root, 0o777)
        status, _, err = self.run_capture("1")
        self.assertNotEqual(status, EX_OK)
        self.assertIn("world-writable", err)
        self.assertIn(
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES", err,
            msg="and the refusal says how to proceed deliberately")
        self.assertEqual(
            self.frame_files(), [],
            msg="nothing is captured with an unverified toolchain")

    def test_declaring_the_unverifiable_toolchain_still_refuses(self):
        """The declaration buys a diagnosis, never a frame.

        This is the half a warning could not enforce.  Setting the
        override used to produce an ordinary, apparently successful
        production capture with nothing but a line on stderr to say the
        toolchain was untrustworthy -- and that frame then counted as
        evidence.  Now the trust state refuses the production capture and
        offers the diagnostic mode, whose frame is withdrawn out of the
        working tree.
        """
        os.chmod(self.root, 0o777)
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES="1")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("trust state is 'diagnostic'", err)
        self.assertIn("PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES", err)
        self.assertEqual(
            self.frame_files(), [],
            msg="the refusal happens before anything is captured")
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES="1")
        self.assertEqual(payload["CAPTURE_MODE"], "diagnostic")
        self.assertEqual(
            self.frame_files(), [],
            msg="and the diagnostic frame never joins the record")

    def test_no_capturer_at_all_is_a_prerequisite_failure(self):
        os.unlink(os.path.join(self.bin, "import"))
        os.unlink(os.path.join(self.bin, "scrot"))
        status, _, err = self.run_capture("1")
        self.assertEqual(status, EX_PREREQ)
        self.assertIn("no usable screen capturer", err)
        self.assertIn(
            "verifiable", err,
            msg=("present-but-untrustworthy is treated exactly like "
                 "absent, so the message covers both"))
        self.assertEqual(self.frame_files(), [])

    def test_scrot_is_the_documented_fallback(self):
        os.unlink(os.path.join(self.bin, "import"))
        payload, err = self.capture("1")
        self.assertEqual(payload["CAPTURE_TOOL"], "scrot")
        self.assertIn("falling back to scrot", err)
        self.assertEqual(len(self.calls("scrot")), 1)

    def test_a_missing_measurement_tool_is_a_prerequisite_failure(self):
        for tool in ("convert", "identify", "xdpyinfo"):
            with self.subTest(tool=tool):
                self.setUp()
                os.unlink(os.path.join(self.bin, tool))
                status, _, err = self.run_capture("1")
                self.assertEqual(status, EX_PREREQ)
                self.assertIn(tool, err)
                self.assertEqual(self.frame_files(), [])

    def test_a_missing_tesseract_is_a_prerequisite_failure(self):
        os.unlink(os.path.join(self.bin, "tesseract"))
        status, _, err = self.run_capture("1")
        self.assertEqual(
            status, EX_PREREQ,
            msg=("both clock-read paths need it, so its absence is a "
                 "prerequisite failure rather than an unreadable "
                 "clock"))
        self.assertEqual(self.frame_files(), [])

    def test_the_missing_tool_message_names_its_package(self):
        os.unlink(os.path.join(self.bin, "convert"))
        _, _, err = self.run_capture("1")
        self.assertIn("imagemagick", err)


class TestTheDisplayGate(CaptureFixture):
    """A wrong display is reported before a frame exists."""

    def test_a_display_of_the_wrong_size_is_refused(self):
        status, _, err = self.run_capture(
            "1", STUB_DIMENSIONS="1280x720")
        self.assertEqual(status, EX_GEOMETRY)
        self.assertIn("root window is '1280x720'", err)
        self.assertEqual(
            self.frame_files(), [],
            msg="the check runs before the grab, so nothing was "
                "captured")

    def test_a_display_of_the_wrong_depth_is_refused(self):
        status, _, err = self.run_capture("1", STUB_DEPTH="16")
        self.assertEqual(status, EX_GEOMETRY)
        self.assertIn("root depth is '16'", err)

    def test_no_answering_display_is_refused(self):
        status, _, err = self.run_capture("1", STUB_XDPYINFO_RC="1")
        self.assertEqual(status, EX_GEOMETRY)
        self.assertIn("no X server", err)
        self.assertEqual(self.frame_files(), [])


class TestTheGrab(CaptureFixture):
    """A capturer that lies is not believed."""

    def test_a_capturer_that_fails_leaves_no_frame(self):
        status, _, err = self.run_capture("1", STUB_IMPORT_RC="1")
        self.assertEqual(status, EX_CAPTURE)
        self.assertIn("import -window root failed", err)
        self.assertEqual(self.frame_files(), [])

    def test_a_capturer_that_writes_nothing_is_not_believed(self):
        status, _, err = self.run_capture("1", STUB_IMPORT_WRITE="0")
        self.assertEqual(status, EX_CAPTURE)
        self.assertIn("reported success but wrote no file", err)
        self.assertEqual(self.frame_files(), [])

    def test_a_zero_byte_frame_is_refused(self):
        status, _, err = self.run_capture("1", STUB_PNG="")
        self.assertEqual(status, EX_CAPTURE)
        self.assertIn("zero-byte", err)
        self.assertEqual(self.frame_files(), [])

    def test_a_frame_that_is_not_a_png_is_refused(self):
        status, _, err = self.run_capture(
            "1", STUB_IDENTIFY="JPEG 1920x1080")
        self.assertEqual(status, EX_CAPTURE)
        self.assertIn("is a JPEG, not a PNG", err)
        self.assertEqual(self.frame_files(), [])

    def test_a_frame_of_the_wrong_size_is_refused(self):
        status, _, err = self.run_capture(
            "1", STUB_IDENTIFY="PNG 1280x720")
        self.assertEqual(status, EX_GEOMETRY)
        self.assertIn("not the contracted 1920x1080", err)
        self.assertEqual(self.frame_files(), [])

    def test_an_unreadable_image_is_refused(self):
        status, _, err = self.run_capture("1", STUB_IDENTIFY_RC="1")
        self.assertEqual(status, EX_CAPTURE)
        self.assertEqual(self.frame_files(), [])

    def test_a_withdrawn_frame_is_kept_outside_the_working_tree(self):
        status, _, err = self.run_capture("1", STUB_LUMA=DUMMY_LUMA)
        self.assertEqual(status, EX_BLANK)
        self.assertEqual(self.frame_files(), [])
        self.assertEqual(
            self.rejected(), ["frame_00001.png"],
            msg=("the rejected frame is the evidence of whatever went "
                 "wrong, and it is kept outside the tree so it can "
                 "never be committed as a session frame"))
        self.assertIn("withdrew", err)


class TestTheBlankGate(CaptureFixture):
    """The guard against the pipeline's one silent catastrophe."""

    def test_a_black_frame_is_refused(self):
        status, _, err = self.run_capture("1", STUB_LUMA=DUMMY_LUMA)
        self.assertEqual(status, EX_BLANK)
        self.assertIn("is blank", err)
        self.assertIn(
            "dummy video backend", err,
            msg=("mean=0 with stddev=0 is its signature, and the "
                 "message says so"))

    def test_a_uniform_solid_frame_is_refused_too(self):
        status, _, err = self.run_capture("1", STUB_LUMA=FLAT_LUMA)
        self.assertEqual(
            status, EX_BLANK,
            msg=("the standard-deviation term catches a flat screen "
                 "that a mean test alone would pass"))
        self.assertIn("uniform solid screen", err)

    def test_a_luminance_that_is_not_numeric_is_refused(self):
        for value in ("nan nan", "inf inf", "mean stddev", ""):
            with self.subTest(luma=repr(value)):
                status, _, err = self.run_capture("1", STUB_LUMA=value)
                self.assertEqual(
                    status, EX_CAPTURE,
                    msg=("awk compares a non-numeric string against 0 "
                         "as STRINGS, so 'nan' would satisfy > 0 and a "
                         "blank frame would pass the gate"))
                self.assertEqual(self.frame_files(), [])

    def test_a_measurement_failure_is_refused(self):
        status, _, err = self.run_capture("1", STUB_CONVERT_RC="1")
        self.assertEqual(status, EX_CAPTURE)
        self.assertEqual(self.frame_files(), [])

    def test_a_faint_but_real_frame_is_accepted(self):
        payload, _ = self.capture("1", STUB_LUMA="0.004 0.002")
        self.assertEqual(payload["LUMA_MEAN"], "0.004")
        self.assertEqual(self.frame_files(), ["frame_00001.png"])


class TestOverwritingAnExistingFrame(CaptureFixture):
    """A repeated index means the counter went backwards."""

    def existing(self, name="frame_00001.png", body="earlier frame"):
        """Put a frame in the way and return its path and bytes."""
        path = self.write(os.path.join(self.frames, name), body)
        with open(path, "rb") as handle:
            return path, handle.read()

    def test_a_frames_directory_that_refuses_writes_is_not_a_collision(
            self):
        """An unwritable directory is a capture failure, not a reuse.

        Both failures arrive as the same refusal from noclobber, and
        reporting the wrong one is not just confusing: "take the next
        index" is the remedy for a collision and is actively harmful
        here, because every index would fail identically and a caller
        following that advice would walk the counter forward through a
        whole session of failures.
        """
        # Immutability rather than a mode, because this suite may run as
        # uid 0 and root ignores directory permissions.  Skipped rather
        # than faked where the filesystem cannot express it.
        os.makedirs(self.frames, exist_ok=True)
        if not self.set_immutable(self.frames, True):
            self.skipTest(
                "this filesystem cannot make a directory immutable, "
                "and a mode would not stop uid 0 from writing")
        self.addCleanup(self.set_immutable, self.frames, False)
        status, _, err = self.run_capture("1")
        self.assertEqual(
            status, EX_CAPTURE,
            msg="EX_EXISTS would mean the index was taken; it is not")
        self.assertIn("nothing is there to be in the way", err)
        self.assertIn("next index would fail identically", err)
        self.assertEqual(self.frame_files(), [])

    def test_an_existing_frame_is_not_clobbered(self):
        path, before = self.existing()
        status, _, err = self.run_capture("1")
        self.assertEqual(status, EX_EXISTS)
        self.assertIn("already exists", err)
        with open(path, "rb") as handle:
            self.assertEqual(
                handle.read(), before,
                msg=("overwriting would leave the frame count one "
                     "short of the keystroke count with nothing to "
                     "show that it happened"))

    def test_a_diagnostic_recapture_loses_nothing(self):
        """OVERWRITE permits a look, and takes nothing away.

        A frame already at this index means the counter repeated, and a
        production capture that replaced it would move a frame that had
        been photographed and committed OUT of the working tree while
        every count still tallied.  So overwriting is diagnostic-only,
        and even then the original is moved aside and put straight back
        when the diagnostic frame is withdrawn: the end state is the
        frames directory exactly as it was found, plus one image outside
        the tree to look at.
        """
        path, before = self.existing()
        payload, err = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_OVERWRITE="1")
        self.assertEqual(self.frame_files(), ["frame_00001.png"])
        with open(path, "rb") as handle:
            self.assertEqual(
                handle.read(), before,
                msg="the committed frame is byte-for-byte as it was")
        self.assertIn(
            "frame_00001.png", self.rejected(),
            msg="and the diagnostic capture is outside the tree")
        self.assertIn("is restored if this capture does not succeed",
                      err.replace("\n", " "))
        self.assertIn("restored the frame that was already at", err)

    def test_replacing_a_kept_frame_is_refused_outright(self):
        """The safeguard itself, asserted rather than trusted."""
        path, before = self.existing()
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_CAPTURE_OVERWRITE="1")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("cannot be used for a frame that is kept", err)
        self.assertIn("the counter repeated", err)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(self.rejected(), [])

    def test_a_failed_recapture_restores_the_original_exactly(self):
        path, before = self.existing()
        status, _, err = self.run_diagnostic(
            "1", PLAYTHROUGH_CAPTURE_OVERWRITE="1",
            STUB_LUMA=DUMMY_LUMA)
        self.assertEqual(status, EX_BLANK)
        self.assertEqual(
            self.frame_files(), ["frame_00001.png"],
            msg="the earlier frame is back in place")
        with open(path, "rb") as handle:
            self.assertEqual(
                handle.read(), before,
                msg=("a non-zero exit always leaves the frames "
                     "directory exactly as it was found, byte for "
                     "byte"))
        self.assertIn("restored the frame that was already at", err)

    def test_a_recapture_that_cannot_move_the_original_aside_refuses(self):
        self.existing()
        status, _, err = self.run_diagnostic(
            "1", PLAYTHROUGH_CAPTURE_OVERWRITE="1",
            PLAYTHROUGH_CAPTURE_REJECT_DIR="/proc/nope/rejected")
        self.assertEqual(status, EX_CAPTURE)
        self.assertIn("refusing to overwrite it in place", err)
        self.assertEqual(self.frame_files(), ["frame_00001.png"])


class TestTheClockRead(CaptureFixture):
    """An assist that may fail and may never invent."""

    def test_a_reading_is_reported_verbatim(self):
        payload, _ = self.capture("1", STUB_CLOCK="23:59:58")
        self.assertEqual(payload["CLOCK"], "23:59:58")
        self.assertEqual(payload["CLOCK_STATUS"], "read")

    def test_an_unreadable_clock_is_an_ordinary_outcome(self):
        payload, _ = self.capture("1", STUB_CLOCK="",
                                  STUB_CLOCK_RC="1")
        self.assertEqual(payload["CLOCK_STATUS"], "unreadable")
        self.assertEqual(
            payload["CLOCK"], "",
            msg=("never 00:00:00, never the previous frame's value, "
                 "never an interpolation"))
        self.assertEqual(self.frame_files(), ["frame_00001.png"])

    def test_a_watchless_frame_reports_its_phrase_instead(self):
        payload, _ = self.capture(
            "1", STUB_CLOCK="", STUB_CLOCK_RC="1",
            STUB_PHRASE=PHRASE, STUB_PHRASE_RC="0")
        self.assertEqual(payload["CLOCK_STATUS"], "unreadable")
        self.assertEqual(
            payload["TIME_PHRASE"], PHRASE,
            msg=("a coarse phrase is a real reading and surfaces "
                 "verbatim rather than being discarded"))

    def test_the_phrase_is_only_read_when_it_is_the_reading(self):
        payload, _ = self.capture("1", STUB_PHRASE=PHRASE,
                                  STUB_PHRASE_RC="0")
        self.assertEqual(
            payload["TIME_PHRASE"], "",
            msg=("with a clock in hand the phrase is not asked for: "
                 "'auto' means exactly when there was no clock"))

    def test_the_phrase_can_be_demanded_or_declined(self):
        payload, _ = self.capture(
            "1", PLAYTHROUGH_CAPTURE_PHRASE="always",
            STUB_PHRASE=PHRASE, STUB_PHRASE_RC="0")
        self.assertEqual(payload["TIME_PHRASE"], PHRASE)
        payload, _ = self.capture(
            "2", PLAYTHROUGH_CAPTURE_PHRASE="off", STUB_CLOCK="",
            STUB_CLOCK_RC="1", STUB_PHRASE=PHRASE,
            STUB_PHRASE_RC="0")
        self.assertEqual(payload["TIME_PHRASE"], "")

    def test_a_fault_is_fatal_by_default(self):
        status, _, err = self.run_capture("1", STUB_CLOCK_RC="2")
        self.assertEqual(status, EX_CLOCK_FAULT)
        self.assertIn("This is a fault, not an unreadable clock", err)
        self.assertEqual(
            self.frame_files(), [],
            msg=("a standing misconfiguration would report every later "
                 "frame as unreadable, collapsing every duration to "
                 "the floor while every count still tallied"))

    def test_a_fault_can_be_recorded_instead_of_fatal(self):
        """And the frame that records it never joins the record.

        STRICT_CLOCK=0 is one of the four production safeguards, so the
        two decisions are the same one: a fault is worth LOOKING at, and
        a frame whose clock faulted has no duration to derive -- so it
        is captured, withdrawn, and reported non-zero.
        """
        payload, err = self.diagnostic(
            "1", STUB_CLOCK_RC="2",
            PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0)
        self.assertEqual(payload["CLOCK_STATUS"], "fault")
        self.assertEqual(
            payload["CLOCK"], "",
            msg=("a reading beside CLOCK_STATUS=fault is a value the "
                 "manifest would record and timeline.py would "
                 "difference"))
        self.assertEqual(
            self.frame_files(), [],
            msg="nothing was added to playthrough/frames/")
        self.assertEqual(
            os.listdir(self.reject), ["frame_00001.png"],
            msg="it is kept outside the tree, where it can be looked at")
        self.assertIn("DIAGNOSTIC capture", err)

    def test_a_recorded_fault_needs_the_mode_declared(self):
        """The safeguard itself, asserted rather than trusted."""
        status, _, err = self.run_capture(
            "1", STUB_CLOCK_RC="2",
            PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0)
        self.assertEqual(status, EX_USAGE)
        self.assertIn("cannot be used for a frame that is kept", err)
        self.assertIn("PLAYTHROUGH_CAPTURE_MODE=diagnostic", err)
        self.assertEqual(self.frame_files(), [])

    def test_an_impossible_reading_is_refused_not_emitted(self):
        status, _, err = self.run_capture(
            "1", STUB_CLOCK=IMPOSSIBLE_CLOCK)
        self.assertEqual(status, EX_CLOCK_FAULT)
        self.assertIn("not a possible", err)
        self.assertEqual(
            self.frame_files(), [],
            msg=("a reading that cannot be true is not reported as a "
                 "clock, whoever produced it"))

    def test_a_malformed_reading_is_refused_too(self):
        for value in ("8:15:32", "0815.32", "13:45", "13:45:27 AM"):
            with self.subTest(clock=value):
                self.setUp()
                status, _, err = self.run_capture("1",
                                                  STUB_CLOCK=value)
                self.assertEqual(status, EX_CLOCK_FAULT)
                self.assertEqual(self.frame_files(), [])

    def test_every_boundary_reading_is_accepted(self):
        for value in ("00:00:00", "23:59:59", "08:15:32"):
            with self.subTest(clock=value):
                self.setUp()
                payload, _ = self.capture("1", STUB_CLOCK=value)
                self.assertEqual(payload["CLOCK"], value)

    def test_the_delegate_is_called_with_the_computed_crop(self):
        self.capture("1")
        clock_calls = [call for call in self.calls("python")
                       if "--kv" in call]
        self.assertEqual(
            len(clock_calls), 1,
            msg=("one OCR pass answers the clock, the phrase and the "
                 "date; three passes over the same pixels could "
                 "disagree about what the frame showed"))
        self.assertIn("--rect %s" % CROP, clock_calls[0])
        self.assertIn(
            "--strict-path", clock_calls[0],
            msg=("an automated caller passes it, so a frame from "
                 "outside the capture directory is refused rather "
                 "than warned about"))
        self.assertIn(
            "--audit-frame 1", clock_calls[0],
            msg=("the date evidence is recorded per frame, and the "
                 "frame number is what lets timeline.py line the "
                 "record up with the reading it belongs to"))

    def test_a_failed_preflight_is_fatal_before_any_frame_exists(self):
        status, _, err = self.run_capture("1", STUB_PREFLIGHT_RC="2")
        self.assertEqual(status, EX_CLOCK_FAULT)
        self.assertEqual(
            self.frame_files(), [],
            msg=("one actionable failure instead of a whole session of "
                 "frames that each look like an honest unreadable "
                 "clock"))
        self.assertEqual(
            self.calls("import"), [],
            msg="and nothing was even grabbed")

    def test_a_failed_preflight_can_fall_back_to_the_inline_chain(self):
        payload, err = self.diagnostic(
            "1", STUB_PREFLIGHT_RC="2",
            PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0,
            STUB_TESSERACT="Thursday, Mar 8\n%s" % CLOCK)
        self.assertEqual(payload["CLOCK_SOURCE"], "inline")
        self.assertEqual(payload["CLOCK"], CLOCK)
        self.assertIn("documented last resort", err)

    def test_the_inline_chain_declines_an_impossible_reading(self):
        payload, err = self.diagnostic(
            "1", STUB_PREFLIGHT_RC="2",
            PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0,
            STUB_TESSERACT="%s\n%s" % (IMPOSSIBLE_CLOCK, CLOCK))
        self.assertEqual(
            payload["CLOCK"], CLOCK,
            msg="the first POSSIBLE match in reading order wins")
        self.assertIn("declining '%s'" % IMPOSSIBLE_CLOCK, err)

    def test_the_inline_chain_reports_an_absent_clock_honestly(self):
        payload, _ = self.diagnostic(
            "1", STUB_PREFLIGHT_RC="2",
            PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0,
            STUB_TESSERACT="New Game    Load")
        self.assertEqual(payload["CLOCK_STATUS"], "unreadable")
        self.assertEqual(payload["CLOCK"], "")

    def test_the_inline_chain_has_no_date_extraction_and_says_so(self):
        # The audit is asked for EXPLICITLY here, because this assertion
        # is about the inline chain rather than about the mode: a
        # diagnostic capture now defaults the audit off (a withdrawn
        # frame owes no row), and "off" would say nothing about whether
        # the fallback records a date when one is wanted.  "no" does.
        payload, err = self.diagnostic(
            "1", STUB_PREFLIGHT_RC="2",
            PLAYTHROUGH_CAPTURE_STRICT_CLOCK=0,
            PLAYTHROUGH_CAPTURE_AUDIT="on",
            STUB_TESSERACT=CLOCK)
        self.assertEqual(payload["DATE_STATUS"], "unavailable")
        self.assertEqual(
            payload["DATE_AUDIT"], "no",
            msg=("and the missing evidence is reported as missing: a "
                 "frame with no date record must be reconciled, never "
                 "read as a day that did not turn"))
        self.assertIn("no date extraction", err)
        self.assertIn("must reconcile", err)


class TestTheCropResolution(CaptureFixture):
    """Computed or explicitly overridden -- and never substituted.

    A DOCUMENTED RECTANGLE IS NOT A FALLBACK, AND THERE ARE TWO OF THEM.
    352x1072+1568+4 is right for the layout a FRESH userdir draws --
    legacy_labels_sidebar, 44 cells at 8x16 on the right of a 240x67
    grid -- and 288x1072+1632+4 is right for a userdir whose panel
    options select the 36-cell custom_sidebar.  Twelve widgets across
    data/json/ui declare "style": "sidebar" at eight distinct widths,
    so each literal describes one configuration out of many.  Cropping
    the wrong column does not look like an error: it reads as an
    unreadable clock, so every duration falls to the 0.25 s floor while
    every count still tallies and the finished film is plausible and
    meaningless.  A crop that could not be computed is therefore a
    stop, and an operator who genuinely wants a fixed rectangle asks
    for one by name.
    """

    def test_a_geometry_module_that_fails_is_not_papered_over(self):
        status, _, err = self.run_capture("1", STUB_GEOMETRY_RC="1")
        self.assertEqual(status, EX_GEOMETRY)
        self.assertIn("is NOT substituted", err)
        self.assertIn(DEFAULT_LAYOUT_CROP, err)
        self.assertIn(
            EXAMPLE_CROP, err,
            msg=("both worked examples are quoted, because naming one "
                 "as THE rectangle is how a reader comes to believe a "
                 "literal describes their run"))
        self.assertIn("PLAYTHROUGH_CAPTURE_RECT", err)
        self.assertEqual(
            self.frame_files(), [],
            msg=("this run's configuration is exactly what could not "
                 "be read, so no frame is kept on the strength of a "
                 "literal that describes a different one"))

    def test_an_absent_geometry_module_is_refused_too(self):
        os.unlink(os.path.join(self.tooling, "sidebar_geometry.py"))
        status, _, err = self.run_capture("1")
        self.assertEqual(status, EX_GEOMETRY)
        self.assertIn("missing", err)
        self.assertIn("NOT substituted", err)
        self.assertIn(DEFAULT_LAYOUT_CROP, err)
        self.assertIn(EXAMPLE_CROP, err)
        self.assertEqual(self.frame_files(), [])

    def test_the_diagnostics_name_the_layout_each_rectangle_belongs_to(
            self):
        """A quoted rectangle carries the layout it is right for.

        Naming one on its own is how a literal goes stale: the value
        below belongs to a 36-cell custom_sidebar, while the engine's own
        default is the 44-cell legacy_labels_sidebar, and a reader who
        took the first for "the documented crop" would be cropping 64
        pixels short of the column while every count still tallied.
        """
        for setup in ({"STUB_GEOMETRY_RC": "1"}, {}):
            if not setup:
                os.unlink(
                    os.path.join(self.tooling, "sidebar_geometry.py"))
            with self.subTest(geometry_absent=not setup):
                _, _, err = self.run_capture("1", **setup)
                self.assertIn(DEFAULT_LAYOUT_CROP, err)
                self.assertIn("legacy_labels_sidebar", err)
                self.assertIn(EXAMPLE_CROP, err)
                self.assertIn("custom_sidebar", err)

    def test_the_sanctioned_way_past_it_is_an_explicit_rectangle(self):
        os.unlink(os.path.join(self.tooling, "sidebar_geometry.py"))
        payload, err = self.capture("1",
                                    PLAYTHROUGH_CAPTURE_RECT=CROP)
        self.assertEqual(payload["CLOCK_RECT"], CROP)
        self.assertEqual(
            payload["CLOCK_RECT_FROM"], "override",
            msg=("the choice is recorded in the session record rather "
                 "than inferred from a warning nobody read"))
        self.assertIn("EXPLICIT crop override", err)

    def test_no_crop_is_resolved_when_no_crop_will_be_used(self):
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_CLOCK="off")
        self.assertEqual(payload["CLOCK_RECT"], "")
        self.assertEqual(
            payload["CLOCK_RECT_FROM"], "skipped",
            msg=("with the clock read off nothing crops the frame, so "
                 "reporting a rectangle would claim a crop that never "
                 "happened"))
        self.assertEqual(
            [call for call in self.calls("python")
             if "sidebar_geometry.py" in call], [],
            msg="and the geometry module is not even asked")

    def test_a_malformed_computed_crop_is_a_clock_fault(self):
        status, _, err = self.run_capture(
            "1", STUB_GEOMETRY="not-a-geometry")
        self.assertEqual(status, EX_CLOCK_FAULT)
        self.assertIn("is not an ImageMagick WxH+X+Y geometry", err)
        self.assertEqual(self.frame_files(), [])


class TestTheTelemetryHandoff(CaptureFixture):
    """Reported here, persisted by the orchestrator.

    capture.sh used to append the telemetry row itself, which split ONE
    logical transaction -- publish the frame, record the row -- across
    two processes with no coordinator, and gave a script whose whole
    contract is "one PNG in playthrough/frames/" a second, redirectable
    destination inside the working tree.  The row now leaves on the
    machine payload and session.py, which already owns the frame counter
    and the manifest row for the same frame, appends it.

    So what is asserted here is a WRITE SURFACE and a HANDOFF: that
    every field the row needs arrives, that the destination named is the
    canonical one, that no environment variable can move it, and that
    the frame really is the only thing inside the checkout a capture
    writes.
    """

    def test_every_field_the_row_needs_arrives_on_the_payload(self):
        """The evidence is not weakened by moving the writer.

        Fifteen fields made up the row.  Each one is checked against
        the payload key that now carries it, so a field that lost its
        way in the handoff fails here rather than going missing from a
        session record nobody re-reads.
        """
        payload, _ = self.capture(
            "1", STUB_DATE=DATE_LINE, STUB_DATE_RC="0")
        for field, key in sorted(OBSERVATION_FIELDS.items()):
            with self.subTest(field=field, key=key):
                self.assertIn(
                    key, payload,
                    msg="%s has no key to arrive on" % field)
                if field == "time_phrase":
                    # Empty BY CONTRACT here, and that is the reading
                    # rather than a gap: the sidebar shows a coarse
                    # phrase INSTEAD of a time when the survivor has no
                    # watch [src/display.cpp:207-218], so beside a clock
                    # a phrase is noise and is dropped.  The populated
                    # case is asserted immediately below.
                    continue
                self.assertNotEqual(
                    payload[key], "",
                    msg=("%s arrived empty, so the row session.py "
                         "builds would carry nothing for it" % field))
        watchless, _ = self.capture(
            "2", STUB_CLOCK="", STUB_CLOCK_RC="1",
            STUB_PHRASE=PHRASE, STUB_PHRASE_RC="0")
        self.assertEqual(
            watchless["TIME_PHRASE"], PHRASE,
            msg=("and when the phrase IS the reading it arrives "
                 "verbatim, so the row carries what the frame showed"))
        self.assertEqual(payload["FRAME_INDEX"], "1")
        self.assertEqual(payload["FRAME_FILE"],
                         "playthrough/frames/frame_00001.png")
        self.assertEqual(payload["CLOCK"], CLOCK)
        self.assertEqual(payload["DATE"], DATE_LINE)
        self.assertEqual(payload["DATE_STATUS"], "read")
        self.assertEqual(payload["CLOCK_RECT"], CROP)

    def test_the_payload_names_the_canonical_destination(self):
        payload, _ = self.capture("1")
        self.assertEqual(
            payload["OBSERVATIONS"], self.observations,
            msg=("the destination reported is env.sh's own "
                 "PLAYTHROUGH_OBSERVATIONS, which is where timeline.py "
                 "looks -- naming anything else would hand the caller "
                 "a path nothing downstream reads"))

    def test_the_capture_appends_nothing_to_it(self):
        """The row is reported, and the file stays absent.

        Two captures, and the sidecar still does not exist: the only
        thing that could have created it was the writer this file no
        longer carries.
        """
        self.capture("1")
        self.capture("2")
        self.assertFalse(
            os.path.exists(self.observations),
            msg=("capture.sh writes into playthrough/frames/ and "
                 "nowhere else inside the tree; the row belongs to the "
                 "process that appends the manifest row beside it"))

    def test_the_destination_cannot_be_redirected(self):
        """There is no override left, and that is the point.

        PLAYTHROUGH_CAPTURE_OBSERVATIONS used to move the append to any
        regular file under the checkout, which is a way to write real
        evidence where nothing reads it while every count still
        tallies.  Setting it now changes nothing: the payload still
        names the canonical path, and no file appears at the nominated
        one.
        """
        elsewhere = os.path.join(self.build, "elsewhere.jsonl")
        payload, _ = self.capture(
            "1", PLAYTHROUGH_CAPTURE_OBSERVATIONS=elsewhere)
        self.assertEqual(payload["OBSERVATIONS"], self.observations)
        self.assertFalse(
            os.path.exists(elsewhere),
            msg="a nominated destination is not honoured, or created")

    def test_the_frame_is_the_only_thing_added_inside_the_checkout(self):
        # playthrough/build/ is created by playthrough_mkdirs, not by
        # this file, so it is already there: what is asserted is what a
        # capture ADDS.  The blast radius is now exactly its own frames
        # directory and the frame in it, plus the DATE AUDIT -- which
        # ocr_clock.py appends through a hardened descriptor of its own,
        # standing in here as the interpreter stub.  capture.sh asks for
        # that record; it does not write it.
        before = self.tree()
        self.capture("1")
        added = sorted(set(self.tree()) - set(before))
        self.assertEqual(
            added,
            ["playthrough/build/frame_dates.jsonl",
             "playthrough/frames",
             "playthrough/frames/frame_00001.png"],
            msg=("nothing else is created, moved or truncated: the "
                 "telemetry sidecar belongs to session.py, and the "
                 "transition frames, the concat list and the movie all "
                 "belong to later stages"))

    def test_the_date_audit_still_goes_where_timeline_py_reads_it(self):
        """The evidence that DOES get persisted, and by whom.

        The date line is the only thing that tells a crossing of
        midnight from a misread clock, so its record survives the
        handoff untouched: ocr_clock.py is asked for it, per frame, at
        env.sh's canonical audit path.
        """
        payload, _ = self.capture(
            "1", STUB_DATE=DATE_LINE, STUB_DATE_RC="0")
        self.assertEqual(payload["DATE_AUDIT"], "yes")
        rows = self.audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["frame"], 1)
        self.assertEqual(rows[0]["date"], DATE_LINE)
        self.assertTrue(
            any("--audit %s" % self.audit in call
                for call in self.calls("python")),
            msg="the delegate was asked for the canonical destination")

    def test_a_production_audit_elsewhere_is_refused(self):
        """The one destination a capture still nominates is fixed.

        A frame's date evidence filed where timeline.py does not look is
        evidence nothing consults, and its absence reads as
        DATE_AUDIT=no rather than as an error -- so every count would
        still tally while the rollover guard treated the frame's date as
        unknown.  Nominating another path is a diagnostic action.
        """
        elsewhere = os.path.join(self.build, "audit-elsewhere.jsonl")
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_CAPTURE_AUDIT_PATH=elsewhere)
        self.assertEqual(status, EX_USAGE)
        self.assertIn("PLAYTHROUGH_CAPTURE_AUDIT_PATH", err)
        self.assertIn(self.audit, err)
        self.assertIn("PLAYTHROUGH_CAPTURE_MODE=diagnostic", err)
        self.assertFalse(
            os.path.exists(elsewhere),
            msg="the refusal precedes the display and every write")
        self.assertEqual(self.frame_files(), [])
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_AUDIT_PATH=elsewhere)
        self.assertEqual(
            payload["DATE_AUDIT"], "yes",
            msg=("a diagnostic capture may file it elsewhere, and its "
                 "frame is withdrawn out of the working tree in "
                 "exchange"))

    def test_a_diagnostic_capture_leaves_no_row_in_the_audit(self):
        """Runtime QA finding: three rows for a frame that never existed.

        A diagnostic capture is withdrawn out of the working tree and
        emits no repository-relative path so that it cannot be mistaken
        for a frame of the record -- but the audit was resolved before
        the mode was read, so a probe at the reserved index 99999 still
        appended a row to the sidecar timeline.py reads, naming a
        playthrough/frames/frame_99999.png that does not exist.  The
        reading a probe wants is in its own payload; the audit is the
        record, and a withdrawn frame owes it nothing.
        """
        payload, _ = self.diagnostic(
            "99999", STUB_DATE=DATE_LINE, STUB_DATE_RC="0")
        self.assertEqual(payload["DATE_AUDIT"], "off")
        self.assertEqual(self.audit_rows(), [])
        self.assertFalse(
            any("--audit" in call for call in self.calls("python")),
            msg="the delegate is not even asked for a destination")
        # The reading itself is not withheld: it is in the payload, which
        # is the whole point of looking at the screen this way.
        self.assertEqual(payload["DATE"], DATE_LINE)

    def test_a_diagnostic_capture_may_still_ask_for_the_audit(self):
        """The relaxation is a default, not a prohibition.

        An explicit PLAYTHROUGH_CAPTURE_AUDIT=on still records the row,
        so a caller diagnosing the audit path itself keeps the one tool
        that shows it working.
        """
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_CAPTURE_AUDIT="on",
            STUB_DATE=DATE_LINE, STUB_DATE_RC="0")
        self.assertEqual(payload["DATE_AUDIT"], "yes")
        rows = self.audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["frame"], 1)

    def test_a_production_capture_still_records_every_frame_s_date(self):
        """The default change is confined to the diagnostic mode.

        The audit is the evidence that tells a crossing of midnight from
        a clock that read backwards, so for a frame that is KEPT it stays
        mandatory and stays at the canonical destination.
        """
        payload, _ = self.capture(
            "1", STUB_DATE=DATE_LINE, STUB_DATE_RC="0")
        self.assertEqual(payload["DATE_AUDIT"], "yes")
        self.assertEqual(len(self.audit_rows()), 1)


class TestTheCommitPoint(CaptureFixture):
    """Nothing that can fail runs after the frame is kept.

    `exit 0` means "one new frame AND the whole output contract", so the
    two halves have to be decided in that order.  A fallible statement
    AFTER `KEPT=1` breaks it in the one direction the 1:1 invariant
    cannot absorb: the statement fails, the script ends non-zero, the
    EXIT trap sees a frame it was told to keep and leaves the PNG, and
    the caller -- correctly reading a non-zero status -- declines to
    append a manifest row.  One frame, no row, and every later count off
    by one.  A `playthrough_log` writing the human-readable record used
    to sit there, and stderr can be closed, full, or a pipe whose reader
    has gone.

    So the commit is TWO ASSIGNMENTS AND AN EXIT, consecutively, and
    that is asserted structurally here as well as behaviourally: an
    ordering guarantee is a property of the source, and a test that can
    only observe it through a race would not hold anyone to it.
    """

    def statements(self):
        """capture.sh's executable lines, comments and blanks removed."""
        with open(os.path.join(TOOLING, "capture.sh"),
                  encoding="utf-8") as handle:
            body = handle.read()
        found = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                found.append(stripped)
        return found

    def test_the_commit_is_two_assignments_and_an_exit(self):
        statements = self.statements()
        self.assertIn("KEPT=1", statements)
        at = statements.index("KEPT=1")
        self.assertEqual(
            statements[at:at + 3],
            ["KEPT=1", 'BACKUP=""', 'exit "${EX_OK}"'],
            msg=("no command may run between the commit and the exit: "
                 "there must be no code path that leaves a kept frame "
                 "behind a non-zero status"))
        self.assertEqual(
            statements.count("KEPT=1"), 1,
            msg="one commit point, so there is one thing to reason about")

    def test_the_human_readable_log_is_taken_before_the_commit(self):
        statements = self.statements()
        logs = [at for at, line in enumerate(statements)
                if line.startswith('playthrough_log "captured')]
        self.assertEqual(
            len(logs), 1,
            msg="the capture is logged once, and in one place")
        self.assertLess(
            logs[0], statements.index("KEPT=1"),
            msg=("the log is the LAST fallible statement, deliberately "
                 "before the commit: while it sat after KEPT=1 a closed "
                 "or full stderr produced exactly the orphan frame the "
                 "invariant cannot tolerate"))

    def test_a_stderr_that_refuses_every_write_leaves_no_orphan(self):
        """The invariant holds however the diagnostics fail.

        /dev/full accepts the descriptor and fails every write, so the
        script's own logging is what breaks.  Either outcome is
        acceptable -- a clean capture, or a refusal -- but the pairing of
        a non-zero status with a frame still in playthrough/frames/ is
        not, because that is the state a caller cannot account for.
        """
        if not os.path.exists("/dev/full"):
            self.skipTest("/dev/full is not present on this host")
        status, out, _ = self.run_capture("1", stderr_to="/dev/full")
        frames = self.frame_files()
        if status == EX_OK:
            self.assertEqual(
                frames, ["frame_00001.png"],
                msg="a zero status means exactly one new frame")
            self.assertIn("FRAME_INDEX=1", out)
        else:
            self.assertEqual(
                frames, [],
                msg=("a non-zero status means the frame was withdrawn: "
                     "no frame exists that no caller was told about"))


class TestTheTrustState(CaptureFixture):
    """A relaxed check cannot produce a frame for the record."""

    # env.sh's registry, which is the single list this gate reads.  Two
    # of these -- the Pillow floor and the compiler -- are nothing to do
    # with capture.sh's own work, and that is the point: the state is one
    # answer about the whole environment the evidence came out of, not a
    # per-script opinion.
    BYPASSES = (
        "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES",
        "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X",
        "PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK",
        "PLAYTHROUGH_ALLOW_TILESET_FALLBACK",
        "PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW",
        "PLAYTHROUGH_ALLOW_ANY_COMPILER",
    )

    def test_the_registry_is_the_one_env_sh_publishes(self):
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c",
             '. "$1" >/dev/null 2>&1; printf "%s" '
             '"$PLAYTHROUGH_TRUST_BYPASS_VARS"',
             "bash", os.path.join(TOOLING, "env.sh")],
            cwd=REPO_ROOT, capture_output=True, timeout=120)
        published = result.stdout.decode("utf-8", "replace").split()
        self.assertEqual(
            sorted(published), sorted(self.BYPASSES),
            msg=("this suite asserts the gate over env.sh's own list, "
                 "so a bypass added there without a test here fails"))

    def test_every_bypass_refuses_a_production_capture(self):
        for name in self.BYPASSES:
            with self.subTest(bypass=name):
                environment = {name: "1"}
                status, out, err = self.run_capture("1", **environment)
                self.assertEqual(
                    status, EX_USAGE,
                    msg="%s must refuse, not warn:\n%s" % (name, err))
                self.assertIn("trust state is 'diagnostic'", err)
                self.assertIn(name, err)
                self.assertEqual(
                    self.frame_files(), [],
                    msg="the refusal precedes the grab entirely")
                self.assertEqual(
                    out, "",
                    msg=("and precedes the payload, so no caller can "
                         "read a contract for a frame that was never "
                         "taken"))

    def test_a_bypass_names_what_it_endangers(self):
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X="1")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("inject keystrokes", err)
        self.assertIn(
            "PLAYTHROUGH_CAPTURE_MODE=diagnostic", err,
            msg="a refusal that leaves no way forward is a dead end")

    def test_a_misspelt_bypass_is_treated_as_set(self):
        """Fail closed on a value the check sites would ignore.

        `=true` does not actually relax anything -- every site tests for
        "1" -- but it is unambiguous evidence that somebody meant to, and
        a recorded session is not the place to be generous about a
        security-relevant variable whose spelling is wrong.
        """
        status, _, err = self.run_capture(
            "1", PLAYTHROUGH_ALLOW_TILESET_FALLBACK="true")
        self.assertEqual(status, EX_USAGE)
        self.assertIn("PLAYTHROUGH_ALLOW_TILESET_FALLBACK", err)

    def test_an_explicit_zero_is_not_a_bypass(self):
        payload, _ = self.capture(
            "1", PLAYTHROUGH_ALLOW_TILESET_FALLBACK="0",
            PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES="0")
        self.assertEqual(payload["CAPTURE_MODE"], "production")
        self.assertEqual(self.frame_files(), ["frame_00001.png"])

    def test_a_diagnostic_capture_may_run_under_a_bypass(self):
        """Diagnosis is separated from the record, not forbidden.

        This is what makes the refusal above acceptable: an operator on a
        host that cannot satisfy a check can still look at a frame, and
        what they get is structurally unusable as evidence -- withdrawn
        out of the working tree, no repository-relative path in the
        payload, and a non-zero status.
        """
        payload, _ = self.diagnostic(
            "1", PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X="1")
        self.assertEqual(payload["FRAME_FILE"], "")
        self.assertEqual(self.frame_files(), [])
        self.assertEqual(self.rejected(), ["frame_00001.png"])


class TestTheSuiteTouchesNoEvidence(CaptureFixture):
    """The committed capture directory is never involved."""

    def test_a_stub_replaces_a_symlink_and_never_the_host_tool(self):
        # The private PATH holds symlinks to real system tools, and
        # some of them are overridden by stubs.  Opening such a name for
        # writing would FOLLOW the link and truncate the host's own
        # binary -- so the link is removed first, and the result is
        # asserted to live inside the sandbox.
        target = shutil.which("date")
        self.assertIsNotNone(target)
        before = os.stat(target)
        link = os.path.join(self.bin, "date")
        self.assertTrue(os.path.islink(link))
        self.stub("date", 'printf "x\\n"\n')
        self.assertFalse(os.path.islink(link))
        after = os.stat(target)
        self.assertEqual((before.st_size, before.st_mtime),
                         (after.st_size, after.st_mtime),
                         msg="the host's date(1) must be untouched")
        self.assertTrue(
            os.path.realpath(link).startswith(
                os.path.realpath(self.root)))

    def test_the_real_frames_directory_is_untouched(self):
        real = os.path.join(PLAYTHROUGH, "frames")
        before = (sorted(os.listdir(real))
                  if os.path.isdir(real) else None)
        self.capture("1")
        after = (sorted(os.listdir(real))
                 if os.path.isdir(real) else None)
        self.assertEqual(
            after, before,
            msg=("every run happens inside a sandbox checkout, so the "
                 "committed frames cannot be written to"))

    def test_the_sandbox_really_is_where_the_frame_landed(self):
        payload, _ = self.capture("1")
        self.assertTrue(
            payload["FRAME_PATH"].startswith(self.root),
            msg=("env.sh resolves every path from its own location, "
                 "which is what makes a sandbox test possible: %s"
                 % payload["FRAME_PATH"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
