#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/run_pipeline.sh.

The sequencer decides three things and does nothing else: WHICH stages
run, in WHAT order, and with WHAT arguments.  Everything that could go
wrong with it is therefore a question about a plan, and a plan can be
inspected without rendering a film or touching a repository -- which is
what this suite does.

    python3 playthrough/tooling/test_run_pipeline.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED

* THE GATE RUNS TWICE, AND THE COMMIT IS REACHABLE.  This is the
  regression that matters.  The gate was sequenced once, ahead of the
  commit, and twelve of its checks ask questions only a commit can make
  true -- is the save tracked, is every class committed, is the tree
  clean.  Measured on a genuine post-session tree, the single gate
  reported nine failures out of a hundred and eight, the sequence stopped
  there, and the run ended with the commit stage UNATTEMPTED: the default
  plan could not reach the checkpoint at all.  So `verify` now runs
  --phase pre-commit ahead of the commit and `attest` runs
  --phase post-commit after it, and this suite pins both the order and
  the two phase arguments.
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

HOW A PLAN IS INSPECTED WITHOUT RUNNING A STAGE
run_pipeline.sh ends with `main "$@"`, so sourcing it would run the whole
pipeline.  These tests source a copy with that one line removed, then call
parse_arguments and resolve_plan directly and read PLAN, SKIPPED and
STAGE_COMMAND back.  Nothing is executed, nothing is written, and the code
under test is the real file rather than a restatement of it.

Standard library only.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(TOOLING))
SEQUENCER = os.path.join(TOOLING, "run_pipeline.sh")

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

# The line that runs the pipeline.  Removed from the copy these tests
# source, and asserted to exist so a rename cannot leave the harness
# silently sourcing the whole file.
MAIN_INVOCATION = 'main "$@" || _rp_status=$?'

TIMEOUT = 300


def sequencer_source():
    with open(SEQUENCER, "r", encoding="utf-8") as handle:
        return handle.read()


class PlanFixture(unittest.TestCase):
    """Drives plan resolution in the real script, running no stage."""

    @classmethod
    def setUpClass(cls):
        source = sequencer_source()
        if MAIN_INVOCATION not in source:
            raise AssertionError(
                "run_pipeline.sh no longer ends with %r, so this "
                "harness would source a file that runs the whole "
                "pipeline" % MAIN_INVOCATION)

    def setUp(self):
        # The script resolves its own directory from BASH_SOURCE and
        # refuses to run outside a checkout, so the trimmed copy has to
        # sit beside the real one.  A unique name keeps concurrent runs
        # of this suite apart, and it is removed however a test ends.
        handle, self.trimmed = tempfile.mkstemp(
            prefix=".blitzy_adhoc_test_plan_", suffix=".sh", dir=TOOLING)
        os.close(handle)
        self.addCleanup(self.remove_trimmed)
        source = sequencer_source()
        head = source.split(MAIN_INVOCATION)[0]
        with open(self.trimmed, "w", encoding="utf-8") as out:
            out.write(head)

    def remove_trimmed(self):
        if os.path.exists(self.trimmed):
            os.unlink(self.trimmed)

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
        env = dict(os.environ)
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                       "plan resolution test; no stage is run")
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
        fields = {}
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                fields[key] = value
        fields["STDERR"] = result.stderr.decode("utf-8", "replace")
        return result.returncode, fields

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
        """
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", SEQUENCER, "--help"],
            cwd=REPO_ROOT, capture_output=True, timeout=TIMEOUT)
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
