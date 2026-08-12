#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/env.sh.

env.sh is the single definition of the headless render environment, and
one line in it is the difference between a real film and a black one:

    export SDL_VIDEODRIVER=x11

The dummy video backend renders zero pixels.  With it set, the game
still runs, every keystroke still lands, `import -window root` still
writes a PNG, ffmpeg still encodes, and every acceptance count still
matches -- the only symptom is that the finished movie shows nothing.
Written as "${SDL_VIDEODRIVER:-x11}" instead of an unconditional
export, a caller who already had dummy in their environment would
silently win.  So the override is asserted here against a shell that
was deliberately poisoned with dummy first.

    python3 playthrough/tooling/test_env.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

HOW A SHELL LIBRARY IS TESTED FROM PYTHON
Every test sources the REAL file in a pristine shell --

    env -i /bin/bash --noprofile --norc -c '. env.sh; ...; env -0'

-- with an explicit PATH and nothing else inherited, then parses the
NUL-separated environment the source produced.  Because `env` lists
only EXPORTED variables, the dump is itself the assertion that a value
reaches a child process rather than merely existing in the shell.  A
marker printed between the source and the dump separates any source-time
stdout from the dump, which is how "sourcing must stay silent" is
checked: a consumer captures stdout, so one stray line would corrupt it.

WHAT IS ASSERTED
* THE RENDERING CONTRACT -- x11 overriding a pre-set dummy, the audio
  driver that legitimately IS dummy, software GL, and the two Python
  variables, one of which (PYTHONDONTWRITEBYTECODE) is load-bearing
  because `!/playthrough/**` re-includes __pycache__.
* THE CLONE INDEX -- an absent index means zero and an explicit bad one
  is REFUSED, never coerced, because coercing it would route a clone
  onto the canonical display and into another clone's frames.  "010" is
  ten, not octal eight.
* XDG_RUNTIME_DIR -- created before it is exported, and mode 0700.
* THE ARTIFACT LAYOUT -- every path derived from the file's own location
  via BASH_SOURCE, so the answer does not depend on the caller's working
  directory; and the two command-line forms that must stay RELATIVE,
  because the engine resolves --userdir against the process working
  directory.
* SOURCING IS INERT AND IDEMPOTENT -- no process is started, nothing is
  written into the working tree, PATH is never touched, two sources
  produce a byte-identical environment, and no scratch name is left
  behind in the caller's shell.
* THE GUARD IS LIVE -- a deliberately sabotaged COPY of the file, with
  x11 replaced by dummy, is refused at source time.  That is the
  regression the final assertion exists for, and it is proved rather
  than assumed.

Nothing in the repository is written.  The only host-global effect is
/tmp/xdg (which the contract owns and which is created idempotently) and
/tmp/xdg91 for the clone-index tests, which is removed again if this
suite created it.
"""

import hashlib
import os
import re
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
ENV_SH = os.path.join(TOOLING, "env.sh")
REQUIREMENTS = os.path.join(TOOLING, "requirements.txt")
REQUIREMENTS_LOCK = os.path.join(TOOLING, "requirements.lock")
# The interpreter the closure checker is measured against: the one the
# pipeline actually runs, because the checker's first verdict is about the
# ABI and asking a different interpreter would measure a different
# environment.  sys.executable is that interpreter -- these tests run
# under it.
PYTHON = sys.executable

# The one line in playthrough_secure_dir that READS the mode back after
# the chmod.  Two tests below replace it wholesale to stand in for a
# filesystem that accepted the chmod and did nothing, so the anchor has
# to be the file's exact text -- including the line continuation, since
# the reading goes through the verified `stat` resolved into
# PLAYTHROUGH_UTIL_STAT rather than through whatever `stat` PATH offers.
# Kept here as one constant so the two tests cannot drift apart from
# each other, and so a future edit to env.sh fails loudly in
# sabotaged_copy()'s uniqueness assertion instead of silently sabotaging
# nothing.
READ_ACTUAL_MODE = (
    '    actual="$("${PLAYTHROUGH_UTIL_STAT}" -Lc \'%a\' '
    '-- "${path}" \\\n'
    '        2>/dev/null || true)"')

# A deliberately ordinary PATH: nothing from the test runner's own
# environment is inherited, so every command the file uses has to be
# found here or not at all.
BASE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Printed between the source and the environment dump.
MARKER = "<<<PLAYTHROUGH-ENV-DUMP>>>"

# A clone index far from any real run, used for the offset tests.
SPARE_INDEX = 91


def unsafe_ancestor(path):
    """The first group/world-writable non-sticky directory at or above
    `path`, or None when every one of them is safe.

    The Python twin of env.sh's playthrough_untrusted_ancestor, and it
    exists so the anchor-selection tests can assert the branch THIS host
    actually takes instead of hard-coding an answer that is only true
    where /tmp is mode 2777.  Both walk to '/', and both treat the sticky
    bit as the deciding property: in a world-writable directory WITHOUT
    it any account may rename any entry regardless of owner, and with it
    only the entry's owner may -- which is why a private tree under a
    conventional 1777 /tmp is not a finding.
    """
    entry = os.path.realpath(path)
    while True:
        try:
            mode = os.stat(entry).st_mode
        except OSError:
            mode = None
        if mode is not None and (mode & 0o022) and not (mode & stat.S_ISVTX):
            return entry
        if entry == "/":
            return None
        entry = os.path.dirname(entry) or "/"


# The contract's own values, restated so that changing one has to be a
# deliberate change to the contract rather than a silent one.
CONTRACT = {
    "SDL_VIDEODRIVER": "x11",
    "SDL_AUDIODRIVER": "dummy",
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}

TUNABLES = {
    "PLAYTHROUGH_SCREEN_WIDTH": "1920",
    "PLAYTHROUGH_SCREEN_HEIGHT": "1080",
    "PLAYTHROUGH_SCREEN_DEPTH": "24",
    "PLAYTHROUGH_SCREEN": "1920x1080x24",
    "PLAYTHROUGH_WINDOW_CLASS": "cataclysm-tiles",
    "PLAYTHROUGH_TERMINAL_X": "240",
    "PLAYTHROUGH_TERMINAL_Y": "67",
    "PLAYTHROUGH_FONT_WIDTH": "8",
    "PLAYTHROUGH_FONT_HEIGHT": "16",
    "PLAYTHROUGH_SIDEBAR_CELLS": "44",
    "PLAYTHROUGH_SIDEBAR_LAYOUT": "legacy_labels_sidebar",
    "PLAYTHROUGH_TILESET": "MshockXottoplus",
    "PLAYTHROUGH_SETTLE_SECONDS": "0.3",
    "PLAYTHROUGH_FRAME_FORMAT": "frame_%05d.png",
    "PLAYTHROUGH_TRANSITION_FORMAT": "trans_%05d_%02d.png",
    "PLAYTHROUGH_MAX_CLONE_INDEX": "99",
}

# The functions the file promises to define.  A consumer calls these by
# name, so losing one is a broken contract even though nothing runs at
# source time.
HELPERS = (
    "playthrough_log",
    "playthrough_warn",
    "playthrough_die",
    "playthrough_assert_video_driver",
    "playthrough_tool_package",
    "playthrough_require_tools",
    "playthrough_display_probe",
    "playthrough_display_ready",
    "playthrough_wait_for_display",
    "playthrough_spawn_detached",
    "playthrough_start_xvfb",
    "playthrough_start_wm",
    "playthrough_assert_display",
    "playthrough_headless_up",
    "playthrough_mkdirs",
    # The lock name a checkout takes.  In the inventory because two
    # sibling scripts CALL it by name -- run_pipeline.sh and
    # commit_artifacts.sh both derive their lock from it -- so losing it
    # is a broken contract even though nothing runs at source time.
    "playthrough_checkout_lock_name",
    "playthrough_python",
    "playthrough_env_summary",
    "playthrough_trust_reason",
    "playthrough_trust_refresh",
    "playthrough_trust_explain",
    "playthrough_assert_trusted",
    "playthrough_trust_unverifiable",
    "playthrough_trusted_util",
    "playthrough_assert_utilities",
)

# Every field playthrough_env_summary() promises to print.  The list is
# spelled out rather than counted because a truncated report is the
# failure this guards against, and a count is exactly what a truncated
# report can still satisfy: a run that dropped the last five fields
# still printed thirty lines.  Two of the five that were dropped are
# security controls -- IMAGEIO_FFMPEG_EXE, which is what stops the
# encoder bundled inside a wheel from being the one that renders, and
# PLAYTHROUGH_PLATFORM_SUPPORTED, which is the end-of-life warning
# surface -- so an operator reading the report to check either one saw
# nothing at all and could not tell "unset" from "unprinted".
SUMMARY_FIELDS = (
    "DISPLAY",
    "SDL_VIDEODRIVER",
    "SDL_AUDIODRIVER",
    "LIBGL_ALWAYS_SOFTWARE",
    "XDG_RUNTIME_DIR",
    "XAUTHORITY",
    "PYTHONDONTWRITEBYTECODE",
    "IMAGEIO_FFMPEG_EXE",
    "PLAYTHROUGH_CLONE_INDEX",
    "PLAYTHROUGH_RUNTIME_DIR",
    "PLAYTHROUGH_XAUTHORITY_ORIGIN",
    "PLAYTHROUGH_PLATFORM",
    # WHICH FILE the platform facts came from, once.  Normally
    # /etc/os-release; a harness may nominate another through
    # PLAYTHROUGH_OS_RELEASE to emulate a host it is not running on, and
    # that nomination is honoured only in a tree git does not track -- so
    # this line is what says whether the verdict beside it is about this
    # host, and a verdict from elsewhere is still one the record carries.
    "PLAYTHROUGH_PLATFORM_SOURCE",
    "PLAYTHROUGH_PLATFORM_SUPPORTED",
    # The end-of-life date and the waiver reason travel with the record
    # because the platform gate is a REFUSAL by default: a session that
    # ran on an out-of-support host did so under a named waiver, and the
    # contract is where that fact has to be readable afterwards.
    "PLAYTHROUGH_PLATFORM_EOL",
    "PLAYTHROUGH_PLATFORM_WAIVER",
    "PLAYTHROUGH_SCREEN",
    "PLAYTHROUGH_WINDOW_CLASS",
    "PLAYTHROUGH_TILESET",
    "PLAYTHROUGH_SIDEBAR_LAYOUT",
    "PLAYTHROUGH_SIDEBAR_CELLS",
    "PLAYTHROUGH_REPO_ROOT",
    "PLAYTHROUGH_DIR",
    "PLAYTHROUGH_FRAMES_DIR",
    "PLAYTHROUGH_BUILD_DIR",
    "PLAYTHROUGH_TRANSITIONS_DIR",
    "PLAYTHROUGH_USERDIR",
    "PLAYTHROUGH_USERDIR_ARG",
    "PLAYTHROUGH_MANIFEST",
    # The two out-of-band ledgers the record cannot carry itself: a
    # correction bound to the sha256 of the line it corrects, and the
    # captured bytes of every frame.  Both are in the contract because
    # both are evidence a reader has to be able to find.
    "PLAYTHROUGH_AMENDMENTS",
    "PLAYTHROUGH_OBSERVATIONS",
    "PLAYTHROUGH_DATE_AUDIT",
    "PLAYTHROUGH_FRAME_DIGESTS",
    "PLAYTHROUGH_TIMELINE",
    "PLAYTHROUGH_MOVIE",
    "PLAYTHROUGH_MOVIE_CC",
    "PLAYTHROUGH_SUPERVISOR_XVFB",
    "PLAYTHROUGH_SUPERVISOR_WM",
    "PLAYTHROUGH_PYTHON",
    "PLAYTHROUGH_PYTHON_VERSION",
    "PLAYTHROUGH_PYTHON_ABI",
    "PLAYTHROUGH_TRUST_STATE",
    "PLAYTHROUGH_TRUST_BYPASSES",
    "PLAYTHROUGH_TRUST_UNVERIFIED",
    "PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR",
)


class Sourced(object):
    """The result of sourcing env.sh in a pristine shell."""

    def __init__(self, status, environment, source_output, stderr):
        self.status = status
        self.environment = environment
        self.source_output = source_output
        self.stderr = stderr

    def __getitem__(self, name):
        return self.environment[name]

    def get(self, name, default=None):
        return self.environment.get(name, default)


def env_source():
    """env.sh's text, read once and cached.

    Several tests below assert on the SOURCE rather than on behaviour --
    that a refusal is written separately from its neighbour, that a check
    precedes the signal it guards. Those are properties of the file.
    """
    global _ENV_SOURCE
    if _ENV_SOURCE is None:
        with open(ENV_SH, encoding="utf-8") as handle:
            _ENV_SOURCE = handle.read()
    return _ENV_SOURCE


_ENV_SOURCE = None


class EnvFixture(unittest.TestCase):
    """Sources env.sh under a controlled, empty environment."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_env_")
        self.addCleanup(shutil.rmtree, self.root, True)

    def forget_record(self):
        """Remove the spare display's ownership record if it exists.

        THE RECORD IS SHARED STATE OUTSIDE ANY FIXTURE'S TEMPORARY
        DIRECTORY, so it is the one thing in this file that leaks from one
        test into the next, and it lives on the base class because more
        than one class writes it.

        This is not hypothetical tidiness. It produced a genuinely
        misleading test: at HEAD, a test that recorded ownership sorted
        alphabetically before
        test_a_foreign_display_holds_the_trust_state_at_diagnostic and
        left its record behind, so the "foreign" test ran with a record
        present, took the STALE branch, and passed against the stale
        branch's wording. Renaming the earlier test reordered the two and
        the foreign test began measuring the arm its name claims -- and
        failed, because the phrase it asserted appears only in the stale
        message. The assertion had been green for the wrong reason.

        ITS PATH IS ASKED OF env.sh RATHER THAN SPELLED HERE, because the
        runtime anchor is chosen at source time: it resolves under /run
        when a root-owned /run path is available and under /tmp otherwise.
        A hardcoded path removes nothing and leaves the stale record in
        place, which is how the above stayed hidden.
        """
        self.source(
            preset={"CLONE_INDEX": str(SPARE_INDEX)},
            after='rm -f -- "$(playthrough_x_ownership_record)"\n')

    def field(self, result, marker):
        """The text inside the first `MARKER[...]` line on stderr."""
        for line in result.stderr.splitlines():
            if line.startswith(marker) and line.endswith("]"):
                return line[len(marker):-1]
        return ""

    # -- the harness -------------------------------------------------

    def source(self, script=ENV_SH, preset=None, cwd=REPO_ROOT,
               path=BASE_PATH, after=""):
        """Source ``script`` in a pristine shell and report the result.

        :param preset: variables the calling shell already carries --
            the poisoned-environment cases live here.
        :param after: extra shell run after the source and before the
            dump, for exercising a helper function.
        :returns: a :class:`Sourced`.
        """
        program = (
            'set +e\n'
            '. "$1"\n'
            'status=$?\n'
            '%s\n'
            'printf "%%s" "%s"\n'
            'if [ "$status" -eq 0 ]; then env -0; fi\n'
            'exit "$status"\n' % (after, MARKER))
        environment = {"PATH": path}
        if preset:
            environment.update(preset)
        result = subprocess.run(
            ["/usr/bin/env", "-i"] + [
                "%s=%s" % (name, value)
                for name, value in environment.items()
            ] + ["/bin/bash", "--noprofile", "--norc", "-c", program,
                 "bash", script],
            cwd=cwd, capture_output=True, timeout=120)
        stdout = result.stdout.decode("utf-8", "replace")
        head, _, tail = stdout.partition(MARKER)
        parsed = {}
        for item in tail.split("\0"):
            if not item:
                continue
            name, _, value = item.partition("=")
            parsed[name] = value
        return Sourced(result.returncode, parsed, head,
                       result.stderr.decode("utf-8", "replace"))

    def sourced(self, **kwargs):
        """Source and require success."""
        result = self.source(**kwargs)
        self.assertEqual(
            result.status, 0,
            msg="sourcing failed: %s" % result.stderr)
        return result

    # -- fixtures ----------------------------------------------------

    def sandbox_checkout(self, name="checkout", valid=True):
        """A directory that env.sh will or will not accept as a root."""
        root = os.path.join(self.root, name)
        tooling = os.path.join(root, "playthrough", "tooling")
        os.makedirs(tooling)
        if valid:
            os.makedirs(os.path.join(root, "data"))
            os.makedirs(os.path.join(root, "src"))
            with open(os.path.join(root, "src", "path_info.cpp"), "w",
                      encoding="utf-8") as handle:
                handle.write("// a marker, not the engine\n")
        copy = os.path.join(tooling, "env.sh")
        shutil.copyfile(ENV_SH, copy)
        return root, copy

    def sabotaged_copy(self, old, new, name="sabotage"):
        """A sandbox copy of env.sh with one line replaced."""
        root, copy = self.sandbox_checkout(name)
        with open(copy, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(
            text.count(old), 1,
            msg="the line to sabotage must be unique: %r" % old)
        with open(copy, "w", encoding="utf-8") as handle:
            handle.write(text.replace(old, new, 1))
        return root, copy

    def thin_path(self):
        """A PATH holding only the commands env.sh itself needs.

        Nothing from the pipeline's toolchain is reachable through it --
        no Xvfb, no openbox, no xdotool, no ImageMagick -- which is how
        "sourcing starts nothing" is proved rather than asserted.
        """
        holder = os.path.join(self.root, "thin-bin")
        os.makedirs(holder, exist_ok=True)
        for tool in ("env", "mkdir", "chmod", "cat", "readlink",
                     "dirname", "pwd"):
            resolved = shutil.which(tool)
            if resolved:
                link = os.path.join(holder, tool)
                if not os.path.exists(link):
                    os.symlink(resolved, link)
        return holder

    def spare_runtime_dir(self):
        """/tmp/xdg<SPARE_INDEX>, created, removed if we made it.

        IT IS CREATED HERE RATHER THAN LEFT TO env.sh, and that is now
        load-bearing rather than convenience.  The anchor is chosen from
        an ordered list (see THE ANCHOR IS CHOSEN in env.sh): the
        conventional /tmp/xdg<suffix> wins whenever it is trusted OR
        already present, and only a road that is BOTH unsafe and carries
        no live state sends the run to /run instead.  On a host whose
        /tmp is 2777 the second condition is the deciding one, so a test
        that wants the conventional anchor has to make it exist -- and a
        test that wants the /run branch removes it, which
        test_an_unsafe_road_with_nothing_to_orphan_moves_to_run does.
        """
        path = "/tmp/xdg%d" % SPARE_INDEX
        if not os.path.exists(path):
            self.addCleanup(shutil.rmtree, path, True)
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
        return path


class TestTheRenderingContract(EnvFixture):
    """One variable may be dummy, and it is not the video driver."""

    def test_the_video_driver_is_x11(self):
        self.assertEqual(self.sourced()["SDL_VIDEODRIVER"], "x11")

    def test_a_caller_who_already_had_dummy_does_not_win(self):
        result = self.sourced(
            preset={"SDL_VIDEODRIVER": "dummy"})
        self.assertEqual(
            result["SDL_VIDEODRIVER"], "x11",
            msg=('the export is unconditional, NOT '
                 '"${SDL_VIDEODRIVER:-x11}": a default would let a '
                 "poisoned environment through, and the dummy backend "
                 "renders zero pixels while every count still matches"))

    def test_any_other_pre_set_driver_is_overwritten_too(self):
        for value in ("offscreen", "wayland", "", "X11", "kmsdrm"):
            with self.subTest(preset=value):
                self.assertEqual(
                    self.sourced(
                        preset={"SDL_VIDEODRIVER": value}
                    )["SDL_VIDEODRIVER"],
                    "x11")

    def test_the_audio_driver_is_the_one_that_may_be_dummy(self):
        result = self.sourced()
        self.assertEqual(
            result["SDL_AUDIODRIVER"], "dummy",
            msg=("a headless host has no audio device and the game runs "
                 "with SOUND_ENABLED=false, so the null audio backend "
                 "is exactly right"))
        self.assertNotEqual(result["SDL_VIDEODRIVER"],
                            result["SDL_AUDIODRIVER"])

    def test_software_rendering_is_forced(self):
        self.assertEqual(
            self.sourced()["LIBGL_ALWAYS_SOFTWARE"], "1",
            msg=("no GPU exists on a headless host, and GL "
                 "initialisation otherwise fails or falls back "
                 "inconsistently between launches"))

    def test_python_writes_no_bytecode(self):
        self.assertEqual(
            self.sourced()["PYTHONDONTWRITEBYTECODE"], "1",
            msg=("load-bearing, not hygiene: .gitignore's terminal "
                 "!/playthrough/** re-includes "
                 "playthrough/tooling/__pycache__/*.pyc, and that "
                 "negation has to stay last for the save data to be "
                 "tracked at all"))

    def test_python_output_is_unbuffered(self):
        self.assertEqual(self.sourced()["PYTHONUNBUFFERED"], "1")

    def test_every_contract_value_reaches_a_child_process(self):
        result = self.sourced()
        for name, value in CONTRACT.items():
            with self.subTest(variable=name):
                self.assertEqual(
                    result.get(name), value,
                    msg=("`env` lists only EXPORTED variables, so this "
                         "is the assertion that a child process sees "
                         "it"))

    def test_the_guard_accepts_the_contract(self):
        result = self.sourced(
            after='playthrough_assert_video_driver'
                  ' && export GUARD_STATUS=ok')
        self.assertEqual(result.get("GUARD_STATUS"), "ok")

    def test_the_guard_refuses_a_driver_changed_after_sourcing(self):
        result = self.sourced(
            after='export SDL_VIDEODRIVER=dummy\n'
                  'if playthrough_assert_video_driver; then\n'
                  '    export GUARD_STATUS=accepted\n'
                  'else\n'
                  '    export GUARD_STATUS=refused\n'
                  'fi')
        self.assertEqual(
            result.get("GUARD_STATUS"), "refused",
            msg=("stages call this at the point of use, so an override "
                 "applied after sourcing is still caught"))
        self.assertIn("renders zero pixels", result.stderr)
        self.assertIn("entirely black", result.stderr)

    def test_a_sabotaged_copy_is_refused_at_source_time(self):
        # THE regression the file's closing assertion exists for.
        root, copy = self.sabotaged_copy(
            "export SDL_VIDEODRIVER=x11",
            "export SDL_VIDEODRIVER=dummy")
        result = self.source(script=copy, cwd=root)
        self.assertNotEqual(
            result.status, 0,
            msg=("a contract that somehow does not carry x11 must not "
                 "leave this file quietly"))
        self.assertIn("FATAL", result.stderr)
        self.assertIn("not 'x11'", result.stderr)
        self.assertEqual(
            result.environment, {},
            msg="the source aborted, so no environment was produced")


class TestTheCloneIndex(EnvFixture):
    """An absent index means zero; a bad one is refused, not coerced."""

    def test_no_index_is_the_canonical_single_checkout_contract(self):
        result = self.sourced()
        self.assertEqual(result["PLAYTHROUGH_CLONE_INDEX"], "0")
        self.assertEqual(result["DISPLAY"], ":99")
        self.assertEqual(result["PLAYTHROUGH_DISPLAY"], ":99")
        self.assertEqual(result["PLAYTHROUGH_DISPLAY_NUM"], "99")
        self.assertEqual(result["XDG_RUNTIME_DIR"], "/tmp/xdg")
        # EVERY SCRATCH FILE LIVES INSIDE THE VERIFIED RUNTIME
        # DIRECTORY, never at a predictable /tmp/<name>.  A world-
        # writable name is exactly how another account pre-plants a
        # symlink and redirects a truncating write; the directory is
        # created mode 0700, owner-checked, and symlink-refused, so
        # confinement to it is the control and the unsuffixed names
        # inside it are then safe.
        self.assertEqual(result["PLAYTHROUGH_RUNTIME_DIR"],
                         "/tmp/xdg/playthrough")
        # Diagnostics, pid files, locks and withdrawn frames are sorted
        # into four subdirectories of that root, each verified the same
        # way: a rejected screenshot is a full-resolution capture of the
        # session and the X cookie is a credential, so neither belongs
        # in the same directory as a log an operator tails.
        self.assertEqual(result["PLAYTHROUGH_LOG_DIR"],
                         "/tmp/xdg/playthrough/log")
        self.assertEqual(result["PLAYTHROUGH_RUN_DIR"],
                         "/tmp/xdg/playthrough/run")
        self.assertEqual(result["PLAYTHROUGH_LOCK_DIR"],
                         "/tmp/xdg/playthrough/lock")
        self.assertEqual(result["PLAYTHROUGH_REJECT_DIR"],
                         "/tmp/xdg/playthrough/rejected")
        self.assertEqual(
            result["PLAYTHROUGH_GAME_LOG"],
            "/tmp/xdg/playthrough/log/cata-play.log",
            msg="index 0 uses the plain, unsuffixed scratch names")
        self.assertEqual(result["PLAYTHROUGH_XVFB_LOG"],
                         "/tmp/xdg/playthrough/log/xvfb.log")
        self.assertEqual(result["PLAYTHROUGH_WM_LOG"],
                         "/tmp/xdg/playthrough/log/openbox.log")
        self.assertEqual(result["PLAYTHROUGH_XVFB_PIDFILE"],
                         "/tmp/xdg/playthrough/run/xvfb.pid")
        self.assertEqual(
            result["PLAYTHROUGH_XAUTHORITY"],
            "/tmp/xdg/playthrough/Xauthority",
            msg=("the cookie is a credential and lives in the private "
                 "root, at mode 0600"))
        self.assertEqual(result["PLAYTHROUGH_SUPERVISOR_XVFB"],
                         "playthrough-xvfb")
        self.assertEqual(result["PLAYTHROUGH_SUPERVISOR_WM"],
                         "playthrough-openbox")

    def test_an_explicit_zero_is_the_same_as_no_index(self):
        bare = dict(self.sourced().environment)
        bare.pop("CLONE_INDEX", None)
        for value in ("0", "00", "000"):
            with self.subTest(index=value):
                observed = dict(
                    self.sourced(
                        preset={"CLONE_INDEX": value}).environment)
                # CLONE_INDEX itself is the caller's variable, not part
                # of the contract this file exports; every value it
                # DERIVES is what has to match.
                observed.pop("CLONE_INDEX", None)
                self.assertEqual(
                    observed, bare,
                    msg=("normalised with 10#, so a zero-padded value "
                         "is decimal zero and not octal"))

    def test_an_index_offsets_the_display_and_every_scratch_path(self):
        self.spare_runtime_dir()
        result = self.sourced(
            preset={"CLONE_INDEX": str(SPARE_INDEX)})
        self.assertEqual(result["PLAYTHROUGH_CLONE_INDEX"],
                         str(SPARE_INDEX))
        self.assertEqual(result["DISPLAY"], ":%d" % (99 + SPARE_INDEX))
        self.assertEqual(result["XDG_RUNTIME_DIR"],
                         "/tmp/xdg%d" % SPARE_INDEX)
        # The index moves the whole runtime directory, so the scratch
        # names inside it need no suffix of their own.
        self.assertEqual(result["PLAYTHROUGH_RUNTIME_DIR"],
                         "/tmp/xdg%d/playthrough" % SPARE_INDEX)
        self.assertEqual(
            result["PLAYTHROUGH_GAME_LOG"],
            "/tmp/xdg%d/playthrough/log/cata-play.log" % SPARE_INDEX)
        self.assertEqual(
            result["PLAYTHROUGH_XVFB_PIDFILE"],
            "/tmp/xdg%d/playthrough/run/xvfb.pid" % SPARE_INDEX)
        self.assertEqual(
            result["PLAYTHROUGH_XAUTHORITY"],
            "/tmp/xdg%d/playthrough/Xauthority" % SPARE_INDEX,
            msg=("two clones must not share one cookie: each display "
                 "gets its own, in its own private root"))
        self.assertEqual(
            result["PLAYTHROUGH_SUPERVISOR_XVFB"],
            "playthrough-xvfb%d" % SPARE_INDEX)

    def test_a_zero_padded_index_is_decimal_not_octal(self):
        self.spare_runtime_dir()
        result = self.sourced(preset={"CLONE_INDEX": "010"})
        self.assertEqual(
            result["PLAYTHROUGH_CLONE_INDEX"], "10",
            msg=("without 10# bash would read 010 as octal 8 and route "
                 "this clone onto display :107 while it believed it "
                 "was on :109"))
        self.assertEqual(result["DISPLAY"], ":109")

    def test_the_maximum_index_is_accepted(self):
        result = self.sourced(preset={"CLONE_INDEX": "99"})
        self.assertEqual(result["DISPLAY"], ":198")

    def test_an_index_above_the_maximum_is_refused(self):
        result = self.source(preset={"CLONE_INDEX": "100"})
        self.assertNotEqual(result.status, 0)
        self.assertIn("above the maximum", result.stderr)
        self.assertIn(
            "refused rather than clamped", result.stderr,
            msg=("a clamped index would collide with whichever clone "
                 "genuinely holds the clamped value"))

    def test_an_index_that_is_not_a_number_is_refused(self):
        for value in ("abc", "-1", "1.5", "1 2", " 1", "1a", "0x10",
                      "+1", ""):
            with self.subTest(index=value):
                result = self.source(preset={"CLONE_INDEX": value})
                self.assertNotEqual(
                    result.status, 0,
                    msg="%r must be refused" % value)
                self.assertIn("CLONE_INDEX", result.stderr)

    def test_the_refusal_says_why_coercing_would_be_worse(self):
        result = self.source(preset={"CLONE_INDEX": "twelve"})
        self.assertIn("refused rather than", result.stderr)
        self.assertIn(
            "canonical", result.stderr,
            msg=("index 0 owns DISPLAY=:99 and the unsuffixed /tmp "
                 "paths, so a coerced index walks into the resources "
                 "of the clone that really is 0"))

    def test_a_refused_index_exports_no_display_at_all(self):
        result = self.source(preset={"CLONE_INDEX": "9999"})
        self.assertEqual(
            result.environment, {},
            msg=("the value is validated BEFORE any shared resource "
                 "path is derived from it"))

    def test_the_index_is_validated_before_the_runtime_dir_is_made(self):
        stray = "/tmp/xdg9999"
        self.assertFalse(os.path.exists(stray))
        self.source(preset={"CLONE_INDEX": "9999"})
        self.assertFalse(
            os.path.exists(stray),
            msg="nothing host-global is created for an index that was "
                "refused")


class TestTheRuntimeDirectory(EnvFixture):
    """Created before it is exported, and private."""

    def test_the_runtime_directory_exists_after_sourcing(self):
        result = self.sourced()
        self.assertTrue(os.path.isdir(result["XDG_RUNTIME_DIR"]))

    def test_the_runtime_directory_is_private(self):
        result = self.sourced()
        mode = os.stat(result["XDG_RUNTIME_DIR"]).st_mode & 0o777
        self.assertEqual(
            mode, 0o700,
            msg=("SDL, Mesa and dbus all refuse or warn on a "
                 "world-readable runtime directory"))

    def test_a_missing_runtime_directory_is_created_not_assumed(self):
        """Whichever anchor is chosen, it EXISTS at 0700 afterwards.

        The path is read out of the result rather than predicted, because
        which candidate wins depends on the host's /tmp: see
        spare_runtime_dir.  What is invariant -- and what this asserts --
        is that env.sh does not assume an anchor into existence.
        """
        path = self.spare_runtime_dir()
        shutil.rmtree(path, True)
        self.assertFalse(os.path.exists(path))
        result = self.sourced(
            preset={"CLONE_INDEX": str(SPARE_INDEX)})
        chosen = result["XDG_RUNTIME_DIR"]
        self.addCleanup(shutil.rmtree, chosen, True)
        self.assertTrue(os.path.isdir(chosen))
        self.assertEqual(os.stat(chosen).st_mode & 0o777, 0o700)
        self.assertEqual(result["PLAYTHROUGH_RUNTIME_DIR"],
                         os.path.join(chosen, "playthrough"))

    def test_an_unsafe_road_with_nothing_to_orphan_moves_to_run(self):
        """The /run branch, on a host whose /tmp is 2777 non-sticky.

        A security review found the ancestry of the runtime anchor
        measured nowhere.  It is measured now, and when the conventional
        address is BOTH unreachable-safely and empty of live state the
        run anchors under the root-owned /run instead -- where the whole
        road is owner-controlled.  On a host with a conventional 1777
        /tmp there is nothing to move away from, and this asserts that
        case too rather than skipping it.
        """
        legacy = "/tmp/xdg%d" % SPARE_INDEX
        shutil.rmtree(legacy, True)
        self.assertFalse(os.path.exists(legacy))
        result = self.sourced(
            preset={"CLONE_INDEX": str(SPARE_INDEX)})
        chosen = result["XDG_RUNTIME_DIR"]
        self.addCleanup(shutil.rmtree, chosen, True)
        if unsafe_ancestor("/tmp") is None:
            self.assertEqual(
                chosen, legacy,
                msg="a trusted /tmp is not a road worth moving away from")
            self.assertEqual(
                result["PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR"], "")
            return
        self.assertEqual(
            chosen,
            "/run/playthrough-%d%d" % (os.geteuid(), SPARE_INDEX),
            msg="an unsafe road with nothing to orphan anchors under /run")
        self.assertEqual(
            result["PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR"], "",
            msg="and the chosen anchor's own road is then clean")
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")

    def test_an_existing_unsafe_road_is_kept_and_measured(self):
        """Continuity wins, and the fact is not swallowed.

        The anchor holds the X cookie, the pid of a running server, the
        locks and any in-flight journal, so moving it out from under a
        live session would orphan all of it.  It is kept -- and the
        unsafe road is MEASURED and exported, which is what
        playthrough_check_path_ancestry refuses on at launch.

        Sourcing stays silent about it deliberately: this file is sourced
        into the caller's shell and sourcing is inert, so the fact is
        published and the refusal belongs to the stage that is about to
        produce evidence.  See TestThePathAncestryGate.
        """
        if unsafe_ancestor("/tmp") is None:
            self.skipTest("this host's /tmp is not a world-writable "
                          "non-sticky directory, so there is no unsafe "
                          "road to keep")
        path = self.spare_runtime_dir()
        result = self.sourced(
            preset={"CLONE_INDEX": str(SPARE_INDEX)})
        self.assertEqual(result["XDG_RUNTIME_DIR"], path)
        self.assertEqual(
            result["PLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR"], "/tmp")
        self.assertEqual(result.stderr, "",
                         msg="sourcing reports it by export, not by "
                             "printing")

    def test_a_nominated_anchor_is_used_and_never_fallen_back_from(self):
        nominated = os.path.join(self.root, "nominated-anchor")
        os.makedirs(nominated, mode=0o700)
        result = self.sourced(
            preset={"PLAYTHROUGH_XDG_ANCHOR": nominated})
        self.assertEqual(result["XDG_RUNTIME_DIR"], nominated)

    def test_a_nomination_that_cannot_be_used_is_fatal(self):
        """A silent fallback would put the credential somewhere else."""
        blocker = os.path.join(self.root, "anchor-in-the-way")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("in the way\n")
        result = self.source(
            preset={"PLAYTHROUGH_XDG_ANCHOR": blocker})
        self.assertNotEqual(result.status, 0)
        self.assertIn("PLAYTHROUGH_XDG_ANCHOR", result.stderr)
        self.assertIn("not fallen back from", result.stderr)

    def test_an_existing_directory_is_tightened_rather_than_trusted(self):
        path = self.spare_runtime_dir()
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o777)
        self.sourced(preset={"CLONE_INDEX": str(SPARE_INDEX)})
        self.assertEqual(
            os.stat(path).st_mode & 0o777, 0o700,
            msg="a directory left over from another run is not trusted")

    def test_a_runtime_directory_that_cannot_be_made_is_fatal(self):
        """BOTH candidates are blocked, because either one would do.

        The anchor is chosen from an ordered list now, so sabotaging only
        the conventional address would simply send the run to the /run
        candidate and prove nothing.  Both are pointed at a regular file,
        which no `mkdir -p` can turn into a directory.
        """
        blocker = os.path.join(self.root, "not-a-dir")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("in the way\n")
        root, copy = self.sabotaged_copy(
            '_playthrough_legacy_anchor="/tmp/xdg${_playthrough_suffix}"',
            '_playthrough_legacy_anchor="%s/in/the/way"' % blocker,
            name="blocked")
        with open(copy, encoding="utf-8") as handle:
            text = handle.read()
        run_candidate = ('_playthrough_runtime_dir=\\\n'
                         '"/run/playthrough-$(_playthrough_euid)'
                         '${_playthrough_suffix}"')
        self.assertEqual(
            text.count(run_candidate), 1,
            msg="the /run candidate must be a single, unique line")
        with open(copy, "w", encoding="utf-8") as handle:
            handle.write(text.replace(
                run_candidate,
                '_playthrough_runtime_dir="%s/in/the/way"' % blocker, 1))
        result = self.source(script=copy, cwd=root)
        self.assertNotEqual(result.status, 0)
        self.assertIn("cannot create", result.stderr)

    def setgid_parent(self, name="setgid"):
        """A directory carrying the set-group-ID bit, as /tmp does here.

        A child created inside it inherits setgid, which is the whole
        point: this reproduces the real host condition rather than
        describing it.

        IT LIVES BENEATH THE SPARE CLONE'S XDG RUNTIME ROOT, and it has
        to.  A nominated PLAYTHROUGH_RUNTIME_DIR is now refused outright
        unless it lies beneath the verified XDG runtime root, so a parent
        in this test's own temporary directory would be rejected for THAT
        reason and the mode logic under test would never be reached.  The
        callers therefore pass CLONE_INDEX with the nomination, which is
        what makes /tmp/xdg<SPARE_INDEX> the verified root for the run.
        """
        base = self.spare_runtime_dir()
        os.makedirs(base, exist_ok=True)
        os.chmod(base, 0o700)
        path = os.path.join(base, name)
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o2777)
        self.assertTrue(os.stat(path).st_mode & stat.S_ISGID)
        return path

    def nominate(self, nominated):
        """The preset that nominates ``nominated`` as the runtime root."""
        return {"PLAYTHROUGH_RUNTIME_DIR": nominated,
                "CLONE_INDEX": str(SPARE_INDEX)}

    def test_an_inherited_setgid_bit_is_not_a_refusal(self):
        # THE REPORTED DEFECT.  /tmp is mode 2777 on this class of host;
        # a runtime directory created under it comes out 2700, GNU chmod
        # preserves that bit on a directory, and the old whole-string
        # compare therefore refused a directory whose access bits were
        # exactly the 0700 it asked for -- killing the source, and with
        # it every stage that sources this file.
        nominated = os.path.join(self.setgid_parent(), "runtime")
        os.makedirs(nominated, mode=0o700, exist_ok=True)
        self.assertTrue(os.stat(nominated).st_mode & stat.S_ISGID)
        result = self.source(preset=self.nominate(nominated))
        self.assertEqual(
            result.status, 0,
            msg="sourcing must survive a setgid temporary directory: %s"
                % result.stderr)
        self.assertEqual(result["PLAYTHROUGH_RUNTIME_DIR"], nominated)
        self.assertEqual(os.stat(nominated).st_mode & 0o077, 0)
        for name in ("log", "run", "lock", "rejected"):
            child = os.path.join(nominated, name)
            with self.subTest(child=name):
                self.assertTrue(os.path.isdir(child))
                self.assertEqual(os.stat(child).st_mode & 0o077, 0)

    def test_the_setgid_case_says_nothing_about_being_widened(self):
        # 2700 is not "wider than 0700", so announcing a repair would be
        # a false alarm on every load on such a host -- and a false
        # alarm about somebody having opened the runtime state to other
        # accounts is the worst kind.
        nominated = os.path.join(self.setgid_parent(), "quiet")
        os.makedirs(nominated, mode=0o700, exist_ok=True)
        result = self.source(preset=self.nominate(nominated))
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertNotIn("was mode", result.stderr)

    def test_a_group_or_other_bit_is_still_repaired_and_announced(self):
        # The control itself is unchanged: what is tolerated is the
        # special-bits digit, never a group or other permission.
        nominated = os.path.join(self.setgid_parent(), "open")
        os.makedirs(nominated, mode=0o700, exist_ok=True)
        os.chmod(nominated, 0o2755)
        result = self.source(preset=self.nominate(nominated))
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertEqual(os.stat(nominated).st_mode & 0o077, 0)
        self.assertIn("was mode", result.stderr)
        self.assertIn("readable by other accounts", result.stderr)

    def test_a_mode_that_stays_wide_is_still_fatal(self):
        # The mode is CONFIRMED, not assumed from chmod's exit status.
        # Sabotaging the reading to a world-writable one stands in for a
        # filesystem that accepted the chmod and did nothing: the source
        # must die rather than proceed on a promise.
        nominated = os.path.join(self.root, "unrepairable")
        os.makedirs(nominated, exist_ok=True)
        root, copy = self.sabotaged_copy(
            READ_ACTUAL_MODE,
            '    actual="777"',
            name="wide-mode")
        result = self.source(
            script=copy, cwd=root,
            preset={"PLAYTHROUGH_RUNTIME_DIR": nominated})
        self.assertNotEqual(result.status, 0)
        self.assertIn("permission bits", result.stderr)

    def test_a_special_bit_cannot_disguise_a_wide_mode(self):
        # The tolerated digit is the special-bits one and nothing else:
        # 2777 carries the same setgid bit as the accepted 2700 and must
        # still be refused when it cannot be tightened.
        nominated = os.path.join(self.root, "disguised")
        os.makedirs(nominated, exist_ok=True)
        root, copy = self.sabotaged_copy(
            READ_ACTUAL_MODE,
            '    actual="2777"',
            name="wide-setgid")
        result = self.source(
            script=copy, cwd=root,
            preset={"PLAYTHROUGH_RUNTIME_DIR": nominated})
        self.assertNotEqual(result.status, 0)
        self.assertIn("permission bits '777'", result.stderr)

    def test_the_shell_and_the_python_agree_on_what_0700_means(self):
        # The two halves of one contract.  session.py is documented as
        # runnable with nothing sourced, so it restates this rule -- and
        # a restatement that disagrees is how a host ends up able to run
        # one and not the other.
        nominated = os.path.join(self.setgid_parent("agree"), "both")
        session_py = os.path.join(PLAYTHROUGH, "tooling", "session.py")
        program = (
            "import sys\n"
            "sys.dont_write_bytecode = True\n"
            "sys.path.insert(0, %r)\n"
            "import session\n"
            "print(session._secure_dir(%r, 'the runtime directory'))\n"
            % (os.path.dirname(session_py), nominated))
        completed = subprocess.run(
            [sys.executable, "-B", "-c", program],
            capture_output=True, timeout=120)
        self.assertEqual(
            completed.returncode, 0,
            msg=completed.stderr.decode("utf-8", "replace"))
        self.assertTrue(os.stat(nominated).st_mode & stat.S_ISGID)
        result = self.source(preset=self.nominate(nominated))
        self.assertEqual(
            result.status, 0,
            msg=("what session.py creates and accepts, env.sh must "
                 "accept: %s" % result.stderr))


