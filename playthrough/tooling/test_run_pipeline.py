#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/run_pipeline.sh.

The sequencer decides three things and does nothing else: WHICH stages
run, in WHAT order, and with WHAT arguments.  Most of what can go wrong
with it is therefore a question about a plan, which can be inspected
without rendering a film; the rest is a question about what it actually
DOES with a plan, which is answered here by running the real sequencer
over fake stages inside a temporary checkout.

    python3 playthrough/tooling/test_run_pipeline.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED

* THE GATE RUNS TWICE, AND THE COMMIT IS REACHABLE.  This is the
  regression that matters.  The gate was sequenced once, ahead of the
  commit, and thirteen of its checks ask questions only a commit can make
  true -- is the save tracked, is every class committed, is the tree
  clean.  Measured on a genuine post-session tree, the single gate
  reported nine failures out of a hundred and eight, the sequence stopped
  there, and the run ended with the commit stage UNATTEMPTED: the default
  plan could not reach the checkpoint at all.  So `verify` now runs
  --phase pre-commit ahead of the commit and `attest` runs
  --phase post-commit after it, and this suite pins both the order and
  the two phase arguments.  The second run is the short one -- the gate
  declares 111 checks, 99 before the commit and 24 after it -- so no
  artifact is re-measured after a commit that did not touch it.
* THE THREE PREFLIGHTS.  A checkpoint that cannot be taken, a disk with
  no room for the plan, and a stage nothing has invalidated are all
  knowable BEFORE the first stage, and each was previously discovered
  after the expensive work: eligibility at stage 7, capacity by running
  out of it, and freshness never.  Each has a class below.
* THE TWO PLAN RULES HOLD OVER THE RESOLVED PLAN.  commit will not run
  without verify ahead of it; attest will not run without commit.  Both
  are asserted against the plan rather than against the flags that
  produced it, so a flag added later cannot slip past them.
* --no-commit DROPS BOTH THE COMMIT AND THE ATTESTATION.  With nothing
  committed the attestation would fail for a reason the operator asked
  for, which is a failure that teaches nothing.
* THE LOCK IS SCOPED TO THE CHECKOUT.  Its name carries a digest of the
  repository root, so two runs over one working tree serialise and two
  runs over different ones do not.  A bare name lived in a directory
  derived from CLONE_INDEX, so two clones started without one shared a
  lock and a run over an unrelated tree blocked this one -- while the
  diagnosis claimed the lock was "over this checkout".
* THE HELP DOCUMENTS WHAT THE PARSER ACCEPTS.  Every argument form the
  parser handles appears in the usage text, because an undocumented form
  is one an operator finds by reading the source.
* IT STILL HOLDS NO STAGE'S LOGIC.  No duration bound, no encoder flag,
  no caption codec, no crop rectangle, no staging list.
* THE PLAN IS ACTUALLY EXECUTED, AND IT SHORT-CIRCUITS.  A plan that
  resolves correctly and then runs the wrong thing is a plan nobody
  checked, so the real sequencer is run over fake stages: every stage is
  started, in order, through the interpreter or shell its suffix implies
  and with the exact arguments the registry gives it; a stage that fails
  stops the sequence THERE, nothing after it is started, its own exit
  status is the run's, and the stages the plan still held are named as
  unattempted.  The commit stage in particular is proved never to start
  after a failed gate -- that refusal is the whole reason the gate
  precedes the checkpoint.

HOW A PLAN IS INSPECTED WITHOUT RUNNING A STAGE
run_pipeline.sh ends with `main "$@"`, so sourcing it would run the whole
pipeline.  These tests source a copy with that one line removed, then call
parse_arguments and resolve_plan directly and read PLAN, SKIPPED and
STAGE_COMMAND back.  Nothing is executed and the code under test is the
real file rather than a restatement of it.

WHERE THAT COPY LIVES, AND WHY NOT BESIDE THE ORIGINAL
The trimmed copy used to be written into the REAL playthrough/tooling/
as a hidden `.blitzy_adhoc_test_plan_*.sh`.  That is a file inside the
one tree whose `!/playthrough/**` negation re-includes everything, and
its leading dot put it outside the `blitzy_adhoc_test_*` glob the
checkpoint's hygiene gate refuses -- so an interrupted run left a
committable machine file that no gate would have caught.  Every fixture
here therefore builds a WHOLE MINIATURE CHECKOUT in a temporary
directory -- Makefile, data/json/ui/sidebar.json, src/path_info.cpp, and
playthrough/tooling holding copies of env.sh and run_pipeline.sh -- and
works only inside it.  Both scripts resolve every path from BASH_SOURCE,
so a copy in the sandbox describes the sandbox, which is what makes this
possible at all.  Nothing outside the temporary directory is written.

The sandbox lives under a PRIVATE base rather than /tmp, for the reason
test_commit_artifacts.py and test_embed_captions.py give: env.sh verifies
the ownership and mode of every tool it resolves and of every directory
above it, and /tmp on this host is mode 2777.

Standard library only.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(TOOLING))
SEQUENCER = os.path.join(TOOLING, "run_pipeline.sh")
ENV_SH = os.path.join(TOOLING, "env.sh")

# The sequencer's own exit codes, from its header.
EX_OK = 0
EX_USAGE = 1
EX_LAYOUT = 2
EX_BUSY = 3

# The stages, in the order the pipeline runs them.  Written out here
# rather than read from the script, so a reordering has to be made
# deliberately in two places.
STAGES = ("timeline", "transitions", "render", "srt", "captions",
          "verify", "commit", "attest")
# The stage whose presence in a plan makes the sequencer take the
# lifecycle preflight, named once rather than spelled at each use.
COMMIT_STAGE = "commit"

# The line that runs the pipeline.  Removed from the copy these tests
# source, and asserted to exist so a rename cannot leave the harness
# silently sourcing the whole file.
MAIN_INVOCATION = 'main "$@" || _rp_status=$?'

# The name the trimmed copy takes INSIDE THE SANDBOX.  Plain, because it
# is not in the repository and has no hygiene glob to satisfy; fixed,
# because each sandbox holds exactly one.
PROBE_NAME = "plan_probe.sh"

TIMEOUT = 300

# The name the SUPERSEDED harness gave its trimmed copy inside the
# repository, and how old one has to be before it is taken for the
# leftover of a killed run rather than a concurrent one's.  Nothing
# here writes such a file any more -- that was the defect this suite
# was rebuilt to remove -- but the sweeper below still clears the
# ones an interrupted older run may have left beside the real
# scripts, so the two constants it needs stay named here.  An hour is
# far longer than this suite's whole runtime.
TRIMMED_PREFIX = ".blitzy_adhoc_test_plan_"
STALE_COPY_SECONDS = 3600

# The stage scripts the registry names, and the stage each one serves.
# verify_artifacts.sh appears once and serves two stages, which is the
# property the registry tests assert from the source; here it is what
# makes the two --phase arguments the only difference between them.
STAGE_SCRIPTS = {
    "timeline": "timeline.py",
    "transitions": "make_transitions.py",
    "render": "render_movie.py",
    "srt": "make_srt.py",
    "captions": "embed_captions.sh",
    "verify": "verify_artifacts.sh",
    "commit": "commit_artifacts.sh",
    "attest": "verify_artifacts.sh",
}

# What each stage's invocation looks like when it is recorded by a fake:
# the script's basename followed by the arguments the sequencer adds.
# Spelled out rather than derived, so a change to either the registry or
# the argument list has to be made deliberately here as well.
EXPECTED_INVOCATIONS = {
    "timeline": "timeline.py",
    "transitions": "make_transitions.py",
    "render": "render_movie.py",
    "srt": "make_srt.py",
    "captions": "embed_captions.sh",
    "verify": "verify_artifacts.sh --phase pre-commit",
    "commit": "commit_artifacts.sh final",
    "attest": "verify_artifacts.sh --phase post-commit",
}

# A fake stage records the invocation it was given and then exits with
# whatever status the run asked for.  Two files carry that conversation:
# a log every fake appends to, and a table of invocation-to-status lines
# a test writes to make one stage fail.
LOG_VARIABLE = "PIPELINE_FAKE_LOG"
STATUS_VARIABLE = "PIPELINE_FAKE_STATUS"
# Where a Python fake records the interpreter it was started under, so
# the -B and the resolved interpreter are measured rather than assumed.
PYTHON_VARIABLE = "PIPELINE_FAKE_PYTHON_LOG"

# A fake Python stage.  It has no shebang of its own on purpose: the
# sequencer starts a .py stage through the interpreter env.sh resolved,
# so a shebang here would hide the interpreter this asserts.
PYTHON_FAKE = '''\
import os
import sys

name = os.path.basename(__file__)
label = " ".join([name] + sys.argv[1:])
with open(os.environ["%(log)s"], "a", encoding="utf-8") as handle:
    handle.write(label + "\\n")
record = os.environ.get("%(python)s")
if record:
    with open(record, "a", encoding="utf-8") as handle:
        handle.write("%%s interpreter=%%s dont_write_bytecode=%%d\\n"
                     %% (name, sys.executable,
                        int(bool(sys.dont_write_bytecode))))
status = 0
table = os.environ.get("%(status)s")
if table and os.path.isfile(table):
    with open(table, "r", encoding="utf-8") as handle:
        for line in handle:
            wanted, _, value = line.rstrip("\\n").partition("|")
            if wanted == label:
                status = int(value)
sys.exit(status)
''' % {"log": LOG_VARIABLE, "status": STATUS_VARIABLE,
       "python": PYTHON_VARIABLE}

# A fake shell stage.  The label is assembled in two steps so that a
# stage with no arguments records its bare name rather than a name with
# a trailing space, which is what the assertions compare against.
SHELL_FAKE = '''\
#!/bin/bash
set -u
label="$(basename "$0")"
if [ "$#" -gt 0 ]; then
    label="${label} $*"
fi
printf '%%s\\n' "${label}" >>"${%(log)s}"
status=0
if [ -n "${%(status)s:-}" ] && [ -f "${%(status)s}" ]; then
    while IFS='|' read -r wanted value; do
        if [ "${wanted}" = "${label}" ]; then
            status="${value}"
        fi
    done <"${%(status)s}"
fi
exit "${status}"
''' % {"log": LOG_VARIABLE, "status": STATUS_VARIABLE}


def sequencer_source():
    with open(SEQUENCER, "r", encoding="utf-8") as handle:
        return handle.read()


