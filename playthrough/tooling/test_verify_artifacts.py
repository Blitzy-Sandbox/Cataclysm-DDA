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
* THE POST-COMMIT PHASE MEASURES THE HISTORY AND NOT THE ARTIFACTS.  It
  used to be an alias for `all`, which meant a default sequencer run
  performed the eighty-nine artifact checks TWICE -- two whole-set digest
  sweeps, two decodes of each film, two lint runs, two runs of the
  timeline suite -- minutes apart, over bytes the commit in between had
  not touched.  So the artifact groups are called under an
  `artifact_phase` predicate, the history groups under `tracking_phase`,
  and `all` is the only phase that is both.
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
* THE CRITICAL CHECKS ARE MEASURED AGAINST MUTATED EVIDENCE, one property
  at a time, inside a synthetic tree:
    - THE VARIABLE-FRAME-RATE FALLBACK.  Under -fps_mode vfr a container
      routinely declares no frame count, so the gate decodes; when the
      decode yields nothing it asks for the PACKET count instead.  A
      fallback nobody exercises is a fallback that silently reports
      "unreadable" on every correct film, so both readings are supplied
      and withheld in turn.
    - A BLACK OR UNIFORM CAPTURE.  mean=0 std=0 is the
      SDL_VIDEODRIVER=dummy signature and std=0 alone is a solid-colour
      frame; both are refused, and a real reading passes.  This is the
      one gate standing between a black film and a green report, so it is
      measured rather than read.
    - THE TRANSITION SAMPLING EXEMPTION.  A frame extracted from inside a
      fade or a title card is legitimately near-black, so an offset that
      lands in a transition window is moved past it.  Without the
      exemption the luminance gate would fail a correct film.
    - THE PHASE GATING, OVER ONE TREE.  The commit-shaped checks are not
      merely classified as deferred in the source: under pre-commit they
      are not called, and under post-commit they are.
    - CONTINUATION AFTER A FAILURE.  A failing check is not a reason to
      stop measuring: the whole gate is run over a deliberately
      incomplete tree and every group, the summary, the machine block and
      the exit status are held to appearing anyway.

HOW THE GATE IS TESTED WITHOUT A FULL ARTIFACT SET
Two harnesses, and neither reads the committed artifacts.

The first asks what the SOURCE says (the classification, the declared
counts, the call sites) and what the CLI does before any artifact is read
(the phase resolution and its refusals).

The second builds a SYNTHETIC TREE in a temporary directory -- a
miniature checkout with copies of env.sh and verify_artifacts.sh, a real
git repository, whatever frames, films and facts the check under test
needs, and fake ffprobe, ffmpeg, convert, identify and compare binaries
that answer exactly what a test told them to.  verify_artifacts.sh ends
with one `main "$@"` line, so a copy with that line removed can be
SOURCED: the real check functions are then called one at a time against
mutated evidence, and their verdicts are read off stdout.  The same
sandbox is also used to run the whole real gate end to end.

WHAT THE SYNTHETIC TREE IS NOT.  It is not a passing artifact set: no
manifest, timeline, digest ledger, save tree or checkpoint history is
reproduced, and a whole-gate run over it fails most of its checks by
design.  Each test builds the evidence ITS check reads, in both the
shape that must pass and the shape that must fail, which is what makes a
verdict here attributable to one property.

Standard library only.  Nothing outside a temporary directory is written.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

# Keep bytecode out of playthrough/tooling/: the terminal
# `!/playthrough/**` negation in .gitignore re-includes anything written
# there, so a __pycache__ beside this file would be committable.
sys.dont_write_bytecode = True

TOOLING = os.path.dirname(os.path.abspath(__file__))
PLAYTHROUGH = os.path.dirname(TOOLING)
REPO_ROOT = os.path.dirname(PLAYTHROUGH)
GATE = os.path.join(TOOLING, "verify_artifacts.sh")
ENV_SH = os.path.join(TOOLING, "env.sh")

# The line that runs the gate.  Removed from the copy the synthetic
# fixture sources, and asserted to exist so a rename cannot leave the
# harness silently running all 120 checks against a temporary tree.
MAIN_INVOCATION = '\nmain "$@"\n'

# The name the sourceable copy takes inside the sandbox.
PROBE_NAME = "gate_probe.sh"

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
    # check_lifecycle_checkpoints calls this one, so it is deferred with
    # it; it is named separately because it is a separate verdict and the
    # inventory counts verdicts.
    ("check_checkpoints_are_this_session", 1),
    ("check_head_generation_checkpoints", 1),
    ("check_change_surface", 1),
)

# The checks the post-commit phase does NOT perform, because they are
# properties of the ARTIFACTS and the commit does not touch the artifacts.
# Each is expensive in a way that scales with the session -- a digest
# sweep, a decode, a raster read, a linter, a suite -- which is why
# running them a second time minutes later was the defect.
ARTIFACT_ONLY_CHECKS = (
    "check_binary_is_tiles",
    "check_tileset_in_engine_log",
    "check_tiles_are_visible",
    "check_lint_scoped",
    "check_flake8_not_weakened",
    "check_timeline_tests",
)

# The groups the post-commit phase runs, and the ones it leaves out.
HISTORY_GROUPS = ("group_environment", "group_version_control",
                  "group_hygiene", "group_inventory")
ARTIFACT_GROUPS = ("group_record", "group_timeline", "group_container",
                   "group_captions", "group_luminance",
                   "group_no_cheating")


def gate_source():
    """The gate's own text, which several assertions are made against."""
    with open(GATE, encoding="utf-8") as handle:
        return handle.read()


def checker_source(label):
    """One embedded Python checker's text, out of its own heredoc.

    The checkers live in `emit_checker <label> <<'PY' ... PY` blocks, so
    they are read from the gate rather than from a file of their own --
    which is the point of embedding them: one artifact to commit, one
    place for the shell and the Python that measure the same property.
    """
    match = re.search(r"emit_checker %s <<'PY'\n(.*?)\nPY\n"
                      % re.escape(label), gate_source(), re.DOTALL)
    if match is None:
        raise AssertionError("verify_artifacts.sh emits no %s checker"
                             % label)
    return match.group(1)


def joined_source():
    """The gate's text with shell line-continuations joined.

    Every long string in the gate is wrapped with a trailing backslash,
    which is how the shell reads it as one line -- so an assertion about
    a PHRASE has to read it the same way.  Matching the raw text instead
    would fail whenever a sentence happened to wrap, which is a fact
    about the column limit rather than about the code.
    """
    return gate_source().replace("\\\n", "")


def group_table(name):
    """One `readonly -a NAME=( ... )` row of integers, as a list.

    The gate no longer writes its totals down: it declares a per-group
    table and SUMS it, because a hand-maintained total is a second place
    for the truth to live and the first thing that happens to it is that
    somebody updates one and not the other.  This suite reads the table
    the same way and does the same arithmetic, so the two cannot drift.
    """
    match = re.search(
        r"^readonly -a %s=\(\s*\n\s*([0-9 ]+)\s*\n\)$"
        % re.escape(name), gate_source(), re.MULTILINE)
    if match is None:
        raise AssertionError(
            "verify_artifacts.sh declares no %s table" % name)
    return [int(value) for value in match.group(1).split()]


def declared(name):
    """The total a phase declares, summed from its group table."""
    tables = {
        "EXPECTED_CHECKS_ALL": "GROUP_CHECKS_ALL",
        "EXPECTED_CHECKS_PRE_COMMIT": "GROUP_CHECKS_PRE_COMMIT",
        "EXPECTED_CHECKS_POST_COMMIT": "GROUP_CHECKS_POST_COMMIT",
    }
    if name not in tables:
        raise AssertionError("no group table is known for %s" % name)
    return sum(group_table(tables[name]))


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

    # THE GATE HAS ONE SIDE EFFECT ON THE REAL TREE, AND THIS SUITE RUNS
    # THE REAL GATE.
    #
    # `publish_report` REMOVES a stale playthrough/acceptance-report.txt
    # whenever a run fails, and it is right to: a passing report from an
    # earlier tree must not stand as evidence for the artifacts as they
    # are now.  But several tests here make the gate fail on purpose --
    # an unresolvable linter, an untrusted override -- and they run it
    # from the real repository root, so exercising a refusal DELETED a
    # committed artifact.  Measured: `-k LintCheck` alone reported four
    # tests OK and left `D playthrough/acceptance-report.txt` behind.
    #
    # The file is therefore taken out of the way for the duration of
    # every run and written back byte-for-byte afterwards.  Removing it
    # first rather than restoring it later is deliberate: the gate then
    # finds nothing to remove and nothing to overwrite, so there is no
    # window in which a concurrent reader sees a half-written report, and
    # no run from this suite can publish one either.
    REPORT = os.path.join(PLAYTHROUGH, "acceptance-report.txt")

    def report_bytes(self):
        """The committed acceptance report's bytes, or None."""
        if not os.path.isfile(self.REPORT):
            return None
        with open(self.REPORT, "rb") as handle:
            return handle.read()

    def run_gate(self, *args, **environment):
        """Run verify_artifacts.sh from the repository root.

        The real acceptance report is preserved across the call, so an
        assertion made after it is made against an untouched tree.
        """
        preserved = self.report_bytes()
        if preserved is not None:
            os.unlink(self.REPORT)
        try:
            return self._run_gate(*args, **environment)
        finally:
            if preserved is not None:
                with open(self.REPORT, "wb") as handle:
                    handle.write(preserved)

    def _run_gate(self, *args, **environment):
        """The invocation itself, with no tree protection of its own."""
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
    """The three totals, and the classification that separates them."""

    def test_every_total_is_declared(self):
        self.assertGreater(declared("EXPECTED_CHECKS_ALL"), 0)
        self.assertGreater(declared("EXPECTED_CHECKS_PRE_COMMIT"), 0)
        self.assertGreater(declared("EXPECTED_CHECKS_POST_COMMIT"), 0)

    def test_the_post_commit_total_is_the_smallest(self):
        """It measures the history, not the tree.

        A post-commit total equal to the full one is the defect this
        split exists to remove: it meant the artifact half ran twice.
        """
        self.assertLess(declared("EXPECTED_CHECKS_POST_COMMIT"),
                        declared("EXPECTED_CHECKS_PRE_COMMIT"))
        self.assertLess(declared("EXPECTED_CHECKS_POST_COMMIT"),
                        declared("EXPECTED_CHECKS_ALL"))

    def test_the_two_phases_together_cover_the_whole_gate(self):
        """Every check is in at least one of the two halves.

        The halves overlap deliberately -- group 1 and the closing
        bytecode sweep are in both, because a phase that cannot establish
        it is able to measure cannot report what it measured -- so the sum
        is at least the full total rather than exactly it.
        """
        self.assertGreaterEqual(
            declared("EXPECTED_CHECKS_PRE_COMMIT") +
            declared("EXPECTED_CHECKS_POST_COMMIT"),
            declared("EXPECTED_CHECKS_ALL"),
            msg="the two phases must not between them measure less than "
                "the whole gate")

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

    def test_the_derivation_comment_carries_every_column(self):
        source = gate_source()
        self.assertIn("all   pre   post", source)
        for name in ("EXPECTED_CHECKS_ALL", "EXPECTED_CHECKS_PRE_COMMIT",
                     "EXPECTED_CHECKS_POST_COMMIT"):
            self.assertIn(str(declared(name)), source)

    def test_the_two_tables_cover_the_same_ten_groups(self):
        """Index 0 is a placeholder, so both rows are eleven long."""
        every = group_table("GROUP_CHECKS_ALL")
        early = group_table("GROUP_CHECKS_PRE_COMMIT")
        self.assertEqual(len(every), len(early))
        self.assertEqual(len(every), 11,
                         msg="ten groups plus the unused index 0")
        self.assertEqual(every[0], 0)
        self.assertEqual(early[0], 0)

    def test_no_group_defers_more_than_it_declares(self):
        """A pre-commit count above the full count is nonsense."""
        every = group_table("GROUP_CHECKS_ALL")
        early = group_table("GROUP_CHECKS_PRE_COMMIT")
        for index, (a, b) in enumerate(zip(every, early)):
            self.assertLessEqual(
                b, a,
                msg=("group %d declares %d for pre-commit and only %d "
                     "in total" % (index, b, a)))

    def test_the_deferred_checks_all_belong_to_the_two_groups(self):
        """Only groups 7 and 9 defer anything, and by the right amount.

        This is the arithmetic the gate's own inventory now enforces per
        group; asserting it here fails at test time instead, which is
        cheaper and names the group.
        """
        every = group_table("GROUP_CHECKS_ALL")
        early = group_table("GROUP_CHECKS_PRE_COMMIT")
        deferred_by_group = {
            index: a - b
            for index, (a, b) in enumerate(zip(every, early)) if a != b
        }
        self.assertEqual(sorted(deferred_by_group), [7, 9],
                         msg="only version control and hygiene defer")
        self.assertEqual(deferred_by_group[9], 1,
                         msg="group 9 defers the change surface alone")
        self.assertEqual(
            deferred_by_group[7],
            sum(count for name, count in DEFERRED_CHECKS
                if name != "check_change_surface"),
            msg="group 7 defers every other classified check")

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


class TestTheArtifactChecksAreGatedToo(unittest.TestCase):
    """The other half of the split, asserted the same way.

    A commit changes the history and not the bytes on disk, so the
    post-commit phase must not re-measure the artifacts.  The predicate
    that decides it lives in ONE place, exactly as tracking_phase does,
    and every expensive artifact-shaped check is called under it.
    """

    def test_the_predicate_exists(self):
        self.assertTrue(
            defines("artifact_phase"),
            msg="verify_artifacts.sh defines no artifact_phase()")

    def test_the_predicate_is_the_only_thing_that_decides(self):
        source = gate_source()
        body = re.search(r"^artifact_phase\(\) \{\n(.*?)^\}",
                         source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("PHASE_POST_COMMIT", body.group(1))

    def test_the_artifact_groups_are_called_under_the_predicate(self):
        """Not one artifact group runs in the history-only phase."""
        lines = gate_source().splitlines()
        for name in ARTIFACT_GROUPS:
            sites = [(number, line.strip())
                     for number, line in enumerate(lines, 1)
                     if line.strip() == name]
            self.assertTrue(sites, msg="%s is never called" % name)
            for number, text in sites:
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
                         "the post-commit phase would then re-measure "
                         "the artifacts" % (name, number, text)))
                self.assertIn("artifact_phase", guard)

    def test_the_history_groups_are_called_unconditionally(self):
        """The history half runs in every phase.

        Group 7's own commit-shaped checks are gated inside it by
        tracking_phase; the GROUP is not, because its working-tree checks
        are answerable at any time and the environment group is what
        establishes that this run can measure at all.
        """
        lines = [line.strip() for line in gate_source().splitlines()]
        for name in HISTORY_GROUPS:
            self.assertIn(name, lines,
                          msg="%s is never called" % name)

    def test_every_artifact_only_check_is_gated(self):
        lines = gate_source().splitlines()
        for name in ARTIFACT_ONLY_CHECKS:
            sites = [number for number, line in enumerate(lines, 1)
                     if line.strip().startswith(name) and
                     not line.startswith("%s()" % name)]
            self.assertTrue(sites, msg="%s is never called" % name)
            for number in sites:
                guard = None
                for index in range(number - 2, max(number - 60, 0), -1):
                    candidate = lines[index].strip()
                    if candidate.startswith("if "):
                        guard = candidate
                        break
                self.assertIsNotNone(
                    guard, msg="%s is called unconditionally" % name)
                self.assertIn("artifact_phase", guard)


