#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/supported_env.sh.

supported_env.sh builds and enters the declared capture environment.  It
holds ONE security-relevant promise, and it is the promise that makes the
whole arrangement honest:

    moving the workload to a supported release must not move the GATE

A host operating under PLAYTHROUGH_ALLOW_EOL_PLATFORM has a registered
trust bypass in its environment.  If that value reached the container,
the trust state inside would be `diagnostic` too, every production stage
would refuse there as well, and -- far worse -- a future change that let
one through would produce a container that LOOKED supported while
running relaxed.  So the driver clears every name in env.sh's bypass
registry on the way in, and this suite proves it for each name rather
than for the idea.

    python3 playthrough/tooling/test_supported_env.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

HOW A DOCKER DRIVER IS TESTED WITHOUT BUILDING AN IMAGE
Every test runs the REAL supported_env.sh out of a temporary SANDBOX
CHECKOUT -- a directory carrying playthrough/tooling/supported_env.sh,
the environment/Dockerfile and both requirements files -- so that the
script's own repository-root resolution points at the sandbox and no test
can touch this checkout.  PATH is prefixed with a stub `docker` that
appends its whole argv to a log and answers `info`, `image inspect`,
`build` and `run` from control files the test writes.  That turns "the
bypasses are cleared", "the checkout is mounted at its own path" and
"the proof script is what runs inside" into assertions about a recorded
command line instead of hopes about a container.

WHAT IS ASSERTED
* THE REGISTRY CANNOT DRIFT -- the literal list in supported_env.sh is
  compared against env.sh's own exported PLAYTHROUGH_TRUST_BYPASS_VARS,
  because the driver deliberately does not source env.sh and a copied
  list is a list that can fall behind.
* EVERY BYPASS IS CLEARED -- one assertion per registered name.
* THE MOUNT IS THE CHECKOUT'S OWN PATH -- so a diagnostic quoting a path
  means the same file inside and outside.
* THE BUILD CONTEXT CARRIES WHAT THE IMAGE INSTALLS -- the Dockerfile and
  both requirements files, and nothing from the record.
* A MISSING DOCKER IS NOT A DEAD END -- the refusal names running the
  preflight directly on a supported release instead.
* THE CONTAINMENT CHECK IS REAL -- a container that writes into
  playthrough/ is caught by the before-and-after comparison and reported
  as a changed working tree.
* THE STAGE FAILURE STATUS SURVIVES -- the driver exits with what the
  proof exited with, because a wrapper that swallows a status is a stage
  that appears to have worked.

Standard library only.  Nothing outside the temporary directory is
written, and no container is ever started.
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
SUPPORTED_ENV = os.path.join(TOOLING, "supported_env.sh")
ENV_SH = os.path.join(TOOLING, "env.sh")
DOCKERFILE = os.path.join(TOOLING, "environment", "Dockerfile")

# The registry, read from env.sh at import time so this file states the
# expectation once and the fixture proves the script agrees with it.
BASE_PATH = "/usr/local/bin:/usr/bin:/bin"


def _registry_from_env_sh():
    """Every trust-bypass name env.sh publishes, in its own order."""
    program = ('. "$1" >/dev/null 2>&1\n'
               'printf "%s" "${PLAYTHROUGH_TRUST_BYPASS_VARS}"\n')
    result = subprocess.run(
        ["/usr/bin/env", "-i", "PATH=" + BASE_PATH,
         "/bin/bash", "--noprofile", "--norc", "-c", program,
         "bash", ENV_SH],
        cwd=REPO_ROOT, capture_output=True, timeout=180)
    return result.stdout.decode("utf-8", "replace").split()


REGISTRY = _registry_from_env_sh()