def _is_private(path):
    """True when PATH and every directory above it are trustworthy.

    The rule env.sh's playthrough_verify_executable applies: every
    component owned by root or by this user and none of them group- or
    world-writable, so nobody can substitute a file between a check and
    the run that follows it.
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

    env.sh resolves every external tool and verifies it, and every
    directory above it.  A sandbox under a world-writable base would
    make every test here exercise the prerequisite failure and assert
    nothing about the sequencer.  /tmp cannot serve on this host, which
    has it at mode 2777.
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
    "would test the prerequisite failure instead of the sequencer.  "
    "Set $PLAYTHROUGH_TEST_TMPDIR to a directory owned by this user "
    "with no group or world write bit on it or on any of its parents.")


def _verified_runtime_root():
    """A private runtime directory beneath the verified XDG root.

    env.sh derives XDG_RUNTIME_DIR itself and refuses a pipeline runtime
    root that is not beneath it, because only that root has been proved
    to be an owner-only 0700 directory: a runtime tree under an
    unverified ancestor can be redirected between one command and the
    next.  The refusal's own remedy is to nominate a directory beneath
    that root, which is what this does -- a unique one per test, removed
    when the test ends, so no suite writes into another's locks and none
    of it lands in the repository.
    """
    root = os.environ.get("XDG_RUNTIME_DIR") or "/tmp/xdg"
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
    except OSError:
        pass
    return tempfile.mkdtemp(prefix="blitzy_runtime_", dir=root)


class SandboxFixture(unittest.TestCase):
    """A miniature checkout holding a copy of the real sequencer.

    Nothing in this class -- and nothing in anything derived from it --
    writes inside the repository.  The copies are the real files, so what
    is exercised is the sequencer itself; the paths it derives from
    BASH_SOURCE are the sandbox's.
    """

    @classmethod
    def setUpClass(cls):
        source = sequencer_source()
        if MAIN_INVOCATION not in source:
            raise AssertionError(
                "run_pipeline.sh no longer ends with %r, so this "
                "harness would source a file that runs the whole "
                "pipeline" % MAIN_INVOCATION)
        cls.sweep_stale_copies()

    @classmethod
    def sweep_stale_copies(cls):
        """Remove a trimmed copy an abruptly killed run left behind.

        The copy has to sit beside the real script, which means it sits
        inside the working tree -- and the terminal `!/playthrough/**`
        negation re-includes everything there, so a leaked one is
        TRACKABLE and can be committed by accident.  addCleanup removes
        it on every ordinary path, but a SIGKILL bypasses cleanup
        entirely, and one was observed left behind by a run whose outer
        timeout terminated the process group.

        The sweep is deliberately narrow, for the same reasons the
        verifier's scratch sweep is: this directory only, the prefix
        only, never a symlink, and only a copy old enough that no
        concurrent run of this suite could still be using it.
        """
        cutoff = time.time() - STALE_COPY_SECONDS
        try:
            names = os.listdir(TOOLING)
        except OSError:
            return
        for name in names:
            if not name.startswith(TRIMMED_PREFIX):
                continue
            path = os.path.join(TOOLING, name)
            try:
                if os.path.islink(path) or not os.path.isfile(path):
                    continue
                if os.stat(path).st_mtime > cutoff:
                    continue
                os.unlink(path)
            except OSError:
                continue

    def setUp(self):
        if SANDBOX_BASE is None:
            self.skipTest(NO_SANDBOX_BASE)
        self.root = tempfile.mkdtemp(prefix="blitzy_pipeline_",
                                     dir=SANDBOX_BASE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.checkout = os.path.join(self.root, "checkout")
        self.tooling = os.path.join(self.checkout, "playthrough",
                                    "tooling")
        os.makedirs(self.tooling)
        # The landmarks both scripts refuse to run without: env.sh wants
        # data/ and src/path_info.cpp, run_pipeline.sh additionally wants
        # the Makefile and the sidebar widget the clock geometry is
        # derived from.
        os.makedirs(os.path.join(self.checkout, "data", "json", "ui"))
        os.makedirs(os.path.join(self.checkout, "src"))
        self.write(os.path.join(self.checkout, "Makefile"),
                   "# a marker, not the build system\n")
        self.write(os.path.join(self.checkout, "data", "json", "ui",
                                "sidebar.json"), "[]\n")
        self.write(os.path.join(self.checkout, "src", "path_info.cpp"),
                   "// a marker, not the engine\n")
        # A SUPPORTED PLATFORM, EMULATED THE WAY env.sh PROVIDES FOR.
        # This sandbox is not a git working tree, which is the VERIFIED
        # condition under which env.sh honours PLAYTHROUGH_OS_RELEASE,
        # and the nomination emulates a host rather than relaxing
        # anything: the dated table is still consulted and an
        # out-of-support answer read from here is still refused.
        #
        # It is used INSTEAD OF the EOL waiver, and that is the point.
        # PLAYTHROUGH_ALLOW_EOL_PLATFORM is a registered trust bypass, so
        # it puts the trust state at 'diagnostic' -- and
        # assert_trusted_plan refuses every stage that DERIVES a
        # delivered artifact under a bypass.  A sandbox run carrying the
        # waiver could therefore not execute one stage that writes
        # anything, which is most of what this suite is about.
        self.os_release = self.write(
            os.path.join(self.checkout, "os-release"),
            'ID=ubuntu\nVERSION_ID="26.04"\n'
            'PRETTY_NAME="Ubuntu 26.04 LTS"\n')
        # THE DEPENDENCY DECLARATIONS TRAVEL WITH THE COPIES.  The
        # sequencer refuses before stage one unless the installed closure
        # matches requirements.txt and requirements.lock, and env.sh
        # derives both paths from the tooling directory it was sourced
        # from -- which is this sandbox's.  Copying the real declarations
        # keeps that assertion doing its real work, measuring the
        # installed libraries against the reviewed pins, instead of
        # failing for want of a file that a sandbox simply did not carry.
        for name in ("env.sh", "run_pipeline.sh", "requirements.txt",
                     "requirements.lock"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        self.sequencer = os.path.join(self.tooling, "run_pipeline.sh")
        os.chmod(self.sequencer, 0o755)
        # THE STAGES, AS THE REGISTRY NAMES THEM.  Present and in the
        # modes a checkout has them in -- a shell stage executable, a
        # Python stage not -- because that is what decides the command
        # the sequencer builds for each of them.  A fake records its own
        # invocation and exits with whatever status a test asked for; the
        # plan tests never start one.
        for script in set(STAGE_SCRIPTS.values()):
            path = os.path.join(self.tooling, script)
            if script.endswith(".py"):
                self.write(path, PYTHON_FAKE, mode=0o644)
            else:
                self.write(path, SHELL_FAKE, mode=0o755)
        # env.sh writes its logs, locks and scratch space under a
        # runtime root it VERIFIES at mode 0700; nominating one inside
        # the sandbox keeps this suite's locks off the shared runtime
        # directory as well as out of the working tree.
        # BENEATH THE VERIFIED XDG ROOT, for the reason
        # _verified_runtime_root gives: env.sh refuses any other pipeline
        # runtime root, and it is still private to this test.
        self.runtime = _verified_runtime_root()
        self.addCleanup(shutil.rmtree, self.runtime, True)
        # The trimmed copy the plan tests source: the real file with its
        # one closing invocation removed, inside the sandbox.
        self.trimmed = os.path.join(self.tooling, PROBE_NAME)
        self.write(self.trimmed,
                   sequencer_source().split(MAIN_INVOCATION)[0])

    # -- fixture plumbing --------------------------------------------

    def write(self, path, text, mode=None):
        """Write a file, creating its parent, and return the path."""
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def environment(self, **overrides):
        """The environment a sandbox invocation inherits.

        HERMETIC BY CONSTRUCTION.  env.sh exports some seventy
        PLAYTHROUGH_* names and the documented way to run anything in
        this pipeline -- including this suite -- is to source it first, so
        an inherited value would point a sandbox run at the committed
        tree.  Measured rather than supposed: a leaked
        PLAYTHROUGH_CONFIG_DIR is refused by the launcher as "outside the
        approved tree", and a leaked PLAYTHROUGH_ALLOW_EOL_PLATFORM
        registers a trust bypass this fixture never asked for.  So EVERY
        inherited PLAYTHROUGH_* name is dropped and the two the sandbox
        needs are set here.
        """
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("PLAYTHROUGH_")}
        env["PLAYTHROUGH_RUNTIME_DIR"] = self.runtime
        env["PLAYTHROUGH_OS_RELEASE"] = self.os_release
        for name, value in overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        return env


class PlanFixture(SandboxFixture):
    """Drives plan resolution in the real script, running no stage."""

    def drive(self, *arguments, **environment):
        """Resolve a plan and report it, or report the refusal.

        Returns (status, fields) where fields carries PLAN, SKIPPED and
        one CMD_<stage> per planned stage.
        """
        script = (
            'set -uo pipefail\n'
            'source "%s" 2>/dev/null\n'
            'trap - EXIT ERR\n'
            'parse_arguments "$@"\n'
            'resolve_plan\n'
            'printf "PLAN=%%s\\n" "${PLAN[*]}"\n'
            'printf "SKIPPED=%%s\\n" "${SKIPPED[*]-}"\n'
            'for s in "${PLAN[@]}"; do\n'
            '  build_stage_command "$s"\n'
            '  printf "CMD_%%s=%%s\\n" "$s" '
            '"$(basename "${STAGE_COMMAND[0]}") ${STAGE_COMMAND[*]:1}"\n'
            'done\n'
        ) % self.trimmed
        env = self.environment(**environment)
        command = ["/bin/bash", "--noprofile", "--norc", "-c", script,
                   "--"]
        command.extend(arguments)
        result = subprocess.run(
            command, cwd=self.checkout, capture_output=True,
            timeout=TIMEOUT, env=env)
        fields = {}
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key] = value
        fields["STDERR"] = result.stderr.decode("utf-8", "replace")
        return result.returncode, fields

    def shell(self, snippet, *arguments, **environment):
        """Run `snippet` with the real script's functions in scope.

        The same trick as drive(): the copy with `main "$@"` removed is
        sourced, so every function under test is the one that ships and
        nothing runs by itself.  The snippet may redefine a function to
        stand in for a collaborator -- the disk measurement and the
        lifecycle probe are both substituted that way, because the
        alternative is a test whose answer depends on how full this host
        happens to be and on whose survivor the repository last recorded.

        Returns (status, stdout, stderr).
        """
        script = ('set -uo pipefail\n'
                  'source "%s" 2>/dev/null\n'
                  'trap - EXIT ERR\n' % self.trimmed) + snippet
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                       "sequencer unit test; no stage is run")
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        command = ["/bin/bash", "--noprofile", "--norc", "-c", script,
                   "--"]
        command.extend(arguments)
        result = subprocess.run(
            command, cwd=REPO_ROOT, capture_output=True,
            timeout=TIMEOUT, env=env)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def fields_of(self, text):
        """KEY=value lines as a dict."""
        found = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                found[key] = value
        return found

    def plan(self, *arguments, **environment):
        """The accepted plan, as a list of stage names."""
        status, fields = self.drive(*arguments, **environment)
        self.assertEqual(
            status, 0,
            msg="that plan was refused:\n%s" % fields["STDERR"])
        return fields["PLAN"].split()

    def refused(self, *arguments, **environment):
        """The diagnosis from a plan that must not be accepted."""
        status, fields = self.drive(*arguments, **environment)
        self.assertNotEqual(
            status, 0,
            msg="that plan was accepted: %s" % fields.get("PLAN"))
        return fields["STDERR"]


class TestTheDefaultPlanReachesTheCheckpoint(PlanFixture):
    """The regression the whole split exists for."""

    def test_the_default_plan_is_every_stage_in_order(self):
        self.assertEqual(self.plan(), list(STAGES))

    def test_the_commit_stage_is_in_the_default_plan(self):
        """It was unreachable, not merely last.

        The gate ahead of it could not pass on an uncommitted tree, so
        the sequence stopped one stage short of the checkpoint every
        time.
        """
        self.assertIn("commit", self.plan())

    def test_the_gate_runs_before_the_commit_and_attest_after(self):
        plan = self.plan()
        self.assertLess(plan.index("verify"), plan.index("commit"))
        self.assertLess(plan.index("commit"), plan.index("attest"))

    def test_the_two_gate_runs_carry_the_two_phases(self):
        """The arguments are the whole difference between them."""
        _, fields = self.drive()
        self.assertEqual(fields["CMD_verify"],
                         "verify_artifacts.sh --phase pre-commit")
        self.assertEqual(fields["CMD_attest"],
                         "verify_artifacts.sh --phase post-commit")

    def test_the_commit_stage_names_the_final_checkpoint(self):
        _, fields = self.drive()
        self.assertEqual(fields["CMD_commit"],
                         "commit_artifacts.sh final")

    def test_the_two_gate_runs_are_the_same_script(self):
        """Not a second copy of the gate: one script, two phases."""
        _, fields = self.drive()
        self.assertTrue(fields["CMD_verify"].startswith(
            "verify_artifacts.sh "))
        self.assertTrue(fields["CMD_attest"].startswith(
            "verify_artifacts.sh "))


class TestItTakesOnlyThePostSessionCheckpoint(PlanFixture):
    """The committer has four milestones; this file may reach exactly one.

    `integration` (the two repository rule files), `dossier` and
    `creation` all assert something about a moment BEFORE the session --
    that no artifact exists yet, that play has not begun, that the
    survivor's words were published first.  A post-session sequencer
    cannot honestly take any of them: by the time it runs, every one of
    those claims is already false.  So the checkpoint it takes is `final`
    and there is no flag that changes that.
    """

    def test_the_commit_stage_takes_final_and_nothing_else(self):
        _, fields = self.drive()
        self.assertEqual(fields["CMD_commit"],
                         "commit_artifacts.sh final")

    def test_no_pre_session_milestone_is_ever_sequenced(self):
        source = sequencer_source()
        for milestone in ("integration", "dossier", "creation"):
            with self.subTest(milestone=milestone):
                self.assertNotIn(
                    'PIPELINE_CHECKPOINT_NAME="%s"' % milestone, source,
                    msg=("the sequencer takes the '%s' milestone, which "
                         "is about a moment before the session it has "
                         "just finished" % milestone))

    def test_the_checkpoint_it_takes_is_named_once(self):
        """One constant, so the name cannot drift between the plan and
        the command."""
        source = sequencer_source()
        self.assertEqual(
            source.count('readonly PIPELINE_CHECKPOINT_NAME='), 1)

    def test_the_note_says_where_the_other_milestones_are_taken(self):
        """An operator who reads only this file still has to end up with
        the rule files committed, so the note names that milestone."""
        source = sequencer_source()
        self.assertIn("integration", source)
        self.assertIn(".gitignore", source)
        self.assertIn("taken by hand", source)


class TestThePlanRules(PlanFixture):
    """Asserted over the resolved plan, not over the flags."""

    def test_the_commit_stage_alone_is_refused(self):
        message = self.refused("--only", "commit")
        self.assertIn("will not run unless the verify stage runs ahead",
                      message)

    def test_the_attest_stage_alone_is_refused(self):
        message = self.refused("--only", "attest")
        self.assertIn("attests to what the commit stage published",
                      message)

    def test_starting_at_the_commit_stage_is_refused(self):
        """--from commit would put the checkpoint ahead of its gate."""
        self.refused("--from", "commit")

    def test_starting_at_the_attest_stage_is_refused(self):
        self.refused("--from", "attest")

    def test_both_refusals_name_the_flag_that_works(self):
        for arguments in (("--only", "commit"), ("--only", "attest")):
            with self.subTest(arguments=arguments):
                self.assertIn("--from verify", self.refused(*arguments))

    def test_from_the_gate_is_the_plan_that_takes_the_checkpoint(self):
        self.assertEqual(self.plan("--from", "verify"),
                         ["verify", "commit", "attest"])

    def test_from_and_only_together_are_refused(self):
        message = self.refused("--from", "verify", "--only", "render")
        self.assertIn("two different plans", message)

    def test_an_unknown_stage_is_refused_and_the_list_is_offered(self):
        message = self.refused("--only", "nonesuch")
        self.assertIn("names no stage", message)
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.assertIn(stage, message)

    def test_an_unknown_option_is_refused(self):
        self.refused("--frobnicate")

    def test_a_flag_without_its_value_is_refused(self):
        for flag in ("--from", "--only"):
            with self.subTest(flag=flag):
                self.assertIn("needs a stage name", self.refused(flag))


class TestNoCommitDropsTheAttestationToo(PlanFixture):
    """With nothing committed there is nothing to attest to."""

    def test_neither_the_commit_nor_the_attestation_is_planned(self):
        plan = self.plan("--no-commit")
        self.assertNotIn("commit", plan)
        self.assertNotIn("attest", plan)

    def test_the_gate_still_runs(self):
        """--no-commit stops before the checkpoint; it does not stop
        checking the artifacts."""
        self.assertEqual(self.plan("--no-commit")[-1], "verify")

    def test_both_are_reported_as_skipped_rather_than_forgotten(self):
        _, fields = self.drive("--no-commit")
        skipped = fields["SKIPPED"].split()
        self.assertIn("commit", skipped)
        self.assertIn("attest", skipped)

    def test_it_composes_with_from(self):
        self.assertEqual(self.plan("--from", "verify", "--no-commit"),
                         ["verify"])


class TestTheDocumentedArgumentForms(PlanFixture):
    """Issue: several accepted forms appeared nowhere in the help."""

    def usage_prose(self):
        """The help text, whitespace collapsed.

        It is hard-wrapped, so a phrase of more than a word or two
        straddles a newline and a literal substring test would fail on
        the wrapping rather than on the content.

        Read from the SANDBOX copy, which is the same bytes as the real
        file: --help returns before the lock and before any stage, so it
        could run anywhere, and running it here keeps every invocation in
        this suite inside the temporary directory.
        """
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", self.sequencer,
             "--help"],
            cwd=self.checkout, capture_output=True, timeout=TIMEOUT,
            env=self.environment())
        self.assertEqual(result.returncode, EX_OK)
        return " ".join(
            result.stdout.decode("utf-8", "replace").split())

    def test_the_equals_forms_work_and_are_documented(self):
        self.assertEqual(self.plan("--from=verify"),
                         ["verify", "commit", "attest"])
        self.assertEqual(self.plan("--only=render"), ["render"])
        prose = self.usage_prose()
        self.assertIn("--from=NAME", prose)
        self.assertIn("--only=NAME", prose)

    def test_a_repeated_flag_takes_the_last_value_and_says_so(self):
        self.assertEqual(
            self.plan("--from", "timeline", "--from", "render")[0],
            "render")
        self.assertEqual(
            self.plan("--only", "srt", "--only", "captions"),
            ["captions"])
        self.assertIn("LAST occurrence wins", self.usage_prose())

    def test_the_terminator_is_accepted_and_documented(self):
        self.assertEqual(self.plan("--"), list(STAGES))
        self.assertIn("end of options", self.usage_prose())

    def test_the_mutual_exclusion_is_documented(self):
        self.assertIn("mutually exclusive", self.usage_prose())

    def test_a_stage_may_be_named_by_its_script(self):
        for spelling in ("render", "render_movie", "render_movie.py"):
            with self.subTest(spelling=spelling):
                self.assertEqual(self.plan("--only", spelling),
                                 ["render"])

    def test_the_attestation_is_named_only_by_its_short_name(self):
        """One script cannot resolve to two stages.

        verify_artifacts.sh already names the `verify` stage, so the
        second run of it is reachable by `attest` alone -- and the help
        says so rather than leaving an operator to discover it.
        """
        self.assertEqual(self.plan("--only", "verify_artifacts.sh"),
                         ["verify"])
        self.assertIn("reachable by its short name only",
                      self.usage_prose())

    def test_the_help_explains_why_the_gate_runs_twice(self):
        prose = self.usage_prose()
        self.assertIn("THE GATE RUNS TWICE", prose)
        self.assertIn("--phase pre-commit", prose)
        self.assertIn("--phase post-commit", prose)

    def test_the_help_is_honest_about_the_stream(self):
        """A stage's output is not captured, so stdout is not this
        file's lines alone."""
        prose = self.usage_prose()
        self.assertIn("THIS FILE'S OWN stdout lines are KEY=value only",
                      prose)
        self.assertIn("A stage's output is NOT captured", prose)