class TestTheBoundedChildren(unittest.TestCase):
    """Every external command runs under a derived ceiling.

    A gate holds the pipeline's lock while it runs, so a wedged ffmpeg or
    a hung ImageMagick would stop the pipeline for ever with no verdict
    and no diagnosis.  The bound is TERM then KILL over the child's own
    process group, and it is DERIVED -- from a film's byte count, from the
    capture population -- because a fixed number is either too small for a
    long session or no bound at all.
    """

    def test_the_runner_exists_and_escalates(self):
        source = gate_source()
        self.assertTrue(defines("bounded"))
        body = re.search(r"^bounded\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("--kill-after=", body.group(1))
        self.assertIn("--signal=TERM", body.group(1))
        self.assertIn("${TIMEOUT}", body.group(1))

    def test_timeout_is_a_verified_tool(self):
        """It is resolved and checked like every other command.

        REQUIRED_COMMANDS is the single declaration, and resolve_tools
        reads its array straight out of it, so asserting membership there
        asserts that `timeout` goes through playthrough_require_tools
        with the other twenty-one.  A second list inside resolve_tools is
        exactly the drift this shape removes.
        """
        source = gate_source()
        match = re.search(
            r'readonly REQUIRED_COMMANDS="((?:[^"\\]|\\\n)*)"', source)
        self.assertIsNotNone(match)
        self.assertIn("timeout",
                      match.group(1).replace("\\\n", " ").split())
        body = re.search(r"^resolve_tools\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn('read -r -a wanted <<<"${REQUIRED_COMMANDS}"',
                      body.group(1))
        self.assertIn('TIMEOUT="${PLAYTHROUGH_BIN_TIMEOUT:-timeout}"',
                      source)

    def test_the_film_ceiling_is_derived_from_the_film(self):
        source = gate_source()
        self.assertTrue(defines("film_bound"))
        self.assertIn("BOUND_FILM_BYTES_PER_SECOND", source)
        body = re.search(r"^film_bound\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("file_bytes", body.group(1))

    def test_the_checker_ceiling_is_derived_from_the_population(self):
        source = gate_source()
        self.assertTrue(defines("checker_bound"))
        body = re.search(r"^checker_bound\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("capture_count", body.group(1))

    def test_no_media_tool_is_invoked_unbounded(self):
        """Every ffprobe, ffmpeg, convert, identify and compare call.

        The tools are invoked through their resolved variables, so a call
        site is `"${FFPROBE}"` and the line above it -- or the same line --
        must be the bounded runner.
        """
        source = gate_source()
        unbounded = []
        lines = source.splitlines()
        for number, line in enumerate(lines, 1):
            for tool in ('"${FFPROBE}"', '"${FFMPEG}"', '"${CONVERT}"',
                         '"${IDENTIFY}"', '"${COMPARE}"'):
                if tool not in line:
                    continue
                if line.strip().startswith("#"):
                    continue
                window = " ".join(lines[max(number - 3, 0):number])
                if "bounded" in window:
                    continue
                unbounded.append("line %d: %s" % (number, line.strip()))
        self.assertEqual(
            unbounded, [],
            msg="these media calls are not bounded: %s"
                % "; ".join(unbounded))

    def test_no_interpreter_or_linter_child_is_invoked_unbounded(self):
        """The Python checkers, the probes and the linter, too.

        The header claims every MEASURING child is bounded, and an
        interpreter that will not return stalls the gate exactly as a
        wedged ffmpeg does.  Array assignments that merely NAME the
        interpreter are not invocations, so they are skipped.
        """
        lines = gate_source().splitlines()
        marks = ('"${PYTHON}" -B', '"${FLAKE8_CMD[@]}"',
                 '"${PLAYTHROUGH_FLAKE8}" --version',
                 'python3 -B -m flake8')
        unbounded = []
        for number, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            if "FLAKE8_CMD=(" in line:
                continue
            if not any(mark in line for mark in marks):
                continue
            window = " ".join(lines[max(number - 3, 0):number])
            if "bounded" in window:
                continue
            unbounded.append("line %d: %s" % (number, line.strip()))
        self.assertEqual(
            unbounded, [],
            msg="these interpreter/linter calls are not bounded: %s"
                % "; ".join(unbounded))

    def test_the_residual_is_named_rather_than_implied(self):
        """What is NOT wrapped is stated, so the claim stays true.

        git plumbing and the shell's own text utilities are deliberately
        not individually bounded.  A header that claimed "every external
        command" would be overstating what is delivered, so the class is
        named and the residual is recorded.
        """
        source = gate_source()
        self.assertIn("EVERY MEASURING CHILD IS TIME-BOUNDED", source)
        self.assertIn("WHAT IS DELIBERATELY NOT WRAPPED", source)


class TestTheScratchGenerationIsSwept(unittest.TestCase):
    """A killed audit must not leak its working directory for ever."""

    def test_the_owner_is_recorded(self):
        source = gate_source()
        self.assertIn("SCRATCH_OWNER_FILE", source)
        self.assertRegex(source,
                         r'printf .%s\\n. "\$\$" >"\$\{SCRATCH\}/')

    def test_the_sweep_runs_and_is_bounded_to_the_runtime_root(self):
        source = gate_source()
        self.assertTrue(defines("sweep_stale_scratch"))
        body = re.search(r"^sweep_stale_scratch\(\) \{\n(.*?)^\}",
                         source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("${SCRATCH_PREFIX}", body.group(1))
        self.assertIn('[ "${dir}" != "${SCRATCH}" ]', body.group(1))
        self.assertIn("scratch_is_stale", body.group(1))

    def test_a_live_owner_is_never_swept(self):
        source = gate_source()
        self.assertTrue(defines("owner_is_alive"))
        body = re.search(r"^scratch_is_stale\(\) \{\n(.*?)^\}",
                         source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("owner_is_alive", body.group(1))
        self.assertIn("SCRATCH_STALE_SECONDS", body.group(1))


class TestTheSharedWorkIsNotRepeated(unittest.TestCase):
    """One decode per film, one digest per file, one offset extraction."""

    def test_the_decode_pass_is_taken_once_and_cached(self):
        source = gate_source()
        self.assertTrue(defines("film_decode_pass"))
        body = re.search(r"^film_decode_pass\(\) \{\n(.*?)^\}",
                         source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        # The state file is what makes a second call free.
        self.assertIn('if [ ! -f "${state}" ]', body.group(1))
        # And the count comes out of the same pass rather than a walk of
        # its own.
        self.assertIn("-progress", body.group(1))

    def test_the_frame_count_reads_the_shared_pass(self):
        source = gate_source()
        body = re.search(r"^decoded_frames\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn("film_decode_pass", body.group(1))
        self.assertNotIn("count_frames", body.group(1))

    def test_an_extracted_frame_is_reused(self):
        source = gate_source()
        self.assertTrue(defines("extracted_frame"))
        body = re.search(r"^extracted_frame\(\) \{\n(.*?)^\}", source,
                         re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body)
        self.assertIn('if [ -s "${path}" ]', body.group(1))

    def test_the_digest_inventory_is_shared_between_the_checkers(self):
        source = gate_source()
        self.assertTrue(defines("digest_inventory"))
        # Group 3 writes it and group 4 reads it, so both checkers are
        # handed the same path.
        self.assertEqual(source.count('"$(digest_inventory)"'), 2)

    def test_the_transition_windows_are_a_file_not_an_argument(self):
        """MAX_ARG_STRLEN is 131072 bytes, whatever argv can hold.

        One window is about thirteen bytes, so a single joined value
        cannot carry ten thousand of them -- and a session that sleeps
        through ten thousand nights is the session this pipeline is for.
        """
        source = gate_source()
        self.assertTrue(defines("windows_file"))
        self.assertNotIn("transition_windows=%s", source)
        self.assertIn("windows_path", source)

    def test_the_in_game_frames_are_a_file_not_an_argument(self):
        source = gate_source()
        self.assertTrue(defines("in_game_file"))
        self.assertNotIn("in_game_frames=%s", source)
        self.assertTrue(defines("sample_file"))


class TestTheCheckersStreamTheirPopulations(unittest.TestCase):
    """No checker holds the session in memory to walk it.

    The session length is deliberately unbounded, and a document with one
    entry per keystroke costs roughly a kilobyte of interpreter objects
    per entry.  Every checker that only WALKS its input reads it as a
    stream: the record and the sidecars line by line, the timeline through
    the producer's own event reader, the concat list and the cue file as
    generators.  Each also bounds the diagnostics it collects, because one
    finding per keystroke is the realistic shape of a broken artifact set.
    """

    def test_every_checker_bounds_its_diagnostics(self):
        for label in ("record", "timeline", "render", "caption"):
            with self.subTest(checker=label):
                body = checker_source(label)
                self.assertIn("PROBLEM_LIMIT", body)
                self.assertIn("def note_problem", body)

    def test_the_record_is_streamed_a_row_at_a_time(self):
        body = checker_source("record")
        # The whole-file read is gone, and what replaced it is a loop over
        # the handle.  Asserted with a short message: the subject here is
        # a seven-hundred-line checker.
        # `handle.read().splitlines()` is the call that was removed, and
        # it is named exactly: the comment that explains why it was wrong
        # quotes it, so a loose match would find the explanation.
        self.assertTrue("handle.read().splitlines()" not in body,
                        msg="the record checker still reads the whole "
                            "record before walking it")
        self.assertTrue("for number, raw in enumerate(handle, 1)" in body,
                        msg="the record checker no longer streams its "
                            "rows")

    def test_the_timeline_is_read_as_a_header_and_a_stream(self):
        body = checker_source("timeline")
        self.assertTrue("tl.read_timeline_header(timeline_path)" in body,
                        msg="the timeline checker does not read a header")
        self.assertTrue("tl.iter_timeline_frames(path)" in body,
                        msg="the timeline checker does not stream the "
                            "entries")
        # The whole-document load is gone.  The call is named exactly, not
        # matched loosely: the prose in this checker explains WHY
        # json.load() was wrong, and a loose match would find the
        # explanation.
        self.assertTrue("json.load(handle)" not in body,
                        msg="the timeline checker still loads the whole "
                            "document")

    def test_the_timeline_is_walked_exactly_once(self):
        """Five walks over a held list became one walk over a stream."""
        body = checker_source("timeline")
        self.assertIn("def walk_entries(", body)
        self.assertEqual(body.count("walk_entries("), 2)
        # And the reporters take the walk, not the entries.
        self.assertIn("def check_clamp(walk, floor, ceil)", body)
        self.assertIn("def check_cues(walk, trans)", body)
        self.assertIn("def check_invariant(walk, document, trans, "
                      "walked, eps)", body)

    def test_the_windows_are_written_during_that_walk(self):
        body = checker_source("timeline")
        self.assertRegex(body, r'open\(windows_path, "w"')
        self.assertIn("windows.write(", body)

    def test_the_concat_list_and_the_cues_are_generators(self):
        render = checker_source("render")
        self.assertIn("def iter_list_lines(", render)
        self.assertIn("def iter_expected(", render)
        self.assertIn("def iter_list_names(", render)
        caption = checker_source("caption")
        self.assertIn("def iter_cue_blocks(", caption)


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

    def test_post_commit_is_no_longer_an_alias_for_all(self):
        """THE DEFECT THIS TEST EXISTS FOR.

        `all` and `post-commit` used to resolve through one `case` arm to
        one declared total, which is what made the sequencer's second gate
        run a repeat of its first: the eighty-nine artifact checks were
        performed twice over bytes the commit had not touched.  Each
        phase now resolves to its own total.
        """
        source = gate_source()
        self.assertNotRegex(
            source,
            r'"\$\{PHASE_ALL\}"\|"\$\{PHASE_POST_COMMIT\}"\)')
        self.assertIn('EXPECTED_CHECKS="${EXPECTED_CHECKS_POST_COMMIT}"',
                      source)


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
        # resolve_flake8 reports the override it did not accept, rather
        # than letting a shell error be printed as a lint finding.
        self.assertIn("PLAYTHROUGH_FLAKE8=\'/nonexistent/flake8\' was "
                      "not accepted", out)
        # And the diagnosis names the container case.
        self.assertIn("supported_env.sh forwards HOME", out)

    def failing_checks(self, out):
        """The names of the checks that FAILED, as a set."""
        return {line[len("FAIL  "):].strip()
                for line in out.splitlines()
                if line.startswith("FAIL  ")}

    def test_an_untrusted_override_is_refused_before_it_is_executed(self):
        """Verification comes first, and the probe is an execution too.

        An override used to be accepted on the strength of a successful
        `--version`, which is not a check but the first run of an
        arbitrary path taken from the environment.  A world-writable
        executable is the case that proves the order changed: it runs
        perfectly, so a probe-first resolver would have adopted it.
        """
        with tempfile.TemporaryDirectory(
                dir=os.environ.get("PLAYTHROUGH_RUNTIME_DIR", "/tmp"),
        ) as scratch:
            planted = os.path.join(scratch, "flake8")
            with open(planted, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(planted, 0o777)
            status, out, err = self.run_gate(
                "--phase", PHASE_PRE, "--samples", "2",
                PLAYTHROUGH_FLAKE8=planted)
        self.assertEqual(status, EX_FAILED, msg=err)
        self.assertIn("was not accepted", out)
        self.assertIn("failed executable verification", out)
        self.assertIn("FAIL  the new Python satisfies the repository's "
                      "own", out)

    def test_it_keeps_measuring_everything_else(self):
        """One unresolved tool is one failure, not an abandoned run.

        The whole reporting model rests on this: a gate that stopped at
        the first broken property would tell an operator about the lint
        and leave them ignorant of the other hundred and five.

        THE COMPARISON IS AGAINST A CONTROL RUN, NOT AGAINST A NUMBER.
        A fixed expected failure count would additionally be asserting
        that THIS host's tree answers every other check -- the built
        binary, the installed artwork -- which is a statement about the
        host rather than about the gate's reporting model, and it made
        this test fail on a clone that had not built the engine.  Two
        runs of the same phase, one with a working linter and one with a
        broken one, differ by EXACTLY the lint verdict; everything else
        is measured identically in both.
        """
        control_status, control_out, control_err = self.run_gate(
            "--phase", PHASE_PRE, "--samples", "2")
        status, out, err = self.run_gate(
            "--phase", PHASE_PRE, "--samples", "2",
            PLAYTHROUGH_FLAKE8="/nonexistent/flake8")
        self.assertEqual(status, EX_FAILED, msg=err)
        lint = "the new Python satisfies the repository's own lint \
contract"
        broken = self.failing_checks(out)
        control = self.failing_checks(control_out)
        self.assertIn(lint, broken,
                      msg="the unresolvable linter must FAIL its check")
        self.assertNotIn(
            lint, control,
            msg=("the control run's linter must work, or this test is "
                 "comparing two broken runs: exit %d, stderr %s"
                 % (control_status, control_err[-400:])))
        self.assertEqual(
            broken - control, {lint},
            msg="a broken linter must not change any other verdict")
        self.assertEqual(
            control - broken, set(),
            msg="a broken linter must not silence any other verdict")
        fields = self.machine_block(out)
        # THE ASSERTION IS ABOUT COMPLETENESS, NOT ABOUT THE FAILURE
        # COUNT.  A count would make this test a statement about how
        # well the host happens to be provisioned -- an unset
        # repository-local git identity or an uninstalled tileset are
        # real failures of the TREE that have nothing to do with the
        # linter -- and it would go red for reasons this test is not
        # about.  What must hold is that the run kept going and measured
        # every declared check, and that the lint verdict is among the
        # failures.
        self.assertIn("FAIL  the new Python satisfies the repository's "
                      "own", out)
        self.assertEqual(
            fields.get("VERIFY_CHECKS"),
            fields.get("VERIFY_EXPECTED_CHECKS"),
            msg="the full declared inventory should still be performed")
        self.assertIn("PASS  this report contains every check this "
                      "gate declares", out)
        self.assertGreater(int(fields.get("VERIFY_PASSES", "0")), 50,
                           msg="the other properties are still measured")


class TestTheCheckpointsMustBeThisSession(unittest.TestCase):
    """C-02: a superseded checkpoint pair FAILS rather than warns.

    The gate used to accept any internally consistent creation/final
    pair and report a pair describing a different, superseded survivor
    as a WARNING -- which does not affect the exit status.  So R1's "the
    save was committed at both mandated points" could be satisfied by
    two commits about somebody whose files were no longer in the tree.
    """

    def test_the_check_exists_and_is_declared_as_deferred(self):
        self.assertTrue(defines("check_checkpoints_are_this_session"))
        self.assertIn(
            "check_checkpoints_are_this_session",
            [name for name, _ in DEFERRED_CHECKS])

    def test_the_divergence_is_a_failure_and_not_a_warning(self):
        """No record_warn survives anywhere near the checkpoint checks."""
        source = gate_source()
        start = source.index("check_checkpoints_are_this_session() {")
        end = source.index("group_version_control() {", start)
        body = source[start:end]
        self.assertNotIn("record_warn", body)
        self.assertIn("record_fail", body)

    def test_head_is_what_the_pair_is_measured_against(self):
        source = gate_source()
        start = source.index("check_checkpoints_are_this_session() {")
        end = source.index("group_version_control() {", start)
        body = source[start:end]
        self.assertIn("LIFECYCLE_HEAD_SURVIVOR", body)
        # Both ends of the pair are compared, not just the final.
        self.assertIn("CHECKPOINT_CREATION_NAME", body)
        self.assertIn("CHECKPOINT_FINAL_NAME", body)

    def test_ancestry_is_asserted_rather_than_inferred(self):
        """A creation that is not an ancestor of its final is refused.

        `git log --grep <commit>` already walks only ancestors, so
        reachability is implied -- but implied is not asserted, and the
        case reachability does not exclude is one commit standing for
        both ends of a session.
        """
        source = gate_source()
        start = source.index("check_lifecycle_checkpoints() {")
        end = source.index("group_version_control() {", start)
        body = source[start:end]
        self.assertIn("merge-base --is-ancestor", body)
        self.assertEqual(
            body.count("merge-base --is-ancestor"), 2,
            msg="both the per-final loop and the newest pair assert it")
        self.assertIn("is its own", body)

    def test_an_unreadable_head_is_a_failure_not_a_skip(self):
        source = gate_source()
        start = source.index("check_checkpoints_are_this_session() {")
        end = source.index("group_version_control() {", start)
        body = source[start:end]
        marker = body.index('if [ -z "${head_survivor}" ]; then')
        self.assertIn("record_fail", body[marker:marker + 400])


class TestTheGitIdentityIsTheRepositorysOwn(unittest.TestCase):
    """M-04: the identity is read from this checkout, not the cascade."""

    def test_the_local_scope_is_what_decides(self):
        source = gate_source()
        start = source.index("check_git_identity() {")
        end = source.index("committed_file() {", start)
        body = source[start:end]
        self.assertIn("config --local --get user.name", body)
        self.assertIn("config --local --get user.email", body)

    def test_no_cascade_read_decides_the_verdict(self):
        """The inherited values are reported, never used as the answer."""
        source = gate_source()
        start = source.index("check_git_identity() {")
        end = source.index("committed_file() {", start)
        body = source[start:end]
        # The pass is reported from the local values alone.
        pass_at = body.index("record_pass")
        self.assertIn("--local --get", body[:pass_at])
        # The cascade appears only in the failure's explanatory detail.
        self.assertIn("inherited_name", body)
        self.assertIn("is NOT this repository", body)

    def test_the_check_name_says_which_scope_it_is_about(self):
        self.assertIn("REPOSITORY-LOCAL identity", gate_source())


class TestTheDependencyClosureIsMeasured(unittest.TestCase):
    """M-05: five properties, not one version string."""

    CLOSURE_CHECKS = (
        "the interpreter is the CPython",
        "the declaration and the lock pin the same versions",
        "every declared library is installed at its declared version",
        "every declared library imports",
        "every installed distribution has its own requirements met",
    )

    def test_the_gate_calls_the_shared_checker(self):
        source = gate_source()
        self.assertTrue(defines("check_dependency_closure"))
        self.assertIn("playthrough_write_closure_checker", source)
        self.assertIn("check_dependency_closure", source)

    def test_the_program_is_env_shs_so_both_stages_share_one(self):
        """One assertion, two consumers, defined in neither of them."""
        with open(os.path.join(TOOLING, "env.sh"),
                  encoding="utf-8") as handle:
            env = handle.read()
        self.assertIn("PLAYTHROUGH_CLOSURE_CHECKER='", env)
        self.assertIn("playthrough_write_closure_checker()", env)
        self.assertIn("PLAYTHROUGH_REQUIREMENTS_LOCK", env)

    def test_the_program_is_assigned_and_never_readonly(self):
        """env.sh is re-sourced, so a readonly here would print to stderr.

        Not a style point.  env.sh is sourced by every stage AND by the
        stages a stage calls, and it is required to be SILENT every time
        -- test_env.py's TestSourcingTwiceIsSafe asserts exactly that.  A
        `readonly` declaration makes the second source write
        "PLAYTHROUGH_CLOSURE_CHECKER: readonly variable" to stderr, which
        is how this was found.  Nothing in env.sh is readonly for that
        reason, so the absence is asserted here rather than left to be
        rediscovered by whoever next reaches for immutability.
        """
        with open(os.path.join(TOOLING, "env.sh"),
                  encoding="utf-8") as handle:
            env = handle.read()
        self.assertNotIn("readonly PLAYTHROUGH_CLOSURE_CHECKER", env)
        self.assertNotIn("declare -r PLAYTHROUGH_CLOSURE_CHECKER", env)
        # And the reason is recorded beside the assignment, so the next
        # reader does not have to reconstruct it from a test failure.
        self.assertIn("A PLAIN ASSIGNMENT, NOT `readonly`", env)

    def test_an_unwritable_checker_still_reports_every_property(self):
        """A gate that cannot measure reports five failures, not none."""
        source = gate_source()  # noqa: F841 -- indices below need it
        start = source.index("check_dependency_closure() {")
        end = source.index("# THE LINTER", start)
        body = source[start:end].replace("\\\n", "")
        for fragment in self.CLOSURE_CHECKS:
            self.assertIn(fragment, body)

    def test_the_six_declared_libraries_are_the_ones_checked(self):
        with open(os.path.join(TOOLING, "env.sh"),
                  encoding="utf-8") as handle:
            env = handle.read()
        with open(os.path.join(TOOLING, "requirements.txt"),
                  encoding="utf-8") as handle:
            declared_names = [
                line.split("==")[0].strip()
                for line in handle
                if "==" in line and not line.lstrip().startswith("#")
            ]
        self.assertEqual(len(declared_names), 6)
        for name in declared_names:
            self.assertIn('("%s", "' % name, env,
                          msg="%s is declared but not checked" % name)


class TestTheLinterGoesThroughTheVerifier(unittest.TestCase):
    """M-22: nothing is executed before it is verified."""

    def test_every_candidate_is_verified(self):
        source = gate_source()
        start = source.index("verify_flake8_candidate() {")
        end = source.index("# THE TRUST STATE, SPLIT BY", start)
        body = source[start:end]
        self.assertIn("playthrough_verify_executable", body)
        # Four candidates, each routed through the verifier.
        self.assertEqual(body.count("verify_flake8_candidate "), 4)

    def test_verification_precedes_the_version_probe(self):
        source = gate_source()
        start = source.index("resolve_flake8() {")
        end = source.index("# THE TRUST STATE, SPLIT BY", start)
        body = source[start:end]
        for line in body.splitlines():
            if "--version" in line and "verify_flake8_candidate" in line:
                self.assertLess(line.index("verify_flake8_candidate"),
                                line.index("--version"))
        # The override's own branch pairs them in that order.
        self.assertRegex(
            body,
            r"verify_flake8_candidate \"\$\{PLAYTHROUGH_FLAKE8\}\""
            r"[\s\S]{0,200}?--version")

    def test_a_refusal_is_reported_rather_than_swallowed(self):
        self.assertIn("FLAKE8_REJECTED", gate_source())
        self.assertIn("An override is not a way round verification",
                      joined_source())


class TestEveryCommandIsResolvedAndCalled(unittest.TestCase):
    """M-25: the inventory is the invoked set, exactly, both ways."""

    # The commands the gate binds to a verified path.
    def tool_variables(self):
        source = gate_source()
        block = source[source.index('FFPROBE="ffprobe"'):
                       source.index("PYTHON=\"${PLAYTHROUGH_PYTHON}\"")]
        return re.findall(r"^([A-Z][A-Z0-9_]*)=\"", block,
                          re.MULTILINE)

    def test_the_declared_list_matches_the_bound_variables(self):
        source = gate_source()
        match = re.search(
            r'readonly REQUIRED_COMMANDS="((?:[^"\\]|\\\n)*)"', source)
        self.assertIsNotNone(match)
        declared_commands = match.group(1).replace("\\\n", " ").split()
        expected = [name.lower().replace("_", "-")
                    for name in self.tool_variables()]
        self.assertEqual(
            sorted(declared_commands), sorted(expected),
            msg="REQUIRED_COMMANDS and the tool variables must be the "
                "same set: a declared command the gate never runs makes "
                "an operator install something for nothing, and an "
                "invoked command that is not declared is unverified")

    def test_every_tool_variable_is_actually_invoked(self):
        """ShellCheck reports the other direction as SC2034."""
        source = gate_source()
        for name in self.tool_variables():
            self.assertIn(
                '"${%s}"' % name, source,
                msg="%s is bound but never invoked, so the gate "
                    "verifies a command it does not use" % name)

    def test_the_resolution_precedes_the_scratch_directory(self):
        """The order of the CALLS in main(), not of anything else.

        Comments are stripped and the definitions above main() are
        excluded, so the assertion is about what runs first rather than
        about where a word happens to appear.
        """
        source = gate_source()
        body = source[source.index("\nmain() {"):]
        body = body[:body.index("\n    group_environment")]
        calls = [line.strip() for line in body.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        self.assertIn("resolve_tools", calls)
        self.assertIn("open_scratch", calls)
        self.assertLess(calls.index("resolve_tools"),
                        calls.index("open_scratch"),
                        msg="open_scratch is built out of mktemp and "
                            "chmod, so resolving after it leaves two of "
                            "the gate's own tools unverified")

    def test_the_bootstrap_needs_no_external_command(self):
        """Nothing runs before the file that verifies the tools is found.

        The subject is the block from the top of the file to the line
        that releases the bootstrap's own variables, which is where env.sh
        has been sourced and every tool is resolvable.  It is located by
        that line rather than by a byte offset, because a header that
        grows would otherwise silently move the assertion off its
        subject.
        """
        source = gate_source()
        end = source.index("unset _va_script_dir _va_env_file")
        bootstrap = source[:end]
        self.assertIn("${BASH_SOURCE[0]%/*}", bootstrap)
        self.assertNotIn("$(dirname", bootstrap)


class TestToolDiagnosticsReachTheReport(unittest.TestCase):
    """M-17: a tool that explained itself is quoted, briefly."""

    MEDIA_TOOLS = ("FFPROBE", "FFMPEG", "CONVERT", "IDENTIFY")

    def test_no_media_helper_discards_its_stderr(self):
        source = gate_source()
        for name in self.MEDIA_TOOLS:
            for line_number, line in enumerate(source.splitlines(), 1):
                if '"${%s}"' % name not in line:
                    continue
                self.assertNotIn(
                    "2>/dev/null", line,
                    msg="line %d discards %s's explanation"
                        % (line_number, name))

    def test_the_reason_is_read_from_the_file_not_a_variable(self):
        """Every helper runs inside $( ), which is a subshell.

        A variable assigned in there is discarded when the substitution
        closes, so a reason kept in one would be empty at every call
        site -- the exact silence this fix exists to end, one layer down.
        """
        source = gate_source()
        self.assertNotIn("LAST_TOOL_ERROR", source)
        self.assertTrue(defines("because"))
        self.assertTrue(defines("tool_error_file"))
        start = source.index("because() {")
        body = source[start:source.index("# probe_field", start)]
        self.assertIn("tool_error_file", body)

    def test_the_quoted_reason_is_bounded(self):
        source = gate_source()
        start = source.index("because() {")
        body = source[start:source.index("# probe_field", start)]
        self.assertIn("-n 2", body)
        self.assertIn("-c 1-200", body)

    def test_failing_verdicts_actually_quote_it(self):
        source = gate_source()
        self.assertGreaterEqual(
            source.count("$(because "), 12,
            msg="the failures that consume a helper must carry its "
                "reason, or the report says 'observed: <nothing>' for a "
                "missing file, a bad container and a permission error "
                "alike")


class TestTheReportIsDurable(unittest.TestCase):
    """M-19: the verdicts survive the terminal they were printed at."""

    def test_every_report_emitter_goes_through_say(self):
        source = gate_source()
        for emitter in ("note()", "group()", "record_pass()",
                        "record_fail()", "record_info()",
                        "record_warn()"):
            start = source.index(emitter)
            body = source[start:start + 400]
            self.assertIn("say ", body,
                          msg="%s must be captured, not only printed"
                              % emitter)

    def test_the_capture_starts_with_the_scratch_directory(self):
        source = gate_source()
        start = source.index("open_scratch() {")
        body = source[start:source.index("publish_report()", start)]
        self.assertIn("REPORT_FILE=", body)

    def test_only_a_passing_full_run_publishes(self):
        source = gate_source()
        start = source.index("report_publication_target() {")
        body = source[start:source.index("# measured_commit", start)]
        self.assertIn('[ "${FAILURES}" -ne 0 ]', body)
        self.assertIn("tracking_phase", body)

    def test_a_failing_run_removes_a_stale_report(self):
        source = gate_source()
        start = source.index("publish_report() {")
        end = source.index("report_publication_target()", start)
        body = source[start:end].replace("\\\n", "")
        self.assertIn("removed the stale acceptance report", body)

    def test_the_machine_block_names_the_published_report(self):
        self.assertIn("note VERIFY_REPORT", gate_source())

    def test_nothing_in_the_report_is_a_wall_clock(self):
        """A committed report that changes every run is churn.

        Worse, it would make a second verify before a commit fail its
        own "nothing left uncommitted" check on a file the gate had just
        rewritten.  The commit being measured is stable and is better
        evidence than the time it was measured at.
        """
        source = gate_source()
        self.assertTrue(defines("measured_commit"))
        self.assertNotIn("report_stamp", source)
        self.assertIn("rev-parse --short=10 HEAD", source)
        # unittest prints its own elapsed seconds; they are stripped.
        self.assertIn("s/ in [0-9]+\\.[0-9]+s$//", source)


class TestRunningThisSuiteDoesNotDisturbTheTree(GateInvocation):
    """The gate's one side effect, kept off the real repository.

    `publish_report` removes a stale acceptance report when a run fails.
    That is correct for an operator and destructive for a test suite that
    runs the real script from the real repository root: before this
    guard, `-k LintCheck` reported four tests OK and left
    `D playthrough/acceptance-report.txt` behind, so running the tests
    silently deleted a committed artifact.
    """

    def test_a_failing_run_leaves_the_committed_report_intact(self):
        before = self.report_bytes()
        if before is None:
            self.skipTest("no acceptance report has been published yet")
        status, _, _ = self.run_gate("--phase", "postcommit")
        self.assertNotEqual(status, 0, msg="that phase must be refused")
        self.assertEqual(self.report_bytes(), before)

    def test_the_harness_names_the_file_it_protects(self):
        """A rename of the artifact must not silently disable this."""
        self.assertTrue(self.REPORT.endswith("acceptance-report.txt"))
        source = gate_source()
        self.assertIn('REPORT_BASENAME="acceptance-report.txt"', source)


class TestTheReportCarriesNoTrailingWhitespace(unittest.TestCase):
    """N-06, applied to the artifact the gate itself writes.

    Verdicts routinely quote a tool's own output with its newlines
    collapsed to spaces, which leaves a trailing space. Invisible on a
    terminal; very visible in a COMMITTED file, where `git diff --check`
    reported playthrough/acceptance-report.txt on three lines -- one of
    them the linter's own version banner.
    """

    REPORT = os.path.join(PLAYTHROUGH, "acceptance-report.txt")

    def test_the_trim_is_at_the_single_point_every_line_passes(self):
        source = gate_source()
        start = source.index("say() {")
        body = source[start:source.index("note() {", start)]
        self.assertIn('line="$(printf "${format}" "$@")"', body)
        self.assertIn('line="${line%"${line##*[![:space:]]}"}"', body)
        # And the untrimmed direct emission is gone.
        self.assertNotIn('    printf "${format}" "$@"\n', body)

    def test_the_committed_report_has_no_trailing_whitespace(self):
        if not os.path.isfile(self.REPORT):
            self.skipTest("no acceptance report has been published yet")
        with open(self.REPORT, encoding="utf-8") as handle:
            offenders = [number
                         for number, line in enumerate(handle, 1)
                         if line.rstrip("\n") != line.rstrip()]
        self.assertEqual(offenders, [],
                         msg="git diff --check reports these lines")


class TestTheInventoryIsExactPerGroup(unittest.TestCase):
    """N-03: extra verdicts in one group cannot pay for a missing one."""

    def test_the_comparison_is_per_group(self):
        source = gate_source()
        start = source.index("check_check_inventory() {")
        body = source[start:source.index("group_inventory() {", start)]
        self.assertIn("GROUP_CHECKS_ALL[index]", body)
        self.assertIn("GROUP_CHECKS_PRE_COMMIT[index]", body)

    def test_the_table_is_chosen_by_the_phase_and_not_by_a_predicate(self):
        """THREE PHASES, THREE TABLES, AND THE DEFECT WAS TWO.

        The selection used to be `if tracking_phase`, which is true for
        `all` AND for `post-commit` because it means "this phase measures
        the history" -- so the post-commit phase compared its own 31
        verdicts against the whole audit's 120 and failed its own
        inventory while performing exactly what it declared.
        """
        source = gate_source()
        start = source.index("check_check_inventory() {")
        body = source[start:source.index("group_inventory() {", start)]
        self.assertIn("GROUP_CHECKS_POST_COMMIT[index]", body)
        self.assertIn('case "${PHASE}" in', body)
        self.assertNotIn("if tracking_phase; then", body)

    def test_a_group_is_numbered_for_itself_not_for_its_turn(self):
        """The number is the group's identity, in every phase.

        register_check files a verdict under ${GROUP} and the inventory
        reads those files back, so a running counter made the ledger mean
        something different in a phase where not every group runs.
        """
        source = gate_source()
        start = source.index("group() {")
        body = source[start:source.index("\n}", start)]
        self.assertIn('GROUP="$1"', body)
        self.assertNotIn("GROUP + 1", body)
        # Every group opens under its own number, in order, once.
        numbers = [int(number) for number in
                   re.findall(r"^    group (\d+) \"", source,
                              re.MULTILINE)]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        declared = re.search(r"^readonly GROUP_COUNT=(\d+)$", source,
                             re.MULTILINE)
        self.assertTrue(declared, msg="GROUP_COUNT is not declared")
        self.assertEqual(len(numbers), int(declared.group(1)))

    def test_both_directions_are_reported(self):
        source = gate_source()
        start = source.index("check_check_inventory() {")
        body = source[start:source.index("group_inventory() {", start)]
        self.assertIn("SHORT", body)
        self.assertIn("UNDECLARED", body)

    def test_the_guard_is_no_longer_at_least(self):
        source = gate_source()
        start = source.index("check_check_inventory() {")
        body = source[start:source.index("group_inventory() {", start)]
        self.assertNotIn("-ge", body,
                         msg="'at least' is the guard that let extra "
                             "verdicts settle another group's debt")

    def test_distinct_names_are_what_is_counted(self):
        """Per-item repetition must not inflate the count."""
        source = gate_source()
        self.assertTrue(defines("distinct_checks_in"))
        start = source.index("distinct_checks_in() {")
        body = source[start:start + 400]
        self.assertIn("-u", body)

    def test_repetition_is_reported_rather_than_merely_tolerated(self):
        self.assertTrue(defines("repeated_checks_in"))
        self.assertIn("checks that reported more than once",
                      gate_source())

    def test_only_verdicts_register_a_check(self):
        """INFO and WARN are notes, not judgements, and do not count."""
        source = gate_source()
        for emitter, expected in (("record_pass()", True),
                                  ("record_fail()", True),
                                  ("record_info()", False),
                                  ("record_warn()", False)):
            start = source.index(emitter)
            body = source[start:start + 320]
            self.assertEqual("register_check" in body, expected,
                             msg="%s registers a check: %s"
                                 % (emitter, expected))


class TestTheFrameGeometryCheckIsReachable(unittest.TestCase):
    """I-01: the function had no caller at all (ShellCheck SC2317)."""

    def test_it_has_a_caller(self):
        source = gate_source()
        self.assertTrue(defines("check_frame_geometry"))
        calls = []
        for line in source.splitlines():
            if "check_frame_geometry" not in line:
                continue
            if line.lstrip().startswith("#"):
                continue
            if "check_frame_geometry()" in line:
                continue
            calls.append(line)
        self.assertTrue(calls, msg="integrated or removed, not orphaned")

    def test_it_is_called_where_a_frame_is_already_being_read(self):
        source = gate_source()
        start = source.index("check_one_frame_luminance() {")
        end = source.index("check_frame_geometry() {", start)
        body = source[start:end]
        self.assertIn("check_frame_geometry", body)

    def test_shellcheck_no_longer_reports_it_unreachable(self):
        result = subprocess.run(
            ["shellcheck", "-x", "-s", "bash", GATE],
            cwd=TOOLING, capture_output=True, timeout=300)
        report = result.stdout.decode("utf-8", "replace")
        self.assertNotIn("check_frame_geometry", report)


class TestADeathEndingLeavesNoLiveWorld(unittest.TestCase):
    """The save checks accept the shape the engine leaves after a death.

    Death is a sanctioned ending, and when the survivor who died was the
    world's only character `turn_handler::cleanup_at_end()`
    (src/do_turn.cpp:111-207) RENAMES the character save into
    `<userdir>/graveyard/<timestamp>/` and then clears the world,
    because WORLD_END defaults to "reset" (src/options.cpp:2836-2841)
    and `delete_world(name, false)` (src/worldfactory.cpp:2458-2496)
    keeps only worldoptions.json, mods.json and *.dict.  So there is no
    master.gsav and no live `#<b64>.sav` to find, and a gate that
    demanded either in the index would fail every correct death ending.

    What must NOT weaken is the property the group exists for: `git add`
    skipping an ignored save and exiting 0.  These tests hold both ends
    -- the death shape is accepted, and it is only accepted with the
    evidence that distinguishes it from a save git never added.
    """

    def helpers(self):
        return ("graveyard_save_paths", "graveyard_saves_on_disk",
                "world_end_value", "history_master_commit")

    def body(self):
        source = joined_source()
        start = source.index("check_save_tracked() {")
        end = source.index("deciding_ignore_pattern() {", start)
        return source[start:end]

    def test_every_helper_the_death_shape_needs_exists(self):
        for helper in self.helpers():
            self.assertTrue(defines(helper),
                            msg="verify_artifacts.sh defines no %s"
                                % helper)

    def test_the_death_shape_needs_all_three_of_its_parts(self):
        """One part alone must not buy the pass."""
        body = self.body()
        start = body.index('world_end="$(world_end_value')
        conjunction = body[start:body.index("record_pass", start)]
        self.assertIn('carrier="$(history_master_commit)"', conjunction)
        self.assertIn('[ -n "${carrier}" ]', conjunction)
        self.assertIn('[ "${buried:-0}" -ge 1 ]', conjunction)
        self.assertIn('[ "${world_end}" = "reset" ]', conjunction)
        self.assertIn('[ "${world_end}" = "delete" ]', conjunction)
        # An AND of the three, never an OR between them.
        self.assertIn("&&", conjunction)

    def test_a_save_git_never_added_still_fails(self):
        """The silent failure this group exists for is still caught.

        With the save ignored, no commit carries a master.gsav and no
        graveyard save is tracked, so `carrier` is empty, the death
        branch is unreachable, and the verdict is a failure that says
        so.
        """
        body = self.body()
        self.assertIn("record_fail", body)
        marker = body.index("no commit reachable from HEAD carries one")
        self.assertIn("a save git never added looks like",
                      body[marker:marker + 200])

    def test_history_reads_the_tree_and_not_the_diff(self):
        """A commit that DELETED the file also touches its path."""
        source = joined_source()
        start = source.index("history_master_commit() {")
        end = source.index("check_save_tracked() {", start)
        body = source[start:end]
        self.assertIn("rev-list HEAD", body)
        self.assertIn("ls-tree -r --name-only", body)

    def test_the_buried_save_satisfies_the_survivor_check(self):
        body = self.body()
        start = body.index("the survivor's own save file is tracked")
        tail = body[start:]
        self.assertIn('elif [ "${buried:-0}" -ge 1 ]', tail)
        self.assertIn("move_save_to_graveyard RENAMED them", tail)

    def test_the_buried_save_is_still_held_to_the_ignore_rule(self):
        """The leading '#' moves with the file, so \\#* still applies."""
        body = self.body()
        start = body.index("the survivor's own save file is tracked")
        self.assertIn("subject to .gitignore's", body[start:])
        # And it is one of the paths the ignore sample is taken over.
        source = joined_source()
        start = source.index("check_nothing_ignored() {")
        end = source.index("check_every_class_tracked() {", start)
        self.assertIn("graveyard_saves_on_disk", source[start:end])

    def test_no_check_was_added_to_pay_for_this(self):
        """Both verdicts were taught a second shape, not duplicated.

        check_save_tracked reports THREE properties -- the world save,
        the survivor save and the world options -- so it takes three
        failure paths, and five success paths, because two of the three
        have a second legitimate shape.  A fourth failure path or a
        fourth verdict NAME would mean a check had been added, which
        group 7's declared count would then be short by one.
        """
        deferred = sum(count for name, count in DEFERRED_CHECKS
                       if name != "check_change_surface")
        self.assertEqual(
            group_table("GROUP_CHECKS_PRE_COMMIT")[7], 4,
            msg="four of group 7's checks are properties of the tree "
                "and run in both phases")
        self.assertEqual(
            group_table("GROUP_CHECKS_ALL")[7], 4 + deferred,
            msg="group 7 declares its four unconditional checks plus "
                "every deferred one, and nothing else")
        self.assertEqual(self.body().count("record_fail"), 3)
        self.assertEqual(self.body().count("record_pass"), 5)


class TestTheWorldEndReaderIsExercised(unittest.TestCase):
    """The WORLD_END reader, run rather than only read.

    worldoptions.json is a LIST of option records, so the value is found
    by name; and the reader has to be as clear about "absent" as about
    "reset", because absence means the engine default was in force and
    the caller decides a verdict on the difference.
    """

    def reader(self):
        match = re.search(
            r"^readonly WORLDOPTIONS_STDIN_READER='\n(.*?)\n'$",
            gate_source(), re.DOTALL | re.MULTILINE)
        if match is None:
            raise AssertionError(
                "verify_artifacts.sh declares no WORLDOPTIONS reader")
        return match.group(1)

    def read(self, document):
        completed = subprocess.run(
            [sys.executable, "-B", "-c", self.reader()],
            input=document, capture_output=True, text=True, check=False)
        return completed.returncode, completed.stdout

    def test_the_value_is_found_by_name(self):
        status, value = self.read(json.dumps([
            {"name": "SEASON_LENGTH", "value": "91"},
            {"name": "WORLD_END", "value": "reset"},
        ]))
        self.assertEqual((status, value), (0, "reset"))

    def test_a_world_that_is_kept_reads_as_kept(self):
        status, value = self.read(json.dumps(
            [{"name": "WORLD_END", "value": "keep"}]))
        self.assertEqual((status, value), (0, "keep"))

    def test_an_absent_override_is_reported_as_unreadable(self):
        status, value = self.read(json.dumps(
            [{"name": "SEASON_LENGTH", "value": "91"}]))
        self.assertEqual(status, 1)
        self.assertEqual(value, "")

    def test_a_document_of_the_wrong_shape_is_refused(self):
        status, _ = self.read(json.dumps({"WORLD_END": "reset"}))
        self.assertEqual(status, 1)

    def test_an_empty_value_is_refused_rather_than_returned(self):
        status, value = self.read(json.dumps(
            [{"name": "WORLD_END", "value": ""}]))
        self.assertEqual(status, 1)
        self.assertEqual(value, "")

    def test_the_committed_world_options_read_back(self):
        """The real file this session produced, if it is there."""
        path = os.path.join(
            REPO_ROOT, "playthrough", "userdir", "save")
        if not os.path.isdir(path):
            self.skipTest("no world has been played in this checkout")
        found = []
        for world in sorted(os.listdir(path)):
            candidate = os.path.join(path, world, "worldoptions.json")
            if os.path.isfile(candidate):
                found.append(candidate)
        if not found:
            self.skipTest("no worldoptions.json has been written")
        with open(found[0], encoding="utf-8") as handle:
            status, value = self.read(handle.read())
        self.assertEqual(status, 0)
        self.assertIn(value, ("reset", "delete", "query", "keep"))


class TestTheFileEndsCleanly(unittest.TestCase):
    """N-06: no trailing whitespace, and exactly one closing newline."""

    def test_exactly_one_trailing_newline(self):
        with open(GATE, encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"),
                         msg="git diff --check reports the extra blank")

    def test_no_line_carries_trailing_whitespace(self):
        with open(GATE, encoding="utf-8") as handle:
            offenders = [number
                         for number, line in enumerate(handle, 1)
                         if line.rstrip("\n") != line.rstrip()]
        self.assertEqual(offenders, [])


# ---------------------------------------------------------------------
# THE EMBEDDED CHECKERS, RUN DIRECTLY
#
# Most of this gate's judgement lives in the Python programs it emits
# through `emit_checker`, and until now nothing exercised them: the
# suite asked what the source says and what the CLI accepts, both of
# which a broken checker passes.  The four properties this section
# covers were each a real defect -- a provenance verdict that claimed
# three attestations after reading one, an empty transition manifest
# read as a missing file, a rationale verdict satisfied by "Swing.",
# and two transcripts compared only by their timestamps -- so each is
# held here to the input that used to fool it.
#
# The checkers are extracted from the heredoc and executed in a fresh
# namespace whose __name__ is NOT "__main__", so the module-level guard
# does not fire and nothing is measured except what a test asks for.
# Their verdicts go to stdout as SEP-joined records, which is the same
# contract run_checker consumes, so parsing them here tests the
# published interface rather than an internal.
# ---------------------------------------------------------------------

SEP = "\x1f"


def load_checker(label):
    """Return the named embedded checker as an executed module."""
    import types

    source = gate_source()
    marker = "emit_checker %s <<'PY'\n" % label
    if marker not in source:
        raise AssertionError("verify_artifacts.sh emits no %s checker"
                             % label)
    start = source.index(marker) + len(marker)
    end = source.index("\nPY\n", start)
    module = types.ModuleType("gate_checker_%s" % label)
    code = compile(source[start:end], "<%s checker>" % label, "exec")
    exec(code, module.__dict__)                       # noqa: S102
    return module


class CheckerCase(unittest.TestCase):
    """Run one checker function and read the verdicts it printed."""

    LABEL = ""

    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker(cls.LABEL)

    def verdicts(self, call):
        """Every verdict `call` prints, as (kind, name, observed)."""
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            call()
        found = []
        for line in buffer.getvalue().splitlines():
            fields = line.split(SEP)
            if len(fields) >= 3:
                found.append((fields[0], fields[1], fields[2]))
        return found

    def only(self, call, name):
        """The one verdict named `name`; fails when there is not one."""
        matching = [v for v in self.verdicts(call) if v[1] == name]
        self.assertEqual(len(matching), 1,
                         msg="expected exactly one %r verdict, got %r"
                             % (name, matching))
        return matching[0]


class TestTheRationaleContract(CheckerCase):
    """"Swing." is not a reason, and the gate has to say so.

    TWO CHANNELS, AND WHICH PROPERTY GOES DOWN WHICH ONE.  The verdict
    FAILS when an entry carries no word beyond the key that produced it,
    or does not close as a sentence -- both decidable whichever field the
    survivor wrote in.  A single-word entry and a sentence repeated
    inside the window are REPORTED, with every frame number, because a
    program cannot tell a one-word reason from a one-word placeholder:
    "West." on the eighth step west is a whole thought, and the same word
    standing in for a reason nobody wrote is a shortfall.  The check's
    own PASS text has always disclaimed deciding that, and measuring the
    contract against a record whose action notes are written in the
    survivor's voice is what showed the per-entry refusal reporting
    entries that plainly do give a reason.

    The narration is read as the UNION of the action's note and the
    commentary, which is what a reader of the record gets.
    """

    LABEL = "record"
    NAME = "no entry is only the key that produced it"
    SHORTFALL = ("entries whose narration is a single word or repeats "
                 "the one before it")

    def write_record(self, pairs):
        """A manifest file from (action, commentary) pairs."""
        import json

        path = os.path.join(self.tmp, "manifest.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            for index, (action, commentary) in enumerate(pairs, start=1):
                handle.write(json.dumps({
                    "frame": index,
                    "file": "playthrough/frames/frame_%05d.png" % index,
                    "real_ts": "2026-08-10T00:00:0%dZ" % (index % 10),
                    "ingame_clock": None,
                    "action": action,
                    "commentary": commentary,
                }) + "\n")
        return path

    def call(self, pairs, timeline=None):
        record = self.write_record(pairs)
        path = timeline or os.path.join(self.tmp, "absent.json")
        return lambda: self.checker.check_rationale(record, path)

    def judge(self, pairs, timeline=None):
        return self.only(self.call(pairs, timeline), self.NAME)

    def reported(self, pairs, timeline=None):
        """The shortfall verdict, when there is one."""
        found = [v for v in self.verdicts(self.call(pairs, timeline))
                 if v[1] == self.SHORTFALL]
        return found[0] if found else None

    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="blitzy_gate_")
        self.addCleanup(__import__("shutil").rmtree, self.tmp,
                        ignore_errors=True)

    def test_an_entry_that_is_only_its_own_key_is_refused(self):
        """The one shape that accounts for nothing in either field."""
        kind, _, observed = self.judge([("press 'w'", "W.")])
        self.assertEqual(kind, "FAIL")
        self.assertIn("the key and nothing else", observed)

    def test_the_reviewed_label_is_reported_with_its_frame(self):
        """"Swing." beside `press '2' -- swing` cannot pass unnamed.

        It is not a refusal, because the same shape is "West." on the
        eighth step west -- see this class's own docstring -- but it is
        counted and named, which is what the review asked for and what
        being satisfied by non-emptiness alone never gave.
        """
        kind, _, observed = self.judge([("press '2' -- swing",
                                         "Swing.")])
        self.assertEqual(kind, "PASS", msg=observed)
        shortfall = self.reported([("press '2' -- swing", "Swing.")])
        self.assertIsNotNone(shortfall,
                             msg="the label was neither failed nor "
                                 "reported, which is the defect the "
                                 "review found")
        self.assertEqual(shortfall[0], "WARN")
        self.assertIn("1 single-word entr(ies)", shortfall[2])
        self.assertIn("'Swing.'", shortfall[2])

    def test_a_one_word_label_is_reported(self):
        """A one-word note and a one-word echo of it, which is the
        shape the shipped record carries fourteen times."""
        shortfall = self.reported([("press 'Left' -- west", "West.")])
        self.assertIsNotNone(shortfall)
        self.assertIn("'West.'", shortfall[2])

    def test_a_one_word_echo_of_a_full_note_is_not_reported(self):
        """The union is what a reader gets, and it is a sentence."""
        pairs = [("press 'M' -- begin spelling my trade", "Mail.")]
        kind, _, observed = self.judge(pairs)
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIsNone(self.reported(pairs))

    def test_a_transcribed_keystroke_is_not_reported_as_a_label(self):
        """Spelling a word into a filter is a transcription.

        One character per frame is what the engine's own search field
        forces, and the reason for the run belongs to the entry that
        opens it -- so these are counted as their own class rather than
        reported as one-word reasons.
        """
        pairs = [("press 'm' -- begin spelling the start I want", "M."),
                 ("press 'i' -- continue spelling it", "I.")]
        kind, _, observed = self.judge(pairs)
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIn("2 of them a single character transcribed",
                      observed)
        self.assertIsNone(self.reported(pairs))

    def test_an_unclosed_fragment_is_refused(self):
        kind, _, observed = self.judge(
            [("press '6' -- east", "Out through the kitchen and away")])
        self.assertEqual(kind, "FAIL")
        self.assertIn("does not close as a sentence", observed)

    def test_the_same_sentence_twice_running_is_reported(self):
        """One sentence over four keystrokes explains at most one."""
        line = "He has my leg, so I pull until something gives."
        pairs = [("press '8' -- pull", line), ("press '8' -- pull", line)]
        kind, _, observed = self.judge(pairs)
        self.assertEqual(kind, "PASS", msg=observed)
        shortfall = self.reported(pairs)
        self.assertIsNotNone(shortfall)
        self.assertEqual(shortfall[0], "WARN")
        self.assertIn("1 entr(ies) repeating a sentence", shortfall[2])

    def test_a_note_in_the_survivors_voice_is_not_an_offence(self):
        """The false positive that the union framing removes.

        Measured on the shipped record, the per-commentary reading
        reported 37 entries like this one -- a full sentence in the note
        and the same sentence as the commentary -- as restating the
        keystroke.  The reason is in both fields; it is not absent.
        """
        pairs = [("press 'Up' -- north one step, there is a back door "
                  "in this wall",
                  "North one step. There is a back door in this wall.")]
        kind, _, observed = self.judge(pairs)
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIsNone(self.reported(pairs))

    def test_distinct_reasoned_sentences_pass_and_are_not_reported(self):
        pairs = [
            ("press '8' -- pull",
             "He has my leg, so I pull until something gives."),
            ("press '8' -- pull",
             "Nothing gave, and the only other way out is the wall."),
        ]
        kind, _, observed = self.judge(pairs)
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIn("2 entr(ies) measured", observed)
        self.assertIsNone(self.reported(pairs))

    def test_it_does_not_claim_the_reason_was_verified(self):
        """The half no program can decide is named, not implied."""
        _, _, observed = self.judge([
            ("press '8' -- pull",
             "He has my leg, so I pull until something gives."),
        ])
        self.assertIn("not machine-decidable", observed)

    def test_the_ledger_corrected_sentence_is_the_one_judged(self):
        """A row corrected in the ledger must not read as broken.

        The record is append-only, so the repaired sentence lives in
        the timeline, and judging the raw row would report a correction
        as an offence for as long as the record exists.
        """
        import json

        timeline = os.path.join(self.tmp, "timeline.json")
        with open(timeline, "w", encoding="utf-8") as handle:
            json.dump({"frames": [{
                "frame": 1, "action": "press '2' -- swing",
                "commentary": "He is in the only doorway, so I swing.",
            }]}, handle)
        kind, _, observed = self.judge([("press '2' -- swing",
                                         "Swing.")], timeline)
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIn("amendments.jsonl applied", observed)


class TestTheProvenanceBlocksAreAllRequired(CheckerCase):
    """A shrinking attestation must not read as a passing one."""

    LABEL = "timeline"
    NAME = ("the timeline names the artifacts it was computed from, "
            "and they still hash to what it recorded")
    # How many entries the document under test describes.  It is a real
    # count rather than a placeholder because check_provenance also
    # reports on the digest sidecar's own arithmetic, and a verdict that
    # names the entry count has to be given one.
    ENTRY_COUNT = 3

    def setUp(self):
        import hashlib
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="blitzy_gate_")
        self.addCleanup(__import__("shutil").rmtree, self.tmp,
                        ignore_errors=True)
        self.blocks = {}
        for name, rows in (("manifest", 3), ("amendments", 1),
                           ("captures", 3)):
            path = os.path.join(self.tmp, "%s.jsonl" % name)
            payload = "".join("{\"row\": %d}\n" % n
                              for n in range(1, rows + 1))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(payload)
            self.blocks[name] = {
                "path": path,
                "sha256": hashlib.sha256(
                    payload.encode("utf-8")).hexdigest(),
                "rows": rows,
            }

    def judge(self, document):
        """The provenance verdict alone, out of everything it prints.

        check_provenance also sweeps the capture digests and publishes
        what it hashed to a shared inventory, so it is given a path to
        write that to inside this test's own directory; those verdicts
        carry other names and `only()` selects past them.
        """
        inventory = os.path.join(self.tmp, "digest-inventory")
        return self.only(
            lambda: self.checker.check_provenance(
                document, self.ENTRY_COUNT, inventory),
            self.NAME)

    def test_all_three_blocks_present_and_counted_pass(self):
        kind, _, observed = self.judge(dict(self.blocks))
        self.assertEqual(kind, "PASS", msg=observed)
        for name in ("manifest", "amendments", "captures"):
            self.assertIn(name, observed)

    def test_a_missing_block_is_refused(self):
        """The defect: one block read, three claimed as verified."""
        document = dict(self.blocks)
        del document["amendments"]
        kind, _, observed = self.judge(document)
        self.assertEqual(kind, "FAIL")
        self.assertIn("amendments declares no attestation block",
                      observed)

    def test_a_declared_row_count_that_is_not_the_file_s_is_refused(self):
        document = dict(self.blocks)
        document["captures"] = dict(document["captures"], rows=99)
        kind, _, observed = self.judge(document)
        self.assertEqual(kind, "FAIL")
        self.assertIn("the timeline declares 99", observed)

    def test_a_document_declaring_nothing_is_refused(self):
        kind, _, observed = self.judge({})
        self.assertEqual(kind, "FAIL")
        for name in ("manifest", "amendments", "captures"):
            self.assertIn(name, observed)


class TestAnEmptyTransitionManifestIsAReading(CheckerCase):
    """No frame over the ceiling is a valid session, not a fault."""

    LABEL = "render"
    NAME = ("every materialised transition image is the one "
            "make_transitions composed")

    def setUp(self):
        import tempfile

        self.directory = tempfile.mkdtemp(prefix="blitzy_gate_")
        self.addCleanup(__import__("shutil").rmtree, self.directory,
                        ignore_errors=True)

    def judge(self, document, flagged=(), transitions=None):
        """The transition verdict, with a memo of its own.

        The digest of each image comes from the shared memo the render
        checker builds, so one is constructed here with no inventory and
        no sidecar behind it: nothing in this test has been hashed
        elsewhere, which is exactly the state the memo is written to
        handle.
        """
        digests = self.checker.Digests(None, None)
        return self.only(
            lambda: self.checker.check_transition_provenance(
                document, self.directory, transitions or {},
                list(flagged), 12, digests),
            self.NAME)

    def test_no_flags_no_groups_and_no_images_pass(self):
        kind, _, observed = self.judge({"groups": []})
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIn("no frame's clock delta passed the ceiling",
                      observed)

    def test_no_groups_against_a_flag_is_refused(self):
        kind, _, observed = self.judge({"groups": []}, flagged=(139,))
        self.assertEqual(kind, "FAIL")
        self.assertIn("1 flagged frame(s)", observed)

    def test_no_groups_with_an_image_on_disk_is_refused(self):
        with open(os.path.join(self.directory, "trans_00001_00.png"),
                  "wb") as handle:
            handle.write(b"\x89PNG")
        kind, _, observed = self.judge({"groups": []})
        self.assertEqual(kind, "FAIL")
        self.assertIn("1 file(s)", observed)

    def test_a_document_without_the_key_is_still_a_missing_manifest(self):
        kind, _, observed = self.judge({})
        self.assertEqual(kind, "FAIL")
        self.assertIn("no transition manifest could be read", observed)


class TestTheTwoTranscriptsAreComparedByTheirWords(CheckerCase):
    """Equal timestamps over different sentences used to pass."""

    LABEL = "caption"
    NAME = "the readable record's sentences are the caption track's"

    ENTRIES = ({"cue_start": 0.0, "cue_end": 0.25,
                "commentary": "He is in the only doorway I have, so I "
                              "swing at him again."},)

    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="blitzy_gate_")
        self.addCleanup(__import__("shutil").rmtree, self.tmp,
                        ignore_errors=True)

    def markdown(self, body):
        path = os.path.join(self.tmp, "transcript.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# A survivor — what I did, and why\n\n"
                         "Timestamps are cumulative video time.\n\n"
                         "**00:00:00,000** %s\n" % body)
        return path

    def cue_index(self, text):
        """The one index record the SRT walk writes for this cue.

        check_cue_file emits one JSON object per cue -- its start, its
        text lines, and the sentence the timeline says that entry carries
        -- in the single walk that has the cue and its timeline entry in
        hand.  check_markdown then reads one line back per entry, so this
        is the artifact the comparison is actually made against, and it
        is written here exactly as the producer writes it.
        """
        sys.path.insert(0, TOOLING)
        import make_srt

        path = os.path.join(self.tmp, "cue-starts")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "start": 0.0,
                "text": make_srt.wrap_cue_text(
                    text, make_srt.CUE_LINE_WIDTH),
                "commentary": self.ENTRIES[0]["commentary"],
            }, ensure_ascii=False) + "\n")
        return path

    def judge(self, body, cue_text=None):
        path = self.markdown(body)
        index = self.cue_index(
            cue_text if cue_text is not None else body)
        return self.only(
            lambda: self.checker.check_markdown(
                path, index, 1, len(self.ENTRIES), TOOLING, 0.002),
            self.NAME)

    def test_the_same_sentence_in_both_files_passes(self):
        kind, _, observed = self.judge(self.ENTRIES[0]["commentary"])
        self.assertEqual(kind, "PASS", msg=observed)
        self.assertIn("wrapped at 42 columns", observed)

    def test_a_markdown_body_the_timeline_does_not_carry_is_refused(self):
        kind, _, observed = self.judge("Swing.")
        self.assertEqual(kind, "FAIL")
        self.assertIn("the timeline records", observed)

    def test_a_cue_carrying_another_sentence_is_refused(self):
        kind, _, observed = self.judge(
            self.ENTRIES[0]["commentary"],
            cue_text="I swing at him again, and again nothing.")
        self.assertEqual(kind, "FAIL")
        self.assertIn("the entry wraps to", observed)


class TestTheIdentityIsTheRepositorysOwn(unittest.TestCase):
    """A global identity satisfies git and not the requirement."""

    def body(self, name):
        """The source of one shell function, definition to closing }."""
        source = gate_source()
        start = source.index("\n%s() {\n" % name)
        end = source.index("\n}\n", start)
        return source[start:end]

    def test_the_check_reads_the_local_scope(self):
        body = self.body("check_git_identity")
        for key in ("user.name", "user.email"):
            self.assertIn("config --local --get %s" % key, body)

    def test_the_pass_path_requires_the_local_values(self):
        """Neither value may be empty, and the report says which was.

        The guard is an array of the unset names rather than a bare
        two-term test, so the failure can name user.name, user.email or
        both -- and the pass path is reachable only when that array is
        empty.
        """
        body = self.body("check_git_identity")
        self.assertIn('[ -n "${name}" ] || missing+=("user.name")', body)
        self.assertIn('[ -n "${email}" ] || missing+=("user.email")',
                      body)
        self.assertIn('if [ "${#missing[@]}" -eq 0 ]; then', body)
        # The failure path is the one reached when the array is not
        # empty, and it reports rather than returning silently.
        self.assertIn("record_fail", body.rsplit("record_pass", 1)[1])

    def test_it_is_compared_against_the_committed_author(self):
        body = self.body("check_git_identity")
        self.assertIn("--format='%an <%ae>'", body)


class TestTheCurrentRecordingMustBeCheckpointed(unittest.TestCase):
    """The superseded pair used to be a WARN, which cannot fail a run."""

    def test_the_divergence_is_a_verdict(self):
        self.assertTrue(defines("check_head_generation_checkpoints"))
        source = gate_source()
        start = source.index("\ncheck_head_generation_checkpoints() {\n")
        end = source.index("\n}\n", start)
        body = source[start:end]
        self.assertIn("record_fail", body)
        self.assertNotIn("record_warn", body)

    def test_the_old_warning_is_gone(self):
        """The exact text that used to carry no consequence."""
        self.assertTrue(
            "the lifecycle checkpoints describe" not in gate_source(),
            msg="the superseded-pair WARN is still in the gate")

    def test_it_is_called_beside_the_anchoring_check(self):
        source = gate_source()
        start = source.index("group_version_control() {")
        end = source.index("\n}\n", start)
        body = source[start:end]
        self.assertIn("check_lifecycle_checkpoints", body)
        self.assertIn("check_head_generation_checkpoints", body)


class TestNoDeadCodeOrLintNoiseIsLeftBehind(unittest.TestCase):
    """Default ShellCheck must exit zero on this file."""

    def test_the_geometry_helper_is_no_longer_unreachable(self):
        """SC2317 was answered by INTEGRATING the helper, not deleting it.

        A capture that is not the full X root is not the frame the
        sidebar crop, the clock region and every duration were computed
        for, so the helper had a check to belong to;
        check_one_frame_luminance is already reading that frame and now
        calls it.  Removing it would have removed the assertion, which is
        the wrong way to silence a lint finding -- so what is asserted
        here is that it is defined AND called.
        """
        source = gate_source()
        self.assertTrue(defines("check_frame_geometry"))
        callers = [line.strip() for line in source.splitlines()
                   if "check_frame_geometry" in line and
                   not line.lstrip().startswith("#") and
                   "check_frame_geometry()" not in line]
        self.assertTrue(
            callers,
            msg="the geometry helper is defined with no caller again")

    def test_every_suppression_is_scoped_and_explained(self):
        """A file-wide disable would hide the next real finding."""
        source = gate_source()
        for code in ("SC2016", "SC2317"):
            self.assertTrue(
                "# shellcheck disable=%s" % code in source,
                msg="no scoped %s suppression is present" % code)
        # A disable directive at the TOP of a file applies to the whole
        # file; `shell=bash` is a dialect declaration and is fine.
        head = source.split("\nset -euo pipefail", 1)[0]
        self.assertTrue(
            "disable=" not in head,
            msg="a suppression sits in the file-wide header")
        self.assertTrue("disable=all" not in source,
                        msg="a blanket suppression is present")

    def test_shellcheck_is_clean_with_no_arguments(self):
        import shutil

        if shutil.which("shellcheck") is None:
            self.skipTest("shellcheck is not installed on this host")
        result = subprocess.run(["shellcheck", GATE],
                                capture_output=True, timeout=300)
        self.assertEqual(
            result.returncode, 0,
            msg=result.stdout.decode("utf-8", "replace"))

    def test_the_file_ends_with_exactly_one_newline(self):
        with open(GATE, "rb") as handle:
            raw = handle.read()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.endswith(b"\n\n"))


# ---------------------------------------------------------------------
# THE SYNTHETIC TREE
#
# Everything above reads the gate; everything below RUNS it, one check at
# a time, over evidence a test wrote and then broke on purpose.
#
# The fakes answer the three measuring tools this gate cannot do
# without.  ffprobe is asked for one entry at a time, so the fake keys
# its answer on the -show_entries spec it was given: a test supplies
# FAKE_PROBE_STREAM_NB_FRAMES for what a container DECLARES, and
# FAKE_PROBE_STREAM_NB_READ_PACKETS for the header-free packet walk.
# The DECODED count comes from ffmpeg rather than from ffprobe -- one
# end-to-end pass reports it through its -progress file -- so the ffmpeg
# fake writes that file from FAKE_FFMPEG_FRAMES, and withholds it to
# model a pass that reported no count at all, which is the ORDINARY case
# under -fps_mode vfr and the reason the packet fallback exists.
# ImageMagick is asked for grayscale statistics and geometry, so the fake
# reads both from a table a test writes -- which is how one capture among
# many is made blank.
#
# NEITHER FAKE PRETENDS TO BE A CODEC.  Nothing here decodes anything;
# what is under test is how the gate JUDGES a reading, and a reading is a
# number.
# ---------------------------------------------------------------------

# ffprobe: one answer per -show_entries spec, looked up by an
# environment name derived from the spec itself.
FAKE_FFPROBE = '''\
#!/bin/bash
set -u
if [ "${1-}" = "-version" ]; then
    printf 'ffprobe version 0.0-fake\\n'
    exit 0
fi
spec=""
previous=""
for argument in "$@"; do
    if [ "${previous}" = "-show_entries" ]; then
        spec="${argument}"
    fi
    previous="${argument}"
done
key="$(printf '%s' "${spec}" | tr -c 'A-Za-z0-9' '_' | tr 'a-z' 'A-Z')"
name="FAKE_PROBE_${key}"
value="${!name-}"
if [ -n "${value}" ]; then
    printf '%s\\n' "${value}"
fi
exit "${FAKE_PROBE_STATUS:-0}"
'''

# ffmpeg: the decode pass AND the frame extractor.  Two jobs, told
# apart by the arguments the gate hands over:
#
#   -progress FILE  the end-to-end pass, which reports how far it got
#                   rather than writing a picture.  The gate reads the
#                   LAST `frame=` line out of FILE and that is the
#                   decoded count, so a test says how many frames came
#                   out through FAKE_FFMPEG_FRAMES and withholds it to
#                   model a pass that reported none.
#   an output path  one extracted frame, written so there is something
#                   for the gate to measure.
#
# FAKE_FFMPEG_STATUS refuses either job, which is how both "no frame
# could be decoded there" and an unusable decode reading are reached.
FAKE_FFMPEG = '''\
#!/bin/bash
set -u
if [ "${1-}" = "-version" ]; then
    printf 'ffmpeg version 0.0-fake\\n'
    exit 0
fi
output=""
progress=""
previous=""
for argument in "$@"; do
    if [ "${previous}" = "-progress" ]; then
        progress="${argument}"
    fi
    previous="${argument}"
    output="${argument}"
done
if [ "${FAKE_FFMPEG_STATUS:-0}" != "0" ]; then
    exit "${FAKE_FFMPEG_STATUS}"
fi
if [ -n "${progress}" ]; then
    if [ -n "${FAKE_FFMPEG_FRAMES:-}" ]; then
        # A real pass writes one block per interval and the gate takes
        # the last frame= line out of them, so more than one block is
        # written here on purpose.
        printf 'frame=1\\nfps=0.00\\nprogress=continue\\n' \\
            >"${progress}"
        printf 'frame=%s\\nfps=0.00\\nprogress=end\\n' \\
            "${FAKE_FFMPEG_FRAMES}" >>"${progress}"
    fi
    exit 0
fi
case "${output}" in
    -*|"") ;;
    *) printf 'an extracted frame, as far as this gate can tell\\n' \\
        >"${output}" ;;
esac
exit 0
'''

# convert: the grayscale reading, and the geometry beside it.  Every
# answer comes from FAKE_IMAGE_TABLE when the file is named there and
# from the four defaults otherwise, so a test can break exactly one
# capture out of a hundred.
FAKE_CONVERT = '''\
#!/bin/bash
set -u
if [ "${1-}" = "--version" ]; then
    printf 'Version: ImageMagick 0.0.0-fake Q16 x86_64\\n'
    exit 0
fi
format=""
declare -a files=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -format)
            format="${2-}"
            shift 2 || shift
            ;;
        -colorspace|-resize|-crop|-depth|-gravity)
            shift 2 || shift
            ;;
        info:|-*)
            shift
            ;;
        *)
            files+=("$1")
            shift
            ;;
    esac
done
reading() {
    local path="$1"
    local field="$2"
    local base
    base="$(basename "${path}")"
    if [ -n "${FAKE_IMAGE_TABLE:-}" ] && [ -f "${FAKE_IMAGE_TABLE}" ]; then
        while IFS='|' read -r name mean std width height; do
            if [ "${name}" = "${base}" ]; then
                case "${field}" in
                    mean) printf '%s' "${mean}"; return 0 ;;
                    std) printf '%s' "${std}"; return 0 ;;
                    width) printf '%s' "${width}"; return 0 ;;
                    height) printf '%s' "${height}"; return 0 ;;
                esac
            fi
        done <"${FAKE_IMAGE_TABLE}"
    fi
    case "${field}" in
        mean) printf '%s' "${FAKE_MEAN:-0.270018}" ;;
        std) printf '%s' "${FAKE_STD:-0.198145}" ;;
        width) printf '%s' "${FAKE_WIDTH:-1920}" ;;
        height) printf '%s' "${FAKE_HEIGHT:-1080}" ;;
    esac
}
if [ "${FAKE_CONVERT_STATUS:-0}" != "0" ]; then
    exit "${FAKE_CONVERT_STATUS}"
fi
for file in "${files[@]}"; do
    if [ ! -f "${file}" ]; then
        printf 'convert-fake: no such file: %s\\n' "${file}" >&2
        exit 1
    fi
    case "${format}" in
        *%w*)
            printf '%s %s %s %s %s\\n' "${file}" \\
                "$(reading "${file}" width)" \\
                "$(reading "${file}" height)" \\
                "$(reading "${file}" mean)" \\
                "$(reading "${file}" std)"
            ;;
        *)
            printf '%s %s' "$(reading "${file}" mean)" \\
                "$(reading "${file}" std)"
            ;;
    esac
done
exit 0
'''

# identify: the geometry alone, in the two spellings the gate asks for.
FAKE_IDENTIFY = '''\
#!/bin/bash
set -u
if [ "${1-}" = "--version" ]; then
    printf 'Version: ImageMagick 0.0.0-fake Q16 x86_64\\n'
    exit 0
fi
format=""
declare -a files=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -format)
            format="${2-}"
            shift 2 || shift
            ;;
        -*)
            shift
            ;;
        *)
            files+=("$1")
            shift
            ;;
    esac
done
width="${FAKE_WIDTH:-1920}"
height="${FAKE_HEIGHT:-1080}"
for file in "${files[@]}"; do
    case "${format}" in
        *x*) printf '%sx%s' "${width}" "${height}" ;;
        *) printf '%s %s' "${width}" "${height}" ;;
    esac
done
exit 0
'''

# compare: resolved by the gate and never asked anything by the checks
# exercised here, but it has to exist for the tool resolution to succeed.
FAKE_COMPARE = '''\
#!/bin/bash
printf 'Version: ImageMagick 0.0.0-fake Q16 x86_64\\n'
exit 0
'''

FAKES = {
    "ffprobe": FAKE_FFPROBE,
    "ffmpeg": FAKE_FFMPEG,
    "convert": FAKE_CONVERT,
    "identify": FAKE_IDENTIFY,
    "compare": FAKE_COMPARE,
}

# The reading a real captured frame gave, quoted by the gate itself as
# its calibration.  Used here as the shape of a reading that must pass.
REAL_MEAN = "0.270018"
REAL_STD = "0.198145"


def gate_probe_source():
    """The gate, with its one closing invocation removed."""
    source = gate_source()
    if MAIN_INVOCATION not in source:
        raise AssertionError(
            "verify_artifacts.sh no longer contains %r, so a sourced "
            "copy would run all of its checks" % MAIN_INVOCATION)
    return source.split(MAIN_INVOCATION)[0]


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


class SyntheticGateFixture(unittest.TestCase):
    """A miniature checkout, fake measuring tools, one check at a time.

    The sandbox lives in the ordinary temporary directory and NOTHING
    here skips for want of a privileged one: the tool paths are assigned
    to the check under test directly, so env.sh's ownership walk -- whose
    own coverage is test_env.py's -- is not in the way of measuring what
    the gate does with a reading.
    """

    @classmethod
    def setUpClass(cls):
        gate_probe_source()

    def setUp(self):
        self.base = os.path.realpath(
            tempfile.mkdtemp(prefix="blitzy_gate_"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.checkout = os.path.join(self.base, "checkout")
        self.tooling = os.path.join(self.checkout, "playthrough",
                                    "tooling")
        os.makedirs(self.tooling)
        os.makedirs(os.path.join(self.checkout, "data", "json", "ui"))
        os.makedirs(os.path.join(self.checkout, "src"))
        self.write(os.path.join(self.checkout, "Makefile"),
                   "# a marker, not the build system\n")
        self.write(os.path.join(self.checkout, "data", "json", "ui",
                                "sidebar.json"), "[]\n")
        self.write(os.path.join(self.checkout, "src", "path_info.cpp"),
                   "// a marker, not the engine\n")
        for name in ("env.sh", "verify_artifacts.sh"):
            shutil.copyfile(os.path.join(TOOLING, name),
                            os.path.join(self.tooling, name))
        self.gate = os.path.join(self.tooling, "verify_artifacts.sh")
        os.chmod(self.gate, 0o755)
        self.probe = os.path.join(self.tooling, PROBE_NAME)
        self.write(self.probe, gate_probe_source())
        self.dir = os.path.join(self.checkout, "playthrough")
        self.frames = os.path.join(self.dir, "frames")
        self.build = os.path.join(self.dir, "build")
        os.makedirs(self.frames)
        os.makedirs(os.path.join(self.build, "transitions"))
        self.movie = os.path.join(self.dir, "cata-play.mp4")
        self.movie_cc = os.path.join(self.dir, "cata-play-cc.mp4")
        # env.sh verifies its runtime root at mode 0700 and accepts a
        # nominated one, so the gate's scratch space lands here instead
        # of in the shared runtime directory.
        # BENEATH THE VERIFIED XDG ROOT, not inside the sandbox: env.sh
        # refuses any other pipeline runtime root.  See
        # _verified_runtime_root above for why, and note that it is still
        # private to this test and still nowhere near the repository.
        self.runtime = _verified_runtime_root()
        self.addCleanup(shutil.rmtree, self.runtime, True)
        self.bin = os.path.join(self.base, "bin")
        os.makedirs(self.bin)
        for name, body in FAKES.items():
            self.write(os.path.join(self.bin, name), body, mode=0o755)
        self.facts = os.path.join(self.base, "facts")
        self.write(self.facts, "")
        self.table = os.path.join(self.base, "image-table")
        self.write(self.table, "")

    # -- fixture plumbing --------------------------------------------

    def write(self, path, text, mode=None):
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def seed_facts(self, **values):
        """Write the facts a checker would have left behind."""
        self.write(self.facts, "".join(
            "%s=%s\n" % item for item in sorted(values.items())))

    def describe_image(self, name, mean, std, width=1920, height=1080):
        """Give one image a reading of its own."""
        with open(self.table, "a", encoding="utf-8") as handle:
            handle.write("%s|%s|%s|%s|%s\n"
                         % (name, mean, std, width, height))

    def captures(self, count, payload="a captured frame\n"):
        """Write `count` captures and return their names."""
        names = []
        for index in range(1, count + 1):
            name = "frame_%05d.png" % index
            self.write(os.path.join(self.frames, name), payload)
            names.append(name)
        return names

    def films(self):
        """Write both films, so a check that reads them finds them."""
        for path in (self.movie, self.movie_cc):
            self.write(path, "a film, as far as this gate can tell\n")

    def environment(self, **overrides):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env.get("PATH", "")
        env["PLAYTHROUGH_RUNTIME_DIR"] = self.runtime
        env["FAKE_IMAGE_TABLE"] = self.table
        env.setdefault("PLAYTHROUGH_ALLOW_EOL_PLATFORM",
                       "the gate is exercised over synthetic evidence")
        for name in ("PLAYTHROUGH_REPO_ROOT", "PLAYTHROUGH_DIR",
                     "PLAYTHROUGH_TOOLING_DIR", "PLAYTHROUGH_FRAMES_DIR",
                     "PLAYTHROUGH_BUILD_DIR",
                     "PLAYTHROUGH_TRANSITIONS_DIR",
                     "PLAYTHROUGH_USERDIR", "PLAYTHROUGH_MANIFEST",
                     "PLAYTHROUGH_TIMELINE", "PLAYTHROUGH_MOVIE",
                     "PLAYTHROUGH_MOVIE_CC", "PLAYTHROUGH_OBSERVATIONS",
                     "PLAYTHROUGH_VERIFY_PHASE"):
            env.pop(name, None)
        for name, value in overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = str(value)
        return env

    # -- driving one check -------------------------------------------

    def drive(self, snippet, phase=PHASE_ALL, samples=None,
              **environment):
        """Source the gate, run `snippet`, and report what was recorded.

        The tool variables are pointed at the fakes here rather than
        through resolve_tools, so the snippet's subject is the check and
        not the resolution.  Errexit stays ON, exactly as it is under
        main, so a snippet has to guard a check that legitimately returns
        non-zero -- which is how main calls those checks too.
        """
        program = (
            'set -uo pipefail\n'
            '. "%(probe)s"\n'
            'PHASE="%(phase)s"\n'
            '%(samples)s'
            'FFPROBE="%(bin)s/ffprobe"\n'
            'FFMPEG="%(bin)s/ffmpeg"\n'
            'CONVERT="%(bin)s/convert"\n'
            'IDENTIFY="%(bin)s/identify"\n'
            'COMPARE="%(bin)s/compare"\n'
            'open_scratch\n'
            'cp "%(facts)s" "${SCRATCH}/facts"\n'
            '%(snippet)s\n'
            'printf "COUNTERS=%%d %%d %%d\\n" "${PASSES}" '
            '"${FAILURES}" "${INFOS}"\n'
        ) % {
            "probe": self.probe,
            "phase": phase,
            "samples": ("LUMINANCE_SAMPLES=%s\n" % samples
                        if samples is not None else ""),
            "bin": self.bin,
            "facts": self.facts,
            "snippet": snippet,
        }
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", program],
            cwd=self.checkout, capture_output=True, timeout=300,
            env=self.environment(**environment))
        out = result.stdout.decode("utf-8", "replace")
        err = result.stderr.decode("utf-8", "replace")
        self.assertEqual(
            result.returncode, 0,
            msg="the harness itself failed:\n%s\n%s" % (out, err))
        return Recorded(out, err)

    # -- running the whole gate --------------------------------------

    def run_gate(self, *arguments, **environment):
        """Run the real gate over the synthetic tree, end to end."""
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", self.gate,
             *arguments],
            cwd=self.checkout, capture_output=True, timeout=900,
            env=self.environment(**environment))
        return (result.returncode,
                result.stdout.decode("utf-8", "replace"),
                result.stderr.decode("utf-8", "replace"))

    def git(self, *arguments):
        """Run real git in the sandbox checkout."""
        env = self.environment()
        env.update({
            "GIT_AUTHOR_NAME": "Blitzy Agent",
            "GIT_AUTHOR_EMAIL": "agent@blitzy.com",
            "GIT_COMMITTER_NAME": "Blitzy Agent",
            "GIT_COMMITTER_EMAIL": "agent@blitzy.com",
            "GIT_CONFIG_GLOBAL": self.write(
                os.path.join(self.base, "global.gitconfig"), ""),
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        result = subprocess.run(
            ["git", *arguments], cwd=self.checkout, env=env,
            capture_output=True, timeout=300)
        self.assertEqual(
            result.returncode, 0,
            msg="git %s failed: %s" % (" ".join(arguments),
                                       result.stderr.decode("utf-8",
                                                            "replace")))
        return result.stdout.decode("utf-8", "replace")


class Recorded(object):
    """The verdicts one harness run produced, ready to be asserted on."""

    VERDICT = re.compile(r"^(PASS|FAIL|INFO|WARN)  ?(.*)$")

    def __init__(self, out, err):
        self.out = out
        self.err = err
        self.verdicts = []
        for line in out.splitlines():
            match = self.VERDICT.match(line)
            if match:
                self.verdicts.append((match.group(1),
                                      match.group(2).strip()))
        self.passes, self.failures, self.infos = 0, 0, 0
        for line in out.splitlines():
            if line.startswith("COUNTERS="):
                numbers = line.partition("=")[2].split()
                self.passes = int(numbers[0])
                self.failures = int(numbers[1])
                self.infos = int(numbers[2])

    def names(self, kind=None):
        return [name for verdict, name in self.verdicts
                if kind is None or verdict == kind]

    def kind_of(self, fragment):
        """The verdict recorded for the check whose name carries
        `fragment`."""
        for verdict, name in self.verdicts:
            if fragment in name:
                return verdict
        return None

    def detail(self, fragment):
        """The whole verdict naming `fragment`, as one line of text.

        The matched line is included rather than only what follows it: a
        PASS or FAIL puts its observation on the lines beneath, but an
        INFO carries it on the line itself, and a reader of these
        assertions should not have to know which.
        """
        lines = self.out.splitlines()
        for index, line in enumerate(lines):
            if fragment in line and self.VERDICT.match(line):
                collected = [line.strip()]
                for following in lines[index + 1:]:
                    if self.VERDICT.match(following):
                        break
                    collected.append(following.strip())
                return " ".join(collected)
        return ""


class TestTheFrameCountFallsBackToPackets(SyntheticGateFixture):
    """Under -fps_mode vfr the decode is not always the reading.

    check_frame_count reads the end-to-end decode pass first; a pass
    that comes back with no count is not a broken film, it is the
    ordinary output of a variable-frame-rate encode, so the gate asks
    ffprobe for the PACKET count instead.  Neither reading was exercised
    anywhere before this: a fallback that had been dropped would have
    reported every correct film as unreadable, and one that answered
    from the wrong entry would have compared the plan against a number
    about something else.
    """

    def facts_for(self, images, entries=6, transitions=12):
        self.seed_facts(expected_images=images,
                        timeline_entries=entries,
                        transition_images=transitions)

    def test_the_decoded_count_is_used_when_the_container_gives_one(self):
        self.facts_for(18)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="18")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "PASS")
        self.assertIn("18 frames DECODED",
                      recorded.detail("one encoded frame per still"))

    def test_the_packet_count_answers_when_the_decode_does_not(self):
        """The fallback, measured: the decode pass reported nothing."""
        self.facts_for(18)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="",
                              FAKE_PROBE_STREAM_NB_READ_PACKETS="18")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "PASS")

    def test_the_repeated_final_entry_is_allowed_for(self):
        """The concat list repeats its last file, so N+1 is correct too.

        A gate that demanded exactly N would fail every film this
        pipeline produces.
        """
        self.facts_for(18)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="19")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "PASS")

    def test_a_shortfall_is_refused_and_both_numbers_are_named(self):
        self.facts_for(18)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="12")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "FAIL")
        detail = recorded.detail("one encoded frame per still")
        self.assertIn("12 frames decoded against 18 stills", detail)
        self.assertIn("captures were dropped", detail)

    def test_a_surplus_beyond_the_repeat_is_refused(self):
        self.facts_for(18)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="20")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "FAIL")

    def test_neither_reading_available_is_refused_not_assumed(self):
        """Unreadable is its own answer, and it is a failure.

        Reporting "0 frames" or passing on an absent reading would each
        be a verdict about nothing.
        """
        self.facts_for(18)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="",
                              FAKE_PROBE_STREAM_NB_READ_PACKETS="")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "FAIL")
        self.assertIn("both counts readable",
                      recorded.detail("one encoded frame per still"))

    def test_an_unreadable_plan_is_refused_too(self):
        """No expected_images fact means nothing to compare against."""
        self.seed_facts(timeline_entries=6)
        self.films()
        recorded = self.drive("check_frame_count",
                              FAKE_FFMPEG_FRAMES="18")
        self.assertEqual(recorded.kind_of("one encoded frame per still"),
                         "FAIL")

    def test_a_container_declaring_nothing_is_not_a_failure(self):
        """nb_frames is routinely N/A under vfr; the decode is the
        reading.

        The complementary half of the same fallback: check_frame_count
        tolerates a missing DECODE, and check_declared_frames_agree
        tolerates a missing DECLARATION.  A gate that failed on either
        would fail on every film this pipeline encodes.
        """
        self.films()
        recorded = self.drive(
            "check_declared_frames_agree",
            FAKE_FFMPEG_FRAMES="18",
            FAKE_PROBE_STREAM_NB_FRAMES="N/A")
        self.assertEqual(recorded.kind_of("decodes as many frames as it "
                                          "declares"), "PASS")
        self.assertIn("declares no nb_frames",
                      recorded.detail("decodes as many frames as it "
                                      "declares"))
        self.assertEqual(recorded.failures, 0)

    def test_a_declaration_that_outruns_the_decode_is_refused(self):
        """The truncation signature: the moov atom survives the cut."""
        self.films()
        recorded = self.drive(
            "check_declared_frames_agree",
            FAKE_FFMPEG_FRAMES="6",
            FAKE_PROBE_STREAM_NB_FRAMES="18")
        self.assertEqual(recorded.kind_of("decodes as many frames as it "
                                          "declares"), "FAIL")
        self.assertIn("6 decoded against 18 declared",
                      recorded.detail("decodes as many frames as it "
                                      "declares"))
        # Both films are measured, so both fail.
        self.assertEqual(recorded.failures, 2)


