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
ENV_SH = os.path.join(TOOLING, "env.sh")

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


class EnvFixture(unittest.TestCase):
    """Sources env.sh under a controlled, empty environment."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="blitzy_env_")
        self.addCleanup(shutil.rmtree, self.root, True)

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
        """/tmp/xdg<SPARE_INDEX>, removed afterwards if we made it."""
        path = "/tmp/xdg%d" % SPARE_INDEX
        if not os.path.exists(path):
            self.addCleanup(shutil.rmtree, path, True)
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
        path = self.spare_runtime_dir()
        shutil.rmtree(path, True)
        self.assertFalse(os.path.exists(path))
        result = self.sourced(
            preset={"CLONE_INDEX": str(SPARE_INDEX)})
        self.assertEqual(result["XDG_RUNTIME_DIR"], path)
        self.assertTrue(os.path.isdir(path))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)

    def test_an_existing_directory_is_tightened_rather_than_trusted(self):
        path = self.spare_runtime_dir()
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o777)
        self.sourced(preset={"CLONE_INDEX": str(SPARE_INDEX)})
        self.assertEqual(
            os.stat(path).st_mode & 0o777, 0o700,
            msg="a directory left over from another run is not trusted")

    def test_a_runtime_directory_that_cannot_be_made_is_fatal(self):
        blocker = os.path.join(self.root, "not-a-dir")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("in the way\n")
        root, copy = self.sabotaged_copy(
            '_playthrough_runtime_dir="/tmp/xdg${_playthrough_suffix}"',
            '_playthrough_runtime_dir="%s/in/the/way"' % blocker,
            name="blocked")
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


class TestTheTrustState(EnvFixture):
    """One computed answer about the environment, not seven warnings."""

    BYPASSES = (
        "PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES",
        "PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X",
        "PLAYTHROUGH_ALLOW_UNVERIFIED_TILESET_PACK",
        "PLAYTHROUGH_ALLOW_TILESET_FALLBACK",
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
            "PLAYTHROUGH_ALLOW_TILESET_FALLBACK": "0",
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
            after='export PLAYTHROUGH_ALLOW_TILESET_FALLBACK=1\n'
                  'playthrough_trust_refresh || true\n'
                  'export LATE="${PLAYTHROUGH_TRUST_STATE}"\n'
                  'unset PLAYTHROUGH_ALLOW_TILESET_FALLBACK\n'
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
        self.assertIn("not started by this checkout", result.stderr)

    def test_a_dead_recorded_pid_is_stale_rather_than_owned(self):
        result = self.probe(
            'playthrough_display_probe() { return 0; }\n'
            'playthrough_display_ready() { return 0; }\n'
            'playthrough_record_x_ownership pipeline 999999999\n'
            'printf "STATE[%s]\\n" "$(playthrough_x_ownership_state)" '
            '>&2\n')
        self.assertIn("STATE[stale]", result.stderr)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