class TestTheTrustGateCoversTheWholePlan(PlanFixture):
    """M-06: the refusal must precede the first stage, not stage three.

    The trust state was logged here and enforced only INSIDE the render
    and the caption mux -- stages three and five.  So a run on a host
    whose state was diagnostic executed `timeline`, `transitions` and
    `srt` first, rewriting timeline.json, every transition PNG and both
    transcripts, and only then met a refusal.  The refusal worked; it
    arrived after the artifact set had already been rewritten under
    exactly the conditions it exists to reject.
    """

    def gate(self, *arguments, **environment):
        """Resolve a plan, then run the trust gate over it."""
        script = (
            'set -uo pipefail\n'
            'source "%s" 2>/dev/null\n'
            'trap - EXIT ERR\n'
            'parse_arguments "$@"\n'
            'resolve_plan\n'
            'assert_trusted_plan\n'
            'printf "GATE_PASSED=%%s\\n" "${PLAN[*]}"\n'
        ) % self.trimmed
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                       "trust gate test; no stage is run")
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        command = ["/bin/bash", "--noprofile", "--norc", "-c", script,
                   "--"]
        command.extend(arguments)
        result = subprocess.run(
            command, cwd=REPO_ROOT, capture_output=True,
            timeout=TIMEOUT, env=env)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def test_every_stage_is_classified(self):
        """A stage with no entry is a stage the gate cannot judge."""
        source = sequencer_source()
        start = source.index("declare -rA STAGE_DERIVES_EVIDENCE=(")
        body = source[start:source.index(")", start)]
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.assertIn("[%s]=" % stage, body)

    def test_the_five_writing_stages_are_the_ones_gated(self):
        source = sequencer_source()
        start = source.index("declare -rA STAGE_DERIVES_EVIDENCE=(")
        body = source[start:source.index(")", start)]
        for stage in ("timeline", "transitions", "render", "srt",
                      "captions"):
            with self.subTest(stage=stage):
                self.assertIn("[%s]=1" % stage, body)
        # Reading and publishing are not derivation.  The checkpoint in
        # particular MUST stay ungated: env.sh's own contract says gating
        # it would leave a host under a waiver unable to commit the very
        # disclosure recording the residual.
        for stage in ("verify", "commit", "attest"):
            with self.subTest(stage=stage):
                self.assertIn("[%s]=0" % stage, body)

    def test_a_deriving_plan_is_refused_under_a_bypass(self):
        status, out, err = self.gate(
            "--only", "timeline",
            PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES="1")
        self.assertNotEqual(status, 0)
        self.assertNotIn("GATE_PASSED", out)
        self.assertIn("DERIVE a delivered artifact", err)

    def test_a_read_only_plan_is_exempt(self):
        """The more important half: diagnosis must stay available.

        Measuring a tree and publishing what is already in it are exactly
        what an operator needs MOST when the host is imperfect, so
        refusing them would withhold the diagnosis and strand the
        disclosure.
        """
        status, out, _ = self.gate(
            "--only", "verify",
            PLAYTHROUGH_ALLOW_UNVERIFIED_EXECUTABLES="1")
        self.assertEqual(status, 0)
        self.assertIn("GATE_PASSED=verify", out)

    def test_the_exemption_cannot_be_claimed_by_a_flag(self):
        """It is computed from the declaration, not asserted.

        A plan that would WRITE cannot buy its way past the gate by
        naming itself read-only, because nothing in the decision reads an
        operator-supplied value.
        """
        source = sequencer_source()
        start = source.index("assert_trusted_plan() {")
        body = source[start:source.index("\n}", start)]
        self.assertIn("STAGE_DERIVES_EVIDENCE", body)
        for spelling in ("READ_ONLY", "--read-only", "FORCE"):
            with self.subTest(spelling=spelling):
                self.assertNotIn(spelling, body)

    def test_the_gates_run_before_any_stage(self):
        """Order is the whole fix, so the order is asserted.

        usage -> resources -> environment -> policy -> stages.  The gates
        sit as late as they can while still preceding anything that
        writes: put before the LOCK they silently changed two exit codes
        this file already contracted for, answering a busy checkout with
        the trust refusal on any host whose state is diagnostic.
        """
        source = sequencer_source()
        body = source[source.index("    parse_arguments \"$@\""):]
        timeout = body.index("assert_lock_timeout")
        lock = body.index("acquire_pipeline_lock")
        closure = body.index("assert_dependency_closure")
        trust = body.index("assert_trusted_plan")
        loop = body.index('for index in "${!PLAN[@]}"')
        self.assertLess(timeout, lock)
        self.assertLess(lock, closure)
        self.assertLess(closure, trust)
        self.assertLess(trust, loop)

    def test_a_usage_error_is_not_overtaken_by_a_policy_refusal(self):
        """A mistyped number is a usage error, whatever the host.

        The timeout used to be validated inside acquire_pipeline_lock, so
        adding gates ahead of it answered a typo with the platform
        refusal -- telling an operator to migrate hosts when what they had
        done was mistype a number.
        """
        source = sequencer_source()
        start = source.index("assert_lock_timeout() {")
        body = source[start:source.index("\n}", start)]
        self.assertIn("EX_USAGE", body)
        self.assertIn("playthrough_validate_int", body)