class TestABlankOrUniformFrameIsRefused(SyntheticGateFixture):
    """The one gate between a black film and a green report.

    Every other check on the film -- the counts, the geometry, the
    duration, the caption track -- passes just as happily on a container
    of black frames, which is exactly what SDL_VIDEODRIVER=dummy
    produces.  So the threshold is mean > 0 AND std > 0, and both halves
    are measured here rather than read off the source.
    """

    def frame(self, name="frame_00001.png"):
        return self.write(os.path.join(self.frames, name), "pixels\n")

    def check(self, path, **environment):
        return self.drive(
            'if check_one_frame_luminance "%s" "the frame"; then\n'
            '    printf "RETURNED=0\\n"\n'
            'else\n'
            '    printf "RETURNED=%%d\\n" "$?"\n'
            'fi\n'
            'printf "LAST_LUMINANCE=%%s\\n" "${LAST_LUMINANCE}"\n'
            % path, **environment)

    def test_a_real_reading_passes_and_is_remembered(self):
        recorded = self.check(self.frame(), FAKE_MEAN=REAL_MEAN,
                              FAKE_STD=REAL_STD)
        self.assertEqual(recorded.failures, 0)
        self.assertIn("RETURNED=0", recorded.out)
        self.assertIn("LAST_LUMINANCE=%s %s" % (REAL_MEAN, REAL_STD),
                      recorded.out)

    def test_the_dummy_driver_signature_is_refused(self):
        recorded = self.check(self.frame(), FAKE_MEAN="0", FAKE_STD="0")
        self.assertEqual(recorded.kind_of("real, non-blank image"),
                         "FAIL")
        detail = recorded.detail("real, non-blank image")
        self.assertIn("mean=0 std=0", detail)
        self.assertIn("SDL_VIDEODRIVER=dummy", detail)
        self.assertIn("1920x1080", detail)
        self.assertIn("RETURNED=1", recorded.out)

    def test_a_uniform_solid_colour_frame_is_refused(self):
        """std=0 alone, which a mean check on its own would pass.

        A grey rectangle is not a session, and the standard deviation is
        the only thing that says so.
        """
        recorded = self.check(self.frame(), FAKE_MEAN="0.5",
                              FAKE_STD="0")
        self.assertEqual(recorded.kind_of("real, non-blank image"),
                         "FAIL")
        self.assertIn("mean=0.5 std=0",
                      recorded.detail("real, non-blank image"))

    def test_a_very_dark_but_real_frame_still_passes(self):
        """Scientific notation is a number, and 3.78e-09 > 0.

        The shell cannot compare these at all, which is why the
        comparison is done in awk -- and why it is worth a test.
        """
        recorded = self.check(self.frame(), FAKE_MEAN="3.78e-09",
                              FAKE_STD="1.2e-05")
        self.assertEqual(recorded.failures, 0)
        self.assertIn("RETURNED=0", recorded.out)

    def test_an_unreadable_reading_is_refused_never_taken_as_zero(self):
        recorded = self.check(self.frame(), FAKE_CONVERT_STATUS="1")
        self.assertEqual(recorded.kind_of("real, non-blank image"),
                         "FAIL")
        self.assertIn("could not measure grayscale statistics",
                      recorded.detail("real, non-blank image"))

    def test_a_missing_frame_is_refused(self):
        recorded = self.check(os.path.join(self.frames, "absent.png"))
        self.assertEqual(recorded.kind_of("real, non-blank image"),
                         "FAIL")
        self.assertIn("no such file",
                      recorded.detail("real, non-blank image"))


