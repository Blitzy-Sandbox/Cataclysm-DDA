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

import io
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
        if [ -f "${STUB_DIR}/container-id" ]; then
            cat "${STUB_DIR}/container-id"
        fi
        exit 0
        ;;
    ps)
        # Whatever the test decided is running.  One id per line, which
        # is what `docker ps --quiet` produces.
        if [ -f "${STUB_DIR}/ps-out" ]; then
            cat "${STUB_DIR}/ps-out"
        fi
        exit 0
        ;;
    inspect)
        # Answered PER TEMPLATE, because the driver asks three separate
        # questions of one container and a single canned answer could
        # not tell them apart.
        format=""
        want=0
        for one in "$@"; do
            if [ "${want}" = "1" ]; then format="${one}"; want=0; fi
            if [ "${one}" = "--format" ]; then want=1; fi
        done
        # A TEMPLATE CARRYING A BACKSLASH IS REJECTED, exactly as docker
        # rejects it, because a canned answer here hid a real defect: the
        # driver's mount template was wrapped across two lines inside
        # SINGLE quotes, where backslash-newline is literal rather than a
        # continuation.  Real docker exited 64 with `template parsing
        # error: template: :1: unexpected "\\" in operand`; this stub
        # returned the answer anyway, so the tests passed while a hosted
        # session was unreachable.  Stricter than Go on purpose: no
        # template this driver sends needs a backslash, so refusing all
        # of them cannot produce a false failure and does catch the
        # quoting mistake that produced one.
        case "${format}" in
            *'\'*)
                printf '%s\n' 'template parsing error: template: :1: \
unexpected "\\" in operand' >&2
                exit 64
                ;;
        esac
        case "${format}" in
            *Config.Image*) file=inspect-image ;;
            *Mounts*) file=inspect-mount ;;
            *Config.User*) file=inspect-user ;;
            *) file=inspect-other ;;
        esac
        if [ -f "${STUB_DIR}/${file}" ]; then
            cat "${STUB_DIR}/${file}"
        fi
        exit 0
        ;;
    exec)
        # The driver asks two questions through exec: whether the engine
        # is alive, and whether Xvfb is serving.
        #
        # THE ENGINE QUESTION IS ANSWERED BY RUNNING THE DRIVER'S OWN
        # PROBE, not by a canned reply, and that distinction is the whole
        # reason this branch is shaped the way it is.  A canned
        # alive/gone stub is what this file used to have, and it passed
        # while the real probe was broken in two ways at once -- it
        # matched its own `sh -c` wrapper through `pgrep -f`, and it
        # counted a `<defunct>` engine as a running one.  Both were found
        # by hand against a real container, which is exactly the work a
        # test is supposed to save.  So the script the driver passes is
        # EXECUTED here, against a synthetic process table supplied
        # through a fake `ps` earlier on PATH: the awk that decides the
        # answer is the awk that ships.
        text=""
        for one in "$@"; do text="${text} ${one}"; done
        script=""
        for one in "$@"; do script="${one}"; done
        case "${text}" in
            *Xvfb*) printf serving ;;
            *comm*)
                if [ -f "${STUB_DIR}/exec-fails" ]; then exit 1; fi
                PATH="${STUB_DIR}/fakebin:${PATH}"
                export PATH
                sh -c "${script}"
                ;;
            *) : ;;
        esac
        exit 0
        ;;
    stop)
        if [ -f "${STUB_DIR}/stop-status" ]; then
            exit "$(cat "${STUB_DIR}/stop-status")"
        fi
        # A stopped container is gone, unless a test is proving that the
        # driver notices when it is not.
        if [ ! -f "${STUB_DIR}/stop-leaks" ]; then
            : >"${STUB_DIR}/ps-out"
        fi
        exit 0
        ;;