class TestTheDependencyClosureIsEnforcedBeforeStageOne(PlanFixture):
    """M-05: an executable interpreter is not a dependency closure.

    The preflight checked only that PLAYTHROUGH_PYTHON could be executed,
    so nothing established that any of the six declared libraries was
    installed -- let alone at the declared version.  A run would reach
    `transitions` and fail inside MoviePy on an import, two stages after
    it began rewriting artifacts; or succeed against a MoviePy that was
    not the reviewed one and silently change the film.
    """

    def closure(self, *arguments, **environment):
        # THE EXIT TRAP IS RE-REGISTERED, and it has to be.  The harness
        # clears the sourced file's traps so that a fixture failure cannot
        # run the sequencer's own teardown at an unexpected moment -- but
        # assert_dependency_closure CREATES a scratch directory under the
        # runtime root, and _rp_on_exit is what removes it.  Without this
        # line the suite left one <runtime>/pipeline-* behind per test that
        # reached the closure, which is precisely the unbounded
        # accumulation env.sh's pruner exists to end.  Measured: two
        # directories per full run.  It is a no-op for the lock, which this
        # harness never takes.
        script = (
            'set -uo pipefail\n'
            'source "%s" 2>/dev/null\n'
            'trap - EXIT ERR\n'
            "trap '_rp_on_exit' EXIT\n"
            'parse_arguments "$@"\n'
            'resolve_plan\n'
            'assert_dependency_closure\n'
            'printf "CLOSURE_PASSED=1\\n"\n'
        ) % self.trimmed
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                       "closure test; no stage is run")
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        command = ["/bin/bash", "--noprofile", "--norc", "-c", script,
                   "--"]
        command.extend(arguments)
        result = subprocess.run(
            command, cwd=REPO_ROOT, capture_output=True, timeout=TIMEOUT,
            env=env)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def test_the_provisioned_closure_passes_and_is_reported(self):
        status, out, err = self.closure("--only", "timeline")
        self.assertEqual(status, 0, msg=err)
        self.assertIn("CLOSURE_PASSED=1", out)
        # The inventory travels with the run, so the record says which
        # libraries produced it.
        self.assertIn("PIPELINE_CLOSURE=", out)
        self.assertIn("moviepy==", out)

    def test_an_interpreter_without_the_libraries_is_refused(self):
        """And the refusal names the properties, not just a status."""
        status, out, err = self.closure(
            "--only", "timeline", PLAYTHROUGH_PYTHON="/usr/bin/python3")
        self.assertNotEqual(status, 0)
        self.assertNotIn("CLOSURE_PASSED", out)
        self.assertIn("not the one this pipeline was reviewed against",
                      err)
        self.assertIn("moviepy", err)

    def test_a_plan_with_no_python_stage_needs_no_closure(self):
        """`--only captions` is a shell stage; nothing to measure."""
        status, out, err = self.closure("--only", "captions")
        self.assertEqual(status, 0, msg=err)
        self.assertIn("CLOSURE_PASSED=1", out)

    def test_the_program_comes_from_env_sh(self):
        """One assertion, two consumers, defined in neither of them."""
        source = sequencer_source()
        self.assertIn("playthrough_write_closure_checker", source)
        self.assertIn("PLAYTHROUGH_REQUIREMENTS_LOCK", source)

    def test_a_crash_is_not_reported_as_a_failing_closure(self):
        """Different faults, different remedies, different messages.

        "the checker could not run" sends an operator to the interpreter;
        "the closure is wrong" sends them to the installed libraries.
        Reporting one as the other sends them to the wrong file.
        """
        source = sequencer_source()
        start = source.index("assert_dependency_closure() {")
        body = source[start:source.index("\n}", start)]
        # Fragments that live inside ONE string literal: the diagnostics
        # here are wrapped across shell line continuations, so a phrase
        # spanning two of them is not contiguous in the source even though
        # it is contiguous in the output.
        self.assertIn("dependency closure could not be", body)
        self.assertIn("checker failing to run rather than the", body)
        # Detected by its own evidence, never by the exit status alone.
        self.assertIn('[ -s "${err}" ] || [ ! -s "${out}" ]', body)

    def test_the_scratch_directory_is_outside_the_checkout(self):
        """It holds a program, so it must not be stageable."""
        source = sequencer_source()
        start = source.index("open_pipeline_scratch() {")
        body = source[start:source.index("\n}", start)]
        self.assertIn("PLAYTHROUGH_RUNTIME_DIR", body)
        self.assertIn("playthrough_secure_dir", body)

    def test_the_scratch_is_assigned_not_printed(self):
        """THE SUBSHELL TRAP, pinned.

        Written to PRINT its path -- so a caller would say
        `dir="$(open_pipeline_scratch)"` -- the assignment to
        PIPELINE_SCRATCH happened inside the command substitution's
        subshell and was discarded.  Every caller still worked; only the
        exit trap, reading an empty variable in the parent, silently
        cleaned nothing up, and a refused run left <runtime>/pipeline-*
        behind.  Measured before it shipped.
        """
        source = sequencer_source()
        start = source.index("open_pipeline_scratch() {")
        body = source[start:source.index("\n}", start)]
        self.assertNotIn("printf '%s' \"${PIPELINE_SCRATCH}\"", body)
        # And no caller may invoke it through a command substitution.
        # Comments are stripped first: both this function and its caller
        # QUOTE the forbidden form in prose to explain why it is
        # forbidden, and a naive search finds those and reports the
        # explanation as the defect.
        code = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#"))
        self.assertNotIn("$(open_pipeline_scratch)", code)
        # The exit trap removes it, guarded on the prefix it created.
        trap = source[source.index("_rp_on_exit() {"):]
        trap = trap[:trap.index("\n}")]
        self.assertIn("pipeline-*", trap)
        self.assertIn("rm -rf", trap)


# ---------------------------------------------------------------------
# EXECUTION.  Everything above resolves a plan; everything below RUNS
# one.
#
# The sequencer's whole remaining job is what it does with the plan it
# resolved: start each stage through the right interpreter, with the
# right arguments, in order, stop at the first refusal, pass that
# refusal's status out, and say what it did not attempt.  None of that is
# visible in a plan, and all of it is what an operator depends on -- so
# the real file is run over stages that record their own invocation and
# exit with whatever status a test asks for.
# ---------------------------------------------------------------------


class ExecutionFixture(SandboxFixture):
    """Runs the real sequencer over fake stages, and reads back what ran.

    A fake stage is a real file in the sandbox's playthrough/tooling,
    named exactly as the registry names it, that appends its own
    invocation to a log and exits with a status the test chose.  So the
    ORDER, the ARGUMENTS, the SHORT-CIRCUIT and the STATUS are all
    measured from the outside, and no stage's logic is involved in
    measuring them.
    """

    # THE LIFECYCLE PROBE IS AN INVOCATION TOO, AND IT IS NOT A STAGE.
    # A plan that contains the checkpoint asks commit_artifacts.sh
    # `status` before the first stage: a read-only probe of whether the
    # checkpoint could be taken at all, so that a run does not spend the
    # timeline, the encode and both transcripts on a plan that could
    # never reach its own checkpoint.  It changes nothing, it is asked
    # once, and it is asked whether or not the checkpoint is reached --
    # so the invocation log carries it and `expected` accounts for it.
    LIFECYCLE_PROBE = "commit_artifacts.sh status"

    def setUp(self):
        super(ExecutionFixture, self).setUp()
        self.log = os.path.join(self.root, "invocations.log")
        self.statuses = os.path.join(self.root, "statuses")
        self.python_log = os.path.join(self.root, "interpreters.log")
        self.write(self.log, "")

    # -- arranging a run ---------------------------------------------

    def fail_stage(self, stage, status):
        """Make one stage exit with `status` when it is invoked.

        Keyed on the INVOCATION rather than on the file, because
        verify_artifacts.sh serves two stages: a table keyed on the file
        could not fail the gate without also failing the attestation, and
        the two are exactly what needs telling apart.
        """
        existing = ""
        if os.path.isfile(self.statuses):
            with open(self.statuses, "r", encoding="utf-8") as handle:
                existing = handle.read()
        self.write(self.statuses, existing + "%s|%d\n"
                   % (EXPECTED_INVOCATIONS[stage], status))

    # -- running it ---------------------------------------------------

    def run_pipeline(self, *arguments, **environment):
        """Run the sandbox sequencer.  Returns (status, fields, stderr).

        `fields` is the KEY=value machine channel; every stage's own
        output would appear there too, so the fakes deliberately write
        nothing to stdout.
        """
        env = self.environment(**environment)
        env[LOG_VARIABLE] = self.log
        env[STATUS_VARIABLE] = self.statuses
        env[PYTHON_VARIABLE] = self.python_log
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", self.sequencer,
             *arguments],
            cwd=self.checkout, capture_output=True, timeout=TIMEOUT,
            env=env)
        fields = {}
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            self.assertIn(
                "=", line,
                msg="stdout is KEY=value only, got %r" % line)
            key, _, value = line.partition("=")
            fields[key] = value
        return (result.returncode, fields,
                result.stderr.decode("utf-8", "replace"))

    def succeeds(self, *arguments, **environment):
        """Run a pipeline that must reach the end of its plan."""
        status, fields, err = self.run_pipeline(*arguments, **environment)
        self.assertEqual(
            status, EX_OK,
            msg="the pipeline stopped:\n%s" % err)
        return fields, err

    # -- reading it back ----------------------------------------------

    def invocations(self):
        """Every stage invocation, in the order it was started."""
        with open(self.log, "r", encoding="utf-8") as handle:
            return [line for line in handle.read().split("\n") if line]

    def interpreters(self):
        """One record per Python stage: its interpreter and its -B."""
        if not os.path.isfile(self.python_log):
            return []
        with open(self.python_log, "r", encoding="utf-8") as handle:
            return [line for line in handle.read().split("\n") if line]

    def stage_invocations(self):
        """Every STAGE invocation, with the lifecycle probe removed.

        A test about what each stage was handed has no business reading
        the probe, which is not a stage and takes no stage's arguments.
        """
        recorded = self.invocations()
        if recorded and recorded[0] == self.LIFECYCLE_PROBE:
            return recorded[1:]
        return recorded

    def expected(self, stages, probed=None):
        """The invocations `stages` should produce, in order.

        `probed` says whether the PLAN contained the checkpoint, which is
        what decides the preflight -- not whether the checkpoint was
        reached, because a run that stops at stage one has already made
        the probe.  It defaults to the honest reading of `stages`.
        """
        if probed is None:
            probed = COMMIT_STAGE in stages
        planned = [EXPECTED_INVOCATIONS[stage] for stage in stages]
        if probed:
            return [self.LIFECYCLE_PROBE] + planned
        return planned

    def resolved_interpreter(self):
        """The interpreter env.sh resolves in this sandbox.

        Asked of env.sh rather than assumed from sys.executable: the
        point of the assertion it feeds is that the sequencer starts a
        Python stage under THE INTERPRETER THE CONTRACT RESOLVED, and a
        test that supplied its own answer would pass against a sequencer
        that had reached for any python3 on PATH.
        """
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c",
             '. "$1" && printf "%s" "${PLAYTHROUGH_PYTHON}"', "bash",
             os.path.join(self.tooling, "env.sh")],
            cwd=self.checkout, capture_output=True, timeout=TIMEOUT,
            env=self.environment())
        resolved = result.stdout.decode("utf-8", "replace").strip()
        self.assertTrue(
            resolved,
            msg="env.sh resolved no interpreter: %s"
                % result.stderr.decode("utf-8", "replace"))
        return resolved


