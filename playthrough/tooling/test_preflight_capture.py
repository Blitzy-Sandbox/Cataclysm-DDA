#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/preflight_capture.sh.

preflight_capture.sh answers one question -- CAN a session be recorded
here? -- and its value depends entirely on the answer being a measurement
rather than a reassurance.  Two properties carry that:

    it FAILS on a host the pipeline's own gates would refuse, and
    it NEVER writes into the committed record while finding out

The first is what makes a pass mean something: the platform verdict, the
trust state and the bypass registry are read back from env.sh, which
recomputes them on every call precisely so a caller cannot forge them.
The second is what makes the file safe to run at all -- stages 7 to 11
launch an engine, capture frames, render and mux, and every one of those
writes goes into a scratch checkout under $TMPDIR.

    python3 playthrough/tooling/test_preflight_capture.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

HOW A CAPTURE PREFLIGHT IS TESTED WITHOUT A CAPTURE
Every test runs the REAL preflight_capture.sh out of a temporary SANDBOX
CHECKOUT carrying copies of env.sh and the script itself, so env.sh's
BASH_SOURCE resolution points the whole artifact layout at the sandbox.
The platform verdict is steered by NOMINATING an os-release file through
PLAYTHROUGH_OS_RELEASE -- which env.sh honours only in a tree git does
not track, and refuses in a real checkout, so the sandbox is deliberately
not a git tree.  That gives both verdicts deterministically, on this host,
with no container and no engine:

    an out-of-support release  -> stage 1 fails and 2..11 are skipped
    a supported release        -> stage 1 passes and the run continues
                                  until it meets something genuinely
                                  absent, which on a bare sandbox is the
                                  toolchain

WHAT IS ASSERTED
* THE UNSUPPORTED HOST FAILS, and fails at stage 1, and says which stage.
* A TRUST BYPASS FAILS THE PREFLIGHT EVEN ON A SUPPORTED RELEASE -- a
  proof taken under a relaxed check would prove the wrong thing.
* THE REMEDY IS NAMED -- the refusal points at supported_env.sh rather
  than stopping at the diagnosis.
* THE LATER STAGES ARE NOT ATTEMPTED after stage 1 fails, so one cause
  reports one failure instead of ten.
* THE STAGE COUNTER IS HONEST -- teardown is stage 11 of 11, not 12 of
  11, which it was until it was measured.
* THE RECORD FINGERPRINT IS TAKEN AND COMPARED, and reports the absence
  of a work tree rather than pretending to a comparison.
* NOTHING IS WRITTEN into the sandbox's playthrough/ tree by a run that
  never reaches the scratch stage.
* THE VERDICT IS ON STDOUT AS KEY=value and the diagnosis on stderr, so a
  caller can read one without parsing the other.