# A stub docker.  It records every invocation and answers from control
# files, so a test decides whether the image "exists" and what the
# container "did" without anything being run.
DOCKER_STUB = r"""#!/bin/sh
log="${STUB_LOG}"
{
    printf 'ARGV'
    for one in "$@"; do printf '\t%s' "${one}"; done
    printf '\n'
} >>"${log}"
case "$1" in
    info)
        [ -f "${STUB_DIR}/no-daemon" ] && exit 1
        exit 0
        ;;
    image)
        [ -f "${STUB_DIR}/no-image" ] && exit 1
        exit 0
        ;;
    build)
        # Record what the build context actually contained: the
        # directory is temporary and is removed the moment the driver
        # returns, so it has to be read here or not at all.
        context=""
        for one in "$@"; do context="${one}"; done
        ls -A "${context}" >"${STUB_DIR}/context" 2>/dev/null || true
        exit 0
        ;;
    run)
        if [ -f "${STUB_DIR}/touch-tree" ]; then
            touch "$(cat "${STUB_DIR}/touch-tree")"
        fi
        if [ -f "${STUB_DIR}/run-status" ]; then
            exit "$(cat "${STUB_DIR}/run-status")"
        fi
        exit 0
        ;;
esac
exit 0
"""


class SupportedEnvFixture(unittest.TestCase):
    """A sandbox checkout, a stub docker, and the real script."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="blitzy_supported_env_")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, "checkout")
        tooling = os.path.join(self.root, "playthrough", "tooling")
        os.makedirs(os.path.join(tooling, "environment"))
        shutil.copyfile(SUPPORTED_ENV,
                        os.path.join(tooling, "supported_env.sh"))
        shutil.copyfile(
            DOCKERFILE,
            os.path.join(tooling, "environment", "Dockerfile"))
        for name in ("requirements.txt", "requirements.lock"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(tooling, name))
        self.script = os.path.join(tooling, "supported_env.sh")
        # The proof script is only ever named on a command line here, so
        # a marker file is enough and keeps the sandbox small.
        with open(os.path.join(tooling, "preflight_capture.sh"), "w",
                  encoding="utf-8") as handle:
            handle.write("#!/usr/bin/env bash\nexit 0\n")
        self.stub_dir = os.path.join(self.base, "stub")
        os.makedirs(self.stub_dir)
        self.stub_log = os.path.join(self.base, "docker.log")
        docker = os.path.join(self.stub_dir, "docker")
        with open(docker, "w", encoding="utf-8") as handle:
            handle.write(DOCKER_STUB)
        os.chmod(docker, 0o755)

    # -- the harness -------------------------------------------------

    def run_script(self, *arguments, **kwargs):
        """Run the sandbox copy and report the completed process."""
        environment = {
            "PATH": kwargs.pop("path", self.stub_dir + ":" + BASE_PATH),
            "STUB_LOG": self.stub_log,
            "STUB_DIR": self.stub_dir,
            "HOME": self.base,
            "TMPDIR": self.base,
        }
        environment.update(kwargs.pop("preset", {}))
        self.assertEqual(kwargs, {}, msg="unexpected keyword arguments")
        return subprocess.run(
            ["/usr/bin/env", "-i"] + [
                "%s=%s" % item for item in environment.items()
            ] + ["/bin/bash", self.script] + list(arguments),
            capture_output=True, timeout=180)

    def control(self, name, contents=""):
        """Write one of the stub's control files."""
        with open(os.path.join(self.stub_dir, name), "w",
                  encoding="utf-8") as handle:
            handle.write(contents)

    def invocations(self):
        """Every recorded docker argv, as a list of lists."""
        if not os.path.exists(self.stub_log):
            return []
        with open(self.stub_log, encoding="utf-8") as handle:
            return [line.rstrip("\n").split("\t")[1:]
                    for line in handle if line.startswith("ARGV")]

    def only_run(self):
        """The single recorded `docker run` argv."""
        runs = [argv for argv in self.invocations()
                if argv and argv[0] == "run"]
        self.assertEqual(
            len(runs), 1,
            msg="expected exactly one `docker run`, got %r"
                % (self.invocations(),))
        return runs[0]

    def make_git_tree(self):
        """A work tree git will answer, with a CLEAN baseline.

        The commit is not decoration.  `git status --porcelain` collapses
        an untracked DIRECTORY to a single line, so with the sandbox
        uncommitted a container that wrote another file inside
        playthrough/ would leave the count unchanged and the containment
        check would look as though it had passed.  Committing first makes
        the baseline zero, and any new path a visible difference.
        """
        for command in (["init", "--quiet"],
                        ["config", "user.email", "t@example.invalid"],
                        ["config", "user.name", "T"],
                        ["add", "-A"],
                        ["-c", "commit.gpgsign=false", "commit",
                         "--quiet", "-m", "the sandbox baseline"]):
            subprocess.run(["git"] + command, cwd=self.root,
                           capture_output=True, timeout=120, check=True)
        state = subprocess.run(
            ["git", "status", "--porcelain", "playthrough/"],
            cwd=self.root, capture_output=True, timeout=120)
        self.assertEqual(
            state.stdout, b"",
            msg="the baseline has to be clean for the containment "
                "check to be able to see a change")

    def empty_path(self):
        """A PATH with no docker on it -- this host has a real one."""
        holder = os.path.join(self.base, "no-tools")
        os.makedirs(holder, exist_ok=True)
        return holder