esac
exit 0
"""

# The process table the engine probe reads, standing in for the one
# inside a session container.  It ignores its arguments on purpose: the
# driver asks for `-eo stat=,comm=` and the table is written in exactly
# that shape, so honouring the format would only be a second place for
# the two to disagree.
FAKE_PS = r"""#!/bin/sh
if [ -f "${STUB_DIR}/ps-table" ]; then
    cat "${STUB_DIR}/ps-table"
fi
exit 0
"""

# The two process-table rows that matter, named for the condition each
# one IS rather than for the answer it should produce.
#
# ZOMBIE_ENGINE is not a hypothetical.  PID 1 in a session container is
# `sleep infinity`, which never calls wait(), so every engine that exits
# leaves this row behind permanently -- measured in a real container as
# `1855 Zs cataclysm-tiles [cataclysm-tiles] <defunct>`, still listed
# long after the process was killed.  It is therefore the NORMAL state
# of a container whose session has ended properly, and a probe that read
# it as a running game would refuse to take any finished session down.
LIVE_ENGINE = "Ss cataclysm-tiles"
ZOMBIE_ENGINE = "Zs cataclysm-tiles"
# A process whose name merely CONTAINS the engine's, which must not be
# mistaken for it.
OTHER_PROCESS = "Ss sleep"


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
        # The fake `ps` the engine probe reads its process table from.
        # It lives in its own directory because it is prepended to PATH
        # only for the probe, inside the stub -- putting it beside the
        # docker stub would hand a fake `ps` to every other command the
        # driver runs.
        fakebin = os.path.join(self.stub_dir, "fakebin")
        os.makedirs(fakebin)
        fake_ps = os.path.join(fakebin, "ps")
        with open(fake_ps, "w", encoding="utf-8") as handle:
            handle.write(FAKE_PS)
        os.chmod(fake_ps, 0o755)

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

    def executable_body(self):
        """The script with whole-line comments removed.

        Several properties below are about what the script DOES, and this
        script documents the defects it used to carry by quoting them
        verbatim -- both `trap "rm -rf ...` and
        `pgrep -f "cataclysm-tiles ...` appear in comments explaining why
        they are gone.  A test that searched the raw text would forbid
        keeping that record, so it reads the executable lines instead.
        test_it_does_not_source_env_sh reasons the same way.
        """
        with io.open(self.script, encoding="utf-8") as handle:
            return "".join(line for line in handle
                           if not line.strip().startswith("#"))

    def process_table(self, *rows):
        """Set what the fake `ps -eo stat=,comm=` inside will report.

        Each row is a "STATE NAME" pair exactly as `ps` prints it, so a
        test can state the condition it means rather than the answer it
        expects: LIVE_ENGINE is a running game, ZOMBIE_ENGINE is the
        `<defunct>` entry every finished session leaves behind.
        """
        self.control("ps-table",
                     "".join("%s\n" % row for row in rows))

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
        for name in ("build", "inventory", "run", "shell", "preflight",
                     "up", "exec", "down", "session"):
            with self.subTest(subcommand=name):
                self.assertIn(name, text)

    def test_help_states_that_no_gate_is_relaxed(self):
        result = self.run_script("help")
        self.assertIn("trusted",
                      result.stdout.decode("utf-8", "replace"))


class TestTheHostedSession(SupportedEnvFixture):
    """A container that outlives the individual command.

    WHY IT EXISTS.  The X server inside the container lives as long as
    the process tree that started it, so a `run` per keystroke would
    photograph a different display each time -- and one `run` for the
    whole session would have to be pre-scripted, which is the blind
    key-spamming the record is required not to be.  The invariant is one
    keystroke per session.py invocation with observation in between, so
    the container has to persist and each keystroke is an `exec` onto the
    same live display.
    """

    def test_up_starts_a_detached_container_that_persists(self):
        result = self.run_script("up")
        self.assertEqual(result.returncode, 0)
        argv = [call for call in self.invocations()
                if call and call[0] == "run"]
        self.assertEqual(len(argv), 1, msg=self.invocations())
        self.assertIn("--detach", argv[0])
        # PID 1 has to outlive every exec, which is the whole point.
        self.assertIn("sleep", argv[0])
        self.assertIn("infinity", argv[0])

    def test_up_clears_every_registered_trust_bypass(self):
        """A session may not be hosted under a relaxed check."""
        self.run_script("up")
        argv = [call for call in self.invocations()
                if call and call[0] == "run"][0]
        joined = " ".join(argv)
        for name in ("PLAYTHROUGH_ALLOW_EOL_PLATFORM",):
            with self.subTest(variable=name):
                self.assertIn("%s=" % name, joined)

    def test_a_session_uses_THE_SAME_contract_as_run(self):
        """One contract, or the path is proved on another environment.

        `preflight` proves the production path under a particular set of
        mounts, workdir, user and shm size.  A session hosted under any
        other set would mean the proof and the record were taken on
        different environments, so both take these arguments from one
        array and this compares them.
        """
        # BOTH IN ONE SANDBOX.  Re-running setUp between them would
        # build a second checkout under a different temporary path, and
        # the mounts would then differ for a reason that has nothing to
        # do with the contract.
        self.run_script("up")
        self.run_script("run", "true")
        runs = [call for call in self.invocations()
                if call and call[0] == "run"]
        self.assertEqual(len(runs), 2, msg=self.invocations())
        hosted = next(call for call in runs if "--detach" in call)
        plain = next(call for call in runs if "--detach" not in call)
        for flag in ("--volume", "--workdir", "--shm-size=1g",
                     "--user"):
            with self.subTest(flag=flag):
                self.assertIn(flag, hosted)
                self.assertIn(flag, plain)
        self.assertEqual(
            hosted[hosted.index("--volume") + 1],
            plain[plain.index("--volume") + 1],
            msg="the session must mount exactly what run mounts")

    def test_exec_without_a_command_is_a_usage_error(self):
        result = self.run_script("exec")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"needs a command", result.stderr)

    def test_exec_without_a_session_refuses_rather_than_starting_one(self):
        """Implicit start would change the display mid-session."""
        result = self.run_script("exec", "true")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"no session container is up", result.stderr)
        self.assertIn(b"not started implicitly", result.stderr)

    def test_session_reports_no_when_nothing_is_up(self):
        result = self.run_script("session")
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode("utf-8", "replace")
        self.assertIn("SESSION_UP=no", text)
        self.assertIn("SESSION_NAME=playthrough-session-", text)

    def test_down_with_nothing_up_is_not_an_error(self):
        result = self.run_script("down")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"nothing to take down", result.stderr)

    def test_down_says_the_session_ends_inside_the_game(self):
        """A session is closed through Save & Quit, not through this."""
        text = io.open(self.script, encoding="utf-8").read()
        self.assertIn("Save &", text)
        self.assertIn("REFUSING to take the session", text)


class TestSessionIdentity(SupportedEnvFixture):
    """Which container a command acts on, and why not by name.

    Every test here pins a property a security review found missing.  The
    driver used to select with `docker ps --filter "name=^<name>$"`,
    where the name carried $CLONE_INDEX verbatim -- and docker's name
    filter is a REGULAR EXPRESSION, so an unvalidated index was
    unvalidated regex.  A sibling clone's session container was up on the
    host this was found on.
    """

    def session(self, identifier="c0ffee1234", alive=False,
                image=None, mount=None, user=None):
        """Make the stub answer as one plausible session container.

        `mount` is the SOURCE/DESTINATION listing docker prints for
        `{{range .Mounts}}{{println .Source .Destination}}{{end}}`, not a
        yes/no verdict, so the driver's own matching runs.  This used to
        be a canned "yes" and that hid a real defect: the driver's mount
        template was wrapped across two lines inside single quotes, where
        a backslash-newline is literal rather than a continuation, so
        docker rejected the template outright and the driver refused
        every container -- while these tests passed.
        """
        self.control("ps-out", identifier + "\n")
        self.control("inspect-image",
                     image if image is not None
                     else "playthrough-capture:26.04")
        self.control("inspect-mount",
                     mount if mount is not None
                     else "%s %s\n" % (self.root, self.root))
        self.control("inspect-user",
                     user if user is not None
                     else "%d:%d" % (os.getuid(), os.getgid()))
        self.process_table(
            *([LIVE_ENGINE] if alive else [ZOMBIE_ENGINE]))
        return identifier

    def filters_of(self, verb="ps"):
        """The --filter arguments of the recorded call for `verb`."""
        calls = [call for call in self.invocations()
                 if call and call[0] == verb]
        self.assertTrue(calls, msg=self.invocations())
        argv = calls[0]
        return [argv[index + 1] for index, item in enumerate(argv)
                if item == "--filter"]

    def test_selection_is_by_label_and_never_by_name(self):
        """A name is not an identity, and a name filter is a regex."""
        self.session()
        result = self.run_script("session")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        filters = self.filters_of("ps")
        self.assertTrue(filters, msg=self.invocations())
        for one in filters:
            with self.subTest(filter=one):
                self.assertTrue(
                    one.startswith("label="),
                    msg="only exact label equality identifies a session")
        joined = " ".join(filters)
        self.assertIn("playthrough.role=capture-session", joined)
        self.assertIn("playthrough.checkout=", joined)
        self.assertIn("playthrough.clone=0", joined)

    def test_up_labels_the_container_it_starts(self):
        """Selection by label needs the labels to have been written."""
        self.run_script("up")
        argv = [call for call in self.invocations()
                if call and call[0] == "run"][0]
        labels = [argv[index + 1] for index, item in enumerate(argv)
                  if item == "--label"]
        joined = " ".join(labels)
        self.assertIn("playthrough.role=capture-session", joined)
        self.assertIn("playthrough.checkout=", joined)
        self.assertIn("playthrough.clone=0", joined)

    def test_a_clone_index_that_is_not_a_number_is_refused(self):
        """`CLONE_INDEX='.*'` used to compose a regex that matched all."""
        for value in (".*", "1;2", "0 1", "-1", "a"):
            with self.subTest(value=value):
                result = self.run_script(
                    "session", preset={"CLONE_INDEX": value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    b"is not a number",
                    result.stderr.replace(b"\n", b" "))

    def test_a_clone_index_above_the_range_is_refused(self):
        result = self.run_script("session", preset={"CLONE_INDEX": "100"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"above 99", result.stderr.replace(b"\n", b" "))

    def test_a_padded_clone_index_names_one_session(self):
        """`07` and `7` must not be two different sessions."""
        first = self.run_script("session", preset={"CLONE_INDEX": "07"})
        padded = [one for one in self.filters_of("ps")
                  if one.startswith("label=playthrough.clone=")]
        self.assertEqual(first.returncode, 0)
        os.unlink(self.stub_log)
        self.run_script("session", preset={"CLONE_INDEX": "7"})
        plain = [one for one in self.filters_of("ps")
                 if one.startswith("label=playthrough.clone=")]
        self.assertEqual(padded, plain)
        self.assertEqual(plain, ["label=playthrough.clone=7"])

    def test_two_matching_containers_are_refused_not_chosen(self):
        """`head -n 1` made an ambiguity into a silent choice."""
        self.control("ps-out", "aaaaaaaaaaaa\nbbbbbbbbbbbb\n")
        result = self.run_script("exec", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"will not", result.stderr.replace(b"\n", b" "))
        self.assertEqual(
            [call for call in self.invocations() if call[0] == "exec"],
            [], msg="nothing may be exec'd into while it is ambiguous")

    def test_a_container_running_another_image_is_refused(self):
        self.session(image="some/other:image")
        result = self.run_script("exec", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"some/other:image",
                      result.stderr.replace(b"\n", b" "))

    def test_a_container_without_this_checkout_mounted_is_refused(self):
        """The frames would be written into somebody else's tree."""
        self.session(mount="")
        result = self.run_script("exec", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"no bind mount", result.stderr.replace(b"\n", b" "))

    def test_a_container_running_as_another_user_is_refused(self):
        self.session(user="4242:4242")
        result = self.run_script("exec", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"4242:4242", result.stderr.replace(b"\n", b" "))

    def test_the_mount_is_inspected_with_a_template_docker_accepts(self):
        """The inspection must not refuse the container `up` just made.

        Found live, not here: the mount template was wrapped across two
        lines inside single quotes, so it reached docker carrying a
        literal backslash and newline.  docker exited 64 with a parse
        error, inspect_field swallowed it, and the driver refused a
        container it had created and labelled itself -- `session`
        reported "no bind mount of <this checkout>" about a container
        that had exactly that mount.  Fail-closed, and completely
        unusable.
        """
        self.session()
        result = self.run_script("exec", "true")
        self.assertEqual(
            result.returncode, 0,
            msg="the driver refused its own session container:\n%s"
                % result.stderr.decode("utf-8", "replace"))
        formats = [
            call[call.index("--format") + 1]
            for call in self.invocations()
            if call and call[0] == "inspect" and "--format" in call]
        self.assertTrue(formats, msg=self.invocations())
        for one in formats:
            self.assertNotIn(
                "\\", one,
                msg="docker's template parser rejects a backslash in "
                    "operand position; this one reached it: %r" % one)
            self.assertNotIn("\n", one, msg=repr(one))

    def test_a_mount_of_another_tree_is_refused(self):
        """A real listing, of the wrong tree, must still be refused."""
        self.session(mount="/somewhere/else /somewhere/else\n")
        result = self.run_script("exec", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"no bind mount", result.stderr.replace(b"\n", b" "))

    def test_a_source_only_match_is_not_enough(self):
        """Source and destination must BOTH be this checkout."""
        self.session(mount="%s /elsewhere\n" % self.root)
        result = self.run_script("exec", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"no bind mount", result.stderr.replace(b"\n", b" "))

    def test_an_inspected_container_is_exec_ed_into(self):
        """The refusals must not have closed the ordinary path."""
        self.session()
        result = self.run_script("exec", "true")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        self.assertTrue(
            [call for call in self.invocations() if call[0] == "exec"])