Standard library only.  No container, no X server and no engine is
started: every test here stops at or before stage 2.
"""

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
PREFLIGHT = os.path.join(TOOLING, "preflight_capture.sh")
ENV_SH = os.path.join(TOOLING, "env.sh")

BASE_PATH = "/usr/local/bin:/usr/bin:/bin"

# Two releases env.sh's dated table has an opinion about.  26.04 LTS is
# supported to 2031-04 and 24.10 reached end of life on 2025-07-10, so
# the pair gives both verdicts without this suite carrying a date of its
# own -- if the table ever changes, these tests change with it rather
# than silently testing the wrong branch.
#
# 26.04 rather than 24.04 deliberately, even though 24.04 also passes the
# table: it is the release the declared capture environment is built on,
# because 24.04's SDL 2.30.0 cannot deliver input to the engine's ImGui
# screens.  A fixture that nominated a release the pipeline will not
# capture on would be testing a host nobody should use.
SUPPORTED_RELEASE = ("NAME=\"Ubuntu\"\n"
                     "ID=ubuntu\n"
                     "VERSION_ID=\"26.04\"\n"
                     "PRETTY_NAME=\"Ubuntu 26.04 LTS\"\n")
EXPIRED_RELEASE = ("NAME=\"Ubuntu\"\n"
                   "ID=ubuntu\n"
                   "VERSION_ID=\"24.10\"\n"
                   "PRETTY_NAME=\"Ubuntu 24.10\"\n")


class PreflightFixture(unittest.TestCase):
    """A sandbox checkout and the real preflight script."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="blitzy_preflight_")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, "checkout")
        self.tooling = os.path.join(self.root, "playthrough", "tooling")
        os.makedirs(self.tooling)
        # What env.sh recognises a checkout by.
        os.makedirs(os.path.join(self.root, "data"))
        os.makedirs(os.path.join(self.root, "src"))
        with open(os.path.join(self.root, "src", "path_info.cpp"), "w",
                  encoding="utf-8") as handle:
            handle.write("// a marker, not the engine\n")
        for name in ("env.sh", "preflight_capture.sh"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        self.script = os.path.join(self.tooling, "preflight_capture.sh")

    # -- the harness -------------------------------------------------

    def nominate(self, contents, name="os-release"):
        """An os-release file for env.sh to read instead of the host's.

        env.sh honours PLAYTHROUGH_OS_RELEASE only when the repository
        root is NOT a git work tree, and only for a readable regular file
        that is not a symlink -- a real checkout reads its own host and
        cannot be told otherwise.  The sandbox satisfies exactly those
        conditions, which is what makes both verdicts reachable here.
        """
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(contents)
        return path

    def run_preflight(self, release=EXPIRED_RELEASE, preset=None,
                      path=BASE_PATH, timeout=600):
        """Run the sandbox copy; report (status, keys, stdout, stderr)."""
        environment = {"PATH": path, "HOME": self.base,
                       "TMPDIR": self.base}
        if release is not None:
            environment["PLAYTHROUGH_OS_RELEASE"] = \
                self.nominate(release)
        if preset:
            environment.update(preset)
        result = subprocess.run(
            ["/usr/bin/env", "-i"] + [
                "%s=%s" % item for item in environment.items()
            ] + ["/bin/bash", self.script],
            cwd=self.root, capture_output=True, timeout=timeout)
        stdout = result.stdout.decode("utf-8", "replace")
        keys = {}
        for line in stdout.splitlines():
            name, sep, value = line.partition("=")
            if sep and name and name == name.upper():
                keys[name] = value
        return (result.returncode, keys, stdout,
                result.stderr.decode("utf-8", "replace"))


class TestAnOutOfSupportHost(PreflightFixture):
    """The verdict that matters: this host cannot record."""

    def test_it_fails_and_names_the_stage(self):
        status, keys, _, stderr = self.run_preflight()
        self.assertEqual(status, 3, msg=stderr)
        self.assertEqual(keys.get("PREFLIGHT"), "fail")
        self.assertEqual(keys.get("PREFLIGHT_STAGE_1"), "fail")
        self.assertEqual(keys.get("PLATFORM_SUPPORTED"), "no")
        self.assertEqual(keys.get("PLATFORM_EOL"), "2025-07-10")

    def test_the_later_stages_are_not_attempted(self):
        # One cause must report one failure.  Running stages 2 to 11 on a
        # host stage 1 already disqualified would produce ten failures
        # for one reason and bury the reason.
        _, keys, _, _ = self.run_preflight()
        for number in range(2, 11):
            with self.subTest(stage=number):
                self.assertNotIn("PREFLIGHT_STAGE_%d" % number, keys)
        self.assertEqual(keys.get("PREFLIGHT_FAILURES"), "1")

    def test_the_refusal_names_the_declared_environment(self):
        _, _, _, stderr = self.run_preflight()
        self.assertIn("supported_env.sh", stderr)
        self.assertIn("preflight", stderr)

    def test_teardown_still_runs_and_is_stage_eleven(self):
        # It was stage 12 of 11 until it was measured: stage_begin takes
        # the NEXT number, so the counter is set to the one before.
        _, keys, _, stderr = self.run_preflight()
        self.assertEqual(keys.get("PREFLIGHT_STAGE_11"), "pass")
        self.assertNotIn("PREFLIGHT_STAGE_12", keys)
        self.assertIn("stage 11/11", stderr)

    def test_nothing_is_written_into_the_record(self):
        before = sorted(os.listdir(self.tooling))
        self.run_preflight()
        self.assertEqual(sorted(os.listdir(self.tooling)), before)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "playthrough",
                                        "frames")),
            msg="a run that never reached the scratch stage must not "
                "have created a frames directory")
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "playthrough",
                                        "manifest.jsonl")))