class TestEveryStageOfThePlanIsActuallyRun(ExecutionFixture):
    """The default plan, executed rather than resolved."""

    def test_all_eight_stages_run_in_the_planned_order(self):
        self.succeeds()
        self.assertEqual(self.invocations(), self.expected(STAGES))

    def test_each_stage_is_given_exactly_the_arguments_it_owns(self):
        """The three that take one, and the five that take none.

        Asserted from the invocation each stage RECORDED, so an argument
        the sequencer builds correctly and then loses on the way to the
        process would fail here and nowhere else.
        """
        self.succeeds()
        recorded = self.stage_invocations()
        for stage, invocation in zip(STAGES, recorded):
            with self.subTest(stage=stage):
                self.assertEqual(invocation,
                                 EXPECTED_INVOCATIONS[stage])

    def test_the_gate_runs_twice_and_the_commit_sits_between_them(self):
        self.succeeds()
        recorded = self.invocations()
        gate = [index for index, invocation in enumerate(recorded)
                if invocation.startswith("verify_artifacts.sh ")]
        commit = recorded.index("commit_artifacts.sh final")
        self.assertEqual(len(gate), 2)
        self.assertLess(gate[0], commit)
        self.assertLess(commit, gate[1])

    def test_every_stage_reports_a_pass_note(self):
        fields, _ = self.succeeds()
        for stage in STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(
                    fields["PIPELINE_STAGE_%s" % stage.upper()], "pass")

    def test_the_run_reports_its_plan_its_checkpoint_and_its_verdict(self):
        fields, _ = self.succeeds()
        self.assertEqual(fields["PIPELINE_PLAN"], " ".join(STAGES))
        self.assertEqual(fields["PIPELINE_SKIPPED"], "none")
        self.assertEqual(fields["PIPELINE_CHECKPOINT"], "final")
        self.assertEqual(fields["PIPELINE_STATUS"], "0")
        self.assertEqual(fields["PIPELINE"], "pass")
        self.assertRegex(fields["PIPELINE_ELAPSED"], r"^\d+$")

    def test_nothing_is_reported_as_unattempted(self):
        fields, _ = self.succeeds()
        self.assertNotIn("PIPELINE_UNATTEMPTED", fields)

    def test_the_python_stages_run_under_the_resolved_interpreter(self):
        """With -B in force, which is not a detail.

        playthrough/ is the one tree the terminal `!/playthrough/**`
        negation re-includes, so a __pycache__ written beside a stage is
        committable -- and the checkpoint's hygiene gate refuses one.
        The sequencer therefore starts every .py stage as
        `$PLAYTHROUGH_PYTHON -B`, and both halves are measured here from
        inside the stage rather than read off the source.
        """
        self.succeeds()
        records = self.interpreters()
        self.assertEqual(len(records), 4,
                         msg="four of the eight stages are Python")
        # A venv interpreter is reached through a chain of links, and
        # sys.executable reports the name it was STARTED as, so the two
        # spellings are compared as the same file rather than as the same
        # string.
        expected = os.path.realpath(self.resolved_interpreter())
        for record in records:
            with self.subTest(record=record):
                fields = dict(
                    item.split("=", 1) for item in record.split(" ")[1:])
                self.assertEqual(
                    os.path.realpath(fields["interpreter"]), expected)
                self.assertEqual(fields["dont_write_bytecode"], "1")
        self.assertFalse(
            os.path.exists(os.path.join(self.tooling, "__pycache__")),
            msg="a stage left bytecode beside itself")

    def test_a_second_run_repeats_the_whole_plan(self):
        """The sequencer is re-runnable: it holds no state of its own.

        The lock is released however a run ends, so a second invocation
        over the same tree neither contends with the first nor skips a
        stage it has already taken.
        """
        self.succeeds()
        self.succeeds()
        self.assertEqual(self.invocations(),
                         self.expected(STAGES) + self.expected(STAGES))


class TestAFailedStageStopsTheSequenceThere(ExecutionFixture):
    """Short-circuit, status pass-through, and what was not attempted."""

    # A status per stage, all distinct and none of them the sequencer's
    # own 1, 2 or 3, so a code invented here could not be mistaken for a
    # code passed through from a stage.
    STATUSES = {"timeline": 9, "transitions": 10, "render": 11,
                "srt": 12, "captions": 8, "verify": 13, "commit": 7,
                "attest": 14}

    def test_each_stage_in_turn_stops_everything_after_it(self):
        for position, stage in enumerate(STAGES):
            with self.subTest(stage=stage):
                self.setUp()
                self.fail_stage(stage, self.STATUSES[stage])
                status, fields, err = self.run_pipeline()
                self.assertEqual(
                    status, self.STATUSES[stage],
                    msg=("the failing stage's own status is what the "
                         "run ends with, because those codes carry "
                         "diagnosis:\n%s" % err))
                self.assertEqual(
                    self.invocations(),
                    self.expected(STAGES[:position + 1], probed=True),
                    msg="a stage after the failure was started")
                self.assertEqual(
                    fields["PIPELINE_STAGE_%s" % stage.upper()], "fail")
                self.assertEqual(fields["PIPELINE_FAILED_STAGE"], stage)
                self.assertEqual(fields["PIPELINE"], "fail")
                self.assertEqual(fields["PIPELINE_STATUS"],
                                 str(self.STATUSES[stage]))

    def test_the_stages_the_plan_still_held_are_named(self):
        for position, stage in enumerate(STAGES):
            with self.subTest(stage=stage):
                self.setUp()
                self.fail_stage(stage, self.STATUSES[stage])
                _, fields, err = self.run_pipeline()
                remaining = list(STAGES[position + 1:])
                if remaining:
                    self.assertEqual(
                        fields["PIPELINE_UNATTEMPTED"],
                        " ".join(remaining))
                    self.assertIn("not attempted: %s"
                                  % " ".join(remaining), err)
                else:
                    self.assertNotIn("PIPELINE_UNATTEMPTED", fields)

    def test_a_failed_gate_never_reaches_the_checkpoint(self):
        """The refusal the whole gate-before-commit order exists for.

        A film that is black, or captions that have drifted out of step
        with the pictures, is a run in which every count still tallies
        and only the gate says otherwise.  So the commit stage must not
        be started at all.
        """
        self.fail_stage("verify", 1)
        status, fields, err = self.run_pipeline()
        self.assertEqual(status, 1)
        self.assertNotIn("commit_artifacts.sh final",
                         self.invocations())
        self.assertEqual(fields["PIPELINE_FAILED_STAGE"], "verify")
        self.assertIn("no checkpoint was taken", err)

    def test_a_failure_says_which_stage_and_what_it_left_behind(self):
        self.fail_stage("render", 11)
        _, _, err = self.run_pipeline()
        self.assertIn("STAGE 3/8 render FAILED", err)
        self.assertIn("exit 11", err)
        self.assertIn("Nothing after it is run", err)

    def test_an_earlier_stage_still_ran_and_is_reported_as_passing(self):
        """A stopped run reports what DID happen, not only what did not."""
        self.fail_stage("render", 11)
        _, fields, _ = self.run_pipeline()
        self.assertEqual(fields["PIPELINE_STAGE_TIMELINE"], "pass")
        self.assertEqual(fields["PIPELINE_STAGE_TRANSITIONS"], "pass")
        self.assertEqual(fields["PIPELINE_STAGE_RENDER"], "fail")
        for stage in ("SRT", "CAPTIONS", "VERIFY", "COMMIT", "ATTEST"):
            with self.subTest(stage=stage):
                self.assertNotIn("PIPELINE_STAGE_%s" % stage, fields)

    def test_the_attestation_can_fail_without_the_gate_failing(self):
        """One script, two stages, two statuses.

        The table is keyed on the invocation, which is what makes this
        possible -- and it is the shape a real run takes when the
        pre-commit half passes and the post-commit half does not.
        """
        self.fail_stage("attest", 14)
        status, fields, _ = self.run_pipeline()
        self.assertEqual(status, 14)
        self.assertEqual(fields["PIPELINE_STAGE_VERIFY"], "pass")
        self.assertEqual(fields["PIPELINE_STAGE_ATTEST"], "fail")
        self.assertEqual(self.invocations(), self.expected(STAGES))


