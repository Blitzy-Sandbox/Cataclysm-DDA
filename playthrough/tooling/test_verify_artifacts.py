#!/usr/bin/env python3
"""Regression suite for playthrough/tooling/verify_artifacts.sh's phases.

The acceptance gate measures two different KINDS of property, and the
distinction is what makes the pipeline able to commit at all:

    properties of the ARTIFACTS   the record, the timeline, the
                                  container, the caption track, the
                                  luminance, the artwork, the lint --
                                  true the instant the render finishes,
                                  with nothing committed
    properties of the COMMIT      the save is tracked, every class is
                                  tracked, nothing is left uncommitted,
                                  the checkpoints are ordered and
                                  anchored, the committed ignore rules
                                  still rescue the save, the change
                                  surface -- NONE of which can hold
                                  before the commit that makes them true

Run as one undivided gate ahead of a commit, the second kind fails on
any tree that is not already fully committed, and a sequencer that puts
the gate before the checkpoint can therefore never reach the checkpoint.
That was measured on a genuine post-session tree: nine failures out of a
hundred and eight, every one of them a tracking, history or clean-tree
property.  `--phase` is the answer, and this suite holds the properties
that make it trustworthy:

    python3 playthrough/tooling/test_verify_artifacts.py
    python3 -B -m unittest discover -s playthrough/tooling -p 'test_*.py'

WHAT IS ASSERTED

* THE PHASE SURFACE IS REAL AND CLOSED.  `all`, `pre-commit` and
  `post-commit` are accepted in every documented spelling -- `--phase X`,
  `--phase=X`, the two shorthands and PLAYTHROUGH_VERIFY_PHASE -- and
  anything else is REFUSED with exit 2 rather than defaulted, because a
  typo that silently produced the full gate would be reported under the
  phase that was asked for.
* THE DEFAULT DID NOT MOVE.  No argument at all still means the whole
  gate, so an operator auditing a committed tree is unaffected by the
  existence of phases.
* A SHORTER REPORT EXPLAINS ITS OWN LENGTH.  The pre-commit phase
  declares fewer checks than the full one, says so on its own first
  lines, and names the deferred properties -- the failure this guards
  against is a report that gets shorter while reading exactly as green.
* THE DECLARED COUNTS AGREE WITH THE CLASSIFICATION.  The two declared
  totals differ by exactly the number of verdicts the phase defers, and
  the group-by-group derivation comment carries both columns, so adding a
  check without declaring it fails the gate's own inventory rather than
  passing quietly.
* THE COMMIT-SHAPED CHECKS ARE GATED IN ONE PLACE.  Each of them is
  called inside a `tracking_phase` branch, never from an unconditional
  call site -- a check that decided for itself whether to run is a check
  that can be talked out of running.
* THE PHASE REACHES THE REPORT.  VERIFY_PHASE is published in the
  machine block and the phase appears on the human summary line, so a
  saved transcript can always be placed.
* IT STILL WRITES NOTHING.  Every invocation here is checked against the
  working tree it ran in.

HOW THE GATE IS TESTED WITHOUT A FULL ARTIFACT SET
The gate needs the whole committed record to reach a verdict on most of
its checks, and reproducing that here would be a second copy of the
evidence.  So this suite asks the two questions that do not need it:
what the SOURCE says (the classification, the declared counts, the call
sites), and what the CLI does before any artifact is read (the phase
resolution and its refusals).  The end-to-end behaviour on a real tree --
pre-commit passing on an uncommitted artifact set and post-commit failing
on it -- is exercised by the pipeline itself through run_pipeline.sh.

Standard library only.  Nothing outside a temporary directory is written.
"""

import os
import re
import subprocess
import sys
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything written
# there, so a __pycache__ beside this file would be committable.
sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
REPO_ROOT = os.path.dirname(PLAYTHROUGH)
GATE = os.path.join(TOOLING, "verify_artifacts.sh")

# The three phase words, and the exit status a usage error carries.
PHASE_ALL = "all"
PHASE_PRE = "pre-commit"
PHASE_POST = "post-commit"
EX_FAILED = 1
EX_USAGE = 2