class TestATrustBypass(PreflightFixture):
    """A proof taken under a relaxed check proves the wrong thing."""

    def test_a_bypass_fails_the_preflight_on_a_supported_release(self):
        status, keys, _, stderr = self.run_preflight(
            release=SUPPORTED_RELEASE,
            preset={"PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X": "1"})
        self.assertEqual(status, 3, msg=stderr)
        self.assertEqual(keys.get("PLATFORM_SUPPORTED"), "yes")
        self.assertEqual(keys.get("PREFLIGHT_STAGE_1"), "fail")
        self.assertIn("PLAYTHROUGH_ALLOW_UNAUTHENTICATED_X",
                      keys.get("TRUST_BYPASSES", ""))
        self.assertEqual(keys.get("TRUST_STATE"), "diagnostic")

    def test_the_platform_waiver_is_reported_not_hidden(self):
        _, keys, _, _ = self.run_preflight(
            preset={"PLAYTHROUGH_ALLOW_EOL_PLATFORM": "the only host"})
        self.assertEqual(keys.get("PLATFORM_WAIVER"), "the only host")
        self.assertEqual(keys.get("PREFLIGHT_STAGE_1"), "fail")

    def test_an_exported_verdict_cannot_forge_a_pass(self):
        # playthrough_check_platform recomputes everything and discards
        # what the caller set, because
        # PLAYTHROUGH_PLATFORM_CHECKED=1 PLAYTHROUGH_PLATFORM_SUPPORTED=yes
        # once produced a trusted verdict on an end-of-life host.  The
        # preflight inherits that property; this proves it still holds
        # through this entry point.
        _, keys, _, _ = self.run_preflight(preset={
            "PLAYTHROUGH_PLATFORM_CHECKED": "1",
            "PLAYTHROUGH_PLATFORM_SUPPORTED": "yes",
            "PLAYTHROUGH_PLATFORM_EOL": "2099-01",
        })
        self.assertEqual(keys.get("PLATFORM_SUPPORTED"), "no")
        self.assertEqual(keys.get("PREFLIGHT_STAGE_1"), "fail")


class TestASupportedRelease(PreflightFixture):
    """Stage 1 passes, and the run then meets what is really missing."""

    def test_stage_one_passes_and_the_run_continues(self):
        status, keys, _, stderr = self.run_preflight(
            release=SUPPORTED_RELEASE)
        self.assertEqual(keys.get("PLATFORM_SUPPORTED"), "yes")
        self.assertEqual(keys.get("PLATFORM_EOL"), "2031-04")
        self.assertEqual(keys.get("TRUST_STATE"), "trusted")
        self.assertEqual(keys.get("TRUST_BYPASSES"), "")
        self.assertEqual(keys.get("PREFLIGHT_STAGE_1"), "pass")
        # Stages 2 to 5 are attempted now.  On a bare sandbox with no
        # engine the run cannot pass -- and it must not: a preflight that
        # reported success without an engine would be worthless.
        self.assertIn("PREFLIGHT_STAGE_2", keys)
        self.assertEqual(status, 3, msg=stderr)

    def test_a_missing_engine_is_reported_with_the_build_command(self):
        status, keys, _, stderr = self.run_preflight(
            release=SUPPORTED_RELEASE)
        self.assertEqual(status, 3)
        self.assertEqual(keys.get("PREFLIGHT_STAGE_4"), "fail")
        self.assertIn("launch_game.sh build", stderr)

    def test_the_scratch_stage_is_not_reached_while_anything_failed(self):
        _, keys, _, _ = self.run_preflight(release=SUPPORTED_RELEASE)
        self.assertNotIn("SCRATCH_CHECKOUT", keys)
        self.assertNotIn("PREFLIGHT_STAGE_6", keys)