class TestTakingASessionDown(SupportedEnvFixture):
    """`down` must not end a recorded session outside the game.

    A recorded session ends INSIDE the game -- realistic sleep or death,
    then the in-game Save & Quit -- because that is the only exit that
    writes the character file the acceptance gate requires.  The previous
    version of this subcommand warned in prose, ran
    `docker stop ... || true`, and printed "session container removed"
    whether or not anything had been removed.
    """

    def session(self, identifier="c0ffee1234", alive=False):
        self.control("ps-out", identifier + "\n")
        self.control("inspect-image", "playthrough-capture:26.04")
        # The real mount listing, so the driver's own matching runs --
        # see TestSessionIdentity.session for why a canned verdict here
        # was worth removing.
        self.control("inspect-mount", "%s %s\n" % (self.root, self.root))
        self.control("inspect-user",
                     "%d:%d" % (os.getuid(), os.getgid()))
        # `alive=False` deliberately leaves the ZOMBIE row rather than an
        # empty table, because that is what a container whose session
        # ended properly actually looks like.  Every teardown test below
        # therefore also asserts that a `<defunct>` engine does not read
        # as a running one.
        self.process_table(
            *([LIVE_ENGINE, ZOMBIE_ENGINE] if alive else [ZOMBIE_ENGINE]))
        return identifier

    def test_a_live_engine_refuses_the_teardown(self):
        self.session(alive=True)
        result = self.run_script("down")
        self.assertEqual(result.returncode, 3,
                         msg=result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"REFUSING", result.stderr.replace(b"\n", b" "))
        self.assertEqual(
            [call for call in self.invocations() if call[0] == "stop"],
            [], msg="nothing may be stopped by a refused teardown")

    def test_an_abandonment_needs_a_reason(self):
        self.session(alive=True)
        result = self.run_script("down", "--abandon")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"needs a reason", result.stderr.replace(b"\n", b" "))
        self.assertEqual(
            [call for call in self.invocations() if call[0] == "stop"], [])

    def test_an_explicit_abandonment_stops_it_and_says_why(self):
        self.session(alive=True)
        result = self.run_script(
            "down", "--abandon", "the instance is wedged on a modal")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"ABANDONING", result.stderr.replace(b"\n", b" "))
        self.assertIn(b"wedged on a modal",
                      result.stderr.replace(b"\n", b" "))
        self.assertTrue(
            [call for call in self.invocations() if call[0] == "stop"])

    def test_a_dead_engine_needs_no_abandonment(self):
        self.session(alive=False)
        result = self.run_script("down")
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        self.assertTrue(
            [call for call in self.invocations() if call[0] == "stop"])
        self.assertIn(b"stopped and removed",
                      result.stderr.replace(b"\n", b" "))

    def test_an_unanswerable_probe_is_treated_as_a_live_session(self):
        """Fail closed: "cannot tell" must not read as "nothing there"."""
        self.session(alive=False)
        self.control("exec-fails")
        result = self.run_script("down")
        self.assertEqual(result.returncode, 3)
        self.assertIn(b"treating", result.stderr.replace(b"\n", b" "))

    def test_a_stop_that_fails_is_reported_not_swallowed(self):
        self.session(alive=False)
        self.control("stop-status", "1")
        result = self.run_script("down")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"STILL", result.stderr.replace(b"\n", b" "))
        self.assertNotIn(b"stopped and removed",
                         result.stderr.replace(b"\n", b" "))

    def test_a_container_that_survives_the_stop_is_reported(self):
        """"docker said yes" is not the same as "the container is gone"."""
        self.session(alive=False)
        self.control("stop-leaks")
        result = self.run_script("down")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"still running", result.stderr.replace(b"\n", b" "))

    def test_no_session_at_all_is_not_an_error(self):
        result = self.run_script("down")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"nothing to take down",
                      result.stderr.replace(b"\n", b" "))

    def test_an_unknown_argument_is_refused(self):
        result = self.run_script("down", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"unknown argument", result.stderr.replace(b"\n", b" "))

    # -- the probe itself, which was wrong twice ---------------------
    #
    # Both defects below were found by running the probe against a real
    # container, AFTER a canned-answer stub had reported these same tests
    # passing.  Each made the probe answer "alive" unconditionally, and an
    # unconditional refusal is not a safe default: it teaches whoever runs
    # `down` to reach for --abandon every time, which is precisely the
    # protection the guard exists to provide.

    def test_a_defunct_engine_does_not_read_as_a_running_one(self):
        """The normal state of a container that finished a session.

        PID 1 is `sleep infinity` and never calls wait(), so an exited
        engine stays in the table as `<defunct>` for the life of the
        container.  Measured: `1855 Zs cataclysm-tiles` was still listed
        long after the process was killed.  Reading that as a session in
        progress would make every finished session impossible to close.
        """
        self.session()
        self.process_table(ZOMBIE_ENGINE)
        result = self.run_script("down")
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"no engine is running",
                      result.stderr.replace(b"\n", b" "))

    def test_a_live_engine_beside_a_zombie_is_still_found(self):
        """Excluding zombies must not blind the probe to a live game."""
        self.session()
        self.process_table(ZOMBIE_ENGINE, LIVE_ENGINE)
        result = self.run_script("down")
        self.assertEqual(result.returncode, 3)
        self.assertIn(b"STILL RUNNING", result.stderr.replace(b"\n", b" "))

    def test_an_empty_process_table_is_not_a_session(self):
        self.session()
        self.process_table()
        result = self.run_script("down")
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", "replace"))

    def test_the_probe_does_not_match_its_own_command_line(self):
        """CWE-free but just as broken: `pgrep -f` matched the wrapper.

        The probe used to be
        `pgrep -f "cataclysm-tiles --userdir"`, and the `sh -c` carrying
        that pattern has the pattern in its own command line.  Measured
        in a container with no engine at all, the probe printed `alive`
        and `pgrep -af` named only the shell.  Matching on `comm` -- the
        process NAME, which for the probe's own processes is ps, awk or
        sh -- is what makes the question answerable at all.
        """
        body = self.executable_body()
        self.assertNotIn(
            'pgrep -f "cataclysm-tiles', body,
            msg="a full-command-line match finds this probe's own "
                "wrapper and therefore always answers 'alive'")
        self.assertIn("comm=", body)
        # And the end-to-end proof that a name-shaped collision does not
        # fool it: a live process whose name merely contains the engine's
        # is not the engine.
        self.session()
        self.process_table(OTHER_PROCESS, ZOMBIE_ENGINE)
        result = self.run_script("down")
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", "replace"))