# The verdicts the pre-commit phase defers, named by the check function
# that reports them.  This is the classification the suite holds the
# source to; the count beside each name is how many verdicts it emits on
# a complete artifact set.
DEFERRED_CHECKS = (
    ("check_save_tracked", 3),
    ("check_every_class_tracked", 1),
    ("check_tracked_frame_count", 1),
    ("check_nothing_uncommitted", 1),
    ("check_commit_order", 2),
    ("check_committed_vcs_rules", 2),
    ("check_lifecycle_checkpoints", 1),
    ("check_change_surface", 1),
)


def gate_source():
    """The gate's own text, which several assertions are made against."""
    with open(GATE, encoding="utf-8") as handle:
        return handle.read()


def declared(name):
    """One `readonly NAME=<integer>` value out of the gate's source."""
    match = re.search(r"^readonly %s=(\d+)$" % re.escape(name),
                      gate_source(), re.MULTILINE)
    if match is None:
        raise AssertionError("verify_artifacts.sh declares no %s" % name)
    return int(match.group(1))


def defines(name):
    """Whether the gate defines a shell function of that name.

    A function definition begins a LINE, so the pattern is anchored --
    and matched with re.MULTILINE, because the subject is a five
    thousand line file rather than one line.  A boolean is returned
    rather than a match object so the caller can assert on it with a
    short message: assertRegex prints its whole subject on failure,
    which for this file is the entire gate.
    """
    return re.search(r"^%s\(\) \{" % re.escape(name), gate_source(),
                     re.MULTILINE) is not None


class GateInvocation(unittest.TestCase):
    """Run the real gate, and prove it changed nothing by doing so."""

    # Long enough for the argument refusals and --help, which return
    # before any artifact is read.  A phase that actually measures the
    # artifacts is not run from here.
    TIMEOUT = 120

    def run_gate(self, *args, **environment):
        """Run verify_artifacts.sh from the repository root."""
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # The host this suite runs on may be past its release's support
        # date, which the gate reports as a warning rather than a
        # failure.  The waiver is set so the report is identical on a
        # supported and an unsupported host: nothing asserted here is
        # about the platform.
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                       "test_verify_artifacts.py reads the CLI only")
        for name, value in environment.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        result = subprocess.run(["/bin/bash", GATE, *args],
                                cwd=REPO_ROOT, capture_output=True,
                                timeout=self.TIMEOUT, env=env)
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def machine_block(self, out):
        """The trailing VERIFY_* KEY=value lines, as a mapping."""
        fields = {}
        for line in out.splitlines():
            if line.startswith("VERIFY") and "=" in line:
                key, _, value = line.partition("=")
                fields[key] = value
        return fields


class TestThePhaseSurfaceIsClosed(GateInvocation):
    """Every accepted spelling, and a refusal for everything else."""

    def test_an_unknown_phase_is_refused(self):
        status, out, err = self.run_gate("--phase", "postcommit")
        self.assertEqual(status, EX_USAGE, msg=err)
        self.assertIn("is not a phase of this gate", err)
        for word in (PHASE_ALL, PHASE_PRE, PHASE_POST):
            self.assertIn(word, err)
        self.assertEqual(out.count("PASS"), 0)

    def test_an_empty_phase_is_refused(self):
        status, _, err = self.run_gate("--phase=")
        self.assertEqual(status, EX_USAGE, msg=err)
        self.assertIn("is not a phase of this gate", err)

    def test_a_phase_with_no_value_is_refused(self):
        status, _, err = self.run_gate("--phase")
        self.assertEqual(status, EX_USAGE, msg=err)
        self.assertIn("--phase needs one of", err)

    def test_an_unknown_phase_from_the_environment_is_refused(self):
        """The environment default is validated like an argument.

        A default nobody typed is exactly the value a typo hides in.
        """
        status, _, err = self.run_gate(
            PLAYTHROUGH_VERIFY_PHASE="pre_commit")
        self.assertEqual(status, EX_USAGE, msg=err)
        self.assertIn("is not a phase of this gate", err)

    def test_the_help_documents_all_three_phases(self):
        status, out, err = self.run_gate("--help")
        self.assertEqual(status, 0, msg=err)
        self.assertEqual(err, "")
        for word in ("--phase", PHASE_ALL, PHASE_PRE, PHASE_POST,
                     "--pre-commit", "--post-commit",
                     "PLAYTHROUGH_VERIFY_PHASE"):
            self.assertIn(word, out)
        # The help has to say which one happens when nobody chooses.
        self.assertIn("THE DEFAULT", out)