class TestTheCaptureSweepFindsTheOneBadFrame(SyntheticGateFixture):
    """A hundred good captures do not answer for the hundred-and-first.

    check_sampled_captures reads every capture by default, and this is
    the check that has to name the frame that failed rather than report a
    tally.
    """

    def sweep(self, count, **environment):
        self.seed_facts(capture_count=count)
        return self.drive("check_sampled_captures", **environment)

    def test_a_clean_set_passes_both_verdicts(self):
        self.captures(5)
        recorded = self.sweep(5)
        self.assertEqual(recorded.kind_of("every capture is a real"),
                         "PASS")
        self.assertEqual(recorded.kind_of("X root's resolution"), "PASS")
        self.assertEqual(recorded.failures, 0)

    def test_one_black_capture_among_five_is_named(self):
        self.captures(5)
        self.describe_image("frame_00003.png", "0", "0")
        recorded = self.sweep(5)
        self.assertEqual(recorded.kind_of("every capture is a real"),
                         "FAIL")
        detail = recorded.detail("every capture is a real")
        self.assertIn("frame_00003.png", detail)
        self.assertIn("mean=0 std=0", detail)
        # The geometry verdict is a different property and is unaffected.
        self.assertEqual(recorded.kind_of("X root's resolution"), "PASS")

    def test_one_uniform_capture_among_five_is_named(self):
        self.captures(5)
        self.describe_image("frame_00002.png", "0.42", "0")
        recorded = self.sweep(5)
        self.assertEqual(recorded.kind_of("every capture is a real"),
                         "FAIL")
        self.assertIn("frame_00002.png",
                      recorded.detail("every capture is a real"))

    def test_a_window_sized_capture_fails_the_geometry_not_the_pixels(self):
        """1920x1072 is the game WINDOW; the root is 1920x1080.

        A capture of the window is a real, non-blank image -- so the
        luminance verdict passes and only the geometry one fails, which
        is what tells an operator which mistake they made.
        """
        self.captures(4)
        self.describe_image("frame_00002.png", REAL_MEAN, REAL_STD,
                            width=1920, height=1072)
        recorded = self.sweep(4)
        self.assertEqual(recorded.kind_of("every capture is a real"),
                         "PASS")
        self.assertEqual(recorded.kind_of("X root's resolution"), "FAIL")
        self.assertIn("1920x1072",
                      recorded.detail("X root's resolution"))

    def test_a_capture_that_cannot_be_read_is_not_counted_as_good(self):
        """The file the record names is not on disk at all."""
        self.captures(4)
        os.unlink(os.path.join(self.frames, "frame_00003.png"))
        recorded = self.sweep(4)
        self.assertEqual(recorded.kind_of("every capture is a real"),
                         "FAIL")

    def test_no_capture_count_fails_both_verdicts_rather_than_passing(self):
        recorded = self.drive("check_sampled_captures")
        self.assertEqual(recorded.kind_of("every capture is a real"),
                         "FAIL")
        self.assertEqual(recorded.kind_of("X root's resolution"), "FAIL")