class TestTheBypassRegistry(SupportedEnvFixture):
    """The copied list may not fall behind env.sh's own."""

    def test_env_sh_publishes_a_registry_to_compare_against(self):
        # A guard on the guard: if this ever comes back empty the two
        # tests below would pass by comparing nothing.
        self.assertTrue(
            REGISTRY,
            msg="env.sh published no PLAYTHROUGH_TRUST_BYPASS_VARS, so "
                "the comparison below would be vacuous")
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM", REGISTRY)

    def test_the_literal_matches_env_sh_exactly(self):
        with open(SUPPORTED_ENV, encoding="utf-8") as handle:
            text = handle.read()
        marker = 'readonly TRUST_BYPASS_VARS="'
        start = text.index(marker) + len(marker)
        literal = text[start:text.index('"', start)]
        self.assertEqual(
            literal.replace("\\\n", " ").split(), REGISTRY,
            msg="supported_env.sh restates env.sh's trust-bypass "
                "registry as a literal, on purpose -- sourcing env.sh "
                "on an end-of-life host is the refusal it routes "
                "around.  The copy has drifted: update it, or the "
                "names missing from it will be forwarded into the "
                "container.")


class TestClearingTheBypasses(SupportedEnvFixture):
    """Every registered name is cleared on the way in."""

    def test_each_registered_bypass_is_cleared(self):
        self.run_script("run", "true")
        argv = self.only_run()
        for name in REGISTRY:
            with self.subTest(bypass=name):
                self.assertIn(
                    "%s=" % name, argv,
                    msg="%s is not cleared inside the container, so a "
                        "host running under it would carry it in and "
                        "the container would be `diagnostic` too"
                        % name)

    def test_a_bypass_in_the_callers_environment_is_still_cleared(self):
        # The case that matters on the host this was written for: the
        # waiver is exported, and it must not travel.
        self.run_script(
            "run", "true",
            preset={"PLAYTHROUGH_ALLOW_EOL_PLATFORM": "a reason"})
        argv = self.only_run()
        self.assertIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM=", argv)
        self.assertNotIn("PLAYTHROUGH_ALLOW_EOL_PLATFORM=a reason",
                         argv)

    def test_no_retired_knob_is_passed_in(self):
        # PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM is retired: =1 is the
        # default and any other value earns a warning saying the knob no
        # longer weakens anything.  Passing it would put that warning in
        # every container's log for no gain.
        self.run_script("run", "true")
        joined = " ".join(self.only_run())
        self.assertNotIn("PLAYTHROUGH_REQUIRE_SUPPORTED_PLATFORM",
                         joined)