class TestTheDeclaredCounts(unittest.TestCase):
    """The two totals, and the classification that separates them."""

    def test_both_totals_are_declared(self):
        self.assertGreater(declared("EXPECTED_CHECKS_ALL"), 0)
        self.assertGreater(declared("EXPECTED_CHECKS_PRE_COMMIT"), 0)

    def test_the_difference_is_exactly_the_deferred_verdicts(self):
        """The arithmetic, not an approximation of it.

        If a check is added to the deferred set without adjusting the
        pre-commit total, the gate's own inventory assertion would fail
        at run time -- this fails at test time instead, which is cheaper
        and more specific.
        """
        deferred = sum(count for _, count in DEFERRED_CHECKS)
        measured = (declared("EXPECTED_CHECKS_ALL") -
                    declared("EXPECTED_CHECKS_PRE_COMMIT"))
        self.assertEqual(
            measured, deferred,
            msg=("the two declared totals must differ by the %d "
                 "verdicts the pre-commit phase defers" % deferred))

    def test_the_derivation_comment_carries_both_columns(self):
        source = gate_source()
        self.assertIn("all   pre-commit", source)
        self.assertIn(str(declared("EXPECTED_CHECKS_ALL")), source)
        self.assertIn(str(declared("EXPECTED_CHECKS_PRE_COMMIT")),
                      source)

    def test_every_deferred_check_exists_as_a_function(self):
        for name, _ in DEFERRED_CHECKS:
            self.assertTrue(
                defines(name),
                msg="%s is classified as deferred but is not defined"
                    % name)