class TestTheSelectedPlansAreExecutedAsSelected(ExecutionFixture):
    """--only, --from and --no-commit, run rather than resolved."""

    def test_no_commit_runs_through_the_gate_and_stops(self):
        fields, _ = self.succeeds("--no-commit")
        self.assertEqual(
            self.invocations(),
            self.expected(("timeline", "transitions", "render", "srt",
                           "captions", "verify")))
        self.assertEqual(fields["PIPELINE_CHECKPOINT"], "none")
        self.assertEqual(fields["PIPELINE_SKIPPED"], "commit attest")

    def test_from_the_gate_runs_exactly_the_three_closing_stages(self):
        self.succeeds("--from", "verify")
        self.assertEqual(self.invocations(),
                         self.expected(("verify", "commit", "attest")))

    def test_only_one_stage_runs_only_that_stage(self):
        self.succeeds("--only", "srt")
        self.assertEqual(self.invocations(), ["make_srt.py"])

    def test_a_refused_plan_runs_nothing_at_all(self):
        status, _, err = self.run_pipeline("--only", "commit")
        self.assertEqual(status, EX_USAGE, msg=err)
        self.assertEqual(self.invocations(), [])

    def test_a_missing_stage_script_runs_nothing_at_all(self):
        """Every stage is checked BEFORE the first one starts.

        Discovering the fourth stage is absent after the third has
        already rewritten an artifact is a half-finished pipeline; the
        preflight makes it a refusal instead.
        """
        os.unlink(os.path.join(self.tooling, "make_srt.py"))
        status, _, err = self.run_pipeline()
        self.assertEqual(status, EX_LAYOUT)
        self.assertIn("make_srt.py", err)
        self.assertEqual(self.invocations(), [])


class TestAShellStageWithNoExecutableBit(ExecutionFixture):
    """It is still run, through bash, and the tree is reported.

    A checkout that lost a mode -- an archive expanded without them, a
    copy by something that does not keep them -- should not silently
    become a pipeline that cannot render.  It should run and say so.
    """

    def test_it_runs_and_the_warning_names_the_repair(self):
        os.chmod(os.path.join(self.tooling, "embed_captions.sh"), 0o644)
        fields, err = self.succeeds()
        self.assertEqual(self.invocations(), self.expected(STAGES))
        self.assertEqual(fields["PIPELINE_STAGE_CAPTIONS"], "pass")
        self.assertIn("chmod +x", err)


class TestThisSuiteWritesNothingIntoTheRepository(ExecutionFixture):
    """The regression that made the sandbox necessary.

    The plan harness used to write its trimmed copy of the sequencer into
    the REAL playthrough/tooling/ as `.blitzy_adhoc_test_plan_*.sh`.
    Inside that tree the repository's ignores do not apply -- the
    terminal `!/playthrough/**` negation re-includes everything -- and
    the leading dot put the name outside the `blitzy_adhoc_test_*` glob
    the checkpoint's hygiene gate refuses, so an interrupted run left a
    committable machine file that no gate would have caught.  This holds
    the whole suite to leaving the folder exactly as it found it.
    """

    def tooling_listing(self):
        return sorted(os.listdir(TOOLING))

    def test_driving_a_plan_leaves_the_real_folder_untouched(self):
        before = self.tooling_listing()
        name = "test_the_default_plan_is_every_stage_in_order"
        probe = TestTheDefaultPlanReachesTheCheckpoint(name)
        probe.setUp()
        try:
            self.assertEqual(probe.plan(), list(STAGES))
        finally:
            probe.doCleanups()
        self.assertEqual(self.tooling_listing(), before)

    def test_running_the_pipeline_leaves_the_real_folder_untouched(self):
        before = self.tooling_listing()
        self.succeeds()
        self.assertEqual(self.tooling_listing(), before)

    def test_the_trimmed_copy_lives_in_the_sandbox_under_a_plain_name(self):
        """Plain, because it has no hygiene glob to satisfy where it is.

        The name is asserted anyway: a copy called `.something` would be
        one that a future move back into the repository would smuggle
        past the gate again.
        """
        self.assertTrue(self.trimmed.startswith(self.root))
        self.assertEqual(os.path.basename(self.trimmed), PROBE_NAME)
        self.assertFalse(os.path.basename(self.trimmed).startswith("."))
        self.assertTrue(os.path.isfile(self.trimmed))


class TestTheSequencerWritesNothingIntoTheTree(ExecutionFixture):
    """It runs stages; it produces no artifact of its own."""

    def tree(self):
        """Every path under the sandbox's playthrough/, relative."""
        found = set()
        root = os.path.join(self.checkout, "playthrough")
        for directory, _, names in os.walk(root):
            for name in names:
                found.add(os.path.relpath(
                    os.path.join(directory, name), root))
        return found

    def test_a_whole_run_adds_no_file_to_the_artifact_tree(self):
        before = self.tree()
        self.succeeds()
        self.assertEqual(self.tree(), before)

    def test_its_own_logs_and_locks_stay_outside_the_checkout(self):
        before = self.tree()
        self.succeeds()
        # AGAINST THE SNAPSHOT, not against the extension alone: the
        # dependency declaration this fixture places in the sandbox is
        # itself called requirements.lock, and it is not a lock the
        # sequencer took.  What must hold is that the run ADDED no lock
        # and no log to the tree it judges.
        appeared = self.tree() - before
        self.assertEqual(
            sorted(name for name in appeared
                   if name.endswith((".lock", ".log"))), [])
        self.assertTrue(
            os.path.isdir(os.path.join(self.runtime, "lock")),
            msg="the lock belongs under the runtime root env.sh verifies")


class TestTheLockIsScopedToTheCheckout(unittest.TestCase):
    """A lock that serialises unrelated trees is a lock in the way."""

    def lock_name(self, cwd):
        """The name the sequencer would take, asked of env.sh directly."""
        script = ('set -eu\n'
                  '. "%s/env.sh"\n'
                  'playthrough_checkout_lock_name pipeline\n') % TOOLING
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM", "lock name")
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", script],
            cwd=cwd, capture_output=True, timeout=TIMEOUT, env=env)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stderr.decode("utf-8", "replace"))
        return result.stdout.decode("utf-8", "replace").strip()

    def test_the_name_carries_a_digest_of_the_repository_root(self):
        self.assertRegex(self.lock_name(REPO_ROOT),
                         r"^pipeline-[0-9a-f]{8}$")

    def test_the_source_derives_the_name_rather_than_spelling_it(self):
        """Comments stripped first: the constant's own comment NAMES the
        helper, so a source that had stopped calling it would still
        mention it and this assertion would pass on the explanation."""
        code = "\n".join(line for line in sequencer_source().split("\n")
                         if not line.lstrip().startswith("#"))
        # assertTrue on a containment test rather than assertIn: the
        # subject here is the whole script, and assertIn would print all
        # of it into the failure report.
        self.assertTrue(
            "playthrough_checkout_lock_name" in code,
            msg="the sequencer no longer derives its lock name from the "
                "checkout, so the lock names the clone index again")
        self.assertIsNone(
            re.search(r'PIPELINE_LOCK_NAME="pipeline"', code),
            msg="the lock name is spelled as a constant again, so it "
                "names the clone index rather than the checkout")

    def test_the_busy_diagnosis_names_the_lock_not_the_root(self):
        """Every message goes through env.sh's redaction, which rewrites
        the repository root to '.' -- so a diagnosis that named the path
        would read "over the checkout at .", which locates nothing.

        COMMENTS ARE STRIPPED FIRST.  The comment above that diagnosis
        explains the trap by quoting the wrong form, and a test that read
        it as code would fail on the explanation of the thing it is
        checking for.
        """
        source = sequencer_source()
        busy = source.split("playthrough_acquire_lock \\")[-1]
        busy = busy.split("LOCK_HELD=1")[0]
        code = "\n".join(line for line in busy.split("\n")
                         if not line.lstrip().startswith("#"))
        self.assertIn("${PIPELINE_LOCK_NAME}", code)
        self.assertNotIn("${REPO_ROOT}", code)
        self.assertNotIn("${PLAYTHROUGH_REPO_ROOT}", code)


class TestTheLockRefusesABusyCheckout(unittest.TestCase):
    """Measured against a real held lock rather than asserted."""

    def setUp(self):
        for tool in ("flock", "sleep"):
            if not shutil.which(tool):
                self.skipTest("%s is needed to hold a lock" % tool)

    def held_lock_path(self):
        script = ('set -eu\n'
                  '. "%s/env.sh"\n'
                  'name="$(playthrough_checkout_lock_name pipeline)"\n'
                  'printf "%%s/%%s.lock\\n" "${PLAYTHROUGH_LOCK_DIR}" '
                  '"${name}"\n') % TOOLING
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM", "lock path")
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", script],
            cwd=REPO_ROOT, capture_output=True, timeout=TIMEOUT, env=env)
        path = result.stdout.decode("utf-8", "replace").strip()
        self.assertTrue(
            path, msg=result.stderr.decode("utf-8", "replace"))
        return path

    def test_a_busy_checkout_is_refused_with_its_own_status(self):
        path = self.held_lock_path()
        holder = subprocess.Popen(
            [shutil.which("flock"), path, shutil.which("sleep"), "60"])

        def release():
            holder.kill()
            holder.wait(timeout=30)

        self.addCleanup(release)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [shutil.which("flock"), "--nonblock", path,
                 shutil.which("true")], capture_output=True, timeout=60)
            if probe.returncode != 0:
                break
            time.sleep(0.1)
        else:
            self.fail("the lock holder never acquired %s" % path)
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM", "busy lock")
        env["PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT"] = "2"
        # --only timeline is the cheapest plan there is, and it never
        # reaches a stage: the lock is taken before the first one runs.
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", SEQUENCER,
             "--only", "timeline"],
            cwd=REPO_ROOT, capture_output=True, timeout=TIMEOUT, env=env)
        self.assertEqual(result.returncode, EX_BUSY)
        message = result.stderr.decode("utf-8", "replace")
        self.assertIn("holds the", message)
        self.assertIn("derived", message)
        # THE NAME THE SEQUENCER ACTUALLY TOOK, not the one env.sh would
        # derive if asked.  This is what makes the test bite: the lock
        # being held here is the digest-suffixed one, so a sequencer that
        # had gone back to a bare `pipeline` would not contend for it at
        # all -- it would sail past and never reach this assertion.
        name = os.path.basename(path)[:-len(".lock")]
        self.assertRegex(name, r"^pipeline-[0-9a-f]{8}$")
        self.assertIn(name, message)

    def test_a_hostile_timeout_is_refused_before_any_arithmetic(self):
        """bash resolves a command substitution inside $(( )), so an
        unchecked value there is an instruction rather than a number."""
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM", "timeout")
        for value in ("2; rm -rf /", "$(id)", "abc", "-1", "86401"):
            with self.subTest(value=value):
                env["PLAYTHROUGH_PIPELINE_LOCK_TIMEOUT"] = value
                result = subprocess.run(
                    ["/bin/bash", "--noprofile", "--norc", SEQUENCER,
                     "--only", "timeline"],
                    cwd=REPO_ROOT, capture_output=True, timeout=TIMEOUT,
                    env=env)
                self.assertEqual(result.returncode, EX_USAGE)