class TestTheArtifactLayout(EnvFixture):
    """Every path derived from the file's own location."""

    def test_the_repository_root_is_the_real_one(self):
        self.assertEqual(self.sourced()["PLAYTHROUGH_REPO_ROOT"],
                         REPO_ROOT)

    def test_the_root_does_not_depend_on_the_working_directory(self):
        expected = self.sourced()["PLAYTHROUGH_REPO_ROOT"]
        for cwd in ("/tmp", "/", TOOLING, self.root):
            with self.subTest(cwd=cwd):
                self.assertEqual(
                    self.sourced(cwd=cwd)["PLAYTHROUGH_REPO_ROOT"],
                    expected,
                    msg=("resolved from BASH_SOURCE, which is what "
                         "keeps it correct no matter where a caller "
                         "sources it from"))

    def test_every_artifact_path_hangs_off_the_root(self):
        result = self.sourced()
        expected = {
            "PLAYTHROUGH_DIR": "playthrough",
            "PLAYTHROUGH_TOOLING_DIR": "playthrough/tooling",
            "PLAYTHROUGH_FRAMES_DIR": "playthrough/frames",
            "PLAYTHROUGH_BUILD_DIR": "playthrough/build",
            "PLAYTHROUGH_TRANSITIONS_DIR":
                "playthrough/build/transitions",
            "PLAYTHROUGH_USERDIR": "playthrough/userdir",
            "PLAYTHROUGH_SAVE_DIR": "playthrough/userdir/save",
            "PLAYTHROUGH_CONFIG_DIR": "playthrough/userdir/config",
            "PLAYTHROUGH_OPTIONS_JSON":
                "playthrough/userdir/config/options.json",
            "PLAYTHROUGH_KEYBINDINGS_JSON":
                "playthrough/userdir/config/keybindings.json",
            "PLAYTHROUGH_MANIFEST": "playthrough/manifest.jsonl",
            "PLAYTHROUGH_TIMELINE": "playthrough/timeline.json",
            "PLAYTHROUGH_OBSERVATIONS":
                "playthrough/build/observations.jsonl",
            "PLAYTHROUGH_CONCAT_LIST": "playthrough/build/concat.txt",
            "PLAYTHROUGH_MOVIE": "playthrough/cata-play.mp4",
            "PLAYTHROUGH_MOVIE_CC": "playthrough/cata-play-cc.mp4",
            "PLAYTHROUGH_TRANSCRIPT_MD": "playthrough/transcript.md",
            "PLAYTHROUGH_TRANSCRIPT_SRT": "playthrough/transcript.srt",
            "PLAYTHROUGH_DOSSIER": "playthrough/dossier.md",
            # The mandated final report.  It was exported here and
            # staged by the committer, and named in neither this map nor
            # any gate -- so a checkpoint could publish a recording with
            # no report at all.  The committer now requires it at its
            # final checkpoint; this is the path half of that contract.
            "PLAYTHROUGH_REPORT": "playthrough/REPORT.md",
            "PLAYTHROUGH_TECH_NOTES":
                "playthrough/TECHNICAL_NOTES.md",
            "PLAYTHROUGH_REQUIREMENTS":
                "playthrough/tooling/requirements.txt",
            "PLAYTHROUGH_GAME_BIN": "cataclysm-tiles",
        }
        for name, relative in expected.items():
            with self.subTest(variable=name):
                self.assertEqual(
                    result[name],
                    os.path.join(REPO_ROOT, relative))

    def test_the_observations_sidecar_is_an_intermediate_not_evidence(self):
        result = self.sourced()
        self.assertTrue(
            result["PLAYTHROUGH_OBSERVATIONS"].startswith(
                result["PLAYTHROUGH_BUILD_DIR"]),
            msg=("it lives under build/ because it is a recomputable "
                 "observation record, and because putting it beside "
                 "manifest.jsonl would invite exactly the confusion "
                 "the six-field contract exists to prevent"))
        self.assertNotIn(
            "\n", result["PLAYTHROUGH_OBSERVATIONS"],
            msg="the line continuation in the export must not leak a "
                "newline into the value")

    def test_the_two_command_line_forms_stay_relative(self):
        result = self.sourced()
        self.assertEqual(result["PLAYTHROUGH_GAME_BIN_ARG"],
                         "./cataclysm-tiles")
        self.assertEqual(
            result["PLAYTHROUGH_USERDIR_ARG"],
            "./playthrough/userdir/",
            msg=("--userdir is normalised but NOT absolutised, so it "
                 "resolves against the process working directory; the "
                 "trailing slash matches as_norm_dir's own "
                 "normalisation"))

    def test_a_root_that_is_not_a_checkout_is_refused(self):
        root, copy = self.sandbox_checkout("bare", valid=False)
        result = self.source(script=copy, cwd=root)
        self.assertNotEqual(result.status, 0)
        self.assertIn("is not a", result.stderr)
        self.assertIn("path_info.cpp", result.stderr)

    def test_a_copy_inside_a_checkout_describes_that_checkout(self):
        root, copy = self.sandbox_checkout("elsewhere")
        result = self.sourced(script=copy, cwd=root)
        self.assertEqual(result["PLAYTHROUGH_REPO_ROOT"], root)
        self.assertEqual(result["PLAYTHROUGH_FRAMES_DIR"],
                         os.path.join(root, "playthrough", "frames"))
        self.assertNotEqual(
            result["PLAYTHROUGH_REPO_ROOT"], REPO_ROOT,
            msg=("the paths follow the file, which is what makes a "
                 "sandbox test of the capture scripts possible at all"))

    def test_a_checkout_missing_only_the_data_tree_is_refused(self):
        root, copy = self.sandbox_checkout("no-data")
        shutil.rmtree(os.path.join(root, "data"))
        result = self.source(script=copy, cwd=root)
        self.assertNotEqual(result.status, 0)
        self.assertIn("is not a", result.stderr)