class TestTheBuildContextCleanup(SupportedEnvFixture):
    """The EXIT trap is a function name, not composed shell text.

    CWE-78, found by a security review: the trap used to be
    `trap "rm -rf -- '${context}'" EXIT`, which interpolates a
    $TMPDIR-derived path into a string bash later EXECUTES.  A probe with
    a quote and a command substitution in $TMPDIR executed an injected
    marker -- with `rm -rf` holding it.
    """

    def test_no_path_is_interpolated_into_an_executable_trap(self):
        """Every `trap` handler is a bare function name.

        The assertion deliberately reads EXECUTABLE lines only, in the
        same way test_it_does_not_source_env_sh does.  The retired form
        is quoted verbatim in a comment above the fix -- that is the
        record of what the defect was, and a test that forbade the
        string outright would forbid documenting it.  What must not
        exist is a trap whose handler is composed text: a quoted
        argument, or one carrying an expansion.
        """
        with io.open(self.script, encoding="utf-8") as handle:
            lines = handle.readlines()
        handlers = []
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or "trap " not in stripped:
                continue
            argument = stripped.split("trap ", 1)[1]
            handlers.append(argument)
            self.assertFalse(
                argument.startswith('"') or argument.startswith("'"),
                msg="line %d installs a QUOTED trap handler (%s); bash "
                    "executes that string, so any path inside it is "
                    "shell -- CWE-78.  Name a function instead."
                    % (number, stripped))
            self.assertNotIn(
                "$", argument,
                msg="line %d expands something into a trap handler "
                    "(%s); the handler must read the value when it "
                    "fires, not carry it as text." % (number, stripped))
        self.assertEqual(
            handlers, ["cleanup_build_context EXIT"],
            msg="the build context's cleanup is the only trap this "
                "driver installs; a new one needs the same review")

    def test_a_hostile_tmpdir_cannot_execute_anything(self):
        """The one that actually proves it: run with such a $TMPDIR."""
        marker = os.path.join(self.base, "injected")
        hostile = os.path.join(
            self.base, "tmp'$(touch %s)'dir" % marker)
        os.makedirs(hostile)
        result = self.run_script(
            "build", preset={"TMPDIR": hostile})
        self.assertEqual(result.returncode, 0,
                         msg=result.stderr.decode("utf-8", "replace"))
        self.assertFalse(
            os.path.exists(marker),
            msg="a path from the environment was executed as shell")
        # And the context really was removed, so the fix did not simply
        # stop cleaning up.
        self.assertEqual(
            [name for name in os.listdir(hostile)
             if name.startswith("playthrough-ctx-")], [])


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