class TestTheLifecyclePreflight(PlanFixture):
    """A checkpoint that cannot be taken is refused before stage 1.

    `final` anchors to the `creation` checkpoint OF THE SURVIVOR THE
    SESSION IS ABOUT and needs the record to have grown since it.  Both
    are settled facts about the history before anything is rendered --
    and this very repository is in a state where they do not hold, so the
    default plan was GUARANTEED to spend the timeline, the transitions,
    the encode, the transcripts, the caption mux and the whole functional
    gate before being refused at stage 7.

    The probe is substituted here rather than driven for real: a test
    whose verdict depended on which survivor the repository last recorded
    would pass today and fail after the next checkpoint.  One test below
    does drive the real one, and asserts only that its answer parses.
    """

    ELIGIBLE = (
        'probe_lifecycle() { LIFECYCLE_ELIGIBLE=yes;'
        ' LIFECYCLE_REASON=""; LIFECYCLE_ANCHOR=abcdef1234; return 0; }\n'
    )
    INELIGIBLE = (
        'probe_lifecycle() { LIFECYCLE_ELIGIBLE=no;'
        ' LIFECYCLE_REASON=no-creation-for-this-survivor;'
        ' LIFECYCLE_ANCHOR=""; return 0; }\n'
    )
    UNREADABLE = 'probe_lifecycle() { return 1; }\n'

    def preflight(self, stub, *arguments):
        return self.shell(
            stub +
            'parse_arguments "$@"\n'
            'resolve_plan\n'
            'assert_lifecycle_eligible\n'
            'printf "REACHED=yes\\n"\n',
            *arguments)

    def test_an_ineligible_checkpoint_stops_the_run_before_stage_one(self):
        status, out, err = self.preflight(self.INELIGIBLE)
        self.assertEqual(status, 4)
        self.assertNotIn("REACHED=yes", out)
        self.assertEqual(
            self.fields_of(out)["PIPELINE_LIFECYCLE"],
            "no-creation-for-this-survivor")
        self.assertIn("CANNOT be taken", err)

    def test_the_refusal_names_the_flag_that_runs_the_render_half(self):
        _, _, err = self.preflight(self.INELIGIBLE)
        self.assertIn("--no-commit", err)
        self.assertIn("no stage is run", err)

    def test_an_eligible_checkpoint_changes_nothing(self):
        status, out, _ = self.preflight(self.ELIGIBLE)
        self.assertEqual(status, 0)
        self.assertIn("REACHED=yes", out)
        self.assertEqual(self.fields_of(out)["PIPELINE_LIFECYCLE"],
                         "eligible")

    def test_an_unreadable_answer_is_reported_and_the_run_proceeds(self):
        """Silence is not evidence of ineligibility.

        A probe that could not run says nothing either way, and the
        checkpoint stage remains the authority -- so turning it into a
        refusal would make this file a second place a lifecycle decision
        is taken.
        """
        status, out, err = self.preflight(self.UNREADABLE)
        self.assertEqual(status, 0)
        self.assertIn("REACHED=yes", out)
        self.assertEqual(self.fields_of(out)["PIPELINE_LIFECYCLE"],
                         "unread")
        self.assertIn("WARNING", err)

    def test_no_commit_asks_the_question_at_all(self):
        """With no checkpoint planned there is nothing to be eligible for."""
        status, out, _ = self.preflight(self.INELIGIBLE, "--no-commit")
        self.assertEqual(status, 0)
        self.assertIn("REACHED=yes", out)
        self.assertNotIn("PIPELINE_LIFECYCLE", out)

    def test_the_real_probe_parses_the_committers_own_answer(self):
        """Driven for real, asserting only that the contract holds.

        Which answer comes back depends on the repository; that it is one
        of the two words, and that a reason accompanies a refusal, is the
        contract between the two files.
        """
        status, out, _ = self.shell(
            'PLAN=(commit)\n'
            'if probe_lifecycle; then\n'
            '  printf "ANSWER=%s\\n" "${LIFECYCLE_ELIGIBLE}"\n'
            '  printf "REASON=%s\\n" "${LIFECYCLE_REASON}"\n'
            'else\n'
            '  printf "ANSWER=unread\\n"\n'
            'fi\n')
        self.assertEqual(status, 0)
        found = self.fields_of(out)
        self.assertIn(found["ANSWER"], ("yes", "no", "unread"))
        if found["ANSWER"] == "no":
            self.assertNotEqual(found["REASON"], "")

    def test_it_asks_rather_than_re_deriving_the_rule(self):
        """The lifecycle rule stays in the module that owns it."""
        code = "\n".join(line for line in sequencer_source().split("\n")
                         if not line.lstrip().startswith("#"))
        self.assertIn("LIFECYCLE_PROBE_SUBCOMMAND", code)
        for borrowed in ("--grep", "rev-list",
                         "Playthrough-Checkpoint", "lastworld"):
            with self.subTest(borrowed=borrowed):
                self.assertNotIn(borrowed, code)


class TestTheCapacityModel(PlanFixture):
    """Room is proved before the artifacts are written, not after.

    Every artifact is full resolution and nothing is ever dropped to make
    a generation fit, so running out of space part way through does not
    produce a smaller film -- it produces a torn one.  The preflight
    proved scripts, interpreter and lock and nothing else.

    df and du are substituted: a test that asked the real disk would
    assert whatever this host happens to have free.
    """

    # One kibibyte per measured path, so the arithmetic in each
    # assertion is exact rather than approximate.
    TREE = 'tree_kib() { printf 1; }\n'

    def capacity(self, free_kib, when="plan", *arguments):
        return self.shell(
            self.TREE +
            'disk_free_kib() { printf %s; }\n' % free_kib +
            'parse_arguments "$@"\n'
            'resolve_plan\n'
            'MEASURED_READY=1\n'
            'if capacity_ok "%s"; then printf "ROOM=yes\\n"; '
            'else printf "ROOM=no\\n"; fi\n' % when,
            *arguments)

    def test_a_full_disk_is_refused_with_every_figure_named(self):
        status, out, err = self.capacity(1)
        self.assertEqual(status, 0)
        self.assertIn("ROOM=no", out)
        self.assertIn("NOTHING IS DROPPED", err)
        self.assertIn("1024 byte(s) free", err)
        self.assertIn("more byte(s)", err)

    def test_room_is_reported_with_its_four_terms(self):
        status, out, err = self.capacity(1099511627776)
        self.assertEqual(status, 0)
        self.assertIn("ROOM=yes", out)
        for term in ("rewrite", "staging", "history", "margin"):
            with self.subTest(term=term):
                self.assertIn(term, err)

    def test_the_reserve_is_the_sum_of_what_this_plan_will_write(self):
        """Measured per planned stage, not as one fixed number.

        Seven output paths across the five producing stages, one more for
        the staging copy the caption mux needs, one more for the objects
        the checkpoint writes, and the margin.  A plan that only writes
        the cue file reserves two of those paths and neither of the
        extras.
        """
        _, out, _ = self.capacity(1099511627776)
        whole = self.fields_of(out)["PIPELINE_CAPACITY"].split(":")[1]
        _, out, _ = self.capacity(1099511627776, "plan", "--only", "srt")
        alone = self.fields_of(out)["PIPELINE_CAPACITY"].split(":")[1]
        kib = 1024
        margin = 268435456
        self.assertEqual(int(alone), 2 * kib + margin)
        self.assertEqual(int(whole), (7 + 1 + 1) * kib + margin)

    def test_the_checkpoint_check_leaves_the_producing_terms_out(self):
        """By then the films exist; only the objects are still ahead.

        And it reports under a key of its own, so a caller reading this
        channel into a dictionary does not have the second measurement
        silently overwrite the first.
        """
        _, out, _ = self.capacity(1099511627776, "checkpoint")
        found = self.fields_of(out)
        self.assertNotIn("PIPELINE_CAPACITY", found)
        reserve = found["PIPELINE_CAPACITY_CHECKPOINT"].split(":")[1]
        self.assertEqual(int(reserve), 1024 + 268435456)

    def test_an_unmeasurable_disk_does_not_stop_the_run(self):
        """An unreadable df is a fact about the host, not a full disk."""
        status, out, err = self.shell(
            'disk_free_kib() { return 1; }\n'
            'PLAN=(timeline)\n'
            'MEASURED_READY=1\n'
            'if capacity_ok plan; then printf "ROOM=yes\\n"; fi\n')
        self.assertEqual(status, 0)
        self.assertIn("ROOM=yes", out)
        self.assertEqual(self.fields_of(out)["PIPELINE_CAPACITY"],
                         "unmeasured")
        self.assertIn("WARNING", err)

    def test_without_the_tools_capacity_is_reported_unmeasured(self):
        status, out, _ = self.shell(
            'PLAN=(timeline)\n'
            'MEASURED_READY=0\n'
            'if capacity_ok plan; then printf "ROOM=yes\\n"; fi\n')
        self.assertEqual(status, 0)
        self.assertIn("ROOM=yes", out)
        self.assertEqual(self.fields_of(out)["PIPELINE_CAPACITY"],
                         "unmeasured")

    def test_the_refusal_carries_its_own_exit_status(self):
        status, _, _ = self.shell(
            'capacity_ok() { return 1; }\n'
            'assert_capacity plan\n'
            'printf "REACHED=yes\\n"\n')
        self.assertEqual(status, 5)

    def test_the_second_check_is_taken_before_the_checkpoint_runs(self):
        """Inside the loop, ahead of run_stage, for the commit stage.

        Asserted against the source order because driving it would mean
        really running the producing stages.
        """
        source = sequencer_source()
        # The LAST occurrence: report_unattempted walks the plan too,
        # and main's loop is the one this order is about.
        body = source.split("for index in \"${!PLAN[@]}\"; do")[-1]
        checkpoint = body.index('capacity_ok "checkpoint"')
        self.assertLess(checkpoint, body.index('run_stage "${name}"'))
        self.assertIn("${COMMIT_STAGE}", body[:checkpoint])