class TestTheFilmIsMeasuredWhereTheSessionIs(SyntheticGateFixture):
    """The transition sampling exemption, and the black-film refusal.

    A transition is a fade to black, a title card and a fade in.  A frame
    extracted from inside one is a legitimately near-black picture, so an
    offset that lands there is moved past the window -- otherwise the
    luminance gate fails a correct film for showing exactly what it was
    asked to show.  The exemption is arithmetic, and it is measured here
    against a timeline that puts a window under one of the offsets.
    """

    def offsets(self, windows=(), **facts):
        """The offsets extract_offsets yields, with `windows` published.

        THE WINDOWS ARE WRITTEN WHERE GROUP 3 WRITES THEM, one per line
        in the scratch generation, because that is where the awk program
        reads them from.  They used to be joined into a single `awk -v`
        value, which is an argument on an exec line and so bounded by
        MAX_ARG_STRLEN -- about ten thousand transitions, which is a
        session this pipeline exists to allow.  A fixture that seeded a
        `transition_windows` fact instead would be measuring a data path
        the gate no longer has.
        """
        self.seed_facts(**facts)
        publish = ""
        if windows:
            publish = ('printf "%s\\n" ' +
                       " ".join('"%s"' % window for window in windows) +
                       ' >"$(windows_file)"\n')
        recorded = self.drive(
            publish +
            'while read -r offset; do\n'
            '    printf "OFFSET=%s\\n" "${offset}"\n'
            'done < <(extract_offsets)\n')
        return [line.partition("=")[2]
                for line in recorded.out.splitlines()
                if line.startswith("OFFSET=")]

    def test_the_offsets_are_the_documented_spread_of_the_total(self):
        """1 s, then a tenth, a half and 95 hundredths of the film."""
        self.assertEqual(self.offsets(timeline_total="200.000"),
                         ["1.000", "20.000", "100.000", "190.000"])

    def test_an_offset_inside_a_transition_window_is_moved_past_it(self):
        """The window brackets 100 s, so the mid-film probe steps out."""
        moved = self.offsets(windows=["99.000-101.000"],
                             timeline_total="200.000")
        self.assertNotIn("100.000", moved)
        self.assertIn("101.150", moved,
                      msg="the offset moves to just past the window")
        # Every other probe is untouched.
        for offset in ("1.000", "20.000", "190.000"):
            self.assertIn(offset, moved)

    def test_two_windows_in_a_row_are_both_stepped_over(self):
        moved = self.offsets(
            windows=["99.000-101.000", "101.100-102.000"],
            timeline_total="200.000")
        self.assertNotIn("100.000", moved)
        self.assertNotIn("101.150", moved)
        self.assertIn("102.150", moved)

    def test_no_window_leaves_every_offset_where_it_was(self):
        """A published-but-empty window list moves nothing.

        Group 3 writes the file whether or not the session held a
        transition, so the blank line it leaves has to be read as no
        window at all rather than as one at second zero -- which is what
        the awk program's NF guard is for.
        """
        plain = self.offsets(timeline_total="200.000")
        self.assertEqual(plain, self.offsets(windows=[""],
                                             timeline_total="200.000"))

    def test_no_offset_runs_past_the_end_of_the_film(self):
        """A probe beyond the last frame decodes nothing."""
        for total in ("0.500", "2.000", "34.500"):
            with self.subTest(total=total):
                for offset in self.offsets(timeline_total=total):
                    self.assertLessEqual(float(offset),
                                         float(total) - 0.25 + 1e-9)

    def test_an_unreadable_total_still_yields_the_historical_probe(self):
        self.assertEqual(self.offsets(), ["1"])

    def test_a_black_film_is_refused_at_every_offset(self):
        """Each offset is its own verdict, and the film gets no pass.

        The per-offset refusal is what names the second of the film that
        is black; the summary verdict is simply never recorded, which is
        why its absence is asserted as well.
        """
        self.films()
        self.seed_facts(timeline_total="10.000")
        recorded = self.drive("check_film_luminance", FAKE_MEAN="0",
                              FAKE_STD="0")
        refusal = "is a real, non-blank image"
        blank = [name for kind, name in recorded.verdicts
                 if kind == "FAIL" and refusal in name]
        counted = {}
        for label in ("playthrough/cata-play.mp4",
                      "playthrough/cata-play-cc.mp4"):
            counted[label] = len([name for name in blank
                                  if label in name])
            with self.subTest(film=label):
                self.assertGreater(
                    counted[label], 0,
                    msg="%s was not refused: %s" % (label, blank))
        # Both films are probed at the same offsets, so both are refused
        # the same number of times and nothing else was refused.
        self.assertEqual(len(set(counted.values())), 1)
        self.assertEqual(len(blank), sum(counted.values()))
        self.assertEqual(recorded.names("PASS"), [],
                         msg="a black film was given a passing verdict")
        self.assertIn("SDL_VIDEODRIVER=dummy",
                      recorded.detail("is a real, non-blank image"))

    def test_a_real_film_passes_and_the_readings_are_reported(self):
        self.films()
        self.seed_facts(timeline_total="10.000")
        recorded = self.drive("check_film_luminance", FAKE_MEAN=REAL_MEAN,
                              FAKE_STD=REAL_STD)
        self.assertEqual(recorded.kind_of("cata-play.mp4 are not blank"),
                         "PASS")
        self.assertIn("%s %s" % (REAL_MEAN, REAL_STD),
                      recorded.detail("cata-play.mp4 are not blank"))
        self.assertEqual(recorded.failures, 0)

    def test_a_film_that_cannot_be_decoded_there_is_refused(self):
        """A film that stops early cannot answer for its later
        seconds."""
        self.films()
        self.seed_facts(timeline_total="10.000")
        recorded = self.drive("check_film_luminance",
                              FAKE_FFMPEG_STATUS="1")
        self.assertEqual(recorded.kind_of("cata-play.mp4 are not blank"),
                         "FAIL")
        self.assertIn("no frame could be decoded",
                      recorded.detail("cata-play.mp4 are not blank"))