class TestTheRecordFingerprint(PreflightFixture):
    """Taken on both sides, and honest about what it could not read."""

    def test_it_is_reported_before_and_after(self):
        _, keys, _, _ = self.run_preflight()
        self.assertIn("COMMITTED_RECORD_BEFORE", keys)
        self.assertIn("COMMITTED_RECORD_AFTER", keys)
        self.assertEqual(keys["COMMITTED_RECORD_BEFORE"],
                         keys["COMMITTED_RECORD_AFTER"])

    def test_without_a_work_tree_it_says_so(self):
        # The sandbox is deliberately not a git tree.  Piping a failing
        # `git status` into `wc` under pipefail would end the whole
        # preflight, so the absence is reported instead.
        _, keys, _, _ = self.run_preflight()
        self.assertIn("not-a-git-tree", keys["COMMITTED_RECORD_BEFORE"])
        self.assertIn("frames=0", keys["COMMITTED_RECORD_BEFORE"])

    def test_it_counts_the_frames_and_rows_it_finds(self):
        frames = os.path.join(self.root, "playthrough", "frames")
        os.makedirs(frames)
        for index in (1, 2, 3):
            with open(os.path.join(frames, "frame_%05d.png" % index),
                      "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")
        with open(os.path.join(self.root, "playthrough",
                               "manifest.jsonl"), "w",
                  encoding="utf-8") as handle:
            handle.write("{}\n{}\n")
        _, keys, _, _ = self.run_preflight()
        self.assertIn("frames=3", keys["COMMITTED_RECORD_BEFORE"])
        self.assertIn("rows=2", keys["COMMITTED_RECORD_BEFORE"])


class TestTheOutputContract(PreflightFixture):
    """KEY=value on stdout, diagnosis on stderr, nothing crossed."""

    def test_stdout_carries_only_key_value_lines(self):
        _, _, stdout, _ = self.run_preflight()
        for line in stdout.splitlines():
            if not line:
                continue
            with self.subTest(line=line):
                name, sep, _ = line.partition("=")
                self.assertTrue(
                    sep and name and name == name.upper(),
                    msg="stdout is a machine contract; %r is not a "
                        "KEY=value line" % line)

    def test_the_diagnosis_is_on_stderr(self):
        _, _, stdout, stderr = self.run_preflight()
        self.assertIn("WARNING", stderr)
        self.assertNotIn("WARNING", stdout)

    def test_the_host_and_root_are_recorded(self):
        _, keys, _, _ = self.run_preflight()
        self.assertIn("PREFLIGHT_HOST", keys)
        self.assertEqual(keys.get("PREFLIGHT_REPO_ROOT"), self.root)


class TestTheScriptItself(unittest.TestCase):
    """Properties of the file, not of a run."""

    def test_it_parses(self):
        result = subprocess.run(["/bin/bash", "-n", PREFLIGHT],
                                capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))

    def test_it_is_shellcheck_clean(self):
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck is not installed")
        result = subprocess.run(
            ["shellcheck", "-x", "preflight_capture.sh"],
            cwd=TOOLING, capture_output=True, timeout=300)
        self.assertEqual(
            result.returncode, 0,
            msg="every other shell script in this directory is "
                "shellcheck-clean:\n%s"
                % result.stdout.decode("utf-8", "replace"))

    def test_it_is_executable(self):
        self.assertTrue(os.stat(PREFLIGHT).st_mode & stat.S_IXUSR)

    def test_it_never_names_the_dummy_video_driver(self):
        # SDL_VIDEODRIVER=dummy renders no pixels, so a capture taken
        # under it succeeds and produces a black film.  The value may
        # not appear anywhere in this tree, including as a default.
        with open(PREFLIGHT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("SDL_VIDEODRIVER=dummy", text)

    def test_the_stage_count_has_exactly_one_source(self):
        # The count is stage_begin's format string.  A hardcoded "7/11"
        # anywhere else is a number that can disagree with the counter,
        # and disagreeing was exactly the defect: teardown announced
        # itself as stage 12 of 11.
        with open(PREFLIGHT, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('stage ${STAGE}/11', text)
        hardcoded = re.findall(r"stage \d+/11", text)
        self.assertEqual(
            hardcoded, [],
            msg="these literals duplicate the stage counter: %r"
                % (hardcoded,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