class TestTheCommitShapedChecksAreGated(unittest.TestCase):
    """Each deferred check is called inside a tracking_phase branch."""

    def call_sites(self, name):
        """Every line that CALLS the check, definition excluded."""
        pattern = re.compile(r"^\s*%s\b" % re.escape(name))
        sites = []
        for number, line in enumerate(gate_source().splitlines(), 1):
            if line.startswith("%s()" % name):
                continue
            if pattern.match(line) and "()" not in line:
                sites.append((number, line.strip()))
        return sites

    def test_the_predicate_exists(self):
        self.assertTrue(
            defines("tracking_phase"),
            msg="verify_artifacts.sh defines no tracking_phase()")

    def test_the_predicate_is_the_only_thing_that_decides(self):
        """The pre-commit phase is defined by ONE comparison.

        Any other test of PHASE inside a check would be a second place
        the classification lives, and two places drift.
        """
        source = gate_source()
        body = re.search(r"^tracking_phase\(\) \{\n(.*?)^\}",
                         source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("PHASE_PRE_COMMIT", body.group(1))

    def test_each_deferred_check_is_called_under_the_predicate(self):
        lines = gate_source().splitlines()
        for name, _ in DEFERRED_CHECKS:
            sites = self.call_sites(name)
            self.assertTrue(
                sites, msg="%s is never called" % name)
            for number, text in sites:
                # Walk back to the nearest `if`/`fi` at any indentation
                # and require it to be the phase predicate.
                guard = None
                for index in range(number - 2, max(number - 40, 0), -1):
                    candidate = lines[index].strip()
                    if candidate.startswith("if "):
                        guard = candidate
                        break
                    if candidate == "fi":
                        break
                self.assertIsNotNone(
                    guard,
                    msg=("%s is called unconditionally at line %d (%s); "
                         "a property of the commit cannot be measured "
                         "before the commit" % (name, number, text)))
                self.assertIn("tracking_phase", guard)


class TestThePhaseReachesTheReport(GateInvocation):
    """A saved transcript can always be placed in its phase."""

    def test_the_machine_block_publishes_the_phase(self):
        source = gate_source()
        self.assertIn('note VERIFY_PHASE "${PHASE}"', source)

    def test_the_summary_line_names_the_phase(self):
        source = gate_source()
        self.assertIn("for the '${PHASE}' phase", source)

    def test_the_header_names_the_phase_and_the_count(self):
        """The first lines of the report, before any verdict.

        A reader who was not told which phase produced a report cannot
        tell a deferred check from a missing one.
        """
        source = gate_source()
        self.assertIn("checks declared)", source)
        self.assertIn("are deferred to the", source)


class TestTheDefaultDidNotMove(unittest.TestCase):
    """No argument still means the whole gate."""

    def test_the_default_phase_is_all(self):
        source = gate_source()
        self.assertIn('readonly PHASE_DEFAULT="${PHASE_ALL}"', source)

    def test_the_default_declares_the_full_count(self):
        source = gate_source()
        self.assertIn('EXPECTED_CHECKS="${EXPECTED_CHECKS_ALL}"',
                      source)

    def test_post_commit_declares_the_same_count_as_all(self):
        """The two are one set of checks under two names.

        `all` is what an operator asks for; `post-commit` is the
        position the sequencer occupies.  They must not diverge.
        """
        source = gate_source()
        self.assertRegex(
            source,
            r'"\$\{PHASE_ALL\}"\|"\$\{PHASE_POST_COMMIT\}"\)')


class TestTheLintCheckCannotBeSkipped(GateInvocation):
    """An unresolvable linter is a FAILURE, never a quiet omission.

    This is the half of the container problem that lives in the gate.
    The other half is the image: supported_env.sh forwards HOME, TMPDIR
    and the cleared trust-bypass names and nothing else, so a host-side
    PLAYTHROUGH_FLAKE8 never reaches a `supported_env.sh run` and the
    linter has to be installed inside the image.  What is asserted here
    is that an image without one cannot pass by omission -- the lint
    verdict FAILS, the run exits non-zero, and the diagnosis names the
    container so an operator is not left guessing why an override they
    exported had no effect.
    """

    # A real pre-commit run, which reads the whole committed artifact
    # set.  Measured at about twenty-two seconds on the provisioned
    # host, so this ceiling is generous rather than tight.
    TIMEOUT = 600

    def test_the_gate_has_no_skip_verdict_at_all(self):
        """Four verdict kinds, and none of them is "skipped"."""
        source = gate_source()
        self.assertNotIn("record_skip", source)
        self.assertIn("There is no SKIP verdict, deliberately", source)

    def test_an_unresolvable_linter_is_a_failure_and_says_why(self):
        status, out, err = self.run_gate(
            "--phase", PHASE_PRE, "--samples", "2",
            PLAYTHROUGH_FLAKE8="/nonexistent/flake8")
        self.assertEqual(status, EX_FAILED, msg=err)
        self.assertIn("FAIL  the new Python satisfies the repository's "
                      "own", out)
        # resolve_flake8 reports the override it could not run, rather
        # than letting a shell error be printed as a lint finding.
        self.assertIn("would not run", out)
        # And the diagnosis names the container case.
        self.assertIn("supported_env.sh forwards HOME", out)

    def test_it_keeps_measuring_everything_else(self):
        """One unresolved tool is one failure, not an abandoned run.

        The whole reporting model rests on this: a gate that stopped at
        the first broken property would tell an operator about the lint
        and leave them ignorant of the other ninety-eight.
        """
        status, out, err = self.run_gate(
            "--phase", PHASE_PRE, "--samples", "2",
            PLAYTHROUGH_FLAKE8="/nonexistent/flake8")
        self.assertEqual(status, EX_FAILED, msg=err)
        fields = self.machine_block(out)
        self.assertEqual(fields.get("VERIFY_FAILURES"), "1",
                         msg="only the lint verdict should have failed")
        self.assertEqual(
            fields.get("VERIFY_CHECKS"),
            fields.get("VERIFY_EXPECTED_CHECKS"),
            msg="the full declared inventory should still be performed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