class TestThePhaseDecidesWhatIsMeasured(SyntheticGateFixture):
    """The gating, over one tree, rather than the classification.

    The source-level tests above prove every commit-shaped check SITS
    inside a tracking_phase branch.  These prove the branch does what it
    says: the same synthetic tree, two phases, and the eight checks
    either run or do not.
    """

    # The checks group 7 defers, named by the function that reports them.
    DEFERRED = ("check_save_tracked", "check_every_class_tracked",
                "check_tracked_frame_count", "check_nothing_uncommitted",
                "check_commit_order", "check_committed_vcs_rules",
                "check_lifecycle_checkpoints",
                "check_head_generation_checkpoints")

    def announced(self, phase):
        """Which deferred checks group 7 calls under `phase`.

        Each one is replaced by a stub that announces itself, so what is
        measured is the CALL rather than the check's own verdict.  The
        four unconditional checks in the group are replaced too, so a
        group that stopped calling one of those would be visible here as
        well.
        """
        stubs = "".join(
            '%s() { printf "RAN=%s\\n"; }\n' % (name, name)
            for name in self.DEFERRED + (
                "check_git_worktree", "check_git_identity",
                "check_nothing_ignored", "check_no_bytecode"))
        recorded = self.drive(stubs + "group_version_control\n",
                              phase=phase)
        return ([line.partition("=")[2]
                 for line in recorded.out.splitlines()
                 if line.startswith("RAN=")], recorded)

    def test_the_pre_commit_phase_calls_none_of_them(self):
        ran, recorded = self.announced(PHASE_PRE)
        for name in self.DEFERRED:
            with self.subTest(check=name):
                self.assertNotIn(name, ran)
        self.assertEqual(recorded.failures, 0)

    def test_the_pre_commit_phase_says_what_it_deferred(self):
        """A shorter report that reads exactly as green is the failure
        this guards against."""
        _, recorded = self.announced(PHASE_PRE)
        self.assertEqual(
            recorded.kind_of("properties of the COMMIT are deferred"),
            "INFO")
        detail = recorded.detail("properties of the COMMIT are deferred")
        for phrase in ("the save", "tracked", "the commit order",
                       "committed ignore rules"):
            self.assertIn(phrase, detail)

    def test_the_post_commit_phase_calls_every_one_of_them(self):
        ran, _ = self.announced(PHASE_POST)
        for name in self.DEFERRED:
            with self.subTest(check=name):
                self.assertIn(name, ran)

    def test_the_default_phase_calls_every_one_of_them(self):
        ran, _ = self.announced(PHASE_ALL)
        for name in self.DEFERRED:
            with self.subTest(check=name):
                self.assertIn(name, ran)

    def test_both_phases_run_the_four_unconditional_checks(self):
        for phase in (PHASE_PRE, PHASE_POST):
            with self.subTest(phase=phase):
                ran, _ = self.announced(phase)
                for name in ("check_git_worktree", "check_git_identity",
                             "check_nothing_ignored",
                             "check_no_bytecode"):
                    self.assertIn(name, ran)

    def test_a_commit_shaped_check_really_fails_before_the_commit(self):
        """Which is WHY they are deferred, and it is measured here.

        check_nothing_uncommitted asks a question only a commit can make
        true.  Run on an uncommitted tree it fails -- so a gate that ran
        it ahead of the checkpoint could never reach the checkpoint, and
        that is exactly what was measured on a real tree before the phase
        split existed.
        """
        self.git("init", "--quiet", "-b", "main", ".")
        self.captures(2)
        recorded = self.drive(
            'GIT="$(command -v git)"\n'
            'check_nothing_uncommitted\n', phase=PHASE_POST)
        self.assertEqual(recorded.kind_of("nothing under"), "FAIL")
        self.assertEqual(recorded.failures, 1)