class TestTheCheckoutLockName(EnvFixture):
    """A lock name that identifies the working tree, not the clone index.

    PLAYTHROUGH_LOCK_DIR hangs off the runtime root, which is derived
    from CLONE_INDEX rather than from the tree -- so two clones started
    without CLONE_INDEX share one lock directory, and a bare name like
    `pipeline` or `checkpoint` serialises two runs that share NOTHING.
    That was measured: a second checkout's run was refused with a message
    about "this checkout" while the holder was a different checkout
    entirely, which sends an operator to look in the wrong place.

    Two siblings call this helper by name -- run_pipeline.sh for its
    `pipeline` lock and commit_artifacts.sh for its `checkpoint` one --
    so the properties below are a contract rather than an internal
    detail.
    """

    def lock_name(self, basename, script=ENV_SH, cwd=REPO_ROOT,
                  path=None):
        """Ask env.sh for a lock name.  Returns (status, name, stderr).

        `path` narrows PATH for the CALL only and restores it
        afterwards: the harness dumps the environment through `env -0`,
        so a PATH left broken would lose the answer rather than report
        it.
        """
        narrow = ""
        widen = ""
        if path is not None:
            narrow = 'SAVED_PATH="${PATH}"\nPATH="%s"\n' % path
            widen = 'PATH="${SAVED_PATH}"\n'
        result = self.source(
            script=script, cwd=cwd,
            after='%sNAME="$(playthrough_checkout_lock_name "%s")"\n'
                  'LOCK_STATUS=$?\n'
                  '%sexport NAME LOCK_STATUS'
                  % (narrow, basename, widen))
        return (result.get("LOCK_STATUS"), result.get("NAME"),
                result.stderr)

    def test_the_name_is_the_basename_and_a_short_digest(self):
        status, name, err = self.lock_name("pipeline")
        self.assertEqual(status, "0", msg=err)
        self.assertRegex(name, r"^pipeline-[0-9a-f]{8}$")

    def test_the_digest_satisfies_the_lock_name_character_class(self):
        """playthrough_acquire_lock refuses anything else, so a name it
        would reject is a name no lock can be taken under."""
        _, name, _ = self.lock_name("checkpoint")
        self.assertRegex(name, r"^[a-z0-9_-]+$")

    def test_the_same_checkout_always_takes_the_same_name(self):
        """Stable across runs, or a second invocation would not contend
        with the first and the whole lock would be decorative."""
        first = self.lock_name("pipeline")[1]
        second = self.lock_name("pipeline")[1]
        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_the_name_does_not_depend_on_the_working_directory(self):
        """It is derived from the root env.sh resolved from its own
        location, not from where a caller happened to stand."""
        expected = self.lock_name("pipeline")[1]
        for cwd in ("/tmp", "/", TOOLING):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.lock_name("pipeline", cwd=cwd)[1],
                                 expected)

    def test_two_different_checkouts_take_two_different_names(self):
        """The whole point: unrelated trees must not serialise."""
        root, copy = self.sandbox_checkout("other-tree")
        mine = self.lock_name("pipeline")[1]
        theirs = self.lock_name("pipeline", script=copy, cwd=root)[1]
        self.assertTrue(theirs)
        self.assertNotEqual(mine, theirs)
        self.assertRegex(theirs, r"^pipeline-[0-9a-f]{8}$")

    def test_the_two_basenames_differ_within_one_checkout(self):
        """One tree, two locks: the sequencer's and the committer's.

        A shared name would make a checkpoint wait for a render that has
        nothing to do with it.
        """
        self.assertNotEqual(self.lock_name("pipeline")[1],
                            self.lock_name("checkpoint")[1])

    def test_an_unusable_basename_is_refused(self):
        for basename in ("", "Pipeline", "pipe line", "pipe/line",
                         "pipe.line", "pipe;line", "../escape",
                         "pipe$(id)"):
            with self.subTest(basename=basename):
                status, name, err = self.lock_name(basename)
                self.assertNotEqual(
                    status, "0",
                    msg="%r was accepted as %r" % (basename, name))
                self.assertIn("not a usable lock basename", err)
                self.assertEqual(name, "")

    def test_a_basename_it_refuses_yields_no_name_to_fall_back_on(self):
        """A refusal that still printed something would be a lock taken
        under a name nobody validated."""
        status, name, _ = self.lock_name("NOPE")
        self.assertNotEqual(status, "0")
        self.assertEqual(name, "")

    def test_the_digest_tool_being_unreachable_is_a_refusal(self):
        """No sha256sum, no name -- and no bare fallback.

        Falling back to the basename here would put the clone-index lock
        back, silently, on exactly the hosts least able to notice.
        """
        status, name, err = self.lock_name("pipeline",
                                           path="/nonexistent")
        self.assertNotEqual(status, "0", msg=name)
        self.assertEqual(name, "")
        self.assertIn("sha256sum", err)


class TestTheTunables(EnvFixture):
    """The geometry and the grid, in one place."""

    def test_every_tunable_carries_its_contracted_value(self):
        result = self.sourced()
        for name, value in TUNABLES.items():
            with self.subTest(variable=name):
                self.assertEqual(result.get(name), value)

    def test_the_screen_is_the_one_xvfb_is_started_with(self):
        result = self.sourced()
        self.assertEqual(
            result["PLAYTHROUGH_SCREEN"],
            "%sx%sx%s" % (result["PLAYTHROUGH_SCREEN_WIDTH"],
                          result["PLAYTHROUGH_SCREEN_HEIGHT"],
                          result["PLAYTHROUGH_SCREEN_DEPTH"]))

    def test_the_window_is_found_by_class(self):
        self.assertEqual(
            self.sourced()["PLAYTHROUGH_WINDOW_CLASS"],
            "cataclysm-tiles",
            msg=("xdotool search --name 'Cataclysm' returns nothing "
                 "for this window even though xwininfo lists it"))

    def test_the_grid_multiplies_out_to_the_game_window(self):
        result = self.sourced()
        width = int(result["PLAYTHROUGH_TERMINAL_X"]) * int(
            result["PLAYTHROUGH_FONT_WIDTH"])
        height = int(result["PLAYTHROUGH_TERMINAL_Y"]) * int(
            result["PLAYTHROUGH_FONT_HEIGHT"])
        self.assertEqual(width, 1920)
        self.assertEqual(
            height, 1072,
            msg=("the window is 1920x1072 inside a 1920x1080 root, "
                 "which is the 4 px letterbox capture keeps"))

    def test_the_recorded_sidebar_width_is_the_engine_default(self):
        result = self.sourced()
        self.assertEqual(
            result["PLAYTHROUGH_SIDEBAR_CELLS"], "44",
            msg=("panel_manager initialises current_layout_id to "
                 "legacy_labels_sidebar, whose widget declares 44; "
                 "custom_sidebar's 36 is merely one of the shipped "
                 "presets"))
        self.assertEqual(result["PLAYTHROUGH_SIDEBAR_LAYOUT"],
                         "legacy_labels_sidebar")

    def test_the_frame_format_is_the_one_every_stage_shares(self):
        result = self.sourced(
            after='FRAME="$(printf -- "${PLAYTHROUGH_FRAME_FORMAT}"'
                  ' 42)"\nexport FRAME')
        self.assertEqual(
            result.get("FRAME"), "frame_00042.png",
            msg=("the 5-digit zero-padded field keeps a lexical sort "
                 "identical to a numeric one, which is what makes the "
                 "concat list trivially correct"))

    def test_the_transition_format_names_a_group_and_a_step(self):
        result = self.sourced(
            after='NAME="$(printf --'
                  ' "${PLAYTHROUGH_TRANSITION_FORMAT}" 7 3)"\n'
                  'export NAME')
        self.assertEqual(result.get("NAME"), "trans_00007_03.png")

    def test_the_tileset_is_named_by_its_id_not_its_view(self):
        result = self.sourced()
        self.assertEqual(result["PLAYTHROUGH_TILESET"],
                         "MshockXottoplus")
        self.assertNotEqual(
            result["PLAYTHROUGH_TILESET"], "MSXotto+",
            msg=("the TILES option takes the NAME: field of the "
                 "installed tileset.txt, never its display name"))


class TestSourcingIsInert(EnvFixture):
    """Nothing starts, nothing is written, nothing is left behind."""

    def test_sourcing_prints_nothing_on_stdout(self):
        result = self.sourced()
        self.assertEqual(
            result.source_output, "",
            msg=("a consumer captures stdout, so one stray line would "
                 "corrupt it: %r" % result.source_output))

    def test_sourcing_is_silent_on_stderr_too(self):
        self.assertEqual(
            self.sourced().stderr, "",
            msg="a clean host produces no warnings at source time")

    def test_sourcing_succeeds_with_no_toolchain_on_path(self):
        holder = self.thin_path()
        result = self.source(path=holder)
        self.assertEqual(
            result.status, 0,
            msg=("no helper runs at source time, so a PATH with no "
                 "Xvfb, no openbox, no xdotool and no ImageMagick is "
                 "still enough to establish the contract: %s"
                 % result.stderr))
        self.assertEqual(result["SDL_VIDEODRIVER"], "x11")
        self.assertTrue(
            os.path.isabs(result["PLAYTHROUGH_PYTHON"]),
            msg=("the provisioned interpreter is found by absolute "
                 "path rather than through PATH, so a thin PATH does "
                 "not cost the render stages their interpreter"))

    def test_no_interpreter_anywhere_is_a_warning_not_a_failure(self):
        # The last-resort branch: no explicit interpreter, no named
        # virtualenv, no provisioned one, and no python3 on PATH.
        root, copy = self.sabotaged_copy(
            '[ -x "/opt/playthrough-venv/bin/python" ]',
            '[ -x "%s/no-such-interpreter" ]' % self.root,
            name="no-python")
        result = self.source(script=copy, cwd=root,
                             path=self.thin_path())
        self.assertEqual(
            result.status, 0,
            msg=("the contract is still established; only the render "
                 "stages are affected, and they say so themselves"))
        self.assertIn("no python3 found on PATH", result.stderr)
        self.assertEqual(
            result["PLAYTHROUGH_PYTHON"], "python3",
            msg=("the name is still exported, so the failure comes "
                 "later and names what was missing"))

    def test_sourcing_creates_no_artifact_directory(self):
        watched = ("frames", "build", "userdir")
        before = {name: os.path.isdir(os.path.join(PLAYTHROUGH, name))
                  for name in watched}
        self.sourced()
        after = {name: os.path.isdir(os.path.join(PLAYTHROUGH, name))
                 for name in watched}
        self.assertEqual(
            after, before,
            msg=("playthrough_mkdirs is called explicitly, never at "
                 "source time: sourcing must not write into the tree"))

    def test_sourcing_writes_nothing_into_the_repository(self):
        listing = sorted(os.listdir(PLAYTHROUGH))
        tooling = sorted(os.listdir(TOOLING))
        self.sourced()
        self.assertEqual(sorted(os.listdir(PLAYTHROUGH)), listing)
        self.assertEqual(sorted(os.listdir(TOOLING)), tooling)

    def test_the_path_is_never_touched(self):
        marker = "/opt/marker-bin:" + BASE_PATH
        result = self.sourced(path=marker)
        self.assertEqual(
            result["PATH"], marker,
            msg=("PATH is deliberately never modified, which is what "
                 "makes re-sourcing safe: it cannot grow"))

    def test_no_scratch_name_is_left_in_the_caller_s_shell(self):
        result = self.sourced(
            after='LEFTOVERS="$(compgen -v | grep -c "^_playthrough")"'
                  '\nexport LEFTOVERS')
        self.assertEqual(
            result.get("LEFTOVERS"), "0",
            msg=("only the exported PLAYTHROUGH_* set, the six "
                 "environment variables and the helper functions are "
                 "part of this file's contract"))

    def test_every_promised_helper_is_defined(self):
        result = self.sourced(
            after='DEFINED="$(declare -F | sed "s/^declare -f //"'
                  ' | tr "\\n" " ")"\nexport DEFINED')
        defined = (result.get("DEFINED") or "").split()
        for name in HELPERS:
            with self.subTest(helper=name):
                self.assertIn(name, defined)

    def test_the_summary_helper_reports_the_contract_on_demand(self):
        result = self.sourced(
            after='SUMMARY="$(playthrough_env_summary'
                  ' | grep -c .)"\nexport SUMMARY')
        self.assertEqual(
            int(result.get("SUMMARY", "0")), len(SUMMARY_FIELDS) + 1,
            msg=("the record of what the capture actually ran under: "
                 "one header line and one line per promised field"))

    def run_the_file(self, preset=None):
        """Execute env.sh as a program and return the CompletedProcess.

        The documented second mode -- "Executing the file instead prints
        the resolved contract and exports nothing" -- and therefore a
        mode that has to be exercised as a whole, not only by calling
        the helper from a sourced shell.
        """
        environment = {"PATH": BASE_PATH}
        if preset:
            environment.update(preset)
        return subprocess.run(
            ["/usr/bin/env", "-i"] + [
                "%s=%s" % (name, value)
                for name, value in environment.items()
            ] + ["/bin/bash", "--noprofile", "--norc", ENV_SH],
            cwd=REPO_ROOT, capture_output=True, timeout=120)

    def test_running_the_file_prints_the_contract_and_exports_nothing(self):
        result = self.run_the_file()
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode("utf-8", "replace")
        self.assertIn("playthrough environment contract", text)
        self.assertIn("SDL_VIDEODRIVER", text)
        self.assertIn("x11", text)

    def test_the_whole_summary_is_one_printf_and_nothing_else(self):
        """A broken continuation ran a LABEL as a command.

        The summary is one `printf` over a long argument list, so a
        missing trailing backslash does not fail loudly: it ends the
        argument list early -- silently truncating every key after that
        point -- and then executes the next line, whose first word is a
        variable NAME, as a command.  That is the defect this asserts is
        gone, from both sides: nothing is reported as a command, and the
        keys that used to be lost are present.
        """
        result = subprocess.run(
            ["/usr/bin/env", "-i", "PATH=" + BASE_PATH,
             "/bin/bash", "--noprofile", "--norc", ENV_SH],
            cwd=REPO_ROOT, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0)
        stderr = result.stderr.decode("utf-8", "replace")
        self.assertNotIn("command not found", stderr)
        text = result.stdout.decode("utf-8", "replace")
        for key in ("PLAYTHROUGH_PYTHON", "PLAYTHROUGH_PYTHON_VERSION",
                    "XAUTHORITY", "PLAYTHROUGH_XAUTHORITY_ORIGIN",
                    "IMAGEIO_FFMPEG_EXE", "PLAYTHROUGH_PLATFORM"):
            with self.subTest(key=key):
                self.assertIn(key, text)
        labels = [line.split()[0] for line in text.splitlines()
                  if line.startswith("  ")]
        self.assertEqual(
            sorted(set(labels)), sorted(labels),
            msg=("every key is reported once; a repeated label is the "
                 "signature of a copied continuation line"))

    @unittest.skipUnless(os.path.exists("/dev/full"),
                         "needs /dev/full to fail a write")
    def test_a_summary_that_cannot_be_written_exits_non_zero(self):
        """The direct run exists to print, so a failed print fails.

        stdout is a sink that refuses every write, so the summary's
        printf cannot land.  The status used to be whatever the trailing
        `unset` returned -- always 0 -- which reported success for a run
        whose record was truncated or absent.
        """
        result = subprocess.run(
            ["/usr/bin/env", "-i", "PATH=" + BASE_PATH,
             "/bin/bash", "--noprofile", "--norc", "-c",
             '"$1" >/dev/full', "bash", ENV_SH],
            cwd=REPO_ROOT, capture_output=True, timeout=120)
        self.assertNotEqual(
            result.returncode, 0,
            msg="a run whose record did not land must not report "
                "success")
        self.assertIn(
            "summary could not be written",
            result.stderr.decode("utf-8", "replace"))

    def test_running_the_file_says_nothing_on_stderr(self):
        """Silence on stderr, because noise there WAS the symptom.

        A report assembled from a continued argument list truncated
        itself when one continuation went missing, and announced it only
        as `PLAYTHROUGH_PYTHON: command not found` on a channel nothing
        was asserting on.
        """
        for index in (None, "2"):
            preset = {} if index is None else {"CLONE_INDEX": index}
            with self.subTest(clone_index=index):
                result = self.run_the_file(preset)
                self.assertEqual(
                    result.stderr.decode("utf-8", "replace"), "",
                    msg="the reporting mode reports, it does not error")
                self.assertEqual(result.returncode, 0)

    def test_the_printed_contract_carries_every_promised_field(self):
        result = self.run_the_file()
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.decode("utf-8", "replace").splitlines()
        self.assertEqual(
            lines[0], "playthrough environment contract",
            msg="the header, then one line per field")
        printed = [line.split()[0] for line in lines[1:] if line.strip()]
        for name in SUMMARY_FIELDS:
            with self.subTest(field=name):
                self.assertIn(
                    name, printed,
                    msg=("a field that is printed as nothing at all "
                         "cannot be told from one that is unset"))
        self.assertEqual(
            sorted(printed), sorted(set(printed)),
            msg="no field is reported twice")
        self.assertEqual(
            len(printed), len(SUMMARY_FIELDS),
            msg="exactly the promised fields, no more: %r" % printed)

    def test_the_printed_contract_carries_values_not_just_names(self):
        result = self.run_the_file({"CLONE_INDEX": "2"})
        text = result.stdout.decode("utf-8", "replace")
        values = {}
        for line in text.splitlines()[1:]:
            parts = line.split(None, 1)
            if len(parts) == 2:
                values[parts[0]] = parts[1].strip()
        self.assertEqual(values.get("DISPLAY"), ":101")
        self.assertEqual(values.get("SDL_VIDEODRIVER"), "x11")
        self.assertEqual(values.get("XDG_RUNTIME_DIR"), "/tmp/xdg2")
        for name in ("XAUTHORITY", "IMAGEIO_FFMPEG_EXE",
                     "PLAYTHROUGH_PLATFORM",
                     "PLAYTHROUGH_PLATFORM_SUPPORTED",
                     "PLAYTHROUGH_XAUTHORITY_ORIGIN"):
            with self.subTest(field=name):
                self.assertTrue(
                    values.get(name),
                    msg=("the trailing fields are the ones a truncated "
                         "report loses first"))


class TestSourcingTwiceIsSafe(EnvFixture):
    """Every assignment is absolute and recomputed from scratch."""

    def test_a_second_source_changes_nothing(self):
        once = self.sourced()
        twice = self.source(
            after='. "$1"\nstatus=$?')
        self.assertEqual(twice.status, 0)
        self.assertEqual(
            twice.environment, once.environment,
            msg=("nothing is ever appended to, so re-sourcing is a "
                 "no-op rather than a slow accumulation"))

    def test_a_third_source_is_still_silent(self):
        result = self.source(after='. "$1"\n. "$1"\nstatus=$?')
        self.assertEqual(result.status, 0)
        self.assertEqual(result.source_output, "")
        self.assertEqual(result.stderr, "")

    def test_re_sourcing_repairs_a_poisoned_driver(self):
        result = self.sourced(
            after='export SDL_VIDEODRIVER=dummy\n. "$1"')
        self.assertEqual(
            result["SDL_VIDEODRIVER"], "x11",
            msg=("the documented remedy -- 'Re-source "
                 "playthrough/tooling/env.sh' -- has to actually "
                 "work"))