class TestTheRunReceipt(PlanFixture):
    """A stage nothing has invalidated is not run a second time.

    Every invocation used to run every planned stage, so a run stopped by
    a late failure re-timed every capture, re-composed every transition
    and re-encoded the whole film over inputs that had not changed by a
    byte.  The receipt is content-addressed: it binds the record, the
    ledgers, the counts, git's own view of the inputs, the pinned closure,
    the interpreter and every stage script, and it binds what the stage
    produced.  No modification time and no bare size appears in it,
    because both can move without the content moving and stay still while
    it does.
    """

    def setUp(self):
        super(TestTheRunReceipt, self).setUp()
        # A runtime root of this test's own, so a test can never write
        # over a real run's receipt -- BENEATH THE VERIFIED XDG ROOT,
        # because env.sh refuses a pipeline runtime root that is not:
        # only that root has been proved to be an owner-only 0700
        # directory, and a tree under an unverified ancestor can be
        # redirected between one command and the next.
        self.runtime = _verified_runtime_root()
        self.addCleanup(shutil.rmtree, self.runtime, True)
        # THE STAGE'S OUTPUT HAS TO EXIST TO BE HASHED.  The receipt binds
        # what a stage PRODUCED as well as what it consumed, so
        # outputs_digest reads playthrough/timeline.json -- and a sandbox
        # checkout has no artifacts unless a test puts them there.  The
        # content is immaterial to every assertion here; that it can be
        # read, and that its digest changes when it does, is the whole
        # subject.
        self.timeline = self.write(
            os.path.join(self.checkout, "playthrough", "timeline.json"),
            '[{"frame": 1, "duration": 0.25}]\n')

    def receipt(self, snippet, **environment):
        environment.setdefault("PLAYTHROUGH_RUNTIME_DIR", self.runtime)
        return self.shell(
            'PLAN=(timeline)\n'
            'resolve_measurement_tools || true\n'
            'open_receipt || true\n' + snippet,
            **environment)

    def test_a_recorded_stage_is_found_fresh_and_then_is_not(self):
        """The whole mechanism, in one run: record, match, invalidate."""
        status, out, _ = self.receipt(
            'record_receipt timeline\n'
            'if stage_is_fresh timeline; then printf "FIRST=fresh\\n"; '
            'else printf "FIRST=stale\\n"; fi\n'
            'REBUILD=1\n'
            'if stage_is_fresh timeline; then printf "REBUILD=fresh\\n"; '
            'else printf "REBUILD=stale\\n"; fi\n'
            'REBUILD=0\n'
            'ONLY_STAGE=timeline\n'
            'if stage_is_fresh timeline; then printf "ONLY=fresh\\n"; '
            'else printf "ONLY=stale\\n"; fi\n'
            'ONLY_STAGE=""\n'
            'FRESH_PREFIX=0\n'
            'if stage_is_fresh timeline; then printf "AFTER=fresh\\n"; '
            'else printf "AFTER=stale\\n"; fi\n'
            'FRESH_PREFIX=1\n'
            'RECEIPT_FINGERPRINT=changed\n'
            'if stage_is_fresh timeline; then printf "INPUTS=fresh\\n"; '
            'else printf "INPUTS=stale\\n"; fi\n')
        self.assertEqual(status, 0)
        found = self.fields_of(out)
        self.assertEqual(found["FIRST"], "fresh")
        self.assertEqual(found["REBUILD"], "stale")
        self.assertEqual(found["ONLY"], "stale")
        self.assertEqual(found["AFTER"], "stale")
        self.assertEqual(found["INPUTS"], "stale")

    def test_an_output_that_no_longer_hashes_true_is_not_fresh(self):
        """Matching inputs alone would skip an encode with no film."""
        status, out, _ = self.receipt(
            'record_receipt timeline\n'
            'printf "%s\\n" "${RECEIPT_HEADER} ${RECEIPT_FORMAT}" '
            '>"${RECEIPT_FILE}"\n'
            'printf "timeline\\t%s\\tnot-the-digest\\n" '
            '"${RECEIPT_FINGERPRINT}" >>"${RECEIPT_FILE}"\n'
            'if stage_is_fresh timeline; then printf "STATE=fresh\\n"; '
            'else printf "STATE=stale\\n"; fi\n')
        self.assertEqual(status, 0)
        self.assertEqual(self.fields_of(out)["STATE"], "stale")

    def test_a_missing_output_is_not_fresh(self):
        """A stage whose output has gone has not been done."""
        status, out, _ = self.receipt(
            'if outputs_digest timeline >/dev/null; then\n'
            '  printf "REAL=measured\\n"\n'
            'fi\n'
            'PLAYTHROUGH_TIMELINE="${PLAYTHROUGH_RUNTIME_DIR}/absent"\n'
            'if outputs_digest timeline >/dev/null; then\n'
            '  printf "GONE=measured\\n"\n'
            'else\n'
            '  printf "GONE=refused\\n"\n'
            'fi\n')
        self.assertEqual(status, 0)
        found = self.fields_of(out)
        self.assertEqual(found["REAL"], "measured")
        self.assertEqual(found["GONE"], "refused")

    def test_the_three_history_stages_are_never_fresh(self):
        """Each asks about a moment rather than producing a thing."""
        status, out, _ = self.receipt(
            'for stage in verify commit attest; do\n'
            '  if stage_outputs "${stage}" >/dev/null; then\n'
            '    printf "OUTPUTS_%s=yes\\n" "${stage}"\n'
            '  else\n'
            '    printf "OUTPUTS_%s=none\\n" "${stage}"\n'
            '  fi\n'
            '  if stage_is_fresh "${stage}"; then\n'
            '    printf "FRESH_%s=yes\\n" "${stage}"\n'
            '  else\n'
            '    printf "FRESH_%s=no\\n" "${stage}"\n'
            '  fi\n'
            'done\n')
        self.assertEqual(status, 0)
        found = self.fields_of(out)
        for stage in ("verify", "commit", "attest"):
            with self.subTest(stage=stage):
                self.assertEqual(found["OUTPUTS_%s" % stage], "none")
                self.assertEqual(found["FRESH_%s" % stage], "no")

    def test_the_receipt_lives_outside_the_working_tree(self):
        """It is not an artifact, so it must not be committable."""
        status, out, _ = self.receipt(
            'printf "FILE=%s\\n" "${RECEIPT_FILE}"\n')
        self.assertEqual(status, 0)
        path = self.fields_of(out)["FILE"]
        self.assertTrue(path.startswith(self.runtime), msg=path)
        self.assertFalse(path.startswith(REPO_ROOT + os.sep), msg=path)
        self.assertRegex(os.path.basename(path),
                         r"^receipt-[0-9a-f]{8}$")

    def test_the_fingerprint_is_stable_and_binds_the_interpreter(self):
        status, out, _ = self.receipt(
            'printf "ONE=%s\\n" "$(input_fingerprint)"\n'
            'printf "TWO=%s\\n" "$(input_fingerprint)"\n'
            'PLAYTHROUGH_PYTHON=/usr/bin/env\n'
            'printf "OTHER=%s\\n" "$(input_fingerprint)"\n')
        self.assertEqual(status, 0)
        found = self.fields_of(out)
        self.assertRegex(found["ONE"], r"^[0-9a-f]{64}$")
        self.assertEqual(found["ONE"], found["TWO"])
        self.assertNotEqual(found["ONE"], found["OTHER"])

    def test_the_fingerprint_binds_every_input_the_review_named(self):
        """Content-addressed, and each component is named in the text.

        The digests themselves are asserted by the test above; this one
        asserts that nothing was left out, because a fingerprint missing
        one of these would match across a change it should not.
        """
        code = "\n".join(line for line in sequencer_source().split("\n")
                         if not line.lstrip().startswith("#"))
        block = code.split("input_fingerprint() {")[1]
        block = block.split("\n}")[0]
        for bound in ("RECEIPT_FORMAT", "rev-parse HEAD",
                      "input_git_state", "capture_count",
                      "PLAYTHROUGH_MANIFEST", "PLAYTHROUGH_AMENDMENTS",
                      "PLAYTHROUGH_FRAME_DIGESTS",
                      "PLAYTHROUGH_REQUIREMENTS", "PLAYTHROUGH_PYTHON",
                      "STAGE_ORDER"):
            with self.subTest(bound=bound):
                self.assertIn(bound, block)

    def test_no_modification_time_or_bare_size_is_trusted(self):
        """Both can move without the content, and stay still with it."""
        code = "\n".join(line for line in sequencer_source().split("\n")
                         if not line.lstrip().startswith("#"))
        for forbidden in ("-newer", "-nt", "-ot", "%Y", "stat -c",
                          "getmtime", "st_mtime"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_the_receipt_is_replaced_atomically(self):
        """A half-written line must never be read as a digest."""
        code = "\n".join(line for line in sequencer_source().split("\n")
                         if not line.lstrip().startswith("#"))
        block = code.split("record_receipt() {")[1].split("\n}")[0]
        self.assertIn('${RECEIPT_FILE}.new', block)
        self.assertIn('"${MV}" -f --', block)


class TestThisSuiteLeavesNothingBehind(PlanFixture):
    """The trimmed copy is committable, so a leaked one matters.

    It has to sit beside the real script, which puts it inside the
    working tree, where the terminal `!/playthrough/**` negation
    re-includes everything -- so a copy a killed run left behind is
    TRACKABLE and can be committed by accident.  One was observed left
    behind by a run whose outer timeout terminated the process group,
    which addCleanup cannot survive.
    """

    def remove_later(self, path):
        """Delete `path` when the test ends, link or not.

        lexists rather than exists, because a cleanup that ran after the
        symlink test's target had gone would find a dangling link, read
        it as absent and leave it in the working tree -- which is exactly
        the litter these two tests are about.  Observed, and fixed here.
        """
        def remove():
            if os.path.lexists(path):
                os.unlink(path)

        self.addCleanup(remove)

    def test_a_stale_copy_is_swept_and_a_fresh_one_is_not(self):
        stale = os.path.join(TOOLING, TRIMMED_PREFIX + "stale.sh")
        with open(stale, "w", encoding="utf-8") as handle:
            handle.write("# left behind by a killed run\n")
        self.remove_later(stale)
        old = time.time() - (STALE_COPY_SECONDS + 60)
        os.utime(stale, (old, old))
        PlanFixture.sweep_stale_copies()
        self.assertFalse(os.path.exists(stale),
                         msg="a copy older than the window survived")
        # And this test's own copy, which is minutes old at most, is
        # untouched -- a sweep that took a concurrent run's file would be
        # worse than the litter it removes.
        self.assertTrue(os.path.exists(self.trimmed))

    def test_the_sweep_refuses_a_symlink(self):
        """The same discipline the verifier's scratch sweep keeps."""
        target = os.path.join(TOOLING, TRIMMED_PREFIX + "target.txt")
        link = os.path.join(TOOLING, TRIMMED_PREFIX + "link.sh")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("not this suite's to delete\n")
        os.symlink(target, link)
        self.remove_later(link)
        self.remove_later(target)
        old = time.time() - (STALE_COPY_SECONDS + 60)
        os.utime(link, (old, old), follow_symlinks=False)
        PlanFixture.sweep_stale_copies()
        self.assertTrue(os.path.islink(link),
                        msg="the sweep followed or removed a symlink")
        self.assertTrue(os.path.exists(target))


class TestItHoldsNoStagesLogic(unittest.TestCase):
    """The sequencer sequences.  Every number below belongs elsewhere.

    A constant that appears here as well as in the module that owns it is
    two sources of truth, and the one that drifts is always the copy.
    """

    # Each entry is a value the pipeline genuinely depends on, owned by
    # exactly one module that is not this one.
    STAGE_OWNED = (
        "0.25", "10.0", "mov_text", "libx264", "yuv420p", "1920x1080",
        "crf", "faststart", "fps_mode", "concat", "language=eng",
        "tesseract", "FONT_WIDTH", "288x1072", "24_HOUR",
        "ASCIITiles", "xdotool", "import -window",
    )

    def test_no_stage_owned_constant_appears_in_the_sequencer(self):
        source = sequencer_source()
        for value in self.STAGE_OWNED:
            with self.subTest(value=value):
                self.assertNotIn(
                    value, source,
                    msg=("%r belongs to the stage that owns it; a copy "
                         "here is a second source of truth" % value))

    def test_every_stage_maps_to_exactly_one_script(self):
        source = sequencer_source()
        block = source.split("declare -rA STAGE_SCRIPT=(")[1]
        block = block.split(")")[0]
        mapped = dict(re.findall(r"\[(\w+)\]=\"([^\"]+)\"", block))
        self.assertEqual(sorted(mapped), sorted(STAGES))

    def test_the_two_gate_stages_share_one_script(self):
        source = sequencer_source()
        block = source.split("declare -rA STAGE_SCRIPT=(")[1]
        block = block.split(")")[0]
        mapped = dict(re.findall(r"\[(\w+)\]=\"([^\"]+)\"", block))
        self.assertEqual(mapped["verify"], mapped["attest"])
        self.assertEqual(mapped["verify"], "verify_artifacts.sh")

    def test_it_neither_launches_the_game_nor_captures(self):
        source = sequencer_source()
        for forbidden in ("cataclysm-tiles", "session.py", "capture.sh",
                          "launch_game.sh"):
            with self.subTest(forbidden=forbidden):
                # Named in prose is fine; named in a stage map is not.
                self.assertNotIn('="%s"' % forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