class TestAFailureIsNotAReasonToStopMeasuring(SyntheticGateFixture):
    """The whole gate, over a tree that cannot pass it.

    A gate that abandoned the report at its first failure would answer
    one question and leave a hundred and nineteen unanswered -- and the
    operator would fix that one thing and run it again, and again.  So
    every group runs, every verdict is printed, the summary counts them,
    the machine block is published, and the exit status is taken exactly
    once at the end.
    """

    # Every group header the report must carry, in order.
    GROUPS = 10

    def setUp(self):
        super(TestAFailureIsNotAReasonToStopMeasuring, self).setUp()
        # Enough of a tree to reach every group: a git repository, a
        # couple of captures and both films.  Nothing here is a passing
        # artifact set, which is the point.
        self.git("init", "--quiet", "-b", "main", ".")
        self.captures(2)
        self.films()

    def report(self, *arguments, **environment):
        status, out, err = self.run_gate(
            "--samples", "2", *arguments, **environment)
        headers = re.findall(r"^=== (\d+)\. ", out, re.MULTILINE)
        fields = {}
        for line in out.splitlines():
            if line.startswith("VERIFY") and "=" in line:
                key, _, value = line.partition("=")
                fields[key] = value
        return status, out, err, headers, fields

    def test_every_group_still_reports_after_dozens_of_failures(self):
        status, out, _, headers, fields = self.report()
        self.assertEqual(status, EX_FAILED)
        self.assertEqual([int(number) for number in headers],
                         list(range(1, self.GROUPS + 1)))
        self.assertGreater(int(fields["VERIFY_FAILURES"]), 10)
        self.assertGreater(out.count("FAIL  "), 10)

    def test_the_last_group_is_reached_even_though_the_first_failed(self):
        """The inventory group is last, so its presence proves the run
        went all the way through."""
        _, out, _, _, _ = self.report()
        first = out.index("FAIL  ")
        last = out.index("=== 10.")
        self.assertLess(first, last,
                        msg="the run failed before its last group")
        self.assertIn("this report contains every check this gate "
                      "declares", out)

    def test_the_summary_and_the_machine_block_are_still_published(self):
        _, out, _, _, fields = self.report()
        self.assertIn("SUMMARY  ", out)
        self.assertEqual(fields["VERIFY"], "fail")
        for name in ("VERIFY_PHASE", "VERIFY_CHECKS",
                     "VERIFY_EXPECTED_CHECKS", "VERIFY_PASSES",
                     "VERIFY_FAILURES", "VERIFY_INFOS"):
            self.assertIn(name, fields)
        self.assertEqual(int(fields["VERIFY_CHECKS"]),
                         int(fields["VERIFY_PASSES"]) +
                         int(fields["VERIFY_FAILURES"]))

    def test_something_still_passes_so_the_run_kept_measuring(self):
        """A run that stopped early would report no later pass at all."""
        _, out, _, _, fields = self.report()
        self.assertGreater(int(fields["VERIFY_PASSES"]), 0)
        self.assertIn("PASS  ", out)

    def test_an_unresolvable_tool_is_a_failure_and_the_run_continues(self):
        """A missing measuring tool is a verdict, not an abort."""
        _, out, _, headers, fields = self.report(
            PLAYTHROUGH_FLAKE8="/nonexistent/flake8")
        self.assertEqual(len(headers), self.GROUPS)
        self.assertIn("FAIL  the new Python satisfies the repository's "
                      "own", out)
        self.assertGreater(int(fields["VERIFY_PASSES"]), 0)

    def test_each_phase_declares_and_measures_its_own_half(self):
        """Measured end to end over one tree, in both phases.

        POST-COMMIT IS THE SMALLER PHASE, and that is the whole point of
        the split.  It used to be a synonym for the entire audit, so the
        artifact properties -- every capture, every digest, the whole
        film -- were measured a second time after the commit for an
        answer the pre-commit phase had already given about the very same
        bytes.  Now each phase declares its own half and measures exactly
        that, and only the phase that defers anything says so.
        """
        _, pre_out, _, _, pre = self.report("--phase", PHASE_PRE)
        _, post_out, _, _, post = self.report("--phase", PHASE_POST)
        self.assertEqual(pre["VERIFY_PHASE"], PHASE_PRE)
        self.assertEqual(post["VERIFY_PHASE"], PHASE_POST)
        self.assertLess(int(post["VERIFY_EXPECTED_CHECKS"]),
                        int(pre["VERIFY_EXPECTED_CHECKS"]),
                        msg="post-commit must not re-measure the "
                            "artifacts the pre-commit phase measured")
        self.assertLess(int(post["VERIFY_CHECKS"]),
                        int(pre["VERIFY_CHECKS"]))
        # Only the pre-commit phase leaves anything unanswered, so only
        # it carries the deferral note.
        self.assertIn("properties of the COMMIT are deferred", pre_out)
        self.assertNotIn("properties of the COMMIT are deferred",
                         post_out)
        # And each phase is internally consistent: every verdict it
        # recorded is counted, in both of them.
        for phase, fields in ((PHASE_PRE, pre), (PHASE_POST, post)):
            with self.subTest(phase=phase):
                self.assertEqual(int(fields["VERIFY_CHECKS"]),
                                 int(fields["VERIFY_PASSES"]) +
                                 int(fields["VERIFY_FAILURES"]))
                self.assertGreater(int(fields["VERIFY_CHECKS"]), 0)

    def test_the_post_commit_phase_keeps_the_groups_own_numbers(self):
        """A shorter report numbers its groups the same as a full one.

        The post-commit phase runs four of the ten groups.  Numbering
        them 1 to 4 made the report incomparable with a full one and,
        worse, filed every verdict under another group's number -- so the
        inventory judged version control against group 2's declaration.
        The numbers are the groups' own, so the headers are a subset of
        the full run's rather than a renumbering of it.
        """
        _, out, _, headers, _ = self.report("--phase", PHASE_POST)
        numbers = [int(number) for number in headers]
        self.assertEqual(numbers, sorted(numbers))
        # The measuring environment, version control, hygiene and the
        # inventory: the four the phase declares, under their own
        # numbers.
        self.assertEqual(numbers, [1, 7, 9, 10])
        self.assertIn("=== 7. version control", out)

    def test_the_gate_writes_nothing_into_the_tree_it_judges(self):
        before = set()
        for directory, _, names in os.walk(self.dir):
            for name in names:
                before.add(os.path.join(directory, name))
        self.report()
        after = set()
        for directory, _, names in os.walk(self.dir):
            for name in names:
                after.add(os.path.join(directory, name))
        self.assertEqual(after, before)


class TestTheSyntheticHarnessTouchesNothingReal(SyntheticGateFixture):
    """The sandbox is the subject; the checkout must be untouched."""

    def test_the_sourceable_copy_lives_in_the_sandbox(self):
        self.assertTrue(self.probe.startswith(self.base))
        self.assertEqual(os.path.basename(self.probe), PROBE_NAME)
        self.assertFalse(os.path.basename(self.probe).startswith("."))

    def test_the_real_tooling_folder_is_unchanged_by_a_run(self):
        before = sorted(os.listdir(TOOLING))
        self.captures(2)
        self.seed_facts(capture_count=2)
        self.drive("check_sampled_captures")
        self.assertEqual(sorted(os.listdir(TOOLING)), before)

    def test_the_gate_under_test_is_the_real_file(self):
        """Byte for byte, so nothing here can pass against a rewrite."""
        with open(self.gate, "rb") as handle:
            copied = handle.read()
        with open(GATE, "rb") as handle:
            original = handle.read()
        self.assertEqual(copied, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
