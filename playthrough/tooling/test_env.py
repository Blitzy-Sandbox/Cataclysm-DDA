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
    "playthrough_python",
    "playthrough_env_summary",
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
        self.assertGreater(
            int(result.get("SUMMARY", "0")), 20,
            msg="the record of what the capture actually ran under")

    def test_running_the_file_prints_the_contract_and_exports_nothing(self):
        result = subprocess.run(
            ["/usr/bin/env", "-i", "PATH=" + BASE_PATH,
             "/bin/bash", "--noprofile", "--norc", ENV_SH],
            cwd=REPO_ROOT, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode("utf-8", "replace")
        self.assertIn("playthrough environment contract", text)
        self.assertIn("SDL_VIDEODRIVER", text)
        self.assertIn("x11", text)


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


class TestTheToolPackageTable(EnvFixture):
    """A missing tool says what to install."""

    def test_each_command_names_the_package_that_ships_it(self):
        pairs = (("Xvfb", "xvfb"), ("openbox", "openbox"),
                 ("xdpyinfo", "x11-utils"), ("xdotool", "xdotool"),
                 ("import", "imagemagick"), ("convert", "imagemagick"),
                 ("ffmpeg", "ffmpeg"), ("tesseract", "tesseract-ocr"),
                 ("scrot", "scrot"), ("make", "make"),
                 ("ccache", "ccache"), ("grep", "grep"),
                 ("sed", "sed"), ("supervisorctl", "supervisor"))
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