class TestThePythonInterpreter(EnvFixture):
    """One interpreter for every sibling, resolved out of tree."""

    def fake_python(self, name="python"):
        """An executable stand-in for an interpreter."""
        holder = os.path.join(self.root, name + "-home", "bin")
        os.makedirs(holder, exist_ok=True)
        path = os.path.join(holder, "python")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(path, 0o755)
        return path

    def test_an_explicit_interpreter_wins(self):
        # A nominated interpreter is honoured -- but only after it has
        # been checked for third-party ownership and for group- or
        # world-writability, on the binary and on every directory above
        # it.  This fixture's sandbox lives under /tmp, which is mode
        # 2777 on this class of host, so the nomination is exercised
        # with the documented per-invocation diagnostic override; the
        # test below proves the same nomination is refused without it.
        path = self.fake_python("explicit")
        result = self.sourced(preset={
            "PLAYTHROUGH_PYTHON": path,
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES": "1"})
        self.assertEqual(result["PLAYTHROUGH_PYTHON"], path)

    def test_an_interpreter_under_a_writable_ancestor_is_refused(self):
        path = self.fake_python("writable")
        result = self.source(preset={"PLAYTHROUGH_PYTHON": path})
        self.assertEqual(
            result.status, 1,
            msg="sourcing must fail rather than fall back silently")
        self.assertIn(
            "group- or world-writable", result.stderr,
            msg=("an interpreter any account can replace between the "
                 "check and the next invocation is not one an "
                 "unattended pipeline may run"))
        self.assertIn("PLAYTHROUGH_PYTHON", result.stderr)

    def test_a_named_virtualenv_is_used_next(self):
        path = self.fake_python("venv")
        venv = os.path.dirname(os.path.dirname(path))
        result = self.sourced(preset={
            "PLAYTHROUGH_VENV": venv,
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES": "1"})
        self.assertEqual(result["PLAYTHROUGH_PYTHON"], path)

    def test_an_interpreter_that_is_not_executable_is_ignored(self):
        path = os.path.join(self.root, "not-executable")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
        result = self.sourced(preset={"PLAYTHROUGH_PYTHON": path})
        self.assertNotEqual(
            result["PLAYTHROUGH_PYTHON"], path,
            msg=("a path that cannot be run is not an interpreter, and "
                 "honouring it would defer the failure to the first "
                 "render stage"))

    def test_the_resolved_interpreter_is_out_of_tree(self):
        resolved = self.sourced()["PLAYTHROUGH_PYTHON"]
        self.assertFalse(
            resolved.startswith(PLAYTHROUGH + os.sep),
            msg=("a virtualenv inside playthrough/ would be "
                 "re-included by !/playthrough/** and committed, byte "
                 "for byte"))

    def test_the_helper_runs_the_resolved_interpreter(self):
        result = self.sourced(
            after='if playthrough_python -c "pass"; then\n'
                  '    export RAN=yes\nfi')
        self.assertEqual(
            result.get("RAN"), "yes",
            msg="so no sibling has to rediscover the interpreter")

    def versioned_python(self, version, name="versioned"):
        """An interpreter stand-in that reports ``version``."""
        holder = os.path.join(self.root, name + "-home", "bin")
        os.makedirs(holder, exist_ok=True)
        path = os.path.join(holder, "python")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nprintf '%s\\n' " + version + "\n")
        os.chmod(path, 0o755)
        return path

    def test_the_interpreter_version_is_observed_and_reported(self):
        """Which Python ran is part of the record, not an assumption."""
        path = self.versioned_python("3.12.13", "matching")
        result = self.sourced(preset={
            "PLAYTHROUGH_PYTHON": path,
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES": "1"})
        self.assertEqual(result["PLAYTHROUGH_PYTHON_VERSION"], "3.12.13")
        self.assertEqual(result["PLAYTHROUGH_PYTHON_ABI"], "3.12")
        self.assertNotIn("pins CPython", result.stderr,
                         msg="the contracted interpreter is silent")

    def test_an_interpreter_of_the_wrong_series_is_named(self):
        """The provisioning mistake this catches is a quiet one.

        `python3 -m venv .venv` on a host whose python3 is 3.13 installs
        into one interpreter while the pipeline runs another, and
        requirements.lock's cp312 wheels cannot go into it at all.  The
        version is therefore checked as well as the trust of the file.
        """
        path = self.versioned_python("3.13.7", "mismatched")
        result = self.sourced(preset={
            "PLAYTHROUGH_PYTHON": path,
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES": "1"})
        self.assertEqual(result["PLAYTHROUGH_PYTHON_VERSION"], "3.13.7")
        self.assertIn("pins CPython", result.stderr)
        self.assertIn("3.12", result.stderr)
        self.assertIn("PLAYTHROUGH_VENV", result.stderr)

    def test_an_interpreter_that_answers_nothing_is_reported_unknown(self):
        path = self.fake_python("silent")
        result = self.sourced(preset={
            "PLAYTHROUGH_PYTHON": path,
            "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES": "1"})
        self.assertEqual(
            result["PLAYTHROUGH_PYTHON_VERSION"], "",
            msg="an unanswered probe is empty, never a guessed version")
        self.assertIn("could not ask", result.stderr)

    def test_the_declared_abi_matches_the_lock_file(self):
        """One interpreter series, named in both places."""
        abi = self.sourced()["PLAYTHROUGH_PYTHON_ABI"]
        path = os.path.join(TOOLING, "requirements.lock")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(
            "CPython %s" % abi, text,
            msg=("env.sh checks the interpreter against the series "
                 "requirements.lock builds its wheels for"))


class TestTheInheritedEnvironmentIsRefused(EnvFixture):
    """A poisoned environment chooses what code the pipeline runs.

    Every external command in this tree is resolved by absolute path and
    verified so that a replaceable tool cannot decide a reading in the
    film.  A security review named the hole beside it: the ENVIRONMENT
    those verified binaries inherit is a second way to choose their code,
    and nothing looked at it.  These are refused rather than unset --
    honouring one runs a caller's code, discarding one silently does
    something other than what the caller asked, and saying so is the only
    honest third option.
    """

    # Every name env.sh refuses, grouped by what it reaches.  The list is
    # the contract; a name added to env.sh without one here fails
    # test_the_refusal_list_is_the_one_env_sh_publishes.
    REFUSED = (
        # bash SOURCES this at the start of every non-interactive shell,
        # so one variable runs a caller's file inside all nine stages.
        "BASH_ENV", "ENV",
        # The dynamic loader: a caller's shared object in every process,
        # able to override any symbol in it.
        "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH",
        # The interpreter, and what its imports resolve to.
        "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
        # Arbitrary git configuration -- core.hooksPath among it --
        # outranking the containment commit_artifacts.sh applies.
        "GIT_CONFIG", "GIT_CONFIG_COUNT",
        # Where git reads the evidence from and writes it to.
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        # Programs git executes.
        "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR", "GIT_SSH",
        "GIT_SSH_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_PROXY_COMMAND",
        "GIT_ASKPASS",
        # ImageMagick's coder and filter MODULE paths -- code that runs
        # on every frame -- and font resolution, which the attested
        # Terminus digest exists to pin.
        "MAGICK_HOME", "MAGICK_CONFIGURE_PATH",
        "MAGICK_CODER_MODULE_PATH", "MAGICK_FILTER_MODULE_PATH",
        "FONTCONFIG_FILE",
        # ffmpeg writing a report to a caller-chosen path every call.
        "FFREPORT",
    )

    # Left alone deliberately: refusing any of these would break a
    # legitimate mechanism this pipeline or its own suites depend on.
    PERMITTED = (
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
        "GIT_TERMINAL_PROMPT", "GIT_CONFIG_NOSYSTEM",
    )

    def test_the_refusal_list_is_the_one_env_sh_publishes(self):
        published = self.sourced()["PLAYTHROUGH_REFUSED_ENV_VARS"]
        self.assertEqual(sorted(published.split()),
                         sorted(self.REFUSED))

    def test_every_refused_variable_stops_the_source(self):
        for name in self.REFUSED:
            with self.subTest(variable=name):
                result = self.source(preset={name: "/tmp/whatever"})
                self.assertNotEqual(
                    result.status, 0,
                    msg="%s must refuse, not warn" % name)
                self.assertIn("refused environment: %s=" % name,
                              result.stderr)

    def test_every_refused_variable_says_what_it_would_reach(self):
        """A refusal that names a variable and stops is not a diagnosis."""
        for name in self.REFUSED:
            with self.subTest(variable=name):
                result = self.source(preset={name: "/tmp/whatever"})
                marker = "refused environment: %s=" % name
                start = result.stderr.index(marker)
                line = result.stderr[start:].split("\n", 1)[0]
                self.assertIn(" -- ", line)
                self.assertNotIn(
                    "it is not part of this pipeline's environment "
                    "contract", line,
                    msg="%s falls through to the generic reason" % name)

    def test_an_empty_value_is_not_a_poisoned_environment(self):
        """`env -u` and `NAME=` reach here the same way."""
        self.sourced(preset={name: "" for name in self.REFUSED})

    def test_the_permitted_variables_are_left_alone(self):
        for name in self.PERMITTED:
            with self.subTest(variable=name):
                result = self.sourced(preset={name: "1"})
                self.assertEqual(result[name], "1")

    def test_a_partial_git_config_injection_is_reported_too(self):
        """GIT_CONFIG_KEY_n only bites through GIT_CONFIG_COUNT.

        It is named anyway, so half an injection is reported rather than
        left in place for the next run to complete.
        """
        result = self.source(
            preset={"GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_VALUE_0": "/tmp/hooks"})
        self.assertNotEqual(result.status, 0)
        self.assertIn("GIT_CONFIG_KEY_0=core.hooksPath", result.stderr)
        self.assertIn("GIT_CONFIG_VALUE_0=/tmp/hooks", result.stderr)

    def test_the_refusal_names_what_is_deliberately_permitted(self):
        """So the reader is not left guessing whether to unset those."""
        result = self.source(preset={"PYTHONPATH": "/tmp/x"})
        for name in ("GIT_AUTHOR_*", "GIT_COMMITTER_*",
                     "GIT_CONFIG_GLOBAL"):
            self.assertIn(name, result.stderr)

    def test_there_is_no_waiver_and_the_refusal_says_so(self):
        result = self.source(preset={"LD_PRELOAD": "/tmp/evil.so"})
        self.assertIn("There is no waiver", result.stderr)
        self.assertIn("env -u", result.stderr)

    def test_a_writable_nominated_git_config_is_refused(self):
        """An isolation lever another account can write is an injection
        point wearing the clothes of a containment measure."""
        path = os.path.join(self.root, "global.gitconfig")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        os.chmod(path, 0o666)
        result = self.source(preset={"GIT_CONFIG_GLOBAL": path})
        self.assertNotEqual(result.status, 0)
        self.assertIn("writable by group or other", result.stderr)

    def test_an_owner_only_nominated_git_config_is_honoured(self):
        path = os.path.join(self.root, "global.gitconfig")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        os.chmod(path, 0o600)
        result = self.sourced(preset={"GIT_CONFIG_GLOBAL": path})
        self.assertEqual(result["GIT_CONFIG_GLOBAL"], path)

    def test_a_nominated_git_config_that_is_absent_is_refused(self):
        result = self.source(
            preset={"GIT_CONFIG_GLOBAL":
                    os.path.join(self.root, "absent.gitconfig")})
        self.assertNotEqual(result.status, 0)
        self.assertIn("does not name a", result.stderr)

    def test_dev_null_is_accepted_as_a_nominated_config(self):
        """git's own documented idiom for "no configuration at all"."""
        self.sourced(preset={"GIT_CONFIG_GLOBAL": "/dev/null"})

    def test_the_user_site_directory_is_kept_out_of_every_interpreter(
            self):
        """PYTHONNOUSERSITE=1 is `-s` without fifteen call sites.

        ~/.local/lib/pythonX.Y/site-packages is writable by this account
        and is not one of the paths the executable verification covers, so
        a module planted there would shadow one of the six pinned,
        hash-locked distributions.
        """
        self.assertEqual(self.sourced()["PYTHONNOUSERSITE"], "1")

    def test_the_safe_path_flag_is_deliberately_not_set(self):
        """-P would drop the script's own directory from sys.path, and
        this pipeline's modules import each other by name."""
        result = self.sourced()
        self.assertNotIn("PYTHONSAFEPATH", result.environment)

    def test_the_sanitiser_runs_before_anything_else(self):
        """A check that ran after the first child would be reporting on
        an environment that had already been used."""
        with open(ENV_SH, encoding="utf-8") as handle:
            source = handle.read()
        call = source.index("if ! playthrough_sanitize_environment; then")
        self.assertLess(call, source.index("_playthrough_script_dir=\"$("))
        self.assertLess(call, source.index("_playthrough_repo_root=\"$("))


class TestThePathAncestryGate(EnvFixture):
    """The road to the evidence, not just the mode of the destination.

    A security review found this tree checking the type, owner and mode of
    every directory it wrote into and of every ancestor BELOW its own
    verified anchor, and stopping there -- so on a host whose /tmp is mode
    2777 (world-writable and NOT sticky) the fact that the anchor's own
    NAME could be renamed out from under it was never measured.  It is
    measured now, a launch REFUSES on it, and the waiver that proceeds is
    a registered trust bypass.
    """

    def ancestry(self, path, after=""):
        """Run playthrough_untrusted_ancestor over `path`."""
        return self.sourced(
            after='ANCESTOR="$(playthrough_untrusted_ancestor "%s" '
                  '|| printf "")"\nexport ANCESTOR\n%s' % (path, after))

    def test_a_safe_road_reports_nothing(self):
        safe = os.path.join(self.root, "safe")
        os.makedirs(safe, mode=0o700)
        if unsafe_ancestor(safe) is not None:
            self.skipTest("this sandbox's own base has an unsafe road, "
                          "so there is no safe path to measure")
        self.assertEqual(self.ancestry(safe)["ANCESTOR"], "")

    def test_a_world_writable_non_sticky_ancestor_is_named(self):
        parent = os.path.join(self.root, "open")
        child = os.path.join(parent, "under")
        os.makedirs(child, mode=0o700)
        os.chmod(parent, 0o777)
        self.assertEqual(self.ancestry(child)["ANCESTOR"], parent)

    def test_the_sticky_bit_makes_a_world_writable_road_safe(self):
        """The whole distinction, and why a 1777 /tmp is not a finding.

        Without the sticky bit any account with write permission may
        rename or unlink any entry regardless of owner; with it, only the
        entry's owner may.
        """
        parent = os.path.join(self.root, "sticky")
        child = os.path.join(parent, "under")
        os.makedirs(child, mode=0o700)
        os.chmod(parent, 0o1777)
        reported = self.ancestry(child)["ANCESTOR"]
        self.assertNotEqual(
            reported, parent,
            msg="a 1777 directory is not an unsafe road")
        # The walk goes PAST it rather than stopping, so whatever it does
        # report is further up -- and on a host whose /tmp is a
        # conventional 1777 the whole road is clean.
        self.assertEqual(reported, unsafe_ancestor(child) or "")
        # And the same directory WITHOUT the bit is reported, which is
        # what proves the bit is what made the difference.
        os.chmod(parent, 0o777)
        self.assertEqual(self.ancestry(child)["ANCESTOR"], parent)

    def test_the_walk_reaches_the_root_rather_than_an_anchor(self):
        """It is the ROAD that is measured, however far up it goes."""
        deep = os.path.join(self.root, "a", "b", "c", "d")
        os.makedirs(deep, mode=0o700)
        opened = os.path.join(self.root, "a")
        os.chmod(opened, 0o777)
        self.assertEqual(self.ancestry(deep)["ANCESTOR"], opened)

    def test_the_gate_refuses_an_unsafe_road_by_default(self):
        result = self.source(
            after='playthrough_untrusted_ancestor() { printf "/openish"; }'
                  '\nplaythrough_check_path_ancestry\n'
                  'export GATE="$?"')
        self.assertEqual(result.get("GATE"), "1")
        self.assertIn("refusing to launch", result.stderr)
        self.assertIn("sticky bit", result.stderr)

    def test_the_waiver_proceeds_and_is_a_registered_bypass(self):
        result = self.source(
            preset={"PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY":
                    "auditing on the provisioning host"},
            after='playthrough_untrusted_ancestor() { printf "/openish"; }'
                  '\nplaythrough_check_path_ancestry\n'
                  'export GATE="$?"')
        self.assertEqual(result.get("GATE"), "0")
        self.assertIn("proceeding with an unsafe path ancestry",
                      result.stderr)
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "diagnostic")

    def test_a_safe_road_passes_the_gate_silently(self):
        result = self.source(
            after='playthrough_untrusted_ancestor() { return 1; }'
                  '\nPLAYTHROUGH_RUNTIME_UNTRUSTED_ANCESTOR=""\n'
                  'playthrough_check_path_ancestry\nexport GATE="$?"')
        self.assertEqual(result.get("GATE"), "0")
        self.assertEqual(result["PLAYTHROUGH_REPO_UNTRUSTED_ANCESTOR"], "")

    def test_the_launch_consults_the_gate(self):
        with open(ENV_SH, encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("playthrough_headless_up() {")
        end = source.index("\nplaythrough_mkdirs()", start)
        self.assertIn("playthrough_check_path_ancestry",
                      source[start:end])


class TestForeignWriteIsDeniedOnTheArtifactTree(EnvFixture):
    """No account but the owner may rewrite the evidence.

    A security review measured fifteen directories at 2777 and a hundred
    and fifty-one files at 0666 on the delivered tree -- the survivor's
    save, the engine's config, the captioned film and the acceptance
    report among them.  The property enforced is WRITE, not read: this
    tree is committed to a git repository and is meant to be read.
    """

    def deny(self, path, after=""):
        return self.sourced(
            after='playthrough_deny_foreign_write "%s" "the subject"\n'
                  'export DENIED="$?"\n%s' % (path, after))

    def test_a_world_writable_directory_is_tightened(self):
        path = os.path.join(self.root, "wide")
        os.makedirs(path, mode=0o777)
        os.chmod(path, 0o777)
        result = self.deny(path)
        self.assertEqual(result["DENIED"], "0")
        self.assertEqual(os.stat(path).st_mode & 0o022, 0)

    def test_a_world_writable_file_is_tightened(self):
        path = os.path.join(self.root, "wide-file")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("evidence\n")
        os.chmod(path, 0o666)
        result = self.deny(path)
        self.assertEqual(result["DENIED"], "0")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)

    def test_read_access_is_left_exactly_as_it_was(self):
        """Owner-only would protect nothing that is about to be
        published."""
        path = os.path.join(self.root, "readable")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("evidence\n")
        os.chmod(path, 0o646)
        self.deny(path)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)

    def test_a_repair_is_announced_rather_than_silent(self):
        path = os.path.join(self.root, "announced")
        os.makedirs(path, mode=0o777)
        os.chmod(path, 0o777)
        result = self.deny(path)
        self.assertIn("has been tightened", result.stderr)
        self.assertIn("another local account", result.stderr)

    def test_an_already_private_path_says_nothing(self):
        path = os.path.join(self.root, "already")
        os.makedirs(path, mode=0o700)
        result = self.deny(path)
        self.assertEqual(result["DENIED"], "0")
        self.assertEqual(result.stderr, "")

    def test_a_mode_that_cannot_be_read_is_fatal_not_assumed_safe(self):
        result = self.source(
            after='playthrough_deny_foreign_write '
                  '"%s/absent" "the subject"\nexport DENIED="$?"'
                  % self.root)
        self.assertEqual(result.get("DENIED"), "1")
        self.assertIn("cannot read the mode", result.stderr)

    def test_the_artifact_directories_are_held_to_it(self):
        with open(ENV_SH, encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("playthrough_mkdirs() {")
        end = source.index("\nplaythrough_deny_foreign_write()", start)
        self.assertIn("playthrough_deny_foreign_write",
                      source[start:end])


class TestTheTrustState(EnvFixture):
    """One computed answer about the environment, not seven warnings."""

    BYPASSES = (
        "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES",
        "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X",
        "PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK",
        "PLAYTHROUGH_ALLOW_VULNERABLE_PILLOW",
        "PLAYTHROUGH_ALLOW_ANY_COMPILER",
        # ADDED BY A SECURITY REVIEW, and it was right.  The end-of-life
        # platform waiver was deliberately kept out of this registry, on
        # the argument that an unmaintained release makes no reading
        # WRONG.  But the packages it leaves unpatched are the three that
        # photograph, decode and encode every frame -- ImageMagick's
        # `import`, ffmpeg and Xorg/Xvfb -- and recording a waiver in a
        # summary does not stop the next command from producing evidence
        # under it.  It forces the diagnostic state now, and the four
        # stages that make production media refuse under it.
        "PLAYTHROUGH_ALLOW_EOL_PLATFORM",
        # A component of the path to this run's own evidence or runtime
        # state can be renamed or replaced by another local account, so a
        # frame, a save or a lock may not be the one this pipeline wrote.
        # playthrough_check_path_ancestry refuses a launch on it and this
        # is the waiver that proceeds; it belongs in the registry for the
        # same reason the platform waiver does -- the launch and the
        # capture consult this list and nothing else.
        "PLAYTHROUGH_ALLOW_UNSAFE_PATH_ANCESTRY",
    )

    def test_the_registry_lists_every_bypass_this_pipeline_has(self):
        """The list is the contract; a missing name is a hole in it.

        Every variable that relaxes a check anywhere in the pipeline has
        to appear here, because this list is the only thing the launch
        and the capture consult before producing evidence.
        """
        published = self.sourced()["PLAYTHROUGH_TRUST_BYPASS_VARS"]
        self.assertEqual(sorted(published.split()),
                         sorted(self.BYPASSES))

    def test_a_clean_environment_is_trusted(self):
        result = self.sourced()
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")
        self.assertEqual(result["PLAYTHROUGH_TRUST_BYPASSES"], "")

    def test_each_bypass_moves_the_state_to_diagnostic(self):
        for name in self.BYPASSES:
            with self.subTest(bypass=name):
                result = self.sourced(preset={name: "1"})
                self.assertEqual(
                    result["PLAYTHROUGH_TRUST_STATE"], "diagnostic")
                self.assertEqual(
                    result["PLAYTHROUGH_TRUST_BYPASSES"], name)

    def test_a_value_of_zero_is_not_a_bypass(self):
        result = self.sourced(preset={
            "PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK": "0",
            "PLAYTHROUGH_ALLOW_ANY_COMPILER": ""})
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")

    def test_any_other_value_is_treated_as_set(self):
        """Fail closed: a misspelt override is still an intention."""
        result = self.sourced(preset={
            "PLAYTHROUGH_ALLOW_ANY_COMPILER": "true"})
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "diagnostic")

    def test_the_state_is_recomputed_at_every_call(self):
        """A bypass exported AFTER sourcing still counts.

        A state memoised at source time would be a statement about the
        past, and a caller can export one of these variables at any
        point -- so the answer is recomputed, and the assertion below is
        what proves it rather than the comment.
        """
        result = self.sourced(
            after='export PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK=1\n'
                  'playthrough_trust_refresh || true\n'
                  'export LATE="${PLAYTHROUGH_TRUST_STATE}"\n'
                  'unset PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK\n'
                  'playthrough_trust_refresh || true\n'
                  'export AGAIN="${PLAYTHROUGH_TRUST_STATE}"')
        self.assertEqual(result.get("LATE"), "diagnostic")
        self.assertEqual(result.get("AGAIN"), "trusted")

    def test_the_assertion_refuses_and_explains(self):
        result = self.sourced(
            after='export PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X=1\n'
                  'if playthrough_assert_trusted "to capture"; then\n'
                  '    export GATE=passed\nelse\n'
                  '    export GATE=refused\nfi')
        self.assertEqual(result.get("GATE"), "refused")
        self.assertIn("inject keystrokes", result.stderr)
        self.assertIn("PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X", result.stderr)
        self.assertIn("refusing to capture", result.stderr)

    def test_the_assertion_passes_a_clean_environment_silently(self):
        result = self.sourced(
            after='if playthrough_assert_trusted "to capture"; then\n'
                  '    export GATE=passed\nfi')
        self.assertEqual(result.get("GATE"), "passed")
        self.assertNotIn("refusing", result.stderr)

    def test_every_bypass_says_what_it_endangers(self):
        for name in self.BYPASSES:
            with self.subTest(bypass=name):
                result = self.sourced(
                    after='playthrough_trust_reason "%s" >&2' % name)
                self.assertGreater(
                    len(result.stderr.strip()), 20,
                    msg=("a refusal that names a variable and stops is "
                         "a dead end for whoever hits it"))

    def test_the_summary_records_the_state(self):
        result = subprocess.run(
            ["/usr/bin/env", "-i", "PATH=" + BASE_PATH,
             "PLAYTHROUGH_ALLOW_ANY_COMPILER=1",
             "/bin/bash", "--noprofile", "--norc", ENV_SH],
            cwd=REPO_ROOT, capture_output=True, timeout=120)
        text = result.stdout.decode("utf-8", "replace")
        self.assertIn("PLAYTHROUGH_TRUST_STATE", text)
        self.assertIn("diagnostic", text)
        self.assertIn("PLAYTHROUGH_ALLOW_ANY_COMPILER", text)


class TestTheTrustedUtilityBootstrap(EnvFixture):
    """The programs the security checks are MADE OF are resolved first.

    Every ownership and mode check in this file is a call to `stat`,
    `readlink` or `chmod`.  Resolving those through the inherited PATH
    put the answer to every check in the hands of whoever could write a
    directory on it, and a missing `stat` was answered with `return 0` --
    an unperformed check reporting success, which no caller can tell from
    a verified one.  These tests hold the two halves of that fix: the
    utilities come from fixed system directories, and an inability to
    verify is a refusal AND a trust state rather than a warning.
    """

    UTILITIES = ("STAT", "READLINK", "CHMOD")

    def test_each_utility_resolves_to_a_fixed_system_directory(self):
        result = self.sourced()
        self.assertEqual(result["PLAYTHROUGH_UTILITY_TRUST"], "trusted")
        for name in self.UTILITIES:
            with self.subTest(utility=name):
                path = result["PLAYTHROUGH_UTIL_" + name]
                self.assertTrue(
                    os.path.isabs(path),
                    msg="a utility is invoked by absolute path")
                self.assertTrue(
                    path.startswith(("/usr/bin/", "/bin/",
                                     "/usr/sbin/", "/sbin/")),
                    msg=("resolved from the trusted directories, never "
                         "from PATH: %r" % path))
                self.assertTrue(os.path.isfile(path))

    def test_a_thin_path_no_longer_costs_the_checks_their_tools(self):
        """The case the old fail-open branch existed for.

        `thin_path` carries no `stat`, so the previous implementation
        warned and returned success from every ownership check.  Now the
        utilities are found on disk rather than on PATH, so the checks
        actually run -- and the source stays silent, which is the proof
        that nothing fell back.
        """
        result = self.source(path=self.thin_path())
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertEqual(result["PLAYTHROUGH_UTILITY_TRUST"], "trusted")
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")
        self.assertEqual(result["PLAYTHROUGH_TRUST_UNVERIFIED"], "")
        self.assertNotIn("could not be verified", result.stderr)

    def test_an_unresolvable_utility_fails_closed(self):
        """No `stat` anywhere means REFUSED, not "carried on".

        The sabotage points the trusted directory list at an empty
        directory, which is the only way to reach this state on a host
        that has coreutils.  The source must fail, the diagnostic must
        say the check could not be performed, and the reason must be
        exported so a stage that never made the call can still read it.
        """
        empty = os.path.join(self.root, "no-utilities")
        os.makedirs(empty, exist_ok=True)
        root, copy = self.sabotaged_copy(
            'PLAYTHROUGH_TRUSTED_UTIL_DIRS="/usr/bin /bin /usr/sbin '
            '/sbin"',
            'PLAYTHROUGH_TRUSTED_UTIL_DIRS="%s"' % empty,
            name="no-utilities")
        result = self.source(script=copy, cwd=root)
        self.assertNotEqual(
            result.status, 0,
            msg=("a security check that cannot be performed must not "
                 "report success: %s" % result.stderr))
        self.assertIn("cannot be performed", result.stderr)
        self.assertIn("REFUSAL", result.stderr)

    def test_an_unperformable_check_holds_the_trust_state(self):
        """It is recorded, not only warned about.

        The state is what launch_game.sh and capture.sh consult, so a
        check that could not run has to reach them the same way a
        deliberate bypass does.
        """
        result = self.sourced(
            after='playthrough_trust_unverifiable "a probe could not '
                  'read an owner"\n'
                  'export STATE="${PLAYTHROUGH_TRUST_STATE}"\n'
                  'export WHY="${PLAYTHROUGH_TRUST_UNVERIFIED}"\n'
                  'if playthrough_assert_trusted "to capture"; then\n'
                  '    export GATE=passed\nelse\n'
                  '    export GATE=refused\nfi')
        self.assertEqual(result.get("STATE"), "diagnostic")
        self.assertIn("could not read an owner", result.get("WHY", ""))
        self.assertEqual(
            result.get("GATE"), "refused",
            msg=("production capture must refuse while any check is "
                 "unverified, exactly as it refuses a named bypass"))

    def test_the_reason_is_recorded_once_however_often_it_fires(self):
        result = self.sourced(
            after='playthrough_trust_unverifiable "one reason"\n'
                  'playthrough_trust_unverifiable "one reason"\n'
                  'export WHY="${PLAYTHROUGH_TRUST_UNVERIFIED}"')
        self.assertEqual(result.get("WHY"), "one reason")

    def test_the_utility_name_vocabulary_is_closed(self):
        """Nothing resembling a path can be appended to a trusted dir."""
        result = self.sourced(
            after='if playthrough_trusted_util "../../tmp/evil"; then\n'
                  '    export RESOLVED=yes\nelse\n'
                  '    export RESOLVED=no\nfi\n'
                  'if playthrough_trusted_util "stat"; then\n'
                  '    export PLAIN=yes\nelse\n'
                  '    export PLAIN=no\nfi')
        self.assertEqual(result.get("RESOLVED"), "no")
        self.assertEqual(result.get("PLAIN"), "yes")


class TestTheToolPackageTable(EnvFixture):
    """A missing tool says what to install."""

    def test_each_command_names_the_package_that_ships_it(self):
        # Every ImageMagick entry point the pipeline calls is listed
        # here, `compare` included: it is what verify_artifacts.sh
        # compares two extracted frames with, it ships in the same
        # package as convert and identify, and it used to fall through
        # to "unknown package".
        pairs = (("Xvfb", "xvfb"), ("openbox", "openbox"),
                 ("xdpyinfo", "x11-utils"), ("xdotool", "xdotool"),
                 ("import", "imagemagick"), ("convert", "imagemagick"),
                 ("identify", "imagemagick"),
                 ("compare", "imagemagick"),
                 ("ffmpeg", "ffmpeg"), ("ffprobe", "ffmpeg"),
                 ("tesseract", "tesseract-ocr"),
                 ("scrot", "scrot"), ("make", "make"),
                 ("ccache", "ccache"), ("grep", "grep"),
                 ("sed", "sed"), ("supervisorctl", "supervisor"),
                 # The sequencer's capacity model measures with df and
                 # du and fingerprints with find and sha256sum; each of
                 # the four is named in a require call, so each has to
                 # name a package rather than falling through to
                 # "unknown".
                 ("df", "coreutils"), ("du", "coreutils"),
                 ("mv", "coreutils"), ("sha256sum", "coreutils"),
                 ("find", "findutils"))
        after = "\n".join(
            'PKG_%d="$(playthrough_tool_package %s)"\nexport PKG_%d'
            % (index, tool, index)
            for index, (tool, _) in enumerate(pairs))
        result = self.sourced(after=after)
        for index, (tool, package) in enumerate(pairs):
            with self.subTest(tool=tool):
                self.assertEqual(result.get("PKG_%d" % index), package)

    def test_an_unknown_command_says_so_rather_than_guessing(self):
        result = self.sourced(
            after='PKG="$(playthrough_tool_package frobnicate)"\n'
                  'export PKG')
        self.assertEqual(result.get("PKG"), "unknown package")

    def test_a_missing_tool_is_reported_with_its_package(self):
        result = self.sourced(
            after='if playthrough_require_tools definitely-absent-tool;'
                  ' then\n    export REQUIRED=accepted\n'
                  'else\n    export REQUIRED=refused\nfi')
        self.assertEqual(result.get("REQUIRED"), "refused")
        self.assertIn("missing required command", result.stderr)
        self.assertIn("definitely-absent-tool", result.stderr)

    def test_every_missing_tool_is_reported_in_one_pass(self):
        result = self.sourced(
            after='playthrough_require_tools absent-one absent-two'
                  ' 2>/dev/null || true\n'
                  'MISSING="$(playthrough_require_tools absent-one'
                  ' absent-two 2>&1 >/dev/null | grep -c'
                  ' "absent-two")"\nexport MISSING')
        self.assertEqual(
            result.get("MISSING"), "1",
            msg=("reporting all of them rather than dying on the first "
                 "is the difference between one fix and three"))

    def test_a_present_tool_is_accepted(self):
        result = self.sourced(
            after='if playthrough_require_tools mkdir; then\n'
                  '    export REQUIRED=ok\nfi')
        self.assertEqual(result.get("REQUIRED"), "ok")

    def test_the_display_probe_separates_a_missing_tool_from_no_server(self):
        holder = self.thin_path()
        result = self.source(
            path=holder,
            after='playthrough_display_probe\nexport PROBE=$?')
        self.assertEqual(
            result.get("PROBE"), "2",
            msg=("with x11-utils absent the question was never asked, "
                 "and reporting that as 'no X server' sends an "
                 "operator to debug a display that is running "
                 "perfectly"))


class TestThePlatformGate(EnvFixture):
    """An out-of-support platform is REFUSED, not warned about.

    playthrough_check_platform used to warn and continue, with the hard
    failure opt-in via PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=1 -- which
    is a safeguard that is off.  It is inverted now, and these tests hold
    the inversion in both directions.

    THE OS IS FAKED BY REDEFINING playthrough_os_release AFTER SOURCING,
    which isolates the part under test here -- the dated table, the
    date comparison, the waiver and the retired knob -- from the
    separate question of which file the keys were read out of.  The
    alternative, asserting against whatever this host happens to be,
    would make the suite pass or fail for a reason that has nothing to
    do with the code.  The memo flags are cleared in the same breath so
    the classification is recomputed against the fake.

    The file-reading half is covered by
    TestThePlatformSourceCanBeNominated, which nominates a real file
    through PLAYTHROUGH_OS_RELEASE instead of replacing the reader.

    The two releases named are chosen so the assertions cannot expire in
    one direction: ubuntu:24.10 reached end of life on 2025-07-10 and
    will stay past it, and ubuntu:26.04 runs to 2031-04.
    """

    def gate(self, release="ubuntu", version="24.10",
             pretty="Ubuntu 24.10", preset=None):
        """Run the gate against a fabricated /etc/os-release."""
        after = (
            'playthrough_os_release() {\n'
            '    case "$1" in\n'
            '        ID) printf "%s" "%s" ;;\n'
            '        VERSION_ID) printf "%s" "%s" ;;\n'
            '        PRETTY_NAME) printf "%s" "%s" ;;\n'
            '    esac\n'
            '}\n'
            'unset PLAYTHROUGH_PLATFORM_CHECKED\n'
            'unset PLAYTHROUGH_PLATFORM_WARNED\n'
            'unset PLAYTHROUGH_PLATFORM_KNOB_WARNED\n'
            'playthrough_check_platform\n'
            'printf "GATE=%%s\\n" "$?"\n'
            'printf "VERDICT=%%s\\n" "${PLAYTHROUGH_PLATFORM_SUPPORTED}"\n'
            'printf "WAIVER=%%s\\n" "${PLAYTHROUGH_PLATFORM_WAIVER}"\n'
            % ("%s", release, "%s", version, "%s", pretty))
        result = self.sourced(preset=preset, after=after)
        reported = {}
        for line in result.source_output.splitlines():
            name, _, value = line.partition("=")
            reported[name] = value
        return reported, result.stderr

    # -- the refusal -------------------------------------------------

    def test_an_end_of_life_release_is_refused(self):
        reported, stderr = self.gate()
        self.assertEqual(reported.get("VERDICT"), "no")
        self.assertEqual(reported.get("GATE"), "1")
        self.assertIn("FATAL", stderr)

    def test_the_refusal_names_the_release_and_its_date(self):
        _, stderr = self.gate()
        self.assertIn("Ubuntu 24.10", stderr)
        self.assertIn("2025-07-10", stderr)

    def test_the_refusal_names_the_migration_target(self):
        _, stderr = self.gate()
        self.assertIn("Ubuntu 26.04 LTS", stderr)

    def test_the_refusal_names_the_waiver(self):
        """A refusal that does not say what to do is half a diagnosis."""
        _, stderr = self.gate()
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM", stderr)

    def test_an_untabulated_release_is_also_refused(self):
        """"Cannot tell" is not "supported"."""
        reported, stderr = self.gate("fedora", "43", "Fedora Linux 43")
        self.assertEqual(reported.get("VERDICT"), "unverified")
        self.assertEqual(reported.get("GATE"), "1")
        self.assertIn("Fedora Linux 43", stderr)

    # -- the waiver --------------------------------------------------

    def test_a_waiver_with_a_reason_is_honoured(self):
        reported, stderr = self.gate(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": "the only host there is"})
        self.assertEqual(reported.get("GATE"), "0")
        self.assertEqual(reported.get("VERDICT"), "no")
        self.assertIn("PLATFORM WAIVER", stderr)

    def test_the_waiver_reason_travels_with_the_record(self):
        """The reason is the only part a later reader needs."""
        reason = "container image cannot be replaced from inside it"
        reported, stderr = self.gate(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": reason})
        self.assertEqual(reported.get("WAIVER"), reason)
        self.assertIn(reason, stderr)

    def test_the_waiver_also_covers_an_untabulated_release(self):
        reported, _ = self.gate(
            "fedora", "43", "Fedora Linux 43",
            preset={"PLAYTHROUGH_ALLOW_EOL_PLATFORM": "confirmed in "
                                                      "support by hand"})
        self.assertEqual(reported.get("GATE"), "0")

    def test_a_waiver_of_zero_is_no_waiver(self):
        """Fail closed on a value that says nothing."""
        reported, _ = self.gate(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": "0"})
        self.assertEqual(reported.get("GATE"), "1")
        self.assertEqual(reported.get("WAIVER"), "")

    def test_an_empty_waiver_is_no_waiver(self):
        reported, _ = self.gate(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": ""})
        self.assertEqual(reported.get("GATE"), "1")

    def test_the_waiver_is_a_trust_bypass(self):
        """It was deliberately kept out of the registry, and that was
        the wrong call.

        The argument was that an end-of-life platform makes no reading
        WRONG -- it raises the risk that a parser has an unfixed defect,
        which needs hostile input to matter -- so recording the waiver in
        the summary was treated as enough.  A security review answered
        with this file's own reasoning about every other relaxable check:
        a warning on stderr does not stop the next command from capturing
        a frame and presenting it as evidence.  The packages left
        unpatched are the three that photograph, decode and encode every
        frame.  So it forces the diagnostic state, and the four stages
        that make production media refuse under it.
        """
        result = self.sourced(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": "a reason"})
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                      result["PLAYTHROUGH_TRUST_BYPASS_VARS"])
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "diagnostic")
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                      result.get("PLAYTHROUGH_TRUST_BYPASSES", ""))

    def test_the_waiver_says_what_it_costs(self):
        """The consequence is stated where an operator will read it."""
        _reported, stderr = self.gate(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": "the only host available"})
        self.assertIn("PLATFORM WAIVER", stderr)
        self.assertIn("TRUST BYPASS", stderr)
        self.assertIn("diagnosis on this host, not evidence", stderr)

    def test_the_waiver_has_a_reason_of_its_own(self):
        """A refusal that names a variable and stops explains nothing."""
        result = self.sourced(after=(
            'playthrough_trust_reason '
            'PLAYTHROUGH_ALLOW_EOL_PLATFORM\n'))
        for expected in ("ImageMagick", "ffmpeg", "Xorg",
                         "no further security fixes"):
            self.assertIn(expected, result.source_output)

    def test_an_empty_waiver_leaves_the_state_trusted(self):
        """Registered is not the same as active."""
        result = self.sourced(preset={
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": ""})
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")

    # -- a supported platform ----------------------------------------

    def test_a_supported_release_passes_silently(self):
        reported, stderr = self.gate("ubuntu", "26.04",
                                     "Ubuntu 26.04 LTS")
        self.assertEqual(reported.get("VERDICT"), "yes")
        self.assertEqual(reported.get("GATE"), "0")
        self.assertNotIn("PLATFORM WAIVER", stderr)
        self.assertNotIn("end of life", stderr)

    # -- the classification cannot be handed to it -------------------

    def test_the_verdict_cannot_be_forged_by_the_caller(self):
        """MEASURED, not theorised, and it is why nothing is memoised.

        The classification used to be cached in exported variables behind
        a PLAYTHROUGH_PLATFORM_CHECKED flag, on the reasonable-sounding
        grounds that /etc/os-release cannot change during a run.  But this
        file is SOURCED into the caller's shell, so every one of those
        variables was an input as well as an output, and presetting two
        of them returned success on an end-of-life host with no waiver, no
        warning and PLAYTHROUGH_TRUST_STATE=trusted -- a silent forgery of
        the very verdict the trust-bypass registry now depends on.
        """
        forged = {
            "PLAYTHROUGH_PLATFORM_CHECKED": "1",
            "PLAYTHROUGH_PLATFORM_SUPPORTED": "yes",
            "PLAYTHROUGH_PLATFORM": "Forged Linux 99.99",
            "PLAYTHROUGH_PLATFORM_EOL": "2099-01",
        }
        reported, _ = self.gate("ubuntu", "24.10", "Ubuntu 24.10",
                                preset=forged)
        self.assertEqual(
            reported.get("VERDICT"), "no",
            msg="the preset verdict is discarded, not honoured")
        self.assertEqual(reported.get("GATE"), "1")

    def test_the_platform_fields_are_outputs_only(self):
        """Whatever the caller set is overwritten, every call."""
        result = self.sourced(preset={
            "PLAYTHROUGH_PLATFORM": "Forged Linux 99.99",
            "PLAYTHROUGH_ALLOW_EOL_PLATFORM": "a reason"},
            after='playthrough_check_platform\n')
        self.assertNotEqual(result["PLAYTHROUGH_PLATFORM"],
                            "Forged Linux 99.99")
        self.assertTrue(result["PLAYTHROUGH_PLATFORM_SOURCE"])

    # -- where the platform facts are read from ----------------------

    def nominated(self, body, root_has_git):
        """Source env.sh in a sandbox that nominates its own facts."""
        root, script = self.sandbox_checkout(
            name="nominated-git" if root_has_git else "nominated-plain")
        if root_has_git:
            os.makedirs(os.path.join(root, ".git"))
        nomination = os.path.join(root, "os-release")
        with open(nomination, "w", encoding="utf-8") as handle:
            handle.write(body)
        result = self.sourced(
            script=script, cwd=root,
            preset={"PLAYTHROUGH_OS_RELEASE": nomination},
            after='playthrough_check_platform\n'
                  'printf "GATE=%s\\n" "$?"\n')
        return result, nomination

    def test_a_nomination_is_honoured_in_a_tree_git_does_not_track(self):
        """The suites' own sandboxes, and nothing relaxed by it.

        The check runs in FULL against the nominated file -- this one
        declares a release that really is in support -- so it passes
        because it passes.
        """
        result, nomination = self.nominated(
            'ID=ubuntu\nVERSION_ID="24.04"\n'
            'PRETTY_NAME="Ubuntu 24.04.3 LTS"\n', False)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         nomination)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SUPPORTED"], "yes")
        self.assertIn("GATE=0", result.source_output)
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")

    def test_a_nomination_still_refuses_an_unsupported_release(self):
        """It says which host to believe, not what to conclude."""
        result, _ = self.nominated(
            'ID=ubuntu\nVERSION_ID="24.10"\n'
            'PRETTY_NAME="Ubuntu 24.10"\n', False)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SUPPORTED"], "no")
        self.assertIn("GATE=1", result.source_output)

    def test_a_nomination_is_ignored_in_a_git_working_tree(self):
        """THE PROPERTY THAT MAKES IT SAFE, and it is verified.

        A tree git tracks can publish artifacts, and the platform facts
        for a run that can publish are the host's own.  Deleting .git to
        reach the nomination would leave a record that can never be
        committed, which is self-defeating rather than a bypass.
        """
        result, nomination = self.nominated(
            'ID=ubuntu\nVERSION_ID="24.04"\n'
            'PRETTY_NAME="Ubuntu 24.04.3 LTS"\n', True)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")
        self.assertNotEqual(result["PLAYTHROUGH_PLATFORM"],
                            "Ubuntu 24.04.3 LTS")
        self.assertIn("IGNORED", result.stderr)
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM", result.stderr)
        self.assertNotIn(nomination,
                         result["PLAYTHROUGH_PLATFORM_SOURCE"])

    def test_an_unreadable_nomination_falls_back_and_says_so(self):
        root, script = self.sandbox_checkout(name="nomination-absent")
        result = self.sourced(
            script=script, cwd=root,
            preset={"PLAYTHROUGH_OS_RELEASE":
                    os.path.join(root, "no-such-file")},
            after='playthrough_check_platform\n')
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")
        self.assertIn("not a readable regular file", result.stderr)

    def test_the_default_source_is_the_hosts_own(self):
        result = self.sourced(after='playthrough_check_platform\n')
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")

    # -- the retired knob --------------------------------------------

    def test_the_retired_knob_no_longer_weakens_anything(self):
        reported, stderr = self.gate(preset={
            "PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM": "0"})
        self.assertEqual(reported.get("GATE"), "1")
        self.assertIn("no longer weakens", stderr)

    def test_the_retired_knob_is_answered_not_ignored(self):
        """An operator who set it believing it configured something has
        to be told it did not."""
        _, stderr = self.gate(preset={
            "PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM": "0"})
        self.assertIn("PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM=0", stderr)
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM", stderr)

    def test_the_knob_set_to_one_is_the_default_and_is_quiet(self):
        quiet = {"PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM": "1"}
        _, stderr = self.gate("ubuntu", "26.04", "Ubuntu 26.04 LTS",
                              preset=quiet)
        self.assertNotIn("no longer weakens", stderr)


class TestThePlatformSourceCanBeNominated(EnvFixture):
    """PLAYTHROUGH_OS_RELEASE lets a harness EMULATE a host.

    Every suite that exercises a production path -- capture.sh's frame
    write, launch_game.sh's preflight -- has to stand up on whatever
    host it is run on, and that host's platform verdict is not the thing
    under test.  The seam is the one those suites already use for the X
    server: a stub xdpyinfo that refuses a cookieless client the way an
    authenticated server does.

    IT EMULATES, IT DOES NOT RELAX.  The gate still runs, still consults
    the dated table, and still refuses an out-of-support answer read
    from a nominated file.  That is precisely what separates it from
    PLAYTHROUGH_ALLOW_EOL_PLATFORM, and the reason this one is not a
    trust bypass while that one now is.

    AND IT IS EXERCISED WHERE IT APPLIES: in a sandbox checkout that git
    does not track.  The nomination is honoured only there -- a verified
    property of the tree, not a claim a caller makes -- because a tree
    git tracks can publish artifacts and the platform facts for a run
    that can publish are the host's own.  These cases therefore source a
    copy of env.sh from a temporary root, which is exactly the shape of
    the sandboxes test_capture.py and test_launch_game.py stand up; the
    git-tree half of the rule has its own cases above.
    """

    def nomination_sandbox(self):
        """A checkout-shaped root, without .git, made once per test."""
        if not hasattr(self, "_nomination_sandbox"):
            self._nomination_sandbox = self.sandbox_checkout(
                name="nomination-seam")
        return self._nomination_sandbox

    def write(self, body, name="os-release"):
        """A platform source file inside the sandbox checkout."""
        root, _script = self.nomination_sandbox()
        path = os.path.join(root, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def supported(self, name="os-release"):
        """A release the table knows and that runs to 2031-04."""
        return self.write('ID=ubuntu\nVERSION_ID="26.04"\n'
                          'PRETTY_NAME="Ubuntu 26.04 LTS"\n', name)

    def expired(self, name="expired"):
        """A release the table knows and that ended 2025-07-10."""
        return self.write('ID=ubuntu\nVERSION_ID="24.10"\n'
                          'PRETTY_NAME="Ubuntu 24.10"\n', name)

    def check(self, source, preset=None):
        """Run the real gate with ``source`` nominated."""
        root, script = self.nomination_sandbox()
        environment = {"PLAYTHROUGH_OS_RELEASE": source}
        environment.update(preset or {})
        result = self.source(
            script=script, cwd=root, preset=environment,
            after='playthrough_check_platform\n'
                  'printf "GATE=%s\\n" "$?"\n')
        reported = {}
        for line in result.source_output.splitlines():
            name, _, value = line.partition("=")
            reported[name] = value
        return reported, result

    # -- it reads the file it was pointed at --------------------------

    def test_the_verdict_comes_from_the_nominated_file(self):
        reported, result = self.check(self.supported())
        self.assertEqual(reported.get("GATE"), "0")
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SUPPORTED"], "yes")
        self.assertEqual(result["PLAYTHROUGH_PLATFORM"],
                         "Ubuntu 26.04 LTS")

    def test_the_default_source_is_the_hosts_own_file(self):
        result = self.sourced(after="playthrough_check_platform")
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")
        self.assertNotIn("rather than from /etc/os-release",
                         result.stderr)

    # -- it does not excuse anything ----------------------------------

    def test_an_expired_nominated_release_is_still_refused(self):
        """The seam stands in for a host; it does not pardon one."""
        reported, result = self.check(self.expired())
        self.assertEqual(reported.get("GATE"), "1")
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SUPPORTED"], "no")
        self.assertIn("2025-07-10", result.stderr)

    def test_nominating_a_source_is_not_a_trust_bypass(self):
        """Emulating a host leaves the readings themselves sound."""
        result = self.sourced(preset={
            "PLAYTHROUGH_OS_RELEASE": self.supported()})
        self.assertNotIn("PLAYTHROUGH_OS_RELEASE",
                         result["PLAYTHROUGH_TRUST_BYPASS_VARS"])
        self.assertEqual(result["PLAYTHROUGH_TRUST_STATE"], "trusted")

    # -- it says so ---------------------------------------------------

    def test_the_nomination_is_disclosed_and_never_silent(self):
        """A verdict that is not the host's own says so.

        The disclosure is the EXPORTED source, not a stderr line.  An
        earlier version of this seam warned on every honoured nomination,
        which made sense while a nomination could be honoured in a real
        checkout; it cannot any more -- git tracks a publishable tree and
        the nomination is ignored there -- so the fact travels where a
        reader of the record will find it, in the contract, and stderr is
        reserved for the case where a nomination is REFUSED.
        """
        source = self.supported()
        _reported, result = self.check(source)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"], source)
        self.assertNotEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                            "/etc/os-release")

    def test_a_refused_nomination_is_warned_about_only_once(self):
        """A per-call warning in a long session is noise, not notice."""
        root, script = self.nomination_sandbox()
        result = self.source(
            script=script, cwd=root,
            preset={"PLAYTHROUGH_OS_RELEASE":
                    os.path.join(root, "no-such-file")},
            after='playthrough_check_platform\n'
                  'playthrough_check_platform\n')
        self.assertEqual(
            result.stderr.count("is not a readable regular file"), 1)

    def test_the_nomination_travels_in_the_environment_summary(self):
        """A session whose verdict is not its host's has to admit it."""
        source = self.supported()
        root, script = self.nomination_sandbox()
        result = self.sourced(
            script=script, cwd=root,
            preset={"PLAYTHROUGH_OS_RELEASE": source},
            after="playthrough_env_summary")
        self.assertIn("PLAYTHROUGH_PLATFORM_SOURCE",
                      result.source_output)
        # The summary shortens a path under the root it is describing, so
        # the line carries the file's name rather than its absolute path.
        self.assertIn(os.path.basename(source), result.source_output)

    # -- an unreadable nomination fails closed ------------------------

    def test_a_symlinked_source_is_not_followed(self):
        """A path that can be repointed after the check is not evidence.

        The link names a release that really is in support, so honouring
        it would read as `yes`; the assertion is that the verdict did not
        come from it at all.  Whatever the host's own answer then is, it
        is the host's -- which is the fail-closed direction, because a
        nomination can then never make a verdict more favourable than the
        truth.
        """
        root, _script = self.nomination_sandbox()
        link = os.path.join(root, "linked")
        os.symlink(self.supported("real"), link)
        _reported, result = self.check(link)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")
        self.assertIn("symbolic link", result.stderr)

    def test_a_missing_source_is_not_honoured(self):
        root, _script = self.nomination_sandbox()
        _reported, result = self.check(os.path.join(root, "absent"))
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")
        self.assertIn("is not a readable regular file", result.stderr)

    def test_a_directory_named_as_the_source_is_not_honoured(self):
        root, _script = self.nomination_sandbox()
        _reported, result = self.check(root)
        self.assertEqual(result["PLAYTHROUGH_PLATFORM_SOURCE"],
                         "/etc/os-release")
        self.assertIn("is not a readable regular file", result.stderr)


class TestTheSummaryDisclosesNoHostPath(EnvFixture):
    """The contract report is repository-relative.

    It is retained -- captured into logs, quoted into reports, read by
    people who have no business knowing where somebody else's clone
    lives -- and half its fields are absolute paths inside the checkout.
    """

    def summary(self):
        result = self.sourced(after="playthrough_env_summary")
        values = {}
        for line in result.source_output.splitlines()[1:]:
            parts = line.split(None, 1)
            if len(parts) == 2:
                values[parts[0]] = parts[1].strip()
        return values, result

    def test_no_field_carries_the_checkout_path(self):
        values, result = self.summary()
        root = result["PLAYTHROUGH_REPO_ROOT"]
        self.assertTrue(root.startswith("/"), msg="a sanity check")
        for name, value in values.items():
            with self.subTest(field=name):
                self.assertNotIn(
                    root, value,
                    msg=("%s discloses the checkout's host path; every "
                         "value goes through playthrough_redact"
                         % name))

    def test_the_artifact_paths_read_as_a_reader_would_type_them(self):
        values, _ = self.summary()
        self.assertEqual(values.get("PLAYTHROUGH_DIR"), "playthrough")
        self.assertEqual(values.get("PLAYTHROUGH_MANIFEST"),
                         "playthrough/manifest.jsonl")
        self.assertEqual(values.get("PLAYTHROUGH_MOVIE_CC"),
                         "playthrough/cata-play-cc.mp4")
        self.assertEqual(values.get("PLAYTHROUGH_REPO_ROOT"), ".")

    def test_the_runtime_root_is_reduced_to_a_marker(self):
        """The file name that matters, not the location that does not."""
        values, _ = self.summary()
        self.assertEqual(values.get("PLAYTHROUGH_RUNTIME_DIR"),
                         "<runtime>")
        self.assertTrue(
            values.get("XAUTHORITY", "").startswith("<runtime>/"),
            msg=values.get("XAUTHORITY"))

    def test_the_platform_verdict_is_in_the_record(self):
        values, _ = self.summary()
        self.assertIn(values.get("PLAYTHROUGH_PLATFORM_SUPPORTED"),
                      ("yes", "no", "unverified"))
        self.assertTrue(values.get("PLAYTHROUGH_PLATFORM_EOL"))
        self.assertTrue(values.get("PLAYTHROUGH_PLATFORM_WAIVER"))


class TestTheHelpersDoNotSilenceTheirCaller(EnvFixture):
    """A redirection on a bare `exec` is applied to THE SHELL.

    Two helpers closed a descriptor with

        exec {fd}>&- 2>/dev/null

    where the `2>/dev/null` was meant to swallow one possible complaint
    from the close.  What it actually did was point the CALLING SHELL's
    stderr at /dev/null for the rest of its life, so every warning,
    diagnosis and refusal that shell produced afterwards went nowhere.

    It was found by a preflight that starts an X server and then reports
    which stage failed: the verdict arrived on stdout and not one word of
    the diagnosis did.  The borrowed branch only runs when no lock is
    held, and the scripts that spawn under a lock skip it -- which is why
    it survived so long in a file this well covered.

    Each test below is paired with a SABOTAGED copy that restores the old
    line, so neither can pass because the situation stopped arising.
    """

    ALIVE = "STDERR_IS_STILL_ALIVE"

    def borrow_and_return(self):
        """Borrow a descriptor for a child and give it back."""
        return ('playthrough_child_close_fd\n'
                'playthrough_child_close_done\n'
                'printf "%s\\n" "' + self.ALIVE + '" >&2\n')

    def take_and_release_a_lock(self):
        """Take a real lock and release it, then try to be heard."""
        return ('playthrough_acquire_lock probe 5 >/dev/null 2>&1\n'
                'playthrough_release_lock\n'
                'printf "%s\\n" "' + self.ALIVE + '" >&2\n')

    def test_returning_a_borrowed_descriptor_keeps_stderr(self):
        result = self.source(after=self.borrow_and_return())
        self.assertIn(
            self.ALIVE, result.stderr,
            msg="playthrough_child_close_done silenced its caller's "
                "stderr; every diagnosis after the first detached "
                "spawn would be lost")

    def test_releasing_a_lock_keeps_stderr(self):
        result = self.source(after=self.take_and_release_a_lock())
        self.assertIn(
            self.ALIVE, result.stderr,
            msg="playthrough_release_lock silenced its caller's "
                "stderr; every script that releases its lock and then "
                "has something to report would report it into the void")

    def test_the_old_close_really_did_silence_it(self):
        # The guard on the guard.  If this ever stops failing, the two
        # tests above have stopped proving anything -- either the idiom
        # changed or bash did.
        root, script = self.sabotaged_copy(
            'if [ -e "/proc/self/fd/${PLAYTHROUGH_CHILD_CLOSE_FD}" ]\n'
            '                then\n'
            '                    exec {PLAYTHROUGH_CHILD_CLOSE_FD}>&-\n'
            '                fi',
            'exec {PLAYTHROUGH_CHILD_CLOSE_FD}>&- 2>/dev/null',
            name="old-close")
        result = self.source(script=script, cwd=root,
                             after=self.borrow_and_return())
        self.assertNotIn(
            self.ALIVE, result.stderr,
            msg="the sabotaged copy carries the ORIGINAL line, so it "
                "must lose the message; if it does not, these tests "
                "are measuring nothing")

    def test_a_second_return_is_not_an_error_either(self):
        # The complaint the old redirection was hiding: closing a
        # descriptor that is not open.  It is now prevented by asking
        # first, so calling twice is quiet AND keeps stderr.
        result = self.source(
            after=('playthrough_child_close_fd\n'
                   'playthrough_child_close_done\n'
                   'playthrough_child_close_done\n'
                   'printf "%s\\n" "' + self.ALIVE + '" >&2\n'))
        self.assertIn(self.ALIVE, result.stderr)
        self.assertNotIn("Bad file descriptor", result.stderr)


class TestTheRuntimeRootIsContained(EnvFixture):
    """Where the runtime root may and may not be.

    Both refusals answer a security finding rather than a preference: a
    runtime root inside the checkout is re-included by the terminal
    ``!/playthrough/**`` negation, so the X cookie and the pid files
    become committable; and a root outside the verified XDG runtime root
    has no verified ancestor at all, which is the redirect the private
    root exists to prevent.
    """

    def test_a_runtime_root_inside_the_checkout_is_refused(self):
        nominated = os.path.join(REPO_ROOT, "playthrough", "runtime")
        result = self.source(
            preset={"PLAYTHROUGH_RUNTIME_DIR": nominated})
        self.assertNotEqual(result.status, 0)
        self.assertIn("inside the checkout", result.stderr)
        self.assertFalse(
            os.path.exists(nominated),
            msg="a refused root must not be created on the way to the "
                "refusal")

    def test_the_repository_root_itself_is_refused(self):
        result = self.source(
            preset={"PLAYTHROUGH_RUNTIME_DIR": REPO_ROOT})
        self.assertNotEqual(result.status, 0)
        self.assertIn("inside the checkout", result.stderr)

    def test_a_root_that_contains_the_checkout_is_refused(self):
        result = self.source(
            preset={"PLAYTHROUGH_RUNTIME_DIR":
                    os.path.dirname(REPO_ROOT)})
        self.assertNotEqual(result.status, 0)
        self.assertIn("inside the checkout", result.stderr)

    def test_a_root_outside_the_verified_xdg_root_is_refused(self):
        nominated = os.path.join(self.root, "elsewhere")
        result = self.source(
            preset={"PLAYTHROUGH_RUNTIME_DIR": nominated})
        self.assertNotEqual(result.status, 0)
        self.assertIn("not beneath the verified XDG runtime root",
                      result.stderr)

    def test_a_traversal_cannot_smuggle_a_root_into_the_checkout(self):
        nominated = os.path.join(
            "/tmp/xdg%d" % SPARE_INDEX, "..", "..",
            os.path.relpath(REPO_ROOT, "/"), "playthrough", "sneaky")
        result = self.source(
            preset={"PLAYTHROUGH_RUNTIME_DIR": nominated,
                    "CLONE_INDEX": str(SPARE_INDEX)})
        self.assertNotEqual(
            result.status, 0,
            msg="the path is canonicalised before it is compared")
        self.assertIn("inside the checkout", result.stderr)

    def test_the_default_root_is_beneath_the_verified_xdg_root(self):
        result = self.sourced()
        self.assertEqual(
            result["PLAYTHROUGH_RUNTIME_DIR"],
            os.path.join(result["XDG_RUNTIME_DIR"], "playthrough"))


class TestTheInheritedAuthority(EnvFixture):
    """An XAUTHORITY is a credential, so inheriting one is verified.

    `-f` -- the whole of the old test -- says only that a path exists. A
    symlink makes ``xauth add`` write wherever it points, another
    account's file hands that account the display, and group or world
    access on the file does the same more slowly.
    """

    def authority(self, name, mode=0o600):
        """A file beneath the verified runtime root, at ``mode``."""
        base = os.path.join("/tmp/xdg%d" % SPARE_INDEX, "auth")
        if not os.path.exists("/tmp/xdg%d" % SPARE_INDEX):
            self.addCleanup(shutil.rmtree, "/tmp/xdg%d" % SPARE_INDEX,
                            True)
        os.makedirs(base, mode=0o700, exist_ok=True)
        os.chmod(base, 0o700)
        path = os.path.join(base, name)
        with open(path, "wb") as handle:
            handle.write(b"")
        os.chmod(path, mode)
        return path

    def inherit(self, path):
        return self.source(preset={"XAUTHORITY": path,
                                   "CLONE_INDEX": str(SPARE_INDEX)})

    def test_a_private_file_under_the_verified_root_is_inherited(self):
        result = self.inherit(self.authority("good"))
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertEqual(result["PLAYTHROUGH_XAUTHORITY_ORIGIN"],
                         "inherited")

    def test_a_group_readable_authority_is_not_inherited(self):
        path = self.authority("loose", mode=0o640)
        result = self.inherit(path)
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertEqual(result["PLAYTHROUGH_XAUTHORITY_ORIGIN"],
                         "pipeline")
        self.assertEqual(
            result["PLAYTHROUGH_XAUTHORITY_INHERITED_REJECTED"], path)
        self.assertIn("group or world access", result.stderr)

    def test_a_symlinked_authority_is_not_inherited(self):
        target = self.authority("target")
        link = os.path.join(os.path.dirname(target), "link")
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(target, link)
        result = self.inherit(link)
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertEqual(result["PLAYTHROUGH_XAUTHORITY_ORIGIN"],
                         "pipeline")
        self.assertIn("symbolic link", result.stderr)

    def test_a_rejected_authority_leaves_the_pipeline_cookie_in_place(self):
        result = self.inherit(self.authority("loose2", mode=0o644))
        self.assertEqual(result["XAUTHORITY"],
                         result["PLAYTHROUGH_XAUTHORITY"])

    def test_a_missing_authority_is_simply_not_inherited(self):
        result = self.inherit(
            os.path.join("/tmp/xdg%d" % SPARE_INDEX, "auth", "absent"))
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertEqual(result["PLAYTHROUGH_XAUTHORITY_ORIGIN"],
                         "pipeline")

    def test_an_inherited_authority_is_not_written_without_consent(self):
        # The write path, exercised without an X server: the refusal has
        # to come from the consent check rather than from xauth failing.
        path = self.authority("nocookie")
        result = self.source(
            preset={"XAUTHORITY": path, "CLONE_INDEX": str(SPARE_INDEX)},
            after="playthrough_ensure_xauth || true\n")
        self.assertIn("does not write into an authority file it did "
                      "not create", result.stderr)


class TestThePlatformWaiverText(EnvFixture):
    """The reason is untrusted text, and it is published evidence."""

    def waiver(self, value):
        return self.source(
            preset={"PLAYTHROUGH_ALLOW_EOL_PLATFORM": value},
            after=('printf "WAIVER[%s]\\n" '
                   '"$(playthrough_platform_waiver)" >&2\n'))

    def test_a_newline_cannot_forge_a_log_line(self):
        result = self.waiver("first line\nplaythrough: FATAL: forged")
        self.assertIn("WAIVER[first line playthrough: FATAL: forged]",
                      result.stderr)

    def test_a_control_character_is_removed(self):
        result = self.waiver("red \x1b[31mnot really\x1b[0m")
        self.assertNotIn("\x1b", result.stderr)

    def test_a_long_reason_is_bounded_and_marked(self):
        result = self.waiver("x" * 400)
        self.assertIn("x" * 160 + "...]", result.stderr)
        self.assertIn("published evidence", result.stderr)

    def test_a_short_clean_reason_is_untouched_and_quiet(self):
        result = self.waiver("no supported release is available here")
        self.assertIn("WAIVER[no supported release is available here]",
                      result.stderr)
        self.assertNotIn("reduced one-line form", result.stderr)

    def test_an_unset_waiver_is_empty(self):
        result = self.source(
            after=('printf "WAIVER[%s]\\n" '
                   '"$(playthrough_platform_waiver)" >&2\n'))
        self.assertIn("WAIVER[]", result.stderr)


class TestDisplayOwnership(EnvFixture):
    """"A server is answering" and "we started it" are two facts."""

    def setUp(self):
        super().setUp()
        # Several tests here write the ownership record, and it outlives
        # the fixture. Clearing it before and after each one is what makes
        # every test in this class measure the branch it names rather than
        # the branch its predecessor left set up.
        self.forget_record()
        self.addCleanup(self.forget_record)

    def probe(self, after):
        return self.source(preset={"CLONE_INDEX": str(SPARE_INDEX)},
                           after=after)

    def test_an_unserved_display_reports_absent(self):
        result = self.probe(
            'printf "STATE[%s]\\n" "$(playthrough_x_ownership_state)" '
            '>&2\n')
        self.assertIn("STATE[absent]", result.stderr)

    def test_the_record_names_the_display_and_the_checkout(self):
        result = self.probe(
            'playthrough_record_x_ownership pipeline 1 || exit 1\n'
            'cat "$(playthrough_x_ownership_record)" >&2\n')
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertIn("display=:%d" % (99 + SPARE_INDEX), result.stderr)
        self.assertIn("repo=%s" % REPO_ROOT, result.stderr)
        self.assertIn("kind=pipeline", result.stderr)

    def test_the_record_is_private(self):
        result = self.probe(
            'playthrough_record_x_ownership pipeline 1 || exit 1\n'
            'printf "RECORD[%s]\\n" '
            '"$(playthrough_x_ownership_record)" >&2\n')
        marker = "RECORD["
        line = [item for item in result.stderr.splitlines()
                if item.startswith(marker)]
        self.assertTrue(line, msg=result.stderr)
        path = line[0][len(marker):-1]
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        self.assertEqual(os.stat(path).st_mode & 0o077, 0)

    def test_a_foreign_display_holds_the_trust_state_at_diagnostic(self):
        # No server is started here, so the classification is driven
        # entirely by the record's absence: the assertion registers an
        # unverifiable check, which is what moves the state.
        result = self.probe(
            'playthrough_display_probe() { return 0; }\n'
            'playthrough_display_ready() { return 0; }\n'
            'playthrough_assert_x_ownership || true\n'
            'printf "TRUST[%s]\\n" "${PLAYTHROUGH_TRUST_STATE}" >&2\n')
        self.assertIn("TRUST[diagnostic]", result.stderr)
        # THE FOREIGN ARM'S OWN WORDING, not the stale arm's. The record is
        # cleared in setUp, so "nothing claims the server that is
        # answering" is the message under measurement; the stale arm's
        # "no longer running" phrasing is covered by
        # test_a_recorded_pid_that_is_not_an_x_server_is_stale, so
        # asserting the correct arm here loses no coverage and stops one
        # test from standing in for two.
        self.assertIn("this checkout did not start", result.stderr)
        self.assertIn("no ownership record exists", result.stderr)

    def test_a_recorded_pid_that_is_not_an_x_server_is_stale(self):
        """`$$` is alive and is not Xvfb, so it cannot be the server."""
        result = self.probe(
            'playthrough_display_probe() { return 0; }\n'
            'playthrough_display_ready() { return 0; }\n'
            'playthrough_record_x_ownership pipeline $$\n'
            'printf "STATE[%s]\\n" "$(playthrough_x_ownership_state)" '
            '>&2\n')
        self.assertIn("STATE[stale]", result.stderr)

    def test_recording_a_pid_with_no_identity_is_refused(self):
        """An unverifiable claim of ownership is worse than none.

        A record naming a process /proc knows nothing about would assert
        an ownership no later run could check -- and a MISSING record
        degrades the trust state, where a false one would not. So the
        recording refuses rather than writing a claim it cannot support.
        """
        result = self.probe(
            'playthrough_record_x_ownership pipeline 999999999\n'
            'printf "STATUS[%s]\\n" "$?" >&2\n'
            'if [ -f "$(playthrough_x_ownership_record)" ]; then\n'
            '    printf "WROTE[yes]\\n" >&2\n'
            'else\n'
            '    printf "WROTE[no]\\n" >&2\n'
            'fi\n')
        self.assertIn("STATUS[1]", result.stderr)
        self.assertIn("WROTE[no]", result.stderr)
        self.assertIn("no readable identity in /proc", result.stderr)


class TestTheXServerIsIdentifiedNotJustCounted(EnvFixture):
    """A pid and a command name are not an identity.

    A review measured this host and found THREE Xvfb processes answering
    for one display, with distinct start times, while the pid files named
    one pair and no ownership record existed at all. The ownership check
    compared the recorded pid against /proc/PID/comm and nothing else, so
    any process that happened to hold the recorded number and be called
    Xvfb would have been treated as the server this checkout started --
    and, running as root, signalled as such by the teardown.

    Linux recycles pids. "Some process called Xvfb is alive at 962316" and
    "the Xvfb we started at 962316 is still that process" are different
    claims, and only the second one is ownership.
    """

    def setUp(self):
        super().setUp()
        # THE RECORD PERSISTS BETWEEN TESTS.  It lives in the spare
        # index's runtime root rather than in this fixture's temporary
        # directory, so a record written by one test is still there for
        # the next -- measured, as a test expecting "no record" read back
        # the previous test's stale one instead.
        #
        # ITS PATH IS ASKED OF env.sh RATHER THAN SPELLED HERE.  A first
        # version hardcoded /tmp/xdg91/..., and the runtime anchor is
        # chosen at source time: on this host it resolves to
        # /run/playthrough-091/..., because the trusted-anchor selection
        # prefers a root-owned /run path over /tmp, whose mode is 2777 and
        # not sticky. The removal silently did nothing and the stale
        # record was still there.
        self.forget_record()
        self.addCleanup(self.forget_record)

    def probe(self, after):
        return self.source(preset={"CLONE_INDEX": str(SPARE_INDEX)},
                           after=after)

    # -- the identity itself -----------------------------------------

    def test_the_identity_has_five_fields(self):
        """comm, start time, uid, resolved exe, argument vector."""
        result = self.probe(
            'printf "ID[%s]\\n" "$(playthrough_pid_identity $$)" >&2\n')
        marker = "ID["
        line = [item for item in result.stderr.splitlines()
                if item.startswith(marker)][0]
        identity = line[len(marker):-1]
        self.assertTrue(identity, msg=result.stderr)
        fields = identity.split(" ")
        self.assertGreaterEqual(len(fields), 5)
        self.assertEqual(fields[0], "bash")
        self.assertRegex(fields[1], r"\A[0-9]+\Z")
        self.assertEqual(fields[2], str(os.getuid()))
        self.assertTrue(fields[3].startswith("/"), msg=fields[3])

    def test_a_later_process_of_the_same_program_differs(self):
        """The property the whole fix rests on, and its real granularity.

        Two processes of the SAME program under the same account differ in
        their start time, which is precisely what comm cannot see. But the
        start time is measured in CLOCK TICKS, so two processes launched
        inside one tick SHARE it: measured, two `sleep 30 &` started back
        to back both reported 58916125.

        That is not a hole in the check. The recorded pid is what selects
        which process is being asked about, and a pid cannot be recycled
        into the same tick its predecessor started in; the socket inode and
        the cookie digest are checked beside it. It does mean this test has
        to separate the two launches in order to measure what it claims to.
        """
        result = self.probe(
            'sleep 30 & first=$!\n'
            'sleep 0.2\n'
            'sleep 30 & second=$!\n'
            'printf "A[%s]\\n" '
            '"$(playthrough_pid_identity "${first}")" >&2\n'
            'printf "B[%s]\\n" '
            '"$(playthrough_pid_identity "${second}")" >&2\n'
            'kill "${first}" "${second}" 2>/dev/null || true\n')
        first = self.field(result, "A[")
        second = self.field(result, "B[")
        self.assertTrue(first and second, msg=result.stderr)
        self.assertNotEqual(first, second)
        # The program is the same; only the start time differs.
        self.assertEqual(first.split(" ")[0], second.split(" ")[0])
        self.assertEqual(first.split(" ")[3], second.split(" ")[3])
        self.assertNotEqual(first.split(" ")[1], second.split(" ")[1])

    def test_reading_one_process_twice_gives_one_identity(self):
        """Otherwise every revalidation would report a replacement."""
        result = self.probe(
            'sleep 30 & child=$!\n'
            'printf "A[%s]\\n" '
            '"$(playthrough_pid_identity "${child}")" >&2\n'
            'sleep 0.2\n'
            'printf "B[%s]\\n" '
            '"$(playthrough_pid_identity "${child}")" >&2\n'
            'kill "${child}" 2>/dev/null || true\n')
        self.assertTrue(self.field(result, "A["), msg=result.stderr)
        self.assertEqual(self.field(result, "A["),
                         self.field(result, "B["))

    def test_a_dead_pid_has_no_identity(self):
        result = self.probe(
            'if playthrough_pid_identity 999999999 >/dev/null; then\n'
            '    printf "ID[yes]\\n" >&2\n'
            'else\n'
            '    printf "ID[no]\\n" >&2\n'
            'fi\n')
        self.assertIn("ID[no]", result.stderr)

    def test_a_cmdline_is_one_printable_line(self):
        """It is written into a record read back line by line.

        A value carrying a newline would forge a field in that record, so
        the reader refuses one rather than trimming it.
        """
        result = self.probe(
            'sleep 30 & child=$!\n'
            'printf "CMD[%s]\\n" '
            '"$(playthrough_proc_cmdline "${child}")" >&2\n'
            'kill "${child}" 2>/dev/null || true\n')
        text = self.field(result, "CMD[")
        self.assertEqual(text, "sleep 30", msg=result.stderr)
        self.assertLessEqual(len(text), 240)

    def test_a_cmdline_carrying_a_newline_is_refused(self):
        """Which is why `$$` is not used above.

        The harness shell's own argument vector holds this multi-line
        program, so its cmdline contains newlines -- and the reader
        rejects it rather than returning a value that would forge a field
        in the ownership record. Measured: the first version of the test
        above read `$$` and got nothing back, which is the refusal working.
        """
        result = self.probe(
            'if playthrough_proc_cmdline $$ >/dev/null; then\n'
            '    printf "CMD[accepted]\\n" >&2\n'
            'else\n'
            '    printf "CMD[refused]\\n" >&2\n'
            'fi\n')
        self.assertIn("CMD[refused]", result.stderr)

    def test_the_uid_is_read_from_status(self):
        result = self.probe(
            'printf "UID[%s]\\n" "$(playthrough_proc_uid $$)" >&2\n')
        self.assertIn("UID[%d]" % os.getuid(), result.stderr)

    # -- what the record carries -------------------------------------

    def test_the_record_carries_the_identity_socket_and_cookie(self):
        result = self.probe(
            'playthrough_record_x_ownership pipeline $$ || exit 1\n'
            'cat "$(playthrough_x_ownership_record)" >&2\n')
        self.assertEqual(result.status, 0, msg=result.stderr)
        for field in ("identity=", "socket=", "cookie="):
            with self.subTest(field=field):
                self.assertIn(field, result.stderr)
        self.assertIn("identity=bash ", result.stderr)

    # -- and what it refuses -----------------------------------------

    def state(self, edit):
        """Record ownership of `$$`, apply `edit` with sed, re-read."""
        return self.probe(
            'playthrough_display_probe() { return 0; }\n'
            'playthrough_display_ready() { return 0; }\n'
            'playthrough_pid_is() { return 0; }\n'
            'playthrough_record_x_ownership pipeline $$ || exit 1\n'
            'R="$(playthrough_x_ownership_record)"\n'
            'sed -i %s "${R}"\n'
            'playthrough_x_ownership_state >/dev/null || true\n'
            'printf "STATE[%%s]\\n" '
            '"${PLAYTHROUGH_X_OWNERSHIP_STATE}" >&2\n'
            'printf "WHY[%%s]\\n" '
            '"${PLAYTHROUGH_X_OWNERSHIP_REASON}" >&2\n' % edit)

    def test_an_unedited_record_is_owned(self):
        """The positive control: the checks must not be unconditional."""
        result = self.state("-e ''")
        self.assertIn("STATE[pipeline]", result.stderr)

    def test_an_altered_start_time_is_replaced(self):
        """The recycled-pid case, which comm cannot see."""
        result = self.state(r"-e 's/^identity=\(\S*\) [0-9]*/"
                            r"identity=\1 999999/'")
        self.assertIn("STATE[replaced]", result.stderr)
        self.assertIn("is not the process that was recorded",
                      result.stderr)

    def test_an_altered_executable_is_replaced(self):
        """A second Xvfb earlier on PATH is a different program."""
        result = self.state(r"-e 's#/bin/bash#/tmp/evil/bash#'")
        self.assertIn("STATE[replaced]", result.stderr)

    def test_a_record_with_no_identity_is_replaced_not_owned(self):
        """A pre-identity record cannot be revalidated.

        Accepting an unverifiable claim on the strength of a pid and a
        name is the whole defect being fixed, so an old record is reported
        rather than trusted.
        """
        result = self.state(r"-e 's/^identity=.*/identity=-/'")
        self.assertIn("STATE[replaced]", result.stderr)
        self.assertIn("no process identity", result.stderr)

    def test_an_altered_socket_is_replaced(self):
        """The display's own identity, independent of any pid.

        A server that died and was replaced leaves a NEW socket inode, and
        the pid check cannot see that at all.
        """
        result = self.state(r"-e 's/^socket=.*/socket=1:999999999/'")
        self.assertIn("STATE[replaced]", result.stderr)
        self.assertIn("is not what was recorded", result.stderr)

    def test_an_altered_cookie_is_replaced(self):
        """-auth is read once, at exec.

        A cookie rotated under a running server leaves that server
        accepting the old value, so the authority file no longer describes
        it.
        """
        result = self.state(r"-e 's/^cookie=.*/cookie=deadbeefdeadbeef/'")
        self.assertIn("STATE[replaced]", result.stderr)
        self.assertIn("was started with", result.stderr)

    def test_replaced_is_reported_separately_from_stale(self):
        """They send an operator to different places.

        `stale` means the recorded process is gone. `replaced` means one
        is there and is not ours. Collapsing them into "not ours" would
        hide exactly the case a recycled pid produces.
        """
        source = env_source()
        self.assertIn('printf \'%s\' "replaced"', source)
        self.assertIn('printf \'%s\' "stale"', source)
        self.assertIn("REPLACED IS REPORTED SEPARATELY FROM STALE",
                      source)

    def test_the_reason_survives_the_call(self):
        """It must not be read through a command substitution.

        `state="$(playthrough_x_ownership_state)"` runs the function in a
        subshell, where every variable it sets dies -- measured that way,
        with the state returned and the reason empty.
        """
        # setUp removed the record, so this measures the absent case.
        result = self.probe(
            'playthrough_display_probe() { return 0; }\n'
            'playthrough_display_ready() { return 0; }\n'
            'playthrough_x_ownership_state >/dev/null || true\n'
            'printf "WHY[%s]\\n" '
            '"${PLAYTHROUGH_X_OWNERSHIP_REASON}" >&2\n')
        why = self.field(result, "WHY[")
        self.assertTrue(why, msg="the reason did not survive the call")
        self.assertIn("no ownership record exists", why)


class TestTheTeardownSignalsOnlyWhatItVerified(EnvFixture):
    """Running as root, a stale pid file is not a failed teardown.

    A review put it exactly: shutdown trusted pid file values weakly while
    running as root. A pid file is a NUMBER written minutes or days ago,
    and on this host the recorded file named one pair while three Xvfb
    processes were alive. Signalling a recycled pid as root is killing a
    stranger's process, not stopping a server.
    """

    def test_a_recycled_pid_is_reported_and_not_signalled(self):
        """The pid is alive and is not the program it should be."""
        result = self.source(
            preset={"CLONE_INDEX": str(SPARE_INDEX)},
            after=(
                'playthrough_display_probe() { return 0; }\n'
                'playthrough_display_ready() { return 0; }\n'
                'playthrough_pid_is() { return 0; }\n'
                'playthrough_record_x_ownership pipeline $$ || exit 1\n'
                'playthrough_pid_is() { return 1; }\n'
                'sleep 30 & victim=$!\n'
                'printf "%s\\n" "${victim}" '
                '>"${PLAYTHROUGH_XVFB_PIDFILE}"\n'
                'printf "%s\\n" "${victim}" '
                '>"${PLAYTHROUGH_WM_PIDFILE}"\n'
                'playthrough_headless_down >/dev/null 2>&1 || true\n'
                'if [ -d "/proc/${victim}" ]; then\n'
                '    printf "VICTIM[alive]\\n" >&2\n'
                'else\n'
                '    printf "VICTIM[killed]\\n" >&2\n'
                'fi\n'
                'kill "${victim}" 2>/dev/null || true\n'))
        self.assertIn(
            "VICTIM[alive]", result.stderr,
            msg="a pid that is not the program it should be was "
                "signalled anyway")

    def test_the_teardown_checks_before_it_kills(self):
        source = env_source()
        start = source.index("playthrough_headless_down() {")
        body = source[start:source.index("\n}\n", start)]
        self.assertIn("NOTHING IS SIGNALLED ON THE STRENGTH OF A PIDFILE",
                      body)
        self.assertIn("playthrough_pid_is", body)
        self.assertIn("playthrough_proc_uid", body)
        # And the check precedes the signal.  The CALL sites are compared
        # rather than the first mention of each name, because the block
        # explaining why the signal goes through a handle names the helper
        # before the loop that uses it.
        self.assertLess(body.index('if ! playthrough_pid_is "'),
                        body.index('$(playthrough_signal_pid "'))

    def test_the_teardown_signals_through_a_handle_not_a_number(self):
        """CWE-367, closed rather than narrowed.

        A review asked for pidfds and got, for a while, an honest "the
        window is a few syscalls wide instead of the whole teardown" --
        because bash has no pidfd.  It does not need one: this pipeline
        already requires a verified interpreter, and os.pidfd_open pins
        the PROCESS rather than the number.  A bare `kill` on a number
        anywhere in this teardown would be the defect returning.
        """
        source = env_source()
        start = source.index("playthrough_headless_down() {")
        body = source[start:source.index("\n}\n", start)]
        self.assertNotIn("if kill ", body)
        self.assertNotIn('kill "${pid}"', body)
        self.assertIn("playthrough_signal_pid", body)
        helper = source[source.index("playthrough_signal_pid() {"):]
        helper = helper[:helper.index("\n}\n")]
        self.assertIn("pidfd_open", helper)
        self.assertIn("pidfd_send_signal", helper)
        # The identity questions are asked AFTER the handle is held,
        # which is the whole reason the handle closes the race.
        self.assertLess(helper.index("opener(pid)"),
                        helper.index("/proc/%d/comm"))

    def test_the_handle_signals_the_process_it_verified(self):
        """End to end, against a real process this test owns."""
        result = self.source(
            preset={"CLONE_INDEX": str(SPARE_INDEX)},
            after=(
                'sleep 30 & victim=$!\n'
                'playthrough_signal_pid sleep "${victim}" SIGTERM '
                '>/dev/null 2>&1 || printf "REFUSED\\n" >&2\n'
                'sleep 0.5\n'
                'if [ -d "/proc/${victim}" ]; then\n'
                '    printf "VICTIM[alive]\\n" >&2\n'
                'else\n'
                '    printf "VICTIM[stopped]\\n" >&2\n'
                'fi\n'
                'kill "${victim}" 2>/dev/null || true\n'))
        self.assertIn("VICTIM[stopped]", result.stderr)
        self.assertNotIn("REFUSED", result.stderr)

    def test_the_handle_refuses_a_process_of_another_program(self):
        """The recycled-number case, at the helper itself."""
        result = self.source(
            preset={"CLONE_INDEX": str(SPARE_INDEX)},
            after=(
                'sleep 30 & victim=$!\n'
                'playthrough_signal_pid Xvfb "${victim}" SIGTERM '
                '>/dev/null 2>&1 || printf "REFUSED\\n" >&2\n'
                'sleep 0.5\n'
                'if [ -d "/proc/${victim}" ]; then\n'
                '    printf "VICTIM[alive]\\n" >&2\n'
                'fi\n'
                'kill "${victim}" 2>/dev/null || true\n'))
        self.assertIn("REFUSED", result.stderr)
        self.assertIn("VICTIM[alive]", result.stderr)


class TestRuntimeRetention(EnvFixture):
    """The runtime root is a cache, and a cache needs a retention rule."""

    def prune(self, after):
        return self.source(
            preset={"CLONE_INDEX": str(SPARE_INDEX),
                    "PLAYTHROUGH_RUNTIME_RETENTION_MINUTES": "1"},
            after=after)

    def aged_lock(self, name):
        base = "/tmp/xdg%d/playthrough/lock" % SPARE_INDEX
        os.makedirs(base, mode=0o700, exist_ok=True)
        path = os.path.join(base, name)
        with open(path, "wb"):
            pass
        os.chmod(path, 0o600)
        os.utime(path, (0, 0))
        self.addCleanup(
            lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_a_closed_and_aged_lock_is_pruned(self):
        path = self.aged_lock("aged.lock")
        result = self.prune("playthrough_prune_runtime\n")
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertFalse(os.path.exists(path))
        self.assertIn("pruned", result.stderr)

    def test_a_held_lock_is_never_pruned(self):
        path = self.aged_lock("held.lock")
        result = self.prune(
            'playthrough_acquire_lock held 5 || exit 1\n'
            'playthrough_prune_runtime\n')
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertTrue(
            os.path.exists(path),
            msg="the lock this very shell holds must survive the "
                "pruner")

    def test_a_fresh_lock_is_not_pruned(self):
        base = "/tmp/xdg%d/playthrough/lock" % SPARE_INDEX
        os.makedirs(base, mode=0o700, exist_ok=True)
        path = os.path.join(base, "fresh.lock")
        with open(path, "wb"):
            pass
        self.addCleanup(
            lambda: os.path.exists(path) and os.unlink(path))
        self.prune("playthrough_prune_runtime\n")
        self.assertTrue(os.path.exists(path))

    def test_an_aged_stage_error_file_is_pruned(self):
        base = "/tmp/xdg%d/playthrough" % SPARE_INDEX
        os.makedirs(base, mode=0o700, exist_ok=True)
        path = os.path.join(base, "capture-stage-424242.err")
        with open(path, "wb"):
            pass
        os.utime(path, (0, 0))
        self.addCleanup(
            lambda: os.path.exists(path) and os.unlink(path))
        self.prune("playthrough_prune_runtime\n")
        self.assertFalse(os.path.exists(path))

    def test_the_cookie_and_the_pid_files_are_left_alone(self):
        base = "/tmp/xdg%d/playthrough" % SPARE_INDEX
        os.makedirs(os.path.join(base, "run"), mode=0o700,
                    exist_ok=True)
        keepers = [os.path.join(base, "Xauthority"),
                   os.path.join(base, "run", "xvfb.pid")]
        for path in keepers:
            with open(path, "wb"):
                pass
            os.utime(path, (0, 0))
            self.addCleanup(
                lambda p=path: os.path.exists(p) and os.unlink(p))
        self.prune("playthrough_prune_runtime\n")
        for path in keepers:
            with self.subTest(path=path):
                self.assertTrue(os.path.exists(path))

    def aged_scratch(self, name, contents):
        """An aged scratch directory holding the named empty files."""
        base = "/tmp/xdg%d/playthrough" % SPARE_INDEX
        path = os.path.join(base, name)
        os.makedirs(path, mode=0o700, exist_ok=True)
        for item in contents:
            with open(os.path.join(path, item), "wb"):
                pass
        os.utime(path, (0, 0))
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def test_a_journal_bearing_scratch_root_is_kept_and_named(self):
        path = self.aged_scratch("session-deadbeefdeadbeef",
                                 ("step.json", "phase.json"))
        result = self.prune("playthrough_prune_runtime\n")
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertTrue(
            os.path.isdir(path),
            msg="an unresolved journal describes a keystroke that may "
                "have been delivered; a timer must not erase it")
        self.assertIn("unresolved journal", result.stderr)
        self.assertIn("step.json", result.stderr)

    def test_a_generation_journal_keeps_a_scratch_root_too(self):
        path = self.aged_scratch("session-cafecafecafecafe",
                                 ("movie.generation.json",))
        self.prune("playthrough_prune_runtime\n")
        self.assertTrue(os.path.isdir(path))

    def test_a_cache_only_scratch_root_is_pruned(self):
        # phase.json is a rebuildable cache of what the sidecar already
        # says, so it must NOT block a prune -- otherwise every session
        # directory this pipeline has ever opened is immortal.
        path = self.aged_scratch("session-0000000000000000",
                                 ("phase.json",))
        self.prune("playthrough_prune_runtime\n")
        self.assertFalse(os.path.exists(path))

    def test_a_scratch_root_holding_a_held_lock_is_kept(self):
        path = self.aged_scratch("pipeline-heldlock", ())
        lock = os.path.join(path, "step.lock")
        with open(lock, "wb"):
            pass
        result = self.prune(
            'exec {probe}>>"%s"\n'
            'flock -n "${probe}" || exit 1\n'
            'playthrough_prune_runtime\n' % lock)
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertTrue(
            os.path.isdir(path),
            msg="removing a directory whose lock is held leaves the "
                "holder locking an inode nothing can reach, and the "
                "next process free to take a new lock at the same name")

    def test_a_lock_file_somebody_still_has_open_is_kept(self):
        # `flock -n` proves nobody HOLDS it and says nothing about a
        # process blocked waiting for it.  Unlinking under a waiter is
        # how two processes come to hold one lock.
        path = self.aged_lock("waited-on.lock")
        result = self.prune(
            'exec {probe}>>"%s"\n'
            'playthrough_prune_runtime\n' % path)
        self.assertEqual(result.status, 0, msg=result.stderr)
        self.assertTrue(os.path.exists(path))

    def test_an_error_file_for_a_live_process_is_kept(self):
        base = "/tmp/xdg%d/playthrough" % SPARE_INDEX
        os.makedirs(base, mode=0o700, exist_ok=True)
        path = os.path.join(base, "capture-stage-%d.err" % os.getpid())
        with open(path, "wb"):
            pass
        os.utime(path, (0, 0))
        self.addCleanup(
            lambda: os.path.exists(path) and os.unlink(path))
        self.prune("playthrough_prune_runtime\n")
        self.assertTrue(
            os.path.exists(path),
            msg="the diagnostics of a stage that is still running are "
                "the ones worth keeping")


class TestProcessIdentityAndOpenPaths(EnvFixture):
    """The two primitives the pruner reasons with.

    A pid is not an identity, and `flock -n` does not answer "is anything
    using this".  The pruner acts on both answers by REMOVING things, so
    both are measured here rather than assumed.
    """

    def setUp(self):
        super(TestProcessIdentityAndOpenPaths, self).setUp()
        self.spare_runtime_dir()

    def probe(self, after):
        return self.source(
            preset={"CLONE_INDEX": str(SPARE_INDEX)}, after=after)

    def test_a_live_process_reports_a_plausible_start_time(self):
        result = self.probe(
            'printf "START[%s]\\n" '
            '"$(playthrough_proc_start_time $$)" >&2\n')
        match = re.search(r"START\[(\d+)\]", result.stderr)
        self.assertTrue(match, msg=result.stderr)
        value = int(match.group(1))
        self.assertGreater(value, 0)
        # Field 22 is clock ticks since boot, so a shell started moments
        # ago cannot precede this process by more than the uptime.  A
        # thread count or a nice value -- what an off-by-one in the field
        # arithmetic would return -- would fail this bound.
        with open("/proc/self/stat", "rb") as handle:
            mine = int(handle.read().rpartition(b") ")[2].split()[19])
        self.assertGreaterEqual(value, mine)

    def test_a_pid_that_does_not_exist_reports_nothing(self):
        result = self.probe(
            'if playthrough_proc_start_time 999999999 >/dev/null; then\n'
            '    printf "FOUND\\n" >&2\n'
            'else\n'
            '    printf "ABSENT\\n" >&2\n'
            'fi\n')
        self.assertIn("ABSENT", result.stderr)

    def in_use(self, target, opened=None):
        prologue = ""
        epilogue = ""
        if opened is not None:
            prologue = 'exec {probe}<"%s"\n' % opened
            epilogue = 'exec {probe}<&-\n'
        question = (
            'if playthrough_path_in_use "%s"; then\n'
            '    printf "IN_USE\\n" >&2\n'
            'else\n'
            '    printf "FREE\\n" >&2\n'
            'fi\n' % target)
        return self.probe(prologue + question + epilogue)

    def test_a_path_this_shell_has_open_is_in_use(self):
        target = os.path.join(self.root, "open-file")
        with open(target, "wb"):
            pass
        self.assertIn("IN_USE",
                      self.in_use(target, opened=target).stderr)

    def test_a_path_nobody_has_open_is_free(self):
        target = os.path.join(self.root, "closed-file")
        with open(target, "wb"):
            pass
        self.assertIn("FREE", self.in_use(target).stderr)

    def test_a_directory_is_in_use_when_a_file_inside_it_is(self):
        directory = os.path.join(self.root, "busy-dir")
        os.makedirs(directory)
        inside = os.path.join(directory, "held")
        with open(inside, "wb"):
            pass
        self.assertIn("IN_USE",
                      self.in_use(directory, opened=inside).stderr)


class TestNothingChosenElsewhereCanForgeALine(EnvFixture):
    """A world name is somebody else's string, and it was printed raw.

    A review found world names reaching both the log and the KEY=value
    channel with no rejection of C0, C1 or newline.  The world name is a
    directory name under the save tree -- the engine writes it from what
    the player typed, and any local account able to create a directory
    there writes whatever it likes.  From there it went into
    `playthrough: WARNING: save/<name> ...` and into
    PLAYTHROUGH_SAVE_WORLD, which later stages parse as KEY=value.

    So a name containing a newline forged a whole extra line -- of the log,
    or of a record a later stage reads as fact -- and one containing ESC-[
    or the single-byte C1 CSI repainted the terminal of whoever was
    reading the run.
    """

    def probe(self, after):
        return self.source(after=after)

    def escaped(self, value):
        """What playthrough_escape_controls makes of one value."""
        result = self.probe(
            'printf "OUT[%%s]\\n" '
            '"$(playthrough_escape_controls %s)" >&2\n' % value)
        return self.field(result, "OUT[")

    # -- detection ----------------------------------------------------

    def test_each_control_class_is_detected(self):
        """C0, DEL and C1 -- the last because 0x9B is a bare CSI."""
        cases = {
            "$(printf 'a\\nb')": "newline",
            "$(printf 'a\\rb')": "carriage return",
            "$(printf 'a\\tb')": "tab",
            "$(printf 'a\\033[31mb')": "escape",
            "$(printf 'a\\177b')": "delete",
            "$(printf 'a\\302\\233b')": "C1 CSI",
            "$(printf 'a\\302\\205b')": "C1 NEL",
        }
        for value, label in cases.items():
            with self.subTest(control=label):
                result = self.probe(
                    'if playthrough_has_control "%s"; then\n'
                    '    printf "OUT[yes]\\n" >&2\n'
                    'else printf "OUT[no]\\n" >&2 ; fi\n' % value)
                self.assertEqual(self.field(result, "OUT["), "yes")

    def test_legitimate_non_ascii_is_not_a_control(self):
        """Refusing a name for not being English would not be safety."""
        for value, label in (("Sunnysid\u00e9", "accented Latin"),
                             ("\u0410\u043d\u043d\u0430", "Cyrillic"),
                             ("\u674e", "Han")):
            with self.subTest(text=label):
                result = self.probe(
                    'if playthrough_has_control "%s"; then\n'
                    '    printf "OUT[yes]\\n" >&2\n'
                    'else printf "OUT[no]\\n" >&2 ; fi\n' % value)
                self.assertEqual(self.field(result, "OUT["), "no")

    # -- escaping -----------------------------------------------------

    def test_a_clean_value_passes_through_unchanged(self):
        self.assertEqual(self.escaped('"Sunnyside"'), "Sunnyside")
        self.assertEqual(self.escaped('"Sunnysid\u00e9"'),
                         "Sunnysid\u00e9")

    def test_a_control_becomes_a_visible_escape(self):
        """Replaced, not deleted: a delete loses the evidence."""
        self.assertEqual(self.escaped("\"$(printf 'a\\nb')\""), "a<0A>b")
        self.assertEqual(self.escaped("\"$(printf 'a\\tb')\""), "a<09>b")
        self.assertEqual(self.escaped("\"$(printf 'a\\177b')\""),
                         "a<7F>b")

    def test_an_ansi_sequence_cannot_reach_the_terminal(self):
        self.assertEqual(
            self.escaped("\"$(printf 'a\\033[31mRED')\""),
            "a<1B>[31mRED")

    def test_the_single_byte_c1_csi_is_escaped_too(self):
        """0x9B is honoured as ESC-[ by some terminals."""
        self.assertEqual(self.escaped("\"$(printf 'a\\302\\233b')\""),
                         "a<9B>b")

    # -- and every diagnostic goes through it -------------------------

    def test_a_warning_cannot_be_made_to_forge_a_second_line(self):
        """The property that matters, measured end to end."""
        result = self.probe(
            'playthrough_warn '
            '"save/$(printf \'Evil\\nplaythrough: FORGED\')"\n')
        lines = [line for line in result.stderr.splitlines()
                 if "playthrough:" in line]
        forged = [line for line in lines
                  if line.startswith("playthrough: FORGED")]
        self.assertEqual(forged, [],
                         msg="a second line was forged: %s" % lines)
        self.assertIn("Evil<0A>playthrough: FORGED", result.stderr)

    def test_a_fatal_diagnostic_is_escaped_as_well(self):
        result = self.probe(
            '(playthrough_die '
            '"world $(printf \'X\\nplaythrough: FORGED\')") || true\n')
        self.assertNotIn("\nplaythrough: FORGED", result.stderr)
        self.assertIn("X<0A>", result.stderr)

    # -- the record-token grammar -------------------------------------

    def token(self, value):
        """STATUS and the diagnosis for one candidate value."""
        result = self.probe(
            'if playthrough_assert_record_token %s "the world name"\n'
            'then printf "OUT[ok]\\n" >&2\n'
            'else printf "OUT[refused]\\n" >&2 ; fi\n' % value)
        return self.field(result, "OUT["), result.stderr

    def test_a_plain_name_is_accepted(self):
        self.assertEqual(self.token('"Sunnyside"')[0], "ok")

    def test_an_accented_name_is_accepted(self):
        self.assertEqual(self.token('"Sunnysid\u00e9"')[0], "ok")

    def test_a_name_carrying_a_newline_is_refused(self):
        status, errors = self.token("\"$(printf 'a\\nb')\"")
        self.assertEqual(status, "refused")
        self.assertIn("carries a control character", errors)

    def test_the_refusal_shows_the_bytes_without_printing_them(self):
        """A diagnostic must not perform the injection it reports."""
        status, errors = self.token(
            "\"$(printf 'Evil\\nplaythrough: FORGED')\"")
        self.assertEqual(status, "refused")
        self.assertIn("Evil<0A>playthrough: FORGED", errors)
        forged = [line for line in errors.splitlines()
                  if line.startswith("playthrough: FORGED")]
        self.assertEqual(forged, [])

    def test_an_empty_name_is_refused(self):
        status, errors = self.token('""')
        self.assertEqual(status, "refused")
        self.assertIn("is empty", errors)

    def test_a_name_past_the_ceiling_is_refused(self):
        # `%.0s` with a single per cent -- a REAL conversion, so printf
        # recycles the format once per argument and emits nothing each
        # time.  Written `%%.0s` it is a literal and printf runs one
        # cycle, which produced a five-character probe that the ceiling
        # correctly accepted; the test failed and the code was right.
        status, errors = self.token(
            '"$(printf \'x%.0s\' $(seq 1 200))"')
        self.assertEqual(status, "refused")
        self.assertIn("past the", errors)

    def test_the_ceiling_is_published_for_the_python_half(self):
        """session.py restates it, and the two have to agree."""
        self.assertIn("PLAYTHROUGH_MAX_RECORD_TOKEN=128", env_source())


class TestTheClosureIsAskedWhatElseIsInIt(unittest.TestCase):
    """Three questions the closure checker was not asking.

    Checks 1 to 5 all ask "is what we declared present and coherent".
    None of them asked the opposite question, and for a supply chain that
    is the one that matters: what ELSE is in here, and what of it runs
    before any pipeline code does.  The third question is narrower and
    sharper -- the pinned Pillow carries advisories accepted only because
    an upstream constraint forces the pin, and nothing noticed if the
    constraint moved.

    The checker is a fixed program embedded in env.sh, so these tests
    extract it and run it against a real interpreter with one fact
    changed at a time.
    """

    @classmethod
    def setUpClass(cls):
        source = env_source()
        match = re.search(r"PLAYTHROUGH_CLOSURE_CHECKER='(.*?)\n'\n",
                          source, re.S)
        if match is None:                       # pragma: no cover
            raise AssertionError(
                "the embedded closure checker could not be extracted "
                "from env.sh, so nothing below is measuring it")
        cls.program = match.group(1)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_closure_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.script = os.path.join(self.root, "closure.py")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write(self.program + "\n")

    def verdicts(self, patch=""):
        """Run the checker, optionally with one fact changed.

        `patch` is Python executed BEFORE the checker, in the same
        interpreter, so it can replace what the checker reads without any
        of it being simulated: the checker still walks real installed
        metadata and a real site-packages.
        """
        driver = os.path.join(self.root, "driver.py")
        with open(driver, "w", encoding="utf-8") as handle:
            handle.write(
                "import runpy, sys\n"
                "%s\n"
                "sys.argv = ['closure', '|', %r, %r]\n"
                "runpy.run_path(%r, run_name='__main__')\n"
                % (patch or "pass", REQUIREMENTS, REQUIREMENTS_LOCK,
                   self.script))
        result = subprocess.run(
            [PYTHON, "-B", driver], capture_output=True, timeout=300)
        rows = []
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split("|")
            if len(parts) >= 3:
                rows.append((parts[0], parts[1], parts[2]))
        return rows

    def failures(self, patch=""):
        return [row for row in self.verdicts(patch) if row[0] == "FAIL"]

    def named(self, rows, fragment):
        found = [row for row in rows if fragment in row[1]]
        self.assertTrue(
            found, msg="no verdict named %r; got %s"
            % (fragment, [row[1] for row in rows]))
        return found[0]

    # -- the environment as it stands ---------------------------------

    def test_the_real_environment_passes_every_check(self):
        """Eight verdicts, all passing, on the provisioned interpreter."""
        rows = self.verdicts()
        self.assertEqual([row for row in rows if row[0] == "FAIL"], [])
        self.assertGreaterEqual(
            len([row for row in rows if row[0] == "PASS"]), 8)

    # -- check 6: the pin, and the day it stops being forced ----------

    def test_the_pin_is_reported_as_forced_while_it_is(self):
        row = self.named(self.verdicts(), "still forces the Pillow pin")
        self.assertEqual(row[0], "PASS")
        self.assertIn("excludes the first fixed release", row[2])

    def test_a_render_stack_that_admits_the_fix_fails_the_gate(self):
        """The whole point: prose does not fire, and this does.

        requirements.txt states the trigger for moving the pin as a
        sentence.  The day a moviepy release lifts `pillow<12.0`, nothing
        would have noticed and the justification for the pin would have
        quietly become false while every gate still reported green.
        """
        rows = self.failures(
            "import importlib.metadata as md\n"
            "_real = md.requires\n"
            "md.requires = lambda name: (['pillow<13.0,>=9.2.0']\n"
            "    if name == 'moviepy' else _real(name))\n")
        row = self.named(rows, "still forces the Pillow pin")
        self.assertIn("ADMITS the first fixed release", row[2])

    def test_an_unreadable_bound_fails_closed(self):
        """An unreadable justification is not "no constraint".

        The pin is defensible only while the constraint that forces it can
        be checked, so a moviepy that declares nothing about Pillow is a
        failure rather than a pass.
        """
        rows = self.failures(
            "import importlib.metadata as md\n"
            "_real = md.requires\n"
            "md.requires = lambda name: ([] if name == 'moviepy'\n"
            "    else _real(name))\n")
        row = self.named(rows, "still forces the Pillow pin")
        self.assertIn("no readable Pillow requirement", row[2])

    # -- check 7: what else is installed ------------------------------

    def test_an_undeclared_distribution_fails_the_gate(self):
        """A package nothing declared, nothing hashed and no review saw.

        Every module in the closure can import it.
        """
        rows = self.failures(
            "import importlib.metadata as md\n"
            "class _Fake(object):\n"
            "    version = '9.9.9'\n"
            "    metadata = {'Name': 'totally-legit-helper'}\n"
            "    requires = None\n"
            "_real = md.distributions\n"
            "md.distributions = lambda *a, **k: (list(_real(*a, **k))\n"
            "    + [_Fake()])\n")
        row = self.named(rows, "does not name")
        self.assertIn("totally-legit-helper==9.9.9", row[2])

    def test_the_bootstrap_tools_are_allowed_without_being_declared(self):
        """pip installs the lock, so it cannot be an entry in it.

        Naming the three explicitly is what lets the check refuse
        everything else instead of accepting whatever is present.
        """
        row = self.named(self.verdicts(), "does not name")
        self.assertEqual(row[0], "PASS")
        for tool in ("pip", "setuptools", "wheel"):
            self.assertIn(tool, row[2])

    # -- check 8: what runs before anything else ----------------------

    def test_an_unexpected_executable_pth_fails_the_gate(self):
        """A .pth beginning `import` runs at every interpreter start.

        It is arbitrary code inside the closure that no wheel hash and no
        version pin describes -- and it runs before this checker does.
        """
        site = os.path.join(self.root, "site")
        os.makedirs(site)
        with open(os.path.join(site, "evil.pth"), "w",
                  encoding="utf-8") as handle:
            handle.write("import os; os.environ['PWNED'] = '1'\n")
        rows = self.failures(
            "import sysconfig\n"
            "_real = sysconfig.get_paths\n"
            "def _paths(*a, **k):\n"
            "    p = dict(_real(*a, **k))\n"
            "    p['purelib'] = %r\n"
            "    p['platlib'] = %r\n"
            "    return p\n"
            "sysconfig.get_paths = _paths\n" % (site, site))
        row = self.named(rows, "runs at interpreter startup")
        self.assertIn("evil.pth", row[2])
        self.assertIn("not an allowed startup file", row[2])

    def test_a_non_executable_pth_is_not_an_offence(self):
        """A path-only .pth adds a directory; it does not run code."""
        site = os.path.join(self.root, "site")
        os.makedirs(site)
        with open(os.path.join(site, "plain.pth"), "w",
                  encoding="utf-8") as handle:
            handle.write("../some/other/directory\n")
        rows = self.verdicts(
            "import sysconfig\n"
            "_real = sysconfig.get_paths\n"
            "def _paths(*a, **k):\n"
            "    p = dict(_real(*a, **k))\n"
            "    p['purelib'] = %r\n"
            "    p['platlib'] = %r\n"
            "    return p\n"
            "sysconfig.get_paths = _paths\n" % (site, site))
        row = self.named(rows, "runs at interpreter startup")
        self.assertEqual(row[0], "PASS", msg=row[2])

    def test_a_mutated_allowed_pth_fails_the_gate(self):
        """Allowed BY DIGEST, so the name alone buys nothing.

        Allowing setuptools' shim by name would allow any content under
        that name, which is exactly the substitution worth refusing.
        """
        site = os.path.join(self.root, "site")
        os.makedirs(site)
        with open(os.path.join(site, "distutils-precedence.pth"), "w",
                  encoding="utf-8") as handle:
            handle.write("import os\nimport shutil\n")
        rows = self.failures(
            "import sysconfig\n"
            "_real = sysconfig.get_paths\n"
            "def _paths(*a, **k):\n"
            "    p = dict(_real(*a, **k))\n"
            "    p['purelib'] = %r\n"
            "    p['platlib'] = %r\n"
            "    return p\n"
            "sysconfig.get_paths = _paths\n" % (site, site))
        row = self.named(rows, "runs at interpreter startup")
        self.assertIn("its bytes have changed", row[2])

    def test_the_allowed_digest_is_the_one_setuptools_ships(self):
        """Measured from the provisioned environment, not invented."""
        source = env_source()
        self.assertIn("distutils-precedence.pth", source)
        self.assertIn("2638ce9e2500e572a5e0de7faed6661eb569d1b696fcba07"
                      "b0dd223da5f5d2", source)

    # -- the file the program lives in --------------------------------

    def test_the_embedded_program_carries_no_apostrophe(self):
        """It lives inside a single-quoted bash string.

        An apostrophe anywhere in it TERMINATES that string, and what
        follows is parsed as bash -- which is how a docstring saying
        "moviepy's own declared bound" turned the program into a shell
        syntax error.  Cheaper to assert than to rediscover.
        """
        self.assertNotIn("'", self.program)


class TestTheMutationLock(EnvFixture):
    """One lock the whole checkout agrees on.

    Every other lock in env.sh serialises a stage against another copy of
    ITSELF.  This one serialises the producers against the gate and the
    committer, which is the gap a review found: a gate that passed, a
    producer that changed the tree, and a commit that published state no
    gate ever saw -- with every individual lock correctly held throughout,
    because no two holders were ever the same stage.
    """

    def setUp(self):
        super(TestTheMutationLock, self).setUp()
        self.spare_runtime_dir()

    def probe(self, after, **preset):
        values = {"CLONE_INDEX": str(SPARE_INDEX)}
        values.update(preset)
        return self.source(preset=values, after=after)

    def outsider(self, mode):
        """A shell carrying no marker, asking for `mode`.

        The marker is stripped so this stands in for an UNRELATED stage
        rather than a child of the holder.
        """
        return (
            'env -u PLAYTHROUGH_MUTATION_LOCK_HELD '
            '-u PLAYTHROUGH_MUTATION_LOCK_FD '
            'bash --noprofile --norc -c '
            '\'. playthrough/tooling/env.sh >/dev/null 2>&1 || exit 9\n'
            'playthrough_acquire_mutation_lock %s 1 >/dev/null 2>&1\n'
            'printf "OUTSIDER[%%s]\\n" "$?" >&2\'\n' % mode)

    def child(self, mode, prefix=""):
        """A child that inherits whatever the parent holds."""
        return (
            '%sbash --noprofile --norc -c '
            '\'. playthrough/tooling/env.sh >/dev/null 2>&1 || exit 9\n'
            'playthrough_acquire_mutation_lock %s 1\n'
            'printf "CHILD[%%s]\\n" "$?" >&2\'\n' % (prefix, mode))

    # -- the name and the two modes ----------------------------------

    def test_the_lock_is_in_the_lock_directory_and_names_the_checkout(
            self):
        result = self.probe(
            'printf "LOCKPATH[%s]\\n" '
            '"$(playthrough_mutation_lock_path)" >&2\n')
        match = re.search(r"LOCKPATH\[(.+)\]", result.stderr)
        self.assertTrue(match, msg=result.stderr)
        path = match.group(1)
        digest = hashlib.sha256(
            REPO_ROOT.encode("utf-8")).hexdigest()[:8]
        self.assertEqual(os.path.basename(path),
                         "mutation-%s.lock" % digest)
        self.assertEqual(
            os.path.dirname(path),
            "/tmp/xdg%d/playthrough/lock" % SPARE_INDEX)

    def test_a_lock_mode_that_is_neither_word_is_refused(self):
        result = self.probe(
            'playthrough_acquire_lock probe 5 sideways || '
            'printf "REFUSED\\n" >&2\n')
        self.assertIn("REFUSED", result.stderr)
        self.assertIn("is not a lock mode", result.stderr)

    def test_a_mutation_mode_that_is_neither_word_is_refused(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock sideways 5 || '
            'printf "REFUSED\\n" >&2\n')
        self.assertIn("REFUSED", result.stderr)
        self.assertIn("is not a mutation lock mode", result.stderr)

    # -- what excludes what ------------------------------------------

    def test_two_shared_holders_coexist(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n' +
            self.outsider("shared"))
        self.assertIn(
            "OUTSIDER[0]", result.stderr,
            msg="two producers must be able to run beside each other; "
                "each already excludes its own twin through its stage "
                "lock")

    def test_an_exclusive_holder_excludes_a_shared_one(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock exclusive 5 || exit 1\n' +
            self.outsider("shared"))
        self.assertIn("OUTSIDER[1]", result.stderr)

    def test_a_shared_holder_excludes_an_exclusive_one(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n' +
            self.outsider("exclusive"))
        self.assertIn("OUTSIDER[1]", result.stderr)

    # -- re-entrancy, proved rather than trusted ---------------------

    def test_a_child_proves_and_inherits_a_shared_hold(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n' +
            self.child("shared"))
        self.assertIn(
            "CHILD[0]", result.stderr,
            msg="a child that re-acquired would block against its own "
                "parent for the whole timeout and then refuse")
        self.assertIn("already held", result.stderr)

    def test_a_child_inherits_an_exclusive_hold_for_a_shared_request(
            self):
        result = self.probe(
            'playthrough_acquire_mutation_lock exclusive 5 || exit 1\n' +
            self.child("shared"))
        self.assertIn("CHILD[0]", result.stderr)

    def test_a_child_needing_exclusive_under_a_shared_hold_is_refused(
            self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n' +
            self.child("exclusive"))
        self.assertIn("CHILD[1]", result.stderr)
        self.assertIn("does not make the tree quiescent", result.stderr)

    def test_a_marker_whose_descriptor_is_not_open_is_refused(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n' +
            self.child(
                "shared",
                prefix="PLAYTHROUGH_MUTATION_LOCK_FD=77 "))
        self.assertIn("CHILD[1]", result.stderr)
        self.assertIn("not open", result.stderr)

    def test_a_marker_whose_descriptor_points_elsewhere_is_refused(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n'
            'exec {decoy}</dev/null\n' +
            self.child(
                "shared",
                prefix='PLAYTHROUGH_MUTATION_LOCK_FD="${decoy}" '))
        self.assertIn("CHILD[1]", result.stderr)
        self.assertIn("rather than", result.stderr)

    def test_a_marker_nothing_actually_holds_is_refused(self):
        # The shape a hand-set marker takes: the descriptor really is open
        # on the right file, and no process holds the lock.
        result = self.probe(
            'lock="$(playthrough_mutation_lock_path)"\n'
            'playthrough_secure_file "${lock}" 600 || exit 1\n'
            'exec {opened}>>"${lock}"\n' +
            self.child(
                "shared",
                prefix=('PLAYTHROUGH_MUTATION_LOCK_HELD=shared '
                        'PLAYTHROUGH_MUTATION_LOCK_FD="${opened}" ')))
        self.assertIn("CHILD[1]", result.stderr)
        self.assertIn("nothing holds it", result.stderr)

    def test_a_marker_that_is_not_a_mode_is_refused(self):
        result = self.probe(self.child(
            "shared",
            prefix="PLAYTHROUGH_MUTATION_LOCK_HELD=sideways "))
        self.assertIn("CHILD[1]", result.stderr)
        self.assertIn("not a lock mode", result.stderr)

    def test_an_inherited_hold_is_not_released_by_the_child(self):
        # THE DANGEROUS CASE, and the reason release is conditional: the
        # child's copy of the descriptor IS the parent's open file
        # description, so an unconditional `flock -u` in the child drops
        # the PARENT's lock while the parent goes on believing it holds
        # the tree.  After a correct release the parent still holds it,
        # which an outsider asking for exclusive proves.
        released = (
            'bash --noprofile --norc -c '
            '\'. playthrough/tooling/env.sh >/dev/null 2>&1 || exit 9\n'
            'playthrough_acquire_mutation_lock shared 1 '
            '>/dev/null 2>&1\n'
            'playthrough_release_mutation_lock\n'
            'printf "CHILD_DONE\\n" >&2\'\n')
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n' +
            released + self.outsider("exclusive"))
        self.assertIn("CHILD_DONE", result.stderr)
        self.assertIn(
            "OUTSIDER[1]", result.stderr,
            msg="the child released a hold it had only inherited, so "
                "the parent lost a lock it still believes it holds")

    def test_a_holder_releases_its_own_hold(self):
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n'
            'playthrough_release_mutation_lock\n' +
            self.outsider("exclusive"))
        self.assertIn("OUTSIDER[0]", result.stderr)

    # -- living beside the stage locks -------------------------------

    def test_a_stage_lock_descriptor_survives_a_mutation_acquisition(
            self):
        result = self.probe(
            'playthrough_acquire_lock stage 5 || exit 1\n'
            'before="${PLAYTHROUGH_LOCK_FD}"\n'
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n'
            'printf "STAGE[%s->%s] MUTATION[%s]\\n" "${before}" '
            '"${PLAYTHROUGH_LOCK_FD}" '
            '"${PLAYTHROUGH_MUTATION_LOCK_FD}" >&2\n')
        match = re.search(
            r"STAGE\[(\d+)->(\d+)\] MUTATION\[(\d+)\]", result.stderr)
        self.assertTrue(match, msg=result.stderr)
        self.assertEqual(
            match.group(1), match.group(2),
            msg="the mutation lock overwrote the stage lock's "
                "descriptor, so the caller can no longer release the "
                "lock it took first")
        self.assertNotEqual(match.group(1), match.group(3))

    def test_both_descriptors_are_withheld_from_a_detached_child(self):
        result = self.probe(
            'playthrough_acquire_lock stage 5 || exit 1\n'
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n'
            'playthrough_child_close_fd || exit 1\n'
            'printf "FD[%s] FD2[%s] BORROWED[%s][%s]\\n" '
            '"${PLAYTHROUGH_CHILD_CLOSE_FD}" '
            '"${PLAYTHROUGH_CHILD_CLOSE_FD2}" '
            '"${PLAYTHROUGH_CHILD_CLOSE_BORROWED}" '
            '"${PLAYTHROUGH_CHILD_CLOSE_BORROWED2}" >&2\n'
            'playthrough_child_close_done\n')
        match = re.search(
            r"FD\[(\d+)\] FD2\[(\d+)\] BORROWED\[(\d)\]\[(\d)\]",
            result.stderr)
        self.assertTrue(match, msg=result.stderr)
        self.assertNotEqual(match.group(1), match.group(2))
        self.assertEqual(match.group(3), "0")
        self.assertEqual(
            match.group(4), "0",
            msg="the mutation descriptor was borrowed rather than "
                "withheld, so a detached child would inherit the lock "
                "and hold the whole checkout for its entire lifetime")

    def test_a_detached_child_really_cannot_see_either_descriptor(self):
        result = self.probe(
            'playthrough_acquire_lock stage 5 || exit 1\n'
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n'
            'playthrough_child_close_fd || exit 1\n'
            'FD_A="${PLAYTHROUGH_CHILD_CLOSE_FD}" '
            'FD_B="${PLAYTHROUGH_CHILD_CLOSE_FD2}" '
            'bash --noprofile --norc -c '
            '\'printf "SEEN[%s][%s]\\n" '
            '"$(readlink "/proc/self/fd/${FD_A}" 2>/dev/null '
            '|| printf absent)" '
            '"$(readlink "/proc/self/fd/${FD_B}" 2>/dev/null '
            '|| printf absent)" >&2\' '
            '{PLAYTHROUGH_CHILD_CLOSE_FD}>&- '
            '{PLAYTHROUGH_CHILD_CLOSE_FD2}>&-\n'
            'playthrough_child_close_done\n')
        self.assertIn(
            "SEEN[absent][absent]", result.stderr,
            msg="a detached child inherited a lock descriptor; that is "
                "the measured defect the two-descriptor withholding "
                "exists to prevent")

    def test_the_marker_survives_a_child_re_sourcing_env(self):
        # THE MEASURED BUG: env.sh runs in the child too, and an
        # unconditional `PLAYTHROUGH_MUTATION_LOCK_FD=""` there erased the
        # one piece of evidence the child had.
        result = self.probe(
            'playthrough_acquire_mutation_lock shared 5 || exit 1\n'
            'bash --noprofile --norc -c '
            '\'. playthrough/tooling/env.sh >/dev/null 2>&1 || exit 9\n'
            'printf "INHERITED[%s][%s]\\n" '
            '"${PLAYTHROUGH_MUTATION_LOCK_HELD:-unset}" '
            '"${PLAYTHROUGH_MUTATION_LOCK_FD:-unset}" >&2\n'
            'printf "OWNED[%s]\\n" '
            '"${PLAYTHROUGH_MUTATION_LOCK_OWNED}" >&2\'\n')
        match = re.search(r"INHERITED\[(\w+)\]\[(\w+)\]", result.stderr)
        self.assertTrue(match, msg=result.stderr)
        self.assertEqual(match.group(1), "shared")
        self.assertTrue(match.group(2).isdigit(), msg=result.stderr)
        self.assertIn(
            "OWNED[0]", result.stderr,
            msg="a child must never believe it OWNS what it inherited, "
                "or its cleanup will release its parent's lock")


if __name__ == "__main__":
    unittest.main(verbosity=2)