class TestTheContainerInvocation(SupportedEnvFixture):
    """What the driver actually asks docker for."""

    def test_the_checkout_is_mounted_at_its_own_absolute_path(self):
        self.run_script("run", "true")
        argv = self.only_run()
        self.assertIn("%s:%s" % (self.root, self.root), argv)
        self.assertIn(self.root, argv)
        self.assertIn("--workdir", argv)

    def test_shared_memory_is_raised_for_the_x_server(self):
        # SDL and the X server share memory through /dev/shm and 64 MB
        # is not enough for a 1920x1080 surface plus the tile atlases.
        self.run_script("run", "true")
        self.assertIn("--shm-size=1g", self.only_run())

    def test_the_command_is_passed_through_unchanged(self):
        self.run_script("run", "bash", "-c", "echo hello")
        argv = self.only_run()
        self.assertEqual(argv[-3:], ["bash", "-c", "echo hello"])

    def test_run_without_a_command_is_a_usage_error(self):
        result = self.run_script("run")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"needs a command", result.stderr)


class TestTheBuild(SupportedEnvFixture):
    """The context carries what the image installs, and no more."""

    def test_the_context_holds_the_dockerfile_and_both_pins(self):
        result = self.run_script("build")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        with open(os.path.join(self.stub_dir, "context"),
                  encoding="utf-8") as handle:
            entries = sorted(handle.read().split())
        self.assertEqual(
            entries,
            ["Dockerfile", "requirements.lock", "requirements.txt"],
            msg="the build context must carry exactly the Dockerfile "
                "and the two requirements files: a wider context sends "
                "the frames and the media to the daemon and "
                "invalidates the cached layers on every edit")

    def test_the_image_is_tagged(self):
        self.run_script("build")
        builds = [argv for argv in self.invocations()
                  if argv and argv[0] == "build"]
        self.assertEqual(len(builds), 1)
        self.assertIn("--tag", builds[0])

    def test_a_missing_dockerfile_is_refused_by_name(self):
        os.remove(os.path.join(self.root, "playthrough", "tooling",
                               "environment", "Dockerfile"))
        result = self.run_script("build")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"environment/Dockerfile", result.stderr)


class TestWhenDockerIsNotAvailable(SupportedEnvFixture):
    """A refusal that names the way forward, not just the obstacle."""

    def test_a_missing_docker_names_the_direct_alternative(self):
        result = self.run_script("build", path=self.empty_path())
        self.assertEqual(result.returncode, 2)
        message = result.stderr.decode("utf-8", "replace")
        self.assertIn("preflight_capture.sh", message)
        self.assertIn("26.04", message)

    def test_the_alternative_does_not_offer_a_host_that_cannot_capture(
            self):
        """Naming a release the support table accepts is not enough.

        Ubuntu 24.04 satisfies env.sh's dated table and still cannot
        deliver keyboard input to the engine's ImGui character creator,
        because its SDL2 is 2.30.0.  An operator sent there by this
        message would reach a frozen creator with nothing to explain
        it, so the message has to carry the second condition too.
        """
        result = self.run_script("build", path=self.empty_path())
        message = result.stderr.decode("utf-8", "replace")
        self.assertIn("SDL", message)
        self.assertIn("2.32", message)
        self.assertIn("24.04", message)
        # Mentioned as the counter-example, not as an option: the
        # sentence that names it must also say it is not a capture host.
        self.assertIn("not a capture host", message)

    def test_a_stopped_daemon_is_distinguished_from_a_missing_one(self):
        self.control("no-daemon")
        result = self.run_script("build")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"daemon", result.stderr)

    def test_an_unbuilt_image_says_how_to_build_it(self):
        self.control("no-image")
        result = self.run_script("run", "true")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"supported_env.sh' build", result.stderr.replace(
            b"supported_env.sh build", b"supported_env.sh' build"))


class TestThePreflightSubcommand(SupportedEnvFixture):
    """The proof runs inside, and its verdict survives the trip."""

    def test_the_proof_script_is_what_runs_inside(self):
        self.make_git_tree()
        result = self.run_script("preflight")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        argv = self.only_run()
        self.assertEqual(argv[-2:], [
            "bash",
            os.path.join(self.root, "playthrough", "tooling",
                         "preflight_capture.sh")])

    def test_a_failing_stage_status_is_propagated(self):
        self.make_git_tree()
        self.control("run-status", "3")
        result = self.run_script("preflight")
        self.assertEqual(
            result.returncode, 3,
            msg="a wrapper that swallows the proof's status is a stage "
                "that appears to have worked")

    def test_a_container_that_writes_into_the_record_is_caught(self):
        self.make_git_tree()
        os.makedirs(os.path.join(self.root, "playthrough", "frames"))
        self.control(
            "touch-tree",
            os.path.join(self.root, "playthrough", "frames",
                         "frame_00001.png"))
        result = self.run_script("preflight")
        self.assertNotEqual(
            result.returncode, 0,
            msg="the preflight writes only into a scratch checkout, so "
                "a changed working tree has to be reported rather than "
                "passed over")
        self.assertIn(b"changed the working tree", result.stderr)

    def test_without_a_work_tree_the_comparison_says_so(self):
        # An export rather than a clone: the driver must still run, and
        # must not claim a comparison it could not make.
        result = self.run_script("preflight")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"not-a-git-tree", result.stderr)


class TestTheCommandLineItself(SupportedEnvFixture):
    """Usage, help, and the refusal of anything else."""

    def test_no_subcommand_is_refused(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"a subcommand is required", result.stderr)

    def test_an_unknown_subcommand_is_refused_by_name(self):
        result = self.run_script("summon")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"'summon'", result.stderr)

    def test_help_lists_every_subcommand_on_stdout(self):
        result = self.run_script("help")
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode("utf-8", "replace")
        for name in ("build", "inventory", "run", "shell", "preflight"):
            with self.subTest(subcommand=name):
                self.assertIn(name, text)

    def test_help_states_that_no_gate_is_relaxed(self):
        result = self.run_script("help")
        self.assertIn("trusted",
                      result.stdout.decode("utf-8", "replace"))


class TestTheScriptItself(unittest.TestCase):
    """Properties of the file, not of a run."""

    def test_it_parses(self):
        result = subprocess.run(["/bin/bash", "-n", SUPPORTED_ENV],
                                capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))

    def test_it_is_shellcheck_clean(self):
        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck is not installed")
        result = subprocess.run(
            ["shellcheck", "-x", "supported_env.sh"],
            cwd=TOOLING, capture_output=True, timeout=300)
        self.assertEqual(
            result.returncode, 0,
            msg="every other shell script in this directory is "
                "shellcheck-clean:\n%s"
                % result.stdout.decode("utf-8", "replace"))

    def test_it_is_executable(self):
        mode = os.stat(SUPPORTED_ENV).st_mode
        self.assertTrue(mode & stat.S_IXUSR,
                        msg="the driver is invoked directly")

    def test_it_does_not_source_env_sh(self):
        # Deliberate: sourcing env.sh on an end-of-life host is the
        # refusal this driver routes around, and it would import the
        # host's own waiver into the process that must not carry one.
        with open(SUPPORTED_ENV, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # The refusals NAME env.sh's support table in prose, on
                # purpose, so the test asks about sourcing rather than
                # about the string: a `.` or `source` command reaching
                # for it is the thing that must not appear.
                sources = (stripped.startswith(". ") or
                           stripped.startswith("source "))
                if sources:
                    self.assertNotIn(
                        "env.sh", stripped,
                        msg="line %d SOURCES env.sh; the driver must "
                            "not, because doing so on an end-of-life "
                            "host is the refusal it exists to route "
                            "around and it would import the host's "
                            "own waiver" % number)


if __name__ == "__main__":
    unittest.main(verbosity=2)
